"""Real native batch serialization/queue tests using private synthetic terminals."""
import json
from pathlib import Path
import unittest

import test_goat_studio as fixtures
from unittest.mock import patch
import studio_batch
from campaign_ledger import packed, sha
from studio_batch import prepare_batch, save_batch, load_batch, batch_status, resume_batch


class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.controller = self.fixture.bound(); self.fixture.grant(self.controller)
        self.root = self.fixture.root
        self.source = self.root / 'Template.set'
        self.source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        self.spec = dict(schema_version=1, export=self.fixture.exports,
            members=[dict(set_path=str(self.source), tester=self.fixture.tester | {'Symbol': symbol})
                     for symbol in ('EURUSD.customer', 'GBPUSD.customer')])

    def tearDown(self): self.fixture.tearDown()

    def prepare(self, name='customer-batch'):
        file = self.root / (name + '.json'); file.write_text(json.dumps(self.spec), encoding='utf-8')
        return prepare_batch(self.controller, name, file)

    def test_real_native_batch_has_two_members_and_one_dispatch(self):
        result = self.prepare(); package = Path(result['package'])
        self.assertEqual(result['member_count'], 2)
        self.assertFalse(result['native_started'])
        self.assertEqual(len(self.controller.state()['queue']), 1)
        native = (package / 'queue.GOAT').read_bytes().decode('utf-16')
        self.assertEqual(native.count(';Pending_'), 2)
        manifest = json.loads((package / 'manifest.json').read_text())
        self.assertEqual(len({job['run_alias'] for job in manifest['jobs']}), 2)
        self.assertEqual(batch_status(self.controller, 'customer-batch')['member_count'], 2)
        self.assertEqual(list(self.fixture.common.iterdir()), [])

    def test_invalid_second_member_does_not_enqueue_anything(self):
        self.spec['members'][1]['tester']['Model'] = 99
        with self.assertRaisesRegex(ValueError, 'Model'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_duplicate_members_are_refused(self):
        self.spec['members'][1] = self.spec['members'][0]
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_retry_reuses_exact_batch_and_changed_settings_refuse(self):
        self.prepare(); self.assertTrue(self.prepare()['reused'])
        self.spec['members'][1]['tester']['Deposit'] = 20000
        with self.assertRaisesRegex(ValueError, 'different members'): self.prepare()

    def test_save_and_load_native_goatbatch_preserves_members_and_settings(self):
        self.prepare(); output = self.root / 'Saved customer batch.goatbatch'
        save_batch(self.controller, 'customer-batch', output)
        result = load_batch(self.controller, 'loaded-batch', output)
        self.assertEqual(result['member_count'], 2)
        before = self.controller.job('customer-batch')['configuration']['batch_members']
        after = self.controller.job('loaded-batch')['configuration']['batch_members']
        for expected, actual in zip(before, after):
            self.assertEqual(expected['tester'], actual['tester'])
            self.assertEqual(expected['export'], actual['export'])
            self.assertEqual(expected['strategy']['values']['Lots'], actual['strategy']['values']['Lots'])
        with self.assertRaises(FileExistsError): save_batch(self.controller, 'customer-batch', output)

    def test_save_cannot_modify_controller_immutable_package(self):
        result = self.prepare(); output = Path(result['package']) / 'saved.goatbatch'
        with self.assertRaisesRegex(ValueError, 'outside controller state'):
            save_batch(self.controller, 'customer-batch', output)
        self.assertFalse(output.exists())
        self.assertTrue(self.prepare()['reused'])

    def test_without_human_grant_no_batch_is_enqueued(self):
        state = self.controller.state()
        self.controller.store.submit(dict(schema_version=1, request_id='takeover-test', terminal_id=self.controller.terminal,
            run_id=self.controller.run, expected_revision=state['revision'], generation=state['generation'],
            command='control.takeover', payload={}), actor='human')
        with self.assertRaisesRegex(ValueError, 'controller required'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_deep_native_validation_failure_cannot_publish_queue(self):
        self.spec['members'][1]['tester']['Symbol'] = 'BROKER#SYMBOL'
        with self.assertRaisesRegex(ValueError, 'Unsafe native config token'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_native_path_budget_failure_cannot_publish_queue(self):
        self.spec['members'][1]['tester']['Symbol'] = 'A' * 200
        with self.assertRaisesRegex(ValueError, 'path budget'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_staging_io_failure_keeps_no_pending_job(self):
        with patch.object(studio_batch, 'prepare', side_effect=OSError('simulated disk failure')):
            with self.assertRaisesRegex(OSError, 'simulated'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_ownership_change_during_staging_cannot_enqueue(self):
        original = studio_batch.prepare
        def race(*args):
            result = original(*args)
            state = self.controller.state()
            self.controller.store.submit(dict(schema_version=1, request_id='human-race', terminal_id=self.controller.terminal,
                run_id=self.controller.run, expected_revision=state['revision'], generation=state['generation'],
                command='control.takeover', payload={}), actor='human')
            return result
        with patch.object(studio_batch, 'prepare', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'publication was not confirmed'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])
        self.assertTrue((self.controller.root / 'packages/customer-batch/manifest.json').is_file())

    def test_retry_and_save_refuse_every_changed_immutable_artifact(self):
        result = self.prepare(); package = Path(result['package'])
        for name in ('manifest.json', 'studio-plan.json', 'queue.GOAT', 'portfolio.goatbatch', result['manifest']['jobs'][1]['run_alias'] + '.set'):
            target = package / name; original = target.read_bytes()
            target.write_bytes(original + (b' ' if name.endswith('.json') else b'\x00'))
            with self.assertRaises((ValueError, UnicodeError)): self.prepare()
            with self.assertRaises((ValueError, UnicodeError)): save_batch(self.controller, 'customer-batch', self.root / 'should-not-exist.goatbatch')
            target.write_bytes(original)
        self.assertFalse((self.root / 'should-not-exist.goatbatch').exists())

    def test_large_plan_and_duplicate_json_are_bounded_explicitly(self):
        plan = self.root / 'padded-plan.json'
        plan.write_text(' ' * 2_000_001 + json.dumps(self.spec), encoding='utf-8')
        result = prepare_batch(self.controller, 'larger-plan', plan)
        self.assertEqual(result['member_count'], 2)
        bad = self.root / 'duplicate-plan.json'
        bad.write_text('{"schema_version":1,"schema_version":1,"export":{},"members":[]}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate batch JSON'): prepare_batch(self.controller, 'duplicate-plan', bad)

    def test_retained_input_budget_rejects_before_queue_mutation(self):
        with patch.object(studio_batch, 'MAX_RETAINED_SET_BYTES', 1):
            with self.assertRaisesRegex(ValueError, '128 MiB'): self.prepare()
        self.assertEqual(self.controller.state()['queue'], [])

    def test_legacy_saved_sequence_default_is_true_and_disclosed(self):
        self.prepare(); output = self.root / 'legacy.goatbatch'
        save_batch(self.controller, 'customer-batch', output)
        text = output.read_bytes().decode('utf-16').replace('IncludeSequenceData=0\r\n', '')
        output.write_bytes(text.encode('utf-16'))
        result = load_batch(self.controller, 'legacy-loaded', output)
        self.assertTrue(self.controller.job('legacy-loaded')['configuration']['export']['IncludeSequenceData'])
        self.assertIn('additional capture time', result['warnings'][0])

    def test_cancelled_unstarted_batch_can_prepare_all_remaining_members(self):
        self.prepare(); self.controller.cancel('customer-batch')
        result = resume_batch(self.controller, 'customer-batch', 'remaining-batch')
        self.assertEqual(result['member_count'], 2)
        self.assertFalse(result['native_started'])
        self.assertEqual(self.controller.job('customer-batch')['status'], 'cancelled')

    def started_fixture(self, states):
        # Synthetic completed attempt: real native queue and input observation,
        # with no terminal process, activation, or execution authorization.
        self.spec['members'] = [dict(set_path=str(self.source), tester=self.fixture.tester | {'Symbol': 'PAIR' + str(index)})
                                for index in range(len(states))]
        result = self.prepare(); package = Path(result['package']); manifest = result['manifest']
        run = self.fixture.common / manifest['native_run_relative'].replace('\\', '/')
        run.mkdir(parents=True)
        blocks = (package / 'queue.GOAT').read_bytes().decode('utf-16').split('\x1f')
        for index, (state, member) in enumerate(zip(states, manifest['jobs'])):
            blocks[index] = blocks[index].replace(';Pending_', ';' + state + '_', 1)
            destination = run / 'inputs' / member['run_alias']; destination.mkdir(parents=True)
            (destination / 'Inputs.GOAT').write_bytes((package / (member['run_alias'] + '.set')).read_bytes())
        (run / 'queue.GOAT').write_bytes('\x1f'.join(blocks).encode('utf-16'))
        original = self.controller.job('customer-batch')
        original['status'] = 'failed'
        original['launch_intent'] = {'package_sha256': studio_batch.hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest()}
        return original, run

    def test_started_remaining_selection_skips_complete_and_opts_into_errors(self):
        original, _ = self.started_fixture(['Completed', 'Cancelled', 'Error'])
        with patch.object(self.controller, 'job', return_value=original):
            selected = resume_batch(self.controller, 'customer-batch', 'remaining-only')
            with_errors = resume_batch(self.controller, 'customer-batch', 'remaining-and-errors', include_failed=True)
        self.assertEqual(selected['member_count'], 1)
        self.assertEqual(with_errors['member_count'], 2)
        self.assertEqual([m['tester']['Symbol'] for m in self.controller.job('remaining-only')['configuration']['batch_members']], ['PAIR1'])
        self.assertEqual([m['tester']['Symbol'] for m in self.controller.job('remaining-and-errors')['configuration']['batch_members']], ['PAIR1', 'PAIR2'])

    def test_started_remaining_requires_stopped_complete_member_evidence(self):
        original, run = self.started_fixture(['Completed', 'OnGoing'])
        with patch.object(self.controller, 'job', return_value=original):
            with self.assertRaisesRegex(ValueError, 'remains unresolved'):
                resume_batch(self.controller, 'customer-batch', 'unresolved')
            queue = run / 'queue.GOAT'; queue.unlink()
            with self.assertRaisesRegex(ValueError, 'Complete per-member'):
                resume_batch(self.controller, 'customer-batch', 'missing-evidence')
        self.assertEqual(len(self.controller.state()['queue']), 1)

    def test_started_remaining_refuses_native_second_member_input_drift(self):
        original, run = self.started_fixture(['Completed', 'Cancelled'])
        inputs = sorted((run / 'inputs').glob('*/Inputs.GOAT'))[-1]
        inputs.write_bytes(inputs.read_bytes() + b'\0')
        with patch.object(self.controller, 'job', return_value=original):
            with self.assertRaisesRegex(ValueError, 'strategy input drift'):
                resume_batch(self.controller, 'customer-batch', 'changed-input')
        self.assertEqual(len(self.controller.state()['queue']), 1)

    def test_saved_loaded_batch_discards_foreign_execution_states_and_paths(self):
        self.prepare(); output = self.root / 'foreign-state.goatbatch'; save_batch(self.controller, 'customer-batch', output)
        text = output.read_bytes().decode('utf-16').replace(';Pending_', ';Completed_').replace('Server=Customer-Demo', 'Server=Foreign-Live')
        output.write_bytes(text.encode('utf-16'))
        result = load_batch(self.controller, 'fresh-import', output)
        self.assertFalse(result['native_started']); self.assertEqual(self.controller.job('fresh-import')['status'], 'pending')
        plan = json.loads((Path(result['package']) / 'studio-plan.json').read_text())
        self.assertEqual(plan['research_binding']['account_server'], 'Customer-Demo')



if __name__ == '__main__': unittest.main()
