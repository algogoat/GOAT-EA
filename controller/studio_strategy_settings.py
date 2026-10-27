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


# B49a (F2, GOAT-EA#265): inputs appended to the v149 input header after B47's 114. A SET written before an input
# existed omits it, and the EA then runs that input's declared default, which reproduces the earlier build (SET
# compatibility: append-only inputs with legacy-reproducing defaults). Every other input stays required. The SET's own
# bytes and values are never rewritten: the controller writes MT5's tester profile from exactly the launch's
# [TesterInputs] (studio_tester_profile), so an omitted appended input runs its build default, and the EA's Studio
# accepts it in the readback only at that default (GOATStudioSettingCompare.mqh, GoatStudioFixedInternal).
# B49b appends its per-fix flags (GOAT-EA B49b PR-1: Fix_MoneyVolume), each defaulting Off = B49a.
APPENDED_INPUTS = ('Ledger_Mode', 'Fix_MoneyVolume')


def appended_default(definition):
    """The declared default of an appended input as a SET value; an enum label resolves to its declared number."""
    expression = definition['default_expression']
    enum = definition.get('enum_choices')
    return str(enum[expression]) if enum is not None and expression in enum else expression


def complete_appended_inputs(values, schema):
    """A copy of `values` in which every appended input it omits carries its declared default."""
    if not isinstance(values, dict):
        return values
    completed = dict(values)
    for name in APPENDED_INPUTS:
        if name in schema['inputs'] and name not in completed:
            completed[name] = appended_default(schema['inputs'][name])
    return completed


def validate_strategy(values, schema):
    definitions = schema['inputs']  # Trusted adapter supplies schema, not command JSON.
    # The checks see an omitted appended input at its default; the caller's own values are returned unchanged, so a
    # stored job, its registry SET and every SET hash stay as they were (Claude-Mac GOAT-EA#265 P1).
    original = values
    values = complete_appended_inputs(values, schema)
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
    check_risk_sizing(values, schema)    # the money-safety refusal is reported first
    check_enum_ladders(values, schema)   # ENUM_LADDER_NOT_NATIVE: a ladder the EA refuses at OnTesterInit
    from studio_ea_init_rules import check_ea_init   # imports numeric from here; bound at call time
    check_ea_init(values, schema)                    # EA_INIT_REFUSED: the EA's own OnInit refusals, every reachable value
    return dict(values=dict(original), axes=axes, source_sha256=schema['source_sha256'],
                dependency_validation='pending', execution_ready=False)


ENUM_LADDER_CODE = 'ENUM_LADDER_NOT_NATIVE'
ENUM_LADDER_EVIDENCE = ('GOAT V1.49.mq5:3949-3950, GoatStudioVerifyOptimizationInputs in '
                        'GOATOptimizationInputs.mqh:66-70')


def _native_enum_ladder(items, start, step, stop):
    """True when `start||step||stop||Y` is a form a real GOAT batch has passed OnTesterInit with.

    OnTesterInit compares every Y ladder with MT5's ParameterGetRange (enabled, value, start, step, stop) and
    refuses the batch on any difference. MT5 does not keep a stepped enum ladder as written: on 10-13
    `RSI_TF_=15||5||10||15||Y` (ENUM_MODE_TFs 0,1,5,15,60,240; both rungs declared) was refused with
    "Native optimization flag/value/range differs: RSI_TF_", while on 10-12 batch R87303ec90d13 ran 137-153
    passes per member with `Active_Time_Weekday=4||3||1||4||Y`. The MQL5 documentation does not say how the
    tester walks an enum (by item or by value) or which step ParameterGetRange reports for one, so only the
    proven form is accepted: step 1 over items that are consecutive in declaration order AND whose values are
    consecutive ascending integers. For such a ladder the item walk and the value ladder are the same list, so
    either reading runs exactly the rungs the controller (and the EA init-rule check) expands."""
    if step != 1:
        return False
    rungs = [start+index for index in range(int(stop-start)+1)]
    return any(items[first:first+len(rungs)] == rungs for first in range(len(items)-len(rungs)+1))


def native_enum_ladders(items):
    """Every `start||1||stop` (start<stop) an optimized enum with these declared values (in order) may use."""
    runs = []
    for first in range(len(items)):
        for last in range(first+1, len(items)):
            if items[last] != items[last-1]+1:
                break
            runs.append((items[first], items[last]))
    return runs


def check_enum_ladders(values, schema):
    """Refuse every active (Y) enum ladder the GOAT EA refuses at OnTesterInit, naming each one and its fix.

    Runs from validate_strategy, so validate-set, prepare-batch, seed-prepare/seed-start, build-set, the queue
    and drafts all agree. The EA's seed path skips its own check (GOAT V1.49.mq5:3941-3942), so this is the
    only gate that keeps a seed plan and the prove batch built from it on the same rule. It applies to every
    supported contract (V1.48 too): the ladder change is MT5's, not the EA's; V1.49 only detects it, and an older EA
    would silently run a search space other than the one the SET, the axis count and the init-rule check describe."""
    problems = []
    for name, encoded in values.items():
        definition = schema['inputs'].get(name) or {}
        choices = definition.get('enum_choices')
        if not choices or definition.get('type') == 'string' or not isinstance(encoded, str):
            continue
        parts = encoded.split('||')
        if len(parts) != 5 or parts[4] != 'Y':
            continue
        start, step, stop = (numeric(parts[1], definition), numeric(parts[2], definition, step=True),
                             numeric(parts[3], definition))
        items = list(choices.values())
        if _native_enum_ladder(items, start, step, stop):
            continue
        allowed = native_enum_ladders(items)
        allowed_text = (', '.join(f'{name}=<value>||{a}||1||{b}||Y' for a, b in allowed) if allowed else
                        'none: no two consecutive items of ' + definition['type'] + ' have consecutive values, so '
                        + name + ' cannot be an optimization axis')
        separate = 'timeframes' if name.endswith('_TF_') else 'values'
        rungs = ', '.join(str(int(start+index*step)) for index in range(int((stop-start)/step)+1))
        problems.append(
            f'{name}={encoded} walks {rungs} by {int(step)} over {definition["type"]} (declared in order '
            + ', '.join(str(item) for item in items) + '). Allowed form for an optimized enum: step 1 over '
            f'items that are consecutive in declaration order and in value; for {name} that is {allowed_text}. '
            f'Fix: fix {name} at one value ({name}={parts[0]}||{parts[1]}||{parts[2]}||{parts[3]}||N), '
            f'or list the {separate} ({rungs}) as separate members')
    if problems:
        raise ValueError(ENUM_LADDER_CODE + ': MT5 does not keep a stepped enum ladder exactly as written, so the GOAT '
                         'EA refuses the optimization before any pass ("Native optimization flag/value/range differs", '
                         + ENUM_LADDER_EVIDENCE + '; an EA before V1.49 has no such check and would search values '
                         'the SET does not say); only step 1 over consecutive declared items is proven to pass. '
                         + ' | '.join(problems))


RISK_SIZING_CODE = 'RISK_PER_SEQUENCE_NEEDS_TWO_TRADES'
RISK_SIZING_MESSAGE = ('Risk-per-sequence sizing needs at least 2 sequence trades; use fixed lots or raise '
                       'Max_Seq_Trades. Single-trade risk sizing isn\'t available yet. We\'ll say so in the release '
                       'notes when it ships.')
RISK_SIZING_SCHEMA_CODE = 'RISK_SIZING_SCHEMA_UNRECOGNISED'


def _reachable(encoded, definition):
    """(current, ladder) of one value: ladder is (start, step, stop) only for an active Y axis.
    A dormant `value||start||step||stop||N` tuple runs with its first field, exactly as MT5 reads it."""
    parts = encoded.split('||')
    current = numeric(parts[0], definition)
    if len(parts) == 5 and parts[4] == 'Y':
        return current, (numeric(parts[1], definition), numeric(parts[2], definition, step=True), numeric(parts[3], definition))
    return current, None


def can_reach(encoded, definition, target):
    current, ladder = _reachable(encoded, definition)
    if current == target:
        return True
    if ladder is None:
        return False
    start, step, stop = ladder
    return start <= target <= stop and ((target-start)/step).denominator == 1


def lowest_reachable(encoded, definition):
    current, ladder = _reachable(encoded, definition)
    return current if ladder is None else min(current, ladder[0])


def check_risk_sizing(values, schema):
    """Unconditional money-safety rule for every strategy the controller validates or stages.

    With Mode_Lots=RiskperSeq the EA solves the first lot from the planned loss path over levels
    1..Max_Seq_Trades-1. With Max_Seq_Trades<=1 that path is empty (planned loss 0), so the solver
    climbs to the broker's maximum volume. Any reachable combination is refused: the current value,
    every value of an active ladder and the first field of a dormant N tuple. A value missing from a
    partial SET is the EA's declared default. Fails closed when a schema with Mode_Lots no longer
    names RiskperSeq or Max_Seq_Trades, so a rename can never switch the rule off silently."""
    inputs = schema['inputs']
    lots, trades = inputs.get('Mode_Lots'), inputs.get('Max_Seq_Trades')
    if lots is None:
        return  # not a GOAT sizing interface (compact test schemas)
    choices = lots.get('enum_choices') or {}
    if 'RiskperSeq' not in choices or trades is None:
        raise ValueError(RISK_SIZING_SCHEMA_CODE + ': this input schema has Mode_Lots but no RiskperSeq choice or no '
                         'Max_Seq_Trades; the risk-per-sequence safety rule cannot be checked, so nothing is accepted')
    def value(name, definition):
        if name in values:
            return values[name]
        from studio_template_tools import schema_default
        return schema_default(name, definition, schema.get('defines'))
    if (can_reach(value('Mode_Lots', lots), lots, Fraction(choices['RiskperSeq']))
            and lowest_reachable(value('Max_Seq_Trades', trades), trades) <= 1):
        raise ValueError(RISK_SIZING_CODE + ': ' + RISK_SIZING_MESSAGE)
