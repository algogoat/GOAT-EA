"""Mutation check for the OOS window formula (goat-oos-windows-v1) and its BOOS/FOOS rule.

Each guard (the pass bar, the 30-trade floor, the rounding, FOOS held out of the export,
re-derivation at activation, unchanged explicit plans) is weakened in a temporary copy of
controller/ and controller/test_studio_oos_windows.py or test_studio_window_metrics.py must fail. The repository is never
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_*window*.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
RULE = 'studio_oos_windows.py'
MUTATIONS = [
    # The pass bar (shared with the desktop through fixtures/oos-holdout-gate-cases.json).
    ('PF bar is strict', RULE, "return pf >= MIN_PF, '%.2f' % pf", "return pf > MIN_PF, '%.2f' % pf"),
    ('net bar is strict', RULE, "return pl >= 0, ('net %+.2f' % pl)", "return pl > 0, ('net %+.2f' % pl)"),
    ('PF bar dropped', RULE, '    if pf_ok is False:\n', '    if False:\n'),
    ('DD bar is strict', RULE, '<= Fraction(base) * MAX_DD_RATIO.numerator:', '< Fraction(base) * MAX_DD_RATIO.numerator:'),
    ('DD ratio is 2x', RULE, 'MAX_DD_RATIO = Fraction(3, 2)', 'MAX_DD_RATIO = Fraction(2, 1)'),
    ('DD bar dropped', RULE, '        if not Fraction(dd) * MAX_DD_RATIO.denominator', '        if False and Fraction(dd) * MAX_DD_RATIO.denominator'),
    ('zero in-sample DD gives a limit', RULE, "dd, base = _number(window.get('dd')), _positive(in_sample_dd)",
     "dd, base = _number(window.get('dd')), _number(in_sample_dd)"),
    # The floor and the result names.
    ('floor is 29', RULE, 'MIN_TRADES = 30 ', 'MIN_TRADES = 29 '),
    ('floor dropped', RULE, '    if trades < MIN_TRADES:\n', '    if False:\n'),
    ('fail does not outrank a thin window', RULE, "SET_ORDER = ('fail', 'not_eligible_yet', 'not_measured', 'no_data', 'pass')",
     "SET_ORDER = ('not_eligible_yet', 'fail', 'not_measured', 'no_data', 'pass')"),
    ('no_data outranks not_measured', RULE, "SET_ORDER = ('fail', 'not_eligible_yet', 'not_measured', 'no_data', 'pass')",
     "SET_ORDER = ('fail', 'not_eligible_yet', 'no_data', 'not_measured', 'pass')"),
    ('unfinished FOOS judged', RULE, "    if window.get('complete') is False:\n", '    if False:\n'),
    ('missing PF passes', RULE, "missing.append('%s profit factor not measured", "(lambda *a: None)('%s profit factor not measured"),
    ('untested window passes', RULE, "window.get('present') is False:\n        result['reasons']",
     "window.get('present') is False:\n        result['status'] = 'pass'; result['reasons']"),
    ('catch-up weeks ignored', RULE, '            last = tested_through        # catch-up weeks count toward FOOS\n', '            pass\n'),    # The date math.
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
    # Exact pre-FOOS metrics at export (studio_window_metrics).
    ('pre-FOOS window runs into FOOS', 'studio_window_metrics.py', 'return export_start, start, to_date - timedelta(days=1)',
     'return export_start, start, to_date + timedelta(days=27)'),
    ('selection window includes BOOS', 'studio_window_metrics.py', 'selectionWindow=window(rows, sample_start,', 'selectionWindow=window(rows, export_start,'),
    ('EA MeanDD weights changed', 'studio_window_metrics.py', 'return (dds[0] * 6 + dds[1] * 5) / 11', 'return (dds[0] * 6 + dds[1] * 5) / 10'),
    ('DD peak ignores the opening equity', 'studio_window_metrics.py', 'peak, dd, dd_pct, episode, episodes = opening,',
     'peak, dd, dd_pct, episode, episodes = inside[0][1],'),
    ('report scan drops the metrics', 'studio_export_scan.py', '        if windows is not None:\n', '        if False:\n'),
    ('locked metrics not redacted', 'studio_heldout_guard.py', "'oos_rule', 'window_metrics', 'preFoos', 'selectionWindow', 'fullExport'))", "'fullExport'))"),
    # Honest BOOS stamp (Claude-Mac, #1885 6007861974): the current EA's export trim partly selects on BOOS.
    ('BOOS stamp dropped from judge', RULE, 'used_for_ranking=False, boosContaminatedBy=boos_contaminated_by,', 'used_for_ranking=False,'),
    ('BOOS stamp says clean', RULE, "BOOS_CONTAMINATED_BY = 'ea_trim'", 'BOOS_CONTAMINATED_BY = None'),
    ('BOOS stamp dropped from the catch-up hook', 'studio_catchup.py',
     "status='no_data', reasons=[reason], used_for_ranking=False,\n                        boosContaminatedBy=BOOS_CONTAMINATED_BY,\n                        plain='No hold-out data under",
     "status='no_data', reasons=[reason], used_for_ranking=False,\n                        plain='No hold-out data under"),
    # Latest closed day for catch-up only (goatai#1885 6008215775): the catch-up / export split.
    ('exports accept auto_day by default', 'studio_evidence_end.py', 'not_before=(), allow_day=False):', 'not_before=(), allow_day=True):'),
    ('auto_day refusal dropped', 'studio_evidence_end.py', '    if day_value and not allow_day:\n', '    if False:\n'),
    ('catch-up refuses auto_day', 'studio_catchup.py', 'clock=broker_clock or evidence_end.DEFAULT_CLOCK, allow_day=True)',
     'clock=broker_clock or evidence_end.DEFAULT_CLOCK)'),
    ('auto_day resolves to the closed Friday', 'studio_evidence_end.py', "chosen, mode, requested, rule = parse_date(latest['date']),",
     "chosen, mode, requested, rule = parse_date(automatic['date']),"),
    ('auto_day includes the unclosed day', 'studio_evidence_end.py', '    day = today - timedelta(days=1)\n', '    day = today\n'),
    ('auto_day lands on a weekend', 'studio_evidence_end.py', '    return day.weekday() < 5 and day not in closed_days',
     '    return day not in closed_days'),
    ('catch-up end ignored when judging FOOS', RULE, '        tested_through = min(tested_through, _day(evidence_end))\n', '        pass\n'),
    ('oos_rule not stamped with the evidence end', 'studio_catchup.py', "        result.setdefault('evidenceEnd', evidence_end)\n", ''),
    ('catch-up record not stamped', 'studio_catchup.py',
     "                       oos_rule=verdict['oos_rule'], evidenceEnd=verdict['evidenceEnd'], evidenceEndMode=verdict['evidenceEndMode'])",
     "                       oos_rule=verdict['oos_rule'])"),
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
