"""Verify parked state and atomically replace its receipt under the session lock.

Trusted local setup coordination only. The authenticated installer must separately
verify admission, bundle/catalog identity and user setup scope. This module cannot
grant admission, pair an account, bootstrap a session or launch MT5.
"""
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import load_installation, read_json
from studio_native_gate import exclusive_gate
from studio_handover import paths, safe_path, load_plan, tree, database_view, stopped, guard, session_lock


def inspect_park(c, review_id, *, allowed_receipt_sha256=None):
    guard(c)
    from studio_bootstrap_retirement import handover_guard
    handover_guard(c)
    root,local,archive,_=paths(c);plan=load_plan(c,review_id);folder=archive/review_id
    if plan['status']!='complete' or plan['action']!='park' or plan.get('restore'):
        raise ValueError('Completed PARK handover required before receipt upgrade')
    if tree(folder/'state')!=plan['parked_state'] or tree(folder/'terminal')!=plan['parked_terminal']:
        raise ValueError('Parked research files changed')
    original=safe_path(folder/'state/installation.json').read_bytes()
    current=safe_path(root/'installation.json').read_bytes()
    old_digest=hashlib.sha256(original).hexdigest();digest=hashlib.sha256(current).hexdigest()
    if read_json(folder/'state/installation.json')!=c.install:
        raise ValueError('Archived receipt differs from reviewed installation')
    if digest not in (old_digest,allowed_receipt_sha256):
        raise ValueError('Registered receipt changed outside reviewed upgrade')
    if tree(root)!={'installation.json':digest} or local.exists():
        raise ValueError('A new session or unreviewed controller files exist after parking')
    for view in plan['after_ownership']:
        if not Path(view['path']).is_relative_to(root) and database_view(view['path'])!=view:
            raise ValueError('External parked controller database changed')
    stopped(c,[v['path'] for v in plan['after_ownership']])
    return dict(status='parked_verified',review_id=review_id,installation_sha256=sha(c.install),
                receipt_sha256=digest,review_sha256=hashlib.sha256((folder/'receipt.json').read_bytes()).hexdigest())


def verify_park(c, review_id):
    with session_lock(c):return inspect_park(c,review_id)


def replace_receipt(c, review_id, candidate, expected_sha256):
    if not re.fullmatch('[a-f0-9]{32}',review_id) or not re.fullmatch('[a-f0-9]{64}',expected_sha256):
        raise ValueError('Exact park review and old receipt SHA-256 required')
    from goat_studio import Controller
    root,local,archive,lock=paths(c);folder=safe_path(archive/review_id)
    # The retained reviewed installation is also available after successful CAS.
    old=Controller(folder/'installation.json')
    raw=safe_path(candidate).read_bytes()
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate candidate receipt key')
            result[key]=value
        return result
    if len(raw)>2_000_000:raise ValueError('Candidate receipt exceeds supported size')
    frozen=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
    desired=load_installation(safe_path(candidate))
    if frozen!=desired:
        raise ValueError('Canonical candidate receipt required')
    if any(old.install[k]!=desired[k] or old.install[k]!=c.install[k] for k in
           ('terminal_executable','terminal_data_root','common_files_root','controller_state_root')):
        raise ValueError('Receipt upgrade cannot change its physical installation target')
    if safe_path(candidate).is_relative_to(root) or safe_path(candidate).is_relative_to(local):
        raise ValueError('Stage candidate receipt outside active controller and terminal state')
    desired_digest=hashlib.sha256(raw).hexdigest()
    if desired_digest==expected_sha256:raise ValueError('Receipt upgrade requires a distinct candidate')
    lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock), ExitStack() as stack:
        plan=load_plan(old,review_id)
        # Serialize external legacy writers through validation and publication.
        for view in sorted(plan['after_ownership'],key=lambda x:x['path']):
            if not Path(view['path']).is_relative_to(root):
                db=stack.enter_context(closing(sqlite3.connect(view['path'],timeout=1,isolation_level=None)))
                db.execute('BEGIN IMMEDIATE')
        target=safe_path(root/'installation.json');journal=folder/'receipt-upgrade.json'
        expected=dict(schema_version=1,review_id=review_id,previous_sha256=expected_sha256,candidate_sha256=desired_digest,
                      previous_installation_sha256=sha(old.install),candidate_installation_sha256=sha(desired))
        retained=read_json(journal) if journal.exists() else None
        if retained is not None:
            if not isinstance(retained,dict) or any(retained.get(k)!=v for k,v in expected.items()):
                raise ValueError('Another or malformed receipt upgrade owns this park review')
            status=retained.get('status')
            extra={'receipt_sha256','session_created','agent_control_granted','terminal_started'} if status=='receipt_replaced' else set()
            if status not in ('publication_intent','receipt_replaced') or set(retained)!=set(expected)|{'status'}|extra:
                raise ValueError('Invalid retained receipt publication state')
            if status=='receipt_replaced' and (retained['receipt_sha256']!=desired_digest or any(retained[k] is not False for k in extra-{'receipt_sha256'})):
                raise ValueError('Retained replacement receipt differs')
        current=hashlib.sha256(target.read_bytes()).hexdigest()
        if current==desired_digest:
            if retained is None:raise ValueError('Candidate receipt appeared without retained publication intent')
            inspect_park(old,review_id,allowed_receipt_sha256=desired_digest)
        else:
            if current!=expected_sha256:raise ValueError('Old receipt compare-and-swap failed')
            verified=inspect_park(old,review_id)
            if verified['receipt_sha256']!=expected_sha256:raise ValueError('Reviewed old receipt differs')
            # Verify physical EA bytes again immediately before publication.
            if load_installation(candidate)!=desired:raise ValueError('Candidate artifact changed')
            write_json(journal,dict(expected,status='publication_intent'))
            saved=folder/'receipt-upgrade-candidate.json'
            if saved.exists() and saved.read_bytes()!=raw:raise ValueError('Retained candidate bytes differ')
            if not saved.exists():
                with saved.open('xb') as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
            # Same volume as the registered receipt, outside the active root so
            # an interrupted temp write cannot resemble a newly created session.
            temporary=folder/('.installation-'+uuid.uuid4().hex+'.tmp')
            try:
                with temporary.open('xb') as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
                if hashlib.sha256(target.read_bytes()).hexdigest()!=expected_sha256:raise ValueError('Old receipt changed before atomic publication')
                os.replace(temporary,target)
            finally:temporary.unlink(missing_ok=True)
        if target.read_bytes()!=raw:raise ValueError('Published receipt readback differs')
        result=dict(expected,status='receipt_replaced',receipt_sha256=desired_digest,session_created=False,agent_control_granted=False,terminal_started=False)
        write_json(journal,result)
        return result
