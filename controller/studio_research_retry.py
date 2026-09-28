"""One exact-plan continuation after positively verified pre-start cancellation.

No start replay, queue removal, new authority or budget reset. Uncertain native
evidence refuses. These are local controller guards, not an MT5 wire extension.
"""
import hashlib
import math
from pathlib import Path
import time

from campaign_ledger import packed, sha
from studio_handover import safe_path
from studio_installation import read_json
from studio_dispatch_observe import observe_dispatch
from studio_native_observe import observe


def predecessor(db, state, scope, *, successor_id=None, require_released=True):
    jobs=state['queue']
    # Deliberately one replacement total. A cancelled replacement cannot form
    # an unattended retry loop or authorize another job.
    if successor_id is None:
        if len(jobs)!=1: raise ValueError('Frozen research may be queued once, with at most one verified replacement')
        old=jobs[0]
    else:
        if len(jobs)!=2 or jobs[1]['job_id']!=successor_id:
            raise ValueError('Only the single retained replacement may start')
        old=jobs[0]
        if jobs[1]['configuration_sha256']!=scope['configuration_sha256']:
            raise ValueError('Replacement configuration changed')
    if old['status']!='cancelled' or sha(old['configuration'])!=scope['configuration_sha256'] or old['configuration_sha256']!=scope['configuration_sha256']:
        raise ValueError('Frozen research may be queued once; predecessor must be the exact frozen cancelled job')
    root=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    gate=Path(db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()[0])
    intent=old['launch_intent']; attempt=intent['attempt_id']
    start=observe_dispatch(gate,attempt)
    if start.get('consumed') is not False or start.get('status')!='receipt_observed' or start['receipt']['status']!='REQUEST_REJECTED':
        raise ValueError('Predecessor start must have exact unconsumed pre-start rejection')
    issued=read_json(safe_path(gate/('issued-'+attempt+'.json')))
    request=issued['request']
    if (request.get('action','start')!='start' or request['expires_utc']>=time.time()
            or request['job_id']!=old['job_id'] or request['configuration_sha256']!=scope['configuration_sha256']
            or request['generation']!=scope['generation']
            or {k:request[k] for k in ('terminal_id','run_id')}!=scope['binding']):
        raise ValueError('Predecessor start scope or expiry changed')
    from studio_cancel_successor import cancel_id as current_cancel_id
    cancel_id=current_cancel_id(root,old,gate)
    cancel=observe_dispatch(gate,cancel_id)
    if cancel.get('consumed') is not True or cancel.get('status')!='receipt_observed' or cancel['receipt']['status']!='CANCELLED_RECONCILE':
        raise ValueError('Exact consumed CANCELLED_RECONCILE required')
    cancel_request=read_json(safe_path(gate/('issued-'+cancel_id+'.json')))['request']
    if (cancel_request.get('action')!='cancel' or cancel_request.get('attempt_id')!=attempt
            or any(cancel_request.get(k)!=request[k] for k in ('terminal_id','run_id','job_id','generation','configuration_sha256'))):
        raise ValueError('Cancellation scope differs from predecessor')
    package=safe_path(root/'packages'/old['job_id'])
    if Path(intent['package']).resolve()!=package or hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()!=intent['package_sha256']:
        raise ValueError('Predecessor package changed')
    native=observe(package)
    count=len(old['configuration']['batch_members'])
    if native['status']!='native_cancelled' or native['member_count']!=count or native['status_counts']!={'native_cancelled':count}:
        raise ValueError('Every original native member must be cancelled without work')
    result_path=safe_path(root/'attempts'/attempt/'result.json')
    result=read_json(result_path)
    transaction=read_json(safe_path(result_path.parent/'transaction.json'))
    if (Path(old['completion_path']).resolve()!=result_path or result!=old['completion']
            or result['status']!='cancelled' or result['attempt_id']!=attempt or result['job_id']!=old['job_id']
            or result['configuration']!=old['configuration'] or result['configuration_sha256']!=scope['configuration_sha256']
            or result['package_sha256']!=intent['package_sha256'] or result.get('reports') is not None
            or result['native']['status_counts']!={'native_cancelled':count}
            or transaction['phase']!='restored' or transaction['owner']!=attempt):
        raise ValueError('Predecessor canonical finish/restoration proof differs')
    # Any produced report/export means this is not an unstarted replacement.
    from studio_report_paths import report_paths
    manifest=read_json(package/'manifest.json');plan=read_json(package/'studio-plan.json')
    paths=report_paths(plan,manifest)
    for run in (paths['local_run'],paths['common_run']):
        for folder in ('reports','Exports','exports'):
            target=safe_path(run/folder)
            if target.exists() and any(p.is_file() for p in target.rglob('*')):
                raise ValueError('Predecessor has work output; replacement refused')
    journal_path=safe_path(root/'batch-drivers'/(old['job_id']+'.json'))
    journal=read_json(journal_path); binding=journal['binding']
    if (journal.get('schema_version')!=2 or journal.get('status')!='cancelled' or journal.get('stopped') is not True
            or journal.get('start_issued') is not True or journal.get('attempt_id')!=attempt
            or binding['job_id']!=old['job_id'] or binding['generation']!=scope['generation']
            or any(binding[k]!=scope['binding'][k] for k in ('terminal_id','run_id'))
            or binding['configuration_sha256']!=scope['configuration_sha256']
            or binding['installation_sha256']!=scope['installation_sha256']
            or binding['session_sha256']!=sha(read_json(root/'session.json'))
            or binding['package_sha256']!=intent['package_sha256']
            or type(journal.get('max_seconds')) is not int or not 1<=journal['max_seconds']<=86400
            or type(journal.get('min_free_bytes')) is not int or journal['min_free_bytes']<=0
            or any(type(journal.get(k)) not in (int,float) or not math.isfinite(journal[k]) for k in ('started_wall','deadline_wall','last_wall'))
            or journal['deadline_wall']!=journal['started_wall']+journal['max_seconds']):
        raise ValueError('Original driver must be verifiably stopped with its original budget')
    if not journal['last_wall']<=time.time()<journal['deadline_wall']:
        raise ValueError('Original research deadline elapsed or clock moved backwards')
    if require_released:
        from studio_native_gate import assert_clear_controls
        settled=assert_clear_controls(db,gate)
        if settled.get('attempt_id')!=attempt or settled.get('request_id')!=cancel_id:
            raise ValueError('Exact predecessor controls must be released')
        from native_control_transaction import NAMES, contents, digest
        base=safe_path(Path(transaction['base']))
        if (base/'agent-native-control-owner.json').exists() or any(digest(contents(base/n))!=transaction['files'][n]['before_sha256'] for n in NAMES):
            raise ValueError('Released native controls changed')
    return dict(predecessor_job_id=old['job_id'],predecessor_attempt_id=attempt,
                plan_sha256=scope['plan_sha256'],configuration_sha256=scope['configuration_sha256'],
                started_wall=journal['started_wall'],deadline_wall=journal['deadline_wall'],
                max_seconds=journal['max_seconds'],min_free_bytes=journal['min_free_bytes'],
                predecessor_result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                predecessor_driver_sha256=hashlib.sha256(journal_path.read_bytes()).hexdigest())


def inherited_budget(controller, job_id):
    if controller.session.get('authority_kind')!='research_continuation':return None
    from studio_research_authority import authority
    state=controller.state()
    scope=authority(controller.store.db,packed(dict(terminal_id=controller.terminal,run_id=controller.run)),state)
    if len(state['queue'])==1:return None
    return predecessor(controller.store.db,state,scope,successor_id=job_id)
