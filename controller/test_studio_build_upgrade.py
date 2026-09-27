"""Same-version exchange and interruption tests: fixture files only, no MT5."""
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from goat_studio import Controller,main
from studio_bridge import write_json
from studio_build_upgrade import replace_build,pending_path,replace_bytes
from studio_handover import paths,database_view,guard
from studio_native_gate import shared_gate
import test_studio_installation_upgrade as fixtures


class BuildUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.InstallationUpgradeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.c=f.c;self.root=f.f.root;self.receipt=f.receipt;self.review=f.review;self.old=f.old
        self.raw=f.raw;self.candidate=f.candidate
        self.binary=f.f.data/'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5'
        self.old_ea=self.binary.read_bytes()
        self.ea=self.candidate.parent/'candidate.ex5';self.ea.write_bytes(b'corrected same-version EA')
        self.desired=dict(self.c.install,ea_sha256=hashlib.sha256(self.ea.read_bytes()).hexdigest())
        write_json(self.candidate,self.desired)

    def run_upgrade(self):
        return replace_build(self.receipt,self.review,self.candidate,self.ea,self.old)

    def test_success_preserves_archives_and_same_version_idempotent(self):
        result=self.run_upgrade()
        self.assertEqual(result['status'],'build_replaced')
        self.assertEqual(Controller(self.receipt).install,self.desired)
        self.assertEqual(self.binary.read_bytes(),self.ea.read_bytes())
        self.assertFalse(any(result[k] for k in ('session_created','agent_control_granted','terminal_started')))
        self.assertFalse(pending_path(self.c.root).exists())
        self.assertEqual((paths(self.c)[2]/self.review/'state/installation.json').read_bytes(),self.raw)
        self.assertEqual(self.run_upgrade(),result)

    def test_cli_recovers_exact_pair_before_controller_hash_check(self):
        def interrupt(target,raw):
            if target==self.receipt:raise OSError('crash between EA and receipt')
            return replace_bytes(target,raw)
        with patch('studio_build_upgrade.replace_bytes',side_effect=interrupt),self.assertRaisesRegex(OSError,'crash'):
            self.run_upgrade()
        self.assertTrue(pending_path(self.c.root).exists())
        with self.assertRaisesRegex(ValueError,'hash differs'):Controller(self.receipt)
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--installation',str(self.receipt),'switch-replace-build','--review-id',self.review,
                       '--candidate-receipt',str(self.candidate),'--candidate-ea',str(self.ea),'--expected-sha256',self.old])
        self.assertEqual(code,0,output.getvalue());self.assertTrue(json.loads(output.getvalue())['ok'])
        self.assertEqual(Controller(self.receipt).install,self.desired)

    def test_crash_after_both_publications_still_fences_bootstrap_until_exact_reconciliation(self):
        real=write_json
        def interrupt(path,value):
            if Path(path).name=='build-upgrade.json' and value['status']=='build_replaced':raise OSError('crash after pair')
            return real(path,value)
        with patch('studio_build_upgrade.write_json',side_effect=interrupt),self.assertRaisesRegex(OSError,'crash'):
            self.run_upgrade()
        c=Controller(self.receipt)
        with self.assertRaisesRegex(ValueError,'Interrupted EA build'):c.bootstrap('123456','Customer-Demo')
        for operation in ('discover','switch-status','switch-apply'):
            options=['--review-id',self.review] if operation.startswith('switch-') else []
            output=io.StringIO()
            with redirect_stdout(output):
                code=main(['--installation',str(self.receipt),operation,*options])
            self.assertEqual(code,2);self.assertIn('Interrupted EA build',output.getvalue())
        self.assertEqual(self.run_upgrade()['status'],'build_replaced')

    def test_concurrent_controller_session_lock_blocks_before_any_mutation(self):
        with shared_gate(paths(self.c)[3]),self.assertRaises(OSError):self.run_upgrade()
        self.assertEqual(self.binary.read_bytes(),self.old_ea);self.assertEqual(self.receipt.read_bytes(),self.raw)

    def test_gate_and_external_database_stay_exclusive_through_both_publications(self):
        folder=paths(self.c)[2]/self.review;external=self.root/'external.sqlite'
        shutil.copyfile(folder/'state/studio.sqlite',external)
        plan=json.loads((folder/'receipt.json').read_bytes());plan['after_ownership'].append(database_view(external))
        write_json(folder/'receipt.json',plan)
        seen=[]
        def assert_locked(target,raw):
            with self.assertRaises(OSError),shared_gate(paths(self.c)[3]):pass
            with closing(sqlite3.connect(external,timeout=0)) as other:
                with self.assertRaises(sqlite3.OperationalError):other.execute('UPDATE studio_state SET revision=revision+1')
            seen.append(target);return replace_bytes(target,raw)
        with patch('studio_build_upgrade.replace_bytes',side_effect=assert_locked):self.run_upgrade()
        self.assertEqual(seen,[self.binary,self.receipt])

    def test_new_session_or_changed_archive_blocks(self):
        (self.c.root/'session.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'new session'):self.run_upgrade()
        (self.c.root/'session.json').unlink()
        (paths(self.c)[2]/self.review/'state/requests/tamper.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Parked research'):self.run_upgrade()
        self.assertEqual(self.binary.read_bytes(),self.old_ea)

    def test_exact_candidate_and_identity_required(self):
        self.ea.write_bytes(b'not admitted EA')
        with self.assertRaisesRegex(ValueError,'Candidate EA'):self.run_upgrade()
        self.ea.write_bytes(b'corrected same-version EA')
        write_json(self.candidate,dict(self.desired,ea_version='1.49'))
        with self.assertRaisesRegex(ValueError,'installation identity'):self.run_upgrade()

    def test_unknown_ea_after_interruption_is_not_overwritten(self):
        def interrupt(target,raw):
            if target==self.receipt:raise OSError('crash')
            return replace_bytes(target,raw)
        with patch('studio_build_upgrade.replace_bytes',side_effect=interrupt),self.assertRaises(OSError):self.run_upgrade()
        self.binary.write_bytes(b'someone changed this')
        with self.assertRaisesRegex(ValueError,'compare-and-swap'):self.run_upgrade()
        self.assertEqual(self.binary.read_bytes(),b'someone changed this');self.assertTrue(pending_path(self.c.root).exists())

    def test_altered_recovery_backup_and_journal_are_refused(self):
        def interrupt(target,raw):raise OSError('crash before first exchange')
        with patch('studio_build_upgrade.replace_bytes',side_effect=interrupt),self.assertRaises(OSError):self.run_upgrade()
        archive=paths(self.c)[2]/self.review
        (archive/'build-upgrade.previous.ex5').write_bytes(b'changed backup')
        with self.assertRaisesRegex(ValueError,'recovery bytes'):self.run_upgrade()
        (archive/'build-upgrade.previous.ex5').write_bytes(self.old_ea)
        write_json(archive/'build-upgrade.json',[])
        with self.assertRaisesRegex(ValueError,'Malformed'):self.run_upgrade()

    def test_no_generic_permission_to_ignore_hash(self):
        self.binary.write_bytes(self.ea.read_bytes())
        with self.assertRaisesRegex(ValueError,'hash differs'):self.run_upgrade()
        self.assertFalse(pending_path(self.c.root).exists())

    def test_receipt_snapshot_is_decoded_from_exact_bytes_once(self):
        original=Path.read_bytes;reads=0
        def changed_second_read(path):
            nonlocal reads
            if path==self.candidate:
                reads+=1
                if reads>1:return json.dumps(dict(self.desired,ea_version='unreviewed')).encode()
            return original(path)
        with patch.object(Path,'read_bytes',changed_second_read):self.run_upgrade()
        self.assertEqual(reads,1);self.assertEqual(Controller(self.receipt).install,self.desired)

    def test_duplicate_candidate_keys_rejected_before_publication(self):
        self.candidate.write_text('{"ea_sha256":"a","ea_sha256":"b"}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.run_upgrade()
        self.assertEqual(self.binary.read_bytes(),self.old_ea)

    def test_backup_snapshot_must_still_match_previous_ea(self):
        from studio_installation_upgrade import inspect_park
        def mutate_after_inspection(*args,**kwargs):
            result=inspect_park(*args,**kwargs)
            self.binary.write_bytes(b'changed before backup')
            return result
        with patch('studio_build_upgrade.inspect_park',side_effect=mutate_after_inspection),self.assertRaisesRegex(ValueError,'before durable backup'):
            self.run_upgrade()
        self.assertEqual(self.receipt.read_bytes(),self.raw)
        self.assertFalse((paths(self.c)[2]/self.review/'build-upgrade.json').exists())


if __name__=='__main__':unittest.main()
