"""Mutation check for the research-launch policy (studio_research_launch, goatai#1885 PR E).

Claude-Mac's must-haves are load-bearing: no JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, refuse (and
terminate the suspended MT5) on any assignment failure with no fallback launch, research launches
only for seed members and the native first start (never trading or monitor MT5), the Idle lock,
the per-terminal Local\\ job name, and the owner CPU-cap staging (one breach steps down, two pause).
Each rule is removed in a temporary copy of controller/, and test_studio_research_launch must fail.
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_research_launch.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
LAUNCH = 'studio_research_launch.py'
PROCESS = 'studio_seed_process.py'
SEED = 'studio_seed.py'
CONFIG = 'studio_config_start.py'
MUTATIONS = [
    ('KILL_ON_JOB_CLOSE is set on the research job', LAUNCH,
     "    return JOB_OBJECT_LIMIT_PRIORITY_CLASS if plan['priority_lock'] is not None else 0",
     "    return (JOB_OBJECT_LIMIT_PRIORITY_CLASS if plan['priority_lock'] is not None else 0) | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE"),
    ('an assignment failure lets MT5 run anyway (fallback launch)', LAUNCH,
     "            api.terminate(process)\n            _history(root, 'refused'",
     "            api.resume(thread)\n            _history(root, 'refused'"),
    ('a refused MT5 is left suspended instead of terminated', LAUNCH,
     "            api.terminate(process)\n            _history(root, 'refused'",
     "            pass\n            _history(root, 'refused'"),
    ('MT5 is resumed before it is in the job', LAUNCH,
     "                api.assign(job, process)\n", "                api.resume(thread);api.assign(job, process)\n"),
    ('a global job name', LAUNCH, "JOB_PREFIX = 'Local\\\\GOAT-Research-'", "JOB_PREFIX = 'Global\\\\GOAT-Research-'"),
    ('owner research MT5 is not created Idle', LAUNCH,
     "creation_priority=BELOW_NORMAL_PRIORITY_CLASS if split else IDLE_PRIORITY_CLASS",
     "creation_priority=BELOW_NORMAL_PRIORITY_CLASS"),
    ('the job does not lock the Idle priority class', LAUNCH,
     "job=True, priority_lock=None if split else IDLE_PRIORITY_CLASS", "job=True, priority_lock=None"),
    ('the customer default gets a CPU cap', LAUNCH,
     "cpu_rate_percent=CUSTOMER_RESPONSIVE_PERCENT if responsive else None", "cpu_rate_percent=CUSTOMER_RESPONSIVE_PERCENT"),
    ('a busy existing job is reused', LAUNCH, "        if existed and api.active_processes(job) > 0:", "        if False:"),
    ('job limits are not read back', LAUNCH,
     "        if observed & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE or observed != flags or (", "        if False and ("),
    ('a NULL job handle reaches Windows (the caller\'s own job)', LAUNCH,
     "    if not handle:raise ValueError(what+' needs an open handle", "    if False:raise ValueError(what+' needs an open handle"),
    ('monitor and recovery launches get the research job', PROCESS, "        if research is True:", "        if True:"),
    ('seed / catch-up / hold-up members are not research launches', SEED,
     "        self.process=research_view(process)", "        self.process=process"),
    ('the native batch first start is not a research launch', CONFIG,
     "    launched=research_view(process).start(startup)", "    launched=process.start(startup)"),
    ('one breach does not step the cap back down', LAUNCH, "        g['stage'] = max(0, g['stage'] - 1)\n", "        pass\n"),
    ('the second breach does not pause the lane', LAUNCH,
     "        if len(g['breaches']) >= PAUSE_AFTER_BREACHES:", "        if False:"),
    ('the cap widens when only one publisher kept its budget', LAUNCH,
     "and all(g['ok_since_stage'].get(p['label']) for p in publishers)",
     "and any(g['ok_since_stage'].get(p['label']) for p in publishers)"),
    ('a starved cycle that is still running is not a breach', LAUNCH,
     "elapsed = (cycle['ended_ms'] if cycle['ended_ms'] is not None else now_ms) - cycle['started_ms']",
     "elapsed = (cycle['ended_ms'] if cycle['ended_ms'] is not None else cycle['started_ms']) - cycle['started_ms']"),
    ('idle_split lowers MT5 itself, not only the tester agents', LAUNCH,
     "PureWindowsPath(info[0]).name.lower() != 'metatester64.exe':continue", "False:continue"),
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
                                    capture_output=True, text=True, cwd=tempfile.gettempdir(),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
