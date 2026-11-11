"""EA init-rule parity (beta.38): validate_strategy refuses what GOAT's OnInit refuses from input values alone,
over every value an optimization range can reach, and every OnInit refusal is ported or listed as not ported."""
import copy
from pathlib import Path
import re
import unittest

from studio_ea_init_rules import (EA_INIT_CODE, EA_INIT_RULES, EA_INIT_SCHEMA_CODE, EA_SOURCE, MAX_COMBINATIONS,
                                  NOT_PORTED, TESTER_INIT_CODE, TESTER_INIT_RULES, applicable_rules, check_ea_init,
                                  check_tester_init)
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

    # B50 (A0): rules on the inputs appended after Ledger_Mode, which only the V1.49 schema declares.
    B50_CASES = {
        'SINGLE_SL_ATR_NOT_POSITIVE': (dict(Engine_Mode='1', Single_SL_ATR='0.5', Mode_Bias_Exit='0'),
                                       dict(Engine_Mode='1', Single_SL_ATR='0.0', Mode_Bias_Exit='0')),
        'SINGLE_TP_NEGATIVE': (dict(Single_TP_ATR='0.0', Single_TP_R='2.0'), dict(Single_TP_R='-0.5')),
        'SINGLE_TIME_STOP_BARS_NEGATIVE': (dict(Single_Time_Stop_Bars='0'), dict(Single_Time_Stop_Bars='-1')),
        'ROLLOVER_BLOCK_NEGATIVE': (dict(Rollover_Block_Minutes='15'), dict(Rollover_Block_Minutes='-1')),
        'SERVER_UTC_OFFSET_RANGE': (dict(Server_UTC_Offset='14'), dict(Server_UTC_Offset='-13')),
        'SINGLE_WITH_SMART_RESCUE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0'),
                                     dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='1', Mode_Lots='2')),
        'NY_SESSION_FORMAT': (dict(NY_Session='22:00-6:30'), dict(NY_Session='9:30-16:0')),
        # B51 (beta-1a): the random-direction benchmark needs the single engine; the seed is not negative.
        'RANDOM_DIRECTION_WITHOUT_SINGLE': (dict(Random_Direction='true', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0',
                                                 Single_Flat_Only='true'),
                                            dict(Random_Direction='true', Engine_Mode='0')),
        'RANDOM_SEED_NEGATIVE': (dict(Random_Seed='0'), dict(Random_Seed='-1')),
        'RANDOM_DIRECTION_ONE_DIRECTION': (dict(Random_Direction='false', Mode_Trade='1'),
                                           dict(Random_Direction='true', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0',
                                                Single_Flat_Only='true', Mode_Trade='0||0||1||2||Y')),
        'RANDOM_DIRECTION_WITHOUT_FLAT_ONLY': (dict(Random_Direction='true', Single_Flat_Only='true', Engine_Mode='1', Single_SL_ATR='1.0',
                                                    Mode_Bias_Exit='0'),
                                               dict(Random_Direction='true', Single_Flat_Only='false', Engine_Mode='1', Single_SL_ATR='1.0',
                                                    Mode_Bias_Exit='0')),
        'SINGLE_FLAT_ONLY_WITHOUT_SINGLE': (dict(Single_Flat_Only='true', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0'),
                                            dict(Single_Flat_Only='true', Engine_Mode='0')),
        # B51 (beta-1b): the break-even and trailing distances are not negative (0 = off).
        'SINGLE_BE_TRAIL_NEGATIVE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_BE_ATR='1.0',
                                          Single_Trail_Start_ATR='0.0', Single_Trail_ATR='0.5'),
                                     dict(Single_BE_ATR='-0.5')),
        'SINGLE_TRAIL_START_WITHOUT_DISTANCE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_Trail_Start_ATR='2.0',
                                                     Single_Trail_ATR='0.5'),
                                                dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_Trail_Start_ATR='2.0',
                                                     Single_Trail_ATR='0.0||0.0||0.5||1.0||Y')),
        'SINGLE_EXITS_WITHOUT_SINGLE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_BE_ATR='1.0'),
                                        dict(Engine_Mode='0', Single_BE_ATR='1.0')),
        'SINGLE_PARTIAL_NEGATIVE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5'),
                                    dict(Single_Partial_ATR='-1.0')),
        'SINGLE_PARTIAL_FRACTION_NOT_BELOW_ONE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.99'),
                                                  dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='1.0')),
        'SINGLE_PARTIAL_INCOMPLETE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5'),
                                      dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_Partial_Fraction='0.5')),
        'SINGLE_PARTIAL_BE_WITHOUT_PARTIAL': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5', Single_Partial_BE='true'),
                                              dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Single_Partial_BE='true')),
        'SINGLE_PARTIAL_WITHOUT_SINGLE': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5'),
                                          dict(Engine_Mode='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5')),
        'SINGLE_PARTIAL_NEEDS_POSITION_JOIN': (dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='1', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5'),
                                               dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', Ledger_Mode='0', Single_Partial_ATR='1.0', Single_Partial_Fraction='0.5')),
        # B52 (the final build's review, P3): the benchmark never runs under the first-order gate (Gate_AtFirstOrder = 1).
        'RANDOM_DIRECTION_WITH_FIRST_ORDER_GATE': (dict(Random_Direction='true', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0',
                                                        Single_Flat_Only='true', Gate_Recheck='0'),
                                                   dict(Random_Direction='true', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0',
                                                        Single_Flat_Only='true', Gate_Recheck='1')),
    }

    # B54 (spec 4.6, GOAT V1.49.mq5:5122-5147): the breakout entries on a valid single. Every mode value has its signal term
    # (entry A since PR A, entry B since PR B), so no *_NOT_BUILT rule is left and a "good" SET with a family on passes.
    S = dict(Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0')
    NBAR, PDAY, ORB = dict(S, BRK_Mode='1'), dict(S, BRK_Mode='2'), dict(S, ORB_Mode='1')
    B54_CASES = {
        'BRK_WITHOUT_SINGLE': (NBAR, dict(BRK_Mode='1', Engine_Mode='0')),
        'ORB_WITHOUT_SINGLE': (ORB, dict(ORB_Mode='1', Engine_Mode='0')),
        'BRK_WITH_ORB': (PDAY, dict(PDAY, ORB_Mode='1')),
        'BRK_BARS_RANGE': (dict(NBAR, BRK_Bars='500'), dict(NBAR, BRK_Bars='501')),
        'BRK_BUFFER_RANGE': (dict(PDAY, BRK_Buffer_ATR='5.0'), dict(PDAY, BRK_Buffer_ATR='-0.1')),
        'BRK_PRIOR_DAY_ON_D1': (dict(PDAY, BRK_TF_='240'), dict(PDAY, BRK_TF_='1440')),
        'ORB_TF_NOT_M1_TO_H1': (dict(ORB, ORB_TF_='60', ORB_Start_Minute='540', ORB_Range_Minutes='60'), dict(ORB, ORB_TF_='240')),
        'ORB_START_RANGE': (dict(ORB, ORB_Start_Minute='0'), dict(ORB, ORB_Start_Minute='1020')),
        'ORB_RANGE_MINUTES': (dict(ORB, ORB_Range_Minutes='240'), dict(ORB, ORB_Range_Minutes='245')),
        'ORB_ENTRY_WINDOW': (dict(ORB, ORB_Entry_Minutes='420'), dict(ORB, ORB_Entry_Minutes='425')),
        'ORB_BUFFER_RANGE': (dict(ORB, ORB_Buffer_ATR='5.0'), dict(ORB, ORB_Buffer_ATR='5.5')),
        'ORB_RANGE_FILTER_NEGATIVE': (dict(ORB, ORB_Min_Range_ATR='0.5', ORB_Max_Range_ATR='2.0'), dict(ORB, ORB_Min_Range_ATR='-0.5')),
        'ORB_RANGE_FILTER_ORDER': (dict(ORB, ORB_Min_Range_ATR='0.5', ORB_Max_Range_ATR='2.0'),
                                   dict(ORB, ORB_Min_Range_ATR='2.0', ORB_Max_Range_ATR='2.0')),
    }

    def test_every_ported_rule_has_a_passing_and_a_failing_set(self):
        self.assertEqual(set(self.CASES) | set(self.B50_CASES) | set(self.B54_CASES), {rule['id'] for rule in EA_INIT_RULES})
        self.assertFalse([rule['id'] for rule in EA_INIT_RULES if rule['id'].endswith('_NOT_BUILT')], 'PR B: every mode value has its term')
        for rule_id, (good, bad) in self.B54_CASES.items():
            with self.subTest(rule=rule_id):
                self.passes(**good)
                self.refused(rule_id, **bad)
        # B54: a schema without the B54 group (B53's) carries none of its rules and every other one; a B54 schema that lost
        # one of its inputs or labels fails closed.
        b54 = set(self.B54_CASES)
        b53 = copy.deepcopy(SCHEMAS['1.49'])
        for name in ('BRK_Mode', 'BRK_TF_', 'BRK_Bars', 'BRK_Buffer_ATR', 'BRK_Once_Per_Level', 'ORB_Mode', 'ORB_Clock', 'ORB_TF_',
                     'ORB_Start_Minute', 'ORB_Range_Minutes', 'ORB_Entry_Minutes', 'ORB_Buffer_ATR', 'ORB_Min_Range_ATR', 'ORB_Max_Range_ATR'):
            del b53['inputs'][name]
        self.assertEqual({rule['id'] for rule in applicable_rules(b53)}, {rule['id'] for rule in EA_INIT_RULES} - b54)
        self.assertEqual(applicable_rules(b53, TESTER_INIT_RULES), list(TESTER_INIT_RULES[:2]))
        for lost in ('ORB_Clock', 'BRK_Bars', 'ORB_Max_Range_ATR'):
            with self.subTest(lost=lost):
                damaged = copy.deepcopy(SCHEMAS['1.49']); del damaged['inputs'][lost]
                with self.assertRaisesRegex(ValueError, EA_INIT_SCHEMA_CODE + ': this input schema has no ' + lost):
                    applicable_rules(damaged)
        damaged = copy.deepcopy(SCHEMAS['1.49']); del damaged['inputs']['ORB_TF_']['enum_choices']['TF_M15']
        with self.assertRaisesRegex(ValueError, EA_INIT_SCHEMA_CODE + ': this input schema has no ORB_TF_.TF_M15 for EA init rule '
                                    'ORB_TF_NOT_M1_TO_H1'):
            applicable_rules(damaged)
        for version, schema in SCHEMAS.items():
            for rule_id, (good, bad) in self.CASES.items():
                with self.subTest(version=version, rule=rule_id):
                    self.schema = schema
                    self.passes(**good)
                    self.refused(rule_id, **bad)
        for rule_id, (good, bad) in self.B50_CASES.items():
            with self.subTest(rule=rule_id):
                self.passes(**good)
                self.refused(rule_id, **bad)
        # V1.48 has no B50 input: its schema carries none of these rules, and nothing else changes.
        self.assertFalse(set(self.B50_CASES) & {rule['id'] for rule in applicable_rules(SCHEMAS['1.48'])})
        self.assertEqual({rule['id'] for rule in applicable_rules(SCHEMAS['1.48'])}, set(self.CASES))
        # GOAT-EA#269 P3: a B50 schema that lost one of its inputs fails closed, as for any other lost input.
        for lost in ('Engine_Mode', 'NY_Session', 'Server_UTC_Offset'):
            with self.subTest(lost=lost):
                damaged = copy.deepcopy(SCHEMAS['1.49']); del damaged['inputs'][lost]
                with self.assertRaisesRegex(ValueError, EA_INIT_SCHEMA_CODE + ': this input schema has no ' + lost):
                    applicable_rules(damaged)
        # B51 (beta-1a): a B50-alpha schema (no B51 input) carries none of B51's rules and every B50 one; a B51 schema
        # that lost one of its inputs fails closed.
        alpha = copy.deepcopy(SCHEMAS['1.49'])
        for name in ('Random_Direction', 'Random_Seed', 'Single_Flat_Only', 'Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR',
                     'Single_Partial_ATR', 'Single_Partial_Fraction', 'Single_Partial_BE'):
            del alpha['inputs'][name]
        b51 = {'RANDOM_DIRECTION_WITHOUT_SINGLE', 'RANDOM_SEED_NEGATIVE', 'RANDOM_DIRECTION_ONE_DIRECTION', 'RANDOM_DIRECTION_WITHOUT_FLAT_ONLY',
               'SINGLE_FLAT_ONLY_WITHOUT_SINGLE', 'SINGLE_BE_TRAIL_NEGATIVE', 'SINGLE_TRAIL_START_WITHOUT_DISTANCE', 'SINGLE_EXITS_WITHOUT_SINGLE',
               'SINGLE_PARTIAL_NEGATIVE', 'SINGLE_PARTIAL_FRACTION_NOT_BELOW_ONE', 'SINGLE_PARTIAL_INCOMPLETE', 'SINGLE_PARTIAL_BE_WITHOUT_PARTIAL',
               'SINGLE_PARTIAL_WITHOUT_SINGLE', 'SINGLE_PARTIAL_NEEDS_POSITION_JOIN', 'RANDOM_DIRECTION_WITH_FIRST_ORDER_GATE'}
        self.assertEqual({rule['id'] for rule in applicable_rules(alpha)}, {rule['id'] for rule in EA_INIT_RULES} - b51)
        for lost in ('Random_Direction', 'Random_Seed', 'Single_Trail_ATR', 'Single_Partial_BE', 'Single_Partial_ATR', 'Ledger_Mode'):
            with self.subTest(lost=lost):
                damaged = copy.deepcopy(SCHEMAS['1.49']); del damaged['inputs'][lost]
                with self.assertRaisesRegex(ValueError, EA_INIT_SCHEMA_CODE + ': this input schema has no ' + lost):
                    applicable_rules(damaged)

    def test_the_ny_session_mirrors_the_eas_parse(self):
        # GOAT V1.49.mq5:5055-5066: one '-', one ':' per half, hours of one or two digits, two-digit minutes.
        for good in ('09:30-16:00', '9:30-16:00', '00:00-23:59', '22:00-06:30', '23:59-00:00'):
            with self.subTest(good=good):
                self.passes(NY_Session=good)
        for bad in ('', '09:30', '09:30-16:00-17:00', '09-16', '24:00-16:00', '09:60-16:00', '09:30-16:0', '009:30-16:00',
                    ' 9:30-16:00', '+9:30-16:00', '09:30-16:00 ', '9:3a-16:00', '09:30-09:30', '09:30:00-16:00'):
            with self.subTest(bad=bad):
                self.refused('NY_SESSION_FORMAT', NY_Session=bad)

    def test_b54_windows_follow_the_anchor_and_the_trigger_minutes(self):
        # Spec 4.1/4.4: Lim is 1020 under the New York anchor and 1260 under the London one; S and R count in ORB_TF_'s minutes.
        orb, london = self.ORB, dict(self.ORB, ORB_Clock='1')
        self.refused('ORB_RANGE_MINUTES', **dict(orb, ORB_Start_Minute='1015', ORB_Range_Minutes='5'))    # S+R = Lim
        self.passes(**dict(orb, ORB_Start_Minute='1010', ORB_Range_Minutes='5', ORB_Entry_Minutes='5'))  # S+R+E = Lim
        self.refused('ORB_ENTRY_WINDOW', **dict(orb, ORB_Start_Minute='1010', ORB_Range_Minutes='5', ORB_Entry_Minutes='6'))
        self.refused('ORB_START_RANGE', **dict(orb, ORB_Start_Minute='1020', ORB_Range_Minutes='5'))
        self.passes(**dict(london, ORB_Start_Minute='1250', ORB_Range_Minutes='5', ORB_Entry_Minutes='5'))
        self.passes(**dict(london, ORB_Start_Minute='1020', ORB_Range_Minutes='5'))            # past NY's Lim
        self.refused('ORB_RANGE_MINUTES', **dict(london, ORB_Start_Minute='1255', ORB_Range_Minutes='5'))
        self.refused('ORB_START_RANGE', **dict(london, ORB_Start_Minute='1260', ORB_Range_Minutes='5'))
        self.refused('ORB_START_RANGE', **dict(orb, ORB_TF_='15', ORB_Start_Minute='575'))
        self.passes(**dict(orb, ORB_TF_='1', ORB_Start_Minute='575', ORB_Range_Minutes='7'))
        self.refused('ORB_RANGE_MINUTES', **dict(orb, ORB_TF_='15', ORB_Range_Minutes='20'))
        self.refused('ORB_START_RANGE', **dict(orb, ORB_Start_Minute='-5'))
        self.refused('ORB_TF_NOT_M1_TO_H1', **dict(orb, ORB_TF_='0'))                                     # TF_Cur
        self.refused('ORB_TF_NOT_M1_TO_H1', **dict(orb, ORB_TF_='1440'))
        # BRK_Bars bounds N-bar only (spec 3.1 A3); a disabled family's inputs are never read.
        self.passes(**dict(self.PDAY, BRK_Bars='1'))
        self.refused('BRK_BARS_RANGE', **dict(self.NBAR, BRK_Bars='1'))
        self.passes(**dict(self.S, BRK_Bars='1', BRK_Buffer_ATR='9.0', BRK_TF_='1440', ORB_TF_='240', ORB_Start_Minute='5000',
                           ORB_Range_Minutes='1', ORB_Entry_Minutes='-1', ORB_Buffer_ATR='-1.0', ORB_Min_Range_ATR='3.0',
                           ORB_Max_Range_ATR='1.0'))
        # A ladder reaching a refused value refuses and names it.
        self.passes(**dict(self.NBAR, BRK_Bars='20||2||1||500||Y'))
        self.assertIn('(reachable through the optimization range of BRK_Bars)',
                      self.refused('BRK_BARS_RANGE', **dict(self.NBAR, BRK_Bars='20||1||1||500||Y')))

    def test_schema_defaults_pass(self):
        for version, schema in SCHEMAS.items():
            with self.subTest(version=version):
                validate_strategy(defaults(schema), schema)

    def test_smart_rescue_with_fixed_lots_is_refused_with_the_ea_alert(self):
        message = self.refused('SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE', Mode_Bias_Exit='1', Mode_Lots='0', Risk='500.0')
        self.assertEqual(message, EA_INIT_CODE + ': the EA refuses this SET at initialization. Rule '
                         'SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE (GOAT V1.49.mq5:4947) fails for '
                         'Mode_Bias_Exit=1 (BiasExit_SmartRescue), Mode_Lots=0 (FixedLots). EA alert: '
                         '"Initialization Failed: Smart Rescue requires Risk per Sequence lot sizing and Risk > 0."')
        self.passes(Mode_Bias_Exit='1', Mode_Lots='2', Risk='500.0')
        self.passes(Mode_Bias_Exit='0', Mode_Lots='0')

    def test_the_single_trade_risk_per_sequence_refusal_is_decided_before_the_init_rules(self):
        # B49b (F6): the EA's OnInit refusal is listed NOT_PORTED because check_risk_sizing refuses the pair first.
        from studio_strategy_settings import RISK_SIZING_CODE
        for trades in ('1', '0', '4||1||1||6||Y'):
            with self.subTest(trades=trades), self.assertRaisesRegex(ValueError, '^' + RISK_SIZING_CODE + ': '):
                validate_strategy(self.values(Mode_Lots='2', Max_Seq_Trades=trades), self.schema)
        self.passes(Mode_Lots='2', Max_Seq_Trades='2')
        self.passes(Mode_Lots='0', Max_Seq_Trades='1')
        # B52 (Codex GOAT-EA#296 4502334956): a single sizes RiskperSeq from its own stop, so the EA refuses the pair for the
        # grid engine only, and check_risk_sizing passes a SET that reaches only Engine_Single (every hunt single).
        self.passes(Mode_Lots='2', Max_Seq_Trades='1', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0')
        with self.assertRaisesRegex(ValueError, '^' + RISK_SIZING_CODE + ': '):
            validate_strategy(self.values(Mode_Lots='2', Max_Seq_Trades='1', Engine_Mode='0'), self.schema)
        ea = [line for line in (REPO / EA_SOURCE).read_text(encoding='utf-8-sig').split('\n') if 'Max_Seq_Trades<=1' in line]
        self.assertEqual(len(ea), 1)
        self.assertIn('if(Engine_Mode!=Engine_Single && Mode_Lots == RiskperSeq && Max_Seq_Trades<=1)', ea[0])

    def test_rrr_derivations_feed_the_lp_tp_rule_as_in_the_ea(self):
        # SL/LP mode derives LP = SL*RRR = 0.5, which line 4993 zeroes; TP_Pips_ = TP_Pips*original LP = 0.
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
        self.assertIn('GRID_SIZE_TOO_SMALL (GOAT V1.49.mq5:4990) cannot be checked: the optimization ranges of Grid_Size '
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
                self.assertIn('(GOAT V1.49.mq5:4545,4562) fails for Mode_Download=%s (%s)' % (value, label), message)
                self.assertIn('EA alert: "News History download is not allowed in this mode / Bias History download is '
                              'not allowed in this mode"', message)
                self.assertIn('use Download_Disabled', message)
        self.passes(Mode_Download='0')


AI_ON = dict(Mode_Bias='2', Bias_Protocol='2')           # the header defaults: Bias_Opens + ControlTowerV2DemoRaw


class TesterInitRuleTests(RuleCase):
    """P-beta38-prepare-tester-ai-bias: GOAT V1.49.mq5:4446, refused in the tester only."""
    def refused_in_tester(self, **changes):
        with self.assertRaises(ValueError) as caught:
            check_tester_init(self.values(**changes), self.schema)
        message = str(caught.exception)
        self.assertTrue(message.startswith(TESTER_INIT_CODE + ': '), message)
        self.assertIn('Rule TESTER_CONTROL_TOWER_BIAS (GOAT V1.49.mq5:4446)', message)
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

    def test_the_new_york_clock_before_2007_is_refused_in_a_test_starting_then(self):
        # B50 (A0, GOAT-EA#273 P3): Clock_NewYork with a Fixed or EU DST server model applies the US DST rules of 2007 on.
        ny = dict(Mode_Bias='1', Clock_Mode='1')
        for model in ('1', '2'):
            with self.subTest(model=model):
                with self.assertRaises(ValueError) as caught:
                    check_tester_init(self.values(Server_Clock_Model=model, **ny), self.schema, from_date='2007.03.10')
                self.assertIn('Rule NY_CLOCK_TEST_BEFORE_2007 (GOAT V1.49.mq5:5053)', str(caught.exception))
                check_tester_init(self.values(Server_Clock_Model=model, **ny), self.schema, from_date='2007.03.11')
                check_tester_init(self.values(Server_Clock_Model=model, **ny), self.schema)   # no FromDate: not checked
        check_tester_init(self.values(Server_Clock_Model='0', **ny), self.schema, from_date='2005.01.03')   # NYClose
        check_tester_init(self.values(Mode_Bias='1', Server_Clock_Model='1'), self.schema, from_date='2005.01.03')   # server clock
        with self.assertRaises(ValueError):   # a Clock_Mode ladder reaching the NY clock
            check_tester_init(self.values(Server_Clock_Model='2', Mode_Bias='1', Clock_Mode='0||0||1||1||Y'), self.schema, from_date='2006.06.01')
        with self.assertRaisesRegex(ValueError, 'unreadable tester FromDate'):
            check_tester_init(self.values(**ny), self.schema, from_date='2007-03-11')
        check_tester_init(self.values(Mode_Bias='1'), SCHEMAS['1.48'], from_date='2005.01.03')   # V1.48: no B50 rule

    def test_the_opening_range_before_2007_is_refused_in_a_test_starting_then(self):
        # B54 (spec 4.4): the New York anchor under a fixed or EU DST model, the London anchor under every model.
        orb = dict(Mode_Bias='1', Engine_Mode='1', Single_SL_ATR='1.0', Mode_Bias_Exit='0', ORB_Mode='1')
        for model in ('1', '2'):
            with self.subTest(anchor='NY', model=model):
                with self.assertRaises(ValueError) as caught:
                    check_tester_init(self.values(Server_Clock_Model=model, **orb), self.schema, from_date='2007.03.10')
                self.assertIn('Rule ORB_NY_TEST_BEFORE_2007 (GOAT V1.49.mq5:5144)', str(caught.exception))
                check_tester_init(self.values(Server_Clock_Model=model, **orb), self.schema, from_date='2007.03.11')
        check_tester_init(self.values(Server_Clock_Model='0', **orb), self.schema, from_date='2005.01.03')   # NYClose
        for model in ('0', '1', '2'):
            with self.subTest(anchor='London', model=model):
                with self.assertRaises(ValueError) as caught:
                    check_tester_init(self.values(Server_Clock_Model=model, ORB_Clock='1', **orb), self.schema, from_date='2007.03.10')
                self.assertIn('Rule ORB_LONDON_TEST_BEFORE_2007 (GOAT V1.49.mq5:5145)', str(caught.exception))
                check_tester_init(self.values(Server_Clock_Model=model, ORB_Clock='1', **orb), self.schema, from_date='2007.03.11')
                check_tester_init(self.values(Server_Clock_Model=model, ORB_Clock='1', **orb), self.schema)   # no FromDate
        check_tester_init(self.values(Mode_Bias='1', Server_Clock_Model='1', ORB_Clock='1'), self.schema, from_date='2005.01.03')   # ORB off

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


class SeedLaneTesterTests(unittest.TestCase):
    """seed-validate and seed-prepare refuse a tester-refused job as prepare-batch refuses the member, before any seed
    is frozen (GOAT-EA#317: a plan that cannot be proved is refused before any seed runs)."""
    def setUp(self):
        import test_goat_studio as fixtures
        from types import SimpleNamespace
        from campaign_ledger import sha
        from studio_seed import SeedRunner
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        real = SCHEMAS['1.49']['inputs']
        self.c.schema['inputs'].update({name: dict(real[name]) for name in ('Mode_Bias', 'Bias_Protocol', 'Clock_Mode', 'Server_Clock_Model')})
        self.c.store.input_schema = self.c.schema
        self.c.store.input_schema_hash = sha(self.c.schema)
        self.root = self.fixture.root
        self.runner = SeedRunner(self.c, process=SimpleNamespace(inspect=lambda: None))

    def plan(self, name, *jobs, **tester):
        """One seed job per (Mode_Bias, Bias_Protocol, Clock_Mode, Server_Clock_Model)."""
        rows = []
        for index, values in enumerate(jobs):
            source = self.root / ('%s-%d.set' % (name, index))
            source.write_bytes(('EA_Desc=Seed %d\r\nLots=0.1||0.1||0.1||0.3||Y\r\nMode_Bias=%s\r\nBias_Protocol=%s\r\nClock_Mode=%s\r\n'
                                'Server_Clock_Model=%s\r\n' % ((index,) + values)).encode('utf-16'))
            rows.append(dict(set_path=str(source), frame_target=2,
                             tester=self.fixture.tester | {'ForwardMode': 0, 'ForwardDate': '', 'Symbol': 'SYM%d' % index} | tester))
        return dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=30, cutoff=dict(min_fitness=0, min_trades=1), jobs=rows)

    def test_a_refused_in_tester_job_fails_at_seed_validate_and_seed_prepare_and_nothing_is_prepared(self):
        plan = self.plan('refused', ('1', '2', '0', '0'), ('2', '2', '0', '0'))
        refusal = ('^' + TESTER_INIT_CODE + r': seed job 2 \(.*refused-1\.set\): the EA refuses this SET in the strategy tester.*'
                   'TESTER_CONTROL_TOWER_BIAS')
        with self.assertRaisesRegex(ValueError, refusal):
            self.runner.validate(plan)
        with self.assertRaisesRegex(ValueError, refusal):
            self.runner.prepare('seed-refused', plan)
        self.assertFalse((self.c.root / 'seeds' / 'seed-refused').exists())
        self.assertFalse((Path(self.c.install['terminal_data_root']) / 'config/GOATStudio/Seeds').exists())
        # A ladder that reaches the refused value is refused too, as for a Prove member.
        with self.assertRaisesRegex(ValueError, '^' + TESTER_INIT_CODE + ': seed job 1 '):
            self.runner.validate(self.plan('laddered', ('1||1||1||2||Y', '1', '0', '0')))

    def test_ai_off_and_legacy_recorded_jobs_validate(self):
        result = self.runner.validate(self.plan('allowed', ('1', '2', '0', '0'), ('2', '0', '0', '0')))
        self.assertEqual((result['valid'], result['job_count'], result['writes']), (True, 2, False))

    def test_the_rule_that_reads_the_test_start_uses_the_seed_jobs_own_from_date(self):
        # The New York clock under a fixed server model needs a test start on or after 2007.03.11 (NY_CLOCK_TEST_BEFORE_2007).
        ny = ('1', '2', '1', '1')
        early = dict(FromDate='2006.02.01', ToDate='2006.09.01')
        with self.assertRaisesRegex(ValueError, '^' + TESTER_INIT_CODE + r': seed job 1 \(.*early-0\.set\): .*NY_CLOCK_TEST_BEFORE_2007'):
            self.runner.validate(self.plan('early', ny, **early))
        self.assertTrue(self.runner.validate(self.plan('late', ny))['valid'])                      # the fixture's 2026 window
        self.assertTrue(self.runner.validate(self.plan('server-clock', ('1', '2', '0', '1'), **early))['valid'])


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
        # B50 (A0) added eleven: seven input refusals (ported), the pre-2007 test start of the New York clock (a tester
        # rule, GOAT-EA#273 P3), the netting account and two indicator handles (not ported).
        # B51 (beta-1a) added six: five input refusals (ported) and the benchmark on a live chart (not ported); beta-1b
        # three input refusals (ported). Section 8.3-8.4 added seven: six input refusals (ported) and the demo gate (not ported).
        # B49b (F7 SIG-01) adds six indicator-handle INIT_FAILED returns (NOT_PORTED: indicator runtime).
        # B49b (F6) adds the RiskperSeq single-trade INIT_PARAMETERS_INCORRECT (NOT_PORTED: check_risk_sizing decides it).
        # B49b (F1 full) adds the live manage-only INIT_FAILED after adoption (NOT_PORTED: licence and expiry, live only).
        # The merged line (B50 + B51 with B49b) carries both sets. B52 (its review) adds two: the benchmark under the
        # first-order gate (ported) and the New York clock on a live chart (not ported: run context).
        # B54 (spec 4.6) adds 19: 18 INIT_PARAMETERS_INCORRECT (13 ported; the two pre-2007 test starts, tester rules; three
        # that read the chart's timeframe, not ported) and 1 INIT_FAILED (ORB on a live chart, not ported). The not-built
        # INIT_FAILED lines went with their terms: BRK_NBar's and BRK_PriorDay's in PR A, ORB_Breakout's in PR B.
        self.assertEqual((len(self.returns), len(self.removals), len(self.sites)), (107, 8, 111))
        self.assertEqual(list(self.returns.values()).count('INIT_PARAMETERS_INCORRECT'), 68)
        self.assertEqual((sum(len(r['lines']) for r in EA_INIT_RULES), sum(len(r['lines']) for r in TESTER_INIT_RULES),
                          sum(len(e['lines']) for e in NOT_PORTED)), (57, 4, 50))
        # The removal-only paths (no INIT_* return on the line): name mismatch, the two download removals, and
        # the unreachable removal after the dashboard-cancel return.
        self.assertEqual(sorted(self.removals - set(self.returns)), [4434, 4545, 4562, 4837])

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
