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
    from studio_process_query import powershell_text
    return json.loads(powershell_text(script,purpose='driver process inventory'))


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
        # A publisher this module resumed (resume() below) runs the retained journal: `run-batch --resume`, no new budget.
        if args[6:] not in (expected,expected+['--min-free-bytes',str(journal['min_free_bytes'])],resume_arguments(job_id)):
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


RESUME_FAILED='PUBLISHER_RESUME_FAILED'


def resume_arguments(job_id):
    """The one resume form: the retained journal's own deadline, budget and disk guard (run() refuses new ones)."""
    return ['run-batch','--job-id',job_id,'--resume']


def _launch_publisher(argv):
    """Start the exact launcher with no window. CREATE_NO_WINDOW still gives this console program its own (hidden)
    console, not this process's, so a later suspension can attach to it and Ctrl+C it alone."""
    from studio_subprocess import background_creationflags
    child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,
                           creationflags=background_creationflags())
    return child.pid


def resume(controller, job_id, folder, *, launch=None, rows_fn=None, clock=time):
    """Relaunch the publisher suspend() stopped, exactly as identify() verified it, on its retained journal.

    goatai#2350 6099078698 / 6101325773 (R1): a monitor restart whose post-suspend readback fails resumes the publisher it
    suspended and then refuses. Only the verified launcher and installation, the same job, and `--resume` (the journal's
    own deadline and budget, never a fresh value); the journal must be byte-identical to the one suspended. One attempt,
    never a loop: any failure writes publisher-resume-failed.json and raises PUBLISHER_RESUME_FAILED naming the one step.
    Returns the publisher-resumed.json record."""
    from studio_refusal import Refusal
    launch=launch or _launch_publisher;rows_fn=rows_fn or processes
    intent_path,done=folder/'publisher-stop-intent.json',folder/'publisher-stopped.json'
    resumed_path,failed_path=folder/'publisher-resumed.json',folder/'publisher-resume-failed.json'
    if resumed_path.exists() or failed_path.exists():
        raise ValueError('A publisher resume is already recorded for this suspension; inspect it, never repeat')
    stopped=read_json(done);intent=read_json(intent_path)
    journal_path=controller.root/'batch-drivers'/(job_id+'.json')
    base=dict(schema_version=1,job_id=job_id,suspension_sha256=hashlib.sha256(done.read_bytes()).hexdigest(),
              old_pids=dict(python=intent['identity']['python']['ProcessId'],launcher=intent['identity']['launcher']['ProcessId']),
              journal_sha256_at_suspension=stopped['journal_sha256'])
    try:
        if stopped.get('supervisor_exited') is not True or stopped['intent_sha256']!=hashlib.sha256(intent_path.read_bytes()).hexdigest():
            raise ValueError('the suspension evidence changed')
        now_sha=hashlib.sha256(journal_path.read_bytes()).hexdigest()
        base['journal_sha256_at_resume']=now_sha
        if now_sha!=stopped['journal_sha256']:
            raise ValueError('the batch journal changed while the publisher was suspended')
        launcher=intent['identity']['launcher']
        original=arguments(launcher['CommandLine'])
        if original[1:4]!=['studio','--installation',str(controller.root/'installation.json')]:
            raise ValueError('the suspended launcher command is not this installation\'s publisher')
        argv=[launcher['ExecutablePath']]+original[1:4]+resume_arguments(job_id)
        base['argv']=argv
        pid=launch(argv)
        deadline=clock.monotonic()+20
        while True:
            rows=rows_fn()
            child=[r for r in rows if r.get('ParentProcessId')==pid and Path(r.get('ExecutablePath') or '').name.lower()=='python.exe'
                   and arguments(r.get('CommandLine') or '')[6:]==resume_arguments(job_id)]
            if child:break
            if not any(r['ProcessId']==pid for r in rows):raise ValueError('the relaunched publisher exited before its driver started')
            if clock.monotonic()>=deadline:raise ValueError('the relaunched publisher\'s driver did not appear within 20 s')
            clock.sleep(.5)
        record=dict(base,status='resumed',new_pids=dict(launcher=pid,python=child[0]['ProcessId']),resumed_utc=clock.time())
        write_json(resumed_path,record)
        return record
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        reason=str(exc)[:300]
        write_json(failed_path,dict(base,status='resume_failed',reason=reason,failed_utc=clock.time()))
        raise Refusal('GOAT stopped the research run to restart the monitor, then could not restart that run (%s). It is '
                      'paused, not lost: press Continue on the batch in GOAT (run-batch --job-id %s --resume) to carry on '
                      'from where it stopped.' % (reason,job_id),RESUME_FAILED,job_id=job_id,receipt=str(failed_path)) from exc


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
