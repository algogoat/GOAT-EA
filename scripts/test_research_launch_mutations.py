"""Mutation check for the research-launch policy (studio_research_launch, goatai#1885 PR E).

Claude-Mac's must-haves are load-bearing: no JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, refuse (and
terminate the suspended MT5) on any assignment failure with no fallback launch, research launches
only for seed members and the native first start (never trading or monitor MT5), the Idle lock,
the per-terminal Local\\ job name, and the owner CPU-cap staging (one breach steps down, two pause).
The PR E follow-up adds: an unconfirmed stop is uncertain (never "nothing ran", never re-identified), a
refused native first start is retried only by run-batch --resume, research MT5 breaks away from the
caller's job when allowed (note 5) with the same suspended launch nested otherwise, and breakaway and
staging are reported as they are.
Each rule is removed in a temporary copy of controller/, and the research-launch, config-start or seed tests must fail.
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
          'for name in ("test_studio_research_launch.py","test_studio_config_start.py","test_studio_seed.py"):\n'
          '    suite.addTests(unittest.defaultTestLoader.discover(root,pattern=name,top_level_dir=root))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
LAUNCH = 'studio_research_launch.py'
PROCESS = 'studio_seed_process.py'
SEED = 'studio_seed.py'
CONFIG = 'studio_config_start.py'
DRIVER = 'studio_batch_driver.py'
MUTATIONS = [
    ('KILL_ON_JOB_CLOSE is set on the research job', LAUNCH,
     "    return JOB_OBJECT_LIMIT_PRIORITY_CLASS if plan['priority_lock'] is not None else 0",
     "    return (JOB_OBJECT_LIMIT_PRIORITY_CLASS if plan['priority_lock'] is not None else 0) | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE"),
    ('an assignment failure lets MT5 run anyway (fallback launch)', LAUNCH,
     "            stopped = _stop_suspended(api, process, job)\n", "            api.resume(thread);stopped = True\n"),
    ('a refused MT5 is left suspended instead of terminated', LAUNCH,
     "            stopped = _stop_suspended(api, process, job)\n", "            stopped = True\n"),
    ('an unconfirmed stop is reported as nothing ran', LAUNCH,
     "    try:\n        return api.exit_code(process) is not None", "    try:\n        return True"),
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
     "        return research_view(process).start(startup)", "        return process.start(startup)"),
    ('a refused native first start is stranded at launch_issued', CONFIG,
     "        phase(c,job_id,generation,'launch_issued','launch_refused',refusal=str(error)[:500])\n", "        pass\n"),
    ('a refused seed member becomes an uncertain start', SEED,
     "item.update(status='pending',attempts=0,launch_refused=str(exc)[:500])",
     "item.update(status='reconcile_required',error=str(exc));state['status']='reconcile_required'"),
    ('an uncertain native first start is left at launch_issued', CONFIG,
     "        phase(c,job_id,generation,'launch_issued','launch_uncertain',refusal=str(error)[:500])\n", "        pass\n"),
    ('run-batch --resume never retries a refused launch', DRIVER,
     "            if _launch_refused(controller, job_id, record):", "            if False:"),
    ('run-batch --resume retries a launch that was not refused', DRIVER,
     ".get('phase') == 'launch_refused'", ".get('phase') in ('launch_refused', 'launch_issued', 'launch_uncertain')"),
    ('an uncertain seed launch is treated as nothing ran', SEED,
     "item.update(status='reconcile_required',error=str(exc),launch_uncertain=True)\n"
     "                            state['status']='reconcile_required';self._save(root,state);raise",
     "item.update(status='pending',attempts=0);self._save(root,state);raise"),
    ('an uncertain seed launch can be re-identified as the member\'s run', SEED,
     "item.get('result') or item.get('launch_uncertain')", "item.get('result')"),
    ('research MT5 never tries to break away from the caller\'s job (note 5)', LAUNCH,
     "flags | CREATE_BREAKAWAY_FROM_JOB)) + (True,)", "flags)) + (True,)"),
    ('a caller job that refuses breakaway refuses the launch', LAUNCH,
     "        if (getattr(error, 'winerror', None) or error.errno) != 5:raise\n", "        raise\n"),
    ('the nested retry is not the same suspended launch', LAUNCH,
     "    return tuple(api.create_suspended(command_line, cwd, flags)) + (False,)",
     "    return tuple(api.create_suspended(command_line, cwd, flags & ~CREATE_SUSPENDED)) + (False,)"),
    ('MT5\'s breakaway is not recorded', LAUNCH,
     "config=str(config) if config is not None else None, broke_away=broke_away,", "config=str(config) if config is not None else None,"),
    ('the keeper\'s breakaway is not recorded', LAUNCH, "            broke_away = extra != 0\n", "            broke_away = None\n"),
    ('staging reports active without a holding keeper', LAUNCH, "    if not fresh:\n", "    if False:\n"),
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
