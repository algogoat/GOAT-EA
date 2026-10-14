"""Keep the controller's ``studio.sqlite`` from holding gigabytes of free pages (beta.38).

Why (Banker, 2026-10-14): ``studio.sqlite`` was 11.4 GB with 98.8% free pages
(page_count 2,789,912, freelist_count 2,756,749; ~136 MB live). Before
3e00695 every queue command's receipt embedded the whole queue
(``studio_command_store.submit``, ``state=state``), and before 5937f41
reconcile appended every native observation to ``native_evidence_history``
inside that queue row. The queue reached 818 MB, so each batch start wrote two
full copies (enqueue + reserve receipts, ~1.6 GB) and 64 receipts held
9.96 GB. ``compact-evidence`` (818 MB -> 89 MB queue) and ``compact-receipts``
(9.96 GB -> 29 kB of receipts) fixed the rows on 2026-10-03, but SQLite keeps
freed pages in the file until a VACUUM, and the store was created with
``auto_vacuum=NONE``. Testers' stores were created the same way.

What this module does:

* ``StudioStore`` creates every NEW database with ``auto_vacuum=INCREMENTAL``
  (``enable_incremental``); the setting only takes effect before the first table.
* ``reclaim`` runs a bounded ``PRAGMA incremental_vacuum`` (``PAGES_PER_STEP``
  pages per statement, ``MAX_SECONDS`` in all, a short busy timeout) when the
  freelist is over ``FREE_RATIO`` of the pages AND over ``FREE_BYTES``.
  ``after_batch`` calls it where the batch driver has verified its batch's
  finish (terminal lease held, no member in flight) and never raises.
* An existing database (``auto_vacuum=NONE``) is offered a one-time
  ``compact``: ``VACUUM INTO`` a temp file beside the database (with
  ``auto_vacuum=INCREMENTAL``), verify (integrity_check, schema, user_version,
  application_id, page_size, encoding, per-table row counts and content
  hashes), a free-space precheck, refusals for a busy lane or a held database,
  then a verified swap that keeps the original as
  ``studio.sqlite.pre-vacuum-<ts>`` (+ a ``.json`` sidecar) until the next
  successful batch start (``retire_pre_vacuum``). Never an in-place VACUUM:
  that needs temp space the size of the whole file.

``facts`` is the read-only view research-status shows (``controller_db``).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

from studio_refusal import Refusal

FREE_RATIO = 0.25                 # freelist share of the file that triggers a reclaim / the compaction offer
FREE_BYTES = 256 * 1024 * 1024    # ...and at least this many free bytes
PAGES_PER_STEP = 2048             # one incremental_vacuum statement (8 MiB at 4 KiB pages)
MAX_SECONDS = 2.0                 # a reclaim never spends longer than this at one idle point
BUSY_MS = 250                     # a reclaim waits at most this long for another writer
SPACE_MARGIN = 0.10               # compact: free space needed = live bytes * (1 + margin) + SPACE_RESERVE
SPACE_RESERVE = 256 * 1024 * 1024
INCREMENTAL = 2
ACTIVE = ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
LOG = 'studio-db-maintenance.jsonl'
ASIDE = '.pre-vacuum-'
SIDECAR_SCHEMA = 'goat-studio-db-pre-vacuum-v1'
_STAMP = re.compile(r'\d{8}T\d{6}Z(-\d+)?')

CODES = ('DB_COMPACT_CONFIRM_REQUIRED', 'DB_COMPACT_LANE_BUSY', 'DB_COMPACT_DB_HELD', 'DB_COMPACT_LOW_SPACE',
         'DB_COMPACT_MISMATCH', 'DB_COMPACT_NOT_NEEDED', 'DB_COMPACT_ORIGINAL_KEPT', 'DB_COMPACT_MISSING',
         'DB_COMPACT_SWAP_FAILED')


# ------------------------------------------------------------------ facts

def over_threshold(page_size, page_count, freelist):
    """True when the free pages are over FREE_RATIO of the file AND over FREE_BYTES."""
    if not page_count:
        return False
    return freelist / page_count > FREE_RATIO and freelist * page_size > FREE_BYTES


def _pragmas(db):
    value = {key: db.execute('PRAGMA ' + key).fetchone()[0]
             for key in ('page_size', 'page_count', 'freelist_count', 'auto_vacuum', 'journal_mode')}
    value['free_bytes'] = value['freelist_count'] * value['page_size']
    value['live_bytes'] = (value['page_count'] - value['freelist_count']) * value['page_size']
    return value


def _ro(path, timeout=1):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=timeout, isolation_level=None)
    db.execute('PRAGMA query_only=1')
    return db


def kept_originals(path):
    """The originals a ``compact`` kept beside the database (its sidecars), oldest first."""
    path = Path(path)
    kept = []
    for sidecar in sorted(path.parent.glob(path.name + ASIDE + '*.json')):
        try:
            record = json.loads(sidecar.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get('schema') != SIDECAR_SCHEMA:
            continue
        aside = sidecar.with_name(sidecar.name[:-len('.json')])
        kept.append(dict(path=str(aside), sidecar=str(sidecar), exists=aside.is_file(), phase=record.get('phase', 'kept'),
                         bytes=aside.stat().st_size if aside.is_file() else None, compacted_at=record.get('at')))
    return kept


SWAP_STALE_SECONDS = 600          # a heartbeat older than this, with a dead (or PID-reused) owner, is a stopped swap
_ACTIVE_SWAPS = set()             # nonces of swaps this process is running now


def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, kernel


def _process_identity(pid):
    """(alive, creation_time) of a PID; creation_time is None where the platform does not say. Never signals it."""
    if type(pid) is not int or pid <= 0:
        return False, None
    if os.name == 'nt':
        ctypes, wintypes, kernel = _kernel()
        handle = kernel.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5, None        # access denied: it exists, identity unknown
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:   # STILL_ACTIVE
                return False, None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                return True, None
            return True, (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)                                      # POSIX: signal 0 only checks
    except ProcessLookupError:
        return False, None
    except PermissionError:
        return True, None
    try:
        return True, int(Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return True, None


def _pid_alive(pid):
    return _process_identity(pid)[0]


def _owner_running(owner):
    """The swap's owner process is still the same running process (same PID and creation time)."""
    if owner.get('pid') == os.getpid():
        return owner.get('nonce') in _ACTIVE_SWAPS          # this process: exactly while the swap runs
    alive, started = _process_identity(owner.get('pid'))
    if not alive:
        return False
    return started is None or owner.get('started') is None or started == owner.get('started')


def _swap_in_progress(sidecar, record):
    """Whether a ``swapping`` record may still have a working owner, so nobody else may touch the files.

    Its owner refreshes the record's mtime (the heartbeat) at every swap phase. Another process takes the
    swap over only when the heartbeat is older than SWAP_STALE_SECONDS AND the owner is dead or its PID now
    names another process (creation time differs). This process's own swap is known exactly (its nonce).
    """
    owner = record.get('owner')
    if not isinstance(owner, dict):
        return False
    if owner.get('pid') == os.getpid():
        return owner.get('nonce') in _ACTIVE_SWAPS
    try:
        fresh = time.time() - sidecar.stat().st_mtime <= SWAP_STALE_SECONDS
    except OSError:
        return False
    return fresh or _owner_running(owner)


def _heartbeat(sidecar):
    """The swap owner is still working: refresh the record's mtime. False when the record is gone (taken over)."""
    try:
        os.utime(sidecar)
        return True
    except OSError:
        return False


def _rejected_name(path, stamp):
    candidate, n = path.with_name(path.name + '.compact-rejected-' + stamp), 1
    while candidate.exists():
        candidate, n = path.with_name(path.name + '.compact-rejected-' + stamp + '-' + str(n)), n + 1
    return candidate


def _put_back(path, aside, stamp):
    """Move whatever sits at ``path`` (a placed copy, or a database something created in the swap gap) to
    ``.compact-rejected-<stamp>`` and the original back from ``aside``. Returns the rejected path or None."""
    rejected = None
    if aside.exists():
        if path.exists():
            rejected = _rejected_name(path, stamp)
            os.rename(path, rejected)
        os.rename(aside, path)
    return rejected


def _swapping_records(path):
    path = Path(path)
    for sidecar in sorted(path.parent.glob(path.name + ASIDE + '*.json')):
        try:
            record = json.loads(sidecar.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get('schema') == SIDECAR_SCHEMA and record.get('phase') == 'swapping':
            yield sidecar, record


def _in_progress_refusal(sidecar):
    return Refusal('A studio.sqlite compaction is swapping files right now, so the database was not opened. Retry in '
                   'a few seconds; if the compacting process hung or its PID was reused, this clears by itself within '
                   + str(SWAP_STALE_SECONDS // 60) + ' minutes of its last heartbeat.', 'DB_COMPACT_IN_PROGRESS',
                   sidecar=str(sidecar))


def recover_interrupted(path):
    """Undo a compaction that a stop interrupted mid-swap (its sidecar still says ``swapping``).

    Until the sidecar says ``kept`` the original is the truth. If it is still aside, it goes back to
    ``studio.sqlite`` (whatever is there, a placed copy or a database something created in the swap gap,
    moves to ``.compact-rejected-<stamp>``, never deleted) and is proven back against the pre-swap snapshot
    the record carries. If no aside is left the original never moved, or was already put back, and is in
    place. Then the temp copy is removed and the record retired. Every opener of the database runs this
    first (StudioStore, connect_existing), so an interruption can never leave the controller to open, or
    create, a database in place of its data, or to write into a copy a swap may still reject.

    A swap that may still have a working owner refuses (DB_COMPACT_IN_PROGRESS) rather than racing it; so
    does an original that cannot be proven back (DB_COMPACT_RECOVERY_REQUIRED). Either way the caller must
    not open the database. An I/O error raises too.
    """
    path = Path(path)
    recovered = []
    for sidecar, record in list(_swapping_records(path)):
        aside = sidecar.with_name(sidecar.name[:-len('.json')])
        if _swap_in_progress(sidecar, record):
            raise _in_progress_refusal(sidecar)
        moved = aside.exists()
        rejected = _put_back(path, aside, aside.name[len(path.name + ASIDE):])
        proven = path.is_file() and not aside.exists()
        if proven and moved:
            identity = record.get('identity')
            if isinstance(identity, dict):
                try:
                    with _closing(_ro(path)) as back:
                        proven = not differences(identity, snapshot(back, integrity=False))
                except sqlite3.Error:
                    proven = False
            else:
                size = record.get('original_bytes')
                proven = type(size) is not int or path.stat().st_size == size
        if not proven:
            raise Refusal('An interrupted studio.sqlite compaction left the original at ' + str(aside) + ' and it could '
                          'not be proven back at ' + str(path) + '; nothing was opened. Inspect ' + str(sidecar) + '.',
                          'DB_COMPACT_RECOVERY_REQUIRED', sidecar=str(sidecar))
        copy = Path(str(record.get('copy') or ''))
        if copy.name.startswith(path.name + '.compact-') and copy.name.endswith('.tmp') and copy.parent == path.parent:
            copy.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        recovered.append(dict(original_restored=str(path), from_aside=str(aside) if moved else None,
                              rejected_copy=str(rejected) if rejected else None))
    if recovered:
        _log(path.parent, dict(operation='recover_interrupted_compaction', recovered=recovered))
    return recovered


def connect_existing(path, *, timeout=1):
    """A read-write connection to an EXISTING database (``mode=rw``, never creates it).

    Runs ``recover_interrupted`` first, so it refuses DB_COMPACT_IN_PROGRESS while a compaction swap may
    still be working (it never opens a placed copy the swap could still reject, so no write is lost there)
    and puts the original back after an interrupted one. A missing database refuses CONTROLLER_DB_MISSING
    with a plain sentence instead of creating an empty one or surfacing a raw I/O error.
    """
    path = Path(path)
    recover_interrupted(path)
    if not path.is_file():
        raise Refusal('The controller database ' + str(path) + ' is missing, so nothing was opened or created. '
                      'If a compaction was interrupted, its original is kept beside it as ' + path.name + ASIDE
                      + '<stamp>.', 'CONTROLLER_DB_MISSING', path=str(path))
    try:
        return sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=timeout, isolation_level=None)
    except sqlite3.OperationalError as error:
        if not path.is_file():
            raise Refusal('The controller database ' + str(path) + ' disappeared while it was being opened; nothing '
                          'was created.', 'CONTROLLER_DB_MISSING', path=str(path)) from None
        raise error


def facts(path):
    """Read-only: size, free pages, auto_vacuum and what GOAT offers. Never raises (``error`` instead)."""
    path = Path(path)
    try:
        if not path.is_file():
            return dict(path=str(path), exists=False)
        with _closing(_ro(path)) as db:
            value = _pragmas(db)
        value.update(path=str(path), exists=True, file_bytes=path.stat().st_size)
        over = over_threshold(value['page_size'], value['page_count'], value['freelist_count'])
        incremental = value['auto_vacuum'] == INCREMENTAL
        value['reclaim_due'] = bool(over and incremental)
        value['compaction_offered'] = bool(over and not incremental)
        value['kept_originals'] = kept_originals(path)
        if value['compaction_offered']:
            value['plain'] = (f"The controller database holds {value['free_bytes'] / 2**30:.1f} GB of free space. "
                              "Run studio-db-compact --apply --confirm while no batch is running to give it back.")
        return value
    except (OSError, sqlite3.Error, ValueError) as error:
        return dict(path=str(path), error=str(error)[:240])


class _closing:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        self.db.close()


# ------------------------------------------------------------------ new databases

def enable_incremental(db):
    """Make a NEW (empty) database incremental. Must run before the first CREATE TABLE; no effect otherwise."""
    if db.execute('PRAGMA page_count').fetchone()[0] == 0:
        db.execute('PRAGMA auto_vacuum=INCREMENTAL')
        return True
    return False


# ------------------------------------------------------------------ queue row writes

def write_queue(db, binding, raw, *, create=False):
    """Replace one ``studio_queues`` row without growing the file; returns the rows written (0 or 1).

    An ``UPDATE`` of a large row whose size changes builds the new overflow chain BEFORE it frees the
    old one, so a store with no free pages grows by one whole queue copy (Banker 2026-10-14: 136 MB ->
    272 MB at round 3 member 1's finish, a reconcile write; flat afterwards because later writes reuse
    that copy's pages). Deleting the row first, then inserting it in the same savepoint, puts the old
    chain on the freelist before the new one is allocated, so the new copy reuses those pages.

    Same semantics as the UPDATE of ``jobs`` by binding it replaces (no row: nothing written), or as an
    insert-or-replace with ``create``. Atomic inside or outside the caller's transaction.
    """
    db.execute('SAVEPOINT goat_queue_write')
    try:
        # A connection stand-in without a cursor (timing fixtures) counts as "row present".
        deleted = getattr(db.execute('DELETE FROM studio_queues WHERE binding=?', (binding,)), 'rowcount', -1)
        if deleted or create:
            db.execute('INSERT INTO studio_queues(binding,jobs) VALUES(?,?)', (binding, raw))
        db.execute('RELEASE goat_queue_write')
    except BaseException:
        try:
            db.execute('ROLLBACK TO goat_queue_write')
            db.execute('RELEASE goat_queue_write')
        except sqlite3.OperationalError:
            pass    # SQLite already rolled the whole transaction back (FULL/IOERR): the original error is the news
        raise
    return 1 if (deleted or create) else 0


# ------------------------------------------------------------------ idle reclaim

def queue_busy(db):
    """Why the queue is not idle (a job starting/running, or pending with a launch intent), or None. Parsed in SQLite."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'studio_queues' not in tables:
        return None
    marks = ','.join('?' * len(ACTIVE))
    rows = db.execute(
        "SELECT json_extract(j.value,'$.job_id') FROM studio_queues q, json_each(q.jobs) j "
        "WHERE json_extract(j.value,'$.status') IN (" + marks + ") OR "
        "(json_extract(j.value,'$.status')='pending' AND json_type(j.value,'$.launch_intent') IS NOT NULL)",
        ACTIVE).fetchall()
    if rows:
        return 'batch ' + ', '.join(str(row[0]) for row in rows) + ' is starting or running'
    if 'studio_fixed_tasks' in tables and db.execute('SELECT 1 FROM studio_fixed_tasks WHERE released=0').fetchone():
        return 'a fixed task still owns this controller'
    return None


def _seed_busy(root):
    try:
        slot = json.loads((Path(root) / 'seed-active.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return 'the seed slot cannot be read'
    if isinstance(slot, dict) and slot.get('status') == 'active':
        return 'the seed slot is held by ' + str(slot.get('batch_id'))
    return None


def reclaim(db, *, pages_per_step=PAGES_PER_STEP, max_seconds=MAX_SECONDS, busy_ms=BUSY_MS, force=False,
            clock=time.monotonic):
    """Bounded ``incremental_vacuum`` on an open autocommit connection; returns what it did, never raises.

    Runs only on an INCREMENTAL database, outside a transaction, and (unless ``force``) only when
    ``over_threshold``. Each statement frees at most ``pages_per_step`` pages; it stops after
    ``max_seconds``, when the freelist is empty, or when another writer holds the database for longer
    than ``busy_ms`` (SQLITE_BUSY), so a reclaim never stalls the controller.
    """
    try:
        before = _pragmas(db)
    except sqlite3.Error as error:
        return dict(ran=False, reason='unreadable', error=str(error)[:240])
    result = dict(ran=False, auto_vacuum=before['auto_vacuum'], page_size=before['page_size'],
                  page_count_before=before['page_count'], freelist_before=before['freelist_count'])
    if before['auto_vacuum'] != INCREMENTAL:
        return dict(result, reason='auto_vacuum_not_incremental')
    if db.in_transaction:
        return dict(result, reason='in_transaction')
    if not force and not over_threshold(before['page_size'], before['page_count'], before['freelist_count']):
        return dict(result, reason='below_threshold')
    previous = db.execute('PRAGMA busy_timeout').fetchone()[0]
    spill = db.execute('PRAGMA cache_spill').fetchone()[0]
    start, steps, stopped = clock(), 0, 'freelist_empty'
    try:
        db.execute('PRAGMA busy_timeout=' + str(int(busy_ms)))
        # No cache spill (Claude-Mac D2 on #239): a step larger than the page cache would spill mid-statement, each
        # spill needs EXCLUSIVE and waits busy_ms behind any reader, and SQLite keeps going after a busy spill, so one
        # step could hold RESERVED+PENDING for minutes (453 s measured) and lock new readers out. Without spilling,
        # the step's only exclusive wait is its commit: at most busy_ms, then SQLITE_BUSY and the step is undone.
        db.execute('PRAGMA cache_spill=0')
        free = before['freelist_count']
        while free > 0:
            if clock() - start >= max_seconds:
                stopped = 'time_budget'
                break
            try:
                db.execute('PRAGMA incremental_vacuum(' + str(int(pages_per_step)) + ')').fetchall()
            except sqlite3.OperationalError as error:
                stopped = 'busy' if 'locked' in str(error) or 'busy' in str(error) else 'error: ' + str(error)[:200]
                break
            steps += 1
            free = db.execute('PRAGMA freelist_count').fetchone()[0]
    finally:
        if db.in_transaction:
            db.execute('ROLLBACK')
        db.execute('PRAGMA cache_spill=' + str(int(spill)))
        db.execute('PRAGMA busy_timeout=' + str(int(previous)))
    after = _pragmas(db)
    return dict(result, ran=steps > 0, reason=stopped, steps=steps, seconds=round(clock() - start, 3),
                page_count_after=after['page_count'], freelist_after=after['freelist_count'],
                freed_bytes=(before['page_count'] - after['page_count']) * before['page_size'])


def _log(root, record):
    try:
        line = json.dumps(dict(record, at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), sort_keys=True,
                          separators=(',', ':'), default=str) + '\n'
        with (Path(root) / LOG).open('a', encoding='utf-8', newline='\n') as output:
            output.write(line)
            output.flush(); os.fsync(output.fileno())
    except OSError:
        pass


def after_batch(controller, **options):
    """The batch driver's idle point (its batch's finish verified, terminal lease held). Never raises.

    Reclaims free pages of an INCREMENTAL store within the bounds of ``reclaim``; on a legacy store
    over the thresholds it records that a one-time ``compact`` is offered (research-status shows it).
    """
    try:
        store = getattr(controller, 'store', None)
        db = getattr(store, 'db', None)
        if db is None:
            return dict(ran=False, reason='no_store')
        busy = queue_busy(db) or _seed_busy(controller.root)
        if busy:
            result = dict(ran=False, reason='busy', busy=busy)
        else:
            result = reclaim(db, **options)
        if result.get('reason') == 'auto_vacuum_not_incremental':
            page = _pragmas(db)
            result['compaction_offered'] = over_threshold(page['page_size'], page['page_count'], page['freelist_count'])
        if result.get('ran') or result.get('compaction_offered') or result.get('reason') == 'busy':
            _log(controller.root, dict(operation='idle_reclaim', **result))
        return result
    except Exception as error:   # maintenance never changes a batch's outcome
        return dict(ran=False, reason='error', error=str(error)[:240])


# ------------------------------------------------------------------ one-time compaction

def _table_hash(db, name):
    """Row count and content hash of one table. A rowid table hashes its rowid too: VACUUM may renumber the rowids
    of a table without an INTEGER PRIMARY KEY, and the controller orders and locates receipts by rowid
    (studio_receipt_digest, campaign_ledger), so a renumbered rowid must fail verification (Claude-Mac 6159866967)."""
    quoted = '"' + name.replace('"', '""') + '"'
    sql = db.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table', name)).fetchone()[0] or ''
    if 'WITHOUT ROWID' in sql.upper():
        columns = ','.join('"' + row[1].replace('"', '""') + '"' for row in db.execute('PRAGMA table_info(' + quoted + ')'))
        query = 'SELECT * FROM ' + quoted + ' ORDER BY ' + columns
    else:
        query = 'SELECT rowid,* FROM ' + quoted + ' ORDER BY rowid'
    digest, count = hashlib.sha256(), 0
    for row in db.execute(query):
        digest.update(json.dumps([v.hex() if isinstance(v, bytes) else v for v in row], ensure_ascii=False,
                                 separators=(',', ':')).encode('utf-8'))
        digest.update(b'\n')
        count += 1
    return dict(rows=count, sha256=digest.hexdigest())


def snapshot(db, *, integrity=True):
    """Everything the swap must keep: identity pragmas, schema, per-table rows + content hash, integrity."""
    schema = [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    value = dict(user_version=db.execute('PRAGMA user_version').fetchone()[0],
                 application_id=db.execute('PRAGMA application_id').fetchone()[0],
                 page_size=db.execute('PRAGMA page_size').fetchone()[0],
                 encoding=db.execute('PRAGMA encoding').fetchone()[0],
                 schema_sha256=hashlib.sha256(json.dumps(schema).encode('utf-8')).hexdigest(),
                 tables={name: _table_hash(db, name) for (name,) in db.execute(
                     "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()})
    if integrity:
        value['integrity_check'] = [row[0] for row in db.execute('PRAGMA integrity_check')]
    return value


IDENTITY = ('user_version', 'application_id', 'page_size', 'encoding', 'schema_sha256', 'tables')


def differences(a, b):
    """The identity fields that differ, plus any integrity_check that is not ['ok']."""
    found = [key for key in IDENTITY if a.get(key) != b.get(key)]
    for side, snap in (('original', a), ('copy', b)):
        if 'integrity_check' in snap and snap['integrity_check'] != ['ok']:
            found.append('integrity_' + side)
    return found


def _held(path):
    """Why the database file is held by someone else right now, or None (journal/WAL present, or a lock)."""
    for suffix in ('-journal', '-wal'):
        extra = Path(str(path) + suffix)
        if extra.exists() and (suffix == '-journal' or extra.stat().st_size):
            return 'a ' + suffix[1:] + ' file is present (another connection is writing or crashed mid-write)'
    probe = connect_existing(path, timeout=0)
    try:
        probe.execute('BEGIN EXCLUSIVE')
        probe.execute('ROLLBACK')
    except sqlite3.OperationalError as error:
        return 'another connection is using it (' + str(error) + ')'
    finally:
        probe.close()
    return None


def _native_gate_root(path):
    try:
        with _closing(_ro(path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            row = db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone() if 'studio_native_gate' in tables else None
    except sqlite3.Error:
        return None
    return Path(row[0]) if row else None


def _place(source, target):
    """Move ``source`` to ``target`` without ever replacing an existing ``target``."""
    if os.name == 'nt':
        os.rename(source, target)          # never overwrites on Windows
    else:
        os.link(source, target)            # fails if target exists
        os.unlink(source)


def _stamp(now):
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))


def _write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, sort_keys=True, indent=1, default=str)
        output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)


def compact(path, *, busy=None, apply=False, now=None, disk_free=None, gate=None):
    """One-time compaction of a legacy (auto_vacuum NONE) store. Preview unless ``apply``.

    ``busy`` is the caller's reason the lane is not idle (checked under its terminal lease), or None.
    ``apply`` refuses with a Refusal and changes nothing when: the lane is busy or a batch is starting
    or running (DB_COMPACT_LANE_BUSY); the store is already incremental and so reclaims itself, or has
    too little free space to be worth it (DB_COMPACT_NOT_NEEDED); an earlier original is still kept
    (DB_COMPACT_ORIGINAL_KEPT); another connection holds the file, a journal/WAL is present, or Windows
    refuses the rename (DB_COMPACT_DB_HELD); the volume has less free space than the live data plus
    margin (DB_COMPACT_LOW_SPACE); the copy differs in any checked way (DB_COMPACT_MISMATCH).
    """
    path = Path(path)
    if apply:
        recover_interrupted(path)       # a preview never moves files
    if not path.is_file():
        raise Refusal('No controller database at ' + str(path) + '; nothing to compact.', 'DB_COMPACT_MISSING')
    now = time.time() if now is None else now
    disk_free = disk_free or (lambda folder: shutil.disk_usage(folder).free)
    info = facts(path)
    if 'error' in info:
        raise Refusal('The controller database cannot be read (' + info['error'] + '); nothing was changed.',
                      'DB_COMPACT_DB_HELD')
    need = int(info['live_bytes'] * (1 + SPACE_MARGIN)) + SPACE_RESERVE
    free = disk_free(path.parent)
    kept = [item for item in info['kept_originals'] if item['exists']]
    blockers = []
    if busy:
        blockers.append(('DB_COMPACT_LANE_BUSY', 'This terminal is not idle: ' + str(busy) + '.'))
    if info['auto_vacuum'] == INCREMENTAL:
        blockers.append(('DB_COMPACT_NOT_NEEDED', 'The controller database is already incremental; GOAT gives its '
                         'free space back after each batch.'))
    elif info['freelist_count'] == 0:
        blockers.append(('DB_COMPACT_NOT_NEEDED', 'The controller database has no free pages to give back.'))
    if kept:
        blockers.append(('DB_COMPACT_ORIGINAL_KEPT', 'The original from the last compaction is still kept at '
                         + kept[0]['path'] + '; it is removed after the next successful batch start.'))
    if free < need:
        blockers.append(('DB_COMPACT_LOW_SPACE', f'The compacted copy needs {need / 2**30:.2f} GB free beside the '
                         f'database; the volume has {free / 2**30:.2f} GB.'))
    plan = dict(path=str(path), file_bytes=info['file_bytes'], live_bytes=info['live_bytes'],
                free_bytes=info['free_bytes'], page_size=info['page_size'], auto_vacuum=info['auto_vacuum'],
                compaction_offered=info['compaction_offered'], space_needed_bytes=need, space_free_bytes=free,
                blockers=[dict(code=code, plain=plain) for code, plain in blockers])
    if not apply:
        return dict(plan, applied=False,
                    next_action=('studio-db-compact --apply --confirm' if not blockers else blockers[0][1]))
    if blockers:
        code, plain = blockers[0]
        raise Refusal(plain + ' Nothing was changed.', code, blockers=plan['blockers'])
    stamp = _stamp(now)
    temporary = path.with_name(path.name + '.compact-' + stamp + '.tmp')
    aside = path.with_name(path.name + ASIDE + stamp)
    sidecar = aside.with_name(aside.name + '.json')
    for candidate in (temporary, aside, sidecar):
        if candidate.exists():
            raise Refusal(str(candidate) + ' already exists; nothing was changed.', 'DB_COMPACT_ORIGINAL_KEPT')
    if gate is None:
        root = _native_gate_root(path)
        if root is not None:
            from studio_native_gate import exclusive_gate
            gate = exclusive_gate(root)
    started = time.monotonic()
    from contextlib import nullcontext
    try:
        gate_scope = gate or nullcontext()
        gate_scope.__enter__()
    except Exception as error:
        raise Refusal('The controller gate is held by another operation (' + str(error)[:200] + '); nothing was changed.',
                      'DB_COMPACT_DB_HELD') from None
    try:
        held = _held(path)
        if held:
            raise Refusal('The controller database is held: ' + held + '. Nothing was changed.', 'DB_COMPACT_DB_HELD')
        lock = connect_existing(path, timeout=0)
        try:
            try:
                lock.execute('BEGIN IMMEDIATE')            # no writer until the copy is verified
            except sqlite3.OperationalError as error:
                raise Refusal('The controller database is held (' + str(error) + '); nothing was changed.',
                              'DB_COMPACT_DB_HELD') from None
            if queue_busy(lock):
                raise Refusal('This terminal is not idle: ' + queue_busy(lock) + '. Nothing was changed.',
                              'DB_COMPACT_LANE_BUSY')
            source = _ro(path, timeout=0)
            try:
                source.execute('PRAGMA query_only=0')      # VACUUM INTO counts as a write; mode=ro still protects the source
                source.execute('PRAGMA auto_vacuum=INCREMENTAL')   # applies to the VACUUM INTO output only
                source.execute('VACUUM INTO ?', (str(temporary),))
                source.execute('PRAGMA query_only=1')
                original = snapshot(source)
            finally:
                source.close()
            with _closing(_ro(temporary)) as copy:
                copied = snapshot(copy)
                copied_auto = copy.execute('PRAGMA auto_vacuum').fetchone()[0]
                copied_pages = _pragmas(copy)
            found = differences(original, copied) + ([] if copied_auto == INCREMENTAL else ['auto_vacuum'])
            if found:
                raise Refusal('The compacted copy differs from the database (' + ', '.join(found) + '); it was removed '
                              'and nothing was changed.', 'DB_COMPACT_MISMATCH', differences=found)
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise
        finally:
            if lock.in_transaction:
                lock.execute('ROLLBACK')
            lock.close()
        # Swap: every handle of this process is closed now. Windows refuses the rename while any other
        # process has the file open, which is exactly "held". The swap is journaled first (sidecar phase
        # "swapping", fsynced): a stop anywhere until the sidecar says "kept" is undone by recover_interrupted,
        # which StudioStore runs before it opens the database, so there is always a canonical studio.sqlite.
        nonce = uuid.uuid4().hex
        original_bytes = path.stat().st_size
        record = dict(schema=SIDECAR_SCHEMA, phase='swapping', at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
                      database=str(path), original=str(aside), copy=str(temporary), original_bytes=original_bytes,
                      identity={key: original[key] for key in IDENTITY},
                      owner=dict(pid=os.getpid(), nonce=nonce, started=_process_identity(os.getpid())[1]))

        def taken_over():
            return Refusal('Another process recovered this compaction while it was swapping (its heartbeat went stale); '
                           'it put the original back, so this run stops here. Nothing was deleted; a placed copy, if '
                           'any, is kept as ' + path.name + '.compact-rejected-' + stamp + '*.',
                           'DB_COMPACT_RECOVERED_ELSEWHERE', sidecar=str(sidecar))

        def beat():
            if not _heartbeat(sidecar):
                raise taken_over()

        _ACTIVE_SWAPS.add(nonce)       # while set, every opener refuses DB_COMPACT_IN_PROGRESS instead of racing this swap
        try:
            _write_json(sidecar, record)
            try:
                os.rename(path, aside)
            except OSError as error:
                temporary.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                raise Refusal('The controller database is held (' + str(error)[:200] + '); the copy was removed and '
                              'nothing was changed.', 'DB_COMPACT_DB_HELD') from None
            try:
                beat()
                if any(Path(str(path) + suffix).exists() for suffix in ('-journal', '-wal')):
                    # A journal written for the original must never be applied to the copy.
                    raise OSError('a journal appeared beside the database during the swap')
                with _closing(_ro(aside)) as moved:
                    unchanged = differences(original, snapshot(moved, integrity=False))
                if unchanged:
                    raise ValueError('the database changed during compaction (' + ', '.join(unchanged) + ')')
                beat()
                _place(temporary, path)
                beat()
                with _closing(_ro(path)) as placed:
                    found = differences(original, snapshot(placed))
                    placed_pages = _pragmas(placed)
                if found:
                    raise ValueError('the placed copy did not verify (' + ', '.join(found) + ')')
                beat()
            except (OSError, ValueError, sqlite3.Error) as error:
                if not sidecar.exists():
                    raise taken_over() from None
                # Claude-Mac D1 on #239: whatever is at the path now (the placed copy, or a database something
                # created in the gap) is moved aside, never trusted, and the sidecar goes only once the original
                # is provably back.
                code = 'DB_COMPACT_MISMATCH' if isinstance(error, ValueError) else 'DB_COMPACT_SWAP_FAILED'
                rejected = None
                try:
                    rejected = _put_back(path, aside, stamp)
                    with _closing(_ro(path)) as back:
                        restored = not aside.exists() and not differences(original, snapshot(back, integrity=False))
                except (OSError, sqlite3.Error):
                    restored = False
                if not restored:
                    raise Refusal('Compaction stopped mid-swap (' + str(error)[:200] + ') and the original could not be '
                                  'proven back; it is kept at ' + str(aside) + ' and the swap record stays, so the next '
                                  'controller open puts it back. Nothing was deleted.', 'DB_COMPACT_RECOVERY_REQUIRED',
                                  sidecar=str(sidecar)) from None
                temporary.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                raise Refusal('Compaction was rolled back: ' + str(error)[:240] + '. The original is back in place '
                              '(verified)' + ('; what was at the path is kept at ' + str(rejected) if rejected else '')
                              + '.', code, **({'rejected': str(rejected)} if rejected else {})) from None
            # Still inside the swap (every opener refuses): "kept" only while this run still owns the record.
            if not (sidecar.exists() and aside.exists() and path.exists()):
                raise taken_over()
            record.update(phase='kept', original_bytes=aside.stat().st_size,
                          compacted_bytes=path.stat().st_size, live_bytes=info['live_bytes'],
                          auto_vacuum_after=placed_pages['auto_vacuum'],
                          tables={name: value['rows'] for name, value in original['tables'].items()},
                          schema_sha256=original['schema_sha256'],
                          retire='after the next successful batch start (retire_pre_vacuum)')
            for key in ('copy', 'owner', 'identity'):
                record.pop(key, None)
            _write_json(sidecar, record)
        finally:
            _ACTIVE_SWAPS.discard(nonce)
    finally:
        gate_scope.__exit__(None, None, None)
    result = dict(plan, applied=True, original=str(aside), sidecar=str(sidecar), bytes_before=record['original_bytes'],
                  bytes_after=record['compacted_bytes'], auto_vacuum_after=record['auto_vacuum_after'],
                  page_count_after=copied_pages['page_count'], tables=record['tables'],
                  seconds=round(time.monotonic() - started, 2),
                  next_action='The original is kept at ' + str(aside) + ' until the next successful batch start, '
                              'then removed.')
    _log(path.parent, dict(operation='compact', database=str(path), original=str(aside),
                           bytes_before=result['bytes_before'], bytes_after=result['bytes_after'],
                           tables=result['tables'], seconds=result['seconds']))
    return result


def retire_pre_vacuum(root):
    """After a successful batch start on the compacted store: remove the originals ``compact`` kept. Never raises.

    Only originals named by this module's own sidecar are removed; any other ``*.pre-vacuum-*`` file
    (for example one a manual runbook kept) is left alone.
    """
    removed = []
    try:
        database = Path(root) / 'studio.sqlite'
        for item in kept_originals(database):
            if item['phase'] != 'kept':
                continue                    # an interrupted swap is recover_interrupted's, never removed here
            aside, sidecar = Path(item['path']), Path(item['sidecar'])
            if not _STAMP.fullmatch(aside.name[len(database.name + ASIDE):]):
                continue
            if aside.exists():
                aside.unlink()
            for suffix in ('-journal', '-wal', '-shm'):
                extra = Path(str(aside) + suffix)
                if extra.exists():
                    extra.unlink()
            sidecar.unlink()
            removed.append(dict(path=str(aside), bytes=item['bytes']))
        if removed:
            _log(root, dict(operation='retire_pre_vacuum', removed=removed))
        return dict(removed=removed)
    except Exception as error:
        return dict(removed=removed, error=str(error)[:240])
