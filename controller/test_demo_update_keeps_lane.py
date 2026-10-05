"""An app update with MT5 open keeps the session's lane (goatai#1885, Terminal 3, 2026-10-04).

The desktop app updates an open demo terminal through ``install-build --require-running
--linked-login --bundle-version --agent-guide-path``. Before this fix that rewrote a customer
session (``native_human_control``, from ``studio bootstrap``) to the owner demo lane
(``demo_direct``), and the customer's next ``studio close-terminal`` refused with "Demo mutation
requires the broker-verified agent tool". Fixture-only: no MT5 terminal is touched.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import digest, read_json
from goat_studio import Controller
import studio_agent_setup as agent_setup
from studio_command_store import StudioStore
from studio_research_authority import dispatch, operation
import test_demo_agent as fixtures

GUIDE = Path(__file__).with_name('AGENT-START-HERE.md').resolve()
REFUSED = 'Demo mutation requires the broker-verified agent tool'


class UpdateKeepsLaneTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.DemoAgentTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.monitor = self.f.install_ready()   # active.json, a human Give to Agent, monitor INI
        self.candidate = self.f.base / 'candidate.ex5'
        self.candidate.write_bytes(b'new-ea')
        prior_mtime = self.f.ui.stat().st_mtime_ns
        tick = [0]

        def ea_answers_after_relaunch():
            tick[0] += 1
            self.f.ui.write_text(json.dumps(dict(owner='agent', loaded=True, runtime=dict(
                account_demo=True, account_login='3000082754', account_server='Darwinex-Demo',
                program_path=str(self.f.binary)))))
            observed = prior_mtime + tick[0] * 1_000_000_000
            os.utime(self.f.ui, ns=(observed, observed))

        self.f.process.on_start = ea_answers_after_relaunch

    def lane(self, kind):
        """The session as `studio bootstrap` (customer) or an owner enrollment (demo_direct) left it."""
        session = read_json(self.f.root / 'session.json')
        session.update(authority_kind=kind, installation_sha256=sha(self.f.agent.install))
        (self.f.root / 'session.json').write_text(json.dumps(session))
        self.f.agent.session = session

    def session(self):
        return read_json(self.f.root / 'session.json')

    def app_update(self, **extra):
        """Exactly what the desktop's suite.applyUpdate sends with MT5 open (SuiteDemoUpdate)."""
        with patch('demo_agent.tester_state', return_value='idle'):
            return self.f.agent.install_build(self.candidate, digest(self.candidate), self.monitor,
                require_running=True, linked_login='3000082754', bundle_version='0.5.0-beta.19',
                agent_guide_path=GUIDE, **extra)

    def customer_close_terminal(self, attempt_id):
        """`goat.exe studio close-terminal` (Desktop suite.closeTerminal): the CLI choke point, then the close."""
        with operation('close-terminal'):
            controller = Controller(self.f.installation)
            dispatch(controller, SimpleNamespace(operation='close-terminal'))
            controller.open()
            (controller.local / 'native-gate').mkdir(parents=True, exist_ok=True)   # bootstrap's configure_gate
            try:
                running = self.f.process.inspect()
                return agent_setup.close_terminal(controller, attempt_id, process=self.f.process,
                    inspect=lambda c: dict(process=running), wait_seconds=1)
            finally:
                controller.store.close()

    def test_customer_update_with_mt5_open_stays_customer_lane_and_close_terminal_works(self):
        self.lane('native_human_control')
        before = self.session()
        result = self.app_update()
        self.assertTrue(result['installed'])
        # The build is verified and the monitor resumed, exactly as before the fix.
        self.assertEqual(result['sha256'], digest(self.candidate))
        self.assertEqual(self.f.binary.read_bytes(), b'new-ea')
        self.assertEqual(read_json(self.f.agent.state_root / 'verified-build.json')['ea_sha256'], digest(self.candidate))
        receipt = read_json(self.f.installation)
        self.assertEqual((receipt['ea_sha256'], receipt['bundle_version']), (digest(self.candidate), '0.5.0-beta.19'))
        # The lane is unchanged; only the receipt binding moved with the new receipt.
        after = self.session()
        self.assertEqual(after['authority_kind'], 'native_human_control')
        self.assertEqual(after['installation_sha256'], sha(receipt))
        self.assertEqual({k: v for k, v in after.items() if k != 'installation_sha256'},
                         {k: v for k, v in before.items() if k != 'installation_sha256'})
        rows = [json.loads(line) for line in (self.f.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        identity_rows = [row for row in rows if row['phase'] == 'local_identity_verified']
        self.assertTrue(identity_rows)
        self.assertTrue(all(row['authority_kind'] == row['previous_authority_kind'] == 'native_human_control'
                            for row in identity_rows))
        # Customer-lane tools still work: the close the T3 tester was refused.
        closed = self.customer_close_terminal('close-after-update')
        self.assertEqual((closed['phase'], closed['method']), ('stopped', 'controller_normal_close'))

    def test_same_bytes_customer_update_verifies_in_place_without_closing_mt5(self):
        self.lane('native_human_control')
        self.app_update()
        self.f.ui.write_text(json.dumps(dict(owner='agent', loaded=True, runtime=dict(account_demo=True,
            account_login='3000082754', account_server='Darwinex-Demo', program_path=str(self.f.binary)))))
        with patch.object(self.f.process, 'close', side_effect=AssertionError('same bytes never close MT5')), \
                patch('demo_agent.tester_state', return_value='idle'):
            again = self.f.agent.install_build(self.candidate, digest(self.candidate), self.monitor,
                require_running=True, linked_login='3000082754', bundle_version='0.5.0-beta.20', agent_guide_path=GUIDE)
        self.assertTrue(again['already_installed'])
        self.assertEqual(self.session()['authority_kind'], 'native_human_control')
        self.assertEqual(self.session()['installation_sha256'], sha(read_json(self.f.installation)))
        self.assertEqual(read_json(self.f.installation)['bundle_version'], '0.5.0-beta.20')

    def test_owner_demo_direct_update_stays_demo_direct(self):
        self.lane('demo_direct')
        self.assertTrue(self.app_update()['installed'])
        after = self.session()
        self.assertEqual(after['authority_kind'], 'demo_direct')
        self.assertEqual(after['installation_sha256'], sha(read_json(self.f.installation)))
        with patch('demo_agent.tester_state', return_value='idle'):
            self.assertTrue(self.f.agent.preflight()['ready_for_batch'])
        # The owner lane's raw-CLI policy is unchanged: its mutations still go through `goat demo`.
        with operation('close-terminal'), self.assertRaisesRegex(ValueError, REFUSED):
            dispatch(Controller(self.f.installation), SimpleNamespace(operation='close-terminal'))

    def test_only_an_explicit_owner_enrollment_enters_the_demo_lane(self):
        self.lane('native_human_control')
        with patch.object(self.f.process, 'close') as close:
            with self.assertRaisesRegex(ValueError, 'An app update keeps the session lane'):
                self.app_update(enter_demo_lane=True)
        close.assert_not_called()
        self.assertEqual(self.f.binary.read_bytes(), b'old-ea')
        with patch('demo_agent.tester_state', return_value='idle'):
            enrolled = self.f.agent.install_build(self.candidate, digest(self.candidate), self.monitor,
                                                  enter_demo_lane=True)
        self.assertTrue(enrolled['installed'])
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    # ------------------------------------------------------------- restore-lane

    def flipped_by_old_update(self):
        """Replay what install-build did before this fix: swap the EA, then move the lane."""
        self.lane('native_human_control')
        self.f.binary.write_bytes(b'new-ea')
        self.f.agent._adopt_installed_binary(digest(self.f.binary), enter_demo_lane=True)
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def test_restore_lane_returns_a_flipped_customer_session_and_close_terminal_works_again(self):
        self.flipped_by_old_update()
        with self.assertRaisesRegex(ValueError, REFUSED):
            self.customer_close_terminal('refused-on-t3')
        flipped = (self.f.root / 'session.json').read_bytes()
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['status'], preview['restores_to']), ('ready_to_restore', 'native_human_control'))
        self.assertEqual((self.f.root / 'session.json').read_bytes(), flipped, 'a preview writes nothing')
        result = self.f.agent.restore_lane(apply=True)
        self.assertEqual(result['status'], 'restored')
        restored = self.session()
        self.assertEqual(restored['authority_kind'], 'native_human_control')
        self.assertEqual(restored['installation_sha256'], sha(read_json(self.f.installation)))
        self.assertEqual(Path(result['demo_direct_backup']).read_bytes(), flipped)
        self.assertEqual(self.f.agent.restore_lane(apply=True)['status'], 'already_customer_lane')
        closed = self.customer_close_terminal('close-after-restore')
        self.assertEqual(closed['phase'], 'stopped')

    def test_restore_lane_never_touches_an_owner_lane_that_did_demo_work(self):
        self.flipped_by_old_update()
        self.f.agent._append('studio_run_batch', 'driver_started', batch_id='owner-batch')
        with self.assertRaisesRegex(ValueError, 'owner demo-lane work \\(studio_run_batch\\)'):
            self.f.agent.restore_lane(apply=True)
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def test_restore_lane_refuses_without_exact_customer_evidence_or_while_work_is_in_flight(self):
        self.flipped_by_old_update()
        backups = sorted((self.f.agent.state_root / 'backups').glob('session-*.json'))
        customer = next(path for path in backups if read_json(path)['authority_kind'] == 'native_human_control')
        held = customer.with_suffix('.held')
        customer.rename(held)
        with self.assertRaisesRegex(ValueError, 'No retained customer-lane backup'):
            self.f.agent.restore_lane()
        held.rename(customer)
        customer.write_bytes(customer.read_bytes() + b' ')   # content no longer matches its name
        with self.assertRaisesRegex(ValueError, 'No retained customer-lane backup'):
            self.f.agent.restore_lane()
        customer.write_bytes(customer.read_bytes()[:-1])
        self.assertEqual(self.f.agent.restore_lane()['status'], 'ready_to_restore')
        stop = self.f.agent.state_root / 'STOP'
        stop.write_text('{"actor":"demo_agent"}')
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.f.agent.restore_lane(apply=True)
        stop.unlink()
        (self.f.root / 'research-authority.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'typed research continuation'):
            self.f.agent.restore_lane(apply=True)
        (self.f.root / 'research-authority.json').unlink()
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with closing(sqlite3.connect(self.f.root / 'studio.sqlite')) as db, db:
            db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)',
                       (binding, json.dumps([dict(job_id='live-batch', status='running')])))
        with self.assertRaisesRegex(ValueError, 'live-batch is active'):
            self.f.agent.restore_lane(apply=True)
        store = self.f.root / 'studio.sqlite'
        store.rename(store.with_suffix('.held'))
        StudioStore(store).close()   # a store with no customer-lane authority for this binding
        with self.assertRaisesRegex(ValueError, 'no customer-lane authority'):
            self.f.agent.restore_lane(apply=True)
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def legacy_only_backups(self, mutate=None):
        """The beta.14-era shape (goatai support edc7e808): the only customer-era backup predates
        authority_kind; every other retained backup is demo_direct."""
        backups = self.f.agent.state_root / 'backups'
        for path in sorted(backups.glob('session-*.json')):
            saved = read_json(path)
            if saved.get('authority_kind') == 'native_human_control':
                path.unlink()
                legacy = {key: value for key, value in saved.items() if key != 'authority_kind'}
                if mutate:
                    mutate(legacy)
                raw = json.dumps(legacy, indent=2).encode('utf-8')
                staged = backups / 'staged.json'
                staged.write_bytes(raw)
                staged.rename(backups / ('session-' + digest(staged) + '.json'))

    def test_restore_lane_accepts_a_legacy_backup_without_authority_kind(self):
        self.flipped_by_old_update()
        self.legacy_only_backups()
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['status'], preview['evidence_kind']),
                         ('ready_to_restore', 'legacy-session-without-authority-kind'))
        result = self.f.agent.restore_lane(apply=True)
        self.assertEqual((result['status'], result['authority_kind']), ('restored', 'native_human_control'))
        self.assertEqual(self.session()['authority_kind'], 'native_human_control')
        closed = self.customer_close_terminal('close-after-legacy-restore')
        self.assertEqual(closed['phase'], 'stopped')

    def test_a_legacy_backup_with_any_other_difference_never_restores(self):
        self.flipped_by_old_update()
        self.legacy_only_backups(mutate=lambda legacy: legacy.update(run_id='another-run'))
        with self.assertRaisesRegex(ValueError, 'No retained customer-lane backup'):
            self.f.agent.restore_lane()
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def test_a_legacy_backup_never_restores_without_the_store_customer_authority(self):
        self.flipped_by_old_update()
        self.legacy_only_backups()
        store = self.f.root / 'studio.sqlite'
        store.rename(store.with_suffix('.held'))
        StudioStore(store).close()   # no customer-lane authority for this binding
        with self.assertRaisesRegex(ValueError, 'no customer-lane authority'):
            self.f.agent.restore_lane(apply=True)
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def test_restore_lane_cli_previews_by_default(self):
        import demo_agent
        self.flipped_by_old_update()
        with patch('demo_agent.DemoAgent', return_value=self.f.agent), patch('builtins.print') as printed:
            self.assertEqual(demo_agent.main(['--installation', str(self.f.installation), 'restore-lane']), 0)
        self.assertEqual(json.loads(printed.call_args.args[0])['result']['status'], 'ready_to_restore')
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')
        with patch('demo_agent.DemoAgent', return_value=self.f.agent), patch('builtins.print') as printed:
            self.assertEqual(demo_agent.main(['--installation', str(self.f.installation), 'restore-lane', '--apply']), 0)
        self.assertEqual(json.loads(printed.call_args.args[0])['result']['status'], 'restored')
        self.assertEqual(self.session()['authority_kind'], 'native_human_control')


if __name__ == '__main__':
    unittest.main()
