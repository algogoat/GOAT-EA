"""The held-out guard fails closed (Claude-Mac on goatai#1885, after GOAT-EA#164).

1. guard_output used to return a reply UNREDACTED when its Context could not be built (a missing or
   malformed installation field): it now redacts every derived value, as when the registry cannot be
   verified.
2. gate-recommend and gate-stamp printed their replies unguarded. They aggregate every export on this PC,
   so no part can be attributed to one strategy or window: they now refuse, before reading evidence or
   writing a file, without a readable installation, with an unverifiable registry, or while any lock is
   active; their replies pass guard_output.
3. Positive control (Claude-Mac on GOAT-EA#166): a registry that verifies as not_configured or absent binds
   nothing, so every guard entry point passes through; the fail-closed cases above still refuse.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_heldout import LOCKED, UNATTRIBUTED, UNAVAILABLE, HeldOutRefused, enforce, read_registry, status as heldout_status
from studio_heldout_guard import (check_batch_plan, check_catchup, check_native_start, check_runner_start, check_seed_jobs,
                                  guard_error, guard_output, guard_trial_journal, require_no_active_lock, run_locks)
from test_studio_heldout import declaration, write_registry

REPLY = dict(batch_id='alpha-batch', profit=1990, summary='Best profit 1990 on USDCHF',
             set_name='GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set')


class GuardOutputFailsClosedTests(unittest.TestCase):
    def assertRedacted(self, reply):
        self.assertTrue(reply['profit']['locked'])
        self.assertTrue(reply['summary']['locked'])
        self.assertIn('_Prf=locked', reply['set_name'])
        self.assertNotIn('1990', json.dumps(reply))
        self.assertEqual((reply['heldout']['redacted'], reply['heldout']['code']), (True, UNAVAILABLE))

    def test_a_context_that_cannot_build_redacts_instead_of_passing_through(self):
        for install in ({}, None):                       # KeyError / TypeError: no controller_state_root
            reply = guard_output(install, dict(REPLY))
            self.assertRedacted(reply)
            self.assertIn('could not start', reply['heldout']['error'])
        with tempfile.TemporaryDirectory() as temp:      # an unverifiable registry was already redacted; still is
            self.assertRedacted(guard_output(dict(controller_state_root=temp, evidence_root='relative\\evidence'), dict(REPLY)))

    def test_a_verified_registry_without_locks_still_returns_the_reply_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            install = dict(controller_state_root=str(Path(temp) / 'suite'), evidence_root=str(Path(temp) / 'evidence'))
            value = dict(REPLY)
            self.assertIs(guard_output(install, value), value)


class PositiveControlTests(unittest.TestCase):
    """Positive control for fail-closed (Claude-Mac on GOAT-EA#166): a registry that verifies as ``not_configured``
    (no evidence root for this installation) or ``absent`` (no locks.jsonl yet) binds nothing, so every guard
    entry point passes through. Only ``unavailable``, a context that cannot build, or an active lock refuses."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def install(self, state):
        if state == 'not_configured':       # no evidence_root and a state root outside <data>/suite/<id>
            return dict(controller_state_root=str(self.base / 'state'))
        install = dict(controller_state_root=str(self.base / 'suite' / 'abc'), evidence_root=str(self.base / 'evidence'))
        if state == 'unavailable':          # present but not a readable regular file
            (self.base / 'evidence' / 'heldout' / 'locks.jsonl').mkdir(parents=True)
        elif state == 'locked':
            write_registry(install['evidence_root'], [('declare', declaration('alpha', '2025-01-05', '2028-01-03', '2027-12-31'),
                                                         '2026-10-04T01:00:00Z')])
        return install

    def journal(self):
        return dict(entries=[dict(exposure=dict(start='2026-01-01', end='2026-03-01'), strategy_keys=['alpha'], outcome=dict(profit=1990))])

    def test_not_configured_and_absent_pass_every_guard_through(self):
        for state in ('not_configured', 'absent'):
            with self.subTest(state=state):
                install = self.install(state)
                controller = SimpleNamespace(install=install, root=Path(install['controller_state_root']))
                self.assertEqual(read_registry(install)['state'], state)
                # Replies come back as the same object: nothing redacted, no heldout block, no locked_windows.
                value = dict(REPLY)
                self.assertIs(guard_output(install, value), value)
                self.assertEqual(value, REPLY)
                journal = self.journal()
                self.assertIs(guard_trial_journal(install, journal), journal)
                self.assertEqual(journal, self.journal())
                text = 'Exported ' + REPLY['set_name']
                self.assertEqual(guard_error(install, text), text)
                # Aggregating commands (gate-recommend, gate-stamp) run.
                self.assertEqual(require_no_active_lock(install, command='gate-recommend').registry['state'], state)
                # Every prepare/start enforcement point lets the work through.
                self.assertEqual(check_batch_plan(controller, dict(members=[{}, {}]), {}, []), [None, None])
                self.assertIsNone(check_native_start(controller, 'any-batch'))
                self.assertIsNone(check_runner_start(controller, dict(members=[])))
                self.assertIsNone(check_seed_jobs(controller, {}, []))
                self.assertIsNone(check_catchup(controller, {}, [], dict(iso='2026-10-02')))
                unknown = dict(label='1 (EURUSD M15)', span=None, declared=None, keys=[], reveal=False)
                self.assertEqual(enforce(install, [unknown])['active_locks'], 0)
                self.assertEqual(run_locks(install, controller.root, 'any-batch')['active_locks'], [])
                self.assertEqual(heldout_status(install)['registry']['state'], state)

    def test_the_fail_closed_cases_still_refuse(self):
        unknown = dict(label='1 (EURUSD M15)', span=None, declared=None, keys=[], reveal=False)
        # A context that cannot build: redacted, and the aggregating commands refuse.
        self.assertTrue(guard_output({}, dict(REPLY))['heldout']['redacted'])
        with self.assertRaises(HeldOutRefused) as refused:
            require_no_active_lock({}, command='gate-recommend')
        self.assertEqual(refused.exception.code, UNAVAILABLE)
        for state, code in (('unavailable', UNAVAILABLE), ('locked', None)):
            with self.subTest(state=state):
                temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.base = Path(temp.name)
                install = self.install(state)
                controller = SimpleNamespace(install=install, root=Path(install['controller_state_root']))
                reply = guard_output(install, dict(REPLY))
                self.assertTrue(reply['heldout']['redacted'])
                self.assertNotIn('1990', json.dumps(reply))
                self.assertNotIn('1990', json.dumps(guard_trial_journal(install, self.journal())))
                self.assertIn('_Prf=locked', guard_error(install, REPLY['set_name']))
                with self.assertRaises(HeldOutRefused) as refused:
                    require_no_active_lock(install, command='gate-recommend')
                self.assertEqual(refused.exception.code, code or LOCKED)
                with self.assertRaises(HeldOutRefused) as refused:
                    check_native_start(controller, 'any-batch')       # no readable plan: unknown dates meet every lock
                self.assertEqual(refused.exception.code, code or UNATTRIBUTED)
                with self.assertRaises(HeldOutRefused) as refused:
                    enforce(install, [unknown])
                self.assertEqual(refused.exception.code, code or UNATTRIBUTED)
                if state == 'unavailable':
                    for check in (lambda: check_batch_plan(controller, dict(members=[{}]), {}, []),
                                  lambda: check_runner_start(controller, dict(members=[])),
                                  lambda: check_seed_jobs(controller, {}, []),
                                  lambda: check_catchup(controller, {}, [], dict(iso='2026-10-02'))):
                        with self.assertRaises(HeldOutRefused) as refused:
                            check()
                        self.assertEqual(refused.exception.code, UNAVAILABLE)


@unittest.skipUnless(sys.platform == 'win32', 'demo_agent imports the Windows-only msvcrt')
class GateCommandsGuardedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.common = self.base / 'common'; self.common.mkdir()
        self.out = self.base / 'out'; self.out.mkdir()
        self.install = dict(controller_state_root=str(self.base / 'suite'), evidence_root=str(self.base / 'evidence'))

    def lock(self):
        write_registry(self.install['evidence_root'], [('declare', declaration('alpha', '2025-01-05', '2028-01-03', '2027-12-31'),
                                                         '2026-10-04T01:00:00Z')])

    def run_main(self, argv, *, install=True):
        import demo_agent
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if install:
                with patch.object(demo_agent, 'load_installation', return_value=self.install):
                    code = demo_agent.main(argv)
            else:
                code = demo_agent.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def recommend(self, **kwargs):
        return self.run_main(['--installation', str(self.base / 'installation.json'), 'gate-recommend', '--common-root', str(self.common),
                              '--output', str(self.out / 'recommendation.json')], **kwargs)

    def test_gate_recommend_refuses_without_a_readable_installation(self):
        code, stdout, stderr = self.recommend(install=False)
        self.assertEqual((code, stdout), (1, ''))
        self.assertIn(UNAVAILABLE, stderr)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_gate_recommend_refuses_while_a_lock_is_active_and_writes_nothing(self):
        self.lock()
        code, stdout, stderr = self.recommend()
        self.assertEqual((code, stdout), (1, ''))
        error = json.loads(stderr)
        self.assertEqual(error['code'], LOCKED)
        self.assertIn('reads every export on this PC', error['plain'])
        self.assertEqual(len(error['locked_windows']), 1)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_gate_stamp_refuses_while_a_lock_is_active_and_writes_no_plan(self):
        self.lock()
        plan, recommendation = self.out / 'plan.json', self.out / 'recommendation.json'
        plan.write_text('{}', encoding='utf-8'); recommendation.write_text('{}', encoding='utf-8')
        code, stdout, stderr = self.run_main(['--installation', str(self.base / 'installation.json'), 'gate-stamp', '--plan', str(plan),
                                              '--recommendation', str(recommendation), '--output', str(self.out / 'stamped.json'),
                                              '--generated-at', '2026-10-02T12:00:00Z'])
        self.assertEqual((code, stdout), (1, ''))
        self.assertIn(LOCKED, stderr)
        self.assertFalse((self.out / 'stamped.json').exists())

    def test_gate_recommend_runs_when_no_lock_is_active(self):
        code, stdout, stderr = self.recommend()            # evidence_root without heldout\locks.jsonl: 'absent'
        self.assertEqual(code, 0, stderr)
        self.assertTrue(json.loads(stdout)['ok'])
        self.assertTrue((self.out / 'recommendation.json').exists())

    def test_gate_recommend_runs_when_the_registry_is_not_configured(self):
        self.install = dict(controller_state_root=str(self.base / 'state'))       # no evidence root: 'not_configured'
        code, stdout, stderr = self.recommend()
        self.assertEqual(code, 0, stderr)
        self.assertTrue(json.loads(stdout)['ok'])
        self.assertTrue((self.out / 'recommendation.json').exists())


if __name__ == '__main__':
    unittest.main()
