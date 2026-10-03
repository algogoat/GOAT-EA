import json
from pathlib import Path
import shutil
import tempfile
import unittest

import studio_evidence as ev

FIXTURES = Path(__file__).parent / 'fixtures' / 'oosc'
G6_AUDUSD = 'g6/deploy/R02291b683f2bc5a39857/AUDUSD/GOAT V1.49 AUDUSD,M1_Trds=406_Prf=278_DD=91_PF=1.57_SR=2.92_ARF=0.315.set'
G6_WS30_DONE = 'g6/deploy/R31019b1ffd701fff0826/WS30/GOAT V1.49 WS30,M1_Trds=1089_Prf=1695_DD=357_PF=1.51_SR=2.54_ARF=0.443.set'
G6_WS30_ROWS = 'g6/deploy/R31019b1ffd701fff0826/WS30/GOAT V1.49 WS30,M1_Trds=1215_Prf=1866_DD=430_PF=1.64_SR=3.08_ARF=0.504.set'
G6_XAUUSD = 'g6/deploy/R04049bbe9cc1b1fe6c3f/XAUUSD/GOAT V1.49 XAUUSD,M1_Trds=587_Prf=984_DD=3362_PF=1.05_SR=0.49_ARF=0.032.set'
R8_USDCHF = 'r8/deploy/R1696f82a0d700d5c7279/USDCHF/GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set'


class FixtureCase(unittest.TestCase):
    """Real exports from the g6 batch (window 2025.10.17-2026.08.28, forward 2026.07.17) and an
    earlier long run (BOOS 2024.12.26, 2025.06.26-2026.06.26, forward 2026.03.26), trimmed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'GOAT'
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, relative):
        return self.root / relative


class ReadExportTests(FixtureCase):
    def test_complete_capture_sets_the_evidence_end(self):
        export = ev.read_export(self.path(G6_AUDUSD))
        self.assertEqual((export['ea_name'], export['symbol'], export['period']), ('GOAT V1.49', 'AUDUSD', 'M1'))
        self.assertEqual(export['metrics'], dict(trades=406, profit=278, dd=91, pf=1.57, sr=2.92, arf=0.315))
        self.assertEqual(export['alias'], 'R02291b683f2bc5a39857')
        self.assertEqual(export['member'], 'R02291b683f2bc5a39857')
        self.assertEqual((export['evidence_start'], export['evidence_end'], export['evidence_end_source']),
                         ('2025-10-03', '2026-09-30', 'capture'))
        # The EA asked for ToDate 2026.10.02 (Thursday evidence); this symbol's ticks ended a day early.
        self.assertEqual(export['requested_end'], '2026-10-01')
        self.assertTrue(export['history_short'])
        self.assertEqual(export['windows']['FWD'], dict(start='2026-07-17', end='2026-08-28', days=30, trades=44, pl=21.0))
        self.assertEqual(export['windows']['FOOS']['end'], '2026-09-30')
        self.assertEqual(export['csv_last_date'], '2026-09-30')
        self.assertTrue(export['capture']['complete'])
        self.assertTrue(export['capture']['set_binding_matches'])
        self.assertEqual(export['capture']['initial_equity'], 100000)
        self.assertEqual(export['threshold'], dict(min_arf=0.2, min_sr=2.5, basis='run_export_settings', passing=True, profit_positive=True,
                                                   arf_margin=0.115, sr_margin=0.42, source='export_file_name_metrics'))
        self.assertEqual(export['tester']['ForwardDate'], '2026.07.17')
        self.assertEqual(export['tester']['ExecutionMode'], 0)
        self.assertEqual(export['run']['run_id'], 'g6')
        self.assertEqual(export['problems'], [])
        self.assertEqual(len(export['values_sha256']), 64)

    def test_full_thursday_end_and_incomplete_capture_uses_header(self):
        done = ev.read_export(self.path(G6_WS30_DONE))
        self.assertEqual((done['evidence_end'], done['history_short']), ('2026-10-01', False))
        rows = ev.read_export(self.path(G6_WS30_ROWS))
        self.assertFalse(rows['capture']['complete'])
        self.assertIn('row resource limit', rows['capture']['reason'])
        self.assertEqual((rows['evidence_end'], rows['evidence_end_source']), ('2026-10-01', 'set_header'))
        self.assertTrue(rows['threshold']['passing'])

    def test_below_threshold_keep_is_flagged(self):
        export = ev.read_export(self.path(G6_XAUUSD))
        self.assertFalse(export['threshold']['passing'])
        self.assertEqual((export['threshold']['arf_margin'], export['threshold']['sr_margin']), (-0.168, -2.01))
        self.assertEqual(export['evidence_end'], '2026-10-01')

    def test_earlier_run_ends_last_thursday(self):
        export = ev.read_export(self.path(R8_USDCHF))
        self.assertEqual((export['evidence_start'], export['evidence_end']), ('2024-12-26', '2026-09-24'))
        self.assertEqual(export['tester']['ForwardDate'], '2026.03.26')
        self.assertEqual(export['run']['back_oos_date'], '2024.12.26')

    def test_library_copy_without_run_files(self):
        copy = self.root / 'library' / 'source'
        copy.mkdir(parents=True)
        stem = Path(G6_AUDUSD).name[:-4]
        source = self.path(G6_AUDUSD).parent
        for name in (stem + '.set', stem + '.csv'):
            shutil.copyfile(source / name, copy / name)
        shutil.copytree(source / (stem + '.goatseq'), copy / (stem + '.goatseq'))
        export = ev.read_export(copy / (stem + '.set'))
        self.assertIsNone(export['run'])
        self.assertIsNone(export['tester'])
        self.assertEqual(export['threshold']['basis'], 'goat_minimum_defaults')
        self.assertTrue(export['threshold']['passing'])
        self.assertEqual(export['evidence_end'], '2026-09-30')

    def test_capture_bound_to_another_set_is_not_evidence(self):
        stem = Path(G6_AUDUSD).name[:-4]
        manifest = self.path(G6_AUDUSD).parent / (stem + '.goatseq') / 'manifest.json'
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['exports']['set']['sha256'] = '0' * 64
        manifest.write_text(json.dumps(value), encoding='utf-8')
        export = ev.read_export(self.path(G6_AUDUSD))
        self.assertIsNone(export['capture'])
        self.assertEqual(export['evidence_end_source'], 'set_header')
        self.assertIn('bound to a different SET', export['problems'][0])

    def test_optimization_set_is_not_an_export(self):
        bad = self.root / 'template.set'
        bad.write_bytes('EA_Desc=x\r\nGrid_Size=1||1||1||3||Y\r\n'.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'optimization axes'):
            ev.read_export(bad)

    def test_stem_parser_handles_spaces(self):
        parsed = ev.parse_stem('GOAT V1.49 GER40 cash,H1_Trds=10_Prf=-5.5_DD=3_PF=0.9_SR=1_ARF=0.1', 'GER40 cash')
        self.assertEqual((parsed['ea_name'], parsed['symbol'], parsed['period']), ('GOAT V1.49', 'GER40 cash', 'H1'))
        self.assertEqual(parsed['metrics']['profit'], -5.5)
        self.assertEqual(ev.parse_stem('GOAT V1.49 US500#,MN1_Trds=1_Prf=1_DD=1_PF=1_SR=1_ARF=1')['period'], 'MN1')
        self.assertIsNone(ev.parse_stem('GOAT V1.49 AUDUSD,M1_Trds=1'))

    def test_weekdays_and_server_dates(self):
        from datetime import date
        self.assertEqual(ev.weekdays(date(2026, 9, 25), date(2026, 10, 2)), 6)
        self.assertEqual(ev.weekdays(date(2026, 10, 1), date(2026, 10, 2)), 2)
        self.assertEqual(ev.weekdays(date(2026, 10, 3), date(2026, 10, 4)), 0)
        self.assertEqual(ev.weekdays(date(2026, 10, 2), date(2026, 10, 1)), 0)
        self.assertEqual(ev.server_date(1790812798000).isoformat(), '2026-09-30')
        self.assertEqual(ev.server_msc(date(2026, 10, 2)), 1790899200000)


class ScanTests(FixtureCase):
    def test_sources_of_every_shape(self):
        whole = ev.collect_sets([self.root])
        self.assertEqual(len(whole), 6)
        self.assertFalse(any('.goatseq' in str(p.parent) for p in whole))
        run = ev.collect_sets([self.root / 'g6'])
        self.assertEqual(len(run), 4)
        member = ev.collect_sets([self.root / 'g6' / 'deploy' / 'R31019b1ffd701fff0826'])
        self.assertEqual(len(member), 2)
        mixed = ev.collect_sets([self.path(G6_AUDUSD), self.root / 'g6', self.path(G6_AUDUSD)])
        self.assertEqual(len(mixed), 4)

    def test_sources_must_be_absolute_and_exist(self):
        with self.assertRaisesRegex(ValueError, 'absolute'):
            ev.collect_sets(['relative/folder'])
        with self.assertRaisesRegex(ValueError, 'not found'):
            ev.collect_sets([self.root / 'missing'])
        with self.assertRaisesRegex(ValueError, 'exported .set'):
            ev.collect_sets([self.root / 'g6' / 'manifest.json'])
        with self.assertRaisesRegex(ValueError, 'scan fewer'):
            ev.collect_sets([self.root], limit=2)

    def test_unreadable_units_are_reported(self):
        broken = self.root / 'g6' / 'deploy' / 'Rbroken' / 'EURUSD'
        broken.mkdir(parents=True)
        (broken / 'GOAT V1.49 EURUSD,M1_Trds=1_Prf=1_DD=1_PF=1_SR=1_ARF=1.set').write_bytes(b'\xff\xfe' + 'no assignment\r\n'.encode('utf-16-le'))
        exports, unreadable = ev.scan([self.root / 'g6'])
        self.assertEqual(len(exports), 4)
        self.assertEqual(len(unreadable), 1)
        self.assertIn('EURUSD', unreadable[0]['set_path'])

    def test_scan_never_writes(self):
        before = sorted((p.relative_to(self.root), p.stat().st_mtime_ns) for p in self.root.rglob('*'))
        ev.scan([self.root])
        after = sorted((p.relative_to(self.root), p.stat().st_mtime_ns) for p in self.root.rglob('*'))
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
