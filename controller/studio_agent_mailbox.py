"""Controller client for the EA's two local Common Files mailboxes. No trades, no credentials.

Ported from the reviewed VPS clients scripts/goat_setup_control.py (GOATSetupControl.mqh:
status, inert shutdown, 15-minute pairing read) and scripts/goat_portfolio_setup.py
(GOATPortfolioSetupControl.mqh: hash-bound demo dashboard rows). The installed bundle ships
controller/ only, so the protocol lives here; the scripts remain the VPS tools.

The EA answers only on a connected demo account (ACCOUNT_TRADE_MODE_DEMO) for the exact
terminal directory, broker account, server and compiled build ID. A receipt is evidence
of what the EA observed, never proof that a requested shutdown has completed.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

CREDENTIAL_NAME = re.compile(r'api-bearer(?:-[A-Za-z0-9_-]+)?\.token(?:\.pending)?', re.I)
BUILD_ID = re.compile(r'[A-Za-z0-9._:-]{8,96}')
PAIRING_REGISTRATION_SECONDS = 300  # The EA refuses a pairing registration above 900 s.
STATUS_REGISTRATION_SECONDS = 120


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate mailbox field')
        result[key] = value
    return result


SHARING_RETRY_ATTEMPTS = 40  # About one second in total: an EA read of a small mailbox file is far shorter.


def sharing_retry(operation, *, attempts=SHARING_RETRY_ATTEMPTS, sleep=time.sleep):
    # A native atomic move, an EA reading the same file, or a terminal exit can briefly
    # deny a Windows share. Retry only that condition, never by issuing another native request.
    for attempt in range(attempts):
        try:
            return operation()
        except OSError as error:
            if getattr(error, 'winerror', None) not in (32, 33) or attempt == attempts - 1:
                raise
            sleep(0.025)


def read_bounded(path, limit=16384):
    path = Path(path)
    if CREDENTIAL_NAME.fullmatch(path.name) or path.is_symlink():
        raise ValueError('Mailbox refuses credential or linked files')
    def bounded():
        with path.open('rb') as handle:
            return handle.read(limit + 1)
    raw = sharing_retry(bounded)
    if not 0 < len(raw) <= limit:
        raise ValueError('Mailbox file is empty or oversized')
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
    if type(value) is not dict:
        raise ValueError('Mailbox object required')
    return value, hashlib.sha256(raw).hexdigest()


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    with temporary.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, separators=(',', ':'))
        handle.flush()
        os.fsync(handle.fileno())
    sharing_retry(lambda: os.replace(temporary, path))


@contextmanager
def producer_lock(root):
    """One producer per mailbox; the native receipt ID is the replay protection."""
    lock = Path(root) / 'producer.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('Another GOAT mailbox client is active for this terminal; retry after it finishes') from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        sharing_retry(lock.unlink)


def identity(controller, session, build_id):
    """Exact native identity the EA compares against its own runtime values."""
    if not isinstance(build_id, str) or not BUILD_ID.fullmatch(build_id):
        raise ValueError('The exact installed GOAT build ID is required')
    account = session.get('account') if isinstance(session, dict) else None
    if session.get('demo_only') is not True or not isinstance(account, dict) or set(account) != {'login', 'server'}:
        raise ValueError('The controller binding must be an exact demo login and server')
    if not re.fullmatch(r'[1-9][0-9]{3,19}', str(account['login'])) or not isinstance(account['server'], str) or not account['server']:
        raise ValueError('The controller binding must be an exact demo login and server')
    directory = str(Path(controller.install['terminal_data_root']).resolve())
    return dict(account=int(account['login']), server=account['server'], directory=directory, buildId=build_id)


def setup_root(controller):
    return Path(controller.install['common_files_root']) / 'GOAT' / 'AgentSetup' / Path(controller.install['terminal_data_root']).name


def portfolio_root(controller):
    return Path(controller.install['common_files_root']) / 'GOAT' / 'AgentPortfolio' / Path(controller.install['terminal_data_root']).name


# ------------------------------------------------------------------ setup mailbox

SETUP_RESULTS = ('observed', 'shutdown_requested', 'rejected_envelope', 'rejected_not_inert',
                 'pairing_available', 'pairing_unavailable', 'pairing_consumed')
PAIRING_FIELDS = ('userCode', 'activationId', 'pairingExpiresAtMs', 'responseExpiresAtUtc')


def setup_receipt(value, request_id, ident, *, pairing=False, fresh=False, now=None):
    fields = {'schema', 'id', 'result', 'account', 'server', 'directory', 'buildId', 'observedAtUtc',
              'connected', 'tradingAllowed', 'activationOnly', 'positions', 'orders', 'charts'}
    if value.get('result') == 'pairing_available':
        if not pairing:
            raise ValueError('Unexpected pairing payload in an ordinary receipt')
        fields |= set(PAIRING_FIELDS)
        if not isinstance(value.get('userCode'), str) or not re.fullmatch(r'[A-Z2-9]{4}-[A-Z2-9]{4}', value['userCode']):
            raise ValueError('Invalid pairing code')
        if not isinstance(value.get('activationId'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', value['activationId']):
            raise ValueError('Invalid pairing identity')
        expiry, response_expiry, observed = value.get('pairingExpiresAtMs'), value.get('responseExpiresAtUtc'), value.get('observedAtUtc')
        if type(expiry) is not int or type(response_expiry) is not int or type(observed) is not int:
            raise ValueError('Invalid pairing expiry')
        if not observed < response_expiry <= min(observed + 60, expiry // 1000) or not observed * 1000 < expiry <= (observed + 900) * 1000:
            raise ValueError('Invalid pairing lifetime')
        current = time.time() if now is None else now
        if fresh and not observed <= current < response_expiry:
            raise ValueError('Stale pairing payload')
        if (value.get('connected') is not True or value.get('tradingAllowed') is not False
                or value.get('activationOnly') is not True or value.get('positions') != 0 or value.get('orders') != 0):
            raise ValueError('Pairing is not inert')
    if set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid setup receipt schema')
    if (value['id'] != request_id or any(value[k] != ident[k] for k in ('account', 'server', 'buildId'))
            or os.path.normcase(value['directory']) != os.path.normcase(ident['directory'])):
        raise ValueError('Setup receipt identity mismatch')
    if value['result'] not in SETUP_RESULTS:
        raise ValueError('Invalid setup receipt result')
    for key in ('connected', 'tradingAllowed', 'activationOnly'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid setup receipt flags')
    for key in ('account', 'observedAtUtc', 'positions', 'orders', 'charts'):
        if type(value[key]) is not int or not 0 <= value[key] <= 2 ** 53:
            raise ValueError('Invalid setup receipt numbers')
    return {key: value[key] for key in fields}


def consume_pairing(path, value):
    tombstone = {key: item for key, item in value.items() if key not in PAIRING_FIELDS}
    tombstone['result'] = 'pairing_consumed'
    atomic(path, tombstone)


def verify_pairing_temporaries(root, request_id, ident):
    for index, path in enumerate(Path(root).glob(request_id + '.json.*.pending')):
        if index >= 16:
            raise ValueError('Too many retained receipt temporaries; inspect the mailbox')
        if not re.fullmatch(re.escape(request_id) + r'\.json\.\d{1,20}(?:\.\d{1,20}\.\d{1,20})?\.pending', path.name) or path.is_symlink():
            raise ValueError('Unknown receipt temporary retained')
        value, _ = read_bounded(path)
        if setup_receipt(value, request_id, ident, pairing=True)['result'] != 'pairing_consumed':
            raise ValueError('A receipt temporary awaits native expiry cleanup')


REGISTRATION_IDENTITY = ('account', 'server', 'buildId', 'directory')
EXPIRY_GRACE_SECONDS = 5  # The same skew allowance a retained request gets before it counts as expired.


def _expired(value, now):
    return type(value.get('expiresAtUtc')) is int and value['expiresAtUtc'] + EXPIRY_GRACE_SECONDS < now


def _supersede_expired(root, path, digest, now):
    """Archive an expired registration for another identity (for example an older build).

    The EA rejects an expired registration, so it can no longer authorize anything; it is
    renamed, never deleted, to ``<sha256>.expired.registration.json`` beside the expired
    requests. Its own retained request is retired first under its own identity, exactly as
    that build's next request would have (a still-live one refuses). Runs under the producer
    lock and re-reads the registration, so a concurrent rewrite is never archived blind.
    """
    old, current = read_bounded(path)
    if current != digest or not _expired(old, now):
        raise ValueError('The retained GOAT setup registration changed while it was inspected; inspect before replacing it')
    if any(key not in old for key in REGISTRATION_IDENTITY):
        raise ValueError('A malformed GOAT setup registration is retained for this terminal; inspect before replacing it')
    archived = root / (digest + '.expired.registration.json')
    if archived.exists():
        raise ValueError('Setup registration archive already exists; inspect retained state')
    _retire_retained(root, {key: old[key] for key in REGISTRATION_IDENTITY}, now=now)
    sharing_retry(lambda: path.rename(archived))
    return dict(sha256=digest, buildId=old.get('buildId'), account=old.get('account'), server=old.get('server'),
                expiresAtUtc=old['expiresAtUtc'], archivedAs=archived.name)


def setup_register(controller, ident, *, allow_pairing=False):
    """Register this build's setup capability. Returns ``(record, superseded)``.

    ``superseded`` is None, or the sha256 and archive name of an expired registration for
    another identity (an older build, typically) that this one replaced. A live registration
    for another identity still refuses: only expiry makes it replaceable.
    """
    root = setup_root(controller)
    root.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    seconds = PAIRING_REGISTRATION_SECONDS if allow_pairing else STATUS_REGISTRATION_SECONDS
    record = dict(schema=1, account=ident['account'], server=ident['server'], directory=ident['directory'],
                  buildId=ident['buildId'], expiresAtUtc=now + seconds)
    if allow_pairing:
        record.update(schema=2, allowPairingRead=True)
    path = root / 'registration.json'
    if path.exists():
        old, digest = read_bounded(path)
        if any(old.get(key) != record[key] for key in REGISTRATION_IDENTITY):
            if not _expired(old, now):
                raise ValueError('A different GOAT setup registration is retained for this terminal; inspect before replacing it')
            with producer_lock(root):
                superseded = _supersede_expired(root, path, digest, now)
                atomic(path, record)
            return record, superseded
    atomic(path, record)
    return record, None


def _retire_retained(root, ident, *, now):
    pending = root / 'request.json'
    if not pending.exists():
        return
    old, _ = read_bounded(pending)
    previous = old.get('id', '')
    if not isinstance(previous, str) or not re.fullmatch(r'[a-f0-9]{32}', previous):
        raise ValueError('Unidentified setup request retained; do not overwrite or repeat it')
    receipt = root / (previous + '.json')
    if receipt.exists():
        value, _ = read_bounded(receipt)
        retained = setup_receipt(value, previous, ident, pairing=True)
        if retained['result'] == 'pairing_available':
            consume_pairing(receipt, retained)
    elif not (type(old.get('expiresAtUtc')) is int and old['expiresAtUtc'] + 5 < now):
        raise ValueError('An unanswered setup request is still live; wait for it to expire before another request')
    # An unanswered, expired request can never be executed by the EA (it rejects
    # expired envelopes); retiring it is safe once no pairing temporary remains.
    verify_pairing_temporaries(root, previous, ident)
    archived = root / (previous + ('.request.json' if receipt.exists() else '.expired.request.json'))
    if archived.exists():
        raise ValueError('Setup request archive already exists; inspect retained state')
    sharing_retry(lambda: pending.rename(archived))


def setup_request(controller, ident, action, *, timeout=30, clock=time.monotonic, sleep=time.sleep):
    if action not in ('status', 'shutdown', 'pairing') or not 1 <= timeout <= 60:
        raise ValueError('Unsupported setup action or timeout')
    root = setup_root(controller)
    registration, _ = read_bounded(root / 'registration.json')
    if registration.get('expiresAtUtc', 0) < time.time():
        raise ValueError('Setup registration expired')
    if any(registration.get(key) != ident[key] for key in ('account', 'server', 'buildId', 'directory')):
        raise ValueError('Setup registration mismatch')
    if action == 'pairing' and (registration.get('schema') != 2 or registration.get('allowPairingRead') is not True):
        raise ValueError('Pairing read was not registered')
    with producer_lock(root):
        _retire_retained(root, ident, now=time.time())
        request_id = uuid.uuid4().hex
        # Short request life: an envelope nobody answered expires within seconds,
        # so a later EA host can never act on a stale close.
        envelope = dict(schema=2 if action == 'pairing' else 1, id=request_id, account=ident['account'],
                        server=ident['server'], directory=ident['directory'], buildId=ident['buildId'],
                        expiresAtUtc=int(time.time()) + timeout + 5, action=action)
        atomic(root / 'request.json', envelope)
        receipt = root / (request_id + '.json')
        deadline = clock() + timeout
        while clock() < deadline:
            if receipt.exists():
                value, _ = read_bounded(receipt)
                result = setup_receipt(value, request_id, ident, pairing=action == 'pairing')
                if result['result'] == 'pairing_available':
                    consume_pairing(receipt, result)
                    # A valid but expired challenge is scrubbed before the error.
                    setup_receipt(result, request_id, ident, pairing=True, fresh=True)
                return result
            sleep(0.25)
        return dict(id=request_id, result='receipt_timeout', requestRetained=True)


def setup_retire(controller, ident, request_id, *, grace=1.5, sleep=time.sleep):
    """Withdraw one unanswered request so no EA host can act on it later.

    Returns the EA's validated receipt when it answered before or during the withdrawal
    (an EA mid-poll finishes within one timer tick), otherwise None.
    """
    root = setup_root(controller)
    receipt = root / (request_id + '.json')
    def answered():
        if not receipt.exists():
            return None
        value, _ = read_bounded(receipt)
        result = setup_receipt(value, request_id, ident, pairing=True)
        if result['result'] == 'pairing_available':
            consume_pairing(receipt, result)
        return result
    with producer_lock(root):
        early = answered()
        if early is not None:
            return early
        pending = root / 'request.json'
        if pending.exists():
            current, _ = read_bounded(pending)
            if current.get('id') == request_id:
                archived = root / (request_id + '.withdrawn.request.json')
                if archived.exists():
                    raise ValueError('Withdrawn request archive already exists; inspect retained state')
                sharing_retry(lambda: pending.rename(archived))
    sleep(grace)
    return answered()


# -------------------------------------------------------------- portfolio mailbox

PORTFOLIO_ACTIONS = ('status', 'audit', 'configure', 'deploy_next', 'apply_policy')
PORTFOLIO_RESULTS = {'observed', 'started', 'rejected_portfolio_mismatch', 'rejected_not_inert',
                     'configured', 'configure_failed', 'rejected_ai_policy_mismatch',
                     'rejected_partial_deployment', 'all_attached', 'child_attached',
                     'child_attach_failed', 'policy_dispatched', 'policy_not_dispatched'}
REGISTRATION_SECONDS = 14400
ROW_FIELDS = {'index', 'symbol', 'chartId', 'magic', 'linkedFresh', 'settingsMatch', 'exposureMode', 'ackId', 'ackStatus',
              'AI_MODE', 'AI_PROTOCOL', 'AI_THRESHOLD', 'AI_SCOPE', 'AI_VERIFIED', 'AI_AVAILABLE', 'AI_AT', 'EA_TRADE_ALLOWED'}


def validate_portfolio_registration(value, ident, common_files, *, check_files=True):
    fields = {'schema', 'account', 'server', 'directory', 'buildId', 'expiresAtUtc',
              'aiMode', 'aiThreshold', 'aiProtocol', 'exposureMode', 'members'}
    if set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid portfolio registration schema')
    for key in ('account', 'server', 'directory', 'buildId'):
        if value[key] != ident[key]:
            raise ValueError('Portfolio registration identity mismatch')
    for key in ('account', 'expiresAtUtc', 'aiMode', 'aiThreshold', 'aiProtocol', 'exposureMode'):
        if type(value[key]) is not int:
            raise ValueError('Invalid portfolio registration number')
    if not time.time() < value['expiresAtUtc'] <= time.time() + REGISTRATION_SECONDS:
        raise ValueError('Portfolio registration expired or too long')
    if value['aiMode'] not in (0, 2) or value['aiProtocol'] != 2 or value['exposureMode'] not in (0, 1) or not 1 <= value['aiThreshold'] <= 100:
        raise ValueError('Unsupported dashboard policy')
    if type(value['members']) is not list or not 1 <= len(value['members']) <= 100:
        raise ValueError('A portfolio needs 1 to 100 members')
    common = Path(common_files).resolve()
    seen = set()
    for index, member in enumerate(value['members']):
        if type(member) is not dict or set(member) != {'index', 'path', 'symbol', 'sha256'} or member['index'] != index:
            raise ValueError('Invalid portfolio member')
        path = Path(member['path'])
        if not path.is_absolute() or path.suffix.lower() != '.set' or path.is_symlink() or '..' in path.parts or '/' in member['path']:
            raise ValueError('Unsafe portfolio member path')
        resolved = path.resolve()
        if not resolved.is_relative_to(common) or resolved in seen:
            raise ValueError('Portfolio member path is outside Common Files or duplicated')
        seen.add(resolved)
        if not isinstance(member['symbol'], str) or not member['symbol'] or any(ord(c) < 33 for c in member['symbol']):
            raise ValueError('Invalid portfolio member symbol')
        if not isinstance(member['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', member['sha256']):
            raise ValueError('Invalid portfolio member digest')
        if check_files:
            with path.open('rb') as handle:
                raw = handle.read(2000001)
            if not 0 < len(raw) <= 2000000 or hashlib.sha256(raw).hexdigest() != member['sha256']:
                raise ValueError('Portfolio member SET bytes differ from their registered hash')


def validate_portfolio_request(value):
    if set(value) != {'schema', 'id', 'action', 'registrationSha256', 'expiresAtUtc'} or value.get('schema') != 1:
        raise ValueError('Invalid retained portfolio request')
    if not isinstance(value['id'], str) or not re.fullmatch('[a-f0-9]{32}', value['id']) or value['action'] not in PORTFOLIO_ACTIONS:
        raise ValueError('Invalid retained portfolio request identity')
    if not isinstance(value['registrationSha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['registrationSha256']) or type(value['expiresAtUtc']) is not int:
        raise ValueError('Invalid retained portfolio request binding')


def portfolio_receipt(value, request, ident, members):
    fields = {'schema', 'id', 'action', 'registrationSha256', 'result', 'account', 'server',
              'directory', 'buildId', 'observedAtUtc', 'connected', 'tradingAllowed', 'positions',
              'orders', 'aiMode', 'aiThreshold', 'aiProtocol', 'commandId', 'commandPending', 'brokerTime', 'rows'}
    if set(value) != fields or value.get('result') not in PORTFOLIO_RESULTS:
        raise ValueError('Invalid portfolio receipt schema')
    if value['schema'] != 1 or any(value[k] != request[k] for k in ('id', 'action', 'registrationSha256')):
        raise ValueError('Portfolio receipt request mismatch')
    if any(value[k] != ident[k] for k in ('account', 'server', 'buildId')) or os.path.normcase(value['directory']) != os.path.normcase(ident['directory']):
        raise ValueError('Portfolio receipt host mismatch')
    for key in ('connected', 'tradingAllowed', 'commandPending'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid portfolio receipt flags')
    for key in ('schema', 'account', 'observedAtUtc', 'brokerTime', 'positions', 'orders', 'aiMode', 'aiThreshold', 'aiProtocol', 'commandId'):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError('Invalid portfolio receipt numbers')
    if type(value['rows']) is not list or len(value['rows']) != len(members):
        raise ValueError('The dashboard reports a different number of portfolio rows')
    for index, row in enumerate(value['rows']):
        if type(row) is not dict or set(row) != ROW_FIELDS or row['index'] != index or type(row['linkedFresh']) is not bool:
            raise ValueError('Invalid portfolio row schema')
        if row['symbol'] != members[index]['symbol'] or type(row['settingsMatch']) is not bool:
            raise ValueError('The dashboard row symbol differs from the registered member')
        for key in ROW_FIELDS - {'symbol', 'linkedFresh', 'settingsMatch'}:
            if row[key] is None and (key.startswith('AI_') or key == 'EA_TRADE_ALLOWED'):
                continue
            if type(row[key]) is not int:
                raise ValueError('Invalid portfolio row number')
    return value


def portfolio_register(controller, ident, value):
    root = portfolio_root(controller)
    validate_portfolio_registration(value, ident, controller.install['common_files_root'])
    root.mkdir(parents=True, exist_ok=True)
    with producer_lock(root):
        digest = None
        if (root / 'registration.json').exists():
            previous, digest = read_bounded(root / 'registration.json', 131072)
            if {k: v for k, v in previous.items() if k != 'expiresAtUtc'} != {k: v for k, v in value.items() if k != 'expiresAtUtc'}:
                raise ValueError('A different dashboard portfolio registration is retained; stop that deployment first')
        if (root / 'request.json').exists():
            retained, _ = read_bounded(root / 'request.json')
            validate_portfolio_request(retained)
            if retained['registrationSha256'] != digest:
                raise ValueError('Retained portfolio request belongs to another registration')
            receipt = root / (retained['id'] + '.json')
            if not receipt.exists():
                if retained['expiresAtUtc'] + 5 >= time.time():
                    raise ValueError('An unanswered portfolio request is still live; wait for it to expire')
                archived = root / (retained['id'] + '.expired.request.json')
            else:
                old, _ = read_bounded(receipt, 131072)
                portfolio_receipt(old, retained, ident, value['members'])
                if old['result'] == 'started':
                    raise ValueError('An unresolved dashboard mutation is retained; inspect deploy-status before continuing')
                archived = root / (retained['id'] + '.request.json')
            sharing_retry(lambda: (root / 'request.json').rename(archived))
        atomic(root / 'registration.json', value)
    _, digest = read_bounded(root / 'registration.json', 131072)
    return digest


def portfolio_request(controller, ident, action, *, timeout=60, clock=time.monotonic, sleep=time.sleep):
    if action not in PORTFOLIO_ACTIONS or not 1 <= timeout <= 90:
        raise ValueError('Invalid dashboard command')
    root = portfolio_root(controller)
    with producer_lock(root):
        registration, digest = read_bounded(root / 'registration.json', 131072)
        validate_portfolio_registration(registration, ident, controller.install['common_files_root'])
        pending = root / 'request.json'
        if pending.exists():
            previous, _ = read_bounded(pending)
            validate_portfolio_request(previous)
            if previous['registrationSha256'] != digest:
                raise ValueError('Retained portfolio request belongs to another registration')
            receipt = root / (previous['id'] + '.json')
            if receipt.exists():
                retained, _ = read_bounded(receipt, 131072)
                portfolio_receipt(retained, previous, ident, registration['members'])
                if retained['result'] == 'started':
                    raise ValueError('An unresolved dashboard mutation is retained; inspect deploy-status before continuing')
                sharing_retry(lambda: pending.rename(root / (previous['id'] + '.request.json')))
            elif previous['expiresAtUtc'] + 5 < time.time():
                sharing_retry(lambda: pending.rename(root / (previous['id'] + '.expired.request.json')))
            else:
                raise ValueError('An unanswered portfolio request is still live; wait for it to expire')
        envelope = dict(schema=1, id=uuid.uuid4().hex, action=action, registrationSha256=digest,
                        expiresAtUtc=int(time.time()) + min(timeout + 5, 120))
        atomic(pending, envelope)
        receipt = root / (envelope['id'] + '.json')
        deadline = clock() + timeout
        while clock() < deadline:
            if receipt.exists():
                value, _ = read_bounded(receipt, 131072)
                result = portfolio_receipt(value, envelope, ident, registration['members'])
                if result['result'] != 'started':
                    if not 0 <= time.time() - result['observedAtUtc'] <= timeout + 5:
                        raise ValueError('Stale or future dashboard receipt')
                    return result
            sleep(0.25)
        return dict(result='receipt_timeout', id=envelope['id'], requestRetained=True)
