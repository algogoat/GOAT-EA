"""Stopped-terminal recovery may open a monitor solely to apply an owned cancel."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from demo_agent import DemoAgent, digest


class StoppedCancelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.agent=DemoAgent.__new__(DemoAgent)
        a=self.agent;a.root=root;a.local=root/'local';a.state_root=root/'demo-agent'
        a.installation_path=root/'installation.json';a.binary=root/'ea.ex5';a.binary.write_bytes(b'exact-ea')
        a.install={'ea_sha256':digest(a.binary),'terminal_data_root':str(root/'data')};a.clock=lambda:1000
        preset=root/'data/MQL5/Presets/GOAT Studio Agent.set';preset.parent.mkdir(parents=True)
        preset.write_text('Mode_Operation=11\nStudio_ReadOnlyMonitor=true\nStudio_MonitorRunPath=\nEA_Desc=Studio Monitor\n')
        a.process=Mock();a.process.inspect.return_value=None
        a._exclusive=lambda:nullcontext();a._owner_clear=Mock();a._space=Mock()
        a._native_active_batches=lambda:['batch'];a._append=Mock();a._readback_current=Mock(return_value={'verified':True})
        self.monitor=root/'monitor.ini';self.monitor.write_text('monitor only')
        a._validate_monitor_config=Mock(return_value=self.monitor)
        for p in [a.local/'native-gate',a.state_root,a.root/'batch-drivers']:p.mkdir(parents=True,exist_ok=True)
        (a.local/'ui-observation.json').write_text('{}')
        (a.state_root/'verified-build.json').write_text(json.dumps({'ea_sha256':digest(a.binary)}))
        (a.root/'batch-drivers/batch.json').write_text(json.dumps(dict(stopped=False,start_issued=True,attempt_id='attempt',binding={'generation':2})))
        self.request=dict(action='cancel',request_id='cancel',attempt_id='attempt',job_id='batch',expires_utc=1120)
        self.controller=Mock();self.controller.cancel.side_effect=self.publish
        self.controller.open.return_value=self.controller

    def publish(self,*args,**kwargs):
        gate=self.agent.local/'native-gate'
        (gate/'request.json').write_text(json.dumps(self.request))
        (gate/'permit.json').write_text(json.dumps({'request_sha256':digest(gate/'request.json')}))
        return {'request_id':'cancel'}

    def recover(self):
        with patch('goat_studio.Controller',return_value=self.controller), patch('studio_batch_driver._owned_attempt') as owned:
            result=self.agent._recover_stop_monitor('batch',self.monitor)
            owned.assert_called_once()
            return result

    def test_cancel_precedes_monitor_launch_and_stop_remains(self):
        marker=self.agent.state_root/'STOP';marker.write_text('{"actor":"demo_agent"}')
        def check_before_launch(config):
            self.assertEqual(json.loads((self.agent.local/'native-gate/request.json').read_text())['action'],'cancel')
            self.assertTrue(marker.exists())
        self.agent.process.start.side_effect=check_before_launch
        self.assertEqual(self.recover(),{'verified':True})
        self.agent._owner_clear.assert_called_once_with(require_fresh=False,settling_stop=True)
        self.agent.process.start.assert_called_once_with(self.monitor)
        self.assertTrue(marker.exists())
        self.controller.store.close.assert_called_once()

    def test_expired_consumed_foreign_or_start_request_never_launch(self):
        for delta in [{'expires_utc':1020},{'action':'start'},{'attempt_id':'foreign'},{'job_id':'foreign'}]:
            with self.subTest(delta=delta):
                original=dict(self.request);self.request.update(delta)
                with self.assertRaisesRegex(ValueError,'Fresh exact unconsumed'):self.recover()
                self.agent.process.start.assert_not_called();self.request=original
        (self.agent.local/'native-gate/consumed-cancel.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Fresh exact unconsumed'):self.recover()
        self.agent.process.start.assert_not_called()

    def test_running_terminal_or_changed_binary_never_launch(self):
        self.agent.process.inspect.return_value={'pid':42}
        with self.assertRaisesRegex(ValueError,'Terminal appeared'):self.recover()
        self.agent.process.inspect.return_value=None;self.agent.binary.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'previously verified'):self.recover()
        self.agent.process.start.assert_not_called()

    def test_live_driver_and_invalid_monitor_never_launch(self):
        folder=self.agent.state_root/'workers';folder.mkdir();(folder/'batch.json').write_text('{}')
        self.agent._worker_alive=lambda value:True
        with self.assertRaisesRegex(ValueError,'Existing supervisor'):self.recover()
        self.agent._validate_monitor_config.side_effect=ValueError('Invalid monitor')
        with self.assertRaisesRegex(ValueError,'Invalid monitor'):self.recover()
        self.agent.process.start.assert_not_called()


if __name__=='__main__':unittest.main()
