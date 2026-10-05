"""Blank starter SETs (beta.20 "build a new strategy from scratch"): generated from the installed schema,
accepted by validate-set, create-only, outside the catalog, and recorded as a build-set parent."""
from contextlib import redirect_stdout
import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
import tempfile
import unittest

from campaign_ledger import sha
from studio_installation import contracts
from studio_research_authority import LOCAL_FILE_OPERATIONS, OPERATIONS, READ_OPERATIONS, authority, operation
from studio_strategy_settings import read_values
from studio_template_tools import (RISK_SIZING_CODE, RISK_SIZING_MESSAGE, STARTER_SHAPES, build_set, schema_default,
                                   signal_modes, starter_set, validate_set)
from unittest.mock import patch
import test_demo_seed_agent as seed_agent_fixture
import test_goat_studio as goat_fixture
import test_studio_agent_setup as agent_fixture

CONTRACTS = {version: contracts(version) for version in ('1.48', '1.49')}


def spec(changes, rationale=None, **notes):
    return dict(ea_desc=notes.pop('ea_desc', 'My EURUSD pullback'), changes=changes,
                rationale=rationale or {name: 'Needed by the idea: ' + name for name in changes},
                summary='Untested new idea built from a blank starter.',
                entry_logic=notes.pop('entry_logic', 'RSI overbought/oversold on M15 decides the entry; no other filter.'),
                ladder_exits='Exits as in the starter; reviewed against the changed entry.',
                intended_role='Exploration candidate; no performance claim before testing.')


class StarterSetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def starter(self, shape='single', version='1.49', name=None, **kw):
        schema, policy = CONTRACTS[version]
        return starter_set(shape, self.root / (name or f'{version}-{shape}.set'), schema, policy,
                           controller_version='test', ea_version=version, **kw)

    def test_both_shapes_validate_against_both_installed_schemas(self):
        for version, (schema, policy) in CONTRACTS.items():
            for shape in STARTER_SHAPES:
                with self.subTest(version=version, shape=shape):
                    result = self.starter(shape, version)
                    path = Path(result['output']['path']); raw = path.read_bytes()
                    self.assertTrue(raw.startswith(b'\xff\xfe'))
                    text = raw[2:].decode('utf-16-le')
                    self.assertNotIn('\n', text.replace('\r\n', '')); self.assertTrue(text.endswith('\r\n'))
                    report = validate_set(path, schema, policy)
                    self.assertEqual((report['kind'], report['active_axes'], report['input_count']),
                                     ('fixed_settings', {}, len(schema['inputs'])))
                    self.assertEqual(report['dependency_audit']['findings'], [])
                    with self.assertRaisesRegex(ValueError, 'No enabled optimization axes'):
                        validate_set(path, schema, policy, require_optimization=True)
                    self.assertEqual(result['output']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_values_are_schema_defaults_except_the_documented_fixes(self):
        for version, (schema, policy) in CONTRACTS.items():
            for shape in STARTER_SHAPES:
                with self.subTest(version=version, shape=shape):
                    result = self.starter(shape, version)
                    values = read_values(Path(result['output']['path']).read_bytes())
                    defaults = {n: schema_default(n, d, schema['defines']) for n, d in schema['inputs'].items()}
                    fixed = {f['input']: f['value'] for f in result['fixes']}
                    self.assertEqual({n for n in values if values[n] != defaults[n]}, set(fixed))
                    self.assertEqual({n: values[n] for n in fixed}, fixed)
                    for mode, disabled in signal_modes(policy).items():
                        self.assertEqual(values[mode], disabled, mode)
                    self.assertTrue(all(values[n] == 'false' for n in values if n.endswith('_MustCheck')))
                    self.assertEqual((values['Mode_Bias'], values['Mode_News']), ('1', '1'))   # Bias_Disabled, News_Disabled
                    self.assertTrue(all(values[n] == defaults[n] for n in values if n.startswith('Grid_')))
                    self.assertEqual(values['CloseAtMaxLevels'], 'true')
                    if shape == 'single':
                        self.assertEqual((values['EA_Desc'], values['Max_Seq_Trades'], values['Mode_Lots']),
                                         ('Starter Single Trade', '1', '0'))   # FixedLots: RiskperSeq needs >1 trade
                    else:
                        self.assertEqual((values['EA_Desc'], values['Max_Seq_Trades'], values['Mode_Lots'],
                                          values['Sequence_MLPS_Hard_Close']), ('Starter Sequence', '5', '2', 'true'))
                        self.assertGreater(int(values['Max_Seq_Trades']), 1)

    def test_receipt_binds_schema_versions_shape_and_hash(self):
        result = self.starter('sequence')
        receipt = Path(result['receipt_path'])
        self.assertEqual(receipt.name, '1.49-sequence.starter.json')
        stored = json.loads(receipt.read_text(encoding='utf-8'))
        schema, _ = CONTRACTS['1.49']
        self.assertEqual((stored['kind'], stored['shape'], stored['parent_label'], stored['status']),
                         ('goat_starter_set', 'sequence', 'starter:sequence', 'untested_starter'))
        self.assertEqual((stored['schema_hash'], stored['controller_version'], stored['ea_version']), (sha(schema), 'test', '1.49'))
        self.assertEqual(stored['output']['sha256'], hashlib.sha256(Path(result['output']['path']).read_bytes()).hexdigest())
        self.assertEqual(result['receipt_sha256'], hashlib.sha256(receipt.read_bytes()).hexdigest())
        self.assertEqual((stored['entry_filters_enabled'], stored['active_axes'], stored['execution_ready']), ([], {}, False))
        self.assertIn('zero evidence', stored['performance_evidence'])

    def test_generated_from_the_installed_schema_not_a_static_file(self):
        schema, policy = copy.deepcopy(CONTRACTS['1.49'][0]), CONTRACTS['1.49'][1]
        schema['inputs']['Grid_Size']['default_expression'] = '12.5'
        schema['inputs']['New_Input'] = dict(type='int', declaration='input', default_expression='7', optimizable=True,
                                             enum_choices=None, dependency_audited=False)
        result = starter_set('single', self.root / 'drift.set', schema, policy, controller_version='t', ea_version='1.49')
        values = read_values(Path(result['output']['path']).read_bytes())
        self.assertEqual((values['Grid_Size'], values['New_Input']), ('12.5', '7'))
        self.assertEqual(list(values), list(schema['inputs']))                       # declaration order

    def test_unresolvable_default_fails_closed_without_writing(self):
        schema, policy = copy.deepcopy(CONTRACTS['1.49'][0]), CONTRACTS['1.49'][1]
        schema['inputs']['Grid_Size']['default_expression'] = 'Grid_Min*2'
        with self.assertRaisesRegex(ValueError, 'not a plain literal.*Grid_Size'):
            starter_set('single', self.root / 'bad.set', schema, policy, controller_version='t', ea_version='1.49')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_never_overwrites_and_refuses_catalog_and_bad_paths(self):
        target = self.root / 'mine.set'; target.write_bytes(b'user bytes')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.starter(name='mine.set')
        self.assertEqual(target.read_bytes(), b'user bytes')
        (self.root / 'other.starter.json').write_text('user receipt')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.starter(name='other.set')
        self.assertFalse((self.root / 'other.set').exists())
        catalog = self.root / 'catalog'; catalog.mkdir()
        with self.assertRaisesRegex(ValueError, 'publisher catalog'):
            self.starter(name='catalog/x.set', forbidden_roots=[catalog])
        self.assertEqual(list(catalog.iterdir()), [])
        with self.assertRaisesRegex(ValueError, '.set extension'):
            self.starter(name='x.txt')
        with self.assertRaisesRegex(ValueError, 'single or sequence'):
            self.starter('grid')
        self.starter(name='again.set')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.starter(name='again.set')

    def test_classified_as_local_file_operation_not_a_native_one(self):
        # starter-set/build-set write create-only local files; research-launch (PR E) only replaces research-launch.json
        self.assertEqual(LOCAL_FILE_OPERATIONS, {'starter-set', 'build-set', 'research-launch'})
        self.assertTrue(LOCAL_FILE_OPERATIONS <= READ_OPERATIONS)
        self.assertTrue(LOCAL_FILE_OPERATIONS <= OPERATIONS)


class BuildFromStarterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.schema, self.policy = CONTRACTS['1.49']

    def starter(self, shape):
        return starter_set(shape, self.root / f'{shape}.set', self.schema, self.policy, controller_version='t', ea_version='1.49')

    def build(self, source, changes, output='variant.set', **notes):
        return build_set(source, self.root / output, spec(changes, **notes), self.schema, self.policy,
                         controller_version='t', ea_version='1.49')

    def test_starter_is_a_valid_build_source_and_parent_is_recorded(self):
        for shape in STARTER_SHAPES:
            with self.subTest(shape=shape):
                starter = self.starter(shape)
                changes = {'RSI_Mode': '1', 'RSI_TF_': '15', 'RSI_Period': '14||7||7||21||Y'}
                if shape == 'sequence': changes['Risk'] = '100.0'                  # the user's own amount
                result = self.build(starter['output']['path'], changes, output=f'{shape}-variant.set')
                self.assertEqual(result['parent'], 'starter:' + shape)
                self.assertEqual(result['starter']['receipt_sha256'], starter['receipt_sha256'])
                self.assertEqual(result['starter']['starter_sha256'], starter['output']['sha256'])
                self.assertEqual(result['starter']['entry_filters_enabled'], ['RSI_Mode'])
                self.assertEqual(result['starter']['warnings'], [])
                self.assertEqual(result['validation']['active_axes'], {'RSI_Period': 3})
                stored = json.loads(Path(result['receipt_path']).read_text(encoding='utf-8'))
                self.assertEqual((stored['parent'], stored['starter']['label']), ('starter:' + shape, 'starter:' + shape))
                notes = Path(result['support_path']).read_text(encoding='utf-8')
                self.assertIn('zero evidence', notes); self.assertNotIn('source-reference evidence only', notes)
                self.assertEqual(hashlib.sha256(Path(starter['output']['path']).read_bytes()).hexdigest(),
                                 starter['output']['sha256'])                       # the starter itself is untouched

    def test_build_from_a_starter_still_needs_an_active_axis(self):
        starter = self.starter('single')
        with self.assertRaisesRegex(ValueError, 'No enabled optimization axes'):
            self.build(starter['output']['path'], {'RSI_Mode': '1'})
        self.assertFalse((self.root / 'variant.set').exists())

    def test_ordinary_sources_record_a_set_parent(self):
        starter = self.starter('single')
        first = self.build(starter['output']['path'], {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        second = self.build(first['output']['path'], {'RSI_Level': '75||70||5||80||Y'}, output='second.set')
        self.assertEqual(second['parent'], 'set'); self.assertNotIn('starter', second)

    def test_changed_starter_bytes_or_other_schema_are_refused(self):
        starter = self.starter('single'); path = Path(starter['output']['path'])
        text = path.read_bytes().decode('utf-16').replace('TP_Pips=2.0', 'TP_Pips=3.0')
        path.write_bytes(text.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'Starter SET changed'):
            self.build(path, {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        other = self.starter('sequence')
        receipt = Path(other['receipt_path']); stored = json.loads(receipt.read_text(encoding='utf-8'))
        receipt.write_text(json.dumps(stored | {'schema_hash': '0' * 64}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different installed input schema'):
            self.build(other['output']['path'], {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})

    def test_risk_sizing_with_a_single_trade_is_refused(self):
        sequence = self.starter('sequence')
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.build(sequence['output']['path'], {'Max_Seq_Trades': '1', 'Risk': '100.0', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.build(sequence['output']['path'], {'Max_Seq_Trades': '3||1||1||5||Y', 'Risk': '100.0'})
        single = self.starter('single')
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.build(single['output']['path'], {'Mode_Lots': '2', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if 'variant' in p.name), [])

    # ---- Claude-Mac's review of f584b85a: each bypass of the max-lot guard, now refused for every SET
    def test_bypass_1_dormant_mode_lots_tuple_is_read_as_mt5_reads_it(self):
        single = self.starter('single')
        for encoded in ('2||0||1||2||N', '2||0||0||0||N'):
            with self.subTest(encoded=encoded), self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
                self.build(single['output']['path'], {'Mode_Lots': encoded, 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        self.assertFalse((self.root / 'variant.set').exists())

    def test_bypass_2_rebuilding_a_variant_parent_set_is_refused(self):
        sequence = self.starter('sequence')
        first = self.build(sequence['output']['path'], {'Risk': '100.0', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.build(first['output']['path'], {'Max_Seq_Trades': '1'}, output='second.set')
        self.assertFalse((self.root / 'second.set').exists())

    def test_bypass_3_deleted_or_moved_receipt_is_refused(self):
        single = self.starter('single'); path = Path(single['output']['path'])
        Path(single['receipt_path']).unlink()
        with self.assertRaisesRegex(ValueError, 'without its .starter.json receipt'):
            self.build(path, {'Mode_Lots': '2', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        moved = self.root / 'elsewhere'; moved.mkdir(); (moved / 'copy.set').write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'without its .starter.json receipt'):
            self.build(moved / 'copy.set', {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        # An edited copy that no longer looks like a starter is an ordinary SET: the unconditional rule still holds.
        text = path.read_bytes().decode('utf-16').replace('; GOAT starter SET', '; my copy').replace('Mode_Lots=0', 'Mode_Lots=2')
        (moved / 'edited.set').write_bytes(text.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            validate_set(moved / 'edited.set', self.schema, self.policy)
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.build(moved / 'edited.set', {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})

    def test_bypass_4_max_seq_trades_zero_or_ladders_reaching_one(self):
        sequence = self.starter('sequence')
        for encoded in ('0', '4||0||1||8||Y', '3||1||1||5||Y', '1||2||1||5||Y', '1||2||1||5||N', '-3'):
            with self.subTest(encoded=encoded), self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
                self.build(sequence['output']['path'], {'Max_Seq_Trades': encoded, 'Risk': '100.0'})
        ok = self.build(sequence['output']['path'], {'Max_Seq_Trades': '5||2||1||8||Y', 'Risk': '100.0'})
        self.assertEqual(ok['validation']['active_axes'], {'Max_Seq_Trades': 7})

    def test_mode_lots_ladder_reaching_risk_per_sequence_is_refused(self):
        schema = copy.deepcopy(self.schema); schema['inputs']['Mode_Lots']['optimizable'] = True
        single = starter_set('single', self.root / 'opt.set', schema, self.policy, controller_version='t', ea_version='1.49')
        for encoded, refused in (('0||0||1||2||Y', True), ('0||0||2||2||Y', True), ('0||0||1||1||Y', False)):
            with self.subTest(encoded=encoded):
                build = lambda: build_set(single['output']['path'], self.root / ('l' + encoded.replace('|', '') + '.set'),
                                          spec({'Mode_Lots': encoded}), schema, self.policy, controller_version='t', ea_version='1.49')
                if refused:
                    with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE): build()
                else:
                    self.assertEqual(build()['validation']['active_axes'], {'Mode_Lots': 2})

    def test_rule_is_unconditional_with_one_reason_code_and_released_exports_still_pass(self):
        fixtures = sorted((Path(__file__).parent / 'fixtures/oosc').glob('*/deploy/*/*/*.set'))
        self.assertGreaterEqual(len(fixtures), 5)
        for path in fixtures:
            values = read_values(path.read_bytes())
            self.assertEqual(values['Mode_Lots'], '2')                                 # real RiskperSeq exports
            validate_set(path, self.schema, self.policy)
            single = path.read_bytes().decode('utf-16').replace('Max_Seq_Trades=' + values['Max_Seq_Trades'], 'Max_Seq_Trades=1')
            target = self.root / path.name; target.write_bytes(single.encode('utf-16'))
            with self.assertRaises(ValueError) as refused:
                validate_set(target, self.schema, self.policy)
            self.assertEqual(str(refused.exception), RISK_SIZING_CODE + ': ' + RISK_SIZING_MESSAGE)
        self.assertEqual(RISK_SIZING_MESSAGE, 'Risk-per-sequence sizing needs at least 2 sequence trades; use fixed lots or '
                         'raise Max_Seq_Trades (single-trade % risk returns in the next EA build).')
        self.assertTrue(validate_set(self.starter('single')['output']['path'], self.schema, self.policy))   # FixedLots + 1 trade

    def test_risk_is_never_silently_inherited_from_a_sequence_starter(self):
        sequence = self.starter('sequence')
        stored = json.loads(Path(sequence['receipt_path']).read_text(encoding='utf-8'))
        self.assertEqual([c['input'] for c in stored['user_choices_required']], ['Risk'])
        self.assertEqual(stored['user_choices_required'][0]['placeholder'], '500.0')
        self.assertIn('; GOAT Risk not chosen: Risk=500.0 is a placeholder', Path(sequence['output']['path']).read_bytes().decode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'RISK_NOT_CHOSEN'):
            self.build(sequence['output']['path'], {'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        same = self.build(sequence['output']['path'], {'Risk': '500.0', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})
        self.assertIn({'input': 'Risk', 'before': '500.0', 'after': '500.0', 'rationale': 'Needed by the idea: Risk'}, same['changes'])
        self.assertEqual((same['risk']['never_chosen'], same['risk']['chosen_here']), (False, True))
        self.assertNotIn('GOAT Risk not chosen', Path(same['output']['path']).read_bytes().decode('utf-16'))
        single = json.loads(Path(self.starter('single')['receipt_path']).read_text(encoding='utf-8'))
        self.assertEqual([c['input'] for c in single['user_choices_required']], ['Risk'])   # unused until a descendant sizes by it

    # ---- Claude-Mac's re-review of fb9deb3b, point 3: RISK_NOT_CHOSEN through the whole lineage
    def test_two_hop_chain_from_a_sequence_starter_cannot_inherit_the_placeholder(self):
        sequence = self.starter('sequence')
        a = self.build(sequence['output']['path'], {'Mode_Lots': '0', 'Sequence_MLPS_Hard_Close': 'false',
                                                    'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'}, output='a.set')
        self.assertTrue(a['risk']['never_chosen'])
        self.assertIn('; GOAT Risk not chosen:', Path(a['output']['path']).read_bytes().decode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'RISK_NOT_CHOSEN'):
            self.build(a['output']['path'], {'Mode_Lots': '2'}, output='b.set')
        with self.assertRaisesRegex(ValueError, 'RISK_NOT_CHOSEN'):
            self.build(a['output']['path'], {'Sequence_MLPS_Hard_Close': 'true'}, output='b.set')
        self.assertFalse((self.root / 'b.set').exists())
        b = self.build(a['output']['path'], {'Mode_Lots': '2', 'Risk': '150.0'}, output='b.set')   # choosing Risk ends it
        self.assertEqual(b['risk']['never_chosen'], False)
        c = self.build(b['output']['path'], {'Risk': '200.0'}, output='c.set')
        self.assertEqual((c['parent'], c['risk']['never_chosen']), ('set', False))

    def test_two_hop_chain_from_a_single_starter_is_refused_too(self):
        single = self.starter('single')
        a = self.build(single['output']['path'], {'Max_Seq_Trades': '5||2||1||8||Y'}, output='a.set')
        with self.assertRaisesRegex(ValueError, 'RISK_NOT_CHOSEN'):
            self.build(a['output']['path'], {'Mode_Lots': '2'}, output='b.set')
        # A hand edit that keeps the marker is caught by validate-set and every validate_raw path as well.
        text = Path(a['output']['path']).read_bytes().decode('utf-16').replace('Mode_Lots=0', 'Mode_Lots=2')
        (self.root / 'hand.set').write_bytes(text.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'RISK_NOT_CHOSEN'):
            validate_set(self.root / 'hand.set', self.schema, self.policy)

    def test_a_starter_resaved_without_comments_or_receipt_is_still_a_starter(self):
        sequence = self.starter('sequence'); path = Path(sequence['output']['path'])
        resaved = ''.join(line for line in path.read_bytes().decode('utf-16').splitlines(keepends=True) if not line.startswith(';'))
        target = self.root / 'mt5' / 'resaved.set'; target.parent.mkdir(); target.write_bytes(resaved.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'without its .starter.json receipt'):
            self.build(target, {'Risk': '100.0', 'RSI_Mode': '1', 'RSI_Period': '14||7||7||21||Y'})

    def test_receipt_write_failure_rolls_back_the_starter(self):
        import studio_template_tools
        real = studio_template_tools._write_new
        def fail_receipt(files):
            if files[0][0].name.endswith('.starter.json'): raise OSError('disk full')
            return real(files)
        with patch('studio_template_tools._write_new', side_effect=fail_receipt), self.assertRaisesRegex(OSError, 'disk full'):
            self.starter('single')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_no_entry_signal_is_built_with_an_honest_warning(self):
        starter = self.starter('sequence')
        result = self.build(starter['output']['path'], {'Grid_Size': '10.0||5.0||5.0||20.0||Y', 'Risk': '100.0'},
                            entry_logic='No indicator: a sequence opens whenever none is open, inside the default sessions.')
        self.assertEqual(result['starter']['entry_filters_enabled'], [])
        self.assertRegex(result['starter']['warnings'][0], 'No entry signal is enabled')
        self.assertIn('**Warning:** No entry signal', Path(result['support_path']).read_text(encoding='utf-8'))


RISKY = dict(Mode_Lots='2', Max_Seq_Trades='1')


class EveryStrategyPathTests(unittest.TestCase):
    """Claude-Mac's re-review of fb9deb3b, points 1, 2 and 4: the rule lives in validate_strategy, so the
    single-job prepare, raw enqueue_batch and EA-panel draft paths hit it, and deploy-load checks bytes."""
    def setUp(self):
        self.fixture = goat_fixture.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        from goat_studio import Controller
        c = Controller(self.fixture.path); self.fixture.controller = c
        c.bootstrap('123456', 'Customer-Demo'); c.store.close(); c.store = None; c.open()   # real shipped 1.48 contracts
        self.c = c
        self.schema = c.schema
        self.safe = starter_set('sequence', self.fixture.root / 'base.set', c.schema, c.policy, controller_version='t',
                                ea_version='1.48')
        self.values = read_values(Path(self.safe['output']['path']).read_bytes())
        self.values['Grid_Size'] = '10.0||5.0||5.0||20.0||Y'

    def risky(self, **extra):
        return self.values | RISKY | extra

    def envelope(self, command, payload, request_id):
        state = self.c.state()
        return dict(schema_version=1, request_id=request_id, terminal_id=self.c.terminal, run_id=self.c.run,
                    expected_revision=state['revision'], generation=state['generation'], command=command, payload=payload)

    def test_every_spelling_is_refused_by_validate_strategy_itself(self):
        from studio_strategy_settings import validate_strategy
        self.assertTrue(validate_strategy(self.values, self.schema)['axes'])
        for name, spellings in (('Max_Seq_Trades', ('1', '0', '-3', '1.0', '01', '+1', '1e0', '-0', '4||0||1||8||Y',
                                                     '5||1||1||8||Y', '1||2||1||5||N', '1||2||1||5||Y')),
                                ('Mode_Lots', ('2.0', '02', '2e0', '2||0||1||2||N'))):
            for spelling in spellings:
                values = self.values | {'Mode_Lots': '2', 'Max_Seq_Trades': '1'} | {name: spelling}
                with self.subTest(name=name, spelling=spelling), self.assertRaisesRegex(ValueError, '^' + RISK_SIZING_CODE):
                    validate_strategy(values, self.schema)

    def test_ea_panel_draft_is_refused(self):
        request = self.envelope('draft.replace_strategy', dict(schema_hash=sha(self.schema), values=self.risky()), 'panel-draft-1')
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.c.store.submit(request, actor='human')
        self.assertIsNone(self.c.state()['strategy_draft'])

    def test_single_job_prepare_is_refused_before_anything_is_queued(self):
        source = self.fixture.root / 'risky.set'
        source.write_bytes(('\r\n'.join(k + '=' + v for k, v in self.risky().items()) + '\r\n').encode('utf-16'))
        config = self.fixture.root / 'settings.json'
        config.write_text(json.dumps(dict(tester=self.fixture.tester, export=self.fixture.exports)))
        self.fixture.grant(self.c)
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.c.prepare('risky-job', source, config)
        self.assertEqual(self.c.state()['queue'], [])
        self.assertFalse((self.c.root / 'packages' / 'risky-job').exists())

    def test_single_job_prepare_refuses_an_unchosen_starter_risk(self):
        # Claude-Mac's review 5409023738, point 2: prepare --set reads the bytes' lineage marker too.
        single = starter_set('single', self.fixture.root / 'single.set', self.schema, self.c.policy, controller_version='t', ea_version='1.48')
        text = Path(single['output']['path']).read_bytes().decode('utf-16')
        self.assertIn('; GOAT Risk not chosen:', text)
        text = (text.replace('EA_Desc=Starter Single Trade', 'EA_Desc=My variant [0123456789ab]').replace('Mode_Lots=0', 'Mode_Lots=2')
                .replace('Max_Seq_Trades=1', 'Max_Seq_Trades=5').replace('Grid_Size=10.0', 'Grid_Size=10.0||5.0||5.0||20.0||Y'))
        source = self.fixture.root / 'marked.set'; source.write_bytes(text.encode('utf-16'))
        config = self.fixture.root / 'settings.json'
        config.write_text(json.dumps(dict(tester=self.fixture.tester, export=self.fixture.exports)))
        self.fixture.grant(self.c)
        with self.assertRaisesRegex(ValueError, '^RISK_NOT_CHOSEN'):
            self.c.prepare('marked-job', source, config)
        self.assertEqual(self.c.state()['queue'], [])
        self.assertIsNone(self.c.state()['strategy_draft'])
        chosen = source.with_name('chosen.set')
        chosen.write_bytes(''.join(l for l in text.splitlines(keepends=True) if not l.startswith('; GOAT Risk not chosen:')).encode('utf-16'))
        self.assertEqual(self.c.prepare('chosen-job', chosen, config)['job_id'], 'chosen-job')   # Risk chosen: it queues

    def test_raw_enqueue_batch_is_refused(self):
        self.fixture.grant(self.c)
        member = dict(tester=self.fixture.tester, export=self.fixture.exports,
                      strategy=dict(schema_hash=sha(self.schema), values=self.risky()))
        request = self.envelope('queue.enqueue_batch', dict(job_id='raw-batch', members=[member]), 'raw-batch-1')
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            self.c.store.submit(request, actor='agent')
        self.assertEqual(self.c.state()['queue'], [])

    def test_a_job_queued_before_the_rule_is_refused_at_every_native_start(self):
        from types import SimpleNamespace
        from studio_research_authority import before_native_dispatch
        fake = SimpleNamespace(schema=self.schema)
        for job in (dict(job_id='old-single', configuration=dict(strategy=dict(values=self.risky()))),
                    dict(job_id='old-batch', configuration=dict(strategy=dict(values=self.values),
                         batch_members=[dict(strategy=dict(values=self.values)), dict(strategy=dict(values=self.risky()))]))):
            with self.subTest(job=job['job_id']), self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
                before_native_dispatch(fake, job)

    def test_schema_that_renames_the_sizing_inputs_fails_closed(self):
        from studio_strategy_settings import RISK_SIZING_SCHEMA_CODE, validate_strategy
        renamed = copy.deepcopy(self.schema)
        renamed['inputs']['Mode_Lots']['enum_choices'] = {'FixedLots': 0, 'ScaledLots': 1, 'RiskPerSequence': 2}
        with self.assertRaisesRegex(ValueError, RISK_SIZING_SCHEMA_CODE):
            validate_strategy(self.values, renamed)
        missing = copy.deepcopy(self.schema); del missing['inputs']['Max_Seq_Trades']
        values = dict(self.values); del values['Max_Seq_Trades']
        with self.assertRaisesRegex(ValueError, RISK_SIZING_SCHEMA_CODE):
            validate_strategy(values, missing)


class DeployLoadGuardTests(unittest.TestCase):
    """deploy-load: the path closest to money checks every member's bytes before anything is written."""
    def setUp(self):
        agent_fixture.AgentSetupTests.setUp(self)
        self.c.schema = contracts('1.48')[0]                                         # the shipped interface

    plan, tearDown = agent_fixture.AgentSetupTests.plan, agent_fixture.AgentSetupTests.tearDown

    def test_risky_member_is_refused_before_any_file_is_written(self):
        import studio_demo_deploy as deploy
        for content in ('EA_Desc=Trend 0\r\nMode_Lots=2\r\nMax_Seq_Trades=1\r\n',
                        'EA_Desc=Trend 0\r\nMode_Lots=2||0||1||2||N\r\nMax_Seq_Trades=0\r\n',
                        'EA_Desc=Trend 0\r\nMax_Seq_Trades=1\r\nMode_Lots=2.0\r\n'):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, '^' + RISK_SIZING_CODE + '.*nothing was written'):
                deploy.load(self.c, self.plan([agent_fixture.member(0, content=content.encode('utf-16'))]),
                            mt5=agent_fixture.FakeMT5(self.c))
        where = deploy.paths(self.c, 'e' * 32)
        self.assertFalse(where['sets'].exists() or where['state'].exists() or where['preset'].exists())
        self.assertFalse(where['journal'].exists())

    def test_partial_and_safe_members_pass_the_value_check(self):
        import studio_demo_deploy as deploy
        for content in ('EA_Desc=Trend 0\r\nMode_Lots=2\r\nMax_Seq_Trades=8\r\n',   # a real RiskperSeq export
                        'EA_Desc=Trend 0\r\nMax_Seq_Trades=1\r\n',                  # missing Mode_Lots is FixedLots
                        'EA_Desc=Trend 0\r\nMode_Lots=2\r\n'):                       # missing Max is the default 10
            deploy.check_member_values(self.c, 'm.set', content.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            deploy.check_member_values(self.c, 'm.set', 'Mode_Lots=2\r\nMax_Seq_Trades=1\r\n'.encode('utf-16'))

    # ---- Claude-Mac's review 5409023738, point 1: read keys the way the dashboard's BuildTemplate does
    def test_whitespace_case_and_duplicate_key_probes_are_refused(self):
        import studio_demo_deploy as deploy
        probes = {
            ' Mode_Lots=2\r\n Max_Seq_Trades=1\r\n': 'SET_KEY_NOT_EXACT',            # leading space (the reproduced bypass)
            '\tMode_Lots=2\r\n\tMax_Seq_Trades=1\r\n': 'SET_KEY_NOT_EXACT',          # tab
            'Mode_Lots =2\r\nMax_Seq_Trades=8\r\n': 'SET_KEY_NOT_EXACT',             # trailing space in the key
            'mode_lots=2\r\nMax_Seq_Trades=1\r\n': 'SET_KEY_NOT_EXACT',              # case near-miss
            'MODE_LOTS=0\r\nMax_Seq_Trades=8\r\n': 'SET_KEY_NOT_EXACT',              # near-miss even with a safe value
            'Mode_Lots=0\r\nMode_Lots=2\r\nMax_Seq_Trades=1\r\n': 'SET_DUPLICATE_INPUT',
            'Mode_Lots=0\r\nMax_Seq_Trades=1\r\n Mode_Lots=2\r\n': 'SET_KEY_NOT_EXACT',   # the shadowing pair
            'Max_Seq_Trades=8\r\nMax_Seq_Trades=1\r\nMode_Lots=2\r\n': 'SET_DUPLICATE_INPUT',
        }
        for content, code in probes.items():
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, '^' + code + '.*nothing was written'):
                deploy.check_member_values(self.c, 'm.set', ('EA_Desc=Trend 0\r\n' + content).encode('utf-16'))
        # Through the whole load: refused before anything is written.
        with self.assertRaisesRegex(ValueError, '^SET_KEY_NOT_EXACT'):
            deploy.load(self.c, self.plan([agent_fixture.member(0, content='EA_Desc=Trend 0\r\n Mode_Lots=2\r\n Max_Seq_Trades=1\r\n'.encode('utf-16'))]),
                        mt5=agent_fixture.FakeMT5(self.c))
        where = deploy.paths(self.c, 'e' * 32)
        self.assertFalse(where['sets'].exists() or where['state'].exists() or where['journal'].exists())
        # Trailing whitespace after a value is what the dashboard trims too; values are compared trimmed.
        with self.assertRaisesRegex(ValueError, RISK_SIZING_CODE):
            deploy.check_member_values(self.c, 'm.set', 'Mode_Lots=2 \r\nMax_Seq_Trades=1\t\r\n'.encode('utf-16'))
        deploy.check_member_values(self.c, 'm.set', '; Mode_Lots=2 in a comment\r\nMode_Lots=2\r\nMax_Seq_Trades=8\r\n'.encode('utf-16'))


class StarterCliTests(unittest.TestCase):
    """The installed CLI on a demo_direct installation: starter-set and build-set run there like validate-set (local
    create-only files); every mutation of the store, queue, terminal or roster still refuses."""
    def setUp(self):
        seed_agent_fixture.DemoSeedAgentTests.setUp(self)
        self.patches[-1].stop()                                                     # the real Controller for the CLI
        with self.database() as db:     # a classified store, as on a real install: dispatch() asks authority() per operation
            db.execute('CREATE TABLE studio_authorities (binding TEXT PRIMARY KEY, kind TEXT, provenance TEXT)')

    database, new_agent, sleep = (seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent,
                                  seed_agent_fixture.DemoSeedAgentTests.sleep)

    def cli(self, *argv):
        from goat_studio import main
        output = StringIO()
        with redirect_stdout(output):
            code = main(['--installation', str(self.installation), *argv])
        return code, json.loads(output.getvalue())

    def test_starter_set_and_validate_set_through_the_cli(self):
        target = Path(self.temp.name) / 'my strategies' / 'Starter.set'
        code, reply = self.cli('starter-set', '--shape', 'single', '--output', str(target))
        self.assertEqual(code, 0, reply)
        self.assertEqual((reply['result']['shape'], reply['result']['ea_version']), ('single', '1.49'))
        self.assertTrue(target.is_file() and target.with_suffix('.starter.json').is_file())
        code, report = self.cli('validate-set', '--set', str(target))
        self.assertEqual((code, report['result']['kind']), (0, 'fixed_settings'))
        code, again = self.cli('starter-set', '--shape', 'single', '--output', str(target))
        self.assertEqual(code, 2); self.assertIn('already exists', again['error'])
        risky = target.with_name('risky.set')
        risky.write_bytes(target.read_bytes().decode('utf-16').replace('Mode_Lots=0', 'Mode_Lots=2||0||1||2||N').encode('utf-16'))
        code, refused = self.cli('validate-set', '--set', str(risky))
        self.assertEqual((code, refused['error']), (2, RISK_SIZING_CODE + ': ' + RISK_SIZING_MESSAGE))

    def test_discover_advertises_the_contract_and_set_building_is_allowed_on_demo_lane(self):
        from goat_studio import OPERATION_CONTRACTS
        contract = OPERATION_CONTRACTS['starter-set']
        self.assertEqual((contract['required'], contract['choices']['shape']), (['shape', 'output'], ['single', 'sequence']))
        self.assertIn('never opens the store or MT5', contract['effect'])
        with self.database() as db:
            for name in ('starter-set', 'build-set'):
                with operation(name):
                    self.assertIsNone(authority(db, self.binding, dict(owner='agent', generation=1)))
            for name in ('prepare-batch', 'run-batch', 'start', 'save-batch', 'seed-prepare', 'seed-promote', 'catchup-prepare',
                         'deploy-load', 'close-terminal', 'peer-add', 'peer-remove', 'monitor-launch'):
                with operation(name), self.assertRaisesRegex(ValueError, 'Demo mutation requires the broker-verified agent tool'):
                    authority(db, self.binding, dict(owner='agent', generation=1))

    def snapshot(self, *roots):
        """Every file under the controller state, terminal data and common roots, with its bytes' hash."""
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for root in roots for path in sorted(Path(root).rglob('*')) if path.is_file()}

    def test_build_set_runs_on_the_demo_lane_and_writes_only_its_three_files(self):
        """goatai#1885: a demo-only tester's agent could not build a SET at all (build-set refused on demo_direct)."""
        folder = Path(self.temp.name) / 'my strategies'
        starter = folder / 'Starter.set'
        code, reply = self.cli('starter-set', '--shape', 'single', '--output', str(starter))
        self.assertEqual(code, 0, reply)
        changes = json.loads(json.dumps(spec({'RSI_Mode': '1', 'RSI_TF_': '15', 'RSI_Period': '14||7||7||21||Y'})))
        changes_path = Path(self.temp.name) / 'changes.json'
        changes_path.write_text(json.dumps(changes), encoding='utf-8')
        roots = (self.root, self.data, self.common)
        before, folder_before = self.snapshot(*roots), self.snapshot(folder)
        variant = folder / 'My RSI.set'
        code, reply = self.cli('build-set', '--source', str(starter), '--output', str(variant), '--spec', str(changes_path))
        self.assertEqual(code, 0, reply)
        result = reply['result']
        self.assertEqual((result['parent'], result['validation']['active_axes']), ('starter:single', {'RSI_Period': 3}))
        # No store, session, queue, terminal or mailbox effect: the controller, terminal and common roots are byte-identical.
        self.assertEqual(self.snapshot(*roots), before)
        # Exactly the new SET, its support notes and its provenance receipt; the source and its receipt are unchanged.
        after = self.snapshot(folder)
        self.assertEqual({k: v for k, v in after.items() if k in folder_before}, folder_before)
        self.assertEqual(sorted(Path(k).name for k in set(after) - set(folder_before)), ['My RSI.build.json', 'My RSI.md', 'My RSI.set'])
        self.assertEqual(after[str(variant)], result['output']['sha256'])
        code, report = self.cli('validate-set', '--set', str(variant), '--require-optimization')
        self.assertEqual((code, report['result']['kind']), (0, 'optimization_template'), report)
        # Create-only, like starter-set: a second build to the same path refuses and changes nothing.
        code, again = self.cli('build-set', '--source', str(starter), '--output', str(variant), '--spec', str(changes_path))
        self.assertEqual(code, 2); self.assertIn('already exists', again['error'])
        self.assertEqual(self.snapshot(folder), after)

    def test_a_real_mutation_is_still_refused_through_the_cli_on_the_demo_lane(self):
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text('{}', encoding='utf-8')
        before = self.snapshot(self.root, self.data, self.common)
        for argv in (('prepare-batch', '--batch-id', 'demo-batch', '--plan', str(plan)),
                     ('peer-add', '--terminal', str(self.exe))):
            code, refused = self.cli(*argv)
            self.assertEqual((code, refused['error']), (2, 'Demo mutation requires the broker-verified agent tool'), argv)
        self.assertEqual(self.snapshot(self.root, self.data, self.common), before)


class StrategyCreateSkillTests(unittest.TestCase):
    root = Path(__file__).parent

    def test_registered_in_names_and_the_customer_skills_table(self):
        from studio_customer_skills import NAMES, customer_skills
        self.assertIn('goat-strategy-create', NAMES)
        table = (self.root / 'CUSTOMER-SKILLS.md').read_text(encoding='utf-8')
        linked = re.findall(r'\| \[([a-z0-9-]+)\]\(skills/([a-z0-9-]+)/SKILL\.md\) \|', table)
        self.assertEqual([name for name, _ in linked], list(NAMES))
        self.assertTrue(all(name == folder for name, folder in linked))
        self.assertIn('goat-strategy-create', [row['name'] for row in customer_skills()])

    def test_skill_keeps_the_honesty_and_safety_rules(self):
        body = ' '.join((self.root / 'skills/goat-strategy-create/SKILL.md').read_text(encoding='utf-8').split())
        for phrase in ('starter-set', 'build-set', 'validate-set --require-optimization', 'strategy.forkTemplate',
                       "starter: 'single'", 'contentBase64', 'UNTESTED', 'a new idea starts with zero evidence',
                       'heldOut.declare', '13-week', 'demo', 'Explore', 'Refine', 'Prove', 'strategy.matrix',
                       'money lost per sequence', 'INPUT-REFERENCE.md', 'discover', 'ask the user for `Risk`',
                       'RISK_NOT_CHOSEN', 'RISK_PER_SEQUENCE_NEEDS_TWO_TRADES'):
            self.assertIn(phrase, body)
        for guide in ('AGENT-START-HERE.md', 'TEMPLATE-WORKFLOW.md'):
            self.assertIn('goat-strategy-create', (self.root / guide).read_text(encoding='utf-8'), guide)


if __name__ == '__main__':
    unittest.main()
