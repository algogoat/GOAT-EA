import json
import unittest
from unittest.mock import patch
from studio_process_check import inspect_processes, classify_processes
from studio_research_authority import demo_agent_scope

class SelectedTerminalScopeTests(unittest.TestCase):
    binding={'research_terminal':'C:/Selected/terminal64.exe'}
    roots=['C:/Selected','C:/Data/Selected']
    def row(self,path,name='terminal64.exe',pid=1):
        return dict(ProcessId=pid,ExecutablePath=path,Name=name,CreatedUtc='2026-09-29T00:00:00Z')
    def scan(self,rows,**kwargs):
        with patch('studio_process_check.subprocess.check_output',return_value=json.dumps(rows)) as call:
            result=inspect_processes(self.binding,**kwargs)
        self.assertNotIn('-Filter',call.call_args.args[0][-1])
        return result
    def test_stopped_selected_with_eight_unrelated_terminals(self):
        rows=[self.row(f'C:/Experiment{i}/terminal64.exe',pid=i) for i in range(1,9)]
        result=self.scan(rows,research_running=False,absent_roots=self.roots,selected_stopped=True)
        self.assertIsNone(result['research']);self.assertEqual(len(result['unrelated']),8)
        self.assertFalse(result['launch_permitted'])
    def test_stopped_selected_rejects_renamed_target_and_unreadable_terminal(self):
        for row in (self.row('C:/Selected/renamed.exe','renamed.exe'),self.row('C:/Data/Selected/x.exe','x.exe'),self.row(None)):
            with self.subTest(row=row),self.assertRaises(ValueError):
                self.scan([row],research_running=False,absent_roots=self.roots,selected_stopped=True)
    def test_no_static_binding_flag_relaxes_generic_path(self):
        binding=dict(self.binding,demo_only=True,allow_unrelated=True)
        with self.assertRaisesRegex(ValueError,'Unmapped'):
            classify_processes([self.row('C:/Selected/terminal64.exe'),self.row('C:/Other/terminal64.exe',pid=2)],binding,observed_unix=1)
    def test_active_selected_refuses_duplicate_and_renamed_target(self):
        for extra in (self.row('C:/Selected/terminal64.exe',pid=2),self.row('C:/Selected/renamed.exe','renamed.exe',2),self.row(None,pid=2)):
            with patch('studio_process_check._demo_selected_roots',return_value=self.roots),self.assertRaises(ValueError):
                self.scan([self.row('C:/Selected/terminal64.exe'),extra])
    def test_active_demo_retains_selected_identity_and_observes_others(self):
        with patch('studio_process_check._demo_selected_roots',return_value=self.roots):
            result=self.scan([self.row('C:/Selected/terminal64.exe'),self.row('C:/Other/terminal64.exe',pid=2)])
        self.assertEqual(result['research']['pid'],1);self.assertEqual(result['unrelated'][0]['pid'],2)
    def test_active_scope_must_validate_installation_session_and_target(self):
        from studio_process_check import _demo_selected_roots
        install={'terminal_executable':'C:/Selected/terminal64.exe','terminal_data_root':'C:/Data/Selected'}
        with demo_agent_scope(root='C:/State',installation_sha256='hash',account={'login':'1','server':'s'}):
            with patch('studio_installation.load_installation',return_value=install),patch('studio_installation.read_json',return_value={}),patch('studio_research_authority.require_demo_agent_scope',side_effect=ValueError('stale proof')):
                with self.assertRaisesRegex(ValueError,'stale proof'):_demo_selected_roots(self.binding)
            with patch('studio_installation.load_installation',return_value=install),patch('studio_installation.read_json',return_value={}),patch('studio_research_authority.require_demo_agent_scope',return_value={}):
                with self.assertRaisesRegex(ValueError,'another selected'):_demo_selected_roots({'research_terminal':'C:/Other/terminal64.exe'})
    def test_selected_stopped_cannot_be_used_for_active_launch_scope(self):
        with self.assertRaisesRegex(ValueError,'stopped roots'):self.scan([],selected_stopped=True)

if __name__=='__main__':unittest.main()
