"""File/store transition chain with mocked native process effects."""
import hashlib
import time
import unittest
from unittest.mock import patch

from campaign_ledger import packed
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import operation,before_native_dispatch,authority
from studio_derived_report_recovery import recover
from studio_never_started_retirement import retire,replacement_proof
from studio_batch import prepare_batch
import test_studio_derived_report_recovery as fixtures
from test_settled_native_request import PENDING_VARIANTS,gate_files,retain_pending_variant,retain_request


class NeverStartedRetirementTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ManagedReportRecoveryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c;self.process=self.f.process
        self.addCleanup(patch.stopall)
        patch('studio_research_regrant.OWNER_ACCOUNT',self.c.session['account']).start()
        original=self.f.f.runtime.side_effect
        def runtime(**kwargs):
            if self.f.started:
                state=self.c.state();path=self.f.draft_path;value=read_json(path)
                write_json(path,value|dict(revision=state['revision'],generation=state['generation']))
            return original(**kwargs)
        self.f.f.runtime.side_effect=runtime
        state=self.c.state()
        self.send('control.takeover','genuine-takeover',state)
        with operation('research-monitor-repair-revoked-report'):
            recover(self.c,'original',process=self.process,revoked_maintenance=True)
        self.native=lambda *args,**kwargs:self.f.f.native|dict(process=self.f.current)
        patch('studio_monitor_probe.inspect_idle_demo',side_effect=self.native).start()
        patch('studio_research_regrant.native',side_effect=self.native).start()
        patch('studio_never_started_retirement.native',side_effect=self.native).start()
        with operation('serve'):state=self.c.state()
        self.send('control.grant_agent','genuine-fresh-grant',state)
        self.c.runtime(require_idle=True)
        self.process.close.reset_mock();self.process.start.reset_mock()
        self.attempt=state['queue'][0]['launch_intent']['attempt_id']
        self.evidence=self.c.root/'attempts'/self.attempt
        self.folder=self.evidence/'never-started-retirement'
        self.gate=self.c.local/'native-gate'
        self.driver=self.c.root/'batch-drivers/original.json';self.driver_raw=self.driver.read_bytes()
        self.authority_raw=(self.c.root/'research-authority.json').read_bytes()
        self.queue=self.f.f.f.common/'queue.GOAT';self.queue_raw=self.queue.read_bytes()

    def send(self,command,ident,state):
        request=dict(schema_version=1,request_id=ident,terminal_id=self.c.terminal,run_id=self.c.run,
            expected_revision=state['revision'],generation=state['generation'],command=command,payload={})
        write_json(self.c.bridge.root/'human/inbox'/(ident+'.json'),request)
        with operation('serve'):self.assertTrue(self.c.bridge.pump()[0]['ok'])

    def run_retire(self):
        with operation('research-retire-never-started'):return retire(self.c,'original',process=self.process)

    def test_retirement_preserves_native_rejection_queue_and_old_budget_then_allows_one_replacement(self):
        result=self.run_retire();self.assertEqual(result['status'],'retired_never_started')
        self.assertFalse(result['native_started']);self.assertEqual(self.run_retire(),result)
        self.process.close.assert_called_once();self.process.start.assert_called_once()
        self.assertEqual(self.queue.read_bytes(),self.queue_raw);self.assertEqual(self.driver.read_bytes(),self.driver_raw)
        self.assertEqual((self.c.root/'research-authority.json').read_bytes(),self.authority_raw)
        self.assertTrue((self.gate/('issued-'+self.attempt+'.json')).exists())
        self.assertFalse((self.gate/('consumed-'+self.attempt+'.json')).exists())
        self.assertFalse((self.gate/'request.json').exists())
        completion=read_json(self.evidence/'result.json')
        self.assertFalse(completion['native_cancellation_claimed']);self.assertEqual(completion['executed_members'],0)
        plan=self.f.f.f.fixture.plan
        with operation('prepare-batch'):
            prepare_batch(self.c,'replacement',plan)
            with self.assertRaisesRegex(ValueError,'one new-epoch'):prepare_batch(self.c,'extra',plan)
        with operation('run-batch'):
            state=self.c.state();binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
            scope=authority(self.c.store.db,binding,state)
            proof=replacement_proof(self.c.store.db,state,scope,successor_id='replacement')
            now=time.time();journal=dict(status='start_issued',start_issued=True,attempt_id=None,binding=dict(job_id='replacement'),
                fresh_authority_budget=proof,max_seconds=172800,min_free_bytes=5368709120,started_wall=now,deadline_wall=now+172800)
            write_json(self.c.root/'batch-drivers/replacement.json',journal)
            with patch('studio_monitor_probe.inspect_idle_demo',side_effect=self.native):before_native_dispatch(self.c,self.c.job('replacement'))
            write_json(self.c.root/'batch-drivers/replacement.json',journal|dict(deadline_wall=now+172801))
            with self.assertRaisesRegex(ValueError,'new native epoch budget'):before_native_dispatch(self.c,self.c.job('replacement'))

    def test_a_request_consumed_and_answered_after_retirement_is_settled_not_new(self):
        result=self.run_retire()
        # Terminal 3 shape (goatai#1885): a later orphan-recovery continuation (the only consumption
        # the retirement proof admits) kept on the gate beside its exact consumed/result pair.
        retain_request(self.gate,self.c.terminal,self.c.run,action='recover_orphan_continuation',status='ORPHAN_RECOVERED')
        before=gate_files(self.gate)
        self.assertEqual(self.run_retire(),result)
        self.assertEqual(gate_files(self.gate),before)
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_a_pending_or_mismatched_request_after_retirement_still_refuses(self):
        self.run_retire()
        for name in PENDING_VARIANTS:
            with self.subTest(name):
                retain_pending_variant(name,self.gate,self.c.terminal,self.c.run,action='recover_orphan_continuation')
                before=gate_files(self.gate)
                with self.assertRaisesRegex(ValueError,'New native request appeared after retirement'):self.run_retire()
                self.assertEqual(gate_files(self.gate),before)
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_evidence_compaction_keeps_the_retired_row_so_the_replacement_proof_still_passes(self):
        from studio_evidence_log import compact
        binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
        with operation('serve'):state=self.c.state()
        history=[dict(native=dict(status='native_rejected',n=i)) for i in range(5)]
        state['queue'][0]['native_evidence_history']=history
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
        self.run_retire()
        with operation('prepare-batch'):prepare_batch(self.c,'replacement',self.f.f.f.fixture.plan)
        with operation('compact-evidence'):result=compact(self.c,apply=True)
        with operation('run-batch'):
            state=self.c.state();scope=authority(self.c.store.db,binding,state)
            # Compacting this row would make the proof refuse 'Retirement original job changed'.
            proof=replacement_proof(self.c.store.db,state,scope,successor_id='replacement')
            self.assertEqual(state['queue'][0]['native_evidence_history'],history)
        self.assertEqual(proof['predecessor_job_id'],'original')
        self.assertFalse(result['applied'])
        self.assertEqual([(s['job_id'],s['reason']) for s in result['skipped']],[('original','never_started_retirement_proof')])

    def test_continue_refuses_in_a_typed_research_continuation_with_one_sentence(self):
        from studio_fast_lane import continue_batch
        self.run_retire()
        with operation('batch-continue'),self.assertRaisesRegex(ValueError,
                r'^Continue is not available in a typed research continuation session, because it authorizes only its exact frozen plan; '
                r'run batch-status for the batch, then ask the owner for a new research grant that covers the remaining members\.$'):
            continue_batch(self.c,'original')

    def test_restoration_publication_interruption_resumes_without_repeated_close(self):
        from studio_never_started_retirement import write_json as real
        def fail(path,value):
            if path==self.folder/'retirement.json' and value.get('phase')=='controls_restored':raise OSError('phase interrupted')
            return real(path,value)
        with patch('studio_never_started_retirement.write_json',side_effect=fail),self.assertRaisesRegex(OSError,'phase interrupted'):
            self.run_retire()
        self.assertEqual(read_json(self.evidence/'transaction.json')['phase'],'restored')
        self.assertEqual(self.run_retire()['status'],'retired_never_started')
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_draft_publication_interruption_resumes_exact_transformation(self):
        from studio_never_started_retirement import write_json as real
        def fail(path,value):
            if path==self.folder/'retirement.json' and value.get('phase')=='draft_repaired':raise OSError('draft phase interrupted')
            return real(path,value)
        with patch('studio_never_started_retirement.write_json',side_effect=fail),self.assertRaisesRegex(OSError,'draft phase interrupted'):
            self.run_retire()
        self.assertEqual(self.run_retire()['status'],'retired_never_started')
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_uncertain_launch_is_not_repeated(self):
        self.process.start.side_effect=ValueError('launch outcome unknown')
        with self.assertRaisesRegex(ValueError,'launch outcome unknown'):self.run_retire()
        with self.assertRaisesRegex(ValueError,'relaunch uncertain'):self.run_retire()
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_original_work_output_refuses_before_close(self):
        (self.queue.parent/'unexpected-output.txt').write_bytes(b'work')
        with self.assertRaisesRegex(ValueError,'artifacts'):self.run_retire()
        self.process.close.assert_not_called();self.process.start.assert_not_called()

    def test_new_human_takeover_is_processed_and_refuses_retirement(self):
        state=self.c.state();request=dict(schema_version=1,request_id='take-again',terminal_id=self.c.terminal,
            run_id=self.c.run,expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
        write_json(self.c.bridge.root/'human/inbox/take-again.json',request)
        with self.assertRaisesRegex(ValueError,'revoked'):self.run_retire()
        self.process.close.assert_not_called();self.process.start.assert_not_called()


if __name__=='__main__':unittest.main()
