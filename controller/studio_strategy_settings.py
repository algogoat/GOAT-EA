"""Structural SET validation against trusted source discovery, without MT5 effects.

Preserves values verbatim. Passing this check does not certify strategy dependencies,
broker limits, source/binary equivalence or readiness to execute.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re


INTEGER_LIMITS = {'int': (-(2**31), 2**31-1), 'uint': (0, 2**32-1),
                  'long': (-(2**63), 2**63-1), 'ulong': (0, 2**64-1)}


def read_values(raw):
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(';'):
            continue
        if '=' not in line:
            raise ValueError('SET line has no assignment')
        name, value = line.split('=', 1)
        if name in values:
            raise ValueError('Duplicate input: '+name)
        values[name] = value
    return values


def numeric(value, definition, *, step=False):
    kind = definition['type']
    if kind == 'bool' and not step:
        if value not in ('true', 'false', '0', '1'):
            raise ValueError('Boolean value required')
        return Fraction(int(value in ('true', '1')))
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
        raise ValueError('Numeric value required')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Invalid number') from exc
    if not number.is_finite() or abs(number) > Decimal('1.7976931348623157e308'):
        raise ValueError('Number outside supported finite range')
    # Bound textual exponent before Fraction conversion to prevent huge allocations.
    if abs(number.as_tuple().exponent) > 324 or (number and abs(number.adjusted()) > 324):
        raise ValueError('Number outside supported precision')
    enum = definition.get('enum_choices')
    if enum is not None or kind in INTEGER_LIMITS or kind == 'bool':
        if number != number.to_integral_value():
            raise ValueError('Integer value required')
        bounds = INTEGER_LIMITS.get(kind, (-(2**31), 2**31-1))
        if not bounds[0] <= number <= bounds[1]:
            raise ValueError('Integer outside type limits')
        if enum is not None and not step and int(number) not in enum.values():
            raise ValueError('Undeclared enum value')
    elif kind not in ('double', 'float'):
        raise ValueError('Unsupported numeric type: '+kind)
    if kind == 'float' and abs(number) > Decimal('3.402823466e38'):
        raise ValueError('Float outside type limits')
    return Fraction(number)


def validate_strategy(values, schema):
    definitions = schema['inputs']  # Trusted adapter supplies schema, not command JSON.
    if not isinstance(values, dict) or set(values) != set(definitions):
        missing = sorted(set(definitions)-set(values)) if isinstance(values, dict) else []
        extra = sorted(set(values)-set(definitions)) if isinstance(values, dict) else []
        raise ValueError(f'Complete explicit input set required; missing={missing}, unknown={extra}')
    axes = {}
    for name, encoded in values.items():
        try:
            if not isinstance(encoded, str) or len(encoded) > 8192 or any(c in encoded for c in '\r\n\0'):
                raise ValueError('Single-line bounded SET value required')
            definition = definitions[name]
            kind = definition['type']
            # Literal string values may contain ||; they never encode numeric axes.
            if kind == 'string':
                continue
            parts = encoded.split('||')
            if len(parts) not in (1, 5) or (len(parts) == 5 and parts[4] not in ('Y', 'N')):
                raise ValueError('Malformed optimization tuple')
            optimize = len(parts) == 5 and parts[4] == 'Y'
            if kind == 'datetime':
                if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?',parts[0]):
                    raise ValueError('Explicit datetime required')
                fmt = '%Y.%m.%d' + (' %H:%M' if ' ' in parts[0] else '') + (':%S' if parts[0].count(':') == 2 else '')
                datetime.strptime(parts[0], fmt)
                if optimize:
                    raise ValueError('Datetime optimization not yet supported')
                continue
            numeric(parts[0], definition)
            if not optimize:
                continue  # Dormant MT5 range placeholders are not active settings.
            if not definition['optimizable']:
                raise ValueError('Input not exposed for optimization')
            start, stop = numeric(parts[1], definition), numeric(parts[3], definition)
            step = numeric(parts[2], definition, step=True)
            if step <= 0 or start > stop:
                raise ValueError('Positive step and ascending range required')
            intervals = (stop-start)/step
            if intervals.denominator != 1:
                raise ValueError('Stop must lie on the requested step ladder')
            count = int(intervals)+1
            enum = definition.get('enum_choices')
            if enum is not None:
                choices = set(enum.values())
                if count > len(choices) or any(start+i*step not in choices for i in range(count)):
                    raise ValueError('Optimization ladder contains undeclared enum values')
            if kind == 'bool' and (start < 0 or stop > 1):
                raise ValueError('Boolean range outside 0..1')
            axes[name] = count
        except ValueError as exc:
            raise ValueError(name+': '+str(exc)) from exc
    return dict(values=dict(values), axes=axes, source_sha256=schema['source_sha256'],
                dependency_validation='pending', execution_ready=False)
