"""Gracefully interrupt one verified old Python supervisor, retaining its budget.

This never signals MT5 and never calls TerminateProcess/Stop-Process. The separate
suspension journal is not native stop proof and does not edit the batch journal.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate


def processes():
    script='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @(\'python.exe\',\'goat.exe\')} | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    return json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],text=True,encoding='utf-8-sig',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))


def arguments(command):
    from ctypes import wintypes as w
    shell=ctypes.WinDLL('shell32'); kernel=ctypes.WinDLL('kernel32')
    shell.CommandLineToArgvW.argtypes=[w.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(w.LPWSTR)
    kernel.LocalFree.argtypes=[w.HLOCAL]
    count=ctypes.c_int(); ptr=shell.CommandLineToArgvW(command,ctypes.byref(count))
    if not ptr:raise ValueError('Unable to parse driver process arguments')
    try:return [ptr[i] for i in range(count.value)]
    finally:kernel.LocalFree(ctypes.cast(ptr,w.HLOCAL))


def require_no_publishers(controller, *, rows=None, allowed=()):
    """Exclude only this caller/its exact launcher and explicitly verified pair."""
    rows=processes() if rows is None else rows
    permitted={os.getpid(),*allowed}
    for row in rows:
        if (row['ProcessId']==os.getppid()
                and Path(row.get('ExecutablePath') or '')==Path(sys.executable).parent.parent/'goat.exe'):
            permitted.add(row['ProcessId'])
    needle=str(controller.root).replace('\\','/').casefold()
    for row in rows:
        if row['ProcessId'] in permitted:continue
        command=row.get('CommandLine')
        if not command:raise ValueError('Unknown publisher command line; inspect before recovery')
        args=arguments(command)
        if any(needle in arg.replace('\\','/').casefold() for arg in args):
            raise ValueError('Another controller publisher references this installation; recovery refused')


def identify(controller, job_id, journal):
    rows=processes(); found=[]
    for row in rows:
        if Path(row.get('ExecutablePath') or '').name.lower()!='python.exe':continue
        args=arguments(row.get('CommandLine') or '')
        if 'run-batch' not in args or job_id not in args:continue
        if len(args)<10 or args[1]!='-B' or Path(args[2]).name!='goat_agent.py' or args[3:6]!=['studio','--installation',str(controller.root/'installation.json')]:
            raise ValueError('Unrecognized batch publisher command; no signal')
        expected=['run-batch','--job-id',job_id,'--max-seconds',str(journal['max_seconds'])]
        if args[6:] not in (expected,expected+['--min-free-bytes',str(journal['min_free_bytes'])]):
            raise ValueError('Publisher command differs from original journal')
        kit=Path(args[2]).parent.parent
        if Path(row['ExecutablePath'])!=kit/'python/python.exe':raise ValueError('Publisher runtime path differs')
        parents=[p for p in rows if p['ProcessId']==row['ParentProcessId']]
        if len(parents)!=1 or Path(parents[0].get('ExecutablePath') or '')!=kit/'goat.exe':
            raise ValueError('Exact GOAT launcher parent required')
        parent=parents[0]
        if arguments(parent['CommandLine'])[1:]!=args[3:]:raise ValueError('Launcher arguments differ')
        if not row.get('CreatedUtc') or not parent.get('CreatedUtc'):raise ValueError('Process creation identity unavailable')
        found.append(dict(python=row,launcher=parent))
    if len(found)!=1:raise ValueError('Exactly one original publisher must be identified')
    require_no_publishers(controller,rows=rows,allowed=[item['ProcessId'] for item in found[0].values()])
    return found[0]


def interrupt(identity):
    # A helper joins only the verified driver's isolated console. It refuses
    # consoles shared with any unrelated process before generating Ctrl+C.
    script=r'''
import ctypes,json,os,sys,time,datetime
from ctypes import wintypes as w
r=json.loads(sys.stdin.read()); k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE]
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
k.GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME)]
k.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
handles=[]
for item in r.values():
    h=k.OpenProcess(0x1000|0x100000,False,item['ProcessId'])
    if not h:raise RuntimeError('Cannot retain publisher process identity')
    handles.append(h)
    name=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(name))
    times=[w.FILETIME() for _ in range(4)]
    if not k.QueryFullProcessImageNameW(h,0,name,ctypes.byref(size)) or os.path.normcase(name.value)!=os.path.normcase(item['ExecutablePath']):raise RuntimeError('Publisher executable changed')
    if not k.GetProcessTimes(h,*[ctypes.byref(t) for t in times]):raise RuntimeError('Publisher creation time unavailable')
    ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    actual=datetime.datetime(1601,1,1,tzinfo=datetime.timezone.utc)+datetime.timedelta(microseconds=ticks//10)
    expected=datetime.datetime.fromisoformat(item['CreatedUtc'].replace('Z','+00:00'))
    if actual!=expected:raise RuntimeError('Publisher creation time changed')
k.FreeConsole()
if not k.AttachConsole(r['python']['ProcessId']):raise RuntimeError('Cannot attach verified driver console')
try:
    if not k.SetConsoleCtrlHandler(None,True):raise RuntimeError('Cannot protect signal helper')
    ids=(w.DWORD*32)();n=k.GetConsoleProcessList(ids,32)
    allowed={r['python']['ProcessId'],r['launcher']['ProcessId'],os.getpid()}
    if not 1<=n<=32 or not set(ids[:n])<=allowed or r['python']['ProcessId'] not in ids[:n]:raise RuntimeError('Driver console has unrelated processes')
    for h in handles:
        code=w.DWORD()
        if not k.GetExitCodeProcess(h,ctypes.byref(code)) or code.value!=259:raise RuntimeError('Publisher exited before signal')
    if not k.GenerateConsoleCtrlEvent(0,0):raise RuntimeError('Graceful Ctrl+C failed')
    time.sleep(.5)
finally:
    k.FreeConsole()
    for h in handles:k.CloseHandle(h)
'''
    # Revalidate immediately; console membership also refuses PID reuse by a
    # different process family. The parent operation checks identities again.
    rows=processes()
    if any(item not in rows for item in identity.values()):raise ValueError('Publisher identity changed before suspension')
    subprocess.run([sys.executable,'-c',script],input=json.dumps(identity),text=True,check=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def suspend(controller, job, folder, *, clock=time):
    path=controller.root/'batch-drivers'/(job['job_id']+'.json')
    journal=read_json(path)
    if (journal.get('attempt_id')!=job['launch_intent']['attempt_id'] or journal.get('stopped') is not False
            or journal['binding']['job_id']!=job['job_id'] or journal['binding']['generation']!=controller.state()['generation']):
        raise ValueError('Exact unfinished supervisor journal required')
    intent_path=folder/'publisher-stop-intent.json';done=folder/'publisher-stopped.json'
    if intent_path.exists():intent=read_json(intent_path)
    else:
        identity=identify(controller,job['job_id'],journal)
        intent=dict(schema_version=1,identity=identity,journal=journal,
                    journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    native_stop_claimed=False,signal='normal_ctrl_c',created_utc=clock.time())
        write_json(intent_path,intent)
        interrupt(identity)
    deadline=clock.monotonic()+20
    while True:
        rows=processes()
        live=[p for p in rows if p['ProcessId'] in {v['ProcessId'] for v in intent['identity'].values()}]
        if not live:break
        if any(p not in intent['identity'].values() for p in live):raise ValueError('Publisher identity changed; no adoption')
        if clock.monotonic()>=deadline:raise ValueError('Publisher did not stop; monitor restart refused; signal is not repeated')
        clock.sleep(.2)
    with exclusive_gate(controller.root/'batch-driver-gate'):
        final=read_json(path)
        for field in ('binding','started_wall','deadline_wall','max_seconds','min_free_bytes','attempt_id'):
            if final[field]!=intent['journal'][field]:raise ValueError('Original supervisor budget or binding changed')
        record=dict(schema_version=1,supervisor_exited=True,native_stop_claimed=False,
                    intent_sha256=hashlib.sha256(intent_path.read_bytes()).hexdigest(),
                    journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),journal=final)
        if done.exists() and read_json(done)!=record:raise ValueError('Suspension evidence changed')
        if not done.exists():write_json(done,record)
        return record
