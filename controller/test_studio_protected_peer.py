"""Filesystem/CLI policy fixtures; never inspect or mutate real terminals."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from studio_protected_peer import prepare, apply, policy, directory, process_binding
from studio_process_check import classify_processes
from studio_handover import stopped, review, apply as switch_apply
from studio_onboarding import monitor_prepare


class ProtectedPeerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableControllerTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.c=self.f.bound()
        self.exe=self.f.root/'peer-program/terminal64.exe';self.exe.parent.mkdir();self.exe.write_bytes(b'peer')
        self.data=self.f.root/'peer-data';(self.data/'MQL5').mkdir(parents=True)
        (self.data/'origin.txt').write_text(str(self.exe.parent))
        self.row=dict(ProcessId=7788,ExecutablePath=str(self.exe),CreatedUtc='2026-09-26T12:00:00.0000000Z',Name='terminal64.exe')
        self.own=dict(ProcessId=os.getpid(),ParentProcessId=0,Name='python.exe',ExecutablePath='test',CommandLine='test')
        self.rows=[self.row]
        self.p=patch('studio_protected_peer.subprocess.check_output',side_effect=lambda *a,**k:json.dumps(self.rows));self.p.start();self.addCleanup(self.p.stop)

    def register(self):
        reviewed=prepare(self.c,self.exe,self.data)
        return apply(self.c,reviewed['review_id'],True)

    def test_explicit_review_has_no_grant_or_launch_and_pins_package_binding(self):
        before=self.c.state()
        reviewed=prepare(self.c,self.exe,self.data)
        self.assertIsNone(policy(self.c))
        with self.assertRaisesRegex(ValueError,'confirmation'): apply(self.c,reviewed['review_id'])
        apply(self.c,reviewed['review_id'],True)
        self.assertEqual(self.c.state(),before)
        self.assertEqual(self.c.binding()['protected_data_roots'],[str(self.data)])
        self.assertEqual(self.c.binding()['protected_process']['pid'],7788)
        self.assertEqual(apply(self.c,reviewed['review_id'],True)['reused'],True)

    def test_replaced_peer_is_refused_before_apply_and_by_native_classifier(self):
        reviewed=prepare(self.c,self.exe,self.data)
        self.rows=[dict(self.row,ProcessId=7789)]
        with self.assertRaisesRegex(ValueError,'changed'): apply(self.c,reviewed['review_id'],True)
        self.rows=[self.row];self.register()
        with self.assertRaisesRegex(ValueError,'Protected peer process changed'):
            classify_processes([dict(self.row,CreatedUtc='replacement')],process_binding(self.c),observed_unix=1,research_running=False)

    def test_unknown_duplicate_and_selected_running_are_not_ignored(self):
        self.register();binding=process_binding(self.c)
        for rows in ([self.row,dict(self.row,ProcessId=9000,ExecutablePath='C:/unknown/terminal64.exe')],
                     [self.row,dict(self.row,ProcessId=9000)],
                     [self.row,dict(self.row,ProcessId=9000,ExecutablePath=str(self.f.bin))]):
            with self.assertRaises(ValueError): classify_processes(rows,binding,observed_unix=1,research_running=False)

    def test_overlapping_paths_wrong_origin_and_binary_drift_fail(self):
        with self.assertRaisesRegex(ValueError,'Absolute'): prepare(self.c,Path('terminal64.exe'),self.data)
        with self.assertRaisesRegex(ValueError,'overlap'): prepare(self.c,self.f.bin,self.f.data)
        (self.data/'origin.txt').write_text('C:/wrong')
        with self.assertRaisesRegex(ValueError,'origin'): prepare(self.c,self.exe,self.data)
        (self.data/'origin.txt').write_text(str(self.exe.parent));self.register()
        self.exe.write_bytes(b'updated')
        with self.assertRaisesRegex(ValueError,'changed'): self.c.binding()

    def test_setup_uses_peer_pin_and_requires_selected_stopped(self):
        self.register()
        def check(binding,**kw):
            self.assertEqual(binding['protected_process']['pid'],7788)
            selected=kw.pop('selected_stopped',False)
            roots=kw.pop('absent_roots',None)
            return classify_processes(self.rows,binding,observed_unix=1,
                                      unrelated_roots=roots if selected else None,**kw)
        with patch('studio_onboarding.inspect_processes',side_effect=check):
            self.rows=[self.row,dict(self.row,ProcessId=9000,ExecutablePath=str(self.f.bin))]
            with self.assertRaises(ValueError): monitor_prepare(self.c,'EURUSD')
            self.rows=[self.row]
            self.assertEqual(monitor_prepare(self.c,'EURUSD')['status'],'prepared')

    def test_handover_allows_only_exact_peer_and_policy_survives_parking(self):
        self.register();before=policy(self.c)
        self.c.store.close();self.c.store=None
        self.rows=[self.own,self.row]
        stopped(self.c,[])
        planned=review(self.c)
        self.rows=[self.own,dict(self.row,ProcessId=7799)]
        with self.assertRaisesRegex(ValueError,'Protected peer process changed'): switch_apply(self.c,planned['review_id'],True)
        self.rows=[self.own,self.row]
        switch_apply(self.c,planned['review_id'],True)
        self.assertEqual(policy(self.c),before)
        self.assertTrue((directory(self.c)/'policy.json').is_file())

    def test_unreviewed_peer_and_metaeditor_block_handover(self):
        self.rows=[self.own,self.row]
        with self.assertRaisesRegex(ValueError,'Close MT5'): stopped(self.c,[])
        self.rows=[self.row];self.register()
        self.rows=[self.own,self.row,dict(ProcessId=999,Name='metaeditor64.exe')]
        with self.assertRaisesRegex(ValueError,'Close MT5'): stopped(self.c,[])

    def test_active_attempt_blocks_policy_replacement(self):
        self.f.grant(self.c);self.f.prepare(self.c)
        state=self.c.state();job=state['queue'][0];job['status']='starting'
        self.c.store.db.execute('UPDATE studio_queues SET jobs=?',(json.dumps([job]),))
        with self.assertRaisesRegex(ValueError,'Reconcile native attempts'): prepare(self.c,self.exe,self.data)
