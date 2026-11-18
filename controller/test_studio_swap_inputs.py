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
        # An unreadable lots value (blank, non-numeric, non-finite) is unknown: held_lots None, and the hold-back stands
        # (Codex P2 on GOAT-EA#352: it must never turn a swap-free run into `unmeasured`, which is not held back).
        for n, bad in enumerate(('', 'x', 'nan', 'inf')):
            with self.subTest(lots=bad):
                path = self.edited(lambda r, bad=bad: r.update(lots=bad) if r['deal_entry'] == '0' else None, name='bad-%d.csv' % n)
                result = si.classify(path)
                self.assertEqual((result['verdict'], result['held_lots']), ('swap_free_inputs', None))
                self.assertTrue(si.held_back(result))
        first_only = self.edited(lambda r: r.update(lots='') if r['position_id'] == HELD_POSITION and r['deal_entry'] == '0' else None, name='first.csv')
        result = si.classify(first_only)
        self.assertEqual((result['verdict'], result['held_lots']), ('swap_free_inputs', None))
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
        self.assertEqual(si.HELD_BACK, {'swap_free_inputs', 'swap_free_by_design', 'unreadable'})

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

    def test_no_deals_csv_is_unmeasured_never_a_flag(self):
        for name, path in dict(none=None, empty='', missing=Path(self.tmp.name) / 'gone' / 'deals.csv').items():
            with self.subTest(name=name):
                result = si.classify(path, live_spec=SWAP_FREE_SPEC)
                self.assertEqual((result['verdict'], result['positions'], result['held_over_rollover']), ('unmeasured', None, None))
                self.assertFalse(si.held_back(result))
                self.assertIn('not a flag', result['plain'])

    def test_a_permission_error_is_unreadable_and_a_vanished_file_unmeasured_without_any_existence_probe(self):
        # Codex P2 on GOAT-EA#353: exists()/is_file() raise PermissionError on Python <= 3.13 and return False on 3.14
        # for a file in a directory we may not read; the read itself must decide. Simulated on the real fixture path.
        from unittest import mock
        real_stat = Path.stat
        def denied(self, *args, **kwargs):
            if self.name == 'deals.csv' or str(self).endswith('swap-free-inputs.deals.csv'):
                raise PermissionError(13, 'Permission denied')
            return real_stat(self, *args, **kwargs)
        with mock.patch.object(Path, 'stat', denied), mock.patch.object(Path, 'exists', side_effect=AssertionError('no probe')), \
                mock.patch.object(Path, 'is_file', side_effect=AssertionError('no probe')):
            result = si.classify(SWAP_FREE)
            self.assertEqual(result['verdict'], 'unreadable')
            self.assertTrue(si.held_back(result))
            self.assertIn('could not be read', result['plain'])
            # capture_deals never probes the file: it hands classify() the path of a complete capture.
            capture = dict(capture=dict(complete=True, path=str(Path(self.tmp.name) / 'cap' / 'manifest.json')))
            self.assertEqual(si.capture_deals(capture), str(Path(self.tmp.name) / 'cap' / 'deals.csv'))
        # A complete capture whose deals.csv does not exist: the read raises FileNotFoundError -> unmeasured, not a flag.
        capture = dict(capture=dict(complete=True, path=str(Path(self.tmp.name) / 'gone' / 'manifest.json')))
        result = si.classify(si.capture_deals(capture))
        self.assertEqual((result['verdict'], si.held_back(result)), ('unmeasured', False))
        self.assertIsNone(si.capture_deals(dict(capture=dict(complete=False, path='x'))))

    def test_a_present_but_unreadable_or_malformed_deals_csv_is_unreadable_and_held_back(self):
        # Claude-Mac goatai#2750 6976984165: the catch-up's own verdict parsers tolerate some of these (deal_window compares
        # deal_entry as a string and takes Decimal('inf')), so the swap check must hold such a run back, never pass it through.
        first_close = lambda r: r['position_id'] == HELD_POSITION and r['deal_entry'] != '0'
        cases = dict(no_swap_column=self.edited(lambda r: None, name='a.csv', drop=('swap',)),
                     bad_number=self.edited(lambda r: r.update(swap='x') if r['position_id'] == HELD_POSITION else None, name='b.csv'),
                     nan_swap=self.edited(lambda r: r.update(swap='nan') if r['position_id'] == HELD_POSITION else None, name='c.csv'),
                     inf_swap_on_every_close=self.edited(lambda r: r.update(swap='inf') if r['deal_entry'] != '0' else None, name='e.csv'),
                     every_entry_bad=self.edited(lambda r: r.update(deal_entry='?'), name='d.csv'),
                     one_closing_entry_x=self.edited(lambda r: r.update(deal_entry='x') if first_close(r) else None, name='f.csv'),
                     one_time_x=self.edited(lambda r: r.update(server_time_msc='x') if first_close(r) else None, name='g.csv'))
        folder = Path(self.tmp.name) / 'a folder'   # present, but not readable as a file (an OSError on read)
        folder.mkdir()
        cases['a_folder'] = folder
        for name, path in cases.items():
            with self.subTest(name=name):
                result = si.classify(path, live_spec=SWAP_FREE_SPEC)
                self.assertEqual((result['verdict'], result['positions'], result['held_over_rollover']), ('unreadable', None, None))
                self.assertTrue(si.held_back(result))
                self.assertIn('Held back until the capture is re-read', result['plain'])
                self.assertNotIn(self.tmp.name, result['plain'])

    def test_verdict_readers_and_the_counter_and_guard_agree(self):
        self.assertEqual((si.verdict_of(dict(verdict='swap_free_inputs')), si.verdict_of('swap_charged'), si.verdict_of(None),
                          si.verdict_of(5)), ('swap_free_inputs', 'swap_charged', None, None))
        self.assertTrue(si.held_back('swap_free_by_design') and si.held_back('unreadable')
                        and not si.held_back('unmeasured') and not si.held_back(None))
        self.assertEqual(board.SWAP_HELD_BACK, si.HELD_BACK)                  # the counter repeats the set; they must agree
        self.assertLessEqual({'swapInputs', 'swap_inputs'}, METRIC_KEYS)     # window-derived numbers: redacted in a lock
        self.assertEqual(set(si.VERDICTS), {'swap_charged', 'not_exercised', 'swap_free_inputs', 'swap_free_by_design',
                                            'unmeasured', 'unreadable'})


def ea_double(value):
    """A double as B56's swap-spec writes it: DoubleToString(x,-16), 17 significant digits in MQL's scientific form."""
    mantissa, exponent = ('%.16e' % value).split('e')
    return '%se%s%02d' % (mantissa, exponent[0], abs(int(exponent)))


def spec_lines(mode=1, long=-12.4, short=3.1, rollover=3, contract=100000.0, digits=3, point=0.001):
    """B56's seven run.csv lines (GOAT_SequenceExport.mqh swap-spec block), in its order and format."""
    return ['symbol_swap_mode,%d' % mode, 'symbol_swap_long,' + ea_double(long), 'symbol_swap_short,' + ea_double(short),
            'symbol_swap_rollover3days,%d' % rollover, 'symbol_contract_size,' + ea_double(contract),
            'symbol_digits,%d' % digits, 'symbol_point,' + ea_double(point)]


class RecordedSpecTests(unittest.TestCase):
    """B56 swap-spec (GOAT-EA#354; Claude-Mac goatai#2750 6978371254): the spec the tester ran on, from the run.csv beside
    deals.csv, judged per side. SWAP_FREE holds 12 long and 3 short positions over a rollover, all at zero swap;
    SWAP_CHARGED holds 8 short, all charged; NOT_EXERCISED holds none."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.n = 0

    def capture(self, deals=SWAP_FREE, run=None, change=None, drop=(), keep=None):
        """A capture folder: deals.csv (a fixture, optionally edited, or only the rows ``keep`` accepts) and, unless
        ``run`` is None, a run.csv of a pre-B56 header plus ``run`` (a list of lines, or bytes written as they are)."""
        self.n += 1
        folder = Path(self.tmp.name) / ('cap%d' % self.n)
        folder.mkdir()
        with deals.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = [f for f in reader.fieldnames if f not in drop], [r for r in reader if keep is None or keep(r)]
        for row in rows:
            if change:
                change(row)
        with (folder / 'deals.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\r\n')
            writer.writeheader()
            writer.writerows(rows)
        if isinstance(run, bytes):
            (folder / 'run.csv').write_bytes(run)
        elif run is not None:
            head = ['key,value', 'schema,goat-native-sequence-capture-v1', 'time_basis,broker-server-time; NOT UTC',
                    'symbol,GBPJPY', 'initial_orders,0']
            (folder / 'run.csv').write_bytes(('﻿' + '\r\n'.join(head + run) + '\r\n').encode('utf-8'))
        return folder / 'deals.csv'

    def test_a_capture_without_a_recorded_spec_reads_exactly_as_before(self):
        for deals in (SWAP_FREE, SWAP_CHARGED, NOT_EXERCISED):
            before = si.classify(deals)
            for run in (None, []):   # no run.csv; a pre-B56 run.csv without the keys
                with self.subTest(deals=deals.name, run=run):
                    result = si.classify(self.capture(deals, run=run))
                    self.assertEqual((result['verdict'], result['plain'], result['held_over_rollover'], result['with_swap']),
                                     (before['verdict'], before['plain'], before['held_over_rollover'], before['with_swap']))
                    self.assertEqual((result['tester_spec'], result['sides'], result['notes']), (None, None, []))

    def test_the_ea_format_reads_back_exactly(self):
        # 17 significant digits show the binary value (-7.35 is written -7.3499999999999996e+00) and read back exactly.
        self.assertEqual(ea_double(-7.35), '-7.3499999999999996e+00')
        self.assertEqual(float(ea_double(-7.35)), -7.35)
        spec = si.tester_spec(self.capture(run=spec_lines(mode=1, long=-7.35, short=0.000123, contract=100000.0, point=0.001)))
        self.assertEqual(spec, dict(swap_mode=1, swap_long=-7.35, swap_short=0.000123, swap_rollover3days=3,
                                    contract_size=100000.0, digits=3, point=0.001))
        self.assertIsNone(si.tester_spec(self.capture(run=None)))
        self.assertIsNone(si.tester_spec(self.capture(run=[])))

    def test_a_spec_that_charges_both_sides_against_zero_booked_swap_is_a_contradiction_held_back(self):
        result = si.classify(self.capture(run=spec_lines(mode=1, long=-12.4, short=3.1)))
        self.assertEqual((result['verdict'], result['notes']), ('swap_free_inputs', ['spec_contradiction']))
        self.assertEqual(result['sides'], dict(long=dict(held=12, with_swap=0, tester_charges=True, verdict='swap_free_inputs'),
                                               short=dict(held=3, with_swap=0, tester_charges=True, verdict='swap_free_inputs')))
        self.assertTrue(si.held_back(result))
        self.assertIn('the booked swap decides', result['plain'])
        self.assertIn('Held back until re-run', result['plain'])

    def test_a_spec_that_charges_nothing_holds_back_from_the_first_held_position_by_design_only_where_live_agrees(self):
        disabled = self.capture(run=spec_lines(mode=0, long=-12.4, short=3.1))   # rates set, swap disabled
        result = si.classify(disabled)
        self.assertEqual((result['verdict'], result['notes']), ('swap_free_inputs', []))
        self.assertEqual([result['sides'][s]['tester_charges'] for s in si.SIDES], [False, False])
        self.assertIn('as the spec says', result['plain'])
        self.assertEqual(si.classify(disabled, live_spec=SWAP_FREE_SPEC)['verdict'], 'swap_free_by_design')
        mixed = si.classify(disabled, live_spec=dict(swap_long=0.0, swap_short=1.5))
        self.assertEqual((mixed['verdict'], mixed['sides']['long']['verdict'], mixed['sides']['short']['verdict']),
                         ('swap_free_inputs', 'swap_free_by_design', 'swap_free_inputs'))
        # No 3-position floor once the spec says it: one held position on a side the spec does not charge is enough.
        one = self.capture(run=spec_lines(mode=0), keep=lambda r: r['position_id'] in (HELD_POSITION, SAME_DAY_POSITION))
        result = si.classify(one)
        self.assertEqual((result['verdict'], result['held_over_rollover']), ('swap_free_inputs', 1))
        self.assertEqual(si.classify(self.capture(run=None, keep=lambda r: r['position_id'] in (HELD_POSITION, SAME_DAY_POSITION)))['verdict'],
                         'not_exercised')   # the same deals without the spec: too few to tell

    def test_note_2_every_held_position_on_the_zero_side_agrees_with_the_spec_and_says_so(self):
        # Claude-Mac's note 2: the tester spec charges one side only and every held position sat on the other side.
        all_long = lambda r: r.update(deal_type='0') if r['deal_entry'] == '0' else None
        deals = self.capture(run=spec_lines(mode=1, long=0.0, short=3.1), change=all_long)
        result = si.classify(deals)
        self.assertEqual((result['verdict'], result['notes']), ('swap_free_inputs', []))
        self.assertEqual((result['sides']['long']['verdict'], result['sides']['short']['verdict']), ('swap_free_inputs', 'not_held'))
        self.assertIn('long: the spec charges no swap (mode 1, swap long 0) and the 15 held positions closed with zero swap, '
                      'as the spec says; no live spec shows this side swap-free', result['plain'])
        self.assertTrue(si.held_back(result))
        by_design = si.classify(deals, live_spec=dict(swap_long=0, swap_short=-2.0))
        self.assertEqual(by_design['verdict'], 'swap_free_by_design')
        self.assertIn('the live spec agrees', by_design['plain'])
        self.assertTrue(si.held_back(by_design))

    def test_one_side_charged_does_not_clear_a_side_that_ran_swap_free(self):
        # Both sides held: the tester spec charges short (and the short positions paid) but not long, where 12 positions
        # were held at zero swap. The long side's stale zero still makes the result optimistic: held back.
        with SWAP_FREE.open(encoding='utf-8', newline='') as stream:
            shorts = {r['position_id'] for r in csv.DictReader(stream) if r['deal_entry'] == '0' and r['deal_type'] == '1'}
        paid_short = lambda r: r.update(swap='-1.25') if r['position_id'] in shorts and r['deal_entry'] != '0' else None
        result = si.classify(self.capture(run=spec_lines(mode=1, long=0.0, short=-4.0), change=paid_short))
        self.assertEqual((result['sides']['long']['verdict'], result['sides']['short']['verdict']), ('swap_free_inputs', 'swap_charged'))
        self.assertEqual((result['verdict'], result['notes']), ('swap_free_inputs', []))
        self.assertTrue(si.held_back(result))
        # Without the recorded spec the same deals read swap_charged: the per-side reading is what catches it.
        self.assertEqual(si.classify(self.capture(run=None, change=paid_short))['verdict'], 'swap_charged')

    def test_charged_runs_and_runs_that_never_held_overnight(self):
        charged = si.classify(self.capture(SWAP_CHARGED, run=spec_lines(mode=1, long=-12.4, short=3.1)))
        self.assertEqual((charged['verdict'], charged['notes'], charged['sides']['short']['verdict'], charged['sides']['long']['verdict']),
                         ('swap_charged', [], 'swap_charged', 'not_held'))
        # A spec that says no swap, against deals that booked it: the deals decide, the note says the spec disagrees.
        booked = si.classify(self.capture(SWAP_CHARGED, run=spec_lines(mode=0)))
        self.assertEqual((booked['verdict'], booked['notes']), ('swap_charged', ['spec_contradiction']))
        self.assertFalse(si.held_back(booked))
        # A zero-swap spec on a run that held nothing overnight is no hold-back: swap could not touch its result.
        for spec in (spec_lines(mode=0), spec_lines(mode=1)):
            result = si.classify(self.capture(NOT_EXERCISED, run=spec))
            self.assertEqual((result['verdict'], result['sides']['long']['verdict'], result['sides']['short']['verdict']),
                             ('not_exercised', 'not_held', 'not_held'))
            self.assertFalse(si.held_back(result))
        # A charging side with fewer than min_roll held positions, none paid: too few to tell, as without a spec (SWAP_FREE
        # holds 3 short; with min_roll 4 the charging short side cannot tell, the uncharged long side still holds it back).
        few = si.classify(self.capture(run=spec_lines(mode=1, long=0.0, short=3.1)), min_roll=4)
        self.assertEqual((few['verdict'], few['notes'], few['sides']['short']['verdict'], few['sides']['long']['verdict']),
                         ('swap_free_inputs', [], 'not_exercised', 'swap_free_inputs'))
        self.assertIn('short: the spec charges swap short 3.1; only 3 held positions, none with swap (4 needed to tell)', few['plain'])

    def test_an_unreadable_or_malformed_recorded_spec_is_unreadable_and_held_back(self):
        good = spec_lines()
        cases = dict(partial=good[:-1], duplicate=good + good[:1], mode_not_whole=['symbol_swap_mode,1.0'] + good[1:],
                     nan_rate=good[:1] + ['symbol_swap_long,nan'] + good[2:], inf_rate=good[:2] + ['symbol_swap_short,inf'] + good[3:],
                     rollover_7=good[:3] + ['symbol_swap_rollover3days,7'] + good[4:],
                     contract_zero=good[:4] + ['symbol_contract_size,' + ea_double(0.0)] + good[5:],
                     point_negative=good[:6] + ['symbol_point,' + ea_double(-0.001)],
                     empty_digits=good[:5] + ['symbol_digits,'] + good[6:])
        paths = {name: self.capture(run=lines) for name, lines in cases.items()}
        paths['not_utf8'] = self.capture(run=b'key,value\r\nsymbol_swap_mode,\xff\xfe\r\n')
        folder_run = self.capture(run=None)
        (folder_run.parent / 'run.csv').mkdir()                       # present, but not readable as a file
        paths['run_csv_a_folder'] = folder_run
        paths['side_unreadable'] = self.capture(run=good, drop=('deal_type',))
        for name, path in paths.items():
            with self.subTest(name=name):
                result = si.classify(path, live_spec=SWAP_FREE_SPEC)
                self.assertEqual(result['verdict'], 'unreadable')
                self.assertTrue(si.held_back(result))
                self.assertIn('Held back until the capture is re-read', result['plain'])
                self.assertNotIn(self.tmp.name, result['plain'])
        # Without a recorded spec the side is never needed: the same deals read as before.
        self.assertEqual(si.classify(self.capture(run=None, drop=('deal_type',)))['verdict'], 'swap_free_inputs')

    def test_the_spec_is_read_beside_the_capture_deals_without_an_existence_probe(self):
        from unittest import mock
        deals = self.capture(run=spec_lines(mode=0))
        export = dict(capture=dict(complete=True, path=str(deals.parent / 'manifest.json')))
        with mock.patch.object(Path, 'exists', side_effect=AssertionError('no probe')), \
                mock.patch.object(Path, 'is_file', side_effect=AssertionError('no probe')):
            result = si.classify(si.capture_deals(export))
        self.assertEqual((result['verdict'], result['tester_spec']['swap_mode']), ('swap_free_inputs', 0))


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
        # A present but malformed capture is held back the same way (verdict `unreadable`; ClassifyTests builds the files).
        result = sc.CatchupRunner._oos_rule(original, retest, spec, dict(verdict='held_up', swapInputs=dict(verdict='unreadable')))
        self.assertEqual((result['status'], result['firstFailingCause']), ('not_judged', 'unreadable'))
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
