"""Verify stopped-terminal rejection cleanup; never infer a current native state."""
from pathlib import Path

from studio_handover import safe_path
from studio_installation import read_json
from studio_orphan_recovery import inspect_local
from studio_process_check import inspect_processes


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
    processes=inspect_processes(c.binding(),research_running=False)
    if processes.get('research') is not None:
        raise ValueError('Selected terminal must remain stopped during rejection settlement')
    assert_clear_human_channels(c)
    return processes
