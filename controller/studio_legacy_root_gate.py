"""Read-only migration of pre-Setup, unscoped campaign completion receipts.

Called only during offline handover, never to clear a running controller queue.
Historical completion is not a current native launch or ownership grant.
"""
import hashlib
import json
import re

from campaign_ledger import packed, sha
from studio_legacy_settled_gate import CONTROLS, _path, _same
from studio_native_gate import _read_gate_evidence


def assert_legacy_root_settled(db, root, installation):
    observed = {}

    def record(path):
        path = _path(path)
        raw, value = _read_gate_evidence(path)
        observed[path] = hashlib.sha256(raw).hexdigest()
        return value

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    try:
        root = _path(root)
        data = _path(installation['terminal_data_root'])
        common = _path(installation['common_files_root'])
        require(root == data/'MQL5/Files/GOATStudio/native-gate', 'Not a legacy root gate')
        database = _path(db.execute('PRAGMA database_list').fetchone()[2])
        require(record(root/'controller.json') == {'database': str(database)}, 'Foreign gate database')
        gate_row = db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
        require(gate_row is not None and _same(gate_row[0], root), 'Registered gate differs')
        require(not (root/'permit.json').exists() and not (root/'permit.json').is_symlink(), 'Unresolved native permit')
        request = record(root/'request.json')
        attempt = request['request_id']
        require(isinstance(attempt, str) and re.fullmatch('[a-f0-9]{64}', attempt), 'Invalid attempt')
        require(request['action'] == 'arm_restart' and not request.get('native_control_scope'), 'Not an unscoped restart')
        digest = observed[root/'request.json']
        require(record(root/('issued-'+attempt+'.json')) == dict(request=request, request_sha256=digest), 'Issuance differs')
        record(root/('consumed-'+attempt+'.json'))
        require(observed[root/('consumed-'+attempt+'.json')] == digest, 'Consumption differs')
        result = record(root/('result-'+attempt+'.json'))
        require(result['request_id'] == attempt and result['request_sha256'] == digest
                and result['status'] == 'RESTART_ARMED_RECONCILE', 'Dispatch result differs')
        binding = packed(dict(terminal_id=request['terminal_id'], run_id=request['run_id']))
        row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
        require(row is not None, 'Missing controller binding')
        jobs = [j for j in json.loads(row[0]) if j['job_id'] == request['job_id']]
        require(len(jobs) == 1, 'Ambiguous retained job')
        job = jobs[0]
        require(job['status'] in ('completed', 'failed') and 'completion_path' not in job, 'Not a settled legacy job')
        intent = job['launch_intent']
        require(intent['attempt_id'] == attempt and sha(job['configuration']) == job['configuration_sha256']
                and request['configuration_sha256'] == job['configuration_sha256'], 'Frozen configuration differs')
        package = _path(intent['package'])
        require(package.name == 'package' and re.fullmatch('[0-9]{3,}', package.parent.name)
                and package.parent.parent.name == 'jobs', 'Not a legacy job package')
        manifest = record(package/'manifest.json')
        plan = record(package/'studio-plan.json')
        require(observed[package/'manifest.json'] == intent['package_sha256']
                and manifest['schema_version'] == 1 and manifest['stage'] == 'native_batch_package_unactivated'
                and manifest['campaign_id'] == sha(plan) and len(manifest['jobs']) == 1, 'Frozen package differs')
        source = plan['studio_source']
        require(all(source[k] == request[k] for k in ('terminal_id', 'run_id', 'job_id', 'configuration_sha256')), 'Package source differs')
        research = plan['research_binding']
        require(_same(research['research_terminal'], installation['terminal_executable'])
                and _same(research['research_data_root'], data) and _same(research['common_files_root'], common)
                and research['live_trading_allowed'] is False
                and not research.get('native_control_scope'), 'Package terminal binding differs')
        item = manifest['jobs'][0]
        alias = item['run_alias']
        require(isinstance(alias, str) and re.fullmatch('R[0-9a-f]{20}', alias), 'Invalid run alias')
        for suffix, key in (('.set', 'staged_sha256'), ('.ini', 'ini_sha256')):
            path = _path(package/(alias+suffix))
            require(path.stat().st_size <= 64*1024*1024, 'Oversized package file')
            observed[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            require(observed[path] == item[key], 'Staged file changed')
        activation = package.parent/'activation'
        outcome = record(activation/'completion/outcome.json')
        transaction = record(activation/'transaction.json')
        started = record(activation/'activation.json')
        require(outcome == job['completion'] and outcome['outcome'] == 'execution_and_report_integrity_verified'
                and outcome['native']['studio_source'] == source and outcome['native']['run_alias'] == alias
                and outcome['native']['status'] == ('native_completed' if job['status'] == 'completed' else 'native_error')
                and bool(outcome['negative_selection']) == (job['status'] == 'failed'), 'Durable completion differs')
        require(started['attempt_id'] == attempt and _same(started['run'], outcome['native']['native_run']), 'Activation differs')
        native_run = _path(started['run'])
        require(native_run.parent == common/'GOAT' and re.fullmatch('R[0-9a-f]{12}', native_run.name), 'Foreign native run')
        require(transaction['owner'] == attempt and transaction['phase'] == 'restored'
                and set(transaction['files']) == CONTROLS
                and all(v['before'] is None and v['before_sha256'] is None for v in transaction['files'].values()), 'Controls were not restored')
        require(isinstance(request['account_server'], str) and re.fullmatch('[A-Za-z0-9_. -]+', request['account_server'])
                and _same(transaction['base'], common/'GOAT'/('GOAT V1.47-'+request['account_server'])), 'Foreign controls')
        for name, key in (('active_optimization_run.ini', 'pointer_sha256'),
                          ('active_optimization_config.ini', 'native_config_sha256'),
                          ('active_optimization_launch.ini', 'guard_sha256')):
            require(transaction['files'][name]['after_sha256'] == request[key], 'Restored request differs')
            path = _path(transaction['base'])/name
            require(not path.exists() and not path.is_symlink(), 'Native controls remain')
        owner = _path(transaction['base'])/'agent-native-control-owner.json'
        require(not owner.exists() and not owner.is_symlink(), 'Native control owner remains')
        for path, expected in observed.items():
            require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Evidence changed during inspection')
        require(db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone() == row, 'Queue changed')
        require(not (root/'permit.json').exists() and not (root/'permit.json').is_symlink(), 'Native permit appeared')
        return dict(status='historical_attempt_settled', scope='historical_attempt_only', attempt_id=attempt,
                    request_id=attempt, request_sha256=digest, job_id=job['job_id'], worker_clearance=False,
                    completion_sha256=observed[activation/'completion/outcome.json'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('Legacy root completion not verified: '+str(error)) from error
