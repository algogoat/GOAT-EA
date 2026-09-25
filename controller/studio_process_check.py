"""Fresh Windows terminal identity check for the managed research runner.

Executable identity does not prove an EA's activity. Native queue ownership and
fresh in-terminal runtime feedback must also pass before launch.
"""
import json
from pathlib import PureWindowsPath
import subprocess
import time


def inspect_processes(binding, *, research_running=True):
    # Fixed command, no caller strings interpolated into shell syntax.
    command='ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    output=subprocess.check_output(['powershell','-NoProfile','-Command',command],
        text=True,encoding='utf-8-sig',timeout=20)
    return classify_processes(json.loads(output),binding,observed_unix=time.time(),research_running=research_running)


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
    if len(result['research'])!=int(research_running) or len(result['protected'])!=int(protected is not None):
        raise ValueError('Expected research process state and one protected terminal required')
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
    if not baseline.get('research') or not baseline.get('protected'):
        raise ValueError('Both original process identities required')
    current=inspect_processes(binding,research_running=False)
    if current['protected']!=baseline['protected']:
        raise ValueError('Protected terminal process changed during research exit')
    return current
