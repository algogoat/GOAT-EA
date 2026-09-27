"""Identify the shipped, waiting desktop qualification client during receipt CAS.

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


def qualification_clients(controller, rows):
    """Recognize a bundle-file-hashed launcher/child pair for this target.

The root comes from the executing controller, never from a process argument.
Called only for an already completed PARK receipt verification/replacement.
    Any missing, changed or ambiguous evidence leaves the normal process fence on.
    File hashes do not attest the running image: inventory precedes file reads.
"""
    root = Path(__file__).resolve().parent.parent
    try:
        manifest = read_json(root/'manifest.json')
        required = ['goat.exe', 'python/python.exe', 'controller/goat_agent.py',
                    'controller/studio_desktop_client.py', 'controller/studio_handover.py']
        files = manifest['files']
        for name in required:
            matches = [f for f in files if f['path'] == name]
            if len(matches) != 1:
                return set()
            target = root/name
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                return set()
            raw = target.read_bytes()
            if len(raw) != matches[0]['size'] or hashlib.sha256(raw).hexdigest() != matches[0]['sha256']:
                return set()
        launcher, python, entry = (str((root/name).resolve()).casefold() for name in required[:3])
        clients = set()
        for row in rows:
            if str(row.get('ExecutablePath', '')).casefold() != launcher:
                continue
            args = windows_argv(row.get('CommandLine'))
            if (len(args) < 5 or args[0].casefold() != launcher
                    or args[1:3] != ['desktop', 'suite.installInternalQualification']):
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
            expected = dict(terminalExecutable=controller.install['terminal_executable'],
                            terminalDataRoot=controller.install['terminal_data_root'],
                            portable=Path(controller.install['terminal_data_root']) ==
                                     Path(controller.install['terminal_executable']).parent)
            if (set(params) != {'selection', 'accountId', 'buildId', 'parkReviewId'}
                    or params['selection'] != expected
                    or not re.fullmatch(r'[a-f0-9]{32}', str(params['parkReviewId']))
                    or not re.fullmatch(r'[1-9][0-9]{3,19}', str(params['accountId']))
                    or not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', str(params['buildId']))):
                continue
            children = [child for child in rows if child.get('ParentProcessId') == row['ProcessId']]
            if len(children) != 1:
                continue
            child = children[0]
            child_args = windows_argv(child.get('CommandLine'))
            if (str(child.get('ExecutablePath', '')).casefold() != python
                    or len(child_args) != len(args) + 2
                    or child_args[0].casefold() != python or child_args[1] != '-B'
                    or child_args[2].casefold() != entry or child_args[3:] != args[1:]):
                continue
            clients.update((row['ProcessId'], child['ProcessId']))
        # Concurrent setup callers remain ambiguous even if individually valid.
        return clients if len(clients) == 2 else set()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()
