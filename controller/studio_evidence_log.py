"""Append-only native evidence logs outside the queue row.

The queue row (studio_queues.jobs) is parsed by every controller state read.
Reconcile used to append each changed native observation (per-member statuses,
input artifacts, report pairs, runtime feedback) to ``native_evidence_history``
inside that row, which nothing reads back. On Banker that grew the store to
7.8 GB: each state read took tens of seconds and a 1122-member start spent
206 s before its first process re-check (2026-10-03).

Evidence is still retained in full: each observation is one JSON line in
``native-evidence/<job>-<attempt16>.jsonl`` under the controller state root,
fsynced before the queue commit that references it. The job keeps only the
latest observation, the log path, the entry count and the hash of the last line.

``compact`` moves an existing in-row history of a *finished* job into such a log,
verifies the bytes it wrote, and only then removes the in-row copy.
"""
import hashlib
import json
import os
from pathlib import Path

from campaign_ledger import packed

TERMINAL = ('completed', 'cancelled', 'failed')


def _root(store):
    return Path(store.db.execute('PRAGMA database_list').fetchone()[2]).parent


def log_path(root, job_id, attempt_id):
    return Path(root) / 'native-evidence' / (job_id + '-' + attempt_id[:16] + '.jsonl')


def _line(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def append(store, job_id, attempt_id, evidence, *, previous=None):
    """Append one observation; returns the reference the job row keeps."""
    from studio_handover import safe_path
    path = safe_path(log_path(_root(store), job_id, attempt_id))
    path.parent.mkdir(exist_ok=True)
    raw = _line(evidence)
    with path.open('ab') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    entries = (previous or {}).get('entries', 0) + 1 if (previous or {}).get('path') == str(path) else 1
    return dict(path=str(path), entries=entries, last_sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    """Every retained observation, in order."""
    with Path(path).open('rb') as source:
        return [json.loads(line) for line in source if line.strip()]


def compact(controller, *, apply=False):
    """Move in-row evidence history of finished jobs into logs. Preview unless apply.

    Only finished jobs are touched; a running job keeps its row history until it
    finishes. The archive is written and re-read before the row changes, and the
    row records the archive's hash and entry count.
    """
    from studio_handover import safe_path
    state = controller.state()
    candidates = [job for job in state['queue']
                  if job.get('status') in TERMINAL and job.get('native_evidence_history')]
    before = len(packed(state['queue']))
    plan = [dict(job_id=job['job_id'], entries=len(job['native_evidence_history']),
                 bytes=len(packed(job['native_evidence_history']))) for job in candidates]
    if not apply or not candidates:
        return dict(applied=False, queue_bytes=before, jobs=plan,
                    next_action=('compact-evidence --apply moves these into append-only logs' if candidates
                                 else 'Nothing to compact'))
    active = [job['job_id'] for job in state['queue']
              if job.get('status') in ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')]
    if active:
        raise ValueError('Batch ' + active[0] + ' is active; compact evidence when no batch is starting or running.')
    archives = {}
    for job in candidates:
        attempt = job.get('launch_intent', {}).get('attempt_id', 'unknown-attempt')
        path = safe_path(Path(controller.root) / 'native-evidence' / (job['job_id'] + '-' + attempt[:16] + '.history.jsonl'))
        path.parent.mkdir(exist_ok=True)
        raw = b''.join(_line(entry) for entry in job['native_evidence_history'])
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('A different evidence archive already exists for ' + job['job_id'] + '; inspect ' + str(path))
        else:
            with path.open('xb') as output:
                output.write(raw); output.flush(); os.fsync(output.fileno())
        if read(path) != json.loads(packed(job['native_evidence_history'])):
            raise ValueError('Evidence archive readback differs for ' + job['job_id'] + '; row history kept')
        archives[job['job_id']] = dict(path=str(path), entries=len(job['native_evidence_history']),
                                       sha256=hashlib.sha256(raw).hexdigest(), compacted_from='native_evidence_history')
    binding = packed(dict(terminal_id=controller.terminal, run_id=controller.run))
    with controller.store.transaction():
        current = controller.store.snapshot(controller.terminal, controller.run)
        for job in current['queue']:
            archive = archives.get(job['job_id'])
            if archive is None:
                continue
            if job.get('status') not in TERMINAL or len(job.get('native_evidence_history') or []) != archive['entries']:
                raise ValueError('Job ' + job['job_id'] + ' changed during compaction; nothing was changed, retry')
            job.pop('native_evidence_history')
            job['native_evidence_archive'] = archive
        controller.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(current['queue']), binding))
        controller.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
    after = len(packed(controller.state()['queue']))
    return dict(applied=True, queue_bytes_before=before, queue_bytes_after=after, jobs=plan,
                archives=list(archives.values()))
