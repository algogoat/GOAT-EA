"""One new stop identity after an expired, unconsumed stop was natively rejected."""
import hashlib
from pathlib import Path
import time

from campaign_ledger import packed,sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json
from studio_dispatch_observe import observe_dispatch
from studio_native_gate import exclusive_gate


def cancel_id(root,job,gate=None):
    attempt=job['launch_intent']['attempt_id'];original=sha([attempt,'cancel'])
    path=safe_path(Path(root)/'cancel-successors'/(attempt+'.json'))
    if not path.exists():return original
    value=read_json(path)
    gate=Path(gate) if gate is not None else Path(value['gate'])
    if (value['attempt_id']!=attempt or value['job_id']!=job['job_id']
            or value['configuration_sha256']!=job['configuration_sha256'] or value['prior_request_id']!=original
            or value['request_id']!=sha([attempt,'cancel-successor',value['prior_issued_sha256']])):
        raise ValueError('Cancellation successor identity changed')
    for prefix,field in (('issued-','prior_issued_sha256'),('result-','prior_result_sha256')):
        if hashlib.sha256(safe_path(gate/(prefix+original+'.json')).read_bytes()).hexdigest()!=value[field]:
            raise ValueError('Immutable prior cancellation evidence changed')
    prior=observe_dispatch(gate,original)
    request=read_json(gate/('issued-'+original+'.json'))['request']
    if (prior.get('consumed') is not False or prior.get('status')!='receipt_observed' or prior['receipt']['status']!='CANCEL_REJECTED'
            or request['expires_utc']>=value['created_utc'] or request.get('action')!='cancel' or request.get('attempt_id')!=attempt
            or request['job_id']!=job['job_id'] or request['configuration_sha256']!=job['configuration_sha256']
            or any(request[k]!=value[k] for k in ('terminal_id','run_id','generation'))):
        raise ValueError('Exact expired unconsumed CANCEL_REJECTED required')
    return value['request_id']


def create(controller,job_id):
    from studio_research_authority import authority
    from studio_rejected_monitor import proof,require_demo
    from studio_monitor_probe import inspect_idle_demo
    job=controller.job(job_id)
    if (controller.root/'cancel-successors'/(job['launch_intent']['attempt_id']+'.json')).exists():
        raise ValueError('One cancellation successor already exists; do not issue a second')
    scope,job=proof(controller,job_id)
    attempt=job['launch_intent']['attempt_id'];gate=controller.local/'native-gate'
    recovery=read_json(controller.root/'rejected-monitor-restarts'/attempt/'restart.json')
    if recovery['phase']!='reverified' or recovery['authority_sha256']!=sha(scope):
        raise ValueError('Reverified exact monitor recovery required')
    with exclusive_gate(gate):
        state=controller.state()
        authority(controller.store.db,packed(dict(terminal_id=controller.terminal,run_id=controller.run)),state)
        if state['generation']!=scope['generation'] or state['owner']!='agent':raise ValueError('Research authority changed')
        controller.runtime(require_idle=True,expected_batch_ongoing=False)
        native=inspect_idle_demo(controller);require_demo(native)
        if native['process']!=recovery['process']:raise ValueError('Recovered monitor process changed')
        folder=safe_path(controller.root/'cancel-successors');folder.mkdir(exist_ok=True)
        path=folder/(attempt+'.json')
        if path.exists():raise ValueError('One cancellation successor already exists; do not issue a second')
        original=sha([attempt,'cancel']);prior=observe_dispatch(gate,original)
        request=read_json(gate/('issued-'+original+'.json'))['request']
        if prior.get('consumed') is not False or prior.get('status')!='receipt_observed' or prior['receipt']['status']!='CANCEL_REJECTED' or request['expires_utc']>=time.time():
            raise ValueError('Native expired unconsumed CANCEL_REJECTED required before successor')
        issued_hash=hashlib.sha256((gate/('issued-'+original+'.json')).read_bytes()).hexdigest()
        value=dict(schema_version=1,attempt_id=attempt,job_id=job_id,configuration_sha256=job['configuration_sha256'],
                   terminal_id=controller.terminal,run_id=controller.run,generation=state['generation'],
                   gate=str(gate),prior_request_id=original,prior_issued_sha256=issued_hash,
                   prior_result_sha256=hashlib.sha256((gate/('result-'+original+'.json')).read_bytes()).hexdigest(),
                   request_id=sha([attempt,'cancel-successor',issued_hash]),authority_sha256=sha(scope),
                   recovery_sha256=sha(recovery),created_utc=time.time())
        # Immutable linkage is committed before publication. An interrupted
        # publication can only publish this same stop via ordinary cancel.
        write_json(path,value)
        cancel_id(controller.root,job,gate)
    return controller.cancel(job_id,expected_generation=scope['generation'])
