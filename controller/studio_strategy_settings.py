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
# B50 (A0, docs/b50/B50_ALPHA_DESIGN.md section 2) appends twelve more after Ledger_Mode: the single-trade engine and the
# New York clock. Their defaults (Engine_Grid, Clock_Server, no single-trade setting, no rollover block) reproduce B49a.
# B49b appends its per-fix flags (PR-1 Fix_MoneyVolume, PR-5 Gate_Recheck, PR-3 Fix_ClosePath), PR-6's pre-trade caps
# (Max_Spread_Points, Min_Margin_Level_PC; 0 = off), PR-4's Fix_Clock and the lag hotfix's Fix_FeedGuard, Diag_TickTiming
# and Fix_TickLoad, each defaulting to B49a's behaviour, after B50-alpha's inputs (Claude-Mac goatai#2587 6433854745 ruling 6).
# B51 (B50-beta-1, section 8) appends its own at the very end: the random-direction benchmark (beta-1a), the single's
# break-even and trailing (beta-1b) and its partial close (section 8.3). Their defaults (no benchmark, seed 1, no
# break-even, no trailing, no partial) reproduce B50-alpha. On the merged line (B50 + B51 with B49b) the order is B50's,
# then B49b's, then B51's. Each group is a build generation: a schema declares all of it or none.
# B54 (PR A0, docs/b54/BREAKOUT_ENTRIES_SPEC.md sections 6.2 and 7) appends the breakout entries of Engine_Single after B51's,
# in their own group: family A (BRK_*, an N-bar or prior-day breakout) and family B (ORB_*, a session opening range). Their
# defaults (both modes Disabled) reproduce B53; scripts/test_b54_gate0.cjs and test_b54_gate0.py prove it on the pool.
B50_INPUTS = ('Engine_Mode', 'Single_SL_ATR', 'Single_TP_ATR', 'Single_TP_R', 'Single_Exit_Opposite',
              'Single_Time_Stop_Bars', 'Single_Time_Stop_TF', 'Clock_Mode', 'Server_Clock_Model', 'Server_UTC_Offset',
              'NY_Session', 'Rollover_Block_Minutes')
B49B_INPUTS = ('Fix_MoneyVolume', 'Gate_Recheck', 'Fix_ClosePath', 'Max_Spread_Points', 'Min_Margin_Level_PC', 'Fix_Clock',
               'Fix_FeedGuard', 'Diag_TickTiming', 'Fix_TickLoad')
B51_INPUTS = ('Random_Direction', 'Random_Seed', 'Single_Flat_Only', 'Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR',
              'Single_Partial_ATR', 'Single_Partial_Fraction', 'Single_Partial_BE')
B54_INPUTS = ('BRK_Mode', 'BRK_TF_', 'BRK_Bars', 'BRK_Buffer_ATR', 'BRK_Once_Per_Level', 'ORB_Mode', 'ORB_Clock', 'ORB_TF_',
              'ORB_Start_Minute', 'ORB_Range_Minutes', 'ORB_Entry_Minutes', 'ORB_Buffer_ATR', 'ORB_Min_Range_ATR', 'ORB_Max_Range_ATR')
APPENDED_INPUTS = ('Ledger_Mode',) + B50_INPUTS + B49B_INPUTS + B51_INPUTS + B54_INPUTS
APPENDED_GROUPS = (B50_INPUTS, B49B_INPUTS, B51_INPUTS, B54_INPUTS)


def appended_default(definition):
    """The declared default of an appended input as a SET value; an enum label resolves to its declared number and a
    string literal to its text (B50: NY_Session)."""
    expression = definition['default_expression']
    enum = definition.get('enum_choices')
    if enum is not None and expression in enum:
        return str(enum[expression])
    literal = re.fullmatch(r'"([^"\\\r\n\x00]*)"', expression) if definition['type'] == 'string' else None
    return literal[1] if literal else expression


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
    check_pretrade_caps(values, schema)  # PRETRADE_CAP_OUT_OF_RANGE: the B49b (F6) caps only ever tighten B49a
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

    Runs from validate_strategy, so validate-set, prepare-batch (its plan check and the store's queue check),
    seed-validate and seed-prepare (one SeedRunner for the goat_studio and the demo-agent lane: studio_seed._freeze ->
    validate_raw), build-set, the queue and drafts all agree. The EA's seed path skips its own check
    (GOAT V1.49.mq5:3941-3942), so this is the only gate that keeps a seed plan and the prove batch built from it on
    the same rule. An enum's declaration order is the order of its ``enum_choices`` in the schema, so every caller
    must pass the schema in contract order: a key-sorted copy judges another enum (GOAT-EA#317: the store's copy held
    ENUM_MODE_TRADE as 5, 4, 0, 3, 1, 2 and refused EMA_Mode=1||0||1||2||Y, which is native; it now keeps the
    contract's order, studio_command_store.held_contract). It applies to every
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


def only_reaches(encoded, definition, target):
    """True only when target is the one value encoded can run: the current value, with no active ladder or a ladder
    that starts and stops at target. Any other ladder counts as reaching another value."""
    current, ladder = _reachable(encoded, definition)
    return current == target and (ladder is None or ladder[0] == ladder[2] == target)


def check_risk_sizing(values, schema):
    """Unconditional money-safety rule for every strategy the controller validates or stages.

    With Mode_Lots=RiskperSeq the EA solves the first lot from the planned loss path over levels
    1..Max_Seq_Trades-1. With Max_Seq_Trades<=1 that path is empty (planned loss 0), so the solver
    climbs to the broker's maximum volume. Any reachable combination is refused: the current value,
    every value of an active ladder and the first field of a dormant N tuple. A value missing from a
    partial SET is the EA's declared default. Fails closed when a schema with Mode_Lots no longer
    names RiskperSeq or Max_Seq_Trades, so a rename can never switch the rule off silently.

    B50 (single-trade engine): a SET whose only reachable Engine_Mode is Engine_Single never runs that solver.
    GoatSingleOpen sizes RiskperSeq from the single's own stop: Risk / (Size_SL x tick value / tick size), floored to
    the volume step, capped at the volume maximum and refused below the volume minimum; Single_SL_ATR > 0 is an OnInit
    rule, and a single never adds a grid level. So such a SET is not refused here. A schema without an Engine_Single
    choice, a missing Engine_Mode (the declared default, Engine_Grid) and any ladder that can reach another engine keep
    the refusal unchanged."""
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
    def single_only():   # read only once the grid rule would refuse, so every other SET is checked exactly as before
        engine = inputs.get('Engine_Mode')
        engines = (engine or {}).get('enum_choices') or {}
        return ('Engine_Single' in engines
                and only_reaches(value('Engine_Mode', engine), engine, Fraction(engines['Engine_Single'])))
    if (can_reach(value('Mode_Lots', lots), lots, Fraction(choices['RiskperSeq']))
            and lowest_reachable(value('Max_Seq_Trades', trades), trades) <= 1
            and not single_only()):
        raise ValueError(RISK_SIZING_CODE + ': ' + RISK_SIZING_MESSAGE)


PRETRADE_CAP_CODE = 'PRETRADE_CAP_OUT_OF_RANGE'
# B49b (F6, Claude-Mac GOAT-EA#281 6445315361): (lowest, highest) allowed; 0 = off = B49a. B49a's spread cap is the fixed
# MaxSP 9999 points (GOAT_Inputs_Definitions.mqh, not an input), so a larger Max_Spread_Points would loosen it.
PRETRADE_CAPS = {'Max_Spread_Points': (0, 9999), 'Min_Margin_Level_PC': (0, None)}


def check_pretrade_caps(values, schema):
    """Refuse a pre-trade cap outside its range, over every reachable value (the current value, an active ladder's ends,
    a dormant tuple's first field). The EA treats a negative cap as off, but WriteSet records it and the child audit
    reports it as set, so a negative is refused rather than silently meaning off. An omitted cap is its default, 0."""
    problems = []
    for name, (lowest, highest) in PRETRADE_CAPS.items():
        definition = schema['inputs'].get(name)
        if definition is None or name not in values:
            continue
        current, ladder = _reachable(values[name], definition)
        reached = [current] + ([ladder[0], ladder[2]] if ladder else [])
        if any(value < lowest or (highest is not None and value > highest) for value in reached):
            allowed = f'{lowest}..{highest}' if highest is not None else f'{lowest} or more'
            problems.append(f'{name}={values[name]} reaches a value outside {allowed} (0 = off)')
    if problems:
        raise ValueError(PRETRADE_CAP_CODE + ': a pre-trade cap may only tighten the EA\'s own limits: '
                         + ' | '.join(problems))
