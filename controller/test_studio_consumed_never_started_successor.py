"""A consumed refusal can continue only after exact no-work cancellation proof."""
import hashlib
import json
import time
import unittest

from studio_batch_driver import _binding
from studio_bridge import write_json
from studio_cancel_successor import create
from studio_consumed_never_started_successor import proof
from studio_finish import finish
from studio_installation import read_json
import test_studio_cancel_successor as fixtures


class ConsumedNeverStartedSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.CancelSuccessorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c;self.gate=self.f.gate;self.attempt=self.f.attempt
        stop=create(self.c,'original');self.stop_id=stop['request_id']
        issued=read_json(self.gate/('issued-'+self.attempt+'.json'))['request']
        start_raw=(json.dumps(issued,ensure_ascii=False,allow_nan=False)+'\n').encode()
        (self.gate/('consumed-'+self.attempt+'.json')).write_bytes(start_raw)
        write_json(self.gate/('result-'+self.attempt+'.json'),dict(request_id=self.attempt,
            request_sha256=hashlib.sha256(start_raw).hexdigest(),status='SETTINGS_NOT_VERIFIED'))
        cancel_raw=(self.gate/'request.json').read_bytes()
        (self.gate/('consumed-'+self.stop_id+'.json')).write_bytes(cancel_raw)
        write_json(self.gate/('result-'+self.stop_id+'.json'),dict(request_id=self.stop_id,
            request_sha256=hashlib.sha256(cancel_raw).hexdigest(),status='CANCELLED_RECONCILE'))
        queue=self.f.fixture.common/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Queued_',';Cancelled_')
            .replace(';Pending_',';Cancelled_').encode('utf-16'))
        finish(self.c,'original')
        self.job=self.c.job('original')
        self.scope=read_json(self.c.root/'research-authority.json')
        self.scope['renewal']=dict(max_seconds=172800,min_free_bytes=5368709120)
        self.first_proof=dict(retirement_sha256='f'*64)
        now=time.time()
        self.driver=self.c.root/'batch-drivers/original.json';self.driver.parent.mkdir(exist_ok=True)
        self.journal=dict(schema_version=2,status='cancelled',stopped=True,cancel_reason='disk_low',
            cancel_issued=True,start_issued=True,attempt_id=self.attempt,fresh_authority_budget=self.first_proof,
            result_path=str(self.c.root/'attempts'/self.attempt/'result.json'),binding=_binding(self.c,'original'),
            max_seconds=172800,min_free_bytes=5368709120,started_wall=now,last_wall=now,
            deadline_wall=now+172800)
        write_json(self.driver,self.journal)
        self.state={'queue':[{'job_id':'retired-original'},self.job]}

    def checked(self):
        return proof(self.c,self.state,self.scope,self.first_proof)

    def test_exact_cancelled_never_started_refusal_has_one_successor_proof(self):
        value=self.checked()
        self.assertTrue(value['fresh_native_epoch'])
        self.assertEqual(value['predecessor_attempt_id'],self.attempt)
        self.assertEqual(value['max_seconds'],172800)
        self.assertEqual(value['min_free_bytes'],5368709120)
        self.assertEqual(len(value['consumed_start_sha256']),64)
        self.assertEqual(len(value['cancelled_request_sha256']),64)
        with self.assertRaisesRegex(ValueError,'one successor'):
            proof(self.c,{'queue':self.state['queue']+[self.job,self.job]},self.scope,self.first_proof)

    def test_refuses_changed_native_refusal_and_any_start_intent(self):
        result=self.gate/('result-'+self.attempt+'.json');before=result.read_bytes()
        item=read_json(result);item['status']='STARTED';write_json(result,item)
        with self.assertRaises(ValueError):self.checked()
        result.write_bytes(before)
        intent=self.gate/('start-intent-'+self.attempt+'.json');intent.write_text('{}')
        with self.assertRaisesRegex(ValueError,'armed'):self.checked()
        intent.unlink()
        self.checked()

    def test_refuses_work_output_or_changed_budget(self):
        from studio_report_paths import report_paths
        package=self.c.root/'packages/original'
        paths=report_paths(read_json(package/'studio-plan.json'),read_json(package/'manifest.json'))
        local=paths['local_run'];local.mkdir(parents=True,exist_ok=True)
        output=local/'unlisted-tester-result.xml';output.write_text('work')
        with self.assertRaisesRegex(ValueError,'work output'):self.checked()
        output.unlink()
        write_json(self.driver,self.journal|dict(deadline_wall=self.journal['deadline_wall']+1))
        with self.assertRaisesRegex(ValueError,'budget evidence'):self.checked()
        write_json(self.driver,self.journal)
        self.checked()


if __name__=='__main__':unittest.main()
