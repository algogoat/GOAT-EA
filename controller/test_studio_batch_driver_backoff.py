"""The observing driver backs off while nothing changes and names a stalled batch (goatai#1885).

Banker 2026-10-05: member 34 ended on the EA's tester-idle timeout and MT5 never
restarted for member 35. For 4.5 h the driver repeated a ~70 s CPU pass every 30 s
(about one full core) while the native queue stayed "not finished", and
research-status read ``running``. Driver fixtures come from test_studio_batch_driver
with a fake clock, so every wait below is simulated, never slept.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_driver as driver
from studio_batch_driver import (QUIET_BACKOFF_CAP_SECONDS, QUIET_PASS_COST_FACTOR, QUIET_WAIT_MAX_SECONDS, run, status)
import studio_batch_stall as stall
import studio_durable_driver as durable
from studio_research_status import research_status
import test_studio_batch_driver as fixtures

ATTEMPT = 'a' * 64
NOT_FINISHED = 'Native queue is not finished; reconcile, do not reset'
POLL = 30


class HostDeath(BaseException):
    pass


def members(*statuses):
    return [dict(index=i, status=s) for i, s in enumerate(statuses)]


BANKER = members('native_completed', 'native_error', 'native_queued', 'native_pending')


class ObserveBackoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BatchDriverTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.c, self.clock = self.fixture.c, self.fixture.c.clock
        self.passes = []          # monotonic time each reconcile (one per pass) began
        self.pass_cost = 0.0      # simulated CPU seconds one pass takes
        self.on_pass = None
        self.reply = lambda: dict(status='reconcile_required', revision=7, changed=False)
        self.c.reconcile = self.reconcile

    def reconcile(self, job_id):
        self.c.reconciles += 1
        self.passes.append(self.clock.mono)
        if self.on_pass:
            self.on_pass()
        self.clock.wall += self.pass_cost; self.clock.mono += self.pass_cost
        reply = self.reply()
        if isinstance(reply, Exception):
            raise reply
        return reply

    def finish(self, controller, job_id, *, expected_generation):
        if not self.c.finished:
            raise ValueError(NOT_FINISHED)
        return dict(status='cancelled' if self.c.cancels else 'completed', result={'attempt_id': ATTEMPT})

    def drive(self, **kwargs):
        return run(self.c, 'batch', poll_seconds=POLL, cancel_grace_seconds=2, clock=self.clock,
                   finish_fn=self.finish, **kwargs)

    def demo_lane(self):
        self.c.session['authority_kind'] = 'demo_direct'
        write_json(self.c.root / 'session.json', self.c.session)
        self.c.bridge = SimpleNamespace(root=self.c.local / self.c.run)

    def gaps(self):
        return [round(b - a, 3) for a, b in zip(self.passes, self.passes[1:])]

    def journal(self):
        return json.loads((self.c.root / 'batch-drivers' / 'batch.json').read_text())

    # ---------------------------------------------------------------- backoff

    def test_unchanged_native_queue_backs_off_to_the_cap_and_never_spins(self):
        result = self.drive(max_seconds=7200)
        self.assertTrue(result['stopped'])          # the deadline still cancels exactly once
        self.assertEqual(self.c.cancels, 1)
        gaps = self.gaps()[:-1]                     # the last gap is cut by the deadline
        self.assertEqual(gaps[:4], [POLL, 2 * POLL, QUIET_BACKOFF_CAP_SECONDS, QUIET_BACKOFF_CAP_SECONDS])
        self.assertGreaterEqual(min(gaps), POLL)
        self.assertLessEqual(max(gaps), QUIET_BACKOFF_CAP_SECONDS)
        # Before: a pass every 30 s, 240 passes in 2 h. Now: about one every 2 min.
        self.assertLessEqual(len(self.passes), 7200 // QUIET_BACKOFF_CAP_SECONDS + 6)
        self.assertGreaterEqual(len(self.passes), 7200 // QUIET_WAIT_MAX_SECONDS)
        observe = status(self.c, 'batch')['observe']
        self.assertEqual(observe['next_wait_seconds'], QUIET_BACKOFF_CAP_SECONDS)
        self.assertGreater(observe['quiet_passes'], 40)

    def test_a_slow_pass_waits_at_least_twice_its_cost_so_the_driver_never_holds_a_core(self):
        self.pass_cost = 70.0                        # Banker's measured pass
        self.drive(max_seconds=3600)
        # Full quiet cycles: after the first (progress) pass, before the deadline cuts a wait.
        cycles = self.gaps()[1:-2]
        self.assertGreaterEqual(len(cycles), 10)
        self.assertGreaterEqual(min(cycles) - self.pass_cost, QUIET_PASS_COST_FACTOR * self.pass_cost)
        busy = self.pass_cost * len(cycles) / sum(cycles)
        self.assertLessEqual(busy, 1 / (1 + QUIET_PASS_COST_FACTOR) + 1e-6)   # was 70 / (70 + 30) = 0.7

    def test_the_wait_is_bounded_even_for_a_pathologically_slow_pass(self):
        self.pass_cost = 1000.0
        self.drive(max_seconds=20000)
        waits = [gap - self.pass_cost for gap in self.gaps()[1:-2]]
        self.assertTrue(waits)
        self.assertLessEqual(max(waits), QUIET_WAIT_MAX_SECONDS)

    def test_progress_resets_the_wait_to_poll_seconds(self):
        def reply():
            changed = len(self.passes) == 6
            return dict(status='reconcile_required', revision=8 if len(self.passes) >= 6 else 7, changed=changed)
        self.reply = reply
        self.drive(max_seconds=1800)
        gaps = self.gaps()
        self.assertEqual(gaps[4], QUIET_BACKOFF_CAP_SECONDS)   # backed off before the change
        self.assertEqual(gaps[5], POLL)                         # the pass after the change is back to poll
        self.assertEqual(gaps[6], 2 * POLL)

    def test_a_changed_observation_is_progress_even_without_a_new_revision(self):
        self.reply = lambda: dict(status='reconcile_required', revision=7, changed=len(self.passes) == 6)
        self.drive(max_seconds=1800)
        gaps = self.gaps()
        self.assertEqual((gaps[4], gaps[5], gaps[6]), (QUIET_BACKOFF_CAP_SECONDS, POLL, 2 * POLL))

    def test_a_repeating_error_backs_off_instead_of_retrying_tightly(self):
        self.reply = lambda: ValueError('Runtime policy mismatch: restart_pending')
        self.drive(max_seconds=3600)
        gaps = [round(b - a, 3) for a, b in zip(self.passes, self.passes[1:]) if b <= 3600]
        self.assertEqual(gaps[:3], [POLL, 2 * POLL, QUIET_BACKOFF_CAP_SECONDS])
        self.assertGreaterEqual(min(gaps), POLL)
        self.assertEqual(self.c.cancels, 1)

    def test_owner_stop_still_cancels_within_a_watch_tick_while_backed_off(self):
        self.demo_lane()
        stop = {}
        def maybe_stop():
            if self.clock.mono >= 1000 and not stop:
                marker = self.c.root / 'demo-agent/STOP'; marker.parent.mkdir(exist_ok=True); marker.write_text('{}')
                stop['at'] = self.clock.mono
        self.clock.on_sleep = maybe_stop
        result = self.drive(max_seconds=86400)
        self.assertEqual((result['status'], result['cancel_reason']), ('cancelled', 'owner_stop'))
        self.assertEqual(self.c.cancels, 1)
        before = [t for t in self.passes if t < stop['at']]
        after = [t for t in self.passes if t >= stop['at']]
        self.assertGreaterEqual(before[-1] - before[-2], QUIET_BACKOFF_CAP_SECONDS)   # it was backed off
        self.assertLessEqual(after[0] - stop['at'], driver.STOP_WATCH_SECONDS)

    def test_a_pause_request_wakes_a_backed_off_driver(self):
        written = {}
        def request_pause():
            if self.clock.mono >= 1000 and not written:
                (self.c.root / 'batch-pauses').mkdir(exist_ok=True)
                write_json(self.c.root / 'batch-pauses' / 'batch.json', dict(
                    schema_version=1, job_id='batch', pause_id='p' * 32, attempt_id=ATTEMPT,
                    configuration_sha256=self.c.current['configuration_sha256'], generation=3, state='pausing',
                    phase='waiting_safe_point', mode='safe_point', cancels=[], history=[]))
                written['at'] = self.clock.mono
        def die_once_paused():
            if written:
                raise HostDeath()
        self.clock.on_sleep, self.on_pass = request_pause, die_once_paused
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=86400)
        self.assertGreaterEqual(self.gaps()[-2], QUIET_BACKOFF_CAP_SECONDS)
        self.assertLessEqual(self.passes[-1] - written['at'], driver.STOP_WATCH_SECONDS)

    # ---------------------------------------------------------------- stall

    def stalled_run(self, *, statuses=BANKER, monitor=None, until=3600, change_at=None):
        self.demo_lane()
        seen = []
        def reply():
            ongoing = change_at is not None and self.clock.mono >= change_at
            native = members('native_completed', 'native_ongoing', 'native_pending') if ongoing else statuses
            return dict(status='running' if ongoing else 'reconcile_required', revision=9 if ongoing else 7, changed=False,
                        job=dict(native_observation=dict(native=dict(members=native), runtime=None, runtime_feedback=None)))
        def snapshot():
            if (self.c.root / 'batch-drivers' / 'batch.json').exists():
                seen.append((self.clock.mono, self.journal()))
        self.reply, self.on_pass = reply, snapshot
        monitor = dict(ticking=True, tester_state='idle', restart_pending=True) if monitor is None else monitor
        self.drive(max_seconds=until, monitor_fn=lambda controller, now: dict(monitor))
        return seen

    def test_a_batch_that_runs_nothing_for_the_stall_window_reads_stalled_with_the_exact_recovery(self):
        seen = self.stalled_run()
        early = [record for at, record in seen if at < stall.STALL_SECONDS]
        late = [record for at, record in seen if at > stall.STALL_SECONDS + QUIET_WAIT_MAX_SECONDS and not record['cancel_issued']]
        self.assertTrue(early and late)
        self.assertTrue(all(record['status'] == 'observing' and 'stall' not in record for record in early[1:]))
        record = late[-1]
        self.assertEqual(record['status'], 'stalled')
        self.assertEqual(record['last_error'], NOT_FINISHED)
        plain = record['stall']['plain']
        self.assertTrue(plain.startswith('Stalled: no member has run for '))
        self.assertIn('needs reconcile', plain)
        self.assertIn('between-member restart, which did not happen', plain)
        self.assertEqual(record['stall']['fix']['commands'], [
            'goat.exe demo --installation <receipt> stop',
            'goat.exe demo --installation <receipt> continue --batch-id batch --clear-stop'])
        self.assertIn('Run goat.exe demo --installation <receipt> stop, then', plain)
        self.assertTrue(record['stall']['restart_pending'])

    def test_batch_driver_status_shows_the_stall_and_clears_it_on_progress(self):
        observed = []
        def inspect():
            if self.clock.mono >= 1500 and len(observed) < 1:
                observed.append(status(self.c, 'batch'))
        self.clock.on_sleep = inspect
        seen = self.stalled_run(until=3600, change_at=2400)
        self.assertEqual(observed[0]['status'], 'stalled')
        self.assertIn('continue --batch-id batch --clear-stop', observed[0]['stall']['plain'])
        after = [record for at, record in seen if at > 2400 + 2 * POLL and not record['cancel_issued']]
        self.assertTrue(after)
        self.assertEqual(after[-1]['status'], 'observing')
        self.assertNotIn('stall', after[-1])

    def test_no_stall_while_a_member_runs_the_tester_works_or_the_monitor_is_silent(self):
        for label, kwargs in (('member ongoing', dict(statuses=members('native_completed', 'native_ongoing', 'native_pending'))),
                              ('queue drained', dict(statuses=members('native_completed', 'native_error'))),
                              ('tester running', dict(monitor=dict(ticking=True, tester_state='running'))),
                              ('monitor silent', dict(monitor=dict(ticking=False, tester_state='idle')))):
            with self.subTest(label):
                self.setUp()
                seen = self.stalled_run(**kwargs)
                self.assertTrue(seen)
                self.assertTrue(all(record['status'] != 'stalled' and 'stall' not in record for _, record in seen), label)

    def test_customer_lane_recovery_is_batch_stop_then_batch_continue(self):
        fix = stall.recovery(dict(authority_kind='native_human_control'), 'pilot-1')
        self.assertEqual(fix['commands'], ['goat.exe studio --installation <receipt> batch-stop --job-id pilot-1',
                                           'goat.exe studio --installation <receipt> batch-continue --job-id pilot-1'])


class ResearchStatusStallTests(unittest.TestCase):
    NOW = 1_791_250_000.0

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'state'; self.root.mkdir()
        data = base / 'data'; self.local = data / 'MQL5/Files/GOATStudio'; self.local.mkdir(parents=True)
        (base / 'common').mkdir()
        self.install = dict(terminal_data_root=str(data), common_files_root=str(base / 'common'),
                            terminal_executable='terminal64.exe', ea_version='1.49', ea_sha256='e' * 64)
        self.session = dict(run_id='r', terminal_id='t', account=dict(login='3000082754', server='Darwinex-Demo'),
                            demo_only=True, authority_kind='demo_direct')
        self.job = dict(job_id='g6-r2', status='reconcile_required', launch_intent=dict(attempt_id=ATTEMPT))
        self.monitor = dict(state='ticking', ticking=True, transient=False, heartbeat_age_seconds=0.7, bound=True,
                            loaded=True, owner='agent', tester_state='idle', batch_ongoing=True, restart_pending=True,
                            activation=None, blocker=None)

    def progress(self, ended_minutes_ago, **extra):
        finished = self.NOW - ended_minutes_ago * 60
        from datetime import datetime, timezone
        return dict(members_total=66, members_done=13, members_finished=34, qualifying=13, evidence='native_queue',
                    native_status='native_queued', current_member=None,
                    status_counts=dict(native_completed=13, native_error=21, native_pending=31, native_queued=1),
                    last_member=dict(index=33, number=34, symbol='CADCHF', timeframe='M1', status='error',
                                     finished_utc=datetime.fromtimestamp(finished, timezone.utc).isoformat(timespec='seconds')),
                    pace=dict(eta_wall=self.NOW + 3600)) | extra

    def status(self, progress, monitor=None):
        with patch('studio_research_status.batch_progress', return_value=progress), \
                patch('studio_research_status.monitor_state', return_value=dict(monitor or self.monitor)):
            return research_status(root=self.root, install=self.install, session=self.session, local=self.local,
                                   now=self.NOW, process=dict(pid=55652), jobs=[self.job])

    def test_banker_shape_reads_stalled_not_running(self):
        value = self.status(self.progress(270))           # 4.5 h after member 34 ended
        activity = value['activity']
        self.assertEqual(activity['status'], 'stalled')
        self.assertEqual(activity['stall']['minutes'], 270)
        self.assertTrue(activity['headline'].startswith('Stalled: no member has run for 270 min since member 34 (CADCHF) ended as error'))
        self.assertIn('Run goat.exe demo --installation <receipt> stop, then goat.exe demo --installation <receipt> '
                      'continue --batch-id g6-r2 --clear-stop', activity['headline'])
        self.assertNotIn('Running', activity['headline'])

    def test_a_recent_member_end_or_a_working_tester_still_reads_running(self):
        self.assertEqual(self.status(self.progress(5))['activity']['status'], 'running')
        self.assertEqual(self.status(self.progress(270), dict(self.monitor, tester_state='running'))['activity']['status'], 'running')
        self.assertEqual(self.status(self.progress(270), dict(self.monitor, ticking=False))['activity']['status'], 'running')
        ongoing = self.progress(270, current_member=dict(index=34, number=35, symbol='EURUSD', timeframe='M1'))
        self.assertEqual(self.status(ongoing)['activity']['status'], 'running')
        drained = self.progress(270, status_counts=dict(native_completed=13, native_error=53), native_status='native_error')
        self.assertEqual(self.status(drained)['activity']['status'], 'running')

    def test_driver_section_carries_the_journal_stall(self):
        folder = self.root / 'batch-drivers'; folder.mkdir()
        write_json(folder / 'g6-r2.json', dict(status='stalled', stall=dict(plain='Stalled: ...'), started_wall=self.NOW - 36000,
                                                deadline_wall=self.NOW + 3600, observe=dict(next_wait_seconds=140)))
        value = self.status(self.progress(270))
        self.assertEqual(value['driver']['journal_status'], 'stalled')
        self.assertEqual(value['driver']['stall']['plain'], 'Stalled: ...')
        self.assertEqual(value['driver']['observe']['next_wait_seconds'], 140)


class DriverPriorityTests(unittest.TestCase):
    def test_only_the_driver_thread_drops_one_step_never_the_process_class(self):
        calls = []
        kernel32 = SimpleNamespace(GetCurrentThread=lambda: 'thread',
                                   SetThreadPriority=lambda thread, value: calls.append((thread, value)) or 1)
        self.assertEqual(durable.lower_driver_priority(kernel32), 'thread_below_normal')
        self.assertEqual(calls, [('thread', -1)])
        refused = SimpleNamespace(GetCurrentThread=lambda: 'thread', SetThreadPriority=lambda thread, value: 0)
        self.assertIsNone(durable.lower_driver_priority(refused))

    def test_bootstrap_lowers_the_driver_before_it_drives(self):
        order = []
        with patch('studio_durable_driver.lower_driver_priority', side_effect=lambda: order.append('priority') or 'thread_below_normal'), \
                patch('studio_durable_driver.validate', return_value=(dict(nonce='n' * 32), 60)), \
                patch('demo_agent.main', side_effect=lambda argv: order.append('drive') or 0), \
                tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder) / 'batch-n'
            envelope = Path(str(prefix) + '.launch.json')
            envelope.write_text(json.dumps(dict(schema_version=1, argv=['py', 'demo_agent.py', '--installation', 'x'],
                                                log_path=str(prefix) + '.log', worker_path=str(Path(folder) / 'w.json'),
                                                started=str(prefix) + '.started.json', finished=str(prefix) + '.finished.json',
                                                task_name='fixture')))
            self.assertEqual(durable.bootstrap(envelope), 0)
            log = Path(str(prefix) + '.log').read_text(encoding='utf-8')
        self.assertEqual(order, ['priority', 'drive'])
        self.assertIn('driver CPU priority: thread_below_normal', log)


if __name__ == '__main__':
    unittest.main()
