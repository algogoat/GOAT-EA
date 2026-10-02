"""Pause and resume a native batch at a safe point; never replay a stop blindly.

``request`` records one durable pause intent. The bounded driver, or a pause
supervisor when no driver is alive, calls ``step`` on every tick:

    waiting_safe_point -> cancel_published -> [successor_published] -> finishing -> paused

* One cancel is published only at a safe point while the bound monitor ticks:
  within the first SAFE_START_SECONDS of a member that just turned OnGoing (never
  inside its last MIN_REMAINING_SECONDS when the pace is known), or with no
  member active, the tester idle and the member-boundary relaunch finished.
  Escalation (owner STOP, human TAKE pending, low disk, clock rollback, the
  driver deadline) drops the member-age rule, never the ticking-monitor rule.
* An expired, unconsumed cancel is never replaced while it is unanswered: the EA
  answers it with CANCEL_REJECTED on its first bound tick. Only that exact
  receipt, observed after expiry, admits exactly one successor identity, linked
  first in ``cancel-successors/<attempt>.json`` under the cancel-rejected-successor
  identity rules, so ``finish`` and the settled-gate checks bind it. Both stop
  receipts are kept.
* A closed, unbound or unlicensed monitor is a named blocker with a fix, never a
  silent wait. So is a member pace too fast for any safe window.
* A pause never sets the driver journal's ``cancel_issued``, so the journal is
  never poisoned: the driver keeps its disk guard and finish throughout, and a
  resumed driver keeps supervising. A journal an owner STOP already left at
  ``stop_unconfirmed`` is adopted: its outstanding cancel becomes the pause's.
* ``paused`` carries a resume token bound to the exact finish result. Resume
  builds the remaining work from per-member native evidence and records lineage.
"""
import calendar
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json

SCHEMA_VERSION = 1
FOLDER = 'batch-pauses'
LINEAGE = 'batch-lineage'
SAFE_START_SECONDS = 300
MIN_REMAINING_SECONDS = 180
# Below this, the median member is too short for the remaining-time rule to ever
# admit a member start; that is a named blocker, never a silent wait.
MIN_SAFE_WINDOW_SECONDS = 20
FINISH_PATIENCE_SECONDS = 900
HISTORY_LIMIT = 200
MAX_MANIFEST_BYTES = 64 * 1024 * 1024  # package manifests scale with member count
ACTIVE = frozenset(('starting', 'running', 'reconcile_required', 'verifying'))
TERMINAL = frozenset(('completed', 'cancelled', 'failed'))
JOB_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')

PLAIN = {
    'waiting_safe_point': ('Waiting for a safe point: the pause is sent right after the next member starts, '
                           'so the running member finishes and is kept.'),
    'cancel_publishing': 'Sending the pause to MT5.',
    'cancel_published': 'Pause sent to MT5; waiting for MT5 to confirm it.',
    'cancel_expired_awaiting_receipt': ('MT5 did not take the pause in time; GOAT waits for its answer, '
                                        'then sends one replacement.'),
    'cancel_rejected_waiting_safe_point': ('MT5 answered that the pause arrived too late; one replacement is sent '
                                           'at the next safe point.'),
    'successor_publishing': 'Sending the replacement pause to MT5.',
    'successor_published': 'Replacement pause sent to MT5; waiting for MT5 to confirm it.',
    'finishing': "MT5 stopped the batch; collecting the finished members' results.",
    'paused': 'Paused. Finished members are saved; Resume continues the remaining members.',
    'finished': 'Every member finished before the pause took effect; there is nothing left to resume.',
    'resumed': 'Resumed: the remaining members continue in a successor batch.',
}
RECEIPT_FAILURES = {
    'CANCEL_CONTROL_REVOKED': ('MT5 refused the pause because control of this batch changed in MT5.',
                               'Check the GOAT Studio panel in MT5 and Give to Agent before pausing again.'),
    'CANCEL_NATIVE_OWNER_CHANGED': ('MT5 refused the pause because this batch no longer owns the native queue.',
                                    'Run batch-status to see which run owns MT5 now; nothing was replayed.'),
    'CANCEL_RUN_CHANGED': ('MT5 refused the pause because a different native run is active.',
                           'Run batch-status to see the active run; nothing was replayed.'),
    'CANCEL_PATH_REJECTED': ('MT5 refused the pause request format.',
                             'Install the controller and EA from the same GOAT build, then pause again.'),
    'CANCEL_SNAPSHOT_REJECTED': ('MT5 could not read the controller snapshot when the pause arrived.',
                                 'Keep MT5 open and run batch-status once; nothing was replayed.'),
    'CANCEL_ALREADY_CONSUMED': ('MT5 had already consumed this exact pause request.',
                                'Run batch-status; a Cancelled queue finishes by itself.'),
}


class PauseRefused(ValueError):
    """A plain, actionable reason a pause or resume cannot proceed."""


def path(root, job_id):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError('Invalid batch ID')
    return safe_path(Path(root) / FOLDER / (job_id + '.json'))


def load(root, job_id, *, quiet=False):
    try:
        target = path(root, job_id)
        if not target.is_file():
            return None
        value = read_json(target)
        if value.get('schema_version') != SCHEMA_VERSION or value.get('job_id') != job_id:
            raise ValueError('Invalid retained pause record')
        return value
    except (OSError, ValueError, KeyError, TypeError):
        if quiet:
            return None
        raise


def _save(root, record):
    write_json(path(root, record['job_id']), record)


def _note(record, now, phase, **detail):
    record['phase'] = phase
    record['updated_utc'] = now
    history = record.setdefault('history', [])
    if not history or history[-1].get('phase') != phase or detail:
        history.append(dict(at=now, phase=phase, **detail))
        del history[:-HISTORY_LIMIT]


def plain(record):
    if record.get('state') == 'pause_failed':
        failure = record.get('failure') or {}
        return 'Pause failed: ' + str(failure.get('message', 'unknown reason')) + ' ' + str(failure.get('fix', ''))
    text = PLAIN.get(record.get('phase'), 'Pausing.')
    blocker = record.get('blocker')
    if record.get('state') == 'pausing' and blocker:
        text += ' Blocked: ' + blocker['message'] + ' ' + blocker['fix']
    return text


def public(record):
    keys = ('job_id', 'pause_id', 'state', 'phase', 'mode', 'escalation', 'requested_utc', 'requested_by', 'updated_utc',
            'paused_utc', 'blocker', 'failure', 'resume_token', 'members_completed', 'members_remaining',
            'members_failed', 'result_path', 'successor_batch_id', 'safe_point', 'adopted_stop')
    value = {key: record.get(key) for key in keys}
    value['cancels'] = [{key: item.get(key) for key in ('request_id', 'kind', 'published_utc', 'expires_utc', 'receipt',
                                                       'adopted')} for item in record.get('cancels', [])]
    value['plain'] = plain(record)
    return value


def request(root, job, journal, *, now, requested_by='agent', immediate=False):
    """Create the durable pause intent once; a repeat returns the retained record.

    Returns (record, created). No native, journal or queue effect happens here.
    """
    job_id = job['job_id']
    existing = load(root, job_id)
    if existing is not None:
        if immediate and existing['state'] == 'pausing' and existing.get('mode') != 'immediate':
            existing.update(mode='immediate', escalation=existing.get('escalation') or 'requested_immediate')
            _note(existing, now, existing['phase'], escalation='requested_immediate')
            _save(root, existing)
        return existing, False
    if job.get('status') not in ACTIVE:
        raise PauseRefused('Batch ' + job_id + ' is ' + str(job.get('status')) + ', not running, so there is nothing to pause.')
    attempt = (job.get('launch_intent') or {}).get('attempt_id')
    if (not isinstance(journal, dict) or journal.get('attempt_id') != attempt or not isinstance(attempt, str)
            or not re.fullmatch(r'[a-f0-9]{64}', attempt)):
        raise PauseRefused('Batch ' + job_id + ' has no bounded GOAT driver journal for its running attempt, '
                           'so GOAT cannot pause it safely; inspect it with batch-status.')
    if journal.get('stopped') is True:
        raise PauseRefused('Batch ' + job_id + ' already stopped (' + str(journal.get('status')) + ').')
    record = dict(schema_version=SCHEMA_VERSION, job_id=job_id, pause_id=uuid.uuid4().hex, attempt_id=attempt,
                  configuration_sha256=job['configuration_sha256'], generation=journal['binding']['generation'],
                  state='pausing', mode='immediate' if immediate else 'safe_point', escalation=None,
                  requested_utc=now, requested_by=requested_by, cancels=[], blocker=None, failure=None,
                  member_watch={}, adopted_stop=journal.get('cancel_issued') is True,
                  adopted_stop_reason=journal.get('cancel_reason'), history=[])
    _note(record, now, 'waiting_safe_point', requested_by=requested_by)
    target = path(root, job_id)
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(record, stream, ensure_ascii=False, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    try:
        # A hard link publishes the complete record only if no other intent exists.
        os.link(temporary, target)
    except FileExistsError:
        return load(root, job_id), False
    finally:
        temporary.unlink(missing_ok=True)
    return record, True


def rejected_after_expiry(receipt, request_value):
    """True only when MT5 observed the cancel at or after its own expiry."""
    try:
        observed = calendar.timegm(time.strptime(receipt['observed_utc'], '%Y.%m.%d %H:%M:%S'))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    expires = request_value.get('expires_utc')
    return type(expires) is int and observed >= expires


def _fail(root, record, now, code, message, fix):
    record.update(state='pause_failed', failure=dict(code=code, message=message, fix=fix), blocker=None)
    _note(record, now, 'pause_failed', code=code)
    _save(root, record)
    return record


def _watch(record, statuses, now):
    """Remember when the active member changed while this pause was watching.

    ``transition_observed`` means the change happened between two of our own
    observations, so ``first_seen_wall`` bounds the member's start to one poll.
    """
    current = next((i for i, status in enumerate(statuses) if status == 'native_ongoing'), None)
    watch = record.setdefault('member_watch', {})
    if 'index' not in watch:
        watch.update(index=current, first_seen_wall=None if current is None else now, transition_observed=False)
    elif watch['index'] != current:
        watch.update(index=current, first_seen_wall=None if current is None else now, transition_observed=True)
    return watch


def _process_started(process):
    try:
        text = process['created_utc'].replace('Z', '+00:00')
        from datetime import datetime
        return datetime.fromisoformat(text).timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def safe_point(record, monitor, statuses, timing, *, now, member_seconds=None, process=None):
    """Whether a cancel published now reaches a ticking monitor well inside its 120 s life."""
    if not monitor.get('ticking'):
        return dict(ok=False, kind=None, reason='monitor_not_ticking')
    current = next((i for i, status in enumerate(statuses) if status == 'native_ongoing'), None)
    if record.get('mode') == 'immediate':
        # Escalation drops the member-age rule, never the relaunch rules: a cancel sent
        # into a pending restart, or to a monitor that has not ticked since MT5 last
        # started, can expire unconsumed exactly like the 06:33Z cancel.
        if monitor.get('restart_pending') is not False:
            return dict(ok=False, kind=None, reason='restart_pending')
        launched = _process_started(process) if isinstance(process, dict) else None
        heartbeat = monitor.get('heartbeat_wall')
        if launched is None or heartbeat is None or heartbeat < launched:
            return dict(ok=False, kind=None, reason='monitor_not_ticked_since_process_start')
        return dict(ok=True, kind='immediate', reason=record.get('escalation') or 'requested_immediate')
    watch = record.get('member_watch') or {}
    if current is not None:
        started, source = None, None
        if timing and current in timing.get('started', {}):
            started, source = timing['started'][current], 'native_timeline'
        elif watch.get('index') == current and watch.get('transition_observed'):
            started, source = watch.get('first_seen_wall'), 'observed_transition'
        if started is None:
            return dict(ok=False, kind=None, reason='waiting_next_member', member=current + 1)
        if member_seconds and member_seconds - MIN_REMAINING_SECONDS < MIN_SAFE_WINDOW_SECONDS:
            return dict(ok=False, kind=None, reason='pace_leaves_no_safe_window', member=current + 1,
                        member_seconds=round(member_seconds))
        age = now - started
        if age > SAFE_START_SECONDS:
            return dict(ok=False, kind=None, reason='waiting_next_member', member=current + 1, member_age_seconds=round(age))
        if member_seconds and member_seconds - age < MIN_REMAINING_SECONDS:
            return dict(ok=False, kind=None, reason='member_too_close_to_end', member=current + 1)
        heartbeat = monitor.get('heartbeat_wall')
        if heartbeat is None or heartbeat < started:
            return dict(ok=False, kind=None, reason='monitor_not_ticked_since_member_start', member=current + 1)
        return dict(ok=True, kind='member_started', member=current + 1, member_age_seconds=round(max(0, age)), source=source)
    if any(status in ('native_queued', 'native_pending') for status in statuses):
        ended = [value for value in (timing or {}).get('ended', {}).values()]
        started = _process_started(process) if isinstance(process, dict) else None
        if (monitor.get('tester_state') == 'idle' and monitor.get('restart_pending') is False and ended
                and started is not None and started >= max(ended)):
            return dict(ok=True, kind='tester_idle_after_relaunch')
    return dict(ok=False, kind=None, reason='between_members')


def _pace_blocker(record, point):
    """Name the wait the pace makes endless, unless a monitor blocker already explains it."""
    if point.get('reason') != 'pace_leaves_no_safe_window' or record.get('blocker') is not None:
        return
    minutes = round(point.get('member_seconds', 0) / 60, 1)
    record['blocker'] = dict(
        code='pace_leaves_no_safe_window',
        message=('Members finish in about ' + str(minutes) + ' min, too fast for the safe pause window: a member must '
                 'still have ' + str(MIN_REMAINING_SECONDS) + ' s to run when the pause is sent, so it is not sent.'),
        fix=('The pause keeps checking and is sent once members take longer on average. To stop now, use STOP in '
             'the GOAT Studio panel in MT5 and follow NATIVE-RECOVERY-CONTRACT.md to keep finished members.'))


def _entry(record, request_id, kind, issued):
    for item in record.setdefault('cancels', []):
        if item.get('request_id') == request_id:
            break
    else:
        item = dict(request_id=request_id, kind=kind, adopted=True)
        record['cancels'].append(item)
    if issued is not None:
        item.setdefault('expires_utc', issued['request'].get('expires_utc'))
        item.setdefault('published_utc', None)
    return item


def _native(controller, job, now):
    from studio_native_observe import observe
    from studio_research_status import timeline, pace, _bounded_json
    package = Path(job['launch_intent']['package'])
    native = observe(package)
    if native.get('status') == 'native_evidence_missing':
        return native, [], None, None
    statuses = [member['status'] for member in native['members']]
    # Package manifests grow with the batch (g6's 1,265 members are ~2.8 MB), past
    # read_json's 2 MB envelope cap; read it like the native observer does, bounded.
    # Unreadable evidence only ever means "keep waiting", never "publish".
    manifest, _ = _bounded_json(package / 'manifest.json', MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('jobs'), list):
        return native, [], None, None
    common_run = Path(controller.install['common_files_root']) / manifest['native_run_relative'].replace('\\', '/')
    timing = timeline(common_run, [item['run_alias'] for item in manifest['jobs']])
    member = pace(timing, statuses, now=now)['member_minutes_median']
    return native, statuses, timing, None if member is None else member * 60


def observe_monitor(controller, now, *, process_fn=None):
    """Monitor classification for the driver; process inspection failure stays 'unknown'."""
    from studio_research_status import monitor_state
    try:
        if process_fn is None:
            from studio_seed_process import WindowsSeedProcess
            process = WindowsSeedProcess(controller).inspect()
        else:
            process = process_fn()
    except (OSError, ValueError, subprocess.SubprocessError):
        process = 'unknown'
    state = monitor_state(controller.install, controller.session, controller.local, now=now, process=process)
    state['process'] = process if isinstance(process, dict) else None
    return state


def _publish(controller, record, now, request_id, kind, point):
    root = controller.root
    item = _entry(record, request_id, kind, None)
    item.update(decided_utc=now, safe_point=point.get('kind'), adopted=False)
    _note(record, now, 'cancel_publishing' if kind == 'original' else 'successor_publishing', request_id=request_id)
    _save(root, record)
    controller.cancel(record['job_id'], expected_generation=record['generation'])
    gate = controller.local / 'native-gate'
    issued = read_json(gate / ('issued-' + request_id + '.json'))
    item.update(published_utc=now, expires_utc=issued['request']['expires_utc'])
    _note(record, now, 'cancel_published' if kind == 'original' else 'successor_published', request_id=request_id)
    _save(root, record)
    return record


def create_successor(controller, job_id, record, *, now):
    """Link one successor stop identity after the exact expired, unconsumed CANCEL_REJECTED.

    Same identity rules as cancel-rejected-successor; the linkage is committed
    before publication, so an interrupted publication can only publish this stop.
    """
    from studio_cancel_successor import cancel_id
    from studio_dispatch_observe import observe_dispatch
    from studio_native_gate import exclusive_gate
    job = controller.job(job_id)
    attempt = job['launch_intent']['attempt_id']
    gate = controller.local / 'native-gate'
    folder = safe_path(controller.root / 'cancel-successors')
    target = folder / (attempt + '.json')
    with exclusive_gate(gate):
        if target.exists():
            return cancel_id(controller.root, job, gate)
        state = controller.state()
        if state['owner'] != 'agent':
            raise PauseRefused('Control of this batch changed in MT5; no replacement pause was sent.')
        original = sha([attempt, 'cancel'])
        prior = observe_dispatch(gate, original)
        issued_path = gate / ('issued-' + original + '.json')
        issued = read_json(issued_path)['request']
        if (prior.get('consumed') is not False or prior.get('status') != 'receipt_observed'
                or prior['receipt'].get('status') != 'CANCEL_REJECTED' or issued['expires_utc'] >= now
                or not rejected_after_expiry(prior['receipt'], issued)):
            raise PauseRefused('A replacement pause needs the exact expired, unconsumed CANCEL_REJECTED receipt.')
        if issued['generation'] != state['generation'] or issued['job_id'] != job_id or issued.get('attempt_id') != attempt:
            raise PauseRefused('The batch identity changed since the first pause was sent; no replacement was sent.')
        issued_hash = hashlib.sha256(issued_path.read_bytes()).hexdigest()
        value = dict(schema_version=1, attempt_id=attempt, job_id=job_id, configuration_sha256=job['configuration_sha256'],
                     terminal_id=controller.terminal, run_id=controller.run, generation=state['generation'],
                     gate=str(gate), prior_request_id=original, prior_issued_sha256=issued_hash,
                     prior_result_sha256=hashlib.sha256((gate / ('result-' + original + '.json')).read_bytes()).hexdigest(),
                     request_id=sha([attempt, 'cancel-successor', issued_hash]), origin='batch_pause',
                     pause_id=record['pause_id'], created_utc=now)
        folder.mkdir(exist_ok=True)
        write_json(target, value)
        return cancel_id(controller.root, job, gate)


def step(controller, job_id, *, now, monitor, escalation=None, finish_error=None):
    """Advance one pausing record by at most one native effect. Idempotent and crash-safe."""
    from studio_cancel_successor import cancel_id
    from studio_dispatch_observe import observe_dispatch
    root = controller.root
    record = load(root, job_id)
    if record is None or record['state'] != 'pausing':
        return record
    job = controller.job(job_id)
    attempt = (job.get('launch_intent') or {}).get('attempt_id')
    if attempt != record['attempt_id'] or job['configuration_sha256'] != record['configuration_sha256']:
        return _fail(root, record, now, 'attempt_changed', 'The running attempt changed after the pause was requested.',
                     'Run batch-status before pausing again; nothing was sent.')
    if job['status'] in TERMINAL:
        return record
    if escalation and record.get('mode') != 'immediate':
        record.update(mode='immediate', escalation=escalation)
        _note(record, now, record['phase'], escalation=escalation)
    record['monitor'] = {key: monitor.get(key) for key in ('state', 'ticking', 'transient', 'heartbeat_age_seconds')}
    record['blocker'] = monitor.get('blocker')
    gate = controller.local / 'native-gate'
    original = sha([attempt, 'cancel'])
    current = cancel_id(root, job, gate)
    kind = 'original' if current == original else 'successor'
    dispatch = observe_dispatch(gate, current)
    issued_path = gate / ('issued-' + current + '.json')
    issued = read_json(issued_path) if issued_path.is_file() else None

    if dispatch['status'] == 'not_issued':
        native, statuses, timing, member_seconds = _native(controller, job, now)
        if not statuses:
            record['safe_point'] = dict(ok=False, reason='native_evidence_missing')
            _note(record, now, 'waiting_safe_point'); _save(root, record)
            return record
        _watch(record, statuses, now)
        point = safe_point(record, monitor, statuses, timing, now=now, member_seconds=member_seconds,
                           process=monitor.get('process'))
        record['safe_point'] = point
        _pace_blocker(record, point)
        if not point['ok']:
            _note(record, now, 'waiting_safe_point' if kind == 'original' else 'cancel_rejected_waiting_safe_point')
            _save(root, record)
            return record
        return _publish(controller, record, now, current, kind, point)

    item = _entry(record, current, kind, issued)
    if dispatch['status'] == 'awaiting_receipt':
        expires = (issued or {}).get('request', {}).get('expires_utc')
        if dispatch.get('consumed'):
            _note(record, now, 'finishing')
        elif type(expires) is int and now < expires:
            _note(record, now, 'cancel_published' if kind == 'original' else 'successor_published')
        else:
            # Expired and unanswered: the EA answers it on its first bound tick.
            # Never replace it before that receipt; the monitor blocker says why it waits.
            _note(record, now, 'cancel_expired_awaiting_receipt')
        _save(root, record)
        return record

    receipt = dispatch['receipt']['status']
    item.update(receipt=receipt, consumed=dispatch.get('consumed'))
    if receipt in ('CANCELLED_RECONCILE', 'CANCEL_SIGNAL_SENT_RECONCILE'):
        if record.get('phase') != 'finishing':
            record['finishing_since'] = now
        _note(record, now, 'finishing')
        since = record.get('finishing_since') or now
        if record['blocker'] is None and finish_error and now - since > FINISH_PATIENCE_SECONDS:
            record['blocker'] = dict(code='finish_waiting', message='MT5 stopped the batch but GOAT cannot finish it yet: '
                                     + str(finish_error)[:200], fix='Keep MT5 open with the GOAT monitor reporting; finish retries every tick.')
        _save(root, record)
        return record
    if receipt == 'CANCEL_REJECTED':
        request_value = (issued or {}).get('request', {})
        if kind == 'successor':
            return _fail(root, record, now, 'successor_rejected',
                         'MT5 did not take the replacement pause either, so GOAT stopped sending pauses rather than replay one blindly.',
                         'The batch keeps running under supervision; stop it from the GOAT Studio panel in MT5 '
                         'and follow NATIVE-RECOVERY-CONTRACT.md to keep its finished members.')
        if dispatch.get('consumed') is not False or not rejected_after_expiry(dispatch['receipt'], request_value):
            return _fail(root, record, now, 'cancel_refused',
                         'MT5 refused the pause itself (an identity check), not because it arrived late, so no replacement was sent.',
                         'Run batch-status to check this installation still matches the running MT5 terminal, account and data folder.')
        native, statuses, timing, member_seconds = _native(controller, job, now)
        if statuses:
            _watch(record, statuses, now)
        point = safe_point(record, monitor, statuses, timing, now=now, member_seconds=member_seconds,
                           process=monitor.get('process')) if statuses else dict(ok=False, reason='native_evidence_missing')
        record['safe_point'] = point
        _pace_blocker(record, point)
        if not point['ok']:
            _note(record, now, 'cancel_rejected_waiting_safe_point')
            _save(root, record)
            return record
        _note(record, now, 'successor_publishing')
        _save(root, record)
        try:
            successor = create_successor(controller, job_id, record, now=now)
        except PauseRefused as error:
            return _fail(root, record, now, 'successor_refused', str(error),
                         'Run batch-status before any other action; nothing was replayed.')
        return _publish(controller, record, now, successor, 'successor', point)
    message, fix = RECEIPT_FAILURES.get(receipt, ('MT5 answered the pause with ' + receipt + '.',
                                                  'Run batch-status before any other action; nothing was replayed.'))
    return _fail(root, record, now, 'receipt_' + receipt.lower(), message, fix)


def resume_token(job_id, attempt_id, result_sha256):
    return hashlib.sha256(('goat-batch-pause-v1\n' + job_id + '\n' + attempt_id + '\n' + result_sha256).encode()).hexdigest()


def complete(controller, job_id, *, now):
    """Record paused (or finished) after studio_finish verified the stopped batch."""
    root = controller.root
    record = load(root, job_id)
    if record is None or record['state'] != 'pausing':
        return record
    job = controller.job(job_id)
    if job['status'] not in TERMINAL or not job.get('completion_path'):
        raise ValueError('Pause completion requires a verified finished batch')
    result_path = Path(job['completion_path'])
    digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    outcomes = [member['status'] for member in job['completion']['member_outcomes']]
    completed = outcomes.count('native_completed')
    failed = outcomes.count('native_error')
    remaining = len(outcomes) - completed - failed
    record.update(result_path=str(result_path), result_sha256=digest, members_completed=completed,
                  members_remaining=remaining, members_failed=failed, paused_utc=now, blocker=None,
                  batch_status=job['status'])
    if remaining == 0 and failed == 0:
        record['state'] = 'finished'
        _note(record, now, 'finished')
    else:
        record.update(state='paused', resume_token=resume_token(job_id, record['attempt_id'], digest))
        _note(record, now, 'paused')
    _save(root, record)
    return record


def refusal(record):
    """The plain reason a record that is not paused cannot be resumed."""
    job_id = record['job_id']
    if record['state'] == 'pausing':
        return PauseRefused('Batch ' + job_id + ' is still pausing: ' + plain(record))
    if record['state'] == 'pause_failed':
        return PauseRefused(plain(record))
    if record['state'] == 'finished':
        return PauseRefused('Every member of batch ' + job_id + ' finished; there is nothing left to resume.')
    return PauseRefused('Batch ' + job_id + ' is ' + str(record['state']) + '.')


def verify_resumable(controller, job_id, token=None):
    """The exact paused record, re-bound to its retained finish result."""
    record = load(controller.root, job_id)
    if record is None:
        raise PauseRefused('No pause is recorded for batch ' + job_id + '; pause it first.')
    if record['state'] not in ('paused', 'resumed'):
        raise refusal(record)
    job = controller.job(job_id)
    result_path = Path(record['result_path'])
    if (job['status'] not in ('cancelled', 'failed') or job.get('completion_path') != str(result_path)
            or hashlib.sha256(result_path.read_bytes()).hexdigest() != record['result_sha256']
            or record['resume_token'] != resume_token(job_id, record['attempt_id'], record['result_sha256'])):
        raise PauseRefused('The paused result of batch ' + job_id + ' changed; inspect it with batch-status before resuming.')
    if token is not None and token != record['resume_token']:
        raise PauseRefused('Resume token does not match the paused batch ' + job_id + '.')
    return record


def successor_id(source, existing):
    """`<base>-rN`: the next free resume identity, within the 80-character limit."""
    match = re.fullmatch(r'(.+)-r([1-9][0-9]{0,3})', source)
    base, number = (match[1], int(match[2]) + 1) if match else (source, 1)
    while True:
        suffix = '-r' + str(number)
        candidate = base[:80 - len(suffix)] + suffix
        if candidate not in existing:
            return candidate
        number += 1


def plan_resume(root, job_id, new_id, *, now):
    """Fix the successor ID before preparing it, so an interrupted resume reuses it."""
    record = load(root, job_id)
    planned = record.get('resume_batch_id')
    if planned and planned != new_id:
        raise PauseRefused('Batch ' + job_id + ' is already resuming as ' + planned + '; resume again without a new batch ID.')
    if not planned:
        record['resume_batch_id'] = new_id
        _note(record, now, record['phase'], resume_batch_id=new_id)
        _save(root, record)
    return record


def mark_resumed(root, job_id, new_id, *, now, selected):
    record = load(root, job_id)
    lineage_path = safe_path(Path(root) / LINEAGE / (new_id + '.json'))
    if not lineage_path.exists():
        lineage_path.parent.mkdir(exist_ok=True)
        write_json(lineage_path, dict(schema_version=1, batch_id=new_id, predecessor_batch_id=job_id,
                                      pause_id=record['pause_id'], resume_token=record['resume_token'],
                                      predecessor_result_sha256=record['result_sha256'], members_selected=selected,
                                      created_utc=now))
    if record['state'] != 'resumed' or record.get('successor_batch_id') != new_id:
        record.update(state='resumed', successor_batch_id=new_id, resumed_utc=now)
        _note(record, now, 'resumed', successor_batch_id=new_id)
        _save(root, record)
    return record
