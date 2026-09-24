"""Filesystem/fake-host regression tests; no SDK, RPC or terminal operations."""
import copy, json, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_orchestrate as o
import goat_demo_pair_profile as p
import goat_demo_pair_recover_child as v1
import goat_demo_pair_recover_child_v2 as v2
from goat_demo_pair_tests import saved_profile, row


def failure():
    return dict(action='deploy_next',result='child_attach_failed',connected=True,tradingAllowed=False,positions=0,orders=0,
        commandPending=False,observedAtUtc=v2.FAILED_AT,registrationSha256='b'*64,id='e'*32,
        rows=[dict(index=i,symbol='NZDUSD' if i==26 else 'EURUSD',chartId=(1000+i if i<26 else v2.FAILED_CID if i==26 else 0),
            magic=2000+i if i<26 else 0,linkedFresh=i<26) for i in range(35)])


def chain(root):
    j=o.Journal(root);j.add('intent',target='deploy:6');j.add('receipt',result='child_attach_failed',sha256='a'*64)
    prior=dict(schema=v1.SCHEMA,status='closed_partial_repair_complete',terminal=7,index=6,registrationSha256='b'*64,
        runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(j.path.read_bytes()),failureSha256='a'*64,
        target='recovery:deploy:6:'+'a'*64,prefix=[[1000+i,2000+i] for i in range(6)])
    path=root/'prior-proof.json';g.write_new(path,prior);pin=dict(path=str(path),sha256=p.digest(path.read_bytes()))
    j.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=pin['sha256'],target=prior['target'])
    j.add('intent',target=prior['target'])
    success=failure();success.update(result='child_attached')
    for i,r in enumerate(success['rows']):r.update(chartId=1000+i if i<7 else 0,magic=2000+i if i<7 else 0)
    g.write_new(root/'receipt-prior.json',success)
    j.add('receipt',result='child_attached',attached=7,linked=7,file='receipt-prior.json',sha256=p.digest((root/'receipt-prior.json').read_bytes()))
    f=failure();g.write_new(root/'receipt-0066.json',f);raw=(root/'receipt-0066.json').read_bytes()
    j.add('intent',target='deploy:26');j.add('receipt',result='child_attach_failed',file='receipt-0066.json',sha256=p.digest(raw))
    api=S(module=S(verify_receipt=lambda *args:None),installation={},reg={'members':[dict(symbol=r['symbol']) for r in f['rows']]},digest='b'*64)
    return j,pin,raw,api


class RecoveryV2Tests(unittest.TestCase):
    def test_exact_failure_and_wrong_scope(self):
        f=failure();reg={'members':[dict(symbol=r['symbol']) for r in f['rows']]};v2.failure_scope(f,reg)
        for i,key,value in [(26,'chartId',v2.FAILED_CID+1),(26,'magic',999),(25,'linkedFresh',False),(27,'chartId',55),(0,'chartId',1001)]:
            changed=copy.deepcopy(f);changed['rows'][i][key]=value
            with self.subTest(i=i,key=key),self.assertRaises(c.Refused):v2.failure_scope(changed,reg)
        for key,value in [('observedAtUtc',v2.FAILED_AT+1),('tradingAllowed',True),('positions',1),('commandPending',True)]:
            with self.subTest(key=key),self.assertRaises(c.Refused):v2.failure_scope(dict(f,**{key:value}),reg)

    def test_only_row26_state_and_empty_nzd_chart(self):
        f=failure();members=[dict(path=f'C:/sets/{i}.set',symbol=r['symbol']) for i,r in enumerate(f['rows'])]
        lines=['#GOAT_AI_LAUNCH_V147_2\t0\t50\t2']+['\t'.join([m['path'],'name',m['symbol'],'strategy','OFF','OFF','Risk $500',str(r['chartId']),str(r['magic'])]) for m,r in zip(members,f['rows'])]
        before=('\r\n'.join(lines)+'\r\n').encode('utf16');after=v1.reset_state(before,dict(members=members),f,index=26)
        self.assertEqual(after,before.replace(f'\t{v2.FAILED_CID}\t0\r\n'.encode('utf-16-le'),'\t0\t0\r\n'.encode('utf-16-le')))
        with self.assertRaises(c.Refused):v1.reset_state(after,dict(members=members),f,index=26)
        empty='<chart>\nid=0\nsymbol=NZDUSD\nperiod_type=0\nperiod_size=1\nwindows_total=0\n</chart>\n'
        v1.empty_chart(empty.encode('utf16'),v2.FAILED_CID,'NZDUSD')
        for changed in [empty.replace('NZDUSD','EURUSD'),empty.replace('windows_total=0','windows_total=1'),empty.replace('</chart>','<expert>\n</expert>\n</chart>')]:
            with self.assertRaises(c.Refused):v1.empty_chart(changed.encode('utf16'),v2.FAILED_CID,'NZDUSD')

    def test_all26_saved_inputs_and_ids_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,reg,audit=saved_profile(root)
            for i in range(26,35):(folder/f'child{i:02d}.chr').unlink()
            f=failure()
            for i,m in enumerate(reg['members']):f['rows'][i]['symbol']=m['symbol']
            reg['members'][26]['symbol']=f['rows'][26]['symbol']='NZDUSD'
            orphan=folder/'chart28.chr';orphan.write_bytes('<chart>\nid=0\nsymbol=NZDUSD\nperiod_type=0\nperiod_size=1\nwindows_total=0\n</chart>\n'.encode('utf16'))
            self.assertEqual(len(v1.saved_prefix(root,reg,f,orphan,index=26,symbol='NZDUSD')),28)
            path=folder/'child25.chr';original=path.read_bytes()
            for changed in [original.replace('Risk=500.000'.encode('utf-16-le'),'Risk=600.000'.encode('utf-16-le')),
                            original.replace('id=1025'.encode('utf-16-le'),'id=1024'.encode('utf-16-le'))]:
                path.write_bytes(changed)
                with self.assertRaises(c.Refused):v1.saved_prefix(root,reg,f,orphan,index=26,symbol='NZDUSD')
            path.write_bytes(original);(folder/'order.wnd').write_bytes('chart28.chr\n'.encode('utf16'))
            with self.assertRaises(c.Refused):v1.saved_prefix(root,reg,f,orphan,index=26,symbol='NZDUSD')

    def test_prior_recovery_and_distinct_second_authority_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);j,pin,raw,api=chain(root);v2.journal_failure(j,raw,pin,api)
            proof=dict(schema=v2.SCHEMA,status='closed_partial_repair_complete',terminal=7,index=26,registrationSha256=api.digest,
                runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(j.path.read_bytes()),failureSha256=p.digest(raw),
                target='recovery:deploy:26:'+p.digest(raw),prefix=[list(v) for v in o.identities(json.loads(raw))[:26]],previousRecovery=pin)
            path=root/'proof.json';g.write_new(path,proof);sha=p.digest(path.read_bytes())
            j.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=sha,target=proof['target'])
            self.assertEqual(v2.validate_authority(path,sha,j,api),proof)
            v2.historical_v1(pin,j,api) # Prior evidence remains valid after the second authority.
            with self.assertRaises(c.Refused):v2.journal_failure(j,raw,pin,api)
            j.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=sha,target=proof['target'])
            with self.assertRaises(c.Refused):v2.validate_authority(path,sha,j,api)

    def test_changed_prior_receipt_or_prefix_is_not_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);j,pin,raw,api=chain(root)
            bad=json.loads(raw);bad['rows'][6]['magic']=5000;changed=g.encoded(bad)
            (root/'receipt-0066.json').write_bytes(changed);j.records[-1]['sha256']=p.digest(changed)
            with self.assertRaisesRegex(c.Refused,'first_recovery_identities_changed'):v2.journal_failure(j,changed,pin,api)
            (root/'receipt-prior.json').write_bytes(b'{}')
            with self.assertRaisesRegex(c.Refused,'prior_recovery_receipt_changed'):v2.historical_v1(pin,j,api)

    def test_second_recovery_is_one_attempt_not_generic_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);j,pin,raw,api=chain(root);value=json.loads(raw);value['rows'][26]['chartId']=0
            recovery=dict(index=26,prefix=[list(v) for v in o.identities(value)[:26]],target='recovery:deploy:26:'+p.digest(raw))
            calls=[]
            def request(action):calls.append(action);raise RuntimeError('retained unknown result')
            runner=o.Runner(S(request=request),{},j,True,recovery=recovery);target=runner.deployment_target(26,value)
            with self.assertRaises(RuntimeError):runner.call('deploy_next',target)
            with self.assertRaisesRegex(o.Stop,'mutation_already_attempted'):runner.call('deploy_next',target)
            self.assertEqual(len(calls),1);self.assertEqual(runner.deployment_target(27,value),'deploy:27')
            value['rows'][0]['magic']+=1
            with self.assertRaisesRegex(o.Stop,'recovery_prefix_changed'):runner.deployment_target(26,value)

    def test_sdk_termination_is_exact_fresh_flat_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=row(7);process=dict(pid=v2.PROCESS_PID,created=v2.PROCESS_CREATED,path=target['directory']+'\\terminal64.exe')
            sdk=dict(connected=True,algoEnabled=False,login=target['login'],server=target['server'],dataPath=target['directory'],
                tradeMode=0,marginMode=2,currency='USD',leverage=200,positionTickets=[],orderTickets=[],observedAtUtc=v2.FAILED_AT+500)
            intent=dict(process=process,operation='explicit_one_off_inert_failed_new_terminal_termination',retainedReadonlyRequest=v2.PENDING_ID,atUtc=sdk['observedAtUtc']+5)
            completed=dict(status='exact_inert_failed_process_exited',process=process,atUtc=intent['atUtc']+2)
            def write(values):
                plan={}
                for key,value in values.items():
                    path=root/(key+'.json');path.write_bytes(g.encoded(value));plan[key]=dict(path=str(path),sha256=p.digest(path.read_bytes()))
                return plan
            values=dict(termination=completed,sdkBefore=sdk,terminationIntent=intent)
            with patch.object(v2.time,'time',return_value=completed['atUtc']+10):
                v2.termination_evidence(write(values),target)
                for key,field,value in [('sdkBefore','algoEnabled',True),('sdkBefore','positionTickets',[1]),('sdkBefore','observedAtUtc',v2.FAILED_AT-1),('termination','process',dict(process,pid=8388)),('terminationIntent','retainedReadonlyRequest','0'*32)]:
                    bad=copy.deepcopy(values);bad[key][field]=value
                    with self.subTest(key=key,field=field),self.assertRaises(c.Refused):v2.termination_evidence(write(bad),target)

    def test_apply_keeps_prior_journal_and_all_unrelated_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'original-run';run.mkdir();j,pin,failure_raw,api=chain(run)
            terminal=root/'07 - fixture';folder=terminal/'MQL5/Profiles/Charts/Default';folder.mkdir(parents=True)
            (terminal/'config').mkdir();(terminal/'config/common.ini').write_bytes(b'original common')
            (terminal/'bases').mkdir();(terminal/'bases/gvariables.dat').write_bytes(b'original globals')
            orphan=folder/'chart28.chr';orphan.write_bytes(b'pinned empty chart');(folder/'good.chr').write_bytes(b'26 unchanged child fixtures')
            native=root/'native';native.mkdir();api.root=native;(native/'request.json').write_bytes(b'original status request')
            state=root/'state.tsv';state.write_bytes(b'original dashboard')
            target=row(7);target['directory']=str(terminal);rows=[target,row(8)]
            files={path.name:path.read_bytes() for path in sorted(folder.iterdir())};before_journal=j.path.read_bytes()
            data=dict(common=b'original common',files=files,stateBefore=b'original dashboard',stateAfter=b'only row26 reset',globals=b'original globals',
                failure=json.loads(failure_raw),journalRaw=before_journal,pendingRaw=b'original status request',pendingReceiptRaw=b'late observed status',registrationSha256=api.digest)
            def pin_file(path):return dict(path=str(path),sha256=p.digest(path.read_bytes()))
            plan=dict(outputDirectory=str(root/'output'),orphan=pin_file(orphan),state=pin_file(state),globals=pin_file(terminal/'bases/gvariables.dat'),
                failure=pin_file(run/'receipt-0066.json'),previousRecovery=pin,pendingRequest=pin_file(native/'request.json'))
            for key in ('termination','sdkBefore','terminationIntent'):
                path=root/(key+'.json');g.write_new(path,dict(evidence=key));plan[key]=pin_file(path)
            plan_path=root/'plan.json';g.write_new(plan_path,plan);witness={'lifecycleLock':str(root/'lifecycle.lock')}
            host=S(processes=lambda r:[],powershell=lambda command:'');args=S(plan=plan_path,protected_witness=root/'witness.json',apply=True)
            def verify(r,closed):
                claims=[[path.name,p.digest(path.read_bytes())] for path in sorted(folder.iterdir())]
                self.assertEqual(r['profileSha256'],p.digest(json.dumps(claims,separators=(',',':')).encode()))
            with patch.object(v2,'inspect',return_value=(witness,rows,api,j,data)),patch.object(c,'WindowsHost',return_value=host),\
                 patch.object(g,'checked_witness',return_value=witness),patch.object(c,'verify_files',side_effect=verify),\
                 patch.object(v1,'saved_prefix',return_value=files),patch.object(v2,'replace_preserving_acl',side_effect=lambda path,blob:path.write_bytes(blob)):
                result=v2.run(args)
            self.assertFalse(orphan.exists());self.assertEqual((folder/'good.chr').read_bytes(),files['good.chr'])
            self.assertEqual((terminal/'config/common.ini').read_bytes(),b'original common')
            self.assertEqual((terminal/'bases/gvariables.dat').read_bytes(),b'original globals')
            self.assertEqual((native/'request.json').read_bytes(),b'original status request')
            self.assertEqual(state.read_bytes(),b'only row26 reset');self.assertTrue(j.path.read_bytes().startswith(before_journal))
            self.assertEqual((root/'output/late-status-receipt.json').read_bytes(),b'late observed status')
            self.assertEqual(len([r for r in j.records if r['kind']=='recovery_authorized']),2)
            v2.validate_authority(result['recoveryProof'],result['recoveryProofSha256'],j,api)
            self.assertEqual(g.read(root/'output/reconnect-manifest.json')['terminals'][1],row(8))


if __name__=='__main__':unittest.main()
