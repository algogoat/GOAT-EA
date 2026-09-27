"""Settle one expired, proven pre-consumption rejection; never retry recovery."""
import hashlib
import json
import time

from campaign_ledger import sha
from studio_bridge import write_json
from studio_build_upgrade import retain
from studio_dispatch_observe import observe_dispatch
from studio_handover import safe_path
from studio_installation import read_json
from studio_native_gate import exclusive_gate
from studio_orphan_recovery import inspect, plan_path, recovery_lock

# Both outcomes precede native consumption/effects. A foreign-file refusal
# additionally re-runs the complete host inventory through inspect below.
PRECONSUMPTION_REJECTIONS = frozenset(('ORPHAN_RUNTIME_REJECTED', 'ORPHAN_FOREIGN_CONTROL'))


def evidence_paths(c, review_id, request_id):
    gate=c.local/'native-gate'
    return {'review.json':plan_path(c,review_id),
            'issued.json':safe_path(gate/('issued-'+request_id+'.json')),
            'result.json':safe_path(gate/('result-'+request_id+'.json')),
            'request.json':safe_path(gate/'request.json'),
            'permit.json':safe_path(gate/'permit.json')}


def retained_evidence(c, plan):
    root=safe_path(plan_path(c,plan['review_id']).parent/'rejection-settlement')
    intent=read_json(safe_path(root/'intent.json'))
    if set(intent)!={'schema_version','review_id','request_id','sha256'} or intent['schema_version']!=1 or intent['review_id']!=plan['review_id']:
        raise ValueError('Rejected recovery settlement intent changed')
    if set(intent['sha256'])!={'review.json','issued.json','result.json','request.json','permit.json'}:
        raise ValueError('Rejected recovery evidence set changed')
    raw={name:safe_path(root/name).read_bytes() for name in intent['sha256']}
    if {name:hashlib.sha256(value).hexdigest() for name,value in raw.items()}!=intent['sha256']:
        raise ValueError('Retained rejected recovery evidence changed')
    original=json.loads(raw['review.json'])
    if original['status']!='issued' or original['review_id']!=intent['review_id'] or original['record']['request']['request_id']!=intent['request_id']:
        raise ValueError('Rejected recovery intent belongs to another review')
    settled=original | dict(status='rejected_settled',rejection_settlement_sha256=sha(intent))
    if plan not in (original,settled):
        raise ValueError('Rejected recovery review changed')
    return intent,raw,original,settled


def settled_status(c, plan):
    # Historical readback never removes a fence or touches a later request.
    intent,raw,original,settled=retained_evidence(c,plan)
    if plan!=settled: raise ValueError('Rejected recovery is not durably settled')
    request_id=original['record']['request']['request_id']
    if request_id!=sha(['orphan-recovery',plan['review_id'],original['observation']]):
        raise ValueError('Settled rejected recovery identity changed')
    files=evidence_paths(c,plan['review_id'],request_id)
    for name in ('issued.json','result.json'):
        if files[name].read_bytes()!=raw[name]: raise ValueError('Settled native rejection evidence changed')
    evidence=observe_dispatch(c.local/'native-gate',request_id)
    if evidence.get('consumed') is not False or evidence.get('receipt',{}).get('status') not in PRECONSUMPTION_REJECTIONS:
        raise ValueError('Settled native rejection evidence is no longer intact')
    fence=safe_path(c.root/'orphan-recovery-pending.json')
    pending=fence.exists() and read_json(fence)=={'review_id':plan['review_id']}
    return dict(status='reconcile_required' if pending else 'rejected_settled',review_id=plan['review_id'],
                request_id=intent['request_id'],launch_permitted=False,recovery_retried=False,native_flags_changed=False,
                next_action='Resume this exact rejected-request settlement' if pending else
                    'Rejection settled without recovery. Diagnose the cause; any later recovery needs a fresh explicitly approved review')


def verify_rejection(c, plan, raw, *, allow_missing_transport=False):
    record=plan['record'];request=record['request'];request_id=request['request_id']
    if (plan['schema_version']!=1 or plan['status']!='issued' or 'prior_request_utf8' not in plan or plan['prior_request_utf8'] is not None
            or record['prior_control']!={'status':'absent'} or plan['observation']['prior_control']!={'status':'absent'}):
        raise ValueError('Only rejection with originally absent controls can be settled')
    if (request_id!=sha(['orphan-recovery',plan['review_id'],plan['observation']])
            or request.get('action')!='recover_orphan_continuation' or request.get('recovery_protocol')!=1
            or type(request.get('expires_utc')) is not int or time.time()<=request['expires_utc']):
        raise ValueError('Exact expired orphan recovery request required')
    files=evidence_paths(c,plan['review_id'],request_id)
    if json.loads(raw['issued.json'])!=record or json.loads(raw['request.json'])!=request or json.loads(raw['permit.json'])!={'request_sha256':record['request_sha256']}:
        raise ValueError('Rejected recovery issuance or transport differs')
    if hashlib.sha256(raw['request.json']).hexdigest()!=record['request_sha256']:
        raise ValueError('Rejected recovery request bytes changed')
    for name in ('issued.json','result.json','permit.json','request.json'):
        path=files[name]
        if not path.exists() and allow_missing_transport and name in ('permit.json','request.json'): continue
        if path.read_bytes()!=raw[name]: raise ValueError('Rejected recovery evidence or transport changed')
    # A missing request with a remaining permit is not a prefix of our cleanup.
    if not files['request.json'].exists() and files['permit.json'].exists():
        raise ValueError('Rejected recovery cleanup order changed')
    if any(safe_path(path).exists() for path in c.local.rglob('consumed-*.json')):
        raise ValueError('Native consumption exists; rejection settlement is forbidden')
    evidence=observe_dispatch(c.local/'native-gate',request_id)
    if (evidence['status']!='receipt_observed' or evidence.get('consumed') is not False
            or evidence['receipt']['status'] not in PRECONSUMPTION_REJECTIONS
            or evidence['receipt']!=json.loads(raw['result.json'])):
        raise ValueError('Exact supported pre-consumption rejection required')
    if inspect(c,expected_batch=True,allow_own_request=record)!=plan['observation']:
        raise ValueError('Rejected recovery process, monitor, account or control state changed')
    # Runtime observation may take time. Recheck bytes/consumption after it,
    # still under the same gate, before the caller retires any transport.
    if any(safe_path(path).exists() for path in c.local.rglob('consumed-*.json')):
        raise ValueError('Native consumption appeared during rejection review')
    for name in ('issued.json','result.json','permit.json','request.json'):
        path=files[name]
        if not path.exists() and allow_missing_transport and name in ('permit.json','request.json'): continue
        if path.read_bytes()!=raw[name]: raise ValueError('Rejected recovery evidence changed during runtime observation')


def reconcile_rejection(c, review_id, *, confirmed=False):
    if not confirmed: raise ValueError('Explicit review confirmation required for rejection settlement')
    with recovery_lock(c):
        path=plan_path(c,review_id);plan=read_json(path)
        if plan.get('review_id')!=review_id or plan.get('status') not in ('issued','rejected_settled'):
            raise ValueError('Exact issued or interrupted rejected recovery required')
        root=safe_path(path.parent/'rejection-settlement');journal=safe_path(root/'intent.json')
        gate=safe_path(c.local/'native-gate');fence=safe_path(c.root/'orphan-recovery-pending.json')
        with exclusive_gate(gate):
            if plan['status']=='rejected_settled' and not fence.exists():
                return settled_status(c,plan) | dict(reused=True)
            if not fence.exists() or read_json(fence)!={'review_id':review_id}:
                raise ValueError('Rejected recovery fence changed')
            if journal.exists():
                intent,raw,original,settled=retained_evidence(c,plan)
            else:
                if plan['status']!='issued': raise ValueError('Missing rejected recovery settlement intent')
                files=evidence_paths(c,review_id,plan['record']['request']['request_id'])
                raw={name:file.read_bytes() for name,file in files.items()}
                original=plan
                if json.loads(raw['review.json'])!=original: raise ValueError('Recovery review changed before settlement')
                verify_rejection(c,original,raw)
                root.mkdir(exist_ok=True)
                for name,value in raw.items(): retain(root/name,value)
                intent=dict(schema_version=1,review_id=review_id,request_id=original['record']['request']['request_id'],
                            sha256={name:hashlib.sha256(value).hexdigest() for name,value in raw.items()})
                # All exact evidence is fsynced before publishing cleanup intent.
                write_json(journal,intent)
                intent,raw,original,settled=retained_evidence(c,plan)
            files=evidence_paths(c,review_id,intent['request_id'])
            # Recheck fresh identity, rejection and all bytes before every removal.
            for name in ('permit.json','request.json'):
                verify_rejection(c,original,raw,allow_missing_transport=True)
                retained_evidence(c,plan)
                if read_json(path)!=plan or read_json(fence)!={'review_id':review_id}:
                    raise ValueError('Rejected recovery review or fence changed during cleanup')
                if files[name].exists(): files[name].unlink()
            verify_rejection(c,original,raw,allow_missing_transport=True)
            retained_evidence(c,plan)
            if read_json(path)!=plan or read_json(fence)!={'review_id':review_id}:
                raise ValueError('Rejected recovery review or fence changed before settlement')
            # Durable terminal status precedes fence removal. Original evidence
            # and the native result stay forever; no original-ID replay can run.
            write_json(path,settled)
            verify_rejection(c,original,raw,allow_missing_transport=True)
            retained_evidence(c,settled)
            if read_json(path)!=settled or read_json(fence)!={'review_id':review_id}:
                raise ValueError('Rejected recovery settlement or fence changed')
            fence.unlink()
            return settled_status(c,settled)
