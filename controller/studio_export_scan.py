"""Inventory one bound export directory; never equate exports with qualified results."""
from decimal import Decimal
import hashlib
from pathlib import Path
import re
from studio_export_inputs import verify_export_inputs
from studio_equity_csv import inspect_equity_csv
from studio_export_qualification import file_name_tokens, public_thresholds, qualify, thresholds_from_values

# goat-export-qualification-v1 status -> the file status consumers already read (append-only).
STATUS_OF = dict(passed='native_threshold_candidate', below_threshold='below_native_thresholds',
                 unknown='native_threshold_unknown')
INPUT_MISMATCH = 'Fixed export input mismatch: '   # studio_export_inputs.verify_export_inputs, followed by the input's name
MAX_UNVERIFIED_FILES = 100


def unverified_summary(reports):
    """The exports a finished batch's report left ``unverified``, said once for the whole batch (GOAT-EA#315).

    In hunt round 13a every member after the first ``Ledger_Mode=1`` member exported with ``Ledger_Mode=1`` although its
    own SET omitted it. Each export was marked ``unverified`` (``Fixed export input mismatch: Ledger_Mode``) deep in its
    member's report, and the batch result said nothing. This is the batch-level sentence: how many, of which members,
    and the inputs involved. ``reports`` is observe_reports' value (one member, or ``members``); None before any report."""
    if not isinstance(reports, dict):
        return None
    members = reports['members'] if isinstance(reports.get('members'), list) else [reports]
    files, inputs, reasons, indices = [], {}, {}, set()
    for member in members:
        exports = member.get('exports') if isinstance(member, dict) else None
        for item in (exports.get('files') or []) if isinstance(exports, dict) else []:
            if not isinstance(item, dict) or item.get('status') != 'unverified':
                continue
            reason = item.get('reason') or 'No reason recorded'
            reasons[reason] = reasons.get(reason, 0) + 1
            if reason.startswith(INPUT_MISMATCH):
                name = reason[len(INPUT_MISMATCH):]
                inputs[name] = inputs.get(name, 0) + 1
            indices.add(member.get('index'))
            exported = next((a for a in item.get('artifacts') or [] if str(a.get('path', '')).lower().endswith('.set')), {})
            files.append(dict(index=member.get('index'), run_alias=member.get('run_alias'), symbol=member.get('symbol'),
                              name=item.get('name'), reason=reason, set_path=exported.get('path'), set_sha256=exported.get('sha256')))
    ranked = sorted(reasons.items(), key=lambda entry: (-entry[1], entry[0]))
    if not files:
        plain = 'No export of this batch is unverified.'
    else:
        said = ['%s differs from the member\'s own SET in %d (an input the SET omits counts at its default)' % (name, count)
                for name, count in sorted(inputs.items(), key=lambda entry: (-entry[1], entry[0]))]
        said += ['%s (%d)' % (reason, count) for reason, count in ranked if not reason.startswith(INPUT_MISMATCH)]
        plain = ('%d export%s of %d member%s %s unverified: %s. An unverified export is not what its member asked for; do not count '
                 'it or re-test it without saying so.'
                 % (len(files), '' if len(files) == 1 else 's', len(indices), '' if len(indices) == 1 else 's',
                    'is' if len(files) == 1 else 'are', '; '.join(said)))
    return dict(count=len(files), member_count=len(indices), inputs=dict(sorted(inputs.items())),
                reasons=[dict(reason=reason, count=count) for reason, count in ranked],
                files=files[:MAX_UNVERIFIED_FILES], files_omitted=max(0, len(files) - MAX_UNVERIFIED_FILES), plain=plain)


def scan_exports(directory, source_raw, schema, back_passes, forward_passes, *,
                 alias, symbol, period, expert_name, min_arf, min_sr, windows=None):
    root = Path(directory).resolve()
    result = dict(status='exports_not_observed', files=[], qualified_count=None,
                  release_permitted=False, performance_verified=False)
    limits = [Decimal(str(min_arf)), Decimal(str(min_sr))]
    if any(not n.is_finite() or n < 0 for n in limits):
        raise ValueError('Finite nonnegative export thresholds required')
    thresholds = thresholds_from_values(min_sr, min_arf, 'job_configuration')
    if not root.is_dir():
        return result
    files = sorted(p for p in root.iterdir() if p.suffix.lower() in ('.set', '.csv'))
    if not files:
        return result
    # Inspect only the caller's exact alias/symbol directory. No broad recursive
    # search or fallback to another run when a report is absent.
    stems = sorted({p.stem for p in files})
    prefix = re.escape(f'{expert_name} {symbol},{period}')
    number = r'(-?\d+(?:\.\d+)?)'
    pattern = prefix + ''.join('_'+key+'='+number for key in ('Trds','Prf','DD','PF','SR','ARF'))
    for stem in stems:
        set_path, csv_path = root/(stem+'.set'), root/(stem+'.csv')
        item = dict(name=stem, status='unverified')
        result['files'].append(item)
        if any(not p.resolve().is_relative_to(root) for p in (set_path, csv_path)):
            item['reason'] = 'Export path escapes run directory'
            continue
        if not set_path.is_file() or not csv_path.is_file():
            item['reason'] = 'Incomplete SET/CSV pair'
            continue
        match = re.fullmatch(pattern, stem)
        if not match:
            item['reason'] = 'Export filename identity/metric format mismatch'
            continue
        raw, csv_raw = set_path.read_bytes(), csv_path.read_bytes()
        item['artifacts'] = [dict(path=str(p), sha256=hashlib.sha256(b).hexdigest())
                             for p, b in ((set_path, raw), (csv_path, csv_raw))]
        if not csv_raw:
            item['reason'] = 'Empty CSV'
            continue
        metrics = dict(zip(('Trds','Prf','DD','PF','SR','ARF'), map(Decimal, match.groups())))
        item['native_filename_metrics'] = {k:str(v) for k,v in metrics.items()}
        try:
            item['equity_samples'] = inspect_equity_csv(csv_raw)
            item['input_identity'] = verify_export_inputs(source_raw, raw, schema, back_passes,
                                                         forward_passes, alias=alias, standard_mode=9)
        except ValueError as exc:
            item['reason'] = str(exc)
            continue
        # One shared judgement (goat-export-qualification-v1): at the cut-off the SET header decides,
        # and a set that cannot be proven either way is unknown, never a candidate.
        stamp = qualify(file_name_tokens(stem), thresholds, header=raw)
        item['qualification'] = dict(stamp, set_sha256=hashlib.sha256(raw).hexdigest())
        item['status'] = STATUS_OF[stamp['status']]
        if windows is not None:
            # goat-export-window-metrics-v1: exact metrics before FOOS (preFoos, selectionWindow), computed from
            # this unit's equity CSV and capture deals. Best effort: never changes the status above.
            from studio_window_metrics import export_window_metrics
            try:
                item['window_metrics'] = export_window_metrics(set_path, csv_raw=csv_raw, **windows)
            except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
                item['window_metrics'] = dict(status='unavailable', reason=str(exc)[:240])
    result['status'] = 'export_inventory_observed'
    result['native_threshold_candidate_count'] = sum(f['status']=='native_threshold_candidate' for f in result['files'])
    result['below_native_threshold_count'] = sum(f['status']=='below_native_thresholds' for f in result['files'])
    result['native_threshold_unknown_count'] = sum(f['status']=='native_threshold_unknown' for f in result['files'])
    result['unverified_count'] = sum(f['status']=='unverified' for f in result['files'])
    result['thresholds'] = public_thresholds(thresholds)
    result['limits'] = 'Filename metrics mirror native selection, not independently verified performance. CSV content, replay coverage and export completion remain unverified.'
    return result
