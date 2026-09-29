"""Prove a recorded config-start intent never reached native activation."""
import hashlib
import json
from pathlib import Path

from campaign_ledger import sha
from studio_handover import safe_path
from studio_installation import read_json
from studio_report_paths import report_paths


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
    for item in gate.glob('*.json'):
        row = read_json(safe_path(item))
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
