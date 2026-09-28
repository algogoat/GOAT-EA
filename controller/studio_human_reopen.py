"""Preserve a saved profile pointer and observe a human-reopened idle monitor.

No launch, close, trading, login, grant or permission modification is provided.
"""
import hashlib
import os
from datetime import datetime
from pathlib import Path
import time

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_handover import safe_path
from studio_native_gate import exclusive_gate
from studio_rejected_monitor import proof,require_demo
from studio_driver_suspend import require_no_publishers
from studio_seed_slot import guard_active_seed
from studio_seed_process import WindowsSeedProcess
from studio_monitor_probe import inspect_idle_demo
from studio_onboarding import saved_launch_policy,verify_monitor_profile


def retained(c,job_id):
    scope,job=proof(c,job_id)
    path=c.root/'rejected-monitor-restarts'/job['launch_intent']['attempt_id']/'restart.json'
    record=read_json(path)
    if record['phase']!='stopped' or record['authority_sha256']!=sha(scope) or record['job_id']!=job_id:
        raise ValueError('Only the original stopped and never-launched recovery may observe a human reopen')
    expected={str(p) for p in (c.root/'session.json',c.root/'research-authority.json',c.bridge.root/'human/ui-draft.json')}
    if set(record['protected_sha256'])!=expected:raise ValueError('Protected paths changed')
    for p,digest in record['protected_sha256'].items():
        if hashlib.sha256(safe_path(Path(p)).read_bytes()).hexdigest()!=digest:raise ValueError('Protected session/authority/draft changed')
    suspended=read_json(path.parent/'publisher-stopped.json')
    if (sha(suspended)!=record['suspension_sha256'] or suspended.get('supervisor_exited') is not True
            or hashlib.sha256((c.root/'batch-drivers'/(job_id+'.json')).read_bytes()).hexdigest()!=suspended['journal_sha256']):
        raise ValueError('Original publisher suspension changed')
    guard_active_seed(c.root);require_no_publishers(c)
    saved_launch_policy(c,c.session)
    return path,record


def prepare(c,job_id,*,process=None):
    process=process or WindowsSeedProcess(c)
    c.bridge.pump()
    with exclusive_gate(c.root/'batch-driver-gate'),exclusive_gate(c.local/'native-gate'):
        path,record=retained(c,job_id)
        if process.inspect() is not None:raise ValueError('Selected MT5 must remain stopped during pointer preparation')
        audit=path.parent/'human-reopen.json'
        if audit.exists():raise ValueError('Human reopen preparation already recorded; inspect retained evidence')
        profile=read_json(c.root/'monitor-profile.json')
        # Validate identity/monitor inputs without treating opaque saved bits as
        # permission to launch. This operation never launches anything.
        folder=verify_monitor_profile(c,profile,observed_human_reopen=True)
        chart=next(p for p in folder.iterdir() if p.suffix.lower()=='.chr')
        common=safe_path(Path(c.install['terminal_data_root'])/'config/common.ini')
        before=common.read_bytes();encoding='utf-16' if before.startswith(b'\xff\xfe') else 'utf-8-sig' if before.startswith(b'\xef\xbb\xbf') else 'utf-8'
        lines=before.decode(encoding).splitlines(keepends=True);section='';indices=[]
        for index,line in enumerate(lines):
            stripped=line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):section=stripped[1:-1].casefold()
            elif section=='charts' and stripped.partition('=')[0].casefold()=='profilelast':indices.append(index)
        if len(indices)!=1:raise ValueError('Exactly one saved Charts/ProfileLast required')
        index=indices[0];line=lines[index];prefix,sep,value=line.partition('=')
        ending='\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
        lines[index]=prefix+sep+profile['profile_name']+ending
        after=''.join(lines).encode(encoding)
        # Only this single value changes; all permission/account bytes remain.
        for name,raw in (('common-before.ini',before),('common-after.ini',after)):
            with (path.parent/name).open('xb') as stream:stream.write(raw)
        receipt=dict(schema_version=1,phase='pointer_prepared',job_id=job_id,created_utc=time.time(),
            restart_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),profile_name=profile['profile_name'],
            chart_path=str(chart),chart_sha256=hashlib.sha256(chart.read_bytes()).hexdigest(),
            common_path=str(common),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest(),
            launch_issued=False,permissions_changed=False,human_reopened=False)
        write_json(audit,receipt)
        if process.inspect() is not None or common.read_bytes()!=before:raise ValueError('Terminal/config changed before profile pointer publication')
        temporary=common.with_name('common.ini.'+job_id+'.tmp')
        with temporary.open('xb') as stream:stream.write(after);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,common)
        return receipt


def adopt(c,job_id,*,human_reopened=False,process=None):
    if human_reopened is not True:raise ValueError('Actual human reopen confirmation required; never infer it from a process')
    process=process or WindowsSeedProcess(c)
    c.bridge.pump()
    with exclusive_gate(c.root/'batch-driver-gate'),exclusive_gate(c.local/'native-gate'):
        path,record=retained(c,job_id)
        receipt=read_json(path.parent/'human-reopen.json')
        if receipt['restart_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest() or receipt['job_id']!=job_id:
            raise ValueError('Human reopen preparation no longer matches stopped record')
        common=safe_path(Path(c.install['terminal_data_root'])/'config/common.ini')
        if receipt['common_path']!=str(common) or hashlib.sha256(common.read_bytes()).hexdigest()!=receipt['after_sha256']:
            raise ValueError('Saved configuration changed after profile pointer preparation')
        profile=read_json(c.root/'monitor-profile.json')
        folder=verify_monitor_profile(c,profile,observed_human_reopen=True)
        chart=next(p for p in folder.iterdir() if p.suffix.lower()=='.chr')
        if str(chart)!=receipt['chart_path'] or hashlib.sha256(chart.read_bytes()).hexdigest()!=receipt['chart_sha256']:
            raise ValueError('Saved monitor chart changed after human reopen preparation')
        current=process.inspect()
        created=datetime.fromisoformat(current['created_utc'].replace('Z','+00:00')).timestamp() if current else 0
        if current is None or not receipt['created_utc']<created<=time.time():
            raise ValueError('Exact terminal must have been opened after the recorded stopped preparation')
        native=inspect_idle_demo(c);require_demo(native)
        if native['process']!=current:raise ValueError('Human-reopened process changed during verification')
        observation,_=c.runtime(require_idle=True,expected_batch_ongoing=False)
        state=c.state()
        if any(observation[k]!=state[k] for k in ('owner','revision','generation')):
            raise ValueError('Current native monitor has not confirmed this exact typed session')
        # Durable adoption precedes re-verification; never write a launch claim.
        record.update(phase='adopted_unverified',process=current,human_reopened=True,
                      human_reopen_sha256=sha(receipt),adopted_utc=time.time(),after=native)
        write_json(path,record)
        after=verify_adopted(c,record,path)
        record.update(phase='reverified',after=after);write_json(path,record)
        return record


def verify_adopted(c,record,path):
    """Reconcile a recorded observation, without ever adopting a second PID."""
    receipt=read_json(path.parent/'human-reopen.json')
    if record.get('human_reopened') is not True or sha(receipt)!=record.get('human_reopen_sha256'):
        raise ValueError('Exact retained human-reopen observation required')
    guard_active_seed(c.root);require_no_publishers(c);saved_launch_policy(c,c.session)
    for p,digest in record['protected_sha256'].items():
        if hashlib.sha256(safe_path(Path(p)).read_bytes()).hexdigest()!=digest:raise ValueError('Protected evidence changed after adoption')
    common=safe_path(Path(c.install['terminal_data_root'])/'config/common.ini')
    if str(common)!=receipt['common_path'] or hashlib.sha256(common.read_bytes()).hexdigest()!=receipt['after_sha256']:
        raise ValueError('Configuration changed after adoption')
    folder=verify_monitor_profile(c,read_json(c.root/'monitor-profile.json'),observed_human_reopen=True)
    chart=next(p for p in folder.iterdir() if p.suffix.lower()=='.chr')
    if str(chart)!=receipt['chart_path'] or hashlib.sha256(chart.read_bytes()).hexdigest()!=receipt['chart_sha256']:
        raise ValueError('Chart changed after adoption')
    native=inspect_idle_demo(c);require_demo(native)
    if native['process']!=record['process']:raise ValueError('Adopted process changed; no second adoption')
    observation,_=c.runtime(require_idle=True,expected_batch_ongoing=False)
    state=c.state()
    if any(observation[k]!=state[k] for k in ('owner','revision','generation')):raise ValueError('Native session changed after adoption')
    return native
