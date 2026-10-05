"""Normal close/start of exactly the selected Windows MT5 process. No force kill."""
from datetime import datetime, timezone
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import time

from studio_process_query import powershell_text


UNKNOWN_EXECUTABLE='Unknown terminal executable; inspect ownership first'
# Windows reports no ExecutablePath for a terminal64 process for a moment while it is
# being created or torn down (seen beside another terminal's own relaunch). That row is
# re-read, never assumed: only a path still missing after this window refuses.
UNKNOWN_SETTLE_SECONDS=10
UNKNOWN_RETRY_SECONDS=.5
# How long start() waits for the identity of the MT5 it just launched. WMI stalls cluster at an MT5
# launch (T2, 2026-10-05 13:43Z): inside this window a stalled or erroring inventory, or a row still
# without its path, is "not seen yet". A wrong PID, two processes or an exit refuse at once.
STARTUP_IDENTITY_SECONDS=90
STARTUP_POLL_SECONDS=.1
STARTUP_UNSEEN='Terminal startup identity not observed'
PROCESS_QUERY_LIMITED_INFORMATION=0x1000
_EPOCH_1601=datetime(1601,1,1,tzinfo=timezone.utc)


def created_ticks(created_utc):
    """100 ns ticks since 1601 of an inventory CreatedUtc, at the microsecond WMI reports; None if unreadable."""
    match=re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(?:Z|\+00:00)',str(created_utc or ''))
    if not match:return None
    try:base=datetime.strptime(match[1],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError:return None
    delta=base-_EPOCH_1601
    return (delta.days*86400+delta.seconds)*10_000_000+int((match[2] or '0')[:6].ljust(6,'0'))*10


def created_unix(created_utc):
    """Unix seconds of an inventory CreatedUtc, or None if unreadable."""
    ticks=created_ticks(created_utc)
    return None if ticks is None else ticks/10_000_000-(datetime(1970,1,1,tzinfo=timezone.utc)-_EPOCH_1601).total_seconds()


def process_image_path(pid,created_utc):
    """The image path of one process read from the process itself (no WMI), or None when it is not provable.

    ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` then ``QueryFullProcessImageNameW``; the handle is bound to
    the inventory row by its creation time (``GetProcessTimes`` on the same handle), so a reused PID is never read
    as that row. A denied open, another process or any failed call is None: no proof, never a guess.
    """
    expected=created_ticks(created_utc)
    if type(pid) is not int or pid<=0 or expected is None:return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    except (ImportError,OSError,AttributeError):
        return None
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.GetProcessTimes.restype=wintypes.BOOL
    kernel.GetProcessTimes.argtypes=(wintypes.HANDLE,)+(ctypes.POINTER(wintypes.FILETIME),)*4
    kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes=(wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    handle=kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,pid)
    if not handle:return None
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(item) for item in times]):return None
        created=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        if created-created%10!=expected:return None
        size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):return None
        return buffer.value or None
    finally:
        kernel.CloseHandle(handle)


def inspect_within(process,budget=None):
    """``process.inspect()``, bounded to ``budget`` seconds when given and the process tool supports it.

    Status reads pass POLL_BUDGET so a WMI stall answers within it (Codex P2 on GOAT-EA#163). Fixture process
    tools without a ``budget`` parameter are called as before.
    """
    if budget is None:return process.inspect()
    import inspect
    try:accepts='budget' in inspect.signature(process.inspect).parameters
    except (TypeError,ValueError):accepts=False
    return process.inspect(budget=budget) if accepts else process.inspect()


class WindowsSeedProcess:
    def __init__(self,controller,*,sleep=time.sleep,monotonic=time.monotonic):
        self.controller=controller;self.sleep=sleep;self.monotonic=monotonic

    def _rows(self,timeout,budget=None):
        command='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
        return json.loads(powershell_text(command,purpose='selected terminal inventory',timeout=timeout,budget=budget))

    def image_path(self,row):
        """Fill a row WMI listed without ExecutablePath from the process itself (bound by its creation time), else None."""
        return process_image_path(row.get('ProcessId'),row.get('CreatedUtc'))

    def inspect(self,timeout=20,budget=None):
        """The selected MT5 or None. ``budget`` bounds the whole inspection for a caller with its own deadline."""
        started=self.monotonic()
        end=None if budget is None else started+budget
        deadline=started+UNKNOWN_SETTLE_SECONDS if end is None else min(started+UNKNOWN_SETTLE_SECONDS,end)
        while True:
            rows=self._rows(timeout,None if end is None else max(.1,end-self.monotonic()))
            for row in rows:
                # WMI leaves the path empty when it cannot open the process with full query rights. Read it
                # from the process itself before refusing; an unreadable process stays unknown.
                if not row.get('ExecutablePath'):
                    filled=self.image_path(row)
                    if filled:row['ExecutablePath']=filled
            if all(row.get('ExecutablePath') for row in rows):break
            # A transient missing path: re-read the whole inventory; never guess the row's owner.
            if self.monotonic()>=deadline:raise ValueError(UNKNOWN_EXECUTABLE)
            self.sleep(UNKNOWN_RETRY_SECONDS)
        target=PureWindowsPath(self.controller.install['terminal_executable']);found=[]
        for row in rows:
            if PureWindowsPath(row['ExecutablePath'])==target:
                if not row.get('CreatedUtc') or type(row.get('ProcessId')) is not int:raise ValueError('Missing terminal identity')
                found.append(dict(pid=row['ProcessId'],executable=str(target),created_utc=row['CreatedUtc']))
        if len(found)>1:raise ValueError('Multiple selected-terminal processes; inspect ownership first')
        return found[0] if found else None

    def command_line(self,identity,timeout=20):
        """Read-only: the command line of exactly this selected process (PID, image and creation time)."""
        if not isinstance(identity,dict) or type(identity.get('pid')) is not int:raise ValueError('Exact process identity required')
        command=('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "ProcessId='
                 +str(identity['pid'])+'" | Select-Object ProcessId,ExecutablePath,CommandLine,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})')
        rows=json.loads(powershell_text(command,purpose='selected terminal command line',timeout=timeout))
        if (len(rows)!=1 or rows[0].get('ProcessId')!=identity['pid'] or not rows[0].get('ExecutablePath')
                or PureWindowsPath(rows[0]['ExecutablePath'])!=PureWindowsPath(identity.get('executable') or '')
                or rows[0].get('CreatedUtc')!=identity.get('created_utc')):
            raise ValueError('Selected terminal process changed before its command line was read')
        return rows[0].get('CommandLine') or ''

    def config_users(self,names,timeout=20):
        """Read-only: every terminal64 process (any install) whose command line names one of ``names``.

        Used to prove no MT5 still runs a seed member's frozen INI. A row whose command line
        cannot be read is re-read like a missing path; still unreadable, it refuses (no proof).
        """
        command=('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process '
                 '-Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,CommandLine)')
        folded=[str(name).casefold() for name in names if name]
        deadline=self.monotonic()+UNKNOWN_SETTLE_SECONDS
        while True:
            rows=json.loads(powershell_text(command,purpose='terminal64 command lines',timeout=timeout))
            if all(row.get('CommandLine') for row in rows):break
            if self.monotonic()>=deadline:raise ValueError('A terminal64 command line cannot be read; inspect ownership first')
            self.sleep(UNKNOWN_RETRY_SECONDS)
        return [dict(pid=row.get('ProcessId'),executable=row.get('ExecutablePath')) for row in rows
                if any(name in row['CommandLine'].casefold() for name in folded)]

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
   if(actual==pid && name.ToString().StartsWith("MetaQuotes::MetaTrader::",StringComparison.Ordinal) && IsWindowVisible(window) && GetWindow(window,4)==IntPtr.Zero) frames.Add(window);
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

    def start(self,config,*,research=False):
        """Launch the selected MT5 with ``config``. ``research`` (only through ResearchLaunch) uses the
        research-launch policy: created suspended at low priority inside this terminal's job, or refused.
        Every other launch (monitor restarts, recovery) is unchanged."""
        if self.inspect() is not None:raise ValueError('Selected terminal is still running')
        install=self.controller.install
        args=[install['terminal_executable']]
        if install.get('terminal_portable',False):args.append('/portable')
        args.append('/config:'+str(Path(config).resolve()))
        cwd=str(Path(install['terminal_executable']).parent)
        if research is True:
            from studio_research_launch import launch
            child=launch(self.controller,args,cwd=cwd,config=config)
        else:
            child=subprocess.Popen(args,cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=self.monotonic()+STARTUP_IDENTITY_SECONDS;unseen=[]
        while True:
            remaining=deadline-self.monotonic()
            if remaining<=0:break
            try:
                # The startup deadline also bounds each inventory and its WMI stall retry.
                actual=self.inspect(timeout=max(.1,min(20,remaining)),budget=max(.1,remaining))
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
                actual=None;unseen.append('the inventory '+('timed out' if isinstance(exc,subprocess.TimeoutExpired) else 'failed'))
            except ValueError as exc:
                if str(exc)!=UNKNOWN_EXECUTABLE:raise              # two processes, a missing identity: refuse at once
                actual=None;unseen.append('a terminal64 row had no path')
            if actual:
                if actual['pid']!=child.pid:raise ValueError('Started terminal PID differs; no further action')
                return actual
            if child.poll() is not None:raise ValueError('Terminal exited before startup identity was observed')
            self.sleep(STARTUP_POLL_SECONDS)
        why=' ('+'; '.join(sorted(set(unseen)))+')' if unseen else ''
        raise ValueError(STARTUP_UNSEEN+' in %d s%s; inspect before recovery'%(STARTUP_IDENTITY_SECONDS,why))


class ResearchLaunch:
    """A WindowsSeedProcess whose ``start`` is a research launch (studio_research_launch).

    Only the research callers wrap their process: SeedRunner (seed, catch-up and hold-up members)
    and the first /config start of a native batch. The demo agent's monitor restarts, deploy and
    onboarding keep the plain process, so a trading or monitor MT5 never gets the job.
    """
    def __init__(self,process):self._process=process
    def start(self,config):return self._process.start(config,research=True)
    def __getattr__(self,name):return getattr(self._process,name)


def research_view(process):
    """The research view of ``process``; any other object (test doubles, placeholders) is returned as is."""
    if isinstance(process,ResearchLaunch) or not isinstance(process,WindowsSeedProcess):return process
    return ResearchLaunch(process)
