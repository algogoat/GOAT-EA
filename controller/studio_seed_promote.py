"""Promote one verified SeedFarming candidate into exact SET files for independent validation.

Local files only: no native, queue, owner or terminal effect. The retained seed
manifest, state, frozen SETs and result artifacts are re-verified by hash through
SeedRunner before anything is read, so changed evidence refuses. Output is
create-only; repeating the same promotion returns the retained receipt.
"""
import hashlib
from fractions import Fraction
from pathlib import Path
import re

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_seed import SeedRunner
from studio_seed_results import read_seed_json, MAX_RESULT_BYTES
from studio_strategy_settings import read_values, numeric
from studio_template_tools import validate_raw

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.#-]{0,62}')
MAX_NEIGHBORHOOD = 5


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


def promote(controller, batch_id, candidate_sha256, name, *, neighborhood=1, member=None, runner=None):
    if not isinstance(candidate_sha256, str) or not re.fullmatch('[0-9a-f]{64}', candidate_sha256):
        raise ValueError('Candidate must be the 64-character candidate_sha256 from the seed result')
    if not isinstance(name, str) or not NAME.fullmatch(name) or 'SeedFarming' in name or '@{' in name:
        raise ValueError('Name must be 1..63 plain letters, digits, spaces or _ . # - without SeedFarming metadata')
    if type(neighborhood) is not int or not 0 <= neighborhood <= MAX_NEIGHBORHOOD:
        raise ValueError('neighborhood must be an integer from 0 to %d ladder steps' % MAX_NEIGHBORHOOD)
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
    receipt_path = out / 'promotion.json'
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if {k: receipt.get(k) for k in request} != request:
            raise ValueError('This candidate was already promoted with a different name or neighborhood')
        for key in ('fixed_set', 'validation_set'):
            if hashlib.sha256(Path(receipt[key]['path']).read_bytes()).hexdigest() != receipt[key]['sha256']:
                raise ValueError('Retained promoted SET changed')
        return receipt
    frozen = Path(spec['set_path']).read_bytes()
    original = read_values(frozen)
    exact = dict(result['base_values']) | candidate['value_overrides']
    # The merged values must reproduce the candidate's own identity (goat-seed-fixed-values-v1).
    inputs = controller.schema['inputs']
    canonical = {k: (v if inputs[k]['type'] in ('string', 'datetime') else str(numeric(v, inputs[k]))) for k, v in exact.items() if k != 'EA_Desc'}
    if candidate.get('candidate_hash_scheme') != 'goat-seed-fixed-values-v1' or sha(canonical) != candidate_sha256:
        raise ValueError('Merged candidate values do not reproduce candidate_sha256')
    fixed, validation, ladder = {'EA_Desc': name}, {'EA_Desc': name}, {}
    for axis in spec['axes']:
        definition = controller.schema['inputs'][axis]
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
        validation[axis] = '||'.join([value, low, parts[2], high, 'Y'])
        ladder[axis] = dict(value=value, start=low, step=parts[2], stop=high)
    fixed_bytes, validation_bytes = _rewrite(frozen, fixed), _rewrite(frozen, validation)
    validate_raw(fixed_bytes, controller.schema, controller.policy)
    validate_raw(validation_bytes, controller.schema, controller.policy, require_optimization=True)
    if read_values(fixed_bytes)['EA_Desc'] != name or read_values(validation_bytes)['EA_Desc'] != name:
        raise ValueError('Promoted SET must carry the new plain EA_Desc')
    out.mkdir(parents=True, exist_ok=False)
    slug = re.sub('[^A-Za-z0-9_-]+', '-', name).strip('-') or 'candidate'
    files = {}
    for key, raw in (('fixed_set', fixed_bytes), ('validation_set', validation_bytes)):
        path = out / f'{slug}.{key.split("_")[0]}.set'
        path.write_bytes(raw)
        files[key] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    seed_window = dict(symbol=spec['tester']['Symbol'], period=spec['tester']['Period'], from_date=spec['tester']['FromDate'], to_date=spec['tester']['ToDate'])
    receipt = request | dict(
        schema_version=1, member_id=spec['member_id'], alias=spec['alias'], source_path=spec['source_path'],
        source_sha256=spec['source_sha256'], frozen_set_sha256=spec['set_sha256'], pass_number=candidate['pass_number'],
        seed_metrics=candidate['metrics'], seed_qualifies=candidate['qualifies'], seed_window=seed_window,
        ladder=ladder, **files,
        scope='Seed in-sample result only. Validate validation_set with prepare-batch on periods after seed_window.to_date, '
              'with a forward window, before any portfolio use.',
        native_launch_qualified=False)
    write_json(receipt_path, receipt)
    return receipt
