"""B49a (F2, GOAT-EA#265): an input appended to the v149 header after B47 (Ledger_Mode) is optional in a SET.

A SET, template or export written before the input existed omits it; it then takes its declared default
(Ledger_Legacy = 0), which reproduces B47. Everywhere a SET reaches MT5 or is compared with MT5, the omitted input is
the default: validation, the scalar paste (never inherited from the terminal's previous run), the input readback
(a tester that ran PositionJoin for a SET that never asked for it is caught), and export verification.
"""
import json
from pathlib import Path
import unittest

from studio_strategy_settings import (APPENDED_INPUTS, B49B_INPUTS, B50_INPUTS, B51_INPUTS, B54_INPUTS, B55_INPUTS, appended_default,
                                      complete_appended_inputs, read_values, validate_strategy)
from studio_input_readback import explicit_paste_inputs, verify_input_readback
from studio_export_inputs import verify_export_inputs
import studio_tester_report as tester_report
from campaign_ledger import sha
from studio_native_request import ini_sections
import test_goat_studio as goat_studio_tests   # its PortableControllerTests fixture (a module attribute, so not collected here)
from test_studio_pinned_tester_inputs import compass_like_template

ROOT = Path(__file__).resolve().parent
# B49b's own appended line: B49a's Ledger_Mode and B49b's nine fix inputs, sinputs that each default to 0. B50's and
# B51's have their own tests below, with their own declarations and defaults.
B49B_LINE = ('Ledger_Mode',) + B49B_INPUTS


class AppendedInputTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        raw = ('\r\n'.join(compass_like_template(self.schema).splitlines())+'\r\n').encode('utf-16')
        self.full = read_values(raw)
        self.old = {k: v for k, v in self.full.items() if k not in APPENDED_INPUTS}   # a B47-era SET

    def test_the_appended_inputs_are_ledger_mode_last_in_the_header_defaulting_to_legacy(self):
        self.assertEqual(APPENDED_INPUTS[0], 'Ledger_Mode')
        # B50 (A0): the appended inputs are the header's last ones, in order, after B47's 114.
        self.assertEqual(list(self.schema['inputs'])[-len(APPENDED_INPUTS):], list(APPENDED_INPUTS), 'appended last, in order')
        self.assertEqual(len(self.schema['inputs']), 114 + len(APPENDED_INPUTS))
        # B49b: its nine follow B50-alpha's and come before B51's (B49b's header: Claude-Mac 6433854745 ruling 6).
        self.assertEqual(B49B_INPUTS, ('Fix_MoneyVolume', 'Gate_Recheck', 'Fix_ClosePath', 'Max_Spread_Points', 'Min_Margin_Level_PC', 'Fix_Clock', 'Fix_FeedGuard', 'Diag_TickTiming', 'Fix_TickLoad'))
        self.assertEqual(APPENDED_INPUTS, ('Ledger_Mode',) + B50_INPUTS + B49B_INPUTS + B51_INPUTS + B54_INPUTS + B55_INPUTS)   # B55 (A0): last
        definition = self.schema['inputs']['Ledger_Mode']
        self.assertEqual((definition['type'], definition['declaration'], definition['default_expression']),
                         ('ENUM_LEDGER_MODE', 'sinput', 'Ledger_Legacy'))
        self.assertEqual(definition['enum_choices'], {'Ledger_Legacy': 0, 'Ledger_PositionJoin': 1})
        # B49b (F7): a per-fix flag, Off = B49a.
        fix = self.schema['inputs']['Fix_MoneyVolume']
        self.assertEqual((fix['type'], fix['declaration'], fix['default_expression']), ('ENUM_GOAT_FIX', 'sinput', 'GoatFix_Off'))
        self.assertEqual(fix['enum_choices'], {'GoatFix_Off': 0, 'GoatFix_On': 1})
        # B49b (F5): Gate_Recheck, Legacy = B49a.
        gate = self.schema['inputs']['Gate_Recheck']
        self.assertEqual((gate['type'], gate['declaration'], gate['default_expression']), ('ENUM_GATE_RECHECK', 'sinput', 'Gate_Legacy'))
        self.assertEqual(gate['enum_choices'], {'Gate_Legacy': 0, 'Gate_AtFirstOrder': 1})
        # B49b (F3): Fix_ClosePath, the shared fix type.
        close = self.schema['inputs']['Fix_ClosePath']
        self.assertEqual((close['type'], close['declaration'], close['default_expression']), ('ENUM_GOAT_FIX', 'sinput', 'GoatFix_Off'))
        for name in B49B_LINE:
            self.assertEqual(appended_default(self.schema['inputs'][name]), '0', name)
            # The same default the tester report pins for any omitted input (GOAT-EA#250).
            self.assertEqual(tester_report._schema_default(self.schema['inputs'][name], self.schema.get('defines')), '0', name)

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

    def test_the_b51_inputs_come_before_b54s_and_default_to_b50_alpha(self):
        # B51 (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8): appended at the end of the header, where B54's now follow
        # them; every default reproduces B50-alpha, and each is the default the tester report pins for an omitted input.
        expected = {'Random_Direction': ('bool', 'sinput', 'false'), 'Random_Seed': ('int', 'input', '1'),
                    'Single_Flat_Only': ('bool', 'sinput', 'false'),
                    'Single_BE_ATR': ('double', 'input', '0.0'), 'Single_Trail_Start_ATR': ('double', 'input', '0.0'),
                    'Single_Trail_ATR': ('double', 'input', '0.0'),
                    'Single_Partial_ATR': ('double', 'input', '0.0'), 'Single_Partial_Fraction': ('double', 'input', '0.0'),
                    'Single_Partial_BE': ('bool', 'input', 'false')}
        self.assertEqual(B51_INPUTS, tuple(expected))
        before_b54 = -len(B54_INPUTS + B55_INPUTS)   # B55 (A0): its input follows B54's
        self.assertEqual(APPENDED_INPUTS[before_b54-len(B51_INPUTS):before_b54], B51_INPUTS)
        self.assertEqual(list(self.schema['inputs'])[before_b54-len(B51_INPUTS):before_b54], list(B51_INPUTS))
        for name, (kind, declaration, default) in expected.items():
            definition = self.schema['inputs'][name]
            self.assertEqual((definition['type'], definition['declaration'], appended_default(definition)),
                             (kind, declaration, default), name)
            self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), default, name)
        # Random_Seed is an axis (a seed sweep); Random_Direction is an sinput, never one.
        self.assertEqual({name for name in expected if self.schema['inputs'][name]['optimizable']},
                         {'Random_Seed', 'Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR',
                          'Single_Partial_ATR', 'Single_Partial_Fraction', 'Single_Partial_BE'})
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

    def test_the_b54_inputs_come_before_b55s_and_default_to_b53(self):
        # B54 (PR A0, docs/b54/BREAKOUT_ENTRIES_SPEC.md sections 3.1, 4.1 and 7): the breakout inputs, appended at the end of the
        # header after B51's, where B55's now follows them; both modes default to Disabled, every default reproduces B53, and
        # each is the default the tester report pins for an omitted input (gate 0: scripts/test_b54_gate0.cjs, test_b54_gate0.py).
        expected = {'BRK_Mode': ('ENUM_MODE_BRK', 'sinput', '0'), 'BRK_TF_': ('ENUM_MODE_TFs', 'input', '60'),
                    'BRK_Bars': ('int', 'input', '20'), 'BRK_Buffer_ATR': ('double', 'input', '0.0'),
                    'BRK_Once_Per_Level': ('bool', 'input', 'true'), 'ORB_Mode': ('ENUM_MODE_ORB', 'sinput', '0'),
                    'ORB_Clock': ('ENUM_ORB_CLOCK', 'sinput', '0'), 'ORB_TF_': ('ENUM_MODE_TFs', 'input', '5'),
                    'ORB_Start_Minute': ('int', 'input', '570'), 'ORB_Range_Minutes': ('int', 'input', '30'),
                    'ORB_Entry_Minutes': ('int', 'input', '0'), 'ORB_Buffer_ATR': ('double', 'input', '0.0'),
                    'ORB_Min_Range_ATR': ('double', 'input', '0.0'), 'ORB_Max_Range_ATR': ('double', 'input', '0.0')}
        self.assertEqual(B54_INPUTS, tuple(expected))
        before_b55 = -len(B55_INPUTS)
        self.assertEqual(APPENDED_INPUTS[before_b55-len(B54_INPUTS):before_b55], B54_INPUTS)
        self.assertEqual(list(self.schema['inputs'])[before_b55-len(B54_INPUTS):before_b55], list(B54_INPUTS))
        for name, (kind, declaration, default) in expected.items():
            definition = self.schema['inputs'][name]
            self.assertEqual((definition['type'], definition['declaration'], appended_default(definition)),
                             (kind, declaration, default), name)
            self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), default, name)
        self.assertEqual(self.schema['inputs']['BRK_Mode']['enum_choices'], {'BRK_Disabled': 0, 'BRK_NBar': 1, 'BRK_PriorDay': 2})
        self.assertEqual(self.schema['inputs']['ORB_Mode']['enum_choices'], {'ORB_Disabled': 0, 'ORB_Breakout': 1})
        self.assertEqual(self.schema['inputs']['ORB_Clock']['enum_choices'], {'ORB_Clock_NewYork': 0, 'ORB_Clock_London': 1})
        for name in ('BRK_TF_', 'ORB_TF_'):
            self.assertEqual(self.schema['inputs'][name]['enum_choices'], self.schema['inputs']['ATR_TF_']['enum_choices'], name)
        # The axes: every input that is not an sinput (the three modes) and not a string (spec section 7).
        self.assertEqual({name for name in expected if self.schema['inputs'][name]['optimizable']},
                         set(expected) - {'BRK_Mode', 'ORB_Mode', 'ORB_Clock'})
        # A B53 SET (none of them) validates and keeps its own values; a mode is never an axis; an undeclared mode is refused.
        b53 = {k: v for k, v in self.full.items() if k not in B54_INPUTS + B55_INPUTS}
        self.assertEqual(validate_strategy(dict(b53), self.schema)['values'], b53)
        with self.assertRaisesRegex(ValueError, 'BRK_Mode: Input not exposed for optimization'):
            validate_strategy(dict(self.old, BRK_Mode='0||0||1||2||Y'), self.schema)
        with self.assertRaisesRegex(ValueError, 'ORB_Clock: Undeclared enum value'):
            validate_strategy(dict(self.old, ORB_Clock='2'), self.schema)
        # The readback wants the defaults for a SET that omits them, and catches a run the SET never asked for.
        observed = complete_appended_inputs(dict(self.full), self.schema)
        self.assertEqual({name: observed[name] for name in B54_INPUTS}, {name: d for name, (_, _, d) in expected.items()})
        self.assertEqual(verify_input_readback(dict(self.old), complete_appended_inputs(dict(self.old), self.schema),
                                               self.schema)['status'], 'INPUT_READBACK_MATCH')
        for name, value in (('BRK_Mode', '1'), ('ORB_Mode', '1'), ('BRK_Bars', '55')):
            with self.assertRaisesRegex(ValueError, 'Fixed input value changed: ' + name):
                verify_input_readback(dict(self.old), dict(complete_appended_inputs(dict(self.old), self.schema), **{name: value}),
                                      self.schema)

    def test_the_b55_input_comes_last_and_defaults_to_b54(self):
        # B55 (PR A0, docs/b55/BREAKOUT_SEQUENCE_SPEC.md sections 3.1 and 7): the sequence switch, appended at the very end of
        # the header after B54's, in its own group; its default (false) reproduces B54, and it is the default the tester
        # report pins for an omitted input. An sinput, so never an axis (gate 0: scripts/test_b55_gate0.cjs, test_b55_gate0.py).
        expected = {'BRK_Start_Seq': ('bool', 'sinput', 'false')}
        self.assertEqual(B55_INPUTS, tuple(expected))
        self.assertEqual(APPENDED_INPUTS[-len(B55_INPUTS):], B55_INPUTS)
        self.assertEqual(list(self.schema['inputs'])[-len(B55_INPUTS):], list(B55_INPUTS))
        for name, (kind, declaration, default) in expected.items():
            definition = self.schema['inputs'][name]
            self.assertEqual((definition['type'], definition['declaration'], appended_default(definition)),
                             (kind, declaration, default), name)
            self.assertEqual(tester_report._schema_default(definition, self.schema.get('defines')), default, name)
            self.assertFalse(definition['optimizable'], name)
        # A B54 SET (without it) validates and keeps its own values; the switch is never an axis.
        b54 = {k: v for k, v in self.full.items() if k not in B55_INPUTS}
        self.assertEqual(validate_strategy(dict(b54), self.schema)['values'], b54)
        with self.assertRaisesRegex(ValueError, 'BRK_Start_Seq: Input not exposed for optimization'):
            validate_strategy(dict(self.old, BRK_Start_Seq='false||false||0||true||Y'), self.schema)
        # The readback wants the default for a SET that omits it, and catches a run the SET never asked for.
        observed = complete_appended_inputs(dict(self.full), self.schema)
        self.assertEqual({name: observed[name] for name in B55_INPUTS}, {name: d for name, (_, _, d) in expected.items()})
        self.assertEqual(verify_input_readback(dict(self.old), complete_appended_inputs(dict(self.old), self.schema),
                                               self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: BRK_Start_Seq'):
            verify_input_readback(dict(self.old), dict(complete_appended_inputs(dict(self.old), self.schema), BRK_Start_Seq='true'),
                                  self.schema)

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
        for name in B49B_LINE:
            self.assertEqual(validate_strategy(dict(self.old, **{name: '1'}), self.schema)['values'][name], '1')
            if self.schema['inputs'][name].get('enum_choices'):   # B49b (F6): the pre-trade caps are plain numbers
                with self.assertRaisesRegex(ValueError, name+': Undeclared enum value'):
                    validate_strategy(dict(self.old, **{name: '2'}), self.schema)
            with self.assertRaisesRegex(ValueError, name+': Input not exposed for optimization'):
                validate_strategy(dict(self.old, **{name: '0||0||1||1||Y'}), self.schema)

    def test_the_pre_trade_caps_only_tighten(self):
        # B49b (F6, Claude-Mac GOAT-EA#281 6445315361): Max_Spread_Points 0..9999 (B49a's fixed MaxSP), both caps >= 0.
        for name, value in (('Max_Spread_Points', '0'), ('Max_Spread_Points', '30'), ('Max_Spread_Points', '9999'),
                            ('Min_Margin_Level_PC', '0'), ('Min_Margin_Level_PC', '150.0'), ('Min_Margin_Level_PC', '100000'),
                            ('Max_Spread_Points', '30||10000||1||10000||N')):            # a dormant tuple runs its first field
            with self.subTest(name=name, value=value):
                self.assertEqual(validate_strategy(dict(self.old, **{name: value}), self.schema)['values'][name], value)
        for name, value in (('Max_Spread_Points', '10000'), ('Max_Spread_Points', '50000'), ('Max_Spread_Points', '-1'),
                            ('Min_Margin_Level_PC', '-0.5'), ('Min_Margin_Level_PC', '-100'),
                            ('Max_Spread_Points', '50000||0||1||10||N')):
            with self.subTest(name=name, value=value):
                with self.assertRaisesRegex(ValueError, '^PRETRADE_CAP_OUT_OF_RANGE: .*' + name + '=' + value.replace('|', r'\|')):
                    validate_strategy(dict(self.old, **{name: value}), self.schema)
        # An omitted cap is its default, 0 (off), and passes.
        validate_strategy(dict(self.old), self.schema)

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
        self.assertEqual(complete_appended_inputs(dict(self.old, Fix_MoneyVolume='1'), self.schema)['Fix_MoneyVolume'], '1')
        # A schema without the inputs (the V1.48 contract) adds nothing; B49a's (no B50 input, fix flag, B51, B54 or B55 input)
        # adds only Ledger_Mode.
        v148 = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k not in APPENDED_INPUTS})
        self.assertEqual(complete_appended_inputs(self.old, v148), self.old)
        b49a = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k not in B50_INPUTS + B49B_INPUTS + B51_INPUTS + B54_INPUTS + B55_INPUTS})
        self.assertEqual(complete_appended_inputs(self.old, b49a), dict(self.old, Ledger_Mode='0'))

    def test_the_paste_sets_the_default_instead_of_inheriting_the_last_run(self):
        pasted = explicit_paste_inputs(dict(self.old), self.schema)
        for name in B49B_LINE:
            self.assertEqual(pasted[name], '0||0||0||0||N', name)

    def test_the_readback_wants_the_default_and_catches_a_position_join_run(self):
        observed = complete_appended_inputs(dict(self.full), self.schema)   # MT5 reports every input (B50's at their defaults)
        self.assertEqual({name: observed[name] for name in B49B_LINE}, {name: '0' for name in B49B_LINE})
        self.assertEqual(verify_input_readback(dict(self.old), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Engine_Mode'):
            verify_input_readback(dict(self.old), dict(observed, Engine_Mode='1'), self.schema)   # B50: a Single run for a B49a SET
        for name in B49B_LINE:
            with self.assertRaisesRegex(ValueError, 'Fixed input value changed: '+name):
                verify_input_readback(dict(self.old), dict(observed, **{name: '1'}), self.schema)


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


class LedgerModeRoundTripTests(unittest.TestCase):
    """Claude-Mac GOAT-EA#267 P2 (B49b PR-0): a PositionJoin research run's export survives the whole round trip:
    the EA's WriteSet line, the controller's export check (studio_export_scan's verify_export_inputs), a reload of the
    exported SET, its paste into the next run and that run's input readback, all as PositionJoin. A writer that drops
    the line (B47's, or the ungated B49a mutant's opposite) is caught by the export check instead of silently becoming
    Legacy, and a Legacy run's export stays B47's bytes."""

    ALIAS = 'GOAT EURUSD roundtrip'
    STANDARD_MODE = 9   # what studio_export_scan passes

    def setUp(self):
        self.schema = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        self.template = compass_like_template(self.schema)
        source = read_values(('\r\n'.join(self.template.splitlines())+'\r\n').encode('utf-16'))
        self.legacy_source = {k: v for k, v in source.items() if k not in APPENDED_INPUTS}
        self.axes = sorted(validate_strategy(dict(self.legacy_source), self.schema)['axes'])
        self.assertTrue(self.axes)
        # The writer: B49a's WriteSet records a non-Legacy ledger with this exact line, after Trade_December.
        writer = (ROOT.parent/'GOAT_Inputs_Definitions.mqh').read_text(encoding='utf-8-sig')
        self.assertIn('if(Ledger_Mode!=Ledger_Legacy) FileWrite(FileSET_handle,"Ledger_Mode="+(string)(int)Ledger_Mode);', writer)
        # B49b (F7): each fix flag is written the same way, only when on.
        self.assertIn('if(Fix_MoneyVolume!=GoatFix_Off) FileWrite(FileSET_handle,"Fix_MoneyVolume="+(string)(int)Fix_MoneyVolume);', writer)

    @staticmethod
    def raw(values):
        return ('\r\n'.join(n+'='+v for n, v in values.items())+'\r\n').encode('utf-16')   # FILE_CSV, no FILE_ANSI: UTF-16

    def export_of(self, source, *, ledger_line, fix_line=False):
        """What WriteSet writes for one optimization pass of `source`: every input at the pass's value (an axis at its
        first value), the alias and the standard mode, the ledger line when the run was PositionJoin, and the fix
        line when Fix_MoneyVolume was on."""
        exported = {}
        for name, value in source.items():
            if name in APPENDED_INPUTS:
                continue
            exported[name] = value if self.schema['inputs'][name]['type'] == 'string' else value.split('||')[0]
        exported.update(EA_Desc=self.ALIAS, Mode_Operation=str(self.STANDARD_MODE))
        if ledger_line:
            exported['Ledger_Mode'] = str(self.schema['inputs']['Ledger_Mode']['enum_choices']['Ledger_PositionJoin'])
        if fix_line:
            exported['Fix_MoneyVolume'] = str(self.schema['inputs']['Fix_MoneyVolume']['enum_choices']['GoatFix_On'])
        return exported

    def check(self, source, exported):
        row = {name: exported[name] for name in self.axes}
        return verify_export_inputs(self.raw(source), self.raw(exported), self.schema, {'7': row}, {'7': dict(row)},
                                    alias=self.ALIAS, standard_mode=self.STANDARD_MODE)

    def test_a_position_join_export_passes_the_check_and_reloads_as_position_join(self):
        source = dict(self.legacy_source, Ledger_Mode='1')
        exported = self.export_of(source, ledger_line=True)
        self.assertEqual(exported['Ledger_Mode'], '1')
        identity = self.check(source, exported)
        self.assertEqual(identity['status'], 'SET_INPUTS_MATCH_PAIRED_PASSES')
        self.assertEqual(identity['matching_pass_ids'], ['7'])
        # The reload: the exported SET is the next run's source.
        reloaded = read_values(self.raw(exported))
        self.assertEqual(validate_strategy(dict(reloaded), self.schema)['values']['Ledger_Mode'], '1')
        self.assertEqual(explicit_paste_inputs(dict(reloaded), self.schema)['Ledger_Mode'], '1||0||0||0||N')
        observed = complete_appended_inputs(dict(reloaded, Ledger_Mode='1', Fix_MoneyVolume='0', Gate_Recheck='0', Fix_ClosePath='0', Max_Spread_Points='0', Min_Margin_Level_PC='0', Fix_Clock='0', Fix_FeedGuard='0', Diag_TickTiming='0', Fix_TickLoad='0'), self.schema)   # MT5 reports every input (B50's and B51's at their defaults)
        self.assertEqual(verify_input_readback(dict(reloaded), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Ledger_Mode'):
            verify_input_readback(dict(reloaded), dict(observed, Ledger_Mode='0'), self.schema)

    def test_a_fix_on_export_round_trips_as_fix_on_and_a_lost_line_is_refused(self):
        # B49b (F7): Fix_MoneyVolume follows Ledger_Mode's rule through the same check, reload, paste and readback.
        source = dict(self.legacy_source, Fix_MoneyVolume='1')
        exported = self.export_of(source, ledger_line=False, fix_line=True)
        self.assertEqual(self.check(source, exported)['status'], 'SET_INPUTS_MATCH_PAIRED_PASSES')
        reloaded = read_values(self.raw(exported))
        self.assertEqual(validate_strategy(dict(reloaded), self.schema)['values']['Fix_MoneyVolume'], '1')
        self.assertEqual(explicit_paste_inputs(dict(reloaded), self.schema)['Fix_MoneyVolume'], '1||0||0||0||N')
        observed = complete_appended_inputs(dict(reloaded, Ledger_Mode='0', Fix_MoneyVolume='1', Gate_Recheck='0', Fix_ClosePath='0', Max_Spread_Points='0', Min_Margin_Level_PC='0', Fix_Clock='0', Fix_FeedGuard='0', Diag_TickTiming='0', Fix_TickLoad='0'), self.schema)
        self.assertEqual(verify_input_readback(dict(reloaded), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        with self.assertRaisesRegex(ValueError, 'Fixed input value changed: Fix_MoneyVolume'):
            verify_input_readback(dict(reloaded), dict(observed, Fix_MoneyVolume='0'), self.schema)
        with self.assertRaisesRegex(ValueError, 'Fixed export input mismatch: Fix_MoneyVolume'):
            self.check(source, self.export_of(source, ledger_line=False, fix_line=False))
        with self.assertRaisesRegex(ValueError, 'Fixed export input mismatch: Fix_MoneyVolume'):
            self.check(self.legacy_source, self.export_of(self.legacy_source, ledger_line=False, fix_line=True))

    def test_an_export_that_lost_the_line_is_refused_not_read_as_legacy(self):
        source = dict(self.legacy_source, Ledger_Mode='1')
        with self.assertRaisesRegex(ValueError, 'Fixed export input mismatch: Ledger_Mode'):
            self.check(source, self.export_of(source, ledger_line=False))

    def test_a_legacy_run_round_trips_without_the_line(self):
        exported = self.export_of(self.legacy_source, ledger_line=False)
        self.assertNotIn('Ledger_Mode', exported)
        self.assertEqual(self.check(self.legacy_source, exported)['status'], 'SET_INPUTS_MATCH_PAIRED_PASSES')
        reloaded = read_values(self.raw(exported))
        self.assertNotIn('Ledger_Mode', validate_strategy(dict(reloaded), self.schema)['values'])
        self.assertEqual(explicit_paste_inputs(dict(reloaded), self.schema)['Ledger_Mode'], '0||0||0||0||N')
        # A Legacy source whose export claims PositionJoin is refused too (the writer's gate, from the other side).
        with self.assertRaisesRegex(ValueError, 'Fixed export input mismatch: Ledger_Mode'):
            self.check(self.legacy_source, self.export_of(self.legacy_source, ledger_line=True))


if __name__ == '__main__':
    unittest.main()
