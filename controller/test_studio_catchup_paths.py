"""Catch-up paths stay bounded on any Windows user name (goatai#1885 6008582393).

catchup-validate sized the evidence folder with the placeholder ``validation-only`` and
``evidence\\<catch-up id>\\<23-char alias>\\`` + 140 had to fit 259 characters: on a 76-character
state root only IDs of 9 characters or fewer fitted, so validate could never pass. The evidence
folder is now ``evidence\\c.<10 hex>\\<5 digits>\\`` (len(state root) + 168, whatever the ID), and
controller-only folders switch to the \\\\?\\ extended-length form past MAX_PATH. MT5's own paths
stay plain and are checked.
"""
import builtins
import contextlib
import io
import json
import ntpath
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import studio_catchup as sc
from studio_installation import read_json
from test_studio_catchup import AFTER_CLOSE, CatchupCase

BANKER_ROOT = 76     # C:\Users\web\AppData\Local\GOAT Portfolio Desktop\suite\ea01797bedf56eef7940
LONG_USER_ROOT = 113  # the same suite root under a 40-character Windows user name
REAL_ID = 'catchup-20261005-banker'   # 23 characters


def prefixed(path):
    return str(path).startswith('\\\\?\\')


@contextlib.contextmanager
def without_long_path_support():
    """Behave like Windows without LongPathsEnabled: an unprefixed path past 259 characters cannot be opened."""
    originals = {name: getattr(os, name) for name in ('stat', 'lstat', 'mkdir', 'rename', 'replace', 'unlink', 'rmdir',
                                                      'scandir', 'listdir', 'open')}
    checks = {name: getattr(ntpath, name) for name in ('isdir', 'isfile', 'exists')}
    real_open = io.open

    def too_long(path):
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except TypeError:
            return False
        return not text.startswith('\\\\?\\') and len(text) > sc.MAX_PATH

    def refuse(original):
        def call(path, *args, **kwargs):
            if too_long(path) or (args and not isinstance(args[0], int) and isinstance(args[0], (str, os.PathLike)) and too_long(args[0])):
                raise FileNotFoundError(2, 'The system cannot find the path specified (unprefixed long path)', os.fspath(path))
            return original(path, *args, **kwargs)
        return call

    def absent(original):
        return lambda path: False if too_long(path) else original(path)

    with contextlib.ExitStack() as stack:
        for name, original in originals.items():
            stack.enter_context(patch.object(os, name, refuse(original)))
        for name, original in checks.items():
            stack.enter_context(patch.object(ntpath, name, absent(original)))
        stack.enter_context(patch.object(io, 'open', refuse(real_open)))
        stack.enter_context(patch.object(builtins, 'open', refuse(real_open)))
        yield


class PathLayoutTests(CatchupCase):
    def root_of(self, length):
        """A controller state root of exactly ``length`` characters inside the test folder."""
        base = os.path.abspath(self.root / 'state')
        filler = length - len(base) - 1
        self.assertGreater(filler, 0, 'temp folder too long for this fixture')
        return Path(base) / ('u' * filler)

    def use_root(self, length):
        root = self.root_of(length)
        sc.io_path(root).mkdir(parents=True)
        self.controller.root = root
        self.runner = sc.CatchupRunner(self.controller, process=self.process, clock=lambda: self.now, sleep=self.sleep, now=AFTER_CLOSE)
        self.assertEqual(len(str(root)), length)
        return root

    def tearDown(self):
        # Long fixture folders need the extended form to be removed.
        if os.name == 'nt':
            shutil.rmtree('\\\\?\\' + os.path.abspath(self.root), ignore_errors=True)
        super().tearDown()

    def test_evidence_folder_is_short_hashed_and_independent_of_the_id(self):
        self.assertEqual(sc.evidence_key(REAL_ID), 'c.' + __import__('hashlib').sha256(REAL_ID.encode()).hexdigest()[:10])
        self.assertEqual(len(sc.evidence_key('x' * 80)), 12)
        self.assertNotEqual(sc.evidence_key('a'), sc.evidence_key('b'))
        for catchup_id in ('c', REAL_ID, 'x' * 80):
            member = self.runner._build(self.runner.path(catchup_id), self.plan(sets=[self.behind]))[0][0]
            folder = Path(member['evidence_dir'])
            self.assertEqual((folder.parent.name, folder.name), (sc.evidence_key(catchup_id), '00001'))
            self.assertEqual(folder.parent.parent, Path(os.path.abspath(self.controller.root / 'evidence')))

    def test_banker_root_validates_with_the_real_id(self):
        """The reported case: 76-character state root, a 23-character ID. The old sizing needed <= 9."""
        root = self.use_root(BANKER_ROOT)
        old_worst = BANKER_ROOT + len('\\evidence\\') + len(REAL_ID) + 1 + 23 + sc.OUTPUT_PATH_ROOM
        self.assertGreater(old_worst, 259)            # why every validate failed before
        for catchup_id in (None, REAL_ID, 'x' * 80):
            with self.subTest(catchup_id=catchup_id):
                result = self.runner.validate(self.plan(), catchup_id)
                self.assertEqual((result['valid'], result['writes'], result['member_count']), (True, False, 2))
                paths = result['paths']
                self.assertEqual(paths['evidence_worst_case'], BANKER_ROOT + 168)
                self.assertEqual(paths['state_root_length'], BANKER_ROOT)
                self.assertLessEqual(paths['evidence_worst_case'], sc.MAX_PATH)
                self.assertFalse(paths['evidence_extended_length'])
                self.assertEqual(paths['catchups_worst_case'], BANKER_ROOT + 83 + len(catchup_id or 'x' * 80))
                self.assertLessEqual(paths['mt5_longest_exact'], sc.MAX_PATH)
        self.assertFalse((root / 'catchups').exists() or (root / 'evidence').exists())
        prepared = self.runner.prepare(REAL_ID, self.plan())
        self.assertEqual(prepared['status'], 'prepared')
        members = read_json(self.runner.path(REAL_ID) / 'manifest.json')['members']
        self.assertTrue(all(not prefixed(m['evidence_dir']) for m in members))   # short enough: plain paths
        self.assertTrue(all(len(m['evidence_dir']) + sc.OUTPUT_PATH_ROOM <= sc.MAX_PATH for m in members))

    @unittest.skipUnless(os.name == 'nt', 'Windows MAX_PATH behaviour')
    def test_forty_character_user_name_runs_a_full_catchup_without_long_path_support(self):
        root = self.use_root(LONG_USER_ROOT)
        catchup_id = 'catchup-' + 'z' * 72          # the longest legal ID: 80 characters
        self.catchup_id = catchup_id
        with without_long_path_support():
            preview = self.runner.validate(self.plan(), catchup_id)['paths']
            self.assertEqual(preview['evidence_worst_case'], LONG_USER_ROOT + 168)
            self.assertTrue(preview['evidence_extended_length'] and preview['catchups_extended_length'])
            self.runner.prepare(catchup_id, self.plan())
            self.auto = True
            state = self.runner.start(catchup_id, 30)
            self.assertEqual(state['status'], 'completed')
            manifest = read_json(self.runner.path(catchup_id) / 'manifest.json')
            for member in manifest['members']:
                folder = Path(member['evidence_dir'])
                self.assertTrue(prefixed(folder), folder)
                self.assertGreater(len(sc.plain(folder)) + sc.OUTPUT_PATH_ROOM, sc.MAX_PATH)
                # A real EA file name can pass the limit here: only the extended form reaches it (the guard is live).
                deepest = folder / ('GOAT V1.49 EURUSD,M1_' + 'x' * (sc.MAX_PATH - len(sc.plain(folder))) + '.csv')
                deepest.write_bytes(b'x')
                self.assertGreater(len(sc.plain(deepest)), sc.MAX_PATH)
                self.assertFalse(Path(sc.plain(deepest)).exists())
                self.assertTrue(deepest.exists())
                deepest.unlink()
                self.assertEqual(read_json(folder / 'evidence-version.json')['catchup_id'], catchup_id)
                # MT5's own files stay plain and under the limit.
                for path, _ in self.runner._mt5_paths(member):
                    self.assertFalse(prefixed(path))
                    self.assertLessEqual(len(path), sc.MAX_PATH)
            record = json.loads((sc.evidence_folder(root, catchup_id) / 'catchup.json').read_text(encoding='utf-8'))
            self.assertEqual((record['schema'], record['catchup_id']), ('goat-catchup-evidence-folder-v1', catchup_id))
            self.assertEqual(record['members']['00001']['alias'], manifest['members'][0]['alias'])
            found = sc.versions(root)
            self.assertEqual(sorted(v['symbol'] for v in found), ['EURUSD', 'GBPUSD'])
            report = self.runner.report(catchup_id)
            self.assertEqual(sum(report['counts'].values()), 2)
            self.assertTrue(all(Path(row['version_path']).is_file() for row in report['members']))
            scan = sc.evidence_scan([self.run], now=AFTER_CLOSE, controller_root=root)
            self.assertEqual(scan['summary']['counts']['caught_up'], 2)

    def test_legacy_evidence_folders_are_still_read(self):
        legacy = self.controller.root / 'evidence' / 'cu-old' / 'Cabcdef0123456789_00001'
        legacy.mkdir(parents=True)
        record = dict(schema=sc.VERSION_SCHEMA, values_sha256='v' * 64, symbol='EURUSD', period='M1', evidence_start='2026-01-05',
                      evidence_end='2026-09-25', catchup_id='cu-old', alias=legacy.name, created_utc='2026-09-26T00:00:00+00:00',
                      verdict=dict(verdict='held_up'))
        (legacy / 'evidence-version.json').write_text(json.dumps(record), encoding='utf-8')
        self.assertEqual(sc.evidence_folder(self.controller.root, 'cu-old'), self.controller.root / 'evidence' / 'cu-old')
        self.assertIsNone(sc.evidence_folder(self.controller.root, 'cu-new'))
        self.runner.prepare('cu-new', self.plan(sets=[self.behind]))
        self.assertEqual(sc.evidence_folder(self.controller.root, 'cu-new').name, sc.evidence_key('cu-new'))
        self.assertEqual([v['catchup_id'] for v in sc.versions(self.controller.root)], ['cu-old'])

    def test_an_evidence_folder_owned_by_another_id_refuses_before_writing(self):
        folder = self.controller.root / 'evidence' / sc.evidence_key('cu1')
        folder.mkdir(parents=True)
        (folder / 'catchup.json').write_text(json.dumps(dict(catchup_id='someone-else')), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already belongs to someone-else'):
            self.runner.prepare('cu1', self.plan())
        self.assertFalse(self.runner.path('cu1').exists())
        self.assertFalse((Path(self.controller.install['terminal_data_root']) / 'config/GOATStudio/Catchups').exists())

    def test_mt5_paths_past_the_limit_refuse_with_the_path(self):
        deep = Path(os.path.abspath(self.root)) / ('d' * max(1, 240 - len(os.path.abspath(self.root))))
        self.controller.install = dict(self.controller.install, terminal_data_root=str(deep))
        with patch.object(sc, 'WINDOWS', True), self.assertRaisesRegex(ValueError, r'MT5 tester INI \(/config\) path would be \d+ characters'):
            self.runner.validate(self.plan(sets=[self.behind]))
        with patch.object(sc, 'WINDOWS', False):
            self.assertEqual(self.runner.validate(self.plan(sets=[self.behind]))['member_count'], 1)

    def test_io_path_switches_to_extended_length_only_past_max_path(self):
        short = Path(os.path.abspath('C:\\s'))
        self.assertEqual(sc.io_path(short, 10, windows=True), short)
        long = 'C:\\' + 'a' * 250
        self.assertTrue(prefixed(sc.io_path(long, 10, windows=True)))
        self.assertFalse(prefixed(sc.io_path(long, 10, windows=False)))
        self.assertEqual(sc.plain(sc.io_path(long, 10, windows=True)), os.path.abspath(long))
        self.assertEqual(sc.plain('\\\\?\\UNC\\server\\share\\x'), '\\\\server\\share\\x')

    def test_cli_validate_accepts_the_catchup_id(self):
        from goat_studio import OPERATION_CONTRACTS
        self.assertIn('catchup-id', OPERATION_CONTRACTS['catchup-validate']['optional'])


if __name__ == '__main__':
    unittest.main()
