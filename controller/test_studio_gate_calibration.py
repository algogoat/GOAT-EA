"""Gate calibration: window split, monotone survival, thin-data fallback, leakage guard,
deterministic stamp and read-only behaviour. Synthetic fixtures copy the real export
file shapes (UTF-16 equity CSV and SET siblings, UTF-8 capture files, UTF-16
SpreadsheetML optimizer rows that declare UTF-8); no real data is used."""
from datetime import date, datetime, timedelta
import hashlib
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


def write_manifest(root, run, members):
    jobs = [dict(run_alias=alias, tester=dict(Symbol=symbol, Period='M1', FromDate=START.strftime('%Y.%m.%d'),
                                              ForwardDate=FORWARD.strftime('%Y.%m.%d'), ToDate=TO.strftime('%Y.%m.%d')))
            for alias, symbol in members]
    path = Path(root) / run / 'manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(schema_version=1, export_settings=dict(
        gates.DEFAULT_EXPORT, BackOOSDate=BOOS.strftime('%Y.%m.%d'), IncludeBackOOS=True, AdjustLots=False,
        IncludeSequenceData=True), jobs=jobs)), encoding='utf-8')


def record(member, *, run='R1', survived=True, is_sr=1.0, fwd_net=None, file_sr=3.0, score=80.0, index=0,
           symbol_class='fx_majors', post_survived=None):
    """A loaded-evidence record without files, for the statistics tests."""
    window = lambda net, first, end, **extra: dict(dict(first_day=first.isoformat(), end_day=end.isoformat(), weekdays=20,
                                                        trades=40, net=net, dd=10.0, pf=1.5, recovery=1.0, sr=1.0, arf=0.1), **extra)
    windows = dict(back_oos=window(5.0, BOOS, START), in_sample=window(100.0, START, FORWARD, sr=is_sr),
                   forward=window(fwd_net if fwd_net is not None else (10.0 if survived else -10.0), FORWARD, TO),
                   post=window(10.0 if (post_survived if post_survived is not None else survived) else -10.0, TO, END))
    return dict(run=run, member=member, set_sha256=hashlib.sha256(('%s/%d' % (member, index)).encode()).hexdigest(),
                symbol_class=symbol_class, family='RSI+EMA', timeframe='TF15', design='IS4m/F5w/B4w',
                windows=windows, observed_end=END.isoformat(), optimizer={'Score': score, 'SR(Back)': is_sr,
                                                                          'PF(Back)': 1.5, 'RF(Back)': 2.0},
                file_name=dict(trades=100, net=100.0, dd=10.0, pf=1.5, sr=file_sr, arf=0.3), path=member)


def graded(n_members=120, seed=7, sets_per_member=2):
    """Forward survival rises with is_sr; nothing else carries signal."""
    rng, rows = random.Random(seed), []
    for member in range(n_members):
        level = member / n_members * 4
        for index in range(sets_per_member):
            value = round(level + rng.uniform(-0.05, 0.05), 3)
            rows.append(record('M%03d' % member, is_sr=value, survived=rng.random() < 0.1 + 0.9 * member / n_members,
                               index=index))
    return rows


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
            self.assertEqual(windows['in_sample']['pf'], 25.0)
            self.assertLess(windows['forward']['recovery'], 0)
            self.assertEqual(record_['optimizer']['Score'], 91.5)
            self.assertEqual(record_['file_name']['sr'], 3.45)
            self.assertEqual(record_['symbol_class'], 'fx_majors')
            self.assertEqual(record_['family'], 'RSI+EMA')
            self.assertEqual(record_['timeframe'], 'TF15')
            self.assertEqual(record_['capture'], 'complete')

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

    def test_symbol_classes(self):
        self.assertEqual(gates.symbol_class('EURUSD'), 'fx_majors')
        self.assertEqual(gates.symbol_class('GBPNZD'), 'fx_crosses')
        self.assertEqual(gates.symbol_class('WS30'), 'indices')
        self.assertEqual(gates.symbol_class('XAGUSD'), 'metals')


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
        # file_sr and Score separate survivors perfectly; nothing clean does.
        rows = []
        for member in range(80):
            survived = member % 2 == 0
            for index in range(2):
                rows.append(record('M%03d' % member, survived=survived, is_sr=1.0, index=index,
                                   file_sr=9.0 if survived else 2.6, score=99.0 if survived else 61.0))
        result = gates.recommend(rows, target='forward', min_survival=0.8)
        self.assertEqual(result['status'], 'fallback_no_qualifying_gate')
        self.assertIsNone(result['gate'])
        self.assertNotIn('file_sr', result['features'])
        self.assertNotIn('opt_score', result['features'])
        self.assertEqual(result['values']['export'], gates.DEFAULT_EXPORT)


class SurvivalTests(unittest.TestCase):
    def test_isotonic_is_non_decreasing_and_preserves_mass(self):
        fitted = gates.isotonic([1, 0, 0, 1, 0, 1, 1, 0, 1, 1])
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(fitted, fitted[1:])))
        self.assertAlmostEqual(sum(fitted), 6.0)

    def test_survival_curve_is_monotone_and_counts_members(self):
        rows = graded()
        result = gates.calibrate(rows, target='forward')
        curve = result['features']['is_sr']['curve']
        smooth = [point['survival_monotone'] for point in curve]
        self.assertTrue(all(a <= b + 1e-9 for a, b in zip(smooth, smooth[1:])), smooth)
        self.assertGreater(smooth[-1], smooth[0])
        for point in curve:
            low, high = gates.wilson(point['survival'] * point['kept_members'], point['kept_members'])
            self.assertAlmostEqual(point['interval'][0], low, delta=3e-4)
            self.assertAlmostEqual(point['interval'][1], high, delta=3e-4)
            self.assertLessEqual(point['kept_members'], point['kept_sets'])
        self.assertEqual(result['features']['is_sr']['direction'], 'higher_is_better')
        self.assertEqual(result['features']['is_pf']['direction'], 'no_clear_signal')

    def test_recommends_the_loosest_gate_whose_lower_bound_meets_the_target(self):
        rows = graded()
        result = gates.recommend(rows, target='forward', min_survival=0.7)
        self.assertEqual(result['status'], 'calibrated')
        gate = result['gate']
        self.assertIn(gate['feature'], ('is_sr', 'opt_is_sr'))
        self.assertGreaterEqual(gate['point']['interval'][0], 0.7)
        self.assertGreaterEqual(gate['point']['kept_sets'], 20)
        self.assertGreaterEqual(gate['point']['kept_members'], 8)
        looser = [p for p in result['features'][gate['feature']]['curve'] if p['threshold'] < gate['threshold']]
        self.assertFalse([p for p in looser if p['qualifies']])
        self.assertEqual(result['values']['qualify'][gate['feature']], gate['threshold'])
        self.assertEqual(result['values']['export'], gates.DEFAULT_EXPORT)
        self.assertIn('Recommended gate', result['summary'])

    def test_point_estimate_alone_never_qualifies_by_default(self):
        rows = graded(n_members=40, seed=3)
        lower = gates.recommend(rows, target='forward', min_survival=0.8, min_sets=10, min_members=8)
        point = gates.recommend(rows, target='forward', min_survival=0.8, min_sets=10, min_members=8, confidence='point')
        if lower['gate'] and point['gate']:
            self.assertGreaterEqual(point['gate']['point']['kept_sets'], lower['gate']['point']['kept_sets'])
        for name, info in lower['features'].items():
            for p in info['curve']:
                if p['qualifies']:
                    self.assertGreaterEqual(p['interval'][0], 0.8, name)
        self.assertTrue(any(p['qualifies'] and p['interval'][0] < 0.8
                            for info in point['features'].values() for p in info['curve']))

    def test_a_gate_concentrated_in_few_members_does_not_qualify(self):
        rows = []
        for member in range(30):
            rows.append(record('M%03d' % member, is_sr=0.5, survived=member % 2 == 0))
        for member in range(6):  # six members (< 8), near-copy sets, all survived, high is_sr
            for index in range(5):
                rows.append(record('H%d' % member, is_sr=3.0, survived=True, index=index))
        result = gates.recommend(rows, target='forward', min_survival=0.6)
        point = next(p for p in result['features']['is_sr']['curve'] if p['threshold'] == 3.0)
        self.assertEqual(point['kept_members'], 6)
        self.assertEqual(point['kept_sets'], 30)
        self.assertGreaterEqual(point['interval'][0], 0.6)  # the interval alone would admit it
        self.assertFalse(point['qualifies'])
        self.assertTrue(result['gate'] is None or result['gate']['point']['kept_members'] >= 8)


class FallbackTests(unittest.TestCase):
    def test_thin_evidence_keeps_current_defaults_and_says_so(self):
        rows = [record('M%d' % (i // 2), index=i, survived=i % 3 != 0, is_sr=i) for i in range(10)]
        result = gates.recommend(rows, target='forward')
        self.assertEqual(result['status'], 'fallback_thin_evidence')
        self.assertIsNone(result['gate'])
        self.assertEqual(result['values']['export'], gates.DEFAULT_EXPORT)
        self.assertEqual(result['values']['qualify'], gates.DEFAULT_QUALIFY)
        self.assertIn('Keeping the current gates', result['summary'])
        self.assertIn('Only 10 judged sets from 5 members', result['summary'])

    def test_many_sets_from_few_members_is_still_thin(self):
        rows = [record('M%d' % (i % 4), index=i, survived=i % 2 == 0, is_sr=i / 10) for i in range(60)]
        self.assertEqual(gates.recommend(rows)['status'], 'fallback_thin_evidence')

    def test_thin_splits_fall_back_while_the_pool_calibrates(self):
        rows = graded()
        rows += [record('X%d' % i, symbol_class='metals', is_sr=3.9, survived=True) for i in range(3)]
        result = gates.recommend(rows, target='forward', min_survival=0.7)
        self.assertEqual(result['by_split']['symbol_class=metals']['status'], 'fallback_thin_evidence')
        self.assertNotIn('symbol_class=metals', result['values']['qualify_by_split'])
        self.assertIn('thin', result['summary'])

    def test_no_signal_falls_back(self):
        rng = random.Random(5)
        rows = [record('M%03d' % m, index=i, survived=rng.random() < 0.5, is_sr=rng.uniform(0, 4))
                for m in range(80) for i in range(2)]
        result = gates.recommend(rows, target='forward', min_survival=0.8)
        self.assertIn(result['status'], ('fallback_no_qualifying_gate',))
        self.assertEqual(result['values']['export'], gates.DEFAULT_EXPORT)

    def test_defaults_already_meet_target(self):
        rows = [record('M%03d' % m, index=i, survived=True, is_sr=m / 10) for m in range(40) for i in range(2)]
        self.assertEqual(gates.recommend(rows, min_survival=0.6)['status'], 'defaults_already_meet_target')

    def test_plan_fields_never_drop_below_the_floor(self):
        rows = []
        for member in range(60):
            for index in range(2):
                rows.append(record('M%03d' % member, index=index, post_survived=member >= 20, score=20 + member))
        result = gates.recommend(rows, target='post', min_survival=0.7)
        self.assertEqual(result['status'], 'calibrated')
        self.assertEqual(result['gate']['feature'], 'opt_score')
        self.assertEqual(result['gate']['plan_field'], 'MinScore')
        self.assertGreaterEqual(result['gate']['threshold'], 60.0)
        self.assertGreaterEqual(result['values']['export']['MinScore'], 60.0)
        below = [p for p in result['features']['opt_score']['curve'] if p['threshold'] < 60]
        self.assertTrue(below and not any(p['qualifies'] for p in below))
        for field, floor in gates.EXPORT_FLOORS.items():
            self.assertGreaterEqual(result['values']['export'][field], floor)


class StampTests(unittest.TestCase):
    def plan(self, root):
        path = Path(root) / 'plan.json'
        path.write_text(json.dumps(dict(schema_version=1, export=dict(
            SetsToExport=2, MinScore=60.0, TargetDD=100, AdjustLots=False, BackOOSDate='2025.01.06', MinARF=0.2,
            MinSR=2.5, IncludeBackOOS=True, IncludeSequenceData=True), members=[dict(set_path='C:/x.set', tester={})])),
            encoding='utf-8')
        return path

    def test_stamp_is_deterministic_and_keeps_the_plan_valid(self):
        rows = graded()
        shuffled = list(rows); random.Random(1).shuffle(shuffled)
        first, second = gates.recommend(rows, min_survival=0.7), gates.recommend(shuffled, min_survival=0.7)
        self.assertEqual(first['evidence_digest'], second['evidence_digest'])
        self.assertEqual(first['values'], second['values'])
        with tempfile.TemporaryDirectory() as root:
            plan = self.plan(root)
            before = plan.read_bytes()
            one = gates.stamp_plan(plan, first, Path(root) / 'a' / 'plan.json', generated_at='2026-10-02T12:00:00Z')
            two = gates.stamp_plan(plan, gates.public(second), Path(root) / 'b' / 'plan.json',
                                   generated_at='2026-10-02T12:00:00Z')
            self.assertEqual(plan.read_bytes(), before)
            self.assertEqual(Path(one['plan']).read_bytes(), Path(two['plan']).read_bytes())
            self.assertEqual(Path(one['sidecar']).read_bytes(), Path(two['sidecar']).read_bytes())
            stamped = json.loads(Path(one['plan']).read_text(encoding='utf-8'))
            self.assertEqual(set(stamped), {'schema_version', 'export', 'members'})
            from studio_settings import validate_export
            validate_export(stamped['export'])
            sidecar = json.loads(Path(one['sidecar']).read_text(encoding='utf-8'))['gates']
            self.assertEqual(set(sidecar) >= {'values', 'method', 'evidence_digest', 'generated_at'}, True)
            self.assertEqual(sidecar['plan_sha256'], hashlib.sha256(Path(one['plan']).read_bytes()).hexdigest())
            self.assertEqual(sidecar['evidence_digest'], first['evidence_digest'])
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


class ReadOnlyTests(unittest.TestCase):
    @staticmethod
    def snapshot(root):
        result = {}
        for path in sorted(Path(root).rglob('*')):
            stat = path.stat()
            result[str(path.relative_to(root))] = (path.is_dir(), stat.st_size, stat.st_mtime_ns,
                                                   None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def test_cli_reads_evidence_and_writes_only_its_output(self):
        import demo_agent
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            common = Path(root) / 'GOAT'
            members = [('A%02d' % i, 'EURUSD' if i % 2 else 'WS30') for i in range(12)]
            write_manifest(common, 'R1', members)
            for i, (alias, symbol) in enumerate(members):
                for k in range(2):
                    write_set(common, 'R1', alias, symbol, dict(back_oos=1.0, in_sample=1.0 + i, forward=1.0 if i > 3 else -1.0,
                                                                post=1.0), grid=-2.25 - k, rsi=5 + i, score=70 + i)
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
            self.assertEqual(reply['result']['evidence']['sets'], 24)
            self.assertIn('summary', reply['result'])
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['evidence_digest'], reply['result']['evidence_digest'])
            # Repeating never overwrites the output.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(demo_agent.main(['--installation', 'x', 'gate-recommend', '--common-root', str(common),
                                                  '--output', str(output)]), 1)
            plan = StampTests.plan(self, out)
            stamped = Path(out) / 'stamped' / 'plan.json'
            with redirect_stdout(io.StringIO()) as stamp_out, redirect_stderr(io.StringIO()):
                self.assertEqual(demo_agent.main(['--installation', 'x', 'gate-stamp', '--plan', str(plan),
                                                  '--recommendation', str(output), '--output', str(stamped),
                                                  '--generated-at', '2026-10-02T12:00:00Z']), 0)
            self.assertTrue(json.loads(stamp_out.getvalue())['ok'])
            self.assertEqual(self.snapshot(root), before)
            self.assertTrue((stamped.parent / 'plan.json.gates.json').is_file())


if __name__ == '__main__':
    unittest.main()
