"""MT5's single-test report, read from a real recorded report (goatai#1885 hold-up test).

Fixture ``fixtures/holdup/mt5-single-test-report.htm.gz``: MT5 build 6182's own Strategy Tester
Report of one non-optimized GOAT V1.47 pass (SP500 M1, Model 4, 2026.01.19-2026.09.11, deposit
100 000 USD, 1:100), recorded on Claude-PC's T2 during the 2026-09-13 band-stack fixed runs
(P6NF24SP5004.htm, sha256 a30a0ea4...). It carries no login, path or account number.
"""
from decimal import Decimal
import gzip
from pathlib import Path
import re
import tempfile
import unittest

import studio_tester_report as tr

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'holdup' / 'mt5-single-test-report.htm.gz'
FIXTURE_SHA256 = 'a30a0ea496df33bccfa2259fd11826ea0034412b87a44fcb9b459638d66ce1a7'


def fixture_text():
    return gzip.decompress(FIXTURE.read_bytes()).decode('utf-16')


def schema_for(values):
    """A compact input schema typed from the report's own values (the real one comes from the EA source)."""
    inputs = {}
    for name, value in values.items():
        if name == 'EA_Desc' or not re.fullmatch(r'-?\d+(\.\d+)?|true|false', value):
            inputs[name] = dict(type='string', optimizable=False)
        elif value in ('true', 'false'):
            inputs[name] = dict(type='bool', optimizable=True)
        elif '.' in value:
            inputs[name] = dict(type='double', optimizable=True)
        else:
            inputs[name] = dict(type='int', optimizable=True)
    return dict(source_sha256='a' * 64, inputs=inputs)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'report.htm'
        self.write(fixture_text())

    def write(self, text):
        self.path.write_bytes(b'\xff\xfe' + text.encode('utf-16-le'))

    def read(self):
        return tr.read_report(self.path)

    def expected(self, report, **change):
        values = dict(report['inputs'])
        return dict(dict(values=values, schema=schema_for(values), expert='GOAT V1.47', symbol='SP500', period='M1',
                         from_date='2026.01.19', to_date='2026.09.11', deposit=100000, currency='USD', leverage='1:100'), **change)

    def test_the_recorded_report_reads_whole(self):
        report = self.read()
        self.assertEqual(report['sha256'], FIXTURE_SHA256)
        self.assertEqual((report['server'], report['mt5_build']), ('Darwinex-Demo', 6182))
        self.assertEqual(report['settings'], dict(expert='GOAT V1.47', symbol='SP500', period='M1', from_date='2026.01.19',
                                                  to_date='2026.09.11', company='Tradeslide Trading Tech Limited', currency='USD',
                                                  deposit=Decimal('100000.00'), leverage='1:100'))
        self.assertEqual(len(report['inputs']), 114)                      # group separators are not inputs
        self.assertTrue(report['inputs']['EA_Desc'].startswith('P6NF24SP5004@{mode=EXPORT'))
        self.assertEqual((report['history_quality_pct'], report['history_quality_text']), (100.0, '100% real ticks'))
        m = tr.metrics(report)
        self.assertEqual((m['net'], m['trades'], m['deals'], m['profit_factor'], m['win_rate_pct']), (-880.37, 128, 240, 0.85, 42.97))
        self.assertEqual((m['equity_dd_max_money'], m['equity_dd_relative_pct'], m['balance_dd_max_money']), (1960.36, 1.96, 1802.2))
        self.assertEqual((m['gross_profit'], m['gross_loss'], m['sharpe_ratio'], m['recovery_factor']), (5186.21, -6066.58, -2.8, -0.45))
        self.assertEqual(len(report['deals']), 241)
        self.assertEqual(report['totals'], dict(commission=Decimal('-68.29'), swap=Decimal('0.00'), profit=Decimal('-812.08'),
                                                balance=Decimal('99119.63')))

    def test_every_check_passes_on_its_own_frozen_values(self):
        report = self.read()
        checks = tr.check(report, **self.expected(report))
        self.assertEqual(checks, dict(inputs_match=True, inputs_checked=114, settings_match=True, balance_chain=True, totals_match=True,
                                      net_reconciles=True, balance_reconciles=True, deals_match=True, trades_match=True))

    def test_different_inputs_settings_or_extra_inputs_fail_with_their_names(self):
        report = self.read()
        values = dict(report['inputs'], Grid_Size='-5')
        with self.assertRaisesRegex(ValueError, 'MT5 ran different inputs than the frozen SET: Grid_Size frozen -5, ran -4'):
            tr.check(report, **self.expected(report, values=values))
        values = {k: v for k, v in report['inputs'].items() if k != 'Grid_Factor'}
        with self.assertRaisesRegex(ValueError, 'MT5 ran input\\(s\\) the frozen SET does not set: Grid_Factor'):
            tr.check(report, **self.expected(report, values=values, schema=schema_for(report['inputs'])))
        with self.assertRaisesRegex(ValueError, 'report symbol is SP500, the frozen test ran NDX'):
            tr.check(report, **self.expected(report, symbol='NDX'))
        with self.assertRaisesRegex(ValueError, 'report to date is 2026.09.11, the frozen test ran 2026.09.12'):
            tr.check(report, **self.expected(report, to_date='2026.09.12'))
        with self.assertRaisesRegex(ValueError, 'initial deposit is 100000.00, the frozen test used 10000'):
            tr.check(report, **self.expected(report, deposit=10000))

    def test_values_compare_by_type_not_by_spelling(self):
        report = self.read()
        values = dict(report['inputs'], Risk='500.0||100||10||900||N', Grid_Exponent='1.00000000')
        schema = schema_for(report['inputs']); schema['inputs']['Risk'] = dict(type='double', optimizable=True)
        schema['inputs']['Grid_Exponent'] = dict(type='double', optimizable=True)
        self.assertTrue(tr.check(report, **self.expected(report, values=values, schema=schema))['inputs_match'])
        self.assertTrue(tr._same_input('X', '1', 'true', dict(type='bool')))
        self.assertFalse(tr._same_input('X', '0.12345678', '0.12345679', dict(type='double')))
        self.assertTrue(tr._same_input('X', '0.123456781', '0.12345678', dict(type='double')))    # beyond MT5's 8 printed decimals
        self.assertFalse(tr._same_input('X', '100000000', '100000000.4', dict(type='double')))   # absolute, not relative
        self.assertTrue(tr._same_input('X', '100000000.000000001', '100000000', dict(type='double')))

    def test_a_tampered_deal_or_total_breaks_the_reconciliation(self):
        text = fixture_text()
        changed = text.replace('<td>-36.98</td><td>99 962.54</td>', '<td>-26.98</td><td>99 962.54</td>', 1)
        self.assertNotEqual(changed, text)
        self.write(changed)
        report = self.read()
        with self.assertRaisesRegex(ValueError, 'balance does not follow from the previous balance'):
            tr.check(report, **self.expected(report))
        self.write(text.replace('<b>-880.37</b>', '<b>-870.37</b>', 1))
        report = self.read()
        with self.assertRaisesRegex(ValueError, 'the deals add up to -880.37, the report says Total Net Profit -870.37'):
            tr.check(report, **self.expected(report))
        self.write(text.replace('<td nowrap><b>240</b></td>', '<td nowrap><b>241</b></td>', 1))
        report = self.read()
        with self.assertRaisesRegex(ValueError, '240 trading deals listed, the report says Total Deals 241'):
            tr.check(report, **self.expected(report))

    def test_a_non_english_or_foreign_file_refuses_plainly(self):
        self.write(fixture_text().replace('Total Net Profit:', 'Gesamtnettogewinn:'))
        with self.assertRaisesRegex(ValueError, 'not in English'):
            self.read()
        self.write('<html><body>nothing</body></html>')
        with self.assertRaisesRegex(ValueError, 'not in English'):
            self.read()
        self.path.write_bytes(b'\x00\x01binary')
        with self.assertRaises(ValueError):
            self.read()

    def test_weekly_daily_and_split_views_add_up_to_the_net(self):
        report = self.read()
        per_week, daily, segments = tr.deal_views(report, split='2026-06-01')
        self.assertEqual(round(sum(w['net'] for w in per_week), 2), -880.37)
        self.assertEqual(per_week[0]['week_start'], '2026-01-19')
        self.assertTrue(all(w['week_start'] <= x['week_start'] for w, x in zip(per_week, per_week[1:])))
        self.assertEqual(sum(w['closed_trades'] for w in per_week), 128)
        self.assertEqual(daily[-1], dict(day='2026-09-09', net=-58.24, balance_close=99119.63))
        self.assertEqual(round(segments['before']['net'] + segments['after']['net'], 2), -880.37)
        self.assertEqual(segments['before']['closed_trades'] + segments['after']['closed_trades'], 128)
        self.assertEqual(tr.deal_views(report)[2], None)
        rows = tr.deal_rows(report)
        self.assertEqual((rows[1]['commission'], rows[1]['balance'], rows[0]['type']), ('-0.24', '99999.76', 'balance'))


if __name__ == '__main__':
    unittest.main()
