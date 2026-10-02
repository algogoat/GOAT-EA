"""Per-terminal/account batch state and per-login credentials (terminal isolation).

INV-BATCH-01: every MT5 terminal/account keeps its own Common batch state in
``GOAT\\<EA>-<server>-<login>-<terminal hash>``. Two terminals on one EA and
server never share an active run pointer, config, launch guard, queue, export
settings or log. The EA mirror is ``GoatOptBasePath`` in
GOAT_Inputs_Definitions.mqh (``GOAT_TERMINAL_ISOLATION_V149``).

INV-CRED-01: the GOAT user credential is stored per MT5 login
(``api-bearer-v149-<login>.token``). The login comes only from the terminal or
the verified session receipt and is validated as digits.

Native batch starts call ``preflight`` under the native gate. It refuses, in one
plain sentence, when the running EA resolves a different folder, when another
live MT5 terminal resolves to this terminal's folder or cannot be matched to a
data folder (fails closed), or when the one-time move of shared pre-isolation
state cannot complete. Across terminals, only the holder of the shared folder's
create-only claim (terminal-isolation-claim.ini) moves anything. Nothing here
launches, stops or grants anything, and no batch state is ever discarded.
"""
import configparser
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import uuid

from studio_subprocess import background_creationflags

ISOLATED_VERSIONS = frozenset({'1.49'})
RECEIPT = 'terminal-isolation.ini'
OWNER = 'agent-native-control-owner.json'
POINTER = 'active_optimization_run.ini'
CONFIG = 'active_optimization_config.ini'
GUARD = 'active_optimization_launch.ini'
# Same order as the EA's GoatOptMigrateLegacyBatchStateLocked: pointer last.
MOVABLE = ('GOAT Batch Queue.GOAT', 'GOAT Export Settings.GOAT', 'log.GOAT', 'portfolio.goatbatch',
           CONFIG, GUARD, POINTER)
LOGIN = re.compile(r'[1-9][0-9]{0,19}')
SERVER = re.compile(r'[A-Za-z0-9_. -]+')
CLAIM = 'terminal-isolation-claim.ini'
NAMESPACE_SUFFIX = re.compile(r'-[0-9]+-([0-9a-fA-F]{8})$')


def valid_login(login):
    """Digits only; never builds a path from anything else."""
    if not isinstance(login, str) or not LOGIN.fullmatch(login):
        raise ValueError('MT5 account login must be digits only')
    return login


def valid_server(server):
    if not isinstance(server, str) or not SERVER.fullmatch(server) or server != server.strip():
        raise ValueError('Invalid server name')
    return server


def isolated(ea_version):
    return ea_version in ISOLATED_VERSIONS


def terminal_hash(data_root):
    """First 8 hex of SHA-256 over the terminal data path, as the EA computes it."""
    text = str(data_root).replace('/', '\\')
    while len(text) > 3 and text.endswith('\\'):
        text = text[:-1]
    lowered = ''.join(chr(ord(c) + 32) if 'A' <= c <= 'Z' else c for c in text)
    return hashlib.sha256(lowered.encode('utf-8')).hexdigest()[:8]


def legacy_base_name(ea_version, server):
    return 'GOAT V' + ea_version + '-' + valid_server(server)


def base_name(ea_version, server, login, data_root):
    """Folder name under Common\\Files\\GOAT for this terminal/account."""
    legacy = legacy_base_name(ea_version, server)
    if not isolated(ea_version):
        return legacy
    return legacy + '-' + valid_login(login) + '-' + terminal_hash(data_root)


def state_base(common, ea_version, server, login, data_root):
    return Path(common).resolve() / 'GOAT' / base_name(ea_version, server, login, data_root)


def relative_base(ea_version, server, login, data_root):
    """Common-relative spelling used inside EA control files (launch guard, pointer)."""
    return 'GOAT\\' + base_name(ea_version, server, login, data_root)


def binding_base(binding, account):
    return state_base(binding['common_files_root'], binding['ea_version'], account['server'],
                      str(account['login']), binding['research_data_root'])


def binding_relative(binding, account):
    return relative_base(binding['ea_version'], account['server'], str(account['login']),
                         binding['research_data_root'])


def _account(c):
    """The verified session account; read from session.json when not yet opened."""
    session = getattr(c, 'session', None)
    if session is None:
        path = Path(c.root) / 'session.json'
        if not path.exists():
            return None
        from studio_installation import read_json
        session = read_json(path)
    return session['account']


def controller_base(c):
    i, a = c.install, _account(c)
    if a is None:
        raise ValueError('Bind this terminal\'s demo account before using its batch state')
    return state_base(i['common_files_root'], i['ea_version'], a['server'], a['login'], i['terminal_data_root'])


def controller_base_name(c):
    """This installation's folder name, or None before any account is bound."""
    i, a = c.install, _account(c)
    if a is None:
        return None
    return base_name(i['ea_version'], a['server'], a['login'], i['terminal_data_root'])


def controller_hash(c):
    return terminal_hash(c.install['terminal_data_root'])


def foreign_namespace(folder_name, own_hash):
    """A folder that is another terminal's own batch state.

    Only the terminal hash decides, case-insensitively: this terminal's folder
    under any login, its -0- folder and case variants are never foreign.
    Mirrors GoatOptForeignNamespaceFolder.
    """
    match = NAMESPACE_SUFFIX.search(folder_name)
    return (folder_name.lower().startswith('goat v') and match is not None
            and match[1].lower() != str(own_hash).lower())


def credential_relative_path(legacy_relative, login):
    """Per-login credential file beside the receipt's legacy credential path.

    Receipts keep ``credential_relative_path`` (the pre-isolation shared file);
    isolation builds read and write ``<stem>-<login>.token`` next to it.
    """
    login = valid_login(login)
    path = PureWindowsPath(legacy_relative)
    if (path.drive or path.root or '..' in path.parts or len(path.parts) != 3
            or tuple(p.lower() for p in path.parts[:2]) != ('goat', 'credentials')
            or not re.fullmatch(r'api-bearer(?:-[A-Za-z0-9_-]+)?\.token', path.name)):
        raise ValueError('Credential path must be GOAT/Credentials/api-bearer*.token')
    separator = '/' if '/' in str(legacy_relative) else '\\'
    return separator.join((path.parts[0], path.parts[1], path.stem + '-' + login + '.token'))


# --------------------------------------------------------------------- receipts

def _read_text(path):
    raw = path.read_bytes()
    return raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'), raw.startswith(b'\xff\xfe')


def read_receipt(base):
    path = base / RECEIPT
    if not path.exists():
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(_read_text(path)[0])
    if parser.sections() != ['TerminalIsolation']:
        raise ValueError('Terminal isolation receipt is not recognised; preserve it for review')
    return dict(parser['TerminalIsolation'])


def _receipt_text(decision, *, legacy_rel, base_rel, login, data_root, planned='', moved='', left='', guard_before=''):
    rows = dict(Version='1', Decision=decision, LegacyBase=legacy_rel, Base=base_rel, Login=login,
                TerminalHash=terminal_hash(data_root), DataPath=str(data_root), Planned=planned, Moved=moved,
                Left=left, GuardConfigPathBefore=guard_before, DecidedBy='controller',
                DecidedAtUtc=datetime.now(timezone.utc).strftime('%Y.%m.%d %H:%M:%S'))
    return '[TerminalIsolation]\r\n' + ''.join(k + '=' + v + '\r\n' for k, v in rows.items())


def _write_receipt(path, text, *, replace):
    # UTF-16 with BOM, as the EA's FILE_UNICODE writer and reader expect. A unique
    # temporary name: a crash between write and publish never blocks a later run.
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.controller-tmp')
    with temporary.open('xb') as stream:
        stream.write(text.encode('utf-16'))
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(temporary, path)
    else:
        try:
            os.link(temporary, path)  # Create-only: fails if another writer published first.
        finally:
            temporary.unlink()


def _claim(legacy, base_rel, login, data_root):
    """Create-only claim in the shared folder; mirrors GoatOptIsolationClaim.

    Only the terminal named by the claim may move anything out of the shared folder.
    Returns (ours, holder).
    """
    me = login + '-' + terminal_hash(data_root)
    claim = legacy / CLAIM
    if not claim.exists():
        text = ('[TerminalIsolationClaim]\r\nLogin=' + login + '\r\nTerminalHash=' + terminal_hash(data_root)
                + '\r\nBase=' + base_rel + '\r\nClaimedAtUtc=' + datetime.now(timezone.utc).strftime('%Y.%m.%d %H:%M:%S') + '\r\n')
        try:
            _write_receipt(claim, text, replace=False)
        except FileExistsError:
            pass  # Another terminal claimed first.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(_read_text(claim)[0])
    except (OSError, UnicodeError, configparser.Error):
        return False, '-'  # Unreadable claim: no decision; the caller retries later.
    values = dict(parser['TerminalIsolationClaim']) if parser.has_section('TerminalIsolationClaim') else {}
    holder = values.get('Login', '') + '-' + values.get('TerminalHash', '').lower()
    return holder == me, holder


def holder_valid(holder):
    """A claim names a real terminal only as <login digits>-<8 hex>; anything else is transient."""
    return bool(re.fullmatch(r'[1-9][0-9]{0,19}-[0-9a-f]{8}', holder or ''))


# -------------------------------------------------------------------- migration

def _local_run_exists(data_root, run):
    relative = PureWindowsPath(run)
    if relative.drive or relative.root or '..' in relative.parts or not relative.parts:
        return False
    return (Path(data_root) / 'MQL5' / 'Files').joinpath(*relative.parts).is_dir()


def _owned_here(owner_path, controller_root):
    if controller_root is None:
        return True
    try:
        evidence = Path(json.loads(owner_path.read_text(encoding='utf-8'))['evidence']).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return True  # Unattributable ownership is treated as ours: refuse, never guess.
    return evidence.is_relative_to(Path(controller_root).resolve())


def _guard_value(path):
    if not path.exists():
        return ''
    match = re.search(r'(?m)^ConfigPath=([^\r\n]*)', _read_text(path)[0])
    return match[1] if match else ''


def migrate_legacy(common, ea_version, server, login, data_root, *, batch_flags=False, controller_root=None):
    """One-time move of shared pre-isolation batch files into this terminal's folder.

    Mirrors the EA. Files are moved, never discarded or overwritten; the launch
    guard's ConfigPath follows the moved config. Only the terminal holding the
    shared folder's create-only claim moves, and an interrupted move resumes.
    Raises ValueError with one plain sentence when the move must not happen
    (unsettled owned controls, or state in both folders). Returns the decision.
    """
    if not isolated(ea_version):
        return dict(decision='not_isolated')
    base = state_base(common, ea_version, server, login, data_root)
    legacy = Path(common).resolve() / 'GOAT' / legacy_base_name(ea_version, server)
    base_rel = relative_base(ea_version, server, login, data_root)
    legacy_rel = 'GOAT\\' + legacy_base_name(ea_version, server)
    text = dict(legacy_rel=legacy_rel, base_rel=base_rel, login=login, data_root=data_root)
    prior = read_receipt(base)
    if prior and prior.get('Decision') != 'moving':
        return dict(decision='decided', receipt=prior)
    if prior:
        planned = [n for n in prior.get('Planned', '').split('|') if n]
        guard_before = prior.get('GuardConfigPathBefore', '')
        if any(n not in MOVABLE for n in planned):
            raise ValueError('The terminal isolation receipt lists an unexpected file; preserve it for review.')
        ours, holder = _claim(legacy, base_rel, login, data_root)
        if not ours:
            raise ValueError('Batch state move stopped: the shared folder ' + str(legacy)
                             + ' is claimed by another MT5 terminal (' + holder + '). Nothing more was moved.')
    else:
        present = [n for n in MOVABLE if (legacy / n).exists()]
        existing = [n for n in MOVABLE if (base / n).exists()]
        if (legacy / OWNER).exists():
            if _owned_here(legacy / OWNER, controller_root):
                raise ValueError('Batch state was not moved: the shared folder ' + str(legacy)
                                 + ' still holds controls of an unfinished attempt from this controller. Finish or reconcile that attempt first.')
            return dict(decision='deferred_owned_elsewhere', legacy=str(legacy), base=str(base))
        base.mkdir(parents=True, exist_ok=True)
        if not present:
            _write_receipt(base / RECEIPT, _receipt_text('nothing_to_move', **text), replace=False)
            return dict(decision='nothing_to_move', legacy=str(legacy), base=str(base))
        inflight = (legacy / CONFIG).exists() or (legacy / GUARD).exists()
        here = batch_flags
        if not here and not inflight:
            run = ''
            if (legacy / POINTER).exists():
                parser = configparser.ConfigParser(interpolation=None, strict=True)
                parser.optionxform = str
                parser.read_string(_read_text(legacy / POINTER)[0])
                run = parser['ActiveOptimizationRun'].get('RunPath', '').strip() if parser.has_section('ActiveOptimizationRun') else ''
            here = run == '' or _local_run_exists(data_root, run)
        if not here:
            _write_receipt(base / RECEIPT, _receipt_text('left_for_other_terminal', left='|'.join(present), **text), replace=False)
            return dict(decision='left_for_other_terminal', legacy=str(legacy), base=str(base), left=present)
        if existing:
            raise ValueError('Batch state was not moved: both the shared folder ' + str(legacy) + ' (' + ', '.join(present)
                             + ') and this terminal\'s folder ' + str(base) + ' (' + ', '.join(existing)
                             + ') hold batch state. Keep one, archive the other, then retry.')
        # Copied terminals carry the same flags and local runs: the claim decides.
        ours, holder = _claim(legacy, base_rel, login, data_root)
        if not ours:
            if not holder_valid(holder):
                # A claim that could not be written or read is not another terminal's
                # win: record nothing, so the next start decides again.
                raise ValueError('Batch state was not moved yet: the shared folder ' + str(legacy)
                                 + ' claim could not be written or read. Nothing was decided; retry in a moment.')
            _write_receipt(base / RECEIPT, _receipt_text('left_for_other_terminal', left='|'.join(present), **text), replace=False)
            return dict(decision='left_for_other_terminal', legacy=str(legacy), base=str(base), left=present, claimed_by=holder)
        planned = present
        guard_before = _guard_value(legacy / GUARD)
        _write_receipt(base / RECEIPT, _receipt_text('moving', planned='|'.join(planned), guard_before=guard_before, **text),
                       replace=False)
    moved = []
    for name in planned:
        source, target = legacy / name, base / name
        if not source.exists():
            continue  # Already moved.
        if name == GUARD:
            body, utf16 = _read_text(source)
            body = body.replace('ConfigPath=' + legacy_rel + '\\' + CONFIG, 'ConfigPath=' + base_rel + '\\' + CONFIG)
            raw = body.encode('utf-16') if utf16 else body.encode('utf-8')
            if target.exists():
                # Only an interrupted move of this very guard may be completed.
                if _read_text(target)[0] != body:
                    raise ValueError('Batch state move stopped: ' + name + ' exists in both ' + str(legacy) + ' and '
                                     + str(base) + '. Keep one, archive the other, then retry.')
            else:
                staged = target.with_name(target.name + '.' + uuid.uuid4().hex + '.moving')
                with staged.open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(staged, target)  # Atomic create: a partial guard is never published.
                finally:
                    staged.unlink()
            source.unlink()  # The new guard is in place: this completes its move.
        else:
            if target.exists():
                raise ValueError('Batch state move stopped: ' + name + ' exists in both ' + str(legacy) + ' and '
                                 + str(base) + '. Keep one, archive the other, then retry.')
            os.rename(source, target)
        moved.append(name)
    _write_receipt(base / RECEIPT, _receipt_text('moved', planned='|'.join(planned), moved='|'.join(moved),
                                                 guard_before=guard_before, **text), replace=True)
    marker = legacy / ('migrated-to-' + login + '-' + terminal_hash(data_root) + '.ini')
    if not marker.exists():
        try:
            _write_receipt(marker, _receipt_text('moved', planned='|'.join(planned), moved='|'.join(moved),
                                                 guard_before=guard_before, **text), replace=False)
        except FileExistsError:
            pass
    return dict(decision='moved', legacy=str(legacy), base=str(base), moved=moved)


# ------------------------------------------------------------- other terminals

def live_terminals():
    """Read-only Windows inventory of running MT5 terminals."""
    command = ('ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" '
               '| Select-Object ProcessId,ExecutablePath,CommandLine)')
    output = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True,
                                     encoding='utf-8-sig', timeout=20, creationflags=background_creationflags())
    rows = json.loads(output) if output.strip() else []
    if not isinstance(rows, list):
        raise ValueError('Complete terminal process inventory required')
    return rows


def candidate_data_roots(executable, appdata=None):
    """Every data folder a running terminal64.exe may be using."""
    install = Path(PureWindowsPath(executable).parent)
    roots = []
    if (install / 'MQL5').is_dir():
        roots.append(install)
    appdata = Path(appdata if appdata is not None else os.environ.get('APPDATA', '')) / 'MetaQuotes' / 'Terminal'
    if appdata.is_dir():
        for folder in appdata.iterdir():
            origin = folder / 'origin.txt'
            try:
                text = _read_text(origin)[0].strip().strip('\x00') if origin.is_file() else ''
            except (OSError, UnicodeDecodeError):
                continue
            if text and PureWindowsPath(text) == PureWindowsPath(str(install)):
                roots.append(folder)
    return roots


def other_terminal_conflicts(data_root, research_terminal, *, processes, appdata=None):
    """Other live terminals whose data folder resolves to this terminal's batch folder.

    Fails closed: a terminal whose program path or data folder cannot be read is
    reported as a conflict, never skipped.
    """
    own_root = PureWindowsPath(str(data_root))
    own_hash = terminal_hash(data_root)
    own_exe = PureWindowsPath(str(research_terminal))
    conflicts, seen = [], 0
    for row in processes:
        executable = row.get('ExecutablePath')
        if not isinstance(executable, str) or not executable.strip():
            conflicts.append(dict(pid=row.get('ProcessId'), executable='program path unreadable', data_root=None))
            continue
        image = PureWindowsPath(executable)
        if image == own_exe and seen == 0:
            seen += 1  # The selected terminal itself.
            continue
        roots = candidate_data_roots(executable, appdata)
        if not roots:
            conflicts.append(dict(pid=row.get('ProcessId'), executable=str(image), data_root=None))
        for root in roots:
            if PureWindowsPath(str(root)) == own_root or terminal_hash(root) == own_hash:
                conflicts.append(dict(pid=row.get('ProcessId'), executable=str(image), data_root=str(root)))
    return conflicts


# -------------------------------------------------------------------- preflight

def preflight(binding, account, *, observation=None, processes=None, appdata=None, controller_root=None):
    """Refuse native batch work unless this terminal's batch folder is its own."""
    version = binding['ea_version']
    login = valid_login(str(account['login']))
    server = valid_server(account['server'])
    base = binding_base(binding, account)
    relative = binding_relative(binding, account)
    result = dict(base=str(base), relative=relative, isolated=isolated(version))
    if not isolated(version):
        return result
    if observation is not None:
        reported = observation.get('state_base')
        if not isinstance(reported, str) or not reported:
            raise ValueError('The GOAT EA running on this terminal predates terminal isolation. Reload its chart with the updated EA, then retry.')
        if PureWindowsPath(reported) != PureWindowsPath(relative):
            raise ValueError('The GOAT EA on this terminal uses batch folder ' + reported + ', but this controller expects '
                             + relative + '. Check the account and terminal, then retry.')
    if processes is None:
        processes = live_terminals()
    conflicts = other_terminal_conflicts(binding['research_data_root'], binding['research_terminal'],
                                         processes=processes, appdata=appdata)
    unknown = next((c for c in conflicts if c['data_root'] is None), None)
    if unknown:
        raise ValueError('A running MT5 terminal (PID ' + str(unknown['pid']) + ', ' + unknown['executable'] + ') cannot be matched to '
                         'a data folder, so GOAT cannot prove it uses a different batch folder. Close it, or run it as this '
                         'Windows user, before starting a batch.')
    if conflicts:
        raise ValueError('Another running MT5 terminal (' + conflicts[0]['executable'] + ') resolves to this terminal\'s batch folder '
                         + relative + '. Close it, or give it its own data folder, before starting a batch.')
    runtime = (observation or {}).get('runtime') or {}
    capability = (observation or {}).get('recovery_capability') or {}
    flags = bool(runtime.get('batch_ongoing') or runtime.get('restart_pending') or capability.get('terminal_running'))
    result['migration'] = migrate_legacy(binding['common_files_root'], version, server, login,
                                         binding['research_data_root'], batch_flags=flags,
                                         controller_root=controller_root)
    return result


def controller_preflight(c, observation=None, *, processes=None, appdata=None):
    """preflight() for an opened Controller (seed starts and diagnostics)."""
    i = c.install
    binding = dict(ea_version=i['ea_version'], common_files_root=i['common_files_root'],
                   research_data_root=i['terminal_data_root'], research_terminal=i['terminal_executable'])
    return preflight(binding, c.session['account'], observation=observation, processes=processes,
                     appdata=appdata, controller_root=c.root)
