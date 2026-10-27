"""A start in flight is never demoted by a concurrent status read (T3, 2026-10-03).

Replay of the beta.17 fresh-tester P1: Start-Batch pilot-2 and its Continue
successor pilot-2-r1 were both refused before MT5 was touched with "Retained
starting attempt required". The tester's agent polled batch-status every 3 s.
The first poll landed 0.4 s after the start recorded its launch intent and
before the start installed its controls; batch-status reconciled, found no
native evidence (nothing was dispatched yet) and demoted the job from
'starting' to 'reconcile_required', so the start's own fail-closed install
check refused it. r2 and r3 succeeded only because their first poll hit the
held native gate (WinError 32) instead.

Real controller store and prepared package; no MT5 process.
"""
import hashlib
import json
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from studio_batch import prepare_batch, resume_batch, batch_status, gate_busy
from studio_bridge import pump_for
from studio_config_start import phase
from studio_launch_intent import record_intent
from studio_native_gate import exclusive_gate
import studio_open_activation
from studio_open_activation import _install_controls
from studio_reconcile import reconcile
from studio_retire_unactivated import retire


IDLE = ({'runtime': dict(tester_state='idle', batch_ongoing=False, account_demo=True)}, {})


class InstallReached(Exception):
    """Raised just past the status check: the start would go on to install controls."""


class RetainedStartingRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        c = self.c = self.fixture.bound(); self.fixture.grant(c)
        source = self.fixture.root / 'Template.set'
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        spec = dict(schema_version=1, export=self.fixture.exports,
                    members=[dict(set_path=str(source), tester=self.fixture.tester | {'Symbol': symbol})
                             for symbol in ('GBPJPY.customer', 'USDJPY.customer', 'EURUSD.customer')])
        self.plan = self.fixture.root / 'plan.json'; self.plan.write_text(json.dumps(spec), encoding='utf-8')
        prepare_batch(c, 'pilot-2', self.plan)
        runtime = patch.object(c, 'runtime', return_value=IDLE)
        runtime.start(); self.addCleanup(runtime.stop)

    # -- the config start's own steps, in its order -------------------------------------------

    def arm_intent(self, job_id):
        """queue.reserve + record_intent, exactly as studio_config_start.start does."""
        c = self.c
        package = c.root / 'packages' / job_id
        (c.root / 'batch-drivers').mkdir(exist_ok=True)
        (c.root / 'batch-drivers' / (job_id + '.json')).write_text(json.dumps(dict(
            schema_version=2, binding=dict(job_id=job_id), deadline_wall=time.time() + 600,
            status='start_issued', start_issued=True, attempt_id=None, cancel_issued=False, stopped=False)))
        job = c.job(job_id)
        digest = hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest()
        c.submit('queue.reserve', dict(job_id=job_id, configuration_sha256=job['configuration_sha256'],
                                       package_sha256=digest), job_id + '-reserve')
        state = c.state()
        intent = record_intent(c.store, c.terminal, c.run, job_id, package, actor='agent',
                               revision=state['revision'], generation=state['generation'])
        self.assertEqual(c.job(job_id)['status'], 'starting')
        return intent

    def install(self, job_id):
        """phase 'prepared', then the real _install_controls status/authority checks."""
        c = self.c
        generation = c.state()['generation']
        phase(c, job_id, generation, None, 'prepared', startup_sha256='0' * 64,
              process_baseline={}, account=dict(c.session['account']))
        with patch.object(studio_open_activation, 'validate_launch_material', side_effect=InstallReached):
            with self.assertRaises(InstallReached):
                _install_controls(c.state(), c.job(job_id), restart=True, **c.native_args(),
                                  evidence=c.root / 'attempts' / 'unused', process_baseline={},
                                  validate_ownership=lambda *args: None)

    def concurrent_readers(self, job_id):
        """What ran against T3 inside the window: batch-status polls, serve, a reconcile."""
        c = self.c
        before = c.state()['revision']
        results = [batch_status(c, job_id) for _ in range(3)]
        pump_for(c.bridge, 0)  # the resident serve process
        direct = c.reconcile(job_id)
        self.assertEqual([r['status'] for r in results], ['starting'] * 3)
        self.assertTrue(direct['start_in_progress']); self.assertFalse(direct['changed'])
        job = c.job(job_id)
        self.assertEqual(job['status'], 'starting')
        self.assertEqual(c.state()['revision'], before)            # nothing committed at all
        self.assertNotIn('native_observation', job)
        self.assertNotIn('native_evidence_log', job)
        self.assertFalse((c.local / 'native-gate' / 'permit.json').exists())

    # -- regressions ------------------------------------------------------------------------------

    def test_status_poll_between_launch_intent_and_install_never_demotes_the_start(self):
        # pilot-2: intent 21:51:55.44Z, batch-status reconcile 55.83Z, install refused 56.06Z.
        self.arm_intent('pilot-2')
        self.concurrent_readers('pilot-2')
        self.install('pilot-2')  # reaches past 'Retained starting attempt required'

    def test_status_poll_after_prepared_phase_never_demotes_the_start(self):
        self.arm_intent('pilot-2')
        phase(self.c, 'pilot-2', self.c.state()['generation'], None, 'prepared', startup_sha256='0' * 64,
              process_baseline={}, account=dict(self.c.session['account']))
        self.concurrent_readers('pilot-2')
        with patch.object(studio_open_activation, 'validate_launch_material', side_effect=InstallReached):
            with self.assertRaises(InstallReached):
                _install_controls(self.c.state(), self.c.job('pilot-2'), restart=True, **self.c.native_args(),
                                  evidence=self.c.root / 'attempts' / 'unused', process_baseline={},
                                  validate_ownership=lambda *args: None)

    def test_first_start_after_normal_reopen_and_its_continue_successor_both_reach_install(self):
        # The exact T3 sequence: start, settle, Continue -> r1, start again, each polled at +3 s.
        # The MT5 reopen (plain launch + profile switch) leaves no controller state behind, so
        # both starts depend only on the poll; before the fix both were refused.
        self.arm_intent('pilot-2'); self.concurrent_readers('pilot-2'); self.install('pilot-2')
        settled = retire(self.c, 'pilot-2', reason='driver_start_refused_before_activation', settle_journal=False)
        self.assertEqual(settled['status'], 'cancelled')
        resume_batch(self.c, 'pilot-2', 'pilot-2-r1')
        self.arm_intent('pilot-2-r1'); self.concurrent_readers('pilot-2-r1'); self.install('pilot-2-r1')

    def test_retained_check_still_refuses_a_job_that_really_left_starting(self):
        # Fail-closed is unchanged: a job that is not 'starting' is still refused.
        intent = self.arm_intent('pilot-2')
        retire(self.c, 'pilot-2', reason='operator', settle_journal=False)
        self.assertEqual(self.c.job('pilot-2')['status'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'Retained starting attempt required'):
            _install_controls(self.c.state(), self.c.job('pilot-2'), restart=True, **self.c.native_args(),
                              evidence=self.c.root / 'attempts' / intent['attempt_id'], process_baseline={},
                              validate_ownership=lambda *args: None)

    def test_unexpected_native_evidence_before_dispatch_still_reconciles(self):
        # Only "nothing dispatched and nothing observed" is a start in flight. Native evidence
        # without an issued dispatch is foreign/unexpected and still demotes, fail-closed.
        intent = self.arm_intent('pilot-2')
        job = self.c.job('pilot-2')
        native = dict(status='native_queued', members=[], observed_at='2026-10-03T21:51:55Z',
                      studio_source=dict(terminal_id=self.c.terminal, run_id=self.c.run, job_id='pilot-2',
                                         configuration_sha256=job['configuration_sha256']))
        with patch('studio_reconcile.observe', return_value=native):
            result = reconcile(self.c.store, self.c.terminal, self.c.run, 'pilot-2', intent['attempt_id'],
                               revision=self.c.state()['revision'])
        self.assertTrue(result['changed'])
        self.assertEqual(self.c.job('pilot-2')['status'], 'reconcile_required')

    def test_issued_dispatch_with_missing_evidence_still_reconciles(self):
        # After the arm/start request is issued, observation proceeds exactly as before.
        intent = self.arm_intent('pilot-2'); attempt = intent['attempt_id']
        request = dict(request_id=attempt, job_id='pilot-2')
        body = json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n'
        (self.c.local / 'native-gate' / ('issued-' + attempt + '.json')).write_text(json.dumps(dict(
            request_sha256=hashlib.sha256(body.encode()).hexdigest(), request=request)))
        result = reconcile(self.c.store, self.c.terminal, self.c.run, 'pilot-2', attempt,
                           revision=self.c.state()['revision'])
        self.assertTrue(result['changed'])
        self.assertEqual(self.c.job('pilot-2')['status'], 'reconcile_required')

    # -- WinError 32: a status read while the start holds the native gate -----------------------

    def test_status_read_while_the_start_holds_the_gate_answers_without_error_or_change(self):
        # r2/r3: the first poll raised "[WinError 32] ... being used by another process".
        self.arm_intent('pilot-2')
        issued = self.c.local / 'native-gate'
        before = self.c.state()['revision']
        # Make the read reach the gate: an issued dispatch means a real observation is due.
        attempt = self.c.job('pilot-2')['launch_intent']['attempt_id']
        request = dict(request_id=attempt, job_id='pilot-2')
        body = json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n'
        (issued / ('issued-' + attempt + '.json')).write_text(json.dumps(dict(
            request_sha256=hashlib.sha256(body.encode()).hexdigest(), request=request)))
        (issued / ('result-' + attempt + '.json')).write_text(json.dumps(dict(
            request_id=attempt, request_sha256=hashlib.sha256(body.encode()).hexdigest(),
            status='RESTART_ARMED_RECONCILE')))
        with patch('studio_batch.GATE_BUSY_WAIT_SECONDS', 0.3):
            with exclusive_gate(issued):  # the driver inside _install_controls / publish
                result = batch_status(self.c, 'pilot-2')
        self.assertEqual(result['status'], 'starting')
        self.assertEqual(result['observation_deferred']['reason'], 'native_gate_busy')
        self.assertEqual(self.c.state()['revision'], before)
        self.assertEqual(self.c.job('pilot-2')['status'], 'starting')
        # Once the gate is free the same read observes normally.
        self.assertNotIn('observation_deferred', batch_status(self.c, 'pilot-2'))

    def test_sharing_violation_is_retried_then_observed(self):
        self.arm_intent('pilot-2')
        calls = []
        real = self.c.reconcile
        def flaky(job_id):
            calls.append(job_id)
            if len(calls) == 1:
                error = PermissionError(13, 'The process cannot access the file because it is being used by another process')
                error.winerror = 32
                raise error
            return real(job_id)
        with patch.object(self.c, 'reconcile', side_effect=flaky):
            result = batch_status(self.c, 'pilot-2')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('observation_deferred', result)
        self.assertEqual(result['status'], 'starting')

    def test_other_os_errors_are_not_swallowed(self):
        self.arm_intent('pilot-2')
        with patch.object(self.c, 'reconcile', side_effect=FileNotFoundError('manifest missing')):
            with self.assertRaises(FileNotFoundError):
                batch_status(self.c, 'pilot-2')

    def test_gate_busy_classification(self):
        sharing = PermissionError(13, 'in use'); sharing.winerror = 32
        lock = PermissionError(13, 'locked'); lock.winerror = 33
        denied = PermissionError(13, 'denied'); denied.winerror = 5
        self.assertTrue(gate_busy(sharing)); self.assertTrue(gate_busy(lock))
        self.assertTrue(gate_busy(BlockingIOError(11, 'would block')))
        self.assertFalse(gate_busy(denied)); self.assertFalse(gate_busy(FileNotFoundError(2, 'missing')))


if __name__ == '__main__':
    unittest.main()
