"""Windows process inventory through a WMI stall, and an unconfirmed launch resolved from its task (goatai#1885 PR D).

T2 and Banker, 2026-10-05: ``Get-CimInstance Win32_Process`` (normally 0.3 s) stalled past its 20 s
timeout and the raised TimeoutExpired killed three drivers. Inventory queries now retry (4 attempts,
2/5/10 s pauses), log every failed attempt and still fail closed. A launch whose driver never reported
is resolved from the Windows task's own state instead of blocking every retry forever.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import demo_agent
from demo_agent import DemoAgent, read_json, write_json
import studio_process_query as query
import test_demo_agent as demo_fixture
import test_demo_lane_driver as lane_fixture
import test_demo_seed_agent as seed_agent_fixture


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'process-query.jsonl'
        query.configure(self.log); self.addCleanup(query.configure, None)
        self.pauses = []
        sleeper = patch.object(query, 'sleep', side_effect=self.pauses.append); sleeper.start(); self.addCleanup(sleeper.stop)
        steady = patch.object(query, 'uniform', return_value=1.0); steady.start(); self.addCleanup(steady.stop)

    def lines(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()] if self.log.exists() else []

    def test_a_stall_that_clears_returns_the_rows_and_logs_each_failed_attempt(self):
        stall = subprocess.TimeoutExpired('powershell', 20)
        with patch('subprocess.check_output', side_effect=[stall, stall, '[{"ProcessId": 1}]']) as call:
            output = query.powershell_text('Get-CimInstance Win32_Process', purpose='test inventory')
        self.assertEqual((output, call.call_count, self.pauses), ('[{"ProcessId": 1}]', 3, [2, 5]))
        logged = self.lines()
        self.assertEqual([l.get('attempt') for l in logged[:2]], [1, 2])
        self.assertTrue(all(l['error'] == 'timed out after 20s' and l['purpose'] == 'test inventory' for l in logged[:2]))
        self.assertEqual((logged[2]['outcome'], logged[2]['attempts']), ('recovered_after', 3))
        self.assertEqual(call.call_args.kwargs['timeout'], 20)
        self.assertIn('creationflags', call.call_args.kwargs)

    def test_a_stall_that_never_clears_still_fails_closed_with_the_same_exception(self):
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)) as call:
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                query.powershell_text('Get-CimInstance Win32_Process', purpose='test inventory')
        self.assertEqual((call.call_count, self.pauses), (4, [2, 5, 10]))
        self.assertIn('did not answer in 4 attempts', ' '.join(getattr(raised.exception, '__notes__', [])))
        self.assertEqual(self.lines()[-1]['outcome'], 'gave_up')

    def test_a_cim_error_is_retried_too_and_other_errors_are_not(self):
        failure = subprocess.CalledProcessError(1, 'powershell')
        with patch('subprocess.check_output', side_effect=[failure, '[]']) as call:
            self.assertEqual(query.powershell_text('x', purpose='p'), '[]')
        self.assertEqual(call.call_count, 2)
        with patch('subprocess.check_output', side_effect=FileNotFoundError('powershell missing')) as call:
            with self.assertRaises(FileNotFoundError):
                query.powershell_text('x', purpose='p')
        self.assertEqual(call.call_count, 1)

    def test_a_poller_budget_bounds_the_attempts_and_their_timeouts(self):
        # Claude-Mac (#1885): status reads and polls never stack 4 x 20 s inside their own loop.
        clock = [100.0]
        def ticking(*args, **kwargs):
            clock[0] += kwargs['timeout']
            raise subprocess.TimeoutExpired('powershell', kwargs['timeout'])
        def pause(seconds):
            self.pauses.append(seconds); clock[0] += seconds
        with patch.object(query, 'monotonic', side_effect=lambda: clock[0]), patch.object(query, 'sleep', side_effect=pause), \
                patch('subprocess.check_output', side_effect=ticking) as call:
            with self.assertRaises(subprocess.TimeoutExpired):
                query.powershell_text('x', purpose='status read', budget=25)
        timeouts = [c.kwargs['timeout'] for c in call.call_args_list]
        self.assertLessEqual(sum(timeouts) + sum(self.pauses), 25.5)
        self.assertEqual(timeouts[0], 20)

    def test_retry_pauses_are_jittered_so_two_drivers_do_not_retry_in_lockstep(self):
        # Claude-Mac (#1885 PR D addendum c): stalls cluster at an MT5 launch; each pause varies by up to 25%.
        stall = subprocess.TimeoutExpired('powershell', 20)
        with patch.object(query, 'uniform', side_effect=[0.75, 1.25, 1.1]) as factor, \
                patch('subprocess.check_output', side_effect=[stall, stall, stall, '[]']):
            self.assertEqual(query.powershell_text('x', purpose='p'), '[]')
        self.assertEqual([round(p, 6) for p in self.pauses], [1.5, 6.25, 11.0])
        self.assertEqual({c.args for c in factor.call_args_list}, {(0.75, 1.25)})

    def test_the_attempt_log_is_bounded(self):
        with patch.object(query, 'MAX_LOG_BYTES', 300), \
                patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)):
            for _ in range(3):
                with self.assertRaises(subprocess.TimeoutExpired):
                    query.powershell_text('x', purpose='p')
        older = self.log.with_name('process-query.1.jsonl')
        self.assertTrue(older.is_file())
        self.assertLess(self.log.stat().st_size, 300 + 400)                     # one generation kept, never unbounded

    def test_the_seed_driver_inventory_survives_a_stall(self):
        from studio_seed_process import WindowsSeedProcess
        controller = types.SimpleNamespace(install=dict(terminal_executable='C:\\MT5\\terminal64.exe'))
        row = dict(ProcessId=7, ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc='2026-10-05T12:13:00Z')
        stall = subprocess.TimeoutExpired('powershell', 20)
        with patch('subprocess.check_output', side_effect=[stall, json.dumps([row])]):
            found = WindowsSeedProcess(controller).inspect()
        self.assertEqual(found, dict(pid=7, executable='C:\\MT5\\terminal64.exe', created_utc='2026-10-05T12:13:00Z'))
        with patch('subprocess.check_output', side_effect=stall):
            with self.assertRaises(subprocess.TimeoutExpired):
                WindowsSeedProcess(controller).inspect()            # never read as "MT5 closed"

    def test_every_inventory_call_site_goes_through_the_retry(self):
        """No controller module runs a Win32_Process query through a bare check_output any more."""
        import ast
        import re
        wmi = re.compile(r'Win32_Process\b')                       # not Win32_Processor
        offenders = []
        for path in sorted(Path(__file__).parent.glob('*.py')):
            if path.name.startswith('test_') or path.name == 'studio_process_query.py':
                continue
            text = path.read_text(encoding='utf-8-sig')
            if not wmi.search(text):
                continue
            tree = ast.parse(text)

            def own(scope):
                """Every node of one scope, not descending into nested functions."""
                stack, found = list(ast.iter_child_nodes(scope)), []
                while stack:
                    node = stack.pop()
                    found.append(node)
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                        stack.extend(ast.iter_child_nodes(node))
                return found
            scopes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.Module))]
            for scope in scopes:
                body = own(scope)
                # Names this scope binds to a command that queries Win32_Process (module constants count everywhere).
                names = {t.id for n in body if isinstance(n, ast.Assign) and wmi.search(ast.get_source_segment(text, n.value) or '')
                         for t in n.targets if isinstance(t, ast.Name)}
                names |= {t.id for n in tree.body if isinstance(n, ast.Assign) and wmi.search(ast.get_source_segment(text, n.value) or '')
                          for t in n.targets if isinstance(t, ast.Name)}
                for node in body:
                    if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) in ('check_output', 'run', 'Popen') and node.args:
                        argv = node.args[0]
                        last = argv.elts[-1] if isinstance(argv, ast.List) and argv.elts else None
                        if (isinstance(last, ast.Name) and last.id in names) or wmi.search(ast.get_source_segment(text, argv) or ''):
                            offenders.append('%s:%d' % (path.name, node.lineno))
        self.assertEqual(sorted(set(offenders)), [])


class LaunchIdentityTests(unittest.TestCase):
    """PR D addendum (a)/(b): the post-launch identity wait tolerates a stall; a missing path is read from the process."""
    EXE = 'C:\\MT5\\terminal64.exe'

    def setUp(self):
        from studio_seed_process import WindowsSeedProcess
        self.clock = [0.0]
        controller = types.SimpleNamespace(install=dict(terminal_executable=self.EXE))
        self.process = WindowsSeedProcess(controller, sleep=self.advance, monotonic=lambda: self.clock[0])
        self.identity = dict(pid=7, executable=self.EXE, created_utc='2026-10-05T13:43:53.1234560Z')
        self.child = types.SimpleNamespace(pid=7, poll=lambda: None)
        popen = patch('studio_seed_process.subprocess.Popen', side_effect=lambda *a, **k: self.child); popen.start()
        self.addCleanup(popen.stop)

    def advance(self, seconds):
        self.clock[0] += seconds

    def inspections(self, *steps):
        """inspect(): the pre-launch read (no MT5), then ``steps``; each read costs 20 s when it stalls, else 1 s."""
        queue = [None] + list(steps)
        calls = []

        def inspect(timeout=20, budget=None):
            calls.append(dict(timeout=timeout, budget=budget))
            step = queue.pop(0) if queue else queue_end
            if isinstance(step, BaseException):
                self.advance(20 if isinstance(step, subprocess.TimeoutExpired) else 1)
                raise step
            self.advance(1)
            return copy.deepcopy(step)
        queue_end = subprocess.TimeoutExpired('powershell', 20)
        self.process.inspect = inspect
        return calls

    def test_a_stall_right_after_the_launch_is_not_seen_yet_and_the_identity_is_returned(self):
        from studio_seed_process import UNKNOWN_EXECUTABLE
        calls = self.inspections(subprocess.TimeoutExpired('powershell', 20), subprocess.CalledProcessError(1, 'powershell'),
                                 ValueError(UNKNOWN_EXECUTABLE), None, dict(self.identity))
        self.assertEqual(self.process.start('C:\\data\\config\\GOATStudio\\Seeds\\Se4_00001.ini'), self.identity)
        self.assertTrue(all(c['budget'] is not None and c['budget'] <= 90 for c in calls[1:]))   # each read inside the window

    def test_the_window_is_bounded_and_names_what_was_not_seen(self):
        self.inspections()                                   # every read stalls
        with self.assertRaisesRegex(ValueError, r'Terminal startup identity not observed in 90 s \(the inventory timed out\); '
                                                'inspect before recovery'):
            self.process.start('x.ini')
        self.assertLess(self.clock[0], 90 + 20 + 2)

    def test_a_wrong_pid_two_processes_or_an_exit_refuse_at_once(self):
        for label, steps, child, pattern in (
                ('a different PID', [dict(self.identity, pid=8)], None, 'PID differs'),
                ('two selected terminals', [ValueError('Multiple selected-terminal processes; inspect ownership first')], None, 'Multiple'),
                ('MT5 exited', [None], types.SimpleNamespace(pid=7, poll=lambda: 1), 'exited before startup identity')):
            with self.subTest(label):
                self.clock[0] = 0.0
                if child:
                    self.child = child
                self.inspections(*steps)
                with self.assertRaisesRegex(ValueError, pattern):
                    self.process.start('x.ini')
                self.assertLess(self.clock[0], 5)            # no waiting out the window

    def test_a_missing_path_is_filled_from_the_process_and_still_refuses_when_that_read_fails(self):
        from studio_seed_process import UNKNOWN_EXECUTABLE, WindowsSeedProcess
        row = dict(ProcessId=29608, ExecutablePath=None, CreatedUtc=self.identity['created_utc'])
        filled = []
        self.process.image_path = lambda r: filled.append(r['ProcessId']) or self.EXE
        with patch.object(WindowsSeedProcess, '_rows', return_value=[dict(row)]):
            self.assertEqual(self.process.inspect(), dict(pid=29608, executable=self.EXE, created_utc=row['CreatedUtc']))
        self.assertEqual(filled, [29608])
        self.process.image_path = lambda r: None             # OpenProcess denied, or a reused PID: no proof
        with patch.object(WindowsSeedProcess, '_rows', return_value=[dict(row)]):
            with self.assertRaisesRegex(ValueError, UNKNOWN_EXECUTABLE):
                self.process.inspect()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process API')
    def test_the_process_api_read_is_bound_to_the_rows_creation_time(self):
        import ctypes
        from ctypes import wintypes
        from datetime import datetime, timedelta, timezone
        from studio_seed_process import process_image_path
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        times = [wintypes.FILETIME() for _ in range(4)]
        self.assertTrue(kernel.GetProcessTimes(kernel.GetCurrentProcess(), *[ctypes.byref(t) for t in times]))
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        created = (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)).strftime('%Y-%m-%dT%H:%M:%S.%f') + '0Z'
        image = ctypes.create_unicode_buffer(32768)
        ctypes.WinDLL('kernel32').GetModuleFileNameW(None, image, 32768)
        found = process_image_path(os.getpid(), created)
        self.assertEqual(os.path.normcase(found or ''), os.path.normcase(image.value))
        self.assertIsNone(process_image_path(os.getpid(), '2000-01-01T00:00:00.0000000Z'))   # same PID, other process
        self.assertIsNone(process_image_path(os.getpid(), 'unreadable'))
        self.assertIsNone(process_image_path(0, created))


class DemoLaneReidentifyTests(unittest.TestCase):
    """The demo lane end to end: seed-resume (under the terminal lock) adopts its own launch and journals it."""
    ORPHAN = 29608
    setUp_agent = seed_agent_fixture.DemoSeedAgentTests.setUp
    database, new_agent, manifest, finish_member, actions = (
        seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent,
        seed_agent_fixture.DemoSeedAgentTests.manifest, seed_agent_fixture.DemoSeedAgentTests.finish_member,
        seed_agent_fixture.DemoSeedAgentTests.actions)

    def setUp(self):
        self.setUp_agent()
        self.line = ''
        self.process.command_line = lambda identity: self.line if identity.get('pid') == self.ORPHAN else '"terminal64.exe"'
        self.process.config_users = lambda names: ([dict(pid=self.ORPHAN, executable='terminal64.exe')]
                                                   if self.process.current and self.process.current.get('pid') == self.ORPHAN
                                                   and any(n.casefold() in self.line.casefold() for n in names) else [])

    def sleep(self, seconds):
        self.now += seconds
        current = self.process.current or {}
        if current.get('pid') == self.ORPHAN:
            self.finish_member(0)                            # the adopted MT5 finishes member 1 and exits
        elif str(current.get('created_utc', '')).startswith('member'):
            self.finish_member(len(self.process.starts) - 1)

    def strand(self):
        from datetime import datetime, timezone
        from studio_seed_process import STARTUP_UNSEEN
        self.agent.seed_prepare('batch', self.plan)
        real = self.process.start

        def orphan(config):
            self.process.starts.append(str(config))
            created = datetime.fromtimestamp(self.now + .5, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + '0Z'
            self.process.current = dict(pid=self.ORPHAN, executable='terminal64.exe', created_utc=created)
            self.line = '"terminal64.exe" "/config:' + str(Path(config).resolve()) + '"'
            raise ValueError(STARTUP_UNSEEN + ' in 90 s (the inventory timed out); inspect before recovery')
        self.process.start = orphan
        with self.assertRaisesRegex(ValueError, 'Terminal startup identity not observed'):
            self.agent.seed_start('batch', 30)
        self.process.start = real
        self.assertEqual(self.agent.seed_status('batch')['seed']['status'], 'reconcile_required')   # a read never adopts

    def test_seed_resume_adopts_its_own_launch_journals_it_and_finishes_the_hunt(self):
        self.strand()
        result = self.agent.seed_resume('batch', 60)
        self.assertEqual((result['status'], [m['status'] for m in result['members']]), ('completed', ['completed', 'completed']))
        rows = [a for a in self.actions() if (a['operation'], a['phase']) == ('seed_resume', 'reidentified')]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['alias'], rows[0]['process']['pid']), (self.manifest()['members'][0]['alias'], self.ORPHAN))
        self.assertTrue(rows[0]['prior_error'].startswith('Terminal startup identity not observed'))
        self.assertEqual(len(self.process.starts), 2)        # the orphan launch and member 2; nothing re-run

    def test_seed_reconcile_adopts_under_the_lock_and_points_at_seed_resume(self):
        self.strand()
        result = self.agent.seed_reconcile('batch')
        self.assertEqual((result['status'], result['members'][0]['status']), ('active', 'running'))
        self.assertIn('seed-resume drives it', result['next_action'])
        self.assertIn(('seed_reconcile', 'reidentified'), [(a['operation'], a['phase']) for a in self.actions()])


class LaneLaunchResolutionTests(unittest.TestCase):
    """The detached seed/catch-up/hold-up driver (GOAT-EA#162) resolves an unconfirmed launch like run-batch."""
    setUp = seed_agent_fixture.DemoSeedAgentTests.setUp
    database, new_agent, sleep, manifest, finish_member, actions = (
        seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent,
        seed_agent_fixture.DemoSeedAgentTests.sleep, seed_agent_fixture.DemoSeedAgentTests.manifest,
        seed_agent_fixture.DemoSeedAgentTests.finish_member, seed_agent_fixture.DemoSeedAgentTests.actions)
    launched, worker = lane_fixture.LaneDriverTests.launched, lane_fixture.LaneDriverTests.worker

    @staticmethod
    def task(exists=True, state='Ready', last_run=None, last_result=267011):
        return dict(exists=exists, state=state, last_run_utc=last_run, last_result=last_result)

    def unconfirmed(self, argv, *, log_path, worker_path):
        envelope = Path(str(log_path)[:-4] + '.launch.json')
        write_json(envelope, dict(started=str(envelope)[:-12] + '.started.json', finished=str(envelope)[:-12] + '.finished.json',
                                  task_name='GOAT-Demo-' + 'c' * 16 + '-' + argv[argv.index('--nonce') + 1]))
        write_json(worker_path, dict(read_json(worker_path), launch_envelope=str(envelope)))
        raise ValueError('Persistent bootstrap unconfirmed; inspect the same launch/task, never issue another')

    def test_a_lane_launch_is_retried_only_after_its_never_started_task_is_removed(self):
        self.agent.seed_prepare('batch', self.plan)
        with patch('studio_durable_driver.launch', side_effect=self.unconfirmed):
            with self.assertRaisesRegex(ValueError, 'could not be confirmed .*the same seed-start runs again only once Windows '
                                                    'shows that task never ran'):
                self.agent.seed_start('batch', 60, detach=True)
        old = self.worker()
        self.assertEqual(old['status'], 'launch_unconfirmed')
        calls, launch = self.launched()
        with launch, patch('studio_durable_driver.task_info', return_value=self.task(state='Running')), \
                patch('studio_durable_driver.unregister_task', side_effect=AssertionError('never while it may run')):
            with self.assertRaisesRegex(ValueError, 'never duplicate'):
                self.agent.seed_start('batch', 60, detach=True)
        with launch, patch('studio_durable_driver.task_info', return_value=self.task()), \
                patch('studio_durable_driver.unregister_task', side_effect=ValueError('could not be removed; inspect it, never duplicate')):
            with self.assertRaisesRegex(ValueError, 'could not be removed'):
                self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual((calls, self.worker()['nonce']), ([], old['nonce']))
        # A status read is bounded and has no effect; it shows the launch never started.
        with patch('studio_durable_driver.task_info', return_value=self.task()) as info, \
                patch('studio_durable_driver.unregister_task', side_effect=AssertionError('a read has no effect')):
            driver = self.agent.seed_status('batch')['driver']
        self.assertEqual((driver['alive'], driver['launch_never_started']), (False, True))
        self.assertEqual(info.call_args.kwargs['budget'], 25)
        with launch, patch('studio_durable_driver.task_info', return_value=self.task()), \
                patch('studio_durable_driver.unregister_task') as removed:
            result = self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual(result['status'], 'driver_starting')
        self.assertEqual(removed.call_args.args[0], 'GOAT-Demo-' + 'c' * 16 + '-' + old['nonce'])
        self.assertNotEqual(self.worker()['nonce'], old['nonce'])
        logged = [a for a in self.actions() if (a['operation'], a['phase']) == ('detached_driver', 'launch_never_started')]
        self.assertEqual((len(logged), logged[0]['kind'], logged[0]['nonce']), (1, 'seed', old['nonce']))

    def test_a_lane_worker_waits_for_the_lock_and_records_a_lock_timeout(self):
        path = self.root / 'demo-agent/lane-workers/seed-batch.json'; path.parent.mkdir(parents=True)
        write_json(path, dict(schema_version=1, kind='seed', batch_id='batch', nonce='n' * 32, status='spawned', initial=True, max_seconds=60))
        waits = []

        @contextmanager
        def busy(*, wait_seconds=0):
            waits.append(wait_seconds)
            raise ValueError('Another demo agent operation owns this terminal')
            yield
        with patch.object(self.agent, '_exclusive', side_effect=busy):
            with self.assertRaisesRegex(ValueError, 'owns this terminal'):
                self.agent._drive_lane('seed', 'batch', 'n' * 32, 60, True)
        self.assertEqual(waits, [120])
        self.assertEqual(read_json(path)['status'], 'failed')
        self.assertIn('stayed busy for 120 s; the seed driver did not start', read_json(path)['error'])


class LaunchResolutionTests(unittest.TestCase):
    """An unconfirmed launch: the driver never reported. The task's own state decides, never a guess."""
    setUp = demo_fixture.DemoAgentTests.setUp

    def envelope(self, *, started=False, finished=False):
        folder = self.agent.state_root / 'workers'; folder.mkdir(parents=True, exist_ok=True)
        nonce = 'a' * 32
        prefix = folder / ('batch-' + nonce)
        envelope = Path(str(prefix) + '.launch.json')
        write_json(envelope, dict(started=str(prefix) + '.started.json', finished=str(prefix) + '.finished.json',
                                  task_name='GOAT-Demo-' + 'b' * 16 + '-' + nonce))
        if started:
            write_json(Path(str(prefix) + '.started.json'), dict(pid=999999, nonce=nonce))
        if finished:
            write_json(Path(str(prefix) + '.finished.json'), dict(exit_code=0, nonce=nonce))
        record = dict(schema_version=1, batch_id='batch', nonce=nonce, status='launch_unconfirmed', resume=False,
                      max_seconds=600, launch_envelope=str(envelope))
        write_json(folder / 'batch.json', record)
        return record

    @staticmethod
    def task(exists=True, state='Ready', last_run=None, last_result=267011):
        return dict(exists=exists, state=state, last_run_utc=last_run, last_result=last_result)

    def test_a_task_that_may_still_start_a_driver_never_allows_a_duplicate(self):
        record = self.envelope()
        for label, info in (('running', self.task(state='Running')), ('queued', self.task(state='Queued')),
                            ('ran since the envelope', self.task(last_run='2999-01-01T00:00:00+00:00')),
                            ('it ran (a result other than has-not-run)', self.task(last_result=0))):
            with self.subTest(label), patch('studio_durable_driver.task_info', return_value=info):
                with self.assertRaisesRegex(ValueError, 'launch unresolved \\(its task is .*\\); wait for it, never duplicate'):
                    self.agent._worker_alive(record)

    def test_a_task_that_provably_never_ran_is_not_a_driver_and_a_status_read_has_no_effect(self):
        record = self.envelope()
        for info in (self.task(), self.task(exists=False), self.task(last_run='2000-01-01T00:00:00+00:00')):
            with self.subTest(info), patch('studio_durable_driver.task_info', return_value=info), \
                    patch('studio_durable_driver.unregister_task', side_effect=AssertionError('no effect without retire')):
                self.assertFalse(self.agent._worker_alive(record))
        with patch('studio_durable_driver.task_info', return_value=self.task()) as info:
            worker = self.agent._batch_worker('batch')
        self.assertEqual((worker['alive'], worker['launch_never_started']), (False, True))
        self.assertEqual(info.call_args.kwargs['budget'], 25)                     # a status read: bounded WMI retry

    def test_an_unreadable_task_state_still_refuses(self):
        record = self.envelope()
        with patch('studio_durable_driver.task_info', side_effect=subprocess.TimeoutExpired('powershell', 20)):
            with self.assertRaisesRegex(ValueError, 'its task cannot be read'):
                self.agent._worker_alive(record)
        with patch('studio_durable_driver.task_info', side_effect=AssertionError('never asked')):
            self.assertFalse(self.agent._worker_alive(self.envelope(finished=True)))   # a finished task is simply done

    def test_task_queries_accept_only_a_goat_task_name(self):
        import studio_durable_driver
        for call in (studio_durable_driver.task_info, studio_durable_driver.unregister_task):
            with self.assertRaisesRegex(ValueError, 'Not a GOAT demand task name'):
                call("x'; Stop-Service Schedule; '")
        name = 'GOAT-Demo-' + 'b' * 16 + '-' + 'a' * 32
        reply = '{"exists":true,"state":"Ready","last_run_utc":null,"last_result":267011}'
        with patch('studio_process_query.powershell_text', return_value=reply) as call:
            self.assertEqual(studio_durable_driver.task_info(name)['last_result'], 267011)
        self.assertIn("Get-ScheduledTask -TaskName '" + name + "'", call.call_args.args[0])
        with patch('studio_process_query.powershell_text', return_value='present') as call:
            with self.assertRaisesRegex(ValueError, 'could not be removed'):
                studio_durable_driver.unregister_task(name)
        self.assertEqual(call.call_args.kwargs['attempts'], 1)                    # an effect is never retried

    def test_an_unconfirmed_launch_is_retried_only_after_its_task_is_removed(self):
        controller = types.SimpleNamespace(job=lambda batch_id: dict(status='pending'))

        @contextmanager
        def studio(*args, **kwargs):
            yield controller, dict(login='3000082754')

        launched = []

        def unconfirmed(argv, *, log_path, worker_path):
            launched.append(dict(argv=list(argv), log_path=log_path))
            envelope = Path(str(log_path)[:-4] + '.launch.json')
            write_json(envelope, dict(started=str(envelope)[:-12] + '.started.json', finished=str(envelope)[:-12] + '.finished.json',
                                      task_name='GOAT-Demo-' + 'c' * 16 + '-' + argv[argv.index('--nonce') + 1]))
            write_json(worker_path, dict(read_json(worker_path), launch_envelope=str(envelope)))
            raise ValueError('Persistent bootstrap unconfirmed; inspect the same launch/task, never issue another')
        with patch.object(self.agent, '_studio', side_effect=studio), patch('studio_durable_driver.launch', side_effect=unconfirmed):
            with self.assertRaisesRegex(ValueError, 'launch unconfirmed .*Run batch-driver-status'):
                self.agent.run_batch('batch', 600)
        worker_path = self.agent.state_root / 'workers/batch.json'
        worker = read_json(worker_path)
        self.assertEqual(worker['status'], 'launch_unconfirmed'); self.assertTrue(worker['launch_envelope'])
        old_nonce = worker['nonce']
        # Still running: the same run-batch refuses.
        with patch.object(self.agent, '_studio', side_effect=studio), \
                patch('studio_durable_driver.task_info', return_value=self.task(state='Running')):
            with self.assertRaisesRegex(ValueError, 'never duplicate'):
                self.agent.run_batch('batch', 600)
        # Never ran, but its removal can't be confirmed: refuse, nothing is launched or replaced.
        with patch.object(self.agent, '_studio', side_effect=studio), patch('studio_durable_driver.task_info', return_value=self.task()), \
                patch('studio_durable_driver.unregister_task', side_effect=ValueError('could not be removed; inspect it, never duplicate')):
            with self.assertRaisesRegex(ValueError, 'could not be removed'):
                self.agent.run_batch('batch', 600)
        self.assertEqual(read_json(worker_path)['nonce'], old_nonce)

        def started(argv, *, log_path, worker_path):
            journal = self.root / 'batch-drivers/batch.json'; journal.parent.mkdir(exist_ok=True)
            journal.write_text(json.dumps(dict(status='observing', attempt_id=None)))
            return types.SimpleNamespace(pid=321, poll=lambda: None)
        with patch.object(self.agent, '_studio', side_effect=studio), patch('studio_durable_driver.task_info', return_value=self.task()), \
                patch('studio_durable_driver.unregister_task') as removed, patch('studio_durable_driver.launch', side_effect=started):
            result = self.agent.run_batch('batch', 600)
        self.assertEqual(removed.call_args.args[0], 'GOAT-Demo-' + 'c' * 16 + '-' + old_nonce)
        self.assertEqual(result['status'], 'driver_journal_recorded')
        fresh = read_json(worker_path)
        self.assertEqual(fresh['status'], 'spawned'); self.assertNotEqual(fresh['nonce'], old_nonce)
        actions = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        logged = [a for a in actions if (a['operation'], a['phase']) == ('detached_driver', 'launch_never_started')]
        self.assertEqual((len(logged), logged[0]['nonce'], logged[0]['task']['last_result']), (1, old_nonce, 267011))
        # A late bootstrap of the old envelope is refused: its nonce no longer matches the reservation.
        import studio_durable_driver
        old = launched[0]
        argv = [old['argv'][0], str(Path(demo_agent.__file__).resolve())] + old['argv'][2:]
        with self.assertRaisesRegex(ValueError, 'Current reserved supervisor identity required'):
            studio_durable_driver.validate(argv, old['log_path'], worker_path)

    def test_a_worker_takes_the_lock_before_its_reservation_and_records_a_lock_timeout(self):
        worker_path = self.agent.state_root / 'workers/batch.json'; worker_path.parent.mkdir(parents=True)
        write_json(worker_path, dict(schema_version=1, batch_id='batch', nonce='n' * 32, status='spawned', resume=False, max_seconds=600))

        @contextmanager
        def busy(*args, **kwargs):
            raise ValueError('Another demo agent operation owns this terminal')
            yield
        with patch.object(self.agent, '_exclusive', side_effect=busy):
            with self.assertRaisesRegex(ValueError, 'owns this terminal'):
                self.agent._drive_batch('batch', 'n' * 32, 600)
        self.assertEqual(read_json(worker_path)['status'], 'failed')
        self.assertIn('stayed busy for 120 s', read_json(worker_path)['error'])
        # A late older task whose reservation was replaced while it waited never drives.
        write_json(worker_path, dict(schema_version=1, batch_id='batch', nonce='m' * 32, status='reserved', resume=False, max_seconds=600))
        with patch.object(self.agent, '_studio', side_effect=AssertionError('never reaches the drive')):
            with self.assertRaisesRegex(ValueError, 'Detached worker identity changed'):
                self.agent._drive_batch('batch', 'n' * 32, 600)
        self.assertEqual(read_json(worker_path)['status'], 'reserved')


if __name__ == '__main__':
    unittest.main()
