"""Normal close/start of exactly the selected Windows MT5 process. No force kill."""
import json
from pathlib import Path, PureWindowsPath
import subprocess
import time


class WindowsSeedProcess:
    def __init__(self,controller):self.controller=controller

    def inspect(self,timeout=20):
        command='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
        rows=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True,encoding='utf-8-sig',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        target=PureWindowsPath(self.controller.install['terminal_executable']);found=[]
        for row in rows:
            if not row.get('ExecutablePath'):raise ValueError('Unknown terminal executable; inspect ownership first')
            if PureWindowsPath(row['ExecutablePath'])==target:
                if not row.get('CreatedUtc') or type(row.get('ProcessId')) is not int:raise ValueError('Missing terminal identity')
                found.append(dict(pid=row['ProcessId'],executable=str(target),created_utc=row['CreatedUtc']))
        if len(found)>1:raise ValueError('Multiple selected-terminal processes; inspect ownership first')
        return found[0] if found else None

    def close(self,identity):
        if self.inspect()!=identity:raise ValueError('Selected terminal process changed before close')
        # JSON over stdin; never insert account/user strings into PowerShell code.
        script=r'''$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using System.Text;
public static class GoatSeedClose {
 public delegate bool EnumWindowProc(IntPtr window, IntPtr parameter);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowProc callback,IntPtr parameter);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr window,StringBuilder name,int capacity);
 [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr window,uint command);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
 [DllImport("user32.dll",SetLastError=true)] public static extern bool PostMessageW(IntPtr window,uint message,UIntPtr wParam,IntPtr lParam);
 public static IntPtr Find(uint pid) {
  var frames=new List<IntPtr>();
  if(!EnumWindows(delegate(IntPtr window,IntPtr parameter) {
   uint actual; GetWindowThreadProcessId(window,out actual);
   var name=new StringBuilder(256); GetClassNameW(window,name,name.Capacity);
   if(actual==pid && name.ToString()=="MetaQuotes::MetaTrader::5.00" && IsWindowVisible(window) && GetWindow(window,4)==IntPtr.Zero) frames.Add(window);
   return true;
  },IntPtr.Zero)) throw new InvalidOperationException("Window enumeration failed");
  if(frames.Count!=1) throw new InvalidOperationException("Unique selected MT5 frame required");
  return frames[0];
 }
}
'@
$r=[Console]::In.ReadToEnd() | ConvertFrom-Json
$p=[Diagnostics.Process]::GetProcessById([int]$r.pid)
try {
 $null=$p.Handle
 if($p.HasExited) { throw 'Selected process already exited' }
 $ticks=$p.StartTime.ToUniversalTime().Ticks
 $expected=[DateTimeOffset]::Parse($r.created_utc).UtcDateTime.Ticks
 if(($ticks-($ticks % 10)) -ne $expected -or $p.MainModule.FileName -ine $r.executable) { throw 'Process provenance changed' }
 $window=[GoatSeedClose]::Find([uint32]$p.Id)
 if($p.HasExited -or [GoatSeedClose]::Find([uint32]$p.Id) -ne $window) { throw 'Frame ownership changed' }
 if(-not [GoatSeedClose]::PostMessageW($window,0x0112,[UIntPtr]::new([uint64]0xF060),[IntPtr]::Zero)) { throw 'Normal SC_CLOSE failed; no force kill performed' }
} finally { $p.Dispose() }
'''
        subprocess.run(['powershell','-NoProfile','-Command',script],input=json.dumps(identity),text=True,check=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def start(self,config):
        if self.inspect() is not None:raise ValueError('Selected terminal is still running')
        install=self.controller.install
        args=[install['terminal_executable']]
        if install.get('terminal_portable',False):args.append('/portable')
        args.append('/config:'+str(Path(config).resolve()))
        child=subprocess.Popen(args,cwd=str(Path(install['terminal_executable']).parent),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            actual=self.inspect(timeout=max(.1,deadline-time.monotonic()))
            if actual:
                if actual['pid']!=child.pid:raise ValueError('Started terminal PID differs; no further action')
                return actual
            if child.poll() is not None:raise ValueError('Terminal exited before startup identity was observed')
            time.sleep(.1)
        raise ValueError('Terminal startup identity not observed; inspect before recovery')
