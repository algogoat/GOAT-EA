"""broker-fit + equity_linear risk scaling (controller/contracts/broker-fit.md). Fixture-only: the MT5 SDK is a fake.

The real reference SET is controller/contracts/profile-fixtures/kestrel-b35-01.set: Balanced35 B35-01 Kestrel, UTF-16LE
with a BOM and CRLF, Mode_Lots=RiskperSeq, Risk=500.0, Lots_Max=20.0, Lots_Max_Cum=50.0, ATR distances, session hours.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import studio_broker_fit as bf
from studio_installation import contracts
from studio_refusal import Refusal

HERE = Path(__file__).parent
KESTREL = (HERE / 'contracts' / 'profile-fixtures' / 'kestrel-b35-01.set').read_bytes()
SCHEMA, _ = contracts('1.49')
# Tuesday 2026-10-13 14:00 UTC = 10:00 New York (EDT); the 6 h before it hold no rollover hour. Darwinex is UTC+3 then.
T0 = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc).timestamp()
DARWINEX_OFFSET = 180
TRACE = 'reference trace: median opening lot of the first 20 sequences'


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


def utf16(lines, newline='\r\n'):
    return b'\xff\xfe' + (newline.join(lines) + newline).encode('utf-16-le')


def kestrel_with(**changes):
    """The Kestrel SET with some values replaced (same encoding and line ends)."""
    text, encoding, bom = bf.set_encoding(KESTREL)
    lines = text.split('\r\n')
    for index, line in enumerate(lines):
        key = line.split('=', 1)[0]
        if key in changes:
            lines[index] = key + '=' + changes[key]
    return bom + '\r\n'.join(lines).encode(encoding)


NEUTRAL = dict(Active_Time_Weekday='6', Active_Time_Friday='7', Active_Time_ASIA='00:00-11:00', Active_Time_EU='10:00-19:00',
               Active_Time_US='15:00-24:00', Action_Dayend='0', Action_Friday='0', Trade_Friday='true', Mode_News='1',
               ATR_TF_='5', RSI_TF_='15', EMA_TF_='15', ADX_TF_='15', BB_TF_='5', MACD_TF_='1', RSI2_TF_='1')
FIXED = dict(Mode_Lots='0', Lots_Input='0.05', Sequence_MLPS_Hard_Close='false', Mode_Bias_Exit='0', Mode_Lots_Prog='1')


def reference(symbol='EURUSD', **changes):
    """The reference broker facts; startLot 0.1 from the trace unless a test removes it."""
    value = dict(server='Darwinex-Demo', symbol=symbol, digits=5, point=0.00001, tickSize=0.00001, tickValue=1, contractSize=100000,
                 volumeMin=0.01, volumeStep=0.01, volumeMax=50, typicalSpreadPts=8, currency='USD', startLot=0.1, startLotSource=TRACE)
    value.update(changes)
    return value


def member(raw, member_id='EURUSD.M1.kestrel', canonical='EURUSD', timeframe='M1', ref=None, name=None):
    return dict(memberId=member_id, symbol=canonical, canonicalSymbol=canonical, timeframe=timeframe,
                setName=name or 'GOAT V1.49 %s,%s_%s.set' % (canonical, timeframe, member_id), setSha256=hashlib.sha256(raw).hexdigest(),
                setBytes=len(raw), backtestTraceSha256=None, backtestTraceBytes=None, reference=ref or reference(canonical))


def manifest(members, **changes):
    value = dict(schema='goat-house-portfolio-v1', portfolioId='goat-fx-core', version=1, ea=dict(buildId='V1.49-b41', eaVersion='1.49'),
                 referenceAccount=dict(server='Darwinex-Demo', currency='USD', startingBalance=100000, leverage=200),
                 riskScaling='equity_linear', minEquity=2500, members=members)
    value.update(changes)
    return value


def symbol(name='EURUSD', **changes):
    base, profit = (name[:3], name[3:6]) if len(name) >= 6 and name[:6].isupper() else ('', '')
    value = dict(name=name, trade_mode=4, digits=5, point=0.00001, trade_contract_size=100000.0, trade_tick_size=0.00001,
                 trade_tick_value=1.0, volume_min=0.01, volume_step=0.01, volume_max=50.0, currency_base=base, currency_profit=profit,
                 swap_long=-6.5, swap_short=1.2, bid=1.1, ask=1.10008)
    value.update(changes)
    return value


def ticks(spreads=(8,), *, point=0.00001, end=T0, count=720, step=30, offset=DARWINEX_OFFSET):
    """count ticks every step seconds up to `end` (UTC), stamped with the server clock; spreads cycle in points."""
    return [dict(time=int(end - (count - i) * step + offset * 60), bid=1.1, ask=1.1 + spreads[i % len(spreads)] * point)
            for i in range(count)]


ACCOUNT = dict(login='123456', server='Darwinex-Demo', currency='USD', equity=100000.0, leverage=200, demo=True)

# A deterministic TEST publisher key (round 5 F2): tests sign their manifests with it and pin it in place of the house
# key (with_test_key). The production pin is checked separately (SignatureTests).
TEST_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
_TEST_DER = TEST_KEY.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
TEST_KEYS = (dict(keyId='goat-house-test-v1', alg='ed25519',
                  spkiPem=TEST_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
                  spkiDerSha256=hashlib.sha256(_TEST_DER).hexdigest()),)


def sign(data, key=TEST_KEY, key_id='goat-house-test-v1'):
    """The manifest with a publisher signature over the 32 raw bytes of its manifestSha256."""
    unsigned = {name: value for name, value in data.items() if name != 'signature'}
    sha = bf.manifest_sha256(unsigned)
    return dict(unsigned, signature=dict(alg='ed25519', keyId=key_id, sig=base64.b64encode(key.sign(bytes.fromhex(sha))).decode()))


def with_test_key():
    return patch.object(bf, 'HOUSE_SIGNING_KEYS', TEST_KEYS)


def reading(*, account=None, symbols=None, spread=None, history=None, offset=DARWINEX_OFFSET, margins=None, quotes=None,
            arrived=None, now=T0):
    """What read_broker returns, as plain data: every symbol has 6 h of ticks at `spread` points (default 8) and a last
    tick seen arriving at `now` (so the clock is proven)."""
    symbols = symbols if symbols is not None else [symbol()]
    names = [s['name'] for s in symbols]
    series = history if history is not None else {s['name']: ticks((spread or 8,), point=s['point'], offset=offset, end=now) for s in symbols}
    return dict(account=dict(account or ACCOUNT), symbols=symbols, ticks=series,
                quotes=quotes if quotes is not None else {name: int(now + offset * 60) for name in names},
                margins=margins if margins is not None else {name: 1000.0 for name in names},
                utc_now=now, arrived=arrived if arrived is not None else names)


def run(members, *, equity=None, account=None, symbols=None, spread=None, history=None, offset=DARWINEX_OFFSET, margins=None,
        quotes=None, arrived=None, **manifest_changes):
    """build_result over plain data (see reading)."""
    data = manifest([m for m, _ in members], **manifest_changes)
    sets = {m['setSha256']: raw for m, raw in members}
    return bf.build_result(data, sets, schema=SCHEMA, equity=equity,
                           **reading(account=account, symbols=symbols, spread=spread, history=history, offset=offset,
                                     margins=margins, quotes=quotes, arrived=arrived))


def one(result):
    return result['members'][0]


class SymbolMappingTests(unittest.TestCase):
    def test_exact_name_then_one_suffix_or_prefix_variant(self):
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD'), symbol('EURUSD.raw')]), ('EURUSD', None))
        for name in ('EURUSD.raw', 'EURUSDm', 'EURUSD#', 'EURUSD_i', 'EURUSDecn', '#EURUSD', 'm.EURUSD', '.EURUSD'):
            with self.subTest(name=name):
                self.assertEqual(bf.map_symbol('EURUSD', [symbol(name, currency_base='EUR', currency_profit='USD'), symbol('GBPUSD')]),
                                 (name, None))

    def test_more_than_one_variant_is_ambiguous_and_none_is_unavailable(self):
        facts = [symbol('EURUSD.raw', currency_base='EUR', currency_profit='USD'), symbol('EURUSDm', currency_base='EUR', currency_profit='USD')]
        self.assertEqual(bf.map_symbol('EURUSD', facts), (None, (bf.SYMBOL_AMBIGUOUS, ['EURUSD.raw', 'EURUSDm'])))
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('GBPUSD')]), (None, (bf.SYMBOL_UNAVAILABLE, [])))
        result = run([(member(KESTREL), KESTREL)], symbols=facts)
        self.assertEqual((one(result)['status'], one(result)['code']), ('excluded', bf.SYMBOL_AMBIGUOUS))
        self.assertIn('EURUSD.raw, EURUSDm', one(result)['message'])

    def test_only_full_trade_mode_and_the_same_instrument_count(self):
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD', trade_mode=3), symbol('EURUSD.r', currency_base='EUR', currency_profit='USD')]),
                         ('EURUSD.r', None))
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSDm', currency_base='EUR', currency_profit='JPY')])[1][0], bf.SYMBOL_UNAVAILABLE)
        self.assertFalse(bf.is_variant('US30', 'US3000'))
        self.assertFalse(bf.is_variant('EURUSD', 'EURUSDX'))
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD', trade_mode=0)])[1][0], bf.SYMBOL_UNAVAILABLE)

    def test_a_pair_without_reported_currencies_is_refused(self):
        # A six-letter pair must report its base and profit currencies; missing ones cannot prove it is that pair.
        for missing in (dict(currency_base=''), dict(currency_profit=None)):
            with self.subTest(missing=missing):
                self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD', **missing)])[1][0], bf.SYMBOL_UNAVAILABLE)
                self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD.r', **missing)])[1][0], bf.SYMBOL_UNAVAILABLE)

    def test_the_deploy_file_name_carries_the_broker_symbol(self):
        result = run([(member(KESTREL), KESTREL)], symbols=[symbol('EURUSD.raw', currency_base='EUR', currency_profit='USD')])
        self.assertEqual(one(result)['brokerSymbol'], 'EURUSD.raw')
        self.assertEqual(one(result)['deployFileName'], 'GOAT V1.49 EURUSD.raw,M1_EURUSD.M1.kestrel.set')


class SpreadTests(unittest.TestCase):
    def check(self, timeframe, spread, four_digits=False):
        facts = [symbol(digits=4, point=0.0001, trade_tick_size=0.0001, trade_tick_value=10.0)] if four_digits else [symbol()]
        raw = kestrel_with(**NEUTRAL) if four_digits else KESTREL
        return one(run([(member(raw, timeframe=timeframe), raw)], symbols=facts, spread=spread))

    def test_m1_and_m5_allow_125_percent_with_the_boundary_inside(self):
        for timeframe in ('M1', 'M5'):
            with self.subTest(timeframe=timeframe):
                self.assertEqual((self.check(timeframe, 10)['status'], self.check(timeframe, 10)['spreadRatio']), ('fit', 1.25))
                self.assertEqual(self.check(timeframe, 10.1)['code'], bf.SPREAD_TOO_WIDE)

    def test_m15_and_above_allow_150_percent_with_the_boundary_inside(self):
        for timeframe in ('M15', 'H1', 'H4', 'D1'):
            with self.subTest(timeframe=timeframe):
                self.assertEqual(self.check(timeframe, 12)['status'], 'fit')          # 12 / 8 = 1.5
                self.assertEqual(self.check(timeframe, 12.1)['code'], bf.SPREAD_TOO_WIDE)

    def test_the_median_of_six_hours_of_ticks_is_used(self):
        row = one(run([(member(KESTREL), KESTREL)], history={'EURUSD': ticks((8, 8, 8, 8, 40))}))
        self.assertEqual((row['status'], row['spread']['medianPoints'], row['spread']['ticks'], row['spread']['hours']), ('fit', 8.0, 720, 6))
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], history={'EURUSD': ticks((11, 11, 11, 8))}))['code'], bf.SPREAD_TOO_WIDE)
        # Ops' rounding: the median in points to one decimal.
        self.assertEqual(bf.history_spread(ticks((8.02, 8.03, 8.04)), point=Decimal('0.00001'), offset_minutes=180)[0], Decimal('8.0'))
        self.assertEqual(bf.history_spread(ticks((8.12, 8.14)), point=Decimal('0.00001'), offset_minutes=180)[0], Decimal('8.1'))

    def test_a_broker_spread_is_normalised_to_the_reference_point(self):
        row = self.check('M15', 1, four_digits=True)                           # 1 point of 0.0001 = 10 reference points
        self.assertEqual((row['status'], row['spread']['referencePoints']), ('fit', 10.0))
        self.assertEqual(self.check('M15', 2, four_digits=True)['code'], bf.SPREAD_TOO_WIDE)

    def test_too_few_ticks_outside_rollover_and_weekend_is_unavailable(self):
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], history={'EURUSD': ticks(count=99)}))['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], history={'EURUSD': ticks(count=100)}))['status'], 'fit')
        # Every tick inside the rollover hours (16:00-18:00 New York = 20:00-22:00 UTC in October) is skipped.
        rollover = {'EURUSD': ticks(end=utc(2026, 10, 13, 22, 0), count=239, step=30)}
        row = one(run([(member(KESTREL), KESTREL)], history=rollover))
        self.assertEqual(row['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        self.assertIn('only 0 ticks', row['message'])
        self.assertIn('Market Watch', row['message'])
        # A symbol with no history (not in Market Watch) and ticks without a price.
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], history={'EURUSD': None}))['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        no_bid = [dict(t, bid=0.0) for t in ticks()]
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], history={'EURUSD': no_bid}))['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)

    def test_without_a_fresh_last_tick_the_clock_and_spread_are_unknown(self):
        result = run([(member(KESTREL), KESTREL)], quotes={'EURUSD': int(T0 + 180 * 60 - 4200)}, arrived=[])
        self.assertEqual((one(result)['code'], result['serverOffset']['brokerMinutes']), (bf.SPREAD_SAMPLE_UNAVAILABLE, None))

    def test_an_old_tick_never_proves_the_server_clock(self):
        # Review 6130418265 item 8. Probe: a UTC+4 broker whose last tick is 3,600 s old. Its time minus UTC now is
        # exactly 3 hours, so the old rule read UTC+3 = ny-close and let a clock-dependent member through.
        stale_tick = int(T0 + 240 * 60 - 3600)
        self.assertEqual(bf.measured_server_offset_minutes([stale_tick], T0), 180, 'one tick time cannot prove its own age')
        other = dict(ACCOUNT, server='Other-Demo')
        before = run([(member(KESTREL), KESTREL)], account=other, offset=240, quotes={'EURUSD': stale_tick})   # as if it arrived
        self.assertEqual((before['serverOffset']['brokerMinutes'], one(before)['status']), (180, 'fit'), 'the probe, reproduced')
        # Now only a tick seen ARRIVING during the read proves the clock: the old tick leaves it unknown and the
        # clock-dependent member refuses.
        after = run([(member(KESTREL), KESTREL)], account=other, offset=240, quotes={'EURUSD': stale_tick}, arrived=[])
        self.assertEqual((after['serverOffset']['brokerMinutes'], one(after)['code']), (None, bf.SERVER_OFFSET_MISMATCH))
        neutral = kestrel_with(**NEUTRAL)
        self.assertEqual(one(run([(member(neutral), neutral)], account=other, offset=240, quotes={'EURUSD': stale_tick},
                                 arrived=[]))['code'], bf.SERVER_OFFSET_MISMATCH, 'offset-neutral still needs a known offset')

    def test_rollover_and_weekend_boundaries_follow_new_york_time(self):
        # EDT (UTC-4) on 2026-10-13: 15:59 / 16:00 / 17:59 / 18:00 New York.
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 13, 19, 59)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 13, 20, 0)), 'rollover')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 13, 21, 59)), 'rollover')
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 13, 22, 0)))
        # EST (UTC-5) after 2026-11-01: 16:00 New York is 21:00 UTC (23:00 on a NY-close server, Ops' skip).
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 11, 3, 20, 59)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 11, 3, 21, 0)), 'rollover')
        # Friday 2026-10-16 15:59 / 16:00 New York; Sunday 2026-10-18 17:59 / 18:00 New York.
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 16, 19, 59)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 16, 20, 0)), 'weekend')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 17, 12, 0)), 'weekend')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 18, 21, 59)), 'weekend')
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 18, 22, 0)))


class ScalingTests(unittest.TestCase):
    def test_scale_1_on_a_reference_identical_account_is_byte_identical(self):
        # Without reference.startLot the member's loss is not modelled: on the reference-identical account the
        # exemption deploys the reference bytes at scale 1.0, byte for byte.
        result = run([(member(KESTREL, ref=NO_START), KESTREL)])
        row = one(result)
        self.assertEqual((result['scale'], row['status'], row['edits'], row['marginReason']), (1.0, 'fit', {}, bf.REFERENCE_IDENTICAL_MARGIN))
        self.assertEqual(row['setSha256Deployed'], row['setSha256Reference'])
        self.assertEqual(row['setSha256Reference'], hashlib.sha256(KESTREL).hexdigest())
        self.assertEqual(bf.rewrite_set(KESTREL, row['edits']), KESTREL)
        json.dumps(result, allow_nan=False)
        # Round 6 (goatai#2350 6134542541): with reference.startLot too, exactly scale 1.0 on a reference-identical
        # account deploys the reference bytes; the EA solves its start lot itself at live ATR (no F1 band).
        row = one(run([(member(KESTREL), KESTREL)]))
        self.assertEqual((row['edits'], row['setSha256Deployed'], row['startLotSource']), ({}, row['setSha256Reference'], TRACE))
        self.assertEqual((row['scaled']['Risk'], row['scaled']['lossBand'], row['scaled']['startLot'], row['scaled']['plannedLoss']),
                         (500.0, None, 0.1, 500.0))
        # One hair off 1.0 (planning equity 99,999.99) the band applies: Risk 452.20 over [0.57, 1.68].
        row = one(run([(member(KESTREL), KESTREL)], equity=99999.99))
        self.assertEqual((row['edits'], row['scaled']['quantizationMargin'], row['scaled']['plannedLossMax']), (dict(Risk='452.2'), 47.79, 499.99))
        self.assertEqual(row['scaled']['lossBand'], dict(low=0.57, high=1.68, kind='atr', valueRatio=1.0, anchorError=0.05))

    def test_risk_scales_and_the_lot_multipliers_do_not(self):
        # Lots_Max and Lots_Max_Cum multiply the start lot (EA mq5:1372, 1366), which already follows Risk: scaling them
        # too would scale the caps twice. Risk 500.0 at half the equity is 250.0 (then lowered by the F1 band to 209.56);
        # the multipliers stay 20.0 and 50.0.
        row = one(run([(member(KESTREL), KESTREL)], equity=50000))
        self.assertEqual(row['edits'], dict(Risk='209.56'))
        self.assertEqual((row['scaled']['riskSearched'], row['scaled']['Risk'], row['scaled']['Lots_Max'], row['scaled']['Lots_Max_Cum'],
                          row['scaled']['startLot']), (250.0, 209.56, 20.0, 50.0, 0.04))
        deployed = bf.rewrite_set(KESTREL, row['edits'])
        self.assertEqual(hashlib.sha256(deployed).hexdigest(), row['setSha256Deployed'])
        values = bf.set_values(deployed, SCHEMA)
        self.assertEqual((values['Risk'], values['Lots_Max'], values['Lots_Max_Cum'], values['Lots_Input']), ('209.56', '20.0', '50.0', '0.05'))

    def test_fixed_lots_round_down_to_the_volume_step(self):
        raw = kestrel_with(**FIXED)
        row = one(run([(member(raw), raw)], equity=75000))                    # 0.05 x 0.75 = 0.0375 -> 0.03
        self.assertEqual(row['edits'], dict(Risk='375.0', Lots_Input='0.03'))
        row = one(run([(member(raw), raw)], equity=99999))                    # 0.049999 -> 0.04, never 0.05
        self.assertEqual((row['edits']['Lots_Input'], row['edits']['Risk']), ('0.04', '499.99'))
        self.assertEqual(one(run([(member(raw), raw)], equity=250000))['edits']['Lots_Input'], '0.12')

    def test_below_min_lot_never_rounds_up(self):
        raw = kestrel_with(**FIXED)
        row = one(run([(member(raw), raw)], equity=19999.99))                 # 0.0099999 -> 0.00
        self.assertEqual((row['code'], row['message']), (bf.BELOW_MIN_LOT, 'This set needs a larger account.'))
        row = one(run([(member(raw), raw)], equity=20000))
        self.assertEqual((row['status'], row['edits']['Lots_Input']), ('fit', '0.01'))

    def test_a_reference_start_lot_proves_risk_per_sequence_below_the_reference_equity(self):
        # reference.startLot 0.1 follows the scaled Risk on the ported loss. Round 5 F1 (b): VOLUME_MIN 0.01 plans 40.594
        # at the model and up to 1.68 x 40.594 = 68.20 at the top of the ATR band, so below Risk 68.20 (13,640) the EA
        # could be forced over Risk: BELOW_MIN_LOT (8,120 before F1).
        scaled = one(run([(member(KESTREL), KESTREL)], equity=99000))['scaled']
        self.assertEqual((scaled['riskSearched'], scaled['Risk'], scaled['startLot']), (495.0, 447.68, 0.09))
        self.assertLessEqual(scaled['plannedLossMax'], 495.0)
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=13640))['scaled']['startLot'], 0.01)
        for equity in (13639.99, 10000, 8120):
            self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=equity))['code'], bf.BELOW_MIN_LOT)
        # Risk under the EA's 10 is refused even with a large start lot (EA mq5:3253).
        self.assertEqual(one(run([(member(KESTREL, ref=reference(startLot=10)), KESTREL)], equity=1999))['code'], bf.BELOW_MIN_LOT)
        # A reference start lot of 3 at Risk 500, equity 33,333.33 (Risk 166.66): deployed 165.09, worst plan 166.65.
        scaled = one(run([(member(KESTREL, ref=reference(startLot=3)), KESTREL)], equity=33333.33, margins={'EURUSD': 100.0}))['scaled']
        self.assertEqual((scaled['riskSearched'], scaled['Risk'], scaled['startLot'], scaled['plannedLossMax']), (166.66, 165.09, 0.99, 166.65))

    def test_the_risk_per_sequence_start_lot_is_the_eas_nearest_pick(self):
        # Review 6130418265 item 6. Probe: startLot 0.10 at Risk 500, scale 0.355 (equity 35,500) -> Risk 177.50.
        # Ideal start lot 0.0355: the old floor model said 0.03; the EA's solver picks 0.04 (|200-177.5| < |150-177.5|),
        # so the peak margin was understated by a third: 0.03 x 50 = 1.5 lots before, 0.04 x 50 = 2.0 lots now.
        self.assertEqual(bf.ea_solve_start_lots(177.5, 0.01, 0.01, 50.0, lambda lots: lots * 5000.0), 0.04)
        # Round 3 B: on the EA's ported loss the pick at 177.50 is still 0.04, but it plans 201.14 > 177.50. Round 5 F1
        # deploys 122.84: anywhere in the ATR band the EA plans at most 177.49. At the model it picks 0.03 (136.07); at the
        # band's low end 0.04, whose ladder (0.43 lots) sizes the margin.
        row = one(run([(member(KESTREL), KESTREL)], equity=35500))
        self.assertEqual((row['status'], row['edits'], row['scaled']['riskSearched'], row['scaled']['Risk'], row['scaled']['startLot'],
                          row['scaled']['startLotMax']), ('fit', dict(Risk='122.84'), 177.5, 122.84, 0.03, 0.04))
        self.assertEqual((row['scaled']['plannedLoss'], row['scaled']['plannedLossMax'], row['margin']['peakLots'], row['margin']['required']),
                         (136.07, 177.49, 0.43, 430.0))

    def test_the_lot_solver_matches_the_ea_traced_by_hand(self):
        # SolveStartLotsByRisk (mq5:781-827) and NormalizedLots (mq5:445-459) in IEEE doubles, as MQL5 runs them, on a
        # broker with VOLUME_MIN 0.1, VOLUME_STEP 0.1, VOLUME_MAX 1.0 and a planned loss of 1,000 per lot.
        # kmax = floor((1.0-0.1)/0.1 + 1e-9) = floor(9.000000000000002 + 1e-9) = 9 (grid 0.1 .. 1.0).
        loss = lambda lots: lots * 1000.0
        solve = lambda target: bf.ea_solve_start_lots(target, 0.1, 0.1, 1.0, loss)
        # 355: round 1 kmid 4 tries k 3,4,5 = 0.4,0.5,0.6 (err 45,145,245), best k3; loss(0.5)=500 > 355 -> kmax 3.
        #      round 2 kmid 1 tries 0.1,0.2,0.3 (err 255,155,55): no improvement; 200 <= 355 -> kmin 2.
        #      round 3 kmid 2 tries 0.3,0.3,0.4: none better; 300 <= 355 -> kmin 3 = kmax: stop. k3 -> 0.4 (the floor model: 0.3).
        self.assertEqual(solve(355), 0.4)
        # 340: round 2 finds k2 = 0.1 + 2 x 0.1 = 0.30000000000000004 (err 40 < 60): 0.3, the nearer step.
        self.assertAlmostEqual(solve(340), 0.3, places=12)
        # 350, a tie on paper: round 1 keeps k3 (0.4, err 50.0); round 2's k2 is 0.30000000000000004, its loss
        # 300.00000000000006 and err 49.99999999999994 < 50.0, so the EA's doubles pick 0.3.
        self.assertAlmostEqual(solve(350), 0.3, places=12)
        # 5 (ideal 0.005) is forced up to VOLUME_MIN 0.1; 2000 is capped at the grid's last step 1.0.
        self.assertEqual((solve(5), solve(2000)), (0.1, 1.0))
        # Early returns: no step or no maximum -> VOLUME_MIN (mq5:788); no target -> VOLUME_MIN (mq5:789).
        self.assertEqual((bf.ea_solve_start_lots(355, 0.1, 0, 1.0, loss), bf.ea_solve_start_lots(0, 0.1, 0.1, 1.0, loss)), (0.1, 0.1))
        # NormalizedLots rounds half away from zero, 0 below VOLUME_MIN, capped at VOLUME_MAX.
        self.assertAlmostEqual(bf.ea_normalized_lots(0.25, 0.1, 0.1, 100), 0.3, places=12)
        self.assertEqual((bf.ea_normalized_lots(0.04, 0.1, 0.1, 100), bf.ea_normalized_lots(7.0, 0.1, 0.1, 5.0)), (0.0, 5.0))
        # The review's own probe on a 0.01 grid: 177.5 at 5,000 per lot -> 0.04.
        self.assertEqual(bf.ea_solve_start_lots(177.5, 0.01, 0.01, 50.0, lambda lots: lots * 5000.0), 0.04)

    def test_the_lot_ladder_matches_the_ea_traced_by_hand(self):
        # Review 6132018108 item B: BuildRawLots + ScaleRawLots + per-level NormalizedLots + BuildCumulativeLots
        # (mq5:840-1036). Kestrel: CumPartial, Lots_Exponent 1.4, Lots_Factor 1.3, 6 levels, Lots_Max_Cum 50.
        # Leff = w1 x 1.4 + w2 x 1.82 with w2 = lvl/6: 1.47, 1.54, 1.61, 1.68, 1.75; each level adds cum x (Leff - 1):
        # 0.1, 0.047, 0.07938, 0.1380918, 0.247840824, 0.459234468 (peak 1.07 < 0.1 x 50: no ScaleRawLots factor).
        inputs = bf.ladder_inputs(bf.set_values(KESTREL, SCHEMA), bf.schema_defaults(SCHEMA))
        self.assertEqual(inputs, dict(mode=5, exponent=1.4, factor=1.3, trades=6, cap=50.0, peak_pos=35.0, lots_max=20.0))
        for got, want in zip(bf.ea_raw_ladder(0.1, inputs), (0.1, 0.047, 0.07938, 0.1380918, 0.247840824, 0.459234468)):
            self.assertAlmostEqual(got, want, places=12)
        # Normalized on a 0.01 step: 0.10, 0.05, 0.08, 0.14, 0.25, 0.46 -> standing 0.10 .. 1.08.
        for got, want in zip(bf.ea_standing(0.1, inputs, 0.01, 0.01, 50.0), (0.1, 0.15, 0.23, 0.37, 0.62, 1.08)):
            self.assertAlmostEqual(got, want, places=12)
        # At start 0.01 level 1 (0.0047) normalizes to 0 and level 2 (0.007938) to 0.01 (+26% over its raw lot).
        for got, want in zip(bf.ea_standing(0.01, inputs, 0.01, 0.01, 50.0), (0.01, 0.01, 0.02, 0.03, 0.05, 0.1)):
            self.assertAlmostEqual(got, want, places=12)
        # Last, Lots_Exponent 2, Lots_Factor 1, 4 levels: 1, 0.75x2+0.25x2 = 2, 0.5x4+0.5x4 = 4, 0.25x8+0.75x8 = 8;
        # peak 15 > 1 x Lots_Max_Cum 3, so ScaleRawLots multiplies levels 1.. by 3/15: 1, 0.4, 0.8, 1.6.
        last = dict(mode=1, exponent=2.0, factor=1.0, trades=4, cap=3.0, peak_pos=50.0, lots_max=0.0)
        for got, want in zip(bf.ea_raw_ladder(1.0, last), (1.0, 0.4, 0.8, 1.6)):
            self.assertAlmostEqual(got, want, places=12)
        # Peak, 3 levels, exponent 1 (s_up 1), cap 2, Peak_Lots_Pos_PC 50: pivot = round(1.5) = 2. Level 1: t 0.5, tp 1,
        # Hermite h 0.5: 0.5 x 1 + 0.125 x (1 x 1) + 0.5 x 2 = 1.625 -> lot 0.625. Level 2 is the pivot AND the last
        # level, so its target is 0: lot -1.625. Running peak 1.625 <= 1 x 2: no ScaleRawLots factor.
        peak = dict(mode=4, exponent=1.0, factor=1.0, trades=3, cap=2.0, peak_pos=50.0, lots_max=0.0)
        for got, want in zip(bf.ea_raw_ladder(1.0, peak), (1.0, 0.625, -1.625)):
            self.assertAlmostEqual(got, want, places=12)
        # CumPartial compounds the ACTUAL standing at run time (mq5:1539-1563): from 0.02 it adds 0.0094 -> 0.01,
        # 0.0162 -> 0.02, 0.0305 -> 0.03, 0.0544 -> 0.05, 0.0975 -> 0.10: peak 0.23 (the plan peaks at 0.22).
        self.assertAlmostEqual(max(bf.ea_standing(0.02, inputs, 0.01, 0.01, 50.0)), 0.22, places=12)
        self.assertAlmostEqual(bf.ea_peak_standing(0.02, inputs, 0.01, 0.01, 50.0), 0.23, places=12)

    def test_the_eas_planned_loss_is_ported(self):
        # Review 6132018108 item B. BuildDistances (mq5:1603-1614) with GetSize(GRID_VALID) (mq5:6754-6767): Kestrel's
        # Grid_Size -3, Grid_Min -1.5 and Grid_Max -15 are all ATR, so the ATR cancels in loss(L) / loss(startLot).
        # Grid_Exponent 1.3, Grid_Factor 1.1: f = w1/1.3 + w2/1.43, size = 3 x (1/f)^(lvl-1), clamped to [1.5, 15].
        values, defaults = bf.set_values(KESTREL, SCHEMA), bf.schema_defaults(SCHEMA)
        shape = bf.grid_shape(values, defaults)
        want = [3.0 * (1.0 / ((1 - lvl / 6) / 1.3 + (lvl / 6) / 1.43)) ** (lvl - 1) for lvl in range(1, 6)]
        for got, expected, rounded in zip(shape, want, (3.0, 4.021875, 5.56435, 7.95075, 11.74224)):
            self.assertAlmostEqual(got, expected, places=12)
            self.assertAlmostEqual(got, rounded, places=4)
        # FindCumLoss at the reference start lot 0.1: 3 x 0.10 + 4.021875 x 0.15 + 5.56435 x 0.23 + 7.95075 x 0.37
        # + 11.74224 x 0.62 = 12.40505 grid units: the reference Risk 500.
        inputs = bf.ladder_inputs(values, defaults)
        self.assertAlmostEqual(bf.ea_loss_shape(0.1, inputs, shape, 0.01, 0.01, 50.0), 12.405050485, places=8)
        loss = bf.sequence_loss(values, defaults, dict(startLot=Decimal('0.1'), volumeMin=Decimal('0.01'), volumeStep=Decimal('0.01'),
                                                       volumeMax=Decimal('50')), risk=Decimal('500'), conversion=1)
        self.assertAlmostEqual(loss(0.1, 0.01, 0.01, 50.0), 500.0, places=9)
        # Probe: equity 14,642 -> Risk 73.21. Start 0.01 stands 0.01, 0.01, 0.02, 0.03, 0.05: 40.594; start 0.02 stands
        # 0.02, 0.03, 0.05, 0.08, 0.13: 105.660. |105.66 - 73.21| = 32.45 < |40.59 - 73.21| = 32.62, so the EA picks
        # 0.02 where the linear model (500 per 0.1 lot) picked 0.01: its margin doubles and it plans to lose 105.66
        # against the Risk 73.21 (+44%, the EA's own nearest rounding).
        self.assertAlmostEqual(loss(0.01, 0.01, 0.01, 50.0), 40.5940, places=3)
        self.assertAlmostEqual(loss(0.02, 0.01, 0.01, 50.0), 105.6596, places=3)
        self.assertEqual(bf.ea_solve_start_lots(73.21, 0.01, 0.01, 50.0, lambda lots: lots * 5000.0), 0.01, 'the linear model')
        self.assertEqual(bf.ea_solve_start_lots(73.21, 0.01, 0.01, 50.0, lambda lots: loss(lots, 0.01, 0.01, 50.0)), 0.02, 'the EA')
        # Round 4 R2 searched down to 73.12, the largest whose pick (0.01) plans <= 73.21 at the model: at 73.13 the EA
        # would pick 0.02. Round 5 F1 keeps the half loss jump inside the band: Risk 50.66 (see test_the_quantization_
        # margin_holds_across_the_loss_band).
        self.assertEqual(bf.ea_solve_start_lots(73.13, 0.01, 0.01, 50.0, lambda lots: loss(lots, 0.01, 0.01, 50.0)), 0.02)
        row = one(run([(member(KESTREL), KESTREL)], equity=14642))
        self.assertEqual((row['status'], row['edits'], row['scaled']['riskSearched'], row['scaled']['Risk'], row['scaled']['startLot'],
                          row['scaled']['plannedLoss']), ('fit', dict(Risk='50.66'), 73.21, 50.66, 0.01, 40.59))
        self.assertEqual((row['scaled']['startLotMax'], row['margin']['peakLots'], row['margin']['required']), (0.02, 0.23, 230.0))
        # Mixed grid kinds (Grid_Size in points, Grid_Min / Grid_Max in ATR) leave the loss unknown: fail closed.
        mixed = kestrel_with(Grid_Size='10.0', EA_Desc='M')
        self.assertIsNone(bf.grid_shape(bf.set_values(mixed, SCHEMA), defaults))
        row = one(run([(member(mixed), mixed)], equity=50000))
        self.assertEqual((row['code'], row['margin']['basis']), (bf.MARGIN_UNKNOWN, 'loss_unknown'))

    def test_an_equity_sweep_picks_what_the_ported_solver_picks(self):
        # Review 6132018108 item B: from 10,000 to 100,000 the EA's pick on the ported loss differs from the old linear
        # pick at about 10% of equities (the evidence for B; the deployed Risk is round 5 F1's, tested below).
        values, defaults = bf.set_values(KESTREL, SCHEMA), bf.schema_defaults(SCHEMA)
        loss = bf.sequence_loss(values, defaults, dict(startLot=Decimal('0.1'), volumeMin=Decimal('0.01'), volumeStep=Decimal('0.01'),
                                                       volumeMax=Decimal('50')), risk=Decimal('500'), conversion=1)
        planned = lambda lots: loss(lots, 0.01, 0.01, 50.0)
        total = moved = 0
        worst_before = 0.0
        for equity in range(10000, 100001, 97):
            risk = (Decimal(500) * Decimal(equity) / Decimal(100000)).quantize(Decimal('0.01'), rounding='ROUND_FLOOR')
            ported = bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, planned)
            total += 1
            moved += abs(ported - bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, lambda lots: lots * 5000.0)) > 1e-9
            worst_before = max(worst_before, planned(ported) / float(risk))
        self.assertEqual((total, moved), (928, 92))                              # 9.9%
        self.assertGreater(worst_before, 1.44)                                   # +44.5% at the model, before R2 / F1

    def test_the_quantization_margin_holds_across_the_loss_band(self):
        # Round 5 F1 (goatai#2350 6133583699). Probe: round 4 put Risk' 73.12 at 14,642 exactly halfway between the
        # picks 0.01 (40.59) and 0.02 (105.66): a loss per lot 0.05% lower made the EA pick 0.02 and plan +44%.
        values, defaults = bf.set_values(KESTREL, SCHEMA), bf.schema_defaults(SCHEMA)
        loss = bf.sequence_loss(values, defaults, dict(startLot=Decimal('0.1'), volumeMin=Decimal('0.01'), volumeStep=Decimal('0.01'),
                                                       volumeMax=Decimal('50')), risk=Decimal('500'), conversion=1)
        planned = lambda lots: loss(lots, 0.01, 0.01, 50.0)
        at = lambda risk, m: m * planned(bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, lambda lots: m * planned(lots)))
        self.assertAlmostEqual(at(73.12, 0.9995), 0.9995 * 105.6596, places=2, msg='round 4: 105.61 against 73.21')
        row = one(run([(member(KESTREL), KESTREL)], equity=14642))
        risk = row['scaled']['Risk']
        self.assertEqual((risk, row['scaled']['quantizationMargin']), (50.66, 22.55))
        for m in (0.9995, 0.95, 1.0, 0.57, 1.68):
            with self.subTest(m=m):
                self.assertLessEqual(at(risk, m), 73.21)
        # The 8,370 high-ATR probe: at 1.6x the minimum lot plans 1.6 x 40.59 = 64.95 against Risk 41.85: refused.
        self.assertAlmostEqual(1.6 * planned(0.01), 64.95, places=2)
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=8370))['code'], bf.BELOW_MIN_LOT)
        # A point grid gets the narrow band; a broker whose value per point is 1.1x the reference's widens it 1.1x.
        points = kestrel_with(Grid_Size='10.0', Grid_Min='5.0', Grid_Max='100.0', EA_Desc='P')
        band = one(run([(member(points), points)], equity=50000))['scaled']['lossBand']
        self.assertEqual((band['kind'], band['low'], band['high']), ('points', round(0.95 * 0.95, 6), round(1.05 * 1.05, 6)))
        richer = one(run([(member(KESTREL), KESTREL)], equity=50000, symbols=[symbol(trade_tick_value=1.1)]))['scaled']['lossBand']
        self.assertEqual((richer['valueRatio'], richer['high']), (1.1, round(1.6 * 1.1 * 1.05, 6)))

    def test_a_sweep_across_the_band_never_exceeds_the_scaled_risk(self):
        # Round 5 F1: from 8,000 to 100,000, at every multiplier of the band (61 steps plus every pick boundary), the
        # EA's actual pick at the deployed Risk plans at most the equity-linear Risk; or the member is BELOW_MIN_LOT.
        values, defaults = bf.set_values(KESTREL, SCHEMA), bf.schema_defaults(SCHEMA)
        loss = bf.sequence_loss(values, defaults, dict(startLot=Decimal('0.1'), volumeMin=Decimal('0.01'), volumeStep=Decimal('0.01'),
                                                       volumeMax=Decimal('50')), risk=Decimal('500'), conversion=1)
        planned = lambda lots: loss(lots, 0.01, 0.01, 50.0)
        rules = dict(volume_min=Decimal('0.01'), volume_step=Decimal('0.01'), volume_max=Decimal('50'), contract_ratio=Decimal(1),
                     reference_volume_min=Decimal('0.01'), reference_volume_step=Decimal('0.01'), reference_volume_max=Decimal('50'),
                     start_lot=Decimal('0.1'), memo={})
        fit = refused = 0
        for equity in range(8000, 100001, 997):
            outcome = bf.rules_at(values, defaults, rules, equity=Decimal(equity), reference_equity=Decimal(100000), rate=Decimal(1))
            if outcome['code'] is not None:
                self.assertEqual(outcome['code'], bf.BELOW_MIN_LOT)
                refused += 1
                continue
            fit += 1
            scaled, risk = outcome['scaled'], float(outcome['scaled']['Risk'])
            low, high = scaled['lossBand']['low'], scaled['lossBand']['high']
            multipliers = [low + (high - low) * i / 60 for i in range(61)]
            lots = [0.01 * k for k in range(1, 400)]
            for a, b in zip(lots, lots[1:]):
                boundary = 2 * risk / (planned(a) + planned(b))
                if low <= boundary <= high:
                    multipliers += [boundary * (1 - 1e-9), boundary * (1 + 1e-9)]
            for m in multipliers:
                pick = bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, lambda size: m * planned(size))
                self.assertLessEqual(m * planned(pick), float(scaled['riskSearched']) * (1 + 1e-9), msg='%s at m=%s' % (equity, m))
        self.assertEqual((fit + refused, refused), (93, 6))

    def test_the_reviewers_worst_case_ladders(self):
        # goatai#2350 6132804177 R3. The reviewer's model: gap = Grid_Exponent^(i-1), Grid_Min / Grid_Max ignored,
        # reference start lot 0.10 at Risk 500. Here Grid_Size -1 (ATR), Grid_Min 0 (clamped to -0.5 ATR: never
        # binds, every gap >= 1), Grid_Max 0 (disabled) and Grid_Factor 1, so GetSize(GRID_VALID) is exactly
        # Grid_Exponent^(lvl-1) and the port must give the reviewer's numbers. "/ 1.0" in the review is Grid_Exponent.
        cases = (  # name, Mode_Lots_Prog, Lots_Exponent, Lots_Factor, Max_Seq_Trades, Grid_Exponent, equity, Risk, linear, EA pick, its loss
            ('CumPartial', '5', '1.25', '1.0', '8', '1.3', 14936, 74.68, 0.01, 0.02, 116.60),
            ('Last', '1', '1.2', '1.0', '10', '1.0', 14390, 71.95, 0.01, 0.02, 96.73),
            ('Cum', '2', '1.3', '1.0', '10', '1.0', 15328, 76.64, 0.02, 0.02, 105.26),
            # The review wrote Risk 125.01 for scale 0.25; 500 x 0.25 is 125.00 (same pick and loss).
            ('Start', '0', '1.6', '1.0', '10', '1.0', 25000, 125.00, 0.03, 0.03, 155.41),
        )
        defaults = bf.schema_defaults(SCHEMA)
        for name, mode, exponent, factor, trades, grid_exponent, equity, risk, linear, pick, planned in cases:
            with self.subTest(ladder=name):
                raw = kestrel_with(Mode_Lots_Prog=mode, Lots_Exponent=exponent, Lots_Factor=factor, Max_Seq_Trades=trades,
                                   Grid_Size='-1.0', Grid_Min='0.0', Grid_Max='0.0', Grid_Exponent=grid_exponent, Grid_Factor='1.0',
                                   EA_Desc=name)
                values = bf.set_values(raw, SCHEMA)
                gaps = bf.grid_shape(values, defaults)
                for lvl, gap in enumerate(gaps, start=1):
                    self.assertAlmostEqual(gap, float(grid_exponent) ** (lvl - 1), places=9)
                loss = bf.sequence_loss(values, defaults, dict(startLot=Decimal('0.1'), volumeMin=Decimal('0.01'), volumeStep=Decimal('0.01'),
                                                               volumeMax=Decimal('50')), risk=Decimal('500'), conversion=1)
                ported = bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, lambda lots: loss(lots, 0.01, 0.01, 50.0))
                self.assertEqual(bf.ea_solve_start_lots(risk, 0.01, 0.01, 50.0, lambda lots: lots * 5000.0), linear)
                self.assertEqual((ported, round(loss(ported, 0.01, 0.01, 50.0), 2)), (pick, planned), 'before round 4 R2')
                self.assertGreater(planned, risk)
                # After R2 the deployed plan is within the equity-linear Risk, or the member is excluded.
                row = one(run([(member(raw), raw)], equity=equity))
                if row['status'] == 'fit':
                    self.assertEqual(row['scaled']['riskSearched'], risk)
                    self.assertLessEqual(row['scaled']['plannedLoss'], risk)
                    self.assertLess(row['scaled']['Risk'], risk)
                else:
                    self.assertEqual(row['code'], bf.BELOW_MIN_LOT)

    def test_fixed_lots_margin_follows_the_eas_ladder(self):
        # Review 6132018108 item B2. FixedLots floors the START lot, but every later level still rounds to the nearest
        # step. CumPartial, Lots_Exponent 1.6, Lots_Factor 1.3 at scale 0.10: the reference Lots_Input 0.10 peaks at
        # 2.12 lots, the account's 0.01 at 0.26, not 0.212 (+22.6%). The margin uses the ported ladder's 0.26.
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.10', Lots_Exponent='1.6', Mode_Lots_Prog='5'))
        inputs = bf.ladder_inputs(bf.set_values(raw, SCHEMA), bf.schema_defaults(SCHEMA))
        self.assertAlmostEqual(bf.ea_peak_standing(0.10, inputs, 0.01, 0.01, 50.0), 2.12, places=12)
        self.assertAlmostEqual(bf.ea_peak_standing(0.01, inputs, 0.01, 0.01, 50.0), 0.26, places=12)
        row = one(run([(member(raw), raw)], equity=10000))
        self.assertEqual((row['status'], row['edits']['Lots_Input'], row['margin']['peakLots']), ('fit', '0.01', 0.26))

    def test_lots_input_is_snapped_to_the_broker_step_at_factor_one(self):
        # Review 6130418265 item 1. Probe: VOLUME_STEP 0.1, VOLUME_MIN 0.1, reference Lots_Input 0.25 at scale 1.0. The
        # old rule wrote nothing, and the EA's NormalizedLots would open 0.25 -> 0.30 (+20%). Now it is floored to 0.2.
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.25'))
        self.assertAlmostEqual(bf.ea_normalized_lots(0.25, 0.1, 0.1, 50.0), 0.3, places=12, msg='what the EA would have opened')
        row = one(run([(member(raw), raw)], symbols=[symbol(volume_min=0.1, volume_step=0.1)]))
        self.assertEqual((row['status'], row['edits'], row['scaled']['Lots_Input']), ('fit', dict(Lots_Input='0.2'), 0.2))
        # Also capped at VOLUME_MAX at factor 1.
        capped = one(run([(member(raw), raw)], symbols=[symbol(volume_max=0.1, volume_min=0.01, volume_step=0.01)]))
        self.assertEqual(capped['edits'], dict(Lots_Input='0.1'))

    def test_an_unreadable_money_value_excludes_the_member(self):
        # Review 6130418265 item 5. Probe: MinLevelEquity=9.5e4 (95,000 to MT5) failed the plain-number rule, read as 0
        # ("no limit") and fitted at 50k. Now any unreadable money value excludes the member.
        raw = kestrel_with(MinLevelEquity='9.5e4')
        row = one(run([(member(raw), raw)], equity=50000))
        self.assertEqual((row['code'], row['message']), (bf.MONEY_VALUE_UNREADABLE, "GOAT cannot read this set's MinLevelEquity value, so it cannot check its money limits."))
        for name, text in (('MaxLossLocal', '1,000'), ('MaxDailyLossLocal', ''), ('Risk', '5e2')):
            with self.subTest(name=name):
                raw = kestrel_with(**{name: text})
                self.assertEqual(one(run([(member(raw), raw)]))['code'], bf.MONEY_VALUE_UNREADABLE)
        # An unreadable indicator timeframe may be H4: never offset-neutral.
        raw = kestrel_with(**dict(NEUTRAL, RSI_TF_='H4'))
        self.assertIn('RSI_TF_ unreadable', bf.offset_neutral(bf.set_values(raw, SCHEMA), bf.schema_defaults(SCHEMA), 'M1')[1])

    def test_a_grid_size_the_ea_refuses_is_excluded(self):
        # mq5:3317: Grid_Size inside (-0.5, 0.5) stops the EA. Point ratio 0.1 turns Grid_Size 4.0 into 0.4.
        raw = kestrel_with(**dict(NEUTRAL, Grid_Size='4.0'))
        row = one(run([(member(raw, timeframe='M15'), raw)], symbols=[symbol(**FOUR_DIGIT)], spread=1))
        self.assertEqual((row['code'], row['message']),
                         (bf.EA_INIT_REFUSED, "On this broker this set's Grid_Size would be 0.4, which the GOAT EA refuses to start with."))
        fine = kestrel_with(**dict(NEUTRAL, Grid_Size='5.0', Grid_Min='5.0', Grid_Max='100.0'))
        self.assertEqual(one(run([(member(fine, timeframe='M15'), fine)], symbols=[symbol(**FOUR_DIGIT)], spread=1))['status'], 'fit')

    def test_without_a_reference_start_lot_risk_per_sequence_is_margin_unknown(self):
        # Ruling (goatai#2350 6129252646): unknown margin fails closed at any equity other than the reference-identical
        # exemption (ReferenceIdenticalTests): any scale but 1.0 refuses.
        for equity in (99000, 200000):
            with self.subTest(equity=equity):
                row = one(run([(member(KESTREL, ref=reference(startLot=None, startLotSource=None)), KESTREL)], equity=equity))
                self.assertEqual((row['code'], row['margin']['basis']), (bf.MARGIN_UNKNOWN, 'start_lot_unknown'))

    def test_a_lot_cap_below_volume_min_is_below_min_lot(self):
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.02', Lots_Max='0.4'))   # cap = 0.4 x 0.02 = 0.008 < 0.01
        self.assertEqual(one(run([(member(raw), raw)]))['code'], bf.BELOW_MIN_LOT)

    def test_fixed_money_limits_are_not_scaled(self):
        raw = kestrel_with(MaxLossLocal='1000.0')
        self.assertEqual(one(run([(member(raw), raw)]))['status'], 'fit')     # scale 1: nothing to scale
        row = one(run([(member(raw), raw)], equity=200000))
        self.assertEqual((row['code'], row['message']), (bf.CONTRACT_MISMATCH, 'This set uses a fixed money limit (MaxLossLocal) that GOAT does not scale.'))


class MinEquityTests(unittest.TestCase):
    def test_min_equity_is_the_smallest_cent_where_90_percent_trades(self):
        raw = kestrel_with(**FIXED)
        result = run([(member(raw), raw)])
        self.assertEqual((result['minEquity'], result['offered'], result['refusal']), (20000.0, True, None))
        result = run([(member(raw), raw)], equity=19999.99)
        self.assertEqual((result['offered'], result['refusal']['code'], result['tradableRiskShare']),
                         (False, bf.PORTFOLIO_NEEDS_LARGER_ACCOUNT, 0.0))

    def test_the_manifest_floor_wins_when_stricter(self):
        raw = kestrel_with(**FIXED)
        result = run([(member(raw), raw)], minEquity=30000)
        self.assertEqual((result['minEquity'], result['manifestMinEquity']), (30000.0, 30000.0))
        self.assertEqual(run([(member(raw), raw)], minEquity=30000, equity=25000)['refusal']['code'], bf.PORTFOLIO_NEEDS_LARGER_ACCOUNT)

    def test_risk_per_sequence_with_a_start_lot_is_offered_below_the_reference(self):
        # VOLUME_MIN plans 40.594 at the model and 1.68 x that at the top of the ATR band (round 5 F1 (b)), so the
        # minimum is Risk 68.20 = 13,640 (8,120 in round 3).
        result = run([(member(KESTREL), KESTREL)], equity=13640)
        self.assertEqual((result['minEquity'], result['offered']), (13640.0, True))
        self.assertEqual(run([(member(KESTREL), KESTREL)], equity=13639.99)['refusal']['code'], bf.PORTFOLIO_NEEDS_LARGER_ACCOUNT)
        without = run([(member(KESTREL, ref=reference(startLot=None)), KESTREL)], equity=99000)
        self.assertEqual((without['offered'], without['refusal']['code'], without['minEquity']), (False, bf.PORTFOLIO_BROKER_UNFIT, None))
        # On the reference-identical account the exemption offers it at the reference equity only.
        at_reference = run([(member(KESTREL, ref=reference(startLot=None)), KESTREL)])
        self.assertEqual((at_reference['offered'], at_reference['minEquity']), (True, 100000.0))

    def test_ninety_percent_of_risk_weight(self):
        rows = []
        for index in range(10):
            raw = kestrel_with(EA_Desc='R%02d' % index)
            rows.append((member(raw, member_id='m%d' % index, canonical='GBPUSD' if index == 9 else 'EURUSD'), raw))
        result = run(rows, margins={'EURUSD': 800.0})                          # 9 x 6.05 lots x 800 = 43,560 margin
        self.assertEqual((result['riskWeighting'], result['tradableRiskShare'], result['offered']), ('risk', 0.9, True))
        rows[8] = (member(rows[8][1], member_id='m8', canonical='GBPUSD'), rows[8][1])
        result = run(rows, margins={'EURUSD': 800.0})
        self.assertEqual((result['tradableRiskShare'], result['offered'], result['refusal']['code'], result['minEquity']),
                         (0.8, False, bf.PORTFOLIO_BROKER_UNFIT, None))


class CurrencyTests(unittest.TestCase):
    def test_an_eur_account_converts_equity_through_eurusd(self):
        raw = kestrel_with(**FIXED)
        account = dict(ACCOUNT, currency='EUR', equity=200000.0)
        result = run([(member(raw), raw)], account=account, symbols=[symbol(), symbol('EURUSD.x', bid=1.2, ask=1.2002, trade_mode=0)])
        self.assertEqual((result['scale'], result['conversion']), (2.2, dict(rate=1.1, symbol='EURUSD', side='bid')))
        # Lots follow the reference-currency equity: 0.05 x 2.2 = 0.11. Risk is money in EUR, the same fraction of
        # equity: 500 x 200,000 / 100,000 = 1000.0 (not x2.2, which would over-risk by the exchange rate).
        self.assertEqual(one(result)['edits'], dict(Lots_Input='0.11', Risk='1000.0'))
        basis = dict(result['deployBasis'])
        self.assertEqual(basis.pop('manifest')['schema'], 'goat-house-portfolio-v1')
        self.assertEqual(basis, dict(schema=bf.DEPLOY_SCHEMA, scale=2.2, equity='200000.0', referenceEquity='100000', accountCurrency='EUR',
                                     rate='1.1', reviewedAtUtc=int(T0), referenceIdentical=None))
        self.assertEqual(one(run([(member(raw), raw)], account=dict(account, equity=100000.0), symbols=[symbol()]))['edits'], {})

    def test_a_jpy_account_uses_the_inverse_pair_at_the_ask(self):
        account = dict(ACCOUNT, currency='JPY', equity=15000000.0)
        facts = [symbol(trade_tick_value=150.0), symbol('USDJPY', bid=149.9, ask=150.0, point=0.001, digits=3)]
        result = run([(member(KESTREL), KESTREL)], account=account, symbols=facts)
        self.assertEqual(result['conversion']['symbol'], 'USDJPY')
        self.assertAlmostEqual(result['scale'], 1.0)
        # Risk 500 x 150 = 75,000 yen, lowered by the round 5 F1 band to 67,831.76.
        self.assertEqual((one(result)['scaled']['riskSearched'], one(result)['edits']), (75000.0, dict(Risk='67831.76')))
        wrong = run([(member(KESTREL), KESTREL)], account=account, symbols=[symbol(), facts[1]])
        self.assertEqual(one(wrong)['code'], bf.CONTRACT_MISMATCH)

    def test_a_conversion_price_older_than_120_seconds_is_not_used(self):
        # Review 6130418265 item 3: the rate needs a price at most 120 s old (judged with the proven server clock).
        account = dict(ACCOUNT, currency='EUR')
        facts = [symbol('GBPUSD'), symbol('EURUSD', bid=1.2, ask=1.2002)]
        live = lambda age: {'GBPUSD': int(T0 + 180 * 60), 'EURUSD': int(T0 + 180 * 60 - age)}
        raw = kestrel_with(**FIXED)
        fresh = run([(member(raw, canonical='GBPUSD'), raw)], account=account, symbols=facts, quotes=live(120), arrived=['GBPUSD'])
        self.assertEqual(fresh['conversion'], dict(rate=1.2, symbol='EURUSD', side='bid'))
        old = run([(member(raw, canonical='GBPUSD'), raw)], account=account, symbols=facts, quotes=live(121), arrived=['GBPUSD'])
        self.assertEqual((old['conversion'], old['refusal']['code'], old['deployBasis']), (None, bf.ACCOUNT_CURRENCY_UNSUPPORTED, None))

    def test_no_conversion_pair_refuses_every_member(self):
        account = dict(ACCOUNT, currency='CHF')
        result = run([(member(KESTREL), KESTREL), (member(KESTREL, member_id='b'), KESTREL)], account=account)
        self.assertEqual({row['code'] for row in result['members']}, {bf.ACCOUNT_CURRENCY_UNSUPPORTED})
        self.assertEqual((result['scale'], result['offered'], result['refusal']['code'], result['deployBasis']),
                         (None, False, bf.ACCOUNT_CURRENCY_UNSUPPORTED, None))


class BrokerSpecTests(unittest.TestCase):
    def test_non_demo_is_refused(self):
        with self.assertRaises(Refusal) as caught:
            run([(member(KESTREL), KESTREL)], account=dict(ACCOUNT, demo=False))
        self.assertEqual(caught.exception.code, bf.NOT_DEMO_ACCOUNT)

    def test_a_different_contract_size_is_corrected_exactly_for_fixed_lots(self):
        raw = kestrel_with(**FIXED)
        row = one(run([(member(raw), raw)], symbols=[symbol(trade_contract_size=10000.0, trade_tick_value=0.1)]))
        self.assertEqual(row['edits'], dict(Lots_Input='0.5'))
        self.assertEqual(row['deploy']['rules']['contractRatio'], '10')

    def test_a_differently_quoted_instrument_is_a_contract_mismatch(self):
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], symbols=[symbol(trade_tick_value=0.01)]))['code'], bf.CONTRACT_MISMATCH)
        unknown = reference(**{key: None for key in ('tickValue', 'typicalSpreadPts')})
        row = one(run([(member(KESTREL, ref=unknown), KESTREL)]))
        self.assertEqual((row['code'], row['message']), (bf.CONTRACT_MISMATCH, bf.MISSING_REFERENCE_MESSAGE))

    def test_point_distances_convert_exactly_or_refuse(self):
        four = dict(digits=4, point=0.0001, trade_tick_size=0.0001, trade_tick_value=10.0)
        raw = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', Lock_Profit_Size='30.0', Grid_Min='5.0', Grid_Max='100.0', TSL_Size='-0.5'))
        row = one(run([(member(raw, timeframe='M15'), raw)], symbols=[symbol(**four)], spread=1))
        self.assertEqual(row['status'], 'fit')
        # ATR (negative) distances unchanged; Risk lowered by the round 5 F1 point-grid band [0.9025, 1.1025].
        self.assertEqual(row['edits'], dict(Risk='467.46', Grid_Size='1.0', Lock_Profit_Size='3.0', Grid_Min='0.5', Grid_Max='10.0'))
        self.assertEqual(row['pointConversion']['inputs'], dict(Grid_Size='1.0', Lock_Profit_Size='3.0', Grid_Min='0.5', Grid_Max='10.0'))
        clamped = kestrel_with(**dict(NEUTRAL, Grid_Min='4.0'))                # 0.4 would cross the EA's 0.5 minimum
        self.assertEqual(one(run([(member(clamped, timeframe='M15'), clamped)], symbols=[symbol(**four)], spread=1))['code'],
                         bf.POINT_SIZE_MISMATCH)
        odd = dict(point=0.00002, trade_tick_size=0.00002, trade_tick_value=2.0)
        self.assertEqual(one(run([(member(raw), raw)], symbols=[symbol(**odd)], spread=4))['code'], bf.POINT_SIZE_MISMATCH)

    def test_costs_are_reported_not_refused(self):
        row = one(run([(member(KESTREL, ref=reference(swapLong=-5.0, swapShort=0.5)), KESTREL)],
                      symbols=[symbol(swap_long=-20.0, swap_short=-9.0)]))
        self.assertEqual(row['status'], 'fit')
        self.assertEqual(row['costs'], dict(swapLong=-20.0, swapShort=-9.0, referenceSwapLong=-5.0, referenceSwapShort=0.5,
                                            commission=None, commissionSource='not_exposed_by_mt5_sdk'))


class ServerOffsetTests(unittest.TestCase):
    OTHER = dict(ACCOUNT, server='Other-Demo')

    def test_without_the_field_the_server_name_assumption_is_used_and_reported(self):
        row = one(run([(member(KESTREL), KESTREL)], account=self.OTHER, offset=120))     # Darwinex is UTC+3 in October
        self.assertEqual((row['code'], row['serverOffset']['referenceSource']), (bf.SERVER_OFFSET_MISMATCH, 'server_name_assumption'))
        self.assertIn('session hours', row['serverOffset']['dependsOn'])
        result = run([(member(KESTREL), KESTREL)], account=self.OTHER)
        self.assertEqual((one(result)['status'], result['serverOffset']['assumed']), ('fit', True))

    def test_the_member_field_is_judged_first(self):
        fixed_two = member(KESTREL, ref=reference(serverGmtOffset=2))
        self.assertEqual(one(run([(fixed_two, KESTREL)], account=self.OTHER, offset=120))['status'], 'fit')
        row = one(run([(fixed_two, KESTREL)], account=self.OTHER, offset=180))
        self.assertEqual((row['code'], row['serverOffset']['referenceSource'], row['serverOffset']['referenceMinutes']),
                         (bf.SERVER_OFFSET_MISMATCH, 'member', 120))
        result = run([(fixed_two, KESTREL)], account=self.OTHER, offset=120)
        self.assertEqual(result['serverOffset']['assumed'], False)

    def test_the_reference_account_model_is_next(self):
        data = dict(referenceAccount=dict(server='Darwinex-Demo', currency='USD', startingBalance=100000, leverage=200, serverGmtOffset='ny-close'))
        row = one(run([(member(KESTREL), KESTREL)], account=self.OTHER, **data))
        self.assertEqual((row['status'], row['serverOffset']['referenceSource']), ('fit', 'referenceAccount'))
        data['referenceAccount']['serverGmtOffset'] = 0
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], account=self.OTHER, **data))['code'], bf.SERVER_OFFSET_MISMATCH)

    def test_an_unreadable_field_is_never_replaced_by_the_assumption(self):
        row = one(run([(member(KESTREL, ref=reference(serverGmtOffset='EET')), KESTREL)], account=self.OTHER))
        self.assertEqual((row['code'], row['serverOffset']['referenceSource'], row['serverOffset']['referenceMinutes']),
                         (bf.SERVER_OFFSET_MISMATCH, 'member', None))

    def test_offset_neutral_members_pass_any_whole_hour_offset(self):
        neutral = kestrel_with(**NEUTRAL)
        self.assertEqual(one(run([(member(neutral), neutral)], account=self.OTHER, offset=120))['status'], 'fit')
        self.assertEqual(one(run([(member(neutral, timeframe='H4'), neutral)], account=self.OTHER, offset=120))['code'], bf.SERVER_OFFSET_MISMATCH)
        h4 = kestrel_with(**dict(NEUTRAL, RSI_TF_='240'))
        self.assertEqual(one(run([(member(h4), h4)], account=self.OTHER, offset=120))['code'], bf.SERVER_OFFSET_MISMATCH)

    def test_the_offset_models(self):
        self.assertEqual(bf.measured_server_offset_minutes([int(T0 + 10800 - 30)], T0), 180)
        self.assertIsNone(bf.measured_server_offset_minutes([int(T0 + 10800 - 600)], T0), 'a ten-minute-old tick proves nothing')
        self.assertEqual(bf.model_offset_minutes('ny-close', T0), 180)
        self.assertEqual(bf.model_offset_minutes('ny-close', utc(2026, 12, 1)), 120)
        self.assertEqual((bf.model_offset_minutes(5.5, T0), bf.model_offset_minutes(-3, T0)), (330, -180))
        self.assertIsNone(bf.model_offset_minutes(True, T0))
        self.assertEqual(bf.reference_server_offset({}, dict(server='Unknown-Server'), T0), (None, 'unknown'))


class MarginTests(unittest.TestCase):
    def test_member_and_portfolio_margin(self):
        # The EA's own ladder (round 3 items B/B2): FixedLots 0.05 on Kestrel's CumPartial ladder runs 0.05, 0.07, 0.11,
        # 0.18, 0.30, 0.52 at run time; 1.77 lots, both directions 3.54.
        six = kestrel_with(**dict(FIXED, Allow_Opposite_Seq='true'))
        self.assertEqual(one(run([(member(six), six)]))['margin']['peakLots'], 3.54)
        raw = kestrel_with(**dict(FIXED, Allow_Opposite_Seq='true', Max_Seq_Trades='1'))
        # One level: 0.05 lots, both directions 0.1, at 50,000 per lot = 5,000.
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 50000.0}))['margin'],
                         dict(perLot=50000.0, peakLots=0.1, required=5000.0, basis='ea_caps', limit=50000.0))
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 600000.0}))['code'], bf.MARGIN_TOO_HIGH)
        pair = [(member(raw), raw), (member(raw, member_id='b'), raw)]
        result = run(pair, margins={'EURUSD': 300000.0})                     # 30,000 each, 60,000 together
        self.assertEqual({r['status'] for r in result['members']}, {'fit'})
        self.assertEqual((result['offered'], result['refusal']['code'], result['refusal']['message'], result['margin']['required'],
                          result['margin']['limit']),
                         (False, bf.MARGIN_TOO_HIGH, bf.PORTFOLIO_MARGIN_MESSAGE, 60000.0, 50000.0))

    def test_margin_may_use_at_most_half_the_equity(self):
        # Review 6130418265 item 9. Probe: a worst case equal to the equity (margin level 100%) used to fit. Now the
        # rule is peak margin <= 50% of equity (margin level >= 200%); the boundary itself fits.
        raw = kestrel_with(**dict(FIXED, Allow_Opposite_Seq='true', Max_Seq_Trades='1'))   # 0.1 lots (one level, both ways)
        at_equity = one(run([(member(raw), raw)], margins={'EURUSD': 1000000.0}))   # 100,000 = equity
        self.assertEqual((at_equity['code'], at_equity['message'], at_equity['margin']['required']),
                         (bf.MARGIN_TOO_HIGH, "This set could use more than half of this account's equity as margin.", 100000.0))
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 500000.0}))['status'], 'fit')    # exactly 50,000
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 500000.1}))['code'], bf.MARGIN_TOO_HIGH)

    def test_unknown_margin_fails_closed(self):
        row = one(run([(member(KESTREL), KESTREL)], margins={'EURUSD': None}, equity=99000))
        self.assertEqual((row['code'], row['margin']['basis'], row['message']),
                         (bf.MARGIN_UNKNOWN, 'margin_per_lot_unavailable', bf.MESSAGES[bf.MARGIN_UNKNOWN]))
        # An unreadable ladder input leaves the EA's lots unknown (round 3: the ladder, not the caps, sizes the margin).
        no_ladder = kestrel_with(Lots_Exponent='1,4')
        self.assertEqual(one(run([(member(no_ladder), no_ladder)], equity=99000))['margin']['basis'], 'lot_ladder_unknown')
        # On the reference-identical account the exemption stands in, with its reason and the unknown basis kept (a
        # member without reference.startLot: one with it gets a band-lowered Risk, which revokes the exemption).
        row = one(run([(member(KESTREL, ref=NO_START), KESTREL)], margins={'EURUSD': None}))
        self.assertEqual((row['marginReason'], row['margin']['unknownBasis']), (bf.REFERENCE_IDENTICAL_MARGIN, 'margin_per_lot_unavailable'))


class SetEncodingTests(unittest.TestCase):
    def test_utf16le_crlf_with_bom_changes_only_the_edited_value(self):
        edited = bf.rewrite_set(KESTREL, dict(Risk='250.0'))
        self.assertTrue(edited.startswith(b'\xff\xfe'))
        before, after = KESTREL[2:].decode('utf-16-le').split('\r\n'), edited[2:].decode('utf-16-le').split('\r\n')
        self.assertEqual(len(before), len(after))
        self.assertEqual([(b, a) for b, a in zip(before, after) if b != a], [('Risk=500.0', 'Risk=250.0')])
        self.assertEqual(edited.count(b'\r\x00\n\x00'), KESTREL.count(b'\r\x00\n\x00'))

    def test_utf8_bom_lf_and_plain_utf8_are_preserved(self):
        for bom in (b'\xef\xbb\xbf', b''):
            raw = bom + b'; header=1\nRisk=500.0\nLots_Input=0.05\n'
            with self.subTest(bom=bom):
                self.assertEqual(bf.rewrite_set(raw, dict(Risk='250.0')), bom + b'; header=1\nRisk=250.0\nLots_Input=0.05\n')

    def test_a_tuple_keeps_its_ladder_and_mixed_line_ends_are_kept(self):
        raw = utf16(['Risk=500.0||100.0||50.0||1000.0||N', 'Lots_Input=0.05'], newline='\n')
        self.assertEqual(bf.rewrite_set(raw, dict(Risk='250.0')), utf16(['Risk=250.0||100.0||50.0||1000.0||N', 'Lots_Input=0.05'], newline='\n'))

    def test_unsafe_edits_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported broker-fit edit'):
            bf.rewrite_set(KESTREL, dict(Mode_Lots='0'))
        with self.assertRaisesRegex(ValueError, 'Unsupported broker-fit edit'):
            bf.rewrite_set(KESTREL, dict(Risk='1e3'))
        with self.assertRaisesRegex(ValueError, 'does not state'):
            bf.rewrite_set(utf16(['Lots_Input=0.05']), dict(Risk='250.0'))
        with self.assertRaisesRegex(ValueError, 'more than once'):
            bf.rewrite_set(utf16(['Risk=1.0', 'Risk=2.0']), dict(Risk='250.0'))


def plan_block(result, sets=None):
    """The deploy plan's brokerFit block as the app assembles it: deployBasis plus each fit member's deploy entry, plus
    the reference SET bytes of every member it leaves out (excludedSets, round 3 item D; `sets` = {setSha256: bytes})."""
    import base64
    entries = [dict(row['deploy'], index=index) for index, row in enumerate(r for r in result['members'] if r['status'] == 'fit')]
    by_id = {m['memberId']: m for m in result['deployBasis']['manifest']['members']}
    excluded = [dict(memberId=row['memberId'], contentBase64=base64.b64encode(sets[by_id[row['memberId']]['setSha256']]).decode())
                for row in result['members'] if row['status'] != 'fit']
    return dict(result['deployBasis'], members=entries, excludedSets=excluded)


def stale(block, references, **read):
    """stale_members against a live read built by reading()."""
    return bf.stale_members(block, references, SCHEMA, **reading(**read))


def inputs(rows):
    return [row['input'] for row in rows]


IDENTITY_CASES = HERE / 'contracts' / 'deploy-identity' / 'deploy-identity-cases.json'
# Vendored byte-identical from goatai docs/fixtures/deploy-identity-cases.json at goatai#2500 head 1e6b7fa4.
IDENTITY_CASES_SHA256 = '0ac65c400b06cf0bb3e5bfde7abc02c8a755179dc52d129f807a7723288301d6'


class DeployRecordTests(unittest.TestCase):
    def test_entries_bytes_and_record(self):
        result = run([(member(KESTREL), KESTREL)], equity=50000)
        block = plan_block(result)
        entries = bf.deploy_entries(block, [object()])
        deployed = bf.rewrite_set(KESTREL, dict(Risk='209.56'))              # 250.0 lowered by the round 5 F1 band
        self.assertEqual(bf.deployed_bytes(KESTREL, entries[0]), deployed)
        self.assertEqual(entries[0]['rules'], dict(volumeMin='0.01', volumeStep='0.01', volumeMax='50.0', contractRatio='1',
                                                   referenceVolumeMin='0.01', referenceVolumeStep='0.01', referenceVolumeMax='50',
                                                   startLot='0.1'))
        self.assertEqual((entries[0]['brokerSymbol'], entries[0]['deployFileName']), ('EURUSD', 'GOAT V1.49 EURUSD,M1_EURUSD.M1.kestrel.set'))
        sha = hashlib.sha256(deployed).hexdigest()
        self.assertEqual(bf.deploy_record(block), dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, deployIdentity=bf.deploy_identity(0.5, [sha]),
                                                       members=[dict(memberId='EURUSD.M1.kestrel', setSha256Reference=hashlib.sha256(KESTREL).hexdigest(),
                                                                     setSha256Deployed=sha, scale=0.5)]))
        with self.assertRaisesRegex(ValueError, 'differs from the reviewed'):
            bf.deployed_bytes(KESTREL, dict(entries[0], setSha256Deployed='0' * 64))
        with self.assertRaisesRegex(ValueError, 'not the broker-fit reference'):
            bf.deployed_bytes(deployed, entries[0])
        with self.assertRaisesRegex(ValueError, 'every deployed member'):
            bf.deploy_entries(block, [object(), object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            bf.deploy_entries(dict(block, scale=float('nan')), [object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            bf.deploy_entries(dict(block, schema='goat-broker-fit-deploy-v1'), [object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit member'):
            bf.deploy_entries(dict(block, members=[dict(entries[0], rules={})]), [object()])
        # brokerSymbol and deployFileName must be the plan member's symbol and file, and the manifest setName's.
        plan_member = dict(symbol='EURUSD', fileName='GOAT V1.49 EURUSD,M1_EURUSD.M1.kestrel.set')
        bf.deploy_entries(block, [plan_member])
        for forged in (dict(brokerSymbol='EURUSD.raw'), dict(deployFileName='GOAT V1.49 EURUSD,M1_other.set')):
            with self.subTest(forged=forged), self.assertRaisesRegex(ValueError, 'does not match its plan member'):
                bf.deploy_entries(dict(block, members=[dict(entries[0], **forged)]), [plan_member])
        with self.assertRaisesRegex(ValueError, 'not a distinct member'):
            bf.deploy_entries(dict(block, members=[dict(entries[0], memberId='other')]), [object()])

    def test_deploy_identity_reproduces_the_shared_cases(self):
        # Rule 9: the journal's deploy identity is the app's (goatai#2500 houseDeployIdentity), checked on the shared
        # vectors byte for byte: pre-image and sha256 of every case.
        raw = IDENTITY_CASES.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), IDENTITY_CASES_SHA256, 'the vendored copy is byte-identical')
        cases = json.loads(raw)['cases']
        self.assertGreaterEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case['name']):
                self.assertEqual(bf.deploy_identity_preimage(case['scale'], case['setSha256Deployed']), case['preimage'])
                self.assertEqual(bf.deploy_identity(case['scale'], case['setSha256Deployed']), case['sha256'])
        for scale, deployed in ((0, ['a' * 64]), (float('inf'), ['a' * 64]), (1, []), (1, ['A' * 64])):
            with self.subTest(scale=scale, deployed=deployed), self.assertRaises(ValueError):
                bf.deploy_identity(scale, deployed)

    def test_stale_members_judges_the_live_equity_with_the_same_rules(self):
        block = plan_block(run([(member(KESTREL), KESTREL)], equity=50000))   # reviewed Risk 209.56 (250.0 after F1)
        def check(equity, currency='USD'):
            return stale(block, [KESTREL], account=dict(ACCOUNT, equity=equity, currency=currency))
        self.assertEqual(check(50000.0), [])
        self.assertEqual(check(50003.0), [], 'live 209.57 is within one cent above the reviewed 209.56')
        moved = check(50100.0)
        self.assertEqual((len(moved), moved[0]['input'], moved[0]['reviewed']), (1, 'Risk', 209.56))
        self.assertGreater(moved[0]['live'], 209.57)
        self.assertEqual(check(49999.0), [dict(memberId='EURUSD.M1.kestrel', input='Risk', reviewed=209.56, live=209.55)],
                         'a reviewed value above the live one would be rounding up: refused at once')
        self.assertEqual(check(4000.0)[0]['input'], bf.BELOW_MIN_LOT)
        self.assertEqual(check(50000.0, 'EUR')[0]['input'], 'account')
        self.assertEqual(check(None)[0]['input'], 'account')

    def test_stale_lots_use_one_volume_step(self):
        raw = kestrel_with(**FIXED)
        block = plan_block(run([(member(raw), raw)], equity=60000))            # Lots 0.03, Risk 300.0
        rows = stale(block, [raw], account=dict(ACCOUNT, equity=79999.0))
        self.assertEqual(set(inputs(rows)), {'Risk'}, 'lots 0.0399 -> 0.03 is the same step; Risk moved')
        rows = stale(block, [raw], account=dict(ACCOUNT, equity=100000.0))
        self.assertIn(dict(memberId='EURUSD.M1.kestrel', input='Lots_Input', reviewed=0.03, live=0.05), rows)


JCS_CASES = HERE / 'contracts' / 'house-manifest' / 'house-manifest-jcs-cases.json'
# Vendored byte-identical from goatai docs/fixtures/house-manifest-jcs-cases.json (house feed v1.1, goatai 269152191).
JCS_CASES_SHA256 = 'c78e21fdd4866870eebd8d0639c5f01e52ad1f32cf565f55237c50ea18fd3a33'


class ManifestShaTests(unittest.TestCase):
    """Round 4 R1 (goatai#2350 6132804177): the manifest's RFC 8785 JCS sha256, stdlib only, on the shared vectors."""

    def fixture(self):
        raw = JCS_CASES.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), JCS_CASES_SHA256, 'the vendored copy is byte-identical')
        return json.loads(raw)

    def test_every_canonical_case(self):
        cases = self.fixture()['cases']
        self.assertGreaterEqual(len(cases), 9)
        for case in cases:
            with self.subTest(case=case['name']):
                canonical = bf.jcs(case['input'])
                self.assertEqual(canonical, case['canonical'])
                self.assertEqual(hashlib.sha256(canonical.encode('utf-8')).hexdigest(), case['sha256'])

    def test_every_refused_case(self):
        for case in self.fixture()['refusedCases']:
            with self.subTest(case=case['name']), self.assertRaisesRegex(ValueError, 'surrogate'):
                bf.jcs(case['input'])

    def test_every_manifest_case(self):
        for case in self.fixture()['manifestCases']:
            with self.subTest(case=case['name']):
                self.assertEqual(bf.manifest_sha256(case['manifest']), case['manifestSha256'])

    def test_numbers_follow_ecmascript(self):
        # The cases Python's repr writes differently: exponent signs and padding, ints read as doubles, -0.
        for value, text in ((1e21, '1e+21'), (1e-7, '1e-7'), (100000, '100000'), (100.0, '100'), (0.01, '0.01'), (-0.0, '0'),
                            (2 ** 53 + 1, '9007199254740992'), (1.5e300, '1.5e+300'), (123e-20, '1.23e-18')):
            with self.subTest(value=value):
                self.assertEqual(bf.jcs(value), text)
        for bad in (float('nan'), float('inf'), 10 ** 400):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bf.jcs(bad)

    def test_the_review_states_the_manifest_sha_and_the_deploy_requires_it(self):
        data = manifest([member(KESTREL)])
        result = run([(member(KESTREL), KESTREL)])
        self.assertEqual(result['manifestSha256'], bf.manifest_sha256(data))
        data = sign(data)
        with with_test_key():
            self.assertEqual(bf.verify_manifest(data, result['manifestSha256'].upper()), result['manifestSha256'])
        signed = dict(data, signature=dict(alg='ed25519', keyId='goat-house-2026-10-v1', sig='A' * 88))
        self.assertEqual(bf.manifest_sha256(signed), result['manifestSha256'], 'the top-level signature is left out')
        forged = json.loads(json.dumps(data))
        forged['referenceAccount']['startingBalance'] = 10000
        for candidate, sha, reason in ((data, None, 'sha_missing'), (data, '0' * 64, 'sha_mismatch'),
                                       (forged, result['manifestSha256'], 'signature_invalid'), (None, result['manifestSha256'], 'manifest_invalid')):
            with with_test_key(), self.assertRaises(Refusal) as caught:
                bf.verify_manifest(candidate, sha)
            self.assertEqual((caught.exception.code, caught.exception.fields['reason']), (bf.MANIFEST_UNVERIFIED, reason))
            self.assertNotIn(result['manifestSha256'], str(caught.exception) + repr(caught.exception.fields), 'no hash echoed')


KEYS_FILE = HERE / 'contracts' / 'house-manifest' / 'house_portfolio_signing_keys.json'
# Vendored byte-identical from goatai functions/serve-api/config/house_portfolio_signing_keys.json.
KEYS_FILE_SHA256 = '3ea1e7e94dc5a2295587a5d0bf0c93ab4331638f2cc11c1ffbfa2ac43f6cd5d7'


class SignatureTests(unittest.TestCase):
    """Round 5 F2 (goatai#2350 6133583699): the house manifest's ed25519 signature, at review and at deploy."""

    def setUp(self):
        self.data = manifest([member(KESTREL)])
        self.signed = sign(self.data)

    def reason(self, candidate, sha=None, require_sha=False):
        with self.assertRaises(Refusal) as caught:
            bf.verify_manifest(candidate, sha, require_sha=require_sha)
        self.assertEqual(caught.exception.code, bf.MANIFEST_UNVERIFIED)
        self.assertEqual(str(caught.exception), bf.MANIFEST_UNVERIFIED_MESSAGE)
        return caught.exception.fields['reason']

    def test_the_pinned_key_is_the_published_one(self):
        raw = KEYS_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), KEYS_FILE_SHA256, 'the vendored copy is byte-identical')
        self.assertEqual([dict(k) for k in bf.HOUSE_SIGNING_KEYS], json.loads(raw)['keys'])
        ring = bf.house_key_ring()
        self.assertEqual(list(ring), ['goat-house-2026-10-v1'])
        # A pin that does not match its key is refused, never trusted.
        broken = (dict(bf.HOUSE_SIGNING_KEYS[0], spkiDerSha256='0' * 64),)
        with patch.object(bf, 'HOUSE_SIGNING_KEYS', broken), self.assertRaises(ValueError):
            bf.house_key_ring()
        with patch.object(bf, 'HOUSE_SIGNING_KEYS', broken):
            self.assertEqual(self.reason(self.signed), 'verifier_unavailable')

    def test_the_genuine_manifest_passes(self):
        with with_test_key():
            self.assertEqual(bf.verify_manifest(self.signed, require_sha=False), bf.manifest_sha256(self.data))
            self.assertEqual(bf.verify_manifest(self.signed, bf.manifest_sha256(self.data)), bf.manifest_sha256(self.data))

    def test_every_edit_and_every_bad_signature_refuses(self):
        edited_set = json.loads(json.dumps(self.signed))
        edited_set['members'][0]['setSha256'] = hashlib.sha256(KESTREL + b'\x00\x00').hexdigest()   # one SET byte
        edited_risk = json.loads(json.dumps(self.signed))
        edited_risk['referenceAccount']['startingBalance'] = 10000                                   # 10x every Risk
        bad_sig = json.loads(json.dumps(self.signed))
        bad_sig['signature']['sig'] = base64.b64encode(bytes(64)).decode()
        other_key = sign(self.data, key=Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))))
        unknown = sign(self.data, key_id='goat-house-2099-01-v9')
        malformed = dict(self.signed, signature=dict(self.signed['signature'], alg='rsa'))
        with with_test_key():
            for candidate, reason in ((edited_set, 'signature_invalid'), (edited_risk, 'signature_invalid'), (bad_sig, 'signature_invalid'),
                                      (other_key, 'signature_invalid'), (malformed, 'signature_invalid'), (unknown, 'unknown_key'),
                                      (self.data, 'unsigned'), (dict(self.data, signature=None), 'unsigned')):
                with self.subTest(reason=reason, candidate=str(candidate.get('signature'))[:40]):
                    self.assertEqual(self.reason(candidate), reason)
        # The real pin does not trust the test key.
        self.assertEqual(self.reason(self.signed), 'unknown_key')

    def test_without_cryptography_every_house_manifest_refuses(self):
        blocked = {name: None for name in ('cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives',
                                           'cryptography.hazmat.primitives.asymmetric', 'cryptography.hazmat.primitives.asymmetric.ed25519',
                                           'cryptography.hazmat.primitives.serialization', 'cryptography.exceptions')}
        with with_test_key(), patch.dict(sys.modules, blocked):
            self.assertIsNone(bf.house_key_ring())
            self.assertEqual(self.reason(self.signed), 'verifier_unavailable')
            self.assertEqual(self.reason(self.signed, bf.manifest_sha256(self.data), require_sha=True), 'verifier_unavailable')


class DeployRecheckTests(unittest.TestCase):
    """Review 6130418265 items 2, 3, 4 and 7: the deploy re-derives every value from the manifest, the planning equity
    and the LIVE broker, and only compares the plan's claims."""

    def test_plans_expire_after_15_minutes(self):
        block = plan_block(run([(member(KESTREL), KESTREL)], equity=50000))
        live = dict(ACCOUNT, equity=50000.0)
        self.assertEqual(stale(block, [KESTREL], account=live, now=T0 + 900), [])
        self.assertEqual(stale(block, [KESTREL], account=live, now=T0 + 901),
                         [dict(memberId=None, input='reviewedAtUtc', reviewed=int(T0), live=int(T0 + 901))])

    def test_the_rate_is_read_again_at_deploy(self):
        # Probe: a EUR account reviewed at EURUSD 1.20 gets Lots_Input 0.10 -> 0.12; deployed at 1.00 that is +20%.
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.10'))
        account = dict(ACCOUNT, currency='EUR')
        at = lambda rate: [symbol('EURUSD', bid=rate, ask=rate + 0.0002)]
        block = plan_block(run([(member(raw), raw)], account=account, symbols=at(1.2)))
        self.assertEqual((block['rate'], block['members'][0]['edits']), ('1.2', dict(Lots_Input='0.12')))
        self.assertEqual(stale(block, [raw], account=account, symbols=at(1.2)), [])
        rows = stale(block, [raw], account=account, symbols=at(1.0))
        self.assertIn(dict(memberId='EURUSD.M1.kestrel', input='Lots_Input', reviewed='0.12', live=None), rows,
                      'at 1.00 the rules write no Lots_Input edit (0.10), so the reviewed 0.12 is refused')
        # The conversion price must be at most 120 s old at deploy too.
        gbp = kestrel_with(**dict(FIXED, Lots_Input='0.10'))
        pair = [symbol('GBPUSD'), symbol('EURUSD', bid=1.2, ask=1.2002)]
        quotes = lambda age: {'GBPUSD': int(T0 + 180 * 60), 'EURUSD': int(T0 + 180 * 60 - age)}
        block = plan_block(run([(member(gbp, canonical='GBPUSD'), gbp)], account=account, symbols=pair, quotes=quotes(0), arrived=['GBPUSD']))
        self.assertEqual(stale(block, [gbp], account=account, symbols=pair, quotes=quotes(120), arrived=['GBPUSD']), [])
        self.assertEqual(inputs(stale(block, [gbp], account=account, symbols=pair, quotes=quotes(121), arrived=['GBPUSD'])), ['rate'])

    def test_fixed_money_limits_are_rechecked_on_the_live_equity(self):
        # Probe: FixedLots with MinLevelEquity 95000, reviewed at 100,000, deployed at 109,999: the old re-check said
        # [] and the account could lose 14,999 where 5,000 was intended.
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.10', MinLevelEquity='95000.0'))
        block = plan_block(run([(member(raw), raw)]))
        self.assertEqual(block['members'][0]['edits'], {})
        rows = stale(block, [raw], account=dict(ACCOUNT, equity=109999.0))
        self.assertIn(dict(memberId='EURUSD.M1.kestrel', input=bf.CONTRACT_MISMATCH, reviewed=None, live=None), rows)

    def test_below_reference_equity_never_deploys_reference_sized_values(self):
        # Review item 2 probe, per-value side: reviewed with --equity 100000, live 95,000.01. Risk 500 against the
        # live 475 (+5.26%) and a FixedLots 0.10 against the live 0.09 (+11%) are both refused.
        fixed = kestrel_with(**dict(FIXED, Lots_Input='0.10', EA_Desc='F'))
        members = [(member(KESTREL), KESTREL), (member(fixed, member_id='fixed', canonical='GBPUSD'), fixed)]
        facts = [symbol(), symbol('GBPUSD')]
        live = dict(ACCOUNT, equity=95000.01)
        block = plan_block(run(members, equity=100000, account=live, symbols=facts))
        self.assertIsNone(block['referenceIdentical'])
        rows = stale(block, [KESTREL, fixed], account=live, symbols=facts)
        # Kestrel's reviewed Risk 452.21 (500 lowered by the F1 band) is above its live 429.60 (475 lowered).
        self.assertIn(dict(memberId='EURUSD.M1.kestrel', input='Risk', reviewed=452.21, live=429.6), rows)
        self.assertIn(dict(memberId='fixed', input='Lots_Input', reviewed=0.1, live=0.09), rows)

    def test_the_plan_deploys_exactly_the_members_the_review_marked_fit(self):
        # Review 6132018108 item D. Probe: a 35-member portfolio, all fit, and a plan that deploys only member 0 (the
        # other 34 passed as excluded). The old re-check re-derived the plan's own members only: 1 of 1 = 100% fit,
        # []. Now the whole manifest is re-derived and the fit set must be exactly the plan's.
        rows = []
        for index in range(35):
            raw = kestrel_with(EA_Desc='R%02d' % index)
            rows.append((member(raw, member_id='m%02d' % index), raw))
        sets = {m['setSha256']: raw for m, raw in rows}
        result = run(rows, margins={'EURUSD': 500.0})
        self.assertEqual((result['offered'], sum(r['status'] == 'fit' for r in result['members'])), (True, 35))
        full = plan_block(result, sets)
        self.assertEqual(stale(full, [raw for _, raw in rows], margins={'EURUSD': 500.0}), [])
        import base64
        one_of_35 = dict(full, members=full['members'][:1],
                         excludedSets=[dict(memberId=m['memberId'], contentBase64=base64.b64encode(raw).decode()) for m, raw in rows[1:]])
        bf.deploy_entries(one_of_35, [object()])
        found = stale(one_of_35, [rows[0][1]], margins={'EURUSD': 500.0})
        self.assertEqual(found, [dict(memberId=None, input='members', reviewed=['m00'], live=['m%02d' % i for i in range(35)])])
        # A superset: a member the review excluded (no GBPUSD on this broker) forged into the plan.
        gbp = kestrel_with(EA_Desc='G')
        pair = [(member(KESTREL), KESTREL), (member(gbp, member_id='gbp', canonical='GBPUSD'), gbp)]
        reviewed = run(pair)
        self.assertEqual([r['status'] for r in reviewed['members']], ['fit', 'excluded'])
        honest = plan_block(reviewed, {m['setSha256']: raw for m, raw in pair})
        self.assertEqual(inputs(stale(honest, [KESTREL])), [bf.PORTFOLIO_BROKER_UNFIT], 'its fit set matches; 1 of 2 is under 90%')
        forged_entry = dict(honest['members'][0], index=1, memberId='gbp', setSha256Reference=pair[1][0]['setSha256'],
                            setSha256Deployed=pair[1][0]['setSha256'], brokerSymbol='GBPUSD',
                            deployFileName=bf.deploy_file_name(pair[1][0]['setName'], 'GBPUSD'))
        superset = dict(honest, members=honest['members'] + [forged_entry], excludedSets=[])
        bf.deploy_entries(superset, [object(), object()])
        self.assertIn('members', inputs(stale(superset, [KESTREL, gbp])))
        # Every manifest member exactly once: one left out of both lists, or named twice, is refused at validation.
        for broken in (dict(honest, excludedSets=[]), dict(honest, excludedSets=honest['excludedSets'] * 2),
                       dict(honest, excludedSets=[dict(honest['excludedSets'][0], contentBase64=base64.b64encode(KESTREL).decode())])):
            with self.assertRaises(ValueError):
                bf.deploy_entries(broken, [object()])

    def test_the_deploy_trusts_no_plan_value(self):
        # Review item 7. Probe: a hand-made referenceIdentical {startingBalance: '10000'} on a 10k account deployed
        # 100k-sized bytes (10x): the old re-check judged the band against the plan's own startingBalance.
        exempt = plan_block(run([(member(KESTREL, ref=NO_START), KESTREL)]))
        forged = dict(exempt, referenceIdentical=dict(exempt['referenceIdentical'], startingBalance='10000'))
        rows = stale(forged, [KESTREL], account=dict(ACCOUNT, equity=10000.0))
        self.assertEqual(inputs(rows), ['referenceIdentical.equityWithinTolerance'])
        known = plan_block(run([(member(KESTREL), KESTREL)]))                     # no exemption: the claim itself is refused
        rows = stale(dict(known, referenceIdentical=forged['referenceIdentical']), [KESTREL], account=dict(ACCOUNT, equity=10000.0))
        self.assertIn('referenceIdentical.equityWithinTolerance', inputs(rows))
        block = plan_block(run([(member(KESTREL), KESTREL)], equity=50000))
        entry = block['members'][0]
        live = dict(ACCOUNT, equity=50000.0)
        # Rule facts (volume step, contract ratio, start lot ...) are claims compared with the live broker's.
        rules = dict(entry['rules'], volumeStep='0.001', startLot='1')
        self.assertEqual(inputs(stale(dict(block, members=[dict(entry, rules=rules)]), [KESTREL], account=live)), ['rules'])
        # A self-consistent forged edit (its own hash) is refused against the re-derived one.
        bigger = bf.rewrite_set(KESTREL, dict(Risk='1000.0'))
        forged_edit = dict(entry, edits=dict(Risk='1000.0'), setSha256Deployed=hashlib.sha256(bigger).hexdigest())
        self.assertEqual(inputs(stale(dict(block, members=[forged_edit]), [KESTREL], account=live)), ['Risk', 'setSha256Deployed'])
        # A forged planning equity re-derives other bytes; a forged scale or reference equity is refused as a claim.
        self.assertIn('setSha256Deployed', inputs(stale(dict(block, equity='100000'), [KESTREL], account=live)))
        self.assertEqual(inputs(stale(dict(block, scale=1.0), [KESTREL], account=live)), ['scale'])
        self.assertEqual(inputs(stale(dict(block, referenceEquity='50000'), [KESTREL], account=live)), ['referenceEquity'])
        # The rate is never an input: a forged one changes nothing that is deployed (the live rate is used).
        self.assertEqual(stale(dict(block, rate='3'), [KESTREL], account=live), [])
        # The broker symbol the live broker maps now is compared with the plan's.
        moved = [symbol('EURUSD.raw', currency_base='EUR', currency_profit='USD')]
        self.assertIn('brokerSymbol', inputs(stale(block, [KESTREL], account=live, symbols=moved)))


NO_START = reference(startLot=None, startLotSource=None)
FOUR_DIGIT = dict(digits=4, point=0.0001, trade_tick_size=0.0001, trade_tick_value=10.0)


class ReferenceIdenticalTests(unittest.TestCase):
    """goatai#2350 6130033743: a follower of the reference never regresses. Kestrel without reference.startLot has an
    unknown margin; on a reference-identical account its margin check passes, with the reason recorded."""

    def check(self, *, account=None, equity=None, members=None, **options):
        return run(members or [(member(KESTREL, ref=NO_START), KESTREL)], account=account, equity=equity, **options)

    def test_the_exemption_applies_with_its_reason_recorded(self):
        result = self.check()
        row = one(result)
        self.assertEqual((row['status'], row['code'], row['marginReason']), ('fit', None, bf.REFERENCE_IDENTICAL_MARGIN))
        self.assertEqual(row['margin'], dict(perLot=1000.0, peakLots=None, required=None, basis=bf.REFERENCE_IDENTICAL_MARGIN,
                                             unknownBasis='start_lot_unknown'))
        self.assertEqual(row['setSha256Deployed'], row['setSha256Reference'])
        self.assertEqual(result['referenceIdentical'], dict(
            applies=True, used=True, reason=bf.REFERENCE_IDENTICAL_MARGIN, liveEquity=100000.0, liveScale=1.0, equityTolerance=0.05,
            conditions=dict(sameServer=True, sameCurrency=True, sameLeverage=True, equityWithinTolerance=True, scaleOne=True,
                            bytesUnchanged=True)))
        self.assertEqual((result['margin']['exemption'], result['margin']['verified'], result['offered']), (bf.REFERENCE_IDENTICAL_MARGIN, True, True))
        self.assertEqual(result['deployBasis']['referenceIdentical'], dict(server='Darwinex-Demo', currency='USD', leverage=200,
                                                                          startingBalance='100000', reason=bf.REFERENCE_IDENTICAL_MARGIN))
        # A member with a known margin is judged as usual and never carries the reason (FixedLots: the round 6 scale-1.0
        # exemption from the F1 band concerns RiskperSeq members only).
        fixed = kestrel_with(**FIXED)
        known = self.check(members=[(member(fixed), fixed)])
        self.assertEqual((one(known)['marginReason'], one(known)['margin']['basis'], known['referenceIdentical']['used']), (None, 'ea_caps', False))
        self.assertIsNone(known['deployBasis']['referenceIdentical'])

    def test_a_leverage_mismatch_refuses(self):
        result = self.check(account=dict(ACCOUNT, leverage=100))           # 1:100 against the 1:200 reference
        self.assertEqual((one(result)['code'], one(result)['marginReason']), (bf.MARGIN_UNKNOWN, None))
        self.assertEqual((result['referenceIdentical']['conditions']['sameLeverage'], result['referenceIdentical']['used']), (False, False))
        self.assertIsNone(result['deployBasis']['referenceIdentical'])

    def test_equity_outside_five_percent_refuses(self):
        # The account's own equity is judged (the scale is pinned at 1.0 with --equity 100000). The band is ONE-SIDED
        # (review 6130418265 item 2): startingBalance <= live <= startingBalance x 1.05. Probe: live 95,000.01 was
        # exempt before and deployed Risk 500 against an equity-linear 475 (+5.26%).
        for live, fits in ((106000.0, False), (94000.0, False), (105000.0, True), (100000.0, True), (99999.99, False),
                           (95000.01, False), (95000.0, False)):
            with self.subTest(live=live):
                result = self.check(account=dict(ACCOUNT, equity=live), equity=100000)
                self.assertEqual(one(result)['status'] == 'fit', fits)
                self.assertEqual(result['referenceIdentical']['conditions']['equityWithinTolerance'], fits)
                if not fits:
                    self.assertEqual(one(result)['code'], bf.MARGIN_UNKNOWN)

    def test_a_scale_other_than_one_refuses(self):
        result = self.check(account=dict(ACCOUNT, equity=102000.0))         # within 5%, but scale 1.02
        self.assertEqual((one(result)['code'], result['referenceIdentical']['conditions']['scaleOne']), (bf.MARGIN_UNKNOWN, False))
        self.assertEqual(one(self.check(equity=100000.01))['code'], bf.MARGIN_UNKNOWN)

    def test_other_server_or_currency_refuses(self):
        other = self.check(account=dict(ACCOUNT, server='Other-Demo'))
        self.assertEqual((one(other)['code'], other['referenceIdentical']['conditions']['sameServer']), (bf.MARGIN_UNKNOWN, False))

    def test_a_changed_member_byte_refuses(self):
        # The member itself converted (a 4-digit broker point): its bytes change, so no exemption.
        neutral = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', Grid_Min='5.0', Grid_Max='100.0'))
        row = one(self.check(members=[(member(neutral, ref=NO_START), neutral)], symbols=[symbol(**FOUR_DIGIT)], spread=0.8))
        self.assertEqual((row['code'], row['margin']['basis']), (bf.MARGIN_UNKNOWN, 'start_lot_unknown'))
        # Another member's point conversion revokes it for the whole portfolio.
        converted = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', Grid_Min='5.0', Grid_Max='100.0', EA_Desc='B'))
        members = [(member(KESTREL, ref=NO_START), KESTREL), (member(converted, member_id='b', canonical='GBPUSD'), converted)]
        history = {'EURUSD': ticks(), 'GBPUSD': ticks((0.8,), point=0.0001)}
        result = self.check(members=members, symbols=[symbol(), symbol('GBPUSD', **FOUR_DIGIT)], history=history)
        first, second = result['members']
        self.assertEqual((second['status'], second['edits']), ('fit', dict(Risk='467.46', Grid_Size='1.0', Grid_Min='0.5', Grid_Max='10.0')))
        self.assertEqual((first['code'], first['marginReason'], first['margin']['basis']), (bf.MARGIN_UNKNOWN, None, 'start_lot_unknown'))
        self.assertEqual((result['referenceIdentical']['conditions']['bytesUnchanged'], result['referenceIdentical']['used']), (False, False))

    def test_scale_one_deploys_the_reference_bytes_even_with_a_start_lot(self):
        # Round 6 (goatai#2350 6134542541): exactly the reference-identical conditions AND scale 1.0: nothing is
        # modelled, the reference bytes deploy, REFERENCE_IDENTICAL_MARGIN stands in for the margin.
        result = run([(member(KESTREL), KESTREL)])
        row = one(result)
        self.assertEqual((row['status'], row['edits'], row['scaled']['Risk'], row['scaled']['lossBand'], row['marginReason']),
                         ('fit', {}, 500.0, None, bf.REFERENCE_IDENTICAL_MARGIN))
        self.assertEqual(row['margin'], dict(perLot=1000.0, peakLots=None, required=None, basis=bf.REFERENCE_IDENTICAL_MARGIN,
                                             unknownBasis='reference_scale'))
        self.assertTrue(result['referenceIdentical']['used'])
        # Any condition off: the band (live equity under the reference, another server, another leverage, a scale off
        # 1.0 with the planning equity).
        for options in (dict(account=dict(ACCOUNT, equity=99999.0), equity=100000), dict(account=dict(ACCOUNT, server='Other-Demo')),
                        dict(account=dict(ACCOUNT, leverage=100)), dict(equity=100000.01)):
            with self.subTest(options=options):
                row = one(run([(member(KESTREL), KESTREL)], **options))
                self.assertIsNotNone(row['scaled']['lossBand'])
                self.assertIn('Risk', row['edits'])
        # One changed member anywhere revokes it: the member is judged again under the band (not refused).
        converted = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', Grid_Min='5.0', Grid_Max='100.0', EA_Desc='B'))
        members = [(member(KESTREL), KESTREL), (member(converted, member_id='b', canonical='GBPUSD'), converted)]
        history = {'EURUSD': ticks(), 'GBPUSD': ticks((0.8,), point=0.0001)}
        result = run(members, symbols=[symbol(), symbol('GBPUSD', **FOUR_DIGIT)], history=history)
        first = result['members'][0]
        self.assertEqual((first['status'], first['edits'], first['marginReason'], first['margin']['basis']),
                         ('fit', dict(Risk='452.21'), None, 'ea_caps'))
        self.assertEqual((result['referenceIdentical']['conditions']['bytesUnchanged'], result['referenceIdentical']['used']), (False, False))

    def test_the_deploy_recheck_honours_the_scale_one_exemption(self):
        block = plan_block(run([(member(KESTREL), KESTREL)]))
        self.assertEqual((block['referenceIdentical']['startingBalance'], block['members'][0]['edits']), ('100000', {}))
        self.assertEqual(stale(block, [KESTREL]), [])
        self.assertEqual(stale(block, [KESTREL], account=dict(ACCOUNT, equity=104000.0)), [], 'inside the one-sided band')
        # Off the exemption the member falls back to the F1 band, so its re-derived bytes change as well.
        self.assertEqual(inputs(stale(block, [KESTREL], account=dict(ACCOUNT, equity=99999.0))),
                         ['referenceIdentical.equityWithinTolerance', 'referenceIdentical.bytesUnchanged'])
        self.assertEqual(inputs(stale(block, [KESTREL], account=dict(ACCOUNT, leverage=100))),
                         ['referenceIdentical.sameLeverage', 'referenceIdentical.bytesUnchanged'])

    def exempt_block(self):
        return plan_block(self.check())

    def test_the_deploy_recheck_keeps_the_exemption_only_while_every_condition_holds(self):
        block = self.exempt_block()
        def check(equity=100000.0, currency='USD', server='Darwinex-Demo', leverage=200, block=block):
            return stale(block, [KESTREL], account=dict(ACCOUNT, equity=equity, currency=currency, server=server, leverage=leverage))
        self.assertEqual(check(), [])
        self.assertEqual(check(equity=103000.0), [], 'inside the one-sided band: the reference bytes deploy at scale 1.0 by design')
        self.assertEqual(inputs(check(leverage=100)), ['referenceIdentical.sameLeverage'])
        self.assertEqual(inputs(check(equity=106000.0)), ['referenceIdentical.equityWithinTolerance'])
        # Review item 2 probe at deploy: live 95,000.01 (and anything under the reference) is stale.
        self.assertEqual(inputs(check(equity=95000.01)), ['referenceIdentical.equityWithinTolerance'])
        self.assertEqual(inputs(check(equity=99999.99)), ['referenceIdentical.equityWithinTolerance'])
        self.assertEqual(inputs(check(server='Other-Demo')), ['referenceIdentical.sameServer'])
        self.assertEqual(check(currency='EUR')[0]['input'], 'account')
        # The scale and the bytes are re-derived, never read from the plan: a forged scale or edit is refused.
        self.assertEqual(inputs(check(block=dict(block, scale=0.5))), ['scale'])
        edited = dict(block, members=[dict(block['members'][0], edits=dict(Risk='250.0'))])
        self.assertEqual(inputs(check(block=edited)), ['Risk'])
        # A non-exempt member in the same plan gets the per-value check (one-sided inside the band) and every rule at
        # the live equity.
        fixed = kestrel_with(**dict(FIXED, Lots_Input='0.10', EA_Desc='F'))
        members = [(member(KESTREL, ref=NO_START), KESTREL), (member(fixed, member_id='fixed', canonical='GBPUSD'), fixed)]
        facts = [symbol(), symbol('GBPUSD')]
        mixed = plan_block(run(members, symbols=facts))
        self.assertIsNotNone(mixed['referenceIdentical'])
        self.assertEqual(stale(mixed, [KESTREL, fixed], account=dict(ACCOUNT, equity=104000.0), symbols=facts), [])
        self.assertIn(bf.MARGIN_TOO_HIGH, inputs(stale(mixed, [KESTREL, fixed], account=dict(ACCOUNT, equity=104000.0), symbols=facts,
                                                       margins={'EURUSD': 1000.0, 'GBPUSD': 30000.0})))
        bf.deploy_entries(block, [object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            bf.deploy_entries(dict(block, referenceIdentical=dict(block['referenceIdentical'], reason='OTHER')), [object()])


class FakeMT5:
    """The MetaTrader5 adapter as broker-fit reads it. No trading call exists here, and no symbol_select."""
    ACCOUNT_TRADE_MODE_DEMO = 0
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    COPY_TICKS_INFO = 2

    def __init__(self, controller, *, trade_mode=0, symbols=None, clock=None, ticking=True):
        self.c, self.trade_mode, self.clock = controller, trade_mode, clock
        self.symbols = symbols or [symbol()]
        self.calls = []
        self.ticking, self.tick_reads = ticking, 0   # ticking: every read sees a newer tick (an open market)

    def initialize(self, path, timeout=0):
        self.calls.append('initialize'); return True

    def shutdown(self):
        self.calls.append('shutdown')

    def terminal_info(self):
        return SimpleNamespace(path=str(Path(self.c.install['terminal_executable']).parent), data_path=self.c.install['terminal_data_root'],
                               connected=True, trade_allowed=False, build=5200)

    def account_info(self):
        return SimpleNamespace(login=123456, server='Darwinex-Demo', trade_mode=self.trade_mode, currency='USD', equity=100000.0, leverage=200)

    def symbols_get(self):
        return [SimpleNamespace(**s, spread=8, time=0, visible=True) for s in self.symbols]

    def symbol_info(self, name):
        facts = next((s for s in self.symbols if s['name'] == name), None)
        return None if facts is None else SimpleNamespace(**facts, spread=8, time=0, visible=True)

    def symbol_info_tick(self, name):
        self.tick_reads += 1
        stamp = int(self.clock()) + DARWINEX_OFFSET * 60 - 2 if self.ticking else int(T0) + DARWINEX_OFFSET * 60 - 3600
        return SimpleNamespace(time=stamp, time_msc=stamp * 1000 + (self.tick_reads if self.ticking else 0), bid=1.1, ask=1.10008)

    def copy_ticks_range(self, name, start, end, flags):
        self.calls.append(('ticks', name, start, end, flags))
        return ticks(end=self.clock())

    def order_calc_margin(self, action, name, volume, price):
        self.calls.append(('margin', action, name)); return 1000.0 * volume


class FakeTerminalProcess:
    """The process lister: the selected terminal64.exe identity, or None when it is not running."""

    def __init__(self, running=True):
        self.running, self.inspected, self.pid = running, 0, 77

    def inspect(self):
        self.inspected += 1
        return dict(pid=self.pid, executable='terminal64.exe', created_utc='2026-10-13T00:00:%02d+00:00' % (self.pid % 60)) if self.running else None


class ReadBrokerTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.c = SimpleNamespace(root=self.folder / 'state', install=dict(terminal_executable=str(self.folder / 'MT5' / 'terminal64.exe'),
                                 terminal_data_root=str(self.folder / 'data'), ea_version='1.49'), schema=SCHEMA)
        self.session = dict(account=dict(login='123456', server='Darwinex-Demo'))
        self.now = T0
        self.process = FakeTerminalProcess()
        keys = with_test_key(); keys.start(); self.addCleanup(keys.stop)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def read(self, mt5):
        return bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock, process=self.process,
                              sleep=self.sleep)

    def write_portfolio(self):
        data = sign(manifest([member(KESTREL)]))
        (self.folder / 'house.json').write_text(json.dumps(data))
        (self.folder / data['members'][0]['setSha256']).write_bytes(KESTREL)
        return self.folder / 'house.json'

    def test_the_cli_reads_six_hours_of_ticks_in_one_short_session(self):
        mt5 = FakeMT5(self.c, clock=self.clock)
        portfolio = self.write_portfolio()
        before = sorted(str(p) for p in self.folder.rglob('*') if 'state' not in p.parts)
        with patch('studio_onboarding.session_state', return_value=(self.session, None)):
            result = bf.broker_fit(self.c, portfolio, mt5=mt5, clock=self.clock, process=self.process, sleep=self.sleep)
        self.assertEqual((result['schema'], result['offered'], one(result)['status']), (bf.SCHEMA, True, 'fit'))
        self.assertEqual((one(result)['spread']['ticks'], result['serverOffset']['brokerMinutes']), (720, 180))
        tick_calls = [call for call in mt5.calls if call[0] == 'ticks']
        server_now = datetime.fromtimestamp(T0 + 180 * 60, timezone.utc)
        self.assertEqual(tick_calls, [('ticks', 'EURUSD', server_now - timedelta(hours=6), server_now, FakeMT5.COPY_TICKS_INFO)])
        self.assertEqual((mt5.calls[0], mt5.calls[-1]), ('initialize', 'shutdown'))
        self.assertEqual(sorted(str(p) for p in self.folder.rglob('*') if 'state' not in p.parts), before, 'nothing written')

    def test_the_rollover_hour_does_not_refuse_up_front(self):
        self.now = utc(2026, 10, 13, 20, 30)                                    # 16:30 New York: the history still counts
        mt5 = FakeMT5(self.c, clock=self.clock)
        account, symbols, history, quotes, margins, now, arrived = self.read(mt5)
        self.assertEqual((len(history['EURUSD']), now, arrived), (720, self.now, ['EURUSD']))
        self.assertEqual(bf.history_spread(history['EURUSD'], point=Decimal('0.00001'), offset_minutes=180)[1], 660)

    def test_non_demo_is_refused_before_reading_ticks(self):
        mt5 = FakeMT5(self.c, trade_mode=2, clock=self.clock)
        with self.assertRaises(Refusal) as caught:
            self.read(mt5)
        self.assertEqual(caught.exception.code, bf.NOT_DEMO_ACCOUNT)
        self.assertFalse([call for call in mt5.calls if call[0] in ('ticks', 'margin')])
        self.assertEqual(mt5.calls[-1], 'shutdown')

    def test_initialize_is_never_called_when_mt5_is_not_running(self):
        # Attach-only (accepted with review 6130418265): MetaTrader5.initialize(path) STARTS a closed MT5 and
        # shutdown() leaves it running, so no matching terminal64.exe process means nothing is called at all.
        mt5 = FakeMT5(self.c, clock=self.clock)
        self.process.running = False
        with self.assertRaises(Refusal) as caught:
            self.read(mt5)
        self.assertEqual((caught.exception.code, str(caught.exception)),
                         ('MT5_NOT_RUNNING', 'Start MT5 and sign in to your demo account, then check again.'))
        self.assertEqual((mt5.calls, self.process.inspected), ([], 1), 'initialize never called; nothing launched')
        portfolio = self.write_portfolio()
        with patch('studio_onboarding.session_state', return_value=(self.session, None)), self.assertRaises(Refusal) as caught:
            bf.broker_fit(self.c, portfolio, mt5=mt5, clock=self.clock, process=self.process, sleep=self.sleep)
        self.assertEqual((caught.exception.code, mt5.calls), (bf.MT5_NOT_RUNNING, []))
        # The default lister is the selected-terminal inventory (exact terminal_executable path).
        with patch('studio_seed_process.WindowsSeedProcess', return_value=FakeTerminalProcess(running=False)) as lister:
            with self.assertRaises(Refusal):
                bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock, sleep=self.sleep)
        lister.assert_called_once_with(self.c)
        self.assertEqual(mt5.calls, [])

    def test_a_terminal_started_by_initialize_is_dropped_and_refused(self):
        # Review 6131884216 item C: MT5 was running at the check (pid 77) but exited before initialize(), which then
        # started a new terminal (pid 78). The re-scan of the exact executable sees another process: shutdown() and
        # refuse MT5_STARTED_BY_CHECK; nothing is read from it.
        process = self.process
        class StartsOne(FakeMT5):
            def initialize(self, path, timeout=0):
                self.calls.append('initialize')
                process.pid = 78
                return True
        mt5 = StartsOne(self.c, clock=self.clock)
        with self.assertRaises(Refusal) as caught:
            self.read(mt5)
        self.assertEqual((caught.exception.code, str(caught.exception)),
                         ('MT5_STARTED_BY_CHECK', 'GOAT started MT5 by accident; close it and check again.'))
        self.assertEqual((caught.exception.fields['pidBefore'], caught.exception.fields['pidAfter']), (77, 78))
        self.assertEqual(mt5.calls, ['initialize', 'shutdown'], 'the link is dropped, nothing is read')
        # A failed initialize() that still started one is refused the same way; the same process attaches as before.
        process.pid = 77
        class FailsButStarts(StartsOne):
            def initialize(self, path, timeout=0):
                super().initialize(path, timeout)
                return False
        with self.assertRaises(Refusal) as caught:
            self.read(FailsButStarts(self.c, clock=self.clock))
        self.assertEqual(caught.exception.code, bf.MT5_STARTED_BY_CHECK)
        process.pid = 77
        self.assertEqual(self.read(FakeMT5(self.c, clock=self.clock))[0]['login'], '123456')

    def test_a_skewed_pc_clock_leaves_the_offset_unknown(self):
        # Re-review 6132018108 (contract Decision 10): the offset is the tick time minus THIS PC's clock. The app passes
        # its server time (--server-time-utc); more than 120 s apart, no tick proves the offset.
        mt5 = FakeMT5(self.c, clock=self.clock)
        read = lambda server: bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock,
                                             process=self.process, sleep=self.sleep, server_time_utc=server)
        self.assertEqual(read(T0 - 120)[6], ['EURUSD'], 'within 120 s: trusted')
        account, symbols, history, quotes, margins, now, arrived = read(T0 - 121)
        self.assertEqual((arrived, history), ([], {}))
        self.assertEqual(read(None)[6], ['EURUSD'], 'not given: unchanged')
        with patch('studio_onboarding.session_state', return_value=(self.session, None)), self.assertRaisesRegex(ValueError, 'unix seconds'):
            bf.broker_fit(self.c, self.write_portfolio(), mt5=mt5, clock=self.clock, process=self.process, server_time_utc=float('nan'))

    def test_a_market_without_new_ticks_leaves_the_clock_unknown(self):
        # Review 6130418265 item 8 at the read: the last tick is an hour old and never changes. No arrival within the
        # bounded window -> no offset, no tick history read, and the result refuses rather than guessing.
        mt5 = FakeMT5(self.c, clock=self.clock, ticking=False)
        account, symbols, history, quotes, margins, now, arrived = self.read(mt5)
        self.assertEqual((arrived, history), ([], {}))
        self.assertLessEqual(now - T0, bf.ARRIVAL_WINDOW_SECONDS + bf.ARRIVAL_POLL_SECONDS)
        self.assertGreaterEqual(now - T0, bf.ARRIVAL_WINDOW_SECONDS)
        result = bf.build_result(manifest([member(KESTREL)]), {hashlib.sha256(KESTREL).hexdigest(): KESTREL}, account=account,
                                 symbols=symbols, ticks=history, quotes=quotes, margins=margins, schema=SCHEMA, utc_now=now, arrived=arrived)
        self.assertEqual((result['serverOffset']['brokerMinutes'], one(result)['code']), (None, bf.SPREAD_SAMPLE_UNAVAILABLE))

    def test_portfolio_files_must_verify(self):
        portfolio = self.write_portfolio()
        data = json.loads(portfolio.read_text())
        (self.folder / data['members'][0]['setSha256']).write_bytes(KESTREL + b'\x00\x00')
        with self.assertRaises(Refusal) as caught:
            bf.load_portfolio(portfolio)
        self.assertEqual((caught.exception.code, caught.exception.fields['members']), (bf.PORTFOLIO_INVALID, ['EURUSD.M1.kestrel']))
        with self.assertRaises(Refusal):
            bf.load_portfolio(self.folder / 'saved.goatportfolio')
        with self.assertRaises(Refusal) as caught:
            bf.validate_manifest(manifest([member(KESTREL)], riskScaling='fixed'))
        self.assertEqual(caught.exception.code, bf.RISK_SCALING_UNSUPPORTED)

    def test_the_cli_contract_is_declared(self):
        from goat_studio import OPERATION_CONTRACTS
        contract = OPERATION_CONTRACTS['broker-fit']
        self.assertEqual((contract['required'], contract['optional']), (['portfolio'], ['equity', 'sets', 'server-time-utc']))
        for phrase in ('NOT_DEMO_ACCOUNT', 'Never writes', 'last 6 h of real ticks', 'MARGIN_UNKNOWN', 'FIT_STALE', 'server-name assumption',
                       'MT5_NOT_RUNNING', 'MARGIN_TOO_HIGH', 'MONEY_VALUE_UNREADABLE'):
            self.assertIn(phrase, contract['effect'])


if __name__ == '__main__':
    unittest.main()
