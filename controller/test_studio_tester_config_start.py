"""Customer (native_human_control) batches start through the report-capable /config route.

MT5 writes the tester Report= main/forward XML only for a /config startup launch.
An in-place Start click wrote none, so every beta.16 tester batch ended
native_error with 0 exports (QA 2026-10-02). These fixtures prove the customer
lane now chooses config start, keeps every fail-closed gate, requires the user's
MT5 restart consent, and surfaces the EA's native_error reason.
"""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from campaign_ledger import sha
from studio_bridge import write_json
import studio_config_start as start
from studio_config_start import RESTART_CONSENT_SCOPE
import test_studio_batch_driver as driver_fixtures
import test_studio_config_start as config_fixtures
from studio_batch_driver import run


IDENTITY = dict(pid=11, executable='terminal64.exe', created_utc='2026-09-29T00:00:00Z')


def consent_journal(job_id='batch', process=None, **overrides):
    import time
    now = time.time()
    record = dict(deadline_wall=now+600, binding=dict(job_id=job_id),
                  mt5_restart_consent=dict(granted=True, scope=RESTART_CONSENT_SCOPE, recorded_wall=now,
                                           expires_wall=now+600, job_id=job_id, process=dict(process or IDENTITY),
                                           source='run-batch --mt5-restart-consent'))
    record.update(overrides)
    return record


class CustomerConfigStartTests(config_fixtures.ConfigStartTests):
    """Every direct-demo ordering/refusal test, rerun on the customer lane, plus its own gates."""

    def setUp(self):
        super().setUp()
        self.c.session['authority_kind'] = 'native_human_control'
        (self.c.root/'batch-drivers/batch.json').write_text(json.dumps(consent_journal(process=self.identity)))
        def sdk(c, expected=None):
            self.events.append('sdk')
            native = dict(process=dict(self.identity), demo=True, connected=True, algo_trading=False,
                          positions=0, orders=0, account_matches=True, tester_state='idle')
            if expected is not None and native['process'] != expected:
                raise ValueError('SDK-observed MT5 differs from the selected process; no close or launch issued')
            return native
        self.mocks['sdk_idle_demo'] = self.stack.enter_context(patch.object(start, 'sdk_idle_demo', side_effect=sdk))

    def test_one_arm_close_config_launch_and_retained_phases(self):
        # Customer lane: broker-proved idle demo before reserve, then arm, close, /config launch.
        result = self.run_start()
        self.assertEqual(self.events, ['sdk', 'reserve', 'install', 'arm', 'sdk', 'close', 'launch'])
        self.assertEqual(result['status'], 'config_process_started_unverified')
        self.assertFalse(result['native_running_verified'])
        phases = [row['phase'] for row in self.c.job('batch')['restart_intent']['history']]
        self.assertEqual(phases, ['prepared', 'controls_installed', 'close_issued', 'research_exited',
                                  'launch_issued', 'process_started_unverified'])
        self.process.close.assert_called_once_with(self.identity)
        with self.assertRaisesRegex(ValueError, 'new pending'):
            self.run_start()
        self.process.start.assert_called_once()

    def test_no_restart_consent_never_reserves_closes_or_launches(self):
        for journal in (consent_journal(mt5_restart_consent=None),
                        consent_journal(mt5_restart_consent=dict(granted=False, scope=RESTART_CONSENT_SCOPE)),
                        consent_journal(mt5_restart_consent=dict(granted=True, scope='something else')),
                        consent_journal(binding=dict(job_id='another-batch'))):
            with self.subTest(journal=journal):
                (self.c.root/'batch-drivers/batch.json').write_text(json.dumps(journal))
                with self.assertRaisesRegex(ValueError, 'MT5 restart consent required'):
                    self.run_start()
                self.assertEqual(self.events, [])
                self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_algo_trading_on_refuses_before_any_effect(self):
        for refusal in (ValueError('Runtime policy mismatch: terminal_trade_allowed'),):
            self.c.runtime.side_effect = refusal
            with self.assertRaisesRegex(ValueError, 'terminal_trade_allowed'):
                self.run_start()
        self.mocks['sdk_idle_demo'].side_effect = ValueError('SDK-confirmed same idle demo, Algo OFF and zero trades required')
        self.c.runtime.side_effect = None
        with self.assertRaisesRegex(ValueError, 'Algo OFF'):
            self.run_start()
        self.assertEqual(self.events, [])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_wrong_account_or_live_account_refuses_before_any_effect(self):
        for message in ('Runtime account mismatch', 'Runtime policy mismatch: account_demo'):
            with self.subTest(message=message):
                self.c.runtime.side_effect = ValueError(message)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_start()
                self.assertEqual(self.events, [])
        self.c.runtime.side_effect = None
        self.mocks['sdk_idle_demo'].side_effect = ValueError('Native terminal/account differs from the installation')
        with self.assertRaisesRegex(ValueError, 'account differs'):
            self.run_start()
        self.assertEqual(self.events, [])
        self.process.close.assert_not_called()

    def test_extra_terminal_refuses_before_any_effect(self):
        self.mocks['inspect_processes'].side_effect = ValueError('Unmapped terminal process requires ownership inspection')
        with self.assertRaisesRegex(ValueError, 'Unmapped terminal'):
            self.run_start()
        self.assertEqual(self.events, [])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_sdk_observing_another_process_refuses_before_reserve(self):
        def other(c, expected=None):
            raise ValueError('SDK-observed MT5 differs from the selected process; no close or launch issued')
        self.mocks['sdk_idle_demo'].side_effect = other
        with self.assertRaisesRegex(ValueError, 'differs from the selected process'):
            self.run_start()
        self.assertEqual(self.events, [])

    def test_customer_lane_never_uses_the_demo_only_unissued_resume(self):
        with self.assertRaisesRegex(ValueError, 'direct demo lane only'):
            start.start(self.c, 'batch', expected_generation=2, process=self.process, resume_unissued=True)
        self.assertEqual(self.events, [])

    def test_other_lanes_still_refuse_config_start(self):
        for kind in (None, 'research_continuation'):
            with self.subTest(kind=kind):
                self.c.session['authority_kind'] = kind
                with self.assertRaisesRegex(ValueError, 'qualified for the direct demo and native human-control'):
                    self.run_start()
        self.assertEqual(self.events, [])

    def test_historical_customer_package_requires_new_identity(self):
        self.plan['research_binding'].pop('report_location_bridge')
        (self.package/'studio-plan.json').write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError, 'new batch ID'):
            self.run_start()
        self.assertEqual(self.events, [])


class CustomerDriverRouteTests(unittest.TestCase):
    """run-batch on the customer lane: consent first, then the /config route, never the click."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.c = driver_fixtures.Controller(self.temp.name)
        self.c.session['authority_kind'] = 'native_human_control'
        write_json(self.c.root/'session.json', self.c.session)
        self.c.bridge = SimpleNamespace(root=self.c.local/self.c.run)
        write_json(self.c.root/'packages/batch/studio-plan.json', dict(research_binding=dict(
            research_profile='GOAT-Studio-'+'a'*32, report_location_bridge='installation_to_data_v1',
            startup_monitor=dict(expert='GOAT.ex5', preset='GOAT Studio Agent.set', preset_sha256='b'*64))))
        self.config_starts = 0
        def config_start(job_id, *, expected_generation, on_attempt):
            journal = json.loads((self.c.root/'batch-drivers/batch.json').read_text())
            self.assertEqual(journal['mt5_restart_consent']['scope'], RESTART_CONSENT_SCOPE)
            self.assertEqual(journal['start_route'], 'config_restart')
            self.assertEqual(journal['mt5_restart_consent']['process'], IDENTITY)
            self.config_starts += 1
            self.c.start(job_id, expected_generation=expected_generation)
            on_attempt(self.c.current['launch_intent'])
        self.c.start_config = config_start
        for target in ('studio_batch_driver._verify_package',):
            patcher = patch(target); patcher.start(); self.addCleanup(patcher.stop)
        disk = patch('studio_batch_driver.shutil.disk_usage', return_value=SimpleNamespace(free=100*1024**3))
        disk.start(); self.addCleanup(disk.stop)
        self.processes = patch('studio_config_start.inspect_processes', return_value=dict(research=dict(IDENTITY), protected=None))
        self.processes.start(); self.addCleanup(self.processes.stop)

    def drive(self, **kwargs):
        return run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2,
                   clock=self.c.clock, finish_fn=self.c.finish, **kwargs)

    def test_regression_customer_batch_start_chooses_config_start_not_the_in_place_click(self):
        self.c.finished = True
        result = self.drive(max_seconds=60, restart_consent=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.config_starts, 1)
        self.assertEqual(self.c.starts, 1)  # counted once, inside config start only
        self.assertEqual(result['start_route'], 'config_restart')
        self.assertTrue(result['mt5_restart_consent']['granted'])

    def test_customer_start_without_consent_writes_nothing_and_dispatches_nothing(self):
        with self.assertRaisesRegex(ValueError, 'MT5 restart consent required'):
            self.drive(max_seconds=60)
        self.assertFalse((self.c.root/'batch-drivers/batch.json').exists())
        self.assertEqual((self.config_starts, self.c.starts), (0, 0))
        self.assertEqual(self.c.current['status'], 'pending')

    def test_consent_is_never_accepted_for_resume(self):
        with self.assertRaisesRegex(ValueError, 'Resume never starts'):
            self.drive(resume=True, restart_consent=True)
        with self.assertRaisesRegex(ValueError, 'explicit boolean'):
            self.drive(max_seconds=60, restart_consent='yes')

    def test_historical_customer_package_refuses_before_journal(self):
        write_json(self.c.root/'packages/batch/studio-plan.json', dict(research_binding=dict()))
        with self.assertRaisesRegex(ValueError, 'prepared without the report-capable MT5 start'):
            self.drive(max_seconds=60, restart_consent=True)
        self.assertFalse((self.c.root/'batch-drivers/batch.json').exists())
        self.assertEqual((self.config_starts, self.c.starts), (0, 0))

    def test_refused_config_start_is_start_uncertain_without_attempt_and_retryable(self):
        def refused(job_id, *, expected_generation, on_attempt):
            self.config_starts += 1
            raise ValueError('Runtime policy mismatch: terminal_trade_allowed')
        self.c.start_config = refused
        first = self.drive(max_seconds=60, restart_consent=True)
        self.assertEqual((first['status'], first['attempt_id']), ('start_uncertain', None))
        self.assertIn('terminal_trade_allowed', first['last_error'])
        self.assertEqual(self.c.starts, 0)

    def test_demo_and_legacy_lanes_keep_their_routes_without_consent(self):
        self.c.finished = True
        for kind, expected in (('demo_direct', 'config_restart'), (None, 'in_place_start')):
            with self.subTest(kind=kind):
                folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
                c = driver_fixtures.Controller(folder.name); c.finished = True
                c.bridge = SimpleNamespace(root=c.local/c.run)
                if kind:
                    c.session['authority_kind'] = kind; write_json(c.root/'session.json', c.session)
                c.start_config = lambda job_id, *, expected_generation, on_attempt: (
                    c.start(job_id, expected_generation=expected_generation), on_attempt(c.current['launch_intent']))
                result = run(c, 'batch', max_seconds=60, poll_seconds=1, cancel_grace_seconds=2,
                             clock=c.clock, finish_fn=c.finish)
                self.assertEqual(result['start_route'], expected)
                self.assertIsNone(result['mt5_restart_consent'])
                self.assertEqual(result['status'], 'completed')


class CustomerBindingTests(unittest.TestCase):
    """The customer binding gains the /config material once onboarding staged its profile."""

    def setUp(self):
        from test_studio_batch import NativeBatchTests
        self.batch = NativeBatchTests(); self.batch.setUp(); self.addCleanup(self.batch.tearDown)
        self.c = self.batch.controller

    def stage_profile(self):
        write_json(self.c.root/'monitor-profile.json',
                   dict(profile_name='GOAT-Studio-'+self.c.run.removeprefix('session-')))

    def test_customer_session_is_native_human_control(self):
        self.assertEqual(self.c.session['authority_kind'], 'native_human_control')

    def test_without_profile_binding_is_unchanged(self):
        binding = self.c.binding()
        for key in ('research_profile', 'report_location_bridge', 'startup_monitor'):
            self.assertNotIn(key, binding)

    def test_staged_profile_adds_report_capable_route_and_new_package_records_it(self):
        self.stage_profile()
        binding = self.c.binding()
        self.assertEqual(binding['report_location_bridge'], 'installation_to_data_v1')
        self.assertTrue(binding['research_profile'].startswith('GOAT-Studio-'))
        preset = Path(self.c.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        self.assertEqual(binding['startup_monitor']['preset_sha256'], hashlib.sha256(preset.read_bytes()).hexdigest())
        result = self.batch.prepare('config-batch')
        plan = json.loads((Path(result['package'])/'studio-plan.json').read_text())
        self.assertEqual(plan['research_binding']['research_profile'], binding['research_profile'])
        from studio_batch import batch_status
        self.assertEqual(batch_status(self.c, 'config-batch')['member_count'], 2)

    def test_historical_customer_package_still_verifies_for_status_and_finish(self):
        from studio_batch import batch_status, _verify_package
        self.batch.prepare('old-batch')
        self.stage_profile()
        self.assertIn('research_profile', self.c.binding())
        _verify_package(self.c, self.c.job('old-batch'))
        self.assertEqual(batch_status(self.c, 'old-batch')['status'], 'pending')

    def test_tolerance_never_relaxes_other_binding_fields(self):
        from studio_batch import _verify_package
        self.batch.prepare('old-batch')
        self.stage_profile()
        drifted = dict(self.c.binding(), ea_sha256='0'*64)
        with patch.object(self.c, 'binding', return_value=drifted):
            with self.assertRaisesRegex(ValueError, 'installation or plan identity changed'):
                _verify_package(self.c, self.c.job('old-batch'))

    def test_tolerance_is_limited_to_the_customer_lane(self):
        from studio_batch import _verify_package
        self.batch.prepare('old-batch')
        self.stage_profile()
        with_route = self.c.binding()
        session = dict(self.c.session, authority_kind='research_continuation')
        with patch.object(self.c, 'session', session), patch.object(self.c, 'binding', return_value=with_route):
            with self.assertRaisesRegex(ValueError, 'installation or plan identity changed'):
                _verify_package(self.c, self.c.job('old-batch'))
    def test_damaged_staged_preset_refuses_binding(self):
        self.stage_profile()
        preset = Path(self.c.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        preset.write_bytes('Mode_Operation=0\r\n'.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'passive monitor preset'):
            self.c.binding()


class NativeErrorEvidenceTests(unittest.TestCase):
    RUN = 'GOAT\\R6b6f51629797'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)/'data'
        self.logs = self.data/'MQL5/Logs'; self.logs.mkdir(parents=True)

    def write_log(self, name, lines):
        (self.logs/name).write_bytes(('\r\n'.join(lines)+'\r\n').encode('utf-16'))

    def test_deinit_reason_for_the_exact_run_is_quoted(self):
        from studio_native_diagnostics import native_error_evidence
        self.write_log('20261002.log', [
            'QK\t0\t22:44:20.100\tGOAT V1.49 (EURUSD,M1)\tStudio monitor heartbeat',
            'QK\t0\t22:44:25.000\tGOAT V1.49 (EURUSD,M1)\tXML Migration incomplete: root=GOAT\\R6b6f51629797\\reports files=0; '
            'paired main/forward reports required. Aborting exports.',
            'QK\t0\t22:44:26.000\tGOAT V1.49 (EURUSD,M1)\tXML Migration incomplete: root=GOAT\\R000000000000\\reports files=0'])
        evidence = native_error_evidence(self.data, self.RUN)
        self.assertEqual(evidence['status'], 'observed')
        self.assertEqual(len(evidence['lines']), 1)
        self.assertIn('Aborting exports', evidence['lines'][0]['line'])
        self.assertEqual(evidence['lines'][0]['log'], '20261002.log')

    def test_absence_is_not_found_and_bad_identity_is_unavailable(self):
        from studio_native_diagnostics import native_error_evidence
        self.write_log('20261002.log', ['QK\t0\t22:44:20.100\tGOAT\tall good'])
        self.assertEqual(native_error_evidence(self.data, self.RUN)['status'], 'not_found')
        self.assertEqual(native_error_evidence(self.data, '..\\escape')['status'], 'unavailable')
        self.assertEqual(native_error_evidence(Path(self.temp.name)/'missing', self.RUN)['status'], 'unavailable')

    def test_for_job_only_reports_native_error(self):
        from studio_native_diagnostics import for_job
        package = Path(self.temp.name)/'package'; package.mkdir()
        write_json(package/'manifest.json', dict(native_run_relative=self.RUN))
        self.write_log('20261002.log', ['x\tAborting exports for GOAT\\R6b6f51629797'])
        controller = SimpleNamespace(install=dict(terminal_data_root=str(self.data)))
        job = dict(launch_intent=dict(package=str(package)))
        self.assertIsNone(for_job(controller, job, dict(status='native_completed')))
        self.assertEqual(for_job(controller, job, dict(status='native_error'))['status'], 'observed')
        self.assertEqual(for_job(controller, dict(), dict(status='native_error'))['status'], 'unavailable')

    def test_reused_finish_returns_its_result_path(self):
        from studio_finish import finish
        job = dict(job_id='batch', status='failed', completion=dict(status='failed',
                   native_error_evidence=dict(status='observed')), completion_path='C:\\state\\result.json')
        controller = SimpleNamespace(job=lambda job_id: job, state=lambda: dict(generation=1))
        result = finish(controller, 'batch')
        self.assertEqual(result['result_path'], 'C:\\state\\result.json')
        self.assertTrue(result['reused'])
        self.assertEqual(result['native_error_evidence']['status'], 'observed')


if __name__ == '__main__':
    unittest.main()
