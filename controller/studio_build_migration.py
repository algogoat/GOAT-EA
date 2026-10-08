"""Build-migration re-test: an older build's SETs re-tested on the installed newer EA build (goatai#2350).

A normal OOS catch-up (studio_catchup) refuses an export made by another EA build: its re-test would not be
the same test, so it could never carry the original's status. A build migration does it on purpose. The plan
key ``build_migration`` names the target build and, per SET, the build that made it and the exact original
export (path and SHA-256). Each member is one non-optimized pass of the frozen values on the target build,
from the original start through the new evidence end, exactly as a catch-up re-test runs.

What comes out is a structurally different record, never a catch-up verdict (Claude-Mac, #2350 6069755001):

* ``kind: build_migration_retest`` and ``provenance: build-migration-retest:<short build>`` (B43 for
  V1.49-BETA17-43), in ``build-migration-retest.json`` next to the re-test unit, never ``evidence-version.json``;
* no ``verdict``, no ``catch_up`` import stamp and no ``comparison``: the evidence-version reader, the
  catch-up report, the equivalence canary, the OOS-rule judge and gate calibration check ``kind`` and refuse
  or ignore these records (``refuse``), so none of them can take one as a verdict on the original export;
* a drift report against the exact original over the original's own span (trades, PF, max DD, return) with
  the verdict ``reproduced`` or ``drifted`` (``TOLERANCES``);
* the re-test's own windows (BOOS/SAMPLE/FWD/FOOS, every one measured on the re-test alone) and the new
  weeks, so the unseen weeks can be judged on the new-build result as a new candidate.

A SET exported without a .goatseq (the V1.47 exports) gets one from the re-test: the original SET bytes are
staged unchanged as the capture's ``source-inputs.set``, and the SET itself is never written.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

KIND = 'build_migration_retest'
PROVENANCE_PREFIX = 'build-migration-retest:'
RECORD_SCHEMA = 'goat-build-migration-retest-v1'
DRIFT_SCHEMA = 'goat-build-migration-drift-v1'
RECORD_FILE = 'build-migration-retest.json'
RESULT_STATUS = 'verified_build_migration_retest'
REPRODUCED, DRIFTED = 'reproduced', 'drifted'
# Claude-Mac, goatai#2350 6069528877: a re-test "reproduced" its original when, over the original span,
# |delta PF| <= 0.15 (absolute), |delta trades| <= 10% and |delta max DD| <= 20% (both relative to the
# original); anything else, an unmeasurable metric included, is "drifted". Boundaries are inclusive.
TOLERANCES = dict(pf_abs=Decimal('0.15'), trades_rel=Decimal('0.10'), max_dd_rel=Decimal('0.20'), source='goatai#2350 6069528877')
PLAN_KEYS = {'target_build', 'originals'}
PLAN_OPTIONAL = {'target_ea_sha256', 'note'}
ORIGINAL_KEYS = {'original_path', 'original_sha256', 'source_build'}
ORIGINAL_OPTIONAL = {'source_ea_sha256'}
BUILD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._@:+-]{0,95}')
SHA = re.compile(r'[0-9a-f]{64}')


class NotAVerdict(ValueError):
    """A build-migration record reached a consumer that only reads catch-up verdicts."""


def short_build(build_id):
    """``V1.49-BETA17-43`` -> ``B43``: the build number after the last hyphen; else the ID itself."""
    match = re.search(r'-(\d+)$', build_id)
    return 'B' + match[1] if match else build_id


def provenance(build_id):
    return PROVENANCE_PREFIX + short_build(build_id)


def is_record(value):
    """True for a build-migration record, a result or summary of one, or a verdict-shaped part of one."""
    if not isinstance(value, dict):
        return False
    if value.get('kind') == KIND or value.get('schema') in (RECORD_SCHEMA, DRIFT_SCHEMA) or value.get('status') == RESULT_STATUS:
        return True
    if str(value.get('provenance') or '').startswith(PROVENANCE_PREFIX):
        return True
    return any(isinstance(value.get(key), dict) and value[key].get('kind') == KIND for key in ('summary', 'record', 'verdict'))


def refuse(value, consumer):
    """Type guard for every catch-up / equivalence consumer: a build-migration record is never a verdict."""
    if is_record(value):
        raise NotAVerdict('%s reads catch-up verdicts; this is a %s record (%s), a new-build re-test that is never a '
                          'verdict on the original export' % (consumer, KIND, value.get('provenance') or KIND))
    return value


def key(path):
    return os.path.normcase(os.path.normpath(str(path)))


def validate_plan(value, sets):
    """The plan's ``build_migration`` block, normalized: target build and one recorded original per SET.

    Refuses a SET with no recorded original, naming it.
    """
    if not isinstance(value, dict) or not PLAN_KEYS <= set(value) or set(value) - PLAN_KEYS - PLAN_OPTIONAL:
        raise ValueError('build_migration requires target_build and originals (optional: target_ea_sha256, note)')
    target = value['target_build']
    if not isinstance(target, str) or not BUILD.fullmatch(target):
        raise ValueError('build_migration.target_build must be an EA build ID such as V1.49-BETA17-43')
    target_sha = value.get('target_ea_sha256')
    if target_sha is not None and (not isinstance(target_sha, str) or not SHA.fullmatch(target_sha)):
        raise ValueError('build_migration.target_ea_sha256 must be 64 lowercase hex')
    entries = value['originals']
    if not isinstance(entries, list):
        raise ValueError('build_migration.originals must list one recorded original per SET')
    by_path = {}
    for entry in entries:
        if not isinstance(entry, dict) or not ORIGINAL_KEYS <= set(entry) or set(entry) - ORIGINAL_KEYS - ORIGINAL_OPTIONAL:
            raise ValueError('Each build_migration original needs original_path, original_sha256 and source_build '
                             '(optional: source_ea_sha256): %r' % (entry,))
        path = entry['original_path']
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('build_migration original_path must be an absolute exported .set path: %r' % (path,))
        if not isinstance(entry['original_sha256'], str) or not SHA.fullmatch(entry['original_sha256']):
            raise ValueError('build_migration original_sha256 must be 64 lowercase hex for SET %s' % path)
        if not isinstance(entry['source_build'], str) or not BUILD.fullmatch(entry['source_build']):
            raise ValueError('build_migration source_build must name the EA build that made SET %s' % path)
        source_sha = entry.get('source_ea_sha256')
        if source_sha is not None and (not isinstance(source_sha, str) or not SHA.fullmatch(source_sha)):
            raise ValueError('build_migration source_ea_sha256 must be 64 lowercase hex for SET %s' % path)
        if key(path) in by_path:
            raise ValueError('build_migration names SET %s twice' % path)
        by_path[key(path)] = dict(entry)
    wanted = {key(p) for p in sets}
    for path in sets:
        if key(path) not in by_path:
            raise ValueError('build_migration has no recorded original for SET %s; every SET needs its source_build, '
                             'original_sha256 and original_path, nothing was planned' % path)
    extra = sorted(entry['original_path'] for k, entry in by_path.items() if k not in wanted)
    if extra:
        raise ValueError('build_migration records an original that is not in sets: %s' % extra[0])
    return dict(target_build=target, target_ea_sha256=target_sha, originals=by_path)


def check_original(entry, set_path):
    """The recorded original must be this SET, unchanged. Raises naming the SET."""
    try:
        raw = Path(entry['original_path']).read_bytes()
    except OSError as exc:
        raise ValueError('build_migration: the recorded original of SET %s cannot be read (%s)' % (set_path, exc)) from None
    actual = hashlib.sha256(raw).hexdigest()
    if actual != entry['original_sha256']:
        raise ValueError('build_migration: SET %s no longer matches its recorded original (sha256 %s, recorded %s)'
                         % (set_path, actual[:12], entry['original_sha256'][:12]))
    return raw


def output_root(value, *, windows=None):
    """A catch-up ``output_root``: an absolute local folder path. UNC and device paths are refused."""
    windows = (os.name == 'nt') if windows is None else windows
    if not isinstance(value, str) or not value or len(value) > 200 or any(c in value for c in '\r\n\x00'):
        raise ValueError('output_root must be an absolute local folder path of at most 200 characters')
    if value.startswith(('\\\\', '//')) or (windows and value.startswith(('\\', '/'))):
        raise ValueError('output_root must be a local drive path, not a UNC or device path: ' + value)
    if windows:
        pure = PureWindowsPath(value)
        if not re.fullmatch(r'[A-Za-z]:', pure.drive) or not pure.is_absolute():
            raise ValueError('output_root must be an absolute path on a local drive letter (for example G:\\GOAT-Evidence): ' + value)
        if '..' in pure.parts:
            raise ValueError('output_root must not contain ..: ' + value)
        kind = _drive_type(pure.drive + '\\')
        if kind == 4:
            raise ValueError('output_root %s is on a network drive; give a local drive' % value)
        if kind == 1:
            raise ValueError('output_root %s is on a drive that does not exist' % value)
        return Path(pure)
    pure = PurePosixPath(value)
    if not pure.is_absolute() or '..' in pure.parts:
        raise ValueError('output_root must be an absolute local folder path: ' + value)
    return Path(value)


def _drive_type(root):
    """GetDriveTypeW: 1 no root dir, 4 remote; None where it cannot be asked."""
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(root)
    except (AttributeError, OSError, ImportError):
        return None


# ---- drift -------------------------------------------------------------------------------------
def _dec(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _relative(original, retest):
    """|retest - original| / |original| as Decimal; 0 when both are 0; None when the original is 0 and the re-test is not."""
    if original == 0:
        return Decimal(0) if retest == 0 else None
    return abs(retest - original) / abs(original)


def judge_drift(original, retest, tolerances=TOLERANCES):
    """``reproduced`` / ``drifted`` from two metric dicts (trades, pf, pf_note, max_dd). Pure; boundaries inclusive."""
    checks, delta = [], {}

    def check(metric, ok, detail):
        checks.append(dict(metric=metric, ok=bool(ok), detail=detail))

    a, b = _dec(original.get('trades')), _dec(retest.get('trades'))
    if a is None or b is None:
        check('trades', False, 'unknown (%s / %s)' % (original.get('trades'), retest.get('trades')))
    else:
        rel = _relative(a, b)
        delta.update(trades=float(b - a), trades_rel=None if rel is None else float(rel))
        check('trades', rel is not None and rel <= tolerances['trades_rel'],
              '%s -> %s (%s; bar <= %s%%)' % (a, b, 'n/a' if rel is None else '%.2f%%' % (rel * 100), tolerances['trades_rel'] * 100))
    a, b = _dec(original.get('pf')), _dec(retest.get('pf'))
    if a is not None and b is not None:
        delta['pf'] = float(b - a)
        check('pf', abs(b - a) <= tolerances['pf_abs'], '%s -> %s (|delta| %s; bar <= %s)' % (a, b, abs(b - a), tolerances['pf_abs']))
    elif original.get('pf_note') == retest.get('pf_note') == 'no losing deals':
        delta['pf'] = 0.0
        check('pf', True, 'no losing deals on either run')
    else:
        check('pf', False, 'unknown (%s / %s)' % (original.get('pf', original.get('pf_note')), retest.get('pf', retest.get('pf_note'))))
    a, b = _dec(original.get('max_dd')), _dec(retest.get('max_dd'))
    if a is None or b is None:
        check('max_dd', False, 'unknown (%s / %s)' % (original.get('max_dd'), retest.get('max_dd')))
    else:
        rel = _relative(a, b)
        delta.update(max_dd=float(b - a), max_dd_rel=None if rel is None else float(rel))
        check('max_dd', rel is not None and rel <= tolerances['max_dd_rel'],
              '%s -> %s (%s; bar <= %s%%)' % (a, b, 'n/a' if rel is None else '%.2f%%' % (rel * 100), tolerances['max_dd_rel'] * 100))
    verdict = REPRODUCED if all(item['ok'] for item in checks) else DRIFTED
    return dict(verdict=verdict, checks=checks, delta=delta,
                reasons=['%s: %s' % (item['metric'], item['detail']) for item in checks if not item['ok']])


def _side(unit, first, last, *, deposit, name_fallback):
    """Trades, PF, max DD and return of one export unit over [first, last], with where each comes from."""
    from studio_window_metrics import equity_samples, window
    deals = None
    capture = unit.get('capture') or {}
    if capture.get('complete') and capture.get('path'):
        candidate = Path(capture['path']).parent / 'deals.csv'
        deals = str(candidate) if candidate.is_file() else None
    rows = equity_samples(Path(unit['csv_path']).read_bytes())
    names = [n for n in ('BOOS', 'SAMPLE', 'FWD', 'FOOS') if n in (unit.get('windows') or {})]
    measured = window(rows, first, last, deals=deals, header=unit.get('windows') or {}, header_names=names)
    out = dict(trades=measured['trades'], pf=measured['pf'], pf_note=measured['pfNote'], max_dd=measured['maxDd'],
               max_dd_pct=measured['ddPct'], net=measured['equityNet'], profit=measured['profit'],
               return_pct=None if not deposit or measured['equityNet'] is None else round(measured['equityNet'] / float(deposit) * 100, 6),
               trade_source=measured['tradeSource'] or 'unavailable', dd_source='equity_csv')
    metrics = unit.get('metrics') or {}
    if name_fallback and out['trades'] is None and metrics.get('trades') is not None:
        out.update(trades=metrics['trades'], trade_source='export_file_name')
    if name_fallback and out['pf'] is None and out['pf_note'] != 'no losing deals' and metrics.get('pf') is not None:
        out.update(pf=metrics['pf'], pf_note=None, pf_source='export_file_name')
    out.setdefault('pf_source', out['trade_source'] if out['pf'] is not None else None)
    return out


def drift(original, retest, *, deposit=None):
    """Drift of the re-test against the exact original over the original's own span (studio_evidence records)."""
    from datetime import date
    first, last = date.fromisoformat(original['evidence_start']), date.fromisoformat(original['evidence_end'])
    try:
        a = _side(original, first, last, deposit=deposit, name_fallback=True)
        b = _side(retest, first, last, deposit=deposit, name_fallback=False)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        reason = 'could not measure the drift: ' + str(exc)[:240]
        return dict(schema=DRIFT_SCHEMA, kind=KIND, verdict=DRIFTED, reasons=[reason], checks=[], delta={},
                    span=dict(first_day=first.isoformat(), last_day=last.isoformat()), original=None, retest=None,
                    tolerances=public_tolerances(), plain='Drift unknown (' + reason + '), so it counts as drifted.')
    judged = judge_drift(a, b)
    for name in ('net', 'return_pct'):
        if a.get(name) is not None and b.get(name) is not None:
            judged['delta'][name if name != 'net' else 'return'] = round(b[name] - a[name], 6)
    plain = ('Reproduced on the target build within the #2350 bar (PF, trades, max DD).' if judged['verdict'] == REPRODUCED
             else 'Drifted on the target build: ' + '; '.join(judged['reasons']) + '.')
    return dict(schema=DRIFT_SCHEMA, kind=KIND, verdict=judged['verdict'], reasons=judged['reasons'], checks=judged['checks'],
                delta=judged['delta'], span=dict(first_day=first.isoformat(), last_day=last.isoformat()), original=a, retest=b,
                tolerances=public_tolerances(), plain=plain)


def public_tolerances():
    return dict(pf_abs=float(TOLERANCES['pf_abs']), trades_rel=float(TOLERANCES['trades_rel']),
                max_dd_rel=float(TOLERANCES['max_dd_rel']), inclusive=True, source=TOLERANCES['source'])
