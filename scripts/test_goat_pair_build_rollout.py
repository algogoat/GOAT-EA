"""Closed rollout fixtures only: no SDK import, RPC, process launch or credentials."""
import copy, json, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
import goat_demo_pair_builds as b
import goat_demo_pair_build_rollout as r
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_orchestrate as o
import goat_demo_pair_profile as p
import goat_demo_pair_readiness as ready
import goat_demo_pair_recover_child as v1
import goat_demo_pair_recover_child_v2 as v2
from goat_demo_pair_tests import row
import goat_demo_pair_tests as fixtures
from test_goat_pair_recovery_v2 import failure


def pin(path):return dict(path=str(path),sha256=p.digest(path.read_bytes()))


def admission(build):
    return dict(schemaVersion=1,buildId=build,**b.BUILDS[build],allowedAccountIds=[3000109421,3000109427],
        notBeforeMs=1000000,expiresAtMs=1000000+7*86400000,registrySHA256='a'*64,
        backendRelease=dict(runId='fixture',attemptId='fixture',sourceCommit='b'*40,publishedRecordSHA256='c'*64,
            canaryState='PASS',api=dict(verificationSHA256='d'*64,sourceTreeSHA256='e'*64,packageSHA256='f'*64)))


def historical_chain(root,installation,registration):
    old_install=root/'old-installation.json';g.write_new(old_install,installation)
    old_reg=root/'old-registration.json';g.write_new(old_reg,registration)
    binding=r.binding(7,old_install.read_bytes(),old_reg.read_bytes())
    api=S(module=S(verify_receipt=lambda *args:None),installation=installation,reg=registration,digest=binding['registrationSha256'])
    j=o.Journal(root);j.add('start',binding=binding);j.add('intent',target='deploy:6');j.add('receipt',result='child_attach_failed',sha256='a'*64)
    prior=dict(schema=v1.SCHEMA,status='closed_partial_repair_complete',terminal=7,index=6,registrationSha256=api.digest,
        runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(j.path.read_bytes()),failureSha256='a'*64,
        target='recovery:deploy:6:'+'a'*64,prefix=[[1000+i,2000+i] for i in range(6)])
    path=root/'prior-proof.json';g.write_new(path,prior);prior_pin=pin(path)
    j.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=prior_pin['sha256'],target=prior['target'])
    j.add('intent',target=prior['target']);success=failure();success.update(result='child_attached',registrationSha256=api.digest)
    for i,record in enumerate(success['rows']):record.update(chartId=1000+i if i<7 else 0,magic=2000+i if i<7 else 0)
    path=root/'receipt-prior.json';g.write_new(path,success)
    j.add('receipt',result='child_attached',attached=7,linked=7,file=path.name,sha256=pin(path)['sha256'])
    fail=failure();fail['registrationSha256']=api.digest;path=root/'receipt-0066.json';g.write_new(path,fail)
    j.add('intent',target='deploy:26');j.add('receipt',result='child_attach_failed',file=path.name,sha256=pin(path)['sha256'])
    proof=dict(schema=v2.SCHEMA,status='closed_partial_repair_complete',terminal=7,index=26,registrationSha256=api.digest,
        runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(j.path.read_bytes()),failureSha256=pin(path)['sha256'],
        target='recovery:deploy:26:'+pin(path)['sha256'],prefix=[list(v) for v in o.identities(fail)[:26]],previousRecovery=prior_pin)
    path=root/'recovery-proof.json';g.write_new(path,proof)
    j.add('recovery_authorized',proofPath=str(path.resolve()),proofSha256=pin(path)['sha256'],target=proof['target'])
    v2.validate_authority(path,pin(path)['sha256'],j,api)
    return j,api,pin(path),old_install,old_reg


def transition_fixture(root):
    install=dict(buildId=b.R1,eaSha256=b.BUILDS[b.R1]['artifactSHA256'],account=c.PAIR_ACCOUNTS[7],directory='fixed fixture')
    registration=dict(buildId=b.R1,expiresAtUtc=1,aiMode=0,aiThreshold=50,aiProtocol=2,exposureMode=0,
        members=[dict(symbol=record['symbol']) for record in failure()['rows']])
    j,old_api,recovery,old_install,old_reg=historical_chain(root,install,registration)
    new_manifest=root/'terminal-07.json';g.write_new(new_manifest,r.successor(install,b.R2))
    new_reg=r.successor(registration,b.R2,int(time.time())+3600)
    api=S(module=old_api.module,installation=g.read(new_manifest),reg=new_reg,manifest=new_manifest,digest=p.digest(g.encoded(new_reg)))
    from_binding=j.records[0]['binding'];to_binding=r.binding(7,new_manifest.read_bytes(),g.encoded(new_reg))
    transition=dict(fromBinding=from_binding,toBinding=to_binding,oldInstallation=str(old_install),
        oldInstallationSha256=pin(old_install)['sha256'],oldRegistration=str(old_reg),oldRegistrationSha256=pin(old_reg)['sha256'])
    proof=dict(schema=r.SCHEMA,status='closed_build_rollout_complete',fromBuild=b.R1,toBuild=b.R2,
        runDirectory=str(root.resolve()),journalBeforeSha256=p.digest(j.path.read_bytes()),transition=transition,
        recovery=recovery,admission=dict(path='fixture-only',sha256='f'*64),createdAtUtc=time.time(),nativeCommands=0)
    path=root/'rollout-proof.json';g.write_new(path,proof)
    j.add('build_transition',proofPath=str(path.resolve()),proofSha256=pin(path)['sha256'],fromBinding=from_binding,toBinding=to_binding)
    return j,api,path


class BuildRolloutTests(unittest.TestCase):
    def test_manifest_catalog_and_native_source_pins_cannot_be_substituted(self):
        value=fixtures.fixture()
        for build in (b.R1,b.R2):
            for target in value['terminals']:target.update(buildId=build,eaSha256=b.BUILDS[build]['artifactSHA256'])
            c.validate_manifest(value)
        value['terminals'][0]['eaSha256']=b.BUILDS[b.R1]['artifactSHA256']
        with self.assertRaises(c.Refused):c.validate_manifest(value)
        for pins in ({'unrelated.py':'a'*64,'another.py':'b'*64},
            {'goat_portfolio_setup.py':'a'*64,'goat_setup_control.py':'NOT-A-HASH'}):
            with patch.object(o,'PINS',pins),patch.object(o.importlib.util,'spec_from_file_location') as loader:
                with self.assertRaises(o.Stop):o.load_api(Path('no-source-may-load'))
                loader.assert_not_called()

    def test_running_target_is_refused_before_any_native_context_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=[]
            for n in (7,8):
                directory=root/f'{n:02d} - fixture';directory.mkdir();rows.append(dict(row(n),directory=str(directory)))
            manifest=root/'manifest.json';g.write_new(manifest,dict(schema='goat-demo-pair-connection-v1',terminals=rows))
            candidate=root/'candidate.ex5';candidate.write_bytes(b'fixture binary')
            pins=root/'pins.json';g.write_new(pins,{'goat_portfolio_setup.py':'a'*64,'goat_setup_control.py':'b'*64})
            keys=('installation','draft','setupRegistration','setupRequest','setupReceipt','portfolioRegistration','portfolioRequest','portfolioReceipt','owner','state','globals')
            plan=dict(schema=r.SCHEMA,manifest=pin(manifest),candidate=pin(candidate),pins=pin(pins),controlDirectory=str(root),
                outputDirectory=str(root/'output'),admission=None,recovery=None,journal=None,dashboardReference=None,dashboardShutdown=None,
                targets=[dict(terminal=n,**{key:None for key in keys}) for n in (7,8)])
            witness=dict(processes=[dict(path=str(root/'protected/terminal64.exe'))]);host=S(processes=lambda target:[{'pid':123}])
            fake=S(context=lambda path:self.fail('native context must not be reached'))
            with patch.object(g,'checked_witness',return_value=witness),patch.object(o,'load_api',return_value=fake),\
                 patch.dict(b.BUILDS[b.R2],artifactSHA256=pin(candidate)['sha256']):
                with self.assertRaisesRegex(c.Refused,'closed_inert_reviewed_source_required'):r.inspect(plan,host,root/'witness.json')
            self.assertFalse((root/'output').exists());self.assertEqual(candidate.read_bytes(),b'fixture binary')

    def test_catalog_requires_exact_source_binary_compile_and_fresh_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'admission.json'
            for build in (b.R1,b.R2):
                target=dict(row(7),buildId=build,eaSha256=b.BUILDS[build]['artifactSHA256']);value=admission(build)
                def verify(candidate,t=target):
                    path.write_bytes(g.encoded(candidate));return g.verify_admission(path,pin(path)['sha256'],t,now=1001)
                self.assertEqual(verify(value),value)
                for key,bad in [('buildId','V1.48-UNREVIEWED'),('artifactSHA256','1'*64),('compileReceiptSHA256','2'*64),
                    ('sourceCommit','3'*40),('allowedAccountIds',[1,2]),('expiresAtMs',1001000),('notBeforeMs',1001001)]:
                    with self.subTest(build=build,key=key),self.assertRaises(c.Refused):verify(dict(value,**{key:bad}))
                other=b.R2 if build==b.R1 else b.R1
                with self.assertRaises(c.Refused):verify(dict(value,**b.BUILDS[other]))
                with self.assertRaises(c.Refused):verify(value,dict(target,buildId='unknown'))
                with self.assertRaises(c.Refused):verify(value,dict(target,eaSha256='1'*64))

    def test_readiness_records_reviewed_build_and_rejects_unknown(self):
        api,audit,status,registration,installation,now,process=fixtures.ReadinessTests().build()
        for build in (b.R1,b.R2):
            ready.verify_pair(api,audit,status,registration,dict(installation,buildId=build,eaSha256=b.BUILDS[build]['artifactSHA256']),now,process)
        with self.assertRaises(ready.Refused):
            ready.verify_pair(api,audit,status,registration,dict(installation,buildId='unknown'),now,process)
        with self.assertRaises(ready.Refused):
            ready.verify_pair(api,audit,status,registration,dict(installation,buildId=b.R2),now,process)

    def test_successor_keeps_all_policy_and_nested_inputs(self):
        original=dict(buildId=b.R1,eaSha256=b.BUILDS[b.R1]['artifactSHA256'],expiresAtUtc=10,
            policy={'aiMode':0,'aiThreshold':50,'exposureMode':0},members=[{'path':'fixed','sha256':'a'*64,'risk':500}])
        snapshot=copy.deepcopy(original);result=r.successor(original,b.R2,20)
        self.assertEqual(result,dict(snapshot,buildId=b.R2,eaSha256=b.BUILDS[b.R2]['artifactSHA256'],expiresAtUtc=20))
        result['members'][0]['risk']=900;self.assertEqual(original,snapshot)

    def test_transition_validates_both_prior_recoveries_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            j,api,path=transition_fixture(Path(tmp));before=j.path.read_bytes()
            old_api,old_journal,proof=r.validate_transition(path,pin(path)['sha256'],j,api)
            self.assertEqual(old_api.installation['buildId'],b.R1)
            v2.validate_authority(Path(proof['recovery']['path']),proof['recovery']['sha256'],old_journal,old_api)
            self.assertEqual(j.path.read_bytes(),before)
            j.add('attempt',resumed=True) # Subsequent retained activity does not invalidate the frozen prefix.
            r.validate_transition(path,pin(path)['sha256'],j,api)

    def test_transition_rejects_wrong_members_policy_build_manifest_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            j,api,path=transition_fixture(Path(tmp));original_reg=copy.deepcopy(api.reg);original_install=copy.deepcopy(api.installation)
            mutations=[('aiMode',2),('aiThreshold',51),('exposureMode',1),('members',[{'symbol':'USDJPY'}]),('buildId',b.R1)]
            for key,value in mutations:
                api.reg=dict(original_reg,**{key:value})
                with self.subTest(key=key),self.assertRaises(c.Refused):r.validate_transition(path,pin(path)['sha256'],j,api)
            api.reg=original_reg
            for key,value in [('eaSha256','a'*64),('account',c.PAIR_ACCOUNTS[8]),('directory','another')]:
                api.installation=dict(original_install,**{key:value})
                with self.subTest(key=key),self.assertRaises(c.Refused):r.validate_transition(path,pin(path)['sha256'],j,api)
            api.installation=original_install;api.digest='a'*64
            with self.assertRaises(c.Refused):r.validate_transition(path,pin(path)['sha256'],j,api)

    def test_transition_rejects_changed_history_old_pins_and_duplicate_authority(self):
        for attack in ('prefix','old-pin','duplicate','foreign-run','wrong-proof-hash'):
            with self.subTest(attack=attack),tempfile.TemporaryDirectory() as tmp:
                j,api,path=transition_fixture(Path(tmp));sha=pin(path)['sha256']
                if attack=='prefix':j.path.write_bytes(j.path.read_bytes().replace(b'deploy:6',b'deploy:5',1))
                elif attack=='old-pin':(Path(tmp)/'old-registration.json').write_bytes(b'{}')
                elif attack=='duplicate':j.add('build_transition',**{k:v for k,v in j.records[-1].items() if k not in ('kind','sequence','atUtc','previous')})
                elif attack=='foreign-run':j.directory=Path(tmp)/'foreign'
                else:sha='0'*64
                with self.assertRaises(c.Refused):r.validate_transition(path,sha,j,api)

    def test_pinned_mailboxes_do_not_accept_unplanned_or_changed_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'request.json';self.assertIsNone(r.pinned_slot(None,path,True))
            path.write_bytes(b'original');claim=pin(path);self.assertEqual(r.pinned_slot(claim,path),b'original')
            with self.assertRaises(c.Refused):r.pinned_slot(None,path,True)
            with self.assertRaises(c.Refused):r.pinned_slot(claim,root/'another.json')
            path.write_bytes(b'changed')
            with self.assertRaises(c.Refused):r.pinned_slot(claim,path)

    def test_apply_changes_only_reviewed_build_metadata_and_keeps_all_prior_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'original-run';work.mkdir();j=o.Journal(work);j.add('start',binding={'original':True})
            journal_raw=j.path.read_bytes();candidate=b'reviewed fixture R2';snaps=[];before={};common=root/'Common';common.mkdir()
            for n in (7,8):
                directory=root/f'{n:02d} - fixture';profile=directory/'MQL5/Profiles/Charts/Default';profile.mkdir(parents=True)
                (directory/'config').mkdir();(directory/'bases').mkdir();binary=directory/c.EXPERT_RELATIVE;binary.parent.mkdir(parents=True)
                setup=common/'GOAT/AgentSetup'/directory.name;setup.mkdir(parents=True)
                portfolio=common/'GOAT/AgentPortfolio'/directory.name;portfolio.mkdir(parents=True)
                state=common/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
                for path,blob in [(binary,b'old binary'),(directory/'config/common.ini',b'AlgoOFF'),(directory/'bases/gvariables.dat',b'globals'),
                    (profile/'chart01.chr',b'unchanged full profile'),(state,b'unchanged members and chart identities')]:
                    path.write_bytes(blob);before[path]=blob
                installation=dict(account=c.PAIR_ACCOUNTS[n],directory=str(directory),commonFiles=str(common),buildId=b.R1,eaSha256=b.BUILDS[b.R1]['artifactSHA256'])
                draft=dict(buildId=b.R1,expiresAtUtc=1,members=[{'inputHash':'a'*64}]*35,aiMode=0 if n==7 else 2,aiThreshold=50,exposureMode=0)
                setup_reg=dict(schema=2,buildId=b.R1,expiresAtUtc=1,allowPairingRead=True)
                mail=dict(setupRegistration=g.encoded(setup_reg),setupRequest=g.encoded(dict(id='a'*32)),setupReceipt=g.encoded({'completed':True}),
                    portfolioRegistration=g.encoded(draft) if n==7 else None,portfolioRequest=g.encoded(dict(id='b'*32)) if n==7 else None,
                    portfolioReceipt=g.encoded({'completed':True}) if n==7 else None,owner=g.encoded({'old':True}) if n==7 else None)
                for kind,folder in [('setup',setup),('portfolio',portfolio)]:
                    for suffix,name in [('Registration','registration.json'),('Request','request.json'),('Receipt',('a' if kind=='setup' else 'b')*32+'.json')]:
                        if mail.get(kind+suffix) is not None:(folder/name).write_bytes(mail[kind+suffix])
                if mail['owner'] is not None:(portfolio/'orchestration-owner.json').write_bytes(mail['owner'])
                target=dict(row(n),directory=str(directory));nxt=r.successor(target,b.R2)
                snaps.append(dict(row=target,nextRow=nxt,directory=directory,installation=installation,installationRaw=g.encoded(installation),
                    draft=draft,draftRaw=g.encoded(draft),setupRoot=setup,portfolioRoot=portfolio,mail=mail,state=state.read_bytes(),
                    globals=b'globals',common=b'AlgoOFF',profile={'chart01.chr':b'unchanged full profile'},oldBinding={'original':True} if n==7 else None))
            admission_path=root/'admission.json';g.write_new(admission_path,{'fixture':True})
            plan=dict(outputDirectory=str(root/'output'),admission=pin(admission_path),recovery={'path':'historical-proof','sha256':'a'*64})
            plan_path=root/'plan.json';g.write_new(plan_path,plan);witness={'lifecycleLock':str(root/'shared.lock')}
            def context(path):
                value=g.read(path);return value,common/'GOAT/AgentPortfolio'/Path(value['directory']).name
            module=S(context=context,validate_registration=lambda *args:None)
            inspected=(witness,[s['row'] for s in snaps],snaps,j,journal_raw,candidate,module)
            host=S(processes=lambda target:[],powershell=lambda command:'')
            args=S(plan=plan_path,protected_witness=root/'witness.json',apply=True)
            with patch.object(r,'inspect',return_value=inspected),patch.object(c,'WindowsHost',return_value=host),\
                 patch.object(c,'verify_files'),patch.object(g,'verify_admission'),patch.object(g,'checked_witness',return_value=witness),\
                 patch.object(r,'replace_preserving_acl',side_effect=lambda path,blob:path.write_bytes(blob)):
                result=r.run(args)
                with self.assertRaises(FileExistsError):r.run(args) # No retained output overwrite, even with mocked inspection.
            self.assertEqual(result['status'],'closed_rollout_complete_no_launch');self.assertEqual(result['nativeCommands'],0)
            self.assertTrue(j.path.read_bytes().startswith(journal_raw));self.assertEqual(j.records[-1]['kind'],'build_transition')
            for path,blob in before.items():self.assertEqual(path.read_bytes(),candidate if path.suffix=='.ex5' else blob)
            for snap in snaps:
                n=snap['row']['terminal'];folder=root/'output'/str(n)
                self.assertEqual((folder/'previous.ex5').read_bytes(),b'old binary')
                self.assertEqual((folder/'installation-before.json').read_bytes(),snap['installationRaw'])
                self.assertEqual(g.read(root/'output'/f'terminal-{n:02d}.json'),r.successor(snap['installation'],b.R2))
                self.assertFalse((snap['setupRoot']/'request.json').exists());self.assertTrue((folder/'setup-retired-request.json').is_file())
                self.assertEqual((snap['setupRoot']/('a'*32+'.json')).read_bytes(),snap['mail']['setupReceipt'])
                self.assertEqual(g.read(snap['portfolioRoot']/'registration.json')['members'],snap['draft']['members'])
            self.assertEqual(g.read(root/'output/reconnect-manifest.json')['terminals'],[s['nextRow'] for s in snaps])


if __name__=='__main__':unittest.main()
