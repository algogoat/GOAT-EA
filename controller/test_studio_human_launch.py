import unittest
from unittest.mock import patch
from studio_human_launch import classify
from studio_human_reopen import pointer_bytes


class HumanLaunchTests(unittest.TestCase):
    def test_exact_console_explorer_and_plain_argv_are_required(self):
        exe=r'C:\Banker\terminal64.exe';explorer=r'C:\Windows\explorer.exe'
        target=dict(ProcessId=20,ParentProcessId=10,SessionId=2,ExecutablePath=exe,CreatedUtc='2026-09-28T02:00:00Z',CommandLine='terminal')
        parent=dict(ProcessId=10,ParentProcessId=5,SessionId=2,ExecutablePath=explorer,CreatedUtc='2026-09-27T00:00:00Z',CommandLine='explorer')
        current=dict(pid=20,created_utc=target['CreatedUtc'])
        with patch('studio_human_launch.arguments',return_value=[exe]) as argv:
            classify([target,parent],current,exe,False,2,explorer)
            for changed,changed_parent,console in ((dict(SessionId=0),{},2),({},dict(SessionId=0),2),({},dict(ExecutablePath=r'C:\Windows\powershell.exe'),2),({},dict(CreatedUtc='2026-09-28T03:00:00Z'),2),({},{},0xffffffff)):
                with self.subTest(changed=changed,parent=changed_parent),self.assertRaises(ValueError):classify([target|changed,parent|changed_parent],current,exe,False,console,explorer)
            for extra in (['/config:evil.ini'],['/portable'],['--anything']):
                argv.return_value=[exe]+extra
                with self.assertRaisesRegex(ValueError,'command'):classify([target,parent],current,exe,False,2,explorer)
            argv.return_value=[exe,'/portable'];classify([target,parent],current,exe,True,2,explorer)

    def test_profile_pointer_preserves_each_native_line_ending(self):
        for newline in ('\r','\n','\r\n'):
            before=newline.join(['[Experts]','Enabled=0','AllowDllImport=1','[Charts]','ProfileLast=old','']).encode('utf-16')
            self.assertEqual(pointer_bytes(before,'new'),before.decode('utf-16').replace('ProfileLast=old','ProfileLast=new').encode('utf-16'))
