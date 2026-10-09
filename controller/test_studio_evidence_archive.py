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

    def volume(self, path):
        return 2 if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(self.archive_root))) else 1

    def files(self):
        found = super().files()
        found.update({str(p): p.read_bytes() for p in self.archive_root.rglob('*') if p.is_file()})
        return found

    def run_archive(self, batch_id=JOB, **kw):
        kw.setdefault('confirm', True)
        kw.setdefault('apply', True)
        return self.agent.evidence_archive(batch_id, kw.pop('archive_root', self.archive_root), **kw)

    def refused_archive(self, code, batch_id=JOB, **kw):
        before = self.files()
        with self.assertRaises(Refusal) as caught:
            self.run_archive(batch_id, **kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(self.files(), before, 'a refusal wrote something')
        return caught.exception

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
        preview = self.agent.evidence_archive(JOB, self.archive_root)
        self.assertEqual(self.files(), before)
        self.assertFalse(preview['applied'])
        self.assertTrue(preview['ready'], preview['blockers'])
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
        preview = self.agent.evidence_archive(JOB, self.archive_root)
        self.assertFalse(preview['ready'])
        self.assertEqual([b['code'] for b in preview['blockers']], ['ARCHIVE_TERMINAL_BUSY'])


class ApplyTests(ArchiveFixture):
    def test_apply_moves_verifies_writes_manifest_and_pointer_and_deletes_nothing_else(self):
        sources = {rel: (self.root / rel).read_bytes() for rel in self.owned()}
        kept = {str(p): p.read_bytes() for p in self.evidence.rglob('*') if p.is_file()
                and p.relative_to(self.root).as_posix() not in sources}
        result = self.run_archive()
        self.assertTrue(result['applied'])
        self.assertEqual((result['result']['copied'], result['result']['removed'], result['result']['verified']), (7, 7, 7))
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
        # Every other file is byte-identical and still in place.
        self.assertEqual({path: Path(path).read_bytes() for path in kept}, kept)
        actions = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        self.assertEqual([(a['operation'], a['phase'], a['files']) for a in actions], [('evidence_archive', 'archived', 7)])

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
        self.assertFalse(any((self.root / rel).exists() for rel in self.owned()))

    def test_interrupted_removal_then_resume_completes_and_readers_use_the_archive_meanwhile(self):
        real, removed = archive._unlink, []

        def crash_after_three(path):
            if len(removed) == 3:
                raise KeyboardInterrupt('power cut')
            removed.append(path)
            real(path)
        with patch('studio_evidence_archive._unlink', side_effect=crash_after_three):
            with self.assertRaises(KeyboardInterrupt):
                self.run_archive()
        self.assertEqual(sum((self.root / rel).exists() for rel in self.owned()), 4)
        self.assertEqual(journal._history(self.root, self.job), {0, 1})        # read through the pointer
        result = self.run_archive()
        self.assertEqual((result['result']['changed'], result['result']['removed'], result['result']['already_removed']), (True, 4, 3))
        self.assertFalse(any((self.root / rel).exists() for rel in self.owned()))
        self.assertEqual(self.run_archive()['result']['removed'], 0)

    def test_a_failed_verification_keeps_the_source_and_writes_no_pointer(self):
        before = {rel: (self.root / rel).read_bytes() for rel in self.owned()}
        with patch('studio_evidence_archive._readback', return_value='0' * 64):
            with self.assertRaises(Refusal) as caught:
                self.run_archive()
        self.assertEqual(caught.exception.code, 'ARCHIVE_VERIFY_FAILED')
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in self.owned()}, before)
        self.assertFalse(archive.pointer_path(self.root, JOB).exists())
        self.assertFalse(any(p.is_file() for p in self.archive_root.rglob('*')), 'an unverified copy was left behind')

    def test_a_source_that_changed_after_its_copy_is_kept(self):
        real = archive._remove_sources

        def tamper(root, pointer, manifest):
            self.log.write_bytes(self.log.read_bytes() + b'{"late":1}\n')
            return real(root, pointer, manifest)
        with patch('studio_evidence_archive._remove_sources', side_effect=tamper):
            with self.assertRaises(Refusal) as caught:
                self.run_archive()
        self.assertEqual(caught.exception.code, 'ARCHIVE_SOURCE_CHANGED')
        self.assertTrue(self.log.is_file())


class ReaderTests(ArchiveFixture):
    def test_trial_journal_history_and_member_identities_follow_the_pointer(self):
        from studio_batch_close import member_identities
        self.assertEqual(journal._history(self.root, self.job), {0, 1})
        done_before = member_identities(self.root, self.job, self.job['completion']['member_outcomes'])
        self.run_archive()
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
        self.run_archive()
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

    def test_foos_read_selection_and_unverifiable_citations_refuse(self):
        write_json(self.root / 'catchups' / 'cu-g20' / 'manifest.json',
                   dict(members=[dict(source_path=str(self.export), source_sha256=self.export_sha)]))
        error = self.refused_archive('ARCHIVE_CITED_FOOS_READ')
        self.assertEqual(error.fields['citations'][0]['run_id'], 'cu-g20')
        (self.root / 'catchups' / 'cu-g20' / 'manifest.json').unlink()
        locks = [dict(lock_id='l' * 64, strategy_key='banker', candidate=[dict(symbol='EURUSD', timeframe='M1', set_sha256=self.export_sha)])]
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=locks)):
            self.refused_archive('ARCHIVE_CITED_SELECTION')
        with patch('studio_heldout.read_registry', return_value=dict(state='unavailable', error='broken chain', locks=[])):
            self.refused_archive('ARCHIVE_CITATIONS_UNVERIFIABLE')

    def test_keep_list_refuses_by_batch_or_run_folder_and_a_bad_list_refuses(self):
        keep = self.f.base / 'keep.json'
        keep.write_text(json.dumps([JOB]))
        self.assertEqual(self.refused_archive('ARCHIVE_KEEP_LISTED', keep_list=keep).fields['keep_entry'], JOB)
        keep.write_text(json.dumps(dict(keep=[RUN])))
        self.refused_archive('ARCHIVE_KEEP_LISTED', keep_list=keep)
        keep.write_text('{not json')
        self.refused_archive('ARCHIVE_KEEP_LIST_INVALID', keep_list=keep)
        keep.write_text(json.dumps([1, 2]))
        self.refused_archive('ARCHIVE_KEEP_LIST_INVALID', keep_list=keep)
        keep.write_text(json.dumps(['another-batch']))
        self.assertTrue(self.run_archive(keep_list=keep)['applied'])

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
        code, applied = self.cli('evidence-archive', '--batch-id', JOB, '--archive-root', str(self.archive_root), '--apply', '--confirm')
        self.assertEqual((code, applied['result']['applied'], applied['result']['result']['removed']), (0, True, 7))

    def test_contract_is_registered(self):
        from goat_studio import OPERATION_CONTRACTS
        contract = OPERATION_CONTRACTS['evidence-archive']
        self.assertEqual(contract['required'], ['batch-id', 'archive-root'])
        self.assertIn('keep-list', contract['optional'])
        self.assertIn('never delete', contract['effect'])
        self.assertIn('goat.exe demo evidence-archive', contract['demo_lane'])
        self.assertTrue(set(archive.CODES) >= {'ARCHIVE_CONFIRM_REQUIRED', 'ARCHIVE_NOT_FINISHED', 'ARCHIVE_TERMINAL_BUSY',
                                               'ARCHIVE_CITED_FOOS_READ', 'ARCHIVE_CITED_SELECTION', 'ARCHIVE_KEEP_LISTED',
                                               'ARCHIVE_ROOT_SAME_VOLUME', 'ARCHIVE_ROOT_NOT_WRITABLE', 'ARCHIVE_ROOT_LOW_SPACE'})


class CatchupArchiveTests(ArchiveFixture):
    """A finished catch-up: its hashed evidence folder moves; versions(), evidence_folder() and the report follow."""

    def setUp(self):
        super().setUp()
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
        preview = self.agent.evidence_archive(CATCHUP, self.archive_root)
        self.assertTrue(preview['ready'], preview['blockers'])
        self.assertEqual(preview['kind'], 'catchup')
        self.assertEqual(preview['file_count'], 5)
        self.assertEqual(preview['folders'], ['evidence/' + sc.evidence_key(CATCHUP)])
        self.run_archive(CATCHUP)
        self.assertFalse(self.cfolder.exists())
        moved = self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP)
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
        self.assertFalse((self.root / 'evidence' / CATCHUP).exists())
        self.assertEqual(sc.evidence_folder(self.root, CATCHUP), self.folder(CATCHUP) / 'evidence' / CATCHUP)
        self.assertEqual(len(sc.versions(self.root)), 1)

    def test_an_unfinished_or_cited_catchup_refuses(self):
        state = self.root / 'catchups' / CATCHUP / 'state.json'
        value = json.loads(state.read_text())
        write_json(state, dict(value, status='active'))
        self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED', CATCHUP).fields['batch_state'], 'running')
        write_json(state, dict(value, status='stopped', members=[dict(value['members'][0], status='pending')]))
        self.assertEqual(self.refused_archive('ARCHIVE_NOT_FINISHED', CATCHUP).fields['batch_state'], 'paused')
        write_json(state, value)
        write_json(self.root / 'holdups' / 'h1' / 'manifest.json', dict(members=[dict(source_path=str(self.retest),
                                                                                       source_sha256='x' * 64)]))
        self.refused_archive('ARCHIVE_CITED_FOOS_READ', CATCHUP)
        (self.root / 'holdups' / 'h1' / 'manifest.json').unlink()
        locks = [dict(lock_id='l' * 64, candidate=[dict(set_sha256=hashlib.sha256(self.retest.read_bytes()).hexdigest())])]
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=locks)):
            self.refused_archive('ARCHIVE_CITED_SELECTION', CATCHUP)

    def test_the_catchup_report_names_the_archived_version(self):
        from types import SimpleNamespace
        runner = sc.CatchupRunner.__new__(sc.CatchupRunner)
        runner.c = SimpleNamespace(root=self.root)
        version = self.cfolder / '00001' / 'evidence-version.json'
        self.assertEqual(runner._version_path(dict(version_path=str(version))), str(version))
        self.run_archive(CATCHUP)
        self.assertEqual(runner._version_path(dict(version_path=str(version))),
                         str(self.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP) / '00001' / 'evidence-version.json'))


if __name__ == '__main__':
    unittest.main()
