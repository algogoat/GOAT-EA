"""Agent pairing-code readback, inert close-terminal and demo dashboard deploy. Fixture-only.

A fake EA thread answers the real Common Files mailboxes with the exact receipt shapes of
GOATSetupControl.mqh and GOATPortfolioSetupControl.mqh. No MT5 terminal is touched.
"""
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_agent_mailbox as mailbox
import studio_agent_setup as agent_setup
import studio_demo_deploy as deploy
from studio_native_gate import exclusive_gate
import test_goat_studio as fixtures

BUILD = 'V1.48-TEST-BUILD-01'


class FakeProcess:
    def __init__(self, running=True):
        self.identity = dict(pid=55, executable='terminal64.exe', created_utc='2026-10-02T00:00:00+00:00') if running else None
        self.closed = []

    def inspect(self, timeout=20):
        return self.identity

    def close(self, identity):
        if identity != self.identity:
            raise ValueError('changed')
        self.closed.append(identity)
        self.identity = None


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, controller, *, trade_mode=0, algo=False, positions=0, orders=0, login='123456', connected=True, account=None):
        self.c, self.trade_mode, self.algo, self.positions, self.orders, self.login, self.connected = controller, trade_mode, algo, positions, orders, login, connected
        self.account = dict(account or {})

    def initialize(self, path, timeout=0): return True
    def shutdown(self): pass
    def terminal_info(self):
        return SimpleNamespace(path=str(Path(self.c.install['terminal_executable']).parent), data_path=self.c.install['terminal_data_root'],
                               connected=self.connected, trade_allowed=self.algo, build=5200)
    def account_info(self):
        return SimpleNamespace(login=int(self.login), server='Customer-Demo', trade_mode=self.trade_mode, **self.account)
    def positions_get(self): return [object()] * self.positions
    def orders_get(self): return [object()] * self.orders


class FakeEA(threading.Thread):
    """Answers the two mailboxes the way the EA does, including its demo/inert gates."""

    def __init__(self, controller, *, demo=True, algo=False, positions=0, pairing='available', setup_host=True,
                 settings_match=True, child_trade=1, attach_failures=0, batch=False):
        super().__init__(daemon=True)
        self.c, self.demo, self.algo, self.positions = controller, demo, algo, positions
        self.pairing, self.setup_host, self.settings_match, self.child_trade = pairing, setup_host, settings_match, child_trade
        self.attach_failures = attach_failures
        self.batch = batch  # A Studio monitor mid-batch refuses shutdown (GoatSetupResearchIdle).
        self.stop_event = threading.Event()
        self.rows = []
        self.command = 0
        self.shutdowns = 0
        self.gate_refusals = 0
        self.code = 'ABCD-EF23'
        self.on_shutdown = lambda: None
        self.audit_registration = None  # Audit a different registration than the request names.
        self.hold_deploy_next = False  # B41.1: the attach is still settling, no final receipt yet.

    def stop(self):
        self.stop_event.set(); self.join(5)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.serve_setup(); self.serve_portfolio()
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.02)

    def base(self, request_id, result, ident):
        return dict(schema=1, id=request_id, result=result, account=ident['account'], server=ident['server'],
                    directory=ident['directory'], buildId=ident['buildId'], observedAtUtc=int(time.time()),
                    connected=True, tradingAllowed=self.algo, activationOnly=self.pairing == 'available',
                    positions=self.positions, orders=0, charts=1)

    def serve_setup(self):
        root = mailbox.setup_root(self.c)
        request = root / 'request.json'
        if not self.setup_host or not self.demo or not request.exists() or not (root / 'registration.json').exists():
            return
        envelope = json.loads(request.read_text())
        receipt = root / (envelope['id'] + '.json')
        if receipt.exists():
            return
        inert = not self.algo and self.positions == 0
        action = envelope['action']
        ident = dict(account=envelope['account'], server=envelope['server'], directory=envelope['directory'], buildId=envelope['buildId'])
        if envelope['expiresAtUtc'] < time.time():
            body = self.base(envelope['id'], 'rejected_envelope', ident)
        elif action == 'shutdown':
            # Like the #112 Studio monitor, the EA holds GOATStudio\native-gate\launch.lock
            # (no sharing) from its idle check through TerminalClose; if the lock cannot be
            # opened it refuses instead of closing.
            gate = self.c.local / 'native-gate'; gate.mkdir(parents=True, exist_ok=True)
            try:
                with exclusive_gate(gate):
                    result = 'shutdown_requested' if inert and not self.batch else 'rejected_not_inert'
            except OSError:
                result = 'rejected_not_inert'
                self.gate_refusals += 1
            body = self.base(envelope['id'], result, ident)
        elif action == 'pairing':
            if not inert:
                body = self.base(envelope['id'], 'rejected_not_inert', ident)
            elif self.pairing != 'available':
                body = self.base(envelope['id'], 'pairing_unavailable', ident)
            else:
                body = self.base(envelope['id'], 'pairing_available', ident)
                now = body['observedAtUtc']
                body.update(userCode=self.code, activationId='a' * 32, responseExpiresAtUtc=now + 30, pairingExpiresAtMs=(now + 600) * 1000)
        else:
            body = self.base(envelope['id'], 'observed', ident)
        mailbox.atomic(receipt, body)
        if body['result'] == 'shutdown_requested':
            self.shutdowns += 1
            self.on_shutdown()  # TerminalClose(0): the selected terminal exits normally

    def serve_portfolio(self):
        root = mailbox.portfolio_root(self.c)
        request, registration = root / 'request.json', root / 'registration.json'
        if not self.demo or not request.exists() or not registration.exists():
            return
        raw = registration.read_bytes(); reg = json.loads(raw)
        envelope = json.loads(request.read_text())
        receipt = root / (envelope['id'] + '.json')
        if receipt.exists() or envelope['registrationSha256'] != hashlib.sha256(raw).hexdigest():
            return
        if envelope['action'] == 'deploy_next' and self.hold_deploy_next:
            return
        if not self.rows:
            self.rows = [dict(cid=0, magic=0, ack=0) for _ in reg['members']]
        inert = not self.algo and self.positions == 0
        action, result = envelope['action'], 'observed'
        if action != 'status' and not inert:
            result = 'rejected_not_inert'
        elif action == 'deploy_next':
            pending = [i for i, row in enumerate(self.rows) if row['cid'] == 0]
            if not pending:
                result = 'all_attached'
            elif self.attach_failures:
                self.attach_failures -= 1; result = 'child_attach_failed'
            else:
                self.rows[pending[0]].update(cid=1000 + pending[0], magic=5000 + pending[0]); result = 'child_attached'
        elif action == 'apply_policy':
            self.command += 1
            for row in self.rows:
                row['ack'] = self.command
            result = 'policy_dispatched'
        rows = [dict(index=i, symbol=m['symbol'], chartId=self.rows[i]['cid'], magic=self.rows[i]['magic'], linkedFresh=self.rows[i]['cid'] > 0,
                     settingsMatch=action == 'audit' and self.rows[i]['cid'] > 0 and self.settings_match,
                     exposureMode=reg['exposureMode'], ackId=self.rows[i]['ack'], ackStatus=1 if self.rows[i]['ack'] else 0,
                     AI_MODE=1, AI_PROTOCOL=2, AI_THRESHOLD=reg['aiThreshold'], AI_SCOPE=0, AI_VERIFIED=0, AI_AVAILABLE=0, AI_AT=None,
                     EA_TRADE_ALLOWED=self.child_trade if self.rows[i]['cid'] > 0 else None) for i, m in enumerate(reg['members'])]
        audited = self.audit_registration if action == 'audit' and self.audit_registration else envelope['registrationSha256']
        body = dict(schema=1, id=envelope['id'], action=action, registrationSha256=audited, result=result,
                    account=reg['account'], server=reg['server'], directory=reg['directory'], buildId=reg['buildId'],
                    observedAtUtc=int(time.time()), connected=True, tradingAllowed=self.algo, positions=self.positions, orders=0,
                    aiMode=reg['aiMode'], aiThreshold=reg['aiThreshold'], aiProtocol=reg['aiProtocol'], commandId=self.command,
                    commandPending=False, brokerTime=int(time.time()), rows=rows)
        mailbox.atomic(receipt, body)


def member(index, symbol='EURUSD', content=None, name=None):
    raw = content if content is not None else ('EA_Desc=Trend ' + str(index) + '\r\nLots=0.1\r\n').encode('utf-16')
    return dict(index=index, fileName=name or f'GOAT V1.48 {symbol},M15_Trds{index}.set', symbol=symbol, strategy='Trend ' + str(index),
                sha256=hashlib.sha256(raw).hexdigest(), contentBase64=base64.b64encode(raw).decode())


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound()
        self.data = self.fixture.data
        (self.data / 'origin.txt').write_text(str(self.fixture.bin.parent))
        (self.data / 'config').mkdir()
        (self.data / 'config/common.ini').write_text('[Common]\nLogin=123456\nServer=Customer-Demo\n[Experts]\nEnabled=0\n')
        self.process = FakeProcess()
        patcher = patch('studio_seed_process.WindowsSeedProcess', return_value=self.process)
        patcher.start(); self.addCleanup(patcher.stop)
        self.idle = patch('studio_monitor_probe.inspect_idle_demo', side_effect=lambda controller: dict(process=self.process.inspect(), demo=True,
                                                                                                    algo_trading=False, positions=0, orders=0, tester_state='idle'))
        self.idle.start(); self.addCleanup(self.idle.stop)
        self.ident = mailbox.identity(self.c, self.c.session, BUILD)
        self.ea = None

    def tearDown(self):
        if self.ea:
            self.ea.stop()

    def start_ea(self, **options):
        self.ea = FakeEA(self.c, **options)
        self.ea.on_shutdown = lambda: setattr(self.process, 'identity', None)
        self.ea.start()
        return self.ea

    # ---------------------------------------------------------------- pairing

    def test_pairing_code_reads_and_consumes_the_native_challenge(self):
        self.start_ea()
        result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual(result['status'], 'pairing_available')
        self.assertEqual((result['userCode'], result['accountLast4'], result['buildId']), ('ABCD-EF23', '3456', BUILD))
        self.assertEqual(result['accountFacts'], dict(source='mt5_broker_readback', login='123456', server='Customer-Demo',
                                                      demo=True, savedLoginMatches=True), 'login and server come from MT5, cross-checked with common.ini')
        registration = json.loads((mailbox.setup_root(self.c) / 'registration.json').read_text())
        self.assertEqual(registration['schema'], 2); self.assertTrue(registration['allowPairingRead'])
        self.assertLessEqual(registration['expiresAtUtc'], time.time() + 900, 'pairing registration is at most 15 minutes')
        stored = json.loads((mailbox.setup_root(self.c) / (result['receiptId'] + '.json')).read_text())
        self.assertEqual(stored['result'], 'pairing_consumed'); self.assertNotIn('userCode', stored, 'the code never stays on disk')

    def test_pairing_without_pending_code_or_host_or_terminal(self):
        self.start_ea(pairing='none')
        self.assertEqual(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['status'], 'no_pending_pairing')
        self.ea.stop(); self.ea = None
        # A Studio monitor chart (older EA build) does not host the mailbox.
        with patch.object(mailbox, 'setup_request', return_value=dict(id='b' * 32, result='receipt_timeout')), \
             patch.object(agent_setup, 'setup_request', return_value=dict(id='b' * 32, result='receipt_timeout')):
            self.assertEqual(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['status'], 'no_native_answer')
        self.process.identity = None
        self.assertEqual(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['status'], 'terminal_stopped')

    def test_pairing_refuses_algo_on_protected_accounts_and_bad_build(self):
        self.start_ea(algo=True)
        with self.assertRaisesRegex(ValueError, 'Algo Trading off'):
            agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        with self.assertRaisesRegex(ValueError, 'build ID'):
            agent_setup.pairing_code(self.c, 'x', mt5=FakeMT5(self.c))
        self.c.session['account']['login'] = '3000109427'
        with patch('studio_agent_setup.session_state', return_value=(self.c.session, {})):
            with self.assertRaisesRegex(ValueError, 'running GOAT experiment'):
                agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))

    def test_pairing_proves_demo_from_the_broker_before_any_request(self):
        ea = self.start_ea()
        for mt5, message in ((FakeMT5(self.c, trade_mode=2), 'real-money'), (FakeMT5(self.c, login='654321'), 'different account')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                agent_setup.pairing_code(self.c, BUILD, mt5=mt5)
        self.assertFalse((mailbox.setup_root(self.c) / 'registration.json').exists(), 'no registration or request on a non-demo account')
        result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['demo'], result['server']), ('pairing_available', True, 'Customer-Demo'))

    def activation_status(self, reason, account='123456', token=None):
        folder = Path(self.c.install['common_files_root']) / 'GOAT'; folder.mkdir(parents=True, exist_ok=True)
        name = token or Path(self.c.install['terminal_data_root']).name
        (folder / ('activation-status-' + name + '.json')).write_text(json.dumps(dict(
            accountId=account, buildId=BUILD, reason=reason, httpStatus=201, nativeError=0, retrySeconds=5, observedAtUtc=int(time.time()))))

    def test_pairing_reads_a_per_login_activation_awaiting_approval(self):
        # SM32/EX33: the status file is keyed by the data-folder token and names the login;
        # it never carries the code, which only the mailbox receipt returns.
        self.activation_status('awaiting_approval')
        self.start_ea()
        result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['activationReason'], result['userCode']), ('pairing_available', 'awaiting_approval', 'ABCD-EF23'))
        self.ea.stop(); self.ea = None
        with patch.object(agent_setup, 'setup_request', return_value=dict(id='b' * 32, result='receipt_timeout')):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['activationReason']), ('no_native_answer', 'awaiting_approval'))
        self.assertIn('waiting for approval', result['next_action']); self.assertNotIn('userCode', result)

    def test_pairing_explains_an_approved_or_refused_activation_and_ignores_other_logins(self):
        self.start_ea(pairing='none')
        self.activation_status('approved')
        result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['activationReason']), ('no_pending_pairing', 'approved'))
        self.assertIn('already connected', result['next_action'])
        self.activation_status('build_not_admitted')
        self.assertIn('approved GOAT build', agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['next_action'])
        self.activation_status('approved', account='999999')
        self.assertIsNone(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['activationReason'],
                          'a status written for another login on this data folder is ignored')

    def shared_code_file(self, token=None, raw=None, **changes):
        """The LC36 EA's GOAT/activation-code-<data folder>.json, as GOATDeviceActivationShareCode writes it."""
        folder = Path(self.c.install['common_files_root']) / 'GOAT'; folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('activation-code-' + (token or Path(self.c.install['terminal_data_root']).name) + '.json')
        now = int(time.time())
        record = dict(schema=1, accountId='123456', server='Customer-Demo', buildId=BUILD, activationId='s' * 32, userCode='WXYZ-2345',
                      expiresAtMs=(now + 600) * 1000, observedAtUtc=now, chart=133464893834552370) | changes
        path.write_bytes(raw if raw is not None else json.dumps(record).encode('ascii'))
        return path

    def test_pairing_reads_the_code_the_ea_shares_locally_without_a_mailbox_host(self):
        # LC36: no Portfolio Dashboard or Studio monitor answers the mailbox, and no screenshot is needed.
        self.shared_code_file()
        with patch.object(agent_setup, 'setup_request', side_effect=AssertionError('the mailbox is not used')):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['source'], result['userCode'], result['activationId']),
                         ('pairing_available', 'activation_code_file', 'WXYZ-2345', 's' * 32))
        self.assertEqual((result['accountLogin'], result['accountLast4'], result['server'], result['buildId'], result['demo']),
                         ('123456', '3456', 'Customer-Demo', BUILD, True))
        self.assertEqual(result['accountFacts']['source'], 'mt5_broker_readback')
        self.assertLessEqual(result['responseExpiresAtUtc'], int(time.time()) + 60)
        self.assertFalse((mailbox.setup_root(self.c) / 'registration.json').exists(), 'no mailbox capability was registered')

    def test_shared_code_keeps_the_inert_demo_rules(self):
        self.shared_code_file()
        for mt5, message in ((FakeMT5(self.c, algo=True), 'Algo Trading off'), (FakeMT5(self.c, positions=1), 'Algo Trading off'),
                             (FakeMT5(self.c, orders=1), 'Algo Trading off'), (FakeMT5(self.c, trade_mode=2), 'real-money'),
                             (FakeMT5(self.c, login='654321'), 'different account'), (FakeMT5(self.c, connected=False), 'not connected')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                agent_setup.pairing_code(self.c, BUILD, mt5=mt5)

    def test_a_foreign_stale_or_malformed_shared_code_is_ignored_and_the_mailbox_answers(self):
        self.start_ea()
        now = int(time.time())
        cases = [dict(accountId='999999'), dict(accountId=123456), dict(server='Other-Demo'), dict(buildId='V1.48-OTHER-BUILD-02'),
                 dict(schema=2), dict(userCode='wxyz-2345'), dict(userCode='WXYZ-2341'), dict(userCode='WXYZ2345'),
                 dict(activationId='s' * 31), dict(activationId='s' * 31 + '"'), dict(expiresAtMs=(now + 10) * 1000),
                 dict(expiresAtMs=(now + 1200) * 1000), dict(expiresAtMs=str((now + 600) * 1000)), dict(observedAtUtc=now + 60),
                 dict(raw=b'{not json'), dict(raw=b' ' * 5000), dict(token='Terminal 1 - Banker')]
        for change in cases:
            with self.subTest(change=change):
                path = self.shared_code_file(**change)
                result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
                self.assertEqual((result['status'], result['source'], result['userCode']), ('pairing_available', 'setup_mailbox', 'ABCD-EF23'))
                path.unlink()

    def test_a_symlinked_shared_code_is_ignored_and_the_mailbox_answers(self):
        # A well-formed file behind a link is not the EA's own file: it is never read.
        self.start_ea()
        path = self.shared_code_file()
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda item: item == path or original(item)):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['source'], result['userCode']), ('pairing_available', 'setup_mailbox', 'ABCD-EF23'))
        with patch.object(Path, 'is_symlink', lambda item: item == path or original(item)):
            self.assertIsNone(agent_setup.shared_code(self.c, '123456', 'Customer-Demo', BUILD))
        self.assertIsNotNone(agent_setup.shared_code(self.c, '123456', 'Customer-Demo', BUILD), 'the same file read directly is accepted')

    def demo_lane(self):
        session = dict(self.c.session, authority_kind='demo_direct')
        return patch('studio_agent_setup.session_state', return_value=(session, {}))

    def test_demo_direct_reads_the_shared_code_and_never_registers_the_mailbox(self):
        # beta.17 T2 QA round 2 (P0): Banker and T2 are demo_direct; the B38 EA shares its code locally.
        self.shared_code_file()
        with self.demo_lane(), patch.object(agent_setup, 'setup_register', side_effect=AssertionError('no registration')), \
             patch.object(agent_setup, 'setup_request', side_effect=AssertionError('no mailbox request')):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['source'], result['userCode'], result['accountLogin']),
                         ('pairing_available', 'activation_code_file', 'WXYZ-2345', '123456'))
        self.assertEqual(result['accountFacts']['source'], 'mt5_broker_readback')
        self.assertFalse(mailbox.setup_root(self.c).exists(), 'nothing was written on the demo lane')

    def test_demo_direct_keeps_every_pairing_guardrail(self):
        self.shared_code_file()
        with self.demo_lane():
            for mt5, message in ((FakeMT5(self.c, algo=True), 'Algo Trading off'), (FakeMT5(self.c, positions=1), 'Algo Trading off'),
                                 (FakeMT5(self.c, trade_mode=2), 'real-money'), (FakeMT5(self.c, login='654321'), 'different account'),
                                 (FakeMT5(self.c, connected=False), 'not connected')):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    agent_setup.pairing_code(self.c, BUILD, mt5=mt5)
            with self.assertRaisesRegex(ValueError, 'build ID'):
                agent_setup.pairing_code(self.c, 'x', mt5=FakeMT5(self.c))
        protected = dict(self.c.session, authority_kind='demo_direct', account=dict(self.c.session['account'], login='3000109427'))
        with patch('studio_agent_setup.session_state', return_value=(protected, {})), self.assertRaisesRegex(ValueError, 'running GOAT experiment'):
            agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        # A file for another build or login is ignored, and the demo lane then falls back without a mailbox write.
        self.shared_code_file(buildId='V1.48-OTHER-BUILD-02')
        with self.demo_lane(), patch.object(agent_setup, 'setup_register', side_effect=AssertionError('no registration')):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['next_action']), ('no_native_answer', agent_setup.DEMO_LANE_NO_SHARED_CODE))
        self.assertNotIn('userCode', result)

    def test_demo_direct_without_a_shared_code_explains_by_activation_reason(self):
        with self.demo_lane(), patch.object(agent_setup, 'setup_register', side_effect=AssertionError('no registration')):
            self.activation_status('awaiting_approval')
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
            self.assertEqual((result['status'], result['next_action']), ('no_pending_pairing', agent_setup.DEMO_LANE_NOT_SHARED))
            self.activation_status('approved')
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
            self.assertEqual(result['status'], 'no_pending_pairing'); self.assertIn('already connected', result['next_action'])

    def test_native_human_control_still_uses_the_shared_code_then_the_mailbox(self):
        # Testers' installations: unchanged behaviour on both paths.
        session = dict(self.c.session, authority_kind='native_human_control')
        self.shared_code_file()
        with patch('studio_agent_setup.session_state', return_value=(session, {})):
            self.assertEqual(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['source'], 'activation_code_file')
        self.shared_code_file(buildId='V1.48-OTHER-BUILD-02')
        self.start_ea()
        with patch('studio_agent_setup.session_state', return_value=(session, {})):
            self.assertEqual(agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))['source'], 'setup_mailbox')

    def test_an_ea_that_shares_nothing_gets_one_plain_fallback(self):
        # SM31 and earlier on a strategy chart: no shared file and no mailbox host.
        with patch.object(agent_setup, 'setup_request', return_value=dict(id='b' * 32, result='receipt_timeout')):
            result = agent_setup.pairing_code(self.c, BUILD, mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['next_action']), ('no_native_answer', agent_setup.NO_SHARED_CODE))
        self.assertNotIn('userCode', result)
        self.assertEqual(agent_setup.NO_SHARED_CODE, 'This EA build does not share its connection code with GOAT (SM31 and earlier). '
                         'Enter the 8-character code MT5 shows in its GOAT window under Connect the EA.')

    def test_setup_receipt_rejects_foreign_or_stale_payloads(self):
        good = dict(schema=1, id='c' * 32, result='pairing_available', account=123456, server='Customer-Demo', directory=self.ident['directory'],
                    buildId=BUILD, observedAtUtc=int(time.time()), connected=True, tradingAllowed=False, activationOnly=True, positions=0, orders=0,
                    charts=1, userCode='ABCD-EF23', activationId='a' * 32, responseExpiresAtUtc=int(time.time()) + 30,
                    pairingExpiresAtMs=(int(time.time()) + 600) * 1000)
        mailbox.setup_receipt(good, 'c' * 32, self.ident, pairing=True, fresh=True)
        for change in (dict(account=999999), dict(buildId='V1.48-OTHER-BUILD'), dict(tradingAllowed=True), dict(positions=1),
                       dict(userCode='abcd-ef23'), dict(responseExpiresAtUtc=int(time.time()) + 120)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                mailbox.setup_receipt(good | change, 'c' * 32, self.ident, pairing=True)
        with self.assertRaisesRegex(ValueError, 'Unexpected pairing'):
            mailbox.setup_receipt(good, 'c' * 32, self.ident, pairing=False)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            mailbox.setup_receipt(good, 'c' * 32, self.ident, pairing=True, fresh=True, now=time.time() + 60)

    def test_unanswered_live_request_is_never_overwritten_but_expired_one_retires(self):
        mailbox.setup_register(self.c, self.ident)
        root = mailbox.setup_root(self.c)
        mailbox.atomic(root / 'request.json', dict(schema=1, id='d' * 32, account=123456, server='Customer-Demo', directory=self.ident['directory'],
                                                   buildId=BUILD, expiresAtUtc=int(time.time()) + 60, action='shutdown'))
        with self.assertRaisesRegex(ValueError, 'still live'):
            mailbox.setup_request(self.c, self.ident, 'status', timeout=1)
        mailbox.atomic(root / 'request.json', dict(schema=1, id='d' * 32, account=123456, server='Customer-Demo', directory=self.ident['directory'],
                                                   buildId=BUILD, expiresAtUtc=int(time.time()) - 60, action='shutdown'))
        self.assertEqual(mailbox.setup_request(self.c, self.ident, 'status', timeout=1)['result'], 'receipt_timeout')
        self.assertTrue((root / ('d' * 32 + '.expired.request.json')).exists())

    def test_a_request_the_ea_is_still_reading_is_retired_once_the_share_frees(self):
        # The EA (or any reader) can hold request.json open for a moment, and Windows then
        # denies the rename with a sharing violation. Only that is retried, and only briefly.
        mailbox.setup_register(self.c, self.ident)
        root = mailbox.setup_root(self.c)
        mailbox.atomic(root / 'request.json', dict(schema=1, id='e' * 32, account=123456, server='Customer-Demo', directory=self.ident['directory'],
                                                   buildId=BUILD, expiresAtUtc=int(time.time()) - 60, action='shutdown'))
        real_rename, denials = Path.rename, []
        def busy_rename(path, target):
            if path.name == 'request.json' and len(denials) < 3:
                denials.append(str(path))
                raise PermissionError(13, 'The process cannot access the file because it is being used by another process', str(path), 32)
            return real_rename(path, target)
        with patch.object(Path, 'rename', busy_rename):
            self.assertEqual(mailbox.setup_request(self.c, self.ident, 'status', timeout=1)['result'], 'receipt_timeout')
        self.assertEqual(len(denials), 3)
        self.assertTrue((root / ('e' * 32 + '.expired.request.json')).exists())
        calls = []
        def shared():
            calls.append('shared'); raise PermissionError(13, 'busy', 'request.json', 32)
        with self.assertRaises(PermissionError):
            mailbox.sharing_retry(shared, attempts=3, sleep=lambda seconds: None)
        self.assertEqual(calls.count('shared'), 3, 'the retry is bounded')
        def missing():
            calls.append('missing'); raise FileNotFoundError(2, 'missing', 'request.json')
        with self.assertRaises(FileNotFoundError):
            mailbox.sharing_retry(missing, sleep=lambda seconds: None)
        self.assertEqual(calls.count('missing'), 1, 'only a transient Windows denial is retried')
        def other():
            calls.append('other'); raise PermissionError(13, 'The network name cannot be found', 'request.json', 67)
        with self.assertRaises(PermissionError):
            mailbox.sharing_retry(other, sleep=lambda seconds: None)
        self.assertEqual(calls.count('other'), 1, 'only a transient Windows denial is retried')

    def test_atomic_retries_a_transient_access_denied_replace(self):
        # CI 2026-10-06 (twice): os.replace in atomic() raised [WinError 5] Access is denied while
        # the target was briefly held. Two denials then success: the write lands, no .pending is left.
        root = Path(self.data) / 'denied-replace'; root.mkdir()
        target = root / 'request.json'
        target.write_text('{"old":1}', encoding='utf-8')
        real_replace, denials = os.replace, []
        def denied_twice(source, destination):
            if len(denials) < 2:
                denials.append(str(destination))
                raise PermissionError(13, 'Access is denied', str(destination), 5)
            return real_replace(source, destination)
        with patch.object(mailbox.os, 'replace', denied_twice), patch.object(mailbox.time, 'sleep', lambda seconds: None):
            mailbox.atomic(target, dict(new=2))
        self.assertEqual(len(denials), 2)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), dict(new=2))
        self.assertEqual(list(root.glob('*.pending')), [])

    def test_persistent_access_denied_stays_loud_after_the_bounded_retry(self):
        calls, sleeps = [], []
        def denied():
            calls.append('denied'); raise PermissionError(13, 'Access is denied', 'request.json', 5)
        with self.assertRaises(PermissionError) as raised:
            mailbox.sharing_retry(denied, sleep=sleeps.append)
        self.assertEqual(raised.exception.winerror, 5)
        self.assertEqual(len(calls), mailbox.SHARING_RETRY_ATTEMPTS, 'the retry is bounded')
        self.assertEqual(sleeps, [0.025] * (mailbox.SHARING_RETRY_ATTEMPTS - 1), 'same backoff as a sharing violation')
        calls.clear()
        with self.assertRaises(PermissionError):
            mailbox.sharing_retry(denied, attempts=3, sleep=lambda seconds: None)
        self.assertEqual(len(calls), 3)

    # ---------------------------------------------------------- close-terminal

    def test_close_uses_ea_inert_shutdown_and_is_never_repeated(self):
        ea = self.start_ea(pairing='none')
        result = agent_setup.close_terminal(self.c, 'close-1', build_id=BUILD)
        self.assertEqual((result['phase'], result['method']), ('stopped', 'ea_inert_shutdown'))
        self.assertEqual(ea.shutdowns, 1); self.assertEqual(self.process.closed, [])
        self.assertEqual(agent_setup.close_terminal(self.c, 'close-1', build_id=BUILD)['phase'], 'stopped')
        self.assertEqual(ea.shutdowns, 1, 'a retained close is returned, not resent')

    def test_close_falls_back_to_one_normal_close_without_a_mailbox_host(self):
        result = agent_setup.close_terminal(self.c, 'close-2')
        self.assertEqual((result['phase'], result['method']), ('stopped', 'controller_normal_close'))
        self.assertEqual(len(self.process.closed), 1)
        self.assertEqual(agent_setup.close_terminal(self.c, 'close-3')['phase'], 'already_stopped')

    def test_close_refuses_unless_inert(self):
        self.idle.stop()
        with patch('studio_monitor_probe.inspect_idle_demo', side_effect=ValueError('Repair requires a connected demo, Algo Trading off and no positions/orders')):
            with self.assertRaisesRegex(ValueError, 'Algo Trading off'):
                agent_setup.close_terminal(self.c, 'close-4')
        self.idle.start()
        self.assertEqual(self.process.closed, [])
        self.start_ea(algo=True)
        with self.assertRaisesRegex(ValueError, 'refused to close'):
            agent_setup.close_terminal(self.c, 'close-5', build_id=BUILD)
        (Path(self.c.root) / 'demo-agent').mkdir(exist_ok=True); (Path(self.c.root) / 'demo-agent/STOP').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            agent_setup.close_terminal(self.c, 'close-6', build_id=BUILD)
        self.assertEqual(self.process.closed, [])

    def test_close_refuses_while_a_native_gate_request_or_permit_exists(self):
        gate = self.c.local / 'native-gate'; gate.mkdir(parents=True, exist_ok=True)
        for name in ('request.json', 'permit.json'):
            (gate / name).write_text('{}')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'native Studio request or permit'):
                agent_setup.close_terminal(self.c, 'gate-' + name[:4], build_id=BUILD)
            (gate / name).unlink()
        self.assertEqual(self.process.closed, [])

    def retained_native_request(self, seed='pilot-2-r3', *, consumed=True, result=True, permit=False, binding=None):
        """The Terminal 3 shape (goatai#1885): request.json kept after the EA consumed and answered it.

        request_id is the attempt identity carried in the request, not a hash of its bytes; the
        receipts bind sha256(request.json) as request_sha256, and consumed-<request_id> is the
        EA's byte-identical claim copy.
        """
        gate = self.c.local / 'native-gate'; gate.mkdir(parents=True, exist_ok=True)
        request_id = hashlib.sha256(seed.encode()).hexdigest()
        terminal_id, run_id = binding or (self.c.session['terminal_id'], self.c.session['run_id'])
        request = dict(data_path=str(self.data), action='arm_restart', startup_sha256='d' * 64, schema_version=1,
                       request_id=request_id, terminal_id=terminal_id, run_id=run_id, owner='agent', revision=7, generation=3,
                       job_id=seed, configuration_sha256='c' * 64, expires_utc=int(time.time()) - 4 * 3600)
        raw = (json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest()
        (gate / ('issued-' + request_id + '.json')).write_bytes(json.dumps(dict(request_sha256=digest, request=request)).encode())
        (gate / 'request.json').write_bytes(raw)
        if consumed:
            (gate / ('consumed-' + request_id + '.json')).write_bytes(raw)
            (gate / ('arm-intent-' + request_id + '.json')).write_bytes(json.dumps(dict(request_sha256=digest, startup_sha256='d' * 64)).encode())
        if result:
            (gate / ('result-' + request_id + '.json')).write_bytes(json.dumps(dict(
                request_id=request_id, request_sha256=digest, status='RESTART_ARMED_RECONCILE', observed_utc='2026.10.03 21:58:06')).encode())
        if permit:
            (gate / 'permit.json').write_bytes(json.dumps(dict(request_sha256=digest)).encode())
        return gate, request_id, raw

    def assert_close_refused(self, attempt_id):
        with self.assertRaisesRegex(ValueError, 'native Studio request or permit is pending'):
            agent_setup.close_terminal(self.c, attempt_id, build_id=BUILD)
        self.assertEqual(self.process.closed, [])
        self.assertIsNotNone(self.process.identity, 'MT5 keeps running')

    def test_close_proceeds_past_a_request_the_ea_already_consumed_and_answered(self):
        # Terminal 3: the batch finished hours ago, the permit is revoked, and request.json is still
        # on disk beside its byte-identical consumed-<request_id> copy, issuance, arm intent and result.
        gate, request_id, raw = self.retained_native_request()
        evidence = {path.name: path.read_bytes() for path in gate.iterdir() if path.name != 'launch.lock'}
        ea = self.start_ea(pairing='none')
        result = agent_setup.close_terminal(self.c, 'settled-1', build_id=BUILD)
        self.assertEqual((result['phase'], result['method'], ea.shutdowns), ('stopped', 'ea_inert_shutdown', 1))
        self.assertEqual(result['settled_native_request'], dict(request_id=request_id, request_sha256=hashlib.sha256(raw).hexdigest(),
                                                                action='arm_restart', result='RESTART_ARMED_RECONCILE'))
        self.assertEqual({path.name: path.read_bytes() for path in gate.iterdir() if path.name != 'launch.lock'}, evidence,
                         'the request and its receipt pair are evidence: nothing is deleted or rewritten')
        # Without a mailbox host the controller's own close re-proves the same settled request.
        ea.stop(); self.ea = None
        self.process.identity = FakeProcess().identity
        result = agent_setup.close_terminal(self.c, 'settled-2')
        self.assertEqual((result['phase'], result['method']), ('stopped', 'controller_normal_close'))
        self.assertEqual(result['settled_native_request']['request_id'], request_id)
        self.assertTrue((gate / 'request.json').exists())

    def test_close_still_refuses_a_request_the_ea_has_not_consumed_and_answered(self):
        cases = (('unconsumed', dict(consumed=False, result=False)),       # issued, never claimed by the EA
                 ('unanswered', dict(result=False)),                       # claimed, handler not returned
                 ('other-binding', dict(binding=('terminal-other', 'session-other'))),
                 ('permit', dict(permit=True)))                            # last: a permit always refuses
        for name, options in cases:
            with self.subTest(name):
                gate, _, raw = self.retained_native_request(name, **options)
                self.assert_close_refused('pending-' + name)
                self.assertEqual((gate / 'request.json').read_bytes(), raw)

    def test_close_refuses_when_the_consumed_copy_does_not_match_the_request(self):
        with self.subTest('different bytes under the request id'):
            gate, request_id, raw = self.retained_native_request('tampered')
            (gate / ('consumed-' + request_id + '.json')).write_bytes(raw.replace(b'"revision": 7', b'"revision": 8'))
            self.assert_close_refused('mismatch-bytes')
        with self.subTest('identical bytes under another request id'):
            gate, request_id, raw = self.retained_native_request('renamed', consumed=False)
            (gate / ('consumed-' + hashlib.sha256(b'another').hexdigest() + '.json')).write_bytes(raw)
            self.assert_close_refused('mismatch-name')
        with self.subTest('result bound to another request hash'):
            gate, request_id, raw = self.retained_native_request('rebound')
            (gate / ('result-' + request_id + '.json')).write_bytes(json.dumps(dict(
                request_id=request_id, request_sha256='e' * 64, status='RESTART_ARMED_RECONCILE')).encode())
            self.assert_close_refused('mismatch-result')

    def test_ea_shutdown_refusal_mid_batch_is_final_and_sends_no_fallback_close(self):
        ea = self.start_ea(pairing='none', batch=True)
        with self.assertRaisesRegex(ValueError, 'refused to close'):
            agent_setup.close_terminal(self.c, 'batch-1', build_id=BUILD)
        self.assertEqual((ea.shutdowns, self.process.closed), (0, []))
        self.assertIsNotNone(self.process.identity, 'MT5 keeps running its batch')

    def test_an_unanswered_shutdown_is_withdrawn_before_the_fallback_close(self):
        result = agent_setup.close_terminal(self.c, 'withdraw-1', build_id=BUILD, retire=lambda c, ident, rid: mailbox.setup_retire(c, ident, rid, grace=0))
        self.assertEqual((result['phase'], result['method']), ('stopped', 'controller_normal_close'))
        root = mailbox.setup_root(self.c)
        self.assertFalse((root / 'request.json').exists(), 'no live shutdown request survives the close')
        self.assertTrue((root / (result['withdrawn_request_id'] + '.withdrawn.request.json')).exists())
        # A host that answered during the withdrawal wins: the EA's own close is used, not ours.
        late = FakeProcess()
        self.process.identity = late.identity
        answered = dict(id='e' * 32, result='shutdown_requested', tradingAllowed=False, positions=0, orders=0, observedAtUtc=int(time.time()))
        with patch.object(agent_setup, 'setup_request', return_value=dict(id='e' * 32, result='receipt_timeout')):
            result = agent_setup.close_terminal(self.c, 'withdraw-2', build_id=BUILD, wait_seconds=0.5,
                                                retire=lambda *args: (setattr(self.process, 'identity', None), answered)[1])
        self.assertEqual(result['method'], 'ea_inert_shutdown'); self.assertEqual(len(self.process.closed), 1, 'only the first test closed through the controller')

    def test_the_ea_shutdown_is_sent_without_the_native_gate_held(self):
        # Regression for #112: the controller must not hold launch.lock across the EA request.
        ea = self.start_ea(pairing='none')
        result = agent_setup.close_terminal(self.c, 'gate-free-1', build_id=BUILD)
        self.assertEqual((result['method'], ea.shutdowns, ea.gate_refusals), ('ea_inert_shutdown', 1, 0))
        # Someone else holding the gate (a batch start) makes the EA refuse, and no fallback close follows.
        self.process.identity = FakeProcess().identity
        gate = self.c.local / 'native-gate'; gate.mkdir(parents=True, exist_ok=True)
        holding, release = threading.Event(), threading.Event()
        def hold():
            with exclusive_gate(gate):
                holding.set(); release.wait(10)
        holder = threading.Thread(target=hold, daemon=True); holder.start(); holding.wait(5)
        try:
            with patch.object(agent_setup, 'exclusive_gate', lambda root: __import__('contextlib').nullcontext()):
                with self.assertRaisesRegex(ValueError, 'refused to close'):
                    agent_setup.close_terminal(self.c, 'gate-held-1', build_id=BUILD)
        finally:
            release.set(); holder.join(5)
        self.assertEqual((ea.gate_refusals, self.process.closed), (1, []))

    def test_broker_proof_refuses_real_money_unconnected_and_other_accounts(self):
        self.assertTrue(agent_setup.broker_proof(self.c, self.c.session, mt5=FakeMT5(self.c))['demo'])
        for mt5, message in ((FakeMT5(self.c, trade_mode=2), 'real-money'), (FakeMT5(self.c, connected=False), 'not connected'),
                             (FakeMT5(self.c, login='654321'), 'different account'), (FakeMT5(self.c, positions=1), 'open positions')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                agent_setup.broker_proof(self.c, self.c.session, mt5=mt5)

    # ------------------------------------------------------------------ deploy

    def plan(self, members=None, **changes):
        value = dict(schema='goat-demo-deploy-v1', deploymentId='e' * 32, portfolio=dict(id='cloud-1', name='Pilot portfolio'),
                     buildId=BUILD, accountLogin='123456', policy=dict(aiMode=0, aiThreshold=50, aiProtocol=2, exposureMode=0),
                     members=members if members is not None else [member(0), member(1, 'GBPUSD')])
        value.update(changes)
        path = Path(self.c.root) / 'plan.json'; path.write_text(json.dumps(value))
        return path

    def relaunch(self):
        return patch('studio_demo_deploy.subprocess.Popen', side_effect=lambda *a, **k: (setattr(self.process, 'identity', dict(
            pid=77, executable='terminal64.exe', created_utc='2026-10-02T01:00:00+00:00')), SimpleNamespace(pid=77))[1])

    def test_deploy_loads_the_reviewed_portfolio_and_reads_back_exact_hashes_with_algo_off(self):
        ea = self.start_ea(pairing='none')
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready'); self.assertEqual(result['instruction'], 'Turn on Algo Trading in MT5 to start trading (demo)')
        readback = result['readback']
        self.assertEqual([row['sha256'] for row in readback['rows']], [m['sha256'] for m in json.loads(self.plan().read_text())['members']])
        self.assertTrue(all(row['settingsMatch'] for row in readback['rows']))
        self.assertFalse(readback['trading_allowed']); self.assertFalse(readback['algo_trading']); self.assertTrue(readback['demo'])
        self.assertEqual(ea.shutdowns, 1, 'the inert monitor terminal is closed once before the dashboard launch')
        config = launch.call_args.args[0][1]
        self.assertTrue(config.startswith('/config:'))
        text = Path(config.removeprefix('/config:')).read_bytes().decode('utf-16')
        self.assertIn('[Experts]\r\nEnabled=0', text); self.assertIn('ExpertParameters=GOAT Dashboard Agent.set', text)
        state = deploy.paths(self.c, 'e' * 32)['state'].read_bytes().decode('utf-16').splitlines()
        self.assertEqual(state[0], '#GOAT_AI_LAUNCH_V147_2\t0\t50\t2')
        self.assertTrue(state[1].endswith('\t0\t0') and '\tEURUSD\t' in state[1])
        self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c))['phase'], 'ready', 'a ready deploy is idempotent')
        launch.assert_called_once()

    def test_deploy_refuses_hash_mismatch_version_mismatch_and_wrong_or_protected_account(self):
        bad = member(0); bad['sha256'] = 'f' * 64
        cases = [([bad], {}, 'reviewed SHA-256'), ([member(0, name='GOAT V1.47 EURUSD,M15_Trds0.set')], {}, 'exported by GOAT V1.47'),
                 ([member(0, symbol='EURUSD', name='GOAT V1.48 GBPUSD,M15_Trds0.set')], {}, 'symbol does not match'),
                 (None, dict(accountLogin='999999'), 'differs from this installation')]
        for members, changes, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                deploy.load(self.c, self.plan(members, **changes), mt5=FakeMT5(self.c))
        self.c.session['account']['login'] = '3000109421'
        with patch('studio_demo_deploy.session_state', return_value=(self.c.session, {})), self.assertRaisesRegex(ValueError, 'running GOAT experiment'):
            deploy.load(self.c, self.plan(accountLogin='3000109421'), mt5=FakeMT5(self.c, login='3000109421'))
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['state'].exists(), 'nothing is staged after a refusal')

    def test_deploy_refuses_real_money_algo_on_and_an_existing_dashboard(self):
        with self.assertRaisesRegex(ValueError, 'real-money'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c, trade_mode=2))
        Path(self.c.root, 'demo-deployments', 'e' * 32 + '.json').unlink()
        state = deploy.paths(self.c, 'e' * 32)['state']; state.parent.mkdir(parents=True, exist_ok=True); state.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'already has a saved GOAT dashboard'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c))
        state.unlink(); Path(self.c.root, 'demo-deployments', 'e' * 32 + '.json').unlink()
        self.start_ea(pairing='none', algo=True)
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'refused to close|Algo Trading'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)

    def test_deploy_never_claims_ready_when_child_inputs_differ_or_children_cannot_trade(self):
        for options, message in ((dict(settings_match=False), 'did not complete|differ from the frozen SET'), (dict(child_trade=0), 'not allowed to trade')):
            with self.subTest(message=message):
                self.process.identity = dict(pid=55, executable='terminal64.exe', created_utc='2026-10-02T00:00:00+00:00')
                for path in [*Path(self.c.root).glob('demo-deployments/*'), *Path(self.c.root).glob('terminal-closes/*')]:
                    path.unlink()
                for path in (deploy.paths(self.c, 'e' * 32)['state'], mailbox.portfolio_root(self.c) / 'registration.json', mailbox.portfolio_root(self.c) / 'request.json'):
                    if path.exists(): path.unlink()
                self.start_ea(pairing='none', **options)
                with self.relaunch(), patch.object(deploy, 'AUDIT_WAIT_SECONDS', 2), self.assertRaisesRegex(ValueError, message):
                    deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
                record = json.loads(Path(self.c.root, 'demo-deployments', 'e' * 32 + '.json').read_text())
                self.assertNotEqual(record['phase'], 'ready')
                self.ea.stop(); self.ea = None

    def attach_settling_at(self, ea, settle_seconds, calls):
        """deploy-load's mailbox request, with each deploy_next on a simulated clock: the fake EA
        writes the final receipt only once settle_seconds have passed (never when None)."""
        def request(controller, ident, action, timeout=60):
            if action != 'deploy_next':
                return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            now = [0.0]
            ea.hold_deploy_next = True
            def sleep(seconds):
                now[0] += seconds
                if settle_seconds is not None and now[0] >= settle_seconds and ea.hold_deploy_next:
                    root = mailbox.portfolio_root(controller)
                    receipt = root / (json.loads((root / 'request.json').read_text())['id'] + '.json')
                    ea.hold_deploy_next = False
                    end = time.monotonic() + 10
                    while not receipt.exists() and time.monotonic() < end:
                        time.sleep(0.02)
            issued = int(time.time())
            result = mailbox.portfolio_request(controller, ident, action, timeout=timeout, clock=lambda: now[0], sleep=sleep)
            calls.append(dict(timeout=timeout, elapsed=now[0], issued=issued, receipt=result))
            return result
        return request

    def test_the_deploy_next_wait_covers_the_async_attach_budget_within_the_request_limits(self):
        # B41.1 (GOAT-EA#186) settles a child attach within 75 s, above the child's 60 s licence
        # startup. The wait is deliberately 90 s: the most portfolio_request accepts.
        self.assertGreater(deploy.DEPLOY_NEXT_WAIT_SECONDS, deploy.CHILD_ATTACH_BUDGET_SECONDS)
        self.assertEqual(deploy.DEPLOY_NEXT_WAIT_SECONDS, 90)
        with self.assertRaisesRegex(ValueError, 'Invalid dashboard command'):
            mailbox.portfolio_request(self.c, self.ident, 'deploy_next', timeout=deploy.DEPLOY_NEXT_WAIT_SECONDS + 1)

    def test_a_child_attach_settling_after_60s_still_loads_the_portfolio(self):
        # Every final deploy_next receipt lands at 70 s: a 60 s wait reported receipt_timeout here.
        ea = self.start_ea(pairing='none'); calls = []
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=self.attach_settling_at(ea, 70, calls), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual([call['receipt']['result'] for call in calls], ['child_attached', 'child_attached', 'all_attached'])
        self.assertEqual({call['timeout'] for call in calls}, {90})
        self.assertEqual({call['elapsed'] for call in calls}, {70.0})

    def test_a_child_attach_that_never_settles_times_out_at_90s_with_the_same_refusal(self):
        ea = self.start_ea(pairing='none'); calls = []
        with self.relaunch(), self.assertRaisesRegex(
                ValueError, r'^A child chart could not be attached \(receipt_timeout\); run deploy-status, then deploy-stop to unwind$'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=self.attach_settling_at(ea, None, calls), sleep=lambda s: None)
        self.assertEqual(len(calls), 1, 'no second attach is sent after a timeout')
        call = calls[0]
        self.assertEqual(call['timeout'], 90)
        self.assertTrue(90 <= call['elapsed'] < 90.5, call['elapsed'])
        self.assertEqual(call['receipt'], dict(result='receipt_timeout', id=call['receipt']['id'], requestRetained=True))
        self.assertEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'dashboard_ready')
        # The unanswered request is retained, and outlives the wait: it expires at wait + 5 = 95 s.
        pending = json.loads((mailbox.portfolio_root(self.c) / 'request.json').read_text())
        self.assertEqual((pending['id'], pending['action']), (call['receipt']['id'], 'deploy_next'))
        self.assertIn(pending['expiresAtUtc'] - call['issued'], (95, 96))

    def test_stop_refuses_algo_on_or_open_positions_and_never_closes_them(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        with self.assertRaisesRegex(ValueError, 'Turn Algo Trading off'):
            deploy.stop(self.c, 'stop-1', mt5=FakeMT5(self.c, algo=True))
        with self.assertRaisesRegex(ValueError, 'never closes them automatically'):
            deploy.stop(self.c, 'stop-1', mt5=FakeMT5(self.c, positions=2))
        result = deploy.stop(self.c, 'stop-1', mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['positions_closed'], result['trading_changed']), ('stopped', False, False))
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['state'].exists())
        self.assertTrue(any('.stopped-' in name for name in result['archived']))
        self.assertIsNone(deploy.current_deployment(self.c))

    def test_a_stopped_deployment_can_be_replaced_by_a_new_one(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        deploy.stop(self.c, 'stop-2', mt5=FakeMT5(self.c))
        self.process.identity = dict(pid=88, executable='terminal64.exe', created_utc='2026-10-02T02:00:00+00:00')  # research monitor relaunched
        self.ea.rows = []
        with self.relaunch():
            result = deploy.load(self.c, self.plan(deploymentId='1' * 32, members=[member(0, 'USDJPY')]), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual((result['phase'], result['deployment_id']), ('ready', '1' * 32))
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'Another demo deployment is live'):
            deploy.load(self.c, self.plan(deploymentId='2' * 32), mt5=FakeMT5(self.c))

    def staged_then(self, mutate):
        """Run deploy-load with a close step that changes something after staging."""
        def close(controller, attempt_id, build_id=None):
            mutate(); self.process.identity = None
            return dict(phase='stopped')
        return close

    def test_a_set_or_resume_file_changed_after_staging_is_never_launched(self):
        where = deploy.paths(self.c, 'e' * 32)
        set_path = where['sets'] / 'GOAT V1.48 EURUSD,M15_Trds0.set'
        for label, mutate in (('SET', lambda: set_path.write_bytes(set_path.read_bytes() + b'X\x00')),
                              ('resume file', lambda: where['state'].write_bytes(where['state'].read_bytes().replace('EURUSD'.encode('utf-16-le'), 'USDJPY'.encode('utf-16-le'))))):
            with self.subTest(label=label):
                for path in [*Path(self.c.root).glob('demo-deployments/*'), *where['sets'].glob('*'), where['state'], where['profile'] / 'chart01.chr', where['namespace']]:
                    if path.exists(): path.unlink()
                self.process.identity = FakeProcess().identity
                with self.relaunch() as launch, self.assertRaisesRegex(ValueError, 'changed after the review'):
                    deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), close=self.staged_then(mutate), sleep=lambda s: None)
                launch.assert_not_called()

    def test_the_saved_login_switched_before_relaunch_is_refused(self):
        ini = self.data / 'config/common.ini'
        with self.relaunch() as launch, self.assertRaisesRegex(ValueError, 'Saved broker login/server differs'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None,
                        close=self.staged_then(lambda: ini.write_text('[Common]\nLogin=999999\nServer=Real-Live\n[Experts]\nEnabled=0\n')))
        launch.assert_not_called()

    def test_an_account_turned_real_mid_flow_is_never_reported_ready(self):
        class Switching(FakeMT5):
            calls = 0
            def account_info(self):
                Switching.calls += 1
                return SimpleNamespace(login=123456, server='Customer-Demo', trade_mode=0 if Switching.calls < 3 else 2)
        self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'real-money'):
            deploy.load(self.c, self.plan(), mt5=Switching(self.c), sleep=lambda s: None)
        self.assertNotEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'ready')

    def test_startup_config_turns_algo_off_on_account_change(self):
        self.start_ea(pairing='none')
        with self.relaunch() as launch:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        text = Path(launch.call_args.args[0][1].removeprefix('/config:')).read_bytes().decode('utf-16')
        self.assertIn('[Experts]\r\nEnabled=0\r\nAccount=1\r\n', text)

    def test_a_refused_first_attempt_leaves_no_live_deployment(self):
        with self.assertRaisesRegex(ValueError, 'real-money'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c, trade_mode=2))
        self.assertEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'refused_before_stage')
        self.assertIsNone(deploy.current_deployment(self.c))
        self.start_ea(pairing='none')
        with self.relaunch():
            self.assertEqual(deploy.load(self.c, self.plan(deploymentId='3' * 32), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')

    def test_readiness_requires_the_audit_to_name_this_attempts_registration(self):
        self.start_ea(pairing='none')
        # The mailbox refuses a receipt for another registration (see the next test);
        # readiness independently binds the audit to the journal's registration too.
        def other_registration(controller, ident, action, timeout=20):
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            return receipt | dict(registrationSha256='f' * 64) if action == 'audit' else receipt
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'audited a different registration'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=other_registration, sleep=lambda s: None)
        self.assertEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'policy_applied')

    def test_a_receipt_for_another_registration_is_refused_by_the_mailbox(self):
        self.start_ea(pairing='none').audit_registration = 'f' * 64
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'Portfolio receipt request mismatch'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertNotEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'ready')

    # ------------------------------------------------- relaunch telemetry (goatai#1885)

    def assert_utc(self, value):
        self.assertIsInstance(value, str)
        self.assertIsNotNone(datetime.fromisoformat(value).tzinfo, value)

    def test_deploy_journal_records_the_relaunch_gap_and_exact_popen_call(self):
        self.start_ea(pairing='none')
        with self.relaunch() as launch:
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')
        journal = json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())
        telemetry = journal['launch_telemetry']
        self.assertEqual((telemetry['schema'], telemetry['pid'], journal['pid']), (1, 77, 77))
        for key in ('launch_started_utc', 'popen_returned_utc'):
            self.assert_utc(telemetry[key])
        self.assertGreaterEqual(telemetry['popen_ms'], 0)
        # The previous terminal: which process, how it was closed, and the window its exit falls in.
        previous = telemetry['previous_terminal']
        self.assertEqual(previous, journal['previous_terminal'], 'recorded at the closed phase, carried into the launch')
        self.assertEqual((previous['present_at_stage'], previous['pid'], previous['created_utc']), (True, 55, '2026-10-02T00:00:00+00:00'))
        self.assertEqual((previous['close_attempt_id'], previous['close_phase'], previous['close_method']),
                         ('deploy-' + 'e' * 24, 'stopped', 'ea_inert_shutdown'))
        for key in ('close_requested_utc', 'exit_after_utc', 'observed_gone_utc'):
            self.assert_utc(previous[key])
        self.assertGreaterEqual(previous['inventories'], 1)
        self.assertLessEqual(datetime.fromisoformat(previous['exit_after_utc']), datetime.fromisoformat(previous['observed_gone_utc']))
        close = json.loads(Path(self.c.root, 'terminal-closes', 'deploy-' + 'e' * 24 + '.json').read_text())
        self.assertEqual(close['exit_observation']['observed_gone_utc'], previous['observed_gone_utc'], 'the close journal holds the same evidence')
        # Was the previous MT5 still listed when the launch was issued (it must not be), and the gaps in ms.
        self.assertIs(telemetry['previous_present_at_launch'], False)
        check = telemetry['pre_launch_check']
        self.assertIs(check['present'], False); self.assert_utc(check['started_utc']); self.assert_utc(check['finished_utc'])
        gaps = telemetry['gap_ms']
        self.assertEqual(set(gaps), {'exit_to_launch_at_least', 'exit_to_launch_at_most', 'pre_launch_check_to_launch'})
        for value in gaps.values():
            self.assertIsInstance(value, int); self.assertGreaterEqual(value, 0)
        self.assertLessEqual(gaps['exit_to_launch_at_least'], gaps['exit_to_launch_at_most'])
        # The Popen call exactly as issued.
        popen = telemetry['popen']
        (argv,), options = launch.call_args
        self.assertEqual(set(options), {'cwd', 'stdin', 'stdout', 'stderr', 'creationflags'}, 'every keyword the launch passes is described')
        self.assertTrue(all(options[name] is subprocess.DEVNULL for name in ('stdin', 'stdout', 'stderr')))
        self.assertEqual(popen['argv'], argv)
        self.assertEqual(popen['executable'], self.c.install['terminal_executable'])
        self.assertEqual(popen['command_line'], subprocess.list2cmdline(argv))
        self.assertEqual(popen['cwd'], options['cwd']); self.assertEqual(popen['cwd'], str(Path(self.c.install['terminal_executable']).parent))
        self.assertEqual((popen['creationflags'], popen['creationflags_names']), (options['creationflags'], ['CREATE_NO_WINDOW']))
        self.assertEqual((popen['stdin'], popen['stdout'], popen['stderr']), ('DEVNULL', 'DEVNULL', 'DEVNULL'))
        self.assertEqual((popen['startupinfo'], popen['startupinfo_flags']), ('default (none passed)', ['STARTF_USESTDHANDLES']))
        self.assertTrue(popen['show_window'].startswith('not set'))
        self.assertEqual(popen['close_fds'], 'default (True)'); self.assertNotIn('close_fds', options, 'Popen keeps its default')
        self.assertTrue(popen['inherited_handles'].startswith('only the redirected std handles'))
        self.assertTrue(popen['env'].startswith('inherited')); self.assertNotIn('env', options)
        self.assertEqual(popen['env_child_vs_controller'], dict(added=[], removed=[]))
        logon = popen['env_controller_vs_logon']
        if 'error' not in logon:
            controller_names = {name.casefold() for name in os.environ}
            self.assertTrue(all(name.casefold() in controller_names for name in logon['added']))
            self.assertTrue(all(name.casefold() not in controller_names for name in logon['removed']))
        # Names only: no environment value reaches the env or controller sections.
        text = json.dumps([popen['env_child_vs_controller'], logon, telemetry['controller']])
        for name, value in os.environ.items():
            if len(value) >= 12:
                self.assertNotIn(json.dumps(value)[1:-1], text, name)
        self.assertEqual(telemetry['controller']['pid'], os.getpid())

    def test_close_journal_bounds_the_exit_between_the_last_listing_and_the_first_absence(self):
        class Lingering(FakeProcess):
            """Still listed for two inventories after the normal close."""
            def close(self, identity):
                self.closed.append(identity); self.left = 2
            def inspect(self, timeout=20):
                if getattr(self, 'left', None) is not None:
                    if self.left == 0:
                        return None
                    self.left -= 1
                return self.identity
        result = agent_setup.close_terminal(self.c, 'linger-1', process=Lingering())
        observation = result['exit_observation']
        self.assertEqual((result['phase'], observation['inventories'], observation['poll_interval_seconds']), ('stopped', 3, 0.25))
        self.assertEqual(observation['exit_after_utc'], observation['last_seen_present_utc'])
        self.assertEqual(result['close_requested_utc'], observation['close_requested_utc'])
        seen = [datetime.fromisoformat(observation[k]) for k in ('close_requested_utc', 'last_seen_present_utc', 'observed_gone_utc')]
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(json.loads(Path(self.c.root, 'terminal-closes', 'linger-1.json').read_text())['exit_observation'], observation)

    def test_a_failing_telemetry_probe_never_blocks_the_launch_or_its_journal(self):
        self.start_ea(pairing='none')
        with self.relaunch() as launch, patch.object(deploy, 'launch_record', side_effect=RuntimeError('probe broke')):
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')
        launch.assert_called_once()
        journal = json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())
        self.assertEqual((journal['pid'], journal['launch_telemetry']), (77, dict(schema=1, error='RuntimeError: probe broke')))

    def test_a_crash_after_staging_resumes_the_same_plan(self):
        real, crashed = deploy.write_json, []
        def crash_once(path, value):
            if value.get('phase') == 'staged' and not crashed:
                crashed.append(True); raise RuntimeError('power loss')
            return real(path, value)
        with patch.object(deploy, 'write_json', crash_once), self.assertRaisesRegex(RuntimeError, 'power loss'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(json.loads(deploy.paths(self.c, 'e' * 32)['journal'].read_text())['phase'], 'validated')
        self.assertTrue(deploy.paths(self.c, 'e' * 32)['state'].exists())
        self.start_ea(pairing='none')
        with self.relaunch():
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')

    def test_a_data_folder_name_used_by_another_terminal_is_refused(self):
        claim = deploy.paths(self.c, 'e' * 32)['namespace']
        claim.parent.mkdir(parents=True, exist_ok=True)
        claim.write_bytes(json.dumps(dict(schema=1, directory='c:\\other parent\\customer data')).encode())
        with self.assertRaisesRegex(ValueError, 'same data folder name'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c))
        self.assertTrue(deploy.preflight(self.c, mt5=FakeMT5(self.c))['namespace_conflict'])

    def test_cli_exposes_the_agent_operations_with_their_contracts(self):
        from goat_studio import OPERATION_CONTRACTS, main
        for name in ('pairing-code', 'close-terminal', 'deploy-preflight', 'deploy-load', 'deploy-status', 'deploy-stop'):
            self.assertIn(name, OPERATION_CONTRACTS)
        self.assertIn('never kills or repeats', OPERATION_CONTRACTS['close-terminal']['effect'])
        self.assertIn('never closes positions', OPERATION_CONTRACTS['deploy-stop']['effect'])
        self.c.store.close(); self.c.store = None
        from io import StringIO
        from contextlib import redirect_stdout
        output = StringIO()
        with redirect_stdout(output):
            code = main(['--installation', str(self.fixture.path), 'deploy-status'])
        reply = json.loads(output.getvalue())
        self.assertEqual((code, reply['ok'], reply['result']['deployment']), (0, True, None))

    def test_preflight_is_read_only_and_reports_the_broker_facts(self):
        with patch('studio_monitor_probe.tester_state', return_value='idle'):
            result = deploy.preflight(self.c, mt5=FakeMT5(self.c, algo=True))
        self.assertEqual(result['broker']['algo_trading'], True); self.assertTrue(result['broker']['demo'])
        self.assertEqual((result['tester_state'], result['existing_dashboard'], result['deployment']), ('idle', False, None))
        self.assertFalse(list(Path(self.c.install['common_files_root']).rglob('*.tsv')))
        result = deploy.preflight(self.c, mt5=FakeMT5(self.c, trade_mode=2))
        self.assertIn('real-money', result['broker_error'])

    def test_preflight_reports_the_account_details_additively(self):
        account = dict(currency='USD', balance=10000.0, equity=9876.5, leverage=500, company='Customer Markets Ltd')
        with patch('studio_monitor_probe.tester_state', return_value='idle'):
            result = deploy.preflight(self.c, mt5=FakeMT5(self.c, account=account))
        broker = result['broker']
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual({k: broker[k] for k in ('currency', 'balance', 'equity', 'leverage', 'company', 'trade_mode')},
                         dict(account, trade_mode='demo'))
        self.assertIsInstance(broker['balance'], float); self.assertIsInstance(broker['leverage'], int)
        # Every version 1 key is still there with its old meaning.
        self.assertEqual({k: broker[k] for k in ('login', 'server', 'demo', 'connected', 'algo_trading', 'positions', 'orders', 'build')},
                         dict(login='123456', server='Customer-Demo', demo=True, connected=True, algo_trading=False,
                              positions=0, orders=0, build=5200))
        json.dumps(result, allow_nan=False)

    def test_preflight_account_details_tolerate_a_partial_or_odd_readback(self):
        odd = dict(balance=float('nan'), equity=float('inf'), leverage=True, currency=7, company='\x00\r\n')
        with patch('studio_monitor_probe.tester_state', return_value='idle'):
            broker = deploy.preflight(self.c, mt5=FakeMT5(self.c, account=odd))['broker']
        self.assertEqual({k: broker[k] for k in ('currency', 'balance', 'equity', 'leverage', 'company')},
                         dict(currency=None, balance=None, equity=None, leverage=None, company=None))
        with patch('studio_monitor_probe.tester_state', return_value='idle'):
            broker = deploy.preflight(self.c, mt5=FakeMT5(self.c))['broker']
        self.assertEqual((broker['currency'], broker['balance'], broker['trade_mode']), (None, None, 'demo'))
        self.assertEqual(agent_setup.account_details(FakeMT5(self.c), SimpleNamespace(company='A' * 300))['company'], 'A' * 128)

    def test_trade_mode_names_follow_the_sdk_enum(self):
        class SDK:
            ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 10, 11, 12
        self.assertEqual([agent_setup.trade_mode_name(SDK, v) for v in (10, 11, 12, 0, None)], ['demo', 'contest', 'real', 'unknown', 'unknown'])
        self.assertEqual([agent_setup.trade_mode_name(object(), v) for v in (0, 1, 2, 3)], ['demo', 'contest', 'real', 'unknown'])

    def test_only_preflight_carries_the_account_details(self):
        proof = agent_setup.broker_proof(self.c, self.c.session, mt5=FakeMT5(self.c, account=dict(balance=5.0, currency='EUR')))
        self.assertFalse({'currency', 'balance', 'equity', 'leverage', 'company', 'trade_mode'} & set(proof))


if __name__ == '__main__':
    unittest.main()
