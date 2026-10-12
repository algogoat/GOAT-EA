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
  to the chart's own start, so it does NOT follow account size); RiskperSeq = SolveStartLotsByRisk(Risk) (mq5:781-827):
  the volume-step lot whose planned sequence loss is NEAREST the Risk, never below VOLUME_MIN. Every lot the EA trades
  goes through NormalizedLots (mq5:445-459, 1686): the NEAREST volume step (MathRound, half away from zero), 0 below
  VOLUME_MIN, capped at VOLUME_MAX. So Lots_Input scales in FixedLots/ScaledLots and is always written on the broker's
  step grid, Risk scales in every mode, and RiskperSeq needs no lot edit at all (ea_solve_start_lots ports the solver).
- Distances (Grid_Size, Grid_Min, Grid_Max, Lock_Profit_Size, SL_Pips, TSL_Size) are value*10*Point() when positive
  and ATR multiples when negative (GetSize, mq5:6709-6794; mq5:2986-3000). TP_Pips multiplies LP (mq5:2989).
  Grid_Size inside (-0.5, 0.5) stops the EA at init (mq5:3317).
- Fixed money limits (MaxLoss*, MaxDaily*, Min/MaxLevelEquity) are account-currency amounts and equity levels the EA
  compares as written (mq5:5595-5630).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import math
import re
import statistics

from studio_refusal import Refusal

SCHEMA = 'goat-broker-fit-v1'
# v2 (GOAT-EA#228 review 6130418265): the block carries the manifest, the planning equity and the review time, and
# every member names its broker symbol and deploy file; the deploy re-derives everything from them and the live broker.
DEPLOY_SCHEMA = 'goat-broker-fit-deploy-v2'
MANIFEST_SCHEMA = 'goat-house-portfolio-v1'

SYMBOL_UNAVAILABLE = 'SYMBOL_UNAVAILABLE'
SYMBOL_AMBIGUOUS = 'SYMBOL_AMBIGUOUS'
SPREAD_TOO_WIDE = 'SPREAD_TOO_WIDE'
SPREAD_SAMPLE_UNAVAILABLE = 'SPREAD_SAMPLE_UNAVAILABLE'
BELOW_MIN_LOT = 'BELOW_MIN_LOT'
CONTRACT_MISMATCH = 'CONTRACT_MISMATCH'
POINT_SIZE_MISMATCH = 'POINT_SIZE_MISMATCH'
SERVER_OFFSET_MISMATCH = 'SERVER_OFFSET_MISMATCH'
MARGIN_TOO_HIGH = 'MARGIN_TOO_HIGH'
MARGIN_UNKNOWN = 'MARGIN_UNKNOWN'
MONEY_VALUE_UNREADABLE = 'MONEY_VALUE_UNREADABLE'
EA_INIT_REFUSED = 'EA_INIT_REFUSED'
FIT_STALE = 'FIT_STALE'
MT5_NOT_RUNNING = 'MT5_NOT_RUNNING'
MT5_STARTED_BY_CHECK = 'MT5_STARTED_BY_CHECK'
# Not a refusal: the explicit reason a member's unknown margin is accepted on a reference-identical account.
REFERENCE_IDENTICAL_MARGIN = 'REFERENCE_IDENTICAL_MARGIN'
# One-sided (review 6130418265 item 2): startingBalance <= live equity <= startingBalance x (1 + this).
REFERENCE_EQUITY_TOLERANCE = Decimal('0.05')
# Peak margin may use at most half the equity (margin level >= 200%, review 6130418265 item 9).
MAX_MARGIN_SHARE = Decimal('0.5')
# A deploy plan older than this refuses FIT_STALE (review 6130418265 item 3).
PLAN_TTL_SECONDS = 900
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
    SPREAD_SAMPLE_UNAVAILABLE: "GOAT found too few recent {symbol} prices to judge its spread; add it to Market Watch in MT5, then check again.",
    BELOW_MIN_LOT: "This set needs a larger account.",
    CONTRACT_MISMATCH: "This broker's {symbol} contract differs from the one this set was tested on.",
    POINT_SIZE_MISMATCH: "This broker prices {symbol} in a different point size, and GOAT cannot convert this set exactly.",
    SERVER_OFFSET_MISMATCH: "This broker's server clock differs from the one this set was tested on, and this set depends on it.",
    MARGIN_TOO_HIGH: "This set could use more than half of this account's equity as margin.",
    MARGIN_UNKNOWN: "GOAT cannot work out the most margin this set could need, so it is not offered.",
    MONEY_VALUE_UNREADABLE: "GOAT cannot read this set's {name} value, so it cannot check its money limits.",
    EA_INIT_REFUSED: "On this broker this set's {name} would be {value}, which the GOAT EA refuses to start with.",
    ACCOUNT_CURRENCY_UNSUPPORTED: "GOAT cannot convert this account's currency for this portfolio.",
}
PORTFOLIO_MARGIN_MESSAGE = "Together these sets could use more than half of this account's equity as margin."
MT5_NOT_RUNNING_MESSAGE = 'Start MT5 and sign in to your demo account, then check again.'
MT5_STARTED_BY_CHECK_MESSAGE = 'GOAT started MT5 by accident; close it and check again.'
FIT_STALE_MESSAGE = 'The account changed since the check; run the fit again.'
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

# Spread = Ops' exp03_symbol_specs.py method: the median (ask-bid)/point of the real ticks of the last 6 hours
# (copy_ticks_range, COPY_TICKS_INFO), skipping the rollover hours and the weekend, rounded to 0.1 point.
SPREAD_HISTORY_HOURS = 6
MIN_TICKS = 100
FRESH_QUOTE_SECONDS = 120
# The broker clock is read only from a tick seen ARRIVING during the read (its age is then at most this window), never
# from a last tick of unknown age (review 6130418265 item 8). A closed market leaves the offset unknown after it.
ARRIVAL_WINDOW_SECONDS = 10
ARRIVAL_POLL_SECONDS = 0.25

TRADE_MODE_FULL = 4                    # SYMBOL_TRADE_MODE_FULL
MODE_LOTS = dict(FixedLots=0, ScaledLots=1, RiskperSeq=2)
LOTS_PROG_PEAK_SMART = 6
BIAS_EXIT_SMART_RESCUE = 1
POINT_INPUTS = ('Grid_Size', 'Grid_Min', 'Grid_Max', 'Lock_Profit_Size', 'SL_Pips', 'TSL_Size')
FIXED_MONEY_INPUTS = ('MaxLossLocal', 'MaxLossGlobal', 'MaxDailyLossLocal', 'MaxDailyProfitLocal', 'MinLevelEquity', 'MaxLevelEquity')
TF_INPUTS = ('ATR_TF_', 'RSI_TF_', 'EMA_TF_', 'ADX_TF_', 'BB_TF_', 'MACD_TF_', 'RSI2_TF_')
TF_H4 = 240
EDITABLE_INPUTS = frozenset(('Risk', 'Lots_Input') + POINT_INPUTS)
# The broker server clock the house evidence was measured on, when the manifest does not say (reference.serverGmtOffset
# or referenceAccount.serverGmtOffset). 'ny-close': 00:00 server = 17:00 New York, i.e. UTC+2, and UTC+3 while New
# York observes daylight saving time (Darwinex).
REFERENCE_SERVER_TIME = {'Darwinex': 'ny-close'}
OFFSET_MODELS = ('ny-close',)
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
    """'rollover', 'weekend' or None for one UTC instant (contract: spread history).

    rollover: 16:00-18:00 New York every day. That is exactly the server hours 23:00-01:00 Ops' exp03_symbol_specs.py
              skips on the NY-close reference server, written in New York time so it holds on any broker clock.
    weekend:  Friday 16:00 New York to Sunday 18:00 New York (an hour either side of the weekly close and open; it
              contains the NY-close server's whole Saturday and Sunday, which Ops skips)."""
    utc = datetime.fromtimestamp(utc_seconds, timezone.utc)
    ny = utc + timedelta(hours=new_york_offset_hours(utc))
    minutes, day = ny.hour * 60 + ny.minute, ny.weekday()
    if day == 5 or (day == 4 and minutes >= 16 * 60) or (day == 6 and minutes < 18 * 60):
        return 'weekend'
    if 16 * 60 <= minutes < 18 * 60:
        return 'rollover'
    return None


def model_offset_minutes(model, utc_seconds):
    """UTC offset (minutes) of a server clock model at an instant: a number of hours is a fixed offset, 'ny-close' is
    UTC+2 / UTC+3 with New York's daylight saving time. None for anything else."""
    if isinstance(model, bool):
        return None
    if isinstance(model, (int, float)) and math.isfinite(model) and -14 <= model <= 14 and (model * 4) == int(model * 4):
        return int(round(model * 60))
    if model == 'ny-close':
        utc = datetime.fromtimestamp(utc_seconds, timezone.utc)
        return (new_york_offset_hours(utc) + 7) * 60
    return None


def reference_server_offset(member_reference, reference_account, utc_seconds):
    """(minutes or None, source) of the reference server clock at an instant. In order: the member's
    reference.serverGmtOffset, the manifest's referenceAccount.serverGmtOffset, then (only when neither is present) the
    server-name assumption. A field that is present but unreadable is never replaced by the assumption."""
    for source, holder in (('member', member_reference), ('referenceAccount', reference_account)):
        if isinstance(holder, dict) and holder.get('serverGmtOffset') is not None:
            return model_offset_minutes(holder['serverGmtOffset'], utc_seconds), source
    server = (reference_account or {}).get('server')
    model = next((value for prefix, value in REFERENCE_SERVER_TIME.items() if isinstance(server, str) and server.startswith(prefix)), None)
    return model_offset_minutes(model, utc_seconds), 'server_name_assumption' if model else 'unknown'


def measured_server_offset_minutes(quote_times, utc_now):
    """The broker server's UTC offset from the freshest of `quote_times`: tick time (server clock) minus UTC now,
    rounded to 15 minutes. One tick time cannot prove its own age (a tick 3,600 s old on a UTC+4 server reads exactly
    UTC+3), so callers pass ONLY ticks seen arriving during the read (read_broker: ARRIVAL_WINDOW_SECONDS, well under
    FRESH_QUOTE_SECONDS). None when there is none or it sits off the 15-minute grid by more than FRESH_QUOTE_SECONDS."""
    deltas = [value - utc_now for value in quote_times if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0]
    if not deltas:
        return None
    best = max(deltas)
    offset = round(best / 900) * 900
    return int(offset // 60) if abs(best - offset) <= FRESH_QUOTE_SECONDS else None


def history_spread(ticks, *, point, offset_minutes):
    """(median spread in broker points, tick count, None) or (None, count, reason) from the tick history of the window.
    Tick 'time' is the server clock: it is placed in UTC with the measured offset, ticks in the rollover hours or the
    weekend and ticks without a positive bid and ask are skipped, and at least MIN_TICKS must remain."""
    if offset_minutes is None:
        return None, 0, "the broker's server clock could not be read from a recent price"
    spreads, size, shift = [], float(point), offset_minutes * 60
    for tick in ticks if ticks is not None else ():
        bid, ask = float(tick['bid']), float(tick['ask'])
        if not bid > 0 or not ask > 0 or quiet_exclusion(int(tick['time']) - shift):
            continue
        spreads.append((ask - bid) / size)
    if len(spreads) < MIN_TICKS:
        return None, len(spreads), 'only %d ticks outside the rollover hours and the weekend in the last %d hours (at least %d needed)' % (
            len(spreads), SPREAD_HISTORY_HOURS, MIN_TICKS)
    # As Ops' exp03_symbol_specs.py, which measured the reference typicalSpreadPts: round(median, 1) in points.
    return dec(round(statistics.median(spreads), 1)), len(spreads), None


# ------------------------------------------------------------------ symbols

def _tradable(facts):
    return facts.get('trade_mode') == TRADE_MODE_FULL


def _same_instrument(canonical, facts):
    """For a six-letter pair, the broker's base and profit currencies must be reported and be its two halves (a symbol
    without them cannot be proven to be that pair, so it is refused)."""
    if not re.fullmatch(r'[A-Z]{6}', canonical):
        return True
    base, profit = facts.get('currency_base'), facts.get('currency_profit')
    if not base or not profit:
        return False
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


def quote_age_seconds(tick_time, offset_minutes, utc_now):
    """Age in seconds of a tick stamped on the server clock, once the server's offset is proven; None otherwise."""
    if offset_minutes is None or isinstance(tick_time, bool) or not isinstance(tick_time, (int, float)) or tick_time <= 0:
        return None
    return utc_now - (tick_time - offset_minutes * 60)


def is_conversion_pair(facts, account_currency, reference_currency):
    return {facts.get('currency_base'), facts.get('currency_profit')} == {account_currency, reference_currency}


def conversion(account_currency, reference_currency, symbols, *, quotes=None, offset_minutes=None, utc_now=None):
    """(rate, symbol, side): the value of 1 account-currency unit in the reference currency, from a quoted pair on the
    terminal, taking the side that values the account LOWER (bid when the account currency is the base, 1/ask when it
    is the quote). (1, None, None) for the same currency; None when no pair has a price at most FRESH_QUOTE_SECONDS old
    (its last tick time in `quotes`, judged with the proven server offset; review 6130418265 item 3)."""
    if account_currency == reference_currency:
        return Decimal(1), None, None
    candidates = []
    for facts in symbols:
        base, profit = facts.get('currency_base'), facts.get('currency_profit')
        bid, ask = dec(facts.get('bid')), dec(facts.get('ask'))
        if not bid or not ask or bid <= 0 or ask <= 0:
            continue
        age = quote_age_seconds((quotes or {}).get(facts['name']), offset_minutes, utc_now)
        if age is None or abs(age) > FRESH_QUOTE_SECONDS:
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


def _readable(values, defaults, name):
    """True when the SET (or the schema default) gives `name` as a plain decimal GOAT reads exactly. A value that is
    missing or written any other way (9.5e4, 1,000, empty) is unreadable: never taken as 0 or 'no limit'."""
    text = _value(values, defaults, name)
    return isinstance(text, str) and NUMBER.fullmatch(first_field(text)) is not None


MONEY_INPUTS = ('Risk',) + FIXED_MONEY_INPUTS


def unreadable_money(values, defaults):
    """The first money input (Risk or a fixed money limit) whose value cannot be read; None when all are readable."""
    return next((name for name in MONEY_INPUTS if not _readable(values, defaults, name)), None)


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
        if not _readable(values, defaults, name):
            reasons.append(name + ' unreadable')        # could be H4: never assumed neutral
        elif _number(values, defaults, name) == TF_H4:
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
        if not _readable(values, defaults, name) or _number(values, defaults, name) != 0:
            reasons.append(name)
    return not reasons, reasons


class EAInitRefused(ValueError):
    """The converted SET would stop the EA in OnInit (INIT_PARAMETERS_INCORRECT)."""

    def __init__(self, name, value):
        super().__init__('%s %s is inside the EA\'s init refusal band' % (name, value))
        self.name, self.value = name, value


def ea_init_refusal(values, defaults):
    """(name, value) when the EA's OnInit would refuse the distances as written: Grid_Size inside (-0.5, 0.5)
    ("Pip Gap Size too small or zero", mq5:3317). None otherwise."""
    grid = _number(values, defaults, 'Grid_Size')
    if grid is not None and Decimal('-0.5') < grid < Decimal('0.5'):
        return 'Grid_Size', grid
    return None


def _ea_clamps(values, defaults):
    """The EA's post-init clamp outcome of each distance (mq5:3318-3323), compared before and after a point conversion.
    The Grid_Size init refusal (mq5:3317) is checked separately (ea_init_refusal): it stops the EA, it does not clamp."""
    grid_min, grid_max = _number(values, defaults, 'Grid_Min'), _number(values, defaults, 'Grid_Max')
    lock, tp, tsl = _number(values, defaults, 'Lock_Profit_Size'), _number(values, defaults, 'TP_Pips'), _number(values, defaults, 'TSL_Size')
    def inside(value, limit):
        return value is not None and -limit < value < limit
    return (inside(grid_min, Decimal('0.5')), inside(grid_max, Decimal(1)), inside(lock, Decimal(1)),
            inside(None if tp is None or lock is None else tp * lock, Decimal(1)), inside(tsl, Decimal('0.5')))


def point_edits(values, defaults, ratio):
    """{input: text} converting every positive point distance by ratio (reference point / broker point), or raise
    ValueError when it cannot be exact (ratio not a power of ten, or an EA clamp would change), EAInitRefused when the
    EA would refuse to start with the converted distances (Grid_Size 4 at ratio 0.1 is 0.4, mq5:3317)."""
    if ratio == 1:
        refused = ea_init_refusal(values, defaults)
        if refused:
            raise EAInitRefused(*refused)
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
    refused = ea_init_refusal(converted, defaults)
    if refused:
        raise EAInitRefused(*refused)
    if _ea_clamps(values, defaults) != _ea_clamps(converted, defaults):
        raise ValueError('an EA minimum-size rule would change after converting the distances')
    return edits


def floor_step(value, step):
    """value rounded DOWN to a whole number of volume steps (never up)."""
    if step <= 0:
        raise ValueError('volume step must be positive')
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


# ---- the EA's own lot rules, ported line for line in IEEE doubles as MQL5 computes them (GOAT V1.49.mq5)

def _mql_round(x):
    """MathRound: round half away from zero on the exact double (C round())."""
    return float(Decimal(x).to_integral_value(rounding='ROUND_HALF_UP'))


def ea_normalized_lots(raw_volume, vmin, vstep, vmax):
    """NormalizedLots (mq5:445-459): the NEAREST whole number of volume steps, 0 below VOLUME_MIN, capped at VOLUME_MAX."""
    raw_volume, vmin, vstep, vmax = float(raw_volume), float(vmin), float(vstep), float(vmax)
    if vstep <= 0.0:                                   # mq5:447
        return 0.0
    if vmax <= 0.0:                                    # mq5:449
        return 0.0
    steps = _mql_round(raw_volume / vstep)             # mq5:451-452
    lots = steps * vstep                               # mq5:453
    if abs(lots) < vmin:                               # mq5:455
        lots = 0.0
    return min(lots, vmax) if lots >= 0 else -min(abs(lots), vmax)   # mq5:456-457


def ea_solve_start_lots(target_loss, vmin, vstep, vmax, loss_for_start):
    """SolveStartLotsByRisk (mq5:781-827), line for line: a bisection over the volume-step indices that evaluates the
    middle index and its two neighbours each round and keeps the index whose planned loss is closest to the target
    (strictly closer wins, so the first one evaluated keeps a tie). `loss_for_start(lots)` stands in for
    EvalLossForStart (mq5:829-838)."""
    target_loss, vmin, vstep, vmax = float(target_loss), float(vmin), float(vstep), float(vmax)
    if vstep <= 0.0 or vmax <= 0.0:                    # mq5:788
        return vmin
    if target_loss <= 0.0:                             # mq5:789
        return vmin
    kmin = 0                                           # mq5:791
    kmax = int(math.floor((vmax - vmin) / vstep + 1e-9))   # mq5:792
    best_k, best_err = kmin, float('inf')              # mq5:794-795 (DBL_MAX)
    iteration = 0
    while iteration < 40 and kmin <= kmax:             # mq5:797
        kmid = (kmin + kmax) // 2                      # mq5:799 (both non-negative: C division)
        candidates = (max(kmin, kmid - 1), kmid, min(kmax, kmid + 1))   # mq5:801
        loss_mid, mid_set = 0.0, False
        for ki in candidates:                          # mq5:805-815
            start = ea_normalized_lots(vmin + ki * vstep, vmin, vstep, vmax)
            loss = float(loss_for_start(start))
            err = abs(loss - target_loss)
            if err < best_err:
                best_err, best_k = err, ki
            if ki == kmid:
                loss_mid, mid_set = loss, True
        if not mid_set:                                # mq5:816
            break
        if loss_mid > target_loss:                     # mq5:818-819
            kmax = kmid - 1
        else:
            kmin = kmid + 1
        if kmax - kmin <= 0:                           # mq5:821
            break
        iteration += 1
    return ea_normalized_lots(vmin + best_k * vstep, vmin, vstep, vmax)   # mq5:823-824


def _lots(value):
    """A double lot size as an exact Decimal on a 1e-10 grid (0.1 + 3 * 0.1 is 0.4, not 0.40000000000000002)."""
    return dec(round(value, 10)).normalize() + 0


# ---- the EA's lot ladder and planned sequence loss (EvalLossForStart, mq5:829-838), ported line for line in doubles

LOTS_PROG = dict(Start=0, Last=1, Cum=2, Cum2=3, Peak=4, CumPartial=5, PeakSmart=6)


def ladder_inputs(values, defaults):
    """The SET inputs the EA's lot ladder reads, as doubles; None when one is unreadable or out of range."""
    names = ('Mode_Lots_Prog', 'Lots_Exponent', 'Lots_Factor', 'Max_Seq_Trades', 'Lots_Max_Cum', 'Peak_Lots_Pos_PC', 'Lots_Max')
    numbers = [_number(values, defaults, name) for name in names]
    if None in numbers:
        return None
    mode, exponent, factor, trades, cap, peak_pos, lots_max = numbers
    if mode not in LOTS_PROG.values() or trades != trades.to_integral_value() or trades < 1:
        return None
    return dict(mode=int(mode), exponent=float(exponent), factor=float(factor), trades=int(trades), cap=float(cap),
                peak_pos=float(peak_pos), lots_max=float(lots_max))


def _hermite(h):
    h2 = h * h
    h3 = h2 * h
    return 2.0 * h3 - 3.0 * h2 + 1.0, h3 - 2.0 * h2 + h, -2.0 * h3 + 3.0 * h2, h3 - h2


def ea_raw_ladder(start, inputs):
    """BuildRawLots(start) (mq5:840-1004) then ScaleRawLots with StartLots = start (mq5:1006-1021). Returns LotsRaw."""
    mode, exponent, factor, trades = inputs['mode'], inputs['exponent'], inputs['factor'], inputs['trades']
    start = float(start)
    raw, cum = [0.0] * trades, 0.0                                        # mq5:842-843
    for lvl in range(trades):                                             # mq5:845
        n = trades if trades > 0 else 1                                   # mq5:847
        w2 = lvl / n                                                      # mq5:848
        w1 = 1.0 - w2                                                     # mq5:849
        lots = 0.0
        if lvl == 0:                                                      # mq5:852-862
            raw[lvl] = start
            leff0 = w1 * exponent + w2 * exponent * factor
            cum = start / (1.0 - 1.0 / leff0) if mode == LOTS_PROG['Cum2'] and leff0 > 1.0 + 1e-9 else start
            continue
        if mode == LOTS_PROG['Start']:                                    # mq5:865-866
            lots = start * (w1 * exponent + w2 * exponent * factor)
        elif mode == LOTS_PROG['Last']:                                   # mq5:867-869
            if exponent * factor < 0.0:
                lots = start * w1 * math.pow(exponent, lvl) - start * w2 * math.pow(abs(exponent * factor), lvl)
            else:
                lots = start * w1 * math.pow(exponent, lvl) + start * w2 * math.pow(abs(exponent * factor), lvl)
        elif mode in (LOTS_PROG['Cum'], LOTS_PROG['CumPartial'], LOTS_PROG['Cum2']):   # mq5:870-896
            leff = w1 * exponent + w2 * exponent * factor
            lots = cum * (leff - 1.0)
            cum += lots
            if cum < 0.0:
                cum = 0.0
        else:                                                             # Peak, PeakSmart: mq5:897-1000
            pivot = int(_mql_round(trades * inputs['peak_pos'] / 100.0))
            pivot = max(pivot, 1)
            pivot = min(pivot, n - 1)
            c0, cpeak = start, start * inputs['cap']
            s_up = min(max(exponent, 0.01), 5.0)
            s_down = min(max(factor, 0.01), 5.0)
            t = lvl / (n - 1) if n > 1 else 0.0
            tp = pivot / (n - 1) if n > 1 else 0.5
            span_up = tp if tp > 1e-9 else 1.0
            span_down = (1.0 - tp) if (1.0 - tp) > 1e-9 else 1.0
            m0 = s_up * (cpeak - c0) / span_up
            m1 = -s_down * (cpeak - 0.0) / span_down
            if t <= tp or n <= 2:
                denom = tp
                if denom < 1e-12:
                    target = cpeak
                else:
                    h00, h10, h01, h11 = _hermite(min(max(t / denom, 0.0), 1.0))
                    target = h00 * c0 + h10 * (denom * m0) + h01 * cpeak + h11 * (denom * 0.0)
            else:
                denom = 1.0 - tp
                if denom < 1e-12:
                    target = 0.0
                else:
                    h00, h10, h01, h11 = _hermite(min(max((t - tp) / denom, 0.0), 1.0))
                    target = h00 * cpeak + h10 * (denom * 0.0) + h01 * 0.0 + h11 * (denom * m1)
            if lvl == pivot:
                target = cpeak
            if lvl == n - 1:
                target = 0.0
            lots = target - cum
            cum += lots
            if lvl == pivot and abs(cpeak - cum) > 1e-6:
                lots += cpeak - cum
                cum = cpeak
            if lvl == n - 1 and abs(0.0 - cum) > 1e-6:
                lots += 0.0 - cum
                cum = 0.0
        raw[lvl] = lots                                                   # mq5:1001
    running = peak = 0.0                                                  # ScaleRawLots, mq5:1008-1015
    for lots in raw:
        running += lots
        if running < 0.0:
            running = 0.0
        if running > peak:
            peak = running
    scale = 1.0                                                           # mq5:1017-1018
    if peak > start * inputs['cap']:
        scale = (start * inputs['cap']) / peak
    return [raw[0]] + [lots * scale for lots in raw[1:]]                  # mq5:1020


def ea_standing(start, inputs, vmin, vstep, vmax):
    """LotsCum (BuildNormalizedLots + BuildCumulativeLots, mq5:1023-1036): the floored running sum of each planned
    level's NormalizedLots (the nearest step; 0 below VOLUME_MIN)."""
    standing, out = 0.0, []
    for lots in ea_raw_ladder(start, inputs):
        standing += ea_normalized_lots(lots, vmin, vstep, vmax)
        if standing < 0.0:
            standing = 0.0
        out.append(standing)
    return out


def ea_peak_standing(start, inputs, vmin, vstep, vmax):
    """The most lots one sequence can stand in. The EA trades its planned LotsNorm level by level (mq5:1676-1686;
    PeakSmart refills to the planned LotsCum, mq5:1349-1376) except CumPartial, which compounds the ACTUAL standing
    (CalcNextLotsCumPartial, mq5:1539-1563): ported here without retrace closes (closes only lower what follows)."""
    planned = max(ea_standing(start, inputs, vmin, vstep, vmax))
    if inputs['mode'] != LOTS_PROG['CumPartial']:
        return planned
    start_lots = ea_normalized_lots(float(start), vmin, vstep, vmax)      # level 0: Lots_Calc = NormalizedLots(StartLots)
    standing = peak = start_lots
    n = inputs['trades']
    for level_count in range(1, n):
        lvl = min(level_count, n - 1)                                     # mq5:1545
        w2 = lvl / n
        w1 = 1.0 - w2
        leff = w1 * inputs['exponent'] + w2 * inputs['exponent'] * inputs['factor']
        if standing <= 0.0:                                               # mq5:1542
            next_lots = 0.0
        else:
            next_lots = standing * (leff - 1.0)                           # mq5:1550
            if next_lots > 0.0 and inputs['cap'] > 0.0:                   # mq5:1551-1556
                remaining = float(start) * inputs['cap'] - standing
                next_lots = 0.0 if remaining <= 0.0 else min(next_lots, remaining)
            if next_lots > 0.0 and inputs['lots_max'] > 0.01:             # mq5:1557-1561
                next_lots = min(next_lots, inputs['lots_max'] * float(start))
            next_lots = ea_normalized_lots(next_lots, vmin, vstep, vmax)  # mq5:1562, 1686
        if next_lots < 0.0 and abs(next_lots) < vmin:                     # mq5:1691: a cut below VOLUME_MIN is no trade
            next_lots = 0.0
        standing = max(standing + next_lots, 0.0)
        peak = max(peak, standing)
    return max(planned, peak)


def grid_shape(values, defaults):
    """The level distances of BuildDistances (mq5:1603-1614) via GetSize(GRID_VALID) (mq5:6754-6767), in one unit:
    ATR when Grid_Size < 0, 10 x Point otherwise. The unit cancels in loss(L) / loss(startLot), so no market data is
    needed, but only when Grid_Min_ and an enabled Grid_Max_ (after the init clamps, mq5:2986-2987, 3318-3319) are the
    same kind as Grid_Size. Returns [d_1 .. d_{N-1}] or None (mixed kinds, unreadable)."""
    names = ('Grid_Size', 'Grid_Min', 'Grid_Max', 'Grid_Exponent', 'Grid_Factor', 'Max_Seq_Trades')
    numbers = [_number(values, defaults, name) for name in names]
    if None in numbers:
        return None
    grid, grid_min, grid_max, exponent, factor, trades = (float(x) for x in numbers)
    trades = int(trades)
    if grid == 0.0 or trades < 1:
        return None
    if -0.5 < grid_min < 0.5:                                             # mq5:3318
        grid_min = -0.5
    max_enabled = not (-1.0 < grid_max < 1.0)                             # mq5:3319 (999999: disabled)
    atr = grid < 0.0
    if (grid_min < 0.0) != atr or (max_enabled and (grid_max < 0.0) != atr):
        return None
    base, low, high = abs(grid), abs(grid_min), abs(grid_max) if max_enabled else math.inf
    sizes = []
    for lvl in range(1, trades):
        if exponent <= 0.0:                                               # mq5:6759
            size = base
        else:
            n = trades if trades > 0 else 1
            w2 = lvl / n
            w1 = 1.0 - w2
            f_eff = w1 * (1.0 / exponent) + w2 * (1.0 / (exponent * factor))   # mq5:6760
            if -1e-12 <= f_eff <= 1e-12:
                f_eff = -1e-12 if f_eff < 0 else 1e-12
            size = base * math.pow(1.0 / f_eff, lvl - 1)                  # mq5:6762-6764
            size = max(size, low)                                         # mq5:6765
            size = min(size, high)                                        # mq5:6766
        sizes.append(abs(size))                                           # mq5:1611
    return sizes


def ea_loss_shape(start, inputs, shape, vmin, vstep, vmax):
    """FindCumLoss (mq5:1616-1634) in grid units per unit of value per lot: the max over prefixes of d_i x LotsCum[i-1]."""
    standing = ea_standing(start, inputs, vmin, vstep, vmax)
    loss = peak = 0.0
    for i in range(1, inputs['trades']):
        loss += shape[i - 1] * max(standing[i - 1], 0.0)
        if loss > peak:
            peak = loss
    return peak


class SequenceLoss:
    """The EA's planned sequence loss (EvalLossForStart, mq5:829-838) on this broker, in the account currency:
    loss(L) = reference Risk x G(L) / G(reference.startLot) / (contract ratio x rate), G = ea_loss_shape. Every unit
    (ATR or point, value per point per lot) cancels in the ratio; reference.startLot is the EA's pick at the reference
    Risk, so its planned loss is that Risk."""

    def __init__(self, inputs, shape, *, reference_risk, start_lot, ref_vmin, ref_vstep, ref_vmax, conversion):
        self.inputs, self.shape = inputs, shape
        anchor = ea_loss_shape(float(start_lot), inputs, shape, float(ref_vmin), float(ref_vstep), float(ref_vmax))
        if not anchor > 0.0:
            raise ValueError('the reference start lot plans no loss')
        self.per_unit = float(reference_risk) / anchor / float(conversion)

    def __call__(self, start, vmin, vstep, vmax):
        return self.per_unit * ea_loss_shape(start, self.inputs, self.shape, float(vmin), float(vstep), float(vmax))


def sequence_loss(values, defaults, reference, *, risk, conversion):
    """SequenceLoss for a member with reference.startLot, or None when the ladder, the grid shape or the anchor is
    unknown."""
    inputs, shape = ladder_inputs(values, defaults), grid_shape(values, defaults)
    if inputs is None or shape is None or reference.get('startLot') is None or risk is None or risk <= 0:
        return None
    try:
        return SequenceLoss(inputs, shape, reference_risk=risk, start_lot=reference['startLot'], ref_vmin=reference['volumeMin'],
                            ref_vstep=reference['volumeStep'], ref_vmax=reference.get('volumeMax') or Decimal(10) ** 9,
                            conversion=conversion)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def uses_risk(values, defaults):
    """The EA requires Risk >= 10 when it sizes by Risk or closes by it (mq5:3253-3260, 3271)."""
    return (_number(values, defaults, 'Mode_Lots') == MODE_LOTS['RiskperSeq'] or _flag(values, defaults, 'Sequence_MLPS_Hard_Close')
            or _number(values, defaults, 'Mode_Lots_Prog') == LOTS_PROG_PEAK_SMART
            or _number(values, defaults, 'Mode_Bias_Exit') == BIAS_EXIT_SMART_RESCUE)


def equity_rules(values, defaults, *, lot_factor, money_factor, broker, reference):
    """The equity-dependent rules for one member at one equity. Returns dict(code, message, edits, scaled, start_lots).
    The same function judges the review (broker-fit) and the deploy-time re-check (stale_fit).

    lot_factor   = scale x (reference contract size / broker contract size): what lots multiply by.
    money_factor = account equity / reference equity (= scale / rate): what money inputs (account currency) multiply by.
    Never rounds up what GOAT writes: Lots_Input rounds DOWN to the broker volume step (always, also at factor 1: the
    EA would otherwise round an off-step value to the NEAREST step, mq5:451-453, 1686) and is capped at VOLUME_MAX,
    Risk rounds DOWN to the cent, and anything that would then sit below VOLUME_MIN (or Risk below the EA's 10) is
    BELOW_MIN_LOT. The RiskperSeq start lot is the EA's own pick (ea_solve_start_lots), which may round up."""
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
    start = planned_loss = None
    if mode in (MODE_LOTS['FixedLots'], MODE_LOTS['ScaledLots']):
        if lots_input is None:
            return dict(code=CONTRACT_MISMATCH, message=NOT_STATED_MESSAGE.format(name='Lots_Input'))
        # Always on the broker's step grid and under its VOLUME_MAX, whatever the factor (review 6130418265 item 1).
        scaled_lots = lots_input * lot_factor
        start = floor_step(min(scaled_lots, vmax) if vmax else scaled_lots, vstep)
        if start != lots_input:
            if 'Lots_Input' not in values:
                return dict(code=CONTRACT_MISMATCH, message=NOT_STATED_MESSAGE.format(name='Lots_Input'))
            edits['Lots_Input'] = format_like(start, first_field(values['Lots_Input']))
        if start < vmin:
            return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
        bound = start
    elif mode == MODE_LOTS['RiskperSeq']:
        # The EA picks the start lot itself: SolveStartLotsByRisk (mq5:781-827) on EvalLossForStart (mq5:829-838), the
        # volume step whose planned sequence loss is NEAREST the deployed Risk. Both are ported (ea_solve_start_lots,
        # SequenceLoss): the lot ladder with every level's NormalizedLots and the grid shape, anchored on
        # reference.startLot (review 6132018108 item B; a linear model picked 0.01 where the EA picks 0.02).
        # BELOW_MIN_LOT when even VOLUME_MIN plans to lose more than the deployed Risk (the EA would be forced up to it).
        # Without reference.startLot the reference VOLUME_MIN is its only proven lower bound.
        known = reference.get('startLot')
        if known is not None:
            # An unreported VOLUME_MAX is taken as unbounded: the EA would return VOLUME_MIN (mq5:788), which would
            # understate the margin.
            top = vmax if vmax else Decimal(10) ** 9
            loss = sequence_loss(values, defaults, reference, risk=risk, conversion=lot_factor / money_factor)
            if loss is None:
                # Not computable (MARGIN_UNKNOWN 'loss_unknown' in the review; reached only under the reference-identical
                # exemption): the linear reference model stands in for the pick, never for the margin.
                per_lot = float(risk * money_factor / (known * lot_factor))
                if new_risk / Decimal(repr(per_lot)) < vmin:
                    return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
                start = _lots(ea_solve_start_lots(new_risk, vmin, vstep, top, lambda lots: lots * per_lot))
            else:
                if loss(vmin, vmin, vstep, top) > float(new_risk):
                    return dict(code=BELOW_MIN_LOT, message=message(BELOW_MIN_LOT))
                start = _lots(ea_solve_start_lots(new_risk, vmin, vstep, top, lambda lots: loss(lots, vmin, vstep, top)))
                planned_loss = _lots(round(loss(start, vmin, vstep, top), 2))
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
    # Lots_Max and Lots_Max_Cum are reported as written: multipliers of the start lot, never scaled. startLot is the
    # EA's start lot here; plannedLoss its planned sequence loss (RiskperSeq, account currency).
    scaled = dict(Risk=new_risk, Lots_Max=lots_max, Lots_Max_Cum=lots_max_cum, Lots_Input=written_lots, startLot=start,
                  plannedLoss=planned_loss)
    return dict(code=None, message=None, edits=edits, scaled=scaled, start_lots=start)


def peak_lots(values, defaults, start, broker):
    """Worst-case concurrent lots of one member: the most one sequence of the EA's own ladder stands in at this start
    lot on this broker (ea_peak_standing: every level's NormalizedLots, review 6132018108 items B and B2), both
    directions when a buy and a sell sequence may coexist. None when the start lot or the ladder is unknown."""
    inputs = ladder_inputs(values, defaults)
    if start is None or inputs is None:
        return None
    top = broker['volume_max'] if broker['volume_max'] else Decimal(10) ** 9
    lots = _lots(ea_peak_standing(start, inputs, float(broker['volume_min']), float(broker['volume_step']), float(top)))
    # An unreadable Mode_Trade or Allow_Opposite_Seq is taken as the worst case (both directions).
    mode_trade = _number(values, defaults, 'Mode_Trade')
    opposite = _value(values, defaults, 'Allow_Opposite_Seq')
    opposite = first_field(opposite) not in ('false', '0') if isinstance(opposite, str) else True
    both = mode_trade in (None, 0) and opposite
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
    for key in ('startLot', 'swapLong', 'swapShort', 'volumeMax'):
        facts[key] = dec(reference.get(key))
    if facts['startLot'] is not None and facts['startLot'] <= 0:
        facts['startLot'] = None
    source = reference.get('startLotSource')
    facts['startLotSource'] = source if isinstance(source, str) and len(source) <= 200 else None
    return facts


def broker_facts(facts):
    out = dict(name=facts['name'])
    for key in ('point', 'trade_contract_size', 'trade_tick_size', 'trade_tick_value', 'volume_min', 'volume_step', 'volume_max',
                'swap_long', 'swap_short', 'bid', 'ask'):
        out[key] = dec(facts.get(key))
    out['digits'] = facts.get('digits')
    return out


def _text(number):
    """An exact Decimal as a JSON string (the deploy re-check reads it back without float rounding)."""
    return None if number is None else format(number, 'f')


# ------------------------------------------------------------------ the result

def build_result(manifest, sets, *, account, symbols, ticks, quotes, margins, schema, utc_now, equity=None, arrived=()):
    """BrokerFitResult (contract goat-broker-fit-v1) from plain data.

    manifest  goat-house-portfolio-v1 dict; sets {setSha256: reference SET bytes}
    account   dict(login, server, currency, equity, leverage, demo)
    symbols   [dict(name, trade_mode, digits, point, trade_contract_size, trade_tick_size, trade_tick_value, volume_min,
              volume_step, volume_max, currency_base, currency_profit, swap_long, swap_short, bid, ask)]
    ticks     {broker symbol: ticks of the last SPREAD_HISTORY_HOURS, each with time (server clock), bid, ask}
    quotes    {broker symbol: time of its last tick (server clock)}: mapped symbols and conversion pairs
    arrived   the symbols whose last tick was seen ARRIVING during the read (read_broker): only they prove the broker's
              UTC offset; every other quote's age is judged with that offset
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
    measured = measured_server_offset_minutes([quotes[name] for name in arrived if name in quotes], utc_now)
    converted = conversion(account.get('currency'), ref_currency, symbols, quotes=quotes, offset_minutes=measured, utc_now=utc_now)
    rate = converted[0] if converted else None
    scale = account_equity * rate / ref_equity if rate else None
    conditions = reference_identical_conditions(ref_account, server=account.get('server'), currency=account.get('currency'),
                                                leverage=account.get('leverage'), live_equity=account.get('equity'), scale=scale)
    clock = dict(same_server=account.get('server') == ref_account['server'],
                 measured=measured, utc_now=utc_now, account=ref_account,
                 reference_identical=all(conditions.values()))
    by_name = {facts['name']: facts for facts in symbols}
    members, internals = [], []
    for member in manifest['members']:
        row, inner = _member(member, sets, defaults, by_name, symbols, ticks, margins, schema, scale=scale, rate=rate,
                             account_equity=account_equity, clock=clock, ref_currency=ref_currency, reference_equity=ref_equity)
        members.append(row); internals.append(inner)
    # Every member's deployed bytes must be the reference's for the exemption; one changed member revokes it for all.
    conditions['bytesUnchanged'] = all(row['setSha256Deployed'] == row['setSha256Reference'] for row in members
                                       if row['setSha256Deployed'] is not None)
    if not conditions['bytesUnchanged']:
        for index, (row, inner) in enumerate(zip(members, internals)):
            if inner.get('exempt'):
                basis = inner.pop('exempt')
                row, inner = _excluded(row, MARGIN_UNKNOWN, message(MARGIN_UNKNOWN), inner)
                row.update(marginReason=None, margin=dict(row['margin'], basis=basis))
                row['margin'].pop('unknownBasis', None)
                inner['min_equity'] = None
                members[index], internals[index] = row, inner
    used = any(inner.get('exempt') for inner in internals)
    result = _portfolio(manifest, account, account_equity, ref_equity, ref_currency, rate, converted, scale, members, internals,
                        clock)
    live = dec(account.get('equity'))
    result['referenceIdentical'] = dict(applies=all(conditions.values()), used=used, reason=REFERENCE_IDENTICAL_MARGIN if used else None,
                                        conditions=conditions, liveEquity=num(live),
                                        liveScale=num(live * rate / ref_equity) if live and rate else None,
                                        equityTolerance=num(REFERENCE_EQUITY_TOLERANCE))
    # What the deploy plan's brokerFit block carries besides its members (+ members[].deploy). The deploy re-derives
    # every value from `manifest`, `equity` and the live broker and only COMPARES the rest (review 6130418265 item 7).
    result['deployBasis'] = None if rate is None else dict(
        schema=DEPLOY_SCHEMA, scale=num(scale), equity=_text(account_equity), referenceEquity=_text(ref_equity),
        accountCurrency=account.get('currency'), rate=_text(rate), reviewedAtUtc=int(utc_now), manifest=manifest,
        referenceIdentical=None if not used else dict(
            server=ref_account['server'], currency=ref_currency, leverage=ref_account.get('leverage'),
            startingBalance=_text(ref_equity), reason=REFERENCE_IDENTICAL_MARGIN))
    return result


def reference_identical_conditions(ref_account, *, server, currency, leverage, live_equity, scale):
    """The account-level conditions of the reference-identical margin exemption (goatai#2350 6130033743): the same
    server, account currency and leverage as referenceAccount, the account's own LIVE equity in the ONE-SIDED band
    startingBalance <= live <= startingBalance x 1.05 (review 6130418265 item 2: below the reference the reference
    bytes would over-risk), and the deployed bytes' scale (planning equity x rate / startingBalance) exactly 1.0. With
    the same currency the live scale is then live / startingBalance, inside [1, 1.05]. bytesUnchanged is added by the
    caller."""
    reference_equity, live = dec(ref_account.get('startingBalance')), dec(live_equity)
    return dict(sameServer=server == ref_account.get('server'), sameCurrency=currency == ref_account.get('currency'),
                sameLeverage=dec(leverage) is not None and dec(leverage) == dec(ref_account.get('leverage')),
                equityWithinTolerance=bool(live and reference_equity
                                           and reference_equity <= live <= reference_equity * (1 + REFERENCE_EQUITY_TOLERANCE)),
                scaleOne=scale is not None and scale == 1)


def _excluded(row, code, text, inner=None):
    row.update(status='excluded', code=code, message=text, scaled=None, setSha256Deployed=None, edits=None, deploy=None)
    return row, inner or dict(weight=Decimal(1), min_equity=None, margin=None)


def _member(member, sets, defaults, by_name, symbols, ticks, margins, schema, *, scale, rate, account_equity, clock,
            ref_currency, reference_equity):
    raw = sets[member['setSha256']]
    values = set_values(raw, schema)
    mode = _number(values, defaults, 'Mode_Lots')
    risk = _number(values, defaults, 'Risk')
    weight = risk if mode == MODE_LOTS['RiskperSeq'] and risk and risk > 0 else None
    row = dict(memberId=member['memberId'], canonicalSymbol=member['canonicalSymbol'], brokerSymbol=None,
               period=member['timeframe'], status='fit', code=None, message=None, spreadRatio=None, scaled=None,
               setSha256Reference=sha256(raw), setSha256Deployed=None, deployFileName=None, edits=None, deploy=None,
               spread=None, pointConversion=None, serverOffset=None, costs=None, margin=None, marginReason=None,
               startLotSource=None)
    inner = dict(weight=weight, min_equity=None, margin=None)
    if rate is None:
        return _excluded(row, ACCOUNT_CURRENCY_UNSUPPORTED, message(ACCOUNT_CURRENCY_UNSUPPORTED), inner)
    # A money value GOAT cannot read is never 0 / "no limit" (review 6130418265 item 5): the member is left out.
    unreadable = unreadable_money(values, defaults)
    if unreadable:
        return _excluded(row, MONEY_VALUE_UNREADABLE, message(MONEY_VALUE_UNREADABLE, name=unreadable), inner)
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
    row['startLotSource'] = reference['startLotSource']
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
    except EAInitRefused as exc:
        return _excluded(row, EA_INIT_REFUSED, message(EA_INIT_REFUSED, name=exc.name, value=format_like(exc.value, '')), inner)
    except ValueError as exc:
        return _excluded(row, POINT_SIZE_MISMATCH, message(POINT_SIZE_MISMATCH, symbol=symbol) + ' (' + str(exc) + ')', inner)
    row['pointConversion'] = dict(referencePoint=num(reference['point']), brokerPoint=num(broker['point']),
                                  factor=num(point_ratio), inputs=dict(converted)) if point_ratio != 1 else None
    # Server clock: the broker's measured GMT offset against the reference's (field, else the server-name assumption).
    measured = clock['measured']
    expected, source = reference_server_offset(member['reference'], clock['account'], clock['utc_now'])
    neutral, reasons = offset_neutral(values, defaults, member['timeframe'])
    same_offset = clock['same_server'] or (measured is not None and expected is not None and measured == expected)
    row['serverOffset'] = dict(sameServer=clock['same_server'], brokerMinutes=measured, referenceMinutes=expected,
                               referenceSource=source, offsetNeutral=neutral, dependsOn=reasons)
    if not same_offset and not (neutral and measured is not None and expected is not None and (measured - expected) % 60 == 0):
        return _excluded(row, SERVER_OFFSET_MISMATCH, message(SERVER_OFFSET_MISMATCH), inner)
    # Spread: the median of the last hours of real ticks (Ops' method), in reference points.
    median, count, reason = history_spread(ticks.get(symbol), point=broker['point'], offset_minutes=measured)
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
                         ticks=count, hours=SPREAD_HISTORY_HOURS)
    # Costs: shown, never refused. MT5's Python SDK does not expose commission.
    row['costs'] = dict(swapLong=num(broker['swap_long']), swapShort=num(broker['swap_short']),
                        referenceSwapLong=num(reference['swapLong']), referenceSwapShort=num(reference['swapShort']),
                        commission=None, commissionSource='not_exposed_by_mt5_sdk')
    if not fits:
        return _excluded(row, SPREAD_TOO_WIDE, message(SPREAD_TOO_WIDE, symbol=symbol), inner)
    # Fixed money limits are account-level amounts GOAT does not scale: a non-zero one only at the reference equity
    # itself (judged again on the LIVE equity at deploy, stale_members).
    fixed = fixed_money_off_reference(values, defaults, account_equity, reference_equity)
    if fixed:
        return _excluded(row, CONTRACT_MISMATCH, FIXED_MONEY_MESSAGE.format(name=fixed), inner)
    # Margin must be knowable at every equity (fail closed): the SDK's margin per lot, an EA lot cap, and a start lot
    # (FixedLots/ScaledLots: Lots_Input; RiskperSeq: reference.startLot).
    per_lot = dec(margins.get(symbol))
    if per_lot is not None and per_lot <= 0:
        per_lot = None
    unknown = ('margin_per_lot_unavailable' if per_lot is None else 'lot_ladder_unknown' if ladder_inputs(values, defaults) is None
               else 'start_lot_unknown' if mode == MODE_LOTS['RiskperSeq'] and reference['startLot'] is None
               # Review 6132018108 item B: the EA's planned loss is not computable (mixed ATR / point grid inputs).
               else 'loss_unknown' if mode == MODE_LOTS['RiskperSeq'] and sequence_loss(values, defaults, reference,
                                                                                     risk=_number(values, defaults, 'Risk'),
                                                                                     conversion=1) is None
               else None)
    exempt = False
    if unknown:
        row['margin'] = dict(perLot=num(per_lot), peakLots=None, required=None, basis=unknown)
        # Ruling goatai#2350 6130033743: a follower of the reference never regresses. On a reference-identical account
        # (same server, currency and leverage, equity within 5%, scale exactly 1.0) a member whose bytes stay the
        # reference's runs exactly as the evidence did, so the reference account's evidenced margin stands in. The
        # bytes-unchanged condition is checked here for this member and for the whole portfolio in build_result.
        if not clock['reference_identical']:
            return _excluded(row, MARGIN_UNKNOWN, message(MARGIN_UNKNOWN), inner)
        exempt = True
    deploy_rules = dict(volume_min=broker['volume_min'], volume_step=broker['volume_step'], volume_max=broker['volume_max'],
                        contract_ratio=contract_ratio, reference_volume_min=reference['volumeMin'],
                        reference_volume_step=reference['volumeStep'], reference_volume_max=reference['volumeMax'],
                        start_lot=reference['startLot'])
    def at(trial_equity):
        return rules_at(values, defaults, deploy_rules, equity=trial_equity, reference_equity=reference_equity, rate=rate)
    fixed_money = any(_number(values, defaults, name) != 0 for name in FIXED_MONEY_INPUTS)
    if not exempt:
        inner['min_equity'] = None if fixed_money else min_equity(lambda trial: at(trial)['code'] is None)
    outcome = at(account_equity)
    if outcome['code']:
        return _excluded(row, outcome['code'], outcome['message'], inner)
    edits = dict(outcome['edits']); edits.update(converted)
    if exempt:
        if edits:
            return _excluded(row, MARGIN_UNKNOWN, message(MARGIN_UNKNOWN), inner)
        # An exempt member is tradable only at scale 1.0, i.e. at the reference equity itself.
        inner['min_equity'] = None if fixed_money else reference_equity
    deployed = rewrite_set(raw, edits)
    row.update(scaled={key: num(value) for key, value in outcome['scaled'].items()}, edits=edits, setSha256Deployed=sha256(deployed))
    if exempt:
        row['margin'] = dict(row['margin'], basis=REFERENCE_IDENTICAL_MARGIN, unknownBasis=unknown)
        row['marginReason'] = REFERENCE_IDENTICAL_MARGIN
        inner['exempt'] = unknown
    else:
        # Margin at the scaled caps and this account's leverage (the SDK's own calculation).
        lots = peak_lots(values, defaults, outcome['start_lots'], broker)
        required = per_lot * lots
        row['margin'] = dict(perLot=num(per_lot), peakLots=num(lots), required=num(required), basis='ea_caps',
                             limit=num(account_equity * MAX_MARGIN_SHARE))
        inner['margin'] = required
        # Margin level must stay >= 200%: the worst case may use at most half the equity (review 6130418265 item 9).
        if required > account_equity * MAX_MARGIN_SHARE:
            return _excluded(row, MARGIN_TOO_HIGH, message(MARGIN_TOO_HIGH), inner)
    # What the deploy plan's brokerFit block carries for this member: claims the deploy compares with its own
    # re-derivation from the manifest and the live broker (stale_members), never inputs.
    row['deploy'] = dict(memberId=member['memberId'], brokerSymbol=symbol, deployFileName=row['deployFileName'],
                         setSha256Reference=row['setSha256Reference'], setSha256Deployed=row['setSha256Deployed'], edits=edits,
                         rules={RULE_KEYS[key]: _text(value) for key, value in deploy_rules.items()})
    return row, inner


def fixed_money_off_reference(values, defaults, equity, reference_equity):
    """The first non-zero fixed money limit when `equity` is not exactly the reference equity; None otherwise."""
    if equity == reference_equity:
        return None
    return next((name for name in FIXED_MONEY_INPUTS if _number(values, defaults, name) != 0), None)


# Deploy-time rule facts, as the plan carries them (exact decimal strings).
RULE_KEYS = dict(volume_min='volumeMin', volume_step='volumeStep', volume_max='volumeMax', contract_ratio='contractRatio',
                 reference_volume_min='referenceVolumeMin', reference_volume_step='referenceVolumeStep',
                 reference_volume_max='referenceVolumeMax', start_lot='startLot')
OPTIONAL_RULES = ('volume_max', 'reference_volume_max', 'start_lot')


def rules_at(values, defaults, rules, *, equity, reference_equity, rate):
    """equity_rules at one equity in the account currency. Lots follow the equity in the reference currency (x rate) and
    the contract size; money inputs are in the account currency, so their factor is equity / reference equity exactly."""
    return equity_rules(values, defaults, lot_factor=equity * rate / reference_equity * rules['contract_ratio'],
                        money_factor=equity / reference_equity,
                        broker=dict(volume_min=rules['volume_min'], volume_step=rules['volume_step'], volume_max=rules['volume_max']),
                        reference=dict(volumeMin=rules['reference_volume_min'], volumeStep=rules['reference_volume_step'],
                                       volumeMax=rules['reference_volume_max'], startLot=rules['start_lot']))


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


def _portfolio(manifest, account, account_equity, ref_equity, ref_currency, rate, converted, scale, members, internals, clock):
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
        # margin grows with equity at the same rate, so MARGIN_TOO_HIGH does not either.
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
    fit_inner = [inner for inner, row in zip(internals, members) if row['status'] == 'fit']
    margin_total = sum(inner['margin'] for inner in fit_inner if inner['margin'] is not None)
    # Verified: computed for every fit member, or (never silently) stood in for by the reference account's evidence.
    margin_verified = all(inner['margin'] is not None or inner.get('exempt') for inner in fit_inner)
    margin_exemption = REFERENCE_IDENTICAL_MARGIN if any(inner.get('exempt') for inner in fit_inner) else None
    if rate is None:
        refusal = dict(code=ACCOUNT_CURRENCY_UNSUPPORTED, message=message(ACCOUNT_CURRENCY_UNSUPPORTED))
    elif min_equity_value is None:
        refusal = dict(code=PORTFOLIO_BROKER_UNFIT, message="Less than 90% of this portfolio can trade on this account's broker.")
    elif account_equity < min_equity_value:
        refusal = dict(code=PORTFOLIO_NEEDS_LARGER_ACCOUNT, message='This portfolio needs a larger account.')
    elif margin_total > account_equity * MAX_MARGIN_SHARE:
        refusal = dict(code=MARGIN_TOO_HIGH, message=PORTFOLIO_MARGIN_MESSAGE)
    elif share < TRADABLE_SHARE:
        refusal = dict(code=PORTFOLIO_BROKER_UNFIT, message="Less than 90% of this portfolio can trade on this account's broker.")
    expected, source = reference_server_offset(None, clock['account'], clock['utc_now'])
    sources = sorted({row['serverOffset']['referenceSource'] for row in members if row.get('serverOffset')})
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
        margin=dict(required=num(margin_total), equity=num(account_equity), limit=num(account_equity * MAX_MARGIN_SHARE),
                    verified=margin_verified, level='member_and_portfolio', exemption=margin_exemption),
        # referenceSource 'server_name_assumption' says the manifest gave no serverGmtOffset and GOAT assumed the
        # reference server's clock from its name; memberSources lists what each checked member used.
        serverOffset=dict(brokerMinutes=clock['measured'], referenceMinutes=expected, referenceSource=source,
                          memberSources=sources, assumed='server_name_assumption' in (sources or [source])),
        members=members)


# ------------------------------------------------------------------ deploy hook (studio_demo_deploy)

DEPLOY_BLOCK_KEYS = frozenset(('schema', 'scale', 'equity', 'referenceEquity', 'accountCurrency', 'rate', 'reviewedAtUtc',
                               'manifest', 'referenceIdentical', 'members', 'excludedSets'))
EXCLUDED_SET_KEYS = frozenset(('memberId', 'contentBase64'))
REFERENCE_IDENTICAL_KEYS = frozenset(('server', 'currency', 'leverage', 'startingBalance', 'reason'))
DEPLOY_MEMBER_KEYS = frozenset(('index', 'memberId', 'brokerSymbol', 'deployFileName', 'setSha256Reference', 'setSha256Deployed',
                                'edits', 'rules'))
DEPLOY_IDENTITY_PREFIX = 'goat-house-deploy-identity-v1'


def _exact(value, *, positive=True, optional=False):
    """A plan number given as an exact decimal string (as broker-fit writes it) or a JSON number."""
    if value is None and optional:
        return None
    number = dec(value) if isinstance(value, str) and NUMBER.fullmatch(value) else (
        dec(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
    if number is None or (positive and number <= 0):
        raise ValueError('Invalid broker-fit number in the demo deploy plan')
    return number


def deploy_entries(block, members):
    """Validate a plan's brokerFit block against its members; returns its member entries, in plan order. The block is
    the broker-fit result's deployBasis plus each fit member's `deploy` with its plan index. Shape only, plus what the
    plan itself must agree on: every entry names a distinct manifest member, its reference hash is that member's
    setSha256, and its brokerSymbol / deployFileName are the plan member's symbol / fileName and the manifest setName
    with that symbol. Every VALUE is re-derived at deploy (stale_members), never taken from here."""
    if (type(block) is not dict or set(block) != DEPLOY_BLOCK_KEYS or block['schema'] != DEPLOY_SCHEMA
            or isinstance(block['scale'], bool) or not isinstance(block['scale'], (int, float))
            or not math.isfinite(block['scale']) or block['scale'] <= 0
            or not isinstance(block['accountCurrency'], str) or not CURRENCY.fullmatch(block['accountCurrency'])
            or type(block['reviewedAtUtc']) is not int or block['reviewedAtUtc'] <= 0):
        raise ValueError('Invalid broker-fit block in the demo deploy plan')
    _exact(block['equity']); _exact(block['referenceEquity']); _exact(block['rate'])
    identical = block['referenceIdentical']
    if identical is not None and (
            type(identical) is not dict or set(identical) != REFERENCE_IDENTICAL_KEYS or identical['reason'] != REFERENCE_IDENTICAL_MARGIN
            or not isinstance(identical['server'], str) or not isinstance(identical['currency'], str)
            or not CURRENCY.fullmatch(identical['currency']) or type(identical['leverage']) is not int or identical['leverage'] < 1):
        raise ValueError('Invalid broker-fit block in the demo deploy plan')
    if identical is not None:
        _exact(identical['startingBalance'])
    try:
        validate_manifest(block['manifest'])
    except Refusal as exc:
        raise ValueError('Invalid broker-fit manifest in the demo deploy plan: ' + str(exc)) from exc
    by_id = {member['memberId']: member for member in block['manifest']['members']}
    entries = block['members']
    if type(entries) is not list or len(entries) != len(members):
        raise ValueError('The broker-fit block must name every deployed member, and only them')
    seen = set()
    for index, (entry, plan_member) in enumerate(zip(entries, members)):
        if (type(entry) is not dict or set(entry) != DEPLOY_MEMBER_KEYS
                or entry['index'] != index or not isinstance(entry['memberId'], str) or not MEMBER_ID.fullmatch(entry['memberId'])
                or not SHA256.fullmatch(str(entry['setSha256Reference'])) or not SHA256.fullmatch(str(entry['setSha256Deployed']))
                or not isinstance(entry['brokerSymbol'], str) or not isinstance(entry['deployFileName'], str)
                or type(entry['edits']) is not dict or type(entry['rules']) is not dict or set(entry['rules']) != set(RULE_KEYS.values())):
            raise ValueError('Invalid broker-fit member %d in the demo deploy plan' % index)
        for key, name in RULE_KEYS.items():
            _exact(entry['rules'][name], optional=key in OPTIONAL_RULES)
        source = by_id.get(entry['memberId'])
        if source is None or entry['memberId'] in seen:
            raise ValueError('Broker-fit member %d is not a distinct member of the plan\'s manifest' % index)
        seen.add(entry['memberId'])
        plan_member = plan_member if isinstance(plan_member, dict) else {}
        if (entry['setSha256Reference'] != source['setSha256']
                or entry['brokerSymbol'] != plan_member.get('symbol', entry['brokerSymbol'])
                or entry['deployFileName'] != plan_member.get('fileName', entry['deployFileName'])
                or entry['deployFileName'] != deploy_file_name(source['setName'], entry['brokerSymbol'])):
            raise ValueError('Broker-fit member %d does not match its plan member and manifest entry' % index)
    excluded_sets(block)
    return entries


def excluded_sets(block):
    """{memberId: reference SET bytes} of every manifest member the plan does NOT deploy (review 6132018108 item D):
    the deploy re-derives the fit set over the WHOLE manifest, so the plan carries the bytes of the members it leaves
    out, each hash-bound to its manifest entry. Together with the plan members they name every manifest member exactly
    once; anything else is refused."""
    import base64
    items, by_id = block['excludedSets'], {member['memberId']: member for member in block['manifest']['members']}
    deployed = {entry['memberId'] for entry in block['members']}
    if type(items) is not list:
        raise ValueError('Invalid broker-fit excludedSets in the demo deploy plan')
    out = {}
    for item in items:
        if type(item) is not dict or set(item) != EXCLUDED_SET_KEYS or not isinstance(item['contentBase64'], str):
            raise ValueError('Invalid broker-fit excludedSets in the demo deploy plan')
        source = by_id.get(item['memberId'])
        if source is None or item['memberId'] in deployed or item['memberId'] in out:
            raise ValueError('The broker-fit block must name every manifest member exactly once')
        try:
            raw = base64.b64decode(item['contentBase64'], validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid broker-fit excludedSets in the demo deploy plan') from exc
        if len(raw) != source['setBytes'] or sha256(raw) != source['setSha256']:
            raise ValueError('An excluded member SET differs from its manifest entry: ' + item['memberId'])
        out[item['memberId']] = raw
    if set(out) | deployed != set(by_id):
        raise ValueError('The broker-fit block must name every manifest member exactly once')
    return out


def deployed_bytes(reference_raw, entry):
    """The scaled SET the deploy writes: the reference bytes with the reviewed edits, hash-checked on both sides."""
    if sha256(reference_raw) != entry['setSha256Reference']:
        raise ValueError('The member SET is not the broker-fit reference SET')
    raw = rewrite_set(reference_raw, entry['edits'])
    if sha256(raw) != entry['setSha256Deployed']:
        raise ValueError('The scaled SET differs from the reviewed broker-fit result')
    return raw


def deploy_identity_preimage(scale, deployed):
    """The house deploy identity pre-image shared with the app (goatai#2500 houseDeployIdentity, vendored test vectors
    controller/contracts/deploy-identity/deploy-identity-cases.json): 'goat-house-deploy-identity-v1|scale=<S>|' + the
    setSha256Deployed values (duplicates kept) sorted ascending and joined with ','. S = the scale with exactly 10
    decimals, then trailing zeros and a trailing point removed. No trailing newline."""
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('The deploy identity needs a finite positive scale')
    deployed = list(deployed)
    if not deployed or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in deployed):
        raise ValueError('The deploy identity needs at least one lower-case SHA-256')
    text = format(scale, '.10f').rstrip('0').rstrip('.')
    return DEPLOY_IDENTITY_PREFIX + '|scale=' + text + '|' + ','.join(sorted(deployed))


def deploy_identity(scale, deployed):
    """sha256 hex of the UTF-8 deploy identity pre-image (Rule 9: the deployment's identity covers its bytes)."""
    return sha256(deploy_identity_preimage(scale, deployed).encode('utf-8'))


def deploy_record(block):
    """What the deploy journal keeps: {schema, scale, deployIdentity, members: [{memberId, setSha256Reference,
    setSha256Deployed, scale}]}."""
    return dict(schema=block['schema'], scale=block['scale'],
                deployIdentity=deploy_identity(block['scale'], [e['setSha256Deployed'] for e in block['members']]),
                members=[dict(memberId=e['memberId'], setSha256Reference=e['setSha256Reference'],
                              setSha256Deployed=e['setSha256Deployed'], scale=block['scale']) for e in block['members']])


def stale_members(block, references, schema, *, account, symbols, ticks, quotes, margins, utc_now, arrived=()):
    """The deploy-time re-check (review 6130418265 items 2, 3, 4 and 7). Nothing in the plan is an input except the
    manifest, the reference SET bytes (hash-bound to it) and the planning equity; every other plan value is a claim
    compared with what GOAT derives from them and the LIVE broker read now. Returns [dict(memberId, input, reviewed,
    live)]; empty = fresh. Stale when:
    - the plan is older than PLAN_TTL_SECONDS (input 'reviewedAtUtc'), or the account currency changed / no equity;
    - re-derived at the planning equity on the live broker (live rate, live symbol facts, live clock), a member is not
      fit or any claim differs: brokerSymbol, deployFileName, setSha256Reference, rules, edits, setSha256Deployed, or
      the block's referenceIdentical (so a forged rate, contract ratio, volume step, start lot, startingBalance or
      edit never deploys);
    - re-derived at the LIVE equity, a member is no longer fit (min lot, money limits, margin <= 50%...) or a deployed
      Risk / Lots_Input is ABOVE the live value (rounding up) or, outside the reference-identical band, more than one
      cent / volume step BELOW it; or the portfolio is no longer offered at the live equity.
    A reference-identical plan (block referenceIdentical) instead keeps its exemption only while every condition holds
    on the live account ('referenceIdentical.<condition>' rows); its exempt members deploy the reference bytes inside
    the one-sided band by design, the rest get the per-value check one-sided, and every member's fixed money limits
    are judged on the live equity."""
    rows = []

    def add(member_id, name, reviewed, live):
        rows.append(dict(memberId=member_id, input=name, reviewed=reviewed, live=live))

    age = utc_now - block['reviewedAtUtc']
    if age > PLAN_TTL_SECONDS or age < -FRESH_QUOTE_SECONDS:
        add(None, 'reviewedAtUtc', block['reviewedAtUtc'], int(utc_now))
        return rows
    live_equity = dec(account.get('equity'))
    if account.get('currency') != block['accountCurrency'] or live_equity is None or live_equity <= 0:
        add(None, 'account', block['accountCurrency'], account.get('currency'))
        return rows
    # The WHOLE manifest is re-derived (review 6132018108 item D): the plan's members plus the ones it leaves out.
    manifest = block['manifest']
    sets = {sha256(raw): raw for raw in list(references) + list(excluded_sets(block).values())}
    reading = dict(account=account, symbols=symbols, ticks=ticks, quotes=quotes, margins=margins, schema=schema, utc_now=utc_now,
                   arrived=arrived)
    reviewed = build_result(manifest, sets, equity=_exact(block['equity']), **reading)
    live = build_result(manifest, sets, equity=None, **reading)
    basis = reviewed['deployBasis']
    if basis is None:
        add(None, 'rate', block['rate'], None)
        return rows
    if _exact(block['referenceEquity']) != dec(manifest['referenceAccount']['startingBalance']):
        add(None, 'referenceEquity', block['referenceEquity'], basis['referenceEquity'])
    # The scale is only a claim (the journal's deploy identity carries it). In one currency it is exact, so it must be
    # the re-derived one; across currencies it moves with every price and the bytes carry its consequence.
    if block['accountCurrency'] == manifest['referenceAccount']['currency'] and block['scale'] != reviewed['scale']:
        add(None, 'scale', block['scale'], reviewed['scale'])
    identical = block['referenceIdentical']
    if identical is not None:
        failing = [name for name, holds in reviewed['referenceIdentical']['conditions'].items() if not holds]
        observed = dict(sameServer=account.get('server'), sameCurrency=account.get('currency'), sameLeverage=account.get('leverage'),
                        equityWithinTolerance=num(live_equity), scaleOne=reviewed['scale'], bytesUnchanged=None)
        for name in failing:
            add(None, 'referenceIdentical.' + name, True, observed[name])
        if failing:
            return rows
    if identical != basis['referenceIdentical']:
        add(None, 'referenceIdentical', identical, basis['referenceIdentical'])
    # The plan deploys exactly the members the review marks fit: a subset (1 of 35 passing the 90% rule at 100%) or
    # a superset is stale.
    planned = sorted(entry['memberId'] for entry in block['members'])
    fit_now = sorted(row['memberId'] for row in reviewed['members'] if row['status'] == 'fit')
    if planned != fit_now:
        add(None, 'members', planned, fit_now)
    reviewed_rows = {row['memberId']: row for row in reviewed['members']}
    live_rows = {row['memberId']: row for row in live['members']}
    defaults = schema_defaults(schema)
    for entry, raw in zip(block['members'], references):
        member_id = entry['memberId']
        rev_row, live_row = reviewed_rows[member_id], live_rows[member_id]
        if rev_row['status'] != 'fit':
            add(member_id, rev_row['code'], None, None)
            continue
        claimed = rev_row['deploy']
        for name in ('brokerSymbol', 'deployFileName', 'setSha256Reference', 'rules'):
            if entry[name] != claimed[name]:
                add(member_id, name, entry[name], claimed[name])
        for name in sorted(set(entry['edits']) | set(claimed['edits'])):
            if entry['edits'].get(name) != claimed['edits'].get(name):
                add(member_id, name, entry['edits'].get(name), claimed['edits'].get(name))
        if entry['setSha256Deployed'] != claimed['setSha256Deployed']:
            add(member_id, 'setSha256Deployed', entry['setSha256Deployed'], claimed['setSha256Deployed'])
        exempt = rev_row['marginReason'] == REFERENCE_IDENTICAL_MARGIN
        if exempt:
            # Fixed money limits are judged on the live equity too (review item 4).
            values = set_values(raw, schema)
            fixed = fixed_money_off_reference(values, defaults, live_equity, dec(manifest['referenceAccount']['startingBalance']))
            if fixed:
                add(member_id, fixed, num(_number(values, defaults, fixed)), num(live_equity))
            continue
        if live_row['status'] != 'fit':
            add(member_id, live_row['code'], None, None)
            continue
        for name, tolerance in (('Risk', CENT), ('Lots_Input', dec(live_row['deploy']['rules']['volumeStep']))):
            then, now = dec(rev_row['scaled'][name]), dec(live_row['scaled'][name])
            if then is None or now is None:
                continue
            if then > now or (identical is None and now - then > tolerance):
                add(member_id, name, num(then), num(now))
    gate = reviewed if identical is not None else live
    if not gate['offered']:
        add(None, gate['refusal']['code'], None, gate['refusal']['message'])
    return rows


def check_live(controller, session, plan, *, mt5=None, process=None, clock=None, sleep=None):
    """Refuse FIT_STALE before anything is staged when the live broker no longer gives the reviewed fit: one short
    attach-only read (read_broker) of the manifest's members, then stale_members."""
    import base64
    block = plan['brokerFit']
    references = [base64.b64decode(member['contentBase64'], validate=True) for member in plan['members']]
    manifest = block['manifest']
    account, symbols, ticks, quotes, margins, utc_now, arrived = read_broker(controller, session, manifest, mt5=mt5, process=process,
                                                                             clock=clock, sleep=sleep)
    stale = stale_members(block, references, controller.schema, account=account, symbols=symbols, ticks=ticks, quotes=quotes,
                          margins=margins, utc_now=utc_now, arrived=arrived)
    if stale:
        raise Refusal(FIT_STALE_MESSAGE + ' Nothing was written or launched.', FIT_STALE, stale=stale[:20],
                      liveEquity=account.get('equity'), liveCurrency=account.get('currency'))


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


def _tick_stamp(tick):
    """(time_msc, time) of an SDK tick; None when there is no tick."""
    if tick is None or not getattr(tick, 'time', 0):
        return None
    msc = getattr(tick, 'time_msc', None)
    return (int(msc) if isinstance(msc, (int, float)) and not isinstance(msc, bool) else int(tick.time) * 1000), int(tick.time)


def read_broker(controller, session, manifest, *, mt5=None, clock=None, process=None, sleep=None, server_time_utc=None):
    """One short read-only MT5 SDK session (seconds) under the terminal lease, ATTACH-ONLY: it refuses MT5_NOT_RUNNING
    and never calls initialize() (which starts a closed MT5 and leaves it running) unless the selected terminal64.exe
    is already running. Reads the account, every symbol, the last tick of each mapped symbol and of each conversion
    pair, its tick history of the last SPREAD_HISTORY_HOURS (copy_ticks_range, COPY_TICKS_INFO), and the SDK's margin
    per lot. The broker clock comes only from a tick seen ARRIVING (at most ARRIVAL_WINDOW_SECONDS of re-reading the
    last ticks; a closed market leaves it unknown). Never trades, never selects a symbol into Market Watch, never opens
    a chart. Returns (account, symbols, ticks, quotes, margins, utc_now, arrived).

    server_time_utc (optional, unix seconds): a trusted time the caller read just before (the app passes its serveApi
    HTTP Date). The broker offset is measured against this PC's clock, so when the two differ by more than
    FRESH_QUOTE_SECONDS the clock is not trusted: no tick counts as arrived and the offset is unknown."""
    import time
    from pathlib import Path
    import studio_seed_process
    from studio_terminal_lease import BUSY_READ, terminal_lease
    clock = clock or time.time
    sleep = sleep or time.sleep
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise ValueError('The MetaTrader5 adapter is unavailable; nothing was read') from exc
    process = process or studio_seed_process.WindowsSeedProcess(controller)
    with terminal_lease(controller.root, purpose='broker-fit', busy_code='BROKER_READ_DEFERRED', busy_message=BUSY_READ,
                        broker_reason='terminal_busy'):
        # Attach only: the exact selected terminal64.exe must already be running (accepted with review 6130418265).
        before = process.inspect()
        if before is None:
            raise Refusal(MT5_NOT_RUNNING_MESSAGE, MT5_NOT_RUNNING)
        attached = mt5.initialize(controller.install['terminal_executable'], timeout=5000)
        # Close the race (review 6131884216 item C): if MT5 exited between the check and initialize(), initialize()
        # started a new one. Re-scan the exact executable: anything but the same process (pid and creation time) is a
        # terminal GOAT started, so the link is dropped and the check refuses instead of reading it.
        after = process.inspect()
        if not after or after.get('pid') != before.get('pid') or after.get('created_utc') != before.get('created_utc'):
            mt5.shutdown()
            raise Refusal(MT5_STARTED_BY_CHECK_MESSAGE, MT5_STARTED_BY_CHECK, pidBefore=before.get('pid'),
                          pidAfter=(after or {}).get('pid'))
        if not attached:
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
            reference_currency = manifest['referenceAccount']['currency']
            pairs = sorted({item['name'] for item in symbols if account['currency'] != reference_currency
                            and is_conversion_pair(item, account['currency'], reference_currency)} - set(mapped))
            first = {name: _tick_stamp(mt5.symbol_info_tick(name)) for name in mapped + pairs}
            quotes = {name: stamp[1] if stamp else None for name, stamp in first.items()}
            # Re-read the mapped symbols' last ticks until one ARRIVES: its age is then at most the time since the
            # first read, so it proves the server clock (review 6130418265 item 8). Bounded; no arrival = unknown.
            started, arrived = clock(), []
            skewed = server_time_utc is not None and abs(started - server_time_utc) > FRESH_QUOTE_SECONDS
            while True:
                for name in mapped:
                    stamp = _tick_stamp(mt5.symbol_info_tick(name))
                    if stamp and first[name] and stamp[0] > first[name][0]:
                        arrived.append(name)
                        quotes[name] = stamp[1]
                utc_now = clock()
                if arrived or skewed or not mapped or utc_now - started >= ARRIVAL_WINDOW_SECONDS:
                    break
                sleep(ARRIVAL_POLL_SECONDS)
            if skewed:
                arrived = []                     # this PC's clock is off: no tick can prove the broker's offset
            offset = measured_server_offset_minutes([quotes[name] for name in arrived], utc_now)
            ticks = {}
            if offset is not None:
                # Tick times and copy_ticks_range dates are the server clock (as Ops' exp03_symbol_specs.py passes them).
                server_now = datetime.fromtimestamp(utc_now + offset * 60, timezone.utc)
                start = server_now - timedelta(hours=SPREAD_HISTORY_HOURS)
                for symbol in mapped:
                    ticks[symbol] = mt5.copy_ticks_range(symbol, start, server_now, getattr(mt5, 'COPY_TICKS_INFO', 1))
            # Fresh facts (and bid/ask) of the mapped symbols AND the conversion pairs (review 6130418265 item 3); the
            # pairs' quote ages are judged in build_result with the proven clock.
            fresh = {item['name']: item for item in (_symbol_dict(mt5.symbol_info(name)) for name in mapped + pairs) if item['name']}
            for name in pairs:
                stamp = _tick_stamp(mt5.symbol_info_tick(name))
                quotes[name] = stamp[1] if stamp else None
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
    return account, symbols, ticks, quotes, margins, utc_now, arrived


def broker_fit(controller, portfolio, *, equity=None, sets_dir=None, mt5=None, clock=None, process=None, sleep=None,
               server_time_utc=None):
    """`studio broker-fit`: read-only; refuses NOT_DEMO_ACCOUNT on a non-demo account."""
    from studio_onboarding import session_state
    if equity is not None and (not math.isfinite(equity) or equity <= 0):
        raise ValueError('--equity must be a positive number')
    if server_time_utc is not None and (not math.isfinite(server_time_utc) or server_time_utc <= 0):
        raise ValueError('--server-time-utc must be unix seconds')
    manifest, sets = load_portfolio(portfolio, sets_dir)
    installed = controller.install.get('ea_version')
    wanted = (manifest.get('ea') or {}).get('eaVersion')
    if wanted and installed and wanted != installed:
        raise Refusal('This portfolio is built for GOAT EA V' + str(wanted) + '; this terminal runs V' + str(installed) + '.',
                      'EA_VERSION_MISMATCH')
    session, _ = session_state(controller)
    account, symbols, ticks, quotes, margins, utc_now, arrived = read_broker(controller, session, manifest, mt5=mt5, clock=clock,
                                                                             process=process, sleep=sleep,
                                                                             server_time_utc=server_time_utc)
    return build_result(manifest, sets, account=account, symbols=symbols, ticks=ticks, quotes=quotes, margins=margins,
                        schema=controller.schema, utc_now=utc_now, equity=equity, arrived=arrived)
