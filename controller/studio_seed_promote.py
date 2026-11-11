"""Promote one verified SeedFarming candidate into a fixed SET and a robustness SET.

Local files only: no native, queue, owner or terminal effect. The retained seed
manifest, state, frozen SETs and result artifacts are re-verified by hash through
SeedRunner before anything is read, so changed evidence refuses. Every file is
written to a hidden temporary sibling folder that is published with one rename,
so a failed write leaves nothing behind and can be retried. Output is
create-only; repeating the same promotion returns the retained receipt.

Lineage by SHA-256 (Claude-Mac goatai#2750 6793727135: "every promotion receipt carries the fork's SET SHA-256
from now on, so lineage never again rests on name and symbol"). 22 migrated October files traced to their seed
job only by design, symbol and a fork name. The receipt names each SET it writes by SHA-256 and by the SHA-256 of
its canonical inputs (``canonical_sha256``: every input but EA_Desc, so a renamed copy still matches). The
strategy-library fork made from a promoted SET is created by the desktop (``strategy.forkTemplate``), not here:
``record_fork`` appends that fork's SET SHA-256 to the promotion (``forks\\<fork sha256>.json``, create-only,
beside the unchanged ``promotion.json``), and ``lookup`` finds the promotion of any SET, read-only: a promoted
SET itself, a recorded fork, or a SET with the same inputs under another name.
"""
from datetime import datetime, timezone
import hashlib
import json
from fractions import Fraction
import os
from pathlib import Path
import re
import shutil
import uuid

from campaign_ledger import sha
from studio_installation import read_json
from studio_seed import SeedRunner
from studio_seed_results import read_seed_json, MAX_RESULT_BYTES
from strategy_registry import inspect_set
from studio_strategy_settings import read_values, numeric
from studio_template_tools import source_bytes, validate_raw

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.#-]{0,62}')
MAX_NEIGHBORHOOD = 5
# Fixed file names: no user text reaches a file name, so Windows reserved names cannot occur.
FILES = (('fixed_set', 'fixed.set'), ('robustness_set', 'robustness.set'))
RECEIPT = 'promotion.json'
FORKS = 'forks'
FORK_SCHEMA = 'goat-promotion-fork-v1'
LOOKUP_SCHEMA = 'goat-promotion-lookup-v1'
FORK_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}')
MAX_PROMOTIONS = 20000
MAX_CHANGED_INPUTS = 50
SCOPE = ('Seed result is in-sample only. robustness_set is a local stability check around the candidate; '
         'only the forward window is out-of-sample. Its batch re-optimizes the neighborhood and picks the best '
         'neighbor on the back window, so judge it on the forward window. Run it with prepare-batch on dates after '
         'seed_window.to_date, with a forward window, before any portfolio use.')


def _number(value):
    """Exact text for a ladder bound: integers plain, decimals without trailing zeros."""
    if value.denominator == 1:
        return str(value.numerator)
    text = format(float(value), '.8f').rstrip('0').rstrip('.')
    if Fraction(text) != value:
        raise ValueError('Ladder bound cannot be written exactly')
    return text


def _rewrite(frozen, lines):
    """Replace whole `Name=` assignments in the frozen UTF-16 SET, keeping order and comments."""
    text = frozen.decode('utf-16')
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        name = body.split('=', 1)[0] if '=' in body and not body.lstrip().startswith(';') else None
        out.append(name + '=' + lines[name] + line[len(body):] if name in lines else line)
    return b'\xff\xfe' + ''.join(out).encode('utf-16-le')


def _candidate_sha(values, inputs):
    """goat-seed-fixed-values-v1: the candidate identity over every input value except EA_Desc."""
    return sha({k: (v if inputs[k]['type'] in ('string', 'datetime') else str(numeric(v, inputs[k])))
                for k, v in values.items() if k != 'EA_Desc'})


def _create(path, raw):
    """Exclusive, durable create: never overwrites, and the bytes reach disk before the folder is published."""
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _retained(out, request):
    """Receipt of a completed promotion folder. Anything else is left in place for a human."""
    try:
        receipt = read_json(out / RECEIPT)
        valid = isinstance(receipt, dict) and receipt.get('schema_version') == 1 and all(
            isinstance(receipt.get(key), dict) and isinstance(receipt[key].get('sha256'), str) for key, _ in FILES)
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Incomplete promotion folder at %s; inspect and remove it manually' % out)
    if {k: receipt.get(k) for k in request} != request:
        raise ValueError('This candidate was already promoted with a different name or neighborhood')
    for key, file in FILES:
        path = out / file
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt[key]['sha256']:
            raise ValueError('Retained promoted SET changed or missing: ' + file)
    return receipt


def promote(controller, batch_id, candidate_sha256, name, *, neighborhood=1, member=None, runner=None):
    if not isinstance(candidate_sha256, str) or not re.fullmatch('[0-9a-f]{64}', candidate_sha256):
        raise ValueError('Candidate must be the 64-character candidate_sha256 from the seed result')
    if not isinstance(name, str) or not NAME.fullmatch(name) or 'SeedFarming' in name or '@{' in name:
        raise ValueError('Name must be 1..63 plain letters, digits, spaces or _ . # - without SeedFarming metadata')
    if type(neighborhood) is not int or not 1 <= neighborhood <= MAX_NEIGHBORHOOD:
        raise ValueError('neighborhood must be an integer from 1 to %d ladder steps' % MAX_NEIGHBORHOOD)
    if member is not None and (not isinstance(member, str) or not member):
        raise ValueError('member must be a seed member alias or member_id')
    runner = runner or SeedRunner(controller, process=object())
    root, manifest, state = runner._read(batch_id)
    # The candidate hash covers input values only, so identical values from two members
    # (another symbol or window) share it: the member must then be named explicitly.
    matches = []
    for spec, item in zip(manifest['members'], state['members']):
        if not item.get('result') or (member is not None and member not in (spec['alias'], spec['member_id'])):
            continue
        result = read_seed_json(item['result']['path'], MAX_RESULT_BYTES)
        candidate = next((c for c in result['candidates'] if c['candidate_sha256'] == candidate_sha256), None)
        if candidate:
            matches.append((spec, result, candidate))
    if not matches:
        raise ValueError('Candidate is not in this seed batch\'s verified results' + ('' if member is None else ' for that member'))
    if len(matches) > 1:
        raise ValueError('Candidate matches %d seed members; pass member with one of: %s' % (len(matches), ', '.join(m[0]['alias'] for m in matches)))
    spec, result, candidate = matches[0]
    if candidate['source_sha256'] != spec['source_sha256'] or candidate['frozen_sha256'] != spec['set_sha256']:
        raise ValueError('Candidate provenance differs from its frozen seed member')
    request = dict(batch_id=batch_id, candidate_sha256=candidate_sha256, name=name, neighborhood=neighborhood)
    out = root / 'promoted' / spec['alias'] / candidate_sha256
    if out.exists():
        return _retained(out, request) | dict(status='retained', receipt_path=str(out / RECEIPT))
    frozen = Path(spec['set_path']).read_bytes()
    original = read_values(frozen)
    exact = dict(result['base_values']) | candidate['value_overrides']
    # The merged values must reproduce the candidate's own identity (goat-seed-fixed-values-v1).
    inputs = controller.schema['inputs']
    if candidate.get('candidate_hash_scheme') != 'goat-seed-fixed-values-v1' or _candidate_sha(exact, inputs) != candidate_sha256:
        raise ValueError('Merged candidate values do not reproduce candidate_sha256')
    fixed, robustness, ladder = {'EA_Desc': name}, {'EA_Desc': name}, {}
    for axis in spec['axes']:
        definition = inputs[axis]
        parts = original[axis].split('||')
        if len(parts) != 5:
            raise ValueError('Frozen axis is not an optimization ladder: ' + axis)
        value = exact[axis]
        fixed[axis] = '||'.join([value, parts[1], parts[2], parts[3], 'N'])
        if definition['type'] == 'bool':
            low, high = parts[1], parts[3]
        else:
            start, step, stop = numeric(parts[1], definition), numeric(parts[2], definition, step=True), numeric(parts[3], definition)
            point = numeric(value, definition)
            low, high = _number(max(start, point - neighborhood * step)), _number(min(stop, point + neighborhood * step))
        robustness[axis] = '||'.join([value, low, parts[2], high, 'Y'])
        ladder[axis] = dict(value=value, start=low, step=parts[2], stop=high)
    fixed_bytes, robustness_bytes = _rewrite(frozen, fixed), _rewrite(frozen, robustness)
    validate_raw(fixed_bytes, controller.schema, controller.policy)
    validate_raw(robustness_bytes, controller.schema, controller.policy, require_optimization=True)
    if read_values(fixed_bytes)['EA_Desc'] != name or read_values(robustness_bytes)['EA_Desc'] != name:
        raise ValueError('Promoted SET must carry the new plain EA_Desc')
    sets = dict(zip((file for _, file in FILES), (fixed_bytes, robustness_bytes)))
    seed_window = dict(symbol=spec['tester']['Symbol'], period=spec['tester']['Period'], from_date=spec['tester']['FromDate'], to_date=spec['tester']['ToDate'])
    receipt = request | dict(
        schema_version=1, member_id=spec['member_id'], alias=spec['alias'], source_path=spec['source_path'],
        source_sha256=spec['source_sha256'], frozen_set_sha256=spec['set_sha256'], pass_number=candidate['pass_number'],
        seed_metrics=candidate['metrics'], seed_qualifies=candidate['qualifies'], seed_window=seed_window, ladder=ladder,
        # Each written SET by its bytes and by its canonical inputs (EA_Desc excluded): the lineage keys (lookup).
        **{key: dict(path=str(out / file), sha256=hashlib.sha256(sets[file]).hexdigest(),
                     canonical_sha256=inspect_set(sets[file])['canonical_sha256']) for key, file in FILES},
        scope=SCOPE, native_launch_qualified=False)
    payload = sets | {RECEIPT: (json.dumps(receipt, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')}
    # Short hidden sibling: never a longer path than the final folder, and unique per attempt.
    temporary = out.parent / ('.%s.tmp-%s' % (candidate_sha256[:12], uuid.uuid4().hex[:16]))
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        for file, raw in payload.items():
            _create(temporary / file, raw)
        for file, raw in payload.items():
            if (temporary / file).read_bytes() != raw:
                raise OSError('Promoted file read-back differs: ' + file)
        # Re-derive the candidate from the written fixed SET: same identity, no active axis.
        written = (temporary / 'fixed.set').read_bytes()
        if validate_raw(written, controller.schema, controller.policy)['active_axes']:
            raise ValueError('Fixed SET must have no active optimization axes')
        values = read_values(written)
        if _candidate_sha({k: v if inputs[k]['type'] == 'string' else v.split('||')[0] for k, v in values.items()}, inputs) != candidate_sha256:
            raise ValueError('Written fixed SET does not reproduce candidate_sha256')
        if out.exists():
            raise ValueError('Promotion folder appeared during this promotion; repeat the request')
        os.rename(temporary, out)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return receipt | dict(status='written', receipt_path=str(out / RECEIPT))

# ---------------------------------------------------------------------------
# Lineage: the fork made from a promoted SET, and the promotion of any SET
# ---------------------------------------------------------------------------

def _canonical(entry, folder, file):
    """The canonical input SHA-256 of one promoted SET: the receipt's own, or computed from the SET for an older receipt."""
    if isinstance(entry.get('canonical_sha256'), str):
        return entry['canonical_sha256']
    return inspect_set((folder / file).read_bytes())['canonical_sha256']


def _fork_records(folder):
    records = []
    for path in sorted((folder / FORKS).glob('*.json')) if (folder / FORKS).is_dir() else []:
        try:
            record = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get('schema') == FORK_SCHEMA and record.get('fork_set_sha256') == path.stem:
            records.append(record)
    return records


def _promotion(folder):
    """(receipt, receipt SHA-256) of one completed promotion folder, its SETs verified against the receipt."""
    raw = (folder / RECEIPT).read_bytes()
    receipt = read_json(folder / RECEIPT)
    request = {key: receipt.get(key) for key in ('batch_id', 'candidate_sha256', 'name', 'neighborhood')} if isinstance(receipt, dict) else {}
    return _retained(folder, request), hashlib.sha256(raw).hexdigest()


def record_fork(controller, batch_id, candidate_sha256, fork_set, *, fork_id=None, member=None, runner=None):
    """Append the SHA-256 of a strategy-library fork's SET to the promotion it was made from. Local files only.

    The fork SET is read as it is and never changed. ``relation`` says how it stands to the promotion's own SETs:
    ``exact`` (the same bytes as fixed.set or robustness.set), ``same_inputs`` (the same inputs under another EA_Desc
    or comments) or ``edited`` (other inputs: ``changed_inputs`` names them against the nearer promoted SET).
    Create-only: recording the same fork again returns the retained record; nothing is ever overwritten."""
    if not isinstance(candidate_sha256, str) or not re.fullmatch('[0-9a-f]{64}', candidate_sha256):
        raise ValueError('Candidate must be the 64-character candidate_sha256 of the promotion')
    if fork_id is not None and (not isinstance(fork_id, str) or not FORK_ID.fullmatch(fork_id)):
        raise ValueError('fork_id must be the strategy-library fork id (letters, digits, . _ -)')
    runner = runner or SeedRunner(controller, process=object())
    root, manifest, _ = runner._read(batch_id)
    folders = [root / 'promoted' / spec['alias'] / candidate_sha256 for spec in manifest['members']
               if (member is None or member in (spec['alias'], spec['member_id']))
               and (root / 'promoted' / spec['alias'] / candidate_sha256 / RECEIPT).is_file()]
    if not folders:
        raise ValueError('No promotion of this candidate in this seed batch' + ('' if member is None else ' for that member'))
    if len(folders) > 1:
        raise ValueError('Candidate was promoted from %d seed members; pass member with one of: %s'
                         % (len(folders), ', '.join(folder.parent.name for folder in folders)))
    folder = folders[0]
    receipt, receipt_sha256 = _promotion(folder)
    _, raw, _ = source_bytes(fork_set)
    info = inspect_set(raw)
    relation, derived_from, changed = 'edited', None, None
    for key, file in FILES:
        if info['sha256'] == receipt[key]['sha256']:
            relation, derived_from = 'exact', key
            break
    else:
        for key, file in reversed(FILES):                       # a fork is made from the robustness SET first
            if info['canonical_sha256'] == _canonical(receipt[key], folder, file):
                relation, derived_from = 'same_inputs', key
                break
    if relation == 'edited':
        mine = json.loads(info['canonical_json'])
        nearest = None
        for key, file in FILES:
            theirs = json.loads(inspect_set((folder / file).read_bytes())['canonical_json'])
            names = sorted(name for name in set(mine) | set(theirs) if mine.get(name) != theirs.get(name))
            if nearest is None or len(names) < len(nearest[1]):
                nearest = (key, names)
        derived_from, changed = nearest[0], dict(count=len(nearest[1]), inputs=nearest[1][:MAX_CHANGED_INPUTS])
    record = dict(schema=FORK_SCHEMA, fork_set_sha256=info['sha256'], fork_canonical_sha256=info['canonical_sha256'], fork_id=fork_id,
                  fork_ea_desc=info['ea_desc'], relation=relation, derived_from=derived_from, changed_inputs=changed,
                  promotion=dict(batch_id=batch_id, alias=receipt['alias'], member_id=receipt['member_id'],
                                 candidate_sha256=candidate_sha256, name=receipt['name'], receipt_sha256=receipt_sha256),
                  recorded_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    path = folder / FORKS / (info['sha256'] + '.json')
    if path.exists():
        retained = read_json(path)
        if not isinstance(retained, dict) or retained.get('schema') != FORK_SCHEMA or retained.get('fork_set_sha256') != info['sha256']:
            raise ValueError('Retained fork record at %s is not a %s record; inspect it' % (path, FORK_SCHEMA))
        if retained.get('fork_id') != fork_id:
            raise ValueError('This fork SET is already recorded for this promotion under fork id %r' % retained.get('fork_id'))
        return retained | dict(status='retained', record_path=str(path))
    path.parent.mkdir(exist_ok=True)
    _create(path, (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
    return record | dict(status='written', record_path=str(path))


def lookup(controller_root, *, set_sha256=None, set_path=None):
    """Read-only: the promotion(s) a SET belongs to, by SHA-256, never by name or symbol.

    Give the SET's SHA-256, or the SET file (then its canonical inputs are matched too). A match is ``promoted_set``
    (the SET is a promotion's fixed.set or robustness.set), ``recorded_fork`` (record_fork wrote its SHA-256 to that
    promotion) or ``same_inputs`` (the same inputs under another name; file only). Every seed batch's promotions
    under this controller state are read; a promotion folder that cannot be read is listed, never skipped silently."""
    if (set_sha256 is None) == (set_path is None):
        raise ValueError('Give exactly one of the SET SHA-256 or the SET file')
    canonical = None
    if set_path is not None:
        _, raw, _ = source_bytes(set_path)
        info = inspect_set(raw)
        set_sha256, canonical = info['sha256'], info['canonical_sha256']
    if not isinstance(set_sha256, str) or not re.fullmatch('[0-9a-f]{64}', set_sha256):
        raise ValueError('The SET SHA-256 must be 64 lowercase hex characters')
    matches, unreadable, read = [], [], 0
    seeds = Path(controller_root) / 'seeds'
    for receipt_path in sorted(seeds.glob('*/promoted/*/*/' + RECEIPT)) if seeds.is_dir() else []:
        if read >= MAX_PROMOTIONS:
            raise ValueError('More than %d promotions under this controller state; look the SET up per seed batch' % MAX_PROMOTIONS)
        folder = receipt_path.parent
        try:
            receipt = read_json(receipt_path)
            if not isinstance(receipt, dict) or any(not isinstance((receipt.get(key) or {}).get('sha256'), str) for key, _ in FILES):
                raise ValueError('not a promotion receipt')
            found = []
            for key, file in FILES:
                if receipt[key]['sha256'] == set_sha256:
                    found.append(dict(relation='promoted_set', which=key, fork=None))
                elif canonical is not None and _canonical(receipt[key], folder, file) == canonical:
                    found.append(dict(relation='same_inputs', which=key, fork=None))
            fork_path = folder / FORKS / (set_sha256 + '.json')
            if fork_path.is_file():
                fork = read_json(fork_path)
                found.insert(0, dict(relation='recorded_fork', which=fork.get('derived_from'), fork=fork))
            receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            unreadable.append(dict(receipt_path=str(receipt_path), reason=str(error)[:200] or type(error).__name__))
            continue
        read += 1
        for item in found:
            matches.append(item | dict(batch_id=receipt.get('batch_id'), alias=receipt.get('alias'), member_id=receipt.get('member_id'),
                                       candidate_sha256=receipt.get('candidate_sha256'), name=receipt.get('name'),
                                       seed_window=receipt.get('seed_window'), source_sha256=receipt.get('source_sha256'),
                                       frozen_set_sha256=receipt.get('frozen_set_sha256'),
                                       promoted_set_sha256=receipt[item['which']]['sha256'] if item['which'] else None,
                                       receipt_path=str(receipt_path), receipt_sha256=receipt_sha256))
    if matches:
        first = matches[0]
        plain = ('This SET belongs to the promotion of candidate %s in seed batch %s (member %s): %s.'
                 % (str(first['candidate_sha256'])[:12], first['batch_id'], first['alias'],
                    dict(promoted_set='it is the promotion\'s own ' + str(first['which']).replace('_', ' '),
                         recorded_fork='its SHA-256 was recorded as a fork of it',
                         same_inputs='it has the same inputs as its ' + str(first['which']).replace('_', ' ')
                                     + ' under another name')[first['relation']])
                 + ('' if len(matches) == 1 else ' %d more matches are listed.' % (len(matches) - 1)))
    else:
        plain = 'No promotion under this controller state names this SET by SHA-256%s.' % ('' if canonical is None else ' or has its inputs')
    return dict(schema=LOOKUP_SCHEMA, set_sha256=set_sha256, canonical_sha256=canonical, matches=matches, promotions_read=read,
                unreadable=unreadable, plain=plain, writes=False)
