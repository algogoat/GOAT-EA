import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_storage_floor as sf

MB = 1000 * 1000


class Usage:
    def __init__(self, free):
        self.total, self.used, self.free = free * 2, free, free


class StorageFloorTests(unittest.TestCase):
    """The output-root floor (Claude-Mac goatai#2750 6877948300): free now - members x the LARGEST finished unit on disk,
    against the drive's floor (15 GB system drive, 5 GB other drives, or the machine policy file)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'out'
        self.sizes = {}   # file name -> faked on-disk bytes

    def unit(self, catchup, number, size_mb, *, record='evidence-version.json'):
        folder = self.root / catchup / ('%05d' % number)
        folder.mkdir(parents=True)
        if record:
            (folder / record).write_text('{}', encoding='utf-8')
        name = '%s-%05d.csv' % (catchup, number)
        (folder / 'x.goatseq').mkdir()
        (folder / 'x.goatseq' / name).write_text('x', encoding='utf-8')
        self.sizes[name] = size_mb * MB
        return folder

    def size(self, path):
        return self.sizes.get(Path(path).name, 0)

    def policy(self, floors, **change):
        path = Path(self.tmp.name) / 'storage-floors.json'
        path.write_text(json.dumps(dict(schema=sf.SCHEMA, floors_gb=floors) | change), encoding='utf-8')
        return path

    def check(self, members, free, path, *, drive='G:'):
        with patch('shutil.disk_usage', return_value=Usage(free)), patch('studio_storage_floor.drive_of', return_value=drive):
            return sf.check(self.root, members, path=path, system='C:', size=self.size)

    def test_largest_not_mean(self):
        for n, mb in enumerate((10, 30, 20), 1):
            self.unit('c.aaaaaaaaaa', n, mb)
        self.unit('c.bbbbbbbbbb', 1, 25, record='build-migration-retest.json')
        self.assertEqual(sf.largest_unit(self.root, self.size), (30 * MB, 4))
        path = self.policy({'G:': 5})
        # 10 units: the largest (30 MB) projects 5.25 - 0.30 = 4.95 GB, under 5; the mean (21.25 MB) would pass.
        with self.assertRaisesRegex(ValueError, 'refused'):
            self.check(10, int(5.25 * sf.GB), path)
        report = self.check(10, int(5.31 * sf.GB), path)
        self.assertEqual(report['unit_bytes'], 30 * MB)
        self.assertEqual(report['units_measured'], 4)
        self.assertIn('the largest of 4 finished unit(s) on disk', report['unit_basis'])

    def test_unfinished_units_and_other_folders_fall_back_to_128_mib(self):
        self.unit('c.aaaaaaaaaa', 1, 900, record=None)          # still being written: no record yet
        (self.root / 'not-a-catchup' / '00001').mkdir(parents=True)
        (self.root / 'not-a-catchup' / '00001' / 'evidence-version.json').write_text('{}', encoding='utf-8')
        (self.root / 'c.aaaaaaaaaa' / 'catchup.json').write_text('{}', encoding='utf-8')
        self.assertEqual(sf.largest_unit(self.root, self.size), (None, 0))
        report = self.check(2, 100 * sf.GB, self.policy({'G:': 50}))
        self.assertEqual(report['unit_bytes'], sf.UNIT_FALLBACK_BYTES)
        self.assertIn('no finished unit here or in sibling roots under %s, so 128 MiB' % Path(self.tmp.name), report['plain'])
        self.assertEqual(sf.largest_unit(Path(self.tmp.name) / 'missing', self.size), (None, 0))

    def test_a_new_root_takes_the_largest_unit_of_its_sibling_roots(self):
        # GOAT-EA#342 6878127520: a new plan's folder (no finished unit yet) is priced by its siblings under the same
        # parent on the same drive, before the 128 MiB fallback.
        top = Path(self.tmp.name)
        self.root = top / 'older'
        self.unit('c.aaaaaaaaaa', 1, 40)
        self.unit('c.aaaaaaaaaa', 2, 60)
        self.root = top / 'oldest'
        self.unit('c.bbbbbbbbbb', 1, 55, record='build-migration-retest.json')
        self.unit('c.bbbbbbbbbb', 2, 900, record=None)        # unfinished: never counted
        self.root = top / 'elsewhere'
        self.unit('c.cccccccccc', 1, 500)                      # a junction to another drive: never counted
        self.root = top / 'new'
        self.root.mkdir()
        other = os.path.normcase(str(top / 'elsewhere'))
        with patch('studio_storage_floor.real_drive', side_effect=lambda p: 'X:' if os.path.normcase(str(p)) == other else sf.drive_of(top)):
            unit, measured, roots, parent = sf.sibling_unit(self.root, self.size)
            self.assertEqual((unit, measured, roots, parent), (60 * MB, 3, 2, top))
            report = self.check(100, 60 * sf.GB, self.policy({'G:': 50}), drive=sf.drive_of(top))
        self.assertEqual(report['unit_bytes'], 60 * MB)
        self.assertIn('no finished unit here yet: the largest of 3 finished unit(s) on disk in 2 sibling root(s) under %s' % top,
                      report['unit_basis'])
        self.unit('c.dddddddddd', 1, 10)                       # once the new root has its own unit, that unit decides
        with patch('studio_storage_floor.real_drive', return_value=sf.drive_of(top)):
            self.assertEqual(self.check(100, 60 * sf.GB, self.policy({'G:': 50}), drive=sf.drive_of(top))['unit_bytes'], 10 * MB)

    def test_system_drive_and_other_drive_defaults(self):
        missing = Path(self.tmp.name) / 'no-policy.json'
        floor, source = sf.floor_for('C:', path=missing, system='C:')
        self.assertEqual(floor, 15 * sf.GB)
        self.assertIn('system drive', source)
        self.assertIn('no policy file at %s' % missing, source)
        self.assertEqual(sf.floor_for('G:', path=missing, system='C:')[0], 5 * sf.GB)
        self.assertEqual(sf.floor_for('', path=None, system=None)[0], 5 * sf.GB)   # off Windows: no system drive
        path = self.policy({'C:': 15})
        floor, source = sf.floor_for('G:', path=path, system='C:')
        self.assertEqual(floor, 5 * sf.GB)
        self.assertIn('no G: entry in policy file %s' % path, source)

    def test_policy_overrides_and_fails_closed(self):
        path = self.policy({'C:': 15, 'g:': 50})
        self.assertEqual(sf.read_policy(path), {'C:': 15.0, 'G:': 50.0})
        self.assertEqual(sf.floor_for('G:', path=path, system='C:'), (50 * sf.GB, 'policy file %s' % path))
        self.assertEqual(sf.floor_for('C:', path=path, system='C:')[0], 15 * sf.GB)
        for bad in (dict(schema='other', floors_gb={'G:': 50}), dict(schema=sf.SCHEMA, floors_gb={'G': 50}),
                    dict(schema=sf.SCHEMA, floors_gb={'G:': True}), dict(schema=sf.SCHEMA, floors_gb={'G:': -1}),
                    dict(schema=sf.SCHEMA, floors_gb=[50]), [1]):
            with self.subTest(bad=bad):
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Storage floor policy .* is not a goat-storage-floors-v1 record'):
                    sf.read_policy(path)
        path.write_text('{not json', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'cannot be read'):
            sf.floor_for('G:', path=path, system='C:')
        with patch.dict(os.environ, {sf.POLICY_ENV: str(path)}):
            self.assertEqual(sf.policy_path(), path)
        with patch.dict(os.environ, {sf.POLICY_ENV: '', 'LOCALAPPDATA': str(self.tmp.name)}):
            self.assertEqual(sf.policy_path(), Path(self.tmp.name) / 'GOAT Portfolio Desktop' / 'storage-floors.json')

    def test_refusal_names_the_projection_the_floor_and_the_policy_file(self):
        self.unit('c.aaaaaaaaaa', 1, 100)
        path = self.policy({'G:': 50})
        with self.assertRaises(ValueError) as caught:
            self.check(204, 58 * sf.GB, path)
        text = str(caught.exception)
        self.assertIn('Evidence root %s is refused' % self.root, text)
        self.assertIn('58.0 GB free now - 204 unit(s) x 100 MB', text)
        self.assertIn('= 37.6 GB projected at the plan\'s end', text)
        self.assertIn('floor 50.0 GB (policy file %s)' % path, text)
        report = self.check(70, 58 * sf.GB, path)
        self.assertEqual(report['projected_free_bytes'], 58 * sf.GB - 70 * 100 * MB)
        self.assertEqual((report['floor_bytes'], report['policy_file'], report['drive']), (50 * sf.GB, str(path), 'G:'))

    def test_a_compressed_unit_counts_its_size_on_disk(self):
        folder = self.unit('c.aaaaaaaaaa', 1, 0)
        big = folder / 'x.goatseq' / 'marks.csv'
        big.write_bytes(b'0' * 1000000)             # logical size 1 MB
        on_disk = {'marks.csv': 300000}            # stored compressed: 0.3 MB (faked GetCompressedFileSizeW)
        self.assertEqual(sf.largest_unit(self.root, lambda p: on_disk.get(Path(p).name, 0)), (300000, 1))
        self.assertLess(sf.largest_unit(self.root, lambda p: on_disk.get(Path(p).name, 0))[0], big.stat().st_size)

    @unittest.skipUnless(os.name == 'nt', 'GetCompressedFileSizeW is Windows only')
    def test_the_real_on_disk_call_reads_an_uncompressed_file_whole(self):
        path = Path(self.tmp.name) / 'plain.bin'
        path.write_bytes(b'x' * 12345)
        self.assertEqual(sf.on_disk_size(path), 12345)
        with self.assertRaises(OSError):
            sf.on_disk_size(Path(self.tmp.name) / 'missing.bin')

    def test_drive_of(self):
        self.assertEqual(sf.drive_of('G:\\GOAT-Evidence\\x'), 'G:')
        self.assertEqual(sf.drive_of('\\\\?\\g:\\GOAT-Evidence'), 'G:')
        self.assertEqual(sf.drive_of('/srv/goat'), '')


if __name__ == '__main__':
    unittest.main()
