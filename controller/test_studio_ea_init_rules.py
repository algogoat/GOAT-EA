"""EA init-rule parity (beta.38): validate_strategy refuses what GOAT's OnInit refuses from input values alone,
over every value an optimization range can reach, and every OnInit refusal is ported or listed as not ported."""
import copy
from pathlib import Path
import re
import unittest

from studio_ea_init_rules import (EA_INIT_CODE, EA_INIT_RULES, EA_INIT_SCHEMA_CODE, EA_SOURCE, MAX_COMBINATIONS,
                                  NOT_PORTED, TESTER_INIT_CODE, TESTER_INIT_RULES, check_ea_init, check_tester_init)
from studio_installation import contracts
from studio_strategy_settings import validate_strategy
from studio_template_tools import schema_default

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = {version: contracts(version)[0] for version in ('1.48', '1.49')}


def defaults(schema):
    return {name: schema_default(name, definition, schema['defines']) for name, definition in schema['inputs'].items()}


class RuleCase(unittest.TestCase):
    schema = SCHEMAS['1.49']

    def values(self, **changes):
        return defaults(self.schema) | changes

    def passes(self, **changes):
        validate_strategy(self.values(**changes), self.schema)

    def refused(self, rule_id, **changes):
        with self.assertRaises(ValueError) as caught:
            validate_strategy(self.values(**changes), self.schema)
        message = str(caught.exception)
        self.assertTrue(message.startswith(EA_INIT_CODE + ': '), message)
        self.assertIn('Rule ' + rule_id + ' (', message)
        return message


class PortedRuleTests(RuleCase):
    """One passing and one failing SET per ported rule, against both shipped schemas."""
    CASES = {
        'EXPORT_FOOS_NOT_AFTER_BOOS': (
            dict(EA_Desc='R0@{mode=EXPORT,dt_BOOS_end=2026.01.19,dt_FOOS_start=2026.01.20}'),
            dict(EA_Desc='R0@{mode=EXPORT,dt_BOOS_end=2026.01.19,dt_FOOS_start=2026.01.19}')),
        'EXPORT_FWD_HALF_GIVEN': (
            dict(EA_Desc='R0@{mode=EXPORT,dt_FWD_start=2026.07.17,dt_FWD_end=2026.08.28}'),
            dict(EA_Desc='R0@{mode=EXPORT,dt_FWD_start=2026.07.17}')),
        'EXPORT_FWD_END_BEFORE_START': (
            dict(EA_Desc='R0@{mode=EXPORT,dt_FWD_start=2026.07.17,dt_FWD_end=2026.07.17}'),
            dict(EA_Desc='R0@{mode=EXPORT,dt_FWD_start=2026.07.17,dt_FWD_end=2026.07.16}')),
        'DATA_DOWNLOAD_MODE_REMOVES_EA': (dict(Mode_Download='0'), dict(Mode_Download='1')),
        'SESSION_FORMAT': (dict(Active_Time_EU='00:00-23:59'), dict(Active_Time_EU='10:00 to 19:00')),
        'RISK_PER_SEQUENCE_RISK_TOO_LOW': (dict(Mode_Lots='2', Risk='10.0'), dict(Mode_Lots='2', Risk='9.99')),
        'MLPS_HARD_CLOSE_RISK_TOO_LOW': (dict(Sequence_MLPS_Hard_Close='true', Risk='10'),
                                         dict(Sequence_MLPS_Hard_Close='true', Risk='5.0')),
        'SMART_PEAK_RISK_TOO_LOW': (dict(Mode_Lots_Prog='6', Risk='10.0'), dict(Mode_Lots_Prog='6', Risk='9.0')),
        'SMART_PEAK_PERCENT_RANGE': (dict(Mode_Lots_Prog='6', Peak_Smart_Release_PC='100.0', Peak_Smart_Max_Close_PC='0.0'),
                                     dict(Mode_Lots_Prog='6', Peak_Smart_Release_PC='100.5')),
        'SMART_RESCUE_MAX_ADDS_BELOW_MINUS_ONE': (dict(Bias_Exit_Max_Exposure_Adds='-1'), dict(Bias_Exit_Max_Exposure_Adds='-2')),
        'SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE': (dict(Mode_Bias_Exit='1', Mode_Lots='2', Risk='500.0'),
                                                 dict(Mode_Bias_Exit='1', Mode_Lots='1')),
        'RRR_NEGATIVE': (dict(Mode_RRR='0', RRR='-1.0'), dict(Mode_RRR='1', RRR='-1.0', SL_Pips='10.0', TP_Pips='0.0')),
        'RRR_ZERO': (dict(Mode_RRR='0', RRR='0.0'), dict(Mode_RRR='2', RRR='0.0')),
        'RRR_SL_TP_BOTH_SET': (dict(Mode_RRR='1', RRR='2.0', SL_Pips='10.0', TP_Pips='0.0'),
                               dict(Mode_RRR='1', RRR='2.0', SL_Pips='10.0', TP_Pips='2.0')),
        'RRR_SL_TP_BOTH_ZERO': (dict(Mode_RRR='1', RRR='2.0', SL_Pips='0.0', TP_Pips='2.0'),
                                dict(Mode_RRR='1', RRR='2.0', SL_Pips='0.0', TP_Pips='0.0')),
        'RRR_SL_LP_BOTH_SET': (dict(Mode_RRR='2', RRR='2.0', SL_Pips='10.0', Lock_Profit_Size='0.0'),
                               dict(Mode_RRR='2', RRR='2.0', SL_Pips='10.0', Lock_Profit_Size='30.0')),
        'RRR_SL_LP_BOTH_ZERO': (dict(Mode_RRR='2', RRR='2.0', SL_Pips='0.0', Lock_Profit_Size='30.0'),
                                dict(Mode_RRR='2', RRR='2.0', SL_Pips='0.0', Lock_Profit_Size='0.0')),
        'GRID_SIZE_TOO_SMALL': (dict(Grid_Size='-0.5'), dict(Grid_Size='0.4')),
        'LP_AND_TP_BOTH_DISABLED': (dict(Lock_Profit_Size='0.5', TP_Pips='4.0'), dict(Lock_Profit_Size='0.5', TP_Pips='1.0')),
    }

    def test_every_ported_rule_has_a_passing_and_a_failing_set(self):
        self.assertEqual(set(self.CASES), {rule['id'] for rule in EA_INIT_RULES})
        for version, schema in SCHEMAS.items():
            for rule_id, (good, bad) in self.CASES.items():
                with self.subTest(version=version, rule=rule_id):
                    self.schema = schema
                    self.passes(**good)
                    self.refused(rule_id, **bad)

    def test_schema_defaults_pass(self):
        for version, schema in SCHEMAS.items():
            with self.subTest(version=version):
                validate_strategy(defaults(schema), schema)

    def test_smart_rescue_with_fixed_lots_is_refused_with_the_ea_alert(self):
        message = self.refused('SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE', Mode_Bias_Exit='1', Mode_Lots='0', Risk='500.0')
        self.assertEqual(message, EA_INIT_CODE + ': the EA refuses this SET at initialization. Rule '
                         'SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE (GOAT V1.49.mq5:4471) fails for '
                         'Mode_Bias_Exit=1 (BiasExit_SmartRescue), Mode_Lots=0 (FixedLots). EA alert: '
                         '"Initialization Failed: Smart Rescue requires Risk per Sequence lot sizing and Risk > 0."')
        self.passes(Mode_Bias_Exit='1', Mode_Lots='2', Risk='500.0')
        self.passes(Mode_Bias_Exit='0', Mode_Lots='0')

    def test_rrr_derivations_feed_the_lp_tp_rule_as_in_the_ea(self):
        # SL/LP mode derives LP = SL*RRR = 0.5, which line 4517 zeroes; TP_Pips_ = TP_Pips*original LP = 0.
        self.refused('LP_AND_TP_BOTH_DISABLED', Mode_RRR='2', RRR='0.05', SL_Pips='10.0', Lock_Profit_Size='0.0', TP_Pips='2.0')
        self.passes(Mode_RRR='2', RRR='2.0', SL_Pips='10.0', Lock_Profit_Size='0.0', TP_Pips='2.0')
        # SL/TP mode derives TP = SL*RRR when TP is zero.
        self.passes(Mode_RRR='1', RRR='0.5', SL_Pips='4.0', Lock_Profit_Size='0.5', TP_Pips='0.0')
        self.refused('LP_AND_TP_BOTH_DISABLED', Mode_RRR='1', RRR='0.1', SL_Pips='4.0', Lock_Profit_Size='0.5', TP_Pips='0.0')

    def test_session_strings_follow_stringsplit(self):
        for text in ('', '01:30', '0130-1100', '01:30-11:00-12:00', '01:30-1100', '-11:00', '01:30-'):
            with self.subTest(text=text):
                self.refused('SESSION_FORMAT', Active_Time_US=text)
        for text in ('01:30-11:00', 'a:b-c:d'):                                    # format only; StringToInteger reads the rest
            with self.subTest(text=text):
                self.passes(Active_Time_US=text)

    def test_export_dates_are_read_from_ea_desc_like_the_ea(self):
        self.passes(EA_Desc='R0@{mode=EXPORT,dt_BOOS_end=2026.01.19,dt_FOOS_start=2026.08.29,'
                            'dt_FWD_start=2026.07.17,dt_FWD_end=2026.08.28}')          # the controller's catch-up shape
        self.passes(EA_Desc='R0@{mode=EXPORT}')
        self.passes(EA_Desc='R0@{mode=SEED,dt_FWD_start=2026.07.17}')                  # not EXPORT: dates unused
        self.passes(EA_Desc='R0 dt_FWD_start=2026.07.17 mode=EXPORT')                  # no @{...} section
        self.refused('EXPORT_FWD_HALF_GIVEN', EA_Desc="R0@{ Mode = 'EXPORT' , dt_FWD_end = \"2026.08.28\" }")
        self.refused('EXPORT_FWD_END_BEFORE_START', EA_Desc='R0@{mode=EXPORT,dt_FWD_start=2026.07.17 10:00,dt_FWD_end=2026.07.17 09:59}')
        # A date form whose StringToTime result is not reproducible is never refused on a guess.
        self.passes(EA_Desc='R0@{mode=EXPORT,dt_FWD_start=17/07/2026}')


class OptimizationRangeTests(RuleCase):
    def test_one_failing_ladder_value_refuses_and_names_it(self):
        message = self.refused('GRID_SIZE_TOO_SMALL', Grid_Size='10.0||-1.0||0.5||2.0||Y')
        self.assertIn('fails for Grid_Size=0 (reachable through the optimization range of Grid_Size)', message)
        self.assertIn('EA alert: "Initialization Failed: Pip Gap Size too small or zero"', message)
        self.passes(Grid_Size='10.0||-2.0||0.5||-0.5||Y')                             # -0.5 is allowed (strict >)
        message = self.refused('SMART_PEAK_PERCENT_RANGE', Mode_Lots_Prog='6', Peak_Smart_Release_PC='50.0||0.0||12.5||125.0||Y')
        self.assertIn('Peak_Smart_Release_PC=100.5', self.refused(
            'SMART_PEAK_PERCENT_RANGE', Mode_Lots_Prog='6', Peak_Smart_Release_PC='50.0||0.5||10||100.5||Y'))
        self.assertIn('Peak_Smart_Release_PC=112.5', message)

    def test_an_enum_ladder_reaching_a_refused_mode_is_refused(self):
        message = self.refused('SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE', Mode_Bias_Exit='0||0||1||1||Y', Mode_Lots='0')
        self.assertIn('Mode_Bias_Exit=1 (BiasExit_SmartRescue), Mode_Lots=0 (FixedLots)', message)
        self.refused('LP_AND_TP_BOTH_DISABLED', Mode_Lots_Prog='1', Lock_Profit_Size='0.5', TP_Pips='4.0||1.0||1.0||4.0||Y')

    def test_two_ladders_combine(self):
        # LP ladder and TP ladder: only LP=0.5 with TP_Pips<=1 fails (|TP_Pips*LP|<1).
        message = self.refused('LP_AND_TP_BOTH_DISABLED', Lock_Profit_Size='30.0||0.5||0.5||30.0||Y', TP_Pips='3.0||1.0||1.0||3.0||Y')
        self.assertIn('Lock_Profit_Size=0.5, TP_Pips=1', message)
        self.passes(Lock_Profit_Size='30.0||0.5||0.5||30.0||Y', TP_Pips='3.0||3.0||1.0||5.0||Y')

    def test_current_value_and_dormant_tuples_count_like_the_risk_rule(self):
        self.refused('GRID_SIZE_TOO_SMALL', Grid_Size='0.0||5.0||5.0||20.0||Y')       # a single test runs the current value
        self.refused('GRID_SIZE_TOO_SMALL', Grid_Size='0.0||5.0||5.0||20.0||N')       # MT5 runs the first field
        self.passes(Grid_Size='10.0||-1.0||0.5||0.0||N')                              # a dormant ladder never runs

    def test_inputs_a_short_circuited_condition_never_reads_are_not_expanded(self):
        huge = '1.0||1.0||1.0||50000.0||Y'
        self.passes(Mode_RRR='0', SL_Pips=huge, RRR=huge)                              # RRR off: SL/RRR never read

    def test_too_many_combinations_is_refused_with_a_clear_message(self):
        message = self.refused_unchecked(Grid_Size='10.0||1.0||1.0||' + str(MAX_COMBINATIONS + 1) + '.0||Y')
        self.assertIn('GRID_SIZE_TOO_SMALL (GOAT V1.49.mq5:4514) cannot be checked: the optimization ranges of Grid_Size '
                      'give more than 10,000 combinations', message)
        message = self.refused_unchecked(Lock_Profit_Size='10.0||1.0||1.0||200.0||Y', TP_Pips='2.0||1.0||1.0||100.0||Y')
        self.assertIn('LP_AND_TP_BOTH_DISABLED', message)
        self.assertIn('Lock_Profit_Size, TP_Pips', message)
        self.passes(Lock_Profit_Size='10.0||1.0||1.0||100.0||Y', TP_Pips='2.0||1.0||1.0||99.0||Y')   # 9,900 combinations

    def refused_unchecked(self, **changes):
        with self.assertRaisesRegex(ValueError, '^' + EA_INIT_CODE + ': .* cannot be checked') as caught:
            validate_strategy(self.values(**changes), self.schema)
        return str(caught.exception)


class SchemaTests(RuleCase):
    def test_a_goat_schema_that_lost_a_rule_label_or_input_fails_closed(self):
        renamed = copy.deepcopy(self.schema)
        renamed['inputs']['Mode_Bias_Exit']['enum_choices'] = {'BiasExit_HardClose': 0, 'BiasExit_Rescue': 1}
        with self.assertRaisesRegex(ValueError, '^' + EA_INIT_SCHEMA_CODE + '.*Mode_Bias_Exit.BiasExit_SmartRescue'):
            check_ea_init(self.values(), renamed)
        missing = copy.deepcopy(self.schema); del missing['inputs']['Grid_Size']
        values = self.values(); del values['Grid_Size']
        with self.assertRaisesRegex(ValueError, '^' + EA_INIT_SCHEMA_CODE + '.*Grid_Size.*GRID_SIZE_TOO_SMALL'):
            validate_strategy(values, missing)

    def test_compact_schema_without_the_goat_interface_checks_only_rules_it_can_express(self):
        compact = dict(source_sha256='0'*64, inputs=dict(Grid_Size=self.schema['inputs']['Grid_Size'],
                                                          Period=dict(type='int', optimizable=True, enum_choices=None)))
        validate_strategy(dict(Grid_Size='10.0', Period='5'), compact)
        with self.assertRaisesRegex(ValueError, '^' + EA_INIT_CODE):
            validate_strategy(dict(Grid_Size='0.0', Period='5'), compact)
        validate_strategy(dict(Period='5'), dict(source_sha256='0'*64, inputs=dict(Period=compact['inputs']['Period'])))

    def test_partial_values_use_the_declared_defaults(self):
        check_ea_init({'Mode_Bias_Exit': '1', 'Mode_Lots': '2'}, self.schema)          # default Risk 500
        with self.assertRaisesRegex(ValueError, 'SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE'):
            check_ea_init({'Mode_Bias_Exit': '1'}, self.schema)                         # default FixedLots


class DataDownloadTests(RuleCase):
    def test_every_download_mode_removes_the_ea_and_is_refused(self):
        for value, label in (('1', 'Download_News'), ('2', 'Download_Bias'), ('3', 'Download_NewsBias')):
            with self.subTest(label=label):
                message = self.refused('DATA_DOWNLOAD_MODE_REMOVES_EA', Mode_Download=value)
                self.assertIn('(GOAT V1.49.mq5:4070,4087) fails for Mode_Download=%s (%s)' % (value, label), message)
                self.assertIn('EA alert: "News History download is not allowed in this mode / Bias History download is '
                              'not allowed in this mode"', message)
                self.assertIn('use Download_Disabled', message)
        self.passes(Mode_Download='0')


AI_ON = dict(Mode_Bias='2', Bias_Protocol='2')           # the header defaults: Bias_Opens + ControlTowerV2DemoRaw


class TesterInitRuleTests(RuleCase):
    """P-beta38-prepare-tester-ai-bias: GOAT V1.49.mq5:3972, refused in the tester only."""
    def refused_in_tester(self, **changes):
        with self.assertRaises(ValueError) as caught:
            check_tester_init(self.values(**changes), self.schema)
        message = str(caught.exception)
        self.assertTrue(message.startswith(TESTER_INIT_CODE + ': '), message)
        self.assertIn('Rule TESTER_CONTROL_TOWER_BIAS (GOAT V1.49.mq5:3972)', message)
        self.assertIn('EA alert: "Live Control Tower bias is unavailable in tester, optimization, and forward contexts. '
                      'Select BiasProtocol_LegacyRecorded or disable AI bias."', message)
        return message

    def test_ai_bias_with_a_control_tower_protocol_is_refused_in_the_tester(self):
        for version, schema in SCHEMAS.items():
            self.schema = schema
            for mode in ('0', '2', '3', '4', '5'):                                      # every mode but Bias_Disabled
                for protocol in ('1', '2'):                                             # ControlTowerV2, ...DemoRaw
                    with self.subTest(version=version, mode=mode, protocol=protocol):
                        self.refused_in_tester(Mode_Bias=mode, Bias_Protocol=protocol)
        self.schema = SCHEMAS['1.49']
        self.assertIn('fails for Mode_Bias=2 (Bias_Opens), Bias_Protocol=2 (BiasProtocol_ControlTowerV2DemoRaw)',
                      self.refused_in_tester(**AI_ON))

    def test_ai_off_or_legacy_recorded_passes_in_the_tester(self):
        for protocol in ('0', '1', '2'):
            check_tester_init(self.values(Mode_Bias='1', Bias_Protocol=protocol), self.schema)
        for mode in ('0', '2', '5'):
            check_tester_init(self.values(Mode_Bias=mode, Bias_Protocol='0'), self.schema)

    def test_ladders_reaching_the_refused_combination_are_refused(self):
        message = self.refused_in_tester(Mode_Bias='1||1||1||2||Y', Bias_Protocol='2')
        self.assertIn('Mode_Bias=2 (Bias_Opens), Bias_Protocol=2 (BiasProtocol_ControlTowerV2DemoRaw) (reachable through '
                      'the optimization range of Mode_Bias)', message)
        self.refused_in_tester(Mode_Bias='2', Bias_Protocol='0||0||1||1||Y')
        check_tester_init(self.values(Mode_Bias='1||1||1||1||Y', Bias_Protocol='0||0||1||2||Y'), self.schema)
        check_tester_init(self.values(Mode_Bias='2||0||1||5||N', Bias_Protocol='0'), self.schema)

    def test_the_live_validate_set_path_is_unaffected(self):
        from studio_template_tools import validate_raw
        values = self.values(**AI_ON)
        validate_strategy(values, self.schema)                                           # live-valid strategy
        raw = b'\xff\xfe' + ''.join('%s=%s\r\n' % kv for kv in values.items()).encode('utf-16-le')
        self.assertEqual(validate_raw(raw, self.schema, contracts('1.49')[1])['kind'], 'fixed_settings')
        self.assertEqual({rule['id'] for rule in EA_INIT_RULES} & {rule['id'] for rule in TESTER_INIT_RULES}, set())

    def test_fresh_starters_pass_the_tester_rule(self):
        # Positive control (GOAT-EA#231): starter-set writes Mode_Bias=Bias_Disabled for both shapes and both schemas.
        import tempfile
        from studio_template_tools import STARTER_SHAPES, starter_set
        for version in SCHEMAS:
            schema, policy = contracts(version)
            for shape in STARTER_SHAPES:
                with self.subTest(version=version, shape=shape), tempfile.TemporaryDirectory() as folder:
                    result = starter_set(shape, Path(folder) / 'starter.set', schema, policy, controller_version='t',
                                         ea_version=version)
                    from studio_strategy_settings import read_values
                    values = read_values(Path(result['output']['path']).read_bytes())
                    self.assertEqual(values['Mode_Bias'], str(schema['inputs']['Mode_Bias']['enum_choices']['Bias_Disabled']))
                    check_tester_init(values, schema)

    def test_a_goat_schema_without_the_protocol_label_fails_closed(self):
        broken = copy.deepcopy(self.schema)
        broken['inputs']['Bias_Protocol']['enum_choices'] = {'BiasProtocol_LegacyRecorded': 0}
        with self.assertRaisesRegex(ValueError, '^' + EA_INIT_SCHEMA_CODE + '.*Bias_Protocol.BiasProtocol_ControlTowerV2 '
                                    'for EA init rule TESTER_CONTROL_TOWER_BIAS'):
            check_tester_init(self.values(Mode_Bias='1', Bias_Protocol='0'), broken)


class PrepareBatchTesterTests(unittest.TestCase):
    """prepare-batch refuses a tester-refused member before anything is staged or queued."""
    def setUp(self):
        import test_goat_studio as fixtures
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        real = SCHEMAS['1.49']['inputs']
        self.c.schema['inputs'].update(Mode_Bias=dict(real['Mode_Bias']), Bias_Protocol=dict(real['Bias_Protocol']))
        self.c.store.input_schema = self.c.schema
        from campaign_ledger import sha
        self.c.store.input_schema_hash = sha(self.c.schema)
        self.root = self.fixture.root

    def prepare(self, name, *members):
        import json
        from studio_batch import prepare_batch
        spec = dict(schema_version=1, export=self.fixture.exports, members=[])
        for index, (mode, protocol) in enumerate(members):
            source = self.root / ('%s-%d.set' % (name, index))
            source.write_bytes(('EA_Desc=Template %d\r\nLots=0.1||0.1||0.1||0.3||Y\r\nMode_Bias=%s\r\nBias_Protocol=%s\r\n'
                                % (index, mode, protocol)).encode('utf-16'))
            spec['members'].append(dict(set_path=str(source), tester=self.fixture.tester | {'Symbol': 'SYM%d' % index}))
        plan = self.root / (name + '.json'); plan.write_text(json.dumps(spec), encoding='utf-8')
        return prepare_batch(self.c, name, plan)

    def test_a_refused_in_tester_member_fails_at_prepare_and_nothing_is_staged(self):
        with self.assertRaisesRegex(ValueError, '^' + TESTER_INIT_CODE + r': batch member 2 \(.*refused-1\.set\): the EA '
                                    'refuses this SET in the strategy tester.*TESTER_CONTROL_TOWER_BIAS'):
            self.prepare('refused', ('1', '2'), ('2', '2'))
        self.assertEqual(self.c.state()['queue'], [])
        self.assertFalse((self.c.root / 'packages' / 'refused').exists())
        with self.assertRaisesRegex(ValueError, '^' + TESTER_INIT_CODE):
            self.prepare('laddered', ('1||1||1||2||Y', '1'))

    def test_ai_off_and_legacy_recorded_members_prepare(self):
        result = self.prepare('allowed', ('1', '2'), ('2', '0'))
        self.assertEqual(result['member_count'], 2)
        self.assertEqual(len(self.c.state()['queue']), 1)


def _code_lines(source):
    """Each source line with comments and string/char literal contents blanked (MQL lexing)."""
    out, state, i = [], 'code', 0
    buffer = []
    while i < len(source):
        ch, nxt = source[i], source[i+1:i+2]
        if state == 'code':
            if ch == '/' and nxt == '/': state = 'line'; i += 2; continue
            if ch == '/' and nxt == '*': state = 'block'; i += 2; continue
            if ch in '"\'': state = ch; buffer.append(ch); i += 1; continue
            buffer.append(ch)
        elif state == 'line':
            if ch == '\n': state = 'code'; buffer.append(ch)
        elif state == 'block':
            if ch == '*' and nxt == '/': state = 'code'; i += 2; continue
            if ch == '\n': buffer.append(ch)
        else:                                                                            # inside a literal
            if ch == '\\': i += 2; continue
            if ch == state: state = 'code'; buffer.append(ch)
            elif ch == '\n': buffer.append(ch)
        i += 1
    out = ''.join(buffer).split('\n')
    return out


def _function_lines(code, signature):
    """1-based (first, last) line numbers of a top-level MQL function body found by brace matching."""
    start = next(index for index, line in enumerate(code) if line.strip().startswith(signature))
    depth, opened = 0, False
    for index in range(start, len(code)):
        for ch in code[index]:
            if ch == '{': depth += 1; opened = True
            elif ch == '}': depth -= 1
        if opened and depth == 0:
            return start + 1, index + 1
    raise AssertionError('unterminated ' + signature)


INIT_RETURN = re.compile(r'\breturn\s*\(?\s*(INIT_PARAMETERS_INCORRECT|INIT_FAILED)\b')
EXPERT_REMOVE = re.compile(r'\bExpertRemove\s*\(')


def _squash(text):
    return re.sub(r'\s+', '', text)


class InventoryTests(unittest.TestCase):
    """A future OnInit refusal cannot be silently missed: each is ported or listed as NOT_PORTED with a reason."""
    def setUp(self):
        self.raw = (REPO / EA_SOURCE).read_text(encoding='utf-8-sig', errors='replace').split('\n')
        code = _code_lines('\n'.join(self.raw))
        first, last = _function_lines(code, 'int OnInit()')
        body = range(first, last+1)
        self.returns = {number: INIT_RETURN.search(code[number-1])[1] for number in body if INIT_RETURN.search(code[number-1])}
        # The EA also ends init by removing itself (ExpertRemove) without an INIT_* return: classified the same way.
        self.removals = {number for number in body if EXPERT_REMOVE.search(code[number-1])}
        self.sites = set(self.returns) | self.removals

    def entries(self):
        return [('ported', rule['id'], rule['lines'], rule['anchor']) for rule in EA_INIT_RULES] + \
               [('tester', rule['id'], rule['lines'], rule['anchor']) for rule in TESTER_INIT_RULES] + \
               [('not_ported', entry['condition'], entry['lines'], entry['anchor']) for entry in NOT_PORTED]

    def test_rule_table_targets_the_newest_ea_source(self):
        versions = sorted(tuple(int(part) for part in re.fullmatch(r'GOAT V(\d+)\.(\d+)\.mq5', p.name).groups())
                          for p in REPO.glob('GOAT V*.mq5'))
        self.assertEqual('GOAT V%d.%d.mq5' % versions[-1], EA_SOURCE,
                         'A newer EA source exists: re-audit its OnInit refusals into EA_INIT_RULES / NOT_PORTED')

    def test_every_oninit_refusal_is_ported_or_explicitly_not_ported(self):
        listed = [line for _, _, lines, _ in self.entries() for line in lines]
        self.assertEqual(len(listed), len(set(listed)), 'a line is listed twice')
        self.assertEqual(sorted(self.sites), sorted(listed),
                         'OnInit refusal/removal lines and the EA_INIT_RULES/TESTER_INIT_RULES/NOT_PORTED tables differ')
        # B49b (F7 SIG-01) adds six indicator-handle INIT_FAILED returns (NOT_PORTED: indicator runtime).
        self.assertEqual((len(self.returns), len(self.removals), len(self.sites)), (57, 8, 61))
        self.assertEqual(list(self.returns.values()).count('INIT_PARAMETERS_INCORRECT'), 26)
        self.assertEqual((sum(len(r['lines']) for r in EA_INIT_RULES), sum(len(r['lines']) for r in TESTER_INIT_RULES),
                          sum(len(e['lines']) for e in NOT_PORTED)), (22, 1, 38))
        # The removal-only paths (no INIT_* return on the line): name mismatch, the two download removals, and
        # the unreachable removal after the dashboard-cancel return.
        self.assertEqual(sorted(self.removals - set(self.returns)), [3960, 4070, 4087, 4362])

    def test_each_listed_line_still_carries_its_condition_text(self):
        for kind, name, lines, anchor in self.entries():
            for line in lines:
                with self.subTest(kind=kind, entry=name, line=line):
                    window = _squash(''.join(self.raw[max(0, line-12):line]))
                    self.assertIn(_squash(anchor), window)

    def test_ported_rules_quote_the_eas_own_alert_text(self):
        source = _squash('\n'.join(self.raw))
        for rule in EA_INIT_RULES + TESTER_INIT_RULES:
            with self.subTest(rule=rule['id']):
                for fragment in re.split(r'<date>| / ', rule['alert']):
                    self.assertIn(_squash(fragment), source)
                self.assertEqual(rule['source'], EA_SOURCE)
                self.assertTrue(rule['inputs'] and rule['condition'] and callable(rule['predicate']))

    def test_not_ported_entries_give_a_reason(self):
        for entry in NOT_PORTED:
            self.assertTrue(entry['reason'].strip() and entry['condition'].strip(), entry)

    def test_lexer_drops_comments_and_literals(self):
        code = _code_lines('a; // return INIT_FAILED;\n/* return INIT_FAILED;\n */ b("return INIT_FAILED;");\n')
        self.assertFalse(any(INIT_RETURN.search(line) for line in code))


if __name__ == '__main__':
    unittest.main()
