import hashlib
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import operation,before_native_dispatch
from studio_research_retry import predecessor
from studio_batch import prepare_batch
from studio_batch_driver import _binding
from studio_cancel_successor import create
from studio_finish import finish
import test_studio_cancel_successor as fixtures


class ResearchRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CancelSuccessorTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c;self.gate=self.fixture.gate;self.attempt=self.fixture.attempt
        self.plan=self.fixture.fixture.fixture.plan
        stop=create(self.c,'original');self.stop_id=stop['request_id']
        raw=(self.gate/'request.json').read_bytes()
        (self.gate/('consumed-'+self.stop_id+'.json')).write_bytes(raw)
        write_json(self.gate/('result-'+self.stop_id+'.json'),dict(request_id=self.stop_id,request_sha256=hashlib.sha256(raw).hexdigest(),status='CANCELLED_RECONCILE'))
        queue=self.fixture.fixture.common/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Queued_',';Cancelled_').replace(';Pending_',';Cancelled_').encode('utf-16'))
        finish(self.c,'original')
        self.scope=read_json(self.c.root/'research-authority.json')
        now=time.time();started=now-100
        self.journal=dict(schema_version=2,status='cancelled',stopped=True,start_issued=True,attempt_id=self.attempt,
                          binding=_binding(self.c,'original'),started_wall=started,deadline_wall=started+86400,max_seconds=86400,
                          min_free_bytes=5368709120,last_wall=now)
        self.path=self.c.root/'batch-drivers/original.json';self.path.parent.mkdir(exist_ok=True);write_json(self.path,self.journal)

    def test_real_cancel_finish_allows_one_exact_plan_replacement_preserving_history(self):
        old=self.c.job('original');proof=predecessor(self.c.store.db,self.c.state(),self.scope)
        with operation('prepare-batch'):result=prepare_batch(self.c,'replacement',self.plan)
        self.assertFalse(result['native_started']);self.assertEqual(self.c.job('original'),old)
        self.assertEqual(self.c.job('replacement')['configuration_sha256'],old['configuration_sha256'])
        self.assertEqual(proof['deadline_wall'],self.journal['deadline_wall'])
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'at most one'):
            prepare_batch(self.c,'second-replacement',self.plan)
        self.assertEqual(len(self.c.state()['queue']),2)

    def test_consumed_start_unconsumed_cancel_and_unstopped_driver_refuse(self):
        started=self.gate/('consumed-'+self.attempt+'.json')
        record=read_json(self.gate/('issued-'+self.attempt+'.json'))
        import json
        started.write_bytes((json.dumps(record['request'],ensure_ascii=False,allow_nan=False)+'\n').encode())
        with self.assertRaisesRegex(ValueError,'unconsumed pre-start'):predecessor(self.c.store.db,self.c.state(),self.scope)
        started.unlink()
        cancelled=self.gate/('consumed-'+self.stop_id+'.json');raw=cancelled.read_bytes();cancelled.unlink()
        with self.assertRaisesRegex(ValueError,'CANCELLED_RECONCILE'):predecessor(self.c.store.db,self.c.state(),self.scope)
        cancelled.write_bytes(raw)
        write_json(self.path,self.journal|dict(stopped=False))
        with self.assertRaisesRegex(ValueError,'verifiably stopped'):predecessor(self.c.store.db,self.c.state(),self.scope)

    def test_complete_inventory_refuses_root_checkpoint_local_output_and_tester_cache(self):
        from studio_report_paths import report_paths
        package=self.c.root/'packages/original'
        paths=report_paths(read_json(package/'studio-plan.json'),read_json(package/'manifest.json'))
        targets=[paths['common_run']/'checkpoint.bin',paths['local_run']/'raw-result.bin',
                 Path(self.c.install['terminal_data_root'])/'Tester/cache/result.opt']
        for path in targets:
            with self.subTest(path=path.name):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'unexpected work')
                with self.assertRaisesRegex(ValueError,'work'):predecessor(self.c.store.db,self.c.state(),self.scope)
                path.unlink()
        predecessor(self.c.store.db,self.c.state(),self.scope)

    def test_direct_start_without_inherited_driver_and_extended_deadline_refuse(self):
        with operation('prepare-batch'):prepare_batch(self.c,'replacement',self.plan)
        with operation('start'),self.assertRaisesRegex(ValueError,'live bounded'):before_native_dispatch(self.c,self.c.job('replacement'))
        inherited=predecessor(self.c.store.db,self.c.state(),self.scope,successor_id='replacement')
        path=self.c.root/'batch-drivers/replacement.json'
        value=dict(status='start_issued',start_issued=True,attempt_id=None,binding=dict(job_id='replacement'),inherited_budget=inherited,started_wall=inherited['started_wall'],max_seconds=86400,
                   deadline_wall=inherited['deadline_wall']+1,min_free_bytes=5368709120)
        write_json(path,value)
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'original bounded'):before_native_dispatch(self.c,self.c.job('replacement'))
        write_json(path,value|dict(deadline_wall=inherited['deadline_wall']))
        with operation('run-batch'):before_native_dispatch(self.c,self.c.job('replacement'))
        write_json(path,value|dict(deadline_wall=inherited['deadline_wall'],status='start_uncertain'))
        with operation('start'),self.assertRaisesRegex(ValueError,'live bounded'):before_native_dispatch(self.c,self.c.job('replacement'))
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'retained failed'):before_native_dispatch(self.c,self.c.job('replacement'))

    def test_expired_original_budget_and_reduced_disk_guard_refuse(self):
        write_json(self.path,self.journal|dict(started_wall=time.time()-86401,deadline_wall=time.time()-1))
        with self.assertRaises(ValueError):predecessor(self.c.store.db,self.c.state(),self.scope)
        write_json(self.path,self.journal)
        with operation('prepare-batch'):prepare_batch(self.c,'replacement',self.plan)
        inherited=predecessor(self.c.store.db,self.c.state(),self.scope,successor_id='replacement')
        write_json(self.c.root/'batch-drivers/replacement.json',dict(status='start_issued',start_issued=True,attempt_id=None,binding=dict(job_id='replacement'),inherited_budget=inherited,started_wall=inherited['started_wall'],
                   max_seconds=86400,deadline_wall=inherited['deadline_wall'],min_free_bytes=1))
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'disk reserve'):before_native_dispatch(self.c,self.c.job('replacement'))

    def test_explicit_owner_amendment_preserves_expired_original_and_requires_exact_new_budget(self):
        from studio_owner_budget import effective_expiry,renewal
        now=time.time()
        policy=dict(schema_version=1,authority_sha256=sha(self.scope),account=self.scope['account'],binding=self.scope['binding'],
                    predecessor_job_id='original',successor_job_id='replacement',max_seconds=172800,min_free_bytes=5368709120,
                    not_before_utc=now-10,expires_utc=now+3*86400)
        path=self.c.root/'fixture-owner-budget.json';write_json(path,policy)
        expired=self.journal|dict(started_wall=now-86401,deadline_wall=now-1,last_wall=now-2)
        write_json(self.path,expired);before=self.path.read_bytes()
        with patch('studio_owner_budget.POLICY_PATH',path):
            self.assertEqual(effective_expiry(self.scope),policy['expires_utc'])
            self.assertIsNone(renewal(self.scope|dict(generation=999)))
            with self.assertRaisesRegex(ValueError,'single replacement'):renewal(self.scope,successor_id='different')
            with operation('prepare-batch'):prepare_batch(self.c,'replacement',self.plan)
            inherited=predecessor(self.c.store.db,self.c.state(),self.scope,successor_id='replacement')
            value=dict(status='start_issued',start_issued=True,attempt_id=None,binding=dict(job_id='replacement'),
                       inherited_budget=inherited,budget_renewal=inherited['renewal_policy'],started_wall=now,
                       replacement_created_wall=now,max_seconds=172800,deadline_wall=now+172800,min_free_bytes=5368709120)
            target=self.c.root/'batch-drivers/replacement.json';write_json(target,value)
            with operation('run-batch'):before_native_dispatch(self.c,self.c.job('replacement'))
            for change in (dict(deadline_wall=now+172801),dict(min_free_bytes=1),dict(budget_renewal={}),dict(max_seconds=86400)):
                write_json(target,value|change)
                with operation('run-batch'),self.assertRaises(ValueError):before_native_dispatch(self.c,self.c.job('replacement'))
            self.assertEqual(self.path.read_bytes(),before)
            self.assertEqual(read_json(self.c.root/'research-authority.json'),self.scope)
            with patch('studio_owner_budget.time.time',return_value=policy['expires_utc']):
                self.assertIsNone(renewal(self.scope))

    def test_budget_amendment_cannot_revive_human_revoked_generation(self):
        from campaign_ledger import packed
        from studio_research_authority import authority
        from studio_owner_budget import effective_expiry
        now=time.time()
        policy=dict(schema_version=1,authority_sha256=sha(self.scope),account=self.scope['account'],binding=self.scope['binding'],
                    predecessor_job_id='original',successor_job_id='replacement',max_seconds=172800,min_free_bytes=5368709120,
                    not_before_utc=now-10,expires_utc=now+3*86400)
        path=self.c.root/'fixture-owner-budget.json';write_json(path,policy)
        with patch('studio_owner_budget.POLICY_PATH',path):
            self.assertGreater(effective_expiry(self.scope),now+172800)
            with operation('run-batch'),self.assertRaisesRegex(ValueError,'permanently revoked'):
                authority(self.c.store.db,packed(self.scope['binding']),dict(owner='human',generation=self.scope['generation']+1))


if __name__=='__main__':unittest.main()
