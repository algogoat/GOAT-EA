"""oos-rule-recount (studio_oos_recount): stored catch-ups judged again under every OOS window rule version.

The catch-up here is a real one: the CatchupRunner prepares it, a fake terminal writes each member's re-test unit
and the runner collects, judges and stores it (test_studio_catchup.CatchupCase). The exports carry OOS formula
dates (O = 13 weeks, export Friday 2026-10-02), so every stored result holds a judged ``oos_rule``. The recount
then reads that stored catch-up and must (1) reproduce each stored verdict under the version it was judged with,
(2) write nothing anywhere and (3) never reach a terminal, a lease, a process or the broker.
"""
import ast
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, time, timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import studio_catchup as sc
import studio_oos_recount as recount
import studio_oos_windows as w
from studio_installation import read_json
from test_studio_catchup import CatchupCase
from test_studio_catchup_verdict import daily, make_unit, trading
from test_studio_heldout import declaration, write_registry

# What each member's evidence is built to show (see FormulaCase.SCENARIOS), per rule version.
EXPECTED = {
    'v1': dict(EURUSD='pass', GBPUSD='fail', USDJPY='fail', AUDUSD='fail', USDCAD='not_eligible_yet', NZDUSD='pass'),
    # Rule version 2: GBPUSD's BOOS loss no longer fails at O = 13 weeks (the loss leg applies from 12 months); USDJPY's FOOS
    # drawdown is within 1.5 x SAMPLE+FWD's.
    'v2': dict(EURUSD='pass', GBPUSD='pass', USDJPY='pass', AUDUSD='fail', USDCAD='not_eligible_yet', NZDUSD='pass'),
}


def d(text):
    return date.fromisoformat(text)


class FormulaCase(CatchupCase):
    """Six kept exports of one formula batch (BOOS 2026-05-02, SAMPLE 06-06, FWD 08-01, optimization end 09-04) and
    their catch-up to the export Friday 2026-10-02. Equity rises 10 a weekday; each window has one intraday dip."""

    # boos: result of each BOOS trade; fwd_dip / foos_dip: the window's equity dip; foos_per_day: FOOS trades a weekday.
    BASE = dict(boos=5.1, sample_dip=100, fwd_dip=0, foos_dip=50, foos_per_day=2)
    SCENARIOS = dict(
        EURUSD=dict(),                               # every bar met
        GBPUSD=dict(boos=-1.0),                      # BOOS lost 60 over 50 trades; every SAMPLE window made money
        USDJPY=dict(fwd_dip=140, foos_dip=180),      # FOOS drawdown above 1.5 x SAMPLE's 100, within 1.5 x SAMPLE+FWD's 140
        AUDUSD=dict(fwd_dip=140, foos_dip=250),      # FOOS drawdown above both
        USDCAD=dict(foos_per_day=1),                 # 20 FOOS trades: under the 30-trade floor
        NZDUSD=dict())                               # every bar met (the tests break this one's files)

    def setUp(self):
        super().setUp()
        self.record = w.compute(13, '2026-10-02')
        self.formula_run = self.root / 'GOAT' / 'Rformula1'
        (self.formula_run / 'deploy').mkdir(parents=True)
        text = ('[Export]\r\nAdjustLots=0\r\nBackOOSDate=%s\r\nIncludeBackOOS=1\r\nMinARF=0.2\r\nMinSR=2.5\r\nSetsToExport=2\r\n'
                % self.record['export']['BackOOSDate'])
        (self.formula_run / 'export_settings.GOAT').write_bytes(text.encode('utf-16'))
        self.optimization_end = d(self.record['optimization_end'])
        self.aliases, self.sets = {}, []
        for number, symbol in enumerate(self.SCENARIOS, 1):
            alias = 'Rform%05d' % number
            self.aliases[symbol] = alias
            rows = self.rows(symbol, self.optimization_end)
            forced = (datetime.combine(self.optimization_end, time(23, 59)), rows[-1][1], rows[-1][2])
            self.sets.append(make_unit(self.formula_run / 'deploy' / alias / symbol, rows=rows + [forced],
                                       deals=self.trades(symbol, self.optimization_end), alias=alias, symbol=symbol,
                                       start=d(self.record['boos']['first_day']), windows=self.header()))
        tester = dict(self.record['tester'], Period='M1', Deposit=10000, Currency='USD', Leverage='1:100', ExecutionMode=0)
        tester.pop('ForwardMode')
        jobs = [dict(run_alias=alias, tester=dict(tester, Symbol=symbol)) for symbol, alias in self.aliases.items()]
        (self.formula_run / 'manifest.json').write_text(json.dumps(dict(ea_sha256=hashlib.sha256(b'ex5').hexdigest(), jobs=jobs)),
                                                        encoding='utf-8')

    def scenario(self, symbol):
        return dict(self.BASE, **self.SCENARIOS[symbol])

    def window(self, key, through):
        first, last = d(self.record[key]['first_day']), min(d(self.record[key]['last_day']), through)
        return (first, last) if first <= last else None

    def rows(self, symbol, through):
        scenario, value, rows = self.scenario(symbol), 10000, []
        for key, depth in (('boos', 50), ('sample', scenario['sample_dip']), ('fwd', scenario['fwd_dip']), ('foos', scenario['foos_dip'])):
            span = self.window(key, through)
            if span is None:
                continue
            dip = [(span[0] + timedelta(days=9), depth)] if depth else []      # the window's second Monday
            part = daily(span[0], span[1], value, 10, dips=dip)
            rows, value = rows + part, part[-1][1]
        return rows

    def trades(self, symbol, through):
        scenario, deals = self.scenario(symbol), []
        for key, per_day, result in (('boos', 2, scenario['boos']), ('sample', 2, 5.1), ('fwd', 2, 5.1),
                                     ('foos', scenario['foos_per_day'], 6.0)):
            span = self.window(key, through)
            if span is not None:
                deals += trading(span[0], span[1], per_day, result)
        return deals

    def header(self, foos_through=None):
        r = self.record
        lines = [('BOOS', d(r['boos']['first_day']), d(r['sample']['first_day']), 50, 245),
                 ('FWD', d(r['fwd']['first_day']), d(r['foos']['first_day']), 50, 245)]
        if foos_through is not None:
            lines.append(('FOOS', d(r['foos']['first_day']) + timedelta(days=1), foos_through, 40, 232))
        return lines

    def native_retest(self, member, *, new_per_day=10):
        """The re-test unit the EA writes for one member: the original's rows and deals again, then the FOOS weeks."""
        tester = member['tester']
        to_date = datetime.strptime(tester['ToDate'], '%Y.%m.%d').date()
        last = to_date - timedelta(days=1)
        folder = Path(self.controller.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'attempt-issued.json').write_text('{}', encoding='utf-8')
        ran = sc._tester_inputs_section(Path(member['config_path']).read_bytes())
        values = {name: ran[name].split('||')[0] for name in ('Mode_Operation', 'Lots_Input', 'Grid_Size') if name in ran}
        return make_unit(folder, rows=self.rows(tester['Symbol'], last), deals=self.trades(tester['Symbol'], last),
                         alias=member['alias'], symbol=tester['Symbol'], run_id=member['capture_id'], values=values,
                         start=datetime.strptime(tester['FromDate'], '%Y.%m.%d').date(), requested_to=to_date,
                         windows=self.header(last))

    def run_catchup(self, catchup_id='cu1', symbols=None, stored_version=None):
        """Prepare, run and collect the catch-up. ``stored_version=1``: store it as a controller before rule version 2
        did: judged under version 1 (the default of that time) and with no ``ruleVersion`` on any ``oos_rule``."""
        self.catchup_id = catchup_id
        wanted = [path for path in self.sets if symbols is None or path.parent.name in symbols]
        self.runner.prepare(catchup_id, dict(schema_version=1, evidence_end='auto', sets=[str(p) for p in wanted],
                                             job_timeout_seconds=3600))
        self.auto, self.starts = True, []
        if self.process_state is None:
            self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='monitor')
        with patch.object(w, 'RULE_VERSION', w.RULE_VERSION if stored_version is None else stored_version):
            state = self.runner.start(catchup_id, 600)
        self.assertEqual(state['status'], 'completed', state)
        if stored_version == 1:
            folder = self.runner.path(catchup_id)
            state = read_json(folder / 'state.json')
            for item in state['members']:
                result = read_json(item['result']['path'])
                self.assertEqual(result['verdict']['oos_rule'].pop('ruleVersion'), 1)
                Path(item['result']['path']).write_text(json.dumps(result), encoding='utf-8')
                item['result']['sha256'] = hashlib.sha256(Path(item['result']['path']).read_bytes()).hexdigest()
            (folder / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        return read_json(self.runner.path(catchup_id) / 'manifest.json')

    def stored(self, catchup_id='cu1'):
        """{symbol: the oos_rule the catch-up stored}, read from each member's result file."""
        state = read_json(self.runner.path(catchup_id) / 'state.json')
        manifest = read_json(self.runner.path(catchup_id) / 'manifest.json')
        return {spec['tester']['Symbol']: read_json(item['result']['path'])['verdict']['oos_rule']
                for spec, item in zip(manifest['members'], state['members'])}

    def snapshot(self):
        """Every file and folder under the test's temp root: path, size, mtime and SHA-256."""
        entries = {}
        for path in sorted(self.root.rglob('*')):
            stat = path.stat()
            entries[str(path)] = ('dir',) if path.is_dir() else (stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        return entries

    def recount(self, *ids, every=False):
        return recount.recount(self.controller.root, list(ids), every=every)

    def rows_by_symbol(self, block):
        return {row['symbol']: row for row in block['members']}


class RecountTests(FormulaCase):
    def check_stored(self, version):
        self.run_catchup(stored_version=version)
        stored = self.stored()
        self.assertEqual({symbol: rule['status'] for symbol, rule in stored.items()}, EXPECTED[recount.label(version)])
        self.assertEqual({rule['schema'] for rule in stored.values()}, {w.EVALUATION})
        self.assertEqual({rule.get('ruleVersion') for rule in stored.values()}, {None if version == 1 else version})
        self.assertEqual({w.record_rule_version(rule) for rule in stored.values()}, {version})
        # The windows are the formula's and BOOS has 4 rolling SAMPLE windows of its own length (O = 13 weeks).
        boos = stored['GBPUSD']['windows']['boos']
        self.assertEqual((boos['trades'], boos['in_sample_windows']), (50, 4))
        self.assertAlmostEqual(boos['pl'], -60.0)
        self.assertEqual((stored['USDJPY']['in_sample_dd'], stored['USDJPY']['windows']['foos']['dd']),
                         ({1: 100.0, 2: 140.0}[version], 180.0))
        self.assertEqual(stored['USDCAD']['windows']['foos']['trades'], 20)

    def test_a_catch_up_stored_before_version_2_holds_the_version_1_verdicts(self):
        self.check_stored(1)

    def test_a_catch_up_stored_now_holds_the_version_2_verdicts(self):
        self.check_stored(2)

    def test_a_catch_up_stored_before_version_2_is_reproduced_under_version_1_and_counted_under_version_2(self):
        self.check_recount(1)
        block, = self.recount('cu1')['catchups']
        rows, counts = self.rows_by_symbol(block), block['counts']
        # The recount the rule change is decided on: stored = version 1; two files gain a pass, none loses one.
        self.assertEqual(counts['pass'], dict(stored=2, v1=2, v2=4))
        self.assertEqual((counts['v1_matches_stored'], counts['v2_matches_stored']), (6, 4))
        self.assertEqual((counts['compared'], counts['gained'], counts['lost']), (['v1', 'v2'], 2, 0))
        self.assertEqual({symbol: row['oos_rule']['change'] for symbol, row in rows.items()},
                         dict(EURUSD='unchanged', GBPUSD='gained', USDJPY='gained', AUDUSD='unchanged', USDCAD='unchanged',
                              NZDUSD='unchanged'))
        loss, deep = rows['GBPUSD']['oos_rule'], rows['USDJPY']['oos_rule']
        self.assertEqual((loss['v1']['in_sample_windows'], loss['v2']['in_sample_windows'], loss['v2']['loss_leg_applied']), (4, 4, False))
        self.assertIn('in-sample 10th-percentile window', loss['v1']['reasons'][0])
        self.assertIn('loss leg not applied (O = 13 weeks; it applies from 52 weeks, 12 months)', loss['v2']['reasons'][0])
        # The O the leg was decided on is in the judge's own window record, which the reply carries as it is.
        self.assertEqual((loss['v2']['windows']['boos']['o_weeks'], loss['v2']['windows']['boos']['min_loss_leg_o_weeks']), (13, 52))
        self.assertNotIn('o_weeks', loss['v1']['windows']['boos'])
        self.assertEqual((deep['v1']['in_sample_dd'], deep['v1']['in_sample_base'], deep['v2']['in_sample_dd'], deep['v2']['in_sample_base']),
                         (100.0, 'SAMPLE', 140.0, 'SAMPLE+FWD'))
        self.assertEqual((deep['stored']['rule_version'], deep['stored']['in_sample_dd']), (1, 100.0))
        # Real negatives stay negative: a FOOS drawdown above both bars, and a FOOS under 30 trades.
        self.assertEqual((rows['AUDUSD']['oos_rule']['v2']['status'], rows['USDCAD']['oos_rule']['v2']['status']),
                         ('fail', 'not_eligible_yet'))
        self.assertEqual((rows['USDCAD']['oos_rule']['v2']['foos_trades'], rows['USDCAD']['oos_rule']['v2']['boos_trades']), (20, 50))

    def test_a_catch_up_stored_under_version_2_is_reproduced_under_version_2(self):
        self.check_recount(2)
        counts = self.recount('cu1')['catchups'][0]['counts']
        self.assertEqual(counts['pass'], dict(stored=4, v1=2, v2=4))
        self.assertEqual((counts['v1_matches_stored'], counts['v2_matches_stored'], counts['gained'], counts['lost']), (4, 6, 2, 0))

    def check_recount(self, stored_version):
        self.run_catchup(stored_version=stored_version)
        stored = self.stored()
        reply = self.recount('cu1')
        self.assertEqual((reply['schema'], reply['read_only'], reply['writes'], reply['rule']),
                         ('goat-oos-rule-recount-v1', True, False, w.EVALUATION))
        self.assertEqual((reply['rule_versions'], reply['default_rule_version']), (list(w.RULE_VERSIONS), w.RULE_VERSION))
        block, = reply['catchups']
        self.assertEqual((block['catchup_id'], block['readable'], block['status'], block['evidence_end']),
                         ('cu1', True, 'completed', '2026-10-02'))
        rows = self.rows_by_symbol(block)
        self.assertEqual(set(rows), set(self.SCENARIOS))
        for version in w.RULE_VERSIONS:
            name = recount.label(version)
            self.assertEqual({symbol: row['oos_rule'][name]['status'] for symbol, row in rows.items()}, EXPECTED[name], name)
        members = {spec['tester']['Symbol']: spec for spec in read_json(self.runner.path('cu1') / 'manifest.json')['members']}
        for symbol, row in rows.items():
            rule = row['oos_rule']
            self.assertTrue(row['readable'])
            self.assertEqual((row['catchup_id'], row['alias'], row['member_id'], row['period'], row['member_status']),
                             ('cu1', members[symbol]['alias'], members[symbol]['member_id'], 'M1', 'completed'))
            # The source SET and its hash, and the re-test SET and its hash, as the catch-up recorded them.
            source = next(path for path in self.sets if path.parent.name == symbol)
            self.assertEqual((row['original_set'], row['original_set_sha256']), (str(source), hashlib.sha256(source.read_bytes()).hexdigest()))
            self.assertEqual(row['retest_set_sha256'], hashlib.sha256(Path(row['retest_set']).read_bytes()).hexdigest())
            # The stored verdict, and the version it was judged with judged again: the same status, reasons and numbers.
            was = stored[symbol]
            self.assertEqual(rule['stored'], dict(present=True, status=was['status'], reasons=was['reasons'],
                                                 rule_version=w.record_rule_version(was), in_sample_dd=was['in_sample_dd']))
            again = rule[recount.label(w.record_rule_version(was))]
            self.assertTrue(rule[recount.label(w.record_rule_version(was)) + '_matches_stored'])
            self.assertEqual((again['status'], again['reasons'], again['in_sample_dd'], again['windows']),
                             (was['status'], was['reasons'], was['in_sample_dd'], was['windows']))
            self.assertEqual((again['boos_trades'], again['foos_trades'], again['in_sample_windows']),
                             (was['windows']['boos']['trades'], was['windows']['foos']['trades'], was['windows']['boos']['in_sample_windows']))
            self.assertEqual(again['foos_judged_through'], '2026-10-02')
        counts = block['counts']
        self.assertEqual((counts['members'], counts['judged'], counts['unreadable'], counts['stored_missing']), (6, 6, 0, 0))
        self.assertEqual(counts['pass']['stored'], sum(status == 'pass' for status in EXPECTED[recount.label(stored_version)].values()))
        for version in w.RULE_VERSIONS:
            name = recount.label(version)
            self.assertEqual(counts['pass'][name], sum(status == 'pass' for status in EXPECTED[name].values()))
        self.assertEqual(counts[recount.label(stored_version) + '_matches_stored'], 6)
        totals = reply['totals']
        self.assertEqual((totals['catchups'], totals['counted_catchups'], totals['locked_catchups'], totals['unreadable_catchups']),
                         (1, 1, [], []))
        for key in ('members', 'judged', 'unreadable', 'stored_missing', 'pass', 'compared', 'gained', 'lost'):
            self.assertEqual(totals[key], counts[key], key)

    def test_it_writes_nothing_anywhere(self):
        self.run_catchup()
        before = self.snapshot()
        self.assertGreater(len(before), 100)
        self.recount('cu1')
        self.recount(every=True)
        self.assertEqual(self.snapshot(), before)
        # Also through the CLI, and with a member whose files cannot be read (the failure path writes nothing either).
        self.assertEqual(self.cli('oos-rule-recount', '--all')[0], 0)
        self.assertEqual(self.snapshot(), before)
        Path(self.retest_csv('NZDUSD')).unlink()
        before = self.snapshot()
        self.assertFalse(self.rows_by_symbol(self.recount('cu1')['catchups'][0])['NZDUSD']['readable'])
        self.assertEqual(self.cli('oos-rule-recount', '--catchup-id', 'cu1')[0], 0)
        self.assertEqual(self.snapshot(), before)
        # catchup-report was never called: it would have written report.json.
        self.assertFalse((self.controller.root / 'catchups' / 'cu1' / 'report.json').exists())

    def test_it_never_reaches_a_terminal_a_lease_a_process_or_the_broker(self):
        self.run_catchup()
        import demo_agent
        import studio_seed_process
        import studio_terminal_lease
        import subprocess
        self.process.inspect = self.process.start = self.process.close = self.refuse('the fake terminal')
        refusals = [patch.object(demo_agent.DemoAgent, '__init__', self.refuse('DemoAgent')),
                    patch.object(studio_seed_process.WindowsSeedProcess, '__init__', self.refuse('WindowsSeedProcess')),
                    patch.object(studio_terminal_lease, 'terminal_lease', self.refuse('the terminal lease')),
                    patch.object(sc.CatchupRunner, '__init__', self.refuse('CatchupRunner')),
                    patch.object(subprocess, 'Popen', self.refuse('subprocess.Popen')),
                    patch.object(subprocess, 'run', self.refuse('subprocess.run')),
                    patch('goat_studio.Controller', self.refuse('the Studio controller')),
                    patch.dict(sys.modules, {'MetaTrader5': None})]       # importing the broker SDK raises ImportError
        for item in refusals:
            item.start()
            self.addCleanup(item.stop)
        code, reply, stderr = self.cli('oos-rule-recount', '--catchup-id', 'cu1')
        self.assertEqual(code, 0, stderr)
        self.assertEqual(reply['result']['totals']['judged'], 6)
        self.assertEqual((self.starts[6:], self.closes[1:]), ([], []))

    def test_the_module_reads_only_and_imports_no_launch_or_broker_module(self):
        source = Path(recount.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {'hashlib', 'json', 'os', 'pathlib', 're', 'studio_agent_mailbox', 'studio_evidence',
                                    'studio_evidence_archive', 'studio_oos_windows', 'studio_seed_results'})
        # Every call the module makes, by name: no write, create, rename, remove, lock, process or SDK call.
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called.add(node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '?'))
        forbidden = {'write', 'write_text', 'write_bytes', 'writelines', 'mkdir', 'makedirs', 'touch', 'unlink', 'rmdir', 'rmtree',
                     'remove', 'rename', 'replace', 'dump', 'copy', 'copy2', 'copytree', 'move', 'write_json', 'utime', 'chmod',
                     'Popen', 'run', 'system', 'startfile', 'terminal_lease', 'initialize', 'connect', 'execute'}
        self.assertEqual(called & forbidden, set())
        opens = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'open']
        self.assertEqual([[arg.value for arg in node.args] for node in opens], [['rb']])      # the one open is a binary read
        self.assertNotIn('open(', source.replace(".open('rb')", ''))

    def test_a_member_whose_inputs_cannot_be_read_is_listed_with_the_reason_and_never_judged(self):
        self.run_catchup()
        Path(self.retest_csv('NZDUSD')).unlink()                                               # the re-test equity CSV is gone
        original = next(path for path in self.sets if path.parent.name == 'USDCAD')
        original.write_bytes(original.read_bytes() + 'Extra=1\r\n'.encode('utf-16')[2:])       # the original export changed
        retest = Path(read_json(self.result_path('AUDUSD'))['path'])
        retest.write_bytes(retest.read_bytes() + 'Extra=1\r\n'.encode('utf-16')[2:])           # the re-test SET changed
        self.result_path('USDJPY').write_text('{}', encoding='utf-8')                     # the stored result changed
        block, = self.recount('cu1')['catchups']
        rows = self.rows_by_symbol(block)
        reasons = {symbol: row['unreadable'] for symbol, row in rows.items() if not row['readable']}
        self.assertEqual(set(reasons), {'NZDUSD', 'USDCAD', 'AUDUSD', 'USDJPY'})
        self.assertIn('equity CSV is missing', reasons['NZDUSD'])
        self.assertIn('original export changed', reasons['USDCAD'])
        self.assertIn('re-test SET changed', reasons['AUDUSD'])
        self.assertIn('stored result file changed', reasons['USDJPY'])
        for symbol in reasons:
            self.assertIsNone(rows[symbol]['oos_rule'], symbol)                                # no verdict of any kind
        counts = block['counts']
        self.assertEqual((counts['members'], counts['judged'], counts['unreadable']), (6, 2, 4))
        name = recount.label(w.RULE_VERSION)                                                   # the two readable members only
        still = sum(EXPECTED[name][symbol] == 'pass' for symbol in ('EURUSD', 'GBPUSD'))
        self.assertEqual((counts['pass']['stored'], counts['pass'][name]), (still, still))

    def test_a_catch_up_that_cannot_be_read_is_listed_and_an_unknown_one_is_refused(self):
        self.run_catchup()
        reply = self.recount(every=True)
        self.assertEqual([block['catchup_id'] for block in reply['catchups']], ['cu1'])
        self.assertEqual(recount.catchup_ids(self.root / 'no-such-state'), [])
        folder = self.controller.root / 'catchups' / 'cu1'
        state = read_json(folder / 'state.json')
        (folder / 'state.json').write_text(json.dumps(dict(state, manifest_sha256='0' * 64)), encoding='utf-8')
        block, = self.recount('cu1')['catchups']
        self.assertEqual((block['readable'], block['members'], block['counts']), (False, [], None))
        self.assertIn('different manifest.json', block['unreadable'])
        totals = self.recount('cu1')['totals']
        self.assertEqual((totals['counted_catchups'], totals['unreadable_catchups'], totals['members']), (0, ['cu1'], 0))
        for bad, message in ((['missing'], 'Unknown catch-up missing'), (['cu1', 'cu1'], 'named twice'), (['../cu1'], 'Catch-up ID must use'),
                             ([], 'not both and not neither')):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                self.recount(*bad)
        with self.assertRaisesRegex(ValueError, 'not both and not neither'):
            self.recount('cu1', every=True)

    def test_a_not_comparable_retest_is_never_judged_and_a_result_without_an_oos_rule_says_so(self):
        self.run_catchup()
        state = read_json(self.runner.path('cu1') / 'state.json')
        manifest_path = self.runner.path('cu1') / 'manifest.json'
        # Rewrite two stored results the way older catch-ups stored them, keeping state.json's hashes true.
        for symbol, change in (('EURUSD', 'drop'), ('GBPUSD', 'not_comparable')):
            item = state['members'][self.index(symbol)]
            result = read_json(item['result']['path'])
            if change == 'drop':
                del result['verdict']['oos_rule']
            else:
                result['verdict']['verdict'] = 'not_comparable'
                result['verdict']['oos_rule'] = dict(schema=w.EVALUATION, status='no_data', reasons=['stored reason'])
            Path(item['result']['path']).write_text(json.dumps(result), encoding='utf-8')
            item['result']['sha256'] = hashlib.sha256(Path(item['result']['path']).read_bytes()).hexdigest()
        (self.runner.path('cu1') / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        self.assertTrue(manifest_path.is_file())
        rows = self.rows_by_symbol(self.recount('cu1')['catchups'][0])
        name = recount.label(w.RULE_VERSION)
        missing = rows['EURUSD']['oos_rule']
        self.assertEqual((missing['stored']['present'], missing['stored']['status'], missing[name]['status'], missing[name + '_matches_stored']),
                         (False, None, 'pass', None))
        unjudged = rows['GBPUSD']['oos_rule']
        self.assertEqual((unjudged['catchup_verdict'], unjudged[name]['status'], unjudged[name + '_matches_stored']),
                         ('not_comparable', 'no_data', True))
        self.assertIn('not judged as the same test', unjudged[name]['reasons'][0])
        counts = self.recount('cu1')['catchups'][0]['counts']
        others = sum(EXPECTED[name][symbol] == 'pass' for symbol in ('USDJPY', 'AUDUSD', 'USDCAD', 'NZDUSD'))
        # EURUSD's stored verdict is gone (it still passes when judged); GBPUSD is not judged; the other four are as stored.
        self.assertEqual((counts['stored_missing'], counts['pass']['stored'], counts['pass'][name]), (1, others, others + 1))

    def test_a_held_out_lock_redacts_the_catch_up_and_keeps_it_out_of_the_totals(self):
        self.run_catchup()
        install = dict(self.controller.install, controller_state_root=str(self.controller.root), evidence_root=str(self.root / 'evidence-root'))
        clear = self.cli('oos-rule-recount', '--catchup-id', 'cu1', install=install)[1]['result']
        self.assertEqual((clear['totals']['counted_catchups'], clear['totals']['judged']), (1, 6))
        self.assertNotIn('heldout', clear['catchups'][0])
        # A lock over the FOOS weeks: the members are unattributed, so it binds every one of them.
        write_registry(install['evidence_root'], [('declare', declaration('alpha', '2026-09-05', '2028-01-03', '2027-12-31'),
                                                   '2026-10-04T01:00:00Z')])
        code, reply, stderr = self.cli('oos-rule-recount', '--catchup-id', 'cu1', install=install)
        self.assertEqual(code, 0, stderr)
        block, = reply['result']['catchups']
        self.assertTrue(block['heldout']['redacted'])
        self.assertTrue(block['counts']['locked'])
        for row in block['members']:
            self.assertTrue(row['oos_rule']['locked'], row['symbol'])
        text = json.dumps(reply)
        for word in ('"fail"', 'not_eligible_yet', 'in_sample_dd', 'boos_trades'):
            self.assertNotIn(word, text, word)
        totals = reply['result']['totals']
        self.assertEqual((totals['counted_catchups'], totals['locked_catchups'], totals['members'], totals['judged'], totals['pass']['stored']),
                         (0, ['cu1'], 0, 0, 0))

    def test_the_cli_takes_named_catch_ups_or_all_and_needs_a_readable_installation(self):
        self.run_catchup()
        code, reply, stderr = self.cli('oos-rule-recount', '--catchup-id', 'cu1')
        self.assertEqual((code, reply['ok'], reply['result']['schema']), (0, True, 'goat-oos-rule-recount-v1'), stderr)
        self.assertEqual(reply['result'], json.loads(json.dumps(self.recount('cu1'))))
        self.assertEqual(self.cli('oos-rule-recount', '--all')[1]['result']['totals']['catchups'], 1)
        for argv, message in ((['oos-rule-recount'], 'not both and not neither'),
                              (['oos-rule-recount', '--all', '--catchup-id', 'cu1'], 'not both and not neither'),
                              (['oos-rule-recount', '--catchup-id', 'nope'], 'Unknown catch-up nope')):
            code, reply, stderr = self.cli(*argv)
            self.assertEqual((code, reply), (1, None), argv)
            error = json.loads(stderr)
            self.assertEqual((error['ok'], error['code']), (False, 'REFUSED'))
            self.assertIn(message, error['error'])
        code, reply, stderr = self.cli('oos-rule-recount', '--all', install=None)
        self.assertEqual((code, reply), (1, None))
        self.assertIn('needs a readable --installation', json.loads(stderr)['error'])

    # ---- helpers ---------------------------------------------------------------------------------------------------
    def refuse(self, what):
        def refused(*args, **kwargs):
            raise AssertionError('oos-rule-recount reached ' + what)
        return refused

    def index(self, symbol):
        manifest = read_json(self.runner.path('cu1') / 'manifest.json')
        return [spec['tester']['Symbol'] for spec in manifest['members']].index(symbol)

    def result_path(self, symbol):
        return Path(read_json(self.runner.path('cu1') / 'state.json')['members'][self.index(symbol)]['result']['path'])

    def retest_csv(self, symbol):
        return read_json(self.result_path(symbol))['path'][:-4] + '.csv'

    def cli(self, *argv, install='default'):
        """demo_agent.main for one command: (exit code, parsed stdout or None, stderr)."""
        import demo_agent
        if install == 'default':
            install = dict(self.controller.install, controller_state_root=str(self.controller.root))
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = ['--installation', str(self.root / 'installation.json'), *argv]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if install is None:
                code = demo_agent.main(arguments)
            else:
                with patch.object(demo_agent, 'load_installation', return_value=install):
                    code = demo_agent.main(arguments)
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()


class ArchivedEvidenceTests(unittest.TestCase):
    """A catch-up whose evidence folder evidence-archive moved: the recount reads the verified archive copy, or refuses."""

    def test_the_retest_unit_is_read_from_its_verified_archive_copy(self):
        import studio_evidence_archive as archive
        from test_studio_evidence_archive import CATCHUP, CatchupArchiveTests
        case = CatchupArchiveTests('test_the_catchup_report_names_the_archived_version')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        self.assertEqual(recount._unit(case.root, str(case.retest)), case.retest)             # not archived: read in place
        case.run_archive(CATCHUP)
        case.complete(CATCHUP)
        self.assertFalse(case.retest.exists())
        moved = case.folder(CATCHUP) / 'evidence' / sc.evidence_key(CATCHUP) / '00001'
        self.assertEqual(sc.plain(recount._unit(case.root, str(case.retest))), str(moved / case.retest.name))
        # A CSV or deals file that no longer matches the archive manifest refuses the unit: the member is then listed
        # unreadable (``_member`` catches ArchiveUnreachable), never read from anything else.
        deals = moved / (case.retest.name[:-4] + '.goatseq') / 'deals.csv'
        deals.write_bytes(deals.read_bytes() + b'more\n')
        with self.assertRaises(archive.ArchiveUnreachable):
            recount._unit(case.root, str(case.retest))


class RuleVersionSeamTests(unittest.TestCase):
    """The rule module names the versions it can judge under; the recount takes its list from there."""

    def test_versions_are_listed_oldest_first_and_include_the_default(self):
        self.assertEqual(w.RULE_VERSIONS[0], 1)
        self.assertEqual(list(w.RULE_VERSIONS), sorted(set(w.RULE_VERSIONS)))
        self.assertIn(w.RULE_VERSION, w.RULE_VERSIONS)
        self.assertEqual(set(EXPECTED), {recount.label(version) for version in w.RULE_VERSIONS})

    def test_a_stored_record_without_a_version_was_judged_under_version_1(self):
        self.assertEqual(w.record_rule_version(dict(schema=w.EVALUATION, status='pass')), 1)
        self.assertEqual(w.record_rule_version(dict(ruleVersion=7)), 7)

    def test_an_unknown_version_is_refused_before_anything_is_read(self):
        for bad in (0, 99, '1', 1.0, True):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'The OOS window rule has versions'):
                w.judge_retest(dict(csv_path='missing'), dict(csv_path='missing'), tester=None, rule_version=bad)


if __name__ == '__main__':
    unittest.main()
