"""Non-native regression checks; no terminal/network/credential operations."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import io
import contextlib
import sys
import subprocess
from unittest.mock import patch

import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_prepare as prep
import goat_demo_pair_orchestrate as o
import goat_demo_pair_profile as p
import goat_demo_pair_readiness as r
import goat_demo_pair_restart as restart
import goat_demo_pair_lifecycle as life


def row(n):
    return dict(terminal=n, directory=rf'C:\GOAT Experiment\{n:02d} - Balanced 35 - AI '+('OFF' if n==7 else 'ON'),
                login=c.PAIR_ACCOUNTS[n],server='Darwinex-Demo',currency='USD',leverage=200,
                terminalSha256='1'*64,eaSha256='2'*64,profile='Default',profileSha256='3'*64,
                commonIniSha256='4'*64,savedAlgoEnabled=False,expertRelativePath=c.EXPERT_RELATIVE,
                credentialRelativePath=c.CREDENTIAL_RELATIVE,buildId=c.BUILD_ID)


def fixture():
    return {'schema':'goat-demo-pair-connection-v1','terminals':[row(7),row(8)]}


def saved_profile(root,ai=False):
    folder=root/'MQL5/Profiles/Charts/Default';folder.mkdir(parents=True)
    dashboard=prep.fresh_chart().decode('utf16').replace('<chart>','<chart>\r\nid=999',1)
    (folder/'chart00.chr').write_bytes(dashboard.encode('utf16'))
    reg=dict(aiMode=2 if ai else 0,aiThreshold=50,aiProtocol=2,members=[]);audit=dict(rows=[])
    for i in range(35):
        source=('Mode_Operation=9\nEA_Desc=Strategy '+str(i)+'\nRisk=500.0\nMode_Bias=1\nBias_Protocol=2\n'
                'Bias_threshold=50\nMode_Bias_Trades=0\nDownload_StartDate=2025.01.01\nActive_Time_ASIA=01:30-11:00\n')
        path=root/f'member{i}.set';path.write_bytes(source.encode('utf16'))
        symbol='EURUSD' if i%2 else 'USDJPY';cid=1000+i
        member=dict(index=i,path=str(path),symbol=symbol,sha256=p.digest(path.read_bytes()))
        reg['members'].append(member);audit['rows'].append(dict(index=i,symbol=symbol,chartId=cid,magic=2000+i,settingsMatch=True))
        inputs=p.effective_inputs(member,reg)
        inputs['Risk']='500.000';inputs['Download_StartDate']='2025.01.01 00:00:00'
        text='<chart>\nid='+str(cid)+'\nsymbol='+symbol+'\nperiod_type=0\nperiod_size=1\n<expert>\nname=GOAT V1.48\npath=Experts\\GOAT Experiment\\GOAT V1.48.ex5\nexpertmode=5\n<inputs>\n'
        text+='\n'.join(k+'='+v for k,v in inputs.items())+'\n</inputs>\n</expert>\n</chart>\n'
        (folder/f'child{i:02d}.chr').write_bytes(text.encode('utf16'))
    return folder,reg,audit


def persistence_fixture(root):
    target=row(7);target.update(directory=str(root),savedAlgoEnabled=True)
    (root/'bases').mkdir();(root/'bases/gvariables.dat').write_bytes(b'closed native global bytes')
    state=root/'Common/GOAT'/('dashboard_state_'+root.name+'.tsv');state.parent.mkdir(parents=True);state.write_bytes(b'closed audited dashboard bytes')
    proof=dict(schema='goat-demo-pair-persistence-v1',terminal=7,account=target['login'],directory=str(root),buildId=target['buildId'],
        eaSha256=target['eaSha256'],profileSha256=target['profileSha256'],commonIniSha256=target['commonIniSha256'],
        registrationSha256='a'*64,pairedProofSha256='b'*64,createdAtUtc=1000,process=dict(pid=10,path=str(root/'terminal64.exe'),created='x'),
        shutdownId='c'*32,globalsSha256=p.digest((root/'bases/gvariables.dat').read_bytes()),dashboardStatePath=str(state),dashboardStateSha256=p.digest(state.read_bytes()))
    path=root/'enabled-persistence.json';g.write_new(path,proof)
    return target,path,p.digest(path.read_bytes()),proof


class ManifestTests(unittest.TestCase):
    def test_exact_pair_and_collector_api(self):
        self.assertEqual([x['id'] for x in c.validate_pair_manifest(fixture())],['control','ai'])
    def test_old_account_refused(self):
        v=fixture();v['terminals'][0]['login']=3000109420
        with self.assertRaises(c.Refused):c.validate_manifest(v)
    def test_old_terminal_refused(self):
        v=fixture();v['terminals'][0]['directory']=r'C:\GOAT Experiment\01 - Standard - Clean R5'
        with self.assertRaises(c.Refused):c.validate_manifest(v)
    def test_placeholder_hash_refused(self):
        v=fixture();v['terminals'][0]['eaSha256']='0'*64
        with self.assertRaises(c.Refused):c.validate_manifest(v)
    def test_wrong_namespace_refused(self):
        v=fixture();v['terminals'][1]['credentialRelativePath']='GOAT/Credentials/api-bearer.token'
        with self.assertRaises(c.Refused):c.validate_manifest(v)
    def test_vault_order_and_old_six_refused(self):
        rows=c.validate_manifest(fixture());v=[dict(login=x['login'],server=x['server'],master='test-secret') for x in rows]
        c.validate_vault(v,rows)
        with self.assertRaises(c.Refused):c.validate_vault(v[::-1],rows)
        with self.assertRaises(c.Refused):c.validate_vault(v*3,rows)
    def test_fresh_chart_has_no_inherited_identity(self):
        txt=prep.fresh_chart().decode('utf-16')
        self.assertNotIn('\nid=',txt);self.assertNotIn('magic=',txt)
        self.assertEqual(p.chart_resume_role(prep.fresh_chart(),Path('C:/x')),'dashboard')
        self.assertIn('GOAT V1.48.ex5',txt)
        self.assertNotIn('<expert>',prep.bare_chart().decode('utf16'))
    def test_fresh_common_inert_exact_account(self):
        txt=prep.fresh_common(3000109421).decode('utf16')
        self.assertIn('Enabled=0',txt);self.assertNotIn('Password',txt)
        updated=p.patch_common(prep.fresh_common(3000109421),3000109421,1).decode('utf16')
        self.assertIn('Enabled=1',updated)
        with self.assertRaises(c.Refused):p.patch_common(prep.fresh_common(3000109421),3000109427,1)
    def test_readonly_snapshot_wrong_runtime_refused(self):
        from types import SimpleNamespace as S
        class SDK:
            ACCOUNT_TRADE_MODE_DEMO=0;ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2
            def account_info(self):return S(login=3000109427,server='Darwinex-Demo',trade_mode=0,margin_mode=2,currency='USD',leverage=200)
            def terminal_info(self):return S(data_path=r'C:\other',path=r'C:\other',trade_allowed=False,connected=True)
        with self.assertRaises(c.Refused):c.snapshot(SDK(),row(7))
    def test_claim_is_exclusive_and_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'intent.json';g.claim_once(path,{'target':'deploy:0'})
            with self.assertRaises(FileExistsError):g.claim_once(path,{'target':'deploy:0'})
            self.assertEqual(g.read(path)['target'],'deploy:0')
    def test_timestamp_fraction_equivalence(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();procs=[dict(pid=i+1,path=rf'C:\old{i}\terminal64.exe',created='2026-09-24T01:00:00.100000Z') for i in range(6)]
            witness=dict(schema='goat-protected-six-v1',observedAtUtc=now-1,expiresAtUtc=now+30,processes=procs,lifecycleLock=r'C:\shared.lock')
            path=Path(tmp)/'w.json';g.write_new(path,witness)
            actual=copy.deepcopy(procs)
            for item in actual:item['created']='2026-09-24T01:00:00.1000000+00:00'
            with patch.object(g,'all_processes',return_value=actual):g.checked_witness(path,None)
            actual[0]['pid']=99
            with patch.object(g,'all_processes',return_value=actual),self.assertRaises(c.Refused):g.checked_witness(path,None)
    def test_admission_missing_refused(self):
        with self.assertRaises(c.Refused):g.verify_admission(None,None,row(8))
    def test_admission_bad_hash_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.json';g.write_new(path,{'fake':'proof'})
            with self.assertRaises(c.Refused):g.verify_admission(path,'0'*64,row(8))
    def test_admission_time_and_api_hashes(self):
        value=dict(schemaVersion=1,buildId=c.BUILD_ID,artifactSHA256='8fec6e0379be4f2657f3c425ec1cf2e1701d3a65324e39576dcdcb6405833b0d',
                   compileReceiptSHA256='ad9617637b9733e1c2c9c72ec5bf1bfe9575613848978d242e9dd5bd9a454fab',sourceCommit='e96465d590690178176e55c51ff3c1bc8a363fde',
                   allowedAccountIds=[3000109421,3000109427],notBeforeMs=1000000,expiresAtMs=1000000+7*86400000,
                   backendRelease=dict(runId='run-fixture',attemptId='attempt-fixture',sourceCommit='b'*40,publishedRecordSHA256='c'*64,canaryState='PASS',
                                       api=dict(verificationSHA256='d'*64,sourceTreeSHA256='e'*64,packageSHA256='f'*64)),registrySHA256='a'*64)
        target=row(8);target['eaSha256']=value['artifactSHA256']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'proof.json'
            def verify(v):
                path.write_bytes(g.encoded(v));return g.verify_admission(path,hashlib.sha256(path.read_bytes()).hexdigest(),target,now=1001)
            verify(value)
            bad=copy.deepcopy(value);bad['expiresAtMs']+=1
            with self.assertRaises(c.Refused):verify(bad)
            bad=copy.deepcopy(value);bad['backendRelease']['api']['packageSHA256']='0'*64
            with self.assertRaises(c.Refused):verify(bad)
            bad=copy.deepcopy(value);del bad['backendRelease']['api']['verificationSHA256']
            with self.assertRaises(c.Refused):verify(bad)
    def test_initial_existing_process_refused_before_sdk(self):
        class Host:
            def processes(self,row):return [dict(pid=10,path='x',created='x')]
        with self.assertRaises(c.Refused):c.reconnect(None,Host(),row(7),{},True,verifier=lambda *a:None,initial=True)
    def test_initial_funds_mismatch_retained(self):
        from types import SimpleNamespace as S
        target=row(7)
        class Host:
            live=False
            def processes(self,row):return [dict(pid=10,path='x',created='x')] if self.live else []
            def launch(self,row):self.live=True;return self.processes(row)[0]
        class SDK:
            ACCOUNT_TRADE_MODE_DEMO=0;ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2
            def initialize(self,*a,**kw):return True
            def shutdown(self):pass
            def account_info(self):return S(login=target['login'],server=target['server'],trade_mode=0,margin_mode=2,currency='USD',leverage=200,balance=99000,equity=99000,trade_allowed=True)
            def terminal_info(self):return S(data_path=target['directory'],path=target['directory'],trade_allowed=False,connected=True)
            def positions_get(self):return []
            def orders_get(self):return []
        audit={}
        with self.assertRaises(c.Refused):c.reconnect(SDK(),Host(),target,{'master':'test'},True,verifier=lambda *a:None,audit=audit,initial=True)
        self.assertEqual(audit['after']['balance'],99000)


class DeploymentTests(unittest.TestCase):
    def test_cli_guard_refusal_preserves_reason_without_native_calls(self):
        # Missing witness is rejected before any process probe, file verification,
        # SDK import or launch. Exercise the real __main__/import class boundary.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'manifest.json';g.write_new(manifest,fixture())
            vault=[dict(login=item['login'],server=item['server'],master='fixture-only') for item in fixture()['terminals']]
            result=subprocess.run([sys.executable,'-B',str(Path(c.__file__)),
                '--manifest',str(manifest),'--terminal','7','--sdk-path',str(root),
                '--attempt-dir',str(root/'attempt'),'--protected-witness',str(root/'missing.json'),'--initial-login'],
                input=json.dumps(vault),text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,2)
            value=json.loads(result.stdout);self.assertEqual(value['reason'],'unsafe_evidence_file')
            self.assertFalse((root/'attempt').exists());self.assertNotIn('fixture-only',result.stdout)
    def test_prepare_os_error_diagnostic_does_not_expose_message(self):
        def fail(*args):
            args[4]['stage']='acquire_lifecycle_lock'
            raise FileExistsError(17,'SENSITIVE_EXCEPTION_MESSAGE','SENSITIVE_PATH')
        output=io.StringIO()
        with patch.object(sys,'argv',['prepare','--plan','p','--protected-witness','w','--apply']),patch.object(prep,'read',return_value={}),patch.object(prep,'prepare',side_effect=fail),contextlib.redirect_stdout(output):
            self.assertEqual(prep.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual(result['stage'],'acquire_lifecycle_lock')
        self.assertEqual(result['exceptionType'],'FileExistsError');self.assertEqual(result['errno'],17)
        self.assertNotIn('SENSITIVE',output.getvalue())
    def test_connect_busy_lock_does_not_claim_or_expose_error(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=fixture()['terminals'];rows[0]['directory']=str(root/'07 - Test')
            manifest=root/'manifest.json';g.write_new(manifest,fixture());out=root/'attempt';output=io.StringIO()
            args=['connect','--manifest',str(manifest),'--terminal','7','--sdk-path',str(root),
                  '--attempt-dir',str(out),'--protected-witness',str(root/'w.json'),'--initial-login','--allow-closed']
            with patch.object(sys,'argv',args),patch.object(sys,'stdin',S(buffer=io.BytesIO(b'[]'))),patch.dict(sys.modules,{'MetaTrader5':S()}),\
                 patch.object(c,'validate_manifest',return_value=rows),patch.object(c,'validate_vault',return_value=[{},{}]),\
                 patch.object(c,'verify_files'),patch.object(c,'WindowsHost',return_value=S(processes=lambda row:[])),\
                 patch.object(g,'checked_witness',return_value={}),patch.object(g,'assert_new_pair_paths'),\
                 patch.object(g,'lifecycle_lock',side_effect=FileExistsError(17,'SENSITIVE_ERROR','SENSITIVE_PATH')),\
                 patch.object(g,'claim_once') as claim,contextlib.redirect_stdout(output):
                self.assertEqual(c.main(),2);claim.assert_not_called()
            value=json.loads(output.getvalue());self.assertEqual(value['stage'],'acquire_lifecycle_lock')
            self.assertEqual(value['exceptionType'],'FileExistsError');self.assertEqual(value['errno'],17)
            self.assertNotIn('SENSITIVE',output.getvalue());self.assertEqual(g.read(out/'result.json'),value)
    def test_partial_id_and_duplicate_chart_fail(self):
        v={'rows':[dict(chartId=1,magic=0)]}
        with self.assertRaises(o.Stop):o.count_attached(v)
        v={'rows':[dict(chartId=1,magic=2),dict(chartId=1,magic=3)]}
        with self.assertRaises(o.Stop):o.count_attached(v)
    def test_retained_mutation_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=o.Journal(Path(tmp));journal.add('intent',target='deploy:0')
            class API:
                def request(self,a):raise AssertionError('mutation repeated')
            runner=o.Runner(API(),{},journal)
            with self.assertRaises(o.Stop):runner.call('deploy_next','deploy:0')
    def test_journal_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);journal=o.Journal(path);journal.add('intent',target='deploy:0')
            (path/'journal.jsonl').write_bytes((path/'journal.jsonl').read_bytes()[:-1])
            with self.assertRaises(o.Stop):o.Journal(path)
    def test_profile_requires35_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root)
            digest,claims=p.profile_claims(root,c,reg,audit);self.assertEqual(len(claims),36)
            (folder/'child34.chr').unlink()
            with self.assertRaises(c.Refused):p.profile_claims(root,c,reg,audit)
    def test_profile_ai_effective_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root,ai=True)
            p.profile_claims(root,c,reg,audit)
            path=folder/'child00.chr';text=path.read_bytes().decode('utf16')
            path.write_bytes(text.replace('Mode_Bias=2','Mode_Bias=1').encode('utf16'))
            with self.assertRaises(c.Refused):p.profile_claims(root,c,reg,audit)
    def test_profile_saved_child_drift_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root);path=folder/'child00.chr';original=path.read_bytes().decode('utf16')
            changes=[('Risk=500.000','Risk=500.00000000000001'),('EA_Desc=Strategy 0','EA_Desc=Strategy 1'),
                ('id=1000','id=1001'),('id=1000','id=999999'),('id=1000\n',''),('symbol=USDJPY','symbol=GBPUSD'),
                ('period_size=1','period_size=5'),('period_type=0','period_type=1'),('expertmode=5','expertmode=4'),
                ('Mode_Bias=1','Mode_Bias=2'),('Bias_Protocol=2','Bias_Protocol=1'),('Bias_threshold=50','Bias_threshold=60'),
                ('Mode_Bias_Trades=0','Mode_Bias_Trades=1'),('Risk=500.000','Risk=500.000\nRisk=500.000'),
                ('Risk=500.000','Risk=500.000\nUnknown=0'),('Risk=500.000\n',''),
                ('Active_Time_ASIA=01:30-11:00','Active_Time_ASIA=01:30-12:00'),('</chart>',''),
                ('</chart>','</chart>\n<chart>\n</chart>'),('<inputs>','<inputs>\n<inputs>'),
                ('Dashboard_Resume_Saved=false','Dashboard_Resume_Saved=true')]
            for before,after in changes:
                with self.subTest(after=after):
                    path.write_bytes(original.replace(before,after,1).encode('utf16'))
                    with self.assertRaises(c.Refused):p.profile_claims(root,c,reg,audit)
            path.write_bytes(original.encode('utf16'))
            source=Path(reg['members'][0]['path']);source.write_bytes(source.read_bytes()+b'\n\x00')
            with self.assertRaises(c.Refused):p.profile_claims(root,c,reg,audit)
    def test_profile_duplicate_clones_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root)
            (folder/'child01.chr').write_bytes((folder/'child00.chr').read_bytes())
            with self.assertRaises(c.Refused):p.profile_claims(root,c,reg,audit)
    def test_input_normalization_matches_native(self):
        self.assertTrue(p.input_equal('Risk','+00500.00','500'))
        self.assertTrue(p.input_equal('Risk','-0.0','0'))
        self.assertTrue(p.input_equal('Download_StartDate','2025.01.01','2025.01.01 00:00'))
        for name,left,right in [('Risk','1e3','1000'),('Risk','1','1.0000000001'),('EA_Desc','001','1'),('Risk','NaN','nan')]:
            self.assertFalse(p.input_equal(name,left,right))
    def test_enabled_persistence_changes_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,path,sha,proof=persistence_fixture(root)
            p.verify_enabled_persistence(target,path,sha,now=1001)
            for file in (root/'bases/gvariables.dat',Path(proof['dashboardStatePath'])):
                original=file.read_bytes();file.write_bytes(original+b'changed')
                with self.assertRaises(c.Refused):p.verify_enabled_persistence(target,path,sha,now=1001)
                file.write_bytes(original)
            for key in ('login','profileSha256','commonIniSha256','eaSha256'):
                changed=copy.deepcopy(target);changed[key]=0 if key=='login' else '9'*64
                with self.assertRaises(c.Refused):p.verify_enabled_persistence(changed,path,sha,now=1001)
            with self.assertRaises(c.Refused):p.verify_enabled_persistence(target,None,None,now=1001)
            with self.assertRaises(c.Refused):p.verify_enabled_persistence(target,path,'9'*64,now=1001)
            with self.assertRaises(c.Refused):p.verify_enabled_persistence(target,path,sha,now=1601)
            with self.assertRaises(c.Refused):p.verify_enabled_persistence(target,path,sha,now=999)
    def test_enabled_start_requires_proof_before_launch(self):
        class Host:
            def processes(self,row):return []
            def launch(self,row):raise AssertionError('unverified launch')
        target=row(7);target['savedAlgoEnabled']=True
        with self.assertRaises(c.Refused):c.reconnect(None,Host(),target,{},True,verifier=lambda *a:None)
    def test_freeze_rejects_changed_profile_before_enable(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=row(7);target['directory']=str(root)
            (root/'config').mkdir();(root/'config/common.ini').write_bytes(prep.fresh_common(target['login']))
            proof_path=root/'proof.json';g.write_new(proof_path,{'fixture':'paired'})
            proof=dict(proof=dict(capturedAtUtc=100,process={'pid':10}),audit={})
            shutdown=dict(result='shutdown_requested',account=target['login'],directory=str(root),buildId=target['buildId'],
                connected=True,tradingAllowed=False,positions=0,orders=0,charts=36,observedAtUtc=101,id='a'*32)
            g.write_new(root/(shutdown['id']+'.json'),shutdown)
            rehearsal=dict(status='restart_policy_paired_ready',members=35,process={'pid':10},pairedProofSha256=p.digest(proof_path.read_bytes()))
            g.write_new(root/'rehearsal.json',rehearsal)
            args=S(operation='freeze-on',proof=proof_path,shutdown=root/(shutdown['id']+'.json'),rehearsal=root/'rehearsal.json',manifest=root/'manifest.json')
            api=S(module=S(setup=S(scope=lambda m:(None,root))),installation={},reg={},digest='a'*64,manifest=root/'manifest.json')
            host=S(processes=lambda row:[])
            before=(root/'config/common.ini').read_bytes()
            with patch.object(r,'verify_stored_pair',return_value=proof),patch.object(p,'profile_claims',side_effect=c.Refused('profile_effective_inputs')),patch.object(life,'replace_preserving_acl') as replace:
                with self.assertRaisesRegex(c.Refused,'profile_effective_inputs'):life.operate(args,[target],target,api,host,{})
                replace.assert_not_called()
            self.assertEqual((root/'config/common.ini').read_bytes(),before)


class ReadinessTests(unittest.TestCase):
    def build(self):
        now=int(time.time()); installation=dict(account=3000109421,server='Darwinex-Demo',directory=row(8)['directory'],buildId=c.BUILD_ID,eaSha256='2'*64)
        reg=dict(aiMode=2,aiThreshold=50,aiProtocol=2,exposureMode=0,members=[{} for _ in range(35)])
        rows=[dict(index=i,symbol='EURUSD',chartId=i+100,magic=i+1,linkedFresh=True,settingsMatch=True,exposureMode=0,ackId=10,ackStatus=1,AI_MODE=2,AI_PROTOCOL=2,AI_THRESHOLD=50,AI_SCOPE=0,AI_VERIFIED=1,AI_AVAILABLE=0,AI_AT=now,EA_TRADE_ALLOWED=1) for i in range(35)]
        common=dict(registrationSha256='c'*64,result='observed',connected=True,tradingAllowed=False,positions=0,orders=0,commandPending=False,commandId=10,observedAtUtc=now,rows=rows,aiMode=2,aiProtocol=2,aiThreshold=50)
        audit=dict(common,id='a'*32,action='audit');status=copy.deepcopy(dict(common,id='b'*32,action='status'))
        process=dict(pid=10,created='2026-01-01T00:00:00Z',path=installation['directory']+'\\terminal64.exe')
        class API:
            def verify_receipt(self,*args):pass
        return API(),audit,status,reg,installation,now,process
    def test_verified_withheld_ai_valid(self):
        args=self.build();self.assertEqual(r.verify_pair(*args)['members'],35)
    def test_missing_settings_refused(self):
        args=self.build();args[1]['rows'][2]['settingsMatch']=False
        with self.assertRaises(r.Refused):r.verify_pair(*args)
    def test_stale_ai_not_forgiven(self):
        args=self.build();args[2]['rows'][3]['AI_AT']-=31
        with self.assertRaises(r.FreshnessPending):r.verify_pair(*args)
    def test_child_identity_replacement_refused(self):
        args=self.build();args[2]['rows'][3]['magic']=999
        with self.assertRaises(r.Refused):r.verify_pair(*args)
    def test_live_algo_cannot_pass_inert_ready(self):
        args=self.build();args[2]['tradingAllowed']=True
        with self.assertRaises(r.Refused):r.verify_pair(*args)
    def test_old33_refused(self):
        args=self.build();args[3]['members']=args[3]['members'][:33]
        with self.assertRaises(r.Refused):r.verify_pair(*args)

if __name__=='__main__':unittest.main(verbosity=2)
