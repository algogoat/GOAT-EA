"""Mutation check for the detached seed, catch-up and hold-up drivers (demo_agent, studio_durable_driver), goatai#1885.

Each guard that keeps a detached lane drive safe is removed in a temporary copy of controller/, and
controller/test_demo_lane_driver.py must fail: the caller's own checks and start record before the
detach, one live driver per terminal, the worker's reservation identity, the durable host's exact
lane validation, the recorded worker refusal and the foreground budget cap.
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_demo_lane_driver.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
AGENT = 'demo_agent.py'
HOST = 'studio_durable_driver.py'
MUTATIONS = [
    ('detached start skips the caller\'s checks and start record', AGENT,
     "                with self._studio(kind + '-start', idle=True, job_id=batch_id) as (controller, broker):\n"
     "                    self._seed_unoccupied(kind)\n                    self._lane_start_record(kind, batch_id, controller, broker)",
     "                pass"),
    ('a second detached driver allowed', AGENT,
     "            live = self._live_lane_worker()\n            if live is not None:\n                if Path(live[0]) == worker_path:",
     "            live = None\n            if live is not None:\n                if Path(live[0]) == worker_path:"),
    ('reservation and launch outside the terminal lock', AGENT,
     "        with self._exclusive():\n            live = self._live_lane_worker()", "        with nullcontext():\n            live = self._live_lane_worker()"),
    ('an unconfirmed launch envelope overwritten', AGENT,
     "            current = read_json(worker_path) if worker_path.is_file() else dict(worker)", "            current = dict(worker)"),
    ('the caller regresses a newer worker state', AGENT,
     "        if worker.get('status') == 'reserved' and worker.get('nonce') == nonce:", "        if True:"),
    ('other lane work ignores a live detached driver', AGENT,
     "        live = self._live_lane_worker(exclude=exclude)", "        live = None"),
    ('worker drives with a changed reservation', AGENT,
     "        if (worker.get('nonce') != nonce or worker.get('kind') != kind",
     "        if False and (worker.get('nonce') != nonce or worker.get('kind') != kind"),
    ('worker refusal not recorded', AGENT,
     "            worker.update(status='failed', error=str(exc)[:2000])", "            pass"),
    ('foreground budget uncapped', AGENT,
     "    if args.max_seconds > DemoAgent.LANE_FOREGROUND_MAX_SECONDS:", "    if False:"),
    ('durable host accepts a changed lane budget', HOST,
     "    if type(remaining) is not int or not 1 <= remaining <= 3600 or str(remaining) != budget:",
     "    if type(remaining) is not int or not 1 <= remaining <= 3600:"),
    ('durable host accepts another script', HOST,
     "        raise ValueError('Only the installed controller driver is accepted')\n    kind, batch_id, nonce, budget, mode",
     "        pass\n    kind, batch_id, nonce, budget, mode"),
    ('durable host accepts a non-canonical lane worker path', HOST,
     "        raise ValueError('Lane driver log/worker path is not canonical')", "        pass"),
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
            # Caught means the lane driver tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
