"""Mutation check for the observing driver's backoff, stall report and priority (goatai#1885).

Banker 2026-10-05: the driver repeated a ~70 s CPU pass every 30 s for 4.5 h while a
stalled batch changed nothing, and research-status read ``running``. Each guard is
removed in a temporary copy of controller/ and the backoff tests must fail (or hang,
which the timeout bounds). The repository is never modified. Works with an embedded
Python that ignores cwd (sys.path is set here).
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
DRIVER, STALL, STATUS, HOST = 'studio_batch_driver.py', 'studio_batch_stall.py', 'studio_research_status.py', 'studio_durable_driver.py'
MUTATIONS = [
    ('quiet wait never grows (the Banker spin)', DRIVER,
     "        quiet.update(wait=_quiet_wait(quiet['wait'], poll_seconds, pass_seconds), passes=quiet['passes'] + 1)",
     "        quiet.update(wait=poll_seconds, passes=quiet['passes'] + 1)"),
    ('backoff computed but the loop still waits poll_seconds', DRIVER,
     "            _wait(controller, record, clock, min(wait, max(.01, remaining)))",
     "            _wait(controller, record, clock, min(poll_seconds, max(.01, remaining)))"),
    ('slow pass cost ignored', DRIVER,
     "    return min(max(backoff, QUIET_PASS_COST_FACTOR * pass_seconds), max(poll_seconds, QUIET_WAIT_MAX_SECONDS))",
     "    return min(backoff, max(poll_seconds, QUIET_WAIT_MAX_SECONDS))"),
    ('backoff unbounded', DRIVER,
     "    backoff = min(max(previous * 2, poll_seconds), max(poll_seconds, QUIET_BACKOFF_CAP_SECONDS))",
     "    backoff = max(previous * 2, poll_seconds)"),
    ('slow-pass wait unbounded', DRIVER,
     "    return min(max(backoff, QUIET_PASS_COST_FACTOR * pass_seconds), max(poll_seconds, QUIET_WAIT_MAX_SECONDS))",
     "    return max(backoff, QUIET_PASS_COST_FACTOR * pass_seconds)"),
    ('progress never resets the wait', DRIVER,
     "    if changed or quiet.get('since_wall') is None or key != quiet.get('key'):",
     "    if quiet.get('since_wall') is None:"),
    ('a changed observation is not progress', DRIVER,
     "    if changed or quiet.get('since_wall') is None or key != quiet.get('key'):",
     "    if quiet.get('since_wall') is None or key != quiet.get('key'):"),
    ('pause request does not wake a backed-off driver', DRIVER,
     "        if _pause_mark(controller, record) != pause_before:", "        if False:"),
    ('stall never recorded by the driver', DRIVER, "    if stall is not None:\n        record.update(status='stalled', stall=stall)",
     "    if False:\n        record.update(status='stalled', stall=stall)"),
    ('stall never cleared on progress', DRIVER,
     "        record.pop('stall', None)\n        if record.get('status') == 'stalled':\n            record['status'] = 'observing'\n",
     "        pass\n"),
    ('stall declared while a member runs', STALL,
     "    if not statuses or 'native_ongoing' in statuses or not any(status in WAITING for status in statuses):",
     "    if not statuses:"),
    ('stall declared with the tester running', STALL,
     "    if not isinstance(monitor, dict) or monitor.get('ticking') is not True or monitor.get('tester_state') != 'idle':\n"
     "        return None\n    minutes = (now - quiet_since) / 60",
     "    minutes = (now - quiet_since) / 60"),
    ('stall declared before the window', STALL,
     "    if quiet_since is None or now - quiet_since < STALL_SECONDS:", "    if quiet_since is None:"),
    ('research-status hides the stall', STATUS,
     "        if stall is not None:\n            activity.update(status='stalled', stall=stall)", "        pass"),
    ('research-status stalls a fresh member boundary', STALL,
     "    if since is None or now - since < STALL_SECONDS:", "    if since is None:"),
    ('driver changes its process class instead of its thread', HOST,
     "        if kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL):",
     "        if kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x40):"),
    ('driver never lowers its priority', HOST,
     "                print('driver CPU priority: ' + str(lower_driver_priority() or 'unchanged'), flush=True)",
     "                print('driver CPU priority: unchanged', flush=True)"),
]
TESTS = ['test_studio_batch_driver_backoff']


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
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)] + TESTS,
                                        timeout=240, capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report = log.read_text(encoding='utf-8') if log.exists() else ''
                # Caught means the backoff tests ran and failed, not that the copy broke.
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
