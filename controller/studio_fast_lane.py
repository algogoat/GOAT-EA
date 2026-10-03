"""One operation per intent: stop, continue. Start is the bounded run-batch driver.

Each returns a result or raises ``ValueError`` with ONE plain sentence that names
the exact next action. Nothing here weakens a check: every native effect still
goes through the existing cancel/driver path, which keeps demo-only, Algo off,
human STOP/TAKE CONTROL and exact-input provenance.

stop      pending -> cancelled; reserved-not-started -> released + cancelled;
          start refused before MT5 was touched -> retire-unactivated (cancelled);
          dispatched -> the EA's own native cancel (the same queue/flag effect as
          the Studio STOP button), observed by the driver; finished -> no-op.
continue  remaining work of a finished/stopped/paused batch as a successor: never-run
          members first, then failures if asked; across an EA build change the
          members are re-prepared under the current installation and fully verified.
"""
import json
from pathlib import Path
import re

from campaign_ledger import sha
from studio_bridge import write_json

TERMINAL = ('completed', 'cancelled', 'failed')
DISPATCHED = ('starting', 'running', 'reconcile_required', 'verifying')


def _id(value, name='batch ID'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError('Invalid ' + name + '; use 1..80 letters, digits, underscore or hyphen.')
    return value


def stop(c, job_id):
    """Settle one batch to a terminal state, or publish its native cancel."""
    from studio_retire_unactivated import retire, unactivated_hint
    job = c.job(_id(job_id))
    status = job['status']
    if status in TERMINAL:
        return dict(status=status, batch_id=job_id, already_settled=True)
    if status == 'pending' and 'launch_intent' not in job:
        c.cancel(job_id, expected_generation=c.state()['generation'])
        return dict(status=c.job(job_id)['status'], batch_id=job_id, settled='pending_cancelled')
    if status == 'reserved' and 'launch_intent' not in job:
        reservation = job['reservation']
        if reservation.get('launch_permitted') is True:
            raise ValueError('Batch ' + job_id + ' was permitted to launch; run batch-status, then stop again once it reports.')
        # Same numbering as the driver's reserve/release pair for this start attempt, so a
        # release here never reuses the ID of an earlier driver release (receipts replay by ID).
        from studio_batch_driver import command_id, retry_index
        c.submit('queue.release_reservation', dict(job_id=job_id, reservation_id=reservation['reservation_id']),
                 command_id(job_id, '-release-reservation', retry_index(c.root, job_id)),
                 expected_generation=c.state()['generation'])
        c.cancel(job_id, expected_generation=c.state()['generation'])
        return dict(status=c.job(job_id)['status'], batch_id=job_id, settled='reservation_released_cancelled')
    if unactivated_hint(c.root, job):
        return retire(c, job_id, reason='stop')
    if status in DISPATCHED:
        published = c.cancel(job_id, expected_generation=c.state()['generation'])
        return dict(status='stopping', batch_id=job_id, cancel=published, stopped=False,
                    next_action='run-batch --job-id ' + job_id + ' --resume observes the native stop and finishes it')
    raise ValueError('Batch ' + job_id + ' is ' + status + '; run batch-status and report it.')


def binding_changed(c, job_id):
    plan = json.loads((Path(c.root) / 'packages' / job_id / 'studio-plan.json').read_text(encoding='utf-8'))
    recorded, current = plan['research_binding'], c.binding()
    from studio_protected_peer import PEER_BINDING_KEYS
    return sorted(key for key in set(recorded) | set(current)
                  if key not in PEER_BINDING_KEYS and recorded.get(key) != current.get(key))


def _lineage(root):
    """Retained successor lineage: {successor batch ID: predecessor batch ID}."""
    result = {}
    for item in sorted((Path(root) / 'batch-lineage').glob('*.json')):
        try:
            value = json.loads(item.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get('predecessor_batch_id'), str):
            result[value.get('batch_id', item.stem)] = value['predecessor_batch_id']
    return result


def _reusable(row):
    return row is None or (row['status'] == 'pending' and 'launch_intent' not in row)


def resolve_successor(root, queue, job_id, new_batch_id=None):
    """The successor ID Continue prepares or reuses. Read-only; ``queue`` maps job ID to row.

    A retained successor of this predecessor (its lineage names it, or a pause
    already planned it) that never started is reused, so a repeated Continue, for
    example after the driver failed to spawn, never allocates another ``-rN``. An
    explicit ID that already exists is reused only when its lineage names this
    predecessor; any other collision refuses.

    A pause's reserved successor that was settled without ever running (retired
    unactivated, retired never started, or cancelled before its start) no longer
    holds the lineage: Continue allocates the next free ``-rN`` (or accepts an
    explicit new ID) and ``continue_batch`` records the release append-only.
    """
    from studio_batch_pause import load as load_pause, releasable, successor_id
    lineage = _lineage(root)
    record = load_pause(root, job_id, quiet=True)
    planned = (record or {}).get('resume_batch_id')
    # Released successors stay ours (never reused: they are settled), so naming one
    # explicitly gets the settled-successor sentence, not "not a successor".
    released = {item.get('batch_id') for item in (record or {}).get('released_successors') or [] if isinstance(item, dict)}
    found = releasable(record, queue)
    if found:
        released.add(found[0])
        planned = None
    ours = {successor for successor, predecessor in lineage.items() if predecessor == job_id} | (released - {None})
    if planned:
        ours.add(planned)
    if new_batch_id is not None:
        new_id = _id(new_batch_id, 'successor batch ID')
        if (new_id in queue or new_id in lineage) and new_id not in ours:
            raise ValueError('Batch ' + new_id + ' already exists and is not a successor of ' + job_id
                             + '; pass a new --new-batch-id.')
        return new_id
    for successor in ([planned] if planned else []) + sorted(ours - {planned} - released):
        if _reusable(queue.get(successor)):
            return successor
    if planned:
        return planned
    return _id(successor_id(job_id, set(queue) | set(lineage)), 'successor batch ID')


def continue_batch(c, job_id, *, new_batch_id=None, include_failed=False, include_no_edge=False):
    """Prepare the remaining work of a finished batch as a new pending batch (no launch)."""
    from studio_batch import resume_batch
    from studio_batch_pause import load as load_pause
    from studio_retire_unactivated import retire, unactivated_hint
    source = c.job(_id(job_id))
    if source['status'] not in TERMINAL and unactivated_hint(c.root, source):
        retire(c, job_id, reason='continue')
        source = c.job(job_id)
    if source['status'] not in TERMINAL:
        raise ValueError('Batch ' + job_id + ' is still ' + source['status'] + '; stop it first: stop --batch-id ' + job_id + '.')
    queue = {row['job_id']: row for row in c.state()['queue']}
    # A reserved successor that never ran releases this batch's resume lineage first,
    # recorded append-only with its retirement proof (studio_batch_pause).
    from studio_batch_pause import release_unactivated
    import time
    released = release_unactivated(c.root, job_id, queue, now=time.time())
    pause = load_pause(c.root, job_id, quiet=True)
    new_id = resolve_successor(c.root, queue, job_id, new_batch_id)
    if new_id in queue:
        job = queue[new_id]
        if _reusable(job):
            return dict(state='prepared', source_batch_id=job_id, batch_id=new_id, reused=True,
                        next_action='start --batch-id ' + new_id)
        from studio_batch_pause import unactivated_proof
        if job['status'] in TERMINAL and 'launch_intent' in job and unactivated_proof(job) is None:
            # It ran: its own remaining work continues from its native evidence.
            raise ValueError('Successor ' + new_id + ' already ran and is ' + job['status']
                             + '; continue it instead: continue --batch-id ' + new_id + '.')
        raise ValueError('Successor ' + new_id + ' already exists as ' + job['status'] + '; pass a new --new-batch-id.')
    changed = binding_changed(c, job_id)
    paused = pause is not None and pause.get('state') == 'paused'
    if paused:
        from studio_batch_pause import verify_resumable, plan_resume
        import time
        verify_resumable(c, job_id, None)
        plan_resume(c.root, job_id, new_id, now=time.time())
    else:
        # Lineage before preparation: an interrupted Continue finds and reuses this ID.
        lineage = Path(c.root) / 'batch-lineage' / (new_id + '.json')
        if not lineage.exists():
            lineage.parent.mkdir(exist_ok=True)
            write_json(lineage, dict(schema_version=1, batch_id=new_id, predecessor_batch_id=job_id,
                                     kind='continue', binding_changed_keys=changed))
    prepared = resume_batch(c, job_id, new_id, include_failed=include_failed, include_no_edge=include_no_edge,
                            allow_peer_refresh=True, allow_binding_change=bool(changed))
    if paused:
        from studio_batch_pause import mark_resumed
        import time
        mark_resumed(c.root, job_id, new_id, now=time.time(), selected=prepared.get('member_count'))
    result = dict(state='prepared', source_batch_id=job_id, batch_id=new_id, members=prepared.get('member_count'),
                  binding_changed_keys=changed, reprepared_for_current_build=bool(changed),
                  next_action='start --batch-id ' + new_id)
    if released:
        result['released_successor'] = dict(batch_id=released['successor_batch_id'], proof=released['proof']['kind'],
                                            journal=released['journal'])
    return result
