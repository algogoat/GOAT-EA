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

def refuse_prepare_while_seed_owns(root):
    """prepare-batch refuses at once (one plain sentence, the next command) while a seed or catch-up holds the terminal."""
    path=Path(root)/'seed-active.json'
    if not path.exists():return
    value=read_json(path)
    if value.get('status')=='released':return
    batch=str(value.get('batch_id') or '<id>')
    kind='catchup' if (Path(root)/'catchups'/batch/'state.json').is_file() else 'seed'
    flag='--catchup-id' if kind=='catchup' else '--batch-id'
    raise ValueError(('Catch-up ' if kind=='catchup' else 'Seed hunt ')+batch+' still holds this terminal, so nothing was prepared; '
                     'settle it first with '+kind+'-reconcile '+flag+' '+batch+' (or '+kind+'-cancel '+flag+' '+batch+
                     ' once MT5 is idle), then prepare again.')
