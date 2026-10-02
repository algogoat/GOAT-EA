"""Mutation check for the gate calibration guards (controller/studio_gate_calibration.py).

Each guard is removed in a temporary copy of controller/ and the gate calibration tests
must fail. The key guards: thin evidence falls back to today's defaults, and no
predictor may read the window it is calibrated against (the forward window never
predicts itself; Score and file-name metrics never predict a window they contain).
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
     "    if baseline['sets'] < min_sets or baseline['members'] < min_members:\n", "    if False:\n"),
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
    ('interval counts near-copy sets instead of members',
     "        low, high = wilson(raw * members, members) if kept else (0.0, 1.0)\n",
     "        low, high = wilson(hits, len(kept)) if kept else (0.0, 1.0)\n"),
    ('gate held by a few members qualifies',
     "point['kept_sets'] >= min_sets and point['kept_members'] >= min_members\n",
     "point['kept_sets'] >= min_sets\n"),
    ('point estimate replaces the lower bound',
     "(point['interval'][0] if confidence == 'lower' else point['survival_monotone'])",
     "point['survival_monotone']"),
    ('plan field qualifies below its floor',
     "                and (plan_field is None or point['threshold'] >= EXPORT_FLOORS[plan_field]))",
     "                and True)"),
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
