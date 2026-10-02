import copy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import studio_catchup as sc
from studio_installation import read_json
from studio_seed_slot import guard_active_seed
from test_studio_catchup_verdict import TESTER, VALUES, daily, make_unit, trading

AFTER_CLOSE = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)      # Saturday: auto = Fri 2026-10-02
BEFORE_CLOSE = datetime(2026, 10, 2, 15, tzinfo=timezone.utc)    # Friday 18:00 server: auto = Fri 2026-09-25
SCHEMA = {'source_sha256': 'a' * 64, 'inputs': {
    'EA_Desc': dict(type='string', optimizable=False),
    'Mode_Operation': dict(type='ENUM_MODE_OPERATION', optimizable=False, enum_choices={'Operation_Standard': 9, 'Operation_Batch': 11}),
    'Lots_Input': dict(type='double', optimizable=True), 'Grid_Size': dict(type='double', optimizable=True)}}
POLICY = dict(header_sha256='a' * 64, main_sha256='b' * 64, coverage='indicator_mode_gates_only', rules=[])


def export_settings(folder):
    text = '[Export]\r\nAdjustLots=0\r\nBackOOSDate=2026.01.05\r\nIncludeBackOOS=1\r\nMinARF=0.2\r\nMinSR=2.5\r\nSetsToExport=2\r\n'
    (folder / 'export_settings.GOAT').write_bytes(text.encode('utf-16'))


class CatchupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 1000000.0
        self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='monitor')
        self.starts, self.closes, self.auto = [], [], False
        data = self.root / 'terminal'
        binary = data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'ex5')
        c = SimpleNamespace(root=self.root / 'controller', local=self.root / 'local')
        c.root.mkdir()
        (c.local / 'native-gate').mkdir(parents=True)
        c.install = dict(terminal_data_root=str(data), common_files_root=str(self.root / 'common'), terminal_executable=str(data / 'terminal64.exe'),
                         ea_relative_path='GOAT-EA\\GOAT V1.49.ex5', ea_version='1.49', ea_sha256=hashlib.sha256(b'ex5').hexdigest())
        c.session = dict(account={'login': '123', 'server': 'Test-Demo'})
        c.schema, c.policy = SCHEMA, POLICY
        self.owner = dict(owner='agent', generation=1, queue=[])
        c.state = lambda: copy.deepcopy(self.owner)
        c.bridge = SimpleNamespace(pump=lambda: None)
        c.runtime = lambda **kw: ({'loaded': True, 'owner': self.owner['owner'], 'generation': self.owner['generation']}, {})
        self.controller = c
        self.process = SimpleNamespace(inspect=lambda: copy.deepcopy(self.process_state), close=self.close, start=self.start)
        self.runner = sc.CatchupRunner(c, process=self.process, clock=lambda: self.now, sleep=self.sleep, now=AFTER_CLOSE)
        self.history = daily(date(2026, 1, 5), date(2026, 9, 24), 10000, 10, dips=[(date(2026, 3, 4), 120)])
        self.deals = trading(date(2026, 1, 5), date(2026, 9, 24), 2, 5.1)
        self.run = self.root / 'GOAT' / 'Rrun1'
        (self.run / 'deploy').mkdir(parents=True)
        export_settings(self.run)
        self.behind = self.export('Rbehind01', 'EURUSD', self.history)
        self.histories = dict(GBPUSD=daily(date(2026, 1, 5), date(2026, 10, 1), 10000, 10))
        self.ahead = self.export('Rahead001', 'GBPUSD', self.histories['GBPUSD'])
        self.weak = self.export('Rweak0001', 'USDJPY', self.history, name_metrics='Trds=100_Prf=50_DD=50_PF=1.1_SR=1_ARF=0.1')
        self.write_run_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, alias, symbol, rows, **kw):
        forced = (datetime.combine(rows[-1][0].date(), time(23, 59)), rows[-1][1], rows[-1][2])
        windows = [('BOOS', date(2026, 1, 5), date(2026, 1, 19), 20, 100), ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300),
                   ('FOOS', date(2026, 8, 29), rows[-1][0].date(), 38, 190)]
        return make_unit(self.run / 'deploy' / alias / symbol, rows=rows + [forced], deals=self.deals, alias=alias, symbol=symbol,
                         windows=windows, **kw)

    def write_run_manifest(self, aliases=('Rbehind01', 'Rahead001', 'Rweak0001'), ea_sha256=None, **tester):
        jobs = [dict(run_alias=a, tester=dict(TESTER, Symbol='x', Period='M1', Deposit=10000, Currency='USD', Leverage='1:100', ExecutionMode=0, **tester))
                for a in aliases]
        (self.run / 'manifest.json').write_text(json.dumps(dict(ea_sha256=ea_sha256 or hashlib.sha256(b'ex5').hexdigest(), jobs=jobs)), encoding='utf-8')

    def plan(self, sets=None, **extra):
        return dict(schema_version=1, evidence_end='auto', sets=[str(p) for p in (sets or [self.behind, self.ahead, self.weak])],
                    job_timeout_seconds=3600, **extra)

    # fake terminal ----------------------------------------------------------------------
    def close(self, identity):
        self.assertEqual(identity, self.process_state)
        self.closes.append(identity)
        self.process_state = None

    def start(self, config):
        self.assertIsNone(self.process_state)
        self.starts.append(config)
        self.process_state = dict(pid=10 + len(self.starts), executable='terminal64.exe', created_utc='run' + str(len(self.starts)))
        return copy.deepcopy(self.process_state)

    def sleep(self, seconds):
        self.now += seconds
        if self.auto and self.starts and self.process_state:
            manifest = read_json(self.runner.path('cu1') / 'manifest.json')
            self.native_retest(manifest['members'][len(self.starts) - 1])
            self.process_state = None

    def native_retest(self, member, *, new_per_day=10):
        """What the EA writes for one /config single pass: the export unit in TEMP\\SQ\\<token>."""
        tester = member['tester']
        to_date = datetime.strptime(tester['ToDate'], '%Y.%m.%d').date()
        base = self.histories.get(tester['Symbol'], self.history)     # a faithful EA reproduces each export's own history
        first = base[-1][0].date() + timedelta(days=1)
        rows = base + daily(first, to_date - timedelta(days=1), base[-1][2], new_per_day)
        deals = self.deals + trading(first, to_date - timedelta(days=1), 2, 6.0)
        windows = [('BOOS', date(2026, 1, 5), date(2026, 1, 19), 20, 100), ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300),
                   ('FOOS', date(2026, 8, 29), to_date - timedelta(days=1), 54, 270)]
        folder = Path(self.controller.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']
        (folder / 'attempt-issued.json').parent.mkdir(parents=True, exist_ok=True)
        (folder / 'attempt-issued.json').write_text('{}', encoding='utf-8')
        return make_unit(folder, rows=rows, deals=deals, alias=member['alias'], symbol=tester['Symbol'], run_id=member['capture_id'],
                         start=datetime.strptime(tester['FromDate'], '%Y.%m.%d').date(), requested_to=to_date, windows=windows)


class ScanTests(CatchupCase):
    def test_before_friday_close_auto_is_last_week(self):
        result = sc.evidence_scan([self.run], now=BEFORE_CLOSE)
        self.assertEqual(result['target']['iso'], '2026-09-25')
        status = {row['symbol']: row['status'] for row in result['exports']}
        self.assertEqual(status, dict(EURUSD='behind', GBPUSD='ahead', USDJPY='ineligible'))
        self.assertEqual(result['summary']['counts']['ahead'], 1)
        self.assertIn('after this week closes (2026.10.02', result['summary']['plain'])
        self.assertFalse(result['summary']['consistent'])
        self.assertFalse(result['writes'])

    def test_after_close_everything_is_behind(self):
        result = sc.evidence_scan([self.run], now=AFTER_CLOSE)
        rows = {row['symbol']: row for row in result['exports']}
        self.assertEqual(result['target']['iso'], '2026-10-02')
        self.assertEqual((rows['EURUSD']['status'], rows['EURUSD']['new_weekdays'], rows['EURUSD']['new_first_day']), ('behind', 6, '2026-09-25'))
        self.assertEqual((rows['GBPUSD']['status'], rows['GBPUSD']['new_weekdays']), ('behind', 1))
        self.assertIn('Below the batch export thresholds', rows['USDJPY']['reasons'][0])
        self.assertEqual(result['summary']['evidence_ends'], {'2026-09-24': 1, '2026-10-01': 1})
        with_weak = sc.evidence_scan([self.run], now=AFTER_CLOSE, include_below_threshold=True)
        self.assertEqual(with_weak['summary']['counts']['behind'], 3)

    def test_explicit_end_and_current(self):
        result = sc.evidence_scan([self.ahead], value='2026-10-01', now=AFTER_CLOSE)
        self.assertEqual(result['exports'][0]['status'], 'current')
        self.assertTrue(result['summary']['consistent'])
        self.assertIn('not a Friday', result['target']['warnings'][0])
        with self.assertRaisesRegex(ValueError, 'not a closed broker day'):
            sc.evidence_scan([self.ahead], value='2026-10-03', now=AFTER_CLOSE)


class PrepareTests(CatchupCase):
    def ini(self, member):
        return Path(member['config_path']).read_bytes().decode('utf-16')

    def test_prepare_freezes_one_pass_per_behind_export(self):
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        result = self.runner.prepare('cu1', self.plan())
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(self.starts or self.closes)
        manifest = read_json(self.runner.path('cu1') / 'manifest.json')
        self.assertEqual((manifest['mode'], manifest['native_launch_qualified'], manifest['evidence_end']['iso']), ('OOSCatchup', False, '2026-10-02'))
        self.assertEqual([m['tester']['Symbol'] for m in manifest['members']], ['EURUSD', 'GBPUSD'])
        member = manifest['members'][0]
        self.assertEqual(member['tester'], dict(Expert='GOAT-EA\\GOAT V1.49.ex5', Symbol='EURUSD', Period='M1', Model=4, ExecutionMode=0,
                                                Optimization=0, FromDate='2026.01.05', ToDate='2026.10.03', ForwardMode=0, Deposit=10000,
                                                Currency='USD', Leverage='1:100', UseLocal=1, UseRemote=0, UseCloud=0, Visual=0,
                                                ShutdownTerminal=1, ReplaceReport=0, Report='MQL5\\Files\\GOATStudio\\CatchupReports\\' + member['alias']))
        self.assertEqual(member['original']['evidence_end'], '2026-09-24')
        self.assertEqual(member['new_window'], dict(first_day='2026-09-25', last_day='2026-10-02', weekdays=6))
        self.assertEqual(member['optimization_window']['source'], 'run_manifest')
        ini = self.ini(member)
        self.assertIn('[Common]\r\nLogin=123\r\nServer=Test-Demo\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n', ini)
        self.assertNotIn('Password', ini)
        self.assertIn('EA_Desc=%s@{mode=EXPORT,dt_BOOS_end=2026.01.19,dt_FOOS_start=2026.08.29,dt_FWD_start=2026.07.17,dt_FWD_end=2026.08.28}\r\n'
                      % member['alias'], ini)
        for line in ('Sequence_Export_Enabled=true', 'Sequence_Export_Id=' + member['capture_id'], 'Sequence_Export_Start=2026.01.05',
                     'Sequence_Export_End=2026.10.03', 'Sequence_Export_Model=4', 'Mode_Operation=9', 'Grid_Size=-2.25', 'Lots_Input=0.05'):
            self.assertIn(line + '\r\n', ini)
        self.assertEqual(member['attempt_token'], hashlib.sha256(member['capture_id'].encode()).hexdigest()[:16])
        frozen = Path(member['set_path']).read_bytes().decode('utf-16')
        self.assertIn('EA_Desc=' + member['alias'] + '\r\n', frozen)
        self.assertEqual(Path(member['source_inputs_path']).read_text(encoding='utf-8'), 'Grid_Size=-2.25\n')
        rows = {Path(r['set_path']).parent.name: r for r in manifest['exports']}
        self.assertEqual(rows['USDJPY']['status'], 'ineligible')
        self.assertEqual({p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}, before)
        preview = result['preview']
        self.assertEqual((preview['member_count'], preview['writes']), (2, True))

    def test_same_id_repeats_and_other_plans_refuse(self):
        plan = self.plan()
        self.runner.prepare('cu1', plan)
        self.assertEqual(self.runner.prepare('cu1', plan)['status'], 'prepared')
        with self.assertRaisesRegex(ValueError, 'different plan'):
            self.runner.prepare('cu1', self.plan(sets=[self.behind]))

    def test_nothing_to_do_writes_nothing(self):
        runner = sc.CatchupRunner(self.controller, process=self.process, clock=lambda: self.now, sleep=self.sleep, now=BEFORE_CLOSE)
        with self.assertRaisesRegex(ValueError, 'Nothing to catch up to 2026-09-25'):
            runner.prepare('cu2', self.plan(sets=[self.ahead]))
        self.assertFalse(runner.path('cu2').exists())
        self.assertFalse((Path(self.controller.install['terminal_data_root']) / 'config/GOATStudio/Catchups').exists())

    def test_validate_is_a_dry_run(self):
        result = self.runner.validate(self.plan())
        self.assertEqual((result['writes'], result['member_count']), (False, 2))
        self.assertFalse(self.runner.base.exists())

    def test_library_copy_needs_an_explicit_delay(self):
        copy_dir = self.root / 'library'
        unit = make_unit(copy_dir, rows=self.history + [(datetime(2026, 9, 24, 23, 59), self.history[-1][1], self.history[-1][2])],
                         deals=self.deals, alias='Rbehind01', windows=[('SAMPLE', date(2026, 1, 19), date(2026, 8, 29), 200, 900),
                                                                      ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300),
                                                                      ('FOOS', date(2026, 8, 29), date(2026, 9, 24), 38, 190)])
        refused = self.runner.validate(self.plan(sets=[unit]))
        self.assertEqual(refused['member_count'], 0)
        self.assertIn('ExecutionMode', refused['exports'][0]['reasons'][0])
        accepted = self.runner.validate(self.plan(sets=[unit], assume=dict(ExecutionMode=0)))
        self.assertEqual(accepted['members'][0]['assumed'], ['ExecutionMode'])
        frozen = self.runner._build(self.runner.base / 'x', self.plan(sets=[unit], assume=dict(ExecutionMode=0)))[0][0]
        self.assertEqual(frozen['optimization_window'], dict(FromDate='2026.01.19', ToDate='2026.08.28', ForwardDate='2026.07.17', source='set_header'))

    def test_other_broker_and_non_standard_mode_are_ineligible(self):
        other = make_unit(self.run / 'deploy' / 'Rother001' / 'EURJPY', rows=self.history, alias='Rother001', symbol='EURJPY', server='Other-Live')
        mode = make_unit(self.run / 'deploy' / 'Rmode0001' / 'EURCHF', rows=self.history, alias='Rmode0001', symbol='EURCHF',
                         values=dict(VALUES, Mode_Operation='11'))
        self.write_run_manifest(aliases=('Rbehind01', 'Rother001', 'Rmode0001'))
        result = self.runner.validate(self.plan(sets=[other, mode]))
        reasons = {Path(r['set_path']).parent.name: ' '.join(r['reasons']) for r in result['exports']}
        self.assertIn('Other-Live', reasons['EURJPY'])
        self.assertIn('Mode_Operation=9', reasons['EURCHF'])

    def test_another_or_unknown_ea_build_is_ineligible(self):
        self.write_run_manifest(ea_sha256='f' * 64)
        refused = self.runner.validate(self.plan(sets=[self.behind]))
        self.assertEqual(refused['member_count'], 0)
        self.assertIn('another EA binary', refused['exports'][0]['reasons'][0])
        unknown = make_unit(self.root / 'library', rows=self.history, alias='Rbehind01', capture=False,
                            windows=[('SAMPLE', date(2026, 1, 19), date(2026, 8, 29), 200, 900), ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300),
                                     ('FOOS', date(2026, 8, 29), date(2026, 9, 24), 38, 190)])
        result = self.runner.validate(self.plan(sets=[unknown], assume=dict(ExecutionMode=0)))
        self.assertIn('EA build that made this export is unknown', ' '.join(result['exports'][0]['reasons']))
        self.write_run_manifest()
        accepted = self.runner.validate(self.plan(sets=[self.behind]))
        self.assertEqual(accepted['member_count'], 1)
        pins = self.runner._build(self.runner.base / 'x', self.plan(sets=[self.behind]))[0][0]['pins']
        self.assertEqual((pins['installed_ea_sha256'], pins['original_ea_sha256'], pins['model']),
                         (hashlib.sha256(b'ex5').hexdigest(), hashlib.sha256(b'ex5').hexdigest(), 4))

    def test_single_pass_tester_goes_through_the_shared_validator(self):
        manifest = self.runner._build(self.runner.base / 'x', self.plan(sets=[self.behind]))[0][0]
        sc._validate_single_pass(manifest['tester'])
        for change in (dict(Optimization=2), dict(Model=1), dict(ForwardMode=1), dict(ShutdownTerminal=0),
                       dict(Leverage='lots'), dict(FromDate='2026-01-05'), dict(UseCloud=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                sc._validate_single_pass(manifest['tester'] | change)

    def test_verdict_rules_and_threshold_choice_are_frozen_and_stamped(self):
        self.runner.prepare('cu1', self.plan(include_below_threshold=True, verdict_rules=dict(min_trades=3, held_pace=0.4)))
        manifest = read_json(self.runner.path('cu1') / 'manifest.json')
        self.assertEqual((manifest['verdict_rules']['min_trades'], manifest['verdict_rules']['held_pace']), (3, 0.4))
        self.assertEqual(manifest['verdict_rules']['overridden'], ['held_pace', 'min_trades'])
        self.assertTrue(manifest['include_below_threshold'])
        weak = next(m for m in manifest['members'] if m['tester']['Symbol'] == 'USDJPY')
        self.assertFalse(weak['original']['threshold']['passing'])  # queued anyway, its miss stays on record
        self.assertEqual(weak['original']['threshold']['arf_margin'], -0.1)
        scan = sc.evidence_scan([self.run], now=AFTER_CLOSE)
        self.assertEqual(scan['rules']['evidence_end'], 'goat-closed-week-v1')
        self.assertTrue(scan['rules']['thresholds_applied_to_eligibility'])
        self.assertIn('sr_margin', scan['exports'][0]['threshold'])

    def test_plan_shape_is_strict(self):
        for change in (dict(job_timeout_seconds=10), dict(sets=[]), dict(sets=['relative.set']), dict(assume=dict(ExecutionMode=-1)),
                       dict(assume=dict(Deposit=5)), dict(include_below_threshold='yes'), dict(extra=1),
                       dict(verdict_rules=dict(min_trades=0)), dict(verdict_rules=dict(score=1))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.runner.validate(self.plan() | change)
        with self.assertRaisesRegex(ValueError, 'Duplicate SET path'):
            self.runner.validate(self.plan(sets=[self.behind, self.behind]))
        with self.assertRaisesRegex(ValueError, 'Catch-up ID'):
            self.runner.prepare('bad id', self.plan())


class NativeCycleTests(CatchupCase):
    def test_full_cycle_moves_the_retest_and_judges_the_new_weeks(self):
        original = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        self.runner.prepare('cu1', self.plan())
        self.auto = True
        state = self.runner.start('cu1', 30)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual((len(self.closes), len(self.starts)), (1, 2))
        guard_active_seed(self.controller.root)  # slot released
        manifest = read_json(self.runner.path('cu1') / 'manifest.json')
        member = manifest['members'][0]
        pending = Path(self.controller.install['common_files_root']) / 'GOATSequencePending' / member['capture_id'] / 'source-inputs.set'
        self.assertEqual(pending.read_text(encoding='utf-8'), 'Grid_Size=-2.25\n')
        attempt = Path(self.controller.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']
        self.assertEqual(sorted(p.name for p in attempt.iterdir()), ['attempt-issued.json'])
        evidence = Path(member['evidence_dir'])
        names = sorted(p.name for p in evidence.iterdir())
        self.assertEqual(len(names), 4)
        self.assertIn('evidence-version.json', names)
        version = read_json(evidence / 'evidence-version.json')
        self.assertEqual(version['schema'], 'goat-evidence-version-v1')
        self.assertEqual((version['evidence_end'], version['target_end'], version['symbol']), ('2026-10-02', '2026-10-02', 'EURUSD'))
        self.assertEqual(version['original']['set_path'], str(self.behind))
        self.assertEqual(version['values_sha256'], version['original']['values_sha256'])
        self.assertEqual(version['verdict']['verdict'], 'held_up')
        self.assertIn('Low confidence: 12 trades over 6 trading days.', version['verdict']['plain'])
        # What the desktop import writes as catchUp; #2170 compares added_at with a portfolio's chosenAt.
        stamp = version['catch_up']
        self.assertEqual((stamp['schema'], stamp['evidence_end'], stamp['first_day'], stamp['last_day'], stamp['verdict'], stamp['comparable']),
                         ('goat-catch-up-import-v1', '2026-10-02', '2026-09-25', '2026-10-02', 'held_up', True))
        self.assertEqual((stamp['rules'], stamp['added_at'], stamp['original_set_sha256']),
                         ('goat-catchup-verdict-v2', version['created_utc'], version['original']['set_sha256']))
        checks = {item['check']: item['ok'] for item in version['comparability']['checks']}
        self.assertTrue(version['comparability']['comparable'])
        self.assertEqual({k for k, ok in checks.items() if ok}, {'inputs', 'ea_build', 'ea_name', 'model', 'symbol', 'server', 'deposit',
                                                                 'leverage', 'currency', 'execution_delay', 'reproduced'})
        self.assertIn('not as proof', version['caveat'])
        # The inputs a later scored qualification needs, with the rules that produced this verdict.
        qualification = version['qualification']
        self.assertEqual((qualification['schema'], qualification['scored'], qualification['verdict']), ('goat-qualification-inputs-v1', False, 'held_up'))
        self.assertEqual(qualification['evidence_end'], dict(rule='goat-closed-week-v1', mode='auto', requested='auto', date='2026-10-02'))
        self.assertEqual(qualification['export_thresholds']['basis'], 'run_export_settings')
        self.assertEqual((qualification['export_thresholds']['arf_margin'], qualification['export_thresholds']['sr_margin']), (0.3, 0.5))
        self.assertTrue(qualification['thresholds_applied_to_eligibility'])
        self.assertEqual(qualification['verdict_rules']['id'], 'goat-catchup-verdict-v2')
        self.assertEqual(qualification['signals']['trades'], 12)
        self.assertEqual({p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}, original)
        report = self.runner.report('cu1')
        self.assertEqual(report['counts'], dict(held_up=1, too_few_trades=1))
        self.assertTrue(all(row['summary']['comparable'] for row in report['members']))
        self.assertEqual((report['verdict_rules']['min_trades'], report['scored'], report['qualification_schema']), (5, False, 'goat-qualification-inputs-v1'))
        self.assertEqual(report['members'][0]['export_thresholds']['min_sr'], 2.5)
        self.assertEqual(report['members'][0]['signals']['weekdays'], 6)
        row = report['members'][0]
        self.assertEqual((row['summary']['weekdays'], row['summary']['trades'], row['summary']['reproduced']), (6, 12, True))
        # The versions now count: both exports are caught up to Fri Oct 2.
        scan = sc.evidence_scan([self.run], now=AFTER_CLOSE, controller_root=self.controller.root)
        self.assertEqual(scan['summary']['counts']['caught_up'], 2)
        self.assertEqual(scan['summary']['evidence_ends'], {'2026-10-02': 2})
        self.assertEqual(len(sc.versions(self.controller.root)), 2)
        # Repeating start never relaunches finished work.
        self.runner.resume('cu1', 5)
        self.assertEqual(len(self.starts), 2)

    def test_catchup_holds_the_shared_terminal_slot(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.runner.start('cu1', 1)
        with self.assertRaisesRegex(ValueError, 'owns this terminal'):
            guard_active_seed(self.controller.root)

    def test_missing_output_stops_the_catchup(self):
        self.runner.prepare('cu1', self.plan())
        self.runner.start('cu1', 1)
        self.process_state = None
        state = self.runner.status('cu1')
        self.assertEqual([m['status'] for m in state['members']], ['missing_output', 'pending'])
        self.assertEqual(state['status'], 'stopped')
        self.runner.resume('cu1', 1)
        self.assertEqual(len(self.starts), 1)  # a failed member stops the run; nothing is retried
        # "Bring all" re-queues under a new attempt id: the failed and the never-run member are both still behind.
        again = self.runner.validate(self.plan())
        self.assertEqual([m['symbol'] for m in again['members']], ['EURUSD', 'GBPUSD'])

    def test_requeue_skips_caught_up_members_and_retries_unjudged_ones(self):
        self.runner.prepare('cu1', self.plan())
        self.auto = True
        self.runner.start('cu1', 30)
        self.assertEqual(self.runner.validate(self.plan())['member_count'], 0)   # idempotent: nothing left to bring
        gbp = next(v for v in sc.versions(self.controller.root) if v['symbol'] == 'GBPUSD')
        record = read_json(Path(gbp['version_path']))
        record['verdict'] = dict(record['verdict'], verdict='not_comparable', reasons=['EA build differs'])
        Path(gbp['version_path']).write_text(json.dumps(record), encoding='utf-8')
        scan = sc.evidence_scan([self.run], now=AFTER_CLOSE, controller_root=self.controller.root)
        row = next(r for r in scan['exports'] if r['symbol'] == 'GBPUSD')
        self.assertEqual((row['status'], row['previous_attempt']['verdict']), ('behind', 'not_comparable'))
        self.assertEqual([m['symbol'] for m in self.runner.validate(self.plan())['members']], ['GBPUSD'])

    def test_ambiguous_outputs_fail(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.runner.start('cu1', 1)
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        first = self.native_retest(member)
        first.with_name(first.name.replace('Trds=100', 'Trds=101')).write_bytes(first.read_bytes())
        self.process_state = None
        state = self.runner.status('cu1')
        self.assertEqual(state['members'][0]['status'], 'failed')
        self.assertIn('Ambiguous', state['members'][0]['error'])

    def test_changed_original_fails_the_member_without_moving(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.runner.start('cu1', 1)
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        retest = self.native_retest(member)
        raw = self.behind.read_bytes().decode('utf-16').replace('Lots_Input=0.05', 'Lots_Input=0.06').encode('utf-16')
        self.behind.write_bytes(raw)
        self.process_state = None
        state = self.runner.status('cu1')
        self.assertEqual(state['members'][0]['status'], 'failed')
        self.assertIn('Original export changed', state['members'][0]['error'])
        self.assertTrue(retest.is_file())
        self.assertFalse(Path(member['evidence_dir']).exists())

    def test_foreign_capture_namespace_blocks_before_launch(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        pending = Path(self.controller.install['common_files_root']) / 'GOATSequencePending' / member['capture_id']
        pending.mkdir(parents=True)
        (pending / 'source-inputs.set').write_text('other', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            self.runner.start('cu1', 1)
        self.assertFalse(self.starts)
        self.assertEqual(read_json(self.runner.path('cu1') / 'state.json')['members'][0]['status'], 'pending')

    def test_unjudgeable_retest_is_kept(self):
        self.runner.prepare('cu1', self.plan(sets=[self.behind]))
        self.runner.start('cu1', 1)
        member = read_json(self.runner.path('cu1') / 'manifest.json')['members'][0]
        retest = self.native_retest(member)
        csv_path = retest.with_name(retest.name[:-4] + '.csv')
        csv_path.write_bytes('<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>\r\nbad\r\n'.encode('utf-16'))
        self.process_state = None
        state = self.runner.status('cu1')
        self.assertEqual(state['members'][0]['status'], 'completed')
        version = read_json(Path(member['evidence_dir']) / 'evidence-version.json')
        self.assertEqual(version['verdict']['verdict'], 'unjudged')


if __name__ == '__main__':
    unittest.main()
