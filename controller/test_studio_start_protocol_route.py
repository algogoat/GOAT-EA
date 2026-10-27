"""Exercise the actual native qualification predicate for both launch routes.

Source predicates are evaluated, not replaced with a separately maintained model.
This is a source regression fixture, not qualification of any MT5 installation.
"""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


class StartProtocolRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'GOATStudioDispatch.mqh').read_text(encoding='utf-8-sig').split(
            'string GoatStudioExecuteRequest(', 1)[1].split('void GoatStudioDispatch(', 1)[0]
        match = re.search(r'if\(([^\n]+)\) return "START_PROTOCOL_NOT_QUALIFIED";', cls.source)
        if match is None:
            raise AssertionError('Native build qualification predicate is absent')
        cls.predicate = match.group(1).replace('&&', ' and ')
        tree = ast.parse(cls.predicate, mode='eval')
        allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Compare, ast.Name,
                   ast.Load, ast.Constant, ast.Eq, ast.NotEq)
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise AssertionError('Unexpected qualification predicate syntax')
        cls.code = compile(tree, '<native-start-build-predicate>', 'eval')

    def refused(self, action, build):
        return eval(self.code, {'__builtins__': {}}, {'action': action, 'start_build': build})

    def test_direct_start_keeps_exact_qualified_builds(self):
        for build in (6182, 6230):
            with self.subTest(build=build):
                self.assertFalse(self.refused('start', build))
        for build in (0, 1, 6181, 6183, 6229, 6231, 999999):
            with self.subTest(build=build):
                self.assertTrue(self.refused('start', build))

    def test_config_arm_is_not_an_undocumented_start_message(self):
        for build in (0, 6181, 6182, 6230, 6231, 999999):
            with self.subTest(build=build):
                self.assertFalse(self.refused('arm_restart', build))
        arm = self.source.split('if(action=="arm_restart")', 1)[1].split(
            'return "RESTART_ARMED_RECONCILE";', 1)[0]
        self.assertNotIn('ClickStart', arm)
        self.assertNotIn('SetSettings', arm)
        self.assertIn('"RESTART_RUNTIME_CHANGED"', arm)
        self.assertIn('"ARM_INTENT_WRITE_FAILED"', arm)
        self.assertIn('"HUMAN_CANCEL_RETAINED"', arm)

    def test_route_selection_and_safety_checks_still_precede_consumption(self):
        before_consumed = self.source.split('"GOATStudio\\\\native-gate\\\\consumed-"', 1)[0]
        for guard in ('action!="start" && action!="arm_restart"',
                      'action=="start" && has_restart',
                      'action=="arm_restart" && !restart_matched',
                      '"NATIVE_CONTROL_DRIFT"', '"CONTROL_REVOKED"',
                      '"RUNTIME_NOT_READY"', '"JOB_NOT_STARTING"',
                      '"HUMAN_CANCEL_RETAINED"'):
            self.assertIn(guard, before_consumed)
        self.assertEqual(self.source.count('MTTESTER::ClickStart(false,1)'), 1)


if __name__ == '__main__':
    unittest.main()
