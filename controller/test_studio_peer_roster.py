"""GOAT peers: peer-add, auto-recognised GOAT terminals and the unmapped refusal (goatai#1885).

Fixture terminals only: every process inventory and Authenticode result is
supplied by the test, and no MT5 is started, stopped, read or written.

Incident (2026-10-05): opening Terminal 3 blocked Banker, and the reviewed
protected peer (policy.json) holds only T2. These tests prove that another
GOAT-owned terminal no longer blocks, that unknown terminals still do, and that
the reviewed peer, every prepared package and the one-namespace rule are
untouched.
"""
import contextlib
import hashlib
import io
import json
import re
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import sha
from studio_batch import prepare_batch, _verify_package
from studio_process_check import classify_processes, inspect_processes
from studio_protected_peer import directory, material, policy, refresh_process, target
import studio_peer_roster as roster
from test_studio_fast_lane import synthetic

METAQUOTES = dict(status='Valid', subject='CN=MetaQuotes Ltd., O=MetaQuotes Ltd., S=Lemesos, C=CY',
                  thumbprint='5A64A7AED24C33DED342D01D01FA5286F06DA6DC')


class RosterFixture(unittest.TestCase):
    version = '1.49'

    def setUp(self):
        self.f = fixtures.PortableControllerTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.c = self.f.bound()
        self.c.install = dict(self.c.install, ea_version=self.version)
        self.appdata = self.f.root / 'appdata'
        self.suite = self.f.root / 'suite'; self.suite.mkdir()
        self.research = dict(ProcessId=5000, ExecutablePath=str(self.f.bin), CreatedUtc='2026-10-05T01:00:00.0000000Z',
                             Name='terminal64.exe')
        self.rows = [self.research]
        self.signer = dict(METAQUOTES)
        self.signed = []
        inventory = lambda *a, **k: json.dumps(self.rows)
        for name, value in (('studio_process_check.subprocess.check_output', dict(side_effect=inventory)),
                            ('studio_peer_roster.suite_root', dict(return_value=self.suite)),
                            ('studio_peer_roster.signature', dict(side_effect=self.signature))):
            p = patch(name, **value); p.start(); self.addCleanup(p.stop)

    def signature(self, executable):
        self.signed.append(str(executable))
        return dict(self.signer)

    def terminal(self, name, *, folder_hash=None, utf16=True):
        """An installed MT5: program folder and an AppData data folder whose origin.txt names it."""
        exe = self.f.root / name / 'terminal64.exe'; exe.parent.mkdir(); exe.write_bytes(b'mt5 ' + name.encode())
        data = self.appdata / 'MetaQuotes/Terminal' / (folder_hash or hashlib.md5(name.encode()).hexdigest().upper())
        (data / 'MQL5').mkdir(parents=True)
        text = str(exe.parent)
        (data / 'origin.txt').write_bytes(text.encode('utf-16') if utf16 else text.encode('utf-8'))
        return exe, data

    def receipt(self, exe, data, folder_id='1ce0354662e44e997a61', **changes):
        folder = self.suite / folder_id; folder.mkdir()
        value = dict(schema_version=1, controller_version='1.49-beta.1', ea_version='1.49',
                     terminal_executable=str(exe), terminal_data_root=str(data),
                     common_files_root=str(self.f.common), ea_relative_path='GOAT-EA\\GOAT V1.49.ex5',
                     ea_sha256='d' * 64, controller_state_root=str(folder), terminal_portable=False) | changes
        (folder / 'installation.json').write_text(json.dumps(value), encoding='utf-8')
        return folder / 'installation.json'

    def row(self, exe, pid, created='2026-10-05T02:00:00.0000000Z'):
        return dict(ProcessId=pid, ExecutablePath=str(exe), CreatedUtc=created, Name='terminal64.exe')

    def inspect(self, research_running=True):
        return inspect_processes(self.c.binding(), research_running=research_running)

    def folder(self):
        return roster.policy_folder(self.c.install['terminal_data_root'])

    def journal(self):
        return roster.journal_rows(self.folder())

    def write_reviewed_policy(self, exe, data, pid=39264):
        """A real-shaped single-peer policy.json, as Banker's (review 47a5519c...) on 2026-10-05."""
        folder = directory(self.c); folder.mkdir(parents=True, exist_ok=True)
        review_id = '47a5519caea14238ac13325e49e6f1c0'
        value = dict(schema_version=1, review_id=review_id, target=target(self.c), peer=material(self.c, exe, data),
                     process=dict(pid=pid, executable=str(exe), created_utc='2026-10-03T04:07:15.0264070Z'))
        (folder / 'policy.json').write_text(json.dumps(value), encoding='utf-8')
        (folder / (review_id + '.json')).write_text(json.dumps(value | dict(status='review', expires_at=1.0,
                                                                            previous_sha256=None)), encoding='utf-8')
        line = dict(schema_version=1, event='peer_restart_accepted', rule='same_executable_data_root_origin_isolated_namespace_v1',
                    review_id=review_id, peer_sha256=sha(value['peer']), executable=str(exe), data_root=str(data),
                    previous_pid=pid, pid=49180, previous_process=value['process'],
                    process=dict(pid=49180, executable=str(exe), created_utc='2026-10-04T01:01:30.8941980Z'),
                    recorded_utc='2026-10-04T14:06:40+00:00', source='refresh_process')
        (folder / 'peer-instances.jsonl').write_text(json.dumps(line, sort_keys=True) + '\n', encoding='utf-8')
        (folder / 'launch.lock').write_bytes(b'')
        return value


class PeerAddTests(RosterFixture):
    def test_peer_add_while_the_peer_is_stopped_previews_then_records(self):
        exe, data = self.terminal('Terminal 4 - Manual')
        binding = self.c.binding()
        preview = roster.add(self.c, exe, data)
        self.assertEqual(preview['status'], 'preview')
        held = preview['held_to']
        from studio_terminal_isolation import terminal_hash
        self.assertEqual(held['namespace_hash'], terminal_hash(str(data)))
        self.assertNotEqual(held['namespace_hash'], held['own_namespace_hash'])
        self.assertIn('origin.txt names ' + str(exe.parent), held['origin_binding'])
        self.assertEqual(held['signer'], 'MetaQuotes Ltd.')
        self.assertFalse((self.folder() / roster.ROSTER).exists())
        added = roster.add(self.c, exe, data, confirmed=True)
        self.assertEqual(added['status'], 'peer_added')
        self.assertEqual(added['peer']['source'], 'user_reviewed')
        self.assertEqual(added['peer']['executable_sha256_at_add'], hashlib.sha256(exe.read_bytes()).hexdigest())
        [receipt] = self.journal()
        self.assertEqual((receipt['event'], receipt['peer']['peer_id']), ('peer_added', added['peer']['peer_id']))
        self.assertEqual(receipt['roster_sha256_after'], sha(roster.read_roster(self.folder(), roster.controller_lane(self.c))))
        self.assertEqual(roster.add(self.c, exe, data, confirmed=True)['status'], 'unchanged')
        self.assertEqual(len(self.journal()), 1)
        self.assertEqual(self.c.binding(), binding)          # no package identity moves
        self.rows = [self.research, self.row(exe, 7001)]
        seen = self.inspect()
        self.assertEqual([(p['executable'], p['pid']) for p in seen['peers']], [(str(exe), 7001)])
        self.assertIsNone(seen['protected'])

    def test_peer_add_takes_the_data_folder_from_a_goat_receipt(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        path = self.receipt(exe, data)
        added = roster.add(self.c, exe, confirmed=True)
        self.assertEqual((added['peer']['source'], added['peer']['receipt_path']), ('goat_receipt', str(path)))
        other = self.appdata / 'elsewhere'; (other / 'MQL5').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'One peer has one data folder'):
            roster.add(self.c, exe, other)

    def test_peer_add_needs_a_data_folder_without_a_receipt(self):
        exe, _ = self.terminal('Terminal 4 - Manual')
        with self.assertRaisesRegex(ValueError, 'Give its data folder with --data-root'):
            roster.add(self.c, exe)
        with self.assertRaisesRegex(ValueError, 'full terminal64.exe path'):
            roster.add(self.c, exe.parent)

    def test_peer_add_refuses_this_terminal_and_overlaps(self):
        with self.assertRaisesRegex(ValueError, 'Cannot add'):
            roster.add(self.c, self.f.bin, self.c.install['terminal_data_root'])


class AutoRecognitionTests(RosterFixture):
    def test_a_goat_installed_terminal_never_blocks_and_nothing_is_written(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        seen = self.inspect()
        self.assertEqual(seen['peers'][0]['data_root'], str(data))
        self.assertEqual(self.signed, [str(exe)])
        self.assertFalse(self.folder().exists())               # a read-only check

    def test_unknown_terminal_is_still_refused(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003), self.row('C:/Other MT5/terminal64.exe', 9000)]
        with self.assertRaisesRegex(ValueError, r'^Unmapped terminal process requires ownership inspection: '
                                                r'C:\\Other MT5\\terminal64.exe \(PID 9000\) is not this terminal, its '
                                                r'reviewed peer or one of its GOAT peers.*peer-add'):
            self.inspect()
        self.assertEqual(self.signed, [str(exe)])

    def test_two_processes_of_one_peer_refuse(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003), self.row(exe, 7004)]
        with self.assertRaisesRegex(ValueError, 'Two processes of one GOAT peer'):
            self.inspect()

    def test_copied_or_foreign_receipts_are_not_trusted(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        path = self.receipt(exe, data, controller_state_root=str(self.f.root / 'somewhere else'))
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, 'Unmapped terminal process'):
            self.inspect()
        listed = roster.listing(self.c, inventory=False)
        self.assertEqual(listed['skipped_receipts'][0]['receipt_path'], str(path))
        self.assertIn('copied receipt', listed['skipped_receipts'][0]['reason'])

    def test_this_terminals_own_receipt_is_not_a_peer(self):
        self.receipt(self.f.bin, self.c.install['terminal_data_root'])
        self.assertEqual(roster.receipts(roster.controller_lane(self.c))[0], [])

    def test_a_portable_peer_is_bound_by_its_own_folder(self):
        exe = self.f.root / 'Portable MT5' / 'terminal64.exe'; exe.parent.mkdir(); exe.write_bytes(b'mt5')
        (exe.parent / 'MQL5').mkdir()
        self.receipt(exe, exe.parent, terminal_portable=True)
        self.rows = [self.research, self.row(exe, 7010)]
        self.assertEqual(self.inspect()['peers'][0]['data_root'], str(exe.parent))


class SafetyTests(RosterFixture):
    def test_same_namespace_peer_is_refused_by_the_roster_and_by_isolation(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        with patch('studio_terminal_isolation.terminal_hash', return_value='0badf00d'):
            with self.assertRaisesRegex(ValueError, "this terminal's batch namespace"):
                self.inspect()
            with self.assertRaisesRegex(ValueError, "batch namespace"):
                roster.add(self.c, exe, confirmed=True)
            # Peers never relax the one-namespace rule: preflight still refuses at every native start.
            from studio_terminal_isolation import preflight
            own = self.appdata / 'MetaQuotes/Terminal/OWN'; (own / 'MQL5').mkdir(parents=True)
            binding = dict(self.c.binding(), research_data_root=str(own))
            with self.assertRaisesRegex(ValueError, "resolves to this terminal's batch folder"):
                preflight(binding, dict(login='123456', server='Customer-Demo'),
                          processes=[dict(ProcessId=5000, ExecutablePath=str(self.f.bin)),
                                     dict(ProcessId=7003, ExecutablePath=str(exe))], appdata=self.appdata)

    def test_a_peer_inside_this_terminals_folders_is_refused(self):
        exe = self.f.root / 'Terminal 5' / 'terminal64.exe'; exe.parent.mkdir(); exe.write_bytes(b'mt5')
        for data in (self.f.common / 'T5DATA', self.c.root / 'T5DATA'):
            with self.subTest(data=str(data)):
                (data / 'MQL5').mkdir(parents=True)
                (data / 'origin.txt').write_bytes(str(exe.parent).encode('utf-16'))
                with self.assertRaisesRegex(ValueError, 'overlaps this terminal'):
                    roster.add(self.c, exe, data, confirmed=True)
        self.receipt(exe, self.f.common / 'T5DATA')
        self.rows = [self.research, self.row(exe, 7005)]
        with self.assertRaisesRegex(ValueError, 'overlaps this terminal'):
            self.inspect()

    def test_a_failed_signature_refuses_and_names_the_signer(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        self.signer = dict(status='Valid', subject='CN=Broker Build, O=Broker Build Ltd, C=XX', thumbprint='AB')
        message = re.escape('terminal64.exe at ' + str(exe) + ' is signed by Broker Build Ltd, not MetaQuotes Ltd.')
        with self.assertRaisesRegex(ValueError, message):
            self.inspect()
        with self.assertRaisesRegex(ValueError, message):
            roster.add(self.c, exe, confirmed=True)
        self.signer = dict(status='NotSigned', subject='', thumbprint='')
        with self.assertRaisesRegex(ValueError, re.escape('is not signed (Authenticode NotSigned), not by MetaQuotes Ltd.')):
            self.inspect()
        self.signer = dict(METAQUOTES, status='HashMismatch')
        with self.assertRaisesRegex(ValueError, re.escape('carries a MetaQuotes Ltd. signature that Windows does not '
                                                          'accept (Authenticode HashMismatch)')):
            self.inspect()
        self.assertFalse((self.folder() / roster.ROSTER).exists())

    def test_signer_organisation_parsing(self):
        self.assertTrue(roster.signer_ok(METAQUOTES))
        self.assertTrue(roster.signer_ok(dict(status='Valid', subject='O=MetaQuotes Software Corp., C=CY')))
        for subject in ('CN=MetaQuotes Ltd.', 'O=MetaQuotes Ltd. Fake, C=CY', 'O="MetaQuotes Ltd., Fake"', ''):
            with self.subTest(subject=subject):
                self.assertFalse(roster.signer_ok(dict(status='Valid', subject=subject)))

    def test_a_lane_without_isolation_has_no_goat_peers(self):
        self.c.install = dict(self.c.install, ea_version='1.48')
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, 'is not the selected terminal or its reviewed peer'):
            self.inspect()
        with self.assertRaisesRegex(ValueError, 'GOAT peers need this terminal on GOAT EA V1.49'):
            roster.add(self.c, exe, confirmed=True)
        self.assertEqual(self.signed, [])

    def test_classify_without_a_lookup_keeps_the_historical_refusal(self):
        rows = [self.research, self.row('C:/Other MT5/terminal64.exe', 9000)]
        with self.assertRaisesRegex(ValueError, r'^Unmapped terminal process requires ownership inspection: '):
            classify_processes(rows, self.c.binding(), observed_unix=1)


class RemovalAndMovesTests(RosterFixture):
    def test_peer_remove_blocks_again_and_excludes_auto_recognition(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        self.inspect()
        preview = roster.remove(self.c, exe)
        self.assertEqual(preview['status'], 'preview')
        self.inspect()                                          # a preview changes nothing
        removed = roster.remove(self.c, exe, confirmed=True)
        self.assertEqual(removed['status'], 'peer_removed')
        self.assertEqual(self.journal()[-1]['event'], 'peer_removed')
        with self.assertRaisesRegex(ValueError, "was removed from this terminal's GOAT peers"):
            self.inspect()
        self.assertEqual(roster.remove(self.c, exe, confirmed=True)['status'], 'unchanged')
        readded = roster.add(self.c, exe, confirmed=True)
        self.assertEqual(self.journal()[-1]['readmitted'][0]['executable'], str(exe))
        self.assertEqual(readded['status'], 'peer_added')
        self.inspect()

    def test_peer_remove_of_an_added_peer(self):
        exe, data = self.terminal('Terminal 4 - Manual')
        roster.add(self.c, exe, data, confirmed=True)
        roster.remove(self.c, exe, confirmed=True)
        value = roster.read_roster(self.folder(), roster.controller_lane(self.c))
        self.assertEqual((value['peers'], value['excluded'][0]['executable']), ([], str(exe)))
        with self.assertRaisesRegex(ValueError, 'is not a GOAT peer of this terminal'):
            roster.remove(self.c, self.f.root / 'never/terminal64.exe', confirmed=True)

    def test_a_receipt_pointing_at_a_moved_data_folder_refuses_plainly(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        (data / 'origin.txt').write_bytes('D:\\Moved MT5'.encode('utf-16'))   # MT5 moved; the receipt did not follow
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, r'is recorded with data folder .* but .*origin.txt names D:\\Moved MT5, '
                                                r'not .*If MT5 moved or was reinstalled'):
            self.inspect()
        (data / 'origin.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'has no origin.txt binding it to'):
            self.inspect()
        listed = roster.listing(self.c, inventory=False)
        self.assertFalse(listed['peers'][0]['eligible'])

    def test_a_data_folder_without_mql5_is_not_a_terminal_data_folder(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        (data / 'MQL5').rmdir()
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, 'has no MQL5 folder'):
            self.inspect()
        with self.assertRaisesRegex(ValueError, 'has no MQL5 folder'):
            roster.add(self.c, exe, confirmed=True)

    def test_records_that_disagree_on_the_data_folder_refuse(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        roster.add(self.c, exe, data, confirmed=True)             # before GOAT installed it
        moved = self.appdata / 'MetaQuotes/Terminal/NEWFOLDER'; (moved / 'MQL5').mkdir(parents=True)
        (moved / 'origin.txt').write_bytes(str(exe.parent).encode('utf-16'))
        self.receipt(exe, moved)                                  # GOAT now names another folder
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, 'is named with different data folders by its GOAT records'):
            self.inspect()

    def test_an_unreadable_roster_refuses_only_a_non_mapped_terminal(self):
        self.folder().mkdir(parents=True)
        (self.folder() / roster.ROSTER).write_text('{"schema_version": 2}', encoding='utf-8')
        self.inspect()                                           # nothing else running: no read, no refusal
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research, self.row(exe, 7003)]
        with self.assertRaisesRegex(ValueError, 'cannot be checked as a GOAT peer: GOAT peer roster .* not recognised'):
            self.inspect()


class OwnerStopTests(RosterFixture):
    """Amendment B (#1885): owner STOP blocks peer-add and peer-remove; peer-list stays allowed."""

    def test_owner_stop_refuses_add_and_remove_and_allows_list(self):
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        stop = self.c.root / 'demo-agent' / 'STOP'; stop.parent.mkdir(parents=True); stop.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Owner STOP is on'):
            roster.add(self.c, exe, confirmed=True)
        with self.assertRaisesRegex(ValueError, 'Owner STOP is on'):
            roster.add(self.c, exe)
        with self.assertRaisesRegex(ValueError, 'Owner STOP is on'):
            roster.remove(self.c, exe, confirmed=True)
        self.assertFalse((self.folder() / roster.ROSTER).exists())
        self.assertTrue(roster.listing(self.c, inventory=False)['peers'][0]['eligible'])

    def test_demo_lane_refuses_under_owner_stop_before_any_broker_or_terminal_step(self):
        from demo_agent import DemoAgent
        # The demo agent reads the receipt on disk (the compact fixture's V1.48); count it as isolated.
        with patch('studio_terminal_isolation.ISOLATED_VERSIONS', frozenset({'1.48', '1.49'})):
            exe, data = self.terminal('Terminal 3 - Tester')
            self.receipt(exe, data)
            self.rows = [self.research, self.row(exe, 7003), self.row('C:/Other MT5/terminal64.exe', 9000)]
            agent = DemoAgent(self.f.path)
            stop = agent.state_root / 'STOP'; stop.parent.mkdir(parents=True); stop.write_text('{}')
            with patch.object(DemoAgent, '_studio', side_effect=AssertionError('no broker step under STOP')):
                with self.assertRaisesRegex(ValueError, 'Owner STOP is on'):
                    agent.peer_add(exe, confirmed=True)
                with self.assertRaisesRegex(ValueError, 'Owner STOP is on'):
                    agent.peer_remove(exe, confirmed=True)
                listed = agent.peer_list()
            self.assertEqual((listed['peers'][0]['executable'], listed['peers'][0]['eligible']), (str(exe), True))
            self.assertEqual(listed['peers'][0]['running_pids'], [7003])
            [blocking] = listed['blocking']
            self.assertEqual(blocking['pid'], 9000)
            self.assertTrue(blocking['reason'].startswith('Unmapped terminal process requires ownership inspection: '))
            self.assertFalse((self.folder() / roster.ROSTER).exists())

    def test_demo_lane_peer_add_runs_inside_the_broker_verified_scope(self):
        from demo_agent import DemoAgent
        calls = []

        @contextlib.contextmanager
        def studio(agent, operation_name, *, idle, owner_required=True, job_id=None, recovery=False):
            calls.append((operation_name, idle, owner_required, job_id))
            yield self.c, dict(login='123456', server='Customer-Demo', demo=True)
        exe, data = self.terminal('Terminal 4 - Manual')
        with patch.object(DemoAgent, '_studio', studio), \
                patch.object(DemoAgent, '_exclusive', side_effect=AssertionError('no terminal lock: a driver may hold it')):
            agent = DemoAgent(self.f.path)
            added = agent.peer_add(exe, data, confirmed=True)
            removed = agent.peer_remove(exe, confirmed=True)
        self.assertEqual((added['status'], removed['status']), ('peer_added', 'peer_removed'))
        self.assertEqual(calls, [('peer-add', False, False, None), ('peer-remove', False, False, None)])
        actions = [json.loads(line) for line in (agent.state_root / 'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['operation'] for row in actions], ['peer_add', 'peer_remove'])


class MigrationTests(RosterFixture):
    """The existing single-peer policy.json (T2) keeps its exact meaning beside GOAT peers."""
    version = '1.48'   # the compact fixture schema stages V1.48 packages; isolation is patched as in peer-restart tests

    def setUp(self):
        super().setUp()
        isolated = patch('studio_terminal_isolation.ISOLATED_VERSIONS', frozenset({'1.48', '1.49'}))
        isolated.start(); self.addCleanup(isolated.stop)
        self.t2, self.t2_data = self.terminal('Terminal 2 - GOAT')
        self.receipt(self.t2, self.t2_data, folder_id='14acc214ac9f7c933a55')
        self.t3, self.t3_data = self.terminal('Terminal 3 - Tester')
        self.receipt(self.t3, self.t3_data)
        self.reviewed = self.write_reviewed_policy(self.t2, self.t2_data)
        self.f.grant(self.c)

    def snapshot(self):
        return {path.name: path.read_bytes() for path in directory(self.c).iterdir()
                if path.name not in (roster.ROSTER, roster.JOURNAL)}

    def test_real_shaped_policy_survives_peer_add_and_a_t2_restart_with_t3_running(self):
        prepare_batch(self.c, 'chunk', synthetic(self.f, self.c, 2))
        binding, files = self.c.binding(), self.snapshot()
        self.assertEqual(policy(self.c)['review_id'], self.reviewed['review_id'])
        added = roster.add(self.c, self.t3, confirmed=True)
        self.assertEqual(added['status'], 'peer_added')
        self.assertEqual(roster.add(self.c, self.t2, confirmed=True)['status'], 'already_reviewed_peer')
        with self.assertRaisesRegex(ValueError, 'reviewed peer in policy.json'):
            roster.remove(self.c, self.t2, confirmed=True)
        self.assertEqual(self.snapshot(), files)                 # policy.json, reviews, peer-instances untouched
        self.assertEqual(self.c.binding(), binding)
        _verify_package(self.c, self.c.job('chunk'))
        # Both running: T2 keeps the protected role, T3 is a GOAT peer.
        self.rows = [self.research, self.row(self.t2, 40692, '2026-10-05T04:15:09.0751800Z'), self.row(self.t3, 7003)]
        seen = self.inspect()
        self.assertEqual(seen['protected']['pid'], 40692)
        self.assertEqual([p['executable'] for p in seen['peers']], [str(self.t3)])
        # The demo `continue` path: refresh_process accepts T2's restart while T3 runs.
        refreshed = refresh_process(self.c)
        self.assertEqual(refreshed['status'], 'restart_accepted')
        lines = [json.loads(line) for line in (directory(self.c) / 'peer-instances.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([line['pid'] for line in lines], [49180, 40692])
        self.assertEqual(policy(self.c), self.reviewed)
        _verify_package(self.c, self.c.job('chunk'))
        listed = roster.listing(self.c, inventory=False)
        self.assertEqual(listed['reviewed_peer']['status'], 'protected')
        self.assertEqual({p['executable']: p['eligible'] for p in listed['peers']}, {str(self.t2): True, str(self.t3): True})

    def test_two_goat_peers_coexist_and_one_restarting_keeps_the_other(self):
        t4, t4_data = self.terminal('Terminal 4 - Manual')
        roster.add(self.c, t4, t4_data, confirmed=True)
        self.rows = [self.research, self.row(self.t3, 7003), self.row(t4, 7004)]
        first = self.inspect()
        self.assertEqual(sorted(p['pid'] for p in first['peers']), [7003, 7004])
        self.assertEqual([row['event'] for row in roster.record_seen(self.c, first['peers'], source='config_start:a')],
                         ['peer_seen', 'peer_seen'])
        self.rows = [self.research, self.row(self.t3, 7013, '2026-10-05T03:00:00Z')]   # T3 restarted, T4 closed
        second = self.inspect()
        self.assertEqual([p['pid'] for p in second['peers']], [7013])
        [row] = roster.record_seen(self.c, second['peers'], source='config_start:b')
        self.assertEqual((row['event'], row['previous_process']['pid']), ('peer_seen', 7003))
        self.assertEqual(roster.record_seen(self.c, second['peers'], source='config_start:c'), [])
        self.rows = [self.research, self.row(self.t3, 7013, '2026-10-05T03:00:00Z'), self.row(t4, 7024)]
        self.assertEqual(len(self.inspect()['peers']), 2)

    def test_an_mt5_update_is_accepted_on_its_signature_and_journaled(self):
        self.rows = [self.research, self.row(self.t3, 7003)]
        [first] = roster.record_seen(self.c, self.inspect()['peers'], source='start:a')
        before = first['executable_sha256']
        self.t3.write_bytes(b'mt5 build 5400')                    # MT5 live update: new bytes, same signer
        self.rows = [self.research, self.row(self.t3, 7033, '2026-10-05T05:00:00Z')]
        [row] = roster.record_seen(self.c, self.inspect()['peers'], source='start:b')
        self.assertEqual(row['event'], 'peer_binary_changed')
        self.assertEqual((row['previous_executable_sha256'], row['executable_sha256']),
                         (before, hashlib.sha256(b'mt5 build 5400').hexdigest()))
        self.assertEqual(row['signer']['subject'], METAQUOTES['subject'])
        # The reviewed policy.json peer keeps its strict executable-bytes identity.
        self.t2.write_bytes(b'mt5 build 5400 on T2')
        with self.assertRaisesRegex(ValueError, 'changed; review again'):
            self.c.binding()


class CommandLineTests(RosterFixture):
    def setUp(self):
        super().setUp()
        # The CLI reads the receipt on disk (the compact fixture's V1.48); count it as isolated.
        isolated = patch('studio_terminal_isolation.ISOLATED_VERSIONS', frozenset({'1.48', '1.49'}))
        isolated.start(); self.addCleanup(isolated.stop)

    def run_cli(self, *args):
        from goat_studio import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['--installation', str(self.f.path), *args])
        return code, json.loads(output.getvalue())

    def test_customer_lane_preview_add_list_remove(self):
        self.c.store.close(); self.c.store = None
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        self.rows = [self.research]
        code, reply = self.run_cli('peer-add', '--terminal', str(exe))
        self.assertEqual((code, reply['result']['status']), (0, 'preview'))
        code, reply = self.run_cli('peer-add', '--terminal', str(exe), '--confirm-reviewed')
        self.assertEqual((code, reply['result']['status']), (0, 'peer_added'))
        code, reply = self.run_cli('peer-list')
        self.assertEqual(code, 0)
        self.assertTrue(reply['result']['peers'][0]['eligible'])
        code, reply = self.run_cli('peer-remove', '--terminal', str(exe), '--confirm-reviewed')
        self.assertEqual((code, reply['result']['status']), (0, 'peer_removed'))

    def test_owner_demo_lane_is_refused_on_the_raw_cli_except_list(self):
        self.c.store.close(); self.c.store = None
        session = self.c.root / 'session.json'
        value = json.loads(session.read_text(encoding='utf-8')); value['authority_kind'] = 'demo_direct'
        session.write_text(json.dumps(value), encoding='utf-8')
        exe, data = self.terminal('Terminal 3 - Tester')
        self.receipt(exe, data)
        for args in (('peer-add', '--terminal', str(exe), '--confirm-reviewed'),
                     ('peer-remove', '--terminal', str(exe), '--confirm-reviewed')):
            with self.subTest(args=args[0]):
                code, reply = self.run_cli(*args)
                self.assertEqual((code, reply['error']), (2, 'Demo mutation requires the broker-verified agent tool'))
        self.assertFalse((self.folder() / roster.ROSTER).exists())
        code, reply = self.run_cli('peer-list')
        self.assertEqual(code, 0)

    def test_operations_are_classified(self):
        from goat_studio import OPERATION_CONTRACTS
        from studio_research_authority import OPERATIONS, READ_OPERATIONS
        self.assertIn('peer-list', READ_OPERATIONS)
        for name in ('peer-add', 'peer-remove'):
            self.assertNotIn(name, READ_OPERATIONS)
            self.assertNotIn(name, OPERATIONS)                  # never allowlisted for a typed continuation
            self.assertIn('owner STOP', OPERATION_CONTRACTS[name]['effect'])


if __name__ == '__main__':
    unittest.main()
