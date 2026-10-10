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

How it moves: two separate invocations, so the only copy is never deleted in the run that made the archive.

``apply`` (``evidence-archive --apply``), resumable and idempotent; it removes nothing:

1. Each file is copied to ``<archive root>/<installation>/<batch id>/<path below the controller state>``
   (temporary file, fsync, atomic rename, fsync again; the folder is fsynced where the platform allows), and its
   copy is read back and SHA-256 verified against the bytes read from the source. A copy already there with the
   same SHA-256 is reused (an interrupted run); a different one refuses.
2. ``manifest.json`` beside them lists every file (relative path, bytes, sha256, source path, ownership proof),
   the batch, the time and the controller revision. A manifest left by an interrupted run (also one interrupted
   between the manifest and the pointer) is reused only when it lists exactly the same files.
3. The pointer ``native-evidence/archived/<batch id>.json`` records the archive folder, the manifest SHA-256 and
   (optional, schema still v1) the archive volume's GUID and the folder's path on that volume. Readers follow it
   from now on; the sources stay in place as the safety copy. A re-run with a pointer re-verifies the archive.

``complete`` (``evidence-archive --complete``) re-reads and re-verifies EVERY archived file from disk (size and
SHA-256 against the manifest, no cache) and validates every manifest entry (relative, no ``..``, below
``native-evidence/`` or ``evidence/``, named by the pointer) before it removes any source; then it removes only a
source that still hashes to the manifest. A missing or corrupt archive copy, or a changed source, refuses with
nothing removed.

``restore`` (``evidence-restore``) copies a verified archive back into the controller state and retires the
pointer to ``native-evidence/archived/retired/`` (an audit record), so readers read the local copy again.
``repoint`` (``evidence-repoint``) accepts a new archive location only when its manifest hashes to the pointer's
and every file verifies, and rewrites the pointer atomically (the old pointer is kept as a retired record).

Durability: the archive root must be a local NTFS or ReFS volume (``ARCHIVE_ROOT_FILESYSTEM`` refuses exFAT/FAT32
USB sticks, ``ARCHIVE_ROOT_REMOTE`` network drives, through studio_build_migration's GetDriveTypeW check), and the
source walk refuses symbolic links and junctions (``ARCHIVE_SOURCE_LINK``).

Readers (``resolve``/``locate``, ``archived_evidence_roots``, ``archived_records``): every controller reader that
resolves this evidence follows the pointer (studio_trial_journal._history for trial-journal, trial-count, finish
and batch-pause-close; studio_catchup.evidence_roots/evidence_folder/versions for evidence-scan,
evidence-versions, catchup-prepare and catchup-report; equivalence-canary-ingest). With a pointer the archive is
the truth: each archived file's size is checked against the manifest on every read and its SHA-256 on its first
read in a process (cached per path, size and mtime), the pointer's files must be listed by the manifest, and an
unreadable or malformed pointer, an unreachable archive root (unplugged drive, also not found by its volume GUID
under another letter), a manifest that no longer matches its pointer, or an archived file that is missing,
corrupt or unreadable refuses ``EVIDENCE_ARCHIVE_UNREACHABLE``, never a silent fallback. studio_evidence_log.append
refuses to write to an archived batch.

Refusals (stable codes, nothing written): the batch is not finished or closed, a seed slot or any batch is
active, an ACTIVE held-out lock (locked, revealable, revealing) holds its SETs, a run that is not finished (seed
hunt, catch-up, hold-up test) reads it as its source, it is on the caller's ``--keep-list`` (required for
``--apply``; it may be ``[]``), the archive root is on the controller's volume, missing, remote, not NTFS/ReFS,
not writable or short of space (the preview size plus a margin), or ``--confirm`` is missing. A finished FOOS read
or a revealed lock does not block (Claude-Mac on GOAT-EA#205): the pointer keeps the evidence readable, and the
preview lists it under ``cited_by``. A manifest or lock registry that cannot be read refuses
(``ARCHIVE_CITATIONS_UNVERIFIABLE``). Prereg and book citations live outside the controller (goatai prereg files,
the book on G:): the keep-list is the caller's way to name them. The Exp 02 refusal belongs to the desktop gate,
as with batch-pause-close.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat as stat_mode
import uuid

from studio_refusal import Refusal

SCHEMA = 'goat-evidence-archive-manifest-v1'
POINTER_SCHEMA = 'goat-evidence-archive-pointer-v1'
SCHEMA_VERSION = 1
POINTERS = ('native-evidence', 'archived')
RETIRED = 'retired'                    # native-evidence/archived/retired/: pointers retired by restore or repoint
MANIFEST = 'manifest.json'
EVIDENCE_PREFIXES = ('native-evidence/', 'evidence/')
DURABLE_FILESYSTEMS = ('NTFS', 'REFS')
SHA256 = re.compile(r'[0-9a-f]{64}')
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
    'ARCHIVE_NOT_FINISHED', 'ARCHIVE_COMPACT_FIRST', 'ARCHIVE_TERMINAL_BUSY', 'ARCHIVE_HELDOUT_LOCK_ACTIVE',
    'ARCHIVE_IN_FLIGHT_READER', 'ARCHIVE_CITATIONS_UNVERIFIABLE', 'ARCHIVE_KEEP_LIST_REQUIRED', 'ARCHIVE_KEEP_LISTED',
    'ARCHIVE_KEEP_LIST_INVALID',
    'ARCHIVE_ROOT_INVALID', 'ARCHIVE_ROOT_UNAVAILABLE', 'ARCHIVE_ROOT_SAME_VOLUME', 'ARCHIVE_ROOT_NOT_WRITABLE',
    'ARCHIVE_ROOT_LOW_SPACE', 'ARCHIVE_ALREADY_ARCHIVED', 'ARCHIVE_TARGET_CONFLICT', 'ARCHIVE_MANIFEST_CONFLICT',
    'ARCHIVE_VERIFY_FAILED', 'ARCHIVE_SOURCE_CHANGED', 'ARCHIVE_NOTHING_TO_MOVE',
    'EVIDENCE_ARCHIVE_UNREACHABLE', 'EVIDENCE_ARCHIVED',
    # Claude-Mac on GOAT-EA#205: durability, separate removal, restore and repoint.
    'ARCHIVE_ROOT_FILESYSTEM', 'ARCHIVE_ROOT_REMOTE', 'ARCHIVE_SOURCE_LINK', 'ARCHIVE_MANIFEST_INVALID',
    'ARCHIVE_NOT_ARCHIVED', 'ARCHIVE_RESTORE_CONFLICT', 'ARCHIVE_REPOINT_MISMATCH', 'ARCHIVE_MODE_CONFLICT'))


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


def _bad_relative(relative):
    """Why a manifest or pointer path is not a plain relative path below native-evidence/ or evidence/, else None."""
    if not isinstance(relative, str) or not relative or len(relative) > 1024:
        return 'is not a path'
    if '\\' in relative or relative.startswith('/') or ':' in relative or '\x00' in relative:
        return 'is not a relative forward-slash path'
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return 'has an empty, . or .. part'
    if len(parts) < 2 or not relative.casefold().startswith(EVIDENCE_PREFIXES):
        return 'is not below native-evidence/ or evidence/'
    return None


def _pointer_problem(value, batch_id):
    if not isinstance(value, dict) or value.get('schema') != POINTER_SCHEMA:
        return 'is not a ' + POINTER_SCHEMA + ' record'
    if value.get('batch_id') != batch_id:
        return 'names batch %r' % (value.get('batch_id'),)
    if not isinstance(value.get('archive_dir'), str) or not Path(value['archive_dir']).is_absolute():
        return 'has no absolute archive_dir'
    if not isinstance(value.get('manifest_sha256'), str) or not SHA256.fullmatch(value['manifest_sha256']):
        return 'has no manifest_sha256'
    if not isinstance(value.get('files'), list) or not isinstance(value.get('folders') or [], list):
        return 'has no files list'
    for item in value['files'] + (value.get('folders') or []):
        problem = _bad_relative(item)
        if problem:
            return 'names %r, which %s' % (item, problem)
    for field in ('volume_guid', 'archive_relative'):
        if value.get(field) is not None and (not isinstance(value[field], str) or not value[field]):
            return 'has an invalid ' + field
    relative = value.get('archive_relative')
    if relative is not None and (Path(relative).is_absolute() or '..' in relative.replace('\\', '/').split('/')):
        return 'has an archive_relative that is not a plain relative path'
    return None


def load_pointer(root, batch_id):
    """The batch's pointer, None when it has none. An unreadable or malformed pointer refuses
    (ArchiveUnreachable): its evidence is somewhere else, so nothing is read in its place."""
    path = pointer_path(root, batch_id)
    if not _io(path).is_file():
        return None
    try:
        value = _bounded_json(path)
    except (OSError, ValueError) as error:
        raise ArchiveUnreachable('The evidence-archive pointer %s cannot be read (%s); batch %s\'s evidence is read from '
                                 'nowhere until the pointer is repaired. Inspect it.' % (path, str(error)[:200], batch_id),
                                 batch_id=batch_id, pointer=str(path)) from None
    problem = _pointer_problem(value, batch_id)
    if problem:
        raise ArchiveUnreachable('The evidence-archive pointer %s %s; batch %s\'s evidence is read from nowhere until the '
                                 'pointer is repaired. Inspect it.' % (path, problem, batch_id), batch_id=batch_id,
                                 pointer=str(path))
    return value


_INDEX = {}
_OPENED = {}       # normcase manifest path -> ((size, mtime_ns, file ID, manifest sha256, pointer signature), entries)
_VERIFIED = set()  # (normcase archived path, size, mtime_ns, file ID, sha256): hashed once per process


def _index(root):
    """[(pointer, file keys, folder keys, signature)] of every pointer, re-read only when a pointer file changes (a
    catch-up's versions() resolves several paths per member). A pointer that cannot be read refuses."""
    folder = Path(root).joinpath(*POINTERS)
    try:
        paths = sorted(p for p in folder.glob('*.json') if JOB_ID.fullmatch(p.stem)) if folder.is_dir() else []
        stamp = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in paths)
    except OSError as error:
        raise ArchiveUnreachable('The evidence-archive pointers in %s cannot be listed (%s); nothing is read.'
                                 % (folder, str(error)[:200]), pointer=str(folder)) from None
    cached = _INDEX.get(os.path.normcase(os.path.abspath(folder)))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    index = []
    for path in paths:
        pointer = load_pointer(root, path.stem)
        if pointer is None:
            continue
        signature = hashlib.sha256(json.dumps(pointer, sort_keys=True).encode('utf-8')).hexdigest()
        index.append((pointer, {_key(item) for item in pointer['files']},
                      [_key(item) for item in pointer.get('folders') or []], signature))
    _INDEX[os.path.normcase(os.path.abspath(folder))] = (stamp, index)
    return index


# ---- volume facts (Windows; each injectable for tests) ---------------------------------------------------------

def _kernel32():
    import ctypes
    return ctypes, ctypes.WinDLL('kernel32', use_last_error=True)


def volume_root_of(path):
    """The root of the volume that holds ``path`` (``G:\\`` or a mount folder; GetVolumePathNameW), else its drive."""
    text = os.path.abspath(_plain(path))
    if os.name == 'nt':
        try:
            ctypes, kernel32 = _kernel32()
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.GetVolumePathNameW(ctypes.c_wchar_p(text), buffer, len(buffer)):
                return buffer.value
        except (AttributeError, OSError, ImportError):
            pass
    drive = os.path.splitdrive(text)[0]
    return drive + os.sep if drive else os.sep


def filesystem_of(volume_root):
    """The volume's file system name (GetVolumeInformationW: NTFS, ReFS, exFAT, FAT32); None off Windows, where it
    is not checked. Raises OSError when Windows cannot say."""
    if os.name != 'nt':
        return None
    ctypes, kernel32 = _kernel32()
    name = ctypes.create_unicode_buffer(261)
    if not kernel32.GetVolumeInformationW(ctypes.c_wchar_p(volume_root), None, 0, None, None, None, name, len(name)):
        raise OSError(ctypes.get_last_error(), 'GetVolumeInformationW failed for ' + str(volume_root))
    return name.value


def volume_guid_of(volume_root):
    """``\\\\?\\Volume{GUID}\\`` of a local volume root (GetVolumeNameForVolumeMountPointW), None when it has none."""
    if os.name != 'nt':
        return None
    try:
        ctypes, kernel32 = _kernel32()
        buffer = ctypes.create_unicode_buffer(64)
        root = volume_root if str(volume_root).endswith('\\') else str(volume_root) + '\\'
        if kernel32.GetVolumeNameForVolumeMountPointW(ctypes.c_wchar_p(root), buffer, len(buffer)):
            return buffer.value
    except (AttributeError, OSError, ImportError):
        pass
    return None


def volume_mounts(guid):
    """Where a volume is mounted now (GetVolumePathNamesForVolumeNameW: ``F:\\`` and mount folders), [] if nowhere."""
    if os.name != 'nt' or not guid:
        return []
    try:
        ctypes, kernel32 = _kernel32()
        buffer, length = ctypes.create_unicode_buffer(4096), ctypes.c_ulong(0)
        if not kernel32.GetVolumePathNamesForVolumeNameW(ctypes.c_wchar_p(guid), buffer, len(buffer), ctypes.byref(length)):
            return []
        return [item for item in buffer[:length.value].split('\x00') if item]
    except (AttributeError, OSError, ImportError):
        return []


def _volume_fields(folder):
    """The optional pointer fields that find an archive whose drive letter changed: its volume GUID and its path on
    that volume. {} where the volume has no GUID (or off Windows)."""
    try:
        volume = volume_root_of(folder)
        guid = volume_guid_of(volume)
    except OSError:
        return {}
    relative = _relative(volume, folder) if guid else None
    return dict(volume_guid=guid, archive_relative=relative) if guid and relative else {}


# ---- opening and verifying an archive ----------------------------------------------------------------------------

def _candidates(pointer):
    """The pointer's archive_dir, then the same path on the volume its GUID names, wherever it is mounted now."""
    first = Path(pointer['archive_dir'])
    yield first
    guid, relative = pointer.get('volume_guid'), pointer.get('archive_relative')
    if not guid or not relative:
        return
    try:
        mounts = list(volume_mounts(guid) or [])
    except OSError:
        mounts = []
    seen = {os.path.normcase(str(first))}
    for mount in mounts + [guid]:
        candidate = Path(mount) / relative
        if os.path.normcase(str(candidate)) not in seen:
            seen.add(os.path.normcase(str(candidate)))
            yield candidate


def manifest_problem(pointer, value):
    """Why a manifest cannot be trusted for its pointer, else None: schema and batch, every entry relative (no
    ``..``), below native-evidence/ or evidence/, named by the pointer (its files or under its folders), with bytes
    and sha256; and every file and folder the pointer names is listed by the manifest."""
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        return 'it is not a ' + SCHEMA + ' record'
    if value.get('batch_id') != pointer['batch_id']:
        return 'it names batch %r' % (value.get('batch_id'),)
    files, folders = value.get('files'), value.get('folders') or []
    if not isinstance(files, list) or not isinstance(folders, list):
        return 'it has no files list'
    named = {_key(item) for item in pointer['files']}
    named_folders = [_key(item) for item in pointer.get('folders') or []]
    keys = set()
    for entry in files:
        relative = entry.get('relative_path') if isinstance(entry, dict) else None
        problem = _bad_relative(relative)
        if problem:
            return 'its entry %r %s' % (relative, problem)
        if type(entry.get('bytes')) is not int or entry['bytes'] < 0 or not isinstance(entry.get('sha256'), str) \
                or not SHA256.fullmatch(entry['sha256']):
            return 'its entry %s has no bytes or sha256' % relative
        key = _key(relative)
        if key in keys:
            return 'it lists %s twice' % relative
        if key not in named and not any(key.startswith(folder + '/') for folder in named_folders):
            return 'it lists %s, which its pointer does not name' % relative
        keys.add(key)
    missing = sorted(item for item in pointer['files'] if _key(item) not in keys)
    if missing:
        return 'its pointer names %s, which the manifest does not list' % missing[0]
    listed = {_key(item) for item in folders if isinstance(item, str)}
    stray = sorted(item for item in pointer.get('folders') or [] if _key(item) not in listed)
    if stray:
        return 'its pointer names folder %s, which the manifest does not list' % stray[0]
    return None


def _entries(pointer, folder, manifest, stat, signature, strict):
    cache_key = os.path.normcase(str(manifest))
    stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ino, pointer['manifest_sha256'], signature)
    cached = _OPENED.get(cache_key)
    if not strict and signature is not None and cached is not None and cached[0] == stamp:
        return cached[1]
    batch_id = pointer['batch_id']

    def fail(why):
        return ArchiveUnreachable('The evidence archive of batch %s at %s %s; nothing is read from it. Inspect the archive.'
                                  % (batch_id, folder, why), batch_id=batch_id, archive_dir=str(folder))
    try:
        if stat.st_size > MAX_RECORD_BYTES:
            raise ValueError('it exceeds %d bytes' % MAX_RECORD_BYTES)
        raw = _io(manifest).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != pointer['manifest_sha256']:
            raise fail('no longer matches its pointer (manifest sha256 differs)')
        value = json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    except ArchiveUnreachable:
        raise
    except (OSError, ValueError) as error:
        raise fail('has a manifest that cannot be read (%s)' % str(error)[:200]) from None
    problem = manifest_problem(pointer, value)
    if problem:
        if strict:
            raise Refusal('The manifest of batch %s at %s cannot be trusted: %s. Nothing was changed. Inspect the archive.'
                          % (batch_id, folder, problem), 'ARCHIVE_MANIFEST_INVALID', batch_id=batch_id,
                          archive_dir=str(folder))
        raise fail('has a manifest that cannot be trusted (%s)' % problem)
    entries = {_key(entry['relative_path']): entry for entry in value['files']}
    if not strict:
        _OPENED[cache_key] = (stamp, entries)
    return entries


def _open(pointer, signature=None, *, strict=False):
    """(archive folder, {key: manifest entry}) of a pointer: its archive_dir, or the same path on its volume found by
    GUID under another drive letter. Raises ArchiveUnreachable; ``strict`` (complete, restore) never uses the cache
    and refuses an untrustworthy manifest with ARCHIVE_MANIFEST_INVALID."""
    errors = []
    for folder in _candidates(pointer):
        manifest = folder / MANIFEST
        try:
            stat = _io(manifest).stat()
        except OSError as error:
            errors.append(str(error)[:200])
            continue
        return folder, _entries(pointer, folder, manifest, stat, signature, strict)
    raise ArchiveUnreachable('Batch %s evidence was archived to %s, which cannot be read now (%s)%s. Reconnect the '
                             'archive drive (or evidence-repoint to a verified copy), then retry; nothing is read in its '
                             'place.' % (pointer['batch_id'], pointer['archive_dir'], errors[0] if errors else 'not found',
                                         '; its volume was not found under another drive letter either'
                                         if pointer.get('volume_guid') else ''),
                             batch_id=pointer['batch_id'], archive_dir=pointer['archive_dir'])


def _verify_entry(pointer, folder, entry, *, full, cache=True):
    """The archived copy of one manifest entry, after checking its size (always) and its sha256 (``full``: once per
    process per path, size and mtime unless ``cache`` is off). Raises ArchiveUnreachable."""
    target = folder / entry['relative_path']
    physical = _io(target)

    def fail(why):
        return ArchiveUnreachable('The archived copy %s of batch %s %s; nothing is read in its place. Inspect the archive '
                                  '(evidence-repoint to a verified copy, or evidence-restore).' % (target, pointer['batch_id'], why),
                                  batch_id=pointer['batch_id'], archive_dir=str(folder), relative_path=entry['relative_path'])
    try:
        stat = physical.stat()
    except OSError as error:
        raise fail('cannot be read (%s)' % str(error)[:200]) from None
    if not stat_mode.S_ISREG(stat.st_mode):
        raise fail('is not a file')
    if stat.st_size != entry['bytes']:
        raise fail('has %d bytes; its manifest lists %d' % (stat.st_size, entry['bytes']))
    if full:
        key = (os.path.normcase(str(physical)), stat.st_size, stat.st_mtime_ns, stat.st_ino, entry['sha256'])
        if not cache or key not in _VERIFIED:
            try:
                digest = file_sha256(target)
            except OSError as error:
                raise fail('cannot be read (%s)' % str(error)[:200]) from None
            if digest != entry['sha256']:
                raise fail('differs from its manifest (sha256)')
            _VERIFIED.add(key)
    return target


def archived_location(root, path, verify='full'):
    """Where ``path`` (a file or folder below the controller state) lives now when a pointer moved it, else None.

    A file the manifest lists is verified first: ``verify='full'`` (a read) checks its size and, once per process,
    its sha256; ``'size'`` (mapping a path a later reader opens) its size; None nothing. Raises ArchiveUnreachable
    when the pointer, the archive or the file cannot be trusted now.
    """
    relative = _relative(root, path)
    if relative is None:
        return None
    key = _key(relative)
    if not key.startswith(EVIDENCE_PREFIXES):
        return None
    for pointer, files, folders, signature in _index(root):
        if key in files or any(key == folder or key.startswith(folder + '/') for folder in folders):
            folder, entries = _open(pointer, signature)
            entry = entries.get(key)
            if entry is not None and verify:
                return _verify_entry(pointer, folder, entry, full=verify == 'full')
            return folder / Path(relative)
    return None


def locate(root, path, verify='full'):
    """(where to read ``path``, moved): its archived location (verified) when a pointer moved it, else itself."""
    moved = archived_location(root, path, verify)
    return (Path(path), False) if moved is None else (moved, True)


def resolve(root, path):
    """``path`` itself, or its archived location (verified) when an evidence-archive pointer moved it."""
    return locate(root, path)[0]


def read_failure(path, error):
    """The refusal for a read that failed on an archived path: never "unavailable", never a fallback."""
    return ArchiveUnreachable('The archived copy %s cannot be read (%s); nothing is read in its place. Inspect the archive.'
                              % (_plain(path), str(error)[:200]), path=_plain(path))


def _evidence_pointers(root):
    return [(pointer, signature) for pointer, _, folders, signature in _index(root)
            if any(folder.startswith('evidence/') for folder in folders)]


def archived_evidence_roots(root):
    """Catch-up evidence bases that moved to an archive (``<archive>/<installation>/<id>/evidence``), each verified
    reachable (ArchiveUnreachable otherwise), so studio_catchup reads them like ``<controller state>/evidence``."""
    return [_open(pointer, signature)[0] / 'evidence' for pointer, signature in _evidence_pointers(root)]


def archived_records(root, base, name):
    """The verified archive copies (IO paths) of every ``evidence/<folder>/<member>/<name>`` the manifest of the
    archived evidence base ``base`` lists: a reader enumerates them from the manifest, so a missing copy refuses
    instead of reading as absent. [] when ``base`` is not an archived evidence base."""
    wanted = os.path.normcase(os.path.abspath(_plain(base)))
    for pointer, signature in _evidence_pointers(root):
        folder, entries = _open(pointer, signature)
        if os.path.normcase(os.path.abspath(_plain(folder / 'evidence'))) != wanted:
            continue
        paths = []
        for key in sorted(entries):
            parts = key.split('/')
            if len(parts) == 4 and parts[0] == 'evidence' and parts[3] == name.casefold():
                paths.append(_io(_verify_entry(pointer, folder, entries[key], full=True)))
        return paths
    return []


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


def _is_link(path):
    """A symbolic link or a junction (the reparse points studio_handover.safe_path refuses)."""
    path = Path(path)
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def link_below(root, path):
    """The first symbolic link or junction at ``path`` or between it and the controller state, else None.

    The same rule as studio_handover.safe_path, applied only below the controller state (the state root itself may
    legitimately sit below a redirected profile folder)."""
    base = os.path.normcase(os.path.abspath(_plain(root)))
    current = Path(os.path.abspath(_plain(path)))
    while os.path.normcase(str(current)) != base and current.parent != current:
        if _is_link(_io(current)):
            return current
        current = current.parent
    return None


def catchup_files(root, catchup_id):
    """(owned, not_attributable, folders, links): every file below the catch-up's evidence folders. A symbolic link
    or junction met on the walk is never followed; it is listed in ``links`` and refuses the archive."""
    folders, unknown = catchup_folders(root, catchup_id)
    owned, links = [], []
    for folder, proof in folders:
        if link_below(root, folder) is not None:
            links.append(_relative(root, folder))
            continue
        physical = _io(folder)
        pending = [physical]
        while pending:                       # never descends into a link (rglob would walk into a junction)
            current = pending.pop()
            with os.scandir(current) as found:
                children = sorted(found, key=lambda entry: entry.name)
            for entry in children:
                path = Path(entry.path)
                logical = folder / path.relative_to(physical)
                if _is_link(path):
                    links.append(_relative(root, logical))
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    owned.append(_item(root, logical, proof))
    owned.sort(key=lambda item: item['relative_path'])
    return owned, unknown, [_relative(root, folder) for folder, _ in folders], sorted(set(links))


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


def runner_state(root, folder, run_id):
    """None when a seed hunt, catch-up or hold-up test run is finished, else running, pending, paused, pausing or
    unsettled (SeedRunner states: a stopped run with members left is resumable, so it reads paused)."""
    base = Path(root) / folder / run_id
    try:
        state = _bounded_json(base / 'state.json')
    except (OSError, ValueError):
        state = None
    if not isinstance(state, dict):
        return 'unsettled'
    members = [m.get('status') for m in state.get('members') or [] if isinstance(m, dict)]
    status = state.get('status')
    if (base / 'pause.json').is_file():
        return 'pausing' if status in ('active', 'closing_monitor') else 'paused'
    if status == 'prepared':
        return 'pending'
    if status in ('active', 'closing_monitor'):
        return 'running'
    if status == 'reconcile_required' or any(m == 'reconcile_required' for m in members):
        return 'unsettled'
    if status in ('completed', 'stopped'):
        return 'paused' if any(m in RUNNER_ACTIVE_MEMBERS for m in members) else None
    return 'unsettled'


def catchup_state_blocker(root, catchup_id):
    status = runner_state(root, 'catchups', catchup_id)
    if status is None:
        return None
    return _blocker('ARCHIVE_NOT_FINISHED', 'Catch-up %s is %s; only a finished catch-up is archived.' % (catchup_id, status),
                    batch_id=catchup_id, batch_state=status)


READERS = (('seeds', 'seed hunt'), ('catchups', 'catch-up'), ('holdups', 'hold-up test'))


def _inside(path, folders):
    if not isinstance(path, str):
        return False
    target = os.path.normcase(os.path.abspath(_plain(path)))
    return any(target.startswith(folder + os.sep) for folder in folders)


def scan_citations(root, install, batch_id, *, shas, lock_shas, folders, reveal=None, skip=None, now):
    """Every citation this controller can see of a batch's SETs (``shas``) or folders (``folders``), each marked:

    * a seed hunt, catch-up or hold-up test whose manifest member sources one of them (``source_path`` /
      ``original.set_path`` inside a folder, or ``source_sha256`` / ``original.set_sha256`` in ``shas``), with
      ``in_flight`` true while that run is not finished (runner_state);
    * a held-out lock whose frozen candidate holds one of ``lock_shas``, or the lock this catch-up reveals
      (``reveal``), with ``active`` (studio_heldout: locked, revealable or revealing).

    Raises ValueError when a manifest or the lock registry cannot be read: nothing can be proven then.
    """
    from studio_heldout import ACTIVE as LOCK_ACTIVE, read_registry
    bases = [os.path.normcase(os.path.abspath(_plain(folder))) for folder in folders]
    hits = []
    for runner, kind in READERS:
        base = Path(root) / runner
        for path in sorted(base.glob('*/manifest.json')) if base.is_dir() else []:
            run_id = path.parent.name
            if (runner, run_id) == skip:
                continue
            try:
                value = _bounded_json(path)
            except (OSError, ValueError, UnicodeError) as error:
                raise ValueError('the %s manifest %s is unreadable (%s)' % (kind, path, str(error)[:200])) from None
            state = None
            for member in (value.get('members') if isinstance(value, dict) else None) or []:
                if not isinstance(member, dict):
                    continue
                original = member.get('original') if isinstance(member.get('original'), dict) else {}
                source = member.get('source_path') or original.get('set_path')
                digest = member.get('source_sha256') or original.get('set_sha256')
                if digest in shas or _inside(source, bases):
                    if state is None:
                        state = runner_state(root, runner, run_id) or 'finished'
                    hits.append(dict(kind='source' if runner == 'seeds' else 'foos_read', via=kind, run_id=run_id,
                                     set_path=source, set_sha256=digest, reader_state=state, in_flight=state != 'finished',
                                     plain='cited by %s %s (%s)' % (kind, run_id, state)))
    registry = read_registry(install, now=now)
    if registry['state'] == 'unavailable':
        raise ValueError('the held-out lock registry cannot be verified (' + str(registry['error']) + ')')
    for lock in registry['locks']:
        active = lock.get('active') if isinstance(lock.get('active'), bool) else lock.get('status') in LOCK_ACTIVE
        cells = [cell.get('set_sha256') for cell in lock.get('candidate') or [] if cell.get('set_sha256') in lock_shas]
        if cells or (reveal is not None and lock.get('lock_id') == reveal):
            hits.append(dict(kind='selection', via='held-out lock freeze' if cells else 'held-out reveal',
                             lock_id=lock.get('lock_id'), strategy_key=lock.get('strategy_key'), set_sha256=(cells or [None])[0],
                             lock_status=lock.get('status'), active=bool(active),
                             plain='cited by held-out lock %s (%s)' % (str(lock.get('lock_id'))[:12], lock.get('status'))))
    return hits


def citation_blockers(batch_id, hits):
    """Citations block only while they matter now: an ACTIVE held-out lock, or a run still reading the batch."""
    blockers = []
    locks = [hit for hit in hits if hit['kind'] == 'selection' and hit['active']]
    if locks:
        blockers.append(_blocker('ARCHIVE_HELDOUT_LOCK_ACTIVE', 'Held-out lock %s (%s) holds batch %s\'s SETs and is still '
                                 'active; archive it after the lock is revealed.' % (locks[0]['lock_id'], locks[0]['lock_status'],
                                                                                    batch_id),
                                 batch_id=batch_id, locks=[{k: h[k] for k in ('lock_id', 'lock_status', 'set_sha256')} for h in locks]))
    readers = [hit for hit in hits if hit.get('in_flight')]
    if readers:
        blockers.append(_blocker('ARCHIVE_IN_FLIGHT_READER', '%s %s is %s and reads batch %s as its source; archive it after '
                                 'that run finishes.' % (readers[0]['via'], readers[0]['run_id'], readers[0]['reader_state'],
                                                         batch_id),
                                 batch_id=batch_id, reader=readers[0]['run_id'], reader_kind=readers[0]['via'],
                                 reader_state=readers[0]['reader_state'],
                                 readers=[{k: h[k] for k in ('via', 'run_id', 'reader_state', 'set_path')} for h in readers[:50]]))
    return blockers


def _unverifiable(batch_id, error):
    return _blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'It cannot be proven which runs or held-out locks cite batch %s (%s); '
                    'nothing is moved.' % (batch_id, str(error)[:300]), batch_id=batch_id)


def native_citations(root, install, job_id, *, now):
    """(blockers, citations, run folder) of a native batch: its export SETs and its run folder."""
    from studio_batch_close import batch_exports, run_root
    try:
        run = run_root(root, install, job_id)
        shas = {item['set_sha256'] for item in batch_exports(run)}
        hits = scan_citations(root, install, job_id, shas=shas, lock_shas=shas, folders=[run], now=now)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        return [_unverifiable(job_id, error)], [], None
    return citation_blockers(job_id, hits), hits, run


def catchup_citations(root, install, catchup_id, folders, *, now):
    """(blockers, citations) of a catch-up: its re-test SETs and evidence folders (read by later runs), and the
    original and re-test SETs a held-out lock may freeze, or the lock it reveals."""
    try:
        manifest = _bounded_json(Path(root) / 'catchups' / catchup_id / 'manifest.json')
        originals, retests = set(), set()
        for spec in manifest.get('members') or []:
            original = (spec or {}).get('original') or {}
            if isinstance(original.get('set_sha256'), str):
                originals.add(original['set_sha256'])
        for folder in folders:
            for path in sorted(_io(Path(root) / folder).glob('*/evidence-version.json')):
                record = _bounded_json(path, 16 * 1024 * 1024)
                sha = ((record or {}).get('retest') or {}).get('set_sha256') if isinstance(record, dict) else None
                if isinstance(sha, str):
                    retests.add(sha)
        reveal = (manifest.get('heldout_reveal') or {}).get('lock_id') if isinstance(manifest.get('heldout_reveal'), dict) else None
        hits = scan_citations(root, install, catchup_id, shas=retests, lock_shas=retests | originals,
                              folders=[Path(root) / folder for folder in folders], reveal=reveal,
                              skip=('catchups', catchup_id), now=now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError) as error:
        return [_unverifiable(catchup_id, error)], []
    return citation_blockers(catchup_id, hits), hits


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


def durability_blockers(target):
    """The archive becomes the only copy: refuse a remote drive (studio_build_migration's GetDriveTypeW check) and
    any file system but NTFS or ReFS (exFAT/FAT32 USB sticks have no journal)."""
    text = os.path.abspath(_plain(target))
    if text.startswith(('\\\\', '//')):
        return [_blocker('ARCHIVE_ROOT_REMOTE', 'The archive root %s is a network path; the archive becomes the only copy, so '
                         'it must be a local drive.' % text, archive_root=text)]
    import studio_build_migration as migration
    volume = volume_root_of(text)
    kind = migration._drive_type(volume)
    if kind is not None and kind not in migration.LOCAL_DRIVE_TYPES:
        what = {0: 'a drive of unknown type', 1: 'a drive that does not exist', 4: 'a network drive',
                5: 'a CD-ROM drive'}.get(kind, 'drive type %s' % kind)
        return [_blocker('ARCHIVE_ROOT_REMOTE', 'The archive root %s is on %s; the archive becomes the only copy, so it must '
                         'be a local drive.' % (text, what), archive_root=text, drive_type=kind)]
    try:
        filesystem = filesystem_of(volume)
    except OSError as error:
        return [_blocker('ARCHIVE_ROOT_FILESYSTEM', 'The file system of the archive root %s cannot be read (%s); only NTFS '
                         'or ReFS is accepted.' % (text, str(error)[:200]), archive_root=text, filesystem=None)]
    if filesystem is not None and str(filesystem).upper() not in DURABLE_FILESYSTEMS:
        return [_blocker('ARCHIVE_ROOT_FILESYSTEM', 'The archive root %s is on a %s volume; the archive becomes the only copy, '
                         'so only NTFS or ReFS is accepted (reformat the drive or pick another).' % (text, filesystem),
                         archive_root=text, filesystem=filesystem)]
    return []


def root_blockers(root, archive_root, size):
    """Archive-root checks: absolute, present, local NTFS/ReFS, another volume than the controller state, writable,
    enough space."""
    text = str(archive_root or '')
    if not text or not Path(text).is_absolute():
        return [_blocker('ARCHIVE_ROOT_INVALID', 'The archive root must be an absolute folder path.', archive_root=text)], None
    target = Path(os.path.abspath(text))
    if not _io(target).is_dir():
        return [_blocker('ARCHIVE_ROOT_UNAVAILABLE', 'The archive root %s is not an existing folder; connect the drive or '
                         'create the folder first.' % target, archive_root=str(target))], None
    durability = durability_blockers(target)
    if durability:
        return durability, None
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
    run, folders, citations, links = None, [], [], []
    if kind == 'native':
        owned, unknown = native_files(root, batch_id, bindings)
        state = native_state_blocker(root, job)
        if state:
            blockers.append(state)
        if job.get('native_evidence_history'):
            blockers.append(_blocker('ARCHIVE_COMPACT_FIRST', 'Batch %s still keeps native evidence history in its queue row; '
                                     'run compact-evidence --apply first so it is archived too.' % batch_id, batch_id=batch_id))
        if pointer is None and owned:
            # A finished FOOS read or a revealed lock is informational (the pointer keeps the evidence readable);
            # an ACTIVE held-out lock or a run still reading the batch blocks (Claude-Mac, #205).
            found, citations, run = native_citations(root, install, batch_id, now=now)
            blockers.extend(found)
    else:
        owned, unknown, folders, links = catchup_files(root, batch_id)
        state = catchup_state_blocker(root, batch_id)
        if state:
            blockers.append(state)
        if pointer is None and owned:
            found, citations = catchup_citations(root, install, batch_id, folders, now=now)
            blockers.extend(found)
    links = sorted(set(links) | {item['relative_path'] for item in owned if link_below(root, Path(root) / item['relative_path'])})
    if links:
        blockers.append(_blocker('ARCHIVE_SOURCE_LINK', '%s is a symbolic link or junction, or lies below one; evidence-archive '
                                 'never follows links, so nothing moves. Replace it with the real folder first.' % links[0],
                                 batch_id=batch_id, links=links[:50]))
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
    if keep is None:
        blockers.append(keep_list_required(batch_id))
    files = sorted(owned, key=lambda item: item['relative_path'])
    if pointer is None:
        step = ('evidence-archive --apply --confirm --keep-list <file> copies these files to the archive, verifies them, '
                'writes the manifest and the pointer, and keeps every source; then evidence-archive --complete --batch-id '
                '%s --confirm re-verifies every archived file from disk and only then removes the sources.' % batch_id)
    else:
        step = ('Archived to %s; readers follow the pointer. %d local source(s) are still here as the safety copy: '
                'evidence-archive --complete --batch-id %s --confirm re-verifies every archived file and then removes them; '
                'evidence-restore brings the archive back, evidence-repoint accepts a verified copy elsewhere.'
                % (pointer['archive_dir'], len(owned), batch_id))
    return dict(batch_id=batch_id, kind=kind, installation=installation_id(root), archive_dir=str(target) if target else None,
                archived=pointer is not None, pointer=str(pointer_path(root, batch_id)) if pointer is not None else None,
                files=files, file_count=len(files), bytes=size, size=_human(size), folders=folders,
                not_attributable=sorted(unknown, key=lambda item: item['relative_path'] or ''),
                required_free_bytes=required_bytes(size), archive_free_bytes=free,
                citations=citations, cited_by=[hit['plain'] for hit in citations], keep_list_checked=keep is not None,
                blockers=blockers, ready=not blockers, run_root=str(run) if run else None, next_step=step)


def keep_list_required(batch_id):
    return _blocker('ARCHIVE_KEEP_LIST_REQUIRED', '--apply needs --keep-list <file>: the JSON list (it may be empty, []) of '
                    'batches the prereg files and the book cite, which the controller cannot see.', batch_id=batch_id)


def public(value, applied=False):
    """The preview/result for a reply: at most MAX_PUBLIC_FILES file rows (counts and bytes stay whole)."""
    result = dict(value, applied=applied)
    for key in ('files', 'not_attributable', 'citations', 'cited_by'):
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


def _fsync_file(path):
    """fsync a file again after its rename, so the renamed bytes are durable before anything relies on them."""
    with _io(path).open('r+b') as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path):
    """fsync a folder where the platform allows it (POSIX); Windows offers no directory fsync through os."""
    if os.name == 'nt':
        return False
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def copy_verified(source, target, expected=None):
    """Copy ``source`` to ``target`` (temporary file, fsync, atomic rename, fsync again) and verify the copy against
    the source bytes by SHA-256 (and against ``expected`` when given: a restore checks the manifest). An existing
    identical target is reused; a different one refuses. Returns (sha256, bytes, reused)."""
    source_io, target_io = _io(source), _io(target)
    if target_io.is_file():
        digest = expected or file_sha256(source)
        if _readback(target) != digest:
            raise Refusal('A different file already exists at %s; nothing was removed. Inspect it.' % target,
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
        actual = digest.hexdigest()
        if expected is not None and actual != expected:
            raise Refusal('%s does not hash to its manifest (sha256 differs); nothing was copied from it.' % source,
                          'ARCHIVE_VERIFY_FAILED', source=_plain(source))
        if _readback(temporary) != actual:
            raise Refusal('The copy of %s did not verify (sha256 differs); the source is kept.' % source,
                          'ARCHIVE_VERIFY_FAILED', source=_plain(source))
        os.replace(temporary, target_io)
    finally:
        if temporary.exists():
            temporary.unlink()
    _fsync_file(target_io)
    _fsync_dir(target_io.parent)
    if _readback(target) != actual:
        raise Refusal('The copy of %s did not verify after its rename (sha256 differs); the source is kept.' % source,
                      'ARCHIVE_VERIFY_FAILED', source=_plain(source))
    return actual, size, False


def _write_json_file(path, value):
    """Temp-write, fsync and atomically rename one record (studio_bridge.write_json), then fsync it again."""
    from studio_bridge import write_json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)
    _fsync_file(path)
    _fsync_dir(Path(path).parent)


def _same_files(left, right):
    return sorted((f['relative_path'], f['bytes'], f['sha256']) for f in left) == \
        sorted((f['relative_path'], f['bytes'], f['sha256']) for f in right)


def _verified_copies(pointer, folder, entries, consequence):
    """Re-read and re-hash EVERY archived file from disk (no cache) against its manifest entry; refuses
    ARCHIVE_VERIFY_FAILED, naming ``consequence`` (what was left untouched), on the first that does not match."""
    for entry in entries:
        try:
            _verify_entry(pointer, folder, entry, full=True, cache=False)
        except ArchiveUnreachable as error:
            raise Refusal('%s %s' % (error, consequence), 'ARCHIVE_VERIFY_FAILED', batch_id=pointer['batch_id'],
                          relative_path=entry['relative_path'], archive_dir=str(folder)) from None


def _refuse_links(root, entries, consequence):
    for entry in entries:
        link = link_below(root, Path(root) / entry['relative_path'])
        if link is not None:
            raise Refusal('%s is a symbolic link or junction; evidence-archive never follows links. %s' % (link, consequence),
                          'ARCHIVE_SOURCE_LINK', relative_path=entry['relative_path'], link=str(link))


def _remove_empty_folders(root, pointer):
    """Remove the folders the moved files left empty (never through a link)."""
    for relative in sorted(pointer.get('folders') or [], key=len, reverse=True):
        logical = Path(root) / relative
        if link_below(root, logical) is not None:
            continue
        physical = _io(logical)
        folders = []
        for current, names, _ in os.walk(physical) if physical.is_dir() else []:
            names[:] = [name for name in names if not _is_link(Path(current) / name)]
            folders.append(Path(current))
        for path in sorted(folders, key=lambda p: len(str(p)), reverse=True):
            try:
                path.rmdir()                     # only empty folders
            except OSError:
                pass


def _summary(root, record, folder, entries, **fields):
    return dict(dict(copied=0, reused=len(entries), removed=0, verified=len(entries), manifest=str(folder / MANIFEST),
                     manifest_sha256=record['manifest_sha256'], pointer=str(pointer_path(root, record['batch_id'])),
                     archive_dir=str(folder), bytes=sum(entry['bytes'] for entry in entries), file_count=len(entries)),
                **fields)


def verify(root, pointer):
    """A re-run of --apply with a pointer: re-verify every archived file from disk; removes nothing."""
    folder, entries = _open(pointer, strict=True)
    entries = sorted(entries.values(), key=lambda entry: entry['relative_path'])
    _verified_copies(pointer, folder, entries, 'Nothing was changed.')
    present = sum(_io(Path(root) / entry['relative_path']).is_file() for entry in entries)
    return _summary(root, pointer, folder, entries, changed=False, sources_kept=present, already_removed=len(entries) - present)


def complete(root, pointer):
    """Remove the sources of an archived batch (``evidence-archive --complete``), the only removal of evidence here.

    First every manifest entry is validated (manifest_problem: relative, no ``..``, below native-evidence/ or
    evidence/, named by the pointer) and EVERY archived file is re-read from disk and re-hashed against the manifest;
    then every present source is hashed. Any missing or corrupt archive copy, link, or changed source refuses with
    nothing removed. Each source is removed only if its size and mtime are still those it hashed with.
    """
    folder, entries = _open(pointer, strict=True)
    entries = sorted(entries.values(), key=lambda entry: entry['relative_path'])
    _verified_copies(pointer, folder, entries, 'Every source is kept; nothing was removed.')
    _refuse_links(root, entries, 'Nothing was removed.')
    sources, changed, gone = [], [], 0
    for entry in entries:
        source = Path(root) / entry['relative_path']
        physical = _io(source)
        try:
            before = physical.stat()
        except FileNotFoundError:
            gone += 1
            continue
        after = None
        if stat_mode.S_ISREG(before.st_mode) and before.st_size == entry['bytes'] and file_sha256(source) == entry['sha256']:
            after = physical.stat()
        if after is None or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            changed.append(entry['relative_path'])
        else:
            sources.append((source, after.st_size, after.st_mtime_ns))
    if changed:
        raise Refusal('%d source(s) of batch %s changed since they were archived (first: %s); nothing was removed. Inspect '
                      'them.' % (len(changed), pointer['batch_id'], changed[0]), 'ARCHIVE_SOURCE_CHANGED',
                      batch_id=pointer['batch_id'], relative_path=changed[0], relative_paths=changed[:50])
    removed = []
    for source, size, mtime in sources:
        now = _io(source).stat()
        if (now.st_size, now.st_mtime_ns) != (size, mtime):
            raise Refusal('The source %s changed while the archive was being completed; it is kept (%d removed before it). '
                          'Inspect it, then re-run --complete.' % (source, len(removed)), 'ARCHIVE_SOURCE_CHANGED',
                          batch_id=pointer['batch_id'], relative_path=_relative(root, source), removed=len(removed))
        _unlink(source)
        removed.append(source)
    _remove_empty_folders(root, pointer)
    return _summary(root, pointer, folder, entries, changed=bool(removed), removed=len(removed), already_removed=gone,
                    sources_kept=0)


def _retire(root, pointer, reason, *, now, by, **details):
    """Keep an audit record of a pointer that restore or repoint replaces: native-evidence/archived/retired/."""
    folder = Path(root).joinpath(*POINTERS, RETIRED)
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = folder / ('%s.%s.%s.json' % (pointer['batch_id'], stamp, uuid.uuid4().hex[:8]))
    _write_json_file(path, dict(pointer, retired_at=_utc(now), retired_by=by, retired_reason=reason, **details))
    return path


def restore(root, pointer, *, now, restored_by='demo_agent'):
    """``evidence-restore``: copy a verified archive back into the controller state and retire the pointer.

    Every archived file is re-hashed against the manifest first; a local file that already exists must equal its
    manifest entry (else ARCHIVE_RESTORE_CONFLICT, nothing restored). Each copy is temp-written, fsynced, verified
    against the manifest's sha256 and renamed. Then the pointer is written to ``archived/retired/`` and removed, so
    readers read the local copy again. The archive copy is kept.
    """
    batch_id = pointer['batch_id']
    folder, entries = _open(pointer, strict=True)
    entries = sorted(entries.values(), key=lambda entry: entry['relative_path'])
    _verified_copies(pointer, folder, entries, 'Nothing was restored.')
    _refuse_links(root, entries, 'Nothing was restored.')
    conflicts, local = [], 0
    for entry in entries:
        target = _io(Path(root) / entry['relative_path'])
        if target.exists() or target.is_symlink():
            if not target.is_file() or file_sha256(target) != entry['sha256']:
                conflicts.append(entry['relative_path'])
            else:
                local += 1
    if conflicts:
        raise Refusal('%d local file(s) of batch %s differ from the archive (first: %s); nothing was restored. Inspect '
                      'them.' % (len(conflicts), batch_id, conflicts[0]), 'ARCHIVE_RESTORE_CONFLICT', batch_id=batch_id,
                      relative_path=conflicts[0], relative_paths=conflicts[:50])
    copied = 0
    for entry in entries:
        target = Path(root) / entry['relative_path']
        if _io(target).is_file():
            continue
        copy_verified(folder / entry['relative_path'], target, expected=entry['sha256'])
        copied += 1
    retired = _retire(root, pointer, 'restored', now=now, by=restored_by, restored_files=copied, already_local=local,
                      restored_from=str(folder))
    path = pointer_path(root, batch_id)
    _io(path).unlink()
    _fsync_dir(path.parent)
    return _summary(root, pointer, folder, entries, changed=True, restored=copied, already_local=local,
                    retired_pointer=str(retired), pointer=None,
                    plain='Batch %s\'s evidence is back in the controller state; the archive copy at %s is kept.'
                          % (batch_id, folder))


def repoint(root, pointer, new_dir, *, now, repointed_by='demo_agent'):
    """``evidence-repoint``: accept ``new_dir`` only when its manifest.json hashes to the pointer's manifest_sha256
    and every file verifies from disk, then rewrite the pointer atomically (the old one is kept as a retired record)."""
    batch_id = pointer['batch_id']
    text = str(new_dir or '')
    if not text or not Path(text).is_absolute():
        raise Refusal('--archive-dir must be an absolute folder path.', 'ARCHIVE_ROOT_INVALID', archive_dir=text)
    target = Path(os.path.abspath(text))
    manifest = target / MANIFEST
    if not _io(manifest).is_file():
        raise Refusal('%s holds no manifest.json; nothing was changed.' % target, 'ARCHIVE_REPOINT_MISMATCH',
                      batch_id=batch_id, archive_dir=str(target))
    found = durability_blockers(target)
    if found:
        raise Refusal(found[0]['plain'] + ' Nothing was changed.', found[0]['code'], batch_id=batch_id, archive_dir=str(target))
    if file_sha256(manifest) != pointer['manifest_sha256']:
        raise Refusal('The manifest at %s is not batch %s\'s archived manifest (sha256 differs from the pointer); nothing '
                      'was changed.' % (manifest, batch_id), 'ARCHIVE_REPOINT_MISMATCH', batch_id=batch_id,
                      archive_dir=str(target))
    moved = dict(pointer, archive_dir=str(target))
    for field in ('volume_guid', 'archive_relative'):
        moved.pop(field, None)
    folder, entries = _open(moved, strict=True)          # the new location only: its own manifest, its own files
    entries = sorted(entries.values(), key=lambda entry: entry['relative_path'])
    _verified_copies(moved, folder, entries, 'Nothing was changed.')
    layout = target.name == batch_id and target.parent.name == installation_id(root)
    updated = dict(moved, manifest=str(manifest), archive_root=str(target.parent.parent) if layout else None,
                   repointed_at=_utc(now), repointed_by=repointed_by,
                   previous_archive_dirs=list(pointer.get('previous_archive_dirs') or []) + [pointer['archive_dir']],
                   plain='This batch\'s evidence lives in ' + str(target) + '; controller readers follow this pointer.',
                   **_volume_fields(target))
    retired = _retire(root, pointer, 'repointed', now=now, by=repointed_by, repointed_to=str(target))
    _write_json_file(pointer_path(root, batch_id), updated)
    return _summary(root, updated, folder, entries, changed=True, previous_archive_dir=pointer['archive_dir'],
                    retired_pointer=str(retired))


def apply(root, install, preview, archive_root, *, now, archived_by='demo_agent'):
    """Copy the previewed files to the archive, verify them, write the manifest and the pointer, and STOP: every
    source stays (removal is ``complete``, a separate invocation). The caller re-built ``preview`` under the terminal
    lock and found no blocker. A re-run with a pointer re-verifies the archive and changes nothing."""
    batch_id = preview['batch_id']
    pointer = load_pointer(root, batch_id)
    if pointer is not None:
        return verify(root, pointer)
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
            plain='Evidence of %s copied off the controller volume, each file sha256-verified; its sources are removed only by '
                  'evidence-archive --complete after every file here is re-verified.' % batch_id))
    manifest = _bounded_json(manifest_path)
    digest = file_sha256(manifest_path)
    pointer = dict(schema=POINTER_SCHEMA, schema_version=SCHEMA_VERSION, batch_id=batch_id, kind=preview['kind'],
                   installation=installation_id(root), archive_root=str(Path(os.path.abspath(archive_root))),
                   archive_dir=str(folder), manifest=str(manifest_path), manifest_sha256=digest,
                   files=[entry['relative_path'] for entry in manifest['files']], folders=manifest.get('folders') or [],
                   file_count=len(manifest['files']), bytes=manifest.get('bytes'), archived_at=_utc(now),
                   archived_by=archived_by, controller_revision=controller_revision(install),
                   plain='This batch\'s evidence lives in ' + str(folder) + '; controller readers follow this pointer.',
                   **_volume_fields(folder))
    _write_json_file(pointer_path(root, batch_id), pointer)
    present = sum(_io(Path(root) / entry['relative_path']).is_file() for entry in manifest['files'])
    return dict(changed=True, copied=copied, reused=reused, removed=0, already_removed=len(entries) - present,
                sources_kept=present, verified=len(entries), manifest=str(manifest_path), manifest_sha256=digest,
                pointer=str(pointer_path(root, batch_id)), archive_dir=str(folder), bytes=manifest.get('bytes'),
                file_count=len(entries))
