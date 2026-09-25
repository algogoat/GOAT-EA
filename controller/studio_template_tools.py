"""Clone real optimization templates with narrow, validated, attributable edits.

No terminal, queue, catalog or source-file mutation. Validation is structural and
partially dependency-aware; it is not a profitability or complete semantic audit.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

from campaign_ledger import sha
from studio_strategy_settings import read_values,validate_strategy
from studio_dependencies import audit_dependencies

MAX_SET_BYTES=2_000_000
LIMITATIONS=[
    'Input types, declared enum ladders and numeric range geometry are checked.',
    'Dependency coverage is limited to the shipped indicator-mode policy; unchecked axes require source-aware review.',
    'No broker history, runtime initialization, order sizing, economic effect or profitability is established.',
    'A range edit creates an untested search space. Source measurements do not become measurements of the new variant.'
]

def source_bytes(path):
    path=Path(path).resolve()
    raw=path.read_bytes()
    if not raw or len(raw)>MAX_SET_BYTES: raise ValueError('SET must be nonempty and at most 2 MB')
    if not raw.startswith(b'\xff\xfe'): raise ValueError('GOAT template requires UTF-16 LE BOM; clone an original released SET')
    text=raw[2:].decode('utf-16-le')
    if '\x00' in text: raise ValueError('NUL is forbidden in SET text')
    without_crlf=text.replace('\r\n','')
    if '\r' in without_crlf or '\n' in without_crlf or '\r\n' not in text:
        raise ValueError('GOAT template requires consistent CRLF line endings')
    return path,raw,text

def validate_raw(raw,schema,policy,*,require_optimization=False):
    values=read_values(raw)
    checked=validate_strategy(values,schema)
    audit=audit_dependencies(checked,schema,policy)
    errors=[item['message'] for item in audit['findings'] if item['severity']=='error']
    if errors: raise ValueError('Inactive optimization axis: '+'; '.join(errors))
    if require_optimization and not checked['axes']:
        raise ValueError('No enabled optimization axes; fixed exports are not optimization templates')
    return dict(schema_version=1,status='structural_checks_passed',sha256=hashlib.sha256(raw).hexdigest(),
        schema_hash=sha(schema),input_count=len(values),ea_desc=values['EA_Desc'],encoding='utf-16-le-bom',newline='CRLF',
        kind='optimization_template' if checked['axes'] else 'fixed_settings',
        active_axes=checked['axes'],cartesian_combinations=math.prod(checked['axes'].values()),
        dependency_audit=audit,execution_ready=False,performance_evidence='not_tested_by_this_command',limitations=LIMITATIONS)

def validate_set(path,schema,policy,*,require_optimization=False):
    resolved,raw,_=source_bytes(path)
    return validate_raw(raw,schema,policy,require_optimization=require_optimization)|dict(path=str(resolved))

def _text(value,name,limit=12000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or '\x00' in value:
        raise ValueError('Nonempty bounded text required: '+name)
    return value.strip()

def build_set(source,output,spec,schema,policy,*,controller_version,ea_version,forbidden_roots=()):
    source,original,text=source_bytes(source);output=Path(output).resolve()
    if output.suffix.lower()!='.set': raise ValueError('Output must have a .set extension')
    if output==source: raise ValueError('Source/in-place overwrite is forbidden; choose a new variant path')
    if any(output.is_relative_to(Path(root).resolve()) for root in forbidden_roots):
        raise ValueError('Output is inside the publisher catalog; choose a local variant folder')
    support=output.with_suffix('.md');receipt=output.with_suffix('.build.json')
    if any(p.exists() for p in (output,support,receipt)):
        raise ValueError('Output or support/provenance file already exists; no overwrite is allowed')
    required={'ea_desc','changes','rationale','summary','entry_logic','ladder_exits','intended_role'}
    if not isinstance(spec,dict) or set(spec)!=required:
        raise ValueError('Build spec requires exactly: '+', '.join(sorted(required)))
    description=_text(spec['ea_desc'],'ea_desc',160)
    if any(c in description for c in '\r\n;=') or '@{' in description:
        raise ValueError('EA description must be single-line plain text, without protocol tags')
    for field in ('summary','entry_logic','ladder_exits','intended_role'):_text(spec[field],field)
    changes,rationale=spec['changes'],spec['rationale']
    if not isinstance(changes,dict) or not changes or len(changes)>len(schema['inputs']):
        raise ValueError('Provide a nonempty bounded changes map')
    if not isinstance(rationale,dict) or set(rationale)!=set(changes):
        raise ValueError('Every changed input requires its own rationale, with no extra keys')
    values=read_values(original)
    # Validate the source before changing it; template tools are not a hidden
    # compatibility migration or a way to repair an unknown source interface.
    validate_raw(original,schema,policy)
    for name,value in changes.items():
        if name=='EA_Desc' or name not in schema['inputs']:
            raise ValueError('Unknown input or reserved EA_Desc change: '+str(name))
        if not isinstance(value,str) or any(c in value for c in '\r\n\x00') or len(value)>8192:
            raise ValueError('Replacement must be one bounded SET value string: '+name)
        if value==values[name]: raise ValueError('Replacement is unchanged: '+name)
        _text(rationale[name],'rationale.'+name)
    variant_id=uuid.uuid4().hex
    description+=' ['+variant_id[:12]+']'
    replacements=changes|{'EA_Desc':description}
    lines=text.splitlines(keepends=True)
    edited=[]
    for line in lines:
        key=line.split('=',1)[0]
        if key in replacements and not line.lstrip().startswith(';'):
            newline='\r\n' if line.endswith('\r\n') else ''
            edited.append(key+'='+replacements[key]+newline)
        else: edited.append(line)
    built=b'\xff\xfe'+''.join(edited).encode('utf-16-le')
    after=read_values(built)
    expected=values|replacements
    if after!=expected: raise ValueError('Narrow replacement verification failed')
    validation=validate_raw(built,schema,policy,require_optimization=True)
    delta=[dict(input=name,before=values[name],after=value,rationale=rationale.get(name,'Unique new variant identity; source identity retained in provenance')) for name,value in replacements.items()]
    record=dict(schema_version=1,variant_id=variant_id,created_utc=datetime.now(timezone.utc).isoformat(),
        status='untested_variant',controller_version=controller_version,ea_version=ea_version,
        source=dict(path=str(source),sha256=hashlib.sha256(original).hexdigest(),ea_desc=values['EA_Desc']),
        output=dict(path=str(output),sha256=validation['sha256'],ea_desc=description),
        support_path=str(support),changes=delta,validation=validation,
        authored_notes={key:spec[key] for key in ('summary','entry_logic','ladder_exits','intended_role')},
        matrix_registration_required=True,source_measurements_inherited=False)
    notes='# '+description+'\n\n**Untested research variant.** Structural validation is not performance evidence.\n\n'
    notes+='## Design notes\n\nThe following rationale was supplied by the author and requires review against active EA logic.\n\n'
    for label,key in [('Summary','summary'),('Entry logic','entry_logic'),('Ladder and exits','ladder_exits'),('Intended portfolio role','intended_role')]:
        notes+='### '+label+'\n\n'+spec[key].strip()+'\n\n'
    notes+='## Input changes\n\n'
    for change in delta:
        notes+='- **'+change['input']+'**: `'+change['before']+'` → `'+change['after']+'`. '+change['rationale']+'\n'
    notes+='\n## Provenance and evidence\n\n'
    notes+='Source SET SHA-256: `'+record['source']['sha256']+'`. New SET SHA-256: `'+validation['sha256']+'`.\n\n'
    notes+='No asset benchmark or frozen-period validation has been executed for this variant. Any measurements of the parent remain source-reference evidence only. Record failures, cancellations, actual counts and subsequent tests in local matrix history; do not overwrite earlier findings.\n\n'
    notes+='Active search axes: '+str(len(validation['active_axes']))+'. Cartesian combinations: '+str(validation['cartesian_combinations'])+' (not a promised genetic pass count).\n\n'
    notes+='Dependency coverage: `'+validation['dependency_audit']['coverage']+'`. Unchecked axes: '+', '.join(validation['dependency_audit']['unchecked_axes'])+'.\n\n'
    notes+='\n'.join('- '+limitation for limitation in LIMITATIONS)+'\n'
    note_bytes=notes.encode('utf-8');record['support_sha256']=hashlib.sha256(note_bytes).hexdigest()
    if source.read_bytes()!=original: raise ValueError('Source changed during validation; review before rebuilding')
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents races overwriting user files. The receipt is
    # published last. Incomplete I/O remains visible; never overwrite on retry.
    for path,data in ((output,built),(support,note_bytes),(receipt,(json.dumps(record,indent=2,ensure_ascii=False)+'\n').encode('utf-8'))):
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return record|dict(receipt_path=str(receipt))
