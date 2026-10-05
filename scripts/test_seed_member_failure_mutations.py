"""Mutation check for seed/catch-up member failures (studio_seed, demo_agent), goatai#1885.

A member that ends failed, timed out or without output fails only itself; the breaker
(3 in a row, or half of 4+ attempted) stops the batch with every reason; cancelled still
stops; seed-resume re-activates a batch stopped by failures only under first-start checks.
Each rule is removed in a temporary copy of controller/, and the seed tests must fail.
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
          'for name in ("test_studio_seed.py","test_demo_seed_agent.py"):\n'
          '    suite.addTests(unittest.defaultTestLoader.discover(root,pattern=name,top_level_dir=root))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
SEED = 'studio_seed.py'
AGENT = 'demo_agent.py'
MUTATIONS = [
    ('a failed member stops the batch again (the old rule)', SEED,
     "        reason=self._breaker(state)\n        if reason:state['status']='stopped';state['stopped_reason']=reason",
     "        state['status']='stopped'"),
    ('no breaker for failures in a row', SEED,
     "        if in_a_row>=BREAKER_IN_A_ROW:rules.append('in_a_row')", "        pass"),
    ('no breaker for half of 4+ attempted failing', SEED,
     "        if len(ended)>=BREAKER_SHARE_MIN and 2*len(failed)>=len(ended):rules.append('half_failed')", "        pass"),
    ('breaker counts members from before the re-activation', SEED,
     "\n                      and (since is None or (m.get('started_unix') or 0)>=since)),", "),"),
    ('cancelled no longer stops the batch', SEED,
     "        if 'cancelled' in statuses:state['status']='stopped';return\n", ""),
    ('a cancelled or uncertain batch is resumable', SEED,
     "not statuses&({'cancelled','reconcile_required'}|SeedRunner.LIVE_MEMBER)", "not statuses&(SeedRunner.LIVE_MEMBER)"),
    ('re-activation without the running terminal', SEED,
     "        if current is None:\n            raise ValueError(('Resuming a stopped %s batch'",
     "        if False:\n            raise ValueError(('Resuming a stopped %s batch'"),
    ('re-activation ignores another holder of the terminal slot', SEED,
     "            guard_active_seed(self.c.root)      # a stopped batch", "            pass      # a stopped batch"),
    ('a member failure carries no plain reason', SEED,
     "                    item['error']=self._failure_reason(manifest,item)", "                    pass"),
    ('demo lane resumes a stopped batch without the start-grade broker check', AGENT,
     "        if self._seed_resumable_stopped(batch_id, kind):\n            return self._lane_reactivate(kind, batch_id, max_seconds)\n", ""),
    ('a resume without start-grade checks re-activates anyway', SEED,
     "                if not initial and reactivate and self.resumable(state):", "                if not initial and self.resumable(state):"),
    ('the ordinary demo resume ignores a batch that stopped after routing', AGENT,
     "            if SeedRunner.resumable(current):\n", "            if False:\n"),
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
            # Caught means the seed tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
