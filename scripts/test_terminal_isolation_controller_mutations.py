"""Mutation check for controller/studio_terminal_isolation.py (INV-BATCH-01).

Each guard is removed in a temporary copy of controller/ and
controller/test_studio_terminal_isolation.py must fail. The repository is never
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_terminal_isolation.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
MUTATIONS = [
    ('claim ignored on a fresh move', "        ours, holder = _claim(legacy, base_rel, login, data_root)\n        if not ours:\n            _write_receipt",
     "        ours, holder = True, ''\n        if not ours:\n            _write_receipt"),
    ('claim ignored on resume', "        ours, holder = _claim(legacy, base_rel, login, data_root)\n        if not ours:\n            raise",
     "        ours, holder = True, ''\n        if not ours:\n            raise"),
    ('claim not create-only', "            os.link(temporary, path)  # Create-only", "            os.replace(temporary, path)  # Create-only"),
    ('guard resume not completed', "                if _read_text(target)[0] != body:", "                if True:"),
    ('unreadable program path skipped',
     "            conflicts.append(dict(pid=row.get('ProcessId'), executable='program path unreadable', data_root=None))\n            continue",
     "            continue"),
    ('unmatched terminal skipped', "        if not roots:\n            conflicts.append", "        if False:\n            conflicts.append"),
    ('foreign check compares names', "            and match[1].lower() != str(own_hash).lower())", "            and folder_name != str(own_hash))"),
    ('both-exist ignored', "        if existing:\n            raise", "        if False:\n            raise"),
    ('fixed temporary name', "    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.controller-tmp')",
     "    temporary = path.with_name(path.name + '.controller-tmp')"),
    ('stale EA build accepted', "        if not isinstance(reported, str) or not reported:", "        if False:"),
]


def main():
    caught = 0
    for label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / 'studio_terminal_isolation.py'
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=900,
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the isolation tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
