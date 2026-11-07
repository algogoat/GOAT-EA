"""One more stop identity per recorded human re-grant of a stranded demo batch.

The deadlock (a reboot, a rejected cancel, one successor, then TAKE CONTROL): only
finish settles the job; finish needs a consumed stop, a settled native queue and
owner=agent; only a consumed stop rewrites queue.GOAT and clears BatchOnGoing; the
one successor is spent and publish_cancel returns it rather than resending it.

A new grant in the human channel is the only new authority in that state, so it admits
exactly one new identity, sha([attempt, 'cancel-successor-regrant', prior_issued_sha256,
generation]). The link is immutable and written before publication, so an interrupted
publication can only publish this same stop at this same generation, through cancel-regrant. cancel_id resolves
to the newest link, which binds finish and every settled-gate check to the new stop.
Every earlier receipt is kept. Nothing here starts work, edits the native queue or changes
a flag: the EA stays the only writer of those, with its own demo and owner checks unchanged.

Boundary: "human" means the request arrived through the human/ bridge folder, so its
receipt says actor=human and a matching file sits in human/archive. Nothing signs it. This
tells the agent channel from the human channel between cooperating local tools; it does not
prove a person clicked, and a same-user process writing into that folder is out of scope.

A consumed stop cannot be replaced, so every refusal finish would give after it that can be
read beforehand is checked before publication (_finish_preflight), with the same report gate.

Two lanes, both demo-only: the owner demo lane (goat.exe demo cancel-regrant) and the customer lane
(goat.exe studio cancel-regrant, studio_entry). admit() proves demo the same way on both, from the
EA sample (_runtime) and from the broker itself (_broker). The EA side is the same on V1.48 and
V1.49: both consume a valid stop with the same receipts; only the batch base folder differs, and
controller_base resolves it per version (V1.48 GOAT V1.48-<server>, V1.49 per terminal and login).
"""
import configparser
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
# The stop's queue rewrite truncates before it writes (Optimizer.mqh ReconstructFile), and finish then writes its result. This
# floor is well above what those need and far below a driver's disk guard, so a batch stopping for low disk can still stop.
MIN_PUBLISH_FREE_BYTES = 256 * 1024**2
NATIVE_GATE_WAIT_SECONDS = 15   # the EA holds this gate for its bounded 10 s stop confirmation
NOTHING_SENT = ' Nothing was sent.'
LANES = frozenset(('demo_direct', 'native_human_control'))
# A file cut by a reboot mid-write fails to parse (configparser.Error is not a ValueError); it is evidence, not a crash.
READ_ERRORS = (OSError, ValueError, KeyError, TypeError, configparser.Error)
ESCALATE = (' Escalate it as a GOAT support report: support.prepareReport with category studio, this code in errorCodes and '
            'this whole reply as actual; show the user the preview, then support.submitReport after their yes.')


def _refuse(code, message, **fields):
    raise Refusal(message + NOTHING_SENT, code, **fields)


def _escalation(code):
    """Where a dead end goes: GOAT support, with this exact reply (GOAT-OPERATING-MODEL.md, "Support report")."""
    return dict(escalate_to=dict(route='support.prepareReport', category='studio', errorCodes=[code],
                                 include='this whole reply, unedited, as actual',
                                 send='support.submitReport, only after the user approved the preview'))


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
    and can never publish under a later grant: only the newest link is current, and
    admission needs its generation. A later link starts from the newest stop that
    really was issued.
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


def require_admission(root, job, request_id):
    """Ordinary cancel never publishes an unissued re-grant stop: only cancel-regrant runs its admission and pre-check."""
    attempt = job['launch_intent']['attempt_id']
    if not (Path(root) / 'cancel-successors' / (attempt + '.json')).exists():
        return
    if any(value['request_id'] == request_id for value in _links(root, attempt)):
        _refuse('REGRANT_LINK_NEEDS_ADMISSION', 'This stop was interrupted before it was published. Only cancel-regrant may '
                'publish a re-grant stop, after checking it again.', request_id=request_id)


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
    except (OSError, ValueError, configparser.Error) as error:
        _refuse('REGRANT_NATIVE_OWNER_CHANGED', 'Native control files could not be read: ' + str(error)[:200] + '.')
    owner_hash, pointer_hash = hashlib.sha256(owner_raw).hexdigest(), hashlib.sha256(pointer_raw).hexdigest()
    if owner.get('owner') != job['launch_intent']['attempt_id'] or owner_hash != prior.get('native_owner_sha256'):
        _refuse('REGRANT_NATIVE_OWNER_CHANGED', 'The native owner file differs from the one the prior stop was issued against.')
    if (pointer_hash != prior.get('pointer_sha256') or manifest['native_run_relative'] != prior.get('native_run')
            or pointer != {'ActiveOptimizationRun': {'RunPath': manifest['native_run_relative']}}):
        _refuse('REGRANT_POINTER_CHANGED', 'The native run pointer differs from the one the prior stop was issued against.')
    return dict(native_owner_sha256=owner_hash, pointer_sha256=pointer_hash)


def _owned(controller, job, journal):
    """The driver's _owned_attempt with one difference: the generation moved, by design, to this grant."""
    from studio_batch_driver import _binding
    intent = job['launch_intent']
    try:
        current = _binding(controller, job['job_id'])
        bound = journal['binding']
        same = ({key: value for key, value in current.items() if key != 'generation'}
                == {key: value for key, value in bound.items() if key != 'generation'}
                and intent.get('attempt_id') == journal.get('attempt_id')
                and intent.get('package_sha256') == bound['package_sha256']
                and str(Path(intent.get('package', '')).resolve()) == bound['package'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        _refuse('REGRANT_ATTEMPT_CHANGED', 'The batch no longer matches its driver journal: ' + str(error)[:200] + '.')
    if not same:
        _refuse('REGRANT_ATTEMPT_CHANGED', 'The batch, session or package no longer matches its driver journal.')


def _finish_preflight(controller, job):
    """What finish would refuse after the stop, read now while nothing has changed.

    The stop rewrites only Pending, Queued and OnGoing rows to Cancelled: Completed and Error rows stay as they
    are, so this is finish's own report gate on the queue as it will be. No rewrite can produce a missing report.
    """
    from native_control_transaction import restorable
    from studio_finish import member_reports, reports_verified
    from studio_native_gate import _read_gate_evidence
    from studio_native_observe import observe
    from studio_report_bridge import check_retirable
    intent = job['launch_intent']
    package = Path(intent['package'])
    evidence = Path(controller.root) / 'attempts' / intent['attempt_id']
    try:
        native = observe(package)
        if native.get('status') == 'native_evidence_missing':
            _refuse('REGRANT_FINISH_WOULD_REFUSE', 'The native queue is missing, so finish could never settle this batch.')
        read_json(Path(controller.root) / 'packages' / (job['job_id'] + '.source.json'))
        transaction = read_json(evidence / 'transaction.json')
        if transaction['owner'] != intent['attempt_id']:
            _refuse('REGRANT_FINISH_WOULD_REFUSE', 'The native control transaction belongs to another attempt.')
        if transaction['phase'] != 'restored':
            restorable(evidence)
        bridge = (job.get('restart_intent') or {}).get('report_bridge')
        if bridge is not None:
            plan, manifest = read_json(package / 'studio-plan.json'), _read_gate_evidence(package / 'manifest.json')[1]
            if read_json(evidence / 'report-bridge.json') != bridge or sha(plan) != manifest['campaign_id']:
                _refuse('REGRANT_FINISH_WOULD_REFUSE', 'The report bridge evidence changed, so finish would refuse this batch.')
            check_retirable(plan['research_binding'], manifest['native_run_relative'], bridge, evidence)
        after_stop = ['native_cancelled' if member['status'] in ('native_pending', 'native_queued', 'native_ongoing')
                      else member['status'] for member in native['members']]
        reports = member_reports(controller, job, package, after_stop)
    except Refusal:
        raise
    except READ_ERRORS as error:
        _refuse('REGRANT_FINISH_WOULD_REFUSE', 'Finish would refuse this batch: ' + str(error)[:200] + '.')
    if not reports_verified(reports):
        rows = reports.get('members') or [reports]
        unverified = [dict(index=row.get('index'), symbol=row.get('symbol'), status=row['status'], missing=row.get('missing'),
                           reason=row.get('reason')) for row in rows
                      if row['status'] not in ('report_pair_verified', 'member_not_completed')]
        if all(row['status'] == 'reports_changing' for row in unverified):
            _refuse('REGRANT_REPORTS_NOT_VERIFIED', 'A completed member\'s report is still being written; retry.', members=unverified)
        # The tester is already proven idle here, so nothing is still migrating these reports.
        _refuse('REGRANT_ESCALATE_REPORTS_LOST', 'A completed member has no verified report pair and the tester is idle, so '
                'nothing is still writing it. Finish would refuse this batch for good once the stop is consumed, so no stop was '
                'sent and no command settles this batch. Keep every file; restoring the exact report pair lets cancel-regrant '
                'run again.' + ESCALATE, members=unverified, **_escalation('REGRANT_ESCALATE_REPORTS_LOST'))


def _disk_reading(disk):
    return ', '.join(item['role'] + (' unavailable' if item['free_bytes'] is None else ' ' + format(item['free_bytes'] / 1024**3, '.1f') + ' GB free')
                     for item in disk['volumes'])


def _disk_gate(controller):
    """Free space for the EA's queue rewrite and finish's result, read before anything changes."""
    from studio_batch_driver import _capacity
    disk = _capacity(controller, MIN_PUBLISH_FREE_BYTES)
    if disk['reason'] == 'disk_probe_unavailable':
        reading = _disk_reading(disk)
        _refuse('REGRANT_DISK_UNREADABLE', 'A stop rewrites the native queue by truncating it first, so every volume it writes '
                'must be readable and have room; found ' + reading + '.', disk_observation=disk,
                next_action='Reconnect or repair the unavailable volume (' + reading + '), then run cancel-regrant again.')
    if disk['reason']:
        reading = _disk_reading(disk)
        _refuse('REGRANT_DISK_TOO_LOW', 'A stop rewrites the native queue by truncating it first, so a full disk could lose it. '
                'Needs ' + str(MIN_PUBLISH_FREE_BYTES // 1024**2) + ' MB free on every volume; found ' + reading + '.',
                disk_observation=disk, next_action='Free disk space (' + reading + '), then run cancel-regrant again.')
    return disk


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
            _refuse('REGRANT_BROKER_NOT_IDLE_DEMO', 'The EA reports this account is not a demo account.')
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
        code = 'REGRANT_TESTER_NOT_IDLE' if 'Tester is running' in str(error) else 'REGRANT_BROKER_NOT_IDLE_DEMO'
        _refuse(code, str(error)[:200] + '.')
    if (any(native.get(key) != value for key, value in dict(demo=True, connected=True, algo_trading=False, positions=0,
                                                            orders=0, account_matches=True).items())
            or native.get('tester_state') not in ('idle', 'unknown')):
        _refuse('REGRANT_BROKER_NOT_IDLE_DEMO', 'A broker-verified connected demo, Algo off and no trades are required.')
    return native


def _delivered(gate, request_id, dispatch):
    """Whether MT5 can still see this stop: its exact request bytes and a permit for them are in place."""
    try:
        digest = dispatch['request_sha256']
        return (_digest(gate / 'request.json') == digest and read_json(gate / 'permit.json').get('request_sha256') == digest)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _refuse_undelivered(gate, request_id, dispatch):
    """A stop written but never handed to MT5 (crash mid-publication, or a later commit revoked its permit) never gets an answer."""
    if dispatch.get('status') == 'awaiting_receipt' and dispatch.get('consumed') is False and not _delivered(gate, request_id, dispatch):
        expires = read_json(gate / ('issued-' + request_id + '.json'))['request']['expires_utc']
        raise Refusal('This stop was written but never reached MT5, and MT5 will never answer it. It is not resent. Next: once it '
                      'expires, ask the user to TAKE CONTROL and GIVE TO AGENT, then run cancel-regrant, which publishes one '
                      'stop for that grant.', 'REGRANT_STOP_UNDELIVERED', request_id=request_id, expires_utc=expires)


def _escalate_claim(controller, job, request_id, dispatch):
    """MT5 claimed this stop and no receipt says it took effect. Call under the native gate, which MT5 holds from its
    claim to its receipt, so a claim seen here is not one still in progress.

    A reboot between the two leaves this. MT5's retry answers CANCEL_REJECTED or CANCEL_ALREADY_CONSUMED, or never answers
    if the permit is gone. Its flags and queue may be unchanged, partly changed or fully changed. Finish rightly refuses it,
    and a new stop could double-apply, so this is the end of what the controller can do by itself.
    """
    if dispatch.get('consumed') is not True or dispatch.get('receipt', {}).get('status') in CONSUMED_RECEIPTS:
        return
    from studio_native_observe import observe
    from studio_resilient_read import read_observation
    facts = dict(request_id=request_id, claimed=True, receipt=dispatch.get('receipt', {}).get('status'))
    try:
        facts['native_queue'] = observe(Path(job['launch_intent']['package'])).get('status_counts')
    except READ_ERRORS as error:
        facts['native_queue_error'] = str(error)[:200]
    try:
        runtime = read_observation(controller.local / 'ui-observation.json')[0]['runtime']
        facts.update(batch_ongoing=runtime.get('batch_ongoing'), tester_state=runtime.get('tester_state'))
    except READ_ERRORS as error:
        facts['runtime_error'] = str(error)[:200]
    raise Refusal('MT5 claimed this stop but no receipt says it took effect, as after a reboot between its claim and its '
                  'receipt. Its effect is unknown, finish will not accept it, and no new stop is allowed, so no command settles '
                  'this batch. Keep every file. Retrying changes nothing.' + ESCALATE,
                  'REGRANT_ESCALATE_CLAIM_WITHOUT_OUTCOME', **facts, **_escalation('REGRANT_ESCALATE_CLAIM_WITHOUT_OUTCOME'))


def admit(controller, job, state, *, now):
    """Every clause, under the native gate. Returns the link to use; refuses with a reason code."""
    session = controller.session
    if session.get('authority_kind') not in LANES or session.get('demo_only') is not True:
        _refuse('REGRANT_NOT_DEMO_LANE', 'A cancellation re-grant exists only on a demo-only lane: the owner demo lane or the '
                'customer lane.')
    intent = job.get('launch_intent') or {}
    attempt = intent.get('attempt_id')
    if job.get('status') not in ACTIVE or not isinstance(attempt, str):
        _refuse('REGRANT_JOB_NOT_ACTIVE', 'Batch ' + job['job_id'] + ' has no unresolved native attempt.')
    if sha(job['configuration']) != job['configuration_sha256']:
        _refuse('REGRANT_CONFIG_CHANGED', 'The frozen batch configuration changed.')
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
    _escalate_claim(controller, job, latest, dispatch)
    if dispatch.get('consumed') is not False:
        _refuse('REGRANT_PRIOR_STOP_CONSUMED', 'MT5 consumed the prior stop, so no new one is needed; run cancel-regrant --settle.', request_id=latest)
    retained = links[-1] if links and links[-1]['generation'] == state['generation'] else None
    if retained is not None and (gate / ('issued-' + retained['request_id'] + '.json')).exists():
        _refuse_undelivered(gate, retained['request_id'], dispatch)
        _refuse('REGRANT_ALREADY_ISSUED', 'This human grant already issued its one stop; run cancel-regrant --settle.',
                request_id=retained['request_id'], generation=state['generation'])
    if links and links[-1]['generation'] > state['generation']:
        _refuse('REGRANT_STOP_IDENTITY_CHANGED', 'A re-grant link is ahead of this controller generation.')
    if state['generation'] <= prior['generation']:
        _refuse('REGRANT_SAME_GENERATION', 'A new human TAKE CONTROL and GIVE TO AGENT must follow the prior stop.',
                generation=state['generation'], prior_generation=prior['generation'])
    if prior.get('job_id') != job['job_id'] or prior.get('attempt_id') != attempt or prior.get('configuration_sha256') != job['configuration_sha256']:
        _refuse('REGRANT_STOP_IDENTITY_CHANGED', 'The prior stop belongs to another attempt.')
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
    journal = _journal(controller, job['job_id'])
    if journal is None:
        _refuse('REGRANT_NO_DRIVER_JOURNAL', 'This batch has no driver journal to bind the re-grant to.')
    _owned(controller, job, journal)
    batch_ongoing = _runtime(controller, state)
    native = _broker(controller)
    _finish_preflight(controller, job)
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
                disk = _disk_gate(controller)
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
                prior_request_id=link['prior_request_id'], pause=public(record), disk_observation=disk,
                next_action='Keep the monitor reporting, then run cancel-regrant --settle until the batch is paused or finished. '
                            'Disk when sent: ' + _disk_reading(disk) + '.')


def studio_entry(controller, job_id, *, settle_stop=False, now=None):
    """goat.exe studio cancel-regrant: the customer lane's entry, with the owner verb's own pre-checks
    (DemoAgent.cancel_regrant), before admit() runs every clause and both demo proofs again.

    The account is not an Open Lab experiment login and no human request waits. The installed EA is the receipt's:
    loading the receipt hashes it for every studio command (studio_installation.load_installation). A live run-batch
    driver holds the driver gate for its whole run, so it refuses REGRANT_BATCH_BUSY here; the customer lane has no
    detached worker. Called under the terminal lease (goat_studio TERMINAL_LEASE_OPERATIONS), so no seed, catch-up or
    batch driver closes or relaunches MT5 meanwhile.
    """
    from studio_batch_pause import observe_monitor
    from studio_onboarding import OPEN_LAB_LOGINS
    session = controller.session
    if session.get('authority_kind') != 'native_human_control' or session.get('demo_only') is not True:
        _refuse('REGRANT_NOT_DEMO_LANE', 'goat.exe studio cancel-regrant is the customer lane\'s entry; on the owner demo lane '
                'use goat.exe demo cancel-regrant.')
    if str(session['account']['login']) in OPEN_LAB_LOGINS:
        _refuse('REGRANT_PROTECTED_ACCOUNT', 'This demo account belongs to a GOAT Open Lab experiment; agents never change it.')
    human = controller.bridge.root / 'human'
    if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
        _refuse('REGRANT_HUMAN_PENDING', 'A human TAKE CONTROL or GIVE TO AGENT has not been processed yet: keep the GOAT app '
                'open so serve processes it, and retry.')
    now = time.time() if now is None else now
    if settle_stop:
        return settle(controller, job_id, now=now, monitor=observe_monitor(controller, now))
    return publish(controller, job_id, now=now)


def _close_driver_journal(controller, job_id, result, pause, *, end_state_fn=None):
    """What the driver does after its verified finish: close its journal, then its one end state. Idempotent.

    Its binding stays as written. The end state leaves any MT5 this batch did not launch alone, which after a reboot
    is the usual answer; the result always says what happened.
    """
    from studio_batch_driver import DEFAULT_MIN_FREE_BYTES, _capacity, _end_state, _save
    path = safe_path(Path(controller.root) / 'batch-drivers' / (job_id + '.json'))
    record = read_json(path)
    if record.get('attempt_id') != result.get('attempt_id'):
        _refuse('REGRANT_ATTEMPT_CHANGED', 'The driver journal belongs to another attempt; it and MT5 were left as they are.')
    if record.get('stopped') is not True:
        record.update(status='paused' if pause['state'] == 'paused' else result['status'], pause_id=pause['pause_id'],
                      stopped=True, last_error=None, settled_by='cancel_regrant', result_path=result.get('result_path'),
                      disk_observation=_capacity(controller, record.get('min_free_bytes') or DEFAULT_MIN_FREE_BYTES))
        _save(path, record, time)
    _end_state(controller, job_id, record, path, time, end_state_fn)
    return record


def settle(controller, job_id, *, now=None, monitor, end_state_fn=None):
    """Observe this grant's stop, then do what the revoked driver would: reconcile, finish, complete the pause,
    close its journal, its one end state, the idle-point maintenance. Publishes nothing."""
    driver_gate = safe_path(Path(controller.root) / 'batch-driver-gate')
    driver_gate.mkdir(exist_ok=True)
    try:
        with exclusive_gate(driver_gate):
            return _settle(controller, job_id, now=time.time() if now is None else now, monitor=monitor, end_state_fn=end_state_fn)
    except GateBusy as error:
        _refuse('REGRANT_BATCH_BUSY', 'Another GOAT process holds this batch: ' + str(error)[:200] + '.')


def _settle(controller, job_id, *, now, monitor, end_state_fn):
    from studio_batch_pause import FINISH_PATIENCE_SECONDS, PauseRefused, complete, load, public, rearm_for_regrant, step
    from studio_cancel_successor import cancel_id
    from studio_db_maintenance import after_batch
    from studio_finish import finish
    job, state = _read(controller, job_id)
    attempt = (job.get('launch_intent') or {}).get('attempt_id')
    gate = controller.local / 'native-gate'
    has_successor = isinstance(attempt, str) and (Path(controller.root) / 'cancel-successors' / (attempt + '.json')).exists()
    if not has_successor:
        _refuse('REGRANT_NOT_PUBLISHED', 'No re-grant stop exists for batch ' + job_id + '.')
    links = _links(controller.root, attempt)
    request_id = cancel_id(controller.root, job, gate)
    with exclusive_gate(gate, wait_seconds=NATIVE_GATE_WAIT_SECONDS):
        dispatch = observe_dispatch(gate, request_id)
    if dispatch['status'] == 'not_issued':
        _refuse('REGRANT_NOT_PUBLISHED', 'This re-grant stop was never published; run cancel-regrant without --settle.')
    if job['status'] not in TERMINAL:
        _escalate_claim(controller, job, request_id, dispatch)
    # A successor MT5 consumed before the human took over needs no new stop, only this settlement.
    if not links and dispatch.get('consumed') is not True:
        _refuse('REGRANT_NOT_PUBLISHED', 'No re-grant stop exists for batch ' + job_id + '.')
    if state['owner'] != 'agent':
        _refuse('REGRANT_OWNER_NOT_AGENT', 'The human owns this terminal; ask them to click GIVE TO AGENT first.')
    summary = dict(batch_id=job_id, request_id=request_id, dispatch=dispatch)
    journal = _journal(controller, job_id)
    if journal is None:
        _refuse('REGRANT_NO_DRIVER_JOURNAL', 'This batch has no driver journal to bind the re-grant to.')
    if job['status'] not in TERMINAL:
        _owned(controller, job, journal)
        _refuse_undelivered(gate, request_id, dispatch)
        if not links and (load(controller.root, job_id) or {}).get('state') != 'pausing':
            try:
                rearm_for_regrant(controller.root, job, journal, now=now, generation=state['generation'], request_id=request_id)
            except PauseRefused as error:
                _refuse('REGRANT_PAUSE_NOT_REARMABLE', str(error))
        record = step(controller, job_id, now=now, monitor=monitor)
        if record['state'] == 'pause_failed':
            return dict(summary, status='pause_failed', pause=public(record),
                        next_action='Nothing was replayed. Another stop needs a new human TAKE CONTROL and GIVE TO AGENT.')
        if dispatch.get('consumed') is not True or dispatch.get('receipt', {}).get('status') not in CONSUMED_RECEIPTS:
            return dict(summary, status='regrant_waiting', pause=public(record), monitor_blocker=monitor.get('blocker'),
                        next_action='MT5 can still see this stop and has not answered. Keep the monitor reporting and run '
                                    'cancel-regrant --settle again; nothing was replayed.')
    try:
        if controller.job(job_id)['status'] not in TERMINAL:
            controller.reconcile(job_id)
        finished = finish(controller, job_id, expected_generation=state['generation'])
    except READ_ERRORS as error:
        record = step(controller, job_id, now=now, monitor=monitor, finish_error=str(error))
        waited = now - (record.get('finishing_since') or now)
        if waited > FINISH_PATIENCE_SECONDS:
            from studio_native_observe import observe
            try:
                queue = observe(Path(job['launch_intent']['package'])).get('status_counts')
            except READ_ERRORS as read_error:
                queue = 'unreadable: ' + str(read_error)[:200]
            raise Refusal('MT5 took this stop, which cannot be replaced, and finish has refused the batch for '
                          + str(round(waited)) + ' s: ' + str(error)[:240] + ' No command settles this batch. Keep every file; '
                          'run cancel-regrant --settle again only once the cause is fixed.' + ESCALATE,
                          'REGRANT_ESCALATE_FINISH_REFUSED', request_id=request_id, error=str(error)[:240], waited_seconds=round(waited),
                          receipt=dispatch.get('receipt', {}).get('status'), native_queue=queue,
                          **_escalation('REGRANT_ESCALATE_FINISH_REFUSED'))
        return dict(summary, status='finish_waiting', error=str(error)[:240], pause=public(record),
                    next_action='MT5 took the stop. Keep the monitor reporting and run cancel-regrant --settle again; after '
                                + str(FINISH_PATIENCE_SECONDS) + ' s this escalates as REGRANT_ESCALATE_FINISH_REFUSED.')
    record = complete(controller, job_id, now=now)
    journal = _close_driver_journal(controller, job_id, dict(finished.get('result') or {}, status=finished['status'],
                                                             result_path=finished.get('result_path')), record, end_state_fn=end_state_fn)
    after_batch(controller)
    end_state = journal.get('end_state') or dict(status='not_applicable', reason=journal.get('start_route'))
    next_action = 'Finished members and their results are kept; batch-resume continues the unfinished members.'
    if end_state.get('plain'):
        next_action = end_state['plain'] + ' ' + next_action
    return dict(summary, status=record['state'], batch_status=finished['status'], result_path=finished.get('result_path'),
                pause=public(record), end_state=end_state, disk_observation=journal.get('disk_observation'), next_action=next_action)
