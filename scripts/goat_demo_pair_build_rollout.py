"""Closed, inert R1-to-R2 pair rollout; immutable evidence, no RPC/startup/trades."""
import argparse, contextlib, copy, json, math, re, time
from pathlib import Path
from types import SimpleNamespace
import goat_demo_pair_builds as builds
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_profile as p
import goat_demo_pair_orchestrate as o
import goat_demo_pair_recover_child_v2 as repair
import goat_demo_pair_dashboard_recapture as recapture
import goat_demo_pair_trust as trust
from goat_demo_pair_lifecycle import replace_preserving_acl

SCHEMA='goat-pair-closed-build-rollout-v1'


def pinned_slot(pin,path,optional=False):
    if pin is None:
        c.require(optional and not path.exists(),'unexpected_retained_mailbox');return None
    c.require(Path(pin['path']).resolve()==path.resolve(),'mailbox_pin_scope')
    return trust.pinned(pin)


def binding(terminal,installation_raw,registration_raw):
    return dict(terminal=terminal,manifestSha256=p.digest(installation_raw),registrationSha256=p.digest(registration_raw))


def successor(value,build,expiry=None):
    result=copy.deepcopy(value);result['buildId']=build
    if 'eaSha256' in result:result['eaSha256']=builds.BUILDS[build]['artifactSHA256']
    if expiry is not None:result['expiresAtUtc']=expiry
    return result


def inspect(plan,host,witness_path,expected=None):
    c.require(set(plan)=={'schema','manifest','candidate','admission','pins','controlDirectory','outputDirectory','recovery','journal',
        'dashboardReference','dashboardShutdown','targets'} and plan['schema']==SCHEMA,'rollout_plan_schema')
    witness=g.checked_witness(witness_path,host,expected=expected)
    rows=c.validate_manifest(json.loads(trust.pinned(plan['manifest'])));g.assert_new_pair_paths(rows,witness)
    out=Path(plan['outputDirectory']);c.require(out.is_absolute() and out.parent.is_dir() and not out.exists(),'new_rollout_output_required')
    c.require([t.get('terminal') for t in plan['targets']]==[7,8],'exact_rollout_pair')
    for path in [out.parent,*[Path(r['directory']) for r in rows]]:
        c.require(not any(v.is_symlink() or v.is_junction() for v in [path,*path.parents]),'rollout_path_alias')
    for root in [Path(v['path']).parent for v in witness['processes']]+[Path(r['directory']) for r in rows]:
        c.require(not out.resolve().is_relative_to(root.resolve()) and not root.resolve().is_relative_to(out.resolve()),'rollout_output_scope')
    candidate=g.raw(plan['candidate']['path'],32*1024*1024)
    c.require(p.digest(candidate)==plan['candidate']['sha256']==builds.BUILDS[builds.R2]['artifactSHA256'],'reviewed_candidate_hash')
    o.PINS=json.loads(trust.pinned(plan['pins']));module=o.load_api(Path(plan['controlDirectory']))
    snapshots=[]
    for row,target in zip(rows,plan['targets']):
        fields={'terminal','installation','draft','setupRegistration','setupRequest','setupReceipt','portfolioRegistration','portfolioRequest','portfolioReceipt','owner','state','globals'}
        c.require(set(target)==fields and row['buildId']==builds.R1 and row['eaSha256']==builds.BUILDS[builds.R1]['artifactSHA256']
            and row['savedAlgoEnabled'] is False and not host.processes(row),'closed_inert_reviewed_source_required')
        c.verify_files(row);directory=Path(row['directory']);common_raw=g.raw(directory/'config/common.ini')
        c.require(p.digest(common_raw)==row['commonIniSha256'] and p.patch_common(common_raw,row['login'],0)==common_raw,'closed_config_changed')
        installation_raw=trust.pinned(target['installation']);installation,portfolio_root=module.context(Path(target['installation']['path']))
        c.require(Path(target['installation']['path']).name==f'terminal-{row["terminal"]:02d}.json'
            and installation['directory']==row['directory'] and installation['eaSha256']==row['eaSha256']
            and installation['account']==row['login'] and installation['buildId']==builds.R1,'old_installation_binding')
        next_row=successor(row,builds.R2);g.verify_admission(Path(plan['admission']['path']),plan['admission']['sha256'],next_row)
        common=Path(installation['commonFiles']);setup_root=common/'GOAT/AgentSetup'/directory.name
        c.require(not any(v.is_symlink() or v.is_junction() for v in [common,setup_root,portfolio_root,*portfolio_root.parents]),'mailbox_alias')
        draft_raw=trust.pinned(target['draft']);draft=json.loads(draft_raw)
        c.require(draft['account']==row['login'] and draft['buildId']==builds.R1 and len(draft['members'])==35
            and draft['aiMode']==(0 if row['terminal']==7 else 2) and draft['aiThreshold']==50 and draft['aiProtocol']==2 and draft['exposureMode']==0,'old_draft_scope')
        module.validate_registration(dict(draft,expiresAtUtc=int(time.time())+3600),installation)
        state_path=common/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
        state=pinned_slot(target['state'],state_path);globals_raw=pinned_slot(target['globals'],directory/'bases/gvariables.dat')
        mail={}
        for name,path,optional in [('setupRegistration',setup_root/'registration.json',False),('setupRequest',setup_root/'request.json',True),
            ('portfolioRegistration',portfolio_root/'registration.json',row['terminal']==8),('portfolioRequest',portfolio_root/'request.json',True),
            ('owner',portfolio_root/'orchestration-owner.json',row['terminal']==8)]:mail[name]=pinned_slot(target[name],path,optional)
        setup_reg=json.loads(mail['setupRegistration'])
        c.require(type(setup_reg.get('schema')) is int and setup_reg['schema'] in (1,2) and type(setup_reg.get('expiresAtUtc')) is int
            and all(setup_reg[k]==installation[k] for k in ('account','server','directory','buildId'))
            and set(setup_reg)==({'schema','account','server','directory','buildId','expiresAtUtc'} if setup_reg['schema']==1 else
                {'schema','account','server','directory','buildId','expiresAtUtc','allowPairingRead'})
            and (setup_reg['schema']==1 or setup_reg['allowPairingRead'] is True),'old_setup_registration')
        if mail['setupRequest'] is not None:
            req=json.loads(mail['setupRequest']);c.require(set(req)=={'schema','id','action','account','server','directory','buildId','expiresAtUtc'}
                and type(req['schema']) is int and req['schema']==1 and type(req['expiresAtUtc']) is int
                and re.fullmatch('[a-f0-9]{32}',req['id']) is not None and req['action'] in ('status','shutdown'),'unreviewed_setup_request')
            receipt=pinned_slot(target['setupReceipt'],setup_root/(req['id']+'.json'))
            observed=json.loads(receipt);module.setup.receipt_record(observed,req['id'],installation)
            c.require(observed['result']==('shutdown_requested' if req['action']=='shutdown' else 'observed'),'unresolved_setup_request')
            c.require(all(req.get(k)==installation[k] for k in ('account','server','directory','buildId')),'setup_request_scope')
            mail['setupReceipt']=receipt
        else:c.require(target['setupReceipt'] is None,'unexpected_setup_receipt')
        if row['terminal']==7:
            historical=repair.historical_api(module,Path(target['installation']['path']),Path(target['draft']['path']))
            c.require(mail['portfolioRegistration'] is not None and p.digest(mail['portfolioRegistration'])==historical.digest,'old_registration_binding')
            c.require(mail['portfolioRequest'] is not None,'retained_second_status_required');req=json.loads(mail['portfolioRequest'])
            receipt=pinned_slot(target['portfolioReceipt'],portfolio_root/(req['id']+'.json'));value=json.loads(receipt)
            module.verify_receipt(value,req,installation,historical.reg['members'])
            c.require(req['id']==repair.PENDING_ID and req['action']=='status' and value['result']=='observed','old_portfolio_read_not_resolved');mail['portfolioReceipt']=receipt
            journal_raw=trust.pinned(plan['journal']);journal=o.Journal(Path(plan['journal']['path']).parent)
            proof=repair.validate_authority(Path(plan['recovery']['path']),plan['recovery']['sha256'],journal,historical)
            c.require(proof['profileSha256']==row['profileSha256'] and proof['stateAfterSha256']==p.digest(state),'repair_persistence_changed')
            old_binding=binding(7,installation_raw,mail['portfolioRegistration'])
            c.require(journal.records[0].get('binding')==old_binding and json.loads(mail['owner'])==dict(schema=1,runDirectory=str(journal.directory.resolve()),binding=old_binding),'old_journal_owner')
            c.require(not any(r['kind']=='build_transition' for r in journal.records),'build_already_transitioned')
            c.verify_files(row,True)
            profile={path.relative_to(directory/'MQL5/Profiles/Charts/Default').as_posix():g.raw(path) for path in sorted((directory/'MQL5/Profiles/Charts/Default').rglob('*')) if path.is_file()}
        else:
            c.require(mail['portfolioRegistration'] is mail['portfolioRequest'] is mail['owner'] is None and target['portfolioReceipt'] is None,'terminal08_must_be_unattached')
            reference=p.chart_details(trust.pinned(plan['dashboardReference']),directory)
            profile,chart,_,digest=recapture.snapshot_profile(row,55908588296300)
            current=p.chart_details(profile[chart['file']],directory)
            c.require(reference[2]==current[2]=='dashboard' and reference[0].get('id')==current[0].get('id')
                and reference[1]==current[1],'dashboard_full_inputs_changed')
            shut=json.loads(trust.pinned(plan['dashboardShutdown']));module.setup.receipt_record(shut,shut['id'],installation)
            c.require(shut['result']=='shutdown_requested' and shut['activationOnly'] is False and shut['connected'] is True
                and shut['tradingAllowed'] is False and shut['positions']==shut['orders']==0 and shut['charts']==1
                and type(shut['observedAtUtc']) in (int,float) and math.isfinite(shut['observedAtUtc'])
                and 0<shut['observedAtUtc']<=time.time() and g.read(setup_root/(shut['id']+'.json'))==shut,'dashboard_closed_native_evidence')
            # This completed receipt is historical. Current process absence,
            # full saved inputs and hashes are checked again under the lock;
            # an admission queue delay must not require another startup.
            row['profileSha256']=digest;next_row['profileSha256']=digest;c.verify_files(row,True)
            old_binding=None
        snapshots.append(dict(row=row,nextRow=next_row,directory=directory,installation=installation,installationRaw=installation_raw,
            draft=draft,draftRaw=draft_raw,setupRoot=setup_root,portfolioRoot=portfolio_root,mail=mail,state=state,globals=globals_raw,
            common=common_raw,profile=profile,oldBinding=old_binding))
    return witness,rows,snapshots,journal,journal_raw,candidate,module


def run(args):
    plan=g.read(args.plan);host=c.WindowsHost();inspected=inspect(plan,host,args.protected_witness)
    witness,rows,snapshots,journal,journal_raw,candidate,module=inspected
    if not args.apply:return dict(status='dry_run_passed',fromBuild=builds.R1,toBuild=builds.R2,nativeCommands=0)
    with g.lifecycle_lock(witness),contextlib.ExitStack() as stack:
        for snap in snapshots:
            # Terminal08 has never had a portfolio writer; creating its bounded
            # mailbox directory only enables taking the same exclusive locks.
            snap['portfolioRoot'].mkdir(parents=True,exist_ok=True)
            for path in (snap['setupRoot']/'producer.lock',snap['portfolioRoot']/'producer.lock',snap['portfolioRoot']/'orchestration.lock'):
                stack.enter_context(g.lifecycle_lock({'lifecycleLock':str(path)},wait_seconds=0))
        stack.enter_context(g.lifecycle_lock({'lifecycleLock':str(journal.directory/'orchestration.lock')},wait_seconds=0))
        fresh=inspect(plan,host,args.protected_witness,expected=witness)
        c.require(fresh[1:3]==inspected[1:3] and fresh[4:6]==inspected[4:6],'rollout_state_changed')
        out=Path(plan['outputDirectory']);out.mkdir();quoted=str(out).replace("'","''")
        host.powershell("$ErrorActionPreference='Stop'; & icacls '"+quoted+"' /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; if($LASTEXITCODE -ne 0){throw 'private evidence ACL failed'}")
        g.write_new(out/'intent.json',plan);g.write_new(out/'journal-before.jsonl',journal_raw);g.write_new(out/'admission.json',trust.pinned(plan['admission']))
        successors=[];transition=None;now=int(time.time())
        for snap in snapshots:
            row=snap['row'];n=row['terminal'];folder=out/str(n);folder.mkdir();mail=snap['mail'];directory=snap['directory']
            for name,raw in [('installation-before.json',snap['installationRaw']),('draft-before.json',snap['draftRaw']),('common.ini',snap['common']),('globals.dat',snap['globals']),('dashboard.tsv',snap['state'])]:g.write_new(folder/name,raw)
            for name,raw in mail.items():
                if raw is not None:g.write_new(folder/(name+'-before.json'),raw)
            for name,raw in snap['profile'].items():
                path=folder/'profile'/name;path.parent.mkdir(parents=True,exist_ok=True);g.write_new(path,raw)
            binary=directory/c.EXPERT_RELATIVE;g.write_new(folder/'previous.ex5',g.raw(binary,32*1024*1024))
            installation=successor(snap['installation'],builds.R2);draft=successor(snap['draft'],builds.R2,now+14400)
            registration=successor(json.loads(mail['portfolioRegistration']) if mail['portfolioRegistration'] else snap['draft'],builds.R2,now+14400)
            module.validate_registration(registration,installation)
            install_raw=g.encoded(installation);reg_raw=g.encoded(registration)
            g.write_new(out/f'terminal-{n:02d}.json',install_raw);g.write_new(out/f'portfolio-{n:02d}.json',draft)
            c.require(not host.processes(row),'target_started_before_rollout');c.verify_files(row,True)
            g.verify_admission(Path(plan['admission']['path']),plan['admission']['sha256'],snap['nextRow'])
            c.require(g.raw(binary,32*1024*1024)==g.raw(folder/'previous.ex5',32*1024*1024),'binary_changed_before_rollout')
            for kind,root in [('setup',snap['setupRoot']),('portfolio',snap['portfolioRoot'])]:
                req=mail[kind+'Request']
                if req is not None:
                    c.require(g.raw(root/'request.json')==req,'request_changed_before_rollout')
                    (root/'request.json').rename(folder/(kind+'-retired-request.json'))
            replace_preserving_acl(binary,candidate)
            setup=successor(json.loads(mail['setupRegistration']),builds.R2,now+(900 if json.loads(mail['setupRegistration'])['schema']==2 else 3600))
            c.require(g.raw(snap['setupRoot']/'registration.json')==mail['setupRegistration'],'setup_registration_changed_before_rollout')
            replace_preserving_acl(snap['setupRoot']/'registration.json',g.encoded(setup))
            if mail['portfolioRegistration'] is None:g.write_new(snap['portfolioRoot']/'registration.json',reg_raw)
            else:
                c.require(g.raw(snap['portfolioRoot']/'registration.json')==mail['portfolioRegistration'],'portfolio_registration_changed_before_rollout')
                replace_preserving_acl(snap['portfolioRoot']/'registration.json',reg_raw)
            new_binding=binding(n,install_raw,reg_raw)
            if n==7:
                owner=dict(schema=1,runDirectory=str(journal.directory.resolve()),binding=new_binding)
                c.require(g.raw(snap['portfolioRoot']/'orchestration-owner.json')==mail['owner'],'owner_changed_before_rollout')
                replace_preserving_acl(snap['portfolioRoot']/'orchestration-owner.json',g.encoded(owner))
                transition=dict(fromBinding=snap['oldBinding'],toBinding=new_binding,oldInstallation=str(folder/'installation-before.json'),
                    oldInstallationSha256=p.digest(snap['installationRaw']),oldRegistration=str(folder/'portfolioRegistration-before.json'),
                    oldRegistrationSha256=p.digest(mail['portfolioRegistration']))
            c.verify_files(snap['nextRow'],True)
            checked_installation,checked_root=module.context(out/f'terminal-{n:02d}.json')
            c.require(checked_installation==installation and checked_root.resolve()==snap['portfolioRoot'].resolve()
                and g.raw(snap['setupRoot']/'registration.json')==g.encoded(setup)
                and g.raw(snap['portfolioRoot']/'registration.json')==reg_raw,'rollout_metadata_readback')
            if n==7:c.require(g.read(snap['portfolioRoot']/'orchestration-owner.json')==owner,'rollout_owner_readback')
            for kind in ('setup','portfolio'):
                c.require(not (snap[kind+'Root']/'request.json').exists(),'rollout_request_reappeared')
                receipt=mail.get(kind+'Receipt')
                if receipt is not None:
                    req=json.loads(mail[kind+'Request'])
                    c.require(g.raw(snap[kind+'Root']/(req['id']+'.json'))==receipt,'rollout_receipt_changed')
            state_path=Path(snap['installation']['commonFiles'])/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
            c.require(not host.processes(row) and g.raw(directory/'bases/gvariables.dat')==snap['globals']
                and g.raw(state_path)==snap['state'],'rollout_process_or_persistence_changed')
            successors.append(snap['nextRow'])
        g.checked_witness(args.protected_witness,host,expected=witness)
        c.require(g.raw(journal.path,8*1024*1024)==journal_raw,'rollout_journal_changed')
        proof=dict(schema=SCHEMA,status='closed_build_rollout_complete',fromBuild=builds.R1,toBuild=builds.R2,
            runDirectory=str(journal.directory.resolve()),journalBeforeSha256=p.digest(journal_raw),transition=transition,
            recovery=plan['recovery'],admission=plan['admission'],createdAtUtc=time.time(),nativeCommands=0)
        proof_path=out/'rollout-proof.json';g.write_new(proof_path,proof);proof_sha=p.digest(g.raw(proof_path))
        journal.add('build_transition',proofPath=str(proof_path.resolve()),proofSha256=proof_sha,fromBinding=transition['fromBinding'],toBinding=transition['toBinding'])
        g.write_new(out/'reconnect-manifest.json',dict(schema='goat-demo-pair-connection-v1',terminals=successors))
        result=dict(status='closed_rollout_complete_no_launch',proofPath=str(proof_path),proofSha256=proof_sha,nativeCommands=0)
        g.write_new(out/'completion.json',result);return result


def validate_transition(path,sha,journal,api):
    proof=json.loads(trust.pinned(dict(path=str(path),sha256=sha)));events=[r for r in journal.records if r['kind']=='build_transition']
    c.require(set(proof)=={'schema','status','fromBuild','toBuild','runDirectory','journalBeforeSha256','transition','recovery','admission','createdAtUtc','nativeCommands'}
        and proof.get('schema')==SCHEMA and proof.get('status')=='closed_build_rollout_complete' and proof.get('nativeCommands')==0
        and proof.get('fromBuild')==builds.R1 and proof.get('toBuild')==builds.R2 and len(events)==1
        and proof.get('runDirectory')==str(journal.directory.resolve()),'rollout_authority_scope')
    event=events[0];transition=proof['transition'];prefix=g.raw(journal.path,8*1024*1024).splitlines(keepends=True)[:event['sequence']]
    c.require(event.get('proofPath')==str(Path(path).resolve()) and event.get('proofSha256')==sha
        and p.digest(b''.join(prefix))==proof['journalBeforeSha256'] and event.get('fromBinding')==transition['fromBinding']
        and event.get('toBinding')==transition['toBinding'] and journal.records[0].get('binding')==transition['fromBinding'],'rollout_journal_chain')
    old_install=json.loads(trust.pinned(dict(path=transition['oldInstallation'],sha256=transition['oldInstallationSha256'])))
    old_reg=json.loads(trust.pinned(dict(path=transition['oldRegistration'],sha256=transition['oldRegistrationSha256'])))
    c.require(old_install['buildId']==builds.R1 and old_install['eaSha256']==builds.BUILDS[builds.R1]['artifactSHA256']
        and api.installation==successor(old_install,builds.R2)
        and {k:v for k,v in api.reg.items() if k!='expiresAtUtc'}=={k:v for k,v in successor(old_reg,builds.R2).items() if k!='expiresAtUtc'},'rollout_scope_changed')
    c.require(transition['toBinding']==dict(terminal=7,manifestSha256=p.digest(g.raw(api.manifest)),registrationSha256=api.digest)
        and transition['fromBinding']==dict(terminal=7,manifestSha256=transition['oldInstallationSha256'],registrationSha256=transition['oldRegistrationSha256']),'rollout_binding')
    old_api=SimpleNamespace(module=api.module,installation=old_install,reg=old_reg,digest=transition['oldRegistrationSha256'])
    old_journal=SimpleNamespace(records=journal.records[:event['sequence']],path=journal.path,directory=journal.directory)
    repair.validate_authority(Path(proof['recovery']['path']),proof['recovery']['sha256'],old_journal,old_api)
    return old_api,old_journal,proof


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--protected-witness',type=Path,required=True);ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    try:print(json.dumps(run(args)))
    except (c.Refused,o.Stop) as error:print(json.dumps(dict(status='needs_review',reason=str(error))));raise SystemExit(2)
    except Exception as error:print(json.dumps(dict(status='needs_review',reason='inspect_retained_rollout_evidence',exceptionType=type(error).__name__)));raise SystemExit(2)
