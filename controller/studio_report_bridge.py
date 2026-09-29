"""Owned output alias for MT5 installation-relative reports and the EA data sandbox."""
from pathlib import Path
import os
import re
from studio_handover import safe_path


def paths(binding, relative):
    if not re.fullmatch(r'GOAT\\R[0-9a-f]{12}',relative):
        raise ValueError('Exact managed report run required')
    parts=relative.split('\\')
    data=safe_path(Path(binding['research_data_root'])/'MQL5/Files')
    install=safe_path(Path(binding['research_terminal']).parent/'MQL5/Files')
    return install.joinpath(*parts),data.joinpath(*parts)


def prepare(binding, relative):
    """Creates only a fresh per-run junction; never replaces or removes a path."""
    source,target=paths(binding,relative)
    if source==target:return dict(kind='same_root',path=str(source),target=str(target))
    if source.exists() or source.is_symlink() or os.path.lexists(source):
        raise ValueError('Installation report run already exists; reconcile it')
    if not target.is_dir():raise ValueError('Reserved local report run required')
    safe_path(target)
    if os.name!='nt':raise ValueError('MT5 report bridge requires Windows')
    import _winapi
    source.parent.mkdir(parents=True,exist_ok=True)
    safe_path(source.parent)
    _winapi.CreateJunction(str(target),str(source))
    receipt=dict(kind='owned_run_junction',path=str(source),target=str(target))
    verify(receipt)
    return receipt


def verify(receipt):
    source,target=map(Path,(receipt['path'],receipt['target']))
    safe_path(target)
    if receipt['kind']=='same_root':
        if source!=target:raise ValueError('Portable report root changed')
    elif (receipt['kind']!='owned_run_junction' or not source.is_junction()
          or source.resolve()!=target.resolve()):
        raise ValueError('Owned report junction changed')
    if not target.is_dir():raise ValueError('Report target disappeared')
