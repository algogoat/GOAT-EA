"""Windows inventory selection and actual scanner wiring; no MT5 operations."""
import json
import subprocess
import unittest
from unittest.mock import patch

from studio_process_check import inspect_processes, stopped_candidates


class StoppedInventoryTests(unittest.TestCase):
    roots=['C:/MT5/Banker','C:/Data/Banker']
    binding={'research_terminal':'C:/MT5/Banker/terminal64.exe'}

    def setUp(self):
        self.binding=dict(type(self).binding)

    def row(self,path,name='renamed.exe',pid=7):
        return dict(ProcessId=pid,Name=name,ExecutablePath=path,CreatedUtc='2026-09-28T00:00:00Z')

    def scan(self,rows):
        with patch('studio_process_check.subprocess.check_output',return_value=json.dumps(rows)) as call:
            result=inspect_processes(self.binding,research_running=False,absent_roots=self.roots)
        command=call.call_args.args[0][-1]
        self.assertIn('$ErrorActionPreference="Stop"',command)
        self.assertNotIn('-Filter',command)
        self.assertNotIn('C:/MT5',command)
        return result

    def test_empty_real_scanner_shape_records_roots_and_no_launch(self):
        result=self.scan([])
        self.assertIsNone(result['research']);self.assertFalse(result['launch_permitted'])
        self.assertEqual(result['root_inventory']['process_count'],0)

    def test_renamed_or_copied_executable_in_either_root_refuses(self):
        for path in ('C:/MT5/Banker/not-terminal.exe','c:/DATA/banker/copy/other.exe'):
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'stopped terminal root'):
                self.scan([self.row(path)])

    def test_similar_prefix_is_not_a_child(self):
        result=self.scan([self.row('C:/MT5/Banker-other/other.exe')])
        self.assertEqual(result['root_inventory']['process_count'],1)

    def test_named_terminal_without_path_or_unmapped_path_still_refuses(self):
        for path in (None,'C:/Other/terminal64.exe'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.scan([self.row(path,name='TERMINAL64.EXE')])

    def test_unreadable_system_paths_are_explicit_in_evidence(self):
        result=self.scan([self.row(None,name='System',pid=0)])
        self.assertEqual(result['root_inventory']['unavailable_path_count'],1)
        self.assertIn('unreadable',result['root_inventory']['limitation'])

    def test_protected_peer_identity_check_is_preserved(self):
        self.binding|={'protected_terminal':'C:/Peer/terminal64.exe',
            'protected_process':dict(pid=7,executable='C:\\Peer\\terminal64.exe',created_utc='old')}
        with self.assertRaisesRegex(ValueError,'Protected peer process changed'):
            self.scan([self.row('C:/Peer/terminal64.exe',name='terminal64.exe')])

    def test_git_bash_dotdot_image_outside_roots_is_ordinary(self):
        # Git for Windows (and so Claude Code) starts bash as bin\..\usr\bin\bash.exe.
        result=self.scan([self.row('C:\\Program Files\\Git\\bin\\..\\usr\\bin\\bash.exe',name='bash.exe')])
        self.assertEqual(result['root_inventory']['process_count'],1)

    def test_dotdot_resolving_into_a_stopped_root_still_refuses(self):
        for path in ('C:/MT5/Other/../Banker/copy.exe','C:\\Data\\Banker\\x\\..\\copy.exe',
                     'C:\\MT5\\.\\Banker\\copy.exe'):
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'stopped terminal root'):
                self.scan([self.row(path)])

    def test_verbatim_and_device_prefixes_cannot_evade_a_root(self):
        for path in ('\\\\?\\C:\\MT5\\Banker\\copy.exe','\\\\?\\c:\\data\\banker\\copy.exe',
                     '\\\\.\\C:\\MT5\\Banker\\copy.exe','\\\\.\\C:\\MT5\\x\\..\\Banker\\copy.exe',
                     '//?/C:/MT5/Banker/copy.exe'):
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'stopped terminal root'):
                self.scan([self.row(path)])

    def test_mixed_separators_resolve_like_windows(self):
        with self.assertRaisesRegex(ValueError,'stopped terminal root'):
            self.scan([self.row('C:/MT5\\Banker/sub\\..\\copy.exe')])
        result=self.scan([self.row('C:/Tools\\bin/../x.exe')])
        self.assertEqual(result['root_inventory']['process_count'],1)

    def test_inventory_or_root_ambiguity_refuses(self):
        # Relative images, and `..` inside a verbatim \\?\ path (Win32 opens it unresolved), stay ambiguous.
        for rows in ({},[self.row('relative.exe')],[self.row('C:/Other/a.exe')]*2,
                     [self.row('..\\copy.exe')],[self.row('\\\\?\\C:\\Other\\x\\..\\copy.exe')],
                     [dict(ProcessId=8)]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.scan(rows)
        for roots in ([],['C:/'],['relative'],['C:/MT5/../Banker']):
            with self.subTest(roots=roots),self.assertRaises(ValueError):stopped_candidates([],roots)

    def test_query_error_or_running_mode_cannot_claim_absence(self):
        # Retried through a stall (studio_process_query), then still a failure: never "absent".
        with patch('studio_process_check.subprocess.check_output',side_effect=subprocess.CalledProcessError(1,'powershell')), \
                patch('studio_process_query.sleep'):
            with self.assertRaises(subprocess.CalledProcessError):
                inspect_processes(self.binding,research_running=False,absent_roots=self.roots)
        with self.assertRaisesRegex(ValueError,'stopped research terminal'):
            inspect_processes(self.binding,absent_roots=self.roots)


if __name__=='__main__':unittest.main()
