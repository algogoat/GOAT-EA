"""One more stop identity per genuine human re-grant of a stranded demo batch.

The deadlock (a reboot, a rejected cancel, one successor, then TAKE CONTROL): only
finish settles the job; finish needs a consumed stop, a settled native queue and
owner=agent; only a consumed stop rewrites queue.GOAT and clears BatchOnGoing; the
one successor is spent and publish_cancel returns it rather than resending it.

A new human grant is the only new authority in that state, so it admits exactly one
new identity, sha([attempt, 'cancel-successor-regrant', prior_issued_sha256, generation]).
The link is immutable and written before publication, so an interrupted publication can
only publish this same stop at this same generation. cancel_id resolves to the newest
link, which binds finish and every settled-gate check to the new stop. Every earlier
receipt is kept. Nothing here starts work, edits the native queue or changes a flag:
the EA stays the only writer of those, with its own demo and owner checks unchanged.
"""
import hashlib
import json
from pathlib import Path
import re
import time

from campaign_ledger import packed, sha
from studio_bridge import write_json
from studio_dispatch_observe import observe_dispatch
from studio_handover import safe_path
from studio_installation import read_json
from studio_native_gate import GateBusy, exclusive_gate
from studio_receipt_digest import receipt_views
from studio_refusal import Refusal

ACTIVE = frozenset(('starting', 'running', 'reconcile_required', 'verifying'))
TERMINAL = frozenset(('completed', 'cancelled', 'failed'))
CONSUMED_RECEIPTS = frozenset(('CANCELLED_RECONCILE', 'CANCEL_SIGNAL_SENT_RECONCILE'))
# The only answers that prove the EA refused the prior stop before its consumption
# claim for a reason a new grant can change. Any other answer stays refused.
REPLACEABLE_RECEIPTS = frozenset(('CANCEL_REJECTED', 'CANCEL_CONTROL_REVOKED'))
NATIVE_GATE_WAIT_SECONDS = 15   # the EA holds this gate for its bounded 10 s stop confirmation
NOTHING_SENT = ' Nothing was sent.'


def _refuse(code, message, **fields):
    raise Refusal(message + NOTHING_SENT, code, **fields)


def _link_path(root, attempt, generation):
    return safe_path(Path(root) / 'cancel-successors' / (attempt + '.regrant-' + str(generation) + '.json'))


def _links(root, attempt):
    folder = safe_path(Path(root) / 'cancel-successors')
    found = []
    for path in folder.glob(attempt + '.regrant-*.json'):
        match = re.fullmatch(re.escape(attempt) + r'\.regrant-([1-9][0-9]{0,11})\.json', path.name)
        value = read_json(safe_path(path))
        if match is None or value.get('generation') != int(match[1]):
            raise ValueError('Cancellation re-grant link changed')
        found.append(value)
    return sorted(found, key=lambda value: value['generation'])


def _digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def chain(root, gate, successor):
    """(verified links oldest first, the newest stop actually issued). Read-only.

    A link that was never published (interrupted, then a later grant) stays on disk
    and can never publish: only the newest link is current, and publication needs
    its generation (require_current_generation). A later link starts from the newest
    stop that really was issued.
    """
    gate = Path(gate)
    attempt = successor['attempt_id']
    links = _links(root, attempt)
    latest = successor['request_id']
    for value in links:
        generation = value['generation']
        if (value.get('schema_version') != 1 or value.get('prior_request_id') != latest
                or any(value.get(key) != successor[key] for key in ('attempt_id', 'job_id', 'configuration_sha256',
                                                                    'terminal_id', 'run_id'))
                or value.get('request_id') != sha([attempt, 'cancel-successor-regrant', value.get('prior_issued_sha256'), generation])
                or _digest(gate / ('issued-' + latest + '.json')) != value['prior_issued_sha256']):
            raise ValueError('Cancellation re-grant identity changed')
        recorded = value.get('prior_result_sha256')
        if recorded is not None and _digest(gate / ('result-' + latest + '.json')) != recorded:
            raise ValueError('Immutable prior cancellation evidence changed')
        request = read_json(gate / ('issued-' + latest + '.json'))['request']
        if (observe_dispatch(gate, latest).get('consumed') is not False or request.get('action') != 'cancel'
                or request.get('attempt_id') != attempt or request.get('job_id') != value['job_id']
                or request['generation'] >= generation or request['expires_utc'] >= value['created_utc']):
            raise ValueError('Exact expired unconsumed prior stop required')
        if (gate / ('issued-' + value['request_id'] + '.json')).exists():
            latest = value['request_id']
    return links, latest


def current_stop(root, gate, successor):
    """The stop identity cancel_id answers once a successor exists."""
    links, _ = chain(root, gate, successor)
    return links[-1]['request_id'] if links else successor['request_id']


def require_current_generation(root, job, request_id, state):
    """An unpublished re-grant stop belongs to its own grant: never publish it under a later one."""
    attempt = job['launch_intent']['attempt_id']
    if not (Path(root) / 'cancel-successors' / (attempt + '.json')).exists():
        return
    for value in _links(root, attempt):
        if value['request_id'] == request_id and value['generation'] != state['generation']:
            _refuse('REGRANT_GENERATION_CHANGED', 'This stop was admitted for an earlier human grant; run cancel-regrant '
                    'again so this grant is checked.', generation=state['generation'], link_generation=value['generation'])


def _archived_grant(controller, state):
    """The one human GIVE TO AGENT that created this generation, proven from its receipt and archive."""
    binding = packed(dict(terminal_id=controller.terminal, run_id=controller.run))
    archive = safe_path(controller.local / controller.session['directory_id'] / 'human/archive')
    found = []
    for request_id, payload_hash, receipt in receipt_views(controller.store.db, binding):
        view = receipt.get('state', {})
        if (receipt.get('command') != 'control.grant_agent' or receipt.get('status') != 'applied'
                or receipt.get('execution_effect') is not False or view.get('owner') != 'agent'
                or view.get('generation') != state['generation']):
            continue
        files = list(archive.glob(request_id + '.*.json')) if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id) else []
        if len(files) != 1:
            _refuse('REGRANT_NO_ARCHIVED_GRANT', 'The grant that created this generation has no archived human request.')
        request = read_json(safe_path(files[0]))
        if (request.get('command') != 'control.grant_agent' or request.get('payload') != {}
                or request.get('generation') != state['generation'] - 1 or request.get('request_id') != request_id
                or {key: request.get(key) for key in ('terminal_id', 'run_id')} != dict(terminal_id=controller.terminal, run_id=controller.run)
                or sha(dict(request=request, actor='human')) != payload_hash):
            _refuse('REGRANT_NO_ARCHIVED_GRANT', 'The archived grant differs from its receipt or did not come from the human channel.')
        found.append(dict(request_id=request_id, payload_hash=payload_hash, request_sha256=_digest(files[0])))
    if len(found) != 1:
        _refuse('REGRANT_NO_ARCHIVED_GRANT', 'Exactly one human GIVE TO AGENT must have created this generation.')
    return found[0]


def _native_hashes(controller, job, prior):
    from studio_native_request import ini_sections
    from studio_terminal_isolation import controller_base
    base = controller_base(controller)
    try:
        owner_raw = (base / 'agent-native-control-owner.json').read_bytes()
        pointer_raw = (base / 'active_optimization_run.ini').read_bytes()
        owner = json.loads(owner_raw.decode('utf-8'))
        manifest = json.loads((Path(job['launch_intent']['package']) / 'manifest.json').read_text(encoding='utf-8'))
        pointer = ini_sections(pointer_raw)
    except (OSError, ValueError) as error:
        _refuse('REGRANT_NATIVE_OWNER_CHANGED', 'Native control files could not be read: ' + str(error)[:200] + '.')
    owner_hash, pointer_hash = hashlib.sha256(owner_raw).hexdigest(), hashlib.sha256(pointer_raw).hexdigest()
    if owner.get('owner') != job['launch_intent']['attempt_id'] or owner_hash != prior.get('native_owner_sha256'):
        _refuse('REGRANT_NATIVE_OWNER_CHANGED', 'The native owner file differs from the one the prior stop was issued against.')
    if (pointer_hash != prior.get('pointer_sha256') or manifest['native_run_relative'] != prior.get('native_run')
            or pointer != {'ActiveOptimizationRun': {'RunPath': manifest['native_run_relative']}}):
        _refuse('REGRANT_POINTER_CHANGED', 'The native run pointer differs from the one the prior stop was issued against.')
    return dict(native_owner_sha256=owner_hash, pointer_sha256=pointer_hash)


def _runtime(controller, state):
    """A fresh bound EA sample: this terminal, demo, Algo off, tester idle, the grant seen."""
    from studio_resilient_read import read_observation
    try:
        observation, _ = read_observation(controller.local / 'ui-observation.json')
        batch_ongoing = observation['runtime']['batch_ongoing']
    except (OSError, ValueError, KeyError, TypeError) as error:
        _refuse('REGRANT_RUNTIME_NOT_VERIFIED', 'No readable EA runtime sample: ' + str(error)[:200] + '.')
    if type(batch_ongoing) is not bool:
        _refuse('REGRANT_RUNTIME_NOT_VERIFIED', 'The EA runtime sample has no BatchOnGoing value.')
    try:
        # BatchOnGoing is what the stop clears, so either value is a fact here, not a precondition.
        controller.runtime(require_idle=True, expected_batch_ongoing=batch_ongoing)
    except (OSError, ValueError, KeyError, TypeError) as error:
        text = str(error)
        if 'Tester idleness' in text:
            _refuse('REGRANT_TESTER_NOT_IDLE', text + '.')
        if 'account_demo' in text:
            _refuse('REGRANT_BROKER_NOT_DEMO', 'The EA reports this account is not a demo account.')
        _refuse('REGRANT_RUNTIME_NOT_VERIFIED', text[:200] + '.')
    if observation.get('owner') != 'agent' or observation.get('generation') != state['generation']:
        _refuse('REGRANT_GRANT_NOT_OBSERVED', 'The EA has not reported this grant yet; keep serve running and retry.')
    return batch_ongoing


def _broker(controller):
    """Broker-side proof of the same connected demo, flat with Algo off; tester caption advisory to the EA sample."""
    from studio_monitor_probe import inspect_idle_demo
    try:
        native = inspect_idle_demo(controller, tester='advisory')
    except Refusal:
        raise
    except (OSError, ValueError) as error:
        code = 'REGRANT_TESTER_NOT_IDLE' if 'Tester is running' in str(error) else 'REGRANT_BROKER_NOT_DEMO'
        _refuse(code, str(error)[:200] + '.')
    if (any(native.get(key) != value for key, value in dict(demo=True, connected=True, algo_trading=False, positions=0,
                                                            orders=0, account_matches=True).items())
            or native.get('tester_state') not in ('idle', 'unknown')):
        _refuse('REGRANT_BROKER_NOT_DEMO', 'A broker-verified connected demo, Algo off and no trades are required.')
    return native


def admit(controller, job, state, *, now):
    """Every clause, under the native gate. Returns the link to use; refuses with a reason code."""
    session = controller.session
    if session.get('authority_kind') != 'demo_direct' or session.get('demo_only') is not True:
        _refuse('REGRANT_NOT_DEMO_LANE', 'A cancellation re-grant exists only on the broker-verified demo lane.')
    intent = job.get('launch_intent') or {}
    attempt = intent.get('attempt_id')
    if job.get('status') not in ACTIVE or not isinstance(attempt, str) or sha(job['configuration']) != job['configuration_sha256']:
        _refuse('REGRANT_JOB_NOT_ACTIVE', 'Batch ' + job['job_id'] + ' has no unresolved native attempt.')
    if state['owner'] != 'agent':
        _refuse('REGRANT_OWNER_NOT_AGENT', 'The human owns this terminal; ask them to click GIVE TO AGENT first.')
    root, gate = controller.root, controller.local / 'native-gate'
    successor_path = safe_path(Path(root) / 'cancel-successors' / (attempt + '.json'))
    if not successor_path.exists():
        _refuse('REGRANT_NO_PRIOR_SUCCESSOR', 'A re-grant only follows one issued cancellation successor.')
    from studio_cancel_successor import cancel_id
    try:
        cancel_id(root, job, gate)
        successor = read_json(successor_path)
        links, latest = chain(root, gate, successor)
        dispatch = observe_dispatch(gate, latest)
        prior = None if dispatch['status'] == 'not_issued' else read_json(gate / ('issued-' + latest + '.json'))['request']
    except (OSError, ValueError, KeyError, TypeError) as error:
        code = 'REGRANT_PRIOR_STOP_CONSUMED' if 'unconsumed prior stop' in str(error) else 'REGRANT_STOP_IDENTITY_CHANGED'
        _refuse(code, 'The prior stop evidence does not verify: ' + str(error)[:200] + '.')
    if prior is None:
        _refuse('REGRANT_NO_PRIOR_SUCCESSOR', 'The cancellation successor was never published; ordinary cancel publishes it.')
    retained = links[-1] if links and links[-1]['generation'] == state['generation'] else None
    if retained is not None and (gate / ('issued-' + retained['request_id'] + '.json')).exists():
        _refuse('REGRANT_ALREADY_ISSUED', 'This human grant already issued its one stop; run cancel-regrant --settle.',
                request_id=retained['request_id'], generation=state['generation'])
    if links and links[-1]['generation'] > state['generation']:
        _refuse('REGRANT_STOP_IDENTITY_CHANGED', 'A re-grant link is ahead of this controller generation.')
    if state['generation'] <= prior['generation']:
        _refuse('REGRANT_SAME_GENERATION', 'A new human TAKE CONTROL and GIVE TO AGENT must follow the prior stop.',
                generation=state['generation'], prior_generation=prior['generation'])
    if prior.get('job_id') != job['job_id'] or prior.get('attempt_id') != attempt or prior.get('configuration_sha256') != job['configuration_sha256']:
        _refuse('REGRANT_STOP_IDENTITY_CHANGED', 'The prior stop belongs to another attempt.')
    if dispatch.get('consumed') is not False:
        _refuse('REGRANT_PRIOR_STOP_CONSUMED', 'MT5 consumed the prior stop; run batch-status and finish it instead.', request_id=latest)
    if prior['expires_utc'] >= now:
        _refuse('REGRANT_PRIOR_STOP_LIVE', 'The prior stop can still be consumed; wait for it to expire.',
                request_id=latest, expires_utc=prior['expires_utc'])
    # With no receipt the expired stop stays unanswered for good: every controller commit, including
    # the grant itself, revokes its permit, and the EA refuses it on expiry anyway.
    if dispatch['status'] == 'receipt_observed' and dispatch['receipt']['status'] not in REPLACEABLE_RECEIPTS:
        _refuse('REGRANT_PRIOR_RECEIPT_NOT_RECOVERABLE', 'MT5 answered the prior stop with ' + dispatch['receipt']['status']
                + ', which a new grant cannot change.', request_id=latest)
    grant = _archived_grant(controller, state)
    hashes = _native_hashes(controller, job, prior)
    batch_ongoing = _runtime(controller, state)
    native = _broker(controller)
    if retained is not None:
        return retained
    issued_hash = _digest(gate / ('issued-' + latest + '.json'))
    result_path = gate / ('result-' + latest + '.json')
    return dict(schema_version=1, attempt_id=attempt, job_id=job['job_id'], configuration_sha256=job['configuration_sha256'],
                terminal_id=controller.terminal, run_id=controller.run, generation=state['generation'],
                prior_request_id=latest, prior_issued_sha256=issued_hash, prior_generation=prior['generation'],
                prior_result_sha256=_digest(result_path) if result_path.exists() else None,
                request_id=sha([attempt, 'cancel-successor-regrant', issued_hash, state['generation']]),
                grant=grant, native=dict(hashes, batch_ongoing=batch_ongoing, process=native.get('process'),
                                         tester_state=native.get('tester_state'), demo=True),
                created_utc=now)


def _read(controller, job_id):
    """(job, state). Inside the demo scope any read while the human owns the terminal refuses; name that."""
    try:
        return controller.job(job_id), controller.state()
    except ValueError as error:
        if 'TAKE CONTROL' in str(error):
            _refuse('REGRANT_OWNER_NOT_AGENT', 'The human owns this terminal; ask them to click GIVE TO AGENT first.')
        raise


def _journal(controller, job_id):
    path = safe_path(Path(controller.root) / 'batch-drivers' / (job_id + '.json'))
    return read_json(path) if path.is_file() else None


def publish(controller, job_id, *, now=None):
    """Admit and publish this grant's one stop, atomically against the EA and other controller commits."""
    from studio_batch_pause import PauseRefused, public, regrant_published, rearm_for_regrant
    from studio_cancel import issue_stop
    from studio_cancel_successor import cancel_id
    now = time.time() if now is None else now
    gate = controller.local / 'native-gate'
    driver_gate = safe_path(Path(controller.root) / 'batch-driver-gate')
    driver_gate.mkdir(exist_ok=True)
    try:
        # A live driver holds this gate for its whole run; it must end before a new epoch takes the batch.
        with exclusive_gate(driver_gate):
            with exclusive_gate(gate, wait_seconds=NATIVE_GATE_WAIT_SECONDS):
                job, state = _read(controller, job_id)
                link = admit(controller, job, state, now=now)
                try:
                    # Durable before any native effect; a pause that cannot re-arm refuses here.
                    record = rearm_for_regrant(controller.root, job, _journal(controller, job_id), now=now,
                                               generation=state['generation'], request_id=link['request_id'])
                except PauseRefused as error:
                    _refuse('REGRANT_PAUSE_NOT_REARMABLE', str(error))
                target = _link_path(controller.root, link['attempt_id'], link['generation'])
                if not target.exists():
                    write_json(target, link)
                # No stale permit can answer the prior stop once its link is on disk.
                (gate / 'permit.json').unlink(missing_ok=True)
                if cancel_id(controller.root, job, gate) != link['request_id']:
                    raise ValueError('Cancellation re-grant link did not become the current stop')
                result = issue_stop(controller, job, link['request_id'], state, gate)
                issued = read_json(gate / ('issued-' + link['request_id'] + '.json'))
                record = regrant_published(controller.root, job_id, link['request_id'], issued, now=now)
    except GateBusy as error:
        _refuse('REGRANT_BATCH_BUSY', 'Another GOAT process holds this batch: ' + str(error)[:200] + '.')
    return dict(result, status='regrant_published_not_confirmed', batch_id=job_id, generation=state['generation'],
                prior_request_id=link['prior_request_id'], pause=public(record),
                next_action='Keep the monitor reporting, then run cancel-regrant --settle until the batch is paused or finished.')


def _record_journal(controller, job_id, result):
    """Close the old epoch's driver journal the way its own finish would have. Its binding stays as written."""
    from studio_batch_driver import _save
    path = safe_path(Path(controller.root) / 'batch-drivers' / (job_id + '.json'))
    if not path.is_file():
        return
    record = read_json(path)
    if record.get('attempt_id') != result.get('attempt_id') or record.get('stopped') is True:
        return
    record.update(status=result['status'], stopped=True, last_error=None, settled_by='cancel_regrant',
                  result_path=result.get('result_path'))
    _save(path, record, time)


def settle(controller, job_id, *, now=None, monitor):
    """Observe this grant's stop; once consumed, finish the batch and complete its pause. Publishes nothing."""
    driver_gate = safe_path(Path(controller.root) / 'batch-driver-gate')
    driver_gate.mkdir(exist_ok=True)
    try:
        with exclusive_gate(driver_gate):
            return _settle(controller, job_id, now=time.time() if now is None else now, monitor=monitor)
    except GateBusy as error:
        _refuse('REGRANT_BATCH_BUSY', 'Another GOAT process holds this batch: ' + str(error)[:200] + '.')


def _settle(controller, job_id, *, now, monitor):
    from studio_batch_pause import complete, public, step
    from studio_cancel_successor import cancel_id
    from studio_finish import finish
    job, state = _read(controller, job_id)
    attempt = (job.get('launch_intent') or {}).get('attempt_id')
    gate = controller.local / 'native-gate'
    links = _links(controller.root, attempt) if isinstance(attempt, str) else []
    if not links or cancel_id(controller.root, job, gate) != links[-1]['request_id']:
        _refuse('REGRANT_NOT_PUBLISHED', 'No re-grant stop exists for batch ' + job_id + '.')
    request_id = links[-1]['request_id']
    dispatch = observe_dispatch(gate, request_id)
    if dispatch['status'] == 'not_issued':
        _refuse('REGRANT_NOT_PUBLISHED', 'This re-grant stop was never published; run cancel-regrant without --settle.')
    if state['owner'] != 'agent':
        _refuse('REGRANT_OWNER_NOT_AGENT', 'The human owns this terminal; ask them to click GIVE TO AGENT first.')
    summary = dict(batch_id=job_id, request_id=request_id, dispatch=dispatch)
    if job['status'] not in TERMINAL:
        record = step(controller, job_id, now=now, monitor=monitor)
        if record['state'] == 'pause_failed':
            return dict(summary, status='pause_failed', pause=public(record),
                        next_action='Nothing was replayed. Another stop needs a new human TAKE CONTROL and GIVE TO AGENT.')
        if dispatch.get('consumed') is not True or dispatch.get('receipt', {}).get('status') not in CONSUMED_RECEIPTS:
            return dict(summary, status='regrant_waiting', pause=public(record),
                        next_action='Keep the monitor reporting and run cancel-regrant --settle again; nothing was replayed.')
    try:
        finished = finish(controller, job_id, expected_generation=state['generation'])
    except (ValueError, GateBusy) as error:
        record = step(controller, job_id, now=now, monitor=monitor, finish_error=str(error))
        return dict(summary, status='finish_waiting', error=str(error)[:240], pause=public(record),
                    next_action='MT5 took the stop; keep the monitor reporting and run cancel-regrant --settle again.')
    record = complete(controller, job_id, now=now)
    _record_journal(controller, job_id, dict(finished.get('result') or {}, status=finished['status'],
                                             result_path=finished.get('result_path')))
    return dict(summary, status=record['state'], batch_status=finished['status'], result_path=finished.get('result_path'),
                pause=public(record),
                next_action='Finished members and their results are kept; batch-resume continues the unfinished members.')
