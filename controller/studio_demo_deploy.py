"""Load a reviewed portfolio into the selected demo terminal's Portfolio Dashboard.

Profile-staged (beta.25, goatai#1885 6033450916): deploy-load writes every chart into one
MT5 profile, GOAT-Deploy-<id16> (studio_deploy_profile): the dashboard on chart01.chr
(Dashboard_Resume_Saved=true) and one child per member with its frozen SET inputs. MT5
loads them all at start-up; the hash-bound AgentPortfolio mailbox then asks the dashboard
to adopt each child it finds (link_children, controller/contracts/profile-deploy.md),
dispatches the exposure policy and audits every child's effective inputs against the
frozen SET bytes. Nothing is attached or applied at runtime.

Hard boundaries, each refused in code:
- broker-reported demo only (MT5 SDK ACCOUNT_TRADE_MODE_DEMO, and the EA itself
  answers only on demo); the Experiment 02 accounts are refused;
- Algo Trading stays off: the startup configuration always writes [Experts] Enabled=0
  and nothing GOAT writes ever turns it on (D1); every receipt after start-up, the audit
  and the broker readback must show it off; turning it on stays the human's one gesture;
- GOAT never writes MT5's AllowLiveTrading; preflight reports it and readiness names
  the human step (D2);
- a member that is not linked by the start-up deadline is a named child_not_started, and
  deploy-load then unwinds itself (inert-only close, profile archived, previous profile
  restored), so a half-loaded MT5 is never left running (D3);
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
import studio_deploy_profile as deploy_profile
from studio_installation import read_json
from studio_launch_telemetry import SCHEMA as TELEMETRY_SCHEMA, launch_record, utc_now
from studio_native_gate import exclusive_gate
from studio_onboarding import saved_launch_policy, session_state, require_idle_control
from studio_refusal import Refusal

PLAN_SCHEMA = 'goat-demo-deploy-v1'
DEPLOYMENT_ID = re.compile(r'[a-f0-9]{32}')
SYMBOL = re.compile(r'[A-Za-z0-9_.#-]{1,64}')
FILE_NAME = re.compile(r'[^\\/:*?"<>|\t\r\n\x00]{1,180}\.set')
PROFILE_NAME = re.compile(r'[^\\/:*?"<>|\t\r\n\x00]{1,128}')
STATE_HEADER = '#GOAT_AI_LAUNCH_V147_2'
READY_INSTRUCTION = 'Turn on Algo Trading in MT5 to start trading (demo)'
DASHBOARD_WAIT_SECONDS = 180  # licence check and dashboard init after the relaunch
ACK_WAIT_SECONDS = 90
AUDIT_WAIT_SECONDS = 90
# MT5 starts every chart of the profile at once: a 60 s child licence retry plus the start-up of
# N charts (T3 proof). link_children is asked every LINK_POLL_SECONDS until then.
CHILD_START_WAIT_SECONDS = 240
LINK_REQUEST_SECONDS = 20
LINK_POLL_SECONDS = 2
# An unanswered request stays live until its expiry (wait + 5 s) and is archived 5 s after that.
LINK_RETRY_AFTER_TIMEOUT_SECONDS = 11
CHILD_NOT_STARTED = 'child_not_started'
CHILD_NOT_LINKED = 'child_not_linked'
# 3: additive only. allow_live_trading_default and readiness_blockers (D2); every version 2 key is unchanged.
PREFLIGHT_SCHEMA_VERSION = 3
ALLOW_LIVE_TRADING_BLOCKER = 'allow_live_trading_off'
# D2: GOAT never changes this MT5 security option. Confirmed against native T3 behaviour in proof step P0.
ALLOW_LIVE_TRADING_INSTRUCTION = (
    "This MT5 starts Expert Advisors without permission to trade (its saved 'Allow Algo Trading' default is off), "
    "so the GOAT charts would stay idle even after you turn Algo Trading on. GOAT does not change MT5 security "
    "settings for you. In MT5, attach any Expert Advisor once with 'Allow Algo Trading' ticked on its Common tab so "
    "MT5 keeps that default, close MT5 normally, then run deploy-stop and deploy again.")


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


SET_KEY_NOT_EXACT = 'SET_KEY_NOT_EXACT'
SET_DUPLICATE_INPUT = 'SET_DUPLICATE_INPUT'


def dashboard_values(raw, schema):
    """The input values exactly as the dashboard's BuildTemplate reads them (Dashboard.mqh): every line is
    trimmed, then split on its first '='; lines without a key are skipped. Comment lines are kept as the
    unknown keys the EA ignores. Stricter than the dashboard: a key that names a schema input only after
    trimming or case folding, and any input given twice after that normalisation, are refused, so a near-miss
    can never hide a value from this check and still reach the child chart."""
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    names = {name.casefold(): name for name in schema['inputs']}
    values, seen = {}, {}
    for line in text.splitlines():
        trimmed = line.strip()
        position = trimmed.find('=')
        if not trimmed or position <= 0:
            continue
        key = trimmed[:position].strip()
        exact = names.get(key.casefold())
        if exact is None:
            continue
        if line[:line.find('=')] != exact:
            raise ValueError(SET_KEY_NOT_EXACT + ': the SET line for ' + exact + ' has extra whitespace or different '
                             'letter case (' + repr(line[:line.find('=')]) + '); the dashboard would still load it, so it is refused')
        if exact in seen:
            raise ValueError(SET_DUPLICATE_INPUT + ': ' + exact + ' appears more than once; which value the chart would use '
                             'is ambiguous, so the SET is refused')
        seen[exact] = True
        values[exact] = trimmed[position + 1:].strip()
    return values


def check_member_values(controller, name, raw):
    """Money-safety rules on the exact bytes a child chart will load, before anything is written.

    The same unconditional rule and reason code as validate-set/build-set/prepare: risk-per-sequence
    sizing with Max_Seq_Trades<=1 would size at the broker maximum once Algo Trading is on. An input a
    SET leaves out is the EA's declared default."""
    from studio_strategy_settings import check_risk_sizing
    from studio_template_tools import check_risk_chosen
    try:
        values = dashboard_values(raw, controller.schema)
    except UnicodeDecodeError as exc:
        raise ValueError('Unreadable SET values: ' + name) from exc
    except ValueError as exc:
        raise ValueError(str(exc) + ' (' + name + '; nothing was written or launched)') from exc
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
        try:
            # The exact chart the profile will hold: period, line, character and nonce rules (studio_deploy_profile).
            deploy_profile.child_chart(dict(name=name, symbol=symbol, raw=raw), controller.install['ea_relative_path'], policy,
                                       plan['deploymentId'])
        except UnicodeDecodeError as exc:
            raise ValueError('Unreadable SET values: ' + name) from exc
        except Refusal as exc:
            raise Refusal(str(exc) + ' Nothing was written or launched.', exc.code, **exc.fields) from exc
        except ValueError as exc:
            raise ValueError(str(exc) + ' (' + name + '; nothing was written or launched)') from exc
        prepared.append(dict(index=index, name=name, symbol=symbol, strategy=member['strategy'], sha256=member['sha256'], raw=raw))
    # Adoption must never be ambiguous: two members that would start identical charts are refused.
    deploy_profile.refuse_duplicates(prepared, policy)
    return prepared


def paths(controller, deployment_id):
    common = Path(controller.install['common_files_root'])
    data = Path(controller.install['terminal_data_root'])
    return dict(
        sets=common / 'GOAT' / 'Deployments' / deployment_id,
        state=common / 'GOAT' / ('dashboard_state_' + data.name + '.tsv'),
        profile=data / 'MQL5' / 'Profiles' / 'Charts' / deploy_profile.profile_name(deployment_id),
        profiles=data / 'MQL5' / 'Profiles' / 'Charts',
        common_ini=data / 'config' / 'common.ini',
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
    """Every file the relaunched MT5 and dashboard will read, as the reviewed plan defines it."""
    where = paths(controller, plan['deploymentId'])
    policy = plan['policy']
    expected = {Path(m['path']): m['raw'] for m in members}
    charts = deploy_profile.profile_files(controller.install['ea_relative_path'], policy,
                                          [dict(name=m['name'], symbol=m['symbol'], raw=m['raw']) for m in members], plan['deploymentId'])
    for name, raw in charts.items():
        expected[where['profile'] / name] = raw
    # Unchanged from beta.24: every row starts cid=0 magic=0; the dashboard writes each row's identity when it
    # adopts the child (controller/contracts/profile-deploy.md). Row i is the child in chart file i + 2.
    expected[where['state']] = state_bytes(dict(policy='\t'.join(str(policy[k]) for k in ('aiMode', 'aiThreshold', 'aiProtocol')), members=members))
    expected[where['namespace']] = namespace_claim(controller)
    return expected


def verify_staged(controller, plan, members):
    staged = staged_bytes(controller, plan, members)
    for path, raw in staged.items():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('A staged dashboard file changed after the review (' + path.name + '); nothing was launched. Stop this deployment and deploy again.')
    # MT5 loads every chart file in the profile folder, so it must hold exactly the staged charts.
    profile = paths(controller, plan['deploymentId'])['profile']
    expected = {path.name for path in staged if path.parent == profile}
    extra = sorted(entry.name for entry in profile.iterdir() if entry.name not in expected)
    if profile.is_symlink() or extra:
        raise ValueError('The deploy profile holds files GOAT did not stage (' + ', '.join(extra[:3]) + '); nothing was launched. Stop this deployment and deploy again.')


def state_bytes(rows):
    lines = [STATE_HEADER + '\t' + rows['policy']]
    for row in rows['members']:
        lines.append('\t'.join([row['path'], row['name'], row['symbol'], row['strategy'], 'As SET', 'As optimized', 'As SET', '0', '0']))
    return ('\r\n'.join(lines) + '\r\n').encode('utf-16')


def startup_config(profile_name):
    """The /config file of the deploy launch. Enabled=0 keeps Algo Trading off (D1) and Account=1 turns it off
    again if MT5 is later signed in to another account. No [StartUp]: the dashboard comes from chart01 of the
    profile, and a startup expert would target an ambiguous chart. AllowLiveTrading is never written (D2)."""
    return ('[Charts]\r\nProfileLast=' + profile_name + '\r\n[Experts]\r\nEnabled=0\r\nAccount=1\r\n').encode('utf-16')


# ------------------------------------------------------- saved MT5 settings (common.ini)

def _decode_ini(raw):
    if raw.startswith(b'\xff\xfe'):
        return raw[2:].decode('utf-16-le'), 'utf-16-le', b'\xff\xfe'
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8', b'\xef\xbb\xbf'
    return raw.decode('utf-8'), 'utf-8', b''


def _ini_lines(text):
    """Lines with their own line ends, so joining them gives the text back exactly."""
    return re.findall(r'[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$', text)


def _ini_values(raw, section, key):
    """(line index, value) of every `key=` line in [section]; MT5 matches both case-insensitively."""
    text, _, _ = _decode_ini(raw)
    found, current = [], None
    for index, line in enumerate(_ini_lines(text)):
        body = line.rstrip('\r\n')
        heading = re.fullmatch(r'\s*\[([^\]]*)\]\s*', body)
        if heading:
            current = heading.group(1).strip().casefold()
        elif current == section.casefold():
            match = re.fullmatch(r'\s*([^=]*?)\s*=\s*(.*?)\s*', body)
            if match and match.group(1).casefold() == key.casefold():
                found.append((index, match.group(2)))
    return found


def read_common_ini(controller):
    raw = paths(controller, '0' * 32)['common_ini'].read_bytes()
    if len(raw) > 4_000_000:
        raise ValueError('MT5 common.ini is larger than GOAT reads')
    return raw


def allow_live_trading_default(controller):
    """D2, read-only: True when MT5's saved [Experts] AllowLiveTrading is 1, False when it is anything else or
    absent (MT5 then saves GOAT charts with the Allow Algo Trading bit off), None when common.ini is unreadable."""
    try:
        values = _ini_values(read_common_ini(controller), 'Experts', 'AllowLiveTrading')
    except (OSError, ValueError, UnicodeError):
        return None
    return len(values) == 1 and values[0][1] == '1'


def profile_last(raw):
    values = _ini_values(raw, 'Charts', 'ProfileLast')
    if len(values) > 1:
        raise ValueError('MT5 common.ini names more than one ProfileLast')
    return values[0][1] if values else None


def patch_profile_last(raw, current, new):
    """common.ini with only the [Charts] ProfileLast value changed from current to new; every other byte kept."""
    text, encoding, bom = _decode_ini(raw)
    if bom + text.encode(encoding) != raw or '\x00' in text:
        raise ValueError('MT5 common.ini does not round-trip exactly; it was not edited')
    lines = _ini_lines(text)
    profile_last(raw)  # refuses more than one ProfileLast
    values = _ini_values(raw, 'Charts', 'ProfileLast')
    if len(values) != 1 or values[0][1] != current or not PROFILE_NAME.fullmatch(new):
        raise ValueError('MT5 common.ini does not name ' + current + ' as its profile; it was not edited')
    index = values[0][0]
    body = lines[index].rstrip('\r\n')
    match = re.fullmatch(r'(\s*[^=]*?\s*=\s*)(.*?)(\s*)', body)
    lines[index] = match.group(1) + new + match.group(3) + lines[index][len(body):]
    patched = bom + ''.join(lines).encode(encoding)
    if profile_last(patched) != new:
        raise ValueError('The ProfileLast edit did not read back; common.ini was not edited')
    return patched


def capture_previous_profile(controller, where):
    """The profile MT5 would open next (common.ini [Charts] ProfileLast) and a SHA-256 manifest of its folder,
    taken after MT5 exits, since MT5 rewrites the active profile on close. GOAT never writes that folder."""
    record = dict(name=None, captured_utc=utc_now())
    try:
        name = profile_last(read_common_ini(controller))
    except (OSError, ValueError, UnicodeError) as exc:
        return record | dict(reason='common.ini unreadable: ' + str(exc)[:160])
    if name is None:
        return record | dict(reason='common.ini names no profile')
    record['name'] = name
    if not PROFILE_NAME.fullmatch(name) or name in ('.', '..') or name.strip() != name:
        return record | dict(reason='not a profile folder name')
    if name == where['profile'].name:
        return record | dict(same_as_deploy=True, reason='MT5 already names this deployment\'s profile')
    folder = where['profiles'] / name
    try:
        manifest = deploy_profile.tree_manifest(folder)
    except (OSError, ValueError) as exc:
        return record | dict(path=str(folder), reason='profile folder unreadable: ' + str(exc)[:160])
    record.update(path=str(folder), exists=manifest is not None, manifest=manifest)
    if manifest is not None:
        record['manifest_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return record


SELECT_PROFILE_INSTRUCTION = ("MT5 would still open GOAT's set-aside deploy profile next time{why}. In MT5, choose File > Profiles "
                              "and select {profile}.")


def _select_profile_instruction(controller, where, result):
    """Plain words for the person when common.ini was left naming the archived deploy profile (goatai#1885 6035859714)."""
    try:
        current = profile_last(read_common_ini(controller))
    except (OSError, ValueError, UnicodeError):
        return result
    if current != where['profile'].name:
        return result
    previous = result.get('previous_profile')
    why = (', because your previous chart profile ' + previous + ' changed while GOAT was deployed' if result.get('previous_profile_intact') is False
           else '')
    return result | dict(select_profile_instruction=SELECT_PROFILE_INSTRUCTION.format(
        why=why, profile=previous if previous and result.get('previous_profile_intact') is not None else 'the profile you want to use'))


def restore_previous_profile(controller, journal, where, stamp, *, running):
    """restore_profile, plus a plain-English File > Profiles step whenever MT5 is left on the archived deploy profile."""
    result = restore_profile(controller, journal, where, stamp, running=running)
    return result if result['profile_restored'] or running else _select_profile_instruction(controller, where, result)


def restore_profile(controller, journal, where, stamp, *, running):
    """Select the recorded previous profile again with an exact single-line common.ini edit, only when its folder
    is byte-identical to the manifest taken before the deploy and MT5 still names this deployment's profile."""
    previous = journal.get('previous_profile') or {}
    result = dict(previous_profile=previous.get('name'), previous_profile_intact=None, profile_restored=False)
    if not previous.get('name') or previous.get('same_as_deploy') or 'manifest' not in previous:
        return result | dict(reason=previous.get('reason') or 'no previous profile was recorded')
    try:
        now = deploy_profile.tree_manifest(previous['path'])
    except (OSError, ValueError):
        now = None
    intact = previous['manifest'] is not None and now == previous['manifest']
    result['previous_profile_intact'] = intact
    if not intact:
        return result | dict(reason='the previous profile folder changed or is missing since the deploy; common.ini was not edited')
    if running:
        return result | dict(reason='MT5 is running, so common.ini was not edited')
    ini = where['common_ini']
    try:
        raw = read_common_ini(controller)
        current = profile_last(raw)
    except (OSError, ValueError, UnicodeError) as exc:
        return result | dict(reason='common.ini unreadable: ' + str(exc)[:160])
    if current == previous['name']:
        return result | dict(profile_restored=True, reason='already selected')
    if current != where['profile'].name:
        return result | dict(reason='MT5 now names profile ' + str(current) + ', not this deployment\'s; common.ini was not edited')
    try:
        patched = patch_profile_last(raw, current, previous['name'])
    except (ValueError, UnicodeError) as exc:
        return result | dict(reason=str(exc)[:200])
    base = where['journal'].with_suffix('')
    before = base.with_name(base.name + '.common-before-' + stamp + '.ini')
    after = base.with_name(base.name + '.common-after-' + stamp + '.ini')
    write_exact(before, raw)
    write_exact(after, patched)
    temporary = ini.with_name(ini.name + '.goat-' + stamp)
    with temporary.open('xb') as handle:
        handle.write(patched); handle.flush(); os.fsync(handle.fileno())
    sharing_retry(lambda: os.replace(temporary, ini))
    return result | dict(profile_restored=True, common_ini_before_sha256=hashlib.sha256(raw).hexdigest(),
                         common_ini_after_sha256=hashlib.sha256(patched).hexdigest(),
                         common_ini_before=str(before), common_ini_after=str(after))


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
    # deploymentId binds adoption and settingsMatch to the nonce in each staged child (B43; contract section 3).
    return dict(schema=1, deploymentId=plan['deploymentId'], account=ident['account'], server=ident['server'], directory=ident['directory'], buildId=ident['buildId'],
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
    result = dict(schema_version=PREFLIGHT_SCHEMA_VERSION, account=dict(session['account']), demo_only_binding=session.get('demo_only') is True,
                  protected_account=session['account']['login'] in PROTECTED_ACCOUNTS,
                  ea_version=controller.install['ea_version'], ea_sha256=controller.install['ea_sha256'],
                  existing_dashboard=paths(controller, '0' * 32)['state'].exists(), deployment=current_deployment(controller),
                  namespace_conflict=namespace_conflict(controller), trading_changed=False)
    # D2: reported, never written. Not a refusal here: readiness fails with the same instruction if a child
    # then reports it may not trade.
    allow_live = allow_live_trading_default(controller)
    result['allow_live_trading_default'] = allow_live
    result['readiness_blockers'] = [dict(code=ALLOW_LIVE_TRADING_BLOCKER, message=ALLOW_LIVE_TRADING_INSTRUCTION)] if allow_live is False else []
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
        proof = broker_proof(controller, session, mt5=mt5, require_flat=False, details=True)
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
        # An unanswered request stays live until wait + 5 s and is archivable 5 s later; asking again sooner would
        # be refused ("still live"). A slow dashboard start-up (every chart of the profile loads at once) is normal.
        sleep(LINK_RETRY_AFTER_TIMEOUT_SECONDS if last['result'] == 'receipt_timeout' else 1)
    return last


def _verify_ready(audit, registration, *, allow_live_trading=None):
    if audit.get('action') != 'audit' or audit.get('result') != 'observed' or not 0 <= time.time() - audit['observedAtUtc'] <= 60:
        raise ValueError('A fresh dashboard settings audit is required')
    if not audit['connected'] or audit['tradingAllowed'] or audit['positions'] or audit['orders'] or audit['commandPending']:
        raise ValueError('The dashboard is not inert: Algo Trading must be off with no positions or orders')
    if any(audit[k] != registration[k] for k in ('aiMode', 'aiThreshold', 'aiProtocol')):
        raise ValueError('The dashboard AI policy differs from the reviewed policy')
    charts, magics, problems, untradable = set(), set(), [], False
    for row in audit['rows']:
        name = registration['members'][row['index']]['path'].rsplit('\\', 1)[-1]
        if not row['linkedFresh'] or row['chartId'] <= 0 or row['magic'] <= 0 or row['chartId'] in charts or row['magic'] in magics:
            problems.append(name + ': child chart identity unverified')
        elif not row['settingsMatch']:
            problems.append(name + ': child inputs differ from the frozen SET')
        elif row['EA_TRADE_ALLOWED'] != 1:
            problems.append(name + ': child chart is not allowed to trade, so Algo Trading would not start it')
            untradable = True
        elif row['exposureMode'] != registration['exposureMode'] or row['ackId'] != audit['commandId'] or row['ackStatus'] != 1:
            problems.append(name + ': exposure policy not acknowledged')
        charts.add(row['chartId']); magics.add(row['magic'])
    if problems:
        # D2: the plain-English human step when MT5's saved Allow Algo Trading default is not on.
        hint = ' ' + ALLOW_LIVE_TRADING_INSTRUCTION if untradable and allow_live_trading is not True else ''
        raise ValueError('Dashboard readback failed: ' + '; '.join(problems[:5]) + hint)


def _closed_terminal(running, attempt, closed):
    """Journal facts about the MT5 deploy-load just closed (telemetry only, goatai#1885)."""
    observation = closed.get('exit_observation') if isinstance(closed.get('exit_observation'), dict) else {}
    running = running if isinstance(running, dict) else {}
    return dict(present_at_stage=True, pid=running.get('pid'), created_utc=running.get('created_utc'),
                close_attempt_id=attempt, close_phase=closed.get('phase'), close_method=closed.get('method'),
                close_requested_utc=observation.get('close_requested_utc'), inventories=observation.get('inventories'),
                last_seen_present_utc=observation.get('last_seen_present_utc'),
                exit_after_utc=observation.get('exit_after_utc'),
                observed_gone_utc=observation.get('observed_gone_utc') or closed.get('stopped_utc'))


def _launch_telemetry(arguments, options, previous, pre_launch_check, launch_started, popen_returned, pid):
    """The launch evidence for the journal. Never raises: MT5 is already started, so the 'launched' phase
    must be written whatever a probe does."""
    try:
        return launch_record(arguments=arguments, options=options, previous=previous, pre_launch_check=pre_launch_check,
                             launch_started_utc=launch_started, popen_returned_utc=popen_returned, pid=pid)
    except Exception as exc:
        return dict(schema=TELEMETRY_SCHEMA, error=type(exc).__name__ + ': ' + str(exc)[:200])


def _row_linked(row):
    return bool(row['linkedFresh']) and row['chartId'] > 0 and row['magic'] > 0


def rows_linked(rows):
    """Every row adopted with a fresh heartbeat, and no chart or magic claimed twice."""
    charts, magics = [r['chartId'] for r in rows], [r['magic'] for r in rows]
    return bool(rows) and all(_row_linked(r) for r in rows) and len(set(charts)) == len(charts) and len(set(magics)) == len(magics)


def rows_failed(members, rows):
    """The per-row outcome at the start-up deadline: child_not_started when no chart with our EA and this member's
    frozen settings was adopted, child_not_linked when one was adopted but is not a fresh, unique link."""
    failed, charts, magics = [], set(), set()
    for member in members:
        row = rows[member['index']] if rows and member['index'] < len(rows) else None
        if row is not None and _row_linked(row) and row['chartId'] not in charts and row['magic'] not in magics:
            charts.add(row['chartId']); magics.add(row['magic'])
            continue
        started = row is not None and row['chartId'] > 0 and row['magic'] > 0
        failed.append(dict(index=member['index'], fileName=member['name'], symbol=member['symbol'],
                           reason=CHILD_NOT_LINKED if started else CHILD_NOT_STARTED))
    return failed


def _link_children(controller, ident, *, request, sleep, clock):
    """Ask the dashboard to adopt the children MT5 started from the profile, until all are linked or the
    start-up window ends. Every receipt must still show Algo Trading off with no positions or orders."""
    deadline = clock() + CHILD_START_WAIT_SECONDS
    last, rows = None, None
    while clock() < deadline:
        try:
            receipt = request(controller, ident, 'link_children', timeout=max(1, min(LINK_REQUEST_SECONDS, int(deadline - clock()))))
        except ValueError as exc:
            return dict(outcome='refused', result=str(exc)[:200], rows=rows)
        last = receipt['result']
        if last in ('children_linked', 'children_pending'):
            rows = receipt['rows']
            if receipt['tradingAllowed'] or receipt['positions'] or receipt['orders'] or not receipt['connected']:
                return dict(outcome='not_inert', result=last, rows=rows)
            if last == 'children_linked' and rows_linked(rows):
                return dict(outcome='linked', result=last, rows=rows, receipt=receipt)
            sleep(LINK_POLL_SECONDS)
        elif last == 'receipt_timeout':
            sleep(LINK_RETRY_AFTER_TIMEOUT_SECONDS)
        else:
            # rejected_not_inert, rejected_portfolio_mismatch, rejected_ai_policy_mismatch or anything unexpected.
            return dict(outcome='not_inert' if last == 'rejected_not_inert' else 'refused', result=last, rows=rows)
    return dict(outcome='timeout', result=last or 'receipt_timeout', rows=rows)


def _named_rows(failed):
    shown = '; '.join(f"{row['fileName']} ({row['symbol']}): {row['reason']}" for row in failed[:5])
    return shown + (f'; and {len(failed) - 5} more' if len(failed) > 5 else '')


def _unwind(controller, session, journal, where, attempt_id, *, mt5, process, close, reason):
    """Unload the deployment from an inert terminal: close MT5 normally, rename the dashboard state, the deploy
    profile and the mailbox files aside, then select the previous profile again. Never closes positions."""
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
        running = process.inspect() is not None
        if launched and running:
            raise ValueError('MT5 reopened during stop; nothing was unloaded')
        # Rename aside, never delete: a later launch has no saved dashboard or deploy profile to resume, and
        # every byte remains for inspection. Only this deployment's own profile is moved, never the previous one.
        mailbox_root = portfolio_root(controller)
        for source in (where['state'], where['profile'], mailbox_root / 'request.json', mailbox_root / 'registration.json'):
            if source.exists():
                target = source.with_name(source.name + '.stopped-' + stamp)
                sharing_retry(lambda: source.rename(target)); archived.append(str(target))
        rollback = restore_previous_profile(controller, journal, where, stamp, running=running)
    journal.update(phase='stopped', stopped_utc=datetime.now(timezone.utc).isoformat(), archived=archived, stop_reason=reason,
                   rollback=rollback, previous_profile_intact=rollback['previous_profile_intact'],
                   profile_restored=rollback['profile_restored'])
    write_json(where['journal'], journal)
    return journal


def _unwind_summary(journal):
    rollback = journal.get('rollback') or {}
    if rollback.get('profile_restored'):
        profile = 'restored the previous chart profile ' + str(rollback.get('previous_profile'))
    else:
        profile = 'left the chart profile selection unchanged (' + str(rollback.get('reason', 'no previous profile')) + ')'
    summary = 'GOAT closed MT5 with Algo Trading off, set this deployment aside and ' + profile + '; nothing traded.'
    return summary + (' ' + rollback['select_profile_instruction'] if rollback.get('select_profile_instruction') else '')


def load(controller, plan_path, *, mt5=None, process=None, request=None, close=None, sleep=time.sleep, clock=time.monotonic):
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
    attempt = 1
    if record and record.get('phase') == 'stopped':
        # A stopped or auto-unwound attempt of this plan: keep its journal and deploy again from the start.
        attempt = int(record.get('attempt', 1)) + 1
        kept = where['journal'].with_name(deployment_id + '.attempt-' + str(attempt - 1) + '.json')
        if kept.exists():
            raise ValueError('An earlier attempt journal of this deployment is already kept; inspect demo-deployments')
        sharing_retry(lambda: where['journal'].rename(kept))
        record = None
    if record is None:
        record = dict(schema_version=1, deployment_id=deployment_id, plan_sha256=plan_sha256, phase='validated',
                      portfolio=plan['portfolio'], account=dict(session['account']), build_id=plan['buildId'],
                      members=[dict(index=m['index'], fileName=m['name'], symbol=m['symbol'], sha256=m['sha256']) for m in members],
                      created_utc=datetime.now(timezone.utc).isoformat(), trading_changed=False, positions_closed=False,
                      profile_format=deploy_profile.PROFILE_FORMAT, attempt=attempt)
        write_json(where['journal'], record)
    if record.get('profile_format') != deploy_profile.PROFILE_FORMAT and record['phase'] in ('validated', 'staged', 'closed', 'launch_intent'):
        raise ValueError('This deployment was staged by an earlier GOAT (template deploy) and never launched; run deploy-stop, then deploy again')
    attempt = int(record.get('attempt', 1))
    suffix = '' if attempt == 1 else '-a' + str(attempt)
    config_path = where['config'] if attempt == 1 else where['config'].with_name(deployment_id + '.attempt-' + str(attempt) + '.ini')

    def phase(name, **extra):
        record.update(phase=name, **extra); record['updated_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(where['journal'], record)

    def fail_and_unwind(code, message, failed=()):
        """D3: never leave a half-loaded MT5 running. The unwind is the inert-only deploy-stop path."""
        record.update(failure=dict(code=code, message=message[:400], utc=utc_now()), rows_failed=list(failed))
        write_json(where['journal'], record)
        try:
            _unwind(controller, session, record, where, 'unwind-' + deployment_id[:24] + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                    mt5=mt5, process=process, close=close, reason=code)
        except (OSError, ValueError) as exc:
            record['auto_unwind'] = dict(status='failed', error=str(exc)[:300], utc=utc_now())
            write_json(where['journal'], record)
            raise ValueError(message + ' GOAT could not unload it: ' + str(exc) + ' Then run deploy-stop.') from exc
        record['auto_unwind'] = dict(status='unwound', utc=utc_now())
        write_json(where['journal'], record)
        raise ValueError(message + ' ' + _unwind_summary(record) + ' Run deploy-load again to retry.')

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
        # Telemetry only (goatai#1885): which MT5 was closed and when it was seen gone.
        previous = dict(present_at_stage=running is not None, observed_gone_utc=None if running else utc_now(), exit_after_utc=None)
        if running is not None:
            # Demo proof and inert state come first; closing never touches positions.
            broker_proof(controller, session, mt5=mt5)
            attempt_id = 'deploy-' + deployment_id[:24] + suffix
            closed = (close or close_terminal)(controller, attempt_id, build_id=plan['buildId'])
            if closed.get('phase') not in ('stopped', 'already_stopped'):
                raise ValueError('MT5 did not confirm a normal close; run deploy-load again after it exits (no second close is sent)')
            previous = _closed_terminal(running, attempt_id, closed)
        # Taken after MT5 exits: MT5 rewrites the active profile and common.ini on close.
        phase('closed', previous_terminal=previous, previous_profile=capture_previous_profile(controller, where))

    if record['phase'] == 'closed':
        with exclusive_gate(controller.local / 'native-gate'), demo_terminal_lock(controller):
            check_started = utc_now()
            present = process.inspect()
            pre_launch_check = dict(started_utc=check_started, finished_utc=utc_now(), present=present is not None)
            if present is not None:
                raise ValueError('The selected MT5 reopened before the dashboard launch; nothing was launched')
            portable = saved_launch_policy(controller, session)
            # Byte-exact: the SETs, resume file, every chart of the profile and the namespace claim.
            verify_staged(controller, plan, members)
            config = startup_config(where['profile'].name)
            write_exact(config_path, config)
            phase('launch_intent', startup_sha256=hashlib.sha256(config).hexdigest(), startup_config=str(config_path))
            arguments = [controller.install['terminal_executable'], '/config:' + str(config_path)]
            if portable:
                arguments.append('/portable')
            launch_started = utc_now()
            child = subprocess.Popen(arguments, cwd=str(Path(arguments[0]).parent), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            popen_returned = utc_now()
            # The same keyword arguments as the call above, for the journal only (the test pins them equal).
            options = dict(cwd=str(Path(arguments[0]).parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            phase('launched', pid=child.pid, launch_telemetry=_launch_telemetry(
                arguments, options, record.get('previous_terminal'), pre_launch_check, launch_started, popen_returned, child.pid))
    elif record['phase'] == 'launch_intent':
        raise ValueError('A dashboard launch intent is retained without confirmation; inspect MT5 before retrying (never launched twice)')

    if record['phase'] in ('launched', 'registered'):
        registration = registration_for(ident, plan, members)
        try:
            digest = portfolio_register(controller, ident, registration)
        except ValueError as exc:
            fail_and_unwind('registration_refused', 'The dashboard portfolio could not be registered (' + str(exc) + ').')
        phase('registered', registration_sha256=digest)
        try:
            status = _poll_until(controller, ident, 'status', lambda r: r['result'] == 'observed', seconds=DASHBOARD_WAIT_SECONDS,
                                 request=request, sleep=sleep, clock=clock)
        except ValueError as exc:
            status = dict(result=str(exc)[:160])
        if status is None or status['result'] != 'observed':
            outcome = status['result'] if status else 'receipt_timeout'
            fail_and_unwind('dashboard_not_ready', 'The Portfolio Dashboard did not answer (' + outcome + '). Check that MT5 opened on the demo account with GOAT paired.')
        if status['tradingAllowed'] or status['positions'] or status['orders']:
            fail_and_unwind('not_inert_after_start', 'Algo Trading is already on (or the account has positions or orders) after MT5 started; '
                            'GOAT does not load a portfolio then.')
        phase('dashboard_ready')

    if record['phase'] == 'dashboard_ready':
        # A beta.24 journal launched by the template deploy resumes here too; its profile holds no children,
        # so every row ends child_not_started and the deploy unwinds cleanly.
        linked = _link_children(controller, ident, request=request, sleep=sleep, clock=clock)
        if linked['outcome'] != 'linked':
            failed = rows_failed(members, linked['rows'])
            if linked['outcome'] == 'not_inert':
                message = ('MT5 stopped being inert (Algo Trading on, a position or order open, or disconnected) before every '
                           'member was linked, so GOAT stopped linking (' + linked['result'] + ').')
            else:
                waited = 'within ' + str(CHILD_START_WAIT_SECONDS) + ' s' if linked['outcome'] == 'timeout' else '(' + linked['result'] + ')'
                message = (str(len(failed)) + ' of ' + str(len(members)) + ' members did not start as linked GOAT charts ' + waited
                           + ': ' + _named_rows(failed) + '.')
            fail_and_unwind(CHILD_NOT_STARTED if any(row['reason'] == CHILD_NOT_STARTED for row in failed) else CHILD_NOT_LINKED,
                            message, failed)
        phase('attached', link_result=linked['result'], linked_rows=[dict(index=r['index'], chartId=r['chartId'], magic=r['magic'])
                                                                     for r in linked['rows']])

    if record['phase'] == 'attached':
        dispatched = request(controller, ident, 'apply_policy', timeout=60)
        if dispatched['result'] != 'policy_dispatched':
            raise ValueError('The exposure policy was not dispatched (' + dispatched['result'] + ')')
        command = dispatched['commandId']
        def acknowledged(r):
            return (r['result'] == 'observed' and not r['commandPending']
                    and all(row['ackId'] == command and row['ackStatus'] == 1 for row in r['rows']))
        acked = _poll_until(controller, ident, 'status', acknowledged, seconds=ACK_WAIT_SECONDS, request=request, sleep=sleep, clock=clock)
        if acked is None or not acknowledged(acked):
            raise ValueError('Child charts did not acknowledge the exposure policy in time; run deploy-load again')
        phase('policy_applied', command_id=command)

    if record['phase'] == 'policy_applied':
        registration, _ = read_bounded(portfolio_root(controller) / 'registration.json', 131072)
        audit = _poll_until(controller, ident, 'audit', lambda r: r['result'] == 'observed' and all(row['settingsMatch'] for row in r['rows']),
                            seconds=AUDIT_WAIT_SECONDS, request=request, sleep=sleep, clock=clock)
        if audit is None or audit['result'] != 'observed':
            raise ValueError('The dashboard settings audit did not complete (' + (audit['result'] if audit else 'receipt_timeout') + ')')
        if audit['registrationSha256'] != record.get('registration_sha256'):
            raise ValueError('The dashboard audited a different registration than this deployment registered; readiness is not claimed')
        _verify_ready(audit, registration, allow_live_trading=allow_live_trading_default(controller))
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
    """Unload the dashboard portfolio from an inert terminal and select the previous profile again. Never closes positions."""
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    record = current_deployment(controller)
    if record is None:
        return dict(status='no_live_deployment', trading_changed=False, positions_closed=False)
    where = paths(controller, record['deployment_id'])
    journal = read_json(where['journal'])
    process = process or WindowsSeedProcess(controller)
    journal = _unwind(controller, session, journal, where, attempt_id, mt5=mt5, process=process, close=close, reason='deploy_stop')
    select = (journal.get('rollback') or {}).get('select_profile_instruction')
    return public(journal) | dict(status='stopped', terminal='stopped', trading_changed=False, positions_closed=False,
                                  next_action=(select + ' ' if select else '')
                                  + 'Run monitor-launch with a new attempt ID to return this terminal to research.')
