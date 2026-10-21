"""Mutation check for studio_finish's successor-stop rule (signal-only receipts need native proof).

Each guard is removed in a temporary copy of controller/ and test_studio_cancel_successor
must fail. The repository is never modified. Works with an embedded Python that ignores
cwd (sys.path is set here).
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
          'suite=unittest.defaultTestLoader.loadTestsFromName("test_studio_cancel_successor")\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
MUTATIONS = [
    ('any successor receipt accepted', "or receipt.get('status') not in ('CANCELLED_RECONCILE','CANCEL_SIGNAL_SENT_RECONCILE')):",
     "or False):"),
    ('unconsumed successor accepted', "if (successor_stop.get('consumed') is not True or successor_stop.get('status')!='receipt_observed'",
     "if (successor_stop.get('status')!='receipt_observed'"),
    ('tester idleness not required', "        controller.runtime(require_idle=True,expected_batch_ongoing=False)\n",
     "        pass\n"),
    ('settled queue not required', "    if native['status'] not in outcomes: raise ValueError('Native queue is not finished; reconcile, do not reset')",
     "    if native['status'] not in outcomes: native=dict(native,status='native_cancelled')"),
    ('signal-only stop not recorded', "    if signal_only:\n", "    if False:\n"),
]


def main():
    caught = 0
    for label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / 'studio_finish.py'
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=600,
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the successor tests ran and failed, not that the copy broke.
            failed = (result.returncode == 1 and 'FAILED (' in report
                      and 'ImportError' not in report and 'SyntaxError' not in report)
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
