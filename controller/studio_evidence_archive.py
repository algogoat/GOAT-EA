"""evidence-archive: move a finished or closed batch's evidence off the controller volume (goatai#2350 6086117953).

The controller state folder keeps every native observation log, every archived full-queue receipt and every
catch-up re-test unit forever. On the Ops PC that is ~26 GB on C: (``native-evidence`` 10.9 GB, ``evidence``
3.6 GB). ``evidence-archive`` MOVES one finished or closed batch's evidence to another volume and leaves a
pointer; it never deletes evidence.

What belongs to a batch (``plan``). A file is moved only when its ownership is proven; every other candidate
is listed as ``not_attributable`` and stays where it is.

* Native batch (a Studio queue job of any session of this installation):
  - ``native-evidence/<job>-<attempt16>.jsonl``: the job row's ``native_evidence_log.path`` names it
    (studio_reconcile -> studio_evidence_log.append), plus its ``.uncommitted`` tail (append moves a different
    uncommitted tail there);
  - ``native-evidence/<job>-<attempt16>.history.jsonl``: the job row's ``native_evidence_archive.path``
    (compact-evidence, studio_evidence_log.compact);
  - a log of that name the row no longer names (an earlier attempt): only when its first line names the job
    (the append envelope's ``job_id``, or a history entry's ``native.studio_source.job_id``);
  - ``native-evidence/receipt-archive/<request_id>.<binding12>.receipt.json`` (compact-receipts,
    studio_receipt_digest): only when ``request_id`` is ``<job>-batch|-reserve|-cancel|-release-reservation``
    with an optional ``-rN`` (the request IDs the demo scope admits, studio_research_authority.command), its
    binding tag is a session whose queue holds the job, and that session's receipt row exists with the matching
    command and is already in the digest form (so compact-receipts never writes that archive again).
* OOS catch-up (``catchups/<id>``): its evidence folder under ``<controller state>/evidence``: the hashed
  ``c.<10 hex>`` folder whose ``catchup.json`` names the catch-up, or the legacy ``evidence/<catch-up id>``
  folder (studio_catchup.evidence_folder). Every file below it belongs to it. Evidence a catch-up wrote to an
  ``output_root`` outside the controller state is not on this volume and is not moved.

Seed hunts and hold-up tests keep their evidence in their own run folders; they are refused
(``ARCHIVE_UNSUPPORTED_KIND``).

How it moves (``apply``), resumable and idempotent:

1. Each file is copied to ``<archive root>/<installation>/<batch id>/<path below the controller state>``
   (temporary file, fsync, atomic rename), and its copy is read back and SHA-256 verified against the bytes
   read from the source. A copy already there with the same SHA-256 is reused (an interrupted run); a
   different one refuses.
2. ``manifest.json`` beside them lists every file (relative path, bytes, sha256, source path, ownership proof),
   the batch, the time and the controller revision. A manifest left by an interrupted run is reused only when it
   lists exactly the same files.
3. The pointer ``native-evidence/archived/<batch id>.json`` records the archive folder and the manifest
   SHA-256. Only then is each source removed, and only after its bytes still hash to the manifest's SHA-256 and
   its archive copy exists with that size. A re-run with a pointer verifies every archive copy and completes the
   removals an interruption left; it copies nothing again.

Readers (``resolve``, ``archived_evidence_roots``): every controller reader that resolves this evidence follows
the pointer (studio_trial_journal._history for trial-journal, trial-count, finish and batch-pause-close;
studio_catchup.evidence_roots/evidence_folder/versions for evidence-scan, evidence-versions, catchup-prepare and
catchup-report; equivalence-canary-ingest). With a pointer the archive is the truth: an unreachable archive root
(unplugged drive) or a manifest that no longer matches its pointer refuses ``EVIDENCE_ARCHIVE_UNREACHABLE``,
never a silent fallback. studio_evidence_log.append refuses to write to an archived batch.

Refusals (stable codes, nothing written): the batch is not finished or closed, a seed slot or any batch is
active, the batch is cited by a held-out lock or a FOOS/selection read this controller can see, it is on the
caller's ``--keep-list``, the archive root is on the controller's volume, missing, not writable or short of space
(the preview size plus a margin), or ``--confirm`` is missing. Prereg and book citations live outside the
controller (goatai prereg files, the book on G:): the keep-list is the caller's way to name them. The Exp 02
refusal belongs to the desktop gate, as with batch-pause-close.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from studio_refusal import Refusal

SCHEMA = 'goat-evidence-archive-manifest-v1'
POINTER_SCHEMA = 'goat-evidence-archive-pointer-v1'
SCHEMA_VERSION = 1
POINTERS = ('native-evidence', 'archived')
MANIFEST = 'manifest.json'
CHUNK = 1 << 20
MARGIN_BYTES = 1 << 30                 # free space needed beyond the preview size: 1 GiB or 5 %, whichever is larger
MARGIN_FRACTION = 0.05
MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_FIRST_LINE = 64 * 1024 * 1024
MAX_KEEP_LIST = 100000
MAX_PUBLIC_FILES = 500
TEMP_MARK = '.goat-archive-tmp'
JOB_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')
INSTALLATION_ID = re.compile(r'[A-Za-z0-9._-]{1,80}')
TERMINAL = ('completed', 'cancelled', 'failed')
ACTIVE = ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
RECEIPT_SUFFIXES = {'-batch': 'queue.enqueue_batch', '-reserve': 'queue.reserve', '-cancel': 'queue.cancel',
                    '-release-reservation': 'queue.release_reservation'}
RUNNER_ACTIVE_MEMBERS = ('pending', 'starting', 'running', 'cancel_requested', 'timeout_requested', 'reconcile_required')

# Refusal codes (append only). EVIDENCE_ARCHIVE_UNREACHABLE and EVIDENCE_ARCHIVED are the readers' and writers'.
CODES = frozenset((
    'ARCHIVE_CONFIRM_REQUIRED', 'ARCHIVE_NOT_DEMO', 'ARCHIVE_UNKNOWN_BATCH', 'ARCHIVE_UNSUPPORTED_KIND',
    'ARCHIVE_NOT_FINISHED', 'ARCHIVE_COMPACT_FIRST', 'ARCHIVE_TERMINAL_BUSY', 'ARCHIVE_CITED_FOOS_READ',
    'ARCHIVE_CITED_SELECTION', 'ARCHIVE_CITATIONS_UNVERIFIABLE', 'ARCHIVE_KEEP_LISTED', 'ARCHIVE_KEEP_LIST_INVALID',
    'ARCHIVE_ROOT_INVALID', 'ARCHIVE_ROOT_UNAVAILABLE', 'ARCHIVE_ROOT_SAME_VOLUME', 'ARCHIVE_ROOT_NOT_WRITABLE',
    'ARCHIVE_ROOT_LOW_SPACE', 'ARCHIVE_ALREADY_ARCHIVED', 'ARCHIVE_TARGET_CONFLICT', 'ARCHIVE_MANIFEST_CONFLICT',
    'ARCHIVE_VERIFY_FAILED', 'ARCHIVE_SOURCE_CHANGED', 'ARCHIVE_NOTHING_TO_MOVE',
    'EVIDENCE_ARCHIVE_UNREACHABLE', 'EVIDENCE_ARCHIVED'))


class ArchiveUnreachable(Refusal):
    """A pointer names an archive that cannot be read now: readers refuse instead of reading partial evidence."""

    def __init__(self, message, **fields):
        super().__init__(message, 'EVIDENCE_ARCHIVE_UNREACHABLE', **fields)


def _utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _io(path):
    """The path for IO: the \\\\?\\ extended-length form on Windows (catch-up evidence paths run long)."""
    from studio_handover import filesystem_path
    return filesystem_path(os.path.abspath(path))


def _plain(path):
    text = str(path)
    if text.startswith('\\\\?\\UNC\\'):
        return '\\\\' + text[8:]
    return text[4:] if text.startswith('\\\\?\\') else text


def _key(relative):
    """Comparison form of a path below the controller state: forward slashes, case-folded (Windows)."""
    return relative.replace('\\', '/').strip('/').casefold()


def _relative(root, path):
    """``path`` below ``root`` as a forward-slash relative path, or None."""
    try:
        relative = os.path.relpath(os.path.abspath(_plain(path)), os.path.abspath(_plain(root)))
    except ValueError:                       # another drive
        return None
    if relative == '.' or relative.startswith('..') or os.path.isabs(relative):
        return None
    return relative.replace('\\', '/')


def file_sha256(path):
    digest = hashlib.sha256()
    with _io(path).open('rb') as source:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_json(path, limit=MAX_RECORD_BYTES):
    path = _io(path)
    if path.stat().st_size > limit:
        raise ValueError(_plain(path) + ' exceeds ' + str(limit) + ' bytes')
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))


def controller_revision(install):
    """What wrote an archive: the controller version, the installed receipt's version and this module's sha256."""
    from studio_installation import VERSION
    try:
        module = file_sha256(__file__)
    except OSError:
        module = None
    return dict(controller_version=VERSION, installed_controller_version=(install or {}).get('controller_version'),
                module_sha256=module)


def installation_id(root):
    """The installation folder name under the suite (``ea01797bedf56eef7940``); a hash of the path otherwise."""
    name = Path(root).name
    return name if INSTALLATION_ID.fullmatch(name) and name not in ('.', '..') else \
        'i' + hashlib.sha256(os.path.abspath(root).encode('utf-8')).hexdigest()[:20]


def archive_dir(root, archive_root, batch_id):
    return Path(os.path.abspath(archive_root)) / installation_id(root) / batch_id


# ---------------------------------------------------------------------------
# Pointers and readers
# ---------------------------------------------------------------------------

def pointer_path(root, batch_id):
    if not isinstance(batch_id, str) or not JOB_ID.fullmatch(batch_id):
        raise ValueError('Invalid batch ID')
    return Path(root).joinpath(*POINTERS) / (batch_id + '.json')


def load_pointer(root, batch_id):
    """The batch's pointer, None when it has none. An unreadable pointer raises: its evidence is somewhere else."""
    path = pointer_path(root, batch_id)
    if not path.is_file():
        return None
    value = _bounded_json(path)
    if (not isinstance(value, dict) or value.get('schema') != POINTER_SCHEMA or value.get('batch_id') != batch_id
            or not isinstance(value.get('files'), list) or not isinstance(value.get('archive_dir'), str)):
        raise ValueError('Evidence archive pointer ' + str(path) + ' is not a ' + POINTER_SCHEMA + ' record')
    return value


_REACHABLE = {}
_INDEX = {}


def _index(root):
    """[(pointer, file keys, folder keys)] of every pointer, re-read only when a pointer file changes (a catch-up's
    versions() resolves several paths per member)."""
    folder = Path(root).joinpath(*POINTERS)
    paths = sorted(p for p in folder.glob('*.json') if JOB_ID.fullmatch(p.stem)) if folder.is_dir() else []
    stamp = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    cached = _INDEX.get(os.path.normcase(os.path.abspath(folder)))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    index = []
    for path in paths:
        pointer = load_pointer(root, path.stem)
        index.append((pointer, {_key(item) for item in pointer['files'] if isinstance(item, str)},
                      [_key(item) for item in pointer.get('folders') or [] if isinstance(item, str)]))
    _INDEX[os.path.normcase(os.path.abspath(folder))] = (stamp, index)
    return index


def _reachable(pointer):
    """Raise ArchiveUnreachable unless the pointer's archive folder and its exact manifest are readable now."""
    folder = Path(pointer['archive_dir'])
    manifest = folder / MANIFEST
    try:
        stat = _io(manifest).stat()
        cache = (str(manifest), stat.st_size, stat.st_mtime_ns, pointer.get('manifest_sha256'))
        if _REACHABLE.get(str(manifest)) == cache:
            return folder
        if file_sha256(manifest) != pointer.get('manifest_sha256'):
            raise ArchiveUnreachable('The evidence archive of batch %s at %s no longer matches its pointer (manifest '
                                     'sha256 differs); nothing is read from it. Inspect the archive.'
                                     % (pointer['batch_id'], folder), batch_id=pointer['batch_id'], archive_dir=str(folder))
    except OSError as error:
        raise ArchiveUnreachable('Batch %s evidence was archived to %s, which cannot be read now (%s). Reconnect the '
                                 'archive drive, then retry; nothing is read in its place.'
                                 % (pointer['batch_id'], folder, str(error)[:200]),
                                 batch_id=pointer['batch_id'], archive_dir=str(folder)) from None
    _REACHABLE[str(manifest)] = cache
    return folder


def archived_location(root, path):
    """Where ``path`` (a file or folder below the controller state) lives now when a pointer moved it, else None.

    Raises ArchiveUnreachable when the pointer's archive cannot be read now.
    """
    relative = _relative(root, path)
    if relative is None:
        return None
    key = _key(relative)
    if not key.startswith(('native-evidence/', 'evidence/')):
        return None
    for pointer, files, folders in _index(root):
        if key in files or any(key == folder or key.startswith(folder + '/') for folder in folders):
            return _reachable(pointer) / Path(relative)
    return None


def resolve(root, path):
    """``path`` itself, or its archived location when an evidence-archive pointer moved it."""
    moved = archived_location(root, path)
    return Path(path) if moved is None else moved


def archived_evidence_roots(root):
    """Catch-up evidence bases that moved to an archive (``<archive>/<installation>/<id>/evidence``), each verified
    reachable (ArchiveUnreachable otherwise), so studio_catchup reads them like ``<controller state>/evidence``."""
    bases = []
    for pointer, _, folders in _index(root):
        if any(folder.startswith('evidence/') for folder in folders):
            bases.append(_reachable(pointer) / 'evidence')
    return bases


def refuse_archived(root, job_id):
    """Writers: an archived batch's evidence is never appended to locally (it would split the evidence)."""
    try:
        exists = pointer_path(root, job_id).is_file()
    except ValueError:
        return
    if exists:
        raise Refusal('The evidence of batch ' + job_id + ' was moved by evidence-archive; nothing is appended to it.',
                      'EVIDENCE_ARCHIVED', batch_id=job_id)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def queue_bindings(root):
    """[(binding, jobs)] of every retained Studio queue of this installation, read-only."""
    from contextlib import closing
    database = Path(root) / 'studio.sqlite'
    if not database.is_file():
        return []
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT binding, jobs FROM studio_queues ORDER BY binding').fetchall()
    found = []
    for binding, text in rows:
        jobs = json.loads(text)
        found.append((binding, [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []))
    return found


def _receipt_rows(root, request_id):
    """{binding: (command, queue_type)} of the stored receipts with this request ID (none without the table)."""
    from contextlib import closing
    database = Path(root) / 'studio.sqlite'
    if not database.is_file():
        return {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_receipts'").fetchone():
            return {}
        rows = db.execute("SELECT binding, CASE WHEN json_valid(receipt) THEN json_extract(receipt,'$.command') END, "
                          "CASE WHEN json_valid(receipt) THEN json_type(receipt,'$.state.queue') END "
                          "FROM studio_receipts WHERE request_id=?", (request_id,)).fetchall()
    return {binding: (command, queue_type) for binding, command, queue_type in rows}


def _first_line_job(path):
    """The job a native evidence log names on its first line, or None (unreadable, too long, another shape)."""
    try:
        with _io(path).open('rb') as source:
            line = source.readline(MAX_FIRST_LINE + 1)
        if not line or len(line) > MAX_FIRST_LINE or not line.endswith(b'\n'):
            return None
        value = json.loads(line)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if isinstance(value.get('job_id'), str) and 'evidence' in value:          # append envelope (studio_evidence_log)
        return value['job_id']
    source = ((value.get('native') or {}) if isinstance(value.get('native'), dict) else {}).get('studio_source')
    return source.get('job_id') if isinstance(source, dict) else None        # a compacted in-row history entry


def _log_name(job_id):
    return re.compile(re.escape(job_id) + r'-([0-9a-f]{16}|unknown-attempt)(\.history)?\.jsonl(\.uncommitted)?')


def _receipt_name(job_id):
    return re.compile('(' + re.escape(job_id) + r'(' + '|'.join(re.escape(s) for s in RECEIPT_SUFFIXES)
                      + r')(?:-r[1-9][0-9]{0,3})?)\.([0-9a-f]{12})\.receipt\.json')


def _item(root, path, proof):
    stat = _io(path).stat()
    return dict(relative_path=_relative(root, path), source_path=_plain(path), bytes=stat.st_size, proof=proof)


def native_files(root, job_id, bindings):
    """(owned, not_attributable) for the native batch ``job_id``: what its queue rows, file identities and
    receipt rows prove, and every other file that names it but cannot be proven its own."""
    from studio_receipt_digest import binding_tag
    root = Path(root)
    folder = root / 'native-evidence'
    rows = [(binding, job) for binding, jobs in bindings for job in jobs if job.get('job_id') == job_id]
    known = {job.get('job_id') for _, jobs in bindings for job in jobs if isinstance(job.get('job_id'), str)}
    others = sorted((other for other in known if other != job_id and other.startswith(job_id + '-')), key=len, reverse=True)
    referenced = {}
    for _, job in rows:
        for field in ('native_evidence_log', 'native_evidence_archive'):
            reference = job.get(field)
            if isinstance(reference, dict) and isinstance(reference.get('path'), str):
                path = Path(reference['path']) if Path(reference['path']).is_absolute() else root / reference['path']
                relative = _relative(root, path)
                if relative is not None:
                    referenced[_key(relative)] = 'queue_row:' + field
                    if field == 'native_evidence_log':
                        referenced[_key(relative + '.uncommitted')] = 'uncommitted_tail_of:' + Path(relative).name
    tags = {binding_tag(binding): binding for binding, _ in rows}
    owned, unknown = [], []
    log_name, receipt_name = _log_name(job_id), _receipt_name(job_id)

    def theirs(name, receipt):
        """Another known job whose own name rule matches: its file, not this batch's and not unknown."""
        return any((_receipt_name(other) if receipt else _log_name(other)).fullmatch(name) for other in others)

    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not path.is_file() or not path.name.startswith(job_id + '-'):
            continue
        relative = _relative(root, path)
        proof = referenced.get(_key(relative))
        if proof is None and log_name.fullmatch(path.name):
            base = path.name[:-len('.uncommitted')] if path.name.endswith('.uncommitted') else path.name
            if _first_line_job(path) == job_id or (base != path.name and _first_line_job(folder / base) == job_id):
                proof = 'first_line_identity'
        if proof is not None:
            owned.append(_item(root, path, proof))
        elif not theirs(path.name, False):
            unknown.append(dict(_item(root, path, None), reason='names the batch but no queue row or first-line '
                                                                 'identity proves it is this batch\'s'))
    receipts = folder / 'receipt-archive'
    for path in sorted(receipts.iterdir()) if receipts.is_dir() else []:
        if not path.is_file() or not path.name.startswith(job_id + '-'):
            continue
        match = receipt_name.fullmatch(path.name)
        reason = None
        if match is None:
            reason = 'not a request ID of this batch\'s queue commands'
        elif match.group(3) not in tags:
            reason = 'its binding tag is not a session whose queue holds this batch'
        else:
            stored = _receipt_rows(root, match.group(1)).get(tags[match.group(3)])
            if stored is None:
                reason = 'no stored receipt row with this request ID in that session'
            elif stored[0] != RECEIPT_SUFFIXES[match.group(2)]:
                reason = 'its stored receipt is a %s command, not %s' % (stored[0], RECEIPT_SUFFIXES[match.group(2)])
            elif stored[1] is not None:
                reason = 'its stored receipt still embeds the queue (compact-receipts has not finished it)'
        if reason is None:
            owned.append(_item(root, path, 'receipt_row:%s@%s' % (RECEIPT_SUFFIXES[match.group(2)], match.group(3))))
        elif not theirs(path.name, True):
            unknown.append(dict(_item(root, path, None), reason=reason))
    return owned, unknown


def catchup_folders(root, catchup_id):
    """(folders, not_attributable): the catch-up's evidence folders under ``<controller state>/evidence``."""
    from studio_catchup import EVIDENCE_FOLDER_RECORD, evidence_key
    base = Path(root) / 'evidence'
    folders, unknown = [], []
    hashed = base / evidence_key(catchup_id)
    if _io(hashed).is_dir():
        try:
            record = _bounded_json(hashed / EVIDENCE_FOLDER_RECORD, 4 * 1024 * 1024)
        except (OSError, ValueError):
            record = None
        if isinstance(record, dict) and record.get('catchup_id') == catchup_id:
            folders.append((hashed, 'catchup.json'))
        else:
            unknown.append(dict(relative_path=_relative(root, hashed), source_path=str(hashed), bytes=None, proof=None,
                                reason='the folder\'s catchup.json does not name this catch-up'))
    legacy = base / catchup_id
    if _io(legacy).is_dir():
        folders.append((legacy, 'legacy_folder_name'))
    return folders, unknown


def catchup_files(root, catchup_id):
    folders, unknown = catchup_folders(root, catchup_id)
    owned = []
    for folder, proof in folders:
        physical = _io(folder)
        for path in sorted(physical.rglob('*')):
            if path.is_file():
                owned.append(_item(root, folder / path.relative_to(physical), proof))
    return owned, unknown, [_relative(root, folder) for folder, _ in folders]


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def _blocker(code, plain, **fields):
    return dict(code=code, plain=plain, **fields)


def native_state_blocker(root, job):
    """A blocker when the native batch is not finished or closed: running, pending, paused, pausing, unsettled."""
    from studio_batch_pause import load
    job_id, status = job['job_id'], job.get('status')
    state = None
    if status == 'pending':
        state = 'pending'
    elif status in ('reserved', 'starting', 'running'):
        state = 'running'
    elif status not in TERMINAL:
        state = 'unsettled'
    else:
        try:
            record = load(root, job_id)
        except (OSError, ValueError, KeyError, TypeError):
            record = dict(state='unreadable')
        pause = (record or {}).get('state')
        if pause == 'pausing':
            state = 'pausing'
        elif pause in ('paused', 'pause_failed'):
            state = 'paused'
        elif pause not in (None, 'closed', 'resumed', 'finished'):
            state = 'unsettled'
    if state is None:
        return None
    return _blocker('ARCHIVE_NOT_FINISHED', 'Batch %s is %s; only a finished or closed batch is archived (close a paused '
                    'batch with batch-pause-close first).' % (job_id, state), batch_id=job_id, batch_state=state)


def catchup_state_blocker(root, catchup_id):
    folder = Path(root) / 'catchups' / catchup_id
    try:
        state = _bounded_json(folder / 'state.json')
    except (OSError, ValueError):
        state = None
    if not isinstance(state, dict):
        status = 'unsettled'
    else:
        members = [m.get('status') for m in state.get('members') or [] if isinstance(m, dict)]
        status = state.get('status')
        if (folder / 'pause.json').is_file():
            status = 'pausing' if status in ('active', 'closing_monitor') else 'paused'
        elif status == 'prepared':
            status = 'pending'
        elif status in ('active', 'closing_monitor'):
            status = 'running'
        elif status == 'reconcile_required' or any(m == 'reconcile_required' for m in members):
            status = 'unsettled'
        elif status in ('completed', 'stopped') and any(m in RUNNER_ACTIVE_MEMBERS for m in members):
            status = 'paused'                                  # stopped with members left: catchup-resume continues it
        elif status in ('completed', 'stopped'):
            return None
        else:
            status = 'unsettled'
    return _blocker('ARCHIVE_NOT_FINISHED', 'Catch-up %s is %s; only a finished catch-up is archived.' % (catchup_id, status),
                    batch_id=catchup_id, batch_state=status)


def _citation_blocker(job_id, hits):
    selection = [hit for hit in hits if hit.get('kind') == 'selection']
    code = 'ARCHIVE_CITED_SELECTION' if selection else 'ARCHIVE_CITED_FOOS_READ'
    return _blocker(code, '%d citation(s) of batch %s by a %s this controller can see; its evidence stays where it is.'
                    % (len(hits), job_id, 'held-out lock or selection' if selection else 'FOOS read (catch-up or hold-up test)'),
                    batch_id=job_id, citations=hits[:50])


def native_citations(root, install, job_id, *, now):
    """A blocker when an export of the batch was read on FOOS or selected (studio_batch_close.foos_reads)."""
    from studio_batch_close import batch_exports, foos_reads, run_root
    try:
        run = run_root(root, install, job_id)
        hits = foos_reads(root, install, run, batch_exports(run), now=now)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        return _blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'It cannot be proven that no export of batch %s entered a FOOS '
                        'read or a selection (%s); nothing is moved.' % (job_id, str(error)[:300]), batch_id=job_id), None
    return (_citation_blocker(job_id, hits) if hits else None), run


def catchup_citations(root, install, catchup_id, folders, *, now):
    """A blocker when the catch-up's re-tests are cited: a held-out lock freezes one of its SETs or it reveals a lock
    (selection), or a later catch-up or hold-up test re-tests one of its re-test SETs (FOOS read)."""
    from studio_heldout import read_registry
    try:
        manifest = _bounded_json(Path(root) / 'catchups' / catchup_id / 'manifest.json')
        shas, retests = set(), set()
        for spec in manifest.get('members') or []:
            original = (spec or {}).get('original') or {}
            if isinstance(original.get('set_sha256'), str):
                shas.add(original['set_sha256'])
        for folder in folders:
            for path in sorted(_io(Path(root) / folder).glob('*/evidence-version.json')):
                record = _bounded_json(path, 16 * 1024 * 1024)
                sha = ((record or {}).get('retest') or {}).get('set_sha256') if isinstance(record, dict) else None
                if isinstance(sha, str):
                    retests.add(sha)
        hits = []
        if manifest.get('heldout_reveal'):
            hits.append(dict(kind='selection', via='held-out reveal', catchup_id=catchup_id))
        registry = read_registry(install, now=now)
        if registry['state'] == 'unavailable':
            raise ValueError('the held-out lock registry cannot be verified (' + str(registry['error']) + ')')
        for lock in registry['locks']:
            for cell in lock.get('candidate') or []:
                if cell.get('set_sha256') in shas | retests:
                    hits.append(dict(kind='selection', via='held-out lock freeze', lock_id=lock.get('lock_id'),
                                     set_sha256=cell['set_sha256']))
        bases = [os.path.normcase(os.path.abspath(Path(root) / folder)) for folder in folders]
        for runner, kind in (('catchups', 'catch-up'), ('holdups', 'hold-up test')):
            base = Path(root) / runner
            for path in sorted(base.glob('*/manifest.json')) if base.is_dir() else []:
                if runner == 'catchups' and path.parent.name == catchup_id:
                    continue
                value = _bounded_json(path)
                for member in (value.get('members') if isinstance(value, dict) else None) or []:
                    if not isinstance(member, dict):
                        continue
                    source = member.get('source_path') or (member.get('original') or {}).get('set_path')
                    digest = member.get('source_sha256') or (member.get('original') or {}).get('set_sha256')
                    inside = isinstance(source, str) and any(
                        os.path.normcase(os.path.abspath(_plain(source))).startswith(b + os.sep) for b in bases)
                    if digest in retests or inside:
                        hits.append(dict(kind='foos_read', via=kind, run_id=path.parent.name, set_path=source,
                                         set_sha256=digest))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError) as error:
        return _blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'It cannot be proven that catch-up %s is not cited by a held-out '
                        'lock or a later re-test (%s); nothing is moved.' % (catchup_id, str(error)[:300]),
                        batch_id=catchup_id)
    return _citation_blocker(catchup_id, hits) if hits else None


def read_keep_list(path):
    """The caller's keep-list: a JSON array of batch IDs / run folder names (or {"keep": [...]})."""
    try:
        value = _bounded_json(path, 16 * 1024 * 1024)
    except (OSError, ValueError, UnicodeError) as error:
        raise Refusal('The keep-list %s cannot be read (%s); nothing is moved.' % (path, str(error)[:200]),
                      'ARCHIVE_KEEP_LIST_INVALID', keep_list=str(path)) from None
    if isinstance(value, dict):
        value = value.get('keep')
    if (not isinstance(value, list) or len(value) > MAX_KEEP_LIST
            or not all(isinstance(item, str) and 0 < len(item) <= 1024 for item in value)):
        raise Refusal('The keep-list %s must be a JSON array of batch IDs or run folders (or {"keep": [...]}); nothing '
                      'is moved.' % path, 'ARCHIVE_KEEP_LIST_INVALID', keep_list=str(path))
    return value


def keep_blocker(keep, batch_id, run=None):
    names = {batch_id.casefold()}
    if run is not None:
        names |= {Path(run).name.casefold(), os.path.normcase(os.path.abspath(run))}
    for item in keep or []:
        if item.casefold() in names or os.path.normcase(item) in names:
            return _blocker('ARCHIVE_KEEP_LISTED', 'Batch %s is on the keep-list (%s); it stays where it is.' % (batch_id, item),
                            batch_id=batch_id, keep_entry=item)
    return None


def volume_of(path):
    """Volume identity of an existing path (its st_dev: the volume serial number on Windows)."""
    return os.stat(_io(path)).st_dev


def _probe_writable(target):
    """Create, fsync and remove one probe file in the archive root; OSError when it cannot be written."""
    probe = _io(target / ('.goat-archive-probe-' + uuid.uuid4().hex))
    try:
        with probe.open('xb') as output:
            output.write(b'probe'); output.flush(); os.fsync(output.fileno())
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _unlink(path):
    """Remove one verified source (the only removal of evidence this module makes)."""
    _io(path).unlink()


def required_bytes(size):
    return size + max(MARGIN_BYTES, int(size * MARGIN_FRACTION))


def root_blockers(root, archive_root, size):
    """Archive-root checks: absolute, present, another volume than the controller state, writable, enough space."""
    text = str(archive_root or '')
    if not text or not Path(text).is_absolute():
        return [_blocker('ARCHIVE_ROOT_INVALID', 'The archive root must be an absolute folder path.', archive_root=text)], None
    target = Path(os.path.abspath(text))
    if not _io(target).is_dir():
        return [_blocker('ARCHIVE_ROOT_UNAVAILABLE', 'The archive root %s is not an existing folder; connect the drive or '
                         'create the folder first.' % target, archive_root=str(target))], None
    try:
        same = volume_of(target) == volume_of(root)
    except OSError as error:
        return [_blocker('ARCHIVE_ROOT_UNAVAILABLE', 'The archive root cannot be inspected (%s).' % str(error)[:200],
                         archive_root=str(target))], None
    if same:
        return [_blocker('ARCHIVE_ROOT_SAME_VOLUME', 'The archive root %s is on the same volume as the controller state; '
                         'moving there frees nothing.' % target, archive_root=str(target))], None
    try:
        _probe_writable(target)
    except OSError as error:
        return [_blocker('ARCHIVE_ROOT_NOT_WRITABLE', 'The archive root %s is not writable (%s).' % (target, str(error)[:200]),
                         archive_root=str(target))], None
    free = shutil.disk_usage(_io(target)).free
    if free < required_bytes(size):
        return [_blocker('ARCHIVE_ROOT_LOW_SPACE', 'The archive root has %d bytes free; this move needs %d (its %d bytes plus '
                         'a margin).' % (free, required_bytes(size), size), archive_root=str(target), free_bytes=free,
                         required_bytes=required_bytes(size))], free
    return [], free


# ---------------------------------------------------------------------------
# Preview and apply
# ---------------------------------------------------------------------------

def _human(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return ('%d %s' % (size, unit)) if unit == 'B' else ('%.2f %s' % (size, unit))
        size /= 1024.0


def plan(root, install, batch_id, archive_root, *, kind, job=None, bindings=(), keep=None, now, busy=None):
    """Read-only plan: what would move, what stays as not attributable, and every blocker. Writes nothing (the
    writability probe creates and removes one file in the archive root)."""
    pointer = load_pointer(root, batch_id)
    blockers = []
    if busy:
        blockers.append(_blocker('ARCHIVE_TERMINAL_BUSY', 'This terminal is not idle: ' + busy + '. Archive once it is idle.',
                                 batch_id=batch_id))
    run, folders = None, []
    if kind == 'native':
        owned, unknown = native_files(root, batch_id, bindings)
        state = native_state_blocker(root, job)
        if state:
            blockers.append(state)
        if job.get('native_evidence_history'):
            blockers.append(_blocker('ARCHIVE_COMPACT_FIRST', 'Batch %s still keeps native evidence history in its queue row; '
                                     'run compact-evidence --apply first so it is archived too.' % batch_id, batch_id=batch_id))
        if pointer is None and owned:
            citation, run = native_citations(root, install, batch_id, now=now)
            if citation:
                blockers.append(citation)
    else:
        owned, unknown, folders = catchup_files(root, batch_id)
        state = catchup_state_blocker(root, batch_id)
        if state:
            blockers.append(state)
        if pointer is None and owned:
            citation = catchup_citations(root, install, batch_id, folders, now=now)
            if citation:
                blockers.append(citation)
    if pointer is None:
        keep_hit = keep_blocker(keep, batch_id, run)
        if keep_hit:
            blockers.append(keep_hit)
    size = sum(item['bytes'] for item in owned)
    target = archive_dir(root, archive_root, batch_id) if str(archive_root or '') and Path(str(archive_root)).is_absolute() else None
    if pointer is not None:
        if target is None or os.path.normcase(str(target)) != os.path.normcase(pointer['archive_dir']):
            blockers.append(_blocker('ARCHIVE_ALREADY_ARCHIVED', 'Batch %s is already archived to %s; re-run with that '
                                     'archive root to verify or complete it.' % (batch_id, pointer['archive_dir']),
                                     batch_id=batch_id, archive_dir=pointer['archive_dir']))
        free = None
    else:
        if not owned:
            blockers.append(_blocker('ARCHIVE_NOTHING_TO_MOVE', 'No evidence file can be proven to belong to %s; nothing '
                                     'moves.' % batch_id, batch_id=batch_id))
        missing = [item['bytes'] for item in owned
                   if target is None or not _io(target / item['relative_path']).is_file()]
        found, free = root_blockers(root, archive_root, sum(missing))
        blockers.extend(found)
    files = sorted(owned, key=lambda item: item['relative_path'])
    return dict(batch_id=batch_id, kind=kind, installation=installation_id(root), archive_dir=str(target) if target else None,
                archived=pointer is not None, pointer=str(pointer_path(root, batch_id)) if pointer is not None else None,
                files=files, file_count=len(files), bytes=size, size=_human(size), folders=folders,
                not_attributable=sorted(unknown, key=lambda item: item['relative_path'] or ''),
                required_free_bytes=required_bytes(size), archive_free_bytes=free,
                blockers=blockers, ready=not blockers, run_root=str(run) if run else None)


def public(value, applied=False):
    """The preview/result for a reply: at most MAX_PUBLIC_FILES file rows (counts and bytes stay whole)."""
    result = dict(value, applied=applied)
    for key in ('files', 'not_attributable'):
        rows = result.get(key) or []
        result[key] = rows[:MAX_PUBLIC_FILES]
        result[key + '_omitted'] = max(0, len(rows) - MAX_PUBLIC_FILES)
    return result


def _remove_temporaries(folder):
    physical = _io(folder)
    for path in physical.rglob('*' + TEMP_MARK) if physical.is_dir() else []:
        try:
            path.unlink()                    # this tool's own unfinished copy, never evidence
        except OSError:
            pass


def _readback(path):
    return file_sha256(path)


def copy_verified(source, target):
    """Copy ``source`` to ``target`` (temporary file, fsync, atomic rename) and verify the copy against the source
    bytes by SHA-256. An existing identical target is reused; a different one refuses. Returns (sha256, bytes, reused)."""
    source_io, target_io = _io(source), _io(target)
    if target_io.is_file():
        digest = file_sha256(source)
        if _readback(target) != digest:
            raise Refusal('A different file already exists at %s; nothing was removed. Inspect the archive.' % target,
                          'ARCHIVE_TARGET_CONFLICT', target=str(target))
        return digest, target_io.stat().st_size, True
    target_io.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_io.with_name(target_io.name + '.' + uuid.uuid4().hex[:8] + TEMP_MARK)
    digest, size = hashlib.sha256(), 0
    try:
        with source_io.open('rb') as reader, temporary.open('xb') as writer:
            for chunk in iter(lambda: reader.read(CHUNK), b''):
                writer.write(chunk); digest.update(chunk); size += len(chunk)
            writer.flush(); os.fsync(writer.fileno())
        expected = digest.hexdigest()
        if _readback(temporary) != expected:
            raise Refusal('The archive copy of %s did not verify (sha256 differs); the source is kept.' % source,
                          'ARCHIVE_VERIFY_FAILED', source=_plain(source))
        os.replace(temporary, target_io)
    finally:
        if temporary.exists():
            temporary.unlink()
    if _readback(target) != expected:
        raise Refusal('The archive copy of %s did not verify after its rename (sha256 differs); the source is kept.' % source,
                      'ARCHIVE_VERIFY_FAILED', source=_plain(source))
    return expected, size, False


def _write_json_file(path, value):
    from studio_bridge import write_json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)


def _same_files(left, right):
    return sorted((f['relative_path'], f['bytes'], f['sha256']) for f in left) == \
        sorted((f['relative_path'], f['bytes'], f['sha256']) for f in right)


def _remove_sources(root, pointer, manifest):
    """Remove each source whose bytes hash to the manifest and whose archive copy is in place; returns (removed, gone)."""
    folder = Path(pointer['archive_dir'])
    removed, gone = [], 0
    for entry in manifest['files']:
        source = Path(root) / entry['relative_path']
        if not _io(source).is_file():
            gone += 1
            continue
        copy = _io(folder / entry['relative_path'])
        if not copy.is_file() or copy.stat().st_size != entry['bytes']:
            raise Refusal('The archive copy of %s is missing or has another size; the source is kept.' % entry['relative_path'],
                          'ARCHIVE_VERIFY_FAILED', relative_path=entry['relative_path'])
        if file_sha256(source) != entry['sha256']:
            raise Refusal('The source %s changed since it was archived (sha256 differs); it is kept. Inspect it.'
                          % entry['relative_path'], 'ARCHIVE_SOURCE_CHANGED', relative_path=entry['relative_path'])
        _unlink(source)
        removed.append(entry['relative_path'])
    for relative in sorted(pointer.get('folders') or [], key=len, reverse=True):
        physical = _io(Path(root) / relative)
        for path in sorted((p for p in physical.rglob('*') if p.is_dir()), key=lambda p: len(str(p)), reverse=True) \
                if physical.is_dir() else []:
            try:
                path.rmdir()                     # only empty folders the moved files left
            except OSError:
                pass
        try:
            physical.rmdir()
        except OSError:
            pass
    return removed, gone


def _verify_archive(pointer, manifest):
    folder = Path(pointer['archive_dir'])
    for entry in manifest['files']:
        copy = folder / entry['relative_path']
        if not _io(copy).is_file() or file_sha256(copy) != entry['sha256']:
            raise Refusal('The archive copy %s is missing or differs from its manifest; every source that is still '
                          'present is kept. Inspect the archive.' % copy, 'ARCHIVE_VERIFY_FAILED',
                          relative_path=entry['relative_path'])


def _complete(root, pointer):
    """Re-run with a pointer: verify the archive against its manifest and finish the removals an interruption left."""
    folder = _reachable(pointer)
    manifest = _bounded_json(folder / MANIFEST)
    _verify_archive(pointer, manifest)
    removed, gone = _remove_sources(root, pointer, manifest)
    return dict(changed=bool(removed), copied=0, reused=len(manifest['files']), removed=len(removed),
                already_removed=gone, verified=len(manifest['files']), manifest=str(folder / MANIFEST),
                manifest_sha256=pointer['manifest_sha256'], pointer=str(pointer_path(root, pointer['batch_id'])),
                bytes=manifest.get('bytes'), file_count=len(manifest['files']))


def apply(root, install, preview, archive_root, *, now, archived_by='demo_agent'):
    """Move the previewed files. The caller re-built ``preview`` under the terminal lock and found no blocker."""
    batch_id = preview['batch_id']
    pointer = load_pointer(root, batch_id)
    if pointer is not None:
        return _complete(root, pointer)
    folder = archive_dir(root, archive_root, batch_id)
    _io(folder).mkdir(parents=True, exist_ok=True)
    _remove_temporaries(folder)
    entries, copied, reused = [], 0, 0
    for item in preview['files']:
        digest, size, again = copy_verified(Path(root) / item['relative_path'], folder / item['relative_path'])
        if size != item['bytes']:
            raise Refusal('The source %s changed size while it was archived; nothing was removed.' % item['relative_path'],
                          'ARCHIVE_SOURCE_CHANGED', relative_path=item['relative_path'])
        reused += again; copied += not again
        entries.append(dict(relative_path=item['relative_path'], bytes=size, sha256=digest, source_path=item['source_path'],
                            proof=item['proof']))
    manifest_path = folder / MANIFEST
    if _io(manifest_path).is_file():
        existing = _bounded_json(manifest_path)
        if not isinstance(existing, dict) or existing.get('batch_id') != batch_id or not _same_files(existing.get('files') or [], entries):
            raise Refusal('A different manifest already exists at %s; nothing was removed. Inspect the archive.' % manifest_path,
                          'ARCHIVE_MANIFEST_CONFLICT', manifest=str(manifest_path))
    else:
        total = sum(entry['bytes'] for entry in entries)
        _write_json_file(manifest_path, dict(
            schema=SCHEMA, schema_version=SCHEMA_VERSION, batch_id=batch_id, kind=preview['kind'],
            installation=installation_id(root), controller_state_root=str(Path(root)), archive_root=str(Path(os.path.abspath(archive_root))),
            archive_dir=str(folder), created_at=_utc(now), created_utc=now, archived_by=archived_by,
            controller_revision=controller_revision(install), files=entries, file_count=len(entries), bytes=total,
            folders=preview.get('folders') or [], not_attributable=preview.get('not_attributable') or [],
            plain='Evidence of %s moved off the controller volume; each file sha256-verified before its source was removed.'
                  % batch_id))
    manifest = _bounded_json(manifest_path)
    digest = file_sha256(manifest_path)
    pointer = dict(schema=POINTER_SCHEMA, schema_version=SCHEMA_VERSION, batch_id=batch_id, kind=preview['kind'],
                   installation=installation_id(root), archive_root=str(Path(os.path.abspath(archive_root))),
                   archive_dir=str(folder), manifest=str(manifest_path), manifest_sha256=digest,
                   files=[entry['relative_path'] for entry in manifest['files']], folders=manifest.get('folders') or [],
                   file_count=len(manifest['files']), bytes=manifest.get('bytes'), archived_at=_utc(now),
                   archived_by=archived_by, controller_revision=controller_revision(install),
                   plain='This batch\'s evidence lives in ' + str(folder) + '; controller readers follow this pointer.')
    _write_json_file(pointer_path(root, batch_id), pointer)
    removed, gone = _remove_sources(root, pointer, manifest)
    return dict(changed=True, copied=copied, reused=reused, removed=len(removed), already_removed=gone,
                verified=len(entries), manifest=str(manifest_path), manifest_sha256=digest,
                pointer=str(pointer_path(root, batch_id)), bytes=manifest.get('bytes'), file_count=len(entries))
