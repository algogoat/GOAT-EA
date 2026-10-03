"""Receipts keep a digest of the queue, never the queue itself.

A ``studio_receipts`` row records one applied command: its request identity,
command, status, ``execution_effect`` and the resulting ``state``. That state
used to embed the whole queue. On Banker (2026-10-02) the queue row was 818 MB,
so every reserve/batch/cancel receipt was 818 MB as well: 62 receipts held
9.78 GB of an 11.4 GB ``studio.sqlite``, each start attempt wrote ~1.6 GB, and
the renewed-epoch authority scans parsed every receipt on every state read.

Nothing reads ``receipt.state.queue`` back:

* replay compares only ``payload_hash`` and returns the stored receipt;
* the bridge outbox copies only ``terminal_id``, ``run_id``, ``revision``,
  ``generation`` and ``owner`` (the MQL side reads ``state.revision``);
* the authority, regrant, owner-research and owner-maintenance checks read
  ``request_id``, ``command``, ``status``, ``execution_effect`` and those same
  state fields.

So a receipt now stores ``state.queue_digest = {"sha256", "job_count"}`` in
place of ``state.queue``. The digest is ``sha256`` of the queue's canonical JSON
(``campaign_ledger.packed``), i.e. ``campaign_ledger.sha(queue)``. Anything that
needs the queue reads current state, never a receipt.

``receipt_views`` is how the checks read receipts: SQLite removes
``state.queue`` (``json_remove``) before Python parses anything, so a legacy
row costs one C-level JSON pass and no Python objects for its queue.

``compact`` (``compact-receipts``) rewrites legacy rows to the digest form after
archiving their exact original bytes; see its docstring.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from campaign_ledger import packed

DIGEST_KEY = 'queue_digest'
ACTIVE = ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
CHUNK = 1 << 20
ARCHIVE_DIR = ('native-evidence', 'receipt-archive')
JOURNAL = ('native-evidence', 'receipt-compactions.jsonl')
_SAFE_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


def queue_digest(queue, raw=None):
    """{sha256, job_count} of a queue; ``raw`` is its packed JSON when already built."""
    if raw is None:
        raw = packed(queue)
    return dict(sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(), job_count=len(queue))


def receipt_state(state, raw_queue=None):
    """The state a receipt stores: every field except the queue, plus its digest."""
    stored = {key: value for key, value in state.items() if key != 'queue'}
    stored[DIGEST_KEY] = queue_digest(state['queue'], raw_queue)
    return stored


_VIEW_SQL = ("SELECT request_id,payload_hash,"
             "CASE WHEN json_valid(receipt) THEN json_remove(receipt,'$.state.queue') END "
             "FROM studio_receipts WHERE binding=?")


def receipt_views(db, binding, request_id=None, *, object_pairs_hook=None):
    """[(request_id, payload_hash, receipt_without_state_queue)] for one binding.

    SQLite validates the receipt and drops ``state.queue`` before Python sees
    it, so a legacy multi-hundred-MB row is never parsed into Python objects.
    Every other field is returned exactly as stored (duplicate keys included,
    so ``object_pairs_hook=unique_object`` still refuses them). A receipt that
    is not valid JSON raises ValueError, as ``json.loads`` did.
    """
    sql, params = _VIEW_SQL, [binding]
    if request_id is not None:
        sql += ' AND request_id=?'
        params.append(request_id)
    views = []
    for rid, payload_hash, text in db.execute(sql, params).fetchall():
        if text is None:
            raise ValueError('Receipt ' + str(rid) + ' is not valid JSON')
        views.append((rid, payload_hash, json.loads(text, object_pairs_hook=object_pairs_hook)))
    return views


# ---------------------------------------------------------------- compaction

def active_batches(db):
    """Job IDs of any queue (any binding) that is starting or running; parsed by SQLite."""
    marks = ','.join('?' * len(ACTIVE))
    return [row[0] for row in db.execute(
        "SELECT json_extract(j.value,'$.job_id') FROM studio_queues q, json_each(q.jobs) j "
        "WHERE json_extract(j.value,'$.status') IN (" + marks + ")", ACTIVE)]


def _active_refusal(active):
    return ValueError('Batch ' + str(active[0]) + ' is active; compact receipts when no batch is starting or running.')


def binding_tag(binding):
    return hashlib.sha256(binding.encode('utf-8')).hexdigest()[:12]


def archive_path(root, binding, request_id):
    """One archive file per receipt (request ID within its binding)."""
    from studio_handover import safe_path
    name = request_id if _SAFE_ID.fullmatch(request_id) else 'id-' + hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:32]
    return safe_path(Path(root).joinpath(*ARCHIVE_DIR) / (name + '.' + binding_tag(binding) + '.receipt.json'))


def _candidates(db):
    """One SQLite pass over every receipt; Python only sees small columns."""
    rows = db.execute(
        "SELECT binding,request_id,payload_hash,length(CAST(receipt AS BLOB)),"
        "CASE WHEN json_valid(receipt) THEN json_type(receipt,'$.state.queue') END,"
        "CASE WHEN json_valid(receipt) THEN json_type(receipt,'$.state." + DIGEST_KEY + "') END,"
        "CASE WHEN json_valid(receipt) THEN json_array_length(receipt,'$.state.queue') END,"
        "json_valid(receipt) FROM studio_receipts ORDER BY rowid").fetchall()
    candidates, skipped, compact_rows = [], [], 0
    for binding, request_id, payload_hash, size, queue_type, digest_type, count, valid in rows:
        item = dict(binding=binding, request_id=request_id, payload_hash=payload_hash, bytes=size)
        if not valid:
            skipped.append(dict(request_id=request_id, bytes=size, reason='invalid_json',
                                plain='Kept as is: the stored receipt is not valid JSON.'))
        elif queue_type is None:
            compact_rows += 1
        elif queue_type != 'array' or digest_type is not None:
            skipped.append(dict(request_id=request_id, bytes=size, reason='unexpected_shape',
                                plain='Kept as is: state.queue is not a list, or a digest is already present.'))
        else:
            candidates.append(dict(item, job_count=count))
    return candidates, skipped, compact_rows


def _locate(db, item):
    row = db.execute('SELECT rowid,payload_hash FROM studio_receipts WHERE binding=? AND request_id=?',
                     (item['binding'], item['request_id'])).fetchone()
    if row is None or row[1] != item['payload_hash']:
        raise ValueError('Receipt ' + item['request_id'] + ' changed during compaction; nothing was changed for it, retry')
    return row[0]


class _Noncanonical(Exception):
    pass


def _frame(view):
    """Exact bytes before and after the queue in the receipt's canonical (packed) form."""
    state = view.get('state') if isinstance(view, dict) else None
    if not isinstance(state, dict):
        raise _Noncanonical()
    marker = 'goat-receipt-queue-' + uuid.uuid4().hex
    probe = dict(view, state=dict(state, queue=marker))
    text = packed(probe)
    token = json.dumps(marker)
    if text.count(token) != 1:
        raise _Noncanonical()
    prefix, suffix = text.split(token)
    return prefix.encode('utf-8'), suffix.encode('utf-8')


def _stream(db, rowid, sink=None, frame=None):
    """Stream one stored receipt in chunks; never holds it whole.

    Returns (sha256, bytes, queue_sha256 or None). With ``frame`` the bytes
    around the queue must equal the canonical prefix/suffix exactly.
    """
    full, middle = hashlib.sha256(), hashlib.sha256()
    head, tail, edges = b'', b'', [None, None]
    with db.blobopen('studio_receipts', 'receipt', rowid, readonly=True) as blob:
        size = len(blob)
        if frame is not None:
            lo, hi = len(frame[0]), size - len(frame[1])
            if hi - lo < 2:
                raise _Noncanonical()
        offset = 0
        while offset < size:
            chunk = blob.read(CHUNK)
            if not chunk:
                raise ValueError('Receipt stream ended early; nothing was changed for it, retry')
            end = offset + len(chunk)
            full.update(chunk)
            if sink is not None:
                sink.write(chunk)
            if frame is not None:
                if offset < lo:
                    head += chunk[:lo - offset]
                start, stop = max(offset, lo), min(end, hi)
                if start < stop:
                    piece = chunk[start - offset:stop - offset]
                    middle.update(piece)
                    if edges[0] is None:
                        edges[0] = piece[:1]
                    edges[1] = piece[-1:]
                if end > hi:
                    tail += chunk[max(hi - offset, 0):]
            offset = end
    if frame is not None and (head != frame[0] or tail != frame[1] or edges != [b'[', b']']):
        raise _Noncanonical()
    return full.hexdigest(), size, (middle.hexdigest() if frame is not None else None)


def _archive(db, rowid, path, frame):
    """Temp file, fsync, sha256 readback, then atomic replace. An identical existing archive is reused."""
    from studio_evidence_log import file_sha256
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as output:
            digest, size, queue_sha = _stream(db, rowid, output, frame)
            output.flush(); os.fsync(output.fileno())
        if file_sha256(temporary) != digest:
            raise ValueError('Receipt archive readback differs for ' + path.name + '; the receipt row is kept')
        if path.exists():
            if file_sha256(path) != digest:
                raise ValueError('A different receipt archive already exists at ' + str(path) + '; inspect it, the receipt row is kept')
        else:
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if file_sha256(path) != digest:
        raise ValueError('Receipt archive readback differs for ' + path.name + '; the receipt row is kept')
    return digest, size, queue_sha


def _authority(controller):
    """The same session authority a state read checks, without parsing the queue."""
    from studio_research_authority import authority
    binding = packed(dict(terminal_id=controller.terminal, run_id=controller.run))
    row = controller.store.db.execute('SELECT owner,generation,revision FROM studio_state WHERE binding=?', (binding,)).fetchone()
    if row is None:
        raise ValueError('Unknown terminal/run binding')
    authority(controller.store.db, binding, dict(owner=row[0], generation=row[1], revision=row[2]))


def _journal(root, result):
    from studio_evidence_log import _line
    path = Path(root).joinpath(*JOURNAL)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {key: result[key] for key in ('binding', 'request_id', 'payload_hash', 'bytes_before', 'bytes_after',
                                           'queue_digest', 'archive')}
    with path.open('ab') as output:
        output.write(_line(record)); output.flush(); os.fsync(output.fileno())
    return str(path)


def compact(controller, *, apply=False):
    """Rewrite legacy receipts to the queue-digest form. Preview unless apply.

    For each receipt that still embeds ``state.queue``, one at a time:

    1. SQLite returns the receipt without its queue (small). The canonical
       bytes before and after the queue are rebuilt from that.
    2. The stored bytes are streamed from the row (``blobopen``, 1 MiB chunks)
       into ``native-evidence/receipt-archive/<request_id>.<binding12>.receipt.json``
       (temp file, fsync, sha256 readback, ``os.replace``). The same pass checks
       the bytes around the queue against the canonical frame and hashes the
       queue bytes in between: that is ``sha256(packed(queue))``. A row that is
       not in the canonical layout is skipped and left as is.
    3. One ``BEGIN IMMEDIATE`` transaction under the mutation gate refuses if a
       batch became active or the session authority changed, re-streams the row
       and requires its sha256 to equal the archive's (re-read from disk), takes
       the job count from that locked row, then rewrites only that row. The
       journal line comes from that transaction's result.

    Never runs while a batch is starting or running. Never deletes an archive and
    never VACUUMs: the file keeps its size until a separate reviewed VACUUM.
    Idempotent: compact rows are not candidates, and an identical archive left
    by an interrupted run is reused.
    """
    db = controller.store.db
    root = Path(controller.root)
    _authority(controller)
    encoding = db.execute('PRAGMA encoding').fetchone()[0]
    candidates, skipped, compact_rows = _candidates(db)
    active = active_batches(db)
    total = sum(item['bytes'] for item in candidates)
    if not apply or not candidates:
        plan = [dict(request_id=item['request_id'], binding=json.loads(item['binding']), bytes=item['bytes'],
                     job_count=item['job_count'],
                     archive=str(archive_path(root, item['binding'], item['request_id']))) for item in candidates]
        return dict(applied=False, receipts=plan, receipt_bytes=total, already_compact=compact_rows,
                    skipped=skipped, active_batches=active,
                    next_action=('compact-receipts --apply archives each and stores its queue digest'
                                 + (' once no batch is active' if active else '') if candidates
                                 else 'Nothing to compact'))
    if active:
        raise _active_refusal(active)
    if encoding != 'UTF-8':
        raise ValueError('Receipt compaction requires a UTF-8 database, found ' + str(encoding))
    from studio_evidence_log import file_sha256
    done, journal_errors, journal = [], [], None
    for item in candidates:
        rowid = _locate(db, item)
        view = receipt_views(db, item['binding'], item['request_id'])[0][2]
        path = archive_path(root, item['binding'], item['request_id'])
        try:
            digest, size, queue_sha = _archive(db, rowid, path, _frame(view))
        except _Noncanonical:
            skipped.append(dict(request_id=item['request_id'], bytes=item['bytes'], reason='noncanonical_layout',
                                plain='Kept as is: the stored bytes are not in the canonical receipt layout.'))
            continue
        with controller.store.transaction():
            active = active_batches(db)
            if active:
                raise _active_refusal(active)
            _authority(controller)
            rowid = _locate(db, item)
            # The row must still be exactly the archived bytes; the frame check
            # above tied those bytes to ``view`` and ``queue_sha``.
            if _stream(db, rowid)[0] != digest or file_sha256(path) != digest:
                raise ValueError('Receipt ' + item['request_id'] + ' changed during compaction; nothing was changed for it, retry')
            count = db.execute("SELECT json_array_length(receipt,'$.state.queue') FROM studio_receipts WHERE rowid=?",
                               (rowid,)).fetchone()[0]
            view['state'][DIGEST_KEY] = dict(sha256=queue_sha, job_count=count)
            compacted = packed(view)
            del view
            changed = db.execute('UPDATE studio_receipts SET receipt=? WHERE rowid=? AND binding=? AND request_id=? AND payload_hash=?',
                                 (compacted, rowid, item['binding'], item['request_id'], item['payload_hash'])).rowcount
            if changed != 1:
                raise ValueError('Receipt ' + item['request_id'] + ' changed during compaction; nothing was changed for it, retry')
            result = dict(binding=json.loads(item['binding']), request_id=item['request_id'],
                          payload_hash=item['payload_hash'], bytes_before=size, bytes_after=len(compacted),
                          queue_digest=dict(sha256=queue_sha, job_count=count),
                          archive=dict(path=str(path), sha256=digest, bytes=size))
        del compacted
        try:
            journal = _journal(root, result)
        except OSError as error:
            # The row is committed; report the journal failure instead of hiding the commit.
            journal_errors.append(dict(request_id=item['request_id'], error=str(error)))
        done.append(result)
    outcome = dict(applied=bool(done), receipts=done, receipt_bytes_before=sum(r['bytes_before'] for r in done),
                   receipt_bytes_after=sum(r['bytes_after'] for r in done), already_compact=compact_rows,
                   skipped=skipped, journal=journal,
                   next_action=('Receipts compacted. studio.sqlite keeps its size until a separate reviewed VACUUM.'
                                if done else 'Nothing was compacted'))
    if journal_errors:
        outcome['journal_errors'] = journal_errors
    return outcome
