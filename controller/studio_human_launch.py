"""Positive shell/console/argv evidence for an actual human terminal reopen."""
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path,PureWindowsPath
import subprocess

from studio_driver_suspend import arguments


def classify(rows,current,executable,portable,console_id,explorer_path,*,retained=None):
    targets=[p for p in rows if p.get('ProcessId')==current['pid']]
    if len(targets)!=1:raise ValueError('Exact human-reopened process metadata required')
    target=targets[0]
    if retained is not None:
        # Revalidate the original proof against this exact process and current
        # console, without requiring its already-recorded parent to stay alive.
        original=classify([retained['target'],retained['parent']],current,
                          executable,portable,console_id,explorer_path)
        if original!=retained or target!=retained['target']:
            raise ValueError('Adopted target or retained human launch evidence changed')
        return original
    parents=[p for p in rows if p.get('ProcessId')==target.get('ParentProcessId')]
    if len(parents)!=1:raise ValueError('Human reopen requires the original Explorer parent')
    parent=parents[0]
    def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    if (PureWindowsPath(target.get('ExecutablePath') or '')!=PureWindowsPath(executable)
            or stamp(target['CreatedUtc'])!=stamp(current['created_utc'])
            or PureWindowsPath(parent.get('ExecutablePath') or '')!=PureWindowsPath(explorer_path)
            or stamp(parent['CreatedUtc'])>=stamp(target['CreatedUtc'])
            or type(console_id) is not int or console_id==0xffffffff
            or target.get('SessionId')!=console_id or parent.get('SessionId')!=console_id):
        raise ValueError('Human reopen requires prior Explorer parent in the active console session')
    args=arguments(target.get('CommandLine') or '')
    if (not args or PureWindowsPath(args[0])!=PureWindowsPath(executable)
            or args[1:]!=(['/portable'] if portable else [])):
        raise ValueError('Human reopen command must contain only the executable and required portable flag')
    return dict(target=target,parent=parent,active_console_session_id=console_id,arguments=args)


def human_launch(c,current,*,retained=None):
    script='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @(\'terminal64.exe\',\'explorer.exe\')} | Select-Object ProcessId,ParentProcessId,SessionId,ExecutablePath,CommandLine,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    rows=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],text=True,encoding='utf-8-sig',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.WTSGetActiveConsoleSessionId.restype=ctypes.c_uint32
    executable=Path(c.install['terminal_executable'])
    return classify(rows,current,str(executable),Path(c.install['terminal_data_root'])==executable.parent,
                    kernel.WTSGetActiveConsoleSessionId(),str(Path(os.environ['SystemRoot'])/'explorer.exe'),retained=retained)
