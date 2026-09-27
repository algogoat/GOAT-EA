"""Receipt-upgrade caller regression; no terminal, account or receipt mutation."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import studio_desktop_client as client
import studio_handover
from studio_handover import stopped
import test_goat_studio


class DesktopClientTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_goat_studio.PortableControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound()
        self.bundle = self.c.root.parent/'bundle with spaces'
        names = ['goat.exe', 'python/python.exe', 'controller/goat_agent.py',
                 'controller/studio_desktop_client.py', 'controller/studio_handover.py']
        files = []
        for name in names:
            p = self.bundle/name
            p.parent.mkdir(parents=True, exist_ok=True)
            raw = ('fixture:'+name).encode()
            p.write_bytes(raw)
            files.append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        (self.bundle/'manifest.json').write_text(json.dumps(dict(files=files)))
        self.params = self.bundle/'request.json'
        self.params.write_text(json.dumps(dict(accountId='123456', buildId='reviewed-build',
            parkReviewId='a'*32, selection=dict(terminalExecutable=self.c.install['terminal_executable'],
                terminalDataRoot=self.c.install['terminal_data_root'], portable=False))))
        self.args = [str(self.bundle/'goat.exe'), 'desktop', 'suite.installInternalQualification',
                     '--params', str(self.params), '--request-id', 'fixture-request', '--timeout-ms', '120000']
        child = [str(self.bundle/'python/python.exe'), '-B', str(self.bundle/'controller/goat_agent.py'), *self.args[1:]]
        self.rows = [dict(ProcessId=os.getpid(), ParentProcessId=0, Name='python.exe',
                         ExecutablePath='own-python', CommandLine='own'),
                     dict(ProcessId=98760, ParentProcessId=0, Name='goat.exe',
                         ExecutablePath=self.args[0], CommandLine=json.dumps(self.args)),
                     dict(ProcessId=98761, ParentProcessId=98760, Name='python.exe',
                         ExecutablePath=child[0], CommandLine=json.dumps(child))]
        self.addCleanup(patch.stopall)
        patch.object(client, '__file__', str(self.bundle/'controller/studio_desktop_client.py')).start()
        patch.object(client, 'windows_argv', side_effect=lambda raw: json.loads(raw)).start()

    def guard(self, allow=True):
        with patch('studio_handover.subprocess.check_output', return_value=json.dumps(self.rows)):
            stopped(self.c, [], allow_qualification_client=allow)

    def test_verified_waiting_client_is_allowed_only_during_receipt_upgrade(self):
        self.guard()
        with self.assertRaisesRegex(ValueError, 'Stop the existing'):
            self.guard(allow=False)

    def test_changed_launcher_entry_runtime_or_controller_stays_blocked(self):
        for name in ['goat.exe', 'controller/goat_agent.py', 'python/python.exe',
                     'controller/studio_desktop_client.py', 'controller/studio_handover.py']:
            with self.subTest(name=name):
                target = self.bundle/name
                original = target.read_bytes()
                target.write_bytes(b'changed')
                with self.assertRaises(ValueError): self.guard()
                target.write_bytes(original)

    def test_same_size_changed_bytes_require_sha256_refusal(self):
        for name in ['goat.exe', 'controller/goat_agent.py', 'python/python.exe']:
            with self.subTest(name=name):
                target = self.bundle/name
                original = target.read_bytes()
                target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                self.assertEqual(target.stat().st_size, len(original))
                with self.assertRaises(ValueError): self.guard()
                target.write_bytes(original)

    def test_legacy_portable_receipt_derives_mode_from_paths(self):
        self.c.install.pop('terminal_portable', None)
        self.c.install['terminal_data_root'] = str(Path(self.c.install['terminal_executable']).parent)
        params = json.loads(self.params.read_text())
        params['selection'].update(terminalDataRoot=self.c.install['terminal_data_root'], portable=True)
        self.params.write_text(json.dumps(params))
        self.assertEqual(client.qualification_clients(self.c, self.rows), {98760, 98761})
        self.guard()
        params['selection']['portable'] = False
        self.params.write_text(json.dumps(params))
        with self.assertRaises(ValueError): self.guard()

    def test_extra_flag_rejected_even_with_required_flags_and_matching_child(self):
        args = [*self.args, '--data-dir', str(self.bundle)]
        child = [str(self.bundle/'python/python.exe'), '-B', str(self.bundle/'controller/goat_agent.py'), *args[1:]]
        self.rows[1]['CommandLine'] = json.dumps(args)
        self.rows[2]['CommandLine'] = json.dumps(child)
        with self.assertRaises(ValueError): self.guard()

    def test_child_script_and_forwarded_method_are_independently_checked(self):
        original = json.loads(self.rows[2]['CommandLine'])
        for index, value in [(2, str(self.bundle/'controller/goat_studio.py')), (4, 'suite.applyUpdate')]:
            with self.subTest(index=index):
                args = original.copy()
                args[index] = value
                self.assertEqual(len(args), len(original))
                self.rows[2]['CommandLine'] = json.dumps(args)
                with self.assertRaises(ValueError): self.guard()

    def test_second_child_is_rejected_even_if_not_a_runner(self):
        self.rows.append(dict(ProcessId=98764, ParentProcessId=98760, Name='conhost.exe',
                              ExecutablePath='console', CommandLine='console'))
        with self.assertRaises(ValueError): self.guard()

    def test_native_methods_unknown_arguments_and_different_target_stay_blocked(self):
        for change in [('surface', 'studio'), ('method', 'suite.applyUpdate'), ('flag', '--data-dir')]:
            with self.subTest(change=change):
                args = self.args.copy()
                args[{'surface':1,'method':2,'flag':3}[change[0]]] = change[1]
                self.rows[1]['CommandLine'] = json.dumps(args)
                with self.assertRaises(ValueError): self.guard()
        self.rows[1]['CommandLine'] = json.dumps(self.args)
        p = json.loads(self.params.read_text())
        p['selection']['terminalDataRoot'] += '-other'
        self.params.write_text(json.dumps(p))
        with self.assertRaises(ValueError): self.guard()

    def test_child_mismatch_missing_identity_and_concurrent_callers_stay_blocked(self):
        original = copy.deepcopy(self.rows)
        for key, value in [('ExecutablePath','other-python'), ('ParentProcessId',0), ('CommandLine','[]')]:
            with self.subTest(key=key):
                self.rows = copy.deepcopy(original)
                self.rows[2][key] = value
                with self.assertRaises(ValueError): self.guard()
        self.rows = copy.deepcopy(original)
        duplicate = copy.deepcopy(self.rows[1:])
        duplicate[0]['ProcessId'] = 98762
        duplicate[1].update(ProcessId=98763, ParentProcessId=98762)
        self.rows += duplicate
        with self.assertRaises(ValueError): self.guard()

    def test_unrelated_native_runner_and_terminal_remain_blocked(self):
        for row in [dict(ProcessId=98764, Name='goat.exe', ExecutablePath='other', CommandLine='other'),
                    dict(ProcessId=98764, Name='python.exe', ExecutablePath='python', CommandLine='goat_studio.py serve'),
                    dict(ProcessId=98764, Name='terminal64.exe')]:
            with self.subTest(row=row):
                self.rows.append(row)
                with self.assertRaises(ValueError): self.guard()
                self.rows.pop()

    def test_missing_duplicate_manifest_and_malformed_parameters_stay_blocked(self):
        manifest = self.bundle/'manifest.json'
        original = manifest.read_text()
        value = json.loads(original)
        value['files'].append(value['files'][0])
        manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.guard()
        manifest.write_text(original)
        self.params.write_text('{')
        with self.assertRaises(ValueError): self.guard()
        manifest.unlink()
        with self.assertRaises(ValueError): self.guard()


@unittest.skipUnless(os.name == 'nt', 'Windows native argument parser')
class NativeArgumentTests(unittest.TestCase):
    def test_spaces_quotes_and_backslashes_preserve_exact_arguments(self):
        args = [r'C:\Program Files\GOAT\goat.exe', 'desktop', 'suite.installInternalQualification',
                '--params', r'C:\Users\Some One\review.json', '--request-id', 'request-1']
        self.assertEqual(client.windows_argv(subprocess.list2cmdline(args)), args)


class QualificationScopeTests(unittest.TestCase):
    def test_only_completed_park_inspection_can_enable_client_recognition(self):
        root = Path(studio_handover.__file__).parent
        tree = ast.parse((root/'studio_handover.py').read_text(encoding='utf-8-sig'))
        definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'stopped')
        index = [a.arg for a in definition.args.kwonlyargs].index('allow_qualification_client')
        default = definition.args.kw_defaults[index]
        self.assertIsInstance(default, ast.Constant)
        self.assertIs(default.value, False)
        sites = []
        for source in root.glob('*.py'):
            if source.name.startswith('test_'):
                continue
            module = ast.parse(source.read_text(encoding='utf-8-sig'))
            for function in [n for n in ast.walk(module) if isinstance(n, ast.FunctionDef)]:
                for call in [n for n in ast.walk(function) if isinstance(n, ast.Call)]:
                    for keyword in call.keywords:
                        if keyword.arg == 'allow_qualification_client':
                            self.assertIsInstance(keyword.value, ast.Constant)
                            self.assertIs(keyword.value.value, True)
                            sites.append((source.name, function.name))
        self.assertEqual(sites, [('studio_installation_upgrade.py', 'inspect_park')])


if __name__ == '__main__':
    unittest.main()
