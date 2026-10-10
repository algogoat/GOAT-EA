"""goat-export-window-metrics-v1: exact preFoos / selectionWindow metrics from an export unit."""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import studio_window_metrics as wm
from studio_catchup_verdict import equity_window, equity_rows

# O = 13 weeks at export Friday 2026-10-02: BOOS 2026-04-18..06-05, SAMPLE 06-06..07-31, FWD 08-01..09-04, FOOS 09-05..10-02.
TESTER = dict(from_date='2026.06.06', to_date='2026.09.05', back_oos_date='2026.04.18', include_back_oos=True)
STEM = 'GOAT V1.49 EURUSD,M1_Trds=60_Prf=100_DD=50_PF=1.50_SR=2.60_ARF=0.250'


def d(text):
    return date.fromisoformat(text)


def msc(day, hour):
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000) + hour * 3600 * 1000


class Unit:
    """One export unit: SET (with window header lines), equity CSV and an optional complete capture."""

    def __init__(self, root, *, equity, deals=None, header=None):
        self.root = Path(root)
        self.set_path = self.root / (STEM + '.set')
        lines = ['; GOAT export', 'EA_Desc=R0@{mode=EXPORT}'] + (header or []) + ['Lots_Input=0.1']
        raw = ('\r\n'.join(lines) + '\r\n').encode('utf-16')
        self.set_path.write_bytes(raw)
        csv_lines = [wm.HEADER] + ['%s\t%.2f\t%.2f\t0.0' % (stamp.strftime('%Y.%m.%d %H:%M'), value, value) for stamp, value in equity]
        (self.root / (STEM + '.csv')).write_text('\n'.join(csv_lines) + '\n', encoding='utf-8')
        if deals is not None:
            seq = self.root / (STEM + '.goatseq')
            seq.mkdir()
            manifest = dict(schemaVersion='goat-sequence-export-v1', status='complete-awaiting-import-verification',
                            requestedPeriod=dict(startServerMsc=1, endServerMsc=2), observedPeriod=dict(startServerMsc=1, endServerMsc=2),
                            exports=dict(set=dict(sha256=hashlib.sha256(raw).hexdigest())))
            (seq / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (seq / 'completion.csv').write_text('key,value\ncapture_status,complete\n', encoding='utf-8')
            with (seq / 'deals.csv').open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['server_time_msc', 'position_id', 'deal_entry', 'deal_type', 'lots',
                                                            'price', 'profit', 'commission', 'fee', 'swap'])
                writer.writeheader()
                writer.writerows(deals)


def weekdays(first, last):
    day, out = d(first), []
    while day <= d(last):
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def series(first, last, start=10000.0, step=10.0, dips=None):
    """One noon sample per weekday rising by ``step``; ``dips`` maps a day to a 13:00 dip below it."""
    rows, value = [], start
    for day in weekdays(first, last):
        value += step
        rows.append((datetime.combine(day, datetime.min.time()) + timedelta(hours=12), value))
        if dips and day in dips:
            rows.append((datetime.combine(day, datetime.min.time()) + timedelta(hours=13), value - dips[day]))
    return rows


def trade(position, day, profit, commission=0.0, swap=0.0):
    return [dict(server_time_msc=msc(day, 9), position_id=position, deal_entry=0, deal_type=0, lots=0.1, price=1.1,
                 profit=0, commission=commission, fee=0, swap=0),
            dict(server_time_msc=msc(day, 10), position_id=position, deal_entry=1, deal_type=1, lots=0.1, price=1.1,
                 profit=profit, commission=commission, fee=0, swap=swap)]


class WindowMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def unit(self, **kwargs):
        return Unit(self.root, **kwargs)

    def test_windows_and_deal_metrics_with_costs(self):
        dips = {d('2026-05-05'): 80.0, d('2026-06-16'): 50.0, d('2026-09-15'): 400.0}
        equity = series('2026-04-18', '2026-10-02', dips=dips)
        deals = []
        deals += trade(1, d('2026-05-04'), 30.0, commission=-1.0)            # BOOS: net 28
        deals += trade(2, d('2026-06-10'), -20.0, swap=-0.5)                 # SAMPLE: net -20.5
        deals += trade(3, d('2026-08-12'), 50.0, commission=-1.0)            # FWD: net 48
        deals += trade(4, d('2026-09-14'), -300.0)                           # FOOS: must not count before FOOS
        unit = self.unit(equity=equity, deals=deals)
        result = wm.export_window_metrics(unit.set_path, **TESTER)
        pre, sel, full = result['preFoos'], result['selectionWindow'], result['fullExport']
        self.assertEqual((pre['from'], pre['to'], sel['from'], sel['to']), ('2026-04-18', '2026-09-04', '2026-06-06', '2026-09-04'))
        self.assertEqual((result['optimizationEnd'], result['foosStart']), ('2026-09-04', '2026-09-05'))
        self.assertEqual((pre['trades'], sel['trades'], full['trades']), (3, 2, 4))
        self.assertAlmostEqual(pre['profit'], 28 - 20.5 + 48)
        self.assertAlmostEqual(sel['profit'], -20.5 + 48)
        # Deal level, all costs: exits +29 and +49; entry commissions -1 and -1, exit -20.5.
        self.assertAlmostEqual(pre['pf'], (29 + 49) / (1 + 20.5 + 1))
        self.assertEqual(pre['tradeSource'], 'capture_deals')
        # Equity drawdowns: the FOOS dip of 400 is outside both pre-FOOS windows.
        self.assertEqual((pre['maxDd'], sel['maxDd'], full['maxDd']), (80.0, 50.0, 400.0))
        self.assertAlmostEqual(pre['recoveryFactor'], pre['profit'] / 80.0)
        self.assertTrue(set(wm.FIELDS) <= set(pre))

    def test_drawdown_is_the_oos_evaluators_definition(self):
        dips = {d('2026-06-16'): 50.0, d('2026-07-07'): 75.0}
        equity = series('2026-04-18', '2026-10-02', dips=dips)
        unit = self.unit(equity=equity)
        result = wm.export_window_metrics(unit.set_path, **TESTER)
        rows = equity_rows(str(self.root / (STEM + '.csv')))
        for key, first in (('selectionWindow', '2026-06-06'), ('preFoos', '2026-04-18')):
            reference = equity_window(rows, d(first), d('2026-09-04'), carry_peak=False)['dd']
            self.assertAlmostEqual(result[key]['maxDd'], reference)

    def test_drawdown_peak_starts_at_the_opening_equity(self):
        noon = lambda text: datetime.combine(d(text), datetime.min.time()) + timedelta(hours=12)
        rows = [(noon('2026-06-05'), 10000.0), (noon('2026-06-08'), 9900.0), (noon('2026-06-09'), 9950.0), (noon('2026-06-10'), 10100.0)]
        metrics = wm.equity_metrics(rows, d('2026-06-06'), d('2026-06-10'))
        self.assertEqual((metrics['maxDd'], metrics['equityNet']), (100.0, 100.0))
        self.assertAlmostEqual(metrics['ddPct'], 1.0)
        reference = equity_window([(s, Decimal(str(v)), Decimal(str(v))) for s, v in rows], d('2026-06-06'), d('2026-06-10'))
        self.assertEqual(reference['dd'], 100.0)

    def test_header_fallback_without_a_capture(self):
        header = ['; BOOS: 2026.04.18-2026.06.05 Days=35 Trades=12 PL=100.5',
                  '; SAMPLE: 2026.06.06-2026.07.31 Days=40 Trades=20 PL=-30',
                  '; FWD: 2026.08.01-2026.09.04 Days=25 Trades=9 PL=44',
                  '; FOOS: 2026.09.05-2026.10.02 Days=20 Trades=7 PL=-90']
        unit = self.unit(equity=series('2026-04-18', '2026-10-02'), header=header)
        result = wm.export_window_metrics(unit.set_path, **TESTER)
        self.assertEqual((result['preFoos']['trades'], result['preFoos']['profit'], result['preFoos']['tradeSource']), (41, 114.5, 'set_header'))
        self.assertEqual((result['selectionWindow']['trades'], result['selectionWindow']['profit']), (29, 14.0))
        self.assertIsNone(result['preFoos']['pf'])
        # A header that does not cover the window exactly is not used.
        unit2 = Unit(Path(tempfile.mkdtemp(dir=self.root)), equity=series('2026-04-18', '2026-10-02'), header=header[1:2])
        self.assertIsNone(wm.export_window_metrics(unit2.set_path, **TESTER)['selectionWindow']['trades'])

    def test_header_sum_never_counts_fwd_twice_when_sample_covers_it(self):
        # goatai#2350 6099037325 / 6099055333: the EA's SAMPLE line spans in-sample + forward (FWD is counted in both), as
        # in the B43 canary b43mig-0b (AUDCAD, V1.47): 25 + 160 + 40 + 24 = 249 summed, 209 / 396 true.
        header = ['; BOOS: 2026.02.02-2026.03.02 Days=20 Trades=25 PL=42',
                  '; SAMPLE: 2026.03.02-2026.08.15 Days=120 Trades=160 PL=286',
                  '; FWD: 2026.06.20-2026.08.14 Days=39 Trades=40 PL=62',
                  '; FOOS: 2026.08.15-2026.09.17 Days=24 Trades=24 PL=68']
        tester = dict(from_date='2026.03.02', to_date='2026.08.15', back_oos_date='2026.02.02', include_back_oos=True)
        unit = self.unit(equity=series('2026-02-02', '2026-09-17'), header=header)
        result = wm.export_window_metrics(unit.set_path, **tester)
        self.assertEqual((result['fullExport']['trades'], result['fullExport']['profit']), (209, 396.0), 'the canary: FWD added once')
        self.assertEqual((result['preFoos']['trades'], result['preFoos']['profit']), (185, 328.0))
        self.assertEqual((result['selectionWindow']['trades'], result['selectionWindow']['profit']), (160, 286.0), 'SAMPLE already holds FWD')
        parsed = {'BOOS': dict(start='2026-02-02', end='2026-03-02', trades=25, pl=42.0),
                  'SAMPLE': dict(start='2026-03-02', end='2026-08-15', trades=160, pl=286.0),
                  'FWD': dict(start='2026-06-20', end='2026-08-14', trades=40, pl=62.0)}
        self.assertEqual(wm._header_sum(parsed, ('FWD',), d('2026-06-20'), d('2026-08-14')), dict(trades=40, profit=62.0),
                         'a FWD-only window stays FWD')
        overlapping = dict(parsed, BOOS=dict(start='2026-02-02', end='2026-03-10', trades=25, pl=42.0))
        self.assertIsNone(wm._header_sum(overlapping, ('BOOS', 'SAMPLE'), d('2026-02-02'), d('2026-08-15')),
                          'any other overlap is refused, never summed')

    def test_without_boos_pre_foos_starts_at_sample(self):
        unit = self.unit(equity=series('2026-06-06', '2026-10-02'))
        result = wm.export_window_metrics(unit.set_path, **dict(TESTER, include_back_oos=False))
        self.assertEqual(result['preFoos']['from'], '2026-06-06')
        self.assertEqual(result['preFoos'], result['selectionWindow'])

    def test_arf_replays_the_ea_formula(self):
        # Opening 10000, rises 10/day; episodes 100 and 60 (60 >= 0.5 x 100): MeanDD = (100*6 + 60*5) / 11.
        dips = {d('2026-06-09'): 100.0, d('2026-06-23'): 60.0}
        rows = series('2026-06-01', '2026-07-03', start=9990.0, dips=dips)
        metrics = wm.equity_metrics(rows, d('2026-06-01'), d('2026-07-03'))
        opening, closing = rows[0][1], rows[-1][1]
        mean_dd = (100 * 6 + 60 * 5) / 11
        days = 25
        expected = ((closing - opening) / opening) / (mean_dd / opening) / (days / 21.7)
        self.assertEqual(metrics['days'], days)
        self.assertAlmostEqual(metrics['arf'], round(expected, 8))

    def test_ea_mean_dd_rules(self):
        self.assertEqual(wm.ea_mean_dd([]), 999999.0)
        self.assertEqual(wm.ea_mean_dd([100.0, 40.0]), 100.0)
        self.assertAlmostEqual(wm.ea_mean_dd([100.0, 60.0]), (600 + 300) / 11)
        self.assertAlmostEqual(wm.ea_mean_dd([100.0, 90.0, 80.0]), (700 + 540 + 400) / 18)
        self.assertAlmostEqual(wm.ea_mean_dd([100.0, 90.0, 80.0, 70.0, 60.0, 50.0]), (900 + 720 + 560 + 420 + 300) / 35)

    def test_sharpe_is_annualized_daily_equity_returns(self):
        rows = series('2026-06-01', '2026-06-12', start=10000.0, step=0.0)
        rows = [(stamp, 10000.0 + (i % 2) * 20.0 + i) for i, (stamp, _) in enumerate(rows)]
        metrics = wm.equity_metrics(rows, d('2026-06-01'), d('2026-06-12'))
        closes = [value for _, value in rows]
        returns, prior = [], closes[0]
        for close in closes:
            returns.append((close - prior) / prior)
            prior = close
        mean = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        self.assertAlmostEqual(metrics['sharpe'], round(mean / std * math.sqrt(252), 8))

    def test_bad_csv_refuses(self):
        with self.assertRaises(ValueError):
            wm.equity_samples(b'')
        with self.assertRaises(ValueError):
            wm.equity_samples((wm.HEADER + '\n2026.06.01 12:00\tx\ty\t0\n').encode())


class ExportScanTests(unittest.TestCase):
    """The report pipeline (studio_report_observe -> scan_exports) carries window_metrics per kept set."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Unit(self.root, equity=series('2026-04-18', '2026-10-02', dips={d('2026-06-16'): 50.0}),
             deals=trade(1, d('2026-06-10'), 30.0) + trade(2, d('2026-09-14'), -300.0))

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, **extra):
        from unittest.mock import patch
        from studio_export_scan import scan_exports
        with patch('studio_export_scan.verify_export_inputs', return_value=dict(status='verified_for_test')):
            return scan_exports(self.root, b'', {}, [], [], alias='R0', symbol='EURUSD', period='M1', expert_name='GOAT V1.49',
                                min_arf=0.2, min_sr=2.5, **extra)

    def test_window_metrics_are_added_and_nothing_else_changes(self):
        plain = self.scan()
        with_metrics = self.scan(windows=TESTER)
        item = with_metrics['files'][0]
        self.assertEqual(item['window_metrics']['schema'], wm.SCHEMA)
        self.assertEqual((item['window_metrics']['selectionWindow']['trades'], item['window_metrics']['preFoos']['maxDd']), (1, 50.0))
        self.assertEqual({k: v for k, v in item.items() if k != 'window_metrics'}, plain['files'][0])
        self.assertNotIn('window_metrics', plain['files'][0])

    def test_report_observe_passes_the_member_windows(self):
        import inspect
        import studio_report_observe
        source = inspect.getsource(studio_report_observe._observe_member)
        self.assertIn("windows=dict(from_date=tester['FromDate'], to_date=tester['ToDate']", source)


class GuardTests(unittest.TestCase):
    def test_window_metrics_and_oos_rule_are_redacted_for_a_locked_export(self):
        from studio_heldout_guard import METRIC_KEYS
        self.assertTrue({'window_metrics', 'preFoos', 'selectionWindow', 'fullExport', 'oos_rule'} <= METRIC_KEYS)


if __name__ == '__main__':
    unittest.main()
