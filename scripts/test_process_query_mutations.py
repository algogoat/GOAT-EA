"""Mutation check for goatai#1885 PR D: WMI inventory retry, unconfirmed-launch resolution, seed unowned doubt.

Each guard is removed in a temporary copy of controller/, and the PR D tests must fail: the retry
itself, failing closed after the last attempt, retrying only transient errors, routing every
Win32_Process call site through the retry, resolving an unconfirmed launch only from a task that is
not running, the worker taking the lock before its reservation, clearing the seed "unowned
process" doubt only once that MT5 is closed and nothing runs a member, the jittered pauses, the
post-launch identity wait, the process-API path fill, and adopting an unconfirmed member launch
only when every proof holds (resume/reconcile under the terminal lock, journaled).
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
          'for name in ("test_studio_process_query.py","test_studio_seed.py"):\n'
          '    suite.addTests(unittest.defaultTestLoader.discover(root,pattern=name,top_level_dir=root))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
QUERY = 'studio_process_query.py'
AGENT = 'demo_agent.py'
SEED = 'studio_seed.py'
PROCESS = 'studio_seed_process.py'
MUTATIONS = [
    ('no retry: the first stall fails', QUERY, 'ATTEMPTS = 4', 'ATTEMPTS = 1'),
    ('the last failure swallowed (read as no MT5)', QUERY, '                raise\n', "                return '[]'\n"),
    ('every error retried, not only a stall', QUERY,
     'RETRIED = (subprocess.TimeoutExpired, subprocess.CalledProcessError)', 'RETRIED = (Exception,)'),
    ('a call site bypasses the retry', 'studio_seed_process.py',
     "        return json.loads(powershell_text(command,purpose='selected terminal inventory',timeout=timeout,budget=budget))",
     "        return json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True,encoding='utf-8-sig',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))"),
    ('a running task treated as never started', 'studio_durable_driver.py',
     "    if info.get('state') in ('Running', 'Queued'):\n        return False", "    if False:\n        return False"),
    ('a task that ran is treated as never started', 'studio_durable_driver.py',
     "    return info.get('last_result') == SCHED_S_TASK_HAS_NOT_RUN", "    return True"),
    ('a run since the envelope is ignored', 'studio_durable_driver.py',
     "            if datetime.fromisoformat(run.replace('Z', '+00:00')) >= envelope_created_utc:", "            if False:"),
    ('an unreadable task state treated as never started', AGENT,
     "                    raise ValueError('Persistent driver launch unresolved and its task cannot be read ('",
     "                    return False\n                    raise ValueError('Persistent driver launch unresolved and its task cannot be read ('"),
    ('the batch worker reads its reservation before the lock', AGENT,
     "            worker = read_json(worker_path)\n            if worker.get('nonce') != nonce or worker.get('batch_id') != batch_id:\n"
     "                raise ValueError('Detached worker identity changed')",
     "            worker = read_json(worker_path)\n            if False:\n                raise ValueError('Detached worker identity changed')"),
    ('a lock timeout leaves the worker record silent', AGENT,
     "                self._mark_worker_failed(worker_path, nonce, 'The terminal lock stayed busy for '", "                (worker_path, nonce, 'The terminal lock stayed busy for '"),
    ('the unowned doubt clears while that MT5 still runs', SEED,
     "state['status']=='reconcile_required' and current is None\n                and not any(m['status']=='reconcile_required'",
     "state['status']=='reconcile_required'\n                and not any(m['status']=='reconcile_required'"),
    ('the unowned doubt clears while a member config still runs', SEED,
     "                and self._idle_proof(manifest,state,current) is None):\n            self._settle_unowned(root,manifest,state)",
     "                ):\n            self._settle_unowned(root,manifest,state)"),
    ('the unowned doubt never clears', SEED,
     "            self._settle_unowned(root,manifest,state)\n            return []", "            pass"),
    ('a settled doubt skips the start-grade re-entry', SEED,
     "        if pending:\n            state['status']='stopped'", "        if pending:\n            state['status']='active'"),
    ('a status read settles the doubt', SEED,
     "    def _observe(self,root,manifest,state,*,settle_unowned=False):", "    def _observe(self,root,manifest,state,*,settle_unowned=True):"),
    ('output from the unowned MT5 is collected', SEED, "            if paths:\n", "            if False:\n"),
    ('a status read retries for the full launch budget', AGENT,
     "            alive = self._worker_alive(record, quick=True)", "            alive = self._worker_alive(record)"),
    ('a never-started task is not removed before the retry', AGENT,
     "                    if info['exists']:\n                        unregister_task(envelope['task_name'])", "                    if False:\n                        unregister_task(envelope['task_name'])"),
    # Addendum (a)-(c): the launch-moment stall (T2 13:43:53Z), Claude-Mac APPROVE with amendments.
    ('retry pauses not jittered', QUERY, ' * uniform(1 - JITTER, 1 + JITTER)', ''),
    ('a stall right after the launch refuses at once', PROCESS,
     "            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:\n                actual=None",
     "            except ZeroDivisionError as exc:\n                actual=None"),
    ('a row without a path right after the launch refuses at once', PROCESS,
     "                if str(exc)!=UNKNOWN_EXECUTABLE:raise", "                raise"),
    ('two processes right after the launch are waited out', PROCESS,
     "                if str(exc)!=UNKNOWN_EXECUTABLE:raise", "                pass"),
    ('a missing path is never read from the process', PROCESS,
     "                    filled=self.image_path(row)\n", "                    filled=None\n"),
    ('the process read is not bound to the row creation time', PROCESS,
     "        if created-created%10!=expected:return None\n", ""),
    ('a status read adopts a launch', SEED,
     "            elif settle_unowned:self._reidentify(root,manifest,state,current)", "            else:self._reidentify(root,manifest,state,current)"),
    ('adoption without the terminal lock and its journal', SEED,
     "        if self.reidentify_journal is None:\n            return", "        if False:\n            return"),
    ('adoption beside a batch-level doubt', SEED,
     "        if state.get('error') is not None:return 'A batch-level doubt", "        if False:return 'A batch-level doubt"),
    ('adoption ignores the launch window', SEED,
     "        if not item['started_unix']-REIDENTIFY_EARLY_SECONDS<=created<=item['started_unix']+REIDENTIFY_LATE_SECONDS:",
     "        if False:"),
    ('adoption without this member INI on the command line', SEED,
     "            return 'The selected MT5 command line does not name", "            pass;'The selected MT5 command line does not name"),
    ('adoption accepts a longer INI file name', SEED, "+re.escape(ini)+r'(?:$|[\\s\"])',line,re.I)", "+re.escape(ini),line,re.I)"),
    ('adoption picks one of two processes naming the INI', SEED,
     "        if len(named)!=1 or named[0].get('pid')!=current.get('pid'):", "        if not named:"),
    ('adoption of an INI edited after the launch', SEED,
     "            if digest(spec['config_path'])!=spec['config_sha256']:return", "            if False:return"),
    ('adoption after an explicit start refusal', SEED,
     " or not launch_unconfirmed(item.get('error'))):", "):"),
    ('a member stranded before PR D is never adopted', SEED,
     "            or re.fullmatch(r\"Command '.*' (timed out", "            or False and re.fullmatch(r\"Command '.*' (timed out"),
    ('adoption beside another uncertain member', SEED, "        if len(uncertain)!=1:return\n", "        if not uncertain:return\n"),
    ('an adoption is not journaled', SEED, "        self.reidentify_journal(spec['alias'],record)", "        pass"),
    ('demo seed-resume never lets the runner adopt', AGENT,
     "            runner = self._reidentifying(self._seed_runner(controller, kind), kind, 'resume', batch_id)\n            current = runner.status(batch_id)\n            if current['status'] == 'prepared':",
     "            runner = self._seed_runner(controller, kind)\n            current = runner.status(batch_id)\n            if current['status'] == 'prepared':"),
]


def main():
    caught = 0
    for label, name, old, new in MUTATIONS:
        # A test child can still hold a file for a moment on Windows: never fail the check on cleanup.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
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
            # Caught means the PR D tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
