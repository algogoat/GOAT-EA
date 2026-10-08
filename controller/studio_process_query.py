"""Read-only Windows inventory queries (WMI through PowerShell) that survive a transient stall.

``Get-CimInstance Win32_Process`` normally answers in about 0.3 s, but WMI stalls intermittently on
loaded PCs. A single 20 s ``check_output`` then raised ``TimeoutExpired`` and killed whichever driver
asked (T2 and Banker, 2026-10-05, goatai#1885). Every inventory call site uses ``powershell_text``:

* up to ``ATTEMPTS`` tries, each with its own timeout, with ``PAUSES`` between them (worst case about
  100 s), and only for ``TimeoutExpired`` and ``CalledProcessError`` (a CIM error under
  ``$ErrorActionPreference='Stop'``). Each pause is jittered by up to ``JITTER`` either way, so two GOAT
  drivers hit by the same stall (it clusters at an MT5 launch) do not retry in lockstep. That full
  policy is for one-shot inventories that gate a launch or close. A caller with its own loop or
  deadline (status reads, polls) passes ``budget`` (seconds, at most ``POLL_BUDGET`` for pollers),
  and no attempt or pause runs past it (Claude-Mac, #1885);
* only this read-only query is repeated: no close, launch or other effect is ever retried here;
* it still fails closed: after the last attempt the *same* exception is raised again (with the
  attempt history as a note), so an unreadable inventory is never read as "no MT5". Every
  ``Get-CimInstance`` runs with ``-ErrorAction Stop`` (``fail_closed``), so a CIM error is a failure,
  never an empty list;
* every failed attempt and the outcome are appended to the configured JSON-lines log, which is
  rotated at ``MAX_LOG_BYTES`` (one previous generation is kept).

``process_rows`` adds one native fallback for inventories that need only ``NATIVE_FIELDS`` (support
64f1c5ae, Claude-Mac #2350): once every CIM attempt has failed, the same rows are read from Windows
itself (Toolhelp32 snapshot, ``QueryFullProcessImageNameW``, ``GetProcessTimes``), with no WMI. It stays
fail-closed: a query that needs ``CommandLine`` or any other CIM-only field never falls back; if the
native read fails too, the original CIM exception is raised; an error is never an empty list. A process
whose path cannot be read (access denied) is returned with ``ExecutablePath`` None, which callers that
match on the path treat as unknown, never as absent. Each fallback is recorded in the same log.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

ATTEMPTS = 4
PAUSES = (2, 5, 10)            # seconds between attempts, before jitter
JITTER = .25                   # each pause is scaled by a random factor in [1 - JITTER, 1 + JITTER]
TIMEOUT = 20                   # seconds per attempt
POLL_BUDGET = 25               # seconds, the most a status read or poll may spend on one inventory
MAX_LOG_BYTES = 1024 * 1024
RETRIED = (subprocess.TimeoutExpired, subprocess.CalledProcessError)
_LOG = {'path': None}
sleep = time.sleep             # injectable for tests
monotonic = time.monotonic
uniform = random.uniform


def configure(log_path):
    """Where failed attempts are recorded (``<controller state>\\process-query.jsonl``); None disables it."""
    _LOG['path'] = None if log_path is None else Path(log_path)


def _record(entry):
    path = _LOG['path']
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size >= MAX_LOG_BYTES:
            os.replace(path, path.with_name(path.stem + '.1' + path.suffix))     # bounded: one older generation
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(dict(entry, at=datetime.now(timezone.utc).isoformat(timespec='seconds')), sort_keys=True) + '\n')
    except OSError:
        pass                    # the log never decides an outcome


def _describe(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return 'timed out after %ss' % error.timeout
    return 'exited %s' % getattr(error, 'returncode', '?')


# PowerShell's default error action (Continue) lets Get-CimInstance write a non-terminating error and still exit 0
# with "[]", which a caller would read as "no process" (Codex P1 on GOAT-EA#163). Every Get-CimInstance in an
# inventory command therefore runs with -ErrorAction Stop: a CIM failure exits non-zero, is retried, then raised.
# Only the CIM call is escalated, never the rest of the pipeline (a null CreationDate in a calculated property stays
# a null, as before). A Get-CimInstance that names its own -ErrorAction in the same pipeline segment is left alone.
# The segment ends at the next | ; ) or line end (no controller filter contains one of those).
_CIM_SEGMENT = re.compile(r'(\bGet-CimInstance\b[^|;\r\n)]*?)(\s*)(?=[|;\r\n)]|$)')


def fail_closed(command):
    """The command with -ErrorAction Stop on every Get-CimInstance that does not set its own error action."""
    def stop(match):
        if re.search(r'-ErrorAction\b', match.group(1)):
            return match.group(0)
        return match.group(1) + ' -ErrorAction Stop' + match.group(2)
    return _CIM_SEGMENT.sub(stop, command)


def powershell_text(command, *, purpose, timeout=TIMEOUT, attempts=ATTEMPTS, pauses=PAUSES, budget=None):
    """stdout of one read-only PowerShell inventory command, retried through a transient WMI stall."""
    from studio_subprocess import background_creationflags
    command = fail_closed(command)
    history, started = [], monotonic()
    deadline = None if budget is None else started + budget
    for attempt in range(1, attempts + 1):
        allowed = timeout if deadline is None else max(.1, min(timeout, deadline - monotonic()))
        try:
            output = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True, encoding='utf-8-sig',
                                             timeout=allowed, creationflags=background_creationflags())
        except RETRIED as error:
            history.append('attempt %d %s' % (attempt, _describe(error)))
            _record(dict(purpose=purpose, attempt=attempt, of=attempts, error=_describe(error), elapsed=round(monotonic() - started, 1)))
            pause = pauses[min(attempt - 1, len(pauses) - 1)] * uniform(1 - JITTER, 1 + JITTER)
            if attempt == attempts or (deadline is not None and monotonic() + pause + .1 >= deadline):
                _record(dict(purpose=purpose, outcome='gave_up', attempts=attempt, elapsed=round(monotonic() - started, 1)))
                note = ('Windows process inventory (%s) did not answer in %d attempts over %.0f s: %s. Nothing was inferred '
                        'from it.' % (purpose, attempt, monotonic() - started, '; '.join(history)))
                if hasattr(error, 'add_note'):
                    error.add_note(note)
                raise
            sleep(pause)
            continue
        if history:
            _record(dict(purpose=purpose, outcome='recovered_after', attempts=attempt, elapsed=round(monotonic() - started, 1)))
        return output


# ---- native fallback (no WMI) -------------------------------------------------------------------------------
# The Win32_Process fields Windows itself answers without WMI. CommandLine is not one of them: reading another
# process's command line needs its PEB, so a query that needs it keeps the CIM-only behaviour.
NATIVE_FIELDS = frozenset(('ProcessId', 'ParentProcessId', 'Name', 'ExecutablePath', 'CreatedUtc'))
_EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)
ERROR_INVALID_PARAMETER = 87          # OpenProcess of a PID that no longer exists
ERROR_NO_MORE_FILES = 18
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x2


def filetime_utc(ticks):
    """A FILETIME (100 ns since 1601) as the CreatedUtc string a CIM inventory prints.

    PowerShell prints ``CreationDate.ToUniversalTime().ToString("o")``, and WMI keeps microseconds, so the
    seventh digit is always 0 (``2026-10-08T07:04:37.2087830Z`` for a process created at ...2087834).
    The native value is truncated the same way, so an identity read natively equals one read through WMI.
    """
    from datetime import timedelta
    ticks = int(ticks)
    return (_EPOCH_1601 + timedelta(microseconds=ticks // 10)).strftime('%Y-%m-%dT%H:%M:%S.%f') + '0Z'


def _kernel():
    if os.name != 'nt':
        raise OSError('The native process inventory needs Windows')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    return ctypes, wintypes, kernel


def _times(ctypes, wintypes, kernel, handle):
    """(created, exited) FILETIME ticks of an open process handle, or None."""
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]):
        return None
    return tuple((t.dwHighDateTime << 32) | t.dwLowDateTime for t in times[:2])


def own_identity():
    """This process as dict(pid, created_utc), read from Windows itself (no WMI); created_utc None elsewhere."""
    try:
        ctypes, wintypes, kernel = _kernel()
        found = _times(ctypes, wintypes, kernel, kernel.GetCurrentProcess())
    except (OSError, AttributeError, ValueError):
        found = None
    return dict(pid=os.getpid(), created_utc=None if found is None else filetime_utc(found[0]))


def native_rows(names=None, pid=None):
    """Win32_Process-shaped rows (NATIVE_FIELDS) from a Toolhelp32 snapshot, filtered by image name and/or PID.

    Raises OSError when the snapshot cannot be taken or walked (never an empty list on error). A process
    that exited between the snapshot and its read is left out, like a CIM query taken a moment later; a
    process GOAT may not open (access denied) is kept with ExecutablePath and CreatedUtc None.
    """
    ctypes, wintypes, kernel = _kernel()

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD),
                    ('szExeFile', wintypes.WCHAR * 260)]
    first, following = kernel.Process32FirstW, kernel.Process32NextW
    first.restype = following.restype = wintypes.BOOL
    first.argtypes = following.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    wanted = None if names is None else {str(name).casefold() for name in names}
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    entries = []
    try:
        entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = first(snapshot, ctypes.byref(entry))
        while ok:
            if (wanted is None or entry.szExeFile.casefold() in wanted) and (pid is None or entry.th32ProcessID == pid):
                entries.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            ok = following(snapshot, ctypes.byref(entry))
        code = ctypes.get_last_error()
        if code != ERROR_NO_MORE_FILES:
            raise ctypes.WinError(code)
    finally:
        kernel.CloseHandle(snapshot)
    rows = []
    for process_id, parent, name in entries:
        row = dict(ProcessId=process_id, ParentProcessId=parent, Name=name, ExecutablePath=None, CreatedUtc=None)
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            if ctypes.get_last_error() == ERROR_INVALID_PARAMETER:
                continue                        # gone since the snapshot
            rows.append(row)                    # denied: path and creation time unknown, never absent
            continue
        try:
            times = _times(ctypes, wintypes, kernel, handle)
            if times is not None and times[1]:
                continue                        # exited (only its handle remains)
            if times is not None:
                row['CreatedUtc'] = filetime_utc(times[0])
            size = wintypes.DWORD(32768); buffer = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and buffer.value:
                row['ExecutablePath'] = buffer.value
        finally:
            kernel.CloseHandle(handle)
        rows.append(row)
    return rows


def process_rows(command, *, purpose, fields, names=None, pid=None, timeout=TIMEOUT, attempts=ATTEMPTS, pauses=PAUSES,
                 budget=None):
    """Rows of one read-only Win32_Process inventory (JSON from ``command``), with the native fallback.

    ``fields`` are the properties the caller reads; ``names`` (image names) and ``pid`` are the command's own
    filter, applied to the native rows the same way. The fallback runs only after ``powershell_text`` has
    failed every attempt, and only when ``fields`` are all NATIVE_FIELDS; otherwise, or when the native read
    fails too, the original CIM exception is raised unchanged.
    """
    try:
        return json.loads(powershell_text(command, purpose=purpose, timeout=timeout, attempts=attempts, pauses=pauses, budget=budget))
    except RETRIED as error:
        if not set(fields) <= NATIVE_FIELDS:
            raise
        started = monotonic()
        try:
            rows = native_rows(names=names, pid=pid)
        except Exception as native:               # any failure of the fallback: fail closed on the CIM error
            _record(dict(purpose=purpose, outcome='native_fallback_failed', error=(type(native).__name__ + ': ' + str(native))[:300]))
            raise error
        _record(dict(purpose=purpose, outcome='native_fallback', rows=len(rows), elapsed=round(monotonic() - started, 1)))
        return [{key: row.get(key) for key in fields} for row in rows]
