"""Inspected retirement of a failed legacy passive monitor startup.

This deliberately cannot retire a research job or manufacture a stable CPU
allocation. It retains the original startup issuance, normal-close intent and
kernel exit evidence, then releases the exact claim and startup slot in ONE
registry transaction. No automatic close retry, restart or flag edits.
"""
from contextlib import ExitStack, closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import time
import uuid

from campaign_ledger import packed, sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate, assert_clear_controls
from studio_process_check import inspect_processes
from studio_process_exit import prove_exited
from studio_runtime_check import check_runtime
from studio_seed_process import WindowsSeedProcess


def safe(path):
    from studio_handover import safe_path
    return safe_path(path)


def file_evidence(path):
    path = safe(path)
    if not path.is_file() or path.stat().st_size > 64*1024*1024:
        raise ValueError('Missing or oversized bootstrap evidence')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(path), sha256=digest)


def folder(c):
    from studio_handover import paths
    return paths(c)[2]/'bootstrap-retirement'


def registry_state(db, scope, attempt):
    worker = db.execute('SELECT configuration FROM workers WHERE scope=?', (scope,)).fetchone()
    claim = db.execute('SELECT claim,released,release_evidence FROM attempts WHERE scope=? AND attempt=?', (scope, attempt)).fetchone()
    slot = db.execute('SELECT scope,attempt,acquired_unix FROM startup_slot WHERE id=1').fetchone()
    if not worker or not claim:
        raise ValueError('Retained registered worker and original attempt required')
    return dict(worker=json.loads(worker[0]), host=json.loads(claim[0]), released=claim[1],
                release_evidence=claim[2], slot=list(slot) if slot else None)


def verify_issuance(c, spec_path, bootstrap):
    spec_path, bootstrap = safe(spec_path), safe(bootstrap)
    spec = read_json(spec_path); b = spec['binding']; scope = spec['terminal_id']
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,31}', scope) or b['native_control_scope'] != scope:
        raise ValueError('Explicit scoped passive monitor binding required')
    for old, new in [('research_terminal','terminal_executable'), ('research_data_root','terminal_data_root'), ('common_files_root','common_files_root')]:
        if safe(b[old]) != safe(c.install[new]):
            raise ValueError('Bootstrap belongs to another installation')
    if b.get('live_trading_allowed') is not False or b.get('account_confirmation_pending') is not False:
        raise ValueError('Confirmed demo-only research binding required')
    paths = [spec_path, *(bootstrap/name for name in ('host-issued.json','startup-issued.json','startup-receipt.json'))]
    evidence = [file_evidence(p) for p in paths]
    host, issued, receipt = [read_json(p) for p in paths[1:]]
    attempt = host['attempt']
    if not isinstance(attempt, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', attempt):
        raise ValueError('Invalid original startup attempt')
    config = safe(issued['config'])
    if (host['configuration'] != issued or receipt['native_receipt']['config'] != str(config)
            or receipt['native_receipt']['config_sha256'].lower() != issued['config_sha256']
            or file_evidence(config)['sha256'] != issued['config_sha256']
            or not config.is_relative_to(safe(b['research_data_root'])/'config')
            or receipt.get('tester_started_verified') is not False
            or host['before'].get('research') is not None
            or receipt['native_receipt'].get('launched') is not True
            or PureWindowsPath(receipt['process']['executable']) != PureWindowsPath(b['research_terminal'])):
        raise ValueError('Original monitor startup issuance differs')
    # A configuration with [Tester] is a research launch, not a passive monitor.
    import configparser
    parser = configparser.ConfigParser(interpolation=None, strict=True); parser.optionxform = str
    raw = config.read_bytes()
    parser.read_string(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    monitor = b['startup_monitor']
    if (parser.defaults() or set(parser.sections()) != {'Charts','Experts','StartUp'}
            or set(parser['Charts'])!={'ProfileLast'} or set(parser['StartUp'])!={'Expert','ExpertParameters','Symbol','Period'}
            or dict(parser['Experts']) != {'Enabled':'0','AllowLiveTrading':'0'}
            or parser['StartUp'].get('Expert') != monitor['expert']
            or parser['StartUp'].get('ExpertParameters') != monitor['preset']):
        raise ValueError('Passive Algo-off monitor startup configuration required')
    preset = safe(b['research_data_root'])/'MQL5/Presets'/monitor['preset']
    if not safe(preset).is_relative_to(safe(b['research_data_root'])/'MQL5/Presets'):
        raise ValueError('Monitor preset escapes selected terminal')
    from studio_strategy_settings import read_values
    values = read_values(preset.read_bytes())
    if (file_evidence(preset)['sha256'] != monitor['preset_sha256'] or values.get('Mode_Operation') != '11'
            or values.get('Studio_ReadOnlyMonitor') != 'true'):
        raise ValueError('Original preset is not an unchanged inert monitor')
    monitor_path = safe(spec['monitor_path'])
    if (not monitor_path.is_relative_to(safe(b['research_data_root'])/'MQL5/Experts')
            or PureWindowsPath(monitor_path)!=PureWindowsPath(b['research_data_root'])/'MQL5/Experts'/monitor['expert']
            or file_evidence(monitor_path)['sha256'] != spec['monitor_sha256']):
        raise ValueError('Original monitor artifact changed')
    profile=parser['Charts']['ProfileLast']
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',profile): raise ValueError('Simple monitor profile name required')
    registry = safe(b['concurrent_worker_registry'])
    with closing(sqlite3.connect(registry.as_uri()+'?mode=ro', uri=True)) as db:
        state = registry_state(db, scope, attempt)
    expected = {'terminal':b['research_terminal'], 'data_root':b['research_data_root'],
                'controller':b['controller_database'], 'bridge':b['bridge_root'], 'common_root':b['common_files_root']}
    if any(PureWindowsPath(state['worker'][key]) != PureWindowsPath(value) for key,value in expected.items()):
        raise ValueError('Registered worker differs from startup binding')
    if state['host'] != host['host'] or state['released'] != 0 or not state['slot'] or state['slot'][:2] != [scope,attempt]:
        raise ValueError('Original unreleased claim and retained startup slot required')
    return dict(spec=spec, spec_path=str(spec_path), bootstrap=str(bootstrap), evidence=evidence+[file_evidence(config),file_evidence(preset),file_evidence(monitor_path)],
                host=host, process=receipt['process'], registry=str(registry), scope=scope, attempt=attempt, registry_state=state)


def saved_profile(context):
    import configparser
    from studio_onboarding import verify_saved_monitor
    b=context['spec']['binding']; parser=configparser.ConfigParser(interpolation=None)
    raw=Path(context['host']['configuration']['config']).read_bytes()
    parser.read_string(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    profile=safe(Path(b['research_data_root'])/'MQL5/Profiles/Charts'/parser['Charts']['ProfileLast'])
    charts=list(profile.glob('*.chr'))
    if not charts or len(charts)>16: raise ValueError('Retained passive profile charts required')
    result=[]
    for path in charts:
        raw=safe(path).read_bytes()
        if len(raw)>2_000_000: raise ValueError('Oversized saved chart')
        text=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
        if '<script>' in text.lower(): raise ValueError('Saved startup profile contains a script')
        if '<expert>' in text.lower():
            verify_saved_monitor(raw,b['startup_monitor']['expert'],parser['StartUp']['Symbol'],b['research_data_root'])
        else:
            # Plain charts may contain only the built-in price indicator.
            blocks=re.findall(r'<indicator>\s*(.*?)\s*</indicator>',text,re.S|re.I)
            if len(blocks)!=text.lower().count('<indicator>'): raise ValueError('Ambiguous saved indicator blocks')
            for block in blocks:
                fields={}
                for line in block.splitlines():
                    key,sep,value=line.strip().partition('=')
                    if not sep or key in fields: raise ValueError('Ambiguous saved indicator')
                    fields[key]=value
                if fields.get('name')!='Main' or fields.get('path','')!='': raise ValueError('Saved profile contains custom indicator')
        result.append(file_evidence(path))
    return result


def classify_testers(c, snapshot):
    """Permanent Windows tester services are not evidence of a running test.

    Only positively identified independent service agents may remain. A selected
    terminal connection to ANY loopback service, unknown agent or updater blocks.
    No tester command lines/passwords enter the observation or receipt.
    """
    rows=snapshot['processes'];services=snapshot['services'];connections=snapshot['connections']
    if not all(isinstance(value,list) for value in (rows,services,connections)):
        raise ValueError('Complete process/service/connection inventory required')
    by_pid={r['ProcessId']:r for r in rows}
    if len(by_pid)!=len(rows):raise ValueError('Ambiguous process inventory')
    selected={r['ProcessId'] for r in rows if PureWindowsPath(r.get('ExecutablePath') or '')==PureWindowsPath(c.install['terminal_executable'])}
    if len(selected)>1:raise ValueError('Ambiguous selected terminal')
    if any(r['OwningProcess'] in selected and str(r['State'])=='Established'
           and r['RemoteAddress'] in ('127.0.0.1','::1','::ffff:127.0.0.1') for r in connections):
        raise ValueError('Selected terminal has an active local service connection')
    excluded=[]
    for row in rows:
        name=str(row.get('Name','')).lower()
        if name.startswith('metaupdate'):raise ValueError('MT5 updater remains active')
        if name not in ('metatester64.exe','metatester.exe'):continue
        matches=[s for s in services if s['ProcessId']==row['ProcessId'] and s['State']=='Running']
        parent=by_pid.get(row.get('ParentProcessId'),{})
        if len(matches)!=1 or str(parent.get('Name','')).lower()!='services.exe':
            raise ValueError('Unowned or selected native tester remains')
        service=matches[0];image=PureWindowsPath(service.get('ExecutablePath') or '')
        if (not image.is_absolute() or image.name.lower()!=name
                or (row.get('ExecutablePath') and PureWindowsPath(row['ExecutablePath'])!=image)):
            raise ValueError('Tester service executable is ambiguous')
        excluded.append(dict(pid=row['ProcessId'],service=service['Name'],executable=str(image)))
    return dict(status='no_selected_tester_or_updater_processes',independent_service_agents=excluded,observed_unix=time.time())


def require_no_testers(c):
    command=r'''$ErrorActionPreference='Stop'
$processes=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(terminal64|terminal|metatester64|metatester|metaupdate64|metaupdate|services)\.exe$'} | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath)
$services=@(Get-CimInstance Win32_Service | Where-Object {$_.ProcessId -in @($processes.ProcessId) -and $_.State -eq 'Running'} | ForEach-Object {
 $serviceImage=$null
 if($_.PathName -match '^"([^"\r\n]+\.exe)"(?:\s|$)') {$serviceImage=$Matches[1]}
 elseif($_.PathName -match '^(\S+\.exe)(?:\s|$)') {$serviceImage=$Matches[1]}
 [ordered]@{Name=$_.Name;State=$_.State;ProcessId=$_.ProcessId;ExecutablePath=$serviceImage}
})
$connections=@(Get-NetTCPConnection | Select-Object OwningProcess,@{Name='State';Expression={$_.State.ToString()}},RemoteAddress)
@{processes=$processes;services=$services;connections=$connections} | ConvertTo-Json -Depth 6 -Compress
'''
    snapshot=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True,encoding='utf-8-sig',timeout=20))
    return classify_testers(c,snapshot)


def state_view(context):
    spec = context['spec']; b = spec['binding']; database = safe(b['controller_database'])
    bridge = safe(b['bridge_root']); local = safe(b['research_data_root'])/'MQL5/Files/GOATStudio'
    if bridge != local/spec['run_id'] or read_json(local/'active.json') != dict(directory_id=spec['run_id'],terminal_id=spec['terminal_id'],run_id=spec['run_id'],terminal_data_path=b['research_data_root']):
        raise ValueError('Legacy active bridge changed')
    binding = read_json(bridge/'binding.json')
    if binding.get('database') != str(database) or binding.get('terminal_id') != spec['terminal_id'] or binding.get('run_id') != spec['run_id']:
        raise ValueError('Legacy bridge database differs')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        key = packed(dict(terminal_id=spec['terminal_id'], run_id=spec['run_id']))
        states = db.execute('SELECT binding,revision,generation,owner FROM studio_state').fetchall()
        if len(states)!=1 or states[0][0]!=key or states[0][2]!=context['host']['generation'] or states[0][3]!='agent':
            raise ValueError('Original controller generation/ownership changed')
        queues = db.execute('SELECT binding,jobs FROM studio_queues').fetchall()
        if any(binding!=key or any(j['status'] not in ('completed','failed','cancelled','removed','superseded') for j in json.loads(raw)) for binding,raw in queues):
            raise ValueError('Pending or unresolved work is not a passive bootstrap')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'studio_fixed_tasks' in tables and db.execute('SELECT 1 FROM studio_fixed_tasks WHERE released=0').fetchone():
            raise ValueError('Fixed task still owns the selected controller')
        gates = [safe(row[0]) for row in db.execute('SELECT root FROM studio_native_gate')]
        for gate in gates:
            if not gate.is_relative_to(local): raise ValueError('Legacy gate escapes selected terminal')
            if read_json(gate/'controller.json') != {'database':str(database)}:
                raise ValueError('Legacy gate database ownership changed')
            if (gate/'request.json').exists() or (gate/'request.json').is_symlink():
                from studio_legacy_settled_gate import assert_legacy_settled_request
                assert_legacy_settled_request(db,gate,context['registry'])
            else:
                assert_clear_controls(db,gate)
        native = safe(b['common_files_root'])/'GOAT/Workers'/context['scope']
        for name in ('active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini','agent-native-control-owner.json'):
            if list(native.rglob(name)) if native.exists() else []:
                raise ValueError('Scoped native execution controls remain')
        seed = database.parent/'seed-active.json'
        if seed.exists() and read_json(seed).get('status')!='released': raise ValueError('Seed task remains active')
        for channel in ('human','agent'):
            for queue in ('inbox','processing'):
                if any((bridge/channel/queue).glob('*.json')):
                    raise ValueError('Unprocessed controller inbox requires reconciliation')
        return dict(states=[list(row) for row in states], queue_sha256=sha(queues), gates=[str(p) for p in gates])


def process_binding(c, context):
    from studio_protected_peer import process_binding as protected_binding
    return protected_binding(c)


def running_snapshot(c, context):
    from studio_resilient_read import read_observation
    processes = inspect_processes(process_binding(c, context))
    require_no_testers(c)
    dead = [prove_exited(context['host']['host']), prove_exited(context['process'])]
    spec = context['spec']; b = spec['binding']
    observation, modified = read_observation(safe(spec['observation_path']))
    if type(observation.get('runtime',{}).get('batch_ongoing')) is not bool:
        raise ValueError('Native batch flag observation required')
    check_runtime(observation, now=time.time(), modified=modified, data_path=b['research_data_root'],
                  installation_path=str(Path(b['research_terminal']).parent), program_path=spec['monitor_path'],
                  account_login=spec['account']['login'], account_server=spec['account']['server'],
                  require_idle=True, expected_batch_ongoing=observation['runtime'].get('batch_ongoing'))
    if observation['runtime'].get('native_control_scope') != context['scope'] or observation.get('loaded') is not True:
        raise ValueError('Fresh loaded scoped monitor required')
    created = datetime.fromisoformat(processes['research']['created_utc'].replace('Z','+00:00')).timestamp()
    if modified < created: raise ValueError('Runtime feedback predates replacement process')
    view = state_view(context)
    state=view['states'][0]
    if any(observation.get(key)!=value for key,value in [('generation',state[2]),('owner',state[3])]):
        raise ValueError('Monitor has not read the current controller state; use original controller to synchronize first')
    draft=None
    if observation.get('revision')!=state[1]:
        # R17's revision is the EDITOR baseline, intentionally retained while
        # dirty. ManagedRefresh emits the current bridge revision in status and
        # only emits this exact suffix after durable ManagedPersistDraft succeeds.
        # Do not reinterpret newer/unknown observation formats this way.
        expected='Agent controls settings / revision '+str(state[1])+' / Unsaved edits retained'
        if (observation.get('build')!='R17' or observation.get('status')!=expected
                or observation.get('pending_id')!='' or type(observation.get('revision')) is not int
                or not 0<=observation['revision']<state[1]):
            raise ValueError('Monitor has not read the current controller state; use original controller to synchronize first')
        draft_path=safe(Path(b['bridge_root'])/'human/ui-draft.json');saved=read_json(draft_path)
        expected_fields=dict(schema_version=1,terminal_id=spec['terminal_id'],run_id=spec['run_id'],revision=observation['revision'],generation=state[2],
                             tester_ini=observation.get('tester_ini'),export_ini=observation.get('export_ini'))
        if any(saved.get(k)!=v for k,v in expected_fields.items()) or any(not isinstance(saved.get(k),str) for k in ('tester_ini','export_ini','baseline','submitted')):
            raise ValueError('Legacy unsaved editor values are not durably preserved')
        draft=file_evidence(draft_path)
    return dict(processes={key:processes[key] for key in ('research','protected')}, controller=view, old_process_exit=dead,
                profile=saved_profile(context),preserved_legacy_draft=draft,
                runtime_flags={k:observation['runtime'][k] for k in ('account_demo','connected','terminal_trade_allowed','tester_state','batch_ongoing','restart_pending')})


def prepare(c, spec_path, bootstrap):
    from studio_handover import session_lock
    with session_lock(c):
        context = verify_issuance(c, spec_path, bootstrap)
        snapshot = running_snapshot(c, context)
        root = folder(c); root.mkdir(parents=True,exist_ok=True)
        with exclusive_gate(root):
            if (root/'pending.json').exists(): raise ValueError('Prior retirement pending; inspect its exact review')
            registered=dict(registry=context['registry'],scope=context['scope'],database=context['spec']['binding']['controller_database'],
                            terminal=c.install['terminal_executable'],data_root=c.install['terminal_data_root'])
            registration=root/'registry.json'
            if registration.exists() and read_json(registration)!=registered: raise ValueError('Different retained legacy registry; reconcile before migration')
            if not registration.exists(): write_json(registration,registered)
            review_id = uuid.uuid4().hex; target = root/review_id; target.mkdir()
            plan = dict(schema_version=1,review_id=review_id,installation_sha256=sha(c.install),
                        created_at=time.time(),expires_at=time.time()+900,context=context,snapshot=snapshot)
            if snapshot['preserved_legacy_draft']:
                draft=snapshot['preserved_legacy_draft'];raw=safe(draft['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=draft['sha256']:raise ValueError('Legacy draft changed during preservation')
                with (target/'preserved-ui-draft.json').open('xb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
            write_json(target/'review.json', plan)
            return dict(review_id=review_id, status='review', selected_process=snapshot['processes']['research'],
                        protected_process=snapshot['processes']['protected'], scope=context['scope'],attempt=context['attempt'],
                        effects=['one normal close of exact idle replacement monitor','retire original failed bootstrap claim and startup slot after exit proof'],
                        no_optimization_started=True,expires_at=plan['expires_at'])


def legacy_registration(c):
    path=folder(c)/'registry.json'
    if not path.exists(): return None
    value=read_json(safe(path))
    if set(value)!={'registry','scope','database','terminal','data_root'} or value['terminal']!=c.install['terminal_executable'] or value['data_root']!=c.install['terminal_data_root']:
        raise ValueError('Retained legacy registry belongs to another terminal')
    with closing(sqlite3.connect(safe(value['registry']).as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT configuration FROM workers WHERE scope=?',(value['scope'],)).fetchone()
        worker=json.loads(row[0]) if row else {}
        for key,field in [('terminal','terminal'),('data_root','data_root'),('controller','database')]:
            if PureWindowsPath(worker.get(key,''))!=PureWindowsPath(value[field]): raise ValueError('Registered legacy worker binding changed')
    return value


def handover_guard(c):
    value=legacy_registration(c)
    if not value:return None
    with closing(sqlite3.connect(safe(value['registry']).as_uri()+'?mode=ro',uri=True)) as db:
        active=db.execute('SELECT attempt FROM attempts WHERE scope=? AND released=0',(value['scope'],)).fetchall()
        slots=db.execute('SELECT attempt FROM startup_slot WHERE scope=?',(value['scope'],)).fetchall()
        if active or slots:raise ValueError('Registered legacy bootstrap/worker still owns this terminal; inspect its retirement')
    return value


def handover_gate(c,db,gate):
    value=legacy_registration(c)
    actual=str(Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve())
    request=Path(gate)/'request.json'
    if value and actual==value['database'] and (request.exists() or request.is_symlink()):
        from studio_legacy_settled_gate import assert_legacy_settled_request
        return assert_legacy_settled_request(db,gate,value['registry'])
    if Path(gate)==c.local/'native-gate' and request.exists() and actual!=str(c.root/'studio.sqlite'):
        from campaign_ledger import packed
        retained=read_json(request)
        binding=packed(dict(terminal_id=retained['terminal_id'],run_id=retained['run_id']))
        row=db.execute('SELECT jobs FROM studio_queues WHERE binding=?',(binding,)).fetchone()
        jobs=[j for j in json.loads(row[0]) if j['job_id']==retained['job_id']] if row else []
        if len(jobs)==1 and 'completion_path' not in jobs[0]:
            from studio_legacy_root_gate import assert_legacy_root_settled
            return assert_legacy_root_settled(db,gate,c.install)
    return assert_clear_controls(db,gate)


def load(c, review_id):
    if not re.fullmatch('[a-f0-9]{32}',review_id): raise ValueError('Invalid retirement review ID')
    target = safe(folder(c)/review_id); plan=read_json(target/'review.json')
    if plan.get('review_id')!=review_id or plan.get('installation_sha256')!=sha(c.install): raise ValueError('Retirement installation changed')
    return target,plan


def validate_proof(plan, proof, review_path):
    value=read_json(proof); context=plan['context']; snapshot=plan['snapshot']
    identities=[context['host']['host'],context['process'],snapshot['processes']['research']]
    exits=value.get('exit_proofs',[])
    if (value.get('status')!='inspected_passive_bootstrap_retirement' or value.get('scope')!=context['scope']
            or value.get('attempt')!=context['attempt'] or value.get('stable_allocation_claimed') is not False
            or value.get('review_sha256')!=file_evidence(review_path)['sha256']
            or value.get('bootstrap_evidence')!=context['evidence']
            or [item.get('identity') for item in exits]!=identities
            or any(item.get('proof') not in ('pid_absent','pid_reused','exact_process_signaled') for item in exits)
            or value.get('processes',{}).get('research') is not None
            or value.get('processes',{}).get('protected')!=snapshot['processes']['protected']
            or value.get('tester_proof',{}).get('status')!='no_selected_tester_or_updater_processes'):
        raise ValueError('Retirement proof does not match exact reviewed bootstrap')
    return value


def retire_transaction(db, context, proof):
    """Atomic release; callers already hold native gates and fresh absence proof."""
    raw = safe(proof).read_bytes(); evidence = dict(receipt_path=str(safe(proof)),receipt_sha256=hashlib.sha256(raw).hexdigest())
    value = read_json(proof)
    if value.get('status')!='inspected_passive_bootstrap_retirement' or value.get('scope')!=context['scope'] or value.get('attempt')!=context['attempt']:
        raise ValueError('Wrong retirement proof')
    scope,attempt = context['scope'],context['attempt']
    current = registry_state(db,scope,attempt)
    if current['released']==1 and current['release_evidence']==json.dumps(evidence,sort_keys=True):
        rows = db.execute('SELECT receipt_path,receipt_sha256 FROM startup_slot_history WHERE scope=? AND attempt=?',(scope,attempt)).fetchall()
        if current['slot'] or rows!=[(evidence['receipt_path'],evidence['receipt_sha256'])]: raise ValueError('Ambiguous prior retirement')
        return evidence
    if current != context['registry_state']: raise ValueError('Original registry claim/slot changed')
    db.execute('INSERT INTO startup_slot_history(scope,attempt,acquired_unix,receipt_path,receipt_sha256) VALUES(?,?,?,?,?)',
               (scope,attempt,current['slot'][2],evidence['receipt_path'],evidence['receipt_sha256']))
    db.execute('UPDATE attempts SET released=1,release_evidence=? WHERE scope=? AND attempt=?',(json.dumps(evidence,sort_keys=True),scope,attempt))
    db.execute('DELETE FROM startup_slot WHERE id=1 AND scope=? AND attempt=?',(scope,attempt))
    return evidence


def apply(c, review_id):
    from studio_handover import paths
    root = folder(c); target,plan=load(c,review_id); context=plan['context']
    lock = paths(c)[3]; lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock), exclusive_gate(root), ExitStack() as stack:
        pending = root/'pending.json'
        if pending.exists() and read_json(pending)!={'review_id':review_id}: raise ValueError('Different retirement pending')
        if (target/'complete.json').exists():
            result=read_json(target/'complete.json')
            if result.get('review_id')!=review_id or result.get('status')!='retired': raise ValueError('Completion identity changed')
            validate_proof(plan,target/'retirement-proof.json',target/'review.json')
            pending.unlink(missing_ok=True)
            return result
        for item in context['evidence']:
            if file_evidence(item['path'])!=item: raise ValueError('Original bootstrap evidence changed')
        for gate in plan['snapshot']['controller']['gates']: stack.enter_context(exclusive_gate(gate))
        # Prevent legacy queue/grant changes across inspection, close and retirement,
        # even for writers which do not cooperate with the native file gate.
        legacy=stack.enter_context(closing(sqlite3.connect(context['spec']['binding']['controller_database'],timeout=1,isolation_level=None)))
        legacy.execute('BEGIN IMMEDIATE')
        if not (target/'close-issued.json').exists():
            if time.time()>plan['expires_at']: raise ValueError('Retirement review expired')
            current = verify_issuance(c,context['spec_path'],context['bootstrap'])
            if current!=context or running_snapshot(c,current)!=plan['snapshot']: raise ValueError('Reviewed bootstrap state changed')
            write_json(pending,dict(review_id=review_id))
            write_json(target/'close-issued.json',dict(process=plan['snapshot']['processes']['research'],issued_at=time.time()))
            # Intent precedes effect. A failed/uncertain close must never resend.
            WindowsSeedProcess(c).close(plan['snapshot']['processes']['research'])
        deadline=time.monotonic()+20
        while True:
            try:
                absence=inspect_processes(process_binding(c,context),research_running=False)
                break
            except ValueError:
                if time.monotonic()>=deadline:
                    return dict(status='close_outcome_unresolved',review_id=review_id,retired=False,close_will_not_be_repeated=True)
                time.sleep(.25)
        if absence['protected']!=plan['snapshot']['processes']['protected']: raise ValueError('Protected peer changed')
        tester_proof=require_no_testers(c)
        death=[prove_exited(identity) for identity in (context['host']['host'],context['process'],plan['snapshot']['processes']['research'])]
        if state_view(context)!=plan['snapshot']['controller']: raise ValueError('Legacy controller changed while closing')
        proof=target/'retirement-proof.json'
        if not proof.exists():
            write_json(proof,dict(status='inspected_passive_bootstrap_retirement',scope=context['scope'],attempt=context['attempt'],
                review_sha256=file_evidence(target/'review.json')['sha256'],observed_at=time.time(),exit_proofs=death,
                processes=absence, tester_proof=tester_proof,bootstrap_evidence=context['evidence'],stable_allocation_claimed=False))
        validate_proof(plan,proof,target/'review.json')
        # Hold a registry write transaction through the final fresh process check.
        with closing(sqlite3.connect(context['registry'],timeout=1,isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                check=inspect_processes(process_binding(c,context),research_running=False)
                if check['protected']!=absence['protected']: raise ValueError('Protected peer changed before retirement')
                require_no_testers(c)
                evidence=retire_transaction(db,context,proof)
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK'); raise
        result=dict(status='retired',review_id=review_id,scope=context['scope'],attempt=context['attempt'],
                    evidence=evidence,registry=context['registry'],closed_process=plan['snapshot']['processes']['research'],
                    protected_process=absence['protected'],flags_changed=False,optimization_started=False)
        write_json(target/'complete.json',result)
        pending.unlink(missing_ok=True)
        return result
