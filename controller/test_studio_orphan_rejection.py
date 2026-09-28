"""Rejected-recovery cleanup fixtures; never operate an installed terminal."""
import json
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from studio_bridge import write_json
from studio_handover import guard
from studio_installation import read_json
from studio_orphan_recovery import prepare, apply, status, plan_path
from studio_orphan_rejection import reconcile_rejection
import studio_orphan_rejection as settlement
import test_studio_orphan_recovery as fixtures


class RejectedRecoveryTests(unittest.TestCase):
    rejection_status='ORPHAN_RUNTIME_REJECTED'
    def setUp(self):
        self.fixture=fixtures.OrphanRecoveryTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown);self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c;self.gate=self.fixture.gate
        self.review=prepare(self.c)['review_id']
        apply(self.c,self.review,confirmed=True)
        self.fixture.consume(self.review,self.rejection_status,consumed=False)
        self.path=plan_path(self.c,self.review)
        self.plan=json.loads(self.path.read_text())
        self.request=self.plan['record']['request'];self.request_id=self.request['request_id']
        self.fence=self.c.root/'orphan-recovery-pending.json'
        self.root=self.path.parent/'rejection-settlement'
        self.before=self.c.state()
        self.clock=patch('studio_orphan_rejection.time.time',return_value=self.request['expires_utc']+1)
        self.clock.start();self.addCleanup(self.clock.stop)

    def run_settlement(self):
        return reconcile_rejection(self.c,self.review,confirmed=True)

    def assert_fenced(self):
        self.assertTrue(self.fence.exists())
        with self.assertRaisesRegex(ValueError,'orphan recovery'):guard(self.c)
        self.assertEqual(self.c.state(),self.before)
        self.assertTrue(self.fixture.flags)

    def test_exact_rejection_settles_without_retry_or_native_state_change(self):
        retained={p:p.read_bytes() for p in self.gate.iterdir() if p.name.startswith(('issued-','result-'))}
        original={name:(self.gate/name).read_bytes() for name in ('request.json','permit.json')}
        before_review=self.path.read_bytes()
        self.assertEqual(status(self.c,self.review)['status'],'reconcile_required')
        result=self.run_settlement()
        self.assertEqual(result['status'],'rejected_settled')
        self.assertFalse(result['launch_permitted']);self.assertFalse(result['recovery_retried'])
        self.assertFalse(self.fence.exists());guard(self.c)
        for name,raw in original.items():
            self.assertFalse((self.gate/name).exists());self.assertEqual((self.root/name).read_bytes(),raw)
        self.assertEqual((self.root/'review.json').read_bytes(),before_review)
        for path,raw in retained.items():self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(self.c.state(),self.before);self.assertTrue(self.fixture.flags)
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')
        self.assertEqual(status(self.c,self.review)['status'],'rejected_settled')
        self.assertEqual(apply(self.c,self.review,confirmed=True)['status'],'rejected_settled')
        self.assertFalse((self.gate/'permit.json').exists())

    def test_foreign_control_rejection_preserves_result_without_native_effect(self):
        self.fixture.consume(self.review,'ORPHAN_FOREIGN_CONTROL',consumed=False)
        result_file=self.gate/('result-'+self.request_id+'.json')
        before=result_file.read_bytes()
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')
        self.assertEqual(result_file.read_bytes(),before)
        self.assertEqual(status(self.c,self.review)['status'],'rejected_settled')
        self.assertEqual(self.c.state(),self.before);self.assertTrue(self.fixture.flags)
        self.assertFalse((self.gate/'request.json').exists())
        self.assertFalse((self.gate/'permit.json').exists())

    def test_foreign_control_rejection_with_actual_foreign_owner_stays_fenced(self):
        self.fixture.consume(self.review,'ORPHAN_FOREIGN_CONTROL',consumed=False)
        foreign=self.c.local/'other/controller.json';foreign.parent.mkdir()
        foreign.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Legacy/foreign'):self.run_settlement()
        self.assert_fenced();self.assertEqual(foreign.read_text(),'{}')
        self.assertFalse((self.root/'intent.json').exists())

    def test_foreign_control_rejection_with_consumption_stays_fenced(self):
        self.fixture.consume(self.review,'ORPHAN_FOREIGN_CONTROL',consumed=True)
        with self.assertRaisesRegex(ValueError,'consumption'):self.run_settlement()
        self.assert_fenced()

    def test_requires_review_confirmation_and_expired_request(self):
        with self.assertRaisesRegex(ValueError,'confirmation'):reconcile_rejection(self.c,self.review)
        for now in (self.request['expires_utc']-1,self.request['expires_utc']):
            with patch('studio_orphan_rejection.time.time',return_value=now),self.assertRaisesRegex(ValueError,'expired'):
                self.run_settlement()
        self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_only_supported_rejection_with_no_consumption_is_supported(self):
        for outcome in ('ORPHAN_RECOVERED','ORPHAN_CHANGED_AFTER_CLAIM','ORPHAN_CLEAR_FAILED','ORPHAN_BINDING_CHANGED','ORPHAN_CONTROL_CHANGED','unknown'):
            self.fixture.consume(self.review,outcome,consumed=False)
            with self.subTest(outcome=outcome),self.assertRaisesRegex(ValueError,'pre-consumption'):
                self.run_settlement()
            self.assert_fenced()
        self.fixture.consume(self.review,'ORPHAN_RUNTIME_REJECTED',consumed=True)
        with self.assertRaisesRegex(ValueError,'consumption'):self.run_settlement()
        self.assert_fenced()

    def test_any_selected_local_consumption_blocks_even_with_different_id(self):
        other=self.c.local/'elsewhere';other.mkdir()
        (other/('consumed-'+'a'*64+'.json')).write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'consumption'):self.run_settlement()
        self.assert_fenced()

    def test_missing_or_changed_receipt_issuance_and_transport_preserve_fence(self):
        files=[self.gate/('result-'+self.request_id+'.json'),self.gate/('issued-'+self.request_id+'.json'),self.gate/'request.json',self.gate/'permit.json']
        for file in files:
            raw=file.read_bytes();file.unlink()
            with self.subTest(path=file),self.assertRaises((ValueError,OSError,KeyError)):
                self.run_settlement()
            file.write_bytes(raw)
            file.write_bytes(raw+b' ')
            # Result/issued whitespace is semantically harmless before intent;
            # request bytes, unlike JSON objects, are bound by the native hash.
            if file.name=='request.json':
                with self.assertRaisesRegex(ValueError,'bytes changed'):self.run_settlement()
            file.write_bytes(raw)
        write_json(self.gate/'permit.json',dict(request_sha256='a'*64))
        with self.assertRaisesRegex(ValueError,'transport'):self.run_settlement()
        self.assert_fenced()

    def test_prior_control_or_request_is_not_discarded(self):
        for changed in (self.plan | dict(prior_request_utf8='old'),
                        self.plan | dict(record=self.plan['record'] | dict(prior_control={'status':'settled'}))):
            write_json(self.path,changed)
            with self.assertRaisesRegex(ValueError,'originally absent'):self.run_settlement()
        self.assert_fenced()

    def test_process_monitor_account_generation_and_batch_drift_refuse(self):
        for field,value in (('pid',999),('created_utc','new')):
            with patch('studio_orphan_recovery.inspect_processes',return_value={'research':dict(self.plan['observation']['process'],**{field:value})}),self.assertRaisesRegex(ValueError,'state changed'):
                self.run_settlement()
        self.fixture.cap['monitor_instance']='replaced'
        with self.assertRaisesRegex(ValueError,'state changed'):self.run_settlement()
        self.fixture.cap['monitor_instance']='instance-one'
        with patch.object(self.c,'runtime',side_effect=ValueError('Runtime policy mismatch: account_login')),self.assertRaisesRegex(ValueError,'account_login'):
            self.run_settlement()
        self.fixture.flags=False
        with self.assertRaisesRegex(ValueError,'batch_ongoing'):self.run_settlement()
        self.fixture.flags=True
        self.c.store.db.execute('UPDATE studio_state SET generation=generation+1')
        with self.assertRaisesRegex(ValueError,'state changed'):self.run_settlement()
        self.assertTrue(self.fence.exists());self.assertTrue((self.gate/'permit.json').exists())

    def test_original_review_fence_and_lock_must_match(self):
        write_json(self.fence,dict(review_id='a'*32))
        with self.assertRaisesRegex(ValueError,'fence changed'):self.run_settlement()
        write_json(self.fence,dict(review_id=self.review))
        from studio_native_gate import exclusive_gate
        with exclusive_gate(self.gate),self.assertRaises(OSError):self.run_settlement()
        self.assert_fenced()

    def test_interruption_after_each_cleanup_boundary_resumes_exact_evidence(self):
        original_unlink=Path.unlink
        for target in ('permit.json','request.json','orphan-recovery-pending.json'):
            def interrupted(path,*args,**kwargs):
                result=original_unlink(path,*args,**kwargs)
                if path.name==target:raise OSError('fixture crash after unlink')
                return result
            with patch.object(Path,'unlink',interrupted),self.assertRaisesRegex(OSError,'fixture crash'):
                self.run_settlement()
            if target!='orphan-recovery-pending.json':self.assert_fenced()
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')
        self.assertEqual(self.c.state(),self.before)

    def test_interruption_before_durable_status_keeps_fence_and_resumes(self):
        original_write=settlement.write_json
        def fail_status(path,value):
            if path==self.path:raise OSError('fixture status fsync failure')
            return original_write(path,value)
        with patch('studio_orphan_rejection.write_json',side_effect=fail_status),self.assertRaisesRegex(OSError,'fsync'):
            self.run_settlement()
        self.assert_fenced();self.assertFalse((self.gate/'request.json').exists())
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_durable_settlement_with_remaining_fence_needs_explicit_resume(self):
        original_unlink=Path.unlink
        def before_fence(path,*args,**kwargs):
            if path==self.fence:raise OSError('fixture interruption before fence cleanup')
            return original_unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',before_fence),self.assertRaisesRegex(OSError,'before fence'):
            self.run_settlement()
        self.assertEqual(read_json(self.path)['status'],'rejected_settled')
        self.assert_fenced()
        self.assertEqual(status(self.c,self.review)['status'],'reconcile_required')
        self.assertEqual(apply(self.c,self.review,confirmed=True)['status'],'reconcile_required')
        self.assertTrue(self.fence.exists())
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_evidence_or_intent_write_failure_never_removes_transport(self):
        for function in ('retain','write_json'):
            with patch('studio_orphan_rejection.'+function,side_effect=OSError('fixture disk full')),self.assertRaisesRegex(OSError,'disk full'):
                self.run_settlement()
            self.assertTrue((self.gate/'permit.json').exists());self.assertTrue((self.gate/'request.json').exists())
            self.assert_fenced()

    def test_late_consumption_is_not_cleaned(self):
        original_write=settlement.write_json
        def change_after_intent(path,value):
            original_write(path,value)
            if path.name=='intent.json':self.fixture.consume(self.review,self.rejection_status,consumed=True)
        with patch('studio_orphan_rejection.write_json',side_effect=change_after_intent),self.assertRaisesRegex(ValueError,'consumption'):
            self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())

    def test_late_result_change_is_not_cleaned(self):
        original_write=settlement.write_json
        def change_after_intent(path,value):
            original_write(path,value)
            if path.name=='intent.json':self.fixture.consume(self.review,'ORPHAN_CHANGED_AFTER_CLAIM',consumed=False)
        with patch('studio_orphan_rejection.write_json',side_effect=change_after_intent),self.assertRaisesRegex(ValueError,'evidence or transport changed'):
            self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())

    def test_transport_change_during_runtime_observation_is_not_removed(self):
        original_inspect=settlement.inspect
        def changed(*args,**kwargs):
            result=original_inspect(*args,**kwargs)
            write_json(self.gate/'permit.json',{'foreign':'permit'})
            return result
        with patch('studio_orphan_rejection.inspect',side_effect=changed),self.assertRaisesRegex(ValueError,'during runtime observation'):
            self.run_settlement()
        self.assertEqual(read_json(self.gate/'permit.json'),{'foreign':'permit'})
        self.assert_fenced()

    def test_foreign_request_after_first_retirement_stays_fenced(self):
        original_unlink=Path.unlink
        def changed(path,*args,**kwargs):
            result=original_unlink(path,*args,**kwargs)
            if path==self.gate/'permit.json':write_json(self.gate/'request.json',{'foreign':'request'})
            return result
        with patch.object(Path,'unlink',changed),self.assertRaisesRegex(ValueError,'transport changed'):
            self.run_settlement()
        self.assertEqual(read_json(self.gate/'request.json'),{'foreign':'request'})
        self.assert_fenced()

    def test_observation_holds_both_session_and_native_locks(self):
        from studio_handover import paths
        from studio_native_gate import shared_gate,exclusive_gate
        original_inspect=settlement.inspect
        def locked(*args,**kwargs):
            with self.assertRaises(OSError),shared_gate(paths(self.c)[3]):pass
            with self.assertRaises(OSError),exclusive_gate(self.gate):pass
            return original_inspect(*args,**kwargs)
        with patch('studio_orphan_rejection.inspect',side_effect=locked):
            self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_changed_archived_bytes_after_intent_refuse_before_cleanup(self):
        original_write=settlement.write_json
        def changed(path,value):
            original_write(path,value)
            if path.name=='intent.json':(self.root/'result.json').write_bytes(b'changed')
        with patch('studio_orphan_rejection.write_json',side_effect=changed),self.assertRaisesRegex(ValueError,'evidence changed'):
            self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())

    def test_future_fence_and_transport_untouched_by_old_apply_or_status(self):
        self.run_settlement()
        write_json(self.fence,dict(review_id='b'*32))
        write_json(self.gate/'request.json',{'later':'request'})
        write_json(self.gate/'permit.json',{'later':'permit'})
        before={p:p.read_bytes() for p in (self.fence,self.gate/'request.json',self.gate/'permit.json')}
        self.assertEqual(status(self.c,self.review)['status'],'rejected_settled')
        self.assertEqual(apply(self.c,self.review,confirmed=True)['status'],'rejected_settled')
        with self.assertRaisesRegex(ValueError,'fence changed'):self.run_settlement()
        for path,raw in before.items():self.assertEqual(path.read_bytes(),raw)

    def test_settled_readback_refuses_later_native_evidence_drift(self):
        self.run_settlement()
        result=self.gate/('result-'+self.request_id+'.json')
        result.write_bytes(result.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'evidence changed'):status(self.c,self.review)
        self.assertFalse((self.gate/'request.json').exists())

    def test_cli_contract_and_help_expose_exact_review_confirmation(self):
        from goat_studio import OPERATION_CONTRACTS,main
        contract=OPERATION_CONTRACTS['orphan-recovery-reconcile-rejection']
        self.assertEqual(contract['required'],['review-id'])
        self.assertEqual(contract['authorization_required_one_of'],['confirm-reviewed','owner-research'])
        self.assertIn('finite reviewed owner-demo',contract['authorization'])
        with patch('sys.stdout'),self.assertRaises(SystemExit) as exit:
            main(['orphan-recovery-reconcile-rejection','--help'])
        self.assertEqual(exit.exception.code,0)

    def test_cli_routes_exact_reconciliation_instead_of_status(self):
        from goat_studio import main
        output=io.StringIO()
        with patch('goat_studio.Controller',return_value=self.c),patch('sys.stdout',output):
            code=main(['--installation',str(self.c.root/'installation.json'),'orphan-recovery-reconcile-rejection',
                       '--review-id',self.review,'--confirm-reviewed'])
        self.assertEqual(code,0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['result']['status'],'rejected_settled')
        self.assertFalse((self.gate/'permit.json').exists())


class ReviewRejectedRecoveryTests(RejectedRecoveryTests):
    # Exercise the complete preserving/negative/interruption matrix for the
    # initial-validation rejection, not only its newly admitted success case.
    rejection_status='ORPHAN_REVIEW_REJECTED'


if __name__=='__main__':unittest.main()
