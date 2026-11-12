"""OOS window formula (goat-oos-windows-v1) and its BOOS/FOOS rule (goat-oos-window-rule-v1)."""
import csv
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

import studio_evidence_end as ee
import studio_oos_windows as w
from studio_heldout import member_span, overlaps

SATURDAY = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)      # broker Saturday: AUTO export Friday = 2026-10-02
FRIDAYS = ('2026-10-02',   # the worked example
           '2024-03-01',   # first Friday after a leap day (2024-02-29)
           '2028-03-03',   # leap year 2028
           '2024-02-23',   # windows ending just before a leap day
           '2025-01-31',   # month end
           '2026-07-31',   # month end
           '2026-12-25',   # a holiday Friday is still the export Friday
           '2027-01-01')   # year boundary
MONTHS = (3, 6, 12, 24)


def d(text):
    return date.fromisoformat(text)


class DateMathTests(unittest.TestCase):
    def test_months_are_thirteen_thirds_of_a_week(self):
        expected = {1: 4, 2: 9, 3: 13, 6: 26, 9: 39, 12: 52, 18: 78, 24: 104, 120: 520}
        for months, weeks in expected.items():
            self.assertEqual(w.optimization_weeks(months=months), weeks, months)
        self.assertEqual(w.optimization_weeks(weeks=30), 30)
        for bad in (dict(), dict(months=12, weeks=52), dict(months=0), dict(months=121), dict(months=12.0),
                    dict(months=True), dict(weeks=3), dict(weeks=521), dict(weeks='52')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.optimization_weeks(**bad)

    def test_worked_example_twelve_months_export_friday_2026_10_02(self):
        r = w.compute(52, '2026-10-02')
        self.assertEqual((r['weeks'], r['oosFormula']), (dict(boos=18, sample=34, fwd=18, foos=13), 'boos-1/3'))
        self.assertEqual({k: (r[k]['first_day'], r[k]['last_day']) for k in ('boos', 'sample', 'fwd', 'foos')}, dict(
            boos=('2025-03-01', '2025-07-04'), sample=('2025-07-05', '2026-02-27'),
            fwd=('2026-02-28', '2026-07-03'), foos=('2026-07-04', '2026-10-02')))
        self.assertEqual(r['optimization_end'], '2026-07-03')
        self.assertEqual(r['tester'], dict(FromDate='2025.07.05', ToDate='2026.07.04', ForwardMode=4, ForwardDate='2026.02.28'))
        self.assertEqual(r['export'], dict(BackOOSDate='2025.03.01', IncludeBackOOS=True))
        self.assertEqual(r['export_evidence_end'], '2026-07-04')
        self.assertEqual(r['seed_tester'], dict(FromDate='2025.07.05', ToDate='2026.02.28', ForwardMode=0, ForwardDate=''))
        self.assertEqual(r['heldout_lock'], dict(start='2026-07-04', end='2026-10-03', revealableAfter='2026-10-02'))
        self.assertEqual(r['foos_replay']['evidence_end'], '2026-10-02')

    def test_pinned_values_for_other_periods_and_a_leap_year(self):
        pinned = {
            (13, '2026-10-02'): ('2026.05.02', '2026.06.06', '2026.08.01', '2026.09.05'),
            (26, '2026-10-02'): ('2025.12.13', '2026.02.14', '2026.06.13', '2026.08.15'),
            (104, '2026-10-02'): ('2023.08.05', '2024.04.06', '2025.08.02', '2026.04.04'),
            # FOOS of 13 weeks ending 2024-03-01 spans the leap day: 91 days, still Saturday..Friday.
            (52, '2024-03-01'): ('2022.07.30', '2022.12.03', '2023.07.29', '2023.12.02'),
        }
        for (weeks, friday), (back, start, forward, to_date) in pinned.items():
            with self.subTest(weeks=weeks, friday=friday):
                r = w.compute(weeks, friday)
                self.assertEqual((r['export']['BackOOSDate'], r['tester']['FromDate'], r['tester']['ForwardDate'],
                                  r['tester']['ToDate']), (back, start, forward, to_date))
        self.assertEqual(w.compute(52, '2024-03-01')['foos']['days'], 91)

    def test_locked_table_boos_is_one_third_of_o(self):
        # Vince 2026-10-11 (goatai#2350 6106946678), Claude-Mac's gate (6162820519): BOOS = FWD = 1/3 O, rounded up.
        self.assertEqual((w.FRACTIONS['boos'], w.OOS_FORMULA, w.BOOS_SHARE[w.OOS_FORMULA]), ('1/3', 'boos-1/3', Fraction(1, 3)))
        table = {3: dict(boos=5, sample=8, fwd=5, foos=4), 6: dict(boos=9, sample=17, fwd=9, foos=7),
                 12: dict(boos=18, sample=34, fwd=18, foos=13), 24: dict(boos=35, sample=69, fwd=35, foos=26)}
        for months, weeks in table.items():
            with self.subTest(months=months):
                self.assertEqual(w.split(w.optimization_weeks(months=months)), weeks)
                self.assertEqual(w.compute(w.optimization_weeks(months=months), '2026-10-02')['weeks'], weeks)
        for o in range(2, 521):
            self.assertEqual(w.split(o)['boos'], w.split(o)['fwd'], o)       # never drifts back to 1/2 O

    def test_legacy_half_o_formula_keeps_the_old_dates(self):
        # The dates every batch stamped before the lock carries (the pre-fix pinned values).
        pinned = {(13, '2026-10-02'): '2026.04.18', (26, '2026-10-02'): '2025.11.15', (52, '2026-10-02'): '2025.01.04',
                  (104, '2026-10-02'): '2023.04.08', (52, '2024-03-01'): '2022.06.04'}
        for (weeks, friday), back in pinned.items():
            with self.subTest(weeks=weeks, friday=friday):
                old, new = w.compute(weeks, friday, 'boos-1/2'), w.compute(weeks, friday)
                self.assertEqual((old['export']['BackOOSDate'], old['oosFormula']), (back, 'boos-1/2'))
                for key in ('tester', 'sample', 'fwd', 'foos', 'optimization_end', 'export_evidence_end', 'seed_tester'):
                    self.assertEqual(old[key], new[key], key)        # only BOOS differs
        with self.assertRaises(ValueError):
            w.compute(52, '2026-10-02', 'boos-1/4')

    def test_invariants_for_every_period_and_export_friday(self):
        for months in MONTHS:
            for friday in FRIDAYS:
                with self.subTest(months=months, friday=friday):
                    o = w.optimization_weeks(months=months)
                    r = w.compute(o, friday)
                    parts = [r[k] for k in ('boos', 'sample', 'fwd', 'foos')]
                    for part in parts:
                        self.assertEqual(d(part['first_day']).weekday(), 5, 'windows start on a Saturday (after a week close)')
                        self.assertEqual(d(part['last_day']).weekday(), 4, 'windows end on a Friday close')
                        self.assertEqual((d(part['last_day']) - d(part['first_day'])).days + 1, 7 * part['weeks'])
                    for older, newer in zip(parts, parts[1:]):
                        self.assertEqual(d(older['last_day']) + timedelta(days=1), d(newer['first_day']), 'contiguous, no gap')
                    self.assertEqual(r['foos']['last_day'], friday)
                    self.assertEqual(r['optimization_end'], (d(friday) - timedelta(days=7 * r['weeks']['foos'])).isoformat())
                    self.assertEqual(r['weeks']['sample'] + r['weeks']['fwd'], o)
                    self.assertEqual(r['optimization']['first_day'], r['sample']['first_day'])
                    self.assertEqual(r['optimization']['last_day'], r['fwd']['last_day'])
                    self.assertEqual(r['tester']['ToDate'], w.mt5(d(r['optimization_end']) + timedelta(days=1)))
                    # MT5's exclusive ToDate is the evidence-end convention's tester_to_date of the optimization end.
                    self.assertEqual(r['tester']['ToDate'], w.mt5(d(r['foos']['first_day'])))

    def test_judging_windows_are_never_shorter_than_their_share(self):
        for o in range(2, 521):
            weeks = w.split(o)
            self.assertGreaterEqual(Fraction(weeks['boos']), Fraction(o, 3))
            self.assertGreaterEqual(Fraction(weeks['fwd']), Fraction(o, 3))
            self.assertGreaterEqual(Fraction(weeks['foos']), Fraction(o, 4))
            self.assertLess(weeks['boos'] - Fraction(o, 3), 1)
            self.assertLess(w.split(o, 'boos-1/2')['boos'] - Fraction(o, 2), 1)
            self.assertGreaterEqual(Fraction(w.split(o, 'boos-1/2')['boos']), Fraction(o, 2))
            self.assertLess(weeks['foos'] - Fraction(o, 4), 1)
            self.assertEqual(weeks['sample'] + weeks['fwd'], o)
            self.assertGreaterEqual(weeks['sample'], 1)

    def test_export_friday_must_be_a_friday_and_closed(self):
        for bad in ('2026-10-01', '2026-10-03', '2026.10.04'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.compute(52, bad)
        r = w.windows(12, 'auto', now=SATURDAY)
        self.assertEqual((r['export_friday'], r['export_friday_resolution']['mode']), ('2026-10-02', 'auto'))
        self.assertEqual(w.windows(52, '2026-09-25', unit='weeks', now=SATURDAY)['foos']['last_day'], '2026-09-25')
        with self.assertRaises(ValueError):
            w.windows(12, '2026-10-09', now=SATURDAY)      # not closed yet
        with self.assertRaises(ValueError):
            w.windows(12, '2026-09-30', now=SATURDAY)      # a Wednesday is refused, never moved
        with self.assertRaises(ValueError):
            w.windows(12, 'auto', unit='days', now=SATURDAY)

    def test_auto_follows_the_evidence_end_rule(self):
        friday_evening = datetime(2026, 10, 2, 20, 59, tzinfo=timezone.utc)   # before the NY close: still Sep 25
        self.assertEqual(w.windows(12, now=friday_evening)['export_friday'], ee.auto(friday_evening)['iso'])
        self.assertEqual(w.windows(12, now=friday_evening)['export_friday'], '2026-09-25')

    def test_formula_of_recognises_only_formula_dates(self):
        r = w.compute(52, '2026-10-02')
        self.assertEqual(w.formula_of(r['tester'], r['export']['BackOOSDate']), r)
        self.assertIsNone(w.formula_of(r['tester'], '2025.01.11'))
        self.assertIsNone(w.formula_of(dict(r['tester'], ForwardDate='2026.03.07'), r['export']['BackOOSDate']))
        self.assertIsNone(w.formula_of(dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01'), '2026.01.01'))
        self.assertIsNone(w.formula_of(None, '2026.01.01'))
        # Explicit 1/3 O dates are formula dates; so are an export's 1/2 O dates stamped before the lock.
        self.assertEqual(w.formula_of(r['tester'], '2025.03.01')['oosFormula'], 'boos-1/3')
        self.assertEqual(w.formula_of(r['tester'], '2025.01.04'), w.compute(52, '2026-10-02', 'boos-1/2'))

    def test_recorded_windows_are_re_derived(self):
        r = w.compute(52, '2026-10-02')
        self.assertEqual(w.same(json.loads(json.dumps(r))), r)
        for key, value in (('optimization_end', '2026-07-10'), ('export_evidence_end', '2026-10-03'),
                           ('tester', dict(r['tester'], ToDate='2026.10.03')), ('rule', 'other'),
                           ('oosFormula', 'boos-1/2'), ('oosFormula', 'boos-1/4')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                w.same(dict(r, **{key: value}))
        stripped = {key: value for key, value in r.items() if key != 'oosFormula'}
        with self.assertRaises(ValueError):
            w.same(stripped)            # a 1/3 O record cannot pass as a pre-lock 1/2 O one

    def legacy_record(self):
        """A record exactly as the pre-lock controller stamped it: BOOS 1/2 O and no oosFormula key."""
        record = json.loads(json.dumps(w.compute(52, '2026-10-02', 'boos-1/2')))
        del record['oosFormula']
        self.assertEqual((record['export']['BackOOSDate'], record['weeks']['boos'], record['boos']['first_day']),
                         ('2025.01.04', 26, '2025-01-04'))
        return record

    def test_a_record_stamped_under_half_o_still_validates(self):
        record = self.legacy_record()
        self.assertEqual(w.record_formula(record), 'boos-1/2')
        self.assertNotIn('oosFormula', w.same(record))
        native = dict(oos_windows=record, back_oos_date='2025.01.04', forward_start='2026.02.28',
                      export_settings=dict(BackOOSDate='2025.01.04', IncludeBackOOS=True),
                      evidence_end=dict(target='2026-07-04', ea_setting=dict(key='EvidenceEnd', value='2026.07.04')))
        jobs = [dict(conditions=dict(from_date='2025.07.05', to_date='2026.07.04', forward_mode=4))]
        self.assertEqual(w.verify_native(native, jobs), record)
        for change in (dict(back_oos_date='2025.03.01'), dict(export_settings=dict(BackOOSDate='2025.03.01', IncludeBackOOS=True))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                w.verify_native(dict(native, **change), jobs)        # still exact: its own 1/2 O dates only
        self.assertEqual(w.successor_request(record), dict(optimization_weeks=52, export_friday='2026-10-02', oosFormula='boos-1/2'))
        self.assertEqual(w.successor_request(w.compute(52, '2026-10-02'))['oosFormula'], 'boos-1/3')

    def test_explicit_one_third_dates_validate_at_activation(self):
        record = w.compute(52, '2026-10-02')
        native = dict(oos_windows=record, back_oos_date='2025.03.01', forward_start='2026.02.28',
                      export_settings=dict(BackOOSDate='2025.03.01', IncludeBackOOS=True),
                      evidence_end=dict(target='2026-07-04', ea_setting=dict(key='EvidenceEnd', value='2026.07.04')))
        jobs = [dict(conditions=dict(from_date='2025.07.05', to_date='2026.07.04', forward_mode=4))]
        self.assertEqual(w.verify_native(native, jobs), record)
        with self.assertRaises(ValueError):
            w.verify_native(dict(native, back_oos_date='2025.01.04'), jobs)


def window(trades=30, pf=1.2, dd=100.0, **extra):
    return dict(trades=trades, pf=pf, dd=dd, **extra)


class EvaluationTests(unittest.TestCase):
    def test_pass_needs_both_windows(self):
        result = w.judge(window(), window(), in_sample_dd=100.0)
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['used_for_ranking'])
        # The bar names what the in-sample drawdown was measured over: SAMPLE + FWD since rule version 2.
        self.assertEqual(result['bar'], dict(min_trades=30, min_pf=1.0, max_dd_ratio=1.5, in_sample='SAMPLE+FWD',
                                             min_loss_leg_o_weeks=52, min_loss_leg_o_months=12))
        self.assertEqual(w.judge(window(), window(), in_sample_dd=100.0, rule_version=1)['bar'],
                         dict(min_trades=30, min_pf=1.0, max_dd_ratio=1.5, in_sample='SAMPLE'))

    def test_thirty_trade_floor(self):
        for name in ('boos', 'foos'):
            with self.subTest(window=name):
                windows = dict(boos=window(), foos=window())
                windows[name] = window(trades=29)
                result = w.judge(windows['boos'], windows['foos'], in_sample_dd=100.0)
                self.assertEqual(result['status'], 'not_eligible_yet')
                self.assertIn('29 of 30', result['plain'])
                windows[name] = window(trades=30)
                self.assertEqual(w.judge(windows['boos'], windows['foos'], in_sample_dd=100.0)['status'], 'pass')

    def test_under_the_floor_is_never_judged_on_pf_or_dd_and_never_passes(self):
        result = w.judge(window(), window(trades=0, pf=0.1, dd=10000.0), in_sample_dd=100.0)
        self.assertEqual(result['status'], 'not_eligible_yet')
        self.assertEqual(result['windows']['foos']['status'], 'not_eligible_yet')
        self.assertIsNone(result['windows']['foos']['dd_limit'])

    def test_pf_bar(self):
        self.assertEqual(w.judge(window(pf=1.0), window(pf=1.0), in_sample_dd=100.0)['status'], 'pass')
        result = w.judge(window(), window(pf=0.999), in_sample_dd=100.0)
        self.assertEqual(result['status'], 'fail')
        self.assertIn('profit factor below 1.0 (1.00)', result['plain'])
        # The PF bar is FOOS's only: every BOOS is lenient, 1/2 O windows too (Claude-Mac 6165051704).
        for formula in ('boos-1/3', 'boos-1/2'):
            for version, o_weeks in ((1, None), (2, 52), (2, 13)):
                with self.subTest(formula=formula, version=version, o_weeks=o_weeks):
                    result = w.judge(window(pf=0.999, pl=-0.5, in_sample_p10=-10.0), window(),
                                     in_sample_dd=100.0, oos_formula=formula, rule_version=version, o_weeks=o_weeks)
                    self.assertEqual((result['status'], result['boosGate'], result['oosFormula']), ('pass', 'lenient_p10', formula))
                    self.assertNotIn('profit factor', result['plain'])
        self.assertEqual(w.judge(window(pf=None, pf_note='no losing deals'), window(), in_sample_dd=100.0)['status'], 'pass')

    def test_lenient_boos_is_never_a_profit_requirement(self):
        # Vince 6106946678 / Claude-Mac 6106961195: BOOS fails only on DD > 1.5x in-sample or a loss worse than the
        # in-sample 10th-percentile window of BOOS's own length.
        cases = ((dict(pf=0.5, pl=-40.0, in_sample_p10=-50.0), 'pass'),       # a loss, but no worse than p10
                 (dict(pf=0.5, pl=-50.0, in_sample_p10=-50.0), 'pass'),       # exactly at the bar
                 (dict(pf=0.5, pl=-50.01, in_sample_p10=-50.0), 'fail'),
                 (dict(pf=0.9, pl=-1.0, in_sample_p10=20.0), 'fail'),         # every in-sample window made money
                 (dict(pf=1.2, pl=30.0, in_sample_p10=None), 'pass'),         # no loss: p10 not needed
                 (dict(pf=0.9, pl=-1.0, in_sample_p10=None), 'not_measured'),
                 (dict(pf=0.9, pl=None, in_sample_p10=-50.0), 'not_measured'),
                 (dict(pf=0.5, pl=-40.0, in_sample_p10=-50.0, dd=150.01), 'fail'))
        # The same verdicts under rule version 1 (the loss leg at every O) and under version 2 for an O of 12 months or
        # more (52 weeks and up).
        for version, o_weeks in ((1, None), (1, 13), (2, 52), (2, 104)):
            for extra, status in cases:
                with self.subTest(version=version, o_weeks=o_weeks, extra=extra):
                    result = w.judge(window(**extra), window(), in_sample_dd=100.0, rule_version=version, o_weeks=o_weeks)
                    self.assertEqual(result['status'], status, result['plain'])
                    self.assertEqual(result['windows']['boos']['gate'], 'lenient_p10')
        result = w.judge(window(pf=0.5, pl=-40.0, in_sample_p10=-50.0, in_sample_windows=17), window(), in_sample_dd=100.0, o_weeks=52)
        self.assertEqual((result['oosFormula'], result['boosGate'], result['oosUsedForSelection'], result['used_for_ranking']),
                         ('boos-1/3', 'lenient_p10', 'gate_only', False))
        self.assertEqual(result['windows']['boos']['in_sample_p10'], -50.0)

    def test_percentile_is_linear_interpolation(self):
        self.assertEqual(w.percentile([-125, -125, -100, -75]), -125.0)
        self.assertAlmostEqual(w.percentile([10, 0, 20, 30, 40, 50, 60, 70, 80, 90, 100]), 10.0)
        self.assertAlmostEqual(w.percentile([0, 10]), 1.0)
        self.assertEqual(w.percentile([7]), 7.0)
        self.assertIsNone(w.percentile([]))

    def test_drawdown_bar_is_one_and_a_half_times_in_sample(self):
        self.assertEqual(w.judge(window(dd=150.0), window(dd=150.0), in_sample_dd=100.0)['status'], 'pass')
        self.assertEqual(w.judge(window(dd=0.3), window(dd=0.3), in_sample_dd=0.2)['status'], 'pass')   # exact at the bar
        for name in ('boos', 'foos'):
            windows = dict(boos=window(), foos=window())
            windows[name] = window(dd=150.01)
            result = w.judge(windows['boos'], windows['foos'], in_sample_dd=100.0)
            self.assertEqual(result['status'], 'fail', name)
            self.assertIn('1.5x the in-sample 100.00', result['plain'])
        self.assertEqual(w.judge(window(dd=0.01), window(), in_sample_dd=0.0)['status'], 'not_measured')   # no limit

    def test_a_failure_with_the_floor_met_outranks_a_thin_window(self):
        result = w.judge(window(dd=200.0), window(trades=3), in_sample_dd=100.0)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['windows']['foos']['status'], 'not_eligible_yet')

    def test_foos_not_tested_is_no_data_and_not_complete_is_not_eligible_yet(self):
        self.assertEqual(w.judge(window(), None, in_sample_dd=100.0)['status'], 'no_data')
        self.assertEqual(w.judge(window(), dict(present=False), in_sample_dd=100.0)['status'], 'no_data')
        partial = window(complete=False, tested_through='2026-09-18', last_day='2026-10-02')
        result = w.judge(window(), partial, in_sample_dd=100.0)
        self.assertEqual(result['status'], 'not_eligible_yet')
        self.assertIn('not complete yet', result['plain'])

    def test_missing_measurements_are_never_a_pass(self):
        for foos, in_sample, status in ((window(pf=None), 100.0, 'not_measured'), (window(trades=None), 100.0, 'no_data'),
                                        (window(dd=None), 100.0, 'not_measured'), (window(), None, 'not_measured'),
                                        (window(pf=None, pl=-1.0, dd=None), 100.0, 'fail')):
            with self.subTest(foos=foos, in_sample=in_sample):
                self.assertEqual(w.judge(window(), foos, in_sample_dd=in_sample)['status'], status)
        self.assertEqual(w.judge(None, window(), in_sample_dd=100.0)['status'], 'no_data')
        self.assertEqual(w.STATUSES, ('pass', 'fail', 'not_eligible_yet', 'no_data', 'not_measured'))

    def test_pf_test_is_net_result_at_least_zero(self):
        self.assertEqual(w.judge(window(pf=None, pl=0.0), window(pf=None, pl=0.0), in_sample_dd=100.0)['status'], 'pass')
        self.assertEqual(w.judge(window(), window(pf=None, pl=-0.01), in_sample_dd=100.0)['status'], 'fail')

    def test_judge_never_shortens_a_window(self):
        foos = window(trades=12, first_day='2026-07-04', last_day='2026-10-02')
        result = w.judge(window(), foos, in_sample_dd=100.0)
        self.assertEqual((result['windows']['foos']['first_day'], result['windows']['foos']['last_day']), ('2026-07-04', '2026-10-02'))
        self.assertEqual(foos, window(trades=12, first_day='2026-07-04', last_day='2026-10-02'))


class SharedFixtureTests(unittest.TestCase):
    """controller/fixtures/oos-holdout-gate-cases.json: the cases the desktop sift (goatai#2274) must match exactly."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent / w.FIXTURE
        cls.fixture = json.loads(path.read_text(encoding='utf-8'))

    def test_rules_match_the_module_constants(self):
        rules = self.fixture['rules']
        self.assertEqual(self.fixture['schema'], 'goat-oos-holdout-gate-cases-v1')
        self.assertEqual(rules['fractions_of_o'], w.FRACTIONS)
        self.assertEqual(w.split(12), dict(boos=4, sample=8, fwd=4, foos=3))        # 1/3, 2/3, 1/3, 1/4 of 12 weeks
        self.assertIn('in_sample_p10_pl', rules['boos_gate'])
        self.assertIn('10th percentile', self.fixture['definitions']['in_sample_p10_pl'])
        self.assertEqual((rules['min_trades'], rules['min_pf'], rules['max_dd_multiple_of_in_sample']),
                         (w.MIN_TRADES, w.MIN_PF, float(w.MAX_DD_RATIO)))
        self.assertEqual(tuple(rules['statuses']), w.STATUSES)
        self.assertEqual(tuple(rules['set_order']), w.SET_ORDER)
        self.assertEqual(set(rules['statuses']), set(rules['set_order']))
        # Rule versions: the fixture names the same versions, the same current one and the same loss-leg floor.
        self.assertEqual((tuple(rules['rule_versions']), rules['current_rule_version']), (w.RULE_VERSIONS, w.RULE_VERSION))
        self.assertEqual((rules['min_o_months_for_loss_leg'], rules['min_o_weeks_for_loss_leg']),
                         (w.MIN_LOSS_LEG_O_MONTHS, w.MIN_LOSS_LEG_O_WEEKS))
        self.assertNotIn('min_in_sample_windows_for_loss_leg', rules)           # the window count no longer decides
        self.assertEqual({int(version): text.split(' ')[0] for version, text in rules['in_sample_base'].items()}, w.IN_SAMPLE_BASE)
        self.assertIn('only for an O of 12 months or more (o_weeks >= 52)', rules['boos_gate'])
        self.assertIn('never by in_sample_windows', rules['boos_gate'])
        for key in ('rule_version', 'optimization_max_drawdown', 'in_sample_windows', 'o_weeks'):
            self.assertIn(key, self.fixture['definitions'])

    def cases(self):
        return self.fixture['window_cases'] + self.fixture['set_cases']

    def test_every_case_names_its_rule_version_and_both_versions_cover_every_result(self):
        for case in self.cases():
            self.assertIn(case.get('rule_version'), w.RULE_VERSIONS, case['id'])
        for version in w.RULE_VERSIONS:
            statuses = {case['expected'] for case in self.fixture['window_cases'] if case['rule_version'] == version}
            self.assertEqual(statuses, set(w.STATUSES), version)
        # A version 2 case gives the SAMPLE + FWD drawdown, never only SAMPLE's (a judge_case never falls back to it).
        for case in self.cases():
            if case['rule_version'] == 2:
                self.assertIn('optimization_max_drawdown', case, case['id'])
        fallback = dict(id='x', rule_version=2, window='foos', in_sample_max_drawdown=100,
                        input=dict(trades=40, pl=50, pf=1.2, max_drawdown=50))
        self.assertEqual(w.judge_case(fallback)['status'], 'not_measured')
        self.assertEqual(w.judge_case(dict(fallback, rule_version=1))['status'], 'pass')
        self.assertEqual(w.judge_case({k: v for k, v in fallback.items() if k != 'rule_version'})['status'], 'pass')   # none = version 1

    def test_the_two_proofs_of_the_rule_change(self):
        # Claude-Mac, goatai#2750 6787022949. Proof 1: the same inputs, version 1 fails and version 2 passes, for the loss
        # leg and for the drawdown base. Proof 2: real negatives are still not a pass under version 2.
        by_id = {case['id']: case for case in self.cases()}
        changes = set()
        for proof in self.fixture['rule_change_proofs']:
            old, new = by_id[proof['v1_case']], by_id[proof['v2_case']]
            with self.subTest(proof=proof['v1_case']):
                strip = lambda case: {k: v for k, v in case.items() if k not in ('id', 'rule_version', 'expected')}
                self.assertEqual(strip(old), strip(new), 'the two cases must have the same inputs')
                self.assertEqual((old['rule_version'], new['rule_version']), (1, 2))
                self.assertEqual((old['expected'], new['expected']), (proof['v1_expected'], proof['v2_expected']))
                self.assertEqual((w.judge_case(old)['status'], w.judge_case(new)['status']), ('fail', 'pass'))
            changes.add(proof['change'])
        self.assertEqual(changes, {'boos_loss_leg', 'in_sample_base'})
        negatives = [by_id[name] for name in self.fixture['still_not_a_pass_under_v2']]
        self.assertGreaterEqual(len(negatives), 10)
        for case in negatives:
            with self.subTest(case=case['id']):
                self.assertEqual(case['rule_version'], 2)
                self.assertNotEqual(case['expected'], 'pass')
                self.assertEqual(w.judge_case(case)['status'], case['expected'])
        self.assertEqual({case['expected'] for case in negatives}, {'fail', 'not_eligible_yet', 'not_measured'})
        # Both ways (Claude-Mac 6788392334): O = 13 and 26 weeks are proofs above; from 52 weeks a loss worse than the
        # p10 fails and one no worse passes; 51 weeks is still under the threshold; an unknown O is not measured.
        self.assertEqual({proof['v2_case'] for proof in self.fixture['rule_change_proofs'] if proof['change'] == 'boos_loss_leg'},
                         {'boos_loss_o_13_weeks_v2', 'boos_loss_o_26_weeks_v2', 'boos_loss_o_13_weeks_set_v2', 'boos_loss_o_26_weeks_set_v2'})
        expected = dict(boos_loss_o_52_weeks_worse_than_p10_v2=(52, 'fail'), boos_loss_o_52_weeks_at_p10_v2=(52, 'pass'),
                        boos_loss_o_52_weeks_within_p10_v2=(52, 'pass'), boos_loss_o_51_weeks_v2=(51, 'pass'),
                        boos_loss_o_104_weeks_worse_than_p10_v2=(104, 'fail'), boos_loss_o_unknown_v2=(None, 'not_measured'),
                        boos_loss_o_13_weeks_v2=(13, 'pass'), boos_loss_o_26_weeks_v2=(26, 'pass'))
        for name, (o_weeks, status) in expected.items():
            self.assertEqual((by_id[name]['o_weeks'], by_id[name]['expected'], w.judge_case(by_id[name])['status']),
                             (o_weeks, status, status), name)
        self.assertNotIn('o_weeks', by_id['boos_loss_o_absent_v2'])
        self.assertEqual(w.judge_case(by_id['boos_loss_o_absent_v2'])['status'], 'not_measured')
        # The 51-week and the 52-week case lose the same amount against the same p10: only O differs in the verdict.
        near, at = by_id['boos_loss_o_51_weeks_v2'], by_id['boos_loss_o_52_weeks_worse_than_p10_v2']
        self.assertEqual((near['input'], near['in_sample_p10_pl']), (at['input'], at['in_sample_p10_pl']))
        # The window count is printed and never decides: 10 windows at 27 weeks pass, 9 windows at 52 weeks fail.
        self.assertEqual((by_id['boos_loss_o_27_weeks_10_windows_v2']['in_sample_windows'], by_id['boos_loss_o_27_weeks_10_windows_v2']['expected']),
                         (10, 'pass'))
        self.assertEqual((by_id['boos_loss_o_52_weeks_9_windows_worse_than_p10_v2']['in_sample_windows'],
                          by_id['boos_loss_o_52_weeks_9_windows_worse_than_p10_v2']['expected']), (9, 'fail'))
        self.assertEqual(by_id['boos_loss_o_52_weeks_window_count_unknown_v2']['expected'], 'pass')
        self.assertEqual(by_id['foos_29_trades_v2']['expected'], 'not_eligible_yet')

    def test_a_version_2_window_result_states_the_loss_leg(self):
        by_id = {case['id']: case for case in self.fixture['window_cases']}
        for name, applied in (('boos_loss_o_13_weeks_v2', False), ('boos_loss_o_26_weeks_v2', False), ('boos_loss_o_51_weeks_v2', False),
                              ('boos_loss_o_52_weeks_worse_than_p10_v2', True), ('boos_loss_o_unknown_v2', None)):
            result = w.judge_case(by_id[name])
            self.assertEqual((result['loss_leg_applied'], result['o_weeks'], result['min_loss_leg_o_weeks'], result['in_sample_windows']),
                             (applied, by_id[name]['o_weeks'], 52, by_id[name]['in_sample_windows']), name)
            self.assertNotIn('min_in_sample_windows', result)
        old = w.judge_case(by_id['boos_loss_o_13_weeks_v1'])
        self.assertNotIn('loss_leg_applied', old)
        self.assertNotIn('o_weeks', old)
        self.assertEqual(old['in_sample_windows'], 4)

    def test_every_window_case(self):
        statuses = set()
        for case in self.fixture['window_cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(w.judge_case(case)['status'], case['expected'])
                statuses.add(case['expected'])
        self.assertEqual(statuses, set(w.STATUSES), 'the fixture covers every result')

    def test_every_set_case(self):
        for case in self.fixture['set_cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(w.judge_case(case)['status'], case['expected'])

    def test_every_date_case(self):
        for case in self.fixture['date_cases']:
            with self.subTest(case=case):
                r = w.compute(w.optimization_weeks(months=case['optimization_months']), case['export_friday'])
                expected = case['expected']
                self.assertEqual((r['export']['BackOOSDate'], r['tester']['FromDate'], r['tester']['ForwardDate'],
                                  r['tester']['ToDate'], r['optimization_end'], [r['foos']['first_day'], r['foos']['last_day']]),
                                 (expected['BackOOSDate'], expected['FromDate'], expected['ForwardDate'], expected['ToDate'],
                                  expected['optimization_end'], expected['foos']))

    def test_case_ids_are_unique(self):
        ids = [case['id'] for case in self.fixture['window_cases'] + self.fixture['set_cases']]
        self.assertEqual(len(ids), len(set(ids)))


class PlanTests(unittest.TestCase):
    def spec(self, **change):
        tester = dict(Expert='GOAT-EA\\GOAT V1.48.ex5', Symbol='EURUSD', Period='M15', Model=1, ExecutionMode=0, Optimization=2,
                      OptimizationCriterion=6, Deposit=10000, Currency='USD', Leverage='1:100', UseLocal=1, UseRemote=0,
                      UseCloud=0, Visual=0)
        export = dict(SetsToExport=2, MinScore=60, TargetDD=100, AdjustLots=False, MinARF=0.2, MinSR=2.5, IncludeSequenceData=False)
        spec = dict(schema_version=1, export=export, members=[dict(set_path='C:\\x.set', tester=tester)],
                    oos_windows=dict(optimization_months=12, export_friday='2026-10-02'))
        spec.update(change)
        return spec

    def test_plan_without_oos_windows_is_returned_unchanged(self):
        spec = self.spec()
        del spec['oos_windows']
        before = json.dumps(spec, sort_keys=True)
        filled, record = w.apply_to_batch_spec(spec, now=SATURDAY)
        self.assertIs(filled, spec)
        self.assertIsNone(record)
        self.assertEqual(json.dumps(spec, sort_keys=True), before)
        plan = dict(schema_version=1, jobs=[])
        self.assertEqual(w.apply_to_seed_plan(plan), (plan, None))
        self.assertIsNone(w.verify_native(dict(back_oos_date='2026.01.01'), []))

    def test_batch_plan_gets_every_date_explicitly(self):
        filled, record = w.apply_to_batch_spec(self.spec(), now=SATURDAY)
        tester = filled['members'][0]['tester']
        self.assertEqual({k: tester[k] for k in ('FromDate', 'ToDate', 'ForwardMode', 'ForwardDate')}, record['tester'])
        self.assertEqual((filled['export']['BackOOSDate'], filled['export']['IncludeBackOOS']), ('2025.03.01', True))
        self.assertEqual(record['oosFormula'], 'boos-1/3')
        self.assertEqual(filled['evidence_end'], '2026-07-04')
        self.assertEqual(record['requested'], dict(optimization_months=12, export_friday='2026-10-02'))

    def test_stated_dates_must_equal_the_formula(self):
        spec = self.spec()
        spec['members'][0]['tester'].update(FromDate='2025.07.05', ToDate='2026.07.04', ForwardMode=4, ForwardDate='2026.02.28')
        spec['export'].update(BackOOSDate='2025.03.01', IncludeBackOOS=True)      # explicit 1/3 O dates
        spec['evidence_end'] = '2026-07-04'
        self.assertEqual(w.apply_to_batch_spec(spec, now=SATURDAY)[1]['o_weeks'], 52)
        for path, value in ((('members', 0, 'tester', 'ToDate'), '2026.10.03'), (('members', 0, 'tester', 'ForwardMode'), 0),
                            (('export', 'BackOOSDate'), '2025.01.03'), (('export', 'IncludeBackOOS'), False),
                            (('export', 'BackOOSDate'), '2025.01.04'),          # 1/2 O dates under the current formula
                            (('oos_windows', 'oosFormula'), 'boos-1/4'),
                            (('evidence_end',), '2026-10-02'), (('evidence_end',), 'auto')):
            with self.subTest(path=path, value=value):
                changed = json.loads(json.dumps(spec))
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    w.apply_to_batch_spec(changed, now=SATURDAY)
        # A batch-resume successor of a pre-lock batch states its own formula and keeps its 1/2 O dates.
        legacy = json.loads(json.dumps(spec))
        legacy['export']['BackOOSDate'] = '2025.01.04'
        legacy['oos_windows']['oosFormula'] = 'boos-1/2'
        self.assertEqual(w.apply_to_batch_spec(legacy, now=SATURDAY)[1]['oosFormula'], 'boos-1/2')

    def test_bad_requests_refuse(self):
        for bad in (dict(), dict(optimization_months=12, extra=1), dict(optimization_months=12, optimization_weeks=52),
                    dict(optimization_months=12, export_friday=20261002), 'twelve'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.apply_to_batch_spec(self.spec(oos_windows=bad), now=SATURDAY)

    def test_seed_plan_reads_sample_only(self):
        tester = dict(self.spec()['members'][0]['tester'])
        plan = dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=600, cutoff=dict(min_fitness=0, min_trades=0),
                    jobs=[dict(set_path='C:\\x.set', tester=tester, frame_target=10)],
                    oos_windows=dict(optimization_weeks=52, export_friday='2026-10-02'))
        filled, record = w.apply_to_seed_plan(plan)
        self.assertNotIn('oos_windows', filled)
        seed = filled['jobs'][0]['tester']
        self.assertEqual((seed['FromDate'], seed['ToDate'], seed['ForwardMode'], seed['ForwardDate']),
                         ('2025.07.05', '2026.02.28', 0, ''))
        self.assertEqual(seed['ToDate'], record['tester']['ForwardDate'])      # FWD, BOOS and FOOS stay unseen

    def test_foos_never_reaches_the_export_or_the_member_span(self):
        record = w.compute(52, '2026-10-02')
        policy = dict(target=record['export_evidence_end'], ea_setting=dict(key='EvidenceEnd', value='2026.07.04'))
        self.assertTrue(w.assert_foos_held_out(record, policy))
        for bad in (dict(policy, ea_setting=dict(key='EvidenceEnd', value='2026.10.02')), dict(policy, target='2026-10-02'),
                    dict(target=record['export_evidence_end']), None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.assert_foos_held_out(record, bad)
        span = member_span(record['tester'], back_oos_date=record['export']['BackOOSDate'],
                           export_end=d(record['export_evidence_end']) + timedelta(days=1))
        # The member reads its whole export through the EvidenceEnd Saturday; the only FOOS day it can touch is that
        # Saturday (no FX trading). Every FOOS trading day lies after the span.
        self.assertEqual(span['end'], d(record['foos']['first_day']) + timedelta(days=1))
        self.assertFalse(overlaps(span['start'], span['end'], d(record['foos']['first_day']) + timedelta(days=1),
                                  d(record['foos']['last_day']) + timedelta(days=1)))
        self.assertEqual(span['start'], d(record['boos']['first_day']))


def write_equity(path, rows):
    lines = ['<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>']
    lines += ['%s\t%.2f\t%.2f\t0.0' % (stamp.strftime('%Y.%m.%d %H:%M'), balance, equity) for stamp, balance, equity in rows]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def msc(day, hour):
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000) + hour * 3600 * 1000


class RetestFixture:
    """A synthetic catch-up re-test of a formula export (O = 13 weeks, export Friday 2026-10-02)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.record = w.compute(13, '2026-10-02')

    def tearDown(self):
        self.temp.cleanup()

    def weekdays(self, key, end=None):
        if key == 'catchup':      # weeks after the export Friday, up to the re-test end
            first, last = d(self.record['foos']['last_day']) + timedelta(days=1), end
        else:
            first, last = d(self.record[key]['first_day']), d(self.record[key]['last_day'])
        return [first + timedelta(days=i) for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() < 5]

    def build(self, *, trades=None, dips=None, end=None, capture=True, losers=None):
        trades = dict(dict(boos=30, sample=30, fwd=10, foos=30, catchup=0), **(trades or {}))
        dips = dict(dict(boos=100.0, sample=100.0, fwd=0.0, foos=100.0, catchup=0.0), **(dips or {}))
        losers = dict(dict(boos=10, sample=10, fwd=2, foos=10, catchup=0), **(losers or {}))
        end = d(end or self.record['foos']['last_day'])
        rows, deals, equity, position = [], [], 10000.0, 0
        for key in ('boos', 'sample', 'fwd', 'foos', 'catchup'):
            days = [day for day in self.weekdays(key, end) if day <= end]
            dip_day = days[len(days) // 2] if days else None
            for index, day in enumerate(days):
                equity += 10.0
                rows.append((datetime.combine(day, datetime.min.time()) + timedelta(hours=12), equity, equity))
                if day == dip_day and dips[key]:
                    rows.append((datetime.combine(day, datetime.min.time()) + timedelta(hours=13), equity, equity - dips[key]))
            for n in range(trades[key]):
                if not days:
                    break
                day = days[n % len(days)]
                position += 1
                profit = -5.0 if n < losers[key] else 10.0
                deals.append(dict(server_time_msc=msc(day, 9), position_id=position, deal_entry=0, deal_type=0, lots=0.1,
                                  price=1.1, profit=0, commission=0, fee=0, swap=0))
                deals.append(dict(server_time_msc=msc(day, 10), position_id=position, deal_entry=1, deal_type=1, lots=0.1,
                                  price=1.1, profit=profit, commission=0, fee=0, swap=0))
        write_equity(self.root / 'retest.csv', rows)
        folder = self.root / 'retest.goatseq'
        folder.mkdir(exist_ok=True)
        (folder / 'manifest.json').write_text('{}', encoding='utf-8')
        with (folder / 'deals.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(deals[0]) if deals else ['server_time_msc'])
            writer.writeheader()
            writer.writerows(deals)
        original = dict(run=dict(back_oos_date=self.record['export']['BackOOSDate']), evidence_start=self.record['boos']['first_day'],
                        evidence_end=self.record['optimization_end'], windows={})
        retest = dict(csv_path=str(self.root / 'retest.csv'), evidence_end=end.isoformat(),
                      capture=dict(complete=capture, path=str(folder / 'manifest.json')))
        return original, retest

    def judge(self, rule_version=None, **kwargs):
        original, retest = self.build(**kwargs)
        return w.judge_retest(original, retest, tester=self.record['tester'], rule_version=rule_version)


class RetestTests(RetestFixture, unittest.TestCase):
    """judge_retest: the FOOS held-out replay scored with the window rule."""

    def test_pass(self):
        result = self.judge()
        self.assertEqual(result['status'], 'pass', result['plain'])
        self.assertEqual((result['windows']['boos']['trades'], result['windows']['foos']['trades']), (30, 30))
        self.assertAlmostEqual(result['windows']['foos']['pf'], 200 / 50)
        self.assertEqual(result['in_sample_dd'], 100.0)
        self.assertEqual(result['windows_dates']['foos'], dict(first_day='2026-09-05', last_day='2026-10-02'))
        self.assertEqual(result['trade_source'], 'capture_deals')

    def test_fewer_than_thirty_foos_trades_is_not_eligible_yet(self):
        self.assertEqual(self.judge(trades=dict(foos=29))['status'], 'not_eligible_yet')
        self.assertEqual(self.judge(trades=dict(boos=29))['status'], 'not_eligible_yet')

    def test_pf_and_dd_failures(self):
        self.assertEqual(self.judge(losers=dict(foos=25))['status'], 'fail')        # 5x10 / 25x5 = 0.4
        self.assertEqual(self.judge(dips=dict(boos=151.0))['status'], 'fail')
        self.assertEqual(self.judge(dips=dict(foos=150.0))['status'], 'pass')

    def test_a_replay_that_stops_before_the_export_friday_is_not_eligible_yet(self):
        result = self.judge(end='2026-09-25')
        self.assertEqual(result['status'], 'not_eligible_yet')
        self.assertIn('not complete yet', result['plain'])

    def test_catch_up_weeks_count_toward_foos(self):
        # 20 FOOS trades by the export Friday: not eligible yet. Two catch-up weeks add 12: judged, and passes.
        self.assertEqual(self.judge(trades=dict(foos=20))['status'], 'not_eligible_yet')
        result = self.judge(trades=dict(foos=20, catchup=12), end='2026-10-16')
        self.assertEqual(result['status'], 'pass', result['plain'])
        foos = result['windows']['foos']
        self.assertEqual((foos['first_day'], foos['last_day'], foos['trades']), ('2026-09-05', '2026-10-16', 32))
        self.assertEqual(result['foos_judged_through'], '2026-10-16')
        self.assertEqual(result['windows_dates']['foos'], dict(first_day='2026-09-05', last_day='2026-10-02'))
        # Losses in the catch-up weeks count as well.
        self.assertEqual(self.judge(trades=dict(catchup=40), losers=dict(catchup=40), end='2026-10-16')['status'], 'fail')

    def test_without_a_complete_capture_the_rule_cannot_pass(self):
        self.assertEqual(self.judge(capture=False)['status'], 'no_data')

    def test_lenient_boos_compares_with_rolling_in_sample_windows_of_its_own_length(self):
        # O = 13 weeks: BOOS 5 weeks, SAMPLE 8 weeks -> 4 rolling 5-week SAMPLE windows, one week apart. Every SAMPLE trade
        # loses 5 (30 trades on its first 30 weekdays): window results -125, -125, -100, -75, so p10 = -125.
        losing_sample = dict(sample=30)
        for version in w.RULE_VERSIONS:      # a loss no worse than the p10 passes under every version
            result = self.judge(version, trades=dict(boos=30), losers=dict(boos=21, **losing_sample))   # BOOS 9x10 - 21x5 = -15
            boos = result['windows']['boos']
            self.assertEqual((result['status'], boos['in_sample_p10'], boos['in_sample_windows']), ('pass', -125.0, 4), result['plain'])
            self.assertAlmostEqual(boos['pl'], -15.0)
            self.assertEqual((result['oosFormula'], result['boosGate']), ('boos-1/3', 'lenient_p10'))
        # Rule version 1 applied the loss leg at these 4 windows.
        worse = self.judge(1, trades=dict(boos=30), losers=dict(boos=30, **losing_sample))      # -150 < -125
        self.assertEqual(worse['status'], 'fail')
        self.assertIn('in-sample 10th-percentile window', worse['plain'])
        # A profitable in-sample history makes any BOOS loss worse than its p10.
        self.assertEqual(self.judge(1, losers=dict(boos=21))['status'], 'fail')
        # Rule version 2: O = 13 weeks is under 12 months, so the loss leg is not applied and neither loss fails.
        for losers in (dict(boos=30, **losing_sample), dict(boos=21)):
            result = self.judge(2, trades=dict(boos=30), losers=losers)
            boos = result['windows']['boos']
            self.assertEqual((result['status'], boos['status'], boos['loss_leg_applied'], boos['in_sample_windows']),
                             ('pass', 'pass', False, 4), result['plain'])
            self.assertIn('loss leg not applied (O = 13 weeks; it applies from 52 weeks, 12 months)', result['plain'])
            self.assertEqual((result['ruleVersion'], result['o_weeks'], result['in_sample_windows'], result['loss_leg_applied']),
                             (2, 13, 4, False))
            self.assertEqual((boos['o_weeks'], boos['min_loss_leg_o_weeks']), (13, 52))

    def test_a_half_o_export_keeps_its_windows_and_gets_the_lenient_bar(self):
        # Claude-Mac 6165051704: the window length follows the stamp, the bar is the lenient rule for EVERY BOOS.
        # O = 26 weeks under 1/2 O: BOOS 13 weeks (2025-11-15..2026-02-13), SAMPLE 17 weeks -> 5 rolling 13-week
        # SAMPLE windows. Every SAMPLE trade loses 5 (30 trades on its first 30 weekdays): -150, -125, -100, -75, -50,
        # so p10 = -150 + 0.4 x 25 = -140.
        self.record = w.compute(26, '2026-10-02', 'boos-1/2')
        self.assertEqual((self.record['weeks']['boos'], self.record['export']['BackOOSDate']), (13, '2025.11.15'))
        losing_sample = dict(sample=30)
        self.assertEqual(self.judge(2, losers=dict(boos=30, **losing_sample))['status'], 'pass')     # version 2: O = 26 weeks, no loss leg
        result = self.judge(1, losers=dict(boos=21, **losing_sample))                 # BOOS 9x10 - 21x5 = -15, PF 0.86
        boos = result['windows']['boos']
        self.assertEqual((result['status'], result['oosFormula'], result['boosGate']), ('pass', 'boos-1/2', 'lenient_p10'),
                         result['plain'])
        self.assertEqual(result['windows_dates']['boos'], dict(first_day='2025-11-15', last_day='2026-02-13'))
        self.assertEqual((boos['gate'], boos['in_sample_p10'], boos['in_sample_windows']), ('lenient_p10', -140.0, 5))
        self.assertLess(boos['pf'], 1.0)                                                 # PF < 1 no longer fails BOOS
        worse = self.judge(1, losers=dict(boos=30, **losing_sample))                   # -150 < -140
        self.assertEqual((worse['status'], worse['oosFormula']), ('fail', 'boos-1/2'))
        self.assertIn('in-sample 10th-percentile window', worse['plain'])

    def test_ambiguous_dates_only_change_the_stamp(self):
        # O = 4 weeks (also optimization_months=1): 1/2 O and 1/3 O both round up to a 2-week BOOS, so the dates alone
        # cannot tell the formulas apart. Without a stamp 'boos-1/2' is stamped; the windows and the gate are the same.
        self.record = w.compute(4, '2026-10-02')
        self.assertEqual(w.split(4), w.split(4, 'boos-1/2'))
        back = self.record['export']['BackOOSDate']
        self.assertEqual(w.formula_of(self.record['tester'], back)['oosFormula'], 'boos-1/2')
        self.assertEqual(w.formula_of(self.record['tester'], back, 'boos-1/3'), self.record)
        original, retest = self.build(losers=dict(boos=21))                                      # a BOOS loss
        for version, status in ((1, 'fail'), (2, 'pass')):       # O = 4 weeks: version 2 does not apply the loss leg
            inferred = w.judge_retest(original, retest, tester=self.record['tester'], rule_version=version)
            stamped = w.judge_retest(original, retest, tester=self.record['tester'], oos_formula='boos-1/3', rule_version=version)
            self.assertEqual((inferred['oosFormula'], stamped['oosFormula']), ('boos-1/2', 'boos-1/3'))
            for result in (inferred, stamped):
                self.assertEqual((result['boosGate'], result['status'], result['windows']['boos']['in_sample_windows']),
                                 ('lenient_p10', status, 1))

    def test_measurement_definitions_are_stated(self):
        result = self.judge()
        self.assertEqual(result['definitions'], w.DEFINITIONS)
        self.assertIn('not balance', w.DEFINITIONS['dd'])
        self.assertIn('commission', w.DEFINITIONS['pl'])
        self.assertAlmostEqual(result['windows']['foos']['pl'], 20 * 10.0 - 10 * 5.0)

    def test_not_applicable_to_explicit_dates_or_an_export_that_saw_foos(self):
        original, retest = self.build()
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        self.assertEqual(w.judge_retest(original, retest, tester=explicit)['status'], 'not_applicable')
        self.assertEqual(w.judge_retest(original, retest, tester=None)['status'], 'not_applicable')
        seen = dict(original, evidence_end='2026-09-11')
        result = w.judge_retest(seen, retest, tester=self.record['tester'])
        self.assertEqual(result['status'], 'not_applicable')
        self.assertIn('already contained FOOS days', result['plain'])


class RuleVersionTests(unittest.TestCase):
    """Rule version 2 (Claude-Mac, goatai#2750 6787022949): the loss leg needs 10 windows; every record names its version."""

    def test_versions(self):
        self.assertEqual((w.RULE_VERSIONS, w.RULE_VERSION), ((1, 2), 2))
        # The loss leg applies from an O of 12 months, in the module's own weeks (13/3 weeks a month, half up): 52.
        self.assertEqual((w.MIN_LOSS_LEG_O_MONTHS, w.MIN_LOSS_LEG_O_WEEKS), (12, 52))
        self.assertEqual(w.MIN_LOSS_LEG_O_WEEKS, w.optimization_weeks(months=12))
        self.assertEqual(w.MIN_LOSS_LEG_O_WEEKS, w.compute(w.optimization_weeks(months=12), '2026-10-02')['o_weeks'])
        self.assertFalse(hasattr(w, 'MIN_LOSS_LEG_WINDOWS'))                     # the window count no longer decides
        self.assertEqual(w.IN_SAMPLE_BASE, {1: 'SAMPLE', 2: 'SAMPLE+FWD'})
        self.assertEqual(w.MAX_DD_RATIO, Fraction(3, 2))       # the multiple stays 1.5
        self.assertEqual(w.EVALUATION, 'goat-oos-window-rule-v1')   # the record schema name is unchanged: readers match it
        for bad in (0, 3, '2', 2.0, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.judge(window(), window(), in_sample_dd=100.0, rule_version=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.judge_window('FOOS', window(), 100.0, rule_version=bad)

    def test_every_record_names_the_rule_it_was_judged_under(self):
        new = w.judge(window(), window(), in_sample_dd=100.0)
        old = w.judge(window(), window(), in_sample_dd=100.0, rule_version=1)
        self.assertEqual((new['ruleVersion'], old['ruleVersion']), (2, 1))
        self.assertEqual((w.record_rule_version(new), w.record_rule_version(old)), (2, 1))
        self.assertEqual(w.record_rule_version({k: v for k, v in old.items() if k != 'ruleVersion'}), 1)   # as stored before version 2
        self.assertIn('(OOS window rule v2)', new['plain'])
        self.assertIn('(OOS window rule): ', old['plain'])
        self.assertEqual(w.not_applicable('x')['ruleVersion'], 2)
        self.assertEqual(w.not_applicable('x', 1)['ruleVersion'], 1)
        # A version 1 record has exactly the keys it always had, plus the stamp.
        self.assertEqual(set(new) - set(old), {'in_sample_windows', 'loss_leg_applied', 'o_weeks'})
        self.assertEqual(set(old), {'schema', 'status', 'reasons', 'windows', 'in_sample_dd', 'bar', 'used_for_ranking',
                                    'boosContaminatedBy', 'oosFormula', 'boosGate', 'oosUsedForSelection', 'plain', 'ruleVersion'})

    def test_o_the_loss_leg_and_the_window_count_are_stated_on_every_version_2_record(self):
        for o_weeks, applied in ((13, False), (26, False), (51, False), (52, True), (104, True), (None, None)):
            result = w.judge(window(in_sample_windows=7), window(), in_sample_dd=100.0, o_weeks=o_weeks)
            self.assertEqual((result['o_weeks'], result['loss_leg_applied'], result['in_sample_windows']), (o_weeks, applied, 7), o_weeks)
            self.assertEqual((result['bar']['min_loss_leg_o_weeks'], result['bar']['min_loss_leg_o_months']), (52, 12))
            self.assertNotIn('min_in_sample_windows', result['bar'])
        # Also when BOOS is not judged at all: O and the count are on the record, not only on a judged BOOS window.
        thin = w.judge(window(trades=3, in_sample_windows=4), window(), in_sample_dd=100.0, o_weeks=13)
        self.assertEqual((thin['status'], thin['o_weeks'], thin['in_sample_windows'], thin['loss_leg_applied']),
                         ('not_eligible_yet', 13, 4, False))
        self.assertNotIn('in_sample_windows', thin['windows']['boos'])
        absent = w.judge(None, window(), in_sample_dd=100.0, o_weeks=52)
        self.assertEqual((absent['in_sample_windows'], absent['o_weeks'], absent['loss_leg_applied']), (None, 52, True))

    def test_the_loss_leg_applies_only_from_an_o_of_twelve_months(self):
        loss = dict(pf=0.2, pl=-500.0, in_sample_p10=25.0)        # far worse than a p10 of +25
        for o_weeks in (4, 13, 26, 27, 48, 51):
            with self.subTest(o_weeks=o_weeks):
                result = w.judge(window(**loss), window(), in_sample_dd=100.0, o_weeks=o_weeks)
                boos = result['windows']['boos']
                self.assertEqual((result['status'], boos['loss_leg_applied'], boos['o_weeks']), ('pass', False, o_weeks), result['plain'])
                self.assertIn('loss leg not applied (O = %d weeks; it applies from 52 weeks, 12 months)' % o_weeks, boos['reasons'][0])
                self.assertEqual(w.judge(window(**loss), window(), in_sample_dd=100.0, rule_version=1, o_weeks=o_weeks)['status'],
                                 'fail')                                    # version 1 failed every one of them
        for o_weeks in (52, 53, 78, 104, 520):
            with self.subTest(o_weeks=o_weeks):
                result = w.judge(window(**loss), window(), in_sample_dd=100.0, o_weeks=o_weeks)
                self.assertEqual((result['status'], result['windows']['boos']['loss_leg_applied']), ('fail', True))
                self.assertIn('worse than the in-sample 10th-percentile window', result['plain'])
                within = w.judge(window(pf=0.9, pl=-1.0, in_sample_p10=-50.0), window(), in_sample_dd=100.0, o_weeks=o_weeks)
                self.assertEqual(within['status'], 'pass')                  # a loss no worse than the p10 passes
        # Months and weeks agree: every plan of 12 months or more is at least 52 weeks, every shorter one is under it.
        for months in range(1, 121):
            self.assertEqual(w.optimization_weeks(months=months) >= w.MIN_LOSS_LEG_O_WEEKS, months >= 12, months)

    def test_the_window_count_never_decides_the_loss_leg(self):
        loss = dict(pf=0.2, pl=-500.0, in_sample_p10=25.0)
        for count in (None, 0, 4, 9, 10, 17, 35):
            with self.subTest(count=count):
                short = w.judge(window(in_sample_windows=count, **loss), window(), in_sample_dd=100.0, o_weeks=27)
                long = w.judge(window(in_sample_windows=count, **loss), window(), in_sample_dd=100.0, o_weeks=52)
                self.assertEqual((short['status'], long['status']), ('pass', 'fail'))
                self.assertEqual((short['in_sample_windows'], long['in_sample_windows']), (count, count))   # printed as given

    def test_a_boos_loss_with_an_unknown_o_is_not_measured_never_a_pass(self):
        loss = dict(pf=0.9, pl=-1.0, in_sample_p10=-50.0, in_sample_windows=17)      # a loss well inside the p10
        for o_weeks in (None, 0, -52, 52.0, '52', True):
            with self.subTest(o_weeks=o_weeks):
                result = w.judge(window(**loss), window(), in_sample_dd=100.0, o_weeks=o_weeks)
                self.assertEqual((result['status'], result['windows']['boos']['loss_leg_applied'], result['o_weeks']),
                                 ('not_measured', None, None))
                self.assertIn('the optimization period O is not known', result['plain'])
        self.assertEqual(w.judge(window(**loss), window(), in_sample_dd=100.0)['status'], 'not_measured')    # O not given at all
        # A profitable BOOS needs neither O nor the p10.
        self.assertEqual(w.judge(window(pl=5.0), window(), in_sample_dd=100.0)['status'], 'pass')
        # Under 12 months the p10 itself is not needed; from 12 months it is.
        self.assertEqual(w.judge(window(pf=0.9, pl=-1.0), window(), in_sample_dd=100.0, o_weeks=13)['status'], 'pass')
        self.assertEqual(w.judge(window(pf=0.9, pl=-1.0), window(), in_sample_dd=100.0, o_weeks=52)['status'], 'not_measured')
        # judge_window takes O the same way.
        self.assertEqual(w.judge_window('BOOS', window(**loss), 100.0, lenient=True)['status'], 'not_measured')
        self.assertEqual(w.judge_window('BOOS', window(**loss), 100.0, lenient=True, o_weeks=52)['status'], 'pass')
        self.assertEqual(w.judge_window('BOOS', window(**loss), 100.0, lenient=True, rule_version=1)['status'], 'pass')   # version 1 never reads O

    def test_the_drawdown_leg_and_the_trade_floor_still_judge_a_boos_under_twelve_months(self):
        loss = dict(pf=0.5, pl=-40.0, in_sample_p10=25.0, in_sample_windows=4)
        judge = lambda boos, in_sample_dd=100.0: w.judge(boos, window(), in_sample_dd=in_sample_dd, o_weeks=13)
        self.assertEqual(judge(window(dd=150.0, **loss))['status'], 'pass')
        deep = judge(window(dd=150.01, **loss))
        self.assertEqual(deep['status'], 'fail')
        self.assertIn('1.5x the in-sample 100.00', deep['plain'])
        self.assertEqual(judge(window(dd=None, **loss))['status'], 'not_measured')
        self.assertEqual(judge(window(**loss), None)['status'], 'not_measured')
        self.assertIn('no in-sample (SAMPLE+FWD) drawdown', judge(window(**loss), None)['plain'])
        self.assertIn('no in-sample (SAMPLE) drawdown', w.judge(window(), window(), in_sample_dd=None, rule_version=1)['plain'])
        # BOOS under 30 trades: unchanged, not eligible yet whatever it lost.
        self.assertEqual(judge(window(trades=29, **loss))['status'], 'not_eligible_yet')
    def test_window_counts_by_optimization_period(self):
        # SAMPLE holds SAMPLE weeks - BOOS weeks + 1 rolling windows of BOOS's length: 4 and 9 where the loss leg is off
        # (O = 3 and 6 months), 17 and 35 where it is on (12 and 24). The count is printed; O decides.
        counts = {months: (lambda s: s['sample'] - s['boos'] + 1)(w.split(w.optimization_weeks(months=months))) for months in MONTHS}
        self.assertEqual(counts, {3: 4, 6: 9, 12: 17, 24: 35})
        # Rounding up FWD and BOOS makes the count step unevenly with O (26 weeks hold 9, 27 hold 10, 28 hold 9 again),
        # which is why the leg is decided by O and not by the count (Claude-Mac 6788392334).
        self.assertEqual({o: (lambda s: s['sample'] - s['boos'] + 1)(w.split(o)) for o in (26, 27, 28, 29, 30)},
                         {26: 9, 27: 10, 28: 9, 29: 10, 30: 11})


class RuleVersion2RetestTests(RetestFixture, unittest.TestCase):
    """judge_retest under rule version 2: the in-sample drawdown is SAMPLE + FWD's, measured on the same equity rows."""

    def test_the_in_sample_drawdown_is_measured_over_sample_and_fwd_together(self):
        # SAMPLE dips 100, FWD dips 140, FOOS dips 180: above 1.5 x 100, within 1.5 x 140.
        dips = dict(sample=100.0, fwd=140.0, foos=180.0)
        old, new = self.judge(1, dips=dips), self.judge(2, dips=dips)
        self.assertEqual((old['status'], old['in_sample_dd'], old['bar']['in_sample']), ('fail', 100.0, 'SAMPLE'))
        self.assertIn('1.5x the in-sample 100.00', old['plain'])
        self.assertEqual((new['status'], new['in_sample_dd'], new['bar']['in_sample']), ('pass', 140.0, 'SAMPLE+FWD'), new['plain'])
        self.assertEqual(new['windows']['foos']['dd_limit'], 210.0)
        self.assertEqual(new['in_sample_window'], dict(name='SAMPLE+FWD', first_day=self.record['sample']['first_day'],
                                                       last_day=self.record['fwd']['last_day'], dd=140.0, complete=True))
        self.assertEqual(new['in_sample_window']['last_day'], self.record['optimization_end'])
        self.assertNotIn('in_sample_window', old)
        # BOOS and FOOS stay outside the base: a deeper BOOS or FOOS dip never raises its own bar.
        self.assertEqual(self.judge(2, dips=dict(boos=151.0))['status'], 'fail')
        self.assertEqual(self.judge(2, dips=dict(boos=151.0))['in_sample_dd'], 100.0)
        # Real negatives: above 1.5 x the new base fails under both versions; at the bar passes.
        self.assertEqual(self.judge(2, dips=dict(dips, foos=210.0))['status'], 'pass')
        deep = self.judge(2, dips=dict(dips, foos=211.0))
        self.assertEqual(deep['status'], 'fail')
        self.assertIn('1.5x the in-sample 140.00', deep['plain'])
        self.assertEqual(self.judge(1, dips=dict(dips, foos=211.0))['status'], 'fail')

    def test_a_drawdown_that_runs_from_sample_into_fwd_is_one_drawdown(self):
        # Equity rises 10 a weekday. A fall that starts on SAMPLE's last day (60 down by its close) and bottoms on FWD's
        # first trading day (100 down) is deeper over the span than in either window alone: SAMPLE sees 60, FWD sees 40
        # from its own opening equity, the span sees 100.
        original, retest = self.build(dips=dict(sample=50.0))
        last_sample, first_fwd = d(self.record['sample']['last_day']), d(self.record['fwd']['first_day']) + timedelta(days=2)
        peak = self.equity_on(retest, last_sample)
        self.insert_rows(retest, [(last_sample, '20:00', peak - 60), (first_fwd, '01:00', peak - 100)])
        old = w.judge_retest(original, retest, tester=self.record['tester'], rule_version=1)
        new = w.judge_retest(original, retest, tester=self.record['tester'], rule_version=2)
        self.assertEqual((old['in_sample_dd'], new['in_sample_dd']), (60.0, 100.0))
        self.assertEqual(new['in_sample_window']['dd'], 100.0)
        from studio_catchup_verdict import equity_rows, equity_window
        fwd = equity_window(equity_rows(retest['csv_path']), d(self.record['fwd']['first_day']), d(self.record['fwd']['last_day']))
        self.assertEqual(fwd['dd'], 40.0)

    def test_the_span_drawdown_starts_at_the_span_opening_equity(self):
        # A fall on BOOS's last day that has only partly recovered when SAMPLE opens is BOOS's drawdown. The in-sample
        # drawdown starts its peak at the span's opening equity (no carried peak), as every window's drawdown does.
        original, retest = self.build()
        last_boos, first_sample = d(self.record['boos']['last_day']), d(self.record['sample']['first_day']) + timedelta(days=2)
        peak = self.equity_on(retest, last_boos)
        self.insert_rows(retest, [(last_boos, '20:00', peak - 500), (first_sample, '01:00', peak - 300)])
        new = w.judge_retest(original, retest, tester=self.record['tester'], rule_version=2)
        self.assertEqual((new['windows']['boos']['dd'], new['in_sample_dd'], new['in_sample_window']['dd']), (500.0, 100.0, 100.0))

    @staticmethod
    def equity_on(retest, day):
        """The equity of the day's first row in the re-test CSV."""
        stamp = day.strftime('%Y.%m.%d')
        lines = Path(retest['csv_path']).read_text(encoding='utf-8').splitlines()
        return next(float(line.split('\t')[2]) for line in lines if line.startswith(stamp))

    @staticmethod
    def insert_rows(retest, rows):
        """Add (day, 'HH:MM', equity) rows to the re-test CSV, each at its place in time."""
        path = Path(retest['csv_path'])
        header, *lines = path.read_text(encoding='utf-8').splitlines()
        for day, clock, equity in rows:
            lines.append('%s %s\t%.2f\t%.2f\t0.0' % (day.strftime('%Y.%m.%d'), clock, equity, equity))
        path.write_text('\n'.join([header] + sorted(lines, key=lambda line: line[:16])) + '\n', encoding='utf-8')

    def test_an_incomplete_span_gives_no_base(self):
        # A re-test that stops inside FWD covers SAMPLE but not the whole O span: version 2 has no in-sample drawdown.
        end = (d(self.record['fwd']['first_day']) + timedelta(days=13)).isoformat()
        old, new = self.judge(1, end=end), self.judge(2, end=end)
        self.assertEqual((old['in_sample_dd'], old['windows']['boos']['status']), (100.0, 'pass'))
        self.assertEqual((new['in_sample_dd'], new['in_sample_window']['complete']), (None, False))
        self.assertEqual(new['windows']['boos']['status'], 'not_measured')
        self.assertIn('no in-sample (SAMPLE+FWD) drawdown to compare with', new['windows']['boos']['reasons'])
        self.assertEqual(new['status'], 'not_eligible_yet')          # FOOS has not been tested yet

    def test_the_window_count_is_printed_as_unknown_until_sample_is_complete(self):
        end = (d(self.record['sample']['first_day']) + timedelta(days=20)).isoformat()
        old = self.judge(1, end=end, losers=dict(boos=21))
        new = self.judge(2, end=end, losers=dict(boos=21))
        self.assertEqual(old['windows']['boos']['in_sample_windows'], 0)            # as version 1 always recorded it
        # Version 2 prints null, never "0 windows". The count decides nothing: O = 13 weeks keeps the loss leg off, and
        # BOOS is not measured only because the SAMPLE + FWD drawdown is not there yet.
        self.assertEqual((new['in_sample_windows'], new['o_weeks'], new['loss_leg_applied']), (None, 13, False))
        self.assertEqual(new['windows']['boos']['status'], 'not_measured')
        self.assertEqual(new['windows']['boos']['reasons'], ['no in-sample (SAMPLE+FWD) drawdown to compare with'])

    def test_at_twelve_months_a_loss_worse_than_the_p10_still_fails(self):
        # O = 52 weeks (12 months): the loss leg applies. BOOS 18 weeks, SAMPLE 34 -> 17 rolling windows. Every SAMPLE trade
        # loses 5 (30 trades on its first 30 weekdays): -150, -125, -100, -75, -50, -25 and eleven zeros, so
        # p10 = -125 + 0.6 x 25 = -110.
        self.record = w.compute(w.optimization_weeks(months=12), '2026-10-02')
        self.assertEqual(self.record['o_weeks'], 52)
        losing_sample = dict(sample=30)
        worse = self.judge(2, losers=dict(boos=30, **losing_sample))                   # -150 < -110
        boos = worse['windows']['boos']
        self.assertEqual((worse['status'], worse['o_weeks'], boos['in_sample_windows'], boos['loss_leg_applied']),
                         ('fail', 52, 17, True), worse['plain'])
        self.assertAlmostEqual(boos['in_sample_p10'], -110.0)
        self.assertIn('in-sample 10th-percentile window', worse['plain'])
        within = self.judge(2, losers=dict(boos=21, **losing_sample))                  # -15 >= -110
        self.assertEqual((within['status'], within['o_weeks'], within['in_sample_windows'], within['loss_leg_applied']),
                         ('pass', 52, 17, True))
        for losers in (dict(boos=30, **losing_sample), dict(boos=21, **losing_sample)):
            self.assertEqual(self.judge(1, losers=losers)['status'], self.judge(2, losers=losers)['status'])   # same verdicts as version 1

    def test_one_week_under_twelve_months_the_loss_leg_is_off(self):
        # O = 51 weeks: SAMPLE holds 18 windows, more than at 52 weeks, and the leg is still off. Every SAMPLE trade wins,
        # so any BOOS loss is worse than the p10: version 1 fails it, version 2 does not apply the leg.
        self.record = w.compute(51, '2026-10-02')
        old, new = self.judge(1, losers=dict(boos=30)), self.judge(2, losers=dict(boos=30))
        boos = new['windows']['boos']
        self.assertEqual((old['status'], new['status'], new['o_weeks'], boos['in_sample_windows'], boos['loss_leg_applied']),
                         ('fail', 'pass', 51, 18, False), new['plain'])
        self.assertIn('loss leg not applied (O = 51 weeks; it applies from 52 weeks, 12 months)', new['plain'])

    def test_at_six_months_the_loss_leg_is_off(self):
        self.record = w.compute(w.optimization_weeks(months=6), '2026-10-02')
        old, new = self.judge(1, losers=dict(boos=30)), self.judge(2, losers=dict(boos=30))
        boos = new['windows']['boos']
        self.assertEqual((old['status'], new['status'], new['o_weeks'], boos['in_sample_windows'], boos['loss_leg_applied']),
                         ('fail', 'pass', 26, 9, False), new['plain'])

    def test_a_half_o_record_of_twelve_months_gets_the_loss_leg_on_its_own_o(self):
        # A 'boos-1/2' record: O is still SAMPLE + FWD (52 weeks), BOOS is 26 weeks, so SAMPLE (34 weeks) holds only 9
        # rolling windows. The leg is decided by O: it applies. Every SAMPLE trade loses 5 (30 trades on its first 30
        # weekdays): -150, -125, -100, -75, -50, -25, 0, 0, 0, so p10 = -150 + 0.8 x 25 = -130.
        self.record = w.compute(52, '2026-10-02', 'boos-1/2')
        self.assertEqual((self.record['weeks']['boos'], self.record['weeks']['sample'], self.record['o_weeks']), (26, 34, 52))
        worse = self.judge(2, losers=dict(boos=30, sample=30))                         # -150 < -130
        boos = worse['windows']['boos']
        self.assertEqual((worse['status'], worse['oosFormula'], worse['o_weeks'], boos['in_sample_windows'], boos['loss_leg_applied']),
                         ('fail', 'boos-1/2', 52, 9, True), worse['plain'])
        self.assertAlmostEqual(boos['in_sample_p10'], -130.0)
        self.assertEqual(self.judge(2, losers=dict(boos=21, sample=30))['status'], 'pass')   # -15 >= -130
    def test_under_thirty_trades_is_still_not_eligible_yet(self):
        for version in w.RULE_VERSIONS:
            self.assertEqual(self.judge(version, trades=dict(foos=29))['status'], 'not_eligible_yet')
            self.assertEqual(self.judge(version, trades=dict(boos=29), losers=dict(boos=29))['status'], 'not_eligible_yet')

    def test_each_version_carries_its_own_definitions(self):
        old, new = self.judge(1), self.judge(2)
        self.assertEqual((old['definitions'], new['definitions']), (w.DEFINITIONS_V1, w.DEFINITIONS))
        self.assertEqual(w.DEFINITIONS_BY_VERSION, {1: w.DEFINITIONS_V1, 2: w.DEFINITIONS})
        self.assertIn('SAMPLE and FWD together', w.DEFINITIONS['in_sample_dd'])
        self.assertIn('not a decision input', w.DEFINITIONS['in_sample_p10'])
        self.assertIn('O of 12 months or more: o_weeks >= 52', w.DEFINITIONS['loss_leg'])
        self.assertIn('unknown O is not_measured', w.DEFINITIONS['loss_leg'])
        self.assertNotIn('loss_leg', w.DEFINITIONS_V1)
        for ruling in ('6787022949', '6788392334'):
            self.assertIn(ruling, w.DEFINITIONS['rule_version'])
        self.assertIn('1.5 x SAMPLE DD', w.DEFINITIONS_V1['dd_bar'])
        self.assertNotIn('in_sample_dd', w.DEFINITIONS_V1)
        for key in ('days', 'trades', 'pl', 'pf', 'foos'):
            self.assertEqual(w.DEFINITIONS[key], w.DEFINITIONS_V1[key], key)       # the measurements themselves did not change
        # The lock text says what the code does and keeps a dated note of what version 1 was.
        for words in ('rule version 2', '6787022949', '6788392334', '2026-11-11', 'SAMPLE and FWD together',
                      'only for an O of 12 months or\nmore: O >= 52 weeks', 'decided by O, never by the window count',
                      'Rule version 1', 'never rewritten'):
            self.assertIn(words, w.__doc__, words)

    def test_the_catch_up_hook_judges_under_the_current_version_and_stamps_it(self):
        from studio_catchup import CatchupRunner
        dips = dict(sample=100.0, fwd=140.0, foos=180.0)
        original, retest = self.build(dips=dips)
        spec = dict(original=dict(tester=self.record['tester']))
        result = CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up'))
        self.assertEqual((result['status'], result['ruleVersion'], result['bar']['in_sample'], result['in_sample_windows']),
                         ('pass', 2, 'SAMPLE+FWD', 4))
        self.assertEqual((result['o_weeks'], result['loss_leg_applied'], result['bar']['min_loss_leg_o_weeks']), (13, False, 52))
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        broken = dict(retest, csv_path=str(self.root / 'missing.csv'))
        for other in (CatchupRunner._oos_rule(original, retest, spec, dict(verdict='not_comparable')),
                      CatchupRunner._oos_rule(original, retest, dict(original=dict(tester=explicit)), dict(verdict='held_up')),
                      CatchupRunner._oos_rule(original, broken, spec, dict(verdict='held_up'))):
            self.assertEqual(other['ruleVersion'], w.RULE_VERSION, other['status'])


class CatchupHookTests(RetestFixture, unittest.TestCase):
    """The catch-up result carries oos_rule next to its unchanged verdict."""

    def spec(self, tester):
        return dict(original=dict(tester=tester))

    def test_every_oos_rule_stamps_boos_as_partly_selected_by_the_ea_trim(self):
        from studio_catchup import CatchupRunner
        original, retest = self.build()
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        broken = dict(retest, csv_path=str(self.root / 'missing.csv'))
        results = [CatchupRunner._oos_rule(original, retest, self.spec(self.record['tester']), dict(verdict='held_up')),
                   CatchupRunner._oos_rule(original, retest, self.spec(self.record['tester']), dict(verdict='not_comparable')),
                   CatchupRunner._oos_rule(original, retest, self.spec(explicit), dict(verdict='held_up')),
                   CatchupRunner._oos_rule(original, broken, self.spec(self.record['tester']), dict(verdict='held_up')),
                   w.judge(window(), window(), in_sample_dd=100.0), w.judge_case(dict(boos=None, foos=None))]
        self.assertEqual({r['status'] for r in results}, {'pass', 'no_data', 'not_applicable'})
        for result in results:
            self.assertEqual(result['boosContaminatedBy'], 'ea_trim', result['status'])
        self.assertEqual(w.BOOS_CONTAMINATED_BY, 'ea_trim')

    def test_formula_export_is_judged(self):
        from studio_catchup import CatchupRunner
        original, retest = self.build()
        result = CatchupRunner._oos_rule(original, retest, self.spec(self.record['tester']), dict(verdict='held_up'))
        self.assertEqual(result['status'], 'pass')

    def test_a_retest_that_is_not_the_same_test_is_never_judged(self):
        from studio_catchup import CatchupRunner
        original, retest = self.build()
        for verdict in ('not_comparable', 'unjudged'):
            result = CatchupRunner._oos_rule(original, retest, self.spec(self.record['tester']), dict(verdict=verdict))
            self.assertEqual(result['status'], 'no_data', verdict)

    def test_explicit_exports_read_not_applicable_and_errors_read_unknown(self):
        from studio_catchup import CatchupRunner
        original, retest = self.build()
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        self.assertEqual(CatchupRunner._oos_rule(original, retest, self.spec(explicit), dict(verdict='held_up'))['status'],
                         'not_applicable')
        broken = dict(retest, csv_path=str(self.root / 'missing.csv'))
        self.assertEqual(CatchupRunner._oos_rule(original, broken, self.spec(self.record['tester']), dict(verdict='held_up'))['status'],
                         'no_data')


class BatchFormulaTests(unittest.TestCase):
    """prepare-batch with oos_windows: explicit dates recorded, FOOS outside the export; explicit plans unchanged."""

    def setUp(self):
        import test_goat_studio as fixtures
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.controller = self.fixture.bound(); self.fixture.grant(self.controller)
        self.root = self.fixture.root
        source = self.root / 'Template.set'
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        tester = {k: v for k, v in self.fixture.tester.items() if k not in ('FromDate', 'ToDate', 'ForwardMode', 'ForwardDate')}
        export = {k: v for k, v in self.fixture.exports.items() if k not in ('BackOOSDate', 'IncludeBackOOS')}
        self.spec = dict(schema_version=1, export=export, oos_windows=dict(optimization_months=12),
                         members=[dict(set_path=str(source), tester=tester | {'Symbol': symbol})
                                  for symbol in ('EURUSD.customer', 'GBPUSD.customer')])
        self.explicit = dict(schema_version=1, export=self.fixture.exports, evidence_end='auto',
                             members=[dict(set_path=str(source), tester=self.fixture.tester)])

    def tearDown(self):
        self.fixture.tearDown()

    def observe(self):
        install = self.controller.install
        program = str(Path(install['terminal_data_root']) / 'MQL5' / 'Experts' / install['ea_relative_path'])
        path = self.controller.local / 'ui-observation.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(schema_version=1, runtime=dict(program_path=program), evidence_end=ee.CAPABILITY)),
                        encoding='utf-8')

    def prepare(self, name, spec, now=SATURDAY):
        from studio_batch import prepare_batch
        file = self.root / (name + '.json'); file.write_text(json.dumps(spec), encoding='utf-8')
        return prepare_batch(self.controller, name, file, now=now)

    def plan(self, result):
        package = Path(result['package'])
        return (json.loads((package / 'studio-plan.json').read_text(encoding='utf-8')),
                json.loads((package / 'manifest.json').read_text(encoding='utf-8')),
                (package / 'export_settings.GOAT').read_bytes().decode('utf-16'))

    def test_formula_batch_records_every_date_and_stops_exports_at_the_optimization_end(self):
        from activate_research_campaign import verify_export_policy
        from studio_batch import batch_status
        self.observe()
        result = self.prepare('formula-batch', self.spec)
        plan, manifest, export = self.plan(result)
        native = plan['native_batch']
        record = native['oos_windows']
        self.assertEqual((record['export_friday'], record['o_weeks'], record['optimization_end']), ('2026-10-02', 52, '2026-07-03'))
        self.assertEqual((native['back_oos_date'], native['forward_start']), ('2025.03.01', '2026.02.28'))
        self.assertEqual(record['oosFormula'], 'boos-1/3')
        for job in plan['jobs']:
            self.assertEqual((job['conditions']['from_date'], job['conditions']['to_date'], job['conditions']['forward_mode']),
                             ('2025.07.05', '2026.07.04', 4))
        self.assertIn('EvidenceEnd=2026.07.04\r\n', export)
        self.assertIn('BackOOSDate=2025.03.01\r\n', export)
        self.assertIn('IncludeBackOOS=1\r\n', export)
        self.assertEqual(manifest['export_evidence_end'], '2026.07.04')
        self.assertEqual(native['evidence_end']['target'], '2026-07-04')
        self.assertEqual(native['evidence_end']['warnings'], [])
        self.assertEqual(native['evidence_end']['evidenceEndMode'], 'oos_windows')
        # The stamp proves the Saturday ToDate covers the nominal end exactly.
        self.assertEqual((native['evidence_end']['evidenceEnd'], native['evidence_end']['evidenceEndEffective']), ('2026-07-04', '2026-07-04'))
        self.assertIn('FOOS 2026-07-04 to 2026-10-02 is held out', native['evidence_end']['catch_up'])
        verify_export_policy(Path(result['package']), plan, manifest)
        status = batch_status(self.controller, 'formula-batch')
        self.assertEqual(status['oos_windows']['windows']['foos'], dict(first_day='2026-07-04', last_day='2026-10-02', weeks=13))
        self.assertEqual(status['oos_windows']['foos_replay']['evidence_end'], '2026-10-02')

    def test_a_tampered_record_is_refused_at_activation(self):
        from activate_research_campaign import verify_export_policy
        self.observe()
        result = self.prepare('formula-batch', self.spec)
        plan, manifest, _ = self.plan(result)
        changed = json.loads(json.dumps(plan))
        changed['native_batch']['oos_windows']['foos']['last_day'] = '2026-10-09'
        with self.assertRaises(ValueError):
            verify_export_policy(Path(result['package']), changed, manifest)
        changed = json.loads(json.dumps(plan))
        changed['native_batch']['back_oos_date'] = '2025.01.11'
        with self.assertRaises(ValueError):
            verify_export_policy(Path(result['package']), changed, manifest)

    def test_builds_without_evidence_end_refuse_the_formula(self):
        with self.assertRaises(ValueError) as caught:
            self.prepare('formula-batch', self.spec)
        self.assertIn('has not reported EvidenceEnd support', str(caught.exception))
        self.assertFalse((self.controller.root / 'packages' / 'formula-batch').exists())

    def test_explicit_date_plans_are_unchanged(self):
        result = self.prepare('explicit-batch', self.explicit)
        plan, _, export = self.plan(result)
        self.assertNotIn('oos_windows', plan['native_batch'])
        self.assertEqual(set(plan['native_batch']), {'export_end_policy', 'back_oos_date', 'forward_start', 'export_settings',
                                                     'evidence_end', 'run_relative'})
        self.assertEqual((plan['native_batch']['back_oos_date'], plan['native_batch']['forward_start']), ('2026.01.01', '2026.07.01'))
        self.assertEqual((plan['jobs'][0]['conditions']['from_date'], plan['jobs'][0]['conditions']['to_date']), ('2026.02.01', '2026.09.01'))
        self.assertNotIn('EvidenceEnd', export)       # unchanged legacy end on a build without the capability
        # Legacy build: the EA's last Friday is an exclusive ToDate, so the exports cover through Thursday.
        policy = plan['native_batch']['evidence_end']
        self.assertEqual((policy['evidenceEnd'], policy['evidenceEndEffective'], policy['evidenceEndMode']),
                         ('2026-10-02', '2026-10-01', 'legacy_thursday_cut'))
        self.assertTrue(any('through Thursday 2026-10-01' in warning for warning in policy['warnings']))

    def test_conflicting_explicit_dates_refuse(self):
        self.observe()
        spec = json.loads(json.dumps(self.spec))
        spec['members'][0]['tester']['FromDate'] = '2026.02.01'
        with self.assertRaises(ValueError):
            self.prepare('formula-batch', spec)
        spec = json.loads(json.dumps(self.spec))
        spec['evidence_end'] = 'auto'
        with self.assertRaises(ValueError):
            self.prepare('formula-batch', spec)

    def test_successor_keeps_the_same_windows_after_the_next_friday(self):
        from studio_batch import resume_batch
        self.observe()
        self.prepare('formula-batch', self.spec)
        self.controller.cancel('formula-batch')
        successor = resume_batch(self.controller, 'formula-batch', 'formula-batch-r1', now=SATURDAY + timedelta(days=7))
        plan, _, export = self.plan(successor)
        self.assertEqual(plan['native_batch']['oos_windows']['export_friday'], '2026-10-02')
        self.assertEqual(plan['native_batch']['oos_windows']['oosFormula'], 'boos-1/3')
        self.assertIn('EvidenceEnd=2026.07.04\r\n', export)

    def test_successor_of_a_half_o_batch_keeps_its_formula(self):
        from activate_research_campaign import verify_export_policy
        from studio_batch import batch_status, resume_batch
        self.observe()
        spec = json.loads(json.dumps(self.spec))
        spec['oos_windows']['oosFormula'] = 'boos-1/2'
        self.prepare('formula-batch', spec)
        self.controller.cancel('formula-batch')
        successor = resume_batch(self.controller, 'formula-batch', 'formula-batch-r1', now=SATURDAY + timedelta(days=7))
        plan, manifest, export = self.plan(successor)
        record = plan['native_batch']['oos_windows']
        self.assertEqual((record['oosFormula'], record['weeks']['boos'], plan['native_batch']['back_oos_date']),
                         ('boos-1/2', 26, '2025.01.04'))
        self.assertIn('BackOOSDate=2025.01.04\r\n', export)
        verify_export_policy(Path(successor['package']), plan, manifest)      # activation accepts its own 1/2 O windows
        self.assertEqual(batch_status(self.controller, 'formula-batch-r1')['oos_windows']['oosFormula'], 'boos-1/2')


class SeedFormulaTests(unittest.TestCase):
    """seed-validate/seed-prepare with oos_windows: SAMPLE-only dates; plans without it unchanged."""

    def setUp(self):
        import test_studio_seed
        self.fixture = test_studio_seed.SeedTests('test_prepare_preserves_source_and_only_tags_description')
        self.fixture.setUp()
        tester = {k: v for k, v in self.fixture.plan['jobs'][0]['tester'].items()
                  if k not in ('FromDate', 'ToDate', 'ForwardMode', 'ForwardDate')}
        self.plan = dict(self.fixture.plan, jobs=[dict(self.fixture.plan['jobs'][0], tester=tester)],
                         oos_windows=dict(optimization_weeks=13, export_friday='2026-10-02'))

    def tearDown(self):
        self.fixture.tearDown()

    def test_seed_jobs_read_sample_only_and_the_plan_stays_hash_bound(self):
        from campaign_ledger import sha
        from studio_installation import read_json
        preview = self.fixture.runner.validate(self.plan)
        self.assertEqual((preview['jobs'][0]['from_date'], preview['jobs'][0]['to_date']), ('2026.06.06', '2026.08.01'))
        self.assertEqual(preview['oos_windows']['sample'], dict(w.compute(13, '2026-10-02')['sample']))
        self.fixture.runner.prepare('batch', self.plan)
        manifest = read_json(self.fixture.runner.path('batch') / 'manifest.json')
        tester = manifest['members'][0]['tester']
        self.assertEqual((tester['FromDate'], tester['ToDate'], tester['ForwardMode'], tester['ForwardDate']),
                         ('2026.06.06', '2026.08.01', 0, ''))
        self.assertEqual(manifest['plan_sha256'], sha(self.plan))
        self.assertEqual(manifest['requested_plan'], self.plan)
        self.assertEqual(manifest['oos_windows']['export_friday'], '2026-10-02')
        self.assertEqual(self.fixture.runner.prepare('batch', self.plan)['status'], 'prepared')   # same plan: retained

    def test_seed_plan_without_oos_windows_is_unchanged(self):
        from studio_installation import read_json
        self.fixture.runner.prepare('batch', self.fixture.plan)
        manifest = read_json(self.fixture.runner.path('batch') / 'manifest.json')
        self.assertEqual(manifest['plan'], self.fixture.plan)
        self.assertNotIn('oos_windows', manifest)
        self.assertNotIn('requested_plan', manifest)


WEDNESDAY = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)      # broker Wed 18:00: the latest closed day is Tue Oct 6


class ClosedDayTests(unittest.TestCase):
    """Evidence for live decisions runs to the latest CLOSED DAY (goatai#1885 6008215775): catch-up only."""

    def test_auto_day_resolver(self):
        cases = {WEDNESDAY: '2026-10-06',
                 datetime(2026, 10, 7, 21, 1, tzinfo=timezone.utc): '2026-10-07',      # server Thu 00:01: Wed has closed
                 datetime(2026, 10, 7, 20, 59, tzinfo=timezone.utc): '2026-10-06',     # server Wed 23:59: not yet
                 SATURDAY: '2026-10-02', datetime(2026, 10, 4, 12, tzinfo=timezone.utc): '2026-10-02',   # Sat, Sun
                 datetime(2026, 10, 5, 10, tzinfo=timezone.utc): '2026-10-02',         # Monday: Friday
                 datetime(2026, 10, 2, 15, tzinfo=timezone.utc): '2026-10-01'}         # Friday before the close: Thursday
        for now, expected in cases.items():
            with self.subTest(now=now):
                result = ee.auto_day(now)
                self.assertEqual((result['iso'], result['rule']), (expected, 'goat-closed-day-v1'))
                self.assertLess(d(result['iso']).weekday(), 5)
        self.assertEqual(ee.auto_day(WEDNESDAY, holidays=['2026-10-06'])['iso'], '2026-10-05')
        self.assertEqual(ee.auto_day(datetime(2026, 10, 5, 10, tzinfo=timezone.utc), holidays=['2026-10-02'])['iso'], '2026-10-01')
        self.assertEqual(ee.auto_day(WEDNESDAY)['tester_to_date'], '2026.10.07')
        self.assertEqual(ee.auto_day(WEDNESDAY)['next_date'], '2026.10.07')

    def test_catch_up_accepts_the_last_closed_weekday(self):
        from studio_catchup import resolve_target
        for value in ('auto_day', 'AUTO_DAY', 'auto-day'):
            result = resolve_target(value, now=WEDNESDAY)
            self.assertEqual((result['mode'], result['requested'], result['iso'], result['rule'], result['warnings']),
                             ('auto_day', 'auto_day', '2026-10-06', 'goat-closed-day-v1', []))
        explicit = resolve_target('2026-10-06', now=WEDNESDAY)
        self.assertEqual((explicit['mode'], explicit['iso']), ('explicit', '2026-10-06'))   # the same date, explicit: like-for-like
        self.assertEqual(resolve_target('auto', now=WEDNESDAY)['iso'], '2026-10-02')          # auto is still the closed Friday

    def test_catch_up_refuses_a_future_or_unclosed_day(self):
        from studio_catchup import resolve_target
        for value in ('2026-10-07', '2026-10-08', '2026-12-31'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'not a closed broker day'):
                resolve_target(value, now=WEDNESDAY)

    def test_exports_refuse_auto_day_and_non_fridays(self):
        from studio_batch import evidence_end_policy
        tester = dict(ToDate='2026.07.04')
        with self.assertRaisesRegex(ValueError, 'OOS catch-up only'):
            evidence_end_policy('auto_day', [tester], now=WEDNESDAY)
        with self.assertRaisesRegex(ValueError, 'OOS catch-up only'):
            ee.resolve('auto_day', WEDNESDAY)
        with self.assertRaisesRegex(ValueError, 'OOS catch-up only'):
            w.windows(12, 'auto_day', now=WEDNESDAY)
        with self.assertRaisesRegex(ValueError, 'must be a Friday'):
            w.windows(12, '2026-10-06', now=WEDNESDAY)
        self.assertEqual(evidence_end_policy('auto', [tester], now=WEDNESDAY)['target'], '2026-10-02')
        with self.assertRaises(ValueError):
            w.apply_to_batch_spec(PlanTests.spec(PlanTests(), oos_windows=dict(optimization_months=12, export_friday='auto_day')),
                                  now=WEDNESDAY)


class EvidenceEndModeTests(unittest.TestCase):
    """evidenceEndMode (Claude-Mac, #1885 6008569394): a legacy explicit non-Friday export end is kept, never
    refused, and stamped legacy_explicit; a catch-up's explicit closed weekday is explicit_day."""

    def test_export_policy_modes(self):
        from studio_batch import evidence_end_policy
        tester = dict(ToDate='2026.07.04')
        legacy = evidence_end_policy('2026-10-06', [tester], now=WEDNESDAY)          # a Tuesday: kept, warned, stamped
        self.assertEqual((legacy['target'], legacy['mode'], legacy['evidenceEndMode']), ('2026-10-06', 'explicit', 'legacy_explicit'))
        self.assertTrue(any('not a Friday' in warning for warning in legacy['warnings']))
        friday = evidence_end_policy('2026-09-25', [tester], now=WEDNESDAY)
        self.assertEqual(friday['evidenceEndMode'], 'explicit')
        self.assertEqual(evidence_end_policy('auto', [tester], now=WEDNESDAY)['evidenceEndMode'], 'auto')

    def test_mode_helper(self):
        from studio_catchup import resolve_target
        cases = (('auto', False, 'auto'), ('auto_day', True, 'auto_day'), ('2026-10-02', False, 'explicit'),
                 ('2026-10-02', True, 'explicit'), ('2026-10-06', False, 'legacy_explicit'), ('2026-10-06', True, 'explicit_day'))
        for value, catch_up, expected in cases:
            with self.subTest(value=value, catch_up=catch_up):
                self.assertEqual(ee.evidence_end_mode(resolve_target(value, now=WEDNESDAY), catch_up=catch_up), expected)

    def test_formula_batch_is_not_legacy(self):
        record = w.compute(52, '2026-10-02')
        policy = dict(requested='2026-07-04', mode='explicit', evidenceEndMode='legacy_explicit', target='2026-07-04',
                      evidenceEnd='2026-07-04', evidenceEndEffective='2026-07-04',
                      warnings=['Sat Jul 4 is not a Friday; evidence ending mid-week compares poorly with weekly files.'],
                      native_export_end='evidence_end_setting', ea_setting=dict(key='EvidenceEnd', value='2026.07.04'))
        from studio_batch import oos_windows_evidence
        stamped = oos_windows_evidence(record, policy)
        self.assertEqual((stamped['evidenceEndMode'], stamped['warnings']), ('oos_windows', []))
        with self.assertRaisesRegex(ValueError, 'must cover exactly its nominal export end'):
            oos_windows_evidence(record, dict(policy, evidenceEndEffective='2026-07-03'))


class EffectiveEndTests(unittest.TestCase):
    """evidenceEndEffective (Claude-Mac, #1885 6008626040): the last day a test covers = exclusive ToDate - 1."""

    def test_effective_end(self):
        self.assertEqual(ee.effective_end('2026.10.03'), '2026-10-02')
        self.assertEqual(ee.effective_end('2026.07.04'), '2026-07-03')

    def test_batch_policy_stamps(self):
        from studio_evidence_end_export import stamp_effective
        base = dict(requested='auto', mode='auto', evidenceEndMode='auto', target='2026-10-02', warnings=[],
                    native_export_end='ea_last_friday_exclusive', native_end_if_exported_now='2026-10-01')
        legacy = stamp_effective(base)
        self.assertEqual((legacy['evidenceEnd'], legacy['evidenceEndEffective'], legacy['evidenceEndMode']),
                         ('2026-10-02', '2026-10-01', 'legacy_thursday_cut'))
        self.assertEqual(len(legacy['warnings']), 1)
        capable = stamp_effective(dict(base, native_export_end='evidence_end_setting', ea_setting=dict(key='EvidenceEnd', value='2026.10.02')))
        self.assertEqual((capable['evidenceEndEffective'], capable['evidenceEndMode'], capable['warnings']), ('2026-10-02', 'auto', []))
        older = stamp_effective(dict(base, target='2026-09-25'))      # legacy end later than an older nominal Friday: no cut
        self.assertEqual((older['evidenceEndEffective'], older['evidenceEndMode']), ('2026-10-01', 'auto'))
        self.assertIsNone(stamp_effective(None))

class ClosedDayRetestTests(RetestFixture, unittest.TestCase):
    """Catch-up days after the export Friday, through a mid-week closed day, count toward the FOOS floor."""

    def test_foos_floor_counts_catch_up_days_through_a_wednesday(self):
        original, retest = self.build(trades=dict(foos=20, catchup=12), end='2026-10-07')
        self.assertEqual(w.judge_retest(original, dict(retest, evidence_end='2026-10-02'), tester=self.record['tester'])['status'],
                         'not_eligible_yet')                                    # 20 by the export Friday
        result = w.judge_retest(original, retest, tester=self.record['tester'], evidence_end='2026-10-07')
        foos = result['windows']['foos']
        self.assertEqual((result['status'], foos['last_day'], foos['trades'], result['evidenceEnd']),
                         ('pass', '2026-10-07', 32, '2026-10-07'))

    def test_one_decision_is_judged_through_its_own_end_date(self):
        # A re-test that ran further is judged only through the decision's evidence end (like-for-like).
        original, retest = self.build(trades=dict(foos=20, catchup=24), end='2026-10-14')
        result = w.judge_retest(original, retest, tester=self.record['tester'], evidence_end='2026-10-07')
        self.assertEqual((result['windows']['foos']['last_day'], result['evidenceEnd']), ('2026-10-07', '2026-10-07'))
        self.assertLess(result['windows']['foos']['trades'], 44)

    def test_every_hook_result_stamps_evidence_end(self):
        from studio_catchup import CatchupRunner
        original, retest = self.build(end='2026-10-07')
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        for tester, verdict in ((self.record['tester'], 'held_up'), (self.record['tester'], 'not_comparable'), (explicit, 'held_up')):
            result = CatchupRunner._oos_rule(original, retest, dict(original=dict(tester=tester)), dict(verdict=verdict),
                                             evidence_end='2026-10-07')
            self.assertEqual(result['evidenceEnd'], '2026-10-07', result['status'])


class ClosedDayCatchupCycleTests(unittest.TestCase):
    """A whole catch-up with evidence_end auto_day on a Wednesday: resolved, recorded and stamped on every result."""

    def setUp(self):
        import test_studio_catchup as cases
        import studio_catchup as sc
        self.case = cases.NativeCycleTests('test_full_cycle_moves_the_retest_and_judges_the_new_weeks')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        c = self.case
        c.runner = sc.CatchupRunner(c.controller, process=c.process, clock=lambda: c.now, sleep=c.sleep, now=WEDNESDAY)

    def test_auto_day_cycle(self):
        from studio_installation import read_json
        c = self.case
        prepared = c.runner.prepare('cu1', dict(c.plan(sets=[c.behind]), evidence_end='auto_day'))
        self.assertEqual((prepared['preview']['target']['iso'], prepared['preview']['target']['mode']), ('2026-10-06', 'auto_day'))
        c.auto = True
        self.assertEqual(c.runner.start('cu1', 30)['status'], 'completed')
        manifest = read_json(c.runner.path('cu1') / 'manifest.json')
        self.assertEqual((manifest['evidence_end']['iso'], manifest['evidence_end']['mode'], manifest['plan']['evidence_end']),
                         ('2026-10-06', 'auto_day', 'auto_day'))
        member = manifest['members'][0]
        self.assertEqual(member['tester']['ToDate'], '2026.10.07')        # MT5 ToDate is exclusive: through Tue Oct 6
        version = read_json(Path(member['evidence_dir']) / 'evidence-version.json')
        self.assertEqual((version['evidenceEnd'], version['evidenceEndMode'], version['target_end']), ('2026-10-06', 'auto_day', '2026-10-06'))
        self.assertEqual((version['catch_up']['evidenceEnd'], version['catch_up']['evidenceEndMode']), ('2026-10-06', 'auto_day'))
        self.assertEqual(version['oos_rule']['evidenceEnd'], '2026-10-06')
        self.assertEqual(version['qualification']['evidence_end']['rule'], 'goat-closed-day-v1')
        report = c.runner.report('cu1')
        self.assertEqual(report['evidence_end']['iso'], '2026-10-06')
        self.assertEqual(report['members'][0]['evidenceEnd'], '2026-10-06')
        self.assertEqual(report['members'][0]['summary']['evidenceEnd'], '2026-10-06')
        self.assertEqual(report['members'][0]['summary']['evidenceEndMode'], 'auto_day')
        self.assertEqual((version['evidenceEndMode'], version['catch_up']['evidenceEndMode']), ('auto_day', 'auto_day'))
        # ToDate = evidence end + 1 (exclusive), so the closed day is fully covered: effective == nominal.
        self.assertEqual((version['evidenceEndEffective'], version['catch_up']['evidenceEndEffective'], version['oos_rule']['evidenceEndEffective'],
                          report['members'][0]['evidenceEndEffective'], report['members'][0]['summary']['evidenceEndEffective']),
                         ('2026-10-06',) * 5)
        # A day later the same catch-up still reads its recorded date; auto_day itself has moved on.
        import studio_catchup as sc
        later = sc.CatchupRunner(c.controller, process=c.process, clock=lambda: c.now, sleep=c.sleep,
                                 now=WEDNESDAY + timedelta(days=1))
        self.assertEqual(later.report('cu1')['evidence_end']['iso'], '2026-10-06')
        self.assertEqual(sc.resolve_target('auto_day', now=WEDNESDAY + timedelta(days=1))['iso'], '2026-10-07')


class DemoRuleTests(unittest.TestCase):
    def test_demo_rule_is_calendar_time_and_trades(self):
        rule = w.DEMO_RULE
        self.assertEqual((rule['minimum_weeks'], rule['minimum_trades'], rule['decision_due_weeks']), (4, 30, 6))
        self.assertEqual((rule['too_slow'], rule['judged_at'], rule['automated']), ('too_slow_to_judge_here', 'portfolio', False))
        self.assertIn('execution parity', rule['plain'])


if __name__ == '__main__':
    unittest.main()
