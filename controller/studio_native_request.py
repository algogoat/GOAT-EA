from studio_resilient_read import read_observation
"""Verify an activated one-job package and construct native dispatch fields.

Call inside the dispatch gate, after the runner checks process ownership.
This verifies artifacts/runtime, not exclusion of legacy Common Files writers.
"""
import configparser
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import time
from activate_research_campaign import verify_export_policy
from campaign_ledger import sha
from studio_native_observe import observe
from studio_runtime_check import check_runtime
from studio_startup_config import startup_config
from studio_input_readback import explicit_paste_inputs
from studio_strategy_settings import read_values


def ini_sections(raw):
    text=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    parser=configparser.ConfigParser(interpolation=None,strict=True)
    parser.optionxform=str
    parser.read_string(text)
    if parser.defaults():raise ValueError('INI defaults are forbidden')
    return {section:dict(parser[section]) for section in parser.sections()}


def validate_launch_material(state, job, *, account, observation_path,
                             monitor_path, monitor_sha256, input_schema):
    return _runtime_material(state,job,account=account,observation_path=observation_path,
        monitor_path=monitor_path,monitor_sha256=monitor_sha256,input_schema=input_schema,
        expected_batch_ongoing=False)


def _runtime_material(state, job, *, account, observation_path,
                      monitor_path, monitor_sha256, input_schema, expected_batch_ongoing):
    material=_validate_material(state,job,account=account,monitor_path=monitor_path,
        monitor_sha256=monitor_sha256,input_schema=input_schema)
    binding=material['plan']['research_binding']
    observation_path=Path(observation_path)
    observation,observed_modified=read_observation(observation_path)
    check_runtime(observation,now=time.time(),modified=observed_modified,
        data_path=str(Path(binding['research_data_root']).resolve()),
        installation_path=str(PureWindowsPath(binding['research_terminal']).parent),
        program_path=str(Path(monitor_path).resolve()),account_login=account['login'],
        account_server=account['server'],require_idle=True,expected_batch_ongoing=expected_batch_ongoing)
    return material


def validate_restart_material(state, job, *, account, monitor_path, monitor_sha256, input_schema):
    from studio_process_check import inspect_processes
    restart=job.get('restart_intent')
    if not restart or restart['phase']!='research_exited' or job['status'] not in ('starting','reconcile_required'):
        raise ValueError('Verified research exit required')
    if restart['account']!=dict(login=str(account['login']),server=account['server']):
        raise ValueError('Research account changed after close')
    material=_validate_material(state,job,account=account,monitor_path=monitor_path,
        monitor_sha256=monitor_sha256,input_schema=input_schema)
    if material['startup_receipt']['sha256']!=restart['startup_sha256']:
        raise ValueError('Startup configuration changed after close')
    current=inspect_processes(material['plan']['research_binding'],research_running=False)
    if current['protected']!=restart['process_baseline']['protected']:
        raise ValueError('Protected terminal changed after close')
    return material | dict(stopped_process_observation=current)


def _validate_material(state, job, *, account, monitor_path, monitor_sha256, input_schema):
    intent=job['launch_intent'];package=Path(intent['package']).resolve()
    raw=(package/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=intent['package_sha256']:
        raise ValueError('Launch package changed')
    manifest=json.loads(raw);plan=json.loads((package/'studio-plan.json').read_text(encoding='utf-8'))
    source=plan['studio_source'];binding=plan['research_binding']
    if manifest['campaign_id']!=sha(plan) or len(manifest['jobs'])!=1:
        raise ValueError('Package identity mismatch')
    if any(source[k]!=v for k,v in dict(terminal_id=state['terminal_id'],run_id=state['run_id'],
            job_id=job['job_id'],configuration_sha256=job['configuration_sha256'],source_revision=job['source_revision']).items()):
        raise ValueError('Package does not belong to frozen job')
    config=job['configuration']
    if input_schema is None or sha(input_schema)!=config['strategy']['schema_hash']:
        raise ValueError('Trusted input schema does not match frozen job')
    if sha(config)!=job['configuration_sha256']:raise ValueError('Frozen job drift')
    if plan['native_batch']['export_settings']!=config['export'] or binding['ea_relative_path']!=config['tester']['Expert']:
        raise ValueError('Frozen export policy or research expert mismatch')
    verify_export_policy(package,plan,manifest)
    item=manifest['jobs'][0];alias=item['run_alias'];relative=manifest['native_run_relative']
    if not re.fullmatch(r'R[0-9a-f]{20}',alias) or not re.fullmatch(r'GOAT\\R[0-9a-f]{12}',relative):
        raise ValueError('Invalid native path')
    staged_set=(package/(alias+'.set')).read_bytes();staged_ini=(package/(alias+'.ini')).read_bytes()
    if hashlib.sha256(staged_set).hexdigest()!=item['staged_sha256'] or hashlib.sha256(staged_ini).hexdigest()!=item['ini_sha256']:
        raise ValueError('Staged SET/INI drift')
    if read_values(staged_set)!=(config['strategy']['values']|{'EA_Desc':alias}):
        raise ValueError('Staged strategy differs from frozen job')
    sections=ini_sections(staged_ini)
    if sections.get('Tester')!={key:str(value) for key,value in item['tester'].items()}:
        raise ValueError('Staged tester differs from manifest')
    for key,value in config['tester'].items():
        if str(value)!=sections['Tester'].get(key):raise ValueError('Frozen tester mismatch: '+key)
    if sections.get('TesterInputs')!=read_values(staged_set):raise ValueError('Inline input drift')
    paste_inputs=explicit_paste_inputs(sections['TesterInputs'],input_schema)
    data=Path(binding['research_data_root']).resolve()
    if binding.get('account_confirmation_pending',True) or binding.get('live_trading_allowed',True):
        raise ValueError('Explicit research account authorization required')
    server=account['server']
    if not re.fullmatch(r'[A-Za-z0-9_. -]+',server):raise ValueError('Invalid server name')
    binary=(data/'MQL5/Experts'/binding['ea_relative_path'].replace('\\','/')).resolve()
    if not binary.is_relative_to(data/'MQL5/Experts') or hashlib.sha256(binary.read_bytes()).hexdigest()!=binding['ea_sha256'].lower():
        raise ValueError('Research EA binary drift')
    monitor=Path(monitor_path).resolve()
    if not monitor.is_relative_to(data/'MQL5/Experts') or hashlib.sha256(monitor.read_bytes()).hexdigest()!=monitor_sha256.lower():
        raise ValueError('Studio monitor binary drift')
    material=dict(package=package,manifest=manifest,plan=plan,sections=sections,paste_inputs=paste_inputs)
    startup_monitor=binding.get('startup_monitor')
    if startup_monitor is not None:
        if set(startup_monitor)!={'expert','preset','preset_sha256'}:
            raise ValueError('Unexpected startup monitor fields')
        relative_monitor=str(PureWindowsPath(monitor.relative_to(data/'MQL5/Experts')))
        if startup_monitor['expert']!=relative_monitor:
            raise ValueError('Startup monitor differs from verified monitor binary')
        preset_name=startup_monitor['preset']
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.set',preset_name):
            raise ValueError('Unsafe monitor preset name')
        preset=(data/'MQL5/Presets'/preset_name).read_bytes()
        if hashlib.sha256(preset).hexdigest()!=startup_monitor['preset_sha256']:
            raise ValueError('Startup monitor preset drift')
        values=read_values(preset)
        if values!={'Mode_Operation':'11','Studio_ReadOnlyMonitor':'true',
                    'Studio_MonitorRunPath':'','EA_Desc':'Studio Monitor'}:
            raise ValueError('Startup preset must be the monitor-only configuration')
        material['startup_monitor']=dict(Expert=relative_monitor,ExpertParameters=preset_name,
            Symbol=config['tester']['Symbol'],Period=config['tester']['Period'])
    startup_raw,startup_receipt=startup_config(material)
    return material | dict(startup_raw=startup_raw,startup_receipt=startup_receipt)


def validate_activated_job(state, job, *, account, observation_path, evidence,
                           monitor_path, monitor_sha256, input_schema):
    if 'restart_intent' in job:
        raise ValueError('Restart route already selected; open dispatch fields forbidden')
    return _activated_fields(state,job,account=account,observation_path=observation_path,
        evidence=evidence,monitor_path=monitor_path,monitor_sha256=monitor_sha256,input_schema=input_schema)


def validate_restart_controls(state, job, **arguments):
    restart=job.get('restart_intent')
    if not restart or restart['phase'] not in ('prepared','controls_installed'):
        raise ValueError('Prepared unarmed restart required')
    if restart['attempt_id']!=job['launch_intent']['attempt_id']:
        raise ValueError('Restart attempt changed')
    material=validate_launch_material(state,job,**{k:v for k,v in arguments.items() if k!='evidence'})
    if restart['startup_sha256']!=material['startup_receipt']['sha256']:
        raise ValueError('Restart startup payload changed')
    if restart['account']!=dict(login=str(arguments['account']['login']),server=arguments['account']['server']):
        raise ValueError('Restart account changed')
    return _activated_fields(state,job,**arguments) | dict(action='arm_restart',startup_sha256=restart['startup_sha256'])


def _activated_fields(state, job, *, account, observation_path, evidence,
                      monitor_path, monitor_sha256, input_schema, expected_batch_ongoing=False):
    material=_runtime_material(state,job,account=account,observation_path=observation_path,
        monitor_path=monitor_path,monitor_sha256=monitor_sha256,input_schema=input_schema,
        expected_batch_ongoing=expected_batch_ongoing)
    return _control_fields(job,material,account=account,evidence=evidence)


def _control_fields(job, material, *, account, evidence):
    package,manifest,plan,sections=(material[k] for k in ('package','manifest','plan','sections'))
    binding=plan['research_binding'];config=job['configuration'];server=account['server']
    data=Path(binding['research_data_root']).resolve()
    item=manifest['jobs'][0];alias=item['run_alias'];relative=manifest['native_run_relative']
    native=observe(package)
    if native['status']!='native_queued':raise ValueError('Native job must be queued and unstarted')
    common=Path(binding['common_files_root']).resolve();run=common/relative.replace('\\','/')
    base=common/'GOAT'/('GOAT V'+binding['ea_version']+'-'+server);evidence=Path(evidence).resolve()
    transaction=json.loads((evidence/'transaction.json').read_text())
    marker=base/'agent-native-control-owner.json';ownership=json.loads(marker.read_text())
    if transaction['phase']!='installed' or Path(transaction['base']).resolve()!=base:
        raise ValueError('Native transaction is not installed here')
    if transaction['owner']!=job['launch_intent']['attempt_id']:
        raise ValueError('Native transaction belongs to another attempt')
    if ownership!=dict(owner=transaction['owner'],evidence=str(evidence)):
        raise ValueError('Native control ownership mismatch')
    if set(transaction['files'])!={'active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini'}:
        raise ValueError('Incomplete native control transaction')
    for name,record in transaction['files'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=record['after_sha256']:
            raise ValueError('Native control transaction drift')
    pointer=ini_sections((base/'active_optimization_run.ini').read_bytes())
    if pointer!={'ActiveOptimizationRun':{'RunPath':relative}}:raise ValueError('Native run pointer mismatch')
    installed=ini_sections((base/'active_optimization_config.ini').read_bytes())
    if installed!=sections:raise ValueError('Native config differs from staged configuration')
    guard=ini_sections((base/'active_optimization_launch.ini').read_bytes()).get('ActiveOptimizationLaunch',{})
    expected=dict(LaunchId=transaction['owner'],RunPath=relative,Strategy=alias,Symbol=config['tester']['Symbol'],
        ConfigPath='GOAT\\GOAT V'+binding['ea_version']+'-'+server+'\\active_optimization_config.ini',
        AuditConfigPath=relative+'\\inputs\\'+alias+'\\config.ini')
    if any(guard.get(k)!=v for k,v in expected.items()):raise ValueError('Native launch guard mismatch')
    # Startup INI uses 1:N, but native paste parses leverage as integer N.
    # Banker build6182 roundtrip read 1:100 back as 1; preserve startup files
    # verbatim and normalize only the independently hashed paste payload.
    clipboard_sections={section:dict(sections[section]) for section in ('Tester','TesterInputs')}
    clipboard_sections['TesterInputs']=material['paste_inputs']
    leverage=clipboard_sections['Tester']['Leverage']
    if not leverage.startswith('1:') or not leverage[2:].isdigit() or int(leverage[2:])<=0:
        raise ValueError('Explicit ratio leverage required before native paste')
    clipboard_sections['Tester']['Leverage']=str(int(leverage[2:]))
    tester_ini=''.join('['+section+']\r\n'+''.join(k+'='+v+'\r\n' for k,v in clipboard_sections[section].items())
                       for section in ('Tester','TesterInputs'))
    fields=dict(data_path=str(PureWindowsPath(data)),installation_path=str(PureWindowsPath(binding['research_terminal']).parent),
        account_login=str(account['login']),account_server=server,native_run=relative,alias=alias,
        tester_ini=tester_ini,tester_ini_sha256=hashlib.sha256(tester_ini.encode('utf-8')).hexdigest())
    paths={'queue_sha256':run/'queue.GOAT','inputs_sha256':run/'inputs'/alias/'Inputs.GOAT',
        'pointer_sha256':base/'active_optimization_run.ini','native_config_sha256':base/'active_optimization_config.ini',
        'guard_sha256':base/'active_optimization_launch.ini','native_owner_sha256':marker}
    return fields|{key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}
