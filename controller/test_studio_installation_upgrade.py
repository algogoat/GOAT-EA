"""Receipt CAS and archived-state checks; no actual install or terminal launch."""
from contextlib import closing
import hashlib
import json
import shutil
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from goat_studio import Controller
from studio_bridge import write_json
from studio_handover import apply,review,paths,database_view
from studio_installation_upgrade import verify_park,replace_receipt
from studio_native_gate import shared_gate


class InstallationUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableControllerTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.c=self.f.bound();self.f.grant(self.c);self.f.prepare(self.c)
        self.c.store.close();self.c.store=None
        self.receipt=self.c.root/'installation.json';write_json(self.receipt,self.c.install)
        self.raw=self.receipt.read_bytes();self.old=hashlib.sha256(self.raw).hexdigest()
        p=patch('studio_handover.stopped');p.start();self.addCleanup(p.stop)
        p=patch('studio_installation_upgrade.stopped');p.start();self.addCleanup(p.stop)
        self.review=review(self.c)['review_id'];apply(self.c,self.review,True)
        self.candidate=self.f.root/'staging/new-installation.json';self.candidate.parent.mkdir()
        self.desired=dict(self.c.install,ea_version='1.49',ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        binary=self.f.data/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5';binary.write_bytes(b'new reviewed EA fixture')
        self.desired['ea_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest();write_json(self.candidate,self.desired)

    def test_readonly_verify_and_atomic_replace_preserve_original(self):
        first=verify_park(self.c,self.review);self.assertEqual(first['status'],'parked_verified');self.assertEqual(first['receipt_sha256'],self.old)
        result=replace_receipt(self.c,self.review,self.candidate,self.old)
        self.assertEqual(result['status'],'receipt_replaced');self.assertFalse(result['session_created'])
        self.assertEqual(self.receipt.read_bytes(),self.candidate.read_bytes())
        self.assertEqual((paths(self.c)[2]/self.review/'state/installation.json').read_bytes(),self.raw)
        self.assertEqual(replace_receipt(Controller(self.receipt),self.review,self.candidate,self.old),result)

    def test_active_session_after_park_blocks(self):
        (self.c.root/'session.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'new session'):replace_receipt(self.c,self.review,self.candidate,self.old)
        self.assertEqual(self.receipt.read_bytes(),self.raw)

    def test_archive_mutation_and_wrong_cas_block(self):
        with self.assertRaisesRegex(ValueError,'compare-and-swap'):replace_receipt(self.c,self.review,self.candidate,'0'*64)
        (paths(self.c)[2]/self.review/'state/requests/tampered.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Parked research'):verify_park(self.c,self.review)

    def test_external_parked_database_is_verified_and_locked_through_publication(self):
        archived=paths(self.c)[2]/self.review;external=self.f.root/'external.sqlite'
        shutil.copyfile(archived/'state/studio.sqlite',external)
        plan=json.loads((archived/'receipt.json').read_bytes());plan['after_ownership'].append(database_view(external))
        write_json(archived/'receipt.json',plan)
        self.assertEqual(verify_park(self.c,self.review)['status'],'parked_verified')
        from studio_installation_upgrade import inspect_park
        def verify_while_writer_blocked(*args,**kwargs):
            with closing(sqlite3.connect(external,timeout=0)) as other:
                with self.assertRaises(sqlite3.OperationalError):other.execute('UPDATE studio_state SET revision=revision+1')
            return inspect_park(*args,**kwargs)
        with patch('studio_installation_upgrade.inspect_park',side_effect=verify_while_writer_blocked):
            self.assertEqual(replace_receipt(self.c,self.review,self.candidate,self.old)['status'],'receipt_replaced')
        with closing(sqlite3.connect(external)) as db:db.execute('UPDATE studio_state SET revision=revision+1');db.commit()
        with self.assertRaisesRegex(ValueError,'External parked'):
            replace_receipt(Controller(self.receipt),self.review,self.candidate,self.old)

    def test_candidate_target_change_and_inside_root_refused(self):
        altered=dict(self.desired,controller_state_root=str(self.f.root/'different'));write_json(self.candidate,altered)
        with self.assertRaisesRegex(ValueError,'physical'):replace_receipt(self.c,self.review,self.candidate,self.old)
        inside=self.c.root/'candidate.json';write_json(inside,self.desired)
        with self.assertRaisesRegex(ValueError,'outside'):replace_receipt(self.c,self.review,inside,self.old)

    def test_missing_exact_new_artifact_refused(self):
        (self.f.data/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash differs'):replace_receipt(self.c,self.review,self.candidate,self.old)

    def test_frozen_candidate_bytes_must_match_validated_receipt(self):
        real=Path.read_bytes;count=0
        changed=json.dumps(dict(self.desired,controller_version='unreviewed')).encode()
        def swapped(path):
            nonlocal count
            if path==self.candidate:
                count+=1
                if count==1:return changed
            return real(path)
        with patch.object(Path,'read_bytes',swapped),self.assertRaisesRegex(ValueError,'Canonical candidate'):
            replace_receipt(self.c,self.review,self.candidate,self.old)
        self.assertEqual(self.receipt.read_bytes(),self.raw)

    def test_concurrent_controller_lock_blocks_receipt_publication(self):
        lock=paths(self.c)[3]
        with shared_gate(lock),self.assertRaises(OSError):replace_receipt(self.c,self.review,self.candidate,self.old)
        self.assertEqual(self.receipt.read_bytes(),self.raw)

    def test_crash_after_receipt_publication_can_complete_without_rewriting_archive(self):
        real=write_json
        def crash(path,value):
            if Path(path).name=='receipt-upgrade.json' and value.get('status')=='receipt_replaced':raise OSError('interrupted final receipt')
            return real(path,value)
        with patch('studio_installation_upgrade.write_json',side_effect=crash),self.assertRaisesRegex(OSError,'interrupted'):
            replace_receipt(self.c,self.review,self.candidate,self.old)
        self.assertEqual(self.receipt.read_bytes(),self.candidate.read_bytes())
        result=replace_receipt(Controller(self.receipt),self.review,self.candidate,self.old)
        self.assertEqual(result['status'],'receipt_replaced')
        self.assertEqual((paths(self.c)[2]/self.review/'state/installation.json').read_bytes(),self.raw)

    def test_candidate_already_present_does_not_make_empty_journal_authoritative(self):
        self.receipt.write_bytes(self.candidate.read_bytes())
        for value in ({},[],{'status':'publication_intent'}):
            write_json(paths(self.c)[2]/self.review/'receipt-upgrade.json',value)
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'malformed'):
                replace_receipt(Controller(self.receipt),self.review,self.candidate,self.old)


if __name__=='__main__':unittest.main()
