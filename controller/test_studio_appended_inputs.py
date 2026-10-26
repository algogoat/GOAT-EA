"""B49a (F2, GOAT-EA#265): an input appended to the v149 header after B47 (Ledger_Mode) is optional in a SET.

A SET, template or export written before the input existed omits it; it then takes its declared default
(Ledger_Legacy = 0), which reproduces B47. Everywhere a SET reaches MT5 or is compared with MT5, the omitted input is
the default: validation, the scalar paste (never inherited from the terminal's previous run), the input readback
(a tester that ran PositionJoin for a SET that never asked for it is caught), and export verification.
"""
import json
from pathlib import Path
import unittest

from studio_strategy_settings import (APPENDED_INPUTS, appended_default, complete_appended_inputs, read_values,
                                      validate_strategy)
from studio_input_readback import explicit_paste_inputs, verify_input_readback
import studio_tester_report as tester_report
from test_studio_pinned_tester_inputs import compass_like_template

ROOT = Path(__file__).resolve().parent


class AppendedInputTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        raw = ('\r\n'.join(compass_like_template(self.schema).splitlines())+'\r\n').encode('utf-16')
        self.full = read_values(raw)
        self.old = {k: v for k, v in self.full.items() if k not in APPENDED_INPUTS}   # a B47-era SET

    def test_the_appended_inputs_are_ledger_mode_last_in_the_header_defaulting_to_legacy(self):
        self.assertEqual(APPENDED_INPUTS, ('Ledger_Mode',))
        self.assertEqual(list(self.schema['inputs'])[-1], 'Ledger_Mode')
        definition = self.schema['inputs']['Ledger_Mode']
        self.assertEqual((definition['type'], definition['declaration'], definition['default_expression']),
                         ('ENUM_LEDGER_MODE', 'sinput', 'Ledger_Legacy'))
        self.assertEqual(definition['enum_choices'], {'Ledger_Legacy': 0, 'Ledger_PositionJoin': 1})
        self.assertEqual(appended_default(definition), '0')
        # The same default the tester report pins for any omitted input (GOAT-EA#250).
        self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), '0')

    def test_a_set_without_it_validates_and_carries_the_default(self):
        checked = validate_strategy(dict(self.old), self.schema)
        self.assertEqual(checked['values']['Ledger_Mode'], '0')
        self.assertEqual(set(checked['values']), set(self.schema['inputs']))
        self.assertNotIn('Ledger_Mode', checked['axes'])

    def test_a_set_may_choose_position_join_but_nothing_undeclared(self):
        self.assertEqual(validate_strategy(dict(self.old, Ledger_Mode='1'), self.schema)['values']['Ledger_Mode'], '1')
        with self.assertRaisesRegex(ValueError, 'Ledger_Mode: Undeclared enum value'):
            validate_strategy(dict(self.old, Ledger_Mode='2'), self.schema)
        with self.assertRaisesRegex(ValueError, 'Ledger_Mode: Input not exposed for optimization'):
            validate_strategy(dict(self.old, Ledger_Mode='0||0||1||1||Y'), self.schema)

    def test_every_other_input_stays_required_and_unknown_inputs_stay_refused(self):
        missing = {k: v for k, v in self.old.items() if k != 'Mode_News'}
        with self.assertRaisesRegex(ValueError, r"missing=\['Mode_News'\], unknown=\[\]"):
            validate_strategy(missing, self.schema)
        with self.assertRaisesRegex(ValueError, r"missing=\[\], unknown=\['Ledger_Mod'\]"):
            validate_strategy(dict(self.old, Ledger_Mod='1'), self.schema)

    def test_completion_copies_and_never_overrides_a_choice(self):
        self.assertIsNot(complete_appended_inputs(self.old, self.schema), self.old)
        self.assertNotIn('Ledger_Mode', self.old)
        self.assertEqual(complete_appended_inputs(dict(self.old, Ledger_Mode='1'), self.schema)['Ledger_Mode'], '1')
        # A schema without the input (the V1.48 contract) adds nothing.
        v148 = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k != 'Ledger_Mode'})
        self.assertEqual(complete_appended_inputs(self.old, v148), self.old)

    def test_the_paste_sets_the_default_instead_of_inheriting_the_last_run(self):
        pasted = explicit_paste_inputs(dict(self.old), self.schema)
        self.assertEqual(pasted['Ledger_Mode'], '0||0||0||0||N')

    def test_the_readback_wants_the_default_and_catches_a_position_join_run(self):
        observed = dict(self.full, Ledger_Mode='0')
        self.assertEqual(verify_input_readback(dict(self.old), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Ledger_Mode'):
            verify_input_readback(dict(self.old), dict(self.full, Ledger_Mode='1'), self.schema)


if __name__ == '__main__':
    unittest.main()
