"""Record fresh native evidence against one retained Studio attempt.

Internal runner API. Never releases ownership, launches, retries or qualifies
exports. Native completion holds the slot until result verification finishes.
"""
import hashlib
import json
from pathlib import Path, PureWindowsPath
from campaign_ledger import packed, sha
from studio_command_store import Conflict
from studio_native_observe import observe
from studio_runtime_check import check_runtime
from studio_dispatch_observe import observe_dispatch
from studio_report_observe import observe_reports


def reconcile(store, terminal_id, run_id, job_id, attempt_id, *, revision,
              runtime_observation=None, runtime_check_args=None):
    initial=store.snapshot(terminal_id,run_id)
    job=next((j for j in initial['queue'] if j['job_id']==job_id),None)
    if job is None or job.get('launch_intent',{}).get('attempt_id')!=attempt_id:
        raise Conflict('Existing attempt identity required')
    package=Path(job['launch_intent']['package'])
    manifest_digest=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
    if manifest_digest!=job['launch_intent']['package_sha256']:
        raise ValueError('Attempt package changed')
    native=observe(package)
    source=native['studio_source']
    if (source['terminal_id'],source['run_id'],source['job_id'])!=(terminal_id,run_id,job_id):
        raise ValueError('Native evidence belongs to another job')
    if source['configuration_sha256']!=job['configuration_sha256'] or sha(job['configuration'])!=job['configuration_sha256']:
        raise ValueError('Attempt configuration changed')
    # Runtime feedback is optional: absence/uncertainty cannot establish running.
    runtime=None
    if runtime_observation is not None:
        if not isinstance(runtime_check_args,dict):raise ValueError('Explicit trusted runtime binding required')
        plan=json.loads((package/'studio-plan.json').read_text(encoding='utf-8'))
        binding=plan['research_binding']
        if (PureWindowsPath(runtime_check_args['data_path'])!=PureWindowsPath(binding['research_data_root'])
                or PureWindowsPath(runtime_check_args['installation_path'])!=PureWindowsPath(binding['research_terminal']).parent):
            raise ValueError('Runtime binding differs from attempt terminal')
        runtime=check_runtime(runtime_observation,**runtime_check_args)
    status='reconcile_required'
    if native['status']=='native_completed':status='verifying'
    elif (native['status']=='native_ongoing' and runtime and runtime['tester_state']=='running'
          and runtime_observation['runtime']['batch_ongoing'] is True):status='running'
    gate=store.db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
    dispatch=observe_dispatch(gate[0],attempt_id) if gate else None
    reports=observe_reports(package,job['configuration'],store.input_schema) if native['status']=='native_completed' else None
    evidence=dict(native=native,reports=reports,runtime=runtime,runtime_feedback=runtime_observation,dispatch=dispatch,
                  status=status,attempt_id=attempt_id)
    # Poll timestamps do not create endless queue revisions. Preserve the actual
    # evidence timestamp of each changed observation, not synthetic progress.
    comparable=json.loads(packed(evidence))
    comparable['native'].pop('observed_at',None)
    if comparable['runtime_feedback'] is not None:
        comparable['runtime_feedback'].pop('observed_terminal_utc',None)
    evidence_hash=sha(comparable)
    with store.transaction():
        state=store.snapshot(terminal_id,run_id)
        current=next((j for j in state['queue'] if j['job_id']==job_id),None)
        if state['revision']!=revision or current is None or current.get('launch_intent',{}).get('attempt_id')!=attempt_id:
            raise Conflict('Controller or attempt changed during observation')
        if current['status'] not in ('starting','running','reconcile_required','verifying'):
            raise Conflict('Attempt is not awaiting native reconciliation')
        if current.get('native_evidence_sha256')==evidence_hash:
            return dict(changed=False,status=current['status'],revision=state['revision'])
        current.setdefault('native_evidence_history',[]).append(evidence)
        current.update(status=status,native_evidence_sha256=evidence_hash,native_observation=evidence)
        binding=packed(dict(terminal_id=terminal_id,run_id=run_id))
        store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
        store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
        return dict(changed=True,status=status,revision=state['revision']+1,launch_permitted=False)
