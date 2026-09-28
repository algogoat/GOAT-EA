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
from studio_research_authority import authority, demo_agent_scope, operation


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
        self.ui.write_text(json.dumps(dict(owner='agent', run_id='session-one')))
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

    def test_stop_and_human_take_preempt_mutation(self):
        self.agent._owner_clear()
        inbox = self.agent.local / 'session-one/human/inbox'
        inbox.mkdir(parents=True)
        (inbox / 'take.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'TAKE CONTROL'):
            self.agent._owner_clear()
        self.assertEqual(self.agent._stop_requested(), 'human_take_control')
        (inbox / 'take.json').unlink()
        self.agent.stop()
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent._owner_clear()
        self.assertEqual(self.agent._stop_requested(), 'owner_stop')
        self.assertEqual(read_json(self.agent.state_root / 'run.json') if
                         (self.agent.state_root / 'run.json').exists() else None, None)

    def test_install_refuses_unsafe_monitor_before_close(self):
        candidate = self.base / 'candidate.ex5'; candidate.write_bytes(b'new-ea')
        monitor = self.base / 'monitor.ini'
        monitor.write_text('[Experts]\nEnabled=1\nAllowLiveTrading=1\n[StartUp]\nExpert=GOAT-EA\\GOAT V1.49.ex5\n')
        with self.assertRaisesRegex(ValueError, 'Algo Trading off'):
            self.agent.install_build(candidate, digest(candidate), monitor)
        self.assertFalse(self.process.closed)
        self.assertEqual(self.binary.read_bytes(), b'old-ea')

    def test_install_reads_back_restarted_demo_before_batch_ready(self):
        candidate = self.base / 'candidate.ex5'; candidate.write_bytes(b'new-ea')
        old_sha = digest(self.binary)
        monitor = self.base / 'monitor.ini'
        monitor.write_text('[Charts]\nProfileLast=GOAT-Studio-test\n[Experts]\nEnabled=0\n'
                           'AllowLiveTrading=0\n[StartUp]\nExpert=GOAT-EA\\GOAT V1.49.ex5\n')
        prior_mtime = self.ui.stat().st_mtime_ns

        def ea_readback():
            self.ui.write_text(json.dumps(dict(owner='agent', loaded=True,
                runtime=dict(account_demo=True, program_path=str(self.binary)))))
            os.utime(self.ui, ns=(prior_mtime + 1_000_000_000,
                                  prior_mtime + 1_000_000_000))

        self.process.on_start = ea_readback
        with patch('demo_agent.tester_state', return_value='idle'):
            result = self.agent.install_build(candidate, digest(candidate), monitor)
            self.assertTrue(result['installed'])
            self.assertTrue(self.agent.preflight()['ready_for_batch'])
            self.assertTrue(self.agent.install_build(candidate, digest(candidate), monitor)['already_installed'])
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
                with self.assertRaises(ValueError):
                    controller.state()
            finally:
                controller.store.close()

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
