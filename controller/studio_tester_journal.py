"""Keep the terminal's tester journal with the run it belongs to (GOAT-EA#315).

Banker and T3, 2026-11-10/11: MT5 cleared the tester's older day logs (``Tester\\logs\\<yyyymmdd>.log``) when a later
optimisation started, so the journal of a finished catch-up no longer existed when the round close needed it. The
controller therefore copies the journal itself when a run ends, before it returns control (Claude-Mac goatai#2750
6791842328), and a read-only check says whether every copy is still there:

* a catch-up: each member's own block of lines, from its MT5 start to its MT5 exit, into the member's evidence folder
  (``tester-journal.<yyyymmdd>.log``), or beside that folder (``<member>.tester-journal.<yyyymmdd>.log``) when the member
  left none because it failed before its re-test was collected;
* a Prove batch: what is left of the batch's own block of each day log, from its launch to its finish, into the
  attempt folder (``attempts\\<attempt>\\tester-journal\\<yyyymmdd>.log.gz``), next to ``result.json``.

What each copy covers (read on T3 by Ops, 2026-11-11). MT5 rewrites the tester's day log at every optimisation
start, today's file included, and removes the older ones: during a running Prove batch the day log held only the
lines since the current member's optimisation started, and a 234 MB log of the day before vanished when a batch
started. A catch-up member is a single test, not an optimisation: the day log survived all 83 members of a
catch-up. So a catch-up member's copy is its whole block, and it exists because the next optimisation start on
that terminal destroys the log. A Prove batch's copy, made at its finish, can only hold the lines since its last
member's optimisation started: its record says ``covers: last_member_only`` and the check never calls it complete
(Claude-Mac goatai#2750 6792752258: a Prove member's proof stays its report, its effective-inputs.set and its
capture). Copying each member's block would need the copy between the terminal's exit and its relaunch at a member
boundary, which the EA drives (TerminalClose, Tester.mqh:161; the relaunch waits for the exit and 500 ms,
Tester.mqh:69-78) and the batch driver only polls (studio_batch_driver.run, every poll_seconds).

Only the run's own lines are copied, never a whole day log: one day's log was 234 MB on the Ops PC. The block is found
by the lines' own time stamps (a binary search, since a journal is written in time order, then one bounded scan; a
real T3 day log of 17,414 lines read by Ops on 2026-11-11 had no line earlier than the running maximum), so a
copy reads the block and a few probe blocks, not the day. A member's copy is plain UTF-16 like the journal and bounded
(MAX_MEMBER_BYTES: past it the first and last halves are kept and the record says so); a batch's copy is the whole
block, gzip. Every copied line is byte for byte the journal's line.

The journal is opened read-only (the plain read-only open studio_native_diagnostics uses, so MT5 keeps writing) and is
never changed or removed. Each copy is recorded with its path, SHA-256, size and first and last line time in the
member's state (a catch-up) or the batch's result (``tester_journal``). A day log that is gone, or holds no line of the
run, is recorded as missing with the reason; nothing is invented. Log times are MT5's local time on this PC.
"""
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from studio_ea_refusal import TESTER_LOG_FOLDER, _line_wall, _wall

SCHEMA = 'goat-tester-journal-copy-v1'
CHECK_SCHEMA = 'goat-tester-journal-check-v1'
BOM = b'\xff\xfe'
LINE_END = b'\n\x00'
BLOCK = 1 << 20                           # one read: a probe of the search, or a piece of the block being copied
MAX_MEMBER_BYTES = 64 * 1024 * 1024       # a catch-up member's copy; a single test's block is far smaller
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024   # never the copy that fills the evidence volume
MAX_DAYS = 62
MEMBER_FILE = 'tester-journal.%s.log'
BATCH_FOLDER = 'tester-journal'
BATCH_FILE = '%s.log.gz'
ENDED = frozenset(('completed', 'failed', 'timeout', 'missing_output', 'cancelled'))
FINISHED = frozenset(('completed', 'stopped'))
SETTLED = frozenset(('completed', 'failed', 'cancelled'))
LAST_MEMBER_ONLY = 'last_member_only'


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _local(wall):
    return None if wall is None else datetime.fromtimestamp(wall).isoformat(sep=' ', timespec='milliseconds')


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(BLOCK), b''):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The run's own block of one day log
# ---------------------------------------------------------------------------

def _line_end(buffer, begin):
    """Index of the first UTF-16 line feed on a code-unit boundary counted from ``begin``, or -1."""
    index = buffer.find(LINE_END, begin)
    while index >= 0 and (index - begin) % 2:
        index = buffer.find(LINE_END, index + 1)
    return index


def _lines(stream, start, limit, stop):
    """(offset, bytes with its line end) of every complete line that starts in [start, limit); ``start`` is a line
    start and ``stop`` the end of the last complete line, so a line MT5 is still writing is never read."""
    stream.seek(start)
    offset, position, pending = start, start, b''
    while offset < limit and position < stop:
        block = stream.read(min(BLOCK, stop - position))
        if not block:
            break
        position += len(block)
        pending += block
        cut = 0
        while offset + cut < limit:
            index = _line_end(pending, cut)
            if index < 0:
                break
            yield offset + cut, pending[cut:index + 2]
            cut = index + 2
        offset += cut
        pending = pending[cut:]


def _stamp(raw, day):
    """A journal line's own time on ``day`` as epoch seconds, or None for a line without one (a continued message)."""
    parts = raw[:128].decode('utf-16-le', 'replace').split('\t')
    return _line_wall(day, parts[2].strip()) if len(parts) > 2 else None


def _complete_end(stream, size):
    """The offset just past the last complete line."""
    end = size - size % 2
    while end > len(BOM):
        begin = max(len(BOM), end - BLOCK)
        stream.seek(begin)
        block = stream.read(end - begin)
        index = block.rfind(LINE_END)
        while index >= 0 and index % 2:
            index = block.rfind(LINE_END, 0, index + 1)
        if index >= 0:
            return begin + index + 2
        end = begin
    return len(BOM)


def _first_line(stream, offset, stop):
    """The first line start at or after ``offset``, or None when there is none before ``stop``."""
    if offset <= len(BOM):
        return len(BOM) if stop > len(BOM) else None
    position = offset - 2
    stream.seek(position)
    while position < stop:
        block = stream.read(min(BLOCK, stop - position))
        if not block:
            return None
        index = _line_end(block, 0)
        if index >= 0:
            start = position + index + 2
            return start if start < stop else None
        position += len(block)
    return None


def _bound(stream, stop, day, wall, *, after):
    """The offset of the first stamped line at ``wall`` or later (strictly later with ``after``), else ``stop``.

    A journal is written in time order, so the line is found by halving: each step reads from the middle to the next
    stamped line. The last stretch (at most one BLOCK) is read line by line."""
    def reached(at):
        return at > wall if after else at >= wall
    low, high, bound = len(BOM), stop, stop
    while high - low > BLOCK:
        middle = low + (((high - low) // 2) & ~1)
        start, found = _first_line(stream, middle, high), None
        if start is not None:
            found = next(((offset, at) for offset, at in ((offset, _stamp(raw, day)) for offset, raw in _lines(stream, start, high, stop))
                          if at is not None), None)
        if found is None:
            high = middle                 # no stamped line starts in [middle, high)
        elif reached(found[1]):
            high = bound = found[0]
        else:
            low = found[0]
    for offset, raw in _lines(stream, low, high, stop):
        at = _stamp(raw, day)
        if at is not None and reached(at):
            return offset
    return bound


def _slice(path, day, since, until):
    """(start, stop, size): the byte range of ``day``'s journal lines stamped within [since, until], with every line
    that continues the last of them."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        if stream.read(len(BOM)) != BOM:
            raise ValueError('it is not a UTF-16 journal')
        stop = _complete_end(stream, size)
        return _bound(stream, stop, day, since, after=False), _bound(stream, stop, day, until, after=True), size


def _copy(source, target, start, stop, size, day, *, compress, limit):
    """Write lines [start, stop) of ``source`` to ``target``: new bytes in a temporary file, then one atomic rename.

    An earlier copy of the same name is replaced: the record that binds its hash is stored only after this returns."""
    half = limit // 2 if limit is not None and stop - start > limit else None
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    content, written, lines, first, last, omitted = hashlib.sha256(BOM), len(BOM), 0, None, None, 0
    try:
        with source.open('rb') as stream, temporary.open('xb') as stored:
            out = gzip.GzipFile(filename='', mode='wb', fileobj=stored, mtime=0) if compress else stored
            try:
                out.write(BOM)
                for offset, raw in _lines(stream, start, stop, stop):
                    if half is not None and offset + len(raw) - start > half and offset < stop - half:
                        omitted += 1      # the middle of a block past the bound
                        continue
                    at = _stamp(raw, day)
                    if at is not None:
                        first, last = (at if first is None else first), at
                    out.write(raw)
                    content.update(raw)
                    written += len(raw)
                    lines += 1
            finally:
                if compress:
                    out.close()
            stored.flush()
            os.fsync(stored.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return dict(day=day.strftime('%Y%m%d'), source=TESTER_LOG_FOLDER + '\\' + source.name, source_bytes=size,
                source_start=start, source_stop=stop, path=str(target), sha256=_sha256(target), bytes=target.stat().st_size,
                compressed=compress, content_sha256=content.hexdigest(), content_bytes=written, lines=lines,
                first_line_time=_local(first), last_line_time=_local(last),
                truncated=None if half is None else dict(block_bytes=stop - start, bound_bytes=limit, omitted_lines=omitted))


def keep(terminal_data_root, since, until, folder, *, name=MEMBER_FILE, compress=False, limit=MAX_MEMBER_BYTES, first_day=True):
    """Copy the tester journal lines stamped within [since, until] (epoch seconds) into ``folder``, one file per local
    day, and return the record to store. Never raises: whatever stops a copy is the record's reason.

    ``copied`` needs the lines of the run's first day (``first_day``; a batch, whose earlier days MT5 has removed by
    its finish, needs any line); every other day with no line is listed (``days_without_lines``)."""
    record = dict(schema=SCHEMA, status='missing', reason=None, source_folder=TESTER_LOG_FOLDER, files=[], days_without_lines=[],
                  window=dict(since_unix=since, until_unix=until),
                  copied_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    try:
        if not _finite(since) or not _finite(until) or until < since:
            record['reason'] = 'The run has no recorded start and end time, so its journal lines cannot be told apart'
            return record
        record['window'].update(since_local=_local(since), until_local=_local(until))
        first, last = datetime.fromtimestamp(since).date(), datetime.fromtimestamp(until).date()
        days = [first + timedelta(days=step) for step in range((last - first).days + 1)]
        if len(days) > MAX_DAYS:
            record['reason'] = 'The run spans %d days; at most %d day logs are copied' % (len(days), MAX_DAYS)
            return record
        logs, folder = Path(terminal_data_root).joinpath(*TESTER_LOG_FOLDER.split('\\')), Path(folder)
        for day in days:
            source = logs / (day.strftime('%Y%m%d') + '.log')
            shown, why = TESTER_LOG_FOLDER + '\\' + source.name, None
            try:
                if source.is_symlink() or not source.is_file():
                    why = shown + ' does not exist'
                else:
                    start, stop, size = _slice(source, day, since, until)
                    if start >= stop:
                        why = '%s has no line between %s and %s' % (shown, _local(since), _local(until))
            except (OSError, ValueError) as error:
                why = '%s cannot be read (%s)' % (shown, str(error)[:200] or type(error).__name__)
            if why is None:
                folder.mkdir(parents=True, exist_ok=True)
                needed = (stop - start) // (4 if compress else 1) + MIN_FREE_BYTES
                if shutil.disk_usage(folder).free < needed:
                    why = '%s was not copied: the evidence volume has less than %d MiB free' % (shown, needed // (1024 * 1024))
            if why is not None:
                record['days_without_lines'].append(dict(day=day.strftime('%Y%m%d'), reason=why))
                continue
            record['files'].append(_copy(source, folder / (name % day.strftime('%Y%m%d')), start, stop, size, day,
                                         compress=compress, limit=limit))
        if record['files'] and (not first_day or record['files'][0]['day'] == first.strftime('%Y%m%d')):
            record['status'] = 'copied'
        else:
            record['reason'] = record['days_without_lines'][0]['reason']
    except Exception as error:
        record.update(status='missing', reason='The tester journal could not be copied: ' + (str(error)[:300] or type(error).__name__))
    return record


def keep_member(install, evidence_dir, since, until):
    """A catch-up member's journal block: inside its evidence folder, or beside it when the member left none."""
    folder = Path(evidence_dir)
    if folder.is_dir():
        return keep(install.get('terminal_data_root'), since, until, folder, limit=MAX_MEMBER_BYTES)
    return keep(install.get('terminal_data_root'), since, until, folder.parent, name=folder.name + '.' + MEMBER_FILE, limit=MAX_MEMBER_BYTES)


def _last_member_words(record):
    first = next((item['first_line_time'] for item in (record or {}).get('files') or [] if item.get('first_line_time')), None)
    return ('This copy holds the last member\'s lines only%s: MT5 rewrites the tester day log at every optimisation start. It is '
            'not the batch\'s journal; each member\'s proof is its report, its effective-inputs.set and its capture.'
            % ('' if first is None else ' (from %s)' % first))


def keep_batch(install, attempt_folder, job, *, now=None):
    """What is left of a Prove batch's journal at its finish, from its launch intent to now, next to the attempt's
    result.json: the lines since its last member's optimisation started (``covers: last_member_only``)."""
    since = _wall(((job.get('launch_intent') or {}).get('recorded_at')))
    record = keep(install.get('terminal_data_root'), since, time.time() if now is None else now,
                  Path(attempt_folder) / BATCH_FOLDER, name=BATCH_FILE, compress=True, limit=None, first_day=False)
    return record | dict(covers=LAST_MEMBER_ONLY, covers_plain=_last_member_words(record))


# ---------------------------------------------------------------------------
# The read-only check (tester-journal-check)
# ---------------------------------------------------------------------------

def verify(record, *, locate=None):
    """('ok' | 'missing' | 'changed', problems) for one stored record: every recorded copy exists with its recorded
    size and SHA-256. ``locate(path)`` gives where a moved copy is now (evidence-archive), or None."""
    if not isinstance(record, dict) or record.get('schema') != SCHEMA:
        return 'missing', ['No tester journal copy was recorded for it']
    if record.get('status') != 'copied' or not record.get('files'):
        return 'missing', [record.get('reason') or 'The tester journal copy was recorded as missing']
    state, problems = 'ok', []
    for item in record['files']:
        try:
            path = Path(item['path'])
            moved = locate(path) if locate is not None else None
            path = Path(moved) if moved is not None else path
            if not path.is_file():
                state = 'missing' if state == 'ok' else state
                problems.append('The copy %s is gone' % item['path'])
            elif path.stat().st_size != item['bytes'] or _sha256(path) != item['sha256']:
                state = 'changed'
                problems.append('The copy %s no longer matches its recorded SHA-256 %s' % (item['path'], item['sha256']))
        except Exception as error:
            state = 'missing' if state == 'ok' else state
            problems.append('The copy %s cannot be read (%s)' % (item.get('path'), str(error)[:200] or type(error).__name__))
    return state, problems


def coverage(record):
    """What an intact copy covers of its run's journal, which is a separate question from whether the copy is intact:
    ``whole`` only when no day of the run is without lines and no copy was cut at the bound. A member whose block ran
    past MAX_MEMBER_BYTES keeps its first and last half (``truncated``), and a run over midnight whose later day log was
    gone is still recorded ``copied`` on its first day (``days_without_lines``): both verify, neither is the whole
    journal. A batch's copy holds its last member only and is never whole."""
    files = (record or {}).get('files') or []
    cut = [dict(day=item.get('day'), **item['truncated']) for item in files if item.get('truncated')]
    without = list((record or {}).get('days_without_lines') or [])
    last_member = (record or {}).get('covers') == LAST_MEMBER_ONLY
    said = ['the copy of %s was cut at the %d-byte bound (%d lines left out of a %d-byte block)'
            % (item['day'], item['bound_bytes'], item['omitted_lines'], item['block_bytes']) for item in cut]
    said += [item['reason'] for item in without]
    if last_member:
        said.append('it holds the batch\'s last member only')
    return dict(whole=bool(files) and not cut and not without and not last_member, truncated=cut, days_without_lines=without,
                plain=None if not said else '; '.join(said))


def _files(record):
    return [{key: item.get(key) for key in ('day', 'path', 'sha256', 'bytes', 'lines', 'first_line_time', 'last_line_time', 'truncated')}
            for item in (record or {}).get('files') or []]


def _result(kind, run_id, status, finished, rows, counts):
    """``ok``: every recorded copy is in place and unchanged (integrity). ``complete``: the copies are the run's whole
    journal (coverage), which only a catch-up's can be, and only when no member's copy was cut at the bound or lacks a
    day of its run (``partial`` names those members); a batch's copy holds its last member only and is never complete."""
    ok = finished and not any(counts.get(state) for state in ('missing', 'changed', 'running'))
    partial = [row for row in rows if row['journal'] == 'ok' and not row['coverage']['whole']]
    if ok and kind == 'batch' and not counts.get('ok'):
        plain = 'Batch %s never launched, so there is no tester journal to keep.' % run_id
    elif ok and kind == 'batch':
        plain = ('The tester journal copy of batch %s is in place and matches its recorded SHA-256, but it is not the batch\'s '
                 'journal. ' % run_id) + _last_member_words(dict(files=[item for row in rows for item in row['files']]))
    elif ok and partial:
        named = '; '.join('%s: %s' % (row['name'], row['coverage']['plain']) for row in partial)[:900]
        plain = ('Every tester journal copy of %s %s is in place and matches its recorded SHA-256, but %d of %d %s not the '
                 'member\'s whole journal: %s.' % (kind, run_id, len(partial), len(rows), 'is' if len(partial) == 1 else 'are', named))
    elif ok:
        plain = 'Every tester journal copy of %s %s is in place and matches its recorded SHA-256.' % (kind, run_id)
    elif not finished:
        plain = 'The %s %s has not finished (%s), so its tester journal is not complete yet.' % (kind, run_id, status)
    else:
        named = '; '.join('%s: %s' % (row['name'], row['problems'][0]) for row in rows if row['journal'] in ('missing', 'changed'))[:600]
        plain = ('%d of %d tester journal %s of %s %s missing or changed: %s.'
                 % (counts.get('missing', 0) + counts.get('changed', 0), len(rows), 'copies' if len(rows) != 1 else 'copy', kind, run_id, named))
    return dict(schema=CHECK_SCHEMA, kind=kind, id=run_id, status=status, ok=ok, complete=ok and kind != 'batch' and not partial,
                covers=LAST_MEMBER_ONLY if kind == 'batch' else 'every_member', counts=counts,
                partial=[dict(name=row['name'], coverage=row['coverage']) for row in partial], plain=plain, writes=False)


def check_catchup(controller_root, catchup_id):
    """tester-journal-check for a catch-up: per member, whether its journal copy exists and matches its recorded hash.
    Read-only: the retained manifest and state are read as they are; nothing is observed, collected or written."""
    from studio_catchup import CATCHUP_FILE_ROOM, MAX_ID, io_path, plain
    from studio_evidence_archive import archived_location
    from studio_seed import SeedRunner
    from studio_seed_results import MAX_MANIFEST_BYTES, read_seed_json
    if not isinstance(catchup_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', catchup_id):
        raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
    folder = io_path(Path(controller_root) / 'catchups', 1 + MAX_ID + 1 + CATCHUP_FILE_ROOM) / catchup_id
    if not (folder / 'state.json').is_file():
        raise ValueError('No catch-up %s under this controller state' % catchup_id)
    manifest, state = read_seed_json(folder / 'manifest.json', MAX_MANIFEST_BYTES), read_seed_json(folder / 'state.json')
    locate = lambda path: archived_location(controller_root, plain(path))
    rows, counts = [], {}
    for spec, item in zip(manifest['members'], state['members']):
        problems = []
        if item['status'] in SeedRunner.LIVE_MEMBER or item['status'] == 'reconcile_required':
            journal, problems = 'running', ['The member has not ended (%s)' % item['status']]
        elif not _finite(item.get('started_unix')):
            journal = 'not_run'                  # never launched: there is no journal to keep
        else:
            journal, problems = verify(item.get('tester_journal'), locate=locate)
        counts[journal] = counts.get(journal, 0) + 1
        rows.append(dict(name=spec['alias'], alias=spec['alias'], status=item['status'], journal=journal, problems=problems,
                         files=_files(item.get('tester_journal')), coverage=coverage(item.get('tester_journal'))))
    result = _result('catch-up', catchup_id, state['status'], state['status'] in FINISHED, rows, counts)
    return result | dict(members=rows)


def check_batch(controller_root, job):
    """tester-journal-check for a Prove batch (a Studio queue row read read-only): whether the journal copy its finish
    recorded (``completion.tester_journal``) exists and matches its recorded hash. That copy holds the batch's last
    member only, so the result is never ``complete``: ``ok`` says the copy is intact, not that the batch has a journal."""
    record = (job.get('completion') or {}).get('tester_journal') if isinstance(job.get('completion'), dict) else None
    finished = job.get('status') in SETTLED
    if not finished:
        journal, problems = 'running', ['The batch has not finished (%s)' % job.get('status')]
    elif 'launch_intent' not in job:
        journal, problems = 'not_run', []            # never launched: there is no journal to keep
    else:
        journal, problems = verify(record)
    rows = [dict(name=job['job_id'], journal=journal, problems=problems, files=_files(record), coverage=coverage(record))]
    members = (job.get('configuration') or {}).get('batch_members') or [job.get('configuration')]
    result = _result('batch', job['job_id'], job.get('status'), finished, rows, {journal: 1})
    return result | dict(member_count=len(members), result_path=job.get('completion_path'), journal=journal, problems=problems,
                         files=_files(record), coverage=coverage(record),
                         days_without_lines=(record or {}).get('days_without_lines') or [])
