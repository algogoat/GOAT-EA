"""Gate calibration v2: window split, #118-aligned PF, trade minimum, v2 verdicts, member
aggregation, within-run signal, leave-one-run-out validation, coverage simulation,
thin-data fallback, leakage guard, tighten-only deterministic stamp and read-only behaviour. Synthetic fixtures copy the real export
file shapes (UTF-16 equity CSV and SET siblings, UTF-8 capture files, UTF-16
SpreadsheetML optimizer rows that declare UTF-8); no real data is used."""
from datetime import date, datetime, timedelta
import hashlib
import math
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parent))

import studio_gate_calibration as gates

BOOS, START, FORWARD, TO, END = date(2025, 1, 6), date(2025, 2, 3), date(2025, 6, 2), date(2025, 7, 7), date(2025, 8, 30)
XML_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<?mso-application progid="Excel.Sheet"?>\r\n'
            '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"\r\nxmlns:o="urn:schemas-microsoft-com:office:office"\r\n'
            'xmlns:x="urn:schemas-microsoft-com:office:excel"\r\nxmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"\r\n'
            'xmlns:html="http://www.w3.org/TR/REC-html40">\r\n<Worksheet ss:Name="Tester Optimizator Results">\r\n<Table>\r\n')
XML_COLUMNS = ['Pass', 'Score', 'Result(Back)', 'Result(Forward)', 'Trades(Back)', 'Trades(Forward)', 'Profit(Back)',
               'Profit(Forward)', 'PF(Back)', 'PF(Forward)', 'RF(Back)', 'RF(Forward)', 'SR(Back)', 'SR(Forward)',
               'DD(Back)', 'DD(Forward)', 'Grid_Size', 'RSI_Period']


def ms(day_value, hour=12):
    return gates.msc(datetime.combine(day_value, datetime.min.time()) + timedelta(hours=hour))


def utf16(path, text):
    path.write_bytes(b'\xff\xfe' + text.encode('utf-16-le'))


def window_of(day_value):
    if day_value < START: return 'back_oos'
    if day_value < FORWARD: return 'in_sample'
    if day_value < TO: return 'forward'
    return 'post'


def write_set(root, run, alias, symbol, pnl, *, grid=-2.25, rsi=5, score=80.0, capture_complete=True,
              area='deploy', family=('RSI', 'EMA')):
    """One exported set. ``pnl``: per-window daily profit, one entry and one exit deal per weekday."""
    days, current = [], BOOS
    while current < END:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    balance, deal_rows, equity_rows, ordinal, totals = 100000.0, [], ['<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'], 1, []
    equity_rows.append('%s 00:04\t100000.00\t100000.00\t0.0' % BOOS.strftime('%Y.%m.%d'))
    for index, day_value in enumerate(days):
        profit = pnl[window_of(day_value)]
        deal_rows.append('%d,%d,%d,%d,%d,%d,1,0,0,0.05,1.1,0.0,0.0,0.0,0.0,29793,known-order-to-position'
                         % (ordinal, ms(day_value, 9), index + 1, 2 * index + 2, 2 * index + 2, 2 * index + 2))
        deal_rows.append('%d,%d,%d,%d,%d,%d,1,1,1,0.05,1.1,%.2f,0.0,0.0,0.0,29793,known-position'
                         % (ordinal + 1, ms(day_value, 15), index + 1, 2 * index + 3, 2 * index + 3, 2 * index + 2, profit))
        ordinal += 2
        balance += profit
        totals.append(profit)
        equity_rows.append('%s 15:00\t%.2f\t%.2f\t0.0' % (day_value.strftime('%Y.%m.%d'), balance, balance))
    net = sum(totals)
    name = 'GOAT V1.49 %s,M1_Trds=%d_Prf=%d_DD=50_PF=1.50_SR=%.2f_ARF=0.250' % (symbol, len(days), round(net), 3 + abs(grid) / 5)
    folder = Path(root) / run / area / alias / symbol / (name + '.goatseq')
    folder.mkdir(parents=True)
    utf16(folder.parent / (name + '.csv'), '\r\n'.join(equity_rows) + '\r\n')
    set_text = '; saved\r\nEA_Desc=%s\r\nGrid_Size=%s\r\nRSI_Period=%d\r\n' % (alias, grid, rsi)
    utf16(folder.parent / (name + '.set'), set_text)
    utf16(folder / 'effective-inputs.set', '; Actual resolved native inputs before trading\r\nMode_Operation=9\r\nEA_Desc=%s\r\n'
          'Grid_Size=%s\r\nRSI_Mode=%d\r\nRSI_TF_=15\r\nRSI_Period=%d\r\nEMA_Mode=%d\r\nEMA_TF_=60\r\nADX_Mode=0\r\nBB_Mode=0\r\n'
          'MACD_Mode=0\r\nRSI2_Mode=0\r\n' % (alias, grid, 'RSI' in family, rsi, 'EMA' in family))
    (folder / 'source-inputs.set').write_text('Grid_Size=%s\nRSI_Period=%d\n' % (grid, rsi), encoding='utf-8')
    cut = ms(date(2025, 4, 1), 0)
    (folder / 'completion.csv').write_text(
        'key,value\ntester_finished,%s\ndeinit_reason,1\nobserved_end_server_msc,%d\nentry_deals,%d\nerror,%s\n'
        'capture_status,%s\nfooter,END\n' % ('true' if capture_complete else 'false', ms(days[-1], 15) if capture_complete else cut,
                                             len(days), '' if capture_complete else '2000000 row resource limit exceeded',
                                             'complete-awaiting-external-reconciliation' if capture_complete else 'incomplete'),
        encoding='utf-8')
    deals_text = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,' \
                 'lots,price,profit,commission,fee,swap,deal_magic,join_basis\n'
    kept = deal_rows if capture_complete else [row for row in deal_rows if int(row.split(',')[1]) < cut]
    (folder / 'deals.csv').write_text(deals_text + '\n'.join(kept) + '\n', encoding='utf-8')
    (folder / 'manifest.json').write_text(json.dumps(dict(
        schemaVersion='goat-sequence-export-v1', status='complete-awaiting-import-verification', asset=symbol,
        initialEquity=100000.0, exports=dict(csv=dict(path='../' + name + '.csv'), set=dict(path='../' + name + '.set')))),
        encoding='utf-8')
    reports = Path(root) / run / 'reports' / alias / symbol
    reports.mkdir(parents=True, exist_ok=True)
    xml = reports / ('GOAT V1.49 %s,M1 2025.02.03-2025.07.07_(2025.06.02)_UniqueRows_Score=%.1f.xml' % (symbol, score))
    rows = []
    if xml.exists():
        old = xml.read_bytes().decode('utf-16')
        rows = [old.split('<Table>\r\n', 1)[1].rsplit('</Table>', 1)[0]]
        xml.unlink()
    cell = lambda kind, value: '    <Cell><Data ss:Type="%s">%s</Data></Cell>\r\n' % (kind, value)
    if not rows:
        rows = ['  <Row>\r\n' + ''.join(cell('String', column) for column in XML_COLUMNS) + '  </Row>\r\n']
    values = [1, score, 0.5, 0.2, 300, 40, 300.0, 40.0, 2.0, 1.8, 4.0, 0.6, 5.5, 2.5, 0.07, 0.07, grid, rsi]
    rows.append('  <Row>\r\n' + ''.join(cell('Number', '%.2f' % float(value)) for value in values) + '  </Row>\r\n')
    utf16(xml, XML_HEAD + ''.join(rows) + '</Table>\r\n</Worksheet>\r\n</Workbook>\r\n')
    return folder


def write_manifest(root, run, members, **settings):
    jobs = [dict(run_alias=alias, tester=dict(Symbol=symbol, Period='M1', FromDate=START.strftime('%Y.%m.%d'),
                                              ForwardDate=FORWARD.strftime('%Y.%m.%d'), ToDate=TO.strftime('%Y.%m.%d')))
            for alias, symbol in members]
    path = Path(root) / run / 'manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(schema_version=1, export_settings=dict(
        gates.DEFAULT_EXPORT, BackOOSDate=BOOS.strftime('%Y.%m.%d'), IncludeBackOOS=True, AdjustLots=False,
        IncludeSequenceData=True, **settings), jobs=jobs)), encoding='utf-8')



def record(member, *, run='R1', survived=True, is_sr=1.0, fwd_net=None, file_sr=3.0, score=80.0, index=0,
           symbol_class='fx_majors', post_survived=None, fwd_trades=40, filler=False, symbol='EURUSD'):
    """A loaded-evidence record without files, for the statistics tests."""
    window = lambda net, first, end, **extra: dict(dict(first_day=first.isoformat(), end_day=end.isoformat(), weekdays=20,
                                                        trades=40, net=net, dd=10.0, pf=1.5, recovery=1.0, sr=1.0, arf=0.1), **extra)
    windows = dict(back_oos=window(5.0, BOOS, START), in_sample=window(100.0, START, FORWARD, sr=is_sr),
                   forward=window(fwd_net if fwd_net is not None else (10.0 if survived else -10.0), FORWARD, TO,
                                  trades=fwd_trades),
                   post=window(10.0 if (post_survived if post_survived is not None else survived) else -10.0, TO, END))
    return dict(run=run, member=member, member_key=run + '/' + member, symbol=symbol,
                set_sha256=hashlib.sha256(('%s/%s/%d' % (run, member, index)).encode()).hexdigest(),
                symbol_class=symbol_class, family='RSI+EMA', timeframe='TF15', design='IS4m/F5w/B4w', period='P-' + run,
                windows=windows, observed_end=END.isoformat(), optimizer={'Score': score, 'SR(Back)': is_sr,
                                                                          'PF(Back)': 1.5, 'RF(Back)': 2.0},
                file_name=dict(trades=100, net=100.0, dd=10.0, pf=1.5, sr=file_sr, arf=0.3), path=member, filler=filler)


def graded(runs=8, members=30, seed=7, sets_per_member=2):
    """Forward survival rises with is_sr inside every run; nothing else carries signal."""
    rng, rows = random.Random(seed), []
    for run in range(runs):
        for member in range(members):
            level = member / members * 4
            survived = rng.random() < 0.05 + 0.95 * member / members
            for index in range(sets_per_member):
                rows.append(record('M%03d' % member, run='R%d' % run, is_sr=round(level + rng.uniform(-0.02, 0.02), 3),
                                   survived=survived, index=index))
    return rows


def verdicts_for(rows, held):
    """held: callable(record) -> verdict string; the in-memory form load_verdicts returns."""
    return {r['set_sha256']: dict(verdict=held(r), evidence_end='2026-10-02') for r in rows}


def verdict_node(sha, verdict='held_up', *, schema=gates.VERDICT_SCHEMA, comparable=True, overridden=(), end='2026-10-02'):
    return dict(schema=schema, verdict=verdict, confidence='low', comparability=dict(comparable=comparable, checks=[]),
                rules=dict(id=gates.VERDICT_SCHEMA, overridden=list(overridden)),
                original=dict(set_sha256=sha, set_path='x.set', evidence_end='2026-09-25', values_sha256='0' * 64),
                retest=dict(set_sha256=sha, set_path='y.set', evidence_end=end))


class WindowSplitTests(unittest.TestCase):
    def test_windows_split_deals_and_equity_by_server_date(self):
        with tempfile.TemporaryDirectory() as root:
            write_manifest(root, 'R1', [('A1', 'EURUSD')])
            pnl = dict(back_oos=10.0, in_sample=5.0, forward=-3.0, post=2.0)
            write_set(root, 'R1', 'A1', 'EURUSD', pnl, score=91.5)
            loaded = gates.load_run(Path(root) / 'R1')
            self.assertEqual(loaded['skipped'], [])
            record_ = loaded['records'][0]
            windows = record_['windows']
            self.assertEqual(set(windows), {'back_oos', 'in_sample', 'forward', 'post'})
            for name, daily in pnl.items():
                window = windows[name]
                first, end = date.fromisoformat(window['first_day']), date.fromisoformat(window['end_day'])
                days = gates.weekdays(first, end)
                self.assertEqual(window['trades'], days, name)
                self.assertAlmostEqual(window['net'], round(daily * days, 2), places=2, msg=name)
            self.assertEqual(windows['in_sample']['first_day'], START.isoformat())
            self.assertEqual(windows['forward']['first_day'], FORWARD.isoformat())
            self.assertEqual(windows['forward']['end_day'], TO.isoformat())
            self.assertEqual(windows['back_oos']['end_day'], START.isoformat())
            self.assertGreater(windows['forward']['dd'], 0)
            self.assertEqual(windows['forward']['pf'], 0.0)
            self.assertIsNone(windows['in_sample']['pf'])  # no losing deal: unknown, as in goat-catchup-verdict-v2
            self.assertLess(windows['forward']['recovery'], 0)
            self.assertEqual(record_['optimizer']['Score'], 91.5)
            self.assertEqual(record_['file_name']['sr'], 3.45)
            self.assertEqual(record_['symbol_class'], 'fx_majors')
            self.assertEqual(record_['family'], 'RSI+EMA')
            self.assertEqual(record_['timeframe'], 'TF15')
            self.assertEqual(record_['capture'], 'complete')
            self.assertEqual(record_['member_key'], 'R1/A1')
            self.assertFalse(record_['filler'])

    def test_pf_counts_only_positions_opened_in_the_window(self):
        rows = [(gates.msc(date(2025, 1, 30)), 0, 'P1', -1.0), (gates.msc(date(2025, 2, 4)), 1, 'P1', -50.0),
                (gates.msc(date(2025, 2, 5)), 0, 'P2', -1.0), (gates.msc(date(2025, 2, 6)), 1, 'P2', 9.0),
                (gates.msc(date(2025, 2, 7)), 0, 'P3', -1.0), (gates.msc(date(2025, 2, 8)), 1, 'P3', -1.0)]
        equity_rows = [(datetime(2025, 1, 6), 100000.0)]
        window = gates.window_metrics(rows, equity_rows, date(2025, 2, 3), date(2025, 3, 3), 100000.0)
        self.assertEqual(window['trades'], 2)
        self.assertEqual(window['closes'], 3)
        self.assertAlmostEqual(window['pf'], 9.0 / 3.0)  # P1 opened earlier: its -50 counts in net, not PF

    def test_partial_capture_keeps_equity_but_never_counts_uncovered_trades(self):
        with tempfile.TemporaryDirectory() as root:
            write_manifest(root, 'R1', [('A1', 'XAUUSD')])
            write_set(root, 'R1', 'A1', 'XAUUSD', dict(back_oos=1.0, in_sample=1.0, forward=2.0, post=3.0),
                      capture_complete=False)
            record_ = gates.load_run(Path(root) / 'R1')['records'][0]
            self.assertEqual(record_['capture'], 'partial')
            self.assertIsNotNone(record_['windows']['back_oos']['trades'])
            self.assertIsNone(record_['windows']['in_sample']['trades'])
            self.assertIsNone(record_['windows']['forward']['trades'])
            self.assertIsNone(record_['windows']['forward']['pf'])
            self.assertGreater(record_['windows']['post']['net'], 0)
            self.assertIsNone(gates.outcome(record_, 'post'))  # trade count unknown: not judged
            self.assertEqual(record_['symbol_class'], 'metals')

    def test_capture_still_being_written_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            write_manifest(root, 'R1', [('A1', 'EURUSD')])
            folder = write_set(root, 'R1', 'A1', 'EURUSD', dict(back_oos=1.0, in_sample=1.0, forward=1.0, post=1.0))
            text = (folder / 'completion.csv').read_text(encoding='utf-8').replace('footer,END\n', '')
            (folder / 'completion.csv').write_text(text, encoding='utf-8')
            loaded = gates.load_run(Path(root) / 'R1')
            self.assertEqual(loaded['records'], [])
            self.assertIn('still being written', loaded['skipped'][0]['reason'])

    def test_only_byte_identical_evidence_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as root:
            pnl = dict(back_oos=1.0, in_sample=1.0, forward=1.0, post=1.0)
            for run in ('R1', 'R2', 'R3'):
                write_manifest(root, run, [('A1', 'EURUSD')])
            write_set(root, 'R1', 'A1', 'EURUSD', pnl)
            write_set(root, 'R2', 'A1', 'EURUSD', pnl)                    # same inputs, same evidence
            write_set(root, 'R3', 'A1', 'EURUSD', dict(pnl, post=-1.0))   # same inputs, different evidence
            evidence = gates.load_evidence(root)
            self.assertEqual(evidence['duplicates_removed'], 1)
            self.assertEqual(sorted(r['run'] for r in evidence['records']), ['R1', 'R3'])

    def test_fillers_are_labelled_against_their_own_run_thresholds(self):
        self.assertTrue(gates.is_filler(dict(sr=2.9, arf=0.5), dict(MinSR=3.0, MinARF=0.2)))
        self.assertFalse(gates.is_filler(dict(sr=2.9, arf=0.5), dict(MinSR=2.5, MinARF=0.2)))
        self.assertTrue(gates.is_filler(dict(sr=4.0, arf=0.1), dict(MinSR=2.5, MinARF=0.2)))
        self.assertIsNone(gates.is_filler(None, {}))
        with tempfile.TemporaryDirectory() as root:
            write_manifest(root, 'R1', [('A1', 'EURUSD')], MinSR=4.0)
            write_set(root, 'R1', 'A1', 'EURUSD', dict(back_oos=1.0, in_sample=1.0, forward=1.0, post=1.0))
            evidence = gates.load_evidence(root)
            self.assertTrue(evidence['records'][0]['filler'])   # SR 3.45 < this run's MinSR 4.0
            self.assertEqual(evidence['runs'][0]['fillers'], 1)

    def test_symbol_classes(self):
        self.assertEqual(gates.symbol_class('EURUSD'), 'fx_majors')
        self.assertEqual(gates.symbol_class('GBPNZD'), 'fx_crosses')
        self.assertEqual(gates.symbol_class('WS30'), 'indices')
        self.assertEqual(gates.symbol_class('XAGUSD'), 'metals')


class OutcomeTests(unittest.TestCase):
    def test_survival_needs_a_minimum_trade_count(self):
        self.assertTrue(gates.outcome(record('M1', fwd_trades=5), 'forward'))
        self.assertIsNone(gates.outcome(record('M1', fwd_trades=4), 'forward'))
        self.assertIsNone(gates.outcome(record('M1', fwd_trades=0, survived=False), 'forward'))
        self.assertIsNone(gates.outcome(record('M1', fwd_trades=None), 'forward'))
        self.assertIsNone(gates.outcome(record('M1', fwd_trades=9), 'forward', min_trades=10))

    def test_verdicts_accept_only_comparable_v2_with_default_rules(self):
        sha = lambda i: hashlib.sha256(str(i).encode()).hexdigest()
        nodes = [verdict_node(sha(1)), verdict_node(sha(2), schema='goat-catchup-verdict-v1'),
                 verdict_node(sha(3), comparable=False), verdict_node(sha(4), overridden=['min_trades']),
                 verdict_node(sha(5), verdict='great'), verdict_node(sha(6), verdict='failed'),
                 verdict_node(sha(7), verdict='not_comparable', comparable=False)]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'verdicts.json'
            path.write_text(json.dumps(dict(members=nodes)), encoding='utf-8')
            found, rejected = gates.load_verdicts(path)
        self.assertEqual(set(found), {sha(1), sha(6), sha(7)})
        self.assertEqual(sum(rejected.values()), 4)
        self.assertIn('not comparable', rejected)
        probe = record('M1')
        probe['set_sha256'] = sha(7)
        self.assertIsNone(gates.outcome(probe, 'held_up', found))
        probe['set_sha256'] = sha(6)
        self.assertFalse(gates.outcome(probe, 'held_up', found))
        probe['set_sha256'] = sha(1)
        self.assertTrue(gates.outcome(probe, 'held_up', found))

    def test_the_newest_verdict_for_a_set_wins_whatever_the_file_order(self):
        sha = hashlib.sha256(b'x').hexdigest()
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'a.json').write_text(json.dumps(verdict_node(sha, 'held_up', end='2026-11-06')), encoding='utf-8')
            (Path(root) / 'b.json').write_text(json.dumps(verdict_node(sha, 'failed', end='2026-10-09')), encoding='utf-8')
            found, _ = gates.load_verdicts(Path(root))
        self.assertEqual(found[sha]['verdict'], 'held_up')
        self.assertEqual(found[sha]['evidence_end'], '2026-11-06')


class LeakageTests(unittest.TestCase):
    def test_feature_refuses_a_source_the_target_contains(self):
        sample = record('M1')
        for name in ('fwd_net', 'fwd_pf', 'opt_score', 'file_sr', 'file_arf'):
            with self.assertRaises(ValueError, msg=name):
                gates.feature(sample, name, 'forward')
        for name in ('file_sr', 'file_arf'):
            with self.assertRaises(ValueError, msg=name):
                gates.feature(sample, name, 'post')
        self.assertEqual(gates.feature(sample, 'fwd_net', 'post'), 10.0)
        self.assertEqual(gates.feature(sample, 'file_sr', 'held_up'), 3.0)

    def test_forward_calibration_never_reads_forward_scores_or_file_names(self):
        allowed = gates.allowed_features('forward')
        self.assertFalse([name for name in allowed if name.startswith(('fwd_', 'file_')) or name == 'opt_score'])
        self.assertIn('is_sr', allowed)

    def test_no_feature_is_allowed_to_predict_a_window_it_reads_or_precedes_it(self):
        order = ['back_oos', 'in_sample', 'forward', 'post']
        for name, (source, _, allowed, _) in gates.FEATURES.items():
            for target in allowed:
                if source in order and target in order:
                    self.assertLess(order.index(source), order.index(target), name)
                if source == 'file_name':
                    self.assertEqual(target, 'held_up', name)
                if name == 'opt_score':
                    self.assertNotEqual(target, 'forward')

    def test_a_perfect_but_leaky_predictor_is_never_chosen(self):
        rows = []
        for run in range(6):
            for member in range(20):
                survived = member % 2 == 0
                for index in range(2):
                    rows.append(record('M%03d' % member, run='R%d' % run, survived=survived, is_sr=1.0, index=index,
                                       file_sr=9.0 if survived else 2.6, score=99.0 if survived else 61.0))
        result = gates.recommend(rows, target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['status'], 'fallback_no_qualifying_gate')
        self.assertIsNone(result['gate'])
        self.assertNotIn('file_sr', result['features'])
        self.assertNotIn('opt_score', result['features'])
        self.assertEqual(result['values']['export_changes'], {})


class SurvivalTests(unittest.TestCase):
    def test_isotonic_is_non_decreasing_and_preserves_mass(self):
        fitted = gates.isotonic([1, 0, 0, 1, 0, 1, 1, 0, 1, 1])
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(fitted, fitted[1:])))
        self.assertAlmostEqual(sum(fitted), 6.0)

    def test_curve_is_monotone_member_aggregated_and_signal_is_within_run(self):
        result = gates.recommend(graded(), target='forward', min_survival=0.75, split_keys=())
        curve = result['features']['is_sr']['curve']
        smooth = [point['survival_monotone'] for point in curve]
        self.assertTrue(all(a <= b + 1e-9 for a, b in zip(smooth, smooth[1:])), smooth)
        self.assertGreater(smooth[-1], smooth[0])
        for point in curve:
            self.assertLessEqual(point['kept_members'], point['kept_sets'])
            if point['lower_band'] is not None:
                self.assertLessEqual(point['lower_band'], point['wilson'][0] + 1e-9)
        self.assertEqual(result['features']['is_sr']['direction'], 'higher_is_better')
        self.assertEqual(result['features']['is_pf']['direction'], 'no_clear_signal')

    def test_member_outcomes_are_averaged_before_counting(self):
        rows = [record('A', run='R1', survived=True, index=i) for i in range(9)] + [record('B', run='R1', survived=False)]
        base = gates.recommend(rows, target='forward', split_keys=())['baseline']
        self.assertEqual(base['members'], 2)
        self.assertEqual(base['survival'], 0.5)  # one member of two, not 9 sets of 10

    def test_forward_gate_validates_as_a_diagnostic_only(self):
        result = gates.recommend(graded(), target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['status'], 'validated')
        self.assertFalse(result['actionable'])
        self.assertEqual(result['values']['export_changes'], {})
        self.assertEqual(result['values']['qualify'], gates.DEFAULT_QUALIFY)
        gate, validation = result['gate'], result['validation']
        self.assertIn(gate['feature'], ('is_sr', 'opt_is_sr'))
        self.assertGreaterEqual(validation['lower'], 0.75)
        self.assertGreaterEqual(validation['judged_clusters'], 4)
        self.assertGreaterEqual(gate['threshold'], gate['full_data_threshold'])
        self.assertIn('diagnostic', result['summary'])

    def test_held_up_gate_is_actionable(self):
        rows = graded()
        verdicts = verdicts_for(rows, lambda r: 'held_up' if r['windows']['forward']['net'] > 0 else 'failed')
        result = gates.recommend(rows, target='held_up', verdicts=verdicts, min_survival=0.75, split_keys=())
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(result['actionable'])
        self.assertIn(result['gate']['feature'], result['values']['qualify'])

    def test_a_gate_held_by_a_few_members_does_not_qualify(self):
        rows = []
        for run in range(6):
            for member in range(10):
                rows.append(record('M%03d' % member, run='R%d' % run, is_sr=0.5 + member / 100, survived=member % 2 == 0))
            rows.append(record('H', run='R%d' % run, is_sr=3.0, survived=True))  # six members across six runs
        for index in range(30):
            rows.append(record('H', run='R0', is_sr=3.0, survived=True, index=index + 1))
        result = gates.recommend(rows, target='forward', min_survival=0.6, split_keys=())
        point = next(p for p in result['features']['is_sr']['curve'] if p['threshold'] == 3.0)
        self.assertEqual(point['kept_members'], 6)
        self.assertGreaterEqual(point['kept_sets'], 20)
        self.assertFalse(point['eligible'])
        self.assertTrue(result['gate'] is None or result['gate']['point']['kept_members'] >= 8)

    def test_a_signal_that_only_exists_between_runs_is_not_a_signal(self):
        rows = []
        for run in range(8):
            good = run < 4  # good runs: every member has a high is_sr and survives; bad runs: low and fails
            for member in range(15):
                for index in range(2):
                    rows.append(record('M%03d' % member, run='R%d' % run, index=index, survived=good,
                                       is_sr=(3.0 if good else 0.5) + member / 100))
        result = gates.recommend(rows, target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['features']['is_sr']['direction'], 'no_clear_signal')
        self.assertNotEqual(result['status'], 'validated')

    def test_a_run_that_clearly_misses_blocks_validation(self):
        rows = []
        for run in range(10):
            for member in range(40):
                high = member < 20 if run < 9 else member < 8
                survived = (high and (run < 9 or member < 3))
                rows.append(record('M%03d' % member, run='R%d' % run, is_sr=(3.0 if high else 0.5) + member / 1000,
                                   survived=survived))
        result = gates.recommend(rows, target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['status'], 'fallback_not_validated')
        self.assertEqual(result['validation']['contradicted'], ['R9'])
        self.assertGreaterEqual(result['validation']['lower'], 0.75)  # the pooled number alone would have passed

    def test_point_estimates_never_qualify(self):
        result = gates.recommend(graded(runs=5, members=12, seed=3), target='forward', min_survival=0.85,
                                 min_sets=10, split_keys=())
        for name, info in result['features'].items():
            for point in info['curve']:
                if point['eligible'] and point['lower_band'] is not None and point['survival'] >= 0.85:
                    self.assertLessEqual(point['lower_band'], point['survival'])
        if result['status'] == 'validated':
            self.assertGreaterEqual(result['validation']['lower'], 0.85)


def simulate(seed, sigma, runs=9, members=21, a=-0.5, b=1.2):
    """9 runs x 21 members x 2 near-copy sets; one real signal (is_sr); a shared shock per run."""
    rng, rows = random.Random(seed), []
    for run in range(runs):
        shock = rng.gauss(0, sigma)
        for member in range(members):
            x = rng.uniform(0, 4)
            survived = rng.random() < 1 / (1 + math.exp(-(a + b * x + shock)))
            for index in range(2):
                rows.append(record('M%02d' % member, run='R%d' % run, index=index, survived=survived,
                                   is_sr=round(x + rng.uniform(-0.02, 0.02), 3)))
    return rows


def true_survival(threshold, sigma, a=-0.5, b=1.2):
    """Survival of future members passing the gate, over new run shocks (numerical integral)."""
    shocks = [-4 + 0.1 * i for i in range(81)]
    weights = [math.exp(-u * u / 2) for u in shocks]
    xs = [threshold + (4 - threshold) * (i + 0.5) / 200 for i in range(200)]
    total = sum(w * sum(1 / (1 + math.exp(-(a + b * x + sigma * u))) for x in xs) / len(xs)
                for u, w in zip(shocks, weights))
    return total / sum(weights)


class CoverageSimulationTests(unittest.TestCase):
    """When a gate validates, its true survival must clear the target at least at the
    nominal 97.5% one-sided level, also with run-level shocks (the review's failing case)."""

    def check(self, sigma, target, seeds):
        validated = misses = 0
        base_covered = base_total = 0
        for seed in range(seeds):
            result = gates.recommend(simulate(seed, sigma), target='forward', min_survival=target, split_keys=())
            base_total += 1
            low, high = result['baseline']['interval']
            base_covered += low <= true_survival(0.0, sigma) <= high
            if result['status'] == 'validated':
                validated += 1
                misses += true_survival(result['gate']['threshold'], sigma) < target
        return validated, misses, base_covered / base_total

    def test_validated_gates_hold_their_target_with_run_shocks(self):
        for sigma, target in ((0.0, 0.9), (0.8, 0.85)):
            validated, misses, _ = self.check(sigma, target, 40)
            self.assertGreaterEqual(validated, 5, (sigma, target))     # not vacuous
            self.assertLessEqual(misses / validated, 0.025, (sigma, target, validated, misses))

    def test_baseline_interval_covers_the_true_rate_with_run_shocks(self):
        _, _, coverage = self.check(0.8, 0.99, 40)
        self.assertGreaterEqual(coverage, 0.9)


class FallbackTests(unittest.TestCase):
    def test_thin_evidence_keeps_current_values_and_says_so(self):
        rows = [record('M%d' % (i // 2), index=i, survived=i % 3 != 0, is_sr=i) for i in range(10)]
        result = gates.recommend(rows, target='forward')
        self.assertEqual(result['status'], 'fallback_thin_evidence')
        self.assertIsNone(result['gate'])
        self.assertEqual(result['values']['export_changes'], {})
        self.assertEqual(result['values']['qualify'], gates.DEFAULT_QUALIFY)
        self.assertIn('Keeping the current gates', result['summary'])
        self.assertIn('Only 10 judged sets from 5 members in 1 independent runs', result['summary'])

    def test_many_members_in_too_few_runs_is_still_thin(self):
        rows = graded(runs=3, members=40)
        self.assertEqual(gates.recommend(rows, split_keys=())['status'], 'fallback_thin_evidence')
        rows = graded(runs=6, members=24)
        period = gates.recommend([dict(r, period='one-window') for r in rows], cluster='period', split_keys=())
        self.assertEqual(period['status'], 'fallback_thin_evidence')

    def test_thin_splits_fall_back_while_the_pool_validates(self):
        rows = graded()
        rows += [record('X%d' % i, run='R0', symbol_class='metals', is_sr=3.9, survived=True) for i in range(3)]
        result = gates.recommend(rows, target='forward', min_survival=0.75)
        self.assertEqual(result['by_split']['symbol_class=metals']['status'], 'fallback_thin_evidence')
        self.assertNotIn('symbol_class=metals', result['values']['qualify_by_split'])
        self.assertIn('too thin', result['summary'])

    def test_no_signal_falls_back(self):
        rng = random.Random(5)
        rows = [record('M%03d' % m, run='R%d' % (m % 6), index=i, survived=rng.random() < 0.5, is_sr=rng.uniform(0, 4))
                for m in range(120) for i in range(2)]
        result = gates.recommend(rows, target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['status'], 'fallback_no_qualifying_gate')
        self.assertEqual(result['values']['export_changes'], {})

    def test_a_tail_without_overall_signal_is_not_chosen(self):
        rows = []
        for run in range(6):
            for member in range(40):  # low and high is_sr survive, the middle fails: within-run AUC ~0.5
                survived = member < 10 or member >= 30
                for index in range(2):
                    rows.append(record('M%03d' % member, run='R%d' % run, index=index, is_sr=member / 10,
                                       survived=survived))
        result = gates.recommend(rows, target='forward', min_survival=0.75, split_keys=())
        self.assertEqual(result['features']['is_sr']['direction'], 'no_clear_signal')
        self.assertEqual(result['status'], 'fallback_no_qualifying_gate')
        self.assertIsNone(result['gate'])

    def test_defaults_already_meet_target(self):
        rows = [record('M%03d' % m, run='R%d' % (m % 5), index=i, survived=True, is_sr=m / 10)
                for m in range(40) for i in range(2)]
        self.assertEqual(gates.recommend(rows, min_survival=0.6, split_keys=())['status'], 'defaults_already_meet_target')

    def test_plan_fields_move_only_on_held_up_and_never_below_the_floor(self):
        rows = []
        for run in range(6):
            for member in range(30):
                rows.append(record('M%03d' % member, run='R%d' % run, score=40 + 2 * member, survived=True))
        verdicts = verdicts_for(rows, lambda r: 'held_up' if r['optimizer']['Score'] >= 50 else 'failed')
        post = gates.recommend(rows, target='post', min_survival=0.9, split_keys=())
        self.assertEqual(post['values']['export_changes'], {})
        result = gates.recommend(rows, target='held_up', verdicts=verdicts, min_survival=0.9, split_keys=())
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['gate']['feature'], 'opt_score')
        self.assertEqual(result['gate']['plan_field'], 'MinScore')
        self.assertGreaterEqual(result['gate']['threshold'], 60.0)
        self.assertGreaterEqual(result['values']['export_changes']['MinScore'], 60.0)
        below = [p for p in result['features']['opt_score']['curve'] if p['threshold'] < 60]
        self.assertTrue(below)
        self.assertTrue(any(p['eligible'] and p['lower_band'] >= 0.9 for p in below))  # only the floor stops them


class StampTests(unittest.TestCase):
    def plan(self, root, **export):
        path = Path(root) / 'plan.json'
        values = dict(SetsToExport=2, MinScore=60.0, TargetDD=100, AdjustLots=False, BackOOSDate='2025.01.06',
                      MinARF=0.2, MinSR=2.5, IncludeBackOOS=True, IncludeSequenceData=True)
        values.update(export)
        path.write_text(json.dumps(dict(schema_version=1, export=values, members=[dict(set_path='C:/x.set', tester={})]),
                                   indent=2), encoding='utf-8')
        return path

    def held_up(self, changes):
        rows = graded()
        verdicts = verdicts_for(rows, lambda r: 'held_up' if r['windows']['forward']['net'] > 0 else 'failed')
        result = gates.recommend(rows, target='held_up', verdicts=verdicts, min_survival=0.75, split_keys=())
        self.assertTrue(result['actionable'])
        result['values']['export_changes'] = dict(changes)
        return result

    def test_stamp_only_tightens_explicit_plan_values(self):
        with tempfile.TemporaryDirectory() as root:
            plan = self.plan(root, MinSR=3.0, MinScore=70.0, MinARF=0.3, SetsToExport=4, TargetDD=150)
            looser = gates.stamp_plan(plan, self.held_up(dict(MinSR=2.6)), Path(root) / 'a.json',
                                      generated_at='2026-10-02T12:00:00Z')
            self.assertEqual(looser['applied'], {})
            self.assertEqual(Path(looser['plan']).read_bytes(), plan.read_bytes())
            stricter = gates.stamp_plan(plan, self.held_up(dict(MinSR=3.4)), Path(root) / 'b.json',
                                        generated_at='2026-10-02T12:00:00Z')
            export = json.loads(Path(stricter['plan']).read_text(encoding='utf-8'))['export']
            self.assertEqual(export['MinSR'], 3.4)
            self.assertEqual((export['MinScore'], export['MinARF'], export['SetsToExport'], export['TargetDD']),
                             (70.0, 0.3, 4, 150))
            self.assertEqual(stricter['applied'], dict(MinSR=dict(before=3.0, after=3.4)))

    def test_fallback_and_diagnostics_never_change_a_plan(self):
        with tempfile.TemporaryDirectory() as root:
            plan = self.plan(root, MinSR=3.0, MinScore=70.0)
            rows = graded(runs=2)
            verdicts = verdicts_for(rows, lambda r: 'held_up')
            fallback = gates.recommend(rows, target='held_up', verdicts=verdicts, split_keys=())
            self.assertFalse(fallback['actionable'])
            out = gates.stamp_plan(plan, fallback, Path(root) / 'c.json', generated_at='2026-10-02T12:00:00Z')
            self.assertEqual(Path(out['plan']).read_bytes(), plan.read_bytes())
            forward = gates.recommend(graded(), target='forward', min_survival=0.75, split_keys=())
            with self.assertRaises(ValueError):
                gates.stamp_plan(plan, forward, Path(root) / 'd.json', generated_at='2026-10-02T12:00:00Z')

    def test_stamp_is_deterministic(self):
        first = self.held_up(dict(MinSR=3.4))
        rows = graded(); shuffled = list(rows); random.Random(1).shuffle(shuffled)
        verdicts = verdicts_for(rows, lambda r: 'held_up' if r['windows']['forward']['net'] > 0 else 'failed')
        again = gates.recommend(shuffled, target='held_up', verdicts=verdicts, min_survival=0.75, split_keys=())
        self.assertEqual(first['evidence_digest'], again['evidence_digest'])
        self.assertEqual(first['gate']['threshold'], again['gate']['threshold'])
        with tempfile.TemporaryDirectory() as root:
            plan = self.plan(root)
            one = gates.stamp_plan(plan, first, Path(root) / 'a' / 'plan.json', generated_at='2026-10-02T12:00:00Z')
            two = gates.stamp_plan(plan, gates.public(first), Path(root) / 'b' / 'plan.json',
                                   generated_at='2026-10-02T12:00:00Z')
            self.assertEqual(Path(one['plan']).read_bytes(), Path(two['plan']).read_bytes())
            self.assertEqual(Path(one['sidecar']).read_bytes(), Path(two['sidecar']).read_bytes())
            stamped = json.loads(Path(one['plan']).read_text(encoding='utf-8'))
            self.assertEqual(set(stamped), {'schema_version', 'export', 'members'})
            from studio_settings import validate_export
            validate_export(stamped['export'])
            sidecar = json.loads(Path(one['sidecar']).read_text(encoding='utf-8'))['gates']
            self.assertTrue(set(sidecar) >= {'values', 'method', 'evidence_digest', 'generated_at', 'plan_sha256'})
            self.assertEqual(sidecar['plan_sha256'], hashlib.sha256(Path(one['plan']).read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                gates.stamp_plan(plan, first, Path(one['plan']), generated_at='2026-10-02T12:00:00Z')
            with self.assertRaises(ValueError):
                gates.stamp_plan(plan, first, plan, generated_at='2026-10-02T12:00:00Z')
            with self.assertRaises(ValueError):
                gates.stamp_plan(plan, first, Path(root) / 'c.json', generated_at='now')

    def test_apply_qualify_fails_missing_numbers_and_honours_split_overrides(self):
        sample = record('M1', is_sr=2.0, symbol_class='indices')
        values = dict(qualify=dict(is_sr=1.5), qualify_by_split={'symbol_class=indices': dict(is_sr=2.5)})
        passes, failures = gates.apply_qualify(sample, values)
        self.assertFalse(passes)
        self.assertEqual(failures[0]['threshold'], 2.5)
        sample['windows']['in_sample']['sr'] = None
        self.assertFalse(gates.apply_qualify(sample, dict(qualify=dict(is_sr=0.0)))[0])


class FillerComparisonTests(unittest.TestCase):
    def test_fillers_are_compared_only_within_run_and_symbol_on_held_up(self):
        rows = []
        for run in range(5):
            for member in range(12):
                rows.append(record('M%02d' % member, run='R%d' % run, filler=member >= 6))
        self.assertEqual(gates.filler_comparison(rows, None)['status'], 'no_held_up_verdicts')
        verdicts = verdicts_for(rows, lambda r: 'failed' if r['filler'] else 'held_up')
        result = gates.filler_comparison(rows, verdicts)
        self.assertEqual(result['status'], 'compared')
        self.assertEqual(result['passed_minus_filler'], 1.0)
        self.assertEqual(result['per_run']['R0']['fillers'], 6)


class ReadOnlyTests(unittest.TestCase):
    @staticmethod
    def snapshot(root):
        result = {}
        for path in sorted(Path(root).rglob('*')):
            stat = path.stat()
            result[str(path.relative_to(root))] = (path.is_dir(), stat.st_size, stat.st_mtime_ns,
                                                   None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def build(self, root):
        common = Path(root) / 'GOAT'
        for run in range(4):
            members = [('A%02d' % i, 'EURUSD' if i % 2 else 'WS30') for i in range(6)]
            write_manifest(common, 'R%d' % run, members)
            for i, (alias, symbol) in enumerate(members):
                for k in range(2):
                    write_set(common, 'R%d' % run, alias, symbol,
                              dict(back_oos=1.0, in_sample=1.0 + i, forward=1.0 if i > 1 else -1.0, post=1.0),
                              grid=-2.25 - k, rsi=5 + i + 10 * run, score=70 + i)
        return common

    def test_recommendation_reads_evidence_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            common = self.build(root)
            before = self.snapshot(root)
            result = gates.gate_recommend(common_root=common, target='forward')
            self.assertEqual(self.snapshot(root), before)
            self.assertEqual(result['evidence']['sets'], 48)
            self.assertIn('summary', result)
            self.assertEqual(result['fillers']['status'], 'no_held_up_verdicts')

    @unittest.skipUnless(sys.platform == 'win32', 'demo_agent imports the Windows-only msvcrt')
    def test_cli_writes_only_its_output(self):
        import demo_agent
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            common = self.build(root)
            before = self.snapshot(root)
            output = Path(out) / 'recommendation.json'
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = demo_agent.main(['--installation', str(Path(out) / 'never-read.json'), 'gate-recommend',
                                        '--common-root', str(common), '--target', 'forward', '--output', str(output)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(self.snapshot(root), before)
            self.assertEqual(sorted(p.name for p in Path(out).iterdir()), ['recommendation.json'])
            reply = json.loads(stdout.getvalue())
            self.assertTrue(reply['ok'])
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['evidence_digest'], reply['result']['evidence_digest'])
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(demo_agent.main(['--installation', 'x', 'gate-recommend', '--common-root', str(common),
                                                  '--output', str(output)]), 1)
            plan = StampTests.plan(self, out)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(demo_agent.main(['--installation', 'x', 'gate-stamp', '--plan', str(plan),
                                                  '--recommendation', str(output), '--output', str(Path(out) / 's.json'),
                                                  '--generated-at', '2026-10-02T12:00:00Z']), 1)
            self.assertIn('Only held_up', err.getvalue())
            self.assertEqual(self.snapshot(root), before)


if __name__ == '__main__':
    unittest.main()
