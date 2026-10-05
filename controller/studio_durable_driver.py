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


STARTED_WAIT_SECONDS = 60
REGISTER_TIMEOUT_SECONDS = 30
TASK_NAME = re.compile(r'GOAT-Demo-[a-f0-9]{16}-[a-f0-9]{32}')


SCHED_S_TASK_HAS_NOT_RUN = 267011      # 0x41303: Task Scheduler's LastTaskResult for a task that never ran


def _task_name(name):
    if not isinstance(name, str) or not TASK_NAME.fullmatch(name):
        raise ValueError('Not a GOAT demand task name')
    return name


def task_info(name, *, budget=None):
    """Read-only Windows view of one GOAT demand task: {exists, state, last_run_utc, last_result}."""
    from studio_process_query import powershell_text
    command = ("$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName '" + _task_name(name) + "' -ErrorAction SilentlyContinue; "
               "if(-not $t){'{\"exists\":false}'} else {$i=$t | Get-ScheduledTaskInfo; "
               "$run=$null; if($i.LastRunTime -and $i.LastRunTime.Year -gt 2000){$run=$i.LastRunTime.ToUniversalTime().ToString('o')}; "
               "ConvertTo-Json -Compress -InputObject @{exists=$true; state=[string]$t.State; last_run_utc=$run; last_result=[int64]$i.LastTaskResult}}")
    value = json.loads(powershell_text(command, purpose='demand task state', budget=budget))
    if not isinstance(value, dict) or type(value.get('exists')) is not bool:
        raise ValueError('Demand task state unreadable')
    return value


def never_started(info, envelope_created_utc):
    """True only when the task provably never ran its bootstrap (Claude-Mac's rule, #1885): it exists, is not
    running or queued, has not run since the envelope was retained, and still reports SCHED_S_TASK_HAS_NOT_RUN;
    or it is gone. The caller also checks that no started receipt exists.

    A gone task is a deliberate widening of "exists + 267011": a task that no longer exists can never start
    its bootstrap, and the retry reserves a fresh nonce, so even a bootstrap already past validate() refuses
    at the driver's nonce check under the terminal lock."""
    if not info['exists']:
        return True
    if info.get('state') in ('Running', 'Queued'):
        return False
    run = info.get('last_run_utc')
    if run is not None:
        try:
            if datetime.fromisoformat(run.replace('Z', '+00:00')) >= envelope_created_utc:
                return False
        except (TypeError, ValueError):
            return False
    return info.get('last_result') == SCHED_S_TASK_HAS_NOT_RUN


def unregister_task(name):
    """Remove one never-started GOAT demand task and confirm it is gone; any doubt raises (fail closed)."""
    from studio_process_query import powershell_text
    command = ("$ErrorActionPreference='Stop'; $n='" + _task_name(name) + "'; "
               "if(Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue){Unregister-ScheduledTask -TaskName $n -Confirm:$false}; "
               "if(Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue){'present'} else {'gone'}")
    if powershell_text(command, purpose='retire never-started demand task', attempts=1).strip() != 'gone':
        raise ValueError('The never-started demand task ' + name + ' could not be removed; inspect it, never duplicate')


def retain(path, value):
    with safe_path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())


LANE_KINDS = ('seed', 'catchup', 'holdup')
# The reservation a bootstrap may still start for. A task that starts only after the caller's 60 s wait
# finds its record 'launch_unconfirmed' with the same nonce; it is that launch, so it drives (Claude-Mac
# on GOAT-EA#163: otherwise the task has run, never_started() is false forever, and the batch is stuck).
# A retry only follows a provably never-run task and replaces the nonce, so a late old task still refuses,
# and the driver re-checks its nonce under the terminal lock before any effect.
BOOTSTRAP_STATUSES = ('reserved', 'launch_unconfirmed')


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
    if (worker.get('status') not in BOOTSTRAP_STATUSES or worker.get('nonce') != nonce or worker.get('batch_id') != batch_id
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
    if worker.get('status') not in BOOTSTRAP_STATUSES or worker.get('nonce') != nonce or worker.get('batch_id') != batch_id:
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
    if worker.get('status') != 'reserved' or worker.get('launch_envelope'):
        raise ValueError('Only a fresh reservation registers a task; never a second task for one launch')
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
            timeout=REGISTER_TIMEOUT_SECONDS, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError('Persistent driver task registration/start unconfirmed; preserve the launch envelope, no retry/fallback') from error
    # Python can take tens of seconds to start under a CPU or WMI stall; 15 s left launches unconfirmed
    # that were only slow (goatai#1885). The worker waits longer than this for the terminal lock.
    deadline = time.monotonic() + STARTED_WAIT_SECONDS
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
