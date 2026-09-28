"""One-use owner maintenance authorization; all native observations are fixtures."""
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import apply, review, paths, database_view, load_plan
from studio_installation import read_json
from studio_owner_maintenance import prepare, directory, read_record
import test_studio_owner_research as owner_fixtures


class OwnerMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = owner_fixtures.OwnerResearchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c = self.fixture.c
        self.c.store.db.execute('DELETE FROM studio_queues')
        self.policy = self.fixture.policy
        self.policy['operations'].append('owner-maintenance-prepare')
        self.policy['maintenance'] = dict(target_ea_sha256='9'*64, plan_sha256='a'*64, max_seconds=14400)
        write_json(self.fixture.policy_path, self.policy)
        patch('studio_owner_maintenance.POLICY_PATH', self.fixture.policy_path).start()
        patch('studio_handover.stopped').start()

    def mint(self):
        value = prepare(self.c)
        self.record_id = value['record_id']
        return value

    def stop(self):
        repair = self.c.root/'monitor-repairs'
        repair.mkdir(exist_ok=True)
        write_json(repair/'owner-stop.json', dict(stop_only=True, phase='stopped',
                   installation_sha256=sha(self.c.install), session_sha256=sha(self.c.session),
                   native=self.fixture.native))
        self.c.store.close()
        self.c.store = None

    def test_mint_binds_exact_original_grant_target_plan_new_session_and_short_expiry(self):
        before = self.c.state()
        result = self.mint()
        _, record = read_record(self.c, result['record_id'])
        self.assertEqual(self.c.state(), before)
        self.assertEqual(record['original_grant_payload_hash'], self.policy['grant_payload_hash'])
        self.assertEqual(record['target_ea_sha256'], '9'*64)
        self.assertNotEqual(record['replacement_run_id'], self.c.run)
        self.assertLessEqual(record['expires_utc']-record['created_utc'], 14400)
        with self.assertRaisesRegex(ValueError, 'never mint another'):
            prepare(self.c)

    def test_park_consumes_one_record_preserves_files_and_does_not_grant(self):
        result = self.mint()
        self.stop()
        review_id = review(self.c)['review_id']
        result = apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertEqual(result['status'], 'complete')
        root = directory(self.c)/self.record_id
        self.assertTrue((root/'park-intent.json').is_file())
        self.assertFalse(read_json(root/'parked.json')['grants_control'])
        self.assertEqual([p.name for p in self.c.root.iterdir()], ['installation.json'])
        old = paths(self.c)[2]/review_id/'state/studio.sqlite'
        self.assertEqual(database_view(old)['states'][0][3], 'human')
        self.assertEqual(apply(self.c, review_id, owner_maintenance=self.record_id), result)

    def test_revocation_or_new_work_after_mint_permanently_retires_chain(self):
        self.mint()
        self.c.store.db.execute("UPDATE studio_state SET owner='human', generation=generation+1")
        self.stop()
        review_id = review(self.c)['review_id']
        with self.assertRaisesRegex(ValueError, 'permanently revoked'):
            apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertTrue((directory(self.c)/self.record_id/'revoked.json').is_file())

    def test_pending_takeover_after_review_cancels_chain_even_if_removed_later(self):
        self.mint()
        self.stop()
        review_id = review(self.c)['review_id']
        takeover = self.c.bridge.root/'human/inbox/takeover.json'
        takeover.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'permanently revoked'):
            apply(self.c, review_id, owner_maintenance=self.record_id)
        takeover.unlink()
        with self.assertRaisesRegex(ValueError, 'permanently revoked'):
            apply(self.c, review_id, owner_maintenance=self.record_id)

    def test_wrong_or_missing_original_stop_and_expired_record_refuse_without_park(self):
        self.mint()
        self.c.store.close(); self.c.store = None
        review_id = review(self.c)['review_id']
        with self.assertRaisesRegex(ValueError, 'verified stop'):
            apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertEqual(load_plan(self.c, review_id)['status'], 'review')
        _, record = read_record(self.c, self.record_id)
        with patch('studio_owner_maintenance.time.time', return_value=record['expires_utc']+1):
            with self.assertRaisesRegex(ValueError, 'expired'):
                apply(self.c, review_id, owner_maintenance=self.record_id)

    def test_changed_account_build_policy_or_record_cannot_authorize_park(self):
        self.mint()
        self.stop()
        review_id = review(self.c)['review_id']
        record_path = directory(self.c)/self.record_id/'record.json'
        original = read_json(record_path)
        for key, value in [('target_ea_sha256','b'*64), ('original_run_id','other'),
                           ('binding_sha256','b'*64), ('original_generation',3),
                           ('plan_sha256','c'*64)]:
            with self.subTest(key=key):
                write_json(record_path, original|{key:value})
                with self.assertRaisesRegex(ValueError, 'exact policy'):
                    apply(self.c, review_id, owner_maintenance=self.record_id)
        write_json(record_path, original)
        with self.assertRaisesRegex(ValueError, 'one explicit'):
            apply(self.c, review_id, True, owner_maintenance=self.record_id)

    def test_crash_after_ownership_revocation_resumes_exact_intent_only(self):
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        with patch('studio_handover.move_once', side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertEqual(load_plan(self.c, review_id)['status'], 'parking')
        self.assertEqual(apply(self.c, review_id, owner_maintenance=self.record_id)['status'], 'complete')

    def test_no_remint_after_expiry_or_revocation(self):
        self.mint()
        write_json(directory(self.c)/self.record_id/'revoked.json', {'reason':'test takeover'})
        with self.assertRaisesRegex(ValueError, 'never mint another'):
            prepare(self.c)

    def test_terminal_restart_prevents_park_before_consuming_record(self):
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        with patch('studio_handover.stopped', side_effect=ValueError('selected terminal still running')):
            with self.assertRaisesRegex(ValueError, 'still running'):
                apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertFalse((directory(self.c)/self.record_id/'park-intent.json').exists())

    def test_record_cannot_change_planned_session_or_proof_after_mint(self):
        self.mint()
        path = directory(self.c)/self.record_id/'record.json'
        record = read_json(path)
        write_json(path, record|dict(replacement_run_id='session-'+'f'*32))
        with self.assertRaisesRegex(ValueError, 'Immutable'):
            read_record(self.c, self.record_id)

    def test_expired_park_review_does_not_consume_maintenance(self):
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        plan = load_plan(self.c, review_id)
        with patch('studio_owner_maintenance.time.time', return_value=plan['expires_at']+1):
            with self.assertRaisesRegex(ValueError, 'review expired'):
                apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertFalse((directory(self.c)/self.record_id/'park-intent.json').exists())

    def test_crash_after_terminal_archive_publication_resumes_same_record(self):
        from studio_handover import move_once
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        def interrupted(source, target, expected):
            move_once(source, target, expected)
            if source == self.c.local:
                raise OSError('after publication')
        with patch('studio_handover.move_once', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'after publication'):
                apply(self.c, review_id, owner_maintenance=self.record_id)
        self.assertEqual(apply(self.c, review_id, owner_maintenance=self.record_id)['status'], 'complete')

    def test_expired_started_park_reconciles_but_cannot_authorize_another_step(self):
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        _, record = read_record(self.c,self.record_id)
        with patch('studio_handover.move_once',side_effect=OSError('interrupt')):
            with self.assertRaises(OSError): apply(self.c,review_id,owner_maintenance=self.record_id)
        with patch('studio_owner_maintenance.time.time',return_value=record['expires_utc']+1):
            self.assertEqual(apply(self.c,review_id,owner_maintenance=self.record_id)['status'],'complete')
            with self.assertRaisesRegex(ValueError,'expired'):
                read_record(self.c,self.record_id)

    def test_single_intent_contains_stop_and_retry_after_publication_is_exact(self):
        from studio_owner_maintenance import retain
        self.mint(); self.stop()
        review_id = review(self.c)['review_id']
        def interrupt(path,raw):
            retain(path,raw)
            if path.name=='park-intent.json': raise OSError('intent published')
        with patch('studio_owner_maintenance.retain',side_effect=interrupt):
            with self.assertRaises(OSError): apply(self.c,review_id,owner_maintenance=self.record_id)
        intent=read_json(directory(self.c)/self.record_id/'park-intent.json')
        self.assertIn('stop',intent)
        self.assertEqual(apply(self.c,review_id,owner_maintenance=self.record_id)['status'],'complete')


if __name__ == '__main__':
    unittest.main()
