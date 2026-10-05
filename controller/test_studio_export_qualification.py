"""goat-export-qualification-v1: qualifying = passed the run's own export thresholds, nothing else.

The EA keeps its best set even when none passed (SortAndTrimExports: Passing=0 Kept=1); those
sets are below_threshold, a set at the cut-off is unknown and never passed, and every surface
(research-status, research-queue, finish's export scan, evidence reads, gate calibration) uses
the one judgement in studio_export_qualification.
"""
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_export_qualification as eq
from studio_research_status import batch_progress, headline

NOW = 1_790_000_000.0
SETTINGS = '[Export]\r\nAdjustLots=0\r\nBackOOSDate=2025.10.03\r\nIncludeBackOOS=1\r\nMinARF=0.2\r\nMinSR=2.5\r\nMinScore=60.0\r\nSetsToExport=2\r\n'


def name(symbol, sr, arf, prf='566', ea='GOAT V1.49'):
    return '%s %s,M1_Trds=781_Prf=%s_DD=564_PF=1.22_SR=%s_ARF=%s' % (ea, symbol, prf, sr, arf)


def header(sr, arf, ret='566'):
    return ('; ------\r\n; GOAT V1.49 AUDUSD,M1\r\n; Days=258 Weeks=51.0 Months=11.9\r\n; Trades=781 Sequences=454\r\n'
            '; PF=1.220 RF=1.003 SR=%s ARF=%s\r\n; Return=%s MonthlyRet=48 DD=564\r\n; ------\r\nMode_Operation=9\r\n'
            'EA_Desc=R2cb17f79c01e8241d45b\r\n' % (sr, arf, ret))


def write_unit(folder, stem, set_text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (stem + '.set')).write_bytes(set_text.encode('utf-16'))
    (folder / (stem + '.csv')).write_text('x', encoding='utf-8')
    return folder / (stem + '.set')


def write_log(run, passes, adjusted=None):
    lines = ['2026.10.02 21:17:12 23:54:56  GOAT V1.49: ✅ Export sequence complete: 4 attempts – 4 profitable, 0 losses, '
             '0 errors, 0 duplicates, %d passed thresholds.' % n for n in passes]
    for n in adjusted or []:
        lines.append('2026.10.02 21:18:12 23:54:56  GOAT V1.49: ✅ Export Adjustment sequence complete: 2 attempts – 2 '
                     'profitable, 0 losses, 0 errors, %d passed thresholds' % n)
    (run / 'log.GOAT').write_bytes('\r\n'.join(lines).encode('utf-16'))


def judge(sr, arf, *, header_text=None, settings=SETTINGS, prf='566'):
    tokens = eq.file_name_tokens(name('AUDUSD', sr, arf, prf))
    return eq.qualify(tokens, eq.thresholds_from_settings_text(settings), header=header_text)


class SettingsTests(unittest.TestCase):
    def test_reads_the_settings_the_way_the_ea_does(self):
        limits = eq.thresholds_from_settings_text(SETTINGS)
        self.assertEqual((limits['available'], float(limits['min_sr']), float(limits['min_arf'])), (True, 2.5, 0.2))
        # FetchExportSetting: the first trimmed "key=" line wins, and [Export] must be present.
        first = eq.thresholds_from_settings_text('[Export]\nMinSR=3.0\nMinSR=2.5\nMinARF=0.25\n')
        self.assertEqual((float(first['min_sr']), float(first['min_arf'])), (3.0, 0.25))
        self.assertFalse(eq.thresholds_from_settings_text('MinSR=2.5\nMinARF=0.2\n')['available'])

    def test_missing_threshold_means_no_threshold_never_a_pass(self):
        limits = eq.thresholds_from_settings_text('[Export]\nMinSR=2.5\n')
        self.assertFalse(limits['available'])
        self.assertIn('MinARF missing', limits['problems'][0])
        stamp = eq.qualify(eq.file_name_tokens(name('AUDUSD', '9.99', '0.900')), limits)
        self.assertEqual((stamp['status'], stamp['missed'], stamp['selection']), ('unknown', ['thresholds_unavailable'], 'unknown'))

    def test_run_folder_without_settings_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(eq.read_run_thresholds(temp)['available'])
            Path(temp, 'export_settings.GOAT').write_bytes(SETTINGS.encode('utf-16'))
            self.assertTrue(eq.read_run_thresholds(temp)['available'])


class JudgementTests(unittest.TestCase):
    def test_pass_and_the_two_ways_to_miss(self):
        passed = judge('2.92', '0.315')
        self.assertEqual((passed['status'], passed['missed'], passed['selection'], passed['ea_native_passed']),
                         ('passed', [], 'passed_gate', True))
        low_arf = judge('2.91', '0.120')
        self.assertEqual((low_arf['status'], low_arf['missed'], low_arf['selection']), ('below_threshold', ['ARF'], 'best_of_failed_search'))
        self.assertEqual(eq.missed_words(low_arf), 'SR 2.91 passes · ARF 0.120 < 0.2 misses')
        both = judge('1.07', '0.084')
        self.assertEqual(both['missed'], ['SR', 'ARF'])
        sr = next(c for c in both['checks'] if c['metric'] == 'SR')
        self.assertEqual((sr['value'], sr['threshold'], sr['passed'], sr['margin'], sr['source'], sr['decimals']),
                         (1.07, 2.5, False, -1.43, 'file_name', 2))

    def test_run_thresholds_decide_not_goat_defaults(self):
        strict = '[Export]\nMinSR=3.0\nMinARF=0.2\n'
        self.assertEqual(judge('2.90', '0.500', settings=strict)['missed'], ['SR'])
        self.assertEqual(judge('2.90', '0.500')['status'], 'passed')

    def test_decisive_file_name_values_never_open_the_set(self):
        def boom():
            raise AssertionError('the SET header must not be read away from the cut-off')
        self.assertEqual(judge('2.49', '0.300', header_text=boom)['status'], 'below_threshold')
        self.assertEqual(judge('2.51', '0.300', header_text=boom)['status'], 'passed')
        self.assertEqual(judge('2.51', '0.201', header_text=boom)['status'], 'passed')

    def test_cutoff_2_495_misses_2_505_passes_from_the_header(self):
        # The file name says 2.50 for both: the EA itself counted both as passed (>= 2.5 on the rounded value).
        low = judge('2.50', '0.300', header_text=header('2.495', '0.300'))
        self.assertEqual((low['status'], low['missed'], low['ea_native_passed']), ('below_threshold', ['SR'], True))
        check = next(c for c in low['checks'] if c['metric'] == 'SR')
        self.assertEqual((check['source'], check['value'], check['decimals'], check['file_name_value'], check['passed']),
                         ('set_header', 2.495, 3, 2.5, False))
        high = judge('2.50', '0.300', header_text=header('2.505', '0.300'))
        self.assertEqual((high['status'], high['missed']), ('passed', []))

    def test_header_still_at_the_cutoff_is_unknown_never_passed(self):
        stamp = judge('2.50', '0.300', header_text=header('2.500', '0.300'))
        self.assertEqual((stamp['status'], stamp['missed'], stamp['selection']), ('unknown', ['at_cutoff'], 'unknown'))
        self.assertTrue(stamp['ea_native_passed'])
        no_header = judge('2.50', '0.300', header_text='Mode_Operation=9\n')
        self.assertEqual((no_header['status'], no_header['missed']), ('unknown', ['at_cutoff']))

    def test_arf_has_no_extra_header_precision(self):
        stamp = judge('2.92', '0.200', header_text=header('2.920', '0.200'))
        self.assertEqual((stamp['status'], stamp['missed']), ('unknown', ['at_cutoff']))
        self.assertEqual(judge('2.92', '0.201')['status'], 'passed')
        self.assertEqual(judge('2.92', '0.199')['missed'], ['ARF'])

    def test_a_definite_miss_wins_over_a_cutoff(self):
        stamp = judge('2.50', '0.120', header_text=header('2.500', '0.120'))
        self.assertEqual((stamp['status'], stamp['missed']), ('below_threshold', ['ARF', 'at_cutoff']))

    def test_header_that_disagrees_with_the_name_is_unknown(self):
        stamp = judge('2.50', '0.300', header_text=header('2.700', '0.300'))
        self.assertEqual((stamp['status'], stamp['missed']), ('unknown', ['header_disagrees']))

    def test_unparsed_names_are_unknown(self):
        stamp = eq.qualify(eq.file_name_tokens('a'), eq.thresholds_from_settings_text(SETTINGS))
        self.assertEqual((stamp['status'], stamp['missed']), ('unknown', ['metrics_unavailable']))

    def test_numbers_from_other_readers_keep_the_file_name_precision(self):
        tokens = eq.tokens_from_numbers(dict(sr=2.5, arf=0.3, net=100.0))
        self.assertEqual(eq.qualify(tokens, eq.thresholds_from_values(2.5, 0.2, 'test'))['status'], 'unknown')
        self.assertEqual(eq.qualify(tokens, eq.thresholds_from_values(2.5, 0.2, 'test'),
                                    header=header('2.504', '0.300'))['status'], 'passed')

    def test_member_class(self):
        p, b, u = (dict(status=s) for s in ('passed', 'below_threshold', 'unknown'))
        self.assertEqual(eq.summarize([b, p])['member'], 'passed')
        self.assertEqual(eq.summarize([b, u])['member'], 'unknown')
        self.assertEqual(eq.summarize([b])['member'], 'below_threshold')
        self.assertIsNone(eq.summarize([])['member'])


class RunFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.common = Path(self.temp.name) / 'common'
        self.run = self.common / 'GOAT' / 'Rabcdef012345'
        self.run.mkdir(parents=True)
        (self.run / 'export_settings.GOAT').write_bytes(SETTINGS.encode('utf-16'))

    def member(self, alias, symbol, *values):
        for sr, arf, head in values:
            write_unit(self.run / 'deploy' / alias / symbol, name(symbol, sr, arf), header(head or (sr + '0'), arf))


class ScanRunTests(RunFixture):
    def fill(self):
        self.member('R1', 'AUDUSD', ('2.92', '0.315', None), ('3.01', '0.499', None))   # 2 passed
        self.member('R2', 'EURUSD', ('1.07', '0.084', None))                            # Passing=0 Kept=1
        self.member('R3', 'USDJPY', ('2.50', '0.300', '2.495'))                         # EA counted it; the header says 2.495

    def test_log_crosscheck_matches_the_ea_counts(self):
        self.fill()
        write_log(self.run, [2, 0, 1])
        result = eq.scan_run(self.run, generated_at='2026-10-05T00:00:00Z')
        self.assertEqual(result['log_crosscheck']['status'], 'match')
        self.assertEqual((result['log_crosscheck']['log_passed_sets'], result['log_crosscheck']['stamped_native_passed_sets']), (3, 3))
        counts = result['counts']
        self.assertEqual((counts['members'], counts['sets'], counts['passed_members'], counts['passed_sets'],
                          counts['below_threshold_members'], counts['below_threshold_sets']), (3, 4, 1, 2, 2, 2))
        self.assertEqual(len({s['set_sha256'] for s in result['stamps']}), 4)
        self.assertEqual(result['thresholds']['min_sr'], 2.5)

    def test_a_log_that_disagrees_turns_every_pass_unknown(self):
        self.fill()
        write_log(self.run, [2, 1, 1])
        result = eq.scan_run(self.run)
        self.assertEqual(result['log_crosscheck']['status'], 'mismatch')
        self.assertEqual(result['counts']['passed_sets'], 0)
        flipped = [s for s in result['stamps'] if s.get('status_before_crosscheck') == 'passed']
        self.assertEqual(len(flipped), 2)
        self.assertEqual(flipped[0]['missed'], ['log_crosscheck_mismatch'])

    def test_no_log_is_never_a_confirmation(self):
        self.fill()
        result = eq.scan_run(self.run)
        self.assertEqual((result['log_crosscheck']['status'], result['counts']['passed_sets']), ('unavailable', 0))

    def test_adjust_lots_reads_the_adjustment_lines(self):
        (self.run / 'export_settings.GOAT').write_bytes(SETTINGS.replace('AdjustLots=0', 'AdjustLots=1').encode('utf-16'))
        self.member('R1', 'AUDUSD', ('2.92', '0.315', None))
        write_log(self.run, [2], adjusted=[1])
        self.assertEqual(eq.scan_run(self.run)['log_crosscheck']['status'], 'match')

    def test_command_appends_a_record_and_never_overwrites(self):
        import demo_agent
        self.fill()
        write_log(self.run, [2, 0, 1])
        state = Path(self.temp.name) / 'state'
        install = dict(controller_state_root=str(state))
        args = type('Args', (), dict(source=[self.run], write=True, installation=Path(self.temp.name) / 'installation.json'))()
        when = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
        with patch.object(demo_agent, 'load_installation', return_value=install):
            result = demo_agent._export_qualification_command(args, now=when)
            self.assertEqual(result['totals']['passed_members'], 1)
            written = Path(result['written'][0])
            self.assertEqual(written, state / 'export-qualification' / 'Rabcdef012345' / '2026-10-05T120000Z.json')
            self.assertEqual(json.loads(written.read_text(encoding='utf-8'))['schema'], eq.BACKFILL_SCHEMA)
            with self.assertRaises(FileExistsError):
                demo_agent._export_qualification_command(args, now=when)

    def test_read_only_command_prints_json(self):
        import demo_agent
        self.fill()
        write_log(self.run, [2, 0, 1])
        out = io.StringIO()
        with redirect_stdout(out):
            code = demo_agent.main(['--installation', str(Path(self.temp.name) / 'none.json'), 'export-qualification',
                                    '--source', str(self.run)])
        self.assertEqual(code, 0)
        value = json.loads(out.getvalue())
        self.assertEqual((value['result']['totals']['passed_sets'], value['result']['written']), (2, []))


class ResearchStatusTests(RunFixture):
    """research-status over a real package manifest: qualifying = passed, kept-below shown apart."""
    SYMBOLS = ('AUDUSD', 'EURUSD', 'USDJPY', 'NZDUSD')

    def setUp(self):
        super().setUp()
        from studio_bridge import write_json
        self.root = Path(self.temp.name) / 'state'
        self.aliases = ['R' + str(i) * 20 for i in range(len(self.SYMBOLS))]
        package = self.root / 'packages' / 'g6'; package.mkdir(parents=True)
        jobs = [dict(run_alias=alias, tester=dict(Symbol=symbol, Period='M1')) for alias, symbol in zip(self.aliases, self.SYMBOLS)]
        write_json(package / 'manifest.json', dict(native_run_relative='GOAT\\Rabcdef012345', jobs=jobs))
        self.install = dict(common_files_root=str(self.common))
        self.job = dict(job_id='g6', launch_intent={}, configuration=dict(batch_members=[{}] * len(self.SYMBOLS)))

    def progress(self, statuses):
        native = dict(status='native_ongoing' if 'native_ongoing' in statuses else 'native_completed',
                      members=[dict(status=s) for s in statuses], completed_count=statuses.count('native_completed'),
                      finished_count=sum(s in ('native_completed', 'native_error', 'native_cancelled') for s in statuses),
                      status_counts={s: statuses.count(s) for s in set(statuses)})
        with patch('studio_native_observe.observe', return_value=native):
            return batch_progress(self.root, self.install, self.job, now=NOW, journal=None)

    def test_kept_below_threshold_is_not_qualifying(self):
        self.member(self.aliases[0], 'AUDUSD', ('2.92', '0.315', None), ('1.20', '0.100', None))   # mixed member
        self.member(self.aliases[1], 'EURUSD', ('1.07', '0.084', None))                            # Passing=0 Kept=1
        self.member(self.aliases[2], 'USDJPY', ('2.50', '0.300', '2.500'))                         # at the cut-off
        value = self.progress(['native_completed', 'native_completed', 'native_completed', 'native_ongoing'])
        self.assertEqual((value['qualifying'], value['passing_sets'], value['exported_sets']), (1, 1, 4))
        self.assertEqual((value['below_threshold_members'], value['below_threshold_sets']), (1, 2))
        self.assertEqual((value['unknown_members'], value['unknown_sets']), (1, 1))
        self.assertEqual(value['thresholds'], dict(min_sr=2.5, min_arf=0.2, source='run_export_settings_file'))
        self.assertEqual(value['qualifying_basis'], 'goat-export-qualification-v1')
        text = headline(dict(kind='batch', status='running', **value, _now=NOW))
        self.assertIn('3 of 4 members done, 1 qualifying (SR ≥ 2.5, ARF ≥ 0.2), 1 more kept below threshold, '
                      '1 at the cut-off, not counted', text)

    def test_single_kept_set_below_threshold_and_last_member(self):
        self.member(self.aliases[0], 'AUDUSD', ('1.07', '0.084', None))
        value = self.progress(['native_completed', 'native_pending', 'native_pending', 'native_pending'])
        self.assertEqual((value['qualifying'], value['below_threshold_members']), (0, 1))
        last = value['last_member']
        self.assertEqual((last['exported_sets'], last['passing_sets'], last['below_threshold_sets'], last['qualifies']), (1, 0, 1, False))

    def test_no_settings_file_is_never_qualifying(self):
        (self.run / 'export_settings.GOAT').unlink()
        self.member(self.aliases[0], 'AUDUSD', ('2.92', '0.315', None))
        value = self.progress(['native_completed', 'native_pending', 'native_pending', 'native_pending'])
        self.assertEqual((value['qualifying'], value['unknown_members'], value['thresholds']), (0, 1, None))
        self.assertIn('1 kept but not judged (no export thresholds found)', headline(dict(kind='batch', status='running', **value)))


class HeldOutKeysTests(unittest.TestCase):
    def test_new_counts_and_stamps_are_redacted_under_a_lock(self):
        from studio_heldout_guard import METRIC_KEYS, METRIC_STATUSES
        for key in ('qualifying', 'passing_sets', 'below_threshold_members', 'below_threshold_sets', 'unknown_members',
                    'unknown_sets', 'qualification', 'checks', 'missed', 'ea_native_passed', 'log_crosscheck', 'stamps',
                    'unproven_members', 'threshold'):
            self.assertIn(key, METRIC_KEYS)
        self.assertIn('native_threshold_unknown', METRIC_STATUSES)


if __name__ == '__main__':
    unittest.main()
