"""Fast-fail re-run, once (studio_fast_fail; goatai#2750, Claude-Mac 6884089927 option (b)). Fixture-only.

Replays the 2026-11-14 Banker loss: tier D member _00179's MT5 closed 14 s into an 1800 s budget with no export (its tester
agent hit `bind error on 127.0.0.1:3024 [10048]` while T3's agent held the port). Such a member is re-run once, after the
batch's other pending members and not before RETRY_DELAY_SECONDS; a second fast-fail is final; nothing else is re-run.
"""
from datetime import datetime
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
import unittest.mock

from studio_installation import read_json
from studio_seed import SeedRunner
import studio_fast_fail as fast_fail
import studio_tester_report as tester_report
# Fixture modules, not their TestCase classes: importing a class here would run its suite twice.
import test_studio_holdup as holdup_fixture
import test_studio_seed as seed_fixture

# B57: MT5 build 6230's own report from the 2026-11-27 hold-up probe fwr-depth-sp500 member _00010 (T3, 15 s, agent 3033 bind
# error): it names no expert and no symbol, period M0 1970.01.01, deposit 0, leverage 1:0, no deals. Gzipped, mtime 0.
EMPTY_REPORT = Path(__file__).resolve().parent / 'fixtures' / 'holdup' / 'mt5-empty-report-6230.htm.gz'
EMPTY_REPORT_SHA256 = 'd6375f984b20ee4912f6933257b0fa93011dcbc2ad279f5b8477816d0d9d3d34'


class FastFailRunnerTests(unittest.TestCase):
    def setUp(self):
        seed_fixture.SeedTests.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        self.fail_starts = set()        # 1-based start numbers whose MT5 closes early with no output
        self.fail_after = 14            # seconds: the 11-14 member closed after 14 s
        self.started_at = {}
        self.agents = Path(self.tmp.name) / 'agents'
        self.runner.agents_root = self.agents          # read by _observe through getattr(self,'agents_root',None)

    close, prepare, member, output = (seed_fixture.SeedTests.close, seed_fixture.SeedTests.prepare,
                                      seed_fixture.SeedTests.member, seed_fixture.SeedTests.output)

    def start(self, config):
        identity = seed_fixture.SeedTests.start(self, config)
        self.started_at[len(self.starts)] = self.now
        return identity

    def sleep(self, seconds):
        self.now += seconds
        if not (self.starts and self.process_state):
            return
        n = len(self.starts)
        if n in self.fail_starts:
            if self.now - self.started_at[n] >= self.fail_after:
                self.process_state = None                       # MT5 closed early, no output
            return
        manifest = read_json(self.runner.path('batch') / 'manifest.json')
        index = [m['config_path'] for m in manifest['members']].index(self.starts[-1])
        self.output(manifest['members'][index]);self.process_state = None

    def jobs(self, n):
        import copy
        for symbol in ('GBPUSD', 'USDJPY')[:n - 1]:
            extra = copy.deepcopy(self.plan['jobs'][0]);extra['tester']['Symbol'] = symbol;self.plan['jobs'].append(extra)

    def state(self):
        return read_json(self.runner.path('batch') / 'state.json')

    def test_a_fast_fail_is_recorded_and_re_run_once_after_its_delay(self):
        self.fail_starts = {1}
        self.prepare();result = self.runner.start('batch', 400)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.starts), 2, 'one re-run')
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('completed', 2))
        first = m['fast_fail']['first_attempt']
        self.assertLess(first['ran_seconds'], fast_fail.FAST_FAIL_SECONDS)
        self.assertIn('MT5 closed after', first['error'])
        self.assertGreaterEqual(self.started_at[2] - first['finished_unix'], fast_fail.RETRY_DELAY_SECONDS)

    def test_a_second_fast_fail_is_final_with_both_attempts(self):
        self.fail_starts = {1, 2}
        self.prepare();result = self.runner.start('batch', 400)
        self.assertEqual(len(self.starts), 2, 'never a third start')
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('missing_output', 2))
        self.assertIn('Fast-failed twice', m['error'])
        self.assertIn('first attempt closed after', m['error'])
        self.assertEqual(result['status'], 'stopped')          # its only member failed: every_member_failed, as before

    def test_a_slow_failure_is_never_re_run(self):
        self.fail_starts = {1};self.fail_after = 40             # MT5 closed after 40 s: it ran, so it is not a fast-fail
        self.plan['job_timeout_seconds'] = 120                  # inside its budget (the fixture's 30 s would time it out)
        self.prepare();self.runner.start('batch', 400)
        self.assertEqual(len(self.starts), 1)
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('missing_output', 1))
        self.assertNotIn('fast_fail', m)

    def test_the_re_run_waits_for_the_batchs_other_pending_members(self):
        self.jobs(3);self.fail_starts = {1}
        self.prepare();result = self.runner.start('batch', 600)
        self.assertEqual(result['status'], 'completed')
        order = [Path(c).name for c in self.starts]
        manifest = read_json(self.runner.path('batch') / 'manifest.json')
        names = [Path(m['config_path']).name for m in manifest['members']]
        self.assertEqual(order, [names[0], names[1], names[2], names[0]])
        self.assertEqual([m['attempts'] for m in self.state()['members']], [2, 1, 1])

    # ---- the re-run's edges with stops, the breaker and restarts, at the real 30 s window (Claude-Mac goatai#2943 7227893902)
    def more_jobs(self, symbols):
        import copy
        for symbol in symbols:
            extra = copy.deepcopy(self.plan['jobs'][0]);extra['tester']['Symbol'] = symbol;self.plan['jobs'].append(extra)

    def waiting_rerun(self):
        """Member 1 fast-fails (14 s), member 2 completes, and the driver returns before member 1's re-run is due."""
        self.jobs(2);self.fail_starts = {1}
        self.prepare();self.runner.start('batch', 40)
        first, second = self.state()['members']
        self.assertEqual([(m['status'], m['attempts']) for m in (first, second)], [('pending', 1), ('completed', 1)])
        self.assertTrue(fast_fail.waiting_retry(first));self.assertFalse(fast_fail.retry_due(first, self.now))
        self.assertEqual(len(self.starts), 2)

    def assert_final_cancelled(self):
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('cancelled', 1), 'the waiting re-run ended final, never run')
        self.assertIn('fast_fail', m, 'the first attempt stays recorded')
        self.assertFalse(SeedRunner.resumable(self.state()))
        self.assertEqual(len(self.starts), 2, 'no re-run launched')

    def test_a_human_cancel_ends_a_waiting_re_run_for_good(self):
        self.waiting_rerun()
        self.runner.cancel('batch')
        self.assertEqual(self.state()['status'], 'stopped')
        self.assert_final_cancelled()
        self.now += 120                                          # past the re-run's due time: a status read starts nothing
        self.runner.status('batch')
        self.assert_final_cancelled()

    def test_a_recorded_cancel_request_wins_over_a_due_re_run(self):
        # The batch-cancel GV / cancel-request route: honoured at the next safe point, even when the re-run is already due.
        self.waiting_rerun()
        self.runner.request_cancel('batch', now=self.now)
        self.now += 120
        self.assertTrue(fast_fail.retry_due(self.state()['members'][0], self.now))
        result = self.runner.resume('batch', 200)
        self.assertTrue(result['cancel_request_honoured'])
        self.assert_final_cancelled()

    def test_an_owner_stop_before_the_re_run_launches_nothing_and_its_cancel_is_final(self):
        # An owner STOP read right before the re-run's launch: nothing is launched, and the STOP the demo agent then applies
        # (seed-cancel, demo_agent._stop_seed) ends the member for good. The retry never undoes the stop.
        self.waiting_rerun()
        self.runner.stop_requested = lambda: 'owner_stop'
        self.now += 120
        result = self.runner.resume('batch', 200)
        self.assertTrue(result['stopped_before_launch'])
        self.assertEqual(len(self.starts), 2)
        self.runner.cancel('batch')
        self.assert_final_cancelled()

    def test_the_breaker_counts_a_fast_failed_member_once(self):
        # Members 1-3 fast-fail on their first attempt: pending, not failures, so three in a row do not trip the breaker and
        # members 4-5 run. Member 1's re-run fails too (one failure); members 2-3's re-runs complete (none).
        self.more_jobs(('GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'));self.fail_starts = {1, 2, 3, 6}
        self.plan['job_timeout_seconds'] = 30
        self.prepare();result = self.runner.start('batch', 600)
        state = self.state()
        self.assertEqual(len(self.starts), 8)
        self.assertEqual([(m['status'], m['attempts']) for m in state['members']],
                         [('missing_output', 2), ('completed', 2), ('completed', 2), ('completed', 1), ('completed', 1)])
        self.assertEqual((result['status'], state['failed_members']), ('completed', 1))
        self.assertNotIn('stopped_reason', state)
        self.assertIn('Fast-failed twice', state['members'][0]['error'])

    def test_failed_re_runs_count_toward_the_breaker_once_each(self):
        # Every first attempt fast-fails (all pending, no breaker); the first three re-runs fail: three failures in a row,
        # each member counted once, and the breaker stops the batch with the last two re-runs still waiting.
        self.more_jobs(('GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'));self.fail_starts = set(range(1, 9))
        self.prepare();result = self.runner.start('batch', 600)
        state = self.state();reason = state['stopped_reason']
        self.assertEqual(len(self.starts), 8)
        self.assertEqual((result['status'], reason['rules']), ('stopped', ['in_a_row']))
        self.assertEqual((reason['attempted'], reason['failed'], reason['in_a_row'], reason['pending']), (3, 3, 3, 2))
        self.assertEqual([(m['status'], m['attempts']) for m in state['members']],
                         [('missing_output', 2)] * 3 + [('pending', 1)] * 2)
        self.assertTrue(SeedRunner.resumable(state), 'seed-resume continues the two waiting re-runs')

    def test_a_restart_resumes_a_waiting_re_run_exactly_once(self):
        # The driver returned (budget) with member 1 waiting; a fresh runner, as after a restart, reads only the persisted
        # attempts and fast_fail record, runs the re-run once, and never again.
        self.waiting_rerun()
        saved = self.state()['members'][0]
        self.assertEqual((saved['attempts'], sorted(saved['fast_fail'])), (1, ['agent_log', 'first_attempt', 'plain', 'retry_after_unix']))
        self.runner = SeedRunner(self.controller, process=self.process, clock=lambda: self.now, sleep=self.sleep)
        self.runner.agents_root = self.agents
        result = self.runner.resume('batch', 200)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.starts), 3, 'one re-run')
        self.assertEqual([(m['status'], m['attempts']) for m in self.state()['members']], [('completed', 2), ('completed', 1)])
        self.runner.resume('batch', 200)
        self.assertEqual(len(self.starts), 3, 'never twice')

    def test_resumable_accepts_a_waiting_re_run_but_not_a_plain_attempted_member(self):
        base = dict(status='stopped', generation=1, error=None)
        waiting = dict(alias='a', status='pending', attempts=1, fast_fail=dict(retry_after_unix=1.0))
        fresh = dict(alias='b', status='pending', attempts=0)
        self.assertTrue(SeedRunner.resumable(dict(base, members=[waiting, fresh])))
        self.assertFalse(SeedRunner.resumable(dict(base, members=[dict(alias='c', status='pending', attempts=1), fresh])))


class EmptyReportFastFailTests(unittest.TestCase):
    """B57 (goatai#2943, Claude-Mac 7226979353): the 2026-11-27 SP500 probe shape. The real HoldupRunner, driver, report
    parser and checks run; only MT5 is a fixture, and its empty report is the real one's bytes."""

    def setUp(self):
        holdup_fixture.HoldupTests.setUp(self)
        self.empty_starts = set()       # 1-based start numbers whose MT5 writes the empty report and closes
        self.empty_after = 15           # seconds: the 11-27 member closed after 15 s
        self.started_at = {}
        self.runner.agents_root = self.root / 'agents'
        self.empty = gzip.decompress(EMPTY_REPORT.read_bytes())

    tearDown, close, mt5_writes_report, write_set, spec_for, plan = (
        holdup_fixture.HoldupTests.tearDown, holdup_fixture.HoldupTests.close, holdup_fixture.HoldupTests.mt5_writes_report,
        holdup_fixture.HoldupTests.write_set, holdup_fixture.HoldupTests.spec_for, holdup_fixture.HoldupTests.plan)

    def start(self, config):
        identity = holdup_fixture.HoldupTests.start(self, config)
        self.started_at[len(self.starts)] = self.now
        return identity

    def report_path(self):
        alias = read_json(self.runner.path('h1') / 'manifest.json')['members'][0]['alias']
        return Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/HoldupReports' / (alias + '.htm'), alias

    def sleep(self, seconds):
        self.now += seconds
        if not (self.starts and self.process_state):
            return
        n = len(self.starts)
        if n in self.empty_starts:
            if self.now - self.started_at[n] >= self.empty_after:
                path, alias = self.report_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.empty)                       # MT5's own empty report, as written on 11-27
                for png in ('-hst', '-mfemae', '-holding'):
                    path.with_name(alias + png + '.png').write_bytes(b'png')
                self.process_state = None
            return
        self.mt5_writes_report(0)
        self.process_state = None

    def state(self):
        return read_json(self.runner.path('h1') / 'state.json')

    def run_batch(self):
        self.runner.prepare('h1', self.plan())
        return self.runner.start('h1', 400)

    def test_the_real_empty_report_names_nothing_and_a_real_report_names_its_expert(self):
        self.assertEqual(hashlib.sha256(self.empty).hexdigest(), EMPTY_REPORT_SHA256)
        path = self.root / 'empty.htm';path.write_bytes(self.empty)
        report = tester_report.read_report(path)
        self.assertTrue(fast_fail.names_nothing(report))
        self.assertEqual((report['settings']['period'], report['settings']['from_date'], report['results']['deals']), ('M0', '1970.01.01', 0))
        good = self.root / 'good.htm';good.write_bytes(b'\xff\xfe' + holdup_fixture.fixture_text().encode('utf-16-le'))
        self.assertFalse(fast_fail.names_nothing(tester_report.read_report(good)))

    def test_an_empty_report_inside_30_s_is_set_aside_and_re_run_once(self):
        self.empty_starts = {1}
        result = self.run_batch()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.starts), 2, 'one re-run')
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('completed', 2))
        first = m['fast_fail']['first_attempt']
        self.assertEqual(first['kind'], 'empty_report')
        self.assertLess(first['ran_seconds'], fast_fail.FAST_FAIL_SECONDS)
        self.assertIn('report expert is , the frozen test ran', first['error'])     # the collector's own refusal, unchanged
        self.assertGreaterEqual(self.started_at[2] - first['finished_unix'], fast_fail.RETRY_DELAY_SECONDS)
        # Moved, never deleted: the empty report's exact bytes now sit in the batch folder; the member's report is the re-run's.
        moved = Path(first['report']['path'])
        self.assertEqual(moved.parent, self.runner.path('h1'))
        self.assertEqual((first['report']['sha256'], hashlib.sha256(moved.read_bytes()).hexdigest()), (EMPTY_REPORT_SHA256,) * 2)
        path, _ = self.report_path()
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), EMPTY_REPORT_SHA256)
        self.assertIn('empty report', m['fast_fail']['plain'])

    def test_a_second_empty_report_is_final_with_both_attempts(self):
        self.empty_starts = {1, 2}
        result = self.run_batch()
        self.assertEqual(len(self.starts), 2, 'never a third start')
        m = self.state()['members'][0]
        self.assertEqual((m['status'], m['attempts']), ('failed', 2))
        self.assertIn('Fast-failed twice', m['error'])
        self.assertEqual(result['status'], 'stopped')
        path, _ = self.report_path()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), EMPTY_REPORT_SHA256, 'the final one stays where MT5 wrote it')

    def test_a_slow_empty_report_or_a_fast_report_that_names_its_test_is_never_re_run(self):
        # 40 s: MT5 ran long enough to be more than a bind failure, so the report's refusal stands.
        self.empty_starts = {1};self.empty_after = 40
        self.run_batch()
        m = self.state()['members'][0]
        self.assertEqual((len(self.starts), m['status'], m['attempts']), (1, 'failed', 1))
        self.assertNotIn('fast_fail', m)
        self.assertTrue(m.get('empty_report'))
        # A fast report that names its expert and symbol but ran a different input: a real refusal, never re-run.
        self.tearDown();self.setUp()
        self.drift = {'Grid_Size': ('-4', '-6')}
        self.run_batch()
        m = self.state()['members'][0]
        self.assertEqual((len(self.starts), m['status'], m['attempts']), (1, 'failed', 1))
        self.assertIn('MT5 ran different inputs than the frozen SET', m['error'])
        self.assertNotIn('fast_fail', m)
        self.assertNotIn('empty_report', m)


class AgentLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_log(self, agent, day, lines):
        path = self.root / agent / 'logs' / (day + '.log');path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xff\xfe' + '\r\n'.join(lines).encode('utf-16-le'))
        return path

    def test_the_window_lines_come_back_notable_first_and_outside_ones_never(self):
        start = datetime(2026, 11, 14, 11, 43, 43).timestamp()      # local clock, as MT5 writes its logs
        self.write_log('Agent-127.0.0.1-3024', '20261114', [
            'CS\t0\t11:43:43.808\tStartup\tMetaTester 5 build 6230, 25 Sep 2026',
            'CS\t3\t11:43:43.810\tServer\tbind error on 127.0.0.1:3024 [10048]',
            'CS\t0\t11:50:00.000\tTester\tan unrelated later line'])
        got = fast_fail.agent_log_lines({}, start - 1, start + 14, agents_root=self.root)
        self.assertEqual(len(got), 2)
        self.assertIn('bind error on 127.0.0.1:3024 [10048]', got[0])
        self.assertNotIn('unrelated', ' '.join(got))

    def test_window_lines_buried_behind_megabytes_of_later_lines_are_still_found(self):
        # The 11-14 probe: by the time it ran, Banker's agent 3024 had logged ~9,400 trade lines after the window, so the
        # first 2 MB tail no longer reached 11:43:43. The tail widens until it reaches back past the window.
        start = datetime(2026, 11, 14, 11, 43, 43).timestamp()
        later = ['CS\t0\t13:%02d:%02d.000\tTrade\t2026.11.10 16:31:28   stop loss triggered #914 sell 0.05 %s'
                 % (i // 60 % 60, i % 60, 'x' * 60) for i in range(3000)]
        self.write_log('Agent-127.0.0.1-3024', '20261114', ['CS\t3\t11:43:43.810\tServer\tbind error on 127.0.0.1:3024 [10048]'] + later)
        with unittest.mock.patch.object(fast_fail, 'AGENT_TAIL_BYTES', 4096):
            got = fast_fail.agent_log_lines({}, start - 1, start + 14, agents_root=self.root)
        self.assertEqual(len(got), 1)
        self.assertIn('bind error on 127.0.0.1:3024 [10048]', got[0])

    def test_an_unreadable_agents_folder_never_raises(self):
        t = 1794685416.0                                            # 00179's real launch time
        self.assertEqual(fast_fail.agent_log_lines({}, t, t + 14, agents_root=self.root / 'missing'), [])
        self.assertTrue(fast_fail.agent_log_lines(None, t, t + 14)[0].startswith('agent logs could not be read'))


if __name__ == '__main__':
    unittest.main()
