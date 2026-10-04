"""Mutation check for the controller's no-profitable-passes classification.

Each guard is weakened in a temporary copy of controller/ and
controller/test_studio_research_outcome.py must fail. The repository is never
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_research_outcome.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
STATUS = 'studio_research_status.py'
MUTATIONS = [
    ('any item_stats status relabels', STATUS, "RESEARCH_OUTCOME_STATUSES.get(fields[3]) if",
     "RESEARCH_OUTCOME_STATUSES.get(fields[3], NO_PROFITABLE_PASSES) if"),
    ('alias alone identifies the member', STATUS, "index = {(alias, symbol): i for i, (alias, symbol) in enumerate(members)}",
     "index = {(alias, s): i for i, (alias, _) in enumerate(members) for s in ('USDCAD', 'USDCHF', 'USDJPY', 'EURUSD', 'NZDUSD')}"),
    ('older attempt relabels a later failure', STATUS, " or written < started[i] - 1:", ":"),
    ('missing timeline turns the attempt guard off', STATUS, " or i not in started or ", " or "),
    ('completed members relabelled', STATUS, "statuses[i] == 'native_error'}", "True}"),
    ('window order not checked', STATUS, "or not window['start'] < window['end'] < window['forward_end']):", "):"),
    # Review HIGH/MEDIUM: the controller mirrors the EA guard exactly.
    ('zero-trade report accepted', STATUS, "or not 1 <= outcome['traded'] <= passes ", "or False "),
    ('unparsed rows accepted', STATUS, "outcome['malformed'] != 0 or ", ""),
    ('partial report accepted', STATUS, " or outcome['complete'] != '1'", ""),
    ('forward report not required', STATUS, "            or not 1 <= outcome['forward_rows'] <= passes\n", ""),
    ('positive best profit with nothing profitable accepted', STATUS,
     "            or (outcome['profitable'] == 0 and outcome['best_profit'] >= 0.001)\n", ""),
    ('no-edge still counted as failed', STATUS, "members_failed=statuses.count('native_error') - len(no_edge),",
     "members_failed=statuses.count('native_error'),"),
    ('headline hides the window', STATUS, "(window['start'] + ' to ' + window['end'] if window else 'their test window')", "'this window'"),
    ('cancelled members not named', STATUS, "        counts += ', ' + str(cancelled) + ' cancelled'", "        pass"),
    ('early stop called finished', STATUS, "(' stopped early;' if cancelled else ' finished;')", "' finished;'"),
    ('differing windows merged', STATUS, "if len(windows) == 1 else None", "if windows else None"),
    ('summary drops the not-a-verdict line', STATUS, "'. A result for this window only, not a verdict on the strategy.'", "'.'"),
    ('no-edge members slow the ETA', STATUS, "if s == 'native_completed' or i in tested]", "if s == 'native_completed']"),
    ('pause counts no-edge as failed', 'studio_batch_pause.py', "failed = outcomes.count('native_error') - len(no_edge)",
     "failed = outcomes.count('native_error')"),
    ('retrying failures re-runs no-edge members', 'studio_batch.py',
     "if status == 'error' and index in no_edge and not include_no_edge: continue\n        if status == 'error' and index not in no_edge and not include_failed: continue",
     "if status == 'error' and not (include_failed or include_no_edge): continue"),
    ('include-no-edge override ignored', 'studio_batch.py', "if status == 'error' and index in no_edge and not include_no_edge: continue",
     "if status == 'error' and index in no_edge: continue"),
    ('finish drops the outcomes', 'studio_finish.py', "                for i in sorted(found)],None", "                for i in sorted(found) if False],None"),
    # No qualifying rows (Banker g6-r1b): the controller mirrors GoatXmlNoQualifierOutcome exactly.
    ('status and outcome need not agree', STATUS, "    if outcome['outcome'] != expected:\n        return None\n", ""),
    ('nothing qualified read as no profitable passes', STATUS, "    if expected == NO_QUALIFYING_ROWS:\n        return _no_qualifier_outcome(values, outcome)\n", ""),
    ('nothing kept accepted', STATUS, "not 1 <= kept <= o['profitable'] <= passes", "not 0 <= kept <= o['profitable'] <= passes"),
    ('kept passes need not have traded', STATUS, "or not kept <= o['traded'] <= passes ", "or False "),
    ('unparsed back rows accepted', STATUS, " or o['malformed'] != 0 or o['complete'] != '1'", " or o['complete'] != '1'"),
    ('partial back report accepted', STATUS, " or o['malformed'] != 0 or o['complete'] != '1'", " or o['malformed'] != 0"),
    ('empty forward report accepted', STATUS, "            or not 1 <= o['forward_rows'] <= passes\n", ""),
    ('kept pass missing from forward accepted', STATUS, "or x['forward_matched'] != kept ", "or False "),
    ('back/forward disagreement accepted', STATUS, " or x['forward_mismatches'] != 0", ""),
    ('unreadable forward rows accepted', STATUS, " or x['forward_malformed'] != 0", ""),
    ('discarded count unchecked', STATUS, "            or x['forward_discarded'] != o['forward_rows'] - x['forward_matched']\n", ""),
    ('qualifying score accepted', STATUS, "or not 0 <= x['best_combined_score'] < x['score_threshold']", "or False"),
    ('threshold unchecked', STATUS, "or not 0 < x['score_threshold'] < float('inf') ", "or False "),
    ('unprofitable kept passes accepted', STATUS, "            or o['best_profit'] < 0.001\n", ""),
    ('nothing-qualified window order unchecked', STATUS, "            or not span['start'] < span['end'] < span['forward_end']):", "            ):"),
    ('last member called no profitable passes', STATUS, "status=(no_edge[last]['outcome'] if", "status=(NO_PROFITABLE_PASSES if"),
    ('nothing-qualified summary reads as none profitable', STATUS, "    if outcome['outcome'] == NO_QUALIFYING_ROWS:\n        kept = outcome['back_rows']\n",
     "    if False:\n        kept = outcome['back_rows']\n"),
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
        # Caught means the outcome tests ran and failed, not that the copy broke.
        return result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report


def main():
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    # Each mutation is an isolated copy plus its own interpreter, so they run side by side;
    # results are printed in list order. GOAT_MUTATION_JOBS overrides the worker count.
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
