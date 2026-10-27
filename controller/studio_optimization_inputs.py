"""Render native optimization flags explicitly; frozen SET bytes stay untouched.

MT5 keeps the optimize flag and range of every input in the terminal's saved
tester profile (MQL5\\Profiles\\Tester\\<expert>.set). A plain ``name=value``
line in a startup [TesterInputs] section only replaces the value, so a flag
left at Y by an earlier tester session silently becomes an extra search axis.
Only an explicit five-part ``value||start||step||stop||N`` tuple clears it.
Every controller-generated tester input set therefore spells out the flag of
each optimizable input: active axes keep their exact frozen tuple (Y), all
other optimizable inputs become ``value||value||0||value||N``. (MT5's own
disabled form keeps a remembered range, e.g. ``true||false||0||true||N``; only
the final ``N`` matters.) Literal strings are never touched.
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
    # B50 (A0, GOAT-EA#269 P1): a SET written before an appended input omits it, and MT5 would keep that input's flag
    # and range from the saved tester profile. In a complete SET (every other optimizable input present: only such a
    # SET validates), each appended axis it omits is written at its declared default, fixed, as the EA's
    # GoatStudioExplicitOptimizationInputs writes it for the native config (OnTesterInit accepts it).
    from studio_strategy_settings import APPENDED_INPUTS, appended_default
    present = {line.split('=', 1)[0].strip() for line in lines if '=' in line and not line.lstrip().startswith(';')}
    axes = {name for name, definition in schema['inputs'].items() if definition['optimizable'] and definition['type'] != 'string'}
    for name in (APPENDED_INPUTS if axes - set(APPENDED_INPUTS) <= present else ()):
        definition = schema['inputs'].get(name)
        if definition and definition['optimizable'] and definition['type'] != 'string' and name not in present:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\r\n'
            value = appended_default(definition)
            lines.append(name+'='+value+'||'+value+'||0||'+value+'||N\r\n')
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
