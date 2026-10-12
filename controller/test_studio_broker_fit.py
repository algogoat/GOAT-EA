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


def run(members, *, account=None, symbols=None, spread=None, history=None, offset=DARWINEX_OFFSET, margins=None, equity=None,
        **manifest_changes):
    """build_result over plain data: every symbol has 6 h of ticks at `spread` points (default 8) and a fresh last tick."""
    symbols = symbols if symbols is not None else [symbol()]
    data = manifest([m for m, _ in members], **manifest_changes)
    sets = {m['setSha256']: raw for m, raw in members}
    names = [s['name'] for s in symbols]
    series = history if history is not None else {s['name']: ticks((spread or 8,), point=s['point'], offset=offset) for s in symbols}
    quotes = {name: int(T0 + offset * 60) for name in names}
    return bf.build_result(data, sets, account=dict(account or ACCOUNT), symbols=symbols, ticks=series, quotes=quotes,
                           margins=margins if margins is not None else {name: 1000.0 for name in names}, schema=SCHEMA,
                           utc_now=T0, equity=equity)


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
        data = manifest([member(KESTREL)])
        result = bf.build_result(data, {data['members'][0]['setSha256']: KESTREL}, account=dict(ACCOUNT), symbols=[symbol()],
                                 ticks={'EURUSD': ticks()}, quotes={'EURUSD': int(T0 + 180 * 60 - 4200)}, margins={'EURUSD': 1000.0},
                                 schema=SCHEMA, utc_now=T0)
        self.assertEqual((one(result)['code'], result['serverOffset']['brokerMinutes']), (bf.SPREAD_SAMPLE_UNAVAILABLE, None))

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
        result = run([(member(KESTREL), KESTREL)])
        row = one(result)
        self.assertEqual((result['scale'], row['status'], row['edits']), (1.0, 'fit', {}))
        self.assertEqual(row['setSha256Deployed'], row['setSha256Reference'])
        self.assertEqual(row['setSha256Reference'], hashlib.sha256(KESTREL).hexdigest())
        self.assertEqual(bf.rewrite_set(KESTREL, row['edits']), KESTREL)
        self.assertEqual(row['scaled'], dict(Risk=500.0, Lots_Max=20.0, Lots_Max_Cum=50.0, Lots_Input=0.05, startLot=0.1))
        self.assertEqual(row['startLotSource'], TRACE)
        json.dumps(result, allow_nan=False)

    def test_risk_scales_and_the_lot_multipliers_do_not(self):
        # Lots_Max and Lots_Max_Cum multiply the start lot (EA mq5:1372, 1366), which already follows Risk: scaling them
        # too would scale the caps twice. Risk 500.0 at half the equity is 250.0; the multipliers stay 20.0 and 50.0.
        row = one(run([(member(KESTREL), KESTREL)], equity=50000))
        self.assertEqual(row['edits'], dict(Risk='250.0'))
        self.assertEqual((row['scaled']['Risk'], row['scaled']['Lots_Max'], row['scaled']['Lots_Max_Cum'], row['scaled']['startLot']),
                         (250.0, 20.0, 50.0, 0.05))
        deployed = bf.rewrite_set(KESTREL, row['edits'])
        self.assertEqual(hashlib.sha256(deployed).hexdigest(), row['setSha256Deployed'])
        values = bf.set_values(deployed, SCHEMA)
        self.assertEqual((values['Risk'], values['Lots_Max'], values['Lots_Max_Cum'], values['Lots_Input']), ('250.0', '20.0', '50.0', '0.05'))

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
        # reference.startLot 0.1 follows the scaled Risk: 0.099 -> 0.09 at 99,000; 0.0099 -> 0.00 at 9,900.
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=99000))['scaled']['startLot'], 0.09)
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=10000))['scaled']['startLot'], 0.01)
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=9999.99))['code'], bf.BELOW_MIN_LOT)
        # Risk under the EA's 10 is refused even with a large start lot (EA mq5:3253).
        self.assertEqual(one(run([(member(KESTREL, ref=reference(startLot=10)), KESTREL)], equity=1999))['code'], bf.BELOW_MIN_LOT)
        # The start lot follows the Risk actually written (rounded down to the cent): 3 x 166.66/500 = 0.99996 -> 0.99.
        self.assertEqual(one(run([(member(KESTREL, ref=reference(startLot=3)), KESTREL)], equity=33333.33, margins={'EURUSD': 100.0}))['scaled'],
                         dict(Risk=166.66, Lots_Max=20.0, Lots_Max_Cum=50.0, Lots_Input=0.05, startLot=0.99))

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
        result = run([(member(KESTREL), KESTREL)], equity=10000)
        self.assertEqual((result['minEquity'], result['offered']), (10000.0, True))
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
        result = run(rows)
        self.assertEqual((result['riskWeighting'], result['tradableRiskShare'], result['offered']), ('risk', 0.9, True))
        rows[8] = (member(rows[8][1], member_id='m8', canonical='GBPUSD'), rows[8][1])
        result = run(rows)
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
        self.assertEqual(result['deployBasis'], dict(schema=bf.DEPLOY_SCHEMA, scale=2.2, referenceEquity='100000', accountCurrency='EUR',
                                                     rate='1.1', referenceIdentical=None))
        self.assertEqual(one(run([(member(raw), raw)], account=dict(account, equity=100000.0), symbols=[symbol()]))['edits'], {})

    def test_a_jpy_account_uses_the_inverse_pair_at_the_ask(self):
        account = dict(ACCOUNT, currency='JPY', equity=15000000.0)
        facts = [symbol(trade_tick_value=150.0), symbol('USDJPY', bid=149.9, ask=150.0, point=0.001, digits=3)]
        result = run([(member(KESTREL), KESTREL)], account=account, symbols=facts)
        self.assertEqual(result['conversion']['symbol'], 'USDJPY')
        self.assertAlmostEqual(result['scale'], 1.0)
        self.assertEqual(one(result)['edits'], dict(Risk='75000.0'))
        wrong = run([(member(KESTREL), KESTREL)], account=account, symbols=[symbol(), facts[1]])
        self.assertEqual(one(wrong)['code'], bf.CONTRACT_MISMATCH)

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
        raw = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', Lock_Profit_Size='30.0', Grid_Min='-1.5', TSL_Size='-0.5'))
        row = one(run([(member(raw, timeframe='M15'), raw)], symbols=[symbol(**four)], spread=1))
        self.assertEqual(row['status'], 'fit')
        self.assertEqual(row['edits'], dict(Grid_Size='1.0', Lock_Profit_Size='3.0'))   # ATR (negative) distances unchanged
        self.assertEqual(row['pointConversion']['inputs'], dict(Grid_Size='1.0', Lock_Profit_Size='3.0'))
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
        raw = kestrel_with(**dict(FIXED, Allow_Opposite_Seq='true'))
        # 0.05 x Lots_Max_Cum 50 = 2.5 lots, both directions = 5 lots, at 1,000 per lot = 5,000.
        self.assertEqual(one(run([(member(raw), raw)]))['margin'], dict(perLot=1000.0, peakLots=5.0, required=5000.0, basis='ea_caps'))
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 30000.0}))['code'], bf.MARGIN_INSUFFICIENT)
        pair = [(member(raw), raw), (member(raw, member_id='b'), raw)]
        result = run(pair, margins={'EURUSD': 12000.0})                      # 60,000 each, 120,000 together
        self.assertEqual({r['status'] for r in result['members']}, {'fit'})
        self.assertEqual((result['offered'], result['refusal']['code'], result['margin']['required']), (False, bf.MARGIN_INSUFFICIENT, 120000.0))

    def test_unknown_margin_fails_closed(self):
        row = one(run([(member(KESTREL), KESTREL)], margins={'EURUSD': None}, equity=99000))
        self.assertEqual((row['code'], row['margin']['basis'], row['message']),
                         (bf.MARGIN_UNKNOWN, 'margin_per_lot_unavailable', bf.MESSAGES[bf.MARGIN_UNKNOWN]))
        no_cap = kestrel_with(Lots_Max_Cum='0.0', Lots_Max='0.0')
        self.assertEqual(one(run([(member(no_cap), no_cap)], equity=99000))['margin']['basis'], 'no_lot_cap')
        # On the reference-identical account the exemption stands in, with its reason and the unknown basis kept.
        row = one(run([(member(KESTREL), KESTREL)], margins={'EURUSD': None}))
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


def plan_block(result):
    """The deploy plan's brokerFit block as the app assembles it: deployBasis plus each fit member's deploy entry."""
    entries = [dict(row['deploy'], index=index) for index, row in enumerate(r for r in result['members'] if r['status'] == 'fit')]
    return dict(result['deployBasis'], members=entries)


class DeployRecordTests(unittest.TestCase):
    def test_entries_bytes_and_record(self):
        result = run([(member(KESTREL), KESTREL)], equity=50000)
        block = plan_block(result)
        entries = bf.deploy_entries(block, [object()])
        deployed = bf.rewrite_set(KESTREL, dict(Risk='250.0'))
        self.assertEqual(bf.deployed_bytes(KESTREL, entries[0]), deployed)
        self.assertEqual(entries[0]['rules'], dict(volumeMin='0.01', volumeStep='0.01', volumeMax='50.0', contractRatio='1',
                                                   referenceVolumeMin='0.01', startLot='0.1'))
        self.assertEqual(bf.deploy_record(block), dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, members=[dict(
            memberId='EURUSD.M1.kestrel', setSha256Reference=hashlib.sha256(KESTREL).hexdigest(),
            setSha256Deployed=hashlib.sha256(deployed).hexdigest(), scale=0.5)]))
        with self.assertRaisesRegex(ValueError, 'differs from the reviewed'):
            bf.deployed_bytes(KESTREL, dict(entries[0], setSha256Deployed='0' * 64))
        with self.assertRaisesRegex(ValueError, 'not the broker-fit reference'):
            bf.deployed_bytes(deployed, entries[0])
        with self.assertRaisesRegex(ValueError, 'every deployed member'):
            bf.deploy_entries(block, [object(), object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            bf.deploy_entries(dict(block, scale=float('nan')), [object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit member'):
            bf.deploy_entries(dict(block, members=[dict(entries[0], rules={})]), [object()])

    def test_stale_members_judges_the_live_equity_with_the_same_rules(self):
        block = plan_block(run([(member(KESTREL), KESTREL)], equity=50000))   # reviewed Risk 250.0
        def stale(equity, currency='USD'):
            return bf.stale_members(block, [KESTREL], SCHEMA, equity=equity, currency=currency)
        self.assertEqual(stale(50000.0), [])
        self.assertEqual(stale(50003.0), [], 'live 250.01 is within one cent above the reviewed 250.0')
        self.assertEqual(stale(50004.0), [dict(memberId='EURUSD.M1.kestrel', input='Risk', reviewed=250.0, live=250.02)])
        self.assertEqual(stale(49999.0), [dict(memberId='EURUSD.M1.kestrel', input='Risk', reviewed=250.0, live=249.99)],
                         'a reviewed value above the live one would be rounding up: refused at once')
        self.assertEqual(stale(4000.0)[0]['input'], bf.BELOW_MIN_LOT)
        self.assertEqual(stale(50000.0, 'EUR')[0]['input'], 'account')
        self.assertEqual(stale(None)[0]['input'], 'account')

    def test_stale_lots_use_one_volume_step(self):
        raw = kestrel_with(**FIXED)
        block = plan_block(run([(member(raw), raw)], equity=60000))            # Lots 0.03, Risk 300.0
        stale = bf.stale_members(block, [raw], SCHEMA, equity=79999.0, currency='USD')
        self.assertEqual({row['input'] for row in stale}, {'Risk'}, 'lots 0.0399 -> 0.03 is the same step; Risk moved')
        stale = bf.stale_members(block, [raw], SCHEMA, equity=100000.0, currency='USD')
        self.assertIn(dict(memberId='EURUSD.M1.kestrel', input='Lots_Input', reviewed=0.03, live=0.05), stale)


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
            applies=True, used=True, reason=bf.REFERENCE_IDENTICAL_MARGIN, liveEquity=100000.0, equityTolerance=0.05,
            conditions=dict(sameServer=True, sameCurrency=True, sameLeverage=True, equityWithinTolerance=True, scaleOne=True,
                            bytesUnchanged=True)))
        self.assertEqual((result['margin']['exemption'], result['margin']['verified'], result['offered']), (bf.REFERENCE_IDENTICAL_MARGIN, True, True))
        self.assertEqual(result['deployBasis']['referenceIdentical'], dict(server='Darwinex-Demo', currency='USD', leverage=200,
                                                                          startingBalance='100000', reason=bf.REFERENCE_IDENTICAL_MARGIN))
        # A member with a known margin is judged as usual and never carries the reason.
        known = self.check(members=[(member(KESTREL), KESTREL)])
        self.assertEqual((one(known)['marginReason'], one(known)['margin']['basis'], known['referenceIdentical']['used']), (None, 'ea_caps', False))
        self.assertIsNone(known['deployBasis']['referenceIdentical'])

    def test_a_leverage_mismatch_refuses(self):
        result = self.check(account=dict(ACCOUNT, leverage=100))           # 1:100 against the 1:200 reference
        self.assertEqual((one(result)['code'], one(result)['marginReason']), (bf.MARGIN_UNKNOWN, None))
        self.assertEqual((result['referenceIdentical']['conditions']['sameLeverage'], result['referenceIdentical']['used']), (False, False))
        self.assertIsNone(result['deployBasis']['referenceIdentical'])

    def test_equity_outside_five_percent_refuses(self):
        # The account's own equity is judged (the scale is pinned at 1.0 with --equity 100000).
        for live, fits in ((106000.0, False), (94000.0, False), (105000.0, True), (95000.0, True)):
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
        neutral = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0'))
        row = one(self.check(members=[(member(neutral, ref=NO_START), neutral)], symbols=[symbol(**FOUR_DIGIT)], spread=0.8))
        self.assertEqual((row['code'], row['margin']['basis']), (bf.MARGIN_UNKNOWN, 'start_lot_unknown'))
        # Another member's point conversion revokes it for the whole portfolio.
        converted = kestrel_with(**dict(NEUTRAL, Grid_Size='10.0', EA_Desc='B'))
        members = [(member(KESTREL, ref=NO_START), KESTREL), (member(converted, member_id='b', canonical='GBPUSD'), converted)]
        history = {'EURUSD': ticks(), 'GBPUSD': ticks((0.8,), point=0.0001)}
        result = self.check(members=members, symbols=[symbol(), symbol('GBPUSD', **FOUR_DIGIT)], history=history)
        first, second = result['members']
        self.assertEqual((second['status'], second['edits']), ('fit', dict(Grid_Size='1.0')))
        self.assertEqual((first['code'], first['marginReason'], first['margin']['basis']), (bf.MARGIN_UNKNOWN, None, 'start_lot_unknown'))
        self.assertEqual((result['referenceIdentical']['conditions']['bytesUnchanged'], result['referenceIdentical']['used']), (False, False))

    def exempt_block(self):
        return plan_block(self.check())

    def test_the_deploy_recheck_keeps_the_exemption_only_while_every_condition_holds(self):
        block = self.exempt_block()
        def stale(equity=100000.0, currency='USD', server='Darwinex-Demo', leverage=200, block=block):
            return bf.stale_members(block, [KESTREL], SCHEMA, equity=equity, currency=currency, server=server, leverage=leverage)
        self.assertEqual(stale(), [])
        self.assertEqual(stale(equity=103000.0), [], 'within 5%: the reference bytes deploy at scale 1.0 by design')
        self.assertEqual([row['input'] for row in stale(leverage=100)], ['referenceIdentical.sameLeverage'])
        self.assertEqual([row['input'] for row in stale(equity=106000.0)], ['referenceIdentical.equityWithinTolerance'])
        self.assertEqual([row['input'] for row in stale(server='Other-Demo')], ['referenceIdentical.sameServer'])
        self.assertEqual(stale(currency='EUR')[0]['input'], 'account')
        self.assertEqual([row['input'] for row in stale(block=dict(block, scale=0.5))], ['referenceIdentical.scaleOne'])
        edited = dict(block, members=[dict(block['members'][0], edits=dict(Risk='250.0'))])
        self.assertEqual([row['input'] for row in stale(block=edited)], ['referenceIdentical.bytesUnchanged'])
        bf.deploy_entries(block, [object()])
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            bf.deploy_entries(dict(block, referenceIdentical=dict(block['referenceIdentical'], reason='OTHER')), [object()])


class FakeMT5:
    """The MetaTrader5 adapter as broker-fit reads it. No trading call exists here, and no symbol_select."""
    ACCOUNT_TRADE_MODE_DEMO = 0
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    COPY_TICKS_INFO = 2

    def __init__(self, controller, *, trade_mode=0, symbols=None, clock=None):
        self.c, self.trade_mode, self.clock = controller, trade_mode, clock
        self.symbols = symbols or [symbol()]
        self.calls = []

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
        return SimpleNamespace(time=int(self.clock()) + DARWINEX_OFFSET * 60 - 2, bid=1.1, ask=1.10008)

    def copy_ticks_range(self, name, start, end, flags):
        self.calls.append(('ticks', name, start, end, flags))
        return ticks(end=self.clock())

    def order_calc_margin(self, action, name, volume, price):
        self.calls.append(('margin', action, name)); return 1000.0 * volume


class ReadBrokerTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.c = SimpleNamespace(root=self.folder / 'state', install=dict(terminal_executable=str(self.folder / 'MT5' / 'terminal64.exe'),
                                 terminal_data_root=str(self.folder / 'data'), ea_version='1.49'), schema=SCHEMA)
        self.session = dict(account=dict(login='123456', server='Darwinex-Demo'))
        self.now = T0

    def clock(self):
        return self.now

    def write_portfolio(self):
        data = manifest([member(KESTREL)])
        (self.folder / 'house.json').write_text(json.dumps(data))
        (self.folder / data['members'][0]['setSha256']).write_bytes(KESTREL)
        return self.folder / 'house.json'

    def test_the_cli_reads_six_hours_of_ticks_in_one_short_session(self):
        mt5 = FakeMT5(self.c, clock=self.clock)
        portfolio = self.write_portfolio()
        before = sorted(str(p) for p in self.folder.rglob('*') if 'state' not in p.parts)
        with patch('studio_onboarding.session_state', return_value=(self.session, None)):
            result = bf.broker_fit(self.c, portfolio, mt5=mt5, clock=self.clock)
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
        account, symbols, history, quotes, margins, now = bf.read_broker(self.c, self.session, manifest([member(KESTREL)]),
                                                                        mt5=mt5, clock=self.clock)
        self.assertEqual((len(history['EURUSD']), now), (720, self.now))
        self.assertEqual(bf.history_spread(history['EURUSD'], point=Decimal('0.00001'), offset_minutes=180)[1], 660)

    def test_non_demo_is_refused_before_reading_ticks(self):
        mt5 = FakeMT5(self.c, trade_mode=2, clock=self.clock)
        with self.assertRaises(Refusal) as caught:
            bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock)
        self.assertEqual(caught.exception.code, bf.NOT_DEMO_ACCOUNT)
        self.assertFalse([call for call in mt5.calls if call[0] in ('ticks', 'margin')])
        self.assertEqual(mt5.calls[-1], 'shutdown')

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
        self.assertEqual((contract['required'], contract['optional']), (['portfolio'], ['equity', 'sets']))
        for phrase in ('NOT_DEMO_ACCOUNT', 'Never writes', 'last 6 h of real ticks', 'MARGIN_UNKNOWN', 'FIT_STALE', 'server-name assumption'):
            self.assertIn(phrase, contract['effect'])


if __name__ == '__main__':
    unittest.main()
