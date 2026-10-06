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
        self.assertEqual(r['weeks'], dict(boos=26, sample=34, fwd=18, foos=13))
        self.assertEqual({k: (r[k]['first_day'], r[k]['last_day']) for k in ('boos', 'sample', 'fwd', 'foos')}, dict(
            boos=('2025-01-04', '2025-07-04'), sample=('2025-07-05', '2026-02-27'),
            fwd=('2026-02-28', '2026-07-03'), foos=('2026-07-04', '2026-10-02')))
        self.assertEqual(r['optimization_end'], '2026-07-03')
        self.assertEqual(r['tester'], dict(FromDate='2025.07.05', ToDate='2026.07.04', ForwardMode=4, ForwardDate='2026.02.28'))
        self.assertEqual(r['export'], dict(BackOOSDate='2025.01.04', IncludeBackOOS=True))
        self.assertEqual(r['export_evidence_end'], '2026-07-04')
        self.assertEqual(r['seed_tester'], dict(FromDate='2025.07.05', ToDate='2026.02.28', ForwardMode=0, ForwardDate=''))
        self.assertEqual(r['heldout_lock'], dict(start='2026-07-04', end='2026-10-03', revealableAfter='2026-10-02'))
        self.assertEqual(r['foos_replay']['evidence_end'], '2026-10-02')

    def test_pinned_values_for_other_periods_and_a_leap_year(self):
        pinned = {
            (13, '2026-10-02'): ('2026.04.18', '2026.06.06', '2026.08.01', '2026.09.05'),
            (26, '2026-10-02'): ('2025.11.15', '2026.02.14', '2026.06.13', '2026.08.15'),
            (104, '2026-10-02'): ('2023.04.08', '2024.04.06', '2025.08.02', '2026.04.04'),
            # FOOS of 13 weeks ending 2024-03-01 spans the leap day: 91 days, still Saturday..Friday.
            (52, '2024-03-01'): ('2022.06.04', '2022.12.03', '2023.07.29', '2023.12.02'),
        }
        for (weeks, friday), (back, start, forward, to_date) in pinned.items():
            with self.subTest(weeks=weeks, friday=friday):
                r = w.compute(weeks, friday)
                self.assertEqual((r['export']['BackOOSDate'], r['tester']['FromDate'], r['tester']['ForwardDate'],
                                  r['tester']['ToDate']), (back, start, forward, to_date))
        self.assertEqual(w.compute(52, '2024-03-01')['foos']['days'], 91)

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
            self.assertGreaterEqual(Fraction(weeks['boos']), Fraction(o, 2))
            self.assertGreaterEqual(Fraction(weeks['fwd']), Fraction(o, 3))
            self.assertGreaterEqual(Fraction(weeks['foos']), Fraction(o, 4))
            self.assertLess(weeks['boos'] - Fraction(o, 2), 1)
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

    def test_recorded_windows_are_re_derived(self):
        r = w.compute(52, '2026-10-02')
        self.assertEqual(w.same(json.loads(json.dumps(r))), r)
        for key, value in (('optimization_end', '2026-07-10'), ('export_evidence_end', '2026-10-03'),
                           ('tester', dict(r['tester'], ToDate='2026.10.03')), ('rule', 'other')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                w.same(dict(r, **{key: value}))


def window(trades=30, pf=1.2, dd=100.0, **extra):
    return dict(trades=trades, pf=pf, dd=dd, **extra)


class EvaluationTests(unittest.TestCase):
    def test_pass_needs_both_windows(self):
        result = w.judge(window(), window(), in_sample_dd=100.0)
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['used_for_ranking'])
        self.assertEqual(result['bar'], dict(min_trades=30, min_pf=1.0, max_dd_ratio=1.5, in_sample='SAMPLE'))

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
        for name in ('boos', 'foos'):
            windows = dict(boos=window(), foos=window())
            windows[name] = window(pf=0.999)
            result = w.judge(windows['boos'], windows['foos'], in_sample_dd=100.0)
            self.assertEqual(result['status'], 'fail', name)
            self.assertIn('profit factor below 1.0 (1.00)', result['plain'])
        self.assertEqual(w.judge(window(pf=None, pf_note='no losing deals'), window(), in_sample_dd=100.0)['status'], 'pass')

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
        result = w.judge(window(pf=0.5), window(trades=3), in_sample_dd=100.0)
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
        self.assertEqual(w.judge(window(pf=None, pl=-0.01), window(), in_sample_dd=100.0)['status'], 'fail')

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
        self.assertEqual(w.split(12), dict(boos=6, sample=8, fwd=4, foos=3))        # 1/2, 2/3, 1/3, 1/4 of 12 weeks
        self.assertEqual((rules['min_trades'], rules['min_pf'], rules['max_dd_multiple_of_in_sample']),
                         (w.MIN_TRADES, w.MIN_PF, float(w.MAX_DD_RATIO)))
        self.assertEqual(tuple(rules['statuses']), w.STATUSES)
        self.assertEqual(tuple(rules['set_order']), w.SET_ORDER)
        self.assertEqual(set(rules['statuses']), set(rules['set_order']))

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
        self.assertEqual((filled['export']['BackOOSDate'], filled['export']['IncludeBackOOS']), ('2025.01.04', True))
        self.assertEqual(filled['evidence_end'], '2026-07-04')
        self.assertEqual(record['requested'], dict(optimization_months=12, export_friday='2026-10-02'))

    def test_stated_dates_must_equal_the_formula(self):
        spec = self.spec()
        spec['members'][0]['tester'].update(FromDate='2025.07.05', ToDate='2026.07.04', ForwardMode=4, ForwardDate='2026.02.28')
        spec['export'].update(BackOOSDate='2025.01.04', IncludeBackOOS=True)
        spec['evidence_end'] = '2026-07-04'
        self.assertEqual(w.apply_to_batch_spec(spec, now=SATURDAY)[1]['o_weeks'], 52)
        for path, value in ((('members', 0, 'tester', 'ToDate'), '2026.10.03'), (('members', 0, 'tester', 'ForwardMode'), 0),
                            (('export', 'BackOOSDate'), '2025.01.03'), (('export', 'IncludeBackOOS'), False),
                            (('evidence_end',), '2026-10-02'), (('evidence_end',), 'auto')):
            with self.subTest(path=path, value=value):
                changed = json.loads(json.dumps(spec))
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    w.apply_to_batch_spec(changed, now=SATURDAY)

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

    def judge(self, **kwargs):
        original, retest = self.build(**kwargs)
        return w.judge_retest(original, retest, tester=self.record['tester'])


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
        self.assertEqual((native['back_oos_date'], native['forward_start']), ('2025.01.04', '2026.02.28'))
        for job in plan['jobs']:
            self.assertEqual((job['conditions']['from_date'], job['conditions']['to_date'], job['conditions']['forward_mode']),
                             ('2025.07.05', '2026.07.04', 4))
        self.assertIn('EvidenceEnd=2026.07.04\r\n', export)
        self.assertIn('BackOOSDate=2025.01.04\r\n', export)
        self.assertIn('IncludeBackOOS=1\r\n', export)
        self.assertEqual(manifest['export_evidence_end'], '2026.07.04')
        self.assertEqual(native['evidence_end']['target'], '2026-07-04')
        self.assertEqual(native['evidence_end']['warnings'], [])
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
        self.assertIn('EvidenceEnd=2026.07.04\r\n', export)


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
