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
from studio_process_check import inspect_processes,revalidate_processes
from studio_research_authority import before_native_dispatch
from studio_seed_process import WindowsSeedProcess
from studio_seed_slot import guard_active_seed
from studio_report_bridge import prepare as bridge_prepare,verify as bridge_verify

CONFIG_START_LANES=('demo_direct','native_human_control')
RESTART_CONSENT_SCOPE='close_and_reopen_selected_mt5_for_this_batch_start'


def config_start_lane(session):
    """True for a session whose bounded driver must use the report-capable /config route."""
    return isinstance(session,dict) and session.get('authority_kind') in CONFIG_START_LANES


def require_restart_consent(c,job_id):
    """The customer lane closes the user's own MT5: their retained consent is mandatory."""
    if c.session.get('authority_kind')!='native_human_control':return None
    journal=json.loads((c.root/'batch-drivers'/(job_id+'.json')).read_text(encoding='utf-8'))
    consent=journal.get('mt5_restart_consent')
    if (not isinstance(consent,dict) or consent.get('granted') is not True
            or consent.get('scope')!=RESTART_CONSENT_SCOPE or journal.get('binding',{}).get('job_id')!=job_id):
        raise ValueError('MT5 restart consent required: tell the user GOAT will close and reopen the selected MT5 '
                         'for this batch, then start with --mt5-restart-consent')
    return consent


def sdk_idle_demo(c):
    """Broker-reported same demo, Algo OFF, zero positions/orders and idle tester (no trading calls)."""
    from studio_monitor_probe import inspect_idle_demo
    from studio_rejected_monitor import require_demo
    native=inspect_idle_demo(c)
    require_demo(native)
    return native


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
    args=c.native_args()
    c.runtime(require_idle=True,expected_batch_ongoing=False)
    before_native_dispatch(c,job)
    baseline=inspect_processes(binding)
    if customer:
        # Fresh broker proof before anything is reserved, armed or closed.
        native=sdk_idle_demo(c)
        if native.get('process')!=baseline['research']:
            raise ValueError('SDK-observed MT5 differs from the selected process; no close or launch issued')
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
    phase(c,job_id,generation,None,'prepared',startup_sha256=material['startup_receipt']['sha256'],
          process_baseline=baseline,account=dict(c.session['account']))
    def owned(bound,inventory):
        checkpoint(c,job_id,generation);revalidate_processes(bound,baseline)
        c.runtime(require_idle=True,expected_batch_ongoing=False)
    with exclusive_gate(c.local/'native-gate'):
        if resume_unissued:
            from studio_unissued_start import native_absence
            native_absence(c,c.job(job_id),package)
        arm_fields=_install_controls(c.state(),c.job(job_id),restart=True,**args,evidence=evidence,
                                     process_baseline=baseline,validate_ownership=owned)
        manifest=material['manifest']
        bridge=bridge_prepare(binding,manifest['native_run_relative'])
        write_json(evidence/'report-bridge.json',bridge)
        startup=evidence/'startup.ini'
        with startup.open('xb') as output:output.write(material['startup_raw'])
    phase(c,job_id,generation,'prepared','controls_installed',startup_path=str(startup),
          report_bridge=bridge,arm_request_fields=arm_fields)
    def validate(state,job):
        checkpoint(c,job_id,generation);revalidate_processes(binding,baseline)
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
    revalidate_processes(binding,baseline)
    process=process or WindowsSeedProcess(c)
    identity=process.inspect()
    expected=baseline['research']
    if identity is None or identity['pid']!=expected['pid']:
        raise ValueError('Selected process changed before close')
    phase(c,job_id,generation,'controls_installed','close_issued',close_identity=identity)
    process.close(identity)
    deadline=time.monotonic()+30
    while process.inspect() is not None:
        checkpoint(c,job_id,generation)
        if time.monotonic()>=deadline:raise ValueError('Normal close unconfirmed; no repeat close or launch')
        time.sleep(.25)
    phase(c,job_id,generation,'close_issued','research_exited')
    material=validate_restart_material(c.state(),c.job(job_id),account=c.session['account'],
        monitor_path=args['monitor_path'],monitor_sha256=args['monitor_sha256'],input_schema=c.schema)
    if hashlib.sha256(startup.read_bytes()).hexdigest()!=material['startup_receipt']['sha256']:
        raise ValueError('Startup bytes changed after close')
    bridge_verify(bridge)
    phase(c,job_id,generation,'research_exited','launch_issued')
    launched=process.start(startup)
    phase(c,job_id,generation,'launch_issued','process_started_unverified',process=launched)
    return dict(status='config_process_started_unverified',attempt_id=intent['attempt_id'],
                process=launched,dispatch=published,native_running_verified=False)
