"""Tick-history drift: when a catch-up re-test may stand in for its original (goat-catchup-rebase-v1).

Decided on goatai#1885 (6008922429, 6008944190, 6008946539). The first native catch-up re-tested 28
exports on the same build, inputs, model, server, deposit, leverage and currency: 3 reproduced exactly,
25 missed the exact ``reproduced`` check by small amounts (final balance -22 to +2, EURUSD trade times
shifted on thousands of rows). The likely cause is that the broker's tick history changed. So:

* ``comparable``: the exact reproduction (``studio_catchup_verdict.reproduction``) is the fast path.
* ``not_comparable``: any identity check failed (inputs, EA build, EA name, model, symbol, server,
  deposit, leverage, currency). Identity stays strict, exactly as before.
* Deal-level step (Ops, goatai#1885 6009311876: the 25 were swap-rate changes; MT5's tester applies a
  symbol's CURRENT swap rates to all history and Darwinex updates them). When both runs have a complete
  capture, their deals before the cut are compared exactly as the trading-equivalence canary does
  (time, type, entry, lots, price: ``studio_equivalence.deal_list``/``compare_deals``). Identical deals
  whose equity difference changes only on rollover rows (the first row after server midnight, where
  swap is charged; ``money_check``) are ``comparable_rebased`` with ``tickHistoryDrift.cause:
  'swap_or_spec'``, whatever the size: current swaps are what live trading pays, so every window is
  re-based on the re-test. Money that moves anywhere else, or different deals, fall through.
* Otherwise (``cause: 'history_or_behaviour'``) the re-test is compared with the original over the ORIGINAL span, in aggregate, never
  row by row (``CRITERIA``). When every criterion holds the verdict is ``comparable_rebased``: the
  re-test becomes the evidence for every window (BOOS, SAMPLE, FWD, FOOS), each recomputed on the
  re-test alone (``rebased_windows``), never the old export spliced with new weeks.
* ``requalify``: any criterion failed or could not be measured. The re-test is a NEW candidate: full
  gates, no carried status, and the reasons name every failed criterion.

The original span is [original start 00:00, cut) where cut is the original's last equity minute: the
original force-closed its positions there, so that minute is excluded from both runs, as in
``reproduction``. Measured on each run:

* deal_count: positions opened in the span (entry deals), the EA's ``Trades=`` count.
* pf: positive / |non-positive| deal results (profit + swap + commission + fee) of the positions
  opened in the span, deals before the cut (``studio_oos_windows.DEFINITIONS``).
* final_balance: the balance of the last equity row before the cut. Both runs are compared at the
  same moment, before the original's forced close, so like is compared with like.
* sample_pf: PF of the SAMPLE window [FromDate, ForwardDate - 1]; its side of 1.0 is PF >= 1.0,
  which is exactly the window's net (pl) >= 0.
* max_dd: deepest fall of the sampled equity below its running peak, from the span's first row.

Deal-based criteria need a complete sequence capture (``deals.csv``) on BOTH runs. Without one they
are not measured, which fails them: such a re-test requalifies, it is never re-based on guesses.

Stamps: ``historyBasis {originalExportedAt, retestAt}`` (the SET files' modification times, UTC) and
``tickHistoryDrift {dealCountDelta, pfDelta, balanceDelta, ddDelta, maxEquityGap, cause}`` (re-test minus
original; maxEquityGap is the largest |equity difference| over the minutes both runs sampled; cause is
``swap_or_spec`` from the deal-level step, else ``history_or_behaviour``). ``decidedBy`` and ``dealCheck``
say which step decided and what the deal comparison found.

The bar is shared through ``fixtures/catchup-rebase-cases.json`` (``judge_case``).
"""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

SCHEMA = 'goat-catchup-rebase-v1'
WINDOWS_SCHEMA = 'goat-catchup-rebased-windows-v1'
COMPARABLE, REBASED, REQUALIFY, NOT_COMPARABLE = 'comparable', 'comparable_rebased', 'requalify', 'not_comparable'
VERDICTS = (COMPARABLE, REBASED, REQUALIFY, NOT_COMPARABLE)
# The bar (Decimal: an exact boundary is inside it, never lost to float rounding).
DEAL_COUNT_REL = Decimal('0.05')        # |deal count delta| <= 5% of the original count
PF_ABS = Decimal('0.05')                # |PF delta| <= 0.05
BALANCE_OF_DEPOSIT = Decimal('0.001')   # |final balance delta| <= max(0.1% of deposit,
BALANCE_OF_NET = Decimal('0.02')        #                            2% of |original net profit|)
DD_REL = Decimal('0.10')                # |max DD delta| <= 10% of the original max DD
PF_SIDE = Decimal('1')                  # SAMPLE PF on the same side of 1.0 (>= 1.0 is one side)
MONEY_TOLERANCE = Decimal('0.005')      # an equity-difference step below this is no change (the reproduction tolerance)
SWAP_OR_SPEC, HISTORY_OR_BEHAVIOUR = 'swap_or_spec', 'history_or_behaviour'   # tickHistoryDrift.cause
CRITERIA = ('deal_count', 'pf', 'final_balance', 'sample_pf_side', 'max_dd')
FIXTURE = 'fixtures/catchup-rebase-cases.json'
BAR = dict(deal_count='|delta| <= 5% of the original deal count', pf='|delta| <= 0.05',
           final_balance='|delta| <= max(0.1% of deposit, 2% of |original net profit|)',
           sample_pf_side='SAMPLE PF on the same side of 1.0 in both (PF >= 1.0 is one side)',
           max_dd='|delta| <= 10% of the original max drawdown')
NO_LOSS = 'no losing deals'


def _dec(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value).strip())
        except ArithmeticError:
            return None
        return number if number.is_finite() else None
    return None


def _num(value):
    return None if value is None else float(value)


def _side(window):
    """True when the window's PF is >= 1.0, False below, None when unknown."""
    if not isinstance(window, dict):
        return None
    pf = _dec(window.get('pf'))
    if pf is not None:
        return pf >= PF_SIDE
    if window.get('pf_note') == NO_LOSS:
        return True
    pl = _dec(window.get('pl'))
    return None if pl is None else pl >= 0


def _row(name, ok, original, retest, delta, limit, detail):
    return dict(criterion=name, ok=bool(ok), original=original, retest=retest, delta=delta, limit=limit, bar=BAR[name], detail=detail)


def criteria(original, retest, *, deposit):
    """Each criterion over the original span, from two aggregate measurements (pure).

    ``original``/``retest``: ``deal_count``, ``pf`` (or ``pf_note`` 'no losing deals'), ``final_balance``,
    ``max_dd`` and ``sample`` (``pf``/``pf_note``/``pl`` of the SAMPLE window). A missing value fails its
    criterion as not measured.
    """
    rows = []
    o, r = original.get('deal_count'), retest.get('deal_count')
    if type(o) is int and type(r) is int and o >= 0 and r >= 0:
        limit = DEAL_COUNT_REL * o
        rows.append(_row('deal_count', abs(r - o) <= limit, o, r, r - o, _num(limit), '%d vs %d deals (%+d, limit %s)' % (o, r, r - o, _num(limit))))
    else:
        rows.append(_row('deal_count', False, o, r, None, None, 'not measured (needs a complete capture on both runs)'))
    o, r = _dec(original.get('pf')), _dec(retest.get('pf'))
    if o is not None and r is not None:
        rows.append(_row('pf', abs(r - o) <= PF_ABS, _num(o), _num(r), _num(r - o), _num(PF_ABS), 'PF %s vs %s' % (o, r)))
    elif o is None and r is None and original.get('pf_note') == NO_LOSS and retest.get('pf_note') == NO_LOSS:
        rows.append(_row('pf', True, None, None, 0.0, _num(PF_ABS), 'no losing deals in either run'))
    else:
        rows.append(_row('pf', False, _num(o), _num(r), None, _num(PF_ABS), 'not measured (%s / %s)' % (
            original.get('pf_note') or o, retest.get('pf_note') or r)))
    o, r, base = _dec(original.get('final_balance')), _dec(retest.get('final_balance')), _dec(deposit)
    if o is not None and r is not None and base is not None and base > 0:
        limit = max(BALANCE_OF_DEPOSIT * base, BALANCE_OF_NET * abs(o - base))
        rows.append(_row('final_balance', abs(r - o) <= limit, _num(o), _num(r), _num(r - o), _num(limit),
                         'final balance %s vs %s (%+.2f, limit %.2f)' % (o, r, r - o, limit)))
    else:
        rows.append(_row('final_balance', False, _num(o), _num(r), None, None, 'not measured (balance or deposit unknown)'))
    o, r = _side(original.get('sample')), _side(retest.get('sample'))
    if o is not None and r is not None:
        word = lambda side: 'PF >= 1.0' if side else 'PF < 1.0'
        rows.append(_row('sample_pf_side', o == r, word(o), word(r), None, None, 'SAMPLE %s vs %s' % (word(o), word(r))))
    else:
        rows.append(_row('sample_pf_side', False, None, None, None, None, 'not measured (SAMPLE window or its deals unknown)'))
    o, r = _dec(original.get('max_dd')), _dec(retest.get('max_dd'))
    if o is not None and r is not None and o >= 0 and r >= 0:
        limit = DD_REL * o
        rows.append(_row('max_dd', abs(r - o) <= limit, _num(o), _num(r), _num(r - o), _num(limit),
                         'max drawdown %s vs %s (%+.2f, limit %.2f)' % (o, r, r - o, limit)))
    else:
        rows.append(_row('max_dd', False, _num(o), _num(r), None, None, 'not measured'))
    return rows


def drift(original, retest, *, max_equity_gap=None):
    """``tickHistoryDrift``: re-test minus original over the original span; null where unmeasured."""
    def delta(key, kind=Decimal):
        a, b = original.get(key), retest.get(key)
        if kind is int:
            return b - a if type(a) is int and type(b) is int else None
        a, b = _dec(a), _dec(b)
        return None if a is None or b is None else float(b - a)
    return dict(dealCountDelta=delta('deal_count', int), pfDelta=delta('pf'), balanceDelta=delta('final_balance'),
                ddDelta=delta('max_dd'), maxEquityGap=max_equity_gap)


def money_check(original_rows, retest_rows):
    """Is the money difference a swap accrual? The equity difference may change only on a rollover row.

    Rows are ``(minute, balance, equity)`` of each run before the cut, sampled at the same minutes. A
    rollover row is the first row of a new server day (the first row after server midnight), where MT5
    charges swap. Balance is not tested on its own: a held position's swap moves from floating equity to
    the balance when it closes, so the balance difference also steps at a close while equity does not.
    """
    if [row[0] for row in original_rows] != [row[0] for row in retest_rows]:
        return dict(swap_only=False, rollover_changes=None, first_off_rollover=None,
                    reason='the two runs sampled equity at different minutes')
    previous, day, changes = Decimal(0), None, 0
    for (stamp, _, old), (_, _, new) in zip(original_rows, retest_rows):
        difference = new - old
        if abs(difference - previous) > MONEY_TOLERANCE:
            if day is None or stamp.date() == day:
                return dict(swap_only=False, rollover_changes=changes, first_off_rollover=stamp.strftime('%Y-%m-%d %H:%M'),
                            reason='the equity difference changed at %s, which is not the first row after a server-midnight '
                                   'rollover, so it is not a swap accrual' % stamp.strftime('%Y-%m-%d %H:%M'))
            changes += 1
        previous, day = difference, stamp.date()
    return dict(swap_only=True, rollover_changes=changes, first_off_rollover=None, final_equity_difference=float(previous),
                reason='the equity difference changed only on rollover rows (%d)' % changes)


def deal_level(original_deals, retest_deals, original_rows, retest_rows):
    """Deal-level step: identical deals (time, type, entry, lots, price) with money drift only at rollovers? (pure).

    Deals compare exactly as the trading-equivalence canary does (``studio_equivalence.compare_deals``).
    """
    from studio_equivalence import compare_deals
    deals = compare_deals(original_deals, retest_deals)
    if not deals['matched']:
        return dict(status='deals_differ', swap_only=False, deals=deals, money=None,
                    reason='the deal lists differ (time, type, entry, lots or price), first at %s' % deals['first_difference'])
    money = money_check(original_rows, retest_rows)
    return dict(status='swap_only' if money['swap_only'] else 'money_off_rollover', swap_only=money['swap_only'], deals=deals,
                money=money, reason='identical deals; ' + money['reason'])


def decide(identity_failed, reproduced, original=None, retest=None, *, deposit=None, max_equity_gap=None, deal_check=None):
    """The comparison verdict (``VERDICTS``) with its criteria, reasons and drift (pure).

    ``deal_check`` (``deal_level``) runs first: identical deals whose money differs only at rollovers is a swap
    or symbol-spec change, ``comparable_rebased`` whatever its size. Otherwise the aggregate criteria decide.
    """
    if identity_failed:
        return dict(schema=SCHEMA, verdict=NOT_COMPARABLE, decidedBy='identity', criteria=None, failed=[],
                    reasons=list(identity_failed), dealCheck=None, tickHistoryDrift=None)
    if reproduced:
        return dict(schema=SCHEMA, verdict=COMPARABLE, decidedBy='exact_reproduction', criteria=None, failed=[],
                    reasons=['reproduced the original exactly'], dealCheck=None, tickHistoryDrift=None)
    if deal_check and deal_check.get('swap_only'):
        return dict(schema=SCHEMA, verdict=REBASED, decidedBy='deal_level', criteria=None, failed=[],
                    reasons=['the same deals (time, type, entry, lots, price); only money and equity differ, and only at '
                             'rollover rows: the broker changed its swap rates or symbol spec, which MT5 applies to all history'],
                    dealCheck=deal_check,
                    tickHistoryDrift=dict(drift(original or {}, retest or {}, max_equity_gap=max_equity_gap), cause=SWAP_OR_SPEC))
    rows = criteria(original or {}, retest or {}, deposit=deposit)
    failed = [row['criterion'] for row in rows if not row['ok']]
    reasons = ['%s: %s' % (row['criterion'], row['detail']) for row in rows if not row['ok']] if failed else \
        ['did not reproduce exactly, but every tick-history drift criterion holds over the original span']
    return dict(schema=SCHEMA, verdict=REQUALIFY if failed else REBASED, decidedBy='aggregate', criteria=rows, failed=failed,
                reasons=reasons, dealCheck=deal_check,
                tickHistoryDrift=dict(drift(original or {}, retest or {}, max_equity_gap=max_equity_gap), cause=HISTORY_OR_BEHAVIOUR))


def _case_deal_check(raw):
    """A fixture case's ``deal_level`` input: deal rows [msc, type, entry, lots, price], equity rows [minute, balance, equity]."""
    if not raw:
        return None
    deals = lambda rows: [(int(r[0]), str(r[1]), str(r[2]), Decimal(str(r[3])), Decimal(str(r[4]))) for r in rows]
    equity = lambda rows: [(datetime.strptime(r[0], '%Y-%m-%d %H:%M'), Decimal(str(r[1])), Decimal(str(r[2]))) for r in rows]
    return deal_level(deals(raw['deals']['original']), deals(raw['deals']['retest']),
                      equity(raw['equity']['original']), equity(raw['equity']['retest']))


def judge_case(case, defaults=None, deal_inputs=None):
    """Run one fixture case (``fixtures/catchup-rebase-cases.json``): ``defaults`` with the case's own fields on top.

    A case's ``deal_level`` is a deal/equity input, or the name of one in the fixture's ``deal_level_inputs``.
    """
    base = defaults or {}
    pick = lambda key, fallback=None: case[key] if key in case else base.get(key, fallback)
    original = dict(base.get('original') or {}, **(case.get('original') or {}))
    retest = dict(base.get('retest') or {}, **(case.get('retest') or {}))
    raw = case.get('deal_level')
    if isinstance(raw, str):
        raw = (deal_inputs or {})[raw]
    return decide(pick('identity_failed', []), pick('reproduced', False), original, retest, deposit=pick('deposit'),
                  deal_check=_case_deal_check(raw))


# ---------------------------------------------------------------------------
# Measuring two runs (bounded files, read only)
# ---------------------------------------------------------------------------

def _msc(moment):
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def deal_totals(deals_csv, lo_msc, hi_msc):
    """Entries and PF of the positions opened in [lo, hi), over their deals in [lo, hi)."""
    from studio_catchup_verdict import MAX_DEALS_CSV
    path = Path(deals_csv)
    if path.stat().st_size > MAX_DEALS_CSV:
        raise ValueError('deals.csv exceeds its byte bound')
    inside = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if lo_msc <= int(row['server_time_msc']) < hi_msc:
                inside.append(row)
    opened = {row['position_id'] for row in inside if row['deal_entry'] == '0'}
    wins, losses = Decimal(0), Decimal(0)
    for row in inside:
        if row['position_id'] in opened:
            result = sum(Decimal(row[key]) for key in ('profit', 'commission', 'fee', 'swap'))
            if result > 0:
                wins += result
            else:
                losses -= result
    return dict(deal_count=sum(row['deal_entry'] == '0' for row in inside), pf=wins / losses if losses > 0 else None,
                pf_note=None if losses > 0 else (NO_LOSS if wins > 0 else 'no deal results'), pl=wins - losses)


def measure(rows, deals, *, cut, sample):
    """One run's aggregate figures over [its first row, cut); ``sample`` = (first day, last day) or None."""
    from studio_catchup_verdict import deal_window
    inside = [row for row in rows if row[0] < cut]
    out = dict(deal_count=None, pf=None, pf_note='needs a complete capture', final_balance=None, max_dd=None, sample=None,
               rows=len(inside))
    if inside:
        peak, dd = inside[0][2], Decimal(0)
        for _, _, equity in inside:
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
        out.update(final_balance=inside[-1][1], max_dd=dd)
    if deals and inside:
        out.update(deal_totals(deals, _msc(datetime.combine(inside[0][0].date(), datetime.min.time())), _msc(cut)))
        if sample:
            window = deal_window(deals, sample[0], sample[1])
            out['sample'] = dict(pf=window['pf'], pf_note=window['pf_note'], pl=window['gross_win'] - window['gross_loss'],
                                 trades=window['entries'], first_day=sample[0].isoformat(), last_day=sample[1].isoformat())
    return out


def equity_gap(original_rows, retest_rows, cut):
    """Largest |equity difference| over the minutes both runs sampled before the cut (None: no shared minute)."""
    first = {stamp: equity for stamp, _, equity in original_rows if stamp < cut}
    gaps = [abs(equity - first[stamp]) for stamp, _, equity in retest_rows if stamp < cut and stamp in first]
    return float(max(gaps)) if gaps else None


def _mt5(text):
    return datetime.strptime(text, '%Y.%m.%d').date()


def window_bounds(original, tester):
    """(FromDate, ForwardDate, ToDate) as dates with their source: the run manifest tester, else the SET header."""
    tester = tester or {}
    try:
        return (_mt5(tester['FromDate']), _mt5(tester['ForwardDate']), _mt5(tester['ToDate'])), 'run_manifest'
    except (KeyError, TypeError, ValueError):
        pass
    windows = original.get('windows') or {}
    sample, fwd = windows.get('SAMPLE'), windows.get('FWD')
    if sample and fwd:
        return (date.fromisoformat(sample['start']), date.fromisoformat(fwd['start']), date.fromisoformat(fwd['end'])), 'set_header'
    return None, 'unknown'


def sample_days(original, tester):
    bounds, _ = window_bounds(original, tester)
    if bounds is None or bounds[1] <= bounds[0]:
        return None
    return bounds[0], bounds[1] - timedelta(days=1)


def _exported_at(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec='seconds')
    except (OSError, TypeError, ValueError):
        return None


def history_basis(original, retest):
    """``historyBasis``: when each run was written (SET file modification time, UTC)."""
    return dict(originalExportedAt=_exported_at(original.get('set_path')), retestAt=_exported_at(retest.get('set_path')),
                source='set_file_mtime_utc', originalEnd=original.get('evidence_end'), retestEnd=retest.get('evidence_end'))


def judge(original, retest, *, identity_failed, reproduced, old_rows, new_rows, old_deals, new_deals, tester, deposit):
    """``decide`` on two read runs, plus the ``historyBasis`` stamp (None unless the re-test is the basis)."""
    if identity_failed or reproduced:
        return dict(decide(identity_failed, reproduced), historyBasis=None, measured=None)
    cut = old_rows[-1][0]
    sample = sample_days(original, tester)
    if sample and sample[1] >= cut.date():
        sample = None   # SAMPLE must end inside the original span
    a = measure(old_rows, old_deals, cut=cut, sample=sample)
    b = measure(new_rows, new_deals, cut=cut, sample=sample)
    if old_deals and new_deals:
        # Deal-level step first (goatai#1885 6009311876): the canary's deal comparison, before the forced close.
        from studio_equivalence import deal_list
        deal_check = deal_level(deal_list(old_deals, cut_msc=_msc(cut)), deal_list(new_deals, cut_msc=_msc(cut)),
                                [row for row in old_rows if row[0] < cut], [row for row in new_rows if row[0] < cut])
    else:
        deal_check = dict(status='not_measured', swap_only=False, deals=None, money=None,
                          reason='needs a complete capture (deals.csv) on both runs')
    result = decide([], False, a, b, deposit=deposit, max_equity_gap=equity_gap(old_rows, new_rows, cut), deal_check=deal_check)
    public = lambda m: {k: (float(v) if isinstance(v, Decimal) else v) for k, v in m.items() if k != 'sample'} | dict(
        sample=None if m['sample'] is None else {k: (float(v) if isinstance(v, Decimal) else v) for k, v in m['sample'].items()})
    return dict(result, historyBasis=history_basis(original, retest), deposit=_num(_dec(deposit)),
                span=dict(first_row=old_rows[0][0].strftime('%Y-%m-%d %H:%M'), cut=cut.strftime('%Y-%m-%d %H:%M'), cut_excluded=True),
                measured=dict(original=public(a), retest=public(b)))


def rebased_windows(original, retest, rows, deals, *, tester, tested_through):
    """BOOS, SAMPLE, FWD and FOOS, every one recomputed on the re-test alone (no splice).

    Bounds: SAMPLE [FromDate, ForwardDate - 1], FWD [ForwardDate, ToDate - 1], BOOS [the run's BackOOSDate
    (else the original start), FromDate - 1] when it lies before SAMPLE, FOOS [ToDate, tested_through].
    Figures as ``studio_window_metrics.window`` (trades/PF from the re-test's deals, DD from its equity).
    """
    from studio_window_metrics import window
    bounds, source = window_bounds(original, tester)
    out = dict(schema=WINDOWS_SCHEMA, basis='retest', spliced=False, windowsSource=source, testedThrough=tested_through.isoformat(),
               BOOS=None, SAMPLE=None, FWD=None, FOOS=None)
    if bounds is None:
        return out
    start, forward, to_date = bounds
    samples = [(stamp, float(equity)) for stamp, _, equity in rows]
    back = (original.get('run') or {}).get('back_oos_date') or original.get('evidence_start')
    try:
        back = _mt5(back) if back and '.' in back else (date.fromisoformat(back) if back else None)
    except ValueError:
        back = None
    spans = dict(SAMPLE=(start, forward - timedelta(days=1)), FWD=(forward, to_date - timedelta(days=1)), FOOS=(to_date, tested_through))
    if back is not None and back < start:
        spans['BOOS'] = (back, start - timedelta(days=1))
    for name, (first, last) in spans.items():
        if last >= first:
            out[name] = dict(window(samples, first, last, deals=deals), name=name, basis='retest')
    return out
