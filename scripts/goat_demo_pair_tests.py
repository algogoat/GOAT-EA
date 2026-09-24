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
import goat_demo_pair_trust as trust
import goat_demo_pair_dashboard_recapture as recapture
import goat_demo_pair_recover_child as recovery


def row(n):
    return dict(terminal=n, directory=rf'C:\GOAT Experiment\{n:02d} - Balanced 35 - AI '+('OFF' if n==7 else 'ON'),
                login=c.PAIR_ACCOUNTS[n],server='Darwinex-Demo',currency='USD',leverage=200,
                terminalSha256='1'*64,eaSha256=c.BUILDS[c.BUILD_ID]['artifactSHA256'],profile='Default',profileSha256='3'*64,
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
    def test_lifecycle_lock_timeout_preserves_other_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shared.lock';other=b'other owner';path.write_bytes(other)
            clock=[0.0];sleeps=[]
            def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
            with patch.object(g.time,'monotonic',side_effect=lambda:clock[0]),patch.object(g.time,'sleep',side_effect=sleep),\
                 patch.object(g,'claim_once') as claim:
                with self.assertRaisesRegex(c.Refused,'lifecycle_lock_busy'):
                    with g.lifecycle_lock({'lifecycleLock':str(path)}):g.claim_once(Path(tmp)/'startup.json',{})
                claim.assert_not_called()
            self.assertEqual(path.read_bytes(),other);self.assertEqual(clock[0],20)
            self.assertTrue(sleeps and max(sleeps)<=0.25)
    def test_lifecycle_lock_temporary_contention_then_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shared.lock';path.write_bytes(b'other owner');clock=[0.0]
            def release(seconds):clock[0]+=seconds;path.unlink()
            with patch.object(g.time,'monotonic',side_effect=lambda:clock[0]),patch.object(g.time,'sleep',side_effect=release):
                with g.lifecycle_lock({'lifecycleLock':str(path)}):
                    value=g.read(path);self.assertEqual(value['kind'],'demo-pair');self.assertEqual(len(value['nonce']),32)
            self.assertFalse(path.exists())
    def test_lifecycle_lock_changed_owner_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shared.lock'
            with self.assertRaisesRegex(c.Refused,'lifecycle_lock_owner_changed'):
                with g.lifecycle_lock({'lifecycleLock':str(path)}):
                    path.write_bytes(b'new owner')
            self.assertEqual(path.read_bytes(),b'new owner')
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


class TrustTests(unittest.TestCase):
    def source(self):
        return prep.fresh_common(c.PAIR_ACCOUNTS[7]).decode('utf16').replace(
            'WebRequest=0\r\nWebRequestUrl=', 'WebRequest=1\r\nWebRequestUrl='+'aB'*48).encode('utf16')
    def test_fresh_permission_is_honestly_disabled(self):
        text=prep.fresh_common(c.PAIR_ACCOUNTS[7]).decode('utf16')
        self.assertIn('WebRequest=0\r\nWebRequestUrl=\r\n',text)
        self.assertNotIn('https://',text)
    def test_permission_patch_changes_only_two_records(self):
        source=self.source()
        for legacy in (False,True):
            text=prep.fresh_common(c.PAIR_ACCOUNTS[8]).decode('utf16')+'[Private]\r\nOpaque=keep-exact\r\n'
            if legacy:text=text.replace('WebRequest=0\r\nWebRequestUrl=', 'WebRequest=1\r\nWebRequestUrl=https://goatedge.ai')
            before=text.encode('utf16');after=trust.patch_trust(before,source)
            expected=text.replace('WebRequest=0','WebRequest=1').replace(
                'WebRequestUrl='+('https://goatedge.ai' if legacy else ''),'WebRequestUrl='+'aB'*48).encode('utf16')
            self.assertEqual(after,expected)
            self.assertEqual(p.patch_common(after,c.PAIR_ACCOUNTS[8],0),after)
            self.assertEqual(source,self.source())
            with self.assertRaises(c.Refused):trust.patch_trust(after,source)
    def test_source_permission_requires_approved_native_format(self):
        source=self.source().decode('utf16');target=prep.fresh_common(c.PAIR_ACCOUNTS[7])
        for change in (source.replace('WebRequest=1','WebRequest=0'),source.replace('aB'*48,'https://goatedge.ai'),
                       source.replace('aB'*48,'a'*15),source.replace('[Experts]','[Experts]\r\nWebRequest=1'),
                       source.replace('WebRequest=1','WebRequest=1\r\nwebrequest=1')):
            with self.subTest(change=change[:30]),self.assertRaises((c.Refused,trust.configparser.Error)):
                trust.patch_trust(target,change.encode('utf16'))
        # Native record length is not a fixed URL length; actual source is hash-pinned.
        trust.patch_trust(target,source.replace('aB'*48,'aB'*42).encode('utf16'))
    def test_trust_shutdown_exact_inert_activation_dashboard(self):
        target=row(7);now=int(time.time())
        receipt=dict(schema=1,id='a'*32,result='shutdown_requested',account=target['login'],server=target['server'],
            directory=target['directory'],buildId=target['buildId'],observedAtUtc=now,
            connected=True,tradingAllowed=False,activationOnly=True,positions=0,orders=0,charts=1)
        trust.shutdown_state(receipt,target)
        changes={'activationOnly':False,'connected':False,'tradingAllowed':True,'positions':1,'orders':1,
                 'charts':36,'account':target['login']+1,'server':'Other','directory':'C:/Other','observedAtUtc':now-14401,
                 'schema':True,'id':'../other','result':'observed'}
        for key,value in changes.items():
            with self.subTest(key=key),self.assertRaises(c.Refused):trust.shutdown_state(dict(receipt,**{key:value}),target)
    def test_target_existing_permissions_and_ambiguity_refused(self):
        target=prep.fresh_common(c.PAIR_ACCOUNTS[7]).decode('utf16');source=self.source()
        for change in (target.replace('Enabled=0','Enabled=1'),target.replace('WebRequestUrl=','WebRequestUrl=https://other.example'),
                       target.replace('WebRequest=0','WebRequest=1'),target.replace('WebRequest=0','WebRequest=0\r\nWebRequest=0'),
                       target.replace('[Experts]','[Experts]\r\n[experts]\r\nEnabled=0'),target.replace('WebRequestUrl=\r\n','')):
            with self.subTest(change=change[:30]),self.assertRaises((c.Refused,trust.configparser.Error)):
                trust.patch_trust(change.encode('utf16'),source)
        with self.assertRaises(c.Refused):trust.patch_trust(target.encode(),source)
    def test_trust_run_dry_and_retained_output_do_not_write(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'trust';plan={'outputDirectory':str(out)}
            args=S(plan=root/'plan.json',protected_witness=root/'witness.json',apply=False)
            with patch.object(g,'read',return_value=plan),patch.object(trust,'inspect',return_value=({},[],[])),\
                 patch.object(c,'WindowsHost'),patch.object(trust,'replace_preserving_acl') as replace:
                self.assertEqual(trust.run(args)['status'],'dry_run_passed');replace.assert_not_called()
                self.assertFalse(out.exists());out.mkdir();args.apply=True
                with self.assertRaisesRegex(c.Refused,'retained_migration_requires_review'):trust.run(args)
                replace.assert_not_called()
    def test_trust_run_refuses_changed_state_after_lock(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'trust';args=S(plan=root/'plan.json',protected_witness=root/'witness.json',apply=True)
            with patch.object(g,'read',return_value={'outputDirectory':str(out)}),patch.object(c,'WindowsHost'),\
                 patch.object(trust,'inspect',side_effect=[({'revision':1},[],[]),({'revision':2},[],[])]),\
                 patch.object(g,'lifecycle_lock',return_value=contextlib.nullcontext()),patch.object(trust,'replace_preserving_acl') as replace:
                with self.assertRaisesRegex(c.Refused,'migration_state_changed'):trust.run(args)
                replace.assert_not_called();self.assertFalse(out.exists())


class DashboardRecaptureTests(unittest.TestCase):
    def test_exact_dashboard_inputs_and_full_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'MQL5/Profiles/Charts/Default';folder.mkdir(parents=True)
            chart=prep.fresh_chart().decode('utf16').replace('<chart>','<chart>\r\nid=123',1)
            chart=chart.replace('</inputs>','NativeExpandedDefault=42\r\n</inputs>');path=folder/'chart01.chr'
            path.write_bytes(chart.encode('utf16'));target=dict(directory=str(root))
            files,proof,claims,sha=recapture.snapshot_profile(target,123)
            self.assertEqual(files['chart01.chr'],chart.encode('utf16'));self.assertEqual(proof['expandedInputCount'],6)
            self.assertEqual(len(proof['explicitInputs']),5);self.assertEqual(len(sha),64)
            changes=[('id=123','id=124'),('symbol=EURUSD','symbol=USDJPY'),('period_size=1','period_size=5'),
                     ('expertmode=5','expertmode=4'),('GOAT V1.48.ex5','GOAT V1.47.ex5'),('Mode_Operation=8','Mode_Operation=9'),
                     ('Dashboard_Resume_Saved=true','Dashboard_Resume_Saved=false'),('Mode_Bias=1','Mode_Bias=2'),
                     ('Bias_Protocol=2','Bias_Protocol=1'),('Bias_threshold=50','Bias_threshold=60')]
            for before,after in changes:
                path.write_bytes(chart.replace(before,after).encode('utf16'))
                with self.subTest(after=after),self.assertRaises(c.Refused):recapture.snapshot_profile(target,123)
            path.write_bytes(chart.encode('utf16'));(folder/'extra.chr').write_bytes(path.read_bytes())
            with self.assertRaisesRegex(c.Refused,'one_dashboard_only'):recapture.snapshot_profile(target,123)
    def test_extra_default_is_preserved_not_claimed_prior_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'MQL5/Profiles/Charts/Default';folder.mkdir(parents=True)
            chart=prep.fresh_chart().decode('utf16').replace('<chart>','<chart>\r\nid=123',1)
            path=folder/'chart01.chr';path.write_bytes(chart.encode('utf16'));target=dict(directory=str(root))
            before=recapture.snapshot_profile(target,123)
            path.write_bytes(chart.replace('</inputs>','ExpandedUnknown=retained\r\n</inputs>').encode('utf16'))
            after=recapture.snapshot_profile(target,123)
            self.assertNotEqual(before[1]['expandedInputsSha256'],after[1]['expandedInputsSha256'])
            self.assertEqual(after[1]['explicitInputs'],before[1]['explicitInputs'])


class PartialRecoveryTests(unittest.TestCase):
    def failure(self):
        return dict(action='deploy_next',result='child_attach_failed',connected=True,tradingAllowed=False,positions=0,orders=0,commandPending=False,
            rows=[dict(index=i,symbol='EURUSD',chartId=1000+i if i<=6 else 0,magic=2000+i if i<6 else 0,linkedFresh=i<6) for i in range(35)])
    def test_failure_scope_refuses_other_outcomes(self):
        failure=self.failure();registration={'members':[dict(symbol='EURUSD') for _ in range(35)]}
        recovery.failure_scope(failure,registration)
        for key,value in [('tradingAllowed',True),('positions',1),('orders',1),('result','child_attached'),('connected',False)]:
            with self.subTest(key=key),self.assertRaises(c.Refused):recovery.failure_scope(dict(failure,**{key:value}),registration)
        for index,key,value in [(6,'magic',777),(7,'chartId',999),(0,'linkedFresh',False),(2,'chartId',1000)]:
            changed=copy.deepcopy(failure);changed['rows'][index][key]=value
            with self.subTest(index=index,key=key),self.assertRaises(c.Refused):recovery.failure_scope(changed,registration)
    def test_empty_orphan_has_no_expert_or_other_chart(self):
        text='<chart>\r\nid=0\r\nsymbol=EURUSD\r\nperiod_type=0\r\nperiod_size=1\r\nwindows_total=0\r\n</chart>\r\n'
        recovery.empty_chart(text.encode('utf16'),1006)
        for changed in [text.replace('id=0','id=1000'),text.replace('windows_total=0','windows_total=1'),
                        text.replace('</chart>','<expert>\r\n</expert>\r\n</chart>'),text+text]:
            with self.assertRaises(c.Refused):recovery.empty_chart(changed.encode('utf16'),1006)
    def test_only_failed_state_identity_changes(self):
        failure=self.failure();members=[dict(path=f'C:/sets/{i}.set',symbol='EURUSD') for i in range(35)]
        lines=['#GOAT_AI_LAUNCH_V147_2\t0\t50\t2']
        for member,child in zip(members,failure['rows']):lines.append('\t'.join([member['path'],'name','EURUSD','strategy','OFF','OFF','Risk $500',str(child['chartId']),str(child['magic'])]))
        before=('\r\n'.join(lines)+'\r\n').encode('utf16');after=recovery.reset_state(before,dict(members=members),failure)
        self.assertEqual(after,before.replace('\t1006\t0\r\n'.encode('utf-16-le'),'\t0\t0\r\n'.encode('utf-16-le')))
        with self.assertRaises(c.Refused):recovery.reset_state(after,dict(members=members),failure)
    def test_six_saved_children_remain_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root)
            for i in range(6,35):(folder/f'child{i:02d}.chr').unlink()
            failure=self.failure()
            for i,member in enumerate(reg['members']):failure['rows'][i]['symbol']=member['symbol']
            orphan=folder/'empty.chr';orphan.write_bytes('<chart>\nid=0\nsymbol=EURUSD\nperiod_type=0\nperiod_size=1\nwindows_total=0\n</chart>\n'.encode('utf16'))
            files=recovery.saved_prefix(root,reg,failure,orphan);self.assertEqual(len(files),8)
            good=folder/'child00.chr';good.write_bytes(good.read_bytes().replace('Risk=500.000'.encode('utf-16-le'),'Risk=600.000'.encode('utf-16-le')))
            with self.assertRaisesRegex(c.Refused,'saved_child_inputs_changed'):recovery.saved_prefix(root,reg,failure,orphan)
    def test_one_recovery_attempt_preserves_original_failed_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);journal=o.Journal(root);journal.add('intent',target='deploy:6')
            before=journal.path.read_bytes();value=self.failure();value['rows'][6]['chartId']=0
            authority={'prefix':[[r['chartId'],r['magic']] for r in value['rows'][:6]],'target':'recovery:deploy:6:'+'a'*64}
            calls=[]
            class API:
                successes={'deploy_next':{'child_attached'}}
                def request(self,action):calls.append(action);return dict(value,result='child_attach_failed')
            runner=o.Runner(API(),{},journal,True,recovery=authority)
            target=runner.deployment_target(6,value)
            with self.assertRaises(o.Stop):runner.call('deploy_next',target)
            with self.assertRaisesRegex(o.Stop,'mutation_already_attempted'):runner.call('deploy_next',target)
            self.assertEqual(len(calls),1);self.assertTrue(journal.path.read_bytes().startswith(before))
            changed=copy.deepcopy(value);changed['rows'][0]['magic']+=5
            with self.assertRaisesRegex(o.Stop,'recovery_prefix_changed'):runner.deployment_target(6,changed)
            self.assertEqual(runner.deployment_target(7,value),'deploy:7')
    def test_recovery_authority_requires_same_journal_chain(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);journal=o.Journal(root);journal.add('intent',target='deploy:6');journal.add('receipt',result='child_attach_failed',sha256='a'*64)
            proof=dict(schema=recovery.SCHEMA,status='closed_partial_repair_complete',terminal=7,index=6,registrationSha256='b'*64,
                runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(journal.path.read_bytes()),failureSha256='a'*64,
                target='recovery:deploy:6:'+'a'*64,prefix=[[1000+i,2000+i] for i in range(6)])
            path=root/'proof.json';g.write_new(path,proof);sha=p.digest(path.read_bytes())
            journal.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=sha,target=proof['target'])
            self.assertEqual(recovery.validate_authority(path,sha,journal,S(digest='b'*64)),proof)
            with self.assertRaises(c.Refused):recovery.validate_authority(path,sha,journal,S(digest='c'*64))
            journal.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=sha,target=proof['target'])
            with self.assertRaises(c.Refused):recovery.validate_authority(path,sha,journal,S(digest='b'*64))
    def test_closed_stage_preserves_files_and_appends_authority(self):
        from types import SimpleNamespace as S
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);terminal=root/'07 - fixture';folder=terminal/'MQL5/Profiles/Charts/Default';folder.mkdir(parents=True)
            (terminal/'config').mkdir();common=prep.fresh_common(c.PAIR_ACCOUNTS[7]);(terminal/'config/common.ini').write_bytes(common)
            (terminal/'bases').mkdir();(terminal/'bases/gvariables.dat').write_bytes(b'original globals')
            orphan=folder/'empty.chr';orphan.write_bytes(b'empty pinned fixture');(folder/'good.chr').write_bytes(b'unchanged good profile')
            state=root/'state.tsv';state.write_bytes(b'original state')
            run_dir=root/'deployment-07';run_dir.mkdir();journal=o.Journal(run_dir)
            journal.add('intent',target='deploy:6');journal.add('receipt',result='child_attach_failed',sha256='a'*64)
            original_journal=journal.path.read_bytes();native=root/'native';native.mkdir();api=S(root=native,digest='b'*64)
            target=row(7);target['directory']=str(terminal);rows=[target,row(8)]
            files={'empty.chr':orphan.read_bytes(),'good.chr':(folder/'good.chr').read_bytes()}
            data=dict(common=common,files=files,stateBefore=b'original state',stateAfter=b'one changed row',globals=b'original globals',
                failure=self.failure(),journalRaw=original_journal,registrationSha256=api.digest)
            plan=dict(outputDirectory=str(root/'recovery'),orphan=dict(path=str(orphan),sha256=p.digest(orphan.read_bytes())),
                state=dict(path=str(state)),failure=dict(sha256='a'*64))
            plan_path=root/'plan.json';g.write_new(plan_path,plan);witness={'lifecycleLock':str(root/'lifecycle.lock')}
            host=S(processes=lambda r:[],powershell=lambda cmd:'');args=S(plan=plan_path,protected_witness=root/'witness.json',apply=True)
            def verify(row,closed):
                claims=[[v.name,p.digest(v.read_bytes())] for v in sorted(folder.iterdir())]
                self.assertEqual(row['profileSha256'],p.digest(json.dumps(claims,separators=(',',':')).encode()))
            with patch.object(recovery,'inspect',return_value=(witness,rows,api,journal,data)),patch.object(c,'WindowsHost',return_value=host),\
                 patch.object(g,'checked_witness',return_value=witness),patch.object(c,'verify_files',side_effect=verify),\
                 patch.object(recovery,'replace_preserving_acl',side_effect=lambda path,blob:path.write_bytes(blob)):
                result=recovery.run(args)
            out=Path(plan['outputDirectory']);self.assertFalse(orphan.exists())
            self.assertEqual((out/'quarantined-empty-chart.chr').read_bytes(),files['empty.chr'])
            self.assertEqual((folder/'good.chr').read_bytes(),files['good.chr']);self.assertEqual((terminal/'config/common.ini').read_bytes(),common)
            self.assertEqual((terminal/'bases/gvariables.dat').read_bytes(),b'original globals');self.assertEqual(state.read_bytes(),b'one changed row')
            self.assertTrue(journal.path.read_bytes().startswith(original_journal));self.assertEqual(journal.records[-1]['kind'],'recovery_authorized')
            recovery.validate_authority(result['recoveryProof'],result['recoveryProofSha256'],journal,api)
            self.assertEqual(g.read(out/'reconnect-manifest.json')['terminals'][1],row(8))


class ReadinessTests(unittest.TestCase):
    def build(self):
        now=int(time.time()); installation=dict(account=3000109421,server='Darwinex-Demo',directory=row(8)['directory'],buildId=c.BUILD_ID,eaSha256=c.BUILDS[c.BUILD_ID]['artifactSHA256'])
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
