"""Retained one-successor orchestration for an expired unconsumed review refusal."""
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json
from studio_orphan_recovery import prepare, apply, status, plan_path
from studio_orphan_rejection import reconcile_rejection


def active(root):
    directory = safe_path(root / 'demo-agent/orphan-successors')
    rows = []
    for path in directory.glob('*.json'):
        record = read_json(safe_path(path))
        if (set(record) != {'schema_version', 'phase', 'original_review_id', 'original_request_id', 'successor_review_id'}
                or record['schema_version'] != 1 or path.stem != record['original_review_id']
                or record['phase'] not in ('settling', 'prepared', 'published', 'completed')):
            raise ValueError('Retained orphan successor journal changed')
        if record['phase'] != 'completed':
            rows.append(record)
    if len(rows) > 1:
        raise ValueError('Multiple unfinished orphan successors require inspection')
    return rows[0] if rows else None


def completed(root, review_id):
    record = active(root)
    if record is not None and record['successor_review_id'] == review_id:
        write_json(safe_path(root / 'demo-agent/orphan-successors' / (record['original_review_id'] + '.json')),
                   dict(record, phase='completed'))


def recover(c, record=None, *, original_review_id=None, evidence=None):
    directory = safe_path(c.root / 'demo-agent/orphan-successors')
    if record is None:
        if (not evidence or evidence.get('status') != 'receipt_observed'
                or evidence.get('consumed') is not False
                or evidence.get('receipt', {}).get('status') != 'ORPHAN_REVIEW_REJECTED'):
            raise ValueError('Exact unconsumed review rejection required')
        original = read_json(plan_path(c, original_review_id))
        record = dict(schema_version=1, phase='settling', original_review_id=original_review_id,
                      original_request_id=original['record']['request']['request_id'], successor_review_id=None)
        directory.mkdir(parents=True, exist_ok=True)
        journal = safe_path(directory / (original_review_id + '.json'))
        if journal.exists():
            raise ValueError('Original recovery already has a retained successor')
        # This intent precedes removal of the old pending fence. A restart can
        # never fall through to a new unlinked ordinary recovery request.
        write_json(journal, record)
    journal = safe_path(directory / (record['original_review_id'] + '.json'))
    if read_json(journal) != record:
        raise ValueError('Orphan successor journal changed before recovery')
    original = read_json(plan_path(c, record['original_review_id']))
    if original['record']['request']['request_id'] != record['original_request_id']:
        raise ValueError('Orphan successor predecessor identity changed')
    fence = c.root / 'orphan-recovery-pending.json'
    if fence.exists() and read_json(fence).get('review_id') not in (record['original_review_id'], record['successor_review_id']):
        raise ValueError('Another pending recovery cannot be superseded')
    if record['phase'] == 'settling':
        settled = reconcile_rejection(c, record['original_review_id'], owner_research=True)
        if settled['status'] != 'rejected_settled':
            return settled
        review = prepare(c)
        record = dict(record, phase='prepared', successor_review_id=review['review_id'])
        write_json(journal, record)
    review_id = record['successor_review_id']
    if record['phase'] == 'prepared':
        # Existing apply observes issued state instead of replaying it, including
        # a crash after publication but before this journal advances.
        result = apply(c, review_id, owner_research=True)
        record = dict(record, phase='published')
        write_json(journal, record)
    else:
        result = status(c, review_id)
    if result['status'] == 'recovered':
        write_json(journal, dict(record, phase='completed'))
    return dict(result, automatic_successor_available=False)
