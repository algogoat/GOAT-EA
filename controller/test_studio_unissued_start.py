"""Do not equate missing consumption with never-issued native activation."""
import json
import unittest

from studio_unissued_start import proof
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
        with self.assertRaisesRegex(ValueError,'request evidence'):
            proof(self.c,self.job,self.fixture.package)

    def test_activation_folder_or_changed_intent_refuses(self):
        evidence=self.c.root/'attempts'/self.intent['attempt_id']
        evidence.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'activation evidence'):
            proof(self.c,self.job,self.fixture.package)

    def test_changed_package_or_generation_refuses(self):
        self.job['reservation']['generation']+=1
        with self.assertRaisesRegex(ValueError,'binding changed'):
            proof(self.c,self.job,self.fixture.package)


if __name__=='__main__':unittest.main()
