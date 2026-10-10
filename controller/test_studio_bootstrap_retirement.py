"""Passive-bootstrap recovery tests. No Windows process is touched."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
import studio_bootstrap_retirement as retirement
from studio_bridge import write_json
from studio_handover import guard
from test_settled_native_request import PENDING_VARIANTS,gate_files,retain_pending_variant,retain_request


class BootstrapRetirementTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableControllerTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.c=self.f.bound(); self.f.grant(self.c)
        state=self.c.state(); scope=self.c.terminal; run=self.c.run
        self.c.store.close(); self.c.store=None
        self.original=dict(pid=11,created_utc='2026-09-26T01:00:00Z',executable=str(self.f.bin))
        self.host=dict(pid=12,created_utc='2026-09-26T00:59:00Z',executable=str(self.f.root/'python.exe'))
        self.current=dict(pid=13,created_utc='2026-09-26T01:01:00Z',executable=str(self.f.bin))
        self.peer=dict(pid=14,created_utc='2026-09-26T01:00:00Z',executable=str(self.f.root/'peer/terminal64.exe'))
        self.running=True
        self.registry=self.f.root/'workers.sqlite'
        monitor=self.f.data/'MQL5/Experts'/self.f.receipt['ea_relative_path'].replace('\\','/')
        preset=self.f.data/'MQL5/Presets/monitor.set'
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\n'.encode('utf-16'))
        profile=self.f.data/'MQL5/Profiles/Charts/Monitor';profile.mkdir(parents=True)
        (profile/'chart01.chr').write_text('<chart>\nsymbol=EURUSD\n<indicator>\nname=Main\npath=\n</indicator>\n</chart>\n')
        self.config=self.f.data/'config/monitor.ini';self.config.parent.mkdir()
        self.config.write_bytes(('[Charts]\nProfileLast=Monitor\n[Experts]\nEnabled=0\nAllowLiveTrading=0\n'
            '[StartUp]\nExpert='+self.f.receipt['ea_relative_path']+'\nExpertParameters=monitor.set\nSymbol=EURUSD\nPeriod=M1\n').encode('utf-16'))
        b=dict(research_terminal=str(self.f.bin),research_data_root=str(self.f.data),common_files_root=str(self.f.common),
               controller_database=str(self.c.root/'studio.sqlite'),bridge_root=str(self.c.local/run),concurrent_worker_registry=str(self.registry),
               native_control_scope=scope,live_trading_allowed=False,account_confirmation_pending=False,
               startup_monitor=dict(expert=self.f.receipt['ea_relative_path'],preset='monitor.set',preset_sha256=hashlib.sha256(preset.read_bytes()).hexdigest()))
        self.spec=dict(binding=b,terminal_id=scope,run_id=run,account=dict(login='123456',server='Customer-Demo'),
                       monitor_path=str(monitor),monitor_sha256=hashlib.sha256(monitor.read_bytes()).hexdigest(),observation_path=str(self.c.local/'ui-observation.json'))
        self.spec_path=self.f.root/'spec.json';write_json(self.spec_path,self.spec)
        self.bootstrap=self.f.root/'bootstrap';self.bootstrap.mkdir()
        self.record=dict(config=str(self.config),config_sha256=hashlib.sha256(self.config.read_bytes()).hexdigest(),protected_process=None)
        write_json(self.bootstrap/'host-issued.json',dict(host=self.host,attempt='passive-monitor',generation=state['generation'],configuration=self.record,before=dict(research=None)))
        write_json(self.bootstrap/'startup-issued.json',self.record)
        write_json(self.bootstrap/'startup-receipt.json',dict(process=self.original,tester_started_verified=False,native_receipt=dict(config=str(self.config),config_sha256=self.record['config_sha256'],launched=True)))
        worker=dict(terminal=str(self.f.bin),data_root=str(self.f.data),controller=b['controller_database'],bridge=b['bridge_root'],common_root=str(self.f.common))
        with closing(sqlite3.connect(self.registry)) as db:
            db.executescript('CREATE TABLE workers(scope TEXT PRIMARY KEY,configuration TEXT); CREATE TABLE attempts(scope TEXT,attempt TEXT,claim TEXT,released INTEGER,release_evidence TEXT); CREATE TABLE startup_slot(id INTEGER PRIMARY KEY,scope TEXT,attempt TEXT,acquired_unix REAL); CREATE TABLE startup_slot_history(scope TEXT,attempt TEXT,acquired_unix REAL,receipt_path TEXT,receipt_sha256 TEXT);')
            db.execute('INSERT INTO workers VALUES(?,?)',(scope,json.dumps(worker)))
            db.execute('INSERT INTO attempts VALUES(?,?,?,0,NULL)',(scope,'passive-monitor',json.dumps(self.host,sort_keys=True)))
            db.execute('INSERT INTO startup_slot VALUES(1,?,?,?)',(scope,'passive-monitor',time.time()-60)); db.commit()
        self.observation=dict(schema_version=1,bound=True,loaded=True,owner=state['owner'],revision=state['revision'],generation=state['generation'],
            observed_terminal_utc=datetime.now(timezone.utc).strftime('%Y.%m.%d %H:%M:%S'),runtime=dict(data_path=str(self.f.data),installation_path=str(self.f.bin.parent),program_path=str(monitor),account_login='123456',account_server='Customer-Demo',connected=True,account_demo=True,terminal_trade_allowed=False,batch_ongoing=True,restart_pending=False,tester_state='idle',native_control_scope=scope))
        self.patches=[]
        for name,kwargs in [
            ('studio_bootstrap_retirement.inspect_processes',dict(side_effect=self.inspect)),
            ('studio_bootstrap_retirement.process_binding',dict(return_value={})),
            ('studio_bootstrap_retirement.require_no_testers',dict(return_value=dict(status='no_selected_tester_or_updater_processes'))),
            ('studio_bootstrap_retirement.prove_exited',dict(side_effect=lambda identity:dict(identity=identity,proof='pid_absent'))),
            ('studio_resilient_read.read_observation',dict(side_effect=lambda p:(self.observation,time.time()))),
            ('studio_bootstrap_retirement.WindowsSeedProcess.close',dict(side_effect=self.close))]:
            mock=patch(name,**kwargs);self.patches.append(mock.start());self.addCleanup(mock.stop)

    def inspect(self,binding,research_running=True):
        if research_running!=self.running: raise ValueError('Selected terminal state differs')
        return dict(research=self.current if self.running else None,protected=self.peer,observed_unix=time.time())

    def close(self,identity):
        self.assertEqual(identity,self.current);self.running=False

    def prepare(self):
        return retirement.prepare(self.c,self.spec_path,self.bootstrap)['review_id']

    def rows(self):
        with closing(sqlite3.connect(self.registry)) as db:
            return (db.execute('SELECT released,release_evidence FROM attempts').fetchall(),db.execute('SELECT * FROM startup_slot').fetchall(),db.execute('SELECT * FROM startup_slot_history').fetchall())

    def test_preview_has_no_native_or_claim_effects(self):
        before=self.rows();self.prepare();self.assertEqual(before,self.rows());self.patches[-1].assert_not_called()

    def test_only_identified_independent_windows_services_may_remain(self):
        service=str(self.f.root/'services/metatester64.exe')
        baseline=dict(processes=[dict(ProcessId=1,Name='services.exe'),dict(ProcessId=2,ParentProcessId=1,Name='metatester64.exe',ExecutablePath=None),
            dict(ProcessId=3,Name='terminal64.exe',ExecutablePath=str(self.f.bin))],services=[dict(ProcessId=2,Name='MetaTester-1',State='Running',ExecutablePath=service)],connections=[])
        self.assertEqual(len(retirement.classify_testers(self.c,baseline)['independent_service_agents']),1)
        cases=[]
        x=deepcopy(baseline);x['services']=[];cases.append(x)
        x=deepcopy(baseline);x['processes'][1]['ParentProcessId']=3;cases.append(x)
        # MT5 installs persistent Windows services beside terminal64.exe. Their
        # service ownership, not shared executable directory, defines this role.
        x=deepcopy(baseline);x['services'][0]['ExecutablePath']=str(self.f.bin.parent/'metatester64.exe')
        self.assertEqual(len(retirement.classify_testers(self.c,x)['independent_service_agents']),1)
        x=deepcopy(baseline);x['processes'][1]['ExecutablePath']=str(self.f.bin.parent/'other.exe');cases.append(x)
        x=deepcopy(baseline);x['services'][0]['ExecutablePath']=None;cases.append(x)
        x=deepcopy(baseline);x['connections']=[dict(OwningProcess=3,State='Established',RemoteAddress='127.0.0.1')];cases.append(x)
        x=deepcopy(baseline);x['processes'].append(dict(ProcessId=4,Name='metaupdate64.exe'));cases.append(x)
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):retirement.classify_testers(self.c,case)

    def test_close_once_and_atomic_retirement_preserve_history(self):
        review=self.prepare();result=retirement.apply(self.c,review)
        self.assertEqual(result['status'],'retired');self.assertFalse(result['flags_changed'])
        rows=self.rows();self.assertEqual(rows[0][0][0],1);self.assertEqual(rows[1],[]);self.assertEqual(len(rows[2]),1)
        self.assertEqual(retirement.apply(self.c,review),result);self.patches[-1].assert_called_once()
        self.assertTrue((self.bootstrap/'startup-receipt.json').exists())

    def test_original_claim_drift_prevents_close(self):
        review=self.prepare()
        with closing(sqlite3.connect(self.registry)) as db:
            db.execute('UPDATE attempts SET released=1');db.commit()
        with self.assertRaisesRegex(ValueError,'unreleased'):retirement.apply(self.c,review)
        self.patches[-1].assert_not_called()

    def test_live_original_host_blocks_preview(self):
        self.patches[3].side_effect=ValueError('still alive')
        with self.assertRaisesRegex(ValueError,'still alive'):self.prepare()
        self.patches[-1].assert_not_called()

    def test_peer_replacement_prevents_close(self):
        review=self.prepare();self.peer=dict(self.peer,pid=99)
        with self.assertRaisesRegex(ValueError,'state changed'):retirement.apply(self.c,review)
        self.patches[-1].assert_not_called()

    def test_stale_controller_projection_blocks_preview(self):
        self.observation['revision']-=1
        with self.assertRaisesRegex(ValueError,'synchronize'):self.prepare()

    def test_legacy_dirty_editor_requires_exact_durable_preservation(self):
        current=self.observation['revision'];self.observation.update(revision=0,build='R17',pending_id='',
            status='Agent controls settings / revision '+str(current)+' / Unsaved edits retained',tester_ini='retained tester',export_ini='retained export')
        draft=dict(schema_version=1,terminal_id=self.c.terminal,run_id=self.c.run,revision=0,generation=self.observation['generation'],
                   tester_ini='retained tester',export_ini='retained export',baseline='old baseline',submitted='')
        p=self.c.local/self.c.run/'human/ui-draft.json';write_json(p,draft)
        review=self.prepare();saved=retirement.folder(self.c)/review/'preserved-ui-draft.json'
        self.assertEqual(saved.read_bytes(),p.read_bytes())
        draft['tester_ini']='changed';write_json(p,draft)
        with self.assertRaisesRegex(ValueError,'durably preserved'):retirement.apply(self.c,review)
        self.patches[-1].assert_not_called()

    def test_inbox_and_fixed_tasks_block_preview(self):
        inbox=self.c.local/self.c.run/'human/processing';inbox.mkdir(parents=True,exist_ok=True)
        message=inbox/'grant.json';message.write_text('{}')
        with self.assertRaisesRegex(ValueError,'inbox'):self.prepare()
        message.unlink()
        with closing(sqlite3.connect(self.c.root/'studio.sqlite')) as db:
            db.executescript('CREATE TABLE studio_fixed_tasks(released INTEGER);INSERT INTO studio_fixed_tasks VALUES(0);');db.commit()
        with self.assertRaisesRegex(ValueError,'Fixed task'):self.prepare()

    def test_gate_owner_mismatch_blocks_even_without_request(self):
        gate=self.c.local/'native-gate/controller.json';write_json(gate,dict(database='elsewhere'))
        with self.assertRaisesRegex(ValueError,'gate database'):self.prepare()

    def test_request_the_ea_already_consumed_and_answered_is_settled_for_preview_and_retirement(self):
        # Terminal 3 shape (goatai#1885): request.json retained beside its exact consumed/result pair.
        gate=self.c.local/'native-gate'
        request_id,raw=retain_request(gate,self.c.terminal,self.c.run)
        before=gate_files(gate)
        review=self.prepare()
        plan=json.loads((retirement.folder(self.c)/review/'review.json').read_bytes())
        settled=plan['snapshot']['controller']['settled_native_requests']
        self.assertEqual([(item['request_id'],item['request_sha256']) for item in settled],[(request_id,hashlib.sha256(raw).hexdigest())])
        result=retirement.apply(self.c,review)
        self.assertEqual(result['status'],'retired');self.patches[-1].assert_called_once()
        self.assertEqual(gate_files(gate),before)

    def test_pending_or_mismatched_request_still_needs_the_legacy_settled_schema(self):
        gate=self.c.local/'native-gate'
        for name in PENDING_VARIANTS:
            with self.subTest(name):
                retain_pending_variant(name,gate,self.c.terminal,self.c.run)
                before=gate_files(gate)
                with self.assertRaisesRegex(ValueError,'Legacy settled request not verified'):self.prepare()
                self.assertEqual(gate_files(gate),before)
        self.patches[-1].assert_not_called()

    def test_a_different_settled_request_after_review_prevents_close(self):
        gate=self.c.local/'native-gate'
        retain_request(gate,self.c.terminal,self.c.run,'reviewed-request')
        review=self.prepare()
        retain_request(gate,self.c.terminal,self.c.run,'newer-request')
        with self.assertRaisesRegex(ValueError,'state changed'):retirement.apply(self.c,review)
        self.patches[-1].assert_not_called()

    def test_script_configuration_rejected_even_when_rehashed(self):
        raw=self.config.read_bytes().decode('utf-16')+'Script=other\n';self.config.write_bytes(raw.encode('utf-16'))
        self.record['config_sha256']=hashlib.sha256(self.config.read_bytes()).hexdigest()
        write_json(self.bootstrap/'startup-issued.json',self.record)
        host=json.loads((self.bootstrap/'host-issued.json').read_bytes());host['configuration']=self.record;write_json(self.bootstrap/'host-issued.json',host)
        receipt=json.loads((self.bootstrap/'startup-receipt.json').read_bytes());receipt['native_receipt']['config_sha256']=self.record['config_sha256'];write_json(self.bootstrap/'startup-receipt.json',receipt)
        with self.assertRaisesRegex(ValueError,'Passive'):self.prepare()

    def test_custom_indicator_prevents_preview(self):
        p=self.f.data/'MQL5/Profiles/Charts/Monitor/chart01.chr';p.write_text(p.read_text().replace('name=Main','name=Custom'))
        with self.assertRaisesRegex(ValueError,'custom indicator'):self.prepare()

    def test_interrupted_close_is_fenced_and_never_resent(self):
        review=self.prepare();self.patches[-1].side_effect=OSError('uncertain dispatch')
        with self.assertRaises(OSError):retirement.apply(self.c,review)
        with self.assertRaisesRegex(ValueError,'retirement'):guard(self.c)
        self.running=False
        result=retirement.apply(self.c,review);self.assertEqual(result['status'],'retired');self.patches[-1].assert_called_once()

    def test_completed_replay_cleans_matching_pending_fence(self):
        review=self.prepare();result=retirement.apply(self.c,review)
        pending=retirement.folder(self.c)/'pending.json';write_json(pending,dict(review_id=review))
        self.assertEqual(retirement.apply(self.c,review),result);self.assertFalse(pending.exists())

    def test_registry_transaction_rolls_back_both_releases(self):
        review=self.prepare();before=self.rows()
        with closing(sqlite3.connect(self.registry)) as db:
            db.executescript("CREATE TRIGGER fail_slot BEFORE DELETE ON startup_slot BEGIN SELECT RAISE(ABORT,'test abort'); END;");db.commit()
        with self.assertRaisesRegex(sqlite3.Error,'test abort'):retirement.apply(self.c,review)
        self.assertEqual(before,self.rows())
        with closing(sqlite3.connect(self.registry)) as db:db.execute('DROP TRIGGER fail_slot');db.commit()
        proof=retirement.folder(self.c)/review/'retirement-proof.json';value=json.loads(proof.read_bytes());value['review_sha256']='0'*64;write_json(proof,value)
        with self.assertRaisesRegex(ValueError,'exact reviewed'):retirement.apply(self.c,review)
        self.assertEqual(before,self.rows());self.patches[-1].assert_called_once()


if __name__=='__main__':unittest.main()
