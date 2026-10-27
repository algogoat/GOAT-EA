"""A setup registration retained from another build (goatai#1885, T3 under B39 -> B41). Fixture-only.

deploy-load closes MT5 through the EA's inert shutdown, which first registers the current build
in Common Files\\GOAT\\AgentSetup\\<data folder>. An expired registration from another build
(and its unanswered pairing request) is archived by rename, never deleted, and recorded as
superseded with its sha256; a live one still refuses. A refusal never leaves a close journal.
No MT5 terminal is touched: the fake EA and process come from test_studio_agent_setup.
"""
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_agent_mailbox as mailbox
import studio_agent_setup as agent_setup
import studio_demo_deploy as deploy
from studio_refusal import Refusal
import test_studio_agent_setup as setup_tests

BUILD = setup_tests.BUILD          # build B, the one being deployed
OLD_BUILD = 'V1.49-BETA17-39'      # build A, which paired on this terminal earlier
DEPLOYMENT = 'e' * 32
CLOSE_ID = 'deploy-' + DEPLOYMENT[:24]
REFUSED = 'different GOAT setup registration is retained'


class BuildBEA(setup_tests.FakeEA):
    """The installed build B. Like the real EA it answers only envelopes for its own build ID,
    so build A's retained request is never answered here."""

    def serve_setup(self):
        request = mailbox.setup_root(self.c) / 'request.json'
        if request.exists() and json.loads(request.read_text()).get('buildId') == BUILD:
            super().serve_setup()


class SetupRegistrationTests(unittest.TestCase):
    # The same fixture as AgentSetupTests, without inheriting (and re-running) its tests.
    setUp = setup_tests.AgentSetupTests.setUp
    tearDown = setup_tests.AgentSetupTests.tearDown
    plan = setup_tests.AgentSetupTests.plan
    relaunch = setup_tests.AgentSetupTests.relaunch

    def start_ea(self, **options):
        self.ea = BuildBEA(self.c, **options)
        self.ea.on_shutdown = lambda: setattr(self.process, 'identity', None)
        self.ea.start()
        return self.ea

    def old_ident(self):
        return dict(self.ident, buildId=OLD_BUILD)

    def root(self):
        return mailbox.setup_root(self.c)

    def pair_on_old_build(self, *, seconds_ago=3600):
        """Build A registers a pairing read and asks once; nobody answers (the T3 state).

        The mailbox clock is moved back, so both files are as old as on T3 when they are read now.
        """
        past = time.time() - seconds_ago
        clock = SimpleNamespace(time=lambda: past, monotonic=time.monotonic, sleep=time.sleep)
        with patch.object(mailbox, 'time', clock):
            mailbox.setup_register(self.c, self.old_ident(), allow_pairing=True)
            answer = mailbox.setup_request(self.c, self.old_ident(), 'pairing', timeout=1)
        self.assertEqual(answer['result'], 'receipt_timeout')
        return answer['id']

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.root().iterdir()}

    def close_journal(self):
        return Path(self.c.root) / 'terminal-closes' / (CLOSE_ID + '.json')

    def assert_refused_without_trace(self, before, message=REFUSED):
        with self.relaunch() as launch, self.assertRaisesRegex(ValueError, message):
            deploy.load(self.c, self.plan(), mt5=setup_tests.FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()
        self.assertFalse(self.close_journal().exists(), 'a refused registration leaves no phantom close_intent')
        self.assertEqual(self.snapshot(), before, 'the retained registration and request are untouched')
        self.assertEqual((self.ea.shutdowns, self.process.closed), (0, []))
        self.assertIsNotNone(self.process.identity, 'MT5 keeps running')

    # -------------------------------------------------------------- replaceable

    def test_deploy_on_build_b_archives_an_expired_build_a_registration_and_records_its_sha(self):
        request_id = self.pair_on_old_build()
        registration = (self.root() / 'registration.json').read_bytes()
        request = (self.root() / 'request.json').read_bytes()
        digest = hashlib.sha256(registration).hexdigest()
        self.assertEqual(json.loads(registration)['buildId'], OLD_BUILD)
        ea = self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=setup_tests.FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(ea.shutdowns, 1, 'MT5 closed through the EA inert shutdown under build B')
        journal = json.loads(self.close_journal().read_text())
        self.assertEqual((journal['phase'], journal['method']), ('stopped', 'ea_inert_shutdown'))
        superseded = journal['superseded_registration']
        self.assertEqual((superseded['sha256'], superseded['buildId'], superseded['archivedAs']),
                         (digest, OLD_BUILD, digest + '.expired.registration.json'))
        # Archived by rename, byte for byte, in the controller's expired naming; nothing deleted.
        self.assertEqual((self.root() / superseded['archivedAs']).read_bytes(), registration)
        self.assertEqual((self.root() / (request_id + '.expired.request.json')).read_bytes(), request)
        self.assertEqual(json.loads((self.root() / 'registration.json').read_text())['buildId'], BUILD)

    def test_close_terminal_returns_the_superseded_registration(self):
        self.pair_on_old_build()
        digest = hashlib.sha256((self.root() / 'registration.json').read_bytes()).hexdigest()
        self.start_ea(pairing='none')
        result = agent_setup.close_terminal(self.c, 'close-b', build_id=BUILD)
        self.assertEqual((result['phase'], result['superseded_registration']['sha256']), ('stopped', digest))

    def test_pairing_code_on_build_b_reports_the_superseded_registration(self):
        request_id = self.pair_on_old_build()
        registration = (self.root() / 'registration.json').read_bytes()
        digest = hashlib.sha256(registration).hexdigest()
        old = json.loads(registration)
        expected = dict(sha256=digest, buildId=OLD_BUILD, account=old['account'], server=old['server'],
                        expiresAtUtc=old['expiresAtUtc'], archivedAs=digest + '.expired.registration.json')
        self.start_ea()
        result = agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c))
        self.assertEqual((result['status'], result['source'], result['buildId']), ('pairing_available', 'setup_mailbox', BUILD))
        self.assertEqual(result['supersededRegistration'], expected)
        self.assertEqual((self.root() / expected['archivedAs']).read_bytes(), registration)
        self.assertTrue((self.root() / (request_id + '.expired.request.json')).exists())
        # The next read on build B supersedes nothing, so the key is absent, as before #184.
        self.assertNotIn('supersededRegistration', agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c)))

    def test_pairing_code_reports_the_supersession_when_no_ea_answers(self):
        self.pair_on_old_build()
        digest = hashlib.sha256((self.root() / 'registration.json').read_bytes()).hexdigest()
        result = agent_setup.pairing_code(self.c, BUILD, timeout=1, mt5=setup_tests.FakeMT5(self.c))
        self.assertEqual(result['status'], 'no_native_answer')
        self.assertEqual((result['supersededRegistration']['sha256'], result['supersededRegistration']['buildId']), (digest, OLD_BUILD))

    def superseded_expected(self):
        registration = (self.root() / 'registration.json').read_bytes()
        digest, old = hashlib.sha256(registration).hexdigest(), json.loads(registration)
        return dict(sha256=digest, buildId=OLD_BUILD, account=old['account'], server=old['server'],
                    expiresAtUtc=old['expiresAtUtc'], archivedAs=digest + '.expired.registration.json')

    def test_a_pairing_refusal_after_superseding_carries_it_as_a_structured_field(self):
        self.pair_on_old_build()
        expected = self.superseded_expected()
        self.start_ea(algo=True)   # The EA refuses: Algo Trading is on.
        with self.assertRaises(Refusal) as caught:
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c))
        self.assertEqual((caught.exception.code, caught.exception.fields), (agent_setup.PAIRING_NOT_INERT, dict(supersededRegistration=expected)))
        self.assertEqual(str(caught.exception), 'MT5 is not inert: turn Algo Trading off and close demo positions before pairing',
                         'the sentence is unchanged; the archive is data, not text')
        self.assertTrue((self.root() / expected['archivedAs']).exists())

    def test_an_ea_or_mailbox_refusal_after_superseding_carries_it_too(self):
        self.pair_on_old_build()
        expected = self.superseded_expected()
        refused = lambda controller, ident, action, timeout: dict(id='b' * 32, result='rejected_envelope')
        with self.assertRaisesRegex(Refusal, r'refused the pairing request \(rejected_envelope\)') as caught:
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c), request=refused)
        self.assertEqual((caught.exception.code, caught.exception.fields), (agent_setup.PAIRING_EA_REFUSED, dict(supersededRegistration=expected)))
        # A later failure on build B supersedes nothing new: a plain refusal without the field.
        with self.assertRaises(Refusal) as caught:
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c), request=refused)
        self.assertEqual(caught.exception.fields, {})

    def test_a_mailbox_error_is_wrapped_only_when_a_registration_was_superseded(self):
        def stale(controller, ident, action, timeout):
            raise ValueError('Stale pairing payload')
        self.pair_on_old_build()
        expected = self.superseded_expected()
        with self.assertRaisesRegex(Refusal, '^Stale pairing payload$') as caught:
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c), request=stale)
        self.assertEqual((caught.exception.code, caught.exception.fields), (agent_setup.PAIRING_MAILBOX_REFUSED, dict(supersededRegistration=expected)))
        with self.assertRaisesRegex(ValueError, '^Stale pairing payload$') as caught:
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c), request=stale)
        self.assertNotIsInstance(caught.exception, Refusal, 'without a supersession the error is unchanged')

    def test_the_cli_emits_the_supersession_beside_the_unchanged_refusal_sentence(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from goat_studio import main
        self.pair_on_old_build()
        expected = self.superseded_expected()
        self.start_ea(algo=True)
        real = agent_setup.pairing_code
        self.c.store.close(); self.c.store = None
        output = StringIO()
        with patch.object(agent_setup, 'pairing_code', lambda controller, build_id: real(controller, build_id, mt5=setup_tests.FakeMT5(controller))), \
             redirect_stdout(output):
            code = main(['--installation', str(self.fixture.path), 'pairing-code', '--build-id', BUILD])
        reply = json.loads(output.getvalue())
        self.assertEqual((code, reply['ok'], reply['refusal_code'], reply['supersededRegistration']),
                         (2, False, agent_setup.PAIRING_NOT_INERT, expected))
        self.assertTrue(reply['error'].startswith('MT5 is not inert'))
        self.assertNotIn(expected['sha256'], reply['error'])

    def test_pairing_code_refuses_a_live_build_a_registration(self):
        mailbox.setup_register(self.c, self.old_ident(), allow_pairing=True)
        before = self.snapshot()
        self.start_ea()
        with self.assertRaisesRegex(ValueError, REFUSED):
            agent_setup.pairing_code(self.c, BUILD, mt5=setup_tests.FakeMT5(self.c))
        self.assertEqual(self.snapshot(), before)

    def test_the_same_build_reregisters_without_superseding(self):
        record, superseded = mailbox.setup_register(self.c, self.ident)
        self.assertIsNone(superseded)
        self.assertEqual(mailbox.setup_register(self.c, self.ident)[1], None)
        self.assertEqual(sorted(path.name for path in self.root().iterdir()), ['registration.json'])
        self.assertEqual(record['buildId'], BUILD)

    # ------------------------------------------------------------------ refused

    def test_a_live_registration_from_build_a_still_refuses_and_writes_no_close_journal(self):
        mailbox.setup_register(self.c, self.old_ident(), allow_pairing=True)
        self.start_ea(pairing='none')
        self.assert_refused_without_trace(self.snapshot())

    def test_close_terminal_refuses_a_live_foreign_registration_before_journaling(self):
        mailbox.setup_register(self.c, self.old_ident())
        self.start_ea(pairing='none')
        with self.assertRaisesRegex(ValueError, REFUSED):
            agent_setup.close_terminal(self.c, 'close-live', build_id=BUILD)
        self.assertFalse((Path(self.c.root) / 'terminal-closes' / 'close-live.json').exists())
        with self.assertRaisesRegex(ValueError, 'build ID'):
            agent_setup.close_terminal(self.c, 'close-bad-build', build_id='x')
        self.assertFalse((Path(self.c.root) / 'terminal-closes' / 'close-bad-build.json').exists())
        self.assertEqual(self.process.closed, [])

    def test_a_registration_inside_the_expiry_grace_still_refuses(self):
        self.pair_on_old_build(seconds_ago=mailbox.PAIRING_REGISTRATION_SECONDS + 2)
        self.start_ea(pairing='none')
        self.assert_refused_without_trace(self.snapshot())

    def test_an_expired_registration_whose_request_is_still_live_refuses(self):
        self.pair_on_old_build()
        old = self.old_ident()
        mailbox.atomic(self.root() / 'request.json', dict(schema=1, id='d' * 32, account=old['account'], server=old['server'],
                                                          directory=old['directory'], buildId=OLD_BUILD,
                                                          expiresAtUtc=int(time.time()) + 60, action='status'))
        self.start_ea(pairing='none')
        self.assert_refused_without_trace(self.snapshot(), 'still live')

    def test_an_expired_registration_without_an_expiry_or_identity_refuses(self):
        old = self.old_ident()
        self.root().mkdir(parents=True)
        for value, message in ((dict(schema=1, account=old['account'], server=old['server'], directory=old['directory'], buildId=OLD_BUILD), REFUSED),
                               (dict(schema=1, account=old['account'], server=old['server'], directory=old['directory'], buildId=OLD_BUILD,
                                     expiresAtUtc=str(int(time.time()) - 3600)), REFUSED),
                               (dict(schema=1, buildId=OLD_BUILD, expiresAtUtc=int(time.time()) - 3600), 'malformed')):
            with self.subTest(value=value):
                mailbox.atomic(self.root() / 'registration.json', value)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, message):
                    mailbox.setup_register(self.c, self.ident)
                self.assertEqual(self.snapshot(), before)

    def test_an_existing_archive_or_a_changed_registration_is_never_overwritten(self):
        self.pair_on_old_build()
        path = self.root() / 'registration.json'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root() / (digest + '.expired.registration.json')).write_bytes(b'earlier archive')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'archive already exists'):
            mailbox.setup_register(self.c, self.ident)
        self.assertEqual(self.snapshot(), before, 'nothing is renamed or overwritten, the old request included')
        with self.assertRaisesRegex(ValueError, 'changed while it was inspected'):
            mailbox._supersede_expired(self.root(), path, 'f' * 64, int(time.time()))
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
