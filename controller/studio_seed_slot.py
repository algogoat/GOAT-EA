"""Shared seed/native launch exclusion. Caller holds native exclusive_gate."""
from pathlib import Path
from studio_installation import read_json


def guard_active_seed(root):
    path=Path(root)/'seed-active.json'
    if path.exists():
        value=read_json(path)
        if value.get('status')!='released':
            raise ValueError('Seed runner owns this terminal; use seed-status/cancel/resume before normal native work')
    return True
