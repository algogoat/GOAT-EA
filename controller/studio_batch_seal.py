"""Verify every member of a prepared batch once, at preparation, and seal the result.

Starting a batch used to re-run the full per-member semantic checks about seven
times (package verify, launch intent, launch material, control install, arm
validation). Those checks are pure functions of the staged bytes, the frozen job
configuration, the trusted input schema and the EA version. The seal records all
of those identities after one complete pass; at start ``sealed`` recomputes them
(O(1)) and re-hashes every member's staged SET and INI against the manifest (one
streaming pass, no parsing). Identical inputs give identical check results, so a
valid seal stands in for the semantic pass. Any mismatch, or no seal (packages
prepared before this change), falls back to the full checks, which raise the
precise error. The seal lives next to the package (``packages/<id>.seal.json``),
outside the hashed package tree, with the same local trust as preparation.json.
"""
import hashlib
import json
from pathlib import Path
import re

from campaign_ledger import sha

SCHEMA_VERSION = 1
CHECKS = ('alias', 'staged_set_sha256', 'staged_ini_sha256', 'strategy_values', 'frozen_tester',
          'ini_tester', 'inline_inputs', 'paste_inputs')


def seal_path(package):
    package = Path(package)
    return package.parent / (package.name + '.seal.json')


CHECKER_SOURCES = ('studio_batch_seal.py', 'studio_optimization_inputs.py', 'studio_input_readback.py',
                   'studio_strategy_settings.py', 'studio_native_request.py')


def checker_sha256():
    """Hash of the code that performs the sealed checks.

    A controller upgrade that changes how members are rendered or checked (for
    example explicit_optimization_inputs) invalidates every older seal, so the
    first start after it runs the full checks again under the new code.
    """
    here = Path(__file__).resolve().parent
    return sha([hashlib.sha256((here / name).read_bytes()).hexdigest() for name in CHECKER_SOURCES])


def _identity(package, job, schema):
    raw = (Path(package) / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    plan = json.loads((Path(package) / 'studio-plan.json').read_text(encoding='utf-8'))
    return manifest, plan, dict(
        schema_version=SCHEMA_VERSION, job_id=job['job_id'], configuration_sha256=job['configuration_sha256'],
        manifest_sha256=hashlib.sha256(raw).hexdigest(), plan_sha256=sha(plan),
        preparation_sha256=hashlib.sha256((Path(package) / 'preparation.json').read_bytes()).hexdigest(),
        input_schema_sha256=sha(schema), ea_version=plan['research_binding']['ea_version'],
        research_binding_sha256=sha(plan['research_binding']), member_count=len(manifest['jobs']), checks=list(CHECKS),
        checker_sha256=checker_sha256())


def verify_member(package, member, item, schema, ea_version):
    """Every semantic check the start path makes for one member; returns its native material."""
    from studio_native_request import ini_sections
    from studio_optimization_inputs import explicit_optimization_inputs
    from studio_input_readback import explicit_paste_inputs
    from studio_strategy_settings import read_values
    alias = item['run_alias']
    if not re.fullmatch(r'R[0-9a-f]{20}', alias):
        raise ValueError('Invalid batch alias')
    staged_set = (Path(package) / (alias + '.set')).read_bytes()
    staged_ini = (Path(package) / (alias + '.ini')).read_bytes()
    if (hashlib.sha256(staged_set).hexdigest() != item['staged_sha256']
            or hashlib.sha256(staged_ini).hexdigest() != item['ini_sha256']):
        raise ValueError('Prepared batch member artifact changed')
    if schema is None or sha(schema) != member['strategy']['schema_hash']:
        raise ValueError('Trusted input schema does not match frozen member')
    if read_values(staged_set) != (member['strategy']['values'] | {'EA_Desc': alias}):
        raise ValueError('Prepared batch strategy differs from frozen member')
    if any(str(value) != str(item['tester'].get(key)) for key, value in member['tester'].items()):
        raise ValueError('Prepared batch tester differs from frozen member')
    sections = ini_sections(staged_ini)
    if sections.get('Tester') != {key: str(value) for key, value in item['tester'].items()}:
        raise ValueError('Prepared INI differs from frozen tester')
    text = staged_set.decode('utf-16')
    native = explicit_optimization_inputs(text, schema) if ea_version == '1.49' else text
    if sections.get('TesterInputs') != read_values(native.encode('utf-16')):
        raise ValueError('Inline input drift')
    return dict(sections=sections, paste_inputs=explicit_paste_inputs(sections['TesterInputs'], schema), alias=alias)


def verify_all(package, job, schema):
    from studio_batch_contract import configuration_members
    manifest, plan, _ = _identity(package, job, schema)
    members = configuration_members(job['configuration'])
    if len(members) != len(manifest['jobs']):
        raise ValueError('Prepared batch member count changed')
    aliases = [item['run_alias'] for item in manifest['jobs']]
    if len(set(aliases)) != len(aliases):
        raise ValueError('Invalid or duplicate native alias')
    ea_version = plan['research_binding']['ea_version']
    return [verify_member(package, member, item, schema, ea_version) for member, item in zip(members, manifest['jobs'])]


def write(package, job, schema):
    """Full pass, then seal. Called by prepare-batch; refuses rather than seal a failing member."""
    from studio_bridge import write_json
    verify_all(package, job, schema)
    _, _, body = _identity(package, job, schema)
    write_json(seal_path(package), body | dict(seal_sha256=sha(body)))
    return body


def sealed(package, job, schema):
    """True only if the seal matches the current package, job and schema, and every byte is unchanged."""
    path = seal_path(package)
    try:
        if not path.is_file() or sha(job['configuration']) != job['configuration_sha256']:
            return False
        recorded = json.loads(path.read_text(encoding='utf-8'))
        stamp = recorded.pop('seal_sha256', None)
        manifest, _, current = _identity(package, job, schema)
        if stamp != sha(recorded) or recorded != current:
            return False
        for item in manifest['jobs']:
            alias = item['run_alias']
            if not re.fullmatch(r'R[0-9a-f]{20}', alias):
                return False
            for suffix, key in (('.set', 'staged_sha256'), ('.ini', 'ini_sha256')):
                if hashlib.sha256((Path(package) / (alias + suffix)).read_bytes()).hexdigest() != item[key]:
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False
