"""evidence-archive --run-folders: move finished native run folders off the Common Files volume (P-beta38-run-folder-archive).

goatai#2350 6156934300. ``Common Files\\GOAT\\R<12 hex>`` holds every native batch's run folder forever: the frozen
queue, inputs, reports, ``exports`` and the kept ``deploy`` units with their ``.goatseq`` captures (``account.csv``
alone is ~60 MB per kept set). On the Banker PC that is ~104 GB on C:. This scope of ``evidence-archive`` MOVES a
finished run folder to an archive root on another local NTFS/ReFS volume and leaves ``ARCHIVED.json`` in its place;
every controller reader follows that stub (``resolve``), so whatever cites a SET, report or export inside the run
folder still reads it.

What is eligible (``plan``), derived from the controller's own state, never from mtimes:

* the folder is ``<Common Files>\\GOAT\\R<12 hex>`` and a package (``packages/<job>/manifest.json``
  ``native_run_relative``) of this installation, or of a sibling installation of the same suite that shares these
  Common Files, names it; a folder no package names is ``not_attributable`` and never moved;
* every owning batch is terminal (completed, cancelled or failed, never ``reconcile_required``) with no unsettled,
  paused or pausing pause record (studio_evidence_archive.native_state_blocker);
* no EA ``active_optimization_run.ini`` pointer names it and no batch-driver journal of an owner is still live
  (``stopped`` false), paused or pausing;
* it is not continue-able: an owner that still has never-run members (cancelled, pending or queued) and was neither
  closed (batch-pause-close) nor continued as a ``-rN`` successor refuses ``ARCHIVE_CONTINUABLE``; a successor
  (``batch-lineage`` or a queued ``<job>-rN``) that is not terminal refuses ``ARCHIVE_SUCCESSOR_ACTIVE``;
* no unfinished seed hunt, catch-up or hold-up test of any of these installations cites a path inside it (member
  ``source_path``, ``original.set_path``, ``build_migration.original_path``, or the plan's ``sets``), and no ACTIVE
  held-out lock freezes one of its deploy SETs; finished citations (b43mig-1) are listed under ``cited_by`` only,
  because the stub keeps them resolvable;
* it is not kept: the newest ``--keep-last`` runs (by the owner's ``launch_intent.recorded_at``) and every batch ID or
  run folder on the caller's ``--keep-list``;
* no symbolic link or junction lies inside it.

The desktop library imports a run's ``deploy`` units by COPYING them (goatai desktop/main/services/libraryService.ts:
companions .csv/.set/.goatseq are copied into ``artifacts/libraries/<id>/source``, and the SET bytes are stored again
in the snapshot as ``rawSetBinaryBase64``). Its only later look at the run folder is the export-qualification stamp
(``export-qualification`` here, which follows the stub) and the catch-up's preference for the original SET
(evidenceCatchupService.memberSet falls back to the library copy when the original is gone). So ``deploy`` is moved
with the rest of the folder.

How it moves, in two separate invocations as evidence-archive (``apply`` never removes; ``complete`` removes only
after re-verifying):

``apply``: each file is copied to ``<archive root>/<run id>/<same relative path>`` (studio_evidence_archive.
copy_verified: temporary file, fsync, atomic rename, sha256 read back; an identical copy left by an interrupted run is
reused, a different one refuses); the source is re-walked and must hold exactly the copied files, and the archive
folder must hold exactly them too; then ``.goat-run-archive-manifest.json`` (every relative path, bytes, sha256) is
written in the archive folder and ``ARCHIVED.json`` (archive folder, file count, bytes, manifest sha256, time, state
``archived``) in the source. Sources stay. A crash before the stub leaves the source untouched; a re-run resumes.

``complete``: the manifest must hash to the stub's, every archived file is re-read and re-hashed from disk (no cache)
and the archive folder must hold exactly the manifest's files; every source file must still be listed and hash to
it. Only then the stub turns ``removing``, each source file is removed (only below that run folder, only a regular
file, never a link, never the stub) and emptied folders are removed; the stub turns ``removed``. A crash while
removing resumes on the next ``complete``.

Readers (``resolve``/``run_dir``/``read_bytes``): while the stub is ``archived`` the local copy is the truth. Once it
is ``removing`` or ``removed`` the archive is: a file the manifest lists is size-checked on every read and sha256-checked
on its first read in a process; an unreachable archive (unplugged drive, also not found by its volume GUID under
another letter), a manifest that no longer matches the stub, or a missing or corrupt copy refuses
``EVIDENCE_ARCHIVE_UNREACHABLE`` (studio_evidence_archive.ArchiveUnreachable), never a silent fallback.

Safety: a preview by default (eligible folders, bytes to free, the target's free space); ``--apply`` needs
``--confirm`` and ``--keep-list``; the archive root must be absolute, existing, local NTFS/ReFS, writable, on another
volume than the run folders (ARCHIVE_ROOT_SAME_VOLUME) and keep ``--free-floor-gb`` (default 50 GB) free after the
copy (ARCHIVE_ROOT_FLOOR). Unlike batch evidence it does not need an idle terminal (a finished run folder is never
read by MT5) and does not hold the terminal lease during a long copy; it holds its own lock
(``<Common Files>\\GOAT\\.run-folder-archive.lock``, shared by every installation of these Common Files) and re-checks
every run's eligibility before it copies or removes it.

Directory readers (``run_dir``) open files of an archive folder through ``checked``, which verifies each file they
consume (size, and sha256 once per process) against the manifest, so a same-size corruption refuses instead of being
read.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat as stat_mode

import studio_evidence_archive as archive
from studio_evidence_archive import ArchiveUnreachable, _io, _plain
from studio_refusal import Refusal

STUB = 'ARCHIVED.json'
STUB_SCHEMA = 'goat-run-folder-archive-stub-v1'
MANIFEST = '.goat-run-archive-manifest.json'
MANIFEST_SCHEMA = 'goat-run-folder-archive-manifest-v1'
SCHEMA_VERSION = 1
RUN_NAME = re.compile(r'R[0-9a-f]{12}')
RUN_RELATIVE = re.compile(r'GOAT[\\/](R[0-9a-f]{12})')
STATES = ('archived', 'removing', 'removed')
TERMINAL = ('completed', 'cancelled', 'failed')
UNRUN_MEMBERS = ('native_cancelled', 'native_pending', 'native_queued')
POINTER_NAME = 'active_optimization_run.ini'
POINTER_DEPTH = 3
LOCK_NAME = '.run-folder-archive.lock'
DEFAULT_KEEP_LAST = 10
DEFAULT_FLOOR_GB = 50
GB = 1024 ** 3
MAX_STUB_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_MANIFEST = 64 * 1024 * 1024
MAX_PUBLIC = 500
SUCCESSOR = re.compile(r'-r[1-9][0-9]{0,3}$')

# Refusal codes of this scope (append only); the shared ones (ARCHIVE_CONFIRM_REQUIRED, ARCHIVE_ROOT_*,
# ARCHIVE_KEEP_LISTED, ARCHIVE_NOT_FINISHED, ARCHIVE_IN_FLIGHT_READER, ARCHIVE_VERIFY_FAILED, ...) are evidence-archive's.
CODES = frozenset((
    'ARCHIVE_RUN_ACTIVE', 'ARCHIVE_DRIVER_LIVE', 'ARCHIVE_CONTINUABLE', 'ARCHIVE_SUCCESSOR_ACTIVE', 'ARCHIVE_OWNER_UNKNOWN',
    'ARCHIVE_KEPT_RECENT', 'ARCHIVE_ROOT_FLOOR', 'ARCHIVE_ACTIVE_UNVERIFIABLE', 'ARCHIVE_RUN_ARCHIVED',
    'ARCHIVE_ARCHIVER_BUSY', 'ARCHIVE_STUB_INVALID'))


def _utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _key(relative):
    return relative.replace('\\', '/').strip('/').casefold()


def _norm(path):
    return os.path.normcase(os.path.abspath(_plain(str(path))))


# ---------------------------------------------------------------------------
# Readers: the stub, the archive and the resolver
# ---------------------------------------------------------------------------

def run_folder_of(path):
    """(run folder, parts below it) when ``path`` lies at or below ``<...>\\GOAT\\R<12 hex>``, else None."""
    if path is None:
        return None
    parts = Path(os.path.abspath(_plain(str(path)))).parts
    for index in range(1, len(parts)):
        if RUN_NAME.fullmatch(parts[index]) and parts[index - 1].casefold() == 'goat':
            return Path(*parts[:index + 1]), parts[index + 1:]
    return None


def _bad_relative(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 1024:
        return 'is not a path'
    if '\\' in relative or relative.startswith('/') or ':' in relative or '\x00' in relative:
        return 'is not a relative forward-slash path'
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return 'has an empty, . or .. part'
    if relative.casefold() in (STUB.casefold(), MANIFEST.casefold()):
        return 'is the archive\'s own record'
    return None


def stub_problem(value, run_id):
    """Why a stub cannot be trusted, else None."""
    if not isinstance(value, dict) or value.get('schema') != STUB_SCHEMA:
        return 'is not a ' + STUB_SCHEMA + ' record'
    if value.get('run_id') != run_id:
        return 'names run %r' % (value.get('run_id'),)
    if value.get('state') not in STATES:
        return 'has state %r' % (value.get('state'),)
    if not isinstance(value.get('archive_dir'), str) or not Path(value['archive_dir']).is_absolute():
        return 'has no absolute archive_dir'
    if not isinstance(value.get('manifest_sha256'), str) or not archive.SHA256.fullmatch(value['manifest_sha256']):
        return 'has no manifest_sha256'
    for field in ('file_count', 'bytes'):
        if type(value.get(field)) is not int or value[field] < 0:
            return 'has no ' + field
    for field in ('volume_guid', 'archive_relative'):
        if value.get(field) is not None and (not isinstance(value[field], str) or not value[field]):
            return 'has an invalid ' + field
    relative = value.get('archive_relative')
    if relative is not None and (Path(relative).is_absolute() or '..' in relative.replace('\\', '/').split('/')):
        return 'has an archive_relative that is not a plain relative path'
    return None


_STUBS = {}       # normcase stub path -> ((size, mtime_ns, ino), stub)
_MANIFESTS = {}   # normcase manifest path -> ((size, mtime_ns, ino, manifest sha256), entries)
_VERIFIED = set()
_OPEN = {}        # normcase archive folder -> (stub, folder, entries): folders run_dir/locate handed to a reader


def stub_path(run):
    return Path(run) / STUB


def load_stub(run):
    """The run folder's ARCHIVED.json, None when it has none. An unreadable or malformed stub refuses
    (ArchiveUnreachable): its files are somewhere else, so nothing is read in their place."""
    path = stub_path(run)
    physical = _io(path)
    try:
        stat = physical.stat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ArchiveUnreachable('The run-folder archive stub %s cannot be read (%s); nothing is read in its place.'
                                 % (path, str(error)[:200]), run_id=Path(run).name, stub=str(path)) from None
    cache_key, stamp = os.path.normcase(str(physical)), (stat.st_size, stat.st_mtime_ns, stat.st_ino)
    cached = _STUBS.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        value = archive._bounded_json(path, MAX_STUB_BYTES)
    except (OSError, ValueError, UnicodeError) as error:
        raise ArchiveUnreachable('The run-folder archive stub %s cannot be read (%s); nothing is read in its place. '
                                 'Inspect it.' % (path, str(error)[:200]), run_id=Path(run).name, stub=str(path)) from None
    problem = stub_problem(value, Path(run).name)
    if problem:
        raise ArchiveUnreachable('The run-folder archive stub %s %s; nothing is read in its place. Inspect it.'
                                 % (path, problem), run_id=Path(run).name, stub=str(path))
    _STUBS[cache_key] = (stamp, value)
    return value


def manifest_problem(stub, value):
    if not isinstance(value, dict) or value.get('schema') != MANIFEST_SCHEMA:
        return 'it is not a ' + MANIFEST_SCHEMA + ' record'
    if value.get('run_id') != stub['run_id']:
        return 'it names run %r' % (value.get('run_id'),)
    files = value.get('files')
    if not isinstance(files, list):
        return 'it has no files list'
    keys, total = set(), 0
    for entry in files:
        relative = entry.get('relative_path') if isinstance(entry, dict) else None
        problem = _bad_relative(relative)
        if problem:
            return 'its entry %r %s' % (relative, problem)
        if type(entry.get('bytes')) is not int or entry['bytes'] < 0 or not isinstance(entry.get('sha256'), str) \
                or not archive.SHA256.fullmatch(entry['sha256']):
            return 'its entry %s has no bytes or sha256' % relative
        if _key(relative) in keys:
            return 'it lists %s twice' % relative
        keys.add(_key(relative))
        total += entry['bytes']
    if value.get('file_count') != len(files) or stub['file_count'] != len(files):
        return 'it lists %d files; its file_count is %r and the stub says %r' % (len(files), value.get('file_count'),
                                                                                  stub['file_count'])
    if value.get('bytes') != total or stub['bytes'] != total:
        return 'its files hold %d bytes; it says %r and the stub says %r' % (total, value.get('bytes'), stub['bytes'])
    return None


def open_archive(stub, *, strict=False):
    """(archive folder, {key: entry}) of a stub: its archive_dir, or the same path on its volume found by GUID under
    another drive letter. Raises ArchiveUnreachable; ``strict`` (complete) never uses the cache and refuses an
    untrustworthy manifest with ARCHIVE_MANIFEST_INVALID."""
    errors = []
    for folder in archive._candidates(stub):
        manifest = folder / MANIFEST
        try:
            stat = _io(manifest).stat()
        except OSError as error:
            errors.append(str(error)[:200])
            continue
        entries = _entries(stub, folder, manifest, stat, strict)
        if not strict:
            _OPEN[os.path.normcase(os.path.abspath(_plain(str(folder))))] = (stub, folder, entries)
        return folder, entries
    raise ArchiveUnreachable('Run folder %s was archived to %s, which cannot be read now (%s)%s. Reconnect the archive '
                             'drive, then retry; nothing is read in its place.'
                             % (stub['run_id'], stub['archive_dir'], errors[0] if errors else 'not found',
                                '; its volume was not found under another drive letter either' if stub.get('volume_guid') else ''),
                             run_id=stub['run_id'], archive_dir=stub['archive_dir'])


def _entries(stub, folder, manifest, stat, strict):
    cache_key = os.path.normcase(str(manifest))
    stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ino, stub['manifest_sha256'])
    cached = _MANIFESTS.get(cache_key)
    if not strict and cached is not None and cached[0] == stamp:
        return cached[1]

    def fail(why):
        return ArchiveUnreachable('The archive of run folder %s at %s %s; nothing is read from it. Inspect the archive.'
                                  % (stub['run_id'], folder, why), run_id=stub['run_id'], archive_dir=str(folder))
    try:
        if stat.st_size > MAX_MANIFEST_BYTES:
            raise ValueError('it exceeds %d bytes' % MAX_MANIFEST_BYTES)
        raw = _io(manifest).read_bytes()
        if hashlib.sha256(raw).hexdigest() != stub['manifest_sha256']:
            raise fail('no longer matches its stub (manifest sha256 differs)')
        value = json.loads(raw.decode('utf-8-sig'))
    except ArchiveUnreachable:
        raise
    except (OSError, ValueError) as error:
        raise fail('has a manifest that cannot be read (%s)' % str(error)[:200]) from None
    problem = manifest_problem(stub, value)
    if problem:
        if strict:
            raise Refusal('The archive manifest of run folder %s at %s cannot be trusted: %s. Nothing was changed.'
                          % (stub['run_id'], folder, problem), 'ARCHIVE_MANIFEST_INVALID', run_id=stub['run_id'],
                          archive_dir=str(folder))
        raise fail('has a manifest that cannot be trusted (%s)' % problem)
    entries = {_key(entry['relative_path']): entry for entry in value['files']}
    if not strict:
        _MANIFESTS[cache_key] = (stamp, entries)
    return entries


def _verify_file(stub, folder, entry, *, full, cache=True):
    """The archived copy of one manifest entry after checking its size (always) and its sha256 (``full``: once per
    process per path, size and mtime unless ``cache`` is off). Raises ArchiveUnreachable."""
    target = folder / entry['relative_path']
    physical = _io(target)

    def fail(why):
        return ArchiveUnreachable('The archived copy %s of run folder %s %s; nothing is read in its place. Inspect the '
                                  'archive.' % (target, stub['run_id'], why), run_id=stub['run_id'], archive_dir=str(folder),
                                  relative_path=entry['relative_path'])
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
                digest = archive.file_sha256(target)
            except OSError as error:
                raise fail('cannot be read (%s)' % str(error)[:200]) from None
            if digest != entry['sha256']:
                raise fail('differs from its manifest (sha256)')
            _VERIFIED.add(key)
    return target


def locate(path, verify='full'):
    """(where to read ``path``, archived): its archive copy when its run folder's stub says the sources are gone (or
    going), else itself. ``verify='full'`` checks a listed file's size and, once per process, its sha256; ``'size'``
    its size; None nothing. Raises ArchiveUnreachable when the stub or the archive cannot be trusted now."""
    found = run_folder_of(path)
    if found is None:
        return Path(path), False
    run, below = found
    stub = load_stub(run)
    if stub is None or stub['state'] == 'archived':
        return Path(path), False
    if len(below) == 1 and below[0].casefold() == STUB.casefold():
        return Path(path), False
    folder, entries = open_archive(stub)
    if not below:
        return folder, True
    entry = entries.get(_key('/'.join(below)))
    if entry is not None and verify:
        return _verify_file(stub, folder, entry, full=verify == 'full'), True
    return folder.joinpath(*below), True


def resolve(path, verify='full'):
    """``path`` itself, or its archived copy once ``evidence-archive --run-folders --complete`` moved it."""
    return locate(path, verify)[0]


def run_dir(run):
    """The folder to read a native run folder's files from: itself, or its archive folder. A reader that opens a file
    below an archive folder passes it through ``checked`` first, so every file it consumes is verified."""
    return locate(run, None)[0]


def checked(path):
    """``path`` itself, after verifying it when it lies below an archive folder this process opened (run_dir, locate):
    its size against the manifest on every call and its sha256 on its first in a process. A file there that the
    manifest does not list refuses (EVIDENCE_ARCHIVE_UNREACHABLE); a missing one is left for the read to report."""
    if not _OPEN:
        return path
    text = os.path.normcase(os.path.abspath(_plain(str(path))))
    for base, (stub, folder, entries) in _OPEN.items():
        if not text.startswith(base + os.sep):
            continue
        entry = entries.get(_key(text[len(base) + 1:]))
        if entry is not None:
            _verify_file(stub, folder, entry, full=True)
        elif _io(path).is_file():
            raise ArchiveUnreachable('%s lies in the archive of run folder %s but its manifest does not list it; nothing is '
                                     'read from it. Inspect the archive.' % (path, stub['run_id']), run_id=stub['run_id'],
                                     archive_dir=str(folder))
        return path
    return path


def read_bytes(path):
    """The bytes of a file that may lie in an archived run folder (a cited SET, report or export)."""
    physical, moved = locate(path)
    return (_io(physical) if moved else Path(physical)).read_bytes()


def logical(path, physical_base, logical_base):
    """``path`` (found below ``physical_base``, a run folder's archive copy) as the cited path below ``logical_base``."""
    try:
        relative = Path(path).relative_to(physical_base)
    except ValueError:
        return Path(path)
    return Path(logical_base) / relative


# ---------------------------------------------------------------------------
# Ownership and eligibility (read-only)
# ---------------------------------------------------------------------------

def source_root(install):
    """``<Common Files>\\GOAT``: the only folder whose ``R<12 hex>`` children this tool moves."""
    return Path(os.path.abspath(install['common_files_root'])) / 'GOAT'


def installations(root, install):
    """[(controller state, installation)] of this installation and every sibling of the same suite that shares its
    Common Files (read-only). A sibling that cannot be read is listed in ``unreadable``; folders only it could own then
    stay ``not_attributable``."""
    found, unreadable = [(Path(root), install)], []
    common = _norm(install['common_files_root'])
    parent = Path(root).parent
    for folder in sorted(parent.iterdir()) if parent.is_dir() else []:
        if _norm(folder) == _norm(root) or not folder.is_dir() or not (folder / 'installation.json').is_file():
            continue
        try:
            other = archive._bounded_json(folder / 'installation.json', 4 * 1024 * 1024)
        except (OSError, ValueError, UnicodeError) as error:
            unreadable.append(dict(installation=str(folder), reason=str(error)[:200]))
            continue
        if isinstance(other, dict) and isinstance(other.get('common_files_root'), str) and _norm(other['common_files_root']) == common:
            found.append((folder, other))
    return found, unreadable


def _package_run(root, job_id):
    """The run folder ID a package names (``GOAT\\R<12 hex>``), else None."""
    path = Path(root) / 'packages' / job_id / 'manifest.json'
    value = archive._bounded_json(path, MAX_PACKAGE_MANIFEST)
    relative = value.get('native_run_relative') if isinstance(value, dict) else None
    match = RUN_RELATIVE.fullmatch(relative) if isinstance(relative, str) else None
    return match.group(1) if match else None


def owners(installs):
    """({run id: [owner]}, problems): each package of each installation that names a run folder, with its queue rows."""
    found, problems = {}, []
    for root, install in installs:
        try:
            bindings = archive.queue_bindings(root)
        except Exception as error:                      # sqlite3.Error, OSError, ValueError: nothing proven here
            problems.append(dict(installation=str(root), reason='its Studio queue cannot be read (%s)' % str(error)[:200]))
            bindings = None
        rows = {}
        for binding, jobs in bindings or []:
            for job in jobs:
                if isinstance(job.get('job_id'), str):
                    rows.setdefault(job['job_id'], []).append((binding, job))
        packages = Path(root) / 'packages'
        for package in sorted(packages.iterdir()) if packages.is_dir() else []:
            if not package.is_dir() or not (package / 'manifest.json').is_file():
                continue
            try:
                run_id = _package_run(root, package.name)
            except (OSError, ValueError, UnicodeError) as error:
                problems.append(dict(installation=str(root), job_id=package.name,
                                     reason='its package manifest cannot be read (%s)' % str(error)[:200]))
                continue
            if run_id is None:
                continue
            found.setdefault(run_id, []).append(dict(root=Path(root), install=install, job_id=package.name,
                                                     rows=rows.get(package.name, []), queue_readable=bindings is not None,
                                                     jobs=rows))
    return found, problems


def active_pointers(source):
    """{run id: [pointer path]} of every EA ``active_optimization_run.ini`` below ``<Common Files>\\GOAT`` (outside
    the run folders, up to POINTER_DEPTH folders deep). Raises ValueError when one cannot be read."""
    import configparser
    found = {}
    pending = [(Path(source), 0)]
    while pending:
        folder, depth = pending.pop()
        try:
            with os.scandir(folder) as entries:
                children = list(entries)
        except FileNotFoundError:
            continue
        for entry in children:
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                if depth < POINTER_DEPTH and not (depth == 0 and RUN_NAME.fullmatch(entry.name)):
                    pending.append((path, depth + 1))
            elif entry.name.casefold() == POINTER_NAME and entry.is_file(follow_symlinks=False):
                try:
                    raw = path.read_bytes()
                    parser = configparser.ConfigParser(interpolation=None, strict=False)
                    parser.optionxform = str
                    parser.read_string(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
                    run_path = parser['ActiveOptimizationRun'].get('RunPath', '').strip()
                except (OSError, ValueError, KeyError, UnicodeError, configparser.Error) as error:
                    raise ValueError('the EA run pointer %s cannot be read (%s)' % (path, str(error)[:200])) from None
                match = RUN_RELATIVE.fullmatch(run_path)
                if match:
                    found.setdefault(match.group(1), []).append(str(path))
    return found


def _drivers(root):
    """{job id: driver journal} of an installation (read-only; an unreadable journal reads as live)."""
    folder = Path(root) / 'batch-drivers'
    found = {}
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            value = archive._bounded_json(path, 16 * 1024 * 1024)
        except (OSError, ValueError, UnicodeError):
            value = dict(stopped=False, status='unreadable')
        job_id = ((value.get('binding') or {}).get('job_id') if isinstance(value, dict) and isinstance(value.get('binding'), dict)
                  else None) or path.stem
        found[job_id] = value if isinstance(value, dict) else dict(stopped=False, status='unreadable')
    return found


def _lineage(root):
    """{predecessor job id: [successor job id]} from ``batch-lineage`` (read-only)."""
    folder = Path(root) / 'batch-lineage'
    found = {}
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            value = archive._bounded_json(path, 4 * 1024 * 1024)
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get('predecessor_batch_id'), str):
            found.setdefault(value['predecessor_batch_id'], []).append(value.get('batch_id') or path.stem)
    return found


def _cited_paths(manifest):
    """Every SET path a runner manifest cites: members' sources and originals, and the plan's sets."""
    paths = []
    if not isinstance(manifest, dict):
        return paths
    for member in manifest.get('members') or []:
        if not isinstance(member, dict):
            continue
        original = member.get('original') if isinstance(member.get('original'), dict) else {}
        migration = member.get('build_migration') if isinstance(member.get('build_migration'), dict) else {}
        for value in (member.get('source_path'), original.get('set_path'), migration.get('original_path')):
            if isinstance(value, str):
                paths.append(value)
    plan = manifest.get('plan') if isinstance(manifest.get('plan'), dict) else {}
    paths.extend(value for value in plan.get('sets') or [] if isinstance(value, str))
    return paths


def runner_citations(installs):
    """{run id: [citation]} of every seed hunt, catch-up and hold-up test of these installations whose manifest cites a
    path inside a run folder, each with the reader's state. Raises ValueError when a manifest cannot be read."""
    found = {}
    for root, _ in installs:
        for folder, kind in archive.READERS:
            base = Path(root) / folder
            for path in sorted(base.glob('*/manifest.json')) if base.is_dir() else []:
                try:
                    value = archive._bounded_json(path)
                except (OSError, ValueError, UnicodeError) as error:
                    raise ValueError('the %s manifest %s is unreadable (%s)' % (kind, path, str(error)[:200])) from None
                runs = {}
                for cited in _cited_paths(value):
                    hit = run_folder_of(cited)
                    if hit is not None:
                        runs.setdefault(hit[0].name, cited)
                if not runs:
                    continue
                state = archive.runner_state(root, folder, path.parent.name) or 'finished'
                for run_id, cited in runs.items():
                    found.setdefault(run_id, []).append(dict(
                        via=kind, run_id=path.parent.name, installation=Path(root).name, set_path=cited, reader_state=state,
                        in_flight=state != 'finished', plain='cited by %s %s (%s)' % (kind, path.parent.name, state)))
    return found


def active_lock_shas(installs, *, now):
    """{set sha256: lock} of every ACTIVE held-out lock's frozen candidate (each installation's registry, once)."""
    from studio_heldout import ACTIVE as LOCK_ACTIVE, read_registry, registry_path
    found, seen = {}, set()
    for _, install in installs:
        try:
            where = str(registry_path(install))
        except (ValueError, KeyError, TypeError):
            where = None
        if where in seen:
            continue
        seen.add(where)
        registry = read_registry(install, now=now)
        if registry['state'] == 'unavailable':
            raise ValueError('the held-out lock registry cannot be verified (' + str(registry['error']) + ')')
        for lock in registry['locks']:
            active = lock.get('active') if isinstance(lock.get('active'), bool) else lock.get('status') in LOCK_ACTIVE
            if active:
                for cell in lock.get('candidate') or []:
                    if isinstance(cell, dict) and isinstance(cell.get('set_sha256'), str):
                        found[cell['set_sha256']] = lock
    return found


def walk(run):
    """(files, links): every regular file below a run folder as {relative_path, bytes} (the stub excluded), and every
    symbolic link or junction met (never followed)."""
    run = Path(run)
    physical = _io(run)
    files, links = [], []
    pending = [physical]
    while pending:
        current = pending.pop()
        with os.scandir(current) as found:
            children = sorted(found, key=lambda entry: entry.name)
        for entry in children:
            path = Path(entry.path)
            relative = path.relative_to(physical).as_posix()
            if archive._is_link(path):
                links.append(relative)
            elif entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                if relative.casefold() == STUB.casefold():
                    continue
                files.append(dict(relative_path=relative, bytes=entry.stat(follow_symlinks=False).st_size))
    files.sort(key=lambda item: item['relative_path'])
    return files, sorted(links)


def _blocker(code, plain, **fields):
    return dict(code=code, plain=plain, **fields)


def _recorded(owner):
    times = [((job.get('launch_intent') or {}).get('recorded_at') or '') for _, job in owner['rows']
             if isinstance(job.get('launch_intent'), dict)]
    return max(times) if times else ''


def owner_blockers(owner, *, drivers, lineage):
    """Why one owning batch keeps its run folder where it is: not terminal, live driver, continue-able, successor."""
    from studio_batch_pause import load
    job_id, root = owner['job_id'], owner['root']
    found = []
    if not owner['queue_readable']:
        return [_blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'The Studio queue of %s cannot be read, so batch %s cannot be '
                         'proven finished.' % (root.name, job_id), batch_id=job_id)]
    if not owner['rows']:
        return [_blocker('ARCHIVE_OWNER_UNKNOWN', 'Batch %s (installation %s) has a package but no queue row, so it cannot '
                         'be proven finished.' % (job_id, root.name), batch_id=job_id)]
    for _, job in owner['rows']:
        state = archive.native_state_blocker(root, job)
        if state:
            found.append(state)
            break
    driver = drivers.get(job_id)
    if driver is not None and (driver.get('stopped') is not True or driver.get('status') in ('paused', 'pausing', 'pause_failed')):
        found.append(_blocker('ARCHIVE_DRIVER_LIVE', 'The batch driver of %s is %s (stopped=%s); its run folder stays.'
                              % (job_id, driver.get('status'), driver.get('stopped')), batch_id=job_id,
                              driver_status=driver.get('status')))
    successors = set(lineage.get(job_id) or []) | {other for other in owner['jobs']
                                                   if other.startswith(job_id + '-r') and SUCCESSOR.search(other[len(job_id):])}
    live = sorted(other for other in successors
                  if any(job.get('status') not in TERMINAL for _, job in owner['jobs'].get(other) or [dict(status='unknown')]))
    if live:
        found.append(_blocker('ARCHIVE_SUCCESSOR_ACTIVE', 'Successor %s of batch %s is not finished; its predecessor\'s run '
                              'folder stays until it is.' % (live[0], job_id), batch_id=job_id, successors=live))
    try:
        closed = (load(root, job_id) or {}).get('state') == 'closed'
    except (OSError, ValueError, KeyError, TypeError):
        closed = False
    rows = [job for _, job in owner['rows']]
    if not found and not successors and not closed and any(job.get('status') in ('cancelled', 'failed') for job in rows):
        outcomes = [item for job in rows for item in ((job.get('completion') or {}).get('member_outcomes') or [])
                    if isinstance(item, dict)]
        unrun = [item for item in outcomes if item.get('status') in UNRUN_MEMBERS]
        if unrun or not outcomes:
            found.append(_blocker('ARCHIVE_CONTINUABLE', 'Batch %s still has %s never-run member(s) and can be continued; '
                                  'close it with batch-pause-close (or continue it) before its run folder moves.'
                                  % (job_id, len(unrun) if outcomes else 'unknown'), batch_id=job_id,
                                  members_unrun=len(unrun) if outcomes else None))
    return found


def _human(size):
    return archive._human(size)


def plan(root, install, archive_root=None, *, keep=None, keep_last=DEFAULT_KEEP_LAST, run_ids=None,
         floor_bytes=DEFAULT_FLOOR_GB * GB, max_runs=None, now, sizes=True):
    """Read-only plan of ``evidence-archive --run-folders``: every run folder under ``<Common Files>\\GOAT``, eligible or
    with the reasons it stays. Writes nothing (the archive root's writability probe creates and removes one file)."""
    source = source_root(install)
    installs, unreadable = installations(root, install)
    owned, problems = owners(installs)
    drivers = {Path(r).name: _drivers(r) for r, _ in installs}
    lineage = {Path(r).name: _lineage(r) for r, _ in installs}
    global_blockers = []
    try:
        pointers = active_pointers(source)
    except ValueError as error:
        pointers = None
        global_blockers.append(_blocker('ARCHIVE_ACTIVE_UNVERIFIABLE', 'The active run cannot be proven (%s); nothing '
                                        'moves.' % str(error)[:300]))
    try:
        citations = runner_citations(installs)
    except ValueError as error:
        citations = None
        global_blockers.append(_blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'It cannot be proven which runs cite the run '
                                        'folders (%s); nothing moves.' % str(error)[:300]))
    try:
        lock_shas = active_lock_shas(installs, now=now)
    except (ValueError, OSError) as error:
        lock_shas = None
        global_blockers.append(_blocker('ARCHIVE_CITATIONS_UNVERIFIABLE', 'The held-out locks cannot be verified (%s); '
                                        'nothing moves.' % str(error)[:300]))
    keep = list(keep or [])
    keep_names = {item.casefold() for item in keep} | {_norm(item) for item in keep if Path(item).is_absolute()}
    recent = sorted(((max(_recorded(o) for o in group), run_id) for run_id, group in owned.items()), reverse=True)
    recent_ids = {run_id for _, run_id in recent[:max(0, int(keep_last))]}
    wanted = {item for item in run_ids} if run_ids else None
    runs, not_attributable, archived = [], [], []
    try:
        names = sorted(entry.name for entry in os.scandir(source) if entry.is_dir(follow_symlinks=False) and RUN_NAME.fullmatch(entry.name))
    except FileNotFoundError:
        names = []
    for run_id in names:
        if wanted is not None and run_id not in wanted:
            continue
        run = source / run_id
        try:
            stub = load_stub(run)
        except ArchiveUnreachable as error:
            archived.append(dict(run_id=run_id, path=str(run), state='invalid_stub', error=str(error)))
            continue
        if stub is not None:
            archived.append(dict(run_id=run_id, path=str(run), state=stub['state'], archive_dir=stub['archive_dir'],
                                 bytes=stub['bytes'], file_count=stub['file_count']))
            continue
        group = owned.get(run_id)
        if not group:
            not_attributable.append(dict(run_id=run_id, path=str(run),
                                         reason='no package of these installations names this run folder'))
            continue
        blockers = []
        if pointers is not None and run_id in pointers:
            blockers.append(_blocker('ARCHIVE_RUN_ACTIVE', 'The EA\'s active run pointer names %s; it is the active run.'
                                     % run_id, pointers=pointers[run_id]))
        for owner in group:
            blockers.extend(owner_blockers(owner, drivers=drivers[owner['root'].name], lineage=lineage[owner['root'].name]))
        cited = (citations or {}).get(run_id) or []
        readers = [hit for hit in cited if hit['in_flight']]
        if readers:
            blockers.append(_blocker('ARCHIVE_IN_FLIGHT_READER', '%s %s is %s and cites %s; this run folder stays until it '
                                     'finishes.' % (readers[0]['via'], readers[0]['run_id'], readers[0]['reader_state'],
                                                    readers[0]['set_path']), readers=readers[:50]))
        keep_hit = next((item for item in keep if item.casefold() in {run_id.casefold()} | {o['job_id'].casefold() for o in group}
                         or (Path(item).is_absolute() and _norm(item) == _norm(run))), None)
        if keep_hit is not None:
            blockers.append(_blocker('ARCHIVE_KEEP_LISTED', '%s is on the keep-list (%s); it stays.' % (run_id, keep_hit),
                                     keep_entry=keep_hit))
        elif run_id in recent_ids:
            blockers.append(_blocker('ARCHIVE_KEPT_RECENT', '%s is one of the newest %d runs (--keep-last); it stays.'
                                     % (run_id, keep_last), keep_last=keep_last))
        files, links = ([], [])
        if not blockers and (sizes or lock_shas):
            files, links = walk(run)
        if links:
            blockers.append(_blocker('ARCHIVE_SOURCE_LINK', '%s holds a symbolic link or junction (%s); nothing in it moves.'
                                     % (run_id, links[0]), links=links[:50]))
        if not blockers and lock_shas:
            for item in files:
                if item['relative_path'].casefold().startswith('deploy/') and item['relative_path'].casefold().endswith('.set'):
                    digest = archive.file_sha256(run / item['relative_path'])
                    if digest in lock_shas:
                        lock = lock_shas[digest]
                        blockers.append(_blocker('ARCHIVE_HELDOUT_LOCK_ACTIVE', 'Held-out lock %s (%s) freezes %s; it stays '
                                                 'until the lock is revealed.' % (str(lock.get('lock_id'))[:12],
                                                                                  lock.get('status'), item['relative_path']),
                                                 lock_id=lock.get('lock_id')))
                        break
        runs.append(dict(run_id=run_id, path=str(run), owners=[dict(installation=o['root'].name, batch_id=o['job_id'],
                                                                     statuses=sorted({j.get('status') for _, j in o['rows']}))
                                                                for o in group],
                         eligible=not blockers, blockers=blockers, files=files if not blockers else [],
                         file_count=len(files) if not blockers else None,
                         bytes=sum(item['bytes'] for item in files) if not blockers else None,
                         cited_by=[hit['plain'] for hit in cited][:50]))
    eligible = [run for run in runs if run['eligible']]
    if max_runs is not None:
        eligible = eligible[:max(0, int(max_runs))]
    total = sum(run['bytes'] or 0 for run in eligible)
    target, free = None, None
    root_blockers = []
    if archive_root is not None and str(archive_root):
        root_blockers, free, target = target_blockers(source, archive_root, total, floor_bytes, eligible)
    elif archive_root is not None:
        root_blockers.append(_blocker('ARCHIVE_ROOT_INVALID', 'The archive root must be an absolute folder path.'))
    return dict(scope='run_folders', source_root=str(source), archive_root=str(target) if target else None,
                installations=[Path(r).name for r, _ in installs], installations_unreadable=unreadable,
                ownership_problems=problems, eligible=[dict(run, files=run['files']) for run in eligible],
                eligible_count=len(eligible), bytes=total, size=_human(total),
                skipped=[dict(run_id=r['run_id'], owners=r['owners'], codes=[b['code'] for b in r['blockers']],
                              plain=r['blockers'][0]['plain'], cited_by=r['cited_by']) for r in runs if not r['eligible']],
                not_attributable=not_attributable, archived=archived, keep_last=keep_last, keep_list=keep,
                archive_free_bytes=free, floor_bytes=floor_bytes,
                free_after_bytes=None if free is None else free - total,
                blockers=global_blockers + root_blockers, ready=not (global_blockers + root_blockers) and bool(eligible))


def missing_bytes(archive_root, run_id, files):
    """Bytes of ``files`` not yet in ``<archive root>/<run id>/``: what a copy still needs (an interrupted run's
    copies are reused, so they are not needed again)."""
    folder = Path(os.path.abspath(str(archive_root))) / run_id
    return sum(item['bytes'] for item in files if not _io(folder / item['relative_path']).is_file())


def target_blockers(source, archive_root, size, floor_bytes, eligible=()):
    """Archive-root checks: absolute, existing, local NTFS/ReFS, another volume than the run folders, writable, and
    ``floor_bytes`` still free after the copy. Returns (blockers, free bytes, target)."""
    text = str(archive_root or '')
    if not text or not Path(text).is_absolute():
        return [_blocker('ARCHIVE_ROOT_INVALID', 'The archive root must be an absolute folder path.', archive_root=text)], None, None
    target = Path(os.path.abspath(text))
    if not _io(target).is_dir():
        return [_blocker('ARCHIVE_ROOT_UNAVAILABLE', 'The archive root %s is not an existing folder; connect the drive or '
                         'create the folder first.' % target, archive_root=str(target))], None, target
    if _norm(target).startswith(_norm(source) + os.sep) or _norm(target) == _norm(source):
        return [_blocker('ARCHIVE_ROOT_INVALID', 'The archive root %s lies inside the run folders\' own folder.' % target,
                         archive_root=str(target))], None, target
    found = archive.durability_blockers(target)
    if found:
        return found, None, target
    try:
        same = archive.volume_of(target) == archive.volume_of(source)
    except OSError as error:
        return [_blocker('ARCHIVE_ROOT_UNAVAILABLE', 'The archive root cannot be inspected (%s).' % str(error)[:200],
                         archive_root=str(target))], None, target
    if same:
        return [_blocker('ARCHIVE_ROOT_SAME_VOLUME', 'The archive root %s is on the same volume as the run folders; moving '
                         'there frees nothing.' % target, archive_root=str(target))], None, target
    try:
        archive._probe_writable(target)
    except OSError as error:
        return [_blocker('ARCHIVE_ROOT_NOT_WRITABLE', 'The archive root %s is not writable (%s).' % (target, str(error)[:200]),
                         archive_root=str(target))], None, target
    free = shutil.disk_usage(_io(target)).free
    needed = sum(missing_bytes(target, run['run_id'], run.get('files') or []) for run in eligible) if eligible else size
    if free - needed < floor_bytes:
        return [_blocker('ARCHIVE_ROOT_FLOOR', 'The archive root has %s free; copying %s would leave %s, under the %s floor '
                         '(--free-floor-gb). Archive fewer runs (--max-runs / --run-id) or pick a larger drive.'
                         % (_human(free), _human(needed), _human(max(0, free - needed)), _human(floor_bytes)),
                         archive_root=str(target), free_bytes=free, needed_bytes=needed, floor_bytes=floor_bytes)], free, target
    return [], free, target


# ---------------------------------------------------------------------------
# Apply and complete
# ---------------------------------------------------------------------------

def _write_record(path, value):
    archive._write_json_file(path, value)
    _STUBS.pop(os.path.normcase(str(_io(path))), None)


def _archive_walk(folder):
    """Every regular file below an archive folder except its manifest and this tool's temporaries, as {key: path}."""
    physical = _io(folder)
    found = {}
    for current, names, files in os.walk(physical):
        names[:] = [name for name in names if not archive._is_link(Path(current) / name)]
        for name in files:
            if name.endswith(archive.TEMP_MARK):
                continue
            relative = (Path(current) / name).relative_to(physical).as_posix()
            if relative.casefold() == MANIFEST.casefold():
                continue
            found[_key(relative)] = relative
    return found


def apply_run(run, archive_root, files, *, install, now, archived_by='demo_agent', owners_=()):
    """Copy one eligible run folder to ``<archive root>/<run id>/``, verify every file, write the manifest and the stub.
    Removes nothing. A crash before the stub leaves the source untouched; a re-run resumes (identical copies are reused)."""
    run = Path(run)
    run_id = run.name
    stub = load_stub(run)
    if stub is not None:
        raise Refusal('Run folder %s is already archived (%s); --complete removes its sources.' % (run_id, stub['state']),
                      'ARCHIVE_RUN_ARCHIVED', run_id=run_id, state=stub['state'])
    folder = Path(os.path.abspath(str(archive_root))) / run_id
    _io(folder).mkdir(parents=True, exist_ok=True)
    archive._remove_temporaries(folder)
    entries, copied, reused = [], 0, 0
    for item in files:
        digest, size, again = archive.copy_verified(run / item['relative_path'], folder / item['relative_path'])
        if size != item['bytes']:
            raise Refusal('The source %s/%s changed size while it was archived; nothing was removed.' % (run_id, item['relative_path']),
                          'ARCHIVE_SOURCE_CHANGED', run_id=run_id, relative_path=item['relative_path'])
        reused += again
        copied += not again
        entries.append(dict(relative_path=item['relative_path'], bytes=size, sha256=digest))
    # The full file count: the source still holds exactly these files, and so does the archive folder.
    now_files, links = walk(run)
    if links or sorted((f['relative_path'], f['bytes']) for f in now_files) != sorted((e['relative_path'], e['bytes']) for e in entries):
        raise Refusal('Run folder %s changed while it was archived (%d files planned, %d now); nothing was removed and no stub '
                      'was written. Re-run the preview.' % (run_id, len(entries), len(now_files)), 'ARCHIVE_SOURCE_CHANGED',
                      run_id=run_id)
    stray = sorted(set(_archive_walk(folder)) - {_key(e['relative_path']) for e in entries})
    if stray:
        raise Refusal('The archive folder %s holds %d file(s) this run folder does not (first: %s); nothing was removed. '
                      'Inspect it.' % (folder, len(stray), stray[0]), 'ARCHIVE_TARGET_CONFLICT', run_id=run_id, target=str(folder))
    total = sum(entry['bytes'] for entry in entries)
    manifest_path = folder / MANIFEST
    if _io(manifest_path).is_file():
        existing = archive._bounded_json(manifest_path, MAX_MANIFEST_BYTES)
        if not isinstance(existing, dict) or existing.get('run_id') != run_id or not archive._same_files(existing.get('files') or [], entries):
            raise Refusal('A different manifest already exists at %s; nothing was removed. Inspect the archive.' % manifest_path,
                          'ARCHIVE_MANIFEST_CONFLICT', run_id=run_id, manifest=str(manifest_path))
    else:
        _write_record(manifest_path, dict(
            schema=MANIFEST_SCHEMA, schema_version=SCHEMA_VERSION, run_id=run_id, source=str(run),
            archive_dir=str(folder), created_at=_utc(now), created_utc=now, archived_by=archived_by,
            controller_revision=archive.controller_revision(install), owners=list(owners_),
            files=entries, file_count=len(entries), bytes=total,
            plain='Run folder %s copied off the Common Files volume, each file sha256-verified; its sources are removed '
                  'only by evidence-archive --run-folders --complete after every file here is re-verified.' % run_id))
    digest = archive.file_sha256(manifest_path)
    _write_record(stub_path(run), dict(
        schema=STUB_SCHEMA, schema_version=SCHEMA_VERSION, run_id=run_id, state='archived',
        archive_root=str(Path(os.path.abspath(str(archive_root)))), archive_dir=str(folder), manifest=str(manifest_path),
        manifest_sha256=digest, file_count=len(entries), bytes=total, archived_at=_utc(now), archived_by=archived_by,
        owners=list(owners_), controller_revision=archive.controller_revision(install),
        plain='This run folder\'s files live in %s; controller readers follow this file. Do not delete it.' % folder,
        **archive._volume_fields(folder)))
    return dict(run_id=run_id, archive_dir=str(folder), copied=copied, reused=reused, file_count=len(entries), bytes=total,
                manifest_sha256=digest, state='archived', removed=0)


def _remove_source(source, run, path):
    """Remove one verified source file: only a regular file strictly below ``run``, which must be an ``R<12 hex>``
    folder directly below ``source`` (``<Common Files>\\GOAT``); never the stub, never through a link."""
    run_text, target = _norm(run), _norm(path)
    if _norm(Path(run).parent) != _norm(source) or not RUN_NAME.fullmatch(Path(run).name):
        raise Refusal('%s is not a run folder directly below %s; nothing was removed.' % (run, source),
                      'ARCHIVE_ROOT_INVALID', run=str(run))
    if not target.startswith(run_text + os.sep) or Path(target).name.casefold() == STUB.casefold():
        raise Refusal('%s is not a file below run folder %s; nothing was removed.' % (path, run), 'ARCHIVE_ROOT_INVALID',
                      path=str(path))
    if archive.link_below(run, path) is not None:
        raise Refusal('%s lies below a symbolic link or junction; nothing was removed.' % path, 'ARCHIVE_SOURCE_LINK',
                      path=str(path))
    physical = _io(path)
    if not stat_mode.S_ISREG(physical.lstat().st_mode):
        raise Refusal('%s is not a regular file; nothing was removed.' % path, 'ARCHIVE_SOURCE_CHANGED', path=str(path))
    physical.unlink()


def _remove_empty_folders(run):
    """Remove the folders below ``run`` the removed files left empty (never ``run`` itself, never through a link)."""
    physical = _io(run)
    folders = []
    for current, names, _ in os.walk(physical):
        names[:] = [name for name in names if not archive._is_link(Path(current) / name)]
        if Path(current) != physical:
            folders.append(Path(current))
    for path in sorted(folders, key=lambda p: len(str(p)), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def complete_run(source, run, *, now, completed_by='demo_agent'):
    """Remove an archived run folder's sources (``--complete``), leaving ARCHIVED.json.

    The manifest must hash to the stub's; EVERY archived file is re-read and re-hashed from disk (no cache) and the
    archive folder must hold exactly the manifest's files; every present source must be listed and hash to it. Any
    mismatch refuses with nothing removed. Then the stub turns ``removing``, the sources go, and it turns ``removed``.
    """
    run = Path(run)
    stub = load_stub(run)
    if stub is None:
        raise Refusal('Run folder %s has no ARCHIVED.json; run --apply first. Nothing was removed.' % run.name,
                      'ARCHIVE_NOT_ARCHIVED', run_id=run.name)
    folder, entries = open_archive(stub, strict=True)
    for entry in entries.values():
        try:
            _verify_file(stub, folder, entry, full=True, cache=False)
        except ArchiveUnreachable as error:
            raise Refusal('%s Every source is kept; nothing was removed.' % error, 'ARCHIVE_VERIFY_FAILED', run_id=run.name,
                          relative_path=entry['relative_path'], archive_dir=str(folder)) from None
    held = _archive_walk(folder)
    if set(held) != set(entries):
        extra = sorted(set(held) ^ set(entries))
        raise Refusal('The archive folder %s holds %d files; its manifest lists %d (first difference: %s). Every source is '
                      'kept; nothing was removed.' % (folder, len(held), len(entries), extra[0]), 'ARCHIVE_VERIFY_FAILED',
                      run_id=run.name, archive_dir=str(folder))
    present, links = walk(run)
    if links:
        raise Refusal('Run folder %s holds a symbolic link or junction (%s); nothing was removed.' % (run.name, links[0]),
                      'ARCHIVE_SOURCE_LINK', run_id=run.name, links=links[:50])
    sources, changed = [], []
    for item in present:
        entry = entries.get(_key(item['relative_path']))
        path = run / item['relative_path']
        before = _io(path).stat()
        if entry is None or before.st_size != entry['bytes'] or archive.file_sha256(path) != entry['sha256']:
            changed.append(item['relative_path'])
            continue
        after = _io(path).stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            changed.append(item['relative_path'])
        else:
            sources.append((path, after.st_size, after.st_mtime_ns))
    if changed:
        raise Refusal('%d source file(s) of run folder %s are not the archived ones (first: %s); nothing was removed. Inspect '
                      'them.' % (len(changed), run.name, changed[0]), 'ARCHIVE_SOURCE_CHANGED', run_id=run.name,
                      relative_path=changed[0], relative_paths=changed[:50])
    if stub['state'] != 'removed' and (sources or stub['state'] == 'archived'):
        _write_record(stub_path(run), dict(stub, state='removing', removing_at=_utc(now), removing_by=completed_by))
    removed = 0
    for path, size, mtime in sources:
        current = _io(path).stat()
        if (current.st_size, current.st_mtime_ns) != (size, mtime):
            raise Refusal('The source %s changed while the archive was being completed; it is kept (%d removed before it). '
                          'Inspect it, then re-run --complete.' % (path, removed), 'ARCHIVE_SOURCE_CHANGED', run_id=run.name,
                          removed=removed)
        _remove_source(source, run, path)
        removed += 1
    _remove_empty_folders(run)
    stub = load_stub(run)
    if stub['state'] != 'removed':
        _write_record(stub_path(run), dict(stub, state='removed', removed_at=_utc(now), removed_by=completed_by))
    return dict(run_id=run.name, archive_dir=str(folder), state='removed', removed=removed, verified=len(entries),
                file_count=len(entries), bytes=sum(entry['bytes'] for entry in entries.values()),
                manifest_sha256=stub['manifest_sha256'])


def public(value, applied=False):
    """The preview/result for a reply: at most MAX_PUBLIC rows per list; eligible runs without their file lists."""
    result = dict(value, applied=applied)
    result['eligible'] = [{k: v for k, v in run.items() if k != 'files'} for run in value.get('eligible') or []][:MAX_PUBLIC]
    for key in ('skipped', 'not_attributable', 'archived'):
        rows = result.get(key) or []
        result[key] = rows[:MAX_PUBLIC]
        result[key + '_omitted'] = max(0, len(rows) - MAX_PUBLIC)
    return result


class ArchiverLock:
    """This scope's own lock, in the run folders' own folder (``<Common Files>\\GOAT\\.run-folder-archive.lock``), so
    every installation sharing these Common Files takes the same one: one archiver at a time per PC, without holding
    the terminal lease through a long copy. Taken without waiting; busy refuses."""

    def __init__(self, install):
        self.path = source_root(install) / LOCK_NAME
        self.handle = None

    def __enter__(self):
        from studio_terminal_lease import _try_lock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, 'a+b')
        if not _try_lock(handle):
            handle.close()
            raise Refusal('Another evidence-archive --run-folders is running on this installation; nothing was changed.',
                          'ARCHIVE_ARCHIVER_BUSY', lock=str(self.path))
        self.handle = handle
        return self

    def __exit__(self, *exc):
        from studio_terminal_lease import _unlock
        try:
            _unlock(self.handle)
        finally:
            self.handle.close()
        return False
