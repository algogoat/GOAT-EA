"""Hold-up test (goatai#1885, Claude-Mac APPROVE 5989126739): one frozen SET, one MT5 pass, MT5's own report.

The real HoldupRunner, SeedRunner driver, report parser and held-out guard run here; only the MT5
process is a fixture. Each "MT5 run" writes the recorded MT5 report (fixtures/holdup, see
test_studio_tester_report) with the member's own EA_Desc, exactly as MT5 would print its inputs.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_evidence_end
from studio_heldout import HeldOutRefused
from studio_holdup import HoldupRunner, evidence_hint, relation_of
from studio_installation import read_json
from studio_research_queue import research_queue
from studio_seed_slot import guard_active_seed
from studio_trial_journal import journal
import studio_tester_report as tr
from test_studio_heldout import NOW_AT, declaration, write_registry
from test_studio_tester_report import fixture_text, schema_for

NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)          # AUTO evidence end: Friday 2026-10-02
REAL_UTC = studio_evidence_end._utc


def report_inputs():
    parser = tr._Rows(); parser.feed(fixture_text()); parser.close()
    return tr._inputs(parser.rows)


class HoldupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1_000_000.0
        self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='monitor')
        self.starts, self.closes, self.auto, self.quality, self.drift = [], [], False, None, {}
        data = self.root / 'terminal'
        binary = data / 'MQL5/Experts/GOAT-EA/GOAT V1.47.ex5'; binary.parent.mkdir(parents=True); binary.write_bytes(b'ex5')
        self.c = SimpleNamespace(root=self.root / 'controller', local=self.root / 'local')
        self.c.root.mkdir(); (self.c.local / 'native-gate').mkdir(parents=True)
        self.c.install = dict(terminal_data_root=str(data), common_files_root=str(self.root / 'common'),
                              terminal_executable=str(data / 'terminal64.exe'), ea_relative_path='GOAT-EA\\GOAT V1.47.ex5',
                              ea_version='1.47', ea_sha256=hashlib.sha256(b'ex5').hexdigest(), evidence_root=str(self.root / 'evidence'),
                              controller_state_root=str(self.c.root))
        self.c.session = dict(account={'login': '123', 'server': 'Test-Demo'})
        self.inputs = report_inputs()
        self.values = dict(self.inputs, Mode_Operation='9')
        schema = schema_for(self.values)
        schema['inputs']['Mode_Bias'] = dict(type='int', optimizable=True, enum_choices=dict(Bias_Disabled=1, Bias_Opens=0, Bias_Display=2))
        schema['inputs']['Mode_Lots'] = dict(type='int', optimizable=True, enum_choices=dict(Fixed=0, Balance=1, RiskperSeq=2))
        self.c.schema = schema
        self.c.policy = dict(header_sha256='a' * 64, main_sha256='b' * 64, coverage='indicator_mode_gates_only', rules=[])
        self.owner = dict(owner='agent', generation=1, queue=[])
        self.c.state = lambda: copy.deepcopy(self.owner)
        self.c.bridge = SimpleNamespace(pump=lambda: None)
        self.c.runtime = lambda **kw: ({'loaded': True, 'owner': self.owner['owner'], 'generation': self.owner['generation']}, {})
        self.process = SimpleNamespace(inspect=lambda: copy.deepcopy(self.process_state), close=self.close, start=self.start)
        clock = patch('studio_evidence_end._utc', side_effect=lambda now: NOW if now is None else REAL_UTC(now))
        clock.start(); self.addCleanup(clock.stop)
        self.runner = HoldupRunner(self.c, process=self.process, clock=lambda: self.now, sleep=self.sleep, now=NOW)
        self.source = self.write_set('GOAT V1.47 SP500,M1_Trds=128_Prf=-880_DD=1960_PF=0.85_SR=-2.80_ARF=-0.1.set',
                                     header=['; BOOS:   2025.01.06-2025.03.28 Days=60 Trades=40 PL=100',
                                             '; SAMPLE: 2025.03.31-2025.09.26 Days=125 Trades=80 PL=900',
                                             '; FWD:    2025.09.29-2025.12.26 Days=64 Trades=30 PL=200',
                                             '; FOOS:   2025.12.29-2026.01.16 Days=15 Trades=6 PL=40'])

    def tearDown(self):
        self.tmp.cleanup()

    # ---- the native world ---------------------------------------------------------------------------
    def close(self, identity):
        self.assertEqual(identity, self.process_state); self.closes.append(identity); self.process_state = None

    def start(self, config):
        self.assertIsNone(self.process_state); self.starts.append(config)
        self.process_state = dict(pid=10 + len(self.starts), executable='terminal64.exe', created_utc='run' + str(len(self.starts)))
        return copy.deepcopy(self.process_state)

    def sleep(self, seconds):
        self.now += seconds
        if self.auto and self.starts and self.process_state:
            self.mt5_writes_report(len(self.starts) - 1)
            self.process_state = None

    def mt5_writes_report(self, index):
        """MT5 prints the inputs it ran: the member's frozen values (plus any drift a test injects)."""
        member = read_json(self.runner.path('h1') / 'manifest.json')['members'][index]
        text = fixture_text()
        original = [line for line in text.splitlines() if '<b>EA_Desc=' in line][0]
        text = text.replace(original, original.split('<b>EA_Desc=')[0] + '<b>EA_Desc=' + member['alias'] + '</b></td>')
        text = text.replace('<b>Mode_Operation=0</b>', '<b>Mode_Operation=9</b>')
        for name, (before, after) in self.drift.items():
            text = text.replace('<b>%s=%s</b>' % (name, before), '<b>%s=%s</b>' % (name, after))
        if self.quality is not None:
            text = text.replace('<b>100% real ticks</b>', '<b>%s</b>' % self.quality)
        path = Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/HoldupReports' / (member['alias'] + '.htm')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xff\xfe' + text.encode('utf-16-le'))
        for png in ('', '-hst', '-mfemae', '-holding'):
            path.with_name(member['alias'] + png + '.png').write_bytes(b'png')

    # ---- plans --------------------------------------------------------------------------------------
    def write_set(self, name, *, values=None, header=(), folder=None):
        values = dict(self.values if values is None else values)
        lines = list(header) + ['; ===========GENERAL SETTINGS============'] + ['%s=%s' % kv for kv in values.items()]
        path = (folder or self.root / 'sets') / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le'))
        return path

    def spec_for(self, path=None, **change):
        path = path or self.source
        spec = dict(set_path=str(path), set_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    window=dict(start='2026-01-19', end='2026-09-11'),
                    tester=dict(Model=4, ExecutionMode=0, Deposit=100000, Currency='USD', Leverage='1:100'))
        spec.update(change)
        return spec

    def plan(self, *tests):
        return dict(schema_version=1, job_timeout_seconds=900, tests=list(tests) or [self.spec_for()])

    def run_plan(self, plan=None):
        self.runner.prepare('h1', plan or self.plan())
        self.auto = True
        return self.runner.start('h1', 60)

    # ---- prepare: frozen bytes and refusals ---------------------------------------------------------
    def test_prepare_freezes_exact_bytes_and_one_single_pass_config(self):
        original = self.source.read_bytes()
        result = self.runner.prepare('h1', self.plan())
        self.assertEqual((result['status'], self.source.read_bytes()), ('prepared', original))
        member = read_json(self.runner.path('h1') / 'manifest.json')['members'][0]
        frozen = Path(member['set_path']).read_bytes().decode('utf-16')
        self.assertEqual(frozen.replace('EA_Desc=' + member['alias'], 'EA_Desc=' + self.values['EA_Desc']), original.decode('utf-16'))
        self.assertNotIn('@{', frozen.split('EA_Desc=')[1].splitlines()[0])      # a plain test: no export or seed mode
        ini = Path(member['config_path']).read_bytes().decode('utf-16')
        for line in ('Optimization=0', 'ForwardMode=0', 'ShutdownTerminal=1', 'Model=4', 'FromDate=2026.01.19', 'ToDate=2026.09.11',
                     'Report=MQL5\\Files\\GOATStudio\\HoldupReports\\' + member['alias'] + '.htm', 'AllowLiveTrading=0', 'Enabled=0',
                     'Symbol=SP500', 'Period=M1', 'Login=123', 'Server=Test-Demo'):
            self.assertIn(line + '\r\n', ini)
        self.assertNotIn('Password', ini)
        self.assertEqual((member['named_by'], member['relation']['relation']), (['export file name'], 'after_selection'))
        self.assertEqual(member['relation']['exposure'], dict(start='2025-01-06', end='2026-01-17'))
        self.assertFalse(self.starts or self.closes)

    def test_validate_writes_nothing(self):
        result = self.runner.validate(self.plan())
        self.assertEqual((result['valid'], result['writes'], result['test_count']), (True, False, 1))
        self.assertEqual(result['tests'][0]['relation'], 'after_selection')
        self.assertFalse(self.runner.path('h1').exists())
        self.assertFalse((Path(self.c.install['terminal_data_root']) / 'config/GOATStudio/Holdups').exists())

    def refused(self, plan, pattern, code=None):
        with self.assertRaisesRegex(ValueError, pattern) as caught:
            self.runner.prepare('bad', plan)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertFalse(self.runner.path('bad').exists())

    def test_refusals_happen_before_any_file(self):
        self.refused(self.plan(self.spec_for(set_sha256='0' * 64)), 'is not the frozen SET: its sha256 is')
        searching = self.write_set('search.set', values=dict(self.values, Grid_Size='-4||-5||1||-3||Y'))
        self.refused(self.plan(self.spec_for(searching, symbol='SP500', period='M1')), 'still searches Grid_Size')
        bias = self.write_set('bias.set', values=dict(self.values, Mode_Bias='0'))
        self.refused(self.plan(self.spec_for(bias, symbol='SP500', period='M1')), 'HOLDUP_AI_BIAS_ON: Test 1 runs with AI bias on')
        batch_mode = self.write_set('batch.set', values=dict(self.values, Mode_Operation='0'))
        self.refused(self.plan(self.spec_for(batch_mode, symbol='SP500', period='M1')), 'standard operation mode')
        starter = self.write_set('starter.set', values=dict(self.values, EA_Desc='Starter Single Trade'))
        self.refused(self.plan(self.spec_for(starter, symbol='SP500', period='M1')), 'starter SET is a blank')
        risky = self.write_set('risky.set', values=dict(self.values, Max_Seq_Trades='1'))
        self.refused(self.plan(self.spec_for(risky, symbol='SP500', period='M1')), 'RISK_PER_SEQUENCE_NEEDS_TWO_TRADES')
        self.refused(self.plan(self.spec_for(window=dict(start='2026-09-01', end='2026-10-05'))), 'reaches into the unfinished week')
        self.refused(self.plan(self.spec_for(symbol='NDX')), 'symbol/period disagree')
        plain = self.write_set('plain.set')
        self.refused(self.plan(self.spec_for(plain)), 'does not name its symbol and period')
        self.refused(self.plan(self.spec_for(tester=dict(Model=4, ExecutionMode=-1, Deposit=100000, Currency='USD', Leverage='1:100'))),
                     'random delay cannot reproduce')
        self.refused(self.plan(self.spec_for(), self.spec_for()), 'repeats another test')
        self.refused(dict(self.plan(), heldout_reveal=dict(lock_id='a' * 64)), 'does not run through hold-up test v1', 'HELDOUT_REVEAL_NOT_IN_V1')
        self.assertFalse(self.starts or self.closes)

    def test_risk_not_chosen_starter_lineage_is_refused(self):
        lines = ['; GOAT Risk not chosen: Risk=500 is a placeholder']
        lineage = self.write_set('lineage.set', header=lines)
        self.refused(self.plan(self.spec_for(lineage, symbol='SP500', period='M1')), 'RISK_NOT_CHOSEN')

    def test_held_out_lock_refuses_prepare_and_a_later_lock_refuses_the_launch(self):
        write_registry(self.root / 'evidence', [('declare', declaration('alpha', '2026-06-01', '2026-08-31', '2026-08-28'), NOW_AT)])
        with self.assertRaises(HeldOutRefused) as refused:
            self.runner.prepare('h1', self.plan())
        self.assertEqual(refused.exception.code, 'HELDOUT_UNATTRIBUTED_MEMBER')
        self.assertFalse(self.runner.path('h1').exists())
        (self.root / 'evidence/heldout/locks.jsonl').unlink()
        self.runner.prepare('h1', self.plan())
        write_registry(self.root / 'evidence', [('declare', declaration('alpha', '2026-06-01', '2026-08-31', '2026-08-28'), NOW_AT)])
        with self.assertRaises(HeldOutRefused):
            self.runner.start('h1', 5)
        self.assertFalse(self.starts or self.closes)

    def test_a_lock_declared_later_redacts_every_reported_value(self):
        self.run_plan()
        from studio_heldout_guard import guard_output
        # A lock on other days leaves the hold-up readable: its own window is known, not guessed.
        write_registry(self.root / 'evidence', [('declare', declaration('alpha', '2026-09-14', '2026-12-14', '2026-12-11'), NOW_AT)])
        readable = json.dumps(guard_output(self.c.install, self.runner.report('h1'), root=self.c.root, now=NOW))
        self.assertIn('-880.37', readable); self.assertNotIn('locked_windows', readable)
        write_registry(self.root / 'evidence', [('declare', declaration('alpha', '2026-06-01', '2026-08-31', '2026-08-28'), NOW_AT)])
        for reply in (self.runner.report('h1'), self.runner.status('h1')):
            guarded = json.dumps(guard_output(self.c.install, reply, root=self.c.root, now=NOW))
            self.assertNotIn('880.37', guarded); self.assertNotIn('1960.36', guarded)
            self.assertIn('locked_windows', guarded)

    # ---- the run ------------------------------------------------------------------------------------
    def test_one_pass_is_read_from_mt5s_report_with_every_check(self):
        state = self.run_plan(self.plan(self.spec_for(window=dict(start='2026-01-19', end='2026-09-11', split='2026-06-01'))))
        self.assertEqual((state['status'], len(self.starts), len(self.closes)), ('completed', 1, 1))
        guard_active_seed(self.c.root)
        item = state['members'][0]
        result = read_json(item['result']['path'])
        self.assertEqual((result['schema'], result['status']), ('goat-holdup-result-v1', 'verified_holdup_test'))
        self.assertEqual(result['checks']['inputs_checked'], len(self.values))
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual((result['metrics']['net'], result['metrics']['trades'], result['metrics']['equity_dd_max_money']), (-880.37, 128, 1960.36))
        self.assertEqual(round(sum(w['net'] for w in result['per_week']), 2), -880.37)
        self.assertEqual(result['segments']['split'], '2026-06-01')
        self.assertEqual(result['identity']['set_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual((result['identity']['mt5_build'], result['conditions']['history_quality_pct']), (6182, 100.0))
        self.assertEqual(result['conditions']['model_tag']['model_rung'], 3)
        self.assertEqual(result['writes'], dict(export=False, promotion=False, library=False, ledger=False, catalog=False))
        self.assertEqual(result['evidence']['role'], 'catch-up')
        self.assertEqual((result['evidence']['level'], result['evidence']['contamination']['status']), ('L3', 'clean'))
        self.assertEqual((result['evidence']['journal_ref_kind'], result['evidence']['metrics_source']), ('holdup-result', 'tester-report'))
        # The retained report copy is the checked bytes, and the deal list is kept beside it.
        self.assertEqual(hashlib.sha256(Path(result['path']).read_bytes()).hexdigest(), result['sha256'])
        deals = read_json(result['deals_path'])
        self.assertEqual((len(deals['deals']), deals['report_sha256']), (241, result['sha256']))
        report = self.runner.report('h1')
        row = report['members'][0]
        self.assertEqual((row['status'], row['summary']['net'], row['relation']), ('completed', -880.37, 'after_selection'))
        self.assertIn('Offered as catch-up evidence (L3)', row['summary']['plain'])
        self.assertEqual(self.runner.resume('h1', 5)['status'], 'completed'); self.assertEqual(len(self.starts), 1)

    def test_mt5_running_other_inputs_fails_that_test_only(self):
        second = self.spec_for(window=dict(start='2026-02-02', end='2026-09-11'))
        self.drift = {'Grid_Size': ('-4', '-6')}
        state = self.run_plan(self.plan(self.spec_for(), second))
        self.assertEqual([m['status'] for m in state['members']], ['failed', 'failed'])
        self.assertIn('MT5 ran different inputs than the frozen SET: Grid_Size frozen -4, ran -6', state['members'][0]['error'])
        self.assertEqual(len(self.starts), 2)          # the first failure did not end the run (goatai#1885)
        self.assertIsNone(state['members'][0]['result'])
        self.assertEqual(state['stopped_reason']['rules'], ['every_member_failed'])

    def test_the_retained_deal_list_is_checked_on_every_read_and_never_replaced(self):
        # Codex P2 on GOAT-EA#161: a stale or edited deals.json must never stand beside a checked report.
        state = self.run_plan()
        deals = Path(read_json(state['members'][0]['result']['path'])['deals_path'])
        deals.write_text(deals.read_text(encoding='utf-8').replace('"-0.24"', '"-0.25"', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Retained hold-up deal list changed'):
            self.runner.status('h1')
        # An interrupted earlier collection left different bytes: the test fails, nothing is overwritten.
        self.runner.prepare('h2', self.plan(self.spec_for(window=dict(start='2026-01-19', end='2026-09-11', split='2026-05-04'))))
        self.runner.slot.write_text(json.dumps(dict(read_json(self.runner.slot), status='released')))
        self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='monitor')
        self.auto = False
        self.runner.start('h2', 1)
        member = read_json(self.runner.path('h2') / 'manifest.json')['members'][0]
        stale = self.runner.path('h2') / (member['alias'] + '.deals.json')
        stale.write_text('{"deals":[]}', encoding='utf-8')
        path = Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/HoldupReports' / (member['alias'] + '.htm')
        text = fixture_text()
        original = [line for line in text.splitlines() if '<b>EA_Desc=' in line][0]
        text = text.replace(original, original.split('<b>EA_Desc=')[0] + '<b>EA_Desc=' + member['alias'] + '</b></td>')
        path.write_bytes(b'\xff\xfe' + text.replace('<b>Mode_Operation=0</b>', '<b>Mode_Operation=9</b>').encode('utf-16-le'))
        self.process_state = None
        state = self.runner.status('h2')
        self.assertEqual(state['members'][0]['status'], 'failed')
        self.assertIn('A different retained copy already exists', state['members'][0]['error'])
        self.assertEqual(stale.read_text(encoding='utf-8'), '{"deals":[]}')

    def test_low_history_quality_keeps_the_result_without_evidence(self):
        self.quality = '87% real ticks'
        state = self.run_plan()
        result = read_json(state['members'][0]['result']['path'])
        self.assertEqual((state['status'], result['metrics']['net']), ('completed', -880.37))
        self.assertIsNone(result['evidence'])
        self.assertIn('87%, below the 90% floor', result['evidence_reason'])
        self.assertFalse(result['summary']['evidence_offered'])

    def test_a_missing_report_fails_the_test_with_a_plain_reason(self):
        self.runner.prepare('h1', self.plan())
        self.runner.start('h1', 1)
        self.process_state = None                                   # MT5 exited without a report
        state = self.runner.status('h1')
        self.assertEqual(state['members'][0]['status'], 'missing_output')
        self.assertIn("without writing this test's Strategy Tester report", state['members'][0]['error'])

    # ---- relation and the ledger mapping ------------------------------------------------------------
    def test_relation_and_evidence_mapping(self):
        from datetime import date
        exposure = dict(start=date(2025, 1, 6), end=date(2026, 1, 17))
        self.assertEqual(relation_of(date(2026, 1, 19), date(2026, 9, 11), exposure), 'after_selection')
        self.assertEqual(relation_of(date(2024, 1, 1), date(2025, 1, 6), exposure), 'before_selection')
        self.assertEqual(relation_of(date(2025, 12, 1), date(2026, 3, 1), exposure), 'overlaps_selection')
        self.assertEqual(relation_of(date(2026, 1, 19), date(2026, 9, 11), None), 'unknown')
        roles = {r: evidence_hint(r, quality=100.0, model=1)[0] for r in ('after_selection', 'before_selection', 'overlaps_selection', 'unknown')}
        self.assertEqual({r: (h['role'], h['level'], h['contamination']['status']) for r, h in roles.items()},
                         dict(after_selection=('catch-up', 'L3', 'clean'), before_selection=('back-oos', 'L2', 'clean'),
                              overlaps_selection=('in-sample', 'L0', 'contaminated'), unknown=('back-oos', 'L2', 'unknown')))
        self.assertEqual(roles['unknown']['drawdown_sampling'], '1m-events')
        self.assertIn('treated exactly like contaminated', roles['unknown']['scorer_rule'])
        self.assertEqual(evidence_hint('after_selection', quality=None, model=4)[0], None)

    def test_a_seed_promotion_names_symbol_period_and_selection_window(self):
        folder = self.root / 'seeds/s1/promoted/S1/abc'
        fixed = self.write_set('fixed.set', folder=folder)
        receipt = dict(fixed_set=dict(path=str(fixed), sha256=hashlib.sha256(fixed.read_bytes()).hexdigest()),
                       seed_window=dict(symbol='SP500', period='M1', from_date='2025.01.01', to_date='2026.03.01'))
        (folder / 'promotion.json').write_text(json.dumps(receipt), encoding='utf-8')
        result = self.runner.validate(self.plan(self.spec_for(fixed)))
        self.assertEqual((result['tests'][0]['named_by'], result['tests'][0]['relation']), (['seed promotion'], 'overlaps_selection'))
        receipt['fixed_set']['sha256'] = '0' * 64                  # a receipt for other bytes is ignored
        (folder / 'promotion.json').write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'does not name its symbol and period'):
            self.runner.validate(self.plan(self.spec_for(fixed)))
        unknown = self.runner.validate(self.plan(self.spec_for(fixed, symbol='SP500', period='M1')))
        self.assertEqual(unknown['tests'][0]['relation'], 'unknown')

    # ---- trial journal and research queue ------------------------------------------------------------
    def test_every_dispatched_test_is_a_peek_and_the_queue_shows_prove(self):
        overlap = self.spec_for(window=dict(start='2025-12-01', end='2026-09-11'))
        self.run_plan(self.plan(self.spec_for(), overlap))
        install = dict(self.c.install, controller_state_root=str(self.c.root))
        entries = journal(self.c.root, install)['entries']
        holdups = [e for e in entries if e['kind'] == 'single-pass']
        self.assertEqual(len(holdups), 2)
        self.assertTrue(all(e['dispatched'] and e['counts_as_peek'] for e in holdups))
        self.assertEqual([e['windows'][0]['role'] for e in holdups], ['catch-up', 'back-oos'])
        self.assertEqual([e['windows'][0]['relation'] for e in holdups], ['after_selection', 'overlaps_selection'])
        queue = research_queue(root=self.c.root, install=install, session=dict(self.c.session), now=self.now, jobs=[])
        row = next(r for r in queue['rows'] if r['batch_id'] == 'h1')
        self.assertEqual((row['kind'], row['stage'], row['state'], row['profitable']), ('holdup', 'prove', 'finished', 0))

    def test_a_never_dispatched_test_is_not_a_peek(self):
        self.runner.prepare('h1', self.plan())
        install = dict(self.c.install, controller_state_root=str(self.c.root))
        entry = [e for e in journal(self.c.root, install)['entries'] if e['kind'] == 'single-pass'][0]
        self.assertEqual((entry['dispatched'], entry['counts_as_peek'], entry['outcome']), (False, False, 'not-dispatched'))


if __name__ == '__main__':
    unittest.main()
