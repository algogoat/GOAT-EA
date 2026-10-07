"""Mutation check: a transient Windows sharing error never fails a detached lane driver (goatai#1885).

Banker 2026-10-07: seed driver release-190check-202610071054 was recorded failed on WinError 32
from the native gate while two seed-status calls held it. Each guard below is removed in a
temporary copy of controller/ and test_lane_final_write_retry must fail (or hang, which the
timeout bounds). The repository is never modified. Works with an embedded Python that ignores
cwd (sys.path is set here).
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
          'suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[3:])\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
GATE, SEED, AGENT, MAILBOX, BRIDGE, INSTALL, RESULTS = ('studio_native_gate.py', 'studio_seed.py', 'demo_agent.py',
    'studio_agent_mailbox.py', 'studio_bridge.py', 'studio_installation.py', 'studio_seed_results.py')
MUTATIONS = [
    ('gate never waits', GATE, '            if clock()>=deadline:\n', '            if True:\n'),
    ('gate waits forever', GATE, '            if clock()>=deadline:\n', '            if False:\n'),
    ('busy gate not a GateBusy', GATE, '                if code in GATE_BUSY_WINERRORS:', '                if False:'),
    ('runner gate has no wait', SEED, 'GATE_WAIT_SECONDS=1\n', 'GATE_WAIT_SECONDS=0\n'),
    ('busy driver pass fails the driver', SEED, '            except GateBusy:\n                # Another GOAT operation',
     '            except ZeroDivisionError:\n                # Another GOAT operation'),
    ('closing status raises on a busy gate', SEED, '        except GateBusy as busy:\n            return dict(batch_id=batch_id,status=',
     '        except ZeroDivisionError as busy:\n            return dict(batch_id=batch_id,status='),
    ('record write not retried', AGENT, '        sharing_retry(lambda: os.replace(temporary, path))', '        os.replace(temporary, path)'),
    ('failed record write leaves its temporary', AGENT, '        temporary.unlink(missing_ok=True)\n', '        pass\n'),
    ('record read not retried', AGENT, "    return json.loads(sharing_retry(lambda: Path(path).read_text(encoding='utf-8-sig')))",
     "    return json.loads(Path(path).read_text(encoding='utf-8-sig'))"),
    ('open() sharing violation not transient', MAILBOX, "    return os.name == 'nt' and getattr(error, 'errno', None) == errno.EACCES",
     '    return False'),
    ('any winerror is transient', MAILBOX, '        return code in TRANSIENT_WINERRORS', '        return True'),
    ('state write not retried', BRIDGE, '                if not transient or attempt == SHARING_RETRY_ATTEMPTS-1:', '                if True:'),
    ('installation read not retried', INSTALL, '    raw = sharing_retry(Path(path).read_bytes)', '    raw = Path(path).read_bytes()'),
    ('seed state read not retried', RESULTS, '    raw=sharing_retry(bounded)', '    raw=bounded()'),
]
TESTS = ['test_lane_final_write_retry']


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
            try:
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)] + TESTS,
                                        timeout=150, capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report = log.read_text(encoding='utf-8') if log.exists() else ''
                # Caught means the tests ran and failed, not that the copy broke.
                failed = (result.returncode == 1 and 'FAILED (' in report
                          and 'ImportError' not in report and 'SyntaxError' not in report)
            except subprocess.TimeoutExpired:
                failed, label = True, label + ' (hang)'
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label, flush=True)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
