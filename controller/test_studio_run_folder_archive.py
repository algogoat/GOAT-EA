"""evidence-archive --run-folders (P-beta38-run-folder-archive, goatai#2350 6156934300).

Fixtures are shaped like the Banker PC: ``Common Files\\GOAT\\R<12 hex>`` run folders with ``queue.GOAT``,
``export_settings.GOAT``, ``inputs``, ``reports``, ``exports`` and ``deploy\\<member>\\<symbol>\\<stem>.set`` units with
their equity CSV and ``.goatseq`` capture, owned by packages and queue rows of the demo installation. The gate test
(``B43MigGateTests``) models b43mig-1: a build-migration catch-up whose members cite their original SETs inside
``GOAT\\Ra260c972f9fc\\deploy\\R08b60f11c99b9d89d59e\\AUDCAD\\``. Every file is a temporary fixture; nothing touches MT5, a
terminal, the real Common Files or a real archive drive (the second volume is simulated by ``volume_of``).
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
import studio_build_migration as bm
from studio_evidence import collect_sets, read_export
import studio_evidence_archive as archive
from studio_installation import read_json
import studio_run_folder_archive as runs
from studio_refusal import Refusal
from test_studio_batch_close import G20Fixture, write_json
from test_studio_build_migration import OLD_EA, SOURCE, MigrationCase
from test_studio_catchup import export_settings

FAKE_GUID = '\\\\?\\Volume{00000000-0000-0000-0000-00000000a5c2}\\'   # never mounted: lookups by it fail
STEM = 'GOAT V1.49 EURUSD,M1_Trds=40_Prf=120_DD=10_PF=2.00_SR=3.00_ARF=0.500'


def alias(n):
    return 'R%020x' % (0xabc00 + n)


def run_id(n):
    return 'R%012x' % (0xa260c972f000 + n)


class VolumePatches:
    """The archive root is a second volume (volume_of); its GUID is a fixed fake one mounted nowhere."""

    def patch_volumes(self, archive_root):
        self.archive_root = archive_root

        def volume(path):
            return 2 if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(archive_root))) else 1
        for name, kw in (('volume_of', dict(side_effect=volume)), ('volume_guid_of', dict(return_value=FAKE_GUID)),
                         ('volume_mounts', dict(return_value=[]))):
            patcher = patch('studio_evidence_archive.' + name, **kw)
            patcher.start()
            self.addCleanup(patcher.stop)
        runs._STUBS.clear(); runs._MANIFESTS.clear(); runs._VERIFIED.clear(); runs._OPEN.clear()


class RunFolderFixture(VolumePatches, G20Fixture):
    """The demo agent fixture with finished run folders of the real shape."""

    def setUp(self):
        super().setUp()
        self.source = self.common / 'GOAT'
        self.patch_volumes(self.f.base / 'archive-volume')
        self.archive_root.mkdir()
        self.queue = []                       # g20's package stays (its run folder then has no queue row)
        self.write_queue()

    def make_run(self, n, job_id, *, status='completed', recorded_at='2026-10-01T00:00:00Z',
                 outcomes=('native_completed', 'native_completed')):
        rid = run_id(n)
        run = self.source / rid
        package = self.root / 'packages' / job_id
        aliases = [alias(n * 10 + i) for i in range(len(outcomes))]
        inputs = {a: ('[Inputs]\r\nGrid_Size=%d\r\n' % i).encode('utf-16') for i, a in enumerate(aliases)}
        plan = dict(studio_source=dict(job_id=job_id), research_binding=dict(common_files_root=str(self.common)))
        jobs = [dict(run_alias=a, tester=dict(Symbol='EURUSD', Period='M1'), staged_sha256=hashlib.sha256(inputs[a]).hexdigest())
                for a in aliases]
        write_json(package / 'studio-plan.json', plan)
        write_json(package / 'manifest.json', dict(campaign_id=sha(plan), native_run_relative='GOAT\\' + rid, jobs=jobs))
        words = {'native_completed': 'Completed', 'native_cancelled': 'Cancelled', 'native_error': 'Error',
                 'native_pending': 'Pending', 'native_queued': 'Queued', 'native_ongoing': 'OnGoing'}
        queue = '\x1f'.join(';%s_EURUSD:%s;\r\n[Tester]\r\nSymbol=EURUSD\r\nPeriod=M1\r\n' % (words[s], a)
                            for s, a in zip(outcomes, aliases))
        files = {'queue.GOAT': queue.encode('utf-16'), 'manifest.json': json.dumps(dict(jobs=jobs)).encode(),
                 'export_settings.GOAT': '[Export]\r\nMinARF=0.2\r\nMinSR=2.5\r\n'.encode('utf-16'),
                 'log.GOAT': b'log\r\n' * 50, 'timeline.tsv': b'a\tb\r\n'}
        for a in aliases:
            files['inputs/%s/Inputs.GOAT' % a] = inputs[a]
            files['reports/%s/EURUSD/%s.xml' % (a, STEM)] = b'<xml/>' * 20
            unit = 'deploy/%s/EURUSD/%s' % (a, STEM)
            files[unit + '.set'] = ('; GOAT export\r\nEA_Desc=%s\r\nMode_Operation=9\r\nGrid_Size=1\r\n' % a).encode('utf-16')
            files[unit + '.csv'] = b'<DATE>\t<BALANCE>\t<EQUITY>\r\n2026.10.01 10:00\t10000\t10000\r\n'
            files[unit + '.goatseq/deals.csv'] = b'deal\r\n' * 30
            files[unit + '.goatseq/account.csv'] = os.urandom(4096)
            files['exports/%s %s.csv' % (STEM, a)] = os.urandom(2048)
        for relative, raw in files.items():
            path = run / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        job = dict(job_id=job_id, status=status, configuration_sha256='c' * 64, configuration=dict(batch_members=[{} for _ in aliases]),
                   launch_intent=dict(attempt_id='a' * 64, package=str(package), recorded_at=recorded_at),
                   completion=dict(status=status, member_outcomes=[dict(index=i, run_alias=a, status=s)
                                                                  for i, (a, s) in enumerate(zip(aliases, outcomes))]))
        self.queue.append(job)
        self.write_queue()
        return run

    def tree(self, folder):
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}

    def keep_file(self, value=()):
        path = self.f.base / 'keep.json'
        path.write_text(json.dumps(list(value)))
        return path

    def preview(self, **kw):
        kw.setdefault('keep_last', 0)
        kw.setdefault('free_floor_gb', 0)
        return self.agent.run_folder_archive(kw.pop('archive_root', self.archive_root), **kw)

    def apply(self, **kw):
        if 'keep_list' not in kw:
            kw['keep_list'] = self.keep_file()           # --apply needs a keep-list; an empty one is the usual case
        return self.preview(apply=True, confirm=True, **kw)

    def complete(self, **kw):
        return self.agent.run_folder_archive(None, complete=True, confirm=True, **kw)

    def skipped(self, result):
        return {row['run_id']: row['codes'] for row in result['skipped']}

    def state(self):
        return {str(p): p.read_bytes() for base in (self.root, self.common, self.archive_root) for p in base.rglob('*')
                if p.is_file() and not p.name.endswith('.lock') and p.name != 'actions.jsonl'}

    def refused(self, code, call, *args, **kw):
        before = self.state()
        with self.assertRaises(Refusal) as caught:
            call(*args, **kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(self.state(), before, 'a refusal changed a file')
        return caught.exception


class MoveTests(RunFolderFixture):
    def test_an_eligible_folder_is_copied_verified_stubbed_and_then_removed(self):
        run = self.make_run(1, 'banker-done-1')
        original = self.tree(run)
        preview = self.preview()
        self.assertEqual([r['run_id'] for r in preview['eligible']], [run.name])
        self.assertEqual(preview['bytes'], sum(len(raw) for raw in original.values()))
        self.assertEqual(preview['eligible'][0]['file_count'], len(original))
        self.assertGreater(preview['archive_free_bytes'], 0)
        self.assertNotIn('files', preview['eligible'][0])               # the reply never carries the file lists
        self.assertFalse((run / runs.STUB).exists(), 'the preview wrote something')
        self.assertIn(dict(run_id='R0123456789ab', owners=[dict(installation=self.root.name, batch_id='g20-rest1', statuses=[])],
                           codes=['ARCHIVE_OWNER_UNKNOWN'], plain=self.skipped_plain(preview, 'R0123456789ab'), cited_by=[]),
                      preview['skipped'])
        result = self.apply()
        self.assertTrue(result['applied'])
        self.assertEqual([(r['run_id'], r['copied'], r['state']) for r in result['results']], [(run.name, len(original), 'archived')])
        target = self.archive_root / run.name
        copied = self.tree(target)
        manifest = json.loads(copied.pop(runs.MANIFEST))
        self.assertEqual(copied, original)                                # every file, byte-identical
        self.assertEqual({e['relative_path']: e['sha256'] for e in manifest['files']},
                         {k: hashlib.sha256(v).hexdigest() for k, v in original.items()})
        stub = json.loads((run / runs.STUB).read_text())
        self.assertEqual((stub['state'], stub['file_count'], stub['bytes'], stub['archive_dir']),
                         ('archived', len(original), preview['bytes'], str(target)))
        self.assertEqual(stub['manifest_sha256'], hashlib.sha256((target / runs.MANIFEST).read_bytes()).hexdigest())
        self.assertEqual({k: v for k, v in self.tree(run).items() if k != runs.STUB}, original)   # --apply removes nothing
        # The preview now lists it as archived, never eligible again.
        again = self.preview()
        self.assertEqual(again['eligible'], [])
        self.assertEqual([(a['run_id'], a['state']) for a in again['archived']], [(run.name, 'archived')])
        done = self.complete()
        self.assertEqual([(r['run_id'], r['removed'], r['state']) for r in done['results']], [(run.name, len(original), 'removed')])
        self.assertEqual(done['freed_bytes'], preview['bytes'])
        self.assertEqual(sorted(p.name for p in run.iterdir()), [runs.STUB])   # only ARCHIVED.json stays
        self.assertEqual(json.loads((run / runs.STUB).read_text())['state'], 'removed')
        self.assertEqual({k: v for k, v in self.tree(target).items() if k != runs.MANIFEST}, original)
        actions = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        self.assertEqual([(a['operation'], a['phase'], a['run_id']) for a in actions],
                         [('run_folder_archive', 'archived', run.name), ('run_folder_archive', 'completed', run.name)])
        # A second --complete has nothing left to do.
        self.refused('ARCHIVE_NOTHING_TO_MOVE', self.complete)

    def skipped_plain(self, preview, rid):
        return next(row['plain'] for row in preview['skipped'] if row['run_id'] == rid)

    def test_apply_needs_confirm_keep_list_and_a_root(self):
        self.make_run(1, 'banker-done-1')
        self.refused('ARCHIVE_CONFIRM_REQUIRED', self.preview, apply=True, keep_list=self.keep_file())
        self.refused('ARCHIVE_KEEP_LIST_REQUIRED', self.preview, apply=True, confirm=True)
        self.refused('ARCHIVE_ROOT_INVALID', self.apply, archive_root=None)
        self.refused('ARCHIVE_MODE_CONFLICT', self.preview, apply=True, complete=True, confirm=True)
        self.refused('ARCHIVE_CONFIRM_REQUIRED', self.agent.run_folder_archive, None, complete=True)
        with self.assertRaisesRegex(ValueError, 'R<12 lowercase hex>'):
            self.preview(run_ids=['..\\x'])

    def test_a_crash_mid_copy_leaves_the_source_intact_and_a_rerun_resumes(self):
        run = self.make_run(1, 'banker-done-1')
        original = self.tree(run)
        real, calls = archive.copy_verified, []

        def crash_after_three(source, target, expected=None):
            calls.append(target)
            if len(calls) == 4:
                raise OSError(28, 'simulated crash mid-copy')
            return real(source, target, expected)
        with patch('studio_evidence_archive.copy_verified', side_effect=crash_after_three):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.tree(run), original)                       # nothing removed, no stub
        self.assertFalse((self.archive_root / run.name / runs.MANIFEST).exists())
        result = self.apply()
        self.assertEqual((result['results'][0]['reused'], result['results'][0]['copied']), (3, len(original) - 3))
        self.assertEqual(json.loads((run / runs.STUB).read_text())['state'], 'archived')

    def test_a_crash_while_removing_resumes_on_the_next_complete(self):
        run = self.make_run(1, 'banker-done-1')
        original = self.tree(run)
        self.apply()
        real, removed = runs._remove_source, []

        def crash_after_two(source, folder, path):
            if len(removed) == 2:
                raise OSError(5, 'simulated crash while removing')
            removed.append(path)
            return real(source, folder, path)
        with patch('studio_run_folder_archive._remove_source', side_effect=crash_after_two):
            with self.assertRaises(Refusal) as caught:              # a removal that fails is named, never left unexplained
                self.complete()
        self.assertEqual((caught.exception.code, caught.exception.fields['removed']), ('ARCHIVE_SOURCE_LOCKED', 2))
        self.assertEqual(json.loads((run / runs.STUB).read_text())['state'], 'removing')
        # Mid-removal, readers already read the archive: the archive is the truth once removal starts.
        cited = run / ('deploy/%s/EURUSD/%s.set' % (alias(10), STEM))
        self.assertEqual(runs.resolve(cited), self.archive_root / run.name / cited.relative_to(run))
        done = self.complete()
        self.assertEqual(done['results'][0]['removed'], len(original) - 2)
        self.assertEqual(sorted(p.name for p in run.iterdir()), [runs.STUB])

    def test_a_sha_mismatch_aborts_and_leaves_the_source_intact(self):
        run = self.make_run(1, 'banker-done-1')
        original = self.tree(run)
        with patch('studio_evidence_archive._readback', return_value='0' * 64):
            with self.assertRaises(Refusal) as caught:
                self.apply()
        self.assertEqual(caught.exception.code, 'ARCHIVE_VERIFY_FAILED')
        self.assertEqual(self.tree(run), original)
        self.assertFalse((run / runs.STUB).exists())
        # After a good --apply, a corrupted archive copy makes --complete refuse with nothing removed.
        self.apply()
        victim = self.archive_root / run.name / 'deploy' / alias(10) / 'EURUSD' / (STEM + '.csv')
        victim.write_bytes(victim.read_bytes()[:-1] + b'X')
        self.refused('ARCHIVE_VERIFY_FAILED', self.complete)
        self.assertEqual({k: v for k, v in self.tree(run).items() if k != runs.STUB}, original)
        # A stray file in the archive folder, or a source that changed, refuses too.
        victim.write_bytes(original['deploy/%s/EURUSD/%s.csv' % (alias(10), STEM)])
        (self.archive_root / run.name / 'stray.txt').write_bytes(b'x')
        self.refused('ARCHIVE_VERIFY_FAILED', self.complete)
        (self.archive_root / run.name / 'stray.txt').unlink()
        (run / 'log.GOAT').write_bytes(b'changed')
        self.refused('ARCHIVE_SOURCE_CHANGED', self.complete)
        (run / 'log.GOAT').write_bytes(original['log.GOAT'])
        self.complete()
        self.assertEqual(sorted(p.name for p in run.iterdir()), [runs.STUB])

    def test_probe_an_archive_copy_lost_mid_complete_keeps_its_source(self):
        """Review item 1 on #237 (toctou237.py): an archive copy removed while --complete hashes the sources used to end
        "removed" with the file gone from both places. Now each copy is re-verified right before its own source goes."""
        run = self.make_run(1, 'banker-done-1')
        original = self.tree(run)
        self.apply()
        last = sorted(original)[-1]
        victim = self.archive_root / run.name / last
        real = archive.file_sha256

        def hash_then_pull_the_copy(path):
            if victim.exists() and os.path.normcase(str(path)).startswith(os.path.normcase(str(run))):
                victim.unlink()                                  # the archive drive loses one copy mid-run
            return real(path)
        with patch('studio_evidence_archive.file_sha256', side_effect=hash_then_pull_the_copy):
            with self.assertRaises(Refusal) as caught:
                self.complete()
        self.assertEqual(caught.exception.code, 'ARCHIVE_VERIFY_FAILED')
        self.assertEqual(caught.exception.fields['removed'], len(original) - 1)
        self.assertEqual((run / last).read_bytes(), original[last])           # its source is kept
        self.assertEqual(json.loads((run / runs.STUB).read_text())['state'], 'removing')
        # No file is lost from both places: every source that went has its verified copy.
        for relative, raw in original.items():
            self.assertTrue((run / relative).is_file() or (self.archive_root / run.name / relative).read_bytes() == raw, relative)
        # A copy changed in place (same size) right before its removal is refused the same way.
        run2 = self.make_run(2, 'banker-done-2')
        original2 = self.tree(run2)
        self.apply()
        last2 = sorted(original2)[-1]
        copy2 = self.archive_root / run2.name / last2
        state = dict(done=False)

        def hash_then_flip(path):
            digest = real(path)
            if not state['done'] and os.path.normcase(str(path)).startswith(os.path.normcase(str(run2 / last2))):
                raw = bytearray(copy2.read_bytes())
                raw[0] ^= 0x01
                copy2.write_bytes(bytes(raw))
                state['done'] = True
            return digest
        with patch('studio_evidence_archive.file_sha256', side_effect=hash_then_flip):
            with self.assertRaises(Refusal) as caught:
                self.complete(run_ids=[run2.name])
        self.assertEqual(caught.exception.code, 'ARCHIVE_VERIFY_FAILED')
        self.assertEqual((run2 / last2).read_bytes(), original2[last2])

    def test_a_read_only_source_refuses_by_name_and_resumes(self):
        run = self.make_run(1, 'banker-done-1')
        self.apply()
        locked = run / 'log.GOAT'
        os.chmod(locked, 0o444)
        self.addCleanup(lambda: os.chmod(locked, 0o666) if locked.exists() else None)
        with self.assertRaises(Refusal) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'ARCHIVE_SOURCE_LOCKED')
        self.assertEqual(caught.exception.fields['path'], str(locked))
        self.assertTrue(locked.is_file())
        self.assertEqual(json.loads((run / runs.STUB).read_text())['state'], 'removing')
        os.chmod(locked, 0o666)
        self.complete()
        self.assertEqual(sorted(p.name for p in run.iterdir()), [runs.STUB])

    def test_removal_never_leaves_the_run_folder(self):
        run = self.make_run(1, 'banker-done-1')
        outside = self.source / 'keep-me.txt'
        outside.write_bytes(b'not a run file')
        for path in (outside, run, run / runs.STUB, run / '..' / 'keep-me.txt'):
            with self.subTest(path=str(path)), self.assertRaises(Refusal):
                runs._remove_source(self.source, run, path)
        with self.assertRaises(Refusal):
            runs._remove_source(self.common, run, run / 'log.GOAT')      # the run is not directly below that root
        self.assertTrue(outside.is_file() and (run / 'log.GOAT').is_file())


class EligibilityTests(RunFolderFixture):
    def test_active_queued_and_continuable_folders_are_refused(self):
        running = self.make_run(1, 'banker-running', status='running')
        queued = self.make_run(2, 'banker-queued', status='pending')
        cancelled = self.make_run(3, 'banker-cut', status='cancelled', outcomes=('native_completed', 'native_cancelled'))
        failed = self.make_run(4, 'banker-failed', status='failed', outcomes=('native_completed', 'native_error'))
        pointed = self.make_run(5, 'banker-pointed')
        driven = self.make_run(6, 'banker-driven')
        parent = self.make_run(7, 'banker-parent', status='cancelled', outcomes=('native_completed', 'native_cancelled'))
        self.make_run(8, 'banker-parent-r1', status='running')
        pointer = self.source / 'GOAT V1.49-Test-Demo-123-abc' / runs.POINTER_NAME
        pointer.parent.mkdir(parents=True)
        pointer.write_bytes(('[ActiveOptimizationRun]\r\nRunPath=GOAT\\%s\r\n' % pointed.name).encode('utf-16'))
        write_json(self.root / 'batch-drivers' / 'banker-driven.json',
                   dict(schema_version=2, binding=dict(job_id='banker-driven'), stopped=False, status='observing'))
        preview = self.preview()
        codes = self.skipped(preview)
        self.assertIn('ARCHIVE_NOT_FINISHED', codes[running.name])
        self.assertIn('ARCHIVE_NOT_FINISHED', codes[queued.name])
        self.assertEqual(codes[cancelled.name], ['ARCHIVE_CONTINUABLE'])
        self.assertEqual(codes[pointed.name], ['ARCHIVE_RUN_ACTIVE'])
        self.assertEqual(codes[driven.name], ['ARCHIVE_DRIVER_LIVE'])
        self.assertEqual(codes[parent.name], ['ARCHIVE_SUCCESSOR_ACTIVE'])
        # A failed member is a deliberate opt-in retry, not continue-able work: that folder is eligible.
        self.assertEqual([r['run_id'] for r in preview['eligible']], [failed.name])
        # Closing the cut batch for good (batch-pause-close) makes it eligible.
        with patch('studio_batch_pause.load', side_effect=lambda root, job: dict(state='closed') if job == 'banker-cut' else None):
            self.assertIn(cancelled.name, [r['run_id'] for r in self.preview()['eligible']])
        # --apply moves only the eligible one and never touches the others.
        before = {p.name: self.tree(p) for p in (running, queued, cancelled, pointed, driven, parent)}
        result = self.apply()
        self.assertEqual([r['run_id'] for r in result['results']], [failed.name])
        self.assertEqual({p.name: self.tree(p) for p in (running, queued, cancelled, pointed, driven, parent)}, before)

    def test_an_unattributed_folder_is_never_moved(self):
        stray = self.source / 'Rfff16576d9af'
        (stray / 'deploy').mkdir(parents=True)
        (stray / 'queue.GOAT').write_bytes(b'x')
        preview = self.preview()
        self.assertIn('Rfff16576d9af', [row['run_id'] for row in preview['not_attributable']])
        self.assertEqual(preview['eligible'], [])
        self.refused('ARCHIVE_NOTHING_TO_MOVE', self.apply)

    def test_keep_listed_and_newest_folders_are_skipped(self):
        old = self.make_run(1, 'banker-old', recorded_at='2026-09-01T00:00:00Z')
        pinned = self.make_run(2, 'banker-pinned', recorded_at='2026-09-02T00:00:00Z')
        newest = self.make_run(3, 'banker-new', recorded_at='2026-10-12T00:00:00Z')
        preview = self.preview(keep_list=self.keep_file(['banker-pinned']), keep_last=1)
        codes = self.skipped(preview)
        self.assertEqual(codes[pinned.name], ['ARCHIVE_KEEP_LISTED'])
        self.assertEqual(codes[newest.name], ['ARCHIVE_KEPT_RECENT'])
        self.assertEqual([r['run_id'] for r in preview['eligible']], [old.name])
        by_folder = self.preview(keep_list=self.keep_file([old.name]))
        self.assertEqual(self.skipped(by_folder)[old.name], ['ARCHIVE_KEEP_LISTED'])
        result = self.apply(keep_list=self.keep_file(['banker-pinned']), keep_last=1)
        self.assertEqual([r['run_id'] for r in result['results']], [old.name])
        self.assertFalse((pinned / runs.STUB).exists() or (newest / runs.STUB).exists())

    def test_an_unfinished_reader_blocks_and_a_finished_one_is_only_listed(self):
        run = self.make_run(1, 'banker-done-1')
        cited = str(run / 'deploy' / alias(10) / 'EURUSD' / (STEM + '.set'))
        write_json(self.root / 'catchups' / 'cu-live' / 'manifest.json',
                   dict(batch_id='cu-live', members=[dict(original=dict(set_path=cited))]))
        write_json(self.root / 'catchups' / 'cu-live' / 'state.json',
                   dict(schema_version=1, batch_id='cu-live', status='active', members=[dict(status='running')]))
        self.assertEqual(self.skipped(self.preview())[run.name], ['ARCHIVE_IN_FLIGHT_READER'])
        write_json(self.root / 'catchups' / 'cu-live' / 'state.json',
                   dict(schema_version=1, batch_id='cu-live', status='completed', members=[dict(status='completed')]))
        preview = self.preview()
        self.assertEqual(preview['eligible'][0]['cited_by'], ['cited by catch-up cu-live (finished)'])
        (self.root / 'catchups' / 'cu-live' / 'manifest.json').write_text('{broken')
        self.assertEqual(self.preview()['blockers'][0]['code'], 'ARCHIVE_CITATIONS_UNVERIFIABLE')


class TargetTests(RunFolderFixture):
    def test_the_floor_refuses(self):
        self.make_run(1, 'banker-done-1')
        usage = SimpleNamespace(total=100 * runs.GB, used=60 * runs.GB, free=40 * runs.GB)
        with patch('studio_run_folder_archive.shutil.disk_usage', return_value=usage):
            preview = self.preview(free_floor_gb=50)
            self.assertEqual(preview['blockers'][0]['code'], 'ARCHIVE_ROOT_FLOOR')
            self.assertEqual(preview['archive_free_bytes'], 40 * runs.GB)
            self.refused('ARCHIVE_ROOT_FLOOR', self.apply, free_floor_gb=50)
            self.assertEqual(self.preview(free_floor_gb=39)['blockers'], [])

    def test_a_resumed_copy_needs_only_the_missing_bytes_above_the_floor(self):
        """Codex on #237: after a crash mid-copy, the per-run floor check counts only what is still to copy."""
        run = self.make_run(1, 'banker-done-1')
        total = sum(len(raw) for raw in self.tree(run).values())
        real, calls = archive.copy_verified, []

        def crash_after_three(source, target, expected=None):
            calls.append(target)
            if len(calls) == 4:
                raise OSError(28, 'simulated crash mid-copy')
            return real(source, target, expected)
        with patch('studio_evidence_archive.copy_verified', side_effect=crash_after_three):
            with self.assertRaises(OSError):
                self.apply()
        missing = runs.missing_bytes(self.archive_root, run.name, runs.walk(run)[0])
        self.assertLess(missing, total)
        usage = SimpleNamespace(total=10 * missing, used=0, free=missing + 1)   # room for the rest, not for all of it again
        with patch('studio_run_folder_archive.shutil.disk_usage', return_value=usage):
            result = self.apply()
        self.assertEqual(result['skipped_at_copy'], [])
        self.assertEqual([(r['run_id'], r['reused']) for r in result['results']], [(run.name, 3)])

    def test_installations_sharing_common_files_share_one_lock(self):
        other = dict(self.agent.install, controller_state_root=str(self.f.base / 'other-installation'))
        first, second = runs.ArchiverLock(self.agent.install), runs.ArchiverLock(other)
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.path.parent, self.source)
        with first:
            with self.assertRaises(Refusal) as caught:
                with second:
                    pass
            self.assertEqual(caught.exception.code, 'ARCHIVE_ARCHIVER_BUSY')
            self.refused('ARCHIVE_ARCHIVER_BUSY', self.complete)

    def test_removable_drives_and_ram_disks_refuse(self):
        """Review item 1 on #237: GetDriveTypeW 2 (removable) and 6 (RAM disk) are never an archive root."""
        self.make_run(1, 'banker-done-1')
        import studio_build_migration as migration
        for kind in (2, 6):
            with self.subTest(drive_type=kind), patch.object(migration, '_drive_type', return_value=kind):
                self.assertEqual(self.preview()['blockers'][0]['code'], 'ARCHIVE_ROOT_REMOVABLE')
                self.refused('ARCHIVE_ROOT_REMOVABLE', self.apply)
        with patch.object(migration, '_drive_type', return_value=3):          # a fixed drive is fine
            self.assertEqual(self.preview()['blockers'], [])

    def test_the_same_volume_refuses(self):
        self.make_run(1, 'banker-done-1')
        with patch('studio_evidence_archive.volume_of', return_value=1):
            self.refused('ARCHIVE_ROOT_SAME_VOLUME', self.apply)
        self.assertEqual(self.preview(archive_root=self.source / 'inside')['blockers'][0]['code'], 'ARCHIVE_ROOT_UNAVAILABLE')


class ResolverTests(RunFolderFixture):
    def test_every_reader_finds_archived_files_under_their_cited_paths(self):
        from studio_batch_close import batch_exports
        from studio_export_qualification import scan_run
        from studio_native_observe import observe
        run = self.make_run(1, 'banker-done-1')
        package = self.root / 'packages' / 'banker-done-1'
        cited = run / 'deploy' / alias(10) / 'EURUSD' / (STEM + '.set')
        before = dict(observe=observe(package), exports=batch_exports(run), sets=collect_sets([str(run)]),
                      scan=scan_run(run, generated_at='t'), export=read_export(cited))
        self.apply()
        self.complete()
        self.assertFalse(cited.exists())
        target = self.archive_root / run.name
        self.assertEqual(runs.resolve(cited), target / cited.relative_to(run))
        self.assertEqual(runs.run_dir(run), target)
        self.assertEqual(runs.read_bytes(cited), (target / cited.relative_to(run)).read_bytes())
        after = observe(package)
        for key in ('observed_at',):
            after.pop(key); before['observe'].pop(key)
        self.assertEqual(after, before['observe'])                         # research-status, finish, resume read it
        self.assertEqual(after['native_run'], str(run.resolve()))
        self.assertEqual(batch_exports(run), before['exports'])            # batch-pause-close citations: cited paths
        self.assertEqual(collect_sets([str(run)]), before['sets'])          # evidence-scan / catchup-prepare
        self.assertEqual(scan_run(run, generated_at='t'), before['scan'])  # export-qualification (desktop runRoots)
        export = read_export(cited)
        self.assertEqual(export.pop('archived_set_path'), str(target / cited.relative_to(run)))
        self.assertEqual({k: v for k, v in export.items() if k not in ('csv_path', 'capture', 'run')},
                         {k: v for k, v in before['export'].items() if k not in ('csv_path', 'capture', 'run')})
        self.assertTrue(export['csv_path'].startswith(str(target)))
        # The archive drive unplugged: every reader refuses, never a silent fallback.
        target.rename(self.archive_root / 'moved-away')
        runs._MANIFESTS.clear()
        for call in (lambda: runs.resolve(cited), lambda: read_export(cited), lambda: observe(package)):
            with self.assertRaises(Refusal) as caught:
                call()
            self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')

    def test_a_same_size_corruption_refuses_every_directory_reader(self):
        """Codex on #237: files handed out through run_dir are verified when consumed, never read unchecked."""
        from studio_batch_close import batch_exports
        from studio_export_qualification import scan_run
        from studio_native_observe import observe
        run = self.make_run(1, 'banker-done-1')
        package = self.root / 'packages' / 'banker-done-1'
        cited = run / 'deploy' / alias(10) / 'EURUSD' / (STEM + '.set')
        self.apply()
        self.complete()
        target = self.archive_root / run.name

        def flip(relative):
            path = target / relative
            raw = bytearray(path.read_bytes())
            raw[-1] ^= 0x01
            path.write_bytes(bytes(raw))                       # same size, different bytes
            runs._VERIFIED.clear()                             # as a new process would
        for relative, calls in (('queue.GOAT', (lambda: observe(package),)),
                                (cited.relative_to(run).as_posix(),
                                 (lambda: batch_exports(run), lambda: scan_run(run, generated_at='t'), lambda: read_export(cited))),
                                ('export_settings.GOAT', (lambda: scan_run(run, generated_at='t'),))):
            original = (target / relative).read_bytes()
            flip(relative)
            for call in calls:
                with self.subTest(file=relative), self.assertRaises(Refusal) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
            (target / relative).write_bytes(original)
            runs._VERIFIED.clear()
        # A file in the archive folder that its manifest does not list is never read either.
        (target / 'deploy' / alias(10) / 'EURUSD' / 'planted.set').write_bytes(b'EA_Desc=x\r\n')
        with self.assertRaises(Refusal) as caught:
            batch_exports(run)
        self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')

    def test_readers_refuse_loudly_while_the_archive_is_offline_or_corrupt(self):
        """Review item 5 on #237: scan, research-status and window metrics re-raise ArchiveUnreachable instead of
        reading one unit fewer, "unknown" or "native_unreadable"."""
        from studio_evidence import scan
        from studio_research_status import batch_progress
        run = self.make_run(1, 'banker-done-1')
        job = self.queue[-1]
        cited = run / 'deploy' / alias(10) / 'EURUSD' / (STEM + '.set')
        before = batch_progress(self.root, self.agent.install, job, now=1.0)
        self.assertEqual(before['evidence'], 'native_queue')
        self.apply()
        self.complete()
        target = self.archive_root / run.name
        for name, relative, call in (
                ('scan', cited.relative_to(run), lambda: scan([str(run)])),
                ('research-status thresholds', Path('export_settings.GOAT'),
                 lambda: batch_progress(self.root, self.agent.install, job, now=1.0))):
            copy = target / relative
            original = copy.read_bytes()
            flipped = bytearray(original)
            flipped[-1] ^= 0x01
            copy.write_bytes(bytes(flipped))
            runs._VERIFIED.clear()
            with self.subTest(reader=name):
                with self.assertRaises(Refusal) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
            copy.write_bytes(original)
            runs._VERIFIED.clear()
        self.assertEqual(batch_progress(self.root, self.agent.install, job, now=1.0)['qualifying'], before['qualifying'])
        target.rename(self.archive_root / 'offline')            # the archive drive unplugged
        runs._MANIFESTS.clear()
        for name, call in (('scan', lambda: scan([str(run)])),
                           ('research-status', lambda: batch_progress(self.root, self.agent.install, job, now=1.0))):
            with self.subTest(reader=name + ' offline'):
                with self.assertRaises(Refusal) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')

    def test_a_path_outside_any_run_folder_is_never_touched(self):
        for path in (self.common / 'GOAT' / 'Workers' / 'x.set', self.common / 'GOAT' / 'R0123456789ab_x' / 'y.set',
                     self.common / 'Rabcdef012345' / 'y.set', Path('relative.set')):
            with self.subTest(path=str(path)):
                self.assertEqual(runs.resolve(path), path)
        self.assertEqual(runs.run_folder_of(self.source / 'Rabcdef012345' / 'deploy' / alias(1) / 'x.set'),
                         (self.source / 'Rabcdef012345', ('deploy', alias(1), 'x.set')))

    def test_a_malformed_stub_refuses(self):
        run = self.make_run(1, 'banker-done-1')
        (run / runs.STUB).write_text('{"schema": "something-else"}')
        with self.assertRaises(Refusal) as caught:
            runs.resolve(run / 'queue.GOAT')
        self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
        self.assertEqual(self.preview()['archived'][0]['state'], 'invalid_stub')


class CliTests(RunFolderFixture):
    def cli(self, *command):
        import demo_agent
        with patch('demo_agent.DemoAgent', return_value=self.agent), patch('builtins.print') as printed:
            code = demo_agent.main(['--installation', str(self.f.installation), *command])
        return code, json.loads(printed.call_args.args[0])

    def test_cli_previews_applies_and_completes_run_folders(self):
        run = self.make_run(1, 'banker-done-1')
        root = ('--archive-root', str(self.archive_root), '--keep-last', '0', '--free-floor-gb', '0')
        code, preview = self.cli('evidence-archive', '--run-folders', *root)
        self.assertEqual((code, preview['result']['applied'], [r['run_id'] for r in preview['result']['eligible']]),
                         (0, False, [run.name]))
        code, refused = self.cli('evidence-archive', '--run-folders', *root, '--apply', '--confirm')
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_KEEP_LIST_REQUIRED'))
        code, refused = self.cli('evidence-archive', '--run-folders', '--batch-id', 'x', *root)
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_MODE_CONFLICT'))
        code, refused = self.cli('evidence-archive', '--archive-root', str(self.archive_root))
        self.assertEqual(code, 1)
        self.assertIn('needs --batch-id', refused['error'])
        code, applied = self.cli('evidence-archive', '--run-folders', *root, '--apply', '--confirm', '--keep-list', str(self.keep_file()),
                                 '--run-id', run.name)
        self.assertEqual((code, [r['state'] for r in applied['result']['results']]), (0, ['archived']))
        code, done = self.cli('evidence-archive', '--run-folders', '--complete', '--confirm')
        self.assertEqual((code, [r['state'] for r in done['result']['results']]), (0, ['removed']))
        self.assertEqual(sorted(p.name for p in run.iterdir()), [runs.STUB])


class StudioPrepareTests(VolumePatches, unittest.TestCase):
    """Codex on #237: goat_studio prepare --set from an export in a completed archive still prepares it."""

    def setUp(self):
        import test_goat_studio
        self.p = test_goat_studio.PortableControllerTests('test_human_archive_name_collision_preserves_original_request')
        self.p.setUp()
        self.addCleanup(self.p.tearDown)
        self.patch_volumes(self.p.root / 'archive-volume')
        self.archive_root.mkdir()

    def test_prepare_reads_an_archived_export_and_records_its_cited_path(self):
        run = self.p.common / 'GOAT' / 'Rabcdef012345'
        source = run / 'deploy' / alias(1) / 'BROKER_EURUSD' / 'strategy.set'
        source.parent.mkdir(parents=True)
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        install = json.loads(self.p.path.read_text())
        runs.apply_run(run, self.archive_root, runs.walk(run)[0], install=install, now=1.0)
        runs.complete_run(self.p.common / 'GOAT', run, now=1.0)
        self.assertFalse(source.exists())
        c = self.p.bound()
        self.p.grant(c)
        config = self.p.root / 'settings.json'
        config.write_text(json.dumps(dict(tester=self.p.tester, export=self.p.exports)))
        c.prepare('beta-job', source, config)
        recorded = read_json(Path(c.root) / 'packages' / 'beta-job.source.json')
        self.assertEqual(recorded['set_path'], str(source.resolve()))
        self.assertEqual(recorded['set_sha256'], hashlib.sha256(runs.read_bytes(source)).hexdigest())


class B43MigGateTests(VolumePatches, MigrationCase):
    """GATE (goatai#2350 6156934300): b43mig-1's cited SET resolves after archive.

    b43mig-1 on the Banker PC is a build-migration catch-up (provenance build-migration-retest:B43, V1.49-EA-EXPERIENCE-33
    -> V1.49-BETA17-43, 148 members, finished). Each member cites its original export inside a run folder three ways:
    ``source_path``, ``original.set_path`` and ``build_migration.original_path`` (plus the plan's ``sets``), e.g.
    ``Common Files\\GOAT\\Ra260c972f9fc\\deploy\\R08b60f11c99b9d89d59e\\AUDCAD\\GOAT V1.49 AUDCAD,M1_Trds=324_..._ARF=0.367.set``,
    pinned by the SET, equity CSV and deals.csv sha256s. This fixture runs a real build-migration catch-up with the
    same id, run folder, member alias and symbol, archives that run folder, and resolves every citation."""

    RUN, MEMBER = 'Ra260c972f9fc', 'R08b60f11c99b9d89d59e'

    def setUp(self):
        super().setUp()
        self.common = Path(self.controller.install['common_files_root'])
        self.run = self.common / 'GOAT' / self.RUN
        (self.run / 'deploy').mkdir(parents=True)
        export_settings(self.run)
        self.cited = self.export(self.MEMBER, 'AUDCAD', self.history, build_id=SOURCE,
                                 name_metrics='Trds=324_Prf=315_DD=88_PF=1.97_SR=3.25_ARF=0.367')
        self.write_run_manifest(aliases=(self.MEMBER,), ea_sha256=OLD_EA)
        # The batch that made the run folder: a completed package and queue row of this installation.
        root = self.controller.root
        write_json(root / 'packages' / 'b43-source' / 'manifest.json', dict(native_run_relative='GOAT\\' + self.RUN, jobs=[]))
        with closing(sqlite3.connect(root / 'studio.sqlite')) as db:
            db.execute('CREATE TABLE studio_queues(binding TEXT PRIMARY KEY, jobs TEXT)')
            db.execute('INSERT INTO studio_queues VALUES(?,?)', (packed(dict(terminal_id='t', run_id='s')), json.dumps([dict(
                job_id='b43-source', status='completed', launch_intent=dict(recorded_at='2026-10-01T00:00:00Z'),
                completion=dict(member_outcomes=[dict(index=0, status='native_completed')]))])))
            db.commit()
        archive_root = self.root / 'archive-volume'
        archive_root.mkdir()
        self.patch_volumes(archive_root)

    def test_gate_b43mig_1_cited_set_resolves_after_archive(self):
        plan = self.mplan(sets=[self.cited])
        state, manifest = self.run_all('b43mig-1', plan)
        self.assertEqual(state['status'], 'completed')
        member = manifest['members'][0]
        citations = (member['source_path'], member['original']['set_path'], member['build_migration']['original_path'],
                     manifest['plan']['sets'][0])
        self.assertEqual(set(citations), {str(self.cited)})
        self.assertEqual(runs.run_folder_of(self.cited)[0].name, self.RUN)
        report_before = self.runner.report('b43mig-1')
        entry = plan['build_migration']['originals'][0]
        # The finished b43mig-1 is listed as a citation; it does not block.
        preview = runs.plan(self.controller.root, self.controller.install, self.archive_root, keep=[], keep_last=0,
                            floor_bytes=0, now=self.now)
        self.assertEqual(preview['blockers'], [])
        self.assertEqual([r['run_id'] for r in preview['eligible']], [self.RUN])
        self.assertEqual(preview['eligible'][0]['cited_by'], ['cited by catch-up b43mig-1 (finished)'])
        run = preview['eligible'][0]
        runs.apply_run(Path(run['path']), self.archive_root, run['files'], install=self.controller.install, now=self.now)
        runs.complete_run(runs.source_root(self.controller.install), self.run, now=self.now)
        self.assertFalse(self.cited.exists())
        self.assertEqual(sorted(p.name for p in self.run.iterdir()), [runs.STUB])

        # GATE: the cited SET resolves, under its cited path, with its recorded identity.
        export = read_export(str(self.cited))
        self.assertEqual(export['set_path'], str(self.cited))
        self.assertEqual(export['set_sha256'], member['source_sha256'])
        self.assertEqual(export['set_sha256'], member['original']['set_sha256'])
        self.assertEqual(export['values_sha256'], member['original']['values_sha256'])
        self.assertEqual(export['archived_set_path'], str(self.archive_root / self.RUN / self.cited.relative_to(self.run)))
        # The pinned drift baseline (SET, equity CSV, deals.csv) still verifies from the archive.
        self.assertEqual(bm.check_original(entry, str(self.cited)),
                         dict(set=entry['original_sha256'], csv=entry['original_csv_sha256'], deals=entry['original_deals_sha256']))
        # catchup-report reads the same, and re-validating b43mig-1's plan (which re-reads every original) still plans it.
        self.assertEqual(self.runner.report('b43mig-1'), report_before)
        self.assertEqual(self.runner.validate(plan)['member_count'], 1)
        self.assertEqual(read_json(self.runner.path('b43mig-1') / 'manifest.json')['members'][0]['original']['set_path'],
                         str(self.cited))
        # A new catch-up citing the archived folder still plans from it (evidence-scan walks the archive copy).
        from studio_catchup import evidence_scan
        scanned = evidence_scan([self.run], now=__import__('test_studio_catchup').AFTER_CLOSE)
        self.assertEqual([row['set_path'] for row in scanned['exports']], [str(self.cited)])
        # Review item 5: window metrics never drop the capture's deals silently when its archived copy is untrusted.
        from studio_window_metrics import export_window_metrics
        window = dict(from_date='2026.01.05', to_date='2026.09.25')
        self.assertEqual(export_window_metrics(str(self.cited), **window)['tradeSource'], 'capture_deals')
        capture = self.archive_root / self.RUN / self.cited.relative_to(self.run).parent / (self.cited.name[:-4] + '.goatseq') / 'manifest.json'
        raw = bytearray(capture.read_bytes())
        raw[-2] ^= 0x01
        capture.write_bytes(bytes(raw))
        runs._VERIFIED.clear()
        with self.assertRaises(Refusal) as caught:
            export_window_metrics(str(self.cited), **window)
        self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')


if __name__ == '__main__':
    unittest.main()
