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
        self.assertEqual(checked[0][1], 25)                                   # a status read: bounded query
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
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('powershell', 20)), \
                patch.object(query, 'native_rows', side_effect=AssertionError('never for CommandLine')):
            with self.assertRaises(subprocess.TimeoutExpired):
                query.process_rows('x', purpose='p', fields=('ProcessId', 'CommandLine'))

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


if __name__ == '__main__':
    unittest.main()
