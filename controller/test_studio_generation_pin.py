"""A bounded runner cannot inherit a successor's grant at a mutation boundary."""
import unittest
from unittest.mock import patch
import test_goat_studio as fixtures
from studio_finish import finish


class GenerationPinTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PortableControllerTests(); self.fixture.setUp()

    def tearDown(self): self.fixture.tearDown()

    def test_generation_change_before_reservation_does_not_create_attempt(self):
        c=self.fixture.bound();self.fixture.grant(c);self.fixture.prepare(c)
        generation=c.state()['generation']; original=c.submit
        def changed(*args,**kwargs):
            c.store.db.execute('UPDATE studio_state SET generation=generation+1,revision=revision+1')
            return original(*args,**kwargs)
        with patch.object(c,'runtime',return_value=({},{})),patch.object(c,'submit',side_effect=changed), \
             patch('studio_process_check.inspect_processes',return_value={}):
            with self.assertRaisesRegex(ValueError,'generation'):
                c.start('beta-job',expected_generation=generation)
        self.assertEqual(c.job('beta-job')['status'],'pending')
        self.assertFalse((c.root/'attempts').exists())

    def test_native_cancel_refuses_successor_grant_inside_gate(self):
        c,_,_,_=self.fixture.activated_fixture()
        generation=c.state()['generation']
        c.store.db.execute('UPDATE studio_state SET generation=generation+1,revision=revision+1')
        with self.assertRaisesRegex(ValueError,'generation changed before cancel'):
            c.cancel('beta-job',expected_generation=generation)
        self.assertFalse((c.local/'native-gate/permit.json').exists())
        self.assertFalse((c.local/'native-gate/request.json').exists())

    def test_finish_generation_change_after_runtime_refuses_before_control_restore(self):
        c,native,base,evidence=self.fixture.activated_fixture()
        generation=c.state()['generation']; queue=native/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Pending_',';Cancelled_').encode('utf-16'))
        before={str(p):p.read_bytes() for p in base.iterdir() if p.is_file()}
        def changed(**kwargs):
            c.store.db.execute('UPDATE studio_state SET generation=generation+1,revision=revision+1')
            return {},{}
        with patch.object(c,'runtime',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'generation changed during finish'):
                finish(c,'beta-job',expected_generation=generation)
        self.assertEqual(before,{str(p):p.read_bytes() for p in base.iterdir() if p.is_file()})
        self.assertFalse((evidence/'result.json').exists())


if __name__=='__main__':unittest.main()
