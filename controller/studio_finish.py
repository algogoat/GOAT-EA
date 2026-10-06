"""Release an observed finished native attempt, retaining all result evidence."""
import hashlib
from pathlib import Path
from campaign_ledger import packed,sha
from studio_installation import read_json
from studio_native_observe import observe
from studio_report_observe import observe_reports
from studio_native_gate import exclusive_gate,_read_gate_evidence
from native_control_transaction import restore,NAMES,contents,digest
from studio_bridge import write_json

def _research_outcomes(native):
    """([outcome per no-edge member], error or None). Read-only; never blocks a finish."""
    from studio_research_status import below_score_sets,no_edge_members,no_edge_summary,timeline
    try:
        members=native['members'];run=native['native_run']
        found=no_edge_members(run,[(m['run_alias'],m['symbol']) for m in members],[m['status'] for m in members],
                              timeline(run,[m['run_alias'] for m in members]))
        return [dict(index=i,run_alias=members[i]['run_alias'],symbol=members[i]['symbol'],timeframe=members[i]['tester']['Period'],
                     **found[i],summary=no_edge_summary(members[i]['symbol'],members[i]['tester']['Period'],found[i]),
                     below_score_sets=below_score_sets(found[i]))   # recorded as metrics.belowScoreSets (step 20)
                for i in sorted(found)],None
    except (OSError,ValueError,KeyError,TypeError) as error:
        return [],str(error)[:240]

def finish(controller,job_id,*,expected_generation=None):
    if expected_generation is not None and controller.state()['generation']!=expected_generation:
        raise ValueError('Controller generation changed before finish')
    job=controller.job(job_id)
    if job['status'] in ('completed','cancelled','failed'):
        reused=dict(status=job['status'],result_path=job.get('completion_path'),result=job.get('completion'),reused=True)
        if (job.get('completion') or {}).get('native_error_evidence') is not None:
            reused['native_error_evidence']=job['completion']['native_error_evidence']
        return reused
    if 'launch_intent' not in job: raise ValueError('No native attempt to finish')
    intent=job['launch_intent'];package=Path(intent['package'])
    if sha(job['configuration'])!=job['configuration_sha256']:
        raise ValueError('Frozen job configuration changed')
    if hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()!=intent['package_sha256']:
        raise ValueError('Frozen package changed')
    native=observe(package)
    from studio_cancel_successor import cancel_id
    from studio_dispatch_observe import observe_dispatch
    stop_id=cancel_id(controller.root,job,controller.local/'native-gate')
    successor_stop=None
    signal_only=False
    if stop_id!=sha([intent['attempt_id'],'cancel']):
        successor_stop=observe_dispatch(controller.local/'native-gate',stop_id)
        receipt=successor_stop.get('receipt') or {}
        # A cancel consumed mid-member answers CANCEL_SIGNAL_SENT_RECONCILE when the
        # tester takes longer than the EA's single 100 ms idle check to stop (g6,
        # 19:18Z): the stop was sent, not yet confirmed. It is accepted only with the
        # same independent proof the release already demands below: a settled native
        # queue and, under the gate, a fresh idle tester with no batch ongoing.
        if (successor_stop.get('consumed') is not True or successor_stop.get('status')!='receipt_observed'
                or receipt.get('status') not in ('CANCELLED_RECONCILE','CANCEL_SIGNAL_SENT_RECONCILE')):
            raise ValueError('Successor cancellation requires its exact consumed CANCELLED_RECONCILE '
                             'or CANCEL_SIGNAL_SENT_RECONCILE')
        signal_only=receipt['status']=='CANCEL_SIGNAL_SENT_RECONCILE'
    outcomes={'native_completed':'completed','native_cancelled':'cancelled','native_error':'failed'}
    if native['status'] not in outcomes: raise ValueError('Native queue is not finished; reconcile, do not reset')
    completed_members=any(member['status']=='native_completed' for member in native['members'])
    reports=observe_reports(package,job['configuration'],controller.schema,member_statuses=[member['status'] for member in native['members']]) if completed_members else None
    if reports and reports['status'] not in ('report_pair_verified','report_batch_verified'):
        raise ValueError('Completed queue members still require verified report pairs')
    research_outcomes,research_error=_research_outcomes(native)
    result=dict(schema_version=1,member_outcomes=native['members'],attempt_id=intent['attempt_id'],job_id=job_id,status=outcomes[native['status']],
                configuration_sha256=job['configuration_sha256'],configuration=job['configuration'],native=native,reports=reports,
                source=read_json(controller.root/'packages'/(job_id+'.source.json')),
                package_sha256=intent['package_sha256'],
                performance_qualification='Native artifacts observed; portfolio evidence is independently validated on import',
                matrix_result_required=True,ea_version=controller.install['ea_version'],ea_sha256=controller.install['ea_sha256'],
                controller_version=controller.install['controller_version'],account_server=controller.session['account']['server'])
    # Members tested with no profitable settings keep native_error; this tells the
    # scoreboard they are results for their window, not failures (studio_research_status).
    result['research_outcomes']=research_outcomes
    if research_error is not None:result['research_outcomes_error']=research_error
    if successor_stop is not None:result['cancellation_dispatch']=successor_stop
    if native['status']=='native_error':
        from studio_native_diagnostics import for_job
        # Read-only EA journal quote; it never changes the outcome or authorizes a retry.
        result['native_error_evidence']=for_job(controller,job,native,[item['index'] for item in research_outcomes])
    if signal_only:
        # Written only if the gated idle check below passes; a failure raises first.
        result['stop_confirmation']=dict(receipt='CANCEL_SIGNAL_SENT_RECONCILE',
                                         confirmed_by=['native_queue_settled','tester_idle_under_gate','batch_ongoing_false'])
    evidence=controller.root/'attempts'/intent['attempt_id']
    gate=controller.local/'native-gate'
    # Same gate excludes controller commits and native command consumption.
    with exclusive_gate(gate):
        controller.runtime(require_idle=True,expected_batch_ongoing=False)
        state=controller.state();current=controller.job(job_id)
        if expected_generation is not None and state['generation']!=expected_generation:
            raise ValueError('Controller generation changed during finish')
        if state['owner']!='agent' or current.get('launch_intent')!=intent: raise ValueError('Attempt ownership changed')
        transaction=read_json(evidence/'transaction.json')
        if transaction['phase']!='restored':
            base=Path(transaction['base'])
            # Before releasing, require the active pointer to still address this run.
            from studio_native_request import ini_sections
            pointer=ini_sections((base/'active_optimization_run.ini').read_bytes())
            # Batch manifests use the existing 64 MiB native-evidence bound;
            # installation receipts keep their separate 2 MB limit.
            manifest=_read_gate_evidence(package/'manifest.json')[1]
            if pointer!={'ActiveOptimizationRun':{'RunPath':manifest['native_run_relative']}}:
                raise ValueError('Native pointer changed; cannot release another run')
            restore(evidence,{name:digest(contents(base/name)) for name in NAMES})
        (gate/'permit.json').unlink(missing_ok=True)
        restart=current.get('restart_intent') or {}
        if restart.get('report_bridge') is not None:
            from studio_report_bridge import retire
            receipt=read_json(evidence/'report-bridge.json')
            if receipt!=restart['report_bridge']:
                raise ValueError('Report bridge evidence changed before finish')
            plan=read_json(package/'studio-plan.json')
            manifest=_read_gate_evidence(package/'manifest.json')[1]
            if sha(plan)!=manifest['campaign_id']:
                raise ValueError('Report cleanup plan changed')
            result['report_bridge_retirement']=retire(plan['research_binding'],
                manifest['native_run_relative'],receipt,evidence)
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
    finished=dict(status=result['status'],result_path=str(result_path),result=result)
    if 'native_error_evidence' in result:finished['native_error_evidence']=result['native_error_evidence']
    return finished
