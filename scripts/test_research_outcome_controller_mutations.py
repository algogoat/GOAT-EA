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
    ('any item_stats status relabels', STATUS, "if len(fields) != 9 or fields[3] != 'NoProfitablePasses':", "if len(fields) != 9:"),
    ('alias alone identifies the member', STATUS, "index = {(alias, symbol): i for i, (alias, symbol) in enumerate(members)}",
     "index = {(alias, s): i for i, (alias, _) in enumerate(members) for s in ('USDCAD', 'USDCHF', 'USDJPY', 'EURUSD', 'NZDUSD')}"),
    ('older attempt relabels a later failure', STATUS, "(i in started and written < started[i] - 1)", "False"),
    ('completed members relabelled', STATUS, "statuses[i] == 'native_error'}", "True}"),
    ('window order not checked', STATUS, "or not window['start'] < window['end'] < window['forward_end']):", "):"),
    ('passes not required', STATUS, "outcome['passes'] <= 0 or ", ""),
    ('no-edge still counted as failed', STATUS, "members_failed=statuses.count('native_error') - len(no_edge),",
     "members_failed=statuses.count('native_error'),"),
    ('headline hides the window', STATUS, "(window['start'] + ' to ' + window['end'] if window else 'their test window')", "'this window'"),
    ('differing windows merged', STATUS, "if len(windows) == 1 else None", "if windows else None"),
    ('summary drops the not-a-verdict line', STATUS, "'. A result for this window only, not a verdict on the strategy.'", "'.'"),
    ('no-edge members slow the ETA', STATUS, "if s == 'native_completed' or i in tested]", "if s == 'native_completed']"),
    ('pause counts no-edge as failed', 'studio_batch_pause.py', "failed = outcomes.count('native_error') - len(no_edge)",
     "failed = outcomes.count('native_error')"),
    ('retry re-runs no-edge members', 'studio_batch.py', "if status == 'error' and (not include_failed or index in no_edge): continue",
     "if status == 'error' and not include_failed: continue"),
    ('finish drops the outcomes', 'studio_finish.py', "                for i in sorted(found)],None", "                for i in sorted(found) if False],None"),
]


def main():
    caught = 0
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    for label, name, old, new in MUTATIONS:
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
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
