"""INV-SWAP-01: the swap a tester run was charged (studio_swap_inputs) and the hooks that hold a swap-free run back.

The classifier is pinned on rows cut from three real tester captures (controller/fixtures/swap-inputs, README there):
a GBPJPY re-test the tester charged no swap (swap_free_inputs), a USDJPY re-test that was charged swap (swap_charged)
and an index run that never held a position over a rollover (not_exercised). The hooks are pinned on the
real catch-up (FormulaCase: the CatchupRunner prepares, a fake terminal writes each re-test and the runner collects,
judges and stores it) and the real build-migration collection (MigrationCase).
"""
import csv
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest

import hunt_board_count as board
import studio_build_migration as bm
import studio_catchup as sc
from studio_evidence import read_export
from studio_heldout_guard import METRIC_KEYS
import studio_oos_recount as recount
import studio_swap_inputs as si
from studio_installation import read_json
from test_studio_build_migration import MigrationCase, V147_EA
from test_studio_oos_recount import FormulaCase
from test_studio_oos_windows import RetestFixture

FIXTURES = Path(__file__).parent / 'fixtures' / 'swap-inputs'
SWAP_FREE = FIXTURES / 'swap-free-inputs.deals.csv'          # fri1009-live3, GBPJPY: charged no swap at all
SWAP_CHARGED = FIXTURES / 'swap-charged.deals.csv'           # w12q-t3-d-1113, USDJPY: swap charged
NOT_EXERCISED = FIXTURES / 'not-exercised.deals.csv'         # exp02-mig-banker-1113-v2, WS30: never held overnight
SWAP_FREE_SPEC = dict(swap_long=0.0, swap_short=0.0)
CHARGING_SPEC = dict(swap_long=-12.4, swap_short=3.1)
HELD_POSITION, SAME_DAY_POSITION = '18', '2'                 # in SWAP_FREE: opened 2025-10-15, closed 10-16 / both 10-06


def overnight(deals):
    """test_studio_catchup_verdict.trading() pairs with every Monday-Thursday close moved from 11:0n to 01:0n the next
    server day: the same entries, results and windows, now held over a rollover and charged no swap."""
    out = []
    for entry, close in zip(deals[0::2], deals[1::2]):
        weekday = datetime.fromtimestamp(entry[0] / 1000, tz=timezone.utc).weekday()
        out += [entry, (close[0] + 14 * 3600 * 1000,) + tuple(close[1:]) if weekday < 4 else close]
    return out


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def edited(self, change, source=SWAP_FREE, name='deals.csv', drop=()):
        """A copy of a fixture with ``change(row)`` applied to every row and the ``drop`` columns left out."""
        with source.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = [f for f in reader.fieldnames if f not in drop], list(reader)
        for row in rows:
            change(row)
        path = Path(self.tmp.name) / name
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_a_real_zero_swap_run_is_swap_free_inputs_and_held_back(self):
        result = si.classify(SWAP_FREE)
        self.assertEqual({k: result[k] for k in ('schema', 'verdict', 'positions', 'held_over_rollover', 'with_swap', 'swap_total',
                                                  'live_spec', 'min_roll')},
                         dict(schema='goat-swap-inputs-v1', verdict='swap_free_inputs', positions=40, held_over_rollover=15,
                              with_swap=0, swap_total=0.0, live_spec=None, min_roll=3))
        self.assertTrue(si.held_back(result))
        self.assertIn('Held back until re-run', result['plain'])
        # The held positions' opening lots are reported, so a reader can see the known false hold-backs (INV-SWAP-01).
        self.assertEqual(result['held_lots'], 0.6)
        self.assertIn('(0.60 lots opened in all)', result['plain'])

    def test_held_lots_are_the_opening_lots_of_held_positions_only_and_optional(self):
        self.assertEqual(si.classify(SWAP_CHARGED)['held_lots'], 0.74)
        self.assertEqual(si.classify(NOT_EXERCISED)['held_lots'], 0.0)
        # A capture without a lots column keeps its verdict; held_lots is then unknown, never a guess.
        no_lots = self.edited(lambda r: None, name='nolots.csv', drop=('lots',))
        result = si.classify(no_lots)
        self.assertEqual((result['verdict'], result['held_lots']), ('swap_free_inputs', None))
        self.assertNotIn('lots opened', result['plain'])
        # Doubling a held position's opening lots moves held_lots; doubling a same-day position's does not.
        held = self.edited(lambda r: r.update(lots=str(float(r['lots']) * 2)) if r['position_id'] == HELD_POSITION and r['deal_entry'] == '0' else None, name='h.csv')
        same = self.edited(lambda r: r.update(lots=str(float(r['lots']) * 2)) if r['position_id'] == SAME_DAY_POSITION and r['deal_entry'] == '0' else None, name='s.csv')
        self.assertGreater(si.classify(held)['held_lots'], 0.6)
        self.assertEqual(si.classify(same)['held_lots'], 0.6)
        self.assertIsNone(si.classify(None)['held_lots'])

    def test_a_real_swap_charged_run_is_swap_charged(self):
        result = si.classify(SWAP_CHARGED)
        self.assertEqual((result['verdict'], result['positions'], result['held_over_rollover'], result['with_swap'], result['swap_total']),
                         ('swap_charged', 40, 8, 8, -7.59))
        self.assertFalse(si.held_back(result))
        self.assertIn('8 of the 8 positions held over a server rollover closed with swap (-7.59 in all)', result['plain'])

    def test_a_real_run_that_never_held_overnight_is_not_exercised_and_never_a_flag(self):
        result = si.classify(NOT_EXERCISED)
        self.assertEqual((result['verdict'], result['positions'], result['held_over_rollover'], result['with_swap']),
                         ('not_exercised', 40, 0, 0))
        self.assertFalse(si.held_back(result))
        self.assertIn('not a flag', result['plain'])
        # The floor is MIN_ROLL held positions, inclusive, on the real swap-free run (15 held).
        self.assertEqual(si.classify(SWAP_FREE, min_roll=15)['verdict'], 'swap_free_inputs')
        self.assertEqual(si.classify(SWAP_FREE, min_roll=16)['verdict'], 'not_exercised')
        with self.assertRaises(ValueError):
            si.classify(SWAP_FREE, min_roll=0)

    def test_a_live_swap_free_spec_makes_it_swap_free_by_design_still_held_back(self):
        result = si.classify(SWAP_FREE, live_spec=SWAP_FREE_SPEC)
        self.assertEqual((result['verdict'], result['live_spec']), ('swap_free_by_design', SWAP_FREE_SPEC))
        self.assertNotEqual(result['verdict'], si.classify(SWAP_FREE)['verdict'])
        self.assertTrue(si.held_back(result))
        self.assertIn('Held back until re-run or reviewed', result['plain'])
        # A spec that charges swap (or one that is not a clean pair of zeros) leaves the stale-spec reading.
        for spec in (CHARGING_SPEC, dict(swap_long=0.0), dict(swap_long='0', swap_short='0'), dict(swap_long=False, swap_short=0.0),
                     'not a spec'):
            with self.subTest(spec=spec):
                self.assertEqual(si.classify(SWAP_FREE, live_spec=spec)['verdict'], 'swap_free_inputs')
        self.assertEqual(si.classify(SWAP_FREE, live_spec=CHARGING_SPEC)['live_spec'], CHARGING_SPEC)
        # The spec never overrides the deals: charged stays charged, too few stays too few.
        self.assertEqual(si.classify(SWAP_CHARGED, live_spec=SWAP_FREE_SPEC)['verdict'], 'swap_charged')
        self.assertEqual(si.classify(NOT_EXERCISED, live_spec=SWAP_FREE_SPEC)['verdict'], 'not_exercised')
        self.assertEqual(si.HELD_BACK, {'swap_free_inputs', 'swap_free_by_design'})

    def test_one_held_position_with_swap_makes_the_run_swap_charged_a_same_day_one_does_not(self):
        held = self.edited(lambda r: r.update(swap='-0.01') if r['position_id'] == HELD_POSITION and r['deal_entry'] != '0' else None)
        result = si.classify(held)
        self.assertEqual((result['verdict'], result['with_swap'], result['swap_total']), ('swap_charged', 1, -0.01))
        same_day = self.edited(lambda r: r.update(swap='-5.0') if r['position_id'] == SAME_DAY_POSITION and r['deal_entry'] != '0' else None)
        self.assertEqual(si.classify(same_day)['verdict'], 'swap_free_inputs')   # swap is only read on held positions
        # Swap on the opening deal is not read either: the tester books it on the closing deals.
        opening = self.edited(lambda r: r.update(swap='-1.0') if r['deal_entry'] == '0' else None)
        self.assertEqual(si.classify(opening)['verdict'], 'swap_free_inputs')

    def test_the_server_date_is_the_utc_date_of_the_epoch(self):
        self.assertEqual((si.server_day(1760523900078), si.server_day(1760640151108)), (date(2025, 10, 15), date(2025, 10, 16)))
        self.assertEqual(si.server_day(1760572799999), date(2025, 10, 15))     # 23:59:59.999 is still the same day
        self.assertEqual(si.server_day(1760572800000), date(2025, 10, 16))     # 00:00 is the rollover

    def test_a_missing_or_unreadable_deals_csv_is_unmeasured_never_an_exception(self):
        cases = dict(none=None, missing=Path(self.tmp.name) / 'gone' / 'deals.csv',
                     no_swap_column=self.edited(lambda r: None, name='a.csv', drop=('swap',)),
                     bad_number=self.edited(lambda r: r.update(swap='x') if r['position_id'] == HELD_POSITION else None, name='b.csv'),
                     not_finite=self.edited(lambda r: r.update(swap='nan') if r['position_id'] == HELD_POSITION else None, name='c.csv'),
                     bad_entry=self.edited(lambda r: r.update(deal_entry='?'), name='d.csv'))
        folder = Path(self.tmp.name) / 'a folder'
        folder.mkdir()
        cases['a_folder'] = folder
        for name, path in cases.items():
            with self.subTest(name=name):
                result = si.classify(path, live_spec=SWAP_FREE_SPEC)
                self.assertEqual((result['verdict'], result['positions'], result['held_over_rollover']), ('unmeasured', None, None))
                self.assertFalse(si.held_back(result))
                self.assertIn('not a flag', result['plain'])
                self.assertNotIn(self.tmp.name, result['plain'])

    def test_verdict_readers_and_the_counter_and_guard_agree(self):
        self.assertEqual((si.verdict_of(dict(verdict='swap_free_inputs')), si.verdict_of('swap_charged'), si.verdict_of(None),
                          si.verdict_of(5)), ('swap_free_inputs', 'swap_charged', None, None))
        self.assertTrue(si.held_back('swap_free_by_design') and not si.held_back('unmeasured') and not si.held_back(None))
        self.assertEqual(board.SWAP_HELD_BACK, si.HELD_BACK)                  # the counter repeats the set; they must agree
        self.assertLessEqual({'swapInputs', 'swap_inputs'}, METRIC_KEYS)     # window-derived numbers: redacted in a lock
        self.assertEqual(set(si.VERDICTS), {'swap_charged', 'not_exercised', 'swap_free_inputs', 'swap_free_by_design', 'unmeasured'})


class OosRuleHookTests(RetestFixture, unittest.TestCase):
    """CatchupRunner._oos_rule: a held-back re-test is never judged, so it never reads pass."""

    def test_a_held_back_retest_is_not_judged_and_never_passes(self):
        original, retest = self.build()
        spec = dict(original=dict(tester=self.record['tester']))
        self.assertEqual(sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up'))['status'], 'pass')
        for live_spec, cause in ((None, 'swap_free_inputs'), (SWAP_FREE_SPEC, 'swap_free_by_design')):
            with self.subTest(cause=cause):
                swap = si.classify(SWAP_FREE, live_spec=live_spec)
                result = sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up', swapInputs=swap))
                self.assertEqual((result['status'], result['reasons'], result['firstFailingCause']), ('not_judged', [cause], cause))
                self.assertIn('held back until re-run (%s)' % cause, result['plain'])
                self.assertFalse(result['used_for_ranking'])
                self.assertEqual(result['boosContaminatedBy'], 'ea_trim')
                # A bare verdict string holds back too.
                self.assertEqual(sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up', swapInputs=cause))['status'],
                                 'not_judged')
        for harmless in (si.classify(SWAP_CHARGED), si.classify(NOT_EXERCISED), si.classify(None)):
            with self.subTest(harmless=harmless['verdict']):
                self.assertEqual(sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up', swapInputs=harmless))['status'],
                                 'pass')
        # A re-test that is not the same test stays no_data, held back or not.
        self.assertEqual(sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='not_comparable',
                                                                                 swapInputs=si.classify(SWAP_FREE)))['status'], 'no_data')

    def test_the_recount_reproduces_a_held_back_member_under_every_version(self):
        for version in (1, 2):
            judged = recount._judge(None, None, {}, {}, 'held_up', version, dict(verdict='swap_free_inputs'))
            self.assertEqual((judged['status'], judged['reasons']), ('not_judged', ['swap_free_inputs']))


class SwapFreeCatchup(FormulaCase):
    """The formula catch-up, with EURUSD's positions held overnight and charged no swap (a stale zero-swap spec)."""

    HELD = 'EURUSD'

    def trades(self, symbol, through):
        deals = super().trades(symbol, through)
        return overnight(deals) if symbol == self.HELD else deals

    def results(self, catchup_id='cu1'):
        state = read_json(self.runner.path(catchup_id) / 'state.json')
        manifest = read_json(self.runner.path(catchup_id) / 'manifest.json')
        return {spec['tester']['Symbol']: (spec, read_json(item['result']['path'])) for spec, item in zip(manifest['members'], state['members'])}


class CatchupSummaryHookTests(SwapFreeCatchup):
    def test_a_catchup_over_a_swap_free_capture_holds_the_member_back(self):
        manifest = self.run_catchup(symbols=('EURUSD', 'NZDUSD'))
        results = self.results()
        spec, held = results['EURUSD']
        summary, verdict = held['summary'], held['verdict']
        self.assertEqual((summary['swapInputs']['verdict'], summary['oos_rule'], verdict['oos_rule']['status']),
                         ('swap_free_inputs', 'not_judged', 'not_judged'))
        self.assertGreaterEqual(summary['swapInputs']['held_over_rollover'], 3)
        self.assertEqual(summary['swapInputs']['with_swap'], 0)
        self.assertEqual(verdict['oos_rule']['reasons'], ['swap_free_inputs'])
        self.assertIn('Held back until re-run', summary['plain'])
        self.assertIn('held back until re-run (swap_free_inputs)', verdict['oos_rule']['plain'])
        version = read_json(held['version_path'])
        self.assertEqual((version['swapInputs']['verdict'], version['oos_rule']['status']), ('swap_free_inputs', 'not_judged'))
        self.assertIn('Held back until re-run', version['verdict']['plain'])
        # Real negative: the same evidence without the hold-back passes the OOS rule; the hold-back alone stops it.
        original, retest = read_export(spec['original']['set_path']), read_export(held['path'])
        unheld = {k: v for k, v in verdict.items() if k != 'swapInputs'}
        self.assertEqual(sc.CatchupRunner._oos_rule(original, retest, spec, unheld, evidence_end=manifest['evidence_end']['iso'])['status'],
                         'pass')
        # The control member traded within each day: nothing to tell, judged as before.
        _, control = results['NZDUSD']
        self.assertEqual((control['summary']['swapInputs']['verdict'], control['summary']['oos_rule']), ('not_exercised', 'pass'))
        self.assertNotIn('Held back', control['summary']['plain'])
        # The recount reproduces the stored hold-back under both rule versions; the self-check stays clean.
        block, = recount.recount(self.controller.root, ['cu1'])['catchups']
        row = self.rows_by_symbol(block)['EURUSD']['oos_rule']
        self.assertEqual((row['stored']['status'], row['v1']['status'], row['v2']['status'], row['v2_matches_stored']),
                         ('not_judged', 'not_judged', 'not_judged', True))
        self.assertIs(block['counts']['self_check']['ok'], True)


class MigrationRecordHookTests(MigrationCase):
    def test_the_migration_record_carries_swap_inputs_for_the_retest_and_the_pinned_original(self):
        self.deals_by = dict(EURUSD=overnight(self.deals))     # the target build's re-test was charged no swap overnight
        _, manifest = self.run_all('bm1', self.mplan())
        record = read_json(Path(manifest['members'][0]['evidence_dir']) / bm.RECORD_FILE)
        self.assertEqual(record['retest']['swap_inputs']['verdict'], 'swap_free_inputs')
        self.assertEqual(record['retest']['swap_inputs']['schema'], 'goat-swap-inputs-v1')
        self.assertEqual(record['original']['swap_inputs']['verdict'], 'not_exercised')   # its pinned deals.csv: same-day trades
        for absent in ('verdict', 'oos_rule'):
            self.assertNotIn(absent, record)                   # still never a verdict

    def test_an_original_without_a_pinned_deals_csv_has_no_original_swap_inputs(self):
        plan = self.mplan(sets=[self.v147], originals=self.originals([self.v147], source_ea_sha256=V147_EA))
        self.write_run_manifest(aliases=('Rv1470001',), ea_sha256=V147_EA)
        _, manifest = self.run_all('bm1', plan)
        record = read_json(Path(manifest['members'][0]['evidence_dir']) / bm.RECORD_FILE)
        self.assertIsNone(record['original']['deals_sha256'])
        self.assertIsNone(record['original']['swap_inputs'])
        self.assertEqual(record['retest']['swap_inputs']['verdict'], 'not_exercised')


if __name__ == '__main__':
    unittest.main()
