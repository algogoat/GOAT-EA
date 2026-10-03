"""Fresh Windows terminal identity check for the managed research runner.

Executable identity does not prove an EA's activity. Native queue ownership and
fresh in-terminal runtime feedback must also pass before launch.
"""
import json
import ntpath
from pathlib import Path, PureWindowsPath
import subprocess
import time


def windows_image(path):
    """The image path Windows itself opens for an inventory ExecutablePath.

    Win32 resolves `.` and `..` lexically (GetFullPathNameW) before opening a
    file, so `C:\\Program Files\\Git\\bin\\..\\usr\\bin\\bash.exe` (how Git for
    Windows, and so Claude Code, starts its shell) IS `C:\\...\\Git\\usr\\bin\\bash.exe`.
    Comparing the resolved path keeps every root check exact without refusing
    ordinary tools. A `\\\\?\\` path is opened verbatim, unresolved, so the prefix is
    stripped for comparison, and any `..` left inside one stays ambiguous. A
    `\\\\.\\` device path IS normalised by Win32, so it is stripped and resolved like
    an ordinary path. Either prefix therefore compares against the same roots and
    cannot evade them. A relative path is ambiguous as well.
    """
    text=str(path)
    verbatim=False
    if text.startswith(('\\\\?\\UNC\\','//?/UNC/')):text,verbatim='\\\\'+text[8:],True
    elif text.startswith(('\\\\?\\','\\??\\','//?/')):text,verbatim=text[4:],True
    elif text.startswith(('\\\\.\\UNC\\','//./UNC/')):text='\\\\'+text[8:]
    elif text.startswith(('\\\\.\\','//./')):text=text[4:]
    raw=PureWindowsPath(text)
    if not raw.is_absolute() or (verbatim and '..' in raw.parts):
        raise ValueError('Ambiguous Windows executable path')
    return PureWindowsPath(ntpath.normpath(text))


def _demo_selected_roots(binding):
    # Authority comes only from the trusted adapter's in-process broker proof,
    # never a persisted binding flag or a session's claimed demo bit alone.
    from studio_research_authority import DEMO_AGENT_SCOPE, require_demo_agent_scope
    from studio_installation import load_installation, read_json
    scope=DEMO_AGENT_SCOPE.get()
    if scope is None:return None
    root=Path(scope['root'])
    installation=load_installation(root/'installation.json')
    require_demo_agent_scope(root,installation,read_json(root/'session.json'))
    if (PureWindowsPath(binding['research_terminal'])!=PureWindowsPath(installation['terminal_executable'])
            or ('research_data_root' in binding and PureWindowsPath(binding['research_data_root'])!=PureWindowsPath(installation['terminal_data_root']))):
        raise ValueError('Demo process scope belongs to another selected terminal')
    return [str(PureWindowsPath(installation['terminal_executable']).parent),installation['terminal_data_root']]


def inspect_processes(binding, *, research_running=True, absent_roots=None, selected_stopped=False,
                      observation_roots=None):
    # Fixed command, no caller strings interpolated into shell syntax.
    command='ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter "Name=\'terminal64.exe\'" | Select-Object ProcessId,ExecutablePath,@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})'
    selected_roots=_demo_selected_roots(binding)
    # Read-only onboarding status can observe a selected process before a grant.
    # No launch/close caller supplies this option; it confers no action authority.
    if observation_roots is not None:selected_roots=observation_roots
    if selected_stopped:
        if research_running is not False or absent_roots is None:
            raise ValueError('Selected onboarding inventory requires stopped roots')
        selected_roots=absent_roots
    if absent_roots is not None or selected_roots is not None:
        if absent_roots is not None and research_running is not False:
            raise ValueError('Root absence scan requires a stopped research terminal')
        command='$ErrorActionPreference="Stop"; ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,@{Name="CreatedUtc";Expression={if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString("o")}}})'
    output=subprocess.check_output(['powershell','-NoProfile','-Command',command],
        text=True,encoding='utf-8-sig',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    rows=json.loads(output)
    visibility=None
    if absent_roots is not None:
        rows,visibility=stopped_candidates(rows,absent_roots)
    elif selected_roots is not None:
        rows,visibility=selected_candidates(rows,selected_roots,binding['research_terminal'])
    result=classify_processes(rows,binding,observed_unix=time.time(),research_running=research_running,
                              unrelated_roots=selected_roots)
    if visibility is not None:
        result['root_inventory']=visibility
    return result


def selected_candidates(processes,roots,executable):
    """Active demo inventory: only the exact selected image may occupy its roots."""
    target=PureWindowsPath(executable)
    other=[]; selected=[]; helpers=[]
    if not isinstance(processes,list):raise ValueError('Complete process inventory required')
    for row in processes:
        image=windows_image(row['ExecutablePath']) if row.get('ExecutablePath') else None
        if image is not None and image==target:
            selected.append(row)
        elif (image is not None and image.parent==target.parent
              and image.name.casefold()=='metatester64.exe'
              and str(row.get('Name','')).casefold()==image.name.casefold()):
            # The running terminal may own tester workers. These exact native
            # helper images are observed, never managed.
            helpers.append(dict(pid=row.get('ProcessId'),executable=str(image),created_utc=row.get('CreatedUtc')))
        else:other.append(row)
    rows,visibility=stopped_candidates(other,roots)
    # Keep the full inventory uniqueness check, including selected PIDs.
    pids=[row.get('ProcessId') for row in processes]
    if any(type(pid) is not int for pid in pids) or len(set(pids))!=len(pids):
        raise ValueError('Incomplete or ambiguous Windows process inventory')
    visibility['process_count']=len(processes)
    visibility['native_helpers']=helpers
    return rows+selected,visibility


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
            actual=windows_image(path)
            if any(actual.is_relative_to(root) for root in paths):
                raise ValueError('Executable is running under a stopped terminal root')
        else:
            unknown+=1
        if name.casefold() in ('terminal64.exe','terminal.exe'):
            selected.append(process)
    return selected,dict(roots=[str(root) for root in paths],process_count=len(processes),
        unavailable_path_count=unknown,
        limitation='Windows-visible executable paths only; unrelated unreadable system paths cannot be attributed to a terminal')


def classify_processes(processes,binding,*,observed_unix,research_running=True,unrelated_roots=None):
    if not isinstance(processes,list):raise ValueError('Complete process inventory required')
    research=PureWindowsPath(binding['research_terminal'])
    protected=PureWindowsPath(binding['protected_terminal']) if binding.get('protected_terminal') else None
    if research==protected:raise ValueError('Research and protected terminal must differ')
    result={'research':[],'protected':[]}; unrelated=[]
    roots=[PureWindowsPath(root) for root in unrelated_roots] if unrelated_roots is not None else None
    if roots is not None and (research.parent not in roots or any(not root.is_absolute() or root==PureWindowsPath(root.anchor) or '..' in root.parts for root in roots)):
        raise ValueError('Exact selected terminal roots required')
    seen=set()
    for process in processes:
        pid=process.get('ProcessId');path=process.get('ExecutablePath');created=process.get('CreatedUtc')
        if type(pid) is not int or pid<=0 or pid in seen or not path or not created:
            raise ValueError('Unknown or ambiguous terminal process identity')
        seen.add(pid)
        actual=windows_image(path)
        if actual==research:role='research'
        elif actual==protected:role='protected'
        elif roots is not None and not any(actual.is_relative_to(root) for root in roots):
            unrelated.append(dict(pid=pid,executable=str(actual),created_utc=created))
            continue
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
                **({'unrelated':unrelated} if roots is not None else {}),
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


class RollingBaseline:
    """Process identity continuity across a long start, with every gap bounded.

    Each check must see exactly the original research/protected identities and
    happen within ``max_age`` of the previous successful check, which then becomes
    the new reference. A start of any size is therefore checked as strictly as a
    small one: no gap is longer than 120 s and no identity may change.
    """
    def __init__(self, binding, first, *, revalidate=None):
        self.binding = binding
        self.revalidate = revalidate or revalidate_processes
        self.original = {role: first[role] for role in ('research', 'protected')}
        self.current = first

    def take_over(self, precheck):
        """A fresh baseline after controller-only work must equal the earlier precheck."""
        for role in ('research', 'protected'):
            if self.current[role] != precheck[role]:
                raise ValueError(role + ' terminal process changed; inspect before launch')
        return self

    def check(self, binding=None):
        current = self.revalidate(binding or self.binding, self.current)
        if any(current[role] != self.original[role] for role in ('research', 'protected')):
            raise ValueError('Terminal process changed during start; inspect before launch')
        self.current = current
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
