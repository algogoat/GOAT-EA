"""Rule version 1 of the OOS window rule judges exactly as the evaluator did before version 2 existed.

The evaluator as it was (GOAT-EA a8c6766, the commit rule version 2 was built on) is read from git history and run
next to the current one. Under ``rule_version=1`` the current ``judge_window``, ``judge``, ``judge_case`` and
``judge_retest`` must return what the old code returned, value for value; the only addition allowed is the
``ruleVersion: 1`` stamp on a set's record. So every verdict stored before version 2 stays reproducible, and
``oos-rule-recount`` shows a stored catch-up's version 1 column from the same arithmetic that stored it.

The shared fixture is checked the same way: every case the old fixture held is still there with the same inputs
and the same expected result, now naming ``rule_version: 1``.

``judge_retest`` reads the equity CSV and deals through studio_catchup_verdict, which both evaluators import from
this tree; rule version 2 did not change it.

The test needs the repository's history (the controller CI job checks out with fetch-depth 0). It is skipped in a
copy of controller/ without a repository, as the mutation scripts make.
"""
from itertools import product
import json
from pathlib import Path
import random
import subprocess
import types
import unittest

import studio_oos_windows as w
from test_studio_oos_windows import RetestFixture

BASE = 'a8c6766243ff577bdcfc90495a6de33ce0797c88'
ROOT = Path(__file__).resolve().parent.parent


def _show(path):
    return subprocess.run(['git', 'show', BASE + ':' + path], cwd=ROOT, capture_output=True, check=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.decode('utf-8')


def stamped(result):
    """A version 1 result without the one key version 1 gained: the stamp that says it is version 1."""
    if isinstance(result, dict) and 'ruleVersion' in result:
        assert result['ruleVersion'] == 1, result['ruleVersion']
        return {key: value for key, value in result.items() if key != 'ruleVersion'}
    return result


@unittest.skipUnless((ROOT / '.git').exists(), 'needs the repository history (git show %s)' % BASE[:7])
class RuleVersion1UnchangedTests(RetestFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = types.ModuleType('studio_oos_windows_before_rule_version_2')
        exec(compile(_show('controller/studio_oos_windows.py'), 'studio_oos_windows@' + BASE[:7], 'exec'), cls.old.__dict__)
        cls.old_fixture = json.loads(_show('controller/fixtures/oos-holdout-gate-cases.json'))
        cls.fixture = json.loads((Path(__file__).resolve().parent / w.FIXTURE).read_text(encoding='utf-8'))

    def test_the_old_evaluator_is_the_one_before_rule_versions(self):
        self.assertFalse(hasattr(self.old, 'RULE_VERSION'))
        self.assertEqual((self.old.EVALUATION, self.old.MIN_TRADES, self.old.MAX_DD_RATIO), (w.EVALUATION, w.MIN_TRADES, w.MAX_DD_RATIO))
        self.assertEqual(self.old.DEFINITIONS, w.DEFINITIONS_V1)

    def windows(self):
        """Window inputs over every branch of the gate: absent, incomplete, the floor, PF, net, drawdown, p10, counts."""
        grid = product((None, 0, 29, 30, 45), (None, 0.5, 1.0, 1.3), (None, -80.01, -80.0, -0.01, 0.0, 12.5),
                       (None, 0.0, 150.0, 150.01), (None, -80.0, 25.0), ('absent', 0, 4, 17))
        for trades, pf, pl, dd, p10, count in grid:
            value = dict(trades=trades, pf=pf, pl=pl, dd=dd, in_sample_p10=p10)
            if count != 'absent':
                value['in_sample_windows'] = count
            yield value
        yield None
        yield dict(present=False)
        yield dict(trades=40, pf=None, pf_note='no losing deals', pl=30.0, dd=10.0)
        yield dict(trades=40, pf=1.2, dd=10.0, complete=False, tested_through='2026-09-18', last_day='2026-10-02')
        yield dict(trades=True, pf=1.2, dd=10.0)
        yield dict(trades=40, pf=True, pl=False, dd=True, in_sample_p10=True)

    def test_judge_window_under_version_1(self):
        compared = 0
        for value in self.windows():
            for in_sample_dd, lenient in product((None, 0.0, 100.0), (False, True)):
                name = 'BOOS' if lenient else 'FOOS'
                was = self.old.judge_window(name, value, in_sample_dd, lenient=lenient)
                now = w.judge_window(name, value, in_sample_dd, lenient=lenient, rule_version=1)
                self.assertEqual(now, was, (value, in_sample_dd, lenient))
                compared += 1
        self.assertGreater(compared, 30000)

    def test_judge_under_version_1(self):
        pool = list(self.windows())
        chooser = random.Random(20261111)
        for _ in range(4000):
            boos, foos = chooser.choice(pool), chooser.choice(pool)
            in_sample_dd, formula = chooser.choice((None, 0.0, 100.0, 0.2)), chooser.choice(('boos-1/3', 'boos-1/2'))
            was = self.old.judge(boos, foos, in_sample_dd=in_sample_dd, oos_formula=formula)
            now = w.judge(boos, foos, in_sample_dd=in_sample_dd, oos_formula=formula, rule_version=1)
            self.assertEqual(now['ruleVersion'], 1)
            self.assertEqual(stamped(now), was, (boos, foos, in_sample_dd, formula))
        self.assertEqual(stamped(w.not_applicable('x', 1)), self.old.not_applicable('x'))

    def test_every_old_fixture_case_is_still_there_unchanged_and_judged_the_same(self):
        for group in ('window_cases', 'set_cases', 'date_cases'):
            kept = {case['id']: case for case in self.fixture[group]} if group != 'date_cases' else None
            for case in self.old_fixture[group]:
                with self.subTest(group=group, case=case.get('id', case)):
                    if group == 'date_cases':
                        self.assertIn(case, self.fixture[group])
                        continue
                    self.assertEqual(kept[case['id']], dict(case, rule_version=1))            # the same inputs, now naming version 1
                    was = self.old.judge_case(case)
                    self.assertEqual(was['status'], case['expected'])
                    self.assertEqual(stamped(w.judge_case(kept[case['id']])), was)
                    self.assertEqual(stamped(w.judge_case(case)), was)                        # a case that names no version is version 1
        for key in ('fractions_of_o', 'min_trades', 'min_pf', 'max_dd_multiple_of_in_sample', 'statuses', 'set_order'):
            self.assertEqual(self.fixture['rules'][key], self.old_fixture['rules'][key], key)
        self.assertEqual((self.fixture['schema'], self.fixture['sync']), (self.old_fixture['schema'], self.old_fixture['sync']))

    def scenarios(self):
        yield 13, None, dict()
        yield 13, None, dict(losers=dict(foos=25))
        yield 13, None, dict(dips=dict(boos=151.0))
        yield 13, None, dict(dips=dict(sample=100.0, fwd=140.0, foos=180.0))
        yield 13, None, dict(dips=dict(sample=0.0))                              # no SAMPLE drawdown: no limit
        yield 13, None, dict(trades=dict(foos=29))
        yield 13, None, dict(trades=dict(foos=20, catchup=12), end='2026-10-16')
        yield 13, None, dict(end='2026-09-25')
        yield 13, None, dict(end='2026-08-14')                                   # the re-test stops inside FWD
        yield 13, None, dict(end='2026-06-26', losers=dict(boos=21))            # ... inside SAMPLE, with a BOOS loss
        yield 13, None, dict(capture=False)
        yield 13, None, dict(trades=dict(boos=30), losers=dict(boos=21, sample=30))
        yield 13, None, dict(trades=dict(boos=30), losers=dict(boos=30, sample=30))
        yield 13, None, dict(losers=dict(boos=21))
        yield 26, 'boos-1/2', dict(losers=dict(boos=21, sample=30))
        yield 26, 'boos-1/2', dict(losers=dict(boos=30, sample=30))
        yield 4, None, dict(losers=dict(boos=21))
        yield 52, None, dict(losers=dict(boos=30, sample=30))
        yield 52, None, dict(losers=dict(boos=21, sample=30))

    def test_judge_retest_under_version_1(self):
        statuses = set()
        for o_weeks, formula, kwargs in self.scenarios():
            with self.subTest(o_weeks=o_weeks, formula=formula, kwargs=kwargs):
                self.record = w.compute(o_weeks, '2026-10-02', formula or w.OOS_FORMULA)
                original, retest = self.build(**kwargs)
                for extra in (dict(), dict(evidence_end='2026-10-02'), dict(oos_formula='boos-1/3')):
                    was = self.old.judge_retest(original, retest, tester=self.record['tester'], **extra)
                    now = w.judge_retest(original, retest, tester=self.record['tester'], rule_version=1, **extra)
                    self.assertEqual(now['ruleVersion'], 1)
                    self.assertEqual(stamped(now), was, extra)
                    statuses.add(was['status'])
        self.assertEqual(statuses, {'pass', 'fail', 'not_eligible_yet', 'no_data', 'not_measured', 'not_applicable'})
        # Explicit (non-formula) dates and an export that already saw FOOS: not applicable, as before.
        self.record = w.compute(13, '2026-10-02')
        original, retest = self.build()
        explicit = dict(FromDate='2026.02.01', ToDate='2026.09.01', ForwardDate='2026.07.01')
        for tester, source in ((explicit, original), (None, original), (self.record['tester'], dict(original, evidence_end='2026-09-11'))):
            self.assertEqual(stamped(w.judge_retest(source, retest, tester=tester, rule_version=1)),
                             self.old.judge_retest(source, retest, tester=tester))


if __name__ == '__main__':
    unittest.main()
