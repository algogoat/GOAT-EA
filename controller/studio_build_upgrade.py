"""Exact same-version parked build exchange; admission belongs to the installer.

This entrypoint intentionally runs before Controller construction: an interrupted
EA/receipt pair cannot pass the ordinary installed-artifact hash check. Only the
retained transaction's exact old/new bytes may be reconciled here. Ordinary
controller commands remain fenced and retain their full hash validation.
"""
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
from types import SimpleNamespace
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import paths, safe_path, load_plan
from studio_installation import load_installation, read_json
from studio_installation_upgrade import inspect_park
from studio_native_gate import exclusive_gate


def receipt_snapshot(source):
    raw=source.read_bytes()
    if len(raw)>2_000_000:raise ValueError('Receipt exceeds supported size')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate build receipt key')
            result[key]=value
        return result
    value=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
    if not isinstance(value,dict):raise ValueError('Build receipt must be an object')
    return raw,value


def pending_path(root):
    return safe_path(Path(root).parent/'.internal-qualification-updates'/Path(root).name/'ea-update.pending.json')


def guard_pending(root, expected=None):
    pending=pending_path(root)
    if pending.exists() and (expected is None or read_json(pending)!=expected):
        raise ValueError('Interrupted EA build update; preserve evidence and reconcile the exact switch-replace-build transaction')


def retain(path, raw):
    safe_path(path)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('Retained build bytes differ; preserve transaction evidence')
    else:
        with path.open('xb') as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())


def replace_bytes(target, raw):
    temporary=target.parent/('.build-upgrade-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)


def replace_build(receipt, review_id, candidate_receipt, candidate_ea, expected_sha256):
    if not re.fullmatch('[a-f0-9]{32}',review_id) or not re.fullmatch('[a-f0-9]{64}',expected_sha256):
        raise ValueError('Exact completed park review and previous receipt SHA-256 required')
    receipt=safe_path(receipt)
    if receipt.name!='installation.json':raise ValueError('Registered installation.json required')
    root=receipt.parent
    folder=safe_path(root.parent/'.studio-handover'/root.name/review_id)
    archived=safe_path(folder/'state/installation.json')
    old_raw,old=receipt_snapshot(archived)
    if hashlib.sha256(old_raw).hexdigest()!=expected_sha256 or old.get('controller_state_root')!=str(root):
        raise ValueError('Reviewed previous receipt does not match exact registered target')
    c=SimpleNamespace(install=old,root=root,local=Path(old['terminal_data_root'])/'MQL5/Files/GOATStudio')
    _,local,_,lock=paths(c)
    candidate_receipt=safe_path(candidate_receipt);candidate_ea=safe_path(candidate_ea)
    for source in (candidate_receipt,candidate_ea):
        if source.is_relative_to(root) or source.is_relative_to(local):
            raise ValueError('Stage build candidate outside active controller and terminal state')
    raw,desired=receipt_snapshot(candidate_receipt)
    mutable={'bundle_version','ea_sha256','agent_guide_path','installed_at'}
    if not isinstance(desired,dict) or set(desired)!=set(old) or any(desired[k]!=old[k] for k in set(old)-mutable):
        raise ValueError('Same-version build replacement cannot change installation identity or catalog')
    if not re.fullmatch('[a-f0-9]{64}',str(desired.get('ea_sha256',''))) or desired['ea_sha256']==old['ea_sha256']:
        raise ValueError('A distinct exact reviewed EA build SHA-256 is required')
    binary=safe_path(Path(old['terminal_data_root'])/'MQL5/Experts'/Path(*PureWindowsPath(old['ea_relative_path']).parts))
    experts=safe_path(Path(old['terminal_data_root'])/'MQL5/Experts')
    if not binary.is_relative_to(experts):raise ValueError('EA build target escapes Experts')
    new_ea=candidate_ea.read_bytes()
    if not new_ea or len(new_ea)>100_000_000 or hashlib.sha256(new_ea).hexdigest()!=desired['ea_sha256']:
        raise ValueError('Candidate EA bytes differ from reviewed receipt')
    desired_sha=hashlib.sha256(raw).hexdigest()
    expected=dict(schema_version=1,review_id=review_id,previous_sha256=expected_sha256,candidate_sha256=desired_sha,
                  previous_ea_sha256=old['ea_sha256'],candidate_ea_sha256=desired['ea_sha256'],
                  previous_installation_sha256=sha(old),candidate_installation_sha256=sha(desired))
    fence=dict(review_id=review_id,transaction_sha256=sha(expected))
    lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock),ExitStack() as stack:
        plan=load_plan(c,review_id)
        for view in sorted(plan['after_ownership'],key=lambda x:x['path']):
            if not Path(view['path']).is_relative_to(root):
                database=safe_path(view['path'])
                db=stack.enter_context(closing(sqlite3.connect(database,timeout=1,isolation_level=None)))
                db.execute('BEGIN IMMEDIATE')
        journal=safe_path(folder/'build-upgrade.json');pending=pending_path(root)
        retained=read_json(journal) if journal.exists() else None
        if journal.exists() and not isinstance(retained,dict):raise ValueError('Malformed build transaction journal')
        old_ea_path=safe_path(folder/'build-upgrade.previous.ex5')
        saved_ea=safe_path(folder/'build-upgrade.candidate.ex5')
        saved_receipt=safe_path(folder/'build-upgrade.candidate.json')
        if retained is not None:
            if not isinstance(retained,dict):raise ValueError('Malformed build transaction journal')
            extra={'receipt_sha256','ea_sha256','session_created','agent_control_granted','terminal_started'} if retained.get('status')=='build_replaced' else set()
            if (not isinstance(retained,dict) or any(retained.get(k)!=v for k,v in expected.items())
                or retained.get('status') not in ('publication_intent','build_replaced')
                or set(retained)!=set(expected)|{'status'}|extra):
                raise ValueError('Another or malformed build transaction owns this park review')
            if extra and (retained['receipt_sha256']!=desired_sha or retained['ea_sha256']!=desired['ea_sha256']
                          or any(retained[k] is not False for k in extra-{'receipt_sha256','ea_sha256'})):
                raise ValueError('Completed build receipt differs')
            if hashlib.sha256(old_ea_path.read_bytes()).hexdigest()!=old['ea_sha256'] or saved_ea.read_bytes()!=new_ea or saved_receipt.read_bytes()!=raw:
                raise ValueError('Retained build recovery bytes changed')
        elif load_installation(archived)!=old:
            raise ValueError('Previous installed artifact is not canonical')
        if pending.exists() and read_json(pending)!=fence:raise ValueError('Another build update owns the pending fence')
        current_receipt=hashlib.sha256(receipt.read_bytes()).hexdigest()
        current_ea=hashlib.sha256(binary.read_bytes()).hexdigest()
        if current_receipt not in (expected_sha256,desired_sha) or current_ea not in (old['ea_sha256'],desired['ea_sha256']):
            raise ValueError('Build compare-and-swap failed; preserve changed files')
        if retained is None and (current_receipt!=expected_sha256 or current_ea!=old['ea_sha256']):
            raise ValueError('Candidate appeared without retained publication intent')
        if current_receipt==desired_sha and current_ea!=desired['ea_sha256']:
            raise ValueError('Ambiguous build publication pair; preserve recovery evidence')
        inspect_park(c,review_id,allowed_receipt_sha256=desired_sha,build_update_fence=fence)
        if retained is None:
            previous_ea=binary.read_bytes()
            if hashlib.sha256(previous_ea).hexdigest()!=old['ea_sha256']:
                raise ValueError('Previous EA changed before durable backup')
            retain(old_ea_path,previous_ea);retain(saved_ea,new_ea);retain(saved_receipt,raw)
            write_json(journal,dict(expected,status='publication_intent'))
        pending.parent.mkdir(parents=True,exist_ok=True)
        if not pending.exists():write_json(pending,fence)
        # Recheck every protected state with the exclusive session and database
        # locks held; no TS-side verification can substitute for this boundary.
        inspect_park(c,review_id,allowed_receipt_sha256=desired_sha,build_update_fence=fence)
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=current_ea or hashlib.sha256(receipt.read_bytes()).hexdigest()!=current_receipt:
            raise ValueError('Installed bytes changed immediately before build publication')
        if current_ea!=desired['ea_sha256']:replace_bytes(binary,new_ea)
        # A crash here leaves the exact intent/fence/backups. Only this same
        # operation can reconcile; Controller still rejects the mismatched pair.
        inspect_park(c,review_id,allowed_receipt_sha256=desired_sha,build_update_fence=fence)
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=desired['ea_sha256'] or hashlib.sha256(receipt.read_bytes()).hexdigest()!=current_receipt:
            raise ValueError('Installed bytes changed before receipt publication; preserve recovery evidence')
        if current_receipt!=desired_sha:replace_bytes(receipt,raw)
        if receipt.read_bytes()!=raw or load_installation(receipt)!=desired:
            raise ValueError('Build publication readback differs; preserve recovery evidence')
        result=dict(expected,status='build_replaced',receipt_sha256=desired_sha,ea_sha256=desired['ea_sha256'],
                    session_created=False,agent_control_granted=False,terminal_started=False)
        write_json(journal,result)
        if read_json(pending)!=fence:raise ValueError('Build fence changed before completion')
        pending.unlink()
        return result
