"""Reviewed V1.49 orphan-flag recovery. Never launches or invents native ownership."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from campaign_ledger import sha
from studio_bridge import display_state, write_json
from studio_dispatch_observe import observe_dispatch
from studio_handover import paths, safe_path, guard
from studio_installation import read_json, load_installation
from studio_native_gate import exclusive_gate
from studio_process_check import inspect_processes
from studio_seed_slot import guard_active_seed

CONTROLS = ('active_optimization_run.ini','active_optimization_config.ini',
            'active_optimization_launch.ini','agent-native-control-owner.json')
SETTLED = {'pending','completed','failed','cancelled','removed','superseded'}


@contextmanager
def recovery_lock(c):
    lock = paths(c)[3]; lock.mkdir(parents=True, exist_ok=True)
    with exclusive_gate(lock):
        opened=c.store is None
        try:
            if opened: c.open(recovery=True)
            yield
        finally:
            if opened and c.store is not None: c.store.close(); c.store=None


def digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def inspect_writers(c):
    command = 'ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine)'
    rows = json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command],
                     text=True, encoding='utf-8-sig', timeout=20))
    if not isinstance(rows,list): raise ValueError('Complete writer inventory required')
    by_id = {r['ProcessId']:r for r in rows}
    if os.getpid() not in by_id or len(by_id)!=len(rows): raise ValueError('Incomplete writer inventory')
    ancestors=set(); pid=os.getpid()
    while pid in by_id and pid not in ancestors:
        ancestors.add(pid); pid=by_id[pid]['ParentProcessId']
    for row in rows:
        if row['ProcessId'] in ancestors: continue
        name=str(row.get('Name','')).lower(); command_line=str(row.get('CommandLine') or '').lower()
        if name.startswith(('python','goat')) or name in ('powershell.exe','pwsh.exe'):
            if not row.get('ExecutablePath') or not command_line:
                raise ValueError('Writer identity unavailable; inspect elevated/other-session processes')
            if name=='goat.exe' or 'studio' in command_line or str(c.root).lower() in command_line or str(c.local).lower() in command_line:
                raise ValueError('Stop other controller/runner processes before orphan review')


def inspect_local(c, *, allow_own_request=None):
    """Caller holds the native gate as well as the exclusive session hold."""
    if c.install['ea_version']!='1.49': raise ValueError('Orphan recovery requires the compatible V1.49 monitor; do not reset a legacy EA')
    # Rehash installed bytes on every boundary, not only at CLI construction.
    if load_installation(c.root/'installation.json')!=c.install: raise ValueError('Installation changed')
    safe_path(c.root); safe_path(c.local)
    state=c.state()
    if state['owner']!='agent': raise ValueError('Existing explicit Give to Agent required; recovery never grants control')
    if c.store.db.execute('SELECT COUNT(*) FROM studio_state').fetchone()[0]!=1:
        raise ValueError('Multiple controller bindings require separate native ownership reconciliation')
    queues=list(c.store.db.execute('SELECT jobs FROM studio_queues'))
    if len(queues)>1: raise ValueError('Unknown queue binding requires reconciliation')
    for row in queues:
        if any(j.get('status') not in SETTLED or (j['status']=='pending' and 'launch_intent' in j) for j in json.loads(row[0])):
            raise ValueError('Unresolved native attempt; use its owned status/cancel/finish')
    guard_active_seed(c.root)
    gate=c.local/'native-gate'
    owners=[]
    for entry in c.local.rglob('*'):
        safe_path(entry)
        name=entry.name.lower()
        if name=='controller.json': owners.append(entry)
        if entry.is_file() and (name in ('pending.json','seed-active.json') or
                (name in ('request.json','permit.json') and entry.parent!=gate)):
            raise ValueError('Foreign or pending controller evidence requires reconciliation')
    if owners!=[gate/'controller.json'] or read_json(owners[0])!={'database':str(c.root/'studio.sqlite')}:
        raise ValueError('Legacy/foreign native gate is not attestable; reviewed migration required')
    gates=list(c.store.db.execute('SELECT root FROM studio_native_gate'))
    if len(gates)!=1 or safe_path(gates[0][0])!=gate: raise ValueError('Selected native gate changed')
    if allow_own_request:
        for name in ('request.json','permit.json'):
            expected=allow_own_request['request'] if name=='request.json' else {'request_sha256':allow_own_request['request_sha256']}
            if (gate/name).exists() and read_json(gate/name)!=expected: raise ValueError('Native recovery controls changed')
        prior_control=allow_own_request['prior_control']
    else:
        from studio_native_gate import assert_clear_controls
        prior_control=assert_clear_controls(c.store.db,gate)
    common=safe_path(Path(c.install['common_files_root'])/'GOAT')
    if not common.is_dir(): raise ValueError('GOAT Common Files inventory unavailable')
    for folder in common.iterdir():
        safe_path(folder)
        if folder.name.lower().startswith('goat v'):
            for name in CONTROLS:
                if (folder/name).exists(): raise ValueError('Native controls exist for a current or legacy EA version')
    inspect_writers(c)
    active=read_json(c.local/'active.json')
    expected=dict(directory_id=c.session['directory_id'],terminal_id=c.terminal,run_id=c.run,
                  terminal_data_path=c.install['terminal_data_root'])
    if active!=expected: raise ValueError('Active binding changed')
    return dict(installation_sha256=sha(c.install),state_sha256=sha(state),revision=state['revision'],generation=state['generation'],
                active_sha256=digest(c.local/'active.json'),
                owner_file_sha256=digest(gate/'controller.json'),binding_sha256=digest(c.bridge.root/'binding.json'),prior_control=prior_control)


def inspect(c, *, expected_batch=True, allow_own_request=None):
    local=inspect_local(c,allow_own_request=allow_own_request)
    process=inspect_processes(c.binding())['research']
    observation,_=c.runtime(require_idle=True,expected_batch_ongoing=expected_batch)
    cap=observation.get('recovery_capability',{})
    if (cap.get('protocol')!=1 or cap.get('ea_version')!='1.49' or cap.get('terminal_running') is not False
            or not isinstance(cap.get('monitor_instance'),str) or not cap['monitor_instance']):
        raise ValueError('Running monitor lacks the exact orphan-recovery capability or has a terminal-running flag')
    # Preserve the running path's final binding/owner reads after native probing.
    active=read_json(c.local/'active.json')
    expected=dict(directory_id=c.session['directory_id'],terminal_id=c.terminal,run_id=c.run,
                  terminal_data_path=c.install['terminal_data_root'])
    if active!=expected: raise ValueError('Active binding changed')
    local.update(active_sha256=digest(c.local/'active.json'),
                 owner_file_sha256=digest(c.local/'native-gate/controller.json'),
                 binding_sha256=digest(c.bridge.root/'binding.json'))
    return local | dict(process=process,monitor_instance=cap['monitor_instance'])


def plan_path(c, review_id):
    if not isinstance(review_id,str) or not re.fullmatch('[a-f0-9]{32}',review_id): raise ValueError('Retained recovery review ID required')
    return safe_path(c.root/'orphan-recovery'/review_id/'review.json')


def prepare(c):
    with recovery_lock(c):
        guard(c)
        with exclusive_gate(c.local/'native-gate'): observed=inspect(c)
        review_id=uuid.uuid4().hex
        plan=dict(schema_version=1,review_id=review_id,status='review',expires_at=time.time()+600,observation=observed)
        path=plan_path(c,review_id); path.parent.mkdir(parents=True,exist_ok=False)
        write_json(path,plan)
        return dict(review_id=review_id,status='review',expires_at=plan['expires_at'],effect='Clear only orphan BatchOnGoing inside MT5; preserve all jobs, files and grants',
                    pending_count=sum(j['status']=='pending' for j in c.state()['queue']),launch_permitted=False,
                    next_action='Explain the exact review and obtain explicit user approval; apply never starts the next batch')


def apply(c,review_id,*,confirmed=False,owner_research=False):
    from studio_research_authority import refuse_typed_confirmation
    refuse_typed_confirmation(c,confirmed)
    if type(owner_research) is not bool or (confirmed and owner_research):
        raise ValueError('Choose one explicit recovery authorization route')
    if not confirmed and not owner_research: raise ValueError('Explicit user approval of this recovery review required')
    with recovery_lock(c):
        path=plan_path(c,review_id); plan=read_json(path)
        if plan['status']!='review': return status_locked(c,plan)
        guard(c)
        if time.time()>plan['expires_at']: raise ValueError('Recovery review expired; prepare a new review')
        gate=c.local/'native-gate'
        with exclusive_gate(gate):
            if inspect(c)!=plan['observation']: raise ValueError('Recovery evidence changed before publication')
            if owner_research:
                from studio_owner_research import authorize,record as record_authorization
                record_authorization(c,authorize(c,'orphan-recovery-apply',review_id))
            # The EA accepts at most 60 seconds from its own TimeGMT. Leave
            # margin for clock differences and the five-second feedback cadence.
            # This is a publication check, not part of the frozen review identity.
            observation,clock=c.runtime(require_idle=True,expected_batch_ongoing=True)
            try:
                stamp=datetime.strptime(observation['observed_terminal_utc'],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
                modified=clock['modified']
            except (KeyError,TypeError,ValueError) as error:
                raise ValueError('Recovery needs a valid terminal UTC observation and file write time; no request published') from error
            # Compare clocks at publication of the observation, not its later read.
            # c.runtime separately enforces the existing 20-second freshness gate.
            if type(modified) not in (int,float) or not abs(stamp-modified)<=5:
                raise ValueError('Terminal UTC differs from its Windows file write time by more than 5 seconds or the write time is invalid. Check clock synchronization; no recovery request published')
            expires_utc=int(time.time())+45
            state=c.state()
            write_json(c.bridge.root/'snapshot.json',dict(protocol_version=1,state=display_state(state),schema_hash=c.store.input_schema_hash,execution_ready=False))
            request_id=sha(['orphan-recovery',review_id,plan['observation']])
            request=dict(schema_version=1,recovery_protocol=1,action='recover_orphan_continuation',request_id=request_id,
                terminal_id=c.terminal,run_id=c.run,owner='agent',revision=state['revision'],generation=state['generation'],
                expires_utc=expires_utc,ea_version=c.install['ea_version'],monitor_instance=plan['observation']['monitor_instance'],
                data_path=c.install['terminal_data_root'],installation_path=str(Path(c.install['terminal_executable']).parent),
                program_path=str(c.native_args()['monitor_path'].resolve()),account_login=c.session['account']['login'],account_server=c.session['account']['server'],
                snapshot_sha256=digest(c.bridge.root/'snapshot.json'),owner_file_sha256=plan['observation']['owner_file_sha256'],active_sha256=plan['observation']['active_sha256'])
            request_hash=hashlib.sha256((json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n').encode()).hexdigest()
            record=dict(request=request,request_sha256=request_hash,prior_control=plan['observation']['prior_control'])
            # Fence and intent precede publication. Interrupted/uncertain issuance
            # is only inspected; the same request is never automatically resent.
            write_json(c.root/'orphan-recovery-pending.json',dict(review_id=review_id))
            plan.update(status='issued',record=record,
                        prior_request_utf8=(gate/'request.json').read_bytes().decode('utf-8') if (gate/'request.json').exists() else None)
            write_json(path,plan)
            write_json(gate/('issued-'+request_id+'.json'),record)
            write_json(gate/'request.json',request)
            write_json(gate/'permit.json',dict(request_sha256=request_hash))
        return dict(status='published_not_recovered',review_id=review_id,request_id=request_id,
                    launch_permitted=False,next_action='Run orphan-recovery-status for the exact native receipt and fresh readback; do not resend')


def status(c,review_id):
    with recovery_lock(c): return status_locked(c,read_json(plan_path(c,review_id)))


def status_locked(c,plan):
    if plan['status']=='review': return dict(status='review',review_id=plan['review_id'],launch_permitted=False)
    if plan['status']=='rejected_settled':
        from studio_orphan_rejection import settled_status
        return settled_status(c,plan)
    if plan['status']=='recovered':
        fence=c.root/'orphan-recovery-pending.json'
        if fence.exists():
            if read_json(fence)!={'review_id':plan['review_id']}: raise ValueError('Another recovery fence exists')
            fence.unlink() # Recovery receipt was durable before fence cleanup.
        return dict(status='recovered',review_id=plan['review_id'],launch_permitted=False,reused=True)
    record=plan['record']; request=record['request']; gate=c.local/'native-gate'
    evidence=observe_dispatch(gate,request['request_id'])
    if evidence['status']!='receipt_observed' or evidence['receipt']['status']!='ORPHAN_RECOVERED' or not evidence.get('consumed'):
        return dict(status='reconcile_required',review_id=plan['review_id'],evidence=evidence,launch_permitted=False,
                    next_action='Preserve exact recovery evidence; no automatic resend or launch. Missing/negative native result requires reviewed reconciliation')
    with exclusive_gate(gate):
        if observe_dispatch(gate,request['request_id'])!=evidence: raise ValueError('Native recovery receipt changed')
        current=inspect(c,expected_batch=False,allow_own_request=record)
        if current!=plan['observation']: raise ValueError('Recovery readback identity/state changed; preserve fence and receipts')
        # Recheck everything including exact request/permit before removing only
        # our transport files. Results and all research remain retained.
        if inspect(c,expected_batch=False,allow_own_request=record)!=current: raise ValueError('Recovery readback changed')
        fence=c.root/'orphan-recovery-pending.json'
        if read_json(fence)!={'review_id':plan['review_id']}: raise ValueError('Recovery fence changed')
        (gate/'permit.json').unlink(missing_ok=True); (gate/'request.json').unlink(missing_ok=True)
        plan.update(status='recovered',readback=current,native_evidence=evidence)
        write_json(plan_path(c,plan['review_id']),plan)
        fence.unlink()
    return dict(status='recovered',review_id=plan['review_id'],launch_permitted=False,
                next_action='Orphan flag cleared and read back; prepare and explicitly start future work separately')
