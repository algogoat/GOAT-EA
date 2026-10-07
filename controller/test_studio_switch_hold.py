"""Member switch hold (goatai#1885, Claude-Mac 6022613005 / 6036112715).

A fake wall clock drives every case. The hold waits for the Exp 02 quiet slot, never longer
than its bound, is off by default, fails open on unreadable publisher state, and never
delays a stop, cancel or pause.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_agent
import studio_switch_hold as hold
import test_studio_seed as seed_fixture
from studio_installation import read_json
from studio_seed import SeedRunner

ODD = 29_000_001                 # an odd epoch minute
T0 = ODD * 60.0                  # its :00 second
EVEN = T0 + 60.0                 # the following even minute
CLOCK = dict(mode='exp02', state_path=None, max_seconds=90, source='test')


def cycle(start, end=None, pid=7):
    rows = [dict(event='START', pid=pid, startedAt=int(start * 1000), endedAt=None)]
    if end is not None:
        rows.append(dict(event='END', pid=pid, startedAt=int(start * 1000), endedAt=int(end * 1000), exitCode=0))
    return rows


def run_until_start(config, start, *, read=hold.read_cycles, step=1.0, limit=400):
    """Drive decide() one pass per ``step`` seconds from ``start``; return (start time, journal rows)."""
    retained, now, rows = None, start, []
    for _ in range(int(limit / step)):
        result = hold.decide(config, retained, member_id='m1', now=now, read=read)
        if result['journal']:
            rows.append(result['journal'])
        if result['start']:
            return now, rows
        retained = result['hold']
        now = min(now + step, max(now, retained['deadline_unix']))
    raise AssertionError('never started')


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / hold.CONFIG_NAME

    def tearDown(self):
        self.tmp.cleanup()

    def test_off_by_default(self):
        self.assertIsNone(hold.load_config({}, self.file))
        self.assertIsNone(hold.load_config({}, None))
        for value in ('', 'off', '0', 'OFF', 'none', 'false', 'exp01', 'bogus'):
            self.assertIsNone(hold.load_config({hold.ENV_MODE: value}, self.file), value)

    def test_environment_enables_with_a_bound_of_at_most_90_seconds(self):
        config = hold.load_config({hold.ENV_MODE: ' EXP02 '}, None)
        self.assertEqual((config['mode'], config['state_path'], config['max_seconds']), ('exp02', None, 90))
        config = hold.load_config({hold.ENV_MODE: 'exp02', hold.ENV_STATE: 'G:\\pair\\cycle-identities.jsonl',
                                   hold.ENV_MAX: '600'}, None)
        self.assertEqual((config['state_path'], config['max_seconds']), ('G:\\pair\\cycle-identities.jsonl', 90))
        self.assertEqual(hold.load_config({hold.ENV_MODE: 'exp02', hold.ENV_MAX: '20'}, None)['max_seconds'], 20)
        for bad in ('-1', '0', 'nan', 'inf', 'soon'):
            self.assertIsNone(hold.load_config({hold.ENV_MODE: 'exp02', hold.ENV_MAX: bad}, None), bad)

    def test_lane_config_file_and_the_environment_wins(self):
        self.file.write_text(json.dumps(dict(mode='exp02', state_path='C:\\x.jsonl', max_seconds=300)), encoding='utf-8')
        config = hold.load_config({}, self.file)
        self.assertEqual((config['mode'], config['state_path'], config['max_seconds']), ('exp02', 'C:\\x.jsonl', 90))
        self.assertIsNone(hold.load_config({hold.ENV_MODE: 'off'}, self.file))
        for text in ('{', '[]', json.dumps(dict(mode='exp03')), json.dumps(dict(mode='exp02', state_path=5)),
                     json.dumps(dict(mode='exp02', max_seconds=-3)), ' ' * (hold.MAX_CONFIG_BYTES + 1)):
            self.file.write_text(text, encoding='utf-8')
            self.assertIsNone(hold.load_config({}, self.file), text[:40])


class SlotTests(unittest.TestCase):
    def test_clock_slot_is_seconds_35_to_55_of_an_odd_minute(self):
        for offset, expected in ((0, False), (20, False), (34.9, False), (35, True), (45, True), (54.9, True),
                                 (55, False), (60 + 40, False), (120 + 40, True)):
            self.assertEqual(hold.quiet(T0 + offset, CLOCK)[0], expected, offset)

    def test_publisher_state_waits_for_the_cycle_end(self):
        config = dict(CLOCK, state_path='state')
        running = lambda path: cycle(T0 + 1)
        ended = lambda path: cycle(T0 - 120 + 1, T0 - 120 + 25, pid=6) + cycle(T0 + 1, T0 + 40)
        self.assertEqual(hold.quiet(T0 + 45, config, running), (False, 'exp02_cycle_running', 'publisher_state'))
        self.assertEqual(hold.quiet(T0 + 45, config, ended), (True, 'exp02_cycle_ended', 'publisher_state'))
        self.assertEqual(hold.quiet(T0 + 20, config, ended)[0], False)       # ended, but before the slot
        self.assertEqual(hold.quiet(EVEN + 40, config, ended)[0], False)     # never in an even minute

    def test_an_idle_publisher_is_not_waited_for(self):
        config = dict(CLOCK, state_path='state')
        old = lambda path: cycle(EVEN - 600, EVEN - 590)
        self.assertEqual(hold.quiet(EVEN + 10, config, old), (True, 'publisher_idle', 'publisher_state'))

    def test_reads_only_the_tail_of_the_real_log(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'cycle-identities.jsonl'
            rows = [row for n in range(400) for row in cycle(T0 - 120 * (400 - n) + 1, T0 - 120 * (400 - n) + 25, pid=n)]
            rows += cycle(T0 + 1)
            path.write_text('\n'.join(json.dumps(row) for row in rows) + '\nnot json\n', encoding='utf-8')
            before = path.read_bytes()
            self.assertGreater(len(before), hold.TAIL_BYTES)
            tail = hold.read_cycles(path)
            self.assertLess(len(tail), len(rows))
            self.assertEqual(tail[-1]['startedAt'], int((T0 + 1) * 1000))
            self.assertEqual(hold.quiet(T0 + 40, dict(CLOCK, state_path=str(path))), (False, 'exp02_cycle_running', 'publisher_state'))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(OSError):
                hold.read_cycles(Path(work) / 'missing.jsonl')
            path.write_text('garbage\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                hold.read_cycles(path)


class DecideTests(unittest.TestCase):
    def test_off_starts_now_without_a_journal(self):
        self.assertEqual(hold.decide(None, None, member_id='m1', now=T0 + 5), dict(start=True, hold=None, journal=None))

    def test_waits_until_the_clock_slot(self):
        started, rows = run_until_start(CLOCK, T0 + 5)
        self.assertEqual(started, T0 + 35)
        self.assertEqual([r[1]['phase'] for r in rows], ['holding', 'released'])
        self.assertEqual(rows[0][1]['reason'], 'outside_clock_slot')
        self.assertEqual(rows[1][1], dict(phase='released', waited_ms=30000, reason='clock_slot', source='clock', member_id='m1'))

    def test_already_in_the_slot_starts_now_and_logs_zero(self):
        started, rows = run_until_start(CLOCK, T0 + 40)
        self.assertEqual((started, rows[-1][1]['waited_ms'], len(rows)), (T0 + 40, 0, 1))

    def test_waits_for_a_slow_publisher_cycle_to_end(self):
        clock = {}
        def read(path):
            return cycle(T0 + 1, T0 + 47) if clock['now'] >= T0 + 47 else cycle(T0 + 1)
        config = dict(CLOCK, state_path='state')
        retained, now = None, T0 + 30
        while True:
            clock['now'] = now
            result = hold.decide(config, retained, member_id='m1', now=now, read=read)
            if result['start']:
                break
            retained, now = result['hold'], now + .5
        self.assertEqual(now, T0 + 47)
        self.assertEqual(result['journal'][1]['reason'], 'exp02_cycle_ended')

    def test_bound_is_never_exceeded(self):
        config = dict(CLOCK, state_path='state')
        always_running = lambda path: cycle(T0 + 1)
        for start in (T0 + 56, T0 + 2, EVEN + 1):
            for step in (1.0, 7.0, 0.25):
                started, rows = run_until_start(config, start, read=always_running, step=step)
                self.assertLessEqual(started - start, hold.MAX_HOLD_SECONDS)
                self.assertLessEqual(rows[-1][1]['waited_ms'], hold.MAX_HOLD_SECONDS * 1000)
        started, rows = run_until_start(config, T0 + 56, read=always_running)
        self.assertEqual((started - (T0 + 56), rows[-1][1]['reason']), (90, 'bound'))
        started, rows = run_until_start(dict(config, max_seconds=20), T0 + 56, read=always_running)
        self.assertEqual(started - (T0 + 56), 20)

    def test_unreadable_state_fails_open(self):
        def broken(path):
            raise OSError('locked')
        result = hold.decide(dict(CLOCK, state_path='state'), None, member_id='m1', now=T0 + 5, read=broken)
        self.assertTrue(result['start'])
        self.assertEqual(result['journal'][1]['waited_ms'], 0)
        self.assertTrue(result['journal'][1]['reason'].startswith('fail_open: publisher state unreadable'))
        result = hold.decide(dict(CLOCK, state_path='state'), None, member_id='m1', now=T0 + 5,
                             read=lambda path: (_ for _ in ()).throw(ValueError('No publisher cycle rows')))
        self.assertTrue(result['start'])

    def test_retained_hold_rules(self):
        first = hold.decide(CLOCK, None, member_id='m1', now=T0 + 5)['hold']
        self.assertEqual(first['deadline_unix'] - first['since_unix'], 90)
        # Another member's hold, or one interrupted long ago, starts a fresh bounded hold.
        other = hold.decide(CLOCK, first, member_id='m2', now=T0 + 6)['hold']
        self.assertEqual((other['member_id'], other['since_unix']), ('m2', T0 + 6))
        stale = hold.decide(CLOCK, first, member_id='m1', now=T0 + 5 + 90 + hold.STALE_HOLD_SECONDS + 1 + 120)
        self.assertEqual(stale['hold']['since_unix'], T0 + 5 + 90 + hold.STALE_HOLD_SECONDS + 1 + 120)
        # A malformed or over-long retained hold, or a clock that went back, starts now.
        for bad in (dict(first, deadline_unix='x'), dict(first, deadline_unix=first['since_unix'] + 500),
                    dict(first, since_unix=float('nan'))):
            self.assertTrue(hold.decide(CLOCK, bad, member_id='m1', now=T0 + 6)['start'])
        self.assertTrue(hold.decide(CLOCK, first, member_id='m1', now=T0 + 1)['start'])
        self.assertTrue(hold.decide(dict(mode='exp02'), None, member_id='m1', now=T0 + 5)['start'])
        self.assertTrue(hold.decide(CLOCK, None, member_id='m1', now=float('nan'))['start'])


class RunnerHoldTests(unittest.TestCase):
    """The seed/catch-up/hold-up member loop (studio_seed._drive) on the seed fixture's fake MT5 and clock."""
    MAX_PASSES = 500    # a hold that never advances the clock fails fast instead of spinning forever

    def setUp(self):
        seed_fixture.SeedTests.setUp(self)
        self.passes = 0
        def pump():
            self.passes += 1
            if self.passes > self.MAX_PASSES:
                raise AssertionError('driver spun without advancing the clock')
        self.controller.bridge.pump = pump

    tearDown = seed_fixture.SeedTests.tearDown
    close = seed_fixture.SeedTests.close
    start = seed_fixture.SeedTests.start
    prepare = seed_fixture.SeedTests.prepare

    def sleep(self, seconds):
        self.now += seconds
        for at, action in list(getattr(self, 'events', [])):
            if self.now >= at:
                self.events.remove((at, action))
                action()

    def arm(self, config, at):
        self.prepare()
        self.journal = []
        self.runner.switch_hold = config
        self.runner.locked_journal = lambda event, details: self.journal.append((event, details))
        self.now = at

    def state(self):
        return read_json(self.runner.path('batch') / 'state.json')

    def test_runner_default_is_off_and_starts_at_once(self):
        self.assertIsNone(SeedRunner(self.controller, process=self.process).switch_hold)
        self.prepare()
        self.now = EVEN + 10
        self.runner.start('batch', 5)
        self.assertEqual(len(self.starts), 1)
        self.assertNotIn('switch_hold', self.state()['members'][0])

    def test_member_starts_in_the_quiet_slot_and_the_hold_is_journaled(self):
        self.arm(CLOCK, T0 + 5)
        self.runner.start('batch', 40)
        member = self.state()['members'][0]
        self.assertEqual(len(self.starts), 1)
        self.assertTrue(T0 + 35 <= member['started_unix'] < T0 + 36)
        self.assertEqual(member['switch_hold']['reason'], 'clock_slot')
        self.assertTrue(29000 <= member['switch_hold']['waited_ms'] <= 31000)
        self.assertEqual([d['phase'] for _, d in self.journal], ['holding', 'released'])
        self.assertNotIn('switch_hold', self.state())

    def test_bound_holds_across_the_demo_lanes_short_slices(self):
        log = Path(self.tmp.name) / 'cycle-identities.jsonl'
        log.write_text(json.dumps(cycle(T0 + 1)[0]) + '\n', encoding='utf-8')      # a cycle that never ends
        self.arm(dict(CLOCK, state_path=str(log)), T0 + 30)
        self.runner.start('batch', 5)
        ready = self.state()['switch_hold']['since_unix']
        for _ in range(40):
            if self.starts:
                break
            self.runner.resume('batch', 5, reactivate=False)
        member = self.state()['members'][0]
        self.assertEqual(len(self.starts), 1)
        self.assertLessEqual(member['started_unix'] - ready, hold.MAX_HOLD_SECONDS)
        self.assertGreaterEqual(member['started_unix'] - ready, hold.MAX_HOLD_SECONDS - 1)
        self.assertEqual(member['switch_hold']['reason'], 'bound')
        self.assertLessEqual(member['switch_hold']['waited_ms'], hold.MAX_HOLD_SECONDS * 1000)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows gate semantics')
    def test_a_busy_gate_during_a_hold_is_skipped_and_the_member_still_starts_in_the_slot(self):
        # #195 and #194 together: a status reader holding launch.lock past the 1 s wait skips a pass
        # (never fails the driver), and the hold still releases in the quiet slot.
        import threading, time
        from studio_native_gate import exclusive_gate
        self.arm(CLOCK, T0 + 5)
        holding, release = threading.Event(), threading.Event()
        def hold():
            with exclusive_gate(self.runner.gate):
                holding.set(); release.wait(10)
        thread = threading.Thread(target=hold, daemon=True); thread.start(); holding.wait(5)
        timer = threading.Timer(1.5, release.set); timer.start()
        try:
            self.runner.start('batch', 40)
        finally:
            release.set(); thread.join(5); timer.join()
        member = self.state()['members'][0]
        self.assertEqual(len(self.starts), 1)
        self.assertTrue(T0 + 35 <= member['started_unix'] < T0 + 36)
        self.assertEqual(member['switch_hold']['reason'], 'clock_slot')

    def test_unreadable_publisher_state_starts_now(self):
        self.arm(dict(CLOCK, state_path=str(Path(self.tmp.name) / 'missing.jsonl')), T0 + 5)
        self.runner.start('batch', 5)
        member = self.state()['members'][0]
        self.assertEqual(len(self.starts), 1)
        self.assertLess(member['started_unix'], T0 + 6)
        self.assertEqual(member['switch_hold']['waited_ms'], 0)

    def test_stop_during_a_hold_ends_it_at_once(self):
        self.arm(CLOCK, T0 + 5)
        stop_at = T0 + 12.1
        self.runner.stop_requested = lambda: 'owner_stop' if self.now >= stop_at else None
        result = self.runner.start('batch', 60)
        self.assertEqual(result['switch_hold_interrupted'], 'stop')
        self.assertEqual(self.starts, [])
        self.assertLessEqual(self.now - stop_at, SeedRunner.HOLD_POLL_SECONDS)

    def test_pause_during_a_hold_ends_it_at_once(self):
        self.arm(CLOCK, T0 + 5)
        pause_at = T0 + 20.1
        self.events = [(pause_at, lambda: self.runner.request_pause('batch', now=self.now))]
        result = self.runner.start('batch', 60)
        self.assertTrue(result.get('paused'))
        self.assertEqual(self.starts, [])
        self.assertLessEqual(self.now - pause_at, SeedRunner.HOLD_POLL_SECONDS)

    def test_cancel_during_a_hold_ends_it_at_once(self):
        self.arm(CLOCK, T0 + 5)
        cancel_at = T0 + 15.1
        self.events = [(cancel_at, lambda: self.runner.cancel('batch'))]
        result = self.runner.start('batch', 60)
        self.assertEqual(self.starts, [])
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(self.state()['members'][0]['status'], 'cancelled')
        self.assertLessEqual(self.now - cancel_at, SeedRunner.HOLD_POLL_SECONDS)


class DemoLaneWiringTests(unittest.TestCase):
    """demo_agent._seed_drive gives the runner the PC's configuration and its stop check."""

    def drive(self, env, config_text=None):
        with tempfile.TemporaryDirectory() as work:
            state_root = Path(work)
            if config_text is not None:
                (state_root / hold.CONFIG_NAME).write_text(config_text, encoding='utf-8')
            seen = {}
            stop = lambda: None
            agent = SimpleNamespace(clock=lambda: 0.0, state_root=state_root, SEED_SLICE_SECONDS=5,
                                    _seed_stop_reason=stop, _append=lambda *a, **k: None)
            def resume(batch_id, max_seconds, reactivate):
                seen.update(switch_hold=runner.switch_hold, stop_requested=runner.stop_requested)
                return dict(status='completed')
            runner = SimpleNamespace(resume=resume, switch_hold='unset', stop_requested=None)
            with patch.dict(demo_agent.os.environ, env):
                if hold.ENV_MODE not in env:
                    demo_agent.os.environ.pop(hold.ENV_MODE, None)
                demo_agent.DemoAgent._seed_drive(agent, runner, 'batch', 5, initial=False)
            self.assertIs(seen['stop_requested'], stop)
            return seen['switch_hold']

    def test_off_for_testers_and_on_by_pc_config(self):
        self.assertIsNone(self.drive({}))
        self.assertEqual(self.drive({hold.ENV_MODE: 'exp02'})['mode'], 'exp02')
        self.assertEqual(self.drive({}, json.dumps(dict(mode='exp02')))['mode'], 'exp02')


if __name__ == '__main__':
    unittest.main()
