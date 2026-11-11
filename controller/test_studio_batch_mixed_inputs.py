"""prepare-batch refuses a batch whose members do not all state the same inputs (BATCH_MIXED_INPUTS, GOAT-EA#315).

Hunt round 13a: after the first member whose SET set ``Ledger_Mode=1``, every later member of the batch ran with
``Ledger_Mode=1`` although its own SET omitted it. Only a batch's first member starts from a complete controller
config; the EA launches the others from their own SET bytes. Until the EA names every declared input itself, a mixed
batch is refused before anything is staged. The controller, the plan reader and prepare-batch here are real."""
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from campaign_ledger import sha
import studio_batch
from studio_batch import BATCH_MIXED_INPUTS, check_member_inputs, prepare_batch
import studio_installed_build
from studio_optimization_inputs import self_named_inputs
from studio_refusal import Refusal
from studio_strategy_settings import APPENDED_INPUTS, appended_default, read_values
import test_goat_studio as goat_studio_tests   # its PortableControllerTests fixture (a module attribute, so not collected here)
from test_studio_pinned_tester_inputs import compass_like_template

ROOT = Path(__file__).resolve().parent
REAL = json.loads((ROOT / 'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
# What the three local D1 designs of round 13a state and the other members of their batches omit.
D1_INPUTS = ('Clock_Mode', 'Engine_Mode', 'Ledger_Mode', 'NY_Session', 'Random_Direction', 'Server_Clock_Model',
             'Server_UTC_Offset', 'Single_Flat_Only')
AXIS = 'Random_Seed'                       # an appended optimization axis: the EA names it for a member that omits it
BASE = 'EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'


class PrepareBatchCase(unittest.TestCase):
    def setUp(self):
        self.fixture = goat_studio_tests.PortableControllerTests('test_prepare_exact_inputs_server_version_ninth_setting')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        c = self.fixture.bound()
        for name in D1_INPUTS + (AXIS,):
            c.schema['inputs'][name] = REAL['inputs'][name]          # this build declares them, as B54 does
        c.store.input_schema = c.schema; c.store.input_schema_hash = sha(c.schema)
        self.fixture.grant(c)
        self.c, self.root = c, self.fixture.root

    def plan(self, *sets):
        """One member per SET text (the fixture's two lines plus ``more``), each on its own symbol."""
        members = []
        for index, more in enumerate(sets):
            path = self.root / ('member-%d.set' % index)
            path.write_bytes((BASE + ''.join(line + '\r\n' for line in more)).encode('utf-16'))
            members.append(dict(set_path=str(path), tester=self.fixture.tester | {'Symbol': 'SYMBOL%d.customer' % index}))
        return dict(schema_version=1, export=self.fixture.exports, members=members)

    def prepare(self, batch_id, *sets):
        file = self.root / (batch_id + '.json')
        file.write_text(json.dumps(self.plan(*sets)), encoding='utf-8')
        return prepare_batch(self.c, batch_id, file)

    def refused(self, batch_id, *sets):
        queued = [job['job_id'] for job in self.c.state()['queue']]
        with self.assertRaises(Refusal) as caught:
            self.prepare(batch_id, *sets)
        self.assertEqual(caught.exception.code, BATCH_MIXED_INPUTS)
        # Refused before anything is staged: no package, no source record, no request, no new queue row.
        self.assertFalse((self.c.root / 'packages' / batch_id).exists())
        self.assertFalse((self.c.root / 'packages' / (batch_id + '.source.json')).exists())
        self.assertFalse((self.c.root / 'requests' / (batch_id + '-batch.json')).exists())
        self.assertEqual([job['job_id'] for job in self.c.state()['queue']], queued)
        return caught.exception


class MixedInputRefusalTests(PrepareBatchCase):
    def test_a_member_that_sets_ledger_mode_before_one_that_omits_it_is_refused_and_nothing_is_staged(self):
        error = self.refused('mixed', ['Ledger_Mode=1'], [])
        self.assertEqual(error.fields['mixed_inputs'], [dict(input='Ledger_Mode', stated_by=[0], omitted_by=[1])])
        self.assertEqual((error.fields['member_count'], error.fields['installed_build'], error.fields['issue']), (2, None, 'GOAT-EA#315'))
        self.assertEqual(str(error), 'Nothing was prepared: the members of this batch do not all state the same inputs. After the first '
                                     'member, MT5 runs an input a member\'s SET leaves out at the value the member before it used, not at '
                                     'its default. Ledger_Mode is stated by member 0 and left out by member 1. Run the members that state '
                                     'it as their own batch, or state it in every member\'s SET, then prepare again. Members are numbered '
                                     'from 0, as batch-status lists them.')
        # The other order is refused too: nothing says which member a later resume or reorder runs first.
        error = self.refused('mixed-reversed', [], ['Ledger_Mode=1'])
        self.assertEqual(error.fields['mixed_inputs'], [dict(input='Ledger_Mode', stated_by=[1], omitted_by=[0])])

    def test_round_13a_three_d1_designs_among_members_that_omit_their_eight_inputs_are_refused(self):
        d1 = ['Clock_Mode=0', 'Engine_Mode=0', 'Ledger_Mode=1', 'NY_Session=09:30-16:00', 'Random_Direction=false',
              'Server_Clock_Model=0', 'Server_UTC_Offset=2', 'Single_Flat_Only=false']
        error = self.refused('round-13a', [], [], d1, [], d1, [], d1, [])
        self.assertEqual([row['input'] for row in error.fields['mixed_inputs']], sorted(D1_INPUTS))
        self.assertTrue(all((row['stated_by'], row['omitted_by']) == ([2, 4, 6], [0, 1, 3, 5, 7]) for row in error.fields['mixed_inputs']))
        self.assertIn('Clock_Mode, Engine_Mode, Ledger_Mode, NY_Session, Random_Direction, Server_Clock_Model, Server_UTC_Offset and '
                      'Single_Flat_Only are stated by members 2, 4 and 6 and left out by members 0, 1, 3, 5 and 7. Run the members that '
                      'state them as their own batch, or state them in every member\'s SET', str(error))
        # The three designs as their own batch, and the other five as theirs, both prepare.
        self.assertEqual(self.prepare('round-13a-d1', d1, d1, d1)['member_count'], 3)
        self.assertEqual(self.prepare('round-13a-rest', [], [], [], [], [])['member_count'], 5)

    def test_members_that_all_omit_it_or_all_state_it_at_any_value_are_prepared(self):
        self.assertEqual(self.prepare('all-omit', [], [])['member_count'], 2)
        self.assertEqual(self.prepare('all-state-same', ['Ledger_Mode=1'], ['Ledger_Mode=1'])['member_count'], 2)
        self.assertEqual(self.prepare('all-state-differ', ['Ledger_Mode=1'], ['Ledger_Mode=0'])['member_count'], 2)

    def test_a_single_member_batch_is_prepared_whatever_it_states(self):
        self.assertEqual(self.prepare('one', ['Ledger_Mode=1'])['member_count'], 1)
        self.assertEqual(self.prepare('one-plain', [])['member_count'], 1)

    def test_an_appended_optimization_axis_one_member_omits_is_not_mixed(self):
        self.assertIn(AXIS, self_named_inputs(self.c.schema))
        self.assertEqual(self.prepare('axis', [AXIS + '=1||1||0||1||N'], [])['member_count'], 2)
        # ... and it does not hide a mixed input next to it.
        error = self.refused('axis-and-ledger', [AXIS + '=1||1||0||1||N', 'Ledger_Mode=1'], [])
        self.assertEqual([row['input'] for row in error.fields['mixed_inputs']], ['Ledger_Mode'])

    def test_a_build_whose_ea_names_every_input_is_not_refused_and_any_other_build_is(self):
        pinned = patch.dict(studio_installed_build.PINNED_BUILDS, {self.c.install['ea_sha256']: 'V1.49-BETA17-55'})
        pinned.start(); self.addCleanup(pinned.stop)
        # The installed build is B55, but nothing says B55 names its own inputs: refused, and the refusal names the build.
        self.assertEqual(self.refused('b55-unlisted', ['Ledger_Mode=1'], []).fields['installed_build'], 'V1.49-BETA17-55')
        with patch.object(studio_batch, 'BUILDS_NAMING_EVERY_INPUT', frozenset({'V1.49-BETA17-55'})):
            self.assertEqual(self.prepare('b55-listed', ['Ledger_Mode=1'], [])['member_count'], 2)
        # Another build is listed, not the installed one: refused.
        with patch.object(studio_batch, 'BUILDS_NAMING_EVERY_INPUT', frozenset({'V1.49-BETA17-56'})):
            self.refused('b56-listed', ['Ledger_Mode=1'], [])
        self.assertEqual(studio_batch.BUILDS_NAMING_EVERY_INPUT, frozenset())          # none today

    def test_a_batch_prepared_before_is_still_reused(self):
        first = self.prepare('same', ['Ledger_Mode=1'], ['Ledger_Mode=1'])
        self.assertTrue(self.prepare('same', ['Ledger_Mode=1'], ['Ledger_Mode=1'])['reused'])
        self.assertEqual(first['member_count'], 2)


class Round13aCompositionTests(unittest.TestCase):
    """Claude-Mac goatai#2750 6792752258: the refusal is tested on round 13a's real p1 composition (it must refuse) and
    on a uniform batch (it must pass). fixtures/round13a-t3-prove-p1-member-inputs.json holds the input names each of
    the 28 members of hunt-t3-depth-prove-13a-p1 states in its own SET (read through the read-only gate; names only),
    its symbol and its timeframe. The values here are the contract template's and each appended input's default,
    except Ledger_Mode=1 in the three members that state it: the check reads names, never values."""

    def setUp(self):
        self.fixture = goat_studio_tests.PortableControllerTests('test_prepare_exact_inputs_server_version_ninth_setting')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        c = self.fixture.bound()
        c.schema = REAL                                                  # the build's real contract: B54 declares all 159
        c.policy = json.loads((ROOT / 'contracts/v149/dependencies.json').read_text(encoding='utf-8-sig'))
        c.store.input_schema = c.schema; c.store.input_schema_hash = sha(c.schema); c.store.dependency_policy = c.policy
        self.fixture.grant(c)
        self.c, self.root = c, self.fixture.root
        self.composition = json.loads((ROOT / 'fixtures/round13a-t3-prove-p1-member-inputs.json').read_text(encoding='utf-8'))
        self.template = read_values(('\r\n'.join(compass_like_template(REAL).splitlines()) + '\r\n').encode('utf-16'))

    def plan(self, members):
        rows = []
        for member in members:
            values = {}
            for name in self.composition['name_lists'][member['names']]:
                values[name] = self.template[name] if name in self.template else appended_default(REAL['inputs'][name])
            values['EA_Desc'] = 'round 13a p1 member %d' % member['index']
            if 'Ledger_Mode' in values:
                values['Ledger_Mode'] = '1'                              # what members 17, 20 and 25 state
            path = self.root / ('round13a-%02d.set' % member['index'])
            path.write_bytes(''.join('%s=%s\r\n' % item for item in values.items()).encode('utf-16'))
            rows.append(dict(set_path=str(path), tester=self.fixture.tester | dict(Symbol=member['symbol'], Period=member['period'])))
        return dict(schema_version=1, export=self.fixture.exports, members=rows)

    def prepare(self, batch_id, members):
        file = self.root / (batch_id + '.json')
        file.write_text(json.dumps(self.plan(members)), encoding='utf-8')
        return prepare_batch(self.c, batch_id, file)

    def test_the_fixture_is_the_batch_the_close_recorded(self):
        members = self.composition['members']
        self.assertEqual((self.composition['batch'], len(members), [m['index'] for m in members]), ('hunt-t3-depth-prove-13a-p1', 28, list(range(28))))
        self.assertEqual([m['index'] for m in members if m['names'] == 'd1'], [17, 20, 25])
        plain, d1 = (self.composition['name_lists'][key] for key in ('plain', 'd1'))
        self.assertEqual((len(plain), len(d1), sorted(set(d1) - set(plain)), set(plain) - set(d1)), (139, 147, sorted(D1_INPUTS), set()))
        self.assertTrue(set(d1) <= set(REAL['inputs']))                 # every stated name is one B54 declares
        self.assertEqual(set(REAL['inputs']) - set(plain), set(APPENDED_INPUTS) - set(self_named_inputs(REAL)))

    def test_round_13a_p1_as_it_was_composed_is_refused_naming_the_eight_inputs_and_members_17_20_and_25(self):
        with self.assertRaises(Refusal) as caught:
            self.prepare('hunt-t3-depth-prove-13a-p1', self.composition['members'])
        error = caught.exception
        self.assertEqual(error.code, BATCH_MIXED_INPUTS)
        others = [index for index in range(28) if index not in (17, 20, 25)]
        self.assertEqual(error.fields['mixed_inputs'], [dict(input=name, stated_by=[17, 20, 25], omitted_by=others) for name in sorted(D1_INPUTS)])
        self.assertEqual(error.fields['member_count'], 28)
        self.assertIn('Clock_Mode, Engine_Mode, Ledger_Mode, NY_Session, Random_Direction, Server_Clock_Model, Server_UTC_Offset and '
                      'Single_Flat_Only are stated by members 17, 20 and 25 and left out by members 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 '
                      'and 13 more.', str(error))
        self.assertFalse((self.c.root / 'packages' / 'hunt-t3-depth-prove-13a-p1').exists())      # nothing was staged
        self.assertEqual(self.c.state()['queue'], [])

    def test_the_same_plan_without_those_three_members_is_uniform_and_is_prepared(self):
        uniform = [m for m in self.composition['members'] if m['index'] not in (17, 20, 25)]
        result = self.prepare('hunt-t3-depth-prove-13a-p1-uniform', uniform)
        self.assertEqual((result['member_count'], result['native_started']), (25, False))
        self.assertEqual([job['job_id'] for job in self.c.state()['queue']], ['hunt-t3-depth-prove-13a-p1-uniform'])
        # The three D1 designs are uniform among themselves, so they prepare as their own batch.
        d1 = [m for m in self.composition['members'] if m['index'] in (17, 20, 25)]
        self.assertEqual(self.prepare('hunt-t3-depth-prove-13a-p1-d1', d1)['member_count'], 3)


class RealContractTests(unittest.TestCase):
    """The check on the real v149 contract: which inputs can be mixed, and that the exempt set is the EA's own."""

    def setUp(self):
        self.schema = REAL
        full = read_values(('\r\n'.join(compass_like_template(self.schema).splitlines()) + '\r\n').encode('utf-16'))
        self.old = {name: value for name, value in full.items() if name not in APPENDED_INPUTS}     # a SET from before B49a
        self.install = dict(ea_sha256='0' * 64)

    def member(self, **more):
        return dict(strategy=dict(values=dict(self.old, **more)))

    def mixed(self, *members):
        try:
            check_member_inputs(list(members), self.schema, self.install)
        except Refusal as error:
            return [row['input'] for row in error.fields['mixed_inputs']]
        return []

    def test_every_appended_input_the_ea_does_not_name_is_refused_when_mixed_and_every_axis_it_names_is_not(self):
        named = set(self_named_inputs(self.schema))
        self.assertEqual(len(named), 25)
        for name in APPENDED_INPUTS:
            value = '1' if self.schema['inputs'][name]['type'] != 'string' else '09:30-16:00'
            found = self.mixed(self.member(**{name: value}), self.member())
            self.assertEqual(found, [] if name in named else [name], name)
        self.assertEqual(sorted(set(APPENDED_INPUTS) - named),
                         sorted(D1_INPUTS + ('Fix_MoneyVolume', 'Gate_Recheck', 'Fix_ClosePath', 'Max_Spread_Points', 'Min_Margin_Level_PC',
                                             'Fix_Clock', 'Fix_FeedGuard', 'Diag_TickTiming', 'Fix_TickLoad', 'BRK_Mode', 'ORB_Mode', 'ORB_Clock')))
        # EA_Desc differs in every member and is never mixed; one member, or none, always passes.
        self.assertEqual(self.mixed(self.member(EA_Desc='one', Ledger_Mode='1'), self.member(EA_Desc='two', Ledger_Mode='1')), [])
        self.assertEqual(self.mixed(self.member(Ledger_Mode='1')), [])
        self.assertEqual(self.mixed(), [])

    def test_the_exempt_set_is_exactly_what_the_ea_writes_for_a_member_that_omits_it(self):
        # GoatStudioExplicitOptimizationInputs (GOATOptimizationInputs.mqh): every name of GoatStudioOptimizationNames that
        # has a GoatStudioAppendedDefault and is not in the source is written at that default, fixed.
        writer = (ROOT.parent / 'GOATOptimizationInputs.mqh').read_text(encoding='utf-8-sig')
        self.assertIn('string b50_names[];StringSplit(GoatStudioOptimizationNames(),\'|\',b50_names);', writer)
        self.assertIn('string b50_default=GoatStudioAppendedDefault(b50_names[n]);', writer)
        self.assertIn('if(b50_default=="" || StringFind("\\n"+source,"\\n"+b50_names[n]+"=")>=0) continue;', writer)
        types = (ROOT.parent / 'GOATStudioSettingTypes.mqh').read_text(encoding='utf-8-sig')
        body = types.split('string GoatStudioOptimizationNames()', 1)[1].split('bool GoatStudioSettingOptimizable', 1)[0]
        axes = {name for text in re.findall(r'"([^"]*)"', body) for name in text.split('|') if name}
        defaults = types.split('string GoatStudioAppendedDefault(const string key)', 1)[1]
        with_default = {name for listed in re.findall(r'StringFind\("\|([^"]+)\|","\|"\+key\+"\|"\)>=0\) return "[^"]*";', defaults)
                        for name in listed.split('|')}
        with_default |= set(re.findall(r'if\(key=="([A-Za-z0-9_]+)"\) return "[^"]*";', defaults))
        self.assertEqual(axes & with_default, set(self_named_inputs(self.schema)))


if __name__ == '__main__':
    unittest.main()
