"""Mutation check for the gate calibration guards (controller/studio_gate_calibration.py).

Each guard is removed in a temporary copy of controller/ and the gate calibration tests
must fail. The key guards: thin evidence falls back to today's values; no predictor
reads the window it is calibrated against; selection is paid for (member counting,
simultaneous band, within-run signal, leave-one-run-out with a hard per-run gate);
only comparable v2 held_up verdicts act; a stamp only tightens.
The repository is never modified. Works with an embedded Python that ignores cwd
(sys.path is set here).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
MODULE = 'studio_gate_calibration.py'
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[3:])\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
MUTATIONS = [
    ('thin evidence does not fall back',
     "    if baseline['sets'] < min_sets or baseline['members'] < min_members or baseline['clusters'] < min_clusters:\n",
     "    if False:\n"),
    ('leaky feature read without refusal',
     "    if target not in allowed:\n        raise ValueError('Feature %s would leak",
     "    if False:\n        raise ValueError('Feature %s would leak"),
    ('calibration admits every feature for every target',
     "    return [name for name, spec in FEATURES.items() if target in spec[2]]\n",
     "    return list(FEATURES)\n"),
    ('forward window admitted to predict itself',
     "    'fwd_net': ('forward', 'net', ('post', 'held_up'), None),\n",
     "    'fwd_net': ('forward', 'net', TARGETS, None),\n"),
    ('Score admitted to predict the forward window it contains',
     "    'opt_score': ('optimizer', 'Score', ('post', 'held_up'), 'MinScore'),\n",
     "    'opt_score': ('optimizer', 'Score', TARGETS, 'MinScore'),\n"),
    ('near-copy sets counted instead of members',
     "            self.S[c, has] += (kept * hits[None, :]).sum(axis=1)[has] / k[has]\n            self.N[c, has] += 1\n",
     "            self.S[c] += (kept * hits[None, :]).sum(axis=1)\n            self.N[c] += k\n"),
    ('gate held by a few members is eligible',
     "eligible = (K >= settings['min_sets']) & (N >= settings['min_members']) & (clusters_kept >= 2)",
     "eligible = (K >= settings['min_sets']) & (clusters_kept >= 2)"),
    ('per-point interval replaces the simultaneous band',
     "        lower[t] = min(band[t], wilson(S[t], N[t])[0])\n",
     "        lower[t] = (S[t] / N[t] + wilson(S[t], N[t])[0]) / 2\n"),
    ('signal pooled across runs instead of within each run',
     "            by_cluster.setdefault(index[cluster], ([], []))[0 if hit else 1].append(value)\n",
     "            by_cluster.setdefault(0, ([], []))[0 if hit else 1].append(value)\n"),
    ('a metric with no clear signal is chosen',
     "        if result['direction'] != 'higher_is_better':\n            continue\n        floor",
     "        floor"),
    ('held-out interval drops the design-effect Wilson bound',
     "    w_low, w_high = clustered_wilson(sums, counts)\n", "    w_low, w_high = wilson(sum(sums), total)\n"),
    ('design effect ignored (members counted as independent)',
     "    deff = max(1.0, cluster_var / binomial_var) if binomial_var > 0 else 1.0\n", "    deff = 1.0\n"),
    ('held-out validation ignored',
     "        if validation['lower'] < min_survival:\n",
     "        if False:\n"),
    ('a run that clearly misses does not block',
     "        if validation['contradicted']:\n",
     "        if False:\n"),
    ('plan field qualifies below its floor',
     "            if floor is not None and data.thresholds[t] < floor:\n                continue\n",
     ""),
    ('forward/post diagnostics become actionable',
     "    actionable = status == 'validated' and target in ACTIONABLE_TARGETS\n",
     "    actionable = status == 'validated'\n"),
    ('survival judged without a trade minimum',
     "    if window.get('trades') is None or window['trades'] < min_trades:\n        return None\n",
     ""),
    ('verdicts of another schema accepted',
     "        if node.get('schema') != VERDICT_SCHEMA:\n", "        if False:\n"),
    ('non-comparable verdicts accepted',
     "        if verdict != 'not_comparable' and comparable is not True:\n", "        if False:\n"),
    ('verdicts with overridden rules accepted',
     "        if rules.get('id') != VERDICT_SCHEMA or rules.get('overridden'):\n", "        if False:\n"),
    ('the last verdict read wins instead of the newest',
     "        if prior is None or (entry['evidence_end'], entry['key']) > (prior['evidence_end'], prior['key']):\n",
     "        if True:\n"),
    ('stamp loosens a stricter plan',
     "            tightened = max(float(export[field]), float(value))\n",
     "            tightened = float(value)\n"),
    ('forward/post recommendations can be stamped',
     "    if recommendation.get('target') not in ACTIONABLE_TARGETS:\n", "    if False:\n"),
    ('different evidence collapsed as a duplicate',
     "                 hashlib.sha256(deals_raw).hexdigest(), hashlib.sha256(equity_raw).hexdigest()],\n",
     "                 ],\n"),
    ('partial capture counts trades it never saw',
     "    covered = deals_until is None or deals_until >= hi\n", "    covered = True\n"),
]

def main():
    caught = 0
    for label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / MODULE
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            try:
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log),
                                         'test_studio_gate_calibration'],
                                        timeout=300, capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report = log.read_text(encoding='utf-8') if log.exists() else ''
                # Caught means the tests ran and failed, not that the copy broke on import.
                failed = (result.returncode == 1 and 'FAILED (' in report
                          and 'ImportError' not in report and 'SyntaxError' not in report)
            except subprocess.TimeoutExpired:
                failed, label = True, label + ' (hang)'
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
