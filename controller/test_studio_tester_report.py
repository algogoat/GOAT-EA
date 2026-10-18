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


def with_ea_init_enums(schema):
    """A GOAT-shaped compact schema (it names Mode_Lots) must declare the enum labels the EA init rules read
    (studio_ea_init_rules fails closed otherwise): take them from the shipped 1.49 interface."""
    from studio_ea_init_rules import EA_INIT_RULES
    from studio_installation import contracts
    real = contracts('1.49')[0]['inputs']
    for name in {name for rule in EA_INIT_RULES for name in rule['enums']} - {'Mode_Lots'}:
        if name in schema['inputs']:
            schema['inputs'][name] = dict(real[name])
    return schema


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
        # The compact schema carries no default for Grid_Factor: an unset input with an unknown default fails closed.
        with self.assertRaisesRegex(ValueError, 'the frozen SET does not set, not at their default: Grid_Factor ran .* \\(its default is unknown\\)'):
            tr.check(report, **self.expected(report, values=values, schema=schema_for(report['inputs'])))
        with self.assertRaisesRegex(ValueError, 'report symbol is SP500, the frozen test ran NDX'):
            tr.check(report, **self.expected(report, symbol='NDX'))
        with self.assertRaisesRegex(ValueError, 'report to date is 2026.09.11, the frozen test ran 2026.09.12'):
            tr.check(report, **self.expected(report, to_date='2026.09.12'))
        with self.assertRaisesRegex(ValueError, 'initial deposit is 100000.00, the frozen test used 10000'):
            tr.check(report, **self.expected(report, deposit=10000))

    def test_unset_inputs_pass_only_at_their_default_goat_ea_250(self):
        """GOAT-EA#250: a frozen SET that omits an input runs it at the EA default (an older-version SET, or the runtime
        inputs no SET carries). That is no mismatch; a non-default value, an unknown default or an unknown input is."""
        report = self.read()
        ran = report['inputs']['Grid_Factor']
        values = {k: v for k, v in report['inputs'].items() if k != 'Grid_Factor'}
        schema = schema_for(report['inputs'])
        # 1. Omitted, ran at its contract default: passes (an older-version SET predating the input).
        schema['inputs']['Grid_Factor'] = dict(type='double', optimizable=True, default_expression=ran)
        self.assertTrue(tr.check(report, **self.expected(report, values=values, schema=schema))['inputs_match'])
        # 2. Omitted, but ran at another value: fails with the value and the default.
        schema['inputs']['Grid_Factor'] = dict(type='double', optimizable=True, default_expression='9.5')
        with self.assertRaisesRegex(ValueError, 'Grid_Factor ran %s, default 9.5' % re.escape(ran)):
            tr.check(report, **self.expected(report, values=values, schema=schema))
        # 3. The runtime inputs no SET carries, as MT5 reports them when the runner pinned them: defaults pass.
        runtime = dict(Sequence_Export_Enabled='false', Sequence_Export_Id='', Sequence_Export_Start='0', Sequence_Export_End='0',
                       Sequence_Export_Model='4', GOAT_FitnessRunNonce='0', Studio_MonitorRunPath='', Dashboard_Resume_Saved='false')
        report_runtime = dict(report, inputs=dict(report['inputs'], **runtime))
        self.assertTrue(tr.check(report_runtime, **self.expected(report))['inputs_match'])
        # 4. The 2026-10-18 repro: MT5 ran them at the terminal's last-used values (another run's export). Refused, named.
        leaked = dict(runtime, Sequence_Export_Enabled='true', Sequence_Export_Id='catchup-c5fb36b46df64517-00103',
                      Sequence_Export_Start='1766188800', Sequence_Export_End='1792195200')
        with self.assertRaisesRegex(ValueError, 'Sequence_Export_Enabled ran true, default false; Sequence_Export_End ran 1792195200, default 0; '
                                                'Sequence_Export_Id ran catchup-c5fb36b46df64517-00103, default ; Sequence_Export_Start ran 1766188800'):
            tr.check(dict(report, inputs=dict(report['inputs'], **leaked)), **self.expected(report))
        with self.assertRaisesRegex(ValueError, 'Dashboard_Resume_Saved ran true, default false'):
            tr.check(dict(report, inputs=dict(report_runtime['inputs'], Dashboard_Resume_Saved='true')), **self.expected(report))
        # 5. An input GOAT does not know at all is never waved through.
        with self.assertRaisesRegex(ValueError, 'Mystery_Input ran 7 \\(not an input GOAT knows\\)'):
            tr.check(dict(report, inputs=dict(report['inputs'], Mystery_Input='7')), **self.expected(report))
        # 6. A frozen value still has to match exactly: the default rule applies only to inputs the SET omits.
        with self.assertRaisesRegex(ValueError, 'MT5 ran different inputs than the frozen SET: Grid_Size frozen -5'):
            tr.check(report, **self.expected(report, values=dict(report['inputs'], Grid_Size='-5')))

    def test_contract_defaults_read_like_a_set_value_goat_ea_250(self):
        """Defaults come from the shipped 1.49 input contract: datetime literals, enum labels (through #define names),
        strings, booleans and numbers, in the spelling a SET uses; anything else is unknown (None, fails closed)."""
        from studio_installation import contracts
        schema = contracts('1.49')[0]
        inputs, defines = schema['inputs'], schema.get('defines')
        self.assertEqual(tr._schema_default(inputs['Download_StartDate'], defines), '2025.01.01')
        self.assertEqual(tr._schema_default(inputs['Mode_Lots'], defines), str(inputs['Mode_Lots']['enum_choices'][inputs['Mode_Lots']['default_expression']]))
        self.assertEqual(tr._schema_default(inputs['Mode_Bias'], defines), str(inputs['Mode_Bias']['enum_choices']['Bias_Opens']))   # via GOAT_DEFAULT_BIAS_MODE
        self.assertEqual(tr._schema_default(inputs['EA_Desc'], defines), 'GOAT_Trading')
        self.assertEqual(tr._schema_default(inputs['Allow_New_Sequence'], defines), 'true')
        self.assertEqual(tr._schema_default(inputs['Grid_Size'], defines), '10.0')
        self.assertIsNone(tr._schema_default(dict(type='int', default_expression='SOME_UNKNOWN_MACRO'), defines))
        self.assertIsNone(tr._schema_default(dict(type='int'), defines))
        # The datetime the report prints as epoch seconds equals the SET's literal (Download_StartDate in #250).
        self.assertTrue(tr._same_input('Download_StartDate', '2025.01.01', '1735689600', dict(type='datetime')))
        self.assertFalse(tr._same_input('Download_StartDate', '2025.01.01', '1735689601', dict(type='datetime')))
        self.assertTrue(tr._same_input('Download_StartDate', '2025.01.01', '2025.01.01 00:00', dict(type='datetime')))

    def test_older_and_current_sets_pass_against_the_v149_build_goat_ea_250(self):
        """Mac's fixtures (goatai#2587 6247100483): a V1.47 SET, a V1.48 SET and a V1.49 export each pass when MT5 ran
        every input they omit at the 1.49 build's default (as the runner now pins them); an omitted input at a
        non-default value and a changed explicit input are refused. Built from the shipped contracts, not hand lists."""
        from studio_installation import contracts
        schema = contracts('1.49')[0]
        pinned = tr.omitted_input_defaults({}, schema)                    # what the runner writes for an empty SET
        report = self.read()
        def declared(version):
            """The input names a version's SET carries: the shipped contract (1.48, 1.49); for 1.47, the inputs of the
            recorded V1.47 pass this suite reads (its report lists exactly the 114 inputs that SET ran)."""
            if version in ('1.48', '1.49'):
                return set(contracts(version)[0]['inputs'])
            return set(report['inputs'])
        self.assertEqual(len(declared('1.47')), 114)
        for version in ('1.47', '1.48', '1.49'):
            older = declared(version)
            values = {name: pinned[name] for name in older if name in pinned}   # the SET of that version, at defaults
            ran = dict(pinned)                                                    # MT5: SET values + the runner's pins
            ran.update(tr.omitted_input_defaults(values, schema))
            ok = tr.check(dict(report, inputs=ran), **self.expected(report, values=values, schema=schema))
            self.assertTrue(ok['inputs_match'], version)
            self.assertEqual(ok['inputs_checked'], len(values), version)
        values = {name: pinned[name] for name in declared('1.47') if name in pinned}
        # The V1.47 SET carries every 1.49 contract input; what it omits are the runtime inputs (as in the repro).
        omitted = next(name for name in sorted(pinned) if name not in values and re.fullmatch(r'-?\d+(\.\d+)?', pinned[name]))
        with self.assertRaisesRegex(ValueError, '%s ran 777, default %s' % (omitted, re.escape(pinned[omitted]))):
            tr.check(dict(report, inputs=dict(pinned, **{omitted: '777'})), **self.expected(report, values=values, schema=schema))
        explicit = next(name for name in sorted(values) if schema['inputs'][name]['type'] == 'int')
        with self.assertRaisesRegex(ValueError, 'MT5 ran different inputs than the frozen SET: %s frozen' % explicit):
            tr.check(dict(report, inputs=dict(pinned, **{explicit: str(int(values[explicit]) + 1)})),
                     **self.expected(report, values=values, schema=schema))

    def test_the_runner_pins_every_omitted_input_goat_ea_250(self):
        from studio_installation import contracts
        schema = contracts('1.49')[0]
        values = {'Grid_Size': '12.0'}
        pins = tr.omitted_input_defaults(values, schema)
        self.assertNotIn('Grid_Size', pins)                                   # a frozen value is never overridden
        self.assertEqual(pins['Download_StartDate'], '2025.01.01')
        self.assertEqual((pins['Sequence_Export_Enabled'], pins['Sequence_Export_Id'], pins['GOAT_FitnessRunNonce']), ('false', '', '0'))
        readable = {n for n, d in schema['inputs'].items() if tr._schema_default(d, schema.get('defines')) is not None}
        self.assertEqual(set(pins) - set(tr.RUNTIME_INPUT_DEFAULTS), readable - set(values))

    def test_runtime_defaults_equal_every_ea_source_declaration_goat_ea_250(self):
        """Claude-Mac on GOAT-EA#251 (should-fix): RUNTIME_INPUT_DEFAULTS is a table; a build that changes one of these
        defaults must fail here, never be accepted at the old value. Every declaration of the 8 runtime inputs in the
        V1.47 / V1.48 / V1.49 sources (and the shared GOAT_SequencePackage.mqh) must equal the table, in default and
        in whether it is an optimizable `input` (needs an explicit N flag) or a fixed `sinput`."""
        repo = Path(__file__).resolve().parents[1]
        sources = [repo / ('GOAT V%s.mq5' % v) for v in ('1.47', '1.48', '1.49')] + [repo / 'GOAT_SequencePackage.mqh']
        literal = {'""': '', 'false': 'false', 'true': 'true'}
        seen = {}
        for source in sources:
            text = source.read_text(encoding='utf-8-sig', errors='strict')
            for name, (default, definition) in tr.RUNTIME_INPUT_DEFAULTS.items():
                for keyword, kind, value in re.findall(r'(?m)^\s*(sinput|input)\s+(\w+)\s+%s\s*=\s*([^;]*);' % name, text):
                    value = value.strip()
                    declared = literal.get(value, value)
                    with self.subTest(source=source.name, input=name):
                        self.assertEqual(declared, default, '%s declares %s=%s; the table says %s' % (source.name, name, value, default))
                        self.assertEqual(keyword == 'input', bool(definition.get('optimizable')), '%s declares %s as %s' % (source.name, name, keyword))
                    seen.setdefault(name, []).append(source.name)
        self.assertEqual(set(seen), set(tr.RUNTIME_INPUT_DEFAULTS), 'every table entry is declared by a supported source')

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
