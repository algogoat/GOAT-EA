"""Mutation check for GOAT peers (studio_peer_roster, studio_process_check), goatai#1885.

Each guard that keeps an unknown, foreign, moved, unsigned or namespace-sharing
MT5 refused is removed in a temporary copy of controller/, and
controller/test_studio_peer_roster.py must fail. The repository is never
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_peer_roster.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
ROSTER = 'studio_peer_roster.py'
CHECK = 'studio_process_check.py'
MUTATIONS = [
    ('GOAT peers on a lane without batch isolation', ROSTER,
     "    if not isolated(binding.get('ea_version')):\n        return None",
     "    if False:\n        return None"),
    ('origin.txt naming another folder accepted', ROSTER,
     "    if not named or PureWindowsPath(named) != exe.parent:", "    if False:"),
    ('missing data folder MQL5 accepted', ROSTER,
     "    if not (Path(data) / 'MQL5').is_dir():\n        raise Unbound", "    if False:\n        raise Unbound"),
    ('peer overlapping this terminal accepted', ROSTER,
     "    if any(_overlap(path, root) for path in (exe.parent, data) for root in own):", "    if False:"),
    ('shared batch namespace accepted', ROSTER,
     "    if data == PureWindowsPath(lane['data_root']) or terminal_hash(str(data)) == terminal_hash(lane['data_root']):",
     "    if False:"),
    ('unsigned or invalid signature accepted', ROSTER,
     "    if not signer_ok(signer):\n        return None, ('cannot be a GOAT peer: '",
     "    if False:\n        return None, ('cannot be a GOAT peer: '"),
    ('any signer accepted', ROSTER,
     "            and organisation(signer.get('subject')) in SIGNER_ORGANISATIONS)", "            )"),
    ('records disagreeing on the data folder accepted', ROSTER,
     "    if len(roots) > 1:\n        # (f) strict", "    if False:\n        # (f) strict"),
    ('removed peer still exempt', ROSTER,
     "        if _same(item['executable'], image):\n            return None, ('was removed",
     "        if False:\n            return None, ('was removed"),
    ('copied receipt trusted', ROSTER,
     "            if not _same(value['controller_state_root'], folder):", "            if False:"),
    ('owner STOP ignored by peer-add and peer-remove', ROSTER,
     "    if (Path(c.root) / 'demo-agent' / 'STOP').exists():", "    if False:"),
    ('peer-add writes without confirmation', ROSTER,
     "    if not confirmed:\n        return dict(status='preview', peer=record",
     "    if False:\n        return dict(status='preview', peer=record"),
    ('reviewed policy.json peer removable', ROSTER,
     "    if reviewed is not None and _same(reviewed['peer']['executable'], exe):\n        raise ValueError('This MT5 is the reviewed peer",
     "    if False:\n        raise ValueError('This MT5 is the reviewed peer"),
    ('MT5 update not journaled', ROSTER,
     "            changed = bool(prior) and prior.get('executable_sha256') != digest", "            changed = False"),
    ('two processes of one GOAT peer accepted', CHECK,
     "    if len(set(ids))!=len(ids):", "    if False:"),
    ('lookup refusal ignored', CHECK,
     "            if peer is None:raise ValueError(_unmapped(actual,pid,reason))", "            if peer is None:continue"),
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
            # Caught means the roster tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
