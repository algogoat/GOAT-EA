import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_bridge import write_json
from studio_monitor_repair import repair
from studio_process_check import classify_processes
import test_studio_onboarding as onboarding


class MonitorRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = onboarding.OnboardingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c = self.fixture.c
        onboarding.monitor_prepare(self.c, 'EURUSD')
        (Path(self.c.install['common_files_root'])/'GOAT').mkdir(exist_ok=True)
        self.identity = dict(pid=44, executable=str(self.fixture.fixture.bin), created_utc='2026-09-01T00:00:00Z')
        self.process = SimpleNamespace(close=lambda identity: None, inspect=lambda: None)
        self.close = patch.object(self.process, 'close').start()
        self.addCleanup(patch.stopall)
        patch('studio_monitor_repair.WindowsSeedProcess', return_value=self.process).start()
        self.probe = patch('studio_monitor_repair.inspect_idle_demo', return_value=dict(process=self.identity)).start()

    def test_repair_preserves_profile_and_attaches_without_grant(self):
        profile = Path(json.loads((self.c.root/'monitor-profile.json').read_text())['profile_path'])
        original = (profile/'chart01.chr').read_bytes()
        changed = original.replace('true'.encode('utf-16-le'), 'false'.encode('utf-16-le'))
        (profile/'chart01.chr').write_bytes(changed)
        result = repair(self.c, 'first')
        self.assertEqual(result['phase'], 'launched')
        self.assertEqual((profile/'chart01.chr').read_bytes(), original)
        self.assertEqual((Path(result['profile_backup'])/'chart01.chr').read_bytes(), changed)
        self.assertEqual(self.c.state()['owner'], 'human')
        self.assertEqual(self.c.state()['queue'], [])
        self.close.assert_called_once_with(self.identity)
        self.assertEqual(repair(self.c, 'first'), result)
        self.close.assert_called_once()
        self.assertEqual(self.fixture.start.call_count, 1)

    def test_unresolved_close_is_never_reissued(self):
        self.close.side_effect = OSError('uncertain normal-close delivery')
        with self.assertRaises(OSError): repair(self.c, 'uncertain')
        self.close.side_effect = None
        result = repair(self.c, 'uncertain')
        self.assertEqual(result['phase'], 'launched')
        self.close.assert_called_once()

    def test_stop_only_preserves_profile_never_launches_and_replays_without_close(self):
        profile=Path(json.loads((self.c.root/'monitor-profile.json').read_text())['profile_path'])
        before={p.name:p.read_bytes() for p in profile.iterdir()}
        result=repair(self.c,'upgrade-stop',stop_only=True)
        self.assertEqual(result['status'],'selected_terminal_stopped')
        self.assertFalse(result['profile_changed'])
        self.fixture.start.assert_not_called(); self.close.assert_called_once()
        self.assertEqual(repair(self.c,'upgrade-stop',stop_only=True)['status'],'selected_terminal_stopped')
        self.close.assert_called_once()
        with self.assertRaisesRegex(ValueError,'reinterpret'):
            repair(self.c,'upgrade-stop')
        self.assertEqual(before,{p.name:p.read_bytes() for p in profile.iterdir()})

    def test_completed_stop_refuses_reopened_terminal(self):
        repair(self.c,'reopened-stop',stop_only=True)
        self.process.inspect=lambda:dict(self.identity,pid=99)
        with self.assertRaisesRegex(ValueError,'reopened'):
            repair(self.c,'reopened-stop',stop_only=True)
        self.close.assert_called_once();self.fixture.start.assert_not_called()

    def test_replacement_is_not_adopted(self):
        self.close.side_effect = OSError('uncertain')
        with self.assertRaises(OSError): repair(self.c, 'replacement')
        self.process.inspect = lambda: dict(self.identity, pid=99)
        with self.assertRaisesRegex(ValueError, 'replaced'): repair(self.c, 'replacement')
        self.close.assert_called_once()
        self.fixture.start.assert_not_called()

    def test_failed_probe_cannot_close_or_launch(self):
        self.probe.side_effect = ValueError('Busy tester or live/unsafe account')
        with self.assertRaises(ValueError): repair(self.c, 'blocked')
        self.close.assert_not_called(); self.fixture.start.assert_not_called()

    def test_outstanding_controls_cannot_close(self):
        base=Path(self.c.install['common_files_root'])/'GOAT/GOAT V1.48-Customer-Demo'
        base.mkdir(); (base/'active_optimization_run.ini').write_text('owned')
        with self.assertRaisesRegex(ValueError, 'controls remain'): repair(self.c, 'blocked')
        self.close.assert_not_called(); self.fixture.start.assert_not_called()

    def test_other_version_history_is_retained_not_cleared(self):
        base=Path(self.c.install['common_files_root'])/'GOAT/GOAT V1.40-Customer-Demo'
        base.mkdir(); pointer=base/'active_optimization_run.ini';pointer.write_bytes(b'old-version-history')
        result=repair(self.c,'historical')
        self.assertIn(str(pointer),result['retained_other_version_controls'])
        self.assertEqual(pointer.read_bytes(),b'old-version-history')

    def test_pending_or_completed_queue_is_not_monitor_repair(self):
        for status in ('pending', 'completed'):
            with patch.object(self.c, 'state', return_value={'queue':[{'status':status}]}):
                with self.assertRaisesRegex(ValueError, 'never-started'): repair(self.c, 'blocked')
        self.close.assert_not_called()

    def test_stopped_peer_is_allowed_but_replacement_is_rejected(self):
        research=dict(ProcessId=1,ExecutablePath='C:/selected/terminal64.exe',CreatedUtc='first')
        peer=dict(ProcessId=2,ExecutablePath='C:/peer/terminal64.exe',CreatedUtc='second')
        binding=dict(research_terminal=research['ExecutablePath'],protected_terminal=peer['ExecutablePath'],
                     protected_process=dict(pid=2,executable='C:\\peer\\terminal64.exe',created_utc='second'),protected_may_be_stopped=True)
        self.assertIsNone(classify_processes([research],binding,observed_unix=0)['protected'])
        self.assertEqual(classify_processes([research,peer],binding,observed_unix=0)['protected']['pid'],2)
        with self.assertRaises(ValueError): classify_processes([research,dict(peer,ProcessId=3)],binding,observed_unix=0)
        with self.assertRaises(ValueError): classify_processes([research],dict(binding,protected_may_be_stopped=False),observed_unix=0)


if __name__=='__main__': unittest.main()
