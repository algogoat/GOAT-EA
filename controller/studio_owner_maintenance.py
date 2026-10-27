"""One-use owner-demo maintenance record and offline PARK authorization.

This slice cannot install a build, bootstrap, grant control or launch research.
The external journal survives PARK and preserves the original grant provenance.
"""
import hashlib
import re
import sqlite3
import time
import uuid
from contextlib import closing

from campaign_ledger import packed, sha
from studio_bridge import write_json
from studio_build_upgrade import retain
from studio_handover import database_view, paths, safe_path, guard, tree
from studio_installation import read_json, load_installation
from studio_native_gate import assert_clear_controls, exclusive_gate
from studio_orphan_recovery import recovery_lock
from studio_owner_research import authorize, POLICY_PATH, BINDING_KEYS


def directory(c):
    return safe_path(paths(c)[2]/'owner-maintenance')


def read_record(c, record_id, *, reconcile_park=False):
    if not re.fullmatch('[a-f0-9]{32}', record_id):
        raise ValueError('Exact owner maintenance record ID required')
    root = directory(c)/record_id
    value = read_json(safe_path(root/'record.json'))
    policy = read_json(POLICY_PATH)
    now = time.time()
    if (value.get('schema_version') != 1 or value.get('record_id') != record_id
            or value.get('policy_sha256') != sha(policy)
            or value.get('target_ea_sha256') != policy['maintenance']['target_ea_sha256']
            or value.get('plan_sha256') != policy['maintenance']['plan_sha256']
            or value.get('binding_sha256') != policy['binding_sha256']
            or value.get('original_run_id') != policy['run_id']
            or value.get('original_grant_request_id') != policy['grant_request_id']
            or value.get('original_grant_payload_hash') != policy['grant_payload_hash']
            or value.get('original_generation') != policy['generation']
            or not value['created_utc'] <= now
            or not value['created_utc'] < value['expires_utc'] <= policy['expires_utc']
            or (not reconcile_park and now >= value['expires_utc'])
            or value['expires_utc']-value['created_utc'] > policy['maintenance']['max_seconds']
            or not re.fullmatch('session-[a-f0-9]{32}', value.get('replacement_run_id', ''))
            or not re.fullmatch('[a-f0-9]{64}', value.get('nonce', ''))):
        raise ValueError('Owner maintenance record is expired or outside the exact policy')
    if (root/'revoked.json').exists():
        raise ValueError('Owner maintenance chain permanently revoked')
    states = value['database']['states']
    binding = packed(dict(terminal_id=value['session']['terminal_id'], run_id=policy['run_id']))
    if (len(states)!=1 or states[0][0]!=binding or states[0][2:]!=[policy['generation'],'agent']
            or value['session']['run_id']!=policy['run_id'] or value['session']['account']!=policy['account']):
        raise ValueError('Maintenance record does not preserve the original grant epoch and account')
    prepared = read_json(root/'prepared.json')
    if prepared != dict(record_sha256=sha(value), step='prepared',
                        authorization=value['authorization'], grants_control=False, starts_work=False):
        raise ValueError('Immutable owner maintenance record differs from its preparation receipt')
    return root, value


def revoke(root, reason):
    path = root/'revoked.json'
    if not path.exists():
        retain(path, (packed(dict(reason=reason))+'\n').encode())
    raise ValueError('Owner maintenance chain permanently revoked: '+reason)


def human_clear(root, human):
    for name in ('inbox', 'processing'):
        folder = safe_path(human/name)
        if not folder.is_dir() or any(folder.iterdir()):
            revoke(root, 'pending or unavailable original human channel')


def prepare(c):
    """Mint once while the original genuine grant and native demo are current."""
    with recovery_lock(c), exclusive_gate(c.local/'native-gate'):
        guard(c)
        assert_clear_controls(c.store.db, c.local/'native-gate')
        for path in (c.root/'monitor-repairs').glob('*.json'):
            repair=read_json(safe_path(path))
            if repair.get('phase')!='launched' and not (repair.get('stop_only') is True and repair.get('phase')=='stopped'):
                raise ValueError('Unfinished monitor repair must be reconciled before maintenance mint')
        if c.state()['queue'] or list((c.root/'attempts').glob('*')):
            raise ValueError('Owner maintenance requires an empty never-started session')
        policy = read_json(POLICY_PATH)
        record_id = uuid.uuid4().hex
        proof = authorize(c, 'owner-maintenance-prepare', record_id)
        parent = directory(c)
        parent.mkdir(parents=True, exist_ok=True)
        # One mint for this original grant, including expired/revoked records.
        # An uncertain mint is never replaced with a fresh identity.
        if any(parent.iterdir()):
            raise ValueError('Retained owner maintenance exists; inspect it, never mint another')
        now = time.time()
        value = dict(schema_version=1, record_id=record_id, policy_sha256=sha(policy),
                     binding_sha256=proof['binding_sha256'], original_run_id=c.run,
                     original_grant_request_id=proof['grant_request_id'],
                     original_grant_payload_hash=proof['grant_payload_hash'],
                     original_generation=proof['revocation_epoch'],
                     target_ea_sha256=policy['maintenance']['target_ea_sha256'],
                     plan_sha256=policy['maintenance']['plan_sha256'],
                     replacement_run_id='session-'+uuid.uuid4().hex,
                     nonce=uuid.uuid4().hex+uuid.uuid4().hex,
                     created_utc=now, expires_utc=min(now+policy['maintenance']['max_seconds'],policy['expires_utc']),
                     installation=c.install, session=c.session,
                     database=database_view(c.root/'studio.sqlite'), authorization=proof)
        folder = parent/record_id
        folder.mkdir()
        human_clear(folder, c.bridge.root/'human')
        state = c.state()
        if state['owner']!='agent' or state['generation']!=policy['generation']:
            revoke(folder, 'original grant changed during mint')
        if database_view(c.root/'studio.sqlite') != value['database']:
            revoke(folder, 'original database changed during mint')
        retain(folder/'record.json', (packed(value)+'\n').encode())
        retain(folder/'prepared.json', (packed(dict(record_sha256=sha(value), step='prepared',
               authorization=proof, grants_control=False, starts_work=False))+'\n').encode())
        return dict(record_id=record_id, record_sha256=sha(value), expires_utc=value['expires_utc'],
                    replacement_run_id=value['replacement_run_id'], status='prepared',
                    grants_control=False, starts_work=False)


def original_grant(c, original_root, original_local, value, *, current_build):
    """Independently verify provenance; a self-consistent record is not authority."""
    policy=read_json(POLICY_PATH)
    install=read_json(safe_path(original_root/'installation.json'))
    session=read_json(safe_path(original_root/'session.json'))
    binding={key:install[key] for key in BINDING_KEYS};binding['account']=session['account']
    if (sha(binding)!=policy['binding_sha256'] or session.get('demo_only') is not True
            or session['account']!=policy['account'] or session['run_id']!=policy['run_id']
            or install['ea_version']!=policy['ea_version'] or install['ea_sha256'] not in policy['allowed_ea_sha256']
            or install!=value['installation'] or session!=value['session']):
        raise ValueError('Original grant installation/account/build provenance differs')
    if current_build and load_installation(original_root/'installation.json')!=install:
        raise ValueError('Original installed artifact differs')
    key=packed(dict(terminal_id=session['terminal_id'],run_id=session['run_id']))
    from studio_agent import unique_object
    from studio_receipt_digest import receipt_views
    with closing(sqlite3.connect((original_root/'studio.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        rows=receipt_views(db,key,policy['grant_request_id'],object_pairs_hook=unique_object)
    if not rows or rows[0][1]!=policy['grant_payload_hash']:
        raise ValueError('Original genuine human grant receipt is missing or changed')
    receipt=rows[0][2]
    if (receipt.get('request_id')!=policy['grant_request_id'] or receipt.get('command')!='control.grant_agent'
            or receipt.get('status')!='applied' or receipt.get('execution_effect') is not False
            or receipt['state']['owner']!='agent' or receipt['state']['generation']!=policy['generation']
            or receipt['state']['terminal_id']!=session['terminal_id'] or receipt['state']['run_id']!=session['run_id']):
        raise ValueError('Original human grant receipt is not the policy-pinned grant')
    human=safe_path(original_local/session['directory_id']/'human/archive')
    files=list(human.glob(policy['grant_request_id']+'.*.json'))
    if len(files)!=1:
        raise ValueError('Exactly one original human grant archive is required')
    request=read_json(safe_path(files[0]))
    if (request.get('request_id')!=policy['grant_request_id'] or request.get('command')!='control.grant_agent'
            or request.get('payload')!={} or request.get('generation')!=policy['generation']-1
            or request.get('terminal_id')!=session['terminal_id'] or request.get('run_id')!=session['run_id']
            or sha(dict(request=request,actor='human'))!=policy['grant_payload_hash']):
        raise ValueError('Original archived human grant request differs from committed evidence')


def authorize_park(c, record_id, plan, *, publish=True):
    """Called inside exclusive handover lock after every writer is proven stopped.

    Existing PARK transaction/archives are the only accepted state transitions.
    A pending human event or any other original-epoch change retires the record.
    """
    root, value = read_record(c, record_id, reconcile_park=plan['status']!='review')
    review_id = plan['review_id']
    if (plan['action'] != 'park' or plan.get('restore')
            or value['installation'] != c.install
            or plan['observation']['installation_sha256'] != sha(value['installation'])):
        raise ValueError('Owner maintenance cannot authorize this installation or handover')
    observation = plan['observation']
    if plan['status']=='review' and time.time() > plan['expires_at']:
        raise ValueError('PARK review expired; obtain a fresh review before consuming maintenance')
    if len(observation['databases']) != 1 or observation['databases'][0] != value['database']:
        revoke(root, 'original database or ownership changed before PARK')
    identity = dict(record_sha256=sha(value), review_id=review_id,
                    observation_sha256=sha(observation), step='park')
    intent_path = root/'park-intent.json'
    prior = read_json(intent_path) if intent_path.exists() else None
    if prior is not None and {k:v for k,v in prior.items() if k!='stop'} != identity:
        raise ValueError('Owner maintenance PARK already belongs to another review')
    if plan['status'] != 'review' and prior is None:
        raise ValueError('PARK effect has no exact owner maintenance intent')
    archive = paths(c)[2]/review_id
    original_root, original_local = c.root, c.local
    for saved, expected in (('state','parked_state'), ('terminal','parked_terminal')):
        if (archive/saved).exists():
            if saved=='terminal':
                human_clear(root,archive/saved/value['session']['directory_id']/'human')
            if tree(archive/saved) != plan.get(expected):
                raise ValueError('Published PARK archive differs; preserve all evidence')
            if saved=='state': original_root=archive/saved
            else: original_local=archive/saved
    if read_json(original_root/'session.json') != value['session']:
        revoke(root, 'original session changed')
    human_clear(root, original_local/value['session']['directory_id']/'human')
    original_grant(c,original_root,original_local,value,current_build=plan['status']=='review')
    current = database_view(original_root/'studio.sqlite')
    # Only the known atomic PARK revocation may advance the original epoch.
    expected = value['database']
    after = dict(expected, states=[[b,r+1,g+1,'human'] for b,r,g,_ in expected['states']])
    current['path'] = expected['path']  # Physical archive path is checked above.
    allowed = [expected] if plan['status']=='review' else [after]
    if plan['status']=='revoking':
        allowed = [expected, after]
    if current not in allowed:
        revoke(root, 'original grant revoked or original research changed')
    repairs = original_root/'monitor-repairs'
    matches = []
    for path in repairs.glob('*.json'):
        stop = read_json(safe_path(path))
        if (stop.get('stop_only') is True and stop.get('phase') == 'stopped'
                and type(stop.get('created_at')) in (int,float) and stop['created_at']>=value['created_utc']
                and stop.get('installation_sha256') == sha(value['installation'])
                and stop.get('session_sha256') == sha(value['session'])
                and stop.get('native',{}).get('process') == value['authorization']['native']['process']):
            matches.append(dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if len(matches) != 1:
        raise ValueError('Exactly one verified stop of the originally observed terminal required')
    identity['stop'] = matches[0]
    # No active MT5 writer exists at this boundary. Handover's exclusive lock
    # excludes all supported controller/UI pumps until publication completes.
    human_clear(root, original_local/value['session']['directory_id']/'human')
    if prior is None and publish:
        retain(intent_path, (packed(identity)+'\n').encode())
    elif prior is not None and prior != identity:
        raise ValueError('Original terminal stop receipt changed')
    return root, identity


def park_complete(c, record_id, plan):
    root, identity = authorize_park(c, record_id, plan)
    retain(root/'parked.json', (packed(dict(identity, receipt_sha256=sha(plan),
           grants_control=False, starts_work=False))+'\n').encode())
