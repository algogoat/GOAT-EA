"""Tick-history drift rule for OOS catch-up (studio_catchup_rebase, goatai#1885 6008946539)."""
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import studio_catchup_rebase as rb
import studio_catchup as sc
import studio_catchup_verdict as cv
from studio_catchup import UNCARRIED, CatchupRunner, catch_up_stamp, classify
from studio_evidence import read_export
from studio_installation import read_json
from studio_window_metrics import window as metrics_window
from test_studio_catchup import AFTER_CLOSE, CatchupCase
from test_studio_catchup_verdict import ORIGINAL_END, Scenario
from test_studio_oos_windows import RetestFixture

FIXTURE = json.loads((Path(__file__).resolve().parent / rb.FIXTURE).read_text(encoding='utf-8'))


class FixtureTests(unittest.TestCase):
    """The shared fixture: exact reproduction, a just-pass and a just-fail per criterion, identity, multi-fail."""

    def test_every_case(self):
        names = [case['name'] for case in FIXTURE['cases']]
        self.assertEqual(len(names), len(set(names)))
        for case in FIXTURE['cases']:
            with self.subTest(case=case['name']):
                result = rb.judge_case(case, FIXTURE['defaults'], FIXTURE['deal_level_inputs'])
                self.assertEqual(result['verdict'], case['expected']['verdict'])
                self.assertEqual(result['failed'], case['expected']['failed'])
                if 'cause' in case['expected']:
                    self.assertEqual(result['tickHistoryDrift']['cause'], case['expected']['cause'])
                    self.assertEqual(result['decidedBy'], case['expected']['decidedBy'])
                if 'dealStatus' in case['expected']:
                    self.assertEqual(result['dealCheck']['status'], case['expected']['dealStatus'])
                self.assertIn(result['verdict'], rb.VERDICTS)
                if result['verdict'] == rb.REQUALIFY:
                    # The reason names every failed criterion, in the fixed order.
                    self.assertEqual([reason.split(':')[0] for reason in result['reasons']], case['expected']['failed'])
                if result['verdict'] in (rb.REBASED, rb.REQUALIFY):
                    self.assertEqual(set(result['tickHistoryDrift']),
                                     {'dealCountDelta', 'pfDelta', 'balanceDelta', 'ddDelta', 'maxEquityGap', 'cause'})
                    if result['decidedBy'] == 'deal_level':
                        self.assertIsNone(result['criteria'])    # swap-only: the aggregates do not decide
                    else:
                        self.assertEqual(result['tickHistoryDrift']['cause'], rb.HISTORY_OR_BEHAVIOUR)
                        self.assertEqual([row['criterion'] for row in result['criteria']], list(rb.CRITERIA))
                else:
                    self.assertIsNone(result['criteria'])
                    self.assertIsNone(result['tickHistoryDrift'])

    def test_fixture_covers_a_just_pass_and_a_just_fail_for_each_criterion(self):
        for criterion in rb.CRITERIA:
            with self.subTest(criterion=criterion):
                fails = [c for c in FIXTURE['cases'] if c['expected']['failed'] == [criterion]]
                label = criterion.split('_')[0] if criterion != 'sample_pf_side' else 'SAMPLE'
                passes = [c for c in FIXTURE['cases'] if c['expected']['verdict'] == rb.REBASED and 'just pass' in c['name']
                          and label.lower() in c['name'].lower()]
                self.assertTrue(fails and passes, criterion)
        verdicts = {c['expected']['verdict'] for c in FIXTURE['cases']}
        self.assertEqual(verdicts, set(rb.VERDICTS))
        self.assertTrue(any(len(c['expected']['failed']) > 1 for c in FIXTURE['cases']))

    def test_drift_is_retest_minus_original(self):
        result = rb.decide([], False, dict(deal_count=4210, pf=1.21, final_balance=104312.55, max_dd=2140.1, sample=dict(pl=1)),
                           dict(deal_count=4206, pf=1.2, final_balance=104290.55, max_dd=2151.4, sample=dict(pl=2)),
                           deposit=100000, max_equity_gap=7.5)
        drift = result['tickHistoryDrift']
        self.assertEqual(drift['dealCountDelta'], -4)
        self.assertAlmostEqual(drift['pfDelta'], -0.01)
        self.assertAlmostEqual(drift['balanceDelta'], -22.0)
        self.assertAlmostEqual(drift['ddDelta'], 11.3)
        self.assertEqual(drift['maxEquityGap'], 7.5)

    def test_unknown_deposit_fails_the_balance_criterion(self):
        result = rb.judge_case(dict(deposit=None), FIXTURE['defaults'])
        self.assertEqual((result['verdict'], result['failed']), (rb.REQUALIFY, ['final_balance']))


class EvaluateTests(unittest.TestCase):
    """studio_catchup_verdict.evaluate on two written runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_reproduction_stays_comparable_with_no_drift_stamp(self):
        result = Scenario(self.root).evaluate()
        self.assertEqual((result['comparison'], result['verdict']), ('comparable', 'held_up'))
        self.assertTrue(result['comparability']['comparable'])
        self.assertEqual(result['comparability']['verdict'], 'comparable')
        self.assertIsNone(result['tickHistoryDrift'])
        self.assertIsNone(result['historyBasis'])
        self.assertIsNone(result['rebasedWindows'])

    def test_swap_only_drift_is_rebased_at_the_deal_level_whatever_its_size(self):
        # Same deals; the equity difference steps only on rows that open a server day (where swap is charged):
        # a 300 step would fail the aggregate DD bar, but it is the broker's current swap, so it re-bases.
        result = Scenario(self.root, alter_history=-300).evaluate()
        self.assertEqual((result['comparison'], result['verdict']), ('comparable_rebased', 'held_up'))
        self.assertEqual((result['rebase']['decidedBy'], result['rebase']['dealCheck']['status']), ('deal_level', 'swap_only'))
        self.assertTrue(result['rebase']['dealCheck']['deals']['matched'])
        self.assertEqual(result['tickHistoryDrift']['cause'], 'swap_or_spec')
        self.assertEqual(result['tickHistoryDrift']['maxEquityGap'], 300.0)
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')

    def test_a_changed_deal_falls_through_to_the_aggregate_rule(self):
        scenario = Scenario(self.root, alter_history=-300)
        deals = Path(str(scenario.retest)[:-4] + '.goatseq') / 'deals.csv'
        lines = deals.read_text(encoding='utf-8').splitlines()
        stamp = lines[44].split(',')[1]
        lines[44] = lines[44].replace(',' + stamp + ',', ',%d,' % (int(stamp) + 60000), 1)   # the close one minute later
        deals.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = scenario.evaluate()
        self.assertEqual((result['rebase']['decidedBy'], result['rebase']['dealCheck']['status']), ('aggregate', 'deals_differ'))
        self.assertEqual((result['comparison'], result['rebase']['failed']), ('requalify', ['max_dd']))
        self.assertEqual(result['tickHistoryDrift']['cause'], 'history_or_behaviour')

    def test_small_drift_is_comparable_rebased_and_still_judges_the_new_weeks(self):
        # +3 on a mid-day row (15:00): not a swap step, so the aggregate rule decides, and it holds.
        result = Scenario(self.root, alter_history=True, alter_row=43).evaluate()
        self.assertFalse(result['reproduction']['reproduced'])
        self.assertEqual((result['comparison'], result['verdict']), ('comparable_rebased', 'held_up'))
        self.assertTrue(result['comparability']['comparable'])
        self.assertTrue(result['comparability']['identity'])
        drift = result['tickHistoryDrift']
        self.assertEqual((drift['dealCountDelta'], drift['pfDelta'], drift['balanceDelta'], drift['ddDelta'], drift['maxEquityGap']),
                         (0, 0.0, 0.0, -3.0, 3.0))
        self.assertEqual((drift['cause'], result['rebase']['dealCheck']['status']), ('history_or_behaviour', 'money_off_rollover'))
        basis = result['historyBasis']
        self.assertTrue(basis['originalExportedAt'] and basis['retestAt'])
        self.assertEqual((basis['originalEnd'], basis['retestEnd']), (ORIGINAL_END.isoformat(), '2026-10-09'))
        self.assertIn('Re-based', result['plain'])
        self.assertEqual(result['rebase']['span']['cut'], '%s 23:59' % ORIGINAL_END.isoformat())

    def test_large_drift_requalifies_and_names_the_criterion(self):
        # The 15:00 dip row 300 lower in the re-test (not a rollover row): DD 420 vs the original 120 (limit 12).
        result = Scenario(self.root, alter_history=-300, alter_row=43).evaluate()
        self.assertEqual((result['comparison'], result['verdict'], result['confidence']), ('requalify', 'requalify', 'none'))
        self.assertFalse(result['comparability']['comparable'])
        self.assertEqual(result['rebase']['failed'], ['max_dd'])
        self.assertTrue(result['reasons'][0].startswith('max_dd: max drawdown 120'))
        self.assertIn('new candidate', result['plain'])
        self.assertIn('max_dd', result['plain'])
        self.assertEqual(result['tickHistoryDrift']['ddDelta'], 300.0)
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')

    def test_identity_mismatch_stays_not_comparable_even_without_reproduction(self):
        result = Scenario(self.root, alter_history=True, retest=dict(server='Other-Demo')).evaluate()
        self.assertEqual((result['comparison'], result['verdict']), ('not_comparable', 'not_comparable'))
        self.assertIsNone(result['tickHistoryDrift'])
        self.assertIsNone(result['rebasedWindows'])

    def test_rebased_windows_are_recomputed_on_the_retest_with_no_splice(self):
        scenario = Scenario(self.root, alter_history=True)
        # The re-test's history differs inside SAMPLE: one close earned 4.1 instead of 5.1.
        deals = Path(str(scenario.retest)[:-4] + '.goatseq') / 'deals.csv'
        lines = deals.read_text(encoding='utf-8').splitlines()
        lines[44] = lines[44].replace(',5.1,', ',4.1,')   # Mon 2026-01-19 11:01, the first SAMPLE day
        deals.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = scenario.evaluate()
        self.assertEqual(result['comparison'], 'comparable_rebased')
        windows = result['rebasedWindows']
        self.assertEqual((windows['basis'], windows['spliced'], windows['windowsSource'], windows['testedThrough']),
                         ('retest', False, 'run_manifest', '2026-10-09'))
        retest = read_export(scenario.retest)
        rows = [(stamp, float(equity)) for stamp, _, equity in cv.equity_rows(retest['csv_path'])]
        bounds = dict(BOOS=(date(2026, 1, 5), date(2026, 1, 18)), SAMPLE=(date(2026, 1, 19), date(2026, 7, 16)),
                      FWD=(date(2026, 7, 17), date(2026, 8, 27)), FOOS=(date(2026, 8, 28), date(2026, 10, 9)))
        for name, (first, last) in bounds.items():
            with self.subTest(window=name):
                expected = metrics_window(rows, first, last, deals=str(deals))
                self.assertEqual({k: windows[name][k] for k in expected}, expected)
                self.assertEqual(windows[name]['basis'], 'retest')
        original = read_export(scenario.original)
        old_deals = str(Path(original['csv_path'][:-4] + '.goatseq') / 'deals.csv')
        old_rows = [(stamp, float(equity)) for stamp, _, equity in cv.equity_rows(original['csv_path'])]
        old_sample = metrics_window(old_rows, *bounds['SAMPLE'], deals=old_deals)
        self.assertAlmostEqual(windows['SAMPLE']['profit'], old_sample['profit'] - 1.0)
        # FOOS runs from the optimization end through the re-test end on the re-test alone: its trades are the
        # re-test's own, not the original export's FOOS header (38) plus the new weeks.
        self.assertEqual(windows['FOOS']['from'], '2026-08-28')
        self.assertEqual(windows['FOOS']['trades'], metrics_window(rows, date(2026, 8, 28), date(2026, 10, 9), deals=str(deals))['trades'])
        self.assertEqual(windows['FOOS']['tradeSource'], 'capture_deals')

    def test_requalify_also_carries_the_retest_windows(self):
        result = Scenario(self.root, retest_complete=False, alter_history=True).evaluate()
        self.assertEqual(result['comparison'], 'requalify')
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')
        self.assertIsNone(result['rebasedWindows']['FOOS']['trades'], 'no capture: trades unknown, never spliced from the header')


class StampTests(unittest.TestCase):
    SPEC = dict(original=dict(evidence_end='2026-09-24', set_sha256='a' * 64, values_sha256='b' * 64), new_window=dict(first_day='2026-09-25'),
                tester=dict(ToDate='2026.10.10'))
    MANIFEST = dict(evidence_end=dict(iso='2026-10-09', mode='explicit'), verdict_rules=cv.validate_rules())
    FOOS = dict(start='2026-08-29', end='2026-09-24', days=19, trades=38, pl=190.0)

    def stamp(self, comparison, **extra):
        verdict = dict(verdict='held_up', confidence='low', comparison=comparison, new_weeks=dict(last_day='2026-10-09'),
                       historyBasis=dict(originalExportedAt='2026-09-25T10:00:00+00:00', retestAt='2026-10-10T10:00:00+00:00'),
                       tickHistoryDrift=dict(dealCountDelta=-4, pfDelta=-0.01, balanceDelta=-22.0, ddDelta=11.3, maxEquityGap=7.5),
                       rebasedWindows=dict(basis='retest', FOOS=dict(trades=60)), **extra)
        return catch_up_stamp(self.SPEC, self.MANIFEST, verdict, '2026-10-10T10:00:00+00:00', self.FOOS)

    def test_rebased_import_takes_every_window_from_the_retest(self):
        stamp = self.stamp('comparable_rebased')
        self.assertIsNone(stamp['original_foos'], 'never restore the old FOOS next to new weeks')
        self.assertEqual((stamp['windowsBasis'], stamp['windows']['FOOS']['trades']), ('retest', 60))
        self.assertEqual(stamp['tickHistoryDrift']['balanceDelta'], -22.0)
        self.assertEqual(stamp['historyBasis']['retestAt'], '2026-10-10T10:00:00+00:00')
        self.assertEqual((stamp['comparison'], stamp['carriesStatus'], stamp['candidate']), ('comparable_rebased', True, None))
        self.assertEqual(stamp['evidenceEnd'], '2026-10-09')

    def test_requalify_is_a_new_candidate_with_no_carried_status(self):
        stamp = self.stamp('requalify')
        self.assertEqual((stamp['candidate'], stamp['carriesStatus'], stamp['windowsBasis']), ('new', False, 'retest'))
        self.assertIsNone(stamp['original_foos'])

    def test_exact_reproduction_keeps_the_original_foos(self):
        stamp = self.stamp('comparable')
        self.assertEqual((stamp['original_foos'], stamp['windowsBasis'], stamp['windows']), (self.FOOS, 'original', None))
        self.assertTrue(stamp['carriesStatus'])

    def test_a_requalify_version_never_catches_the_original_up(self):
        self.assertIn('requalify', UNCARRIED)
        export = dict(set_path='x.set', values_sha256='v', symbol='EURUSD', period='M1', evidence_start='2026-01-05',
                      evidence_end='2026-09-24', threshold=dict(passing=True, min_arf=0.2, min_sr=2.5), problems=[])
        version = dict(values_sha256='v', symbol='EURUSD', period='M1', evidence_start='2026-01-05', evidence_end='2026-10-09',
                       version_path='p', verdict=dict(verdict='requalify', reasons=['max_dd: ...']))
        row = classify(export, '2026-10-09', known_versions=[version])
        self.assertEqual(row['status'], 'behind')
        self.assertEqual(row['previous_attempt']['verdict'], 'requalify')
        held = dict(version, verdict=dict(verdict='held_up'))
        self.assertEqual(classify(export, '2026-10-09', known_versions=[held])['status'], 'caught_up')


class CollectTests(CatchupCase):
    """A full catch-up cycle whose re-test drifted: the stamps reach the verdict, the summary and evidence-version.json."""

    def drifted(self, shift, row=43):
        # Row 43 is the 15:00 dip row of 2026-03-04 (mid-day: not a swap step); row 50 opens its server day.
        rows = [list(r) for r in self.history]
        rows[row][2] += Decimal(str(shift))
        self.histories['EURUSD'] = [tuple(row) for row in rows]

    def cycle(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.auto = True
        self.assertEqual(self.runner.start('cu1', 30)['status'], 'completed')
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        version = read_json(Path(member['evidence_dir']) / 'evidence-version.json')
        return version, self.runner.report('cu1')['members'][0]['summary']

    def test_rebased_stamps_on_version_summary_and_import(self):
        self.drifted(3)
        version, summary = self.cycle()
        for record in (version, summary, version['catch_up']):
            self.assertEqual(record['comparison'], 'comparable_rebased')
            self.assertEqual(record['tickHistoryDrift']['maxEquityGap'], 3.0)
            self.assertEqual(record['tickHistoryDrift']['dealCountDelta'], 0)
            self.assertEqual(record['tickHistoryDrift']['cause'], 'history_or_behaviour')
            self.assertEqual(set(record['historyBasis']) >= {'originalExportedAt', 'retestAt'}, True)
        self.assertEqual((version['verdict']['verdict'], summary['comparable'], summary['reproduced']), ('held_up', True, False))
        stamp = version['catch_up']
        self.assertIsNone(stamp['original_foos'])
        self.assertEqual((stamp['windowsBasis'], stamp['windows']['FOOS']['from'], stamp['windows']['FOOS']['to']),
                         ('retest', '2026-08-28', '2026-10-02'))
        self.assertEqual(version['rebasedWindows'], stamp['windows'])
        self.assertEqual(version['rebase']['verdict'], 'comparable_rebased')
        self.assertEqual(version['oos_rule']['status'], 'not_applicable')   # explicit (non-formula) dates in this harness
        # A re-based version carries the export to the shared end like an exact one.
        scan = sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)
        self.assertEqual(scan['summary']['counts']['caught_up'], 1)

    def test_requalify_stamps_and_carries_nothing(self):
        self.drifted(-300)
        version, summary = self.cycle()
        self.assertEqual((summary['verdict'], summary['comparison'], summary['comparable']), ('requalify', 'requalify', False))
        self.assertEqual(version['rebase']['failed'], ['max_dd'])
        self.assertEqual((version['catch_up']['candidate'], version['catch_up']['carriesStatus']), ('new', False))
        self.assertEqual(version['tickHistoryDrift']['ddDelta'], 300.0)
        scan = sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)
        row = scan['exports'][0]
        self.assertEqual((row['status'], row['previous_attempt']['verdict']), ('behind', 'requalify'))

    def test_swap_only_cycle_rebases_with_its_cause(self):
        self.drifted(-300, row=50)
        version, summary = self.cycle()
        for record in (version, summary, version['catch_up']):
            self.assertEqual(record['comparison'], 'comparable_rebased')
            self.assertEqual(record['tickHistoryDrift']['cause'], 'swap_or_spec')
        self.assertEqual(version['rebase']['decidedBy'], 'deal_level')
        self.assertEqual(version['catch_up']['windowsBasis'], 'retest')

    def test_exact_reproduction_stamps_comparable(self):
        version, summary = self.cycle()
        self.assertEqual((version['comparison'], summary['comparison'], version['catch_up']['comparison']), ('comparable',) * 3)
        self.assertIsNone(version['tickHistoryDrift'])
        self.assertIsNone(summary['historyBasis'])
        self.assertEqual(version['catch_up']['windowsBasis'], 'original')


class RedactionTests(unittest.TestCase):
    def test_drift_and_rebased_windows_are_redacted_inside_a_lock(self):
        from studio_heldout_guard import METRIC_KEYS
        self.assertLessEqual({'rebase', 'tickHistoryDrift', 'rebasedWindows'}, METRIC_KEYS)


class MeasureTests(unittest.TestCase):
    def test_the_forced_final_minute_and_closes_are_not_counted(self):
        folder = Path(tempfile.mkdtemp())
        header = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,profit,commission,fee,swap,deal_magic,join_basis'
        stamp = lambda hour, minute=0: int(datetime(2026, 9, 24, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)
        deals = [(stamp(9), 1, '0', '0'), (stamp(10), 1, '1', '20'), (stamp(11), 2, '0', '0'), (stamp(23, 59), 2, '1', '-50')]
        (folder / 'deals.csv').write_text('\n'.join([header] + ['%d,%d,1,%d,%d,%d,1,1,%s,0.1,1,%s,0,0,0,1,k' % (i, s, i, i, p, e, r)
                                                                for i, (s, p, e, r) in enumerate(deals, 1)]) + '\n', encoding='utf-8')
        rows = [(datetime(2026, 9, 24, 9), Decimal(1000), Decimal(1000)), (datetime(2026, 9, 24, 12), Decimal(1020), Decimal(990)),
                (datetime(2026, 9, 24, 23, 59), Decimal(970), Decimal(970))]
        measured = rb.measure(rows, str(folder / 'deals.csv'), cut=rows[-1][0], sample=None)
        # The forced close at 23:59 is outside the span: balance 1020, DD 10 (not 50), PF from the 20 win only.
        self.assertEqual((measured['final_balance'], measured['max_dd'], measured['deal_count']), (Decimal(1020), Decimal(10), 2))
        self.assertEqual((measured['pf'], measured['pf_note']), (None, rb.NO_LOSS))
        gap = rb.equity_gap(rows, [rows[0], (rows[1][0], rows[1][1], Decimal(1004)), rows[2]], rows[-1][0])
        self.assertEqual(gap, 14.0)


class OosRuleTests(RetestFixture, unittest.TestCase):
    """The OOS formula gates run on the re-based evidence, and judge a requalified set as a new candidate."""

    def test_gates_run_on_the_retest_for_rebased_and_requalify(self):
        original, retest = self.build()
        spec = dict(original=dict(tester=self.record['tester']))
        exact = CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up', comparison='comparable'))
        self.assertNotIn('evidenceBasis', exact)
        for comparison, verdict in (('comparable_rebased', 'held_up'), ('requalify', 'requalify')):
            with self.subTest(comparison=comparison):
                result = CatchupRunner._oos_rule(original, retest, spec, dict(verdict=verdict, comparison=comparison))
                self.assertEqual(result['status'], exact['status'])
                self.assertEqual(result['status'], 'pass')
                self.assertEqual((result['evidenceBasis'], result['comparison']), ('retest', comparison))
                self.assertEqual(result['candidate'], 'new' if comparison == 'requalify' else None)
                self.assertEqual(result['windows']['foos']['trades'], 30)


if __name__ == '__main__':
    unittest.main()
