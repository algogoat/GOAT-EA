from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch

from studio_bridge import write_json
from studio_installation import read_json
from studio_driver_suspend import identify as REAL_IDENTIFY,suspend,require_no_publishers
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

    def suspended(self):
        """A real suspension of the verified publisher: goat.exe studio --installation <this> run-batch --job-id original."""
        installation=str(self.root/'installation.json')
        self.identity['launcher'].update(ExecutablePath=r'C:\kit\goat.exe',
            CommandLine=r'"C:\kit\goat.exe" studio --installation "%s" run-batch --job-id original --max-seconds 86400' % installation)
        suspend(self.c,self.job,self.folder,clock=Clock())
        return installation

    def test_resume_relaunches_the_exact_publisher_on_its_retained_journal_once(self):
        # goatai#2350 6101325773 (R1): the verified launcher and installation, the same job, `--resume` (never a budget).
        from studio_driver_suspend import resume
        installation=self.suspended();launched=[]
        def launch(argv):
            launched.append(argv);return 501
        child=dict(ProcessId=502,ParentProcessId=501,ExecutablePath=r'C:\kit\python\python.exe',
                   CommandLine=r'"C:\kit\python\python.exe" -B "C:\kit\agent\goat_agent.py" studio --installation "%s" run-batch --job-id original --resume' % installation)
        polls=iter([[dict(ProcessId=501,ParentProcessId=1,ExecutablePath=r'C:\kit\goat.exe')],[child]])
        record=resume(self.c,'original',self.folder,launch=launch,rows_fn=lambda:next(polls),clock=Clock())
        self.assertEqual(launched,[[r'C:\kit\goat.exe','studio','--installation',installation,'run-batch','--job-id','original','--resume']])
        self.assertEqual((record['status'],record['old_pids'],record['new_pids']),('resumed',dict(python=10,launcher=11),dict(launcher=501,python=502)))
        self.assertEqual(record['journal_sha256_at_resume'],record['journal_sha256_at_suspension'])
        self.assertEqual(read_json(self.folder/'publisher-resumed.json'),record)
        with self.assertRaisesRegex(ValueError,'never repeat'):
            resume(self.c,'original',self.folder,launch=launch,rows_fn=lambda:[child],clock=Clock())
        self.assertEqual(len(launched),1)

    def test_resume_refuses_a_changed_journal_and_says_the_one_step(self):
        from studio_driver_suspend import resume
        self.suspended()
        write_json(self.path,self.journal|dict(last_wall=2000))           # someone wrote the journal while suspended
        launch=unittest.mock.Mock()
        with self.assertRaises(ValueError) as caught:
            resume(self.c,'original',self.folder,launch=launch,rows_fn=lambda:[],clock=Clock())
        self.assertEqual(caught.exception.code,'PUBLISHER_RESUME_FAILED')
        self.assertIn('press Continue on the batch', str(caught.exception))
        self.assertIn('run-batch --job-id original --resume', str(caught.exception))
        launch.assert_not_called()
        failed=read_json(self.folder/'publisher-resume-failed.json')
        self.assertEqual((failed['status'],failed['reason']),('resume_failed','the batch journal changed while the publisher was suspended'))
        with self.assertRaisesRegex(ValueError,'never repeat'):          # one attempt, never a loop
            resume(self.c,'original',self.folder,launch=launch,rows_fn=lambda:[],clock=Clock())

    def test_resume_that_never_starts_its_driver_fails_once_without_a_second_launch(self):
        from studio_driver_suspend import resume
        self.suspended();launched=[]
        def launch(argv):
            launched.append(argv);return 501
        with self.assertRaises(ValueError) as caught:                     # the launcher exits before any driver appears
            resume(self.c,'original',self.folder,launch=launch,rows_fn=lambda:[],clock=Clock())
        self.assertEqual(caught.exception.code,'PUBLISHER_RESUME_FAILED')
        self.assertIn('exited before its driver started',read_json(self.folder/'publisher-resume-failed.json')['reason'])
        self.assertEqual(len(launched),1)

    def test_a_resumed_publisher_is_identified_for_a_later_suspension(self):
        installation=str(self.root/'installation.json')
        python=dict(ProcessId=502,ParentProcessId=501,ExecutablePath=r'C:\kit\python\python.exe',CreatedUtc='t',
                    CommandLine=r'"C:\kit\python\python.exe" -B "C:\kit\agent\goat_agent.py" studio --installation "%s" run-batch --job-id original --resume' % installation)
        launcher=dict(ProcessId=501,ParentProcessId=1,ExecutablePath=r'C:\kit\goat.exe',CreatedUtc='t',
                      CommandLine=r'"C:\kit\goat.exe" studio --installation "%s" run-batch --job-id original --resume' % installation)
        self.processes.return_value=[python,launcher]
        with patch('studio_driver_suspend.require_no_publishers'):
            found=REAL_IDENTIFY(self.c,'original',self.journal)                 # the real identify(), not setUp's patch
        self.assertEqual((found['python']['ProcessId'],found['launcher']['ProcessId']),(502,501))

    def test_publisher_inventory_allows_only_current_caller_and_own_launcher(self):
        import os,sys
        rows=[dict(ProcessId=os.getpid(),CommandLine='self'),
              dict(ProcessId=os.getppid(),ExecutablePath=str(Path(sys.executable).parent.parent/'goat.exe'),CommandLine='parent')]
        require_no_publishers(self.c,rows=rows)
        rows.append(dict(ProcessId=123456,ExecutablePath='old/python.exe',CommandLine='old studio serve'))
        with patch('studio_driver_suspend.arguments',return_value=['old','studio','--installation',str(self.root/'installation.json'),'serve']):
            with self.assertRaisesRegex(ValueError,'Another controller publisher'):require_no_publishers(self.c,rows=rows)
        with patch('studio_driver_suspend.arguments',return_value=['unrelated','other.py']):
            require_no_publishers(self.c,rows=rows)
        rows[-1]['CommandLine']=None
        with self.assertRaisesRegex(ValueError,'Unknown publisher'):require_no_publishers(self.c,rows=rows)


if __name__=='__main__':unittest.main()
