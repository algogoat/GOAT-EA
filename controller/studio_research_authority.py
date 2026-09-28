"""Default-deny research continuation at the public dispatcher and store boundary.

Native owner=agent is only transport identity. Authority has its own immutable
type/provenance and never creates a human grant or any trading permission.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import time

from campaign_ledger import packed, sha
from studio_installation import read_json, load_installation

CURRENT_OPERATION = ContextVar('studio_research_operation', default=None)
DEMO_AGENT_SCOPE = ContextVar('studio_demo_agent_scope', default=None)
READ_OPERATIONS = frozenset(('discover','resource-profile','state','onboarding-status',
                             'native-recovery-status','batch-driver-status','owner-maintenance-status'))
OPERATIONS = READ_OPERATIONS | frozenset(('owner-maintenance-bootstrap','monitor-prepare','monitor-launch',
    'serve','orphan-recovery-prepare','orphan-recovery-apply','orphan-recovery-status',
    'orphan-recovery-reconcile-rejection','prepare-batch','run-batch','start','status','reconcile',
    'batch-status','cancel','finish','benchmark-report','save-batch','research-monitor-restart','research-monitor-restart-resume','research-monitor-restart-status','research-monitor-reopen-prepare','research-monitor-adopt-reopen','research-monitor-repair-derived-report','research-retire-never-started','cancel-rejected-successor'))


@contextmanager
def operation(name):
    token = CURRENT_OPERATION.set(name)
    try:
        yield
    finally:
        CURRENT_OPERATION.reset(token)


@contextmanager
def demo_agent_scope(*, root, installation_sha256, account, job_id=None):
    """Trusted local adapter scope after a fresh broker-reported demo check.

    This changes the policy for the demo lane only. It never changes the stored
    history of human grants or permits a non-demo account to enter the lane.
    """
    value = dict(root=str(Path(root).resolve()), installation_sha256=installation_sha256,
                 account=dict(account), job_id=job_id)
    token = DEMO_AGENT_SCOPE.set(value)
    try:
        yield
    finally:
        DEMO_AGENT_SCOPE.reset(token)


def require_demo_agent_scope(root, installation, session):
    scope = DEMO_AGENT_SCOPE.get()
    if (scope is None or scope['root'] != str(Path(root).resolve())
            or scope['installation_sha256'] != sha(installation)
            or session.get('installation_sha256') != scope['installation_sha256']
            or session.get('authority_kind') != 'demo_direct'
            or session.get('demo_only') is not True
            or session.get('account') != scope['account']):
        raise ValueError('Fresh broker-verified demo agent scope required')
    return scope


HUMAN_RECOVERY_OPERATIONS = READ_OPERATIONS | frozenset(('serve','cancel','switch-plan','switch-apply',
    'switch-status','switch-verify-park','monitor-stop','research-monitor-repair-revoked-report','research-regrant-status'))


def _legacy_human_grant(db, binding, state):
    """Recognize only an actor-bound archived real grant, never infer from owner."""
    from studio_handover import safe_path
    root=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    if (root/'research-authority.json').exists() or not (root/'session.json').is_file():return False
    session=read_json(root/'session.json')
    if 'authority_kind' in session:return False
    if {k:session.get(k) for k in ('terminal_id','run_id')}!=json.loads(binding):return False
    install=read_json(root/'installation.json')
    human=safe_path(Path(install['terminal_data_root'])/'MQL5/Files/GOATStudio'/session['directory_id']/'human/archive')
    for row in db.execute('SELECT request_id,payload_hash,receipt FROM studio_receipts WHERE binding=?',(binding,)):
        receipt=json.loads(row[2]); granted=receipt.get('state',{})
        if (receipt.get('command')!='control.grant_agent' or receipt.get('status')!='applied'
                or receipt.get('execution_effect') is not False or receipt.get('request_id')!=row[0]
                or granted.get('owner')!='agent' or {k:granted.get(k) for k in ('terminal_id','run_id')}!=json.loads(binding)
                or granted.get('generation',-1)>state['generation']
                or (state['owner']=='agent' and granted.get('generation')!=state['generation'])):continue
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',row[0]):continue
        files=list(human.glob(row[0]+'.*.json'))
        if len(files)!=1:continue
        request=read_json(safe_path(files[0]))
        if (request.get('command')=='control.grant_agent' and request.get('payload')=={}
                and request.get('request_id')==row[0]
                and {k:request.get(k) for k in ('terminal_id','run_id')}==json.loads(binding)
                and request.get('generation')==granted['generation']-1
                and request.get('expected_revision')==granted['revision']-1
                and sha(dict(request=request,actor='human'))==row[1]):return True
    return False


def legacy_human_grant(db, binding, state):
    try:
        return _legacy_human_grant(db,binding,state)
    except (OSError,ValueError,KeyError,TypeError):
        # Damaged evidence cannot classify an agent, but must not prevent opening
        # the trusted human takeover channel to permanently revoke it.
        return False


def authority(db, binding, state):
    if DEMO_AGENT_SCOPE.get() is not None:
        root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
        session = read_json(root / 'session.json')
        installation = read_json(root / 'installation.json')
        require_demo_agent_scope(root, installation, session)
        if {key: session.get(key) for key in ('terminal_id', 'run_id')} != json.loads(binding):
            raise ValueError('Demo agent session binding changed')
        if state['owner'] != 'agent':
            raise ValueError('Owner TAKE CONTROL wins over demo agent work')
        return None
    row = db.execute('SELECT kind,provenance FROM studio_authorities WHERE binding=?', (binding,)).fetchone()
    if row is None:
        root=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
        session=read_json(root/'session.json') if (root/'session.json').is_file() else {}
        if (root/'research-authority.json').exists() or session.get('authority_kind') is not None:
            if state['owner']=='human' and CURRENT_OPERATION.get() in HUMAN_RECOVERY_OPERATIONS:
                return dict(kind='revoked_continuation',generation=-1)
            raise ValueError('Typed agent session has no classified authority')
        if state['owner']=='agent' and not legacy_human_grant(db,binding,state):
            raise ValueError('Agent session has no classified authority; continuation is refused')
        return None
    kind, raw = row
    root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    if kind=='native_human_control':
        session=read_json(root/'session.json') if (root/'session.json').exists() else {}
        if (root/'research-authority.json').exists() or session.get('authority_kind') not in (None,'native_human_control'):
            raise ValueError('Native authority cannot downgrade a typed continuation')
        if json.loads(raw) != {'kind':'native_human_control','binding':json.loads(binding)}:
            raise ValueError('Human-channel authority provenance changed')
        return None
    if state['owner']=='human' and CURRENT_OPERATION.get() in HUMAN_RECOVERY_OPERATIONS:
        return dict(kind='revoked_continuation',generation=-1)
    if kind!='research_continuation':
        raise ValueError('Unknown authority kind; no fallback to agent control')
    value = json.loads(raw)
    root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    if read_json(root/'research-authority.json') != value:
        raise ValueError('Immutable research continuation provenance changed')
    if value.get('kind')!=kind or value.get('binding')!=json.loads(binding):
        raise ValueError('Research continuation binding changed')
    original_value=value
    if state['owner']=='agent' and state['generation']!=value['generation']:
        from studio_research_regrant import active
        value=active(db,binding,state,value)
    if (root/'continuation-revocation/revoked.json').exists() and CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve','cancel','status','reconcile','finish','batch-status'}:
        raise ValueError('Research continuation permanently revoked by pending human control')
    if state['generation']!=value['generation'] or state['owner']!='agent':
        # Readback and human takeover remain possible after permanent revocation.
        if CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve'}:
            raise ValueError('Research continuation permanently revoked by human control')
    elif not value['created_utc'] <= time.time() < value['expires_utc']:
        # The retained driver must still observe/cancel/finish its existing attempt.
        # New reservations and native dispatch separately require live authority.
        if CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve','cancel','status','reconcile','finish','batch-status','run-batch'}:
            raise ValueError('Research continuation expired; no new work')
    if CURRENT_OPERATION.get() not in OPERATIONS:
        raise ValueError('Operation is not allowlisted for research continuation')
    session = read_json(root/'session.json')
    if session.get('authority_kind')!=kind or session.get('authority_sha256')!=sha(original_value):
        raise ValueError('Required session authority kind/provenance missing or changed')
    install = load_installation(root/'installation.json')
    if sha(install)!=value['installation_sha256'] or session['account']!=value['account']:
        raise ValueError('Research continuation installation or account changed')
    return value


def command(db, binding, state, request, actor):
    if actor=='human' and request['command']=='control.takeover':return
    if DEMO_AGENT_SCOPE.get() is not None:
        scope = DEMO_AGENT_SCOPE.get()
        authority(db, binding, state)
        op = CURRENT_OPERATION.get()
        command_name = request['command']
        job_id = scope['job_id']
        if actor != 'agent' or not isinstance(job_id, str):
            raise ValueError('Demo agent scope requires an exact agent job')
        allowed = (op == 'prepare-batch' and command_name == 'queue.enqueue_batch'
                   and request['request_id'] == job_id + '-batch'
                   and request['payload'].get('job_id') == job_id) or (
                   op == 'run-batch' and command_name in ('queue.reserve', 'queue.cancel')
                   and request['request_id'] == job_id + ('-reserve' if command_name == 'queue.reserve' else '-cancel')
                   and request['payload'].get('job_id') == job_id)
        if not allowed:
            raise ValueError('Demo agent scope permits only this tool job and exact Studio command')
        return
    if actor=='human' and request['command']=='control.grant_agent':
        row=db.execute('SELECT kind FROM studio_authorities WHERE binding=?',(binding,)).fetchone()
        if row is not None and row[0]=='research_continuation':
            from studio_research_regrant import prepare
            return prepare(db,binding,state,request)
    value = authority(db, binding, state)
    if value is None:
        return
    command_name = request['command']
    if command_name.startswith('control.'):
        raise ValueError('Research continuation cannot create or promote a control grant')
    if state['owner']=='human' and actor=='human' and command_name=='queue.cancel':return
    if state['owner']!='agent' or state['generation']!=value['generation']:
        raise ValueError('Research continuation permanently revoked')
    if actor!='agent':
        raise ValueError('Human must take over before changing restricted research')
    op = CURRENT_OPERATION.get()
    if command_name=='queue.enqueue_batch' and op=='prepare-batch':
        payload = request['payload']
        if sha(payload['members'])!=value['members_sha256']:
            raise ValueError('Only the exact frozen research members may be queued once')
        if state['queue']:
            from studio_research_retry import predecessor
            predecessor(db,state,value)
        return
    if command_name=='queue.reserve' and op in ('start','run-batch'):
        if not value['created_utc'] <= time.time() < value['expires_utc']:
            raise ValueError('Research continuation expired; no new reservation')
        job = next((j for j in state['queue'] if j['job_id']==request['payload']['job_id']), None)
        if job is None or job['configuration_sha256']!=value['configuration_sha256']:
            raise ValueError('Reservation is outside the frozen research plan')
        if len(state['queue'])>1:
            from studio_research_retry import predecessor
            predecessor(db,state,value,successor_id=job['job_id'])
        return
    if command_name=='queue.cancel' and op in ('cancel','run-batch'):
        return
    raise ValueError('Command is not allowlisted for research continuation')


def dispatch(controller, args):
    """Single public CLI choke point: even future commands default to refusal."""
    if not (controller.root/'session.json').exists():
        return
    import sqlite3
    from contextlib import closing
    session = read_json(controller.root/'session.json')
    binding = packed(dict(terminal_id=session['terminal_id'],run_id=session['run_id']))
    with closing(sqlite3.connect((controller.root/'studio.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        state = db.execute('SELECT owner,generation FROM studio_state WHERE binding=?',(binding,)).fetchone()
        if state is None:
            raise ValueError('Session authority has no matching controller state')
        if 'studio_authorities' not in tables:
            if state[0]=='agent' and args.operation not in READ_OPERATIONS | {'serve'} and not legacy_human_grant(db,binding,dict(owner=state[0],generation=state[1])):
                raise ValueError('Existing agent session requires explicit authority classification')
            return
        if args.operation in ('state','serve'):
            return  # Pump only: each mutation still checks the store authority.
        value = authority(db,binding,dict(owner=state[0],generation=state[1]))
        if value is not None and state[0]=='agent' and getattr(args,'confirm_reviewed',False):
            raise ValueError('Typed continuation forbids human-confirmation flags; use owner-research')
        if value is not None and args.operation=='prepare-batch':
            from studio_batch import _json
            _,raw=_json(args.plan,with_raw=True)
            if hashlib.sha256(raw).hexdigest()!=value['plan_sha256']:
                raise ValueError('Only the exact frozen research plan is authorized')


def before_native_dispatch(controller, job):
    binding = packed(dict(terminal_id=controller.terminal,run_id=controller.run))
    value = authority(controller.store.db,binding,controller.state())
    if value is not None:
        if not value['created_utc'] <= time.time() < value['expires_utc']:
            raise ValueError('Research continuation expired; no native dispatch')
        if job['configuration_sha256']!=value['configuration_sha256']:
            raise ValueError('Native dispatch differs from frozen research configuration')
        if CURRENT_OPERATION.get()!='run-batch':
            raise ValueError('Typed research start requires the live bounded run-batch driver')
        journal=read_json(controller.root/'batch-drivers'/(job['job_id']+'.json'))
        if (journal.get('status')!='start_issued' or journal.get('start_issued') is not True
                or journal.get('attempt_id') is not None or journal.get('binding',{}).get('job_id')!=job['job_id']):
            raise ValueError('Typed research requires the live driver initial start intent, never a retained failed journal')
        state=controller.state()
        if len(state['queue'])>1:
            from studio_research_retry import predecessor
            inherited=predecessor(controller.store.db,state,value,successor_id=job['job_id'],require_released=job['status']=='pending')
            if inherited.get('fresh_native_epoch'):
                capped='authority_expires_utc' in inherited
                valid_seconds=(type(journal.get('max_seconds')) is int and
                    (1<=journal['max_seconds']<=inherited['max_seconds'] if capped else journal['max_seconds']==inherited['max_seconds']))
                if (journal.get('fresh_authority_budget')!=inherited or not valid_seconds
                        or journal['started_wall']<value['created_utc'] or journal['deadline_wall']!=journal['started_wall']+journal['max_seconds']
                        or (capped and (inherited['authority_expires_utc']!=value['expires_utc']
                            or journal['deadline_wall']>value['expires_utc']))
                        or journal['min_free_bytes']<inherited['min_free_bytes'] or time.time()>=journal['deadline_wall']):
                    raise ValueError('Replacement requires its new native epoch budget and disk reserve')
            elif (journal.get('inherited_budget')!=inherited or journal['deadline_wall']!=inherited['deadline_wall']
                    or journal['started_wall']!=inherited['started_wall'] or journal['max_seconds']!=inherited['max_seconds']
                    or journal['min_free_bytes']<inherited['min_free_bytes'] or time.time()>=journal['deadline_wall']):
                raise ValueError('Replacement requires the original bounded driver deadline and disk reserve')
        from studio_monitor_probe import inspect_idle_demo
        native = inspect_idle_demo(controller)
        if (native.get('demo') is not True or native.get('algo_trading') is not False
                or native.get('account_matches') is not True or native.get('connected') is not True
                or native.get('positions')!=0 or native.get('orders')!=0 or native.get('tester_state')!='idle'):
            raise ValueError('Research dispatch requires the same idle demo with Algo OFF and no trades')


def recovery_authorization(c, operation_name, review_id):
    if operation_name not in ('orphan-recovery-apply','orphan-recovery-reconcile-rejection'):
        raise ValueError('Continuation cannot authorize other maintenance operations')
    state=c.state()
    value=authority(c.store.db,packed(dict(terminal_id=c.terminal,run_id=c.run)),state)
    if value is None or state['owner']!='agent' or state['generation']!=value['generation']:
        raise ValueError('Current typed research continuation required')
    from studio_owner_maintenance import human_clear
    # Revocation evidence belongs to this session, never the original grant.
    audit=c.root/'continuation-revocation';audit.mkdir(exist_ok=True)
    if (audit/'revoked.json').exists():
        raise ValueError('Research continuation permanently revoked')
    human_clear(audit,c.bridge.root/'human')
    observation,_=c.runtime(require_idle=True,expected_batch_ongoing=True)
    if any(observation.get(k)!=state[k] for k in ('owner','revision','generation')):
        raise ValueError('Native monitor has not confirmed typed continuation')
    from studio_monitor_probe import inspect_idle_demo
    native=inspect_idle_demo(c)
    if (native.get('demo') is not True or native.get('connected') is not True
            or native.get('account_matches') is not True or native.get('algo_trading') is not False
            or native.get('positions')!=0 or native.get('orders')!=0 or native.get('tester_state')!='idle'):
        raise ValueError('Recovery requires the same idle demo with Algo OFF and no trades')
    human_clear(audit,c.bridge.root/'human')
    if c.state()!=state:
        raise ValueError('Typed continuation changed during native observation')
    return dict(schema_version=1,operation=operation_name,review_id=review_id,
                authority_sha256=sha(value),authorization='research_continuation',
                original_grant_request_id=value['original_grant_request_id'],
                original_grant_payload_hash=value['original_grant_payload_hash'],
                revocation_epoch=state['generation'],native=native,human_confirmation_fabricated=False)


def refuse_typed_confirmation(c, confirmed):
    if confirmed and read_json(c.root/'session.json').get('authority_kind')=='research_continuation':
        raise ValueError('Typed continuation forbids human-confirmation flags; use owner-research')
