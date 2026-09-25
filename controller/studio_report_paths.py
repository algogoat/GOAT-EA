"""Resolve one managed job's local and Common Files report destinations."""
from pathlib import Path, PureWindowsPath
import re


def report_paths(plan, manifest):
    if len(manifest['jobs']) != 1:
        raise ValueError('One managed report job required')
    job = manifest['jobs'][0]
    run = manifest['native_run_relative']
    alias = job['run_alias']
    if not re.fullmatch(r'GOAT\\R[0-9a-f]{12}', run) or not re.fullmatch(r'R[0-9a-f]{20}', alias):
        raise ValueError('Invalid managed report identity')
    report = job['tester']['Report']
    parts = PureWindowsPath(report).parts
    prefix = ('MQL5', 'Files', *PureWindowsPath(run).parts, 'reports', alias,
              job['tester']['Symbol'])
    if (parts[:-1] != prefix or not parts[-1].endswith('.xml')
            or any(p in ('.', '..') or ':' in p for p in parts)
            or report != job['report_relative']):
        raise ValueError('Report path differs from managed run')
    binding = plan['research_binding']
    local_base = Path(binding['research_data_root']).resolve() / 'MQL5' / 'Files'
    common_base = Path(binding['common_files_root']).resolve()
    result = {}
    for name, base in (('local', local_base), ('common', common_base)):
        root = (base / Path(*PureWindowsPath(run).parts)).resolve()
        back = (base / Path(*parts[2:])).resolve()
        if not root.is_relative_to(base.resolve()) or not back.is_relative_to(root):
            raise ValueError('Report path escapes bound root')
        result[name + '_run'] = root
        result[name + '_back'] = back
        result[name + '_forward'] = back.with_name(back.stem + '.forward.xml')
    return result
