"""One exact-plan successor after a consumed settings refusal with no research.

Read-only proof. It never retires a request, edits the native queue, changes a
grant, or resets a prior driver. The next prepare/reserve/start path rechecks it.
"""
import hashlib
import math
from pathlib import Path
import time

from campaign_ledger import sha
from studio_cancel_successor import cancel_id
from studio_dispatch_observe import observe_dispatch
from studio_handover import safe_path
from studio_installation import read_json
from studio_native_gate import assert_clear_controls
from studio_native_observe import observe
from studio_report_paths import report_paths


def _digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def proof(c,state,scope,first_proof,*,successor_id=None,require_released=True):
    jobs=state['queue']
    if len(jobs) not in (2,3) or (successor_id is None and len(jobs)!=2) or (
            successor_id is not None and (len(jobs)!=3 or jobs[2]['job_id']!=successor_id)):
        raise ValueError('Only one successor of the consumed replacement is allowed')
    job=jobs[1]
    if (job['status']!='cancelled' or job['configuration_sha256']!=scope['configuration_sha256']
            or sha(job['configuration'])!=scope['configuration_sha256']
            or (successor_id is not None and jobs[2]['configuration_sha256']!=scope['configuration_sha256'])):
        raise ValueError('Only one new-epoch successor of an exact cancelled replacement is allowed')
    intent=job['launch_intent'];attempt=intent['attempt_id'];gate=c.local/'native-gate'
    package=safe_path(c.root/'packages'/job['job_id'])
    if (Path(intent['package']).resolve()!=package
            or _digest(package/'manifest.json')!=intent['package_sha256']):
        raise ValueError('Consumed replacement package identity changed')
    start=observe_dispatch(gate,attempt)
    issued=read_json(safe_path(gate/('issued-'+attempt+'.json')))['request']
    if (start.get('status')!='receipt_observed' or start.get('consumed') is not True
            or start.get('retry_permitted') is not False
            or start['receipt']['status']!='SETTINGS_NOT_VERIFIED'
            or issued.get('action','start')!='start' or issued['request_id']!=attempt
            or issued['job_id']!=job['job_id'] or issued['generation']!=scope['generation']
            or issued['configuration_sha256']!=scope['configuration_sha256']
            or issued['expires_utc']>=time.time()
            or {k:issued[k] for k in ('terminal_id','run_id')}!=scope['binding']):
        raise ValueError('Exact consumed, non-retriable settings refusal required')
    activation=read_json(safe_path(c.root/'attempts'/attempt/'activation.json'))
    if (activation.get('stage')!='CONTROLS_INSTALLED_NOT_ARMED' or activation.get('attempt_id')!=attempt
            or any((gate/(prefix+attempt+'.json')).exists() for prefix in ('start-intent-','arm-intent-'))):
        raise ValueError('Consumed replacement may have armed research')
    stop_id=cancel_id(c.root,job,gate)
    cancel=observe_dispatch(gate,stop_id)
    cancel_request=read_json(safe_path(gate/('issued-'+stop_id+'.json')))['request']
    if (cancel.get('status')!='receipt_observed' or cancel.get('consumed') is not True
            or cancel['receipt']['status']!='CANCELLED_RECONCILE'
            or cancel_request.get('action')!='cancel' or cancel_request.get('attempt_id')!=attempt
            or any(cancel_request.get(k)!=issued[k] for k in ('terminal_id','run_id','job_id','generation','configuration_sha256'))):
        raise ValueError('Exact consumed cancellation of refused attempt required')
    result_path=safe_path(c.root/'attempts'/attempt/'result.json')
    result=read_json(result_path);tx=read_json(result_path.parent/'transaction.json')
    count=len(job['configuration']['batch_members'])
    if (Path(job['completion_path']).resolve()!=result_path or result!=job['completion']
            or result['status']!='cancelled' or result['attempt_id']!=attempt
            or result['job_id']!=job['job_id'] or result['configuration']!=job['configuration']
            or result['configuration_sha256']!=scope['configuration_sha256']
            or result['package_sha256']!=intent['package_sha256'] or result.get('reports') is not None
            or result['native']['status']!='native_cancelled'
            or result['native']['status_counts']!={'native_cancelled':count}
            or len(result['member_outcomes'])!=count
            or any(item['status']!='native_cancelled' for item in result['member_outcomes'])
            or tx['phase']!='restored' or tx['owner']!=attempt):
        raise ValueError('Canonical cancelled finish or restored controls changed')
    native=observe(package)
    if (native['status']!='native_cancelled' or native['member_count']!=count
            or native['status_counts']!={'native_cancelled':count}):
        raise ValueError('Native replacement has work or changed members')
    manifest=read_json(package/'manifest.json');plan=read_json(package/'studio-plan.json')
    paths=report_paths(plan,manifest);local=safe_path(paths['local_run'])
    if local.exists() and any(safe_path(p).is_file() for p in local.rglob('*')):
        raise ValueError('Consumed replacement has local work output')
    expected={p.relative_to(package).as_posix():_digest(p) for p in package.rglob('*') if p.is_file()}
    for item in manifest['jobs']:
        expected['inputs/'+item['run_alias']+'/config.ini']=_digest(package/(item['run_alias']+'.ini'))
    expected['portfolio.goatbatch']=hashlib.sha256((package/'portfolio.goatbatch').read_bytes()
        .decode('utf-16').replace(';Pending_',';Queued_',1).encode('utf-16')).hexdigest()
    expected['queue.GOAT']=native['artifacts'][0]['sha256']
    common=safe_path(paths['common_run'])
    actual={p.relative_to(common).as_posix():_digest(p) for p in common.rglob('*') if p.is_file()}
    if actual!=expected:raise ValueError('Consumed replacement has work artifacts or changed native material')
    cache=safe_path(Path(plan['research_binding']['research_data_root'])/'Tester/cache')
    if cache.exists() and any(safe_path(p).is_file() and p.stat().st_mtime>=scope['created_utc'] for p in cache.rglob('*')):
        raise ValueError('Tester cache has work artifacts since the genuine grant')
    journal_path=safe_path(c.root/'batch-drivers'/(job['job_id']+'.json'))
    journal=read_json(journal_path);binding=journal['binding']
    if (journal.get('schema_version')!=2 or journal.get('status')!='cancelled' or journal.get('stopped') is not True
            or journal.get('cancel_reason')!='disk_low' or journal.get('cancel_issued') is not True
            or journal.get('start_issued') is not True or journal.get('attempt_id')!=attempt
            or journal.get('fresh_authority_budget')!=first_proof
            or journal.get('result_path')!=str(result_path)
            or binding['job_id']!=job['job_id'] or binding['generation']!=scope['generation']
            or any(binding[k]!=scope['binding'][k] for k in ('terminal_id','run_id'))
            or binding['configuration_sha256']!=scope['configuration_sha256']
            or binding['installation_sha256']!=scope['installation_sha256']
            or binding['package_sha256']!=intent['package_sha256']
            or binding['session_sha256']!=sha(read_json(c.root/'session.json'))
            or type(journal.get('max_seconds')) is not int or journal['max_seconds']!=scope['renewal']['max_seconds']
            or type(journal.get('min_free_bytes')) is not int or journal['min_free_bytes']<scope['renewal']['min_free_bytes']
            or any(type(journal.get(k)) not in (int,float) or not math.isfinite(journal[k])
                   for k in ('started_wall','deadline_wall','last_wall'))
            or journal['deadline_wall']!=journal['started_wall']+journal['max_seconds']
            or not scope['created_utc']<=journal['started_wall']<=journal['last_wall']<journal['deadline_wall']):
        raise ValueError('Stopped replacement driver or original budget evidence changed')
    if require_released:
        settled=assert_clear_controls(c.store.db,gate)
        if settled.get('request_id')!=stop_id or settled.get('attempt_id')!=attempt:
            raise ValueError('Consumed replacement controls are not released')
    return dict(fresh_native_epoch=True,authority_sha256=sha(scope),generation=scope['generation'],
        authority_expires_utc=scope['expires_utc'],
        predecessor_job_id=job['job_id'],predecessor_attempt_id=attempt,
        predecessor_result_sha256=_digest(result_path),predecessor_driver_sha256=_digest(journal_path),
        consumed_start_sha256=_digest(gate/('consumed-'+attempt+'.json')),
        cancelled_request_sha256=_digest(gate/('consumed-'+stop_id+'.json')),
        first_retirement_sha256=first_proof['retirement_sha256'],
        max_seconds=scope['renewal']['max_seconds'],min_free_bytes=scope['renewal']['min_free_bytes'])
