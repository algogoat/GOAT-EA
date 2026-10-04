"""GOAT-EA#120 review fixes for the customer (native_human_control) /config start.

Each class covers one review item:
- RecoveryGuidanceTests: a start that stops after arming says, from the retained
  phase, whether MT5 was left open, closing or closed, and the plain next step.
- PreCloseRecheckTests: positions/orders/account are proved again right before the close.
- ConsentBindingTests: consent is bound to the selected MT5 process and expires.
- RawStartRefusalTests: raw `start` is refused on the customer lane.
- AdvisoryTesterProbeTests: a non-English MT5 tester caption no longer refuses
  the SDK check; a recognised running caption still does.
- NoEdgeEvidenceTests / relative evidence folder (LOW items).
"""
import inspect
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import studio_config_start as start
from studio_config_start import (RESTART_CONSENT_SECONDS, consent_record, refuse_raw_start,
                                 require_restart_consent, restart_recovery)
import test_studio_tester_config_start as customer
import test_studio_monitor_probe as probe_tests


def phases(c):
    return [row['phase'] for row in c.job('batch')['restart_intent']['history']]


class PreCloseRecheckTests(customer.CustomerConfigStartTests):
    """MEDIUM 3: the SDK proof runs again after the arm, immediately before close_issued."""

    def failing_second_sdk(self, message):
        calls = []
        def sdk(c, expected=None):
            calls.append(expected)
            self.events.append('sdk')
            if len(calls) == 2:
                raise ValueError(message)
            return dict(process=dict(self.identity), demo=True, connected=True, algo_trading=False,
                        positions=0, orders=0, account_matches=True, tester_state='idle')
        self.mocks['sdk_idle_demo'].side_effect = sdk
        return calls

    def test_position_opened_after_arm_refuses_before_close(self):
        calls = self.failing_second_sdk(start.SDK_REFUSAL)
        with self.assertRaisesRegex(ValueError, 'zero trades required'):
            self.run_start()
        self.assertEqual(self.events, ['sdk', 'reserve', 'install', 'arm', 'sdk'])
        self.assertEqual(calls, [self.identity, self.identity])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()
        self.assertEqual(phases(self.c), ['prepared', 'controls_installed'])
        recovery = restart_recovery(self.c.job('batch'))
        self.assertEqual(recovery['mt5'], 'open_may_be_armed')
        self.assertIn('MT5 was not closed', recovery['plain'])

    def test_account_switched_after_arm_refuses_before_close(self):
        self.failing_second_sdk('SDK-confirmed same idle demo, Algo OFF and zero trades required: '
                                'Native terminal/account differs from the installation')
        with self.assertRaisesRegex(ValueError, 'account differs'):
            self.run_start()
        self.process.close.assert_not_called()

    def test_recheck_follows_the_arm_and_precedes_close_issued(self):
        seen = []
        def sdk(c, expected=None):
            seen.append(c.job('batch').get('restart_intent', {}).get('phase'))
            self.events.append('sdk')
            return dict(process=dict(self.identity))
        self.mocks['sdk_idle_demo'].side_effect = sdk
        self.run_start()
        self.assertEqual(seen, [None, 'controls_installed'])

    def test_demo_lane_does_not_need_the_customer_sdk_recheck(self):
        self.c.session['authority_kind'] = 'demo_direct'
        self.run_start()
        self.assertNotIn('sdk', self.events)


class ConsentBindingTests(customer.CustomerConfigStartTests):
    """MEDIUM 4: the yes is for one start, on the exact MT5 process, for a short time."""

    def write(self, **consent):
        journal = customer.consent_journal(process=self.identity)
        journal['mt5_restart_consent'].update(consent)
        (self.c.root/'batch-drivers/batch.json').write_text(json.dumps(journal))

    def assert_refused_before_effects(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.run_start()
        self.assertEqual(self.events, [])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_expired_consent_refuses_before_any_effect(self):
        old = time.time() - RESTART_CONSENT_SECONDS - 5
        self.write(recorded_wall=old, expires_wall=old + RESTART_CONSENT_SECONDS)
        self.assert_refused_before_effects('consent expired')

    def test_overlong_or_missing_expiry_refuses(self):
        now = time.time()
        for consent in (dict(expires_wall=now + RESTART_CONSENT_SECONDS * 10), dict(expires_wall=None),
                        dict(recorded_wall='now'), dict(recorded_wall=now + 60, expires_wall=now + 120)):
            with self.subTest(consent=consent):
                self.write(**consent)
                self.assert_refused_before_effects('consent expired or invalid')

    def test_consent_for_another_process_refuses_before_any_effect(self):
        for other in (dict(self.identity, pid=12), dict(self.identity, created_utc='2026-09-30T00:00:00Z'),
                      dict(self.identity, executable='C:/other/terminal64.exe'), None):
            with self.subTest(other=other):
                self.write(process=other)
                self.assert_refused_before_effects('another MT5 process')

    def test_consent_for_another_job_refuses(self):
        self.write(job_id='another-batch')
        self.assert_refused_before_effects('MT5 restart consent required')

    def test_pre_close_check_binds_the_process_but_never_strands_an_armed_mt5_on_expiry(self):
        consent = customer.consent_journal(process=self.identity)
        (self.c.root/'batch-drivers/batch.json').write_text(json.dumps(consent))
        later = consent['mt5_restart_consent']['expires_wall'] + 30
        self.assertEqual(require_restart_consent(self.c, 'batch', self.identity, now=later, expiry=False)['job_id'], 'batch')
        with self.assertRaisesRegex(ValueError, 'expired'):
            require_restart_consent(self.c, 'batch', self.identity, now=later)
        with self.assertRaisesRegex(ValueError, 'another MT5 process'):
            require_restart_consent(self.c, 'batch', dict(self.identity, pid=99), now=later, expiry=False)

    def test_consent_record_binds_the_running_selected_process_and_an_expiry(self):
        (self.c.root/'packages/batch/studio-plan.json').write_text(json.dumps(self.plan))
        self.mocks['inspect_processes'].return_value = dict(self.baseline, research=dict(self.identity, extra='x'))
        record = consent_record(self.c, 'batch', 1000.0)
        self.assertEqual(record['process'], self.identity)
        self.assertEqual((record['recorded_wall'], record['expires_wall']), (1000.0, 1000.0 + RESTART_CONSENT_SECONDS))
        self.assertEqual(record['job_id'], 'batch')
        self.mocks['inspect_processes'].return_value = dict(self.baseline, research=None)
        with self.assertRaisesRegex(ValueError, 'needs the selected MT5 running'):
            consent_record(self.c, 'batch', 1000.0)


class DriverConsentAndRecoveryTests(customer.CustomerDriverRouteTests):
    """The driver records the bound consent and, after arming, a plain recovery."""

    def test_driver_consent_is_bound_and_expires(self):
        self.c.finished = True
        result = self.drive(max_seconds=60, restart_consent=True)
        consent = result['mt5_restart_consent']
        self.assertEqual(consent['process'], customer.IDENTITY)
        self.assertEqual(consent['expires_wall'] - consent['recorded_wall'], RESTART_CONSENT_SECONDS)

    def test_no_running_mt5_refuses_consent_before_any_journal(self):
        self.processes.stop()
        stopped = patch('studio_config_start.inspect_processes', return_value=dict(research=None, protected=None))
        stopped.start(); self.addCleanup(stopped.stop)
        with self.assertRaisesRegex(ValueError, 'needs the selected MT5 running'):
            self.drive(max_seconds=60, restart_consent=True)
        self.assertFalse((self.c.root/'batch-drivers/batch.json').exists())
        self.assertEqual((self.config_starts, self.c.starts), (0, 0))

    def stopped_after(self, reached, message):
        def config_start(job_id, *, expected_generation, on_attempt):
            self.c.start(job_id, expected_generation=expected_generation)
            on_attempt(self.c.current['launch_intent'])
            self.c.current['restart_intent'] = dict(phase=reached, history=[])
            raise ValueError(message)
        self.c.start_config = config_start
        return self.drive(max_seconds=60, restart_consent=True)

    def test_every_post_arm_failure_records_where_mt5_was_left(self):
        cases = (('controls_installed', 'Native arming unconfirmed; no close or launch issued', 'open_may_be_armed'),
                 ('controls_installed', 'Selected process changed before close', 'open_may_be_armed'),
                 ('close_issued', 'Normal close unconfirmed; no repeat close or launch', 'closing_or_closed'),
                 ('close_issued', 'Pending human control request during config start', 'closing_or_closed'),
                 ('research_exited', 'Startup bytes changed after close', 'closed_not_reopened'),
                 ('launch_issued', 'MT5 launch failed', 'reopen_uncertain'))
        for reached, message, mt5 in cases:
            with self.subTest(reached=reached, message=message):
                customer.CustomerDriverRouteTests.setUp(self)  # a fresh controller per case
                result = self.stopped_after(reached, message)
                self.assertEqual(result['status'], 'start_uncertain')
                self.assertEqual(result['attempt_id'], 'a'*64)
                self.assertEqual(result['recovery']['mt5'], mt5)
                self.assertIn('Do not run Start-Batch', result['recovery']['next_safe_action'])
                journal = json.loads((self.c.root/'batch-drivers/batch.json').read_text())
                self.assertEqual(journal['recovery'], result['recovery'])
                from studio_batch_driver import status
                self.assertEqual(status(self.c, 'batch')['recovery']['mt5'], mt5)

    def test_refusal_before_arming_says_mt5_was_not_touched(self):
        def refused(job_id, *, expected_generation, on_attempt):
            raise ValueError('Runtime policy mismatch: terminal_trade_allowed')
        self.c.start_config = refused
        result = self.drive(max_seconds=60, restart_consent=True)
        self.assertEqual(result['recovery']['mt5'], 'not_touched')


class RecoveryGuidanceTests(unittest.TestCase):
    """HIGH 1: one plain row per retained phase, never telling the agent to start again."""

    def test_each_phase_has_plain_mt5_state_and_safe_action(self):
        expected = {None: 'not_touched', 'prepared': 'not_touched', 'controls_installed': 'open_may_be_armed',
                    'close_issued': 'closing_or_closed', 'research_exited': 'closed_not_reopened',
                    'launch_issued': 'reopen_uncertain', 'process_started_unverified': 'reopened_unverified'}
        for reached, mt5 in expected.items():
            with self.subTest(reached=reached):
                job = dict(restart_intent=dict(phase=reached)) if reached else dict()
                guidance = restart_recovery(job)
                self.assertEqual(guidance['mt5'], mt5)
                self.assertTrue(guidance['plain'] and guidance['next_safe_action'])
                if mt5 in ('closing_or_closed', 'closed_not_reopened', 'reopen_uncertain'):
                    self.assertIn('open MT5 normally', guidance['next_safe_action'])
                    self.assertIn('support report', guidance['next_safe_action'])
                if mt5 == 'open_may_be_armed':
                    self.assertIn('do not close or restart it', guidance['next_safe_action'])

    def test_unreadable_job_is_unknown_never_not_touched(self):
        self.assertEqual(restart_recovery(None)['mt5'], 'unknown')

    def test_guide_has_a_row_for_every_post_arm_error(self):
        guide = (Path(__file__).parent/'AGENT-START-HERE.md').read_text(encoding='utf-8')
        source = inspect.getsource(start.start)
        for message in ('Native arming refused', 'Native arming unconfirmed', 'Selected process changed before close',
                        'Normal close unconfirmed', 'Startup bytes changed after close'):
            with self.subTest(message=message):
                self.assertIn(message, source)
                self.assertIn(message, guide)
        for phrase in ('MT5 was not closed', 'MT5 closed for the start', '`recovery`',
                       'MT5 restart consent expired or invalid', 'Raw start is not available on this lane'):
            self.assertIn(phrase, guide)
        self.assertNotIn("orphan-recovery-apply','--review-id'", guide)


class RawStartRefusalTests(unittest.TestCase):
    """MEDIUM 5: raw start can only produce 0 exports on the customer lane."""

    def test_customer_lane_refuses_and_points_to_run_batch(self):
        with self.assertRaisesRegex(ValueError, 'Raw start is not available.*--mt5-restart-consent'):
            refuse_raw_start(dict(authority_kind='native_human_control'))
        for kind in ('demo_direct', 'research_continuation', None):
            self.assertIsNone(refuse_raw_start(dict(authority_kind=kind)))

    def test_cli_start_refuses_before_controller_start(self):
        import goat_studio
        source = inspect.getsource(goat_studio.main)
        branch = source[source.index("elif args.operation=='start':"):]
        self.assertLess(branch.index('refuse_raw_start(controller.session)'), branch.index('controller.start(args.job_id)'))
        self.assertEqual(goat_studio.OPERATION_CONTRACTS['start']['refused_lanes'], ['native_human_control'])

    def test_prepare_batch_points_customer_to_run_batch(self):
        from studio_batch import _start_next_action
        customer_lane = SimpleNamespace(session=dict(authority_kind='native_human_control'))
        self.assertIn('run-batch --job-id pilot-1', _start_next_action(customer_lane, 'pilot-1'))
        self.assertIn('--mt5-restart-consent', _start_next_action(customer_lane, 'pilot-1'))
        self.assertNotIn('use start', _start_next_action(customer_lane, 'pilot-1'))
        demo = SimpleNamespace(session=dict(authority_kind='demo_direct'))
        self.assertIn('use start --job-id', _start_next_action(demo, 'pilot-1'))

    def test_real_customer_prepare_reply_names_run_batch(self):
        from test_studio_batch import NativeBatchTests
        batch = NativeBatchTests(); batch.setUp(); self.addCleanup(batch.tearDown)
        self.assertEqual(batch.controller.session['authority_kind'], 'native_human_control')
        self.assertIn('--mt5-restart-consent', batch.prepare('pilot-1')['next_action'])


class AdvisoryTesterProbeTests(probe_tests.MonitorProbeTests):
    """MEDIUM 6: tester idleness from the EA sample; caption read advisory for any MT5 language."""

    def advisory(self, tester, *, raises=None):
        c, terminal, account, sdk, processes = self.fixture()
        from studio_monitor_probe import inspect_idle_demo
        state = Mock(side_effect=raises) if raises else Mock(return_value=tester)
        with patch.dict('sys.modules', {'MetaTrader5': sdk}), patch('studio_monitor_probe.process_binding', return_value={}), \
                patch('studio_monitor_probe.inspect_processes', side_effect=[processes, processes]), \
                patch('studio_monitor_probe.tester_state', state):
            return inspect_idle_demo(c, tester='advisory'), sdk

    def test_unrecognised_language_caption_defers_to_the_ea(self):
        result, sdk = self.advisory('unknown')
        self.assertEqual((result['tester_state'], result['tester_source']), ('unknown', 'ea_runtime'))
        self.assertEqual((result['positions'], result['orders'], result['algo_trading']), (0, 0, False))
        sdk.shutdown.assert_called_once()

    def test_unreadable_tester_frame_defers_to_the_ea(self):
        result, _ = self.advisory(None, raises=ValueError('Native tester state unavailable; no close performed'))
        self.assertEqual(result['tester_state'], 'unknown')

    def test_recognised_running_caption_still_refuses(self):
        with self.assertRaisesRegex(ValueError, 'Strategy Tester is running'):
            self.advisory('running')

    def test_recognised_idle_caption_is_reported_from_the_window(self):
        result, _ = self.advisory('idle')
        self.assertEqual((result['tester_state'], result['tester_source']), ('idle', 'window_caption'))

    def test_repair_paths_keep_requiring_a_recognised_idle_caption(self):
        c, terminal, account, sdk, processes = self.fixture()
        with self.assertRaisesRegex(ValueError, 'positively observed idle'):
            self.run_probe(c, sdk, [processes, processes], 'unknown')
        from studio_monitor_probe import inspect_idle_demo
        with self.assertRaisesRegex(ValueError, 'Explicit tester observation mode'):
            inspect_idle_demo(c, tester='guess')

    def test_config_start_sdk_check_uses_advisory_mode_and_one_refusal_prefix(self):
        c = SimpleNamespace()
        native = dict(process='p', demo=True, connected=True, algo_trading=False, positions=0, orders=0,
                      account_matches=True, tester_state='unknown')
        with patch('studio_monitor_probe.inspect_idle_demo', return_value=native) as probe:
            self.assertEqual(start.sdk_idle_demo(c, 'p'), native)
        probe.assert_called_once_with(c, tester='advisory')
        for bad in (dict(positions=1), dict(orders=2), dict(algo_trading=True), dict(demo=False), dict(tester_state='running')):
            with self.subTest(bad=bad), patch('studio_monitor_probe.inspect_idle_demo', return_value=native | bad):
                with self.assertRaisesRegex(ValueError, '^SDK-confirmed same idle demo, Algo OFF and zero trades required'):
                    start.sdk_idle_demo(c, 'p')
        with patch('studio_monitor_probe.inspect_idle_demo', side_effect=ValueError('Native terminal/account differs from the installation')):
            with self.assertRaisesRegex(ValueError, '^SDK-confirmed .*: Native terminal/account differs'):
                start.sdk_idle_demo(c, 'p')
        with patch('studio_monitor_probe.inspect_idle_demo', return_value=native):
            with self.assertRaisesRegex(ValueError, 'differs from the selected process'):
                start.sdk_idle_demo(c, 'other')


class NoEdgeEvidenceTests(unittest.TestCase):
    """LOW: no-edge members are results, and evidence never stores the absolute log folder."""
    RUN = 'GOAT\\R6b6f51629797'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)/'Users'/'someone'/'data'
        logs = self.data/'MQL5/Logs'; logs.mkdir(parents=True)
        (logs/'20261002.log').write_bytes('x\tAborting exports for GOAT\\R6b6f51629797\r\n'.encode('utf-16'))
        self.package = Path(self.temp.name)/'package'; self.package.mkdir()
        (self.package/'manifest.json').write_text(json.dumps(dict(native_run_relative=self.RUN)))
        self.controller = SimpleNamespace(install=dict(terminal_data_root=str(self.data)))
        self.job = dict(launch_intent=dict(package=str(self.package)))

    def native(self, *statuses):
        return dict(status='native_error', members=[dict(status=s) for s in statuses])

    def test_all_errored_members_no_edge_is_a_result_not_a_failure(self):
        from studio_native_diagnostics import for_job
        evidence = for_job(self.controller, self.job, self.native('native_completed', 'native_error'), [1])
        self.assertEqual(evidence['status'], 'no_edge_only')
        self.assertEqual((evidence['members_no_edge'], evidence['members_failed']), ([1], []))
        self.assertIn('not a failure', evidence['note'])

    def test_mixed_batch_names_only_real_failures(self):
        from studio_native_diagnostics import for_job
        evidence = for_job(self.controller, self.job, self.native('native_error', 'native_error'), [1])
        self.assertEqual(evidence['status'], 'observed')
        self.assertEqual((evidence['members_no_edge'], evidence['members_failed']), ([1], [0]))

    def test_without_no_edge_members_evidence_is_unchanged(self):
        from studio_native_diagnostics import for_job
        evidence = for_job(self.controller, self.job, self.native('native_error'))
        self.assertEqual(evidence['status'], 'observed')
        self.assertNotIn('members_no_edge', evidence)

    def test_folder_is_relative_and_never_holds_the_user_path(self):
        from studio_native_diagnostics import native_error_evidence
        for root in (self.data, Path(self.temp.name)/'missing'):
            evidence = native_error_evidence(root, self.RUN)
            self.assertEqual(evidence['folder'], 'MQL5\\Logs')
            self.assertNotIn('someone', json.dumps(evidence))


# These classes reuse fixtures; run only their own tests, not the inherited ones again.
def _own_tests_only(*classes):
    for owner in classes:
        for name in dir(owner):
            if name.startswith('test') and name not in owner.__dict__:
                setattr(owner, name, None)


_own_tests_only(PreCloseRecheckTests, ConsentBindingTests, DriverConsentAndRecoveryTests, AdvisoryTesterProbeTests)


if __name__ == '__main__':
    unittest.main()
