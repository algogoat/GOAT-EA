"""Boundary tests for the direct demo-only MT5 agent lane."""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import DemoAgent, digest, read_json
from goat_studio import Controller
from studio_command_store import StudioStore
from studio_research_authority import authority, command, demo_agent_scope, operation


class Process:
    identity = dict(pid=91, executable='terminal64.exe', created_utc='2026-09-28T00:00:00Z')

    def __init__(self):
        self.closed = False
        self.on_start = None

    def inspect(self):
        return None if self.closed else self.identity

    def close(self, identity):
        self.closed = True

    def start(self, config):
        self.closed = False
        if self.on_start:
            self.on_start()
        return self.identity


class MetaTrader:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, exe, data):
        self.login = 3000082754
        self.trade_mode = 0
        self.server = 'Darwinex-Demo'
        self.trade_allowed = False
        self.exe = exe
        self.data = data

    def initialize(self, *args, **kwargs):
        return True

    def terminal_info(self):
        return types.SimpleNamespace(path=str(self.exe.parent), data_path=str(self.data),
                                     connected=True, trade_allowed=self.trade_allowed, build=6230)

    def account_info(self):
        return types.SimpleNamespace(login=self.login, server=self.server,
                                     trade_mode=self.trade_mode)

    def shutdown(self):
        pass

    def positions_get(self):
        return ()

    def orders_get(self):
        return ()


class DemoAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / 'data'; self.data.mkdir()
        self.common = self.base / 'common'; self.common.mkdir()
        self.root = self.base / 'state'; self.root.mkdir()
        self.exe = self.base / 'bin' / 'terminal64.exe'; self.exe.parent.mkdir()
        self.exe.write_bytes(b'fake')
        self.binary = self.data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'old-ea')
        self.installation = self.root / 'installation.json'
        self.installation.write_text(json.dumps(dict(schema_version=1,
             controller_version='1.49-beta.1', ea_version='1.49',
             ea_sha256=digest(self.binary), controller_state_root=str(self.root),
             terminal_data_root=str(self.data), common_files_root=str(self.common),
             terminal_executable=str(self.exe), ea_relative_path=r'GOAT-EA\GOAT V1.49.ex5')))
        (self.root / 'session.json').write_text(json.dumps(dict(directory_id='session-one',
             terminal_id='terminal-one', run_id='session-one', demo_only=True,
             account=dict(login='3000082754', server='Darwinex-Demo'))))
        (self.root / 'monitor-profile.json').write_text(json.dumps(dict(profile_name='GOAT-Studio-test')))
        self.ui = self.data / 'MQL5/Files/GOATStudio/ui-observation.json'
        self.ui.parent.mkdir(parents=True)
        self.ui.write_text(json.dumps(dict(owner='agent', run_id='session-one',
            runtime=dict(account_demo=True, account_login='3000082754',
                         account_server='Darwinex-Demo', program_path=str(self.binary)))))
        self.process = Process()
        self.mt5 = MetaTrader(self.exe, self.data)
        self.agent = DemoAgent(self.installation, process=self.process, mt5=self.mt5)

    def test_broker_reported_demo_and_exact_allowlist_required(self):
        with patch('demo_agent.tester_state', return_value='idle'):
            self.assertTrue(self.agent._broker()['demo'])
            self.mt5.trade_mode = 1
            with self.assertRaisesRegex(ValueError, 'demo and allowlisted'):
                self.agent._broker()
            self.mt5.trade_mode = 0
            self.mt5.login = 3000082755
            with self.assertRaisesRegex(ValueError, 'demo and allowlisted'):
                self.agent._broker()
            self.mt5.login = 3000082754
            self.mt5.trade_allowed = True
            with self.assertRaisesRegex(ValueError, 'Algo Trading is on'):
                self.agent._broker()

    def test_receipt_path_is_validated_before_binary_target_derivation(self):
        receipt = read_json(self.installation)
        receipt['ea_relative_path'] = r'..\..\other.ex5'
        self.installation.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'relative to MQL5/Experts'):
            DemoAgent(self.installation, process=self.process, mt5=self.mt5)

    def test_preflight_distinguishes_safe_install_from_batch_readiness(self):
        with patch('demo_agent.tester_state', return_value='idle'):
            before = self.agent.preflight()
            self.assertTrue(before['ready_for_install'])
            self.assertFalse(before['ready_for_batch'])
            self.agent._adopt_installed_binary(digest(self.binary))
            self.assertFalse(self.agent.preflight()['ready_for_batch'])
            (self.agent.state_root / 'verified-build.json').write_text(json.dumps(dict(
                ea_sha256=digest(self.binary), process=self.process.inspect())))
            self.assertTrue(self.agent.preflight()['ready_for_batch'])

    def test_low_disk_and_terminal_lock_refuse_mutation(self):
        with patch('demo_agent.shutil.disk_usage', return_value=types.SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError, 'less than 5 GiB'):
                self.agent._space()
        with self.agent._exclusive():
            with self.assertRaisesRegex(ValueError, 'Another demo agent operation'):
                with self.agent._exclusive():
                    pass

    def test_stop_and_human_take_preempt_mutation(self):
        self.agent._owner_clear()
        inbox = self.agent.local / 'session-one/human/inbox'
        inbox.mkdir(parents=True)
        (inbox / 'take.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'TAKE CONTROL'):
            self.agent._owner_clear()
        self.assertEqual(self.agent._stop_requested(), 'human_take_control')
        (inbox / 'take.json').unlink()
        with patch.object(self.agent, '_native_active_batches', return_value=[]):
            self.agent.stop()
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent._owner_clear()
        self.assertEqual(self.agent._stop_requested(), 'owner_stop')
        self.assertEqual(read_json(self.agent.state_root / 'run.json') if
                         (self.agent.state_root / 'run.json').exists() else None, None)

    def test_agent_can_clear_only_its_own_verified_stop(self):
        with patch.object(self.agent, '_native_active_batches', return_value=[]):
            self.agent.stop()
        with patch.object(self.agent, '_native_active_batches', return_value=[]), patch(
                'demo_agent.tester_state', return_value='idle'):
            self.assertEqual(self.agent.clear_stop()['phase'], 'verified')
        self.assertFalse((self.agent.state_root / 'STOP').exists())
        (self.agent.state_root / 'STOP').write_text('human-owned')
        with self.assertRaisesRegex(ValueError, 'not written by this demo tool'):
            self.agent.clear_stop()

    def test_stop_reattaches_when_no_driver_process_holds_terminal(self):
        journal = self.root / 'batch-drivers/batch.json'
        journal.parent.mkdir()
        journal.write_text(json.dumps(dict(stopped=False, status='observing', attempt_id='a'*64)))

        @contextmanager
        def studio(*args, **kwargs):
            yield object(), dict(login='3000082754')

        with patch.object(self.agent, '_native_active_batches', return_value=['batch']), patch.object(
                self.agent, '_studio', side_effect=studio), patch(
                'studio_batch_driver.run', return_value=dict(stopped=True,
                    status='cancelled', attempt_id='a'*64)) as resume:
            result = self.agent.stop()
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(resume.call_args.kwargs['resume'], True)
        self.assertTrue((self.agent.state_root / 'STOP').is_file())

    def test_batch_start_spawns_detached_worker_and_returns_retained_status(self):
        controller = types.SimpleNamespace(job=lambda batch_id: dict(status='pending'))

        @contextmanager
        def studio(*args, **kwargs):
            yield controller, dict(login='3000082754')

        journal = self.root / 'batch-drivers/batch.json'

        def spawn(*argv, **kwargs):
            journal.parent.mkdir(exist_ok=True)
            journal.write_text(json.dumps(dict(status='observing', attempt_id='a'*64)))
            return types.SimpleNamespace(pid=123, poll=lambda: None)

        with patch.object(self.agent, '_studio', side_effect=studio), patch(
                'demo_agent.subprocess.Popen', side_effect=spawn) as popen:
            result = self.agent.run_batch('batch', 172800)
        self.assertEqual(result['status'], 'driver_journal_recorded')
        self.assertEqual(result['driver_status'], 'observing')
        self.assertTrue(result['native_running_unverified'])
        self.assertIn('_drive-batch', popen.call_args.args[0])
        self.assertNotEqual(popen.call_args.kwargs['creationflags'], 0)

    def test_resume_spawns_worker_for_existing_attempt_without_new_budget(self):
        journal = self.root / 'batch-drivers/batch.json'
        journal.parent.mkdir()
        journal.write_text(json.dumps(dict(status='observing', attempt_id='a'*64)))

        @contextmanager
        def studio(*args, **kwargs):
            yield object(), dict(login='3000082754')

        with patch.object(self.agent, '_studio', side_effect=studio), patch(
                'studio_batch_driver.status', return_value=dict(stopped=False)), patch(
                'demo_agent.subprocess.Popen', return_value=types.SimpleNamespace(
                    pid=124, poll=lambda: None)) as popen:
            result = self.agent.resume_batch('batch')
        argv = popen.call_args.args[0]
        self.assertIn('_drive-batch', argv)
        self.assertNotIn('--max-seconds', argv)
        self.assertTrue(read_json(self.agent.state_root / 'workers/batch.json')['resume'])
        self.assertEqual(result['driver_status'], 'observing')

    def test_install_refuses_unsafe_monitor_before_close(self):
        candidate = self.base / 'candidate.ex5'; candidate.write_bytes(b'new-ea')
        monitor = self.base / 'monitor.ini'
        monitor.write_text('[Experts]\nEnabled=1\nAllowLiveTrading=1\n[StartUp]\nExpert=GOAT-EA\\GOAT V1.49.ex5\n')
        with self.assertRaisesRegex(ValueError, 'Algo Trading off'):
            self.agent.install_build(candidate, digest(candidate), monitor)
        monitor.write_text('[Charts]\nProfileLast=GOAT-Studio-test\n[Experts]\nEnabled=0\n'
                           'AllowLiveTrading=0\n[StartUp]\nExpert=GOAT-EA\\GOAT V1.49.ex5\n'
                           'ExpertParameters=GOAT Studio Agent.set\nPeriod=M1\n'
                           '[Common]\nLogin=another-account\n')
        with self.assertRaisesRegex(ValueError, 'Algo Trading off'):
            self.agent.install_build(candidate, digest(candidate), monitor)
        self.assertFalse(self.process.closed)
        self.assertEqual(self.binary.read_bytes(), b'old-ea')

    def test_install_reads_back_restarted_demo_before_batch_ready(self):
        candidate = self.base / 'candidate.ex5'; candidate.write_bytes(b'new-ea')
        old_sha = digest(self.binary)
        (self.agent.local / 'active.json').write_text(json.dumps(dict(
            directory_id='session-one', terminal_id='terminal-one', run_id='session-one',
            terminal_data_path=str(self.data))))
        store = StudioStore(self.root / 'studio.sqlite')
        try:
            initial = store.bind('terminal-one', 'session-one')
            store.submit(dict(schema_version=1, request_id='human-give-for-install',
                terminal_id='terminal-one', run_id='session-one',
                expected_revision=initial['revision'], generation=initial['generation'],
                command='control.grant_agent', payload={}), actor='human')
        finally:
            store.close()
        monitor = self.base / 'monitor.ini'
        monitor.write_text('[Charts]\nProfileLast=GOAT-Studio-test\n[Experts]\nEnabled=0\n'
                           'AllowLiveTrading=0\n[StartUp]\nExpert=GOAT-EA\\GOAT V1.49.ex5\n'
                           'ExpertParameters=GOAT Studio Agent.set\nPeriod=M1\n')
        prior_mtime = self.ui.stat().st_mtime_ns
        readback_tick = [0]

        def ea_readback():
            readback_tick[0] += 1
            self.ui.write_text(json.dumps(dict(owner='agent', loaded=True,
                runtime=dict(account_demo=True, account_login='3000082754',
                             account_server='Darwinex-Demo', program_path=str(self.binary)))))
            observed = prior_mtime + readback_tick[0] * 1_000_000_000
            os.utime(self.ui, ns=(observed, observed))

        self.process.on_start = ea_readback
        with patch('demo_agent.tester_state', return_value='idle'):
            result = self.agent.install_build(candidate, digest(candidate), monitor)
            self.assertTrue(result['installed'])
            self.assertTrue(self.agent.preflight()['ready_for_batch'])
            self.assertTrue(self.agent.install_build(candidate, digest(candidate), monitor)['already_installed'])
            self.process.closed = True  # MT5 exits after the verified swap.
            recovered = self.agent.install_build(candidate, digest(candidate), monitor)
            self.assertTrue(recovered['recovered'])
            self.assertTrue(self.agent.preflight()['ready_for_batch'])
            self.process.closed = True
            self.assertEqual(self.agent.launch_terminal(monitor)['sha256'], digest(candidate))
        self.assertEqual(self.binary.read_bytes(), b'new-ea')
        self.assertEqual(read_json(self.installation)['ea_sha256'], digest(candidate))
        self.assertEqual((self.agent.state_root / 'backups' / (old_sha + '.ex5')).read_bytes(), b'old-ea')

    def test_local_install_identity_and_scoped_demo_authority(self):
        self.binary.write_bytes(b'new-ea')
        self.agent._adopt_installed_binary(digest(self.binary))
        receipt = read_json(self.installation)
        session = read_json(self.root / 'session.json')
        self.assertEqual(receipt['ea_sha256'], digest(self.binary))
        self.assertEqual(session['authority_kind'], 'demo_direct')
        self.assertEqual(session['installation_sha256'], sha(self.agent.install))
        self.assertEqual(self.agent._broker(idle=False)['login'], '3000082754')
        db = sqlite3.connect(self.root / 'studio.sqlite')
        self.addCleanup(db.close)
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with operation('prepare-batch'), demo_agent_scope(
                root=self.root, installation_sha256=sha(self.agent.install),
                account=session['account']):
            self.assertIsNone(authority(db, binding, dict(owner='agent', generation=2)))
            with self.assertRaisesRegex(ValueError, 'TAKE CONTROL'):
                authority(db, binding, dict(owner='human', generation=2))
        self.assertEqual(list((self.agent.state_root / 'backups').glob('installation-*.json')).__len__(), 1)

    def test_demo_scope_rejects_unrelated_inbox_commands(self):
        self.agent._adopt_installed_binary(digest(self.binary))
        session = read_json(self.root / 'session.json')
        db = sqlite3.connect(self.root / 'studio.sqlite')
        self.addCleanup(db.close)
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        state = dict(owner='agent', generation=2)
        with operation('prepare-batch'), demo_agent_scope(
                root=self.root, installation_sha256=sha(self.agent.install),
                account=session['account'], job_id='chosen'):
            exact = dict(command='queue.enqueue_batch', request_id='chosen-batch',
                         payload=dict(job_id='chosen'))
            self.assertIsNone(command(db, binding, state, exact, actor='agent'))
            with self.assertRaisesRegex(ValueError, 'exact Studio command'):
                command(db, binding, state, dict(command='draft.replace_strategy',
                        request_id='stale-draft', payload={}), actor='agent')
            with self.assertRaisesRegex(ValueError, 'exact Studio command'):
                command(db, binding, state, dict(command='queue.enqueue_batch',
                        request_id='other-batch', payload=dict(job_id='other')), actor='agent')

    def test_existing_studio_rpc_is_reused_only_inside_fresh_demo_scope(self):
        original_session = read_json(self.root / 'session.json')
        original_session['authority_kind'] = 'native_human_control'
        (self.root / 'session.json').write_text(json.dumps(original_session))
        store = StudioStore(self.root / 'studio.sqlite')
        try:
            initial = store.bind('terminal-one', 'session-one')
            request = dict(schema_version=1, request_id='fixture-human-give',
                           terminal_id='terminal-one', run_id='session-one',
                           expected_revision=initial['revision'], generation=initial['generation'],
                           command='control.grant_agent', payload={})
            store.submit(request, actor='human')
        finally:
            store.close()
        self.binary.write_bytes(b'new-ea')
        self.agent._adopt_installed_binary(digest(self.binary))
        active = self.agent.local / 'active.json'
        active.write_text(json.dumps(dict(directory_id='session-one', terminal_id='terminal-one',
                                          run_id='session-one', terminal_data_path=str(self.data))))
        session = read_json(self.root / 'session.json')
        with operation('state'), demo_agent_scope(root=self.root,
                 installation_sha256=sha(self.agent.install), account=session['account']):
            controller = Controller(self.installation).open()
            try:
                self.assertEqual(controller.state()['owner'], 'agent')
            finally:
                controller.store.close()
        with operation('state'):
            controller = Controller(self.installation).open()
            try:
                self.assertEqual(controller.state()['owner'], 'agent')
            finally:
                controller.store.close()
        db = sqlite3.connect(self.root / 'studio.sqlite')
        self.addCleanup(db.close)
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with operation('serve'), self.assertRaisesRegex(ValueError, 'broker-verified tool'):
            command(db, binding, dict(owner='agent'), dict(command='draft.replace_strategy',
                    request_id='stale-agent-edit', payload={}), actor='agent')
        with operation('serve'):
            self.assertIsNone(command(db, binding, dict(owner='human'),
                    dict(command='control.grant_agent'), actor='human'))
        with operation('state'), self.assertRaisesRegex(ValueError, 'binding changed'):
            authority(db, packed(dict(terminal_id='other', run_id='session-one')),
                      dict(owner='agent'))
        with operation('serve'), self.assertRaisesRegex(ValueError, 'binding changed'):
            command(db, packed(dict(terminal_id='other', run_id='session-one')),
                    dict(owner='human'), dict(command='control.grant_agent'), actor='human')

    def test_repeated_batch_preparation_reads_count_from_existing_queue(self):
        plan = self.base / 'plan.json'; plan.write_text('{}')
        controller = types.SimpleNamespace(job=lambda batch_id: dict(
            status='pending', configuration=dict(batch_members=[{}, {}]),
            configuration_sha256='frozen'))

        @contextmanager
        def studio(*args, **kwargs):
            yield controller, dict(login='3000082754')

        with patch.object(self.agent, '_studio', side_effect=studio), patch(
                'studio_batch.prepare_batch', return_value=dict(
                    batch_id='existing', reused=True, native_started=False)):
            result = self.agent.prepare_batch('existing', plan)
        self.assertEqual(result['member_count'], 2)
        self.assertTrue(result['reused'])



if __name__ == '__main__':
    unittest.main()
