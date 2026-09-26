"""Windows filesystem/SQLite handover tests; no broker or tester is launched."""
import json
import os
from pathlib import Path
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from goat_studio import Controller
from studio_handover import apply, database_view, guard, inspect, load_plan, paths, review, tree
from studio_handover import stopped as inspect_stopped
from studio_bridge import write_json
from test_goat_studio import PortableControllerTests


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PortableControllerTests()
        self.fixture.setUp()
        self.c = self.fixture.bound()
        self.fixture.grant(self.c)
        self.fixture.prepare(self.c)
        self.c.store.close(); self.c.store = None
        self.before = database_view(self.c.root/'studio.sqlite')
        self.process = patch('studio_handover.stopped').start()
        self.addCleanup(patch.stopall)
        # Customer receipts normally live in the controller directory.
        write_json(self.c.root/'installation.json', self.fixture.receipt)
        self.receipt = self.c.root/'installation.json'

    def tearDown(self):
        self.fixture.tearDown()

    def test_park_preserves_pending_research_revokes_control_and_bootstraps_human(self):
        planned = review(self.c)
        self.assertEqual(planned['databases'][0]['counts'], {'pending': 1})
        before_files = tree(self.c.local)
        result = apply(self.c, planned['review_id'], True)
        self.assertEqual(result['status'], 'complete')
        _, _, archive, _ = paths(self.c)
        saved = archive/planned['review_id']
        self.assertEqual(tree(saved/'terminal'), before_files)
        archived = database_view(saved/'state/studio.sqlite')
        self.assertEqual(archived['content'], self.before['content'])
        self.assertEqual(archived['states'][0][3], 'human')
        self.assertEqual(archived['states'][0][2], self.before['states'][0][2]+1)
        self.assertEqual(list(p.name for p in self.c.root.iterdir()), ['installation.json'])
        new = Controller(self.receipt)
        try:
            session = new.bootstrap('123456', 'Customer-Demo')
            self.assertEqual(new.store.snapshot(session['terminal_id'], session['run_id'])['owner'], 'human')
        finally:
            if new.store: new.store.close()
        self.assertEqual(apply(self.c, planned['review_id'], True), result)

    def test_restore_parks_new_work_and_does_not_restore_agent_grant(self):
        first = review(self.c)['review_id']; apply(self.c, first, True)
        new = Controller(self.receipt); new.bootstrap('123456', 'Customer-Demo')
        new.store.close(); new.store = None
        second = review(new, first)['review_id']
        self.assertEqual(apply(new, second, True)['status'], 'complete')
        restored = Controller(self.receipt).open()
        try:
            self.assertEqual(len(restored.state()['queue']), 1)
            self.assertEqual(restored.state()['owner'], 'human')
            self.assertEqual(restored.state()['queue'][0]['status'], 'pending')
        finally: restored.store.close()

    def test_restore_receipt_can_restore_the_session_it_parked(self):
        # A has pending research. Park it, create B, restore A, then restore B
        # using exactly the second receipt ID advertised by the app.
        first = review(self.c)['review_id']; apply(self.c, first, True)
        session_b = Controller(self.receipt)
        session_b.bootstrap('123456', 'Customer-Demo')
        session_b.store.close(); session_b.store = None
        before_b = database_view(session_b.root/'studio.sqlite')
        second = review(session_b, first)['review_id']
        apply(session_b, second, True)
        self.assertEqual(load_plan(session_b, second)['action'], 'restore')
        current_a = Controller(self.receipt).open()
        try:
            self.assertEqual(len(current_a.state()['queue']), 1)
        finally:
            current_a.store.close(); current_a.store = None
        third = review(current_a, second)['review_id']
        self.assertEqual(apply(current_a, third, True)['status'], 'complete')
        restored_b = Controller(self.receipt).open()
        try:
            self.assertEqual(restored_b.state()['queue'], [])
            self.assertEqual(restored_b.state()['owner'], 'human')
            self.assertEqual(database_view(restored_b.root/'studio.sqlite')['content'], before_b['content'])
        finally:
            restored_b.store.close()
        # A remains available under the newest receipt, including its pending job.
        parked_a = database_view(paths(current_a)[2]/third/'state/studio.sqlite')
        self.assertEqual(parked_a['counts'], {'pending': 1})
        self.assertEqual(parked_a['states'][0][3], 'human')

    def test_review_is_read_only_for_research_and_confirmation_is_required(self):
        before = tree(self.c.root), tree(self.c.local)
        plan = review(self.c)
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            apply(self.c, plan['review_id'])
        self.assertEqual(before, (tree(self.c.root), tree(self.c.local)))

    def test_changed_queue_and_expired_review_refuse_before_revocation(self):
        plan = review(self.c)
        with patch('studio_handover.time.time', return_value=plan['expires_at_ms']/1000+1):
            with self.assertRaisesRegex(ValueError, 'expired'):
                apply(self.c, plan['review_id'], True)
        (self.c.root/'new-file').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            apply(self.c, plan['review_id'], True)
        self.assertEqual(database_view(self.c.root/'studio.sqlite'), self.before)

    def test_running_controller_unresolved_native_and_seed_are_blocked(self):
        self.process.side_effect = ValueError('controller running')
        with self.assertRaisesRegex(ValueError, 'controller running'): review(self.c)
        self.process.side_effect = None
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            key, raw = db.execute('SELECT binding,jobs FROM studio_queues').fetchone()
            jobs = json.loads(raw); jobs[0]['status'] = 'reconcile_required'
            db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (json.dumps(jobs),key))
            db.commit()
        with self.assertRaisesRegex(ValueError, 'Unresolved'): review(self.c)
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            jobs[0]['status'] = 'pending'
            db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (json.dumps(jobs),key))
            db.commit()
        write_json(self.c.root/'seed-active.json', {'status':'active'})
        with self.assertRaisesRegex(ValueError, 'Seed runner'): review(self.c)

    def test_two_database_owners_are_both_reviewed(self):
        from studio_command_store import StudioStore
        from studio_native_gate import configure_gate
        external = self.fixture.root/'older.sqlite'
        older = StudioStore(external)
        try:
            older.bind('old-terminal','old-run')
            configure_gate(older, self.c.local/'older/native-gate')
        finally: older.close()
        plan = review(self.c)
        self.assertEqual(len(plan['databases']), 2)
        apply(self.c, plan['review_id'], True)
        self.assertEqual(database_view(external)['states'][0][3], 'human')

    def test_unconsumed_native_request_blocks(self):
        (self.c.local/'native-gate/permit.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'permit'): review(self.c)

    def test_interrupted_directory_move_replays_once_and_fences_bootstrap(self):
        plan = review(self.c)
        original = Path.rename
        moves = []
        def crash_after_move(source, target):
            result = original(source, target); moves.append(str(source))
            if len(moves) == 1: raise OSError('simulated crash after rename')
            return result
        with patch.object(Path, 'rename', crash_after_move):
            with self.assertRaises(OSError): apply(self.c, plan['review_id'], True)
        with self.assertRaisesRegex(ValueError, 'Interrupted'): guard(self.c)
        with self.assertRaisesRegex(ValueError, 'Interrupted'): self.c.bootstrap('123456','Customer-Demo')
        apply(self.c, plan['review_id'], True)
        guard(self.c)
        self.assertEqual(load_plan(self.c, plan['review_id'])['status'], 'complete')

    def test_crash_after_complete_receipt_clears_only_matching_fence(self):
        plan = review(self.c); apply(self.c, plan['review_id'], True)
        archive = paths(self.c)[2]
        write_json(archive/'pending.json', {'review_id':plan['review_id']})
        apply(self.c, plan['review_id'], True)
        guard(self.c)

    def test_crash_after_state_move_can_reopen_original_receipt_for_recovery(self):
        plan = review(self.c)
        original = Path.rename
        def crash(source, target):
            result = original(source, target)
            if source == self.c.root: raise OSError('after state rename')
            return result
        with patch.object(Path, 'rename', crash):
            with self.assertRaises(OSError): apply(self.c, plan['review_id'], True)
        self.assertFalse(self.receipt.exists())
        recovered = Controller(self.receipt)
        apply(recovered, plan['review_id'], True)
        self.assertTrue(self.receipt.exists())
        guard(recovered)

    def test_plan_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'review ID'): apply(self.c, '../escape', True)

    def test_real_process_guard_rejects_live_unknown_and_missing_inventory(self):
        own = dict(ProcessId=os.getpid(), ParentProcessId=0, Name='python.exe', ExecutablePath='test-python', CommandLine='test')
        with patch('studio_handover.subprocess.check_output', return_value=json.dumps([own])):
            inspect_stopped(self.c, [])
        for other in [dict(ProcessId=98765, Name='terminal64.exe'), dict(ProcessId=98765, Name='python.exe'),
                      dict(ProcessId=98765, Name='python.exe', ExecutablePath='python.exe', CommandLine='goat_studio.py serve')]:
            with patch('studio_handover.subprocess.check_output', return_value=json.dumps([own, other])):
                with self.assertRaises(ValueError): inspect_stopped(self.c, [])
        with patch('studio_handover.subprocess.check_output', return_value='[]'):
            with self.assertRaisesRegex(ValueError, 'incomplete'): inspect_stopped(self.c, [])

    def test_restore_archive_change_after_review_is_rejected(self):
        first = review(self.c)['review_id']; apply(self.c, first, True)
        new = Controller(self.receipt); new.bootstrap('123456', 'Customer-Demo')
        new.store.close(); new.store = None
        restore = review(new, first)['review_id']
        archive = paths(self.c)[2]
        (archive/first/'state/changed').write_text('changed after review')
        with self.assertRaisesRegex(ValueError, 'Restore source changed'):
            apply(new, restore, True)


if __name__ == '__main__': unittest.main()
