"""Fast-fail re-run, once (studio_fast_fail; goatai#2750, Claude-Mac 6884089927 option (b)). Fixture-only.

Replays the 2026-11-14 Banker loss: tier D member _00179's MT5 closed 14 s into an 1800 s budget with no export (its tester
agent hit `bind error on 127.0.0.1:3024 [10048]` while T3's agent held the port). Such a member is re-run once, after the
batch's other pending members and not before RETRY_DELAY_SECONDS; a second fast-fail is final; nothing else is re-run.
"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import unittest.mock

from studio_installation import read_json
from studio_seed import SeedRunner
import studio_fast_fail as fast_fail
# Fixture module, not its TestCase class: importing the class here would run its suite twice.
import test_studio_seed as seed_fixture


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

    def test_three_fast_fails_in_a_row_trip_the_breaker_with_their_members_pending(self):
        # A systemic launch fault (every MT5 closes at once): the breaker counts each first attempt, so it stops after 3
        # launches, not after every member was also re-run once. The members wait as pending for their one re-run.
        self.jobs(3);import copy
        for symbol in ('EURJPY', 'AUDJPY'):
            extra = copy.deepcopy(self.plan['jobs'][0]);extra['tester']['Symbol'] = symbol;self.plan['jobs'].append(extra)
        self.fail_starts = {1, 2, 3, 4, 5, 6}
        self.prepare();result = self.runner.start('batch', 400)
        self.assertEqual(len(self.starts), 3, 'stopped after three launches')
        self.assertEqual((result['status'], result['stopped_reason']['rules']), ('stopped', ['in_a_row']))
        members = self.state()['members']
        self.assertEqual([m['status'] for m in members], ['pending'] * 5)
        self.assertEqual([bool(m.get('fast_fail')) for m in members], [True, True, True, False, False])
        self.assertTrue(SeedRunner.resumable(self.state()))

    def test_resumable_accepts_a_waiting_re_run_but_not_a_plain_attempted_member(self):
        base = dict(status='stopped', generation=1, error=None)
        waiting = dict(alias='a', status='pending', attempts=1, fast_fail=dict(retry_after_unix=1.0))
        fresh = dict(alias='b', status='pending', attempts=0)
        self.assertTrue(SeedRunner.resumable(dict(base, members=[waiting, fresh])))
        self.assertFalse(SeedRunner.resumable(dict(base, members=[dict(alias='c', status='pending', attempts=1), fresh])))


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
