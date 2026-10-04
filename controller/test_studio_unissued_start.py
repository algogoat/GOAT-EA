"""Do not equate missing consumption with never-issued native activation."""
import hashlib
import json
from pathlib import Path
import unittest

from studio_batch import prepare_batch
from studio_bridge import write_json
from studio_launch_intent import record_intent
from studio_unissued_start import proof, settled_other_request
import test_studio_launch_transport as fixtures
from test_settled_native_request import PENDING_VARIANTS, gate_files, retain_pending_variant, retain_request


class UnissuedStartTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LaunchTransportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.intent=self.fixture.reserve_and_record()
        self.c=self.fixture.c
        self.job=self.c.job('mixed')

    def test_exact_unactivated_intent_reuses_same_identity(self):
        self.assertEqual(proof(self.c,self.job,self.fixture.package),self.intent)

    def test_request_without_consumption_still_refuses(self):
        gate=self.c.local/'native-gate'
        path=gate/('issued-'+self.intent['attempt_id']+'.json')
        path.write_text(json.dumps(dict(request=dict(job_id='mixed',request_id=self.intent['attempt_id']))))
        with self.assertRaises(ValueError):
            proof(self.c,self.job,self.fixture.package)

    def test_hash_only_permit_and_request_refuse_for_any_job(self):
        gate=self.c.local/'native-gate'
        for name in ('permit.json','request.json'):
            path=gate/name
            path.write_text(json.dumps(dict(request_sha256='f'*64)))
            with self.assertRaisesRegex(ValueError,'request or permit'):
                proof(self.c,self.job,self.fixture.package)
            path.unlink()

    def test_pending_or_mismatched_request_still_refuses_first_activation(self):
        gate=self.c.local/'native-gate'
        for name in PENDING_VARIANTS:
            with self.subTest(name):
                retain_pending_variant(name,gate,self.c.terminal,self.c.run)
                before=gate_files(gate)
                with self.assertRaisesRegex(ValueError,'request or permit'):
                    proof(self.c,self.job,self.fixture.package)
                self.assertEqual(gate_files(gate),before)

    def test_settled_request_still_needs_its_job_durably_finished(self):
        # The request.json presence check accepts the Terminal 3 shape (goatai#1885), but the
        # unchanged history check still requires the other job's durable completion.
        gate=self.c.local/'native-gate'
        retain_request(gate,self.c.terminal,self.c.run)
        with self.assertRaisesRegex(ValueError,'no settled controller job'):
            proof(self.c,self.job,self.fixture.package)

    def test_finished_batch_request_left_on_the_gate_does_not_block_first_activation(self):
        # Terminal 3 shape with a real finished batch: request.json is kept beside its exact
        # consumed/result pair after finish (goatai#1885); a fresh batch's unissued intent resumes.
        import test_studio_settled_gate as settled
        fixture=settled.SettledGateTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.settle('start')
        c,gate,files=fixture.c,fixture.gate,fixture.fixture
        self.assertTrue((gate/'request.json').exists())
        plan=files.root/'fresh-batch.json'
        write_json(plan,dict(schema_version=1,export=files.exports,
                             members=[dict(set_path=str(files.root/'strategy.set'),tester=files.tester)]))
        package=Path(prepare_batch(c,'fresh-batch',plan)['package'])
        digest=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
        c.submit('queue.reserve',dict(job_id='fresh-batch',configuration_sha256=c.job('fresh-batch')['configuration_sha256'],
                 package_sha256=digest),'fresh-reservation')
        state=c.state()
        intent=record_intent(c.store,c.terminal,c.run,'fresh-batch',package,actor='agent',
                             revision=state['revision'],generation=state['generation'])
        before=gate_files(gate)
        self.assertEqual(proof(c,c.job('fresh-batch'),package),intent)
        self.assertEqual(gate_files(gate),before)

    def test_hash_only_orphan_dispatch_history_refuses(self):
        gate=self.c.local/'native-gate'
        for prefix in ('issued','consumed','result'):
            path=gate/(prefix+'-'+'f'*64+'.json')
            path.write_text(json.dumps(dict(request_sha256='f'*64)))
            with self.assertRaises((ValueError,KeyError,OSError)):
                proof(self.c,self.job,self.fixture.package)
            path.unlink()

    def test_activation_folder_or_changed_intent_refuses(self):
        evidence=self.c.root/'attempts'/self.intent['attempt_id']
        evidence.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'activation evidence'):
            proof(self.c,self.job,self.fixture.package)

    def test_changed_package_or_generation_refuses(self):
        self.job['reservation']['generation']+=1
        with self.assertRaisesRegex(ValueError,'binding changed'):
            proof(self.c,self.job,self.fixture.package)

    def test_foreign_history_requires_exact_finish_and_restored_transaction(self):
        import test_studio_settled_gate as settled
        fixture=settled.SettledGateTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.settle('start')
        before={p.name:p.read_bytes() for p in fixture.gate.glob('*.json')}
        settled_other_request(fixture.c,fixture.gate,fixture.request_id,'fresh-job')
        self.assertEqual(before,{p.name:p.read_bytes() for p in fixture.gate.glob('*.json')})
        with self.assertRaisesRegex(ValueError,'different settled job'):
            settled_other_request(fixture.c,fixture.gate,fixture.request_id,'beta-job')
        transaction=fixture.evidence/'transaction.json'
        value=json.loads(transaction.read_text())
        value['phase']='installed'
        transaction.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'restored controls'):
            settled_other_request(fixture.c,fixture.gate,fixture.request_id,'fresh-job')


if __name__=='__main__':unittest.main()
