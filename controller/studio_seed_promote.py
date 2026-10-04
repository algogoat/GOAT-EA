"""Promote one verified SeedFarming candidate into a fixed SET and a robustness SET.

Local files only: no native, queue, owner or terminal effect. The retained seed
manifest, state, frozen SETs and result artifacts are re-verified by hash through
SeedRunner before anything is read, so changed evidence refuses. Every file is
written to a hidden temporary sibling folder that is published with one rename,
so a failed write leaves nothing behind and can be retried. Output is
create-only; repeating the same promotion returns the retained receipt.
"""
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
from studio_strategy_settings import read_values, numeric
from studio_template_tools import validate_raw

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.#-]{0,62}')
MAX_NEIGHBORHOOD = 5
# Fixed file names: no user text reaches a file name, so Windows reserved names cannot occur.
FILES = (('fixed_set', 'fixed.set'), ('robustness_set', 'robustness.set'))
RECEIPT = 'promotion.json'
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
        **{key: dict(path=str(out / file), sha256=hashlib.sha256(sets[file]).hexdigest()) for key, file in FILES},
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
