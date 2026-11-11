"""Mutation check for the hunt board counter: every refusal and both caps are load-bearing.

Each guard of controller/hunt_board_count.py is removed in a temporary copy (the module, its test and its fixture
only) and test_hunt_board_count must fail. The repository is never modified. Works with an embedded Python that
ignores cwd (sys.path is set here).
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
          'suite=unittest.defaultTestLoader.loadTestsFromName("test_hunt_board_count")\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
MUTATIONS = [
    ('R1 missing tag file tolerated',
     "        raise Refused('R1', disclosed_path, 'disclosed-exports file missing or unreadable (%s)' % type(exc).__name__)\n",
     "        tags = {}\n"),
    ('R2 untagged unverified export counted', "        if key not in tags:\n            raise Refused('R2'", "        if False:\n            raise Refused('R2'"),
    ('R3 tag on an export that is not unverified accepted', "        if e is None:\n            raise Refused('R3'", "        if False:\n            raise Refused('R3'"),
    ('R7 judged file without an export record accepted', "        if e is None:\n            raise Refused('R7'", "        if False:\n            raise Refused('R7'"),
    ('R7 judged status may differ from the export record', "        if x['prove_status'] != e['status']:\n", "        if False:\n"),
    ('apart file keeps the counted state', "        states[x['source'].lower()] = 'apart'\n", "        pass\n"),
    ('apart file stays in the by-machine breakdown',
     "                                    disclosed=sum(1 for x in proven if x['machine'] == m and kind(x) == 'disclosed')) for m in machines},\n",
     "                                    disclosed=sum(1 for x in counted if x['machine'] == m and kind(x) == 'disclosed')) for m in machines},\n"),
    ('R3 any tag reason or ruling accepted', "        if tag.get('reason') != reason or tag.get('ruling') != ruling:\n", "        if False:\n"),
    ('R3 a stated ledger accepted as inherited',
     "        if e['source_ledger'] is not None or e['ini_ledger'] is not None or e['export_ledger'] != '1':\n", "        if False:\n"),
    ('R4 counted without a hold-out record',
     "        if r is None:\n            raise Refused('R4'", "        if False:\n            raise Refused('R4'"),
    ('R4 same_inputs flag ignored', "        if not r.get('same_inputs'):\n", "        if False:\n"),
    ('R4 hold-out problems do not refuse', "        if problems:\n            raise Refused('R4'", "        if False:\n            raise Refused('R4'"),
    ('R5 counted without a report record',
     "        if r is None:\n            raise Refused('R5'", "        if False:\n            raise Refused('R5'"),
    ('R5 failed report accepted',
     "        if not r.get('passed') or r.get('problems') or (r.get('source') or '').lower() != source.lower():\n", "        if False:\n"),
    ('R6 round duplicate counted', "        if x.get('duplicate') or x.get('duplicate_hits'):\n", "        if False:\n"),
    ('R6 migrated duplicate counted', "        if r.get('duplicate_hits') or not r.get('condition1_no_duplicate'):\n", "        if False:\n"),
    ('R6 migrated file with other inputs counted',
     "        if not r.get('same_inputs') or not r.get('condition2_inputs') or r.get('inherited_in_retest') or r.get('appended_differ'):\n",
     "        if False:\n"),
    ('round cap not applied', "        elif used[group] < room:\n", "        elif True:\n"),
    ('migrated cap not applied', "(migrated if used[r['group']] <= rules['cap'] else migrated_reserve)", "(migrated if True else migrated_reserve)"),
    ('any report proves a file without a journal', "        elif x['report'].get('history_quality') == rules['real_ticks']:\n", "        elif True:\n"),
]


def main():
    caught = 0
    for label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            (copy / 'fixtures').mkdir(parents=True)
            for name in ('hunt_board_count.py', 'test_hunt_board_count.py'):
                shutil.copy2(CONTROLLER / name, copy / name)
            shutil.copytree(CONTROLLER / 'fixtures' / 'hunt-board', copy / 'fixtures' / 'hunt-board')
            module = copy / 'hunt_board_count.py'
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if text.count(old) != 1:
                raise SystemExit('mutation anchor missing or not unique: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=600,
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the board tests ran and failed, not that the copy broke.
            failed = (result.returncode == 1 and 'FAILED (' in report
                      and 'ImportError' not in report and 'SyntaxError' not in report)
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
