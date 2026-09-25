"""Regenerate the shipped input reference from pinned V1.48 declarations."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
schema = json.loads((root/'controller/contracts/inputs.json').read_text())
policy = json.loads((root/'controller/contracts/dependencies.json').read_text())
raw = (root/'GOAT_Inputs_Definitions.mqh').read_bytes()
if hashlib.sha256(raw).hexdigest() != schema['source_sha256']:
    raise ValueError('Refresh the reviewed schema before regenerating this reference')
comments, groups, group = {}, {}, 'General'
for line in raw.decode('utf-8-sig').splitlines():
    section = re.match(r'\s*(?:input|sinput)\s+group\s+"([^"]+)"',line)
    if section: group = section[1].strip('= ')
    decl = re.match(r'\s*(?:input|sinput)\s+\w+\s+(\w+)\s*=',line)
    if decl and decl[1] in schema['inputs']:
        comments[decl[1]] = line.split('//',1)[1].strip() if '//' in line else 'See the mode and workflow notes below.'
        groups[decl[1]] = group
rules = {r['input']:r for r in policy['rules']}
def cell(s): return str(s).replace('|','\\|').replace('\n',' ')
lines = ['# GOAT V1.48 input reference','',
'This reference lists every input exposed by this installed build. Run `discover`',
'for the machine-readable schema and use `validate-set` before preparing a run.',
'Source defaults below are declaration defaults, not recommended portfolio settings.',
'A supplied optimization template has its own deliberate values and ranges.','',
'## Reading and changing inputs','',
'- SET values use `current||start||step||stop||Y` for enabled search axes; `N` fixes the current value. Preserve the template format with `build-set`.',
'- `sinput` and strings cannot be search dimensions. For enums use the exact numeric values listed below; contiguous numeric ranges are not always valid enum ladders.',
'- Dependency validation currently covers the listed indicator mode gates only. An unchecked axis still needs a behavior-based rationale; a valid file does not prove a useful search space.',
'- Never optimize identity, controller monitoring or credential fields. `EA_Desc` is generated uniquely for each variant/attempt. Keep credentials in the user’s own activation flow.',
'- Operation mode, sequence sizing, exits and signal modes work together. Begin with a reviewed template, explain each change, keep unused indicator dimensions fixed, and preserve untouched validation history.',
'- Optimization Studio tester and export settings are separate from these EA inputs. See [all Studio controls](goat-beta-agent-guide.md) for the 18 tester and nine export fields, including sequence capture and its time/storage cost.',
'- See [template creation](TEMPLATE-WORKFLOW.md), [capabilities](goat-agent-capabilities.md), and [seed research](SEED-WORKFLOW.md) for the supported workflows.','',
f'Input declaration SHA-256: `{schema["source_sha256"]}`. Dependency logic SHA-256: `{policy["main_sha256"]}`.',
f'This release contains **{len(schema["inputs"])} inputs**. The installed contract files retain the build defines and complete enum mapping.','']
last = None
for name, definition in schema['inputs'].items():
    section = groups[name]
    if section != last:
        lines += ['', f'## {section.title()}','', '| Input | Meaning / units from EA declaration | Type | Source default | Search axis |', '|---|---|---|---|---|']
        last = section
    lines.append('| '+ ' | '.join([f'`{name}`',cell(comments[name]),f'`{definition["type"]}`',f'`{cell(definition["default_expression"])}`','Allowed; validate dependency' if definition['optimizable'] else 'Fixed only'])+' |')
    # Keep enum choices in a separate section so the input table remains readable.
lines += ['', '## Enum choices', '', 'Names and numbers are exact. Do not infer omitted values or use a numeric ladder that crosses an undefined value.', '']
enums = {}
for definition in schema['inputs'].values():
    if definition['enum_choices']: enums[definition['type']] = definition['enum_choices']
for name, choices in enums.items():
    lines += [f'### {name}', '', ', '.join(f'`{label}={value}`' for label,value in choices.items())+'.','']
lines += ['## Validated indicator dependencies', '', 'An axis is rejected when its controlling mode is disabled throughout the search. A mixed enabled/disabled mode range produces a conditional warning. Other behavior dependencies are not automatically certified.', '', '| Axis | Controlling mode | Disabled value |', '|---|---|---|']
for rule in policy['rules']: lines.append(f'| `{rule["input"]}` | `{rule["controller"]}` | `{rule["disabled"]}` |')
lines += ['', '## Reporting unclear behavior', '', 'Retain the exact installed versions, input schema hash, template hash, changed values, expected behavior and observed evidence. Use the private support workflow in the [agent guide](goat-beta-agent-guide.md). Preview the report with the user and submit its approved contents; never include activation secrets or another user’s paths/account.', '']
(root/'controller/INPUT-REFERENCE.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'inputs':len(schema['inputs']),'enums':len(enums),'document':'controller/INPUT-REFERENCE.md'}))