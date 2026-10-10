"""One graceful monitor restart for a proven rejected, never-consumed start.

Owner-internal research only. No native control file, draft, grant, permission,
queue or batch journal is edited. The outstanding stop still needs a receipt.
"""
import hashlib
from pathlib import Path
import time

from campaign_ledger import packed,sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_handover import safe_path
from studio_native_gate import exclusive_gate
from studio_dispatch_observe import observe_dispatch
from studio_native_observe import observe
from studio_monitor_probe import inspect_idle_demo
from studio_seed_process import WindowsSeedProcess

OWNER_LOGIN='3000082754'

def proof(controller, job_id, *, revoked_maintenance=False):
    from studio_research_authority import authority
    state=controller.state()
    binding=packed(dict(terminal_id=controller.terminal,run_id=controller.run))
    if revoked_maintenance:
        from studio_research_regrant import takeover
        _,scope,_=takeover(controller.store.db,binding,state)
    else:
        scope=authority(controller.store.db,binding,state)
    if not revoked_maintenance and (scope is None or scope['kind']!='research_continuation' or state['owner']!='agent'
            or scope['generation']!=state['generation'] or controller.session['account']['login']!=OWNER_LOGIN
            or not scope['created_utc']<=time.time()<scope['expires_utc']):
        raise ValueError('Current owner-demo typed research continuation required')
    return unstarted_proof(controller,job_id,scope)


def unstarted_proof(controller,job_id,scope):
    """Historical native proof only; caller separately verifies current authority."""
    state=controller.state()
    if len(state['queue'])!=1 or state['queue'][0]['job_id']!=job_id:
        raise ValueError('Exactly one rejected original research job required')
    return unstarted_material(controller,state['queue'][0],scope)


def unstarted_material(controller,job,scope,*,request_path=None,allow_expired_unconsumed=False):
    """Verify retained original evidence; this never grants current authority."""
    job_id=job['job_id'];attempt=job['launch_intent']['attempt_id']
    if (job['status'] not in ('starting','reconcile_required') or 'restart_intent' in job
            or sha(job['configuration'])!=scope['configuration_sha256'] or job['configuration_sha256']!=scope['configuration_sha256']):
        raise ValueError('Rejected original job scope changed')
    gate=controller.local/'native-gate'
    for path in gate.glob('consumed-*.json'):
        item=read_json(safe_path(path))
        if item.get('action','start') in ('start','arm_restart'):
            raise ValueError('A consumed start exists; monitor restart refused')
    dispatch=observe_dispatch(gate,attempt)
    request=read_json(safe_path(gate/('issued-'+attempt+'.json')))['request']
    rejected=(dispatch.get('status')=='receipt_observed' and dispatch['receipt']['status']=='REQUEST_REJECTED')
    # Customer self-repair separately proves the exact expired cancel and absent
    # permit. Keep owner research monitor-restart callers rejection-only.
    expired_unconsumed=(allow_expired_unconsumed and dispatch.get('status')=='awaiting_receipt'
                        and dispatch.get('consumed') is False and not safe_path(gate/'permit.json').exists())
    if (not (rejected or expired_unconsumed) or dispatch.get('consumed') is not False
            or request['expires_utc']>=time.time()
            or request.get('action','start')!='start' or request['generation']!=scope['generation']
            or request['job_id']!=job_id or request['configuration_sha256']!=scope['configuration_sha256']
            or {k:request[k] for k in ('terminal_id','run_id')}!=scope['binding']):
        raise ValueError('Verified expired pre-consumption REQUEST_REJECTED required')
    zero_work_material(controller,job,scope)
    # Preserve all transport, including an expired pending cancel. Neither a
    # permit nor an unknown consumed action may arm anything during restart.
    current=read_json(safe_path(request_path or gate/'request.json'))
    if current['request_id'] not in (attempt,sha([attempt,'cancel'])) or current['expires_utc']>=time.time():
        raise ValueError('Only the expired original start/cancel may remain')
    for path in gate.glob('consumed-*.json'):
        if read_json(path).get('action') not in ('recover_orphan_continuation',):
            raise ValueError('Only prior orphan recovery consumption is allowed')
    return scope,job


def zero_work_material(controller,job,scope):
    """Causal zero-work evidence for one attempt: untouched package, native queue and run
    folders, an unarmed activation and no tester output. Grants no authority."""
    job_id=job['job_id'];attempt=job['launch_intent']['attempt_id']
    package=safe_path(controller.root/'packages'/job_id)
    if Path(job['launch_intent']['package']).resolve()!=package or hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()!=job['launch_intent']['package_sha256']:
        raise ValueError('Original package identity changed')
    native=observe(package)
    count=len(job['configuration']['batch_members'])
    expected={'native_queued':1}
    if count>1:expected['native_pending']=count-1
    if native['status_counts']!=expected:raise ValueError('Original native queue has work or changed members')
    activation=read_json(controller.root/'attempts'/attempt/'activation.json')
    from studio_report_paths import report_paths
    manifest=read_json(package/'manifest.json');plan=read_json(package/'studio-plan.json')
    paths=report_paths(plan,manifest)
    if activation['stage']!='CONTROLS_INSTALLED_NOT_ARMED' or activation['attempt_id']!=attempt:
        raise ValueError('Original unarmed activation required')
    # The local run may contain empty report directories, never actual output.
    local=safe_path(paths['local_run'])
    if any(p.is_file() for p in local.rglob('*')):raise ValueError('Native work artifacts exist')
    common=safe_path(paths['common_run'])
    expected_files={p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*') if p.is_file()}
    for item in manifest['jobs']:
        expected_files['inputs/'+item['run_alias']+'/config.ini']=hashlib.sha256((package/(item['run_alias']+'.ini')).read_bytes()).hexdigest()
    for name in ('queue.GOAT','portfolio.goatbatch'):
        expected_files[name]=hashlib.sha256((package/name).read_bytes().decode('utf-16').replace(';Pending_',';Queued_',1).encode('utf-16')).hexdigest()
    actual={p.relative_to(common).as_posix():hashlib.sha256(safe_path(p).read_bytes()).hexdigest() for p in common.rglob('*') if p.is_file()}
    if actual!=expected_files:raise ValueError('Native work artifacts or checkpoint/control changes exist')
    cache=Path(controller.install['terminal_data_root'])/'Tester/cache'
    if cache.exists() and any(p.is_file() and p.stat().st_mtime>=scope['created_utc'] for p in cache.rglob('*')):
        raise ValueError('Tester work artifacts exist since bootstrap')


def require_demo(native):
    if any(native.get(k)!=v for k,v in dict(demo=True,connected=True,algo_trading=False,positions=0,orders=0,account_matches=True,tester_state='idle').items()):
        raise ValueError('SDK-confirmed same idle demo, Algo OFF and zero trades required')


def reverify(controller,job_id):
    from studio_terminal_lease import BUSY_READ,terminal_lease
    scope,job=proof(controller,job_id)
    path=controller.root/'rejected-monitor-restarts'/job['launch_intent']['attempt_id']/'restart.json'
    # A read: the terminal lease (L1) without waiting BEFORE the native gate (L4), never after it, so a status read
    # neither waits on the gate nor attaches while a driver owns this MT5 (goatai#2350 6098964146).
    with terminal_lease(controller.root,purpose='research-monitor-restart-status',busy_code='BROKER_READ_DEFERRED',
                        busy_message=BUSY_READ,broker_reason='terminal_busy'),\
            exclusive_gate(controller.local/'native-gate'):
        record=read_json(path)
        if record['phase'] not in ('started_unverified','adopted_unverified','reverified') or record['authority_sha256']!=sha(scope):
            raise ValueError('No exact started monitor to reverify; never repeat launch')
        if record.get('controller_derived_report_recovery'):
            from studio_derived_report_recovery import verify_completed
            native=verify_completed(controller,record)
        elif record.get('human_reopened') is True:
            from studio_human_reopen import verify_adopted
            native=verify_adopted(controller,record,path)
        else:
            native=inspect_idle_demo(controller);require_demo(native)
        if native['process']!=record['process']:raise ValueError('Relaunch process changed')
        if record['phase']!='reverified':
            record.update(phase='reverified',after=native);write_json(path,record)
        return record


def _launch_stopped(controller,record,path,process,clock):
    from studio_onboarding import verify_monitor_profile,saved_launch_policy
    from studio_driver_suspend import require_no_publishers
    if record['phase']!='stopped' or process.inspect() is not None:
        raise ValueError('Recorded monitor exit required before its first relaunch')
    saved_launch_policy(controller,controller.session)
    profile=read_json(controller.root/'monitor-profile.json');verify_monitor_profile(controller,profile)
    preset=safe_path(Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
    expected_preset='Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
    if preset.read_bytes()!=expected_preset:raise ValueError('Saved monitor preset changed after close')
    expected=('[Charts]\r\nProfileLast='+profile['profile_name']+'\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n'
              '[StartUp]\r\nExpert='+controller.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+'\r\nPeriod=M1\r\n').encode('utf-16')
    config=safe_path(Path(record['launch']['startup_config']))
    if config.read_bytes()!=expected or hashlib.sha256(expected).hexdigest()!=record['launch']['startup_sha256']:
        raise ValueError('Saved config changed after close')
    protected={str(p) for p in (controller.root/'session.json',controller.root/'research-authority.json',controller.bridge.root/'human/ui-draft.json')}
    if set(record['protected_sha256'])!=protected:raise ValueError('Protected evidence paths changed')
    for p,digest in record['protected_sha256'].items():
        if hashlib.sha256(safe_path(Path(p)).read_bytes()).hexdigest()!=digest:
            raise ValueError('Protected session/draft changed during close; inspect before relaunch')
    require_no_publishers(controller)
    record['phase']='launch_issued';write_json(path,record)
    record['process']=process.start(config)
    record['phase']='started_unverified';write_json(path,record)
    deadline=clock.monotonic()+30
    while True:
        try:
            after=inspect_idle_demo(controller);require_demo(after)
            if after['process']!=record['process']:raise ValueError('Relaunch process changed')
            break
        except ValueError:
            if clock.monotonic()>=deadline:raise
            clock.sleep(1)
    record.update(phase='reverified',after=after);write_json(path,record)
    return record


def resume(controller,job_id,*,process=None,clock=time):
    """Reconcile a retained close, then issue its not-yet-issued launch once."""
    from studio_seed_slot import guard_active_seed
    process=process or WindowsSeedProcess(controller)
    controller.bridge.pump()
    with exclusive_gate(controller.root/'batch-driver-gate'),exclusive_gate(controller.local/'native-gate'):
        scope,job=proof(controller,job_id);guard_active_seed(controller.root)
        path=controller.root/'rejected-monitor-restarts'/job['launch_intent']['attempt_id']/'restart.json'
        record=read_json(path)
        if (record['phase'] not in ('close_issued','stopped') or record['authority_sha256']!=sha(scope)
                or record['job_id']!=job_id or record['attempt_id']!=job['launch_intent']['attempt_id']):
            raise ValueError('Only the original unlaunched close can resume; never repeat a launch')
        suspended=read_json(path.parent/'publisher-stopped.json')
        if sha(suspended)!=record['suspension_sha256'] or suspended.get('supervisor_exited') is not True:
            raise ValueError('Original publisher suspension proof changed')
        driver=controller.root/'batch-drivers'/(job_id+'.json')
        if hashlib.sha256(driver.read_bytes()).hexdigest()!=suspended['journal_sha256']:
            raise ValueError('Original publisher journal changed after suspension')
        current=process.inspect()
        if current is not None:
            raise ValueError('Monitor is still present or replaced; no repeated close or adoption')
        record['phase']='stopped';write_json(path,record)
        return _launch_stopped(controller,record,path,process,clock)


def restart(controller,job_id,*,process=None,suspend_fn=None,clock=time):
    from studio_driver_suspend import suspend
    from studio_onboarding import verify_monitor_profile,saved_launch_policy
    from studio_seed_slot import guard_active_seed
    process=process or WindowsSeedProcess(controller);suspend_fn=suspend_fn or suspend
    scope,job=proof(controller,job_id)
    attempt=job['launch_intent']['attempt_id']
    folder=safe_path(controller.root/'rejected-monitor-restarts'/attempt)
    folder.mkdir(parents=True,exist_ok=True)
    record_path=folder/'restart.json'
    if record_path.exists():raise ValueError('One monitor restart already recorded; inspect, never repeat')
    native=inspect_idle_demo(controller);require_demo(native)
    stopped=suspend_fn(controller,job,folder)
    if stopped.get('supervisor_exited') is not True or stopped.get('native_stop_claimed') is not False:
        raise ValueError('Old publisher has not verifiably stopped')
    # Inbox processing can enter store mutation_gate. Never pump under the
    # non-reentrant native gate; recheck authority after pending human actions.
    controller.bridge.pump()
    with exclusive_gate(controller.root/'batch-driver-gate'),exclusive_gate(controller.local/'native-gate'):
        if record_path.exists():raise ValueError('One monitor restart already recorded; inspect, never repeat')
        scope,job=proof(controller,job_id);guard_active_seed(controller.root)
        native=inspect_idle_demo(controller);require_demo(native)
        preset=safe_path(Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
        expected='Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
        if preset.read_bytes()!=expected:raise ValueError('Saved monitor preset changed')
        profile=read_json(controller.root/'monitor-profile.json')
        verify_monitor_profile(controller,profile)
        launches=[read_json(p) for p in (controller.root/'monitor-launches').glob('*.json')]
        matching=[r for r in launches if r.get('pid')==native['process']['pid'] and r.get('status')=='process_started_unverified'
                  and r.get('installation_sha256')==sha(controller.install) and r.get('run_id')==controller.run]
        if len(matching)!=1:raise ValueError('Exact current monitor launch receipt required')
        launch=matching[0];config=safe_path(Path(launch['startup_config']))
        expected_config=('[Charts]\r\nProfileLast='+profile['profile_name']+'\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n'
                         '[StartUp]\r\nExpert='+controller.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+'\r\nPeriod=M1\r\n').encode('utf-16')
        if config.read_bytes()!=expected_config or hashlib.sha256(expected_config).hexdigest()!=launch['startup_sha256']:
            raise ValueError('Saved monitor-only startup config changed')
        protected=[controller.root/'session.json',controller.root/'research-authority.json',controller.bridge.root/'human/ui-draft.json']
        hashes={str(p):hashlib.sha256(safe_path(p).read_bytes()).hexdigest() for p in protected}
        record=dict(schema_version=1,attempt_id=attempt,job_id=job_id,authority_sha256=sha(scope),
                    phase='close_issued',native=native,protected_sha256=hashes,launch=launch,
                    suspension_sha256=sha(stopped),created_utc=clock.time(),native_started=False,grant_created=False)
        from studio_driver_suspend import require_no_publishers
        require_no_publishers(controller)
        write_json(record_path,record)
        process.close(native['process'])
        deadline=clock.monotonic()+20
        while True:
            current=process.inspect()
            if current is None:break
            if current!=native['process']:raise ValueError('Monitor identity changed after close; no adoption')
            if clock.monotonic()>=deadline:raise ValueError('Monitor close unconfirmed; never force kill or repeat')
            clock.sleep(.2)
        record['phase']='stopped';write_json(record_path,record)
        _launch_stopped(controller,record,record_path,process,clock)
    return record
