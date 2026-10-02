"""The bounded driver keeps supervising while a batch pauses; its journal is never poisoned.

Driver fixtures from test_studio_batch_driver with the pause step injected: the
step's own native rules are covered by test_studio_batch_pause.
"""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_pause as pause
from studio_batch_driver import run, status
import test_studio_batch_driver as fixtures

ATTEMPT = 'a' * 64


class HostDeath(BaseException):
    pass


class DriverPauseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BatchDriverTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.c, self.disk = self.fixture.c, self.fixture.disk
        self.steps = []
        self.step_result = 'pausing'
        self.finish_on_step = None
        stepper = patch('studio_batch_pause.step', side_effect=self.fake_step); stepper.start()
        self.addCleanup(stepper.stop)

    def write_pause(self, **extra):
        record = dict(schema_version=1, job_id='batch', pause_id='p' * 32, attempt_id=ATTEMPT,
                      configuration_sha256=self.c.current['configuration_sha256'], generation=3,
                      state='pausing', phase='waiting_safe_point', mode='safe_point', cancels=[], history=[]) | extra
        (self.c.root / 'batch-pauses').mkdir(exist_ok=True)
        write_json(self.c.root / 'batch-pauses' / 'batch.json', record)
        return record

    def fake_step(self, controller, job_id, *, now, monitor, escalation=None, finish_error=None):
        self.steps.append(dict(now=now, escalation=escalation, monitor=monitor))
        record = pause.load(controller.root, job_id)
        if self.step_result == 'pause_failed':
            record.update(state='pause_failed', failure=dict(code='cancel_refused', message='m', fix='f'))
            write_json(pause.path(controller.root, job_id), record)
        if self.finish_on_step is not None and len(self.steps) >= self.finish_on_step:
            self.c.finished = True
        return record

    def drive(self, **kwargs):
        return run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2, clock=self.c.clock,
                   finish_fn=self.c.finish, monitor_fn=lambda controller, now: dict(ticking=True), **kwargs)

    @staticmethod
    def fake_complete(controller, job_id, *, now):
        record = pause.load(controller.root, job_id)
        record.update(state='paused', phase='paused', resume_token='t' * 64)
        write_json(pause.path(controller.root, job_id), record)
        return record

    def completes(self):
        """complete() reads the real finished job; the fixture's finish is synthetic."""
        return patch('studio_batch_pause.complete', side_effect=self.fake_complete)

    def die_on_first_sleep(self):
        self.c.clock.on_sleep = lambda: (_ for _ in ()).throw(HostDeath())
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=86400)
        self.c.clock.on_sleep = None

    def test_pause_never_sets_cancel_issued_keeps_disk_guard_and_records_paused(self):
        def request_pause_then_low_disk():
            if not (self.c.root / 'batch-pauses' / 'batch.json').exists():
                self.write_pause()
            else:
                self.disk.return_value = SimpleNamespace(free=1)
        self.c.clock.on_sleep = request_pause_then_low_disk
        self.finish_on_step = 3
        with self.completes():
            result = self.drive(max_seconds=86400)
        self.assertEqual((result['status'], result['stopped'], result['pause_id']), ('paused', True, 'p' * 32))
        self.assertFalse(result['cancel_issued'])
        self.assertEqual(self.c.cancels, 0)
        self.assertEqual(len(self.steps), 3)
        # The disk guard kept observing during the pause and escalated it.
        self.assertEqual([step['escalation'] for step in self.steps], [None, 'disk_low', 'disk_low'])
        self.assertEqual(result['disk_observation']['reason'], 'disk_low')

    def test_poisoned_stop_unconfirmed_journal_is_adopted_and_supervised_to_paused(self):
        self.c.finish_on_cancel = False; self.c.cancel_error = True
        first = self.drive(max_seconds=2)
        self.assertEqual((first['status'], first['cancel_issued'], first['stopped']), ('stop_unconfirmed', True, False))
        # Without a pause a resumed driver still returns stop_unconfirmed at once.
        self.c.clock.wall += 600
        self.assertEqual(self.drive(resume=True)['status'], 'stop_unconfirmed')
        self.write_pause(adopted_stop=True)
        self.finish_on_step = 4
        with self.completes():
            result = self.drive(resume=True, pause_seconds=3600)
        self.assertEqual((result['status'], result['stopped']), ('paused', True))
        self.assertEqual(self.c.cancels, 1)
        self.assertEqual(len(self.steps), 4)
        self.assertEqual(self.steps[0]['escalation'], 'deadline')

    def test_supervisor_budget_ends_pausing_without_poisoning_and_can_resume(self):
        self.die_on_first_sleep()
        self.write_pause()
        result = self.drive(resume=True, pause_seconds=5)
        self.assertEqual((result['status'], result['stopped'], result['pause_supervision']), ('pausing', False, 'budget_exhausted'))
        self.assertFalse(result['cancel_issued'])
        self.finish_on_step = len(self.steps) + 1
        with self.completes():
            again = self.drive(resume=True, pause_seconds=5)
        self.assertEqual(again['status'], 'paused')
        self.assertEqual(self.c.cancels, 0)

    def test_failed_pause_hands_back_to_normal_supervision(self):
        self.c.clock.on_sleep = lambda: self.write_pause() if not self.steps else setattr(self.c, 'finished', True)
        self.step_result = 'pause_failed'
        result = self.drive(max_seconds=86400)
        self.assertEqual((result['status'], result['stopped']), ('completed', True))
        self.assertEqual(result['pause_failure']['code'], 'cancel_refused')
        self.assertEqual(self.c.cancels, 0)
        self.assertEqual(len(self.steps), 1)

    def test_pause_supervisor_requires_a_pausing_record(self):
        self.die_on_first_sleep()
        with self.assertRaisesRegex(ValueError, 'requires a pausing batch'):
            self.drive(resume=True, pause_seconds=5)
        with self.assertRaisesRegex(ValueError, 'pause supervisor'):
            self.drive(max_seconds=10, pause_seconds=5)
        self.assertEqual(self.steps, [])

    def test_host_death_mid_pause_resumes_the_same_pause(self):
        def die_after_pause():
            if not (self.c.root / 'batch-pauses' / 'batch.json').exists():
                self.write_pause()
            else:
                raise HostDeath()
        self.c.clock.on_sleep = die_after_pause
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=86400)
        journal = json.loads((self.c.root / 'batch-drivers' / 'batch.json').read_text())
        self.assertEqual((journal['status'], journal['cancel_issued']), ('pausing', False))
        self.c.clock.on_sleep = None
        self.finish_on_step = len(self.steps) + 1
        with self.completes():
            result = self.drive(resume=True, pause_seconds=60)
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(status(self.c, 'batch')['pause_id'], 'p' * 32)

    def test_stopped_journal_completes_an_interrupted_pause_record(self):
        self.write_pause()
        self.c.finished = True
        with patch('studio_batch_pause.complete', side_effect=self.fake_complete) as complete:
            result = self.drive(max_seconds=10)
        complete.assert_called_once()
        self.assertTrue(result['stopped'])
        self.write_pause()
        self.c.current['status'] = 'cancelled'
        with patch('studio_batch_pause.complete', side_effect=self.fake_complete) as complete:
            self.drive(resume=True)
        complete.assert_called_once()


if __name__ == '__main__':
    unittest.main()
