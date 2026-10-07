"""Research-terminal launch policy (goatai#1885 PR E).

Fixture tests drive studio_research_launch through a recording fake of the Win32 layer. The
RealWindows tests launch only small Python processes (never MT5) through the real kernel32 path:
a suspended child, a per-test job, nested assignment and a real ERROR_ACCESS_DENIED refusal.
"""
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import studio_research_launch as r
from studio_research_launch import (BELOW_NORMAL_PRIORITY_CLASS, CREATE_NO_WINDOW, CREATE_SUSPENDED, IDLE_PRIORITY_CLASS,
                                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_LIMIT_PRIORITY_CLASS,
                                    ResearchLaunchRefused)

HERE = Path(__file__).resolve().parent
OWNER = dict(schema=r.SCHEMA, profile='owner')
SPLIT = dict(schema=r.SCHEMA, profile='owner', agent_priority='idle_split')
RESPONSIVE = dict(schema=r.SCHEMA, profile='customer', keep_pc_responsive=True)


def plan_of(policy=None):
    return r.effective(r.validate_policy(policy) if policy else r.load_policy(tempfile.mkdtemp()))


class FakeApi:
    """Records every Win32 call; behaves like a job that keeps exactly what was set."""

    def __init__(self, *, assign_error=None, resume_error=None, create_error=None, job_error=None, existed=False,
                 active=0, keep_flags=None, in_job=True, terminate_fails=False, breakaway_denied=False):
        self.calls = [];self.flags = 0;self.priority = 0;self.rate = None
        self.assign_error, self.resume_error, self.create_error, self.job_error = assign_error, resume_error, create_error, job_error
        self.existed, self.active, self.keep_flags, self.member = existed, active, keep_flags, in_job
        self.terminate_fails = terminate_fails
        self.breakaway_denied = breakaway_denied     # the caller's job (e.g. Task Scheduler's) refuses breakaway
        self.processes = {}

    def names(self):return [call[0] for call in self.calls]

    def create_job(self, name):
        self.calls.append(('create_job', name))
        if self.job_error:raise self.job_error
        return 'JOB', self.existed

    def open_job(self, name, *, write=False, terminate=False):
        self.calls.append(('open_job', name, write));return 'JOB'

    def active_processes(self, job):return self.active

    def set_limits(self, job, flags, priority):
        assert job, 'NULL job handle'
        self.calls.append(('set_limits', flags, priority))
        self.flags = flags if self.keep_flags is None else self.keep_flags;self.priority = priority or 0

    def query_limits(self, job):return self.flags, self.priority

    def set_cpu_rate(self, job, percent):
        assert job, 'NULL job handle'
        self.calls.append(('set_cpu_rate', percent));self.rate = percent

    def query_cpu_rate(self, job):return self.rate

    def create_suspended(self, command_line, cwd, flags):
        self.calls.append(('create_suspended', command_line, cwd, flags))
        if self.create_error:raise self.create_error
        if self.breakaway_denied and flags & r.CREATE_BREAKAWAY_FROM_JOB:
            raise OSError(None, 'CreateProcessW failed', None, 5)     # ERROR_ACCESS_DENIED: no process was created
        return 'PROCESS', 'THREAD', 4242

    def assign(self, job, process):
        self.calls.append(('assign', job, process))
        if self.assign_error:raise self.assign_error

    def in_job(self, process, job):return self.member

    def resume(self, thread):
        self.calls.append(('resume', thread))
        if self.resume_error:raise self.resume_error

    def terminate(self, process):
        self.calls.append(('terminate', process));return not self.terminate_fails

    def terminate_job(self, job):self.calls.append(('terminate_job', job))

    def exit_code(self, process):return None

    def close(self, handle):self.calls.append(('close', handle))

    def process_ids(self, job):return list(self.processes)

    def process_info(self, pid):return self.processes.get(pid)

    def set_priority(self, pid, priority):
        self.calls.append(('set_priority', pid, priority))
        image, _ = self.processes[pid];self.processes[pid] = (image, priority);return True


def denied(code=5):
    return OSError(None, 'AssignProcessToJobObject failed', None, code)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state';self.root.mkdir()
        self.data = Path(self.tmp.name) / 'data';(self.data / 'Tester' / 'logs').mkdir(parents=True)
        self.install = dict(terminal_executable=str(Path(self.tmp.name) / 'MT5' / 'terminal64.exe'),
                            terminal_data_root=str(self.data))
        self.name = r.job_name(self.install)
        self.keepers = []

    def keeper(self, root, name, *, now=None):
        self.keepers.append(name);return dict(state='test')

    def policy(self, value):
        r.write_policy(self.root, value)

    def launch(self, api, policy=None, *, now=1000.0):
        if policy:self.policy(policy)
        controller = SimpleNamespace(root=self.root, install=self.install)
        return r.launch(controller, ['C:\\MT5 x\\terminal64.exe', '/config:C:\\a b\\member.ini'], cwd='C:\\MT5 x',
                        config='C:\\a b\\member.ini', api=api, now=now, keeper=self.keeper)


# ---------------------------------------------------------------- policy

class PolicyTests(Workspace):
    def test_default_is_customer_below_normal_without_job_or_cap(self):
        plan = r.effective(r.load_policy(self.root))
        self.assertEqual((plan['profile'], plan['creation_priority'], plan['job'], plan['cpu_rate_percent'], plan['keeper']),
                         ('customer', BELOW_NORMAL_PRIORITY_CLASS, False, None, False))

    def test_keep_pc_responsive_is_a_50_percent_cap_with_below_normal_lock(self):
        plan = plan_of(RESPONSIVE)
        self.assertEqual((plan['job'], plan['priority_lock'], plan['cpu_rate_percent'], plan['stages'], plan['keeper']),
                         (True, BELOW_NORMAL_PRIORITY_CLASS, 50, [], False))

    def test_owner_default_is_idle_locked_and_staged_17_then_33(self):
        plan = plan_of(OWNER)
        self.assertEqual((plan['creation_priority'], plan['priority_lock'], plan['stages'], plan['cpu_rate_percent'], plan['keeper']),
                         (IDLE_PRIORITY_CLASS, IDLE_PRIORITY_CLASS, [17, 33], 17, True))

    def test_idle_split_is_below_normal_mt5_with_idle_agents_and_no_lock(self):
        plan = plan_of(SPLIT)
        self.assertEqual((plan['creation_priority'], plan['priority_lock'], plan['agent_priority']),
                         (BELOW_NORMAL_PRIORITY_CLASS, None, IDLE_PRIORITY_CLASS))

    def test_no_policy_can_launch_at_normal_or_above(self):
        for policy in (None, RESPONSIVE, OWNER, SPLIT, dict(OWNER, cpu_stages_percent=[90])):
            plan = plan_of(policy)
            self.assertIn(plan['creation_priority'], (IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS))
            self.assertIn(plan['priority_lock'], (None, IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS))

    def test_invalid_policies_refused(self):
        bad = [dict(profile='owner'), dict(OWNER, agent_priority='normal'), dict(OWNER, cpu_stages_percent=[33, 17]),
               dict(OWNER, cpu_stages_percent=[100]), dict(OWNER, cpu_stages_percent=[]), dict(OWNER, extra=1),
               dict(OWNER, publishers=[dict(label='Exp 01', cycle_log='relative\\x.jsonl', max_seconds=90)]),
               dict(OWNER, publishers=[dict(label='Exp 01', cycle_log='C:\\x.jsonl', max_seconds=1)]),
               dict(OWNER, publishers=[dict(label='A', cycle_log='C:\\x', max_seconds=90)] * 2),
               dict(RESPONSIVE, keep_pc_responsive='yes'), dict(RESPONSIVE, cpu_stages_percent=[50]),
               dict(schema=r.SCHEMA, profile='trading')]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.validate_policy(value)

    def test_toggle_writes_customer_policy_and_refuses_on_owner_policy(self):
        r.set_keep_pc_responsive(self.root, True)
        self.assertTrue(r.load_policy(self.root)['keep_pc_responsive'])
        r.set_keep_pc_responsive(self.root, False)
        self.assertFalse(r.load_policy(self.root)['keep_pc_responsive'])
        self.policy(OWNER)
        with self.assertRaisesRegex(ValueError, 'owner research-launch policy'):
            r.set_keep_pc_responsive(self.root, True)

    def test_operation_contract_and_local_file_classification(self):
        from goat_studio import OPERATION_CONTRACTS
        from studio_research_authority import LOCAL_FILE_OPERATIONS, READ_OPERATIONS
        contract = OPERATION_CONTRACTS['research-launch']
        self.assertEqual((contract['required'], contract['choices']['keep-pc-responsive']), ([], ['on', 'off']))
        self.assertIn('never opens the store or MT5', contract['effect'])
        self.assertIn('trading, monitor and deploy launches are never affected', contract['effect'])
        self.assertTrue({'research-launch'} <= LOCAL_FILE_OPERATIONS <= READ_OPERATIONS)


class JobNameTests(unittest.TestCase):
    def test_name_is_local_per_terminal_hash(self):
        a = dict(terminal_executable='G:\\MT5\\T2\\terminal64.exe', terminal_data_root='C:\\Data\\BF13')
        name = r.job_name(a)
        self.assertRegex(name, r'^Local\\GOAT-Research-[0-9a-f]{32}$')
        self.assertTrue(r.JOB_NAME_PATTERN.fullmatch(name))
        self.assertNotIn('Global', name)
        self.assertEqual(name, r.job_name(dict(terminal_executable='g:\\mt5\\t2\\TERMINAL64.EXE', terminal_data_root='c:\\data\\bf13')))
        self.assertNotEqual(name, r.job_name(dict(a, terminal_data_root='C:\\Data\\B192')))
        self.assertNotEqual(name, r.job_name(dict(a, terminal_executable='G:\\MT5\\T1\\terminal64.exe')))


# ---------------------------------------------------------------- KILL_ON_JOB_CLOSE (Mac must-have 1)

class KillOnJobCloseTests(Workspace):
    def test_limit_flags_never_include_kill_on_job_close_or_breakaway(self):
        for policy in (None, RESPONSIVE, OWNER, SPLIT):
            flags = r.limit_flags(plan_of(policy))
            self.assertFalse(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, policy)
            self.assertFalse(flags & (r.JOB_OBJECT_LIMIT_BREAKAWAY_OK | r.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK), policy)

    def test_launch_sets_and_records_limits_without_kill_on_job_close(self):
        for policy in (RESPONSIVE, OWNER, SPLIT):
            api = FakeApi();self.launch(api, policy)
            sets = [call for call in api.calls if call[0] == 'set_limits']
            self.assertEqual(len(sets), 1)
            self.assertFalse(sets[0][1] & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
            record = json.loads((self.root / 'research-launch' / 'launch.json').read_text(encoding='utf-8'))
            self.assertIs(record['job']['kill_on_job_close'], False)

    def test_a_job_that_keeps_kill_on_job_close_refuses_before_any_process(self):
        api = FakeApi(keep_flags=JOB_OBJECT_LIMIT_PRIORITY_CLASS | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        with self.assertRaisesRegex(ResearchLaunchRefused, 'did not keep the requested limits'):
            self.launch(api, OWNER)
        self.assertNotIn('create_suspended', api.names())


# ---------------------------------------------------------------- launch flags and order

class LaunchTests(Workspace):
    def test_owner_launch_is_suspended_idle_assigned_then_resumed(self):
        api = FakeApi()
        launched = self.launch(api, OWNER)
        names = api.names()
        self.assertEqual([n for n in names if n != 'close'],
                         ['create_job', 'set_limits', 'set_cpu_rate', 'create_suspended', 'assign', 'resume'])
        self.assertEqual(api.calls[0], ('create_job', self.name))
        self.assertEqual(api.calls[1], ('set_limits', JOB_OBJECT_LIMIT_PRIORITY_CLASS, IDLE_PRIORITY_CLASS))
        self.assertEqual(api.calls[2], ('set_cpu_rate', 17))
        create = api.calls[3]
        self.assertEqual(create[3], CREATE_SUSPENDED | IDLE_PRIORITY_CLASS | CREATE_NO_WINDOW | r.CREATE_BREAKAWAY_FROM_JOB)
        self.assertEqual(create[1], subprocess.list2cmdline(['C:\\MT5 x\\terminal64.exe', '/config:C:\\a b\\member.ini']))
        self.assertLess(names.index('assign'), names.index('resume'))
        self.assertEqual(launched.pid, 4242);self.assertIsNone(launched.poll())
        self.assertEqual(self.keepers, [self.name])
        record = json.loads((self.root / 'research-launch' / 'launch.json').read_text(encoding='utf-8'))
        self.assertEqual((record['profile'], record['creation_priority'], record['job']['name'], record['job']['priority_lock'],
                          record['job']['cpu_rate_percent'], record['keeper']), ('owner', 'idle', self.name, 'idle', 17, dict(state='test')))
        self.assertIs(record['broke_away'], True)
        self.assertIn(('close', 'JOB'), api.calls)       # the launcher's own job handle is closed; MT5 keeps the job

    def test_customer_default_is_below_normal_without_a_job(self):
        api = FakeApi();self.launch(api)
        self.assertEqual([n for n in api.names() if n != 'close'], ['create_suspended', 'resume'])
        self.assertEqual(api.calls[0][3], CREATE_SUSPENDED | BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW | r.CREATE_BREAKAWAY_FROM_JOB)
        self.assertEqual(self.keepers, [])
        self.assertIsNone(json.loads((self.root / 'research-launch' / 'launch.json').read_text(encoding='utf-8'))['job'])

    def test_keep_pc_responsive_launch_has_the_50_percent_cap_and_no_keeper(self):
        api = FakeApi();self.launch(api, RESPONSIVE)
        self.assertIn(('set_limits', JOB_OBJECT_LIMIT_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS), api.calls)
        self.assertIn(('set_cpu_rate', 50), api.calls)
        self.assertEqual(self.keepers, [])

    def test_idle_split_launches_below_normal_without_a_priority_lock(self):
        api = FakeApi();self.launch(api, SPLIT)
        self.assertIn(('set_limits', 0, None), api.calls)
        self.assertEqual(next(c for c in api.calls if c[0] == 'create_suspended')[3],
                         CREATE_SUSPENDED | BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW | r.CREATE_BREAKAWAY_FROM_JOB)

    def test_guard_starts_only_with_publishers_to_watch(self):
        self.launch(FakeApi(), OWNER)
        self.assertFalse((self.root / 'research-launch' / 'guard.json').exists())
        log = Path(self.tmp.name) / 'cycles.jsonl';log.write_text('', encoding='utf-8')
        self.launch(FakeApi(), dict(OWNER, publishers=[dict(label='Exp 01', cycle_log=str(log), max_seconds=90)]))
        guard = json.loads((self.root / 'research-launch' / 'guard.json').read_text(encoding='utf-8'))
        self.assertEqual((guard['stage'], guard['cpu_rate_percent'], guard['paused'], guard['job_name']), (0, 17, False, self.name))

    def test_an_idle_existing_job_is_reconfigured_not_trusted(self):
        api = FakeApi(existed=True, active=0);self.launch(api, OWNER)
        self.assertIn(('set_limits', JOB_OBJECT_LIMIT_PRIORITY_CLASS, IDLE_PRIORITY_CLASS), api.calls)
        self.assertIn('resume', api.names())


# ---------------------------------------------------------------- breakaway (Claude-Mac note 5)

class BreakawayTests(Workspace):
    """MT5 leaves the caller's job (a Task Scheduler driver's) when allowed, so a task stop or its
    ExecutionTimeLimit cannot end it mid-member; a refusing job keeps today's nesting, recorded."""

    BASE = CREATE_SUSPENDED | IDLE_PRIORITY_CLASS | CREATE_NO_WINDOW

    def creates(self, api):
        return [call[3] for call in api.calls if call[0] == 'create_suspended']

    def test_research_mt5_is_created_breaking_away_from_the_callers_job(self):
        for policy in (None, RESPONSIVE, OWNER, SPLIT):
            api = FakeApi();self.launch(api, policy)
            flags = self.creates(api)
            self.assertEqual(len(flags), 1, policy);self.assertTrue(flags[0] & r.CREATE_BREAKAWAY_FROM_JOB, policy)
            record = json.loads((self.root / 'research-launch' / 'launch.json').read_text(encoding='utf-8'))
            self.assertIs(record['broke_away'], True)

    def test_a_job_that_refuses_breakaway_gets_the_same_suspended_launch_nested(self):
        api = FakeApi(breakaway_denied=True)
        launched = self.launch(api, OWNER)
        self.assertEqual(self.creates(api), [self.BASE | r.CREATE_BREAKAWAY_FROM_JOB, self.BASE])   # identical but the flag
        names = [n for n in api.names() if n != 'close']
        self.assertEqual(names, ['create_job', 'set_limits', 'set_cpu_rate', 'create_suspended', 'create_suspended', 'assign', 'resume'])
        self.assertEqual(launched.pid, 4242)
        record = json.loads((self.root / 'research-launch' / 'launch.json').read_text(encoding='utf-8'))
        self.assertIs(record['broke_away'], False)
        self.assertIn('"broke_away":false', (self.root / 'research-launch' / 'history.jsonl').read_text(encoding='utf-8'))
        status = r.status(self.install, self.root, api=FakeApi())
        self.assertIs(status['last_launch']['broke_away'], False)

    def test_only_access_denied_retries_nested_and_any_other_creation_error_refuses(self):
        api = FakeApi(create_error=OSError(None, 'CreateProcessW failed', None, 2))
        with self.assertRaisesRegex(ResearchLaunchRefused, 'could not be created'):
            self.launch(api, OWNER)
        self.assertEqual(len(self.creates(api)), 1)

    def test_a_refused_assignment_after_a_nested_creation_still_terminates(self):
        api = FakeApi(breakaway_denied=True, assign_error=denied(5))
        with self.assertRaisesRegex(ResearchLaunchRefused, 'Nothing ran'):
            self.launch(api, OWNER)
        self.assertIn(('terminate', 'PROCESS'), api.calls);self.assertNotIn('resume', api.names())
        self.assertEqual(len(self.creates(api)), 2)                         # one refused breakaway, one process


# ---------------------------------------------------------------- refusal (Mac must-have 2)

class RefusalTests(Workspace):
    def refused(self, api, policy=OWNER, pattern=None):
        with self.assertRaises(ResearchLaunchRefused) as caught:
            self.launch(api, policy)
        if pattern:self.assertRegex(str(caught.exception), pattern)
        return str(caught.exception)

    def test_access_denied_on_assignment_terminates_the_suspended_process(self):
        api = FakeApi(assign_error=denied(5))
        text = self.refused(api, pattern='access denied')
        self.assertIn('never starts research MT5 at normal priority', text)
        self.assertIn('Nothing ran', text)
        self.assertIn(('terminate', 'PROCESS'), api.calls)
        self.assertNotIn('resume', api.names())
        self.assertEqual(api.names().count('create_suspended'), 1)          # no second (fallback) launch
        self.assertFalse((self.root / 'research-launch' / 'launch.json').exists())
        history = (self.root / 'research-launch' / 'history.jsonl').read_text(encoding='utf-8')
        self.assertIn('"event":"refused"', history)

    def test_any_assignment_failure_refuses_the_same_way(self):
        api = FakeApi(assign_error=denied(87))
        self.assertNotIn('access denied', self.refused(api, pattern='could not be placed in its low-priority research job'))
        self.assertIn(('terminate', 'PROCESS'), api.calls);self.assertNotIn('resume', api.names())

    def test_not_in_the_job_after_assignment_refuses(self):
        api = FakeApi(in_job=False);self.refused(api)
        self.assertIn(('terminate', 'PROCESS'), api.calls);self.assertNotIn('resume', api.names())

    def test_resume_failure_terminates(self):
        api = FakeApi(resume_error=OSError(None, 'ResumeThread failed', None, 6))
        self.refused(api, pattern='could not resume it')
        self.assertIn(('terminate', 'PROCESS'), api.calls)

    def test_job_creation_failure_refuses_before_any_process(self):
        api = FakeApi(job_error=denied(5))
        self.refused(api, pattern='could not create the research job')
        self.assertNotIn('create_suspended', api.names())

    def test_a_busy_existing_job_refuses_before_any_process(self):
        api = FakeApi(existed=True, active=3)
        self.refused(api, pattern='Another process already runs')
        self.assertNotIn('create_suspended', api.names())

    def test_an_unconfirmed_stop_is_never_reported_as_nothing_ran(self):
        # Claude-Mac note 1: TerminateProcess and its wait are checked; the job is the fallback; a process
        # still alive is an uncertain start (the seed member then needs reconcile), never "nothing ran".
        api = FakeApi(assign_error=denied(5), terminate_fails=True)
        with self.assertRaises(r.ResearchLaunchUncertain) as caught:
            self.launch(api, OWNER)
        self.assertNotIsInstance(caught.exception, ResearchLaunchRefused)
        self.assertIn('could not confirm', str(caught.exception))
        self.assertIn(('terminate_job', 'JOB'), api.calls);self.assertNotIn('resume', api.names())
        self.assertIn('"confirmed_stopped":false', (self.root / 'research-launch' / 'history.jsonl').read_text(encoding='utf-8'))

    def test_customer_refusal_never_falls_back_either(self):
        api = FakeApi(resume_error=OSError(None, 'ResumeThread failed', None, 6))
        self.refused(api, policy=None)
        self.assertEqual(api.names().count('create_suspended'), 1)

    def test_invalid_policy_file_refuses_the_launch(self):
        (self.root / r.POLICY_FILE).write_text('{"schema":"goat-research-launch-v1","profile":"owner","agent_priority":"normal"}',
                                              encoding='utf-8')
        api = FakeApi()
        with self.assertRaisesRegex(ResearchLaunchRefused, 'research-launch.json is not valid'):
            self.launch(api)
        self.assertEqual(api.calls, [])


# ---------------------------------------------------------------- routing: research vs trading/monitor

class _Controller(SimpleNamespace):
    pass


class RoutingTests(Workspace):
    def process(self):
        from studio_seed_process import WindowsSeedProcess
        controller = _Controller(root=self.root, install=self.install)
        process = WindowsSeedProcess(controller)
        state = iter([None, dict(pid=4242, executable=self.install['terminal_executable'], created_utc='x')])
        # PR D (#163): the startup identity loop passes budget= to every inventory.
        process.inspect = lambda timeout=20, budget=None: next(state)
        return process

    def test_research_start_uses_the_research_launch(self):
        process = self.process()
        child = SimpleNamespace(pid=4242, poll=lambda: None)
        with patch('studio_research_launch.launch', return_value=child) as research, patch('subprocess.Popen') as popen:
            identity = process.start(Path(self.tmp.name) / 'member.ini', research=True)
        self.assertEqual(identity['pid'], 4242)
        research.assert_called_once();popen.assert_not_called()

    def test_research_start_keeps_the_90_s_identity_loop(self):
        # PR D (#163) + PR E: a research launch waits the same STARTUP_IDENTITY_SECONDS (90 s) for its
        # identity, with each inventory bounded by the remaining budget; seen at 60 s it is adopted.
        from studio_seed_process import STARTUP_IDENTITY_SECONDS, WindowsSeedProcess
        self.assertEqual(STARTUP_IDENTITY_SECONDS, 90)
        clock = [0.0]
        process = WindowsSeedProcess(_Controller(root=self.root, install=self.install),
                                     sleep=lambda s: clock.__setitem__(0, clock[0] + 10), monotonic=lambda: clock[0])
        budgets = []
        identity = dict(pid=4242, executable=self.install['terminal_executable'], created_utc='x')

        def inspect(timeout=20, budget=None):
            if budget is None:return None                              # the "still running?" check before launch
            budgets.append(budget)
            return identity if clock[0] >= 60 else None
        process.inspect = inspect
        child = SimpleNamespace(pid=4242, poll=lambda: None)
        with patch('studio_research_launch.launch', return_value=child) as research:
            self.assertEqual(process.start(Path(self.tmp.name) / 'member.ini', research=True), identity)
        research.assert_called_once()
        self.assertEqual(budgets[0], 90);self.assertEqual(budgets[-1], 30)

    def test_plain_start_is_unchanged_popen_and_never_the_research_launch(self):
        process = self.process()
        with patch('studio_research_launch.launch', side_effect=AssertionError('monitor launch reached the research job')), \
                patch('studio_seed_process.subprocess.Popen', return_value=SimpleNamespace(pid=4242, poll=lambda: None)) as popen:
            process.start(Path(self.tmp.name) / 'monitor.ini')
        self.assertEqual(popen.call_args.kwargs['creationflags'], getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_research_view_wraps_only_the_windows_process(self):
        from studio_seed_process import ResearchLaunch, research_view
        process = self.process()
        view = research_view(process)
        self.assertIsInstance(view, ResearchLaunch);self.assertIs(research_view(view), view)
        fake = object();self.assertIs(research_view(fake), fake)
        calls = []
        process.start = lambda config, research=False: calls.append((config, research))
        view.start('member.ini')
        self.assertEqual(calls, [('member.ini', True)])
        self.assertIs(view.inspect, process.inspect)                       # everything else is delegated

    def test_seed_runner_members_are_research_launches(self):
        from studio_seed import SeedRunner
        from studio_seed_process import ResearchLaunch
        controller = SimpleNamespace(root=self.root, local=self.root, install=self.install)
        runner = SeedRunner(controller, process=self.process())
        self.assertIsInstance(runner.process, ResearchLaunch)
        fake = SimpleNamespace(start=lambda config: None)
        self.assertIs(SeedRunner(controller, process=fake).process, fake)   # test doubles stay as given


class TradingTerminalExclusionTests(unittest.TestCase):
    """REQUIRED: trading, deploy, onboarding and monitor launches never get the research job."""

    TOKENS = (r'\bstudio_research_launch\b', r'\bresearch_view\b', r'\bResearchLaunch\b', r'\bresearch=True\b')

    def test_trading_and_monitor_launch_sources_never_reach_the_research_launch(self):
        for name in ('studio_demo_deploy.py', 'studio_onboarding.py', 'demo_agent.py', 'studio_rejected_monitor.py',
                     'studio_human_launch.py'):
            text = (HERE / name).read_text(encoding='utf-8')
            for token in self.TOKENS:
                self.assertIsNone(re.search(token, text), name + ' must not reach the research launch (' + token + ')')

    def test_deploy_and_onboarding_popen_flags_are_unchanged(self):
        for name in ('studio_demo_deploy.py', 'studio_onboarding.py'):
            text = (HERE / name).read_text(encoding='utf-8')
            self.assertIn('subprocess.Popen(', text)
            for token in ('CREATE_SUSPENDED', 'PRIORITY_CLASS', 'JobObject', 'AssignProcessToJobObject'):
                self.assertNotIn(token, text, name)

    def test_only_seed_members_and_the_native_first_start_wrap_the_process(self):
        users = sorted(p.name for p in HERE.glob('*.py') if not p.name.startswith('test_')
                       and 'research_view(' in p.read_text(encoding='utf-8'))
        self.assertEqual(users, ['studio_config_start.py', 'studio_seed.py', 'studio_seed_process.py'])
        config = (HERE / 'studio_config_start.py').read_text(encoding='utf-8')
        self.assertIn('        return research_view(process).start(startup)', config)
        self.assertEqual(config.count('launched=_research_launch(c,job_id,generation,process,startup)'), 2)   # start and its retry
        starts = re.findall(r'\w+\.start\([^)]*\bresearch=True', ''.join(
            p.read_text(encoding='utf-8') for p in HERE.glob('*.py') if not p.name.startswith('test_')))
        self.assertEqual(starts, ['_process.start(config,research=True'])


# ---------------------------------------------------------------- stepping (owner CPU cap)

def cycle(start_s, seconds=None):
    return dict(started_ms=int(start_s * 1000), ended_ms=None if seconds is None else int((start_s + seconds) * 1000))


class SteppingTests(unittest.TestCase):
    PUBLISHERS = [dict(label='Exp 01', cycle_log='C:\\a', max_seconds=90), dict(label='Exp 02', cycle_log='C:\\b', max_seconds=45)]

    def guard(self):
        record = dict(launch_id='L', job=dict(name='Local\\GOAT-Research-' + '0' * 32))
        return r.new_guard(record, plan_of(OWNER), 1000)

    def test_widens_only_after_every_publisher_kept_its_budget(self):
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(1010, 50)]}, 1100_000)
        self.assertEqual((event, g['cpu_rate_percent']), (None, 17))
        g, event = r.step(g, self.PUBLISHERS, {'Exp 01': [cycle(1010, 50)], 'Exp 02': [cycle(1020, 20)]}, 1110_000)
        self.assertEqual((event, g['stage'], g['cpu_rate_percent']), ('widen', 1, 33))

    def test_one_breach_steps_back_down_and_the_second_pauses(self):
        g, _ = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(1010, 50)], 'Exp 02': [cycle(1020, 20)]}, 1100_000)
        self.assertEqual(g['cpu_rate_percent'], 33)
        g, event = r.step(g, self.PUBLISHERS, {'Exp 02': [cycle(1200, 60)]}, 1300_000)
        self.assertEqual((event, g['cpu_rate_percent'], g['paused']), ('breach', 17, False))
        g, event = r.step(g, self.PUBLISHERS, {'Exp 01': [cycle(1400, 120)]}, 1600_000)
        self.assertEqual((event, g['cpu_rate_percent'], g['paused'], len(g['breaches'])), ('pause', 17, True, 2))
        self.assertEqual(r.step(g, self.PUBLISHERS, {'Exp 02': [cycle(1700, 99)]}, 1900_000)[1], None)

    def test_a_breach_at_the_first_stage_stays_there_and_counts(self):
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(1010, 200)]}, 1300_000)
        self.assertEqual((event, g['stage'], g['cpu_rate_percent'], len(g['breaches'])), ('breach', 0, 17, 1))

    def test_a_cycle_still_running_over_budget_is_a_breach(self):
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(1010)]}, 1150_000)
        self.assertEqual(event, 'breach');self.assertTrue(g['breaches'][0]['running'])
        g, event = r.step(g, self.PUBLISHERS, {'Exp 01': [cycle(1010, 780)]}, 1800_000)
        self.assertIsNone(event)                                            # the same cycle counts once

    def test_a_running_cycle_inside_budget_is_not_judged_yet(self):
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(1010)]}, 1050_000)
        self.assertIsNone(event);self.assertEqual(g['judged'], [])

    def test_cycles_from_before_the_launch_are_ignored_except_one_budget_back(self):
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(800, 500)]}, 1400_000)
        self.assertIsNone(event)
        g, event = r.step(self.guard(), self.PUBLISHERS, {'Exp 01': [cycle(967, 763)]}, 1800_000)
        self.assertEqual(event, 'breach')                                   # started 33 s before, hung 12.7 min

    def test_without_publishers_the_cap_never_widens(self):
        g, event = r.step(self.guard(), [], {}, 5000_000)
        self.assertEqual((event, g['cpu_rate_percent']), (None, 17))

    def test_read_cycles_pairs_start_and_end_and_keeps_running_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cycle-identities.jsonl'
            rows = [dict(event='START', pid=1, startedAt=1000), dict(event='END', pid=1, startedAt=1000, endedAt=51000),
                    dict(event='START', pid=2, startedAt=120000)]
            path.write_text('\n'.join(json.dumps(x) for x in rows) + '\n', encoding='utf-8')
            self.assertEqual(r.read_cycles(path), [dict(started_ms=1000, ended_ms=51000), dict(started_ms=120000, ended_ms=None)])


# ---------------------------------------------------------------- keeper and guard pass

class GuardPassTests(Workspace):
    def owner_with_logs(self, policy=OWNER):
        logs = {}
        for label in ('Exp 01', 'Exp 02'):
            logs[label] = Path(self.tmp.name) / (label.replace(' ', '') + '.jsonl');logs[label].write_text('', encoding='utf-8')
        publishers = [dict(label='Exp 01', cycle_log=str(logs['Exp 01']), max_seconds=90),
                      dict(label='Exp 02', cycle_log=str(logs['Exp 02']), max_seconds=45)]
        api = FakeApi()
        self.launch(api, dict(policy, publishers=publishers), now=1000.0)
        return api, logs

    @staticmethod
    def append(path, start_s, seconds):
        with open(path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event='START', pid=int(start_s), startedAt=int(start_s * 1000))) + '\n')
            if seconds is not None:
                stream.write(json.dumps(dict(event='END', pid=int(start_s), startedAt=int(start_s * 1000),
                                             endedAt=int((start_s + seconds) * 1000))) + '\n')

    def test_keeper_guard_widens_steps_down_and_pauses_the_lane(self):
        api, logs = self.owner_with_logs()
        self.append(logs['Exp 01'], 1010, 50);self.append(logs['Exp 02'], 1020, 20)
        seen = r.guard_pass(self.root, self.name, api, 'JOB', 1100)
        self.assertEqual((seen['event'], seen['cpu_rate_percent']), ('widen', 33))
        self.assertEqual(api.calls[-1], ('set_cpu_rate', 33))
        self.assertEqual(r.guard_pass(self.root, self.name, api, 'JOB', 1105).get('event'), None)    # throttled
        self.append(logs['Exp 02'], 1200, 70)
        seen = r.guard_pass(self.root, self.name, api, 'JOB', 1300)
        self.assertEqual((seen['event'], seen['cpu_rate_percent']), ('breach', 17))
        self.assertFalse(r.pause_wanted(SimpleNamespace(root=self.root, install=self.install)))
        self.append(logs['Exp 01'], 1400, 120)
        seen = r.guard_pass(self.root, self.name, api, 'JOB', 1600)
        self.assertEqual((seen['event'], seen['paused']), ('pause', True))
        self.assertTrue(r.pause_wanted(SimpleNamespace(root=self.root, install=self.install)))
        history = (self.root / 'research-launch' / 'history.jsonl').read_text(encoding='utf-8')
        for event in ('"event":"widen"', '"event":"breach"', '"event":"pause"'):self.assertIn(event, history)

    def test_an_unreadable_publisher_log_never_widens(self):
        api, logs = self.owner_with_logs()
        self.append(logs['Exp 01'], 1010, 50);logs['Exp 02'].unlink()
        seen = r.guard_pass(self.root, self.name, api, 'JOB', 1100)
        self.assertEqual((seen['event'], seen['cpu_rate_percent']), (None, 17))
        guard = json.loads((self.root / 'research-launch' / 'guard.json').read_text(encoding='utf-8'))
        self.assertTrue(guard['publisher_read_errors'])

    def test_idle_split_sets_only_tester_agents_to_idle(self):
        api, _ = self.owner_with_logs(SPLIT)
        api.processes = {1: ('G:\\MT5\\terminal64.exe', BELOW_NORMAL_PRIORITY_CLASS),
                         2: ('G:\\MT5\\metatester64.exe', BELOW_NORMAL_PRIORITY_CLASS),
                         3: ('G:\\MT5\\metatester64.exe', IDLE_PRIORITY_CLASS), 4: None}
        seen = r.guard_pass(self.root, self.name, api, 'JOB', 1100)
        self.assertEqual(seen['agents_lowered'], 1)
        self.assertEqual([c for c in api.calls if c[0] == 'set_priority'], [('set_priority', 2, IDLE_PRIORITY_CLASS)])
        self.assertEqual(api.processes[1][1], BELOW_NORMAL_PRIORITY_CLASS)  # MT5 itself stays below normal

    def test_pause_wanted_needs_the_current_launch_and_this_terminal(self):
        controller = SimpleNamespace(root=self.root, install=self.install)
        self.assertFalse(r.pause_wanted(controller))
        self.owner_with_logs()
        path = self.root / 'research-launch' / 'guard.json'
        guard = json.loads(path.read_text(encoding='utf-8'));guard['paused'] = True;path.write_text(json.dumps(guard), encoding='utf-8')
        self.assertTrue(r.pause_wanted(controller))
        self.assertFalse(r.pause_wanted(SimpleNamespace(root=self.root, install=dict(self.install, terminal_data_root='C:\\other'))))
        guard['launch_id'] = 'older';path.write_text(json.dumps(guard), encoding='utf-8')
        self.assertFalse(r.pause_wanted(controller))

    def test_seed_lane_requests_its_between_members_pause_once(self):
        from studio_seed import SeedRunner
        from studio_seed_process import ResearchLaunch
        runner = SeedRunner.__new__(SeedRunner);runner.c = SimpleNamespace(root=self.root, install=self.install)
        runner.process = ResearchLaunch(object());runner.clock = lambda: 5.0
        requested = []
        runner.paused = lambda batch_id: bool(requested)
        runner.request_pause = lambda batch_id, now: requested.append((batch_id, now))
        with patch('studio_research_launch.pause_wanted', return_value=True):
            self.assertTrue(runner._research_guard('hunt'));self.assertFalse(runner._research_guard('hunt'))
        self.assertEqual(requested, [('hunt', 5.0)])
        runner.process = object()
        with patch('studio_research_launch.pause_wanted', side_effect=AssertionError):
            self.assertFalse(runner._research_guard('hunt'))                # test doubles never consult it

    def test_native_batch_requests_the_safe_point_pause_only_without_one(self):
        from studio_batch_driver import _research_guard
        controller = SimpleNamespace(root=self.root, install=self.install, job=lambda job_id: dict(job_id=job_id))
        with patch('studio_research_launch.pause_wanted', return_value=True), patch('studio_batch_pause.request') as request:
            self.assertTrue(_research_guard(controller, 'b1', dict(attempt_id='a'), 7.0, None))
            self.assertFalse(_research_guard(controller, 'b1', dict(attempt_id='a'), 8.0, dict(state='pausing')))
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['requested_by'], 'research_launch_guard')
        with patch('studio_research_launch.pause_wanted', side_effect=RuntimeError('boom')):
            self.assertFalse(_research_guard(controller, 'b1', {}, 9.0, None))  # never raises into the driver

    def test_keeper_holds_while_busy_and_exits_after_the_idle_grace(self):
        api = FakeApi();states = iter([2, 2, 0, 0, 0, 0])
        api.active_processes = lambda job: next(states)
        api.create_mutex = lambda name: ('MUTEX', False)
        clock = iter([0, 2, 4, 6, 8, 10, 12])
        code = r.keep(self.root, self.name, api=api, clock=lambda: next(clock), sleep=lambda s: None, idle_seconds=4)
        self.assertEqual(code, 0)
        beat = json.loads((self.root / 'research-launch' / 'keeper.json').read_text(encoding='utf-8'))
        self.assertEqual((beat['state'], beat['job']), ('stopped', self.name))
        self.assertIn(('close', 'JOB'), api.calls);self.assertIn(('close', 'MUTEX'), api.calls)

    def test_a_second_keeper_leaves_the_job_to_the_first(self):
        api = FakeApi();api.create_mutex = lambda name: ('MUTEX', True)
        self.assertEqual(r.keep(self.root, self.name, api=api, sleep=lambda s: None), 0)
        self.assertNotIn('open_job', api.names())


# ---------------------------------------------------------------- status fields

def tester_log(lines):
    return '\ufeff' + '\r\n'.join(lines) + '\r\n'


FAN_OUT = (['DD\t0\t06:01:41.100\tTester\tgenetic optimization started'] +
           ['NS\t0\t06:01:41.%03d\tCore %02d\tagent process started on 127.0.0.1:%d' % (110 + i, i, 3047 + i) for i in range(1, 25)] +
           ['MG\t0\t06:01:41.565\tCore 01\tconnecting to 127.0.0.1:3048', 'FR\t0\t06:01:41.586\tCore 01\tconnected',
            'XX\t0\t06:05:00.000\tCore 07\tconnection to 127.0.0.1:3054 lost',
            'XX\t0\t06:05:01.000\tCore 07\tagent process started on 127.0.0.1:3054',
            'XX\t0\t06:09:00.000\tTester\tauthorized tester agent 127.0.0.1:3060 disconnected',
            'XX\t0\t06:20:05.000\tCore 01\tconnection closed'])


class StatusTests(Workspace):
    def test_parse_counts_the_newest_fan_out_restarts_and_losses(self):
        older = ['A\t0\t05:00:00.000\tCore %02d\tagent process started on 127.0.0.1:%d' % (i, 3000 + i) for i in range(1, 9)]
        seen = r.parse_tester_log(older + FAN_OUT)
        self.assertEqual((seen['enabled_mt5_workers'], seen['agent_restarts'], seen['agent_losses'], seen['agents_started_local_time']),
                         (24, 1, 2, '06:01:41.111'))
        self.assertIsNone(r.parse_tester_log(['no fan-out here']))

    def test_status_reports_policy_job_guard_keeper_and_real_agent_count(self):
        log = self.data / 'Tester' / 'logs' / '20261005.log'
        api = FakeApi();self.launch(api, dict(OWNER, publishers=[dict(label='Exp 01', cycle_log='C:\\x.jsonl', max_seconds=90)]),
                                    now=time.time() - 5)
        log.write_bytes(tester_log(FAN_OUT).encode('utf-16-le'))
        r._atomic_json(self.root / 'research-launch' / 'keeper.json', dict(state='holding', pid=77, job=self.name,
                                                                            heartbeat_wall=time.time()))
        api.flags, api.priority, api.rate, api.active = JOB_OBJECT_LIMIT_PRIORITY_CLASS, IDLE_PRIORITY_CLASS, 17, 25
        seen = r.status(self.install, self.root, api=api)
        self.assertEqual((seen['profile'], seen['creation_priority'], seen['agent_priority'], seen['cpu_cap_percent_planned']),
                         ('owner', 'idle', 'idle', 17))
        self.assertEqual((seen['enabled_mt5_workers'], seen['agent_count_source'], seen['agents']['agent_losses']), (24, 'tester_log', 2))
        self.assertEqual(seen['job'], dict(state='running', active_processes=25, limit_flags=JOB_OBJECT_LIMIT_PRIORITY_CLASS,
                                           priority_lock='idle', kill_on_job_close=False, cpu_rate_percent=17))
        self.assertEqual((seen['guard']['stage'], seen['guard']['cpu_rate_percent'], seen['guard']['paused']), (0, 17, False))
        self.assertEqual((seen['keeper']['state'], seen['last_launch']['job']['kill_on_job_close']), ('holding', False))

    def test_staging_reports_what_it_really_does(self):
        # Claude-Mac note 2: per member launch, gated on publishers and a holding keeper; never more.
        self.policy(OWNER)
        seen = r.status(self.install, self.root, api=FakeApi())
        self.assertEqual((seen['staging'], seen['staging_scope']), ('off_no_publishers', 'per_member_launch'))
        self.assertIn('never pauses the lane', seen['staging_plain'])
        publishers = [dict(label='Exp 01', cycle_log='C:\\x.jsonl', max_seconds=90)]
        self.launch(FakeApi(), dict(OWNER, publishers=publishers), now=time.time())
        self.assertEqual(r.status(self.install, self.root, api=FakeApi())['staging'], 'stalled_no_keeper')
        r._atomic_json(self.root / 'research-launch' / 'keeper.json', dict(state='holding', pid=7, job=self.name, heartbeat_wall=time.time()))
        seen = r.status(self.install, self.root, api=FakeApi())
        self.assertEqual(seen['staging'], 'active');self.assertIn('reset at the next member', seen['staging_plain'])
        path = self.root / 'research-launch' / 'guard.json'
        guard = json.loads(path.read_text(encoding='utf-8'));guard['paused'] = True;path.write_text(json.dumps(guard), encoding='utf-8')
        self.assertEqual(r.status(self.install, self.root, api=FakeApi())['staging'], 'paused')
        self.assertIsNone(r.status(self.install, Path(tempfile.mkdtemp()), api=FakeApi())['staging'])   # customer

    def test_keeper_records_whether_it_could_break_away_from_the_callers_job(self):
        # Evidence for Claude-Mac note 5: False means the caller's job (a Task Scheduler driver's) refuses breakaway.
        spawned = []

        def popen(args, **kwargs):
            spawned.append(kwargs['creationflags'])
            if kwargs['creationflags'] & r.CREATE_BREAKAWAY_FROM_JOB:raise PermissionError(5, 'Access is denied')
            r._atomic_json(self.root / 'research-launch' / 'keeper.json', dict(state='holding', pid=99, job=self.name,
                                                                                heartbeat_wall=time.time()))
            return SimpleNamespace(pid=99)
        with patch('studio_research_launch.subprocess.Popen', side_effect=popen):
            seen = r.start_keeper(self.root, self.name, now=time.time(), wait=1)
        self.assertEqual((seen['state'], seen['broke_away']), ('holding', False))
        self.assertTrue(spawned[0] & r.CREATE_BREAKAWAY_FROM_JOB);self.assertFalse(spawned[1] & r.CREATE_BREAKAWAY_FROM_JOB)

    def test_status_without_any_launch_is_the_plain_customer_default(self):
        seen = r.status(self.install, self.root, api=FakeApi())
        self.assertEqual((seen['profile'], seen['creation_priority'], seen['enabled_mt5_workers'], seen['job'], seen['last_launch']),
                         ('customer', 'below_normal', None, None, None))
        self.assertIn('below-normal priority', seen['plain'])

    def test_an_old_tester_log_is_not_counted_for_a_newer_launch(self):
        log = self.data / 'Tester' / 'logs' / '20261005.log';log.write_bytes(tester_log(FAN_OUT).encode('utf-16-le'))
        os.utime(log, (time.time() - 3600, time.time() - 3600))
        self.launch(FakeApi(), now=time.time())
        self.assertIsNone(r.status(self.install, self.root, api=FakeApi())['enabled_mt5_workers'])

    def test_proof_helpers_count_passes_and_publisher_overruns(self):
        lines = ['CS\t0\t06:%02d:00.000\tTester\t%d OnTester result 0.1 : passed in 0:01:00.000' % (m, m) for m in range(1, 11)]
        lines.append('CS\t0\t07:30:00.000\tTester\t99 OnTester result 0.1 : passed in 0:00:30.000')
        self.assertEqual(r.passes_per_minute(lines, since_local='06:00:00', until_local='07:00:00'),
                         dict(passes=10, passes_per_minute=1.11, first='06:01:00', last='06:10:00'))
        log = Path(self.tmp.name) / 'c.jsonl'
        log.write_text('\n'.join(json.dumps(x) for x in (
            dict(event='START', pid=1, startedAt=1000_000), dict(event='END', pid=1, startedAt=1000_000, endedAt=1050_000),
            dict(event='START', pid=2, startedAt=1100_000), dict(event='END', pid=2, startedAt=1100_000, endedAt=1883_000),
            dict(event='START', pid=3, startedAt=5000_000))) + '\n', encoding='utf-8')
        rows = r.publisher_window([dict(label='Exp 01', cycle_log=str(log), max_seconds=90)], 1020, 2000)
        self.assertEqual(rows, [dict(label='Exp 01', budget_seconds=90, cycles=2, max_seconds=783, over_budget=1)])

    def test_research_status_carries_the_research_launch_block(self):
        from studio_research_status import research_status
        self.launch(FakeApi(), now=time.time() - 5)
        (self.data / 'Tester' / 'logs' / '20261005.log').write_bytes(tester_log(FAN_OUT).encode('utf-16-le'))
        install = dict(self.install, controller_state_root=str(self.root), common_files_root=str(self.root))
        result = research_status(root=self.root, install=install, session={}, local=self.root / 'local', now=time.time(), jobs=[])
        self.assertEqual(result['enabled_mt5_workers'], 24)
        self.assertEqual((result['research_launch']['profile'], result['research_launch']['agent_count_source']),
                         ('customer', 'tester_log'))


# ---------------------------------------------------------------- real Windows (Python children only, never MT5)

def _kill(pid):
    handle = ctypes.windll.kernel32.OpenProcess(0x1, False, pid)     # PROCESS_TERMINATE
    if handle:
        ctypes.windll.kernel32.TerminateProcess(handle, 1);ctypes.windll.kernel32.CloseHandle(handle)


def _alive(pid):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)                # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


@unittest.skipUnless(os.name == 'nt', 'Windows job objects')
class RealWindowsTests(Workspace):
    def setUp(self):
        super().setUp()
        self.api = r.Win32Jobs();self.held = []
        self.cwd = tempfile.gettempdir()      # never the test folder: a live child would pin it
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for job in self.held:
            try:self.api.terminate_job(job)
            except (OSError, ValueError):pass
            self.api.close(job)

    def holding_keeper(self, root, name, *, now=None):
        job = self.api.open_job(name, write=True, terminate=True);self.held.append(job)
        return dict(state='test')

    def child(self, code):
        return [sys.executable, '-B', '-c', code]

    def wait_members(self, job, count, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ids = self.api.process_ids(job)
            infos = [self.api.process_info(i) for i in ids]
            pythons = [info for info in infos if info and info[0] and Path(info[0]).name.lower() == 'python.exe']
            if len(pythons) >= count:return pythons
            time.sleep(.1)
        self.fail('job members did not appear')

    def test_owner_child_and_grandchild_run_idle_in_the_job_and_outlive_closed_handles(self):
        plan = plan_of(OWNER)
        code = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]); time.sleep(30)'
        launched = r.launch_plan(self.api, plan, self.child(code), cwd=self.cwd, name=self.name, root=self.root,
                                 keeper=self.holding_keeper)
        job = self.held[0]
        self.assertIsNone(launched.poll())
        pythons = self.wait_members(job, 2)
        self.assertEqual({priority for _, priority in pythons}, {IDLE_PRIORITY_CLASS})
        flags, priority = self.api.query_limits(job)
        self.assertEqual((flags, priority), (JOB_OBJECT_LIMIT_PRIORITY_CLASS, IDLE_PRIORITY_CLASS))
        self.assertFalse(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertEqual(self.api.query_cpu_rate(job), 17)
        pid = launched.pid;launched.close()
        ids = self.api.process_ids(job)
        self.api.close(self.held.pop())                                     # every GOAT handle to the job is closed now
        time.sleep(.5)
        self.assertIsNotNone(self.api.process_info(pid), 'closing the last job handle must not kill MT5 (no KILL_ON_JOB_CLOSE)')
        for member in ids:_kill(member)

    def test_real_access_denied_assignment_refuses_and_nothing_ran(self):
        api = self.api

        created = []
        self.addCleanup(lambda: [_kill(pid) for pid in created])            # never strand a suspended child

        class QueryOnlyAssign(r.Win32Jobs):
            def create_suspended(self, command_line, cwd, flags):
                handles = super().create_suspended(command_line, cwd, flags);created.append(handles[2])
                return handles

            def assign(self, job, process):
                weak = api.open_job(name)                                   # QUERY access only -> ERROR_ACCESS_DENIED
                try:return super().assign(weak, process)
                finally:api.close(weak)

        name = self.name
        marker = Path(self.tmp.name) / 'ran.txt'
        refused = QueryOnlyAssign()
        with self.assertRaisesRegex(ResearchLaunchRefused, 'access denied') as caught:
            r.launch_plan(refused, plan_of(OWNER), self.child('open(%r,"w").write("ran")' % str(marker)), cwd=self.cwd,
                          name=name, root=self.root, keeper=self.holding_keeper)
        self.assertIn('never starts research MT5 at normal priority', str(caught.exception))
        time.sleep(1)
        self.assertFalse(marker.exists(), 'the suspended process must never run')
        self.assertFalse((self.root / 'research-launch' / 'launch.json').exists())
        self.assertEqual(self.held, [])                                     # refused before any keeper

    def test_nested_job_assignment_works_from_inside_another_job(self):
        outer_name = r.JOB_PREFIX + 'f' * 32
        outer, _ = self.api.create_job(outer_name);self.held.append(outer)
        self.api.set_limits(outer, 0, None)
        result = Path(self.tmp.name) / 'nested.json'
        code = ('import json,sys,time\n'
                'sys.path.insert(0,%r)\n'
                'import studio_research_launch as r\n'
                'api=r.Win32Jobs();held=[]\n'
                'def keep(root,name,now=None):\n'
                '    held.append(api.open_job(name,write=True,terminate=True));return dict(state="test")\n'
                'plan=r.effective(r.validate_policy(dict(schema=r.SCHEMA,profile="owner")))\n'
                'out=dict()\n'
                'try:\n'
                '    child=r.launch_plan(api,plan,[sys.executable,"-c","import time;time.sleep(20)"],cwd=%r,name=%r,root=%r,keeper=keep)\n'
                '    time.sleep(.5);info=api.process_info(child.pid)\n'
                '    out=dict(ok=True,priority=info[1],limits=list(api.query_limits(held[0])),members=len(api.process_ids(held[0])),\n'
                '             broke_away=child.record["broke_away"])\n'
                '    api.terminate_job(held[0])\n'
                'except Exception as error:\n'
                '    out=dict(ok=False,error=str(error))\n'
                'open(%r,"w").write(json.dumps(out))\n') % (str(HERE), self.cwd, self.name, str(self.root), str(result))
        process, thread, pid = self.api.create_suspended(subprocess.list2cmdline(self.child(code)), self.cwd,
                                                         CREATE_SUSPENDED | CREATE_NO_WINDOW)
        try:
            self.api.assign(outer, process);self.api.resume(thread)
            deadline = time.monotonic() + 20
            while not result.exists() and time.monotonic() < deadline:time.sleep(.1)
        finally:
            self.api.close(thread);self.api.close(process)
        value = json.loads(result.read_text())
        self.assertTrue(value.get('ok'), value)
        self.assertEqual((value['priority'], value['limits']), (IDLE_PRIORITY_CLASS, [JOB_OBJECT_LIMIT_PRIORITY_CLASS, IDLE_PRIORITY_CLASS]))
        self.assertIs(value['broke_away'], False)                           # the outer job refuses breakaway: nested

    def test_terminating_the_drivers_task_job_spares_research_mt5_that_broke_away(self):
        # Claude-Mac note 5, mechanism only (the T3 -TaskStopCheck proves it with Task Scheduler and MT5):
        # Task Scheduler ends a stopped task, or one past its ExecutionTimeLimit, by terminating the task's
        # job. Here a driver (a Python child) runs inside such an outer job, starts a research launch, and the
        # outer job is then terminated. MT5 (a sleeping Python child) survives exactly when it broke away.
        for breakaway_ok in (True, False):
            with self.subTest(breakaway_ok=breakaway_ok):
                value, survived = self.task_job_stop(breakaway_ok)
                self.assertEqual(survived, value['broke_away'], value)
                if not breakaway_ok:
                    self.assertIs(value['broke_away'], False)               # nested, as before: ends with the task
                elif not value['broke_away']:
                    self.skipTest('this test process runs inside a job that refuses breakaway, so the driver cannot break away')

    def task_job_stop(self, breakaway_ok):
        outer, _ = self.api.create_job(r.JOB_PREFIX + ('e' if breakaway_ok else 'd') * 32);self.held.append(outer)
        self.api.set_limits(outer, r.JOB_OBJECT_LIMIT_BREAKAWAY_OK if breakaway_ok else 0, None)
        result = Path(self.tmp.name) / ('task-%s.json' % breakaway_ok)
        code = ('import json,sys,time\n'
                'sys.path.insert(0,%r)\n'
                'import studio_research_launch as r\n'
                'api=r.Win32Jobs()\n'
                'plan=r.effective(r.validate_policy(dict(schema=r.SCHEMA,profile="owner")))\n'
                'try:\n'
                '    child=r.launch_plan(api,plan,[sys.executable,"-c","import time;time.sleep(60)"],cwd=%r,name=%r,root=%r,\n'
                '                        keeper=lambda root,name,now=None:dict(state="test"))\n'
                '    out=dict(ok=True,pid=child.pid,broke_away=child.record["broke_away"])\n'
                'except Exception as error:\n'
                '    out=dict(ok=False,error=str(error))\n'
                'open(%r,"w").write(json.dumps(out))\n'
                'time.sleep(60)\n') % (str(HERE), self.cwd, self.name, str(self.root), str(result))
        process, thread, _ = self.api.create_suspended(subprocess.list2cmdline(self.child(code)), self.cwd,
                                                       CREATE_SUSPENDED | CREATE_NO_WINDOW)
        value = {}
        try:
            self.api.assign(outer, process);self.api.resume(thread)
            deadline = time.monotonic() + 20
            while not result.exists() and time.monotonic() < deadline:time.sleep(.1)
            value = json.loads(result.read_text())
            self.assertTrue(value.get('ok'), value)
            self.api.terminate_job(outer)                                   # what a task stop or time limit does
            deadline = time.monotonic() + 10
            while self.api.exit_code(process) is None and time.monotonic() < deadline:time.sleep(.1)
            self.assertIsNotNone(self.api.exit_code(process), 'the driver must end with its task job')
            time.sleep(.5)
            return value, _alive(value['pid'])
        finally:
            if value.get('pid'):_kill(value['pid'])                         # the research child never outlives the test
            self.api.terminate_job(outer)
            self.api.close(thread);self.api.close(process)

    def test_customer_default_is_below_normal_and_creates_no_job(self):
        launched = r.launch_plan(self.api, plan_of(None), self.child('import time;time.sleep(20)'), cwd=self.cwd,
                                 name=self.name, root=self.root, keeper=self.holding_keeper)
        try:
            self.assertEqual(self.api.process_info(launched.pid)[1], BELOW_NORMAL_PRIORITY_CLASS)
            self.assertIsNone(self.api.open_job(self.name))
            self.assertEqual(self.held, [])
        finally:
            _kill(launched.pid);launched.close()

    def test_a_null_job_handle_is_refused_before_windows_sees_it(self):
        # kernel32 is unplugged first: even with the guard removed (mutation check) no call may reach
        # Windows, which would apply a NULL job call to this process's own job.
        api = r.Win32Jobs()

        def forbidden(*args):
            raise AssertionError('reached kernel32 with a NULL job handle')
        for attr in ('_SetInformationJobObject', '_QueryInformationJobObject', '_AssignProcessToJobObject',
                     '_IsProcessInJob', '_TerminateJobObject'):
            setattr(api, attr, forbidden)
        for call in (lambda: api.query_limits(None), lambda: api.set_cpu_rate(None, 17), lambda: api.set_limits(0, 0, None),
                     lambda: api.process_ids(None), lambda: api.active_processes(None), lambda: api.query_cpu_rate(None),
                     lambda: api.assign(None, 1), lambda: api.in_job(1, None), lambda: api.terminate_job(None)):
            with self.assertRaisesRegex(ValueError, 'NULL job handle'):
                call()


if __name__ == '__main__':
    unittest.main()
