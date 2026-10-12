"""Batches run on GOAT's own research chart profile, GOAT Research (Claude-Mac goatai#2350 6120004490; Release 6119992056).

MT5 adds the auto-tested symbol's bare chart (id=0) to the chart profile it has open and saves it there when it
closes. Every batch type used to run MT5 on the GOAT monitor profile (GOAT-Studio-<session>), so each batch left
stray charts in it, and monitor-launch, the fix-B record (GOAT-EA#222) and goatai#2479's restore then refused that
profile on structure (extra_charts). A person cleaning it up by hand was undone by the next batch. Now:

- New packages bind ``research_profile='GOAT Research'`` (goat_studio.binding). The first /config launch names it as
  ProfileLast with a ``[StartUp]`` monitor expert and no Symbol (the monitor_launch shape); seed, catch-up and
  hold-up member INIs carry ``[Charts] ProfileLast=GOAT Research``. The monitor profile is never opened during a batch.
- prepare(): with MT5 stopped and the native gate held, an existing GOAT Research folder is MOVED ASIDE (never
  deleted) to ``<controller state>/research-profiles/<attempt>/`` with a manifest, and GOAT Research is recreated
  with one chart01.chr holding the monitor chart bytes (studio_onboarding.monitor_chart, expertmode=0). Every batch.
- restore(): a single-line ``[Charts] ProfileLast`` edit in common.ini from GOAT Research back to the monitor profile
  (studio_demo_deploy.patch_profile_last/write_exact, before and after bytes kept), only with MT5 stopped, no batch
  or seed slot active and the current value exactly GOAT Research. Seed, catch-up and hold-up call it at any
  terminal status and on cancel.
- migrate_monitor_profile(): a one-time move-aside, before the first GOAT Research batch on an installation, of the
  stray charts earlier batches left in the monitor profile (see migration_plan for the exact rules).
- batch_end_state(): the config-start end state (Mac option (i)): at the batch driver's finish, one normal close
  under close-terminal's checks and monitor-launch back onto the monitor profile; any refusal leaves MT5 as it is.

Every write here is either inside GOAT Research (GOAT-owned), a move-aside into controller state, or the one
ProfileLast line. Nothing is ever deleted except a source file whose verified copy already sits in controller state
(a cross-volume move).
"""
from contextlib import nullcontext
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sqlite3
from contextlib import closing

from studio_bridge import write_json
from studio_native_gate import exclusive_gate

RESEARCH_PROFILE = 'GOAT Research'
STATE_FOLDER = 'research-profiles'
MIGRATION_RECORD = 'monitor-profile-migration.json'
MIGRATION_JOURNAL = 'monitor-profile-migration.jsonl'
# A package prepared before batches ran on GOAT Research (its first start would open the monitor profile). Stable code:
# the goatai app/agent re-prepares the same plan under a new batch ID automatically on it (Claude-Mac goatai#2350
# 6120693275); documented in AGENT-START-HERE.md's refusal table. Running and paused batches finish as they are.
PACKAGE_REFUSAL_CODE = 'PACKAGE_PREDATES_RESEARCH_PROFILE'
LEGACY_PACKAGE_REFUSAL = ('This batch was prepared by an older GOAT; it will be prepared again. Nothing was started '
                          '(it was packaged before GOAT ran batches on its own GOAT Research chart profile, so starting it '
                          'would add charts to the GOAT Studio monitor profile).')
END_STATE_SKIPPED = 'END_STATE_SKIPPED:not_batch_process'
END_STATE_JOURNAL = 'end-state.jsonl'


def legacy_package_refusal(batch_id, kind='batch'):
    """The structured refusal for a package prepared before GOAT Research (PACKAGE_REFUSAL_CODE)."""
    from studio_refusal import Refusal
    return Refusal(LEGACY_PACKAGE_REFUSAL, PACKAGE_REFUSAL_CODE, batch_id=batch_id, kind=kind, prepare_again=True,
                   next_action='Prepare the same plan again under a new batch ID, then start that batch.')
ATTEMPT = re.compile(r'[A-Za-z0-9_.-]{1,120}')
BUSY_JOB_STATUSES = frozenset(('reserved', 'starting', 'running', 'reconcile_required', 'verifying'))
MAX_CHART_BYTES = 8_000_000
GATE_WAIT_SECONDS = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _is_link(path):
    path = Path(path)
    junction = getattr(os.path, 'isjunction', None)
    return path.is_symlink() or bool(junction and junction(path))


def profiles_root(controller):
    return Path(controller.install['terminal_data_root'])/'MQL5'/'Profiles'/'Charts'


def research_folder(controller):
    return profiles_root(controller)/RESEARCH_PROFILE


def _gate(controller, gate_held):
    return nullcontext() if gate_held else exclusive_gate(Path(controller.local)/'native-gate', wait_seconds=GATE_WAIT_SECONDS)


def _session(controller):
    session = getattr(controller, 'session', None)
    if isinstance(session, dict) and session.get('run_id'):
        return session
    from studio_installation import read_json
    return read_json(Path(controller.root)/'session.json')


# ---- INI and chart reading (read-only)

def _text(raw):
    return raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')


def config_profile(raw):
    """The [Charts] ProfileLast an MT5 startup INI names, else None. Read-only."""
    section, found = None, []
    for line in _text(raw).splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().casefold()
        elif section == 'charts' and line.partition('=')[0].strip().casefold() == 'profilelast':
            found.append(line.split('=', 1)[1].strip())
    return found[0] if len(found) == 1 else None


def research_profile_manifest(manifest):
    """True when every member INI of a seed/catch-up/hold-up manifest names GOAT Research as its ProfileLast.

    The INIs were hash-checked against the manifest by the runner's _read before this is called. A manifest prepared
    before this change (no [Charts] section) is a legacy package: it is refused at its first start and a batch of it
    that already started finishes as it is."""
    members = manifest.get('members') or []
    if not members:
        return False
    for member in members:
        try:
            if config_profile(Path(member['config_path']).read_bytes()) != RESEARCH_PROFILE:
                return False
        except (OSError, KeyError, TypeError, UnicodeError):
            return False
    return True


def parse_chart(raw):
    """dict(symbol, experts=[{name, path}], programs) of an MT5 .chr; ValueError when its structure is unreadable."""
    if len(raw) > MAX_CHART_BYTES:
        raise ValueError('chart file is larger than GOAT reads')
    try:
        text = _text(raw)
    except UnicodeError:
        raise ValueError('chart file is not UTF-8 or UTF-16 text') from None
    stack, symbol, experts, programs, closed = [], [], [], 0, False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        tag = re.fullmatch(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)>', line)
        if tag:
            ending, name = tag.groups()
            name = name.lower()
            if ending:
                if not stack or stack[-1] != name:
                    raise ValueError('chart file nesting is invalid')
                stack.pop()
                if name == 'chart' and not stack:
                    closed = True
            else:
                if closed or (not stack and name != 'chart') or len(stack) > 32:
                    raise ValueError('chart file structure is invalid')
                stack.append(name)
                if name == 'expert':
                    experts.append({})
                elif name == 'script':
                    programs += 1
            continue
        if not stack:
            raise ValueError('chart file content is outside its chart')
        key, sep, value = line.partition('=')
        if stack == ['chart'] and sep and key == 'symbol':
            symbol.append(value)
        elif stack == ['chart', 'expert'] and sep and key in ('name', 'path') and experts:
            experts[-1][key] = value
    if stack or not closed or len(symbol) != 1:
        raise ValueError('chart file structure is invalid')
    return dict(symbol=symbol[0], experts=experts, programs=programs)


def _goat_expert(controller, expert):
    relative = PureWindowsPath(controller.install['ea_relative_path'])
    allowed = (PureWindowsPath('Experts')/relative, PureWindowsPath(controller.install['terminal_data_root'])/'MQL5'/'Experts'/relative)
    return PureWindowsPath(expert.get('path') or '') in allowed


def _tree(folder):
    """Every file under ``folder`` (relative path, bytes, sha256), sorted; refuses links and junctions."""
    folder = Path(folder)
    if _is_link(folder):
        raise ValueError(str(folder)+' is a link or junction; GOAT never follows it')
    files = []
    for root, dirs, names in os.walk(folder):
        for name in dirs:
            if _is_link(Path(root)/name):
                raise ValueError(str(Path(root)/name)+' is a link or junction; GOAT never follows it')
        for name in names:
            path = Path(root)/name
            if _is_link(path):
                raise ValueError(str(path)+' is a link; GOAT never follows it')
            raw = path.read_bytes()
            files.append(dict(path=str(path.relative_to(folder)), bytes=len(raw), sha256=_digest(raw)))
    return sorted(files, key=lambda item: item['path'])


def _cross_volume(error):
    return getattr(error, 'winerror', None) == 17 or error.errno == errno.EXDEV


def _move_file(source, target):
    """Move one file into controller state. Across volumes: copy, fsync, verify the copy's SHA-256, then unlink the
    source (a move, never a delete: the verified copy is the file). Returns its sha256."""
    source, target = Path(source), Path(target)
    raw = source.read_bytes()
    digest = _digest(raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError(target.name+' already exists in the move-aside folder; nothing was moved')
    try:
        os.replace(source, target)
    except OSError as error:
        if not _cross_volume(error):
            raise
        with target.open('xb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        if _digest(target.read_bytes()) != digest:
            raise ValueError('The moved-aside copy of '+source.name+' does not verify; the original was kept') from None
        source.unlink()
    if _digest(target.read_bytes()) != digest:
        raise ValueError('The moved-aside '+target.name+' does not verify')
    return digest


def _move_tree(source, target):
    """Move a whole folder into controller state; the copy is verified file by file before any source file goes."""
    source, target = Path(source), Path(target)
    before = _tree(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError as error:
        if not _cross_volume(error):
            raise
        shutil.copytree(source, target)
        if _tree(target) != before:
            raise ValueError('The moved-aside copy of '+source.name+' does not verify; the original was kept') from None
        for item in before:
            (source/item['path']).unlink()
        for root, dirs, _ in sorted(os.walk(source), key=lambda row: -len(row[0])):
            for name in dirs:
                (Path(root)/name).rmdir()
        source.rmdir()
    if _tree(target) != before:
        raise ValueError('The moved-aside '+source.name+' does not verify')
    return before


def _record_folder(controller, attempt_id):
    """A new folder under <controller state>/research-profiles, named short whatever the attempt ID (a catch-up ID alone
    is up to 80 characters and paths stay under MAX_PATH): <UTC stamp>-<12 hex of the attempt ID>. The full attempt
    ID is in that folder's manifest.json."""
    if not isinstance(attempt_id, str) or not ATTEMPT.fullmatch(attempt_id) or attempt_id in ('.', '..'):
        raise ValueError('Research profile attempt ID must be 1..120 letters, digits, dot, underscore or hyphen')
    base = Path(controller.root)/STATE_FOLDER
    base.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+_digest(attempt_id.encode())[:12]
    for index in range(1, 1000):
        folder = base/(name if index == 1 else name+'.'+str(index))
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise ValueError('Too many research profile records for '+attempt_id)


# ---- prepare (every batch)

def chart_symbol(controller, fallback_symbol=None):
    """The symbol of GOAT Research's chart01: the monitor-prepare receipt's symbol, else (a session without one, never a
    config start) the batch's first member symbol."""
    from studio_installation import read_json
    receipt = Path(controller.root)/'monitor-profile.json'
    symbol = read_json(receipt).get('symbol') if receipt.is_file() else None
    if isinstance(symbol, str) and symbol:
        return symbol, 'monitor_profile'
    if fallback_symbol:
        return fallback_symbol, 'first_member'
    raise ValueError('No monitor profile receipt (monitor-prepare) and no member symbol for the research chart')


def prepare(controller, attempt_id, *, inspect, gate_held=False, fallback_symbol=None):
    """Reset GOAT Research for one batch with MT5 stopped and the native gate held. Raises ValueError before any launch.

    ``inspect()`` re-reads the selected MT5 (None = stopped). An existing GOAT Research folder is moved aside whole
    (never deleted) to <controller state>/research-profiles/<attempt>/GOAT Research, listed with every file's hash in
    that record's manifest.json; GOAT Research is then recreated with one chart01.chr = monitor_chart bytes."""
    from studio_onboarding import monitor_chart
    with _gate(controller, gate_held):
        if inspect() is not None:
            raise ValueError('MT5 is running, so GOAT did not prepare its GOAT Research chart profile; nothing was launched')
        symbol, source = chart_symbol(controller, fallback_symbol)
        raw = monitor_chart(controller, symbol)
        data = Path(controller.install['terminal_data_root']).resolve()
        base = profiles_root(controller)
        if not base.parent.resolve().is_relative_to(data) or (base.exists() and not base.resolve().is_relative_to(data)):
            raise ValueError('MT5 chart profiles folder escapes the selected data folder; nothing was changed')
        folder = research_folder(controller)
        record = _record_folder(controller, attempt_id)
        moved = None
        if folder.exists() or folder.is_symlink():
            if _is_link(folder) or not folder.is_dir():
                raise ValueError('GOAT Research in MT5 is not a plain folder; GOAT left it as it is and launched nothing')
            target = record/RESEARCH_PROFILE
            files = _move_tree(folder, target)
            moved = dict(from_path=str(folder), to_path=str(target), files=files)
        base.mkdir(parents=True, exist_ok=True)
        folder.mkdir()
        with (folder/'chart01.chr').open('xb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        receipt = dict(schema_version=1, kind='research_profile_prepared', attempt_id=attempt_id, profile=RESEARCH_PROFILE,
                       profile_path=str(folder), chart_symbol=symbol, chart_symbol_source=source,
                       chart_sha256=_digest(raw), chart_bytes=len(raw), moved_aside=moved, prepared_utc=utc_now())
        write_json(record/'manifest.json', receipt)
    return receipt | dict(manifest_path=str(record/'manifest.json'))


# ---- restore (ProfileLast back to the monitor profile)

def batch_active(controller):
    """The reason a batch or seed slot holds this terminal now, else None. Read-only."""
    from studio_installation import read_json
    root = Path(controller.root)
    slot = root/'seed-active.json'
    if slot.exists() and read_json(slot).get('status') != 'released':
        return 'seed_slot_active'
    database = root/'studio.sqlite'
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
            for (jobs,) in db.execute('SELECT jobs FROM studio_queues'):
                if any(job.get('status') in BUSY_JOB_STATUSES for job in json.loads(jobs) or []):
                    return 'native_batch_active'
    return None


def restore(controller, reason, *, inspect, gate_held=False):
    """Single-line ProfileLast edit from GOAT Research back to this session's monitor profile. Never raises.

    Only with MT5 stopped (``inspect()`` is None), no batch or seed slot active and common.ini naming exactly GOAT
    Research. The before and after common.ini bytes are kept (create-only) under research-profiles/restores."""
    try:
        from studio_demo_deploy import patch_profile_last, profile_last, write_exact
        from studio_agent_mailbox import sharing_retry
        from studio_onboarding import monitor_paths
        with _gate(controller, gate_held):
            if inspect() is not None:
                return dict(status='not_restored', reason='terminal_running')
            active = batch_active(controller)
            if active:
                return dict(status='not_restored', reason=active)
            name, _ = monitor_paths(controller, _session(controller))
            ini = Path(controller.install['terminal_data_root'])/'config'/'common.ini'
            raw = ini.read_bytes()
            if len(raw) > 4_000_000:
                return dict(status='not_restored', reason='common_ini_too_large')
            current = profile_last(raw)
            if current == name:
                return dict(status='not_needed', profile_last=current)
            if current != RESEARCH_PROFILE:
                return dict(status='not_restored', reason='profile_last_not_research', profile_last=current)
            patched = patch_profile_last(raw, RESEARCH_PROFILE, name)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            slug = re.sub(r'[^A-Za-z0-9_-]+', '-', str(reason))[:24].strip('-') or 'restore'   # the full reason is in restores.jsonl
            folder = Path(controller.root)/STATE_FOLDER/'restores'
            before, after = folder/(stamp+'-'+slug+'.common-before.ini'), folder/(stamp+'-'+slug+'.common-after.ini')
            write_exact(before, raw)
            write_exact(after, patched)
            temporary = ini.with_name(ini.name+'.goat-research-'+stamp)
            with temporary.open('xb') as handle:
                handle.write(patched); handle.flush(); os.fsync(handle.fileno())
            sharing_retry(lambda: os.replace(temporary, ini))
            if ini.read_bytes() != patched:
                return dict(status='not_restored', reason='readback_differs')
            entry = dict(reason=reason, restored_utc=utc_now(), profile_last_before=RESEARCH_PROFILE, profile_last_after=name,
                         common_ini_before_sha256=_digest(raw), common_ini_after_sha256=_digest(patched),
                         common_ini_before=str(before), common_ini_after=str(after))
            with (folder/'restores.jsonl').open('a', encoding='utf-8') as journal:
                journal.write(json.dumps(entry, sort_keys=True)+'\n'); journal.flush(); os.fsync(journal.fileno())
        return dict(status='restored', **entry)
    except Exception as error:     # restoring is a follow-up step: it never changes the outcome of the batch
        return dict(status='not_restored', reason=getattr(error, 'code', None) or 'check_failed', detail=str(error)[:300])


# ---- one-time migration of the monitor profile

def batch_history_symbols(controller):
    """Symbols this installation's controller records show MT5 tested: started native batches (queue rows with a
    launch intent: every member's tester Symbol) and started seed hunts, catch-ups and hold-up tests (state with an
    activation generation or an attempted member: every member's tester Symbol from its manifest). Read-only.
    A record that cannot be read adds nothing (the migration then refuses rather than guesses)."""
    from studio_seed_results import MAX_MANIFEST_BYTES, read_seed_json
    root = Path(controller.root)
    symbols, counts, unreadable = set(), dict(native=0, seed=0, catchup=0, holdup=0), []
    database = root/'studio.sqlite'
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
                for (jobs,) in db.execute('SELECT jobs FROM studio_queues'):
                    for job in json.loads(jobs) or []:
                        if not isinstance(job, dict) or 'launch_intent' not in job:
                            continue
                        configuration = job.get('configuration') or {}
                        members = configuration.get('batch_members') or [configuration]
                        found = {str((m.get('tester') or {}).get('Symbol')) for m in members if (m.get('tester') or {}).get('Symbol')}
                        if found:
                            counts['native'] += 1
                            symbols |= found
        except (sqlite3.Error, ValueError, TypeError, AttributeError) as error:
            unreadable.append('studio.sqlite: '+str(error)[:120])
    for kind, folder in (('seed', 'seeds'), ('catchup', 'catchups'), ('holdup', 'holdups')):
        base = root/folder
        if not base.is_dir():
            continue
        for run in sorted(base.iterdir()):
            try:
                if not (run/'state.json').is_file():
                    continue
                state = read_seed_json(run/'state.json')
                if state.get('generation') is None and not any((m or {}).get('attempts') for m in state.get('members') or []):
                    continue
                manifest = read_seed_json(run/'manifest.json', MAX_MANIFEST_BYTES)
                found = {str(m['tester']['Symbol']) for m in manifest.get('members') or [] if (m.get('tester') or {}).get('Symbol')}
                if found:
                    counts[kind] += 1
                    symbols |= found
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                unreadable.append(folder+'/'+run.name+': '+str(error)[:120])
    return dict(symbols=sorted(symbols), runs=counts, unreadable=unreadable)


def migration_plan(controller):
    """Read-only: what the one-time migration would do to this installation's monitor profile. Never raises.

    The rules (Claude-Mac goatai#2350 6120004490): in this installation's own GOAT-Studio-* monitor profile,
    - chart01.chr is the monitor chart and is always kept; it must carry exactly one EA, the installed GOAT EA;
    - every other chart file with NO expert (and no script) whose symbol appears in this installation's batch history
      (batch_history_symbols) is moved aside;
    - anything else (a chart carrying any EA or script, a bare chart of a symbol never in batch history, an unreadable
      chart, a link, a folder, or a file MT5 does not save there besides order.wnd) refuses the whole migration and
      nothing is touched.
    status: 'clean' (nothing to move), 'movable' (move lists the charts) or 'refused' (reasons lists every problem)."""
    try:
        from studio_onboarding import monitor_paths
        name, profile = monitor_paths(controller, _session(controller))
    except Exception as error:
        return dict(status='refused', reasons=[dict(check='session', plain='GOAT could not read this installation\'s '
                                                    'session to find its monitor profile ('+str(error)[:160]+').')])
    plan = dict(profile_name=name, profile_path=str(profile), keep=None, move=[], reasons=[])
    def refuse(check, plain, **facts):
        plan['reasons'].append(dict(check=check, plain=plain, **facts))
    try:
        if _is_link(profile) or not profile.is_dir():
            refuse('profile_missing', 'The GOAT Studio monitor profile '+name+' is not a plain folder in MT5.')
            return plan | dict(status='refused')
        charts = []
        for entry in sorted(profile.iterdir(), key=lambda p: p.name.lower()):
            if _is_link(entry) or not entry.is_file():
                refuse('unexpected_item', entry.name+' in '+name+' is a link or a folder; GOAT never moves it.', item=entry.name)
            elif entry.suffix.lower() == '.chr':
                charts.append(entry)
            elif entry.name.lower() != 'order.wnd':
                refuse('unexpected_item', entry.name+' in '+name+' is not a file MT5 saves in a chart profile.', item=entry.name)
        monitor = next((chart for chart in charts if chart.name.lower() == 'chart01.chr'), None)
        if monitor is None:
            refuse('monitor_chart_missing', 'The monitor profile '+name+' has no chart01.chr, the GOAT monitor chart.')
        else:
            raw = monitor.read_bytes()
            try:
                parsed = parse_chart(raw)
                if len(parsed['experts']) != 1 or parsed['programs'] or not _goat_expert(controller, parsed['experts'][0]):
                    refuse('monitor_chart_not_goat', 'chart01.chr in '+name+' does not carry exactly the installed GOAT EA.')
                plan['keep'] = dict(file=monitor.name, symbol=parsed['symbol'], sha256=_digest(raw), bytes=len(raw))
            except ValueError as error:
                refuse('chart_unreadable', 'chart01.chr in '+name+' cannot be read ('+str(error)+').', file=monitor.name)
        history = batch_history_symbols(controller)
        plan['batch_history'] = history
        for chart in charts:
            if chart is monitor:
                continue
            raw = chart.read_bytes()
            try:
                parsed = parse_chart(raw)
            except ValueError as error:
                refuse('chart_unreadable', chart.name+' in '+name+' cannot be read ('+str(error)+'); GOAT never moves it.', file=chart.name)
                continue
            if parsed['experts'] or parsed['programs']:
                names = ', '.join(e.get('name') or PureWindowsPath(e.get('path') or '?').stem for e in parsed['experts']) or 'a script'
                refuse('chart_with_program', chart.name+' ('+parsed['symbol']+') in '+name+' runs '+names+
                       '; GOAT never moves a chart that carries an EA or script.', file=chart.name, symbol=parsed['symbol'])
            elif parsed['symbol'] not in history['symbols']:
                refuse('symbol_not_in_batch_history', chart.name+' is a bare '+parsed['symbol']+' chart, and no batch, seed hunt, '
                       'catch-up or hold-up test of this installation ever tested '+parsed['symbol']+', so GOAT did not add it.',
                       file=chart.name, symbol=parsed['symbol'])
            else:
                plan['move'].append(dict(file=chart.name, symbol=parsed['symbol'], sha256=_digest(raw), bytes=len(raw)))
    except Exception as error:
        refuse('check_failed', 'GOAT could not read the monitor profile '+name+' ('+str(error)[:160]+').')
    if plan['reasons']:
        return plan | dict(status='refused', move=[], plain=' '.join(r['plain'] for r in plan['reasons'])+
                           ' Nothing in the monitor profile was moved.')
    return plan | dict(status='movable' if plan['move'] else 'clean')


def migration_done(controller):
    from studio_installation import read_json
    path = Path(controller.root)/STATE_FOLDER/MIGRATION_RECORD
    try:
        return path.is_file() and read_json(path).get('status') in ('migrated', 'clean')
    except (OSError, ValueError):
        return False


def pending_set_aside(controller):
    """For a start driver's pre-close health read before the migration ran: the chart files the migration will move
    aside right after that close (only when the plan is 'movable'). The record after the close still checks the real
    folder in full. Never raises; () when nothing applies."""
    try:
        if migration_done(controller):
            return ()
        plan = migration_plan(controller)
        return tuple(item['file'] for item in plan['move']) if plan['status'] == 'movable' else ()
    except Exception:
        return ()


def _inventory(profile):
    return [dict(file=p.name, bytes=p.stat().st_size, sha256=_digest(p.read_bytes()))
            for p in sorted(Path(profile).iterdir(), key=lambda p: p.name.lower()) if p.is_file() and not _is_link(p)]


def migrate_monitor_profile(controller, attempt_id, *, inspect, gate_held=False):
    """The one-time migration (see migration_plan), only with MT5 stopped and the native gate held. Never raises.

    Returns dict(status='already'|'clean'|'migrated'|'refused'|'failed', ...). 'migrated' moves every planned chart to
    <controller state>/research-profiles/<attempt>/monitor-profile/ (never deleted) and writes a receipt with the
    folder's before and after hashes; 'clean' and 'migrated' are recorded once (MIGRATION_RECORD) and never run again.
    A refusal touches nothing and is journaled; the next batch start tries again."""
    root = Path(controller.root)/STATE_FOLDER
    try:
        if migration_done(controller):
            return dict(status='already', record=str(root/MIGRATION_RECORD))
        with _gate(controller, gate_held):
            if inspect() is not None:
                return dict(status='refused', reasons=[dict(check='terminal_running', plain='MT5 is running; the migration runs only with MT5 stopped.')])
            plan = migration_plan(controller)
            root.mkdir(parents=True, exist_ok=True)
            if plan['status'] == 'refused':
                with (root/MIGRATION_JOURNAL).open('a', encoding='utf-8') as journal:
                    journal.write(json.dumps(dict(attempt_id=attempt_id, status='refused', utc=utc_now(), reasons=plan['reasons']),
                                             sort_keys=True)+'\n')
                return plan
            profile = Path(plan['profile_path'])
            before = _inventory(profile)
            receipt = dict(schema_version=1, kind='monitor_profile_migration', attempt_id=attempt_id, profile_name=plan['profile_name'],
                           profile_path=plan['profile_path'], kept=plan['keep'], batch_history=plan['batch_history'],
                           before=before, before_sha256=_digest(json.dumps(before, sort_keys=True).encode()), moved=[])
            if plan['status'] == 'movable':
                current = {item['file']: item['sha256'] for item in before}
                changed = [item['file'] for item in plan['move'] if current.get(item['file']) != item['sha256']]
                if changed or current.get(plan['keep']['file']) != plan['keep']['sha256']:
                    return dict(status='refused', reasons=[dict(check='changed', plain='The monitor profile changed while GOAT '
                                'checked it; nothing was moved.')])
                record = _record_folder(controller, attempt_id)
                target = record/'monitor-profile'
                for item in plan['move']:
                    _move_file(profile/item['file'], target/item['file'])
                    receipt['moved'].append(dict(item, to_path=str(target/item['file'])))
                receipt['move_aside_folder'] = str(target)
            after = _inventory(profile)
            receipt.update(status='migrated' if receipt['moved'] else 'clean', after=after,
                           after_sha256=_digest(json.dumps(after, sort_keys=True).encode()), migrated_utc=utc_now())
            if receipt['moved']:
                write_json(Path(receipt['move_aside_folder']).parent/'manifest.json', receipt)
            write_json(root/MIGRATION_RECORD, receipt)
        return receipt
    except Exception as error:
        return dict(status='failed', reason='check_failed', detail=str(error)[:300],
                    plain='The monitor profile migration stopped part-way ('+str(error)[:160]+'); every chart it moved is in '
                          'controller state under research-profiles and nothing was deleted.')


# ---- read-only status for agents and the pilot

def status(controller):
    """Read-only: ProfileLast, the monitor profile's charts, the migration plan/record and GOAT Research's files."""
    from studio_demo_deploy import profile_last
    from studio_installation import read_json
    result = dict(research_profile=RESEARCH_PROFILE)
    try:
        result['profile_last'] = profile_last((Path(controller.install['terminal_data_root'])/'config'/'common.ini').read_bytes())
    except (OSError, ValueError, UnicodeError) as error:
        result['profile_last'] = None; result['profile_last_error'] = str(error)[:160]
    plan = migration_plan(controller)
    result['monitor_profile'] = dict(name=plan.get('profile_name'), path=plan.get('profile_path'))
    try:
        result['monitor_profile']['files'] = _inventory(plan['profile_path'])
    except (OSError, KeyError, TypeError) as error:
        result['monitor_profile']['error'] = str(error)[:160]
    record = Path(controller.root)/STATE_FOLDER/MIGRATION_RECORD
    result['migration'] = read_json(record) if record.is_file() else dict(status='not_run', plan=plan)
    folder = research_folder(controller)
    try:
        result['goat_research'] = dict(path=str(folder), files=_tree(folder) if folder.is_dir() else None)
    except (OSError, ValueError) as error:
        result['goat_research'] = dict(path=str(folder), error=str(error)[:160])
    return result


# ---- config-start end state (Mac option (i))

def monitor_launch_preflight(controller):
    """Every check monitor-launch makes that can be read while MT5 still runs, so a refusal leaves MT5 open.
    Returns None when monitor-launch would accept, else the plain reason. The healthy-chart check may retire a record
    whose binding changed, exactly as monitor-launch would."""
    from studio_onboarding import (check_healthy_chart, require_demo_binding, require_unprotected, saved_launch_policy,
                                   session_state, verify_monitor_profile)
    from studio_installation import read_json
    session, _ = session_state(controller)
    require_unprotected(session['account']['login'])
    require_demo_binding(controller, session)
    with exclusive_gate(Path(controller.local)/'native-gate', wait_seconds=GATE_WAIT_SECONDS):
        healthy = check_healthy_chart(controller, session)
        verify_monitor_profile(controller, read_json(Path(controller.root)/'monitor-profile.json'), healthy_chart=healthy['record'])
    saved_launch_policy(controller, session)
    preset = Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
    if preset.read_bytes() != 'Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'):
        raise ValueError('Monitor startup preset changed; preserve it before repair')
    return None


def _same_identity(a, b):
    """The same process: PID, creation time and image (a reused PID is another process)."""
    return (isinstance(a, dict) and isinstance(b, dict) and type(a.get('pid')) is int and a.get('pid') == b.get('pid')
            and bool(a.get('created_utc')) and a.get('created_utc') == b.get('created_utc')
            and PureWindowsPath(str(a.get('executable') or '')) == PureWindowsPath(str(b.get('executable') or '')))


def active_config_path(controller, job_id):
    """The /config file the GOAT EA relaunches MT5 with between this batch's members (Optimizer.mqh ActivatePending:
    <batch base>\\active_optimization_config.ini, the base of this package's binding and account)."""
    from studio_installation import read_json
    from studio_terminal_isolation import binding_base
    plan = read_json(Path(controller.root)/'packages'/job_id/'studio-plan.json')
    return Path(binding_base(plan['research_binding'], controller.session['account']))/'active_optimization_config.ini'


def _config_args(line):
    return [PureWindowsPath(match.strip('"')) for match in re.findall(r'/config:("[^"]+"|\S+)', line or '', re.I)]


def batch_process_binding(controller, job_id, record, process):
    """Is the selected MT5 running now the one this batch launched? (Claude-Mac goatai#2350 6120693275 point 4)

    The driver journals ``batch_process`` (pid, image, creation time) at the batch's /config launch. The running MT5
    is the batch's when it is exactly that process, or a later process whose command line names this batch's own
    member /config file (the GOAT EA's relaunch between members): then that later process is the batch's last launch
    and is journaled as ``batch_process``. No record, a different PID, the same PID with another creation time, or any
    other command line: not_batch_process. Returns dict(status='batch_process'|'not_running'|'not_batch_process', ...)."""
    recorded = record.get('batch_process')
    if not (isinstance(recorded, dict) and type(recorded.get('pid')) is int and recorded.get('created_utc')):
        return dict(status='not_batch_process', reason='no_batch_process_record')
    running = process.inspect()
    if running is None:
        return dict(status='not_running', process=None, recorded=recorded)
    if _same_identity(running, recorded):
        return dict(status='batch_process', process=running, source=recorded.get('source'))
    from studio_seed_process import created_unix
    reader = getattr(process, 'command_line', None)
    newer = (created_unix(running.get('created_utc')) or 0) > (created_unix(recorded.get('created_utc')) or float('inf'))
    if reader is not None and newer and PureWindowsPath(str(running.get('executable') or '')) == PureWindowsPath(str(recorded.get('executable') or '')):
        config = active_config_path(controller, job_id)
        if any(str(arg).casefold() == str(PureWindowsPath(config)).casefold() for arg in _config_args(reader(running))):
            relaunch = dict({k: running.get(k) for k in ('pid', 'executable', 'created_utc')}, source='ea_member_relaunch',
                            config=str(config), previous=recorded, recorded_utc=utc_now())
            record['batch_process'] = relaunch          # the batch's last launch, journaled by the driver
            return dict(status='batch_process', process=running, source='ea_member_relaunch')
    return dict(status='not_batch_process', reason='different_process', running=running, recorded=recorded)


def _journal_end_state(controller, entry):
    folder = Path(controller.root)/STATE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/END_STATE_JOURNAL).open('a', encoding='utf-8') as journal:
        journal.write(json.dumps(dict(entry, utc=utc_now()), sort_keys=True, default=str)+'\n')
        journal.flush(); os.fsync(journal.fileno())


def batch_end_state(controller, job_id, record, *, process=None, inspect=None):
    """At the batch driver's finish: one normal close of the batch's MT5 and monitor-launch back onto the monitor profile.

    Within the batch's consent (studio_config_start.RESTART_CONSENT_SCOPE). The close is close-terminal's own (demo,
    Algo Trading off, no positions/orders, idle tester, no batch/seed/native job, not an Open Lab login); before it,
    every monitor-launch check that can be read with MT5 running must pass. Any refusal before the close leaves MT5
    exactly as it is, with the plain reason; nothing loops or retries. Never raises.

    Binding (Claude-Mac goatai#2350 6120693275 point 4): only the MT5 this batch launched may be closed
    (batch_process_binding; re-checked by close-terminal under the gate right before the close). Any other MT5 is left
    as it is: status 'skipped', code END_STATE_SKIPPED:not_batch_process, journaled in research-profiles/end-state.jsonl."""
    from studio_config_start import CONFIG_START_LANES, RESTART_CONSENT_SCOPE
    result = dict(status='left_as_is', job_id=job_id)
    session = getattr(controller, 'session', {}) or {}
    kind = session.get('authority_kind')
    if kind not in CONFIG_START_LANES:
        return dict(status='not_applicable', reason='lane')
    attempt = record.get('attempt_id') or ''
    if not re.fullmatch(r'[a-f0-9]{64}', attempt):
        return result | dict(reason='no_attempt', plain='GOAT has no exact attempt for this batch, so it left MT5 as it is.')
    if kind == 'native_human_control':
        consent = record.get('mt5_restart_consent') or {}
        if consent.get('granted') is not True or consent.get('scope') != RESTART_CONSENT_SCOPE:
            return result | dict(reason='consent_scope', plain='This batch\'s MT5 consent did not cover closing and reopening '
                                 'MT5 at its end, so GOAT left MT5 as it is.')
    end_id = 'batch-end-'+attempt[:32]
    from studio_seed_process import WindowsSeedProcess
    process = process or WindowsSeedProcess(controller)
    try:
        bound = batch_process_binding(controller, job_id, record, process)
    except Exception as error:
        bound = dict(status='not_batch_process', reason='check_failed', detail=str(error)[:300])
    result['batch_process'] = bound
    if bound['status'] == 'not_batch_process':
        # Never close an MT5 this batch did not launch (a person restarted it, another terminal, or no record): MT5 is
        # left as it is and the next GOAT stop restores ProfileLast lazily (close-terminal, a batch's own end state).
        _journal_end_state(controller, dict(job_id=job_id, attempt_id=attempt, code=END_STATE_SKIPPED, binding=bound))
        return result | dict(status='skipped', reason=END_STATE_SKIPPED, code=END_STATE_SKIPPED,
                             plain='The MT5 running now is not the one this batch launched, so GOAT did not close it. MT5 was '
                                   'left as it is; GOAT moves its saved chart profile back to the GOAT Studio monitor the next '
                                   'time it stops MT5.')
    try:
        monitor_launch_preflight(controller)
    except Exception as error:
        return result | dict(reason='monitor_not_launchable', detail=str(error)[:400], failed_checks=getattr(error, 'fields', {}).get('failed_checks'),
                             plain='GOAT could not reopen its monitor yet ('+str(error)[:200]+'), so it left MT5 open on the batch\'s '
                                   'GOAT Research chart profile, which also carries the GOAT monitor.')
    from studio_agent_setup import close_terminal
    try:
        closed = close_terminal(controller, end_id, process=process, inspect=inspect,
                                expected_process=bound.get('process'))
    except Exception as error:
        if getattr(error, 'code', None) == END_STATE_SKIPPED:     # another MT5 appeared right before the close
            _journal_end_state(controller, dict(job_id=job_id, attempt_id=attempt, code=END_STATE_SKIPPED, binding=dict(error.fields)))
            return result | dict(status='skipped', reason=END_STATE_SKIPPED, code=END_STATE_SKIPPED, detail=str(error)[:400],
                                 plain='The MT5 running now is not the one this batch launched, so GOAT did not close it.')
        return result | dict(reason='close_refused', detail=str(error)[:400],
                             plain='GOAT did not close MT5 at the end of the batch ('+str(error)[:200]+'); MT5 was left as it is.')
    result['close'] = {k: closed.get(k) for k in ('attempt_id', 'phase', 'status', 'method', 'stopped_utc', 'monitor_chart_record',
                                                 'research_profile_restore')}
    if closed.get('phase') not in ('stopped', 'already_stopped'):
        return result | dict(status='close_unresolved', reason='close_outcome_unresolved',
                             plain='GOAT asked MT5 to close normally at the end of the batch and did not see it stop; it will not '
                                   'repeat the close or launch. If MT5 is closed, open it normally; it opens the GOAT Studio monitor.')
    # close-terminal already moved ProfileLast back after its stop (research_profile_restore); this is idempotent.
    result['restore'] = restore(controller, 'batch-end:'+job_id, inspect=process.inspect)
    try:
        from studio_onboarding import monitor_launch
        launched = monitor_launch(controller, end_id)
    except Exception as error:
        return result | dict(status='closed_not_reopened', reason='monitor_launch_refused', detail=str(error)[:400],
                             plain='GOAT closed MT5 at the end of the batch but monitor-launch refused ('+str(error)[:200]+'). '
                                   'MT5 is closed; opening it normally opens the GOAT Studio monitor profile.')
    result['launch'] = {k: launched.get(k) for k in ('attempt_id', 'status', 'pid', 'startup_config', 'startup_sha256',
                                                     'saved_chart_sha256', 'observed_healthy_chart', 'reused')}
    return result | dict(status='monitor_relaunched', reason=None,
                         plain='The batch ended; GOAT closed MT5 once and reopened it on the GOAT Studio monitor with Algo '
                               'Trading off. Process start is not runtime readiness: run onboarding-status.')
