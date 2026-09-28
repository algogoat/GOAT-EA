"""Pure transformation fixtures; no native or customer-state mutations."""
import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from studio_derived_report_recovery import corrected_draft, permission_bytes, recover, verify_completed
from studio_bridge import write_json
from studio_installation import read_json
import test_studio_human_reopen as fixtures


class DerivedReportTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(terminal_id='fixture', run_id='session-fixture', ea_version='1.49', server='Broker-Demo', native_run='GOAT\\R123456789abc')
        tester = '[Tester]\nSymbol=EURUSD\nModel=4\nReport=MQL5\\Files\\GOAT\\R123456789abc\\reports\\Example\\EURUSD\\result.xml\nVisual=0\n'
        exports = '[Export]\nMinSR=2.5\n'
        self.draft = dict(schema_version=1, terminal_id='fixture', run_id='session-fixture', revision=0, generation=0,
                          tester_ini=tester, export_ini=exports, submitted='',
                          baseline=(tester + exports).replace('R123456789abc\\reports', 'GOAT V1.49-Broker-Demo'))

    def test_only_baseline_changes_no_invented_revision_or_settings(self):
        before = copy.deepcopy(self.draft)
        result = corrected_draft(self.draft, **self.args)
        self.assertEqual(self.draft, before)
        self.assertEqual(result['baseline'], before['tester_ini'] + before['export_ini'])
        self.assertEqual({k:v for k,v in result.items() if k!='baseline'}, {k:v for k,v in before.items() if k!='baseline'})

    def test_real_edits_and_ambiguous_reports_are_retained(self):
        for key, old, new in [('tester_ini', 'Model=4', 'Model=1'), ('tester_ini', 'EURUSD\n', 'GBPUSD\n'),
                              ('export_ini', 'MinSR=2.5', 'MinSR=1'), ('tester_ini', 'Visual=0', 'Visual='),
                              ('tester_ini', 'Report=', 'report='), ('baseline', 'Report=', 'Report=x\nReport='),
                              ('tester_ini', 'Report=', 'Report=x\nReport='), ('baseline', 'Report=', 'Missing='),
                              ('baseline', '[Tester]', '[Other]'), ('tester_ini', 'result.xml', '..\\result.xml')]:
            with self.subTest(key=key, new=new):
                value = copy.deepcopy(self.draft); value[key] = value[key].replace(old, new)
                with self.assertRaises(ValueError): corrected_draft(value, **self.args)

    def test_wrong_identity_namespace_pending_and_metadata_refused(self):
        for key, value in [('terminal_id','other'), ('run_id','other'), ('revision',False), ('generation',-1),
                           ('submitted','pending settings'), ('schema_version',2)]:
            with self.subTest(key=key):
                draft = self.draft | {key:value}
                with self.assertRaises(ValueError): corrected_draft(draft, **self.args)
        for key, value in [('native_run','GOAT\\R000000000000'), ('server','other'), ('ea_version','1.48')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError): corrected_draft(self.draft, **(self.args | {key:value}))
        with self.assertRaises(ValueError): corrected_draft(self.draft | {'unknown':'value'}, **self.args)

    def test_already_corrected_or_other_path_change_is_not_a_new_repair(self):
        result = corrected_draft(self.draft, **self.args)
        with self.assertRaises(ValueError): corrected_draft(result, **self.args)
        self.draft['tester_ini'] = self.draft['tester_ini'].replace('result.xml', 'other.xml')
        with self.assertRaises(ValueError): corrected_draft(self.draft, **self.args)

    def test_actual_saved_monitor_failure_fixture_keeps_opaque_mode4(self):
        chart=(Path(__file__).parent/'fixtures/saved-monitor-input-groups.chr.txt').read_bytes()
        self.assertIn(b'expertmode=4',chart)
        common=b'[Experts]\r\nAllowDllImport=1\r\nEnabled=0\r\n[Charts]\r\nProfileLast=fixture\r\n'
        flags=permission_bytes(chart,common)
        expected=next(line for line in chart.splitlines(keepends=True) if line.strip()==b'expertmode=4')
        self.assertEqual(bytes.fromhex(flags['chart']),expected)
        self.assertEqual(permission_bytes(chart.replace(b'<indicator>',b'<indicator>\r\nexpertmode=0'),common),flags)
        self.assertNotEqual(permission_bytes(chart.replace(b'expertmode=4',b'expertmode=5'),common),flags)
        self.assertNotEqual(permission_bytes(chart,common.replace(b'AllowDllImport=1',b'AllowDllImport=0')),flags)
        with self.assertRaises(ValueError):permission_bytes(chart,common.replace(b'Enabled=0',b'Enabled=1'))

    def test_broker_server_spaces_preserve_exact_derived_report_suffix(self):
        value=copy.deepcopy(self.draft)
        value['baseline']=value['baseline'].replace('Broker-Demo','Broker Demo 01')
        result=corrected_draft(value,**(self.args|dict(server='Broker Demo 01')))
        self.assertEqual(result['baseline'],value['tester_ini']+value['export_ini'])


class ManagedReportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.HumanReopenTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.prepared(); self.c=self.f.c; self.process=self.f.process
        self.original=self.f.path; self.draft_path=self.f.draft
        base=DerivedReportTests(); base.setUp()
        draft=base.draft | dict(terminal_id=self.c.terminal,run_id=self.c.run)
        run=self.f.f.manifest['native_run_relative'].split('\\')[-1]
        draft['tester_ini']=draft['tester_ini'].replace('R123456789abc',run)
        draft['baseline']=draft['baseline'].replace('Broker-Demo',self.c.session['account']['server']).replace('GOAT V1.49-', 'GOAT V'+self.c.install['ea_version']+'-')
        write_json(self.draft_path,draft)
        self.before=self.draft_path.read_bytes()
        old=read_json(self.original)
        old['protected_sha256'][str(self.draft_path)]=hashlib.sha256(self.before).hexdigest()
        config=Path(old['launch']['startup_config'])
        raw=config.read_bytes().decode('utf-16').replace('GOAT-Studio-fixture',self.f.profile['profile_name']).encode('utf-16')
        config.write_bytes(raw); old['launch']['startup_sha256']=hashlib.sha256(raw).hexdigest(); write_json(self.original,old)
        self.old=self.original.read_bytes()
        self.current=self.f.native['process']; self.started=False
        self.process.inspect.side_effect=lambda:self.current
        self.process.close.reset_mock(); self.process.start.reset_mock()
        def close(identity):
            self.assertEqual(identity,self.current); self.current=None
        def start(config):
            self.assertIsNone(self.current)
            self.current=dict(pid=46,created_utc=datetime.now(timezone.utc).isoformat())
            self.started=True
            return self.current
        self.process.close.side_effect=close; self.process.start.side_effect=start
        patch('studio_derived_report_recovery.inspect_idle_demo',side_effect=lambda c:self.f.native|dict(process=self.current)).start()
        patch('studio_derived_report_recovery.load_installation',side_effect=lambda p:self.c.install).start()
        def runtime(**kwargs):
            state=self.c.state(); value=read_json(self.draft_path)
            obs=dict(state,revision=state['revision'] if self.started else value['revision'],generation=value['generation'],
                     pending_id='',tester_ini=value['tester_ini'],export_ini=value['export_ini'])
            return obs,dict(modified=time.time())
        self.f.runtime.side_effect=runtime
        self.folder=self.original.parent/'derived-report-recovery'

    def test_managed_close_repair_launch_preserves_permissions_and_provenance(self):
        chart=Path(self.f.profile['profile_path'])/'chart01.chr'
        flags=permission_bytes(chart.read_bytes(),self.f.common.read_bytes())
        result=recover(self.c,'original',process=self.process)
        self.assertEqual(result['phase'],'reverified')
        self.assertEqual((self.folder/'draft-before.json').read_bytes(),self.before)
        self.assertEqual((self.folder/'restart-before.json').read_bytes(),self.old)
        self.assertEqual(permission_bytes(chart.read_bytes(),self.f.common.read_bytes()),flags)
        self.assertIn('expertmode=4',chart.read_bytes().decode('utf-16'))
        self.assertEqual(read_json(self.draft_path)['revision'],0) # only EA may acknowledge a revision
        self.process.close.assert_called_once();self.process.start.assert_called_once()
        saved=read_json(self.original)
        self.assertNotIn('human_reopened',saved)
        self.assertEqual(verify_completed(self.c,saved)['process'],self.current)
        self.assertEqual(recover(self.c,'original',process=self.process)['phase'],'reverified')
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_real_edit_does_not_close_or_launch(self):
        value=read_json(self.draft_path);value['tester_ini']=value['tester_ini'].replace('Model=4','Model=1')
        write_json(self.draft_path,value)
        with self.assertRaises(ValueError):recover(self.c,'original',process=self.process)
        self.process.close.assert_not_called();self.process.start.assert_not_called()

    def test_chart_different_from_retained_stopped_profile_refuses_before_close(self):
        chart=Path(self.f.profile['profile_path'])/'chart01.chr'
        chart.write_bytes(chart.read_bytes().decode('utf-16').replace('expertmode=4','expertmode=5').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'prior verified stopped'):recover(self.c,'original',process=self.process)
        self.process.close.assert_not_called();self.process.start.assert_not_called()

    def test_revoked_maintenance_repairs_baseline_without_regrant_or_old_scope_revival(self):
        from studio_research_authority import operation
        state=self.c.state()
        request=dict(schema_version=1,request_id='native-takeover',terminal_id=self.c.terminal,run_id=self.c.run,
            expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
        write_json(self.c.bridge.root/'human/inbox/native-takeover.json',request)
        with operation('serve'):self.assertTrue(self.c.bridge.pump()[0]['ok'])
        prior=(self.c.root/'research-authority.json').read_bytes()
        initial_runtime=self.f.runtime.side_effect
        def observed(**kwargs):
            value,details=initial_runtime(**kwargs)
            if self.started:value['generation']=self.c.state()['generation']
            return value,details
        self.f.runtime.side_effect=observed
        with operation('research-monitor-repair-revoked-report'),patch('studio_research_regrant.OWNER_ACCOUNT',self.c.session['account']):
            result=recover(self.c,'original',process=self.process,revoked_maintenance=True)
            self.assertEqual(result['phase'],'reverified')
            self.assertEqual(self.c.state()['owner'],'human')
            self.assertEqual(self.c.state()['generation'],state['generation']+1)
            self.assertEqual(recover(self.c,'original',process=self.process,revoked_maintenance=True)['phase'],'reverified')
        self.assertEqual((self.c.root/'research-authority.json').read_bytes(),prior)
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],0)
        self.process.close.assert_called_once();self.process.start.assert_called_once()
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'revoked'):self.c.state()

    def test_uncertain_launch_never_repeats(self):
        self.process.start.side_effect=ValueError('uncertain startup')
        with self.assertRaisesRegex(ValueError,'uncertain startup'):recover(self.c,'original',process=self.process)
        with self.assertRaisesRegex(ValueError,'Launch result uncertain'):recover(self.c,'original',process=self.process)
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_changed_permission_after_launch_never_acknowledges_recovery(self):
        original=self.process.start.side_effect
        def changed(config):
            result=original(config)
            chart=Path(self.f.profile['profile_path'])/'chart01.chr'
            chart.write_bytes(chart.read_bytes().decode('utf-16').replace('expertmode=4','expertmode=5').encode('utf-16'))
            return result
        self.process.start.side_effect=changed
        with self.assertRaisesRegex(ValueError,'permission bytes changed'):recover(self.c,'original',process=self.process)
        self.assertEqual(self.original.read_bytes(),self.old)
        self.assertEqual(read_json(self.folder/'transaction.json')['phase'],'started_unverified')

    def test_changed_permission_after_close_never_launches(self):
        original=self.process.close.side_effect
        def changed(identity):
            original(identity)
            self.f.common.write_bytes(self.f.common.read_bytes().decode('utf-16').replace('AllowDllImport=1','AllowDllImport=0').encode('utf-16'))
        self.process.close.side_effect=changed
        with self.assertRaisesRegex(ValueError,'permission bytes changed'):recover(self.c,'original',process=self.process)
        self.process.start.assert_not_called();self.assertEqual(self.draft_path.read_bytes(),self.before)

    def test_publication_resume_does_not_repeat_native_operations(self):
        from studio_derived_report_recovery import write_json as real_write
        def fail(path,value):
            if path==self.original: raise OSError('publication interruption')
            return real_write(path,value)
        with patch('studio_derived_report_recovery.write_json',side_effect=fail):
            with self.assertRaisesRegex(OSError,'publication interruption'):recover(self.c,'original',process=self.process)
        self.assertEqual(read_json(self.folder/'transaction.json')['phase'],'verified_pending_publication')
        self.assertEqual(recover(self.c,'original',process=self.process)['phase'],'reverified')
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_interrupted_stopped_draft_publication_resumes_exact_bytes_once(self):
        import os
        real_replace=os.replace
        def fail(source,target):
            if Path(target)==self.draft_path: raise OSError('draft CAS interruption')
            return real_replace(source,target)
        with patch('studio_derived_report_recovery.os.replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'draft CAS interruption'):recover(self.c,'original',process=self.process)
        self.assertIsNone(self.current);self.assertEqual(self.draft_path.read_bytes(),self.before)
        self.assertEqual(read_json(self.folder/'transaction.json')['phase'],'stopped')
        self.assertEqual(recover(self.c,'original',process=self.process)['phase'],'reverified')
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_unexpected_draft_after_stop_blocks_launch_and_retains_evidence(self):
        original=self.process.close.side_effect
        def changed(identity):
            original(identity);self.draft_path.write_bytes(b'{"unexpected":true}')
        self.process.close.side_effect=changed
        with self.assertRaisesRegex(ValueError,'draft changed outside'):recover(self.c,'original',process=self.process)
        self.process.start.assert_not_called()
        self.assertEqual((self.folder/'draft-before.json').read_bytes(),self.before)

    def test_modified_archived_permissions_refuse_reverification(self):
        recover(self.c,'original',process=self.process)
        path=self.folder/'chart-before.chr'
        path.write_bytes(path.read_bytes().decode('utf-16').replace('expertmode=4','expertmode=5').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'Archived permission evidence'):verify_completed(self.c,read_json(self.original))
