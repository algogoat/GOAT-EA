"""Research-terminal launch policy (goatai#1885 PR E): a research MT5 yields the PC.

On 2026-10-05 every T2 seed-member start froze the owner PC for ~12.5 min: MT5 and its 24
local tester agents ran at Normal priority, the public publishers run at Task Scheduler
priority 7 (BelowNormal), and 24 Normal CPU-bound agents on 24 logical CPUs starved them for
the whole first generation. Banker never did, because its agents happen to inherit
BelowNormal. This module makes the low priority deliberate and enforced.

Only research launches come here: seed / catch-up / hold-up members and the first /config
start of a native batch, through ``studio_seed_process.ResearchLaunch`` (its ``start`` sets the
``research`` flag of ``WindowsSeedProcess.start``). Trading and monitor launches
(studio_demo_deploy, studio_onboarding, the demo agent's monitor restarts) never do, and no EA,
SET or service changes.

How a research MT5 starts:
1. The job ``Local\\GOAT-Research-<install hash>`` is created and configured first (a failure
   there refuses before any process exists).
2. MT5 is created with CREATE_SUSPENDED and its low priority class.
3. It is assigned to the job while suspended; the tester agents are its child processes, so
   they (and the EA's own MT5 relaunch chain) join the job automatically.
4. Only then is it resumed. Any failure in 3-4 terminates the suspended process (nothing ran)
   and refuses with a plain error; there is never a fallback launch at Normal.

Rules from Claude-Mac's approval (#1885 5997182052):
- JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is never set: the controller exits all the time and MT5
  must outlive it. Every set is read back and checked.
- The controller may itself run inside a job (desktop app, scheduled task): assignment uses
  Windows nested jobs; a refusal (ERROR_ACCESS_DENIED or anything else) refuses the launch.
- The job name is per terminal and session-local, never global or fixed.

Windows removes a job's *name* when its last handle closes, although the job and its limits
live on with MT5 inside. So an owner launch also starts a small keeper (``_keep``) that holds
the handle while the job has processes: it runs the CPU-cap staging and the idle_split agent
priority, keeps ``research-status`` able to read the live job, and exits 90 s after the job
empties. Without a keeper the launch still holds its priority and its first-stage cap.

A job handle is never NULL here: Windows would apply a NULL job call to the caller's own job.

Profiles live in ``<controller state>/research-launch.json`` (absent = customer default):
- customer: BelowNormal at creation, no job, no cap. ``keep_pc_responsive: true`` adds the job
  with a BelowNormal lock and a 50 % hard CPU cap.
- owner: Idle, locked by the job, and an owner-only hard CPU cap staged 17 % -> 33 % while
  every watched publisher cycle stays within its budget; one breach steps the cap back down,
  a second pauses the lane (seed: between members; native batch: batch-pause at a safe point).
- owner with ``agent_priority: idle_split`` (liveness fallback): MT5 at BelowNormal, every
  tester agent set to Idle per process (the job then carries no priority lock).
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import time
import uuid

# Process creation
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
PRIORITY_NAMES = {IDLE_PRIORITY_CLASS: 'idle', BELOW_NORMAL_PRIORITY_CLASS: 'below_normal',
                  NORMAL_PRIORITY_CLASS: 'normal'}
# Job objects
JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004
JOB_PREFIX = 'Local\\GOAT-Research-'
JOB_NAME_PATTERN = re.compile(r'Local\\GOAT-Research-[0-9a-f]{32}')

SCHEMA = 'goat-research-launch-v1'
POLICY_FILE = 'research-launch.json'
STATE_FOLDER = 'research-launch'
CUSTOMER_RESPONSIVE_PERCENT = 50
OWNER_STAGES_PERCENT = (17, 33)
PAUSE_AFTER_BREACHES = 2
GUARD_SECONDS = 10          # publisher budgets are evaluated at most this often
KEEPER_PERIOD_SECONDS = 2   # keeper loop: agent priority (idle_split)
KEEPER_HEARTBEAT_SECONDS = 10
KEEPER_IDLE_SECONDS = 90    # the keeper exits once the job has been empty this long
KEEPER_READY_SECONDS = 5
CYCLE_TAIL_BYTES = 256 * 1024
TESTER_LOG_TAIL_BYTES = 2 * 1024 * 1024    # research-status reads only the newest log's tail (light IO)
AGENT_START = re.compile(r'agent process started on (\S+)$')
CORE_SOURCE = re.compile(r'Core (\d+)$')
# MT5 build 6230 wording (terminal64 string table) for an agent that dropped out mid-run.
AGENT_LOSS = re.compile(r'connection (?:to \S+ )?lost|authorized tester agent \S+ disconnected|'
                        r'task rejected by tester agent|platform info was not received from tester agent|'
                        r'connect timeout', re.I)


class ResearchLaunchRefused(ValueError):
    """The research launch was refused; when a process had been created it was terminated suspended."""


# ---------------------------------------------------------------- policy

def _plain_bool(value, name):
    if type(value) is not bool:raise ValueError('research-launch.json: '+name+' must be true or false')
    return value


def validate_policy(value):
    """Strict normalized policy. A policy can only lower MT5's priority, never raise it."""
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise ValueError('research-launch.json needs schema '+SCHEMA)
    profile = value.get('profile')
    if profile == 'customer':
        extra = set(value) - {'schema', 'profile', 'keep_pc_responsive', 'updated_utc'}
        if extra:raise ValueError('research-launch.json: unknown customer keys '+', '.join(sorted(extra)))
        return dict(schema=SCHEMA, profile='customer',
                    keep_pc_responsive=_plain_bool(value.get('keep_pc_responsive', False), 'keep_pc_responsive'))
    if profile != 'owner':raise ValueError('research-launch.json: profile must be customer or owner')
    extra = set(value) - {'schema', 'profile', 'agent_priority', 'cpu_stages_percent', 'publishers', 'updated_utc'}
    if extra:raise ValueError('research-launch.json: unknown owner keys '+', '.join(sorted(extra)))
    agent_priority = value.get('agent_priority', 'idle')
    if agent_priority not in ('idle', 'idle_split'):
        raise ValueError('research-launch.json: agent_priority must be idle or idle_split')
    stages = value.get('cpu_stages_percent', list(OWNER_STAGES_PERCENT))
    if (not isinstance(stages, list) or not 1 <= len(stages) <= 4 or any(type(s) is not int or not 5 <= s <= 90 for s in stages)
            or any(b <= a for a, b in zip(stages, stages[1:]))):
        raise ValueError('research-launch.json: cpu_stages_percent must be 1-4 increasing whole percents from 5 to 90')
    publishers = value.get('publishers', [])
    if not isinstance(publishers, list) or len(publishers) > 4:
        raise ValueError('research-launch.json: publishers must be a list of at most 4')
    normalized = []
    for row in publishers:
        if (not isinstance(row, dict) or set(row) != {'label', 'cycle_log', 'max_seconds'} or not isinstance(row['label'], str)
                or not 1 <= len(row['label']) <= 40 or not isinstance(row['cycle_log'], str)
                or not PureWindowsPath(row['cycle_log']).is_absolute() or type(row['max_seconds']) is not int
                or not 5 <= row['max_seconds'] <= 900):
            raise ValueError('research-launch.json: each publisher needs label, an absolute cycle_log and max_seconds 5..900')
        normalized.append(dict(label=row['label'], cycle_log=row['cycle_log'], max_seconds=row['max_seconds']))
    if len({row['label'] for row in normalized}) != len(normalized):
        raise ValueError('research-launch.json: publisher labels must be unique')
    return dict(schema=SCHEMA, profile='owner', agent_priority=agent_priority, cpu_stages_percent=stages,
                publishers=normalized)


def load_policy(root):
    path = Path(root) / POLICY_FILE
    if not path.is_file():
        return dict(schema=SCHEMA, profile='customer', keep_pc_responsive=False, source='default')
    raw = path.read_bytes()
    if len(raw) > 64 * 1024:raise ValueError('research-launch.json exceeds 64 KB')
    return validate_policy(json.loads(raw.decode('utf-8-sig'))) | dict(source=str(path))


def effective(policy):
    """What a launch under ``policy`` does: creation class, job lock, cap, stages and keeper."""
    if policy['profile'] == 'owner':
        split = policy['agent_priority'] == 'idle_split'
        stages = list(policy['cpu_stages_percent'])
        return dict(profile='owner', creation_priority=BELOW_NORMAL_PRIORITY_CLASS if split else IDLE_PRIORITY_CLASS,
                    job=True, priority_lock=None if split else IDLE_PRIORITY_CLASS,
                    agent_priority=IDLE_PRIORITY_CLASS if split else None,
                    cpu_rate_percent=stages[0], stages=stages, publishers=list(policy['publishers']), keeper=True)
    responsive = policy['keep_pc_responsive']
    return dict(profile='customer', creation_priority=BELOW_NORMAL_PRIORITY_CLASS, job=responsive,
                priority_lock=BELOW_NORMAL_PRIORITY_CLASS if responsive else None, agent_priority=None,
                cpu_rate_percent=CUSTOMER_RESPONSIVE_PERCENT if responsive else None, stages=[], publishers=[],
                keeper=False)


def limit_flags(plan):
    """The job's limit flags: only the priority lock. KILL_ON_JOB_CLOSE and breakaway are never set."""
    return JOB_OBJECT_LIMIT_PRIORITY_CLASS if plan['priority_lock'] is not None else 0


def job_name(install):
    """Per terminal (its executable and data folder), session-local, not a fixed or global name."""
    key = '\0'.join(str(PureWindowsPath(install[k])).casefold() for k in ('terminal_executable', 'terminal_data_root'))
    return JOB_PREFIX + hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]


def write_policy(root, value):
    """Validate, then atomically replace ``research-launch.json``."""
    policy = validate_policy(value)
    stored = dict(policy) | dict(updated_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    _atomic_json(Path(root) / POLICY_FILE, stored)
    return load_policy(root)


def set_keep_pc_responsive(root, enabled):
    """Customer toggle. Refuses on an owner policy (the owner manages that file)."""
    current = load_policy(root)
    if current['profile'] != 'customer':
        raise ValueError('This installation uses the owner research-launch policy; change it with --policy')
    return write_policy(root, dict(schema=SCHEMA, profile='customer', keep_pc_responsive=_plain_bool(enabled, 'enabled')))


# ---------------------------------------------------------------- Win32

def _need(handle, what):
    # Windows applies a NULL job handle to the *calling* process's own job; never let that happen.
    if not handle:raise ValueError(what+' needs an open handle (a NULL job handle would target the caller\'s own job)')
    return handle


class Win32Jobs:
    """Thin kernel32 wrapper. Calls raise OSError(winerror) on failure, ValueError on a NULL handle."""

    def __init__(self):
        from ctypes import wintypes
        self.w = wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        H, B, D, P = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('Read', 'Write', 'Other', 'ReadT', 'WriteT', 'OtherT')]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', D), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', D),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', D), ('SchedulingClass', D)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        class CPU_RATE(ctypes.Structure):
            _fields_ = [('ControlFlags', D), ('Value', D)]

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
                        ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
                        ('TotalPageFaultCount', D), ('TotalProcesses', D), ('ActiveProcesses', D),
                        ('TotalTerminatedProcesses', D)]

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [('cb', D), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                        ('lpTitle', wintypes.LPWSTR), ('dwX', D), ('dwY', D), ('dwXSize', D), ('dwYSize', D),
                        ('dwXCountChars', D), ('dwYCountChars', D), ('dwFillAttribute', D), ('dwFlags', D),
                        ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', P),
                        ('hStdInput', H), ('hStdOutput', H), ('hStdError', H)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [('hProcess', H), ('hThread', H), ('dwProcessId', D), ('dwThreadId', D)]

        self.EXTENDED_LIMIT, self.CPU_RATE, self.ACCOUNTING = EXTENDED_LIMIT, CPU_RATE, ACCOUNTING
        self.STARTUPINFOW, self.PROCESS_INFORMATION = STARTUPINFOW, PROCESS_INFORMATION
        for name, args, result in (
                ('CreateJobObjectW', (P, wintypes.LPCWSTR), H), ('OpenJobObjectW', (D, B, wintypes.LPCWSTR), H),
                ('SetInformationJobObject', (H, ctypes.c_int, P, D), B),
                ('QueryInformationJobObject', (H, ctypes.c_int, P, D, ctypes.POINTER(D)), B),
                ('AssignProcessToJobObject', (H, H), B), ('IsProcessInJob', (H, H, ctypes.POINTER(B)), B),
                ('TerminateJobObject', (H, wintypes.UINT), B),
                ('CreateProcessW', (wintypes.LPCWSTR, wintypes.LPWSTR, P, P, B, D, P, wintypes.LPCWSTR,
                                    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)), B),
                ('ResumeThread', (H,), D), ('TerminateProcess', (H, wintypes.UINT), B),
                ('WaitForSingleObject', (H, D), D), ('GetExitCodeProcess', (H, ctypes.POINTER(D)), B),
                ('CloseHandle', (H,), B), ('OpenProcess', (D, B, D), H), ('GetPriorityClass', (H,), D),
                ('SetPriorityClass', (H, D), B), ('CreateMutexW', (P, B, wintypes.LPCWSTR), H),
                ('QueryFullProcessImageNameW', (H, D, wintypes.LPWSTR, ctypes.POINTER(D)), B)):
            function = getattr(k, name);function.argtypes = args;function.restype = result
            setattr(self, '_' + name, function)

    @staticmethod
    def _fail(what):
        code = ctypes.get_last_error()
        return OSError(None, what + ' failed (Windows error ' + str(code) + ')', None, code)

    def create_job(self, name):
        if not JOB_NAME_PATTERN.fullmatch(name):raise ValueError('Research job names are Local\\GOAT-Research-<hash>')
        ctypes.set_last_error(0)
        handle = self._CreateJobObjectW(None, name)
        if not handle:raise self._fail('CreateJobObjectW')
        return handle, ctypes.get_last_error() == 183           # ERROR_ALREADY_EXISTS

    def open_job(self, name, *, write=False, terminate=False):
        if not JOB_NAME_PATTERN.fullmatch(name):raise ValueError('Research job names are Local\\GOAT-Research-<hash>')
        # QUERY, plus SET_ATTRIBUTES to change the cap, plus TERMINATE (test cleanup only).
        handle = self._OpenJobObjectW(0x4 | (0x10 if write else 0) | (0x8 if terminate else 0), False, name)
        return handle or None

    def create_mutex(self, name):
        ctypes.set_last_error(0)
        handle = self._CreateMutexW(None, False, name)
        if not handle:raise self._fail('CreateMutexW')
        return handle, ctypes.get_last_error() == 183

    def active_processes(self, job):
        info = self.ACCOUNTING()
        if not self._QueryInformationJobObject(_need(job, 'active_processes'), 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise self._fail('QueryInformationJobObject')
        return int(info.ActiveProcesses)

    def set_limits(self, job, flags, priority_class):
        info = self.EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = flags
        info.BasicLimitInformation.PriorityClass = priority_class or 0
        if not self._SetInformationJobObject(_need(job, 'set_limits'), 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise self._fail('SetInformationJobObject(limits)')

    def query_limits(self, job):
        info = self.EXTENDED_LIMIT()
        if not self._QueryInformationJobObject(_need(job, 'query_limits'), 9, ctypes.byref(info), ctypes.sizeof(info), None):
            raise self._fail('QueryInformationJobObject(limits)')
        return int(info.BasicLimitInformation.LimitFlags), int(info.BasicLimitInformation.PriorityClass)

    def set_cpu_rate(self, job, percent):
        info = self.CPU_RATE()
        if percent is not None:
            info.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            info.Value = int(percent) * 100                   # CpuRate: 1/100 of a percent of the whole machine
        if not self._SetInformationJobObject(_need(job, 'set_cpu_rate'), 15, ctypes.byref(info), ctypes.sizeof(info)):
            raise self._fail('SetInformationJobObject(cpu rate)')

    def query_cpu_rate(self, job):
        info = self.CPU_RATE()
        if not self._QueryInformationJobObject(_need(job, 'query_cpu_rate'), 15, ctypes.byref(info), ctypes.sizeof(info), None):
            raise self._fail('QueryInformationJobObject(cpu rate)')
        if not info.ControlFlags & JOB_OBJECT_CPU_RATE_CONTROL_ENABLE:return None
        return int(info.Value) // 100

    def process_ids(self, job):
        _need(job, 'process_ids');count = 256
        while True:
            class LIST(ctypes.Structure):
                _fields_ = [('Assigned', self.w.DWORD), ('Listed', self.w.DWORD), ('Ids', ctypes.c_size_t * count)]
            info = LIST()
            if self._QueryInformationJobObject(job, 3, ctypes.byref(info), ctypes.sizeof(info), None):
                return [int(info.Ids[i]) for i in range(info.Listed)]
            if ctypes.get_last_error() != 234 or count >= 8192:raise self._fail('QueryInformationJobObject(process ids)')
            count *= 4                                       # ERROR_MORE_DATA

    def terminate_job(self, job):
        """Test cleanup only: end every process of one research job."""
        if not self._TerminateJobObject(_need(job, 'terminate_job'), 1):raise self._fail('TerminateJobObject')

    def create_suspended(self, command_line, cwd, flags):
        startup = self.STARTUPINFOW();startup.cb = ctypes.sizeof(startup)
        info = self.PROCESS_INFORMATION()
        buffer = ctypes.create_unicode_buffer(command_line)
        if not self._CreateProcessW(None, buffer, None, None, False, flags, None, cwd, ctypes.byref(startup), ctypes.byref(info)):
            raise self._fail('CreateProcessW')
        return info.hProcess, info.hThread, int(info.dwProcessId)

    def assign(self, job, process):
        if not self._AssignProcessToJobObject(_need(job, 'assign'), process):raise self._fail('AssignProcessToJobObject')

    def in_job(self, process, job):
        result = self.w.BOOL()
        if not self._IsProcessInJob(process, _need(job, 'in_job'), ctypes.byref(result)):raise self._fail('IsProcessInJob')
        return bool(result.value)

    def resume(self, thread):
        if self._ResumeThread(thread) == 0xFFFFFFFF:raise self._fail('ResumeThread')

    def terminate(self, process):
        self._TerminateProcess(process, 1)
        self._WaitForSingleObject(process, 5000)

    def exit_code(self, process):
        code = self.w.DWORD()
        if not self._GetExitCodeProcess(process, ctypes.byref(code)):raise self._fail('GetExitCodeProcess')
        return None if code.value == 259 else int(code.value)   # STILL_ACTIVE

    def close(self, handle):
        if handle:self._CloseHandle(handle)

    def process_info(self, pid):
        """(image path, priority class) of one process, or None when it cannot be opened."""
        handle = self._OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:return None
        try:
            size = self.w.DWORD(1024);buffer = ctypes.create_unicode_buffer(1024)
            image = buffer.value if self._QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None
            return image, int(self._GetPriorityClass(handle))
        finally:
            self._CloseHandle(handle)

    def set_priority(self, pid, priority_class):
        handle = self._OpenProcess(0x1000 | 0x200, False, pid)   # QUERY_LIMITED | SET_INFORMATION
        if not handle:return False
        try:
            return bool(self._SetPriorityClass(handle, priority_class))
        finally:
            self._CloseHandle(handle)


def _api(api):
    if api is not None:return api
    if os.name != 'nt':raise ResearchLaunchRefused('Research launches need Windows; nothing was started')
    return Win32Jobs()


# ---------------------------------------------------------------- launch

class LaunchedResearch:
    """Popen-like handle (pid, poll) of a research MT5 started by ``launch``."""

    def __init__(self, api, process, pid, record):
        self._api, self._process, self.pid, self.record = api, process, pid, record

    def poll(self):
        if self._process is None:return None
        return self._api.exit_code(self._process)

    def close(self):
        process, self._process = self._process, None
        if process:self._api.close(process)

    def __del__(self):
        try:self.close()
        except Exception:pass


def _atomic_json(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=1);stream.write('\n')
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path):
    try:
        path = Path(path)
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _history(root, event, **details):
    try:
        folder = Path(root) / STATE_FOLDER;folder.mkdir(parents=True, exist_ok=True)
        row = dict(at=datetime.now(timezone.utc).isoformat(timespec='seconds'), event=event, **details)
        with (folder / 'history.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(row, sort_keys=True, separators=(',', ':'), default=str) + '\n')
    except OSError:
        pass


def _job_summary(name, plan, flags):
    return dict(name=name, limit_flags=flags, priority_lock=PRIORITY_NAMES.get(plan['priority_lock']),
                kill_on_job_close=bool(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE), cpu_rate_percent=plan['cpu_rate_percent'])


def _configure_job(api, name, plan):
    """Create or reopen this terminal's job and set exactly our limits. Raises ResearchLaunchRefused."""
    try:
        job, existed = api.create_job(name)
    except OSError as error:
        raise ResearchLaunchRefused('GOAT could not create the research job for this MT5 ('+str(error)+'); nothing was started') from error
    try:
        if existed and api.active_processes(job) > 0:
            raise ResearchLaunchRefused('Another process already runs in this MT5\'s research job; nothing was started. '
                                        'Check that this MT5 and its tester agents are closed, then start again.')
        flags = limit_flags(plan)
        api.set_limits(job, flags, plan['priority_lock'])
        api.set_cpu_rate(job, plan['cpu_rate_percent'])
        observed, priority = api.query_limits(job)
        if observed & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE or observed != flags or (plan['priority_lock'] is not None
                                                                                 and priority != plan['priority_lock']):
            raise ResearchLaunchRefused('The research job did not keep the requested limits; nothing was started')
        if api.query_cpu_rate(job) != plan['cpu_rate_percent']:
            raise ResearchLaunchRefused('The research job did not keep the requested CPU cap; nothing was started')
        return job, flags
    except ResearchLaunchRefused:
        api.close(job);raise
    except OSError as error:
        api.close(job)
        raise ResearchLaunchRefused('GOAT could not set this MT5\'s research job limits ('+str(error)+'); nothing was started') from error


def launch_plan(api, plan, args, *, cwd, name, root, config=None, now=None, keeper=None):
    """Create, assign, record, resume. Never launches at Normal and never without the planned job."""
    now = time.time() if now is None else now
    job = None;flags = None
    if plan['job']:
        job, flags = _configure_job(api, name, plan)
    process = thread = None
    try:
        try:
            process, thread, pid = api.create_suspended(subprocess.list2cmdline([str(a) for a in args]), cwd,
                                                        CREATE_SUSPENDED | plan['creation_priority'] | CREATE_NO_WINDOW)
        except OSError as error:
            raise ResearchLaunchRefused('MT5 could not be created ('+str(error)+'); nothing was started') from error
        record = dict(schema=SCHEMA, launch_id=uuid.uuid4().hex, launched_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
                      launched_wall=now, pid=pid, profile=plan['profile'], creation_priority=PRIORITY_NAMES[plan['creation_priority']],
                      agent_priority=PRIORITY_NAMES.get(plan['agent_priority']), stages=plan['stages'],
                      config=str(config) if config is not None else None,
                      job=_job_summary(name, plan, flags) if job else None)
        stage = 'assign'
        try:
            if job:
                # Assigned while suspended: MT5 has not run one instruction outside the job.
                api.assign(job, process)
                if not api.in_job(process, job):raise OSError(None, 'process is not in the research job after assignment', None, 0)
            stage = 'record'
            _atomic_json(Path(root) / STATE_FOLDER / 'launch.json', record)
            if job and plan['stages'] and plan['publishers']:
                _atomic_json(Path(root) / STATE_FOLDER / 'guard.json', new_guard(record, plan, now))
            stage = 'resume'
            api.resume(thread)
        except BaseException as error:
            # Refuse: the suspended process never ran. No second launch, never at Normal.
            api.terminate(process)
            _history(root, 'refused', pid=pid, stage=stage, error=str(error)[:300], job=name)
            if not isinstance(error, OSError):raise
            if stage == 'assign':
                winerror = getattr(error, 'winerror', None) or error.errno
                denied = (' (access denied: the GOAT process that starts MT5 runs inside a job that does not allow it)'
                          if winerror == 5 else '')
                raise ResearchLaunchRefused('MT5 was not started: it could not be placed in its low-priority research job'
                                            + denied + '. GOAT never starts research MT5 at normal priority. Nothing ran; '
                                            'report this with research-status.') from error
            raise ResearchLaunchRefused('MT5 was not started: GOAT could not '+('record the launch' if stage == 'record' else
                                        'resume it')+' ('+str(error)[:160]+'). Nothing ran.') from error
        if job and plan['keeper']:
            # Hold the job's name past this controller's exit (see the module notes). A keeper that
            # does not start leaves MT5 at its locked priority and first-stage cap.
            record['keeper'] = (keeper or start_keeper)(root, name, now=now)
            try:_atomic_json(Path(root) / STATE_FOLDER / 'launch.json', record)
            except OSError:pass
        _history(root, 'launched', pid=pid, profile=plan['profile'], job=name, creation_priority=record['creation_priority'],
                 cpu_rate_percent=plan['cpu_rate_percent'], keeper=record.get('keeper'))
        launched = LaunchedResearch(api, process, pid, record);process = None
        return launched
    finally:
        if thread:api.close(thread)
        if process:api.close(process)
        if job:api.close(job)                   # the job lives on with MT5 (no KILL_ON_JOB_CLOSE)


def launch(controller, args, *, cwd, config=None, api=None, now=None, keeper=None):
    """The research launch behind studio_seed_process.ResearchLaunch (the research flag of its start)."""
    try:
        policy = load_policy(controller.root)
    except (OSError, ValueError) as error:
        raise ResearchLaunchRefused('research-launch.json is not valid ('+str(error)+'); nothing was started. '
                                    'Fix or remove it, then start again.') from error
    plan = effective(policy)
    return launch_plan(_api(api), plan, args, cwd=cwd, name=job_name(controller.install), root=controller.root,
                       config=config, now=now, keeper=keeper)


# ---------------------------------------------------------------- keeper

def keeper_command(root, name):
    executable = Path(sys.executable)
    windowless = executable.with_name('pythonw.exe')
    return [str(windowless if windowless.is_file() else executable), '-B', str(Path(__file__).resolve()),
            '_keep', '--root', str(Path(root).resolve()), '--job', name]


def start_keeper(root, name, *, now=None, wait=KEEPER_READY_SECONDS):
    """Start (or reuse) the job's keeper and wait for its heartbeat. Returns a summary; never raises."""
    now = time.time() if now is None else now
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    pid = None;error = None
    for extra in (CREATE_BREAKAWAY_FROM_JOB, 0):        # leave the controller's own job when it allows that
        try:
            pid = subprocess.Popen(keeper_command(root, name), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, close_fds=True,
                                   creationflags=flags | extra | getattr(subprocess, 'CREATE_NO_WINDOW', 0)).pid
            break
        except OSError as exc:
            error = str(exc)[:200]
    if pid is None:return dict(state='not_started', error=error)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        beat = _read_json(Path(root) / STATE_FOLDER / 'keeper.json')
        # A keeper that already holds this job (the previous member's) counts: its heartbeat is <= 10 s old.
        if (beat and beat.get('job') == name and beat.get('state') == 'holding'
                and (beat.get('heartbeat_wall') or 0) >= now - KEEPER_HEARTBEAT_SECONDS - 2):
            return dict(state='holding', pid=beat.get('pid'), spawned_pid=pid)
        time.sleep(.1)
    return dict(state='unconfirmed', spawned_pid=pid)


def keep(root, name, *, api=None, clock=time.time, sleep=time.sleep, idle_seconds=KEEPER_IDLE_SECONDS,
         period=KEEPER_PERIOD_SECONDS, max_loops=None):
    """Keeper loop: hold the job handle while the job has processes; run the owner guard pass."""
    api = _api(api);root = Path(root)
    mutex, existed = api.create_mutex(name + '-keeper')
    try:
        if existed:return 0                     # another keeper already holds this job
        job = api.open_job(name, write=True)
        if job is None:return 2
        idle_since = None;loops = 0;beat_wall = None;beat_active = None
        try:
            while max_loops is None or loops < max_loops:
                loops += 1;now = clock()
                active = api.active_processes(job)
                if beat_wall is None or now - beat_wall >= KEEPER_HEARTBEAT_SECONDS or (active == 0) != (beat_active == 0):
                    # A small heartbeat, not every loop: the 2 s loop is for idle_split agents only.
                    _atomic_json(root / STATE_FOLDER / 'keeper.json', dict(schema=SCHEMA, pid=os.getpid(), job=name, state='holding',
                                                                           heartbeat_wall=now, active_processes=active))
                    beat_wall, beat_active = now, active
                if active == 0:
                    idle_since = now if idle_since is None else idle_since
                    if now - idle_since >= idle_seconds:return 0
                else:
                    idle_since = None
                    guard_pass(root, name, api, job, now)
                sleep(period)
            return 0
        finally:
            api.close(job)
            beat = _read_json(root / STATE_FOLDER / 'keeper.json') or {}
            if beat.get('pid') == os.getpid():
                try:_atomic_json(root / STATE_FOLDER / 'keeper.json', beat | dict(state='stopped', stopped_wall=clock()))
                except OSError:pass
    finally:
        api.close(mutex)


# ---------------------------------------------------------------- owner CPU-cap staging

def new_guard(record, plan, now):
    ms = int(now * 1000)
    return dict(schema=SCHEMA, launch_id=record['launch_id'], job_name=record['job']['name'], stages=plan['stages'],
                stage=0, cpu_rate_percent=plan['stages'][0], launch_ms=ms, stage_since_ms=ms, judged=[],
                ok_since_stage={}, breaches=[], paused=False, last_eval_wall=None, history=[])


def read_cycles(path, *, tail_bytes=CYCLE_TAIL_BYTES):
    """Publisher cycles from a cycle-identities.jsonl tail: [{started_ms, ended_ms|None}]. Raises OSError."""
    with open(path, 'rb') as stream:
        stream.seek(0, 2);size = stream.tell();stream.seek(max(0, size - tail_bytes))
        raw = stream.read()
    lines = raw.decode('utf-8', 'replace').splitlines()
    if size > tail_bytes and lines:lines = lines[1:]      # first line may be cut
    cycles = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or type(row.get('startedAt')) is not int:continue
        key = (row.get('pid'), row['startedAt'])
        if row.get('event') == 'START':
            cycles.setdefault(key, dict(started_ms=row['startedAt'], ended_ms=None))
        elif row.get('event') == 'END' and type(row.get('endedAt')) is int:
            cycles[key] = dict(started_ms=row['startedAt'], ended_ms=row['endedAt'])
    return sorted(cycles.values(), key=lambda c: c['started_ms'])


def step(guard, publishers, cycles, now_ms):
    """Pure staging decision. Returns (guard, event) with event in None|'widen'|'breach'|'pause'.

    - A cycle over its budget is a breach, also while it still runs (a starved cycle can take
      12 min to log END). Cycles that started up to one budget before the launch still count.
    - One breach steps the cap down one stage (never below the first); the second pauses the lane.
    - The cap widens one stage only when every publisher finished a cycle in budget that
      started after the current stage was applied, with no breach since.
    """
    g = json.loads(json.dumps(guard))
    if g['paused']:return g, None
    judged = set(g['judged'])
    breach = None
    for publisher in publishers:
        label, budget = publisher['label'], publisher['max_seconds'] * 1000
        for cycle in cycles.get(label) or []:
            key = label + '|' + str(cycle['started_ms'])
            if key in judged or cycle['started_ms'] < g['launch_ms'] - budget:continue
            elapsed = (cycle['ended_ms'] if cycle['ended_ms'] is not None else now_ms) - cycle['started_ms']
            if elapsed > budget:
                judged.add(key)
                breach = breach or dict(publisher=label, started_ms=cycle['started_ms'], seconds=round(elapsed / 1000),
                                        running=cycle['ended_ms'] is None)
            elif cycle['ended_ms'] is not None:
                judged.add(key)
                if cycle['started_ms'] >= g['stage_since_ms']:g['ok_since_stage'][label] = True
    g['judged'] = sorted(judged)[-400:]
    event = None
    if breach:
        g['breaches'].append(breach)
        g['stage'] = max(0, g['stage'] - 1)
        event = 'breach'
        if len(g['breaches']) >= PAUSE_AFTER_BREACHES:
            g['paused'] = True;g['stage'] = 0;event = 'pause'
        g['stage_since_ms'] = now_ms;g['ok_since_stage'] = {}
    elif (publishers and g['stage'] < len(g['stages']) - 1
          and all(g['ok_since_stage'].get(p['label']) for p in publishers)):
        g['stage'] += 1;g['stage_since_ms'] = now_ms;g['ok_since_stage'] = {};event = 'widen'
    g['cpu_rate_percent'] = g['stages'][g['stage']]
    if event:g['history'] = (g['history'] + [dict(at_ms=now_ms, event=event, cpu_rate_percent=g['cpu_rate_percent'])])[-50:]
    return g, event


def enforce_agent_priority(api, job, priority_class):
    """idle_split: set every tester agent in the job to ``priority_class``; MT5 itself is left as is."""
    changed = 0
    for pid in api.process_ids(job):
        info = api.process_info(pid)
        if not info or not info[0] or PureWindowsPath(info[0]).name.lower() != 'metatester64.exe':continue
        if info[1] != priority_class and api.set_priority(pid, priority_class):changed += 1
    return changed


def guard_pass(root, name, api, job, now):
    """One keeper pass over a live job: idle_split agent priority, then the owner CPU-cap staging.
    The keeper is the only writer of guard.json. Never raises; returns an observation."""
    root = Path(root)
    try:
        plan = effective(load_policy(root))
        if plan['profile'] != 'owner':return None
        observation = {}
        if plan['agent_priority'] is not None:
            observation['agents_lowered'] = enforce_agent_priority(api, job, plan['agent_priority'])
        record = _read_json(root / STATE_FOLDER / 'launch.json')
        guard = _read_json(root / STATE_FOLDER / 'guard.json')
        if not record or not guard or guard.get('launch_id') != record.get('launch_id') or guard.get('job_name') != name:
            return observation
        if guard.get('last_eval_wall') is not None and now - guard['last_eval_wall'] < GUARD_SECONDS:
            return observation | dict(cpu_rate_percent=guard['cpu_rate_percent'], paused=guard['paused'])
        cycles, errors = {}, []
        for publisher in plan['publishers']:
            try:
                cycles[publisher['label']] = read_cycles(publisher['cycle_log'])
            except OSError as error:
                errors.append(publisher['label'] + ': ' + str(error)[:120])   # no data: never widens
        updated, event = step(guard, plan['publishers'], cycles, int(now * 1000))
        updated['last_eval_wall'] = now;updated['publisher_read_errors'] = errors
        if event:api.set_cpu_rate(job, updated['cpu_rate_percent'])
        _atomic_json(root / STATE_FOLDER / 'guard.json', updated)
        if event:_history(root, event, cpu_rate_percent=updated['cpu_rate_percent'],
                          breach=updated['breaches'][-1] if event in ('breach', 'pause') else None)
        return observation | dict(cpu_rate_percent=updated['cpu_rate_percent'], event=event, paused=updated['paused'])
    except Exception as error:                 # the guard never breaks the keeper loop
        _history(root, 'guard_error', error=str(error)[:300])
        return dict(error=str(error)[:300])


def pause_wanted(controller):
    """True when the owner guard of this terminal's current research launch paused the lane
    (two publisher budget breaches). Read-only; the lane driver requests its own pause."""
    root = getattr(controller, 'root', None);install = getattr(controller, 'install', None)
    if root is None or not isinstance(install, dict):return False
    try:
        record = _read_json(Path(root) / STATE_FOLDER / 'launch.json')
        guard = _read_json(Path(root) / STATE_FOLDER / 'guard.json')
        return bool(record and guard and guard.get('launch_id') == record.get('launch_id')
                    and guard.get('job_name') == job_name(install) and guard.get('paused') is True)
    except (KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------- observation (research-status, T3 proof)

def _read_utf16_tail(path, limit):
    with open(path, 'rb') as stream:
        stream.seek(0, 2);size = stream.tell()
        start = max(0, size - limit);start -= start % 2
        stream.seek(start);raw = stream.read()
    if raw.startswith(b'\xff\xfe'):raw = raw[2:]
    lines = raw.decode('utf-16-le', 'replace').splitlines()
    return lines[1:] if start and lines else lines


def parse_tester_log(lines):
    """The newest local-agent fan-out in a terminal Tester log: agents started and agents lost since."""
    block = None;latest = None
    for index, line in enumerate(lines):
        parts = line.split('\t')
        if len(parts) < 5:continue
        source, message = parts[3], parts[4].strip()
        core = CORE_SOURCE.match(source)
        if core and AGENT_START.match(message):
            number = int(core.group(1))
            if block is None or number == block['first']:
                # A new fan-out (after a start line, or the first core starting again).
                block = dict(first=number, cores=set(), restarts=0, started=parts[2], index=index)
                latest = block
            elif number in block['cores']:
                block['restarts'] += 1          # one agent restarted inside the same run
            block['cores'].add(number)
        elif source == 'Tester' and ('optimization started' in message or 'testing of' in message):
            block = None
    if latest is None:return None
    losses = [line.split('\t')[4].strip() for line in lines[latest['index']:]
              if len(line.split('\t')) >= 5 and AGENT_LOSS.search(line.split('\t')[4])]
    return dict(enabled_mt5_workers=len(latest['cores']), agents_started_local_time=latest['started'],
                agent_restarts=latest['restarts'], agent_losses=len(losses), agent_loss_lines=losses[-5:])


def agent_observation(install, *, since_wall=None):
    """Read the selected terminal's newest Tester log; None when there is no fan-out since ``since_wall``."""
    folder = Path(install['terminal_data_root']) / 'Tester' / 'logs'
    try:
        logs = sorted((p for p in folder.glob('*.log') if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in logs[:2]:
        try:
            if since_wall is not None and path.stat().st_mtime < since_wall:return None
            observed = parse_tester_log(_read_utf16_tail(path, TESTER_LOG_TAIL_BYTES))
        except OSError:
            continue
        if observed:return observed | dict(source=str(path))
    return None


def status(install, root, *, now=None, api=None):
    """research-status block: policy, last launch, live job limits, owner guard and real agent count. Read-only."""
    now = time.time() if now is None else now
    result = dict(enabled_mt5_workers=None, agent_count_source=None)
    try:
        policy = load_policy(root)
    except (OSError, ValueError) as error:
        return result | dict(policy='invalid', plain='research-launch.json is not valid: '+str(error)[:200]+
                             '. The next research launch refuses until it is fixed or removed.')
    plan = effective(policy)
    result.update(profile=plan['profile'], keep_pc_responsive=policy.get('keep_pc_responsive'),
                  creation_priority=PRIORITY_NAMES[plan['creation_priority']],
                  agent_priority=PRIORITY_NAMES.get(plan['agent_priority']) or PRIORITY_NAMES.get(plan['priority_lock'])
                  or PRIORITY_NAMES[plan['creation_priority']],
                  job_planned=plan['job'], cpu_cap_percent_planned=plan['cpu_rate_percent'],
                  publisher_budgets=[dict(label=p['label'], max_seconds=p['max_seconds']) for p in plan['publishers']],
                  plain=_plain(plan))
    folder = Path(root) / STATE_FOLDER
    record = _read_json(folder / 'launch.json')
    result['last_launch'] = None if not record else {k: record.get(k) for k in ('launched_utc', 'pid', 'profile', 'creation_priority',
                                                                               'agent_priority', 'job', 'keeper')}
    live = None
    if record and record.get('job'):
        live = dict(state='unavailable', plain='The live job can be read only while its keeper (owner) or the launching '
                    'GOAT process holds it; the limits shown in last_launch were set and read back at launch.')
        try:
            if os.name == 'nt' or api is not None:
                api = _api(api);handle = api.open_job(record['job']['name'])
                if handle is not None:
                    try:
                        flags, priority = api.query_limits(handle)
                        live = dict(state='running', active_processes=api.active_processes(handle), limit_flags=flags,
                                    priority_lock=PRIORITY_NAMES.get(priority) if flags & JOB_OBJECT_LIMIT_PRIORITY_CLASS else None,
                                    kill_on_job_close=bool(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
                                    cpu_rate_percent=api.query_cpu_rate(handle))
                    finally:
                        api.close(handle)
        except (OSError, ValueError) as error:
            live = dict(state='unknown', error=str(error)[:200])
    result['job'] = live
    beat = _read_json(folder / 'keeper.json')
    result['keeper'] = None if not beat else dict(state=beat.get('state'), pid=beat.get('pid'),
                                                   heartbeat_age_seconds=round(now - beat['heartbeat_wall'])
                                                   if type(beat.get('heartbeat_wall')) in (int, float) else None)
    guard = _read_json(folder / 'guard.json')
    if guard and record and guard.get('launch_id') == record.get('launch_id'):
        result['guard'] = dict(stage=guard['stage'], stages=guard['stages'], cpu_rate_percent=guard['cpu_rate_percent'],
                               breaches=guard['breaches'], paused=guard['paused'],
                               publisher_read_errors=guard.get('publisher_read_errors', []))
    else:
        result['guard'] = None
    if record:
        agents = agent_observation(install, since_wall=record.get('launched_wall'))
        if agents:
            result.update(enabled_mt5_workers=agents['enabled_mt5_workers'], agent_count_source='tester_log',
                          agents=agents)
    return result


def _plain(plan):
    if plan['profile'] == 'owner':
        if plan['agent_priority'] is not None:
            return ('Owner research: MT5 starts at below-normal priority and every tester agent is set to idle, inside a '
                    'per-terminal job with a CPU cap that starts at %d%% and widens only while the publishers keep their budget.'
                    % plan['cpu_rate_percent'])
        return ('Owner research: MT5 and its tester agents run at idle priority, locked by a per-terminal job, with a CPU '
                'cap that starts at %d%% and widens only while the publishers keep their budget.' % plan['cpu_rate_percent'])
    if plan['job']:
        return ('Keep my PC responsive is on: research MT5 runs at below-normal priority and its tester agents together '
                'use at most %d%% of this PC\'s processor.' % plan['cpu_rate_percent'])
    return ('Research MT5 runs at below-normal priority, so your other programs come first; it still uses all spare '
            'processor time. Turn on keep my PC responsive to cap it at %d%%.' % CUSTOMER_RESPONSIVE_PERCENT)


# ---------------------------------------------------------------- owner T3 proof (never run by tests)

def passes_per_minute(agent_log_lines, *, since_local=None, until_local=None):
    """Count finished passes ('... passed in h:mm:ss') in tester agent logs between two local HH:MM:SS times."""
    times = []
    for line in agent_log_lines:
        parts = line.split('\t')
        if len(parts) >= 5 and 'passed in' in parts[4] and 'OnTester result' in parts[4]:
            stamp = parts[2][:8]
            if (since_local is None or stamp >= since_local) and (until_local is None or stamp <= until_local):times.append(stamp)
    if len(times) < 2:return dict(passes=len(times), passes_per_minute=None)
    def seconds(text):
        h, m, s = (int(x) for x in text.split(':'));return h * 3600 + m * 60 + s
    span = max(1, seconds(max(times)) - seconds(min(times)))
    return dict(passes=len(times), passes_per_minute=round(len(times) * 60 / span, 2), first=min(times), last=max(times))


def publisher_window(publishers, since_wall, until_wall):
    """Every watched publisher cycle that overlaps [since, until]: durations and budget breaches."""
    rows = []
    for publisher in publishers:
        try:
            cycles = read_cycles(publisher['cycle_log'], tail_bytes=4 * 1024 * 1024)
        except OSError as error:
            rows.append(dict(label=publisher['label'], error=str(error)[:200]));continue
        inside = [c for c in cycles if c['started_ms'] <= until_wall * 1000 and (c['ended_ms'] or until_wall * 1000) >= since_wall * 1000]
        durations = [round(((c['ended_ms'] or until_wall * 1000) - c['started_ms']) / 1000) for c in inside]
        rows.append(dict(label=publisher['label'], budget_seconds=publisher['max_seconds'], cycles=len(inside),
                         max_seconds=max(durations) if durations else None,
                         over_budget=sum(d > publisher['max_seconds'] for d in durations)))
    return rows


def _local(wall):
    return datetime.fromtimestamp(wall).strftime('%H:%M:%S')


def proof_report(install, *, since_wall, until_wall, agents_root=None):
    """Owner T3 A/B summary for one research launch: status, real agents, losses, passes/min, publishers."""
    root = Path(install['controller_state_root'])
    plan = effective(load_policy(root))
    report = dict(status=status(install, root), window=dict(since_utc=datetime.fromtimestamp(since_wall, timezone.utc).isoformat(),
                                                             until_utc=datetime.fromtimestamp(until_wall, timezone.utc).isoformat()))
    folder = Path(agents_root) if agents_root else (Path(os.environ.get('APPDATA', '')) / 'MetaQuotes' / 'Tester'
                                                    / Path(install['terminal_data_root']).name)
    lines = []
    for log in sorted(folder.glob('Agent-*/logs/*.log')):
        try:
            if log.stat().st_mtime >= since_wall:lines += _read_utf16_tail(log, 32 * 1024 * 1024)
        except OSError:
            continue
    report['passes'] = passes_per_minute(lines, since_local=_local(since_wall), until_local=_local(until_wall))
    report['agent_log_losses'] = sum(1 for line in lines if len(line.split('\t')) >= 5 and AGENT_LOSS.search(line.split('\t')[4]))
    report['publishers'] = publisher_window(plan['publishers'], since_wall, until_wall)
    return report


def _proof_controller(installation):
    from types import SimpleNamespace
    from studio_installation import load_installation
    install = load_installation(installation, verify_binary=False)
    return SimpleNamespace(install=install, root=Path(install['controller_state_root']))


def _main(argv=None):
    parser = argparse.ArgumentParser(description='GOAT research-launch keeper and owner proof tools')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('_keep');p.add_argument('--root', type=Path, required=True);p.add_argument('--job', required=True)
    p = sub.add_parser('proof-status');p.add_argument('--installation', type=Path, required=True)
    # Owner T3 proof only (docs/research-launch/T3-PROOF.md): one research launch of one tester INI.
    p = sub.add_parser('proof-launch');p.add_argument('--installation', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p = sub.add_parser('proof-report');p.add_argument('--installation', type=Path, required=True)
    p.add_argument('--since-wall', type=float, required=True);p.add_argument('--until-wall', type=float, required=True)
    p.add_argument('--agents-root', type=Path)
    args = parser.parse_args(argv)
    if args.command == '_keep':
        if not JOB_NAME_PATTERN.fullmatch(args.job):return 2
        return keep(args.root, args.job)
    controller = _proof_controller(args.installation)
    if args.command == 'proof-status':
        result = status(controller.install, controller.root)
    elif args.command == 'proof-launch':
        from studio_seed_process import ResearchLaunch, WindowsSeedProcess
        identity = ResearchLaunch(WindowsSeedProcess(controller)).start(args.config.resolve())
        result = dict(process=identity, launch=_read_json(controller.root / STATE_FOLDER / 'launch.json'))
    else:
        result = proof_report(controller.install, since_wall=args.since_wall, until_wall=args.until_wall,
                              agents_root=args.agents_root)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(_main())
