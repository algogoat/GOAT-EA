"""Repair only an empty, never-started local monitor session. No control grants."""
import hashlib
from pathlib import Path
import re
import shutil
import time

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json
from studio_monitor_probe import inspect_idle_demo
from studio_native_gate import exclusive_gate, assert_clear_controls
from studio_onboarding import session_state, monitor_launch, monitor_chart, monitor_paths, require_idle_control
from studio_seed_process import WindowsSeedProcess


def repair(controller, attempt_id, *, stop_only=False):
    if type(stop_only) is not bool:
        raise ValueError("Explicit monitor operation required")
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', attempt_id):
        raise ValueError('Simple retained repair attempt ID required')
    session, _ = session_state(controller)
    root = safe_path(controller.root/'monitor-repairs')
    root.mkdir(exist_ok=True)
    path = root/(attempt_id+'.json')
    process = WindowsSeedProcess(controller)
    with exclusive_gate(controller.local/'native-gate'):
        require_idle_control(controller, session)
        state = controller.state()
        if state['queue'] or list((controller.root/'attempts').glob('*')):
            raise ValueError('Repair is limited to an empty, never-started monitor session')
        assert_clear_controls(controller.store.db, controller.local/'native-gate')
        for other in root.glob('*.json'):
            retained = read_json(other)
            if other != path and retained.get('phase') != 'launched' and not (retained.get('stop_only') is True and retained.get('phase') == 'stopped'):
                raise ValueError('Resume the retained monitor repair; do not create another attempt')
        if path.exists():
            record = read_json(path)
            if record.get('stop_only', False) != stop_only:
                raise ValueError('Retained monitor operation differs; never reinterpret a stop as a relaunch')
            if record['installation_sha256'] != sha(controller.install) or record['session_sha256'] != sha(session):
                raise ValueError('Repair installation/session changed')
            if record.get('schema_version') != 1 or record.get('attempt_id') != attempt_id or record.get('phase') not in ('close_issued','stopped','prepared','launched'):
                raise ValueError('Invalid retained repair state; preserve evidence')
            if record['phase'] == 'launched':
                return record
        else:
            from studio_terminal_isolation import controller_base_name, controller_hash, foreign_namespace, legacy_base_name
            common = safe_path(Path(controller.install['common_files_root'])/'GOAT')
            # This terminal's own folder and the shared pre-isolation folder of the
            # installed version (which the EA may move here) both block repair.
            current_bases = {controller_base_name(controller).casefold(),
                             legacy_base_name(controller.install['ea_version'], session['account']['server']).casefold()}
            own_hash = controller_hash(controller)
            retained_other_versions = {}
            for folder in common.iterdir():
                safe_path(folder)
                if foreign_namespace(folder.name, own_hash):
                    continue  # Another terminal's independent batch state.
                if folder.name.lower().startswith('goat v'):
                    for name in ('active_optimization_run.ini', 'active_optimization_config.ini', 'active_optimization_launch.ini', 'agent-native-control-owner.json'):
                        if (folder/name).exists():
                            control = safe_path(folder/name)
                            if folder.name.casefold() in current_bases:
                                raise ValueError('Native campaign controls remain for the installed EA; repair cannot interrupt research')
                            # Older version pointers are not consumed by this EA. Preserve
                            # them; this operation cannot arm a batch or clear native flags.
                            retained_other_versions[str(control)] = hashlib.sha256(control.read_bytes()).hexdigest()
            native = inspect_idle_demo(controller)
            record = dict(schema_version=1, attempt_id=attempt_id, stop_only=stop_only, phase='close_issued',
                          installation_sha256=sha(controller.install), session_sha256=sha(session),
                          native=native, retained_other_version_controls=retained_other_versions,
                          created_at=time.time(), grants_changed=False, optimization_started=False)
            write_json(path, record)
            # Persist the intent first; a failed or uncertain close is never resent.
            process.close(native['process'])
        if record['phase'] == 'close_issued':
            deadline = time.monotonic()+20
            current = process.inspect()
            while current is not None and time.monotonic() < deadline:
                if current != record['native']['process']:
                    raise ValueError('Terminal was replaced after repair close; no process adoption')
                time.sleep(.2); current = process.inspect()
            if current is not None:
                return record | dict(status='close_outcome_unresolved', close_will_not_be_repeated=True)
            record['phase'] = 'stopped'; write_json(path, record)
        if record['phase'] == 'stopped' and stop_only:
            if process.inspect() is not None:
                raise ValueError('Terminal reopened after retained stop; no further close or adoption')
            return record | dict(status='selected_terminal_stopped', profile_changed=False)
        if record['phase'] == 'stopped':
            if process.inspect() is not None:
                raise ValueError('Terminal reopened before monitor repair; no additional close')
            receipt = read_json(controller.root/'monitor-profile.json')
            name, profile = monitor_paths(controller, session)
            safe_path(profile)
            if receipt['profile_name'] != name or receipt['profile_path'] != str(profile):
                raise ValueError('Prepared monitor identity changed')
            entries = list(profile.iterdir())
            if any(not safe_path(p).is_file() or p.name not in ('chart01.chr', 'order.wnd') for p in entries):
                raise ValueError('Unexpected profile contents; preserve and inspect before repair')
            raw = monitor_chart(controller, receipt['symbol'])
            if hashlib.sha256(raw).hexdigest() != receipt['chart_sha256']:
                raise ValueError('Prepared monitor contract changed')
            backup = root/(attempt_id+'-profile')
            if not backup.exists():
                shutil.copytree(profile, backup)
            else:
                # An uncertain previous write may only have published the intended chart.
                for item in entries:
                    old = safe_path(backup/item.name)
                    if not old.is_file() or (item.read_bytes() != old.read_bytes() and not (item.name == 'chart01.chr' and item.read_bytes() == raw)):
                        raise ValueError('Profile repair/backup changed; preserve both')
            (profile/'chart01.chr').write_bytes(raw)
            record.update(phase='prepared', profile_backup=str(backup)); write_json(path, record)
    # Public launch performs its own stopped/process/profile/preset checks under the native gate.
    launched = monitor_launch(controller, 'repair-'+attempt_id)
    record.update(phase='launched', launch=launched)
    write_json(path, record)
    return record
