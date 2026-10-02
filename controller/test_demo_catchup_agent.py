"""Broker-verified demo OOS catch-up lane: same guard chain, scope and slot as seed hunts.

The real DemoAgent, CatchupRunner, evidence reader and verdict run here; only the MT5
process, broker SDK and Studio controller handle are local fixtures.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time as clock
import types
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import DemoAgent, digest, read_json
import studio_evidence_end
from studio_seed_slot import guard_active_seed
from test_demo_agent import MetaTrader
from test_demo_seed_agent import MONITOR, FakeController, SeedProcess
from test_studio_catchup import POLICY, SCHEMA, export_settings
from test_studio_catchup_verdict import TESTER, daily, make_unit, trading


class DemoCatchupAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.data = base / 'data'; self.common = base / 'common'; self.root = base / 'state'
        for folder in (self.data, self.common, self.root): folder.mkdir()
        self.exe = base / 'bin/terminal64.exe'; self.exe.parent.mkdir(); self.exe.write_bytes(b'fake')
        self.binary = self.data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'; self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'ea-149')
        self.installation = self.root / 'installation.json'
        self.installation.write_text(json.dumps(dict(schema_version=1, controller_version='1.49-beta.1', ea_version='1.49',
            ea_sha256=digest(self.binary), controller_state_root=str(self.root), terminal_data_root=str(self.data),
            common_files_root=str(self.common), terminal_executable=str(self.exe), ea_relative_path=r'GOAT-EA\GOAT V1.49.ex5')))
        install = read_json(self.installation)
        self.account = dict(login='3000082754', server='Test-Demo')
        (self.root / 'session.json').write_text(json.dumps(dict(directory_id='session-one', terminal_id='terminal-one',
            run_id='session-one', demo_only=True, account=self.account, authority_kind='demo_direct', installation_sha256=sha(install))))
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with closing(sqlite3.connect(self.root / 'studio.sqlite', isolation_level=None)) as db:
            db.execute('CREATE TABLE studio_queues (binding TEXT PRIMARY KEY, jobs TEXT)')
            db.execute('CREATE TABLE studio_state (binding TEXT PRIMARY KEY, owner TEXT, generation INTEGER)')
            db.execute('INSERT INTO studio_queues VALUES (?, ?)', (binding, '[]'))
            db.execute('INSERT INTO studio_state VALUES (?, ?, ?)', (binding, 'agent', 1))
        ui = self.data / 'MQL5/Files/GOATStudio/ui-observation.json'; ui.parent.mkdir(parents=True)
        (ui.parent / 'native-gate').mkdir()
        ui.write_text(json.dumps(dict(owner='agent', run_id='session-one', runtime=dict(account_demo=True,
            account_login=self.account['login'], account_server=self.account['server'], program_path=str(self.binary)))))
        (self.root / 'demo-agent').mkdir()
        (self.root / 'demo-agent/verified-build.json').write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=MONITOR)))
        self.schema, self.policy = SCHEMA, POLICY
        self.base = base; self.new_per_day = 10
        self.plan = base / 'catchup-plan.json'
        self.write_exports()
        self.owner = 'agent'; self.opened = []; self.auto = False
        self.now = clock.time()
        self.process = SeedProcess(); self.mt5 = MetaTrader(self.exe, self.data); self.mt5.server = 'Test-Demo'
        # Evidence ends resolve against Saturday 2026-10-03 (week of Oct 2 closed); the agent keeps the real clock.
        real_utc = studio_evidence_end._utc
        saturday = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)
        self.patches = [patch('demo_agent.tester_state', return_value='idle'),
                        patch('studio_terminal_isolation.live_terminals', return_value=[]),
                        patch('studio_evidence_end._utc', side_effect=lambda now: saturday if now is None else real_utc(now)),
                        patch('goat_studio.Controller', side_effect=lambda path: FakeController(self, path))]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        self.agent = DemoAgent(self.installation, process=self.process, mt5=self.mt5, clock=lambda: self.now, sleep=self.sleep)

    def write_exports(self, forward_per_day=10, run_name='Rrun1'):
        """Two kept exports of one run, ending last Thursday; the run's own manifest gives the tester settings.

        ``forward_per_day`` is the equity pace inside the TESTER forward window [ForwardDate 2026-07-17, ToDate 2026-08-28).
        Writes the catch-up plan for these two exports.
        """
        forward_first, forward_last = date(2026, 7, 17), date(2026, 8, 27)
        before = daily(date(2026, 1, 5), forward_first - timedelta(days=1), 10000, 10)
        forward = daily(forward_first, forward_last, before[-1][2], forward_per_day)
        self.history = before + forward + daily(forward_last + timedelta(days=1), date(2026, 9, 24), forward[-1][2], 10)
        self.deals = trading(date(2026, 1, 5), date(2026, 9, 24), 2, 5.1)
        run = self.base / 'GOAT' / run_name; (run / 'deploy').mkdir(parents=True); export_settings(run)
        forced = (datetime(2026, 9, 24, 23, 59), self.history[-1][1], self.history[-1][2])
        windows = [('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300), ('FOOS', date(2026, 8, 29), date(2026, 9, 24), 38, 190)]
        self.sets = [make_unit(run / 'deploy' / alias / symbol, rows=self.history + [forced], deals=self.deals, alias=alias, symbol=symbol,
                               windows=windows, server='Test-Demo') for alias, symbol in (('Rone00001', 'EURUSD'), ('Rtwo00002', 'GBPUSD'))]
        jobs = [dict(run_alias=a, tester=dict(TESTER, Deposit=10000, Currency='USD', Leverage='1:100', ExecutionMode=0)) for a in ('Rone00001', 'Rtwo00002')]
        (run / 'manifest.json').write_text(json.dumps(dict(ea_sha256=digest(self.binary), jobs=jobs)), encoding='utf-8')
        self.run = run
        self.plan.write_text(json.dumps(dict(schema_version=1, evidence_end='2026-10-02', sets=[str(p) for p in self.sets],
                                             job_timeout_seconds=600)))

    def sleep(self, seconds):
        self.now += seconds
        if self.auto and self.process.current and self.process.current['created_utc'].startswith('member'):
            self.finish_member(len(self.process.starts) - 1)

    def manifest(self):
        return read_json(self.root / 'catchups/cu1/manifest.json')

    def finish_member(self, index):
        member = self.manifest()['members'][index]
        tester = member['tester']
        to_date = datetime.strptime(tester['ToDate'], '%Y.%m.%d').date()
        rows = self.history + daily(date(2026, 9, 25), to_date - timedelta(days=1), self.history[-1][2], self.new_per_day)
        folder = self.common / 'TEMP' / 'SQ' / member['attempt_token']
        unit = make_unit(folder, rows=rows, deals=self.deals + trading(date(2026, 9, 25), to_date - timedelta(days=1), 2, 6.0),
                         alias=member['alias'], symbol=tester['Symbol'], run_id=member['capture_id'], server='Test-Demo',
                         start=datetime.strptime(tester['FromDate'], '%Y.%m.%d').date(), requested_to=to_date,
                         windows=[('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300), ('FOOS', date(2026, 8, 29), date(2026, 10, 2), 50, 250)])
        for path in [unit] + list(folder.rglob('*')):
            os.utime(path, (self.now, self.now))
        self.process.current = None

    def actions(self):
        path = self.root / 'demo-agent/actions.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_read_only_tools_never_touch_the_terminal(self):
        scan = self.agent.evidence_scan([str(self.run)], '2026-10-02')
        self.assertEqual((scan['summary']['counts']['behind'], scan['writes']), (2, False))
        end = self.agent.evidence_end('2026-09-25')
        self.assertEqual((end['iso'], end['ea_evidence_end_setting']['supported']), ('2026-09-25', False))
        self.assertEqual(end['batch_exports_now']['weekday'], 'Thu')
        preview = self.agent.catchup_validate(self.plan)
        self.assertEqual((preview['member_count'], preview['writes']), (2, False))
        self.assertFalse((self.root / 'catchups').exists())
        self.assertEqual((self.process.starts, self.process.closes), ([], []))

    def test_full_catchup_runs_in_the_demo_scope_and_shares_the_seed_slot(self):
        prepared = self.agent.catchup_prepare('cu1', self.plan)
        self.assertEqual(prepared['status'], 'prepared')
        self.auto = True
        result = self.agent.catchup_start('cu1', 60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.process.closes, [MONITOR])
        self.assertEqual(len(self.process.starts), 2)
        self.assertTrue(all(start.endswith('.ini') and 'Catchups' in start for start in self.process.starts))
        record = read_json(self.root / 'demo-agent/catchup-starts/cu1.json')
        self.assertEqual((record['account'], record['manifest_sha256']), (self.account, prepared['manifest_sha256']))
        self.assertEqual([o['operation'] for o in self.opened], ['catchup-prepare', 'catchup-start'])
        phases = [(a['operation'], a['phase']) for a in self.actions()]
        self.assertEqual(phases[:3], [('catchup_prepare', 'intent'), ('catchup_prepare', 'verified'), ('catchup_start', 'start_recorded')])
        self.assertIn(('catchup_drive', 'slice'), phases)
        self.assertTrue(guard_active_seed(self.root))
        report = self.agent.catchup_report('cu1')
        self.assertEqual(report['counts'], dict(held_up=2))
        self.assertTrue(all(Path(row['version_path']).is_file() for row in report['members']))
        status = self.agent.research_status()
        self.assertEqual(status['activity']['kind'], 'idle')

    def test_losing_forward_window_then_a_small_new_profit_caps_at_weakened(self):
        # Claude-Mac fold-in, end to end: the forward window lost 3/day, then the new weeks made +2/day.
        # That is a recovery, so prepare -> start -> report and the import stamp all say weakened, never held_up.
        self.write_exports(forward_per_day=-3, run_name='Rlosing'); self.new_per_day = 2
        self.assertEqual(self.agent.catchup_prepare('cu1', self.plan)['status'], 'prepared')
        self.auto = True
        self.assertEqual(self.agent.catchup_start('cu1', 60)['status'], 'completed')
        report = self.agent.catchup_report('cu1')
        self.assertEqual(report['counts'], dict(weakened=2))
        for row in report['members']:
            self.assertGreater(row['summary']['net'], 0, 'the new weeks made a small profit')
            self.assertIn('Forward window lost (-3.0/day); profitable since', row['summary']['plain'])
            self.assertEqual(row['signals']['forward_net_per_day'], -3.0)
            stamp = read_json(Path(row['version_path']))['catch_up']
            self.assertEqual((stamp['verdict'], stamp['comparable']), ('weakened', True))
        self.assertNotIn('held_up', json.dumps(report['counts']))

    def test_owner_stop_and_research_status_know_a_running_catchup(self):
        self.agent.catchup_prepare('cu1', self.plan)
        self.agent.catchup_start('cu1', 6)
        running = self.process.inspect()
        activity = self.agent.research_status()['activity']
        self.assertEqual((activity['kind'], activity['members_total']), ('catchup', 2))
        self.assertIn('catch-up', activity['headline'].lower())
        with self.assertRaisesRegex(ValueError, 'already started; use catchup-resume'):
            self.agent.catchup_start('cu1', 30)
        result = self.agent.stop()
        self.assertEqual((result['batch_id'], result['owner_stop']), ('cu1', True))
        self.assertTrue(result['status'].startswith('catchup_'))
        self.assertEqual(self.process.closes[-1], running)
        self.assertEqual([m['status'] for m in self.agent.catchup_status('cu1')['catchup']['members']], ['cancelled', 'cancelled'])

    def test_pause_between_members_and_resume(self):
        self.agent.catchup_prepare('cu1', self.plan)
        self.agent.catchup_start('cu1', 6)
        paused = self.agent.batch_pause('cu1')
        self.assertEqual((paused['kind'], paused['state']), ('catchup', 'pausing'))
        self.finish_member(0)
        self.process.current = None
        second = self.agent.catchup_resume('cu1', 6)
        self.assertTrue(second.get('paused'))
        self.assertEqual(len(self.process.starts), 1)
        self.auto = True
        resumed = self.agent.batch_resume('cu1')
        self.assertEqual((resumed['kind'], resumed['state']), ('catchup', 'resumed'))
        self.assertEqual(resumed['seed']['status'], 'completed')

    def test_nothing_behind_refuses_without_files(self):
        self.plan.write_text(json.dumps(dict(schema_version=1, evidence_end='2026-09-24', sets=[str(p) for p in self.sets],
                                             job_timeout_seconds=600)))
        with self.assertRaisesRegex(ValueError, 'Nothing to catch up to 2026-09-24'):
            self.agent.catchup_prepare('cu1', self.plan)
        self.assertFalse((self.root / 'catchups/cu1').exists())


if __name__ == '__main__':
    unittest.main()
