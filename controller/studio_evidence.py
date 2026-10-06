"""Read exported GOAT evidence (kept SET + equity CSV + optional .goatseq capture).

Read-only and bounded: nothing here writes, launches or changes MT5 or controller
state. Large capture files (account.csv, marks.csv) are never read here.

An export unit is ``<stem>.set`` with its ``<stem>.csv`` equity curve and, when
sequence capture was on, a ``<stem>.goatseq`` folder. Kept units live under
``Common Files\\GOAT\\R<run>\\deploy\\<member alias>\\<symbol>\\`` next to the run's
``export_settings.GOAT`` and ``manifest.json``; a desktop library copy keeps the
unit but not the run files.

Evidence end: the last broker server calendar day the export's test covers. The
capture's observed end is authoritative when the capture completed; otherwise the
SET header's FOOS end (the EA writes the date of the last tick it saw), then the
equity CSV's last row. Dates are broker server dates, never UTC.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from strategy_registry import inspect_set
from studio_export_qualification import (BELOW_SCORE_FOLDER, STANDARD_TIER, export_tier, file_name_tokens, qualify,
                                         research_only_stamp, thresholds_from_settings_text, thresholds_from_values,
                                         unavailable_thresholds)
from studio_settings import PERIODS

MAX_SET_BYTES = 4 * 1024 * 1024
MAX_SMALL_JSON = 8 * 1024 * 1024
MAX_RUN_MANIFEST = 64 * 1024 * 1024
MAX_SETS = 10000
CSV_TAIL_BYTES = 4096
COMPLETE = 'complete-awaiting-import-verification'
WINDOWS = ('BOOS', 'SAMPLE', 'FWD', 'FOOS')
DEFAULT_THRESHOLDS = dict(MinARF=0.2, MinSR=2.5)
_METRICS = ('Trds', 'Prf', 'DD', 'PF', 'SR', 'ARF')
_NUMBER = r'(-?\d+(?:\.\d+)?)'
_TAIL = (r',(?P<period>' + '|'.join(sorted(PERIODS, key=len, reverse=True)) + r')'
         + ''.join('_' + key + '=' + _NUMBER for key in _METRICS))
_WINDOW = re.compile(r'^;\s*(BOOS|SAMPLE|FWD|FOOS):\s*(\d{4}\.\d{2}\.\d{2})-(\d{4}\.\d{2}\.\d{2})'
                     r'\s+Days=(\d+)\s+Trades=(\d+)\s+PL=(-?\d+(?:\.\d+)?)\s*$')


def mt5_date(text):
    return datetime.strptime(text, '%Y.%m.%d').date()


def server_date(msc):
    """Broker server calendar date of a wall-clock-as-unix-ms stamp."""
    return datetime.fromtimestamp(msc / 1000, timezone.utc).date()


def server_msc(day):
    """Wall-clock-as-unix-ms of 00:00 broker server time on ``day``."""
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)


def weekdays(first, last):
    """Mon-Fri days in the inclusive range; zero when the range is empty."""
    if last < first:
        return 0
    days = (last - first).days + 1
    full, rest = divmod(days, 7)
    return full * 5 + sum((first + timedelta(days=i)).weekday() < 5 for i in range(rest))


def _read(path, limit):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Evidence file exceeds its byte bound: ' + path.name)
    return raw


def read_json_bounded(path, limit=MAX_SMALL_JSON):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key in ' + Path(path).name)
            value[key] = item
        return value
    raw = _read(path, limit)
    return json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'), object_pairs_hook=unique)


def read_ini(path, limit=64 * 1024):
    """Flat key=value reader for small native INI files (export_settings.GOAT)."""
    raw = _read(path, limit)
    values = {}
    for line in raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith((';', '[')) or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _key_values(path, limit=64 * 1024):
    rows = {}
    for line in _read(path, limit).decode('utf-8-sig').splitlines()[1:]:
        if ',' in line:
            key, value = line.split(',', 1)
            rows[key] = value
    return rows


def unit_paths(set_path):
    """Sibling paths of one export unit. Stems contain dots, so never use with_suffix."""
    set_path = Path(set_path)
    if set_path.suffix.lower() != '.set':
        raise ValueError('Export unit must be named by its .set file')
    stem = set_path.name[:-4]
    return dict(set=set_path, csv=set_path.with_name(stem + '.csv'), goatseq=set_path.with_name(stem + '.goatseq'), stem=stem)


def parse_header(text):
    """BOOS/SAMPLE/FWD/FOOS window lines the EA writes into an exported SET."""
    windows = {}
    for line in text.splitlines():
        match = _WINDOW.match(line)
        if match:
            kind = match[1]
            if kind in windows:
                raise ValueError('Duplicate ' + kind + ' window in SET header')
            windows[kind] = dict(start=mt5_date(match[2]).isoformat(), end=mt5_date(match[3]).isoformat(),
                                 days=int(match[4]), trades=int(match[5]), pl=float(match[6]))
    return windows


def parse_stem(stem, symbol=None):
    """``<EA name> <SYMBOL>,<PERIOD>_Trds=.._Prf=.._DD=.._PF=.._SR=.._ARF=..`` (EA names contain spaces).

    With a known symbol (capture asset or run tester) the split is exact; without
    one the symbol is taken as the last space-free token before the comma.
    """
    symbol_pattern = re.escape(symbol) if symbol else r'[^ ]+'
    match = re.fullmatch(r'(?P<ea>.+) (?P<symbol>' + symbol_pattern + ')' + _TAIL, stem)
    if not match:
        return None
    metrics = {}
    for key, value in zip(_METRICS, match.groups()[3:]):
        try:
            metrics[key] = float(Decimal(value))
        except InvalidOperation:
            return None
    return dict(ea_name=match['ea'], symbol=match['symbol'], period=match['period'],
                metrics=dict(trades=metrics['Trds'], profit=metrics['Prf'], dd=metrics['DD'], pf=metrics['PF'],
                             sr=metrics['SR'], arf=metrics['ARF']))


def csv_last_date(csv_path):
    """Date of the equity CSV's last row, reading only its tail."""
    path = Path(csv_path)
    size = path.stat().st_size
    with path.open('rb') as stream:
        head = stream.read(2)
        stream.seek(max(0, size - CSV_TAIL_BYTES))
        tail = stream.read(CSV_TAIL_BYTES)
    if head == b'\xff\xfe':
        if (size - len(tail)) % 2:
            tail = tail[1:]
        text = tail.decode('utf-16-le', errors='ignore')
    else:
        text = tail.decode('utf-8', errors='ignore')
    for line in reversed(text.splitlines()):
        match = re.match(r'﻿?(\d{4}\.\d{2}\.\d{2}) \d{2}:\d{2}\t', line)
        if match:
            return mt5_date(match[1]).isoformat()
    return None


def read_capture(goatseq, set_sha256):
    """Small facts from a .goatseq package: manifest, run.csv and completion.csv only."""
    folder = Path(goatseq)
    manifest_path = folder / 'manifest.json'
    if not manifest_path.is_file():
        return None
    manifest = read_json_bounded(manifest_path)
    if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 'goat-sequence-export-v1':
        raise ValueError('Unsupported sequence package manifest')
    requested, observed = manifest.get('requestedPeriod') or {}, manifest.get('observedPeriod') or {}
    for value in (requested.get('startServerMsc'), requested.get('endServerMsc'), observed.get('startServerMsc'), observed.get('endServerMsc')):
        if type(value) is not int or value <= 0:
            raise ValueError('Sequence package periods must be positive integer milliseconds')
    completion = _key_values(folder / 'completion.csv') if (folder / 'completion.csv').is_file() else {}
    run = _key_values(folder / 'run.csv') if (folder / 'run.csv').is_file() else {}
    exported = (manifest.get('exports') or {}).get('set') or {}
    complete = manifest.get('status') == COMPLETE and completion.get('capture_status', '').startswith('complete')
    return dict(path=str(manifest_path), manifest_sha256=hashlib.sha256(_read(manifest_path, MAX_SMALL_JSON)).hexdigest(),
                status=manifest.get('status'), reason=manifest.get('reason') or completion.get('error') or '',
                complete=complete, run_id=manifest.get('runId'), asset=manifest.get('asset'), build_id=manifest.get('buildId'),
                model=manifest.get('model'), currency=manifest.get('currency'), initial_equity=manifest.get('initialEquity'),
                leverage=manifest.get('leverage'), server=(manifest.get('timeBasis') or {}).get('server'),
                requested_start_msc=requested['startServerMsc'], requested_end_msc=requested['endServerMsc'],
                observed_start_msc=observed['startServerMsc'], observed_end_msc=observed['endServerMsc'],
                set_binding_matches=exported.get('sha256') == set_sha256, account=run.get('account'))


def find_run_root(set_path):
    """``R<run>`` folder above ``deploy\\<alias>\\<symbol>\\<file>.set`` (or the research-only
    ``below_score\\<alias>\\<symbol>\\<file>.set``), when present."""
    parents = Path(set_path).resolve().parents
    if len(parents) > 3 and parents[2].name.lower() in ('deploy', BELOW_SCORE_FOLDER):
        root = parents[3]
        if (root / 'export_settings.GOAT').is_file():
            return root
    return None


class RunContext:
    """Run-level facts (thresholds, member tester settings), parsed once per run."""

    def __init__(self):
        self._runs = {}

    def get(self, root):
        if root is None:
            return None
        key = str(root)
        if key not in self._runs:
            settings_path = root / 'export_settings.GOAT'
            settings_raw = _read(settings_path, 64 * 1024)
            settings = read_ini(settings_path)
            jobs, ea_sha256 = {}, None
            manifest_path = root / 'manifest.json'
            if manifest_path.is_file():
                manifest = read_json_bounded(manifest_path, MAX_RUN_MANIFEST)
                ea_sha256 = manifest.get('ea_sha256') if isinstance(manifest.get('ea_sha256'), str) else None
                for job in manifest.get('jobs') or []:
                    if isinstance(job, dict) and isinstance(job.get('run_alias'), str) and isinstance(job.get('tester'), dict):
                        jobs[job['run_alias']] = job['tester']
            self._runs[key] = dict(root=key, run_id=root.name, export_settings=settings, testers=jobs, ea_sha256=ea_sha256,
                                   export_settings_path=str(settings_path),
                                   export_settings_text=settings_raw.decode('utf-16' if settings_raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
        return self._runs[key]


def _number(text):
    try:
        value = float(Decimal(text))
    except (InvalidOperation, TypeError):
        return None
    return value


def thresholds(run):
    settings = (run or {}).get('export_settings') or {}
    values, basis = {}, 'run_export_settings'
    for key, default in DEFAULT_THRESHOLDS.items():
        number = _number(settings.get(key))
        if number is None:
            number, basis = default, 'goat_minimum_defaults'
        values[key] = number
    return dict(min_arf=values['MinARF'], min_sr=values['MinSR'], basis=basis)


def read_export(set_path, *, runs=None):
    """Facts about one kept export unit. Raises ValueError only for an unreadable SET."""
    paths = unit_paths(set_path)
    raw = _read(paths['set'], MAX_SET_BYTES)
    info = inspect_set(raw)
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    if info['axes']:
        raise ValueError('Exported SET still has optimization axes; catch-up needs frozen values')
    windows = parse_header(text)
    problems = []
    capture = None
    if paths['goatseq'].is_dir():
        try:
            capture = read_capture(paths['goatseq'], info['sha256'])
        except (OSError, ValueError) as exc:
            problems.append('Sequence package unreadable: ' + str(exc))
    if capture and not capture['set_binding_matches']:
        problems.append('Sequence package is bound to a different SET; it is not this export\'s evidence')
        capture = None
    run = (runs or RunContext()).get(find_run_root(paths['set']))
    alias = info['ea_desc']
    tester = (run or {}).get('testers', {}).get(alias)
    hint = (capture or {}).get('asset') or (tester or {}).get('Symbol')
    named = parse_stem(paths['stem'], hint) if hint else None
    named = named or parse_stem(paths['stem'])
    if named is None:
        problems.append('File name does not follow the GOAT export pattern (EA SYMBOL,PERIOD_Trds=..._ARF=...)')
    csv_end = csv_last_date(paths['csv']) if paths['csv'].is_file() else None
    if not paths['csv'].is_file():
        problems.append('Equity CSV missing next to the SET')
    if capture and capture['complete']:
        end, source = server_date(capture['observed_end_msc']), 'capture'
    elif 'FOOS' in windows:
        end, source = date.fromisoformat(windows['FOOS']['end']), 'set_header'
    elif csv_end:
        end, source = date.fromisoformat(csv_end), 'equity_csv'
    else:
        end, source = None, None
        problems.append('No evidence end: no complete capture, FOOS header or equity CSV')
    if capture:
        start = server_date(capture['requested_start_msc'])
    elif 'BOOS' in windows:
        start = date.fromisoformat(windows['BOOS']['start'])
    elif 'SAMPLE' in windows:
        start = date.fromisoformat(windows['SAMPLE']['start'])
    else:
        start = None
    requested_end = server_date(capture['requested_end_msc']) - timedelta(days=1) if capture else None
    member = paths['set'].parent.parent.name if run else None
    limits = thresholds(run)
    metrics = named['metrics'] if named else None
    # One shared judgement (goat-export-qualification-v1). Only the run's own export_settings.GOAT
    # can make a set pass: without the run (a library copy) the margins below still read against
    # GOAT's minimum defaults for a scored qualification, but the stamp is unknown, never passed.
    tokens = file_name_tokens(paths['stem'])
    qualification = qualify(tokens,
                            thresholds_from_settings_text(run['export_settings_text'], path=run['export_settings_path'])
                            if run and run.get('export_settings_text') is not None else
                            unavailable_thresholds('No run export_settings.GOAT next to this export (a library copy)'),
                            header=text)
    # A research-only unit (below_score, GOAT-EA BS42) is an attempt, never a pass: unknown, not passing and
    # not re-test eligible by default (catch-up's include_below_threshold opt-in still reaches it).
    tier = export_tier(text, paths['set'])
    research_only = tier != STANDARD_TIER
    qualification = research_only_stamp(qualification, tier)
    passing = qualification['status'] == 'passed'
    # Catch-up eligibility is a re-test policy, not qualification, and stays as it was: the EA's own
    # rounded comparison (ea_native_passed), against GOAT's minimum defaults for a library copy.
    native = qualification['ea_native_passed']
    if 'thresholds_unavailable' in qualification['missed']:
        native = qualify(tokens, thresholds_from_values(limits['min_sr'], limits['min_arf'], limits['basis']))['ea_native_passed']
    retest_eligible = bool(native)   # False for a research-only unit: its stamp says ea_native_passed=False
    # Margins say how far inside or outside each bar the export sits, so a later scored
    # qualification can weigh a near miss instead of treating the bars as rigid.
    if metrics:
        limits = dict(limits, profit_positive=metrics['profit'] > 0, arf_margin=round(metrics['arf'] - limits['min_arf'], 6),
                      sr_margin=round(metrics['sr'] - limits['min_sr'], 6), source='export_file_name_metrics')
    return dict(schema='goat-export-evidence-v1', set_path=str(paths['set']), set_sha256=info['sha256'],
                values_sha256=info['canonical_sha256'], alias=alias, member=member, export_tier=tier, research_only=research_only,
                ea_name=named and named['ea_name'], symbol=named and named['symbol'], period=named and named['period'],
                metrics=metrics, windows=windows, csv_path=str(paths['csv']) if paths['csv'].is_file() else None,
                csv_last_date=csv_end, capture=capture,
                evidence_start=start and start.isoformat(), evidence_end=end and end.isoformat(), evidence_end_source=source,
                requested_end=requested_end and requested_end.isoformat(),
                history_short=bool(capture and capture['complete'] and requested_end and end and end < requested_end),
                run=run and dict(root=run['root'], run_id=run['run_id'], back_oos_date=run['export_settings'].get('BackOOSDate'),
                                 include_back_oos=run['export_settings'].get('IncludeBackOOS'), ea_sha256=run.get('ea_sha256')),
                tester=tester, threshold=dict(limits, passing=passing, status=qualification['status'], missed=qualification['missed'],
                                              retest_eligible=retest_eligible),
                qualification=dict(qualification, set_sha256=info['sha256']), problems=problems)


def collect_sets(sources, limit=MAX_SETS):
    """Kept export SETs under each source (a .set file, member, deploy or run folder)."""
    found, seen = [], set()
    for source in sources:
        path = Path(source)
        if not path.is_absolute():
            raise ValueError('Evidence sources must be absolute paths')
        if path.is_file():
            candidates = [path] if path.suffix.lower() == '.set' else []
            if not candidates:
                raise ValueError('Evidence source file must be an exported .set: ' + str(path))
        elif path.is_dir():
            deploy = path / 'deploy'
            base = deploy if deploy.is_dir() and (path / 'export_settings.GOAT').is_file() else path
            # A run folder's research-only units (below_score) are read too, and carry their tier.
            bases = [base] + ([path / BELOW_SCORE_FOLDER] if base == deploy and (path / BELOW_SCORE_FOLDER).is_dir() else [])
            candidates = sorted(p for root in bases for p in root.rglob('*.set')
                                if not any(part.lower().endswith('.goatseq') for part in p.relative_to(root).parts[:-1]))
        else:
            raise ValueError('Evidence source not found: ' + str(path))
        for candidate in candidates:
            key = str(candidate.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
            if len(found) > limit:
                raise ValueError('More than %d exported SETs; scan fewer sources at once' % limit)
    return found


def scan(sources):
    """Read every kept export under ``sources``. Unreadable units are reported, not skipped silently."""
    runs, exports, unreadable = RunContext(), [], []
    for set_path in collect_sets(sources):
        try:
            exports.append(read_export(set_path, runs=runs))
        except (OSError, ValueError, UnicodeError) as exc:
            unreadable.append(dict(set_path=str(set_path), reason=str(exc)))
    return exports, unreadable
