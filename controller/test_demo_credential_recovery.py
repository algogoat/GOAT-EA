"""Credential recovery: an app update for an EA that lost its GOAT sign-in (goatai#1885, T2 2026-10-04).

A terminal whose stored EA credential is rejected ("License not valid for this MT5 account") waits
for a new connection and never loads its Studio UI, so ``preflight`` refuses with ``Fresh EA owner
feedback unavailable`` and no update could fix it. ``credential-recovery-preflight`` and
``install-build --credential-recovery`` relax only that freshness: the account is proven from MT5
itself on an allowlisted demo server, strictly flat, the stale observation must come from the
installed build, and at most two recoveries per login per UTC day reach the MT5 close (Claude-Mac's
APPROVE conditions on #1885). Fixture-only: no MT5 terminal is touched.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import types
import unittest
from unittest.mock import patch

import demo_agent
from demo_agent import FeedbackUnavailable, digest, read_json
import test_demo_agent as fixtures

GUIDE = Path(__file__).with_name('AGENT-START-HERE.md').resolve()
LOGIN = '3000082754'


class CredentialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.DemoAgentTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.monitor = self.f.install_ready()   # active.json, a human Give to Agent, monitor INI
        self.agent = self.f.agent
        self.candidate = self.f.base / 'candidate.ex5'
        self.candidate.write_bytes(b'new-ea')
        self.stuck()
        idle = patch('demo_agent.tester_state', return_value='idle')
        idle.start()
        self.addCleanup(idle.stop)

    def stuck(self, observed_age=1200, binary_age=3600):
        """The EA last reported 20 minutes ago (then its sign-in was rejected); the EX5 was placed an hour ago."""
        now = time.time()
        os.utime(self.f.binary, (now - binary_age, now - binary_age))
        os.utime(self.f.ui, (now - observed_age, now - observed_age))

    def observation(self, **changes):
        value = read_json(self.f.ui)
        value.update(changes)
        stat = self.f.ui.stat()
        self.f.ui.write_text(json.dumps(value))
        os.utime(self.f.ui, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    def recover(self, **extra):
        """Exactly what the desktop's suite.applyUpdate sends for credential recovery (SuiteDemoUpdate)."""
        arguments = dict(require_running=True, linked_login=LOGIN, bundle_version='0.5.0-beta.19',
                         agent_guide_path=GUIDE, credential_recovery=True)
        arguments.update(extra)
        return self.agent.install_build(self.candidate, digest(self.candidate), self.monitor, **arguments)

    def cli(self, *command):
        with patch('demo_agent.DemoAgent', return_value=self.agent), patch('builtins.print') as printed:
            code = demo_agent.main(['--installation', str(self.f.installation), *command])
        return code, json.loads(printed.call_args.args[0])

    def recovery_rows(self, login=LOGIN, at=None):
        row = dict(at=(at or datetime.now(timezone.utc)).isoformat(), operation='install_build',
                   phase='credential_recovery_close', login=login)
        self.agent.state_root.mkdir(parents=True, exist_ok=True)
        with (self.agent.state_root / 'actions.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(row) + '\n')

    # ------------------------------------------------------------- the refusal that opens the path

    def test_only_missing_feedback_carries_the_recovery_reason(self):
        code, refusal = self.cli('preflight')
        self.assertEqual((code, refusal['code'], refusal['reason']), (1, 'REFUSED', 'ea_feedback_unavailable'))
        self.assertIn('Fresh EA owner feedback unavailable', refusal['error'])
        # Fresh feedback that says a person owns the EA: an ordinary refusal, no recovery reason.
        self.observation(owner='human')
        os.utime(self.f.ui, None)
        code, refusal = self.cli('preflight')
        self.assertEqual(code, 1)
        self.assertIn('Human owns the EA', refusal['error'])
        self.assertNotIn('reason', refusal)
        self.assertTrue(issubclass(FeedbackUnavailable, ValueError), 'every existing ValueError refusal path is unchanged')

    def test_existing_feedback_path_is_unchanged(self):
        # Fresh feedback: preflight passes exactly as before, and the recovery preflight refuses.
        os.utime(self.f.ui, None)
        self.assertTrue(self.agent.preflight()['ready_for_install'])
        with self.assertRaisesRegex(ValueError, 'The EA is reporting'):
            self.agent.credential_recovery_preflight()
        # Stale feedback without --credential-recovery: install-build refuses before anything is closed.
        self.stuck()
        with patch.object(self.f.process, 'close') as close:
            with self.assertRaises(FeedbackUnavailable):
                self.recover(credential_recovery=False)
        close.assert_not_called()
        self.assertEqual(self.f.binary.read_bytes(), b'old-ea')

    # ------------------------------------------------------------- happy path

    def test_recovery_preflight_reads_the_account_from_mt5_itself(self):
        self.f.activation_status()   # the B38 EA asked for a new connection
        result = self.agent.credential_recovery_preflight()
        self.assertEqual((result['owner'], result['ready_for_install'], result['ready_for_batch']), ('agent', True, False))
        self.assertEqual((result['broker']['login'], result['broker']['server'], result['broker']['demo']), (LOGIN, 'Darwinex-Demo', True))
        recovery = result['credential_recovery']
        self.assertEqual((recovery['reason'], recovery['server'], recovery['attempts_today'], recovery['daily_limit']),
                         ('ea_feedback_unavailable', 'Darwinex-Demo', 0, 2))
        self.assertGreaterEqual(recovery['feedback_age_seconds'], 1000)
        self.assertEqual((recovery['ea_sign_in']['reason'], recovery['ea_sign_in']['build_id'], recovery['ea_sign_in']['this_login']),
                         ('awaiting_approval', 'V1.49-BETA17-38', True))
        code, reply = self.cli('credential-recovery-preflight')
        self.assertEqual((code, reply['ok']), (0, True))

    def test_recovery_installs_the_new_build_and_it_asks_to_connect(self):
        self.f.process.on_start = self.f.activation_status   # the new build waits for its connection
        result = self.recover()
        self.assertTrue(result['installed'])
        self.assertTrue(result['pairing_required'])
        self.assertEqual(self.f.binary.read_bytes(), b'new-ea')
        receipt = read_json(self.f.installation)
        self.assertEqual((receipt['ea_sha256'], receipt['bundle_version']), (digest(self.candidate), '0.5.0-beta.19'))
        rows = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        close = [row for row in rows if row['phase'] == 'before_close']
        self.assertEqual(len(close), 1)
        self.assertEqual((close[0]['credential_recovery'], close[0]['login']), (True, LOGIN))
        counted = [row for row in rows if row['phase'] == 'credential_recovery_close']
        self.assertEqual([(row['login'], row['new_sha256']) for row in counted], [(LOGIN, digest(self.candidate))])
        self.assertLess(rows.index(counted[0]), rows.index(next(row for row in rows if row['phase'] == 'binary_replaced')))
        self.assertEqual(self.agent._recovery_attempts_today(), 1)

    def test_a_refusal_before_the_close_never_spends_the_daily_allowance(self):
        # Codex review on GOAT-EA#151: DLL imports off refuses after before_close but before MT5 is closed.
        self.f.mt5.dlls_allowed = False
        for _ in range(3):
            with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, 'enable DLL imports'):
                self.recover()
            close.assert_not_called()
        self.assertEqual(self.agent._recovery_attempts_today(), 0)
        self.f.mt5.dlls_allowed = True
        self.f.process.on_start = self.f.activation_status
        self.assertTrue(self.recover()['installed'], 'the person fixed MT5; the allowance is intact')
        self.assertEqual(self.agent._recovery_attempts_today(), 1)

    def test_the_cli_flag_reaches_install_build(self):
        self.f.process.on_start = self.f.activation_status
        code, reply = self.cli('install-build', '--candidate', str(self.candidate), '--sha256', digest(self.candidate),
                               '--monitor-config', str(self.monitor), '--require-running', '--linked-login', LOGIN,
                               '--bundle-version', '0.5.0-beta.19', '--agent-guide-path', str(GUIDE), '--credential-recovery')
        self.assertEqual((code, reply['ok'], reply['result']['pairing_required']), (0, True, True))
        rows = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        self.assertTrue(any(row['phase'] == 'before_close' and row.get('credential_recovery') is True for row in rows))

    def test_recovery_install_refuses_without_its_preconditions_before_anything_closes(self):
        with patch.object(self.f.process, 'close') as close:
            for extra, message in ((dict(require_running=False), 'only a running terminal'),
                                   (dict(linked_login=None), 'only a running terminal'),
                                   (dict(credential_recovery='yes'), 'must be boolean'),
                                   (dict(linked_login='3000109270'), 'differs from paired')):
                with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, message):
                    self.recover(**extra)
            # The same bytes again fix nothing: the build needs its connection approved instead.
            same = self.f.base / 'same.ex5'
            same.write_bytes(b'old-ea')
            with self.assertRaisesRegex(ValueError, 'installs a different build'):
                self.agent.install_build(same, digest(same), self.monitor, require_running=True, linked_login=LOGIN,
                                         bundle_version='0.5.0-beta.19', agent_guide_path=GUIDE, credential_recovery=True)
        close.assert_not_called()
        self.assertEqual(self.f.binary.read_bytes(), b'old-ea')

    # ------------------------------------------------------------- what the broker must prove

    def test_real_account_login_mismatch_and_unreadable_mt5_refuse(self):
        self.f.mt5.trade_mode = 1   # a real-money account
        with self.assertRaisesRegex(ValueError, 'demo and exact paired'):
            self.agent.credential_recovery_preflight()
        self.f.mt5.trade_mode = 0
        self.f.mt5.login = 3000082755   # MT5 shows another login than the paired, linked one
        with self.assertRaisesRegex(ValueError, 'demo and exact paired'):
            self.agent.credential_recovery_preflight()
        self.f.mt5.login = int(LOGIN)
        self.f.mt5.initialize = lambda *args, **kwargs: False   # the MetaTrader5 package cannot read MT5
        with self.assertRaisesRegex(ValueError, 'broker state unavailable'):
            self.agent.credential_recovery_preflight()
        with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, 'broker state unavailable'):
            self.recover()
        close.assert_not_called()

    def test_only_an_allowlisted_demo_server(self):
        server = 'OtherBroker-Demo'   # demo-named, but not on the allowlist
        session = read_json(self.f.root / 'session.json')
        session['account']['server'] = server
        (self.f.root / 'session.json').write_text(json.dumps(session))
        self.agent.session = session
        self.f.mt5.server = server
        self.observation(runtime=dict(read_json(self.f.ui)['runtime'], account_server=server))
        with self.assertRaisesRegex(ValueError, 'only a demo on Darwinex-Demo; MT5 shows OtherBroker-Demo'):
            self.agent.credential_recovery_preflight()
        with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, 'only a demo on Darwinex-Demo'):
            self.recover()
        close.assert_not_called()

    def test_recovery_is_strictly_flat_without_a_read_only_allowance(self):
        # A read-only demo with positions passes the normal broker check, never recovery.
        self.f.mt5.account_trade_allowed = False
        for positions, orders in (((types.SimpleNamespace(symbol='EURUSD'),), ()), ((), (types.SimpleNamespace(symbol='USDJPY'),))):
            with self.subTest(positions=len(positions), orders=len(orders)):
                self.f.mt5.positions, self.f.mt5.orders = positions, orders
                self.assertTrue(self.agent._broker()['demo'], 'the ordinary update path keeps its read-only allowance')
                with self.assertRaisesRegex(ValueError, '0 open positions and 0 pending orders'):
                    self.agent.credential_recovery_preflight()
                with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, '0 open positions'):
                    self.recover()
                close.assert_not_called()

    # ------------------------------------------------------------- the stale observation must be this install's

    def test_an_observation_from_before_this_install_cannot_vouch_for_it(self):
        self.stuck(observed_age=7200, binary_age=3600)   # written before the current EX5 was placed
        with self.assertRaisesRegex(ValueError, 'predates the installed EA build'):
            self.agent.credential_recovery_preflight()
        self.stuck()
        self.assertTrue(self.agent.credential_recovery_preflight()['ready_for_install'])
        # GOAT's own swap of these bytes is newer than the observation (EX5 write time kept old).
        swapped = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.agent._append('install_build', 'binary_replaced', old_sha256='0' * 64, new_sha256=digest(self.f.binary))
        rows = (self.agent.state_root / 'actions.jsonl').read_text().splitlines()
        last = json.loads(rows[-1]); last['at'] = swapped.isoformat()
        (self.agent.state_root / 'actions.jsonl').write_text('\n'.join(rows[:-1] + [json.dumps(last)]) + '\n')
        with self.assertRaisesRegex(ValueError, 'predates the installed EA build'):
            self.agent.credential_recovery_preflight()
        with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, 'predates the installed EA build'):
            self.recover()
        close.assert_not_called()

    def test_the_observation_must_name_the_installed_file_and_its_verified_build(self):
        self.observation(runtime=dict(read_json(self.f.ui)['runtime'], program_path=str(self.f.base / 'other' / 'GOAT V1.49.ex5')))
        with self.assertRaisesRegex(ValueError, 'not from the installed EA file'):
            self.agent.credential_recovery_preflight()
        self.observation(runtime=dict(read_json(self.f.ui)['runtime'], program_path=str(self.f.binary)), build='B37')
        verified = self.agent.state_root / 'verified-build.json'
        verified.parent.mkdir(parents=True, exist_ok=True)
        verified.write_text(json.dumps(dict(ea_sha256=digest(self.f.binary), build='B38')))
        with self.assertRaisesRegex(ValueError, 'names build B37, not the installed build B38'):
            self.agent.credential_recovery_preflight()
        self.observation(build='B38')
        self.assertEqual(self.agent.credential_recovery_preflight()['credential_recovery']['observed_build'], 'B38')
        # A marker recorded for other bytes says nothing about this build.
        verified.write_text(json.dumps(dict(ea_sha256='0' * 64, build='B36')))
        self.assertTrue(self.agent.credential_recovery_preflight()['ready_for_install'])

    def test_a_verified_readback_records_the_build_marker_with_its_bytes(self):
        os.utime(self.f.ui, None)   # the EA reports: the ordinary update path
        prior = self.f.ui.stat().st_mtime_ns

        def answers():
            self.f.ui.write_text(json.dumps(dict(owner='agent', loaded=True, build='B40', run_id='session-one',
                runtime=dict(account_demo=True, account_login=LOGIN, account_server='Darwinex-Demo', program_path=str(self.f.binary)))))
            os.utime(self.f.ui, ns=(prior + 10**9, prior + 10**9))

        self.f.process.on_start = answers
        self.agent.install_build(self.candidate, digest(self.candidate), self.monitor, require_running=True,
                                 linked_login=LOGIN, bundle_version='0.5.0-beta.19', agent_guide_path=GUIDE)
        self.assertEqual(read_json(self.agent.state_root / 'verified-build.json')['build'], 'B40')
        self.assertEqual(read_json(self.agent.state_root / 'verified-build.json')['ea_sha256'], digest(self.candidate))

    # ------------------------------------------------------------- at most two per login per UTC day

    def test_at_most_two_recoveries_per_login_per_utc_day(self):
        self.recovery_rows(at=datetime.now(timezone.utc) - timedelta(days=1))   # yesterday: not counted
        self.recovery_rows(login='3000099999')                                 # another login: not counted
        self.recovery_rows()
        self.assertEqual(self.agent.credential_recovery_preflight()['credential_recovery']['attempts_today'], 1)
        self.recovery_rows()
        with self.assertRaisesRegex(ValueError, 'already ran 2 times today \\(UTC\\) for this login; a person should look at this terminal'):
            self.agent.credential_recovery_preflight()
        with patch.object(self.f.process, 'close') as close, self.assertRaisesRegex(ValueError, 'a person should look at this terminal'):
            self.recover()
        close.assert_not_called()
        self.assertEqual(self.f.binary.read_bytes(), b'old-ea')

    def test_two_real_recoveries_exhaust_the_day_and_no_third_close_happens(self):
        closes = []
        original_close = self.f.process.close

        def close(identity):
            closes.append(identity)
            original_close(identity)

        def reported_after_the_swap():
            # The new build ran (a person approved it), reported once, then lost its sign-in again.
            time.sleep(0.05)
            self.observation(build='B40')
            os.utime(self.f.ui, None)

        self.f.process.close = close
        self.f.process.on_start = self.f.activation_status
        self.assertTrue(self.recover()['pairing_required'])
        second = self.f.base / 'second.ex5'
        second.write_bytes(b'newer-ea')
        reported_after_the_swap()
        self.agent.install_build(second, digest(second), self.monitor, require_running=True, linked_login=LOGIN,
                                 bundle_version='0.5.0-beta.19', agent_guide_path=GUIDE, credential_recovery=True)
        third = self.f.base / 'third.ex5'
        third.write_bytes(b'newest-ea')
        reported_after_the_swap()
        with self.assertRaisesRegex(ValueError, 'a person should look at this terminal'):
            self.agent.install_build(third, digest(third), self.monitor, require_running=True, linked_login=LOGIN,
                                     bundle_version='0.5.0-beta.19', agent_guide_path=GUIDE, credential_recovery=True)
        self.assertEqual(len(closes), 2)
        self.assertEqual(self.f.binary.read_bytes(), b'newer-ea')

    def test_an_unreadable_action_log_refuses(self):
        self.agent.state_root.mkdir(parents=True, exist_ok=True)
        (self.agent.state_root / 'actions.jsonl').write_text('{not json\n')
        with self.assertRaisesRegex(ValueError, 'action log unreadable'):
            self.agent.credential_recovery_preflight()


if __name__ == '__main__':
    unittest.main()
