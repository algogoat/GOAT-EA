"""Load a reviewed portfolio into the selected demo terminal's Portfolio Dashboard.

Uses only the EA's own features: the dashboard resumes a saved Common Files state
(Dashboard_Resume_Saved=true on the first chart) and the hash-bound AgentPortfolio
mailbox attaches each child chart, dispatches the exposure policy and audits every
child's effective inputs against the frozen SET bytes.

Hard boundaries, each refused in code:
- broker-reported demo only (MT5 SDK ACCOUNT_TRADE_MODE_DEMO, and the EA itself
  answers only on demo); the Experiment 02 accounts are refused;
- Algo Trading stays off; the EA attaches children only while it is off with no
  positions or orders, and readiness requires it still off;
- member SET bytes must match the reviewed SHA-256 at stage, registration and audit;
- stop never closes positions: it unloads only an inert terminal.

deploy-preflight is read-only. deploy-load and deploy-stop keep a phase journal and
resume from it; a native close or launch is never issued twice.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import time

from studio_agent_mailbox import identity, portfolio_register, portfolio_request, portfolio_root, read_bounded, sharing_retry
from studio_agent_setup import PROTECTED_ACCOUNTS, broker_proof, close_terminal, demo_terminal_lock, require_unprotected
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate
from studio_onboarding import saved_launch_policy, session_state, require_idle_control

PLAN_SCHEMA = 'goat-demo-deploy-v1'
DEPLOYMENT_ID = re.compile(r'[a-f0-9]{32}')
SYMBOL = re.compile(r'[A-Za-z0-9_.#-]{1,64}')
FILE_NAME = re.compile(r'[^\\/:*?"<>|\t\r\n\x00]{1,180}\.set')
PRESET_NAME = 'GOAT Dashboard Agent.set'
# The dashboard chart itself never trades; children take their inputs from each SET.
PRESET = 'Mode_Operation=8\r\nDashboard_Resume_Saved=true\r\nMode_Bias=1\r\nBias_Protocol=2\r\nBias_threshold=50\r\nEA_Desc=GOAT Dashboard\r\n'.encode('utf-16')
STATE_HEADER = '#GOAT_AI_LAUNCH_V147_2'
READY_INSTRUCTION = 'Turn on Algo Trading in MT5 to start trading (demo)'
DASHBOARD_WAIT_SECONDS = 180  # licence check and dashboard init after the relaunch
ACK_WAIT_SECONDS = 90
AUDIT_WAIT_SECONDS = 90


def set_identity(file_name):
    """The dashboard's own ExtractEAnameAndSymbol rule (Dashboard.mqh)."""
    comma = file_name.find(',')
    if comma < 0:
        return None, None
    for position in range(comma - 1, -1, -1):
        if file_name[position] == ' ':
            name = file_name[:position]
            return (name, file_name[position + 1:comma]) if name else (None, None)
    return None, None


def set_values(raw):
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig', errors='replace')
    values = {}
    for line in text.splitlines():
        if not line or line.startswith(';') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values.setdefault(key, value)
    return values


def check_member_values(controller, name, raw):
    """Money-safety rules on the exact bytes a child chart will load, before anything is written.

    The same unconditional rule and reason code as validate-set/build-set/prepare: risk-per-sequence
    sizing with Max_Seq_Trades<=1 would size at the broker maximum once Algo Trading is on. An input a
    SET leaves out is the EA's declared default."""
    from studio_strategy_settings import check_risk_sizing, read_values
    from studio_template_tools import check_risk_chosen
    try:
        values = read_values(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError('Unreadable SET values: ' + name) from exc
    try:
        check_risk_sizing(values, controller.schema)
        check_risk_chosen(raw, values, controller.schema)
    except ValueError as exc:
        raise ValueError(str(exc) + ' (' + name + '; nothing was written or launched)') from exc


def validate_plan(controller, session, plan):
    if type(plan) is not dict or set(plan) != {'schema', 'deploymentId', 'portfolio', 'buildId', 'accountLogin', 'policy', 'members'}:
        raise ValueError('Invalid demo deploy plan')
    if plan['schema'] != PLAN_SCHEMA or not isinstance(plan['deploymentId'], str) or not DEPLOYMENT_ID.fullmatch(plan['deploymentId']):
        raise ValueError('Invalid demo deploy identity')
    portfolio = plan['portfolio']
    if (type(portfolio) is not dict or set(portfolio) != {'id', 'name'}
            or not (portfolio['id'] is None or (isinstance(portfolio['id'], str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', portfolio['id'])))
            or not isinstance(portfolio['name'], str) or not 0 < len(portfolio['name']) <= 160
            or any(ord(c) < 32 for c in portfolio['name'])):
        raise ValueError('Invalid portfolio identity')
    if str(plan['accountLogin']) != session['account']['login']:
        raise ValueError('The reviewed demo account differs from this installation')
    require_unprotected(plan['accountLogin'])
    policy = plan['policy']
    if (type(policy) is not dict or set(policy) != {'aiMode', 'aiThreshold', 'aiProtocol', 'exposureMode'}
            or policy['aiMode'] not in (0, 2) or policy['aiProtocol'] != 2 or policy['exposureMode'] not in (0, 1)
            or type(policy['aiThreshold']) is not int or not 1 <= policy['aiThreshold'] <= 100):
        raise ValueError('Unsupported dashboard policy')
    members = plan['members']
    if type(members) is not list or not 1 <= len(members) <= 100:
        raise ValueError('A demo portfolio needs 1 to 100 members')
    expected_ea = 'GOAT V' + controller.install['ea_version']
    names, prepared = set(), []
    for index, member in enumerate(members):
        if type(member) is not dict or set(member) != {'index', 'fileName', 'symbol', 'strategy', 'sha256', 'contentBase64'} or member['index'] != index:
            raise ValueError('Invalid portfolio member')
        name = member['fileName']
        if not isinstance(name, str) or not FILE_NAME.fullmatch(name) or '..' in name or name.strip() != name:
            raise ValueError('Unsafe SET file name: ' + str(name)[:80])
        if name.casefold() in names:
            raise ValueError('Duplicate SET file name: ' + name)
        names.add(name.casefold())
        ea_name, symbol = set_identity(name)
        if ea_name != expected_ea:
            raise ValueError(f'{name} was exported by {ea_name or "an unknown EA"}; this terminal runs {expected_ea}')
        if symbol != member['symbol'] or not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ValueError('SET file symbol does not match its member: ' + name)
        if not isinstance(member['strategy'], str) or len(member['strategy']) > 160 or any(c in member['strategy'] for c in '\t\r\n'):
            raise ValueError('Invalid strategy label: ' + name)
        if not isinstance(member['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', member['sha256']):
            raise ValueError('Invalid SET digest: ' + name)
        try:
            raw = base64.b64decode(member['contentBase64'], validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid SET bytes: ' + name) from exc
        if not 0 < len(raw) <= 2_000_000 or hashlib.sha256(raw).hexdigest() != member['sha256']:
            raise ValueError('SET bytes differ from the reviewed SHA-256: ' + name)
        check_member_values(controller, name, raw)
        prepared.append(dict(index=index, name=name, symbol=symbol, strategy=member['strategy'], sha256=member['sha256'], raw=raw))
    return prepared


def paths(controller, deployment_id):
    common = Path(controller.install['common_files_root'])
    data = Path(controller.install['terminal_data_root'])
    return dict(
        sets=common / 'GOAT' / 'Deployments' / deployment_id,
        state=common / 'GOAT' / ('dashboard_state_' + data.name + '.tsv'),
        profile=data / 'MQL5' / 'Profiles' / 'Charts' / ('GOAT-Deploy-' + deployment_id[:16]),
        preset=data / 'MQL5' / 'Presets' / PRESET_NAME,
        journal=Path(controller.root) / 'demo-deployments' / (deployment_id + '.json'),
        config=Path(controller.root) / 'demo-deployments' / (deployment_id + '.ini'),
        # The EA keys its saved dashboard and mailboxes by the data folder NAME only; this
        # claim binds that name to one full directory so two terminals can never share it.
        namespace=common / 'GOAT' / 'Deployments' / 'namespaces' / (data.name + '.json'))


def namespace_claim(controller):
    return (json.dumps(dict(schema=1, directory=str(Path(controller.install['terminal_data_root']).resolve()).casefold()),
                       sort_keys=True, separators=(',', ':')) + '\n').encode()


def namespace_conflict(controller):
    claim = paths(controller, '0' * 32)['namespace']
    return claim.exists() and claim.read_bytes() != namespace_claim(controller)


def staged_bytes(controller, plan, members):
    """Every file the relaunched dashboard will read, as the reviewed plan defines it."""
    where = paths(controller, plan['deploymentId'])
    policy = plan['policy']
    expected = {Path(m['path']): m['raw'] for m in members}
    expected[where['preset']] = PRESET
    expected[where['profile'] / 'chart01.chr'] = chart_bytes(members[0]['symbol'])
    expected[where['state']] = state_bytes(dict(policy='\t'.join(str(policy[k]) for k in ('aiMode', 'aiThreshold', 'aiProtocol')), members=members))
    expected[where['namespace']] = namespace_claim(controller)
    return expected


def verify_staged(controller, plan, members):
    for path, raw in staged_bytes(controller, plan, members).items():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('A staged dashboard file changed after the review (' + path.name + '); nothing was launched. Stop this deployment and deploy again.')


def state_bytes(rows):
    lines = [STATE_HEADER + '\t' + rows['policy']]
    for row in rows['members']:
        lines.append('\t'.join([row['path'], row['name'], row['symbol'], row['strategy'], 'As SET', 'As optimized', 'As SET', '0', '0']))
    return ('\r\n'.join(lines) + '\r\n').encode('utf-16')


def chart_bytes(symbol):
    # A plain first chart: [StartUp] attaches the dashboard EA to it with the preset.
    text = ('<chart>\nsymbol=' + symbol + '\nperiod_type=0\nperiod_size=1\nscale=8\nmode=1\ngrid=0\n'
            'scroll=1\none_click=0\nwindows_total=1\n<window>\nheight=100.000000\nobjects=0\n'
            '<indicator>\nname=Main\npath=\napply=1\nshow_data=1\n</indicator>\n</window>\n</chart>\n')
    return text.replace('\n', '\r\n').encode('utf-16')


def write_exact(path, raw):
    """Create-only; an existing file must already hold these exact bytes."""
    path = Path(path)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('A different file already exists at ' + path.name + '; preserve it and inspect')
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return True


def registration_for(ident, plan, members):
    return dict(schema=1, account=ident['account'], server=ident['server'], directory=ident['directory'], buildId=ident['buildId'],
                expiresAtUtc=int(time.time()) + 14400, aiMode=plan['policy']['aiMode'], aiThreshold=plan['policy']['aiThreshold'],
                aiProtocol=plan['policy']['aiProtocol'], exposureMode=plan['policy']['exposureMode'],
                members=[dict(index=m['index'], path=m['path'], symbol=m['symbol'], sha256=m['sha256']) for m in members])


def public(record):
    return dict(record)


def preflight(controller, *, mt5=None, process=None):
    """Read-only facts for the desktop review. Never closes, launches or registers."""
    from studio_monitor_probe import tester_state
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    process = process or WindowsSeedProcess(controller)
    result = dict(schema_version=1, account=dict(session['account']), demo_only_binding=session.get('demo_only') is True,
                  protected_account=session['account']['login'] in PROTECTED_ACCOUNTS,
                  ea_version=controller.install['ea_version'], ea_sha256=controller.install['ea_sha256'],
                  existing_dashboard=paths(controller, '0' * 32)['state'].exists(), deployment=current_deployment(controller),
                  namespace_conflict=namespace_conflict(controller), trading_changed=False)
    try:
        require_idle_control(controller, session)
        result['active_work'] = None
    except ValueError as exc:
        result['active_work'] = str(exc)
    running = process.inspect()
    result['terminal'] = 'running' if running else 'stopped'
    if not running:
        result['broker_error'] = 'The selected MT5 is not running; open it on the demo account.'
        return result
    try:
        proof = broker_proof(controller, session, mt5=mt5, require_flat=False)
        result['broker'] = proof
        try:
            result['tester_state'] = tester_state(running['pid'], proof['build'])
        except (OSError, ValueError, AttributeError):
            result['tester_state'] = 'unknown'
    except ValueError as exc:
        result['broker_error'] = str(exc)
    return result


def current_deployment(controller):
    root = Path(controller.root) / 'demo-deployments'
    if not root.is_dir():
        return None
    records = [read_json(path) for path in root.glob('*.json')]
    # A refused first attempt staged nothing and blocks nothing.
    live = [r for r in records if r.get('phase') not in ('stopped', 'refused_before_stage')]
    if not live:
        return None
    if len(live) > 1:
        raise ValueError('More than one live demo deployment is recorded for this terminal; inspect demo-deployments')
    return public(live[0])


def _poll_until(controller, ident, action, accept, *, seconds, step_timeout=20, request=None, sleep=time.sleep, clock=time.monotonic):
    request = request or portfolio_request
    deadline = clock() + seconds
    last = None
    while clock() < deadline:
        last = request(controller, ident, action, timeout=min(step_timeout, max(1, int(deadline - clock()))))
        if accept(last):
            return last
        if last['result'] not in ('receipt_timeout', 'observed', 'child_attached'):
            return last
        sleep(1)
    return last


def _verify_ready(audit, registration):
    if audit.get('action') != 'audit' or audit.get('result') != 'observed' or not 0 <= time.time() - audit['observedAtUtc'] <= 60:
        raise ValueError('A fresh dashboard settings audit is required')
    if not audit['connected'] or audit['tradingAllowed'] or audit['positions'] or audit['orders'] or audit['commandPending']:
        raise ValueError('The dashboard is not inert: Algo Trading must be off with no positions or orders')
    if any(audit[k] != registration[k] for k in ('aiMode', 'aiThreshold', 'aiProtocol')):
        raise ValueError('The dashboard AI policy differs from the reviewed policy')
    charts, magics, problems = set(), set(), []
    for row in audit['rows']:
        name = registration['members'][row['index']]['path'].rsplit('\\', 1)[-1]
        if not row['linkedFresh'] or row['chartId'] <= 0 or row['magic'] <= 0 or row['chartId'] in charts or row['magic'] in magics:
            problems.append(name + ': child chart identity unverified')
        elif not row['settingsMatch']:
            problems.append(name + ': child inputs differ from the frozen SET')
        elif row['EA_TRADE_ALLOWED'] != 1:
            problems.append(name + ': child chart is not allowed to trade, so Algo Trading would not start it')
        elif row['exposureMode'] != registration['exposureMode'] or row['ackId'] != audit['commandId'] or row['ackStatus'] != 1:
            problems.append(name + ': exposure policy not acknowledged')
        charts.add(row['chartId']); magics.add(row['magic'])
    if problems:
        raise ValueError('Dashboard readback failed: ' + '; '.join(problems[:5]))


def load(controller, plan_path, *, mt5=None, process=None, request=None, close=None, sleep=time.sleep):
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    plan = read_json(plan_path)
    members = validate_plan(controller, session, plan)
    ident = identity(controller, session, plan['buildId'])
    deployment_id = plan['deploymentId']
    where = paths(controller, deployment_id)
    process = process or WindowsSeedProcess(controller)
    request = request or portfolio_request
    plan_sha256 = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for member in members:
        member['path'] = str(where['sets'] / member['name'])
    where['journal'].parent.mkdir(parents=True, exist_ok=True)
    record = read_json(where['journal']) if where['journal'].exists() else None
    if record and record.get('plan_sha256') != plan_sha256:
        raise ValueError('This deployment ID was used for a different plan')
    other = current_deployment(controller)
    if other and other['deployment_id'] != deployment_id:
        raise ValueError('Another demo deployment is live on this terminal; stop it first')
    if record and record.get('phase') == 'ready':
        return public(record)
    if record and record.get('phase') == 'refused_before_stage':
        record = None  # Nothing was staged; the same reviewed plan starts again.
    if record is None:
        record = dict(schema_version=1, deployment_id=deployment_id, plan_sha256=plan_sha256, phase='validated',
                      portfolio=plan['portfolio'], account=dict(session['account']), build_id=plan['buildId'],
                      members=[dict(index=m['index'], fileName=m['name'], symbol=m['symbol'], sha256=m['sha256']) for m in members],
                      created_utc=datetime.now(timezone.utc).isoformat(), trading_changed=False, positions_closed=False)
        write_json(where['journal'], record)

    def phase(name, **extra):
        record.update(phase=name, **extra); record['updated_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(where['journal'], record)

    if record['phase'] == 'validated':
        try:
            with exclusive_gate(controller.local / 'native-gate'), demo_terminal_lock(controller):
                require_idle_control(controller, session)
                # A crash after staging but before the journal said 'staged' leaves this
                # plan's own exact resume file; only a different one blocks the deploy.
                if where['state'].exists() and (where['state'].is_symlink()
                                                or where['state'].read_bytes() != staged_bytes(controller, plan, members)[where['state']]):
                    raise ValueError('This terminal already has a saved GOAT dashboard portfolio; stop or remove it before deploying another')
                if (portfolio_root(controller) / 'registration.json').exists():
                    raise ValueError('Another dashboard portfolio registration is retained for this terminal; inspect it before deploying')
                if namespace_conflict(controller):
                    raise ValueError('Another MT5 terminal with the same data folder name already uses GOAT\'s dashboard files; GOAT will not deploy here')
                if process.inspect() is None:
                    raise ValueError('Open the selected MT5 on the demo account first so GOAT can verify it is a demo account')
                broker_proof(controller, session, mt5=mt5)
                for path, raw in staged_bytes(controller, plan, members).items():
                    write_exact(path, raw)
        except (OSError, ValueError):
            if not where['state'].exists() or where['state'].read_bytes() != staged_bytes(controller, plan, members)[where['state']]:
                phase('refused_before_stage')
            raise
        phase('staged')

    if record['phase'] == 'staged':
        running = process.inspect()
        if running is not None:
            # Demo proof and inert state come first; closing never touches positions.
            broker_proof(controller, session, mt5=mt5)
            closed = (close or close_terminal)(controller, 'deploy-' + deployment_id[:24], build_id=plan['buildId'])
            if closed.get('phase') not in ('stopped', 'already_stopped'):
                raise ValueError('MT5 did not confirm a normal close; run deploy-load again after it exits (no second close is sent)')
        phase('closed')

    if record['phase'] == 'closed':
        with exclusive_gate(controller.local / 'native-gate'), demo_terminal_lock(controller):
            if process.inspect() is not None:
                raise ValueError('The selected MT5 reopened before the dashboard launch; nothing was launched')
            portable = saved_launch_policy(controller, session)
            # Byte-exact: the SETs, resume file, chart, preset and namespace claim the EA will read.
            verify_staged(controller, plan, members)
            # Enabled=0 keeps Algo Trading off; Account=1 turns it off again if MT5 is later
            # signed in to another account (MT5 "disable on account change").
            config = ('[Charts]\r\nProfileLast=' + where['profile'].name + '\r\n[Experts]\r\nEnabled=0\r\nAccount=1\r\n'
                      '[StartUp]\r\nExpert=' + controller.install['ea_relative_path'] + '\r\nExpertParameters=' + PRESET_NAME +
                      '\r\nPeriod=M1\r\n').encode('utf-16')
            write_exact(where['config'], config)
            phase('launch_intent', startup_sha256=hashlib.sha256(config).hexdigest())
            arguments = [controller.install['terminal_executable'], '/config:' + str(where['config'])]
            if portable:
                arguments.append('/portable')
            child = subprocess.Popen(arguments, cwd=str(Path(arguments[0]).parent), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            phase('launched', pid=child.pid)
    elif record['phase'] == 'launch_intent':
        raise ValueError('A dashboard launch intent is retained without confirmation; inspect MT5 before retrying (never launched twice)')

    if record['phase'] in ('launched', 'registered'):
        registration = registration_for(ident, plan, members)
        digest = portfolio_register(controller, ident, registration)
        phase('registered', registration_sha256=digest)
        status = _poll_until(controller, ident, 'status', lambda r: r['result'] == 'observed', seconds=DASHBOARD_WAIT_SECONDS, request=request, sleep=sleep)
        if status is None or status['result'] != 'observed':
            outcome = status['result'] if status else 'receipt_timeout'
            raise ValueError('The Portfolio Dashboard did not answer (' + outcome + '). Check that MT5 opened on the demo account with GOAT paired, then run deploy-load again.')
        if status['tradingAllowed']:
            raise ValueError('Algo Trading is already on; turn it off before GOAT loads the portfolio')
        phase('dashboard_ready')

    if record['phase'] == 'dashboard_ready':
        for _ in range(len(members) + 2):
            attached = request(controller, ident, 'deploy_next', timeout=60)
            if attached['result'] == 'all_attached':
                break
            if attached['result'] != 'child_attached':
                raise ValueError('A child chart could not be attached (' + attached['result'] + '); run deploy-status, then deploy-stop to unwind')
        else:
            raise ValueError('The dashboard did not report every child attached')
        phase('attached')

    if record['phase'] == 'attached':
        dispatched = request(controller, ident, 'apply_policy', timeout=60)
        if dispatched['result'] != 'policy_dispatched':
            raise ValueError('The exposure policy was not dispatched (' + dispatched['result'] + ')')
        command = dispatched['commandId']
        def acknowledged(r):
            return (r['result'] == 'observed' and not r['commandPending']
                    and all(row['ackId'] == command and row['ackStatus'] == 1 for row in r['rows']))
        acked = _poll_until(controller, ident, 'status', acknowledged, seconds=ACK_WAIT_SECONDS, request=request, sleep=sleep)
        if acked is None or not acknowledged(acked):
            raise ValueError('Child charts did not acknowledge the exposure policy in time; run deploy-load again')
        phase('policy_applied', command_id=command)

    if record['phase'] == 'policy_applied':
        registration, _ = read_bounded(portfolio_root(controller) / 'registration.json', 131072)
        audit = _poll_until(controller, ident, 'audit', lambda r: r['result'] == 'observed' and all(row['settingsMatch'] for row in r['rows']),
                            seconds=AUDIT_WAIT_SECONDS, request=request, sleep=sleep)
        if audit is None or audit['result'] != 'observed':
            raise ValueError('The dashboard settings audit did not complete (' + (audit['result'] if audit else 'receipt_timeout') + ')')
        if audit['registrationSha256'] != record.get('registration_sha256'):
            raise ValueError('The dashboard audited a different registration than this deployment registered; readiness is not claimed')
        _verify_ready(audit, registration)
        proof = broker_proof(controller, session, mt5=mt5)
        if proof['algo_trading']:
            raise ValueError('Algo Trading turned on during the deploy; readiness is not claimed')
        rows = [dict(index=row['index'], symbol=row['symbol'], sha256=registration['members'][row['index']]['sha256'],
                     chartId=row['chartId'], magic=row['magic'], settingsMatch=row['settingsMatch']) for row in audit['rows']]
        phase('ready', readback=dict(audit_id=audit['id'], observed_at_utc=audit['observedAtUtc'], registration_sha256=audit['registrationSha256'],
                                     trading_allowed=audit['tradingAllowed'], positions=audit['positions'], orders=audit['orders'],
                                     demo=proof['demo'], algo_trading=proof['algo_trading'], login=proof['login'], server=proof['server'], rows=rows),
              instruction=READY_INSTRUCTION)
    return public(record)


def status(controller, *, mt5=None, process=None, request=None):
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    record = current_deployment(controller)
    process = process or WindowsSeedProcess(controller)
    request = request or portfolio_request
    result = dict(schema_version=1, deployment=record, terminal='running' if process.inspect() else 'stopped')
    if not record or result['terminal'] != 'running' or record.get('phase') not in ('registered', 'dashboard_ready', 'attached', 'policy_applied', 'ready'):
        return result
    try:
        ident = identity(controller, session, record['build_id'])
        observed = request(controller, ident, 'status', timeout=20)
        result['dashboard'] = dict(result=observed['result'], **({k: observed[k] for k in ('tradingAllowed', 'positions', 'orders', 'commandPending', 'observedAtUtc')}
                                                                 if observed['result'] == 'observed' else {}),
                                   rows=[dict(index=r['index'], symbol=r['symbol'], linkedFresh=r['linkedFresh']) for r in observed.get('rows', [])])
        if observed['result'] == 'observed':
            result['trading'] = bool(observed['tradingAllowed'] and observed['rows'] and all(r['linkedFresh'] for r in observed['rows']))
    except ValueError as exc:
        result['dashboard_error'] = str(exc)
    return result


def stop(controller, attempt_id, *, mt5=None, process=None, close=None):
    """Unload the dashboard portfolio from an inert terminal. Never closes positions."""
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    record = current_deployment(controller)
    if record is None:
        return dict(status='no_live_deployment', trading_changed=False, positions_closed=False)
    where = paths(controller, record['deployment_id'])
    journal = read_json(where['journal'])
    process = process or WindowsSeedProcess(controller)
    launched = journal.get('phase') not in ('validated', 'staged', 'closed')
    if launched and process.inspect() is not None:
        proof = broker_proof(controller, session, mt5=mt5, require_flat=False)
        if proof['algo_trading']:
            raise ValueError('Turn Algo Trading off in MT5 first; GOAT never turns it off or closes trades for you')
        if proof['positions'] or proof['orders']:
            raise ValueError('The demo account still has open positions or orders. Close or keep them yourself in MT5; GOAT never closes them automatically')
        closed = (close or close_terminal)(controller, attempt_id, build_id=journal['build_id'])
        if closed.get('phase') not in ('stopped', 'already_stopped'):
            raise ValueError('MT5 did not confirm a normal close; inspect it before deploy-stop again (no second close is sent)')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archived = []
    with exclusive_gate(controller.local / 'native-gate'), demo_terminal_lock(controller):
        if launched and process.inspect() is not None:
            raise ValueError('MT5 reopened during stop; nothing was unloaded')
        # Rename aside, never delete: a later launch has no saved dashboard or
        # deploy profile to resume, and every byte remains for inspection.
        mailbox_root = portfolio_root(controller)
        for source in (where['state'], where['profile'], mailbox_root / 'request.json', mailbox_root / 'registration.json'):
            if source.exists():
                target = source.with_name(source.name + '.stopped-' + stamp)
                sharing_retry(lambda: source.rename(target)); archived.append(str(target))
    journal.update(phase='stopped', stopped_utc=datetime.now(timezone.utc).isoformat(), archived=archived)
    write_json(where['journal'], journal)
    return public(journal) | dict(status='stopped', terminal='stopped', trading_changed=False, positions_closed=False,
                                  next_action='Run monitor-launch with a new attempt ID to return this terminal to research.')
