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
from studio_export_inputs import verify_export_inputs
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
        self.assertEqual(APPENDED_INPUTS, ('Ledger_Mode', 'Fix_MoneyVolume', 'Gate_Recheck', 'Fix_ClosePath', 'Max_Spread_Points', 'Min_Margin_Level_PC'))
        self.assertEqual(list(self.schema['inputs'])[-len(APPENDED_INPUTS):], list(APPENDED_INPUTS), 'appended last, in order')
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
        for name in APPENDED_INPUTS:
            self.assertEqual(appended_default(self.schema['inputs'][name]), '0', name)
            # The same default the tester report pins for any omitted input (GOAT-EA#250).
            self.assertEqual(tester_report._schema_default(self.schema['inputs'][name], self.schema.get('defines')), '0', name)

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
        for name in APPENDED_INPUTS:
            self.assertEqual(validate_strategy(dict(self.old, **{name: '1'}), self.schema)['values'][name], '1')
            if self.schema['inputs'][name].get('enum_choices'):   # B49b (F6): the pre-trade caps are plain numbers
                with self.assertRaisesRegex(ValueError, name+': Undeclared enum value'):
                    validate_strategy(dict(self.old, **{name: '2'}), self.schema)
            with self.assertRaisesRegex(ValueError, name+': Input not exposed for optimization'):
                validate_strategy(dict(self.old, **{name: '0||0||1||1||Y'}), self.schema)

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
        # A schema without the inputs (the V1.48 contract) adds nothing; B49a's (no fix flag) adds only Ledger_Mode.
        v148 = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k not in APPENDED_INPUTS})
        self.assertEqual(complete_appended_inputs(self.old, v148), self.old)
        b49a = dict(self.schema, inputs={k: v for k, v in self.schema['inputs'].items() if k not in ('Fix_MoneyVolume', 'Gate_Recheck', 'Fix_ClosePath', 'Max_Spread_Points', 'Min_Margin_Level_PC')})
        self.assertEqual(complete_appended_inputs(self.old, b49a), dict(self.old, Ledger_Mode='0'))

    def test_the_paste_sets_the_default_instead_of_inheriting_the_last_run(self):
        pasted = explicit_paste_inputs(dict(self.old), self.schema)
        for name in APPENDED_INPUTS:
            self.assertEqual(pasted[name], '0||0||0||0||N', name)

    def test_the_readback_wants_the_default_and_catches_a_position_join_run(self):
        defaults = {name: '0' for name in APPENDED_INPUTS}
        observed = dict(self.full, **defaults)
        self.assertEqual(verify_input_readback(dict(self.old), observed, self.schema)['status'], 'INPUT_READBACK_MATCH')
        for name in APPENDED_INPUTS:
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
        observed = dict(reloaded, Ledger_Mode='1', Fix_MoneyVolume='0', Gate_Recheck='0', Fix_ClosePath='0', Max_Spread_Points='0', Min_Margin_Level_PC='0')   # MT5 reports every input
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
        observed = dict(reloaded, Ledger_Mode='0', Fix_MoneyVolume='1', Gate_Recheck='0', Fix_ClosePath='0', Max_Spread_Points='0', Min_Margin_Level_PC='0')
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
