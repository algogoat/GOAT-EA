"""The EA's own reason for refusing a batch before any test ran, read from the terminal's Experts log.

Banker, 2026-10-13: a prove batch refused at OnTesterInit. The EA Printed why to the terminal's
Experts log (``MQL5\\Logs\\<yyyymmdd>.log``)::

    07:03:27.463  GOAT V1.49 (WS30,M1)  GOAT optimization refused before passes: Native optimization
                                        flag/value/range differs: RSI_TF_

while the tester journal (``Tester\\logs\\<yyyymmdd>.log``) said only ``OnTesterInit failed.
Optimization cannot be started.`` People read the tester journal, so 50 minutes went by, and then
``continue --clear-stop`` was run as the "fix": it only deletes the owner STOP file and cannot fix
an input the EA refused.

This module quotes the EA's refusal for one launch attempt so batch-status, batch-driver-status,
research-status and the stall verdict can say it plainly, and so ``continue`` can refuse a retry
that would refuse again. It reads only from the attempt's start onward (and before the next
attempt on this terminal), only the last MAX_TAIL_BYTES of each day's log, keeps at most
MAX_MATCHES matching lines, and only for the batch's own symbols when the line names one.

Read-only: the plain read-only open studio_native_diagnostics uses for MT5 journals (it shares
read and write, so MT5 keeps writing). A missing, locked or unreadable log is no evidence:
the answer is None, never an error. Log times are MT5's local time on this PC.
"""
from collections import deque
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import time

from studio_native_diagnostics import LOG_FOLDER, MAX_LINE_CHARS, _decode, _tail

MAX_TAIL_BYTES = 2 * 1024 * 1024
MAX_MATCHES = 200
MAX_LOG_DAYS = 3
TESTER_LOG_FOLDER = 'Tester\\logs'

# The EA's refusal lines (GOAT V1.49.mq5 OnTesterInit/OnInit, GOATStudioDispatch.mqh), most specific first.
REFUSALS = (('GOAT optimization refused before passes:', 'input_verification'),
            ('Initialization Failed:', 'initialization_failed'),
            ('Studio settings refused:', 'studio_settings_refused'))
# Refusals of the batch's own inputs: the EA refuses the same SET again, and no STOP clear changes that.
INPUT_REFUSALS = frozenset(('input_verification', 'initialization_failed'))
CONTEXT = 'Optimization Initialization'
TESTER_INIT_FAILED = 'OnTesterInit failed'
SOURCE = re.compile(r'^GOAT V[0-9.]+ \(([^,()]+),[A-Za-z0-9]+\)$')
STAMP = re.compile(r'^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$')
CLEAR_STOP_NOTE = 'clear-stop only clears the owner STOP file and cannot fix this'


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _wall(text):
    """An ISO time (the launch intent's recorded_at) as epoch seconds, or None."""
    try:
        value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _line_wall(day, stamp):
    """A journal line's local HH:MM:SS.mmm on its log's day, as epoch seconds (MT5 writes this PC's local time)."""
    match = STAMP.match(stamp)
    if not match:
        return None
    hour, minute, second, milli = (int(part) for part in match.groups())
    try:
        return datetime(day.year, day.month, day.day, hour, minute, second, milli * 1000).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _lines(path):
    """The bounded tail of one MT5 journal as lines; [] when it is missing, locked or unreadable."""
    try:
        if path.is_symlink() or not path.is_file():
            return []
        cut = path.stat().st_size > MAX_TAIL_BYTES
        lines = _decode(_tail(path, MAX_TAIL_BYTES)).splitlines()
    except OSError:
        return []
    return lines[1:] if cut and lines else lines   # a cut tail starts mid-line


def _days(since_wall, end_wall):
    """The local log days of the window, oldest first: always the attempt's launch day and the MAX_LOG_DAYS days
    from it (a start refusal lands there), plus the newest MAX_LOG_DAYS days up to the window's end. At most
    2 * MAX_LOG_DAYS files however old the attempt (GOAT-EA#234 review: a retry days later still sees the refusal)."""
    first = datetime.fromtimestamp(since_wall).date()
    last = datetime.fromtimestamp(max(end_wall, since_wall)).date()
    days = {first + timedelta(days=step) for step in range(MAX_LOG_DAYS)}
    days |= {last - timedelta(days=step) for step in range(MAX_LOG_DAYS)}
    return sorted(day for day in days if first <= day <= last)


def _window_lines(root, folder, since_wall, until_wall, end_wall):
    """(day, log name, at, parts, line) for every tab-separated journal line inside the window, oldest first."""
    for day in _days(since_wall, end_wall):
        name = day.strftime('%Y%m%d') + '.log'
        for line in _lines(root.joinpath(*folder.split('\\'), name)):
            parts = line.split('\t')
            if len(parts) < 5:
                continue
            at = _line_wall(day, parts[2].strip())
            if at is None or at < since_wall or (until_wall is not None and at >= until_wall):
                continue
            yield name, at, parts, line


def _iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def plain(refusal):
    """One sentence for a person or an agent."""
    reason = refusal.get('reason') or 'no reason given'
    where = ' (Experts log ' + str(refusal.get('log')) + ' at ' + str(refusal.get('at_local')) + ')'
    if refusal.get('kind') in INPUT_REFUSALS:
        return ('The EA refused this batch before any test ran: ' + reason + '. Retrying unchanged will refuse again; '
                'rebuild the SET (fix the input it names), prepare a new batch from it and start that; '
                + CLEAR_STOP_NOTE + '.' + where)
    return ('The EA refused this batch\'s settings before any test ran: ' + reason + '. Check the batch\'s SET and '
            'the MT5 tester settings before starting again; ' + CLEAR_STOP_NOTE + '.' + where)


def ea_refusal(terminal_data_root, since_wall, *, until_wall=None, symbols=None, now=None):
    """The newest EA refusal line in [since_wall, until_wall), or None.

    ``symbols`` (optional) keeps only lines from a chart of one of the batch's symbols, so a refusal
    another chart printed in the same window is never quoted. Returns ``at`` (UTC), ``at_local``,
    ``line``, ``reason``, ``kind``, ``source``, ``log``, the EA's preceding ``Optimization
    Initialization`` line as ``context``, the tester journal's ``OnTesterInit failed`` line when
    present, ``retry_unchanged_refuses`` and ``plain``.
    """
    if not _finite(since_wall) or (until_wall is not None and not _finite(until_wall)):
        return None
    now = time.time() if now is None else now
    end = until_wall if until_wall is not None else now
    if not _finite(end):
        return None
    wanted = {str(symbol) for symbol in symbols} if symbols else None
    root = Path(terminal_data_root)
    matches, contexts = deque(maxlen=MAX_MATCHES), {}
    try:
        for name, at, parts, line in _window_lines(root, LOG_FOLDER, since_wall, until_wall, end):
            source, message = parts[3].strip(), '\t'.join(parts[4:]).strip()
            chart = SOURCE.match(source)
            if wanted is not None and chart is not None and chart.group(1) not in wanted:
                continue
            if CONTEXT in message:
                contexts[source] = line.strip()[:MAX_LINE_CHARS]
                continue
            for marker, kind in REFUSALS:
                index = message.find(marker)
                if index >= 0:
                    matches.append(dict(at=_iso(at), at_wall=at, at_local=name[:4] + '-' + name[4:6] + '-' + name[6:8]
                                        + ' ' + parts[2].strip(), line=line.strip()[:MAX_LINE_CHARS],
                                        reason=message[index + len(marker):].strip()[:MAX_LINE_CHARS], kind=kind,
                                        source=source, log=LOG_FOLDER + '\\' + name, context=contexts.get(source)))
                    break
    except (OSError, ValueError, OverflowError):
        return None
    if not matches:
        return None
    found = dict(matches[-1], matches=len(matches), tester_journal=_tester_init_failed(root, since_wall, until_wall, end),
                 retry_unchanged_refuses=matches[-1]['kind'] in INPUT_REFUSALS)
    found['plain'] = plain(found)
    return found


def _tester_init_failed(root, since_wall, until_wall, end):
    """The tester journal's own ``OnTesterInit failed`` line in the window, or None (corroboration only)."""
    seen = None
    try:
        for name, _at, parts, line in _window_lines(root, TESTER_LOG_FOLDER, since_wall, until_wall, end):
            if TESTER_INIT_FAILED in '\t'.join(parts[4:]):
                seen = dict(log=TESTER_LOG_FOLDER + '\\' + name, line=line.strip()[:MAX_LINE_CHARS])
    except (OSError, ValueError, OverflowError):
        return None
    return seen


def _symbols(job):
    configuration = job.get('configuration') if isinstance(job.get('configuration'), dict) else {}
    members = configuration.get('batch_members', [configuration])
    found = {member['tester']['Symbol'] for member in members if isinstance(member, dict)
             and isinstance(member.get('tester'), dict) and isinstance(member['tester'].get('Symbol'), str)}
    return found or None


SETTLED = frozenset(('completed', 'failed', 'cancelled'))


def _settled_wall(job, since):
    """When a settled attempt's completion was observed (completion.native.observed_at), or None while unsettled."""
    if job.get('status') not in SETTLED:
        return None
    completion = job.get('completion') if isinstance(job.get('completion'), dict) else {}
    native = completion.get('native') if isinstance(completion.get('native'), dict) else {}
    wall = _wall(native.get('observed_at'))
    return wall if wall is not None and wall > since else None


def attempt_window(job, jobs=()):
    """(start, end) of this job's launch attempt: from its launch intent up to the earlier of its retained completion
    (once settled) and the next attempt on this terminal; open-ended (None) only while unsettled with no later attempt.
    A refusal another run prints after this attempt settled is never this attempt's (GOAT-EA#234 review)."""
    intent = job.get('launch_intent') if isinstance(job, dict) else None
    since = _wall(intent.get('recorded_at')) if isinstance(intent, dict) else None
    if since is None:
        return None, None
    ends = [wall for wall in (_wall(((other or {}).get('launch_intent') or {}).get('recorded_at'))
                              for other in jobs or () if isinstance(other, dict)
                              and other.get('job_id') != job.get('job_id'))
            if wall is not None and wall > since]
    settled = _settled_wall(job, since)
    if settled is not None:
        ends.append(settled)
    return since, (min(ends) if ends else None)


def for_job(install, job, jobs=(), *, now=None):
    """The EA refusal of this queue job's own launch attempt, or None. Never raises."""
    try:
        since, until = attempt_window(job, jobs)
        if since is None:
            return None
        return ea_refusal(install['terminal_data_root'], since, until_wall=until, symbols=_symbols(job), now=now)
    except Exception:
        return None


def for_controller(controller, job_id, *, now=None):
    """for_job for a queue job of an open controller (batch-status, batch-driver-status, the driver's stall). Never raises."""
    try:
        return for_job(controller.install, controller.job(job_id), controller.state()['queue'], now=now)
    except Exception:
        return None


def blocks_retry(refusal):
    """True when this refusal is of the batch's own inputs: an unchanged continue would refuse again."""
    return isinstance(refusal, dict) and refusal.get('kind') in INPUT_REFUSALS
