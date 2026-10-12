"""Customer monitor onboarding; no credentials, permissions or ownership grants.

Saved profile staging and a single stopped-terminal launch are distinct effects.
Status consumes existing evidence without pumping the human control inbox. Its one
write is controller-local evidence: when it observes the monitor healthy (see
record_healthy_observation) it notes the running chart hash, which never authorises
a launch. Only close-terminal's post-close record does (record_post_close_chart).
MT5 files are never written by status.
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
from studio_process_check import StoppedRootProcess, inspect_processes
from studio_protected_peer import process_binding
from studio_refusal import Refusal


# Open Lab experiment demo logins (all Darwinex-Demo), retired arms included (Ops, goatai#2350 6118578483). The one
# shared list: pairing-code, close-terminal, deploy, monitor-launch and monitor-repair never act on these accounts.
OPEN_LAB_LOGINS = frozenset((
    '3000109268', '3000109269', '3000109270', '3000109271', '3000109272', '3000109273',   # Experiment 01
    '3000109427', '3000109421',                                                           # Experiment 02
    '3000110705', '3000110706',                                                           # Experiment 03
))
PROTECTED_ACCOUNT_REFUSAL = 'PROTECTED_ACCOUNT'
NOT_DEMO_REFUSAL = 'NOT_DEMO_ACCOUNT'
# monitor-launch attempt IDs; monitor-repair launches as REPAIR_LAUNCH_PREFIX + its own ID.
LAUNCH_ATTEMPT_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')
REPAIR_LAUNCH_PREFIX = 'repair-'


def require_unprotected(login):
    if str(login) in OPEN_LAB_LOGINS:
        raise Refusal('This demo account belongs to a GOAT Open Lab experiment; agents never change it',
                      PROTECTED_ACCOUNT_REFUSAL)


def require_demo_binding(controller, session):
    """The demo evidence monitor-launch and monitor-repair hold without starting MT5.

    A stopped terminal cannot be read through the MetaTrader5 adapter (initialize(path) would start it), so this is
    the session's demo-only binding plus the last EA runtime report for this exact login and server, which must not
    say the account is not a demo. monitor-repair additionally reads the broker trade mode through inspect_idle_demo
    before its close, as close-terminal does; a launch that reuses an observed-healthy chart requires that record's
    SDK demo proof; and every launched monitor is ready only after the runtime readback proves demo and Algo OFF.
    """
    if session.get('demo_only') is not True:
        raise Refusal('This installation is not bound to a demo account; GOAT only opens MT5 for demo accounts',
                      NOT_DEMO_REFUSAL)
    try:
        observation = read_json(controller.local/'ui-observation.json')
    except (OSError, ValueError):
        return
    runtime = observation.get('runtime') if isinstance(observation, dict) else None
    if (isinstance(runtime, dict) and runtime.get('account_login') == str(session['account']['login'])
            and runtime.get('account_server') == session['account']['server'] and runtime.get('account_demo') is False):
        raise Refusal('The GOAT EA last reported this MT5 account as not a demo account; GOAT only opens MT5 for demo accounts',
                      NOT_DEMO_REFUSAL)


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


def onboarding_status(controller, *, mt5=None):
    steps = []
    healthy = False
    def step(name, state, action, **evidence):
        steps.append(dict(id=name, state=state, action=action, **evidence))
    step('installation', 'complete', 'Installed EA hash matches the selected installation receipt')
    result = dict(schema_version=1, status='needs_action', execution_ready=False,
                  native_qualification=False, steps=steps,
                  scope='Local monitor onboarding only; desktop onboarding.status checks signed-in beta access and account linking')
    try:
        session, state = session_state(controller)
        result['account'] = dict(login=session['account']['login'], server=session['account']['server'])
        step('controller_binding', 'complete', 'Existing local demo account binding verified')
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        step('controller_binding', 'blocked', 'Run bootstrap --account-login <own demo login> --account-server <exact server>', detail=str(exc))
        result['next_action']=steps[-1]['action']
        return result
    try:
        processes = inspect_processes(process_binding(controller),
                    observation_roots=[str(Path(controller.install['terminal_executable']).parent),controller.install['terminal_data_root']])
        step('terminal_process', 'complete', 'Selected terminal is running; exact executable process observed')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        processes = None
        if isinstance(exc, StoppedRootProcess):
            step('terminal_process', 'blocked', exc.next_action(), detail=str(exc), program=exc.program, pid=exc.pid, program_path=exc.path)
        else:
            step('terminal_process', 'blocked', 'Inspect terminal processes. For a stopped selected terminal use monitor-prepare then monitor-launch; never stop unrelated terminals.', detail=str(exc))
    try:
        monitor = native_monitor_observation(controller, session, state, processes['research'] if processes else None)
        result['runtime_valid_until_ms'] = monitor['runtime_valid_until_ms']
        step('native_monitor', 'complete', 'Fresh bound demo monitor is connected, Algo Trading off and tester idle')
        healthy = True
        step('agent_control', 'complete' if state['owner']=='agent' else 'human_action',
             'Human clicks Give to Agent in Studio while serve is running; then recheck status')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = None
        activation = Path(controller.install['common_files_root'])/'GOAT'/('activation-status-'+Path(controller.install['terminal_data_root']).name+'.json')
        try:
            report = read_json(activation)
            age = time.time()-float(report['observedAtUtc'])
            if (0 <= age <= 60 and report.get('accountId') == session['account']['login']
                    and str(report.get('buildId','')).startswith('V'+controller.install['ea_version']+'-')
                    and report.get('reason') == 'ACTIVATION_RELOAD_REQUIRED'):
                reason = 'ACTIVATION_RELOAD_REQUIRED'
        except (OSError, ValueError, KeyError, TypeError):
            pass
        action = ('Activation completed, but the EA did not confirm restart. Use the controller monitor repair on an idle session, or change the chart timeframe once.' if reason else
                  'Inspect the selected MT5 monitor: sign in to your demo, complete GOAT activation, approve DLL imports and required WebRequest URL, keep Algo Trading off, run serve and recheck.')
        profile = None if reason else wrong_chart_profile(controller, session)
        if profile and launched_monitor(controller, processes):
            # MT5 runs from GOAT's own monitor-launch, which names the monitor EA as its startup expert; ProfileLast in
            # common.ini changes only when MT5 closes, so the saved profile is not why feedback is missing yet.
            action = ('MT5 was started by monitor-launch with the GOAT monitor EA. Finish GOAT activation in that MT5 (Activate GOAT window), '
                      'approve DLL imports and the WebRequest URL, keep Algo Trading off, run serve and recheck.')
            profile = None
        if profile:
            action = ('MT5 saved chart profile '+profile['profile_last']+' as its last profile, not the GOAT Studio monitor profile '+profile['monitor_profile']+
                      '. Ask the user to choose File > Profiles > '+profile['monitor_profile']+' in MT5 (or, with MT5 closed, run monitor-launch --attempt-id <new id>), then recheck.')
        step('native_monitor', 'blocked', action, detail=str(exc), **({'reason_code':reason} if reason else {}), **(profile or {}))
    # Fix B (Claude-Mac, goatai#2350 6118571536 / 6118831254): a healthy observation here is EVIDENCE only (facts, the
    # running chart hash, time). It never authorises a launch; only close-terminal's post-close record does.
    result['monitor_healthy_observation'] = (record_healthy_observation(controller, session, processes, mt5=mt5) if healthy and processes
                                             else dict(status='not_observed', reason='native_monitor_not_observed_healthy'))
    if all(s['state']=='complete' for s in steps):
        result['status']='local_monitor_ready'
    result['next_action'] = next((s['action'] for s in steps if s['state']!='complete'),
        'Use desktop onboarding.status for account eligibility; native job start still performs fresh ownership/runtime checks')
    result['monitor_preset'] = str(Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
    result['permissions'] = dict(automation_changes_permissions=False,
        webrequest='Add https://goatedge.ai in MT5 Tools > Options > Expert Advisors > Allow WebRequest for listed URL',
        webrequest_urls=['https://goatedge.ai'],
        dll_imports='User approves DLL imports in MT5 and the monitor EA properties',
        broker_login='User signs in directly in MT5; never pass broker passwords through controller arguments')
    return result


def native_monitor_observation(controller, session, state, process):
    """The facts onboarding-status's native_monitor step requires; raises ValueError (or KeyError/TypeError/OSError) otherwise.

    Fresh bound EA runtime feedback for this terminal, data folder, EA and account (connected, demo, Algo Trading off,
    no batch, idle tester), the controller state loaded, feedback newer than ``process`` (the selected MT5's identity,
    when known) and the activation, and the same owner/revision/generation as the controller. Read-only.
    """
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
    if process and modified < datetime.fromisoformat(process['created_utc'].replace('Z','+00:00')).timestamp():
        raise ValueError('Monitor feedback predates the selected process; await fresh runtime evidence')
    if modified < (controller.local/'active.json').stat().st_mtime:
        raise ValueError('Monitor feedback predates the selected controller activation')
    same = all(observation.get(k) == state[k] for k in ('owner','revision','generation'))
    if not same:
        raise ValueError('Monitor and controller revision/generation/owner differ; run serve and recheck')
    stamp = datetime.strptime(observation['observed_terminal_utc'], '%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    return dict(observed_terminal_utc=observation['observed_terminal_utc'], feedback_modified=modified,
                runtime_valid_until_ms=int((min(modified, stamp) + 20) * 1000))


def wrong_chart_profile(controller, session):
    """Read-only: the saved MT5 ProfileLast when it is not this session's monitor profile.

    A seed or research /config launch can leave common.ini on an older profile, so
    a plain MT5 open shows charts without the GOAT Studio monitor.
    """
    try:
        name, profile = monitor_paths(controller, session)
        if not profile.is_dir():
            return None
        raw = (Path(controller.install['terminal_data_root'])/'config/common.ini').read_bytes()
        if len(raw) > 4_000_000:
            return None
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        section = None; last = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1].casefold()
            elif section == 'charts' and line.casefold().startswith('profilelast='):
                last = line.split('=', 1)[1].strip()
        if last and last != name:
            return dict(profile_last=last, monitor_profile=name)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        pass
    return None


def launched_monitor(controller, processes):
    """Read-only: the running selected MT5 is the process GOAT's own monitor-launch started.

    True only when the observed process ID is the one a retained monitor-launch record names and that
    record's untouched startup configuration sets the installed GOAT EA as the startup expert.
    """
    try:
        research = (processes or {}).get('research') or {}
        pid = research.get('pid')
        if type(pid) is not int or pid <= 0:
            return False
        directory = controller.root/'monitor-launches'
        if not directory.is_dir():
            return False
        for record in directory.glob('*.json'):
            launch = read_json(record)
            if launch.get('status') != 'process_started_unverified' or launch.get('pid') != pid:
                continue
            # A reused process ID is not this launch: the process must have started right after the launch record.
            started = datetime.fromisoformat(str(research['created_utc']).replace('Z','+00:00')).timestamp()
            if not -5 <= started-datetime.fromisoformat(launch['created_at']).timestamp() <= 120:
                continue
            config = Path(launch['startup_config'])
            raw = config.read_bytes()
            if config.parent != directory or len(raw) > 64_000 or hashlib.sha256(raw).hexdigest() != launch.get('startup_sha256'):
                continue
            text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
            if ('\r\n[StartUp]\r\nExpert='+controller.install['ea_relative_path']+'\r\n') in text:
                return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        pass
    return False


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


def monitor_chart(controller, symbol):
    if not re.fullmatch(r'[A-Za-z0-9_.#-]{1,64}', symbol):
        raise ValueError('Supply the exact broker symbol using letters, digits, underscore, dot, # or hyphen')
    relative = PureWindowsPath(controller.install['ea_relative_path'])
    if any(c in str(relative) for c in '\r\n<>\0'):
        raise ValueError('Unsupported EA profile path')
    text = ('<chart>\nsymbol='+symbol+'\nperiod_type=0\nperiod_size=1\nscale=8\nmode=1\ngrid=0\n'
            'scroll=1\none_click=0\nwindows_total=1\n<expert>\nname='+relative.stem+'\npath=Experts\\'+str(relative)+
            '\nexpertmode=0\n<inputs>\nMode_Operation=11\nStudio_ReadOnlyMonitor=true\nStudio_MonitorRunPath=\n'
            'EA_Desc=Studio Monitor\n</inputs>\n</expert>\n<window>\nheight=100.000000\nobjects=0\n'
            '<indicator>\nname=Main\npath=\napply=1\nshow_data=1\n</indicator>\n</window>\n</chart>\n')
    return text.replace('\n','\r\n').encode('utf-16')


def monitor_prepare(controller, symbol):
    raw = monitor_chart(controller, symbol)
    session, _ = session_state(controller)
    name, profile = monitor_paths(controller, session)
    receipt = dict(schema_version=1, installation_sha256=sha(controller.install), run_id=session['run_id'],
                   profile_name=name, profile_path=str(profile), symbol=symbol,
                   chart_sha256=hashlib.sha256(raw).hexdigest(), trading_enabled=False, permissions_granted=False)
    target = controller.root/'monitor-profile.json'
    with exclusive_gate(controller.local/'native-gate'):
        require_idle_control(controller, session)
        processes=inspect_processes(process_binding(controller), research_running=False, selected_stopped=True,
                          absent_roots=[str(Path(controller.install['terminal_executable']).parent),controller.install['terminal_data_root']])
        with (controller.root/'monitor-inventory.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps(dict(operation='monitor_prepare',process_inventory=processes),sort_keys=True)+'\n')
            output.flush();os.fsync(output.fileno())
        if target.exists():
            # A profile prepared before an EA update of this installation is the same profile.
            rebind_monitor_profile(controller, session, retained_installations(controller))
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


# The receipt fields an EA update of the same installation rewrites: demo_agent install-build
# (ea_sha256, bundle_version, agent_guide_path, demo_installed_at) and the desktop's stopped-terminal
# update (installed_at). Every other field (terminal, data folder, EA path, versions, state root) still
# names the installation the monitor profile was prepared for.
UPDATE_OWNED_INSTALLATION_FIELDS = frozenset(('ea_sha256','bundle_version','agent_guide_path','demo_installed_at','installed_at'))
MONITOR_RECEIPT_FIELDS = frozenset(('schema_version','installation_sha256','run_id','profile_name','profile_path','symbol',
                                    'chart_sha256','trading_enabled','permissions_granted'))


def same_installation(previous, current):
    """True when ``previous`` differs from ``current`` only in what an EA update rewrites."""
    if not isinstance(previous,dict) or not isinstance(current,dict):
        return False
    keep=lambda value:{k:v for k,v in value.items() if k not in UPDATE_OWNED_INSTALLATION_FIELDS}
    return keep(previous)==keep(current)


def retained_installations(controller):
    """The installation receipts install-build backed up before each EA update (demo-agent/backups).

    A backup counts only when its name is the SHA-256 of its exact bytes, as install-build writes it.
    """
    from studio_installation import load_installation
    found=[]
    folder=controller.root/'demo-agent'/'backups'
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob('installation-*.json')):
        try:
            if path.is_symlink() or path.name!='installation-'+hashlib.sha256(path.read_bytes()).hexdigest()+'.json':
                continue
            found.append(load_installation(path,verify_binary=False))
        except (OSError,ValueError,KeyError,TypeError,UnicodeError):
            continue
    return found


def rebind_monitor_profile(controller, session, previous_installations):
    """Carry the prepared monitor profile across an EA update of this same installation and session.

    install-build rebinds session.json to the updated receipt (new EA hash and bundle identity), but
    monitor-profile.json kept the previous installation hash, so monitor-launch then refused with
    "belongs to another installation/session" (goatai#1885, 2026-10-06). The receipt is rebound only
    when the session is already bound to the current receipt, the receipt names this session's run
    and profile, and the installation it names (a supplied previous receipt) differs from the current
    one only in UPDATE_OWNED_INSTALLATION_FIELDS. Only installation_sha256 changes; the saved chart is
    untouched and verify_monitor_profile still checks it in full before any launch. Anything else is
    left as it is, so verify_monitor_profile keeps refusing it.
    """
    target=controller.root/'monitor-profile.json'
    if not target.is_file():
        return dict(status='no_profile')
    raw=target.read_bytes()
    receipt=read_json(target)
    current=sha(controller.install)
    if not isinstance(receipt,dict) or set(receipt)!=MONITOR_RECEIPT_FIELDS or receipt.get('schema_version')!=1:
        return dict(status='not_prepared_receipt')
    if receipt['installation_sha256']==current:
        return dict(status='current')
    name,profile=monitor_paths(controller,session)
    previous=next((p for p in previous_installations if sha(p)==receipt['installation_sha256']),None)
    if (session.get('installation_sha256')!=current or previous is None or not same_installation(previous,controller.install)
            or receipt['run_id']!=session['run_id'] or receipt['profile_name']!=name or receipt['profile_path']!=str(profile)):
        return dict(status='unrelated')
    backup=controller.root/'demo-agent'/'backups'/('monitor-profile-'+hashlib.sha256(raw).hexdigest()+'.json')
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():
        with backup.open('xb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
    write_json(target,receipt|dict(installation_sha256=current))
    return dict(status='rebound',previous_installation_sha256=receipt['installation_sha256'],installation_sha256=current,backup=str(backup))


# ---- Fix B (Claude-Mac, goatai#2350 6118571536, timing ruling 6118831254): the post-close monitor chart.
#
# After a person approves DLL imports, MT5 saves a non-zero expertmode on the monitor chart and monitor-launch refused
# every later launch. GOAT still never decodes a permission bit. MT5 rewrites the chart when it closes, so the bytes a
# running monitor was loaded from are not the bytes the next launch reads. The authoritative record is therefore
# written by the controller's OWN close-terminal: immediately before its close it reads the monitor's health itself
# (the onboarding native_monitor facts plus its SDK readback: Algo Trading OFF, demo, the bound login, the same
# process); after MT5 has fully stopped, and only when the installation, terminal, account, session/profile and chart
# file are unchanged, it hashes the saved chart file and records that post-close SHA-256. monitor-launch accepts
# exactly those bytes (verify_saved_monitor's preserved_permissions_sha256 path); any other byte, including another
# permission value, refuses as before. onboarding-status keeps only a healthy OBSERVATION (facts, running hash, time)
# as evidence; it never authorises a launch. A record is retired (archived, never deleted) as soon as any bound fact
# differs, so it can never become valid again.
HEALTHY_CHART_RECORD = 'monitor-healthy-chart.json'
HEALTHY_CHART_ARCHIVE = 'monitor-healthy-chart-retired'
HEALTHY_CHART_KIND = 'post_close_monitor_chart'
HEALTHY_CHART_FIELDS = frozenset(('schema_version','kind','binding','chart_sha256','chart_bytes','permissions_changed','pre_close','close'))
HEALTHY_OBSERVATION = 'monitor-healthy-observation.json'
HEALTHY_OBSERVATION_KIND = 'healthy_monitor_observation'


def healthy_chart_binding(controller, session, chart_path):
    """What a post-close record is bound to: installation, terminal, account, session/profile and chart file.

    The installation is its suite folder ID plus every receipt field an EA update does not rewrite (the same rule
    rebind_monitor_profile uses), so an EA update of this installation keeps the record and anything else retires it.
    """
    from studio_evidence_archive import installation_id
    install = controller.install
    name, _ = monitor_paths(controller, session)
    return dict(installation_id=installation_id(controller.root),
                installation_identity_sha256=sha({k:v for k,v in install.items() if k not in UPDATE_OWNED_INSTALLATION_FIELDS}),
                terminal_executable=install['terminal_executable'], terminal_data_root=install['terminal_data_root'],
                account=dict(login=str(session['account']['login']), server=session['account']['server']),
                run_id=session['run_id'], profile_name=name, chart_path=str(chart_path))


def healthy_chart_mismatch(controller, session, record):
    """None when ``record`` is a well-formed post-close record whose binding still holds; else the first fact that differs."""
    if (not isinstance(record, dict) or set(record) != HEALTHY_CHART_FIELDS or record.get('schema_version') != 1
            or record.get('kind') != HEALTHY_CHART_KIND or not isinstance(record.get('binding'), dict)
            or not isinstance(record.get('pre_close'), dict) or not isinstance(record.get('close'), dict)
            or record.get('permissions_changed') is not False
            or not isinstance(record.get('chart_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['chart_sha256'])):
        return 'record'
    bound = record['binding']
    if not isinstance(bound.get('chart_path'), str):
        return 'record'
    current = healthy_chart_binding(controller, session, bound['chart_path'])
    if set(bound) != set(current):
        return 'record'
    for reason, keys in (('terminal', ('terminal_executable','terminal_data_root')), ('account', ('account',)),
                         ('installation', ('installation_id','installation_identity_sha256')), ('session', ('run_id','profile_name'))):
        if any(bound[key] != current[key] for key in keys):
            return reason
    _, profile = monitor_paths(controller, session)
    if Path(bound['chart_path']).parent != profile or Path(bound['chart_path']).suffix.lower() != '.chr':
        return 'chart_path'
    pre, sdk = record['pre_close'], record['pre_close'].get('sdk')
    if (pre.get('native_monitor') != 'complete' or not isinstance(sdk, dict) or sdk.get('demo') is not True
            or sdk.get('algo_trading') is not False or sdk.get('login') != current['account']['login']
            or sdk.get('server') != current['account']['server'] or record['close'].get('source') != 'close-terminal'):
        return 'record'
    return None


def check_healthy_chart(controller, session=None):
    """The valid post-close record, or None after retiring one whose binding no longer holds. Caller holds the native gate.

    ``session`` defaults to the raw session.json, so a changed installation retires the record even where
    session_state would refuse first. A retired record moves to HEALTHY_CHART_ARCHIVE (never deleted).
    """
    path = controller.root/HEALTHY_CHART_RECORD
    if not path.exists() and not path.is_symlink():
        return dict(status='none', record=None)
    raw = None
    try:
        if path.is_symlink():
            raise ValueError('linked record')
        raw = path.read_bytes()
        record = read_json(path)
        reason = healthy_chart_mismatch(controller, read_json(controller.root/'session.json') if session is None else session, record)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        record, reason = None, 'record'
    if reason is None:
        return dict(status='valid', record=record)
    return retire_healthy_chart(controller, raw, reason) | dict(record=None)


def retire_healthy_chart(controller, raw, reason):
    """Move the record into HEALTHY_CHART_ARCHIVE (named by its bytes' SHA-256) and journal why. Never deletes evidence."""
    path = controller.root/HEALTHY_CHART_RECORD
    folder = controller.root/HEALTHY_CHART_ARCHIVE
    folder.mkdir(exist_ok=True)
    if path.is_symlink():
        digest, target = None, None
        path.unlink()   # A link is not a record GOAT wrote; removing the link leaves its target untouched.
    elif raw is None:
        raise ValueError('The post-close monitor chart record could not be read; preserve and inspect it')
    else:
        digest = hashlib.sha256(raw).hexdigest()
        target = folder/(digest+'.json')
        if target.exists() and target.read_bytes() == raw:
            path.unlink()   # The same bytes are already archived.
        else:
            os.replace(path, target)
    with (folder/'retired.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps(dict(record_sha256=digest, reason=reason, retired_utc=datetime.now(timezone.utc).isoformat()), sort_keys=True)+'\n')
        output.flush(); os.fsync(output.fileno())
    return dict(status='retired', reason=reason, archived=str(target) if target else None)


def _observed_chart(controller, receipt):
    """The single saved monitor chart (path, bytes) after every non-permission check; observational, never for launch."""
    folder = verify_monitor_profile(controller, receipt, observed_human_reopen=True)
    chart = next(p for p in folder.iterdir() if p.suffix.lower() == '.chr')
    return chart, chart.read_bytes()


def record_healthy_observation(controller, session, processes, *, mt5=None):
    """onboarding-status EVIDENCE only: the monitor observed healthy, with the running chart hash. Never authorises a launch.

    Called right after the native_monitor step completed. Adds an SDK readback under the terminal lease (broker_proof:
    the running selected terminal and data folder, the linked login and server, demo, connected) and requires Algo
    Trading OFF, with the same process before and after. Writes HEALTHY_OBSERVATION (latest only) when the running
    chart or its binding changed since the last one. Never raises; no MT5 file is written.
    """
    from studio_agent_setup import broker_proof
    from studio_terminal_lease import BUSY_READ, terminal_lease
    research = (processes or {}).get('research') or {}
    if type(research.get('pid')) is not int:
        return dict(status='not_observed', reason='terminal_process')
    target = controller.root/HEALTHY_OBSERVATION
    try:
        with terminal_lease(controller.root, purpose='monitor-healthy-observation', busy_code='BROKER_READ_DEFERRED',
                            busy_message=BUSY_READ, broker_reason='terminal_busy'):
            chart, raw = _observed_chart(controller, read_json(controller.root/'monitor-profile.json'))
            digest = hashlib.sha256(raw).hexdigest()
            binding = healthy_chart_binding(controller, session, chart)
            try:
                prior = read_json(target)
            except (OSError, ValueError):
                prior = None
            if (isinstance(prior, dict) and prior.get('observed_running_sha256') == digest and prior.get('binding') == binding
                    and prior.get('process') == research):
                return dict(status='current', observed_running_sha256=digest, authorises_launch=False)
            proof = broker_proof(controller, session, mt5=mt5, require_flat=False)
            if proof['algo_trading'] is not False:
                return dict(status='not_observed', reason='algo_trading_on')
            after = inspect_processes(process_binding(controller),
                        observation_roots=[str(Path(controller.install['terminal_executable']).parent),controller.install['terminal_data_root']])
            if (after or {}).get('research') != research:
                return dict(status='not_observed', reason='process_changed')
            write_json(target, dict(schema_version=1, kind=HEALTHY_OBSERVATION_KIND, authorises_launch=False, binding=binding,
                                    observed_running_sha256=digest, process=research, native_monitor='complete',
                                    observed_utc=datetime.now(timezone.utc).isoformat(),
                                    sdk=dict(login=proof['login'], server=proof['server'], demo=proof['demo'], connected=proof['connected'],
                                             algo_trading=proof['algo_trading'], build=proof.get('build'))))
            return dict(status='observed', observed_running_sha256=digest, authorises_launch=False)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        return dict(status='not_observed', reason=getattr(exc, 'code', None) or 'check_failed', detail=str(exc))


def pre_close_health(controller, session, state, native, process):
    """close-terminal's own health read immediately before its close. Never raises.

    ``native`` is close-terminal's fresh SDK readback (inspect_idle_demo: selected terminal and data folder, the bound
    login and server, demo, connected, Algo Trading off, no positions or orders, idle tester) and ``process`` the MT5
    it is about to close. Healthy only with a demo-only, unprotected binding, that readback for that same process,
    the onboarding native_monitor facts (native_monitor_observation) and a saved monitor chart that passes every
    non-permission check. Returns dict(healthy=True, binding, observed_running_sha256, ...) or dict(healthy=False, reason).
    """
    try:
        if session.get('demo_only') is not True:
            return dict(healthy=False, reason='not_demo_binding')
        if str(session['account']['login']) in OPEN_LAB_LOGINS:
            return dict(healthy=False, reason='protected_account')
        if (not isinstance(native, dict) or native.get('demo') is not True or native.get('algo_trading') is not False
                or native.get('account_matches') is not True or native.get('connected') is not True or native.get('process') != process):
            return dict(healthy=False, reason='sdk_readback')
        monitor = native_monitor_observation(controller, session, state, process)
        chart, raw = _observed_chart(controller, read_json(controller.root/'monitor-profile.json'))
        return dict(healthy=True, native_monitor='complete', observed_utc=datetime.now(timezone.utc).isoformat(),
                    observed_terminal_utc=monitor['observed_terminal_utc'], process=process,
                    binding=healthy_chart_binding(controller, session, chart),
                    observed_running_sha256=hashlib.sha256(raw).hexdigest(),
                    sdk=dict(login=str(session['account']['login']), server=session['account']['server'], demo=True,
                             algo_trading=False, connected=True, tester_state=native.get('tester_state'),
                             source=native.get('tester_source', 'inspect_idle_demo')))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        return dict(healthy=False, reason=getattr(exc, 'code', None) or 'native_monitor', detail=str(exc))


def record_post_close_chart(controller, health, *, attempt_id, method, stopped_utc, process):
    """After close-terminal's own close: record the POST-CLOSE chart bytes the next monitor-launch reads. Never raises.

    Only with a healthy pre-close read (pre_close_health) from this same close, MT5 still stopped, and the
    installation, terminal, account, session/profile and chart file unchanged since that read.
    """
    if not isinstance(health, dict) or health.get('healthy') is not True:
        return dict(status='not_recorded', reason='no_healthy_pre_close_observation',
                    **({'pre_close_reason': health.get('reason')} if isinstance(health, dict) else {}))
    try:
        if process.inspect() is not None:
            return dict(status='not_recorded', reason='terminal_running')
        with exclusive_gate(controller.local/'native-gate'):
            session, _ = session_state(controller)
            chart, raw = _observed_chart(controller, read_json(controller.root/'monitor-profile.json'))
            if healthy_chart_binding(controller, session, chart) != health['binding']:
                return dict(status='not_recorded', reason='identity_changed')
            existing = check_healthy_chart(controller, session)
            digest = hashlib.sha256(raw).hexdigest()
            record = dict(schema_version=1, kind=HEALTHY_CHART_KIND, binding=health['binding'], chart_sha256=digest,
                          chart_bytes=len(raw), permissions_changed=False,
                          pre_close={k: health[k] for k in ('native_monitor','observed_utc','observed_terminal_utc','process',
                                                           'observed_running_sha256','sdk')},
                          close=dict(source='close-terminal', attempt_id=attempt_id, method=method, stopped_utc=stopped_utc,
                                     recorded_utc=datetime.now(timezone.utc).isoformat()))
            superseded = None
            if existing['record']:
                superseded = retire_healthy_chart(controller, (controller.root/HEALTHY_CHART_RECORD).read_bytes(), 'superseded')
            write_json(controller.root/HEALTHY_CHART_RECORD, record)
        return dict(status='recorded', chart_sha256=digest, chart_path=str(chart),
                    observed_running_sha256=health['observed_running_sha256'],
                    rewritten_on_close=digest != health['observed_running_sha256'],
                    **(dict(superseded=superseded) if superseded else {}))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        return dict(status='not_recorded', reason=getattr(exc, 'code', None) or 'check_failed', detail=str(exc))


# One stable machine code for every saved-monitor check below (Claude-Mac, goatai#2350 6095158688). The
# exception stays a ValueError (the CLI's top-level REFUSED is unchanged); ``failed_check`` names the first
# failing check and ``failed_checks`` all of them. Every sentence names what is wrong and the one step the
# person takes. Nothing here repairs anything: chart permissions and the saved chart are human-owned.
MONITOR_PROFILE_REFUSAL = 'MONITOR_PROFILE_CHANGED'
MONITOR_PRESET_NAME = 'GOAT Studio Agent'
MONITOR_INPUTS = (('Mode_Operation','11'),('Studio_ReadOnlyMonitor','true'),('Studio_MonitorRunPath',''))
# A check the person cannot fix in MT5 ends in GOAT's existing support route, in the same words: the controller's
# refusals say "send a support report with ... this message" (studio_config_start.restart_recovery) and the
# agent's support method is support.prepareReport (AGENT-START-HERE.md, "To report a product problem").
SUPPORT_ROUTE = 'send a support report with this message (support.prepareReport).'


def monitor_refusal(failures, *, profile_name=None, **fields):
    """A Refusal naming each failed check: ``failures`` is a list of (check, sentence, observed facts)."""
    from studio_refusal import Refusal
    checks=[check for check,_,_ in failures]
    observed={}
    for _,_,facts in failures:
        observed.update(facts)
    extra=dict(monitor_profile=profile_name) if profile_name else {}
    return Refusal(' '.join(sentence for _,sentence,_ in failures), MONITOR_PROFILE_REFUSAL,
                   failed_check=checks[0], failed_checks=checks, **(dict(observed=observed) if observed else {}), **extra, **fields)


def _profile_menu(profile_name):
    return 'File > Profiles > '+(profile_name or 'GOAT-Studio-...')


def verify_monitor_profile(controller, receipt, *, observed_human_reopen=False, preserved_permissions_sha256=None, healthy_chart=None):
    """``healthy_chart``: a record check_healthy_chart returned as valid (monitor-launch only). Its exact chart bytes
    are accepted through the preserved_permissions_sha256 path, and only for the chart file it is bound to."""
    session, _ = session_state(controller)
    name, profile = monitor_paths(controller, session)
    menu = _profile_menu(name)
    symbol = receipt.get('symbol') or 'the monitor symbol'
    ea_file = PureWindowsPath(controller.install['ea_relative_path']).name
    if receipt.get('installation_sha256') != sha(controller.install) or receipt.get('run_id') != session['run_id'] or receipt.get('profile_name') != name or receipt.get('profile_path') != str(profile):
        raise monitor_refusal([('profile_other_session',
            'The saved monitor profile was prepared for another GOAT installation or session, and GOAT never reuses it; '
            +SUPPORT_ROUTE,{})], profile_name=name)
    if not profile.is_dir() and not profile.is_symlink():
        raise monitor_refusal([('profile_missing',
            'The saved monitor profile '+name+' is no longer in MT5, and GOAT never recreates a prepared profile on its own; '
            +SUPPORT_ROUTE,{})], profile_name=name)
    if profile.resolve()!=profile:
        raise monitor_refusal([('profile_alias',
            'The saved monitor profile folder '+name+' is a link to another folder, and GOAT never follows a link there; '
            +SUPPORT_ROUTE,{})], profile_name=name)
    entries = list(profile.iterdir())
    charts = [p for p in entries if p.suffix.lower()=='.chr']
    unexpected = sorted(p.name for p in entries if p.resolve()!=p or not p.is_file() or (p not in charts and p.name.lower()!='order.wnd'))
    failures = []
    if not charts:
        failures.append(('chart_missing',
            'The saved monitor profile '+name+' has no chart left (the monitor chart was closed in MT5); '
            'in MT5, choose '+menu+', open a '+symbol+' chart and attach '+ea_file+' with the '+MONITOR_PRESET_NAME+' preset.',
            dict(chart_count=0)))
    elif len(charts)>1:
        failures.append(('extra_charts',
            'The saved monitor profile '+name+' has '+str(len(charts))+' charts and GOAT needs exactly one; '
            'in MT5, choose '+menu+' and close every chart except the '+symbol+' monitor chart.',
            dict(chart_count=len(charts))))
    if unexpected:
        failures.append(('extra_files',
            'The saved monitor profile folder holds items MT5 does not save there ('+', '.join(unexpected)+'); '
            'move them out of '+str(profile)+'.',
            dict(unexpected_items=unexpected)))
    if failures:
        raise monitor_refusal(failures, profile_name=name)
    raw = charts[0].read_bytes()
    if len(raw)>2_000_000:
        raise monitor_refusal([('chart_too_large',
            'The saved monitor chart file is over 2 MB, far bigger than a monitor chart; '+SUPPORT_ROUTE,
            dict(chart_bytes=len(raw)))], profile_name=name)
    if (healthy_chart is not None and preserved_permissions_sha256 is None
            and healthy_chart['binding']['chart_path'] == str(charts[0])):
        preserved_permissions_sha256 = healthy_chart['chart_sha256']
    verify_saved_monitor(raw, controller.install['ea_relative_path'], receipt['symbol'], controller.install['terminal_data_root'], observed_human_reopen=observed_human_reopen, preserved_permissions_sha256=preserved_permissions_sha256, profile_name=name)
    return profile


def verify_saved_monitor(raw, ea_relative_path, symbol, data_root, *, observed_human_reopen=False, preserved_permissions_sha256=None, profile_name=None):
    # MT5 rewrites chart metadata and permission flags on a normal close.
    # Accept those changes only after rechecking the effective saved monitor.
    menu=_profile_menu(profile_name)
    ea_file=PureWindowsPath(ea_relative_path).name
    load_preset=('in MT5, open the EA\'s settings on the monitor chart and load the '+MONITOR_PRESET_NAME+' preset on the Inputs tab.')
    def refuse(failures):
        return monitor_refusal(failures, profile_name=profile_name)
    def unreadable(detail):
        # The chart file is damaged or not in MT5's chart format; the original check stays in ``detail``.
        return refuse([('chart_unreadable','The saved monitor chart file is damaged or not in MT5\'s chart format, so GOAT cannot check it; '
                        +SUPPORT_ROUTE,dict(detail=detail))])
    try:
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    except UnicodeError:
        # Invalid UTF-8 or truncated UTF-16 is a damaged chart, refused like any other unreadable one.
        raise unreadable('Saved monitor chart is not valid UTF-8 or UTF-16 text') from None
    stack=[]; fields={}; counts={}; closed=False
    for line in text.splitlines():
        line=line.strip()
        if not line: continue
        if line.startswith('<'):
            tag=re.fullmatch(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)>',line)
            if not tag: raise unreadable('Invalid saved monitor chart tag')
            ending,name=tag.groups()
            if name != name.lower(): raise unreadable('Ambiguous saved monitor chart tag')
            if name=='script':
                raise refuse([('chart_runs_script','The monitor chart runs a script; in MT5, remove the script from the monitor chart.',{})])
            if ending:
                if not stack or stack[-1]!=name: raise unreadable('Invalid saved monitor chart nesting')
                stack.pop()
                if name=='chart': closed=True
            else:
                if closed or (not stack and name!='chart') or (stack and name=='chart') or len(stack)>32:
                    raise unreadable('Invalid saved monitor chart structure')
                stack.append(name);key=tuple(stack)
                counts[key]=counts.get(key,0)+1
            continue
        if not stack or closed: raise unreadable('Invalid saved monitor chart content')
        scope=tuple(stack)
        # MT5 persists GOAT's MQL input group labels as equals-framed rows
        # followed by whitespace and an empty assignment. They are headings,
        # not input keys; accept this exact shape only inside the input block.
        if scope==('chart','expert','inputs') and re.fullmatch(r'={3,}[A-Z][A-Z0-9 /]{0,79}={3,}[ \t]+=',line):
            continue
        if scope in (('chart',),('chart','expert'),('chart','expert','inputs'),('chart','window','indicator')):
            key,sep,value=line.partition('=')
            existing=fields.setdefault(scope,{})
            if not key or key != key.strip() or not sep:
                raise unreadable('Ambiguous saved monitor chart fields')
            if key.casefold() in {prior.casefold() for prior in existing}:
                if scope==('chart','expert','inputs'):
                    raise refuse([('inputs_duplicated','The monitor EA lists the input '+key+' more than once; '+load_preset,dict(duplicate_input=key))])
                # A repeated key from a second EA or indicator block names that block; within one block it is unreadable.
                if scope==('chart','expert') and counts.get(scope,0)>1:
                    raise refuse([('extra_ea','The monitor chart has more than one EA; in MT5, remove every EA except '+ea_file+' from the monitor chart.',{})])
                if scope==('chart','window','indicator') and counts.get(scope,0)>1:
                    raise refuse([('indicator','The monitor chart has an indicator GOAT did not add; '
                                   'in MT5, remove it from the monitor chart (Charts > Indicators List).',{})])
                raise unreadable('Ambiguous saved monitor chart fields')
            fields[scope][key]=value
    if stack or not closed:
        raise unreadable('Invalid saved monitor chart structure')
    experts=counts.get(('chart','expert'),0)
    if experts==0:
        raise refuse([('ea_missing','The GOAT EA is no longer on the monitor chart; '
                       'in MT5, choose '+menu+' and attach '+ea_file+' to the monitor chart with the '+MONITOR_PRESET_NAME+' preset.',{})])
    if experts!=1 or sum(count for scope,count in counts.items() if scope[-1]=='expert')!=1:
        raise refuse([('extra_ea','The monitor chart has more than one EA; in MT5, remove every EA except '+ea_file+' from the monitor chart.',{})])
    if counts.get(('chart','expert','inputs'))!=1:
        raise refuse([('inputs_missing','The monitor EA\'s saved inputs are missing; '+load_preset,{})])
    chart=fields.get(('chart',),{});expert=fields.get(('chart','expert'),{});inputs=fields.get(('chart','expert','inputs'),{})
    relative=PureWindowsPath(ea_relative_path)
    allowed=[PureWindowsPath('Experts')/relative,PureWindowsPath(data_root)/'MQL5'/'Experts'/relative]
    mode=expert.get('expertmode','')
    # This exception is observational only: the human has already reopened MT5.
    # Its caller binds unchanged saved bytes and verifies global Algo OFF via SDK.
    # Never infer undocumented bits, write a permission, or use this for launch.
    # A managed recovery may preserve the exact previously inspected inert
    # chart. Its transaction also checks saved/runtime Algo OFF and archives
    # permission bytes before close and after launch. No bit is reinterpreted.
    # monitor-launch uses the same path for the exact post-close chart bytes
    # close-terminal recorded after it observed this monitor healthy right before
    # its own close (record_post_close_chart; fix B, goatai#2350 6118571536 /
    # 6118831254); its launch still forces Algo Trading and live trading off.
    # Any other byte, including another permission value, refuses.
    preserved=(isinstance(preserved_permissions_sha256,str)
               and hashlib.sha256(raw).hexdigest()==preserved_permissions_sha256)
    permission_ok=(mode=='0' or ((observed_human_reopen is True or preserved) and re.fullmatch(r'[0-9]{1,3}',mode)))
    # Every remaining check is evaluated, so a refusal names each one that failed (in this order).
    failures=[]
    if chart.get('symbol')!=symbol:
        shown=chart.get('symbol') or 'no symbol'
        failures.append(('symbol','The monitor chart shows '+shown+' instead of '+symbol+'; '
                         'in MT5, choose '+menu+' and switch that chart back to '+symbol+'.',
                         dict(symbol=chart.get('symbol'),required_symbol=symbol)))
    if PureWindowsPath(expert.get('path','')) not in allowed:
        shown=PureWindowsPath(expert['path']).name if expert.get('path') else 'an EA with no saved path'
        failures.append(('ea_identity','The monitor chart runs '+shown+' instead of the installed '+ea_file+'; '
                         'in MT5, choose '+menu+' and attach '+ea_file+' to the monitor chart with the '+MONITOR_PRESET_NAME+' preset.',
                         dict(ea_path=expert.get('path'),required_ea=str(relative))))
    if not permission_ok:
        # The saved value is reported as MT5 wrote it; no bit of it is interpreted.
        failures.append(('permissions','The EA\'s chart permissions changed (Allow Algo Trading or DLL imports on the chart); '
                         'reopen the saved monitor profile in MT5 yourself ('+menu+').',
                         dict(expertmode=mode,required_expertmode='0')))
    changed=[]
    for key,required in MONITOR_INPUTS:
        value=inputs.get(key,'' if key=='Studio_MonitorRunPath' else None)
        if value!=required:
            changed.append(key+(' is missing' if value is None else ' is empty' if value=='' else ' is '+value)+
                           ' but GOAT needs '+(required if required else 'it empty'))
    if changed:
        failures.append(('inputs','The monitor EA\'s inputs changed ('+', and '.join(changed)+'); '+load_preset,
                         dict(inputs={key:inputs.get(key) for key,_ in MONITOR_INPUTS})))
    indicator=fields.get(('chart','window','indicator'),{})
    indicators=sum(count for scope,count in counts.items() if scope[-1]=='indicator')
    if indicators==0:
        # No Main block: the chart lost its price window. MT5 has no way to add it back to that chart; a new
        # chart in the same profile has one, so the step rebuilds the monitor chart there.
        failures.append(('indicator_missing','The monitor chart has lost its main price window; '
                         'in MT5, choose '+menu+', close that chart, open a new '+symbol+' chart and attach '+ea_file+
                         ' with the '+MONITOR_PRESET_NAME+' preset.',dict(indicator_count=0)))
    elif indicators!=1 or indicator.get('name')!='Main' or indicator.get('path','')!='':
        failures.append(('indicator','The monitor chart has an indicator GOAT did not add; '
                         'in MT5, remove it from the monitor chart (Charts > Indicators List).',
                         dict(indicator=indicator.get('name'))))
    if failures:
        raise refuse(failures)


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
    # A key MT5 has never saved (a fresh terminal) is named plainly; it is not a real Algo ON or another login.
    enabled = ini.get('Experts','Enabled',fallback=None)
    if enabled is None:
        raise ValueError('MT5 has not saved the Algo Trading setting yet (fresh terminal): open Tools > Options once and press OK, or use Connect in GOAT, then close MT5 normally before monitor launch')
    if enabled != '0':
        raise ValueError('Human must turn Algo Trading off and close the selected terminal normally before monitor launch')
    login, server = ini.get('Common','Login',fallback=None), ini.get('Common','Server',fallback=None)
    if login is None or server is None:
        raise ValueError('MT5 has not saved the broker '+('login' if login is None else 'server')+' yet (fresh terminal): sign in to your demo in the selected MT5 once and close it normally, or use Connect in GOAT')
    if login != session['account']['login'] or server != session['account']['server']:
        raise ValueError('Saved broker login/server differs; user must sign in directly in selected MT5, turn Algo Trading off and close normally')
    return portable


def monitor_launch(controller, attempt_id):
    if not isinstance(attempt_id, str) or not LAUNCH_ATTEMPT_ID.fullmatch(attempt_id):
        raise ValueError('Attempt ID must be 1..80 letters, digits, underscore or hyphen')
    # Retire an observed-healthy chart record whose installation, terminal, account or session changed, before
    # session_state can refuse a changed installation: a record never becomes valid again (fix B).
    record_path = controller.root/HEALTHY_CHART_RECORD
    if record_path.exists() or record_path.is_symlink():
        with exclusive_gate(controller.local/'native-gate'):
            check_healthy_chart(controller)
    session, _ = session_state(controller)
    require_unprotected(session['account']['login'])
    require_demo_binding(controller, session)
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
        # Heals a profile left on the previous receipt by an EA update from an earlier controller.
        rebound = rebind_monitor_profile(controller, session, retained_installations(controller))
        receipt = read_json(controller.root/'monitor-profile.json')
        healthy = check_healthy_chart(controller, session)
        try:
            profile = verify_monitor_profile(controller, receipt, healthy_chart=healthy['record'])
        except Refusal as exc:
            if exc.code == MONITOR_PROFILE_REFUSAL and 'permissions' in exc.fields.get('failed_checks', ()):
                # Which observed-healthy chart (if any) this launch compared against; nothing in it is a permission.
                record = healthy['record']
                exc.fields['observed_healthy_chart'] = (dict(status='differs', chart_sha256=record['chart_sha256']) if record
                                                        else dict(status=healthy['status'], **({'reason':healthy['reason']} if 'reason' in healthy else {})))
            raise
        chart = next(p for p in profile.iterdir() if p.suffix.lower() == '.chr')
        chart_sha256 = hashlib.sha256(chart.read_bytes()).hexdigest()
        reused_chart = (dict(chart_sha256=chart_sha256, chart_path=str(chart), recorded_by_close=healthy['record']['close']['attempt_id'],
                             stopped_utc=healthy['record']['close']['stopped_utc'])
                        if healthy['record'] and healthy['record']['chart_sha256'] == chart_sha256 else None)
        portable = saved_launch_policy(controller, session)
        processes=inspect_processes(process_binding(controller), research_running=False, selected_stopped=True,
                          absent_roots=[str(Path(controller.install['terminal_executable']).parent),controller.install['terminal_data_root']])
        # MT5 can open a profile without applying its embedded expert inputs.
        # Explicit native startup is required for a reproducible monitor attach.
        preset = Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        expected = 'Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
        if preset.read_bytes() != expected:
            raise ValueError('Monitor startup preset changed; preserve it before repair')
        config = directory/(attempt_id+'.ini')
        # Omit StartUp.Symbol: MT5 then attaches to the saved first chart,
        # rather than creating a disposable chart that vanishes on next start.
        startup = ('[Charts]\r\nProfileLast='+receipt['profile_name']+'\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n'
                   '[StartUp]\r\nExpert='+controller.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+
                   '\r\nPeriod=M1\r\n').encode('utf-16')
        if config.exists():
            raise ValueError('Unclaimed startup configuration exists; preserve and inspect before another launch')
        with config.open('xb') as stream:
            stream.write(startup); stream.flush(); os.fsync(stream.fileno())
        arguments = [controller.install['terminal_executable'], '/config:'+str(config)]
        if portable: arguments.append('/portable')
        intent = dict(schema_version=1, attempt_id=attempt_id, status='launch_intent',
                      installation_sha256=sha(controller.install), run_id=session['run_id'],
                      created_at=datetime.now(timezone.utc).isoformat(), execution_ready=False, process_inventory=processes,
                      native_qualification=False, startup_config=str(config),
                      startup_sha256=hashlib.sha256(startup).hexdigest(), preset_sha256=hashlib.sha256(expected).hexdigest(),
                      saved_chart_sha256=chart_sha256, observed_healthy_chart=reused_chart)
        write_json(target, intent)
        # A crash/failure here retains uncertainty; no automatic retry or close.
        process = subprocess.Popen(arguments, cwd=str(Path(arguments[0]).parent),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        intent.update(status='process_started_unverified', pid=process.pid)
        write_json(target, intent)
    return intent | dict(reused=False, **(dict(monitor_profile_rebound=rebound) if rebound['status']=='rebound' else {}),
        next_action=('MT5 reopened the monitor chart GOAT saved when it last closed this healthy monitor, with Algo Trading off; run serve, then onboarding-status (it names any human step left). '
                     'Process start is not runtime readiness.' if reused_chart else
                     'Approve DLL/WebRequest permissions and legitimate GOAT pairing in MT5; run serve, human Give to Agent, then onboarding-status. Process start is not runtime readiness.'))
