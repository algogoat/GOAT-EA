"""New-weeks-only verdict for one OOS catch-up re-test (goat-catchup-verdict-v2).

The re-test is one non-optimized pass of the frozen exported values from the
original start to the new evidence end. Only the days after the original export's
evidence end are judged: they are unseen by the optimizer and by the original
export. Everything before them is the baseline (same run, same definitions) and
must reproduce the original export, or nothing is judged.

Comparability (``comparability``): the re-test is judged only when it ran the same
trading inputs, the same EA build (capture build id, else the run's EA binary hash
against the installed one), the same tester model (real ticks), symbol, broker
server, deposit, currency and leverage, and reproduced the original's equity and
deals before the new weeks. The execution delay is pinned in the tester INI and
checked through that reproduction. Symbol specification (contract size, digits) is
not captured by this EA build; a change would alter the pre-window trades and fail
the reproduction check. Any failed check makes the verdict ``not_comparable``.

Definitions (broker server time, half-open windows [start 00:00, end+1 00:00)):
- net: equity change over the window from the export equity CSV (includes the
  floating result of positions open at either boundary); realized: balance change.
- trades: positions opened in the window (entry deals), the same count the EA
  writes as "Trades" in its window header lines. From the capture's deals.csv when
  the capture completed, else the difference of the FOOS header trade counts.
- pf: winning / losing deal results (profit + swap + commission + fee) of the
  positions opened in the window; only with a complete capture. Closes of positions
  opened earlier count in net, not in pf.
- dd: the deepest fall of the sampled equity inside the window below the running
  peak, which includes every equity row before the window, so a drawdown already
  under way is carried in. prior_dd is the worst such fall before the window.
  Equity is sampled at one-minute events; intrabar extremes can be deeper.
- pace: the original forward window [ForwardDate, ToDate) measured in the re-test.

Verdict rules, in order:
1. not_comparable: any comparability check failed.
2. failed: the new weeks went below the worst drawdown already shown (dd >
   prior_dd), or, with at least min_trades trades, lost money with pf < failed_pf
   (no pf: lost more than one forward-pace window of profit).
3. too_few_trades: fewer than min_trades trades; too few to judge either way.
4. held_up: net > 0, a known pf >= 1, and at least held_pace of the forward profit
   pace and min_pace_trades of the forward trade pace (when that pace is known).
5. weakened: everything else (pf unknown, profitable but slow, few trades for its
   pace, or a small loss).

The numbers are defaults a plan may override within bounds (``validate_rules``).
Every verdict stamps the rules it used and the raw ``signals`` it was decided from;
the evidence version adds the export thresholds and margins, so a later scored,
explained qualification can re-judge without re-running MT5. Confidence is never
above moderate. No score is computed here.
"""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from strategy_registry import inspect_set
from studio_evidence import server_msc, weekdays

RULES = 'goat-catchup-verdict-v2'
MIN_TRADES = 5
FAILED_PF = 0.8
HELD_PACE = 0.5
MIN_PACE_TRADES = 0.3
MODERATE_TRADES = 20
MODERATE_DAYS = 10
DEFAULT_RULES = dict(id=RULES, min_trades=MIN_TRADES, failed_pf=FAILED_PF, held_pace=HELD_PACE, min_pace_trades=MIN_PACE_TRADES,
                     moderate_trades=MODERATE_TRADES, moderate_days=MODERATE_DAYS, overridden=[])
# Bounds keep an override meaningful: (type, low, high).
RULE_BOUNDS = dict(min_trades=(int, 1, 1000), failed_pf=(float, 0.0, 2.0), held_pace=(float, 0.0, 2.0),
                   min_pace_trades=(float, 0.0, 1.0), moderate_trades=(int, 1, 100000), moderate_days=(int, 1, 1000))
MAX_EQUITY_CSV = 64 * 1024 * 1024
MAX_DEALS_CSV = 256 * 1024 * 1024
TOLERANCE = Decimal('0.005')
CAVEAT = ('The new weeks are unseen data, but a few weeks is a small sample: treat held_up as "no warning sign yet", '
          'not as proof of an edge.')
SYMBOL_SPEC = ('Symbol specification (contract size, digits) is not captured by this EA build; a change would alter '
               'the trades before the new weeks and fail the reproduction check.')


def validate_rules(overrides=None):
    """Defaults merged with bounded overrides; the result is stamped on every verdict."""
    if overrides is None:
        return dict(DEFAULT_RULES)
    if not isinstance(overrides, dict) or set(overrides) - set(RULE_BOUNDS):
        raise ValueError('verdict_rules may set only: ' + ', '.join(sorted(RULE_BOUNDS)))
    rules = dict(DEFAULT_RULES, overridden=sorted(overrides))
    for key, value in overrides.items():
        kind, low, high = RULE_BOUNDS[key]
        if type(value) is bool or (kind is int and type(value) is not int) or (kind is float and type(value) not in (int, float)) \
                or not low <= value <= high:
            raise ValueError('verdict_rules.%s must be %s %g..%g' % (key, 'a whole number' if kind is int else 'a number', low, high))
        rules[key] = kind(value)
    return rules


def equity_rows(csv_path):
    """(minute, balance, equity) rows of an exported equity CSV, in file order."""
    path = Path(csv_path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_EQUITY_CSV + 1)
    if len(raw) > MAX_EQUITY_CSV:
        raise ValueError('Equity CSV exceeds 64 MiB')
    lines = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig').splitlines()
    if not lines or lines[0] != '<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>':
        raise ValueError('Unexpected equity CSV header: ' + path.name)
    rows, previous = [], None
    for index, line in enumerate(lines[1:], 2):
        parts = line.split('\t')
        if len(parts) != 4 or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}', parts[0]):
            raise ValueError('Invalid equity row %d in %s' % (index, path.name))
        stamp = datetime.strptime(parts[0], '%Y.%m.%d %H:%M')
        if previous is not None and stamp < previous:
            raise ValueError('Equity timestamps go backwards at row %d in %s' % (index, path.name))
        try:
            balance, equity = Decimal(parts[1]), Decimal(parts[2])
        except InvalidOperation as exc:
            raise ValueError('Invalid equity number at row %d in %s' % (index, path.name)) from exc
        if not balance.is_finite() or not equity.is_finite():
            raise ValueError('Nonfinite equity at row %d in %s' % (index, path.name))
        rows.append((stamp, balance, equity))
        previous = stamp
    if not rows:
        raise ValueError('Equity CSV has no rows: ' + path.name)
    return rows


def _midnight(day):
    return datetime.combine(day, datetime.min.time())


def equity_window(rows, first_day, last_day, *, opening=None, carry_peak=False):
    """Net/realized/dd over [first_day, last_day] (inclusive dates) from equity rows.

    With ``carry_peak`` the drawdown is measured from the running peak of every row
    before the window too (a drawdown already under way counts); ``dd_from_open``
    is always measured from the window's opening equity.
    """
    start, end = _midnight(first_day), _midnight(last_day + timedelta(days=1))
    before = [row for row in rows if row[0] < start]
    inside = [row for row in rows if start <= row[0] < end]
    if before:
        open_balance, open_equity = before[-1][1], before[-1][2]
    elif opening is not None:
        open_balance = open_equity = Decimal(str(opening))
    else:
        open_balance, open_equity = rows[0][1], rows[0][2]
    close_balance, close_equity = (inside[-1][1], inside[-1][2]) if inside else (open_balance, open_equity)
    peak = max([open_equity] + ([row[2] for row in before] if carry_peak else []))
    open_peak, dd, dd_open = open_equity, Decimal(0), Decimal(0)
    for _, _, equity in inside:
        peak, open_peak = max(peak, equity), max(open_peak, equity)
        dd, dd_open = max(dd, peak - equity), max(dd_open, open_peak - equity)
    return dict(first_day=first_day.isoformat(), last_day=last_day.isoformat(), weekdays=weekdays(first_day, last_day),
                samples=len(inside), open_equity=float(open_equity), close_equity=float(close_equity),
                net=float(close_equity - open_equity), realized=float(close_balance - open_balance), dd=float(dd),
                dd_from_open=float(dd_open), dd_basis='running_peak_incl_prior' if carry_peak else 'window_open',
                dd_pct=float(dd / peak * 100) if peak > 0 else None)


def prior_drawdown(rows, before_day):
    """Worst sampled drawdown over every row before ``before_day`` 00:00."""
    cut = _midnight(before_day)
    peak, dd = None, Decimal(0)
    for stamp, _, equity in rows:
        if stamp >= cut:
            break
        peak = equity if peak is None else max(peak, equity)
        dd = max(dd, peak - equity)
    return float(dd)


def deal_window(deals_csv, first_day, last_day):
    """Entries/closes in [first_day, last_day]; pf over the positions opened in it."""
    lo, hi = server_msc(first_day), server_msc(last_day + timedelta(days=1))
    path = Path(deals_csv)
    if path.stat().st_size > MAX_DEALS_CSV:
        raise ValueError('deals.csv exceeds its byte bound')
    inside = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if lo <= int(row['server_time_msc']) < hi:
                inside.append(row)
    opened = {row['position_id'] for row in inside if row['deal_entry'] == '0'}
    entries = sum(row['deal_entry'] == '0' for row in inside)
    closes = sum(row['deal_entry'] in ('1', '2', '3') for row in inside)
    carried = sum(row['deal_entry'] in ('1', '2', '3') and row['position_id'] not in opened for row in inside)
    wins, losses = Decimal(0), Decimal(0)
    for row in inside:
        if row['position_id'] not in opened:
            continue
        result = sum(Decimal(row[key]) for key in ('profit', 'commission', 'fee', 'swap'))
        if result > 0:
            wins += result
        else:
            losses -= result
    pf = float(wins / losses) if losses > 0 else None
    return dict(entries=entries, closes=closes, closes_of_earlier_positions=carried, gross_win=float(wins), gross_loss=float(losses),
                pf=pf, pf_note=None if losses > 0 else ('no losing deals' if wins > 0 else 'no deal results'))


def _deal_signature(deals_csv, cut_msc):
    rows = []
    with Path(deals_csv).open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if int(row['server_time_msc']) < cut_msc:
                rows.append((row['server_time_msc'], row['deal_type'], row['deal_entry'], row['lots'], row['price'],
                             str(Decimal(row['profit']).quantize(Decimal('0.01')))))
    return rows


def reproduction(original_rows, retest_rows, *, original_deals=None, retest_deals=None):
    """Does the re-test repeat the original export up to the original's end?

    The original test force-closed open positions at its final tick, so the last
    minute of the original is excluded; everything before it must match.
    """
    cut = original_rows[-1][0]
    old = [row for row in original_rows if row[0] < cut]
    new = [row for row in retest_rows if row[0] < cut]
    result = dict(compared_until=cut.strftime('%Y-%m-%d %H:%M'), equity_rows_compared=len(old), reproduced=True, first_difference=None)
    for index, (a, b) in enumerate(zip(old, new)):
        if a[0] != b[0] or abs(a[1] - b[1]) > TOLERANCE or abs(a[2] - b[2]) > TOLERANCE:
            result.update(reproduced=False, first_difference=dict(row=index + 2, original=[a[0].strftime('%Y.%m.%d %H:%M'), str(a[1]), str(a[2])],
                                                                    retest=[b[0].strftime('%Y.%m.%d %H:%M'), str(b[1]), str(b[2])]))
            return result
    if len(old) != len(new):
        result.update(reproduced=False, first_difference=dict(original_rows=len(old), retest_rows=len(new)))
        return result
    if original_deals and retest_deals:
        cut_msc = int(cut.replace(tzinfo=timezone.utc).timestamp() * 1000)
        a, b = _deal_signature(original_deals, cut_msc), _deal_signature(retest_deals, cut_msc)
        result['deals_compared'] = len(a)
        if a != b:
            index = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            result.update(reproduced=False, first_difference=dict(deal=index, original=a[index] if index < len(a) else None,
                                                                  retest=b[index] if index < len(b) else None))
    return result


def inputs_match(original_set, retest_set):
    """Same trading inputs (every value except EA_Desc and comments)?"""
    a, b = inspect_set(Path(original_set).read_bytes()), inspect_set(Path(retest_set).read_bytes())
    return a['canonical_sha256'] == b['canonical_sha256']


def comparability(original, retest, *, pins=None, repro, same_inputs):
    """Every check the re-test must pass before its new weeks are judged (see module docstring).

    ``pins`` are the frozen member's tester settings and EA identities; they stand in for
    the re-test's values when its capture was off, and for the original's when the run
    manifest supplied them. An unknown original value fails its check.
    """
    pins = pins or {}
    oc, rc = original.get('capture') or {}, retest.get('capture') or {}
    tester = pins.get('original_tester') or {}
    checks = []

    def check(name, ok, detail):
        checks.append(dict(check=name, ok=bool(ok), detail=detail))

    def pair(name, original_value, retest_value):
        if original_value is None or retest_value is None:
            check(name, False, 'unknown (%s / %s)' % (original_value, retest_value))
        else:
            check(name, str(original_value) == str(retest_value), '%s / %s' % (original_value, retest_value))

    check('inputs', same_inputs, 'every SET value except EA_Desc')
    if oc.get('build_id') or rc.get('build_id'):
        pair('ea_build', oc.get('build_id'), rc.get('build_id'))
    elif pins.get('original_ea_sha256') and pins.get('installed_ea_sha256'):
        check('ea_build', pins['original_ea_sha256'] == pins['installed_ea_sha256'], 'EA binary: run manifest / installed')
    else:
        check('ea_build', False, 'the EA build of the original or the re-test is unknown')
    pair('ea_name', original.get('ea_name'), retest.get('ea_name'))
    # The EA's export pass always forces real ticks (Model 4), so an original without a capture is Model 4.
    pair('model', oc.get('model') if oc else 4, rc.get('model') if rc else pins.get('model'))
    pair('symbol', oc.get('asset') or original.get('symbol'), rc.get('asset') or retest.get('symbol'))
    pair('server', oc.get('server') or pins.get('original_server'), rc.get('server') or pins.get('server'))
    number = lambda value: None if value is None else float(value)
    pair('deposit', number(oc.get('initial_equity') if oc.get('initial_equity') is not None else tester.get('Deposit')),
         number(rc.get('initial_equity') if rc.get('initial_equity') is not None else pins.get('deposit')))
    leverage = ('1:%d' % oc['leverage']) if type(oc.get('leverage')) is int else tester.get('Leverage')
    pair('leverage', leverage, ('1:%d' % rc['leverage']) if type(rc.get('leverage')) is int else pins.get('leverage'))
    pair('currency', oc.get('currency') or tester.get('Currency'), rc.get('currency') or pins.get('currency'))
    check('execution_delay', True, 'pinned at %s in the tester INI%s; verified by the reproduction check'
          % (pins.get('execution_mode', 'the original value'), ' (assumed)' if 'ExecutionMode' in pins.get('assumed', []) else ''))
    check('reproduced', repro.get('reproduced'), 'equity rows and deals before the new weeks'
          + ('' if repro.get('reproduced') else ': first difference %s' % repro.get('first_difference')))
    return dict(comparable=all(item['ok'] for item in checks), checks=checks, symbol_spec=SYMBOL_SPEC)


def _pf_known(new):
    return new.get('pf') is not None or new.get('pf_note') == 'no losing deals'


def decide(new, prior_dd, pace, rules=None):
    """Apply the verdict rules to measured numbers (comparability already passed). Pure."""
    rules = rules or DEFAULT_RULES
    min_trades, failed_pf, held_pace = rules['min_trades'], rules['failed_pf'], rules['held_pace']
    min_pace_trades = rules.get('min_pace_trades', MIN_PACE_TRADES)
    trades, net, dd, pf = new['trades'], new['net'], new['dd'], new.get('pf')
    days = max(new['weekdays'], 1)
    forward_per_day = pace.get('net_per_day') if pace else None
    expected = new.get('expected_trades_at_forward_pace')
    reasons = []
    if dd > prior_dd:
        reasons.append('went below the worst drawdown already shown (%.0f from the peak vs %.0f before)' % (dd, prior_dd))
        return 'failed', reasons
    if trades is not None and trades >= min_trades and net < 0:
        if pf is not None and pf < failed_pf:
            reasons.append('lost %.0f with profit factor %.2f' % (-net, pf))
            return 'failed', reasons
        if pf is None and forward_per_day is not None and -net > abs(forward_per_day) * days:
            reasons.append('lost %.0f, more than a forward-pace window of profit' % -net)
            return 'failed', reasons
    if trades is None or trades < min_trades:
        reasons.append('%s trades in the new weeks; too few to judge' % ('unknown' if trades is None else trades))
        return 'too_few_trades', reasons
    if net <= 0:
        reasons.append('lost %.0f' % -net if net < 0 else 'flat')
        return 'weakened', reasons
    if not _pf_known(new):
        reasons.append('profitable, but the profit factor is unknown (needs a complete capture)')
        return 'weakened', reasons
    if pf is not None and pf < 1.0:
        reasons.append('profit factor %.2f below 1' % pf)
        return 'weakened', reasons
    if forward_per_day is not None and forward_per_day > 0 and net / days < held_pace * forward_per_day:
        reasons.append('profitable but at %.0f%% of the forward profit pace' % (100 * net / days / forward_per_day))
        return 'weakened', reasons
    if expected and trades < min_pace_trades * expected:
        reasons.append('%d trades, under %.0f%% of the ~%g expected at the forward pace' % (trades, 100 * min_pace_trades, expected))
        return 'weakened', reasons
    reasons.append('profitable, drawdown within what it had already shown')
    return 'held_up', reasons


def signals(new, prior_dd, pace, repro, same_inputs, capture):
    """Raw numbers the verdict was decided from, for a later scored qualification.

    Ratios are null when their base is missing or not positive, never guessed.
    """
    days = new['weekdays'] or 0
    per_day = new['net'] / days if days else None
    forward = pace.get('net_per_day') if pace else None
    expected = new.get('expected_trades_at_forward_pace')
    ratio = lambda value, base: round(value / base, 4) if value is not None and base not in (None, 0) and base > 0 else None
    return dict(schema='goat-catchup-signals-v2', weekdays=days, trades=new['trades'], expected_trades=expected,
                trades_vs_pace=ratio(new['trades'], expected), net=new['net'], net_per_day=per_day,
                forward_net_per_day=forward, pace_ratio=ratio(per_day, forward), pf=new.get('pf'), pf_note=new.get('pf_note'),
                dd=new['dd'], dd_from_open=new.get('dd_from_open'), dd_pct=new.get('dd_pct'), prior_dd=prior_dd,
                dd_vs_prior=ratio(new['dd'], prior_dd), reproduced=repro.get('reproduced'), inputs_match=same_inputs,
                capture_complete=bool((capture or {}).get('complete')), trade_source=new.get('trade_source'))


def _plain(verdict, new, pace, reasons, confidence, comparable):
    span = '%s to %s (%d trading days)' % (new['first_day'], new['last_day'], new['weekdays'])
    text = {'held_up': 'Held up', 'weakened': 'Weakened', 'failed': 'Failed', 'too_few_trades': 'Too few trades to judge',
            'not_comparable': 'Not comparable'}[verdict]
    if not comparable:
        return '%s: the re-test over %s is not the same test as the original (%s), so its new weeks are not judged.' % (
            text, span, '; '.join(reasons))
    numbers = '%+.0f, %s trades, DD %.0f' % (new['net'], '?' if new['trades'] is None else new['trades'], new['dd'])
    numbers += ', PF %.2f' % new['pf'] if new.get('pf') is not None else ', PF unknown' if new.get('pf_note') != 'no losing deals' else ', no losing trades'
    sentence = '%s over the new weeks %s: %s' % (text, span, numbers)
    if pace and pace.get('net_per_day') is not None:
        sentence += '; forward pace was %+.1f/day, new weeks %+.1f/day' % (pace['net_per_day'], new['net'] / max(new['weekdays'], 1))
    sentence += '. ' + '; '.join(reasons).capitalize()
    if verdict == 'too_few_trades' and new.get('expected_trades_at_forward_pace') is not None:
        sentence += ' (about %g expected at the forward pace)' % new['expected_trades_at_forward_pace']
    sentence += '. %s confidence: %s trades over %d trading days.' % (
        confidence.capitalize(), '?' if new['trades'] is None else new['trades'], new['weekdays'])
    return sentence


def evaluate(original, retest, *, new_end, tester=None, rules=None, pins=None):
    """Verdict for one catch-up member.

    ``original``: the original export's evidence record (studio_evidence.read_export).
    ``retest``: the re-test unit's evidence record. ``tester``: original optimization
    window (FromDate/ToDate/ForwardDate) when the run manifest supplied it. ``rules``:
    the frozen plan's ``validate_rules`` result. ``pins``: the frozen member's tester
    settings and EA identities (studio_catchup), used by ``comparability``.
    """
    rules = rules or validate_rules()
    original_end = date.fromisoformat(original['evidence_end'])
    new_end = date.fromisoformat(new_end) if isinstance(new_end, str) else new_end
    first_new = original_end + timedelta(days=1)
    if new_end < first_new:
        raise ValueError('Catch-up end is not after the original evidence end')
    same_inputs = inputs_match(original['set_path'], retest['set_path'])
    old_rows, new_rows = equity_rows(original['csv_path']), equity_rows(retest['csv_path'])
    old_capture, new_capture = original.get('capture') or {}, retest.get('capture') or {}
    old_deals = str(Path(old_capture['path']).parent / 'deals.csv') if old_capture.get('complete') else None
    new_deals = str(Path(new_capture['path']).parent / 'deals.csv') if new_capture.get('complete') else None
    if new_deals and not Path(new_deals).is_file():
        new_deals = None
    if old_deals and not Path(old_deals).is_file():
        old_deals = None
    repro = reproduction(old_rows, new_rows, original_deals=old_deals, retest_deals=new_deals)
    comparable = comparability(original, retest, pins=pins, repro=repro, same_inputs=same_inputs)
    opening = new_capture.get('initial_equity')
    window = equity_window(new_rows, first_new, new_end, opening=opening, carry_peak=True)
    covered = bool(new_capture.get('complete')) and new_capture.get('observed_end_msc', 0) >= server_msc(new_end) and new_deals
    if covered:
        deals = deal_window(new_deals, first_new, new_end)
        window.update(trades=deals['entries'], closes=deals['closes'], closes_of_earlier_positions=deals['closes_of_earlier_positions'],
                      pf=deals['pf'], pf_note=deals['pf_note'], trade_source='capture_deals')
    else:
        old_foos, new_foos = (original.get('windows') or {}).get('FOOS'), (retest.get('windows') or {}).get('FOOS')
        trades = new_foos['trades'] - old_foos['trades'] if old_foos and new_foos and repro['reproduced'] else None
        window.update(trades=trades if trades is None or trades >= 0 else None, closes=None, pf=None,
                      pf_note='needs a complete capture', trade_source='set_header_difference' if trades is not None else 'unavailable')
    prior = prior_drawdown(new_rows, first_new)
    pace = None
    forward = (tester or {}).get('ForwardDate'), (tester or {}).get('ToDate')
    if not all(forward) and (retest.get('windows') or {}).get('FWD'):
        fwd = retest['windows']['FWD']
        forward = fwd['start'].replace('-', '.'), fwd['end'].replace('-', '.')
    if all(forward):
        fwd_first = datetime.strptime(forward[0], '%Y.%m.%d').date()
        fwd_last = datetime.strptime(forward[1], '%Y.%m.%d').date() - timedelta(days=1)
        measured = equity_window(new_rows, fwd_first, fwd_last, opening=opening)
        days = max(measured['weekdays'], 1)
        fwd_trades = deal_window(new_deals, fwd_first, fwd_last)['entries'] if new_deals else ((retest.get('windows') or {}).get('FWD') or {}).get('trades')
        pace = dict(first_day=measured['first_day'], last_day=measured['last_day'], weekdays=measured['weekdays'],
                    net=measured['net'], trades=fwd_trades, dd=measured['dd'], net_per_day=measured['net'] / days,
                    trades_per_day=None if fwd_trades is None else fwd_trades / days)
        if window['weekdays'] and pace['trades_per_day'] is not None:
            window['expected_trades_at_forward_pace'] = round(pace['trades_per_day'] * window['weekdays'], 1)
    if not comparable['comparable']:
        verdict = 'not_comparable'
        reasons = ['%s: %s' % (item['check'], item['detail']) for item in comparable['checks'] if not item['ok']]
        confidence = 'none'
    else:
        verdict, reasons = decide(window, prior, pace, rules)
        confidence = 'low'
        if window['trades'] is not None and window['trades'] >= rules['moderate_trades'] and window['weekdays'] >= rules['moderate_days']:
            confidence = 'moderate'  # never higher: a few weeks is a small sample
    return dict(schema=RULES, verdict=verdict, confidence=confidence, reasons=reasons,
                plain=_plain(verdict, window, pace, reasons, confidence, comparable['comparable']),
                new_weeks=window, prior_dd=prior, forward_pace=pace, inputs_match=same_inputs, reproduction=repro,
                comparability=comparable,
                original=dict(set_path=original['set_path'], set_sha256=original['set_sha256'], evidence_end=original['evidence_end'],
                              values_sha256=original['values_sha256']),
                retest=dict(set_path=retest['set_path'], set_sha256=retest['set_sha256'], evidence_end=retest['evidence_end'],
                            capture_status=new_capture.get('status')),
                rules=rules, signals=signals(window, prior, pace, repro, same_inputs, new_capture), caveat=CAVEAT)
