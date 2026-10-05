"""Reviewed protection of one existing peer; never ignore unknown terminals.

This file's policy.json holds one reviewed peer and is never converted: it is
bound into every prepared package. Further GOAT-owned terminals (peer-add and
GOAT installation receipts) live in studio_peer_roster, outside every binding.

The policy lives outside both switched directories. It records the peer's
executable, data root and origin binding (and the process instance seen at
review), not permission to manage it. A different peer, binary or data root
requires a new review.

Peer restarts (studio_process_check.restart_tolerant): when this lane runs an
isolated EA whose batch namespace cannot be the peer's, a restarted, closed or
reopened peer whose executable, data root and origin are unchanged is the same
reviewed peer. It is accepted without a new review and each new instance is
recorded append-only in ``peer-instances.jsonl`` (old and new PID). The policy
itself is never rewritten for a restart, and package bindings then carry the
peer's identity (``protected_peer_sha256``), not a PID, so a peer restart never
invalidates a prepared package. Without that isolation proof the historical
exact-instance rule applies unchanged.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
from studio_subprocess import background_creationflags
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
    rows=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command], text=True,encoding='utf-8-sig',timeout=20, creationflags=background_creationflags()))
    if not isinstance(rows,list): raise ValueError('Complete terminal inventory required')
    count=sum(PureWindowsPath(r.get('ExecutablePath') or '')==PureWindowsPath(c.install['terminal_executable']) for r in rows)
    if count not in (0,1): raise ValueError('Ambiguous selected terminal process')
    # A closed peer is observed as None, never as an error: every package binding
    # already lets the peer be stopped. Unknown terminals and a second process of
    # the peer still refuse in classify_processes. Other GOAT-owned terminals
    # (studio_peer_roster: peer-add and GOAT receipts) are exempt here too, so a
    # second GOAT terminal never blocks a refresh of this reviewed peer.
    from studio_peer_roster import lookup_for_controller
    result=classify_processes(rows,dict(research_terminal=c.install['terminal_executable'],protected_terminal=peer['executable'],
                                        protected_may_be_stopped=True),
                             observed_unix=time.time(),research_running=bool(count),
                             peer_lookup=lookup_for_controller(c))
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


PEER_BINDING_KEYS=frozenset(('protected_terminal','protected_data_roots','protected_process',
                             'protected_policy_sha256','protected_may_be_stopped','protected_peer_sha256'))
JOURNAL='peer-instances.jsonl'
RESTART_RULE='same_executable_data_root_origin_isolated_namespace_v1'


def _lane(c):
    """The binding fields restart_tolerant reads about this research lane."""
    return dict(research_data_root=c.install['terminal_data_root'],ea_version=c.install['ea_version'])


def tolerant(c, value):
    from studio_process_check import restart_tolerant
    return restart_tolerant(dict(_lane(c),protected_terminal=value['peer']['executable'],
                                 protected_data_roots=[value['peer']['data_root']],protected_may_be_stopped=True))


def binding_fields(c):
    value=policy(c)
    if value is None: return {}
    fields=dict(protected_terminal=value['peer']['executable'],protected_data_roots=[value['peer']['data_root']],
                protected_may_be_stopped=True)
    if tolerant(c,value):
        # Identity only: executable, data root, executable bytes and origin binding.
        return fields|dict(protected_peer_sha256=sha(value['peer']))
    return fields|dict(protected_process=value['process'],protected_policy_sha256=sha(value))


def _journal_instances(folder):
    path=folder/JOURNAL
    if not path.is_file(): return []
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row=json.loads(line)
        except ValueError:
            continue  # A torn final line from an interrupted append records nothing.
        if isinstance(row,dict) and isinstance(row.get('process'),dict):
            rows.append(row)
    return rows


def last_instance(c, value=None):
    """The peer instance last accepted: the newest journal line, else the reviewed one."""
    value=value or policy(c)
    rows=[row for row in _journal_instances(directory(c)) if row.get('review_id')==value['review_id']]
    return rows[-1]['process'] if rows else value['process']


def accept_instance(c, value, current, *, source):
    """Record a restarted instance of the reviewed peer, append-only. Never rewrites the policy."""
    if current is None:
        return dict(status='peer_closed',process=None,last_process=last_instance(c,value),
                    plain='The protected peer MT5 is closed; that never blocks this terminal.')
    if PureWindowsPath(current.get('executable',''))!=PureWindowsPath(value['peer']['executable']):
        raise ValueError('Protected peer executable changed; review the peer again')
    folder=directory(c)
    with exclusive_gate(folder):
        previous=last_instance(c,value)
        if current==previous:
            return dict(status='unchanged',process=current)
        line=dict(schema_version=1,event='peer_restart_accepted',rule=RESTART_RULE,
                  recorded_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  review_id=value['review_id'],peer_sha256=sha(value['peer']),
                  executable=value['peer']['executable'],data_root=value['peer']['data_root'],
                  previous_pid=previous.get('pid'),pid=current['pid'],previous_process=previous,process=current,
                  source=source)
        with (folder/JOURNAL).open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(line,sort_keys=True)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        return dict(status='restart_accepted',previous_process=previous,process=current,
                    journal=str(folder/JOURNAL),rule=RESTART_RULE)


def record_observed(c, binding, observed, *, source):
    """Journal a restarted peer seen by a start's own process check (tolerant bindings only)."""
    from studio_process_check import restart_tolerant
    if observed is None or not restart_tolerant(binding):
        return None
    value=policy(c)
    if value is None or not tolerant(c,value):
        return None
    return accept_instance(c,value,observed,source=source)


def refresh_process(c):
    """Accept the already reviewed peer after its process restarted, closed or reopened.

    The executable bytes, data root and origin binding must equal the policy the
    user reviewed (policy() re-proves them); anything else (a different peer,
    binary or data root) still needs an explicit human review. A closed peer is
    reported, never refused. When the lanes keep separate batch state
    (restart_tolerant) a new instance is recorded append-only and the policy and
    every package binding stay unchanged. Otherwise the exact instance is
    re-reviewed as before: called by the broker-verified demo agent between
    batches; never grants or manages the peer and never runs while a native
    attempt is unresolved.
    """
    value=policy(c)
    if value is None:
        return dict(status='no_protected_peer')
    current=observe(c,value['peer'])
    if tolerant(c,value):
        return accept_instance(c,value,current,source='refresh_process')
    if current is None:
        return dict(status='peer_closed',process=None,reviewed_process=value['process'],
                    plain='The protected peer MT5 is closed; that never blocks this terminal.')
    if current==value['process']:
        return dict(status='unchanged',process=value['process'])
    review=prepare(c,value['peer']['executable'],value['peer']['data_root'])
    if review['peer']!=value['peer'] or review['process']!=current:
        raise ValueError('Protected peer executable, data root or process changed during review; review it explicitly')
    applied=apply(c,review['review_id'],True)
    return dict(status='refreshed',previous_process=value['process'],process=applied['policy']['process'],
                review_id=review['review_id'])


def _reviewed_policies(c):
    """Every policy this folder ever applied: the current one and each retained review."""
    folder=directory(c)
    for path in sorted(folder.glob('*.json')):
        try:
            value=read_json(path)
        except (OSError,ValueError):
            continue
        if not isinstance(value,dict): continue
        candidate={key:value.get(key) for key in ('schema_version','review_id','target','peer','process')}
        if candidate['target']==target(c) and isinstance(candidate['peer'],dict):
            yield candidate


def _peer_identity(c, binding):
    """(terminal, data roots, peer material hash) a binding names, or None when unprovable."""
    terminal,roots=binding.get('protected_terminal'),binding.get('protected_data_roots')
    if binding.get('protected_peer_sha256'):
        return (terminal,roots,binding['protected_peer_sha256'])
    recorded=binding.get('protected_policy_sha256')
    if not recorded: return None
    # A package prepared under the exact-instance rule records the whole policy hash.
    # It names this peer only when a retained reviewed policy has that exact hash.
    for candidate in _reviewed_policies(c):
        if (sha(candidate)==recorded and candidate['process']==binding.get('protected_process')
                and candidate['peer'].get('executable')==terminal and [candidate['peer'].get('data_root')]==roots):
            return (terminal,roots,sha(candidate['peer']))
    return None


def comparable(c, recorded, current):
    """A package's recorded binding and the current one, with the peer reduced to its identity.

    Only when both are restart tolerant and name the same reviewed executable,
    data root and peer bytes. Every other field still compares exactly; any other
    pair is returned unchanged, so it compares exactly too.
    """
    from studio_process_check import restart_tolerant
    if recorded==current or not (restart_tolerant(recorded) and restart_tolerant(current)):
        return recorded,current
    if recorded.get('protected_may_be_stopped') is not True or current.get('protected_may_be_stopped') is not True:
        return recorded,current
    mine,theirs=_peer_identity(c,recorded),_peer_identity(c,current)
    if mine is None or mine!=theirs:
        return recorded,current
    def strip(binding):
        return {key:value for key,value in binding.items() if key not in PEER_BINDING_KEYS}|dict(protected_peer_identity=list(mine))
    return strip(recorded),strip(current)


def process_binding(c):
    return dict(research_terminal=c.install['terminal_executable'],**_lane(c),**binding_fields(c))


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
            if process is None:
                raise ValueError('Open the peer MT5 normally, then review it again; a closed peer cannot be reviewed')
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
