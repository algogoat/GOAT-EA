"""Prove a recorded config-start intent never reached native activation."""
import hashlib
import json
from pathlib import Path
import re

from campaign_ledger import sha
from studio_handover import safe_path
from studio_installation import read_json
from studio_report_paths import report_paths
from studio_dispatch_observe import observe_dispatch
from studio_native_gate import settled_native_request


def proof(c, job, package):
    if job.get('status') != 'starting' or 'restart_intent' in job:
        raise ValueError('Only an intent refused before native preparation can resume')
    intent = job['launch_intent']
    reservation = job['reservation']
    state = c.state()
    manifest_path = safe_path(package / 'manifest.json')
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if (Path(intent['package']).resolve() != package or intent['package_sha256'] != digest
        or reservation['package_sha256'] != digest or reservation['generation'] != state['generation']
        or reservation['owner'] != state['owner'] or state['owner'] != 'agent'
        or intent['attempt_id'] != sha([reservation['reservation_id'], digest])):
        raise ValueError('Unissued intent/reservation binding changed')
    native_absence(c, job, package)
    return intent


def native_absence(c, job, package):
    intent = job['launch_intent']
    evidence = safe_path(c.root / 'attempts' / intent['attempt_id'])
    if evidence.exists():
        raise ValueError('Native activation evidence exists; never repeat an issued operation')
    gate = safe_path(c.local / 'native-gate')
    # A request.json the EA already consumed and answered for this session is settled evidence
    # (goatai#1885); the history checks below still require its job's durable completion.
    permit, request_path = gate / 'permit.json', gate / 'request.json'
    requested = request_path.exists() or request_path.is_symlink()
    if (permit.exists() or permit.is_symlink()
            or (requested and settled_native_request(gate, dict(terminal_id=c.terminal, run_id=c.run)) is None)):
        raise ValueError('Native request or permit exists; reconcile before any first activation')
    for item in gate.glob('*.json'):
        item = safe_path(item)
        marker = re.fullmatch(r'(issued|consumed|result)-([a-f0-9]{64})\.json', item.name)
        if marker:
            settled_other_request(c, gate, marker[2], job['job_id'])
        row = read_json(item)
        request = row.get('request', row)
        if (request.get('job_id') == job['job_id'] or request.get('attempt_id') == intent['attempt_id']
            or request.get('request_id') == intent['attempt_id']):
            raise ValueError('Native request evidence exists; reconcile its original outcome')
    manifest = read_json(safe_path(package / 'manifest.json'))
    plan = read_json(safe_path(package / 'studio-plan.json'))
    for index in range(len(manifest['jobs'])):
        paths = report_paths(plan, manifest, index)
        for name in ('local_run', 'common_run'):
            root = safe_path(paths[name])
            if root.exists():
                raise ValueError('Native run directory exists; never assume no execution')


def settled_other_request(c, gate, request_id, current_job):
    """Hash-only marker history needs full, durable, foreign-job completion."""
    from studio_native_gate import _read_gate_evidence
    from studio_cancel_successor import cancel_id
    _, issued = _read_gate_evidence(gate / ('issued-' + request_id + '.json'))
    request = issued['request']
    if (request['request_id'] != request_id or request['job_id'] == current_job
        or request['terminal_id'] != c.terminal or request['run_id'] != c.run):
        raise ValueError('Native request is not from a different settled job')
    jobs = [row for row in c.state()['queue'] if row['job_id'] == request['job_id']]
    if len(jobs) != 1 or jobs[0]['status'] not in ('completed', 'cancelled', 'failed'):
        raise ValueError('Native request history has no settled controller job')
    other = jobs[0]
    intent = other['launch_intent']
    attempt = intent['attempt_id']
    action = request.get('action', 'start')
    if action not in ('start', 'arm_restart', 'cancel'):
        raise ValueError('Unknown native history action')
    expected = cancel_id(c.root, other, gate) if action == 'cancel' else attempt
    if request_id != expected or (action == 'cancel' and request.get('attempt_id') != attempt):
        raise ValueError('Native history does not match its original attempt')
    dispatch = observe_dispatch(gate, request_id)
    if dispatch.get('status') != 'receipt_observed' or dispatch.get('consumed') is not True:
        raise ValueError('Native history is not durably consumed and acknowledged')
    evidence = safe_path(c.root / 'attempts' / attempt)
    result_path = safe_path(evidence / 'result.json')
    _, result = _read_gate_evidence(result_path)
    _, transaction = _read_gate_evidence(evidence / 'transaction.json')
    outcomes = {'completed': 'native_completed', 'cancelled': 'native_cancelled', 'failed': 'native_error'}
    if (Path(other['completion_path']).resolve() != result_path or other['completion'] != result
        or result['status'] != other['status'] or result['job_id'] != other['job_id']
        or result['attempt_id'] != attempt or result['configuration'] != other['configuration']
        or result['configuration_sha256'] != sha(other['configuration'])
        or result['configuration_sha256'] != request['configuration_sha256']
        or result['package_sha256'] != intent['package_sha256']
        or result['native']['status'] != outcomes[other['status']]
        or transaction['phase'] != 'restored' or transaction['owner'] != attempt):
        raise ValueError('Native history lacks exact completion and restored controls')
    package = safe_path(c.root / 'packages' / other['job_id'])
    if (Path(intent['package']).resolve() != package
        or hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest() != intent['package_sha256']):
        raise ValueError('Settled history package changed')
