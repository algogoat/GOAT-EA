"""Settled native dispatches allow queue cleanup without deleting any evidence."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed
from studio_batch import prepare_batch
from studio_bridge import write_json
from studio_finish import finish
from studio_native_gate import assert_clear_controls, exclusive_gate
from studio_queue_clear import clear_queue


class SettledGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.c, self.native, self.base, self.evidence = self.fixture.activated_fixture()
        self.gate = self.c.local/'native-gate'

    def tearDown(self):
        self.fixture.tearDown()

    def consume(self, action='cancel'):
        if action == 'cancel':
            self.c.cancel('beta-job')
        else:
            job = self.c.job('beta-job')
            request = dict(request_id=job['launch_intent']['attempt_id'], terminal_id=self.c.terminal,
                           run_id=self.c.run, job_id='beta-job', configuration_sha256=job['configuration_sha256'])
            if action != 'start': request['action'] = action
            raw = (json.dumps(request, ensure_ascii=False, allow_nan=False)+'\n').encode()
            write_json(self.gate/('issued-'+request['request_id']+'.json'),
                       dict(request=request, request_sha256=hashlib.sha256(raw).hexdigest()))
            (self.gate/'request.json').write_bytes(raw)
        raw = (self.gate/'request.json').read_bytes()
        request = json.loads(raw); self.request_id = request['request_id']
        (self.gate/('consumed-'+self.request_id+'.json')).write_bytes(raw)
        write_json(self.gate/('result-'+self.request_id+'.json'),
                   dict(request_id=self.request_id, request_sha256=hashlib.sha256(raw).hexdigest(),
                        status='CANCEL_REQUESTED' if action == 'cancel' else 'START_SENT_RECONCILE'))

    def settle(self, action='cancel'):
        self.consume(action)
        queue = self.native/'queue.GOAT'
        queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Pending_', ';Cancelled_').encode('utf-16'))
        with patch.object(self.c, 'runtime', return_value=({}, {})):
            result = finish(self.c, 'beta-job')
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse((self.gate/'permit.json').exists())
        return result

    def classify(self):
        with exclusive_gate(self.gate):
            return assert_clear_controls(self.c.store.db, self.gate)

    def test_actual_finish_then_clear_and_fresh_prepare_preserves_all_receipts(self):
        self.settle()
        before_files = {p: p.read_bytes() for p in self.gate.iterdir() if p.is_file()}
        completed = self.c.job('beta-job')
        self.c.submit('queue.enqueue', dict(job_id='pending-next'), 'pending-next')
        preview = clear_queue(self.c)
        clear_queue(self.c, apply=True, request_id='clear-after-finish', expected_revision=preview['expected_revision'])
        self.assertEqual(self.c.job('beta-job'), completed)
        self.assertEqual(self.c.job('pending-next')['status'], 'removed')
        for path, raw in before_files.items(): self.assertEqual(path.read_bytes(), raw)
        classified = self.classify()
        self.assertEqual(classified['status'], 'settled')
        self.assertEqual(classified['request_id'], self.request_id)
        self.assertEqual(classified['completion_sha256'], hashlib.sha256((self.evidence/'result.json').read_bytes()).hexdigest())
        plan = self.fixture.root/'fresh-batch.json'
        write_json(plan, dict(schema_version=1, export=self.fixture.exports,
                   members=[dict(set_path=str(self.fixture.root/'strategy.set'), tester=self.fixture.tester)]))
        prepared = prepare_batch(self.c, 'fresh-batch', plan)
        self.assertFalse(prepared['native_started'])
        self.assertEqual(self.c.job('fresh-batch')['status'], 'pending')
        for path, raw in before_files.items(): self.assertEqual(path.read_bytes(), raw)

    def test_finished_start_request_without_action_field_is_settled(self):
        self.settle('start')
        self.assertEqual(self.classify()['status'], 'settled')

    def test_native_result_alone_never_proves_finished_and_never_discards_permit(self):
        self.consume()
        raw = (self.gate/'permit.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Native request or permit'):
            self.classify()
        self.assertEqual((self.gate/'permit.json').read_bytes(), raw)
        # Removing the fixture permit does not create controller finish evidence.
        (self.gate/'permit.json').unlink()
        with self.assertRaisesRegex(ValueError, 'not durably finished'):
            self.classify()

    def test_missing_evidence_fails_closed(self):
        self.settle()
        paths = [self.gate/(prefix+self.request_id+'.json') for prefix in ('issued-', 'consumed-', 'result-')]
        paths += [self.evidence/'result.json', self.evidence/'transaction.json']
        for path in paths:
            with self.subTest(path=path.name):
                raw = path.read_bytes(); path.unlink()
                with self.assertRaisesRegex(ValueError, 'Native request or permit'):
                    self.classify()
                path.write_bytes(raw)
        self.assertEqual(self.classify()['status'], 'settled')

    def test_mismatched_request_consumption_receipt_and_completion_refused(self):
        self.settle()
        paths = [self.gate/'request.json', self.gate/('consumed-'+self.request_id+'.json'),
                 self.gate/('result-'+self.request_id+'.json'), self.evidence/'result.json']
        for path in paths:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                if path.name in ('request.json', 'consumed-'+self.request_id+'.json'):
                    path.write_bytes(raw+b' ')
                else:
                    value = json.loads(raw); value['request_sha256' if path.parent == self.gate else 'attempt_id'] = 'f'*64
                    write_json(path, value)
                with self.assertRaisesRegex(ValueError, 'Native request or permit'):
                    self.classify()
                path.write_bytes(raw)
        self.assertEqual(self.classify()['status'], 'settled')

    def test_changed_transaction_owner_and_foreign_database_refused(self):
        self.settle()
        for path, field, value in [(self.evidence/'transaction.json', 'owner', 'f'*64),
                                   (self.evidence/'transaction.json', 'phase', 'installed'),
                                   (self.gate/'controller.json', 'database', str(self.fixture.root/'foreign.sqlite'))]:
            with self.subTest(field=field):
                raw = path.read_bytes(); document = json.loads(raw); document[field] = value; write_json(path, document)
                with self.assertRaisesRegex(ValueError, 'Native request or permit'):
                    self.classify()
                path.write_bytes(raw)

    def test_unresolved_job_and_wrong_completion_path_refused(self):
        self.settle()
        original = self.c.state()['queue']
        for field, value in [('status', 'verifying'), ('completion_path', str(self.fixture.root/'foreign-result.json'))]:
            jobs = json.loads(packed(original)); jobs[0][field] = value
            self.c.store.db.execute('UPDATE studio_queues SET jobs=?', (packed(jobs),))
            with self.assertRaisesRegex(ValueError, 'Native request or permit'):
                self.classify()
        self.c.store.db.execute('UPDATE studio_queues SET jobs=?', (packed(original),))
        self.assertEqual(self.classify()['status'], 'settled')


if __name__ == '__main__':
    unittest.main()
