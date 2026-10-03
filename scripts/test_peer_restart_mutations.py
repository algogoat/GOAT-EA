"""Mutation check for the protected-peer restart rule (studio_protected_peer, studio_process_check).

Each refusal or isolation guard is removed in a temporary copy of controller/ and
controller/test_studio_peer_restart.py must fail. The repository is never
modified. Works with an embedded Python that ignores cwd (sys.path is set here).
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_peer_restart.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
CHECK = 'studio_process_check.py'
PEER = 'studio_protected_peer.py'
MUTATIONS = [
    ('restart tolerated without an isolated EA', CHECK,
     "            or not isinstance(own,str) or not own or not isolated(binding.get('ea_version'))):",
     "            or not isinstance(own,str) or not own):"),
    ('restart tolerated when the namespaces could be shared', CHECK,
     "    return terminal_hash(roots[0])!=terminal_hash(own)", "    return True"),
    ('restart tolerated for a peer that must stay running', CHECK,
     "    if (not binding.get('protected_terminal') or binding.get('protected_may_be_stopped') is not True",
     "    if (not binding.get('protected_terminal')"),
    ('exact-instance rule dropped on a strict lane', CHECK,
     "    if (binding.get('protected_process') is not None and result['protected']",
     "    if (False and result['protected']"),
    ('second peer process accepted', CHECK,
     "    if len(result['research'])!=int(research_running) or len(result['protected']) not in allowed_protected:",
     "    if len(result['research'])!=int(research_running):"),
    ('unknown MT5 accepted', CHECK,
     "        else:raise ValueError('Unmapped terminal process requires ownership inspection')",
     "        else:continue"),
    ('research terminal continuity relaxed with the peer', CHECK,
     "    if role=='protected' and restart_tolerant(binding):", "    if restart_tolerant(binding):"),
    ('changed peer executable accepted', PEER,
     "    if material(c,value['peer']['executable'],value['peer']['data_root'])!=value['peer']:",
     "    if False:"),
    ('closed peer refused again', PEER,
     "                                        protected_may_be_stopped=True),\n                             observed_unix",
     "                                        ),\n                             observed_unix"),
    ('closed peer reviewed', PEER, "            if process is None:\n                raise", "            if False:\n                raise"),
    ('restart not journaled', PEER, "            stream.write(json.dumps(line,sort_keys=True)+'\\n')", "            pass"),
    ('package of another peer accepted', PEER, "    if mine is None or mine!=theirs:", "    if False:"),
    ('unproven legacy policy hash accepted', PEER,
     "        if (sha(candidate)==recorded and candidate['process']", "        if (candidate['process']"),
    ('non-peer binding fields relaxed', PEER,
     "        return {key:value for key,value in binding.items() if key not in PEER_BINDING_KEYS}",
     "        return {}"),
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
            # Caught means the restart tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
