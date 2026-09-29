"""Do not equate missing consumption with never-issued native activation."""
import json
import unittest

from studio_unissued_start import proof, settled_other_request
import test_studio_launch_transport as fixtures


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
