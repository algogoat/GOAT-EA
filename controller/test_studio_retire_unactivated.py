"""retire-unactivated: a start refused before MT5 was touched settles to cancelled.

Real controller store and prepared native package; no MT5 process. The g6-r1 shape
(2026-10-03): reservation + launch intent + restart phase 'prepared', no attempt
folder, no controls, nothing issued.
"""
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed, sha
from studio_batch import prepare_batch, resume_batch
from studio_launch_intent import record_intent
from studio_retire_unactivated import retire, proof, unactivated_hint, KIND
import studio_research_status


IDLE = ({'runtime': dict(tester_state='idle', batch_ongoing=False, account_demo=True)}, {})


class RetireUnactivatedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        c = self.c = self.fixture.bound(); self.fixture.grant(c)
        source = self.fixture.root / 'Template.set'
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        spec = dict(schema_version=1, export=self.fixture.exports,
                    members=[dict(set_path=str(source), tester=self.fixture.tester | {'Symbol': symbol})
                             for symbol in ('EURUSD.customer', 'GBPUSD.customer', 'USDJPY.customer')])
        plan = self.fixture.root / 'plan.json'; plan.write_text(json.dumps(spec), encoding='utf-8')
        prepare_batch(c, 'g6-r1', plan)
        self.package = c.root / 'packages' / 'g6-r1'
        self.runtime = patch.object(c, 'runtime', return_value=IDLE)
        self.runtime.start(); self.addCleanup(self.runtime.stop)

    def unactivated(self, phase='prepared'):
        """Reserve, record the launch intent and the 'prepared' restart phase, as config start does."""
        c = self.c
        job = c.job('g6-r1')
        digest = hashlib.sha256((self.package / 'manifest.json').read_bytes()).hexdigest()
        c.submit('queue.reserve', dict(job_id='g6-r1', configuration_sha256=job['configuration_sha256'],
                                       package_sha256=digest), 'g6-r1-reserve')
        state = c.state()
        intent = record_intent(c.store, c.terminal, c.run, 'g6-r1', self.package, actor='agent',
                               revision=state['revision'], generation=state['generation'])
        state = c.state()
        current = next(row for row in state['queue'] if row['job_id'] == 'g6-r1')
        if phase is not None:
            current['restart_intent'] = dict(attempt_id=intent['attempt_id'], phase=phase,
                                             history=[dict(phase=phase, at=time.time())])
        current['status'] = 'reconcile_required'
        binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
        with c.store.transaction():
            c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
            c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
        drivers = c.root / 'batch-drivers'; drivers.mkdir(exist_ok=True)
        (drivers / 'g6-r1.json').write_text(json.dumps(dict(
            schema_version=2, binding=dict(job_id='g6-r1'), status='stop_unconfirmed', start_issued=True,
            attempt_id=intent['attempt_id'], cancel_issued=True, stopped=False, last_wall=time.time(),
            last_error='Process baseline is stale or future-dated')))
        return intent['attempt_id']

    def test_retires_never_activated_start_to_cancelled_with_journal_and_is_idempotent(self):
        attempt = self.unactivated()
        folder = self.c.root / 'demo-agent'; folder.mkdir(); (folder / 'STOP').write_text('{"actor":"demo_agent"}')
        result = retire(self.c, 'g6-r1')
        self.assertEqual((result['status'], result['kind'], result['executed_members']), ('cancelled', KIND, 0))
        self.assertFalse(result['native_cancellation_claimed'])
        job = self.c.job('g6-r1')
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(job['launch_intent']['attempt_id'], attempt)        # evidence kept
        self.assertEqual(job['restart_intent']['phase'], 'prepared')
        self.assertEqual(json.loads(Path(result['result_path']).read_text())['proof']['folders']['native_queue'],
                         'native_evidence_missing')
        journal = json.loads((self.c.root / 'batch-drivers/g6-r1.json').read_text())
        self.assertEqual((journal['stopped'], journal['status']), (True, 'cancelled'))
        self.assertTrue(list((self.c.root / 'batch-driver-refusals').glob('g6-r1.before-retire-*.json')))
        again = retire(self.c, 'g6-r1')
        self.assertTrue(again['reused']); self.assertEqual(again['result_path'], result['result_path'])
        self.assertFalse((self.c.root / 'attempts' / attempt).exists())

    def test_retired_batch_prepares_every_member_again_under_a_new_id(self):
        self.unactivated(); retire(self.c, 'g6-r1')
        result = resume_batch(self.c, 'g6-r1', 'g6-r1b')
        self.assertEqual(result['member_count'], 3)
        self.assertEqual(self.c.job('g6-r1b')['status'], 'pending')

    def test_intent_without_restart_phase_also_retires(self):
        self.unactivated(phase=None)
        self.assertEqual(retire(self.c, 'g6-r1')['status'], 'cancelled')

    def test_refuses_once_controls_may_have_been_installed(self):
        self.unactivated(phase='controls_installed')
        with self.assertRaisesRegex(ValueError, 'may have touched MT5'):
            retire(self.c, 'g6-r1')
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_when_activation_evidence_exists(self):
        attempt = self.unactivated()
        (self.c.root / 'attempts' / attempt).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Activation evidence exists'):
            retire(self.c, 'g6-r1')
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_any_gate_file_naming_the_attempt_or_its_cancel(self):
        attempt = self.unactivated()
        gate = self.c.local / 'native-gate'
        for name in ('issued-' + attempt + '.json', 'arm-intent-' + attempt + '.json',
                     'issued-' + sha([attempt, 'cancel']) + '.json'):
            (gate / name).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'names this attempt'):
                retire(self.c, 'g6-r1')
            (gate / name).unlink()
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_a_current_request_or_orphan_permit(self):
        self.unactivated()
        gate = self.c.local / 'native-gate'
        (gate / 'request.json').write_text(json.dumps(dict(request_id='f' * 64, job_id='g6-r1')))
        with self.assertRaisesRegex(ValueError, 'current native request belongs'):
            retire(self.c, 'g6-r1')
        (gate / 'request.json').write_text(json.dumps(dict(request_id='f' * 64, job_id='other-job')))
        with self.assertRaises(Exception):  # must be a durable, consumed request of a settled job
            retire(self.c, 'g6-r1')
        (gate / 'request.json').unlink(); (gate / 'permit.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'permit exists without its request'):
            retire(self.c, 'g6-r1')
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_any_native_run_folder(self):
        self.unactivated()
        manifest = json.loads((self.package / 'manifest.json').read_text())
        run = self.fixture.common / manifest['native_run_relative'].replace('\\', '/')
        run.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'native run folder exists'):
            retire(self.c, 'g6-r1')
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_when_this_attempt_owns_native_controls(self):
        attempt = self.unactivated()
        from studio_terminal_isolation import controller_base
        base = controller_base(self.c); base.mkdir(parents=True, exist_ok=True)
        (base / 'agent-native-control-owner.json').write_text(json.dumps(dict(owner=attempt)))
        with self.assertRaisesRegex(ValueError, 'owns the native controls'):
            retire(self.c, 'g6-r1')

    def test_refuses_without_fresh_idle_ea_sample(self):
        self.unactivated()
        self.c.runtime.side_effect = ValueError('Runtime policy mismatch: batch_ongoing')
        with self.assertRaisesRegex(ValueError, 'idle with no batch running'):
            retire(self.c, 'g6-r1')
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_refuses_human_takeover(self):
        self.unactivated()
        state = self.c.state()
        self.c.store.submit(dict(schema_version=1, request_id='take', terminal_id=self.c.terminal, run_id=self.c.run,
                                 expected_revision=state['revision'], generation=state['generation'],
                                 command='control.takeover', payload={}), actor='human')
        with self.assertRaises(ValueError):
            retire(self.c, 'g6-r1')

    def test_refuses_pending_and_finished_jobs(self):
        with self.assertRaisesRegex(ValueError, 'no unactivated start'):
            retire(self.c, 'g6-r1')

    def test_research_status_names_the_dead_start_instead_of_running(self):
        self.unactivated()
        job = self.c.job('g6-r1')
        self.assertTrue(unactivated_hint(self.c.root, job))
        session = json.loads((self.c.root / 'session.json').read_text())
        status = studio_research_status.research_status(root=self.c.root, install=self.c.install, session=session,
                                                        local=self.c.local, now=time.time(), jobs=[job])
        self.assertEqual(status['activity']['status'], 'start_failed_unactivated')
        self.assertIn('retire-unactivated --batch-id g6-r1', status['activity']['headline'])
        self.assertNotIn('Running', status['activity']['headline'])

    def test_driver_settles_its_own_refused_start(self):
        from studio_batch_driver import _retire_if_unactivated
        attempt = self.unactivated()
        path = self.c.root / 'batch-drivers/g6-r1.json'
        record = json.loads(path.read_text()) | dict(status='start_uncertain', stopped=False)
        result = _retire_if_unactivated(self.c, 'g6-r1', record, path, time)
        self.assertEqual(result['attempt_id'], attempt)
        saved = json.loads(path.read_text())
        self.assertEqual((saved['stopped'], saved['status'], saved['retired']), (True, 'cancelled', KIND))
        self.assertEqual(self.c.job('g6-r1')['status'], 'cancelled')

    def test_driver_keeps_start_uncertain_when_proof_fails(self):
        from studio_batch_driver import _retire_if_unactivated
        attempt = self.unactivated()
        (self.c.root / 'attempts' / attempt).mkdir(parents=True)
        path = self.c.root / 'batch-drivers/g6-r1.json'
        record = json.loads(path.read_text()) | dict(status='start_uncertain', stopped=False)
        self.assertIsNone(_retire_if_unactivated(self.c, 'g6-r1', record, path, time))
        saved = json.loads(path.read_text())
        self.assertEqual(saved['status'], 'start_uncertain')
        self.assertIn('Activation evidence exists', saved['retire_unactivated_refused'])


if __name__ == '__main__':
    unittest.main()
