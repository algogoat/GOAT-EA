"""Identify the shipped, waiting desktop migration client during receipt CAS, and the
requesting desktop RPC client during a reviewed handover's inspect/apply.

This is local process coordination, not an OS-user security boundary. Never
recognize arbitrary goat.exe instances or native Studio operations as clients.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import re

from studio_installation import read_json


def windows_argv(command):
    if os.name != 'nt' or not isinstance(command, str) or not command:
        return []
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        return []
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(pointer)


def hashed_bundle():
    """(launcher, python, entry) of this manifest-hashed bundle, casefolded; None on any doubt.

    The root comes from the executing controller, never from a process argument."""
    root = Path(__file__).resolve().parent.parent
    manifest = read_json(root/'manifest.json')
    required = ['goat.exe', 'python/python.exe', 'controller/goat_agent.py',
                'controller/studio_desktop_client.py', 'controller/studio_handover.py']
    files = manifest['files']
    for name in required:
        matches = [f for f in files if f['path'] == name]
        if len(matches) != 1:
            return None
        target = root/name
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            return None
        raw = target.read_bytes()
        if len(raw) != matches[0]['size'] or hashlib.sha256(raw).hexdigest() != matches[0]['sha256']:
            return None
    return tuple(str((root/name).resolve()).casefold() for name in required[:3])


def agent_child(rows, row, args, python, entry):
    """The one python -B goat_agent.py child forwarding exactly args[1:], else None."""
    children = [child for child in rows if child.get('ParentProcessId') == row['ProcessId']]
    if len(children) != 1:
        return None
    child = children[0]
    child_args = windows_argv(child.get('CommandLine'))
    if (str(child.get('ExecutablePath', '')).casefold() != python
            or len(child_args) != len(args) + 2
            or child_args[0].casefold() != python or child_args[1] != '-B'
            or child_args[2].casefold() != entry or child_args[3:] != args[1:]):
        return None
    return child


# Read-only desktop RPC calls an agent keeps open while the app runs its own switch-plan /
# switch-apply child (P-beta40-prepare-switch-self-pid). goat_agent.py's desktop surface is only an
# HTTP client of the app; it never imports or runs a controller.
DESKTOP_RPC_METHODS = ('onboarding.prepareSwitch', 'onboarding.switchStatus', 'events.wait')
DESKTOP_RPC_FLAGS = {'--params', '--request-id', '--timeout-ms', '--session', '--data-dir'}


def desktop_rpc_clients(controller, rows):
    """Recognize bundle-file-hashed `goat.exe desktop <method>` launcher/child pairs.

    Only for the reviewed handover's inspect/apply process fence. Every pair must name one of
    DESKTOP_RPC_METHODS with flags from DESKTOP_RPC_FLAGS (as `--flag value`) and have exactly one
    forwarding goat_agent.py child. Several pairs may be open at once (a prepareSwitch call and an
    events.wait). Anything else, including `studio`/`demo` launchers, stays fenced.
    """
    try:
        bundle = hashed_bundle()
        if bundle is None:
            return set()
        launcher, python, entry = bundle
        clients = set()
        for row in rows:
            if str(row.get('ExecutablePath', '')).casefold() != launcher:
                continue
            args = windows_argv(row.get('CommandLine'))
            if (len(args) < 3 or args[0].casefold() != launcher or args[1] != 'desktop'
                    or args[2] not in DESKTOP_RPC_METHODS):
                continue
            flags = args[3:]
            if len(flags) % 2 or len(set(flags[::2])) != len(flags[::2]):
                continue
            options = dict(zip(flags[::2], flags[1::2]))
            if (options.keys() - DESKTOP_RPC_FLAGS
                    or any(not value or value.startswith('-') for value in options.values())
                    or ('--request-id' in options
                        and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', options['--request-id']))
                    or ('--session' in options
                        and not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', options['--session']))
                    or ('--timeout-ms' in options and (not options['--timeout-ms'].isdecimal()
                        or not 1 <= int(options['--timeout-ms']) <= 3600000))):
                continue
            child = agent_child(rows, row, args, python, entry)
            if child is None:
                continue
            clients.update((row['ProcessId'], child['ProcessId']))
        return clients
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def qualification_clients(controller, rows):
    """Recognize a bundle-file-hashed launcher/child pair for this target.

The root comes from the executing controller, never from a process argument.
Called only for an already completed PARK receipt verification/replacement.
    Any missing, changed or ambiguous evidence leaves the normal process fence on.
    File hashes do not attest the running image: inventory precedes file reads.
"""
    try:
        bundle = hashed_bundle()
        if bundle is None:
            return set()
        launcher, python, entry = bundle
        clients = set()
        for row in rows:
            if str(row.get('ExecutablePath', '')).casefold() != launcher:
                continue
            args = windows_argv(row.get('CommandLine'))
            if (len(args) < 5 or args[0].casefold() != launcher
                    or args[1] != 'desktop'
                    or args[2] not in ('suite.installInternalQualification', 'suite.migrateInstallation')):
                continue
            flags = args[3:]
            if len(flags) % 2 or len(set(flags[::2])) != len(flags[::2]):
                continue
            options = dict(zip(flags[::2], flags[1::2]))
            if (not {'--params', '--request-id'} <= options.keys()
                    or options.keys() - {'--params', '--request-id', '--timeout-ms'}
                    or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', options['--request-id'])
                    or ('--timeout-ms' in options and (not options['--timeout-ms'].isdecimal()
                        or not 1 <= int(options['--timeout-ms']) <= 3600000))):
                continue
            params_path = Path(options['--params'])
            if not params_path.is_absolute():
                continue
            params = read_json(params_path)
            if (not isinstance(params, dict) or not isinstance(params.get('parkReviewId'), str)
                    or not re.fullmatch(r'[a-f0-9]{32}', params['parkReviewId'])):
                continue
            if args[2] == 'suite.migrateInstallation':
                if set(params) != {'receiptPath', 'parkReviewId'} or not isinstance(params['receiptPath'], str):
                    continue
                receipt = Path(params['receiptPath'])
                registered = Path(controller.install['receipt_path'])
                expected = Path(controller.install['controller_state_root'])/'installation.json'
                if (not receipt.is_absolute() or not registered.is_absolute() or receipt.is_symlink()
                        or receipt.resolve() != expected.resolve() or registered.resolve() != expected.resolve()):
                    continue
            else:
                expected = dict(terminalExecutable=controller.install['terminal_executable'],
                                terminalDataRoot=controller.install['terminal_data_root'],
                                portable=Path(controller.install['terminal_data_root']) ==
                                         Path(controller.install['terminal_executable']).parent)
                if (set(params) != {'selection', 'accountId', 'buildId', 'parkReviewId'}
                        or params['selection'] != expected
                        or not re.fullmatch(r'[1-9][0-9]{3,19}', str(params['accountId']))
                        or not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', str(params['buildId']))):
                    continue
            child = agent_child(rows, row, args, python, entry)
            if child is None:
                continue
            clients.update((row['ProcessId'], child['ProcessId']))
        # Concurrent setup callers remain ambiguous even if individually valid.
        return clients if len(clients) == 2 else set()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()
