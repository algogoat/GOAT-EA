"""Clone real optimization templates with narrow, validated, attributable edits.

No terminal, queue, catalog or source-file mutation. Validation is structural and
partially dependency-aware; it is not a profitability or complete semantic audit.
A blank starting point (`starter_set`) is generated from the installed input schema,
never from a hand-written file, so it cannot drift from the EA's input interface.
"""
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid

from campaign_ledger import sha
from studio_strategy_settings import INTEGER_LIMITS,numeric,read_values,validate_strategy
from studio_dependencies import audit_dependencies

MAX_SET_BYTES=2_000_000
RISK_SIZING_CODE='RISK_PER_SEQUENCE_NEEDS_TWO_TRADES'
RISK_SIZING_MESSAGE=('Risk-per-sequence sizing needs at least 2 sequence trades; use fixed lots or raise '
                     'Max_Seq_Trades (single-trade % risk returns in the next EA build).')
RISK_NOT_CHOSEN_CODE='RISK_NOT_CHOSEN'
STARTER_SHAPES=('single','sequence')
STARTER_DESCRIPTIONS={'single':'Starter Single Trade','sequence':'Starter Sequence'}
STARTER_SEQUENCE_MAX_TRADES='5'
STARTER_RECEIPT_SUFFIX='.starter.json'
STARTER_HEADER='; GOAT starter SET'
# Optional entry filters outside the dependency policy's indicator modes, each turned off by its exact enum label.
STARTER_OPTIONAL_FILTERS={
    'Mode_Bias':('Bias_Disabled','GOAT AI bias filter off: it can block or close entries and needs recorded bias data. '
                 'Bias_Display would still load bias data, so Bias_Disabled is the true off state.'),
    'Mode_News':('News_Disabled','News filter off; turn it on only when the idea is about news.')}
STARTER_LIMITATIONS=[
    'Structurally valid against the installed input schema; it is a blank, not a strategy.',
    'No entry signal is on. The EA treats a disabled signal mode as "pass", so an unchanged starter opens a new '
    'sequence at every signal check whenever none is open (both directions with the default Long_and_Short and '
    'Allow_Opposite_Seq=true). Use build-set to add the idea\'s entry filter(s) before any test.',
    'No input is searched. build-set must add at least one search axis before a batch can use it.',
    'Every other input is its declared default; defaults are not recommended settings and the starter has zero evidence.'
]
_NUMBER=re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
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

def _reachable(encoded,definition):
    """(current, ladder) of one structurally valid value: ladder is (start, step, stop) only for an active Y axis.
    A dormant `value||start||step||stop||N` tuple runs with its first field, exactly as MT5 reads it."""
    parts=encoded.split('||')
    current=numeric(parts[0],definition)
    if len(parts)==5 and parts[4]=='Y':
        return current,(numeric(parts[1],definition),numeric(parts[2],definition,step=True),numeric(parts[3],definition))
    return current,None

def can_reach(encoded,definition,target):
    current,ladder=_reachable(encoded,definition)
    if current==target: return True
    if ladder is None: return False
    start,step,stop=ladder
    return start<=target<=stop and ((target-start)/step).denominator==1

def lowest_reachable(encoded,definition):
    current,ladder=_reachable(encoded,definition)
    return current if ladder is None else min(current,ladder[0])

def check_risk_sizing(values,schema):
    """Unconditional money-safety rule for every SET (catalog, fork, starter, build output, batch member).

    With Mode_Lots=RiskperSeq the EA solves the first lot from the planned loss path over levels
    1..Max_Seq_Trades-1. With Max_Seq_Trades<=1 that path is empty (planned loss 0), so the solver
    climbs to the broker's maximum volume. Any reachable combination is refused: the current value,
    every value of an active ladder, and the first field of a dormant N tuple."""
    inputs=schema['inputs']
    lots,trades=inputs.get('Mode_Lots'),inputs.get('Max_Seq_Trades')
    choices=(lots or {}).get('enum_choices') or {}
    if trades is None or 'RiskperSeq' not in choices or 'Mode_Lots' not in values or 'Max_Seq_Trades' not in values:
        return
    if (can_reach(values['Mode_Lots'],lots,Fraction(choices['RiskperSeq']))
            and lowest_reachable(values['Max_Seq_Trades'],trades)<=1):
        raise ValueError(RISK_SIZING_CODE+': '+RISK_SIZING_MESSAGE)

def validate_raw(raw,schema,policy,*,require_optimization=False):
    values=read_values(raw)
    checked=validate_strategy(values,schema)
    check_risk_sizing(values,schema)
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

def _new_output(output,forbidden_roots):
    output=Path(output).resolve()
    if output.suffix.lower()!='.set': raise ValueError('Output must have a .set extension')
    if any(output.is_relative_to(Path(root).resolve()) for root in forbidden_roots):
        raise ValueError('Output is inside the publisher catalog; choose a local variant folder')
    return output

def _write_new(files):
    # Exclusive creation prevents races overwriting user files. The receipt is
    # published last. Incomplete I/O remains visible; never overwrite on retry.
    for path,data in files:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())

def _receipt_bytes(record):
    return (json.dumps(record,indent=2,ensure_ascii=False)+'\n').encode('utf-8')

def schema_default(name,definition,defines=None):
    """The SET value of one input's declared default; refuses anything that is not a plain literal."""
    defines=defines or {}
    expression=str(definition['default_expression']).strip()
    for _ in range(4):  # follow #define aliases such as GOAT_DEFAULT_BIAS_MODE -> Bias_Opens
        if expression not in defines: break
        expression=str(defines[expression]).strip()
    kind=definition['type'];choices=definition.get('enum_choices')
    if choices is not None:
        if expression in choices: return str(choices[expression])
        if re.fullmatch(r'-?\d+',expression) and int(expression) in choices.values(): return str(int(expression))
    elif kind=='string':
        match=re.fullmatch(r'"([^"\\\r\n\x00]*)"',expression)
        if match: return match[1]
    elif kind=='bool':
        if expression in ('true','false'): return expression
    elif kind=='datetime':
        match=re.fullmatch(r"D'(\d{4}\.\d{2}\.\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?)'",expression)
        if match: return match[1]
    elif kind in INTEGER_LIMITS:
        if re.fullmatch(r'[+-]?\d+',expression): return expression
    elif kind in ('double','float'):
        if _NUMBER.fullmatch(expression): return expression if any(c in expression for c in '.eE') else expression+'.0'
    raise ValueError('Installed schema default is not a plain literal; refusing to guess a starter value: '+name+'='+expression)

def signal_modes(policy):
    """Indicator signal modes in policy order, each with the exact value that disables it."""
    modes={}
    for rule in policy['rules']: modes.setdefault(rule['controller'],str(int(rule['disabled'])))
    return modes

def starter_values(shape,schema,policy):
    if shape not in STARTER_SHAPES: raise ValueError('Starter shape must be single or sequence')
    inputs=schema['inputs'];defines=schema.get('defines') or {}
    defaults={name:schema_default(name,definition,defines) for name,definition in inputs.items()}
    values=dict(defaults);fixes=[]
    def enum_value(name,label):
        choices=inputs[name].get('enum_choices') or {}
        if label not in choices: raise ValueError('Installed schema has no '+label+' choice for '+name+'; the starter cannot be built')
        return str(choices[label])
    def fix(name,value,reason):
        if name not in inputs: raise ValueError('Installed schema has no '+name+'; the starter cannot be built for this EA')
        if value!=defaults[name]: fixes.append(dict(input=name,schema_default=defaults[name],value=value,reason=reason))
        values[name]=value
    fix('EA_Desc',STARTER_DESCRIPTIONS[shape],'Readable starter identity; build-set appends a unique variant suffix to every variant.')
    for mode,disabled in signal_modes(policy).items():
        if mode not in inputs or int(disabled) not in (inputs[mode].get('enum_choices') or {}).values():
            raise ValueError('Dependency policy names a signal mode the installed schema cannot disable: '+mode)
        fix(mode,disabled,'Entry signal off. A blank starter enables no indicator; switch on only what the idea needs.')
        must_check=mode.removesuffix('_Mode')+'_MustCheck'
        if must_check in inputs and inputs[must_check]['type']=='bool':
            fix(must_check,'false','MustCheck only matters with its signal on; off with the signal.')
    for name,(label,reason) in STARTER_OPTIONAL_FILTERS.items():
        if name in inputs: fix(name,enum_value(name,label),reason)
    if shape=='single':
        fix('Max_Seq_Trades','1','Single trade: one entry per signal and no adds (Max_Seq_Trades=1).')
        fix('CloseAtMaxLevels','true','With one trade, reaching the next gap against it closes it, so Grid_Size acts as the stop. '
            'Off, a losing single trade would be held with no stop (SL_Pips defaults to 0).')
    else:
        fix('Max_Seq_Trades',STARTER_SEQUENCE_MAX_TRADES,'Conservative sequence: at most '+STARTER_SEQUENCE_MAX_TRADES+
            ' trades (schema default 10). Grid_* gaps and lot growth stay at their declared defaults.')
        fix('CloseAtMaxLevels','true','Close the whole sequence at the next gap after its last trade instead of holding it open.')
        fix('Mode_Lots',enum_value('Mode_Lots','RiskperSeq'),'Size the first trade from Risk, the money one sequence may lose, instead of fixed lots.')
        fix('Sequence_MLPS_Hard_Close','true','Hard-close a sequence whose loss reaches Risk.')
    return values,fixes,defaults

def starter_set(shape,output,schema,policy,*,controller_version,ea_version,forbidden_roots=()):
    """Write a blank, valid starter SET (no entry filter, no search axis) and its receipt. Create-only."""
    if shape not in STARTER_SHAPES: raise ValueError('Starter shape must be single or sequence')
    output=_new_output(output,forbidden_roots)
    receipt=output.with_suffix(STARTER_RECEIPT_SUFFIX)
    if any(p.exists() for p in (output,receipt)):
        raise ValueError('Output or starter receipt already exists; no overwrite is allowed')
    values,fixes,_=starter_values(shape,schema,policy)
    choices=[]
    if shape=='sequence' and 'Risk' in values:
        choices.append(dict(input='Risk',placeholder=values['Risk'],reason='Money one failed sequence may lose (RiskperSeq sizing and the '
            'hard close). '+values['Risk']+' is only the schema default, not a recommendation: on a 1,000 demo it is half the account. '
            'build-set from this starter refuses until its changes set Risk explicitly to the amount the user chose.'))
    lines=[STARTER_HEADER+' ('+shape+'): '+values['EA_Desc'],
           '; Generated by goat studio starter-set from the installed input schema. Every input not listed in the',
           '; .starter.json receipt is its declared default. Input declaration SHA-256: '+schema['source_sha256'],
           '; UNTESTED: no entry filter is on and nothing is searched. It has zero evidence; build your idea with build-set.']
    lines+=['; '+c['input']+'='+c['placeholder']+' is a placeholder, not a choice: build-set requires the user\'s own '+c['input']+'.' for c in choices]
    lines+=[name+'='+values[name] for name in schema['inputs']]
    raw=b'\xff\xfe'+''.join(line+'\r\n' for line in lines).encode('utf-16-le')
    if len(raw)>MAX_SET_BYTES or read_values(raw)!=values: raise ValueError('Starter generation verification failed')
    validation=validate_raw(raw,schema,policy)
    if validation['active_axes'] or validation['kind']!='fixed_settings': raise ValueError('Starter must have no active search axis')
    record=dict(schema_version=1,kind='goat_starter_set',shape=shape,parent_label='starter:'+shape,status='untested_starter',
        created_utc=datetime.now(timezone.utc).isoformat(),controller_version=controller_version,ea_version=ea_version,
        schema_hash=sha(schema),input_declaration_sha256=schema['source_sha256'],
        dependency_policy=dict(header_sha256=policy['header_sha256'],main_sha256=policy['main_sha256'],coverage=policy['coverage']),
        output=dict(path=str(output),sha256=validation['sha256'],ea_desc=values['EA_Desc']),input_count=len(values),
        fixes=fixes,user_choices_required=choices,entry_filters_enabled=[],active_axes={},validation=validation,
        performance_evidence='none: a new idea starts with zero evidence',execution_ready=False,
        next_step='build-set --source <this .set> --output <new .set> --spec <changes.json>: add the entry filter(s), '
                  'at least one search axis'+(' and the user\'s own Risk' if choices else ''),
        limitations=STARTER_LIMITATIONS)
    receipt_raw=_receipt_bytes(record)
    _write_new(((output,raw),))
    try:_write_new(((receipt,receipt_raw),))
    except BaseException:
        # A starter without its receipt cannot be built on (see starter_parent); remove only the file this call created.
        if output.read_bytes()==raw: output.unlink()
        raise
    return record|dict(receipt_path=str(receipt),receipt_sha256=hashlib.sha256(receipt_raw).hexdigest())

def starter_parent(source,original,schema):
    """The starter receipt beside a source SET, verified against its exact bytes; None for any other SET.
    An unmodified starter (its generated header and starter EA_Desc) without its receipt is refused."""
    receipt=Path(source).with_suffix(STARTER_RECEIPT_SUFFIX)
    if not receipt.is_file():
        text=original[2:].decode('utf-16-le')
        if text.startswith(STARTER_HEADER) and read_values(original).get('EA_Desc') in STARTER_DESCRIPTIONS.values():
            raise ValueError('This is a GOAT starter without its .starter.json receipt beside it; keep the receipt next to '
                             'the starter or create a new one with starter-set')
        return None
    raw=receipt.read_bytes()
    if len(raw)>MAX_SET_BYTES: raise ValueError('Starter receipt exceeds 2 MB')
    try:value=json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError,ValueError) as exc: raise ValueError('Starter receipt beside the source is not valid JSON') from exc
    if not isinstance(value,dict) or value.get('kind')!='goat_starter_set' or value.get('shape') not in STARTER_SHAPES:
        raise ValueError('File beside the source is not a GOAT starter receipt')
    if value.get('output',{}).get('sha256')!=hashlib.sha256(original).hexdigest():
        raise ValueError('Starter SET changed since its .starter.json receipt; create a new starter with starter-set')
    if value.get('schema_hash')!=sha(schema):
        raise ValueError('Starter was generated for a different installed input schema; create a new starter with starter-set')
    return dict(label='starter:'+value['shape'],shape=value['shape'],receipt_path=str(receipt.resolve()),
                receipt_sha256=hashlib.sha256(raw).hexdigest(),starter_sha256=value['output']['sha256'])

def _uses_risk(values,schema):
    """True when Risk can size or close: RiskperSeq is reachable, or the hard close at Risk is on."""
    inputs=schema['inputs'];choices=(inputs.get('Mode_Lots') or {}).get('enum_choices') or {}
    risk_lots='RiskperSeq' in choices and 'Mode_Lots' in values and can_reach(values['Mode_Lots'],inputs['Mode_Lots'],Fraction(choices['RiskperSeq']))
    hard_close='Sequence_MLPS_Hard_Close' in values and values['Sequence_MLPS_Hard_Close'].split('||')[0] in ('true','1')
    return risk_lots or hard_close

def _starter_checks(values,schema,policy,changes):
    """Second line of the money-safety rules plus honest notes for a variant whose parent is a blank starter."""
    check_risk_sizing(values,schema)   # validate_raw already applied it to every SET; kept here as a second line
    if 'Risk' in schema['inputs'] and _uses_risk(values,schema) and 'Risk' not in changes:
        raise ValueError(RISK_NOT_CHOSEN_CODE+': this starter sizes or closes by Risk (money lost per sequence) and its '
                         'Risk is only the schema placeholder. Ask the user for the amount and set Risk explicitly in changes.')
    enabled=[]
    for mode,disabled in signal_modes(policy).items():
        if mode in values and not (values[mode].split('||')[0]==disabled and not values[mode].endswith('||Y')):
            enabled.append(mode)
    warnings=[] if enabled else ['No entry signal is enabled: the EA opens a new sequence at every signal check whenever none is '
                                 'open. Keep this only when "always in the market" (for example a pure session or grid idea) is the plan.']
    return enabled,warnings

def build_set(source,output,spec,schema,policy,*,controller_version,ea_version,forbidden_roots=()):
    source,original,text=source_bytes(source);output=_new_output(output,forbidden_roots)
    if output==source: raise ValueError('Source/in-place overwrite is forbidden; choose a new variant path')
    starter=starter_parent(source,original,schema)
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
        # From a starter, Risk must be stated even when the user's amount equals the placeholder.
        if value==values[name] and not (starter is not None and name=='Risk'): raise ValueError('Replacement is unchanged: '+name)
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
    if starter is not None:
        starter['entry_filters_enabled'],starter['warnings']=_starter_checks(after,schema,policy,changes)
    delta=[dict(input=name,before=values[name],after=value,rationale=rationale.get(name,'Unique new variant identity; source identity retained in provenance')) for name,value in replacements.items()]
    record=dict(schema_version=1,variant_id=variant_id,created_utc=datetime.now(timezone.utc).isoformat(),
        status='untested_variant',controller_version=controller_version,ea_version=ea_version,
        parent=starter['label'] if starter else 'set',
        source=dict(path=str(source),sha256=hashlib.sha256(original).hexdigest(),ea_desc=values['EA_Desc']),
        output=dict(path=str(output),sha256=validation['sha256'],ea_desc=description),
        support_path=str(support),changes=delta,validation=validation,
        authored_notes={key:spec[key] for key in ('summary','entry_logic','ladder_exits','intended_role')},
        matrix_registration_required=True,source_measurements_inherited=False)
    if starter is not None: record['starter']=starter
    notes='# '+description+'\n\n**Untested research variant.** Structural validation is not performance evidence.\n\n'
    notes+='## Design notes\n\nThe following rationale was supplied by the author and requires review against active EA logic.\n\n'
    for label,key in [('Summary','summary'),('Entry logic','entry_logic'),('Ladder and exits','ladder_exits'),('Intended portfolio role','intended_role')]:
        notes+='### '+label+'\n\n'+spec[key].strip()+'\n\n'
    notes+='## Input changes\n\n'
    for change in delta:
        notes+='- **'+change['input']+'**: `'+change['before']+'` → `'+change['after']+'`. '+change['rationale']+'\n'
    notes+='\n## Provenance and evidence\n\n'
    notes+='Source SET SHA-256: `'+record['source']['sha256']+'`. New SET SHA-256: `'+validation['sha256']+'`.\n\n'
    if starter is not None:
        notes+='Parent: blank GOAT starter (`'+starter['label']+'`), generated from the installed input schema; starter receipt SHA-256: `'+starter['receipt_sha256']+'`. A starter has no results of any kind: this new idea starts with zero evidence.\n\n'
        notes+='Entry signals enabled: '+(', '.join(starter['entry_filters_enabled']) or 'none')+'.\n\n'
        notes+=''.join('**Warning:** '+warning+'\n\n' for warning in starter['warnings'])
        notes+='No asset benchmark or frozen-period validation has been executed for this variant. Record failures, cancellations, actual counts and subsequent tests in local matrix history; do not overwrite earlier findings.\n\n'
    else:
        notes+='No asset benchmark or frozen-period validation has been executed for this variant. Any measurements of the parent remain source-reference evidence only. Record failures, cancellations, actual counts and subsequent tests in local matrix history; do not overwrite earlier findings.\n\n'
    notes+='Active search axes: '+str(len(validation['active_axes']))+'. Cartesian combinations: '+str(validation['cartesian_combinations'])+' (not a promised genetic pass count).\n\n'
    notes+='Dependency coverage: `'+validation['dependency_audit']['coverage']+'`. Unchecked axes: '+', '.join(validation['dependency_audit']['unchecked_axes'])+'.\n\n'
    notes+='\n'.join('- '+limitation for limitation in LIMITATIONS)+'\n'
    note_bytes=notes.encode('utf-8');record['support_sha256']=hashlib.sha256(note_bytes).hexdigest()
    if source.read_bytes()!=original: raise ValueError('Source changed during validation; review before rebuilding')
    _write_new(((output,built),(support,note_bytes),(receipt,_receipt_bytes(record))))
    return record|dict(receipt_path=str(receipt))
