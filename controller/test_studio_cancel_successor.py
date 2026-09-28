import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_cancel_successor import create,cancel_id
from studio_finish import finish
import test_studio_rejected_monitor as fixtures


class CancelSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RejectedMonitorTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c;self.gate=self.fixture.gate;self.attempt=self.fixture.attempt
        with patch('studio_cancel.time',SimpleNamespace(time=lambda:1)):self.c.cancel('original')
        self.original=sha([self.attempt,'cancel'])
        prior=read_json(self.gate/('issued-'+self.original+'.json'))
        write_json(self.gate/('result-'+self.original+'.json'),dict(request_id=self.original,request_sha256=prior['request_sha256'],status='CANCEL_REJECTED'))
        recovery=self.c.root/'rejected-monitor-restarts'/self.attempt;recovery.mkdir(parents=True)
        write_json(recovery/'restart.json',dict(phase='reverified',authority_sha256=sha(read_json(self.c.root/'research-authority.json')),process=self.fixture.native['process']))
        patch('studio_monitor_probe.inspect_idle_demo',return_value=self.fixture.native).start()
        self.runtime=patch.object(self.c,'runtime',return_value=({},{})).start()

    def test_new_cancel_retains_prior_evidence_and_finish_binds_successor(self):
        paths=[self.gate/(prefix+self.original+'.json') for prefix in ('issued-','result-')]
        before={p:p.read_bytes() for p in paths}
        result=create(self.c,'original');identity=result['request_id']
        self.assertNotEqual(identity,self.original)
        self.assertEqual(cancel_id(self.c.root,self.c.job('original'),self.gate),identity)
        for p,raw in before.items():self.assertEqual(p.read_bytes(),raw)
        with self.assertRaisesRegex(ValueError,'successor already'):create(self.c,'original')
        with self.assertRaisesRegex(ValueError,'Successor cancellation'):finish(self.c,'original')
        raw=(self.gate/'request.json').read_bytes()
        (self.gate/('consumed-'+identity+'.json')).write_bytes(raw)
        write_json(self.gate/('result-'+identity+'.json'),dict(request_id=identity,request_sha256=hashlib.sha256(raw).hexdigest(),status='CANCELLED_RECONCILE'))
        queue=self.fixture.common/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Queued_',';Cancelled_').replace(';Pending_',';Cancelled_').encode('utf-16'))
        result=finish(self.c,'original')
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['result']['cancellation_dispatch']['receipt']['request_id'],identity)
        from studio_native_gate import assert_clear_controls,exclusive_gate
        with exclusive_gate(self.gate):self.assertEqual(assert_clear_controls(self.c.store.db,self.gate)['request_id'],identity)

    def test_missing_rejection_or_consumed_old_cancel_refuses(self):
        receipt=self.gate/('result-'+self.original+'.json');raw=receipt.read_bytes();receipt.unlink()
        with self.assertRaisesRegex(ValueError,'CANCEL_REJECTED'):create(self.c,'original')
        receipt.write_bytes(raw)
        (self.gate/('consumed-'+self.original+'.json')).write_bytes((self.gate/'request.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'orphan recovery'):create(self.c,'original')
        self.assertFalse((self.c.root/'cancel-successors'/(self.attempt+'.json')).exists())

    def test_prior_evidence_tamper_and_signal_only_stop_refuse(self):
        result=create(self.c,'original');identity=result['request_id']
        path=self.gate/('result-'+self.original+'.json');raw=path.read_bytes();path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'prior cancellation'):cancel_id(self.c.root,self.c.job('original'),self.gate)
        path.write_bytes(raw)
        request=(self.gate/'request.json').read_bytes();(self.gate/('consumed-'+identity+'.json')).write_bytes(request)
        write_json(self.gate/('result-'+identity+'.json'),dict(request_id=identity,request_sha256=hashlib.sha256(request).hexdigest(),status='CANCEL_SIGNAL_SENT_RECONCILE'))
        with self.assertRaisesRegex(ValueError,'CANCELLED_RECONCILE'):finish(self.c,'original')


if __name__=='__main__':unittest.main()
