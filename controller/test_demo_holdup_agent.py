"""Broker-verified demo hold-up test lane (goatai#1885): same guard chain, scope, slot and STOP as seeds.

The real DemoAgent, HoldupRunner and MT5 report parser run here; only the MT5 process, broker SDK and
Studio controller handle are local fixtures (test_demo_seed_agent). Each member's "MT5 run" writes
the recorded MT5 report (fixtures/holdup) with that member's EA_Desc and the installed EA's name.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time as clock
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import DemoAgent, digest, read_json
import studio_evidence_end
from studio_seed_slot import guard_active_seed
from test_demo_agent import MetaTrader
from test_demo_seed_agent import MONITOR, FakeController, SeedProcess
from test_studio_holdup import report_inputs
from test_studio_tester_report import fixture_text, schema_for


class DemoHoldupAgentTests(unittest.TestCase):
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
        self.account = dict(login='3000082754', server='Darwinex-Demo')
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
        values = dict(report_inputs(), Mode_Operation='9')
        self.schema = schema_for(values)
        self.schema['inputs']['Mode_Bias'] = dict(type='int', optimizable=True, enum_choices=dict(Bias_Disabled=1, Bias_Opens=0))
        self.schema['inputs']['Mode_Lots'] = dict(type='int', optimizable=True, enum_choices=dict(Fixed=0, Balance=1, RiskperSeq=2))
        self.policy = dict(header_sha256='a' * 64, main_sha256='b' * 64, coverage='indicator_mode_gates_only', rules=[])
        self.source = base / 'sets' / 'GOAT V1.49 SP500,M1_Trds=128_Prf=-880_DD=1960_PF=0.85_SR=-2.80_ARF=-0.1.set'
        self.source.parent.mkdir()
        self.source.write_bytes(b'\xff\xfe' + ('\r\n'.join(['; GOAT V1.49 SP500,M1'] + ['%s=%s' % kv for kv in values.items()]) + '\r\n').encode('utf-16-le'))
        self.plan = base / 'holdup-plan.json'
        self.write_plan()
        self.owner = 'agent'; self.opened = []; self.auto = False
        self.now = clock.time()
        self.process = SeedProcess(); self.mt5 = MetaTrader(self.exe, self.data)
        real_utc = studio_evidence_end._utc
        saturday = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)
        self.patches = [patch('demo_agent.tester_state', return_value='idle'),
                        patch('studio_terminal_isolation.live_terminals', return_value=[]),
                        patch('studio_evidence_end._utc', side_effect=lambda now: saturday if now is None else real_utc(now)),
                        patch('goat_studio.Controller', side_effect=lambda path: FakeController(self, path))]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        self.agent = DemoAgent(self.installation, process=self.process, mt5=self.mt5, clock=lambda: self.now, sleep=self.sleep)

    def write_plan(self, **extra):
        test = dict(set_path=str(self.source), set_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
                    window=dict(start='2026-01-19', end='2026-09-11'),
                    tester=dict(Model=4, ExecutionMode=0, Deposit=100000, Currency='USD', Leverage='1:100'))
        self.plan.write_text(json.dumps(dict(dict(schema_version=1, job_timeout_seconds=900, tests=[test]), **extra)))

    def sleep(self, seconds):
        self.now += seconds
        if self.auto and self.process.current and self.process.current['created_utc'].startswith('member'):
            self.mt5_writes_report(len(self.process.starts) - 1)
            self.process.current = None

    def mt5_writes_report(self, index):
        member = read_json(self.root / 'holdups/h1/manifest.json')['members'][index]
        text = fixture_text().replace('<b>GOAT V1.47</b>', '<b>GOAT V1.49</b>').replace('<b>Mode_Operation=0</b>', '<b>Mode_Operation=9</b>')
        original = [line for line in text.splitlines() if '<b>EA_Desc=' in line][0]
        text = text.replace(original, original.split('<b>EA_Desc=')[0] + '<b>EA_Desc=' + member['alias'] + '</b></td>')
        path = self.data / 'MQL5/Files/GOATStudio/HoldupReports' / (member['alias'] + '.htm')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xff\xfe' + text.encode('utf-16-le'))

    def actions(self):
        path = self.root / 'demo-agent/actions.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_validate_is_non_executing(self):
        result = self.agent.holdup_validate(self.plan)
        self.assertEqual((result['valid'], result['writes'], result['test_count']), (True, False, 1))
        self.assertFalse((self.root / 'holdups').exists())
        self.assertEqual((self.process.starts, self.process.closes), ([], []))
        self.assertEqual([a['operation'] for a in self.actions()], ['holdup_validate'])

    def test_a_full_hold_up_test_runs_in_the_demo_scope_and_shares_the_seed_slot(self):
        prepared = self.agent.holdup_prepare('h1', self.plan)
        self.assertEqual(prepared['status'], 'prepared')
        self.auto = True
        result = self.agent.holdup_start('h1', 60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual((self.process.closes, len(self.process.starts)), ([MONITOR], 1))
        self.assertTrue(self.process.starts[0].endswith('.ini') and 'Holdups' in self.process.starts[0])
        record = read_json(self.root / 'demo-agent/holdup-starts/h1.json')
        self.assertEqual((record['account'], record['manifest_sha256'], record['broker']['demo']), (self.account, prepared['manifest_sha256'], True))
        self.assertEqual([o['operation'] for o in self.opened], ['holdup-prepare', 'holdup-start'])
        phases = [(a['operation'], a['phase']) for a in self.actions()]
        self.assertEqual(phases[:3], [('holdup_prepare', 'intent'), ('holdup_prepare', 'verified'), ('holdup_start', 'start_recorded')])
        self.assertTrue(guard_active_seed(self.root))
        report = self.agent.holdup_report('h1')
        row = report['members'][0]
        self.assertEqual((row['status'], row['summary']['net'], row['metrics']['trades'], row['relation']), ('completed', -880.37, 128, 'unknown'))
        self.assertEqual(row['evidence']['contamination']['status'], 'unknown')        # no header: back-oos, unknown
        status = self.agent.holdup_status('h1')
        self.assertEqual(status['holdup']['status'], 'completed')
        self.assertEqual(self.agent.research_status()['activity']['kind'], 'idle')
        queue = self.agent.research_queue()
        row = next(r for r in queue['rows'] if r['batch_id'] == 'h1')
        self.assertEqual((row['kind'], row['stage']), ('holdup', 'prove'))

    def test_owner_stop_refuses_the_start_and_settles_a_running_test(self):
        self.agent.holdup_prepare('h1', self.plan)
        (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent.holdup_start('h1', 30)
        (self.root / 'demo-agent/STOP').unlink()
        self.agent.holdup_start('h1', 6)                                       # the test is running in MT5
        running = self.process.inspect()
        activity = self.agent.research_status()['activity']
        self.assertEqual(activity['kind'], 'holdup'); self.assertIn('hold-up test', activity['headline'])
        result = self.agent.stop()
        self.assertEqual((result['batch_id'], result['owner_stop']), ('h1', True))
        self.assertTrue(result['status'].startswith('holdup_'))
        self.assertEqual(self.process.closes[-1], running)
        self.assertEqual([m['status'] for m in self.agent.holdup_status('h1')['holdup']['members']], ['cancelled'])

    def test_a_reveal_is_refused_in_v1_with_its_code(self):
        self.write_plan(heldout_reveal=dict(lock_id='a' * 64))
        with self.assertRaises(ValueError) as refused:
            self.agent.holdup_validate(self.plan)
        self.assertEqual(refused.exception.code, 'HELDOUT_REVEAL_NOT_IN_V1')
        self.assertFalse((self.root / 'holdups').exists())


if __name__ == '__main__':
    unittest.main()
