"""Windows filesystem/SQLite handover tests; no broker or tester is launched."""
import io
import json
import errno
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

import goat_studio
from goat_studio import Controller
from studio_handover import apply, database_view, filesystem_path, guard, inspect, load_plan, paths, review, tree, session_lock
from studio_installation_upgrade import verify_park
from studio_native_gate import exclusive_gate, shared_gate
from studio_handover import stopped as inspect_stopped
from studio_bridge import write_json,worker_lock
from studio_installation import read_json
from test_goat_studio import PortableControllerTests
import studio_desktop_client
from test_studio_desktop_client import desktop_rpc_pair, write_hashed_bundle


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PortableControllerTests()
        self.fixture.setUp()
        self.c = self.fixture.bound()
        self.fixture.grant(self.c)
        self.fixture.prepare(self.c)
        self.c.store.close(); self.c.store = None
        self.before = database_view(self.c.root/'studio.sqlite')
        self.process_patch = patch('studio_handover.stopped')
        self.process = self.process_patch.start()
        self.addCleanup(patch.stopall)
        # Customer receipts normally live in the controller directory.
        write_json(self.c.root/'installation.json', self.fixture.receipt)
        self.receipt = self.c.root/'installation.json'

    def tearDown(self):
        self.fixture.tearDown()

    def test_completed_park_verifies_long_archived_path_without_reparking(self):
        relative = Path(*(['research-' + 'a'*55]*3))/'evidence.bin'
        source = filesystem_path(self.c.root/relative)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'preserved research evidence')
        planned = review(self.c)
        self.assertEqual(apply(self.c, planned['review_id'], True)['status'], 'complete')
        archived = paths(self.c)[2]/planned['review_id']/'state'/relative
        self.assertGreater(len(str(archived)), 260)

        original_is_file = Path.is_file
        def without_unprefixed_long_paths(path):
            if os.name == 'nt' and len(str(path)) > 260 and not str(path).startswith('\\\\?\\'):
                return False
            return original_is_file(path)
        # This filesystem fixture must not consult the developer's live MT5.
        with patch('studio_installation_upgrade.stopped') as stopped, patch.object(Path, 'is_file', without_unprefixed_long_paths):
            self.assertEqual(verify_park(self.c, planned['review_id'])['status'], 'parked_verified')
            stopped.assert_called_once()
            self.assertIs(stopped.call_args.args[0], self.c)
            self.assertTrue(stopped.call_args.kwargs['allow_qualification_client'])
        self.assertEqual(filesystem_path(archived).read_bytes(), b'preserved research evidence')
        original_is_symlink = Path.is_symlink
        def linked_deep_file(path):
            if os.name == 'nt' and str(path).startswith('\\\\?\\') and path.name == 'evidence.bin':
                return True
            return original_is_symlink(path)
        with patch.object(Path, 'is_symlink', linked_deep_file):
            with self.assertRaisesRegex(ValueError, 'filesystem links'):
                verify_park(self.c, planned['review_id'])
        filesystem_path(archived).write_bytes(b'changed research evidence')
        with self.assertRaisesRegex(ValueError, 'Parked research files changed'):
            verify_park(self.c, planned['review_id'])

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

    def test_park_then_bootstrap_a_different_demo_login_moves_the_binding(self):
        # P-beta40-demo-login-switch gate (Claude-Mac goatai#2587 6300398545): an expired demo
        # login (123456) is parked and the same installation bootstraps a new login (654321).
        old_session = read_json(self.c.root/'session.json')
        self.assertEqual(old_session['account'], {'login': '123456', 'server': 'Customer-Demo'})
        before_files = tree(self.c.local)
        probe = Controller(self.receipt)
        try:
            with self.assertRaisesRegex(ValueError, 'Existing account binding differs'):
                probe.bootstrap('654321', 'Customer-Demo')
        finally:
            if probe.store: probe.store.close()
        planned = review(self.c)
        self.assertEqual(apply(self.c, planned['review_id'], True)['status'], 'complete')
        with patch('studio_installation_upgrade.stopped'):
            self.assertEqual(verify_park(self.c, planned['review_id'])['status'], 'parked_verified')
        new = Controller(self.receipt)
        try:
            session = new.bootstrap('654321', 'Customer-Demo')
            self.assertEqual(session['account'], {'login': '654321', 'server': 'Customer-Demo'})
            self.assertTrue(session['demo_only'])
            self.assertEqual(session['authority_kind'], 'native_human_control')
            self.assertNotEqual(session['run_id'], old_session['run_id'])
            self.assertEqual(new.store.snapshot(session['terminal_id'], session['run_id'])['owner'], 'human')
        finally:
            if new.store: new.store.close()
        # The binding moved: the new login re-opens without refusal, the old one now differs.
        for login, refusal in (('654321', None), ('123456', 'Existing account binding differs')):
            again = Controller(self.receipt)
            try:
                if refusal:
                    with self.assertRaisesRegex(ValueError, refusal): again.bootstrap(login, 'Customer-Demo')
                else:
                    self.assertEqual(again.bootstrap(login, 'Customer-Demo')['run_id'], session['run_id'])
            finally:
                if again.store: again.store.close()
        self.assertEqual(read_json(self.c.root/'session.json')['account']['login'], '654321')
        self.assertEqual(read_json(self.c.local/'active.json')['run_id'], session['run_id'])
        # The old session sits in the archive, research and terminal files intact, human-owned.
        saved = paths(self.c)[2]/planned['review_id']
        self.assertEqual(read_json(saved/'state'/'session.json'), old_session)
        self.assertEqual(read_json(saved/'terminal'/'active.json')['run_id'], old_session['run_id'])
        self.assertEqual(tree(saved/'terminal'), before_files)
        archived = database_view(saved/'state'/'studio.sqlite')
        self.assertEqual(archived['content'], self.before['content'])
        self.assertEqual(archived['counts'], {'pending': 1})
        self.assertEqual(archived['states'][0][3], 'human')

    def test_inspect_and_apply_fence_recognize_desktop_rpc_clients(self):
        planned = review(self.c)
        self.assertEqual([call.kwargs for call in self.process.call_args_list],
                         [dict(allow_desktop_rpc_client=True)])
        self.process.reset_mock()
        apply(self.c, planned['review_id'], True)
        # apply's own fence and its re-inspection both recognize the requesting client.
        self.assertEqual([call.kwargs for call in self.process.call_args_list],
                         [dict(allow_desktop_rpc_client=True)]*2)

    def test_real_fence_accepts_requesting_prepare_switch_client_but_not_a_runner(self):
        # P-beta40-prepare-switch-self-pid (goatai#2587 6300078347): the agent's own
        # `goat.exe desktop onboarding.prepareSwitch` was refused as "the existing controller".
        self.process_patch.stop()
        bundle = self.fixture.root/'bundle with spaces'
        write_hashed_bundle(bundle)
        patch.object(studio_desktop_client, '__file__', str(bundle/'controller/studio_desktop_client.py')).start()
        patch.object(studio_desktop_client, 'windows_argv', side_effect=lambda raw: json.loads(raw)).start()
        own = dict(ProcessId=os.getpid(), ParentProcessId=0, Name='python.exe', ExecutablePath='test-python', CommandLine='test')
        requester = desktop_rpc_pair(bundle, 98770, 'onboarding.prepareSwitch')
        waiter = desktop_rpc_pair(bundle, 98772, 'events.wait', ['--timeout-ms', '60000', '--session', 'agentSession01'])
        runner = desktop_rpc_pair(bundle, 98780, 'serve', ['--installation', str(self.receipt)], surface='studio')
        inventory = patch('studio_handover.subprocess.check_output').start()
        inventory.return_value = json.dumps([own, *requester])
        planned = review(self.c)  # Old code: "Stop the existing controller/runner ... (PID 98770)".
        self.assertEqual(planned['status'], 'review')
        inventory.return_value = json.dumps([own, *requester, *runner])
        with self.assertRaisesRegex(ValueError, r'Stop the existing controller/runner before switching \(PID 9878[01]\)'):
            review(self.c)
        inventory.return_value = json.dumps([own, *requester, *waiter, *runner])
        with self.assertRaisesRegex(ValueError, r'Stop the existing controller/runner before switching \(PID 9878[01]\)'):
            apply(self.c, planned['review_id'], True)
        inventory.return_value = json.dumps([own, *requester, *waiter])
        self.assertEqual(apply(self.c, planned['review_id'], True)['status'], 'complete')

    def test_button_flow_with_agent_in_events_wait_never_reaches_owner_maintenance_recheck(self):
        # Claude-Mac goatai#2587 6301648760: prepareSwitch -> the person's confirm -> switch-apply
        # --confirm-reviewed -> switch-verify-park, while the agent's `goat.exe desktop events.wait`
        # stays open. The owner-maintenance re-check (apply's completed branch) needs
        # owner_maintenance, which --confirm-reviewed excludes; verify-park is the step that must
        # recognize the waiting client.
        real_stopped = inspect_stopped
        self.process_patch.stop()
        fences = []
        def recording(*args, **kwargs):
            fences.append(kwargs)
            return real_stopped(*args, **kwargs)
        patch('studio_handover.stopped', side_effect=recording).start()
        bundle = self.fixture.root/'bundle with spaces'
        write_hashed_bundle(bundle)
        patch.object(studio_desktop_client, '__file__', str(bundle/'controller/studio_desktop_client.py')).start()
        patch.object(studio_desktop_client, 'windows_argv', side_effect=lambda raw: json.loads(raw)).start()
        own = dict(ProcessId=os.getpid(), ParentProcessId=0, Name='python.exe', ExecutablePath='test-python', CommandLine='test')
        requester = desktop_rpc_pair(bundle, 98770, 'onboarding.prepareSwitch')
        waiter = desktop_rpc_pair(bundle, 98772, 'events.wait', ['--timeout-ms', '60000', '--session', 'agentSession01'])
        inventory = patch('studio_handover.subprocess.check_output').start()
        inventory.return_value = json.dumps([own, *requester, *waiter])
        planned = review(self.c)
        inventory.return_value = json.dumps([own, *waiter])  # prepareSwitch answered; events.wait still open
        self.assertEqual(apply(self.c, planned['review_id'], True)['status'], 'complete')
        # A retried confirm of the completed park returns the receipt without any process fence.
        self.assertEqual(apply(self.c, planned['review_id'], True)['status'], 'complete')
        # Every fence the button reached recognized desktop RPC clients; the full-fence
        # owner-maintenance re-check (called without the keyword) never ran.
        self.assertEqual(fences, [dict(allow_desktop_rpc_client=True)]*3)
        with self.assertRaisesRegex(ValueError, 'one explicit handover authorization route'):
            apply(self.c, planned['review_id'], True, owner_maintenance='owner-record')
        self.assertEqual(len(fences), 3)
        # switch-verify-park with the agent still in events.wait (old code: "Stop the existing
        # controller/runner ... (PID 98772)").
        self.assertEqual(verify_park(self.c, planned['review_id'])['status'], 'parked_verified')
        runner = desktop_rpc_pair(bundle, 98780, 'serve', ['--installation', str(self.receipt)], surface='studio')
        inventory.return_value = json.dumps([own, *waiter, *runner])
        with self.assertRaisesRegex(ValueError, r'Stop the existing controller/runner before switching \(PID 9878[01]\)'):
            verify_park(self.c, planned['review_id'])

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

    def test_cross_volume_park_and_restore_preserve_research_and_human_ownership(self):
        rename = Path.rename
        def cross_volume(source, target):
            if source in (self.c.local, self.c.root) or (source.name in ('state', 'terminal') and target in (self.c.local, self.c.root)):
                raise OSError(errno.EXDEV, 'cross-volume test boundary')
            return rename(source, target)
        with patch.object(Path, 'rename', cross_volume):
            first = review(self.c)['review_id']; apply(self.c, first, True)
            new = Controller(self.receipt); new.bootstrap('123456', 'Customer-Demo')
            new.store.close(); new.store = None
            second = review(new, first)['review_id']
            self.assertEqual(apply(new, second, True)['status'], 'complete')
        restored = Controller(self.receipt).open()
        try:
            self.assertEqual(restored.state()['owner'], 'human')
            self.assertEqual(restored.state()['queue'][0]['status'], 'pending')
            self.assertEqual(database_view(restored.root/'studio.sqlite')['content'], self.before['content'])
        finally: restored.store.close()

    def test_cross_volume_retirement_interruption_keeps_same_review_fence_and_resumes(self):
        planned = review(self.c)['review_id']
        before_files = tree(self.c.local)
        rename, unlink = Path.rename, Path.unlink
        def cross_volume(source, target):
            if source == self.c.local: raise OSError(errno.EXDEV, 'cross-volume test boundary')
            return rename(source, target)
        def interrupt(file, *args, **kwargs):
            result = unlink(file, *args, **kwargs)
            if file.is_relative_to(self.c.local): raise OSError('interrupted retirement')
            return result
        with patch.object(Path, 'rename', cross_volume), patch.object(Path, 'unlink', interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted retirement'): apply(self.c, planned, True)
        with self.assertRaisesRegex(ValueError, planned): guard(self.c)
        with self.assertRaisesRegex(ValueError, 'Interrupted'): self.c.bootstrap('123456', 'Customer-Demo')
        self.assertEqual(tree(paths(self.c)[2]/planned/'terminal'), before_files)
        self.assertEqual(apply(self.c, planned, True)['status'], 'complete')
        guard(self.c)
        self.assertEqual(tree(paths(self.c)[2]/planned/'terminal'), before_files)

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
        older = StudioStore(external, create=True)
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

    def test_expired_review_cleanup_preserves_active_applied_and_unknown_evidence(self):
        expired = review(self.c)['review_id']
        future = review(self.c)['review_id']
        unknown = review(self.c)['review_id']
        archive = paths(self.c)[2]
        (archive/unknown/'unexpected').write_text('retain')
        for review_id in (expired, unknown):
            plan = load_plan(self.c, review_id)
            plan['expires_at'] = 0
            write_json(archive/review_id/'receipt.json', plan)
        applied = review(self.c)['review_id']
        self.assertFalse((archive/expired).exists())
        self.assertTrue((archive/future/'receipt.json').exists())
        self.assertTrue((archive/unknown/'unexpected').exists())
        apply(self.c, applied, True)
        new = Controller(self.receipt)
        new.bootstrap('123456', 'Customer-Demo')
        new.store.close(); new.store = None
        plan = load_plan(new, applied); plan['expires_at'] = 0
        write_json(archive/applied/'receipt.json', plan)
        review(new)
        self.assertTrue((archive/applied/'state/studio.sqlite').is_file())
        self.assertTrue((archive/applied/'receipt.json').is_file())

    def test_process_identity_error_explains_elevated_or_other_session(self):
        rows = [dict(ProcessId=os.getpid(), ParentProcessId=0),
                dict(ProcessId=123, Name='pwsh.exe', CommandLine=None, ExecutablePath=None)]
        with patch('studio_handover.subprocess.check_output', return_value=json.dumps(rows)):
            with self.assertRaisesRegex(ValueError, 'elevated or in another Windows session'):
                inspect_stopped(self.c, [])

    def test_shared_holds_exclude_apply_and_exclusive_hold_excludes_commands(self):
        # Real platform handles, across processes: no mocked lock primitives.
        lock = paths(self.c)[3]; lock.mkdir(parents=True, exist_ok=True)
        code = ('import sys; from studio_native_gate import shared_gate,exclusive_gate; '
                'gate=shared_gate if sys.argv[2]=="shared" else exclusive_gate; '
                '\nwith gate(sys.argv[1]): print("held",flush=True); input()')
        for mode in ('shared', 'exclusive'):
            with self.subTest(mode=mode):
                child = subprocess.Popen([sys.executable, '-c', code, str(lock), mode],
                                         cwd=Path(__file__).parent, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(child.stdout.readline().strip(), 'held')
                    if mode == 'shared':
                        with session_lock(self.c): pass
                    else:
                        with self.assertRaises(OSError):
                            with session_lock(self.c): pass
                    with self.assertRaises(OSError):
                        with exclusive_gate(lock): pass
                finally:
                    out, err = child.communicate('\n', timeout=10)
                    self.assertEqual(child.returncode, 0, err)
                with exclusive_gate(lock): pass

    def test_real_cli_serve_allows_state_onboarding_cancel_and_blocks_switch_apply(self):
        planned = review(self.c)['review_id']
        ready = self.fixture.root/'serve-ready'
        # The marker is written by the real serve loop after its first bridge
        # pump, proving the public CLI acquired its lifetime hold and is running.
        script = ('import sys; from pathlib import Path; import goat_studio; '
                  'from studio_bridge import pump_for; marker=Path(sys.argv.pop(1)); '
                  'original=goat_studio.pump_for\n'
                  'def serve(bridge, seconds):\n'
                  '  pump=bridge.pump\n'
                  '  def marked(*a,**kw):\n'
                  '    result=pump(*a,**kw); marker.touch(); return result\n'
                  '  bridge.pump=marked\n'
                  '  return original(bridge, seconds)\n'
                  'goat_studio.pump_for=serve\n'
                  'sys.exit(goat_studio.main())')
        folder = Path(__file__).parent
        args = ['--installation', str(self.receipt)]
        # Check the cold real CLI first, including Windows process discovery.
        # The concurrent probes below then measure the server/client boundary.
        cold = subprocess.run([sys.executable, 'goat_studio.py', *args, 'onboarding-status'],
                              cwd=folder, capture_output=True, text=True, timeout=15)
        self.assertEqual(cold.returncode, 0, cold.stderr)
        self.assertTrue(json.loads(cold.stdout)['ok'])
        # Each of the five concurrent CLI probes has a 20-second bound: a CLI blocked by the
        # running server still fails (it would wait for the server's whole lifetime), while a
        # slow, loaded machine no longer flakes it (goatai#1885, Claude-Mac on GOAT-EA#160).
        # Leave the real server alive through the full aggregate probe window.
        child = subprocess.Popen([sys.executable, '-c', script, str(ready), *args,
                                  'serve', '--watch-seconds', '45'], cwd=folder,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'serve did not enter its real pump loop')
            for command in [('switch-apply', '--review-id', planned, '--confirm-reviewed'),
                            ('state',), ('onboarding-status',), ('cancel', '--job-id', 'beta-job'),
                            ('state',)]:
                self.assertIsNone(child.poll(), 'serve exited before concurrent CLI assertion')
                started = time.monotonic()
                try:
                    result = subprocess.run([sys.executable, 'goat_studio.py', *args, *command],
                                            cwd=folder, capture_output=True, text=True, timeout=20)
                finally:
                    print(f'concurrent CLI {command[0]}: {time.monotonic()-started:.3f}s; '
                          f'serve_running={child.poll() is None}', file=sys.stderr)
                body = json.loads(result.stdout)
                if command[0] == 'switch-apply':
                    self.assertFalse(body['ok'], body)
                    self.assertTrue('WinError 32' in body['error'] or 'temporarily unavailable' in body['error'], body)
                else:
                    self.assertTrue(body['ok'], body)
            self.assertEqual(body['result']['queue'][0]['status'], 'cancelled')
        finally:
            out, err = child.communicate(timeout=60)
            self.assertEqual(child.returncode, 0, out+err)


class WorkerContentionTests(unittest.TestCase):
    def test_real_exclusive_worker_contention_waits_before_any_work(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'worker.lock').write_bytes(b'0')
            script='from studio_bridge import worker_lock; from pathlib import Path; import sys,time\nwith worker_lock(Path(sys.argv[1])):\n print("held",flush=True)\n time.sleep(float(sys.argv[2]))'
            for duration,expires in ((.25,False),(1.5,True)):
                child=subprocess.Popen([sys.executable,'-c',script,str(root),str(duration)],cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    self.assertEqual(child.stdout.readline().strip(),'held')
                    started=time.monotonic();entered=False
                    if expires:
                        with self.assertRaises(OSError):
                            with worker_lock(root):entered=True
                        self.assertFalse(entered)
                    else:
                        with worker_lock(root):entered=True
                        self.assertTrue(entered)
                        self.assertGreater(time.monotonic()-started,.05)
                    self.assertLess(time.monotonic()-started,1.4)
                finally:
                    out,err=child.communicate(timeout=5)
                    self.assertEqual(child.returncode,0,out+err)


# A real `goat_studio.py bootstrap` in a second Python process, paused inside its first guard(): after the CLI took
# the binding lock and before any state write. argv: controller folder, receipt, held marker, release marker, login.
CHILD_BOOTSTRAP = r'''
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import studio_handover
real, paused = studio_handover.guard, []
def guard(*args, **kwargs):
    if not paused:
        paused.append(True)
        pathlib.Path(sys.argv[3]).write_text('held')
        while not pathlib.Path(sys.argv[4]).exists():
            time.sleep(.05)
    return real(*args, **kwargs)
studio_handover.guard = guard
import goat_studio
raise SystemExit(goat_studio.main(['--installation', sys.argv[2], 'bootstrap',
                                   '--account-login', sys.argv[5], '--account-server', 'Customer-Demo']))
'''


class BindingLockTests(unittest.TestCase):
    """Claude-Mac goatai#2587 6304681152: bootstrap, switch-verify-park and switch-apply hold one exclusive OS lock
    per installation, owned by the controller's own Python process. The old controller let them overlap: the
    shared session_lock is no exclusion, and bootstrap took no lock at all."""

    def setUp(self):
        self.fixture = PortableControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.state = Path(self.fixture.receipt['controller_state_root'])

    def hold(self, receipt, login='123456'):
        folder = Path(tempfile.mkdtemp(dir=self.fixture.root))
        held, release, errors = folder/'held.txt', folder/'release.txt', folder/'child.err'
        log = errors.open('wb')
        child = subprocess.Popen([sys.executable, '-c', CHILD_BOOTSTRAP, str(Path(__file__).resolve().parent),
                                  str(receipt), str(held), str(release), login], stdout=subprocess.DEVNULL, stderr=log)
        def stop():
            if child.poll() is None:
                child.kill()
            child.wait(30)
            log.close()
        self.addCleanup(stop)
        deadline = time.monotonic() + 90
        while not held.exists():
            if child.poll() is not None:
                log.flush()
                self.fail('the holding bootstrap exited early: '+errors.read_text(errors='replace'))
            if time.monotonic() > deadline:
                self.fail('the holding bootstrap never reached its pause')
            time.sleep(.05)
        return child, release

    def bootstrap(self, receipt, login='123456'):
        c = Controller(receipt)
        try:
            return c.bootstrap(login, 'Customer-Demo')
        finally:
            if c.store: c.store.close()

    def cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = goat_studio.main(list(argv))
        return code, json.loads(out.getvalue())

    def assertBindingRefused(self, call):
        with self.assertRaises(ValueError) as caught:
            call()
        self.assertEqual(getattr(caught.exception, 'code', None), 'BINDING_IN_PROGRESS', str(caught.exception))
        self.assertIn('GOAT is still finishing an earlier step on this terminal; wait, then check again',
                      str(caught.exception))

    def test_second_concurrent_bootstrap_refuses_binding_in_progress(self):
        child, release = self.hold(self.fixture.path)
        self.assertBindingRefused(lambda: self.bootstrap(self.fixture.path))
        code, reply = self.cli('--installation', str(self.fixture.path), 'bootstrap',
                               '--account-login', '123456', '--account-server', 'Customer-Demo')
        self.assertEqual((code, reply['ok'], reply.get('refusal_code'), reply.get('operation')),
                         (2, False, 'BINDING_IN_PROGRESS', 'bootstrap'), reply)
        self.assertFalse((self.state/'session.json').exists(), 'a refused bootstrap writes nothing')
        release.write_text('go')
        self.assertEqual(child.wait(90), 0)
        self.assertEqual(read_json(self.state/'session.json')['account'], {'login': '123456', 'server': 'Customer-Demo'})

    def test_killed_holder_frees_the_lock_and_a_retry_passes(self):
        child, _ = self.hold(self.fixture.path)
        self.assertBindingRefused(lambda: self.bootstrap(self.fixture.path))
        child.kill(); child.wait(30)                         # TerminateProcess on Windows, SIGKILL elsewhere
        lock = self.state.parent/'.studio-binding'/self.state.name/'binding.lock'
        self.assertTrue(lock.is_file(), 'the lock file stays; only the OS lock ever counted')
        code, reply = self.cli('--installation', str(self.fixture.path), 'bootstrap',
                               '--account-login', '123456', '--account-server', 'Customer-Demo')
        self.assertEqual((code, reply['ok']), (0, True), reply)
        self.assertEqual(reply['result']['account'], {'login': '123456', 'server': 'Customer-Demo'})

    def test_verify_park_and_apply_refuse_while_a_bootstrap_holds_the_lock(self):
        c = self.fixture.bound(); self.fixture.grant(c); self.fixture.prepare(c)
        c.store.close(); c.store = None
        receipt = c.root/'installation.json'; write_json(receipt, self.fixture.receipt)
        patch('studio_handover.stopped').start(); patch('studio_installation_upgrade.stopped').start()
        self.addCleanup(patch.stopall)
        planned = review(c)['review_id']
        self.assertEqual(apply(c, planned, True)['status'], 'complete')
        child, _ = self.hold(receipt)
        self.assertBindingRefused(lambda: verify_park(c, planned))
        self.assertBindingRefused(lambda: apply(c, planned, True))
        for argv in (('switch-verify-park', '--review-id', planned),
                     ('switch-apply', '--review-id', planned, '--confirm-reviewed')):
            code, reply = self.cli('--installation', str(receipt), *argv)
            self.assertEqual((code, reply.get('refusal_code'), reply.get('operation')), (2, 'BINDING_IN_PROGRESS', argv[0]), reply)
        child.kill(); child.wait(30)
        self.assertEqual(verify_park(c, planned)['status'], 'parked_verified')
        self.assertEqual(apply(c, planned, True)['status'], 'complete')

    def test_different_installations_do_not_block_each_other(self):
        other = PortableControllerTests(); other.setUp(); self.addCleanup(other.tearDown)
        # A second installation whose state root sits in the SAME parent folder as the first one's.
        other.receipt['controller_state_root'] = str(self.state.parent/'second customer state')
        other.path.write_text(json.dumps(other.receipt))
        child, _ = self.hold(self.fixture.path)
        self.assertEqual(self.bootstrap(other.path)['account'], {'login': '123456', 'server': 'Customer-Demo'})
        self.assertBindingRefused(lambda: self.bootstrap(self.fixture.path))

    def test_lock_file_is_derived_from_the_installation_not_the_arguments(self):
        # The holder runs from a copy of the receipt in another folder with another login; the lock is still the
        # installation's own, beside its state root (switch-apply moves the state root itself).
        copy = self.fixture.root/'elsewhere'/'receipt copy.json'
        copy.parent.mkdir(); copy.write_text(json.dumps(self.fixture.receipt))
        child, _ = self.hold(copy, login='999999')
        lock = self.state.parent/'.studio-binding'/self.state.name/'binding.lock'
        self.assertTrue(lock.is_file())
        self.assertFalse((copy.parent/'.studio-binding').exists())
        self.assertFalse(self.state.exists() and any(p.name == 'binding.lock' for p in self.state.rglob('*')))
        self.assertBindingRefused(lambda: self.bootstrap(self.fixture.path, login='123456'))


if __name__ == '__main__': unittest.main()
