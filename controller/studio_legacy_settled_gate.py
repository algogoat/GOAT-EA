"""Read-only recognition of the scoped-worker completion schema predating Setup.

This is an explicit legacy schema route, never a fallback for public finish.
Caller holds the native gate and coordinates controller/worker registry writers;
recheck before mutation. A historical released attempt is NOT current worker
clearance, tester liveness, permission, or financial performance qualification.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from campaign_ledger import packed, sha
from studio_native_gate import _read_gate_evidence


CONTROLS = {'active_optimization_run.ini', 'active_optimization_config.ini',
            'active_optimization_launch.ini'}


def _path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(value).startswith(('\\\\', '//')):
        raise ValueError('Absolute local evidence path required')
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Linked legacy evidence refused')
    return path.resolve()


def _same(left, right):
    return os.path.normcase(str(_path(left))) == os.path.normcase(str(_path(right)))


def assert_legacy_settled_request(db, root, registry_path):
    """Return only historical_attempt_settled, without modifying any evidence.

    registry_path must come from the caller's reviewed worker binding, never a
    path supplied by a retained request. Missing/changed evidence fails closed.
    """
    registry = None
    observed = {}
    def raw_file(path):
        path = _path(path)
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Missing or oversized legacy evidence')
        raw = path.read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError('Oversized legacy evidence')
        observed[path] = hashlib.sha256(raw).hexdigest()
        return raw
    def record(path):
        path = _path(path)
        raw, value = _read_gate_evidence(path)
        observed[path] = hashlib.sha256(raw).hexdigest()
        return value
    def require(ok, message):
        if not ok: raise ValueError(message)
    try:
        root, registry_path = _path(root), _path(registry_path)
        database = _path(db.execute('PRAGMA database_list').fetchone()[2])
        require(registry_path.is_file(), 'Worker registry missing')
        require(not (root/'permit.json').exists() and not (root/'permit.json').is_symlink(), 'Native permit remains unresolved')
        require(record(root/'controller.json') == {'database': str(database)}, 'Foreign native gate database')
        gate_row = db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
        require(gate_row is not None and _same(gate_row[0], root), 'Controller native gate differs')
        request = record(root/'request.json'); digest = observed[root/'request.json']
        attempt = request['request_id']; scope = request['terminal_id']
        require(isinstance(attempt, str) and re.fullmatch('[a-f0-9]{64}', attempt), 'Invalid request identity')
        require(isinstance(scope, str) and re.fullmatch('[a-z0-9][a-z0-9-]{0,31}', scope), 'Invalid worker scope')
        require(request['action'] == 'arm_restart' and request['native_control_scope'] == scope,
                'Only the original scoped restart completion schema is accepted')
        issued = record(root/('issued-'+attempt+'.json'))
        consumed = raw_file(root/('consumed-'+attempt+'.json'))
        result = record(root/('result-'+attempt+'.json'))
        require(issued == {'request': request, 'request_sha256': digest}
                and hashlib.sha256(consumed).hexdigest() == digest,
                'Request issuance/consumption differs')
        require(result['request_id'] == attempt and result['request_sha256'] == digest
                and result['status'] == 'RESTART_ARMED_RECONCILE', 'Dispatch result differs')
        binding = packed(dict(terminal_id=scope, run_id=request['run_id']))
        queue_row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
        require(queue_row is not None, 'Controller binding missing')
        jobs = [j for j in json.loads(queue_row[0]) if j['job_id'] == request['job_id']]
        require(len(jobs) == 1, 'Ambiguous historical job')
        job = jobs[0]; intent = job['launch_intent']
        require(job['status'] in ('failed', 'completed') and 'completion_path' not in job,
                'Not a settled legacy worker job')
        require(intent['attempt_id'] == attempt and sha(job['configuration']) == job['configuration_sha256']
                and request['configuration_sha256'] == job['configuration_sha256'], 'Frozen attempt/configuration differs')
        # Original worker artifacts have an explicit layout under the reviewed registry root.
        package = _path(intent['package'])
        relative = package.relative_to(registry_path.parent)
        parts = relative.parts
        require(len(parts) == 6 and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*', parts[0])
                and parts[1:4] == (scope, 'campaign', 'jobs')
                and re.fullmatch('[0-9]{3,}', parts[4]) and parts[5] == 'package',
                'Package is not in the canonical legacy campaign layout')
        manifest = record(package/'manifest.json'); plan = record(package/'studio-plan.json')
        require(observed[package/'manifest.json'] == intent['package_sha256']
                and manifest['schema_version'] == 1 and manifest['stage'] == 'native_batch_package_unactivated'
                and manifest['campaign_id'] == sha(plan) and len(manifest['jobs']) == 1,
                'Immutable package manifest/plan differs')
        source = plan['studio_source']
        require(all(source[k] == request[k] for k in ('terminal_id', 'run_id', 'job_id', 'configuration_sha256')),
                'Package belongs to another controller job')
        item = manifest['jobs'][0]; alias = item['run_alias']
        require(isinstance(alias, str) and re.fullmatch('R[0-9a-f]{20}', alias), 'Unsafe package alias')
        for suffix, key in (('.set', 'staged_sha256'), ('.ini', 'ini_sha256')):
            require(hashlib.sha256(raw_file(package/(alias+suffix))).hexdigest() == item[key], 'Immutable staged bytes changed')
        registry = sqlite3.connect(registry_path.as_uri()+'?mode=ro', uri=True)
        registry.execute('BEGIN')
        worker_row = registry.execute('SELECT configuration FROM workers WHERE scope=?', (scope,)).fetchone()
        require(worker_row is not None, 'Reviewed worker registration missing')
        worker = json.loads(worker_row[0]); research = plan['research_binding']
        require(worker['scope'] == scope and _same(worker['controller'], database)
                and _same(Path(worker['bridge'])/'native-gate', root)
                and _same(research['controller_database'], database)
                and _same(research['bridge_root'], worker['bridge'])
                and _same(research['concurrent_worker_registry'], registry_path)
                and research['native_control_scope'] == scope and research['live_trading_allowed'] is False,
                'Registered worker/package binding differs')
        activation = package.parent/'activation'; completion = activation/'completion'
        outcome = record(completion/'outcome.json'); transaction = record(activation/'transaction.json')
        release = record(completion/'release.json')
        require(outcome == job['completion'] and outcome['attempt_id'] == attempt and outcome['scope'] == scope
                and outcome['job_id'] == job['job_id'] and outcome['configuration_sha256'] == job['configuration_sha256']
                and outcome['outcome'] == 'execution_and_report_integrity_verified', 'Exact settled outcome missing')
        require(outcome['native']['status'] == ('native_error' if job['status'] == 'failed' else 'native_completed')
                and bool(outcome['negative_selection']) == (job['status'] == 'failed'), 'Settled outcome/status differs')
        require(transaction['owner'] == attempt and transaction['phase'] == 'restored'
                and set(transaction['files']) == CONTROLS
                and all(v['before'] is None and v['before_sha256'] is None for v in transaction['files'].values()),
                'Original empty scoped controls were not restored')
        for name, key in (('active_optimization_run.ini', 'pointer_sha256'),
                          ('active_optimization_config.ini', 'native_config_sha256'),
                          ('active_optimization_launch.ini', 'guard_sha256')):
            require(transaction['files'][name]['after_sha256'] == request[key],
                    'Restored controls do not match the consumed request')
        expected_base = _path(worker['common_root'])/'GOAT'/'Workers'/scope/('GOAT V1.47-'+request['account_server'])
        require(re.fullmatch('[A-Za-z0-9_. -]+', request['account_server']) and _same(transaction['base'], expected_base),
                'Restored transaction belongs to another scoped control root')
        require(release['scope'] == scope and release['attempt_id'] == attempt and release['controls_retired'] is True
                and release['outcome_sha256'] == sha(outcome), 'Completion release does not bind the outcome')
        historical = registry.execute('SELECT claim,released,release_evidence FROM attempts WHERE scope=? AND attempt=?',
                                      (scope, attempt)).fetchone()
        require(historical is not None and historical[1] == 1, 'Historical registry claim not released')
        proof = json.loads(historical[2])
        require(json.loads(historical[0]) == release['host'] and _same(proof['receipt_path'], completion/'release.json')
                and proof['receipt_sha256'] == observed[completion/'release.json'], 'Registry release evidence differs')
        # Re-read files and the durable queue to reject observations mixed across writers.
        for evidence, expected in observed.items():
            require(hashlib.sha256(raw_file(evidence)).hexdigest() == expected, 'Legacy evidence changed during inspection')
        require(not (root/'permit.json').exists() and not (root/'permit.json').is_symlink(), 'Native permit appeared during inspection')
        require(db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone() == queue_row,
                'Controller changed during historical inspection')
        return dict(status='historical_attempt_settled', scope='historical_attempt_only', attempt_id=attempt,
                    request_id=attempt, request_sha256=digest, job_id=job['job_id'], terminal_id=scope,
                    run_id=request['run_id'], completion_sha256=observed[completion/'outcome.json'],
                    release_sha256=observed[completion/'release.json'], transaction_sha256=observed[activation/'transaction.json'],
                    package_sha256=observed[package/'manifest.json'], worker_clearance=False)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error) as error:
        raise ValueError('Legacy settled request not verified: '+str(error)) from error
    finally:
        if registry is not None: registry.close()
