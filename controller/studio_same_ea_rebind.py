"""Rebind a demo Studio session after a stopped same-EA desktop receipt rewrite.

This repairs local metadata only. It never launches MT5, settles an attempt,
clears a permit, changes ownership or enables trading. The original attempt
must be reconciled through its original receipt before this command can run.
"""
import hashlib
import json
import os
import shutil
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import load_installation, read_json
from studio_native_gate import exclusive_gate
from studio_seed_process import WindowsSeedProcess


ALLOWED_RECEIPT_DELTA = {'bundle_version', 'installed_at', 'agent_guide_path'}
SETTLED_JOBS = {'completed', 'failed', 'cancelled', 'removed', 'superseded'}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab') as output:
        output.write((json.dumps(row, sort_keys=True, allow_nan=False) + '\n').encode())
        output.flush(); os.fsync(output.fileno())


def rebind(receipt_path, *, process=None):
    receipt_path = safe_path(Path(receipt_path).absolute())
    current = load_installation(receipt_path)
    state = safe_path(Path(current['controller_state_root']))
    local = safe_path(Path(current['terminal_data_root']) / 'MQL5/Files/GOATStudio')
    lock = safe_path(local.parent / '.studio-handover-lock')
    lock.mkdir(parents=True, exist_ok=True)
    (state / 'batch-driver-gate').mkdir(parents=True, exist_ok=True)
    (local / 'native-gate').mkdir(parents=True, exist_ok=True)
    with exclusive_gate(lock), exclusive_gate(state / 'batch-driver-gate'), exclusive_gate(local / 'native-gate'):
        session_path = safe_path(state / 'session.json')
        session_raw = session_path.read_bytes()
        session = read_json(session_path)
        if session.get('installation_sha256') == sha(current):
            return dict(status='already_bound', installation_sha256=sha(current), native_action=False)
        if session.get('demo_only') is not True or not re.fullmatch(r'[1-9][0-9]{0,19}', str(session.get('account', {}).get('login', ''))):
            raise ValueError('Only an existing exact demo session can be rebound')
        if shutil.disk_usage(state).free < 5 * 1024 ** 3:
            raise ValueError('At least 5 GiB free disk is required for demo metadata recovery')
        if process is None:
            process = WindowsSeedProcess(SimpleNamespace(install=current))
        if process.inspect() is not None:
            raise ValueError('Selected terminal must be stopped for same-EA receipt rebind')
        if any((local / 'native-gate' / name).exists() for name in ('request.json', 'permit.json')):
            raise ValueError('Unresolved native request or permit; reconcile with the original receipt first')
        human = local / session['directory_id'] / 'human'
        if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
            raise ValueError('Pending human control takes priority over session rebind')
        active = read_json(safe_path(local / 'active.json'))
        if active != dict(directory_id=session['directory_id'], terminal_id=session['terminal_id'],
                          run_id=session['run_id'], terminal_data_path=current['terminal_data_root']):
            raise ValueError('Active Studio session differs from the retained demo binding')
        db_path = safe_path(state / 'studio.sqlite')
        if not db_path.is_file():
            raise ValueError('Controller database missing; preserve original session')
        db_before = _digest(db_path.read_bytes())
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as db:
            for (packed_jobs,) in db.execute('SELECT jobs FROM studio_queues'):
                jobs = json.loads(packed_jobs)
                if any(job.get('status') not in SETTLED_JOBS for job in jobs):
                    raise ValueError('Controller queue has an unresolved attempt; reconcile it first')
        backups = []
        for candidate in safe_path(state / 'ea-update-backups').glob('*/installation.json'):
            candidate = safe_path(candidate)
            previous = load_installation(candidate)
            if sha(previous) == session['installation_sha256']:
                backups.append((candidate, previous))
        if len(backups) != 1:
            raise ValueError('Exactly one preserved previous installation must match the bound session')
        backup_path, previous = backups[0]
        if previous.get('receipt_path') != current.get('receipt_path') or (current.get('receipt_path')
                and Path(current['receipt_path']).resolve() != receipt_path):
            raise ValueError('Registered receipt path changed across the update')
        for key in set(previous) | set(current):
            if key not in ALLOWED_RECEIPT_DELTA and previous.get(key) != current.get(key):
                raise ValueError('Same-EA rebind refuses a changed installation field: ' + key)
        if previous['ea_sha256'] != current['ea_sha256']:
            raise ValueError('Same-EA rebind requires identical physical EA bytes')
        if (state / 'ea-update.pending.json').exists():
            raise ValueError('Interrupted desktop EA update must be resolved first')
        if db_before != _digest(db_path.read_bytes()) or session_raw != session_path.read_bytes():
            raise ValueError('Controller database or session changed during rebind review')
        record_root = state / 'same-ea-rebind'
        record_root.mkdir(parents=True, exist_ok=True)
        saved = record_root / ('session-' + _digest(session_raw) + '.json')
        if saved.exists():
            if saved.read_bytes() != session_raw:
                raise ValueError('Retained previous session changed')
        else:
            with saved.open('xb') as output:
                output.write(session_raw); output.flush(); os.fsync(output.fileno())
        log = record_root / 'actions.jsonl'
        _append(log, dict(phase='before_rebind', old_sha256=sha(previous), new_sha256=sha(current),
                          backup=str(backup_path), db_sha256=db_before, native_action=False))
        session['installation_sha256'] = sha(current)
        write_json(session_path, session)
        if db_before != _digest(db_path.read_bytes()):
            raise ValueError('Controller database changed after local session rebind; preserve evidence')
        _append(log, dict(phase='verified', installation_sha256=sha(current),
                          session_sha256=sha(session), native_action=False))
        return dict(status='rebound', installation_sha256=sha(current),
                    previous_session_backup=str(saved), native_action=False,
                    native_qualification=False)
