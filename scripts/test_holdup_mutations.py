"""Mutation check for the hold-up test (studio_holdup, studio_tester_report and their wiring), goatai#1885.

Each guard that keeps a hold-up result honest is removed in a temporary copy of controller/, and the
hold-up tests must fail: the hash binding, the frozen-inputs check, the report's own reconciliation,
the refusals (search axis, AI bias, held-out reveal, unfinished week, held-out lock), the history
quality floor, the trial-journal peek and the held-out redaction of hold-up replies.
The repository is never modified. Works with an embedded Python that ignores cwd.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.TestSuite()\n'
          'for name in ("test_studio_holdup.py","test_studio_tester_report.py","test_demo_holdup_agent.py"):\n'
          '    suite.addTests(unittest.defaultTestLoader.discover(root,pattern=name,top_level_dir=root))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
HOLDUP = 'studio_holdup.py'
REPORT = 'studio_tester_report.py'
MUTATIONS = [
    ('other SET bytes accepted', HOLDUP, "            if actual != test['set_sha256']:", "            if False:"),
    ('a searching SET accepted', HOLDUP, "            if valid['active_axes']:", "            if False:"),
    ('AI bias on accepted', HOLDUP, "        if current != disabled:", "        if False:"),
    ('a held-out reveal accepted in v1', HOLDUP, "        if isinstance(plan, dict) and 'heldout_reveal' in plan:", "        if False:"),
    ('a window into the unfinished week accepted', HOLDUP, "            if end > latest_end:", "            if False:"),
    ('held-out lock not enforced at prepare', HOLDUP, "        check_seed_jobs(self.c, plan, members)\n", "\n"),
    ('evidence offered below the quality floor', HOLDUP, "    if quality < QUALITY_FLOOR:", "    if False:"),
    ('MT5 inputs never compared', REPORT,
     "    differ = [name for name in values if name in reported and not _same_input(name, values[name], reported[name], definitions.get(name))]",
     "    differ = []"),
    ('extra MT5 inputs accepted', REPORT, "    if extra:\n        problems.append('MT5 ran input(s)", "    if False:\n        problems.append('MT5 ran input(s)"),
    ('report settings never compared', REPORT, "        if str(settings[key]) != str(value):", "        if False:"),
    ('deal balance chain not checked', REPORT, "    if not chain:", "    if False:"),
    ('net not reconciled with the deals', REPORT, "    net_reconciles = abs(net - results['net']) <= TOLERANCE", "    net_reconciles = True"),
    ('deal count not reconciled', REPORT, "    deals_match = len(trading) == results['deals']", "    deals_match = True"),
    ('a non-English report read anyway', REPORT, "    if missing:\n        raise ValueError(NOT_ENGLISH", "    if False:\n        raise ValueError(NOT_ENGLISH"),
    ('hold-up tests are not peeks', 'studio_trial_journal.py',
     "            windows = [w for w in (_window(role, _day(window.get('start')), _day(window.get('end')), relation=relation),) if w]",
     "            windows = []"),
    ('hold-up replies not redacted under a lock', 'studio_heldout_guard.py',
     "            for folder in ('seeds', 'catchups', 'holdups'):", "            for folder in ('seeds', 'catchups'):"),
]


def main():
    caught = 0
    for label, name, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=900,
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the hold-up tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
