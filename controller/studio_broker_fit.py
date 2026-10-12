"""Plug-and-play broker-fit and equity_linear risk scaling (controller side, contract controller/contracts/broker-fit.md).

A house portfolio (goat-house-portfolio-v1) is measured on one reference account (Darwinex demo, USD 100k). broker-fit
answers, read-only, whether each member can run on THIS demo account's broker at THIS equity, and what the deploy would
write: the reference SET with only its money and lot inputs scaled (and point distances converted when the broker's
point differs). Everything below the CLI section is pure: plain data in, plain data out, no MT5, no disk.

EA semantics this module relies on (GOAT V1.49.mq5, read 2026-10-12):
- Risk is MONEY in the account currency in every mode ("Risk/Loss per Sequence in $$$", Inputs:644): the RiskperSeq
  solver target (mq5:617, 1669, 781-827) and the MLPS amount (mq5:1146-1169). It is never a percentage. Its EA
  minimum is 10 whenever it is used (mq5:3253-3260): RiskperSeq, Sequence_MLPS_Hard_Close, Smart Peak.
- Lots_Max and Lots_Max_Cum are MULTIPLIERS of the start lot, not lots ("multiplies Starting Lots", Inputs:647-648;
  tradeCap = Lots_Max*StartLots mq5:1372, 1559, 1732; StartLots*Lots_Max_Cum mq5:1018, 1366, 1553). Scaling them
  with Risk would scale the caps twice, so they are never scaled.
- The start lot: FixedLots = Lots_Input; ScaledLots = Lots_Input * equity_now / equity_at_init (mq5:3252, 1667: relative
  to the chart's own start, so it does NOT follow account size); RiskperSeq = solved from Risk on the broker's own tick
  value, never below VOLUME_MIN (mq5:784-789, 823-824). So Lots_Input scales in FixedLots/ScaledLots, Risk scales in
  every mode, and RiskperSeq needs no lot edit at all.
- Distances (Grid_Size, Grid_Min, Grid_Max, Lock_Profit_Size, SL_Pips, TSL_Size) are value*10*Point() when positive
  and ATR multiples when negative (GetSize, mq5:6709-6794; mq5:2986-3000). TP_Pips multiplies LP (mq5:2989).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import math
import re
import statistics

from studio_refusal import Refusal

SCHEMA = 'goat-broker-fit-v1'
DEPLOY_SCHEMA = 'goat-broker-fit-deploy-v1'
MANIFEST_SCHEMA = 'goat-house-portfolio-v1'

SYMBOL_UNAVAILABLE = 'SYMBOL_UNAVAILABLE'
SYMBOL_AMBIGUOUS = 'SYMBOL_AMBIGUOUS'
SPREAD_TOO_WIDE = 'SPREAD_TOO_WIDE'
SPREAD_SAMPLE_UNAVAILABLE = 'SPREAD_SAMPLE_UNAVAILABLE'
BELOW_MIN_LOT = 'BELOW_MIN_LOT'
CONTRACT_MISMATCH = 'CONTRACT_MISMATCH'
POINT_SIZE_MISMATCH = 'POINT_SIZE_MISMATCH'
SERVER_OFFSET_MISMATCH = 'SERVER_OFFSET_MISMATCH'
MARGIN_INSUFFICIENT = 'MARGIN_INSUFFICIENT'
ACCOUNT_CURRENCY_UNSUPPORTED = 'ACCOUNT_CURRENCY_UNSUPPORTED'
NOT_DEMO_ACCOUNT = 'NOT_DEMO_ACCOUNT'
PORTFOLIO_INVALID = 'PORTFOLIO_INVALID'
PORTFOLIO_NEEDS_LARGER_ACCOUNT = 'PORTFOLIO_NEEDS_LARGER_ACCOUNT'
PORTFOLIO_BROKER_UNFIT = 'PORTFOLIO_BROKER_UNFIT'
RISK_SCALING_UNSUPPORTED = 'RISK_SCALING_UNSUPPORTED'

MESSAGES = {
    SYMBOL_UNAVAILABLE: "This broker has no tradable {symbol}.",
    SYMBOL_AMBIGUOUS: "This broker has more than one {symbol} ({candidates}), so GOAT will not guess which one to use.",
    SPREAD_TOO_WIDE: "This broker's {symbol} spread is too wide for this set.",
    SPREAD_SAMPLE_UNAVAILABLE: "GOAT could not watch {symbol}'s spread; add it to Market Watch in MT5, then check again.",
    BELOW_MIN_LOT: "This set needs a larger account.",
    CONTRACT_MISMATCH: "This broker's {symbol} contract differs from the one this set was tested on.",
    POINT_SIZE_MISMATCH: "This broker prices {symbol} in a different point size, and GOAT cannot convert this set exactly.",
    SERVER_OFFSET_MISMATCH: "This broker's server clock differs from the one this set was tested on, and this set depends on it.",
    MARGIN_INSUFFICIENT: "This set could need more margin than this account has.",
    ACCOUNT_CURRENCY_UNSUPPORTED: "GOAT cannot convert this account's currency for this portfolio.",
}
MISSING_REFERENCE_MESSAGE = "This set's reference broker details are missing, so GOAT cannot check it on this account."
FIXED_MONEY_MESSAGE = "This set uses a fixed money limit ({name}) that GOAT does not scale."
NOT_STATED_MESSAGE = "This set does not state {name}, so GOAT cannot scale it."

TIMEFRAMES = ('M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1')
FAST_TIMEFRAMES = ('M1', 'M5')
SPREAD_LIMIT_FAST = Decimal('1.25')   # M1 and M5
SPREAD_LIMIT = Decimal('1.5')         # M15 and above
OFFSET_NEUTRAL_TIMEFRAMES = ('M1', 'M5', 'M15', 'M30', 'H1')
TRADABLE_SHARE = Decimal('0.9')
EA_MIN_RISK = Decimal('10')
CENT = Decimal('0.01')
# Value per price unit per contract unit, broker over reference (both in the reference currency). Outside this band the
# instrument is quoted differently (cents, x10 index points); inside it, only FX drift of a cross's tick value.
CONTRACT_VALUE_BAND = (Decimal('0.8'), Decimal('1.25'))

SPREAD_WINDOW_DEFAULT = 300
SPREAD_WINDOW_LIMITS = (300, 1800)
SAMPLE_SECONDS = 5
MIN_SAMPLES = 20
SPAN_SLACK_SECONDS = 10
FRESH_QUOTE_SECONDS = 120

TRADE_MODE_FULL = 4                    # SYMBOL_TRADE_MODE_FULL
MODE_LOTS = dict(FixedLots=0, ScaledLots=1, RiskperSeq=2)
LOTS_PROG_PEAK_SMART = 6
BIAS_EXIT_SMART_RESCUE = 1
POINT_INPUTS = ('Grid_Size', 'Grid_Min', 'Grid_Max', 'Lock_Profit_Size', 'SL_Pips', 'TSL_Size')
FIXED_MONEY_INPUTS = ('MaxLossLocal', 'MaxLossGlobal', 'MaxDailyLossLocal', 'MaxDailyProfitLocal', 'MinLevelEquity', 'MaxLevelEquity')
TF_INPUTS = ('ATR_TF_', 'RSI_TF_', 'EMA_TF_', 'ADX_TF_', 'BB_TF_', 'MACD_TF_', 'RSI2_TF_')
TF_H4 = 240
EDITABLE_INPUTS = frozenset(('Risk', 'Lots_Input') + POINT_INPUTS)
# The broker server clock the house evidence was measured on. 'ny-close': 00:00 server = 17:00 New York, i.e.
# UTC+2, and UTC+3 while New York observes daylight saving time (Darwinex).
REFERENCE_SERVER_TIME = {'Darwinex': 'ny-close'}
NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)')
SHA256 = re.compile(r'[0-9a-f]{64}')
MEMBER_ID = re.compile(r'[A-Za-z0-9._-]{1,64}')
CURRENCY = re.compile(r'[A-Z]{3}')
SUFFIX = re.compile(r'(?:[._#-][A-Za-z0-9]{0,8}|[a-z]{1,4})')
PREFIX = re.compile(r'(?:[#._]|[a-z]{1,4}[._]?)')
REFERENCE_REQUIRED = ('digits', 'point', 'tickSize', 'tickValue', 'contractSize', 'volumeMin', 'volumeStep', 'typicalSpreadPts', 'currency')


def dec(value):
    """A finite Decimal from an SDK float, an int or a SET string; None for anything else."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(value) if isinstance(value, (int, str)) else Decimal(repr(float(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def num(value):
    """JSON number for a Decimal (None stays None)."""
    return None if value is None else float(value)


def message(code, **fields):
    return MESSAGES[code].format(**fields)


# ------------------------------------------------------------------ SET bytes: read, rewrite, encode

def set_encoding(raw):
    """(text, encoding, bom) of a SET, refusing anything that does not round-trip byte for byte."""
    if raw.startswith(b'\xff\xfe'):
        if len(raw) % 2:
            raise ValueError('Odd UTF-16 SET file')
        text, encoding, bom = raw[2:].decode('utf-16-le'), 'utf-16-le', b'\xff\xfe'
    elif raw.startswith(b'\xfe\xff'):
        raise ValueError('UTF-16BE SET files are not supported')
    elif raw.startswith(b'\xef\xbb\xbf'):
        text, encoding, bom = raw[3:].decode('utf-8'), 'utf-8', b'\xef\xbb\xbf'
    else:
        text, encoding, bom = raw.decode('utf-8'), 'utf-8', b''
    if bom + text.encode(encoding) != raw:
        raise ValueError('The SET does not round-trip exactly')
    return text, encoding, bom


def _lines(text):
    """Lines with their own line ends, so joining them gives the text back exactly."""
    return re.findall(r'[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$', text)


def set_values(raw, schema):
    """{input: value} as the dashboard reads it (trimmed line, split on the first '='), for schema inputs only."""
    text, _, _ = set_encoding(raw)
    values = {}
    for line in re.split(r'\r\n|\n|\r', text):
        trimmed = line.strip()
        position = trimmed.find('=')
        if position <= 0:
            continue
        key = trimmed[:position].strip()
        if key not in schema['inputs']:
            continue
        if key in values:
            raise ValueError(key + ' appears more than once in the SET')
        values[key] = trimmed[position + 1:].strip()
    return values


def first_field(value):
    """The value MT5 runs with: the first field of a `value||start||step||stop||Y/N` tuple."""
    return value.split('||', 1)[0].strip()


def format_like(number, like):
    """A scaled value written the way the reference wrote its number: plain decimal, with '.0' kept when it had a point."""
    text = format(number.normalize(), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if text in ('-0', ''):
        text = '0'
    if '.' in like and '.' not in text:
        text += '.0'
    return text


def rewrite_set(raw, edits):
    """The reference SET with only the first field of each edited input replaced; every other byte, the encoding,
    the BOM and every line end kept. An edited input must appear exactly once with an exact key."""
    for name, value in edits.items():
        if name not in EDITABLE_INPUTS or not isinstance(value, str) or not NUMBER.fullmatch(value):
            raise ValueError('Unsupported broker-fit edit: ' + repr(name)[:60])
    if not edits:
        return raw
    text, encoding, bom = set_encoding(raw)
    lines, found = _lines(text), {}
    for index, line in enumerate(lines):
        body = line.rstrip('\r\n')
        position = body.find('=')
        if position <= 0:
            continue
        key = body[:position]
        if key.strip() in edits and key != key.strip():
            raise ValueError('The SET line for ' + key.strip() + ' has extra whitespace; it was not edited')
        if key not in edits:
            continue
        if key in found:
            raise ValueError(key + ' appears more than once in the SET; it was not edited')
        found[key] = index
        value = body[position + 1:]
        head, sep, tail = value.partition('||')
        match = re.fullmatch(r'(\s*)(.*?)(\s*)', head)
        lines[index] = body[:position + 1] + match.group(1) + edits[key] + match.group(3) + sep + tail + line[len(body):]
    missing = sorted(set(edits) - set(found))
    if missing:
        raise ValueError('The SET does not state ' + ', '.join(missing) + '; it was not edited')
    rewritten = bom + ''.join(lines).encode(encoding)
    set_encoding(rewritten)
    return rewritten


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------ time: New York, rollover, weekend, server offset

def _nth_sunday(year, month, n):
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    return first + timedelta(days=(6 - first.weekday()) % 7, weeks=n - 1)


def new_york_offset_hours(utc):
    """-4 while New York observes daylight saving time (2nd Sunday of March 02:00 to 1st Sunday of November 02:00), else -5."""
    start = _nth_sunday(utc.year, 3, 2) + timedelta(hours=7)
    end = _nth_sunday(utc.year, 11, 1) + timedelta(hours=6)
    return -4 if start <= utc < end else -5


def quiet_exclusion(utc_seconds):
    """'rollover', 'weekend' or None for one UTC instant (contract: spread sampling windows).

    rollover: 16:30-17:30 New York every day, the hour around the 17:00 New York FX rollover.
    weekend:  Friday 16:00 New York to Sunday 18:00 New York (an hour either side of the weekly close and open)."""
    utc = datetime.fromtimestamp(utc_seconds, timezone.utc)
    ny = utc + timedelta(hours=new_york_offset_hours(utc))
    minutes, day = ny.hour * 60 + ny.minute, ny.weekday()
    if day == 5 or (day == 4 and minutes >= 16 * 60) or (day == 6 and minutes < 18 * 60):
        return 'weekend'
    if 16 * 60 + 30 <= minutes < 17 * 60 + 30:
        return 'rollover'
    return None


def next_quiet_window(utc_seconds, window_seconds):
    """The first UTC instant (minute-aligned) from which a whole sampling window avoids rollover and weekend."""
    start = int(utc_seconds // 60 * 60)
    for step in range(0, 4 * 24 * 60):
        begin = start + step * 60
        if begin < utc_seconds:
            continue
        if all(quiet_exclusion(begin + offset) is None for offset in range(0, window_seconds + 1, 60)):
            return begin
    return None


def reference_server_offset_minutes(server, utc_seconds):
    """UTC offset (minutes) of the reference broker's server clock at an instant; None when GOAT has no model of it."""
    model = next((value for prefix, value in REFERENCE_SERVER_TIME.items() if isinstance(server, str) and server.startswith(prefix)), None)
    if model != 'ny-close':
        return None
    utc = datetime.fromtimestamp(utc_seconds, timezone.utc)
    return (new_york_offset_hours(utc) + 7) * 60


def measured_server_offset_minutes(samples):
    """The broker server's UTC offset from its freshest quote: quote time (server clock) minus the sample's UTC time,
    rounded to 15 minutes, trusted only when the quote is at most FRESH_QUOTE_SECONDS old. None otherwise."""
    deltas = [s['quoteTime'] - s['utc'] for s in samples if isinstance(s.get('quoteTime'), (int, float)) and s['quoteTime'] > 0]
    if not deltas:
        return None
    best = max(deltas)
    offset = round(best / 900) * 900
    return int(offset // 60) if abs(best - offset) <= FRESH_QUOTE_SECONDS else None


def median_spread(samples, *, window_seconds):
    """(median spread in broker points, None) or (None, reason). Samples inside rollover or weekend are dropped; the rest
    must span the window, number at least MIN_SAMPLES and show the quote moving (a symbol outside Market Watch does not)."""
    valid = [s for s in samples if quiet_exclusion(s['utc']) is None and isinstance(s.get('spread'), int) and s['spread'] >= 0]
    if len(valid) < MIN_SAMPLES:
        return None, 'fewer than %d spread samples outside rollover and the weekend' % MIN_SAMPLES
    span = max(s['utc'] for s in valid) - min(s['utc'] for s in valid)
    if span < window_seconds - SPAN_SLACK_SECONDS:
        return None, 'the samples span %d s, less than the %d s window' % (span, window_seconds)
    if len({s.get('quoteTime') for s in valid}) < 2:
        return None, 'the quote did not change while GOAT watched it'
    return dec(statistics.median(s['spread'] for s in valid)), None


# ------------------------------------------------------------------ symbols

def _tradable(facts):
    return facts.get('trade_mode') == TRADE_MODE_FULL


def _same_instrument(canonical, facts):
    """For a six-letter pair, the broker's base and profit currencies (when reported) must be its two halves."""
    if not re.fullmatch(r'[A-Z]{6}', canonical):
        return True
    base, profit = facts.get('currency_base'), facts.get('currency_profit')
    if not base or not profit:
        return True
    return base == canonical[:3] and profit == canonical[3:]


def is_variant(canonical, name):
    """name is canonical plus one broker suffix (EURUSD.raw, EURUSDm, EURUSD#) or one broker prefix (#EURUSD, m.EURUSD)."""
    if name == canonical:
        return False
    if name.startswith(canonical) and SUFFIX.fullmatch(name[len(canonical):]):
        return True
    return name.endswith(canonical) and PREFIX.fullmatch(name[:-len(canonical)]) is not None


def map_symbol(canonical, symbols):
    """(broker symbol, None) or (None, (code, candidates)). Exact name first; else exactly one tradable variant."""
    by_name = {facts['name']: facts for facts in symbols}
    exact = by_name.get(canonical)
    if exact is not None and _tradable(exact) and _same_instrument(canonical, exact):
        return canonical, None
    variants = sorted(facts['name'] for facts in symbols
                      if is_variant(canonical, facts['name']) and _tradable(facts) and _same_instrument(canonical, facts))
    if len(variants) == 1:
        return variants[0], None
    if variants:
        return None, (SYMBOL_AMBIGUOUS, variants)
    return None, (SYMBOL_UNAVAILABLE, [])


def conversion(account_currency, reference_currency, symbols):
    """(rate, symbol, side): the value of 1 account-currency unit in the reference currency, from a quoted pair on the
    terminal, taking the side that values the account LOWER (bid when the account currency is the base, 1/ask when it
    is the quote). (1, None, None) for the same currency; None when no pair is quoted."""
    if account_currency == reference_currency:
        return Decimal(1), None, None
    candidates = []
    for facts in symbols:
        base, profit = facts.get('currency_base'), facts.get('currency_profit')
        bid, ask = dec(facts.get('bid')), dec(facts.get('ask'))
        if not bid or not ask or bid <= 0 or ask <= 0:
            continue
        if base == account_currency and profit == reference_currency:
            candidates.append((facts['name'] != account_currency + reference_currency, facts['name'], bid, 'bid'))
        elif base == reference_currency and profit == account_currency:
            candidates.append((facts['name'] != reference_currency + account_currency, facts['name'], Decimal(1) / ask, 'ask'))
    if not candidates:
        return None
    _, name, rate, side = sorted(candidates)[0]
    return rate, name, side


# ------------------------------------------------------------------ input semantics

def _value(values, defaults, name):
    return values[name] if name in values else defaults.get(name)


def _number(values, defaults, name):
    text = _value(values, defaults, name)
    return dec(first_field(text)) if isinstance(text, str) and NUMBER.fullmatch(first_field(text)) else None


def _flag(values, defaults, name):
    text = _value(values, defaults, name)
    return isinstance(text, str) and first_field(text) in ('true', '1')


def schema_defaults(schema):
    from studio_template_tools import schema_default
    defaults = {}
    for name, definition in schema['inputs'].items():
        try:
            defaults[name] = schema_default(name, definition, schema.get('defines'))
        except (ValueError, KeyError, TypeError):
            continue
    return defaults


def _session_minutes(text):
    match = re.fullmatch(r'(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})', text or '')
    if not match:
        return None
    h1, m1, h2, m2 = (int(part) for part in match.groups())
    return h1 * 60 + m1, h2 * 60 + m2


def offset_neutral(values, defaults, timeframe):
    """(True, []) when the member's trading cannot depend on the broker's UTC offset, else (False, reasons).

    Neutral means: a chart of M1..H1 (H4/D1 bars start at the server's midnight); no indicator on H4 (any *_TF_ = TF_H4);
    trading 24 hours on every weekday (Active_Time_Weekday = SESS_ALL, Active_Time_Friday = SESSION_ALL or
    SESSION_FRI, and the sessions spanning 00:00-24:00, the EA's own span rule); no end-of-day or Friday action; new
    sequences allowed on Friday; news off or display-only (event times); no daily loss/profit limit (server day)."""
    reasons = []
    if timeframe not in OFFSET_NEUTRAL_TIMEFRAMES:
        reasons.append('timeframe ' + str(timeframe))
    for name in TF_INPUTS:
        if _number(values, defaults, name) == TF_H4:
            reasons.append(name + '=H4')
    weekday, friday = _number(values, defaults, 'Active_Time_Weekday'), _number(values, defaults, 'Active_Time_Friday')
    sessions = [_session_minutes(first_field(_value(values, defaults, name) or ''))
                for name in ('Active_Time_ASIA', 'Active_Time_EU', 'Active_Time_US')]
    full_day = all(sessions) and min(s[0] for s in sessions) == 0 and max(s[1] for s in sessions) >= 24 * 60
    if weekday != 6 or friday not in (6, 7) or not full_day:
        reasons.append('session hours')
    if _number(values, defaults, 'Action_Dayend') != 0 or _number(values, defaults, 'Action_Friday') != 0:
        reasons.append('end-of-day or Friday action')
    if not _flag(values, defaults, 'Trade_Friday'):
        reasons.append('Trade_Friday=false')
    if _number(values, defaults, 'Mode_News') not in (0, 1):
        reasons.append('news filter')
    for name in ('MaxDailyLossLocal', 'MaxDailyProfitLocal'):
        if (_number(values, defaults, name) or 0) != 0:
            reasons.append(name)
    return not reasons, reasons


def _ea_clamps(values, defaults):
    """The EA's post-init clamp outcome of each distance (mq5:3318-3323), compared before and after a point conversion."""
    grid_min, grid_max = _number(values, defaults, 'Grid_Min'), _number(values, defaults, 'Grid_Max')
    lock, tp, tsl = _number(values, defaults, 'Lock_Profit_Size'), _number(values, defaults, 'TP_Pips'), _number(values, defaults, 'TSL_Size')
    def inside(value, limit):
        return value is not None and -limit < value < limit
    return (inside(grid_min, Decimal('0.5')), inside(grid_max, Decimal(1)), inside(lock, Decimal(1)),
            inside(None if tp is None or lock is None else tp * lock, Decimal(1)), inside(tsl, Decimal('0.5')))


def point_edits(values, defaults, ratio):
    """{input: text} converting every positive point distance by ratio (reference point / broker point), or raise
    ValueError when it cannot be exact (ratio not a power of ten, or an EA clamp would change)."""
    if ratio == 1:
        return {}
    exponent = ratio.log10()
    if exponent != exponent.to_integral_value():
        raise ValueError('point ratio %s is not a power of ten' % ratio)
    edits, converted = {}, dict(values)
    for name in POINT_INPUTS:
        number = _number(values, defaults, name)
        if number is None or number <= 0:
            continue
        if name not in values:
            raise ValueError(name + ' is not stated in the SET')
        new = number * ratio
        edits[name] = format_like(new, first_field(values[name]))
        converted[name] = edits[name]
    if _ea_clamps(values, defaults) != _ea_clamps(converted, defaults):
        raise ValueError('an EA minimum-size rule would change after converting the distances')
    return edits


def floor_step(value, step):
    """value rounded DOWN to a whole number of volume steps (never up)."""
    if step <= 0:
        raise ValueError('volume step must be positive')
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def uses_risk(values, defaults):
    """The EA requires Risk >= 10 when it sizes by Risk or closes by it (mq5:3253-3260, 3271)."""
    return (_number(values, defaults, 'Mode_Lots') == MODE_LOTS['RiskperSeq'] or _flag(values, defaults, 'Sequence_MLPS_Hard_Close')
            or _number(values, defaults, 'Mode_Lots_Prog') == LOTS_PROG_PEAK_SMART
            or _number(values, defaults, 'Mode_Bias_Exit') == BIAS_EXIT_SMART_RESCUE)


def equity_rules(values, defaults, *, lot_factor, money_factor, broker, reference):
    """The equity-dependent rules for one member at one equity. Returns dict(code, message, edits, scaled, start_lots).

    lot_factor   = scale x (reference contract size / broker contract size): what lots multiply by.
    money_factor = account equity / reference equity (= scale / rate): what money inputs (account currency) multiply by.
    Never rounds up: lots round DOWN to the broker volume step, Risk DOWN to the cent, and anything that would then sit
    below VOLUME_MIN (or Risk below the EA's 10) is BELOW_MIN_LOT."""
    edits, mode = {}, _number(values, defaults, 'Mode_Lots')
    vmin, vstep, vmax = broker['volume_min'], broker['volume_step'], broker['volume_max']
    risk = _number(values, defaults, 'Risk')
    new_risk = risk
    if risk is not None and money_factor != 1:
        if 'Risk' not in values:
            return dict(code=CONTRACT_MISMATCH, message=NOT_STATED_MESSAGE.format(name='Risk'))
        new_risk = (risk * money_factor).quantize(CENT, rounding=ROUND_FLOOR)
        if new_risk != risk:
            edits['Risk'] = format_like(new_risk, first_field(values['Risk']))
    if uses_risk(values, defaults) and (new_risk is None or new_risk < EA_MIN_RISK):
        return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
    lots_input = _number(values, defaults, 'Lots_Input')
    lots_max, lots_max_cum = _number(values, defaults, 'Lots_Max'), _number(values, defaults, 'Lots_Max_Cum')
    start = None
    if mode in (MODE_LOTS['FixedLots'], MODE_LOTS['ScaledLots']):
        if lots_input is None:
            return dict(code=CONTRACT_MISMATCH, message=NOT_STATED_MESSAGE.format(name='Lots_Input'))
        start = lots_input
        if lot_factor != 1:
            if 'Lots_Input' not in values:
                return dict(code=CONTRACT_MISMATCH, message=NOT_STATED_MESSAGE.format(name='Lots_Input'))
            start = floor_step(min(lots_input * lot_factor, vmax) if vmax else lots_input * lot_factor, vstep)
            if start != lots_input:
                edits['Lots_Input'] = format_like(start, first_field(values['Lots_Input']))
        if start < vmin:
            return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
        bound = start
    elif mode == MODE_LOTS['RiskperSeq']:
        # The EA solves the start lot from Risk on this broker's tick value (never below VOLUME_MIN). With the
        # reference start lot known it scales; otherwise the reference VOLUME_MIN is its proven lower bound.
        known = reference.get('startLots')
        if known is not None:
            start = floor_step(known * lot_factor, vstep)
            bound = start
        else:
            bound = reference['volumeMin'] * lot_factor
        if bound < vmin:
            return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
    else:
        return dict(code=CONTRACT_MISMATCH, message='This set uses a lot sizing mode GOAT does not scale.')
    if lots_max is not None and lots_max > Decimal('0.01') and lots_max * bound < vmin:
        return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
    written_lots = dec(edits['Lots_Input']) if 'Lots_Input' in edits else lots_input
    # Lots_Max and Lots_Max_Cum are reported as written: multipliers of the start lot, never scaled.
    scaled = dict(Risk=new_risk, Lots_Max=lots_max, Lots_Max_Cum=lots_max_cum, Lots_Input=written_lots, startLots=start)
    return dict(code=None, message=None, edits=edits, scaled=scaled, start_lots=start)


def peak_lots(values, defaults, start):
    """Worst-case concurrent lots of one member: the EA's caps on the start lot, both directions when a buy and a sell
    sequence may coexist. None when the start lot or every cap is unknown."""
    if start is None:
        return None
    cum, per_trade = _number(values, defaults, 'Lots_Max_Cum'), _number(values, defaults, 'Lots_Max')
    trades = _number(values, defaults, 'Max_Seq_Trades')
    if cum is not None and cum > 0:
        lots = start * cum
    elif per_trade is not None and per_trade > Decimal('0.01') and trades:
        lots = start * per_trade * trades
    else:
        return None
    both = _number(values, defaults, 'Mode_Trade') == 0 and _flag(values, defaults, 'Allow_Opposite_Seq')
    return lots * (2 if both else 1)


# ------------------------------------------------------------------ manifest

def _refuse(text, field=None):
    raise Refusal('This house portfolio file is not one GOAT can check (' + text + ').', PORTFOLIO_INVALID, field=field)


def validate_manifest(manifest):
    if type(manifest) is not dict or manifest.get('schema') != MANIFEST_SCHEMA:
        _refuse('schema', 'schema')
    if manifest.get('riskScaling', 'equity_linear') != 'equity_linear':
        raise Refusal('This portfolio scales risk in a way GOAT does not support (' + str(manifest.get('riskScaling'))[:40] + ').',
                      RISK_SCALING_UNSUPPORTED)
    account = manifest.get('referenceAccount')
    if (type(account) is not dict or not isinstance(account.get('server'), str) or not CURRENCY.fullmatch(str(account.get('currency')))
            or dec(account.get('startingBalance')) is None or dec(account['startingBalance']) <= 0):
        _refuse('referenceAccount', 'referenceAccount')
    floor = manifest.get('minEquity')
    if floor is not None and (dec(floor) is None or dec(floor) <= 0):
        _refuse('minEquity', 'minEquity')
    members = manifest.get('members')
    if type(members) is not list or not 1 <= len(members) <= 100:
        _refuse('members', 'members')
    seen = set()
    for index, member in enumerate(members):
        at = 'members[%d]' % index
        if (type(member) is not dict or not isinstance(member.get('memberId'), str) or not MEMBER_ID.fullmatch(member['memberId'])
                or member['memberId'] in seen or not isinstance(member.get('canonicalSymbol'), str)
                or member.get('timeframe') not in TIMEFRAMES or not isinstance(member.get('setName'), str)
                or ',' not in member['setName'] or not SHA256.fullmatch(str(member.get('setSha256')))
                or type(member.get('setBytes')) is not int or type(member.get('reference')) is not dict):
            _refuse(at, at)
        seen.add(member['memberId'])


def deploy_file_name(set_name, broker_symbol):
    """The member's SET name with the broker's symbol (the dashboard reads the symbol between the last space before the
    first comma and that comma, Dashboard.mqh ExtractEAnameAndSymbol)."""
    comma = set_name.find(',')
    space = set_name.rfind(' ', 0, comma)
    return set_name[:space + 1] + broker_symbol + set_name[comma:]


def reference_facts(reference):
    """The member reference with Decimals; None when a key a rule needs is unknown (null) or invalid."""
    facts = {}
    for key in REFERENCE_REQUIRED:
        value = reference.get(key)
        if key == 'currency':
            if not isinstance(value, str) or not CURRENCY.fullmatch(value):
                return None
            facts[key] = value
            continue
        number = dec(value)
        if number is None or number < 0 or (key != 'typicalSpreadPts' and number <= 0):
            return None
        facts[key] = number
    for key in ('startLots', 'swapLong', 'swapShort', 'volumeMax'):
        facts[key] = dec(reference.get(key))
    if facts['startLots'] is not None and facts['startLots'] <= 0:
        facts['startLots'] = None
    return facts


def broker_facts(facts):
    out = dict(name=facts['name'])
    for key in ('point', 'trade_contract_size', 'trade_tick_size', 'trade_tick_value', 'volume_min', 'volume_step', 'volume_max',
                'swap_long', 'swap_short', 'bid', 'ask'):
        out[key] = dec(facts.get(key))
    out['digits'] = facts.get('digits')
    return out


# ------------------------------------------------------------------ the result

def build_result(manifest, sets, *, account, symbols, samples, margins, schema, utc_now,
                 equity=None, window_seconds=SPREAD_WINDOW_DEFAULT):
    """BrokerFitResult (contract goat-broker-fit-v1) from plain data.

    manifest  goat-house-portfolio-v1 dict; sets {setSha256: reference SET bytes}
    account   dict(login, server, currency, equity, leverage, demo)
    symbols   [dict(name, trade_mode, digits, point, trade_contract_size, trade_tick_size, trade_tick_value, volume_min,
              volume_step, volume_max, currency_base, currency_profit, swap_long, swap_short, bid, ask)]
    samples   {broker symbol: [dict(utc, spread, quoteTime)]} collected over the window
    margins   {broker symbol: margin per 1.0 lot in the account currency (worse of buy and sell)}
    equity    planning override in the account currency (--equity)"""
    if account.get('demo') is not True:
        raise Refusal('broker-fit runs on demo accounts only; this account is not a demo account.', NOT_DEMO_ACCOUNT)
    validate_manifest(manifest)
    defaults = schema_defaults(schema)
    ref_account = manifest['referenceAccount']
    ref_equity, ref_currency = dec(ref_account['startingBalance']), ref_account['currency']
    account_equity = dec(equity if equity is not None else account.get('equity'))
    if account_equity is None or account_equity <= 0:
        raise Refusal('GOAT could not read a positive equity for this account.', PORTFOLIO_INVALID, field='equity')
    converted = conversion(account.get('currency'), ref_currency, symbols)
    rate = converted[0] if converted else None
    scale = account_equity * rate / ref_equity if rate else None
    all_samples = [sample for series in samples.values() for sample in series]
    offset_now = (account.get('server') == ref_account['server'], measured_server_offset_minutes(all_samples),
                  reference_server_offset_minutes(ref_account['server'], utc_now))
    by_name = {facts['name']: facts for facts in symbols}
    members, internals = [], []
    for member in manifest['members']:
        row, inner = _member(member, sets, defaults, by_name, symbols, samples, margins, schema, scale=scale, rate=rate,
                             account_equity=account_equity, offsets=offset_now, window_seconds=window_seconds,
                             ref_currency=ref_currency, reference_equity=ref_equity)
        members.append(row); internals.append(inner)
    return _portfolio(manifest, account, account_equity, ref_equity, ref_currency, rate, converted, scale, members, internals,
                      offset_now)


def _excluded(row, code, text, inner=None):
    row.update(status='excluded', code=code, message=text, scaled=None, setSha256Deployed=None, edits=None)
    return row, inner or dict(weight=Decimal(1), min_equity=None, margin=None)


def _member(member, sets, defaults, by_name, symbols, samples, margins, schema, *, scale, rate, account_equity, offsets,
            window_seconds, ref_currency, reference_equity):
    raw = sets[member['setSha256']]
    values = set_values(raw, schema)
    mode = _number(values, defaults, 'Mode_Lots')
    risk = _number(values, defaults, 'Risk')
    weight = risk if mode == MODE_LOTS['RiskperSeq'] and risk and risk > 0 else None
    row = dict(memberId=member['memberId'], canonicalSymbol=member['canonicalSymbol'], brokerSymbol=None,
               period=member['timeframe'], status='fit', code=None, message=None, spreadRatio=None, scaled=None,
               setSha256Reference=sha256(raw), setSha256Deployed=None, deployFileName=None, edits=None,
               spread=None, pointConversion=None, serverOffset=None, costs=None, margin=None)
    inner = dict(weight=weight, min_equity=None, margin=None)
    if rate is None:
        return _excluded(row, ACCOUNT_CURRENCY_UNSUPPORTED, message(ACCOUNT_CURRENCY_UNSUPPORTED), inner)
    symbol, problem = map_symbol(member['canonicalSymbol'], symbols)
    if problem:
        code, candidates = problem
        return _excluded(row, code, message(code, symbol=member['canonicalSymbol'], candidates=', '.join(candidates)), inner)
    row['brokerSymbol'], row['deployFileName'] = symbol, deploy_file_name(member['setName'], symbol)
    reference = reference_facts(member['reference'])
    broker = broker_facts(by_name[symbol])
    needed = ('point', 'trade_contract_size', 'trade_tick_size', 'trade_tick_value', 'volume_min', 'volume_step')
    # A house manifest measures every member on one account: a reference tick value quoted in another currency is refused.
    if reference is None or reference['currency'] != ref_currency or any(broker[key] is None or broker[key] <= 0 for key in needed):
        return _excluded(row, CONTRACT_MISMATCH, MISSING_REFERENCE_MESSAGE, inner)
    # Contract: value of one price unit per contract unit, in the reference currency, must match (else the instrument is
    # quoted differently); a different contract SIZE is corrected exactly through the lot factor.
    broker_value = broker['trade_tick_value'] / broker['trade_tick_size'] / broker['trade_contract_size'] * rate
    reference_value = reference['tickValue'] / reference['tickSize'] / reference['contractSize']
    ratio = broker_value / reference_value
    if not CONTRACT_VALUE_BAND[0] <= ratio <= CONTRACT_VALUE_BAND[1]:
        return _excluded(row, CONTRACT_MISMATCH, message(CONTRACT_MISMATCH, symbol=symbol), inner)
    contract_ratio = reference['contractSize'] / broker['trade_contract_size']
    # Point size: positive distances are value*10*Point(); convert them exactly or refuse.
    point_ratio = reference['point'] / broker['point']
    try:
        converted = point_edits(values, defaults, point_ratio)
    except ValueError as exc:
        return _excluded(row, POINT_SIZE_MISMATCH, message(POINT_SIZE_MISMATCH, symbol=symbol) + ' (' + str(exc) + ')', inner)
    row['pointConversion'] = dict(referencePoint=num(reference['point']), brokerPoint=num(broker['point']),
                                  factor=num(point_ratio), inputs=dict(converted)) if point_ratio != 1 else None
    # Server clock.
    same_server, measured, expected = offsets
    neutral, reasons = offset_neutral(values, defaults, member['timeframe'])
    same_offset = same_server or (measured is not None and expected is not None and measured == expected)
    row['serverOffset'] = dict(sameServer=same_server, brokerMinutes=measured, referenceMinutes=expected,
                               offsetNeutral=neutral, dependsOn=reasons)
    if not same_offset and not (neutral and measured is not None and expected is not None and (measured - expected) % 60 == 0):
        return _excluded(row, SERVER_OFFSET_MISMATCH, message(SERVER_OFFSET_MISMATCH), inner)
    # Spread: the median over the window, in reference points.
    median, reason = median_spread(samples.get(symbol, []), window_seconds=window_seconds)
    if median is None:
        return _excluded(row, SPREAD_SAMPLE_UNAVAILABLE, message(SPREAD_SAMPLE_UNAVAILABLE, symbol=symbol) + ' (' + reason + ')', inner)
    normalised = median * broker['point'] / reference['point']
    limit = SPREAD_LIMIT_FAST if member['timeframe'] in FAST_TIMEFRAMES else SPREAD_LIMIT
    typical = reference['typicalSpreadPts']
    if typical > 0:
        row['spreadRatio'] = num((normalised / typical).quantize(Decimal('0.0001')))
        fits = normalised <= typical * limit
    else:
        fits = normalised == 0
    row['spread'] = dict(medianPoints=num(median), referencePoints=num(normalised), typicalSpreadPts=num(typical), limit=num(limit),
                         samples=len(samples.get(symbol, [])))
    # Costs: shown, never refused. MT5's Python SDK does not expose commission.
    row['costs'] = dict(swapLong=num(broker['swap_long']), swapShort=num(broker['swap_short']),
                        referenceSwapLong=num(reference['swapLong']), referenceSwapShort=num(reference['swapShort']),
                        commission=None, commissionSource='not_exposed_by_mt5_sdk')
    if not fits:
        return _excluded(row, SPREAD_TOO_WIDE, message(SPREAD_TOO_WIDE, symbol=symbol), inner)
    # Fixed money limits are account-level amounts GOAT does not scale.
    for name in FIXED_MONEY_INPUTS:
        if (_number(values, defaults, name) or 0) != 0 and account_equity != reference_equity:
            return _excluded(row, CONTRACT_MISMATCH, FIXED_MONEY_MESSAGE.format(name=name), inner)
    rules = dict(broker=dict(volume_min=broker['volume_min'], volume_step=broker['volume_step'], volume_max=broker['volume_max']),
                 reference=dict(volumeMin=reference['volumeMin'], startLots=reference['startLots']))
    def at(trial_equity):
        # Lots follow the equity in the reference currency (x rate) and the contract size; money inputs are in the
        # account currency, so their factor is equity / reference equity exactly (the rate cancels).
        return equity_rules(values, defaults, lot_factor=trial_equity * rate / reference_equity * contract_ratio,
                            money_factor=trial_equity / reference_equity, **rules)
    fixed_money = any((_number(values, defaults, name) or 0) != 0 for name in FIXED_MONEY_INPUTS)
    inner['min_equity'] = None if fixed_money else min_equity(lambda trial: at(trial)['code'] is None)
    outcome = at(account_equity)
    if outcome['code']:
        return _excluded(row, outcome['code'], outcome['message'], inner)
    edits = dict(outcome['edits']); edits.update(converted)
    deployed = rewrite_set(raw, edits)
    row.update(scaled={key: num(value) for key, value in outcome['scaled'].items()}, edits=edits, setSha256Deployed=sha256(deployed))
    # Margin at the scaled caps and this account's leverage (the SDK's own calculation).
    per_lot = dec(margins.get(symbol))
    lots = peak_lots(values, defaults, outcome['start_lots'])
    required = per_lot * lots if per_lot is not None and lots is not None else None
    row['margin'] = dict(perLot=num(per_lot), peakLots=num(lots), required=num(required),
                         basis='ea_caps' if required is not None else ('start_lots_unknown' if lots is None else 'margin_unavailable'))
    inner['margin'] = required
    if required is not None and required > account_equity:
        return _excluded(row, MARGIN_INSUFFICIENT, message(MARGIN_INSUFFICIENT), inner)
    return row, inner


MAX_EQUITY_CENTS = 10 ** 14


def min_equity(tradable):
    """Smallest equity, on the cent grid of the account currency, where tradable(equity) holds. The rules only ever
    round down as equity falls, so they are monotone and a bisection over whole cents is exact. None when not even at
    MAX_EQUITY_CENTS."""
    low, high = 0, MAX_EQUITY_CENTS
    if not tradable(Decimal(high) * CENT):
        return None
    while high - low > 1:
        middle = (low + high) // 2
        if tradable(Decimal(middle) * CENT):
            high = middle
        else:
            low = middle
    return Decimal(high) * CENT


def _portfolio(manifest, account, account_equity, ref_equity, ref_currency, rate, converted, scale, members, internals, offsets):
    if all(inner['weight'] is not None for inner in internals):
        weights = [inner['weight'] for inner in internals]
        weighting = 'risk'
    else:
        weights = [Decimal(1)] * len(internals)
        weighting = 'equal'
    total = sum(weights)
    fit_weight = sum(weight for weight, row in zip(weights, members) if row['status'] == 'fit')
    share = fit_weight / total if total else Decimal(0)
    min_equity_value, refusal = None, None
    if rate is not None:
        # Equity-dependent exclusions only: a member excluded for any other reason never becomes tradable by equity, and
        # margin grows with equity at the same rate, so MARGIN_INSUFFICIENT does not either.
        thresholds = sorted((inner['min_equity'], weight) for inner, weight, row in zip(internals, weights, members)
                            if inner.get('min_equity') is not None and row['code'] in (None, BELOW_MIN_LOT))
        running, needed = Decimal(0), None
        for threshold, weight in thresholds:
            running += weight
            if total and running / total >= TRADABLE_SHARE:
                needed = threshold
                break
        if needed is not None:
            # The manifest's own minEquity (reference currency) is a floor the publisher set; the stricter one wins.
            floor = dec(manifest.get('minEquity'))
            min_equity_value = max(needed, (floor / rate).quantize(CENT, rounding=ROUND_CEILING)) if floor is not None else needed
    margin_known = [inner['margin'] for inner, row in zip(internals, members) if row['status'] == 'fit']
    margin_total = sum(value for value in margin_known if value is not None)
    margin_verified = all(value is not None for value in margin_known)
    if rate is None:
        refusal = dict(code=ACCOUNT_CURRENCY_UNSUPPORTED, message=message(ACCOUNT_CURRENCY_UNSUPPORTED))
    elif min_equity_value is None:
        refusal = dict(code=PORTFOLIO_BROKER_UNFIT, message="Less than 90% of this portfolio can trade on this account's broker.")
    elif account_equity < min_equity_value:
        refusal = dict(code=PORTFOLIO_NEEDS_LARGER_ACCOUNT, message='This portfolio needs a larger account.')
    elif margin_total > account_equity:
        refusal = dict(code=MARGIN_INSUFFICIENT, message='Together these sets could need more margin than this account has.')
    elif share < TRADABLE_SHARE:
        refusal = dict(code=PORTFOLIO_BROKER_UNFIT, message="Less than 90% of this portfolio can trade on this account's broker.")
    _, measured, expected = offsets
    return dict(
        schema=SCHEMA,
        account=dict(login=str(account.get('login')), server=account.get('server'), currency=account.get('currency'),
                     equity=num(account_equity), leverage=account.get('leverage'), demo=True),
        reference=dict(equity=num(ref_equity), currency=ref_currency, server=manifest['referenceAccount']['server']),
        scale=num(scale), scaleMode='equity_linear',
        conversion=None if converted is None else dict(rate=num(converted[0]), symbol=converted[1], side=converted[2]),
        minEquity=num(min_equity_value), manifestMinEquity=num(dec(manifest.get('minEquity'))),
        offered=refusal is None, refusal=refusal,
        tradableRiskShare=num(share.quantize(Decimal('0.0001'))), riskWeighting=weighting,
        margin=dict(required=num(margin_total), equity=num(account_equity), verified=margin_verified, level='member_and_portfolio'),
        serverOffset=dict(brokerMinutes=measured, referenceMinutes=expected),
        members=members)


# ------------------------------------------------------------------ deploy hook (studio_demo_deploy)

def deploy_entries(block, members):
    """Validate a plan's brokerFit block against its members; returns one entry per member, in order."""
    if (type(block) is not dict or set(block) != {'schema', 'scale', 'members'} or block['schema'] != DEPLOY_SCHEMA
            or isinstance(block['scale'], bool) or not isinstance(block['scale'], (int, float))
            or not math.isfinite(block['scale']) or block['scale'] <= 0):
        raise ValueError('Invalid broker-fit block in the demo deploy plan')
    entries = block['members']
    if type(entries) is not list or len(entries) != len(members):
        raise ValueError('The broker-fit block must name every deployed member, and only them')
    for index, entry in enumerate(entries):
        if (type(entry) is not dict or set(entry) != {'index', 'memberId', 'setSha256Reference', 'setSha256Deployed', 'edits'}
                or entry['index'] != index or not isinstance(entry['memberId'], str) or not MEMBER_ID.fullmatch(entry['memberId'])
                or not SHA256.fullmatch(str(entry['setSha256Reference'])) or not SHA256.fullmatch(str(entry['setSha256Deployed']))
                or type(entry['edits']) is not dict):
            raise ValueError('Invalid broker-fit member %d in the demo deploy plan' % index)
    return entries


def deployed_bytes(reference_raw, entry):
    """The scaled SET the deploy writes: the reference bytes with the reviewed edits, hash-checked on both sides."""
    if sha256(reference_raw) != entry['setSha256Reference']:
        raise ValueError('The member SET is not the broker-fit reference SET')
    raw = rewrite_set(reference_raw, entry['edits'])
    if sha256(raw) != entry['setSha256Deployed']:
        raise ValueError('The scaled SET differs from the reviewed broker-fit result')
    return raw


def deploy_record(block):
    """What the deploy journal keeps per member: {memberId, setSha256Reference, setSha256Deployed, scale}."""
    return dict(schema=block['schema'], scale=block['scale'],
                members=[dict(memberId=e['memberId'], setSha256Reference=e['setSha256Reference'],
                              setSha256Deployed=e['setSha256Deployed'], scale=block['scale']) for e in block['members']])


# ------------------------------------------------------------------ CLI (read-only MT5 SDK readback)

def load_portfolio(path, sets_dir=None):
    """(manifest, {sha: bytes}) from a manifest JSON file. Each SET is found in sets_dir (default: the manifest's folder)
    as the app's house cache names it (<setSha256>) or by its setName, and must hash to setSha256 with setBytes bytes."""
    import json
    from pathlib import Path
    path = Path(path)
    if path.suffix.lower() == '.goatportfolio':
        raise Refusal('broker-fit reads a house portfolio manifest (.json); a saved .goatportfolio package is not supported yet.',
                      PORTFOLIO_INVALID, field='portfolio')
    try:
        raw = path.read_bytes()
        if len(raw) > 4_000_000:
            raise ValueError('larger than 4 MB')
        manifest = json.loads(raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise Refusal('GOAT could not read the portfolio file (' + str(exc)[:120] + ').', PORTFOLIO_INVALID, field='portfolio') from exc
    validate_manifest(manifest)
    folder = Path(sets_dir) if sets_dir else path.parent
    sets, missing = {}, []
    for member in manifest['members']:
        found = None
        for candidate in (folder / member['setSha256'], folder / member['setName']):
            try:
                data = candidate.read_bytes() if candidate.is_file() else None
            except OSError:
                data = None
            if data is not None and len(data) == member['setBytes'] and sha256(data) == member['setSha256']:
                found = data
                break
        if found is None:
            missing.append(member['memberId'])
        else:
            sets[member['setSha256']] = found
    if missing:
        raise Refusal('GOAT could not find the verified SET file of ' + ', '.join(missing[:5]) + '.', PORTFOLIO_INVALID,
                      field='sets', members=missing)
    return manifest, sets


def _symbol_dict(info):
    keys = ('name', 'trade_mode', 'digits', 'point', 'trade_contract_size', 'trade_tick_size', 'trade_tick_value', 'volume_min',
            'volume_step', 'volume_max', 'currency_base', 'currency_profit', 'swap_long', 'swap_short', 'bid', 'ask', 'spread',
            'time', 'visible')
    return {key: getattr(info, key, None) for key in keys}


def read_broker(controller, session, manifest, *, mt5=None, window_seconds=SPREAD_WINDOW_DEFAULT, clock=None, sleep=None):
    """One read-only MT5 SDK session under the terminal lease: account, every symbol, spread samples over the window and
    the SDK's margin per lot. Never trades, never selects a symbol into Market Watch, never opens a chart."""
    import time
    from pathlib import Path
    from studio_terminal_lease import BUSY_READ, terminal_lease
    clock, sleep = clock or time.time, sleep or time.sleep
    now = clock()
    if any(quiet_exclusion(now + offset) for offset in range(0, window_seconds + 1, 60)):
        start = next_quiet_window(now, window_seconds)
        raise Refusal('GOAT measures spreads outside the rollover hour and the weekend; check again from '
                      + (datetime.fromtimestamp(start, timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if start else 'Monday') + '.',
                      SPREAD_SAMPLE_UNAVAILABLE, nextWindowUtc=start)
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise ValueError('The MetaTrader5 adapter is unavailable; nothing was read') from exc
    with terminal_lease(controller.root, purpose='broker-fit', busy_code='BROKER_READ_DEFERRED', busy_message=BUSY_READ,
                        broker_reason='terminal_busy'):
        if not mt5.initialize(controller.install['terminal_executable'], timeout=5000):
            raise ValueError('The selected MT5 terminal could not be read; start it and sign in to the demo account')
        try:
            terminal, info = mt5.terminal_info(), mt5.account_info()
            if terminal is None or info is None:
                raise ValueError('Incomplete native account and terminal readback')
            if (Path(terminal.path) != Path(controller.install['terminal_executable']).parent
                    or Path(terminal.data_path) != Path(controller.install['terminal_data_root'])):
                raise ValueError('The running MT5 is not the selected installation')
            if str(info.login) != session['account']['login'] or info.server != session['account']['server']:
                raise ValueError('MT5 is signed in to a different account than this installation is bound to')
            if info.trade_mode != getattr(mt5, 'ACCOUNT_TRADE_MODE_DEMO', 0):
                raise Refusal('broker-fit runs on demo accounts only; this account is not a demo account.', NOT_DEMO_ACCOUNT)
            if not terminal.connected:
                raise ValueError('MT5 is not connected to the demo server')
            account = dict(login=str(info.login), server=info.server, currency=info.currency, equity=info.equity,
                           leverage=info.leverage, demo=True)
            symbols = [_symbol_dict(item) for item in (mt5.symbols_get() or ())]
            mapped = sorted({symbol for symbol, problem in (map_symbol(m['canonicalSymbol'], symbols) for m in manifest['members'])
                             if symbol})
            samples = {symbol: [] for symbol in mapped}
            deadline = clock() + window_seconds
            while True:
                stamp = clock()
                for symbol in mapped:
                    current = mt5.symbol_info(symbol)
                    if current is not None:
                        samples[symbol].append(dict(utc=stamp, spread=int(current.spread), quoteTime=int(current.time)))
                if stamp >= deadline:
                    break
                sleep(SAMPLE_SECONDS)
            fresh = {item['name']: item for item in (_symbol_dict(mt5.symbol_info(name)) for name in mapped) if item['name']}
            symbols = [fresh.get(item['name'], item) for item in symbols]
            margins = {}
            for symbol in mapped:
                facts = fresh.get(symbol) or {}
                values = [mt5.order_calc_margin(getattr(mt5, kind, default), symbol, 1.0, facts.get(price))
                          for kind, default, price in (('ORDER_TYPE_BUY', 0, 'ask'), ('ORDER_TYPE_SELL', 1, 'bid'))
                          if facts.get(price)]
                values = [value for value in values if isinstance(value, (int, float)) and math.isfinite(value) and value > 0]
                margins[symbol] = max(values) if values else None
        finally:
            mt5.shutdown()
    return account, symbols, samples, margins, clock()


def broker_fit(controller, portfolio, *, equity=None, sets_dir=None, window_seconds=SPREAD_WINDOW_DEFAULT, mt5=None,
               clock=None, sleep=None):
    """`studio broker-fit`: read-only; refuses NOT_DEMO_ACCOUNT on a non-demo account."""
    from studio_onboarding import session_state
    if type(window_seconds) is not int or not SPREAD_WINDOW_LIMITS[0] <= window_seconds <= SPREAD_WINDOW_LIMITS[1]:
        raise ValueError('--spread-window-seconds must be between %d and %d' % SPREAD_WINDOW_LIMITS)
    if equity is not None and (not math.isfinite(equity) or equity <= 0):
        raise ValueError('--equity must be a positive number')
    manifest, sets = load_portfolio(portfolio, sets_dir)
    installed = controller.install.get('ea_version')
    wanted = (manifest.get('ea') or {}).get('eaVersion')
    if wanted and installed and wanted != installed:
        raise Refusal('This portfolio is built for GOAT EA V' + str(wanted) + '; this terminal runs V' + str(installed) + '.',
                      'EA_VERSION_MISMATCH')
    session, _ = session_state(controller)
    account, symbols, samples, margins, utc_now = read_broker(controller, session, manifest, mt5=mt5, window_seconds=window_seconds,
                                                               clock=clock, sleep=sleep)
    return build_result(manifest, sets, account=account, symbols=symbols, samples=samples, margins=margins,
                        schema=controller.schema, utc_now=utc_now, equity=equity, window_seconds=window_seconds)
