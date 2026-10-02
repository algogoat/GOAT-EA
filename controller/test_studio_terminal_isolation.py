"""Terminal isolation (INV-BATCH-01, INV-CRED-01): every MT5 terminal/account runs its
batch state independently, and each MT5 login keeps its own GOAT credential.

Pins are shared with scripts/test_terminal_isolation.cjs, which runs the EA side.
"""
import configparser
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import studio_terminal_isolation as iso
from studio_native_inventory import inventory

BANKER = r'G:\MetaTrader5 Data\Terminals\Terminal 1 - Banker'
PEER = r'G:\MetaTrader5 Data\Terminals\Terminal 2 - GOAT'
LOGIN, OTHER_LOGIN, SERVER = '3000082754', '3000107825', 'Darwinex-Demo'


def ini(path):
    raw = path.read_bytes()
    self_check = raw.startswith(b'\xff\xfe')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(raw.decode('utf-16' if self_check else 'utf-8-sig'))
    return dict(parser[parser.sections()[0]]), self_check


class NamespaceFormulaTests(unittest.TestCase):
    def test_two_terminals_on_one_ea_and_server_resolve_to_different_bases(self):
        banker = iso.base_name('1.49', SERVER, LOGIN, BANKER)
        peer = iso.base_name('1.49', SERVER, LOGIN, PEER)
        self.assertEqual(banker, 'GOAT V1.49-Darwinex-Demo-3000082754-c2408708')
        self.assertEqual(peer, 'GOAT V1.49-Darwinex-Demo-3000082754-30d46804')
        self.assertNotEqual(banker, peer)
        self.assertNotEqual(banker, iso.base_name('1.49', SERVER, OTHER_LOGIN, BANKER))
        self.assertEqual(iso.relative_base('1.49', SERVER, LOGIN, BANKER), 'GOAT\\' + banker)

    def test_hash_matches_the_ea_normalisation(self):
        for spelling in (BANKER, BANKER + '\\', 'g:/metatrader5 data/terminals/terminal 1 - banker/'):
            self.assertEqual(iso.terminal_hash(spelling), 'c2408708')
        # Only ASCII A-Z is folded, exactly as the EA does; other characters are hashed as written.
        self.assertNotEqual(iso.terminal_hash(r'C:\Users\Jürgen\T'), iso.terminal_hash(r'C:\Users\JÜRGEN\T'))

    def test_pre_isolation_versions_keep_the_shared_folder(self):
        self.assertEqual(iso.base_name('1.48', SERVER, LOGIN, BANKER), 'GOAT V1.48-Darwinex-Demo')
        self.assertFalse(iso.isolated('1.48'))

    def test_login_and_server_are_strictly_validated(self):
        for bad in ('', '0', '0123', '12a', ' 1', '1 ', '..\\1', '1/2', '-1', '１２３', 30000, None, '1' * 21):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'digits only'):
                iso.base_name('1.49', SERVER, bad, BANKER)
        for bad in ('Demo\\x', 'Demo/..', ' Demo', 'Demo:1', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                iso.base_name('1.49', bad, LOGIN, BANKER)

    def test_foreign_namespace_detection(self):
        own = iso.base_name('1.49', SERVER, LOGIN, BANKER)
        self.assertTrue(iso.foreign_namespace(iso.base_name('1.49', SERVER, LOGIN, PEER), own))
        self.assertTrue(iso.foreign_namespace(iso.base_name('1.49', SERVER, OTHER_LOGIN, BANKER), own))
        for name in (own, 'GOAT V1.49-Darwinex-Demo', 'GOAT V1.48-Customer-Demo', 'GOAT V1.49-Demo-1-ABCDEF12',
                     'GOAT V1.49-Demo-x-0123abcd', 'Workers', 'SeedFarmingXML'):
            with self.subTest(name=name):
                self.assertFalse(iso.foreign_namespace(name, own))

    def test_inventory_requires_the_namespace_for_isolated_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'per terminal/account'):
                inventory(temp, SERVER, '1.49')
            result = inventory(temp, SERVER, '1.49', login=LOGIN, data_root=BANKER)
            self.assertEqual(result['controls']['active_optimization_run.ini'], None)

    def test_no_controller_module_builds_the_shared_base_by_hand(self):
        root = Path(__file__).parent
        allowed = {'studio_terminal_isolation.py', 'studio_legacy_root_gate.py', 'studio_legacy_settled_gate.py'}
        offenders = []
        for path in root.glob('*.py'):
            if path.name.startswith('test_') or path.name in allowed:
                continue
            text = path.read_text(encoding='utf-8-sig')
            if re.search(r"'GOAT V'\s*\+\s*[\w\[\]'.]+\s*\+\s*'-'\s*\+", text):
                offenders.append(path.name)
        self.assertEqual(offenders, [], 'Resolve batch folders through studio_terminal_isolation')


class CredentialPathTests(unittest.TestCase):
    LEGACY = 'GOAT/Credentials/api-bearer-v149.token'

    def test_two_logins_on_one_pc_keep_separate_credentials(self):
        a = iso.credential_relative_path(self.LEGACY, LOGIN)
        b = iso.credential_relative_path(self.LEGACY, OTHER_LOGIN)
        self.assertEqual(a, 'GOAT/Credentials/api-bearer-v149-3000082754.token')
        self.assertEqual(b, 'GOAT/Credentials/api-bearer-v149-3000107825.token')
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, self.LEGACY)
        self.assertEqual(iso.credential_relative_path('GOAT\\Credentials\\api-bearer-v149.token', LOGIN),
                         'GOAT\\Credentials\\api-bearer-v149-3000082754.token')

    def test_only_digits_and_the_receipt_credential_folder_are_accepted(self):
        for login in ('', '12a', '../1', '1\\2', '0', 7):
            with self.subTest(login=login), self.assertRaises(ValueError):
                iso.credential_relative_path(self.LEGACY, login)
        for legacy in ('GOAT/Credentials/../x.token', 'C:/GOAT/Credentials/api-bearer.token', '/GOAT/Credentials/api-bearer.token',
                       'GOAT/Other/api-bearer.token', 'GOAT/Credentials/sub/api-bearer.token', 'GOAT/Credentials/key.txt',
                       'GOAT/Credentials/api-bearer-v1.4.token'):
            with self.subTest(legacy=legacy), self.assertRaises(ValueError):
                iso.credential_relative_path(legacy, LOGIN)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.common = base / 'common'; self.data = base / 'Terminal 1 - Banker'; self.peer = base / 'Terminal 2 - GOAT'
        self.controller_root = base / 'suite'
        for folder in (self.common, self.data / 'MQL5/Files', self.peer / 'MQL5/Files', self.controller_root):
            folder.mkdir(parents=True)
        self.legacy = self.common / 'GOAT/GOAT V1.49-Darwinex-Demo'; self.legacy.mkdir(parents=True)
        self.base = iso.state_base(self.common, '1.49', SERVER, LOGIN, self.data)
        self.pointer = '[ActiveOptimizationRun]\r\nRunPath=GOAT\\Rabcdefabcdef\r\nUpdatedAt=2026.10.01 00:00:00\r\n'.encode('utf-16')

    def migrate(self, data=None, login=LOGIN, **kwargs):
        return iso.migrate_legacy(self.common, '1.49', SERVER, login, data or self.data,
                                  controller_root=self.controller_root, **kwargs)

    def test_idle_pointer_moves_to_the_terminal_that_ran_it_and_only_once(self):
        (self.legacy / iso.POINTER).write_bytes(self.pointer)
        (self.data / 'MQL5/Files/GOAT/Rabcdefabcdef').mkdir(parents=True)
        self.assertEqual(self.migrate(data=self.peer, login=OTHER_LOGIN)['decision'], 'left_for_other_terminal')
        self.assertTrue((self.legacy / iso.POINTER).exists())
        result = self.migrate()
        self.assertEqual((result['decision'], result['moved']), ('moved', [iso.POINTER]))
        self.assertFalse((self.legacy / iso.POINTER).exists())
        self.assertEqual((self.base / iso.POINTER).read_bytes(), self.pointer)
        receipt, utf16 = ini(self.base / iso.RECEIPT)
        self.assertTrue(utf16)  # The EA reads FILE_UNICODE text.
        self.assertEqual((receipt['Decision'], receipt['Moved'], receipt['Login'], receipt['TerminalHash']),
                         ('moved', iso.POINTER, LOGIN, iso.terminal_hash(self.data)))
        self.assertTrue((self.legacy / ('migrated-to-' + LOGIN + '-' + iso.terminal_hash(self.data) + '.ini')).exists())
        (self.legacy / iso.POINTER).write_bytes(b'new shared state from an older build')
        self.assertEqual(self.migrate()['decision'], 'decided')
        self.assertTrue((self.legacy / iso.POINTER).exists())

    def test_in_flight_batch_moves_only_with_this_terminals_batch_flags(self):
        relative = 'GOAT\\GOAT V1.49-Darwinex-Demo'
        guard = ('[ActiveOptimizationLaunch]\r\nLaunchId=1_2\r\nRunPath=GOAT\\Rabcdefabcdef\r\nConfigPath=' + relative
                 + '\\active_optimization_config.ini\r\nCreatedAt=x\r\n')
        for name, raw in ((iso.POINTER, self.pointer), (iso.CONFIG, b'[Tester]\r\n'), (iso.GUARD, guard.encode('utf-16'))):
            (self.legacy / name).write_bytes(raw)
        peer = self.migrate(data=self.peer, login=OTHER_LOGIN)
        self.assertEqual(peer['decision'], 'left_for_other_terminal')
        self.assertEqual(sorted(p.name for p in self.legacy.iterdir()), sorted([iso.POINTER, iso.CONFIG, iso.GUARD]))
        result = self.migrate(batch_flags=True)
        self.assertEqual(result['moved'], [iso.CONFIG, iso.GUARD, iso.POINTER])
        moved = (self.base / iso.GUARD).read_bytes().decode('utf-16')
        self.assertIn('ConfigPath=' + iso.relative_base('1.49', SERVER, LOGIN, self.data) + '\\active_optimization_config.ini', moved)
        self.assertEqual(moved.replace(iso.relative_base('1.49', SERVER, LOGIN, self.data), relative), guard)
        self.assertEqual(ini(self.base / iso.RECEIPT)[0]['GuardConfigPathBefore'], relative + '\\active_optimization_config.ini')
        self.assertEqual((self.base / iso.CONFIG).read_bytes(), b'[Tester]\r\n')

    def test_both_folders_holding_state_is_refused_and_nothing_changes(self):
        (self.legacy / iso.POINTER).write_bytes(self.pointer)
        (self.data / 'MQL5/Files/GOAT/Rabcdefabcdef').mkdir(parents=True)
        self.base.mkdir(parents=True); (self.base / iso.POINTER).write_bytes(b'own')
        with self.assertRaisesRegex(ValueError, r'both the shared folder .* hold batch state'):
            self.migrate()
        self.assertEqual((self.legacy / iso.POINTER).read_bytes(), self.pointer)
        self.assertEqual((self.base / iso.POINTER).read_bytes(), b'own')
        self.assertFalse((self.base / iso.RECEIPT).exists())

    def test_unsettled_owned_controls_are_never_moved(self):
        (self.legacy / iso.POINTER).write_bytes(self.pointer)
        evidence = self.controller_root / 'attempts/a1'
        (self.legacy / iso.OWNER).write_text(json.dumps(dict(owner='a1', evidence=str(evidence))))
        with self.assertRaisesRegex(ValueError, 'unfinished attempt from this controller'):
            self.migrate(batch_flags=True)
        (self.legacy / iso.OWNER).write_text(json.dumps(dict(owner='b1', evidence=str(Path(self.temp.name) / 'other-suite/attempts/b1'))))
        self.assertEqual(self.migrate(batch_flags=True)['decision'], 'deferred_owned_elsewhere')
        self.assertTrue((self.legacy / iso.POINTER).exists())
        self.assertFalse((self.base / iso.RECEIPT).exists())

    def test_interrupted_move_resumes_from_its_receipt(self):
        (self.legacy / 'log.GOAT').write_bytes(b'log')
        self.base.mkdir(parents=True); (self.base / iso.POINTER).write_bytes(self.pointer)
        (self.base / iso.RECEIPT).write_bytes('[TerminalIsolation]\r\nDecision=moving\r\nPlanned=log.GOAT|active_optimization_run.ini\r\n'.encode('utf-16'))
        self.assertEqual(self.migrate()['moved'], ['log.GOAT'])
        self.assertEqual(ini(self.base / iso.RECEIPT)[0]['Decision'], 'moved')
        (self.base / iso.RECEIPT).write_bytes('[TerminalIsolation]\r\nDecision=moving\r\nPlanned=..\\x\r\n'.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'unexpected file'):
            self.migrate()

    def test_nothing_shared_records_one_decision_and_pre_isolation_versions_do_nothing(self):
        self.assertEqual(self.migrate()['decision'], 'nothing_to_move')
        self.assertEqual(ini(self.base / iso.RECEIPT)[0]['Decision'], 'nothing_to_move')
        self.assertEqual(iso.migrate_legacy(self.common, '1.48', SERVER, LOGIN, self.data)['decision'], 'not_isolated')


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.common = base / 'common'; self.common.mkdir()
        self.appdata = base / 'appdata'; (self.appdata / 'MetaQuotes/Terminal').mkdir(parents=True)
        self.a = base / 'Terminal A'; self.b = base / 'Terminal B'
        for folder in (self.a, self.b):
            (folder / 'MQL5').mkdir(parents=True); (folder / 'terminal64.exe').write_bytes(b'')
        self.account = dict(login=LOGIN, server=SERVER)
        self.binding = dict(ea_version='1.49', common_files_root=str(self.common), research_data_root=str(self.a),
                            research_terminal=str(self.a / 'terminal64.exe'))
        self.observation = dict(state_base=iso.binding_relative(self.binding, self.account), runtime=dict(batch_ongoing=False))

    def row(self, pid, folder):
        return dict(ProcessId=pid, ExecutablePath=str(folder / 'terminal64.exe'), CommandLine='')

    def preflight(self, processes, observation=None):
        return iso.preflight(self.binding, self.account, observation=observation or self.observation,
                             processes=processes, appdata=self.appdata, controller_root=self.common.parent / 'suite')

    def test_two_terminals_on_one_ea_server_and_login_run_independently(self):
        other = dict(self.binding, research_data_root=str(self.b), research_terminal=str(self.b / 'terminal64.exe'))
        processes = [self.row(1, self.a), self.row(2, self.b)]
        first = self.preflight(processes)
        second = iso.preflight(other, self.account, observation=dict(state_base=iso.binding_relative(other, self.account)),
                               processes=processes, appdata=self.appdata)
        self.assertNotEqual(first['base'], second['base'])
        self.assertEqual({first['migration']['decision'], second['migration']['decision']}, {'nothing_to_move'})

    def test_another_live_terminal_on_the_same_folder_is_refused(self):
        with self.assertRaisesRegex(ValueError, r'Another running MT5 terminal .* resolves to this terminal\'s batch folder'):
            self.preflight([self.row(1, self.a), self.row(2, self.a)])
        # A different installation whose AppData data folder is this terminal's folder.
        install = Path(self.temp.name) / 'Program Files/MetaTrader 5'; install.mkdir(parents=True)
        hashed = self.appdata / 'MetaQuotes/Terminal/ABCDEF'; hashed.mkdir()
        (hashed / 'origin.txt').write_bytes(str(install).encode('utf-16'))
        binding = dict(self.binding, research_data_root=str(hashed))
        observation = dict(state_base=iso.binding_relative(binding, self.account))
        with self.assertRaisesRegex(ValueError, 'Another running MT5 terminal'):
            iso.preflight(binding, self.account, observation=observation, appdata=self.appdata,
                          processes=[self.row(1, self.a), dict(ProcessId=3, ExecutablePath=str(install / 'terminal64.exe'))])
        self.assertFalse((self.common / 'GOAT').exists())  # Refusal precedes any migration effect.

    def test_running_ea_must_resolve_the_same_folder(self):
        with self.assertRaisesRegex(ValueError, 'predates terminal isolation'):
            self.preflight([self.row(1, self.a)], observation=dict(runtime={}))
        stale = dict(self.observation, state_base='GOAT\\GOAT V1.49-Darwinex-Demo')
        with self.assertRaisesRegex(ValueError, 'uses batch folder GOAT\\\\GOAT V1.49-Darwinex-Demo, but this controller expects'):
            self.preflight([self.row(1, self.a)], observation=stale)

    def test_preflight_runs_the_migration_and_surfaces_its_refusal(self):
        legacy = self.common / 'GOAT/GOAT V1.49-Darwinex-Demo'; legacy.mkdir(parents=True)
        (legacy / iso.POINTER).write_bytes('[ActiveOptimizationRun]\r\nRunPath=\r\n'.encode('utf-16'))
        base = Path(iso.binding_base(self.binding, self.account)); base.mkdir(parents=True)
        (base / iso.POINTER).write_bytes(b'own')
        with self.assertRaisesRegex(ValueError, 'hold batch state'):
            self.preflight([self.row(1, self.a)])

    def test_live_terminal_inventory_is_read_only_and_windowless(self):
        with patch('studio_terminal_isolation.subprocess.check_output', return_value='[]') as call:
            self.assertEqual(iso.live_terminals(), [])
        command = call.call_args[0][0][-1]
        self.assertIn("Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\"", command)
        for verb in ('Stop-Process', 'Start-Process', 'Invoke-', 'Remove-'):
            self.assertNotIn(verb, command)
        self.assertIn('creationflags', call.call_args[1])


if __name__ == '__main__':
    unittest.main()
