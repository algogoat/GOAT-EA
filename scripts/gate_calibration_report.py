"""Real-data gate calibration report (goat-gate-calibration-v2): recommendations plus the evidence.

Reads the export evidence once (read only), runs the calibration for several targets
and writes report.json and report.md into a NEW output folder. Never writes anywhere
else. Usage (the embedded Python ignores cwd, so the controller path is set here):

    python scripts/gate_calibration_report.py --out-dir G:/GOAT-Build-Artifacts/gate-calibration-YYYYMMDD
        [--common-root <GOAT Common Files>] [--runs R1,R2] [--verdicts <catch-up verdicts>]
        [--captured-before 2026-10-02T21:00:00Z]

Only the held_up target (comparable goat-catchup-verdict-v2 verdicts) can change a
gate. Forward and post are reported as diagnostics: what would validate, never
applied.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path[:] = [p for p in sys.path if not p.rstrip('\\/').lower().endswith('controller')]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'controller'))

import studio_gate_calibration as gates  # noqa: E402

SCENARIOS = [('forward', 0.6), ('forward', 0.8), ('forward', 0.9), ('post', 0.6), ('post', 0.75), ('post', 0.8)]


def pct(value):
    return '-' if value is None else '%.0f%%' % (100 * value)


def interval(pair):
    return '-' if not pair else '%s-%s' % (pct(pair[0]), pct(pair[1]))


def capture_mtime(common, record):
    """Modification time of the set's capture manifest (``path`` is run/area/member/<capture folder>)."""
    run, area, member, folder = record['path'].split('/', 3)
    return (Path(common) / run / area / member / record['symbol'] / folder / 'manifest.json').stat().st_mtime


def labelled_split(records, target, verdicts):
    """Passed vs filler, pooled, per target. Descriptive only: fillers come from
    members that found nothing better, so the pooled gap is confounded by construction."""
    rows = []
    for label, flag in (('passed the run\'s MinSR/MinARF', False), ('filler (below them, kept to fill SetsToExport)', True)):
        subset = [r for r in records if r['filler'] is flag]
        judged = [(r, gates.outcome(r, target, verdicts)) for r in subset]
        judged = [(r, hit) for r, hit in judged if hit is not None]
        if not judged:
            rows.append(dict(target=target, group=label, sets=0, members=0, runs=0, survival=None, interval=None))
            continue
        clusters = sorted({r['run'] for r, _ in judged})
        base = gates._baseline(judged, clusters, lambda r: r['run'])
        rows.append(dict(target=target, group=label, sets=base['sets'], members=base['members'], runs=base['clusters'],
                         survival=base['survival'], interval=base['interval']))
    return rows


def markdown(report):
    ev = report['evidence']
    lines = ['# Gate calibration report v2 (%s)' % report['generated_at'][:10], '',
             'Generated %s by `scripts/gate_calibration_report.py` (schema `%s`), read only over %s.'
             % (report['generated_at'], gates.SCHEMA, ev['common_root']), '']
    lines += ['## Bottom line', '', report['bottom_line'], '']
    meaning = report['validation_meaning']
    lines += ['## What "validated" means: per draw, not per gate', '', meaning['text'], '',
              '| Run shock sigma | Target | Draws | Validated | Validated but under target | Per draw | Per validated gate | Shortfall (points) |',
              '|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in meaning['simulation']['rows']:
        lines.append('| %s | %s | %d | %d | %d | %.1f%% | %s | %s |' % (
            row['run_shock_sigma'], pct(row['target']), row['draws'], row['validated'], row['validated_below_target'],
            100 * row['per_draw'], pct(row['per_validated_gate']),
            '-' if not row['shortfall_points'] else '%.1f-%.1f' % tuple(row['shortfall_points'])))
    lines.append('')
    lines += ['## Evidence', '',
              '%d distinct exported sets with a finished sequence capture (%d byte-identical copies removed%s). '
              'A member\'s sets are near copies, so outcomes are averaged per member first; runs are the independent '
              'unit for every interval, bootstrap and hold-out.'
              % (ev['sets'], ev['duplicates_removed'],
                 '' if not ev.get('captured_before') else '; captures written before %s only' % ev['captured_before']), '',
              '| Run | Sets | Fillers | Skipped | Export gates at the time |', '|---|---:|---:|---:|---|']
    for run in ev['runs']:
        s = run['export_settings']
        lines.append('| %s | %d | %d | %d | MinScore %s, MinSR %s, MinARF %s, SetsToExport %s, BOOS %s |'
                     % (run['run'], run['sets'], run['fillers'], run['skipped'], s.get('MinScore'), s.get('MinSR'),
                        s.get('MinARF'), s.get('SetsToExport'), s.get('BackOOSDate')))
    lines += ['', 'Verdicts: %s.' % ('none supplied (no comparable goat-catchup-verdict-v2 records exist yet), so the '
                                    'held_up target, the only one that can move a gate, could not run'
                                    if not ev['verdicts'] else '%d accepted, rejected %s' % (ev['verdicts'],
                                                                                              ev['verdicts_rejected'])), '']
    lines += ['## Scenarios', '',
              'Method: a threshold is chosen only on a metric whose survivors beat failures inside the same run '
              '(run-bootstrap AUC range above 0.5), on a simultaneous lower band over the whole threshold grid '
              '(sup-t, run bootstrap), and then leave-one-run-out: the whole selection is repeated without each run and '
              'judged on that run. It validates only when the pooled held-out lower bound clears the target with '
              '>= %d runs judged and no run clearly contradicts it.' % report['scenarios'][0]['settings']['min_clusters'], '',
              '| Target | Needed | Status | Actionable | Best full-data gate | Kept sets (members) | Held-out survival (lower) | Baseline (95% range) |',
              '|---|---:|---|---|---|---:|---|---|']
    for item in report['scenarios']:
        gate, validation = item['gate'], item['validation']
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            item['target'], pct(item['settings']['min_survival']), item['status'], 'yes' if item['actionable'] else 'no',
            '-' if not gate else '`%s >= %s`' % (gate['feature'], gate['threshold']),
            '-' if not gate else '%d (%d)' % (gate['point']['kept_sets'], gate['point']['kept_members']),
            '-' if not validation else '%s (%s), %d runs judged%s' % (
                pct(validation['survival']), pct(validation['lower']), validation['judged_clusters'],
                '' if not validation['contradicted'] else ', contradicted by ' + ', '.join(validation['contradicted'])),
            '%s (%s), %d sets / %d members / %d runs' % (pct(item['baseline']['survival']), interval(item['baseline']['interval']),
                                                         item['baseline']['sets'], item['baseline']['members'],
                                                         item['baseline']['clusters'])))
    lines.append('')
    for item in report['scenarios']:
        lines += ['**%s, %s:** %s' % (item['target'], pct(item['settings']['min_survival']), item['summary']), '']
    lines += ['## Which numbers predict survival (inside each run)', '',
              'AUC = chance a surviving set scores higher than a failing one of the same run (0.5 = no signal); the '
              'range is a run bootstrap. Only features clean for the target are listed (leakage rule).', '']
    for target in ('forward', 'post'):
        item = next(s for s in report['scenarios'] if s['target'] == target)
        lines += ['### %s window' % target, '', '| Feature | Source | Coverage | AUC | AUC range | Reading |',
                  '|---|---|---:|---:|---|---|']
        for name, info in sorted(item['features'].items(), key=lambda kv: -(kv[1]['auc'] or 0)):
            lines.append('| %s | %s %s | %d | %s | %s | %s |' % (
                name, info['source'], info['metric'], info['coverage'], '-' if info['auc'] is None else info['auc'],
                '-' if not info['auc_interval'] else '%.2f-%.2f' % tuple(info['auc_interval']), info['direction']))
        lines.append('')
    lines += ['## Splits (descriptive)', '',
              'Ranges are run-robust, so a split seen in one run only shows 0-100%: one run says nothing about the next.', '']
    for target in ('forward', 'post'):
        item = next(s for s in report['scenarios'] if s['target'] == target)
        lines += ['### %s window' % target, '', '| Split | Sets | Members | Runs | Survival | 95% range |',
                  '|---|---:|---:|---:|---:|---|']
        for key in ('symbol_class', 'design', 'timeframe', 'family', 'run', 'filler'):
            for name, info in item['splits'][key].items():
                lines.append('| %s=%s | %d | %d | %d | %s | %s |' % (key, name, info['sets'], info['members'], info['runs'],
                                                                   pct(info['survival']), interval(info['interval'])))
        lines.append('')
    lines += ['## Fillers', '',
              'Fillers are sets the EA exported below its run\'s own MinSR/MinARF to fill SetsToExport. They are labelled '
              '(`filler`), never excluded. The pooled split below is confounded by construction (fillers come from '
              'members that found nothing better), so the decision test is within run and symbol on held_up only: %s.'
              % report['fillers'].get('reading', report['fillers']['status'].replace('_', ' ')), '',
              '| Window | Group | Sets | Members | Runs | Survival | 95% range |', '|---|---|---:|---:|---:|---:|---|']
    for row in report['filler_pooled']:
        lines.append('| %s | %s | %d | %d | %d | %s | %s |' % (row['target'], row['group'], row['sets'], row['members'],
                                                             row['runs'], pct(row['survival']), interval(row['interval'])))
    lines += ['', '## Caveats', '']
    lines += ['- ' + text for text in report['caveats']]
    return '\n'.join(lines) + '\n'


def bottom_line(results, verdicts):
    actionable = [r for r in results if r['actionable']]
    if actionable:
        return 'Actionable: ' + '; '.join('%s at %s: %s >= %s' % (r['target'], pct(r['settings']['min_survival']),
                                                                   r['gate']['feature'], r['gate']['threshold'])
                                           for r in actionable) + '. Stamp with `gate-stamp` (tighten only). ' + \
            gates.validation_meaning(actionable[0]['settings']['min_survival'])['text']
    diagnostic = [r for r in results if r['status'] == 'validated']
    text = ('Keep today\'s gates (MinScore 60, MinSR 2.5, MinARF 0.2, SetsToExport 2, TargetDD 100 and the EA back-row '
            'filter). ')
    text += ('No held_up verdicts exist yet, so nothing is actionable. ' if not verdicts
             else 'No held_up gate validated. ')
    if diagnostic:
        text += 'Diagnostics that validate (not applied, the window lies inside the export run): ' + '; '.join(
            '%s at %s: %s >= %s (held-out %s, lower %s)' % (r['target'], pct(r['settings']['min_survival']),
                                                            r['gate']['feature'], r['gate']['threshold'],
                                                            pct(r['validation']['survival']), pct(r['validation']['lower']))
            for r in diagnostic) + '.'
    else:
        text += 'No diagnostic gate validated either.'
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--common-root', type=Path)
    parser.add_argument('--runs')
    parser.add_argument('--verdicts', type=Path)
    parser.add_argument('--captured-before', help='Only sets whose capture manifest was written before this UTC time')
    args = parser.parse_args(argv)
    out = args.out_dir
    if (out / 'report.json').exists() or (out / 'report.md').exists():
        raise SystemExit('Report already exists in ' + str(out) + '; choose a new folder')
    common = args.common_root or gates.default_common_root()
    runs = [r.strip() for r in args.runs.split(',')] if args.runs else None
    evidence = gates.load_evidence(common, runs)
    records = evidence['records']
    if args.captured_before:
        cutoff = datetime.strptime(args.captured_before, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
        records = [r for r in records if capture_mtime(common, r) < cutoff]
    verdicts, rejected = gates.load_verdicts(args.verdicts) if args.verdicts else (None, {})
    scenarios = list(SCENARIOS) + ([('held_up', 0.6), ('held_up', 0.75)] if verdicts else [])
    results = []
    for target, survival in scenarios:
        results.append(gates.public(gates.recommend(records, target=target, verdicts=verdicts, min_survival=survival)))
    report = dict(schema=gates.SCHEMA + '-report', generated_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  evidence=dict(common_root=str(common), runs=evidence['runs'], sets=len(records),
                                duplicates_removed=evidence['duplicates_removed'], captured_before=args.captured_before,
                                verdicts=None if verdicts is None else len(verdicts), verdicts_rejected=rejected),
                  scenarios=results, bottom_line=bottom_line(results, verdicts),
                  validation_meaning=gates.validation_meaning(),
                  fillers=gates.filler_comparison(records, verdicts),
                  filler_pooled=[row for target in ('forward', 'post') for row in labelled_split(records, target, verdicts)],
                  caveats=[
                      'Selection: every set here was chosen by the EA using its Score (in-sample AND forward) and '
                      'whole-export-run file-name metrics, so forward survival is inflated, and forward and post both lie '
                      'inside the export run the EA judged. They are diagnostics only; the catch-up held_up verdicts '
                      '(weeks after the export, comparable re-tests) are the only target that can move a gate.',
                      'Few independent runs: most sets come from three large runs; intervals and hold-outs count runs, '
                      'so they are wide on purpose. Treat the numbers as this market period\'s evidence, not a law.',
                      'Sharpe, recovery and ARF are computed per window from the exported equity curve (daily, sampled '
                      'equity); close to, not identical with, MT5\'s SR and the EA\'s ARF. opt_* are MT5\'s own '
                      'in-sample columns.',
                      'Captures that hit the 2,000,000-row limit keep their full equity curve but their trade counts and '
                      'PF after the cut are unknown, so they are not judged where a trade minimum applies.',
                  ])
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'report.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, sort_keys=True, indent=1, default=str)
        stream.write('\n')
    with (out / 'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(markdown(report))
    print(json.dumps(dict(ok=True, out_dir=str(out), sets=len(records), bottom_line=report['bottom_line'],
                          statuses=[(s['target'], s['settings']['min_survival'], s['status'],
                                     s['gate'] and (s['gate']['feature'], s['gate']['threshold']),
                                     s['validation'] and (s['validation']['survival'], s['validation']['lower']))
                                    for s in results])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
