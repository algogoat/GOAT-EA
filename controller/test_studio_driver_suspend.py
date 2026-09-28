from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from studio_bridge import write_json
from studio_installation import read_json
from studio_driver_suspend import suspend
from test_studio_batch_driver import Clock


class DriverSuspendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'batch-drivers').mkdir();(self.root/'batch-driver-gate').mkdir()
        self.folder=self.root/'recovery';self.folder.mkdir()
        self.c=SimpleNamespace(root=self.root,state=lambda:dict(generation=0))
        self.job=dict(job_id='original',launch_intent=dict(attempt_id='a'*64))
        self.journal=dict(binding=dict(job_id='original',generation=0),stopped=False,attempt_id='a'*64,
                          started_wall=1000,deadline_wall=87400,max_seconds=86400,min_free_bytes=5368709120)
        self.path=self.root/'batch-drivers/original.json';write_json(self.path,self.journal)
        self.identity=dict(python=dict(ProcessId=10,CreatedUtc='first'),launcher=dict(ProcessId=11,CreatedUtc='first'))
        self.identify=patch('studio_driver_suspend.identify',return_value=self.identity).start()
        self.interrupt=patch('studio_driver_suspend.interrupt').start()
        self.processes=patch('studio_driver_suspend.processes',return_value=[]).start()
        self.addCleanup(patch.stopall)

    def test_exit_and_lock_proof_preserve_original_driver_budget(self):
        raw=self.path.read_bytes();result=suspend(self.c,self.job,self.folder,clock=Clock())
        self.assertTrue(result['supervisor_exited']);self.assertFalse(result['native_stop_claimed'])
        self.assertEqual(raw,self.path.read_bytes());self.interrupt.assert_called_once_with(self.identity)
        suspend(self.c,self.job,self.folder,clock=Clock());self.interrupt.assert_called_once()

    def test_unstopped_driver_refuses_without_second_signal(self):
        self.processes.return_value=list(self.identity.values())
        with self.assertRaisesRegex(ValueError,'did not stop'):suspend(self.c,self.job,self.folder,clock=Clock())
        with self.assertRaisesRegex(ValueError,'did not stop'):suspend(self.c,self.job,self.folder,clock=Clock())
        self.interrupt.assert_called_once();self.assertFalse((self.folder/'publisher-stopped.json').exists())

    def test_process_replacement_or_changed_budget_refuses(self):
        self.processes.return_value=[dict(ProcessId=10,CreatedUtc='replacement')]
        with self.assertRaisesRegex(ValueError,'identity changed'):suspend(self.c,self.job,self.folder,clock=Clock())
        self.processes.return_value=[]
        write_json(self.path,self.journal|dict(deadline_wall=999999))
        with self.assertRaisesRegex(ValueError,'budget'):suspend(self.c,self.job,self.folder,clock=Clock())
        self.interrupt.assert_called_once()


if __name__=='__main__':unittest.main()
