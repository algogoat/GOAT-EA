"""One bounded first-member /config launch after the EA acknowledges native arming.

All phases are retained. Interrupted close/launch is observation-only: this function
never resumes a consumed start, repeats a close, resets a deadline or creates a grant.

Qualified lanes: the broker-verified direct demo lane, and the customer native
human-control lane (`goat.exe studio` after bootstrap). MT5 writes the tester
`Report=` main/forward XML only for a /config startup launch, never for an
in-place Start click, so without this route every customer batch ends with zero
reports and the EA aborts its exports. The customer lane additionally requires
the user's MT5 restart consent retained in this batch's driver journal and an
SDK-confirmed same idle demo (Algo OFF, zero positions/orders) before arming.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
from campaign_ledger import packed
from studio_bridge import write_json
from studio_dispatch_observe import observe_dispatch
from studio_dispatch_transport import publish_restart_arm
from studio_launch_intent import record_intent
from studio_native_gate import exclusive_gate
from studio_native_request import (validate_launch_material,validate_restart_controls,
                                   validate_restart_material)
from studio_open_activation import _install_controls
from studio_process_check import RollingBaseline,inspect_processes,revalidate_processes
from studio_research_authority import before_native_dispatch
from studio_seed_process import WindowsSeedProcess,research_view
from studio_seed_slot import guard_active_seed
from studio_report_bridge import prepare as bridge_prepare,verify as bridge_verify

CONFIG_START_LANES=('demo_direct','native_human_control')
# The user's yes covers one start of this batch on the MT5 that was running when they gave it, for a short time:
# a restarted MT5 or a later start needs a new yes. Since batches run on GOAT Research (Claude-Mac goatai#2350
# 6120004490, option (i)) it also covers returning MT5 to normal when this batch ends: at the batch driver's finish,
# one normal close (close-terminal's checks: demo, Algo Trading off, no positions/orders, not an Open Lab login) and
# monitor-launch back onto the GOAT Studio monitor profile (studio_research_profile.batch_end_state). The scope name
# changed with it, so a consent recorded under the start-only wording never authorises that end close.
RESTART_CONSENT_SCOPE='close_and_reopen_selected_mt5_for_this_batch_start_and_end'
RESTART_CONSENT_SECONDS=600
SDK_REFUSAL='SDK-confirmed same idle demo, Algo OFF and zero trades required'


def config_start_lane(session):
    """True for a session whose bounded driver must use the report-capable /config route."""
    return isinstance(session,dict) and session.get('authority_kind') in CONFIG_START_LANES


def refuse_raw_start(session):
    """The raw in-place `start` can never make MT5 write reports on the customer lane."""
    if isinstance(session,dict) and session.get('authority_kind')=='native_human_control':
        raise ValueError('Raw start is not available on this lane: an in-place Start never makes MT5 write the batch '
                         'reports, so the batch would end with 0 exports. Nothing was started. Tell the user GOAT '
                         'closes and reopens their MT5 to start the batch, then after their yes run run-batch '
                         '--job-id <id> --max-seconds <budget> --mt5-restart-consent (goat.ps1: Start-Batch <id> '
                         '-MaxSeconds <budget> -Mt5RestartConsent)')


def _identity(process):
    return {k:process.get(k) for k in ('pid','executable','created_utc')} if isinstance(process,dict) else None


def consent_record(c,job_id,now):
    """Consent bound to the exact selected MT5 process (PID, image, creation time) and an expiry."""
    from studio_installation import read_json
    plan=read_json(c.root/'packages'/job_id/'studio-plan.json')
    observed=inspect_processes(plan['research_binding'])
    process=_identity(observed.get('research'))
    if not process or type(process['pid']) is not int or not process['executable'] or not process['created_utc']:
        raise ValueError('MT5 restart consent needs the selected MT5 running: ask the user to open it normally, '
                         'then start again; nothing was started')
    return dict(granted=True,recorded_wall=now,expires_wall=now+RESTART_CONSENT_SECONDS,scope=RESTART_CONSENT_SCOPE,
                job_id=job_id,process=process,source='run-batch --mt5-restart-consent')


def require_restart_consent(c,job_id,process=None,*,now=None,expiry=True):
    """The customer lane closes the user's own MT5: their retained, bound, unexpired consent is mandatory."""
    if c.session.get('authority_kind')!='native_human_control':return None
    journal=json.loads((c.root/'batch-drivers'/(job_id+'.json')).read_text(encoding='utf-8'))
    consent=journal.get('mt5_restart_consent')
    if (not isinstance(consent,dict) or consent.get('granted') is not True
            or consent.get('scope')!=RESTART_CONSENT_SCOPE or journal.get('binding',{}).get('job_id')!=job_id
            or consent.get('job_id')!=job_id):
        raise ValueError('MT5 restart consent required: tell the user GOAT will close and reopen the selected MT5 '
                         'for this batch, then start with --mt5-restart-consent')
    now=time.time() if now is None else now
    recorded,expires=consent.get('recorded_wall'),consent.get('expires_wall')
    if (type(recorded) not in (int,float) or type(expires) not in (int,float)
            or not recorded<=expires<=recorded+RESTART_CONSENT_SECONDS or (expiry and not recorded-5<=now<expires)):
        raise ValueError('MT5 restart consent expired or invalid: nothing was closed. Ask the user again, then start '
                         'with --mt5-restart-consent')
    if process is not None and _identity(process)!=consent.get('process'):
        raise ValueError('MT5 restart consent was given for another MT5 process (it restarted since): nothing was '
                         'closed. Ask the user again, then start with --mt5-restart-consent')
    return consent


def sdk_idle_demo(c,expected=None):
    """Broker-reported same demo, Algo OFF and zero positions/orders (no trading calls).

    Tester idleness comes from the EA runtime sample checked just before. The
    window-caption read is advisory here so a non-English MT5 is not refused:
    a recognised running caption still refuses, an unrecognised one defers to
    the EA (studio_monitor_probe.tester_caption_state).
    """
    from studio_monitor_probe import inspect_idle_demo
    try:
        native=inspect_idle_demo(c,tester='advisory')
    except ValueError as error:
        raise ValueError(SDK_REFUSAL+': '+str(error)) from error
    if any(native.get(k)!=v for k,v in dict(demo=True,connected=True,algo_trading=False,positions=0,orders=0,
                                            account_matches=True).items()) or native.get('tester_state')=='running':
        raise ValueError(SDK_REFUSAL)
    if expected is not None and native.get('process')!=expected:
        raise ValueError('SDK-observed MT5 differs from the selected process; no close or launch issued')
    return native


def restart_recovery(job):
    """Plain next step after a config start stopped part-way, from the retained phase. Read-only."""
    never='Do not run Start-Batch or start again for this batch, and do not click Start in the MT5 Strategy Tester. '
    report='Then run batch-status for this batch and send a support report with the batch ID and this message.'
    if not isinstance(job,dict):
        return dict(phase='unknown',mt5='unknown',plain='GOAT could not read how far the start got. MT5 may have been closed.',
                    next_safe_action='If MT5 is not open, ask the user to open MT5 normally from its usual shortcut. '+never+report)
    intent=job.get('restart_intent') or {}
    reached=intent.get('phase')
    if reached in (None,'prepared'):
        return dict(phase=reached,mt5='not_touched',plain='GOAT stopped before it changed anything in MT5. MT5 was not closed.',
                    next_safe_action='Follow the row for the error text (retire-unactivated settles a start refused before MT5 was touched).')
    if reached=='controls_installed':
        return dict(phase=reached,mt5='open_may_be_armed',
                    plain='MT5 was not closed. GOAT may already have told the EA a batch is starting, so the EA can show a batch as running.',
                    next_safe_action='Leave MT5 open and do not close or restart it yourself. '+never+report)
    # Batches run on GOAT Research (studio_research_profile): until the batch's MT5 is launched, common.ini still names
    # the GOAT Studio monitor profile, so a plain open shows the monitor. Once launched, MT5 may reopen on GOAT
    # Research, which also carries the GOAT monitor chart: never a File > Profiles step for the user.
    profiles='Do not change chart profiles in MT5 (File > Profiles); GOAT moves MT5 back to the monitor itself. '
    if reached=='close_issued':
        return dict(phase=reached,mt5='closing_or_closed',
                    plain='GOAT asked MT5 to close normally for the start. MT5 may still be closing (for example it shows a question) or may be closed. GOAT did not reopen it.',
                    next_safe_action='If MT5 is still open, leave it and do not answer for the user. If it is closed, ask the user to open MT5 normally from its usual shortcut; it opens on the GOAT Studio chart with the same account. '+never+report)
    if reached=='research_exited':
        return dict(phase=reached,mt5='closed_not_reopened',
                    plain='MT5 was closed for the start and GOAT did not reopen it.',
                    next_safe_action='If MT5 is not open, ask the user to open MT5 normally from its usual shortcut; it opens on the GOAT Studio chart with the same account. Keep Algo Trading off. '+never+report)
    if reached=='launch_issued':
        return dict(phase=reached,mt5='reopen_uncertain',
                    plain='MT5 was closed for the start and GOAT did not confirm reopening it.',
                    next_safe_action='If MT5 is not open, ask the user to open MT5 normally from its usual shortcut; it may open on GOAT Research, GOAT\'s batch chart profile, which also shows the GOAT monitor, with the same account. Keep Algo Trading off. '+profiles+never+report)
    return dict(phase=reached,mt5='reopened_unverified',plain='MT5 was reopened with the batch on GOAT Research, GOAT\'s batch chart profile. GOAT is checking that the batch runs.',
                next_safe_action='Keep polling batch-status; do not start again. '+profiles)


def checkpoint(c,job_id,generation):
    state=c.state();job=c.job(job_id)
    if state['owner']!='agent' or state['generation']!=generation:
        raise ValueError('Ownership changed during config start')
    if (c.root/'demo-agent/STOP').exists():raise ValueError('Owner STOP during config start')
    if any(any((c.bridge.root/'human'/part).glob('*.json')) for part in ('inbox','processing')):
        raise ValueError('Pending human control request during config start')
    journal=json.loads((c.root/'batch-drivers'/(job_id+'.json')).read_text(encoding='utf-8'))
    if journal['deadline_wall']<=time.time():raise ValueError('Batch deadline elapsed before config launch')
    return state,job


def phase(c,job_id,generation,expected,next_phase,**values):
    with c.store.transaction():
        state,job=checkpoint(c,job_id,generation)
        intent=job.get('restart_intent')
        if expected is None:
            if intent is not None:raise ValueError('Existing restart must be reconciled, never replayed')
            intent=dict(attempt_id=job['launch_intent']['attempt_id'],history=[])
        elif not intent or intent['phase']!=expected:
            raise ValueError('Restart phase changed')
        if intent['attempt_id']!=job['launch_intent']['attempt_id']:
            raise ValueError('Restart attempt changed')
        intent.update(values,phase=next_phase)
        intent['history'].append(dict(phase=next_phase,at=time.time()))
        job['restart_intent']=intent
        state['queue']=[job if row['job_id']==job_id else row for row in state['queue']]
        binding=packed(dict(terminal_id=c.terminal,run_id=c.run))
        c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
        c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
    c.bridge.pump()


def start(c,job_id,*,expected_generation=None,process=None,on_attempt=None,resume_unissued=False):
    if not config_start_lane(c.session):
        raise ValueError('Config start is qualified for the direct demo and native human-control lanes only')
    customer=c.session.get('authority_kind')=='native_human_control'
    guard_active_seed(c.root)
    state=c.state();job=c.job(job_id)
    generation=state['generation'] if expected_generation is None else expected_generation
    if type(resume_unissued) is not bool:raise ValueError('Explicit unissued resume flag required')
    if customer and resume_unissued:
        raise ValueError('Unissued-start resume is qualified for the direct demo lane only')
    if not resume_unissued and (job['status']!='pending' or 'launch_intent' in job):
        raise ValueError('Only a new pending batch may use config start')
    checkpoint(c,job_id,generation)
    require_restart_consent(c,job_id)
    package=c.root/'packages'/job_id
    plan=json.loads((package/'studio-plan.json').read_text(encoding='utf-8'))
    binding=plan['research_binding']
    if (binding.get('report_location_bridge')!='installation_to_data_v1'
            or not binding.get('startup_monitor') or not binding.get('research_profile')):
        raise ValueError('Prepare a new config-start package under a new batch ID; historical package remains unchanged')
    from studio_research_profile import RESEARCH_PROFILE,legacy_package_refusal
    if binding.get('research_profile')!=RESEARCH_PROFILE:
        # Packaged before batches ran on GOAT Research: its launch would open the monitor profile (goatai#2350
        # 6120004490). PACKAGE_PREDATES_RESEARCH_PROFILE: the app re-prepares it automatically (6120693275).
        raise legacy_package_refusal(job_id)
    args=c.native_args()
    c.runtime(require_idle=True,expected_batch_ongoing=False)
    before_native_dispatch(c,job)
    # Fast precheck before any reservation; the guarding baseline is taken below,
    # after the O(members) controller work, so a large batch never outlives it.
    precheck=inspect_processes(binding)
    # A restarted reviewed peer is accepted here and recorded append-only; an
    # unknown terminal or a changed peer executable/data root refused above.
    from studio_protected_peer import record_observed
    record_observed(c,binding,precheck.get('protected'),source='config_start:'+job_id)
    # GOAT peers it saw (a new instance, or MT5-updated bytes) are journaled the same way.
    from studio_peer_roster import record_seen
    record_seen(c,precheck.get('peers'),source='config_start:'+job_id)
    if customer:
        # The yes was for this exact MT5 process; then fresh broker proof before
        # anything is reserved, armed or closed.
        require_restart_consent(c,job_id,precheck['research'])
        sdk_idle_demo(c,precheck['research'])
    digest=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
    if resume_unissued:
        from studio_unissued_start import proof
        with exclusive_gate(c.local/'native-gate'):
            intent=proof(c,c.job(job_id),package)
    else:
        from studio_batch_driver import command_id,retry_index
        c.submit('queue.reserve',dict(job_id=job_id,configuration_sha256=job['configuration_sha256'],
                 package_sha256=digest),command_id(job_id,'-reserve',retry_index(c.root,job_id)),
                 expected_generation=generation)
        state=c.state()
        intent=record_intent(c.store,c.terminal,c.run,job_id,package,actor='agent',
                             revision=state['revision'],generation=generation)
    if on_attempt is not None:on_attempt(intent)
    evidence=c.root/'attempts'/intent['attempt_id'];evidence.parent.mkdir(exist_ok=True)
    material=validate_launch_material(c.state(),c.job(job_id),**{k:v for k,v in args.items() if k!='evidence'})
    rolling=RollingBaseline(binding,inspect_processes(binding),revalidate=revalidate_processes).take_over(precheck)
    baseline=rolling.current
    phase(c,job_id,generation,None,'prepared',startup_sha256=material['startup_receipt']['sha256'],
          process_baseline=baseline,account=dict(c.session['account']))
    def owned(bound,inventory):
        checkpoint(c,job_id,generation);rolling.check(bound)
        c.runtime(require_idle=True,expected_batch_ongoing=False)
    with exclusive_gate(c.local/'native-gate'):
        if resume_unissued:
            from studio_unissued_start import native_absence
            native_absence(c,c.job(job_id),package)
        arm_fields=_install_controls(c.state(),c.job(job_id),restart=True,**args,evidence=evidence,
                                     process_baseline=rolling.current,validate_ownership=owned)
        manifest=material['manifest']
        bridge=bridge_prepare(binding,manifest['native_run_relative'])
        write_json(evidence/'report-bridge.json',bridge)
        startup=evidence/'startup.ini'
        with startup.open('xb') as output:output.write(material['startup_raw'])
    phase(c,job_id,generation,'prepared','controls_installed',startup_path=str(startup),
          report_bridge=bridge,arm_request_fields=arm_fields)
    def validate(state,job):
        checkpoint(c,job_id,generation);rolling.check()
        bridge_verify(bridge)
        before_native_dispatch(c,job)
        return validate_restart_controls(state,job,**args,evidence=evidence)
    state=c.state()
    published=publish_restart_arm(c.store,c.terminal,c.run,job_id,c.bridge.root,actor='agent',
        revision=state['revision'],generation=generation,validate_native=validate,lifetime=60)
    deadline=time.monotonic()+65
    while True:
        checkpoint(c,job_id,generation)
        observed=observe_dispatch(c.local/'native-gate',intent['attempt_id'])
        if observed['status']=='receipt_observed':
            if not observed['consumed'] or observed['receipt']['status']!='RESTART_ARMED_RECONCILE':
                raise ValueError('Native arming refused; preserve receipt and do not relaunch')
            break
        if time.monotonic()>=deadline:raise ValueError('Native arming unconfirmed; no close or launch issued')
        time.sleep(.25)
    # The EA writes the arm receipt after its current runtime sample. Wait for
    # the next sample; retry this read only, never the arm or another command.
    runtime_deadline=time.monotonic()+15
    while True:
        checkpoint(c,job_id,generation)
        try:
            c.runtime(require_idle=True,expected_batch_ongoing=True)
            break
        except ValueError as error:
            if str(error)!='Runtime policy mismatch: batch_ongoing' or time.monotonic()>=runtime_deadline:
                raise
            time.sleep(.25)
    rolling.check()
    process=process or WindowsSeedProcess(c)
    identity=process.inspect()
    expected=baseline['research']
    if identity is None or identity['pid']!=expected['pid']:
        raise ValueError('Selected process changed before close')
    health=None
    if customer:
        # Up to ~80 s passed since the first SDK read: the user may have opened a
        # trade or switched account. Re-prove right before the only close. The
        # expiry was proved before reserve; refusing on it now would only strand
        # an armed MT5, so this check binds the process only.
        require_restart_consent(c,job_id,expected,expiry=False)
        native=sdk_idle_demo(c,expected)
        checkpoint(c,job_id,generation)
        # Fix B (Claude-Mac goatai#2350 6119079150): this restart close is the GOAT monitor's first close in the
        # start. The same health facts as close-terminal, from this SDK read and the EA's armed runtime sample
        # (batch_ongoing; the start advanced the revision). Never refuses or alters the start.
        health=_monitor_health(c,identity,native)
    else:
        # The direct demo lane (Banker's): the same first-close health read (Claude-Mac goatai#2350 6120693275 point 3),
        # its SDK readback taken by driver_pre_close_health itself only after every cheaper fact holds, so the end
        # state's monitor-launch is accepted through the fix-B record in both lanes. Never refuses or alters the start.
        health=_monitor_health(c,identity,None)
    phase(c,job_id,generation,'controls_installed','close_issued',close_identity=identity)
    process.close(identity)
    deadline=time.monotonic()+30
    while process.inspect() is not None:
        checkpoint(c,job_id,generation)
        if time.monotonic()>=deadline:raise ValueError('Normal close unconfirmed; no repeat close or launch')
        time.sleep(.25)
    # Order keeps fix B intact (goatai#2350 6120004490): the one-time monitor-profile migration (MT5 stopped, gate held)
    # moves aside the stray charts earlier batches left, then the record reads the monitor profile MT5 just saved, then
    # GOAT Research is reset for this batch's launch. The monitor profile is never opened again during the batch.
    migration=_migrate(c,intent['attempt_id'],process)
    monitor_chart_record=_monitor_record(c,health,intent['attempt_id'],process)
    phase(c,job_id,generation,'close_issued','research_exited')
    research_profile=_research_profile(c,intent['attempt_id'],process)
    material=validate_restart_material(c.state(),c.job(job_id),account=c.session['account'],
        monitor_path=args['monitor_path'],monitor_sha256=args['monitor_sha256'],input_schema=c.schema)
    if hashlib.sha256(startup.read_bytes()).hexdigest()!=material['startup_receipt']['sha256']:
        raise ValueError('Startup bytes changed after close')
    bridge_verify(bridge)
    phase(c,job_id,generation,'research_exited','launch_issued')
    # The batch's first /config start is a research MT5 launch (goatai#1885 PR E): created
    # suspended at low priority inside this terminal's job, or refused with nothing run. The EA's
    # own per-member relaunches stay inside that job.
    launched=research_view(process).start(startup)
    phase(c,job_id,generation,'launch_issued','process_started_unverified',process=launched)
    # The MT5 process this batch launched (pid + creation time): the end state may only close this process, or a
    # later one the EA itself relaunched for this batch (studio_research_profile.batch_end_state).
    batch_process=dict({k:(launched or {}).get(k) for k in ('pid','executable','created_utc')},source='config_start',
                       recorded_utc=datetime.now(timezone.utc).isoformat()) if isinstance(launched,dict) else None
    return dict(status='config_process_started_unverified',attempt_id=intent['attempt_id'],
                process=launched,dispatch=published,native_running_verified=False,
                research_profile=research_profile,monitor_profile_migration=migration,batch_process=batch_process,
                **({'monitor_chart_record':monitor_chart_record} if monitor_chart_record is not None else {}))


def _research_profile(c,attempt_id,process):
    """Reset GOAT Research for this batch's launch (studio_research_profile.prepare). Raises before any launch."""
    from studio_research_profile import prepare
    return prepare(c,'config-start-'+attempt_id,inspect=process.inspect)


def _migrate(c,attempt_id,process):
    """The one-time monitor-profile migration with MT5 stopped (studio_research_profile). Never raises; never refuses
    the start: a refusal leaves the monitor profile untouched and is reported in the start receipt."""
    try:
        from studio_research_profile import migrate_monitor_profile
        return migrate_monitor_profile(c,'config-start-'+attempt_id,inspect=process.inspect)
    except Exception as error:
        return dict(status='failed',reason='check_failed',detail=str(error))


def _monitor_health(c,identity,native):
    """The pre-close health read for this start's restart close (studio_onboarding.pre_close_health). Never raises."""
    try:
        from studio_onboarding import driver_pre_close_health
        from studio_research_profile import pending_set_aside
        return driver_pre_close_health(c,identity,native=native,expected_batch_ongoing=True,revision_may_lag=True,
                                       set_aside=pending_set_aside(c))
    except Exception as error:   # recording is evidence only: it never changes the start
        return dict(healthy=False,reason='check_failed',detail=str(error))


def _monitor_record(c,health,attempt_id,process):
    """After the restart close stopped MT5: record its post-close monitor chart (fix B). Never raises."""
    try:
        from datetime import datetime,timezone
        from studio_onboarding import record_post_close_chart
        return record_post_close_chart(c,health,attempt_id=attempt_id,method='config_restart_close',source='config-start',
                                       stopped_utc=datetime.now(timezone.utc).isoformat(),process=process)
    except Exception as error:
        return dict(status='not_recorded',reason='check_failed',detail=str(error))
