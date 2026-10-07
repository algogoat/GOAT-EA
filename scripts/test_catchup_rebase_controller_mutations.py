"""Mutation check for the catch-up swap-only drift rule (goat-catchup-rebase-v2, goatai#1885 6029484888).

Each rule, each boundary ($5 / 2% swap, $0.01 money, 10% max DD) and its direction, the first failing rule,
every verdict branch and every stamp (comparable_rebased, requalify, not_comparable, historyBasis,
tickHistoryDrift, firstFailingRule / firstDifference, the re-based windows with no splice) is weakened in a
temporary copy of controller/, and controller/test_studio_catchup_rebase.py or test_studio_catchup_verdict.py
must fail. The repository is never modified. Works with an embedded Python that ignores cwd (sys.path is set
here). GOAT_MUTATION_TMP may name the scratch folder.
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
    # The swap rule: max($5, 2% of the ORIGINAL's |total swap|), both directions, inclusive.
    ('swap floor is $6', RULE, "SWAP_FLOOR = Decimal('5')", "SWAP_FLOOR = Decimal('6')"),
    ('swap share is 3%', RULE, "SWAP_OF_TOTAL = Decimal('0.02')", "SWAP_OF_TOTAL = Decimal('0.03')"),
    ('swap bound takes the smaller', RULE, 'max(SWAP_FLOOR, SWAP_OF_TOTAL', 'min(SWAP_FLOOR, SWAP_OF_TOTAL'),
    ("swap bound on the re-test's total", RULE, "SWAP_OF_TOTAL * abs(swap['original'])", "SWAP_OF_TOTAL * abs(swap['retest'])"),
    ('swap bound is strict', RULE, '        ok = abs(delta) <= bound', '        ok = abs(delta) < bound'),
    ('swap bound is one-sided', RULE, '        ok = abs(delta) <= bound', '        ok = delta <= bound'),
    ('unmeasured swap passes', RULE, "rules.append(_rule('swap', False, 'not measured", "rules.append(_rule('swap', True, 'not measured"),
    ('total swap ignores floating swap', RULE, 'return total, total + sum(floating.values(), Decimal(0))', 'return total, total'),
    # The money rules: a cent, inclusive; balance on realized swap, equity on cumulative swap as of the last tick.
    ('money tolerance is two cents', RULE, "MONEY_TOLERANCE = Decimal('0.01')", "MONEY_TOLERANCE = Decimal('0.02')"),
    ('money tolerance is strict', RULE, "if residual > MONEY_TOLERANCE and item['first'] is None:", "if residual >= MONEY_TOLERANCE and item['first'] is None:"),
    ('balance ignores the swap', RULE, "(('balance', b[2] - a[2], b[4] - a[4])", "(('balance', b[2] - a[2], 0)"),
    ('equity on the realized swap', RULE, "('equity', b[3] - a[3], equity_swap))", "('equity', b[3] - a[3], b[4] - a[4]))"),
    ('equity ignores the last tick', RULE, '        quote = a[6] if a[6] and a[6] == b[6] else a[0]', '        quote = a[0]'),
    ('marks applied by time, not ordinal', RULE, 'while pending is not None and pending[0] < ordinal:', 'while pending is not None and pending[1] <= stamp:'),
    ('account rows need not line up', RULE, '        if a is None or b is None or a[:2] != b[:2]:', '        if a is None or b is None:'),
    ('a missing account row is ignored', RULE, 'enumerate(zip_longest(original_states, retest_states))', 'enumerate(zip(original_states, retest_states))'),
    ('reader ignores the quote time', RULE, 'Decimal(row[e]), int(row[q])', 'Decimal(row[e]), int(row[t])'),
    # Exact behaviour: orders (all but the ordinal) and deals (time, type, entry, lots, price, profit; magic and swap ignored).
    ('orders compare the ordinal', RULE, "ORDER_IGNORED = frozenset(('ordinal',))", 'ORDER_IGNORED = frozenset()'),
    ('orders never differ', RULE, 'orders = compare_rows(cut(old_orders), cut(new_orders), old_fields)',
     'orders = compare_rows(cut(old_orders), cut(old_orders), old_fields)'),
    ('unmeasured orders pass', RULE, "rules.append(_rule('orders', False, 'not measured", "rules.append(_rule('orders', True, 'not measured"),
    ('deals compare magic', RULE, "'price', 'profit')\nNUMERIC", "'price', 'profit', 'deal_magic')\nNUMERIC"),
    ('deals compare swap', RULE, "'price', 'profit')\nNUMERIC", "'price', 'profit', 'swap')\nNUMERIC"),
    ('deals ignore profit', RULE, "'price', 'profit')\nNUMERIC", "'price')\nNUMERIC"),
    ('deals ignore price', RULE, "'lots', 'price', 'profit')\nNUMERIC", "'lots', 'profit')\nNUMERIC"),
    ('unmeasured deals pass', RULE, "rules.append(_rule('deals', False, 'not measured", "rules.append(_rule('deals', True, 'not measured"),
    ('capture ignored', RULE, "rules.append(_rule('capture', not missing,", "rules.append(_rule('capture', True,"),
    ('a missing capture file is not recorded', RULE, "            run['missing'].append(name + '.csv missing')\n", "            pass\n"),
    # Max DD within 10% relative, both directions, inclusive; unmeasured fails.
    ('DD bar is 11%', RULE, "DD_REL = Decimal('0.10')", "DD_REL = Decimal('0.11')"),
    ('DD bar is strict', RULE, '        ok = abs(b - a) <= limit', '        ok = abs(b - a) < limit'),
    ('DD bar is one-sided', RULE, '        ok = abs(b - a) <= limit', '        ok = (b - a) <= limit'),
    ('unmeasured DD passes', RULE, "rules.append(_rule('max_dd', False,", "rules.append(_rule('max_dd', True,"),
    # The verdict: anything failed is requalify (fail-safe); first failing rule logged; no aggregate path.
    ('a failed rule re-bases', RULE, "verdict=REQUALIFY, firstFailingRule=first['rule']", "verdict=REBASED, firstFailingRule=first['rule']"),
    ('a failed rule is not_comparable', RULE, "verdict=REQUALIFY, firstFailingRule=first['rule']", "verdict=NOT_COMPARABLE, firstFailingRule=first['rule']"),
    ('first failing rule is the last', RULE, "first = next((row for row in rules if not row['ok']), None)",
     "first = next((row for row in reversed(rules) if not row['ok']), None)"),
    ('only the first failure is named', RULE, "failed = [row['rule'] for row in rules if not row['ok']]",
     "failed = [row['rule'] for row in rules if not row['ok']][:1]"),
    ('nothing measured passes', RULE, "check = check or dict(rules=[_rule('capture', False,", "check = check or dict(rules=[_rule('capture', True,"),
    ('judge skips the behaviour check', RULE, 'check = behaviour_check(read_run(old_deals', 'check = None and behaviour_check(read_run(old_deals'),
    ('exact reproduction is not the fast path', RULE, '    if reproduced:\n        return dict(blank, verdict=COMPARABLE',
     '    if False:\n        return dict(blank, verdict=COMPARABLE'),
    ('reproduction outranks identity', RULE, '    if identity_failed:\n        return dict(blank, verdict=NOT_COMPARABLE',
     '    if identity_failed and not reproduced:\n        return dict(blank, verdict=NOT_COMPARABLE'),
    ('swap cause mislabelled', RULE, 'tickHistoryDrift=dict(stamp, cause=SWAP_OR_SPEC,', 'tickHistoryDrift=dict(stamp, cause=HISTORY_OR_BEHAVIOUR,'),
    ('requalify cause mislabelled', RULE, 'tickHistoryDrift=dict(stamp, cause=HISTORY_OR_BEHAVIOUR,', 'tickHistoryDrift=dict(stamp, cause=SWAP_OR_SPEC,'),
    # Review flag on a re-based set (Claude-Mac, goatai#1885 6010080246).
    ('swap review bar is 6%', RULE, "SWAP_REVIEW_OF_NET = Decimal('0.05')", "SWAP_REVIEW_OF_NET = Decimal('0.06')"),
    ('swap review bar is inclusive', RULE, '    if delta > limit:\n        return True, (', '    if delta >= limit:\n        return True, ('),
    ('swap review is one-sided', RULE, 'delta, limit = abs(r - o), SWAP_REVIEW_OF_NET', 'delta, limit = (r - o), SWAP_REVIEW_OF_NET'),
    ('swap review ignores a losing net', RULE, 'SWAP_REVIEW_OF_NET * abs(o - base)', 'SWAP_REVIEW_OF_NET * (o - base)'),
    ('unsized swap drift not flagged', RULE, "        return True, 'swap drift could not be sized", "        return False, 'swap drift could not be sized"),
    ('swap review flag dropped', RULE, 'cause=SWAP_OR_SPEC, reviewFlag=flag,', 'cause=SWAP_OR_SPEC, reviewFlag=False,'),
    # Across builds: the same rule, recorded.
    ('evaluate never sees a cross build', VERDICT, "    cross_build = bool(((pins or {}).get('equivalence') or {}).get('mode') == 'active')",
     '    cross_build = False'),
    ('judge drops the cross build', RULE, 'max_equity_gap=equity_gap(old_rows, new_rows, cut),\n                    cross_build=cross_build)',
     'max_equity_gap=equity_gap(old_rows, new_rows, cut))'),
    ('history basis source dropped', RULE, "originalExportedAtBasis='set_mtime',", ''),
    # The verdict module.
    ('reproduction counts as identity', VERDICT, "if not item['ok'] and item['check'] != 'reproduced']", "if not item['ok']]"),
    ('requalify judged as a continuation', VERDICT, '    elif comparison == rebase_rule.REQUALIFY:\n', '    elif False:\n'),
    ('re-based is not comparable', VERDICT, 'comparable=comparison in (rebase_rule.COMPARABLE, rebase_rule.REBASED)',
     'comparable=comparison == rebase_rule.COMPARABLE'),
    ('verdict drops the first failing rule', VERDICT, "firstFailingRule=rebase.get('firstFailingRule'), firstDifference=rebase.get('firstDifference'),", ''),
    # Measurement for the drift stamp: the original span, entries only, the equity gap.
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
    # Stamps on the verdict, the summary (the receipt) and evidence-version.json.
    ('verdict drops the drift stamp', VERDICT, "tickHistoryDrift=rebase.get('tickHistoryDrift'), rebasedWindows=windows,",
     'rebasedWindows=windows,'),
    ('verdict drops the history basis', VERDICT, "historyBasis=rebase.get('historyBasis'), tickHistoryDrift=", 'tickHistoryDrift='),
    ('version drops the stamps', CATCHUP,
     "                       comparison=verdict.get('comparison'), historyBasis=verdict.get('historyBasis'),\n                       tickHistoryDrift=verdict.get('tickHistoryDrift'), rebase=verdict.get('rebase'),\n",
     "                       rebase=verdict.get('rebase'),\n"),
    ('summary drops the drift stamp', CATCHUP,
     "                       tickHistoryDrift=verdict.get('tickHistoryDrift'),\n                       firstFailingRule=",
     '                       firstFailingRule='),
    ('summary drops the first failing rule', CATCHUP,
     ",\n                       firstFailingRule=verdict.get('firstFailingRule'), firstDifference=verdict.get('firstDifference'))", ')'),
    # The OOS formula gates on the re-based evidence.
    ('requalify skips the gates', CATCHUP, "        if verdict.get('verdict') in ('not_comparable', 'unjudged'):",
     "        if verdict.get('verdict') in ('not_comparable', 'unjudged', 'requalify'):"),
    ('gates not stamped with their basis', CATCHUP, "            result.update(evidenceBasis='retest', comparison=comparison,",
     "            result.update(comparison=comparison,"),
    ('drift not redacted inside a lock', 'studio_heldout_guard.py', "    'rebase', 'tickHistoryDrift', 'rebasedWindows', 'firstDifference',\n", ''),
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
