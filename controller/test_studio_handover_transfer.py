"""Cross-volume handover interruption tests; never use a customer terminal."""
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_handover as handover


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='goat-handover-transfer-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.target = self.root/'source', self.root/'archive'/'terminal'
        (self.source/'nested'/'empty').mkdir(parents=True)
        (self.source/'first').write_bytes(b'exact first file')
        (self.source/'nested'/'second').write_bytes(bytes(range(256))*8193)
        self.expected = handover.tree(self.source)
        self.rename = Path.rename

    def cross_volume(self, source, target):
        if source == self.source:
            raise OSError(errno.EXDEV, 'simulated cross-volume boundary')
        return self.rename(source, target)

    def move(self):
        with patch.object(Path, 'rename', lambda source, target: self.cross_volume(source, target)):
            handover.move_once(self.source, self.target, self.expected)

    def assert_complete(self):
        self.assertFalse(self.source.exists())
        self.assertEqual(handover.tree(self.target), self.expected)
        self.assertTrue((self.target/'nested'/'empty').is_dir())

    def test_cross_volume_copy_preserves_all_bytes_and_empty_directories(self):
        self.move(); self.assert_complete()
        self.move(); self.assert_complete()
        journals = list(self.target.parent.glob('.studio-transfer-*.json'))
        self.assertEqual(len(journals), 1)
        self.assertEqual(handover.read_json(journals[0])['phase'], 'complete')

    def test_windows_not_same_device_error_is_supported(self):
        def windows_error(source, target):
            if source == self.source:
                error = OSError('different disk drive'); error.winerror = 17
                raise error
            return self.rename(source, target)
        with patch.object(Path, 'rename', windows_error):
            handover.move_once(self.source, self.target, self.expected)
        self.assert_complete()

    def test_non_cross_volume_error_never_starts_a_copy(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('locked')):
            with self.assertRaisesRegex(PermissionError, 'locked'):
                handover.move_once(self.source, self.target, self.expected)
        self.assertEqual(handover.tree(self.source), self.expected)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.target.parent.iterdir()), [])

    def test_interrupted_partial_write_keeps_complete_source_and_resumes(self):
        original = handover.os.fsync
        def interrupt(fd):
            # Journal publication fsync precedes staging; interrupt first data fsync.
            if list(self.target.parent.glob('.studio-transfer-*.part')):
                raise OSError(errno.ENOSPC, 'copy interrupted: disk full at fsync')
            return original(fd)
        with patch('studio_handover.os.fsync', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'copy interrupted'): self.move()
        self.assertEqual(handover.tree(self.source), self.expected)
        self.assertFalse(self.target.exists())
        self.move(); self.assert_complete()

    def test_interruption_before_empty_directory_cleanup_resumes_after_last_file_deleted(self):
        rmdir = Path.rmdir
        def interrupt(directory):
            if directory.is_relative_to(self.source):
                raise OSError('before directory cleanup')
            return rmdir(directory)
        with patch.object(Path, 'rmdir', interrupt):
            with self.assertRaisesRegex(OSError, 'before directory cleanup'): self.move()
        self.assertEqual(handover.tree(self.source), {})
        self.assertEqual(handover.tree(self.target), self.expected)
        self.move(); self.assert_complete()

    def test_interruption_after_source_root_removed_resumes_before_complete_journal(self):
        rmdir = Path.rmdir
        def interrupt(directory):
            result = rmdir(directory)
            if directory == self.source:
                raise OSError('after source root removal')
            return result
        with patch.object(Path, 'rmdir', interrupt):
            with self.assertRaisesRegex(OSError, 'after source root removal'): self.move()
        self.assertFalse(self.source.exists())
        self.assertEqual(handover.tree(self.target), self.expected)
        journal = next(self.target.parent.glob('.studio-transfer-*.json'))
        self.assertEqual(handover.read_json(journal)['phase'], 'cleaning')
        self.move(); self.assert_complete()

    def test_interruption_after_destination_publish_resumes_without_overwrite(self):
        def interrupt(source, target):
            result = self.cross_volume(source, target)
            if target == self.target:
                raise OSError('published before phase update')
            return result
        with patch.object(Path, 'rename', interrupt):
            with self.assertRaisesRegex(OSError, 'published before phase'):
                handover.move_once(self.source, self.target, self.expected)
        self.assertEqual(handover.tree(self.source), self.expected)
        self.assertEqual(handover.tree(self.target), self.expected)
        self.move(); self.assert_complete()

    def test_interrupted_source_retirement_resumes_only_remaining_matching_files(self):
        unlink = Path.unlink
        removed = []
        def interrupt(file, *args, **kwargs):
            result = unlink(file, *args, **kwargs)
            if file.is_relative_to(self.source):
                removed.append(file)
                raise OSError('after source unlink')
            return result
        with patch.object(Path, 'unlink', interrupt):
            with self.assertRaisesRegex(OSError, 'after source unlink'): self.move()
        self.assertEqual(len(removed), 1)
        self.assertEqual(handover.tree(self.target), self.expected)
        self.assertEqual(len(handover.tree(self.source)), len(self.expected)-1)
        self.move(); self.assert_complete()

    def test_published_corruption_blocks_retirement_with_source_intact(self):
        write = handover.write_json
        def corrupt(file, record):
            write(file, record)
            if record.get('phase') == 'cleaning':
                (self.target/'first').write_bytes(b'corrupt target')
        with patch('studio_handover.write_json', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'Published handover changed'): self.move()
        self.assertEqual(handover.tree(self.source), self.expected)
        with self.assertRaisesRegex(ValueError, 'Published handover changed'): self.move()

    def test_source_changed_after_publish_is_preserved_with_verified_archive(self):
        write = handover.write_json
        def mutate(file, record):
            write(file, record)
            if record.get('phase') == 'cleaning':
                (self.source/'unreviewed').write_bytes(b'preserve new data')
        with patch('studio_handover.write_json', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'Remaining handover source changed'): self.move()
        self.assertEqual(handover.tree(self.target), self.expected)
        self.assertEqual((self.source/'unreviewed').read_bytes(), b'preserve new data')
        self.assertEqual((self.source/'first').read_bytes(), b'exact first file')

    def test_unreviewed_empty_source_directory_is_not_removed(self):
        write = handover.write_json
        def mutate(file, record):
            write(file, record)
            if record.get('phase') == 'cleaning':
                (self.source/'unreviewed-empty').mkdir()
        with patch('studio_handover.write_json', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'unexpected directory'): self.move()
        self.assertEqual(handover.tree(self.source), self.expected)
        self.assertTrue((self.source/'unreviewed-empty').is_dir())
        self.assertEqual(handover.tree(self.target), self.expected)

    def test_source_link_refuses_without_touching_its_target(self):
        outside = self.root/'outside'; outside.write_bytes(b'preserve outside')
        (self.source/'first').unlink(); (self.source/'first').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'filesystem links'): self.move()
        self.assertEqual(outside.read_bytes(), b'preserve outside')
        self.assertFalse(self.target.exists())

    def test_staging_link_refuses_during_copy_resume(self):
        original = handover.os.fsync
        def interrupt(fd):
            if list(self.target.parent.glob('.studio-transfer-*.part')): raise OSError('copy interrupted')
            return original(fd)
        with patch('studio_handover.os.fsync', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'copy interrupted'): self.move()
        stage = next(p for p in self.target.parent.glob('.studio-transfer-*') if p.is_dir())
        # Stage only has empty copied directories; preserve them at a new path.
        stage.rename(self.root/'retained-stage')
        outside = self.root/'outside'; outside.mkdir(); (outside/'keep').write_bytes(b'preserve outside')
        stage.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'filesystem links'): self.move()
        self.assertEqual((outside/'keep').read_bytes(), b'preserve outside')
        self.assertEqual(handover.tree(self.source), self.expected)

    def test_corrupt_partial_staging_fails_closed_and_keeps_source(self):
        def interrupt(source, target):
            result = self.cross_volume(source, target)
            if source.suffix == '.part':
                raise OSError('staged first file')
            return result
        with patch.object(Path, 'rename', interrupt):
            with self.assertRaisesRegex(OSError, 'staged first file'):
                handover.move_once(self.source, self.target, self.expected)
        stage = next(p for p in self.target.parent.glob('.studio-transfer-*') if p.is_dir())
        (stage/'first').write_bytes(b'corrupt stage')
        with self.assertRaisesRegex(ValueError, 'staging changed'): self.move()
        self.assertEqual(handover.tree(self.source), self.expected)
        self.assertFalse(self.target.exists())

    def test_foreign_destination_and_journal_drift_never_authorize_source_delete(self):
        self.target.mkdir(parents=True); (self.target/'foreign').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'): self.move()
        self.assertEqual(handover.tree(self.source), self.expected)
        (self.target/'foreign').unlink(); self.target.rmdir()
        with patch('studio_handover.os.fsync', side_effect=OSError('stop')):
            with self.assertRaises(OSError): self.move()
        # No successful durable journal means source remained unchanged.
        self.assertEqual(handover.tree(self.source), self.expected)
        self.move(); self.assert_complete()
        journal = next(self.target.parent.glob('.studio-transfer-*.json'))
        record = handover.read_json(journal); record['identity']['source'] = str(self.root/'foreign')
        handover.write_json(journal, record)
        with self.assertRaisesRegex(ValueError, 'identity changed'): self.move()


if __name__ == '__main__': unittest.main()
