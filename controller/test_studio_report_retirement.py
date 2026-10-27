"""Real Windows junction cleanup, preserving all target report data."""
import os
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from studio_bridge import write_json
from studio_report_bridge import paths,prepare,retire


@unittest.skipUnless(os.name=='nt','Native Windows junction semantics')
class ReportRetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.binding=dict(research_data_root=str(self.root/'data'),
                          research_terminal=str(self.root/'install/terminal64.exe'))
        self.relative='GOAT\\R123456abcdef'
        self.source,self.target=paths(self.binding,self.relative)
        self.target.mkdir(parents=True)
        (self.target/'report.xml').write_text('retain exact report')
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        self.receipt=prepare(self.binding,self.relative)

    def apply(self):
        return retire(self.binding,self.relative,self.receipt,self.evidence)

    def test_removes_only_alias_and_replays_without_touching_target(self):
        result=self.apply()
        self.assertTrue(result['removed'])
        self.assertFalse(os.path.lexists(self.source))
        self.assertEqual((self.target/'report.xml').read_text(),'retain exact report')
        self.assertEqual(self.apply(),result)

    def test_interrupted_after_unlink_resumes_same_retirement(self):
        original=write_json
        def fail_done(path,value):
            if value.get('phase')=='retired':raise OSError('injected receipt failure')
            return original(path,value)
        with patch('studio_bridge.write_json',side_effect=fail_done):
            with self.assertRaisesRegex(OSError,'injected'):self.apply()
        self.assertFalse(os.path.lexists(self.source))
        self.assertEqual(self.apply()['phase'],'retired')
        self.assertTrue((self.target/'report.xml').is_file())

    def test_missing_alias_without_intent_refuses(self):
        self.source.rmdir()
        with self.assertRaisesRegex(ValueError,'without retirement intent'):self.apply()

    def test_replaced_regular_directory_is_never_removed(self):
        self.source.rmdir();self.source.mkdir()
        (self.source/'unrelated.txt').write_text('preserve')
        with self.assertRaisesRegex(ValueError,'junction changed'):self.apply()
        self.assertTrue((self.source/'unrelated.txt').is_file())

    def test_retargeted_junction_refuses(self):
        import _winapi
        self.source.rmdir();other=self.root/'other';other.mkdir()
        _winapi.CreateJunction(str(other),str(self.source))
        with self.assertRaisesRegex(ValueError,'junction changed'):self.apply()
        self.assertTrue(self.source.is_junction())

    def test_receipt_and_run_drift_refuse(self):
        changed=dict(self.receipt,target=str(self.root/'other'))
        with self.assertRaisesRegex(ValueError,'frozen run'):
            retire(self.binding,self.relative,changed,self.evidence)
        with self.assertRaisesRegex(ValueError,'Exact managed report run'):
            retire(self.binding,'GOAT\\..',self.receipt,self.evidence)
        self.assertTrue(self.source.is_junction())

    def test_recreated_alias_after_retirement_refuses(self):
        self.apply();prepare(self.binding,self.relative)
        with self.assertRaisesRegex(ValueError,'recreated'):self.apply()

    def test_portable_same_root_preserves_directory(self):
        self.source.rmdir()
        self.binding['research_terminal']=str(self.root/'data/terminal64.exe')
        self.receipt=prepare(self.binding,self.relative)
        self.assertFalse(self.apply()['removed'])
        self.assertTrue((self.target/'report.xml').is_file())


from test_goat_studio import PortableControllerTests

@unittest.skipUnless(os.name=='nt','Native Windows junction semantics')
class FinishRetirementTests(PortableControllerTests):
    def prepare_retirement(self):
        from campaign_ledger import packed
        c,native,base,evidence=self.activated_fixture()
        job=c.job('beta-job');package=Path(job['launch_intent']['package'])
        plan=json.loads((package/'studio-plan.json').read_text())
        manifest=json.loads((package/'manifest.json').read_text())
        source,target=paths(plan['research_binding'],manifest['native_run_relative'])
        target.mkdir(parents=True,exist_ok=True)
        (target/'retain.xml').write_text('report')
        receipt=prepare(plan['research_binding'],manifest['native_run_relative'])
        write_json(evidence/'report-bridge.json',receipt)
        job['restart_intent']=dict(report_bridge=receipt,phase='process_started_unverified',
                                  attempt_id=job['launch_intent']['attempt_id'])
        state=c.state();state['queue']=[job]
        binding=packed(dict(terminal_id=c.terminal,run_id=c.run))
        c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
        queue=native/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Pending_',';Cancelled_').encode('utf-16'))
        return c,source,target

    def test_finish_retires_verified_alias_after_idle_and_preserves_reports(self):
        from studio_finish import finish
        c,source,target=self.prepare_retirement()
        with patch.object(c,'runtime',return_value=({},{})):
            result=finish(c,'beta-job')
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['result']['report_bridge_retirement']['phase'],'retired')
        self.assertTrue((target/'retain.xml').is_file())
        self.assertFalse(os.path.lexists(source))

    def test_busy_native_refuses_cleanup(self):
        from studio_finish import finish
        c,source,target=self.prepare_retirement()
        with patch.object(c,'runtime',side_effect=ValueError('native still running')):
            with self.assertRaisesRegex(ValueError,'still running'):finish(c,'beta-job')
        self.assertTrue(source.is_junction())
        self.assertTrue((target/'retain.xml').is_file())


if __name__=='__main__':unittest.main()
