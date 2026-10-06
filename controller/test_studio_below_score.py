"""Research-only below_score exports (GOAT-EA BS42, goatai#1885: Claude-Mac 6021965811 and 6022008420).

When nothing a member tested reached the export score, the EA exports its one best profitable pass
(ranked on FWD profit/DD) into ``<run>\\below_score\\<alias>\\<symbol>\\`` with ``; EXPORT: below_score``
in its SET header. Fail closed, on every controller surface:

* it is an attempt, never a pass: its qualification stamp is ``unknown`` (``missed: ['below_score']``),
  never ``passed``, whatever its SR/ARF, and either signal (header or folder) is enough;
* it is counted on its own (``below_score_sets`` / ``below_score_members``), never in qualifying,
  exported, passing, kept-below-threshold or unknown counts, and never in the EA log cross-check;
* catch-up re-tests it only on the explicit research opt-in; gate calibration never reads it;
* the item_stats row that reports it keeps its NoQualifyingRows outcome and FinalExports=0.
"""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import studio_evidence as ev
import studio_export_qualification as eq
from studio_catchup import classify
from studio_research_status import _no_edge_outcome, batch_progress, headline, item_outcomes
from test_studio_export_qualification import NOW, SETTINGS, header, name, write_unit
from test_studio_research_outcome import QDETAILS, TIMING, q_row, write_stats

TAG = '; EXPORT: below_score research only, nothing scored at or above the export score\r\n'
FIXTURES = Path(__file__).parent / 'fixtures' / 'oosc'
G6_AUDUSD = ('R02291b683f2bc5a39857', 'AUDUSD', 'GOAT V1.49 AUDUSD,M1_Trds=406_Prf=278_DD=91_PF=1.57_SR=2.92_ARF=0.315')
BELOW = (';below_score=exported;below_score_pass=17;below_score_fwd_profit_dd=1.8421;below_score_fwd_profit=212.40;'
         'below_score_fwd_trades=44;below_score_combined_score=48.1;below_score_rank=fwd_profit_dd;below_score_min_fwd_trades=30')


def tagged(sr, arf, head=None):
    """A SET header with the EA's below_score line after the window lines."""
    text = header(head or (sr + '0'), arf)
    cut = text.index('Mode_Operation=')
    return text[:cut] + TAG + text[cut:]


class TierTests(unittest.TestCase):
    def test_header_line_and_folder_each_make_a_unit_research_only(self):
        self.assertEqual(eq.export_tier(tagged('2.92', '0.315')), eq.BELOW_SCORE)
        self.assertEqual(eq.export_tier('\ufeff' + TAG), eq.BELOW_SCORE)
        self.assertEqual(eq.export_tier(header('2.920', '0.315')), eq.STANDARD_TIER)
        run = Path('C:/x/GOAT/Rabc')
        self.assertEqual(eq.export_tier(None, run / 'below_score' / 'R1' / 'AUDUSD' / 'a.set'), eq.BELOW_SCORE)
        self.assertEqual(eq.export_tier(header('2.920', '0.315'), run / 'below_score' / 'R1' / 'AUDUSD' / 'a.set'), eq.BELOW_SCORE)
        self.assertEqual(eq.export_tier(None, run / 'deploy' / 'R1' / 'AUDUSD' / 'a.set'), eq.STANDARD_TIER)

    def test_an_unknown_tier_is_research_only_too(self):
        self.assertEqual(eq.export_tier('; EXPORT: second_slot\r\n'), 'unrecognised:second_slot')
        self.assertEqual(eq.export_tier('; EXPORT:\r\n'), 'unrecognised:')
        stamp = eq.research_only_stamp(dict(status='passed', selection='passed_gate', missed=[]), 'unrecognised:x')
        self.assertEqual(stamp['status'], 'unknown')

    def test_only_the_header_is_read(self):
        late = header('2.920', '0.315') + ''.join('Input%d=1\r\n' % i for i in range(eq.TIER_HEADER_LINES)) + TAG
        self.assertEqual(eq.export_tier(late), eq.STANDARD_TIER)

    def test_a_research_only_stamp_is_never_passed(self):
        passed = eq.qualify(eq.file_name_tokens(name('AUDUSD', '2.92', '0.315')), eq.thresholds_from_settings_text(SETTINGS))
        self.assertEqual(passed['status'], 'passed')
        stamp = eq.research_only_stamp(passed, eq.BELOW_SCORE)
        self.assertEqual((stamp['status'], stamp['selection'], stamp['missed'], stamp['status_before_tier'], stamp['export_tier'],
                          stamp['ea_native_passed']), ('unknown', 'unknown', ['below_score'], 'passed', 'below_score', False))
        self.assertIs(eq.research_only_stamp(passed, eq.STANDARD_TIER), passed)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.common = Path(self.temp.name) / 'common'
        self.run = self.common / 'GOAT' / 'Rabcdef012345'
        self.run.mkdir(parents=True)
        (self.run / 'export_settings.GOAT').write_bytes(SETTINGS.encode('utf-16'))
        self.thresholds = eq.read_run_thresholds(self.run)

    def test_stamp_set_reads_the_tier_of_a_passing_set(self):
        # A tagged SET that would pass, misplaced in deploy: the header alone keeps it from passing, even
        # on the status path that otherwise opens no file.
        path = write_unit(self.run / 'deploy' / 'R1' / 'AUDUSD', name('AUDUSD', '2.92', '0.315'), tagged('2.92', '0.315'))
        for with_sha256 in (True, False):
            stamp = eq.stamp_set(path, self.thresholds, with_sha256=with_sha256)
            self.assertEqual((stamp['status'], stamp['status_before_tier']), ('unknown', 'passed'))
        plain = write_unit(self.run / 'deploy' / 'R2' / 'AUDUSD', name('AUDUSD', '2.92', '0.315'), header('2.920', '0.315'))
        self.assertEqual(eq.stamp_set(plain, self.thresholds, with_sha256=False)['status'], 'passed')

    def test_stamp_set_by_folder_alone(self):
        path = write_unit(self.run / 'below_score' / 'R1' / 'AUDUSD', name('AUDUSD', '2.92', '0.315'), header('2.920', '0.315'))
        for with_sha256 in (True, False):
            self.assertEqual(eq.stamp_set(path, self.thresholds, with_sha256=with_sha256)['status'], 'unknown')
        below = write_unit(self.run / 'below_score' / 'R2' / 'EURUSD', name('EURUSD', '1.07', '0.084'), header('1.070', '0.084'))
        self.assertEqual(eq.stamp_set(below, self.thresholds, with_sha256=False)['status'], 'unknown')

    def test_scan_run_counts_research_units_apart(self):
        write_unit(self.run / 'deploy' / 'R1' / 'AUDUSD', name('AUDUSD', '2.92', '0.315'), header('2.920', '0.315'))
        write_unit(self.run / 'below_score' / 'R2' / 'EURUSD', name('EURUSD', '2.95', '0.401'), tagged('2.95', '0.401'))
        write_unit(self.run / 'below_score' / 'R3' / 'USDJPY', name('USDJPY', '1.07', '0.084'), tagged('1.07', '0.084'))
        (self.run / 'log.GOAT').write_bytes(('2026.10.02 21:17:12 23:54:56  GOAT V1.49: Export sequence complete: 1 attempts '
                                             '- 1 profitable, 0 losses, 0 errors, 0 duplicates, 1 passed thresholds.\r\n').encode('utf-16'))
        result = eq.scan_run(self.run)
        counts = result['counts']
        self.assertEqual((counts['members'], counts['sets'], counts['passed_sets'], counts['passed_members'],
                          counts['unknown_sets'], counts['unknown_members']), (1, 1, 1, 1, 0, 0))
        self.assertEqual((counts['below_score_sets'], counts['below_score_members']), (2, 2))
        self.assertEqual(result['log_crosscheck']['status'], 'match', 'research units never enter the EA log cross-check')
        self.assertEqual([(e['member'], e['symbol'], e['qualification']['status'], e['qualification']['export_tier'])
                          for e in result['research_only']],
                         [('R2', 'EURUSD', 'unknown', 'below_score'), ('R3', 'USDJPY', 'unknown', 'below_score')])
        self.assertEqual(result['research_only'][0]['qualification']['status_before_tier'], 'passed')
        self.assertTrue(all(len(e['set_sha256']) == 64 for e in result['research_only']))

    def test_export_scan_never_offers_a_tagged_unit(self):
        from studio_export_scan import scan_exports
        folder = self.run / 'deploy' / 'R1' / 'AUDUSD'
        write_unit(folder, name('AUDUSD', '2.92', '0.315'), tagged('2.92', '0.315'))
        with patch('studio_export_scan.verify_export_inputs', return_value={}), \
             patch('studio_export_scan.inspect_equity_csv', return_value={}):
            result = scan_exports(folder, b'', {}, 1, 1, alias='R1', symbol='AUDUSD', period='M1', expert_name='GOAT V1.49',
                                  min_arf=0.2, min_sr=2.5)
        self.assertEqual(result['files'][0]['status'], 'native_threshold_unknown')
        self.assertEqual(result['native_threshold_candidate_count'], 0)


class EvidenceTests(unittest.TestCase):
    """Real g6 unit (SR 2.92, ARF 0.315: it would pass) moved into the research-only folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'GOAT'
        shutil.copytree(FIXTURES, self.root)
        alias, symbol, stem = G6_AUDUSD
        source, target = self.root / 'g6' / 'deploy' / alias / symbol, self.root / 'g6' / 'below_score' / alias / symbol
        target.mkdir(parents=True)
        for suffix in ('.set', '.csv', '.goatseq'):
            shutil.move(str(source / (stem + suffix)), str(target / (stem + suffix)))
        self.set_path = target / (stem + '.set')

    def test_read_export_carries_the_tier_and_never_passes(self):
        export = ev.read_export(self.set_path)
        self.assertEqual((export['export_tier'], export['research_only']), ('below_score', True))
        self.assertEqual((export['qualification']['status'], export['qualification']['status_before_tier']), ('unknown', 'passed'))
        self.assertEqual((export['threshold']['passing'], export['threshold']['retest_eligible']), (False, False))
        # Everything else about the unit still reads: the run, member, windows and capture.
        self.assertEqual((export['run']['run_id'], export['member'], export['problems']), ('g6', G6_AUDUSD[0], []))
        self.assertTrue(export['capture']['complete'])
        self.assertEqual(export['windows']['FWD']['trades'], 44)

    def test_a_run_folder_scan_carries_both_tiers(self):
        exports, unreadable = ev.scan([str(self.root / 'g6')])
        self.assertEqual(unreadable, [])
        tiers = sorted((e['symbol'], e['export_tier']) for e in exports)
        self.assertIn(('AUDUSD', 'below_score'), tiers)
        self.assertTrue(all(t == 'standard' for s, t in tiers if s != 'AUDUSD'))
        standard = [e for e in exports if e['export_tier'] == 'standard']
        self.assertTrue(standard and not any(e['research_only'] for e in standard))

    def test_catch_up_needs_the_explicit_research_opt_in(self):
        export = ev.read_export(self.set_path)
        row = classify(export, '2026-10-01')
        self.assertEqual((row['status'], row['export_tier']), ('ineligible', 'below_score'))
        self.assertTrue(any('Research-only below_score export' in reason for reason in row['reasons']))
        opted = classify(export, '2026-10-01', include_below_threshold=True)
        self.assertNotEqual(opted['status'], 'ineligible')
        self.assertFalse(opted['threshold_passing'])


class ItemStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def test_row_keeps_its_outcome_and_carries_the_pick(self):
        outcome = _no_edge_outcome(QDETAILS + BELOW, 'no_qualifying_rows')
        self.assertEqual(outcome['outcome'], 'no_qualifying_rows')
        self.assertEqual(outcome['below_score'], dict(result='exported', rank='fwd_profit_dd', pass_number=17, fwd_profit_dd=1.8421,
                                                      fwd_profit=212.4, fwd_trades=44, combined_score=48.1, min_fwd_trades=30, kept=1))
        write_stats(self.run, [q_row('A0', 'USDCAD', details=QDETAILS + BELOW)])
        found = item_outcomes(self.run, [('A0', 'USDCAD')], TIMING)
        self.assertEqual(found[0]['below_score']['result'], 'exported')

    def test_older_rows_and_other_results(self):
        self.assertNotIn('below_score', _no_edge_outcome(QDETAILS, 'no_qualifying_rows'))
        none = _no_edge_outcome(QDETAILS + ';below_score=none;below_score_rank=fwd_profit_dd;below_score_min_fwd_trades=30',
                                'no_qualifying_rows')
        self.assertEqual(none['below_score'], dict(result='none', rank='fwd_profit_dd'))
        lost = _no_edge_outcome(QDETAILS + BELOW.replace('=exported', '=lost'), 'no_qualifying_rows')
        self.assertEqual((lost['below_score']['result'], lost['below_score']['pass_number']), ('lost', 17))

    def test_the_slot_rule_facts(self):
        two = BELOW.replace(';below_score_pass', ';below_score_kept=2;below_score_pass') + (
            ';slot1_pass=17;slot1=kept;slot2_pass=21;slot2_character=SL_Pips 0->10;slot2_correlation=0.912;slot2_days=59;'
            'slot2=kept;slot2_reason=different character: SL_Pips 0->10')
        facts = _no_edge_outcome(QDETAILS + two, 'no_qualifying_rows')['below_score']
        self.assertEqual((facts['result'], facts['kept']), ('exported', 2))
        self.assertEqual(facts['slot2'], dict(result='kept', reason='different character: SL_Pips 0->10', correlation='0.912',
                                              character='SL_Pips 0->10'))
        skipped = BELOW + ';slot2=skipped;slot2_correlation=0.940;slot2_reason=same character and SAMPLE correlation 0.940 above 0.5'
        facts = _no_edge_outcome(QDETAILS + skipped, 'no_qualifying_rows')['below_score']
        self.assertEqual((facts['kept'], facts['slot2']['result'], facts['slot2']['correlation']), (1, 'skipped', '0.940'))
        # Two kept units without a kept slot 2, or a kept slot 2 counted once, never read as a clean export.
        for details in (BELOW.replace(';below_score_pass', ';below_score_kept=2;below_score_pass') + ';slot2=skipped',
                        BELOW + ';slot2=kept', BELOW.replace(';below_score_pass', ';below_score_kept=3;below_score_pass')):
            self.assertEqual(_no_edge_outcome(QDETAILS + details, 'no_qualifying_rows')['below_score']['result'], 'unreadable', details)

    def test_an_unreadable_report_is_never_a_kept_export(self):
        for label, details in (('unknown result', BELOW.replace('=exported', '=kept')),
                               ('exported without its figures', ';below_score=exported'),
                               ('a figure that is not a number', BELOW.replace('=1.8421', '=n/a'))):
            outcome = _no_edge_outcome(QDETAILS + details, 'no_qualifying_rows')
            self.assertEqual(outcome['outcome'], 'no_qualifying_rows', label)
            self.assertEqual(outcome['below_score']['result'], 'unreadable', label)


class BatchProgressTests(unittest.TestCase):
    SYMBOLS = ('AUDUSD', 'EURUSD', 'USDJPY')

    def setUp(self):
        from studio_bridge import write_json
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.common = Path(self.temp.name) / 'common'
        self.run = self.common / 'GOAT' / 'Rabcdef012345'
        self.run.mkdir(parents=True)
        (self.run / 'export_settings.GOAT').write_bytes(SETTINGS.encode('utf-16'))
        self.root = Path(self.temp.name) / 'state'
        self.aliases = ['R' + str(i) * 20 for i in range(len(self.SYMBOLS))]
        package = self.root / 'packages' / 'g7'; package.mkdir(parents=True)
        jobs = [dict(run_alias=alias, tester=dict(Symbol=symbol, Period='M1')) for alias, symbol in zip(self.aliases, self.SYMBOLS)]
        write_json(package / 'manifest.json', dict(native_run_relative='GOAT\\Rabcdef012345', jobs=jobs))
        self.install = dict(common_files_root=str(self.common))
        self.job = dict(job_id='g7', launch_intent={}, configuration=dict(batch_members=[{}] * len(self.SYMBOLS)))

    def progress(self, statuses):
        native = dict(status='native_completed', members=[dict(status=s) for s in statuses],
                      completed_count=statuses.count('native_completed'),
                      finished_count=sum(s in ('native_completed', 'native_error', 'native_cancelled') for s in statuses),
                      status_counts={s: statuses.count(s) for s in set(statuses)})
        with patch('studio_native_observe.observe', return_value=native):
            return batch_progress(self.root, self.install, self.job, now=NOW, journal=None)

    def test_research_units_are_their_own_count_never_qualifying(self):
        write_unit(self.run / 'deploy' / self.aliases[0] / 'AUDUSD', name('AUDUSD', '2.92', '0.315'), header('2.920', '0.315'))
        # Member 2 had nothing at the export score: its best profitable pass, which would pass SR/ARF.
        write_unit(self.run / 'below_score' / self.aliases[1] / 'EURUSD', name('EURUSD', '2.95', '0.401'), tagged('2.95', '0.401'))
        write_unit(self.run / 'below_score' / self.aliases[2] / 'USDJPY', name('USDJPY', '1.07', '0.084'), tagged('1.07', '0.084'))
        value = self.progress(['native_completed', 'native_error', 'native_completed'])
        self.assertEqual((value['qualifying'], value['passing_sets'], value['exported_sets'], value['below_threshold_sets'],
                          value['unknown_sets']), (1, 1, 1, 0, 0))
        self.assertEqual((value['below_score_sets'], value['below_score_members']), (2, 2))
        text = headline(dict(kind='batch', status='finished', **value))
        self.assertIn('1 qualifying', text)
        self.assertIn(', 2 best profitable sets kept below score for research only', text)

    def test_none_kept_says_nothing(self):
        value = self.progress(['native_completed', 'native_completed', 'native_completed'])
        self.assertEqual((value['below_score_sets'], value['below_score_members']), (0, 0))
        self.assertNotIn('below score', headline(dict(kind='batch', status='finished', **value)))


class CalibrationTests(unittest.TestCase):
    def test_gate_calibration_never_loads_a_research_unit(self):
        import studio_gate_calibration as gates
        from test_studio_gate_calibration import utf16, write_manifest, write_set
        pnl = dict(back_oos=1.0, in_sample=1.0, forward=1.0, post=1.0)
        with tempfile.TemporaryDirectory() as root:
            write_manifest(root, 'R1', [('A1', 'EURUSD'), ('A2', 'GBPUSD'), ('A3', 'USDJPY')])
            write_set(root, 'R1', 'A1', 'EURUSD', pnl)
            write_set(root, 'R1', 'A2', 'GBPUSD', pnl, area='below_score')                 # its own folder: never read
            tagged_unit = write_set(root, 'R1', 'A3', 'USDJPY', pnl)                        # misplaced in deploy, header-tagged
            set_path = next(tagged_unit.parent.glob('*.set'))
            utf16(set_path, TAG + set_path.read_bytes().decode('utf-16'))
            loaded = gates.load_run(Path(root) / 'R1')
            self.assertEqual([r['member'] for r in loaded['records']], ['A1'])
            self.assertEqual(len(loaded['skipped']), 1)
            self.assertIn('research-only below_score export: not calibration evidence', loaded['skipped'][0]['reason'])


class HeldOutTests(unittest.TestCase):
    def test_research_counts_are_redacted_under_a_lock(self):
        from studio_heldout_guard import METRIC_KEYS
        for key in ('below_score_sets', 'below_score_members', 'research_only', 'below_score', 'status_before_tier'):
            self.assertIn(key, METRIC_KEYS)


if __name__ == '__main__':
    unittest.main()
