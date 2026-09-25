"""Onboarding effects are fixture-only: no installed terminal is touched/launched."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goat_studio import Controller
from studio_onboarding import onboarding_status, monitor_prepare, monitor_launch
import test_goat_studio as fixtures


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound()
        self.data = self.fixture.data
        self.processes = patch('studio_onboarding.inspect_processes', return_value={
            'research':{'created_utc':'2020-01-01T00:00:00+00:00','pid':55}})
        self.inspector = self.processes.start()
        self.addCleanup(self.processes.stop)
        self.launch = patch('studio_onboarding.subprocess.Popen',return_value=SimpleNamespace(pid=42))
        self.start = self.launch.start()
        self.addCleanup(self.launch.stop)
        (self.data/'origin.txt').write_text(str(self.fixture.bin.parent))
        (self.data/'config').mkdir()
        self.common_ini = self.data/'config/common.ini'
        self.common_ini.write_text('[Common]\nLogin=123456\nServer=Customer-Demo\n[Experts]\nEnabled=0\n')

    def observe(self, **changes):
        state = self.c.state()
        observation = dict(schema_version=1, bound=True, loaded=True,
            observed_terminal_utc=datetime.now(timezone.utc).strftime('%Y.%m.%d %H:%M:%S'),
            owner=state['owner'], revision=state['revision'], generation=state['generation'],
            runtime=dict(data_path=str(self.data),installation_path=str(self.fixture.bin.parent),
                program_path=str(self.data/'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5'),
                account_login='123456',account_server='Customer-Demo',connected=True,account_demo=True,
                terminal_trade_allowed=False,batch_ongoing=False,restart_pending=False,tester_state='idle'))
        observation.update(changes)
        (self.c.local/'ui-observation.json').write_text(json.dumps(observation),encoding='utf-8')

    def test_status_without_bootstrap_is_blocked_and_does_not_create_database(self):
        other = dict(self.fixture.receipt,controller_state_root=str(self.fixture.root/'empty-state'))
        path = self.fixture.root/'other.json';path.write_text(json.dumps(other))
        result = onboarding_status(Controller(path))
        self.assertEqual(result['status'],'needs_action')
        self.assertFalse(Path(other['controller_state_root']).exists())
        self.start.assert_not_called()

    def test_status_never_consumes_human_request_or_grants_control(self):
        self.observe()
        inbox = self.c.bridge.root/'human/inbox/pending-grant.json';inbox.write_text('{}')
        before = (self.c.root/'studio.sqlite').read_bytes()
        result = onboarding_status(self.c)
        self.assertEqual(result['status'],'needs_action')
        self.assertEqual(result['steps'][-1]['state'],'human_action')
        self.assertTrue(inbox.exists())
        self.assertEqual(before,(self.c.root/'studio.sqlite').read_bytes())
        self.assertEqual(self.c.state()['owner'],'human')

    def test_ready_means_local_monitor_only(self):
        self.fixture.grant(self.c);self.observe()
        result = onboarding_status(self.c)
        self.assertEqual(result['status'],'local_monitor_ready')
        self.assertFalse(result['execution_ready'])
        self.assertFalse(result['native_qualification'])

    def test_stale_revision_or_feedback_never_ready(self):
        self.fixture.grant(self.c);self.observe(generation=-1)
        result=onboarding_status(self.c)
        self.assertEqual(result['steps'][-1]['state'],'blocked')
        self.observe(observed_terminal_utc='2000.01.01 00:00:00')
        self.assertEqual(onboarding_status(self.c)['status'],'needs_action')

    def test_feedback_before_process_start_is_rejected(self):
        self.observe()
        self.inspector.return_value={'research':{'created_utc':'2099-01-01T00:00:00+00:00','pid':55}}
        self.assertIn('predates',onboarding_status(self.c)['steps'][-1]['detail'])

    def test_prepare_separate_persistent_chart_no_permissions_and_idempotent(self):
        original = self.data/'MQL5/Profiles/Charts/Default/chart01.chr'
        original.parent.mkdir(parents=True);original.write_bytes(b'untouched')
        result=monitor_prepare(self.c,'EURUSD.a')
        text=(Path(result['profile_path'])/'chart01.chr').read_text(encoding='utf-16')
        self.assertIn('expertmode=0',text);self.assertIn('Studio_ReadOnlyMonitor=true',text)
        self.assertEqual(original.read_bytes(),b'untouched')
        self.assertTrue(monitor_prepare(self.c,'EURUSD.a')['reused'])
        self.start.assert_not_called()
        with self.assertRaises(ValueError):monitor_prepare(self.c,'another-symbol')

    def test_prepare_refuses_running_terminal_before_profile_write(self):
        self.inspector.side_effect=ValueError('Expected research process state')
        with self.assertRaises(ValueError):monitor_prepare(self.c,'EURUSD')
        self.assertFalse((self.data/'MQL5/Profiles').exists())

    def test_launch_profile_without_config_password_or_grant_and_never_retry(self):
        result=monitor_prepare(self.c,'EURUSD');before=self.common_ini.read_bytes()
        launch=monitor_launch(self.c,'first-open')
        self.assertEqual(launch['status'],'process_started_unverified')
        args=self.start.call_args.args[0]
        self.assertEqual(args,[str(self.fixture.bin),'/profile:'+result['profile_name']])
        self.assertEqual(self.c.state()['owner'],'human')
        self.assertEqual(before,self.common_ini.read_bytes())
        self.assertTrue(monitor_launch(self.c,'first-open')['reused'])
        self.assertEqual(self.start.call_count,1)

    def test_launch_rejects_saved_trading_login_and_wrong_origin(self):
        monitor_prepare(self.c,'EURUSD')
        original=self.common_ini.read_text()
        for text in (original.replace('Enabled=0','Enabled=1'),original.replace('123456','998877')):
            self.common_ini.write_text(text)
            with self.assertRaises(ValueError):monitor_launch(self.c,'unsafe')
        self.common_ini.write_text(original)
        (self.data/'origin.txt').write_text('C:/another/terminal')
        with self.assertRaises(ValueError):monitor_launch(self.c,'wrong-origin')
        self.start.assert_not_called()

    def test_launch_crash_retains_intent_blocks_automatic_relaunch(self):
        monitor_prepare(self.c,'EURUSD');self.start.side_effect=OSError('fixture launch failure')
        with self.assertRaises(OSError):monitor_launch(self.c,'crash')
        self.assertEqual(monitor_launch(self.c,'crash')['status'],'launch_intent')
        with self.assertRaisesRegex(ValueError,'Unresolved'):monitor_launch(self.c,'new-after-crash')
        self.assertEqual(self.start.call_count,1)

    def test_changed_profile_not_overwritten_or_launched(self):
        result=monitor_prepare(self.c,'EURUSD')
        chart=Path(result['profile_path'])/'chart01.chr';chart.write_bytes(b'MT5 changed saved profile')
        with self.assertRaises(ValueError):monitor_launch(self.c,'changed')
        with self.assertRaises(ValueError):monitor_prepare(self.c,'EURUSD')
        self.assertEqual(chart.read_bytes(),b'MT5 changed saved profile')
        self.start.assert_not_called()

    def test_saved_profile_metadata_survives_restart_with_zero_permissions(self):
        result=monitor_prepare(self.c,'EURUSD')
        chart=Path(result['profile_path'])/'chart01.chr'
        text=chart.read_text(encoding='utf-16').replace('scale=8','scale=7')
        chart.write_text(text,encoding='utf-16')
        (chart.parent/'order.wnd').write_bytes(b'fixture ordering')
        monitor_launch(self.c,'saved-restart')
        self.start.assert_called_once()

    def test_saved_profile_rejects_changed_trading_or_executable_inputs(self):
        result=monitor_prepare(self.c,'EURUSD')
        chart=Path(result['profile_path'])/'chart01.chr';original=chart.read_text(encoding='utf-16')
        unsafe=[original.replace('expertmode=0','expertmode=5'),
                original.replace('expertmode=0','expertmode=4'),
                original.replace('Studio_ReadOnlyMonitor=true','Studio_ReadOnlyMonitor=false'),
                original.replace('Mode_Operation=11','Mode_Operation=8'),
                original.replace('Mode_Operation=11','Mode_Operation=11\nMode_Operation =8'),
                original.replace('GOAT V1.48.ex5','another.ex5'),
                original.replace('name=Main','name=CustomIndicator')]
        for text in unsafe:
            chart.write_text(text,encoding='utf-16')
            with self.assertRaises(ValueError):monitor_launch(self.c,'unsafe-saved')
        self.start.assert_not_called()

    def test_active_seed_blocks_setup(self):
        (self.c.root/'seed-active.json').write_text(json.dumps(dict(status='active',batch_id='seed-fixture')))
        with self.assertRaises(ValueError):monitor_prepare(self.c,'EURUSD')
        self.start.assert_not_called()

    def test_cli_discovery_advertises_new_commands(self):
        from goat_studio import OPERATION_CONTRACTS
        self.assertEqual(OPERATION_CONTRACTS['monitor-launch']['required'],['attempt-id'])
        self.assertEqual(OPERATION_CONTRACTS['monitor-prepare']['required'],['symbol'])
        self.assertEqual(OPERATION_CONTRACTS['onboarding-status']['required'],[])


if __name__=='__main__':unittest.main()
