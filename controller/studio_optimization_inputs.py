"""Render native optimization flags explicitly; frozen SET bytes stay untouched.

MT5 keeps the optimize flag and range of every input in the terminal's saved
tester profile (MQL5\\Profiles\\Tester\\<expert>.set). A plain ``name=value``
line in a startup [TesterInputs] section only replaces the value, so a flag
left at Y by an earlier tester session silently becomes an extra search axis.
Only an explicit five-part ``value||start||step||stop||N`` tuple clears it.
Every controller-generated tester input set therefore spells out the flag of
each optimizable input: active axes keep their exact frozen tuple (Y), all
other optimizable inputs become ``value||value||0||value||N`` (the form MT5
itself writes for a disabled input). Literal strings are never touched.
"""


def explicit_optimization_inputs(text, schema):
    lines=[]
    for line in text.splitlines(keepends=True):
        body=line.rstrip('\r\n'); ending=line[len(body):]
        if '=' in body and not body.lstrip().startswith(';'):
            key,value=body.split('=',1)
            definition=schema['inputs'].get(key)
            if definition and definition['optimizable'] and definition['type']!='string' and '||' not in value:
                body=key+'='+value+'||'+value+'||0||'+value+'||N'
        lines.append(body+ending)
    return ''.join(lines)


def verify_explicit_inputs(values, schema, axes):
    """Refuse generated tester inputs whose effective axes MT5 could still change.

    ``values`` is the parsed [TesterInputs]/SET mapping, ``axes`` the frozen
    active axis names. Every optimizable non-string input must carry an
    explicit five-part tuple, flagged Y exactly for the frozen axes.
    """
    axes=set(axes)
    for key,value in values.items():
        definition=schema['inputs'].get(key)
        if not definition or definition['type']=='string' or not definition['optimizable']:
            continue
        parts=value.split('||')
        if len(parts)!=5 or parts[4] not in ('Y','N'):
            raise ValueError('Generated tester input has no explicit optimization flag: '+key)
        if (parts[4]=='Y')!=(key in axes):
            raise ValueError('Generated tester input flag differs from the frozen axes: '+key)
    missing=sorted(axes-set(values))
    if missing:
        raise ValueError('Generated tester inputs miss frozen axes: '+', '.join(missing))
    return values
