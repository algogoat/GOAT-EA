"""ENUM_LADDER_NOT_NATIVE (beta.38 P0): an optimized enum ladder the GOAT EA refuses at OnTesterInit is refused by
validate-set, prepare-batch and seed-prepare alike, before any batch or seed is frozen.

Evidence: GOAT V1.49.mq5:3949-3950 refused `RSI_TF_=15||5||10||15||Y` on 10-13 ("Native optimization flag/value/range
differs: RSI_TF_"); batch R87303ec90d13 ran full optimizations on 10-12 with `Active_Time_Weekday=4||3||1||4||Y`."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from campaign_ledger import sha
import goat_studio
from studio_installation import contracts
from studio_strategy_settings import (ENUM_LADDER_CODE, check_enum_ladders, native_enum_ladders,
                                      validate_strategy)
from studio_template_tools import schema_default, validate_set
import test_goat_studio as fixtures

SCHEMA, POLICY = contracts('1.49')
TFS = [0, 1, 5, 15, 60, 240]   # ENUM_MODE_TFs, GOAT_Inputs_Definitions.mqh:104-112


def defaults(**changes):
    return {name: schema_default(name, definition, SCHEMA['defines'])
            for name, definition in SCHEMA['inputs'].items()} | changes


def write_set(path, values):
    path.write_bytes(b'\xff\xfe' + ''.join(f'{k}={v}\r\n' for k, v in values.items()).encode('utf-16-le'))
    return path


class EnumLadderRuleTests(unittest.TestCase):
    def refused(self, **changes):
        with self.assertRaises(ValueError) as caught:
            validate_strategy(defaults(**changes), SCHEMA)
        message = str(caught.exception)
        self.assertTrue(message.startswith(ENUM_LADDER_CODE + ': '), message)
        return message

    def test_the_banker_refusal_is_refused_with_input_ladder_form_and_fix(self):
        message = self.refused(RSI_TF_='15||5||10||15||Y')
        for text in ('RSI_TF_=15||5||10||15||Y', 'walks 5, 15 by 10', 'ENUM_MODE_TFs', 'declared in order 0, 1, 5, 15, 60, 240',
                     'step 1 over items that are consecutive in declaration order and in value',
                     'RSI_TF_=<value>||0||1||1||Y', 'fix RSI_TF_ at one value (RSI_TF_=15||5||10||15||N)',
                     'list the timeframes (5, 15) as separate members', 'GOATOptimizationInputs.mqh:66-70'):
            self.assertIn(text, message)

    def test_every_prove_ladder_shape_is_refused_and_all_offenders_are_named(self):
        message = self.refused(RSI_TF_='15||5||10||15||Y', EMA_TF_='60||60||180||240||Y', ADX_TF_='15||15||45||60||Y')
        for text in ('RSI_TF_=15||5||10||15||Y', 'EMA_TF_=60||60||180||240||Y', 'ADX_TF_=15||15||45||60||Y'):
            self.assertIn(text, message)

    def test_known_good_enum_ladders_pass(self):
        validate_strategy(defaults(Active_Time_Weekday='4||3||1||4||Y'), SCHEMA)   # ran in R87303ec90d13 (10-12)
        validate_strategy(defaults(Mode_Trade='0||0||1||2||Y'), SCHEMA)
        validate_strategy(defaults(RSI_TF_='1||0||1||1||Y'), SCHEMA)                # the one native TF ladder

    def test_fixed_and_dormant_enums_pass(self):
        validate_strategy(defaults(RSI_TF_='15'), SCHEMA)
        validate_strategy(defaults(RSI_TF_='15||5||10||15||N'), SCHEMA)             # N runs the first field only
        validate_strategy(defaults(EMA_TF_='60||60||180||240||N', ADX_TF_='15||0||0||240||N'), SCHEMA)

    def test_a_value_ladder_that_is_not_an_item_run_is_refused(self):
        # ENUM_MODE_SAMPLING declares 0, -1, 1, 99: -1..1 by 1 is all declared, but not consecutive items.
        self.assertIn('Trailing_Sample_Period=0||-1||1||1||Y', self.refused(Trailing_Sample_Period='0||-1||1||1||Y'))
        # ENUM_MODE_PRICE declares 1, 6, 7, 5: 6..7 is consecutive items and values.
        validate_strategy(defaults(EMA_Price='6||6||1||7||Y'), SCHEMA)

    def test_undeclared_rungs_keep_their_existing_message(self):
        with self.assertRaisesRegex(ValueError, 'ATR_TF_: Optimization ladder contains undeclared enum values'):
            validate_strategy(defaults(ATR_TF_='5||5||5||15||Y'), SCHEMA)

    def test_native_forms_listed_per_enum(self):
        self.assertEqual(native_enum_ladders(TFS), [(0, 1)])
        self.assertEqual(native_enum_ladders([0, 1, 2]), [(0, 1), (0, 2), (1, 2)])
        self.assertEqual(native_enum_ladders([1, 6, 7, 5]), [(6, 7)])
        schema = dict(inputs=dict(Gap=dict(type='ENUM_GAP', enum_choices={'A': 0, 'B': 10})))
        with self.assertRaisesRegex(ValueError, 'none: no two consecutive items of ENUM_GAP have consecutive values'):
            check_enum_ladders(dict(Gap='0||0||10||10||Y'), schema)


class EnumLadderPathTests(unittest.TestCase):
    """validate-set --require-optimization, prepare-batch and seed-prepare refuse the same SET."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def test_validate_set_require_optimization(self):
        bad = write_set(self.root / 'bad.set', defaults(EA_Desc='Prove', RSI_TF_='15||5||10||15||Y'))
        with self.assertRaisesRegex(ValueError, '^' + ENUM_LADDER_CODE + ': .*RSI_TF_=15'):
            validate_set(bad, SCHEMA, POLICY, require_optimization=True)
        good = write_set(self.root / 'good.set', defaults(EA_Desc='Prove', Active_Time_Weekday='4||3||1||4||Y'))
        self.assertEqual(validate_set(good, SCHEMA, POLICY, require_optimization=True)['active_axes'],
                         {'Active_Time_Weekday': 2})


class CompactControllerPaths(unittest.TestCase):
    """The real prepare-batch and seed-prepare routes, on the portable synthetic controller."""
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        self.c.schema['inputs']['RSI_TF_'] = dict(type='ENUM_MODE_TFs', optimizable=True,
                                                  enum_choices=dict(zip(['TF_Current', 'TF_M1', 'TF_M5', 'TF_M15', 'TF_H1', 'TF_H4'], TFS)))
        self.c.store.input_schema_hash = sha(self.c.schema)

    def tearDown(self): self.fixture.tearDown()

    def source(self, name, tf):
        path = self.fixture.root / name
        path.write_bytes(('EA_Desc=Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\nRSI_TF_=' + tf + '\r\n').encode('utf-16'))
        return path

    def test_prepare_batch_refuses_and_freezes_nothing(self):
        from studio_batch import prepare_batch
        plan = self.fixture.root / 'plan.json'
        plan.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=[
            dict(set_path=str(self.source('bad.set', '15||5||10||15||Y')), tester=self.fixture.tester)])))
        queue = copy.deepcopy(self.c.state()['queue'])
        with self.assertRaisesRegex(ValueError, '^' + ENUM_LADDER_CODE + ': .*RSI_TF_=15\\|\\|5\\|\\|10\\|\\|15\\|\\|Y'):
            prepare_batch(self.c, 'enum-bad', plan)
        self.assertEqual(self.c.state()['queue'], queue)
        plan.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=[
            dict(set_path=str(self.source('good.set', '15||5||10||15||N')), tester=self.fixture.tester)])))
        self.assertEqual(prepare_batch(self.c, 'enum-good', plan)['member_count'], 1)

    def seed_prepare(self, batch_id, tf):
        """The public `seed-prepare` CLI route (as test_seed_cli drives it), on this controller's schema."""
        tester = self.fixture.tester | {'ForwardMode': 0, 'ForwardDate': ''}
        plan = dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=30, cutoff=dict(min_fitness=0, min_trades=1),
                    jobs=[dict(set_path=str(self.source(batch_id + '.set', tf)), tester=tester, frame_target=2)])
        path = self.fixture.root / (batch_id + '-plan.json'); path.write_text(json.dumps(plan))
        self.c.store.close(); self.c.store = None
        process = SimpleNamespace(inspect=Mock(return_value=None), start=Mock(side_effect=AssertionError('no launch')),
                                  close=Mock(side_effect=AssertionError('no close')))
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), \
                patch('studio_seed_process.WindowsSeedProcess', return_value=process), redirect_stdout(output):
            code = goat_studio.main(['--installation', str(self.fixture.path), 'seed-prepare', '--batch-id', batch_id,
                                     '--plan', str(path)])
        return code, json.loads(output.getvalue())

    def test_seed_prepare_refuses_a_stepped_tf_enum(self):
        code, result = self.seed_prepare('enum-seed', '15||5||10||15||Y')
        self.assertEqual(code, 2, result)
        self.assertTrue(result['error'].startswith(ENUM_LADDER_CODE + ': '), result['error'])
        self.assertIn('RSI_TF_=15||5||10||15||Y', result['error'])
        self.assertFalse((Path(self.fixture.receipt['controller_state_root']) / 'seeds/enum-seed').exists())

    def test_seed_prepare_accepts_the_native_tf_ladder(self):
        code, result = self.seed_prepare('enum-seed-ok', '1||0||1||1||Y')
        self.assertEqual((code, result['result']['status']), (0, 'prepared'), result)


if __name__ == '__main__':
    unittest.main()
