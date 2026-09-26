"""Reviewed protection of one existing peer; never ignore unknown terminals.

The policy lives outside both switched directories. It records a particular
running process, not permission to manage it. Replacement requires a new review.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate


def directory(c):
    from studio_handover import safe_path
    return safe_path(c.local.parent/'.studio-peer-policy')


def target(c):
    return {key:c.install[key] for key in ('terminal_executable','terminal_data_root','common_files_root','controller_state_root')}


def material(c, executable, data_root):
    from studio_handover import safe_path
    if not Path(executable).is_absolute() or not Path(data_root).is_absolute():
        raise ValueError('Absolute protected peer paths required')
    executable, data = safe_path(executable), safe_path(data_root)
    if not executable.is_absolute() or executable.name.lower()!='terminal64.exe' or not executable.is_file() or not (data/'MQL5').is_dir():
        raise ValueError('Existing peer terminal64.exe and absolute MT5 data root required')
    roots=[Path(c.install['terminal_executable']).parent, Path(c.install['terminal_data_root']),
           c.root, Path(c.install['common_files_root'])]
    for peer in (executable.parent, data):
        if any(peer.is_relative_to(root) or root.is_relative_to(peer) for root in roots):
            raise ValueError('Protected peer paths overlap selected terminal, controller or Common Files')
    origin = None
    if data != executable.parent:
        raw=safe_path(data/'origin.txt').read_bytes()
        text=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        if PureWindowsPath(text.strip())!=PureWindowsPath(executable.parent):
            raise ValueError('Peer origin.txt does not bind the executable to its data root')
        origin=hashlib.sha256(raw).hexdigest()
    return dict(executable=str(executable), data_root=str(data),
                executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), origin_sha256=origin)


def observe(c, peer):
    from studio_process_check import classify_processes
    command='ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\' OR Name=\'terminal.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    rows=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command], text=True,encoding='utf-8-sig',timeout=20))
    if not isinstance(rows,list): raise ValueError('Complete terminal inventory required')
    count=sum(PureWindowsPath(r.get('ExecutablePath') or '')==PureWindowsPath(c.install['terminal_executable']) for r in rows)
    if count not in (0,1): raise ValueError('Ambiguous selected terminal process')
    result=classify_processes(rows,dict(research_terminal=c.install['terminal_executable'],protected_terminal=peer['executable']),
                             observed_unix=time.time(),research_running=bool(count))
    return result['protected']


def policy(c):
    path=directory(c)/'policy.json'
    if not path.exists(): return None
    value=read_json(path)
    if value.get('schema_version')!=1 or value.get('target')!=target(c):
        raise ValueError('Protected peer policy belongs to another installation target')
    if material(c,value['peer']['executable'],value['peer']['data_root'])!=value['peer']:
        raise ValueError('Protected peer executable or data binding changed; review again')
    process=value.get('process',{})
    if (set(process)!={'pid','executable','created_utc'} or type(process['pid']) is not int or process['pid']<=0
            or not process['created_utc'] or PureWindowsPath(process['executable'])!=PureWindowsPath(value['peer']['executable'])):
        raise ValueError('Exact protected peer process identity required')
    return value


def binding_fields(c):
    value=policy(c)
    if value is None: return {}
    return dict(protected_terminal=value['peer']['executable'],protected_data_roots=[value['peer']['data_root']],
                protected_process=value['process'],protected_policy_sha256=sha(value),protected_may_be_stopped=True)


def process_binding(c):
    return dict(research_terminal=c.install['terminal_executable'],**binding_fields(c))


def _idle(c):
    # This may run before bootstrap. Never open a mutable controller/bridge here.
    from studio_seed_slot import guard_active_seed
    guard_active_seed(c.root)
    database=c.root/'studio.sqlite'
    if database.exists():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            for row in db.execute('SELECT jobs FROM studio_queues'):
                if any(j.get('status') not in ('pending','completed','cancelled','failed','removed','superseded')
                       or (j.get('status')=='pending' and j.get('launch_intent')) for j in json.loads(row[0])):
                    raise ValueError('Reconcile native attempts before changing protected peer policy')


def prepare(c, executable, data_root):
    from studio_handover import session_lock, guard
    with session_lock(c):
        guard(c)
        folder=directory(c);folder.mkdir(parents=True,exist_ok=True)
        with exclusive_gate(folder):
            _idle(c)
            peer=material(c,executable,data_root)
            process=observe(c,peer)
            existing=folder/'policy.json'
            review=dict(schema_version=1,review_id=uuid.uuid4().hex,status='review',expires_at=time.time()+600,
                        target=target(c),peer=peer,process=process,
                        previous_sha256=hashlib.sha256(existing.read_bytes()).hexdigest() if existing.exists() else None)
            write_json(folder/(review['review_id']+'.json'),review)
            return review | dict(effect='Protect this exact peer from selected-terminal setup and switching; no ownership, close or launch permission')


def apply(c, review_id, confirmed=False):
    from studio_handover import paths, guard
    if not confirmed: raise ValueError('Authorized caller confirmation of the exact protected peer review required')
    if not re.fullmatch('[a-f0-9]{32}',review_id): raise ValueError('Retained peer review ID required')
    lock=paths(c)[3];lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock):
        guard(c)
        folder=directory(c)
        with exclusive_gate(folder):
            review=read_json(folder/(review_id+'.json'))
            if review.get('review_id')!=review_id or review.get('target')!=target(c): raise ValueError('Peer review target changed')
            peer=material(c,review['peer']['executable'],review['peer']['data_root'])
            if peer!=review['peer'] or observe(c,peer)!=review['process']: raise ValueError('Protected peer changed since review')
            desired={key:review[key] for key in ('schema_version','review_id','target','peer','process')}
            path=folder/'policy.json'
            if path.exists() and read_json(path)==desired: return dict(status='protected',policy=desired,reused=True)
            if time.time()>review['expires_at']: raise ValueError('Peer review expired')
            if (hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)!=review['previous_sha256']:
                raise ValueError('Protected peer policy changed since review')
            _idle(c)
            write_json(path,desired)
            return dict(status='protected',policy=desired,reused=False)
