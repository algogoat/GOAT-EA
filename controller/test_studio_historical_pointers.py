"""Fixture-only historical pointer retirement; never touches customer terminals."""
import hashlib
from contextlib import closing,redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from studio_bridge import write_json
from studio_handover import tree,paths
from studio_historical_pointers import prepare,apply,review_path,pending_path,known_sources
from studio_native_gate import shared_gate
from studio_bootstrap_retirement import classify_testers


class HistoricalPointerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableControllerTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.c=self.f.bound()
        self.c.store.db.execute('INSERT INTO studio_queues(binding,jobs) SELECT binding,? FROM studio_state',('[]',));self.c.store.db.commit()
        self.c.store.close();self.c.store=None
        write_json(self.c.root/'installation.json',self.c.install)
        self.base=self.f.common/'GOAT/GOAT V1.40-Customer-Demo';self.run=self.base/'Old Run';self.run.mkdir(parents=True)
        self.relative='GOAT\\GOAT V1.40-Customer-Demo\\Old Run'
        self.pointer=self.base/'active_optimization_run.ini'
        self.pointer.write_bytes(('[ActiveOptimizationRun]\nRunPath='+self.relative+'\nUpdatedAt=2026.05.01 01:02:03\n').encode('utf-16'))
        (self.run/'manifest.ini').write_bytes(('[OptimizationRun]\nVersion=1\nRunName=Old Run\nRunPath='+self.relative+'\nParentRunPath=\nEA=GOAT V1.40\nServer=Customer-Demo\nCreatedAt=2026.05.01 01:02:03\n').encode('utf-16'))
        self.queue=self.run/'queue.GOAT';self.queue.write_bytes(';Completed_old job;\n[Tester]\nSymbol=EURUSD\n'.encode('utf-16'))
        (self.run/'reports').mkdir();(self.run/'reports/result.xml').write_text('<report>retained</report>')
        self.original=self.pointer.read_bytes();self.run_tree=tree(self.run)
        p=patch('studio_historical_pointers.writer_check',return_value={'status':'stopped','independent_service_agents':[]});self.writer=p.start();self.addCleanup(p.stop)

    def review(self):return prepare(self.c)['review_id']
    def perform(self,review):return apply(self.c,review,confirmed=True)

    def test_exact_pointer_archived_run_and_session_preserved(self):
        before=tree(self.c.local);review=self.review();result=self.perform(review)
        self.assertEqual(result['status'],'retired');self.assertFalse(self.pointer.exists())
        self.assertEqual(tree(self.run),self.run_tree);self.assertEqual(tree(self.c.local),before)
        self.assertEqual((review_path(self.c,review).parent/'0.pointer').read_bytes(),self.original)
        moved=self.f.common/'GOAT/.historical-control-maintenance/retired'/review/'0.pointer'
        self.assertEqual(moved.read_bytes(),self.original)
        self.assertFalse(pending_path(self.c).exists());self.assertEqual(self.perform(review),result)

    def test_pending_paused_running_and_unknown_historical_queue_refused(self):
        for status in ('Pending','Queued','OnGoing','Paused','Unknown'):
            with self.subTest(status=status):
                self.queue.write_bytes((';'+status+'_old job;\n[Tester]\nSymbol=EURUSD\n').encode('utf-16'))
                with self.assertRaisesRegex(ValueError,'pending, paused, active or unknown'):self.review()
        self.assertEqual(self.pointer.read_bytes(),self.original)

    def test_other_native_controls_and_current_version_pointer_refused(self):
        for name in ('active_optimization_config.ini','active_optimization_launch.ini','agent-native-control-owner.json'):
            p=self.base/name;p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Native config'):self.review()
            p.unlink()
        current=self.f.common/'GOAT/GOAT V1.48-Customer-Demo';current.mkdir()
        (current/'active_optimization_run.ini').write_bytes(self.original)
        with self.assertRaisesRegex(ValueError,'older version'):self.review()

    def test_user_review_ttl_and_changed_pointer_or_run_block(self):
        review=self.review()
        with self.assertRaisesRegex(ValueError,'confirmation'):apply(self.c,review)
        with patch('studio_historical_pointers.time.time',return_value=10**12),self.assertRaisesRegex(ValueError,'expired'):self.perform(review)
        (self.run/'reports/result.xml').write_text('changed')
        with self.assertRaisesRegex(ValueError,'evidence changed'):self.perform(review)
        self.assertTrue(self.pointer.exists())

    def test_writer_or_session_lock_prevents_review_and_apply(self):
        review=self.review();self.writer.side_effect=ValueError('active writer')
        with self.assertRaisesRegex(ValueError,'active writer'):self.perform(review)
        self.writer.side_effect=None
        with shared_gate(paths(self.c)[3]),self.assertRaises(OSError):self.perform(review)
        self.assertTrue(self.pointer.exists())

    def test_owned_nested_json_backslash_and_slash_paths_refused(self):
        for target in (self.relative,self.relative.replace('\\','/').upper(),str(self.run)):
            with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
                db.execute('CREATE TABLE IF NOT EXISTS retained_notes (value TEXT)');db.execute('DELETE FROM retained_notes')
                db.execute('INSERT INTO retained_notes VALUES(?)',(json.dumps({'nested':{'frozenRun':target}}),))
                db.commit()
            with self.assertRaisesRegex(ValueError,'known controller references'):self.review()

    def test_unrelated_paused_pending_job_is_preserved(self):
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            db.execute('UPDATE studio_queues SET jobs=?',(json.dumps([{'job_id':'paused-history','status':'pending'}]),))
            db.commit()
        review=self.review();self.perform(review)
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            self.assertEqual(json.loads(db.execute('SELECT jobs FROM studio_queues').fetchone()[0])[0]['status'],'pending')

    def test_pending_launch_intent_or_active_seed_is_not_paused_history(self):
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            db.execute('UPDATE studio_queues SET jobs=?',(json.dumps([{'job_id':'old','status':'pending','launch_intent':{'attempt':'owned'}}]),))
            db.commit()
        with self.assertRaisesRegex(ValueError,'launch intent'):self.review()
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            db.execute('UPDATE studio_queues SET jobs=?',('[]',));db.commit()
        write_json(self.c.root/'seed-active.json',{'status':'running'})
        with self.assertRaisesRegex(ValueError,'Seed runner'):self.review()

    def test_crash_after_move_has_exact_forward_reconciliation_and_fence(self):
        real=Path.rename
        def interrupt(path,target):
            result=real(path,target)
            if path==self.pointer:raise OSError('crash after pointer move')
            return result
        review=self.review()
        with patch.object(Path,'rename',interrupt),self.assertRaisesRegex(OSError,'crash'):self.perform(review)
        self.assertFalse(self.pointer.exists());self.assertTrue(pending_path(self.c).exists())
        from goat_studio import Controller
        with self.assertRaisesRegex(ValueError,'historical pointer retirement'):Controller(self.c.root/'installation.json').bootstrap('123456','Customer-Demo')
        from goat_studio import main
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--installation',str(self.c.root/'installation.json'),'historical-pointers-apply','--review-id',review,'--confirm-reviewed'])
        self.assertEqual(code,0,output.getvalue());self.assertEqual(json.loads(output.getvalue())['result']['status'],'retired')
        self.assertEqual(tree(self.run),self.run_tree)

    def test_reappeared_pointer_after_crash_is_preserved(self):
        real=Path.rename
        def interrupt(path,target):
            result=real(path,target)
            if path==self.pointer:raise OSError('crash')
            return result
        review=self.review()
        with patch.object(Path,'rename',interrupt),self.assertRaises(OSError):self.perform(review)
        self.pointer.write_bytes(self.original)
        with self.assertRaisesRegex(ValueError,'New or changed'):self.perform(review)
        self.assertEqual(self.pointer.read_bytes(),self.original)

    def test_crash_after_fence_before_intent_can_resume_after_original_ttl(self):
        review=self.review();real=write_json
        def interrupt(path,value):
            if Path(path)==review_path(self.c,review) and value.get('status')=='archiving':raise OSError('crash before intent record')
            return real(path,value)
        with patch('studio_historical_pointers.write_json',side_effect=interrupt),self.assertRaises(OSError):self.perform(review)
        self.assertTrue(pending_path(self.c).exists());self.assertTrue(self.pointer.exists())
        with patch('studio_historical_pointers.time.time',return_value=10**12):
            self.assertEqual(self.perform(review)['status'],'retired')

    def test_crash_after_completion_before_fence_cleanup_replays(self):
        review=self.review();real=Path.unlink
        def interrupt(path,*args,**kwargs):
            if path==pending_path(self.c):raise OSError('crash before fence cleanup')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupt),self.assertRaises(OSError):self.perform(review)
        self.assertFalse(self.pointer.exists());self.assertTrue(pending_path(self.c).exists())
        self.assertEqual(self.perform(review)['status'],'retired');self.assertFalse(pending_path(self.c).exists())

    def test_changed_retired_archive_is_not_accepted_after_crash(self):
        real=Path.rename;review=self.review()
        def interrupt(path,target):
            result=real(path,target)
            if path==self.pointer:raise OSError('crash')
            return result
        with patch.object(Path,'rename',interrupt),self.assertRaises(OSError):self.perform(review)
        moved=self.f.common/'GOAT/.historical-control-maintenance/retired'/review/'0.pointer';moved.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'exact archived move'):self.perform(review)
        self.assertTrue(pending_path(self.c).exists())

    def test_controller_database_is_locked_through_pointer_move(self):
        real=Path.rename;review=self.review()
        def verify_locked(path,target):
            with closing(sqlite3.connect(self.c.root/'studio.sqlite',timeout=0)) as db:
                with self.assertRaises(sqlite3.OperationalError):db.execute('UPDATE studio_state SET revision=revision+1')
            return real(path,target)
        with patch.object(Path,'rename',verify_locked):self.perform(review)

    def test_active_worker_claim_or_registry_target_binding_blocks(self):
        registry=self.f.root/'workers.sqlite'
        with closing(sqlite3.connect(registry)) as db:
            db.executescript('CREATE TABLE attempts(released INTEGER); CREATE TABLE startup_slot(id INTEGER); CREATE TABLE workers(configuration TEXT); INSERT INTO attempts VALUES(0);');db.commit()
        sources=known_sources(self.c);sources['registries']=[str(registry)]
        with patch('studio_historical_pointers.known_sources',return_value=sources):
            with self.assertRaisesRegex(ValueError,'claim or startup'):self.review()
            with closing(sqlite3.connect(registry)) as db:
                db.execute('UPDATE attempts SET released=1');db.execute('INSERT INTO workers VALUES(?)',(json.dumps({'nested':{'run':self.relative}}),));db.commit()
            with self.assertRaisesRegex(ValueError,'registry references'):self.review()

    @unittest.skipUnless(os.name=='nt','Windows case aliases share one physical SQLite database')
    def test_real_legacy_registry_case_alias_does_not_deadlock_maintenance(self):
        from studio_bootstrap_retirement import folder as legacy_folder
        registry=self.f.root/'legacy-workers.sqlite';database=self.c.root/'studio.sqlite'
        worker=dict(scope='fixture-worker',terminal=self.c.install['terminal_executable'],
                    data_root=self.c.install['terminal_data_root'],controller=str(database).lower(),
                    common_root=self.c.install['common_files_root'])
        with closing(sqlite3.connect(registry)) as db:
            db.executescript('CREATE TABLE workers(scope TEXT,configuration TEXT); CREATE TABLE attempts(released INTEGER); CREATE TABLE startup_slot(id INTEGER);')
            db.execute('INSERT INTO workers VALUES(?,?)',(worker['scope'],json.dumps(worker)));db.commit()
        retained=legacy_folder(self.c);retained.mkdir(parents=True)
        write_json(retained/'registry.json',dict(registry=str(registry),scope=worker['scope'],database=str(database).upper(),
                                                terminal=self.c.install['terminal_executable'],data_root=self.c.install['terminal_data_root']))
        # All real discovery/registry readers run. Raw casing differs in three
        # durable sources; every concurrent writer must still stay locked out.
        review=self.review()
        self.assertEqual(len(known_sources(self.c)['databases']),1)
        self.assertEqual(self.perform(review)['status'],'retired')

    def test_foreign_review_and_run_escape_refused(self):
        with self.assertRaisesRegex(ValueError,'review ID'):self.perform('../outside')
        self.pointer.write_bytes('[ActiveOptimizationRun]\nRunPath=..\\outside\nUpdatedAt=2026.05.01 01:02:03\n'.encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'own version'):self.review()

    def test_reparse_path_refused(self):
        original=Path.is_symlink
        def linked(path):return True if path==self.run else original(path)
        with patch.object(Path,'is_symlink',linked),self.assertRaisesRegex(ValueError,'[Ll]ink|[Rr]eparse'):self.review()


class IdleServiceTests(unittest.TestCase):
    def test_known_tester_service_with_established_remote_connection_is_not_idle(self):
        from types import SimpleNamespace
        c=SimpleNamespace(install={'terminal_executable':r'C:\MT5\terminal64.exe'})
        snapshot={'processes':[{'ProcessId':1,'Name':'services.exe'},{'ProcessId':2,'ParentProcessId':1,'Name':'metatester64.exe','ExecutablePath':None}],
                  'services':[{'ProcessId':2,'State':'Running','Name':'MetaTester','ExecutablePath':r'C:\Agent\metatester64.exe'}],
                  'connections':[{'OwningProcess':2,'State':'Established','RemoteAddress':'203.0.113.1'}]}
        with self.assertRaisesRegex(ValueError,'active connection'):classify_testers(c,snapshot,require_idle_services=True)
        snapshot['connections']=[]
        self.assertEqual(len(classify_testers(c,snapshot,require_idle_services=True)['independent_service_agents']),1)


if __name__=='__main__':unittest.main()
