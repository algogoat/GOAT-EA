"""Recoverable byte-exact shared-control replacement; no MT5 launch or authorization.

Callers must verify native ownership separately. The persistent marker refuses a
second transaction even after process exit; recovery requires explicit inspection.
Legacy EA processes do not honor this marker, so compare-before-write is detection,
not a claim of atomic coordination with those processes.
"""
import base64
import hashlib
import json
import os
from pathlib import Path

NAMES = ('active_optimization_run.ini', 'active_optimization_config.ini',
         'active_optimization_launch.ini')


def digest(raw):
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def contents(path):
    return path.read_bytes() if path.exists() else None


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def begin(base, evidence, replacements, expected, owner):
    base, evidence = Path(base).resolve(), Path(evidence).resolve()
    if set(replacements) != set(NAMES) or set(expected) != set(NAMES):
        raise ValueError('Exactly the three native controls are required')
    if evidence.is_relative_to(base) or base.is_relative_to(evidence):
        raise ValueError('Independent evidence location required')
    if not owner or evidence.exists():
        raise ValueError('New owner and unused evidence directory required')
    for name in NAMES:
        if type(replacements[name]) is not bytes:
            raise ValueError('Exact replacement bytes required')
        if digest(contents(base / name)) != expected[name]:
            raise ValueError('Shared controls changed before transaction')
    marker = base / 'agent-native-control-owner.json'
    # Exclusive creation is durable ownership among cooperating adapters.
    with marker.open('x', encoding='utf-8') as stream:
        json.dump(dict(owner=owner, evidence=str(evidence)), stream)
        stream.flush()
        os.fsync(stream.fileno())
    evidence.mkdir(parents=True)
    receipt = dict(owner=owner, base=str(base), phase='prepared', files={})
    for name in NAMES:
        before = contents(base / name)
        if digest(before) != expected[name]:
            raise ValueError('Shared controls changed while claiming; preserve marker for reconciliation')
        receipt['files'][name] = dict(before=None if before is None else base64.b64encode(before).decode(),
                                     before_sha256=digest(before), after_sha256=digest(replacements[name]))
    write_json(evidence / 'transaction.json', receipt)
    try:
        for name in NAMES:
            if digest(contents(base / name)) != expected[name]:
                raise ValueError('Concurrent native control mutation; reconciliation required')
            temporary = base / (name + '.agent-tmp')
            with temporary.open('xb') as stream:
                stream.write(replacements[name]); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, base / name)
        if any(digest(contents(base / n)) != receipt['files'][n]['after_sha256'] for n in NAMES):
            raise ValueError('Post-write controls differ; reconciliation required')
        receipt['phase'] = 'installed'
    except Exception:
        receipt['phase'] = 'reconcile_required'
        write_json(evidence / 'transaction.json', receipt)
        raise
    write_json(evidence / 'transaction.json', receipt)
    return receipt


def restore(evidence, expected_current):
    """Restore after caller proves native jobs stopped; refuse unknown newer state.

    expected_current must come from an inspected completion/recovery snapshot,
    since native export legitimately deletes or rewrites config/guard files.
    """
    evidence = Path(evidence).resolve()
    receipt = json.loads((evidence / 'transaction.json').read_text())
    base = Path(receipt['base'])
    marker = base / 'agent-native-control-owner.json'
    ownership = json.loads(marker.read_text())
    if ownership != dict(owner=receipt['owner'], evidence=str(evidence)):
        raise ValueError('Different transaction owns native controls')
    if set(expected_current) != set(NAMES):
        raise ValueError('Inspect all current controls before recovery')
    originals = {}
    for name in NAMES:
        item = receipt['files'][name]
        raw = None if item['before'] is None else base64.b64decode(item['before'], validate=True)
        if digest(raw) != item['before_sha256']:
            raise ValueError('Corrupt backup; cannot restore')
        originals[name] = raw
        if digest(contents(base / name)) != expected_current[name]:
            raise ValueError('New native state detected; refusing restoration')
    receipt['phase'] = 'restoring'
    write_json(evidence / 'transaction.json', receipt)
    for name, raw in originals.items():
        path = base / name
        if digest(contents(path)) != expected_current[name]:
            raise ValueError('Concurrent native mutation during restoration')
        if raw is None:
            if path.exists(): path.unlink()
        else:
            temp = base / (name + '.restore-tmp')
            with temp.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
    if any(digest(contents(base / n)) != receipt['files'][n]['before_sha256'] for n in NAMES):
        raise ValueError('Restoration verification failed')
    receipt['phase'] = 'restored'
    write_json(evidence / 'transaction.json', receipt)
    marker.unlink()
    return receipt
