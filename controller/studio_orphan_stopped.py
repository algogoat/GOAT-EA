"""Verify stopped-terminal rejection cleanup; never infer a current native state."""
import math
from pathlib import Path, PureWindowsPath

from studio_handover import safe_path
from studio_installation import read_json
from studio_orphan_recovery import inspect_local
from studio_process_check import inspect_processes


def validate_observation(c,proof):
    inventory=proof.get('root_inventory') if isinstance(proof,dict) else None
    expected=[str(PureWindowsPath(Path(c.install['terminal_executable']).parent)),
              str(PureWindowsPath(c.install['terminal_data_root']))]
    if (not isinstance(inventory,dict)
            or set(inventory)!={'roots','process_count','unavailable_path_count','limitation'}
            or inventory['roots']!=expected
            or type(inventory['process_count']) is not int or inventory['process_count']<0
            or type(inventory['unavailable_path_count']) is not int
            or not 0<=inventory['unavailable_path_count']<=inventory['process_count']
            or inventory['limitation']!='Windows-visible executable paths only; unrelated unreadable system paths cannot be attributed to a terminal'
            or type(proof.get('observed_unix')) not in (int,float)
            or not math.isfinite(proof['observed_unix']) or proof['observed_unix']<0
            or proof.get('research','missing') is not None or proof.get('launch_permitted') is not False):
        raise ValueError('Stopped recovery root inventory evidence changed')


def assert_clear_human_channels(c):
    for name in ('inbox','processing'):
        directory=safe_path(c.bridge.root/'human'/name)
        if not directory.is_dir() or any(directory.iterdir()):
            raise ValueError('Pending or unavailable human control channel; retain recovery evidence')


def inspect_stopped(c, plan):
    request=plan['record']['request']
    current=inspect_local(c,allow_own_request=plan['record'])
    expected={key:value for key,value in plan['observation'].items() if key not in ('process','monitor_instance')}
    if current!=expected:
        raise ValueError('Stopped recovery local installation, binding or state changed')
    if read_json(c.root/'session.json')!=c.session:
        raise ValueError('Stopped recovery session changed')
    if c.session.get('authority_kind') not in (None,'native_human_control'):
        raise ValueError('Stopped recovery requires the native human control route')
    fields=dict(terminal_id=c.terminal,run_id=c.run,owner='agent',
                revision=current['revision'],generation=current['generation'],
                account_login=c.session['account']['login'],account_server=c.session['account']['server'],
                ea_version=c.install['ea_version'],data_path=c.install['terminal_data_root'],
                installation_path=str(Path(c.install['terminal_executable']).parent),
                program_path=str(c.native_args()['monitor_path'].resolve()),
                monitor_instance=plan['observation']['monitor_instance'])
    if any(request.get(key)!=value for key,value in fields.items()):
        raise ValueError('Stopped recovery request account or session identity changed')
    assert_clear_human_channels(c)
    # Full process classification refuses running, unmapped, replaced peer or
    # ambiguous processes. Absence is not represented as a normal-exit receipt.
    processes=inspect_processes(c.binding(),research_running=False,
        absent_roots=[str(Path(c.install['terminal_executable']).parent),c.install['terminal_data_root']])
    if processes.get('research') is not None:
        raise ValueError('Selected terminal must remain stopped during rejection settlement')
    assert_clear_human_channels(c)
    return processes
