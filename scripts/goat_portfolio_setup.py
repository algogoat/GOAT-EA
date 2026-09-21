"""Explicit, hash-bound demo portfolio setup over the native mailbox. No trades.

Run on the terminal host. Uses the setup installation manifest and a reviewed
portfolio registration draft. Does not auto-retry mutations after a timeout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import goat_setup_control as setup

OPERATIONS = ('status', 'audit', 'configure', 'deploy_next', 'apply_policy')
SUCCESSES = {'status': {'observed'}, 'audit': {'observed'}, 'configure': {'configured'},
             'deploy_next': {'child_attached', 'all_attached'}, 'apply_policy': {'policy_dispatched'}}
RESULTS = {'observed', 'started', 'rejected_portfolio_mismatch', 'rejected_not_inert',
           'configured', 'configure_failed', 'rejected_ai_policy_mismatch',
           'rejected_partial_deployment', 'all_attached', 'child_attached',
           'child_attach_failed', 'policy_dispatched', 'policy_not_dispatched'}


def read_bounded(path):
    path = Path(path)
    if path.name.lower() == 'api-bearer.token' or path.is_symlink():
        raise ValueError('unsafe input')
    with path.open('rb') as handle:
        raw = handle.read(131073)
    if not 0 < len(raw) <= 131072:
        raise ValueError('invalid size')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=setup.unique_object)
    if type(value) is not dict:
        raise ValueError('object required')
    return value, hashlib.sha256(raw).hexdigest()


def validate_registration(value, installation, check_files=True):
    fields = {'schema', 'account', 'server', 'directory', 'buildId', 'expiresAtUtc',
              'aiMode', 'aiThreshold', 'aiProtocol', 'exposureMode', 'members'}
    if set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid registration schema')
    for key in ('account', 'server', 'directory', 'buildId'):
        if value[key] != installation[key]:
            raise ValueError('identity mismatch')
    for key in ('account', 'expiresAtUtc', 'aiMode', 'aiThreshold', 'aiProtocol', 'exposureMode'):
        if type(value[key]) is not int:
            raise ValueError('invalid numeric value')
    if not time.time() < value['expiresAtUtc'] <= time.time() + 14400:
        raise ValueError('registration expired or too long')
    if value['aiMode'] not in (0, 2) or value['aiProtocol'] != 2 or value['exposureMode'] not in (0, 1) or not 1 <= value['aiThreshold'] <= 100:
        raise ValueError('unsupported experiment policy')
    if type(value['members']) is not list or not 1 <= len(value['members']) <= 100:
        raise ValueError('invalid member count')
    common = Path(installation['commonFiles']).resolve()
    paths = set()
    for index, member in enumerate(value['members']):
        if type(member) is not dict or set(member) != {'index', 'path', 'symbol', 'sha256'} or type(member['index']) is not int or member['index'] != index:
            raise ValueError('invalid member')
        path = Path(member['path'])
        if not path.is_absolute() or path.suffix.lower() != '.set' or path.is_symlink() or '..' in path.parts:
            raise ValueError('unsafe member path')
        resolved = path.resolve()
        if not resolved.is_relative_to(common) or resolved in paths:
            raise ValueError('member path is outside Common Files or duplicated')
        paths.add(resolved)
        if not isinstance(member['symbol'], str) or not member['symbol'] or any(ord(c) < 33 for c in member['symbol']):
            raise ValueError('invalid symbol')
        if not isinstance(member['sha256'], str) or not setup.re.fullmatch('[a-f0-9]{64}', member['sha256']):
            raise ValueError('invalid digest')
        if check_files:
            with path.open('rb') as handle:
                raw = handle.read(2000001)
            if not 0 < len(raw) <= 2000000 or hashlib.sha256(raw).hexdigest() != member['sha256']:
                raise ValueError('member hash mismatch')


def context(manifest):
    installation, _ = setup.scope(manifest)
    root = Path(installation['commonFiles']) / 'GOAT/AgentPortfolio' / Path(installation['directory']).name
    return installation, root


def register(manifest, draft):
    installation, root = context(manifest)
    value, _ = read_bounded(draft)
    value['expiresAtUtc'] = int(time.time()) + 14400
    validate_registration(value, installation)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / 'producer.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        if (root / 'registration.json').exists():
            previous, digest = read_bounded(root / 'registration.json')
            if {k: v for k, v in previous.items() if k != 'expiresAtUtc'} != {k: v for k, v in value.items() if k != 'expiresAtUtc'}:
                raise ValueError('registration scope change requires separate review')
        else:
            digest = None
        if (root / 'request.json').exists():
            retained_request, _ = read_bounded(root / 'request.json')
            validate_request(retained_request)
            if retained_request['registrationSha256'] != digest:
                raise ValueError('retained request scope mismatch')
            old_receipt, _ = read_bounded(root / (retained_request['id'] + '.json'))
            verify_receipt(old_receipt, retained_request, installation, value['members'])
            if old_receipt['result'] == 'started':
                raise ValueError('unresolved deployment intent')
            setup.sharing_retry(lambda: (root / 'request.json').rename(root / (retained_request['id'] + '.request.json')))
        setup.atomic(root / 'registration.json', value)
    finally:
        os.close(fd)
        setup.sharing_retry(lock.unlink)
    return {'result': 'registered', 'members': len(value['members']), 'expiresAtUtc': value['expiresAtUtc']}


def validate_request(value):
    if set(value) != {'schema', 'id', 'action', 'registrationSha256', 'expiresAtUtc'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid retained request')
    if not isinstance(value['id'], str) or not setup.re.fullmatch('[a-f0-9]{32}', value['id']) or value['action'] not in OPERATIONS:
        raise ValueError('invalid request identity')
    if not isinstance(value['registrationSha256'], str) or not setup.re.fullmatch('[a-f0-9]{64}', value['registrationSha256']) or type(value['expiresAtUtc']) is not int:
        raise ValueError('invalid request binding')


def verify_receipt(value, request, installation, members):
    fields = {'schema', 'id', 'action', 'registrationSha256', 'result', 'account', 'server',
              'directory', 'buildId', 'observedAtUtc', 'connected', 'tradingAllowed', 'positions',
              'orders', 'aiMode', 'aiThreshold', 'aiProtocol', 'commandId', 'commandPending', 'brokerTime', 'rows'}
    if set(value) != fields or value.get('result') not in RESULTS:
        raise ValueError('invalid receipt schema')
    if value['schema'] != 1 or any(value[k] != request[k] for k in ('id', 'action', 'registrationSha256')):
        raise ValueError('receipt request mismatch')
    if any(value[k] != installation[k] for k in ('account', 'server', 'directory', 'buildId')):
        raise ValueError('receipt host mismatch')
    for key in ('connected', 'tradingAllowed', 'commandPending'):
        if type(value[key]) is not bool:
            raise ValueError('invalid flags')
    for key in ('schema', 'account', 'observedAtUtc', 'brokerTime', 'positions', 'orders', 'aiMode', 'aiThreshold', 'aiProtocol', 'commandId'):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError('invalid numbers')
    if type(value['rows']) is not list or len(value['rows']) != len(members):
        raise ValueError('incomplete portfolio')
    row_fields = {'index', 'symbol', 'chartId', 'magic', 'linkedFresh', 'settingsMatch', 'exposureMode', 'ackId', 'ackStatus',
                  'AI_MODE', 'AI_PROTOCOL', 'AI_THRESHOLD', 'AI_SCOPE', 'AI_VERIFIED', 'AI_AVAILABLE', 'AI_AT', 'EA_TRADE_ALLOWED'}
    for index, row in enumerate(value['rows']):
        if type(row) is not dict or set(row) != row_fields or row['index'] != index or type(row['linkedFresh']) is not bool:
            raise ValueError('invalid row schema')
        if row['symbol'] != members[index]['symbol'] or type(row['settingsMatch']) is not bool:
            raise ValueError('invalid row symbol')
        for key in row_fields - {'symbol', 'linkedFresh', 'settingsMatch'}:
            if row[key] is None and (key.startswith('AI_') or key == 'EA_TRADE_ALLOWED'):
                continue
            if type(row[key]) is not int:
                raise ValueError('invalid row number')
    return value


def verify_ready(value, registration, now=None):
    now = time.time() if now is None else now
    if value['action'] != 'audit' or value['result'] != 'observed' or not 0 <= now-value['observedAtUtc'] <= 30:
        raise ValueError('fresh native settings audit required')
    if not value['connected'] or value['tradingAllowed'] or value['positions'] or value['orders'] or value['commandPending']:
        raise ValueError('inert connected state required')
    if any(value[k] != registration[k] for k in ('aiMode', 'aiThreshold', 'aiProtocol')) or value['commandId'] <= 0:
        raise ValueError('policy not applied')
    charts, magics = set(), set()
    for row in value['rows']:
        if not row['linkedFresh'] or not row['settingsMatch'] or row['EA_TRADE_ALLOWED'] != 1 or row['chartId'] <= 0 or row['magic'] <= 0 or row['chartId'] in charts or row['magic'] in magics:
            raise ValueError('child identity/settings unverified')
        charts.add(row['chartId']); magics.add(row['magic'])
        if row['exposureMode'] != registration['exposureMode'] or row['ackId'] != value['commandId'] or row['ackStatus'] != 1:
            raise ValueError('exposure acknowledgement incomplete')
        expected_mode = 2 if registration['aiMode'] == 2 else 1
        if row['AI_MODE'] != expected_mode or row['AI_PROTOCOL'] != 2 or row['AI_THRESHOLD'] != registration['aiThreshold'] or row['AI_SCOPE'] != 0:
            raise ValueError('effective child AI policy mismatch')
        if expected_mode == 2 and (row['AI_VERIFIED'] != 1 or row['AI_AT'] is None or not 0 <= now-row['AI_AT'] <= 30):
            raise ValueError('fresh verified AI feed required')
    return True


def request(manifest, action, timeout=60):
    if action not in OPERATIONS or not 1 <= timeout <= 90:
        raise ValueError('invalid command')
    installation, root = context(manifest)
    lock = root / 'producer.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        registration, digest = read_bounded(root / 'registration.json')
        validate_registration(registration, installation)
        pending = root / 'request.json'
        if pending.exists():
            previous, _ = read_bounded(pending)
            validate_request(previous)
            if previous['registrationSha256'] != digest:
                raise ValueError('retained request scope mismatch')
            retained, _ = read_bounded(root / (previous['id'] + '.json'))
            verify_receipt(retained, previous, installation, registration['members'])
            if retained['result'] == 'started':
                raise ValueError('unresolved deployment intent')
            pending.rename(root / (previous['id'] + '.request.json'))
        envelope = {'schema': 1, 'id': uuid.uuid4().hex, 'action': action,
                    'registrationSha256': digest, 'expiresAtUtc': int(time.time()) + 120}
        setup.atomic(pending, envelope)
        receipt = root / (envelope['id'] + '.json')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if receipt.exists():
                value, _ = read_bounded(receipt)
                result = verify_receipt(value, envelope, installation, registration['members'])
                if result['result'] != 'started':
                    if not 0 <= time.time() - result['observedAtUtc'] <= timeout + 5:
                        raise ValueError('stale or future receipt')
                    return result
            time.sleep(.25)
        return {'result': 'receipt_timeout', 'id': envelope['id'], 'requestRetained': True}
    finally:
        os.close(fd)
        setup.sharing_retry(lock.unlink)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('register',) + OPERATIONS)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--draft')
    args = parser.parse_args()
    try:
        if args.operation == 'register' and not args.draft:
            raise ValueError('draft required')
        result = register(args.manifest, args.draft) if args.operation == 'register' else request(args.manifest, args.operation)
        print(json.dumps(result))
        return 0 if result['result'] == 'registered' or result['result'] in SUCCESSES.get(args.operation, set()) else 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'result': 'portfolio_setup_error', 'action': args.operation}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
