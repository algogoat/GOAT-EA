"""The held-out guard fails closed (Claude-Mac on goatai#1885, after GOAT-EA#164).

1. guard_output used to return a reply UNREDACTED when its Context could not be built (a missing or
   malformed installation field): it now redacts every derived value, as when the registry cannot be
   verified.
2. gate-recommend and gate-stamp printed their replies unguarded. They aggregate every export on this PC,
   so no part can be attributed to one strategy or window: they now refuse, before reading evidence or
   writing a file, without a readable installation, with an unverifiable registry, or while any lock is
   active; their replies pass guard_output.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_heldout import LOCKED, UNAVAILABLE
from studio_heldout_guard import guard_output
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
        code, stdout, stderr = self.recommend()
        self.assertEqual(code, 0, stderr)
        self.assertTrue(json.loads(stdout)['ok'])
        self.assertTrue((self.out / 'recommendation.json').exists())


if __name__ == '__main__':
    unittest.main()
