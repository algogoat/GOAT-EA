"""Bounded supervision of one frozen native batch; never a process watchdog.

Host/controller liveness is required. Native cancellation is a request until
studio_finish verifies completion. An interrupted uncertain start is never
retried or adopted, and a revoked owner never cancels a successor's work.
"""
import hashlib
import math
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
            'min_free_bytes', 'cancel_reason', 'disk_observation')} | dict(
        journal_path=str(path), job_id=record['binding']['job_id'],
        disk_guard_available=(record.get('schema_version') == 2 and type(record.get('min_free_bytes')) is int
                              and record['min_free_bytes'] > 0),
        host_liveness_required=True, independent_hard_stop=False)


def run(controller, job_id, *, max_seconds=None, resume=False, poll_seconds=5,
        cancel_grace_seconds=120, min_free_bytes=None, clock=time, finish_fn=finish):
    """Start once, or explicitly observe a retained attempt against its old deadline.

    Controller must already be open. CLI callers can hold their normal shared
    session lock too. No resume path starts a pending job, retries a start or
    acquires agent ownership. All journals remain available for reviewed recovery.
    """
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job_id):
        raise ValueError('Invalid prepared batch ID')
    if type(resume) is not bool:
        raise ValueError('Resume must be an explicit boolean')
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
                return _summary(path, record)
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
                raise ValueError('Driver journal exists; explicit resume required, never restart')
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
                controller.start(job_id, expected_generation=binding['generation'])
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
            if not record['cancel_issued']:
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
                return _summary(path, record)
            except Exception as error:
                record['last_error'] = str(error)
            now, mono = clock.time(), clock.monotonic()
            rollback = rollback or now < record['last_wall'] or now-wall_start+.05 < mono-monotonic_start
            disk_reason = record.get('disk_observation', {}).get('reason')
            if record['cancel_issued'] or disk_reason or rollback or now >= record['deadline_wall'] or mono >= monotonic_deadline:
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
                                  cancel_reason=disk_reason or ('clock_rollback' if rollback else 'deadline'))
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
