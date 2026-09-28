"""Reviewed owner budget amendment; original grants and journals stay immutable."""
from pathlib import Path
import time

from campaign_ledger import sha
from studio_installation import read_json

POLICY_PATH = Path(__file__).parent/'contracts/owner_replacement_budget.json'


def renewal(scope, *, successor_id=None):
    policy = read_json(POLICY_PATH)
    if sha(scope) != policy['authority_sha256']:
        return None
    if (policy.get('schema_version') != 1 or policy['account'] != scope['account']
            or policy['binding'] != scope['binding'] or policy['max_seconds'] != 172800
            or type(policy['min_free_bytes']) is not int or policy['min_free_bytes'] < 5368709120
            or not 0 < policy['expires_utc']-policy['not_before_utc'] <= 7*86400):
        raise ValueError('Exact owner replacement budget is unavailable')
    if not policy['not_before_utc'] <= time.time() < policy['expires_utc']:
        return None  # Original expiry rules still permit observing/cancelling old work.
    if successor_id is not None and successor_id != policy['successor_job_id']:
        raise ValueError('Owner budget permits only the exact single replacement')
    return dict(policy_sha256=sha(policy), predecessor_job_id=policy['predecessor_job_id'],
                successor_job_id=policy['successor_job_id'], max_seconds=policy['max_seconds'],
                min_free_bytes=policy['min_free_bytes'], expires_utc=policy['expires_utc'])


def effective_expiry(scope):
    amendment = renewal(scope)
    return max(scope['expires_utc'], amendment['expires_utc']) if amendment else scope['expires_utc']


def verify_budget(journal, inherited):
    amendment = inherited.get('renewal_policy')
    if (not amendment or journal.get('budget_renewal') != amendment
            or journal['max_seconds'] != amendment['max_seconds']
            or journal['started_wall'] != journal.get('replacement_created_wall')
            or journal['deadline_wall'] != journal['started_wall'] + amendment['max_seconds']
            or journal['deadline_wall'] > amendment['expires_utc']
            or journal['min_free_bytes'] < max(inherited['min_free_bytes'], amendment['min_free_bytes'])):
        raise ValueError('Replacement differs from the explicit owner budget and disk reserve')
