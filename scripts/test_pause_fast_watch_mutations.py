"""Mutation check for the pause fast watch (studio_batch_driver) and the pace blocker (studio_batch_pause).

Each guard is removed in a temporary copy of controller/ and the pause tests must fail
(or hang, which the timeout bounds). The repository is never modified. Works with an
embedded Python that ignores cwd (sys.path is set here).
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
          'suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[3:])\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
WATCH = "    while _waiting_safe_point(pause) and clock.monotonic() + FAST_POLL_SECONDS <= until:"
MUTATIONS = [
    ('fast watch removed', 'studio_batch_driver.py', WATCH, "    while False:"),
    ('fast watch unbounded', 'studio_batch_driver.py', WATCH, "    while _waiting_safe_point(pause):"),
    ('fast watch steps on a rolled-back clock', 'studio_batch_driver.py',
     "        if now < record['last_wall'] or now-wall_start+.05 < mono-monotonic_start:\n            break\n", "        pass\n"),
    ('fast watch ignores low disk', 'studio_batch_driver.py',
     "        if record['disk_observation'].get('reason'):\n            break\n", "        pass\n"),
    ('pace window never named', 'studio_batch_pause.py',
     "        if member_seconds and member_seconds - MIN_REMAINING_SECONDS < MIN_SAFE_WINDOW_SECONDS:", "        if False:"),
    ('pace blocker overwrites the monitor blocker', 'studio_batch_pause.py',
     "    if point.get('reason') != 'pace_leaves_no_safe_window' or record.get('blocker') is not None:",
     "    if point.get('reason') != 'pace_leaves_no_safe_window':"),
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
            try:
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log),
                                         'test_studio_batch_driver_pause', 'test_studio_batch_pause'],
                                        timeout=240, capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report = log.read_text(encoding='utf-8') if log.exists() else ''
                # Caught means the pause tests ran and failed, not that the copy broke.
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
