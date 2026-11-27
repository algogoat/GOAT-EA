"""build-set adds a DECLARED input the source SET omits; an undeclared name still refuses (Claude-Mac goatai#2943 7213040506).

Why: the EA writes an appended input only off its default (WriteSet, GOAT V1.49.mq5:593 for Engine_Mode; inputs 975-976 for the
B54 BRK_/ORB_ modes), so no catalog or hunt SET carries Engine_Mode or BRK_Mode. Before this change build-set read
values[name] for every change and raised KeyError('Engine_Mode') on the hunt hawk base (2026-11-27 07:59Z, Ops' Engine_Single
smoke), so no catalog base could become a single-engine or breakout template.

Fixture: the hunt hawk base SET (research seed-defaults hw2-hawk-trend-breakout.set, sha256 db36010a..., UTF-16 LE BOM, CRLF,
committed byte-identical under controller/fixtures/build-set, -text) against this tree's contracts/v149 inputs.json and
dependencies.json. Positive: Engine_Mode=Engine_Single (1) and BRK_Mode=BRK_NBar (1) are ADDED (with the single engine's
required Single_SL_ATR > 0 and a bias exit other than Smart Rescue, both changed lines the source already has), in declared
order, and the built SET passes validate_raw and the EA-init mirror. Negative: an undeclared name refuses; restating a declared
default the omitted line already means refuses; and an added input that the EA would refuse at init (BRK_Mode on the grid
engine; the single engine without its stop) refuses with the init rule, before any output exists.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from studio_template_tools import build_set, validate_set
from studio_strategy_settings import read_values

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'fixtures' / 'build-set' / 'hw2-hawk-trend-breakout.set'
FIXTURE_SHA256 = 'db36010a5e03c90664c97e543d391ebfc070aec1806822cf2a9468857866446a'
SINGLE_NBAR = {'Engine_Mode': '1', 'BRK_Mode': '1', 'Single_SL_ATR': '1.5||1.0||0.5||3.0||Y', 'Mode_Bias_Exit': '0'}


class BuildSetDeclaredInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        contracts = HERE / 'contracts' / 'v149'
        cls.schema = json.loads((contracts / 'inputs.json').read_text(encoding='utf-8-sig'))
        cls.policy = json.loads((contracts / 'dependencies.json').read_text(encoding='utf-8-sig'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.source = self.root / 'hawk.set'; shutil.copyfile(FIXTURE, self.source)

    def tearDown(self): self.tmp.cleanup()

    def build(self, changes, name='out.set'):
        spec = dict(ea_desc='Hawk base on the single engine with N-bar breakout', changes=changes,
                    rationale={key: 'Fixture change for the declared-input rule.' for key in changes},
                    summary='Fixture', entry_logic='Fixture', ladder_exits='Fixture', intended_role='Fixture')
        return build_set(self.source, self.root / name, spec, self.schema, self.policy, controller_version='test', ea_version='1.49')

    def test_fixture_is_the_hunt_hawk_base_and_omits_both_inputs(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        values = read_values(raw)
        self.assertNotIn('Engine_Mode', values); self.assertNotIn('BRK_Mode', values)
        self.assertIn('Engine_Mode', self.schema['inputs']); self.assertIn('BRK_Mode', self.schema['inputs'])

    def test_positive_control_adds_declared_engine_and_breakout_in_declared_order(self):
        record = self.build(SINGLE_NBAR)
        out = Path(record['output']['path']).read_bytes()
        self.assertTrue(out.startswith(b'\xff\xfe'))
        after = read_values(out); before = read_values(FIXTURE.read_bytes())
        self.assertEqual(after['Engine_Mode'], '1'); self.assertEqual(after['BRK_Mode'], '1')
        # every other source value unchanged; exactly the two added names are new
        self.assertEqual(set(after) - set(before), {'Engine_Mode', 'BRK_Mode'})
        for key in before:
            if key not in SINGLE_NBAR and key != 'EA_Desc': self.assertEqual(after[key], before[key], key)
        # declared order: each added line sits right after the last source input declared before it
        lines = [line.split('=', 1)[0] for line in out.decode('utf-16').splitlines() if '=' in line and not line.startswith(';')]
        order = list(self.schema['inputs'])
        for name in ('Engine_Mode', 'BRK_Mode'):
            i = lines.index(name)
            self.assertLess(order.index(lines[i - 1]), order.index(name))
            self.assertGreater(order.index(lines[i + 1]), order.index(name))
        text = out.decode('utf-16'); self.assertEqual(text.count('\r\n'), len(text.splitlines()))
        added = {c['input']: c for c in record['changes'] if c.get('added')}
        self.assertEqual(set(added), {'Engine_Mode', 'BRK_Mode'})
        self.assertIsNone(added['Engine_Mode']['before']); self.assertEqual(added['Engine_Mode']['declared_default'], '0')
        self.assertEqual(added['BRK_Mode']['declared_default'], '0')
        self.assertIn('(absent: declared default 0)', Path(record['support_path']).read_text(encoding='utf-8'))
        # the built SET is a valid optimization template under the installed schema and the EA-init mirror
        report = validate_set(Path(record['output']['path']), self.schema, self.policy, require_optimization=True)
        self.assertIn('Single_SL_ATR', report['active_axes'])

    def test_undeclared_name_still_refuses_before_any_output(self):
        with self.assertRaisesRegex(ValueError, 'Unknown input or reserved EA_Desc change: Not_A_Declared_Input'):
            self.build(SINGLE_NBAR | {'Not_A_Declared_Input': '1'})
        self.assertFalse((self.root / 'out.set').exists())

    def test_restating_the_declared_default_refuses(self):
        with self.assertRaisesRegex(ValueError, 'Engine_Mode is omitted by the source, which already means its declared default 0'):
            self.build({'Engine_Mode': '0'})
        with self.assertRaisesRegex(ValueError, 'BRK_Mode is omitted by the source'):
            self.build({'BRK_Mode': '0||0||0||0||N'})

    def test_added_input_the_ea_refuses_at_init_refuses(self):
        with self.assertRaisesRegex(ValueError, 'BRK_WITHOUT_SINGLE'):
            self.build({'BRK_Mode': '1'})
        with self.assertRaisesRegex(ValueError, 'SINGLE_SL_ATR_NOT_POSITIVE'):
            self.build({'Engine_Mode': '1', 'BRK_Mode': '1'})
        with self.assertRaisesRegex(ValueError, 'Undeclared enum'):
            self.build(SINGLE_NBAR | {'BRK_Mode': '7'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['hawk.set'])


if __name__ == '__main__':
    unittest.main()
