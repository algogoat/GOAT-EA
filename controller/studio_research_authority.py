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
READ_OPERATIONS = frozenset(('discover','resource-profile','state','onboarding-status',
                             'native-recovery-status','batch-driver-status','owner-maintenance-status'))
OPERATIONS = READ_OPERATIONS | frozenset(('owner-maintenance-bootstrap','monitor-prepare','monitor-launch',
    'serve','orphan-recovery-prepare','orphan-recovery-apply','orphan-recovery-status',
    'orphan-recovery-reconcile-rejection','prepare-batch','run-batch','start','status','reconcile',
    'batch-status','cancel','finish','benchmark-report','save-batch'))


@contextmanager
def operation(name):
    token = CURRENT_OPERATION.set(name)
    try:
        yield
    finally:
        CURRENT_OPERATION.reset(token)


def authority(db, binding, state):
    row = db.execute('SELECT kind,provenance FROM studio_authorities WHERE binding=?', (binding,)).fetchone()
    if row is None:
        if state['owner']=='agent':
            raise ValueError('Agent session has no classified authority; continuation is refused')
        return None
    kind, raw = row
    if kind=='native_human_control':
        if json.loads(raw) != {'kind':'native_human_control','binding':json.loads(binding)}:
            raise ValueError('Human-channel authority provenance changed')
        return None
    if kind!='research_continuation':
        raise ValueError('Unknown authority kind; no fallback to agent control')
    value = json.loads(raw)
    root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    if read_json(root/'research-authority.json') != value:
        raise ValueError('Immutable research continuation provenance changed')
    if value.get('kind')!=kind or value.get('binding')!=json.loads(binding):
        raise ValueError('Research continuation binding changed')
    if (root/'continuation-revocation/revoked.json').exists() and CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve','cancel','status','reconcile','finish','batch-status'}:
        raise ValueError('Research continuation permanently revoked by pending human control')
    if state['generation']!=value['generation'] or state['owner']!='agent':
        # Readback and human takeover remain possible after permanent revocation.
        if CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve'}:
            raise ValueError('Research continuation permanently revoked by human control')
    elif not value['created_utc'] <= time.time() < value['expires_utc']:
        if CURRENT_OPERATION.get() not in READ_OPERATIONS | {'serve','cancel','status','reconcile','finish','batch-status'}:
            raise ValueError('Research continuation expired; no new work')
    if CURRENT_OPERATION.get() not in OPERATIONS:
        raise ValueError('Operation is not allowlisted for research continuation')
    session = read_json(root/'session.json')
    if session.get('authority_kind')!=kind or session.get('authority_sha256')!=sha(value):
        raise ValueError('Required session authority kind/provenance missing or changed')
    install = load_installation(root/'installation.json')
    if sha(install)!=value['installation_sha256'] or session['account']!=value['account']:
        raise ValueError('Research continuation installation or account changed')
    return value


def command(db, binding, state, request, actor):
    value = authority(db, binding, state)
    if value is None:
        return
    command_name = request['command']
    if actor=='human' and command_name=='control.takeover':
        return
    if command_name.startswith('control.'):
        raise ValueError('Research continuation cannot create or promote a control grant')
    if state['owner']!='agent' or state['generation']!=value['generation']:
        raise ValueError('Research continuation permanently revoked')
    if actor!='agent':
        raise ValueError('Human must take over before changing restricted research')
    op = CURRENT_OPERATION.get()
    if command_name=='queue.enqueue_batch' and op=='prepare-batch':
        payload = request['payload']
        if sha(payload['members'])!=value['members_sha256'] or state['queue']:
            raise ValueError('Only the exact frozen research members may be queued once')
        return
    if command_name=='queue.reserve' and op in ('start','run-batch'):
        job = next((j for j in state['queue'] if j['job_id']==request['payload']['job_id']), None)
        if job is None or job['configuration_sha256']!=value['configuration_sha256']:
            raise ValueError('Reservation is outside the frozen research plan')
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
            if state[0]=='agent' and args.operation not in READ_OPERATIONS:
                raise ValueError('Existing agent session requires explicit authority classification')
            return
        value = authority(db,binding,dict(owner=state[0],generation=state[1]))
        if value is not None and args.operation=='prepare-batch':
            from studio_batch import _json
            _,raw=_json(args.plan,with_raw=True)
            if hashlib.sha256(raw).hexdigest()!=value['plan_sha256']:
                raise ValueError('Only the exact frozen research plan is authorized')


def before_native_dispatch(controller, job):
    binding = packed(dict(terminal_id=controller.terminal,run_id=controller.run))
    value = authority(controller.store.db,binding,controller.state())
    if value is not None:
        if job['configuration_sha256']!=value['configuration_sha256']:
            raise ValueError('Native dispatch differs from frozen research configuration')
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
