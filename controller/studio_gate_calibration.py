"""Per-run qualification gates calibrated on our own export evidence (goat-gate-calibration-v1).

Read only. Every export folder this module touches is opened for reading; nothing
is written except the explicit output file of ``write_report`` and the new plan
plus its sidecar of ``stamp_plan``.

What it does
------------
1. Loads exported sets (``<run>/deploy`` and ``<run>/exports``) whose sequence
   capture completed. Each set carries ``deals.csv`` and an equity CSV covering
   back OOS + optimization + after, plus the run manifest with the member windows.
2. Splits every set into windows (broker server time, half-open):
       back_oos  [BackOOSDate, FromDate)
       in_sample [FromDate, ForwardDate)
       forward   [ForwardDate, ToDate)
       post      [ToDate, observed end]          (the export ran past ToDate)
   and measures net (equity change), trades (entry deals), PF, drawdown,
   recovery (net/dd), a daily Sharpe and a monthly ARF-style ratio per window.
3. For each candidate gate (a metric and a threshold), measures how many sets
   pass it (yield) and how many of those survived the target window (net > 0),
   with a Wilson interval whose sample size is the number of distinct optimization
   members kept, not sets: the two or so sets of one member are near copies, so
   counting sets would overstate the evidence.
4. Recommends the loosest gate whose interval LOWER bound reaches the target
   survival with enough sets and members. Otherwise it keeps today's defaults and
   says why. It never relaxes a plan field below the EA/controller floor.

Leakage rule (the key guard)
----------------------------
A predictor may only use data the target window could not have influenced:
- forward target: in-sample and back-OOS metrics, plus the optimizer's own
  in-sample ("Back") columns. NOT the forward window, NOT the Score (the EA's
  Score is computed from back and forward results) and NOT the file-name metrics
  (measured over the whole export window, which contains the forward window).
- post target: also the forward window and the Score.
- held_up target (catch-up verdicts from goat-catchup-verdict-v1): also the
  file-name metrics, because the catch-up weeks start after the export ended.
Plan fields only move when their predictor is clean for the target: MinScore needs
post/held_up, MinSR/MinARF need held_up. Everything else is a qualification gate
for the portfolio stage, stamped as metadata.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import xml.etree.ElementTree as ET

SCHEMA = 'goat-gate-calibration-v1'
STAMP_SCHEMA = 'goat-gate-stamp-v1'
WINDOWS = ('back_oos', 'in_sample', 'forward', 'post')
TARGETS = ('forward', 'post', 'held_up')
# Today's fixed gates: the export plan fields and the EA back-row filter.
DEFAULT_EXPORT = dict(MinScore=60.0, MinSR=2.5, MinARF=0.2, SetsToExport=2, TargetDD=100)
EXPORT_FLOORS = dict(MinScore=60.0, MinSR=2.5, MinARF=0.2, SetsToExport=2, TargetDD=100)
DEFAULT_QUALIFY = dict(is_trades=50, is_net=0.001)
MIN_POST_WEEKDAYS = 10
MAX_MANIFEST = 64 * 1024 * 1024
MAX_CSV = 64 * 1024 * 1024
MAX_XML = 32 * 1024 * 1024
MAX_SMALL = 1024 * 1024
BOOTSTRAP = 400
SEED = 20261002
NAME_METRICS = re.compile(r'_Trds=(\d+)_Prf=(-?[\d.]+)_DD=(-?[\d.]+)_PF=(-?[\d.]+)_SR=(-?[\d.]+)_ARF=(-?[\d.]+)$')
INDICATORS = ('RSI', 'EMA', 'ADX', 'BB', 'MACD', 'RSI2')
FX = {'USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD', 'SEK', 'NOK', 'DKK', 'SGD', 'HKD', 'MXN', 'ZAR', 'TRY', 'PLN', 'CNH'}
MAJORS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD'}
INDICES = {'WS30', 'US30', 'SP500', 'US500', 'SPX500', 'NDX', 'US100', 'USTEC', 'NAS100', 'GDAXI', 'DE40', 'GER40',
           'UK100', 'FTSE100', 'JP225', 'NI225', 'STOXX50', 'EU50', 'FRA40', 'AUS200', 'HK50', 'ESP35'}

# name: (source window or kind, metric, allowed targets, plan field)
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


# ---------------------------------------------------------------- reading
def _read(path, limit):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('File exceeds its read limit: ' + path.name)
    return raw


def _text(path, limit=MAX_CSV):
    raw = _read(path, limit)
    return raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')


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


def deals(path):
    rows = []
    lines = _text(path).splitlines()
    header = lines[0].split(',') if lines else []
    need = ('server_time_msc', 'deal_type', 'deal_entry', 'profit', 'commission', 'fee', 'swap')
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
        rows.append((int(parts[index['server_time_msc']]), int(parts[index['deal_entry']]), result))
    rows.sort(key=lambda row: row[0])
    return rows


def equity(path):
    rows = []
    lines = _text(path).splitlines()
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

    ``deals_until``: msc where an incomplete capture stopped; trade counts and PF of a
    window it does not fully cover are unknown (None), never a partial count.
    """
    lo, hi = msc(first), msc(end)
    covered = deals_until is None or deals_until >= hi
    inside = [row for row in deal_rows if lo <= row[0] < hi]
    entries = sum(1 for row in inside if row[1] in (0, 2)) if covered else None
    closes = [row[2] for row in inside if row[1] in (1, 2, 3)]
    wins = sum(value for value in closes if value > 0)
    losses = -sum(value for value in closes if value < 0)
    pf = (min(wins / losses, 25.0) if losses > 0 else (25.0 if wins > 0 else None)) if covered else None
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
        if current in closes_by_day:
            value = closes_by_day[current]
        else:
            value = previous
        if current.weekday() < 5:
            returns.append((value - previous) / initial)
            previous = value
        else:
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
                closes=len(closes) if covered else None, net=round(net, 2), dd=round(dd, 2), pf=None if pf is None else round(pf, 4),
                recovery=None if recovery is None else round(recovery, 4),
                sr=None if sr is None else round(sr, 4), arf=None if arf is None else round(arf, 4))


# ---------------------------------------------------------------- optimizer rows
def _xml_rows(path):
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
    raw = _read(path, MAX_XML)
    # MT5 writes UTF-16 bodies that still declare UTF-8; parse the decoded text.
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
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


def load_run(run_dir):
    """Records for every completed sequence capture of one run, plus skipped reasons."""
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
            deal_rows, equity_rows = deals(folder / 'deals.csv'), equity(sibling_csv)
            # The tester's equity CSV covers the whole export run even when the sequence
            # capture hit its row limit; that capture only bounds trade counts and PF.
            observed_end = msc(equity_rows[-1][0])
            deals_until = None if complete else int(completion['observed_end_server_msc'])
            windows = windows_for(job['tester'], settings.get('BackOOSDate') if settings.get('IncludeBackOOS', True) else None,
                                  observed_end)
            values = _set_values(folder / 'effective-inputs.set')
            optimized = _set_values(folder / 'source-inputs.set') if (folder / 'source-inputs.set').is_file() else {}
            family, timeframe = strategy_profile(values)
            identity = hashlib.sha256(json.dumps(
                [symbol, sorted((k, v) for k, v in values.items() if k != 'EA_Desc'),
                 sorted((name, [a.isoformat(), b.isoformat()]) for name, (a, b) in windows.items() if name != 'post')],
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
            records.append(dict(
                run=run_dir.name, area=area, member=alias, symbol=symbol, path=label,
                set_sha256=hashlib.sha256(_read(sibling_set, MAX_SMALL)).hexdigest(), identity=identity,
                symbol_class=symbol_class(symbol), family=family, timeframe=timeframe,
                design='IS%.0fm/F%.0fw/B%.0fw' % (is_months, weekdays(*windows['forward']) / 5,
                                                 weekdays(*windows['back_oos']) / 5 if 'back_oos' in windows else 0),
                windows=metrics, file_name=file_metrics, optimizer=optimizer,
                capture='complete' if complete else 'partial',
                observed_end=datetime.fromtimestamp(observed_end / 1000, tz=timezone.utc).date().isoformat()))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            skipped.append(dict(path=label, reason=str(exc) or type(exc).__name__))
    return dict(run=run_dir.name, export_settings=settings, records=records, skipped=skipped)


def load_evidence(common_root, runs=None):
    runs = list(runs) if runs else discover_runs(common_root)
    loaded = [load_run(Path(common_root) / run) for run in runs]
    seen, records, duplicates = set(), [], 0
    # deploy before exports, then run order: the first copy of identical evidence wins.
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
                           skipped=len(run['skipped']), skipped_examples=run['skipped'][:5]) for run in loaded],
                records=records, duplicates_removed=duplicates)


def load_verdicts(path):
    """{set_sha256: verdict} from goat-catchup-verdict-v1 records anywhere in a JSON/JSONL file or folder."""
    path = Path(path)
    files = sorted(path.rglob('*.json*')) if path.is_dir() else [path]
    found = {}

    def walk(node):
        if isinstance(node, dict):
            if 'verdict' in node and (str(node.get('schema', '')).startswith('goat-catchup-verdict')
                                      or 'original' in node or 'set_sha256' in node):
                original = node.get('original') or {}
                sha = original.get('set_sha256') or node.get('set_sha256')
                if isinstance(sha, str) and isinstance(node['verdict'], str):
                    found[sha] = node['verdict']
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
    return found


# ---------------------------------------------------------------- outcomes and features
def outcome(record, target, verdicts=None):
    """True/False survival in the target window, or None when it cannot be judged."""
    if target == 'held_up':
        verdict = (verdicts or {}).get(record['set_sha256'])
        if verdict in (None, 'not_comparable', 'too_few_trades'):
            return None
        return verdict == 'held_up'
    window = record['windows'].get(target)
    if window is None:
        return None
    if target == 'post' and window['weekdays'] < MIN_POST_WEEKDAYS:
        return None
    if target == 'forward' and record['observed_end'] < (date.fromisoformat(window['end_day']) - timedelta(days=1)).isoformat():
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


# ---------------------------------------------------------------- statistics
def wilson(successes, n, z=1.96):
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


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


def auc(pairs):
    """P(feature of a survivor > feature of a non-survivor); ties count half."""
    positives = sorted(value for value, hit in pairs if hit)
    negatives = sorted(value for value, hit in pairs if not hit)
    if not positives or not negatives:
        return None
    import bisect
    total = 0.0
    for value in positives:
        below = bisect.bisect_left(negatives, value)
        equal = bisect.bisect_right(negatives, value) - below
        total += below + equal / 2
    return total / (len(positives) * len(negatives))


def cluster_auc_interval(rows, resamples=BOOTSTRAP, seed=SEED):
    """Bootstrap over members (clusters) so near-copy sets do not shrink the interval."""
    clusters = {}
    for member, value, hit in rows:
        clusters.setdefault(member, []).append((value, hit))
    keys = sorted(clusters)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = []
        for _ in keys:
            sample.extend(clusters[keys[rng.randrange(len(keys))]])
        result = auc(sample)
        if result is not None:
            values.append(result)
    if len(values) < resamples // 2:
        return None
    values.sort()
    return (values[int(0.025 * len(values))], values[min(len(values) - 1, int(0.975 * len(values)))])


def survival_curve(rows, thresholds):
    """rows: (member, value, hit). Raw + monotone survival among value >= t, with member-cluster Wilson."""
    total_sets = len(rows)
    total_members = len({row[0] for row in rows})
    present = sorted((row for row in rows if row[1] is not None), key=lambda row: row[1])
    fitted = isotonic([1.0 if row[2] else 0.0 for row in present])
    curve = []
    for threshold in thresholds:
        kept = [row for row in present if row[1] >= threshold]
        smooth = [value for row, value in zip(present, fitted) if row[1] >= threshold]
        members = len({row[0] for row in kept})
        hits = sum(1 for row in kept if row[2])
        raw = hits / len(kept) if kept else None
        low, high = wilson(raw * members, members) if kept else (0.0, 1.0)
        curve.append(dict(threshold=threshold, kept_sets=len(kept), kept_members=members,
                          yield_=round(len(kept) / total_sets, 4) if total_sets else 0.0,
                          survival=None if raw is None else round(raw, 4),
                          survival_monotone=round(sum(smooth) / len(smooth), 4) if smooth else None,
                          interval=[round(low, 4), round(high, 4)], members_total=total_members))
    return curve


def candidate_thresholds(values, extra=()):
    values = sorted(value for value in values if value is not None)
    if not values:
        return []
    grid = {values[min(len(values) - 1, int(q * len(values) / 20))] for q in range(0, 19)}
    grid.update(value for value in extra if value is not None)
    return sorted(_round(value) for value in grid)


def _round(value):
    if value == 0 or abs(value) >= 100:
        return round(value, 0) if abs(value) >= 100 else 0.0
    digits = max(0, 3 - int(math.floor(math.log10(abs(value)))))
    return round(value, digits)


# ---------------------------------------------------------------- recommendation
def calibrate(records, *, target='forward', verdicts=None, min_survival=0.6, min_sets=20, min_members=8,
              confidence='lower'):
    if target not in TARGETS:
        raise ValueError('target must be one of: ' + ', '.join(TARGETS))
    if not 0 < min_survival < 1:
        raise ValueError('min_survival must be between 0 and 1')
    if confidence not in ('lower', 'point'):
        raise ValueError("confidence must be 'lower' or 'point'")
    labelled = []
    for record in records:
        hit = outcome(record, target, verdicts)
        if hit is not None:
            labelled.append((record, hit))
    members = len({(r['member']) for r, _ in labelled})
    hits = sum(1 for _, hit in labelled if hit)
    base_low, base_high = wilson(hits / len(labelled) * members, members) if labelled else (0.0, 1.0)
    baseline = dict(sets=len(labelled), members=members, survivors=hits,
                    survival=round(hits / len(labelled), 4) if labelled else None,
                    interval=[round(base_low, 4), round(base_high, 4)])
    table = {}
    for name in allowed_features(target):
        rows = [(r['member'], feature(r, name, target), hit) for r, hit in labelled]
        present = [(m, v, h) for m, v, h in rows if v is not None]
        default = {'is_trades': DEFAULT_QUALIFY['is_trades'], 'is_net': DEFAULT_QUALIFY['is_net']}.get(name)
        plan_field = FEATURES[name][3]
        extra = [default, DEFAULT_EXPORT.get(plan_field) if plan_field else None]
        thresholds = candidate_thresholds([v for _, v, _ in present], extra)
        area = auc([(v, h) for _, v, h in present])
        interval = cluster_auc_interval(present) if area is not None else None
        curve = survival_curve(rows, thresholds)
        for point in curve:
            point['qualifies'] = bool(
                point['survival'] is not None and point['kept_sets'] >= min_sets and point['kept_members'] >= min_members
                and (point['interval'][0] if confidence == 'lower' else point['survival_monotone']) >= min_survival
                and (plan_field is None or point['threshold'] >= EXPORT_FLOORS[plan_field]))
        direction = ('higher_is_better' if interval and interval[0] > 0.5 else
                     'higher_is_worse' if interval and interval[1] < 0.5 else 'no_clear_signal')
        table[name] = dict(source=FEATURES[name][0], metric=FEATURES[name][1], plan_field=plan_field,
                           coverage=len(present), auc=None if area is None else round(area, 4),
                           auc_interval=None if interval is None else [round(x, 4) for x in interval],
                           direction=direction, curve=curve)
    return dict(target=target, baseline=baseline, features=table, labelled=labelled,
                settings=dict(min_survival=min_survival, min_sets=min_sets, min_members=min_members, confidence=confidence))


def _split_table(labelled, key):
    groups = {}
    for record, hit in labelled:
        groups.setdefault(record[key], []).append((record, hit))
    result = {}
    for name in sorted(groups):
        rows = groups[name]
        members = len({r['member'] for r, _ in rows})
        hits = sum(1 for _, hit in rows if hit)
        low, high = wilson(hits / len(rows) * members, members)
        result[name] = dict(sets=len(rows), members=members, survival=round(hits / len(rows), 4),
                            interval=[round(low, 4), round(high, 4)])
    return result


def evidence_digest(labelled, target):
    rows = [[r['run'], r['member'], r['set_sha256'], hit,
             {name: feature(r, name, target) for name in allowed_features(target)}]
            for r, hit in labelled]
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return hashlib.sha256(json.dumps([SCHEMA, target, rows], sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


SPLIT_KEYS = ('symbol_class', 'design')


def recommend(records, *, target='forward', verdicts=None, min_survival=0.6, min_sets=20, min_members=8,
              confidence='lower', current_export=None, split_keys=SPLIT_KEYS):
    """Gate values for a new run, with the evidence behind them, or today's defaults when evidence is thin.

    ``split_keys``: also calibrate each symbol class / run design on its own; a split
    only gets its own qualification gate when it clears the same evidence bar alone.
    """
    current = dict(DEFAULT_EXPORT, **{k: v for k, v in (current_export or {}).items() if k in DEFAULT_EXPORT})
    result = calibrate(records, target=target, verdicts=verdicts, min_survival=min_survival,
                       min_sets=min_sets, min_members=min_members, confidence=confidence)
    labelled, baseline = result.pop('labelled'), result['baseline']
    choices = []
    for name, info in result['features'].items():
        if info['direction'] != 'higher_is_better':
            continue
        passing = [point for point in info['curve'] if point['qualifies']]
        if passing:
            best = max(passing, key=lambda p: (p['kept_sets'], p['interval'][0], -p['threshold']))
            choices.append((name, best))
    choices.sort(key=lambda item: (-item[1]['kept_sets'], -item[1]['interval'][0], item[0]))
    reasons, chosen = [], None
    if baseline['sets'] < min_sets or baseline['members'] < min_members:
        status = 'fallback_thin_evidence'
        reasons.append('Only %d judged sets from %d members for the %s window (need %d sets, %d members).'
                       % (baseline['sets'], baseline['members'], target, min_sets, min_members))
    elif baseline['interval'][0] >= min_survival:
        status = 'defaults_already_meet_target'
        reasons.append('Without any extra gate, %.0f%% of sets survived (lower bound %.0f%%), already at the %.0f%% target.'
                       % (100 * baseline['survival'], 100 * baseline['interval'][0], 100 * min_survival))
    elif not choices:
        status = 'fallback_no_qualifying_gate'
        reasons.append('No single gate lifted the %s survival lower bound to %.0f%% while keeping %d sets from %d members.'
                       % (target, 100 * min_survival, min_sets, min_members))
    else:
        status = 'calibrated'
        chosen = choices[0]
    export = dict(current)
    qualify = dict(DEFAULT_QUALIFY)
    if chosen:
        name, point = chosen
        plan_field = FEATURES[name][3]
        if plan_field:
            export[plan_field] = max(float(point['threshold']), float(EXPORT_FLOORS[plan_field]))
        else:
            qualify[name] = point['threshold']
    for field, floor in EXPORT_FLOORS.items():
        if export[field] < floor:
            export[field] = floor
    cross_run = {}
    if chosen:
        name, point = chosen
        for run in sorted({r['run'] for r, _ in labelled}):
            rows = [(r, hit) for r, hit in labelled if r['run'] == run]
            kept = [(r, hit) for r, hit in rows if (feature(r, name, target) is not None
                                                    and feature(r, name, target) >= point['threshold'])]
            members = len({r['member'] for r, _ in kept})
            hits = sum(1 for _, hit in kept if hit)
            low, high = wilson(hits / len(kept) * members, members) if kept else (0.0, 1.0)
            cross_run[run] = dict(sets=len(rows), kept=len(kept), survival=round(hits / len(kept), 4) if kept else None,
                                  interval=[round(low, 4), round(high, 4)])
    splits = {key: _split_table(labelled, key) for key in ('symbol_class', 'family', 'timeframe', 'design', 'run')}
    by_split = {}
    for key in split_keys or ():
        for name in sorted({r[key] for r, _ in labelled}):
            subset = [r for r, _ in labelled if r[key] == name]
            inner = recommend(subset, target=target, verdicts=verdicts, min_survival=min_survival, min_sets=min_sets,
                              min_members=min_members, confidence=confidence, current_export=current, split_keys=())
            gate = inner['gate']
            by_split['%s=%s' % (key, name)] = dict(
                status=inner['status'], baseline=inner['baseline'], reasons=inner['reasons'],
                gate=None if gate is None else dict(feature=gate['feature'], threshold=gate['threshold'],
                                                    plan_field=gate['plan_field'], kept_sets=gate['point']['kept_sets'],
                                                    kept_members=gate['point']['kept_members'],
                                                    survival=gate['point']['survival'], interval=gate['point']['interval']))
    split_qualify = {name: {info['gate']['feature']: info['gate']['threshold']}
                     for name, info in by_split.items()
                     if info['status'] == 'calibrated' and info['gate']['plan_field'] is None}
    digest = evidence_digest(labelled, target)
    gate = None if not chosen else dict(feature=chosen[0], threshold=chosen[1]['threshold'],
                                        plan_field=FEATURES[chosen[0]][3], point=chosen[1])
    alternatives = [dict(feature=name, threshold=point['threshold'], kept_sets=point['kept_sets'],
                         survival=point['survival'], interval=point['interval']) for name, point in choices[1:6]]
    return dict(schema=SCHEMA, status=status, target=target, settings=result['settings'], baseline=baseline,
                gate=gate, alternatives=alternatives, reasons=reasons,
                values=dict(export=export, qualify=qualify, qualify_by_split=split_qualify),
                current=dict(export=current, qualify=dict(DEFAULT_QUALIFY)),
                features=result['features'], splits=splits, by_split=by_split, cross_run=cross_run, evidence_digest=digest,
                leakage_rule={name: list(FEATURES[name][2]) for name in FEATURES},
                summary=summarize(status, target, baseline, gate, reasons, min_survival, splits, cross_run, result['features'])
                + _split_sentence(by_split))


def _split_sentence(by_split):
    calibrated = ['%s: %s >= %s' % (name, info['gate']['feature'], info['gate']['threshold'])
                  for name, info in sorted(by_split.items()) if info['status'] == 'calibrated']
    thin = [name for name, info in sorted(by_split.items()) if info['status'] == 'fallback_thin_evidence']
    text = ''
    if calibrated:
        text += ' Split gates with enough evidence on their own: %s.' % '; '.join(calibrated)
    if thin:
        text += ' Splits kept on the pooled gates because their own evidence is thin: %s.' % ', '.join(thin)
    return text


def summarize(status, target, baseline, gate, reasons, min_survival, splits, cross_run, features):
    lines = []
    if baseline['survival'] is None:
        lines.append('No set could be judged on the %s window.' % target)
    else:
        lines.append('%d sets from %d members could be judged on the %s window; %.0f%% were profitable there '
                     '(95%% range %.0f-%.0f%%, counted by member).'
                     % (baseline['sets'], baseline['members'], target, 100 * baseline['survival'],
                        100 * baseline['interval'][0], 100 * baseline['interval'][1]))
    if status == 'calibrated':
        point = gate['point']
        lines.append('Recommended gate: %s >= %s. It keeps %d sets (%d members, %.0f%% of judged sets), and %.0f%% of '
                     'those were profitable (95%% range %.0f-%.0f%%), meeting the %.0f%% target at the lower bound.'
                     % (gate['feature'], point['threshold'], point['kept_sets'], point['kept_members'],
                        100 * point['yield_'], 100 * point['survival'], 100 * point['interval'][0],
                        100 * point['interval'][1], 100 * min_survival))
        if gate['plan_field']:
            lines.append('This sets the plan field %s.' % gate['plan_field'])
        else:
            lines.append('It is a portfolio qualification gate; the export plan fields stay at their current values.')
        weak = [run for run, info in cross_run.items() if info['survival'] is not None and info['interval'][0] < min_survival]
        if weak:
            lines.append('Per run, the lower bound stays under target for: %s. Treat it as a pooled result.' % ', '.join(weak))
    else:
        lines.append('Keeping the current gates. ' + ' '.join(reasons))
    inverse = sorted(name for name, info in features.items() if info['direction'] == 'higher_is_worse')
    if inverse:
        lines.append('Higher values did worse for: %s (a sign of over-fitting; never tighten on these).' % ', '.join(inverse))
    thin = sorted('%s=%s' % (key, name) for key, table in splits.items() if key != 'run'
                  for name, info in table.items() if info['members'] < 8)
    if thin:
        lines.append('Too thin to calibrate separately (<8 members): %s.' % ', '.join(thin[:12]) + (' ...' if len(thin) > 12 else ''))
    lines.append('Leakage rule: forward-window, Score and file-name metrics are never used to predict a window they contain.')
    return ' '.join(lines)


# ---------------------------------------------------------------- stamping
def gate_stamp(recommendation, *, generated_at):
    if not isinstance(generated_at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', generated_at):
        raise ValueError('generated_at must be an explicit UTC time like 2026-10-02T12:00:00Z')
    gate = recommendation.get('gate')
    return dict(schema=STAMP_SCHEMA, values=recommendation['values'],
                method=dict(calibration=SCHEMA, status=recommendation['status'], target=recommendation['target'],
                            settings=recommendation['settings'],
                            gate=None if gate is None else dict(feature=gate['feature'], threshold=gate['threshold'],
                                                                plan_field=gate['plan_field'],
                                                                survival=gate['point']['survival'],
                                                                interval=gate['point']['interval'],
                                                                kept_sets=gate['point']['kept_sets'],
                                                                kept_members=gate['point']['kept_members']),
                            baseline=recommendation['baseline'], reasons=recommendation['reasons']),
                evidence_digest=recommendation['evidence_digest'], generated_at=generated_at)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + '\n').encode('utf-8')


def stamp_plan(plan_path, recommendation, output_path, *, generated_at):
    """Write a new plan whose export fields carry the gate values, plus ``<output>.gates.json``.

    The prepare path accepts only schema_version/export/members, so the stamp lives in
    a sidecar bound to the new plan's SHA-256; the plan itself stays valid as-is.
    Never overwrites: the source plan and any existing output are left untouched.
    """
    from studio_settings import validate_export
    plan_path, output_path = Path(plan_path).resolve(), Path(output_path).resolve()
    sidecar = output_path.with_name(output_path.name + '.gates.json')
    if output_path == plan_path:
        raise ValueError('Write the stamped plan to a new path; the source plan is never modified')
    if output_path.exists() or sidecar.exists():
        raise ValueError('Stamped plan output already exists; choose a new path')
    spec = json.loads(_text(plan_path, MAX_MANIFEST))
    if not isinstance(spec, dict) or set(spec) != {'schema_version', 'export', 'members'} or spec['schema_version'] != 1:
        raise ValueError('Batch plan requires schema_version:1, export and members')
    export = dict(spec['export'])
    for field, value in recommendation['values']['export'].items():
        export[field] = int(value) if field in ('SetsToExport',) else value
    validate_export(export)
    stamped = dict(spec, export=export)
    raw = _canonical(stamped)
    stamp = gate_stamp(recommendation, generated_at=generated_at)
    stamp['plan_sha256'] = hashlib.sha256(raw).hexdigest()
    stamp['source_plan_sha256'] = hashlib.sha256(_read(plan_path, MAX_MANIFEST)).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('xb') as stream:
        stream.write(raw)
    with sidecar.open('xb') as stream:
        stream.write(_canonical(dict(gates=stamp)))
    return dict(plan=str(output_path), sidecar=str(sidecar), plan_sha256=stamp['plan_sha256'], gates=stamp)


def apply_qualify(record, values):
    """(passes, failures) of one exported set against stamped qualification gates.

    A gate on a metric the set lacks fails: a missing number is never read as passing.
    Split-specific gates (``qualify_by_split``) replace the pooled value for that metric.
    """
    gates = dict(values.get('qualify') or {})
    for name, overrides in (values.get('qualify_by_split') or {}).items():
        key, _, group = name.partition('=')
        if record.get(key) == group:
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
                              | dict(best_points=[p for p in info['curve'] if p['qualifies']][:3])
                              for name, info in recommendation['features'].items()}
    return result


def default_common_root():
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise ValueError('APPDATA is not set; pass --common-root')
    return Path(appdata) / 'MetaQuotes' / 'Terminal' / 'Common' / 'Files' / 'GOAT'


def gate_recommend(*, common_root=None, runs=None, target='forward', min_survival=0.6, min_sets=20, min_members=8,
                   confidence='lower', verdicts=None, curves=False):
    common_root = Path(common_root) if common_root else default_common_root()
    evidence = load_evidence(common_root, runs)
    verdict_map = load_verdicts(verdicts) if verdicts else None
    if target == 'held_up' and not verdict_map:
        raise ValueError('The held_up target needs --verdicts with goat-catchup-verdict-v1 records')
    result = recommend(evidence['records'], target=target, verdicts=verdict_map, min_survival=min_survival,
                       min_sets=min_sets, min_members=min_members, confidence=confidence)
    result = public(result, curves=curves)
    result['evidence'] = dict(common_root=str(common_root), runs=evidence['runs'], sets=len(evidence['records']),
                              duplicates_removed=evidence['duplicates_removed'],
                              verdicts=None if verdict_map is None else len(verdict_map))
    return result
