"""Append-only native evidence logs outside the queue row.

The queue row (studio_queues.jobs) is parsed by every controller state read.
Reconcile used to append each changed native observation (per-member statuses,
input artifacts, report pairs, runtime feedback) to ``native_evidence_history``
inside that row, which nothing reads back. On Banker that grew the row to 818 MB
(770 MB of it history, 29 jobs): every state read parsed it for 3.4 s and a
1122-member start spent 206 s before its first process re-check (2026-10-03).

Evidence is still retained in full: each observation is one JSON line in
``native-evidence/<job>-<attempt16>.jsonl`` under the controller state root,
fsynced before the queue commit that references it. The job keeps only the
latest observation, the log path, the committed entry count and byte length, and
the hash of the last line. Each line carries a deterministic evidence identity
(job, attempt, sequence number, evidence hash), so a crash between the fsync and
the queue commit never duplicates a line or corrupts the count: the retry finds
the identical uncommitted tail and adopts it, and a different uncommitted tail is
moved aside (``.uncommitted``) before the next committed line is written.

``compact`` moves an existing in-row history of a *finished* job into such a log,
verifies the archive by sha256, and only then removes the in-row copy.
"""
import hashlib
import json
import os
from pathlib import Path
import uuid

from campaign_ledger import packed, sha

TERMINAL = ('completed', 'cancelled', 'failed')
ACTIVE = ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
RECORD_KEYS = frozenset(('evidence_id', 'seq', 'job_id', 'attempt_id', 'evidence_sha256', 'evidence'))
CHUNK = 1 << 20


def _root(store):
    return Path(store.db.execute('PRAGMA database_list').fetchone()[2]).parent


def log_path(root, job_id, attempt_id):
    return Path(root) / 'native-evidence' / (job_id + '-' + attempt_id[:16] + '.jsonl')


def _line(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def evidence_id(job_id, attempt_id, seq, evidence_sha256):
    """Deterministic identity of one committed observation."""
    return sha([job_id, attempt_id, seq, evidence_sha256])


def _committed_bytes(path, previous):
    """Byte length the queue row has committed for this log."""
    if type(previous.get('bytes')) is int:
        return previous['bytes']
    # A reference written before byte lengths were recorded: the first `entries` lines.
    offset, wanted = 0, previous.get('entries', 0)
    with Path(path).open('rb') as source:
        for _ in range(wanted):
            line = source.readline()
            if not line.endswith(b'\n'):
                raise ValueError('Evidence log is shorter than its committed entries; inspect ' + str(path))
            offset += len(line)
    return offset


def append(store, job_id, attempt_id, evidence, *, previous=None):
    """Append one observation idempotently; returns the reference the job row keeps."""
    from studio_handover import safe_path
    path = safe_path(log_path(_root(store), job_id, attempt_id))
    path.parent.mkdir(exist_ok=True)
    previous = previous or {}
    same = previous.get('path') == str(path)
    entries = previous.get('entries', 0) if same else 0
    committed = _committed_bytes(path, previous) if same and path.exists() else 0
    seq = entries + 1
    digest = hashlib.sha256(_line(evidence)).hexdigest()
    ident = evidence_id(job_id, attempt_id, seq, digest)
    raw = _line(dict(evidence_id=ident, seq=seq, job_id=job_id, attempt_id=attempt_id,
                     evidence_sha256=digest, evidence=evidence))
    reference = dict(path=str(path), entries=seq, bytes=committed + len(raw),
                     last_sha256=hashlib.sha256(raw).hexdigest(), last_evidence_id=ident)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o644)
    with os.fdopen(fd, 'r+b') as output:
        size = output.seek(0, os.SEEK_END)
        if size < committed:
            raise ValueError('Evidence log is shorter than its committed entries; inspect ' + str(path))
        if size > committed:
            # Written and fsynced by an attempt whose queue commit never happened.
            output.seek(committed)
            tail = output.read()
            if tail == raw:
                return reference          # the same observation: adopt it, write nothing
            aside = safe_path(path.with_name(path.name + '.uncommitted'))
            with aside.open('ab') as kept:
                kept.write(tail); kept.flush(); os.fsync(kept.fileno())
            output.truncate(committed)
        output.seek(committed)
        output.write(raw); output.flush(); os.fsync(output.fileno())
    return reference


def read(path, entries=None):
    """Every retained observation, in order (only the first ``entries`` if given)."""
    result = []
    with Path(path).open('rb') as source:
        for line in source:
            if not line.strip():
                continue
            if entries is not None and len(result) >= entries:
                break
            value = json.loads(line)
            result.append(value['evidence'] if isinstance(value, dict) and set(value) == RECORD_KEYS else value)
    return result


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def history_sha256(history):
    """Archive digest of an in-row history, serialised one entry at a time."""
    digest, size = hashlib.sha256(), 0
    for entry in history:
        raw = _line(entry); digest.update(raw); size += len(raw)
    return digest.hexdigest(), size


def retirement_proof_path(root, job):
    attempt = (job.get('launch_intent') or {}).get('attempt_id')
    if not isinstance(attempt, str) or not attempt:
        return None
    return Path(root) / 'attempts' / attempt / 'never-started-retirement' / 'retirement.json'


def _protected(root, job):
    """A never-started retirement proof compares this whole job row to job-before.json."""
    path = retirement_proof_path(root, job)
    return path is not None and path.exists()


def _archive_path(root, job):
    from studio_handover import safe_path
    attempt = (job.get('launch_intent') or {}).get('attempt_id', 'unknown-attempt')
    return safe_path(Path(root) / 'native-evidence' / (job['job_id'] + '-' + attempt[:16] + '.history.jsonl'))


def write_archive(path, history, job_id):
    """Temp file, fsync, verify by sha256, then atomic replace. Returns (sha256, bytes)."""
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open('xb') as output:
            for entry in history:
                raw = _line(entry); output.write(raw); digest.update(raw); size += len(raw)
            output.flush(); os.fsync(output.fileno())
        expected = digest.hexdigest()
        if file_sha256(temporary) != expected:
            raise ValueError('Evidence archive readback differs for ' + job_id + '; row history kept')
        if path.exists():
            if file_sha256(path) != expected:
                raise ValueError('A different evidence archive already exists for ' + job_id + '; inspect ' + str(path))
        else:
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if file_sha256(path) != expected:
        raise ValueError('Evidence archive readback differs for ' + job_id + '; row history kept')
    return expected, size


def queue_bytes(controller):
    """Stored size of this binding's queue row, without parsing it."""
    row = controller.store.db.execute('SELECT length(CAST(jobs AS BLOB)) FROM studio_queues WHERE binding=?',
                                      (packed(dict(terminal_id=controller.terminal, run_id=controller.run)),)).fetchone()
    return 0 if row is None or row[0] is None else row[0]


def _active_refusal(active):
    return ValueError('Batch ' + active[0] + ' is active; compact evidence when no batch is starting or running.')


def _journal(root, result):
    """Durable record of a committed compaction, built from the transaction result."""
    path = Path(root) / 'native-evidence' / 'compactions.jsonl'
    record = {key: result[key] for key in ('queue_bytes_before', 'queue_bytes_after', 'revision', 'archives', 'skipped')}
    with path.open('ab') as output:
        output.write(_line(record)); output.flush(); os.fsync(output.fileno())
    return str(path)


def compact(controller, *, apply=False):
    """Move in-row evidence history of finished jobs into logs. Preview unless apply.

    Only finished jobs are touched; a running job keeps its row history until it
    finishes. A job whose never-started retirement proof compares the whole row
    (``attempts/<attempt>/never-started-retirement/retirement.json``) is skipped.
    Each archive is written to a temporary file, fsynced, verified by sha256 and
    atomically renamed before the row changes. Inside the queue transaction the
    active-batch refusal and every archived history are re-checked against the
    current row; the journal is recorded from that transaction's result.
    """
    root = Path(controller.root)
    before = queue_bytes(controller)
    state = controller.state()
    active = [job['job_id'] for job in state['queue'] if job.get('status') in ACTIVE]
    candidates, skipped = [], []
    for job in state['queue']:
        if job.get('status') not in TERMINAL or not job.get('native_evidence_history'):
            continue
        if _protected(root, job):
            skipped.append(dict(job_id=job['job_id'], reason='never_started_retirement_proof',
                                plain='Kept in the row: its never-started retirement proof compares the whole job row.'))
            continue
        candidates.append(job)
    if not apply or not candidates:
        plan = [dict(job_id=job['job_id'], entries=len(job['native_evidence_history']),
                     bytes=history_sha256(job['native_evidence_history'])[1]) for job in candidates]
        return dict(applied=False, queue_bytes=before, jobs=plan, skipped=skipped,
                    next_action=('compact-evidence --apply moves these into append-only logs' if candidates
                                 else 'Nothing to compact'))
    if active:
        raise _active_refusal(active)
    archives = {}
    for job in candidates:
        path = _archive_path(root, job)
        digest, size = write_archive(path, job['native_evidence_history'], job['job_id'])
        archives[job['job_id']] = dict(path=str(path), entries=len(job['native_evidence_history']),
                                       sha256=digest, bytes=size, compacted_from='native_evidence_history')
    # Drop the first parsed copy before the transaction parses the row again.
    del state, candidates, job
    binding = packed(dict(terminal_id=controller.terminal, run_id=controller.run))
    with controller.store.transaction():
        current = controller.store.snapshot(controller.terminal, controller.run)
        active = [row['job_id'] for row in current['queue'] if row.get('status') in ACTIVE]
        if active:
            raise _active_refusal(active)
        for row in current['queue']:
            archive = archives.get(row['job_id'])
            if archive is None:
                continue
            history = row.get('native_evidence_history') or []
            if (row.get('status') not in TERMINAL or _protected(root, row) or len(history) != archive['entries']
                    or history_sha256(history)[0] != archive['sha256']):
                raise ValueError('Job ' + row['job_id'] + ' changed during compaction; nothing was changed, retry')
            del row['native_evidence_history']
            row['native_evidence_archive'] = archive
        raw = packed(current['queue'])
        revision = current['revision'] + 1
        del current
        controller.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (raw, binding))
        controller.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
        after = len(raw)                    # packed() is ASCII: characters == stored bytes
        del raw
    result = dict(applied=True, queue_bytes_before=before, queue_bytes_after=after, revision=revision,
                  jobs=[dict(job_id=job_id, entries=item['entries'], bytes=item['bytes']) for job_id, item in archives.items()],
                  skipped=skipped, archives=list(archives.values()))
    try:
        result['journal'] = _journal(root, result)
    except OSError as error:
        # The compaction is committed; report the journal failure instead of hiding the commit.
        result['journal_error'] = str(error)
    return result
