"""Mutation check for the function-level certificate and the build externals manifest.

Each fail-closed guard is removed in a temporary copy of controller/ and the tests must fail.
The repository is never modified. Works with an embedded Python that ignores cwd
(sys.path is set here). Usage: python scripts/test_function_units_mutations.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
TESTS = ['test_studio_function_units', 'test_studio_equivalence']
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3].split(","))\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
UNITS, EQ = 'studio_function_units.py', 'studio_equivalence.py'
MUTATIONS = [
    # Parse uncertainty fails closed.
    (UNITS, 'conditional brace depth unchecked', "            if stack[-1] != depth:", "            if False:"),
    (UNITS, 'function-defining macro accepted', "if self.strict and re.search(r'[{};]'", "if False and re.search(r'[{};]'"),
    (UNITS, '#include inside a body accepted', "        elif word in ('include', 'import', 'resource', 'property'):\n            self.fail(tok, '#%s inside a function or class body' % word)",
     "        elif word in ('include', 'import', 'resource', 'property'):\n            pass"),
    (UNITS, 'duplicate units accepted', "        if unit['key'] in seen:", "        if False:"),
    (UNITS, 'ambiguous signatures accepted', "            if sig in signatures:", "            if False:"),
    (UNITS, 'tiling unchecked', "            if unit['start'] != cursor:", "            if False:"),
    (UNITS, 'macro call without a type accepted', " or open_at < 2:", ":"),
    # Blocking rules.
    (UNITS, 'inputs and directives allowlistable', "        elif unit['kind'] in NEVER_ALLOWLISTED:", "        elif False:"),
    (UNITS, 'changed globals allowlistable', "elif unit['kind'] in ('global', 'declaration') and change == 'changed':", "elif False:"),
    (UNITS, 'unreviewed unit version accepted', "        elif unreviewed:\n            item['blocking'] = 'allowlisted unit", "        elif False:\n            item['blocking'] = 'allowlisted unit"),
    (UNITS, 'guard ignored for units', "        elif hits:\n", "        elif False:\n"),
    (UNITS, 'trading path acknowledgement dropped', "elif on_path and entry.get('trading_path_reviewed') is not True:", "elif False:"),
    (UNITS, 'unconfirmed receipt accepted', "        elif not confirmed:", "        elif False:"),
    (UNITS, 'layout ignored', "equivalent=not blocking and not layout)", "equivalent=not blocking)"),
    (UNITS, 'code between units accepted', "            if not item['comment_or_whitespace_only']:", "            if False:"),
    (UNITS, 'macro call edges dropped', "            stack.extend(macros.get(name, ()))", "            pass"),
    (UNITS, 'unparsed file treated as certain', "not (graph or {}).get('opaque'))", "True)"),
    # Certificate integration and externals.
    (EQ, 'function-level parse doubt ignored', "                        problems.append('function-level comparison of %s is uncertain: %s' % (a, exc))",
     "                        pass"),
    (EQ, 'function-level blocking dropped', "                if not fl['equivalent']:", "                if False:"),
    (EQ, 'consumed externals not compared', "and not externals_differ and not consumed_differ", "and not externals_differ"),
    (EQ, 'manifest with problems accepted', "    if record.get('problems'):\n        raise", "    if False:\n        raise"),
    (EQ, 'not-consumed accepted without a manifest', "if sentinels and not build.get('externals_manifest'):", "if False:"),
    (EQ, 'external modified after the compile accepted', "        if later:\n            problems.append", "        if False:\n            problems.append"),
    (EQ, 'standard include resources not hashed', "        _include_closure(root, child, seen)\n", "        pass\n"),
    (EQ, 'uncovered consumed file accepted', "    if uncovered:\n", "    if False:\n"),
]


def main():
    caught = 0
    for name, label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if text.count(old) != 1:
                raise SystemExit('mutation anchor missing or not unique: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log), ','.join(TESTS)], timeout=900,
                                    capture_output=True, text=True, cwd=work,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the tests ran and failed, not that the copy broke.
            failed = (result.returncode == 1 and 'FAILED (' in report
                      and 'ImportError' not in report and 'SyntaxError' not in report)
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label, flush=True)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
