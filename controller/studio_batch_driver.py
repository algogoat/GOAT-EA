"""Bounded supervision of one frozen native batch; never a process watchdog.

Host/controller liveness is required. Native cancellation is a request until
studio_finish verifies completion. An interrupted uncertain start is never
retried or adopted, and a revoked owner never cancels a successor's work.
A start refused BEFORE any native effect (no attempt, no cancel, the job still
pending or reserved-but-never-permitted) is not uncertain: it may start again
under the same batch ID; its journal is archived, never deleted.
"""
import hashlib
import math
import os
import re
import shutil
import time
from pathlib import Path

from campaign_ledger import sha
from studio_batch import _verify_package
from studio_bridge import write_json
from studio_finish import finish
from studio_handover import safe_path, session_lock
from studio_installation import read_json
from studio_native_gate import exclusive_gate

TERMINAL = {'completed', 'cancelled', 'failed'}


def refused_before_dispatch(record, job):
    """True when a retained driver journal provably never reached MT5.

    The journal recorded the intent to start, but no attempt was bound, no cancel
    was issued and the queue still holds the job unstarted: pending, or reserved
    with launch never permitted and no launch intent. Nothing was armed or
    dispatched, so starting again cannot double-dispatch.
    """
    if not isinstance(record, dict) or not isinstance(job, dict):
        return False
    reservation = job.get('reservation') or {}
    return (record.get('status') == 'start_uncertain' and record.get('start_issued') is True
            and record.get('attempt_id') is None and record.get('cancel_issued') is False
            and record.get('stopped') is not True and 'launch_intent' not in job
            and (job.get('status') == 'pending'
                 or (job.get('status') == 'reserved' and reservation.get('launch_permitted') is False)))


REFUSALS = 'batch-driver-refusals'


def retry_index(root, job_id):
    """How many refused starts of this job are archived; '.' never occurs in a job ID."""
    archive = Path(root) / REFUSALS
    pattern = re.compile(re.escape(job_id) + r'\.refused-[1-9][0-9]*\.json')
    return sum(1 for item in archive.iterdir() if pattern.fullmatch(item.name)) if archive.is_dir() else 0


def command_id(job_id, suffix, index):
    """Queue command ID for a start attempt. Receipts replay by ID, so each retry needs a fresh one."""
    return job_id + suffix + ('' if index == 0 else f'-r{index}')


def _retire_refused_journal(controller, job_id, path, clock):
    """Archive a refused-before-dispatch journal and release an unstarted reservation.

    Archives are numbered per job and never overwrite: an existing name refuses,
    so every refusal stays available as evidence.
    """
    root = safe_path(controller.root)
    index = retry_index(root, job_id)
    job = controller.job(job_id)
    if job['status'] == 'reserved':
        controller.submit('queue.release_reservation',
                          dict(job_id=job_id, reservation_id=job['reservation']['reservation_id']),
                          command_id(job_id, '-release-reservation', index),
                          expected_generation=controller.state()['generation'])
        if controller.job(job_id)['status'] != 'pending':
            raise ValueError('Unstarted reservation was not released; refused start remains retained')
    archive = safe_path(root / REFUSALS)
    archive.mkdir(exist_ok=True)
    target = safe_path(archive / f'{job_id}.refused-{index + 1}.json')
    if target.exists():
        raise ValueError('Refused-start archive already exists; retained journal left in place')
    os.replace(path, target)
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3


def _capacity(controller, minimum):
    """Probe each actual output filesystem; missing/unreadable roots fail closed."""
    observations = []
    for role, key in (('terminal_data', 'terminal_data_root'), ('common_files', 'common_files_root'),
                      ('controller_state', 'controller_state_root')):
        item = dict(role=role, free_bytes=None)
        try:
            root = safe_path(Path(controller.install[key]))
            item['path'] = str(root)
            if not root.is_dir():
                raise ValueError('Output root is unavailable')
            free = shutil.disk_usage(root).free
            if type(free) is not int or free < 0:
                raise ValueError('Invalid free capacity')
            item['free_bytes'] = free
        except (OSError, ValueError, KeyError, TypeError):
            item['unavailable'] = True
        observations.append(item)
    reason = ('disk_probe_unavailable' if any(item.get('unavailable') for item in observations) else
              'disk_low' if any(item['free_bytes'] < minimum for item in observations) else None)
    return dict(reason=reason, volumes=observations)



def _binding(controller, job_id, verify_preparation=False):
    state = controller.state()
    if state['owner'] != 'agent':
        raise ValueError('Agent ownership was revoked; no takeover or cancellation performed')
    job = controller.job(job_id)
    if sha(job['configuration']) != job['configuration_sha256']:
        raise ValueError('Frozen batch configuration changed')
    if not job['configuration'].get('batch_members'):
        raise ValueError('A prepared native batch is required')
    package = safe_path(controller.root/'packages'/job_id)
    if verify_preparation:
        _verify_package(controller, job)
    preparation = read_json(package/'preparation.json')
    if preparation.get('configuration_sha256') != job['configuration_sha256']:
        raise ValueError('Prepared batch configuration differs')
    for relative, expected in preparation['files'].items():
        target = safe_path(package/relative)
        if not target.is_relative_to(package) or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('Prepared batch bytes changed')
    session = read_json(controller.root/'session.json')
    if session != controller.session or session['installation_sha256'] != sha(controller.install):
        raise ValueError('Installed session changed')
    expected_active = dict(directory_id=session['directory_id'], terminal_id=controller.terminal,
                           run_id=controller.run, terminal_data_path=controller.install['terminal_data_root'])
    if read_json(controller.local/'active.json') != expected_active:
        raise ValueError('Active controller session changed')
    return dict(job_id=job_id, terminal_id=controller.terminal, run_id=controller.run,
                generation=state['generation'], installation_sha256=sha(controller.install),
                session_sha256=sha(session), configuration_sha256=job['configuration_sha256'],
                package=str(package), package_sha256=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest(),
                preparation_sha256=hashlib.sha256((package/'preparation.json').read_bytes()).hexdigest())


def _owned_attempt(controller, record):
    if _binding(controller, record['binding']['job_id']) != record['binding']:
        raise ValueError('Batch binding or ownership generation changed; no foreign cancellation')
    job = controller.job(record['binding']['job_id'])
    intent = job.get('launch_intent', {})
    if (intent.get('attempt_id') != record['attempt_id']
            or intent.get('package_sha256') != record['binding']['package_sha256']
            or str(Path(intent.get('package', '')).resolve()) != record['binding']['package']):
        raise ValueError('Exact owned attempt changed; no foreign cancellation')
    return job


def _save(path, record, clock):
    now = clock.time()
    if not math.isfinite(now):
        raise ValueError('Wall clock is not finite')
    record['last_wall'] = max(record.get('last_wall', now), now)
    write_json(path, record)


def _summary(path, record):
    return {key: record.get(key) for key in ('status', 'max_seconds', 'started_wall', 'deadline_wall',
            'attempt_id', 'start_issued', 'cancel_issued', 'stopped', 'last_error', 'result_path',
            'min_free_bytes', 'cancel_reason', 'disk_observation', 'pause_id', 'pause_failure',
            'pause_supervision')} | dict(
        journal_path=str(path), job_id=record['binding']['job_id'],
        disk_guard_available=(record.get('schema_version') == 2 and type(record.get('min_free_bytes')) is int
                              and record['min_free_bytes'] > 0),
        host_liveness_required=True, independent_hard_stop=False)


PAUSE_OVERRUN_SECONDS = 240
# A safe point is a short window at each member start (g6: ~40 s), but one
# supervision pass (reconcile + finish over every member's native evidence) takes
# minutes on a large batch, so the pause step only ran every 3-10 minutes and
# missed the window for over an hour. While a pause waits for a safe point, the
# driver re-checks only the pause every FAST_POLL_SECONDS for up to
# FAST_WATCH_SECONDS between passes. The step and its rules are unchanged.
FAST_WATCH_SECONDS = 150
FAST_POLL_SECONDS = 5
SAFE_POINT_WAITS = frozenset(('waiting_safe_point', 'cancel_rejected_waiting_safe_point'))


def _pause(controller, job_id):
    from studio_batch_pause import load
    return load(controller.root, job_id, quiet=True)


def _waiting_safe_point(pause):
    point = pause.get('safe_point') if isinstance(pause, dict) else None
    return (isinstance(point, dict) and point.get('ok') is False and pause.get('state') == 'pausing'
            and pause.get('phase') in SAFE_POINT_WAITS)


def _fast_watch(controller, job_id, record, path, clock, monitor_fn, pause, escalation, *, until, wall_start, monotonic_start):
    """Re-step a pause waiting for a safe point until it leaves the wait or ``until``.

    Anything the outer pass escalates on (a clock rollback, low disk) hands back to
    it at once, so a fast step never runs on a suspect clock or past the disk guard.
    """
    from studio_batch_pause import step, observe_monitor
    while _waiting_safe_point(pause) and clock.monotonic() + FAST_POLL_SECONDS <= until:
        clock.sleep(FAST_POLL_SECONDS)
        now, mono = clock.time(), clock.monotonic()
        if now < record['last_wall'] or now-wall_start+.05 < mono-monotonic_start:
            break
        record['disk_observation'] = _capacity(controller, record['min_free_bytes'])
        if record['disk_observation'].get('reason'):
            break
        try:
            monitor = (monitor_fn or observe_monitor)(controller, now)
            pause = step(controller, job_id, now=now, monitor=monitor, escalation=escalation,
                         finish_error=record.get('last_error'))
        except Exception as error:
            record['last_error'] = 'Pause step: ' + str(error)
            break
        finally:
            _save(path, record, clock)
    return pause


def run(controller, job_id, *, max_seconds=None, resume=False, poll_seconds=30,
        cancel_grace_seconds=120, min_free_bytes=None, clock=time, finish_fn=finish,
        pause_seconds=None, monitor_fn=None):
    """Start once, or explicitly observe a retained attempt against its old deadline.

    Controller must already be open. CLI callers can hold their normal shared
    session lock too. No resume path starts a pending job, retries a start or
    acquires agent ownership. All journals remain available for reviewed recovery.

    While a batch pause is pausing (studio_batch_pause), the driver hands every
    stop to the pause: it never sets cancel_issued, keeps its disk guard and
    finish, and adopts an outstanding unconfirmed stop instead of giving up on
    it. ``pause_seconds`` bounds a pause supervisor that resumes a retained
    journal; without it a pausing driver ends PAUSE_OVERRUN_SECONDS after its
    own deadline, before its host's execution limit.
    """
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job_id):
        raise ValueError('Invalid prepared batch ID')
    if type(resume) is not bool:
        raise ValueError('Resume must be an explicit boolean')
    if pause_seconds is not None and (not resume or type(pause_seconds) is not int or not 1 <= pause_seconds <= 172800):
        raise ValueError('A pause supervisor resumes a retained journal with 1..172800 seconds of supervision')
    if resume and min_free_bytes is not None:
        raise ValueError('Resume preserves the original disk guard; do not supply min_free_bytes')
    if not resume:
        min_free_bytes = DEFAULT_MIN_FREE_BYTES if min_free_bytes is None else min_free_bytes
        if type(min_free_bytes) is not int or min_free_bytes <= 0:
            raise ValueError('min_free_bytes must be a positive integer; disk guard cannot be disabled')
    if resume and max_seconds is not None:
        raise ValueError('Resume preserves the original budget; do not supply max_seconds')
    if not resume and (type(max_seconds) is not int or not 1 <= max_seconds <= 172800):
        raise ValueError('max_seconds must be an integer from 1 through 172800')
    for value, minimum, maximum in ((poll_seconds, .1, 60), (cancel_grace_seconds, 1, 600)):
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError('Polling and cancellation observation limits must be finite and bounded')
    call_wall, call_monotonic = clock.time(), clock.monotonic()
    if not math.isfinite(call_wall) or not math.isfinite(call_monotonic):
        raise ValueError('Driver clocks must be finite')
    root = safe_path(controller.root)
    gate = safe_path(root/'batch-driver-gate')
    journals = safe_path(root/'batch-drivers')
    gate.mkdir(exist_ok=True); journals.mkdir(exist_ok=True)
    path = safe_path(journals/(job_id+'.json'))
    with session_lock(controller), exclusive_gate(gate):
        if resume:
            record = read_json(path)
            if (record.get('schema_version') not in (1, 2) or type(record.get('max_seconds')) is not int
                    or not 1 <= record['max_seconds'] <= 172800
                    or record['deadline_wall'] != record['started_wall']+record['max_seconds']
                    or not all(type(record.get(k)) is bool for k in ('start_issued', 'cancel_issued', 'stopped'))
                    or record['binding']['job_id'] != job_id
                    or type(record.get('cancel_grace_seconds')) not in (int, float)
                    or not 1 <= record['cancel_grace_seconds'] <= 600
                    or any(type(record.get(k)) not in (int, float) or not math.isfinite(record[k])
                           for k in ('started_wall', 'deadline_wall', 'last_wall'))
                    or (record['cancel_issued'] and (type(record.get('cancel_deadline_wall')) not in (int, float)
                        or not math.isfinite(record['cancel_deadline_wall'])))):
                raise ValueError('Invalid retained batch driver journal')
            if _binding(controller, job_id) != record['binding']:
                raise ValueError('Batch/session/ownership changed; resume refused')
            if record['stopped']:
                pause = _pause(controller, job_id)
                if pause is not None and pause['state'] == 'pausing' and controller.job(job_id)['status'] in TERMINAL:
                    # Interrupted between the journal's stop and the pause record.
                    from studio_batch_pause import complete
                    complete(controller, job_id, now=clock.time())
                return _summary(path, record)
            if pause_seconds is not None and (_pause(controller, job_id) or {}).get('state') != 'pausing':
                raise ValueError('A pause supervisor requires a pausing batch')
            if (record.get('schema_version') != 2 or type(record.get('min_free_bytes')) is not int
                    or record['min_free_bytes'] <= 0):
                raise ValueError('Retained disk guard unavailable; active legacy driver needs reviewed recovery, not resume')
            if not record['start_issued'] or not record.get('attempt_id'):
                record['status'] = 'start_uncertain'
                record['last_error'] = 'No exact retained attempt; observe/reconcile manually. No start or cancel was issued.'
                _save(path, record, clock)
                return _summary(path, record)
        else:
            if path.exists():
                if not refused_before_dispatch(read_json(path), controller.job(job_id)):
                    raise ValueError('Driver journal exists; explicit resume required, never restart')
                _retire_refused_journal(controller, job_id, path, clock)
            binding = _binding(controller, job_id, verify_preparation=True)
            job = controller.job(job_id)
            if job['status'] != 'pending' or 'launch_intent' in job:
                raise ValueError('Only an unstarted pending prepared batch can be driven')
            if any(item['status'] in ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
                   for item in controller.state()['queue']):
                raise ValueError('Existing native work requires reconciliation')
            from studio_research_retry import inherited_budget
            inherited=inherited_budget(controller,job_id)
            if inherited is not None:
                min_free_bytes=max(min_free_bytes,inherited['min_free_bytes'])
                max_seconds=inherited['max_seconds']
            capacity = _capacity(controller, min_free_bytes)
            if capacity['reason']:
                raise ValueError('Batch dispatch refused: '+capacity['reason'])
            now = clock.time()
            if not math.isfinite(now):
                raise ValueError('Wall clock is not finite')
            if inherited is not None and inherited.get('fresh_native_epoch') and 'authority_expires_utc' in inherited:
                expiry=inherited['authority_expires_utc']
                if type(expiry) not in (int,float) or not math.isfinite(expiry) or now>=expiry:
                    raise ValueError('Research authority epoch expired before successor start')
                remaining=math.floor(expiry-now)
                if remaining<1:
                    raise ValueError('Research authority epoch has no whole second for successor start')
                max_seconds=min(max_seconds,remaining)
            record = dict(schema_version=2, binding=binding, max_seconds=max_seconds,
                          min_free_bytes=min_free_bytes, disk_observation=capacity,
                          started_wall=now, deadline_wall=now+max_seconds, last_wall=now,
                          start_issued=True, attempt_id=None, cancel_issued=False,
                          stopped=False, status='start_issued', cancel_grace_seconds=cancel_grace_seconds)
            if inherited is not None:
                if inherited.get('fresh_native_epoch'):
                    record['fresh_authority_budget']=inherited
                else:
                    if now>=inherited['deadline_wall']:raise ValueError('Original research deadline elapsed')
                    record.update(started_wall=inherited['started_wall'],deadline_wall=inherited['deadline_wall'],
                                  inherited_budget=inherited,replacement_created_wall=now)
            # Durable intent precedes any dispatch, including a crash before start.
            _save(path, record, clock)
            try:
                if _binding(controller, job_id) != binding:
                    raise ValueError('Batch authority changed before dispatch')
                def retain_attempt(intent):
                    if (not re.fullmatch(r'[a-f0-9]{64}',intent.get('attempt_id',''))
                            or intent.get('package_sha256')!=binding['package_sha256']):
                        raise ValueError('Config start returned a different attempt')
                    record['attempt_id']=intent['attempt_id']
                    _owned_attempt(controller,record)
                    _save(path,record,clock)
                if controller.session.get('authority_kind')=='demo_direct' and hasattr(controller,'start_config'):
                    controller.start_config(job_id,expected_generation=binding['generation'],on_attempt=retain_attempt)
                else:
                    controller.start(job_id,expected_generation=binding['generation'])
                intent = controller.job(job_id).get('launch_intent', {})
                if (not re.fullmatch(r'[a-f0-9]{64}', intent.get('attempt_id', ''))
                        or intent.get('package_sha256') != binding['package_sha256']):
                    raise ValueError('Start returned without an exact native attempt')
                record['attempt_id'] = intent['attempt_id']
                record['status'] = 'observing'
                _save(path, record, clock)
            except Exception as error:
                record['status'] = 'start_uncertain'; record['last_error'] = str(error)
                _save(path, record, clock)
                return _summary(path, record)
        wall_start, monotonic_start = call_wall, call_monotonic
        rollback = clock.time() < record['last_wall']
        monotonic_deadline = monotonic_start+max(0, record['deadline_wall']-wall_start)
        supervision_deadline = (monotonic_start+pause_seconds if pause_seconds is not None
                                else monotonic_deadline+PAUSE_OVERRUN_SECONDS)
        cancel_mono_deadline = None
        if record['cancel_issued']:
            cancel_mono_deadline = monotonic_start+min(record['cancel_grace_seconds'], max(0, record['cancel_deadline_wall']-wall_start))
        while True:
            now, mono = clock.time(), clock.monotonic()
            rollback = rollback or now < record['last_wall'] or now-wall_start+.05 < mono-monotonic_start
            try:
                _owned_attempt(controller, record)
            except Exception as error:
                record['status'] = 'ownership_or_binding_changed'; record['last_error'] = str(error)
                _save(path, record, clock)
                return _summary(path, record)
            pause = _pause(controller, job_id)
            pausing = pause is not None and pause['state'] == 'pausing'
            if not record['cancel_issued'] or pausing:
                record['disk_observation'] = _capacity(controller, record['min_free_bytes'])
            try:
                if controller.job(job_id)['status'] not in TERMINAL:
                    controller.reconcile(job_id)
                _owned_attempt(controller, record)
                result = finish_fn(controller, job_id, expected_generation=record['binding']['generation'])
                if result.get('status') not in TERMINAL or result.get('result', {}).get('attempt_id') != record['attempt_id']:
                    raise ValueError('Finish did not verify this exact attempt')
                record.update(status=result['status'], stopped=True, last_error=None,
                              result_path=result.get('result_path') or controller.job(job_id).get('completion_path'))
                _save(path, record, clock)
                if pausing:
                    from studio_batch_pause import complete
                    done = complete(controller, job_id, now=clock.time())
                    record.update(status='paused' if done['state'] == 'paused' else record['status'],
                                  pause_id=done['pause_id'])
                    _save(path, record, clock)
                return _summary(path, record)
            except Exception as error:
                record['last_error'] = str(error)
            now, mono = clock.time(), clock.monotonic()
            rollback = rollback or now < record['last_wall'] or now-wall_start+.05 < mono-monotonic_start
            disk_reason = record.get('disk_observation', {}).get('reason')
            owner_stop = None
            if controller.session.get('authority_kind') == 'demo_direct':
                if (controller.root/'demo-agent/STOP').exists():
                    owner_stop = 'owner_stop'
                else:
                    human = controller.bridge.root/'human'
                    if any(any((human/channel).glob('*.json')) for channel in ('inbox','processing')):
                        owner_stop = 'human_take_control'
            if pausing:
                # Every stop belongs to the pause: no cancel_issued, no grace give-up.
                from studio_batch_pause import step, observe_monitor
                # Owner STOP and the driver deadline never escalate a running pause: the
                # pause is already the stop, and its single cancel must still wait for a
                # safe point (the 06:33Z cancel expired at a member-boundary relaunch).
                # Only low disk and a clock rollback justify publishing immediately.
                escalation = disk_reason or ('clock_rollback' if rollback else None)
                record.update(status='pausing', pause_id=pause['pause_id'])
                try:
                    monitor = (monitor_fn or observe_monitor)(controller, now)
                    pause = step(controller, job_id, now=now, monitor=monitor, escalation=escalation,
                                 finish_error=record.get('last_error'))
                except Exception as error:
                    record['last_error'] = 'Pause step: ' + str(error)
                else:
                    pause = _fast_watch(controller, job_id, record, path, clock, monitor_fn, pause, escalation,
                                        until=min(mono+FAST_WATCH_SECONDS, supervision_deadline),
                                        wall_start=wall_start, monotonic_start=monotonic_start)
                    mono = clock.monotonic()
                if pause is not None and pause.get('state') == 'pause_failed':
                    # A failed pause sent nothing it could not prove; the original
                    # driver keeps supervising the still-running batch normally.
                    record.update(status='pause_failed' if pause_seconds is not None else 'observing',
                                  pause_failure=pause.get('failure'))
                    _save(path, record, clock)
                    if pause_seconds is not None:
                        return _summary(path, record)
                    clock.sleep(min(poll_seconds, max(.01, monotonic_deadline-mono)))
                    continue
                if mono >= supervision_deadline:
                    record['pause_supervision'] = 'budget_exhausted'
                    _save(path, record, clock)
                    return _summary(path, record)
                _save(path, record, clock)
                clock.sleep(min(poll_seconds, max(.01, supervision_deadline-mono)))
                continue
            if pause_seconds is not None:
                # The pause settled elsewhere; this supervisor has nothing left to do.
                _save(path, record, clock)
                return _summary(path, record)
            if record['cancel_issued'] or owner_stop or disk_reason or rollback or now >= record['deadline_wall'] or mono >= monotonic_deadline:
                if not record['cancel_issued']:
                    try:
                        _owned_attempt(controller, record)
                    except Exception as error:
                        record['status'] = 'ownership_or_binding_changed'; record['last_error'] = str(error)
                        _save(path, record, clock)
                        return _summary(path, record)
                    grace = record['cancel_grace_seconds']
                    record.update(cancel_issued=True, status='cancel_requested_unconfirmed',
                                  cancel_deadline_wall=now+grace,
                                  cancel_reason=owner_stop or disk_reason or ('clock_rollback' if rollback else 'deadline'))
                    cancel_mono_deadline = mono+grace
                    _save(path, record, clock)
                    try:
                        controller.cancel(job_id, expected_generation=record['binding']['generation'])
                    except Exception as error:
                        record['last_error'] = str(error)
                if (mono >= cancel_mono_deadline or now >= record['cancel_deadline_wall']):
                    record['status'] = 'stop_unconfirmed'
                    _save(path, record, clock)
                    return _summary(path, record)
            _save(path, record, clock)
            remaining = (cancel_mono_deadline if record['cancel_issued'] else monotonic_deadline)-mono
            clock.sleep(min(poll_seconds, max(.01, remaining)))


def status(controller, job_id):
    """Read the atomically retained driver record, even while its lock is held."""
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job_id):
        raise ValueError('Invalid prepared batch ID')
    path = safe_path(controller.root/'batch-drivers'/(job_id+'.json'))
    with session_lock(controller):
        record = read_json(path)
        if record.get('schema_version') not in (1, 2) or record['binding']['job_id'] != job_id:
            raise ValueError('Invalid retained batch driver journal')
        try:
            matches = _binding(controller, job_id) == record['binding']
        except (ValueError, OSError, KeyError):
            matches = False
        return _summary(path, record) | dict(current_binding_matches=matches,
            last_recorded_wall=record['last_wall'], observation='retained_driver_record_not_fresh_native_state')
