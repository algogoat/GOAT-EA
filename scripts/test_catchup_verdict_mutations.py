"""Mutation check for the OOS catch-up review fixes (verdict v2, eligibility, import stamp, re-queue).

Each guard is removed in a temporary copy of controller/ and the catch-up tests must fail.
The repository is never modified. Works with an embedded Python that ignores cwd
(sys.path is set here). Usage: python scripts/test_catchup_verdict_mutations.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
TESTS = ['test_studio_catchup_verdict', 'test_studio_catchup', 'test_studio_research_status', 'test_studio_batch',
         'test_demo_catchup_agent']  # the DemoAgent harness: prepare -> start -> report end to end
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3].split(","))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
VERDICT, CATCHUP, STATUS, BATCH = 'studio_catchup_verdict.py', 'studio_catchup.py', 'studio_research_status.py', 'studio_batch.py'
MUTATIONS = [
    # Comparability: every pinned condition must be compared, and a mismatch is never judged.
    (VERDICT, 'EA build not compared', "        pair('ea_build', oc.get('build_id'), rc.get('build_id'))\n",
     "        check('ea_build', True, 'skipped')\n"),
    (VERDICT, 'unknown EA build accepted', "check('ea_build', False, 'the EA build of the original or the re-test is unknown')",
     "check('ea_build', True, 'unknown')"),
    (VERDICT, 'deposit not compared', "    pair('deposit',", "    (lambda *a: None)('deposit',"),
    (VERDICT, 'server not compared', "    pair('server',", "    (lambda *a: None)('server',"),
    (VERDICT, 'reproduction not required', "check('reproduced', repro.get('reproduced'),", "check('reproduced', True,"),
    (VERDICT, 'not_comparable judged anyway', "    if not comparable['comparable']:\n        verdict = 'not_comparable'",
     "    if False:\n        verdict = 'not_comparable'"),
    # Drawdown from the running peak, including pre-window equity.
    (VERDICT, 'pre-window peak ignored', "if carry_peak else []", "if False else []"),
    (VERDICT, 'evaluate measures DD from the window open', "opening=opening, carry_peak=True)", "opening=opening, carry_peak=False)"),
    # held_up needs a known PF, PF over new positions only, and a trade-pace floor.
    (VERDICT, 'unknown PF can hold up', "    if not _pf_known(new):\n", "    if False:\n"),
    (VERDICT, 'PF counts earlier positions', "        if row['position_id'] not in opened:\n            continue\n",
     "        if False:\n            continue\n"),
    (VERDICT, 'trade-pace floor dropped', "    if expected and trades < min_pace_trades * expected:", "    if False:"),
    (VERDICT, 'losing forward window can hold up', "    if forward_per_day is not None and forward_per_day <= 0:\n", "    if False:\n"),
    # Low confidence in the text.
    (VERDICT, 'confidence missing from the sentence', "'. %s confidence: %s trades over %d trading days.'", "'.%.0s%.0s%.0s'"),
    # Prepare-time eligibility and the shared tester validator.
    (CATCHUP, 'another EA binary eligible', "        if run_ea and run_ea != self.c.install['ea_sha256']:", "        if False:"),
    (CATCHUP, 'unknown EA build eligible', "        elif not run_ea and not capture.get('build_id'):", "        elif False:"),
    (CATCHUP, 'capture-only build not compared with the installed EA', "            elif installed != capture['build_id']:", "            elif False:"),
    (CATCHUP, 'unreadable installed build accepted', "            if installed is None:", "            if False:"),
    (CATCHUP, 'single pass not validated', "    validate_tester(view | dict(Optimization=2, OptimizationCriterion=6, ForwardDate=''))",
     "    pass"),
    # catchUp import stamp and re-queue.
    (CATCHUP, 'catch_up stamp loses added_at', "added_at=created_utc,", "added_at=None,"),
    (CATCHUP, 'unjudged re-test counts as caught up', "not in UNJUDGED]", "not in ()]"),
    # Catch-up results never count as qualifying.
    (STATUS, 'held_up reported as qualifying', "        candidates = qualifying_members = None\n", "        pass\n"),
    # A resumed batch keeps its resolved evidence end.
    (BATCH, 'resume re-resolves auto', "        remaining['evidence_end'] = recorded['target']\n", "        pass\n"),
]


def main():
    caught = 0
    for name, label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log), ','.join(TESTS)], timeout=900,
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the tests ran and failed, not that the copy broke.
            failed = (result.returncode == 1 and 'FAILED (' in report
                      and 'ImportError' not in report and 'SyntaxError' not in report)
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label, flush=True)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
