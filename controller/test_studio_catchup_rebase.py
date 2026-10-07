"""Swap-only drift rule for OOS catch-up (studio_catchup_rebase, goat-catchup-rebase-v2, goatai#1885 6029484888)."""
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import studio_catchup_rebase as rb
import studio_catchup as sc
import studio_catchup_verdict as cv
from studio_catchup import UNCARRIED, CatchupRunner, catch_up_stamp, classify
from studio_evidence import read_export
from studio_installation import read_json
from studio_window_metrics import window as metrics_window
from test_studio_catchup import AFTER_CLOSE, CatchupCase
from test_studio_catchup_verdict import ORIGINAL_END, TESTER, Scenario, msc
from test_studio_oos_windows import RetestFixture

FIXTURE = json.loads((Path(__file__).resolve().parent / rb.FIXTURE).read_text(encoding='utf-8'))
D = Decimal
DRIFT_KEYS = {'dealCountDelta', 'pfDelta', 'balanceDelta', 'ddDelta', 'maxEquityGap', 'swapDelta', 'swapBound', 'originalSwap',
              'retestSwap', 'cause', 'reviewFlag', 'reviewReason'}


class FixtureTests(unittest.TestCase):
    """The shared fixture: every rule, a just-pass and a just-fail per boundary, identity, multi-fail, first failing rule."""

    def test_every_case(self):
        names = [case['name'] for case in FIXTURE['cases']]
        self.assertEqual(len(names), len(set(names)))
        for case in FIXTURE['cases']:
            with self.subTest(case=case['name']):
                expected = case['expected']
                result = rb.judge_case(case, FIXTURE['defaults'])
                self.assertEqual((result['verdict'], result['failed']), (expected['verdict'], expected['failed']))
                self.assertIn(result['verdict'], rb.VERDICTS)
                self.assertEqual(result['schema'], 'goat-catchup-rebase-v2')
                self.assertEqual(result['crossBuild'], case.get('cross_build', False))
                if 'cause' in expected:
                    self.assertEqual(result['tickHistoryDrift']['cause'], expected['cause'])
                if result['verdict'] == rb.REQUALIFY:
                    # The first failing rule and its first differing row are logged; the reasons name every failed rule in order.
                    self.assertEqual(result['firstFailingRule'], expected['failed'][0])
                    self.assertEqual(result['firstFailingRule'], expected.get('firstFailingRule', expected['failed'][0]))
                    self.assertEqual(result['firstFailingCause'], expected.get('firstFailingCause', result['firstFailingCause']))
                    self.assertTrue(result['firstFailingCause'].split(':')[0] == result['firstFailingRule'])
                    causes = {row['rule']: row['cause'] for row in result['rules'] if not row['ok']}
                    self.assertLessEqual(expected.get('causes', {}).items(), causes.items())
                    self.assertIsNotNone(result['firstDifference'])
                    if 'firstDifferenceTime' in expected:
                        self.assertEqual(result['firstDifference']['time'], expected['firstDifferenceTime'])
                    self.assertEqual([reason.split(':')[0] for reason in result['reasons']], expected['failed'])
                    self.assertEqual([row['rule'] for row in result['rules']], list(rb.RULES))
                    self.assertEqual((result['tickHistoryDrift']['cause'], result['tickHistoryDrift']['reviewFlag']),
                                     (rb.HISTORY_OR_BEHAVIOUR, False))
                elif result['verdict'] == rb.REBASED:
                    self.assertEqual((result['firstFailingRule'], result['firstDifference']), (None, None))
                    self.assertEqual([row['rule'] for row in result['rules'] if row['ok']], list(rb.RULES))
                    self.assertEqual((result['decidedBy'], result['tickHistoryDrift']['cause']), ('behaviour_rules', rb.SWAP_OR_SPEC))
                    self.assertEqual(set(result['tickHistoryDrift']), DRIFT_KEYS)
                    if 'reviewFlag' in expected:
                        self.assertIs(result['tickHistoryDrift']['reviewFlag'], expected['reviewFlag'])
                        if expected['reviewFlag']:
                            self.assertTrue(result['tickHistoryDrift']['reviewReason'])
                else:
                    self.assertIsNone(result['rules'])
                    self.assertIsNone(result['tickHistoryDrift'])
                    self.assertIsNone(result['firstFailingRule'])

    def test_fixture_covers_every_rule_and_boundary(self):
        firsts = {c['expected'].get('firstFailingRule') for c in FIXTURE['cases']}
        self.assertLessEqual(set(rb.RULES), firsts)
        for label in ('on the deposit term (', 'on the deposit term high', 'on the P/L term', 'balance just', 'equity just', 'max DD just',
                      'max DD just pass low'):
            with self.subTest(boundary=label):
                matching = [c for c in FIXTURE['cases'] if label in c['name']]
                self.assertTrue(any('just pass' in c['name'] for c in matching) or label == 'max DD just pass low', label)
                self.assertTrue(any(c['expected']['verdict'] == rb.REBASED for c in matching), label)
                if label != 'max DD just pass low':
                    self.assertTrue(any(c['expected']['verdict'] == rb.REQUALIFY for c in matching), label)
        self.assertEqual({c['expected']['verdict'] for c in FIXTURE['cases']}, set(rb.VERDICTS))
        self.assertTrue(any(len(c['expected']['failed']) > 2 for c in FIXTURE['cases']))

    def test_the_v1_aggregate_pass_no_longer_passes(self):
        # A deal moved by a minute: v1 compared deal count, PF, balance, SAMPLE side and DD in aggregate and re-based it.
        case = dict(retest=dict(deals_edit=[[1, 'server_time_msc', '1767780060000']]))
        result = rb.judge_case(case, FIXTURE['defaults'])
        old, new = (rb.fixture_run(FIXTURE['defaults'][side]) for side in ('original', 'retest'))
        self.assertEqual(rb.equity_figures(old['rows'][:-1]), rb.equity_figures(new['rows'][:-1]), 'every aggregate unchanged')
        self.assertEqual((result['verdict'], result['failed'], result['firstFailingRule']), (rb.REQUALIFY, ['deals'], 'deals'))
        self.assertEqual(result['firstDifference']['fields'], ['server_time_msc'])
        for retired in ('criteria', 'CRITERIA', 'deal_level', 'money_check', 'DEAL_COUNT_REL', 'PF_ABS', 'BALANCE_OF_DEPOSIT', 'CROSS_BUILD'):
            self.assertFalse(hasattr(rb, retired), retired)

    def test_nothing_measured_requalifies(self):
        result = rb.decide([], False)
        self.assertEqual((result['verdict'], result['failed'], result['firstFailingRule']), (rb.REQUALIFY, ['capture'], 'capture'))
        # No equity rows before the cut: the drawdown is not measured, which fails it (never waved through).
        old, new = rb.fixture_run({}), rb.fixture_run({})
        cut = rb._msc(old['rows'][-1][0])
        old['rows'] = new['rows'] = []
        rules = {row['rule']: row['ok'] for row in rb.behaviour_check(old, new, cut)['rules']}
        self.assertFalse(rules['max_dd'])
        self.assertTrue(rules['equity'])
        self.assertFalse(rules['swap'], 'no net P/L to size the swap bound')

    def test_drift_is_retest_minus_original(self):
        result = rb.judge_case(dict(retest=dict(swap=[-12.5, -12.5])), FIXTURE['defaults'])
        drift = result['tickHistoryDrift']
        self.assertEqual((drift['swapDelta'], drift['swapBound'], drift['originalSwap'], drift['retestSwap']), (-5.0, 25.0, -20.0, -25.0))
        self.assertEqual((drift['balanceDelta'], drift['ddDelta']), (-5.0, 5.0))
        self.assertEqual((result['swap']['delta'], result['swap']['deposit'], result['swap']['originalNet']), (-5.0, 100000.0, 480.0))

    def test_fill_timing_and_incomplete_causes(self):
        close = dict(server_time_msc=10, deal_type='1', deal_entry='1', lots=D(1), price=D('1.1'), profit=D(5))
        moved = dict(close, server_time_msc=11, price=D('1.0999'), profit=D('4.9'))
        self.assertEqual(rb.deal_cause(True, [close], [moved]), 'deals:fill_timing')
        self.assertEqual(rb.deal_cause(False, [close], [moved]), 'deals', 'orders differ')
        self.assertEqual(rb.deal_cause(True, [close], [dict(moved, deal_entry='0')]), 'deals', 'an entry, not a close')
        self.assertEqual(rb.deal_cause(True, [dict(close, deal_entry='0')], [dict(moved, deal_entry='0')]), 'deals', 'an entry, not a close')
        self.assertEqual(rb.deal_cause(True, [close], [dict(close, profit=D(6))]), 'deals', 'profit alone')
        self.assertEqual(rb.deal_cause(True, [close], [dict(moved, lots=D(2))]), 'deals', 'other lots')
        self.assertEqual(rb.deal_cause(True, [close], [moved, moved]), 'deals', 'another deal count')
        self.assertEqual(rb.deal_cause(True, [close, dict(close, deal_entry='3')], [moved, dict(moved, deal_entry='3')]), 'deals:fill_timing')
        self.assertEqual(rb.read_run(None, [], 0)['missing'], [rb.INCOMPLETE])

    def test_an_unsized_swap_drift_is_flagged(self):
        self.assertEqual(rb.swap_review({}, {}, deposit=100000)[0], True)
        self.assertEqual(rb.swap_review(dict(final_balance=100480), dict(final_balance=100475), deposit=None)[0], True)


class MoneyRowTests(unittest.TestCase):
    """The balance and equity rules on account rows (pure)."""

    @staticmethod
    def row(stamp, balance, equity, realized, total, quote=None, reason='minute'):
        return (stamp, reason, D(str(balance)), D(str(equity)), D(str(realized)), D(str(total)), stamp if quote is None else quote)

    def test_equity_follows_the_swap_as_of_the_last_tick(self):
        # Rollover at t=100 charges both runs' open position (the re-test 0.40 more); no tick until t=300.
        original = [self.row(0, 1000, 1000, 0, 0), self.row(100, 1000, 1000, 0, -1, quote=50), self.row(200, 1000, 1000, 0, -1, quote=50),
                    self.row(300, 1000, 999, 0, -1)]
        retest = [self.row(0, 1000, 1000, 0, 0), self.row(100, 1000, 1000, 0, -1.4, quote=50), self.row(200, 1000, 1000, 0, -1.4, quote=50),
                  self.row(300, 1000, 998.6, 0, -1.4)]
        money = rb.money_rows(original, retest)
        self.assertTrue(money['balance']['ok'] and money['equity']['ok'])
        self.assertEqual(money['rows'], 4)
        # The same rows claiming a fresh tick at the rollover: equity should already carry the 0.40.
        fresh = lambda rows: [r[:6] + (r[0],) for r in rows]
        money = rb.money_rows(fresh(original), fresh(retest))
        self.assertFalse(money['equity']['ok'])
        self.assertEqual((money['equity']['first']['row'], money['equity']['first']['swapDifference']), (1, -0.4))
        self.assertTrue(money['balance']['ok'])

    def test_money_boundary_is_a_cent(self):
        for shift, ok in (('0.01', True), ('0.0101', False), ('-0.01', True), ('-0.0101', False)):
            with self.subTest(shift=shift):
                original = [self.row(0, 1000, 1000, 0, 0), self.row(60, 1000, 1000, -2, -2)]
                retest = [self.row(0, 1000, 1000, 0, 0), self.row(60, D(1000) + D(shift), D(1000) + D(shift), -2, -2)]
                money = rb.money_rows(original, retest)
                self.assertEqual((money['balance']['ok'], money['equity']['ok']), (ok, ok))

    def test_rows_that_do_not_line_up_fail_both(self):
        original = [self.row(0, 1000, 1000, 0, 0), self.row(60, 1000, 1000, 0, 0)]
        for retest in ([self.row(0, 1000, 1000, 0, 0)], [self.row(0, 1000, 1000, 0, 0), self.row(60, 1000, 1000, 0, 0, reason='event')]):
            with self.subTest(retest=len(retest)):
                money = rb.money_rows(original, retest)
                self.assertFalse(money['balance']['ok'] or money['equity']['ok'])
                self.assertEqual(money['balance']['first']['row'], 1)
                self.assertIn('different moments', money['balance']['first']['reason'])

    def test_swap_at_a_row_is_every_mark_with_a_smaller_ordinal(self):
        account = [(2, 100, 'event', D(1000), D(1000), 100), (4, 100, 'minute', D(1000), D(999), 100)]
        marks = [(1, 50, '1', D(0), D(0)), (3, 100, '1', D(0), D(-1)), (5, 100, '2', D(-3), D(0))]
        states = list(rb.account_states(account, marks))
        self.assertEqual([(s[4], s[5]) for s in states], [(D(0), D(0)), (D(0), D(-1))])
        self.assertEqual(rb.swap_totals(marks), (D(-3), D(-4)))

    def test_compare_rows_names_the_first_difference(self):
        fields = ('server_time_msc', 'price')
        same = rb.compare_rows([dict(server_time_msc=1, price=D('1.10'))], [dict(server_time_msc=1, price=D('1.1'))], fields)
        self.assertTrue(same['matched'], 'numbers compare exactly, not as text')
        moved = rb.compare_rows([dict(server_time_msc=1, price=D(1))] * 2, [dict(server_time_msc=1, price=D(1)), dict(server_time_msc=2, price=D(1))], fields)
        self.assertEqual((moved['first_difference']['index'], moved['first_difference']['fields']), (1, ['server_time_msc']))
        short = rb.compare_rows([dict(server_time_msc=1, price=D(1))] * 2, [dict(server_time_msc=1, price=D(1))], fields)
        self.assertEqual((short['first_difference']['index'], short['first_difference']['retest']), (1, None))


class ReaderTests(unittest.TestCase):
    """The capture readers: the cut, unchanged marks skipped, a missing or unreadable file is a failed capture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, lines):
        (self.folder / name).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def capture(self):
        self.write('orders.csv', ['ordinal,server_time_msc,sequence_id,direction,order_id,deal_id,retcode,sent,requested_lots,result_lots,result_price',
                                  '7,1000,1,0,2,2,10009,true,0.04,0.04,0.80917', '9,9000,1,0,3,3,10009,true,0.04,0.04,0.8'])
        self.write('deals.csv', ['ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,'
                                 'profit,commission,fee,swap,deal_magic,join_basis', '8,1000,1,2,2,2,0,0,0,0.04,0.80917,0.0,-0.06,0.0,0.0,21058,k'])
        self.write('marks.csv', ['ordinal,server_time_msc,quote_server_time_msc,sequence_id,direction,logical_active,ended,lots,realized_profit,'
                                 'commission,fee,realized_swap,floating_profit,floating_swap,equity_pnl,reason',
                                 '10,1000,1000,1,0,true,false,0.04,0,0,0,0.0,-0.2,0.0,-0.2,event',
                                 '12,2000,1990,1,0,true,false,0.04,0,0,0,0.0,-0.1,0.0,-0.1,minute',
                                 '14,3000,2990,1,0,true,false,0.04,0,0,0,0.0,-0.1,-0.04,-0.14,minute',
                                 '16,9000,8990,1,0,true,false,0.04,0,0,0,0.0,-0.1,-0.08,-0.18,minute'])
        self.write('account.csv', ['ordinal,server_time_msc,quote_server_time_msc,reason,balance,equity,margin,positions,orders,ledger_realized,'
                                   'ledger_floating,balance_residual,equity_residual', '11,1000,1000,event,100000.0,99999.74,1,1,0,0,0,0,0',
                                   '13,2000,1990,minute,100000.0,99999.84,1,1,0,0,0,0,0'])

    def test_a_complete_capture_reads_before_the_cut(self):
        self.capture()
        run = rb.read_run(str(self.folder / 'deals.csv'), [], 5000)
        self.assertEqual(run['missing'], [])
        fields, orders = run['orders']
        self.assertNotIn('ordinal', fields)
        self.assertEqual([o['server_time_msc'] for o in orders], [1000])
        self.assertEqual(run['deals'][0]['price'], D('0.80917'))
        # The 2000 mark repeats the sequence's swap: skipped; the 9000 one is past the cut.
        self.assertEqual([m[:2] for m in run['marks']], [(10, 1000), (14, 3000)])
        self.assertEqual(list(run['account'])[1], (13, 2000, 'minute', D('100000.0'), D('99999.84'), 1990))

    def test_missing_and_unreadable_files_fail_the_capture(self):
        self.capture()
        (self.folder / 'marks.csv').unlink()
        self.write('account.csv', ['ordinal,server_time_msc,reason,balance,equity'])
        run = rb.read_run(str(self.folder / 'deals.csv'), [], 5000)
        self.assertEqual(run['missing'][0], 'marks.csv missing')
        self.assertTrue(run['missing'][1].startswith('account.csv unreadable'))
        self.assertIsNone(run['marks'])
        self.assertEqual(rb.read_run(None, [], 5000)['missing'], [rb.INCOMPLETE])

    def test_a_bounded_reader_refuses_an_oversized_file(self):
        self.capture()
        with mock.patch.object(rb, 'MAX_MARKS_CSV', 10):
            run = rb.read_run(str(self.folder / 'deals.csv'), [], 5000)
        self.assertTrue(run['missing'][0].startswith('marks.csv unreadable'))


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
        self.assertIsNone(result['firstFailingRule'])

    def test_swap_only_drift_within_the_bar_is_rebased(self):
        # From row 50 on the re-test's held position carries 3.00 more swap: equity 3 lower, marks say why.
        result = Scenario(self.root, swap_from=(50, -3)).evaluate()
        self.assertFalse(result['reproduction']['reproduced'])
        self.assertEqual((result['comparison'], result['verdict']), ('comparable_rebased', 'held_up'))
        self.assertTrue(result['comparability']['comparable'] and result['comparability']['identity'])
        self.assertEqual((result['rebase']['decidedBy'], result['rebase']['failed'], result['firstFailingRule']), ('behaviour_rules', [], None))
        self.assertTrue(all(row['ok'] for row in result['rebase']['rules']))
        drift = result['tickHistoryDrift']
        self.assertEqual((drift['cause'], drift['swapDelta'], drift['swapBound'], drift['maxEquityGap']), ('swap_or_spec', -3.0, 37.8, 3.0))   # max(0.025% of 10000, 2% of net 1890)
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')
        self.assertIn('Re-based', result['plain'])
        basis = result['historyBasis']
        self.assertTrue(basis['originalExportedAt'] and basis['retestAt'])
        self.assertEqual((basis['originalEnd'], basis['retestEnd']), (ORIGINAL_END.isoformat(), '2026-10-09'))
        self.assertEqual(result['rebase']['span']['cut'], '%s 23:59' % ORIGINAL_END.isoformat())

    def test_swap_past_the_bar_requalifies_on_swap(self):
        result = Scenario(self.root, swap_from=(50, -300)).evaluate()
        self.assertEqual((result['comparison'], result['verdict'], result['confidence']), ('requalify', 'requalify', 'none'))
        self.assertFalse(result['comparability']['comparable'])
        self.assertEqual((result['rebase']['failed'], result['firstFailingRule']), (['swap', 'max_dd'], 'swap'))
        self.assertEqual((result['firstDifference']['delta'], result['firstDifference']['bound']), (-300.0, 37.8))
        self.assertTrue(result['reasons'][0].startswith('swap: total swap 0.00 vs -300.00'))
        self.assertIn('new candidate', result['plain'])
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')

    def test_money_that_is_not_swap_requalifies_at_its_first_row(self):
        # +3 on the 15:00 dip row with no swap behind it.
        result = Scenario(self.root, alter_history=True, alter_row=43).evaluate()
        self.assertEqual((result['comparison'], result['rebase']['failed'], result['firstFailingRule']), ('requalify', ['equity'], 'equity'))
        first = result['firstDifference']
        self.assertEqual((first['time'], first['difference'], first['swapDifference']), ('2026-03-04 15:00:00.000', 3.0, 0.0))
        self.assertEqual((result['tickHistoryDrift']['cause'], result['tickHistoryDrift']['ddDelta']), ('history_or_behaviour', -3.0))

    def test_a_changed_deal_requalifies(self):
        scenario = Scenario(self.root, swap_from=(50, -3))
        deals = Path(str(scenario.retest)[:-4] + '.goatseq') / 'deals.csv'
        lines = deals.read_text(encoding='utf-8').splitlines()
        stamp = lines[44].split(',')[1]
        lines[44] = lines[44].replace(',' + stamp + ',', ',%d,' % (int(stamp) + 60000), 1)   # the close one minute later
        deals.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = scenario.evaluate()
        self.assertEqual((result['comparison'], result['rebase']['failed'], result['firstFailingRule']), ('requalify', ['deals'], 'deals'))
        self.assertEqual((result['firstDifference']['index'], result['firstDifference']['fields']), (43, ['server_time_msc']))
        self.assertEqual(result['firstFailingCause'], 'deals:fill_timing', 'identical orders, a close filled a minute later')

    def test_identity_mismatch_stays_not_comparable_even_without_reproduction(self):
        result = Scenario(self.root, alter_history=True, retest=dict(server='Other-Demo')).evaluate()
        self.assertEqual((result['comparison'], result['verdict']), ('not_comparable', 'not_comparable'))
        self.assertIsNone(result['tickHistoryDrift'])
        self.assertIsNone(result['rebasedWindows'])

    def test_retest_windows_are_recomputed_on_the_retest_with_no_splice(self):
        scenario = Scenario(self.root, swap_from=(50, -3))
        # The re-test's history differs inside SAMPLE: one close earned 4.1 instead of 5.1 (a new candidate).
        deals = Path(str(scenario.retest)[:-4] + '.goatseq') / 'deals.csv'
        lines = deals.read_text(encoding='utf-8').splitlines()
        lines[44] = lines[44].replace(',5.1,', ',4.1,')   # Mon 2026-01-19 11:01, the first SAMPLE day
        deals.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = scenario.evaluate()
        self.assertEqual((result['comparison'], result['firstFailingRule']), ('requalify', 'deals'))
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
        self.assertEqual((result['comparison'], result['firstFailingRule'], result['firstFailingCause']), ('requalify', 'capture', 'capture:incomplete'))
        self.assertEqual(result['rebasedWindows']['basis'], 'retest')
        self.assertIsNone(result['rebasedWindows']['FOOS']['trades'], 'no capture: trades unknown, never spliced from the header')


class CrossBuildTests(unittest.TestCase):
    """Another build under an ACTIVE equivalence certificate: the same rule, recorded (#1885 6010080246, 6029484888)."""
    PINS = dict(original_ea_sha256='a' * 64, installed_ea_sha256='b' * 64, model=4, server='Test-Demo',
                equivalence=dict(mode='active', export_build=dict(ea_sha256='a' * 64), installed_build=dict(ea_sha256='b' * 64),
                                 valid_at_collect=True, status_at_collect='active', certificate_digest='c' * 64, canary_digest='d' * 64))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def evaluate(self, scenario, pins=PINS):
        return cv.evaluate(read_export(scenario.original), read_export(scenario.retest), new_end=scenario.new_last,
                           tester=TESTER, pins=pins)

    def test_swap_only_drift_across_builds_rebases(self):
        result = self.evaluate(Scenario(self.root, swap_from=(50, -3)))
        self.assertTrue(result['comparability']['identity'], 'the certificate makes the builds the same identity')
        self.assertEqual((result['comparison'], result['verdict'], result['rebase']['crossBuild']), ('comparable_rebased', 'held_up', True))
        self.assertEqual(result['tickHistoryDrift']['cause'], 'swap_or_spec')

    def test_other_drift_across_builds_requalifies_on_its_own_rule(self):
        result = self.evaluate(Scenario(self.root, alter_history=True, alter_row=43))
        self.assertEqual((result['comparison'], result['rebase']['failed'], result['rebase']['crossBuild']), ('requalify', ['equity'], True))

    def test_exact_reproduction_across_builds_stays_comparable(self):
        self.assertEqual(self.evaluate(Scenario(self.root))['comparison'], 'comparable')

    def test_history_basis_names_its_source(self):
        basis = Scenario(self.root, swap_from=(50, -3)).evaluate()['historyBasis']
        self.assertEqual(basis['originalExportedAtBasis'], 'set_mtime')


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
        # Row 43 is the 15:00 dip row of 2026-03-04 (money with no swap behind it).
        rows = [list(r) for r in self.history]
        rows[row][2] += Decimal(str(shift))
        self.histories['EURUSD'] = [tuple(row) for row in rows]

    def swapped(self, amount, row=50):
        # From row 50 on, the re-test's held position carries ``amount`` more swap (marks.csv says so).
        rows = [list(r) for r in self.history]
        for r in rows[row:]:
            r[2] += Decimal(str(amount))
        self.histories['EURUSD'] = [tuple(r) for r in rows]
        self.retest_marks = [(msc(rows[row][0]) - 30000, '2', '0', str(amount))]

    def cycle(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.auto = True
        self.assertEqual(self.runner.start('cu1', 30)['status'], 'completed')
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        version = read_json(Path(member['evidence_dir']) / 'evidence-version.json')
        return version, self.runner.report('cu1')['members'][0]['summary']

    def test_rebased_stamps_on_version_summary_and_import(self):
        self.swapped(-3)
        version, summary = self.cycle()
        for record in (version, summary, version['catch_up']):
            self.assertEqual(record['comparison'], 'comparable_rebased')
            self.assertEqual(record['tickHistoryDrift']['maxEquityGap'], 3.0)
            self.assertEqual(record['tickHistoryDrift']['dealCountDelta'], 0)
            self.assertEqual((record['tickHistoryDrift']['cause'], record['tickHistoryDrift']['swapDelta']), ('swap_or_spec', -3.0))
            self.assertEqual(set(record['historyBasis']) >= {'originalExportedAt', 'retestAt'}, True)
        self.assertEqual((version['verdict']['verdict'], summary['comparable'], summary['reproduced']), ('held_up', True, False))
        self.assertEqual((summary['firstFailingRule'], summary['firstDifference']), (None, None))
        stamp = version['catch_up']
        self.assertIsNone(stamp['original_foos'])
        self.assertEqual((stamp['windowsBasis'], stamp['windows']['FOOS']['from'], stamp['windows']['FOOS']['to']),
                         ('retest', '2026-08-28', '2026-10-02'))
        self.assertEqual(version['rebasedWindows'], stamp['windows'])
        self.assertEqual((version['rebase']['verdict'], version['rebase']['schema']), ('comparable_rebased', 'goat-catchup-rebase-v2'))
        self.assertEqual(version['oos_rule']['status'], 'not_applicable')   # explicit (non-formula) dates in this harness
        # A re-based version carries the export to the shared end like an exact one.
        scan = sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)
        self.assertEqual(scan['summary']['counts']['caught_up'], 1)

    def test_requalify_stamps_the_first_failing_rule_and_carries_nothing(self):
        self.drifted(-300)
        version, summary = self.cycle()
        self.assertEqual((summary['verdict'], summary['comparison'], summary['comparable']), ('requalify', 'requalify', False))
        self.assertEqual(version['rebase']['failed'], ['equity', 'max_dd'])
        # The receipt and the evidence-version both log the first failing rule and its first differing row.
        self.assertEqual((summary['firstFailingRule'], version['rebase']['firstFailingRule']), ('equity', 'equity'))
        self.assertEqual(summary['firstDifference']['time'], '2026-03-04 15:00:00.000')
        self.assertEqual(version['rebase']['firstDifference'], summary['firstDifference'])
        self.assertEqual((version['catch_up']['candidate'], version['catch_up']['carriesStatus']), ('new', False))
        self.assertEqual(version['tickHistoryDrift']['ddDelta'], 300.0)
        scan = sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)
        row = scan['exports'][0]
        self.assertEqual((row['status'], row['previous_attempt']['verdict']), ('behind', 'requalify'))

    def test_swap_past_the_bar_requalifies_on_swap(self):
        self.swapped(-60)
        version, summary = self.cycle()
        self.assertEqual((summary['comparison'], summary['firstFailingRule'], version['rebase']['failed']), ('requalify', 'swap', ['swap']))
        self.assertEqual((summary['firstDifference']['delta'], summary['firstDifference']['bound']), (-60.0, 37.8))
        self.assertEqual(summary['firstFailingCause'], 'swap')

    def test_exact_reproduction_stamps_comparable(self):
        version, summary = self.cycle()
        self.assertEqual((version['comparison'], summary['comparison'], version['catch_up']['comparison']), ('comparable',) * 3)
        self.assertIsNone(version['tickHistoryDrift'])
        self.assertIsNone(summary['historyBasis'])
        self.assertIsNone(summary['firstFailingRule'])
        self.assertEqual(version['catch_up']['windowsBasis'], 'original')


class RedactionTests(unittest.TestCase):
    def test_drift_and_rebased_windows_are_redacted_inside_a_lock(self):
        from studio_heldout_guard import METRIC_KEYS
        self.assertLessEqual({'rebase', 'tickHistoryDrift', 'rebasedWindows', 'firstDifference'}, METRIC_KEYS)


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
