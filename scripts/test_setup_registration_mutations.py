"""Mutation check for replacing an expired setup registration from another build (goatai#1885).

Each guard is broken in a temporary copy of controller/ and
controller/test_studio_setup_registration.py must fail. The repository is never
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_setup_registration.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
MAILBOX = 'studio_agent_mailbox.py'
SETUP = 'studio_agent_setup.py'
MUTATIONS = [
    ('an expired registration from another build still refuses (the B39 -> B41 bug)', MAILBOX,
     "            if not _expired(old, now):\n                raise", "            if True:\n                raise"),
    ('a live registration from another build is replaced', MAILBOX,
     "            if not _expired(old, now):\n                raise", "            if False:\n                raise"),
    ('the expiry grace is dropped', MAILBOX,
     "value['expiresAtUtc'] + EXPIRY_GRACE_SECONDS < now", "value['expiresAtUtc'] < now"),
    ('a non-integer expiry counts as expired', MAILBOX,
     "    return type(value.get('expiresAtUtc')) is int and value['expiresAtUtc'] + EXPIRY_GRACE_SECONDS < now",
     "    return int(value.get('expiresAtUtc') or 0) + EXPIRY_GRACE_SECONDS < now"),
    ('the expired registration is deleted instead of archived', MAILBOX,
     "    sharing_retry(lambda: path.rename(archived))", "    sharing_retry(path.unlink)"),
    ('an existing registration archive is overwritten', MAILBOX,
     "    if archived.exists():\n        raise ValueError('Setup registration archive", "    if False:\n        raise ValueError('Setup registration archive"),
    ('a registration changed since inspection is archived blind', MAILBOX,
     "    if current != digest or not _expired(old, now):", "    if not _expired(old, now):"),
    ('a malformed registration is superseded', MAILBOX,
     "    if any(key not in old for key in REGISTRATION_IDENTITY):", "    if False:"),
    ('the old build request is not retired under its own identity', MAILBOX,
     "    _retire_retained(root, {key: old[key] for key in REGISTRATION_IDENTITY}, now=now)\n", ""),
    ('the superseded sha is not recorded in the close journal', SETUP,
     "                record['superseded_registration'] = superseded", "                pass"),
    ('pairing-code drops the supersession from its answer', SETUP,
     "            value['supersededRegistration'] = superseded", "            pass"),
    ('pairing-code reports a supersession that did not happen', SETUP,
     "        if superseded is not None:\n            value['supersededRegistration']",
     "        if True:\n            value['supersededRegistration']"),
    ('the close is journaled before the registration check (phantom close_intent)', SETUP,
     "            ident = superseded = None\n",
     "            write_json(path, dict(schema_version=1, attempt_id=attempt_id, phase='close_intent', process=running))\n"
     "            ident = superseded = None\n"),
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
            # Caught means the registration tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
