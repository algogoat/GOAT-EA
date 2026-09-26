"""Reviewed, offline Studio handover. Parks files; never starts or grants work.

The durable journal lives outside both directories being exchanged. An interrupted
apply is retried with the SAME review ID. Unknown filesystem states fail closed.
This coordinates trusted local tools, not an OS-user security boundary.
"""
from collections import Counter
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate

SETTLED = {'pending', 'completed', 'failed', 'cancelled', 'removed', 'superseded'}
MAX_FILES = 50000


def safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Handover refuses filesystem links: '+str(part))
    if path.resolve() != path:
        raise ValueError('Handover requires canonical paths')
    return path


def tree(path):
    path = safe_path(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise ValueError('Expected controller directory')
    files = {}
    for item in sorted(path.rglob('*')):
        safe_path(item)
        if item.is_dir():
            continue
        if not item.is_file() or len(files) >= MAX_FILES:
            raise ValueError('Unsupported or oversized controller directory')
        with item.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        files[item.relative_to(path).as_posix()] = digest
    return files


def paths(c):
    root, local = safe_path(c.root), safe_path(c.local)
    if root == local or root.is_relative_to(local) or local.is_relative_to(root):
        raise ValueError('Controller and terminal roots must be separate')
    archive = safe_path(root.parent/'.studio-handover'/root.name)
    lock = safe_path(local.parent/'.studio-handover-lock')
    return root, local, archive, lock


def stopped(c, databases):
    """Read complete process identities, excluding only this invocation's parents."""
    command = 'ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine)'
    raw = subprocess.check_output(['powershell', '-NoProfile', '-Command', command],
                                  text=True, encoding='utf-8-sig', timeout=20)
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError('Complete process inventory required')
    by_id = {r['ProcessId']: r for r in rows}
    if os.getpid() not in by_id or len(by_id) != len(rows):
        raise ValueError('Process inventory is incomplete or ambiguous')
    ancestors = set()
    pid = os.getpid()
    while pid in by_id and pid not in ancestors:
        ancestors.add(pid)
        pid = by_id[pid]['ParentProcessId']
    needles = [str(c.local).lower(), str(c.root).lower(), *(str(p).lower() for p in databases)]
    for row in rows:
        if row['ProcessId'] in ancestors:
            continue
        name = str(row.get('Name', '')).lower()
        command_line = str(row.get('CommandLine') or '').lower()
        if name in ('terminal64.exe', 'terminal.exe', 'metaeditor64.exe'):
            raise ValueError('Close MT5 terminals and MetaEditor before switching; none are stopped automatically')
        candidate = name.startswith(('python', 'goat')) or name in ('powershell.exe', 'pwsh.exe')
        if candidate and (not row.get('ExecutablePath') or not row.get('CommandLine')):
            raise ValueError('Controller process identity unavailable; reconcile before switching')
        if candidate and (name == 'goat.exe' or 'studio' in command_line or any(n in command_line for n in needles)):
            raise ValueError('Stop the existing controller/runner before switching (PID '+str(row['ProcessId'])+')')


def database_view(path):
    path = safe_path(path)
    if not path.is_file():
        raise ValueError('Referenced controller database is missing')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1)) as db:
        db.execute('BEGIN')
        states = [list(row) for row in db.execute('SELECT binding,revision,generation,owner FROM studio_state ORDER BY binding')]
        queues = list(db.execute('SELECT binding,jobs FROM studio_queues ORDER BY binding'))
        jobs = [j for _, raw in queues for j in json.loads(raw)]
        if any(j.get('status') not in SETTLED for j in jobs):
            raise ValueError('Unresolved native attempt; reconcile it with its original controller')
        if len(states) != 1 or any(row[3] not in ('agent', 'human') for row in states):
            raise ValueError('Unknown or shared controller ownership; inspect each terminal separately')
        gates = [str(safe_path(row[0])) for row in db.execute('SELECT root FROM studio_native_gate')]
        # Hash every durable table except ownership. This includes queues, drafts,
        # receipts and any campaign state, not just a stale display snapshot.
        content = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            if name == 'studio_state':
                continue
            quoted = '"'+name.replace('"', '""')+'"'
            rows = [sha(list(r)) for r in db.execute('SELECT * FROM '+quoted)]
            content[name] = sha(sorted(rows))
        return dict(path=str(path), states=states, content=content, gates=gates,
                    counts=dict(Counter(j['status'] for j in jobs)))


def inspect(c):
    root, local, _, _ = paths(c)
    databases = set()
    bindings = []
    active = None
    if (local/'active.json').exists():
        active = read_json(safe_path(local/'active.json'))
        if active.get('terminal_data_path') != c.install['terminal_data_root']:
            raise ValueError('Active Studio belongs to another terminal data path')
        directory = active.get('directory_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', directory):
            raise ValueError('Invalid active Studio directory')
        binding = read_json(safe_path(local/directory/'binding.json'))
        if any(binding.get(k) != active.get(k) for k in ('terminal_id', 'run_id')):
            raise ValueError('Active Studio binding differs from its retained bridge')
        databases.add(str(safe_path(binding['database'])))
        bindings.append(dict(kind='active', run_id=active['run_id'], database=binding['database']))
    # Inspect every retained gate, including root gates from older controllers.
    for owner in local.rglob('controller.json') if local.exists() else []:
        if owner.parent.name == 'native-gate':
            value = read_json(safe_path(owner))
            databases.add(str(safe_path(value['database'])))
            bindings.append(dict(kind='native-gate', path=str(owner.parent), database=value['database']))
    if (root/'studio.sqlite').exists():
        databases.add(str(root/'studio.sqlite'))
    stopped(c, databases)
    views = [database_view(p) for p in sorted(databases)]
    for view in views:
        if Path(view['path']).is_relative_to(local):
            raise ValueError('Legacy database inside the terminal needs a separate compatible migration')
        for gate in view['gates']:
            gate = safe_path(gate)
            if not gate.is_relative_to(local):
                raise ValueError('Controller gate lies outside this terminal; reconcile its scope first')
            if read_json(gate/'controller.json') != {'database': view['path']}:
                raise ValueError('Native gate database ownership differs')
            if any((gate/name).exists() for name in ('permit.json', 'request.json')):
                raise ValueError('Native request or permit remains; reconcile it before switching')
        seed = Path(view['path']).parent/'seed-active.json'
        if seed.exists() and read_json(seed).get('status') != 'released':
            raise ValueError('Seed runner still owns this terminal')
    return dict(installation_sha256=sha(c.install), active=active, bindings=bindings,
                databases=views, state_files=tree(root), terminal_files=tree(local))


def review(c, restore_id=None):
    guard(c)
    root, local, archive, _ = paths(c)
    observation = inspect(c)
    restore = None
    if restore_id:
        previous = load_plan(c, restore_id)
        if previous.get('status') != 'complete' or previous['action'] != 'park':
            raise ValueError('Choose a completed park receipt to restore')
        restore = dict(id=restore_id, state_files=tree(archive/restore_id/'state'),
                       terminal_files=tree(archive/restore_id/'terminal'))
        if restore['state_files'] != previous['parked_state'] or restore['terminal_files'] != previous['parked_terminal']:
            raise ValueError('Archived session changed; preserve and inspect it before restoration')
        old_receipt = archive/restore_id/'state'/'installation.json'
        if old_receipt.exists() and read_json(old_receipt) != read_json(root/'installation.json'):
            raise ValueError('Installation changed since parking; compatible migration required before restore')
        # External legacy databases must also remain exactly at their parked state.
        for view in previous['after_ownership']:
            if not Path(view['path']).is_relative_to(root) and database_view(view['path']) != view:
                raise ValueError('Archived session database changed outside its parked files')
    elif not observation['active'] and not observation['bindings'] and not observation['databases']:
        raise ValueError('No existing controller session to switch')
    review_id = uuid.uuid4().hex
    plan = dict(schema_version=1, review_id=review_id, action='restore' if restore else 'park',
                created_at=time.time(), expires_at=time.time()+600, status='review',
                observation=observation, restore=restore)
    if len(json.dumps(plan).encode('utf-8')) > 800000:
        raise ValueError('Handover inventory exceeds supported review size; preserve state for support')
    folder = archive/review_id
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder/'installation.json', c.install)
    write_json(folder/'receipt.json', plan)
    return public(plan)


def load_plan(c, review_id):
    if not re.fullmatch('[a-f0-9]{32}', review_id):
        raise ValueError('Use the retained review ID')
    _, _, archive, _ = paths(c)
    plan = read_json(safe_path(archive/review_id/'receipt.json'))
    if plan.get('review_id') != review_id or plan['observation']['installation_sha256'] != sha(c.install):
        raise ValueError('Review belongs to another installation')
    return plan


def public(plan):
    observation = plan['observation']
    return dict(review_id=plan['review_id'], action=plan['action'], status=plan['status'],
                expires_at_ms=int(plan['expires_at']*1000), bindings=observation['bindings'],
                databases=[dict(path=d['path'], counts=d['counts']) for d in observation['databases']],
                recovery_id=plan['review_id'], human_owned=True,
                next_action='Review preserved research, stop all controller processes, and explicitly confirm. After switching bootstrap a new session, then personally Give to Agent. Restoration never starts work.')


def move_once(source, target, expected):
    safe_path(source); safe_path(target)
    if expected is None:
        if source.exists() or target.exists():
            raise ValueError('Unexpected directory during retained handover')
        return
    if target.exists():
        if source.exists() or tree(target) != expected:
            raise ValueError('Ambiguous interrupted handover; preserve both directories')
        return
    if tree(source) != expected:
        raise ValueError('Controller files changed since review')
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)


def apply(c, review_id, confirmed=False):
    if not confirmed:
        raise ValueError('Explicit user review confirmation required')
    root, local, archive, lock = paths(c)
    lock.mkdir(parents=True, exist_ok=True)
    with exclusive_gate(lock):
        plan = load_plan(c, review_id)
        if plan['status'] == 'complete':
            pending = archive/'pending.json'
            if pending.exists() and read_json(pending) == {'review_id': review_id}:
                pending.unlink()
            return public(plan)
        folder = archive/review_id
        observation = plan['observation']
        stopped(c, [v['path'] for v in observation['databases']])
        if plan['status'] == 'review':
            if time.time() > plan['expires_at'] or inspect(c) != observation:
                pending = archive/'pending.json'
                if pending.exists() and read_json(pending) == {'review_id': review_id}:
                    pending.unlink()  # No revocation/move started in review phase.
                raise ValueError('Review expired or research changed; obtain a fresh review')
            if plan['restore']:
                prior = load_plan(c, plan['restore']['id'])
                saved = archive/plan['restore']['id']
                if tree(saved/'state') != plan['restore']['state_files'] or tree(saved/'terminal') != plan['restore']['terminal_files']:
                    raise ValueError('Restore source changed since review')
                for view in prior['after_ownership']:
                    if not Path(view['path']).is_relative_to(root) and database_view(view['path']) != view:
                        raise ValueError('Restore database changed since review')
            # Durable fence is checked by every updated public controller command.
            pending = archive/'pending.json'
            if pending.exists() and read_json(pending) != {'review_id': review_id}:
                raise ValueError('Another handover needs recovery first')
            write_json(pending, dict(review_id=review_id))
            plan['status'] = 'revoking'
            write_json(folder/'receipt.json', plan)
        if plan['status'] == 'revoking':
            after = []
            for old in observation['databases']:
                expected = dict(old, states=[[b, r+1, g+1, 'human'] for b, r, g, _ in old['states']])
                with ExitStack() as stack:
                    for gate in sorted(old['gates']):
                        stack.enter_context(exclusive_gate(gate))
                        if any((Path(gate)/name).exists() for name in ('permit.json', 'request.json')):
                            raise ValueError('Native controls changed during handover')
                    db = stack.enter_context(closing(sqlite3.connect(old['path'], timeout=1, isolation_level=None)))
                    db.execute('BEGIN IMMEDIATE')
                    current = database_view(old['path'])
                    if current == old:
                        db.execute("UPDATE studio_state SET owner='human',revision=revision+1,generation=generation+1")
                        db.execute('COMMIT')
                    elif current != expected:
                        raise ValueError('Controller changed during handover; reconcile retained receipt')
                if database_view(old['path']) != expected:
                    raise ValueError('Ownership revocation readback differs')
                after.append(expected)
            plan.update(after_ownership=after, parked_state=tree(root), parked_terminal=tree(local), status='parking')
            if plan['parked_terminal'] != observation['terminal_files']:
                raise ValueError('Terminal files changed during ownership reconciliation')
            before_files, after_files = observation['state_files'] or {}, plan['parked_state'] or {}
            allowed = set()
            for view in after:
                database = Path(view['path'])
                if database.is_relative_to(root):
                    relative = database.relative_to(root).as_posix()
                    allowed.update((relative, relative+'-wal', relative+'-shm', relative+'-journal'))
            if any(before_files.get(p) != after_files.get(p) for p in set(before_files) | set(after_files) if p not in allowed):
                raise ValueError('Controller files changed during ownership reconciliation')
            write_json(folder/'receipt.json', plan)
        if plan['status'] == 'parking':
            move_once(local, folder/'terminal', plan['parked_terminal'])
            move_once(root, folder/'state', plan['parked_state'])
            plan['status'] = 'installing'
            write_json(folder/'receipt.json', plan)
        if plan['status'] == 'installing':
            if plan['action'] == 'restore':
                prior = archive/plan['restore']['id']
                move_once(prior/'terminal', local, plan['restore']['terminal_files'])
                move_once(prior/'state', root, plan['restore']['state_files'])
            else:
                root.mkdir(parents=True, exist_ok=True)
                # Keep the app's registered installation receipt available. No
                # credentials, session, profile or controller grant are copied.
                receipt = folder/'state'/'installation.json'
                if receipt.exists():
                    target = root/'installation.json'
                    raw = receipt.read_bytes()
                    if target.exists() and target.read_bytes() != raw:
                        raise ValueError('Registered installation receipt changed during recovery')
                    if not target.exists():
                        with target.open('xb') as handle:
                            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            plan['status'] = 'complete'
            write_json(folder/'receipt.json', plan)
        pending = archive/'pending.json'
        if pending.exists():
            if read_json(pending) != {'review_id': review_id}:
                raise ValueError('Handover fence changed')
            pending.unlink()
        return public(plan)


def guard(c):
    _, _, archive, _ = paths(c)
    pending = archive/'pending.json'
    if pending.exists():
        raise ValueError('Interrupted Studio handover; resume switch-apply with review ID '+read_json(pending)['review_id'])


def session_lock(c):
    """Held for the entire public CLI operation, including a long-running serve."""
    lock = paths(c)[3]
    lock.mkdir(parents=True, exist_ok=True)
    return exclusive_gate(lock)


def recovery_installation(receipt):
    """Recover the registered receipt across the atomic state-directory rename."""
    receipt = safe_path(receipt)
    if receipt.name != 'installation.json':
        return receipt
    archive = safe_path(receipt.parent.parent/'.studio-handover'/receipt.parent.name)
    pending = read_json(archive/'pending.json')
    review_id = pending.get('review_id', '')
    if not re.fullmatch('[a-f0-9]{32}', review_id):
        raise ValueError('Invalid retained handover identity')
    saved = safe_path(archive/review_id/'installation.json')
    install = read_json(saved)
    if install.get('controller_state_root') != str(receipt.parent):
        raise ValueError('Recovery installation belongs to another state root')
    plan = read_json(archive/review_id/'receipt.json')
    if plan.get('status') not in ('revoking','parking','installing','complete') or sha(install) != plan['observation']['installation_sha256']:
        raise ValueError('Recovery installation differs from the retained handover')
    return saved
