"""Retire a start that was refused before MT5 was touched (never activated).

A config start records a reservation and a launch intent, and may record restart
phase ``prepared``, before it installs any native control. If it fails in that
window (g6-r1, 2026-10-03: "Process baseline is stale or future-dated") nothing
ever reached MT5, yet the job sits in ``starting``/``reconcile_required`` and every
other settlement refuses, so owner STOP can never be cleared.

``retire`` settles exactly that job to ``cancelled`` with a retained journal, and
only after proving under the native gate that the attempt never activated:

* restart phase is absent or ``prepared`` (no controls installed, no arm, no close);
* no ``attempts/<attempt>`` folder (activation creates it before any control file);
* no native-gate file names the attempt, its cancel identity or this job, and any
  current request/permit belongs to a different, settled job;
* this attempt owns no native control (``agent-native-control-owner.json``);
* no native run or report folder exists for any member, local, Common Files or
  the installation report alias;
* a fresh EA runtime sample shows the bound terminal idle with no batch ongoing.

It sends nothing to MT5, so it is allowed while owner STOP is set. It never claims
a native cancellation and never deletes evidence: the reservation, intent, restart
record and driver journal are kept. Repeating it returns the retained result.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from campaign_ledger import packed, sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json

KIND = 'retired_never_activated'
GATE_MARKER = re.compile(r'(issued|consumed|result|arm-intent|start-intent)-([a-f0-9]{64})\.json')
UNSETTLED = ('reserved', 'starting', 'reconcile_required')


def _refuse(sentence):
    raise ValueError(sentence)


def retained(c, job):
    """The earlier retirement of this exact job, or None."""
    completion = job.get('completion') or {}
    if job.get('status') == 'cancelled' and completion.get('kind') == KIND:
        return dict(status='cancelled', kind=KIND, batch_id=job['job_id'], reused=True,
                    attempt_id=completion.get('attempt_id'), result_path=job.get('completion_path'),
                    executed_members=0, native_cancellation_claimed=False)
    return None


def _cancel_identities(c, job, gate):
    from studio_cancel_successor import cancel_id
    attempt = job['launch_intent']['attempt_id']
    identities = {attempt, sha([attempt, 'cancel'])}
    try:
        identities.add(cancel_id(c.root, job, gate))
    except (OSError, ValueError, KeyError) as error:
        _refuse('A cancellation record exists for this attempt and cannot be read (' + str(error)[:120]
                + '); it may have reached MT5, so inspect it instead of retiring.')
    return identities


def _gate_proof(c, job, gate, identities):
    from studio_unissued_start import settled_other_request
    seen = []
    if not gate.is_dir():
        return dict(gate=str(gate), files=0, current_request=None)
    for item in sorted(gate.iterdir()):
        name = item.name
        if any(identity in name for identity in identities):
            _refuse('Native gate file ' + name + ' names this attempt, so it may have reached MT5; '
                    'inspect it instead of retiring.')
        marker = GATE_MARKER.fullmatch(name)
        if marker and marker[1] == 'issued':
            row = read_json(safe_path(item))
            request = row.get('request', row)
            if request.get('job_id') == job['job_id']:
                _refuse('A native request was issued for this batch (' + name + '); inspect it instead of retiring.')
        seen.append(name)
    current = None
    request_path, permit_path = gate / 'request.json', gate / 'permit.json'
    if request_path.exists() or request_path.is_symlink():
        request = read_json(safe_path(request_path))
        if (request.get('job_id') == job['job_id'] or request.get('request_id') in identities
                or request.get('attempt_id') in identities):
            _refuse('The current native request belongs to this batch; inspect it instead of retiring.')
        # Refuses unless it is the durable, consumed request of a different settled job.
        try:
            settled_other_request(c, gate, request['request_id'], job['job_id'])
        except (OSError, ValueError, KeyError, TypeError) as error:
            _refuse('The current native request ' + str(request.get('request_id'))[:16] + ' is not a settled request of '
                    'another batch (' + str(error)[:120] + '); settle that request first, then retry.')
        current = request['request_id']
    elif permit_path.exists() or permit_path.is_symlink():
        _refuse('A native permit exists without its request; inspect the native gate instead of retiring.')
    return dict(gate=str(gate), files=len(seen), current_request=current)


def _folder_proof(c, job, package, manifest, plan):
    from studio_report_paths import report_paths
    from studio_report_bridge import paths as bridge_paths
    attempt = job['launch_intent']['attempt_id']
    evidence = safe_path(c.root / 'attempts' / attempt)
    if evidence.exists() or evidence.is_symlink():
        _refuse('Activation evidence exists for this attempt (' + str(evidence) + '); it may have reached MT5, '
                'so use stop or reconcile instead.')
    relative = manifest['native_run_relative']
    roots = set()
    for index in range(len(manifest['jobs'])):
        found = report_paths(plan, manifest, index)
        roots.update((found['local_run'], found['common_run']))
    install_alias, _ = bridge_paths(plan['research_binding'], relative)
    roots.add(install_alias)
    for root in sorted(roots, key=str):
        if root.exists() or root.is_symlink():
            _refuse('A native run folder exists (' + str(root) + '); MT5 may have used it, so use stop or reconcile instead.')
    from studio_native_observe import observe
    native = observe(package)
    if native['status'] != 'native_evidence_missing':
        _refuse('The native queue exists for this batch (' + native['status'] + '); use stop or reconcile instead.')
    return dict(attempt_folder=False, run_folders_checked=len(roots), native_queue=native['status'])


def _control_proof(c, job):
    from studio_terminal_isolation import controller_base
    base = controller_base(c)
    marker = base / 'agent-native-control-owner.json'
    owner = None
    if marker.exists():
        owner = read_json(marker).get('owner')
        if owner == job['launch_intent']['attempt_id']:
            _refuse('This attempt owns the native controls; it reached MT5, so use stop or reconcile instead.')
    return dict(control_base=str(base), control_owner=owner)


def proof(c, job_id):
    """Read-only proof that this job's attempt never activated. Raises one plain sentence otherwise."""
    job = c.job(job_id)
    done = retained(c, job)
    if done is not None:
        return job, None
    if job['status'] not in UNSETTLED or 'launch_intent' not in job:
        _refuse('Batch ' + job_id + ' is ' + job['status'] + ' with no unactivated start to retire; '
                'research-status shows what it needs.')
    restart = job.get('restart_intent')
    if restart is not None and restart.get('phase') != 'prepared':
        _refuse('Batch ' + job_id + ' reached restart phase ' + str(restart.get('phase'))
                + ', so it may have touched MT5; use stop or reconcile instead.')
    intent, reservation = job['launch_intent'], job.get('reservation') or {}
    package = safe_path(c.root / 'packages' / job_id)
    digest = hashlib.sha256(safe_path(package / 'manifest.json').read_bytes()).hexdigest()
    attempt = intent.get('attempt_id', '')
    if (not re.fullmatch(r'[a-f0-9]{64}', attempt) or Path(intent['package']).resolve() != package.resolve()
            or intent.get('package_sha256') != digest or reservation.get('package_sha256') != digest
            or attempt != sha([reservation.get('reservation_id'), digest])
            or sha(job['configuration']) != job['configuration_sha256']):
        _refuse('The attempt, reservation or package identity of ' + job_id + ' changed; inspect it instead of retiring.')
    if restart is not None and restart.get('attempt_id') != attempt:
        _refuse('The restart record belongs to another attempt; inspect it instead of retiring.')
    # Batch manifests and plans use the 64 MiB batch bound (1122 members exceed 2 MB).
    from studio_batch import _json
    manifest = _json(safe_path(package / 'manifest.json'))
    plan = _json(safe_path(package / 'studio-plan.json'))
    if manifest.get('campaign_id') != sha(plan):
        _refuse('The prepared package of ' + job_id + ' changed; inspect it instead of retiring.')
    gate = safe_path(c.local / 'native-gate')
    identities = _cancel_identities(c, job, gate)
    evidence = dict(folders=_folder_proof(c, job, package, manifest, plan),
                    gate=_gate_proof(c, job, gate, identities),
                    controls=_control_proof(c, job))
    return job, evidence


def _runtime(c):
    try:
        observation, _ = c.runtime(require_idle=True, expected_batch_ongoing=False)
    except (ValueError, OSError, KeyError) as error:
        _refuse('The EA must report this terminal idle with no batch running before retiring (' + str(error)[:160]
                + '); open MT5 with the GOAT monitor and retry.')
    runtime = observation.get('runtime', {}) if isinstance(observation, dict) else {}
    return dict(tester_state=runtime.get('tester_state'), batch_ongoing=runtime.get('batch_ongoing'),
                account_demo=runtime.get('account_demo'), observed_terminal_utc=runtime.get('observed_terminal_utc'))


def _settle_journal(c, job_id, attempt, result_path, now):
    """Mark the retained driver journal stopped; it stays in place as evidence."""
    from studio_native_gate import exclusive_gate
    root = safe_path(c.root)
    path = safe_path(root / 'batch-drivers' / (job_id + '.json'))
    if not path.is_file():
        return None
    gate = safe_path(root / 'batch-driver-gate'); gate.mkdir(exist_ok=True)
    with exclusive_gate(gate):
        record = read_json(path)
        if record.get('binding', {}).get('job_id') != job_id or record.get('attempt_id') not in (None, attempt):
            return dict(journal=str(path), updated=False, reason='Journal belongs to another attempt')
        if record.get('stopped') is True and record.get('status') == 'cancelled':
            return dict(journal=str(path), updated=False, reason='already settled')
        archive = safe_path(root / 'batch-driver-refusals'); archive.mkdir(exist_ok=True)
        before = safe_path(archive / (job_id + '.before-retire-' + attempt[:16] + '.json'))
        if not before.exists():
            write_json(before, record)
        record.update(stopped=True, status='cancelled', retired=KIND, result_path=str(result_path),
                      retired_wall=now, last_error=record.get('last_error'))
        record['last_wall'] = max(record.get('last_wall', now), now)
        write_json(path, record)
        return dict(journal=str(path), updated=True, previous=str(before))


def retire(c, job_id, *, clock=None, reason='operator', settle_journal=True):
    """Settle a never-activated start to cancelled with a journal. Idempotent.

    ``settle_journal`` is False only for the driver itself, which holds the driver
    gate and records the same settlement in its own journal.
    """
    import time
    from studio_native_gate import exclusive_gate
    from studio_research_authority import authority
    clock = clock or time.time
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job_id):
        raise ValueError('Invalid batch ID')
    job, _ = proof(c, job_id)
    done = retained(c, job)
    if done is not None:
        journal = _settle_journal(c, job_id, done['attempt_id'], done['result_path'], clock()) if settle_journal else None
        return done | dict(driver_journal=journal)
    gate = safe_path(c.local / 'native-gate')
    with exclusive_gate(gate):
        # Repeat the whole proof while EA consumption and controller commits are excluded.
        job, evidence = proof(c, job_id)
        done = retained(c, job)
        if done is not None:
            return done
        runtime = _runtime(c)
        state = c.state()
        binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
        authority(c.store.db, binding, state)
        if state['owner'] != 'agent':
            _refuse('A human has taken control of this terminal; nothing was retired.')
        attempt = job['launch_intent']['attempt_id']
        now = clock()
        folder = safe_path(c.root / 'retired-starts'); folder.mkdir(exist_ok=True)
        result_path = safe_path(folder / (job_id + '-' + attempt[:16] + '.json'))
        result = dict(schema_version=1, kind=KIND, status='cancelled', job_id=job_id, attempt_id=attempt,
                      reason=reason, previous_status=job['status'],
                      restart_phase=(job.get('restart_intent') or {}).get('phase'),
                      configuration_sha256=job['configuration_sha256'],
                      package_sha256=job['launch_intent']['package_sha256'],
                      reservation=job.get('reservation'), launch_intent=job['launch_intent'],
                      member_count=len(job['configuration'].get('batch_members') or [job['configuration']]),
                      executed_members=0, native_cancellation_claimed=False, native_effects_sent=False,
                      proof=evidence, runtime=runtime,
                      retired_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                      next_action=('Nothing ran. Prepare the same members under a new batch ID: resume-batch --source-batch-id '
                                   + job_id + ' --batch-id <new-id>, or prepare-batch with the original plan.'))
        if not result_path.exists():
            write_json(result_path, result)
        elif read_json(result_path).get('attempt_id') != attempt:
            _refuse('A different retirement record already exists for this batch; inspect ' + str(result_path) + '.')
        else:
            result = read_json(result_path)
        # The native gate is already held (as in studio_finish), so commit directly
        # rather than through store.transaction, which would take it again.
        c.store.db.execute('BEGIN IMMEDIATE')
        try:
            current_state = c.store.snapshot(c.terminal, c.run)
            current = next((row for row in current_state['queue'] if row['job_id'] == job_id), None)
            if (current is None or current.get('launch_intent') != job['launch_intent']
                    or current['status'] != job['status'] or current_state['owner'] != 'agent'):
                _refuse('Batch ' + job_id + ' changed during retirement; nothing was retired, retry to re-check it.')
            current.update(status='cancelled', completion=result, completion_path=str(result_path))
            c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(current_state['queue']), binding))
            c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
            c.store.db.execute('COMMIT')
        except BaseException:
            c.store.db.execute('ROLLBACK'); raise
    c.bridge.pump()
    journal = _settle_journal(c, job_id, attempt, result_path, now) if settle_journal else None
    return dict(status='cancelled', kind=KIND, batch_id=job_id, attempt_id=attempt, result_path=str(result_path),
                executed_members=0, native_cancellation_claimed=False, reused=False, driver_journal=journal,
                next_action=result['next_action'])


def unactivated_hint(root, job):
    """Read-only, for status: does this active job look like a start refused before activation?"""
    if job.get('status') not in UNSETTLED or 'launch_intent' not in job:
        return False
    restart = job.get('restart_intent')
    if restart is not None and restart.get('phase') != 'prepared':
        return False
    attempt = job['launch_intent'].get('attempt_id', '')
    return bool(re.fullmatch(r'[a-f0-9]{64}', attempt)) and not (Path(root) / 'attempts' / attempt).exists()
