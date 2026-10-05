"""Did a kept export pass its run's export thresholds? One stamp: ``goat-export-qualification-v1``.

Read only. This module never writes, launches or changes MT5, the EA's run folders or
controller state (the back-fill command that appends a sidecar lives in demo_agent).

What the EA does (V1.49 at 278ec109, the beta.21 build; V1.35-V1.48 are identical here)
---------------------------------------------------------------------------------------
* It writes each export's metrics into the FILE NAME, rounded:
  ``_Prf=`` 0 decimals, ``_SR=`` 2 decimals, ``_ARF=`` 3 decimals (``GOAT V1.49.mq5:4238-4247``).
* It reads them back from that file name (``RunAndStoreSet``, ``GOAT V1.49.mq5:4747-4752``, via
  ``Tester.mqh:787-817 FetchMetric`` = ``StringToDouble`` of the token) and stores a set only when
  ``Prf > 0`` (``:4728``).
* Its pass test compares those ROUNDED file-name values with ``MinARF``/``MinSR`` as read raw from
  ``<run>\\export_settings.GOAT`` (``:4492-4493``, no floor; a missing key reads as 0.0):
  ``if(g_allExports[idx].arf>=MinARF && g_allExports[idx].sr>=MinSR)`` (``:4566``), and
  ``SortAndTrimExports`` uses the same rounded values (``Tester.mqh:711``).
* The SET header carries SR with 3 decimals and ARF with 3 decimals
  (``; PF=1.220 RF=1.003 SR=1.073 ARF=0.084``, ``GOAT V1.49.mq5:4056``): the same
  ``TesterStatistics(STAT_SHARPE_RATIO)`` value, one more decimal for SR only.

So ``ea_native_passed`` (the file-name comparison) reproduces the EA's own decision and its log's
"N passed thresholds" exactly. ``status`` is stricter at the cut-off (Claude-Mac amendment 1):
a value within half a unit of its printed precision of the threshold could lie on either side,
so the 3-decimal header decides it; if the header is also within its half unit the set is
``unknown`` with ``missed: ['at_cutoff']``, never ``passed``.
"""
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re

SCHEMA = 'goat-export-qualification-v1'
BASIS = 'export_file_name_metrics'
MAX_SETTINGS_BYTES = 64 * 1024
MAX_SET_BYTES = 4 * 1024 * 1024
HEADER_LINES = 40
# Metric, file-name token, comparison, export setting. Profit is the EA's store condition (> 0).
CHECKS = (('Profit', 'Prf', '>', None), ('SR', 'SR', '>=', 'MinSR'), ('ARF', 'ARF', '>=', 'MinARF'))
# The EA's printed precision: file name (GOAT V1.49.mq5:4240-4245) and SET header (:4056, :4058).
FILE_NAME_DECIMALS = dict(Prf=0, SR=2, ARF=3)
HEADER_DECIMALS = dict(Prf=0, SR=3, ARF=3)
# Reasons an export cannot be judged; they appear in ``missed`` in place of metric names.
AT_CUTOFF, NO_THRESHOLDS, NO_METRICS, DISAGREE = 'at_cutoff', 'thresholds_unavailable', 'metrics_unavailable', 'header_disagrees'
SELECTION = dict(passed='passed_gate', below_threshold='best_of_failed_search', unknown='unknown')

_NAME = re.compile(r'_Trds=(?P<Trds>-?\d+(?:\.\d+)?)_Prf=(?P<Prf>-?\d+(?:\.\d+)?)_DD=(?P<DD>-?\d+(?:\.\d+)?)'
                   r'_PF=(?P<PF>-?\d+(?:\.\d+)?)_SR=(?P<SR>-?\d+(?:\.\d+)?)_ARF=(?P<ARF>-?\d+(?:\.\d+)?)$')
_HEADER = re.compile(r'^;\s*PF=-?\d+(?:\.\d+)?\s+RF=-?\d+(?:\.\d+)?\s+SR=(?P<SR>-?\d+(?:\.\d+)?)\s+ARF=(?P<ARF>-?\d+(?:\.\d+)?)\s*$')
_RETURN = re.compile(r'^;\s*Return=(?P<Prf>-?\d+(?:\.\d+)?)\s')
_LEADING_NUMBER = re.compile(r'\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))')


class Token:
    """A metric exactly as printed: its value and how many decimals it was printed with."""
    __slots__ = ('value', 'decimals', 'source')

    def __init__(self, text, source, decimals=None):
        text = str(text).strip()
        self.value = Decimal(text)
        if not self.value.is_finite():
            raise InvalidOperation(text)
        self.decimals = decimals if decimals is not None else (len(text.split('.', 1)[1]) if '.' in text else 0)
        self.source = source

    @property
    def half_unit(self):
        return Decimal(5) / (Decimal(10) ** (self.decimals + 1))


def _decode(raw):
    return raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')


# ---------------------------------------------------------------------------
# Inputs: thresholds, file-name metrics, header metrics
# ---------------------------------------------------------------------------

def ea_setting(text, key):
    """``FetchExportSetting`` (Optimizer.mqh:3833-3860): the file must contain ``[Export]``; the
    first trimmed line starting ``key=`` wins. None when the EA would read an empty string."""
    if '[Export]' not in text:
        return None
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith(key + '='):
            return line[len(key) + 1:]
    return None


def thresholds_from_settings_text(text, source='run_export_settings_file', path=None):
    """The thresholds the EA compared with. A missing or non-numeric MinSR/MinARF means the EA
    compared with 0.0: that is no threshold at all, so the result is unavailable (never 'passed')."""
    values, problems = {}, []
    for key in ('MinSR', 'MinARF'):
        raw = ea_setting(text, key)
        match = _LEADING_NUMBER.match(raw or '')
        if raw is None or not match:
            problems.append(key + ' missing from the export settings (the EA would have compared with 0.0)')
            continue
        values[key] = Decimal(match.group(1))
    if problems:
        return dict(available=False, min_sr=None, min_arf=None, source=source, path=path, problems=problems)
    return dict(available=True, min_sr=values['MinSR'], min_arf=values['MinARF'], source=source, path=path, problems=[])


def thresholds_from_values(min_sr, min_arf, source):
    """Thresholds from a frozen configuration (numbers or strings), e.g. a job's ``export`` block."""
    try:
        values = dict(MinSR=Decimal(str(min_sr)), MinARF=Decimal(str(min_arf)))
    except (InvalidOperation, TypeError, ValueError):
        values = None
    if values is None or min_sr is None or min_arf is None or any(not v.is_finite() for v in values.values()):
        return dict(available=False, min_sr=None, min_arf=None, source=source, path=None,
                    problems=['MinSR/MinARF missing or not numeric in ' + source])
    return dict(available=True, min_sr=values['MinSR'], min_arf=values['MinARF'], source=source, path=None, problems=[])


def unavailable_thresholds(reason, source='none'):
    return dict(available=False, min_sr=None, min_arf=None, source=source, path=None, problems=[reason])


def read_run_thresholds(run_root):
    """``<run>\\export_settings.GOAT``, the file the EA itself read (GoatOptExportSettingsPath)."""
    path = Path(run_root) / 'export_settings.GOAT'
    try:
        if not path.is_file():
            return unavailable_thresholds('No export_settings.GOAT in the run folder', source='none')
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            return unavailable_thresholds('export_settings.GOAT exceeds its byte bound', source='none')
        text = _decode(path.read_bytes())
    except (OSError, UnicodeError) as error:
        return unavailable_thresholds('export_settings.GOAT unreadable: ' + str(error)[:160], source='none')
    return thresholds_from_settings_text(text, path=str(path))


def _printed(text, source, spec):
    """A token at the precision its writer used: the EA's documented decimals, or more if printed."""
    token = Token(text, source)
    token.decimals = max(token.decimals, spec)
    return token


def file_name_tokens(stem):
    """Printed Prf/SR/ARF of an export stem, or None when the name is not a GOAT export name.

    The precision is the EA's (``DoubleToString`` 0/2/3 decimals, GOAT V1.49.mq5:4240-4245): the
    half unit is 0.005 for SR and 0.0005 for ARF even when a hand-made name drops trailing zeros."""
    match = _NAME.search(stem)
    if not match:
        return None
    try:
        return {key: _printed(match.group(key), 'file_name', FILE_NAME_DECIMALS[key]) for key in ('Prf', 'SR', 'ARF')}
    except InvalidOperation:
        return None


def tokens_from_numbers(metrics):
    """File-name tokens from already parsed numbers (``sr``, ``arf``, optional ``profit``/``net``)."""
    if not isinstance(metrics, dict):
        return None
    try:
        out = dict(SR=Token(repr(float(metrics['sr'])), 'file_name', FILE_NAME_DECIMALS['SR']),
                   ARF=Token(repr(float(metrics['arf'])), 'file_name', FILE_NAME_DECIMALS['ARF']))
        profit = metrics.get('profit', metrics.get('net'))
        if profit is not None:
            out['Prf'] = Token(repr(float(profit)), 'file_name', FILE_NAME_DECIMALS['Prf'])
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    return out


def header_tokens(text):
    """SR, ARF (3 decimals) and Return (0 decimals) from the SET header the EA wrote, or {}."""
    found = {}
    for index, line in enumerate(text.splitlines()):
        if index >= HEADER_LINES:
            break
        line = line.lstrip('﻿')
        match = _HEADER.match(line)
        if match and 'SR' not in found:
            try:
                found['SR'] = _printed(match.group('SR'), 'set_header', HEADER_DECIMALS['SR'])
                found['ARF'] = _printed(match.group('ARF'), 'set_header', HEADER_DECIMALS['ARF'])
            except InvalidOperation:
                return {}
        match = _RETURN.match(line)
        if match and 'Prf' not in found:
            try:
                found['Prf'] = _printed(match.group('Prf'), 'set_header', HEADER_DECIMALS['Prf'])
            except InvalidOperation:
                pass
    return found


# ---------------------------------------------------------------------------
# The judgement
# ---------------------------------------------------------------------------

def _number(value):
    return None if value is None else float(value)


def _side(token, threshold, op):
    """True/False when the printed value is decisively on one side, None when within its half unit."""
    diff = token.value - threshold
    if abs(diff) <= token.half_unit:
        return None
    return diff > 0


def _ea_compare(token, threshold, op):
    """The EA's own comparison of the printed (rounded) value."""
    return token.value > threshold if op == '>' else token.value >= threshold


def qualify(file_tokens, thresholds, *, header=None):
    """One ``goat-export-qualification-v1`` stamp.

    ``file_tokens``: ``file_name_tokens(stem)`` (or ``tokens_from_numbers``). ``thresholds``: one of
    the ``thresholds_*`` helpers. ``header``: the SET text, its ``header_tokens``, or a callable
    returning either; it is read only when a file-name value sits at the cut-off.
    """
    limits = dict(min_sr=_number(thresholds.get('min_sr')), min_arf=_number(thresholds.get('min_arf')),
                  source=thresholds.get('source'))
    stamp = dict(schema=SCHEMA, basis=BASIS, thresholds=limits, checks=[], missed=[], status='unknown',
                 ea_native_passed=None, selection=SELECTION['unknown'], reason=None)
    if not file_tokens or not all(key in file_tokens for key in ('SR', 'ARF')):
        stamp.update(missed=[NO_METRICS], reason='The file name does not carry the EA export metrics (_Prf=, _SR=, _ARF=)')
        return stamp
    if not thresholds.get('available'):
        stamp.update(missed=[NO_THRESHOLDS], reason='; '.join(thresholds.get('problems') or ['Export thresholds unavailable']))
        stamp['checks'] = [dict(metric=metric, value=float(file_tokens[token].value), source='file_name',
                                decimals=file_tokens[token].decimals, op=op, threshold=None, passed=None, margin=None,
                                at_cutoff=False) for metric, token, op, _ in CHECKS if token in file_tokens]
        return stamp
    limit_of = dict(Prf=Decimal(0), SR=thresholds['min_sr'], ARF=thresholds['min_arf'])
    header_cache = []

    def header_value(token):
        if not header_cache:
            value = header() if callable(header) else header
            if isinstance(value, (bytes, bytearray)):
                value = _decode(bytes(value))
            header_cache.append(header_tokens(value) if isinstance(value, str) else (value or {}))
        return header_cache[0].get(token)

    native, cutoff, failed, disagree = [], False, [], False
    for metric, token, op, _ in CHECKS:
        printed = file_tokens.get(token)
        if printed is None:
            continue   # profit is optional for callers that only have SR/ARF
        threshold = limit_of[token]
        native.append(_ea_compare(printed, threshold, op))
        check = dict(metric=metric, value=float(printed.value), source='file_name', decimals=printed.decimals, op=op,
                     threshold=float(threshold), passed=None, margin=round(float(printed.value - threshold), 6), at_cutoff=False)
        side = _side(printed, threshold, op)
        if side is None:
            precise = header_value(token)
            if precise is not None and precise.decimals > printed.decimals:
                if abs(precise.value - printed.value) > printed.half_unit + precise.half_unit:
                    disagree = True
                    check.update(passed=None, at_cutoff=True, header_value=float(precise.value))
                else:
                    side = _side(precise, threshold, op)
                    check.update(value=float(precise.value), source='set_header', decimals=precise.decimals,
                                 margin=round(float(precise.value - threshold), 6), file_name_value=float(printed.value))
            if side is None and not check.get('at_cutoff'):
                check['at_cutoff'] = True
        if side is not None:
            check['passed'] = side
            if not side:
                failed.append(metric)
        else:
            cutoff = True
        stamp['checks'].append(check)
    stamp['ea_native_passed'] = all(native)
    if failed:
        stamp.update(status='below_threshold', missed=failed + ([AT_CUTOFF] if cutoff else []))
    elif cutoff:
        stamp.update(status='unknown', missed=[DISAGREE] if disagree else [AT_CUTOFF],
                     reason=('The SET header disagrees with the file name at the cut-off' if disagree else
                             'A metric sits within its printed precision of the threshold; neither side can be proven'))
    else:
        stamp['status'] = 'passed'
    stamp['selection'] = SELECTION[stamp['status']]
    return stamp


def stamp_set(set_path, thresholds, *, with_sha256=True):
    """Stamp one kept export unit by its ``.set`` path.

    With ``with_sha256`` the SET's SHA-256 (what the desktop matches) is added and the file is read
    once; without it the file is opened only when a value sits at the cut-off (status calls)."""
    path = Path(set_path)
    stem = path.name[:-4] if path.name.lower().endswith('.set') else path.stem
    raw_cache = []

    def raw():
        if not raw_cache:
            with path.open('rb') as stream:
                data = stream.read(MAX_SET_BYTES + 1)
            if len(data) > MAX_SET_BYTES:
                raise ValueError('SET exceeds its byte bound: ' + path.name)
            raw_cache.append(data)
        return raw_cache[0]

    stamp = dict(qualify(file_name_tokens(stem), thresholds, header=raw), set_name=path.name)
    if with_sha256:
        stamp['set_sha256'] = hashlib.sha256(raw()).hexdigest()
    return stamp


def summarize(stamps):
    """Counts for one member's kept sets and that member's class (passed beats unknown beats below)."""
    counts = dict(passed=0, below_threshold=0, unknown=0)
    for stamp in stamps:
        counts[stamp['status']] += 1
    member = ('passed' if counts['passed'] else 'unknown' if counts['unknown'] else
              'below_threshold' if counts['below_threshold'] else None)
    return dict(counts, kept=len(stamps), member=member)


def public_thresholds(thresholds):
    """The stamped thresholds a status reply carries (numbers, or None when unavailable)."""
    if not thresholds or not thresholds.get('available'):
        return None
    return dict(min_sr=float(thresholds['min_sr']), min_arf=float(thresholds['min_arf']), source=thresholds.get('source'))


def threshold_words(public):
    """``SR ≥ 2.5, ARF ≥ 0.2`` for a headline."""
    return 'SR ≥ %g, ARF ≥ %g' % (public['min_sr'], public['min_arf'])


def missed_words(stamp):
    """``SR 2.91 passes · ARF 0.12 < 0.2 misses`` for one stamp (agent and UI wording)."""
    parts = []
    for check in stamp.get('checks') or []:
        if check['metric'] == 'Profit':
            continue
        value = ('%.' + str(check['decimals']) + 'f') % check['value']
        if check['passed'] is True:
            parts.append('%s %s passes' % (check['metric'], value))
        elif check['passed'] is False:
            parts.append('%s %s < %g misses' % (check['metric'], value, check['threshold']))
        elif check['threshold'] is not None:
            parts.append('%s %s at the %g cut-off, not proven' % (check['metric'], value, check['threshold']))
    return ' · '.join(parts)


# ---------------------------------------------------------------------------
# Whole runs: every kept set, cross-checked against the EA's own log (back-fill)
# ---------------------------------------------------------------------------

BACKFILL_SCHEMA = 'goat-export-qualification-run-v1'
MAX_LOG_BYTES = 256 * 1024 * 1024
MAX_RUN_SETS = 20000
CROSSCHECK_MISMATCH = 'log_crosscheck_mismatch'
_SEQUENCE = re.compile(r'Export sequence complete: \d+ attempts.*?(\d+) passed thresholds')
_ADJUSTED = re.compile(r'Export Adjustment sequence complete: \d+ attempts.*?(\d+) passed thresholds')
_TRIM = re.compile(r'SortAndTrimExports: Total=(\d+) Passing=(\d+) Kept=(\d+)')


def log_cycles(text):
    """The EA's export cycles in ``log.GOAT`` order: one per "Export sequence complete" line.

    Each cycle keeps its "N passed thresholds" count, the ``SortAndTrimExports: Total= Passing= Kept=``
    lines that follow it, and, with AdjustLots, the "Export Adjustment sequence complete" count and the
    trim of the adjusted re-runs (GOAT V1.49.mq5:4600-4646)."""
    cycles = []
    for line in text.splitlines():
        match = _SEQUENCE.search(line)
        if match:
            cycles.append(dict(passed=int(match.group(1)), trims=[], adjusted=None, adjusted_trims=[]))
            continue
        if not cycles:
            continue
        match = _ADJUSTED.search(line)
        if match:
            cycles[-1]['adjusted'] = int(match.group(1))
            continue
        match = _TRIM.search(line)
        if match:
            cycle = cycles[-1]
            trim = dict(total=int(match.group(1)), passing=int(match.group(2)), kept=int(match.group(3)))
            (cycle['adjusted_trims'] if cycle['adjusted'] is not None else cycle['trims']).append(trim)
    return cycles


def kept_passing(cycle, adjust_lots):
    """(passing sets the EA kept, basis) for one cycle.

    The count that matters is the one AFTER trimming: ``SortAndTrimExports`` logs ``Passing=`` for the
    sets it keeps (Tester.mqh:708-717; Claude-Mac review of GOAT-EA#164). A cycle with one stored set
    never logs it: ``SortAndTrimExports`` returns before its log line when n <= 1 (Tester.mqh:694), and
    a cycle with none never calls it (GOAT V1.49.mq5:4602). For those, the cycle's own "N passed
    thresholds" count is exact (0 or 1, the single set kept as it is). With AdjustLots the kept sets are
    the adjusted re-runs, so their adjustment count and trim decide."""
    if adjust_lots:
        if cycle['adjusted'] is None:
            return 0, 'no_adjusted_exports'
        if cycle['adjusted_trims']:
            return cycle['adjusted_trims'][-1]['passing'], 'sort_and_trim'
        return cycle['adjusted'], 'single_export_passed_thresholds'
    if cycle['trims']:
        return cycle['trims'][-1]['passing'], 'sort_and_trim'
    return cycle['passed'], 'single_export_passed_thresholds'


def read_log(log_path):
    """``log.GOAT`` as text (UTF-16 as the EA writes it), or None when missing, too large or unreadable."""
    path = Path(log_path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_LOG_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    return raw.decode('utf-16', errors='replace') if raw.startswith(b'\xff\xfe') or b'\x00' in raw[:400] else \
        raw.decode('utf-8', errors='replace')


def scan_run(run_root, *, generated_at=None):
    """Every kept export of one run folder, stamped, with the EA log cross-check (read only).

    Each entry is ``{set_path, set_name, set_sha256, member, symbol, qualification}``; the judgement sits
    under ``qualification`` so the held-out guard redacts it whole for a locked export. The cross-check
    compares what the EA's own file-name comparison reproduces (``ea_native_passed``) with the passing
    sets the EA logged as kept (``kept_passing``): their sum and the number of members with any. When
    they differ, or the log is unreadable, nothing in this run may read as passed: each passed stamp
    becomes unknown (``missed: ['log_crosscheck_mismatch']``), so a stale or partial folder never
    overstates. A mismatch can also mean the EA kept a non-passer over a passer (it keeps the top
    ``Passing=`` sets by ARF x SR, Tester.mqh:696-716); that is not attributable from the log, so it
    fails closed too.
    """
    run_root = Path(run_root)
    if not any((run_root / name).exists() for name in ('deploy', 'export_settings.GOAT', 'log.GOAT', 'manifest.json')):
        raise ValueError('Not a GOAT run folder (no deploy folder, export_settings.GOAT, log.GOAT or manifest.json): ' + str(run_root))
    thresholds = read_run_thresholds(run_root)
    settings_text = ''
    try:
        settings_path = run_root / 'export_settings.GOAT'
        if settings_path.is_file() and settings_path.stat().st_size <= MAX_SETTINGS_BYTES:
            settings_text = _decode(settings_path.read_bytes())
    except (OSError, UnicodeError):
        settings_text = ''
    adjust_lots = (ea_setting(settings_text, 'AdjustLots') or '0').strip() not in ('', '0')
    entries, members = [], {}
    deploy = run_root / 'deploy'
    for alias in sorted(p for p in deploy.iterdir() if p.is_dir()) if deploy.is_dir() else []:
        for symbol in sorted(p for p in alias.iterdir() if p.is_dir()):
            for set_path in sorted(p for p in symbol.glob('*.set') if p.is_file()):
                if len(entries) >= MAX_RUN_SETS:
                    raise ValueError('More than %d kept sets in one run; refusing a partial scan' % MAX_RUN_SETS)
                stamp = stamp_set(set_path, thresholds)
                entry = dict(set_path=str(set_path), set_name=stamp['set_name'], set_sha256=stamp['set_sha256'],
                             member=alias.name, symbol=symbol.name, qualification=stamp)
                entries.append(entry)
                members.setdefault((alias.name, symbol.name), []).append(stamp)
    stamps = [entry['qualification'] for entry in entries]
    native_sets = sum(1 for s in stamps if s.get('ea_native_passed'))
    native_members = sum(1 for kept in members.values() if any(s.get('ea_native_passed') for s in kept))
    crosscheck = dict(log_path=str(run_root / 'log.GOAT'), adjust_lots=adjust_lots,
                      stamped_native_passed_sets=native_sets, stamped_members_with_native_pass=native_members)
    text = read_log(run_root / 'log.GOAT')
    if text is None:
        crosscheck.update(status='unavailable', reason='log.GOAT missing or unreadable: the EA log cannot confirm these stamps')
    else:
        kept = [kept_passing(cycle, adjust_lots) for cycle in log_cycles(text)]
        bases = {}
        for _, basis in kept:
            bases[basis] = bases.get(basis, 0) + 1
        crosscheck.update(log_export_cycles=len(kept), log_kept_passing_sets=sum(n for n, _ in kept),
                          log_members_with_kept_pass=sum(1 for n, _ in kept if n > 0), log_bases=bases)
        same = (crosscheck['log_kept_passing_sets'] == native_sets
                and crosscheck['log_members_with_kept_pass'] == native_members)
        crosscheck['status'] = 'match' if same else 'mismatch'
    if crosscheck['status'] != 'match':
        for stamp in stamps:
            if stamp['status'] == 'passed':
                stamp.update(status='unknown', missed=[CROSSCHECK_MISMATCH], selection=SELECTION['unknown'],
                             status_before_crosscheck='passed',
                             reason='The EA log does not confirm this run\'s pass counts (%s)' % crosscheck['status'])
    counts = dict(members=len(members), sets=len(stamps))
    for status in ('passed', 'below_threshold', 'unknown'):
        counts[status + '_sets'] = sum(1 for s in stamps if s['status'] == status)
        counts[status + '_members'] = sum(1 for kept in members.values() if summarize(kept)['member'] == status)
    return dict(schema=BACKFILL_SCHEMA, run_id=run_root.name, run_root=str(run_root), generated_at=generated_at,
                thresholds=dict(public_thresholds(thresholds) or {}, available=bool(thresholds.get('available')),
                                path=thresholds.get('path'), problems=thresholds.get('problems') or []),
                log_crosscheck=crosscheck, counts=counts, stamps=entries,
                provenance=dict(method='Kept sets under deploy/<member>/<symbol>, judged by goat-export-qualification-v1 '
                                       'from their file-name metrics (SET header at the cut-off) against the run\'s own '
                                       'export_settings.GOAT, cross-checked with the passing sets the EA logged as kept '
                                       '(SortAndTrimExports Passing=, or the single-export cycle\'s "passed thresholds" '
                                       'count). Read only; receipts and earlier records are never rewritten.',
                                basis=BASIS, stamp_schema=SCHEMA))


def guard_scan(result, guard):
    """A scan reply after the held-out guard: per-export redaction comes from ``guard`` (guard_output);
    a run with any redacted export also loses its run counts and log cross-check, and the totals go
    when any run lost them, since those aggregate locked results."""
    guarded = guard(result)
    if not isinstance(guarded, dict) or not isinstance(guarded.get('runs'), list):
        return guarded
    marker = None
    for run in guarded['runs']:
        if not isinstance(run, dict):
            continue
        entries = run.get('stamps')
        locked = [e.get('qualification') for e in entries if isinstance(e, dict) and isinstance(e.get('qualification'), dict)
                  and e['qualification'].get('locked') is True] if isinstance(entries, list) else []
        if isinstance(entries, dict) and entries.get('locked') is True:
            locked = [entries]
        if locked:
            marker = marker or locked[0]
            run['counts'] = locked[0]
            run['log_crosscheck'] = locked[0]
    if marker is not None:
        guarded['counts'] = marker
    return guarded


