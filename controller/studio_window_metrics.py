"""Exact per-set metrics before FOOS (``goat-export-window-metrics-v1``), computed controller-side at export.

Claude-Mac's ruling (goatai#1885 comment 6006565005): the desktop estimated pre-FOOS ARF and
Sharpe by scaling the EA's full-period header values; exact values are better. The EA writes
its header and file-name metrics over the whole export test, and the EA is not changed here,
so the controller computes them from what each export unit already holds: the equity CSV
(one-minute equity samples) and, when the export carries a complete sequence capture, its
``deals.csv``. Read only.

Fields (camelCase, read by the desktop, goatai#2276), each a window object
``{from, to, days, profit, pf, pfNote, trades, tradeSource, maxDd, ddPct, arf, sharpe,
recoveryFactor, equityNet}``:

* ``preFoos``: everything the export holds before FOOS: from the export start (BOOS start
  when the export includes BOOS, else SAMPLE start) through the optimization end (the day
  before FOOS starts = MT5 ToDate - 1 day).
* ``selectionWindow``: SAMPLE + FWD only: SAMPLE start (FromDate) through the optimization
  end. House portfolios rank on this span.
* ``fullExport``: the whole export, computed the same way, so the desktop compares like with
  like (these are controller values, not the EA's header values).

Definitions (shared with the OOS evaluator, ``studio_oos_windows.DEFINITIONS``):

* trades, profit (= PL), pf: positions opened in the window, from the capture's deals: profit
  is the net of profit + swap + commission + fee of their deals inside the window (all costs);
  pf = positive deal results / |non-positive deal results|, null with ``pfNote`` 'no losing
  deals' when nothing lost. Without a complete capture: trades and profit are the sums of the
  EA's SET header window lines (``tradeSource: set_header``) when those lines cover the window
  exactly, pf is null.
* maxDd: equity drawdown in money, deepest fall of the sampled equity below its running peak,
  the peak starting at the window's opening equity (the last sample before the window, else its
  first sample). ddPct: the deepest such fall as a percent of the running peak at that moment.
* recoveryFactor = profit / maxDd. equityNet = closing - opening equity.
* arf: the EA's header ARF (monthly ARF, ``OnTester`` in GOAT V1.49.mq5) replayed on the
  samples: Return = equityNet / opening equity; drawdown episodes end at each new equity high;
  MeanDD = the EA's weighted mean of the five deepest episodes (the deepest one when Return < 0);
  ARF = Return / (MeanDD / opening equity) / (days / 21.7), days = Mon-Fri days in the window.
  The EA measures on ticks and counts days with ticks, so values can differ slightly from a
  header ARF over the same span.
* sharpe: daily equity returns (close of each Mon-Fri day, carried forward) annualized:
  mean / sample standard deviation x sqrt(252). This is NOT MT5's STAT_SHARPE_RATIO (the EA
  header SR); compare it only with ``fullExport.sharpe``.
"""
from datetime import date, datetime, timedelta
import math
from pathlib import Path

SCHEMA = 'goat-export-window-metrics-v1'
FIELDS = ('from', 'to', 'days', 'profit', 'pf', 'pfNote', 'trades', 'tradeSource', 'maxDd', 'ddPct', 'arf', 'sharpe',
          'recoveryFactor', 'equityNet')
MAX_EQUITY_CSV = 64 * 1024 * 1024
HEADER = '<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'


def equity_samples(raw):
    """[(minute datetime, equity float)] from an export equity CSV's bytes, in file order."""
    if not raw or len(raw) > MAX_EQUITY_CSV:
        raise ValueError('Empty or oversized equity CSV')
    lines = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig').splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError('Unexpected equity CSV header')
    rows, previous = [], None
    for index, line in enumerate(lines[1:], 2):
        parts = line.split('\t')
        text = parts[0]
        if len(parts) != 4 or len(text) != 16 or text[4] != '.' or text[7] != '.' or text[10] != ' ' or text[13] != ':':
            raise ValueError('Invalid equity row %d' % index)
        try:
            stamp = datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]), int(text[11:13]), int(text[14:16]))
            equity = float(parts[2])
        except ValueError as exc:
            raise ValueError('Invalid equity row %d' % index) from exc
        if not math.isfinite(equity) or (previous is not None and stamp < previous):
            raise ValueError('Invalid or backwards equity row %d' % index)
        rows.append((stamp, equity))
        previous = stamp
    if not rows:
        raise ValueError('Equity CSV has no rows')
    return rows


def _weekdays(first, last):
    if last < first:
        return 0
    days = (last - first).days + 1
    full, rest = divmod(days, 7)
    return full * 5 + sum((first + timedelta(days=i)).weekday() < 5 for i in range(rest))


def ea_mean_dd(episodes):
    """The EA's MeanDD (money) from episode drawdowns, before the Return < 0 / zero rules."""
    dds = sorted(episodes, reverse=True)[:5] + [0.0] * 5
    if dds[0] == 0:
        return 999999.0
    if dds[1] == 0 or dds[1] < 0.1 * dds[0] or dds[1] < 0.5 * dds[0]:
        return dds[0]
    if dds[2] == 0 or dds[2] < 0.1 * dds[0] or dds[2] < 0.5 * dds[1]:
        return (dds[0] * 6 + dds[1] * 5) / 11
    if dds[3] == 0 or dds[3] < 0.1 * dds[0] or dds[3] < 0.5 * dds[2]:
        return (dds[0] * 7 + dds[1] * 6 + dds[2] * 5) / 18
    if dds[4] == 0 or dds[4] < 0.1 * dds[0] or dds[4] < 0.5 * dds[3]:
        return (dds[0] * 8 + dds[1] * 7 + dds[2] * 6 + dds[3] * 5) / 26
    return (dds[0] * 9 + dds[1] * 8 + dds[2] * 7 + dds[3] * 6 + dds[4] * 5) / 35


def equity_metrics(rows, first, last):
    """maxDd, ddPct, arf, sharpe, equityNet over [first, last] (inclusive days) from equity samples."""
    start = datetime.combine(first, datetime.min.time())
    end = datetime.combine(last + timedelta(days=1), datetime.min.time())
    before = [r for r in rows if r[0] < start]
    inside = [r for r in rows if start <= r[0] < end]
    if not inside:
        return None
    opening = before[-1][1] if before else inside[0][1]
    closing = inside[-1][1]
    peak, dd, dd_pct, episode, episodes = opening, 0.0, 0.0, 0.0, []
    for _, equity in inside:
        if equity > peak:
            if episode > 0:
                episodes.append(episode)
            peak, episode = equity, 0.0
        fall = peak - equity
        episode = max(episode, fall)
        dd = max(dd, fall)
        if peak > 0:
            dd_pct = max(dd_pct, fall / peak * 100)
    if episode > 0:
        episodes.append(episode)
    days = _weekdays(first, last)
    arf = None
    if opening > 0 and days > 0:
        ret = (closing - opening) / opening
        mean_dd = max(episodes) if ret < 0 and episodes else ea_mean_dd(episodes)
        if ret < 0 and not episodes:
            mean_dd = 0.0
        if mean_dd == 0:
            mean_dd = opening / 2
        arf = (ret / (mean_dd / opening)) / (days / 21.7)
    # Daily closes (Mon-Fri), carried forward; the first return is against the opening equity.
    closes, index, value = [], 0, opening
    day = first
    while day <= last:
        cut = datetime.combine(day + timedelta(days=1), datetime.min.time())
        while index < len(inside) and inside[index][0] < cut:
            value = inside[index][1]
            index += 1
        if day.weekday() < 5:
            closes.append(value)
        day += timedelta(days=1)
    returns, prior = [], opening
    for close in closes:
        if prior > 0:
            returns.append((close - prior) / prior)
        prior = close
    sharpe = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        if std > 0:
            sharpe = mean / std * math.sqrt(252)
    return dict(maxDd=round(dd, 8), ddPct=round(dd_pct, 8), arf=None if arf is None else round(arf, 8),
                sharpe=None if sharpe is None else round(sharpe, 8), equityNet=round(closing - opening, 8), days=days)


def _header_sum(windows, names, first, last):
    """Trades and PL summed from the EA's SET header window lines when they cover [first, last] exactly."""
    parts = [windows.get(name) for name in names]
    if not all(parts):
        return None
    spans = sorted((date.fromisoformat(p['start']), date.fromisoformat(p['end'])) for p in parts)
    if spans[0][0] != first or spans[-1][1] != last or any(b[0] > a[1] + timedelta(days=1) for a, b in zip(spans, spans[1:])):
        return None
    return dict(trades=sum(p['trades'] for p in parts), profit=round(sum(p['pl'] for p in parts), 8))


def window(rows, first, last, *, deals=None, header=None, header_names=()):
    """One window object (``FIELDS``)."""
    out = dict.fromkeys(FIELDS)
    out.update({'from': first.isoformat(), 'to': last.isoformat(), 'days': _weekdays(first, last)})
    measured = equity_metrics(rows, first, last)
    if measured:
        out.update(measured)
    if deals:
        from studio_catchup_verdict import deal_window
        counted = deal_window(deals, first, last)
        out.update(trades=counted['entries'], profit=round(counted['gross_win'] - counted['gross_loss'], 8), pf=counted['pf'],
                   pfNote=counted['pf_note'], tradeSource='capture_deals')
    elif header:
        summed = _header_sum(header, header_names, first, last)
        if summed:
            out.update(summed, pfNote='needs a complete capture', tradeSource='set_header')
    if out['profit'] is not None and out['maxDd']:
        out['recoveryFactor'] = round(out['profit'] / out['maxDd'], 8)
    return out


def boundaries(from_date, to_date, back_oos_date=None, include_back_oos=True):
    """(export start, SAMPLE start, optimization end) days from the MT5 tester/export dates."""
    def day(text):
        return datetime.strptime(text, '%Y.%m.%d').date() if '.' in text else date.fromisoformat(text)
    start, to_date = day(from_date), day(to_date)
    back = day(back_oos_date) if back_oos_date and include_back_oos else None
    export_start = back if back is not None and back < start else start
    return export_start, start, to_date - timedelta(days=1)


def export_window_metrics(set_path, *, from_date, to_date, back_oos_date=None, include_back_oos=True, csv_raw=None):
    """``preFoos``, ``selectionWindow`` and ``fullExport`` for one kept export unit (read only)."""
    from studio_evidence import parse_header, read_capture, unit_paths
    paths = unit_paths(set_path)
    raw = Path(paths['set']).read_bytes()
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    rows = equity_samples(csv_raw if csv_raw is not None else Path(paths['csv']).read_bytes())
    deals = None
    if Path(paths['goatseq']).is_dir():
        import hashlib
        try:
            capture = read_capture(paths['goatseq'], hashlib.sha256(raw).hexdigest())
        except (OSError, ValueError):
            capture = None
        candidate = Path(paths['goatseq']) / 'deals.csv'
        if capture and capture['complete'] and capture['set_binding_matches'] and candidate.is_file():
            deals = str(candidate)
    try:
        header = parse_header(text)
    except ValueError:
        header = {}
    export_start, sample_start, optimization_end = boundaries(from_date, to_date, back_oos_date, include_back_oos)
    last_sample = rows[-1][0].date()
    pre_names = ('BOOS', 'SAMPLE', 'FWD') if export_start < sample_start else ('SAMPLE', 'FWD')
    return dict(schema=SCHEMA, basis='controller_replay_of_export_csv_and_capture',
                preFoos=window(rows, export_start, optimization_end, deals=deals, header=header, header_names=pre_names),
                selectionWindow=window(rows, sample_start, optimization_end, deals=deals, header=header,
                                       header_names=('SAMPLE', 'FWD')),
                fullExport=window(rows, export_start, last_sample, deals=deals, header=header,
                                  header_names=pre_names + ('FOOS',)),
                optimizationEnd=optimization_end.isoformat(), foosStart=(optimization_end + timedelta(days=1)).isoformat(),
                tradeSource='capture_deals' if deals else 'set_header_or_none')
