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
from studio_research_status import _no_edge_outcome, batch_progress, headline, item_outcomes, no_edge_summary
from test_studio_export_qualification import NOW, SETTINGS, header, name, write_unit
from test_studio_research_outcome import QDETAILS, TIMING, local, q_row, write_stats
self_root = tempfile.gettempdir()

TAG = '; EXPORT: below_score research only, nothing scored at or above the export score\r\n'
FIXTURES = Path(__file__).parent / 'fixtures' / 'oosc'
G6_XAUUSD_REL = 'g6/deploy/R04049bbe9cc1b1fe6c3f/XAUUSD/GOAT V1.49 XAUUSD,M1_Trds=587_Prf=984_DD=3362_PF=1.05_SR=0.49_ARF=0.032.set'
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

    def test_catch_up_needs_the_separate_research_opt_in(self):
        export = ev.read_export(self.set_path)
        row = classify(export, '2026-10-01')
        self.assertEqual((row['status'], row['export_tier']), ('ineligible', 'below_score'))
        self.assertTrue(any('include_research_only' in reason for reason in row['reasons']))
        # include_below_threshold never admits a research-only unit (Claude-Mac 6025359910 item 3).
        mixed = classify(export, '2026-10-01', include_below_threshold=True)
        self.assertEqual(mixed['status'], 'ineligible')
        opted = classify(export, '2026-10-01', include_research_only=True)
        self.assertNotEqual(opted['status'], 'ineligible')
        self.assertFalse(opted['threshold_passing'])
        # ... and a research opt-in never admits an ordinary below-threshold set either.
        standard = ev.read_export(self.root / G6_XAUUSD_REL)
        self.assertEqual(classify(standard, '2026-10-01', include_research_only=True)['status'], 'ineligible')
        self.assertNotEqual(classify(standard, '2026-10-01', include_below_threshold=True)['status'], 'ineligible')

    def test_an_unknown_tier_is_never_re_tested(self):
        export = dict(ev.read_export(self.set_path), export_tier='unrecognised:second_slot')
        row = classify(export, '2026-10-01', include_research_only=True)
        self.assertEqual(row['status'], 'ineligible')
        self.assertTrue(any('Unknown export tier' in reason for reason in row['reasons']))

    def test_the_re_test_keeps_its_tier(self):
        from studio_catchup import _export_desc
        window = dict(source='run_manifest', FromDate='2025.10.17', ToDate='2026.08.28', ForwardDate='2026.07.17')
        self.assertEqual(_export_desc('R1', window, 'below_score'),
                         'R1@{mode=EXPORT,dt_BOOS_end=2025.10.17,dt_FOOS_start=2026.08.29,dt_FWD_start=2026.07.17,dt_FWD_end=2026.08.28,tier=below_score}')
        self.assertEqual(_export_desc('R1', window), 'R1@{mode=EXPORT,dt_BOOS_end=2025.10.17,dt_FOOS_start=2026.08.29,dt_FWD_start=2026.07.17,dt_FWD_end=2026.08.28}')
        self.assertEqual(_export_desc('R1', dict(source='unknown'), 'below_score'), 'R1@{mode=EXPORT,tier=below_score}')
        import inspect
        import studio_catchup
        member = inspect.getsource(studio_catchup.CatchupRunner._member)
        self.assertIn("EA_Desc=_export_desc(alias, window, tier)", member)
        self.assertIn("export_tier=tier, research_only=bool(export.get('research_only'))", member)
        collect = inspect.getsource(studio_catchup)
        self.assertIn("export_tier=spec.get('export_tier', 'standard'), research_only=bool(spec.get('research_only')),", collect)
        self.assertIn("retest_export_tier=retest.get('export_tier', 'standard'),", collect)
        self.assertIn("include_research_only=plan.get('include_research_only', False), native_launch_qualified=False)", collect)

    def test_collect_refuses_a_re_test_that_reads_back_another_tier(self):
        # Claude-Mac 6026738987: a research-only original whose re-test reads back standard is refused by _collect,
        # before anything is moved or judged; so is the reverse. A matching tier passes the check.
        from studio_catchup import CatchupRunner
        runner = object.__new__(CatchupRunner)
        runner._outputs = lambda spec: ['one unit']
        standard_path = self.root / G6_XAUUSD_REL
        self.assertEqual(ev.read_export(standard_path)['export_tier'], 'standard')
        research = dict(export_tier='below_score', research_only=True)
        with self.assertRaisesRegex(ValueError, r"^Re-test export tier standard differs from the original's below_score \(research only\): refused"):
            runner._collect(standard_path, research, {})
        self.assertTrue(standard_path.is_file(), 'nothing moved')
        with self.assertRaisesRegex(ValueError, r"^Re-test export tier below_score \(research only\) differs from the original's standard: refused"):
            runner._collect(self.set_path, dict(export_tier='standard', research_only=False), {})
        with self.assertRaisesRegex(ValueError, r'^Re-test export tier below_score \(research only\) differs'):
            runner._collect(self.set_path, {}, {})   # a spec from before BS42 is standard
        self.assertTrue(self.set_path.is_file(), 'nothing moved')
        # The same tier gets past the check (the next check needs the frozen tester, absent here).
        with self.assertRaises(KeyError):
            runner._collect(self.set_path, research, {})
        with self.assertRaises(KeyError):
            runner._collect(standard_path, {}, {})


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

    def test_a_reason_rides_with_its_result(self):
        multi = _no_edge_outcome(QDETAILS + ';below_score=none;below_score_reason=multiple_pairs;below_score_pairs=2;below_score_rank=fwd_profit_dd',
                                 'no_qualifying_rows')['below_score']
        self.assertEqual((multi['result'], multi['reason']), ('none', 'multiple_pairs'))
        deposit = _no_edge_outcome(QDETAILS + ';below_score=failed;below_score_reason=tester_deposit_unknown;below_score_rank=fwd_profit_dd',
                                   'no_qualifying_rows')['below_score']
        self.assertEqual((deposit['result'], deposit['reason']), ('failed', 'tester_deposit_unknown'))
        for details in (';below_score=exported;below_score_reason=multiple_pairs', ';below_score=none;below_score_reason=guess',
                        ';below_score=failed;below_score_reason=guess'):
            self.assertEqual(_no_edge_outcome(QDETAILS + BELOW.replace(';below_score=exported', '') + details, 'no_qualifying_rows')
                             ['below_score']['result'], 'unreadable', details)

    def test_an_unreadable_report_is_never_a_kept_export(self):
        for label, details in (('unknown result', BELOW.replace('=exported', '=kept')),
                               ('exported without its figures', ';below_score=exported'),
                               ('a figure that is not a number', BELOW.replace('=1.8421', '=n/a'))):
            outcome = _no_edge_outcome(QDETAILS + details, 'no_qualifying_rows')
            self.assertEqual(outcome['outcome'], 'no_qualifying_rows', label)
            self.assertEqual(outcome['below_score']['result'], 'unreadable', label)


FDETAILS = ('outcome=no_fwd_eligible_rows;passes=158;profitable=7;traded=158;malformed=0;complete=1;forward_rows=158;'
            'best_profit=660.00;best_score=0.5600;min_trades=50;window_start=2024.01.08;window_end=2025.01.06;forward_end=2025.03.15;'
            'back_rows=7;forward_matched=7;best_combined_score=72.0;score_threshold=60.0;score_qualifying_rows=2')
NONE = (';below_score=none;no_fwd_eligible_pass=1;rows=7;fwd_eligible=0;not_in_forward=0;sample_unprofitable_or_thin=1;'
        'fwd_unprofitable=4;fwd_trades_under_floor=2;fwd_dd_unmeasured=0;below_score_rank=fwd_profit_dd;below_score_min_fwd_trades=30')


class NoFwdEligibleTests(unittest.TestCase):
    """Switch on (GOAT_EXPORT_RANK_FWD_PROFIT_DD): 60+ passes, none FWD-eligible. Never silent, never qualifying."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def row(self, details):
        return q_row('A0', 'USDCAD', details=details).replace('\tNoQualifyingRows\t', '\tNoFwdEligibleRows\t')

    def test_fall_through_to_below_score_is_a_research_result(self):
        write_stats(self.run, [self.row(FDETAILS + BELOW)])
        found = item_outcomes(self.run, [('A0', 'USDCAD')], TIMING)[0]
        self.assertEqual((found['outcome'], found['score_qualifying_rows'], found['below_score']['result']),
                         ('no_fwd_eligible_rows', 2, 'exported'))
        text = no_edge_summary('USDCAD', 'M1', found)
        self.assertIn('2 of 158 settings scored 60+ but none was profitable in the forward period', text)
        self.assertIn('kept for research only (below score)', text)
        # Claude-Mac 6025359910 nit a: the user sentence reads an em dash, never the UTF-8-as-cp1252 mojibake.
        self.assertRegex(text, r'^USDCAD M1: tested, nothing FWD-eligible in \d{4}\.\d\d\.\d\d to \d{4}\.\d\d\.\d\d — 2 of 158 settings')
        self.assertNotIn('â', text)
        line = headline(dict(kind='batch', status='finished', members_total=1, members_done=0, members_no_edge=1, no_edge=[found],
                             no_edge_counts={'no_fwd_eligible_rows': 1}, no_edge_window=dict(start='2024.01.08', end='2025.01.06')))
        self.assertIn('1 none FWD-eligible at the export score', line)

    def test_nothing_eligible_carries_the_counts(self):
        found = _no_edge_outcome(FDETAILS + NONE, 'no_fwd_eligible_rows')
        self.assertEqual(found['below_score']['result'], 'none')
        self.assertEqual(found['below_score']['no_fwd_eligible_pass'],
                         dict(rows=7, fwd_eligible=0, not_in_forward=0, sample_unprofitable_or_thin=1, fwd_unprofitable=4,
                              fwd_trades_under_floor=2, fwd_dd_unmeasured=0))
        self.assertIn('nothing was exported (no FWD-eligible pass)', no_edge_summary('USDCAD', 'M1', found))
        # Switch off: the below_score path's own NO_FWD_ELIGIBLE_PASS facts ride on the NoQualifyingRows row.
        off = _no_edge_outcome(QDETAILS + NONE, 'no_qualifying_rows')
        self.assertEqual(off['below_score']['no_fwd_eligible_pass']['fwd_unprofitable'], 4)

    def test_a_row_without_its_proof_stays_an_error(self):
        for label, details in (('no below_score report', FDETAILS),
                               ('none without its counts', FDETAILS + ';below_score=none;below_score_rank=fwd_profit_dd'),
                               ('best score under the threshold', FDETAILS.replace('best_combined_score=72.0', 'best_combined_score=48.0') + BELOW),
                               ('no score-qualifying pass', FDETAILS.replace('score_qualifying_rows=2', 'score_qualifying_rows=0') + BELOW),
                               ('a forward merge that lost a pass', FDETAILS.replace('forward_matched=7', 'forward_matched=6') + BELOW),
                               ('a partial report', FDETAILS.replace('complete=1', 'complete=0') + BELOW)):
            self.assertIsNone(_no_edge_outcome(details, 'no_fwd_eligible_rows'), label)
        self.assertIsNone(_no_edge_outcome(FDETAILS + BELOW, 'no_qualifying_rows'), 'the status decides the outcome')
        counts = _no_edge_outcome(QDETAILS + NONE.replace('fwd_unprofitable=4', 'fwd_unprofitable=x'), 'no_qualifying_rows')
        self.assertEqual(counts['below_score']['result'], 'unreadable')

    def test_several_pairs_are_named_not_counted(self):
        multi = FDETAILS + ';below_score=none;below_score_reason=multiple_pairs;below_score_pairs=2;below_score_rank=fwd_profit_dd'
        found = _no_edge_outcome(multi, 'no_fwd_eligible_rows')
        self.assertEqual(found['below_score'], dict(result='none', rank='fwd_profit_dd', reason='multiple_pairs'))
        self.assertNotIn('no_fwd_eligible_pass', found['below_score'], 'never NO_FWD_ELIGIBLE_PASS from one pair of several')


class DiskEstimateTests(unittest.TestCase):
    """The disk a batch's exports may write, shown with prepare-batch (Claude-Mac 6023896492)."""

    def test_measured_units_and_the_below_score_line(self):
        from studio_export_disk import MIB, export_disk_estimate
        value = export_disk_estimate(100, dict(SetsToExport=2, IncludeSequenceData=True))
        self.assertEqual((value['normal_exports']['units_max'], value['unit_median_bytes'], value['unit_p90_bytes']), (200, 97 * MIB, 163 * MIB))
        self.assertEqual(round(value['below_score']['low_bytes'] / 1e9, 1), 0.4)
        self.assertEqual(round(value['below_score']['high_bytes'] / 1e9, 1), 1.1)
        self.assertIn('about 0.4-1.1 GB per 100 members', value['plain'])
        self.assertIn('up to 200 kept exports (100 members x 2) at about 102 MB each', value['plain'])
        # Slot 2 counted in the high estimate (nit b): two units per below_score member at the p90 size.
        self.assertEqual(value['below_score']['high_p90_bytes'], int(2 * 11.0 * 163 * MIB))
        self.assertIn('up to 3.8 GB if each also keeps a second, different pass', value['plain'])
        self.assertEqual(value['total_high_bytes'], value['normal_exports']['high_bytes'] + value['below_score']['high_p90_bytes'])
        self.assertEqual((value['normal_exports']['typical_bytes'], value['normal_exports']['high_bytes']), (200 * 97 * MIB, 200 * 163 * MIB))
        self.assertIn('about 20.3 GB typical and up to 34.2 GB', value['plain'])
        small = export_disk_estimate(10, dict(SetsToExport=1, IncludeSequenceData='0'))
        self.assertEqual((small['sets_to_export'], small['sequence_data'], small['unit_median_bytes']), (2, False, MIB))
        self.assertIn('under 1 MB', small['plain'])

    def test_free_space_is_compared_with_the_high_estimate(self):
        from studio_export_disk import GIB, export_disk_estimate
        tight = export_disk_estimate(100, dict(SetsToExport=2), free_bytes=20 * GIB)
        self.assertFalse(tight['fits'])
        self.assertIn('not enough to keep 5 GB free', tight['plain'])
        roomy = export_disk_estimate(100, dict(SetsToExport=2), free_bytes=200 * GIB)
        self.assertTrue(roomy['fits'])
        self.assertIn('214.7 GB free on the Common Files disk.', roomy['plain'])
        # Unreadable free space is never a disk that fits (nit c).
        unread = export_disk_estimate(100, dict(SetsToExport=2))
        self.assertEqual((unread['fits'], unread['free_bytes']), (False, None))
        self.assertIn('free space could not be read: check it before starting', unread['plain'])
        from studio_export_disk import estimate_for_root
        self.assertIs(estimate_for_root(1, {}, None)['fits'], False)
        self.assertIs(estimate_for_root(1, {}, r'Z:\no\such\disk\here')['fits'], False)

    def test_prepare_batch_returns_it(self):
        import inspect
        import studio_batch
        source = inspect.getsource(studio_batch.prepare_batch)
        self.assertEqual(source.count('disk_estimate=_disk_estimate(controller, checked)'), 2, 'new and reused preparations')
        estimate = studio_batch._disk_estimate(type('C', (), {'binding': lambda self: dict(common_files_root=self_root)})(),
                                               [dict(export=dict(SetsToExport=3))])
        self.assertEqual((estimate['members'], estimate['sets_to_export']), (1, 3))
        self.assertIn('free_bytes', estimate)
        broken = studio_batch._disk_estimate(type('C', (), {'binding': lambda self: {}['missing']})(), [])
        self.assertEqual((broken['members'], broken['free_bytes'], broken['fits']), (0, None, False))


class MixedDeployTests(unittest.TestCase):
    """Switch ON (nit d): a slot 1 below the thresholds can sit in deploy beside a passing slot 2, which
    SortAndTrimExports never produced. Removing slot 1 by its full-span metrics would let FOOS pick again, so it
    stays; every deploy reader handles the member: one set passed, one is below threshold, the EA log matches."""

    def test_scan_run_and_status_read_a_mixed_member(self):
        from test_studio_export_qualification import cycle, write_log
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / 'common' / 'GOAT' / 'Rabcdef012345'
            run.mkdir(parents=True)
            (run / 'export_settings.GOAT').write_bytes(SETTINGS.encode('utf-16'))
            folder = run / 'deploy' / 'R1' / 'AUDUSD'
            write_unit(folder, name('AUDUSD', '1.07', '0.084'), header('1.070', '0.084'))   # slot 1, below threshold
            write_unit(folder, name('AUDUSD', '2.92', '0.315'), header('2.920', '0.315'))   # slot 2, passing
            # The switched EA's own lines: 2 attempts, 2 stored, 1 passed; GoatSlotTrimLog's Passing=1 Kept=2.
            write_log(run, cycle(1, (2, 1, 2)))
            result = eq.scan_run(run)
            self.assertEqual(result['log_crosscheck']['status'], 'match')
            counts = result['counts']
            self.assertEqual((counts['passed_sets'], counts['below_threshold_sets'], counts['passed_members'],
                              counts['below_threshold_members']), (1, 1, 1, 0))
            stamps = {entry['set_name'].split('_SR=')[1][:4]: entry['qualification']['status'] for entry in result['stamps']}
            self.assertEqual(stamps, {'1.07': 'below_threshold', '2.92': 'passed'}, 'each set keeps its own stamp')

class FinishRecordTests(unittest.TestCase):
    """Claude-Mac 6026738987 item 3: the finish reply says how many research-only sets each no-edge member kept, and
    AGENT-START-HERE step 20 records it as metrics.belowScoreSets, the field the desktop fit map reads."""

    def test_finish_reports_the_below_score_sets_each_member_kept(self):
        import studio_finish
        import studio_research_status as rs
        one = _no_edge_outcome(QDETAILS + BELOW, 'no_qualifying_rows')
        self.assertEqual(one['below_score']['kept'], 1)
        found = {0: one, 1: dict(one, below_score=dict(one['below_score'], kept=2)),
                 2: _no_edge_outcome(QDETAILS + ';below_score=none;below_score_rank=fwd_profit_dd;below_score_min_fwd_trades=30', 'no_qualifying_rows'),
                 3: _no_edge_outcome(QDETAILS + BELOW.replace('=exported', '=lost'), 'no_qualifying_rows'),
                 4: _no_edge_outcome(QDETAILS, 'no_qualifying_rows')}   # a pre-B42 row
        native = dict(native_run='run', members=[dict(run_alias='A%d' % i, symbol='USDCAD', status='native_error', tester=dict(Period='M1'))
                                                 for i in range(6)])
        with patch.object(rs, 'no_edge_members', lambda *args: found), patch.object(rs, 'timeline', lambda *args: None):
            outcomes, error = studio_finish._research_outcomes(native)
        self.assertIsNone(error)
        self.assertEqual([(o['index'], o['below_score_sets']) for o in outcomes], [(0, 1), (1, 2), (2, 0), (3, 0), (4, 0)])
        self.assertEqual(rs.below_score_sets(dict(one, below_score=dict(one['below_score'], result='unreadable'))), 0)
        self.assertEqual(rs.below_score_sets(dict(one, below_score=dict(one['below_score'], kept=3))), 0, 'an impossible count is none')
        self.assertEqual(rs.below_score_sets(None), 0)
        # The recipe records it, 0 when the member has no research outcome (or the controller predates B42).
        guide = (Path(__file__).parent / 'AGENT-START-HERE.md').read_text(encoding='utf-8')
        self.assertIn('$bsSets[[int]$o.index] = [int]$o.below_score_sets', guide)
        self.assertIn('belowScoreSets=[int]$bsSets[[int]$i]}', guide)


class WindowMetricsParityTests(unittest.TestCase):
    """Claude-Mac 6026738987: the EA judges slot 2 with GoatEquityWindowMetrics, which must measure a window exactly
    as window_metrics does. Both sides are pinned to one fixture of real export CSVs: this test pins the controller,
    scripts/test_below_score_export.cjs pins the EA function to the same numbers."""

    def test_window_metrics_reproduces_the_parity_fixture(self):
        import json
        from datetime import date
        import studio_gate_calibration as gc
        folder = Path(__file__).resolve().parent.parent / 'scripts' / 'fixtures' / 'below-score'
        fixture = json.loads((folder / 'window-metrics-parity.json').read_text(encoding='utf-8'))
        self.assertEqual(len(fixture['cases']), 6)
        for case in fixture['cases']:
            rows = gc.equity(gc._decode((folder / case['csv']).read_bytes()))
            got = gc.window_metrics([], rows, date.fromisoformat(case['first']), date.fromisoformat(case['end']), fixture['initial'])
            self.assertEqual({k: got[k] for k in ('net', 'dd', 'sr', 'arf', 'weekdays', 'recovery')},
                             {k: case[k] for k in ('net', 'dd', 'sr', 'arf', 'weekdays', 'recovery')}, case['csv'] + ' ' + case['window'])
        sample = {case['csv']: case for case in fixture['cases'] if case['window'] == 'sample'}
        # Mac's example: on EQUITY Trds184's SAMPLE has DD 319 and SR 1.77, under the 2.5 bar (on BALANCE it read 233 / 2.62).
        self.assertEqual((sample['real-AUDUSD-Trds184.csv']['dd'], sample['real-AUDUSD-Trds184.csv']['sr']), (319.01, 1.7705))


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
