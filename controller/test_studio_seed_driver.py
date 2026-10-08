"""seed-status says whether a driver is running, and the exact next step (support 64f1c5ae).

The seed lane has no background driver: each seed-start/seed-resume call drives for at most --max-seconds.
A tester's run read "active, N pending, none running" after the caller's loop had ended on a transient
error, and nothing said to resume. Each call now records itself; a status read proves liveness from that
call's own process (PID and creation time) and never guesses: unknown is said as unknown.

Also here (Claude-Mac #2350): the WMI inventory falls back to a native Windows read once every CIM
attempt has failed, and a member launch is never left reconcile_required by a transient inventory stall.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import studio_process_query as query
import studio_seed_driver
import test_studio_seed as seed_fixture
from studio_installation import read_json

LIVE = '2026-10-08T07:00:00.1234560Z'
ALIVE_PID = 4242


class _Fixture:
    setUp = seed_fixture.SeedTests.setUp
    tearDown = seed_fixture.SeedTests.tearDown
    close, start, sleep, prepare, member, output = (
        seed_fixture.SeedTests.close, seed_fixture.SeedTests.start, seed_fixture.SeedTests.sleep,
        seed_fixture.SeedTests.prepare, seed_fixture.SeedTests.member, seed_fixture.SeedTests.output)

    def record_open_call(self, pid, created=LIVE):
        """A call that recorded its start and never its return (killed, or still running elsewhere)."""
        studio_seed_driver.begin(self.runner.path('batch'), command='seed-resume', max_seconds=60, now=self.now,
                                 identity=dict(pid=pid, created_utc=created))


class SeedStatusDriverTests(_Fixture, unittest.TestCase):

    def test_a_live_call_reads_running_and_says_not_to_start_a_second_one(self):
        self.prepare()
        self.runner.identity = lambda: dict(pid=ALIVE_PID, created_utc=LIVE)
        driving = [True]
        checked = []

        def alive(identity, budget):
            checked.append((identity, budget))
            return identity == dict(pid=ALIVE_PID, created_utc=LIVE) and driving[0]
        self.process.process_alive = alive
        seen = []
        real = self.runner.sleep

        def sleep(seconds):
            if not seen:
                seen.append(self.runner.status('batch'))          # read while the call is between passes
            real(seconds)
        self.runner.sleep = sleep
        self.runner.start('batch', 3)
        during = seen[0]
        self.assertEqual((during['status'], during['driver']), ('active', 'running'))
        self.assertEqual((during['driver_detail']['call']['pid'], during['driver_detail']['call']['command']), (ALIVE_PID, 'seed-start'))
        self.assertIn('is driving this run now; do not start a second one', during['next_step'])
        self.assertTrue(0 < checked[0][1] <= studio_seed_driver.CHECK_SECONDS)   # one short shared deadline
        driving[0] = False                                                    # the call returned
        after = self.runner.status('batch')
        self.assertEqual(after['driver'], 'none')
        self.assertEqual(after['driver_detail']['last_call']['status'], 'returned')
        self.assertTrue(after['next_step'].startswith('Not advancing: 0 members pending and no driver running'))
        self.assertIn(self.member()['alias'] + ' is still running in MT5', after['next_step'])
        self.assertIn('Resume with: goat.exe studio --installation <installation receipt> seed-resume --batch-id batch --max-seconds 60',
                      after['next_step'])

    def test_no_driver_with_pending_members_names_the_exact_resume_and_the_loop(self):
        # The tester's case: the call ended on a transient error; nothing ran, the member is pending.
        from studio_research_launch import ResearchLaunchRefused
        self.prepare()
        self.controller.receipt = Path('C:/Users/You/GOAT Suite/installation.json')
        self.process.start = lambda config: (_ for _ in ()).throw(ResearchLaunchRefused('MT5 was not started: test. Nothing ran.'))
        with self.assertRaises(ResearchLaunchRefused):
            self.runner.start('batch', 5)
        self.process.process_alive = lambda identity, budget: self.fail('a returned call needs no process check')
        status = self.runner.status('batch')
        self.assertEqual((status['status'], status['members'][0]['status'], status['driver']), ('active', 'pending', 'none'))
        last = status['driver_detail']['last_call']
        self.assertEqual((last['status'], last['command']), ('failed', 'seed-start'))
        self.assertIn('Nothing ran', last['error'])
        self.assertEqual(status['next_step'],
                         'Not advancing: 1 member pending and no driver running (no seed-start or seed-resume call is in progress). '
                         'Resume with: goat.exe studio --installation "' + str(self.controller.receipt) + '" seed-resume --batch-id batch '
                         '--max-seconds 60. Call it again and again until the status is completed or stopped, and call it again after '
                         'any non-zero exit: each call drives for at most --max-seconds and nothing advances between calls.')

    def test_a_call_killed_before_it_recorded_its_return_reads_none_from_its_gone_process(self):
        self.prepare(); self.runner.start('batch', 1)
        self.record_open_call(4243)
        self.process.process_alive = lambda identity, budget: False         # PID gone (or reused: other creation time)
        status = self.runner.status('batch')
        self.assertEqual(status['driver'], 'none')
        self.assertIn('ended without recording its return; its process is gone', status['driver_detail']['basis'])
        self.assertIn('seed-resume --batch-id batch --max-seconds 60', status['next_step'])

    def test_reconcile_required_points_to_seed_reconcile(self):
        self.prepare()
        self.process.start = lambda config: (_ for _ in ()).throw(ValueError('Terminal startup identity not observed in 90 s'))
        with self.assertRaises(ValueError):
            self.runner.start('batch', 5)
        status = self.runner.status('batch')
        self.assertEqual((status['status'], status['driver']), ('reconcile_required', 'none'))
        self.assertIn('Settle it with: goat.exe studio --installation <installation receipt> seed-reconcile --batch-id batch.',
                      status['next_step'])
        self.assertNotIn('seed-resume', status['next_step'])

    def test_completed_needs_no_driver_and_points_to_the_report(self):
        self.prepare(); self.auto = True
        self.assertEqual(self.runner.start('batch', 10)['status'], 'completed')
        status = self.runner.status('batch')
        self.assertEqual(status['driver'], 'none')
        self.assertEqual(status['next_step'], 'Completed; nothing is pending and no driver is needed. Read the results with: '
                                              'goat.exe studio --installation <installation receipt> seed-report --batch-id batch.')

    def test_an_unavailable_process_query_reads_unknown_never_running_or_stopped(self):
        self.prepare(); self.runner.start('batch', 1)
        self.record_open_call(4244)
        for label, alive in (('no process check in this tool', None),
                             ('the query stalled', subprocess.TimeoutExpired('powershell', 20)),
                             ('the creation time cannot be read', ValueError('creation time cannot be read'))):
            with self.subTest(label):
                if alive is None:
                    self.process.__dict__.pop('process_alive', None)
                else:
                    self.process.process_alive = lambda identity, budget, error=alive: (_ for _ in ()).throw(error)
                status = self.runner.status('batch')
                self.assertEqual(status['driver'], 'unknown')
                self.assertIn('Nothing is inferred', status['driver_detail']['basis'])
                self.assertTrue(status['next_step'].startswith('Driver unknown: '))
                self.assertNotIn('no driver running', status['next_step'])
                self.assertNotIn('is driving this run now', status['next_step'])

    def test_an_unreadable_driver_record_reads_unknown(self):
        self.prepare()
        (self.runner.path('batch') / studio_seed_driver.RECORD).write_text('{not json', encoding='utf-8')
        self.assertEqual(self.runner.status('batch')['driver'], 'unknown')

    def test_prepared_and_a_stopped_resumable_run_name_their_commands(self):
        self.prepare()
        status = self.runner.status('batch')
        self.assertEqual(status['driver'], 'none')
        self.assertTrue(status['next_step'].startswith('Not started yet. Start with: goat.exe studio --installation <installation receipt> '
                                                       'seed-start --batch-id batch --max-seconds 60.'))
        state = dict(status='stopped', generation=1, error=None, members=[dict(status='failed', attempts=1), dict(status='pending', attempts=0)])
        step = self.runner._next_step('batch', state, dict(state='none'))
        self.assertTrue(step.startswith('Stopped with 1 member pending and no driver running. Resume with: goat.exe studio'))

    def test_the_closing_reply_of_a_call_never_reads_itself_as_a_driver(self):
        self.prepare()
        result = self.runner.start('batch', 1)               # this process's own call: returning, not driving
        self.assertTrue(result['driver_budget_exhausted'])
        self.assertEqual(result['driver'], 'none')
        record = read_json(self.runner.path('batch') / studio_seed_driver.RECORD)
        self.assertEqual([(c['command'], c['status'], c['pid']) for c in record['calls']], [('seed-start', 'returned', os.getpid())])

    def test_the_driver_record_keeps_only_the_last_calls(self):
        self.prepare(); self.runner.start('batch', 1)
        for _ in range(studio_seed_driver.MAX_CALLS + 5):
            self.runner.resume('batch', 1)
        self.assertEqual(len(read_json(self.runner.path('batch') / studio_seed_driver.RECORD)['calls']), studio_seed_driver.MAX_CALLS)

    def test_catchup_and_demo_lanes_spell_their_own_commands(self):
        from studio_catchup import CatchupRunner
        catchup = CatchupRunner(self.controller, process=self.process)
        self.assertEqual(catchup._command('resume', 'c1', budget=True),
                         'goat.exe studio --installation <installation receipt> catchup-resume --catchup-id c1 --max-seconds 60')
        self.runner.cli_lane, self.runner.receipt, self.runner.next_step_budget = 'demo', 'C:/r.json', 3600
        self.assertEqual(self.runner._command('resume', 'batch', budget=True),
                         'goat.exe demo --installation "C:/r.json" seed-resume --batch-id batch --max-seconds 3600')

    def test_a_demo_lane_run_seen_from_the_studio_lane_is_unknown_and_points_to_demo(self):
        self.prepare()
        start = self.controller.root / 'demo-agent/seed-starts/batch.json'; start.parent.mkdir(parents=True); start.write_text('{}')
        status = self.runner.status('batch')
        self.assertEqual(status['driver'], 'unknown')
        self.assertIn('owner demo lane', status['driver_detail']['basis'])
        self.assertIn('goat.exe demo --installation <installation receipt> seed-start --batch-id batch --max-seconds 3600', status['next_step'])

    def test_research_status_and_queue_show_the_same_driver_block(self):
        from studio_research_queue import runner_row
        from studio_research_status import lane_driver_block
        self.prepare(); self.runner.start('batch', 1)
        self.record_open_call(4245)
        self.process.process_alive = lambda identity, budget: False
        probe = lambda kind, batch_id: self.runner.driver_summary(batch_id)
        block = lane_driver_block(probe, 'seed', 'batch', 'active')
        self.assertEqual((block['state'], block['alive'], block['health']), ('none', False, 'unsupervised'))
        self.assertIn('seed-resume --batch-id batch --max-seconds 60', block['fix'])
        row, _ = runner_row(self.controller.root, 'seed', 'batch', now=self.now, lane_driver=probe)
        self.assertEqual((row['state'], row['driver']['state'], row['driver']['next_step']), ('running', 'none', block['next_step']))
        plain, _ = runner_row(self.controller.root, 'seed', 'batch', now=self.now)
        self.assertNotIn('driver', plain)                                    # without a probe: unchanged
        failing = lane_driver_block(lambda kind, batch_id: 1 / 0, 'seed', 'batch', 'active')
        self.assertEqual((failing['state'], failing['alive'], failing['health']), ('unknown', None, 'unknown'))


class DemoLaneLivenessTests(unittest.TestCase):
    """The owner demo lane's driver is its detached lane worker; its record maps to the same three states."""

    def test_the_lane_worker_record_maps_to_running_none_or_unknown(self):
        from demo_agent import DemoAgent
        live = DemoAgent._lane_liveness
        record = dict(kind='seed', batch_id='b', nonce='n' * 32, pid=77, initial=False, status='supervising', created_at='2026-10-08T07:00:00+00:00')
        self.assertEqual(live(None)['state'], 'none')
        self.assertEqual(live(dict(record, alive=True))['state'], 'running')
        self.assertEqual(live(dict(record, alive=True))['call']['command'], 'seed-resume')
        failed = live(dict(record, alive=False, status='failed', error='Windows process inventory did not answer'))
        self.assertEqual((failed['state'], failed['last_call']['status']), ('none', 'failed'))
        self.assertIn('failed: Windows process inventory did not answer', failed['basis'])
        unknown = live(dict(record, alive='unknown: Cannot verify detached driver process; no duplicate launch'))
        self.assertEqual(unknown['state'], 'unknown')
        self.assertIn('Nothing is inferred', unknown['basis'])


class NativeFallbackTests(unittest.TestCase):
    """After every CIM attempt fails, native Windows answers the fields it can; everything else stays fail-closed."""
    FIELDS = ('ProcessId', 'ExecutablePath', 'CreatedUtc')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'process-query.jsonl'
        query.configure(self.log); self.addCleanup(query.configure, None)
        for name, value in (('sleep', lambda seconds: None), ('uniform', lambda a, b: 1.0)):
            patcher = patch.object(query, name, side_effect=value); patcher.start(); self.addCleanup(patcher.stop)

    def lines(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_the_native_rows_answer_and_the_fallback_is_logged(self):
        row = dict(ProcessId=7, ParentProcessId=1, Name='terminal64.exe', ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc=LIVE)
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)) as cim, \
                patch.object(query, 'native_rows', return_value=[row]) as native:
            rows = query.process_rows('Get-CimInstance Win32_Process', purpose='p', fields=self.FIELDS, names=('terminal64.exe',))
        self.assertEqual(cim.call_count, 4)                                   # the existing retries first
        self.assertEqual(rows, [dict(ProcessId=7, ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc=LIVE)])
        self.assertEqual(native.call_args.kwargs, dict(names=('terminal64.exe',), pid=None))
        self.assertEqual([l.get('outcome') for l in self.lines()][-2:], ['gave_up', 'native_fallback'])

    def test_a_query_that_needs_the_command_line_never_falls_back(self):
        # The native read would answer (with no command line), yet it is never used: the CIM error is raised.
        rows = [dict(ProcessId=7, ParentProcessId=1, Name='terminal64.exe', ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc=LIVE)]
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)), \
                patch.object(query, 'native_rows', return_value=rows) as native:
            with self.assertRaises(subprocess.TimeoutExpired):
                query.process_rows('x', purpose='p', fields=('ProcessId', 'CommandLine'))
        native.assert_not_called()

    def test_a_failed_native_read_raises_the_original_cim_error_never_an_empty_list(self):
        with patch('subprocess.check_output', side_effect=subprocess.CalledProcessError(1, 'powershell')), \
                patch.object(query, 'native_rows', side_effect=OSError('snapshot failed')):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                query.process_rows('x', purpose='p', fields=self.FIELDS)
        self.assertIn('did not answer in 4 attempts', ' '.join(getattr(raised.exception, '__notes__', [])))
        self.assertEqual(self.lines()[-1]['outcome'], 'native_fallback_failed')

    def test_a_cim_answer_is_used_as_is(self):
        with patch('subprocess.check_output', return_value='[{"ProcessId": 3}]'), \
                patch.object(query, 'native_rows', side_effect=AssertionError('not needed')):
            self.assertEqual(query.process_rows('x', purpose='p', fields=self.FIELDS), [{'ProcessId': 3}])

    def test_native_creation_times_print_exactly_like_wmi(self):
        # WMI keeps microseconds: PowerShell printed ...37.2087830Z for a process Windows created at ...37.2087834.
        base = datetime(2026, 10, 8, 7, 4, 37, 208783, tzinfo=timezone.utc) - datetime(1601, 1, 1, tzinfo=timezone.utc)
        ticks = (base // timedelta(microseconds=1)) * 10 + 4
        self.assertEqual(query.filetime_utc(ticks), '2026-10-08T07:04:37.2087830Z')

    def test_the_seed_inventory_and_driver_liveness_use_the_fallback(self):
        from studio_seed_process import WindowsSeedProcess
        controller = types.SimpleNamespace(install=dict(terminal_executable='C:\\MT5\\terminal64.exe'))
        process = WindowsSeedProcess(controller)
        native = [dict(ProcessId=7, ParentProcessId=1, Name='terminal64.exe', ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc=LIVE)]
        unproven = patch.object(query, 'native_alive', return_value=None)       # e.g. access denied: CIM decides
        unproven.start(); self.addCleanup(unproven.stop)
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)), \
                patch.object(query, 'native_rows', return_value=native):
            self.assertEqual(process.inspect(), dict(pid=7, executable='C:\\MT5\\terminal64.exe', created_utc=LIVE))
            self.assertTrue(process.process_alive(dict(pid=7, created_utc=LIVE)))
            self.assertFalse(process.process_alive(dict(pid=7, created_utc='2026-10-08T06:00:00.0000000Z')))   # reused PID
        denied = [dict(native[0], ExecutablePath=None, CreatedUtc=None)]
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)), \
                patch.object(query, 'native_rows', return_value=denied), patch.object(process, 'image_path', return_value=None), \
                patch('studio_seed_process.UNKNOWN_SETTLE_SECONDS', 0):
            with self.assertRaisesRegex(ValueError, 'Unknown terminal executable'):
                process.inspect()                                              # a null path is unknown, never absent
            with self.assertRaisesRegex(ValueError, 'creation time cannot be read'):
                process.process_alive(dict(pid=7, created_utc=LIVE))
        with patch('subprocess.check_output', return_value='[]'):
            self.assertFalse(process.process_alive(dict(pid=7, created_utc=LIVE)))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process API')
    def test_the_native_read_of_this_process_matches_its_own_identity(self):
        rows = query.native_rows(pid=os.getpid())
        own = query.own_identity()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['ProcessId'], rows[0]['CreatedUtc']), (own['pid'], own['created_utc']))
        self.assertEqual(os.path.normcase(rows[0]['ExecutablePath']), os.path.normcase(sys.executable))
        self.assertTrue(own['created_utc'].endswith('0Z'))
        self.assertEqual(query.native_rows(names=('no-such-process-goat.exe',)), [])


class StartupStallEndToEndTests(_Fixture, unittest.TestCase):
    """Every CIM attempt stalls while a member starts: the batch must never end reconcile_required for it."""

    def setUp(self):
        _Fixture.setUp(self)
        from studio_seed import SeedRunner
        from studio_seed_process import WindowsSeedProcess
        self.exe = self.controller.install['terminal_executable']
        self.mt5 = dict(ProcessId=10, ParentProcessId=1, Name='terminal64.exe', ExecutablePath=self.exe, CreatedUtc=LIVE)
        self.cim_calls, self.stall_from, self.native_fails, self.launches = 0, None, False, []
        self.log = self.root / 'process-query.jsonl'
        query.configure(self.log); self.addCleanup(query.configure, None)
        for target, value in (('studio_process_query.sleep', lambda seconds: None), ('studio_process_query.uniform', lambda a, b: 1.0),
                              ('subprocess.check_output', self.cim), ('studio_process_query.native_rows', self.native),
                              ('studio_research_launch.launch', self.launch), ('studio_research_launch.pause_wanted', lambda c: False)):
            patcher = patch(target, side_effect=value); patcher.start(); self.addCleanup(patcher.stop)
        closer = patch.object(WindowsSeedProcess, 'close', side_effect=self.close_mt5); closer.start(); self.addCleanup(closer.stop)
        self.windows = WindowsSeedProcess(self.controller, sleep=lambda seconds: None)
        self.runner = SeedRunner(self.controller, process=self.windows, clock=lambda: self.now, sleep=self.finish)

    def cim(self, argv, **kwargs):
        self.cim_calls += 1
        if self.stall_from is not None and self.cim_calls >= self.stall_from:
            raise subprocess.TimeoutExpired('powershell', kwargs.get('timeout', 20))
        return json.dumps([{k: self.mt5[k] for k in ('ProcessId', 'ExecutablePath', 'CreatedUtc')}] if self.mt5 else [])

    def native(self, names=None, pid=None):
        if self.native_fails:
            raise OSError('snapshot failed')
        return [dict(self.mt5)] if self.mt5 else []

    def close_mt5(self, identity):
        self.mt5 = None

    def launch(self, controller, args, *, cwd, config=None):
        self.launches.append(config)
        pid = 20 + len(self.launches)
        self.mt5 = dict(ProcessId=pid, ParentProcessId=1, Name='terminal64.exe', ExecutablePath=self.exe,
                        CreatedUtc='2026-10-08T07:00:%02d.0000000Z' % len(self.launches))
        return types.SimpleNamespace(pid=pid, poll=lambda: None)

    def finish(self, seconds):
        self.now += seconds
        if self.mt5 and self.mt5['ProcessId'] > 20:                          # the member's MT5 writes and exits
            self.output(self.member(len(self.launches) - 1)); self.mt5 = None

    def outcomes(self):
        return [json.loads(line).get('outcome') for line in self.log.read_text(encoding='utf-8').splitlines()] if self.log.exists() else []

    def test_the_native_fallback_answers_and_the_member_completes(self):
        self.prepare()
        self.stall_from = 1                                                   # WMI never answers during the whole run
        result = self.runner.start('batch', 30)
        self.assertEqual((result['status'], [m['status'] for m in result['members']]), ('completed', ['completed']))
        self.assertEqual(len(self.launches), 1)
        self.assertIn('native_fallback', self.outcomes())
        self.assertNotIn('reconcile_required', json.dumps(read_json(self.runner.path('batch') / 'state.json')))

    def test_when_the_fallback_also_fails_before_the_launch_the_member_stays_pending_and_resumable(self):
        from studio_research_launch import ResearchLaunchRefused
        self.prepare()
        # CIM answers the activation (monitor inspect) and the first observe, then stalls from the member's
        # pre-launch inventory on (the third inventory of the start); the native read fails too.
        self.cim_calls, self.stall_from, self.native_fails = 0, 3, True
        with self.assertRaisesRegex(ResearchLaunchRefused, 'could not list the running MT5 processes before the launch'):
            self.runner.start('batch', 30)
        self.assertEqual(self.launches, [])                                   # nothing was started
        state = read_json(self.runner.path('batch') / 'state.json')
        self.assertEqual((state['status'], state['members'][0]['status'], state['members'][0]['attempts']), ('active', 'pending', 0))
        self.assertIn('native_fallback_failed', self.outcomes())
        self.stall_from, self.native_fails = None, False                      # Windows answers again
        status = self.runner.status('batch')
        self.assertEqual((status['status'], status['driver']), ('active', 'none'))
        self.assertTrue(status['next_step'].startswith('Not advancing: 1 member pending and no driver running'))
        self.assertIn('seed-resume --batch-id batch --max-seconds 60', status['next_step'])
        self.assertEqual(self.runner.resume('batch', 30)['status'], 'completed')
        self.assertEqual(len(self.launches), 1)


class BoundedStatusTests(_Fixture, unittest.TestCase):
    """Claude-Mac on GOAT-EA#197: 19 stale entries x 25 s of CIM each outlasted the agent's tool timeout."""

    def open_calls(self, folder, pids, created=LIVE):
        for pid in pids:
            studio_seed_driver.begin(folder, command='seed-resume', max_seconds=60, now=0, identity=dict(pid=pid, created_utc=created))

    def test_every_entry_shares_one_deadline_and_late_entries_read_unknown(self):
        folder = self.root / 'run'; folder.mkdir()
        self.open_calls(folder, range(101, 120))                              # 19 entries, the reproduced worst case
        clock, budgets = [100.0], []

        def stalled(identity, budget):                                       # every check uses up its whole budget
            budgets.append(budget); clock[0] += budget
            raise subprocess.TimeoutExpired('powershell', budget)
        result = studio_seed_driver.liveness(folder, alive=stalled, own_pid=-1, monotonic=lambda: clock[0])
        self.assertEqual(result['state'], 'unknown')
        self.assertLessEqual(clock[0] - 100.0, studio_seed_driver.CHECK_SECONDS)   # the whole check, not per entry
        self.assertEqual(budgets, [studio_seed_driver.CHECK_SECONDS])

        clock[0], budgets[:] = 100.0, []

        def slow_gone(identity, budget):
            budgets.append(budget); clock[0] += 6
            return False
        result = studio_seed_driver.liveness(folder, alive=slow_gone, own_pid=-1, monotonic=lambda: clock[0])
        self.assertEqual((result['state'], budgets), ('unknown', [8, 2]))     # never "none" for an unchecked entry
        self.assertIn('ran out of its time', result['basis'])

    def test_a_new_call_closes_entries_whose_process_is_provably_gone(self):
        self.prepare(); self.runner.start('batch', 1)
        folder = self.runner.path('batch')
        self.open_calls(folder, (5001, 5002))
        self.open_calls(folder, (5003,), created=None)                        # no creation time, PID gone: still provable
        self.process.process_gone = lambda identity: identity['pid'] in (5001, 5003)
        self.runner.resume('batch', 1)
        calls = {c['pid']: c for c in read_json(folder / studio_seed_driver.RECORD)['calls'] if c['pid'] in (5001, 5002, 5003)}
        self.assertEqual({pid: c['status'] for pid, c in calls.items()}, {5001: 'gone', 5002: 'driving', 5003: 'gone'})
        self.assertIn('ended without recording its return', calls[5001]['error'])
        self.process.process_gone = lambda identity: (_ for _ in ()).throw(OSError('no answer'))
        self.runner.resume('batch', 1)                                        # an unanswered check closes nothing
        self.assertEqual([c['status'] for c in read_json(folder / studio_seed_driver.RECORD)['calls'] if c['pid'] == 5002], ['driving'])

    def test_seed_status_is_bounded_with_a_stalled_process_check(self):
        self.prepare(); self.runner.start('batch', 1)
        self.open_calls(self.runner.path('batch'), range(201, 220))
        budgets = []
        self.process.process_alive = lambda identity, budget: budgets.append(budget) or (_ for _ in ()).throw(
            subprocess.TimeoutExpired('powershell', budget))
        with patch.object(studio_seed_driver, 'time', types.SimpleNamespace(monotonic=self.ticking())):
            self.assertEqual(self.runner.status('batch')['driver'], 'unknown')
        self.assertLessEqual(sum(budgets), studio_seed_driver.CHECK_SECONDS)

    @staticmethod
    def ticking():
        clock = [0.0]

        def now():
            clock[0] += 3                                                     # each check costs 3 s of the shared time
            return clock[0]
        return now

    def test_research_queue_runs_share_one_deadline(self):
        import time
        import goat_studio
        import studio_seed
        seen = []
        with patch.object(studio_seed.SeedRunner, 'driver_summary', autospec=True,
                          side_effect=lambda runner, batch_id, **kw: seen.append(kw.get('deadline')) or dict(state='none')):
            probe = goat_studio._lane_driver(self.controller)
            probe('seed', 'a'); probe('seed', 'b')
        self.assertEqual(len(set(seen)), 1)
        self.assertLessEqual(seen[0] - time.monotonic(), studio_seed_driver.CHECK_SECONDS)

    def test_the_demo_lane_probe_bounds_its_worker_check(self):
        from demo_agent import DemoAgent
        path = self.root / 'seed-b.json'; path.write_text(json.dumps(dict(kind='seed', batch_id='b', nonce='n' * 32, pid=9)), encoding='utf-8')
        checks = []
        agent = types.SimpleNamespace(_lane_worker_path=lambda kind, batch_id: path, _launch_never_started=DemoAgent._launch_never_started,
                                      _worker_alive=lambda record, **kw: checks.append(kw) or True)
        late = DemoAgent._lane_driver_bounded(agent, 'seed', 'b', 0)
        self.assertTrue(str(late['alive']).startswith('unknown: the status check ran out of its time'))
        self.assertEqual((checks, DemoAgent._lane_liveness(late)['state']), ([], 'unknown'))
        self.assertIs(DemoAgent._lane_driver_bounded(agent, 'seed', 'b', 3.5)['alive'], True)
        self.assertEqual(checks, [dict(quick=True, budget=3.5)])


class NativeFirstTests(unittest.TestCase):
    """The recorded driver is checked natively first (exact, instant, no WMI); CIM only when Windows will not say."""

    def process(self):
        from studio_seed_process import WindowsSeedProcess
        return WindowsSeedProcess(types.SimpleNamespace(install=dict(terminal_executable='C:\\MT5\\terminal64.exe')))

    def test_a_native_answer_never_asks_cim(self):
        for answer in (True, False):
            with self.subTest(answer), patch.object(query, 'native_alive', return_value=answer) as native, \
                    patch('subprocess.check_output', side_effect=AssertionError('no CIM when Windows answered natively')):
                self.assertIs(self.process().process_alive(dict(pid=7, created_utc=LIVE), 2), answer)
            self.assertEqual(native.call_args.args, (7, LIVE))

    def test_an_entry_without_a_creation_time_is_gone_when_its_pid_is(self):
        with patch.object(query, 'native_alive', return_value=None), patch('subprocess.check_output', return_value='[]'):
            self.assertFalse(self.process().process_alive(dict(pid=7, created_utc=None), 2))
        with patch.object(query, 'native_alive', return_value=None), \
                patch('subprocess.check_output', return_value=json.dumps([dict(ProcessId=7, CreatedUtc=LIVE)])):
            with self.assertRaisesRegex(ValueError, 'no creation time to prove'):
                self.process().process_alive(dict(pid=7, created_utc=None), 2)

    def test_process_gone_is_native_proof_only(self):
        for answer, gone in ((False, True), (True, False), (None, False)):
            with self.subTest(answer), patch.object(query, 'native_alive', return_value=answer):
                self.assertIs(self.process().process_gone(dict(pid=7, created_utc=LIVE)), gone)


class FakeKernel:
    """kernel32 for native_rows/native_alive: a process table, no Windows needed. Each entry is
    (pid, parent, name, mode, created_ticks, exited_ticks, path); mode is ok, denied or gone."""

    def __init__(self, table, *, snapshot=True, walk_error=18):
        import ctypes
        self.table, self.error, self.closed, self.index = {row[0]: row for row in table}, 0, [], 0
        order = list(table)
        fake = self

        def fill(ref):
            if fake.index >= len(order):
                fake.error = walk_error
                return False
            pid, parent, name = order[fake.index][:3]
            ref._obj.th32ProcessID, ref._obj.th32ParentProcessID, ref._obj.szExeFile = pid, parent, name
            return True

        def first(handle, ref):
            fake.index = 0
            return fill(ref)

        def following(handle, ref):
            fake.index += 1
            return fill(ref)

        def snap(flags, pid):
            if snapshot:
                return 77
            fake.error = 5
            return ctypes.c_void_p(-1).value

        def open_process(access, inherit, pid):
            row = fake.table.get(pid)
            if row is None or row[3] == 'gone':
                fake.error = 87
                return None
            if row[3] == 'denied':
                fake.error = 5
                return None
            return 1000 + pid

        def times(handle, created, exited, kernel_time, user_time):
            row = fake.table[handle - 1000]
            for ref, ticks in ((created, row[4]), (exited, row[5])):
                ref._obj.dwLowDateTime, ref._obj.dwHighDateTime = ticks & 0xFFFFFFFF, ticks >> 32
            return True

        def image(handle, flags, buffer, size):
            buffer.value = fake.table[handle - 1000][6]
            return True

        self.CreateToolhelp32Snapshot, self.Process32FirstW, self.Process32NextW = snap, first, following
        self.OpenProcess, self.GetProcessTimes, self.QueryFullProcessImageNameW = open_process, times, image
        self.CloseHandle = lambda handle: fake.closed.append(handle) or True

    def patch(self):
        import ctypes
        from ctypes import wintypes
        return patch.object(query, '_kernel', return_value=(ctypes, wintypes, self, lambda: self.error,
                                                            lambda code: OSError(code, 'Windows error %d' % code)))


class FakeKernelTests(unittest.TestCase):
    """Claude-Mac on GOAT-EA#197: the native_rows branches (denied row kept, gone and exited left out) under test."""
    US = query._microseconds(LIVE)
    TICKS = US * 10 + 4                                                       # Windows keeps 100 ns; CIM prints microseconds

    def table(self):
        return [(10, 1, 'terminal64.exe', 'ok', self.TICKS, 0, 'C:\\MT5\\terminal64.exe'),
                (11, 1, 'terminal64.exe', 'denied', 0, 0, None),
                (12, 1, 'terminal64.exe', 'gone', 0, 0, None),
                (13, 1, 'terminal64.exe', 'ok', self.TICKS, self.TICKS + 50, 'C:\\MT5\\terminal64.exe'),
                (14, 1, 'explorer.exe', 'ok', self.TICKS, 0, 'C:\\Windows\\explorer.exe')]

    def test_native_rows_keep_a_denied_row_and_leave_out_gone_exited_and_other_names(self):
        kernel = FakeKernel(self.table())
        with kernel.patch():
            rows = query.native_rows(names=('TERMINAL64.EXE',))
        self.assertEqual(rows, [dict(ProcessId=10, ParentProcessId=1, Name='terminal64.exe', ExecutablePath='C:\\MT5\\terminal64.exe', CreatedUtc=LIVE),
                                dict(ProcessId=11, ParentProcessId=1, Name='terminal64.exe', ExecutablePath=None, CreatedUtc=None)])
        self.assertEqual(sorted(kernel.closed), [77, 1010, 1013])                    # snapshot and every opened handle
        with kernel.patch():
            self.assertEqual([r['ProcessId'] for r in query.native_rows(pid=14)], [14])

    def test_a_failed_snapshot_or_walk_raises_never_an_empty_list(self):
        with FakeKernel(self.table(), snapshot=False).patch():
            with self.assertRaises(OSError):
                query.native_rows(names=('terminal64.exe',))
        broken = FakeKernel(self.table(), walk_error=31)
        with broken.patch():
            with self.assertRaises(OSError):
                query.native_rows(names=('terminal64.exe',))
        self.assertIn(77, broken.closed)

    def test_native_alive_proves_running_and_gone_and_says_none_otherwise(self):
        with FakeKernel(self.table()).patch():
            self.assertIs(query.native_alive(10, LIVE), True)                         # same PID and microsecond
            self.assertIs(query.native_alive(10, '2026-10-08T06:00:00.0000000Z'), False)   # PID reused
            self.assertIs(query.native_alive(12, LIVE), False)                        # no such PID
            self.assertIs(query.native_alive(12, None), False)                        # gone even without a creation time
            self.assertIs(query.native_alive(13, LIVE), False)                        # exited
            self.assertIsNone(query.native_alive(11, LIVE))                           # denied: not provable natively
            self.assertIsNone(query.native_alive(10, None))                           # live PID, nothing to prove it by
        with patch.object(query, '_kernel', side_effect=OSError('not Windows')):
            self.assertIsNone(query.native_alive(10, LIVE))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows CIM and process API')
    def test_cim_and_native_print_the_same_creation_time_for_one_process(self):
        # Claude-Mac on GOAT-EA#197: a rounding or time-zone difference would make a live driver read "none".
        query.configure(None)
        command = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance '
                   'Win32_Process -Filter "ProcessId=%d" | Select-Object ProcessId,@{Name="CreatedUtc";Expression={$_.CreationDate.'
                   'ToUniversalTime().ToString("o")}})' % os.getpid())
        cim = json.loads(query.powershell_text(command, purpose='creation time parity test', budget=90))
        own = query.own_identity()['created_utc']
        self.assertEqual([row['CreatedUtc'] for row in cim], [own])
        self.assertEqual(query.native_rows(pid=os.getpid())[0]['CreatedUtc'], own)
        self.assertIs(query.native_alive(os.getpid(), cim[0]['CreatedUtc']), True)
        self.assertIs(query.native_alive(os.getpid(), '2000-01-01T00:00:00.0000000Z'), False)


if __name__ == '__main__':
    unittest.main()
