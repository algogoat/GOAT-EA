"""Fast-fail re-run, once (goatai#2750, Claude-Mac 6884071485 / 6884089927, option (b)).

On 2026-11-14 Banker's catch-up member ``Cc62f2b9acc1a418b_00179`` ended ``missing_output``: MT5 closed 14 s into its
1800 s budget without an export, because Banker's tester agent could not bind ``127.0.0.1:3024`` (10048) while T3's own
agent on the same port was mid-test. T3's agent refused Banker's tester with ``invalid password``, so the collision failed
closed: it cost one member, never a wrong result. A member like that never really ran, so the runner re-runs it ONCE:

* **What counts:** the member ends ``missing_output`` (no output at all), MT5 closed fewer than ``FAST_FAIL_SECONDS`` after
  the launch, and it is the member's first attempt. A timeout, a failure with output, a cancel or a reconcile never counts.
* **When:** after every never-attempted pending member of the batch, and never sooner than ``RETRY_DELAY_SECONDS`` after
  the first attempt ended (the other terminal's test has usually finished by then).
* **The record:** ``fast_fail`` keeps the first attempt (start, end, seconds run, the plain reason, the process) and the
  agent-log lines of its window (bind error, invalid password, anything else MT5's agents logged at warning or error).
  ``attempts`` reads 2 once the re-run starts.
* **Final:** a second fast-fail is ``missing_output`` with both attempts in its error; it is never re-run again.

B57 (goatai#2943, Claude-Mac 7226979353): **an empty report is a fast-fail too.** On 2026-11-27 the hold-up probe
``fwr-depth-sp500`` member ``_00010`` ended ``failed`` 15 s after its launch: MT5 (build 6230) wrote a report that names no
expert and no symbol (period M0 1970.01.01, deposit 0, leverage 1:0, no deals), because its agent 3033 had hit a bind
error. The member never really ran, exactly like a ``missing_output`` fast-fail, but the report file existed. So a FIRST
attempt that ends ``failed`` with such a report (``EmptyReport``, raised by the hold-up collector) inside
``FAST_FAIL_SECONDS`` is recorded the same way, its report is set aside (moved, create-only, never deleted, its sha256
recorded) so the member's output path is free, and it is re-run once on the same rules. Only hold-ups read an MT5 report;
seed and catch-up outputs are not reports, so their fast-fail stays ``missing_output``.
"""
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import re

FAST_FAIL_SECONDS = 30
RETRY_DELAY_SECONDS = 60
AGENT_LINE_CAP = 12
AGENT_TAIL_BYTES = 2 * 1024 * 1024        # the first tail read; widened x4 until it reaches back past the window
AGENT_TAIL_MAX_BYTES = 256 * 1024 * 1024   # never read more than this of one log
WINDOW_PAD_SECONDS = 5
NOTABLE = re.compile(r'bind error|invalid password|error|failed|cannot|refused|denied|not found', re.I)


class EmptyReport(ValueError):
    """MT5 wrote a report that names no expert and no symbol: the test never ran (B57, the 2026-11-27 SP500 probe). The
    message is the collector's own refusal, unchanged; only its type marks the shape."""


def names_nothing(report):
    """A parsed MT5 report (studio_tester_report.read_report) whose settings name no expert and no symbol."""
    settings = (report or {}).get('settings') or {}
    return not str(settings.get('expert') or '').strip() and not str(settings.get('symbol') or '').strip()


def is_fast_fail(item, ran_seconds, has_output):
    """True for a member whose FIRST attempt ended missing_output, with no output, inside FAST_FAIL_SECONDS."""
    return (item.get('status') == 'missing_output' and not has_output and item.get('attempts') == 1
            and not item.get('fast_fail') and type(ran_seconds) in (int, float) and 0 <= ran_seconds < FAST_FAIL_SECONDS)


def is_empty_report_fast_fail(item, ran_seconds):
    """True for a member whose FIRST attempt ended failed on an EmptyReport, inside FAST_FAIL_SECONDS (B57)."""
    return (item.get('status') == 'failed' and item.get('empty_report') is True and item.get('attempts') == 1
            and not item.get('fast_fail') and type(ran_seconds) in (int, float) and 0 <= ran_seconds < FAST_FAIL_SECONDS)


def set_aside(path, target):
    """Move an empty report out of the member's output path before its re-run: create-only (an existing target refuses),
    never deleted. Returns its record (from, to, sha256, size); raises OSError or ValueError, and then nothing moved."""
    path, target = Path(path), Path(target)
    if target.exists():
        raise ValueError('A set-aside report already exists: ' + target.name)
    raw = path.read_bytes()
    path.rename(target)
    return dict(from_path=str(path), path=str(target), sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))


def retry_due(item, now):
    """A fast-failed member waiting for its one re-run, and its delay has passed."""
    ff = item.get('fast_fail')
    return (item.get('status') == 'pending' and item.get('attempts') == 1 and isinstance(ff, dict)
            and type(ff.get('retry_after_unix')) in (int, float) and now >= ff['retry_after_unix'])


def waiting_retry(item):
    """A pending member whose one fast-fail re-run has not started yet (due or not)."""
    return item.get('status') == 'pending' and item.get('attempts') == 1 and isinstance(item.get('fast_fail'), dict)


def _read_tail(path, limit):
    with open(path, 'rb') as stream:
        stream.seek(0, 2);size = stream.tell()
        start = max(0, size - limit);start -= start % 2
        stream.seek(start);raw = stream.read()
    if raw.startswith(b'\xff\xfe'):raw = raw[2:]
    lines = raw.decode('utf-16-le', 'replace').splitlines()
    return lines[1:] if start and lines else lines


def _line_time(line, day):
    parts = line.split('\t')
    if len(parts) < 5:return None, parts
    try:
        return datetime.combine(day.date(), datetime.strptime(parts[2], '%H:%M:%S.%f').time()), parts
    except ValueError:
        return None, parts


def _window_lines(log, day, lo):
    """The log's tail, widened until its first timed line is at or before ``lo`` (a busy agent can write megabytes of trade
    lines after the window within minutes: Banker's agent 3024 on 2026-11-14), or the whole file, or the cap."""
    size = log.stat().st_size;limit = AGENT_TAIL_BYTES
    while True:
        lines = _read_tail(log, limit)
        first = next((t for t in (_line_time(l, day)[0] for l in lines) if t is not None), None)
        if limit >= size or limit >= AGENT_TAIL_MAX_BYTES or (first is not None and first <= lo):return lines
        limit *= 4


def agent_log_lines(install, started_unix, finished_unix, *, agents_root=None):
    """MT5 agent-log lines written inside the attempt's window (local clock, padded), notable ones first. Never raises."""
    try:
        folder = Path(agents_root) if agents_root else (Path(os.environ.get('APPDATA', '')) / 'MetaQuotes' / 'Tester'
                                                        / Path(install['terminal_data_root']).name)
        lo = datetime.fromtimestamp(started_unix - WINDOW_PAD_SECONDS)
        hi = datetime.fromtimestamp(finished_unix + WINDOW_PAD_SECONDS)
        found = []
        for log in sorted(folder.glob('Agent-*/logs/*.log')):
            try:
                if log.stat().st_mtime < started_unix - WINDOW_PAD_SECONDS:continue
                day = datetime.strptime(log.stem, '%Y%m%d')
            except (OSError, ValueError):
                continue
            for line in _window_lines(log, day, lo):
                when, parts = _line_time(line, day)
                if when is None or not lo <= when <= hi:continue
                found.append((0 if (parts[1].strip() not in ('0', '') or NOTABLE.search(parts[4])) else 1,
                              log.parent.parent.name + ' ' + log.stem + ' ' + '\t'.join(parts[1:5]).strip()))
        found.sort(key=lambda x: x[0])
        return [text[:300] for _, text in found[:AGENT_LINE_CAP]]
    except Exception as error:      # the record never blocks the member's outcome
        return ['agent logs could not be read: ' + str(error)[:200]]


def record(item, *, started_unix, finished_unix, error, install, agents_root=None, set_aside_report=None):
    """The fast_fail record for the first attempt, and the member set back to pending for its one re-run. With
    ``set_aside_report`` (B57) the first attempt was an empty report, already moved out of the output path."""
    ran = int(round(finished_unix - started_unix))
    first = dict(started_unix=started_unix, finished_unix=finished_unix, ran_seconds=ran, error=error, process=item.get('process'))
    if set_aside_report is None:
        plain = 'MT5 closed %d s after the launch with no output' % ran
    else:
        first.update(kind='empty_report', report=set_aside_report)
        plain = ('MT5 closed %d s after the launch with an empty report (no expert, no symbol), set aside as %s'
                 % (ran, Path(set_aside_report['path']).name))
    item['fast_fail'] = dict(first_attempt=first,
                             agent_log=agent_log_lines(install, started_unix, finished_unix, agents_root=agents_root),
                             retry_after_unix=finished_unix + RETRY_DELAY_SECONDS,
                             plain=(plain + ' (a fast-fail: the member never really ran). It is re-run once, after the '
                                    'batch\'s other pending members and not before %d s.' % RETRY_DELAY_SECONDS))
    for key in ('error', 'process', 'started_unix', 'finished_unix', 'result', 'observed_xml', 'empty_report'):
        item.pop(key, None)
    item['status'] = 'pending'
    return item


def final_error(item, ran_seconds, error):
    """The error of a member whose one re-run fast-failed too: both attempts, never re-run again."""
    first = (item.get('fast_fail') or {}).get('first_attempt') or {}
    return ('Fast-failed twice, so it is not re-run again: the first attempt closed after %s s (%s) and the re-run after %d s '
            '(%s). Nothing is inferred: the member has no result.'
            % (first.get('ran_seconds'), first.get('error') or 'no reason recorded', ran_seconds, error))
