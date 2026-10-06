"""Read-only research status for one installation: what a UI lane or agent needs.

Nothing here opens the mutable store, takes the terminal lock, launches, closes
or signals MT5. The database is read with ``mode=ro`` and every native file is
read with a size bound. Missing or unreadable evidence is reported as unknown
with a plain reason, never synthesised.

The monitor classification is shared with batch pause: a pause never waits
silently. When the bound monitor is closed, unbound or unlicensed it names the
blocker in one sentence and says how to fix it.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import statistics
import time

from campaign_ledger import packed
from studio_export_qualification import (SCHEMA as QUALIFICATION_SCHEMA, below_score_units, public_thresholds, read_run_thresholds, stamp_set,
                                         summarize, threshold_words)

HEARTBEAT_FRESH_SECONDS = 20
RELAUNCH_GRACE_SECONDS = 240
ACTIVE = frozenset(('reserved', 'starting', 'running', 'reconcile_required', 'verifying'))
TERMINAL = frozenset(('completed', 'cancelled', 'failed'))
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TIMELINE_BYTES = 64 * 1024 * 1024
MIN_FREE_BYTES = 5 * 1024 ** 3
# Activation reasons the EA writes while it has no usable GOAT sign-in.
UNLICENSED = frozenset(('awaiting_approval', 'waiting_for_host_activation', 'host_activation_cooldown',
                        'activation_not_pending', 'ACTIVATION_RELOAD_REQUIRED', 'activation_reload_pending',
                        'activation_storage_error', 'network_error', 'service_error', 'build_not_admitted',
                        'webrequest_permission_required', 'rate_limited'))
REPAIR_FIX = ('Re-pair it: the GOAT chart in this MT5 shows a connection code; approve it in the GOAT portal '
              '(your agent can read the code). Paused or running work continues by itself once the monitor reports again.')
ACTIVATION_HELP = {
    'build_not_admitted': ('GOAT refused this EA build at sign-in, so its monitor cannot start.',
                           'Install the approved GOAT build on this terminal, then reopen MT5.'),
    'webrequest_permission_required': ('MT5 is blocking the GOAT sign-in request.',
                                       'In MT5 Tools > Options > Expert Advisors, allow WebRequest for the GOAT address, then reload the GOAT chart.'),
    'rate_limited': ('GOAT sign-in is rate limited for this terminal; it retries by itself in about 15 minutes.',
                     'Nothing to do: wait for the automatic retry.'),
    'network_error': ('This terminal cannot reach GOAT to sign in.',
                      'Check this PC is online; the EA retries every minute by itself.'),
}


def _bounded_json(path, limit=MAX_JSON_BYTES):
    """(value, mtime) or (None, None). Observation-only; never raises on bad evidence."""
    try:
        path = Path(path)
        if not path.is_file():
            return None, None
        before = path.stat()
        if before.st_size > limit:
            return None, None
        raw = path.read_bytes()
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        return json.loads(text), before.st_mtime
    except (OSError, ValueError, UnicodeError):
        return None, None


def terminal_token(install):
    """Same token as the EA's GoatTerminalToken: the data folder's last component."""
    return PureWindowsPath(install['terminal_data_root']).name or Path(install['terminal_data_root']).name


def activation(install, login=None):
    """This terminal's EA sign-in status (operational metadata only), plus other terminals'.

    Read from the EA's own ``GOAT/activation-status-<data folder>.json`` (the same
    file studio_onboarding reads); a status written for another account is ignored.
    """
    folder = Path(install['common_files_root']) / 'GOAT'
    own = terminal_token(install)
    mine, others = None, []
    try:
        candidates = sorted(folder.glob('activation-status-*.json')) if folder.is_dir() else []
    except OSError:
        candidates = []
    for path in candidates[:64]:
        value, _ = _bounded_json(path, 64 * 1024)
        if not isinstance(value, dict) or not isinstance(value.get('reason'), str):
            continue
        observed = value.get('observedAtUtc')
        item = dict(reason=value['reason'], observed_utc=observed if type(observed) is int else None)
        if path.name == 'activation-status-' + own + '.json':
            if login is None or value.get('accountId') in (None, '', str(login)):
                mine = item
        else:
            others.append(item)
    return mine, others


def monitor_state(install, session, local, *, now, process='unknown'):
    """Classify the bound Studio monitor from its own heartbeat and sign-in evidence.

    ``process`` is the selected terminal identity, ``None`` when MT5 is closed or
    ``'unknown'`` when the caller could not inspect processes. Returns ``ticking``
    (a fresh bound agent-owned heartbeat), ``transient`` (an ordinary member-boundary
    relaunch) and, otherwise, a ``blocker`` with a one-sentence reason and fix.
    """
    observation, modified = _bounded_json(Path(local) / 'ui-observation.json')
    age = None if modified is None else max(0.0, now - modified)
    runtime = observation.get('runtime') if isinstance(observation, dict) and isinstance(observation.get('runtime'), dict) else {}
    mine, others = activation(install, (session.get('account') or {}).get('login'))
    result = dict(heartbeat_age_seconds=None if age is None else round(age, 1),
                  heartbeat_wall=modified, bound=None, loaded=None, owner=None,
                  tester_state=runtime.get('tester_state'), batch_ongoing=runtime.get('batch_ongoing'),
                  restart_pending=runtime.get('restart_pending'), connected=runtime.get('connected'),
                  terminal_build=runtime.get('terminal_build'),
                  ea_build=observation.get('build') if isinstance(observation, dict) else None,
                  activation=mine, ticking=False, transient=False, blocker=None)
    if isinstance(observation, dict):
        result.update(bound=observation.get('bound'), loaded=observation.get('loaded'), owner=observation.get('owner'))
    signed_out = mine is not None and mine['reason'] in UNLICENSED and (
        modified is None or mine['observed_utc'] is None or mine['observed_utc'] >= modified - 5)

    def block(state, code, message, fix):
        result.update(state=state, blocker=dict(code=code, message=message, fix=fix))
        return result

    if process is None:
        return block('closed', 'terminal_closed', 'MT5 for this terminal is closed.',
                     'Open this MT5 terminal; the GOAT monitor reports again within a minute.')
    fresh = age is not None and age <= HEARTBEAT_FRESH_SECONDS
    if fresh and isinstance(observation, dict):
        if observation.get('owner') == 'human':
            return block('human_owned', 'human_took_control', 'You took control in MT5, so the agent no longer drives this terminal.',
                         'Give to Agent in the GOAT Studio panel when you want the agent to continue.')
        if observation.get('bound') is not True or observation.get('loaded') is not True:
            return block('unbound', 'monitor_unbound', 'The GOAT monitor in MT5 is running but is not bound to this controller session.',
                         'Reopen the GOAT Studio monitor chart for this installation (onboarding-status names the exact chart).')
        if observation.get('run_id', session.get('run_id')) != session.get('run_id'):
            return block('other_session', 'monitor_other_session', 'The GOAT monitor in MT5 belongs to a different controller session.',
                         'Inspect switch-status before using this installation.')
        result.update(state='ticking', ticking=True)
        return result
    if signed_out:
        reason = mine['reason']
        if reason in ACTIVATION_HELP:
            message, fix = ACTIVATION_HELP[reason]
            return block('unlicensed', 'monitor_' + reason, message, fix)
        replaced = any(item['reason'] == 'approved' and item['observed_utc'] is not None
                       and (modified is None or item['observed_utc'] >= modified - 5) for item in others)
        if replaced:
            return block('unlicensed', 'monitor_unlicensed',
                         "This terminal's GOAT sign-in was replaced by another terminal — re-pair it.", REPAIR_FIX)
        return block('unlicensed', 'monitor_unlicensed',
                     "This terminal's GOAT EA is waiting for its sign-in to be approved — re-pair it.", REPAIR_FIX)
    if age is None:
        return block('never_reported', 'monitor_never_reported', 'The GOAT monitor has not reported from this terminal yet.',
                     'Open the GOAT Studio monitor chart in this MT5 (onboarding-status names it) and allow DLL imports.')
    if age <= RELAUNCH_GRACE_SECONDS:
        result.update(state='relaunching', transient=True)
        return result
    minutes = max(1, int(age // 60))
    return block('silent', 'monitor_silent', 'The GOAT monitor in MT5 stopped reporting ' + str(minutes) + ' minute'
                 + ('s' if minutes != 1 else '') + ' ago.',
                 'Check the GOAT chart is still open in this MT5 with DLL imports allowed; if it shows a connection code, approve it.')


def queue_jobs(root, session):
    """Retained Studio queue rows, read-only. Never reconciles or mutates."""
    database = Path(root) / 'studio.sqlite'
    if not database.is_file():
        return []
    binding = packed(dict(terminal_id=session['terminal_id'], run_id=session['run_id']))
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
    return json.loads(row[0]) if row else []


def _local_epoch(text):
    try:
        return time.mktime(time.strptime(text, '%Y.%m.%d %H:%M:%S'))
    except (ValueError, OverflowError, TypeError):
        return None


def timeline(native_run, aliases):
    """Lenient per-member native timing: last OnGoing start and end per member."""
    path = Path(native_run) / 'timeline.tsv'
    try:
        if not path.is_file() or path.stat().st_size > MAX_TIMELINE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    except UnicodeError:
        return None
    lines = text.splitlines()
    if not lines or lines[0] != 'LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails':
        return None
    index = {alias: i for i, alias in enumerate(aliases)}
    started, ended, outcome = {}, {}, {}
    for line in lines[1:]:
        fields = line.split('\t')
        if len(fields) != 6 or fields[2] != 'QUEUE_STATE':
            continue
        alias = fields[3].rsplit(':', 1)[-1]
        if alias not in index:
            continue
        stamp = _local_epoch(fields[0])
        if stamp is None:
            continue
        i = index[alias]
        if fields[4] == 'OnGoing':
            started[i] = stamp
            ended.pop(i, None)
        elif fields[4] in ('Completed', 'Cancelled', 'Error'):
            ended[i] = stamp
            outcome[i] = fields[4]
    return dict(started=started, ended=ended, outcome=outcome)


ITEM_STATS_HEADER = 'LocalTime\tSymbol\tStrategy\tStatus\tXmlRows\tUniqueRows\tTopScore\tFinalExports\tDetails'
MAX_ITEM_STATS_BYTES = 16 * 1024 * 1024
NO_PROFITABLE_PASSES = 'no_profitable_passes'
NO_QUALIFYING_ROWS = 'no_qualifying_rows'
# Sets scored high enough with the forward period, but every one re-tested over the export
# window lost money, so the EA exported nothing and wrote a plain Error row (goatai#1885).
NO_PROFITABLE_EXPORTS = 'no_profitable_exports'
OUTCOME_ORDER = (NO_PROFITABLE_PASSES, NO_QUALIFYING_ROWS, NO_PROFITABLE_EXPORTS)
# item_stats.tsv Status -> the one outcome a row with that status may carry.
RESEARCH_OUTCOME_STATUSES = {'NoProfitablePasses': NO_PROFITABLE_PASSES, 'NoQualifyingRows': NO_QUALIFYING_ROWS}
MAX_NO_EDGE_LISTED = 200
MAX_LOG_BYTES = 64 * 1024 * 1024
_DATE = re.compile(r'\d{4}\.\d{2}\.\d{2}')
_LOG_LINE = re.compile(r'(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}) \d{2}:\d{2}:\d{2}\s+(.*)')
_EXPORT_SEQUENCE = re.compile(r'Export sequence complete: (\d+) attempts \S (\d+) profitable, (\d+) losses, (\d+) errors, '
                              r'(\d+) duplicates, (\d+) passed thresholds\.')
_EXPORT_DISCARDED = re.compile(r'Export Profit=(-?\d+(?:\.\d+)?)<0, Discarding completed Set')
_TOP_ROWS = re.compile(r'SXmlData::WriteTopToXml: wrote \d+ distinct row\(s\) \(Score≥(\d+(?:\.\d+)?)\)')
_BACK_RANGE = re.compile(r'Extracted Back Test range: (\d{4}\.\d{2}\.\d{2}) - (\d{4}\.\d{2}\.\d{2})$')
_FORWARD_DATE = re.compile(r'Forward Date Extracted: (\d{4}\.\d{2}\.\d{2})$')
_EXPORT_DATES = re.compile(r'Adjusting Test Dates, StartDate=(\d{4}\.\d{2}\.\d{2}) EndDate=(\d{4}\.\d{2}\.\d{2})$')


def _no_qualifier_outcome(values, outcome):
    """``outcome`` extended with the forward-merge evidence of a NoQualifyingRows row, or None.

    Mirrors the EA guard (XmlProcessor.mqh GoatXmlNoQualifierOutcome) exactly: the
    same whole-report proof as no_profitable_passes, at least one kept pass (profitable
    with enough trades), every kept pass found once in a whole forward report with
    matching back values and inputs, and a best combined score below the export score.
    A forward report that is partial, unreadable or disagrees with the back report is
    never accepted: that member stays a real error.
    """
    try:
        extra = dict(back_rows=int(values['back_rows']), forward_matched=int(values['forward_matched']),
                     forward_discarded=int(values['forward_discarded']), forward_mismatches=int(values['forward_mismatches']),
                     forward_malformed=int(values['forward_malformed']),
                     best_combined_score=float(values['best_combined_score']), score_threshold=float(values['score_threshold']))
    except (KeyError, ValueError):
        return None
    o, x = outcome, extra
    span, passes, kept = o['window'], o['passes'], x['back_rows']
    if (passes <= 0 or not 1 <= kept <= o['profitable'] <= passes
            or not kept <= o['traded'] <= passes or o['malformed'] != 0 or o['complete'] != '1'
            or not 1 <= o['forward_rows'] <= passes
            or x['forward_matched'] != kept or x['forward_mismatches'] != 0 or x['forward_malformed'] != 0
            or x['forward_discarded'] != o['forward_rows'] - x['forward_matched']
            or not 0 < x['score_threshold'] < float('inf') or not 0 <= x['best_combined_score'] < x['score_threshold']
            or o['best_profit'] < 0.001
            or o['min_trades'] <= 0 or not all(_DATE.fullmatch(span[key]) for key in ('start', 'end', 'forward_end'))
            or not span['start'] < span['end'] < span['forward_end']):
        return None
    below = _below_score_facts(values)
    return dict(o, **x, **({'below_score': below} if below else {}))


BELOW_SCORE_RESULTS = ('exported', 'lost', 'none', 'failed')


def _below_score_facts(values):
    """The research-only below_score export a NoQualifyingRows row reports (GOAT-EA BS42), or None.

    Older builds write no ``below_score`` key. A value outside the known results, or an exported pick
    without its pass and FWD figures, is reported as ``unreadable``: never as a kept export.
    """
    result = values.get('below_score')
    if result is None:
        return None
    facts = dict(result=result if result in BELOW_SCORE_RESULTS else 'unreadable', rank=values.get('below_score_rank'))
    if result in ('exported', 'lost', 'failed') and 'below_score_pass' in values:
        try:
            facts.update(pass_number=int(values['below_score_pass']),
                         fwd_profit_dd=float(values['below_score_fwd_profit_dd']),
                         fwd_profit=float(values['below_score_fwd_profit']), fwd_trades=int(values['below_score_fwd_trades']),
                         combined_score=float(values['below_score_combined_score']),
                         min_fwd_trades=int(values['below_score_min_fwd_trades']))
        except (KeyError, ValueError):
            facts['result'] = 'unreadable'
    elif result == 'exported':
        facts['result'] = 'unreadable'
    # The export slot rule (goatai#1885 6022264062): how many units were kept and why slot 2 was or was not.
    if facts['result'] == 'exported':
        try:
            kept = int(values.get('below_score_kept', '1'))
        except ValueError:
            kept = None
        slot2 = values.get('slot2')
        if kept not in (1, 2) or (kept == 2) != (slot2 == 'kept'):
            facts['result'] = 'unreadable'
        else:
            facts['kept'] = kept
    if values.get('slot2') is not None:
        facts['slot2'] = dict(result=values['slot2'] if values['slot2'] in ('kept', 'skipped', 'none') else 'unreadable',
                              reason=values.get('slot2_reason'), correlation=values.get('slot2_correlation'),
                              character=values.get('slot2_character'))
    return facts


def _no_edge_outcome(details, expected=NO_PROFITABLE_PASSES):
    """The EA's key=value details for one research-outcome row, or None.

    ``expected`` is the outcome the row's Status allows. For NoProfitablePasses this
    mirrors the EA guard (XmlProcessor.mqh GoatXmlResearchOutcome) exactly: at
    least one pass really traded, every row parsed, the results table closed and
    the forward report is whole with no more rows than back passes. A row from an
    older build without that proof, or a report whose EA never traded, cannot be
    read or is partial, is never accepted: that member stays a real error.
    NoQualifyingRows rows are checked by _no_qualifier_outcome.
    """
    values = dict(part.split('=', 1) for part in details.split(';') if '=' in part)
    try:
        outcome = dict(outcome=values['outcome'], passes=int(values['passes']), profitable=int(values['profitable']),
                       traded=int(values['traded']), malformed=int(values['malformed']), complete=values['complete'],
                       forward_rows=int(values['forward_rows']),
                       best_profit=float(values['best_profit']), best_score=float(values['best_score']),
                       min_trades=int(values['min_trades']),
                       window=dict(start=values['window_start'], end=values['window_end'], forward_end=values['forward_end']))
    except (KeyError, ValueError):
        return None
    if outcome['outcome'] != expected:
        return None
    if expected == NO_QUALIFYING_ROWS:
        return _no_qualifier_outcome(values, outcome)
    window, passes = outcome['window'], outcome['passes']
    if (outcome['outcome'] != NO_PROFITABLE_PASSES or passes <= 0 or not 0 <= outcome['profitable'] <= passes
            or not 1 <= outcome['traded'] <= passes or outcome['malformed'] != 0 or outcome['complete'] != '1'
            or not 1 <= outcome['forward_rows'] <= passes
            or (outcome['profitable'] == 0 and outcome['best_profit'] >= 0.001)
            or outcome['min_trades'] <= 0 or not all(_DATE.fullmatch(window[key]) for key in ('start', 'end', 'forward_end'))
            or not window['start'] < window['end'] < window['forward_end']):
        return None
    return outcome


def no_edge_summary(symbol, timeframe, outcome):
    """One honest sentence: what was tested, in which window, and that it is not a verdict."""
    window = outcome['window']
    if outcome['outcome'] == NO_PROFITABLE_EXPORTS:
        sets, retested, export = outcome['unique_sets'], outcome['sets_retested'], outcome['export_window']
        return (symbol + ' ' + timeframe + ': tested, nothing held up in ' + window['start'] + ' to ' + window['end'] + ' — '
                + str(sets) + (' set' if sets == 1 else ' sets') + ' scored ' + format(outcome['score_threshold'], 'g')
                + '+ once the forward period to ' + window['forward_end'] + ' was included (best '
                + format(outcome['best_combined_score'], '.1f') + '), but '
                + ('the 1 set' if retested == 1 else 'all ' + str(retested) + ' sets') + ' re-tested over '
                + export['start'] + ' to ' + export['end'] + ' lost money (best ' + format(outcome['best_export_profit'], ',.2f')
                + '). A result for this window only, not a verdict on the strategy.')
    if outcome['outcome'] == NO_QUALIFYING_ROWS:
        kept = outcome['back_rows']
        return (symbol + ' ' + timeframe + ': tested, nothing qualified in ' + window['start'] + ' to ' + window['end'] + ' — '
                + str(outcome['passes']) + ' settings, ' + str(kept) + (' was' if kept == 1 else ' were') + ' profitable with '
                + str(outcome['min_trades']) + '+ trades but none scored ' + format(outcome['score_threshold'], 'g')
                + '+ once the forward period to ' + window['forward_end'] + ' was included (best '
                + format(outcome['best_combined_score'], '.1f')
                + (': the forward period scored zero' if outcome['best_combined_score'] == 0 else '') + '). A result for this window only, not a verdict on the strategy.')
    profitable = outcome['profitable']
    near = (' (' + str(profitable) + ' profitable on fewer trades)') if profitable else ''
    return (symbol + ' ' + timeframe + ': tested, no edge in ' + window['start'] + ' to ' + window['end'] + ' — '
            + str(outcome['passes']) + ' settings, none profitable with ' + str(outcome['min_trades']) + '+ trades' + near
            + ', best profit ' + format(outcome['best_profit'], ',.2f') + '. A result for this window only, not a verdict on the strategy.')


def _log_lines(native_run):
    """The run's EA log (``log.GOAT``) as (local epoch or None, text) pairs, or None when unreadable."""
    path = Path(native_run) / 'log.GOAT'
    try:
        if not path.is_file() or path.stat().st_size > MAX_LOG_BYTES:
            return None
        raw = path.read_bytes()
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    except (OSError, UnicodeError):
        return None
    lines = []
    for line in text.splitlines():
        match = _LOG_LINE.fullmatch(line.rstrip())
        lines.append((_local_epoch(match.group(1)), match.group(2)) if match else (None, line.rstrip()))
    return lines


def _member_log(lines, alias, started, ended):
    """The EA log lines of a member's last attempt, from its own start to its own Error, or None.

    The attempt must be the one the timeline names: the log's start and end lines carry
    the same local times (within 2 s) as the timeline's last OnGoing and its Error.
    """
    tail = ':' + alias + ';'
    begin = None
    for k, (_, text) in enumerate(lines):
        if 'Queued->OnGoing: ;OnGoing_' in text and text.endswith(tail):
            begin = k
    if begin is None or lines[begin][0] is None or abs(lines[begin][0] - started) > 2:
        return None
    for k in range(begin + 1, len(lines)):
        stamp, text = lines[k]
        if '->OnGoing: ' in text:
            return None   # another member started before this one ended
        if 'OnGoing->' in text and text.endswith(tail):
            if 'OnGoing->Error: ;Error_' not in text or stamp is None or abs(stamp - ended) > 2:
                return None
            return [line for _, line in lines[begin + 1:k]]
    return None


def _export_loss_outcome(segment):
    """The export-loss evidence of one member's log, or None when anything else happened.

    Mirrors StartExporter (GOAT V1.49.mq5): the optimization ended once, the reports were
    combined once, the top set reproduced its report, and exactly one export sequence ran
    in which every set re-tested over the export window completed and lost money (no
    errors, nothing profitable, nothing passed, no lot-adjustment run), each loss
    logged with its negative profit. Any tester error, timeout, start or move failure
    (any other ❌ line) keeps the member a real failure.
    """
    def count(words):
        return sum(words in line for line in segment)

    def one(pattern):
        found = [m for m in (pattern.search(line) for line in segment) if m]
        return found[0] if len(found) == 1 else None

    sequence, top, back, forward, export = (one(p) for p in (_EXPORT_SEQUENCE, _TOP_ROWS, _BACK_RANGE, _FORWARD_DATE, _EXPORT_DATES))
    if None in (sequence, top, back, forward, export):
        return None
    attempts, profitable, losses, errors, duplicates, passed = (int(value) for value in sequence.groups())
    if attempts < 1 or losses != attempts or profitable != 0 or errors != 0 or passed != 0:
        return None
    if (count('DEINIT: Optimization Ended') != 1 or count('DEINIT: ✅ XML files Combined and Analyzed.') != 1
            or count('DEINIT: ✅ Top Set Export Verified') != 1 or count('Export Adjustment sequence complete') != 0
            or count('❌ zero exports available after the export cycle.') != 1 or count('Export found in ') != attempts + 1
            or any('❌' in line and '❌ zero exports available after the export cycle.' not in line for line in segment)):
        return None
    profits = [float(m.group(1)) for m in (_EXPORT_DISCARDED.search(line) for line in segment) if m]
    if len(profits) != losses or not all(profit < 0 for profit in profits):
        return None
    window = dict(start=back.group(1), end=forward.group(1), forward_end=back.group(2))
    export_window = dict(start=export.group(1), end=export.group(2))
    threshold = float(top.group(1))
    if (not window['start'] < window['end'] < window['forward_end'] or not export_window['start'] < export_window['end']
            or not 0 < threshold < float('inf')):
        return None
    return dict(outcome=NO_PROFITABLE_EXPORTS, window=window, export_window=export_window, score_threshold=threshold,
                sets_retested=attempts, export_losses=losses, duplicates=duplicates, best_export_profit=max(profits))


def _export_loss_outcomes(native_run, index, timing, rows):
    """{member index: outcome} for plain ``Error`` rows whose log proves every re-tested set lost money.

    The EA writes ``Error`` with ``Export cycle finished`` and no exports both for a tester
    failure during the export cycle and for sets that ran and lost money; only the log
    tells them apart (Banker r1c-b40-r2: NZDCAD and AUDJPY lost money, NZDJPY and CADCHF
    timed out). The row must belong to the timeline's last attempt, which ended in Error.
    """
    started, ended, ends = (timing or {}).get('started', {}), (timing or {}).get('ended', {}), (timing or {}).get('outcome', {})
    candidates = {}
    for fields in rows:
        i = index.get((fields[2], fields[1]))
        written = _local_epoch(fields[0])
        if (i is None or written is None or ends.get(i) != 'Error' or i not in ended or started.get(i) is None
                or written + 1 < started[i]):
            continue
        try:
            back_rows, unique, top, exports = int(fields[4]), int(fields[5]), float(fields[6]), int(fields[7])
        except ValueError:
            continue
        if exports == 0 and 1 <= unique <= back_rows and 0 < top < float('inf'):
            candidates[i] = dict(back_rows=back_rows, unique_sets=unique, best_combined_score=top, recorded_local=fields[0],
                                 alias=fields[2])
    lines = _log_lines(native_run) if candidates else None
    found = {}
    for i, row in (candidates.items() if lines is not None else ()):
        segment = _member_log(lines, row.pop('alias'), started[i], ended[i])
        outcome = _export_loss_outcome(segment) if segment is not None else None
        if outcome is not None and row['best_combined_score'] >= outcome['score_threshold']:
            found[i] = dict(outcome, **row)
    return found


def item_outcomes(native_run, members, timing=None):
    """{member index: outcome} the EA recorded as tested with nothing qualifying in its window.

    ``members`` are (run_alias, symbol) pairs in queue order. The EA writes one
    ``NoProfitablePasses`` row to ``item_stats.tsv`` when a member's optimization
    ran but no pass was profitable with enough trades, and one ``NoQualifyingRows``
    row when profitable passes were kept but none scored high enough once the
    forward period was included; its queue status stays ``Error`` either way.
    A row counts only for the same alias and symbol, and only when the
    timeline shows the member's last start and the row was written after it, so
    an older attempt never relabels a later real failure; without timeline
    evidence nothing is relabelled. Lenient: missing or unreadable evidence
    returns {} and every member keeps its native status.

    A plain ``Error`` row from a finished export cycle with no exports is a result
    (``no_profitable_exports``) only when the run's own EA log proves every set
    re-tested over the export window completed and lost money (_export_loss_outcome).
    """
    path = Path(native_run) / 'item_stats.tsv'
    try:
        if not path.is_file() or path.stat().st_size > MAX_ITEM_STATS_BYTES:
            return {}
        raw = path.read_bytes()
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    except (OSError, UnicodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0] != ITEM_STATS_HEADER:
        return {}
    index = {(alias, symbol): i for i, (alias, symbol) in enumerate(members)}
    started = (timing or {}).get('started', {})
    found, export_rows = {}, []
    for line in lines[1:]:
        fields = line.split('\t')
        expected = RESEARCH_OUTCOME_STATUSES.get(fields[3]) if len(fields) == 9 else None
        if expected is None:
            if len(fields) == 9 and fields[3] == 'Error' and fields[8] == 'Export cycle finished':
                export_rows.append(fields)
            continue
        i = index.get((fields[2], fields[1]))
        written = _local_epoch(fields[0])
        if i is None or written is None or i not in started or written < started[i] - 1:
            continue
        outcome = _no_edge_outcome(fields[8], expected)
        if outcome is not None:
            found[i] = dict(outcome, recorded_local=fields[0])
    for i, outcome in _export_loss_outcomes(native_run, index, timing, export_rows).items():
        found.setdefault(i, outcome)
    return found


def no_edge_members(native_run, members, statuses, timing=None):
    """item_outcomes restricted to members whose native status is ``native_error``."""
    found = item_outcomes(native_run, members, timing)
    return {i: outcome for i, outcome in found.items() if i < len(statuses) and statuses[i] == 'native_error'}


def shared_window(outcomes):
    """The one tested window every no-edge member shares, or None when they differ."""
    windows = {(o['window']['start'], o['window']['end']) for o in outcomes}
    return dict(start=next(iter(windows))[0], end=next(iter(windows))[1]) if len(windows) == 1 else None


def pace(timing, statuses, *, now, fallback_started=None, tested=()):
    """Observed minutes per member and an ETA. Observations, never a promise.

    ``tested`` are member indices that ran to a research result without a
    completed queue status (no profitable passes); they took a full cycle too.
    """
    completed = [i for i, s in enumerate(statuses) if s == 'native_completed' or i in tested]
    remaining = sum(s in ('native_pending', 'native_queued', 'native_ongoing') for s in statuses)
    cycle, member, basis = None, None, None
    if timing:
        spans = [(timing['started'][i], timing['ended'][i]) for i in completed
                 if i in timing['started'] and i in timing['ended'] and timing['ended'][i] > timing['started'][i]]
        if spans:
            member = statistics.median(end - start for start, end in spans)
            first = min(start for start, _ in spans)
            last = max(end for _, end in spans)
            cycle = max(member, (last - first) / len(spans))
            basis = 'native_timeline'
    if cycle is None and fallback_started is not None and completed:
        cycle = max(1.0, (now - fallback_started) / len(completed))
        basis = 'driver_start_and_completed_count'
    current = next((i for i, s in enumerate(statuses) if s == 'native_ongoing'), None)
    current_age = None
    if current is not None and timing and current in timing['started']:
        current_age = max(0.0, now - timing['started'][current])
    eta = None
    if cycle is not None and remaining:
        seconds = remaining * cycle - (min(current_age, cycle * .95) if current_age is not None else 0)
        eta = now + max(0.0, seconds)
    return dict(minutes_per_member=None if cycle is None else round(cycle / 60, 1),
                member_minutes_median=None if member is None else round(member / 60, 1),
                basis=basis, remaining_members=remaining,
                eta_utc=None if eta is None else datetime.fromtimestamp(eta, timezone.utc).isoformat(timespec='seconds'),
                eta_wall=eta, current_index=current, current_age_seconds=None if current_age is None else round(current_age))


def batch_progress(root, install, job, *, now, journal=None):
    """Members done/total, qualifying exports, last member result, pace and ETA."""
    from studio_native_observe import observe
    package = Path(root) / 'packages' / job['job_id']
    members = job['configuration'].get('batch_members') or [job['configuration']]
    result = dict(members_total=len(members), members_done=0, members_finished=0, qualifying=None,
                  exported_sets=None, passing_sets=None, below_threshold_members=None, below_threshold_sets=None,
                  unknown_members=None, unknown_sets=None, thresholds=None, qualifying_basis=None,
                  members_no_edge=None, no_edge_counts=None, members_failed=None, members_native_error=None,
                  members_cancelled=None, no_edge_window=None, below_score_sets=None, below_score_members=None,
                  no_edge=None, last_member=None, current_member=None, pace=None, evidence='unavailable')
    manifest, _ = _bounded_json(package / 'manifest.json', 64 * 1024 * 1024)
    if not isinstance(manifest, dict) or 'launch_intent' not in job:
        result['evidence'] = 'not_started' if 'launch_intent' not in job else 'package_unreadable'
        return result
    try:
        native = observe(package)
    except (OSError, ValueError, KeyError) as error:
        result.update(evidence='native_unreadable', evidence_reason=str(error)[:240])
        return result
    if native.get('status') == 'native_evidence_missing':
        result['evidence'] = 'native_evidence_missing'
        return result
    statuses = [m['status'] for m in native['members']]
    aliases = [item['run_alias'] for item in manifest['jobs']]
    common_run = Path(install['common_files_root']) / manifest['native_run_relative'].replace('\\', '/')
    timing = timeline(common_run, aliases)
    # "Qualifying" = passed this run's own export thresholds (goat-export-qualification-v1). The EA
    # also keeps its best set when nothing passed (SortAndTrimExports: Passing=0 Kept=1); those are
    # counted apart as kept below threshold, and a set at the cut-off is unknown, never qualifying.
    thresholds_cache = []

    def run_thresholds():
        if not thresholds_cache:
            thresholds_cache.append(read_run_thresholds(common_run))
        return thresholds_cache[0]

    def member_sets(i):
        folder = common_run / 'deploy' / aliases[i] / manifest['jobs'][i]['tester']['Symbol']
        try:
            paths = sorted(p for p in folder.glob('*.set') if p.is_file()) if folder.is_dir() else []
        except OSError:
            paths = []
        stamps = []
        for path in paths:
            try:
                stamps.append(stamp_set(path, run_thresholds(), with_sha256=False))
            except (OSError, ValueError, UnicodeError):
                stamps.append(dict(status='unknown', missed=['metrics_unavailable']))
        return summarize(stamps)

    counted = dict(qualifying=0, passing_sets=0, exported_sets=0, below_threshold_members=0, below_threshold_sets=0,
                   unknown_members=0, unknown_sets=0)
    per_member = {}
    for i in [i for i, s in enumerate(statuses) if s == 'native_completed']:
        summary = per_member[i] = member_sets(i)
        counted['exported_sets'] += summary['kept']
        counted['passing_sets'] += summary['passed']
        counted['below_threshold_sets'] += summary['below_threshold']
        counted['unknown_sets'] += summary['unknown']
        counted['qualifying'] += summary['member'] == 'passed'
        counted['below_threshold_members'] += summary['member'] == 'below_threshold'
        counted['unknown_members'] += summary['member'] == 'unknown'
    # Tested with nothing qualifying in their window (no profitable settings, none scoring
    # high enough with the forward period, or every re-tested set lost money): results, never failures.
    no_edge = no_edge_members(common_run, [(item['run_alias'], item['tester']['Symbol']) for item in manifest['jobs']],
                              statuses, timing)
    # Research-only below_score exports (GOAT-EA BS42, <run>\below_score): their own count, never qualifying,
    # never an exported, passing or kept-below-threshold set (an attempt, not a pass).
    research = [len(below_score_units(common_run, aliases[i], manifest['jobs'][i]['tester']['Symbol']))
                for i in range(len(aliases))]
    counted.update(below_score_sets=sum(research), below_score_members=sum(1 for n in research if n))
    result.update(**counted, qualifying_basis=QUALIFICATION_SCHEMA,
                  thresholds=public_thresholds(run_thresholds()) if per_member else None,
                  thresholds_problems=(run_thresholds()['problems'] or None) if per_member else None)
    result.update(members_done=native['completed_count'], members_finished=native['finished_count'],
                  status_counts=native['status_counts'],
                  members_no_edge=len(no_edge), members_failed=statuses.count('native_error') - len(no_edge),
                  members_native_error=statuses.count('native_error'),
                  no_edge_counts={kind: n for kind in OUTCOME_ORDER
                                  if (n := sum(o['outcome'] == kind for o in no_edge.values()))},
                  members_cancelled=statuses.count('native_cancelled'),
                  no_edge_window=shared_window(no_edge.values()) if no_edge else None,
                  no_edge=[dict(index=i, number=i + 1, symbol=manifest['jobs'][i]['tester']['Symbol'],
                                timeframe=manifest['jobs'][i]['tester']['Period'], **no_edge[i],
                                summary=no_edge_summary(manifest['jobs'][i]['tester']['Symbol'],
                                                        manifest['jobs'][i]['tester']['Period'], no_edge[i]))
                           for i in sorted(no_edge)[:MAX_NO_EDGE_LISTED]],
                  native_status=native['status'], evidence='native_queue')
    finished = [i for i, s in enumerate(statuses) if s in ('native_completed', 'native_error', 'native_cancelled')]
    if finished:
        def order(i):
            return (timing['ended'].get(i, 0) if timing else 0, i)
        last = max((i for i in finished if statuses[i] != 'native_cancelled'), key=order, default=None)
        if last is not None:
            tester = manifest['jobs'][last]['tester']
            kept = per_member.get(last) or (member_sets(last) if statuses[last] == 'native_completed' else summarize([]))
            minutes = None
            if timing and last in timing['started'] and last in timing['ended']:
                minutes = round((timing['ended'][last] - timing['started'][last]) / 60, 1)
            result['last_member'] = dict(index=last, number=last + 1, symbol=tester['Symbol'], timeframe=tester['Period'],
                                         status=(no_edge[last]['outcome'] if last in no_edge else statuses[last].removeprefix('native_')),
                                         exported_sets=kept['kept'], passing_sets=kept['passed'],
                                         below_threshold_sets=kept['below_threshold'], unknown_sets=kept['unknown'],
                                         qualifies=statuses[last] == 'native_completed' and kept['passed'] > 0,
                                         minutes=minutes,
                                         finished_utc=(datetime.fromtimestamp(timing['ended'][last], timezone.utc).isoformat(timespec='seconds')
                                                       if timing and last in timing['ended'] else None))
            if last in no_edge:
                result['last_member'].update(outcome=no_edge[last],
                                             summary=no_edge_summary(tester['Symbol'], tester['Period'], no_edge[last]))
    started = journal.get('started_wall') if isinstance(journal, dict) else None
    result['pace'] = pace(timing, statuses, now=now, fallback_started=started if type(started) in (int, float) else None,
                          tested=frozenset(no_edge))
    current = result['pace']['current_index']
    if current is not None:
        tester = manifest['jobs'][current]['tester']
        result['current_member'] = dict(index=current, number=current + 1, symbol=tester['Symbol'], timeframe=tester['Period'],
                                        age_seconds=result['pace']['current_age_seconds'])
    return result


def seed_progress(root, batch_id, *, now, kind='seed'):
    """Seed hunt (or OOS catch-up) members done/total, qualifying results and pace, from retained state.

    Catch-up results are never "qualifying": held_up members are counted as ``held_up``.
    """
    folder = Path(root) / dict(catchup='catchups', holdup='holdups').get(kind, 'seeds') / batch_id
    state, _ = _bounded_json(folder / 'state.json', 32 * 1024 * 1024)
    if not isinstance(state, dict) or not isinstance(state.get('members'), list):
        return dict(batch_id=batch_id, kind=kind, status='unknown', evidence='seed_state_unreadable')
    members = state['members']
    done = [m for m in members if m.get('status') == 'completed']
    finished = [m for m in members if m.get('status') in ('completed', 'cancelled', 'timeout', 'failed', 'missing_output')]
    spans = [m['finished_unix'] - m['started_unix'] for m in finished
             if type(m.get('started_unix')) in (int, float) and type(m.get('finished_unix')) in (int, float)
             and m['finished_unix'] > m['started_unix']]
    cycle = statistics.median(spans) if spans else None
    remaining = sum(m.get('status') in ('pending', 'starting', 'running', 'closing') for m in members)
    running = next((m for m in members if m.get('status') in ('running', 'starting', 'closing')), None)
    age = (now - running['started_unix']) if running and type(running.get('started_unix')) in (int, float) else None
    eta = None
    if cycle is not None and remaining:
        eta = now + max(0.0, remaining * cycle - (min(age, cycle * .95) if age is not None else 0))
    candidates = sum((m.get('result') or {}).get('summary', {}).get('qualifying_count', 0) or 0 for m in done)
    qualifying_members = sum(1 for m in done if ((m.get('result') or {}).get('summary', {}).get('qualifying_count') or 0) > 0)
    held_up = profitable = None
    if kind == 'catchup':
        # A few new weeks never qualify anything: report held_up separately, not as qualifying.
        held_up = sum(1 for m in done if (m.get('result') or {}).get('summary', {}).get('verdict') == 'held_up')
        candidates = qualifying_members = None
    elif kind == 'holdup':
        # A hold-up test has no verdict and no cutoff: count the tests whose window made money.
        profitable = sum(1 for m in done if ((m.get('result') or {}).get('summary', {}).get('net') or 0) > 0)
        candidates = qualifying_members = None
    last = max(finished, key=lambda m: m.get('finished_unix') or 0, default=None)
    paused = (folder / 'pause.json').is_file()
    status = state.get('status')
    return dict(batch_id=batch_id, kind=kind, status=('paused' if paused and running is None and status == 'active'
                                                         else 'pausing' if paused and status == 'active' else status),
                members_total=len(members), members_done=len(done), members_finished=len(finished),
                qualifying=qualifying_members, qualifying_candidates=candidates, held_up=held_up,
                **({} if kind != 'holdup' else dict(profitable=profitable)),
                last_member=None if last is None else dict(alias=last.get('alias'), status=last.get('status'),
                    qualifying_candidates=(last.get('result') or {}).get('summary', {}).get('qualifying_count'),
                    best_fitness=(last.get('result') or {}).get('summary', {}).get('best_fitness')),
                pace=dict(minutes_per_member=None if cycle is None else round(cycle / 60, 1), remaining_members=remaining,
                          eta_utc=None if eta is None else datetime.fromtimestamp(eta, timezone.utc).isoformat(timespec='seconds'),
                          basis='seed_member_timestamps' if cycle is not None else None),
                pause_requested=paused, evidence='seed_state',
                # A start GOAT could not confirm: nothing runs, so there is nothing to pause. One action settles it.
                needs_settle=status == 'reconcile_required',
                settle=(dict(command=(kind if kind in ('catchup', 'holdup') else 'seed') + '-reconcile',
                             argument=dict(catchup='--catchup-id ', holdup='--holdup-id ').get(kind, '--batch-id ') + batch_id,
                             reasons=[m.get('reconcile_reason') or m.get('error') for m in members if m.get('status') == 'reconcile_required'],
                             plain='GOAT could not confirm how a member started. Settle checks that MT5 is idle and keeps the member''s own result if it passes every check.')
                        if status == 'reconcile_required' else None))


def disk(install, root, minimum):
    import shutil
    volumes, ok = [], True
    for role, path in (('terminal_data', install['terminal_data_root']), ('common_files', install['common_files_root']),
                       ('controller_state', root)):
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            free = None
        ok = ok and free is not None and free >= minimum
        volumes.append(dict(role=role, path=str(path), free_bytes=free))
    return dict(minimum_free_bytes=minimum, headroom_ok=ok, volumes=volumes,
                lowest_free_bytes=min((v['free_bytes'] for v in volumes if v['free_bytes'] is not None), default=None))


def _superseded(job, jobs):
    """True when a batch queued after ``job`` has started or ended: ``job``'s pause is then history."""
    later = jobs[jobs.index(job) + 1:]
    return any('launch_intent' in other or other.get('status') in ACTIVE | TERMINAL for other in later)


def end_state(status, progress):
    """The honest end of a batch the queue marks ``completed`` or ``failed``, from its native members.

    The queue says ``failed`` whenever a member ended with MT5's Error status. When every member reached
    an end and none was cancelled, the batch ran to completion: ``finished_with_errors`` names the members
    that really failed (``members_failed``), and a batch whose only errors were no-edge results is
    ``finished``. ``failed`` stays for a batch that stopped with members left, was cancelled part-way, or
    whose native evidence cannot be read.
    """
    total, ended = progress.get('members_total'), progress.get('members_finished')
    if progress.get('evidence') != 'native_queue' or not total or ended != total or progress.get('members_cancelled'):
        return status
    if progress.get('members_failed'):
        return 'finished_with_errors'
    return 'finished' if status == 'failed' else status


def lineage(root, batch_id, limit=50):
    """Paused batch -> successor chain for results and scoreboard continuity."""
    chain = [batch_id]
    folder = Path(root) / 'batch-lineage'
    current = batch_id
    for _ in range(limit):
        value, _ = _bounded_json(folder / (current + '.json'), 256 * 1024)
        previous = value.get('predecessor_batch_id') if isinstance(value, dict) else None
        if not isinstance(previous, str) or previous in chain:
            break
        chain.insert(0, previous)
        current = previous
    current = batch_id
    for _ in range(limit):
        value, _ = _bounded_json(Path(root) / 'batch-pauses' / (current + '.json'), 4 * 1024 * 1024)
        following = value.get('successor_batch_id') if isinstance(value, dict) else None
        if not isinstance(following, str) or following in chain:
            break
        chain.append(following)
        current = following
    return chain


def headline(activity):
    """One plain sentence for a lane or a status line."""
    kind = activity.get('kind')
    if kind == 'idle':
        return 'No research is running on this terminal.'
    total, done = activity.get('members_total'), activity.get('members_done')
    name = dict(seed='seed hunt', catchup='catch-up', holdup='hold-up test').get(kind, 'batch')
    status = activity.get('status')
    pace_value = activity.get('pace') or {}
    eta = pace_value.get('eta_wall')
    left = ''
    if eta is not None:
        minutes = max(0, int((eta - activity.get('_now', eta)) // 60))
        left = ', about ' + (str(minutes // 60) + ' h ' if minutes >= 60 else '') + str(minutes % 60) + ' min left'
    qualifying = activity.get('qualifying')
    # goat-export-qualification-v1: qualifying = passed the run's thresholds, stated; best-effort
    # sets kept below them and sets at the cut-off are named apart, never added to it.
    stamped = activity.get('qualifying_basis') is not None and activity.get('kind') == 'batch'
    limits = activity.get('thresholds') if stamped else None
    qualified_words = '' if qualifying is None else ', ' + str(qualifying) + ' qualifying' + (
        ' (' + threshold_words(limits) + ')' if limits else '')
    if stamped:
        below, unknown = activity.get('below_threshold_members') or 0, activity.get('unknown_members') or 0
        if below:
            qualified_words += ', ' + str(below) + ' more kept below threshold'
        if unknown:
            qualified_words += (', ' + str(unknown) + (' kept but not judged (no export thresholds found)' if not limits
                                                       else ' at the cut-off, not counted'))
    counts = ('' if total is None else ' ' + str(done) + ' of ' + str(total) + ' members done') + qualified_words + (
        '' if activity.get('held_up') is None else ', ' + str(activity['held_up']) + ' held up (low-sample verdicts)') + (
        '' if activity.get('profitable') is None else ', ' + str(activity['profitable']) + ' made money on their window')
    # No-edge members are results for their window, reported apart and never as failures.
    no_edge, failed = activity.get('members_no_edge'), activity.get('members_failed')
    if no_edge:
        window = activity.get('no_edge_window')
        where = (window['start'] + ' to ' + window['end'] if window else 'their test window')
        kinds = {kind: n for kind, n in (activity.get('no_edge_counts') or {}).items() if n}
        if set(kinds) <= {NO_PROFITABLE_PASSES}:
            counts += ', ' + str(no_edge) + ' tested with no edge in ' + where
        else:
            # Not "no edge": settings were profitable in-sample. Say what fell short, per kind.
            scores = {o.get('score_threshold') for o in activity.get('no_edge') or [] if o.get('outcome') != NO_PROFITABLE_PASSES}
            reached = ('scored ' + format(next(iter(scores)), 'g') + '+') if len(scores) == 1 and None not in scores else 'reached the export score'
            words = {NO_PROFITABLE_PASSES: 'with no profitable settings',
                     NO_QUALIFYING_ROWS: 'none ' + reached + ' once the forward period was included',
                     NO_PROFITABLE_EXPORTS: 'lost money on the export re-test'}
            counts += (', ' + str(no_edge) + ' tested, nothing qualified in ' + where + ' ('
                       + ', '.join(str(kinds[kind]) + ' ' + words[kind] for kind in OUTCOME_ORDER if kind in kinds) + ')')
    research = activity.get('below_score_sets') if activity.get('kind') == 'batch' else None
    if research:
        # GOAT-EA BS42: named apart, never added to qualifying or the kept sets.
        counts += ', ' + str(research) + (' best profitable set' if research == 1 else ' best profitable sets') + ' kept below score for research only'
    if failed:
        counts += ', ' + str(failed) + ' failed'
    cancelled = activity.get('members_cancelled')
    if cancelled and status not in ('pausing', 'paused'):   # a pause cancels the rest by design
        counts += ', ' + str(cancelled) + ' cancelled'
    if status == 'start_failed_unactivated':
        return ('Start failed before MT5 was touched; nothing ran. Settle it with retire-unactivated --batch-id '
                + str(activity.get('batch_id')) + ', then prepare its members again under a new batch ID.')
    if status == 'pausing':
        return 'Pausing this ' + name + ' at the next safe point;' + counts + '.'
    if status == 'paused':
        return 'Paused;' + counts + '. Resume continues the remaining members.'
    if kind in ('seed', 'catchup', 'holdup') and status == 'reconcile_required':
        return (name[0].upper() + name[1:] + ' ' + str(activity.get('batch_id')) + ' needs settling: GOAT could not confirm how a member started, '
                'so nothing is running and there is nothing to pause. Settle it with ' + (activity.get('settle') or {}).get('command', 'seed-reconcile')
                + ' ' + (activity.get('settle') or {}).get('argument', '') + ';' + counts + '.')
    if status in ('running', 'starting', 'reconcile_required', 'verifying', 'active'):
        current = activity.get('current_member') or {}
        member = (' on ' + current['symbol'] + ' ' + current['timeframe']) if current.get('symbol') else ''
        return 'Running' + dict(catchup=' OOS catch-up', holdup=' hold-up test').get(kind, '') + member + ';' + counts + left + '.'
    if status == 'finished_with_errors':
        # Every member ran to an end; "N failed" in the counts are the members MT5 ended with Error.
        return name[0].upper() + name[1:] + ' finished with errors;' + counts + '.'
    if status == 'finished':
        return name[0].upper() + name[1:] + ' finished;' + counts + '.'
    ended = activity.get('members_finished')
    unreached = (total - ended) if status == 'failed' and type(total) is int and type(ended) is int and ended < total else 0
    if unreached:
        # The queue failed with members it never reached: never "finished", whatever the others did.
        return name[0].upper() + name[1:] + ' failed;' + counts + ', ' + str(unreached) + ' never ran.'
    if status == 'failed' and no_edge and failed == 0:
        # The queue calls it failed only because no-edge members keep an Error status.
        # Cancelled members mean it stopped early: never "finished" (counts name them).
        return name[0].upper() + name[1:] + (' stopped early;' if cancelled else ' finished;') + counts + '.'
    return name[0].upper() + name[1:] + ' ' + str(status) + ';' + counts + '.'


def research_status(*, root, install, session, local, now, process='unknown', worker_alive=None, owner_stop=False,
                    jobs=None):
    """One read-only call: terminal, account, build, activity, pause, driver, disk, monitor."""
    from studio_batch_pause import load as load_pause, public as public_pause
    root = Path(root)
    monitor = monitor_state(install, session, local, now=now, process=process)
    jobs_error = None
    if jobs is None:
        try:
            jobs = queue_jobs(root, session)
        except (OSError, sqlite3.Error, ValueError) as error:
            jobs, jobs_error = [], str(error)[:240]
    pauses = {}
    for job in jobs:
        value = load_pause(root, job['job_id'], quiet=True)
        if value is not None:
            pauses[job['job_id']] = value
    active = [job for job in jobs if job.get('status') in ACTIVE]
    # A pause shows only while it is the latest work: a parent paused before a newer batch started (its
    # successor, or any later batch) is history, never the current state (goatai#1885: a finished batch
    # fell back to its old parent's pause and the watcher reported "paused").
    pausing = [job for job in jobs if pauses.get(job['job_id'], {}).get('state') in ('pausing', 'paused')
               and not _superseded(job, jobs)]
    current = active[-1] if active else (pausing[-1] if pausing else (jobs[-1] if jobs else None))
    seed_slot, _ = _bounded_json(root / 'seed-active.json', 64 * 1024)
    seed_id = seed_slot.get('batch_id') if isinstance(seed_slot, dict) and seed_slot.get('status') == 'active' else None
    journal = None
    activity = dict(kind='idle', status='idle')
    if seed_id and not active and isinstance(seed_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', seed_id):
        # Seeds and catch-ups share the slot; the slot names the manifest it belongs to.
        kind = 'seed'
        for runner, folder in (('catchup', 'catchups'), ('holdup', 'holdups')):
            runner_state, _ = _bounded_json(root / folder / seed_id / 'state.json', 32 * 1024 * 1024)
            if isinstance(runner_state, dict) and runner_state.get('manifest_sha256') == seed_slot.get('manifest_sha256'):
                kind = runner
                break
        activity = seed_progress(root, seed_id, now=now, kind=kind)
    elif current is not None:
        journal, _ = _bounded_json(root / 'batch-drivers' / (current['job_id'] + '.json'))
        pause = pauses.get(current['job_id'])
        progress = batch_progress(root, install, current, now=now, journal=journal)
        status = current['status']
        from studio_retire_unactivated import unactivated_hint
        if unactivated_hint(root, current) and progress.get('evidence') == 'native_evidence_missing':
            # Intent recorded, but no attempt folder, controls or native queue: MT5 was
            # never touched. It is not running and needs retire-unactivated.
            status = 'start_failed_unactivated'
        elif pause is not None and pause.get('state') in ('pausing', 'paused', 'pause_failed', 'resumed', 'finished'):
            status = pause['state']
        elif status in ('reserved', 'starting', 'reconcile_required', 'verifying'):
            status = 'running' if status in ('reconcile_required', 'verifying') else status
        elif status in ('completed', 'failed'):
            status = end_state(status, progress)
        activity = dict(kind='batch', batch_id=current['job_id'], status=status, queue_status=current['status'],
                        lineage=lineage(root, current['job_id']), pause=None if pause is None else public_pause(pause),
                        **progress)
        # A batch whose MT5 has run nothing for a while is not "running" (goatai#1885, Banker 2026-10-05).
        from studio_batch_stall import research_stall
        stall = research_stall(activity, monitor, journal, now=now, session=session)
        if stall is not None:
            activity.update(status='stalled', stall=stall)
    activity['_now'] = now
    activity['headline'] = activity['stall']['plain'] if activity.get('status') == 'stalled' else headline(activity)
    activity.pop('_now', None)
    driver = None
    if journal is not None or activity.get('kind') == 'batch':
        worker, _ = _bounded_json(root / 'demo-agent' / 'workers' / (activity.get('batch_id', '') + '.json'))
        alive = None
        if worker is not None and worker_alive is not None:
            try:
                alive = bool(worker_alive(worker))
            except (ValueError, OSError):
                alive = None
        driver = dict(alive=alive, worker_status=worker.get('status') if isinstance(worker, dict) else None,
                      journal_status=journal.get('status') if isinstance(journal, dict) else None,
                      stopped=journal.get('stopped') if isinstance(journal, dict) else None,
                      cancel_issued=journal.get('cancel_issued') if isinstance(journal, dict) else None,
                      deadline_utc=(datetime.fromtimestamp(journal['deadline_wall'], timezone.utc).isoformat(timespec='seconds')
                                    if isinstance(journal, dict) and type(journal.get('deadline_wall')) in (int, float) else None),
                      stall=journal.get('stall') if isinstance(journal, dict) else None,
                      observe=journal.get('observe') if isinstance(journal, dict) else None)
        unsupervised = (activity.get('queue_status') in ACTIVE and alive is False)
        driver['health'] = ('unsupervised' if unsupervised else 'supervising' if alive else 'idle' if alive is False else 'unknown')
        if unsupervised:
            driver['message'] = 'No GOAT driver is supervising this running batch (no disk guard or finish).'
            driver['fix'] = 'Pause it (batch-pause) to stop it safely and keep its results, or resume-batch to supervise it again.'
    minimum = journal.get('min_free_bytes') if isinstance(journal, dict) and type(journal.get('min_free_bytes')) is int else MIN_FREE_BYTES
    account = session.get('account') or {}
    research_launch = _research_launch(install, root, now)
    return dict(schema_version=1, observed_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
                terminal=dict(executable=install.get('terminal_executable'), data_root=install.get('terminal_data_root'),
                              running=None if process == 'unknown' else process is not None,
                              process=process if isinstance(process, dict) else None,
                              build=monitor.get('terminal_build')),
                account=dict(login=account.get('login'), server=account.get('server'), demo_only=session.get('demo_only') is True),
                ea=dict(version=install.get('ea_version'), sha256=install.get('ea_sha256'), build=monitor.get('ea_build'),
                        controller_version=install.get('controller_version'), bundle_version=install.get('bundle_version')),
                monitor=dict({key: monitor.get(key) for key in ('state', 'ticking', 'transient', 'heartbeat_age_seconds', 'bound', 'loaded',
                                                                'owner', 'tester_state', 'batch_ongoing', 'activation')},
                             licence=('signed_out' if monitor.get('state') == 'unlicensed' else
                                      'signed_in' if monitor.get('ticking') else 'unknown'),
                             blocker=monitor.get('blocker')),
                activity=activity, driver=driver, owner_stop=bool(owner_stop),
                disk=disk(install, root, minimum), queue_error=jobs_error,
                heldout_locks=_heldout(install, root, activity.get('batch_id'), now),
                research_launch=research_launch, enabled_mt5_workers=research_launch.get('enabled_mt5_workers'),
                read_only=True, launch_permitted=False)


def _research_launch(install, root, now):
    """Research-launch policy, live job limits, owner CPU guard and the real local agent count
    (goatai#1885 PR E). Query-only; never fails the read."""
    try:
        from studio_research_launch import status
        return status(install, root, now=now)
    except Exception as error:
        return dict(enabled_mt5_workers=None, agent_count_source=None,
                    plain='The research launch state could not be read: ' + str(error)[:200])


def _heldout(install, root, run_id, now):
    """Active held-out locks of this activity's strategies (goatai#2221 §4.3); never fails the read."""
    try:
        from studio_heldout_guard import run_locks
        return run_locks(install, root, run_id, now=datetime.fromtimestamp(now, timezone.utc))
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(registry='unknown', active_locks=[], plain='Held-out locks could not be read: ' + str(error)[:200])
