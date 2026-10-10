"""evidence-archive (goatai#2350 6086117953): move a finished or closed batch's evidence off C:, never delete it.

The fixture is shaped like the Ops PC's controller state: ``native-evidence/<job>-<attempt16>.jsonl`` logs and their
``.history.jsonl`` / ``.uncommitted`` siblings, ``native-evidence/receipt-archive/<request>.<binding12>.receipt.json``
files with their digest-form receipt rows in ``studio.sqlite``, another job whose files share the batch's prefix, and
a catch-up's hashed ``evidence/c.<10 hex>/`` folder. Every file is a temporary fixture; nothing touches MT5, a
terminal, the installed suite state or a real archive drive (the second volume is simulated by ``volume_of``).
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
import studio_catchup as sc
import studio_evidence_archive as archive
from studio_evidence_log import RECORD_KEYS
from studio_receipt_digest import binding_tag
from studio_refusal import Refusal
import studio_trial_journal as journal
from test_studio_batch_close import ATTEMPT, G20Fixture, JOB, MEMBERS, RUN, write_json

OTHER = JOB + '-r1'               # another job whose file names start with the batch's prefix
EARLIER = 'b' * 64                # an earlier attempt of the batch: its log is no longer named by the row
CATCHUP = 'cu1'
FAKE_GUID = '\\\\?\\Volume{00000000-0000-0000-0000-00000000a5c1}\\'   # never mounted: lookups by it fail


def envelope(job_id, attempt, seq, evidence):
    raw = json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    return dict(evidence_id=sha([job_id, attempt, seq, digest]), seq=seq, job_id=job_id, attempt_id=attempt,
                evidence_sha256=digest, evidence=evidence)


def observation(started):
    return dict(native=dict(members=[dict(index=i, status='native_ongoing' if i in started else 'native_queued')
                                     for i in range(MEMBERS)]), status='running')


def lines(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b''.join((json.dumps(v, sort_keys=True, separators=(',', ':')) + '\n').encode() for v in values))


class ArchiveFixture(G20Fixture):
    """The g20 batch, closed (finish), with its evidence moved out of the queue row into the real file layout."""

    def setUp(self):
        super().setUp()
        self.archive_root = self.f.base / 'archive-volume'
        self.archive_root.mkdir()
        self.evidence = self.root / 'native-evidence'
        self.binding = packed(dict(terminal_id=self.agent.session['terminal_id'], run_id=self.agent.session['run_id']))
        self.tag = binding_tag(self.binding)
        stem = JOB + '-' + ATTEMPT[:16]
        self.log = self.evidence / (stem + '.jsonl')
        lines(self.log, [envelope(JOB, ATTEMPT, 1, observation({0})), envelope(JOB, ATTEMPT, 2, observation({0, 1}))])
        self.history = self.evidence / (stem + '.history.jsonl')
        lines(self.history, [dict(observation({0}), attempt_id=ATTEMPT, native=dict(observation({0})['native'],
                                                                                     studio_source=dict(job_id=JOB)))])
        (self.evidence / (stem + '.jsonl.uncommitted')).write_bytes(b'{"tail":1}\n')
        lines(self.evidence / (JOB + '-' + EARLIER[:16] + '.jsonl'), [envelope(JOB, EARLIER, 1, observation(set()))])
        # Names the batch but proves nothing: kept and listed.
        (self.evidence / (JOB + '-notes.jsonl')).write_bytes(b'free text\n')
        lines(self.evidence / (JOB + '-' + 'c' * 16 + '.jsonl'), [envelope('someone-else', 'c' * 64, 1, observation(set()))])
        # Another job's own files: neither moved nor listed.
        lines(self.evidence / (OTHER + '-' + 'd' * 16 + '.jsonl'), [envelope(OTHER, 'd' * 64, 1, observation(set()))])
        self.receipts = self.evidence / 'receipt-archive'
        self.receipts.mkdir()
        rows = [(JOB + '-batch', 'queue.enqueue_batch', False), (JOB + '-reserve', 'queue.reserve', False),
                (JOB + '-reserve-r1', 'queue.reserve', False), (JOB + '-cancel', 'queue.cancel', False),
                (JOB + '-batch-r2', 'queue.enqueue_batch', True), (OTHER + '-batch', 'queue.enqueue_batch', False)]
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            db.execute('CREATE TABLE studio_receipts(binding TEXT, request_id TEXT, payload_hash TEXT, receipt TEXT)')
            for request_id, command, legacy in rows:
                if request_id == JOB + '-cancel':
                    continue                     # an archive file with no stored receipt row
                state = dict(revision=3, queue=[]) if legacy else dict(revision=3, queue_digest=dict(sha256='0' * 64, job_count=1))
                db.execute('INSERT INTO studio_receipts VALUES(?,?,?,?)', (self.binding, request_id, 'p' * 64, packed(dict(
                    request_id=request_id, command=command, status='applied', state=state, execution_effect=False))))
            db.commit()
        for request_id, _, _ in rows:
            (self.receipts / ('%s.%s.receipt.json' % (request_id, self.tag))).write_bytes(('{"receipt":"%s"}' % request_id).encode() * 50)
        (self.receipts / ('%s.%s.receipt.json' % (JOB + '-reserve', 'f' * 12))).write_bytes(b'{"other session"}')
        self.job.pop('native_evidence_history')
        self.job.update(native_evidence_log=dict(path=str(self.log), entries=2, bytes=self.log.stat().st_size),
                        native_evidence_archive=dict(path=str(self.history), entries=1, sha256='0' * 64))
        self.queue = [self.job, dict(job_id=OTHER, status='completed', configuration_sha256='e' * 64)]
        self.write_queue()
        self.write_record(state='closed', closed_mode='finish', closed_at='2026-10-08T22:53:20Z')
        self.volumes = patch('studio_evidence_archive.volume_of', side_effect=self.volume)
        self.volumes.start(); self.addCleanup(self.volumes.stop)
        # The file system and drive type checks run for real (the fixture volume is a local NTFS drive); the volume
        # GUID is a fixed fake one that is mounted nowhere, so no test finds an archive on the real C: by GUID.
        for name, value in (('volume_guid_of', FAKE_GUID), ('volume_mounts', [])):
            patcher = patch('studio_evidence_archive.' + name, return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)

    def volume(self, path):
        return 2 if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(self.archive_root))) else 1

    def files(self):
        found = super().files()
        found.update({str(p): p.read_bytes() for p in self.archive_root.rglob('*') if p.is_file()})
        return found

    def keep_file(self, value=()):
        path = self.f.base / 'keep.json'
        path.write_text(json.dumps(list(value) if not isinstance(value, dict) else value))
        return path

    def run_archive(self, batch_id=JOB, **kw):
        kw.setdefault('confirm', True)
        kw.setdefault('apply', True)
        if 'keep_list' not in kw:
            kw['keep_list'] = self.keep_file()          # --apply needs a keep-list; an empty one is the usual case
        return self.agent.evidence_archive(batch_id, kw.pop('archive_root', self.archive_root), **kw)

    def preview(self, batch_id=JOB, **kw):
        kw.setdefault('keep_list', self.keep_file())
        return self.agent.evidence_archive(batch_id, kw.pop('archive_root', self.archive_root), **kw)

    def write_runner(self, folder, run_id, status, members):
        write_json(self.root / folder / run_id / 'manifest.json', dict(batch_id=run_id, members=members))
        write_json(self.root / folder / run_id / 'state.json', dict(schema_version=1, batch_id=run_id, status=status,
                                                                    members=[dict(status='completed' if status == 'completed'
                                                                                  else 'pending')] * len(members)))

    def refused_archive(self, code, batch_id=JOB, **kw):
        return self.refused(code, self.run_archive, batch_id, **kw)

    def refused(self, code, call, *args, **kw):
        before = self.files()
        with self.assertRaises(Refusal) as caught:
            call(*args, **kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(self.files(), before, 'a refusal wrote something')
        return caught.exception

    def complete(self, batch_id=JOB, **kw):
        kw.setdefault('confirm', True)
        return self.agent.evidence_archive(batch_id, complete=True, **kw)

    def archive_and_complete(self, batch_id=JOB):
        self.run_archive(batch_id)
        return self.complete(batch_id)

    @staticmethod
    def forget():
        """What a new process sees: no cached pointer index, manifest or sha256 verification (a test rewrites files in
        place within one clock tick, which an mtime-keyed cache cannot see; os.replace writers get a new file ID)."""
        archive._INDEX.clear(); archive._OPENED.clear(); archive._VERIFIED.clear()

    def actions(self):
        log = self.agent.state_root / 'actions.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []

    def folder(self, batch_id=JOB):
        return self.archive_root / 'state' / batch_id

    def owned(self):
        stem = 'native-evidence/' + JOB + '-'
        return sorted([stem + ATTEMPT[:16] + '.jsonl', stem + ATTEMPT[:16] + '.history.jsonl',
                       stem + ATTEMPT[:16] + '.jsonl.uncommitted', stem + EARLIER[:16] + '.jsonl']
                      + ['native-evidence/receipt-archive/%s.%s.receipt.json' % (JOB + s, self.tag)
                         for s in ('-batch', '-reserve', '-reserve-r1')])


class PreviewTests(ArchiveFixture):
    def test_preview_lists_exactly_the_proven_files_and_writes_nothing(self):
        before = self.files()
        preview = self.preview()
        self.assertEqual(self.files(), before)
        self.assertFalse(preview['applied'])
        self.assertTrue(preview['ready'], preview['blockers'])
        self.assertEqual((preview['citations'], preview['cited_by'], preview['keep_list_checked']), ([], [], True))
        self.assertEqual([f['relative_path'] for f in preview['files']], self.owned())
        proofs = {Path(f['relative_path']).name: f['proof'] for f in preview['files']}
        self.assertEqual(proofs[self.log.name], 'queue_row:native_evidence_log')
        self.assertEqual(proofs[self.history.name], 'queue_row:native_evidence_archive')
        self.assertEqual(proofs[self.log.name + '.uncommitted'], 'uncommitted_tail_of:' + self.log.name)
        self.assertEqual(proofs[JOB + '-' + EARLIER[:16] + '.jsonl'], 'first_line_identity')
        self.assertEqual(proofs['%s-batch.%s.receipt.json' % (JOB, self.tag)], 'receipt_row:queue.enqueue_batch@' + self.tag)
        unknown = {Path(f['relative_path']).name: f['reason'] for f in preview['not_attributable']}
        self.assertEqual(set(unknown), {JOB + '-notes.jsonl', JOB + '-' + 'c' * 16 + '.jsonl',
                                        '%s-reserve.%s.receipt.json' % (JOB, 'f' * 12),
                                        '%s-cancel.%s.receipt.json' % (JOB, self.tag),
                                        '%s-batch-r2.%s.receipt.json' % (JOB, self.tag)})
        self.assertIn('still embeds the queue', unknown['%s-batch-r2.%s.receipt.json' % (JOB, self.tag)])
        self.assertIn('no stored receipt row', unknown['%s-cancel.%s.receipt.json' % (JOB, self.tag)])
        self.assertFalse(any(OTHER in f['relative_path'] for f in preview['files'] + preview['not_attributable']))
        size = sum((self.root / f).stat().st_size for f in self.owned())
        self.assertEqual(preview['bytes'], size)
        self.assertEqual(preview['required_free_bytes'], size + archive.MARGIN_BYTES)
        self.assertEqual(preview['archive_dir'], str(self.folder()))

    def test_preview_reports_blockers_instead_of_refusing(self):
        write_json(self.root / 'seed-active.json', dict(status='active', batch_id='seedhunt-1'))
        preview = self.preview()
        self.assertFalse(preview['ready'])
        self.assertEqual([b['code'] for b in preview['blockers']], ['ARCHIVE_TERMINAL_BUSY'])

    def test_preview_works_without_a_keep_list_and_names_it_as_required(self):
        before = self.files()
        preview = self.agent.evidence_archive(JOB, self.archive_root)
        self.assertEqual(self.files(), before)
        self.assertEqual((preview['file_count'], preview['keep_list_checked']), (7, False))
        self.assertEqual([b['code'] for b in preview['blockers']], ['ARCHIVE_KEEP_LIST_REQUIRED'])


class ApplyTests(ArchiveFixture):
    def test_apply_copies_verifies_writes_manifest_and_pointer_and_keeps_every_source(self):
        sources = {rel: (self.root / rel).read_bytes() for rel in self.owned()}
        kept = {str(p): p.read_bytes() for p in self.evidence.rglob('*') if p.is_file()
                and p.relative_to(self.root).as_posix() not in sources}
        result = self.run_archive()
        self.assertTrue(result['applied'])
        self.assertEqual((result['result']['copied'], result['result']['removed'], result['result']['verified'],
                          result['result']['sources_kept']), (7, 0, 7, 7))
        # --apply STOPS after the pointer: every source is still here, byte-identical (the safety copy).
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in self.owned()}, sources)
        self.assertEqual(journal._history(self.root, self.job), {0, 1})        # readers already follow the pointer
        self.assertEqual(archive.resolve(self.root, self.log), self.folder() / 'native-evidence' / self.log.name)
        completed = self.complete()
        self.assertTrue(completed['completed'])
        self.assertEqual((completed['result']['removed'], completed['result']['verified']), (7, 7))
        folder = self.folder()
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema'], archive.SCHEMA)
        self.assertEqual((manifest['batch_id'], manifest['kind'], manifest['installation']), (JOB, 'native', 'state'))
        self.assertEqual(manifest['controller_revision']['module_sha256'], archive.file_sha256(archive.__file__))
        self.assertTrue(manifest['created_at'].endswith('Z'))
        # The manifest matches the files: every archived file is listed with its bytes and sha256, nothing else is there.
        self.assertEqual(sorted(e['relative_path'] for e in manifest['files']), self.owned())
        for entry in manifest['files']:
            copy = folder / entry['relative_path']
            self.assertEqual(copy.read_bytes(), sources[entry['relative_path']])
            self.assertEqual((entry['bytes'], entry['sha256']), (copy.stat().st_size, hashlib.sha256(copy.read_bytes()).hexdigest()))
            self.assertEqual(entry['source_path'], str(self.root / entry['relative_path']))
            self.assertFalse((self.root / entry['relative_path']).exists())
        on_disk = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())
        self.assertEqual(on_disk, sorted(self.owned() + ['manifest.json']))
        pointer = json.loads(archive.pointer_path(self.root, JOB).read_text(encoding='utf-8'))
        self.assertEqual(pointer['manifest_sha256'], hashlib.sha256((folder / 'manifest.json').read_bytes()).hexdigest())
        self.assertEqual(pointer['archive_dir'], str(folder))
        self.assertEqual(pointer['schema'], archive.POINTER_SCHEMA)
        self.assertEqual(pointer['volume_guid'], FAKE_GUID)            # optional field; the schema stays v1
        self.assertTrue(pointer['archive_relative'].endswith('archive-volume/state/' + JOB))
        # Every other file is byte-identical and still in place.
        self.assertEqual({path: Path(path).read_bytes() for path in kept}, kept)
        self.assertEqual([(a['operation'], a['phase'], a['files'], a['removed']) for a in self.actions()],
                         [('evidence_archive', 'archived', 7, 0), ('evidence_archive', 'completed', 7, 7)])

    def test_a_rerun_is_idempotent_and_copies_nothing_twice(self):
        self.run_archive()
        log = str(self.agent.state_root / 'actions.jsonl')
        before = {path: data for path, data in self.files().items() if path != log}
        again = self.run_archive()
        self.assertEqual((again['result']['changed'], again['result']['copied'], again['result']['removed']), (False, 0, 0))
        self.assertEqual(again['result']['verified'], 7)
        self.assertEqual({path: data for path, data in self.files().items() if path != log}, before)
        actions = [json.loads(line) for line in Path(log).read_text().splitlines()]
        self.assertEqual([a['phase'] for a in actions], ['archived', 'verified'])
        self.assertTrue(again['archived'])
        # Another archive root for the same batch refuses: it already lives somewhere.
        other = self.f.base / 'second-volume'; other.mkdir()
        self.refused_archive('ARCHIVE_ALREADY_ARCHIVED', archive_root=other)

    def test_interrupted_copy_then_resume_completes_without_duplicates(self):
        real, calls = archive.copy_verified, []

        def crash_after_two(source, target):
            if len(calls) == 2:
                raise KeyboardInterrupt('power cut')
            calls.append(source)
            return real(source, target)
        with patch('studio_evidence_archive.copy_verified', side_effect=crash_after_two):
            with self.assertRaises(KeyboardInterrupt):
                self.run_archive()
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        self.assertTrue(all((self.root / rel).is_file() for rel in self.owned()), 'a source went before the move finished')
        (self.folder() / 'native-evidence' / ('left-over' + archive.TEMP_MARK)).write_bytes(b'partial')
        result = self.run_archive()
        self.assertEqual((result['result']['copied'], result['result']['reused']), (5, 2))
        files = sorted(p.relative_to(self.folder()).as_posix() for p in self.folder().rglob('*') if p.is_file())
        self.assertEqual(files, sorted(self.owned() + ['manifest.json']))
        self.assertTrue(all((self.root / rel).exists() for rel in self.owned()))
        self.complete()
        self.assertFalse(any((self.root / rel).exists() for rel in self.owned()))

    def test_interrupted_removal_then_resume_completes_and_readers_use_the_archive_meanwhile(self):
        self.run_archive()
        real, removed = archive._unlink, []

        def crash_after_three(path):
            if len(removed) == 3:
                raise KeyboardInterrupt('power cut')
            removed.append(path)
            real(path)
        with patch('studio_evidence_archive._unlink', side_effect=crash_after_three):
            with self.assertRaises(KeyboardInterrupt):
                self.complete()
        self.assertEqual(sum((self.root / rel).exists() for rel in self.owned()), 4)
        self.assertEqual(journal._history(self.root, self.job), {0, 1})        # read through the pointer
        result = self.complete()
        self.assertEqual((result['result']['changed'], result['result']['removed'], result['result']['already_removed']), (True, 4, 3))
        self.assertFalse(any((self.root / rel).exists() for rel in self.owned()))
        self.assertEqual(self.complete()['result']['removed'], 0)
        self.assertEqual(self.run_archive()['result']['removed'], 0)       # a re-run of --apply only re-verifies

    def test_a_failed_verification_keeps_the_source_and_writes_no_pointer(self):
        before = {rel: (self.root / rel).read_bytes() for rel in self.owned()}
        with patch('studio_evidence_archive._readback', return_value='0' * 64):
            with self.assertRaises(Refusal) as caught:
                self.run_archive()
        self.assertEqual(caught.exception.code, 'ARCHIVE_VERIFY_FAILED')
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in self.owned()}, before)
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        self.assertFalse(any(p.is_file() for p in self.archive_root.rglob('*')), 'an unverified copy was left behind')

    def test_a_source_that_changed_after_its_copy_refuses_complete_and_nothing_is_removed(self):
        self.run_archive()
        self.log.write_bytes(self.log.read_bytes() + b'{"late":1}\n')
        error = self.refused('ARCHIVE_SOURCE_CHANGED', self.complete)
        self.assertEqual(error.fields['relative_path'], 'native-evidence/' + self.log.name)
        self.assertTrue(all((self.root / rel).is_file() for rel in self.owned()))


class ReaderTests(ArchiveFixture):
    def test_trial_journal_history_and_member_identities_follow_the_pointer(self):
        from studio_batch_close import member_identities
        self.assertEqual(journal._history(self.root, self.job), {0, 1})
        done_before = member_identities(self.root, self.job, self.job['completion']['member_outcomes'])
        self.archive_and_complete()
        self.assertFalse(self.log.exists())
        self.assertEqual(archive.resolve(self.root, self.log), self.folder() / 'native-evidence' / self.log.name)
        self.assertEqual(journal._history(self.root, self.job), {0, 1})
        self.assertEqual(member_identities(self.root, self.job, self.job['completion']['member_outcomes']), done_before)

    def test_the_trial_journal_is_identical_through_the_pointer_and_refuses_while_unreachable(self):
        before = journal.journal(self.root, self.agent.install)
        self.assertTrue(any(e['batch_id'] == JOB for e in before['entries']))
        self.run_archive()
        self.assertEqual(json.dumps(journal.journal(self.root, self.agent.install), sort_keys=True),
                         json.dumps(before, sort_keys=True))
        self.complete()
        self.assertEqual(json.dumps(journal.journal(self.root, self.agent.install), sort_keys=True),
                         json.dumps(before, sort_keys=True))
        self.archive_root.rename(self.f.base / 'unplugged')
        with self.assertRaises(archive.ArchiveUnreachable):
            journal.journal(self.root, self.agent.install)

    def test_an_unreachable_archive_refuses_clearly_and_reads_nothing_else(self):
        self.run_archive()
        self.archive_root.rename(self.f.base / 'unplugged')
        with self.assertRaises(archive.ArchiveUnreachable) as caught:
            journal._history(self.root, self.job)
        self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
        self.assertIn('Reconnect the archive drive', str(caught.exception))
        (self.f.base / 'unplugged').rename(self.archive_root)
        manifest = self.folder() / 'manifest.json'
        manifest.write_text(json.dumps(dict(json.loads(manifest.read_text(encoding='utf-8')), kind='tampered')), encoding='utf-8')
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'no longer matches its pointer'):
            journal._history(self.root, self.job)

    def test_the_log_writer_refuses_an_archived_batch(self):
        from types import SimpleNamespace
        from studio_evidence_log import append
        self.archive_and_complete()
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            with self.assertRaises(Refusal) as caught:
                append(SimpleNamespace(db=db), JOB, ATTEMPT, dict(native={}), previous=self.job['native_evidence_log'])
        self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVED')
        self.assertFalse(self.log.exists())


class RefusalTests(ArchiveFixture):
    def test_confirm_is_required_to_apply(self):
        self.refused_archive('ARCHIVE_CONFIRM_REQUIRED', confirm=False)

    def test_running_pending_paused_pausing_and_unsettled_batches_refuse(self):
        self.queue = [dict(self.job, status='running'), self.queue[1]]; self.write_queue()
        error = self.refused_archive('ARCHIVE_TERMINAL_BUSY')
        self.assertIn('ARCHIVE_NOT_FINISHED', [b['code'] for b in error.fields['blockers']])
        for status, state in (('pending', 'pending'), ('verifying', 'unsettled')):
            job = {key: value for key, value in self.job.items() if status != 'pending' or key != 'launch_intent'}
            self.queue = [dict(job, status=status), self.queue[1]]; self.write_queue()
            if status == 'verifying':
                with patch.object(self.agent, '_close_busy', return_value=None), \
                        patch('demo_agent.ACTIVE_NATIVE_STATUSES', ('reserved', 'starting', 'running')):
                    self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED').fields['batch_state'], state)
            else:
                self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED').fields['batch_state'], state)
        self.queue = [self.job, self.queue[1]]; self.write_queue()
        for record_state, state in (('paused', 'paused'), ('pause_failed', 'paused'), ('pausing', 'pausing')):
            self.write_record(state=record_state)
            self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED').fields['batch_state'], state)
        self.write_record(state='closed', closed_mode='finish')
        self.assertTrue(self.run_archive()['applied'])

    def test_a_finished_batch_without_a_pause_is_archived(self):
        pause_path = self.root / 'batch-pauses' / (JOB + '.json')
        pause_path.unlink()
        self.queue = [dict(self.job, status='completed'), self.queue[1]]; self.write_queue()
        self.assertTrue(self.run_archive()['applied'])

    def test_in_row_history_must_be_compacted_first(self):
        self.queue = [dict(self.job, native_evidence_history=[observation({0})]), self.queue[1]]; self.write_queue()
        self.refused_archive('ARCHIVE_COMPACT_FIRST')

    def test_seed_slot_fixed_task_live_driver_or_the_lock_refuse(self):
        write_json(self.root / 'seed-active.json', dict(status='active', batch_id='seedhunt-1'))
        self.assertIn('seed slot', str(self.refused_archive('ARCHIVE_TERMINAL_BUSY')))
        (self.root / 'seed-active.json').unlink()
        self.write_queue(fixed_task=0)
        self.assertIn('fixed task', str(self.refused_archive('ARCHIVE_TERMINAL_BUSY')))
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            db.execute('UPDATE studio_fixed_tasks SET released=1'); db.commit()
        with self.agent._exclusive():
            self.refused_archive('ARCHIVE_TERMINAL_BUSY')
        worker = self.root / 'demo-agent' / 'workers' / 'g21.json'
        write_json(worker, dict(batch_id='g21', nonce='n' * 32, pid=5))
        with patch.object(self.agent, '_worker_alive', return_value=True):
            self.refused_archive('ARCHIVE_TERMINAL_BUSY')

    def test_a_batch_active_in_another_session_refuses(self):
        other = packed(dict(terminal_id='terminal-one', run_id='older-session'))
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            db.execute('INSERT INTO studio_queues VALUES(?,?)', (other, json.dumps([dict(job_id='old', status='running')])))
            db.commit()
        self.assertIn('old', str(self.refused_archive('ARCHIVE_TERMINAL_BUSY')))

    def lock(self, status, active):
        return [dict(lock_id='l' * 64, strategy_key='banker', status=status, active=active,
                     candidate=[dict(symbol='EURUSD', timeframe='M1', set_sha256=self.export_sha)])]

    def test_a_batch_cited_by_a_finished_foos_read_moves_and_stays_readable_through_the_pointer(self):
        self.write_runner('catchups', 'cu-g20', 'completed', [dict(original=dict(set_path=str(self.export),
                                                                                  set_sha256=self.export_sha))])
        self.write_runner('holdups', 'h-g20', 'completed', [dict(source_path='C:\\library\\copy.set', source_sha256=self.export_sha)])
        preview = self.preview()
        self.assertTrue(preview['ready'], preview['blockers'])
        self.assertEqual(preview['cited_by'], ['cited by catch-up cu-g20 (finished)', 'cited by hold-up test h-g20 (finished)'])
        self.assertEqual({(c['run_id'], c['in_flight']) for c in preview['citations']}, {('cu-g20', False), ('h-g20', False)})
        result = self.run_archive()
        self.assertEqual((result['result']['removed'], result['result']['sources_kept']), (0, 7))
        self.assertEqual(len(result['citations']), 2)
        self.complete()
        self.assertFalse(self.log.exists())
        self.assertEqual(journal._history(self.root, self.job), {0, 1})     # read through the pointer

    def test_a_revealed_lock_is_listed_and_an_active_lock_refuses(self):
        for status in ('locked', 'revealable', 'revealing'):
            with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=self.lock(status, True))):
                error = self.refused_archive('ARCHIVE_HELDOUT_LOCK_ACTIVE')
            self.assertEqual(error.fields['locks'][0]['lock_status'], status)
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=self.lock('revealed', False))):
            preview = self.preview()
            self.assertTrue(preview['ready'], preview['blockers'])
            self.assertEqual(preview['cited_by'], ['cited by held-out lock llllllllllll (revealed)'])
            self.assertTrue(self.run_archive()['applied'])

    def test_an_in_flight_reader_refuses_and_names_the_reading_run(self):
        member = dict(original=dict(set_path=str(self.export), set_sha256='z' * 64))      # by a path inside the run folder
        for status, state in (('prepared', 'pending'), ('active', 'running')):
            self.write_runner('catchups', 'cu-next', status, [member])
            error = self.refused_archive('ARCHIVE_IN_FLIGHT_READER')
            self.assertEqual((error.fields['reader'], error.fields['reader_kind'], error.fields['reader_state']),
                             ('cu-next', 'catch-up', state))
            self.assertIn('cu-next', str(error))
        write_json(self.root / 'catchups' / 'cu-next' / 'pause.json', dict(batch_id='cu-next'))
        self.write_runner('catchups', 'cu-next', 'stopped', [member])
        self.assertEqual(self.refused_archive('ARCHIVE_IN_FLIGHT_READER').fields['reader_state'], 'paused')
        shutil.rmtree(self.root / 'catchups' / 'cu-next')
        self.write_runner('seeds', 'seed-next', 'active', [dict(source_path=str(self.export), source_sha256=self.export_sha)])
        self.assertEqual(self.refused_archive('ARCHIVE_IN_FLIGHT_READER').fields['reader_kind'], 'seed hunt')
        self.write_runner('seeds', 'seed-next', 'completed', [dict(source_path=str(self.export), source_sha256=self.export_sha)])
        self.assertTrue(self.run_archive()['applied'])

    def test_unreadable_citations_still_fail_closed(self):
        with patch('studio_heldout.read_registry', return_value=dict(state='unavailable', error='broken chain', locks=[])):
            self.refused_archive('ARCHIVE_CITATIONS_UNVERIFIABLE')
        (self.root / 'catchups' / 'bad').mkdir(parents=True)
        (self.root / 'catchups' / 'bad' / 'manifest.json').write_text('{not json')
        self.assertIn('unreadable', str(self.refused_archive('ARCHIVE_CITATIONS_UNVERIFIABLE')))

    def test_apply_without_a_keep_list_refuses(self):
        self.assertIn('may be empty', str(self.refused_archive('ARCHIVE_KEEP_LIST_REQUIRED', keep_list=None)))

    def test_keep_list_refuses_by_batch_or_run_folder_and_a_bad_list_refuses(self):
        keep = self.keep_file([JOB])
        self.assertEqual(self.refused_archive('ARCHIVE_KEEP_LISTED', keep_list=keep).fields['keep_entry'], JOB)
        keep = self.keep_file(dict(keep=[RUN]))
        self.refused_archive('ARCHIVE_KEEP_LISTED', keep_list=keep)
        keep.write_text('{not json')
        self.refused_archive('ARCHIVE_KEEP_LIST_INVALID', keep_list=keep)
        keep.write_text(json.dumps([1, 2]))
        self.refused_archive('ARCHIVE_KEEP_LIST_INVALID', keep_list=keep)
        self.assertTrue(self.run_archive(keep_list=self.keep_file(['another-batch']))['applied'])

    def test_archive_root_same_volume_missing_not_writable_or_short_of_space_refuse(self):
        self.volumes.stop()
        with patch('studio_evidence_archive.volume_of', return_value=1):
            self.refused_archive('ARCHIVE_ROOT_SAME_VOLUME')
        self.volumes.start()
        self.refused_archive('ARCHIVE_ROOT_UNAVAILABLE', archive_root=self.archive_root / 'missing')
        self.refused_archive('ARCHIVE_ROOT_INVALID', archive_root=Path('relative-folder'))
        with patch('studio_evidence_archive._probe_writable', side_effect=PermissionError('read-only')):
            self.refused_archive('ARCHIVE_ROOT_NOT_WRITABLE')
        size = sum((self.root / rel).stat().st_size for rel in self.owned())
        usage = shutil.disk_usage(self.archive_root)._replace(free=size + archive.MARGIN_BYTES - 1)
        with patch('studio_evidence_archive.shutil.disk_usage', return_value=usage):
            error = self.refused_archive('ARCHIVE_ROOT_LOW_SPACE')
        self.assertEqual(error.fields['required_bytes'], size + archive.MARGIN_BYTES)

    def test_unknown_batch_seed_hunt_and_non_demo_refuse(self):
        with self.assertRaises(Refusal) as caught:
            self.run_archive('nobody')
        self.assertEqual(caught.exception.code, 'ARCHIVE_UNKNOWN_BATCH')
        write_json(self.root / 'seeds' / 'seedhunt-1' / 'state.json', dict(status='completed', members=[]))
        self.assertEqual(self.refused_archive('ARCHIVE_UNSUPPORTED_KIND', 'seedhunt-1').fields['kind'], 'seed')
        self.agent.session['demo_only'] = False
        self.refused_archive('ARCHIVE_NOT_DEMO')

    def test_nothing_attributable_refuses(self):
        for rel in self.owned():
            (self.root / rel).unlink()
        self.refused_archive('ARCHIVE_NOTHING_TO_MOVE')


class CliTests(ArchiveFixture):
    def cli(self, *command):
        import demo_agent
        with patch('demo_agent.DemoAgent', return_value=self.agent), patch('builtins.print') as printed:
            code = demo_agent.main(['--installation', str(self.f.installation), *command])
        return code, json.loads(printed.call_args.args[0])

    def test_cli_previews_then_applies_and_refuses_without_confirm(self):
        code, preview = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root))
        self.assertEqual((code, preview['ok'], preview['result']['applied'], preview['result']['file_count']), (0, True, False, 7))
        code, refused = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root), '--apply')
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_CONFIRM_REQUIRED'))
        code, refused = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root), '--apply', '--confirm')
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_KEEP_LIST_REQUIRED'))
        self.assertTrue((self.root / 'native-evidence' / self.log.name).is_file())
        code, applied = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root), '--apply', '--confirm',
                                 '--keep-list', str(self.keep_file()))
        self.assertEqual((code, applied['result']['applied'], applied['result']['result']['removed'],
                          applied['result']['result']['sources_kept']), (0, True, 0, 7))
        self.assertTrue(self.log.is_file())
        code, refused = self.cli('evidence-archive', '--batch-id', JOB, '--complete')
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_CONFIRM_REQUIRED'))
        code, refused = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root), '--apply',
                                 '--complete', '--confirm', '--keep-list', str(self.keep_file()))
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_MODE_CONFLICT'))
        code, completed = self.cli('evidence-archive', '--batch-id', JOB, '--complete', '--confirm')
        self.assertEqual((code, completed['result']['completed'], completed['result']['result']['removed']), (0, True, 7))
        self.assertFalse(self.log.exists())

    def test_cli_restore_and_repoint(self):
        self.archive_and_complete()
        moved = self.f.base / 'second-volume' / 'copy'
        shutil.copytree(self.folder(), moved)
        code, refused = self.cli('evidence-repoint', '--batch-id', JOB, '--archive-dir', str(moved))
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_CONFIRM_REQUIRED'))
        code, repointed = self.cli('evidence-repoint', '--batch-id', JOB, '--archive-dir', str(moved), '--confirm')
        self.assertEqual((code, repointed['result']['repointed'], repointed['result']['result']['archive_dir']), (0, True, str(moved)))
        code, restored = self.cli('evidence-restore', '--batch-id', JOB, '--confirm')
        self.assertEqual((code, restored['result']['restored'], restored['result']['result']['restored']), (0, True, 7))
        self.assertTrue(self.log.is_file())
        code, refused = self.cli('evidence-restore', '--batch-id', JOB, '--confirm')
        self.assertEqual((code, refused['refusal_code']), (1, 'ARCHIVE_NOT_ARCHIVED'))

    def test_contract_is_registered(self):
        from goat_studio import OPERATION_CONTRACTS
        contract = OPERATION_CONTRACTS['evidence-archive']
        self.assertEqual(contract['required'], ['batch-id'])
        self.assertEqual(contract['preview_required'], ['archive-root'])
        self.assertIn('keep-list', contract['optional'])
        self.assertIn('complete', contract['optional'])
        self.assertIn('--apply STOPS', contract['effect'])
        self.assertIn('goat.exe demo evidence-archive --batch-id <id> --complete --confirm', contract['demo_lane'])
        self.assertEqual(contract['apply_required'], ['archive-root', 'confirm', 'keep-list'])
        self.assertEqual(contract['complete_required'], ['confirm'])
        self.assertEqual(OPERATION_CONTRACTS['evidence-restore']['required'], ['batch-id', 'confirm'])
        self.assertEqual(OPERATION_CONTRACTS['evidence-repoint']['required'], ['batch-id', 'archive-dir', 'confirm'])
        self.assertTrue({'ARCHIVE_ROOT_FILESYSTEM', 'ARCHIVE_ROOT_REMOTE', 'ARCHIVE_SOURCE_LINK', 'ARCHIVE_MANIFEST_INVALID',
                         'ARCHIVE_NOT_ARCHIVED', 'ARCHIVE_RESTORE_CONFLICT', 'ARCHIVE_REPOINT_MISMATCH',
                         'ARCHIVE_MODE_CONFLICT'} <= archive.CODES)
        self.assertTrue(set(archive.CODES) >= {'ARCHIVE_CONFIRM_REQUIRED', 'ARCHIVE_NOT_FINISHED', 'ARCHIVE_TERMINAL_BUSY',
                                               'ARCHIVE_HELDOUT_LOCK_ACTIVE', 'ARCHIVE_IN_FLIGHT_READER',
                                               'ARCHIVE_CITATIONS_UNVERIFIABLE', 'ARCHIVE_KEEP_LIST_REQUIRED',
                                               'ARCHIVE_KEEP_LISTED', 'ARCHIVE_ROOT_SAME_VOLUME',
                                               'ARCHIVE_ROOT_NOT_WRITABLE', 'ARCHIVE_ROOT_LOW_SPACE'})
        self.assertFalse({'ARCHIVE_CITED_FOOS_READ', 'ARCHIVE_CITED_SELECTION'} & archive.CODES)


class CatchupArchiveTests(ArchiveFixture):
    """A finished catch-up: its hashed evidence folder moves; versions(), evidence_folder() and the report follow."""

    def setUp(self):
        super().setUp()
        self.make_catchup()

    def make_catchup(self):
        runs = self.root / 'catchups' / CATCHUP
        write_json(runs / 'state.json', dict(schema_version=1, batch_id=CATCHUP, status='completed',
                                             members=[dict(member_id='m1', alias='cu1_00001', status='completed')]))
        write_json(runs / 'manifest.json', dict(batch_id=CATCHUP, members=[dict(alias='cu1_00001', original=dict(
            set_path=str(self.export), set_sha256=self.export_sha))]))
        self.cfolder = self.root / 'evidence' / sc.evidence_key(CATCHUP)
        write_json(self.cfolder / sc.EVIDENCE_FOLDER_RECORD, dict(schema=sc.EVIDENCE_FOLDER_SCHEMA, catchup_id=CATCHUP))
        member = self.cfolder / '00001'
        self.retest = member / 'GOAT EURUSD,M1_Trds=40.set'
        self.retest.parent.mkdir(parents=True)
        self.retest.write_bytes('Grid_Size=0\r\n'.encode('utf-16'))
        (member / 'GOAT EURUSD,M1_Trds=40.csv').write_bytes(b'time,equity\n' * 100)
        (member / 'GOAT EURUSD,M1_Trds=40.goatseq').mkdir()
        (member / 'GOAT EURUSD,M1_Trds=40.goatseq' / 'deals.csv').write_bytes(b'deal\n' * 10)
        write_json(member / 'evidence-version.json', dict(
            schema=sc.VERSION_SCHEMA, kind=sc.VERSION_KIND, catchup_id=CATCHUP, values_sha256='v' * 64, symbol='EURUSD',
            period='M1', evidence_start='2025-01-01', evidence_end='2026-10-02', created_utc='2026-10-03T00:00:00+00:00',
            original=dict(set_path=str(self.export), set_sha256=self.export_sha),
            retest=dict(set_path=str(self.retest), set_sha256=hashlib.sha256(self.retest.read_bytes()).hexdigest(),
                        csv_path=str(member / 'GOAT EURUSD,M1_Trds=40.csv'),
                        capture=dict(path=str(member / 'GOAT EURUSD,M1_Trds=40.goatseq' / 'manifest.json'), status='complete')),
            verdict=dict(verdict='held_up')))

    def test_catchup_evidence_moves_and_versions_follow_the_pointer(self):
        before = sc.versions(self.root)
        self.assertEqual(len(before), 1)
        preview = self.preview(CATCHUP)
        self.assertTrue(preview['ready'], preview['blockers'])
        self.assertEqual(preview['kind'], 'catchup')
        self.assertEqual(preview['file_count'], 5)
        self.assertEqual(preview['folders'], ['evidence/' + sc.evidence_key(CATCHUP)])
        self.run_archive(CATCHUP)
        moved = self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP)
        # --apply leaves the local folder as the safety copy: it is never read twice, the archive is read instead.
        self.assertTrue(self.cfolder.exists())
        kept = sc.versions(self.root)
        self.assertEqual(len(kept), 1)
        self.assertEqual(sc.plain(kept[0]['version_path']), str(moved / '00001' / 'evidence-version.json'))
        self.assertEqual(sc.plain(sc.evidence_folder(self.root, CATCHUP)), str(moved))
        self.complete(CATCHUP)
        self.assertFalse(self.cfolder.exists())
        after = sc.versions(self.root)
        self.assertEqual(len(after), 1)
        self.assertEqual(sc.plain(after[0]['version_path']), str(moved / '00001' / 'evidence-version.json'))
        self.assertEqual(after[0]['retest']['set_path'], str(moved / '00001' / self.retest.name))
        self.assertEqual(after[0]['original']['set_path'], str(self.export))          # Common Files: never moved
        self.assertTrue(after[0]['retest']['capture']['path'].startswith(str(moved)))
        self.assertEqual(sc.plain(sc.evidence_folder(self.root, CATCHUP)), str(moved))
        # The stored record bytes are unchanged; only the reader's copy is relocated.
        stored = json.loads((moved / '00001' / 'evidence-version.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['retest']['set_path'], str(self.retest))
        self.archive_root.rename(self.f.base / 'unplugged')
        with self.assertRaises(archive.ArchiveUnreachable):
            sc.versions(self.root)

    def test_a_legacy_catchup_folder_moves_and_is_found_again(self):
        shutil.move(str(self.cfolder), str(self.root / 'evidence' / CATCHUP))
        (self.root / 'evidence' / CATCHUP / sc.EVIDENCE_FOLDER_RECORD).unlink()
        self.run_archive(CATCHUP)
        self.assertEqual(sc.evidence_folder(self.root, CATCHUP), self.folder(CATCHUP) / 'evidence' / CATCHUP)
        self.assertEqual(len(sc.versions(self.root)), 1)
        self.complete(CATCHUP)
        self.assertFalse((self.root / 'evidence' / CATCHUP).exists())
        self.assertEqual(sc.evidence_folder(self.root, CATCHUP), self.folder(CATCHUP) / 'evidence' / CATCHUP)
        self.assertEqual(len(sc.versions(self.root)), 1)

    def test_an_unfinished_catchup_an_in_flight_reader_or_an_active_lock_refuses(self):
        state = self.root / 'catchups' / CATCHUP / 'state.json'
        value = json.loads(state.read_text())
        write_json(state, dict(value, status='active'))
        self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED', CATCHUP).fields['batch_state'], 'running')
        write_json(state, dict(value, status='stopped', members=[dict(value['members'][0], status='pending')]))
        self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED', CATCHUP).fields['batch_state'], 'paused')
        write_json(state, value)
        # A hold-up test that re-tests this catch-up's re-test SET: in flight while it runs, a listed citation after.
        reader = [dict(source_path=str(self.retest), source_sha256='x' * 64)]
        self.write_runner('holdups', 'h1', 'active', reader)
        error = self.refused_archive('ARCHIVE_IN_FLIGHT_READER', CATCHUP)
        self.assertEqual((error.fields['reader'], error.fields['reader_kind']), ('h1', 'hold-up test'))
        self.write_runner('holdups', 'h1', 'completed', reader)
        self.assertEqual(self.preview(CATCHUP)['cited_by'], ['cited by hold-up test h1 (finished)'])
        retest_sha = hashlib.sha256(self.retest.read_bytes()).hexdigest()
        locks = [dict(lock_id='l' * 64, status='revealing', active=True, candidate=[dict(set_sha256=retest_sha)])]
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=locks)):
            self.refused_archive('ARCHIVE_HELDOUT_LOCK_ACTIVE', CATCHUP)
        # The lock this catch-up revealed blocks while it is still revealing, not once it is revealed.
        write_json(self.root / 'catchups' / CATCHUP / 'manifest.json',
                   dict(json.loads((self.root / 'catchups' / CATCHUP / 'manifest.json').read_text()), heldout_reveal=dict(lock_id='r' * 64)))
        reveal = [dict(lock_id='r' * 64, status='revealing', active=True, candidate=[])]
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=reveal)):
            self.refused_archive('ARCHIVE_HELDOUT_LOCK_ACTIVE', CATCHUP)
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=[dict(reveal[0], status='revealed', active=False)])):
            self.assertTrue(self.run_archive(CATCHUP)['applied'])
        self.assertEqual(len(sc.versions(self.root)), 1)

    def test_the_catchup_report_names_the_archived_version(self):
        from types import SimpleNamespace
        runner = sc.CatchupRunner.__new__(sc.CatchupRunner)
        runner.c = SimpleNamespace(root=self.root)
        version = self.cfolder / '00001' / 'evidence-version.json'
        self.assertEqual(runner._version_path(dict(version_path=str(version))), str(version))
        self.run_archive(CATCHUP)
        self.assertEqual(runner._version_path(dict(version_path=str(version))),
                         str(self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP) / '00001' / 'evidence-version.json'))

    def test_the_build_migration_report_routes_record_path_through_the_pointer(self):
        import studio_build_migration as migration
        from types import SimpleNamespace
        record = self.cfolder / '00001' / migration.RECORD_FILE
        write_json(record, dict(kind=migration.KIND, schema=migration.RECORD_SCHEMA))
        result_path = self.f.base / 'migration-result.json'
        write_json(result_path, dict(kind=migration.KIND, status=migration.RESULT_STATUS, summary=dict(drift='within'),
                                     record_path=str(record)))
        spec = dict(alias='cu1_00001', tester=dict(Symbol='EURUSD', Period='M1', ToDate='2026.10.03'),
                    original=dict(evidence_end='2026-09-25'),
                    build_migration=dict(provenance=migration.provenance('V1.49-BETA17-43'), source_build='V1.49-BETA17-41',
                                         target_build='V1.49-BETA17-43', original_path=str(self.export),
                                         original_sha256=self.export_sha))
        manifest = dict(batch_id=CATCHUP, members=[spec], evidence_end=dict(iso='2026-10-02'), output_root=None,
                        build_migration=dict(provenance=migration.provenance('V1.49-BETA17-43'), target_build='V1.49-BETA17-43'))
        state = dict(status='completed', members=[dict(status='completed', result=dict(path=str(result_path)))])
        runner = sc.CatchupRunner.__new__(sc.CatchupRunner)
        runner.c = SimpleNamespace(root=self.root)
        report_root = self.f.base / 'report'; report_root.mkdir()
        self.assertEqual(runner._migration_report(report_root, manifest, state)['members'][0]['record_path'], str(record))
        self.run_archive(CATCHUP)
        moved = self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP) / '00001' / migration.RECORD_FILE
        self.assertEqual(runner._migration_report(report_root, manifest, state)['members'][0]['record_path'], str(moved))
        moved.write_bytes(b'{}')                               # a corrupt archived record refuses, never reads stale
        with self.assertRaises(archive.ArchiveUnreachable):
            runner._migration_report(report_root, manifest, state)


class VerifyOnReadTests(ArchiveFixture):
    """Claude-Mac on #205, must-fix 1 and 2: the archive is the only copy, so a bad archived file refuses loudly."""

    def archived_log(self):
        return self.folder() / 'native-evidence' / self.log.name

    def test_a_corrupt_archived_log_behind_a_good_manifest_refuses_instead_of_history_unavailable(self):
        self.archive_and_complete()
        before = journal._history(self.root, self.job)
        copy = self.archived_log()
        raw = copy.read_bytes()
        copy.write_bytes(b'x' * len(raw))                     # same size, not JSON: was "history unavailable"
        self.forget()                                          # a new process hashes it again
        for call in (lambda: journal._history(self.root, self.job), lambda: journal.journal(self.root, self.agent.install)):
            with self.assertRaises(archive.ArchiveUnreachable) as caught:
                call()
            self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
            self.assertIn('differs from its manifest', str(caught.exception))
        copy.write_bytes(raw + b'\n')                          # another size: refused before any read
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'its manifest lists'):
            journal._history(self.root, self.job)
        copy.write_bytes(raw)
        self.assertEqual(journal._history(self.root, self.job), before)

    def test_a_missing_archived_log_behind_a_good_manifest_refuses(self):
        self.archive_and_complete()
        self.archived_log().unlink()
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'cannot be read'):
            journal._history(self.root, self.job)
        from studio_batch_close import member_identities
        with self.assertRaises(archive.ArchiveUnreachable):
            member_identities(self.root, self.job, self.job['completion']['member_outcomes'])

    def test_any_read_error_after_the_pointer_redirects_refuses(self):
        self.archive_and_complete()
        with patch('studio_evidence_log.read', side_effect=ValueError('truncated line')):
            with self.assertRaises(archive.ArchiveUnreachable) as caught:
                journal._history(self.root, self.job)
        self.assertIn('truncated line', str(caught.exception))
        # A log that was never archived still reads as "history unavailable", as before.
        self.assertIsNone(journal._history(self.root, dict(self.job, native_evidence_log=dict(path=str(self.root / 'nowhere.jsonl')),
                                                           native_evidence_archive=None)))

    def test_a_malformed_pointer_refuses_every_reader(self):
        self.archive_and_complete()
        path = archive.pointer_path(self.root, JOB)
        good = path.read_bytes()
        value = json.loads(good)
        for bad in (b'{not json', json.dumps(dict(value, schema='other')).encode(),
                    json.dumps(dict(value, files=value['files'] + ['native-evidence/../../studio.sqlite'])).encode(),
                    json.dumps(dict(value, files=value['files'] + ['packages/x.json'])).encode(),
                    json.dumps(dict(value, manifest_sha256='nope')).encode()):
            path.write_bytes(bad); self.forget()
            with self.assertRaises(archive.ArchiveUnreachable, msg=bad[:40]):
                journal._history(self.root, self.job)
            with self.assertRaises(archive.ArchiveUnreachable):
                sc.versions(self.root)                       # every batch's reader, not only this batch's
            with self.assertRaises(Refusal) as caught:
                self.preview()
            self.assertEqual(caught.exception.code, 'EVIDENCE_ARCHIVE_UNREACHABLE')
        path.write_bytes(good); self.forget()
        self.assertEqual(journal._history(self.root, self.job), {0, 1})

    def test_size_on_every_read_and_sha256_once_per_process(self):
        self.archive_and_complete()
        archive._VERIFIED.clear()
        calls = []
        real = archive.file_sha256

        def counted(path):
            calls.append(Path(str(path)).name)
            return real(path)
        with patch('studio_evidence_archive.file_sha256', side_effect=counted):
            journal._history(self.root, self.job)
            journal._history(self.root, self.job)
        self.assertEqual(calls.count(self.log.name), 1, calls)
        # A changed size is caught on the next read even though the sha256 is cached.
        copy = self.archived_log()
        copy.write_bytes(copy.read_bytes()[:-1])
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'its manifest lists'):
            journal._history(self.root, self.job)

    def test_the_pointer_files_must_be_listed_by_the_manifest(self):
        self.archive_and_complete()
        path = archive.pointer_path(self.root, JOB)
        value = json.loads(path.read_bytes())
        path.write_text(json.dumps(dict(value, files=value['files'] + ['native-evidence/' + JOB + '-extra.jsonl'])), encoding='utf-8')
        self.forget()
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'which the manifest does not list'):
            journal._history(self.root, self.job)
        path.write_text(json.dumps(dict(value, folders=['evidence/c.0000000000'])), encoding='utf-8')
        self.forget()
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'which the manifest does not list'):
            journal._history(self.root, self.job)

    def test_a_corrupt_or_missing_archived_catchup_record_refuses_versions_and_evidence_folder(self):
        CatchupArchiveTests.make_catchup(self)
        self.archive_and_complete(CATCHUP)
        moved = self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP)
        version = moved / '00001' / 'evidence-version.json'
        raw = version.read_bytes()
        self.assertEqual(len(sc.versions(self.root)), 1)
        version.write_bytes(b' ' * len(raw)); self.forget()    # same size, other bytes (a new process re-hashes)
        with self.assertRaises(archive.ArchiveUnreachable):
            sc.versions(self.root)
        version.unlink()                                      # a missing record never reads as "no version"
        with self.assertRaises(archive.ArchiveUnreachable):
            sc.versions(self.root)
        version.write_bytes(raw)
        self.assertEqual(len(sc.versions(self.root)), 1)
        record = moved / sc.EVIDENCE_FOLDER_RECORD
        record.write_bytes(b'#' * record.stat().st_size); self.forget()
        with self.assertRaises(archive.ArchiveUnreachable):
            sc.evidence_folder(self.root, CATCHUP)
        record.unlink()
        with self.assertRaises(archive.ArchiveUnreachable):
            sc.evidence_folder(self.root, CATCHUP)


class DurabilityTests(ArchiveFixture):
    """Must-fix 3: only NTFS/ReFS local roots, fsync after rename, removal as its own verified step."""

    def test_exfat_fat32_and_unknown_file_systems_refuse_in_preview_and_apply(self):
        for name in ('exFAT', 'FAT32', 'FAT'):
            with patch('studio_evidence_archive.filesystem_of', return_value=name):
                preview = self.preview()
                self.assertEqual([b['code'] for b in preview['blockers']], ['ARCHIVE_ROOT_FILESYSTEM'])
                self.assertEqual(self.refused_archive('ARCHIVE_ROOT_FILESYSTEM').fields['filesystem'], name)
        with patch('studio_evidence_archive.filesystem_of', side_effect=OSError(21, 'not ready')):
            self.refused_archive('ARCHIVE_ROOT_FILESYSTEM')
        with patch('studio_evidence_archive.filesystem_of', return_value='ReFS'):
            self.assertTrue(self.preview()['ready'])
        self.assertEqual(archive.filesystem_of(archive.volume_root_of(self.archive_root)).upper(), 'NTFS')   # the real call

    def test_remote_drives_refuse_through_the_build_migration_drive_type_check(self):
        import studio_build_migration as migration
        for kind in (4, 0, 1, 5):
            with patch.object(migration, '_drive_type', return_value=kind) as asked:
                self.assertEqual(self.refused_archive('ARCHIVE_ROOT_REMOTE').fields['drive_type'], kind)
            self.assertTrue(asked.called)
        with patch.object(migration, '_drive_type', return_value=2):         # a removable NTFS drive is fine
            self.assertTrue(self.preview()['ready'])

    def test_each_copy_manifest_and_pointer_is_fsynced_again_after_its_rename(self):
        synced = []
        real = archive._fsync_file
        with patch('studio_evidence_archive._fsync_file', side_effect=lambda path: (synced.append(archive._plain(path)), real(path))):
            self.run_archive()
        expected = [str(self.folder() / rel) for rel in self.owned()] + [str(self.folder() / 'manifest.json'),
                                                                         str(archive.pointer_path(self.root, JOB))]
        self.assertEqual(sorted(synced), sorted(expected))

    def test_complete_refuses_and_removes_nothing_when_an_archived_file_is_missing_or_corrupt(self):
        self.run_archive()
        copy = self.folder() / 'native-evidence' / self.log.name
        raw = copy.read_bytes()
        copy.unlink()
        self.assertIn('Every source is kept', str(self.refused('ARCHIVE_VERIFY_FAILED', self.complete)))
        copy.write_bytes(b'0' * len(raw))                   # same size, other bytes: only a fresh sha256 catches it
        self.refused('ARCHIVE_VERIFY_FAILED', self.complete)
        self.assertTrue(all((self.root / rel).is_file() for rel in self.owned()))
        copy.write_bytes(raw)
        self.assertEqual(self.complete()['result']['removed'], 7)

    def test_complete_rereads_every_archived_file_from_disk(self):
        self.run_archive()
        journal._history(self.root, self.job)                # warms the per-process sha256 cache
        hashed = []
        real = archive.file_sha256
        with patch('studio_evidence_archive.file_sha256', side_effect=lambda path: (hashed.append(str(path)), real(path))[1]):
            self.complete()
        folder = os.path.normcase(str(self.folder()))
        self.assertEqual(len([p for p in hashed if os.path.normcase(archive._plain(p)).startswith(folder)]), 7)

    def test_complete_needs_confirm_a_pointer_an_idle_terminal_and_never_combines_with_apply(self):
        self.refused('ARCHIVE_NOT_ARCHIVED', self.complete)
        self.run_archive()
        self.refused('ARCHIVE_CONFIRM_REQUIRED', self.complete, confirm=False)
        self.refused('ARCHIVE_MODE_CONFLICT', self.run_archive, complete=True)
        with self.agent._exclusive():
            self.refused('ARCHIVE_TERMINAL_BUSY', self.complete)
        write_json(self.root / 'seed-active.json', dict(status='active', batch_id='seedhunt-1'))
        self.assertIn('seed slot', str(self.refused('ARCHIVE_TERMINAL_BUSY', self.complete)))
        (self.root / 'seed-active.json').unlink()
        self.agent.session['demo_only'] = False
        self.refused('ARCHIVE_NOT_DEMO', self.complete)

    def test_a_crash_between_manifest_and_pointer_is_completed_by_a_rerun(self):
        real = archive._write_json_file

        def crash_at_pointer(path, value):
            if Path(path).parent.name == 'archived':
                raise KeyboardInterrupt('power cut')
            return real(path, value)
        with patch('studio_evidence_archive._write_json_file', side_effect=crash_at_pointer):
            with self.assertRaises(KeyboardInterrupt):
                self.run_archive()
        self.assertTrue((self.folder() / 'manifest.json').is_file())
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        self.assertEqual(archive.resolve(self.root, self.log), self.log)          # no pointer: the local copy is read
        manifest = (self.folder() / 'manifest.json').read_bytes()
        again = self.run_archive()
        self.assertEqual((again['result']['copied'], again['result']['reused']), (0, 7))
        self.assertEqual((self.folder() / 'manifest.json').read_bytes(), manifest)   # reused, not rewritten
        self.assertEqual(self.complete()['result']['removed'], 7)

    def test_a_crash_between_manifest_and_pointer_with_a_different_manifest_refuses_cleanly(self):
        real = archive._write_json_file

        def crash_at_pointer(path, value):
            if Path(path).parent.name == 'archived':
                raise KeyboardInterrupt('power cut')
            return real(path, value)
        with patch('studio_evidence_archive._write_json_file', side_effect=crash_at_pointer):
            with self.assertRaises(KeyboardInterrupt):
                self.run_archive()
        path = self.folder() / 'manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        path.write_text(json.dumps(dict(value, files=value['files'][1:])), encoding='utf-8')
        self.refused_archive('ARCHIVE_MANIFEST_CONFLICT')
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        self.assertTrue(all((self.root / rel).is_file() for rel in self.owned()))


class ManifestValidationTests(ArchiveFixture):
    """Should-fix 5: every manifest entry is validated before any source is removed."""

    def forge(self, entry):
        """A manifest the pointer still matches (both rewritten), with one extra entry."""
        path = self.folder() / 'manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        path.write_text(json.dumps(dict(value, files=value['files'] + [entry])), encoding='utf-8')
        pointer_file = archive.pointer_path(self.root, JOB)
        pointer = json.loads(pointer_file.read_text(encoding='utf-8'))
        pointer_file.write_text(json.dumps(dict(pointer, manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest())),
                                encoding='utf-8')
        self.forget()

    def test_traversal_absolute_foreign_and_unnamed_entries_refuse_before_any_removal(self):
        self.run_archive()
        outside = self.f.base / 'outside.txt'
        outside.write_bytes(b'not evidence')
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        for relative in ('native-evidence/../../outside.txt', str(outside), 'C:/outside.txt', 'packages/' + JOB + '/manifest.json',
                         'native-evidence/' + JOB + '-not-named.jsonl'):
            with self.subTest(relative=relative):
                self.run_archive_reset()
                self.forge(dict(relative_path=relative, bytes=12, sha256=digest))
                self.refused('ARCHIVE_MANIFEST_INVALID', self.complete)
                with self.assertRaises(archive.ArchiveUnreachable):
                    journal._history(self.root, self.job)
                self.assertTrue(outside.is_file())
                self.assertTrue(all((self.root / rel).is_file() for rel in self.owned()))

    def run_archive_reset(self):
        """Put back the archive's own manifest and pointer between sub-tests."""
        if not hasattr(self, '_clean'):
            self._clean = ((self.folder() / 'manifest.json').read_bytes(), archive.pointer_path(self.root, JOB).read_bytes())
        (self.folder() / 'manifest.json').write_bytes(self._clean[0])
        archive.pointer_path(self.root, JOB).write_bytes(self._clean[1])
        self.forget()


class LinkTests(ArchiveFixture):
    """Should-fix 6: a junction or symbolic link in the source walk is never followed and refuses."""

    def make_link(self, link, target):
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError):
            try:
                os.symlink(str(target), str(link), target_is_directory=True)
            except (OSError, NotImplementedError):
                return False
        self.addCleanup(lambda: os.rmdir(link) if os.path.lexists(link) else None)
        return True

    def test_a_junction_in_the_catchup_evidence_tree_refuses_and_is_never_walked(self):
        CatchupArchiveTests.make_catchup(self)
        elsewhere = self.f.base / 'elsewhere'
        elsewhere.mkdir()
        (elsewhere / 'secret.bin').write_bytes(b'not this catch-up\'s evidence')
        link = self.cfolder / '00001' / 'linked'
        if self.make_link(link, elsewhere):
            preview = self.preview(CATCHUP)
        else:                                               # no junction or symlink can be created: simulate the check
            with patch('studio_evidence_archive._is_link', side_effect=lambda p: Path(p).name == 'GOAT EURUSD,M1_Trds=40.goatseq'):
                preview = self.preview(CATCHUP)
        self.assertIn('ARCHIVE_SOURCE_LINK', [b['code'] for b in preview['blockers']])
        self.assertFalse(any('secret.bin' in f['relative_path'] for f in preview['files']))
        if os.path.lexists(link):
            self.assertEqual(self.refused_archive('ARCHIVE_SOURCE_LINK', CATCHUP).fields['links'],
                             ['evidence/%s/00001/linked' % sc.evidence_key(CATCHUP)])
            self.assertTrue((elsewhere / 'secret.bin').is_file())

    def test_a_linked_native_log_refuses(self):
        with patch('studio_evidence_archive._is_link', side_effect=lambda p: Path(str(p)).name == self.log.name):
            preview = self.preview()
            self.assertIn('ARCHIVE_SOURCE_LINK', [b['code'] for b in preview['blockers']])
            self.refused_archive('ARCHIVE_SOURCE_LINK')


class RestoreRepointTests(ArchiveFixture):
    """Must-fix 4: evidence-restore, evidence-repoint, and the volume GUID that finds a re-lettered drive."""

    def restore(self, **kw):
        kw.setdefault('confirm', True)
        return self.agent.evidence_restore(JOB, **kw)

    def repoint(self, folder, **kw):
        kw.setdefault('confirm', True)
        return self.agent.evidence_repoint(JOB, folder, **kw)

    def test_restore_copies_back_verified_retires_the_pointer_and_keeps_the_archive(self):
        sources = {rel: (self.root / rel).read_bytes() for rel in self.owned()}
        self.archive_and_complete()
        self.refused('ARCHIVE_CONFIRM_REQUIRED', self.restore, confirm=False)
        result = self.restore()
        self.assertEqual((result['result']['restored'], result['result']['already_local'], result['result']['verified']), (7, 0, 7))
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in self.owned()}, sources)
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        retired = list((self.root / 'native-evidence' / 'archived' / 'retired').glob(JOB + '.*.json'))
        self.assertEqual(len(retired), 1)
        record = json.loads(retired[0].read_text(encoding='utf-8'))
        self.assertEqual((record['retired_reason'], record['archive_dir'], record['restored_files']), ('restored', str(self.folder()), 7))
        self.assertTrue((self.folder() / 'native-evidence' / self.log.name).is_file())        # the archive copy is kept
        self.assertEqual(archive.resolve(self.root, self.log), self.log)                     # readers read the local copy
        self.assertEqual(journal._history(self.root, self.job), {0, 1})
        archive.refuse_archived(self.root, JOB)                                              # the writer may append again
        self.assertEqual(self.actions()[-1]['phase'], 'restored')
        self.refused('ARCHIVE_NOT_ARCHIVED', self.restore)

    def test_restore_after_apply_reuses_identical_sources_and_refuses_a_different_one(self):
        self.run_archive()
        self.log.write_bytes(self.log.read_bytes() + b'{"late":1}\n')
        error = self.refused('ARCHIVE_RESTORE_CONFLICT', self.restore)
        self.assertEqual(error.fields['relative_path'], 'native-evidence/' + self.log.name)
        self.assertTrue(archive.pointer_path(self.root, JOB).exists())
        self.log.write_bytes(self.log.read_bytes()[:-len(b'{"late":1}\n')])
        result = self.restore()
        self.assertEqual((result['result']['restored'], result['result']['already_local']), (0, 7))

    def test_restore_refuses_a_corrupt_archive_and_restores_nothing(self):
        self.archive_and_complete()
        copy = self.folder() / 'native-evidence' / self.log.name
        copy.write_bytes(b'0' * copy.stat().st_size)
        self.refused('ARCHIVE_VERIFY_FAILED', self.restore)
        self.assertFalse(any((self.root / rel).exists() for rel in self.owned()))

    def test_restore_and_repoint_run_under_the_terminal_lock(self):
        self.run_archive()
        with self.agent._exclusive():
            self.refused('ARCHIVE_TERMINAL_BUSY', self.restore)
            self.refused('ARCHIVE_TERMINAL_BUSY', self.repoint, self.folder())
        self.queue = [dict(self.job), dict(job_id='busy', status='running')]; self.write_queue()
        self.refused('ARCHIVE_TERMINAL_BUSY', self.restore)

    def test_repoint_accepts_only_a_verified_copy_and_rewrites_the_pointer(self):
        self.archive_and_complete()
        old = self.folder()
        new = self.f.base / 'new-volume' / 'state' / JOB
        shutil.copytree(old, new)
        # Mismatches: no manifest, another manifest, a missing file, a corrupt file.
        empty = self.f.base / 'empty'; empty.mkdir()
        self.refused('ARCHIVE_REPOINT_MISMATCH', self.repoint, empty)
        self.refused('ARCHIVE_ROOT_INVALID', self.repoint, Path('relative'))
        manifest = new / 'manifest.json'
        raw = manifest.read_bytes()
        manifest.write_bytes(raw + b' ')                         # another manifest: its sha256 is not the pointer's
        self.refused('ARCHIVE_REPOINT_MISMATCH', self.repoint, new)
        manifest.write_bytes(raw)
        copy = new / 'native-evidence' / self.log.name
        data = copy.read_bytes()
        copy.unlink()
        self.refused('ARCHIVE_VERIFY_FAILED', self.repoint, new)
        copy.write_bytes(b'0' * len(data))
        self.refused('ARCHIVE_VERIFY_FAILED', self.repoint, new)
        copy.write_bytes(data)
        with patch('studio_evidence_archive.filesystem_of', return_value='exFAT'):
            self.refused('ARCHIVE_ROOT_FILESYSTEM', self.repoint, new)
        result = self.repoint(new)
        self.assertEqual((result['result']['archive_dir'], result['result']['previous_archive_dir']), (str(new), str(old)))
        pointer = json.loads(archive.pointer_path(self.root, JOB).read_text(encoding='utf-8'))
        self.assertEqual((pointer['schema'], pointer['archive_dir'], pointer['previous_archive_dirs']),
                         (archive.POINTER_SCHEMA, str(new), [str(old)]))
        self.assertEqual(pointer['archive_root'], str(self.f.base / 'new-volume'))
        retired = json.loads(next((self.root / 'native-evidence' / 'archived' / 'retired').glob(JOB + '.*.json')).read_text(encoding='utf-8'))
        self.assertEqual((retired['retired_reason'], retired['archive_dir']), ('repointed', str(old)))
        shutil.rmtree(old)                                       # the old drive is gone; readers use the new copy
        self.assertEqual(archive.resolve(self.root, self.log), new / 'native-evidence' / self.log.name)
        self.assertEqual(journal._history(self.root, self.job), {0, 1})
        self.assertEqual(self.actions()[-1]['phase'], 'repointed')

    def test_a_drive_that_returns_under_another_letter_is_found_by_its_volume_guid(self):
        volume = self.f.base / 'G-volume'
        volume.mkdir()
        self.archive_root.rename(volume / 'archive')
        self.archive_root = volume / 'archive'                   # the archive volume's root is G-volume
        with patch('studio_evidence_archive.volume_root_of', side_effect=lambda p: str(volume) + os.sep
                   if os.path.normcase(os.path.abspath(str(p))).startswith(os.path.normcase(str(volume))) else 'C:\\'), \
                patch('studio_evidence_archive.filesystem_of', return_value='NTFS'), \
                patch('studio_build_migration._drive_type', return_value=2):
            self.archive_and_complete()
        pointer = json.loads(archive.pointer_path(self.root, JOB).read_text(encoding='utf-8'))
        self.assertEqual((pointer['volume_guid'], pointer['archive_relative']), (FAKE_GUID, 'archive/state/' + JOB))
        # The drive comes back as another letter (another folder here): the old path is gone.
        remounted = self.f.base / 'F-volume'
        volume.rename(remounted)
        with self.assertRaisesRegex(archive.ArchiveUnreachable, 'not found under another drive letter'):
            journal._history(self.root, self.job)
        with patch('studio_evidence_archive.volume_mounts', return_value=[str(remounted) + os.sep]) as mounts:
            self.assertEqual(journal._history(self.root, self.job), {0, 1})
            self.assertEqual(archive.resolve(self.root, self.log),
                             remounted / 'archive' / 'state' / JOB / 'native-evidence' / self.log.name)
            mounts.assert_called_with(FAKE_GUID)
        # A volume that is mounted but holds another manifest at that path is not accepted.
        manifest = remounted / 'archive' / 'state' / JOB / 'manifest.json'
        manifest.write_bytes(manifest.read_bytes() + b' ')
        with patch('studio_evidence_archive.volume_mounts', return_value=[str(remounted) + os.sep]):
            with self.assertRaisesRegex(archive.ArchiveUnreachable, 'no longer matches its pointer'):
                journal._history(self.root, self.job)


if __name__ == '__main__':
    unittest.main()
