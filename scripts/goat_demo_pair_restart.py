"""Pair-only post-inert-restart acknowledgement and fresh readiness proof."""
from datetime import datetime
import hashlib,json,time
from goat_demo_pair_connection import require as need
from goat_demo_pair_guard import raw as raw_file

def sha(data):return hashlib.sha256(data).hexdigest()

def identities(value):return [(r['chartId'],r['magic']) for r in value['rows']]


def process_identity(value,row):
    need(type(value) is dict and set(value)=={'pid','created','path'} and type(value['pid']) is int
         and value['pid']>0 and isinstance(value['created'],str),'invalid_process_identity')
    need(value['path'].replace('/','\\').casefold()==(row['directory']+'\\terminal64.exe').casefold(),'process_path')
    created=datetime.fromisoformat(value['created'].replace('Z','+00:00'))
    need(created.utcoffset() is not None,'process_timezone_required')
    return created.timestamp()


def restart_binding(prior_runtime,restart,row,audit,now):
    need(prior_runtime.get('readOnly') is True and isinstance(prior_runtime.get('accounts'),list),'prior_runtime_shape')
    old=[r for r in prior_runtime['accounts'] if r.get('terminal')==row['terminal']]
    new=[restart] if restart.get('terminal')==row['terminal'] else []
    need(len(old)==len(new)==1 and restart.get('schema')==1 and restart.get('status')=='verified_same_account','restart_receipt')
    old,new=old[0],new[0]
    need(old.get('status')=='observed' and new.get('status')=='verified_same_account' and new.get('launched') is True,'owned_restart_required')
    need(row['savedAlgoEnabled'] is False,'off_manifest_required')
    for state in (old,new.get('before',{}),new.get('after',{})):
        need(state.get('login')==row['login'] and state.get('server')==row['server']
             and state.get('dataPath')==row['directory'] and state.get('connected') is True
             and state.get('algoEnabled') is False and state.get('positionTickets')==[]
             and state.get('orderTickets')==[],'restart_not_same_inert_account')
    old_created=process_identity(old['process'],row);new_created=process_identity(new['process'],row)
    need(old['process']!=new['process'] and new_created>old_created,'new_process_required')
    need(old_created<=audit['observedAtUtc']<new_created<=now
         and old_created<=old['observedAtUtc']<new_created
         and 0<=now-audit['observedAtUtc']<=14400,'restart_chronology')
    return new['process']


def paired_restart_binding(prior_pair,runtime,restart,row,now):
    prior=prior_pair['audit']
    process=restart_binding(runtime,restart,row,prior,now)
    old=[item for item in runtime['accounts'] if item.get('terminal')==row['terminal']][0]
    need(prior_pair['proof']['process']==old['process'],'prior_pair_process_mismatch')
    need(prior['observedAtUtc']<=prior_pair['proof']['capturedAtUtc']<process_identity(process,row),
         'paired_restart_chronology')
    return process


def run_policy(api,runner,host,row,process,prior,claim_dir,write_new,paired,paired_output,clock=time.monotonic,sleep=time.sleep):
    expected=identities(prior)
    need(len(expected)==35 and len(set(c for c,m in expected))==35 and len(set(m for c,m in expected))==35
         and all(c>0 and m>0 for c,m in expected),'prior_35_identities_required')
    deadline=clock()+180;calls=0
    def call(action):
        nonlocal calls
        need(action in ('status','apply_policy','audit') and calls<64 and clock()<deadline,'operation_bound')
        need(host.processes(row)==[process],'restart_process_changed')
        calls+=1
        value=runner.call(action,'apply_policy' if action=='apply_policy' else None)
        need(host.processes(row)==[process],'restart_process_changed')
        need(identities(value)==expected,'child_identity_changed')
        need(all(value[k]==api.reg[k] for k in ('aiMode','aiThreshold','aiProtocol')),'ai_policy_changed')
        return value
    status=call('status')
    need(not status['commandPending'] and all(r['linkedFresh'] for r in status['rows']),'restart_children_not_ready')
    key=sha(json.dumps(process,sort_keys=True,separators=(',',':')).encode())
    claim_dir.mkdir(exist_ok=True)
    need(not claim_dir.is_symlink() and not claim_dir.is_junction(),'aliased_claim_directory')
    claim=claim_dir/(key+'.json')
    # O_EXCL + flush/fsync: changing --run-dir cannot bypass a prior attempt.
    write_new(claim,dict(schema=1,terminal=row['terminal'],process=process,registrationSha256=api.digest,
                         priorAuditId=prior['id'],runDirectory=str(runner.journal.directory.resolve()),intent='apply_policy_once'))
    value=call('apply_policy')
    command=value['commandId']
    need(command>0 and command not in (status['commandId'],prior['commandId']),'policy_command_not_new')
    ack_deadline=min(deadline,clock()+90)
    while True:
        need(value['commandId']==command,'policy_command_replaced')
        for child in value['rows']:
            if child['ackId']==command:need(child['ackStatus'] in (0,1),'policy_ack_rejected')
        if not value['commandPending'] and all(c['linkedFresh'] and c['ackId']==command and c['ackStatus']==1
             and c['exposureMode']==api.reg['exposureMode'] for c in value['rows']):break
        need(clock()<ack_deadline,'policy_ack_timeout');sleep(2);value=call('status')
    audit=call('audit')
    need(audit['commandId']==command,'audit_command_changed')
    # Never combine receipt fields or pretend older AI telemetry is current.
    # The core retains this native settings audit and a distinct fresh status.
    proof_path=paired.capture_pair(api.module,api.manifest,api.root/(audit['id']+'.json'),paired_output,host,
                                   request_status=lambda:call('status'))
    verified=paired.verify_stored_pair(api.module,proof_path,api.installation,api.reg,api.digest,
                                       max_age=10,current_process=process)
    need(verified['audit']['id']==audit['id'] and verified['audit']['commandId']==command
         and verified['status']['commandId']==command and verified['proof']['process']==process,'final_paired_binding')
    need(host.processes(row)==[process],'restart_process_changed')
    runner.journal.add('restart_policy_paired_ready',members=35,commandId=command,process=process,
                       pairedProofPath=str(proof_path),pairedProofSha256=sha(raw_file(proof_path)))
    return dict(status='restart_policy_paired_ready',ready=True,members=35,commandId=command,
                auditId=audit['id'],statusId=verified['status']['id'],pairedProofPath=str(proof_path),
                pairedProofSha256=sha(raw_file(proof_path)),process=process)
