"""Inventory one bound export directory; never equate exports with qualified results."""
from decimal import Decimal
import hashlib
from pathlib import Path
import re
from studio_export_inputs import verify_export_inputs
from studio_equity_csv import inspect_equity_csv


def scan_exports(directory, source_raw, schema, back_passes, forward_passes, *,
                 alias, symbol, period, expert_name, min_arf, min_sr):
    root = Path(directory).resolve()
    result = dict(status='exports_not_observed', files=[], qualified_count=None,
                  release_permitted=False, performance_verified=False)
    limits = [Decimal(str(min_arf)), Decimal(str(min_sr))]
    if any(not n.is_finite() or n < 0 for n in limits):
        raise ValueError('Finite nonnegative export thresholds required')
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
        passing = metrics['Prf'] > 0 and metrics['ARF'] >= limits[0] and metrics['SR'] >= limits[1]
        item['status'] = 'native_threshold_candidate' if passing else 'below_native_thresholds'
    result['status'] = 'export_inventory_observed'
    result['native_threshold_candidate_count'] = sum(f['status']=='native_threshold_candidate' for f in result['files'])
    result['limits'] = 'Filename metrics mirror native selection, not independently verified performance. CSV content, replay coverage and export completion remain unverified.'
    return result
