"""Mutation check for restore-lane's never-started allowance and demo settle-refused-start (goatai#1885, a649295d).

restore-lane accepts logged owner demo-lane work only when every batch it touched is proven never
started for its exact attempt: retire-unactivated's retired-starts/ record or settle-refused-start's
refused-starts/ record (with its completed self-repair journal). settle-refused-start reuses the
self-repair proof and settlement, relaxed only to let earlier settled rows stay in the queue.
Each guard is removed in a temporary copy of controller/, and the tests must fail.
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
          'for name in ("test_demo_settle_refused_start.py",):\n'
          '    suite.addTests(unittest.defaultTestLoader.discover(root,pattern=name,top_level_dir=root))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
AGENT = 'demo_agent.py'
REPAIR = 'studio_self_repair.py'
MUTATIONS = [
    ('batch steps accepted without a settlement proof', AGENT,
     "        settled = {batch: self._never_started_settlement(batch, jobs) for batch in sorted(batches)}",
     "        settled = {}"),
    ('any other demo operation accepted', AGENT,
     "                    if (operation not in NEVER_STARTED_BATCH_OPERATIONS or not isinstance(batch, str)",
     "                    if (not isinstance(batch, str)"),
    ('a logged retirement needs no record', AGENT,
     "                        if entry.get('phase') != 'intent':\n                            batches.add(batch)",
     "                        if False:\n                            batches.add(batch)"),
    ('a settle that may have closed MT5 treated as refused', AGENT,
     "                        if phase == 'refused' and entry.get('native_action') is False:",
     "                        if phase in ('refused', 'failed'):"),
    ('an unresolved settle intent ignored', AGENT,
     "        batches.update(batch for batch, open_ in settling.items() if open_)",
     "        pass"),
    ('retired-starts attempt not compared', AGENT,
     "                and retired.get('job_id') == batch_id and retired.get('attempt_id') == attempt",
     "                and retired.get('job_id') == batch_id"),
    ('a retired record accepted for an activated job', AGENT,
     "        if (job.get('status') == 'cancelled' and completion.get('kind') == 'retired_never_activated'",
     "        if (completion.get('kind') == 'retired_never_activated'"),
    ('refused-starts attempt not compared', AGENT,
     "                and refused.get('job_id') == batch_id and refused.get('attempt_id') == attempt",
     "                and refused.get('job_id') == batch_id"),
    ('refused-starts kind not compared', AGENT,
     "                and isinstance(refused, dict) and refused.get('kind') == REFUSED_START_KIND",
     "                and isinstance(refused, dict)"),
    ('an unfinished self-repair journal accepted', AGENT,
     "            if (isinstance(journal, dict) and journal.get('phase') == 'complete'",
     "            if (isinstance(journal, dict)"),
    ('a second unsettled batch allowed', REPAIR, [
     ("                if others:\n                    raise ValueError('Another batch may hold native work (",
      "                if False:\n                    raise ValueError('Another batch may hold native work ("),
     ("                if refused_start_only and _other_unsettled(state, job_id):",
      "                if False:")]),
    ('settlement rewrites the queue to one row', REPAIR,
     "                    jobs = [current_job if row['job_id'] == job_id else row for row in state['queue']]",
     "                    jobs = [current_job]"),
    ('a start without a restart arm accepted', REPAIR,
     "    if not isinstance(attempt, str) or not re.fullmatch(r'[a-f0-9]{64}', attempt) or 'restart_intent' not in job:",
     "    if not isinstance(attempt, str) or not re.fullmatch(r'[a-f0-9]{64}', attempt):"),
    ('a non pre-consumption receipt accepted', REPAIR,
     "            or arm['receipt']['status'] not in PRE_CONSUMPTION_REFUSALS):",
     "            ):"),
]


def main():
    caught = 0
    for label, name, *change in MUTATIONS:
        pairs = change[0] if len(change) == 1 else [tuple(change)]
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            for old, new in pairs:
                if old not in text:
                    raise SystemExit('mutation anchor missing: ' + label)
                text = text.replace(old, new, 1)
            module.write_text(text, encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=900,
                                    capture_output=True, text=True,
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
