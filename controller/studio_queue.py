"""Pending-job preparation only; no native launch or state transitions."""
import copy
import re
from campaign_ledger import sha
from studio_settings import validate_tester, validate_export
from studio_strategy_settings import validate_strategy
from studio_dependencies import audit_dependencies

COMMANDS = ('queue.enqueue', 'queue.enqueue_batch', 'queue.revise', 'queue.cancel', 'queue.remove', 'queue.reorder', 'queue.reserve', 'queue.release_reservation')


def validate_batch_members(members, schema, policy):
    if not isinstance(members, list) or not 1 <= len(members) <= 10000:
        raise ValueError('Native batch requires 1..10000 explicit members')
    checked_members, identities = [], set()
    for member in members:
        if not isinstance(member, dict) or set(member) != {'tester', 'export', 'strategy'}:
            raise ValueError('Each batch member requires tester, export and strategy settings')
        tester = validate_tester(member['tester'])
        exports = validate_export(member['export'], tester)
        raw = member['strategy']
        if not isinstance(raw, dict) or set(raw) != {'schema_hash', 'values'} or raw['schema_hash'] != sha(schema):
            raise ValueError('Batch member requires the installed input schema')
        strategy = validate_strategy(raw['values'], schema)
        if not strategy['axes']:
            raise ValueError('Optimization batch member has no enabled search dimensions')
        strategy['schema_hash'] = sha(schema)
        if policy is not None:
            audit = audit_dependencies(strategy, schema, policy)
            errors = [item['message'] for item in audit['findings'] if item['severity'] == 'error']
            if errors:
                raise ValueError('; '.join(errors))
            strategy['dependency_validation'] = audit
        current = dict(tester=tester, export=exports, strategy=strategy)
        if tester['ForwardMode'] != 4:
            raise ValueError('Native export batches require an explicit custom forward window')
        if checked_members:
            first = checked_members[0]
            if exports != first['export'] or tester['ForwardDate'] != first['tester']['ForwardDate'] or tester['Expert'] != first['tester']['Expert']:
                raise ValueError('Studio uses one EA, export policy and forward boundary per native batch')
        identity = sha(current)
        if identity in identities:
            raise ValueError('Duplicate file/asset/settings member')
        identities.add(identity)
        checked_members.append(current)
    return checked_members


def reserve_job(state, payload, reservation_id):
    if (not isinstance(payload, dict) or set(payload) != {'job_id','configuration_sha256','package_sha256'}
            or not isinstance(payload['job_id'], str)
            or any(not isinstance(payload[k], str) or not re.fullmatch('[0-9a-f]{64}',payload[k])
                   for k in ('configuration_sha256','package_sha256'))):
        raise ValueError('Job identity and explicit configuration/package hashes required')
    jobs = copy.deepcopy(state['queue'])
    pending = next((j for j in jobs if j['status'] == 'pending'), None)
    if pending is None or pending['job_id'] != payload['job_id']:
        raise ValueError('Only the first pending job can be reserved')
    if sha(pending['configuration']) != payload['configuration_sha256'] or pending['configuration_sha256'] != payload['configuration_sha256']:
        raise ValueError('Reservation configuration mismatch')
    pending.update(status='reserved', reservation=dict(reservation_id=reservation_id,
        package_sha256=payload['package_sha256'],generation=state['generation'],owner=state['owner'],
        launch_permitted=False))
    return jobs


def change_queue(command, payload, state, schema, policy):
    if not isinstance(payload, dict):
        raise ValueError('Queue payload must be an object')
    jobs = copy.deepcopy(state['queue'])
    if command == 'queue.enqueue_batch':
        if set(payload) != {'job_id', 'members'} or not isinstance(payload['job_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', payload['job_id']):
            raise ValueError('Explicit safe batch job_id and members required')
        if any(j['job_id'] == payload['job_id'] for j in jobs) or len(jobs) >= 10000:
            raise ValueError('Batch identity exists or campaign queue is full')
        members = validate_batch_members(payload['members'], schema, policy)
        config = dict(members[0], batch_members=members)
        jobs.append(dict(job_id=payload['job_id'], status='pending', configuration=config,
            configuration_sha256=sha(config), source_revision=state['revision'], execution_ready=False))
    elif command in ('queue.enqueue', 'queue.revise'):
        required = {'job_id', 'replaces_job_id'} if command == 'queue.revise' else {'job_id'}
        if set(payload) != required or not isinstance(payload['job_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', payload['job_id']):
            raise ValueError('Explicit safe job_id required')
        if any(j['job_id'] == payload['job_id'] for j in jobs):
            raise ValueError('Job identity already exists; use the original request to retry')
        if len(jobs) >= 10000:
            raise ValueError('Campaign job limit reached')
        previous = None
        if command == 'queue.revise':
            if not isinstance(payload['replaces_job_id'], str):
                raise ValueError('Existing pending job identity required')
            previous = next((j for j in jobs if j['job_id'] == payload['replaces_job_id']), None)
            if previous is None or previous['status'] != 'pending':
                raise ValueError('Only an existing pending job can be revised')
        tester = validate_tester(state['tester_draft'])
        exports = validate_export(state['export_draft'], tester)
        strategy = state['strategy_draft']
        if schema is None or not isinstance(strategy, dict) or strategy.get('schema_hash') != sha(schema):
            raise ValueError('Complete strategy draft with current schema required')
        checked = validate_strategy(strategy['values'], schema)
        checked['schema_hash'] = sha(schema)
        if policy is not None:
            audit = audit_dependencies(checked, schema, policy)
            errors = [f['message'] for f in audit['findings'] if f['severity'] == 'error']
            if errors:
                raise ValueError('; '.join(errors))
            checked['dependency_validation'] = audit
        configuration = {'tester': tester, 'export': exports, 'strategy': checked}
        new_job = dict(job_id=payload['job_id'], status='pending',
                         configuration=configuration, configuration_sha256=sha(configuration),
                         source_revision=state['revision'], execution_ready=False)
        if previous is None:
            jobs.append(new_job)
        else:
            new_job['replaces_job_id'] = previous['job_id']
            previous.update(status='superseded', superseded_by=new_job['job_id'])
            jobs.insert(jobs.index(previous)+1, new_job)
    elif command == 'queue.release_reservation':
        if (set(payload) != {'job_id', 'reservation_id'}
                or any(not isinstance(payload[k], str) or not payload[k] for k in payload)):
            raise ValueError('Explicit job and reservation identities required')
        job = next((j for j in jobs if j['job_id'] == payload['job_id']), None)
        if job is None or job['status'] != 'reserved' or 'launch_intent' in job:
            raise ValueError('Only an unstarted reservation can be released; reconcile attempted launches')
        reservation = job.get('reservation', {})
        if (reservation.get('reservation_id') != payload['reservation_id']
                or reservation.get('launch_permitted') is not False):
            raise ValueError('Unstarted reservation identity mismatch')
        # Current owner may recover a revoked predecessor's reservation. The
        # store serializes this against record_intent; neither can win twice.
        job.setdefault('reservation_history', []).append(dict(reservation,
            outcome='released_before_intent', released_by=state['owner'],
            released_generation=state['generation'], released_revision=state['revision']+1))
        del job['reservation']
        job['status'] = 'pending'
    elif command in ('queue.cancel', 'queue.remove'):
        if set(payload) != {'job_id'} or not isinstance(payload['job_id'], str):
            raise ValueError('job_id required')
        job = next((j for j in jobs if j['job_id'] == payload['job_id']), None)
        if job is None or job['status'] != 'pending':
            raise ValueError('Only an existing pending job can be cancelled or removed')
        job['status'] = 'cancelled' if command == 'queue.cancel' else 'removed'
    elif command == 'queue.reorder':
        ids = payload.get('job_ids')
        pending = {j['job_id']: j for j in jobs if j['status'] == 'pending'}
        if (set(payload) != {'job_ids'} or not isinstance(ids, list)
                or any(not isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids)) or set(ids) != set(pending)):
            raise ValueError('List every pending job exactly once')
        ordered = iter(pending[i] for i in ids)
        jobs = [next(ordered) if j['status'] == 'pending' else j for j in jobs]
    else:
        raise ValueError('Unsupported queue command')
    return jobs
