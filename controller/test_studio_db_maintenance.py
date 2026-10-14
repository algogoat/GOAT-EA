"""studio.sqlite gives its free pages back (studio_db_maintenance, beta.38).

Banker 2026-10-14: an 11.4 GB controller database with 98.8% free pages. Before 3e00695 every queue
receipt embedded the whole queue (818 MB on Banker; 64 receipts held 9.96 GB) and compact-receipts
freed them in place, but the store was auto_vacuum=NONE, so SQLite kept every freed page.

These tests pin: a new store is INCREMENTAL; the idle reclaim runs only above both thresholds, only
when idle, and is bounded; the driver calls it at its finish and retires a kept original after a
successful start; the one-time compaction verifies (rowids included), swaps and refuses on a busy
lane, a held database, low space, a mismatch, an incremental store and a kept original; and the
root-cause path (queue receipts across many runs) no longer grows the file.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed
from studio_batch import prepare_batch
import studio_db_maintenance as maint
from studio_command_store import StudioStore
from studio_refusal import Refusal
from test_studio_fast_lane import synthetic
from test_studio_receipt_digest import make_legacy

MB = 1 << 20


def pragma(path, name):
    with maint._closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return db.execute('PRAGMA ' + name).fetchone()[0]


def legacy_db(path, *, rows=40, size=64 * 1024, keep=4):
    """An auto_vacuum=NONE database with free pages: big rows inserted, most deleted."""
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('CREATE TABLE studio_receipts(binding TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL, '
               'receipt TEXT NOT NULL, PRIMARY KEY(binding,request_id))')
    db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT NOT NULL)')
    db.execute('PRAGMA user_version=7')
    for i in range(rows):
        db.execute('INSERT INTO studio_receipts VALUES(?,?,?,?)', ('b', 'r%03d' % i, 'h%d' % i, 'x' * size))
    db.execute('DELETE FROM studio_receipts WHERE rowid > ?', (keep,))
    db.execute('INSERT INTO studio_queues VALUES(?,?)', ('b', json.dumps([dict(job_id='done', status='completed')])))
    db.close()
    return path


class Thresholds:
    """Small thresholds so a few-MB fixture counts as bloated."""
    def setUp(self):
        for name, value in (('FREE_BYTES', 64 * 1024), ('SPACE_RESERVE', 0)):
            patcher = patch.object(maint, name, value); patcher.start(); self.addCleanup(patcher.stop)


class NewDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_new_store_is_incremental(self):
        store = StudioStore(self.root / 'new.sqlite'); store.close()
        self.assertEqual(pragma(self.root / 'new.sqlite', 'auto_vacuum'), 2)

    def test_a_portable_controller_store_is_incremental(self):
        fixture = fixtures.PortableControllerTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        c = fixture.bound()
        self.assertEqual(c.store.db.execute('PRAGMA auto_vacuum').fetchone()[0], 2)

    def test_an_existing_store_keeps_its_mode_and_content(self):
        path = legacy_db(self.root / 'old.sqlite')
        StudioStore(path).close()
        self.assertEqual(pragma(path, 'auto_vacuum'), 0)                  # only a compaction converts it
        self.assertEqual(pragma(path, 'user_version'), 7)


class ReclaimTests(Thresholds, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'studio.sqlite'
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.addCleanup(self.db.close)
        maint.enable_incremental(self.db)
        self.db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT NOT NULL)')
        self.db.execute('CREATE TABLE blobs(v TEXT)')

    def bloat(self, mb=4):
        for _ in range(mb * 4):
            self.db.execute('INSERT INTO blobs VALUES(?)', ('y' * (256 * 1024),))
        self.db.execute('DELETE FROM blobs')

    def queue(self, *jobs):
        self.db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', ('b', json.dumps(list(jobs))))

    def test_below_either_threshold_nothing_runs(self):
        self.bloat(1)
        with patch.object(maint, 'FREE_BYTES', 64 * MB):                 # ratio over, bytes under
            self.assertEqual(maint.reclaim(self.db)['reason'], 'below_threshold')
        for i in range(40):
            self.db.execute('INSERT INTO blobs VALUES(?)', (str(i) * (256 * 1024),))
        self.db.execute('DELETE FROM blobs WHERE rowid IN (SELECT rowid FROM blobs LIMIT 4)')   # ~1 MB free of ~11 MB
        page = maint._pragmas(self.db)
        self.assertGreater(page['free_bytes'], maint.FREE_BYTES)
        self.assertLess(page['freelist_count'] / page['page_count'], maint.FREE_RATIO)   # bytes over, ratio under
        self.assertEqual(maint.reclaim(self.db)['reason'], 'below_threshold')

    def test_above_both_thresholds_it_gives_the_pages_back(self):
        self.bloat(4)
        size = os.path.getsize(self.path)
        result = maint.reclaim(self.db)
        self.assertTrue(result['ran'])
        self.assertEqual(result['reason'], 'freelist_empty')
        self.assertEqual(self.db.execute('PRAGMA freelist_count').fetchone()[0], 0)
        self.assertLess(os.path.getsize(self.path), size - 3 * MB)
        self.assertGreater(result['freed_bytes'], 3 * MB)

    def test_each_step_and_the_whole_reclaim_are_bounded(self):
        self.bloat(4)
        ticks = iter(range(1000))
        result = maint.reclaim(self.db, pages_per_step=16, max_seconds=3, clock=lambda: next(ticks))
        self.assertEqual(result['reason'], 'time_budget')
        self.assertLessEqual(result['steps'], 3)
        self.assertLessEqual(result['freelist_before'] - result['freelist_after'], 16 * result['steps'])
        self.assertGreater(result['freelist_after'], 0)

    def test_another_writer_stops_it_quickly_and_restores_the_busy_timeout(self):
        self.bloat(4)
        before = self.db.execute('PRAGMA busy_timeout').fetchone()[0]
        other = sqlite3.connect(self.path, isolation_level=None); self.addCleanup(other.close)
        other.execute('BEGIN IMMEDIATE')
        result = maint.reclaim(self.db, busy_ms=50)
        other.execute('ROLLBACK')
        self.assertEqual(result['reason'], 'busy')
        self.assertFalse(result['ran'])
        self.assertEqual(self.db.execute('PRAGMA busy_timeout').fetchone()[0], before)

    def test_a_reader_holding_a_shared_lock_never_stalls_it_past_its_bound(self):
        """Claude-Mac D2 on #239: a step larger than the page cache spilled, and each spill waited behind a reader."""
        self.bloat(8)
        self.db.execute('PRAGMA cache_size=20')                       # far smaller than one 2048-page step
        spill = self.db.execute('PRAGMA cache_spill').fetchone()[0]
        reader = sqlite3.connect(self.path, isolation_level=None); self.addCleanup(reader.close)
        reader.execute('BEGIN'); reader.execute('SELECT count(*) FROM studio_queues').fetchone()   # SHARED lock held
        free = self.db.execute('PRAGMA freelist_count').fetchone()[0]
        import time as clock
        started = clock.monotonic()
        result = maint.reclaim(self.db, busy_ms=100)
        elapsed = clock.monotonic() - started
        reader.execute('ROLLBACK')
        self.assertLess(elapsed, maint.MAX_SECONDS + 0.5, result)
        self.assertEqual(result['reason'], 'busy')
        self.assertEqual(self.db.execute('PRAGMA freelist_count').fetchone()[0], free)   # the step was undone
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('PRAGMA cache_spill').fetchone()[0], spill)
        self.assertTrue(maint.reclaim(self.db)['ran'])                 # and it runs once the reader is gone
        with maint._closing(maint._ro(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_never_inside_a_transaction_and_never_on_a_legacy_store(self):
        self.bloat(4)
        self.db.execute('BEGIN')
        self.assertEqual(maint.reclaim(self.db)['reason'], 'in_transaction')
        self.db.execute('ROLLBACK')
        legacy = legacy_db(Path(self.temp.name) / 'legacy.sqlite')
        with maint._closing(sqlite3.connect(legacy, isolation_level=None)) as db:
            self.assertEqual(maint.reclaim(db)['reason'], 'auto_vacuum_not_incremental')

    def controller(self, db=None):
        return SimpleNamespace(root=Path(self.temp.name), store=SimpleNamespace(db=db or self.db))

    def test_after_batch_runs_only_when_the_lane_is_idle(self):
        self.bloat(4)
        for job in (dict(job_id='live', status='running'),
                    dict(job_id='go', status='pending', launch_intent=dict(attempt_id='a' * 64))):
            self.queue(job)
            result = maint.after_batch(self.controller())
            self.assertEqual((result['ran'], result['reason']), (False, 'busy'), job)
            self.assertIn(job['job_id'], result['busy'])
        self.queue(dict(job_id='done', status='completed'), dict(job_id='next', status='pending'))
        (Path(self.temp.name) / 'seed-active.json').write_text(json.dumps(dict(status='active', batch_id='hunt')))
        self.assertEqual(maint.after_batch(self.controller())['reason'], 'busy')
        (Path(self.temp.name) / 'seed-active.json').unlink()
        result = maint.after_batch(self.controller())
        self.assertTrue(result['ran'], result)
        lines = (Path(self.temp.name) / maint.LOG).read_text(encoding='utf-8').splitlines()
        self.assertEqual(json.loads(lines[-1])['operation'], 'idle_reclaim')

    def test_after_batch_offers_compaction_on_a_legacy_store_and_never_raises(self):
        legacy = legacy_db(Path(self.temp.name) / 'legacy.sqlite')
        with maint._closing(sqlite3.connect(legacy, isolation_level=None)) as db:
            result = maint.after_batch(self.controller(db))
        self.assertEqual(result['reason'], 'auto_vacuum_not_incremental')
        self.assertTrue(result['compaction_offered'])
        self.assertEqual(maint.after_batch(SimpleNamespace(root=None))['reason'], 'no_store')
        closed = sqlite3.connect(':memory:'); closed.close()
        self.assertEqual(maint.after_batch(self.controller(closed))['reason'], 'error')


class DriverHookTests(unittest.TestCase):
    """The batch driver reclaims at its verified finish and retires a kept original after a successful start."""
    def setUp(self):
        from test_studio_batch_driver import Controller
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.c = Controller(self.temp.name)
        for target, kwargs in (('studio_batch_driver._verify_package', {}),
                               ('studio_batch_driver.shutil.disk_usage', dict(return_value=SimpleNamespace(free=100 * 1024**3)))):
            patcher = patch(target, **kwargs); patcher.start(); self.addCleanup(patcher.stop)

    def test_start_retires_and_finish_reclaims_once(self):
        from studio_batch_driver import run
        calls = []
        journal = self.c.root / 'batch-drivers' / 'batch.json'
        def retire(root):
            calls.append(('retire', json.loads(journal.read_text())['status'], self.c.finished))
            return dict(removed=[])
        def reclaim(controller):
            calls.append(('reclaim', json.loads(journal.read_text())['status'], controller is self.c))
            return dict(ran=False)
        self.c.clock.on_sleep = lambda: setattr(self.c, 'finished', True)
        with patch('studio_db_maintenance.retire_pre_vacuum', side_effect=retire), \
                patch('studio_db_maintenance.after_batch', side_effect=reclaim):
            result = run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2, clock=self.c.clock,
                         finish_fn=self.c.finish, max_seconds=10)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(calls, [('retire', 'observing', False), ('reclaim', 'completed', True)])

    def test_a_refused_start_retires_nothing(self):
        from studio_batch_driver import run
        self.c.start_error = True
        with patch('studio_db_maintenance.retire_pre_vacuum') as retire, patch('studio_db_maintenance.after_batch') as reclaim:
            run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2, clock=self.c.clock, finish_fn=self.c.finish,
                max_seconds=10)
        retire.assert_not_called(); reclaim.assert_not_called()

    def test_the_real_hooks_never_change_the_outcome_on_a_fixture_controller(self):
        from studio_batch_driver import run
        self.c.clock.on_sleep = lambda: setattr(self.c, 'finished', True)
        result = run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2, clock=self.c.clock, finish_fn=self.c.finish,
                     max_seconds=10)
        self.assertEqual(result['status'], 'completed')


class CompactTests(Thresholds, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = legacy_db(self.root / 'studio.sqlite')

    def content(self, path=None):
        with maint._closing(maint._ro(path or self.path)) as db:
            return maint.snapshot(db)

    def leftovers(self):
        return sorted(p.name for p in self.root.iterdir() if '.compact-' in p.name or maint.ASIDE in p.name)

    def refused(self, code, **kwargs):
        before = (self.content(), os.path.getsize(self.path), self.leftovers())
        with self.assertRaises(Refusal) as caught:
            maint.compact(self.path, apply=True, **kwargs)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual((self.content(), os.path.getsize(self.path), self.leftovers()), before, 'nothing was changed')
        return caught.exception

    def test_preview_offers_and_changes_nothing(self):
        before = self.path.read_bytes()
        plan = maint.compact(self.path)
        self.assertFalse(plan['applied'])
        self.assertTrue(plan['compaction_offered'])
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(plan['next_action'], 'studio-db-compact --apply --confirm')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(maint.facts(self.path)['compaction_offered'])

    def test_apply_verifies_swaps_keeps_the_original_and_the_next_start_retires_it(self):
        before, size = self.content(), os.path.getsize(self.path)
        manual = self.root / 'studio.sqlite.pre-vacuum-manual'
        manual.write_bytes(b'kept by a runbook')
        result = maint.compact(self.path, apply=True, now=1_760_000_000)
        self.assertTrue(result['applied'])
        self.assertEqual(maint.differences(before, self.content()), [])
        self.assertEqual(pragma(self.path, 'auto_vacuum'), 2)
        self.assertEqual(pragma(self.path, 'freelist_count'), 0)
        self.assertEqual(pragma(self.path, 'user_version'), 7)
        self.assertLess(os.path.getsize(self.path), size / 3)
        aside = Path(result['original'])
        self.assertEqual(aside.name, 'studio.sqlite.pre-vacuum-' + maint._stamp(1_760_000_000))
        self.assertRegex(aside.name, r'pre-vacuum-\d{8}T\d{6}Z$')
        self.assertEqual(os.path.getsize(aside), size)
        self.assertEqual(maint.differences(before, self.content(aside)), [])
        self.assertTrue(Path(result['sidecar']).is_file())
        self.assertEqual(maint.facts(self.path)['kept_originals'][0]['path'], str(aside))
        self.assertFalse(maint.facts(self.path)['compaction_offered'])
        self.assertEqual(json.loads((self.root / maint.LOG).read_text(encoding='utf-8').splitlines()[-1])['operation'], 'compact')
        retired = maint.retire_pre_vacuum(self.root)
        self.assertEqual([item['path'] for item in retired['removed']], [str(aside)])
        self.assertFalse(aside.exists()); self.assertFalse(Path(result['sidecar']).exists())
        self.assertEqual(manual.read_bytes(), b'kept by a runbook')            # never ours: left alone
        self.assertEqual(maint.retire_pre_vacuum(self.root)['removed'], [])

    def test_refuses_a_busy_lane(self):
        self.refused('DB_COMPACT_LANE_BUSY', busy='batch g7 is running')
        with maint._closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute('UPDATE studio_queues SET jobs=?', (json.dumps([dict(job_id='g8', status='running')]),))
        self.assertIn('g8', str(self.refused('DB_COMPACT_LANE_BUSY')))

    def test_refuses_a_held_database(self):
        reader = sqlite3.connect(self.path, isolation_level=None); self.addCleanup(reader.close)
        reader.execute('BEGIN'); reader.execute('SELECT count(*) FROM studio_receipts').fetchone()
        self.refused('DB_COMPACT_DB_HELD')
        reader.execute('ROLLBACK')
        journal = Path(str(self.path) + '-journal'); journal.write_bytes(b'')
        self.refused('DB_COMPACT_DB_HELD')
        journal.unlink()

    @unittest.skipUnless(os.name == 'nt', 'Windows refuses to rename a file another handle holds open')
    def test_an_open_handle_refuses_the_swap_and_removes_the_copy(self):
        holder = sqlite3.connect(self.path); self.addCleanup(holder.close)
        holder.execute('SELECT 1').fetchone()
        self.assertIn('held', str(self.refused('DB_COMPACT_DB_HELD')))

    def test_refuses_low_space(self):
        error = self.refused('DB_COMPACT_LOW_SPACE', disk_free=lambda folder: 1024)
        self.assertIn('GB free', str(error))

    def test_refuses_a_mismatch_and_removes_the_copy(self):
        real = maint.differences
        with patch.object(maint, 'differences', side_effect=lambda a, b: real(a, b) + ['tables']):
            error = self.refused('DB_COMPACT_MISMATCH')
        self.assertEqual(error.fields['differences'], ['tables'])

    def test_a_renumbered_rowid_is_a_mismatch(self):
        other = self.root / 'renumbered.sqlite'
        with maint._closing(sqlite3.connect(other, isolation_level=None)) as db:
            db.execute("ATTACH DATABASE ? AS src", (str(self.path),))
            for (sql,) in db.execute("SELECT sql FROM src.sqlite_master WHERE type='table'").fetchall():
                db.execute(sql)
            db.execute('INSERT INTO studio_queues SELECT * FROM src.studio_queues')
            db.execute('INSERT INTO studio_receipts SELECT * FROM src.studio_receipts ORDER BY rowid DESC')
            db.execute('PRAGMA user_version=7')
            db.execute('DETACH DATABASE src')
        self.assertEqual(maint.differences(self.content(), self.content(other)), ['tables'])

    def test_refuses_an_incremental_store_and_a_kept_original(self):
        maint.compact(self.path, apply=True, now=1_760_000_000)
        error = self.refused('DB_COMPACT_NOT_NEEDED')
        self.assertIn('DB_COMPACT_ORIGINAL_KEPT', [b['code'] for b in error.fields['blockers']])

    def test_a_stop_at_any_swap_point_leaves_a_canonical_database(self):
        """Codex P1 on #239: a stop between the rename and the placement, or before the sidecar says kept."""
        class HostStop(BaseException):
            pass
        before = self.content()
        real_rename, real_place, real_write = os.rename, maint._place, maint._write_json

        def stop_first_rename(source, target):
            raise HostStop()

        def stop_place(source, target):
            raise HostStop()

        writes = []

        def stop_second_write(path, value):
            writes.append(value.get('phase'))
            if len(writes) == 2:
                raise HostStop()
            return real_write(path, value)

        for name, target, replacement in (('before the rename', 'studio_db_maintenance.os.rename', stop_first_rename),
                                          ('after the rename, before placing', 'studio_db_maintenance._place', stop_place),
                                          ('placed, before the sidecar says kept', 'studio_db_maintenance._write_json',
                                           stop_second_write)):
            writes.clear()
            with patch(target, side_effect=replacement), self.assertRaises(HostStop):
                maint.compact(self.path, apply=True, now=1_760_000_000)
            sidecars = list(self.root.glob('studio.sqlite.pre-vacuum-*.json'))
            self.assertEqual(len(sidecars), 1, name)
            self.assertEqual(json.loads(sidecars[0].read_text(encoding='utf-8'))['phase'], 'swapping', name)
            self.assertEqual(maint.retire_pre_vacuum(self.root)['removed'], [], name)   # never removes mid-swap
            StudioStore(self.path).close()                                              # the next open recovers
            after = self.content()        # StudioStore adds its own missing tables to this small fixture; compare ours
            self.assertEqual({key: after['tables'][key] for key in before['tables']}, before['tables'], name)
            self.assertEqual((after['user_version'], after['integrity_check']), (7, ['ok']), name)
            before = after
            self.assertEqual(pragma(self.path, 'auto_vacuum'), 0, name)
            self.assertEqual([p.name for p in self.root.iterdir() if '.pre-vacuum-' in p.name or p.name.endswith('.tmp')],
                             [], name)
            for rejected in self.root.glob('studio.sqlite.compact-rejected-*'):
                rejected.unlink()
        self.assertEqual(real_rename, os.rename); self.assertEqual(real_place, maint._place)
        self.assertTrue(maint.compact(self.path, apply=True, now=1_760_000_000)['applied'])   # and it can run again

    def test_a_database_created_in_the_swap_gap_is_set_aside_and_the_original_restored(self):
        """Claude-Mac D1 on #239: an outside opener creates studio.sqlite between the rename and the placement."""
        before = self.content()
        real_place = maint._place

        def gap(source, target):
            with maint._closing(sqlite3.connect(target, isolation_level=None)) as db:   # a creating opener
                db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT NOT NULL)')
                db.execute("INSERT INTO studio_queues VALUES('gap','[]')")
            return real_place(source, target)                                           # the path exists: fails
        with patch.object(maint, '_place', side_effect=gap), self.assertRaises(Refusal) as caught:
            maint.compact(self.path, apply=True, now=1_760_000_000)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_SWAP_FAILED', str(caught.exception))
        self.assertIn('verified', str(caught.exception))
        self.assertEqual(maint.differences(before, self.content()), [])               # the real data is back
        self.assertEqual(pragma(self.path, 'auto_vacuum'), 0)
        rejected = Path(caught.exception.fields['rejected'])
        with maint._closing(maint._ro(rejected)) as db:                               # the gap database is kept
            self.assertEqual(db.execute('SELECT binding FROM studio_queues').fetchall(), [('gap',)])
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if maint.ASIDE in p.name or p.name.endswith('.tmp')), [])
        self.assertTrue(maint.compact(self.path, apply=True, now=1_760_000_100)['applied'])

    def test_an_opener_in_the_swap_gap_refuses_and_creates_nothing(self):
        real_place = maint._place
        seen = []

        def gap(source, target):
            for opener in (lambda: StudioStore(target), lambda: maint.connect_existing(target).close()):
                try:
                    opener()
                    seen.append('opened')
                except Refusal as error:
                    seen.append(error.code)
                self.assertFalse(Path(target).exists(), 'nothing created in the gap')
            return real_place(source, target)
        with patch.object(maint, '_place', side_effect=gap):
            self.assertTrue(maint.compact(self.path, apply=True, now=1_760_000_000)['applied'])
        self.assertEqual(seen, ['DB_COMPACT_IN_PROGRESS', 'DB_COMPACT_IN_PROGRESS'])
        self.assertEqual(pragma(self.path, 'auto_vacuum'), 2)

    def test_rw_post_no_writer_reaches_the_placed_copy_while_the_swap_runs(self):
        """Claude-Mac on #239 @ aa9b97d (rw_post): owner alive, paused after _place; a connect_existing writer
        (historical pointers, build or installation upgrade) must refuse, never commit into the placed copy."""
        real_place = maint._place
        seen = []

        def paused(source, target):
            real_place(source, target)
            self.assertTrue(Path(target).exists())                                  # the placed copy is there
            for opener in (lambda: StudioStore(target), lambda: maint.connect_existing(target)):
                try:
                    db = opener()
                    seen.append('opened')
                    (db.db if hasattr(db, 'db') else db).close()
                except Refusal as error:
                    seen.append(error.code)
        for mismatch in (False, True):
            seen.clear()
            real = maint.differences
            calls = []

            def differs(a, b):
                calls.append(1)
                return real(a, b) + (['tables'] if mismatch and len(calls) == 3 else [])   # the placed-copy verify
            with patch.object(maint, '_place', side_effect=paused), patch.object(maint, 'differences', side_effect=differs):
                if mismatch:
                    with self.assertRaises(Refusal) as caught:
                        maint.compact(self.path, apply=True, now=1_760_000_000 + mismatch)
                    self.assertEqual(caught.exception.code, 'DB_COMPACT_MISMATCH')
                else:
                    self.assertTrue(maint.compact(self.path, apply=True, now=1_760_000_000)['applied'])
            self.assertEqual(seen, ['DB_COMPACT_IN_PROGRESS', 'DB_COMPACT_IN_PROGRESS'], mismatch)
            for rejected in self.root.glob('studio.sqlite.compact-rejected-*'):
                with maint._closing(maint._ro(rejected)) as db:                       # nothing extra was written there
                    self.assertEqual(db.execute('SELECT count(*) FROM studio_receipts').fetchone()[0], 4)
            if not mismatch:
                self.assertTrue(maint.retire_pre_vacuum(self.root)['removed'])
                for path in self.root.glob('studio.sqlite.pre-vacuum-*'):
                    path.unlink()
                self.path.unlink()
                legacy_db(self.path)                                                    # a fresh legacy store again

    def test_an_unprovable_restore_keeps_the_swap_record_for_the_next_open(self):
        before = self.content()
        with patch.object(maint, '_place', side_effect=OSError('placement failed')), \
                patch.object(maint, '_put_back', side_effect=OSError('restore failed')), \
                self.assertRaises(Refusal) as caught:
            maint.compact(self.path, apply=True, now=1_760_000_000)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_RECOVERY_REQUIRED')
        self.assertFalse(self.path.exists())
        sidecar = Path(caught.exception.fields['sidecar'])
        self.assertEqual(json.loads(sidecar.read_text(encoding='utf-8'))['phase'], 'swapping')
        with self.assertRaises(Refusal) as missing:
            maint.connect_existing(self.path.with_name('other.sqlite'))
        self.assertEqual(missing.exception.code, 'CONTROLLER_DB_MISSING')
        maint.connect_existing(self.path).close()                                       # an opener puts it back first
        after = self.content()
        self.assertEqual({key: after['tables'][key] for key in before['tables']}, before['tables'])
        self.assertFalse(sidecar.exists())

    def swap_record(self, owner, *, age=0, aside_original=True):
        stamp = maint._stamp(1_760_000_000)
        aside = self.root / ('studio.sqlite' + maint.ASIDE + stamp)
        with maint._closing(maint._ro(self.path)) as db:
            identity = {key: value for key, value in maint.snapshot(db, integrity=False).items() if key in maint.IDENTITY}
        if aside_original:
            os.rename(self.path, aside)
        sidecar = aside.with_name(aside.name + '.json')
        record = dict(schema=maint.SIDECAR_SCHEMA, phase='swapping', original_bytes=os.path.getsize(aside if aside_original else self.path),
                      identity=identity, owner=owner)
        sidecar.write_text(json.dumps(record), encoding='utf-8')
        if age:
            stale = time.time() - age
            os.utime(sidecar, (stale, stale))
        return sidecar

    def test_takeover_needs_a_stale_heartbeat_and_a_dead_or_reused_owner(self):
        import time as clock
        live_pid = os.getppid()
        alive, started = maint._process_identity(live_pid)
        self.assertTrue(alive)
        sidecar = self.swap_record(dict(pid=live_pid, nonce='x', started=started), age=maint.SWAP_STALE_SECONDS + 60)
        for identity, refuses in (((True, started), True),            # hung owner past the bound: never raced
                                  ((False, None), False)):           # stale heartbeat and dead owner: recovered
            with patch.object(maint, '_process_identity', return_value=identity):
                if refuses:
                    with self.assertRaises(Refusal) as caught:
                        StudioStore(self.path)
                    self.assertEqual(caught.exception.code, 'DB_COMPACT_IN_PROGRESS')
                    self.assertIn('minutes', str(caught.exception))
                    self.assertFalse(self.path.exists(), 'never creates while the owner may still swap')
                else:
                    self.assertEqual(len(maint.recover_interrupted(self.path)), 1)
        self.assertEqual(pragma(self.path, 'user_version'), 7)
        self.assertFalse(sidecar.exists())
        # PID reused: alive, but another process (different creation time), and a stale heartbeat.
        sidecar = self.swap_record(dict(pid=live_pid, nonce='x', started=(started or 0) + 1),
                                   age=maint.SWAP_STALE_SECONDS + 60)
        with patch.object(maint, '_process_identity', return_value=(True, (started or 0) + 2)):
            self.assertEqual(len(maint.recover_interrupted(self.path)), 1)
        # A fresh heartbeat refuses even when the owner looks dead.
        sidecar = self.swap_record(dict(pid=live_pid, nonce='x', started=started))
        with patch.object(maint, '_process_identity', return_value=(False, None)), self.assertRaises(Refusal) as caught:
            maint.connect_existing(self.path)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_IN_PROGRESS')
        old = clock.time() - maint.SWAP_STALE_SECONDS - 60
        os.utime(sidecar, (old, old))
        with patch.object(maint, '_process_identity', return_value=(False, None)):
            maint.connect_existing(self.path).close()
        self.assertFalse(sidecar.exists())

    def test_a_record_left_after_the_original_was_back_is_retired_even_if_the_store_changed(self):
        sidecar = self.swap_record(dict(pid=os.getppid(), nonce='x'), age=maint.SWAP_STALE_SECONDS + 60,
                                   aside_original=False)
        with maint._closing(sqlite3.connect(self.path, isolation_level=None)) as db:   # later legitimate writes
            db.execute("INSERT INTO studio_receipts VALUES('b','later','h','x')")
        with patch.object(maint, '_process_identity', return_value=(False, None)):
            self.assertEqual(len(maint.recover_interrupted(self.path)), 1)
        self.assertFalse(sidecar.exists())

    def test_the_owner_stops_cleanly_when_another_process_recovered_its_swap(self):
        real_place = maint._place

        def raced(source, target):
            real_place(source, target)
            sidecar = next(self.root.glob('studio.sqlite.pre-vacuum-*.json'))         # another process takes over
            aside = sidecar.with_name(sidecar.name[:-len('.json')])
            maint._put_back(Path(target), aside, 'elsewhere')
            sidecar.unlink()
        before = self.content()
        with patch.object(maint, '_place', side_effect=raced), self.assertRaises(Refusal) as caught:
            maint.compact(self.path, apply=True, now=1_760_000_000)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_RECOVERED_ELSEWHERE')
        self.assertEqual(maint.differences(before, self.content()), [])
        self.assertEqual(pragma(self.path, 'auto_vacuum'), 0)

    def test_connect_existing_never_creates(self):
        missing = self.root / 'none.sqlite'
        with self.assertRaises(Refusal) as caught:
            maint.connect_existing(missing)
        self.assertEqual(caught.exception.code, 'CONTROLLER_DB_MISSING')
        self.assertFalse(missing.exists())

    def test_refuses_a_missing_database(self):
        with self.assertRaises(Refusal) as caught:
            maint.compact(self.root / 'none.sqlite', apply=True)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_MISSING')


class ControllerCompactTests(Thresholds, unittest.TestCase):
    """The real root cause end to end on a portable controller: full-queue receipts, compact-receipts, then
    the space comes back, and the controller's own content view is unchanged."""
    def setUp(self):
        super().setUp()
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'old', synthetic(self.fixture, self.c, 2))
        self.binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        state = self.c.state()
        state['queue'][0].update(status='completed', completion=dict(report='r' * (2 * MB)))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), self.binding))
        self.path = self.c.root / 'studio.sqlite'

    def bloat_like_banker(self):
        """Every receipt embeds the 2 MB queue (pre-3e00695), then compact-receipts rewrites them in place."""
        count = self.c.store.db.execute('SELECT count(*) FROM studio_receipts').fetchone()[0]
        self.assertGreaterEqual(count, 2)
        make_legacy(self.c.store.db, self.c.state()['queue'])
        grown = os.path.getsize(self.path)
        from studio_receipt_digest import compact
        self.assertTrue(compact(self.c, apply=True)['applied'])
        self.assertGreaterEqual(os.path.getsize(self.path), grown)     # freed in place, never returned
        free = self.c.store.db.execute('PRAGMA freelist_count').fetchone()[0] * self.c.store.db.execute('PRAGMA page_size').fetchone()[0]
        self.assertGreater(free, (count - 0.5) * 2 * MB)
        return grown, free

    def test_an_incremental_store_gets_the_digest_pass_space_back_at_once(self):
        grown, free = self.bloat_like_banker()
        result = maint.after_batch(self.c, max_seconds=30.0)
        self.assertTrue(result['ran'], result)
        self.assertLessEqual(os.path.getsize(self.path), grown - free + 64 * 1024)

    def test_a_legacy_store_is_compacted_with_the_same_controller_view(self):
        from studio_handover import database_view
        self.c.store.close(); self.c.store = None
        with maint._closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute('PRAGMA auto_vacuum=0'); db.execute('VACUUM')        # a store created before beta.38
        self.c.open()
        self.assertEqual(self.c.store.db.execute('PRAGMA auto_vacuum').fetchone()[0], 0)
        _, free = self.bloat_like_banker()
        self.c.store.close(); self.c.store = None
        before, size = database_view(self.path), os.path.getsize(self.path)
        result = maint.compact(self.path, apply=True)
        self.assertEqual(database_view(self.path), before)
        self.assertLessEqual(result['bytes_after'], size - free + 64 * 1024)
        self.assertEqual(pragma(self.path, 'auto_vacuum'), 2)
        self.c.open()
        self.assertEqual(self.c.state()['queue'][0]['job_id'], 'old')


class GrowthTests(unittest.TestCase):
    """The root-cause path: each run writes queue receipts. With digest receipts the file stays bounded."""
    RUNS = 6

    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'old', synthetic(self.fixture, self.c, 2))
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        state = self.c.state()
        state['queue'][0].update(status='completed', completion=dict(report='r' * (2 * MB)))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.queue_bytes = len(self.c.store.db.execute('SELECT jobs FROM studio_queues').fetchone()[0])
        self.path = self.c.root / 'studio.sqlite'

    def runs(self):
        sizes = []
        for i in range(self.RUNS):
            job = 'g%d' % i
            prepare_batch(self.c, job, synthetic(self.fixture, self.c, 2))            # queue.enqueue_batch receipt
            self.c.cancel(job, expected_generation=self.c.state()['generation'])     # queue.cancel receipt
            sizes.append(os.path.getsize(self.path))
        return sizes

    def test_runs_do_not_grow_the_file(self):
        sizes = self.runs()
        self.assertLessEqual(sizes[-1] - sizes[0], 2 * self.queue_bytes, sizes)
        largest = self.c.store.db.execute('SELECT max(length(receipt)) FROM studio_receipts').fetchone()[0]
        self.assertLess(largest, 4096)

    def test_the_old_receipt_shape_would_grow_it_by_queue_copies(self):
        # Guards the test itself: with receipts that embed the queue (pre-3e00695) the same runs grow the file.
        with patch('studio_command_store.receipt_state', side_effect=lambda state, raw=None: dict(state)):
            sizes = self.runs()
        self.assertGreater(sizes[-1] - sizes[0], (self.RUNS - 1) * self.queue_bytes, sizes)


def footprint(db):
    page_count = db.execute('PRAGMA page_count').fetchone()[0]
    freelist = db.execute('PRAGMA freelist_count').fetchone()[0]
    return dict(page_count=page_count, freelist=freelist, total=page_count + freelist)


OLD_UPDATE = 'UPDATE studio_queues SET jobs=? WHERE binding=?'


class MemberBoundaryTests(unittest.TestCase):
    """Banker 2026-10-14 (#2350 6160566397): right after compaction, round 3 member 1's finish grew the 136 MB store
    to 272 MB in one step, then it stayed flat. A member boundary writes no receipt: reconcile rewrites the queue row
    (studio_reconcile). An UPDATE of a large row whose size changes allocates the new overflow chain before it frees
    the old one, so a store with no free pages grows by one whole queue copy. write_queue deletes, then inserts."""
    QUEUE = 4 * MB
    BOUNDARIES = 8

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def compacted(self, name, auto_vacuum):
        """A store just after compaction: one large queue row and no free pages."""
        path = Path(self.temp.name) / name
        with maint._closing(sqlite3.connect(path, isolation_level=None)) as db:
            db.execute('PRAGMA auto_vacuum=%d' % auto_vacuum)
            db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT NOT NULL)')
            db.execute('CREATE TABLE studio_state(binding TEXT PRIMARY KEY, revision INTEGER NOT NULL)')
            db.execute("INSERT INTO studio_state VALUES('b',0)")
            db.execute("INSERT INTO studio_queues VALUES('b',?)", ('q' * self.QUEUE,))
            db.execute('VACUUM')
        db = sqlite3.connect(path, isolation_level=None); self.addCleanup(db.close)
        self.assertEqual(footprint(db)['freelist'], 0)
        return db

    def boundaries(self, db, write):
        """Each boundary: one reconcile-shaped transaction that rewrites the queue (a little longer) and the revision."""
        trace = [footprint(db)]
        for i in range(1, self.BOUNDARIES + 1):
            db.execute('BEGIN IMMEDIATE')
            write(db, 'b', 'q' * (self.QUEUE + 997 * i))
            db.execute("UPDATE studio_state SET revision=revision+1 WHERE binding='b'")
            db.execute('COMMIT')
            trace.append(footprint(db))
        return trace

    def test_before_an_update_grows_the_store_by_a_queue_copy_after_write_queue_does_not(self):
        queue_pages = self.QUEUE // 4096
        for auto_vacuum in (0, 2):
            before = self.boundaries(self.compacted('update-%d.sqlite' % auto_vacuum, auto_vacuum),
                                     lambda db, b, raw: db.execute(OLD_UPDATE, (raw, b)))
            after = self.boundaries(self.compacted('write-%d.sqlite' % auto_vacuum, auto_vacuum), maint.write_queue)
            # Before: the first boundary adds a whole queue copy (page_count + freelist_count grows by ~2 copies),
            # then later boundaries reuse it.
            self.assertGreater(before[1]['page_count'] - before[0]['page_count'], 0.95 * queue_pages, before)
            self.assertGreater(before[1]['total'] - before[0]['total'], 1.9 * queue_pages, before)
            self.assertGreater(before[-1]['freelist'], 0.95 * queue_pages, before)
            # After: every boundary reuses the pages it frees; growth is only the few pages the row itself grew.
            self.assertLess(after[-1]['total'] - after[0]['total'], 16, after)
            self.assertLess(after[-1]['freelist'], 4, after)

    def test_write_queue_keeps_update_and_replace_semantics_and_is_atomic(self):
        db = sqlite3.connect(':memory:', isolation_level=None); self.addCleanup(db.close)
        db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT NOT NULL)')
        self.assertEqual(maint.write_queue(db, 'b', '[]'), 0)                          # UPDATE: no row, no write
        self.assertIsNone(db.execute('SELECT jobs FROM studio_queues').fetchone())
        self.assertEqual(maint.write_queue(db, 'b', '[1]', create=True), 1)           # INSERT OR REPLACE
        self.assertEqual(maint.write_queue(db, 'b', '[2]'), 1)
        self.assertEqual(maint.write_queue(db, 'b', '[3]', create=True), 1)
        self.assertEqual(db.execute('SELECT binding,jobs FROM studio_queues').fetchall(), [('b', '[3]')])
        for in_transaction in (False, True):
            if in_transaction:
                db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.IntegrityError):
                maint.write_queue(db, 'b', None)                                     # NOT NULL: the insert fails
            self.assertEqual(db.execute('SELECT jobs FROM studio_queues').fetchall(), [('[3]',)], 'old row kept')
            self.assertEqual(db.in_transaction, in_transaction)
            if in_transaction:
                db.execute('ROLLBACK')

    def test_write_queue_reraises_the_real_error_when_sqlite_already_rolled_back(self):
        class Full(sqlite3.OperationalError):
            pass

        class Db:
            def execute(self, sql, *args):
                if sql.startswith('DELETE'):
                    raise Full('database or disk is full')
                if sql.startswith('ROLLBACK TO'):
                    raise sqlite3.OperationalError('no such savepoint: goat_queue_write')
        with self.assertRaises(Full):
            maint.write_queue(Db(), 'b', '[]')

    def test_no_production_module_rewrites_the_queue_row_with_update_or_replace(self):
        controller = Path(__file__).resolve().parent
        offenders = [path.name for path in controller.glob('*.py') if not path.name.startswith('test_')
                     and ('UPDATE studio_queues SET' in path.read_text(encoding='utf-8')
                          or 'INSERT OR REPLACE INTO studio_queues' in path.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [])

    def test_a_portable_controller_queue_write_reuses_its_pages(self):
        fixture = fixtures.PortableControllerTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        c = fixture.bound(); fixture.grant(c)
        prepare_batch(c, 'old', synthetic(fixture, c, 2))
        binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
        state = c.state()
        state['queue'][0].update(status='completed', completion=dict(report='r' * self.QUEUE))
        maint.write_queue(c.store.db, binding, packed(state['queue']))
        c.store.db.execute('VACUUM')                                                # as after tonight's compaction
        start = footprint(c.store.db)
        for i in range(self.BOUNDARIES):                                             # a member observation per boundary
            state = c.state()
            state['queue'][0]['native_observation'] = dict(member=i, members=['m'] * (50 * i))
            with c.store.transaction():
                maint.write_queue(c.store.db, binding, packed(state['queue']))
        end = footprint(c.store.db)
        self.assertLess(end['total'] - start['total'], 16, (start, end))
        self.assertEqual(c.state()['queue'][0]['native_observation']['member'], self.BOUNDARIES - 1)


class SurfaceTests(Thresholds, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        legacy_db(self.root / 'studio.sqlite')

    def test_research_status_shows_the_offer(self):
        from studio_research_status import _controller_db
        value = _controller_db(self.root)
        self.assertTrue(value['compaction_offered'])
        self.assertEqual(value['auto_vacuum'], 0)
        self.assertIn('studio-db-compact', value['plain'])
        self.assertEqual(_controller_db(self.root / 'missing'), dict(path=str(self.root / 'missing' / 'studio.sqlite'),
                                                                    exists=False))

    def agent(self, busy=None, lease_busy=False):
        from demo_agent import DemoAgent
        appended = []

        @contextmanager
        def exclusive(**_):
            if lease_busy:
                raise ValueError('Another demo agent operation owns this terminal')
            yield
        fake = SimpleNamespace(root=self.root, clock=lambda: 1_760_000_000.0, _close_busy=lambda: busy,
                               _exclusive=exclusive, _append=lambda *a, **k: appended.append((a, k)))
        return (lambda **kw: DemoAgent.studio_db_compact(fake, **kw)), appended

    def test_demo_agent_command_needs_confirm_the_lease_and_an_idle_terminal(self):
        run, appended = self.agent()
        self.assertFalse(run()['applied'])
        for kwargs, code in ((dict(apply=True), 'DB_COMPACT_CONFIRM_REQUIRED'),):
            with self.assertRaises(Refusal) as caught:
                run(**kwargs)
            self.assertEqual(caught.exception.code, code)
        busy_run, _ = self.agent(lease_busy=True)
        with self.assertRaises(Refusal) as caught:
            busy_run(apply=True, confirm=True)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_LANE_BUSY')
        idle_busy, _ = self.agent(busy='the seed slot is held by hunt')
        with self.assertRaises(Refusal) as caught:
            idle_busy(apply=True, confirm=True)
        self.assertEqual(caught.exception.code, 'DB_COMPACT_LANE_BUSY')
        result = run(apply=True, confirm=True)
        self.assertTrue(result['applied'])
        self.assertEqual(appended[0][0], ('studio_db_compact', 'swapped'))

    def test_cli_routes_the_command(self):
        import demo_agent
        with patch('demo_agent.DemoAgent') as agent, patch('builtins.print'):
            agent.return_value.studio_db_compact.return_value = dict(applied=False)
            self.assertEqual(demo_agent.main(['--installation', 'x', 'studio-db-compact', '--apply', '--confirm']), 0)
        agent.return_value.studio_db_compact.assert_called_once_with(apply=True, confirm=True)


if __name__ == '__main__':
    unittest.main()
