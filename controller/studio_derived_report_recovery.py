"""Exact generated-report baseline reconciliation; never discard user edits.

Preparation is pure and has no native or filesystem effects. The transaction
must separately own the stopped editor and preserve before/after evidence.
"""
import copy
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath

from campaign_ledger import sha
from studio_bridge import write_json
from studio_build_upgrade import retain
from studio_handover import safe_path
from studio_installation import read_json, load_installation
from studio_native_gate import exclusive_gate
from studio_seed_process import WindowsSeedProcess
from studio_monitor_probe import inspect_idle_demo
from studio_rejected_monitor import proof, require_demo
from studio_driver_suspend import require_no_publishers
from studio_seed_slot import guard_active_seed
from studio_onboarding import verify_monitor_profile, saved_launch_policy


def corrected_draft(draft, *, terminal_id, run_id, ea_version, server, native_run, base_names=None):
    """base_names: generated-root folder names the retained baseline may use
    (this terminal's isolated folder, and the shared pre-isolation one)."""
    required = {'schema_version', 'terminal_id', 'run_id', 'revision', 'generation',
                'tester_ini', 'export_ini', 'baseline', 'submitted'}
    if (not isinstance(draft, dict) or set(draft) != required
            or draft['schema_version'] != 1 or draft['terminal_id'] != terminal_id
            or draft['run_id'] != run_id
            or any(type(draft[k]) is not int or draft[k] < 0 for k in ('revision', 'generation'))
            or any(not isinstance(draft[k], str) for k in ('tester_ini', 'export_ini', 'baseline', 'submitted'))
            or draft['submitted'] != ''):
        raise ValueError('Exact unsubmitted retained editor draft required')
    if (not re.fullmatch(r'GOAT\\R[0-9a-f]{12}', native_run)
            or not re.fullmatch(r'[0-9]+\.[0-9]+', ea_version)
            or not re.fullmatch(r'[A-Za-z0-9_. -]{1,80}', server) or server!=server.strip()):
        raise ValueError('Exact generated report namespace required')
    current = draft['tester_ini'] + draft['export_ini']
    baseline = draft['baseline']
    reports = []
    for text in (baseline, current):
        rows = list(re.finditer(r'(?m)^Report=([^\r\n]+)\n', text))
        if len(rows) != 1 or len(re.findall(r'(?im)^report\s*=', text)) != 1:
            raise ValueError('One complete generated Report row required')
        match = rows[0]
        if text.count('[Tester]\n') != 1 or text.count('[Export]\n') != 1 or not text.index('[Tester]\n') < match.start() < text.index('[Export]\n'):
            raise ValueError('Generated Report must belong to tester section')
        value = match.group(1)
        parts = PureWindowsPath(value).parts
        if (value != '\\'.join(parts) or not value.endswith('.xml')
                or any(p in ('.', '..') or ':' in p for p in parts)):
            raise ValueError('Generated report path is not canonical')
        reports.append((match, value, parts))
    old, new = reports
    from studio_terminal_isolation import legacy_base_name
    shared = legacy_base_name(ea_version, server)
    names = tuple(base_names) if base_names else (shared,)
    if any(not n.startswith(shared) for n in names):
        raise ValueError('Exact generated report namespace required')
    legacy = next((('MQL5', 'Files', 'GOAT', n) for n in names if old[2][:4] == ('MQL5', 'Files', 'GOAT', n)), ('MQL5', 'Files', 'GOAT', names[0]))
    scoped = ('MQL5', 'Files', *PureWindowsPath(native_run).parts, 'reports')
    if old[2][:len(legacy)] != legacy or new[2][:len(scoped)] != scoped or old[2][len(legacy):] != new[2][len(scoped):]:
        raise ValueError('Only the bound legacy-to-scoped generated root may change')
    replaced = baseline[:old[0].start(1)] + new[1] + baseline[old[0].end(1):]
    if replaced != current:
        raise ValueError('Actual user edits exist; generated-path repair refused')
    result = copy.deepcopy(draft)
    result['baseline'] = current
    return result


def _report_base_names(c):
    """This terminal's isolated folder first, then the shared pre-isolation one."""
    from studio_terminal_isolation import controller_base_name, legacy_base_name
    return (controller_base_name(c), legacy_base_name(c.install['ea_version'], c.session['account']['server']))


def permission_bytes(chart, common):
    """Exact encoded saved flag rows; never interpret opaque expertmode bits."""
    result = {}
    for name, raw in (('chart', chart), ('common', common)):
        encoding = 'utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
        text = raw.decode(encoding)
        if name == 'chart':
            rows=[]; stack=[]
            for line in text.splitlines(keepends=True):
                tag=re.fullmatch(r'<(/?)([a-z_][a-z0-9_]*)>',line.strip())
                if tag:
                    closing,kind=tag.groups()
                    if closing:
                        if not stack or stack[-1]!=kind: raise ValueError('Malformed saved chart permission scope')
                        stack.pop()
                    else: stack.append(kind)
                elif stack==['chart','expert'] and re.fullmatch(r'expertmode=[0-9]{1,3}',line.strip()): rows.append(line)
            if stack: raise ValueError('Unclosed saved chart permission scope')
            if len(rows) != 1: raise ValueError('Exactly one saved expert permission row required')
            selected = rows[0]
        else:
            sections = re.findall(r'(?im)^\[Experts\][^\r\n]*(?:\r\n|\n|\r)(.*?)(?=^\[|\Z)', text, re.S)
            if len(sections) != 1 or not re.search(r'(?m)^Enabled=0(?:\r?\n|\r|$)', sections[0]):
                raise ValueError('One saved Experts permission section with Algo OFF required')
            selected = sections[0]
        result[name] = selected.encode(encoding).hex()
    return result


def _hash(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def _no_human_pending(c):
    for name in ('inbox', 'processing'):
        folder = safe_path(c.bridge.root/'human'/name)
        if not folder.is_dir() or any(folder.iterdir()):
            raise ValueError('Pending human action must be processed before recovery')


def _profile(c, record=None, *, expected_chart_sha256=None):
    profile = read_json(c.root/'monitor-profile.json')
    folder = safe_path(Path(profile['profile_path']))
    charts = list(folder.glob('*.chr'))
    if len(charts) != 1: raise ValueError('Exactly one preserved inert monitor chart required')
    chart = safe_path(charts[0]); common = safe_path(Path(c.install['terminal_data_root'])/'config/common.ini')
    raw, config = chart.read_bytes(), common.read_bytes()
    flags = permission_bytes(raw, config)
    if record is not None and flags != record['permission_bytes']:
        raise ValueError('Saved permission bytes changed; no launch or recovery acknowledgement')
    if record is None and expected_chart_sha256!=hashlib.sha256(raw).hexdigest():
        raise ValueError('Prepare chart differs from the prior verified stopped chart')
    verify_monitor_profile(c, profile, preserved_permissions_sha256=expected_chart_sha256 if record is None else hashlib.sha256(raw).hexdigest())
    saved_launch_policy(c, c.session)
    return chart, common, raw, config, flags


def _guard(c, record, *, draft_hashes):
    scope, job = proof(c, record['job_id'],revoked_maintenance=record.get('revoked_maintenance',False))
    if sha(scope) != record['authority_sha256'] or sha(c.install) != record['installation_sha256'] or load_installation(c.root/'installation.json') != c.install:
        raise ValueError('Recovery authority or installed build changed')
    state = c.state()
    if {k:state[k] for k in ('owner','revision','generation')} != record['state']:
        raise ValueError('Controller session changed during recovery')
    guard_active_seed(c.root); require_no_publishers(c); _no_human_pending(c)
    for name in ('session.json', 'research-authority.json'):
        if _hash(c.root/name) != record['protected'][name]: raise ValueError('Protected session evidence changed')
    if draft_hashes is not None and _hash(c.bridge.root/'human/ui-draft.json') not in draft_hashes:
        raise ValueError('Retained editor draft changed outside this recovery')
    if _hash(Path(record['startup_config'])) != record['startup_sha256'] or _hash(Path(record['preset'])) != record['preset_sha256']:
        raise ValueError('Inert monitor startup inputs changed')
    _profile(c, record)
    return job


def _fresh(c, identity, *, aligned):
    native = inspect_idle_demo(c); require_demo(native)
    if native['process'] != identity: raise ValueError('Controller-owned monitor process identity changed')
    observation, runtime = c.runtime(require_idle=True, expected_batch_ongoing=False)
    created = datetime.fromisoformat(identity['created_utc'].replace('Z','+00:00')).timestamp()
    if runtime['modified'] < created or observation.get('pending_id'):
        raise ValueError('Fresh settled native monitor feedback required')
    if aligned and any(observation[k] != c.state()[k] for k in ('owner','revision','generation')):
        raise ValueError('Native editor has not synchronized the actual controller session')
    return observation, native


def recover(c, job_id, *, process=None, clock=time, revoked_maintenance=False):
    """One journaled close/CAS/relaunch, resuming known phases without retries."""
    from studio_human_reopen import retained
    process = process or WindowsSeedProcess(c)
    c.bridge.pump()
    with exclusive_gate(c.root/'batch-driver-gate'), exclusive_gate(c.local/'native-gate'):
        scope, job = proof(c, job_id,revoked_maintenance=revoked_maintenance)
        original_path = c.root/'rejected-monitor-restarts'/job['launch_intent']['attempt_id']/'restart.json'
        folder = safe_path(original_path.parent/'derived-report-recovery')
        journal = folder/'transaction.json'
        draft_path = c.bridge.root/'human/ui-draft.json'
        if not journal.exists():
            if folder.exists(): raise ValueError('Partial recovery preparation retained; inspect before proceeding')
            _, old = retained(c, job_id,revoked_maintenance=revoked_maintenance)
            current = process.inspect()
            if current is None: raise ValueError('Current idle selected monitor required for diagnosis')
            observation, native = _fresh(c, current, aligned=False)
            state = c.state(); draft = read_json(draft_path)
            expected_owner='human' if revoked_maintenance else 'agent'
            if (observation['owner'] != expected_owner or state['owner'] != expected_owner
                    or observation['revision'] != draft['revision'] or observation['generation'] != draft['generation']
                    or state['generation'] != draft['generation']+(1 if revoked_maintenance else 0) or state['revision'] <= draft['revision']
                    or observation['tester_ini'] + observation['export_ini'] != draft['tester_ini'] + draft['export_ini']):
                raise ValueError('Only the proven retained generated-report revision mismatch is recoverable')
            manifest = read_json(c.root/'packages'/job_id/'manifest.json')
            after = corrected_draft(draft, terminal_id=c.terminal, run_id=c.run, ea_version=c.install['ea_version'],
                                    server=c.session['account']['server'], native_run=manifest['native_run_relative'],
                                    base_names=_report_base_names(c))
            prior_profile=read_json(original_path.parent/'human-reopen.json')
            chart, common, chart_raw, common_raw, flags = _profile(c,expected_chart_sha256=prior_profile['chart_sha256'])
            preset = safe_path(Path(c.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
            expected_preset = 'Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
            profile = read_json(c.root/'monitor-profile.json')
            expected_config = ('[Charts]\r\nProfileLast='+profile['profile_name']+'\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n'
                               '[StartUp]\r\nExpert='+c.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+'\r\nPeriod=M1\r\n').encode('utf-16')
            config = safe_path(Path(old['launch']['startup_config']))
            if preset.read_bytes()!=expected_preset or config.read_bytes()!=expected_config or _hash(config)!=old['launch']['startup_sha256']:
                raise ValueError('Exact original inert monitor startup required')
            _no_human_pending(c)
            before_raw = draft_path.read_bytes(); after_raw = (json.dumps(after,ensure_ascii=False,allow_nan=False)+'\n').encode()
            record = dict(schema_version=1, job_id=job_id, attempt_id=job['launch_intent']['attempt_id'],
                          authority_sha256=sha(scope), installation_sha256=sha(c.install),
                          state={k:state[k] for k in ('owner','revision','generation')},
                          protected={n:_hash(c.root/n) for n in ('session.json','research-authority.json')},
                          before_sha256=hashlib.sha256(before_raw).hexdigest(), after_sha256=hashlib.sha256(after_raw).hexdigest(),
                          original_sha256=_hash(original_path), permission_bytes=flags,
                          startup_config=str(config), startup_sha256=_hash(config), preset=str(preset), preset_sha256=_hash(preset),
                          prior_process=current, phase='prepared', created_utc=clock.time(), grants_control=False, starts_research=False,
                          revoked_maintenance=revoked_maintenance)
            folder.mkdir()
            for name, raw in (('draft-before.json',before_raw),('draft-after.json',after_raw),('restart-before.json',original_path.read_bytes()),
                              ('chart-before.chr',chart_raw),('common-before.ini',common_raw)):
                retain(folder/name,raw)
            write_json(journal,record)
        record = read_json(journal)
        if record.get('revoked_maintenance',False)!=revoked_maintenance:raise ValueError('Recovery mode differs from retained transaction')
        if record.get('phase') not in ('prepared','close_issued','stopped','draft_repaired','launch_issued','started_unverified','verified_pending_publication','reverified'):
            raise ValueError('Unknown retained recovery phase; no effect authorized')
        if record['job_id'] != job_id or _hash(folder/'restart-before.json') != record['original_sha256']:
            raise ValueError('Original recovery linkage changed')
        before_hash, after_hash = record['before_sha256'], record['after_sha256']
        if _hash(folder/'draft-before.json') != before_hash or _hash(folder/'draft-after.json') != after_hash:
            raise ValueError('Draft transformation evidence changed')
        old = read_json(folder/'restart-before.json')
        manifest=read_json(c.root/'packages'/job_id/'manifest.json')
        recalculated=corrected_draft(read_json(folder/'draft-before.json'),terminal_id=c.terminal,run_id=c.run,
                                    ea_version=c.install['ea_version'],server=c.session['account']['server'],native_run=manifest['native_run_relative'],
                                    base_names=_report_base_names(c))
        if recalculated!=read_json(folder/'draft-after.json') or old['phase']!='stopped' or old['authority_sha256']!=sha(scope):
            raise ValueError('Retained baseline repair no longer matches the original proof')
        if permission_bytes((folder/'chart-before.chr').read_bytes(),(folder/'common-before.ini').read_bytes())!=record['permission_bytes']:
            raise ValueError('Archived permission evidence changed')
        if record['phase'] not in ('reverified','verified_pending_publication') and _hash(original_path) != record['original_sha256']:
            raise ValueError('Original recovery record changed before verified completion')
        if record['phase'] == 'prepared':
            _guard(c, record, draft_hashes={before_hash}); _fresh(c, record['prior_process'], aligned=False)
            record['phase']='close_issued'; write_json(journal,record)
            process.close(record['prior_process'])
        if record['phase'] == 'close_issued':
            deadline=clock.monotonic()+20
            while process.inspect() is not None:
                if process.inspect()!=record['prior_process']: raise ValueError('Unexpected monitor after close; no adoption')
                if clock.monotonic()>=deadline: raise ValueError('Close remains unconfirmed; no repeated close or force kill')
                clock.sleep(.2)
            record['phase']='stopped'; write_json(journal,record)
        if record['phase'] == 'stopped':
            if process.inspect() is not None: raise ValueError('Monitor reappeared before stopped draft repair')
            _guard(c,record,draft_hashes={before_hash,after_hash})
            if _hash(draft_path)==before_hash:
                # Editor is stopped. Reconcile only this archived byte transition.
                temporary=safe_path(draft_path.with_name('ui-draft.derived-report.tmp'))
                retain(temporary,(folder/'draft-after.json').read_bytes())
                os.replace(temporary,draft_path)
            record['phase']='draft_repaired'; write_json(journal,record)
        if record['phase'] == 'draft_repaired':
            if process.inspect() is not None: raise ValueError('Monitor reappeared before controller launch')
            _guard(c,record,draft_hashes={after_hash})
            record['phase']='launch_issued'; write_json(journal,record)
            record['process']=process.start(Path(record['startup_config']))
            record['phase']='started_unverified'; write_json(journal,record)
        if record['phase']=='launch_issued': raise ValueError('Launch result uncertain; never repeat or adopt an unrecorded PID')
        if record['phase'] in ('started_unverified','verified_pending_publication','reverified'):
            deadline=clock.monotonic()+30
            while True:
                _guard(c,record,draft_hashes=None)
                try:
                    observation,native=_fresh(c,record['process'],aligned=True)
                    break
                except ValueError:
                    if clock.monotonic()>=deadline: raise
                    clock.sleep(1)
            # Preserve all old evidence and link this explicit transformation.
            # No human-adoption witness or editor revision is manufactured.
            expected=dict(old,phase='reverified',process=record['process'],after=native,
                          controller_derived_report_recovery=dict(path=str(journal),before_sha256=before_hash,after_sha256=after_hash,
                                                                original_sha256=record['original_sha256']))
            if record['phase']=='started_unverified':
                record['phase']='verified_pending_publication'; record['after']=native
                record['expected_recovery']=expected; write_json(journal,record)
            expected=record['expected_recovery']
            if record['phase']=='reverified':
                if read_json(original_path)!=expected: raise ValueError('Verified controller recovery linkage changed')
                return record
            if _hash(original_path)==record['original_sha256']: write_json(original_path,expected)
            elif read_json(original_path)!=expected: raise ValueError('Recovery publication differs from retained transaction')
            record['phase']='reverified'; write_json(journal,record)
        return record


def verify_completed(c, record):
    link=record['controller_derived_report_recovery']
    expected=c.root/'rejected-monitor-restarts'/record['attempt_id']/'derived-report-recovery/transaction.json'
    if Path(link['path'])!=expected: raise ValueError('Recovery journal must belong to the exact original attempt')
    transaction=read_json(safe_path(expected))
    if transaction['phase']!='reverified' or transaction['expected_recovery']!=record:
        raise ValueError('Controller repair is not completely verified')
    folder=expected.parent
    if any(_hash(folder/name)!=transaction[key] for name,key in
           (('draft-before.json','before_sha256'),('draft-after.json','after_sha256'),('restart-before.json','original_sha256'))):
        raise ValueError('Original controller repair evidence changed')
    if permission_bytes((folder/'chart-before.chr').read_bytes(),(folder/'common-before.ini').read_bytes())!=transaction['permission_bytes']:
        raise ValueError('Archived permission evidence changed')
    _guard(c,transaction,draft_hashes=None)
    return _fresh(c,transaction['process'],aligned=True)[1]
