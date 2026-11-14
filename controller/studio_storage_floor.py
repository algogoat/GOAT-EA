"""Output-root storage floor (Claude-Mac, goatai#2750 6877948300, after Ops 6877900019).

A catch-up plan with an ``output_root`` is refused when the drive's projected free space at the plan's end falls under
that drive's floor:

    projected = free now - members x unit

``unit`` is the LARGEST on-disk size of a finished unit already in that output root, never a mean (compression ratios
vary by unit). On disk means the compressed size (``GetCompressedFileSizeW`` on Windows), summed over the unit's files.
A finished unit is a ``c.<10 hex>\\<5 digits>`` folder holding its record (``evidence-version.json`` or
``build-migration-retest.json``). While none is finished, a unit counts as UNIT_FALLBACK_BYTES (128 MiB).

Floors: 15 GB on the Windows system drive and 5 GB on any other drive, unless the machine policy file overrides them.
The file is ``%LOCALAPPDATA%\\GOAT Portfolio Desktop\\storage-floors.json``, beside the ``suite`` folder, so every
terminal's controller on the machine reads the same file. ``GOAT_STORAGE_FLOORS`` names another path:

    {"schema": "goat-storage-floors-v1", "floors_gb": {"C:": 15, "G:": 50}}

A file that exists but cannot be read, or breaks that shape, refuses the plan (fail closed) and names the file. The
refusal names the projection, the floor and the policy file; a passing check returns the same report.
"""
import json
import os
import re
from pathlib import Path

SCHEMA = 'goat-storage-floors-v1'
POLICY_ENV = 'GOAT_STORAGE_FLOORS'
POLICY_NAME = 'storage-floors.json'
GB = 1000 ** 3
SYSTEM_FLOOR_GB = 15
OTHER_FLOOR_GB = 5
UNIT_FALLBACK_BYTES = 128 * 1024 * 1024
UNIT_RECORDS = ('evidence-version.json', 'build-migration-retest.json')
MAX_UNITS_MEASURED = 5000
MAX_POLICY_BYTES = 64 * 1024
DRIVE = re.compile(r'[A-Za-z]:')


def policy_path():
    """The machine policy file: GOAT_STORAGE_FLOORS, else ``%LOCALAPPDATA%\\GOAT Portfolio Desktop\\storage-floors.json``."""
    named = os.environ.get(POLICY_ENV)
    if named:
        return Path(named)
    base = os.environ.get('LOCALAPPDATA')
    return Path(base) / 'GOAT Portfolio Desktop' / POLICY_NAME if base else None


def read_policy(path):
    """{drive: floor GB} from the policy file; {} when there is no file. Fails closed on a file it cannot trust."""
    if path is None or not Path(path).exists():
        return {}
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
        if len(raw) > MAX_POLICY_BYTES:
            raise ValueError('larger than 64 KiB')
        record = json.loads(raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError('Storage floor policy %s cannot be read (%s); no output root is checked against an unknown floor'
                         % (path, exc)) from None
    floors = record.get('floors_gb') if isinstance(record, dict) else None
    if (not isinstance(record, dict) or record.get('schema') != SCHEMA or not isinstance(floors, dict)
            or not all(isinstance(k, str) and DRIVE.fullmatch(k) and type(v) in (int, float) and 0 <= v <= 1000000
                       for k, v in floors.items())):
        raise ValueError('Storage floor policy %s is not a %s record ({"schema": "%s", "floors_gb": {"C:": 15, "G:": 50}})'
                         % (path, SCHEMA, SCHEMA))
    return {k.upper(): float(v) for k, v in floors.items()}


def system_drive():
    """The Windows system drive ('C:'), or None off Windows."""
    return (os.environ.get('SystemDrive') or 'C:').upper() if os.name == 'nt' else None


def drive_of(root):
    """'G:' for G:\\GOAT-Evidence (the \\\\?\\ prefix dropped); '' for a path without a drive letter."""
    text = str(root)
    if text.startswith('\\\\?\\'):
        text = text[4:]
    return text[:2].upper() if DRIVE.match(text[:2]) else ''


def floor_for(drive, *, path=None, system=None):
    """(floor bytes, where it came from) for ``drive``: the policy file's value, else the default."""
    table = read_policy(path)
    if drive in table:
        return int(table[drive] * GB), 'policy file %s' % path
    where = ('no %s entry in policy file %s' % (drive or 'drive', path)) if path is not None and Path(path).exists() \
        else 'no policy file at %s' % path
    if drive and drive == system:
        return SYSTEM_FLOOR_GB * GB, 'default for the system drive, %d GB; %s' % (SYSTEM_FLOOR_GB, where)
    return OTHER_FLOOR_GB * GB, 'default for a non-system drive, %d GB; %s' % (OTHER_FLOOR_GB, where)


def on_disk_size(path):
    """One file's size on disk: its compressed size on Windows (GetCompressedFileSizeW), else its allocated blocks."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        call = kernel32.GetCompressedFileSizeW
        call.argtypes, call.restype = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD
        text = str(path)
        if not text.startswith('\\\\?\\'):
            text = '\\\\?\\' + os.path.abspath(text)
        high = wintypes.DWORD(0)
        low = call(text, ctypes.byref(high))
        if low == 0xFFFFFFFF:
            error = ctypes.get_last_error()
            if error:
                raise OSError(error, 'GetCompressedFileSizeW failed', str(path))
        return (high.value << 32) + low
    status = os.stat(path)
    blocks = getattr(status, 'st_blocks', None)
    return blocks * 512 if blocks is not None else status.st_size


def largest_unit(root, size=None):
    """(largest on-disk bytes of a finished unit under ``root``, units measured); (None, 0) when none is finished."""
    size = size or on_disk_size
    base = Path(root)
    if os.name == 'nt' and not str(base).startswith('\\\\?\\'):
        base = Path('\\\\?\\' + os.path.abspath(base))
    if not base.is_dir():
        return None, 0
    best, measured = None, 0
    for folder in sorted(base.glob('c.*')):
        if not folder.is_dir():
            continue
        for unit in sorted(folder.iterdir()):
            if measured >= MAX_UNITS_MEASURED:
                return best, measured
            if not (unit.is_dir() and unit.name.isdigit() and any((unit / name).is_file() for name in UNIT_RECORDS)):
                continue
            total = sum(size(path) for path in unit.rglob('*') if path.is_file())
            measured += 1
            best = total if best is None else max(best, total)
    return best, measured


def check(root, members, *, path=None, system=None, size=None):
    """Refuse ``root`` when free now - members x unit falls under its drive's floor; else return the projection."""
    import shutil
    path = policy_path() if path is None else path
    system = system_drive() if system is None else system
    probe = Path(root)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise ValueError('output_root %s: free space cannot be read (%s)' % (root, exc)) from None
    try:
        measured_unit, measured = largest_unit(root, size)
    except OSError as exc:
        raise ValueError('output_root %s: the finished units cannot be measured (%s)' % (root, exc)) from None
    unit = measured_unit if measured_unit is not None else UNIT_FALLBACK_BYTES
    basis = ('the largest of %d finished unit(s) on disk' % measured if measured_unit is not None
             else 'no finished unit yet, so 128 MiB')
    drive = drive_of(root)
    floor, source = floor_for(drive, path=path, system=system)
    projected = free - members * unit
    report = dict(drive=drive, free_bytes=free, members=members, unit_bytes=unit, unit_basis=basis, units_measured=measured,
                  projected_free_bytes=projected, floor_bytes=floor, floor_source=source,
                  policy_file=str(path) if path is not None else None)
    report['plain'] = ('%s: %.1f GB free now - %d unit(s) x %.0f MB (%s) = %.1f GB projected at the plan\'s end; floor %.1f GB (%s)'
                       % (drive or root, free / GB, members, unit / 1e6, basis, projected / GB, floor / GB, source))
    if projected < floor:
        raise ValueError('output_root %s is refused: %s' % (root, report['plain']))
    return report
