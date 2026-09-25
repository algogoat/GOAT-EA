"""Typed MT5 input readback comparison; does not authorize native execution.

Active optimization tuples must remain byte-for-byte equal. Fixed numeric
inputs may acquire dormant N tuples; strings never undergo tuple parsing.
"""
from datetime import datetime, timezone
import re
from studio_strategy_settings import numeric, validate_strategy


def explicit_paste_inputs(values, schema):
    """Prevent MT5 scalar paste from inheriting previous optimization flags.

Only affects the native transport representation, never the source SET.
Disabled range placeholders are deliberately inert; active tuples and literal
strings remain exactly as supplied. Requires the trusted complete schema.
"""
    validate_strategy(values, schema)
    result = dict(values)
    for name, value in values.items():
        if schema['inputs'][name]['type'] != 'string' and '||' not in value:
            result[name] = value + '||0||0||0||N'
    return result


def verify_input_readback(wanted, observed, schema):
    checked = validate_strategy(wanted, schema)
    if set(observed) != set(wanted):
        raise ValueError('Readback input names differ')
    equivalent = []
    for name, expected in wanted.items():
        actual = observed[name]
        definition = schema['inputs'][name]
        if not isinstance(actual, str) or len(actual) > 8192 or any(c in actual for c in '\r\n\0'):
            raise ValueError('Malformed readback: '+name)
        if definition['type'] == 'string' or name in checked['axes']:
            if actual != expected:
                raise ValueError('Literal or active tuple changed: '+name)
            continue
        parts = actual.split('||')
        if len(parts) not in (1, 5) or (len(parts) == 5 and parts[4] != 'N'):
            raise ValueError('Fixed input optimization flag/tuple changed: '+name)
        value = expected.split('||')[0]
        if definition['type'] == 'datetime':
            fmt = '%Y.%m.%d' + (' %H:%M' if ' ' in value else '') + (':%S' if value.count(':') == 2 else '')
            epoch = int(datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp())
            equal = parts[0] == value or (re.fullmatch(r'\d{1,12}', parts[0]) is not None and int(parts[0]) == epoch)
        else:
            equal = numeric(value, definition) == numeric(parts[0], definition)
        if not equal:
            raise ValueError('Fixed input value changed: '+name)
        if actual != expected:
            equivalent.append(name)
    return dict(status='INPUT_READBACK_MATCH', input_count=len(wanted),
                exact_active_axes=sorted(checked['axes']), equivalent_fixed_inputs=equivalent,
                launch_authorized=False)
