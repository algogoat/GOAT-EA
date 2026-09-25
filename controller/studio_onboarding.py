"""Customer monitor onboarding; no credentials, permissions or ownership grants.

Saved profile staging and a single stopped-terminal launch are distinct effects.
Status consumes existing evidence without pumping the human control inbox.
"""
import configparser
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import time

from campaign_ledger import packed, sha
from studio_installation import read_json
from studio_bridge import write_json
from studio_native_gate import exclusive_gate
from studio_process_check import inspect_processes


def session_state(controller):
    session = read_json(controller.root/'session.json')
    if session['installation_sha256'] != sha(controller.install):
        raise ValueError('Installation changed since bootstrap; reconcile before repair')
    active = read_json(controller.local/'active.json')
    expected = dict(directory_id=session['directory_id'], terminal_id=session['terminal_id'],
                    run_id=session['run_id'], terminal_data_path=controller.install['terminal_data_root'])
    if active != expected:
        raise ValueError('Native Studio activation differs from this controller session')
    database = controller.root/'studio.sqlite'
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        key = packed(dict(terminal_id=session['terminal_id'], run_id=session['run_id']))
        row = db.execute('SELECT owner,revision,generation FROM studio_state WHERE binding=?', (key,)).fetchone()
    if row is None:
        raise ValueError('Controller session has no matching database binding')
    return session, dict(owner=row[0], revision=row[1], generation=row[2])


def onboarding_status(controller):
    steps = []
    def step(name, state, action, **evidence):
        steps.append(dict(id=name, state=state, action=action, **evidence))
    step('installation', 'complete', 'Installed EA hash matches the selected installation receipt')
    result = dict(schema_version=1, status='needs_action', execution_ready=False,
                  native_qualification=False, steps=steps,
                  scope='Local monitor onboarding only; desktop onboarding.status checks signed-in beta access and account linking')
    try:
        session, state = session_state(controller)
        step('controller_binding', 'complete', 'Existing local demo account binding verified')
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        step('controller_binding', 'blocked', 'Run bootstrap --account-login <own demo login> --account-server <exact server>', detail=str(exc))
        result['next_action']=steps[-1]['action']
        return result
    binding = dict(research_terminal=controller.install['terminal_executable'])
    try:
        processes = inspect_processes(binding)
        step('terminal_process', 'complete', 'Selected terminal is running; exact executable process observed')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        processes = None
        step('terminal_process', 'blocked', 'Inspect terminal processes. For a stopped selected terminal use monitor-prepare then monitor-launch; never stop unrelated terminals.', detail=str(exc))
    try:
        from studio_resilient_read import read_observation
        from studio_runtime_check import check_runtime
        observation, modified = read_observation(controller.local/'ui-observation.json')
        i = controller.install
        check_runtime(observation, now=time.time(), modified=modified, data_path=i['terminal_data_root'],
                      installation_path=str(Path(i['terminal_executable']).parent),
                      program_path=str((Path(i['terminal_data_root'])/'MQL5/Experts').joinpath(*PureWindowsPath(i['ea_relative_path']).parts)),
                      account_login=session['account']['login'], account_server=session['account']['server'], require_idle=True)
        if observation.get('loaded') is not True:
            raise ValueError('Monitor has not loaded controller state')
        if processes and modified < datetime.fromisoformat(processes['research']['created_utc'].replace('Z','+00:00')).timestamp():
            raise ValueError('Monitor feedback predates the selected process; await fresh runtime evidence')
        if modified < (controller.local/'active.json').stat().st_mtime:
            raise ValueError('Monitor feedback predates the selected controller activation')
        same = all(observation.get(k) == state[k] for k in ('owner','revision','generation'))
        if not same:
            raise ValueError('Monitor and controller revision/generation/owner differ; run serve and recheck')
        step('native_monitor', 'complete', 'Fresh bound demo monitor is connected, Algo Trading off and tester idle')
        step('agent_control', 'complete' if state['owner']=='agent' else 'human_action',
             'Human clicks Give to Agent in Studio while serve is running; then recheck status')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        step('native_monitor', 'blocked', 'Inspect the selected MT5 monitor: sign in to your demo, complete GOAT activation, approve DLL imports and required WebRequest URL, keep Algo Trading off, run serve and recheck.', detail=str(exc))
    if all(s['state']=='complete' for s in steps):
        result['status']='local_monitor_ready'
    result['next_action'] = next((s['action'] for s in steps if s['state']!='complete'),
        'Use desktop onboarding.status for account eligibility; native job start still performs fresh ownership/runtime checks')
    result['monitor_preset'] = str(Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
    result['permissions'] = dict(automation_changes_permissions=False,
        webrequest='User approves the exact URL shown by the EA activation panel',
        dll_imports='User approves DLL imports in MT5 and the monitor EA properties',
        broker_login='User signs in directly in MT5; never pass broker passwords through controller arguments')
    return result


def monitor_paths(controller, session):
    name = 'GOAT-Studio-'+session['run_id'].removeprefix('session-')
    if not re.fullmatch(r'GOAT-Studio-[a-f0-9]{32}', name):
        raise ValueError('Invalid monitor profile identity')
    return name, Path(controller.install['terminal_data_root'])/'MQL5/Profiles/Charts'/name


def require_idle_control(controller, session):
    from studio_seed_slot import guard_active_seed
    guard_active_seed(controller.root)
    key = packed(dict(terminal_id=session['terminal_id'], run_id=session['run_id']))
    with closing(sqlite3.connect((controller.root/'studio.sqlite').as_uri()+'?mode=ro', uri=True)) as db:
        row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (key,)).fetchone()
    if row and any(job['status'] not in ('pending','completed','cancelled','failed','removed') for job in json.loads(row[0])):
        raise ValueError('Native job outcome remains unresolved; reconcile before monitor setup')
    if Path(controller.install['terminal_executable']).name.lower() != 'terminal64.exe':
        raise ValueError('Monitor process inspection requires terminal64.exe')


def monitor_prepare(controller, symbol):
    if not re.fullmatch(r'[A-Za-z0-9_.#-]{1,64}', symbol):
        raise ValueError('Supply the exact broker symbol using letters, digits, underscore, dot, # or hyphen')
    session, _ = session_state(controller)
    name, profile = monitor_paths(controller, session)
    relative = PureWindowsPath(controller.install['ea_relative_path'])
    if any(c in str(relative) for c in '\r\n<>\0'):
        raise ValueError('Unsupported EA profile path')
    text = ('<chart>\nsymbol='+symbol+'\nperiod_type=0\nperiod_size=1\nscale=8\nmode=1\ngrid=0\n'
            'scroll=1\none_click=0\nwindows_total=1\n<expert>\nname='+relative.stem+'\npath=Experts\\'+str(relative)+
            '\nexpertmode=0\n<inputs>\nMode_Operation=11\nStudio_ReadOnlyMonitor=true\nStudio_MonitorRunPath=\n'
            'EA_Desc=Studio Monitor\n</inputs>\n</expert>\n<window>\nheight=100.000000\nobjects=0\n'
            '<indicator>\nname=Main\npath=\napply=1\nshow_data=1\n</indicator>\n</window>\n</chart>\n')
    raw = text.replace('\n','\r\n').encode('utf-16')
    receipt = dict(schema_version=1, installation_sha256=sha(controller.install), run_id=session['run_id'],
                   profile_name=name, profile_path=str(profile), symbol=symbol,
                   chart_sha256=hashlib.sha256(raw).hexdigest(), trading_enabled=False, permissions_granted=False)
    target = controller.root/'monitor-profile.json'
    with exclusive_gate(controller.local/'native-gate'):
        require_idle_control(controller, session)
        inspect_processes(dict(research_terminal=controller.install['terminal_executable']), research_running=False)
        if target.exists():
            if read_json(target)!=receipt:
                raise ValueError('A different monitor profile is already prepared; preserve existing setup')
            verify_monitor_profile(controller, receipt)
            return receipt | dict(status='prepared', reused=True)
        if not profile.parent.resolve().is_relative_to(Path(controller.install['terminal_data_root'])):
            raise ValueError('Monitor profile parent escapes selected data folder')
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.mkdir(exist_ok=False)
        with (profile/'chart01.chr').open('xb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        write_json(target, receipt)
    return receipt | dict(status='prepared', reused=False,
        next_action='With the selected terminal stopped and saved Algo Trading off, run monitor-launch --attempt-id <new-id>')


def verify_monitor_profile(controller, receipt):
    session, _ = session_state(controller)
    name, profile = monitor_paths(controller, session)
    if receipt.get('installation_sha256') != sha(controller.install) or receipt.get('run_id') != session['run_id'] or receipt.get('profile_name') != name or receipt.get('profile_path') != str(profile):
        raise ValueError('Monitor profile receipt belongs to another installation/session')
    if profile.resolve()!=profile:
        raise ValueError('Prepared profile is an alias; inspect before restart')
    entries = list(profile.iterdir())
    charts = [p for p in entries if p.suffix.lower()=='.chr']
    if len(charts)!=1 or any(p.resolve()!=p or not p.is_file() or (p not in charts and p.name.lower()!='order.wnd') for p in entries):
        raise ValueError('Prepared profile changed; exactly one monitor chart and optional MT5 order.wnd required')
    raw = charts[0].read_bytes()
    if len(raw)>2_000_000:
        raise ValueError('Saved monitor chart exceeds size limit')
    verify_saved_monitor(raw, controller.install['ea_relative_path'], receipt['symbol'], controller.install['terminal_data_root'])
    return profile


def verify_saved_monitor(raw, ea_relative_path, symbol, data_root):
    # MT5 rewrites chart metadata and permission flags on a normal close.
    # Accept those changes only after rechecking the effective saved monitor.
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    stack=[]; fields={}; counts={}; closed=False
    for line in text.splitlines():
        line=line.strip()
        if not line: continue
        if line.startswith('<'):
            tag=re.fullmatch(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)>',line)
            if not tag: raise ValueError('Invalid saved monitor chart tag')
            ending,name=tag.groups()
            if name != name.lower(): raise ValueError('Ambiguous saved monitor chart tag')
            if name=='script': raise ValueError('Saved monitor profile must not execute a script')
            if ending:
                if not stack or stack[-1]!=name: raise ValueError('Invalid saved monitor chart nesting')
                stack.pop()
                if name=='chart': closed=True
            else:
                if closed or (not stack and name!='chart') or (stack and name=='chart') or len(stack)>32:
                    raise ValueError('Invalid saved monitor chart structure')
                stack.append(name);key=tuple(stack)
                counts[key]=counts.get(key,0)+1
            continue
        if not stack or closed: raise ValueError('Invalid saved monitor chart content')
        scope=tuple(stack)
        if scope in (('chart',),('chart','expert'),('chart','expert','inputs'),('chart','window','indicator')):
            key,sep,value=line.partition('=')
            existing=fields.setdefault(scope,{})
            if key != key.strip() or not sep or key.casefold() in {prior.casefold() for prior in existing}: raise ValueError('Ambiguous saved monitor chart fields')
            fields[scope][key]=value
    if stack or not closed or counts.get(('chart','expert'))!=1 or counts.get(('chart','expert','inputs'))!=1:
        raise ValueError('Saved monitor must contain exactly one EA and input block')
    if sum(count for scope,count in counts.items() if scope[-1]=='expert')!=1:
        raise ValueError('Saved monitor has unexpected expert blocks')
    chart=fields.get(('chart',),{});expert=fields.get(('chart','expert'),{});inputs=fields.get(('chart','expert','inputs'),{})
    relative=PureWindowsPath(ea_relative_path)
    allowed=[PureWindowsPath('Experts')/relative,PureWindowsPath(data_root)/'MQL5'/'Experts'/relative]
    if chart.get('symbol')!=symbol or PureWindowsPath(expert.get('path','')) not in allowed or expert.get('expertmode') != '0':
        raise ValueError('Saved monitor symbol, EA identity or permissions changed; human must review and reopen the saved profile in MT5')
    if inputs.get('Mode_Operation')!='11' or inputs.get('Studio_ReadOnlyMonitor')!='true' or inputs.get('Studio_MonitorRunPath','')!='':
        raise ValueError('Saved chart is no longer an inert Studio monitor')
    indicator=fields.get(('chart','window','indicator'),{})
    if sum(count for scope,count in counts.items() if scope[-1]=='indicator')!=1 or indicator.get('name')!='Main' or indicator.get('path','')!='':
        raise ValueError('Saved monitor contains an unexpected indicator')


def saved_launch_policy(controller, session):
    data = Path(controller.install['terminal_data_root'])
    executable = Path(controller.install['terminal_executable'])
    portable = data == executable.parent
    if not portable:
        origin = (data/'origin.txt').read_bytes()
        origin = origin.decode('utf-16') if origin.startswith(b'\xff\xfe') else origin.decode('utf-8-sig')
        if PureWindowsPath(origin.strip()) != PureWindowsPath(executable.parent):
            raise ValueError('MT5 origin.txt does not bind this executable to the selected data folder')
    raw = (data/'config/common.ini').read_bytes()
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    ini = configparser.ConfigParser(interpolation=None, strict=True)
    try: ini.read_string(text)
    except configparser.Error as exc: raise ValueError('Invalid saved MT5 common.ini') from exc
    if ini.defaults() or len({s.casefold() for s in ini.sections()}) != len(ini.sections()) or any(s.casefold() in ('startup','tester','testerinputs') for s in ini.sections()):
        raise ValueError('Ambiguous or automatic-start saved MT5 configuration; inspect manually')
    if ini.get('Experts','Enabled',fallback=None) != '0':
        raise ValueError('Human must turn Algo Trading off and close the selected terminal normally before monitor launch')
    if ini.get('Common','Login',fallback=None) != session['account']['login'] or ini.get('Common','Server',fallback=None) != session['account']['server']:
        raise ValueError('Saved broker login/server differs; user must sign in directly in selected MT5, turn Algo Trading off and close normally')
    return portable


def monitor_launch(controller, attempt_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', attempt_id):
        raise ValueError('Attempt ID must be 1..80 letters, digits, underscore or hyphen')
    session, _ = session_state(controller)
    directory = controller.root/'monitor-launches'
    directory.mkdir(exist_ok=True)
    target = directory/(attempt_id+'.json')
    with exclusive_gate(controller.local/'native-gate'):
        if target.exists():
            return read_json(target) | dict(reused=True, next_action='Run onboarding-status; a retained launch is never retried')
        for previous in directory.glob('*.json'):
            if read_json(previous).get('status') == 'launch_intent':
                raise ValueError('Unresolved monitor launch intent; inspect process and retained attempt, never launch again blindly')
        require_idle_control(controller, session)
        receipt = read_json(controller.root/'monitor-profile.json')
        verify_monitor_profile(controller, receipt)
        portable = saved_launch_policy(controller, session)
        inspect_processes(dict(research_terminal=controller.install['terminal_executable']), research_running=False)
        arguments = [controller.install['terminal_executable'], '/profile:'+receipt['profile_name']]
        if portable: arguments.append('/portable')
        intent = dict(schema_version=1, attempt_id=attempt_id, status='launch_intent',
                      installation_sha256=sha(controller.install), run_id=session['run_id'],
                      created_at=datetime.now(timezone.utc).isoformat(), execution_ready=False,
                      native_qualification=False)
        write_json(target, intent)
        # A crash/failure here retains uncertainty; no automatic retry or close.
        process = subprocess.Popen(arguments, cwd=str(Path(arguments[0]).parent),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        intent.update(status='process_started_unverified', pid=process.pid)
        write_json(target, intent)
    return intent | dict(reused=False,
        next_action='Approve DLL/WebRequest permissions and legitimate GOAT pairing in MT5; run serve, human Give to Agent, then onboarding-status. Process start is not runtime readiness.')
