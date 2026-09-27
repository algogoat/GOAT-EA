"""Explicit pending-work cleanup; retained history is never deleted or reset."""
from collections import Counter
import json
import re


def clear_queue(controller, *, apply=False, request_id=None, expected_revision=None):
    if apply:
        if (not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id)
                or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError('Apply requires a safe request-id and the expected-revision from clear-queue preview')
        receipt = controller.submit('queue.clear_pending', {}, request_id, expected_revision=expected_revision)
        return dict(status='pending_cleared', receipt=receipt, execution_effect=False,
                    next_action='prepare-batch with a new batch-id and explicit plan; inspect batch-status, then explicitly start')
    if request_id is not None or expected_revision is not None:
        raise ValueError('Preview takes no request identity; use --apply for an explicit mutation')
    state = controller.state()
    pending = [j for j in state['queue'] if j['status'] == 'pending']
    return dict(status='preview', expected_revision=state['revision'], owner=state['owner'],
                pending_job_ids=[j['job_id'] for j in pending], pending_count=len(pending),
                preserved_status_counts=dict(Counter(j['status'] for j in state['queue'] if j['status'] != 'pending')),
                execution_effect=False, readiness_scope='Queue preview only; apply rechecks ownership, state and native controls',
                next_action='To clear these pending jobs, repeat with --apply --request-id <unique-id> --expected-revision '+str(state['revision']))


def recovery_status(controller):
    """Diagnosis only: missing launch ownership must never become reset authority."""
    from studio_native_inventory import inventory
    from studio_process_check import inspect_processes
    from studio_resilient_read import read_observation
    from studio_seed_slot import guard_active_seed
    blockers, runtime, controls = [], None, None
    try:
        observation, _ = read_observation(controller.local/'ui-observation.json')
        batch = observation['runtime']['batch_ongoing']
        if type(batch) is not bool: raise ValueError('Unknown batch continuation flag')
        checked, _ = controller.runtime(require_idle=True, expected_batch_ongoing=batch)
        runtime = dict(batch_ongoing=batch, tester_state=checked['runtime']['tester_state'])
    except (OSError, ValueError, KeyError) as exc:
        blockers.append('Runtime inspection: '+str(exc))
    try:
        inspect_processes(controller.binding())
    except (OSError, ValueError) as exc:
        blockers.append('Terminal process inspection: '+str(exc))
    try:
        native = inventory(controller.install['common_files_root'], controller.session['account']['server'], controller.install['ea_version'])
        controls = [name for name, value in native['controls'].items() if value is not None]
        if controls: blockers.append('Existing native controls require their original owned attempt to be reconciled')
        guard_active_seed(controller.root)
    except (OSError, ValueError, KeyError) as exc:
        blockers.append('Native ownership inspection: '+str(exc))
    settled = {'pending','completed','failed','cancelled','removed','superseded'}
    for queued in controller.store.db.execute('SELECT jobs FROM studio_queues'):
        if any(j.get('status') not in settled or (j['status']=='pending' and 'launch_intent' in j)
               for j in json.loads(queued['jobs'])):
            blockers.append('Unresolved controller attempt; use status/cancel/finish with its retained job identity')
            break
    if any((controller.local/'native-gate'/name).exists() for name in ('request.json','permit.json')):
        blockers.append('Unconsumed native request or permit requires reconciliation')
    possible_orphan = runtime is not None and runtime['batch_ongoing'] and not blockers
    return dict(status='possible_orphan_unqualified' if possible_orphan else 'inspection',
                runtime=runtime, present_native_controls=controls, blockers=blockers,
                orphan_recovery_supported=False, execution_effect=False, launch_permitted=False,
                limitations=['Point-in-time diagnosis is not proof of orphan ownership',
                             'Legacy gates and other-version Common Files need review before any native recovery'],
                next_action='For owned work use status/cancel/finish. An orphan continuation flag requires a compatible reviewed EA/controller recovery release; do not invoke Start/Stop as a reset, delete native files, edit terminal globals or fabricate an attempt.')
