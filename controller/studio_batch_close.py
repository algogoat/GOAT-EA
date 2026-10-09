"""batch-pause-close: end a paused native batch for good, deleting nothing (goatai#2350 6083618615).

A paused batch could only be resumed (studio_batch_pause), so a batch closed "as partial" by
decision kept a ``paused`` record forever. ``close`` turns that record into terminal history:

* ``finish`` (the default): exports, receipts, journals and qualified sets stay where they are
  and go into the book and pack as normal. The unrun members are listed so a later PLANNED run
  can pick them up; the batch itself never resumes (every resume and continue path refuses).
* ``exclude``: the same record, plus a free-text reason and an exclusion marker
  ``batch-exclusions/<job>.json`` naming the batch's native run folder and every export SET
  (path and sha256). ``evidence-scan`` and ``catchup-prepare`` read the marker and report those
  exports ``ineligible`` with ``excluded`` set (``excluded_reason``). Nothing is deleted. Exclusion is
  refused once any export of the batch entered a FOOS read or a selection decision this
  controller can see (``foos_reads``), and when that cannot be checked.

Every trial counts under both modes: ``members_done`` lists each member that ran (a member
cancelled after it started counts too) as ``{index, member_id, configuration_sha256, set_sha256,
symbol, timeframe, outcome}``. ``member_identities`` builds that list for both this record and
the finished batch's ``attempts/<attempt>/result.json`` (studio_finish), so a research-side
reader sees finished and closed batches alike. The controller writes no trial ledger: the
deflation N lives in goatai's prereg files.

Preconditions (stable refusal codes, nothing written on refusal): the pause record is exactly
``paused`` and bound to its retained finish result, the driver journal (when present) stopped,
no planned successor that may have run, and ``--confirm``. The terminal-idle check (no running
batch, seed slot or unreleased fixed task, no live driver) belongs to the caller, which holds the
terminal lock around it (demo_agent.batch_pause_close). Closing again with the same mode is a no-op;
another mode refuses.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_refusal import Refusal

SCHEMA_VERSION = 1
MODES = ('finish', 'exclude')
EXCLUSIONS = 'batch-exclusions'
EXCLUSION_SCHEMA = 'goat-batch-exclusion-v1'
MAX_REASON = 2000
MAX_EXPORTS = 20000
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_RUNNER_MANIFEST = 32 * 1024 * 1024
TERMINAL = frozenset(('completed', 'cancelled', 'failed'))

# Refusal codes (append only).
CODES = frozenset((
    'CLOSE_CONFIRM_REQUIRED', 'CLOSE_INVALID_MODE', 'CLOSE_REASON_REQUIRED', 'CLOSE_NO_PAUSE', 'CLOSE_NOT_PAUSED',
    'CLOSE_MODE_CONFLICT', 'CLOSE_RESULT_CHANGED', 'CLOSE_DRIVER_NOT_STOPPED', 'CLOSE_SUCCESSOR_PLANNED',
    'CLOSE_TERMINAL_BUSY', 'CLOSE_NOT_NATIVE_BATCH', 'CLOSE_UNKNOWN_BATCH', 'CLOSE_NOT_DEMO',
    'CLOSE_EXCLUDE_AFTER_FOOS_READ', 'CLOSE_EXCLUDE_AFTER_SELECTION', 'CLOSE_EXCLUDE_UNVERIFIABLE', 'BATCH_CLOSED'))


def _utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _bounded(path, limit):
    """Parsed JSON or None for a missing file; raises ValueError for one that is unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    if path.stat().st_size > limit:
        raise ValueError(str(path) + ' exceeds ' + str(limit) + ' bytes')
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))


# ---------------------------------------------------------------------------
# Member identities: one shape for finished and closed batches
# ---------------------------------------------------------------------------

def member_identities(root, job, member_outcomes, research_outcomes=()):
    """``(members_done, members_unrun)`` of one native batch from its per-member native outcomes.

    A member is done (a trial) when it ended ``native_completed`` or ``native_error`` (``outcome``
    completed, no-edge or failed), or ended ``native_cancelled`` after it started (``cancelled``).
    Whether a cancelled member started is read from the job's retained native evidence history the
    way the trial journal reads it; when that history is unavailable the member counts as a trial
    (``start_known: false``), never as unrun-only. Unrun members are every member without an end
    result, with ``started`` true, false or null (unknown).
    """
    configuration = job.get('configuration') or {}
    members = configuration.get('batch_members') or ([configuration] if configuration.get('tester') else [])
    try:
        sources = _bounded(Path(root) / 'packages' / (job['job_id'] + '.source.json'), MAX_MANIFEST_BYTES) or {}
    except (OSError, ValueError, UnicodeError):
        sources = {}
    source_members = sources.get('members') if isinstance(sources, dict) and isinstance(sources.get('members'), list) else []
    no_edge = {item.get('index') for item in research_outcomes or () if isinstance(item, dict)}
    started, history_read = None, False
    done, unrun = [], []
    for index, outcome in enumerate(member_outcomes or []):
        outcome = outcome if isinstance(outcome, dict) else {}
        member = members[index] if index < len(members) and isinstance(members[index], dict) else None
        tester = (member or {}).get('tester') or outcome.get('tester') or {}
        source = source_members[index] if index < len(source_members) and isinstance(source_members[index], dict) else {}
        identity = dict(index=index, member_id=outcome.get('run_alias'),
                        configuration_sha256=sha(member) if member else None,
                        set_sha256=source.get('set_sha256') if isinstance(source.get('set_sha256'), str) else None,
                        symbol=tester.get('Symbol') or outcome.get('symbol'), timeframe=tester.get('Period'))
        status = outcome.get('status')
        if status == 'native_completed':
            done.append(dict(identity, outcome='completed', start_known=True))
            continue
        if status == 'native_error':
            done.append(dict(identity, outcome='no-edge' if index in no_edge else 'failed', start_known=True))
            continue
        if not history_read:
            from studio_trial_journal import _history
            started, history_read = _history(root, job), True
        ran = None if started is None else index in started
        if status == 'native_cancelled' and ran is not False:
            done.append(dict(identity, outcome='cancelled', start_known=ran is not None))
        unrun.append(dict(identity, status=status, started=ran))
    return done, unrun


# ---------------------------------------------------------------------------
# Exports of a batch, FOOS reads and the exclusion marker
# ---------------------------------------------------------------------------

def run_root(root, install, job_id):
    """The batch's native run folder (``<Common Files>/<native_run_relative>``) from its package manifest."""
    manifest = _bounded(Path(root) / 'packages' / job_id / 'manifest.json', MAX_MANIFEST_BYTES)
    relative = (manifest or {}).get('native_run_relative') if isinstance(manifest, dict) else None
    if not isinstance(relative, str) or not relative:
        raise ValueError('the package manifest of batch ' + job_id + ' names no native run folder')
    return Path(install['common_files_root']) / relative.replace('\\', '/')


def batch_exports(run):
    """Every export SET under the run's deploy folder: [{set_path, set_sha256}], sorted by path."""
    deploy = Path(run) / 'deploy'
    found = []
    for path in sorted(deploy.rglob('*.set')) if deploy.is_dir() else []:
        if len(found) >= MAX_EXPORTS:
            raise ValueError('more than %d export SETs under %s' % (MAX_EXPORTS, deploy))
        found.append(dict(set_path=str(path), set_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return found


def _within(path, folder):
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError, TypeError):
        return False


def foos_reads(root, install, run, exports, *, now=None):
    """Where this controller shows an export of the batch read on FOOS or selected, or raises ValueError.

    * a catch-up (``catchups/<id>/manifest.json``) or hold-up test (``holdups/<id>/manifest.json``)
      member whose ``source_sha256`` is an export SET of the batch, or whose ``source_path`` (catch-up
      ``original.set_path``) lies in its run folder: a FOOS read (the re-test runs past the export);
    * a held-out lock whose frozen candidate (``freeze`` cells) holds an export's ``set_sha256``: a
      selection decision.

    An unreadable runner manifest or an unverifiable lock registry raises: exclusion then refuses,
    because it cannot prove nothing was read. Selections recorded outside this controller (goatai
    prereg files, the book's own pool) are not visible here.
    """
    shas = {item['set_sha256'] for item in exports}
    hits = []
    for folder, kind in (('catchups', 'catch-up'), ('holdups', 'hold-up test')):
        base = Path(root) / folder
        for path in sorted(base.glob('*/manifest.json')) if base.is_dir() else []:
            try:
                manifest = _bounded(path, MAX_RUNNER_MANIFEST)
            except (OSError, ValueError, UnicodeError) as error:
                raise ValueError('the %s manifest %s is unreadable (%s)' % (kind, path, str(error)[:200])) from None
            members = manifest.get('members') if isinstance(manifest, dict) else None
            for member in members if isinstance(members, list) else []:
                if not isinstance(member, dict):
                    continue
                source = member.get('source_path') or (member.get('original') or {}).get('set_path')
                digest = member.get('source_sha256') or (member.get('original') or {}).get('set_sha256')
                if digest in shas or (isinstance(source, str) and _within(source, run)):
                    hits.append(dict(kind='foos_read', via=kind, run_id=path.parent.name, set_path=source,
                                     set_sha256=digest, manifest=str(path)))
    from studio_heldout import read_registry
    registry = read_registry(install, now=now)
    if registry['state'] == 'unavailable':
        raise ValueError('the held-out lock registry cannot be verified (' + str(registry['error']) + ')')
    for lock in registry['locks']:
        for cell in lock.get('candidate') or []:
            if cell.get('set_sha256') in shas:
                hits.append(dict(kind='selection', via='held-out lock freeze', lock_id=lock['lock_id'],
                                 strategy_key=lock.get('strategy_key'), set_sha256=cell['set_sha256']))
    return hits


def exclusion_path(root, job_id):
    from studio_batch_pause import path as pause_path
    pause_path(root, job_id)                       # validates the ID
    return safe_path(Path(root) / EXCLUSIONS / (job_id + '.json'))


def exclusions(root):
    """Retained exclusion markers of this controller: {batch_id: marker}. Unreadable markers raise."""
    folder = Path(root) / EXCLUSIONS
    found = {}
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        value = _bounded(path, MAX_MANIFEST_BYTES)
        if (not isinstance(value, dict) or value.get('schema') != EXCLUSION_SCHEMA or value.get('batch_id') != path.stem
                or not isinstance(value.get('exports'), list)):
            raise ValueError('Batch exclusion marker ' + str(path) + ' is not a ' + EXCLUSION_SCHEMA + ' record')
        found[path.stem] = value
    return found


def apply_exclusions(rows, markers):
    """Mark evidence rows whose export belongs to an excluded batch: ``ineligible`` with ``excluded``.

    A row matches by its native run folder name (``run_id``) or by the exact SET sha256 (a library
    copy outside the run folder). Other rows are returned unchanged.
    """
    if not markers:
        return rows
    by_run, by_sha = {}, {}
    for marker in markers.values():
        if isinstance(marker.get('run_id'), str):
            by_run[marker['run_id'].lower()] = marker
        for item in marker['exports']:
            if isinstance(item, dict) and isinstance(item.get('set_sha256'), str):
                by_sha[item['set_sha256']] = marker
    result = []
    for row in rows:
        marker = by_run.get(str(row.get('run_id') or '').lower()) or by_sha.get(row.get('set_sha256'))
        if marker is None:
            result.append(row)
            continue
        reason = 'Excluded from book and pack: batch %s was closed with exclude (%s)' % (marker['batch_id'], marker['reason'])
        result.append(dict(row, status='ineligible', reasons=list(row.get('reasons') or []) + [reason],
                           excluded=True, excluded_batch_id=marker['batch_id'], excluded_reason=marker['reason'],
                           excluded_at=marker.get('closed_at')))
    return result


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------

def _verify_paused(root, job, record):
    from studio_batch_pause import refusal
    job_id = job['job_id']
    if record['state'] != 'paused':
        message = str(refusal(record))
        raise Refusal('Batch ' + job_id + ' cannot be closed: it is ' + str(record['state']) + ', not paused. ' + message,
                      'CLOSE_NOT_PAUSED', batch_id=job_id, pause_state=record['state'])
    result = Path(record.get('result_path') or '')
    try:
        digest = hashlib.sha256(result.read_bytes()).hexdigest() if record.get('result_path') else None
    except OSError:
        digest = None
    if (job.get('status') not in TERMINAL or job.get('completion_path') != str(result) or digest is None
            or digest != record.get('result_sha256')):
        raise Refusal('The paused result of batch ' + job_id + ' changed or is missing; inspect it with batch-status. '
                      'Nothing was closed.', 'CLOSE_RESULT_CHANGED', batch_id=job_id)
    journal = _bounded(Path(root) / 'batch-drivers' / (job_id + '.json'), 4 * 1024 * 1024)
    if isinstance(journal, dict) and journal.get('stopped') is not True:
        raise Refusal('The GOAT driver journal of batch ' + job_id + ' has not stopped (' + str(journal.get('status'))
                      + '); a paused batch is closed only after its driver stopped.', 'CLOSE_DRIVER_NOT_STOPPED', batch_id=job_id)


def _successor_planned(record, queue):
    from studio_batch_pause import planned_successor, unactivated_proof
    successor = planned_successor(record)
    if not successor:
        return None
    row = (queue or {}).get(successor)
    if row is None or unactivated_proof(row) is not None:
        return None
    return successor


def _exclusion(root, install, job_id, record, reason, closed_at, *, now):
    try:
        run = run_root(root, install, job_id)
        exports = batch_exports(run)
        hits = foos_reads(root, install, run, exports, now=now)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        raise Refusal('Exclude cannot prove that no export of batch ' + job_id + ' entered a FOOS read or a selection '
                      'decision: ' + str(error)[:300] + '. Nothing was closed; close with --mode finish, or repair it first.',
                      'CLOSE_EXCLUDE_UNVERIFIABLE', batch_id=job_id) from None
    if hits:
        selection = [hit for hit in hits if hit['kind'] == 'selection']
        code = 'CLOSE_EXCLUDE_AFTER_SELECTION' if selection else 'CLOSE_EXCLUDE_AFTER_FOOS_READ'
        raise Refusal('Exclude is refused: %d export(s) of batch %s already entered a %s, so its results are part of the '
                      'record. Close it with --mode finish instead.' % (len(hits), job_id,
                                                                        'selection decision' if selection else 'FOOS read'),
                      code, batch_id=job_id, reads=hits[:50])
    return _marker(job_id, record, reason, closed_at, run, exports)


def _marker(job_id, record, reason, closed_at, run, exports):
    return dict(schema=EXCLUSION_SCHEMA, schema_version=SCHEMA_VERSION, batch_id=job_id, pause_id=record['pause_id'],
                reason=reason, closed_at=closed_at, run_root=str(run), run_id=run.name, exports=exports,
                plain=('Every export of batch ' + job_id + ' is excluded from book and pack ingestion (' + str(reason)
                       + '). Nothing was deleted.'))


def _public(record, *, changed, exclusion=None):
    from studio_batch_pause import public
    value = public(record)
    for key in ('closed_mode', 'closed_at', 'closed_by', 'reason', 'members_done', 'members_done_count', 'members_unrun',
                'members_unrun_count', 'exclusion_path'):
        value[key] = record.get(key)
    value['changed'] = changed
    if exclusion is not None:
        value['exclusion'] = {key: exclusion.get(key) for key in ('run_id', 'run_root', 'plain')} | dict(
            exports=len(exclusion.get('exports') or []))
    return value


def close(root, install, job, *, mode='finish', reason=None, confirm=False, closed_by='agent', now, queue=None):
    """Close the paused batch ``job``. Returns its public record with ``changed``; refusals write nothing."""
    from studio_batch_pause import _note, _save, load
    job_id = job['job_id']
    if confirm is not True:
        raise Refusal('batch-pause-close changes batch ' + job_id + ' for good; pass --confirm.', 'CLOSE_CONFIRM_REQUIRED',
                      batch_id=job_id)
    if mode not in MODES:
        raise Refusal('Mode must be finish or exclude.', 'CLOSE_INVALID_MODE', batch_id=job_id)
    reason = reason.strip() if isinstance(reason, str) else ''
    if mode == 'exclude' and not reason:
        raise Refusal('Exclude needs a free-text --reason saying why these results are kept out of the book.',
                      'CLOSE_REASON_REQUIRED', batch_id=job_id)
    if len(reason) > MAX_REASON:
        raise Refusal('The reason is longer than %d characters.' % MAX_REASON, 'CLOSE_REASON_REQUIRED', batch_id=job_id)
    record = load(root, job_id)
    if record is None:
        raise Refusal('No pause is recorded for batch ' + job_id + '; only a paused batch can be closed.', 'CLOSE_NO_PAUSE',
                      batch_id=job_id)
    if record['state'] == 'closed':
        if record.get('closed_mode') != mode:
            raise Refusal('Batch ' + job_id + ' is already closed with ' + str(record.get('closed_mode')) + '; it cannot be '
                          'closed again with ' + mode + '.', 'CLOSE_MODE_CONFLICT', batch_id=job_id,
                          closed_mode=record.get('closed_mode'))
        exclusion = None
        if mode == 'exclude':
            # The record is the truth: a marker lost to an interruption between the two writes is written
            # again from the run folder. The exclusion was already decided, so no FOOS check repeats.
            target = exclusion_path(root, job_id)
            try:
                exclusion = _bounded(target, MAX_MANIFEST_BYTES)
            except (OSError, ValueError, UnicodeError):
                exclusion = None
            if not isinstance(exclusion, dict):
                run = run_root(root, install, job_id)
                exclusion = _marker(job_id, record, record.get('reason'), record.get('closed_at'), run, batch_exports(run))
                target.parent.mkdir(exist_ok=True)
                write_json(target, exclusion)
        return _public(record, changed=False, exclusion=exclusion)
    _verify_paused(root, job, record)
    successor = _successor_planned(record, queue)
    if successor:
        raise Refusal('Batch ' + job_id + ' already has a planned successor ' + successor + ' that may have run; settle '
                      'or finish that successor first. Nothing was closed.', 'CLOSE_SUCCESSOR_PLANNED',
                      batch_id=job_id, successor_batch_id=successor)
    completion = job.get('completion') or {}
    done, unrun = member_identities(root, job, completion.get('member_outcomes'), completion.get('research_outcomes'))
    closed_at = _utc(now)
    exclusion = _exclusion(root, install, job_id, record, reason, closed_at, now=now) if mode == 'exclude' else None
    record.update(state='closed', closed_mode=mode, closed_at=closed_at, closed_utc=now, closed_by=closed_by,
                  members_done=done, members_done_count=len(done), members_unrun=unrun, members_unrun_count=len(unrun),
                  blocker=None)
    if mode == 'exclude':
        record.update(reason=reason, exclusion_path=str(exclusion_path(root, job_id)), exclusion_run_id=exclusion['run_id'],
                      exclusion_exports=len(exclusion['exports']))
    _note(record, now, 'closed', mode=mode, closed_by=closed_by)
    _save(root, record)
    if exclusion is not None:
        target = exclusion_path(root, job_id)
        target.parent.mkdir(exist_ok=True)
        write_json(target, exclusion)
    return _public(record, changed=True, exclusion=exclusion)


def refuse_closed(root, job_id):
    """Every resume and continue path: a closed batch never resumes; its unrun members need a new planned run."""
    from studio_batch_pause import load
    record = load(root, job_id, quiet=True)
    if isinstance(record, dict) and record.get('state') == 'closed':
        raise Refusal('Batch ' + job_id + ' was closed (' + str(record.get('closed_mode')) + ') at '
                      + str(record.get('closed_at')) + ' and never resumes. Its ' + str(record.get('members_unrun_count'))
                      + ' unrun member(s) are listed in its pause record (members_unrun): prepare them as a new planned '
                      'batch.', 'BATCH_CLOSED', batch_id=job_id, closed_mode=record.get('closed_mode'))
