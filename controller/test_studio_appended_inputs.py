"""B49a (F2, GOAT-EA#265): an input appended to the v149 header after B47 (Ledger_Mode) is optional in a SET.

A SET, template or export written before the input existed omits it; it then takes its declared default
(Ledger_Legacy = 0), which reproduces B47. Everywhere a SET reaches MT5 or is compared with MT5, the omitted input is
the default: validation, the scalar paste (never inherited from the terminal's previous run), the input readback
(a tester that ran PositionJoin for a SET that never asked for it is caught), and export verification.
"""
import json
from pathlib import Path
import unittest

from studio_strategy_settings import (APPENDED_INPUTS, B50_INPUTS, B51_INPUTS, appended_default, complete_appended_inputs,
                                      read_values, validate_strategy)
from studio_input_readback import explicit_paste_inputs, verify_input_readback
import studio_tester_report as tester_report
from campaign_ledger import sha
from studio_native_request import ini_sections
import test_goat_studio as goat_studio_tests   # its PortableControllerTests fixture (a module attribute, so not collected here)
from test_studio_pinned_tester_inputs import compass_like_template

ROOT = Path(__file__).resolve().parent


class AppendedInputTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        raw = ('\r\n'.join(compass_like_template(self.schema).splitlines())+'\r\n').encode('utf-16')
        self.full = read_values(raw)
        self.old = {k: v for k, v in self.full.items() if k not in APPENDED_INPUTS}   # a B47-era SET

    def test_the_appended_inputs_are_ledger_mode_last_in_the_header_defaulting_to_legacy(self):
        self.assertEqual(APPENDED_INPUTS[0], 'Ledger_Mode')
        # B50 (A0): the appended inputs are the header's last ones, in order, after B47's 114.
        self.assertEqual(list(self.schema['inputs'])[-len(APPENDED_INPUTS):], list(APPENDED_INPUTS))
        self.assertEqual(len(self.schema['inputs']), 114 + len(APPENDED_INPUTS))
        definition = self.schema['inputs']['Ledger_Mode']
        self.assertEqual((definition['type'], definition['declaration'], definition['default_expression']),
                         ('ENUM_LEDGER_MODE', 'sinput', 'Ledger_Legacy'))
        self.assertEqual(definition['enum_choices'], {'Ledger_Legacy': 0, 'Ledger_PositionJoin': 1})
        self.assertEqual(appended_default(definition), '0')
        # The same default the tester report pins for any omitted input (GOAT-EA#250).
        self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), '0')

    def test_the_b50_inputs_follow_ledger_mode_and_default_to_b49a(self):
        # B50 (A0, docs/b50/B50_ALPHA_DESIGN.md section 2): twelve inputs after Ledger_Mode; every default reproduces
        # B49a, and each is the default the tester report pins for an omitted input.
        expected = {'Engine_Mode': ('ENUM_ENGINE_MODE', 'sinput', '0'), 'Single_SL_ATR': ('double', 'input', '0.0'),
                    'Single_TP_ATR': ('double', 'input', '0.0'), 'Single_TP_R': ('double', 'input', '0.0'),
                    'Single_Exit_Opposite': ('bool', 'input', 'false'), 'Single_Time_Stop_Bars': ('int', 'input', '0'),
                    'Single_Time_Stop_TF': ('ENUM_MODE_TFs', 'input', '0'), 'Clock_Mode': ('ENUM_CLOCK_MODE', 'sinput', '0'),
                    'Server_Clock_Model': ('ENUM_SERVER_CLOCK_MODEL', 'sinput', '0'),
                    'Server_UTC_Offset': ('int', 'sinput', '2'), 'NY_Session': ('string', 'input', '09:30-16:00'),
                    'Rollover_Block_Minutes': ('int', 'input', '0')}
        self.assertEqual(B50_INPUTS, tuple(expected))
        self.assertEqual(APPENDED_INPUTS[1:1+len(B50_INPUTS)], B50_INPUTS)
        for name, (kind, declaration, default) in expected.items():
            definition = self.schema['inputs'][name]
            self.assertEqual((definition['type'], definition['declaration'], appended_default(definition)),
                             (kind, declaration, default), name)
            self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), default, name)
        self.assertEqual(self.schema['inputs']['Engine_Mode']['enum_choices'], {'Engine_Grid': 0, 'Engine_Single': 1})
        self.assertEqual(self.schema['inputs']['Clock_Mode']['enum_choices'], {'Clock_Server': 0, 'Clock_NewYork': 1})
        self.assertEqual(self.schema['inputs']['Server_Clock_Model']['enum_choices'],
                         {'ServerClock_NYClose': 0, 'ServerClock_Fixed': 1, 'ServerClock_EUDST': 2})
        self.assertEqual(self.schema['inputs']['Single_Time_Stop_TF']['enum_choices']['TF_D1'], 1440)
        # The optimization axes: the input (not sinput), non-string ones.
        self.assertEqual({name for name in expected if self.schema['inputs'][name]['optimizable']},
                         {'Single_SL_ATR', 'Single_TP_ATR', 'Single_TP_R', 'Single_Exit_Opposite', 'Single_Time_Stop_Bars',
                          'Single_Time_Stop_TF', 'Rollover_Block_Minutes'})

    def test_the_b51_inputs_come_last_and_default_to_b50_alpha(self):
        # B51 (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8): appended at the very end of the header; every default
        # reproduces B50-alpha, and each is the default the tester report pins for an omitted input.
        expected = {'Random_Direction': ('bool', 'sinput', 'false'), 'Random_Seed': ('int', 'input', '1'),
                    'Single_Flat_Only': ('bool', 'sinput', 'false'),
                    'Single_BE_ATR': ('double', 'input', '0.0'), 'Single_Trail_Start_ATR': ('double', 'input', '0.0'),
                    'Single_Trail_ATR': ('double', 'input', '0.0')}
        self.assertEqual(B51_INPUTS, tuple(expected))
        self.assertEqual(APPENDED_INPUTS[-len(B51_INPUTS):], B51_INPUTS)
        self.assertEqual(list(self.schema['inputs'])[-len(B51_INPUTS):], list(B51_INPUTS))
        for name, (kind, declaration, default) in expected.items():
            definition = self.schema['inputs'][name]
            self.assertEqual((definition['type'], definition['declaration'], appended_default(definition)),
                             (kind, declaration, default), name)
            self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), default, name)
        # Random_Seed is an axis (a seed sweep); Random_Direction is an sinput, never one.
        self.assertEqual({name for name in expected if self.schema['inputs'][name]['optimizable']},
                         {'Random_Seed', 'Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR'})
        # A B50-alpha SET (neither input) validates and keeps its own values; a benchmark SET validates too.
        alpha = {k: v for k, v in self.full.items() if k not in B51_INPUTS}
        self.assertEqual(validate_strategy(dict(alpha), self.schema)['values'], alpha)
        bench = dict(self.old, Engine_Mode='1', Single_SL_ATR='1.5', Mode_Bias_Exit='0', Random_Direction='true',
                     Single_Flat_Only='true', Random_Seed='1||1||1||50||Y')
        with self.assertRaisesRegex(ValueError, 'RANDOM_DIRECTION_WITHOUT_FLAT_ONLY'):
            validate_strategy(dict(bench, Single_Flat_Only='false'), self.schema)
        self.assertEqual(validate_strategy(bench, self.schema)['values'], bench)
        with self.assertRaisesRegex(ValueError, 'RANDOM_DIRECTION_WITHOUT_SINGLE'):
            validate_strategy(dict(bench, Engine_Mode='0'), self.schema)
        with self.assertRaisesRegex(ValueError, 'RANDOM_SEED_NEGATIVE'):
            validate_strategy(dict(bench, Random_Seed='5||-5||1||10||Y'), self.schema)
        with self.assertRaisesRegex(ValueError, 'Random_Direction: Input not exposed for optimization'):
            validate_strategy(dict(bench, Random_Direction='false||false||1||true||Y'), self.schema)
        # The readback wants the defaults for a SET that omits them.
        observed = complete_appended_inputs(dict(self.full), self.schema)
        self.assertEqual((observed['Random_Direction'], observed['Random_Seed']), ('false', '1'))
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Random_Direction'):
            verify_input_readback(dict(self.old), dict(observed, Random_Direction='true'), self.schema)

    def test_a_b49a_set_may_choose_the_single_engine_and_its_axes(self):
        # The fixture runs Smart Rescue, which the single engine refuses (Claude-Mac ruling 4): hard close instead.
        single = dict(self.old, Engine_Mode='1', Single_SL_ATR='1.5||1.0||0.5||3.0||Y', Single_TP_R='2.0', Mode_Bias_Exit='0')
        with self.assertRaisesRegex(ValueError, 'SINGLE_WITH_SMART_RESCUE'):
            validate_strategy(dict(single, Mode_Bias_Exit='1'), self.schema)
        self.assertEqual(validate_strategy(single, self.schema)['values'], single)
        with self.assertRaisesRegex(ValueError, 'Engine_Mode: Input not exposed for optimization'):
            validate_strategy(dict(single, Engine_Mode='0||0||1||1||Y'), self.schema)
        with self.assertRaisesRegex(ValueError, 'Clock_Mode: Undeclared enum value'):
            validate_strategy(dict(self.old, Clock_Mode='2'), self.schema)

    def test_a_set_without_it_validates_and_keeps_its_own_values(self):
        # Claude-Mac GOAT-EA#265 P1: the checks see the default, the caller gets its own values back, so a stored job,
        # its registry SET bytes and every SET hash stay exactly as they were.
        checked = validate_strategy(dict(self.old), self.schema)
        self.assertEqual(checked['values'], self.old)
        self.assertNotIn('Ledger_Mode', checked['values'])
        self.assertNotIn('Ledger_Mode', checked['axes'])
        # The checks did see the default: a SET naming every input validates to the same axes.
        self.assertEqual(validate_strategy(dict(self.full), self.schema)['axes'], checked['axes'])

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
        v148 = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k not in APPENDED_INPUTS})
        self.assertEqual(complete_appended_inputs(self.old, v148), self.old)

    def test_the_paste_sets_the_default_instead_of_inheriting_the_last_run(self):
        pasted = explicit_paste_inputs(dict(self.old), self.schema)
        self.assertEqual(pasted['Ledger_Mode'], '0||0||0||0||N')

    def test_the_readback_wants_the_default_and_catches_a_position_join_run(self):
        observed = complete_appended_inputs(dict(self.full), self.schema)   # MT5 reports every input (B50's at their defaults)
        self.assertEqual(observed['Ledger_Mode'], '0')
        self.assertEqual(verify_input_readback(dict(self.old), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Engine_Mode'):
            verify_input_readback(dict(self.old), dict(observed, Engine_Mode='1'), self.schema)   # B50: a Single run for a B49a SET
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Ledger_Mode'):
            verify_input_readback(dict(self.old), dict(observed, Ledger_Mode='1'), self.schema)


class AppendedInputPrepareTests(unittest.TestCase):
    """Claude-Mac GOAT-EA#265 P1, reproduced with test_goat_studio's fixture: a SET without Ledger_Mode goes through
    prepare (which stages it against the registry bytes), is reused, and its readback wants the default."""

    def setUp(self):
        self.fixture = goat_studio_tests.PortableControllerTests('test_prepare_exact_inputs_server_version_ninth_setting')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)

    def bound(self):
        c = self.fixture.bound()
        real = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))['inputs']['Ledger_Mode']
        c.schema['inputs']['Ledger_Mode'] = real
        c.store.input_schema = c.schema; c.store.input_schema_hash = sha(c.schema)
        return c

    def test_a_set_without_it_is_prepared_staged_reused_and_read_back(self):
        c = self.bound(); self.fixture.grant(c)
        first = self.fixture.prepare(c)                              # prepare stages it (studio_native_stage) against the registry
        self.assertEqual(self.fixture.prepare(c)['reused'], True)    # job reuse compares the stored values with the SET's own
        stored = c.state()['queue'][0]['configuration']['strategy']['values']
        self.assertEqual(stored, {'EA_Desc': 'Customer Template', 'Lots': '0.1||0.1||0.1||0.3||Y'}, 'the SET\'s own values, unchanged')
        ini = ini_sections((Path(first['package'])/(first['manifest']['jobs'][0]['run_alias']+'.ini')).read_bytes())
        self.assertNotIn('Ledger_Mode', ini['TesterInputs'], 'the SET bytes are not rewritten: the profile run takes the build default')
        observed = dict(stored, Ledger_Mode='0')
        self.assertEqual(verify_input_readback(dict(stored), observed, c.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Ledger_Mode'):
            verify_input_readback(dict(stored), dict(stored, Ledger_Mode='1'), c.schema)



if __name__ == '__main__':
    unittest.main()
