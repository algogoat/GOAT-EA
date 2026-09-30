"""Task envelopes retain exact scope and never fall back after uncertain start."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_durable_driver import launch, validate, bootstrap
import studio_durable_driver as durable
import test_goat_studio as fixtures


class DurableDriverTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableControllerTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.c=self.f.bound()
        self.root=self.c.root/'demo-agent/workers';self.root.mkdir(parents=True)
        self.nonce='a'*32;self.worker=self.root/'batch.json'
        self.worker.write_text(json.dumps(dict(schema_version=1,status='reserved',batch_id='batch',nonce=self.nonce,resume=False,max_seconds=60)))
        self.python=self.f.root/'python runtime with spaces';self.python.mkdir()
        (self.python/'python.exe').write_bytes(b'fixture')
        (self.python/'pythonw.exe').write_bytes(b'fixture')
        self.argv=[str(self.python/'python.exe'),str(Path(durable.__file__).with_name('demo_agent.py')),
            '--installation',str(self.f.path),'_drive-batch','--batch-id','batch','--nonce',self.nonce,'--max-seconds','60']
        self.log=self.root/('batch-'+self.nonce+'.log')

    def registered(self,*args,**kwargs):
        self.request=json.loads(kwargs['input'])
        record=json.loads(self.worker.read_text())
        envelope=json.loads(Path(record['launch_envelope']).read_text())
        Path(envelope['started']).write_text(json.dumps(dict(pid=456,nonce=self.nonce)))
        return SimpleNamespace(returncode=0)

    def test_windowless_demand_task_keeps_exact_args_and_retained_identity(self):
        with patch('studio_durable_driver.subprocess.run',side_effect=self.registered) as call:
            child=launch(self.argv,log_path=self.log,worker_path=self.worker)
        self.assertEqual(child.pid,456);self.assertIsNone(child.poll())
        self.assertTrue(self.request['executable'].endswith('pythonw.exe'))
        self.assertIn(self.nonce,self.request['arguments'])
        self.assertEqual(self.request['limit'],360)
        self.assertNotIn('-Trigger',durable.REGISTER_TASK)
        self.assertIn('-RunLevel Limited',durable.REGISTER_TASK)
        self.assertIn('Interactive',durable.REGISTER_TASK)
        self.assertIn('-EncodedCommand',call.call_args.args[0])
        envelope=json.loads(Path(json.loads(self.worker.read_text())['launch_envelope']).read_text())
        self.assertEqual(envelope['argv'],self.argv)
        Path(envelope['finished']).write_text(json.dumps(dict(exit_code=0,nonce=self.nonce)))
        self.assertEqual(child.poll(),0)

    def test_uncertain_registration_never_uses_popen_or_replaces_envelope(self):
        failure=subprocess.TimeoutExpired('powershell',30)
        with patch('studio_durable_driver.subprocess.run',side_effect=failure),patch('subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError,'unconfirmed'):
                launch(self.argv,log_path=self.log,worker_path=self.worker)
            popen.assert_not_called()
        envelope=Path(json.loads(self.worker.read_text())['launch_envelope'])
        self.assertTrue(envelope.is_file())
        with self.assertRaises((ValueError,FileExistsError)):
            launch(self.argv,log_path=self.log,worker_path=self.worker)

    def test_finished_receipt_cannot_identify_a_different_nonce(self):
        with patch('studio_durable_driver.subprocess.run',side_effect=self.registered):
            child=launch(self.argv,log_path=self.log,worker_path=self.worker)
        child.finished.write_text(json.dumps(dict(exit_code=0,nonce='b'*32)))
        with self.assertRaisesRegex(ValueError,'identity changed'):
            child.poll()

    def test_path_escape_foreign_nonce_and_new_resume_budget_refuse(self):
        with self.assertRaisesRegex(ValueError,'canonical'):
            validate(self.argv,self.f.root/'outside.log',self.worker)
        value=json.loads(self.worker.read_text());value['nonce']='b'*32;self.worker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'identity'):
            validate(self.argv,self.log,self.worker)
        value.update(nonce=self.nonce,resume=True,max_seconds=None);self.worker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'Resume'):
            validate(self.argv,self.log,self.worker)

    def test_expired_resume_is_observation_cancellation_only_without_new_budget(self):
        value=json.loads(self.worker.read_text());value.update(resume=True,max_seconds=None);self.worker.write_text(json.dumps(value))
        folder=self.c.root/'batch-drivers';folder.mkdir()
        (folder/'batch.json').write_text(json.dumps(dict(deadline_wall=1)))
        _,remaining=validate(self.argv[:-2],self.log,self.worker)
        self.assertEqual(remaining,0)

    def test_bootstrap_redirects_output_and_keeps_exact_driver_arguments(self):
        prefix=self.log.with_suffix('')
        envelope=Path(str(prefix)+'.launch.json')
        started=Path(str(prefix)+'.started.json');finished=Path(str(prefix)+'.finished.json')
        envelope.write_text(json.dumps(dict(schema_version=1,argv=self.argv,log_path=str(self.log),
            worker_path=str(self.worker),started=str(started),finished=str(finished),task_name='fixture-task')))
        original=sys.stdout,sys.stderr
        def driver(argv):
            self.assertEqual(argv,self.argv[2:])
            self.assertFalse(json.loads(started.read_text())['native_running_verified'])
            print('driver observation, not native qualification')
            return 0
        with patch('demo_agent.main',side_effect=driver):
            self.assertEqual(bootstrap(envelope),0)
        self.assertEqual((sys.stdout,sys.stderr),original)
        self.assertEqual(json.loads(finished.read_text())['exit_code'],0)
        self.assertIn('not native qualification',self.log.read_text())


if __name__=='__main__':unittest.main()
