"""Real-data gate calibration report: recommended gates plus the evidence table.

Reads the export evidence once (read only), runs the calibration for several targets
and writes report.json and report.md into a NEW output folder. Never writes anywhere
else. Usage (the embedded Python ignores cwd, so the controller path is set here):

    python scripts/gate_calibration_report.py --out-dir G:/GOAT-Build-Artifacts/gate-calibration-YYYYMMDD
        [--common-root <GOAT Common Files>] [--runs R1,R2] [--verdicts <catch-up verdicts>]
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
DETAIL = ('is_sr', 'is_pf', 'is_recovery', 'is_net', 'boos_net', 'opt_is_pf', 'opt_is_rf', 'opt_score', 'fwd_recovery')


def pct(value):
    return '-' if value is None else '%.0f%%' % (100 * value)


def interval(pair):
    return '%s-%s' % (pct(pair[0]), pct(pair[1]))


def descriptive_file_gates(records):
    """Today's EA gate (file-name SR/ARF over the whole export window) against each window.

    Descriptive only: the export window contains forward and most of post, so this is
    never calibration input."""
    rows = []
    for target in ('forward', 'post'):
        for label, test in (('file-name SR >= 2.5 and ARF >= 0.2 (EA "passed thresholds")',
                             lambda r: r['file_name'] and r['file_name']['sr'] >= 2.5 and r['file_name']['arf'] >= 0.2),
                            ('below the EA thresholds (kept to fill SetsToExport)',
                             lambda r: r['file_name'] and not (r['file_name']['sr'] >= 2.5 and r['file_name']['arf'] >= 0.2))):
            judged = [(r, gates.outcome(r, target)) for r in records if test(r)]
            judged = [(r, hit) for r, hit in judged if hit is not None]
            members = len({r['member'] for r, _ in judged})
            hits = sum(1 for _, hit in judged if hit)
            share = hits / len(judged) if judged else None
            low, high = gates.wilson(share * members, members) if judged else (0.0, 1.0)
            rows.append(dict(target=target, group=label, sets=len(judged), members=members, survival=share,
                             interval=[round(low, 4), round(high, 4)]))
    return rows


def markdown(report):
    lines = ['# Gate calibration report (%s)' % report['generated_at'][:10], '',
             'Generated %s by `scripts/gate_calibration_report.py` (schema `%s`), read only over %s.'
             % (report['generated_at'], gates.SCHEMA, report['evidence']['common_root']), '']
    ev = report['evidence']
    lines += ['## Evidence', '',
              '%d distinct exported sets with a finished sequence capture (%d identical copies removed). '
              'Survival = the set made money (equity net > 0) in the target window. Intervals are 95%% Wilson '
              'intervals whose sample size is the number of distinct optimization members, not sets.'
              % (ev['sets'], ev['duplicates_removed']), '',
              '| Run | Sets | Skipped | Export gates at the time |', '|---|---:|---:|---|']
    for run in ev['runs']:
        s = run['export_settings']
        lines.append('| %s | %d | %d | MinScore %s, MinSR %s, MinARF %s, SetsToExport %s, BOOS %s |'
                     % (run['run'], run['sets'], run['skipped'], s.get('MinScore'), s.get('MinSR'), s.get('MinARF'),
                        s.get('SetsToExport'), s.get('BackOOSDate')))
    lines += ['', 'Windows (server time, half-open): back OOS [BackOOSDate, FromDate), in-sample [FromDate, ForwardDate), '
              'forward [ForwardDate, ToDate), post [ToDate, end of the export run]. Two run designs are present: '
              + ', '.join('`%s` (%d sets)' % (name, info['sets'])
                          for name, info in report['scenarios'][0]['splits']['design'].items()) + '.', '']
    lines += ['## Recommended gates', '',
              '| Target | Needed (lower bound) | Status | Gate | Kept sets (members) | Survival (95% range) | Plan fields |',
              '|---|---:|---|---|---:|---|---|']
    for item in report['scenarios']:
        gate = item['gate']
        lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
            item['target'], pct(item['settings']['min_survival']), item['status'],
            '-' if not gate else '`%s >= %s`' % (gate['feature'], gate['threshold']),
            '-' if not gate else '%d (%d)' % (gate['point']['kept_sets'], gate['point']['kept_members']),
            ('baseline %s (%s)' % (pct(item['baseline']['survival']), interval(item['baseline']['interval']))) if not gate
            else '%s (%s)' % (pct(gate['point']['survival']), interval(gate['point']['interval'])),
            ', '.join('%s %s' % (k, v) for k, v in sorted(item['values']['export'].items()))))
    lines += ['', 'Today\'s fixed gates: MinScore 60, MinSR 2.5, MinARF 0.2, SetsToExport 2, TargetDD 100 (export plan) '
              'plus the EA back-row filter (in-sample profit > 0.001 and >= 50 trades).', '']
    for item in report['scenarios']:
        lines += ['**%s, %s:** %s' % (item['target'], pct(item['settings']['min_survival']), item['summary']), '']
    watched = [(item['target'], item['settings']['min_survival'], w) for item in report['scenarios']
               if item['status'] != 'calibrated' for w in item['watchlist']]
    if watched:
        lines += ['### Watchlist (not recommended)', '',
                  'Tails that would meet the target but belong to a feature with no clear overall signal. With this many '
                  'features and thresholds scanned they can be chance; recheck them on the next run before using them.', '',
                  '| Target | Needed | Gate | Kept sets (members) | Survival (95% range) | Feature AUC |',
                  '|---|---:|---|---:|---|---|']
        for target, needed, w in watched:
            lines.append('| %s | %s | `%s >= %s` | %d (%d) | %s (%s) | %s (%s) |' % (
                target, pct(needed), w['feature'], w['threshold'], w['kept_sets'], w['kept_members'], pct(w['survival']),
                interval(w['interval']), w['auc'], '-' if not w['auc_interval'] else '%.2f-%.2f' % tuple(w['auc_interval'])))
        lines.append('')
    lines += ['## Which numbers predict survival', '',
              'AUC = chance a surviving set scores higher than a failing one (0.5 = no signal); the range is a member-level '
              'bootstrap. Only features clean for the target are listed (leakage rule).', '']
    for target in ('forward', 'post'):
        item = next(s for s in report['scenarios'] if s['target'] == target)
        lines += ['### Target: %s window (baseline %s, %s; %d sets, %d members)'
                  % (target, pct(item['baseline']['survival']), interval(item['baseline']['interval']),
                     item['baseline']['sets'], item['baseline']['members']), '',
                  '| Feature | Source | Coverage | AUC | AUC range | Reading |', '|---|---|---:|---:|---|---|']
        for name, info in sorted(item['features'].items(), key=lambda kv: -(kv[1]['auc'] or 0)):
            lines.append('| %s | %s %s | %d | %s | %s | %s |' % (
                name, info['source'], info['metric'], info['coverage'], info['auc'],
                '-' if not info['auc_interval'] else '%.2f-%.2f' % tuple(info['auc_interval']), info['direction']))
        lines.append('')
    lines += ['## Threshold curves (selected features)', '',
              'Each row: keep sets with feature >= threshold. Yield = share of judged sets kept. Monotone = the isotonic '
              '(never-decreasing) estimate.', '']
    for target in ('forward', 'post'):
        item = next(s for s in report['curves'] if s['target'] == target)
        for name in DETAIL:
            if name not in item['features']:
                continue
            curve = item['features'][name]['curve']
            picks = curve[::max(1, len(curve) // 6)] + ([curve[-1]] if curve and curve[-1] not in curve[::max(1, len(curve) // 6)] else [])
            lines += ['**%s / %s** (AUC %s)' % (target, name, item['features'][name]['auc']), '',
                      '| Threshold | Kept sets | Members | Yield | Survival | Monotone | 95% range |',
                      '|---:|---:|---:|---:|---:|---:|---|']
            for p in picks:
                lines.append('| %s | %d | %d | %s | %s | %s | %s |' % (
                    p['threshold'], p['kept_sets'], p['kept_members'], pct(p['yield_']), pct(p['survival']),
                    pct(p['survival_monotone']), interval(p['interval'])))
            lines.append('')
    lines += ['## Splits', '']
    for target in ('forward', 'post'):
        item = next(s for s in report['scenarios'] if s['target'] == target)
        lines += ['### %s window' % target, '', '| Split | Sets | Members | Survival | 95% range |', '|---|---:|---:|---:|---|']
        for key in ('symbol_class', 'design', 'timeframe', 'family', 'run'):
            for name, info in item['splits'][key].items():
                lines.append('| %s=%s | %d | %d | %s | %s |' % (key, name, info['sets'], info['members'],
                                                             pct(info['survival']), interval(info['interval'])))
        lines.append('')
        calibrated = {k: v for k, v in item['by_split'].items() if v['status'] == 'calibrated'}
        if calibrated:
            lines += ['Split gates that clear the bar on their own at %s:' % pct(item['settings']['min_survival']), '']
            for name, info in calibrated.items():
                g = info['gate']
                lines.append('- %s: `%s >= %s`, %d sets (%d members), %s (%s)' % (
                    name, g['feature'], g['threshold'], g['kept_sets'], g['kept_members'], pct(g['survival']),
                    interval(g['interval'])))
            lines.append('')
    lines += ['## Today\'s EA export gate, descriptively', '',
              'The EA judges MinSR/MinARF on the whole export run (back OOS through the export date), which contains the '
              'forward window and most of the post window, so these rows are NOT calibration evidence. They show what '
              'the current gate let through.', '',
              '| Window | Group | Sets | Members | Survival | 95% range |', '|---|---|---:|---:|---:|---|']
    for row in report['descriptive_ea_gate']:
        lines.append('| %s | %s | %d | %d | %s | %s |' % (row['target'], row['group'], row['sets'], row['members'],
                                                       pct(row['survival']), interval(row['interval'])))
    lines += ['', '## Caveats', '']
    lines += ['- ' + text for text in report['caveats']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--common-root', type=Path)
    parser.add_argument('--runs')
    parser.add_argument('--verdicts', type=Path)
    args = parser.parse_args(argv)
    out = args.out_dir
    if (out / 'report.json').exists() or (out / 'report.md').exists():
        raise SystemExit('Report already exists in ' + str(out) + '; choose a new folder')
    common = args.common_root or gates.default_common_root()
    runs = [r.strip() for r in args.runs.split(',')] if args.runs else None
    evidence = gates.load_evidence(common, runs)
    verdicts = gates.load_verdicts(args.verdicts) if args.verdicts else None
    scenarios = list(SCENARIOS) + ([('held_up', 0.6)] if verdicts else [])
    results, curves = [], []
    for target, survival in scenarios:
        result = gates.recommend(evidence['records'], target=target, verdicts=verdicts, min_survival=survival)
        if not any(c['target'] == target for c in curves):
            curves.append(dict(target=target, features={k: dict(auc=v['auc'], curve=v['curve'])
                                                         for k, v in result['features'].items()}))
        results.append(gates.public(result))
    report = dict(schema=gates.SCHEMA + '-report', generated_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  evidence=dict(common_root=str(common), runs=evidence['runs'], sets=len(evidence['records']),
                                duplicates_removed=evidence['duplicates_removed'],
                                verdicts=None if verdicts is None else len(verdicts)),
                  scenarios=results, curves=curves, descriptive_ea_gate=descriptive_file_gates(evidence['records']),
                  caveats=[
                      'Selection bias: every set here was chosen by the EA using its Score (built from in-sample AND forward '
                      'results) and full-window file-name metrics, so forward survival is inflated and the forward window '
                      'cannot validate the plan fields. The post window (after ToDate) is cleaner but was still inside the '
                      'export run that the EA judged; the catch-up held_up verdicts (weeks after the export) are the clean '
                      'target, and this tool takes them through --verdicts once they exist.',
                      'Two run designs only (IS 9 months with a 6-week or 3-month forward window); the post windows are about '
                      '1 and 3 months of one market period. Treat the numbers as this period\'s evidence, not a law.',
                      'Near-copy sets: the sets of one member share most inputs, so intervals count members, not sets.',
                      'Sharpe, recovery and ARF here are computed per window from the exported equity curve (daily, sampled '
                      'equity); they are close to, not identical with, MT5\'s own SR and the EA\'s mean-DD ARF. The optimizer '
                      'columns (opt_*) are MT5\'s own in-sample numbers.',
                      'Captures that hit the 2,000,000-row limit keep their full equity curve, so net, drawdown and Sharpe '
                      'stay exact, but their trade counts and PF are unknown after the cut and count as missing (a gate on '
                      'a missing number fails).',
                      'The g6 run (Re7e282f93d41) was still exporting when this was read; only finished captures count.',
                  ])
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'report.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, sort_keys=True, indent=1, default=str)
        stream.write('\n')
    with (out / 'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(markdown(report))
    print(json.dumps(dict(ok=True, out_dir=str(out), sets=len(evidence['records']),
                          statuses=[(s['target'], s['settings']['min_survival'], s['status'],
                                     s['gate'] and (s['gate']['feature'], s['gate']['threshold'])) for s in results])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
