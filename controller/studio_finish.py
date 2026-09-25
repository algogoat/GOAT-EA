"""Release an observed finished native attempt, retaining all result evidence."""
import hashlib
from pathlib import Path
from campaign_ledger import packed,sha
from studio_installation import read_json
from studio_native_observe import observe
from studio_report_observe import observe_reports
from studio_native_gate import exclusive_gate
from native_control_transaction import restore,NAMES,contents,digest
from studio_bridge import write_json

def finish(controller,job_id):
    job=controller.job(job_id)
    if job['status'] in ('completed','cancelled','failed'):
        return dict(status=job['status'],result=job.get('completion'),reused=True)
    if 'launch_intent' not in job: raise ValueError('No native attempt to finish')
    intent=job['launch_intent'];package=Path(intent['package'])
    if sha(job['configuration'])!=job['configuration_sha256']:
        raise ValueError('Frozen job configuration changed')
    if hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()!=intent['package_sha256']:
        raise ValueError('Frozen package changed')
    native=observe(package)
    outcomes={'native_completed':'completed','native_cancelled':'cancelled','native_error':'failed'}
    if native['status'] not in outcomes: raise ValueError('Native queue is not finished; reconcile, do not reset')
    completed_members=any(member['status']=='native_completed' for member in native['members'])
    reports=observe_reports(package,job['configuration'],controller.schema,member_statuses=[member['status'] for member in native['members']]) if completed_members else None
    if reports and reports['status'] not in ('report_pair_verified','report_batch_verified'):
        raise ValueError('Completed queue members still require verified report pairs')
    result=dict(schema_version=1,member_outcomes=native['members'],attempt_id=intent['attempt_id'],job_id=job_id,status=outcomes[native['status']],
                configuration_sha256=job['configuration_sha256'],configuration=job['configuration'],native=native,reports=reports,
                source=read_json(controller.root/'packages'/(job_id+'.source.json')),
                package_sha256=intent['package_sha256'],
                performance_qualification='Native artifacts observed; portfolio evidence is independently validated on import',
                matrix_result_required=True,ea_version=controller.install['ea_version'],ea_sha256=controller.install['ea_sha256'],
                controller_version=controller.install['controller_version'],account_server=controller.session['account']['server'])
    evidence=controller.root/'attempts'/intent['attempt_id']
    gate=controller.local/'native-gate'
    # Same gate excludes controller commits and native command consumption.
    with exclusive_gate(gate):
        controller.runtime(require_idle=True,expected_batch_ongoing=False)
        state=controller.state();current=controller.job(job_id)
        if state['owner']!='agent' or current.get('launch_intent')!=intent: raise ValueError('Attempt ownership changed')
        transaction=read_json(evidence/'transaction.json')
        if transaction['phase']!='restored':
            base=Path(transaction['base'])
            # Before releasing, require the active pointer to still address this run.
            from studio_native_request import ini_sections
            pointer=ini_sections((base/'active_optimization_run.ini').read_bytes())
            manifest=read_json(package/'manifest.json')
            if pointer!={'ActiveOptimizationRun':{'RunPath':manifest['native_run_relative']}}:
                raise ValueError('Native pointer changed; cannot release another run')
            restore(evidence,{name:digest(contents(base/name)) for name in NAMES})
        (gate/'permit.json').unlink(missing_ok=True)
        # Filesystem receipt precedes the database finalization; interrupted
        # completion can replay from the restored transaction without relaunch.
        result_path=evidence/'result.json';write_json(result_path,result)
        controller.store.db.execute('BEGIN IMMEDIATE')
        try:
            current=next(j for j in state['queue'] if j['job_id']==job_id)
            current.update(status=result['status'],completion=result,completion_path=str(result_path))
            binding=packed(dict(terminal_id=controller.terminal,run_id=controller.run))
            controller.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
            controller.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
            controller.store.db.execute('COMMIT')
        except BaseException:
            controller.store.db.execute('ROLLBACK');raise
    controller.bridge.pump()
    return dict(status=result['status'],result_path=str(result_path),result=result)
