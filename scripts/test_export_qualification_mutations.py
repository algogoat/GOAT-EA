"""Mutation check for goat-export-qualification-v1 (controller/studio_export_qualification.py).

Each guard is weakened in a temporary copy of controller/ and
controller/test_studio_export_qualification.py must fail. The repository is never
modified. Works with an embedded Python that ignores cwd (sys.path is set here).
GOAT_MUTATION_TMP may name the scratch folder (default: the system temp folder).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_export_qualification.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
EQ, STATUS, GUARD = 'studio_export_qualification.py', 'studio_research_status.py', 'studio_heldout_guard.py'
MUTATIONS = [
    # Cut-off fidelity (Claude-Mac amendment 1): the rounded file name never decides a near miss.
    ('a value at the cut-off decided by the rounded file name', EQ,
     "    if abs(diff) <= token.half_unit:\n        return None\n", ""),
    ('the 3-decimal header ignored at the cut-off', EQ,
     "            if precise is not None and precise.decimals > printed.decimals:", "            if False:"),
    ('a header that disagrees with the file name accepted', EQ,
     "                if abs(precise.value - printed.value) > printed.half_unit + precise.half_unit:", "                if False:"),
    ('an unresolved cut-off reported as passed', EQ, "    elif cutoff:\n", "    elif False:\n"),
    # Thresholds are the run's own, read the way the EA reads them.
    ('missing thresholds compared anyway', EQ, "    if not thresholds.get('available'):", "    if False:"),
    ('[Export] section not required', EQ, "    if '[Export]' not in text:\n        return None\n", ""),
    # The EA log cross-check.
    ('a log that disagrees keeps the passes', EQ, "    if crosscheck['status'] != 'match':", "    if False:"),
    ('a missing log confirms the stamps', EQ, "crosscheck.update(status='unavailable',", "crosscheck.update(status='match',"),
    ('AdjustLots runs read the first export pass', EQ, "    if adjust_lots:\n        if cycle['adjusted'] is None:",
     "    if False:\n        if cycle['adjusted'] is None:"),
    # Claude-Mac on #164: the passing sets the EA KEPT (SortAndTrimExports Passing=) decide, not the count before trimming.
    ('the count before trimming decides', EQ,
     "    if cycle['trims']:\n        return cycle['trims'][-1]['passing'], 'sort_and_trim'\n", ""),
    ('single-export cycles never confirm', EQ,
     "    return cycle['passed'], 'single_export_passed_thresholds'\n", "    return 0, 'single_export_passed_thresholds'\n"),
    # Held-out guard (Claude-Mac on #164): the reply is guarded, and a locked run loses its aggregates.
    ('export-qualification printed unguarded', 'demo_agent.py',
     "    return guard_scan(result, lambda value: guard_output(install, value, root=install['controller_state_root']))", "    return result"),
    ('a locked run keeps its counts', EQ, "            run['counts'] = locked[0]\n", ""),
    ('an unknown member counted as passing', EQ,
     "    member = ('passed' if counts['passed'] else", "    member = ('passed' if counts['passed'] or counts['unknown'] else"),
    # research-status: qualifying = passed, kept-below shown apart.
    ('every kept member counted as qualifying', STATUS,
     "        counted['qualifying'] += summary['member'] == 'passed'", "        counted['qualifying'] += summary['kept'] > 0"),
    ('the headline hides the thresholds', STATUS, "        ' (' + threshold_words(limits) + ')' if limits else '')", "        '')"),
    ('kept-below-threshold members not named', STATUS,
     "            qualified_words += ', ' + str(below) + ' more kept below threshold'", "            pass"),
    ('pass counts not redacted under a held-out lock', GUARD,
     "    'passing_sets', 'below_threshold_members', 'below_threshold_sets', 'unknown_members', 'unknown_sets',\n", ""),
]


def run_mutation(mutation, scratch):
    label, name, old, new = mutation
    with tempfile.TemporaryDirectory(dir=scratch) as work:
        copy = Path(work) / 'controller'
        shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
        module = copy / name
        text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
        if text.count(old) != 1:
            raise SystemExit('mutation anchor missing or repeated: ' + label)
        module.write_text(text.replace(old, new, 1), encoding='utf-8')
        log = Path(work) / 'log.txt'
        result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=900,
                                capture_output=True, text=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        report = log.read_text(encoding='utf-8') if log.exists() else ''
        # Caught means the qualification tests ran and failed, not that the copy broke.
        return result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report


def main():
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    jobs = int(os.environ.get('GOAT_MUTATION_JOBS') or min(8, os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(lambda m: run_mutation(m, scratch), MUTATIONS))
    for (label, _, _, _), failed in zip(MUTATIONS, results):
        print(('CAUGHT ' if failed else 'MISSED ') + label)
    caught = sum(results)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
