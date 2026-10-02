"""New-weeks-only verdict for one OOS catch-up re-test (goat-catchup-verdict-v1).

The re-test is one non-optimized pass of the frozen exported values from the
original start to the new evidence end. Only the days after the original export's
evidence end are judged: they are genuinely unseen by the optimizer and by the
original export. Everything before them is used as the baseline (same run, same
definitions), and to check that the re-test reproduces the original export.

Definitions (broker server time, half-open windows [start 00:00, end+1 00:00)):
- net: equity change over the window from the export equity CSV (includes the
  floating result of positions open at either boundary); realized: balance change.
- trades: positions opened in the window (entry deals), the same count the EA
  writes as "Trades" in its BOOS/SAMPLE/FWD/FOOS header lines. From the capture's
  deals.csv when the capture completed, else the difference of the FOOS header
  trade counts (re-test minus original), which needs a reproduced re-test.
- pf: sum of winning deal results / sum of losing deal results (profit + swap +
  commission + fee per deal); only with a complete capture.
- dd: largest peak-to-trough fall of the sampled equity inside the window,
  starting from the window's opening equity. prior_dd is the same measure over
  everything before the window (the worst drawdown the export had already shown).
  Equity is sampled at one-minute events, so intrabar extremes can be deeper.
- pace: the original forward window [ForwardDate, ToDate) measured the same way
  in the re-test, per Mon-Fri day.

Verdict rules, in order:
1. not_comparable: the re-test did not run the same inputs.
2. failed: the new weeks set a new worst drawdown (dd > prior_dd), or, with at
   least MIN_TRADES trades, lost money with pf < FAILED_PF (no pf: lost more than
   one forward-pace window's worth of profit).
3. too_few_trades: fewer than MIN_TRADES trades; too few to judge either way.
4. held_up: net > 0, pf >= 1 (when known), dd <= prior_dd, and the profit pace is
   at least HELD_PACE of the forward pace (skipped when the forward window lost).
5. weakened: everything else (profitable but well below pace, or a small loss).
"""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from strategy_registry import inspect_set
from studio_evidence import server_msc, weekdays

RULES = 'goat-catchup-verdict-v1'
MIN_TRADES = 5
FAILED_PF = 0.8
HELD_PACE = 0.5
MODERATE_TRADES = 20
MODERATE_DAYS = 10
MAX_EQUITY_CSV = 64 * 1024 * 1024
MAX_DEALS_CSV = 256 * 1024 * 1024
TOLERANCE = Decimal('0.005')
CAVEAT = ('The new weeks are unseen data, but a few weeks is a small sample: treat held_up as "no warning sign yet", '
          'not as proof of an edge.')


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


def equity_window(rows, first_day, last_day, *, opening=None):
    """Net/realized/dd over [first_day, last_day] (inclusive dates) from equity rows."""
    start, end = _midnight(first_day), _midnight(last_day + timedelta(days=1))
    before = [row for row in rows if row[0] < start]
    inside = [row for row in rows if start <= row[0] < end]
    if before:
        open_balance, open_equity = before[-1][1], before[-1][2]
    elif opening is not None:
        open_balance = open_equity = Decimal(str(opening))
    else:
        open_balance, open_equity = rows[0][1], rows[0][2]
    last = inside[-1] if inside else (open_balance, open_equity)
    close_balance, close_equity = (last[1], last[2]) if inside else last
    peak, dd = open_equity, Decimal(0)
    for _, _, equity in inside:
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dict(first_day=first_day.isoformat(), last_day=last_day.isoformat(), weekdays=weekdays(first_day, last_day),
                samples=len(inside), open_equity=float(open_equity), close_equity=float(close_equity),
                net=float(close_equity - open_equity), realized=float(close_balance - open_balance), dd=float(dd),
                dd_pct=float(dd / open_equity * 100) if open_equity > 0 else None)


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
    """Entry/close counts and pf from a capture deals.csv over [first_day, last_day]."""
    lo, hi = server_msc(first_day), server_msc(last_day + timedelta(days=1))
    path = Path(deals_csv)
    if path.stat().st_size > MAX_DEALS_CSV:
        raise ValueError('deals.csv exceeds its byte bound')
    entries = closes = 0
    wins, losses = Decimal(0), Decimal(0)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            stamp = int(row['server_time_msc'])
            if not lo <= stamp < hi:
                continue
            entry = row['deal_entry']
            if entry == '0':
                entries += 1
            elif entry in ('1', '2', '3'):
                closes += 1
            result = sum(Decimal(row[key]) for key in ('profit', 'commission', 'fee', 'swap'))
            if result > 0:
                wins += result
            else:
                losses -= result
    pf = float(wins / losses) if losses > 0 else None
    return dict(entries=entries, closes=closes, gross_win=float(wins), gross_loss=float(losses), pf=pf,
                pf_note=None if losses > 0 else ('no losing deals' if wins > 0 else 'no deal results'))


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


def decide(new, prior_dd, pace):
    """Apply the verdict rules to measured numbers. Pure; see module docstring."""
    trades, net, dd, pf = new['trades'], new['net'], new['dd'], new.get('pf')
    days = max(new['weekdays'], 1)
    forward_per_day = pace.get('net_per_day') if pace else None
    reasons = []
    if dd > prior_dd:
        reasons.append('new weeks set a new worst drawdown (%.0f vs %.0f before)' % (dd, prior_dd))
        return 'failed', reasons
    if trades is not None and trades >= MIN_TRADES and net < 0:
        if pf is not None and pf < FAILED_PF:
            reasons.append('lost %.0f with profit factor %.2f' % (-net, pf))
            return 'failed', reasons
        if pf is None and forward_per_day is not None and -net > abs(forward_per_day) * days:
            reasons.append('lost %.0f, more than a forward-pace window of profit' % -net)
            return 'failed', reasons
    if trades is None or trades < MIN_TRADES:
        reasons.append('%s trades in the new weeks; too few to judge' % ('unknown' if trades is None else trades))
        return 'too_few_trades', reasons
    held = net > 0 and (pf is None or pf >= 1.0)
    if held and forward_per_day is not None and forward_per_day > 0 and net / days < HELD_PACE * forward_per_day:
        held = False
        reasons.append('profitable but at %.0f%% of the forward pace' % (100 * net / days / forward_per_day))
    if held:
        reasons.append('profitable, drawdown within what it had already shown')
        return 'held_up', reasons
    if not reasons:
        reasons.append('lost %.0f' % -net if net < 0 else 'flat' if net == 0 else 'profit factor below 1')
    return 'weakened', reasons


def _plain(verdict, new, pace, reasons, reproduced):
    span = '%s to %s (%d trading days)' % (new['first_day'], new['last_day'], new['weekdays'])
    numbers = '%+.0f, %s trades, DD %.0f' % (new['net'], '?' if new['trades'] is None else new['trades'], new['dd'])
    if new.get('pf') is not None:
        numbers += ', PF %.2f' % new['pf']
    text = {'held_up': 'Held up', 'weakened': 'Weakened', 'failed': 'Failed', 'too_few_trades': 'Too few trades to judge',
            'not_comparable': 'Not comparable'}[verdict]
    sentence = '%s over the new weeks %s: %s' % (text, span, numbers)
    if pace and pace.get('net_per_day') is not None:
        sentence += '; forward pace was %+.1f/day, new weeks %+.1f/day' % (pace['net_per_day'], new['net'] / max(new['weekdays'], 1))
    sentence += '. ' + '; '.join(reasons).capitalize()
    if verdict == 'too_few_trades' and new.get('expected_trades_at_forward_pace') is not None:
        sentence += ' (about %g expected at the forward pace)' % new['expected_trades_at_forward_pace']
    sentence += '.'
    if reproduced is False:
        sentence += ' The re-test did not exactly repeat the original export before the new weeks; judge with care.'
    return sentence


def evaluate(original, retest, *, new_end, tester=None):
    """Verdict for one catch-up member.

    ``original``: the original export's evidence record (studio_evidence.read_export).
    ``retest``: the re-test unit's evidence record. ``tester``: original optimization
    window (FromDate/ToDate/ForwardDate) when the run manifest supplied it.
    """
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
    opening = new_capture.get('initial_equity')
    window = equity_window(new_rows, first_new, new_end, opening=opening)
    covered = bool(new_capture.get('complete')) and new_capture.get('observed_end_msc', 0) >= server_msc(new_end) and new_deals
    if covered:
        deals = deal_window(new_deals, first_new, new_end)
        window.update(trades=deals['entries'], closes=deals['closes'], pf=deals['pf'], pf_note=deals['pf_note'], trade_source='capture_deals')
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
    if not same_inputs:
        verdict, reasons = 'not_comparable', ['the re-test SET inputs differ from the original export']
    else:
        verdict, reasons = decide(window, prior, pace)
    confidence = 'low'
    if (verdict != 'not_comparable' and repro['reproduced'] and window['trades'] is not None
            and window['trades'] >= MODERATE_TRADES and window['weekdays'] >= MODERATE_DAYS):
        confidence = 'moderate'
    return dict(schema=RULES, verdict=verdict, confidence=confidence, reasons=reasons,
                plain=_plain(verdict, window, pace, reasons, repro['reproduced']),
                new_weeks=window, prior_dd=prior, forward_pace=pace, inputs_match=same_inputs, reproduction=repro,
                original=dict(set_path=original['set_path'], set_sha256=original['set_sha256'], evidence_end=original['evidence_end'],
                              values_sha256=original['values_sha256']),
                retest=dict(set_path=retest['set_path'], set_sha256=retest['set_sha256'], evidence_end=retest['evidence_end'],
                            capture_status=new_capture.get('status')),
                rules=dict(min_trades=MIN_TRADES, failed_pf=FAILED_PF, held_pace=HELD_PACE), caveat=CAVEAT)
