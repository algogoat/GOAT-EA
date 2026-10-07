"""Catch-up re-test vs its original export: when the re-test may stand in for it (goat-catchup-rebase-v2).

History (goatai#1885). v1 (6008922429, 6008944190, 6008946539, 6009311876, 6010080246) re-based a re-test
that missed the exact reproduction on a deal-level swap step, else on aggregate drift bars (deal count, PF,
balance, SAMPLE side, max DD). Ops then showed that the MT5 tester is deterministic except swap
(6029461500): re-test vs re-test, orders.csv is byte-identical and the deals are identical in every column
except magic (run-local) and swap. Swap drifts because the tester applies the symbol's CURRENT swap rates to
all history. Claude-Mac's ruling (6029484888) replaces v1:

* ``not_comparable``: any identity check failed (inputs, EA build, EA name, model, symbol, server, deposit,
  leverage, currency). Unchanged.
* ``comparable``: the exact reproduction (``studio_catchup_verdict.reproduction``). Unchanged.
* ``comparable_rebased``: every rule in ``RULES`` holds over the original span. The behaviour is identical
  and only swap moved the money, within the bar: current swaps are what live trading pays, so every window
  is re-based on the re-test (``rebased_windows``), never the old export spliced with new weeks.
* ``requalify``: anything else (fail-safe). The re-test is a NEW candidate: full gates, no carried status.
  There is no aggregate pass path any more: if broker history revisions move a deal, the set is judged anew.

Rules, in order. Every rule is evaluated; ``failed`` names each failing one, and ``firstFailingRule`` and
``firstDifference`` (that rule's first differing row) are logged on the verdict and the receipt.

1. ``capture``: orders.csv, deals.csv, marks.csv and account.csv of a complete sequence capture, both runs.
2. ``orders``: every order before the cut identical in every column except the capture's ``ordinal``
   (a row counter shared by all capture files, not behaviour).
3. ``deals``: every deal before the cut identical on time, type, entry, lots, price and profit. Magic is
   run-local and swap is judged below, so neither is compared; commission and fee move the balance, so the
   balance rule catches them.
4. ``swap``: |delta total swap| <= max($5, 2% of the original's |total swap|). Total swap at the cut is the
   realized swap plus the floating swap of the positions still open (marks.csv).
5. ``balance``: on every account row, the balance difference equals the realized-swap difference within $0.01.
6. ``equity``: on every account row, the equity difference equals the cumulative swap difference (realized
   plus floating) within $0.01.
7. ``max_dd``: |delta max DD| <= 10% of the original's max DD (the export equity CSV, as the export measures it).

Which rows. The export equity CSV samples a row only when price or equity moved enough, so a swap change can
add or drop a row after a rollover (13 of the 25 B40 re-tests did) and its equity is a minute low, not a
point value. The capture's account.csv records balance and equity at fixed moments instead: every minute and
every trading event, identical in both runs when the behaviour is identical. The EA writes each moment's
marks (per sequence: realized swap, floating swap) just before its account row, under one ordinal counter,
so the swap "at that row" is exact: every mark with a smaller ordinal. Account rows that do not line up (a
different event or minute) fail both money rules.

The original span is [original start, cut) where cut is the original's last equity minute: the original
force-closed its positions there, so that minute is excluded from both runs, as in ``reproduction``.

Stamps: ``historyBasis {originalExportedAt, retestAt}`` (the SET files' modification times, UTC) and
``tickHistoryDrift {dealCountDelta, pfDelta, balanceDelta, ddDelta, maxEquityGap, swapDelta, swapBound,
originalSwap, retestSwap, cause, reviewFlag, reviewReason}`` (re-test minus original; ``cause`` is
``swap_or_spec`` for a re-based re-test, else ``history_or_behaviour``). A re-based re-test whose |final
balance delta| exceeds 5% of |original net profit| carries ``reviewFlag: true`` (Claude-Mac, 6010080246).
Across builds (an ACTIVE trading-equivalence certificate) the rule is the same: with no aggregate path, build
drift and history drift cannot stack; ``crossBuild`` records it.

The bar is shared through ``fixtures/catchup-rebase-cases.json`` (``judge_case``).
"""
from bisect import bisect_right
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path

SCHEMA = 'goat-catchup-rebase-v2'
WINDOWS_SCHEMA = 'goat-catchup-rebased-windows-v1'
COMPARABLE, REBASED, REQUALIFY, NOT_COMPARABLE = 'comparable', 'comparable_rebased', 'requalify', 'not_comparable'
VERDICTS = (COMPARABLE, REBASED, REQUALIFY, NOT_COMPARABLE)
# The bar (Decimal: an exact boundary is inside it, never lost to float rounding).
SWAP_FLOOR = Decimal('5')               # |delta total swap| <= max($5,
SWAP_OF_TOTAL = Decimal('0.02')         #                           2% of the original |total swap|)
MONEY_TOLERANCE = Decimal('0.01')       # balance / equity difference vs the swap difference (rounding)
DD_REL = Decimal('0.10')                # |max DD delta| <= 10% of the original max DD
SWAP_REVIEW_OF_NET = Decimal('0.05')    # re-based: reviewFlag when |balance delta| > 5% of |original net profit|
SWAP_OR_SPEC, HISTORY_OR_BEHAVIOUR = 'swap_or_spec', 'history_or_behaviour'   # tickHistoryDrift.cause
RULES = ('capture', 'orders', 'deals', 'swap', 'balance', 'equity', 'max_dd')
BAR = dict(capture='orders.csv, deals.csv, marks.csv and account.csv of a complete capture on both runs',
           orders='every order before the cut identical (every column except the capture ordinal)',
           deals='every deal before the cut identical on time, type, entry, lots, price and profit (magic and swap ignored)',
           swap='|delta total swap| <= max($5, 2% of the original |total swap|)',
           balance='on every account row, balance difference = realized swap difference within $0.01',
           equity='on every account row, equity difference = cumulative swap difference within $0.01',
           max_dd='|delta max DD| <= 10% of the original max DD')
CAPTURE_FILES = ('orders', 'deals', 'marks', 'account')
ORDER_IGNORED = frozenset(('ordinal',))
DEAL_FIELDS = ('server_time_msc', 'deal_type', 'deal_entry', 'lots', 'price', 'profit')
NUMERIC = frozenset(('lots', 'price', 'profit', 'commission', 'fee', 'swap', 'requested_lots', 'result_lots', 'result_price'))
MAX_ORDERS_CSV = 64 * 1024 * 1024
MAX_MARKS_CSV = 512 * 1024 * 1024
MAX_ACCOUNT_CSV = 512 * 1024 * 1024
FIXTURE = 'fixtures/catchup-rebase-cases.json'
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


def _msc(moment):
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _when(stamp):
    """A server-time msc as text (broker server time, as the capture records it)."""
    moment = datetime.fromtimestamp(stamp / 1000, timezone.utc)
    return moment.strftime('%Y-%m-%d %H:%M:%S.') + '%03d' % (stamp % 1000)


def _text(value):
    return str(value) if isinstance(value, Decimal) else value


def _norm(field, value):
    """A capture cell as compared: times as integers, money and volumes as exact decimals, the rest as text."""
    if field == 'server_time_msc':
        return int(value)
    if field in NUMERIC:
        return Decimal(value)
    return value


def _rule(name, ok, detail, *, first=None, **values):
    return dict(rule=name, ok=bool(ok), bar=BAR[name], detail=detail, firstDifference=first, **values)


# ---------------------------------------------------------------------------
# The rules (pure)
# ---------------------------------------------------------------------------

def compare_rows(original, retest, fields):
    """Identical row lists on ``fields``? Else the first differing row, both sides and the fields that differ."""
    a = [tuple(row.get(f) for f in fields) for row in original]
    b = [tuple(row.get(f) for f in fields) for row in retest]
    if a == b:
        return dict(matched=True, rows=len(a), first_difference=None)
    index = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    show = lambda rows: None if index >= len(rows) else {f: _text(v) for f, v in zip(fields, rows[index])}
    differ = [f for n, f in enumerate(fields) if index < len(a) and index < len(b) and a[index][n] != b[index][n]]
    return dict(matched=False, rows=[len(a), len(b)], first_difference=dict(
        index=index, original=show(a), retest=show(b), fields=differ or ['row count %d vs %d' % (len(a), len(b))]))


def swap_totals(marks):
    """(realized swap, cumulative swap) after every mark (ordinal, msc, sequence, realized swap, floating swap) (pure)."""
    realized, floating = {}, {}
    for _, _, sequence, done, open_swap in marks:
        realized[sequence], floating[sequence] = done, open_swap
    total = sum(realized.values(), Decimal(0))
    return total, total + sum(floating.values(), Decimal(0))


def account_states(account, marks):
    """Each account row with the run's swap at that moment (pure; both in capture order).

    ``account``: (ordinal, msc, reason, balance, equity, quote msc); ``marks``: (ordinal, msc, sequence, realized
    swap, floating swap), each sequence's latest values. The swap at a row is every mark with a smaller ordinal.
    Yields (msc, reason, balance, equity, realized swap, cumulative swap, quote msc).
    """
    marks = iter(marks)
    pending = next(marks, None)
    realized, floating, done, open_swap = {}, {}, Decimal(0), Decimal(0)
    for ordinal, stamp, reason, balance, equity, quote in account:
        while pending is not None and pending[0] < ordinal:
            _, _, sequence, value, still_open = pending
            done += value - realized.get(sequence, 0)
            open_swap += still_open - floating.get(sequence, 0)
            realized[sequence], floating[sequence] = value, still_open
            pending = next(marks, None)
        yield stamp, reason, balance, equity, done, done + open_swap, quote


class _Steps:
    """A run's cumulative swap as a step function of time, from the account rows seen so far."""

    def __init__(self):
        self.times, self.values = [], []

    def add(self, stamp, value):
        if not self.values or self.values[-1] != value:
            self.times.append(stamp)
            self.values.append(value)

    def at(self, stamp):
        index = bisect_right(self.times, stamp) - 1
        return self.values[index] if index >= 0 else Decimal(0)


def money_rows(original_states, retest_states):
    """The ``balance`` and ``equity`` rules over two runs' ``account_states`` (pure).

    Rows must line up (same moment and reason). On each, the balance difference must equal the realized-swap
    difference, and the equity difference the cumulative-swap difference as of the row's last price tick,
    within ``MONEY_TOLERANCE``. The tester charges swap on the open positions at the rollover but recalculates
    account equity only on the next tick, so until a tick arrives (the market is often closed just after
    midnight) the account's equity still carries the swap before the charge: the capture's quote time
    (``quote_server_time_msc``) says which.
    """
    out = {name: dict(ok=True, first=None, max_residual=Decimal(0)) for name in ('balance', 'equity')}
    rows, steps = 0, (_Steps(), _Steps())
    for index, (a, b) in enumerate(zip_longest(original_states, retest_states)):
        if a is None or b is None or a[:2] != b[:2]:
            show = lambda row: None if row is None else dict(time=_when(row[0]), reason=row[1])
            first = dict(row=index, original=show(a), retest=show(b),
                         reason='the two runs recorded the account at different moments (another event or minute row)')
            for item in out.values():
                if item['first'] is None:
                    item.update(ok=False, first=first)
            break
        rows += 1
        steps[0].add(a[0], a[5])
        steps[1].add(b[0], b[5])
        quote = a[6] if a[6] and a[6] == b[6] else a[0]   # no or differing quote: the row's own moment
        equity_swap = steps[1].at(quote) - steps[0].at(quote)
        for name, difference, swap in (('balance', b[2] - a[2], b[4] - a[4]), ('equity', b[3] - a[3], equity_swap)):
            item, residual = out[name], abs(difference - swap)
            item['max_residual'] = max(item['max_residual'], residual)
            if residual > MONEY_TOLERANCE and item['first'] is None:
                item['ok'] = False
                item['first'] = dict(row=index, time=_when(a[0]), reason=a[1], original=dict(balance=_num(a[2]), equity=_num(a[3])),
                                     retest=dict(balance=_num(b[2]), equity=_num(b[3])), difference=_num(difference),
                                     swapDifference=_num(swap), residual=_num(residual),
                                     quoteTime=_when(quote) if name == 'equity' else None)
    return dict(out, rows=rows)


def equity_figures(rows):
    """Final balance and max drawdown (deepest fall of the sampled equity below its running peak) of rows."""
    if not rows:
        return dict(final_balance=None, max_dd=None)
    peak, dd = rows[0][2], Decimal(0)
    for _, _, equity in rows:
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dict(final_balance=rows[-1][1], max_dd=dd)


def behaviour_check(original, retest, cut_msc):
    """Every rule in ``RULES`` on two runs before the cut (pure).

    A run is ``dict(orders=(fields, rows) | None, deals=[row] | None, marks=[(ordinal, msc, sequence, realized
    swap, floating swap)] | None, account=iterable of (ordinal, msc, reason, balance, equity, quote msc) | None,
    rows=[(minute, balance, equity)] (the export equity CSV), missing=[reason])``.
    """
    rules = []
    missing = ['original %s' % m for m in original.get('missing') or ()] + ['re-test %s' % m for m in retest.get('missing') or ()]
    rules.append(_rule('capture', not missing, 'complete captures on both runs' if not missing else
                       'not measured: %s' % '; '.join(missing), first=None if not missing else dict(missing=missing)))
    both = lambda key: original.get(key) is not None and retest.get(key) is not None
    # orders
    if both('orders'):
        (old_fields, old_orders), (new_fields, new_orders) = original['orders'], retest['orders']
        cut = lambda rows: [row for row in rows if row['server_time_msc'] < cut_msc]
        if old_fields != new_fields:
            rules.append(_rule('orders', False, 'orders.csv columns differ', first=dict(original=list(old_fields), retest=list(new_fields))))
        else:
            orders = compare_rows(cut(old_orders), cut(new_orders), old_fields)
            rules.append(_rule('orders', orders['matched'], 'identical orders (%s)' % orders['rows'] if orders['matched'] else
                               'order %d differs (%s)' % (orders['first_difference']['index'], ', '.join(orders['first_difference']['fields'])),
                               first=orders['first_difference'], rows=orders['rows']))
    else:
        rules.append(_rule('orders', False, 'not measured (orders.csv missing)'))
    # deals
    if both('deals'):
        deals = compare_rows([d for d in original['deals'] if d['server_time_msc'] < cut_msc],
                             [d for d in retest['deals'] if d['server_time_msc'] < cut_msc], DEAL_FIELDS)
        rules.append(_rule('deals', deals['matched'], 'identical deals (%s)' % deals['rows'] if deals['matched'] else
                           'deal %d differs (%s)' % (deals['first_difference']['index'], ', '.join(deals['first_difference']['fields'])),
                           first=deals['first_difference'], rows=deals['rows']))
    else:
        rules.append(_rule('deals', False, 'not measured (deals.csv missing)'))
    # swap
    swap = dict(original=None, retest=None, delta=None, bound=None, originalRealized=None, retestRealized=None)
    marks = {}
    if both('marks'):
        for side, run in (('original', original), ('retest', retest)):
            marks[side] = sorted((m for m in run['marks'] if m[1] < cut_msc), key=lambda m: m[0])
            swap[side + 'Realized'], swap[side] = swap_totals(marks[side])
        delta, bound = swap['retest'] - swap['original'], max(SWAP_FLOOR, SWAP_OF_TOTAL * abs(swap['original']))
        swap.update(delta=delta, bound=bound)
        ok = abs(delta) <= bound
        rules.append(_rule('swap', ok, 'total swap %.2f vs %.2f (%+.2f, limit %.2f)' % (swap['original'], swap['retest'], delta, bound),
                           first=None if ok else dict(original=_num(swap['original']), retest=_num(swap['retest']), delta=_num(delta), bound=_num(bound)),
                           original=_num(swap['original']), retest=_num(swap['retest']), delta=_num(delta), limit=_num(bound)))
    else:
        rules.append(_rule('swap', False, 'not measured (marks.csv missing)'))
    # balance and equity, on the capture's account rows
    if marks and both('account'):
        states = [account_states((row for row in run['account'] if row[1] < cut_msc), marks[side])
                  for side, run in (('original', original), ('retest', retest))]
        try:
            money = money_rows(*states)
        except (OSError, ValueError, KeyError, IndexError, ArithmeticError, csv.Error) as exc:   # a malformed streamed row
            unreadable = dict(ok=False, first=dict(reason='account.csv unreadable (%s)' % exc), max_residual=None)
            money = dict(balance=unreadable, equity=unreadable, rows=None)
        for name, what in (('balance', 'realized swap'), ('equity', 'cumulative swap')):
            item = money[name]
            if item['ok']:
                rules.append(_rule(name, True, '%s difference = %s difference on every account row (%d rows, largest residual %.4f)' % (
                    name, what, money['rows'], item['max_residual']), rows=money['rows'], max_residual=_num(item['max_residual'])))
            else:
                first = item['first']
                detail = first.get('reason') if 'difference' not in first else '%s difference %+.2f at %s, %s difference %+.2f (residual %.4f)' % (
                    name, first['difference'], first['time'], what, first['swapDifference'], first['residual'])
                rules.append(_rule(name, False, detail, first=first, rows=money['rows'], max_residual=_num(item['max_residual'])))
    else:
        for name in ('balance', 'equity'):
            rules.append(_rule(name, False, 'not measured (%s missing)' % ('account.csv' if marks else 'marks.csv')))
    # max_dd, on the export equity CSV
    a = equity_figures([row for row in original['rows'] if _msc(row[0]) < cut_msc])['max_dd']
    b = equity_figures([row for row in retest['rows'] if _msc(row[0]) < cut_msc])['max_dd']
    if a is not None and b is not None:
        limit = DD_REL * a
        ok = abs(b - a) <= limit
        rules.append(_rule('max_dd', ok, 'max drawdown %s vs %s (%+.2f, limit %.2f)' % (a, b, b - a, limit),
                           first=None if ok else dict(original=_num(a), retest=_num(b), delta=_num(b - a), limit=_num(limit)),
                           original=_num(a), retest=_num(b), delta=_num(b - a), limit=_num(limit)))
    else:
        rules.append(_rule('max_dd', False, 'not measured (no equity rows before the cut)'))
    return dict(rules=rules, swap={k: _num(v) for k, v in swap.items()})


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


def swap_review(original, retest, *, deposit):
    """(reviewFlag, reviewReason) for a re-based re-test: flagged when |balance delta| > 5% of |original net profit|.

    Claude-Mac, goatai#1885 6010080246: a swap change can change a carry-heavy set's economics, so a large one
    is flagged for review. An unmeasurable delta or net is flagged too (never waved through).
    """
    o, r, base = _dec(original.get('final_balance')), _dec(retest.get('final_balance')), _dec(deposit)
    if o is None or r is None or base is None:
        return True, 'swap drift could not be sized (final balance or deposit unknown)'
    delta, limit = abs(r - o), SWAP_REVIEW_OF_NET * abs(o - base)
    if delta > limit:
        return True, ('swap drift moved the final balance by %.2f, more than 5%% of the original net profit (%.2f): '
                      'review the set\'s carry before relying on it' % (r - o, limit))
    return False, 'swap drift %.2f is within 5%% of the original net profit (%.2f)' % (r - o, limit)


def decide(identity_failed, reproduced, check=None, *, original=None, retest=None, deposit=None, max_equity_gap=None,
           cross_build=False):
    """The comparison verdict (``VERDICTS``) with its rules, first failing rule, reasons and drift (pure).

    ``check`` is ``behaviour_check``'s result; without one nothing is measured, which requalifies (fail-safe).
    """
    blank = dict(schema=SCHEMA, rules=None, failed=[], firstFailingRule=None, firstDifference=None, tickHistoryDrift=None,
                 crossBuild=cross_build, swap=None)
    if identity_failed:
        return dict(blank, verdict=NOT_COMPARABLE, decidedBy='identity', reasons=list(identity_failed))
    if reproduced:
        return dict(blank, verdict=COMPARABLE, decidedBy='exact_reproduction', reasons=['reproduced the original exactly'])
    check = check or dict(rules=[_rule('capture', False, 'not measured: needs complete captures on both runs',
                                       first=dict(missing=['no behaviour check']))], swap={})
    rules, swap = check['rules'], check.get('swap') or {}
    failed = [row['rule'] for row in rules if not row['ok']]
    first = next((row for row in rules if not row['ok']), None)
    stamp = dict(drift(original or {}, retest or {}, max_equity_gap=max_equity_gap), swapDelta=swap.get('delta'),
                 swapBound=swap.get('bound'), originalSwap=swap.get('original'), retestSwap=swap.get('retest'))
    common = dict(schema=SCHEMA, decidedBy='behaviour_rules', rules=rules, failed=failed, crossBuild=cross_build, swap=swap)
    if failed:
        return dict(common, verdict=REQUALIFY, firstFailingRule=first['rule'], firstDifference=first['firstDifference'],
                    reasons=['%s: %s' % (row['rule'], row['detail']) for row in rules if not row['ok']],
                    tickHistoryDrift=dict(stamp, cause=HISTORY_OR_BEHAVIOUR, reviewFlag=False, reviewReason=None))
    flag, why = swap_review(original or {}, retest or {}, deposit=deposit)
    return dict(common, verdict=REBASED, firstFailingRule=None, firstDifference=None,
                reasons=['the same orders and deals (time, type, entry, lots, price, profit); only swap differs, by %+.2f '
                         '(limit %.2f), and balance and equity moved only by it: the broker changed its swap rates, which '
                         'MT5 applies to all history' % (swap.get('delta') or 0.0, swap.get('bound') or 0.0)],
                tickHistoryDrift=dict(stamp, cause=SWAP_OR_SPEC, reviewFlag=flag, reviewReason=why))


# ---------------------------------------------------------------------------
# The shared fixture (fixtures/catchup-rebase-cases.json)
# ---------------------------------------------------------------------------

def fixture_run(spec):
    """One run of the fixture's carry scenario (see the fixture's ``notes``), with the case's edits applied."""
    s1, s2 = (Decimal(str(v)) for v in spec.get('swap', (0, 0)))
    dip, b0 = Decimal(str(spec.get('dip', 160))), Decimal(100000)
    at = lambda day, hour, minute=0, second=0: datetime(2026, 1, 5 + day, hour, minute, second)
    opened, closed = _msc(at(0, 10)), _msc(at(2, 10))
    end = b0 + 500 + s1 + s2
    # The export equity CSV rows; the capture's account rows are taken at the same moments (index for index).
    rows = [[at(0, 10), b0, b0], [at(0, 15), b0, b0 + 200], [at(1, 0, 1), b0, b0 + 200 + s1], [at(1, 12), b0, b0 + dip + s1],
            [at(2, 0, 1), b0, b0 + 200 + s1 + s2], [at(2, 8), b0, b0 + dip + s1 + s2], [at(2, 10), end, end], [at(2, 12), end, end],
            [at(2, 15), end, end]]
    fields = ('server_time_msc', 'sequence_id', 'direction', 'order_id', 'deal_id', 'retcode', 'sent', 'requested_lots',
              'result_lots', 'result_price')
    orders = [dict(zip(fields, (opened, '1', '0', '2', '2', '10009', 'true', Decimal(1), Decimal(1), Decimal('1.1')))),
              dict(zip(fields, (closed, '1', '0', '3', '3', '10009', 'true', Decimal(1), Decimal(1), Decimal('1.105'))))]
    magic = str(spec.get('magic', '21058'))
    deals = [dict(server_time_msc=opened, deal_type='0', deal_entry='0', lots=Decimal(1), price=Decimal('1.1'), profit=Decimal(0),
                  swap=Decimal(0), commission=Decimal(0), fee=Decimal(0), deal_magic=magic),
             dict(server_time_msc=closed, deal_type='1', deal_entry='1', lots=Decimal(1), price=Decimal('1.105'), profit=Decimal(500),
                  swap=s1 + s2, commission=Decimal(0), fee=Decimal(0), deal_magic=magic)]
    marks = [[opened, '1', Decimal(0), Decimal(0)], [_msc(at(1, 0, 0, 1)), '1', Decimal(0), s1],
             [_msc(at(2, 0, 0, 1)), '1', Decimal(0), s1 + s2], [closed, '1', s1 + s2, Decimal(0)]]
    account = [[_msc(row[0]), 'event' if n in (0, 6) else 'minute', row[1], row[2], _msc(row[0])] for n, row in enumerate(rows)]
    for kind, target in (('orders_edit', orders), ('deals_edit', deals)):
        for index, field, value in spec.get(kind) or ():
            target[index][field] = _norm(field, str(value))
    for index, field, value in spec.get('marks_edit') or ():   # field: 2 realized swap, 3 floating swap
        marks[index][field] = Decimal(str(value))
    for index, amount in spec.get('balance_shift') or ():     # money moved from that row on (balance and equity)
        for row in rows[index:]:
            row[1] += Decimal(str(amount))
            row[2] += Decimal(str(amount))
        for row in account[index:]:
            row[2] += Decimal(str(amount))
            row[3] += Decimal(str(amount))
    for index, amount in spec.get('balance_only_shift') or ():   # balance alone moved at that account row
        account[index][2] += Decimal(str(amount))
    for index, amount in spec.get('equity_shift') or ():      # equity moved at that row only
        rows[index][2] += Decimal(str(amount))
        account[index][3] += Decimal(str(amount))
    for index, minute in spec.get('csv_minute_shift') or ():  # the export CSV sampled another minute
        rows[index][0] = datetime.strptime(minute, '%Y-%m-%d %H:%M')
    for index, minute in spec.get('account_minute_shift') or ():   # the account row at another moment
        account[index][0] = _msc(datetime.strptime(minute, '%Y-%m-%d %H:%M'))
    swap_at = lambda stamp: next((m[2] + m[3] for m in reversed(marks) if m[0] <= stamp), Decimal(0))   # one sequence
    for index, minute in spec.get('stale') or ():   # no tick since that minute: account equity before any later charge
        quote = _msc(datetime.strptime(minute, '%Y-%m-%d %H:%M'))
        account[index][3] -= swap_at(account[index][0]) - swap_at(quote)
        account[index][4] = quote
    # One ordinal counter, as the EA writes it: each moment's marks just before its account row.
    events = sorted([(m[0], 0, n) for n, m in enumerate(marks)] + [(a[0], 1, n) for n, a in enumerate(account)])
    ordinal = int(spec.get('ordinal_offset', 0))
    marked, accounted = {}, {}
    for number, (_, kind, n) in enumerate(events, ordinal + 1):
        (marked if kind == 0 else accounted)[n] = number
    run = dict(orders=(fields, orders), deals=deals, rows=[tuple(row) for row in rows], missing=[],
               marks=[(marked[n], *m) for n, m in enumerate(marks)],
               account=[(accounted[n], *a) for n, a in enumerate(account)])
    for name in spec.get('missing') or ():
        run[name] = None
        run['missing'].append(name + '.csv missing')
    return run


def judge_case(case, defaults=None):
    """Run one fixture case: ``defaults`` with the case's own fields on top, each run built by ``fixture_run``."""
    base = defaults or {}
    pick = lambda key, fallback=None: case[key] if key in case else base.get(key, fallback)
    spec = lambda side: dict(base.get(side) or {}, **(case.get(side) or {}))
    old, new = fixture_run(spec('original')), fixture_run(spec('retest'))
    cut = old['rows'][-1][0]
    check = behaviour_check(old, new, _msc(cut))
    figures = lambda run: equity_figures([row for row in run['rows'] if row[0] < cut])
    return decide(pick('identity_failed', []), pick('reproduced', False), check, original=figures(old), retest=figures(new),
                  deposit=pick('deposit'), cross_build=pick('cross_build', False))


# ---------------------------------------------------------------------------
# Reading two runs (bounded files, read only)
# ---------------------------------------------------------------------------

def _bounded(path, limit):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('%s exceeds its byte bound' % path.name)
    return path


def read_orders(path, cut_msc):
    """(fields, rows) of orders.csv before the cut, every column except ``ORDER_IGNORED``."""
    with _bounded(path, MAX_ORDERS_CSV).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = tuple(f for f in reader.fieldnames or () if f not in ORDER_IGNORED)
        rows = [{f: _norm(f, row[f]) for f in fields} for row in reader if int(row['server_time_msc']) < cut_msc]
    return fields, rows


def read_deals(path, cut_msc):
    """Deals before the cut: the compared fields plus swap, commission, fee and magic."""
    from studio_catchup_verdict import MAX_DEALS_CSV
    keep = DEAL_FIELDS + ('swap', 'commission', 'fee')
    with _bounded(path, MAX_DEALS_CSV).open(encoding='utf-8-sig', newline='') as stream:
        return [dict({f: _norm(f, row[f]) for f in keep}, deal_magic=row.get('deal_magic'))
                for row in csv.DictReader(stream) if int(row['server_time_msc']) < cut_msc]


def read_marks(path, cut_msc):
    """(ordinal, msc, sequence, realized swap, floating swap) of marks.csv before the cut, where a sequence's swap changed."""
    out, last = [], {}
    with _bounded(path, MAX_MARKS_CSV).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        header = next(reader)
        o, t, s, rs, fs = (header.index(name) for name in ('ordinal', 'server_time_msc', 'sequence_id', 'realized_swap', 'floating_swap'))
        for row in reader:
            pair = (row[rs], row[fs])
            if last.get(row[s]) == pair or int(row[t]) >= cut_msc:
                continue
            last[row[s]] = pair
            out.append((int(row[o]), int(row[t]), row[s], Decimal(pair[0]), Decimal(pair[1])))
    return out


def read_account(path):
    """(ordinal, msc, reason, balance, equity, quote msc) of account.csv, streamed (the file is a row per minute)."""
    with _bounded(path, MAX_ACCOUNT_CSV).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        header = next(reader)
        o, t, r, b, e, q = (header.index(name) for name in ('ordinal', 'server_time_msc', 'reason', 'balance', 'equity', 'quote_server_time_msc'))
        for row in reader:
            yield int(row[o]), int(row[t]), row[r], Decimal(row[b]), Decimal(row[e]), int(row[q])


def read_run(deals_csv, rows, cut_msc):
    """One run for ``behaviour_check``: its capture files next to ``deals_csv`` (None: no complete capture).

    account.csv is streamed when the rules read it (``read_account``); the others are read here.
    """
    run = dict(orders=None, deals=None, marks=None, account=None, rows=rows, missing=[])
    if not deals_csv:
        run['missing'].append('no complete sequence capture')
        return run
    folder = Path(deals_csv).parent
    readers = dict(orders=read_orders, deals=read_deals, marks=read_marks)
    for name in CAPTURE_FILES:
        path = folder / (name + '.csv')
        if not path.is_file():
            run['missing'].append(name + '.csv missing')
            continue
        try:
            run[name] = readers[name](path, cut_msc) if name in readers else read_account(_bounded(path, MAX_ACCOUNT_CSV))
            if name == 'account':
                next(iter(read_account(path)), None)   # the header and first row read now, so a bad file is a missing capture
        except (OSError, ValueError, KeyError, IndexError, ArithmeticError, csv.Error) as exc:
            run['missing'].append('%s.csv unreadable (%s)' % (name, exc))
    return run


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
    """One run's aggregate figures over [its first row, cut) for the drift stamp; ``sample`` = (first day, last day) or None."""
    from studio_catchup_verdict import deal_window
    inside = [row for row in rows if row[0] < cut]
    out = dict(deal_count=None, pf=None, pf_note='needs a complete capture', final_balance=None, max_dd=None, sample=None,
               rows=len(inside))
    if inside:
        out.update(equity_figures(inside))
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
    # originalExportedAtBasis says what the time is (Claude-Mac, #1885 6010080246): the capture has no export timestamp yet.
    return dict(originalExportedAt=_exported_at(original.get('set_path')), originalExportedAtBasis='set_mtime',
                retestAt=_exported_at(retest.get('set_path')), source='set_file_mtime_utc', originalEnd=original.get('evidence_end'), retestEnd=retest.get('evidence_end'))


def judge(original, retest, *, identity_failed, reproduced, old_rows, new_rows, old_deals, new_deals, tester, deposit,
          cross_build=False):
    """``decide`` on two read runs, plus the ``historyBasis`` stamp (None unless the re-test is the basis)."""
    if identity_failed or reproduced:
        return dict(decide(identity_failed, reproduced, cross_build=cross_build), historyBasis=None, measured=None)
    cut = old_rows[-1][0]
    sample = sample_days(original, tester)
    if sample and sample[1] >= cut.date():
        sample = None   # SAMPLE must end inside the original span
    a = measure(old_rows, old_deals, cut=cut, sample=sample)
    b = measure(new_rows, new_deals, cut=cut, sample=sample)
    check = behaviour_check(read_run(old_deals, old_rows, _msc(cut)), read_run(new_deals, new_rows, _msc(cut)), _msc(cut))
    result = decide([], False, check, original=a, retest=b, deposit=deposit, max_equity_gap=equity_gap(old_rows, new_rows, cut),
                    cross_build=cross_build)
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
