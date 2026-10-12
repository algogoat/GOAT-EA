"""Fix B (Claude-Mac, goatai#2350 6118571536): monitor-launch reopens the exact chart GOAT observed healthy.

Fixture-only: no installed terminal is touched, launched or closed, and the MetaTrader5 adapter is never imported for
real (a fake answers every SDK readback). After a person approves DLL imports, MT5 saves a non-zero expertmode on the
monitor chart. GOAT never decodes it: when onboarding-status itself observes the monitor healthy (native_monitor
complete, SDK Algo Trading OFF, demo, the linked login) it records the SHA-256 of the exact saved chart bytes, bound to
the installation, terminal, account, session and chart file. monitor-launch accepts only those bytes; anything else
refuses exactly as before. Also: the shared Open Lab protected-login list and the demo check on monitor-launch,
monitor-repair and close-terminal, and the monitor-repair attempt ID length checked before any close.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_agent_setup import close_terminal
import studio_agent_setup
import studio_demo_deploy
from studio_monitor_repair import repair
from studio_onboarding import (HEALTHY_CHART_ARCHIVE, HEALTHY_CHART_RECORD, MONITOR_PROFILE_REFUSAL, NOT_DEMO_REFUSAL,
                               OPEN_LAB_LOGINS, PROTECTED_ACCOUNT_REFUSAL, monitor_launch, onboarding_status,
                               verify_monitor_profile)
from studio_refusal import Refusal
import test_studio_onboarding as onboarding

EXPERIMENT_LOGINS = {'Experiment 01': '3000109268', 'Experiment 02': '3000109427', 'Experiment 03': '3000110706'}


class FakeMT5:
    """The MetaTrader5 adapter as broker_proof and inspect_idle_demo read it. Never a trading call."""
    ACCOUNT_TRADE_MODE_DEMO = 0
    __version__ = 'fixture'

    def __init__(self, controller, *, login='123456', server='Customer-Demo', trade_mode=0, algo=False, connected=True):
        self.c, self.login, self.server, self.trade_mode, self.algo, self.connected = controller, login, server, trade_mode, algo, connected
        self.initialized = 0

    def initialize(self, path, timeout=0):
        self.initialized += 1
        return True

    def shutdown(self): pass

    def terminal_info(self):
        return SimpleNamespace(path=str(Path(self.c.install['terminal_executable']).parent), data_path=self.c.install['terminal_data_root'],
                               connected=self.connected, trade_allowed=self.algo, build=5200)

    def account_info(self):
        return SimpleNamespace(login=int(self.login), server=self.server, trade_mode=self.trade_mode)

    def positions_get(self): return []
    def orders_get(self): return []


class PreservedChartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = onboarding.OnboardingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # The real adapter is never reachable from these tests: a missed fake fails instead of attaching to an MT5.
        guard = patch.dict(sys.modules, {'MetaTrader5': None}); guard.start(); self.addCleanup(guard.stop)
        self.c = self.fixture.c
        self.start = self.fixture.start
        prepared = onboarding.monitor_prepare(self.c, 'EURUSD')
        self.chart = Path(prepared['profile_path'])/'chart01.chr'
        self.prepared = self.chart.read_text(encoding='utf-16')
        self.record = self.c.root/HEALTHY_CHART_RECORD
        self.session_path = self.c.root/'session.json'
        self.session_raw = self.session_path.read_bytes()

    # ---- helpers

    def approve_dll(self, mode='4'):
        """What MT5 saves after the person approved DLL imports on the monitor chart: a non-zero expertmode."""
        self.chart.write_text(self.prepared.replace('expertmode=0', 'expertmode='+mode), encoding='utf-16')
        return self.chart.read_bytes()

    def status(self, mt5=None, **observation):
        self.fixture.observe(**observation)
        return onboarding_status(self.c, mt5=mt5 or FakeMT5(self.c))

    def recorded(self):
        result = self.status()['monitor_chart_record']
        self.assertEqual(result['status'], 'recorded', result)
        return json.loads(self.record.read_text())

    def refused(self, attempt, code=MONITOR_PROFILE_REFUSAL):
        before = self.chart.read_bytes()
        with self.assertRaises(Refusal) as caught:
            monitor_launch(self.c, attempt)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.start.assert_not_called()
        self.assertEqual(self.chart.read_bytes(), before, 'GOAT never writes the saved chart')
        return caught.exception

    def set_account(self, login='123456', server='Customer-Demo', **session_changes):
        session = json.loads(self.session_raw)
        session['account'] = dict(login=login, server=server)
        session.update(session_changes)
        self.session_path.write_text(json.dumps(session))
        self.fixture.common_ini.write_text('[Common]\nLogin='+login+'\nServer='+server+'\n[Experts]\nEnabled=0\n')

    def retired_reasons(self):
        journal = self.c.root/HEALTHY_CHART_ARCHIVE/'retired.jsonl'
        return [json.loads(line)['reason'] for line in journal.read_text().splitlines()] if journal.exists() else []

    # ---- record and accept

    def test_byte_identical_observed_healthy_chart_is_accepted_by_monitor_launch(self):
        raw = self.approve_dll()
        record = self.recorded()
        self.assertEqual(record['chart_sha256'], __import__('hashlib').sha256(raw).hexdigest())
        self.assertEqual(record['binding']['chart_path'], str(self.chart))
        self.assertEqual(record['binding']['account'], dict(login='123456', server='Customer-Demo'))
        self.assertEqual(record['binding']['terminal_data_root'], self.c.install['terminal_data_root'])
        self.assertEqual(record['binding']['terminal_executable'], self.c.install['terminal_executable'])
        self.assertEqual(record['observed']['sdk'], dict(login='123456', server='Customer-Demo', demo=True, connected=True,
                                                         algo_trading=False, build=5200))
        self.assertFalse(record['permissions_changed'])
        # A second healthy observation of the same bytes needs no new SDK readback.
        again = FakeMT5(self.c)
        self.assertEqual(self.status(again)['monitor_chart_record']['status'], 'current')
        self.assertEqual(again.initialized, 0)
        launch = monitor_launch(self.c, 'self-restore-1')
        self.assertEqual(launch['status'], 'process_started_unverified')
        self.assertEqual(launch['observed_healthy_chart']['chart_sha256'], record['chart_sha256'])
        self.assertEqual(launch['saved_chart_sha256'], record['chart_sha256'])
        startup = Path(launch['startup_config']).read_bytes().decode('utf-16')
        self.assertIn('[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n', startup, 'Algo Trading and live trading stay forced off')
        self.assertEqual(self.chart.read_bytes(), raw, 'no permission is written or changed')
        self.start.assert_called_once()

    def test_one_changed_byte_is_refused_as_today(self):
        self.approve_dll(); self.recorded()
        self.chart.write_text(self.chart.read_text(encoding='utf-16').replace('scale=8', 'scale=7'), encoding='utf-16')
        refusal = self.refused('changed-byte')
        self.assertEqual(refusal.fields['failed_checks'], ['permissions'])
        self.assertEqual(refusal.fields['observed'], {'expertmode': '4', 'required_expertmode': '0'})
        self.assertEqual(refusal.fields['observed_healthy_chart']['status'], 'differs')

    def test_a_different_permission_value_is_refused(self):
        self.approve_dll('4'); self.recorded()
        for mode in ('5', '6', '36'):
            with self.subTest(mode=mode):
                self.approve_dll(mode)
                refusal = self.refused('other-permission-'+mode)
                self.assertEqual(refusal.fields['failed_check'], 'permissions')
                self.assertEqual(refusal.fields['observed']['expertmode'], mode)

    def test_a_new_healthy_observation_supersedes_and_archives_the_previous_record(self):
        self.approve_dll('4'); first = self.recorded()
        self.approve_dll('6'); second = self.recorded()
        self.assertNotEqual(first['chart_sha256'], second['chart_sha256'])
        self.assertEqual(self.retired_reasons(), ['superseded'])
        self.assertTrue(any(p.suffix == '.json' for p in (self.c.root/HEALTHY_CHART_ARCHIVE).iterdir()))
        self.assertEqual(monitor_launch(self.c, 'after-supersede')['observed_healthy_chart']['chart_sha256'], second['chart_sha256'])

    # ---- invalidation

    def test_an_account_change_retires_the_binding(self):
        for changed in (dict(login='654321'), dict(server='Other-Demo')):
            with self.subTest(changed=changed):
                self.set_account()
                self.approve_dll(); self.recorded()
                self.set_account(**changed)
                refusal = self.refused('account-'+'-'.join(changed))
                self.assertEqual(refusal.fields['failed_check'], 'permissions')
                self.assertFalse(self.record.exists())
                self.assertEqual(self.retired_reasons()[-1], 'account')
                # Back on the original account the retired record never becomes valid again.
                self.set_account()
                self.assertEqual(self.refused('account-back-'+'-'.join(changed)).fields['observed_healthy_chart']['status'], 'none')

    def test_a_terminal_path_change_retires_the_binding(self):
        self.approve_dll(); self.recorded()
        original = self.c.install['terminal_executable']
        other = Path(original).parent.parent/'other program'/'terminal64.exe'
        other.parent.mkdir(); other.write_bytes(b'mt5')
        self.c.install['terminal_executable'] = str(other)
        with self.assertRaisesRegex(ValueError, 'Installation changed'):
            monitor_launch(self.c, 'other-terminal')
        self.assertFalse(self.record.exists())
        self.assertEqual(self.retired_reasons(), ['terminal'])
        self.c.install['terminal_executable'] = original
        self.assertEqual(self.refused('terminal-back').fields['observed_healthy_chart']['status'], 'none')

    def test_an_ea_update_of_the_same_installation_keeps_the_binding(self):
        self.approve_dll(); record = self.recorded()
        self.fixture.update_ea()
        c = self.fixture.reopened()
        launch = monitor_launch(c, 'after-update')
        self.assertEqual(launch['observed_healthy_chart']['chart_sha256'], record['chart_sha256'])

    # ---- no record unless every health fact holds

    def test_no_record_without_a_fresh_native_monitor(self):
        self.approve_dll()
        sdk = FakeMT5(self.c)
        result = self.status(sdk, observed_terminal_utc='2000.01.01 00:00:00')
        self.assertEqual(result['monitor_chart_record']['status'], 'not_recorded')
        self.assertEqual(sdk.initialized, 0, 'no SDK readback for a monitor that is not healthy')
        self.assertFalse(self.record.exists())
        self.refused('no-record')

    def test_no_record_when_the_sdk_reads_algo_trading_on(self):
        self.approve_dll()
        result = self.status(FakeMT5(self.c, algo=True))['monitor_chart_record']
        self.assertEqual((result['status'], result['reason']), ('not_recorded', 'algo_trading_on'))
        self.assertFalse(self.record.exists())

    def test_no_record_when_the_sdk_reads_a_non_demo_account(self):
        self.approve_dll()
        for mode in (1, 2):
            result = self.status(FakeMT5(self.c, trade_mode=mode))['monitor_chart_record']
            self.assertEqual(result['status'], 'not_recorded')
        self.assertIn('real-money', result['detail'])
        self.assertFalse(self.record.exists())

    def test_no_record_when_the_sdk_reads_another_login_or_server(self):
        self.approve_dll()
        for sdk in (FakeMT5(self.c, login='999999'), FakeMT5(self.c, server='Other-Demo')):
            result = self.status(sdk)['monitor_chart_record']
            self.assertEqual(result['status'], 'not_recorded')
            self.assertIn('different account', result['detail'])
        self.assertFalse(self.record.exists())

    def test_a_human_reopen_observation_alone_never_records(self):
        raw = self.approve_dll()
        # The observational check human-reopen paths use accepts the saved permissions but writes nothing.
        receipt = json.loads((self.c.root/'monitor-profile.json').read_text())
        verify_monitor_profile(self.c, receipt, observed_human_reopen=True)
        self.assertFalse(self.record.exists())
        # A human-opened MT5 (not monitor-launch's process) without fresh healthy runtime feedback: still no record.
        sdk = FakeMT5(self.c)
        result = onboarding_status(self.c, mt5=sdk)
        self.assertEqual(result['monitor_chart_record']['status'], 'not_recorded')
        self.assertEqual(sdk.initialized, 0)
        self.assertFalse(self.record.exists())
        self.refused('human-only')
        self.assertEqual(self.chart.read_bytes(), raw)

    # ---- protected logins and demo, matching close-terminal

    def test_the_shared_list_holds_every_open_lab_login(self):
        self.assertEqual(OPEN_LAB_LOGINS, frozenset(('3000109268', '3000109269', '3000109270', '3000109271', '3000109272',
                                                     '3000109273', '3000109427', '3000109421', '3000110705', '3000110706')))
        self.assertIs(studio_agent_setup.PROTECTED_ACCOUNTS, OPEN_LAB_LOGINS)
        self.assertIs(studio_demo_deploy.PROTECTED_ACCOUNTS, OPEN_LAB_LOGINS)

    def test_open_lab_logins_are_refused_by_monitor_launch_monitor_repair_and_close_terminal(self):
        process = SimpleNamespace(close=lambda identity: self.fail('closed MT5'), inspect=lambda: self.fail('inspected MT5'))
        for experiment, login in EXPERIMENT_LOGINS.items():
            with self.subTest(experiment=experiment):
                self.set_account(login=login, server='Darwinex-Demo')
                self.refused('protected-'+login, PROTECTED_ACCOUNT_REFUSAL)
                with patch('studio_monitor_repair.WindowsSeedProcess', return_value=process), \
                     patch('studio_monitor_repair.inspect_idle_demo', side_effect=AssertionError('probed MT5')), \
                     self.assertRaises(Refusal) as caught:
                    repair(self.c, 'protected-'+login)
                self.assertEqual(caught.exception.code, PROTECTED_ACCOUNT_REFUSAL)
                with self.assertRaises(Refusal) as caught:
                    close_terminal(self.c, 'protected-'+login, process=process, inspect=lambda c: self.fail('probed MT5'))
                self.assertEqual(caught.exception.code, PROTECTED_ACCOUNT_REFUSAL)
                self.assertFalse((self.c.root/'monitor-repairs'/('protected-'+login+'.json')).exists())
                self.assertFalse((self.c.root/'terminal-closes'/('protected-'+login+'.json')).exists())
        self.start.assert_not_called()

    def test_a_non_demo_binding_or_report_is_refused_by_monitor_launch_and_monitor_repair(self):
        process = SimpleNamespace(close=lambda identity: self.fail('closed MT5'), inspect=lambda: None)
        self.set_account(demo_only=False)
        self.refused('not-demo-binding', NOT_DEMO_REFUSAL)
        with patch('studio_monitor_repair.WindowsSeedProcess', return_value=process), self.assertRaises(Refusal) as caught:
            repair(self.c, 'not-demo-binding')
        self.assertEqual(caught.exception.code, NOT_DEMO_REFUSAL)
        # The EA's last runtime report for this exact account says it is not a demo.
        self.set_account()
        self.fixture.observe()
        runtime = json.loads((self.c.local/'ui-observation.json').read_text())['runtime']
        self.fixture.observe(runtime=dict(runtime, account_demo=False))
        self.refused('not-demo-report', NOT_DEMO_REFUSAL)
        # A report for another account says nothing about this one.
        self.fixture.observe(runtime=dict(runtime, account_demo=False, account_login='777777'))
        self.assertEqual(monitor_launch(self.c, 'other-account-report')['status'], 'process_started_unverified')

    def test_monitor_repair_reads_the_broker_trade_mode_before_any_close(self):
        identity = dict(pid=44, executable=self.c.install['terminal_executable'], created_utc='2026-09-01T00:00:00Z')
        closed = []
        process = SimpleNamespace(close=closed.append, inspect=lambda: identity)
        (Path(self.c.install['common_files_root'])/'GOAT').mkdir(exist_ok=True)
        for mode in (1, 2):
            with self.subTest(trade_mode=mode), \
                 patch.dict(sys.modules, {'MetaTrader5': FakeMT5(self.c, trade_mode=mode)}), \
                 patch('studio_monitor_repair.WindowsSeedProcess', return_value=process), \
                 patch('studio_monitor_probe.process_binding', return_value={}), \
                 patch('studio_monitor_probe.inspect_processes', return_value=dict(research=identity, protected=None)), \
                 self.assertRaisesRegex(ValueError, 'connected demo'):
                repair(self.c, 'real-'+str(mode))
        self.assertEqual(closed, [])
        self.start.assert_not_called()

    # ---- monitor-repair attempt ID length

    def test_an_over_long_repair_attempt_id_is_refused_before_any_close(self):
        process = SimpleNamespace(close=lambda identity: self.fail('closed MT5'), inspect=lambda: self.fail('inspected MT5'))
        with patch('studio_monitor_repair.WindowsSeedProcess', return_value=process), \
             patch('studio_monitor_repair.inspect_idle_demo', side_effect=AssertionError('probed MT5')) as probe:
            for length in (74, 80):
                with self.subTest(length=length), self.assertRaisesRegex(ValueError, 'Nothing was closed'):
                    repair(self.c, 'a'*length)
            probe.assert_not_called()
        self.assertFalse((self.c.root/'monitor-repairs').exists() and any((self.c.root/'monitor-repairs').iterdir()))
        self.start.assert_not_called()

    def test_the_longest_repair_attempt_id_still_relaunches(self):
        identity = dict(pid=44, executable=self.c.install['terminal_executable'], created_utc='2026-09-01T00:00:00Z')
        closed = []
        process = SimpleNamespace(close=closed.append, inspect=lambda: None)
        (Path(self.c.install['common_files_root'])/'GOAT').mkdir(exist_ok=True)
        with patch('studio_monitor_repair.WindowsSeedProcess', return_value=process), \
             patch('studio_monitor_repair.inspect_idle_demo', return_value=dict(process=identity)):
            result = repair(self.c, 'b'*73)
        self.assertEqual(result['phase'], 'launched')
        self.assertEqual(result['launch']['attempt_id'], 'repair-'+'b'*73)
        self.assertEqual(closed, [identity])
        self.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
