"""Inspected terminal07/index26 recovery only; no RPC, SDK, process or build changes."""
import argparse, contextlib, copy, hashlib, json, ntpath, time
from pathlib import Path
from types import SimpleNamespace
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_profile as p
import goat_demo_pair_orchestrate as o
import goat_demo_pair_recover_child as v1
import goat_demo_pair_trust as trust
from goat_demo_pair_lifecycle import replace_preserving_acl

SCHEMA='goat-partial-child-recovery-v2'
INDEX=26
FAILED_CID=55957314657764
FAILED_AT=1790231505
PROCESS_PID=20896
PROCESS_CREATED='2026-09-24T06:23:35.6919830Z'
PENDING_ID='477ab53b36004ea5b5c60dea500f8f53'


def failure_scope(value,reg):
    c.require(value.get('action')=='deploy_next' and value.get('result')=='child_attach_failed'
        and value.get('observedAtUtc')==FAILED_AT and value.get('connected') is True
        and value.get('tradingAllowed') is False and value.get('positions')==value.get('orders')==0
        and value.get('commandPending') is False and len(value.get('rows',[]))==len(reg['members'])==35,'exact_second_failure_required')
    for index,(row,member) in enumerate(zip(value['rows'],reg['members'])):
        c.require(row['index']==index and row['symbol']==member['symbol'],'failure_member_identity')
        if index<INDEX:c.require(row['chartId']>0 and row['magic']>0 and row['linkedFresh'] is True,'twenty_six_good_children_required')
        elif index==INDEX:c.require(row['chartId']==FAILED_CID and row['magic']==0 and row['symbol']=='NZDUSD','exact_second_failed_row')
        else:c.require(row['chartId']==row['magic']==0,'later_children_present')
    c.require(len({r['chartId'] for r in value['rows'][:27]})==27
        and len({r['magic'] for r in value['rows'][:26]})==26,'duplicate_child_identity')


def historical_v1(pin,journal,api):
    events=[r for r in journal.records if r['kind']=='recovery_authorized']
    c.require(events and events[0]['target'].startswith('recovery:deploy:6:'),'prior_recovery_missing')
    event=events[0]
    # Validate the unchanged v1 proof against precisely its original journal prefix.
    original=SimpleNamespace(records=journal.records[:event['sequence']+1],path=journal.path,directory=journal.directory)
    prior=v1.validate_authority(Path(pin['path']),pin['sha256'],original,api)
    intents=[r for r in journal.records if r['kind']=='intent' and r.get('target')==prior['target']]
    c.require(len(intents)==1 and intents[0]['sequence']>event['sequence'],'prior_recovery_not_issued_once')
    following=journal.records[intents[0]['sequence']+1:]
    c.require(following and following[0]['kind']=='receipt' and following[0].get('result')=='child_attached'
        and following[0].get('attached')==following[0].get('linked')==7,'prior_recovery_not_completed')
    record=following[0];raw=g.raw(journal.directory/record['file'])
    c.require(p.digest(raw)==record['sha256'],'prior_recovery_receipt_changed')
    value=json.loads(raw);api.module.verify_receipt(value,{k:value[k] for k in ('id','action','registrationSha256')},api.installation,api.reg['members'])
    c.require(value['registrationSha256']==api.digest and value['result']=='child_attached'
        and o.count_attached(value)==7 and [list(v) for v in o.identities(value)[:6]]==prior['prefix'],'prior_recovery_receipt_scope')
    return prior,value


def journal_failure(journal,failure_raw,prior_pin,api):
    c.require(len([r for r in journal.records if r['kind']=='recovery_authorized'])==1,'second_recovery_already_authorized')
    prior,successful=historical_v1(prior_pin,journal,api)
    intents=[r for r in journal.records if r['kind']=='intent'];receipts=[r for r in journal.records if r['kind']=='receipt']
    c.require(intents and receipts and intents[-1].get('target')=='deploy:26'
        and sum(r.get('target')=='deploy:26' for r in intents)==1
        and receipts[-1].get('result')=='child_attach_failed' and receipts[-1].get('file')=='receipt-0066.json'
        and receipts[-1]['sha256']==p.digest(failure_raw)
        and g.raw(journal.directory/receipts[-1]['file'])==failure_raw,'original_second_failed_attempt_required')
    failure=json.loads(failure_raw)
    c.require(o.identities(failure)[:7]==o.identities(successful)[:7],'first_recovery_identities_changed')
    return prior


def termination_evidence(plan,row):
    # Exact SDK-qualified termination evidence is checked below; never invoke the SDK.
    complete=json.loads(trust.pinned(plan['termination']))
    sdk=json.loads(trust.pinned(plan['sdkBefore']))
    intent=json.loads(trust.pinned(plan['terminationIntent']))
    expected={'pid':PROCESS_PID,'created':PROCESS_CREATED,'path':ntpath.join(row['directory'],'terminal64.exe')}
    c.require(complete.get('status')=='exact_inert_failed_process_exited' and complete.get('process')==expected
        and intent.get('process')==expected and intent.get('operation')=='explicit_one_off_inert_failed_new_terminal_termination'
        and intent.get('retainedReadonlyRequest')==PENDING_ID,'exact_terminated_process_required')
    c.require(sdk.get('connected') is True and sdk.get('algoEnabled') is False
        and sdk.get('login')==row['login'] and sdk.get('server')==row['server']
        and c.canonical(sdk.get('dataPath',''))==c.canonical(row['directory'])
        and sdk.get('tradeMode')==0 and sdk.get('marginMode')==2 and sdk.get('currency')=='USD'
        and sdk.get('leverage')==200 and sdk.get('positionTickets')==sdk.get('orderTickets')==[],'fresh_inert_sdk_required')
    c.require(FAILED_AT<=sdk['observedAtUtc']<=intent['atUtc']<=complete['atUtc']<=time.time()
        and intent['atUtc']-sdk['observedAtUtc']<=30 and complete['atUtc']-intent['atUtc']<=60
        and time.time()-complete['atUtc']<=14400,'termination_chronology')
    return complete,sdk,intent


def historical_api(module,manifest,draft):
    installation,root=module.context(manifest);reg,digest=module.read_bounded(root/'registration.json')
    c.require(manifest.name=='terminal-07.json' and installation['account']==c.PAIR_ACCOUNTS[7]
        and installation['server']=='Darwinex-Demo' and installation['buildId']=='V1.48-DASHBOARD-AI-PAIR-R1','historical_installation')
    c.require(type(reg.get('expiresAtUtc')) is int and FAILED_AT<reg['expiresAtUtc']<=FAILED_AT+14400,'registration_not_valid_at_failure')
    # Exercise the pinned library's complete structural/member checks. Only this
    # throwaway validation copy has a current expiry; original bytes/digest below
    # remain historical, and this helper cannot issue requests or renew anything.
    structural=dict(reg,expiresAtUtc=int(time.time())+3600)
    module.validate_registration(structural,installation)
    reviewed,_=module.read_bounded(draft)
    c.require({k:v for k,v in reviewed.items() if k!='expiresAtUtc'}=={k:v for k,v in reg.items() if k!='expiresAtUtc'},'reviewed_draft_mismatch')
    c.require(len(reg['members'])==35 and reg['aiMode']==0 and reg['aiThreshold']==50
        and reg['aiProtocol']==2 and reg['exposureMode']==0,'historical_pair_policy')
    return SimpleNamespace(module=module,manifest=manifest,installation=installation,root=root,reg=reg,digest=digest)


def inspect(plan,host,witness_path,expected=None):
    fields={'schema','reconnectManifest','installation','draft','pins','controlDirectory','failure','journal','orphan','state','globals',
        'outputDirectory','previousRecovery','termination','sdkBefore','terminationIntent','pendingRequest','pendingReceipt'}
    c.require(set(plan)==fields and plan['schema']==SCHEMA,'second_recovery_plan_schema')
    witness=g.checked_witness(witness_path,host,expected=expected)
    rows=c.validate_manifest(json.loads(trust.pinned(plan['reconnectManifest']),object_pairs_hook=c.unique_object));g.assert_new_pair_paths(rows,witness)
    row=next(r for r in rows if r['terminal']==7);directory=Path(row['directory']);out=Path(plan['outputDirectory'])
    c.require(not row['savedAlgoEnabled'] and not host.processes(row),'terminal07_must_be_closed_inert');c.verify_files(row)
    c.require(out.is_absolute() and out.parent.is_dir() and not out.exists(),'new_recovery_output_required')
    for folder in [directory,out.parent,Path(plan['controlDirectory']),Path(plan['journal']['path']).parent,Path(plan['state']['path']).parent]:
        c.require(folder.is_dir() and not any(v.is_symlink() or v.is_junction() for v in [folder,*folder.parents]),'recovery_path_alias')
    for root in [ntpath.dirname(v['path']) for v in witness['processes']]+[r['directory'] for r in rows]:
        a=c.canonical(str(out));b=c.canonical(root);c.require(a!=b and not a.startswith(b+'\\') and not b.startswith(a+'\\'),'output_scope')
    trust.pinned(plan['installation']);trust.pinned(plan['draft']);o.PINS=json.loads(trust.pinned(plan['pins']))
    api=historical_api(o.load_api(Path(plan['controlDirectory'])),Path(plan['installation']['path']),Path(plan['draft']['path']))
    c.require(api.installation['directory']==row['directory'] and api.installation['eaSha256']==row['eaSha256'],'installation_binding')
    failure_raw=trust.pinned(plan['failure']);failure=json.loads(failure_raw)
    api.module.verify_receipt(failure,{k:failure[k] for k in ('id','action','registrationSha256')},api.installation,api.reg['members'])
    c.require(failure['registrationSha256']==api.digest and g.read(api.root/(failure['id']+'.json'))==failure,'failure_native_binding');failure_scope(failure,api.reg)
    journal_path=Path(plan['journal']['path']);journal_raw=trust.pinned(plan['journal']);journal=o.Journal(journal_path.parent)
    c.require(journal_path.name=='journal.jsonl','original_journal_required');journal_failure(journal,failure_raw,plan['previousRecovery'],api)
    binding={'terminal':7,'registrationSha256':api.digest,'manifestSha256':plan['installation']['sha256']}
    c.require(journal.records[0].get('binding')==binding and g.read(api.root/'orchestration-owner.json')==
        {'schema':1,'runDirectory':str(journal_path.parent.resolve()),'binding':binding},'original_owner_binding')
    terminated,_,_=termination_evidence(plan,row)
    pending_raw=trust.pinned(plan['pendingRequest']);pending=json.loads(pending_raw)
    c.require(set(pending)=={'schema','id','action','registrationSha256','expiresAtUtc'} and pending['schema']==1
        and pending['id']==PENDING_ID and pending['action']=='status' and pending['registrationSha256']==api.digest
        and Path(plan['pendingRequest']['path']).resolve()==(api.root/'request.json').resolve(),'retained_read_only_request_required')
    receipt_path=api.root/(PENDING_ID+'.json')
    c.require(Path(plan['pendingReceipt']['path']).resolve()==receipt_path.resolve(),'pending_receipt_scope')
    pending_receipt_raw=trust.pinned(plan['pendingReceipt']);observed=json.loads(pending_receipt_raw)
    api.module.verify_receipt(observed,pending,api.installation,api.reg['members'])
    c.require(observed['result']=='observed' and observed['observedAtUtc']==1790231682
        and observed['connected'] is True and observed['tradingAllowed'] is False
        and observed['positions']==observed['orders']==0 and observed['commandPending'] is False
        and o.identities(observed)==o.identities(failure)
        and FAILED_AT<=observed['observedAtUtc']<=terminated['atUtc'],'pending_receipt_state_changed')
    common=g.raw(directory/'config/common.ini');c.require(p.digest(common)==row['commonIniSha256']
        and p.patch_common(common,row['login'],0)==common,'inert_config_changed')
    orphan=Path(plan['orphan']['path']);folder=directory/'MQL5/Profiles/Charts/Default'
    c.require(orphan.parent.resolve()==folder.resolve() and orphan.name=='chart28.chr','second_orphan_scope');trust.pinned(plan['orphan'])
    state=Path(plan['state']['path']);expected_state=Path(api.installation['commonFiles'])/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
    c.require(state.resolve()==expected_state.resolve() and Path(plan['globals']['path']).resolve()==(directory/'bases/gvariables.dat').resolve(),'state_scope')
    state_before=trust.pinned(plan['state']);state_after=v1.reset_state(state_before,api.reg,failure,index=INDEX);globals_raw=trust.pinned(plan['globals'])
    files=v1.saved_prefix(directory,api.reg,failure,orphan,index=INDEX,symbol='NZDUSD')
    for member in api.reg['members']:c.require(p.digest(g.raw(member['path']))==member['sha256'],'source_set_changed')
    return witness,rows,api,journal,dict(common=common,files=files,stateBefore=state_before,stateAfter=state_after,globals=globals_raw,
        failure=failure,journalRaw=journal_raw,pendingRaw=pending_raw,pendingReceiptRaw=pending_receipt_raw,registrationSha256=api.digest)


def validate_authority(path,expected_sha,journal,api):
    proof=json.loads(trust.pinned({'path':str(path),'sha256':expected_sha}));events=[r for r in journal.records if r['kind']=='recovery_authorized']
    c.require(proof.get('schema')==SCHEMA and proof.get('status')=='closed_partial_repair_complete' and proof.get('terminal')==7
        and proof.get('index')==INDEX and proof.get('registrationSha256')==api.digest
        and proof.get('runDirectory')==str(journal.directory.resolve()) and len(events)==2,'second_recovery_authority_scope')
    event=events[1];prefix=g.raw(journal.path,8*1024*1024).splitlines(keepends=True)[:event['sequence']]
    c.require(event.get('proofSha256')==expected_sha and event.get('proofPath')==str(Path(path).resolve())
        and p.digest(b''.join(prefix))==proof['journalBeforeSha256'],'second_recovery_authority_chain')
    old=SimpleNamespace(records=journal.records[:event['sequence']],path=journal.path,directory=journal.directory)
    receipts=[r for r in old.records if r['kind']=='receipt'];c.require(receipts,'second_recovery_failure_missing')
    raw=g.raw(journal.directory/receipts[-1]['file']);journal_failure(old,raw,proof['previousRecovery'],api);failure_scope(json.loads(raw),api.reg)
    c.require(proof['failureSha256']==p.digest(raw) and proof['target']=='recovery:deploy:26:'+proof['failureSha256']
        and event.get('target')==proof['target'] and proof['prefix']==[list(v) for v in o.identities(json.loads(raw))[:26]],'second_recovery_target')
    return proof


def run(args):
    plan=g.read(args.plan);host=c.WindowsHost();witness,rows,api,journal,data=inspect(plan,host,args.protected_witness)
    if not args.apply:return dict(status='dry_run_passed',terminal=7,preservedChildren=26,recoveryIndex=26,nativeCommands=0,priorExpandedDashboardDefaultsEqualityProven=False)
    with g.lifecycle_lock(witness),contextlib.ExitStack() as stack:
        for path in (journal.directory/'orchestration.lock',api.root/'orchestration.lock'):
            stack.enter_context(g.lifecycle_lock({'lifecycleLock':str(path)},wait_seconds=0))
        _,rows,api,journal,fresh=inspect(plan,host,args.protected_witness,expected=witness);c.require(fresh==data,'recovery_state_changed')
        out=Path(plan['outputDirectory']);out.mkdir();quoted=str(out).replace("'","''")
        host.powershell("$ErrorActionPreference='Stop'; & icacls '"+quoted+"' /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; if($LASTEXITCODE -ne 0){throw 'private evidence ACL failed'}")
        g.write_new(out/'intent.json',plan)
        for name,key in [('common.ini','common'),('dashboard-before.tsv','stateBefore'),('dashboard-after.tsv','stateAfter'),('gvariables.dat','globals'),('journal-before.jsonl','journalRaw'),('pending-status-request.json','pendingRaw')]:g.write_new(out/name,data[key])
        if data['pendingReceiptRaw'] is not None:g.write_new(out/'late-status-receipt.json',data['pendingReceiptRaw'])
        for key in ('previousRecovery','termination','sdkBefore','terminationIntent','failure'):g.write_new(out/(key+'.json'),trust.pinned(plan[key]))
        for name,blob in data['files'].items():
            path=out/'profile-before'/name;path.parent.mkdir(parents=True,exist_ok=True);g.write_new(path,blob)
        row=next(r for r in rows if r['terminal']==7);directory=Path(row['directory']);orphan=Path(plan['orphan']['path']);state=Path(plan['state']['path'])
        c.require(not host.processes(row) and g.raw(state)==data['stateBefore'] and trust.pinned(plan['pendingRequest'])==data['pendingRaw'],'terminal_or_state_changed')
        c.require(v1.saved_prefix(directory,api.reg,data['failure'],orphan,index=INDEX,symbol='NZDUSD')==data['files']
            and g.raw(directory/'config/common.ini')==data['common'] and trust.pinned(plan['globals'])==data['globals'],'persistence_changed_before_repair')
        trust.pinned(plan['orphan']);orphan.rename(out/'quarantined-empty-chart.chr');replace_preserving_acl(state,data['stateAfter'])
        c.require(g.raw(state)==data['stateAfter'] and g.raw(directory/'bases/gvariables.dat')==data['globals'],'repair_readback')
        claims=[[name,p.digest(blob)] for name,blob in data['files'].items() if name!=orphan.name]
        row['profileSha256']=p.digest(json.dumps(claims,separators=(',',':'),ensure_ascii=True).encode());c.verify_files(row,True)
        g.checked_witness(args.protected_witness,host,expected=witness);c.require(not host.processes(row),'terminal_started_during_repair')
        g.write_new(out/'reconnect-manifest.json',{'schema':'goat-demo-pair-connection-v1','terminals':rows})
        proof=dict(schema=SCHEMA,status='closed_partial_repair_complete',terminal=7,index=INDEX,registrationSha256=api.digest,
            runDirectory=str(journal.directory.resolve()),journalBeforeSha256=p.digest(data['journalRaw']),failureSha256=plan['failure']['sha256'],
            target='recovery:deploy:26:'+plan['failure']['sha256'],prefix=[list(v) for v in o.identities(data['failure'])[:26]],createdAtUtc=time.time(),
            previousRecovery=copy.deepcopy(plan['previousRecovery']),terminationSha256=plan['termination']['sha256'],pendingRequestSha256=p.digest(data['pendingRaw']),
            stateAfterSha256=p.digest(data['stateAfter']),profileSha256=row['profileSha256'],priorExpandedDashboardDefaultsEqualityProven=False)
        proof_path=out/'recovery-proof.json';g.write_new(proof_path,proof);proof_sha=p.digest(g.raw(proof_path))
        c.require(g.raw(journal.path,8*1024*1024)==data['journalRaw'],'journal_changed_during_repair')
        journal.add('recovery_authorized',proofPath=str(proof_path.resolve()),proofSha256=proof_sha,target=proof['target'])
        result=dict(status='closed_repair_staged_no_launch',recoveryProof=str(proof_path),recoveryProofSha256=proof_sha,nativeCommands=0)
        g.write_new(out/'completion.json',result);return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',required=True,type=Path);ap.add_argument('--protected-witness',required=True,type=Path)
    ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    try:print(json.dumps(run(args)))
    except (c.Refused,o.Stop) as error:print(json.dumps({'status':'needs_review','reason':str(error)}));raise SystemExit(2)
    except Exception as error:print(json.dumps({'status':'needs_review','reason':'inspect_retained_second_recovery_evidence','exceptionType':type(error).__name__}));raise SystemExit(2)
