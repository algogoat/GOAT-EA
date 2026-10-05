"""Read-only research queue for one installation: every batch, seed hunt and catch-up, one row each.

research-status describes the one activity a terminal runs now. The queue lists every job beside it, so
the desktop's Research queue and agents see everything a PC is doing from one controller call
(goatai#2240, #1885) instead of reading the controller's files themselves:

* Refine: native Studio batches, from the bound session's queue rows (``studio.sqlite``, read only);
* Explore: seed hunts, from ``seeds/<id>/state.json`` and ``manifest.json``;
* Prove: OOS catch-ups, from ``catchups/<id>/``, and hold-up tests (one frozen SET, one MT5 pass), from
  ``holdups/<id>/`` (the same runner format).

Every row names its run in ``batch_id``. Both CLIs print replies through ``guard_output``, which redacts
each row's values derived from a held-out locked window per strategy key and window, exactly as for
research-status (results, plain notes); progress counts, dates and state stay readable.

Nothing here opens the mutable store, takes the terminal lock, launches, closes or signals MT5, and
nothing is written. Missing or unreadable evidence never becomes a guess: a run whose state or manifest
cannot be read whole, or disagree, is listed in ``skipped`` with its reason instead of as a row.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from studio_research_status import ACTIVE, _bounded_json, batch_progress, seed_progress

JOB_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')
STAGE = dict(batch='refine', seed='explore', catchup='prove', holdup='prove')
RUNNER_FOLDER = dict(seed='seeds', catchup='catchups', holdup='holdups')
STATES = ('queued', 'running', 'pausing', 'paused', 'blocked', 'finished', 'stopped', 'failed')
ENDED = frozenset(('finished', 'stopped', 'failed'))
FINISHED_DEFAULT = 5        # ended jobs kept (most recent first); unfinished jobs are always listed
FINISHED_MAX = 50
MAX_RUN_FOLDERS = 2000      # runner folders listed per kind
MAX_RUNS_READ = 25          # most recently written runner folders read per kind
MAX_RUNNER_JSON = 32 * 1024 * 1024
# Runner members that ran to an end (a result or a failure); a cancelled member never ran.
RAN = frozenset(('completed', 'failed', 'timeout', 'missing_output'))
FAILED = frozenset(('failed', 'timeout', 'missing_output'))
RUNNER_STATUSES = frozenset(('prepared', 'closing_monitor', 'active', 'pausing', 'paused', 'reconcile_required',
                             'completed', 'stopped'))
_RANK = dict(running=0, pausing=0, blocked=1, paused=2, queued=3, finished=4, stopped=4, failed=4)


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds')


def _finite(value):
    return type(value) in (int, float) and value == value and value not in (float('inf'), float('-inf'))


def _distinct(values):
    seen = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return seen


def _plural(count, noun):
    return str(count) + ' ' + noun + ('' if count == 1 else 's')


def _row(kind, batch_id, *, state, status, note, symbols, timeframes, total, done, started, finished, eta, results):
    return dict(batch_id=batch_id, kind=kind, stage=STAGE[kind], state=state, status=status, note=note,
                symbols=symbols, timeframes=timeframes, members_total=total, members_done=done,
                started_utc=started, finished_utc=finished, eta_utc=eta if state == 'running' else None, **results)


# ---------------------------------------------------------------------------
# Refine: native Studio batches
# ---------------------------------------------------------------------------

def _batch_state(job, pause, progress, unactivated):
    """(state, note) for one queue row; the pause record and the native evidence refine the queue status."""
    status, batch_id = job.get('status'), job['job_id']
    pause_state = (pause or {}).get('state')
    if unactivated:
        return 'blocked', ('Start failed before MT5 was touched; nothing ran. Settle it with retire-unactivated --job-id '
                           + batch_id + ', then prepare its members again under a new batch ID.')
    if pause_state == 'pausing':
        return 'pausing', 'Pausing at the next safe point.'
    if pause_state == 'paused':
        return 'paused', 'Paused; batch-resume continues the remaining members as a successor batch.'
    if pause_state == 'pause_failed':
        return 'blocked', ((pause.get('failure') or {}).get('message') or 'The pause failed.')
    if pause_state == 'resumed':
        successor = pause.get('successor_batch_id')
        return 'stopped', ('Continued as ' + successor + '.') if isinstance(successor, str) else 'Continued in a successor batch.'
    if status == 'pending':
        return ('running', 'Starting.') if 'launch_intent' in job else ('queued', 'Prepared; not started.')
    if status in ACTIVE:
        return 'running', None
    if status == 'completed':
        return 'finished', None
    if status == 'cancelled':
        return 'stopped', None
    if status == 'failed':
        # No-edge members keep an Error status: a batch of results and no failures is not a failed batch.
        if progress.get('members_no_edge') and progress.get('members_failed') == 0:
            return ('stopped' if progress.get('members_cancelled') else 'finished'), None
        return 'failed', None
    return 'blocked', 'The queue reports status ' + str(status) + ', which GOAT does not know; batch-status shows this batch.'


def batch_row(root, install, job, *, now, with_progress=True):
    """One Refine row from a queue job. Native evidence is read only when asked (unfinished or kept rows)."""
    from studio_batch_pause import load as load_pause
    from studio_retire_unactivated import unactivated_hint
    root = Path(root)
    batch_id = job['job_id']
    configuration = job.get('configuration') or {}
    members = configuration.get('batch_members') or ([configuration] if configuration else [])
    testers = [(member.get('tester') or {}) if isinstance(member, dict) else {} for member in members]
    journal, _ = _bounded_json(root / 'batch-drivers' / (batch_id + '.json'))
    progress = (batch_progress(root, install, job, now=now, journal=journal) if with_progress
                else dict(members_total=len(members), evidence='not_read'))
    pause = load_pause(root, batch_id, quiet=True)
    unactivated = unactivated_hint(root, job) and progress.get('evidence') == 'native_evidence_missing'
    state, note = _batch_state(job, pause, progress, unactivated)
    counts = progress.get('status_counts') if isinstance(progress.get('status_counts'), dict) else None
    done = (counts.get('native_completed', 0) + counts.get('native_error', 0)) if counts is not None else (
        0 if progress.get('evidence') == 'not_started' else None)
    failed = progress.get('members_failed')
    if type(failed) is int and failed > 0 and state != 'failed':
        note = ' '.join(filter(None, (note, _plural(failed, 'member') + ' failed.')))
    # Started: the bounded driver's own start, else the recorded launch intent (a studio start has no driver).
    started = journal.get('started_wall') if isinstance(journal, dict) else None
    intent = job.get('launch_intent') if isinstance(job.get('launch_intent'), dict) else {}
    started = _iso(started) if _finite(started) else intent.get('recorded_at') if isinstance(intent.get('recorded_at'), str) else None
    completion = job.get('completion') if isinstance(job.get('completion'), dict) else {}
    finished = (completion.get('native') or {}).get('observed_at') if isinstance(completion.get('native'), dict) else None
    return _row('batch', batch_id, state=state, status=job.get('status') if isinstance(job.get('status'), str) else 'unknown', note=note,
                symbols=_distinct(t.get('Symbol') for t in testers), timeframes=_distinct(t.get('Period') for t in testers),
                total=progress.get('members_total', len(members)), done=done, started=started,
                finished=finished if state in ENDED and isinstance(finished, str) else None,
                eta=(progress.get('pace') or {}).get('eta_utc'),
                results=dict(qualifying=progress.get('qualifying'), members_no_edge=progress.get('members_no_edge'),
                             members_failed=failed, evidence=progress.get('evidence')))


# ---------------------------------------------------------------------------
# Explore and Prove: seed hunts and catch-ups
# ---------------------------------------------------------------------------

def runner_row(root, kind, batch_id, *, now):
    """One Explore or Prove row, or (None, reason) when the run cannot be read whole."""
    folder = Path(root) / RUNNER_FOLDER[kind] / batch_id
    state, _ = _bounded_json(folder / 'state.json', MAX_RUNNER_JSON)
    manifest, _ = _bounded_json(folder / 'manifest.json', MAX_RUNNER_JSON)
    if not isinstance(state, dict) or not isinstance(manifest, dict):
        return None, 'state.json or manifest.json is missing, too large or not whole JSON'
    members, specs = state.get('members'), manifest.get('members')
    if (state.get('batch_id', batch_id) != batch_id or manifest.get('batch_id', batch_id) != batch_id
            or not isinstance(members, list) or not members or not isinstance(specs, list) or len(specs) != len(members)
            or not all(isinstance(m, dict) and isinstance(m.get('status'), str) for m in members)
            or not all(isinstance(s, dict) and isinstance(s.get('tester'), dict) for s in specs)):
        return None, 'state.json and manifest.json disagree or are incomplete'
    progress = seed_progress(root, batch_id, now=now, kind=kind)
    status = progress.get('status')
    if status not in RUNNER_STATUSES:
        return None, 'unknown run status ' + str(status)
    noun = dict(seed='candidate', catchup='re-test', holdup='test')[kind]
    statuses = [m['status'] for m in members]
    cancelled, failed = statuses.count('cancelled'), sum(s in FAILED for s in statuses)
    completed = statuses.count('completed')
    note = None
    if status == 'prepared':
        row_state = 'queued'
    elif status == 'closing_monitor':
        row_state, note = 'running', 'Starting: GOAT is handing this MT5 over to the run.'
    elif status == 'active':
        row_state = 'running'
    elif status == 'pausing':
        row_state, note = 'pausing', 'Pausing after the current ' + noun + '.'
    elif status == 'paused':
        row_state, note = 'paused', 'Paused between ' + noun + 's; batch-resume continues the rest.'
    elif status == 'reconcile_required':
        settle = progress.get('settle') or {}
        row_state = 'blocked'
        note = ('Needs settling: GOAT could not confirm how a ' + noun + ' started, so nothing runs. Settle it with '
                + (settle.get('command') or (kind + '-reconcile')) + ' ' + (settle.get('argument') or '') ).strip() + '.'
    elif status == 'completed':
        row_state = 'finished'
    else:   # stopped: cancelled, every attempted member failed, or the failure breaker tripped with members pending
        pending = statuses.count('pending')
        row_state = 'stopped' if cancelled or pending else 'finished' if completed else 'failed'
        if cancelled:
            note = 'Stopped before ' + _plural(cancelled, noun) + ' ran.'
        elif pending:
            reason = state.get('stopped_reason') if isinstance(state.get('stopped_reason'), dict) else {}
            note = (reason['plain'][:600] if isinstance(reason.get('plain'), str) else
                    'Stopped; ' + kind + '-resume continues the ' + _plural(pending, 'pending ' + noun) + '.')
    if failed:
        note = ('Every ' + noun + ' failed.') if row_state == 'failed' else ' '.join(filter(None, (note, _plural(failed, noun) + ' failed.')))
    started = [m['started_unix'] for m in members if _finite(m.get('started_unix'))]
    ended = [m['finished_unix'] for m in members if _finite(m.get('finished_unix'))]
    finished = max(ended) if ended else (state.get('updated_unix') if _finite(state.get('updated_unix')) else None)
    testers = [s['tester'] for s in specs]
    results = (dict(qualifying=progress.get('qualifying'), qualifying_candidates=progress.get('qualifying_candidates'))
               if kind == 'seed' else dict(profitable=progress.get('profitable')) if kind == 'holdup'
               else dict(held_up=progress.get('held_up')))
    if not completed:
        results = {key: None for key in results}
    return _row(kind, batch_id, state=row_state, status=status, note=note,
                symbols=_distinct(t.get('Symbol') for t in testers), timeframes=_distinct(t.get('Period') for t in testers),
                total=len(members), done=sum(s in RAN for s in statuses),
                started=_iso(min(started)) if started else None,
                finished=_iso(finished) if row_state in ENDED and finished is not None else None,
                eta=(progress.get('pace') or {}).get('eta_utc'), results=results), None


def _runner_ids(root, kind):
    """The most recently written run folders of one kind (real folders only, never links)."""
    base = Path(root) / RUNNER_FOLDER[kind]
    try:
        entries = [p for p in base.iterdir() if JOB_ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink()][:MAX_RUN_FOLDERS]
    except OSError:
        return []
    stamped = []
    for path in entries:
        try:
            stamped.append((path.joinpath('state.json').stat().st_mtime, path.name))
        except OSError:
            continue
    return [name for _, name in sorted(stamped, reverse=True)[:MAX_RUNS_READ]]


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def _when(row):
    return row.get('finished_utc') or row.get('started_utc') or ''


def research_queue(*, root, install, session, now, jobs=None, finished=FINISHED_DEFAULT):
    """Every job of one installation, one row each: unfinished ones always, then the ``finished`` most
    recent ended ones. Running and pausing first, then blocked, paused and queued, then the ends."""
    from studio_research_status import queue_jobs
    import sqlite3
    if type(finished) is not int or not 0 <= finished <= FINISHED_MAX:
        raise ValueError('--finished keeps 0..%d ended jobs' % FINISHED_MAX)
    root = Path(root)
    queue_error = None
    if jobs is None:
        try:
            jobs = queue_jobs(root, session)
        except (OSError, sqlite3.Error, ValueError) as error:
            jobs, queue_error = [], str(error)[:240]
    rows, skipped = [], []
    valid = [job for job in jobs if isinstance(job, dict) and isinstance(job.get('job_id'), str) and JOB_ID.fullmatch(job['job_id'])]
    # Light rows first, then native evidence only for unfinished jobs and the most recent ended ones.
    light = [batch_row(root, install, job, now=now, with_progress=False) for job in valid]
    ended_ids = [row['batch_id'] for row in light[::-1] if row['state'] in ENDED][:finished]   # newest last in the queue
    for job, row in zip(valid, light):
        if row['state'] not in ENDED or row['batch_id'] in ended_ids:
            try:
                rows.append(batch_row(root, install, job, now=now))
            except (OSError, ValueError, KeyError, TypeError) as error:
                skipped.append(dict(batch_id=job['job_id'], kind='batch', reason='native evidence unreadable: ' + str(error)[:200]))
    for kind in ('seed', 'catchup', 'holdup'):
        for batch_id in _runner_ids(root, kind):
            row, reason = runner_row(root, kind, batch_id, now=now)
            if row is None:
                skipped.append(dict(batch_id=batch_id, kind=kind, reason=reason))
            else:
                rows.append(row)
    unfinished = [row for row in rows if row['state'] not in ENDED]
    ends = sorted((row for row in rows if row['state'] in ENDED), key=_when, reverse=True)[:finished]
    ordered = sorted(unfinished, key=lambda row: (_RANK[row['state']], row['kind'] != 'batch', row['batch_id'])) + ends
    return dict(schema_version=1, observed_utc=_iso(now), rows=ordered, finished_kept=finished,
                skipped=skipped, queue_error=queue_error, read_only=True, launch_permitted=False)
