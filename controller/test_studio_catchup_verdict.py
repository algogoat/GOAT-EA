from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import studio_catchup_verdict as cv
from studio_evidence import read_export, server_msc

VALUES = dict(Mode_Operation='9', Lots_Input='0.05', Grid_Size='-2.25')


def msc(moment):
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def daily(first, last, start, per_day, *, dips=()):
    """One equity row per weekday at 10:00, plus an intraday dip row on the given days."""
    rows, value, day, dips = [], Decimal(str(start)), first, dict(dips)
    while day <= last:
        if day.weekday() < 5:
            value += Decimal(str(per_day))
            rows.append((datetime.combine(day, time(10)), value, value))
            if day in dips:
                rows.append((datetime.combine(day, time(15)), value, value - Decimal(str(dips[day]))))
                rows.append((datetime.combine(day, time(16)), value, value))
        day += timedelta(days=1)
    return rows


def trading(first, last, per_day, result):
    """Entry at 09:00 and close at 11:00, ``per_day`` times per weekday, each close earning ``result``."""
    deals, day = [], first
    while day <= last:
        if day.weekday() < 5:
            for n in range(per_day):
                deals.append((msc(datetime.combine(day, time(9, n))), '0', '0.0', '-0.1'))
                deals.append((msc(datetime.combine(day, time(11, n))), '1', str(result), '-0.1'))
        day += timedelta(days=1)
    return deals


def window_line(kind, first, last, trades, pl):
    return '; %-7s %s-%s Days=%d Trades=%d PL=%d' % (kind + ':', first.strftime('%Y.%m.%d'), last.strftime('%Y.%m.%d'),
                                                    max(1, (last - first).days * 5 // 7), trades, pl)


def make_unit(folder, *, rows, deals=(), alias='R0001', symbol='EURUSD', period='M1', values=None, start=date(2026, 1, 5),
              requested_to=None, observed_end=None, capture=True, complete=True, windows=(), run_id='export-1', initial=10000,
              server='Test-Demo', name_metrics='Trds=100_Prf=500_DD=50_PF=1.5_SR=3_ARF=0.5', build_id='TEST', model=4):
    """Write one export unit (SET + equity CSV + optional .goatseq) the way the EA lays it out."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = 'GOAT V1.49 %s,%s_%s' % (symbol, period, name_metrics)
    lines = ['; ' + '-' * 40, '; GOAT V1.49 %s,%s' % (symbol, period)] + [window_line(*w) for w in windows] + ['; ' + '-' * 40]
    values = dict(VALUES if values is None else values)
    body = [lines[0]] + lines[1:] + ['Mode_Operation=' + values.pop('Mode_Operation', '9'), 'EA_Desc=' + alias] + ['%s=%s' % kv for kv in values.items()]
    set_raw = ('\r\n'.join(body) + '\r\n').encode('utf-16')
    (folder / (stem + '.set')).write_bytes(set_raw)
    csv_lines = ['<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'] + ['%s\t%s\t%s\t0.0' % (r[0].strftime('%Y.%m.%d %H:%M'), r[1], r[2]) for r in rows]
    (folder / (stem + '.csv')).write_bytes(('\r\n'.join(csv_lines) + '\r\n').encode('utf-16'))
    if capture:
        package = folder / (stem + '.goatseq')
        package.mkdir()
        requested_to = requested_to or (rows[-1][0].date() + timedelta(days=1))
        observed_end = observed_end or msc(datetime.combine(requested_to, time()) - timedelta(seconds=2))
        manifest = dict(schemaVersion='goat-sequence-export-v1', status='complete-awaiting-import-verification' if complete else 'incomplete',
                        reason='' if complete else '2000000 row resource limit exceeded', runId=run_id, asset=symbol, buildId=build_id, model=model,
                        currency='USD', initialEquity=initial, leverage=100, timeBasis=dict(kind='broker-server', server=server),
                        requestedPeriod=dict(startServerMsc=server_msc(start), endServerMsc=server_msc(requested_to)),
                        observedPeriod=dict(startServerMsc=server_msc(start), endServerMsc=observed_end),
                        exports=dict(set=dict(path='../' + stem + '.set', sha256=hashlib.sha256(set_raw).hexdigest(), bytes=len(set_raw))))
        (package / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (package / 'completion.csv').write_text('key,value\ncapture_status,%s\n' % ('complete-awaiting-external-reconciliation' if complete else 'incomplete'), encoding='utf-8')
        (package / 'run.csv').write_text('key,value\nrun_id,%s\nserver,%s\n' % (run_id, server), encoding='utf-8')
        (package / 'source-inputs.set').write_text('Grid_Size=-2.25\n', encoding='utf-8')
        header = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,profit,commission,fee,swap,deal_magic,join_basis'
        # trading() writes entry/close pairs, so each pair shares one position id.
        body = [header] + ['%d,%d,1,%d,%d,%d,1,1,%s,0.05,1.1,%s,%s,0.0,0.0,1,known' % (i, stamp, i, i, (i + 1) // 2, entry, profit, fee)
                           for i, (stamp, entry, profit, fee) in enumerate(deals, 1)]
        (package / 'deals.csv').write_text('\n'.join(body) + '\n', encoding='utf-8')
    return folder / (stem + '.set')


ORIGINAL_END = date(2026, 9, 24)
TESTER = dict(FromDate='2026.01.19', ToDate='2026.08.28', ForwardDate='2026.07.17')


class Scenario:
    """An original export ending Thu 2026-09-24 and its re-test to Fri 2026-10-09 (11 new weekdays)."""

    def __init__(self, root, *, new_per_day=10, new_trades=2, new_result=6.0, dips_new=(), new_last=date(2026, 10, 9),
                 retest_capture=True, retest_complete=True, change_inputs=False, alter_history=False, retest=None, tail_drop=None):
        history = daily(date(2026, 1, 5), ORIGINAL_END, 10000, 10, dips=[(date(2026, 3, 4), 120)])
        if tail_drop:   # the original ends in a drawdown already under way: its last three rows sit tail_drop below the peak
            low = history[-4][2] - Decimal(str(tail_drop))
            history[-3:] = [(stamp, low, low) for stamp, _, _ in history[-3:]]
        history_deals = trading(date(2026, 1, 5), ORIGINAL_END, 2, 5.1)
        forced = (datetime.combine(ORIGINAL_END, time(23, 59)), history[-1][1], history[-1][2])
        foos = [('BOOS', date(2026, 1, 5), date(2026, 1, 19), 20, 100), ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300)]
        self.original = make_unit(Path(root) / 'original', rows=history + [forced], deals=history_deals,
                                  windows=foos + [('FOOS', date(2026, 8, 29), ORIGINAL_END, 38, 190)])
        new_rows = daily(ORIGINAL_END + timedelta(days=1), new_last, history[-1][2], new_per_day, dips=dips_new)
        retest_history = [list(r) for r in history]
        if alter_history:
            retest_history[50][2] += Decimal('3')
        new_trades_list = trading(ORIGINAL_END + timedelta(days=1), new_last, new_trades, new_result)
        new_count = sum(entry == '0' for _, entry, _, _ in new_trades_list)
        values = dict(VALUES, Grid_Size='-3.0') if change_inputs else None
        self.retest = make_unit(Path(root) / 'retest', rows=[tuple(r) for r in retest_history] + new_rows, alias='C0001',
                                deals=history_deals + new_trades_list, capture=retest_capture, complete=retest_complete, values=values, **(retest or {}),
                                windows=foos + [('FOOS', date(2026, 8, 29), new_last, 38 + new_count, 190)])
        self.new_last = new_last

    def evaluate(self, tester=TESTER):
        return cv.evaluate(read_export(self.original), read_export(self.retest), new_end=self.new_last, tester=tester)


class DecideTests(unittest.TestCase):
    PACE = dict(net_per_day=10.0)

    def new(self, **kw):
        base = dict(trades=10, net=60.0, dd=20.0, pf=1.5, weekdays=5)
        return base | kw

    def test_rule_table(self):
        cases = [
            (self.new(), 100, 'held_up'),
            (self.new(dd=150), 100, 'failed'),                      # new worst drawdown
            (self.new(trades=2, dd=150), 100, 'failed'),            # even with few trades
            (self.new(net=-40, pf=0.6), 100, 'failed'),
            (self.new(net=-10, pf=0.9), 100, 'weakened'),
            (self.new(trades=3, net=-40, pf=0.2), 100, 'too_few_trades'),
            (self.new(trades=None), 100, 'too_few_trades'),
            (self.new(net=10), 100, 'weakened'),                    # 2/day vs 10/day forward pace
            (self.new(net=30), 100, 'held_up'),                     # exactly half the pace
            (self.new(net=60, pf=0.95), 100, 'weakened'),
            (self.new(net=0), 100, 'weakened'),
            (self.new(net=-60, pf=None), 100, 'failed'),            # no pf: lost more than 5 days of pace
            (self.new(net=-20, pf=None), 100, 'weakened'),
        ]
        for new, prior, expected in cases:
            with self.subTest(new=new):
                self.assertEqual(cv.decide(new, prior, self.PACE)[0], expected)

    def test_rules_are_defaults_with_bounded_overrides(self):
        self.assertEqual(cv.validate_rules(), cv.DEFAULT_RULES)
        loose = cv.validate_rules(dict(min_trades=2, held_pace=0.25))
        self.assertEqual((loose['min_trades'], loose['held_pace'], loose['failed_pf'], loose['overridden']), (2, 0.25, 0.8, ['held_pace', 'min_trades']))
        self.assertEqual(loose['id'], 'goat-catchup-verdict-v2')
        for bad in (dict(min_trades=0), dict(min_trades=2.5), dict(failed_pf=3), dict(held_pace=True), dict(score=1), [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cv.validate_rules(bad)
        # Rules are not rigid: the same numbers judged under a looser trade floor and pace.
        few = self.new(trades=3, net=15.0)  # 3/day: below the default half pace (5/day), above a quarter (2.5/day)
        self.assertEqual(cv.decide(few, 100, self.PACE)[0], 'too_few_trades')
        self.assertEqual(cv.decide(few, 100, self.PACE, loose)[0], 'held_up')

    def test_held_up_needs_a_known_profit_factor_and_enough_trades_for_its_pace(self):
        self.assertEqual(cv.decide(self.new(pf=None, pf_note='needs a complete capture'), 100, self.PACE)[0], 'weakened')
        self.assertEqual(cv.decide(self.new(pf=None, pf_note='no losing deals'), 100, self.PACE)[0], 'held_up')
        self.assertEqual(cv.decide(self.new(pf=None), 100, None)[0], 'weakened', 'an unknown forward pace never waives the PF')
        slow = self.new(trades=6, expected_trades_at_forward_pace=30.0)
        self.assertEqual(cv.decide(slow, 100, self.PACE)[0], 'weakened')
        self.assertIn('expected at the forward pace', cv.decide(slow, 100, self.PACE)[1][0])
        self.assertEqual(cv.decide(self.new(trades=9, expected_trades_at_forward_pace=30.0), 100, self.PACE)[0], 'held_up')

    def test_losing_forward_window_caps_at_weakened(self):
        # Claude-Mac round 2: +1 after a losing forward window is a recovery, never "held up".
        verdict, reasons = cv.decide(self.new(net=1), 100, dict(net_per_day=-3.0))
        self.assertEqual(verdict, 'weakened')
        self.assertIn('forward window lost (-3.0/day); profitable since', reasons[0])
        self.assertEqual(cv.decide(self.new(net=500), 100, dict(net_per_day=0.0))[0], 'weakened', 'a flat forward window too')
        self.assertEqual(cv.decide(self.new(net=-60, pf=0.5), 100, dict(net_per_day=-3.0))[0], 'failed', 'losses still fail')
        # No forward window measured at all: nothing to compare, the other rules decide.
        self.assertEqual(cv.decide(self.new(net=1), 100, None)[0], 'held_up')

    def test_losing_forward_window_in_a_full_evaluation(self):
        # The forward window (Tue 22 to Thu 24 Sep) lost 70; the new weeks then made a little.
        result = Scenario(Path(tempfile.mkdtemp()), new_per_day=2, tail_drop=70).evaluate(tester=dict(TESTER, ForwardDate='2026.09.22', ToDate='2026.09.25'))
        self.assertLess(result['forward_pace']['net_per_day'], 0)
        self.assertEqual(result['verdict'], 'weakened')
        self.assertIn('Forward window lost (-23.3/day); profitable since', result['plain'])


class MeasureTests(unittest.TestCase):
    def test_window_uses_opening_equity_and_floating_dips(self):
        rows = daily(date(2026, 9, 21), date(2026, 10, 2), 1000, 10, dips=[(date(2026, 9, 30), 35)])
        measured = cv.equity_window(rows, date(2026, 9, 28), date(2026, 10, 2))
        self.assertEqual((measured['weekdays'], measured['open_equity'], measured['close_equity'], measured['net']), (5, 1050.0, 1100.0, 50.0))
        self.assertEqual(measured['dd'], 35.0)
        self.assertEqual(cv.prior_drawdown(rows, date(2026, 9, 28)), 0.0)
        self.assertEqual(cv.prior_drawdown(rows, date(2026, 10, 3)), 35.0)

    def test_drawdown_already_under_way_is_carried_in(self):
        # Claude-Mac's probe: peak 1000, down 80 before the window (the prior worst), then 66 more inside it.
        rows = [(datetime(2026, 9, 21, 10), Decimal(1000), Decimal(1000)), (datetime(2026, 9, 24, 10), Decimal(920), Decimal(920)),
                (datetime(2026, 9, 28, 10), Decimal(890), Decimal(890)), (datetime(2026, 9, 30, 10), Decimal(854), Decimal(854))]
        carried = cv.equity_window(rows, date(2026, 9, 25), date(2026, 10, 2), carry_peak=True)
        self.assertEqual((carried['dd'], carried['dd_from_open'], carried['dd_basis']), (146.0, 66.0, 'running_peak_incl_prior'))
        prior = cv.prior_drawdown(rows, date(2026, 9, 25))
        self.assertEqual(prior, 80.0)
        new = dict(carried, trades=10, pf=0.9)
        self.assertEqual(cv.decide(new, prior, None)[0], 'failed')
        self.assertEqual(cv.decide(dict(new, dd=carried['dd_from_open']), prior, None)[0], 'weakened', 'the old open-based DD missed it')

    def test_pf_counts_only_positions_opened_in_the_window(self):
        folder = Path(tempfile.mkdtemp())
        header = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,profit,commission,fee,swap,deal_magic,join_basis'
        stamp = lambda day, hour: msc(datetime(2026, 9, day, hour))
        rows = [(stamp(24, 9), 7, '0', '0'), (stamp(28, 9), 7, '1', '-90'),           # opened before, closed inside at a loss
                (stamp(28, 10), 8, '0', '0'), (stamp(28, 11), 8, '1', '30'), (stamp(29, 10), 9, '0', '0'), (stamp(29, 11), 9, '1', '-10')]
        (folder / 'deals.csv').write_text('\n'.join([header] + ['%d,%d,1,%d,%d,%d,1,1,%s,0.1,1,%s,0,0,0,1,k' % (i, s, i, i, p, e, r)
                                                                for i, (s, p, e, r) in enumerate(rows, 1)]) + '\n', encoding='utf-8')
        window = cv.deal_window(folder / 'deals.csv', date(2026, 9, 25), date(2026, 10, 2))
        self.assertEqual((window['entries'], window['closes'], window['closes_of_earlier_positions'], window['pf']), (2, 3, 1, 3.0))

    def test_reproduction_ignores_the_forced_final_minute_only(self):
        rows = daily(date(2026, 9, 21), date(2026, 9, 25), 1000, 10)
        original = rows + [(datetime(2026, 9, 25, 23, 59), Decimal(990), Decimal(990))]
        retest = rows + daily(date(2026, 9, 28), date(2026, 10, 2), 1050, 5)
        self.assertTrue(cv.reproduction(original, retest)['reproduced'])
        changed = [rows[0], (rows[1][0], rows[1][1], rows[1][2] + 1)] + rows[2:]
        result = cv.reproduction(original, changed)
        self.assertFalse(result['reproduced'])
        self.assertEqual(result['first_difference']['row'], 3)
        self.assertFalse(cv.reproduction(original, rows[:3])['reproduced'])


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_held_up_with_measured_forward_pace(self):
        result = Scenario(self.root).evaluate()
        self.assertEqual(result['verdict'], 'held_up')
        new = result['new_weeks']
        self.assertEqual((new['first_day'], new['last_day'], new['weekdays'], new['trades'], new['closes']), ('2026-09-25', '2026-10-09', 11, 22, 22))
        self.assertEqual(new['net'], 110.0)
        self.assertEqual(new['trade_source'], 'capture_deals')
        self.assertGreater(new['pf'], 1)
        self.assertTrue(result['reproduction']['reproduced'])
        self.assertTrue(result['inputs_match'])
        self.assertEqual(result['forward_pace']['first_day'], '2026-07-17')
        self.assertEqual(result['forward_pace']['last_day'], '2026-08-27')
        self.assertEqual(result['forward_pace']['net_per_day'], 10.0)
        self.assertEqual(result['prior_dd'], 120.0)
        self.assertEqual(result['confidence'], 'moderate')
        self.assertIn('Held up over the new weeks 2026-09-25 to 2026-10-09', result['plain'])
        self.assertEqual(result['schema'], 'goat-catchup-verdict-v2')
        # Stamped for a later scored qualification: the exact rules and the raw signals.
        self.assertEqual(result['rules'], cv.DEFAULT_RULES)
        signals = result['signals']
        self.assertEqual((signals['schema'], signals['weekdays'], signals['trades'], signals['expected_trades']), ('goat-catchup-signals-v2', 11, 22, 22.0))
        self.assertEqual((signals['trades_vs_pace'], signals['pace_ratio'], signals['net_per_day'], signals['forward_net_per_day']), (1.0, 1.0, 10.0, 10.0))
        self.assertEqual((signals['dd_vs_prior'], signals['prior_dd'], signals['reproduced'], signals['capture_complete']), (0.0, 120.0, True, True))

    def test_overridden_rules_are_stamped(self):
        rules = cv.validate_rules(dict(min_trades=1))
        scenario = Scenario(self.root, new_last=date(2026, 9, 28), new_trades=1)
        result = cv.evaluate(read_export(scenario.original), read_export(scenario.retest), new_end=scenario.new_last, tester=TESTER, rules=rules)
        self.assertEqual(result['verdict'], 'held_up')
        self.assertEqual(result['rules']['overridden'], ['min_trades'])

    def test_new_worst_drawdown_fails(self):
        result = Scenario(self.root, dips_new=[(date(2026, 10, 1), 400)]).evaluate()
        self.assertEqual(result['verdict'], 'failed')
        self.assertIn('worst drawdown already shown', result['reasons'][0])

    def test_drawdown_under_way_before_the_new_weeks_counts(self):
        # Down 70 from the peak at the original's end, then 80 more on the first new day: 140 from the peak beats the prior 120.
        result = Scenario(self.root, tail_drop=70, dips_new=[(date(2026, 9, 25), 80)]).evaluate()
        new = result['new_weeks']
        self.assertEqual((new['dd'], new['dd_from_open'], new['dd_basis'], result['prior_dd']), (140.0, 80.0, 'running_peak_incl_prior', 120.0))
        self.assertEqual(result['verdict'], 'failed')
        self.assertIn('140 from the peak vs 120 before', result['reasons'][0])

    def test_few_trades_is_too_few_to_judge(self):
        result = Scenario(self.root, new_last=date(2026, 9, 28), new_trades=1).evaluate()
        self.assertEqual(result['verdict'], 'too_few_trades')
        self.assertEqual(result['new_weeks']['trades'], 2)
        self.assertEqual(result['new_weeks']['expected_trades_at_forward_pace'], 4.0)
        self.assertEqual(result['confidence'], 'low')
        self.assertIn('about 4 expected at the forward pace', result['plain'])

    def test_losing_weeks_fail_on_profit_factor(self):
        result = Scenario(self.root, new_per_day=-12, new_result=-6.0).evaluate()
        self.assertEqual(result['verdict'], 'failed')
        self.assertLess(result['new_weeks']['pf'], cv.FAILED_PF)

    def test_slow_profit_is_weakened(self):
        result = Scenario(self.root, new_per_day=2).evaluate()
        self.assertEqual(result['verdict'], 'weakened')
        self.assertIn('forward profit pace', result['reasons'][0])

    def test_incomplete_capture_uses_header_difference(self):
        result = Scenario(self.root, retest_complete=False).evaluate()
        new = result['new_weeks']
        self.assertEqual((new['trade_source'], new['trades'], new['pf']), ('set_header_difference', 22, None))
        # Without a capture the profit factor is unknown, so the weeks cannot be called held up.
        self.assertEqual(result['verdict'], 'weakened')
        self.assertIn('profit factor is unknown', result['reasons'][0])

    def test_header_difference_needs_reproduction(self):
        result = Scenario(self.root, retest_complete=False, alter_history=True).evaluate()
        self.assertFalse(result['reproduction']['reproduced'])
        self.assertIsNone(result['new_weeks']['trades'])
        self.assertEqual((result['verdict'], result['confidence']), ('not_comparable', 'none'))
        self.assertIn('not the same test as the original', result['plain'])

    def test_changed_inputs_are_not_comparable(self):
        result = Scenario(self.root, change_inputs=True).evaluate()
        self.assertEqual(result['verdict'], 'not_comparable')
        self.assertFalse(result['inputs_match'])

    def test_forward_window_falls_back_to_the_set_header(self):
        result = Scenario(self.root).evaluate(tester=None)
        self.assertEqual(result['forward_pace']['first_day'], '2026-07-17')
        self.assertEqual(result['verdict'], 'held_up')

    def test_a_different_build_deposit_or_server_is_not_comparable(self):
        # Claude-Mac's probe: a re-test on another EA build must never say held_up, at any confidence.
        for name, change in (('ea_build', dict(build_id='OTHER-BUILD')), ('deposit', dict(initial=20000)), ('server', dict(server='Other-Demo'))):
            with self.subTest(change=name):
                result = Scenario(self.root / name, retest=change).evaluate()
                self.assertEqual((result['verdict'], result['confidence']), ('not_comparable', 'none'))
                failed = [item['check'] for item in result['comparability']['checks'] if not item['ok']]
                self.assertEqual(failed, [name])
                self.assertIn('not the same test as the original', result['plain'])
        same = Scenario(self.root / 'same').evaluate()
        self.assertTrue(same['comparability']['comparable'])
        self.assertIn('symbol_spec', same['comparability'])

    def test_unknown_original_build_is_not_comparable(self):
        scenario = Scenario(self.root)
        original, retest = read_export(scenario.original), read_export(scenario.retest)
        original['capture'] = dict(original['capture'], build_id=None)
        retest['capture'] = dict(retest['capture'], build_id=None)
        result = cv.evaluate(original, retest, new_end=scenario.new_last, tester=TESTER)
        self.assertEqual(result['verdict'], 'not_comparable')
        pinned = cv.evaluate(original, retest, new_end=scenario.new_last, tester=TESTER,
                             pins=dict(original_ea_sha256='a' * 64, installed_ea_sha256='a' * 64, model=4, server='Test-Demo'))
        self.assertEqual(pinned['verdict'], 'held_up', 'the run manifest binary hash proves the same build')

    def test_low_confidence_is_in_the_sentence(self):
        result = Scenario(self.root, new_last=date(2026, 9, 30)).evaluate()
        self.assertEqual(result['confidence'], 'low')
        self.assertIn('Low confidence: 8 trades over 4 trading days.', result['plain'])
        self.assertIn('Moderate confidence', Scenario(self.root / 'long').evaluate()['plain'])

    def test_end_must_follow_the_original(self):
        scenario = Scenario(self.root)
        with self.assertRaisesRegex(ValueError, 'not after'):
            cv.evaluate(read_export(scenario.original), read_export(scenario.retest), new_end='2026-09-24')


if __name__ == '__main__':
    unittest.main()
