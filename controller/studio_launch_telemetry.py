"""Read-only evidence about how the controller relaunches MT5 (goatai#1885, deploy-load child chart).

Nothing here changes a launch: the caller passes the exact Popen arguments it used, and this module
only describes them, the time between the previous terminal's exit and the launch, and the
controller process the child inherits from (session, window station, desktop, job). Environment
variables are reported by NAME only, never their values. Every probe is best-effort: a failure is
recorded as text and never raised, so telemetry can never block or alter a deploy.
"""
from datetime import datetime, timezone
import os
import subprocess

SCHEMA = 1
NAME_LIMIT = 200

# Windows process-creation flags, named for the journal (winbase.h values).
CREATION_FLAGS = (
    ('DEBUG_PROCESS', 0x00000001), ('DEBUG_ONLY_THIS_PROCESS', 0x00000002), ('CREATE_SUSPENDED', 0x00000004),
    ('DETACHED_PROCESS', 0x00000008), ('CREATE_NEW_CONSOLE', 0x00000010), ('NORMAL_PRIORITY_CLASS', 0x00000020),
    ('IDLE_PRIORITY_CLASS', 0x00000040), ('HIGH_PRIORITY_CLASS', 0x00000080), ('REALTIME_PRIORITY_CLASS', 0x00000100),
    ('CREATE_NEW_PROCESS_GROUP', 0x00000200), ('CREATE_UNICODE_ENVIRONMENT', 0x00000400),
    ('CREATE_SEPARATE_WOW_VDM', 0x00000800), ('CREATE_SHARED_WOW_VDM', 0x00001000),
    ('BELOW_NORMAL_PRIORITY_CLASS', 0x00004000), ('ABOVE_NORMAL_PRIORITY_CLASS', 0x00008000),
    ('INHERIT_PARENT_AFFINITY', 0x00010000), ('CREATE_PROTECTED_PROCESS', 0x00040000),
    ('EXTENDED_STARTUPINFO_PRESENT', 0x00080000), ('PROCESS_MODE_BACKGROUND_BEGIN', 0x00100000),
    ('PROCESS_MODE_BACKGROUND_END', 0x00200000), ('CREATE_SECURE_PROCESS', 0x00400000),
    ('CREATE_BREAKAWAY_FROM_JOB', 0x01000000), ('CREATE_PRESERVE_CODE_AUTHZ_LEVEL', 0x02000000),
    ('CREATE_DEFAULT_ERROR_MODE', 0x04000000), ('CREATE_NO_WINDOW', 0x08000000),
    ('PROFILE_USER', 0x10000000), ('PROFILE_KERNEL', 0x20000000), ('PROFILE_SERVER', 0x40000000),
    ('CREATE_IGNORE_SYSTEM_DEFAULT', 0x80000000))
STARTF_FLAGS = (('STARTF_USESHOWWINDOW', 0x1), ('STARTF_USESIZE', 0x2), ('STARTF_USEPOSITION', 0x4),
                ('STARTF_USECOUNTCHARS', 0x8), ('STARTF_USEFILLATTRIBUTE', 0x10), ('STARTF_RUNFULLSCREEN', 0x20),
                ('STARTF_FORCEONFEEDBACK', 0x40), ('STARTF_FORCEOFFFEEDBACK', 0x80), ('STARTF_USESTDHANDLES', 0x100),
                ('STARTF_USEHOTKEY', 0x200), ('STARTF_TITLEISLINKNAME', 0x800), ('STARTF_TITLEISAPPID', 0x1000),
                ('STARTF_PREVENTPINNING', 0x2000), ('STARTF_UNTRUSTEDSOURCE', 0x8000))
SHOW_WINDOW = {0: 'SW_HIDE', 1: 'SW_SHOWNORMAL', 2: 'SW_SHOWMINIMIZED', 3: 'SW_SHOWMAXIMIZED', 4: 'SW_SHOWNOACTIVATE',
               5: 'SW_SHOW', 6: 'SW_MINIMIZE', 7: 'SW_SHOWMINNOACTIVE', 8: 'SW_SHOWNA', 9: 'SW_RESTORE',
               10: 'SW_SHOWDEFAULT', 11: 'SW_FORCEMINIMIZE'}
JOB_LIMIT_FLAGS = (('WORKINGSET', 0x1), ('PROCESS_TIME', 0x2), ('JOB_TIME', 0x4), ('ACTIVE_PROCESS', 0x8),
                   ('AFFINITY', 0x10), ('PRIORITY_CLASS', 0x20), ('PRESERVE_JOB_TIME', 0x40), ('SCHEDULING_CLASS', 0x80),
                   ('PROCESS_MEMORY', 0x100), ('JOB_MEMORY', 0x200), ('DIE_ON_UNHANDLED_EXCEPTION', 0x400),
                   ('BREAKAWAY_OK', 0x800), ('SILENT_BREAKAWAY_OK', 0x1000), ('KILL_ON_JOB_CLOSE', 0x2000),
                   ('SUBSET_AFFINITY', 0x4000))
JOB_UI_FLAGS = (('HANDLES', 0x1), ('READCLIPBOARD', 0x2), ('WRITECLIPBOARD', 0x4), ('SYSTEMPARAMETERS', 0x8),
                ('DISPLAYSETTINGS', 0x10), ('GLOBALATOMS', 0x20), ('DESKTOP', 0x40), ('EXITWINDOWS', 0x80))
# Set by Windows for every logon (CreateEnvironmentBlock / winlogon), not stored in the registry keys read below.
LOGON_DEFAULT_NAMES = frozenset((
    'ALLUSERSPROFILE', 'APPDATA', 'LOCALAPPDATA', 'CommonProgramFiles', 'CommonProgramFiles(x86)', 'CommonProgramW6432',
    'COMPUTERNAME', 'HOMEDRIVE', 'HOMEPATH', 'LOGONSERVER', 'ProgramData', 'ProgramFiles',
    'ProgramFiles(x86)', 'ProgramW6432', 'PUBLIC', 'SystemDrive', 'SystemRoot', 'USERDOMAIN',
    'USERDOMAIN_ROAMINGPROFILE', 'USERNAME', 'USERPROFILE', 'SESSIONNAME'))
ENV_REGISTRY_KEYS = (('HKLM', r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                     ('HKCU', 'Environment'), ('HKCU', 'Volatile Environment'))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def gap_ms(later, earlier):
    """Milliseconds from ``earlier`` to ``later`` (ISO UTC strings), or None when either is missing or unreadable."""
    try:
        return round((datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds() * 1000)
    except (TypeError, ValueError):
        return None


def named_flags(value, table):
    names = [name for name, bit in table if value & bit]
    rest = value & ~sum(bit for _, bit in table)
    return names + (['0x%08X' % rest] if rest else [])


def _handle(value):
    if value is None:
        return 'inherit'
    for name in ('DEVNULL', 'PIPE', 'STDOUT'):
        if value is getattr(subprocess, name):
            return name
    return 'file_descriptor' if isinstance(value, int) else type(value).__name__


def _names(values):
    return sorted(values, key=str.casefold)[:NAME_LIMIT]


def env_name_diff(child, parent):
    """Names in ``child`` but not ``parent`` (added) and in ``parent`` but not ``child`` (removed); never values."""
    child_names = {name.casefold(): name for name in child}
    parent_names = {name.casefold(): name for name in parent}
    return dict(added=_names(child_names[k] for k in child_names.keys() - parent_names.keys()),
                removed=_names(parent_names[k] for k in parent_names.keys() - child_names.keys()))


def logon_env_names(*, winreg=None):
    """Variable names a fresh Explorer-started process gets: the registry environment plus the logon defaults."""
    if winreg is None:
        import winreg
    names = set(LOGON_DEFAULT_NAMES)
    hives = dict(HKLM=winreg.HKEY_LOCAL_MACHINE, HKCU=winreg.HKEY_CURRENT_USER)

    def read(key):
        index = 0
        while True:
            try:
                names.add(winreg.EnumValue(key, index)[0])
            except OSError:
                return
            index += 1

    for hive, path in ENV_REGISTRY_KEYS:
        with winreg.OpenKey(hives[hive], path) as key:
            read(key)
            if path == 'Volatile Environment':  # per-session values live in a numbered subkey
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    with winreg.OpenKey(key, sub) as child:
                        read(child)
                    index += 1
    return names


def popen_facts(arguments, options, *, environ=None, logon_names=None):
    """The exact Popen call described for the journal: argv (paths only), the command line Windows receives,
    cwd, creation flags by name, the STARTUPINFO Python builds, std handles, handle inheritance and env names."""
    environ = os.environ if environ is None else environ
    flags = int(options.get('creationflags', 0) or 0)
    std = {name: _handle(options.get(name)) for name in ('stdin', 'stdout', 'stderr')}
    redirected = all(value != 'inherit' for value in std.values())
    close_fds = options.get('close_fds', True)
    info = options.get('startupinfo')
    startf = (getattr(info, 'dwFlags', 0) or 0) | (0x100 if redirected else 0)
    show = getattr(info, 'wShowWindow', 0) if info is not None else None
    if startf & 0x1:
        show_window = SHOW_WINDOW.get(show, str(show))
    else:
        show_window = 'not set (STARTF_USESHOWWINDOW absent: the GUI uses its own first ShowWindow, SW_SHOWDEFAULT)'
    facts = dict(
        argv=[str(value) for value in arguments],
        command_line=subprocess.list2cmdline([str(value) for value in arguments]),
        executable=str(arguments[0]), cwd=options.get('cwd'),
        creationflags=flags, creationflags_names=named_flags(flags, CREATION_FLAGS),
        startupinfo='default (none passed)' if info is None else 'passed',
        startupinfo_flags=named_flags(startf, STARTF_FLAGS), show_window=show_window,
        stdin=std['stdin'], stdout=std['stdout'], stderr=std['stderr'],
        close_fds='default (True)' if 'close_fds' not in options else bool(close_fds),
        # CPython on Windows: close_fds with redirected std handles passes only those handles through
        # PROC_THREAD_ATTRIBUTE_HANDLE_LIST (bInheritHandles=TRUE); otherwise no handle is inherited.
        inherited_handles=('only the redirected std handles (PROC_THREAD_ATTRIBUTE_HANDLE_LIST)'
                           if close_fds and redirected else 'none' if close_fds else 'every inheritable handle'),
        env='inherited (env=None: the controller environment unchanged)' if options.get('env') is None else 'explicit')
    child_env = environ if options.get('env') is None else options['env']
    facts['env_child_vs_controller'] = env_name_diff(child_env, environ)
    try:
        baseline = logon_env_names() if logon_names is None else logon_names
        facts['env_controller_vs_logon'] = env_name_diff(environ, {name: None for name in baseline})
        facts['env_controller_vs_logon']['baseline'] = 'registry HKLM+HKCU Environment, HKCU Volatile Environment, logon defaults'
    except Exception as exc:  # telemetry never blocks a launch
        facts['env_controller_vs_logon'] = dict(error=type(exc).__name__ + ': ' + str(exc)[:200])
    return facts


def controller_context(*, ctypes_module=None):
    """Where the controller (and so the child MT5) runs: pid, session, window station, desktop, job."""
    result = dict(pid=os.getpid())
    try:
        if ctypes_module is None:
            import ctypes as ctypes_module
        from ctypes import wintypes
        kernel32 = ctypes_module.WinDLL('kernel32', use_last_error=True)
        user32 = ctypes_module.WinDLL('user32', use_last_error=True)
        session = wintypes.DWORD()
        if kernel32.ProcessIdToSessionId(os.getpid(), ctypes_module.byref(session)):
            result['session_id'] = session.value

        def object_name(handle):
            if not handle:
                return None
            buffer = ctypes_module.create_unicode_buffer(256); needed = wintypes.DWORD()
            user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes_module.c_int, ctypes_module.c_void_p,
                                                         wintypes.DWORD, ctypes_module.POINTER(wintypes.DWORD))
            if user32.GetUserObjectInformationW(handle, 2, buffer, ctypes_module.sizeof(buffer), ctypes_module.byref(needed)):
                return buffer.value
            return None

        user32.GetProcessWindowStation.restype = wintypes.HANDLE
        user32.GetThreadDesktop.restype = wintypes.HANDLE
        result['window_station'] = object_name(user32.GetProcessWindowStation())
        result['desktop'] = object_name(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()))
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        in_job = wintypes.BOOL()
        kernel32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes_module.POINTER(wintypes.BOOL))
        if kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes_module.byref(in_job)):
            result['in_job'] = bool(in_job.value)
        if result.get('in_job'):
            kernel32.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes_module.c_int, ctypes_module.c_void_p,
                                                           wintypes.DWORD, ctypes_module.POINTER(wintypes.DWORD))
            # JOBOBJECT_BASIC_LIMIT_INFORMATION (class 2): LimitFlags is the DWORD after two LARGE_INTEGERs.
            basic = (ctypes_module.c_byte * 64)()
            if kernel32.QueryInformationJobObject(None, 2, basic, ctypes_module.sizeof(basic), None):
                limit = int.from_bytes(bytes(basic[16:20]), 'little')
                result['job_limit_flags'] = named_flags(limit, JOB_LIMIT_FLAGS)
            ui = wintypes.DWORD()
            if kernel32.QueryInformationJobObject(None, 4, ctypes_module.byref(ui), 4, None):
                result['job_ui_restrictions'] = named_flags(ui.value, JOB_UI_FLAGS)
    except Exception as exc:  # telemetry never blocks a launch
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:200]
    return result


def launch_record(*, arguments, options, previous, pre_launch_check, launch_started_utc, popen_returned_utc, pid,
                  environ=None, logon_names=None, context=None):
    """The journal block for one MT5 launch. Never raises: a failed probe is kept as an ``error`` field."""
    record = dict(schema=SCHEMA, launch_started_utc=launch_started_utc, popen_returned_utc=popen_returned_utc,
                  popen_ms=gap_ms(popen_returned_utc, launch_started_utc), pid=pid, previous_terminal=previous,
                  pre_launch_check=pre_launch_check)
    previous = previous or {}
    # The previous MT5 exited after exit_after_utc (a moment it was still listed, or the close request) and
    # before observed_gone_utc (the end of the first inventory that no longer listed it).
    record['gap_ms'] = dict(
        exit_to_launch_at_least=gap_ms(launch_started_utc, previous.get('observed_gone_utc')),
        exit_to_launch_at_most=gap_ms(launch_started_utc, previous.get('exit_after_utc')),
        pre_launch_check_to_launch=gap_ms(launch_started_utc, (pre_launch_check or {}).get('finished_utc')))
    record['previous_present_at_launch'] = (pre_launch_check or {}).get('present')
    try:
        record['popen'] = popen_facts(arguments, options, environ=environ, logon_names=logon_names)
    except Exception as exc:
        record['popen'] = dict(error=type(exc).__name__ + ': ' + str(exc)[:200])
    record['controller'] = controller_context() if context is None else context
    return record
