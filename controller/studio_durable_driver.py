"""Windows demand-task host for the bounded demo driver, outside caller jobs.

No native grant, broker login, order or MT5 operation is performed here. The
driver rechecks demo/STOP/disk/ownership as usual. A failed/unknown task launch
has no process-launch fallback, because that could duplicate a supervisor.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

# Same anchoring as demo_agent.py: the embedded GOAT Python lists its installed
# controller (../controller) ahead of this script's directory, so without this
# the demand task would import an older demo_agent and refuse newer arguments
# (seen live: `_drive-batch --pause-seconds` rejected, supervisor exit 2).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio_handover import safe_path
from studio_installation import load_installation, read_json


def retain(path, value):
    with safe_path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())


LANE_KINDS = ('seed', 'catchup', 'holdup')


def validate_lane(argv, log_path, worker_path):
    """The detached seed/catch-up/hold-up driver (goatai#1885): demo_agent.py _drive-lane with its exact reservation."""
    if len(argv) != 14 or argv[2] != '--installation' or argv[4:6] != ['_drive-lane', '--kind']:
        raise ValueError('Only the bound demo lane driver can use the durable host')
    if Path(argv[1]).resolve() != Path(__file__).with_name('demo_agent.py').resolve():
        raise ValueError('Only the installed controller driver is accepted')
    kind, batch_id, nonce, budget, mode = argv[6], argv[8], argv[10], argv[12], argv[13]
    if (argv[7] != '--batch-id' or argv[9] != '--nonce' or argv[11] != '--max-seconds' or kind not in LANE_KINDS
            or mode not in ('--initial', '--resume') or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id)
            or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
        raise ValueError('Exact lane, batch, nonce and mode identities required')
    install = load_installation(safe_path(Path(argv[3]).absolute()))
    root = safe_path(Path(install['controller_state_root']))
    worker_path = safe_path(Path(worker_path).absolute())
    expected = root / 'demo-agent/lane-workers' / (kind + '-' + batch_id + '.json')
    if worker_path != expected or Path(log_path).absolute() != expected.with_name(kind + '-' + batch_id + '-' + nonce + '.log'):
        raise ValueError('Lane driver log/worker path is not canonical')
    worker = read_json(worker_path)
    if (worker.get('status') != 'reserved' or worker.get('nonce') != nonce or worker.get('batch_id') != batch_id
            or worker.get('kind') != kind or worker.get('initial') is not (mode == '--initial')):
        raise ValueError('Current reserved lane driver identity required')
    remaining = worker.get('max_seconds')
    if type(remaining) is not int or not 1 <= remaining <= 3600 or str(remaining) != budget:
        raise ValueError('Lane driver budget changed or out of 1..3600 seconds')
    return worker, remaining


def validate(argv, log_path, worker_path):
    if len(argv) == 14 and argv[4:5] == ['_drive-lane']:
        return validate_lane(argv, log_path, worker_path)
    if len(argv) not in (9, 11) or argv[2] != '--installation' or argv[4:6] != ['_drive-batch', '--batch-id']:
        raise ValueError('Only the bound demo driver can use the durable host')
    if Path(argv[1]).resolve() != Path(__file__).with_name('demo_agent.py').resolve():
        raise ValueError('Only the installed controller driver is accepted')
    batch_id, nonce = argv[6], argv[8]
    if argv[7] != '--nonce' or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('Exact batch and nonce identities required')
    install = load_installation(safe_path(Path(argv[3]).absolute()))
    root = safe_path(Path(install['controller_state_root']))
    worker_path = safe_path(Path(worker_path).absolute())
    expected = root / 'demo-agent/workers' / (batch_id + '.json')
    if worker_path != expected or Path(log_path).absolute() != expected.with_name(batch_id + '-' + nonce + '.log'):
        raise ValueError('Driver log/worker path is not canonical')
    worker = read_json(worker_path)
    if worker.get('status') != 'reserved' or worker.get('nonce') != nonce or worker.get('batch_id') != batch_id:
        raise ValueError('Current reserved supervisor identity required')
    if worker.get('resume') is True:
        if worker.get('max_seconds') is not None:
            raise ValueError('Resume must keep the original driver budget')
        if worker.get('pause_seconds') is None:
            if len(argv) != 9:
                raise ValueError('Resume must keep the original driver budget')
            deadline = read_json(safe_path(root / 'batch-drivers' / (batch_id + '.json')))['deadline_wall']
            remaining = max(0, math.ceil(deadline - time.time()))
        else:
            # A pause supervisor has its own bounded budget; the batch deadline is unchanged.
            if len(argv) != 11 or argv[9] != '--pause-seconds' or str(worker['pause_seconds']) != argv[10]:
                raise ValueError('Pause supervision budget changed')
            remaining = worker['pause_seconds']
    else:
        if len(argv) != 11 or argv[9] != '--max-seconds' or str(worker.get('max_seconds')) != argv[10]:
            raise ValueError('Initial driver budget changed')
        remaining = worker['max_seconds']
    if type(remaining) is not int or not (0 if worker.get('resume') is True else 1) <= remaining <= 172800:
        raise ValueError('Bounded unexpired driver budget required')
    return worker, remaining


REGISTER_TASK = r'''$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$r=[Console]::In.ReadToEnd() | ConvertFrom-Json
if(Get-ScheduledTask -TaskName $r.name -ErrorAction SilentlyContinue){throw 'Existing task; reconcile, never duplicate'}
$u=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$a=New-ScheduledTaskAction -Execute $r.executable -Argument $r.arguments -WorkingDirectory $r.cwd
$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromSeconds($r.limit)) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $r.name -Action $a -Principal $p -Settings $s -Description 'GOAT bounded demo driver; demand only, original budget and human STOP retained' | Out-Null
Start-ScheduledTask -TaskName $r.name
'''


class DriverHandle:
    def __init__(self, pid, finished, nonce):
        self.pid, self.finished, self.nonce = pid, finished, nonce

    def poll(self):
        if not self.finished.exists():
            return None
        result = read_json(self.finished)
        if result.get('nonce') != self.nonce:
            raise ValueError('Persistent driver completion identity changed')
        return result['exit_code']


def launch(argv, *, log_path, worker_path):
    worker, remaining = validate(argv, log_path, worker_path)
    pythonw = Path(argv[0]).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise ValueError('The installed windowless Python runtime is missing; no ephemeral launch fallback')
    prefix = Path(log_path).with_suffix('')
    envelope = safe_path(Path(str(prefix) + '.launch.json'))
    started = safe_path(Path(str(prefix) + '.started.json'))
    finished = safe_path(Path(str(prefix) + '.finished.json'))
    task_name = 'GOAT-Demo-' + hashlib.sha256(str(worker_path).lower().encode()).hexdigest()[:16] + '-' + worker['nonce']
    retain(envelope, dict(schema_version=1, argv=argv, log_path=str(log_path), worker_path=str(worker_path),
        started=str(started), finished=str(finished), task_name=task_name))
    # Retain an unresolved launch before registration so a killed caller cannot
    # retry with a fresh nonce and accidentally create a second task.
    from demo_agent import write_json
    worker.update(launch_envelope=str(envelope), launch_mechanism='windows_demand_task')
    write_json(worker_path, worker)
    request = dict(name=task_name, executable=str(pythonw),
        arguments=subprocess.list2cmdline([str(Path(__file__).resolve()), '--envelope', str(envelope)]),
        cwd=str(Path(__file__).parent), limit=remaining + 300)
    import base64
    encoded = base64.b64encode(REGISTER_TASK.encode('utf-16-le')).decode('ascii')
    try:
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            input=json.dumps(request), text=True, encoding='utf-8', capture_output=True, check=True,
            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError('Persistent driver task registration/start unconfirmed; preserve the launch envelope, no retry/fallback') from error
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if started.is_file():
            observed = read_json(started)
            if observed.get('nonce') != worker['nonce'] or type(observed.get('pid')) is not int:
                raise ValueError('Persistent bootstrap identity differs; preserve evidence')
            return DriverHandle(observed['pid'], finished, worker['nonce'])
        time.sleep(.1)
    raise ValueError('Persistent bootstrap unconfirmed; inspect the same launch/task, never issue another')


def bootstrap(envelope):
    data = read_json(safe_path(Path(envelope).absolute()))
    if data.get('schema_version') != 1 or set(data) != {'schema_version','argv','log_path','worker_path','started','finished','task_name'}:
        raise ValueError('Only the exact driver envelope schema is accepted')
    worker, _ = validate(data['argv'], data['log_path'], data['worker_path'])
    prefix = Path(data['log_path']).with_suffix('')
    for key in ('started', 'finished'):
        if Path(data[key]) != Path(str(prefix) + '.' + key + '.json'):
            raise ValueError('Bootstrap receipt path differs')
    retain(Path(data['started']), dict(pid=os.getpid(), nonce=worker['nonce'],
        at=datetime.now(timezone.utc).isoformat(), native_running_verified=False))
    code = 2
    previous = sys.stdout, sys.stderr
    try:
        with safe_path(Path(data['log_path'])).open('a', encoding='utf-8') as log:
            sys.stdout = sys.stderr = log
            try:
                from demo_agent import main
                code = main(data['argv'][2:])
            finally:
                log.flush(); os.fsync(log.fileno())
                retain(Path(data['finished']), dict(exit_code=code, nonce=worker['nonce']))
    finally:
        sys.stdout, sys.stderr = previous
    return code


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--envelope':
        raise SystemExit('Bound driver envelope required')
    raise SystemExit(bootstrap(sys.argv[2]))
