"""Pending queue cleanup is atomic, owned and does not reset native execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed
from studio_batch import prepare_batch
from studio_bridge import write_json
from studio_queue_clear import clear_queue, recovery_status


class ClearQueueTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.c = self.fixture.bound(); self.fixture.grant(self.c); self.fixture.prepare(self.c)

    def tearDown(self):
        self.fixture.tearDown()

    def replace_jobs(self, jobs, binding=None):
        binding = binding or packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', (binding, packed(jobs)))

    def test_preview_is_read_only_and_apply_preserves_history_packages_and_fresh_batch(self):
        original = self.c.state()['queue'][0]
        history = [dict(copy.deepcopy(original), job_id='old-'+status, status=status,
                        completion={'evidence': 'retained'})
                   for status in ('completed','failed','cancelled','removed','superseded')]
        self.replace_jobs([original, *history])
        before = self.c.state()
        files = {str(p):p.read_bytes() for p in (self.c.root/'packages').rglob('*') if p.is_file()}
        preview = clear_queue(self.c)
        self.assertEqual(self.c.state(), before)
        self.assertEqual(preview['pending_job_ids'], ['beta-job'])
        result = clear_queue(self.c, apply=True, request_id='clear-one', expected_revision=preview['expected_revision'])
        self.assertFalse(result['execution_effect'])
        state = self.c.state()
        self.assertEqual(state['queue'][0], dict(original, status='removed'))
        self.assertEqual(state['queue'][1:], history)
        self.assertEqual(state['revision'], before['revision']+1)
        for path, content in files.items(): self.assertEqual(Path(path).read_bytes(), content)
        self.assertEqual(clear_queue(self.c, apply=True, request_id='clear-one', expected_revision=preview['expected_revision']), result)
        self.assertEqual(self.c.state(), state)
        plan = self.fixture.root/'new-batch.json'
        plan.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports,
            members=[dict(set_path=str(self.fixture.root/'strategy.set'), tester=self.fixture.tester)])))
        prepared = prepare_batch(self.c, 'fresh-batch', plan)
        self.assertFalse(prepared['native_started'])
        self.assertEqual(self.c.state()['queue'][-1]['status'], 'pending')
        self.assertEqual(list(self.fixture.common.iterdir()), [])

    def test_stale_preview_or_revoked_agent_cannot_clear(self):
        preview = clear_queue(self.c)
        self.c.submit('queue.enqueue', {'job_id':'new-pending'}, 'append-pending')
        before = self.c.state()
        with self.assertRaisesRegex(ValueError, 'Stale state revision'):
            clear_queue(self.c, apply=True, request_id='stale', expected_revision=preview['expected_revision'])
        self.assertEqual(self.c.state(), before)
        self.c.store.submit(dict(schema_version=1, request_id='takeover', terminal_id=self.c.terminal,
            run_id=self.c.run, expected_revision=before['revision'], generation=before['generation'],
            command='control.takeover', payload={}), actor='human')
        before = self.c.state()
        with self.assertRaisesRegex(ValueError, 'Current controller'):
            clear_queue(self.c, apply=True, request_id='revoked', expected_revision=before['revision'])
        self.assertEqual(self.c.state(), before)

    def test_unresolved_jobs_across_bindings_block_atomically(self):
        original = self.c.state()['queue'][0]
        for index, status in enumerate(('reserved','starting','running','verifying','reconcile_required','unknown')):
            with self.subTest(status=status):
                self.replace_jobs([dict(original, status=status)], 'other-binding')
                before = self.c.state()
                with self.assertRaisesRegex(ValueError, 'Unresolved native'):
                    clear_queue(self.c, apply=True, request_id='active-'+str(index), expected_revision=before['revision'])
                self.assertEqual(self.c.state(), before)

    def test_pending_with_launch_intent_is_not_treated_as_unstarted(self):
        job = self.c.state()['queue'][0]; job['launch_intent'] = {'attempt_id':'retain'}
        self.replace_jobs([job]); before = self.c.state()
        with self.assertRaisesRegex(ValueError, 'Unresolved native'):
            clear_queue(self.c, apply=True, request_id='intent', expected_revision=before['revision'])
        self.assertEqual(self.c.state(), before)

    def test_unconsumed_controls_and_seed_ownership_are_preserved(self):
        before = self.c.state()
        for name in ('permit.json','request.json'):
            path = self.c.local/'native-gate'/name; path.write_bytes(b'preserve exact native evidence')
            with self.assertRaisesRegex(ValueError, 'Native request or permit'):
                clear_queue(self.c, apply=True, request_id='control-'+name.replace('.', '-'), expected_revision=before['revision'])
            self.assertEqual(path.read_bytes(), b'preserve exact native evidence')
            self.assertEqual(self.c.state(), before)
            path.unlink()
        seed = self.c.root/'seed-active.json'; write_json(seed, {'status':'active'})
        with self.assertRaisesRegex(ValueError, 'Seed runner owns'):
            clear_queue(self.c, apply=True, request_id='seed-blocked', expected_revision=before['revision'])
        self.assertEqual(self.c.state(), before)
        self.assertEqual(json.loads(seed.read_text()), {'status':'active'})

    def test_identity_and_revision_validation_and_discoverable_cli(self):
        for request, revision in [(None, 0), ('../escape', 0), ('safe', None), ('safe', -1), ('safe', True)]:
            with self.assertRaises(ValueError):
                clear_queue(self.c, apply=True, request_id=request, expected_revision=revision)
        before = self.c.state()
        args = [sys.executable, 'goat_studio.py', '--installation', str(self.fixture.path)]
        folder = Path(__file__).parent
        discovered = subprocess.run([*args, 'discover'], cwd=folder, capture_output=True, text=True, check=True)
        self.assertIn('clear-queue', json.loads(discovered.stdout)['result']['operation_contracts'])
        preview = subprocess.run([*args, 'clear-queue'], cwd=folder, capture_output=True, text=True, check=True)
        revision = json.loads(preview.stdout)['result']['expected_revision']
        applied = subprocess.run([*args, 'clear-queue', '--apply', '--request-id', 'cli-clear',
                                  '--expected-revision', str(revision)], cwd=folder, capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(applied.stdout)['ok'])
        self.assertEqual(self.c.state()['queue'][0]['status'], 'removed')
        self.assertEqual(self.c.state()['revision'], before['revision']+1)
        with self.assertRaisesRegex(ValueError, 'revision changed'):
            clear_queue(self.c, apply=True, request_id='cli-clear', expected_revision=revision+1)

    def test_orphan_diagnosis_never_claims_reset_supported_or_changes_state(self):
        observation = {'runtime': {'batch_ongoing': True, 'tester_state': 'idle'}}
        before = self.c.state()
        with patch('studio_resilient_read.read_observation', return_value=(observation, 1)), \
             patch.object(self.c, 'runtime', return_value=(observation, {})), \
             patch('studio_process_check.inspect_processes'):
            result = recovery_status(self.c)
            self.assertEqual(result['status'], 'possible_orphan_unqualified')
            self.assertFalse(result['orphan_recovery_supported'])
            self.assertFalse(result['execution_effect'])
            self.assertEqual(self.c.state(), before)
            self.assertEqual(list(self.fixture.common.iterdir()), [])
            (self.c.local/'native-gate/permit.json').write_text('retain')
            self.assertEqual(recovery_status(self.c)['status'], 'inspection')
            self.assertEqual((self.c.local/'native-gate/permit.json').read_text(), 'retain')

    def test_legacy_runtime_mismatch_and_active_controls_are_reported(self):
        observation = {'runtime': {'batch_ongoing': True}}
        native = self.fixture.common/'GOAT'/'GOAT V1.48-Customer-Demo'
        native.mkdir(parents=True)
        owner = native/'agent-native-control-owner.json'; owner.write_text('{"retained":true}')
        with patch('studio_resilient_read.read_observation', return_value=(observation, 1)), \
             patch.object(self.c, 'runtime', side_effect=ValueError('Runtime program_path mismatch')), \
             patch('studio_process_check.inspect_processes', side_effect=ValueError('Unmapped terminal')):
            result = recovery_status(self.c)
        self.assertEqual(result['status'], 'inspection')
        self.assertIsNone(result['runtime'])
        self.assertIn('Runtime inspection: Runtime program_path mismatch', result['blockers'])
        self.assertIn('agent-native-control-owner.json', result['present_native_controls'])
        self.assertEqual(owner.read_text(), '{"retained":true}')


if __name__ == '__main__': unittest.main()
