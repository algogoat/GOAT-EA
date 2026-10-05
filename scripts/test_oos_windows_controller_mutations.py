"""Mutation check for the OOS window formula (goat-oos-windows-v1) and its BOOS/FOOS rule.

Each guard (the pass bar, the 30-trade floor, the rounding, FOOS held out of the export,
re-derivation at activation, unchanged explicit plans) is weakened in a temporary copy of
controller/ and controller/test_studio_oos_windows.py must fail. The repository is never
modified. Works with an embedded Python that ignores cwd (sys.path is set here).
GOAT_MUTATION_TMP may name the scratch folder (default: the system temp folder).
"""
import os
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_oos_windows.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
RULE = 'studio_oos_windows.py'
MUTATIONS = [
    # The pass bar.
    ('PF bar is strict', RULE, '    if not pf >= MIN_PF:\n', '    if not pf > MIN_PF:\n'),
    ('PF bar dropped', RULE, '    if not pf >= MIN_PF:\n', '    if False:\n'),
    ('DD bar is strict', RULE, '<= Fraction(in_sample_dd) * MAX_DD_RATIO.numerator:', '< Fraction(in_sample_dd) * MAX_DD_RATIO.numerator:'),
    ('DD ratio is 2x', RULE, 'MAX_DD_RATIO = Fraction(3, 2)', 'MAX_DD_RATIO = Fraction(2, 1)'),
    ('DD bar dropped', RULE, '    if not Fraction(dd) * MAX_DD_RATIO.denominator', '    if False and Fraction(dd) * MAX_DD_RATIO.denominator'),
    # The floor.
    ('floor is 29', RULE, 'MIN_TRADES = 30 ', 'MIN_TRADES = 29 '),
    ('floor dropped', RULE, '    if trades < MIN_TRADES:\n', '    if False:\n'),
    ('fail does not outrank a thin window', RULE, "('fail', 'not_eligible_yet', 'unknown', 'pass')",
     "('not_eligible_yet', 'fail', 'unknown', 'pass')"),
    ('unfinished FOOS judged', RULE, "    if window.get('complete') is False:\n", '    if False:\n'),
    ('missing PF passes', RULE, "        missing.append('%s profit factor unknown", "        (lambda *a: None)('%s profit factor unknown"),
    ('untested FOOS passes', RULE, "        result.update(status='not_eligible_yet' if name == 'FOOS' else 'unknown',",
     "        result.update(status='pass' if name == 'FOOS' else 'unknown',"),
    # The date math.
    ('BOOS rounded down', RULE, "boos=_ceil(Fraction(o_weeks, 2))", "boos=o_weeks // 2"),
    ('FWD rounded down', RULE, "fwd = _ceil(Fraction(o_weeks, 3))", "fwd = o_weeks // 3"),
    ('FOOS rounded down', RULE, "foos=_ceil(Fraction(o_weeks, 4))", "foos=o_weeks // 4"),
    ('a month is 4 weeks', RULE, 'WEEKS_PER_MONTH = Fraction(13, 3)', 'WEEKS_PER_MONTH = Fraction(4, 1)'),
    ('non-Friday accepted', RULE, '    if friday.weekday() != FRIDAY:\n', '    if False:\n'),
    # FOOS held out of the export and of ranking.
    ('export runs to the export Friday', RULE, 'export_evidence_end=to_date.isoformat(),', 'export_evidence_end=friday.isoformat(),'),
    ('held-out check dropped', RULE, "    if not isinstance(setting, dict) or setting.get('value') != wanted", "    if False and setting.get('value') != wanted"),
    ('export that saw FOOS judged', RULE, '    if original_end >= _day(record', '    if False and original_end >= _day(record'),
    ('builds without EvidenceEnd accepted', 'studio_batch.py', "    if not isinstance(evidence, dict) or 'ea_setting' not in evidence:\n",
     '    if False:\n'),
    ('activation skips the formula check', 'activate_research_campaign.py', '    verify_native(native, plan.get(\'jobs\'))', '    pass'),
    ('recorded windows not re-derived', RULE, '        if record.get(key) != value:\n', '        if False:\n'),
    ('native BOOS date not checked', RULE, "    if native.get('back_oos_date') != record['export']['BackOOSDate']", "    if False"),
    # Plans.
    ('stated dates overwritten', RULE, '        if key in out and out[key] != value:\n', '        if False:\n'),
    ('conflicting evidence_end accepted', RULE, '        if not same_day:\n', '        if False:\n'),
    ('explicit plans rewritten', RULE, '    if SPEC_KEY not in spec:\n        return spec, None\n', ''),
    ('seed reads FWD', RULE, "seed_tester=dict(FromDate=mt5(start), ToDate=mt5(forward)", "seed_tester=dict(FromDate=mt5(start), ToDate=mt5(to_date)"),
    ('seed prepare ignores the formula', 'studio_seed.py', 'members,payloads=self._freeze(root,filled)',
     'members,payloads=self._freeze(root,{k:v for k,v in plan.items() if k!="oos_windows"})'),
    ('successor loses the windows', 'studio_batch.py',
     "        remaining['oos_windows'] = dict(optimization_weeks=oos_record['o_weeks'], export_friday=oos_record['export_friday'])\n",
     '        pass\n'),
]


def main():
    caught = 0
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    for label, name, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory(dir=scratch) as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if text.count(old) != 1:
                raise SystemExit('mutation anchor missing or repeated: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
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
