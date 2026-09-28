"""Finite owner-only recovery authority from a genuine, still-current native grant.

No grant creation, human-channel submission, native effect or trade permission.
The reviewed policy is deliberately not a general customer standing-grant API.
"""
import json
from pathlib import Path
import time

from campaign_ledger import packed, sha
from studio_agent import unique_object
from studio_build_upgrade import retain
from studio_handover import safe_path
from studio_installation import load_installation, read_json
from studio_monitor_probe import inspect_idle_demo

POLICY_PATH = Path(__file__).parent/'contracts/owner_research_maintenance.json'
BINDING_KEYS = ('terminal_executable', 'terminal_data_root', 'common_files_root',
                'terminal_portable', 'controller_state_root')


def authorize(c, operation, review_id):
    """Caller holds the exclusive session and native gate. Recheck before effects."""
    policy = read_json(POLICY_PATH)
    if (policy.get('schema_version') != 1 or operation not in policy['operations']
            or not policy['not_before_utc'] <= time.time() < policy['expires_utc']):
        raise ValueError('Owner research maintenance is unavailable for this operation or time')
    install = load_installation(c.root/'installation.json')
    session = read_json(c.root/'session.json')
    if install != c.install or session != c.session:
        raise ValueError('Owner research installation or session changed')
    binding = {key: install[key] for key in BINDING_KEYS}
    binding['account'] = session['account']
    if (session['account'] != policy['account'] or session.get('demo_only') is not True
            or sha(binding) != policy['binding_sha256'] or session['run_id'] != policy['run_id']
            or install['ea_version'] != policy['ea_version']
            or install['ea_sha256'] not in policy['allowed_ea_sha256']):
        raise ValueError('Owner research account, terminal, session or build is outside the reviewed scope')
    state = c.state()
    if (state['owner'] != 'agent' or state['generation'] != policy['generation']
            or state['terminal_id'] != session['terminal_id'] or state['run_id'] != session['run_id']
            or c.store.db.execute('SELECT COUNT(*) FROM studio_state').fetchone()[0] != 1):
        raise ValueError('Owner research grant was revoked, replaced or is ambiguous')
    # Do not race a human takeover that has arrived but has not been pumped yet.
    human = safe_path(c.bridge.root/'human')
    for name in ('inbox', 'processing'):
        folder = safe_path(human/name)
        if not folder.is_dir() or any(folder.iterdir()):
            raise ValueError('Pending or unavailable human control channel; reconcile it first')
    key = packed(dict(terminal_id=c.terminal, run_id=c.run))
    row = c.store.db.execute('SELECT payload_hash,receipt FROM studio_receipts WHERE binding=? AND request_id=?',
                            (key, policy['grant_request_id'])).fetchone()
    if not row or row['payload_hash'] != policy['grant_payload_hash']:
        raise ValueError('Original human grant receipt is missing or changed')
    receipt = json.loads(row['receipt'], object_pairs_hook=unique_object)
    if (receipt.get('status') != 'applied' or receipt.get('command') != 'control.grant_agent'
            or receipt.get('execution_effect') is not False
            or receipt.get('request_id') != policy['grant_request_id']
            or receipt['state']['owner'] != 'agent' or receipt['state']['generation'] != policy['generation']
            or receipt['state']['terminal_id'] != c.terminal or receipt['state']['run_id'] != c.run):
        raise ValueError('Original human grant receipt is not the reviewed grant')
    archive = safe_path(human/'archive')
    files = list(archive.glob(policy['grant_request_id']+'.*.json'))
    if len(files) != 1:
        raise ValueError('Exactly one retained native human grant request is required')
    raw = safe_path(files[0]).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError('Retained human grant request exceeds the transport limit')
    request = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
    if (request.get('request_id') != policy['grant_request_id']
            or request.get('terminal_id') != c.terminal or request.get('run_id') != c.run
            or request.get('command') != 'control.grant_agent' or request.get('payload') != {}
            or request.get('generation') != policy['generation']-1
            or sha(dict(request=request, actor='human')) != row['payload_hash']):
        raise ValueError('Retained human grant request differs from the committed human receipt')
    observation, _ = c.runtime(require_idle=True, expected_batch_ongoing=True)
    if any(observation.get(k) != state[k] for k in ('owner', 'revision', 'generation')):
        raise ValueError('Native monitor has not confirmed the current owner grant')
    native = inspect_idle_demo(c)
    if (native.get('demo') is not True or native.get('connected') is not True
            or native.get('account_matches') is not True or native.get('algo_trading') is not False
            or native.get('positions') != 0 or native.get('orders') != 0 or native.get('tester_state') != 'idle'):
        raise ValueError('Owner research requires the same idle demo with no trading or open work')
    if c.state() != state or read_json(c.root/'session.json') != session:
        raise ValueError('Owner research state changed during native observation')
    for name in ('inbox', 'processing'):
        if any(safe_path(human/name).iterdir()):
            raise ValueError('Pending human control appeared during native observation')
    return dict(schema_version=1, operation=operation, review_id=review_id,
                policy_sha256=sha(policy), binding_sha256=sha(binding), ea_sha256=install['ea_sha256'],
                grant_request_id=policy['grant_request_id'], grant_payload_hash=row['payload_hash'],
                revocation_epoch=state['generation'], native=native,
                authorization='existing_owner_research_grant', human_confirmation_fabricated=False)


def record(c, authorization):
    """Retain exact authority separately; never alter an original rejected request."""
    directory = safe_path(c.root/'owner-research-audit')
    directory.mkdir(exist_ok=True)
    path = safe_path(directory/(authorization['operation']+'-'+authorization['review_id']+'.json'))
    retain(path, (packed(authorization)+'\n').encode('utf-8'))
