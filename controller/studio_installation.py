"""Customer-local installation receipt. No machine paths or account defaults."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

VERSION = '1.48-beta.1'

def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000: raise ValueError('JSON exceeds 2 MB')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)

def load_installation(path):
    value = read_json(path)
    required = {'schema_version','controller_version','ea_version','terminal_executable',
                'terminal_data_root','common_files_root','ea_relative_path','ea_sha256','controller_state_root'}
    if not isinstance(value,dict) or not required <= value.keys() or value['schema_version'] != 1:
        raise ValueError('Version 1 installation receipt required; run GOAT Setup')
    if value['controller_version'] != VERSION or value['ea_version'] != '1.48':
        raise ValueError('EA/controller receipt is incompatible with this controller')
    for name in ('terminal_executable','terminal_data_root','common_files_root','controller_state_root'):
        if not isinstance(value[name],str) or not Path(value[name]).is_absolute():
            raise ValueError('Absolute installed path required: '+name)
        value[name] = str(Path(value[name]).resolve())
    if not Path(value['terminal_executable']).is_file(): raise ValueError('Selected MT5 executable missing')
    data = Path(value['terminal_data_root'])
    if not (data/'MQL5').is_dir() or not Path(value['common_files_root']).is_dir():
        raise ValueError('Selected MT5 data/Common Files folders missing')
    relative = PureWindowsPath(value['ea_relative_path'])
    if relative.drive or relative.root or '..' in relative.parts or relative.suffix.lower() != '.ex5':
        raise ValueError('EA path must be relative to MQL5/Experts')
    binary = (data/'MQL5/Experts').joinpath(*relative.parts).resolve()
    if not binary.is_relative_to(data/'MQL5/Experts'): raise ValueError('EA path escapes Experts')
    if not re.fullmatch('[a-f0-9]{64}',value['ea_sha256']): raise ValueError('EA SHA-256 required')
    if hashlib.sha256(binary.read_bytes()).hexdigest() != value['ea_sha256']:
        raise ValueError('Installed EA hash differs from receipt; repair installation')
    state = Path(value['controller_state_root'])
    for root in (data,Path(value['terminal_executable']).parent,Path(value['common_files_root'])):
        if state.is_relative_to(root): raise ValueError('Controller state must be outside MT5 and Common Files')
    return value

def contracts():
    root = Path(__file__).parent/'contracts'
    schema,policy = read_json(root/'inputs.json'),read_json(root/'dependencies.json')
    if schema['source_sha256'] != policy['header_sha256']: raise ValueError('Mismatched controller contracts')
    return schema,policy
