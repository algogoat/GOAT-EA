"""Internal open-terminal activation: installs controls, never arms or starts MT5.

Caller holds the controller native gate and verifies all terminal batch ownership
through validate_ownership. The callback must reject unknown or armed terminals;
process inventory alone is insufficient. No public CLI until runner integration.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
from native_control_transaction import begin,NAMES
from studio_native_inventory import inventory
from studio_native_request import validate_launch_material,validate_activated_job,validate_restart_controls
from studio_process_check import revalidate_processes
from studio_report_paths import report_paths


def activate_open(state,job,**arguments):
    if 'restart_intent' in job:
        raise ValueError('Restart route already selected; open activation forbidden')
    return _install_controls(state,job,restart=False,**arguments)


def _install_controls(state,job,*,restart,account,observation_path,monitor_path,monitor_sha256,
                      evidence,process_baseline,validate_ownership,input_schema):
    if job['status']!='starting':raise ValueError('Retained starting attempt required')
    if (job['reservation']['owner'],job['reservation']['generation'])!=(state['owner'],state['generation']):
        raise ValueError('Reservation authority revoked')
    args=dict(account=account,observation_path=observation_path,monitor_path=monitor_path,monitor_sha256=monitor_sha256,input_schema=input_schema)
    material=validate_launch_material(state,job,**args)
    package,manifest,plan=(material[k] for k in ('package','manifest','plan'))
    binding=plan['research_binding'];server=account['server']
    processes=revalidate_processes(binding,process_baseline)
    if restart:
        prior=job.get('restart_intent')
        if not prior or prior['phase']!='prepared' or prior['attempt_id']!=job['launch_intent']['attempt_id']:
            raise ValueError('Prepared restart attempt required')
        if prior['startup_sha256']!=material['startup_receipt']['sha256'] or prior['account']!=dict(login=str(account['login']),server=server):
            raise ValueError('Restart configuration or account changed')
        if any(prior['process_baseline'][role]!=processes[role] for role in ('research','protected')):
            raise ValueError('Terminal identity changed after preparation')
    common=Path(binding['common_files_root']).resolve();base=common/'GOAT'/('GOAT V'+binding['ea_version']+'-'+server)
    before=inventory(common,server,binding['ea_version'])
    if before['controls']['agent-native-control-owner.json'] is not None:
        raise ValueError('Existing native owner requires reconciliation')
    if before['queue'] and (before['queue'].get('status')=='missing' or before['queue'].get('unresolved')):
        raise ValueError('Existing unresolved native queue must be reconciled')
    validate_ownership(binding,before)
    relative=manifest['native_run_relative'];alias=manifest['jobs'][0]['run_alias']
    run=common/relative.replace('\\','/');evidence=Path(evidence).resolve()
    if run.exists() or evidence.exists():raise ValueError('Existing activation requires reconciliation')
    all_reports=[report_paths(plan,manifest,index) for index in range(len(manifest['jobs']))]
    reports=all_reports[0]
    if reports['local_run'].exists():raise ValueError('Existing local report run requires reconciliation')
    raw_queue=(package/'queue.GOAT').read_bytes().decode('utf-16')
    if raw_queue.count(';Pending_')!=len(manifest['jobs']) or ';OnGoing_' in raw_queue or ';Queued_' in raw_queue:
        raise ValueError('Only an untouched complete native batch package is accepted')
    queue=raw_queue.replace(';Pending_',';Queued_',1)
    title=queue.strip().splitlines()[0].strip(';')
    owner=job['launch_intent']['attempt_id']
    pointer='[ActiveOptimizationRun]\r\nRunPath='+relative+'\r\n'
    config=(package/(alias+'.ini')).read_bytes()
    guard='[ActiveOptimizationLaunch]\r\n'+''.join(k+'='+v+'\r\n' for k,v in dict(
        LaunchId=owner,RunPath=relative,ConfigPath='GOAT\\GOAT V'+binding['ea_version']+'-'+server+'\\active_optimization_config.ini',
        AuditConfigPath=relative+'\\inputs\\'+alias+'\\config.ini',QueuedTitle=title,
        Symbol=job['configuration']['tester']['Symbol'],Strategy=alias).items())
    replacements=dict(zip(NAMES,[pointer.encode('utf-16'),config,guard.encode('utf-16')]))
    expected={name:None if before['controls'][name] is None else before['controls'][name]['sha256'] for name in NAMES}
    # All validation above precedes creation. A partially created run is retained
    # on any failure; subsequent calls refuse it rather than silently retrying.
    # MT5 requires the destination folder to exist before writing its XML.
    # Reserve the entire unique local run: stale/colliding reports never mix.
    reports['local_run'].mkdir(parents=True,exist_ok=False)
    for member_reports in all_reports:
        member_reports['local_back'].parent.mkdir(parents=True,exist_ok=False)
    shutil.copytree(package,run)
    for member_reports in all_reports:
        member_reports['common_back'].parent.mkdir(parents=True,exist_ok=True)
    (run/'queue.GOAT').write_bytes(queue.encode('utf-16'))
    batch=(package/'portfolio.goatbatch').read_bytes().decode('utf-16')
    (run/'portfolio.goatbatch').write_bytes(batch.replace(';Pending_',';Queued_',1).encode('utf-16'))
    for item in manifest['jobs']:
        (run/'inputs'/item['run_alias']/'config.ini').write_bytes((package/(item['run_alias']+'.ini')).read_bytes())
    base.mkdir(parents=True,exist_ok=True)
    transaction=begin(base,evidence,replacements,expected,owner)
    validator=validate_restart_controls if restart else validate_activated_job
    fields=validator(state,job,evidence=evidence,**args)
    receipt=dict(stage='CONTROLS_INSTALLED_NOT_ARMED',attempt_id=owner,run=str(run),
        report_destinations={key:str(value) for key,value in reports.items()},
        member_report_destinations=[{key:str(value) for key,value in member.items()} for member in all_reports],
        observed_at=datetime.now(timezone.utc).isoformat(),transaction_phase=transaction['phase'],
        request_fields_sha256=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest())
    (evidence/'activation.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return fields
