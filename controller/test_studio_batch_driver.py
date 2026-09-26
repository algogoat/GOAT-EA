"""Offline driver fixtures: actual journals/locks and injected native boundaries."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_native_gate import exclusive_gate
from studio_batch_driver import run, status


class HostDeath(BaseException):
    pass


class Clock:
    def __init__(self):
        self.wall = 1000.0
        self.mono = 0.0
        self.on_sleep = None

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        self.wall += seconds
        self.mono += seconds
        if self.on_sleep:
            self.on_sleep()


class Controller:
    def __init__(self, folder):
        self.root = Path(folder)/'state'
        self.local = Path(folder)/'terminal'/'MQL5'/'Files'/'GOATStudio'
        self.root.mkdir(); self.local.mkdir(parents=True)
        self.install = dict(controller_state_root=str(self.root), terminal_data_root=str(self.local.parent.parent.parent))
        self.terminal, self.run = 'terminal-fixture', 'run-fixture'
        self.session = dict(installation_sha256=sha(self.install), directory_id=self.run,
                            terminal_id=self.terminal, run_id=self.run)
        write_json(self.root/'session.json', self.session)
        write_json(self.local/'active.json', dict(directory_id=self.run, terminal_id=self.terminal,
                                                run_id=self.run, terminal_data_path=self.install['terminal_data_root']))
        configuration = dict(batch_members=[{'symbol': 'EURUSD'}, {'symbol': 'XAUUSD'}])
        self.current = dict(job_id='batch', configuration=configuration, configuration_sha256=sha(configuration), status='pending')
        self.snapshot = dict(owner='agent', generation=3, queue=[self.current])
        package = self.root/'packages'/'batch'; package.mkdir(parents=True)
        write_json(package/'manifest.json', dict(jobs=['one', 'two']))
        self.package_hash = hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
        write_json(package/'preparation.json', dict(configuration_sha256=self.current['configuration_sha256'],
                    files={'manifest.json': self.package_hash}))
        self.starts = self.cancels = self.reconciles = 0
        self.start_error = False
        self.cancel_error = False
        self.finished = False
        self.finish_on_cancel = True
        self.clock = Clock()

    def state(self):
        return self.snapshot

    def job(self, job_id):
        if job_id != 'batch':
            raise ValueError('Unknown job')
        return self.current

    def start(self, job_id, *, expected_generation):
        assert expected_generation == self.snapshot['generation']
        journal = json.loads((self.root/'batch-drivers'/'batch.json').read_text())
        assert journal['start_issued'] is True and journal['attempt_id'] is None
        self.starts += 1
        if self.start_error:
            raise ValueError('native start reply lost')
        self.current.update(status='starting', launch_intent=dict(attempt_id='a'*64,
            package=str(self.root/'packages'/'batch'), package_sha256=self.package_hash))

    def reconcile(self, job_id):
        self.reconciles += 1
        return {'status': 'running'}

    def cancel(self, job_id, *, expected_generation):
        assert expected_generation == self.snapshot['generation']
        journal = json.loads((self.root/'batch-drivers'/'batch.json').read_text())
        assert journal['cancel_issued'] is True
        self.cancels += 1
        if self.cancel_error:
            raise ValueError('cancel transport uncertain')
        self.finished = self.finish_on_cancel
        return {'stopped': False}

    def finish(self, controller, job_id, *, expected_generation):
        assert expected_generation == self.snapshot['generation']
        if not self.finished:
            raise ValueError('Native queue is not finished')
        status = 'cancelled' if self.cancels else 'completed'
        return dict(status=status, result={'attempt_id': 'a'*64})


class BatchDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = Controller(self.temp.name)
        # Package-domain validation has its own full native-batch suite. The
        # driver still hashes actual prepared files/config/session in every test.
        verify = patch('studio_batch_driver._verify_package')
        self.verified = verify.start(); self.addCleanup(verify.stop)

    def drive(self, **kwargs):
        return run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2,
                   clock=self.c.clock, finish_fn=self.c.finish, **kwargs)

    def test_deadline_cancel_once_then_confirmed_stop(self):
        result = self.drive(max_seconds=3)
        self.assertEqual((self.c.starts, self.c.cancels), (1, 1))
        self.assertEqual(result['status'], 'cancelled')
        self.assertTrue(result['stopped'])
        self.assertFalse(result['independent_hard_stop'])
        self.verified.assert_called_once()

    def test_cancel_receipt_or_error_is_not_stop_proof_and_resume_does_not_reissue(self):
        for transport_error in (False, True):
            with self.subTest(transport_error=transport_error):
                self.c.finish_on_cancel = False; self.c.cancel_error = transport_error
                if self.c.starts:
                    result = self.drive(resume=True)
                else:
                    result = self.drive(max_seconds=2)
                self.assertEqual(result['status'], 'stop_unconfirmed')
                self.assertFalse(result['stopped'])
                self.assertEqual(self.c.cancels, 1)
                self.c.clock.wall += 50

    def test_uncertain_start_never_retried_or_adopted_on_resume(self):
        self.c.start_error = True
        result = self.drive(max_seconds=3)
        self.assertEqual(result['status'], 'start_uncertain')
        self.c.current.update(status='running', launch_intent=dict(attempt_id='f'*64))
        result = self.drive(resume=True)
        self.assertEqual((self.c.starts, self.c.cancels), (1, 0))
        self.assertFalse(result['stopped'])
        with self.assertRaisesRegex(ValueError, 'explicit resume'):
            self.drive(max_seconds=3)

    def test_resume_keeps_original_deadline_after_host_death(self):
        def crash():
            raise HostDeath()
        self.c.clock.on_sleep = crash
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=4)
        self.c.clock.on_sleep = None
        self.c.clock.wall += 10
        result = self.drive(resume=True)
        self.assertEqual(result['deadline_wall'], 1004)
        self.assertEqual((self.c.starts, self.c.cancels), (1, 1))
        # The work deadline stays fixed; first cancel gets only bounded readback.
        self.assertTrue(result['stopped'])
        self.assertIsNone(result['last_error'])
        with self.assertRaisesRegex(ValueError, 'original budget'):
            self.drive(resume=True, max_seconds=100)

    def test_revoked_owner_never_cancels(self):
        self.c.clock.on_sleep = lambda: self.c.snapshot.update(owner='human')
        result = self.drive(max_seconds=4)
        self.assertEqual(result['status'], 'ownership_or_binding_changed')
        self.assertEqual(self.c.cancels, 0)

    def test_generation_change_is_not_a_new_grant_for_this_driver(self):
        self.c.clock.on_sleep = lambda: self.c.snapshot.update(generation=4)
        result = self.drive(max_seconds=4)
        self.assertEqual(result['status'], 'ownership_or_binding_changed')
        self.assertEqual(self.c.cancels, 0)

    def test_driver_file_lock_excludes_other_driver(self):
        gate = self.c.root/'batch-driver-gate'; gate.mkdir()
        with exclusive_gate(gate):
            with self.assertRaises(OSError):
                self.drive(max_seconds=1)
        self.assertEqual(self.c.starts, 0)

    def test_invalid_budget_does_not_issue_start(self):
        for value in (None, 0, -1, 86401, 1.5, True, float('nan')):
            with self.assertRaises(ValueError):
                self.drive(max_seconds=value)
        self.assertEqual(self.c.starts, 0)

    def test_natural_completion_does_not_cancel(self):
        self.c.clock.on_sleep = lambda: setattr(self.c, 'finished', True)
        result = self.drive(max_seconds=10)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['stopped'])
        self.assertEqual(self.c.cancels, 0)

    def test_clock_rollback_requests_early_owned_cancel(self):
        def rollback():
            self.c.clock.wall -= 100
            self.c.clock.on_sleep = None
        self.c.clock.on_sleep = rollback
        result = self.drive(max_seconds=10)
        self.assertTrue(result['stopped'])
        record = json.loads((self.c.root/'batch-drivers'/'batch.json').read_text())
        self.assertEqual(record['cancel_reason'], 'clock_rollback')
        self.assertLess(self.c.clock.mono, 10)

    def test_prepared_bytes_or_attempt_drift_never_cancel_foreign_work(self):
        self.c.clock.on_sleep = lambda: self.c.current['launch_intent'].update(attempt_id='f'*64)
        result = self.drive(max_seconds=3)
        self.assertEqual(result['status'], 'ownership_or_binding_changed')
        self.assertEqual(self.c.cancels, 0)

    def test_existing_active_work_refused_before_issuance(self):
        self.c.snapshot['queue'].append(dict(job_id='foreign', status='running'))
        with self.assertRaisesRegex(ValueError, 'Existing native work'):
            self.drive(max_seconds=3)
        self.assertEqual(self.c.starts, 0)

    def test_cancel_error_does_not_claim_stop_or_retry(self):
        self.c.cancel_error = True
        result = self.drive(max_seconds=2)
        self.assertEqual(result['status'], 'stop_unconfirmed')
        self.assertFalse(result['stopped'])
        self.assertEqual(self.c.cancels, 1)
        self.drive(resume=True)
        self.assertEqual(self.c.cancels, 1)

    def test_changed_prepared_file_aborts_without_cancellation(self):
        target = self.c.root/'packages'/'batch'/'manifest.json'
        self.c.clock.on_sleep = lambda: target.write_text('{}')
        result = self.drive(max_seconds=3)
        self.assertEqual(result['status'], 'ownership_or_binding_changed')
        self.assertEqual(self.c.cancels, 0)

    def test_status_is_available_while_driver_holds_exclusive_lock(self):
        observed = []
        def inspect():
            observed.append(status(self.c, 'batch'))
            self.c.finished = True
        self.c.clock.on_sleep = inspect
        self.drive(max_seconds=3)
        self.assertTrue(observed[0]['current_binding_matches'])
        self.assertFalse(observed[0]['stopped'])
        self.assertEqual(observed[0]['observation'], 'retained_driver_record_not_fresh_native_state')

    def test_crash_after_cancel_issuance_never_reissues(self):
        def cancel_crash(job_id, *, expected_generation):
            self.c.cancels += 1
            raise HostDeath()
        self.c.cancel = cancel_crash
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=2)
        self.c.clock.wall += 100
        result = self.drive(resume=True)
        self.assertEqual(self.c.cancels, 1)
        self.assertEqual(result['status'], 'stop_unconfirmed')

    def test_wall_clock_rollback_across_resume_cannot_extend_work(self):
        def die():
            raise HostDeath()
        self.c.clock.on_sleep = die
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=10)
        self.c.clock.on_sleep = None
        self.c.clock.wall -= 500
        result = self.drive(resume=True)
        self.assertEqual(result['deadline_wall'], 1010)
        self.assertEqual((self.c.starts, self.c.cancels), (1, 1))
        self.assertLess(self.c.clock.mono, 10)

    def test_resumed_early_cancellation_keeps_its_short_observation_limit(self):
        def crash_cancel(job_id, *, expected_generation):
            self.c.cancels += 1
            raise HostDeath()
        self.c.cancel = crash_cancel
        def rollback():
            self.c.clock.wall -= 100
            self.c.clock.on_sleep = None
        self.c.clock.on_sleep = rollback
        with self.assertRaises(HostDeath):
            self.drive(max_seconds=1000)
        # Wall clock is corrected, but the earlier cancellation remains pending.
        self.c.clock.wall = 1002
        before = self.c.clock.mono
        result = self.drive(resume=True)
        self.assertEqual(result['status'], 'stop_unconfirmed')
        self.assertLessEqual(self.c.clock.mono-before, 2)
        self.assertEqual(self.c.cancels, 1)


if __name__ == '__main__':
    unittest.main()
