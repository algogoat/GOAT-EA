"""Mutation check for the catch-up tick-history drift rule (goat-catchup-rebase-v1, goatai#1885 6008946539).

Each threshold, its direction, every verdict branch and every stamp (comparable_rebased, requalify,
not_comparable, historyBasis, tickHistoryDrift, the re-based windows with no splice) is weakened in a
temporary copy of controller/, and controller/test_studio_catchup_rebase.py or
test_studio_catchup_verdict.py must fail. The repository is never modified. Works with an embedded Python
that ignores cwd (sys.path is set here). GOAT_MUTATION_TMP may name the scratch folder.
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_catchup_*.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
RULE = 'studio_catchup_rebase.py'
VERDICT = 'studio_catchup_verdict.py'
CATCHUP = 'studio_catchup.py'
MUTATIONS = [
    # Thresholds: each bar loosened, made strict, or made one-sided.
    ('deal count bar is 6%', RULE, "DEAL_COUNT_REL = Decimal('0.05')", "DEAL_COUNT_REL = Decimal('0.06')"),
    ('deal count bar is strict', RULE, "_row('deal_count', abs(r - o) <= limit", "_row('deal_count', abs(r - o) < limit"),
    ('deal count bar is one-sided', RULE, "_row('deal_count', abs(r - o) <= limit", "_row('deal_count', (r - o) <= limit"),
    ('PF bar is 0.06', RULE, "PF_ABS = Decimal('0.05')", "PF_ABS = Decimal('0.06')"),
    ('PF bar is strict', RULE, "_row('pf', abs(r - o) <= PF_ABS", "_row('pf', abs(r - o) < PF_ABS"),
    ('PF bar is one-sided', RULE, "_row('pf', abs(r - o) <= PF_ABS", "_row('pf', (r - o) <= PF_ABS"),
    ('unmeasured PF passes', RULE, "        rows.append(_row('pf', False,", "        rows.append(_row('pf', True,"),
    ('no losing deals in both is drift', RULE, "    elif o is None and r is None and original.get('pf_note') == NO_LOSS",
     '    elif False'),
    ('balance bar is 0.2% of deposit', RULE, "BALANCE_OF_DEPOSIT = Decimal('0.001')", "BALANCE_OF_DEPOSIT = Decimal('0.002')"),
    ('balance bar is 3% of net', RULE, "BALANCE_OF_NET = Decimal('0.02')", "BALANCE_OF_NET = Decimal('0.03')"),
    ('balance bar takes the smaller', RULE, 'limit = max(BALANCE_OF_DEPOSIT * base,', 'limit = min(BALANCE_OF_DEPOSIT * base,'),
    ('balance bar ignores a losing net', RULE, 'BALANCE_OF_NET * abs(o - base)', 'BALANCE_OF_NET * (o - base)'),
    ('balance bar is strict', RULE, "_row('final_balance', abs(r - o) <= limit", "_row('final_balance', abs(r - o) < limit"),
    ('balance bar is one-sided', RULE, "_row('final_balance', abs(r - o) <= limit", "_row('final_balance', (r - o) <= limit"),
    ('unknown deposit passes', RULE, "        rows.append(_row('final_balance', False,", "        rows.append(_row('final_balance', True,"),
    ('SAMPLE PF 1.0 is below the line', RULE, '        return pf >= PF_SIDE', '        return pf > PF_SIDE'),
    ('SAMPLE net 0 is below the line', RULE, 'return None if pl is None else pl >= 0', 'return None if pl is None else pl > 0'),
    ('SAMPLE side ignored', RULE, "_row('sample_pf_side', o == r,", "_row('sample_pf_side', True,"),
    ('unmeasured SAMPLE passes', RULE, "        rows.append(_row('sample_pf_side', False,", "        rows.append(_row('sample_pf_side', True,"),
    ('DD bar is 11%', RULE, "DD_REL = Decimal('0.10')", "DD_REL = Decimal('0.11')"),
    ('DD bar is strict', RULE, "_row('max_dd', abs(r - o) <= limit", "_row('max_dd', abs(r - o) < limit"),
    ('DD bar is one-sided', RULE, "_row('max_dd', abs(r - o) <= limit", "_row('max_dd', (r - o) <= limit"),
    # Branches and their order.
    ('exact reproduction is not the fast path', RULE, '    if reproduced:\n        return dict(schema=SCHEMA, verdict=COMPARABLE',
     '    if False:\n        return dict(schema=SCHEMA, verdict=COMPARABLE'),
    ('reproduction outranks identity', RULE, '    if identity_failed:\n        return dict(schema=SCHEMA, verdict=NOT_COMPARABLE',
     '    if identity_failed and not reproduced:\n        return dict(schema=SCHEMA, verdict=NOT_COMPARABLE'),
    ('a failed criterion is not_comparable', RULE, 'verdict=REQUALIFY if failed else REBASED', 'verdict=NOT_COMPARABLE if failed else REBASED'),
    ('nothing is ever re-based', RULE, 'verdict=REQUALIFY if failed else REBASED', 'verdict=REQUALIFY'),
    ('reproduction counts as identity', VERDICT, "if not item['ok'] and item['check'] != 'reproduced']", "if not item['ok']]"),
    ('requalify judged as a continuation', VERDICT, '    elif comparison == rebase_rule.REQUALIFY:\n', '    elif False:\n'),
    ('re-based is not comparable', VERDICT, 'comparable=comparison in (rebase_rule.COMPARABLE, rebase_rule.REBASED)',
     'comparable=comparison == rebase_rule.COMPARABLE'),
    # Measurement: the original span, the forced final minute, entries only, the equity gap.
    ('forced final minute counted', RULE, '    inside = [row for row in rows if row[0] < cut]', '    inside = [row for row in rows if row[0] <= cut]'),
    ('closes counted as deals', RULE, "deal_count=sum(row['deal_entry'] == '0' for row in inside)", 'deal_count=len(inside)'),
    ('equity gap is the smallest', RULE, 'return float(max(gaps)) if gaps else None', 'return float(min(gaps)) if gaps else None'),
    # Every window on the re-test, never spliced.
    ('FOOS starts at the original end', RULE, 'FOOS=(to_date, tested_through)',
     "FOOS=(date.fromisoformat(original['evidence_end']) + timedelta(days=1), tested_through)"),
    ('windows from the original run', VERDICT, 'rebase_rule.rebased_windows(original, retest, new_rows, new_deals,',
     "rebase_rule.rebased_windows(original, retest, old_rows, old_deals,"),
    ('no re-based windows for requalify', VERDICT, '    if comparison in (rebase_rule.REBASED, rebase_rule.REQUALIFY):\n        # The re-test',
     '    if comparison == rebase_rule.REBASED:\n        # The re-test'),
    ('import restores the original FOOS', CATCHUP, 'original_foos=None if rebased else original_foos', 'original_foos=original_foos'),
    ('import gets no re-based windows', CATCHUP, "windows=verdict.get('rebasedWindows') if rebased else None", 'windows=None'),
    ('requalify carries status', CATCHUP, "carriesStatus=verdict.get('comparison') in ('comparable', 'comparable_rebased')",
     'carriesStatus=True'),
    ('requalify catches the original up', CATCHUP, "get('verdict') not in UNCARRIED]", "get('verdict') not in UNJUDGED]"),
    # Stamps on the verdict, the summary and evidence-version.json.
    ('verdict drops the drift stamp', VERDICT, "tickHistoryDrift=rebase.get('tickHistoryDrift'), rebasedWindows=windows,",
     'rebasedWindows=windows,'),
    ('verdict drops the history basis', VERDICT, "historyBasis=rebase.get('historyBasis'), tickHistoryDrift=", 'tickHistoryDrift='),
    ('version drops the stamps', CATCHUP,
     "                       comparison=verdict.get('comparison'), historyBasis=verdict.get('historyBasis'),\n                       tickHistoryDrift=verdict.get('tickHistoryDrift'), rebase=verdict.get('rebase'),\n",
     "                       rebase=verdict.get('rebase'),\n"),
    ('summary drops the stamps', CATCHUP,
     "                       evidenceEndMode=verdict['evidenceEndMode'], comparison=verdict.get('comparison'),\n                       historyBasis=verdict.get('historyBasis'), tickHistoryDrift=verdict.get('tickHistoryDrift'))",
     "                       evidenceEndMode=verdict['evidenceEndMode'])"),
    # The OOS formula gates on the re-based evidence.
    ('requalify skips the gates', CATCHUP, "        if verdict.get('verdict') in ('not_comparable', 'unjudged'):",
     "        if verdict.get('verdict') in ('not_comparable', 'unjudged', 'requalify'):"),
    ('gates not stamped with their basis', CATCHUP, "            result.update(evidenceBasis='retest', comparison=comparison,",
     "            result.update(comparison=comparison,"),
    ('drift not redacted inside a lock', 'studio_heldout_guard.py', "    'rebase', 'tickHistoryDrift', 'rebasedWindows',\n", ''),
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
