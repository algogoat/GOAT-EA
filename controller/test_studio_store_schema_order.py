"""The store judges enum ladders in the contract's declaration order, as the seed lane and prepare-batch's plan check do
(GOAT-EA#317).

Hunt round 13a wave 3 seeded cells with ``EMA_Mode=1||0||1||2||Y``. ENUM_MODE_TRADE is declared 0, 1, 2, 3, 4, 5
(GOAT_Inputs_Definitions.mqh), so 0..2 by 1 is a native ladder: the seed lane accepted it, MT5 walked 0, 1, 2, and
prepare-batch's own plan check accepted it too. The store then refused it when the batch was queued, after it was
staged: "ENUM_LADDER_NOT_NATIVE ... declared in order 5, 4, 0, 3, 1, 2". The store's copy of the schema was
``json.loads(packed(schema))`` and ``packed`` sorts keys, so every enum's choices were in name order. The controller
here is built as production builds it (the real v149 contract, StudioStore's own copy, no fixture override)."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from goat_studio import Controller
import studio_command_store
from studio_command_store import CONTRACT_ORDER_LOST, StudioStore, held_contract
from studio_installation import contracts
from studio_seed import SeedRunner
from studio_strategy_settings import APPENDED_INPUTS, ENUM_LADDER_CODE, appended_default, native_enum_ladders, read_values, validate_strategy
from studio_template_tools import schema_default
import test_goat_studio as goat_studio_tests   # its PortableControllerTests fixture (a module attribute, so not collected here)
from test_studio_pinned_tester_inputs import compass_like_template

SCHEMA, POLICY = contracts('1.49')
WAVE3 = '1||0||1||2||Y'                  # hunt round 13a wave 3: 006-beacon-ema-axis.set, 007-harbor-ema-axis.set
TRADE = [0, 1, 2, 3, 4, 5]               # ENUM_MODE_TRADE as declared (GOAT_Inputs_Definitions.mqh)


def name_sorted(schema):
    """What the store held before: every dict in key order."""
    return json.loads(packed(schema))


def defaults(**changes):
    return {name: schema_default(name, definition, SCHEMA['defines']) for name, definition in SCHEMA['inputs'].items()} | changes


class StoreCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = StudioStore(Path(self.temp.name) / 'studio.sqlite', input_schema=SCHEMA, dependency_policy=POLICY, create=True)
        self.addCleanup(self.store.close)

    def test_a_production_built_store_holds_every_enum_in_the_contracts_declaration_order(self):
        held = self.store.input_schema
        self.assertEqual(list(held['inputs']['EMA_Mode']['enum_choices'].values()), TRADE)
        self.assertEqual(list(held['inputs']), list(SCHEMA['inputs']))                 # the inputs' own order too
        for name, definition in SCHEMA['inputs'].items():
            if definition.get('enum_choices'):
                self.assertEqual(list(held['inputs'][name]['enum_choices'].items()), list(definition['enum_choices'].items()), name)
        self.assertEqual(json.dumps(held), json.dumps(SCHEMA))
        self.assertIsNot(held, SCHEMA)                                                # still its own copy
        self.assertEqual(json.dumps(self.store.dependency_policy), json.dumps(POLICY))

    def test_the_schema_hash_is_the_value_it_was_with_the_sorted_copy(self):
        before = sha(name_sorted(SCHEMA))                  # what StudioStore computed until now
        self.assertEqual(self.store.input_schema_hash, before)
        self.assertEqual(self.store.input_schema_hash, sha(SCHEMA))
        self.assertEqual(sha(self.store.dependency_policy), sha(name_sorted(POLICY)))
        # The dependency policy has no order in its keys to lose: its rules are a list, which sorting keys never reorders.
        self.assertEqual(name_sorted(POLICY)['rules'], POLICY['rules'])

    def test_what_the_sorted_copy_did_to_the_wave_3_ladder(self):
        """The old behaviour, as a reproduction: the same validator, two orders of one enum."""
        values = defaults(EMA_Mode=WAVE3)
        self.assertEqual(validate_strategy(dict(values), SCHEMA)['axes'], dict(EMA_Mode=3))
        old = name_sorted(SCHEMA)
        self.assertEqual(list(old['inputs']['EMA_Mode']['enum_choices'].values()), [5, 4, 0, 3, 1, 2])
        with self.assertRaisesRegex(ValueError, '^' + ENUM_LADDER_CODE + r': .*EMA_Mode=1\|\|0\|\|1\|\|2\|\|Y walks 0, 1, 2 by 1 over '
                                                r'ENUM_MODE_TRADE \(declared in order 5, 4, 0, 3, 1, 2\)'):
            validate_strategy(dict(values), old)
        self.assertEqual(validate_strategy(dict(values), self.store.input_schema)['axes'], dict(EMA_Mode=3))
        # 34 optimizable enums changed their order in that copy; none does in the store's copy now.
        changed = [name for name, d in SCHEMA['inputs'].items() if d.get('enum_choices') and d.get('optimizable') and d['type'] != 'string'
                   and list(old['inputs'][name]['enum_choices'].values()) != list(d['enum_choices'].values())]
        self.assertEqual(len(changed), 34)
        self.assertIn('EMA_Mode', changed)

    def test_a_copy_that_loses_the_order_is_refused_not_judged_by(self):
        with patch.object(studio_command_store, '_detached', name_sorted):
            with self.assertRaisesRegex(ValueError, '^' + CONTRACT_ORDER_LOST + ': the store\'s copy of the input schema is not in the order'):
                StudioStore(Path(self.temp.name) / 'other.sqlite', input_schema=SCHEMA, dependency_policy=POLICY, create=True)
            # The policy's key order is alphabetical only by accident of how it is written; a sorted copy of it is refused too.
            if json.dumps(name_sorted(POLICY)) != json.dumps(POLICY):
                with self.assertRaisesRegex(ValueError, CONTRACT_ORDER_LOST + ': the store\'s copy of the dependency policy'):
                    held_contract(POLICY, 'dependency policy')
        self.assertEqual(json.dumps(held_contract(SCHEMA, 'input schema')), json.dumps(SCHEMA))


class ProductionControllerCase(unittest.TestCase):
    """A controller opened the way goat_studio opens it on a V1.49 installation: contracts('1.49') and the store's own
    copy of them. Nothing is assigned onto the store."""

    def setUp(self):
        self.fixture = goat_studio_tests.PortableControllerTests('test_prepare_exact_inputs_server_version_ninth_setting')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.fixture.receipt['ea_version'] = '1.49'
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        c = Controller(self.fixture.path); self.fixture.controller = c
        c.bootstrap('123456', 'Customer-Demo'); c.store.close(); c.store = None; c.open()
        self.fixture.grant(c)
        self.c, self.root = c, self.fixture.root
        template = read_values(('\r\n'.join(compass_like_template(SCHEMA).splitlines()) + '\r\n').encode('utf-16'))
        # A complete V1.49 SET: the template's inputs and every appended input at its declared default.
        self.values = dict(template, **{name: appended_default(SCHEMA['inputs'][name]) for name in APPENDED_INPUTS if name not in template})

    def source(self, name, **changes):
        path = self.root / name
        values = dict(self.values, EA_Desc='Harbor EMA axis', **changes)
        path.write_bytes(b'\xff\xfe' + ''.join('%s=%s\r\n' % item for item in values.items()).encode('utf-16-le'))
        return path

    def prepare_batch(self, batch_id, source):
        from studio_batch import prepare_batch
        plan = self.root / (batch_id + '.json')
        plan.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=[dict(set_path=str(source), tester=self.fixture.tester)])))
        return prepare_batch(self.c, batch_id, plan)

    def seed_validate(self, source):
        plan = dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=30, cutoff=dict(min_fitness=0, min_trades=1),
                    jobs=[dict(set_path=str(source), tester=self.fixture.tester | {'ForwardMode': 0, 'ForwardDate': ''}, frame_target=81)])
        runner = SeedRunner(self.c, process=SimpleNamespace(inspect=lambda: None))
        return runner.validate(plan)

    def staged(self, batch_id):
        return ((self.c.root / 'packages' / batch_id).exists(), (self.c.root / 'requests' / (batch_id + '-batch.json')).exists(),
                [job['job_id'] for job in self.c.state()['queue']])


class LaneAgreementTests(ProductionControllerCase):
    def test_the_controller_and_its_store_hold_one_order(self):
        self.assertIsNot(self.c.store.input_schema, self.c.schema)
        self.assertEqual(json.dumps(self.c.store.input_schema), json.dumps(self.c.schema))
        self.assertEqual(list(self.c.store.input_schema['inputs']['EMA_Mode']['enum_choices'].values()), TRADE)
        self.assertEqual(self.c.store.input_schema_hash, sha(SCHEMA))

    def test_prepare_batch_accepts_the_wave_3_ladder_and_stages_and_queues_it(self):
        """Before: refused at the store's queue check with "Prepared package retained; queue publication was not
        confirmed ... ENUM_LADDER_NOT_NATIVE ... declared in order 5, 4, 0, 3, 1, 2", the package and request left behind."""
        result = self.prepare_batch('prove-ema', self.source('ema-axis.set', EMA_Mode=WAVE3))
        self.assertEqual((result['member_count'], result['native_started']), (1, False))
        self.assertEqual(self.staged('prove-ema'), (True, True, ['prove-ema']))
        job = self.c.job('prove-ema')
        self.assertEqual((job['status'], job['configuration']['strategy']['values']['EMA_Mode']), ('pending', WAVE3))
        self.assertEqual(job['configuration']['strategy']['axes']['EMA_Mode'], 3)

    def test_the_seed_lane_and_prepare_batch_both_accept_the_wave_3_ladder(self):
        source = self.source('ema-axis.set', EMA_Mode=WAVE3)
        self.assertEqual(self.seed_validate(source)['jobs'][0]['axes']['EMA_Mode'], 3)
        self.assertEqual(self.prepare_batch('prove-ema', source)['member_count'], 1)
        # The form the old refusal recommended, and a fixed EMA_Mode, are accepted by both as before.
        for name, ladder in (('narrow', '1||1||1||2||Y'), ('fixed', '1||0||1||2||N')):
            other = self.source(name + '.set', EMA_Mode=ladder)
            self.assertTrue(self.seed_validate(other)['valid'], name)
            self.assertEqual(self.prepare_batch('prove-' + name, other)['member_count'], 1, name)

    def test_the_seed_lane_and_prepare_batch_both_refuse_a_ladder_that_is_not_native_before_anything_is_staged(self):
        source = self.source('rsi-tf.set', RSI_TF_='15||5||10||15||Y')
        refusal = '^' + ENUM_LADDER_CODE + r': .*RSI_TF_=15\|\|5\|\|10\|\|15\|\|Y walks 5, 15 by 10 over ENUM_MODE_TFs \(declared in order 0, 1, 5, 15, 60, 240, 1440\)'
        with self.assertRaisesRegex(ValueError, refusal):
            self.seed_validate(source)
        with self.assertRaisesRegex(ValueError, refusal):
            self.prepare_batch('prove-rsi', source)
        self.assertEqual(self.staged('prove-rsi'), (False, False, []))

    def test_a_member_only_the_store_would_refuse_is_refused_before_staging_and_keeps_its_batch_id(self):
        """The store's check now runs before anything is staged. With the store holding the old name-sorted copy (put
        there on purpose), the wave 3 ladder is refused by that check alone: no "Prepared package retained", nothing
        left behind, and the same batch ID prepares once the store's copy is in order again."""
        source = self.source('ema-axis.set', EMA_Mode=WAVE3)
        ordered = self.c.store.input_schema
        self.c.store.input_schema = name_sorted(SCHEMA)
        with self.assertRaises(ValueError) as caught:
            self.prepare_batch('prove-ema', source)
        self.assertTrue(str(caught.exception).startswith(ENUM_LADDER_CODE + ': '), str(caught.exception)[:200])
        self.assertNotIn('Prepared package retained', str(caught.exception))
        self.assertEqual(self.staged('prove-ema'), (False, False, []))
        self.c.store.input_schema = ordered
        self.assertEqual(self.prepare_batch('prove-ema', source)['member_count'], 1)


class DraftPathTests(ProductionControllerCase):
    """The store's draft check (draft.replace_strategy) reads only the store's copy: the name-sorted copy allowed five
    ladders that are not native."""

    def draft(self, **changes):
        state = self.c.state()
        return self.c.store.submit(dict(schema_version=1, request_id='draft-' + '-'.join(changes), terminal_id=self.c.terminal, run_id=self.c.run,
                                        expected_revision=state['revision'], generation=state['generation'], command='draft.replace_strategy',
                                        payload=dict(schema_hash=self.c.store.input_schema_hash, values=defaults(**changes))), actor='agent')

    def test_ladders_the_sorted_copy_wrongly_allowed_are_refused_through_the_draft_path(self):
        old = name_sorted(SCHEMA)
        cases = dict(Trailing_Sample_Period='0||-1||1||0||Y',     # declared 0, -1, 1, 99: -1, 0 are not consecutive items
                     EMA_Price='5||5||1||7||Y', RSI_Price='5||5||1||6||Y', MACD_Price='5||5||1||7||Y', RSI2_Price='5||5||1||6||Y')   # declared 1, 6, 7, 5
        for name, ladder in cases.items():
            validate_strategy(defaults(**{name: ladder}), old)                         # the name-sorted copy allowed it
            with self.assertRaisesRegex(ValueError, '^' + ENUM_LADDER_CODE + ': .*' + name + '=', msg=name):
                self.draft(**{name: ladder})
            start, _, stop = (int(part) for part in ladder.split('||')[1:4])
            self.assertNotIn((start, stop), native_enum_ladders(list(SCHEMA['inputs'][name]['enum_choices'].values())), name)
        self.assertIsNone(self.c.state()['strategy_draft'])                             # no refused draft was stored

    def test_native_ladders_pass_the_draft_path(self):
        receipt = self.draft(EMA_Mode=WAVE3)
        self.assertEqual(self.c.state()['strategy_draft']['values']['EMA_Mode'], WAVE3)
        self.assertEqual(self.c.state()['strategy_draft']['axes'], dict(EMA_Mode=3))
        self.assertTrue(receipt)


if __name__ == '__main__':
    unittest.main()
