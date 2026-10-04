"""Held-out lock: the controller half of library scoring v1, phase 1 (goatai#2221 §4).

The desktop declares one lock per strategy key (inherited by forks) in
``<evidence_root>/heldout/locks.jsonl``. The controller never writes that file. On
every check it reads it and verifies the whole hash chain; a missing file means no
lock was ever declared, while an unreadable file or a broken chain refuses every
prepare and start and redacts every reported metric (HELDOUT_REGISTRY_UNAVAILABLE).

Registry line format (one canonical JSON object per line, UTF-8, ``\\n`` ended)::

    {"at":<instant>,"hash":<sha256>,"lock":{...},"op":<op>,"prev":<sha256>,"ref":<lockId>,"seq":<n>}

* ``seq`` counts from 0; ``prev`` is the previous line's ``hash`` (64 zeros first).
* ``hash = sha256(prev || canonical(line without hash))``, where ``canonical`` is the
  desktop's (sorted keys, no whitespace, non-ASCII kept), and every line must be
  byte-identical to ``canonical(line)``: any changed byte breaks the chain.
* Numbers are integers only, so JavaScript and Python serialise them identically.
* ``op`` is one of declare, freeze, reveal, revealed, breach; ``ref`` is the lockId.
* declare: ``lock = {lockId, strategyKey, start, end, revealableAfter, ...}`` with
  broker days, half-open ``[start, end)``; ``lockId = sha256(canonical(lock without
  lockId))``. A key with an active lock cannot declare another.
* freeze: ``{lockId, cells:[{symbol, timeframe, setSha256}]}`` (re-freezable).
* reveal: ``{lockId}`` once frozen (the candidate is fixed: ``revealing``).
* revealed: ``{lockId}`` after a reveal. breach: ``{lockId, reason?, recordId?}``.

Active statuses are ``locked`` (prospective: waits for its window to close),
``revealable`` and ``revealing``; ``revealed`` and ``breached`` locks no longer bind.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re

SCHEMA = 'goat-heldout-lock-v1'
CAPABILITY = 'heldout_enforcement'
GENESIS = '0' * 64
OPS = ('declare', 'freeze', 'reveal', 'revealed', 'breach')
ACTIVE = frozenset(('locked', 'revealable', 'revealing'))
LINE_KEYS = frozenset(('seq', 'at', 'op', 'ref', 'lock', 'prev', 'hash'))
MAX_BYTES = 16 * 1024 * 1024
SHA = re.compile('[a-f0-9]{64}')
ID = re.compile('[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
INSTANT = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z')

UNAVAILABLE = 'HELDOUT_REGISTRY_UNAVAILABLE'
LOCKED = 'HELDOUT_LOCKED_WINDOW'
UNATTRIBUTED = 'HELDOUT_UNATTRIBUTED_MEMBER'
REVEAL_MISMATCH = 'HELDOUT_REVEAL_MISMATCH'
ALREADY_REVEALED = 'HELDOUT_ALREADY_REVEALED'
INVALID_REF = 'HELDOUT_INVALID_STRATEGY_REF'


class HeldOutRefused(ValueError):
    """A refusal with a stable code, a plain sentence and the lock windows involved."""

    def __init__(self, code, plain, locked_windows=()):
        super().__init__(code + ': ' + plain)
        self.code, self.plain, self.locked_windows = code, plain, list(locked_windows)


def canonical(value):
    """The desktop's canonical(): JSON.stringify with sorted keys and no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def chain_hash(prev, entry):
    return hashlib.sha256((prev + canonical(entry)).encode('utf-8')).hexdigest()


def lock_id(payload):
    return hashlib.sha256(canonical({k: v for k, v in payload.items() if k != 'lockId'}).encode('utf-8')).hexdigest()


def day(text):
    if not isinstance(text, str) or not DAY.fullmatch(text):
        raise ValueError('broker day YYYY-MM-DD required')
    return date.fromisoformat(text)


def iso_day(value):
    """A broker day from a controller date: YYYY.MM.DD, YYYY-MM-DD or a date."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}[.-]\d{2}[.-]\d{2}', value.strip()[:10]):
        return date.fromisoformat(value.strip()[:10].replace('.', '-'))
    return None


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open day ranges [a_start, a_end) and [b_start, b_end) share a day."""
    return a_start < b_end and b_start < a_end


def _integers_only(value, where='lock'):
    if isinstance(value, float):
        raise ValueError(where + ' holds a non-integer number')
    if isinstance(value, dict):
        for key, item in value.items():
            _integers_only(item, where + '.' + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _integers_only(item, '%s[%d]' % (where, index))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key ' + key)
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Registry location and verification
# ---------------------------------------------------------------------------

def evidence_root(install):
    """``evidence_root`` from installation.json, else the desktop's own layout
    (``<desktop data>/suite/<id>`` -> ``<desktop data>/evidence``), else None."""
    explicit = (install or {}).get('evidence_root')
    if explicit is not None:
        if not isinstance(explicit, str) or not Path(explicit).is_absolute():
            raise ValueError('installation evidence_root must be an absolute path')
        return Path(explicit)
    state = (install or {}).get('controller_state_root')
    if isinstance(state, str) and Path(state).parent.name.lower() == 'suite':
        return Path(state).parent.parent / 'evidence'
    return None


def registry_path(install):
    root = evidence_root(install)
    return None if root is None else root / 'heldout' / 'locks.jsonl'


def _validate_payload(op, payload, where):
    if not isinstance(payload, dict) or not isinstance(payload.get('lockId'), str) or not SHA.fullmatch(payload['lockId']):
        raise ValueError(where + ': lock.lockId must be a sha256')
    _integers_only(payload, where + ' lock')
    if op == 'declare':
        if not isinstance(payload.get('strategyKey'), str) or not ID.fullmatch(payload['strategyKey']):
            raise ValueError(where + ': declare needs a strategyKey id')
        start, end, reveal = day(payload.get('start')), day(payload.get('end')), day(payload.get('revealableAfter'))
        if not start < end or not start <= reveal < end:
            raise ValueError(where + ': declare needs start < end and start <= revealableAfter < end')
        if payload['lockId'] != lock_id(payload):
            raise ValueError(where + ': lockId is not sha256(canonical(lock without lockId))')
    elif op == 'freeze':
        cells = payload.get('cells')
        if not isinstance(cells, list) or not cells or not all(
                isinstance(c, dict) and isinstance(c.get('symbol'), str) and c['symbol']
                and isinstance(c.get('timeframe'), str) and isinstance(c.get('setSha256'), str)
                and SHA.fullmatch(c['setSha256']) for c in cells):
            raise ValueError(where + ': freeze needs cells [{symbol, timeframe, setSha256}]')


def read_registry(install, *, now=None):
    """Verify the lock registry. Never raises: returns ``state`` ok, absent,
    not_configured or unavailable (with the failing line named in ``error``)."""
    try:
        path = registry_path(install)
    except ValueError as exc:
        return dict(state='unavailable', path=None, error=str(exc), head=None, events=0, locks=[])
    if path is None:
        return dict(state='not_configured', path=None, error=None, head=GENESIS, events=0, locks=[])
    try:
        if not path.exists():
            return dict(state='absent', path=str(path), error=None, head=GENESIS, events=0, locks=[])
        if path.is_symlink() or not path.is_file():
            raise ValueError('the registry is not a regular file')
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('the registry exceeds 16 MB')
        if raw and not raw.endswith(b'\n'):
            raise ValueError('the last line is incomplete (no newline)')
        text = raw.decode('utf-8')
        prev, locks, order = GENESIS, {}, []
        for seq, line in enumerate(text.split('\n')[:-1] if text else []):
            where = 'line %d' % (seq + 1)
            try:
                entry = json.loads(line, object_pairs_hook=_unique)
            except ValueError as exc:
                raise ValueError(where + ': not JSON (' + str(exc) + ')') from None
            if not isinstance(entry, dict) or set(entry) != LINE_KEYS:
                raise ValueError(where + ': keys must be exactly ' + ', '.join(sorted(LINE_KEYS)))
            if line != canonical(entry):
                raise ValueError(where + ': not canonical JSON')
            if entry['seq'] != seq or type(entry['seq']) is not int:
                raise ValueError(where + ': seq %r, expected %d' % (entry['seq'], seq))
            if entry['prev'] != prev:
                raise ValueError(where + ': prev does not match the previous hash')
            body = {k: v for k, v in entry.items() if k != 'hash'}
            if entry['hash'] != chain_hash(prev, body):
                raise ValueError(where + ': hash does not match its content')
            if not isinstance(entry['at'], str) or not INSTANT.fullmatch(entry['at']):
                raise ValueError(where + ': at must be a UTC instant')
            if entry['op'] not in OPS:
                raise ValueError(where + ': unknown op %r' % (entry['op'],))
            payload = entry['lock']
            _validate_payload(entry['op'], payload, where)
            if entry['ref'] != payload['lockId']:
                raise ValueError(where + ': ref must equal lock.lockId')
            _apply(locks, order, entry, where)
            prev = entry['hash']
        values = [_public(locks[i], now) for i in order]
        return dict(state='ok', path=str(path), error=None, head=prev, events=len(text.split('\n')) - 1 if text else 0, locks=values)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return dict(state='unavailable', path=str(path), error=str(exc), head=None, events=0, locks=[])


def _apply(locks, order, entry, where):
    op, payload, lid = entry['op'], entry['lock'], entry['lock']['lockId']
    if op == 'declare':
        if lid in locks:
            raise ValueError(where + ': lock declared twice')
        key = payload['strategyKey']
        if any(l['strategy_key'] == key and l['phase'] in ('declared', 'revealing') for l in locks.values()):
            raise ValueError(where + ': ' + key + ' already has an active lock')
        locks[lid] = dict(lock_id=lid, strategy_key=key, start=payload['start'], end=payload['end'],
                          reveal_after=payload['revealableAfter'], declared_at=entry['at'], phase='declared',
                          candidate=None, exposure_end=payload.get('exposureEnd'), weeks=payload.get('weeks'),
                          scope=payload.get('scope'))
        order.append(lid)
        return
    lock = locks.get(lid)
    if lock is None:
        raise ValueError(where + ': ' + op + ' names an undeclared lock')
    if op == 'freeze':
        if lock['phase'] != 'declared':
            raise ValueError(where + ': a ' + lock['phase'] + ' lock cannot be re-frozen')
        lock['candidate'] = [dict(symbol=c['symbol'], timeframe=c['timeframe'], set_sha256=c['setSha256']) for c in payload['cells']]
    elif op == 'reveal':
        if lock['phase'] != 'declared' or not lock['candidate']:
            raise ValueError(where + ': reveal needs a frozen, unrevealed lock (' + ALREADY_REVEALED + ')')
        lock['phase'], lock['reveal_started_at'] = 'revealing', entry['at']
    elif op == 'revealed':
        if lock['phase'] != 'revealing':
            raise ValueError(where + ': revealed needs a revealing lock')
        lock['phase'] = 'revealed'
    elif op == 'breach':
        if lock['phase'] not in ('declared', 'revealing'):
            raise ValueError(where + ': a ' + lock['phase'] + ' lock cannot be breached')
        lock['phase'], lock['breach'] = 'breached', dict(at=entry['at'], reason=payload.get('reason'), record_id=payload.get('recordId'))


def evidence_end_iso(now=None):
    """The AUTO evidence end (latest closed Friday, broker NY-close clock)."""
    from studio_evidence_end import auto
    return auto(now)['iso']


def _public(lock, now):
    status = lock['phase']
    if status == 'declared':
        try:
            status = 'revealable' if evidence_end_iso(now) >= lock['reveal_after'] else 'locked'
        except (ValueError, ImportError):
            status = 'locked'
    value = dict(lock)
    value['status'] = status
    value['active'] = status in ACTIVE
    value['plain'] = lock_sentence(value)
    return value


def lock_sentence(lock):
    head = 'Held-out lock %s: %s %s to %s' % (lock['lock_id'][:12], lock['strategy_key'], lock['start'], lock['end'])
    status = lock.get('status')
    if status == 'locked':
        return head + ' stays locked until its Prove reveal; it becomes revealable once Friday %s closes.' % lock['reveal_after']
    if status == 'revealable':
        return head + ' stays locked until its Prove reveal; it is revealable now.'
    if status == 'revealing':
        return head + ' is being revealed with its frozen candidate; only that reveal may test the window.'
    if status == 'revealed':
        return head + ' was revealed; the window is ordinary history now.'
    return head + ' was breached by an earlier exposure; it binds nothing and earns no held-out evidence.'


def active_locks(registry):
    return [l for l in registry['locks'] if l['active']]


def window(lock):
    return day(lock['start']), day(lock['end'])


def public_window(lock):
    """The lock fields every redacted reply lists in ``locked_windows``."""
    return dict(lock_id=lock['lock_id'], strategy_key=lock['strategy_key'], start=lock['start'], end=lock['end'],
                reveal_after=lock['reveal_after'], status=lock['status'], plain=lock['plain'])


# ---------------------------------------------------------------------------
# Enforcement: prepare and start refuse a member that overlaps an active lock
# ---------------------------------------------------------------------------

def member_span(tester, *, back_oos_date=None, export_end=None, open_end=False):
    """The data days a member reads: [min(BackOOSDate, FromDate), max(ToDate, export end)).

    ToDate is exclusive (MT5). A batch export runs past ToDate to its evidence end;
    ``open_end`` marks an EA build that ends exports at its own last Friday at
    export time, so the end is unknown before it runs and nothing later is safe.
    """
    start, end = iso_day(tester.get('FromDate')), iso_day(tester.get('ToDate'))
    if start is None or end is None:
        return None
    back = iso_day(back_oos_date)
    if back is not None and back < start:
        start = back
    export = iso_day(export_end)
    if export is not None and export > end:
        end = export
    return dict(start=start, end=date.max if open_end else end, open_end=bool(open_end))


def legacy_export_end(at=None):
    """Exclusive export end of an EA build without EvidenceEnd exporting at ``at`` (an
    instant; None = now): its own last Friday, which MT5 excludes. None if unreadable."""
    from studio_evidence_end import legacy_end
    try:
        moment = None
        if at is not None:
            moment = at if isinstance(at, datetime) else datetime.fromisoformat(str(at).replace('Z', '+00:00'))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        return date.fromisoformat(legacy_end(moment)['iso']) + timedelta(days=1)
    except (TypeError, ValueError, KeyError):
        return None


def native_export_end(native_batch):
    """(exclusive export end, open_end) for a native batch plan's ``native_batch``."""
    evidence = (native_batch or {}).get('evidence_end')
    if isinstance(evidence, dict) and 'ea_setting' in evidence and iso_day(evidence.get('target')):
        return iso_day(evidence['target']) + timedelta(days=1), False
    return None, True


def refusal_sentence(lock, member):
    span = member['span']
    to_text = 'its export end (unknown before it runs)' if span.get('open_end') else (span['end'] - timedelta(days=1)).isoformat()
    return ('Held-out lock %s: %s %s to %s stays locked until its Prove reveal. Member %s tests %s to %s, which overlaps. '
            'End its dates before %s, or reveal the lock.' % (
                lock['lock_id'][:12], lock['strategy_key'], lock['start'], lock['end'], member['label'],
                span['start'].isoformat(), to_text, lock['start']))


def enforce(install, members, *, reveal_lock_id=None, now=None, registry=None):
    """Refuse when any member overlaps an active lock (spec §4.3).

    ``members``: dicts with ``label``, ``span`` (from member_span), ``declared`` (a
    validated strategy_ref or None), ``keys`` (every key it may belong to) and
    ``reveal`` (it runs a frozen candidate of ``reveal_lock_id``). Returns the
    verified registry summary when nothing overlaps.
    """
    registry = registry or read_registry(install, now=now)
    if registry['state'] == 'unavailable':
        raise HeldOutRefused(UNAVAILABLE, 'The held-out lock registry cannot be verified (%s), so nothing may be '
                             'prepared or started until the desktop repairs it.' % registry['error'])
    active = active_locks(registry)
    for member in members:
        span = member.get('span')
        for lock in active:
            start, end = window(lock)
            if span is not None and not overlaps(span['start'], span['end'], start, end):
                continue
            if reveal_lock_id == lock['lock_id'] and member.get('reveal'):
                continue
            if member.get('declared') is None:
                from studio_strategy_attribution import STRATEGY_REF_HELP
                hint = member.get('suggestion')
                plain = refusal_sentence(lock, member) if span is not None else (
                    'Held-out lock %s: %s %s to %s stays locked; member %s has unknown test dates.'
                    % (lock['lock_id'][:12], lock['strategy_key'], lock['start'], lock['end'], member['label']))
                plain += (' The member names no strategy, so it counts against every lock. ' + STRATEGY_REF_HELP
                          + (' Its SET matches %s.' % canonical(hint) if hint else ''))
                raise HeldOutRefused(UNATTRIBUTED, plain, [public_window(lock)])
            if lock['strategy_key'] in member.get('keys', ()):
                raise HeldOutRefused(LOCKED, refusal_sentence(lock, member), [public_window(lock)])
    return dict(state=registry['state'], head=registry['head'], active_locks=len(active), checked_members=len(members))


def reveal_lock(install, lock_id, members, *, evidence_end=None, now=None, registry=None):
    """A plan that names ``heldout_reveal.lock_id``: the lock must be revealing, and the
    plan must run exactly its frozen candidate under its own key, to the window end."""
    if not isinstance(lock_id, str) or not SHA.fullmatch(lock_id):
        raise HeldOutRefused(REVEAL_MISMATCH, 'heldout_reveal.lock_id must be a lock id (sha256).')
    registry = registry or read_registry(install, now=now)
    if registry['state'] == 'unavailable':
        raise HeldOutRefused(UNAVAILABLE, 'The held-out lock registry cannot be verified (%s).' % registry['error'])
    lock = next((l for l in registry['locks'] if l['lock_id'] == lock_id), None)
    if lock is None:
        raise HeldOutRefused(REVEAL_MISMATCH, 'Held-out lock %s is not in the registry.' % lock_id[:12])
    if lock['status'] in ('revealed',):
        raise HeldOutRefused(ALREADY_REVEALED, lock['plain'])
    if lock['status'] != 'revealing':
        raise HeldOutRefused(REVEAL_MISMATCH, lock['plain'] + ' The desktop starts the reveal (heldOut.reveal) before '
                             'the controller prepares or starts it.', [public_window(lock)])
    cells = sorted((c['symbol'], c['timeframe'], c['set_sha256']) for c in lock['candidate'] or [])
    planned = sorted((m.get('symbol'), m.get('timeframe'), m.get('set_sha256')) for m in members)
    if planned != cells:
        raise HeldOutRefused(REVEAL_MISMATCH, 'A reveal runs exactly the frozen candidate of lock %s (%d cells); this plan '
                             'runs %d different or extra SETs.' % (lock_id[:12], len(cells), len(planned)), [public_window(lock)])
    for member in members:
        if (member.get('declared') or {}).get('strategy_key') != lock['strategy_key']:
            raise HeldOutRefused(REVEAL_MISMATCH, 'Every reveal member declares strategy_ref.strategy_key %s.' % lock['strategy_key'])
    if evidence_end is not None and iso_day(evidence_end) < day(lock['reveal_after']):
        raise HeldOutRefused(REVEAL_MISMATCH, 'The reveal must run through Friday %s (the window\'s last closed Friday); '
                             'this plan ends %s.' % (lock['reveal_after'], evidence_end), [public_window(lock)])
    return lock


def status(install, *, now=None):
    """Read-only ``heldout-status``: the verified registry and every lock in it."""
    registry = read_registry(install, now=now)
    locks = registry['locks']
    active = [l for l in locks if l['active']]
    if registry['state'] == 'unavailable':
        plain = ('The held-out lock registry cannot be verified (%s). Every prepare and start is refused and every '
                 'metric is redacted until the desktop repairs it.' % registry['error'])
    elif registry['state'] == 'not_configured':
        plain = 'No evidence root is configured for this installation, so no held-out lock can apply here.'
    elif not active:
        plain = 'No held-out lock is active.'
    else:
        plain = ' '.join(l['plain'] for l in active)
    return dict(capability=CAPABILITY, schema=SCHEMA, registry=dict(state=registry['state'], path=registry['path'],
                head=registry['head'], events=registry['events'], error=registry['error']),
                locks=locks, active=[public_window(l) for l in active], plain=plain)
