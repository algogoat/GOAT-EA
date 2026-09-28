"""Fresh Windows terminal identity check for the managed research runner.

Executable identity does not prove an EA's activity. Native queue ownership and
fresh in-terminal runtime feedback must also pass before launch.
"""
import json
from pathlib import PureWindowsPath
import subprocess
import time


def inspect_processes(binding, *, research_running=True, absent_roots=None):
    # Fixed command, no caller strings interpolated into shell syntax.
    command='ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    if absent_roots is not None:
        if research_running is not False:
            raise ValueError('Root absence scan requires a stopped research terminal')
        command='$ErrorActionPreference="Stop"; ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,@{Name="CreatedUtc";Expression={if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString("o")}}})'
    output=subprocess.check_output(['powershell','-NoProfile','-Command',command],
        text=True,encoding='utf-8-sig',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    rows=json.loads(output)
    visibility=None
    if absent_roots is not None:
        rows,visibility=stopped_candidates(rows,absent_roots)
    result=classify_processes(rows,binding,observed_unix=time.time(),research_running=research_running)
    if visibility is not None:
        result['root_inventory']=visibility
    return result


def stopped_candidates(processes,roots):
    """Select every named terminal and refuse any executable in stopped roots.

    This is a Windows-visible inventory, not proof against hidden/privileged
    processes. Unrelated system processes commonly have no readable image path.
    """
    if not isinstance(processes,list) or not isinstance(roots,(list,tuple)) or not roots:
        raise ValueError('Complete process inventory and stopped roots required')
    paths=[PureWindowsPath(root) for root in roots]
    if any(not root.is_absolute() or root==PureWindowsPath(root.anchor) or '..' in root.parts for root in paths):
        raise ValueError('Exact absolute terminal roots required')
    selected=[];unknown=0;seen=set()
    for process in processes:
        pid=process.get('ProcessId');name=process.get('Name');path=process.get('ExecutablePath')
        if type(pid) is not int or pid<0 or pid in seen or not isinstance(name,str) or not name:
            raise ValueError('Incomplete or ambiguous Windows process inventory')
        seen.add(pid)
        if path:
            actual=PureWindowsPath(path)
            if not actual.is_absolute() or '..' in actual.parts:
                raise ValueError('Ambiguous Windows executable path')
            if any(actual.is_relative_to(root) for root in paths):
                raise ValueError('Executable is running under a stopped terminal root')
        else:
            unknown+=1
        if name.casefold()=='terminal64.exe':
            selected.append(process)
    return selected,dict(roots=[str(root) for root in paths],process_count=len(processes),
        unavailable_path_count=unknown,
        limitation='Windows-visible executable paths only; unrelated unreadable system paths cannot be attributed to a terminal')


def classify_processes(processes,binding,*,observed_unix,research_running=True):
    if not isinstance(processes,list):raise ValueError('Complete process inventory required')
    research=PureWindowsPath(binding['research_terminal'])
    protected=PureWindowsPath(binding['protected_terminal']) if binding.get('protected_terminal') else None
    if research==protected:raise ValueError('Research and protected terminal must differ')
    result={'research':[],'protected':[]}
    seen=set()
    for process in processes:
        pid=process.get('ProcessId');path=process.get('ExecutablePath');created=process.get('CreatedUtc')
        if type(pid) is not int or pid<=0 or pid in seen or not path or not created:
            raise ValueError('Unknown or ambiguous terminal process identity')
        seen.add(pid)
        actual=PureWindowsPath(path)
        if actual==research:role='research'
        elif actual==protected:role='protected'
        else:raise ValueError('Unmapped terminal process requires ownership inspection')
        result[role].append(dict(pid=pid,executable=str(actual),created_utc=created))
    if type(research_running) is not bool:
        raise ValueError('Explicit research process state required')
    allowed_protected = (0, 1) if protected is not None and binding.get('protected_may_be_stopped') is True else (int(protected is not None),)
    if len(result['research'])!=int(research_running) or len(result['protected']) not in allowed_protected:
        raise ValueError('Expected research process state and one protected terminal required')
    if binding.get('protected_process') is not None and result['protected'] and result['protected'] != [binding['protected_process']]:
        raise ValueError('Protected peer process changed; obtain a fresh explicit review')
    return dict(observed_unix=observed_unix,**{key:(value[0] if value else None) for key,value in result.items()},
                launch_permitted=False,limitation='Process identity does not establish native batch ownership')


def revalidate_processes(binding,baseline,*,max_age=120):
    now=time.time()
    if not 0<=now-baseline['observed_unix']<=max_age:
        raise ValueError('Process baseline is stale or future-dated')
    current=inspect_processes(binding)
    for role in ('research','protected'):
        if current[role]!=baseline[role]:
            raise ValueError(role+' terminal process changed; inspect before launch')
    return current


def verify_research_exited(binding, baseline, *, max_age=120):
    """Read-only restart boundary; never stops or starts a process."""
    if not 0<=time.time()-baseline['observed_unix']<=max_age:
        raise ValueError('Process baseline is stale or future-dated')
    if not baseline.get('research') or (not baseline.get('protected') and binding.get('protected_may_be_stopped') is not True):
        raise ValueError('Both original process identities required')
    current=inspect_processes(binding,research_running=False)
    if current['protected']!=baseline['protected']:
        raise ValueError('Protected terminal process changed during research exit')
    return current
