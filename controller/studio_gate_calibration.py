"""Per-run qualification gates calibrated on our own export evidence (goat-gate-calibration-v2).

Read only. Every export folder this module touches is opened for reading; nothing
is written except the new plan plus its sidecar of ``stamp_plan`` (and the CLI's
explicit ``--output``).

What it does
------------
1. Loads exported sets (``<run>/deploy`` and ``<run>/exports``) whose sequence
   capture finished writing, with the run manifest's member windows.
2. Splits every set into windows (broker server time, half-open):
       back_oos  [BackOOSDate, FromDate)
       in_sample [FromDate, ForwardDate)
       forward   [ForwardDate, ToDate)
       post      [ToDate, end of the export run]
   Net and drawdown come from the exported equity curve; trades are positions
   opened in the window and PF covers only those positions (as in
   goat-catchup-verdict-v2).
3. Survival in a target window: forward/post need at least ``min_trades`` trades
   there and then net > 0; held_up uses goat-catchup-verdict-v2 verdicts
   (comparable, default rules) matched by the exported SET's SHA-256.
4. Statistics are selection aware:
   - outcomes are averaged per optimization member first (a member's sets are
     near copies), then counted per member;
   - intervals and the "does this metric predict survival" test are bootstrapped
     over runs (clusters), and the test compares survivors with failures inside
     the same run only, so differences between runs cannot fake a signal;
   - a threshold is chosen on one band that holds simultaneously across the whole
     threshold grid (run bootstrap, max deviation), never a per-point interval;
   - leave one run out: the whole selection is repeated without each run and
     judged on that run. A gate is only validated when the pooled held-out lower
     bound (the lowest of a cluster t interval, a design-effect Wilson interval and
     a run bootstrap) clears the target, enough runs were judged, and no run
     clearly contradicts it. The recommended threshold is the strictest one any fold
     chose for the same metric; when that threshold does not clear the full-data
     band the gate is not validated (fail closed, never the looser full-data value).
   - "validated" holds per evidence draw, not per gate: among gates that validate,
     a larger share is still slightly under the target (``VALIDATED_GATE_MISS``,
     measured by scripts/gate_calibration_coverage.py). Every summary, stamp and
     report says so.
5. Only the held_up target can change anything. Forward and post lie inside the
   export run the EA already judged, so they are diagnostics: they report what
   would validate but never move a plan field or stamp a qualification gate.
   Stamping only tightens: a plan's explicit values are never loosened.

Leakage rule (the key guard)
----------------------------
A predictor may only use data the target window could not have influenced:
- forward: in-sample and back-OOS metrics and the optimizer's in-sample columns;
  NOT the forward window, NOT the Score (built from in-sample and forward results)
  and NOT the file-name metrics (measured over the whole export run).
- post: also the forward window and the Score.
- held_up (weeks after the export): also the file-name metrics.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np

SCHEMA = 'goat-gate-calibration-v2'
STAMP_SCHEMA = 'goat-gate-stamp-v2'
VERDICT_SCHEMA = 'goat-catchup-verdict-v2'
WINDOWS = ('back_oos', 'in_sample', 'forward', 'post')
TARGETS = ('forward', 'post', 'held_up')
ACTIONABLE_TARGETS = ('held_up',)
CLUSTERS = ('run', 'period')
# Today's fixed gates: the export plan fields and the EA back-row filter.
DEFAULT_EXPORT = dict(MinScore=60.0, MinSR=2.5, MinARF=0.2, SetsToExport=2, TargetDD=100)
EXPORT_FLOORS = dict(MinScore=60.0, MinSR=2.5, MinARF=0.2, SetsToExport=2, TargetDD=100)
DEFAULT_QUALIFY = dict(is_trades=50, is_net=0.001)
JUDGED_VERDICTS = dict(held_up=True, weakened=False, failed=False)
UNJUDGED_VERDICTS = ('too_few_trades', 'not_comparable')
MIN_POST_WEEKDAYS = 10
MIN_TRADES = 5
MIN_CLUSTERS = 4
MAX_MANIFEST = 64 * 1024 * 1024
MAX_CSV = 64 * 1024 * 1024
MAX_XML = 32 * 1024 * 1024
MAX_SMALL = 1024 * 1024
BOOTSTRAP = 300
SEED = 20261002
ALPHA = 0.025  # one-sided: every lower bound here is a 97.5% lower bound (a 95% two-sided band)
NAME_METRICS = re.compile(r'_Trds=(\d+)_Prf=(-?[\d.]+)_DD=(-?[\d.]+)_PF=(-?[\d.]+)_SR=(-?[\d.]+)_ARF=(-?[\d.]+)$')
INDICATORS = ('RSI', 'EMA', 'ADX', 'BB', 'MACD', 'RSI2')
FX = {'USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD', 'SEK', 'NOK', 'DKK', 'SGD', 'HKD', 'MXN', 'ZAR', 'TRY', 'PLN', 'CNH'}
MAJORS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD'}
INDICES = {'WS30', 'US30', 'SP500', 'US500', 'SPX500', 'NDX', 'US100', 'USTEC', 'NAS100', 'GDAXI', 'DE40', 'GER40',
           'UK100', 'FTSE100', 'JP225', 'NI225', 'STOXX50', 'EU50', 'FRA40', 'AUS200', 'HK50', 'ESP35'}
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}

# name: (source window or kind, metric, allowed targets, plan field it can move on held_up)
FEATURES = {
    'is_net': ('in_sample', 'net', TARGETS, None),
    'is_trades': ('in_sample', 'trades', TARGETS, None),
    'is_pf': ('in_sample', 'pf', TARGETS, None),
    'is_recovery': ('in_sample', 'recovery', TARGETS, None),
    'is_sr': ('in_sample', 'sr', TARGETS, None),
    'is_arf': ('in_sample', 'arf', TARGETS, None),
    'boos_net': ('back_oos', 'net', TARGETS, None),
    'boos_pf': ('back_oos', 'pf', TARGETS, None),
    'boos_recovery': ('back_oos', 'recovery', TARGETS, None),
    'opt_is_sr': ('optimizer', 'SR(Back)', TARGETS, None),
    'opt_is_pf': ('optimizer', 'PF(Back)', TARGETS, None),
    'opt_is_rf': ('optimizer', 'RF(Back)', TARGETS, None),
    'opt_score': ('optimizer', 'Score', ('post', 'held_up'), 'MinScore'),
    'fwd_net': ('forward', 'net', ('post', 'held_up'), None),
    'fwd_pf': ('forward', 'pf', ('post', 'held_up'), None),
    'fwd_recovery': ('forward', 'recovery', ('post', 'held_up'), None),
    'file_sr': ('file_name', 'sr', ('held_up',), 'MinSR'),
    'file_arf': ('file_name', 'arf', ('held_up',), 'MinARF'),
    'file_pf': ('file_name', 'pf', ('held_up',), None),
}
# What "validated" guarantees, measured by scripts/gate_calibration_coverage.py (the
# test suite's model with correlated proxies, every chosen gate judged on fresh
# periods). Per draw: share of ALL evidence draws that validate a gate whose true
# survival is under the target. Per validated gate: that count among the draws that
# validated. The second is much larger; reports and stamps must say so.
def _miss_row(sigma, target, validated, below, bound_missed, evaluated, shortfall):
    return dict(run_shock_sigma=sigma, target=target, draws=4000, validated=validated, validated_below_target=below,
                bound_missed=bound_missed, evaluated=evaluated, per_draw=round(below / 4000, 4),
                per_validated_gate=round(below / validated, 4) if validated else None, shortfall_points=shortfall)


VALIDATED_GATE_MISS = dict(
    source='scripts/gate_calibration_coverage.py --draws 4000',
    rows=[_miss_row(0.0, 0.9, 447, 13, 31, 2828, [0.1, 2.5]), _miss_row(0.5, 0.9, 308, 15, 56, 2528, [0.0, 5.0]),
          _miss_row(0.8, 0.9, 209, 27, 55, 2184, [0.1, 2.7]), _miss_row(0.0, 0.8, 1780, 0, 10, 3925, None),
          _miss_row(0.5, 0.8, 1158, 2, 23, 3916, [0.1, 0.5]), _miss_row(0.8, 0.8, 716, 8, 32, 3887, [0.1, 1.2])],
    # Claude-Mac's independent simulation in the #119 v2 approval (1,000 draws per row,
    # target 90%, run shock sigma 0/0.5/0.8): 1/21, 4/23, 7/19 validated gates short.
    review=dict(source='Claude-Mac #119 review simulation', per_draw_max=0.007, per_validated_gate_max=0.37,
                shortfall_points_max=5.5))


def validation_meaning(min_survival=None):
    """The disclosure that travels with every recommendation, summary, stamp and report."""
    rows = VALIDATED_GATE_MISS['rows']
    if min_survival is not None and any(r['target'] == min_survival for r in rows):
        rows = [r for r in rows if r['target'] == min_survival]
    review = VALIDATED_GATE_MISS['review']
    per_draw = max((r['per_draw'] for r in rows), default=0.0)
    per_gate = max((r['per_validated_gate'] for r in rows if r['per_validated_gate'] is not None), default=0.0)
    shortfall = max((r['shortfall_points'][1] for r in rows if r['shortfall_points']), default=0.0)
    text = ('"Validated" holds per draw, not per gate. In simulation (%s), at most %.1f%% of evidence draws validated a '
            'gate whose true survival on fresh periods was under the target, but among the gates that validated, up to '
            '%.0f%% were still under it (by at most %.1f points); %s found up to %.0f%% (by at most %.1f points). Gates '
            'only tighten and only from held_up, so a miss over-tightens rather than loosens.'
            % (VALIDATED_GATE_MISS['source'], 100 * per_draw, 100 * per_gate, shortfall, review['source'],
               100 * review['per_validated_gate_max'], review['shortfall_points_max']))
    return dict(scope='per_draw_not_per_gate', text=text, per_draw_max=per_draw, per_validated_gate_max=per_gate,
                shortfall_points_max=shortfall, review=dict(review),
                simulation=dict(source=VALIDATED_GATE_MISS['source'], rows=rows))


SURVIVAL_DEFINITION = {
    'forward': 'at least min_trades positions opened in [ForwardDate, ToDate) and equity net > 0 there',
    'post': 'at least min_trades positions opened in [ToDate, end of the export run) (>= 10 weekdays) and equity net > 0',
    'held_up': 'goat-catchup-verdict-v2 verdict held_up (weakened/failed = not; too_few_trades/not_comparable unjudged)',
}


# ---------------------------------------------------------------- reading
def _read(path, limit):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('File exceeds its read limit: ' + path.name)
    return raw


def _decode(raw):
    return raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')


def _text(path, limit=MAX_CSV):
    return _decode(_read(path, limit))


def _json(path, limit=MAX_SMALL):
    return json.loads(_text(path, limit))


def _keyvalues(path):
    rows = {}
    for line in _text(path, MAX_SMALL).splitlines()[1:]:
        key, _, value = line.partition(',')
        rows[key] = value
    return rows


def _set_values(path):
    values = {}
    for line in _text(path, MAX_SMALL).splitlines():
        line = line.strip()
        if not line or line.startswith(';') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        values[key.strip()] = value.split('||', 1)[0].strip()
    return values


def day(text):
    return datetime.strptime(text, '%Y.%m.%d').date()


def msc(value):
    """Broker wall-clock date/datetime as the capture's unix-ms encoding."""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def weekdays(first, end):
    """Mon-Fri days in [first, end)."""
    count, current = 0, first
    while current < end:
        count += current.weekday() < 5
        current += timedelta(days=1)
    return count


def windows_for(tester, back_oos_date, observed_end_msc):
    observed_end = datetime.fromtimestamp(observed_end_msc / 1000, tz=timezone.utc).date() + timedelta(days=1)
    start, forward, to = day(tester['FromDate']), day(tester['ForwardDate']), day(tester['ToDate'])
    result = dict(in_sample=(start, forward), forward=(forward, to))
    if back_oos_date and day(back_oos_date) < start:
        result['back_oos'] = (day(back_oos_date), start)
    if observed_end > to:
        result['post'] = (to, observed_end)
    return result


def symbol_class(symbol):
    base = re.sub(r'[^A-Z0-9]', '', symbol.upper())
    if base[:3] in ('XAU', 'XAG', 'XPT', 'XPD') or base.startswith(('GOLD', 'SILVER')):
        return 'metals'
    if base in INDICES:
        return 'indices'
    if len(base) >= 6 and base[:3] in FX and base[3:6] in FX:
        return 'fx_majors' if base[:6] in MAJORS else 'fx_crosses'
    return 'other'


def strategy_profile(values):
    active = [name for name in INDICATORS if values.get(name + '_Mode', '0') not in ('0', '')]
    frames = []
    for name in active:
        try:
            frames.append(int(float(values.get(name + '_TF_', ''))))
        except ValueError:
            pass
    return '+'.join(active) or 'none', ('TF%d' % min(frames)) if frames else 'unknown'


def deals(text):
    """(msc, deal_entry, position_id, result) of buy/sell deals, sorted by time."""
    rows = []
    lines = text.splitlines()
    header = lines[0].split(',') if lines else []
    need = ('server_time_msc', 'position_id', 'deal_type', 'deal_entry', 'profit', 'commission', 'fee', 'swap')
    if any(name not in header for name in need):
        raise ValueError('Unexpected deals.csv header')
    index = {name: header.index(name) for name in need}
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) < len(header):
            continue
        if parts[index['deal_type']] not in ('0', '1'):
            continue
        result = sum(float(parts[index[key]] or 0) for key in ('profit', 'commission', 'fee', 'swap'))
        rows.append((int(parts[index['server_time_msc']]), int(parts[index['deal_entry']]),
                     parts[index['position_id']], result))
    rows.sort(key=lambda row: row[0])
    return rows


def equity(text):
    rows = []
    lines = text.splitlines()
    if not lines or lines[0] != '<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>':
        raise ValueError('Unexpected equity CSV header')
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) != 4:
            continue
        rows.append((datetime.strptime(parts[0], '%Y.%m.%d %H:%M'), float(parts[2])))
    if not rows:
        raise ValueError('Empty equity CSV')
    return rows


# ---------------------------------------------------------------- per-window metrics
def window_metrics(deal_rows, equity_rows, first, end, initial, deals_until=None):
    """Metrics for [first, end) from deals (trades, PF) and sampled equity (net, dd, Sharpe).

    Trades are positions opened in the window; PF covers only those positions'
    deals inside the window (closes of earlier positions count in net, not PF), as in
    goat-catchup-verdict-v2. ``deals_until``: msc where an incomplete capture stopped;
    trades and PF of a window it does not fully cover are unknown (None).
    """
    lo, hi = msc(first), msc(end)
    covered = deals_until is None or deals_until >= hi
    inside = [row for row in deal_rows if lo <= row[0] < hi]
    opened = {row[2] for row in inside if row[1] == 0}
    entries = sum(1 for row in inside if row[1] == 0) if covered else None
    results = [row[3] for row in inside if row[2] in opened]
    wins = sum(value for value in results if value > 0)
    losses = -sum(value for value in results if value < 0)
    pf = min(wins / losses, 25.0) if (covered and losses > 0) else None
    start_dt, end_dt = datetime.combine(first, datetime.min.time()), datetime.combine(end, datetime.min.time())
    opening = initial
    for stamp, value in equity_rows:
        if stamp >= start_dt:
            break
        opening = value
    level, peak, dd = opening, opening, 0.0
    closes_by_day = {}
    for stamp, value in equity_rows:
        if stamp < start_dt:
            continue
        if stamp >= end_dt:
            break
        level = value
        peak = max(peak, value)
        dd = max(dd, peak - value)
        closes_by_day[stamp.date()] = value
    net = level - opening
    days = weekdays(first, end)
    returns, previous, current = [], opening, first
    while current < end:
        value = closes_by_day.get(current, previous)
        if current.weekday() < 5:
            returns.append((value - previous) / initial)
        previous = value
        current += timedelta(days=1)
    sr = None
    if len(returns) >= 5:
        mean = sum(returns) / len(returns)
        var = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        if var > 0:
            sr = max(min(mean / math.sqrt(var) * math.sqrt(252), 25.0), -25.0)
    recovery = (net / dd) if dd > 0 else (25.0 if net > 0 else None)
    recovery = None if recovery is None else max(min(recovery, 25.0), -25.0)
    arf = None if recovery is None or not days else recovery / (days / 21.7)
    return dict(first_day=first.isoformat(), end_day=end.isoformat(), weekdays=days, trades=entries,
                closes=sum(1 for row in inside if row[1] in (1, 2, 3)) if covered else None,
                net=round(net, 2), dd=round(dd, 2), pf=None if pf is None else round(pf, 4),
                recovery=None if recovery is None else round(recovery, 4),
                sr=None if sr is None else round(sr, 4), arf=None if arf is None else round(arf, 4))


# ---------------------------------------------------------------- optimizer rows
def _xml_rows(path):
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
    # MT5 writes UTF-16 bodies that still declare UTF-8; parse the decoded text.
    text = _decode(_read(path, MAX_XML))
    root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', text))
    rows = []
    for row in root.iterfind('.//ss:Worksheet/ss:Table/ss:Row', ns):
        rows.append([(cell.find('ss:Data', ns).text if cell.find('ss:Data', ns) is not None else '')
                     for cell in row.iterfind('ss:Cell', ns)])
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, row)) for row in rows[1:]]


def optimizer_rows(run_dir, alias, symbol):
    folder = Path(run_dir) / 'reports' / alias / symbol
    if not folder.is_dir():
        return []
    for pattern in ('*_UniqueRows_Score=*.xml', '*_CombinedRows_Score=*.xml'):
        files = sorted(folder.glob(pattern))
        if files:
            try:
                return _xml_rows(files[0])
            except (ET.ParseError, ValueError, OSError):
                return []
    return []


def _same(left, right):
    try:
        return abs(float(left) - float(right)) <= 1e-6 * max(1.0, abs(float(left)))
    except (TypeError, ValueError):
        return str(left).strip().lower() == str(right).strip().lower()


def match_optimizer_row(rows, optimized):
    """The optimizer row with these optimized input values, else None (ambiguity -> None)."""
    if not rows or not optimized:
        return None
    hits = [row for row in rows if all(key in row and _same(row[key], value) for key, value in optimized.items())]
    if not hits:
        return None
    scores = {row.get('Score') for row in hits}
    return hits[0] if len(scores) == 1 else None


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------- loading runs
def discover_runs(common_root):
    root = Path(common_root)
    found = []
    for run in sorted(root.glob('R*')):
        if not run.is_dir() or not (run / 'manifest.json').is_file():
            continue
        if any(True for _ in _goatseq_dirs(run)):
            found.append(run.name)
    return found


def _goatseq_dirs(run):
    for area in ('deploy', 'exports'):
        base = Path(run) / area
        if not base.is_dir():
            continue
        for member in sorted(base.iterdir()):
            if not member.is_dir():
                continue
            for symbol in sorted(member.iterdir()):
                if not symbol.is_dir():
                    continue
                for item in sorted(symbol.iterdir()):
                    if item.is_dir() and item.name.endswith('.goatseq'):
                        yield area, member.name, symbol.name, item


def is_filler(file_metrics, settings):
    """True when the EA exported the set below its own run's MinSR/MinARF (to fill SetsToExport).

    A label only: fillers stay in the evidence until a within-run held_up comparison
    shows they do worse."""
    if file_metrics is None:
        return None
    min_sr = float(settings.get('MinSR', DEFAULT_EXPORT['MinSR']))
    min_arf = float(settings.get('MinARF', DEFAULT_EXPORT['MinARF']))
    return not (file_metrics['sr'] >= min_sr and file_metrics['arf'] >= min_arf)


def load_run(run_dir):
    """Records for every finished sequence capture of one run, plus skipped reasons."""
    run_dir = Path(run_dir)
    manifest = json.loads(_text(run_dir / 'manifest.json', MAX_MANIFEST))
    settings = manifest.get('export_settings') or {}
    jobs = {job['run_alias']: job for job in manifest.get('jobs', [])}
    records, skipped = [], []
    xml_cache = {}
    for area, alias, symbol, folder in _goatseq_dirs(run_dir):
        label = '%s/%s/%s/%s' % (run_dir.name, area, alias, folder.name)
        try:
            job = jobs.get(alias)
            if job is None:
                raise ValueError('member not in the run manifest')
            completion = _keyvalues(folder / 'completion.csv')
            if completion.get('footer') != 'END':
                raise ValueError('sequence capture still being written')
            complete = completion.get('tester_finished') == 'true' and not completion.get('error')
            capture = _json(folder / 'manifest.json')
            csv_name = Path(capture['exports']['csv']['path']).name
            set_name = Path(capture['exports']['set']['path']).name
            sibling_csv, sibling_set = folder.parent / csv_name, folder.parent / set_name
            initial = float(capture.get('initialEquity') or 100000.0)
            deals_raw, equity_raw = _read(folder / 'deals.csv', MAX_CSV), _read(sibling_csv, MAX_CSV)
            deal_rows, equity_rows = deals(_decode(deals_raw)), equity(_decode(equity_raw))
            # The tester's equity CSV covers the whole export run even when the sequence
            # capture hit its row limit; that capture only bounds trade counts and PF.
            observed_end = msc(equity_rows[-1][0])
            deals_until = None if complete else int(completion['observed_end_server_msc'])
            back_oos = settings.get('BackOOSDate') if settings.get('IncludeBackOOS', True) else None
            windows = windows_for(job['tester'], back_oos, observed_end)
            values = _set_values(folder / 'effective-inputs.set')
            optimized = _set_values(folder / 'source-inputs.set') if (folder / 'source-inputs.set').is_file() else {}
            family, timeframe = strategy_profile(values)
            # Identical evidence only: the same inputs AND byte-identical captures.
            identity = hashlib.sha256(json.dumps(
                [symbol, sorted((k, v) for k, v in values.items() if k != 'EA_Desc'),
                 hashlib.sha256(deals_raw).hexdigest(), hashlib.sha256(equity_raw).hexdigest()],
                separators=(',', ':')).encode()).hexdigest()
            metrics = {name: window_metrics(deal_rows, equity_rows, first, end, initial, deals_until)
                       for name, (first, end) in windows.items()}
            match = NAME_METRICS.search(folder.name[:-len('.goatseq')])
            file_metrics = None if not match else dict(
                trades=int(match[1]), net=float(match[2]), dd=float(match[3]), pf=float(match[4]),
                sr=float(match[5]), arf=float(match[6]))
            if alias not in xml_cache:
                xml_cache[alias] = optimizer_rows(run_dir, alias, symbol)
            row = match_optimizer_row(xml_cache[alias], optimized)
            optimizer = None if row is None else {key: _number(row.get(key)) for key in
                                                  ('Score', 'SR(Back)', 'PF(Back)', 'RF(Back)', 'Trades(Back)', 'Profit(Back)')}
            is_months = weekdays(*windows['in_sample']) / 21.7
            tester = job['tester']
            records.append(dict(
                run=run_dir.name, area=area, member=alias, member_key=run_dir.name + '/' + alias, symbol=symbol,
                path=label, set_sha256=hashlib.sha256(_read(sibling_set, MAX_SMALL)).hexdigest(), identity=identity,
                symbol_class=symbol_class(symbol), family=family, timeframe=timeframe,
                design='IS%.0fm/F%.0fw/B%.0fw' % (is_months, weekdays(*windows['forward']) / 5,
                                                 weekdays(*windows['back_oos']) / 5 if 'back_oos' in windows else 0),
                period='%s|%s|%s|%s' % (back_oos or '-', tester['FromDate'], tester['ForwardDate'], tester['ToDate']),
                windows=metrics, file_name=file_metrics, optimizer=optimizer,
                filler=is_filler(file_metrics, settings),
                capture='complete' if complete else 'partial',
                observed_end=datetime.fromtimestamp(observed_end / 1000, tz=timezone.utc).date().isoformat()))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            skipped.append(dict(path=label, reason=str(exc) or type(exc).__name__))
    return dict(run=run_dir.name, export_settings=settings, records=records, skipped=skipped)


def load_evidence(common_root, runs=None):
    runs = list(runs) if runs else discover_runs(common_root)
    loaded = [load_run(Path(common_root) / run) for run in runs]
    seen, records, duplicates = set(), [], 0
    # deploy before exports, then run order: only byte-identical evidence collapses.
    for area in ('deploy', 'exports'):
        for run in loaded:
            for record in run['records']:
                if record['area'] != area:
                    continue
                if record['identity'] in seen:
                    duplicates += 1
                    continue
                seen.add(record['identity'])
                records.append(record)
    records.sort(key=lambda r: (r['run'], r['member'], r['set_sha256'], r['path']))
    return dict(runs=[dict(run=run['run'], export_settings=run['export_settings'], sets=len(run['records']),
                           fillers=sum(1 for r in run['records'] if r['filler']),
                           skipped=len(run['skipped']), skipped_examples=run['skipped'][:5]) for run in loaded],
                records=records, duplicates_removed=duplicates)


def load_verdicts(path):
    """{set_sha256: verdict record} from goat-catchup-verdict-v2 records in a JSON/JSONL file or folder.

    Accepted only: schema goat-catchup-verdict-v2, a whitelisted verdict, a comparable
    re-test (``comparability.comparable`` true, except the explicit not_comparable
    verdict which is kept as unjudged), and the default rules (nothing overridden).
    For one SET the verdict with the newest evidence end wins. Returns
    (verdicts, rejected counts by reason)."""
    path = Path(path)
    files = sorted(path.rglob('*.json*')) if path.is_dir() else [path]
    found, rejected = {}, {}

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    def consider(node):
        if node.get('schema') != VERDICT_SCHEMA:
            return reject('schema is not ' + VERDICT_SCHEMA)
        verdict = node.get('verdict')
        if verdict not in JUDGED_VERDICTS and verdict not in UNJUDGED_VERDICTS:
            return reject('unknown verdict')
        rules = node.get('rules') or {}
        if rules.get('id') != VERDICT_SCHEMA or rules.get('overridden'):
            return reject('rules overridden or missing')
        comparable = (node.get('comparability') or {}).get('comparable')
        if verdict != 'not_comparable' and comparable is not True:
            return reject('not comparable')
        sha = (node.get('original') or {}).get('set_sha256')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            return reject('missing original set_sha256')
        end = str((node.get('retest') or {}).get('evidence_end') or '')
        entry = dict(verdict=verdict, evidence_end=end, confidence=node.get('confidence'),
                     key=hashlib.sha256(json.dumps(node, sort_keys=True, default=str).encode()).hexdigest())
        prior = found.get(sha)
        if prior is None or (entry['evidence_end'], entry['key']) > (prior['evidence_end'], prior['key']):
            found[sha] = entry

    def walk(node):
        if isinstance(node, dict):
            if 'verdict' in node and 'original' in node:
                consider(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for file in files:
        text = _text(file, MAX_MANIFEST)
        try:
            walk(json.loads(text))
        except json.JSONDecodeError:
            for line in text.splitlines():
                if line.strip():
                    walk(json.loads(line))
    return found, rejected


# ---------------------------------------------------------------- outcomes and features
def outcome(record, target, verdicts=None, min_trades=MIN_TRADES):
    """True/False survival in the target window, or None when it cannot be judged."""
    if target == 'held_up':
        entry = (verdicts or {}).get(record['set_sha256'])
        if entry is None:
            return None
        verdict = entry['verdict'] if isinstance(entry, dict) else entry
        return JUDGED_VERDICTS.get(verdict)
    window = record['windows'].get(target)
    if window is None:
        return None
    if target == 'post' and window['weekdays'] < MIN_POST_WEEKDAYS:
        return None
    if target == 'forward' and record['observed_end'] < (date.fromisoformat(window['end_day']) - timedelta(days=1)).isoformat():
        return None
    if window.get('trades') is None or window['trades'] < min_trades:
        return None
    return window['net'] > 0


def feature(record, name, target):
    """Feature value, refusing any source the target window could have influenced."""
    source, metric, allowed, _ = FEATURES[name]
    if target not in allowed:
        raise ValueError('Feature %s would leak the %s window into its own calibration' % (name, target))
    if source == 'optimizer':
        return None if record.get('optimizer') is None else record['optimizer'].get(metric)
    if source == 'file_name':
        return None if record.get('file_name') is None else record['file_name'].get(metric)
    if source == target:
        raise ValueError('Feature %s reads the target window' % name)
    window = record['windows'].get(source)
    return None if window is None else window.get(metric)


def allowed_features(target):
    return [name for name, spec in FEATURES.items() if target in spec[2]]


def plan_field(name, target):
    """The plan field a gate on this feature may move: only for an actionable target."""
    return FEATURES[name][3] if target in ACTIONABLE_TARGETS else None


# ---------------------------------------------------------------- statistics
def wilson(successes, n, z=1.96):
    if n <= 0:
        return (0.0, 1.0)
    p = min(max(successes / n, 0.0), 1.0)
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def t975(df):
    if df < 1:
        return float('inf')
    return T975.get(df, 2.0 if df <= 60 else 1.98 if df <= 120 else 1.96)


def cluster_ratio_interval(sums, counts):
    """Cluster-robust t interval for a pooled ratio sum(S)/sum(N) with one term per cluster."""
    sums, counts = np.asarray(sums, float), np.asarray(counts, float)
    keep = counts > 0
    sums, counts = sums[keep], counts[keep]
    k = len(counts)
    if k < 2 or counts.sum() <= 0:
        return (0.0, 1.0)
    rate = sums.sum() / counts.sum()
    residual = sums - rate * counts
    se = math.sqrt(k / (k - 1) * float((residual ** 2).sum())) / counts.sum()
    half = t975(k - 1) * se
    return (max(0.0, rate - half), min(1.0, rate + half))


def clustered_wilson(sums, counts):
    """Wilson score interval on the design-effect sample size (Kish).

    A cluster t interval is too narrow when the rate is near 1 and the few clusters
    happen to agree (the sampling distribution is skewed there). The score interval
    handles the boundary; deflating n by the observed design effect (never below 1)
    pays for the clustering. Callers take the lower of this and the t interval."""
    sums, counts = np.asarray(sums, float), np.asarray(counts, float)
    keep = counts > 0
    sums, counts = sums[keep], counts[keep]
    k, total = len(counts), float(counts.sum())
    if k < 2 or total <= 0:
        return (0.0, 1.0)
    rate = float(sums.sum()) / total
    residual = sums - rate * counts
    cluster_var = k / (k - 1) * float((residual ** 2).sum()) / (total * total)
    binomial_var = rate * (1 - rate) / total
    # Every member survived (or none did): no spread to read, members count as is.
    deff = max(1.0, cluster_var / binomial_var) if binomial_var > 0 else 1.0
    return wilson(rate * total / deff, total / deff)


def isotonic(values, weights=None):
    """Pool-adjacent-violators: the closest non-decreasing sequence (weighted least squares)."""
    weights = weights or [1.0] * len(values)
    blocks = []
    for value, weight in zip(values, weights):
        blocks.append([value * weight, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, mass, count = blocks.pop()
            blocks[-1][0] += total; blocks[-1][1] += mass; blocks[-1][2] += count
    fitted = []
    for total, mass, count in blocks:
        fitted.extend([total / mass] * count)
    return fitted


def _pair_wins(positives, negatives):
    """(wins, pairs): survivor value above failure value, ties half."""
    import bisect
    negatives = sorted(negatives)
    wins = 0.0
    for value in positives:
        below = bisect.bisect_left(negatives, value)
        wins += below + (bisect.bisect_right(negatives, value) - below) / 2
    return wins, float(len(positives) * len(negatives))


def candidate_thresholds(values, extra=()):
    values = sorted(value for value in values if value is not None)
    if not values:
        return []
    grid = {values[min(len(values) - 1, int(q * len(values) / 20))] for q in range(0, 19)}
    grid.update(value for value in extra if value is not None)
    return sorted({_round(value) for value in grid})


def _round(value):
    if value == 0 or abs(value) >= 100:
        return round(value, 0) if abs(value) >= 100 else 0.0
    digits = max(0, 3 - int(math.floor(math.log10(abs(value)))))
    return round(value, digits)


def boot_matrix(include, resamples=BOOTSTRAP, seed=SEED):
    """Cluster bootstrap weights: rows are resamples, columns clusters (0 when excluded)."""
    include = np.asarray(include, bool)
    chosen = np.flatnonzero(include)
    weights = np.zeros((resamples, len(include)))
    if len(chosen) == 0:
        return weights
    rng = np.random.default_rng(seed + int(hashlib.sha256(include.tobytes()).hexdigest()[:8], 16))
    draws = rng.integers(0, len(chosen), size=(resamples, len(chosen)))
    for column, cluster in enumerate(chosen):
        weights[:, cluster] = (draws == column).sum(axis=1)
    return weights


class FeatureData:
    """Per-cluster, per-threshold member-aggregated counts of one feature."""

    def __init__(self, name, target, labelled, cluster_names, cluster_of):
        self.name = name
        self.plan_field = plan_field(name, target)
        rows = [(cluster_of(r), r['member_key'], feature(r, name, target), hit) for r, hit in labelled]
        present = [row for row in rows if row[2] is not None]
        default = DEFAULT_QUALIFY.get(name)
        extra = [default, DEFAULT_EXPORT.get(self.plan_field) if self.plan_field else None]
        self.thresholds = candidate_thresholds([row[2] for row in present], extra)
        self.coverage = len(present)
        index = {name_: i for i, name_ in enumerate(cluster_names)}
        C, T = len(cluster_names), len(self.thresholds)
        self.S, self.N, self.K = np.zeros((C, T)), np.zeros((C, T)), np.zeros((C, T))
        self.wins, self.pairs = np.zeros(C), np.zeros(C)
        thresholds = np.asarray(self.thresholds, float)
        members = {}
        for cluster, member, value, hit in present:
            members.setdefault((index[cluster], member), []).append((value, hit))
        for (c, _), sets in members.items():
            values = np.array([v for v, _ in sets], float)
            hits = np.array([1.0 if h else 0.0 for _, h in sets])
            kept = values[None, :] >= thresholds[:, None]
            k = kept.sum(axis=1)
            has = k > 0
            self.S[c, has] += (kept * hits[None, :]).sum(axis=1)[has] / k[has]
            self.N[c, has] += 1
            self.K[c] += k
        by_cluster = {}
        for cluster, _, value, hit in present:
            by_cluster.setdefault(index[cluster], ([], []))[0 if hit else 1].append(value)
        for c, (positives, negatives) in by_cluster.items():
            self.wins[c], self.pairs[c] = _pair_wins(positives, negatives)
        # Weights so set-level points add up to one per member (for the monotone curve).
        self._points = sorted(((value, hit, 1.0 / len(members[(index[cluster], member)]))
                               for cluster, member, value, hit in present), key=lambda p: p[0])


def _evaluate(data, include, boot, settings):
    """Curve, simultaneous lower band and within-cluster signal of one feature on the included clusters."""
    w = np.asarray(include, float)
    S, N, K = w @ data.S, w @ data.N, w @ data.K
    with np.errstate(invalid='ignore', divide='ignore'):
        rate = np.where(N > 0, S / np.maximum(N, 1e-12), np.nan)
        clusters_kept = (data.N[np.asarray(include, bool)] > 0).sum(axis=0)
        eligible = (K >= settings['min_sets']) & (N >= settings['min_members']) & (clusters_kept >= 2)
        pairs = float(w @ data.pairs)
        auc = float(w @ data.wins) / pairs if pairs > 0 else None
        boot_pairs = boot @ data.pairs
        boot_auc = np.where(boot_pairs > 0, (boot @ data.wins) / np.maximum(boot_pairs, 1e-12), np.nan)
        auc_low = float(np.nanquantile(boot_auc, ALPHA)) if np.isfinite(boot_auc).any() else None
        auc_high = float(np.nanquantile(boot_auc, 1 - ALPHA)) if np.isfinite(boot_auc).any() else None
        band = np.full(len(data.thresholds), np.nan)
        if eligible.any():
            # Studentized (sup-t) simultaneous band over the run bootstrap: one critical
            # value for the whole grid, so picking the best threshold is paid for.
            Sb, Nb = boot @ data.S[:, eligible], boot @ data.N[:, eligible]
            rb = np.where(Nb > 0, Sb / np.maximum(Nb, 1e-12), 0.0)  # a resample with no kept member counts as 0
            spread = np.maximum(rb.std(axis=0, ddof=1), 1e-3)
            deviation = ((rate[eligible][None, :] - rb) / spread[None, :]).max(axis=1)
            critical = max(float(np.quantile(deviation, 1 - ALPHA)), 1.96)
            band[eligible] = rate[eligible] - critical * spread
    lower = np.full(len(data.thresholds), np.nan)
    for t in np.flatnonzero(eligible):
        lower[t] = min(band[t], wilson(S[t], N[t])[0])
    if auc_low is not None and auc_low > 0.5:
        direction = 'higher_is_better'
    elif auc_high is not None and auc_high < 0.5:
        direction = 'higher_is_worse'
    else:
        direction = 'no_clear_signal'
    return dict(S=S, N=N, K=K, rate=rate, eligible=eligible, lower=lower, auc=auc,
                auc_interval=None if auc_low is None else [auc_low, auc_high], direction=direction)


def _choose(datas, include, settings):
    """The selection procedure: loosest gate (most sets kept) on a metric with a clear
    within-run signal whose simultaneous lower band clears the target."""
    boot = boot_matrix(include, settings['resamples'])
    best, evaluated = None, {}
    for name, data in datas.items():
        result = _evaluate(data, include, boot, settings)
        evaluated[name] = result
        if result['direction'] != 'higher_is_better':
            continue
        floor = EXPORT_FLOORS.get(data.plan_field) if data.plan_field else None
        for t in np.flatnonzero(result['eligible']):
            if result['lower'][t] < settings['min_survival']:
                continue
            if floor is not None and data.thresholds[t] < floor:
                continue
            key = (result['K'][t], result['lower'][t], -data.thresholds[t])
            if best is None or key > best[0]:
                best = (key, name, int(t))
    return (None if best is None else (best[1], best[2])), evaluated


def pooled_interval(sums, counts, resamples=BOOTSTRAP):
    """Held-out survival interval over runs: the LOWEST lower bound of a cluster t
    interval, the design-effect Wilson interval and a percentile bootstrap over runs
    (each fails in a different corner: few runs, a rate near 1, skew)."""
    total = float(sum(counts))
    if len(sums) < 1 or total <= 0:
        return (0.0, 1.0)
    t_low, t_high = cluster_ratio_interval(sums, counts)
    w_low, w_high = clustered_wilson(sums, counts)
    boot_low = 0.0
    if len(sums) >= 2:
        weights = boot_matrix(np.ones(len(sums), bool), resamples, SEED + 1)
        bs, bn = weights @ np.asarray(sums, float), weights @ np.asarray(counts, float)
        boot_low = float(np.quantile(np.where(bn > 0, bs / np.maximum(bn, 1e-12), 0.0), ALPHA))
    return (min(t_low, w_low, boot_low), max(t_high, w_high))


def _validate(datas, clusters, settings, full_choice):
    """Leave one cluster out: rerun the whole selection without it, judge it on it."""
    folds = []
    all_in = np.ones(len(clusters), bool)
    for c, name in enumerate(clusters):
        if not any(data.N[c].max() > 0 for data in datas.values()):
            continue
        include = all_in.copy(); include[c] = False
        choice, _ = _choose(datas, include, settings)
        if choice is None:
            folds.append(dict(cluster=name, feature=None, threshold=None, kept_members=0, survivors=0.0, kept_sets=0))
            continue
        data, t = datas[choice[0]], choice[1]
        folds.append(dict(cluster=name, feature=choice[0], threshold=data.thresholds[t],
                          kept_members=int(data.N[c, t]), survivors=round(float(data.S[c, t]), 4),
                          kept_sets=int(data.K[c, t])))
    judged = [f for f in folds if f['feature'] is not None and f['kept_members'] > 0]
    sums = [f['survivors'] for f in judged]
    counts = [f['kept_members'] for f in judged]
    total = sum(counts)
    rate = sum(sums) / total if total else None
    lower, upper = pooled_interval(sums, counts, settings['resamples'])
    contradicted = []
    for f in judged:
        if f['kept_members'] >= settings['min_members'] and wilson(f['survivors'], f['kept_members'])[1] < settings['min_survival']:
            contradicted.append(f['cluster'])
    same = [f['threshold'] for f in judged if full_choice and f['feature'] == full_choice[0]]
    return dict(folds=folds, judged_clusters=len(judged), survival=None if rate is None else round(rate, 4),
                lower=round(lower, 4), interval=[round(lower, 4), round(upper, 4)],
                contradicted=contradicted, same_feature_thresholds=same,
                no_gate_clusters=[f['cluster'] for f in folds if f['feature'] is None])


def _baseline(labelled, clusters, cluster_of):
    index = {name: i for i, name in enumerate(clusters)}
    members = {}
    for record, hit in labelled:
        members.setdefault((index[cluster_of(record)], record['member_key']), []).append(1.0 if hit else 0.0)
    sums, counts = np.zeros(len(clusters)), np.zeros(len(clusters))
    for (c, _), hits in members.items():
        sums[c] += sum(hits) / len(hits)
        counts[c] += 1
    total = counts.sum()
    rate = sums.sum() / total if total else None
    w_low, w_high = clustered_wilson(sums, counts) if total else (0.0, 1.0)
    c_low, c_high = cluster_ratio_interval(sums, counts)
    return dict(sets=len(labelled), members=int(total), clusters=int((counts > 0).sum()),
                survivors=round(float(sums.sum()), 2), survival=None if rate is None else round(rate, 4),
                interval=[round(min(w_low, c_low), 4), round(max(w_high, c_high), 4)])


def _curve(data, result, total_sets):
    fitted = isotonic([1.0 if hit else 0.0 for _, hit, _ in data._points], [w for _, _, w in data._points])
    curve = []
    for t, threshold in enumerate(data.thresholds):
        kept = [(f, w) for (value, _, w), f in zip(data._points, fitted) if value >= threshold]
        mass = sum(w for _, w in kept)
        n, s = float(result['N'][t]), float(result['S'][t])
        curve.append(dict(threshold=threshold, kept_sets=int(result['K'][t]), kept_members=int(n),
                          yield_=round(result['K'][t] / total_sets, 4) if total_sets else 0.0,
                          survival=round(s / n, 4) if n else None,
                          survival_monotone=round(sum(f * w for f, w in kept) / mass, 4) if mass else None,
                          wilson=[round(x, 4) for x in wilson(s, n)] if n else None,
                          lower_band=None if math.isnan(result['lower'][t]) else round(float(result['lower'][t]), 4),
                          eligible=bool(result['eligible'][t])))
    return curve


def evidence_digest(labelled, target):
    rows = [[r['run'], r['member'], r['set_sha256'], hit,
             {name: feature(r, name, target) for name in allowed_features(target)}]
            for r, hit in labelled]
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return hashlib.sha256(json.dumps([SCHEMA, target, rows], sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


SPLIT_KEYS = ('symbol_class', 'design')


def recommend(records, *, target='forward', verdicts=None, min_survival=0.6, min_sets=20, min_members=8,
              min_trades=MIN_TRADES, min_clusters=MIN_CLUSTERS, cluster='run', resamples=BOOTSTRAP,
              split_keys=SPLIT_KEYS):
    """Validated gate for a new run, or today's values with the reason.

    Only ``held_up`` is actionable; forward and post return diagnostics with no value
    changes. ``cluster``: the independent unit for bootstraps and leave-one-out
    (``run``, or ``period`` = the exact market window, stricter).
    """
    if target not in TARGETS:
        raise ValueError('target must be one of: ' + ', '.join(TARGETS))
    if cluster not in CLUSTERS:
        raise ValueError('cluster must be one of: ' + ', '.join(CLUSTERS))
    if not 0 < min_survival < 1:
        raise ValueError('min_survival must be between 0 and 1')
    if type(min_trades) is not int or min_trades < 1:
        raise ValueError('min_trades must be a whole number of at least 1')
    settings = dict(min_survival=min_survival, min_sets=min_sets, min_members=min_members, min_trades=min_trades,
                    min_clusters=min_clusters, cluster=cluster, resamples=resamples)
    cluster_of = (lambda r: r['run']) if cluster == 'run' else (lambda r: r['period'])
    labelled = sorted(((r, outcome(r, target, verdicts, min_trades)) for r in records),
                      key=lambda item: (item[0]['run'], item[0]['member'], item[0]['set_sha256']))
    unjudged = sum(1 for _, hit in labelled if hit is None)
    labelled = [(r, hit) for r, hit in labelled if hit is not None]
    clusters = sorted({cluster_of(r) for r, _ in labelled})
    baseline = _baseline(labelled, clusters, cluster_of) if labelled else dict(
        sets=0, members=0, clusters=0, survivors=0, survival=None, interval=[0.0, 1.0])
    datas = {name: FeatureData(name, target, labelled, clusters, cluster_of) for name in allowed_features(target)}
    full_choice, evaluated = (None, {})
    if clusters:
        full_choice, evaluated = _choose(datas, np.ones(len(clusters), bool), settings)
    features = {}
    for name, data in datas.items():
        result = evaluated.get(name)
        features[name] = dict(source=FEATURES[name][0], metric=FEATURES[name][1], plan_field=data.plan_field,
                              coverage=data.coverage,
                              auc=None if not result or result['auc'] is None else round(result['auc'], 4),
                              auc_interval=None if not result or not result['auc_interval'] else
                              [round(x, 4) for x in result['auc_interval']],
                              direction=result['direction'] if result else 'no_clear_signal',
                              curve=_curve(data, result, len(labelled)) if result else [])
    reasons, gate, validation = [], None, None
    if baseline['sets'] < min_sets or baseline['members'] < min_members or baseline['clusters'] < min_clusters:
        status = 'fallback_thin_evidence'
        reasons.append('Only %d judged sets from %d members in %d independent %ss for the %s window (need %d sets, '
                       '%d members, %d %ss).' % (baseline['sets'], baseline['members'], baseline['clusters'], cluster,
                                                  target, min_sets, min_members, min_clusters, cluster))
    elif baseline['interval'][0] >= min_survival:
        status = 'defaults_already_meet_target'
        reasons.append('Without any extra gate, %.0f%% of members survived (lower bound %.0f%%), already at the %.0f%% '
                       'target.' % (100 * baseline['survival'], 100 * baseline['interval'][0], 100 * min_survival))
    elif full_choice is None:
        status = 'fallback_no_qualifying_gate'
        reasons.append('No gate on a metric with a clear within-%s signal lifted the simultaneous lower band to %.0f%% '
                       'while keeping %d sets from %d members.' % (cluster, 100 * min_survival, min_sets, min_members))
    else:
        validation = _validate(datas, clusters, settings, full_choice)
        name, t = full_choice
        data = datas[name]
        strictest = max([data.thresholds[t]] + validation['same_feature_thresholds'])
        t_final = data.thresholds.index(strictest)
        # Fail closed: when the strictest fold threshold does not clear the full-data
        # band, the gate is not validated. Never fall back to the looser full-data
        # threshold the folds did not support.
        strictest_ok = bool(evaluated[name]['eligible'][t_final]) and bool(evaluated[name]['lower'][t_final] >= min_survival)
        point = next(p for p in features[name]['curve'] if p['threshold'] == data.thresholds[t_final])
        gate = dict(feature=name, threshold=data.thresholds[t_final], plan_field=data.plan_field, point=point,
                    full_data_threshold=data.thresholds[t], strictest_fold_clears_full_data=strictest_ok)
        problems = []
        if not strictest_ok:
            problems.append('the strictest held-out fold threshold %s >= %s does not clear the full-data band (%s), and '
                            'the looser full-data threshold %s is never stamped in its place'
                            % (name, strictest, 'too few sets or members kept' if not point['eligible'] else
                               'lower band %s under the %.0f%% target' % (
                                   '-' if point['lower_band'] is None else '%.0f%%' % (100 * point['lower_band']),
                                   100 * min_survival), data.thresholds[t]))
        if validation['judged_clusters'] < min_clusters:
            problems.append('only %d held-out %ss could judge it (need %d)' % (validation['judged_clusters'], cluster,
                                                                                 min_clusters))
        if validation['lower'] < min_survival:
            problems.append('held-out survival %s with lower bound %.0f%% is under the %.0f%% target'
                            % ('-' if validation['survival'] is None else '%.0f%%' % (100 * validation['survival']),
                               100 * validation['lower'], 100 * min_survival))
        if validation['contradicted']:
            problems.append('held-out %s(s) %s clearly miss the target' % (cluster, ', '.join(validation['contradicted'])))
        if problems:
            status = 'fallback_not_validated'
            reasons.append('The best full-data gate (%s >= %s) failed leave-one-%s-out validation: %s.'
                           % (name, gate['threshold'], cluster, '; '.join(problems)))
        else:
            status = 'validated'
    actionable = status == 'validated' and target in ACTIONABLE_TARGETS
    export_changes, qualify = {}, dict(DEFAULT_QUALIFY)
    if actionable:
        if gate['plan_field']:
            export_changes[gate['plan_field']] = max(float(gate['threshold']), float(EXPORT_FLOORS[gate['plan_field']]))
        else:
            qualify[gate['feature']] = gate['threshold']
    splits = {key: _split_table(labelled, key) for key in ('symbol_class', 'family', 'timeframe', 'design', 'run', 'filler')}
    by_split = {}
    for key in split_keys or ():
        for group in sorted({str(r[key]) for r, _ in labelled}):
            subset = [r for r, _ in labelled if str(r[key]) == group]
            inner = recommend(subset, target=target, verdicts=verdicts, min_survival=min_survival, min_sets=min_sets,
                              min_members=min_members, min_trades=min_trades, min_clusters=min_clusters,
                              cluster=cluster, resamples=resamples, split_keys=())
            by_split['%s=%s' % (key, group)] = dict(
                status=inner['status'], actionable=inner['actionable'], baseline=inner['baseline'],
                reasons=inner['reasons'], validation=None if not inner['validation'] else dict(
                    survival=inner['validation']['survival'], lower=inner['validation']['lower'],
                    judged_clusters=inner['validation']['judged_clusters']),
                gate=None if inner['gate'] is None else dict(feature=inner['gate']['feature'],
                                                             threshold=inner['gate']['threshold']))
    split_qualify = {name: {info['gate']['feature']: info['gate']['threshold']}
                     for name, info in by_split.items()
                     if info['actionable'] and FEATURES[info['gate']['feature']][3] is None}
    digest = evidence_digest(labelled, target)
    result = dict(schema=SCHEMA, status=status, actionable=actionable, target=target,
                  survival_definition=SURVIVAL_DEFINITION[target], settings=settings, baseline=baseline,
                  unjudged_sets=unjudged, gate=gate, validation=validation, reasons=reasons,
                  values=dict(export_changes=export_changes, qualify=qualify if actionable else dict(DEFAULT_QUALIFY),
                              qualify_by_split=split_qualify),
                  current=dict(export=dict(DEFAULT_EXPORT), qualify=dict(DEFAULT_QUALIFY)),
                  validation_meaning=validation_meaning(min_survival),
                  features=features, splits=splits, by_split=by_split, evidence_digest=digest,
                  leakage_rule={name: list(FEATURES[name][2]) for name in FEATURES})
    result['summary'] = summarize(result)
    return result


def _split_table(labelled, key):
    groups = {}
    for record, hit in labelled:
        groups.setdefault(str(record[key]), []).append((record, hit))
    result = {}
    for name in sorted(groups):
        rows = groups[name]
        clusters = sorted({r['run'] for r, _ in rows})
        base = _baseline(rows, clusters, lambda r: r['run'])
        result[name] = dict(sets=base['sets'], members=base['members'], runs=base['clusters'],
                            survival=base['survival'], interval=base['interval'])
    return result


def summarize(result):
    target, baseline, settings = result['target'], result['baseline'], result['settings']
    lines = []
    if baseline['survival'] is None:
        lines.append('No set could be judged on the %s window.' % target)
    else:
        lines.append('%d sets from %d members in %d %ss could be judged on the %s window (%s); %.0f%% of members '
                     'survived (95%% range %.0f-%.0f%%, member- and %s-robust).'
                     % (baseline['sets'], baseline['members'], baseline['clusters'], settings['cluster'], target,
                        SURVIVAL_DEFINITION[target], 100 * baseline['survival'], 100 * baseline['interval'][0],
                        100 * baseline['interval'][1], settings['cluster']))
    if result['unjudged_sets']:
        lines.append('%d more sets could not be judged (too few trades, unknown trade count or no verdict).'
                     % result['unjudged_sets'])
    gate, validation = result['gate'], result['validation']
    if result['status'] == 'validated':
        point = gate['point']
        lines.append('Validated gate: %s >= %s keeps %d sets (%d members); held out one %s at a time, %.0f%% of the '
                     'members it kept survived (lower bound %.0f%%, %d %ss judged), meeting the %.0f%% target.'
                     % (gate['feature'], gate['threshold'], point['kept_sets'], point['kept_members'], settings['cluster'],
                        100 * validation['survival'], 100 * validation['lower'], validation['judged_clusters'],
                        settings['cluster'], 100 * settings['min_survival']))
        lines.append(result['validation_meaning']['text'])
        if result['actionable']:
            lines.append('It sets the plan field %s (only ever tightening).' % gate['plan_field'] if gate['plan_field']
                         else 'It is a portfolio qualification gate; export plan fields are unchanged.')
        else:
            lines.append('This is a diagnostic: the %s window lies inside the export run the EA already judged, so '
                         'nothing is changed or stamped. Only held_up verdicts can move gates.' % target)
    else:
        lines.append('Keeping the current gates. ' + ' '.join(result['reasons']))
    inverse = sorted(name for name, info in result['features'].items() if info['direction'] == 'higher_is_worse')
    if inverse:
        lines.append('Within the same %s, higher values did worse for: %s (never tighten on these).'
                     % (settings['cluster'], ', '.join(inverse)))
    calibrated = ['%s: %s >= %s' % (name, info['gate']['feature'], info['gate']['threshold'])
                  for name, info in sorted(result['by_split'].items()) if info['status'] == 'validated']
    if calibrated:
        lines.append('Split gates that validate on their own: %s.' % '; '.join(calibrated))
    thin = [name for name, info in sorted(result['by_split'].items()) if info['status'] == 'fallback_thin_evidence']
    if thin:
        lines.append('Splits too thin to calibrate alone: %s.' % ', '.join(thin))
    lines.append('Leakage rule: forward-window, Score and file-name metrics never predict a window they contain.')
    return ' '.join(lines)


# ---------------------------------------------------------------- fillers
def filler_comparison(records, verdicts, resamples=BOOTSTRAP):
    """Passed vs filler sets on held_up only, inside each run x symbol (Mantel-Haenszel
    risk difference, run bootstrap). Fillers are labelled, never excluded here."""
    counts = {}
    for r in records:
        row = counts.setdefault(r['run'], dict(sets=0, fillers=0, unknown=0))
        row['sets'] += 1
        if r['filler']:
            row['fillers'] += 1
        elif r['filler'] is None:
            row['unknown'] += 1
    judged = [(r, outcome(r, 'held_up', verdicts)) for r in records if r['filler'] is not None]
    judged = [(r, hit) for r, hit in judged if hit is not None]
    strata = {}
    for r, hit in judged:
        cell = strata.setdefault((r['run'], r['symbol']), [0, 0, 0, 0])  # passed n, passed hits, filler n, filler hits
        offset = 2 if r['filler'] else 0
        cell[offset] += 1
        cell[offset + 1] += 1 if hit else 0
    usable = {key: cell for key, cell in strata.items() if cell[0] and cell[2]}
    if not usable:
        return dict(status='no_held_up_verdicts' if not judged else 'no_run_symbol_with_both',
                    per_run=counts, judged_sets=len(judged))

    def mh(cells):
        top = bottom = 0.0
        for n1, a, n0, c in cells:
            total = n1 + n0
            top += (a * n0 - c * n1) / total
            bottom += n1 * n0 / total
        return top / bottom if bottom else None
    estimate = mh(usable.values())
    runs = sorted({key[0] for key in usable})
    by_run = {run: [cell for key, cell in usable.items() if key[0] == run] for run in runs}
    weights = boot_matrix(np.ones(len(runs), bool), resamples, SEED + 2)
    draws = []
    for row in weights:
        cells = [cell for run, count in zip(runs, row) for _ in range(int(count)) for cell in by_run[run]]
        value = mh(cells)
        if value is not None:
            draws.append(value)
    low, high = (float(np.quantile(draws, ALPHA)), float(np.quantile(draws, 1 - ALPHA))) if len(draws) > 10 else (None, None)
    return dict(status='compared', per_run=counts, judged_sets=len(judged), strata=len(usable), runs=len(runs),
                passed_minus_filler=round(estimate, 4), interval=None if low is None else [round(low, 4), round(high, 4)],
                reading=('fillers did worse within runs' if low is not None and low > 0 else
                         'no clear within-run difference; keep fillers labelled, not excluded'))


# ---------------------------------------------------------------- stamping
def gate_stamp(recommendation, *, generated_at, applied):
    if not isinstance(generated_at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', generated_at):
        raise ValueError('generated_at must be an explicit UTC time like 2026-10-02T12:00:00Z')
    gate, validation = recommendation.get('gate'), recommendation.get('validation')
    return dict(schema=STAMP_SCHEMA, values=dict(recommendation['values'], export_applied=applied),
                method=dict(calibration=recommendation.get('schema'), status=recommendation['status'],
                            actionable=recommendation['actionable'], target=recommendation['target'],
                            settings=recommendation['settings'],
                            gate=None if gate is None else dict(feature=gate['feature'], threshold=gate['threshold'],
                                                                plan_field=gate['plan_field']),
                            validation=None if validation is None else dict(
                                survival=validation['survival'], lower=validation['lower'],
                                judged_clusters=validation['judged_clusters']),
                            baseline=recommendation['baseline'], reasons=recommendation['reasons'],
                            validation_meaning=validation_meaning(recommendation['settings']['min_survival'])),
                evidence_digest=recommendation['evidence_digest'], generated_at=generated_at)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + '\n').encode('utf-8')


def stamp_plan(plan_path, recommendation, output_path, *, generated_at):
    """Write a new plan that only TIGHTENS export fields, plus ``<output>.gates.json``.

    Only a held_up recommendation can be stamped. A changed field becomes
    max(plan value, recommended value); everything else, and the whole plan on a
    fallback, stays byte-identical. The prepare path accepts only schema_version/
    export/members, so the stamp lives in a sidecar bound to the new plan's SHA-256.
    Never overwrites: the source plan and any existing output are left untouched.
    """
    from studio_settings import validate_export
    if recommendation.get('schema') != SCHEMA:
        raise ValueError('Recommendation is not %s; re-run gate-recommend' % SCHEMA)
    if recommendation.get('target') not in ACTIONABLE_TARGETS:
        raise ValueError('Only held_up recommendations can be stamped; forward and post are diagnostics')
    plan_path, output_path = Path(plan_path).resolve(), Path(output_path).resolve()
    sidecar = output_path.with_name(output_path.name + '.gates.json')
    if output_path == plan_path:
        raise ValueError('Write the stamped plan to a new path; the source plan is never modified')
    if output_path.exists() or sidecar.exists():
        raise ValueError('Stamped plan output already exists; choose a new path')
    source = _read(plan_path, MAX_MANIFEST)
    spec = json.loads(_decode(source))
    if not isinstance(spec, dict) or set(spec) != {'schema_version', 'export', 'members'} or spec['schema_version'] != 1:
        raise ValueError('Batch plan requires schema_version:1, export and members')
    validate_export(spec['export'])
    applied = {}
    export = dict(spec['export'])
    if recommendation['actionable']:
        for field, value in sorted(recommendation['values']['export_changes'].items()):
            if field not in ('MinScore', 'MinSR', 'MinARF'):
                raise ValueError('A gate may only tighten MinScore, MinSR or MinARF')
            tightened = max(float(export[field]), float(value))
            if tightened != float(export[field]):
                export[field] = tightened
                applied[field] = dict(before=spec['export'][field], after=tightened)
    if applied:
        validate_export(export)
        raw = _canonical(dict(spec, export=export))
    else:
        raw = source  # nothing tightened: the plan is copied byte for byte
    stamp = gate_stamp(recommendation, generated_at=generated_at, applied=applied)
    stamp['plan_sha256'] = hashlib.sha256(raw).hexdigest()
    stamp['source_plan_sha256'] = hashlib.sha256(source).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('xb') as stream:
        stream.write(raw)
    with sidecar.open('xb') as stream:
        stream.write(_canonical(dict(gates=stamp)))
    return dict(plan=str(output_path), sidecar=str(sidecar), plan_sha256=stamp['plan_sha256'], applied=applied,
                gates=stamp)


def apply_qualify(record, values):
    """(passes, failures) of one exported set against stamped qualification gates.

    A gate on a metric the set lacks fails: a missing number is never read as passing.
    Split-specific gates (``qualify_by_split``) replace the pooled value for that metric.
    """
    gates = dict(values.get('qualify') or {})
    for name, overrides in (values.get('qualify_by_split') or {}).items():
        key, _, group = name.partition('=')
        if str(record.get(key)) == group:
            gates.update(overrides)
    failures = []
    for name, threshold in sorted(gates.items()):
        source, metric, _, _ = FEATURES[name]
        if source == 'optimizer':
            value = (record.get('optimizer') or {}).get(metric)
        elif source == 'file_name':
            value = (record.get('file_name') or {}).get(metric)
        else:
            value = (record['windows'].get(source) or {}).get(metric)
        if value is None or value < threshold:
            failures.append(dict(gate=name, threshold=threshold, value=value))
    return not failures, failures


def public(recommendation, *, curves=False):
    """JSON-safe view; full threshold curves only on request."""
    result = dict(recommendation)
    if not curves:
        result['features'] = {name: {key: value for key, value in info.items() if key != 'curve'}
                              for name, info in recommendation['features'].items()}
    return result


def default_common_root():
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise ValueError('APPDATA is not set; pass --common-root')
    return Path(appdata) / 'MetaQuotes' / 'Terminal' / 'Common' / 'Files' / 'GOAT'


def gate_recommend(*, common_root=None, runs=None, target='forward', min_survival=0.6, min_sets=20, min_members=8,
                   min_trades=MIN_TRADES, min_clusters=MIN_CLUSTERS, cluster='run', verdicts=None, curves=False):
    common_root = Path(common_root) if common_root else default_common_root()
    evidence = load_evidence(common_root, runs)
    verdict_map, rejected = load_verdicts(verdicts) if verdicts else (None, {})
    if target == 'held_up' and not verdict_map:
        raise ValueError('The held_up target needs --verdicts with comparable goat-catchup-verdict-v2 records')
    result = recommend(evidence['records'], target=target, verdicts=verdict_map, min_survival=min_survival,
                       min_sets=min_sets, min_members=min_members, min_trades=min_trades, min_clusters=min_clusters,
                       cluster=cluster)
    result = public(result, curves=curves)
    result['fillers'] = filler_comparison(evidence['records'], verdict_map)
    result['evidence'] = dict(common_root=str(common_root), runs=evidence['runs'], sets=len(evidence['records']),
                              duplicates_removed=evidence['duplicates_removed'],
                              verdicts=None if verdict_map is None else len(verdict_map), verdicts_rejected=rejected)
    return result
