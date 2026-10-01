"""Broker-verified demo SeedFarming adapter: refusals, STOP/TAKE, exclusion, restart and validation.

The real DemoAgent guard chain, demo policy scope and SeedRunner run here; only the MT5
process, broker SDK and Studio controller handle are local fixtures.
"""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import DemoAgent, digest, read_json
from studio_research_authority import authority, operation, CURRENT_OPERATION, DEMO_AGENT_SCOPE
from studio_seed_slot import guard_active_seed
from test_demo_agent import MetaTrader
from test_studio_seed import xml_result

MONITOR = dict(pid=91, executable='terminal64.exe', created_utc='monitor')


class SeedProcess:
    """The selected terminal: the monitor first, then one tester terminal per seed member."""
    def __init__(self):
        self.current = dict(MONITOR); self.starts = []; self.closes = []

    def inspect(self):
        return copy.deepcopy(self.current)

    def close(self, identity):
        if identity != self.current:
            raise AssertionError('close for a process that is not the selected terminal')
        self.closes.append(identity); self.current = None

    def start(self, config):
        if self.current is not None:
            raise AssertionError('start while the selected terminal still runs')
        self.starts.append(str(config))
        self.current = dict(pid=100 + len(self.starts), executable='terminal64.exe', created_utc='member' + str(len(self.starts)))
        return copy.deepcopy(self.current)


class FakeController:
    """Studio handle for the policy scope; records the operation and scope it was opened under."""
    def __init__(self, test, installation):
        self.t = test
        self.install = read_json(installation)
        self.root = Path(self.install['controller_state_root'])
        self.local = Path(self.install['terminal_data_root']) / 'MQL5/Files/GOATStudio'
        self.session = read_json(self.root / 'session.json')
        self.schema, self.policy = test.schema, test.policy
        self.bridge = types.SimpleNamespace(pump=lambda: None)
        self.store = None

    def open(self, recovery=False):
        db = sqlite3.connect(self.root / 'studio.sqlite')
        self.store = types.SimpleNamespace(db=db, close=db.close)
        self.t.opened.append(dict(operation=CURRENT_OPERATION.get(), scope=copy.deepcopy(DEMO_AGENT_SCOPE.get())))
        return self

    def state(self):
        return dict(owner=self.t.owner, generation=1, queue=[])

    def runtime(self, **kwargs):
        return dict(loaded=True, owner=self.t.owner, generation=1), {}


class DemoSeedAgentTests(unittest.TestCase):
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
            run_id='session-one', demo_only=True, account=self.account, authority_kind='demo_direct',
            installation_sha256=sha(install))))
        self.binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with self.database() as db:
            db.execute('CREATE TABLE studio_queues (binding TEXT PRIMARY KEY, jobs TEXT)')
            db.execute('CREATE TABLE studio_state (binding TEXT PRIMARY KEY, owner TEXT, generation INTEGER)')
            db.execute('INSERT INTO studio_queues VALUES (?, ?)', (self.binding, '[]'))
            db.execute('INSERT INTO studio_state VALUES (?, ?, ?)', (self.binding, 'agent', 1))
        self.ui = self.data / 'MQL5/Files/GOATStudio/ui-observation.json'; self.ui.parent.mkdir(parents=True)
        (self.ui.parent / 'native-gate').mkdir()
        self.ui.write_text(json.dumps(dict(owner='agent', run_id='session-one', runtime=dict(account_demo=True,
            account_login=self.account['login'], account_server=self.account['server'], program_path=str(self.binary)))))
        (self.root / 'demo-agent').mkdir()
        (self.root / 'demo-agent/verified-build.json').write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=MONITOR)))
        self.schema = {'source_sha256': 'a' * 64, 'inputs': {'EA_Desc': dict(type='string', optimizable=False),
            'Period': dict(type='int', optimizable=True), 'Size': dict(type='double', optimizable=True)}}
        self.policy = dict(header_sha256='a' * 64, main_sha256='b' * 64, coverage='indicator_mode_gates_only', rules=[])
        self.source = base / 'source.set'
        self.source.write_bytes('; Source header\r\nEA_Desc=Original\r\nPeriod=10||10||5||20||Y\r\nSize=1.5\r\n'.encode('utf-16'))
        tester = dict(Expert=install['ea_relative_path'], Symbol='EURUSD', Period='H1', Model=4, ExecutionMode=0, Optimization=2,
                      OptimizationCriterion=6, FromDate='2026.01.01', ToDate='2026.03.01', ForwardMode=0, ForwardDate='',
                      Deposit=10000, Currency='USD', Leverage='1:100', UseLocal=1, UseRemote=0, UseCloud=0, Visual=0)
        second = copy.deepcopy(tester); second['Symbol'] = 'GBPUSD'
        self.plan = self.root.parent / 'seed-plan.json'
        self.plan.write_text(json.dumps(dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=30,
            cutoff=dict(min_fitness=0, min_trades=1),
            jobs=[dict(set_path=str(self.source), tester=tester, frame_target=2),
                  dict(set_path=str(self.source), tester=second, frame_target=2)])))
        self.owner = 'agent'; self.opened = []; self.auto = False
        self.now = time.time()
        self.process = SeedProcess(); self.mt5 = MetaTrader(self.exe, self.data)
        self.patches = [patch('demo_agent.tester_state', return_value='idle'),
                        patch('goat_studio.Controller', side_effect=lambda path: FakeController(self, path))]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        self.agent = self.new_agent()

    def database(self):
        return closing(sqlite3.connect(self.root / 'studio.sqlite', isolation_level=None))

    def new_agent(self):
        return DemoAgent(self.installation, process=self.process, mt5=self.mt5, clock=lambda: self.now, sleep=self.sleep)

    # ---- the native world: time passes, a running member finishes and its terminal exits
    def sleep(self, seconds):
        self.now += seconds
        if self.auto and self.process.current and self.process.current['created_utc'].startswith('member'):
            self.finish_member(len(self.process.starts) - 1)

    def manifest(self):
        return read_json(self.root / 'seeds/batch/manifest.json')

    def finish_member(self, index):
        member = self.manifest()['members'][index]
        path = self.common / 'GOAT/SeedFarmingXML' / (member['output_base'] + '_N2_AvgFit=1.000_Health=50.00_Zero=1_AvgTrades=5.0_Best=4.000.xml')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xml_result(member, [[1, 4, 10, 2, 2, 2, 2, 4, 1, 10, 10], [2, -2, 0, 0, 0, 0, 0, -2, 0, 0, 15]]))
        os.utime(path, (self.now, self.now))                       # the native file carries the fixture clock
        self.process.current = None

    def actions(self):
        path = self.root / 'demo-agent/actions.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def seed_files(self):
        return sorted(p.name for p in (self.root / 'seeds').rglob('*')) if (self.root / 'seeds').exists() else []

    # ---------------------------------------------------------------- validation
    def test_validation_is_nonexecuting_and_names_every_job(self):
        result = self.agent.seed_validate(self.plan)
        self.assertEqual((result['valid'], result['writes'], result['job_count']), (True, False, 2))
        self.assertEqual([job['symbol'] for job in result['jobs']], ['EURUSD', 'GBPUSD'])
        self.assertEqual(self.seed_files(), [])
        self.assertFalse((self.data / 'config/GOATStudio/Seeds').exists())
        self.assertEqual((self.process.starts, self.process.closes), ([], []))
        self.assertEqual([a['operation'] for a in self.actions()], ['seed_validate'])
        bad = json.loads(self.plan.read_text()); bad['jobs'][0]['tester']['ForwardMode'] = 1
        self.plan.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, 'ForwardMode=0'):
            self.agent.seed_validate(self.plan)

    # ---------------------------------------------------------------- refusals before any effect
    def test_real_or_mismatched_account_refuses_before_any_seed_file(self):
        self.mt5.trade_mode = 1
        with self.assertRaisesRegex(ValueError, 'demo and exact paired'):
            self.agent.seed_prepare('batch', self.plan)
        self.mt5.trade_mode = 0; self.mt5.login = 3000082755
        with self.assertRaisesRegex(ValueError, 'demo and exact paired'):
            self.agent.seed_prepare('batch', self.plan)
        self.mt5.login = 3000082754; self.mt5.server = 'Darwinex-Live'
        with self.assertRaisesRegex(ValueError, 'demo and exact paired'):
            self.agent.seed_prepare('batch', self.plan)
        self.mt5.server = 'Darwinex-Demo'; self.mt5.trade_allowed = True
        with self.assertRaisesRegex(ValueError, 'Algo Trading is on'):
            self.agent.seed_prepare('batch', self.plan)
        self.assertEqual(self.seed_files(), [])
        self.assertEqual(self.process.closes, [])

    def test_stop_and_take_control_refuse_prepare_and_start(self):
        self.agent.seed_prepare('batch', self.plan)
        (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent.seed_start('batch', 30)
        (self.root / 'demo-agent/STOP').unlink()
        inbox = self.data / 'MQL5/Files/GOATStudio/session-one/human/inbox'; inbox.mkdir(parents=True)
        (inbox / 'take.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'TAKE CONTROL'):
            self.agent.seed_start('batch', 30)
        self.assertFalse((self.root / 'demo-agent/seed-starts/batch.json').exists())
        self.assertEqual((self.process.starts, self.process.closes), ([], []))

    def test_occupied_terminal_low_disk_and_changed_build_refuse(self):
        with self.database() as db:
            db.execute('UPDATE studio_queues SET jobs=?', (json.dumps([dict(job_id='native', status='running')]),))
        with self.assertRaisesRegex(ValueError, 'ordinary native batch is active'):
            self.agent.seed_prepare('batch', self.plan)
        with self.database() as db:
            db.execute('UPDATE studio_queues SET jobs=?', ('[]',))
        (self.root / 'demo-agent/workers').mkdir()
        (self.root / 'demo-agent/workers/native.json').write_text(json.dumps(dict(pid=5, nonce='n')))
        with patch.object(DemoAgent, '_worker_alive', return_value=True):
            with self.assertRaisesRegex(ValueError, 'live demo batch driver'):
                self.agent.seed_prepare('batch', self.plan)
        with patch('demo_agent.shutil.disk_usage', return_value=types.SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError, 'less than 5 GiB'):
                self.agent.seed_prepare('batch', self.plan)
        self.binary.write_bytes(b'other-ea')
        with self.assertRaisesRegex(ValueError, 'EA hash changed'):
            self.agent.seed_prepare('batch', self.plan)
        self.assertEqual(self.seed_files(), [])

    # ---------------------------------------------------------------- the demo path
    def test_full_run_completes_inside_fresh_demo_scope_with_append_only_evidence(self):
        prepared = self.agent.seed_prepare('batch', self.plan)
        self.assertEqual(prepared['status'], 'prepared')
        self.auto = True
        result = self.agent.seed_start('batch', 60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.process.closes, [MONITOR])                  # monitor closed once, normally
        self.assertEqual(len(self.process.starts), 2)                     # one attempt per member, no retry
        self.assertTrue(all(member['attempts'] == 1 for member in result['members']))
        record = read_json(self.root / 'demo-agent/seed-starts/batch.json')
        self.assertEqual((record['account'], record['broker']['demo'], record['manifest_sha256']),
                         (self.account, True, prepared['manifest_sha256']))
        self.assertEqual([o['operation'] for o in self.opened], ['seed-prepare', 'seed-start'])
        self.assertTrue(all(o['scope']['account'] == self.account and o['scope']['job_id'] == 'batch' for o in self.opened))
        phases = [(a['operation'], a['phase']) for a in self.actions()]
        self.assertEqual(phases[:3], [('seed_prepare', 'intent'), ('seed_prepare', 'verified'), ('seed_start', 'start_recorded')])
        self.assertIn(('seed_drive', 'slice'), phases)
        self.assertTrue(guard_active_seed(self.root))                     # slot released after completion
        report = self.agent.seed_report('batch')
        self.assertEqual([row['status'] for row in report['members']], ['completed', 'completed'])

    def test_duplicate_start_refused_and_restart_resumes_only_the_original_attempt(self):
        self.agent.seed_prepare('batch', self.plan)
        first = self.agent.seed_start('batch', 6)                         # budget ends with member 1 running
        self.assertTrue(first['driver_budget_exhausted'])
        self.assertEqual(len(self.process.starts), 1)
        with self.assertRaisesRegex(ValueError, 'Seed runner owns this terminal'):
            guard_active_seed(self.root)                                  # ordinary native work stays blocked
        with self.assertRaisesRegex(ValueError, 'already started; use seed-resume'):
            self.agent.seed_start('batch', 30)
        # The tool process dies; member 1 finishes while nothing drives. MT5 is now closed.
        self.finish_member(0)
        self.agent = self.new_agent()
        self.auto = True
        self.mt5.trade_mode = 1   # a live broker cannot even be asked while MT5 is closed
        result = self.agent.seed_resume('batch', 60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.process.starts), 2)                     # member 1 was never retried
        retained = [o for o in self.opened if o['operation'] == 'seed-resume'][0]
        self.assertEqual(retained['scope']['account'], self.account)       # from the broker-verified start record
        resumed = [a for a in self.actions() if a['operation'] == 'seed_resume'][0]
        self.assertEqual((resumed['broker'], resumed['retained_start']), (None, True))

    def test_retained_resume_refuses_changed_build_account_or_missing_start(self):
        self.agent.seed_prepare('batch', self.plan)
        with self.assertRaisesRegex(ValueError, 'no native effect yet; use seed-start'):
            self.agent.seed_resume('batch', 30)
        self.agent.seed_start('batch', 6)
        self.finish_member(0)
        self.binary.write_bytes(b'swapped-ea')
        with self.assertRaisesRegex(ValueError, 'EA hash changed'):
            self.agent.seed_resume('batch', 30)
        self.binary.write_bytes(b'ea-149')
        session = read_json(self.root / 'session.json'); session['account'] = dict(login='3000082755', server='Darwinex-Demo')
        (self.root / 'session.json').write_text(json.dumps(session))
        with self.assertRaisesRegex(ValueError, 'differs from this installation or paired demo account'):
            self.new_agent().seed_resume('batch', 30)
        self.assertEqual(len(self.process.starts), 1)

    def test_stop_or_take_mid_run_closes_only_the_owned_member_and_keeps_stop(self):
        for reason, arrange in (('owner_stop', lambda: (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))),
                                ('human_take_control', lambda: self.take_control())):
            with self.subTest(reason=reason):
                self.setUp()
                self.agent.seed_prepare('batch', self.plan)
                self.agent.seed_start('batch', 6)                         # member 1 running
                running = self.process.inspect()
                arrange()
                result = self.agent.seed_resume('batch', 30)
                self.assertEqual(result['stopped_by'], reason)
                self.assertEqual(self.process.closes[-1], running)        # normal close of the exact member
                self.assertEqual(len(self.process.starts), 1)             # nothing new launched
                status = self.agent.seed_status('batch')['seed']
                self.assertEqual([m['status'] for m in status['members']], ['cancelled', 'cancelled'])
                if reason == 'owner_stop':
                    self.assertTrue((self.root / 'demo-agent/STOP').exists())   # STOP is never cleared by the tool

    def take_control(self):
        inbox = self.data / 'MQL5/Files/GOATStudio/session-one/human/inbox'; inbox.mkdir(parents=True, exist_ok=True)
        (inbox / 'take.json').write_text('{}')

    def test_owner_stop_command_settles_an_undriven_seed_run(self):
        self.agent.seed_prepare('batch', self.plan)
        self.agent.seed_start('batch', 6)
        running = self.process.inspect()
        result = self.agent.stop()
        self.assertEqual((result['batch_id'], result['owner_stop']), ('batch', True))
        self.assertEqual(self.process.closes[-1], running)
        with self.assertRaisesRegex(ValueError, 'Active seed run must reach a verified terminal state'):
            self.process.current = dict(MONITOR)                          # broker reachable again, seed still unsettled
            self.agent.clear_stop()

    def test_prepared_batch_can_be_observed_cancelled_and_reported_without_a_start_record(self):
        self.agent.seed_prepare('batch', self.plan)
        status = self.agent.seed_status('batch')
        self.assertEqual((status['seed']['status'], status['broker']['demo']), ('prepared', True))
        self.assertEqual(self.agent.seed_report('batch')['status'], 'prepared')
        with self.assertRaisesRegex(ValueError, 'no native effect yet; use seed-start'):
            self.agent.seed_resume('batch', 30)
        cancelled = self.agent.seed_cancel('batch')
        self.assertEqual((cancelled['status'], cancelled['native_started']), ('stopped', False))
        self.assertEqual((self.process.starts, self.process.closes), ([], []))   # ledger only, no native effect
        self.assertFalse((self.root / 'demo-agent/seed-starts/batch.json').exists())

    def test_without_a_start_record_closed_mt5_or_native_effects_refuse(self):
        self.agent.seed_prepare('batch', self.plan)
        self.process.current = None                                               # MT5 closed: no fresh check possible
        with self.assertRaisesRegex(ValueError, 'open the selected MT5 for a fresh demo check'):
            self.agent.seed_status('batch')
        self.process.current = dict(MONITOR)
        state_path = self.root / 'seeds/batch/state.json'
        state = read_json(state_path); state['status'] = 'active'                 # effects without a start record
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'native effects but no broker-verified demo start record'):
            self.agent.seed_status('batch')

    # ---------------------------------------------------------------- default deny
    def test_raw_studio_demo_direct_seed_mutation_is_still_refused(self):
        with self.database() as db:
            for name in ('seed-prepare', 'seed-start', 'seed-resume', 'seed-cancel'):
                with operation(name):
                    with self.assertRaisesRegex(ValueError, 'Demo mutation requires the broker-verified agent tool'):
                        authority(db, self.binding, dict(owner='agent', generation=1))


if __name__ == '__main__':
    unittest.main()
