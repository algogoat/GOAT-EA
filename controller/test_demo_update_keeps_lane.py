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


def legacy_adopt(agent, expected_sha256):
    """DemoAgent._adopt_installed_binary exactly as bundles beta.15-17 shipped it (GOAT-EA before #143,
    e.g. controller-release-71caef1): it forced demo_direct and logged no lane fields."""
    import shutil
    from datetime import datetime, timezone
    from demo_agent import write_json
    from studio_installation import load_installation
    backup = agent.state_root / 'backups'
    backup.mkdir(parents=True, exist_ok=True)
    for name, path in (('installation', agent.installation_path), ('session', agent.root / 'session.json')):
        saved = backup / (name + '-' + digest(path) + '.json')
        if not saved.exists():
            shutil.copyfile(path, saved)
    installed = read_json(agent.installation_path)
    if installed['ea_sha256'] != expected_sha256:
        installed['ea_sha256'] = expected_sha256
        installed['demo_installed_at'] = datetime.now(timezone.utc).isoformat()
        write_json(agent.installation_path, installed)
    checked = load_installation(agent.installation_path)
    session = read_json(agent.root / 'session.json')
    if session.get('authority_kind') != 'demo_direct' or session.get('installation_sha256') != sha(checked):
        session['authority_kind'] = 'demo_direct'
        session['installation_sha256'] = sha(checked)
        write_json(agent.root / 'session.json', session)
    agent.install, agent.session = checked, session
    agent._append('install_build', 'local_identity_verified', ea_sha256=expected_sha256,
                  installation_sha256=sha(checked), session_sha256=sha(session))


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

    def flipped_by_old_update(self, *, bundle_row=True):
        """Replay what a beta.15-17 app update did (GOAT-EA before #143): swap the EA, then move the lane."""
        self.lane('native_human_control')
        self.f.binary.write_bytes(b'new-ea')
        legacy_adopt(self.f.agent, digest(self.f.binary))
        if bundle_row:   # the desktop's update finish (suiteDemoUpdate passes --bundle-version since 2026-09-29)
            self.f.agent._append('install_build', 'bundle_identity_verified', bundle_version='0.5.0-beta.17',
                                 agent_guide_path=str(GUIDE))
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def enrolled_by_owner(self, *, marker=True):
        """The owner's install-build --enter-demo-lane on a customer session (beta.19 on). Without
        ``marker``, the identity row exactly as beta.19-21 wrote it (no enter_demo_lane field)."""
        self.lane('native_human_control')
        self.f.binary.write_bytes(b'new-ea')
        self.f.agent._adopt_installed_binary(digest(self.f.binary), enter_demo_lane=True)
        if not marker:
            self.rewrite_log(lambda row: {k: v for k, v in row.items() if k != 'enter_demo_lane'})
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def rewrite_log(self, change):
        log = self.f.agent.state_root / 'actions.jsonl'
        rows = [change(json.loads(line)) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
        log.write_text(''.join(json.dumps(row) + '\n' for row in rows if row is not None), encoding='utf-8')

    def log(self):
        return [json.loads(line) for line in (self.f.agent.state_root / 'actions.jsonl').read_text().splitlines()]

    def cli(self, *args):
        import demo_agent
        with patch('demo_agent.DemoAgent', return_value=self.f.agent), patch('builtins.print') as printed:
            code = demo_agent.main(['--installation', str(self.f.installation), *args])
        return code, json.loads(printed.call_args.args[0])

    # ------------------------------------------------------------- moved_by (goatai#2272 gap 1)

    def test_an_old_app_updates_flip_is_moved_by_app_update_and_applies_without_confirmation(self):
        self.flipped_by_old_update()
        rows = [row for row in self.log() if row['phase'] == 'local_identity_verified']
        self.assertEqual(len(rows), 1)
        self.assertNotIn('previous_authority_kind', rows[0])        # what the beta.15-17 controller logged
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['status'], preview['moved_by'], preview['owner_confirmation_required']),
                         ('ready_to_restore', 'app_update', False))
        self.assertEqual(preview['moved_by_evidence']['bundle_version'], '0.5.0-beta.17')
        self.assertEqual(preview['moved_by_evidence']['previous_authority_kind'], None)
        applied = self.f.agent.restore_lane(apply=True)
        self.assertEqual((applied['status'], applied['moved_by'], applied['owner_confirmed']), ('restored', 'app_update', False))
        self.assertEqual(self.session()['authority_kind'], 'native_human_control')
        self.assertEqual((self.log()[-1]['operation'], self.log()[-1]['moved_by']), ('restore_lane', 'app_update'))

    def test_an_old_flip_without_the_desktops_bundle_row_is_still_an_app_update(self):
        self.flipped_by_old_update(bundle_row=False)
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['moved_by'], preview['moved_by_evidence']['bundle_version']), ('app_update', None))

    def test_an_owner_enrollment_previews_but_applies_only_with_owner_confirmed(self):
        for marker in (True, False):
            with self.subTest(marker=marker):
                self.enrolled_by_owner(marker=marker)
                row = [row for row in self.log() if row['phase'] == 'local_identity_verified'][-1]
                self.assertEqual((row['previous_authority_kind'], row['authority_kind']), ('native_human_control', 'demo_direct'))
                self.assertEqual(row.get('enter_demo_lane'), True if marker else None)
                preview = self.f.agent.restore_lane()
                # The preview is unchanged for a person or agent; it only says who moved the session.
                self.assertEqual((preview['status'], preview['moved_by'], preview['owner_confirmation_required']),
                                 ('ready_to_restore', 'owner_enrollment', True))
                self.assertIn('--owner-confirmed', preview['next_action'])
                with self.assertRaisesRegex(ValueError, 'changes nothing without --owner-confirmed') as refused:
                    self.f.agent.restore_lane(apply=True)
                self.assertEqual((refused.exception.code, refused.exception.fields), ('RESTORE_OWNER_ENROLLED', dict(moved_by='owner_enrollment')))
                self.assertEqual(self.session()['authority_kind'], 'demo_direct')
                code, error = self.cli('restore-lane', '--apply')
                self.assertEqual((code, error['ok'], error['code'], error['refusal_code'], error['moved_by']),
                                 (1, False, 'REFUSED', 'RESTORE_OWNER_ENROLLED', 'owner_enrollment'))
                self.assertEqual(self.session()['authority_kind'], 'demo_direct')
                code, applied = self.cli('restore-lane', '--apply', '--owner-confirmed')
                self.assertEqual((code, applied['result']['status'], applied['result']['owner_confirmed']), (0, 'restored', True))
                self.assertEqual(self.session()['authority_kind'], 'native_human_control')
                self.assertEqual((self.log()[-1]['moved_by'], self.log()[-1]['owner_confirmed']), ('owner_enrollment', True))
                self.f.binary.write_bytes(b'old-ea')

    def test_no_lane_move_on_record_is_unknown_and_applies(self):
        self.flipped_by_old_update()
        self.legacy_only_backups()
        self.drop_identity_rows()
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['status'], preview['moved_by'], preview['moved_by_evidence']), ('ready_to_restore', 'unknown', None))
        self.assertEqual(self.f.agent.restore_lane(apply=True)['moved_by'], 'unknown')

    def test_moved_by_follows_the_current_stint(self):
        from demo_agent import _lane_moved_by
        old = dict(operation='install_build', phase='local_identity_verified', ea_sha256='a')       # beta.15-17
        def new(previous, now, **extra):                                                          # beta.19 on
            return dict(operation='install_build', phase='local_identity_verified', previous_authority_kind=previous,
                        authority_kind=now, **extra)
        restored = dict(operation='restore_lane', phase='restored')
        cases = [
            ([], 'unknown'),
            ([old], 'app_update'),
            ([new('native_human_control', 'native_human_control')], 'unknown'),     # an update that kept the lane
            ([new('native_human_control', 'demo_direct')], 'owner_enrollment'),
            ([new(None, 'demo_direct')], 'owner_enrollment'),                        # a legacy session enrolled
            ([new('demo_direct', 'demo_direct')], 'unknown'),                        # already moved before the log
            ([old, new('demo_direct', 'demo_direct')], 'app_update'),                # a later update keeps the flip's cause
            ([old, new('demo_direct', 'demo_direct', enter_demo_lane=True)], 'owner_enrollment'),  # the owner claims it
            ([new('native_human_control', 'demo_direct'), old], 'owner_enrollment'),
            ([old, restored, new('native_human_control', 'demo_direct')], 'owner_enrollment'),
            ([new('native_human_control', 'demo_direct'), restored, old], 'app_update'),
            ([old, restored], 'unknown'),
            ([old, new('demo_direct', 'native_human_control')], 'unknown'),
        ]
        for rows, expected in cases:
            with self.subTest(rows=rows):
                self.assertEqual(_lane_moved_by(rows)[0], expected)

    # ------------------------------------------------------------- refusal codes (goatai#2272 gap 3)

    def test_every_restore_lane_refusal_has_its_stable_code_beside_the_unchanged_sentence(self):
        from demo_agent import RESTORE_REFUSAL_CODES, Refusal
        agent, root, seen = self.f.agent, self.f.root, set()

        def refused(code, sentence, call=lambda: agent.restore_lane(apply=True)):
            with self.subTest(code=code):
                with self.assertRaisesRegex(Refusal, sentence) as caught:
                    call()
                self.assertEqual(caught.exception.code, code)
                seen.add(code)
            self.assertEqual(self.session()['authority_kind'], session_lane)

        session_lane = 'demo_direct'
        self.flipped_by_old_update()
        refused('RESTORE_INVALID_ARGUMENT', 'restore-lane --apply must be boolean', lambda: agent.restore_lane('yes'))
        refused('RESTORE_INVALID_ARGUMENT', 'restore-lane --owner-confirmed must be boolean',
                lambda: agent.restore_lane(True, owner_confirmed=1))
        saved = (root / 'session.json').read_bytes()
        for change, code, sentence in ((dict(authority_kind='something_else'), 'RESTORE_NOT_DEMO_DIRECT', 'returns only a demo_direct session'),
                                       (dict(installation_sha256='0' * 64), 'RESTORE_NOT_BOUND_TO_RECEIPT', 'not bound to the current receipt')):
            (root / 'session.json').write_text(json.dumps(json.loads(saved) | change))
            session_lane = self.session()['authority_kind']
            refused(code, sentence)
            (root / 'session.json').write_bytes(saved)
        session_lane = 'demo_direct'
        backups = agent.state_root / 'backups'
        held = backups.with_name('backups-held'); backups.rename(held)
        refused('RESTORE_NO_BACKUP', 'No retained customer-lane backup')
        held.rename(backups)
        (root / 'research-authority.json').write_text('{}')
        refused('RESTORE_RESEARCH_BOUND', 'typed research continuation')
        (root / 'research-authority.json').unlink()
        store = root / 'studio.sqlite'
        store.rename(store.with_suffix('.held'))
        store.write_bytes(b'not a database at all' * 100)
        refused('RESTORE_STORE_UNREADABLE', 'Controller store unreadable')
        store.unlink()
        StudioStore(store).close()
        refused('RESTORE_NO_CUSTOMER_AUTHORITY', 'no customer-lane authority')
        store.unlink(); store.with_suffix('.held').rename(store)
        log = agent.state_root / 'actions.jsonl'
        kept = log.read_bytes()
        log.write_bytes(kept + b'{torn\n')
        refused('RESTORE_ACTION_LOG_UNREADABLE', 'Demo action log unreadable')
        log.write_bytes(kept)
        self.drop_identity_rows()
        refused('RESTORE_NO_INSTALL_RECORD', 'No retained install-build record for this session')
        self.legacy_only_backups()
        self.f.binary.write_bytes(b'not-the-receipt-ea')
        refused('RESTORE_EA_DIFFERS_FROM_RECEIPT', 'installed EA differs from the receipt')
        self.f.binary.write_bytes(b'new-ea')
        log.write_bytes(kept)
        agent._append('seed_promote', 'promoted', batch_id='owner-seed')
        with self.assertRaises(Refusal) as work:
            agent.restore_lane()
        self.assertEqual(work.exception.fields, dict(operations=['seed_promote'], moved_by='app_update'))
        refused('RESTORE_OWNER_DEMO_WORK', 'owner demo-lane work')
        log.write_bytes(kept)
        agent._append('studio_run_batch', 'driver_started', batch_id='owner-batch')
        refused('RESTORE_BATCH_NOT_PROVEN_NEVER_STARTED', 'Batch owner-batch is not proven never-started')
        code, error = self.cli('restore-lane')
        self.assertEqual((code, error['code'], error['refusal_code'], error['batch_id'], error['moved_by']),
                         (1, 'REFUSED', 'RESTORE_BATCH_NOT_PROVEN_NEVER_STARTED', 'owner-batch', 'app_update'))
        self.assertTrue(error['error'].startswith('Batch owner-batch is not proven never-started (no retired-unactivated'))
        log.write_bytes(kept)
        stop = agent.state_root / 'STOP'; stop.write_text('{"actor":"demo_agent"}')
        refused('RESTORE_OWNER_STOP', 'Owner STOP is set; restore-lane changes nothing')
        stop.unlink()
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        with closing(sqlite3.connect(store)) as db, db:
            before = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
            db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', (binding, json.dumps([dict(job_id='live-batch', status='running')])))
        refused('RESTORE_ACTIVE_BATCH', 'Batch live-batch is active; restore-lane waits for it to finish')
        with closing(sqlite3.connect(store)) as db, db:
            if before is None:
                db.execute('DELETE FROM studio_queues WHERE binding=?', (binding,))
            else:
                db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', (binding, before[0]))
        workers = agent.state_root / 'workers'; workers.mkdir(exist_ok=True)
        (workers / 'w.json').write_text('{}')
        with patch.object(agent, '_worker_alive', return_value=True):
            refused('RESTORE_LIVE_DRIVER', 'A live demo batch driver owns this terminal')
        (workers / 'w.json').unlink()
        with patch.object(agent, '_active_seed', return_value=dict(batch_id='hunt')):
            refused('RESTORE_SEED_RUNNING', 'A seed or catch-up run holds this terminal')
        self.assertEqual(agent.restore_lane()['status'], 'ready_to_restore')
        log.write_bytes(b'')
        self.enrolled_by_owner()
        refused('RESTORE_OWNER_ENROLLED', 'without --owner-confirmed')
        self.assertEqual(seen, RESTORE_REFUSAL_CODES)

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
        # A batch step is accepted only for a batch proven never started (test_demo_settle_refused_start).
        with self.assertRaisesRegex(ValueError, 'Batch owner-batch is not proven never-started'):
            self.f.agent.restore_lane(apply=True)
        self.f.agent._append('seed_promote', 'promoted', batch_id='owner-seed')
        with self.assertRaisesRegex(ValueError, 'owner demo-lane work \\(seed_promote\\)'):
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

    def test_a_legacy_backup_never_restores_with_a_non_customer_store_authority(self):
        self.flipped_by_old_update()
        self.legacy_only_backups()
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        store = self.f.root / 'studio.sqlite'
        store.rename(store.with_suffix('.held'))
        StudioStore(store).close()   # authorities are immutable: a fresh store holding another kind for this binding
        with closing(sqlite3.connect(store)) as db, db:
            db.execute('INSERT INTO studio_authorities VALUES(?,?,?)',
                       (binding, 'demo_direct', json.dumps(dict(kind='demo_direct', binding=json.loads(binding)))))
        with self.assertRaisesRegex(ValueError, 'no customer-lane authority'):
            self.f.agent.restore_lane(apply=True)
        self.assertEqual(self.session()['authority_kind'], 'demo_direct')

    def drop_identity_rows(self):
        log = self.f.agent.state_root / 'actions.jsonl'
        rows = [line for line in log.read_text(encoding='utf-8').splitlines()
                if line.strip() and not (json.loads(line).get('operation') == 'install_build'
                                         and json.loads(line).get('phase') == 'local_identity_verified')]
        log.write_text(''.join(row + '\n' for row in rows), encoding='utf-8')

    def test_a_legacy_session_without_an_identity_row_restores_only_when_the_installed_ea_matches(self):
        self.flipped_by_old_update()
        self.legacy_only_backups()
        self.drop_identity_rows()
        preview = self.f.agent.restore_lane()
        self.assertEqual((preview['status'], preview['evidence_kind']),
                         ('ready_to_restore', 'legacy-session-without-authority-kind-or-identity-row'))
        self.f.binary.write_bytes(b'not-the-receipt-ea')
        with self.assertRaisesRegex(ValueError, 'installed EA differs from the receipt'):
            self.f.agent.restore_lane()

    def test_a_customer_backup_without_an_identity_row_still_refuses(self):
        self.flipped_by_old_update()
        self.drop_identity_rows()
        with self.assertRaisesRegex(ValueError, 'No retained install-build record'):
            self.f.agent.restore_lane()

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
