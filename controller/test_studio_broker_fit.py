"""broker-fit + equity_linear risk scaling (controller/contracts/broker-fit.md). Fixture-only: the MT5 SDK is a fake.

The real reference SET is controller/contracts/profile-fixtures/kestrel-b35-01.set: Balanced35 B35-01 Kestrel, UTF-16LE
with a BOM and CRLF, Mode_Lots=RiskperSeq, Risk=500.0, Lots_Max=20.0, Lots_Max_Cum=50.0, ATR distances, session hours.
"""
import base64
from datetime import datetime, timezone
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
# Tuesday 2026-10-13 14:00 UTC = 10:00 New York (EDT): outside rollover and the weekend. Darwinex is UTC+3 then.
T0 = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc).timestamp()
DARWINEX_OFFSET = 180


def utf16(lines, newline='\r\n'):
    return b'\xff\xfe' + (newline.join(lines) + newline).encode('utf-16-le')


def kestrel_with(**changes):
    """The Kestrel SET with some values replaced (same encoding and line ends)."""
    return bf.rewrite_set(KESTREL, {}) if not changes else _replace(KESTREL, changes)


def _replace(raw, changes):
    text, encoding, bom = bf.set_encoding(raw)
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
    value = dict(server='Darwinex-Demo', symbol=symbol, digits=5, point=0.00001, tickSize=0.00001, tickValue=1, contractSize=100000,
                 volumeMin=0.01, volumeStep=0.01, volumeMax=50, typicalSpreadPts=8, currency='USD')
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


def samples(spreads=(8,), start=T0, count=61, step=5, offset=DARWINEX_OFFSET):
    """count samples every step seconds; the quote time (server clock) moves with each one."""
    return [dict(utc=start + i * step, spread=spreads[i % len(spreads)], quoteTime=int(start + i * step + offset * 60)) for i in range(count)]


ACCOUNT = dict(login='123456', server='Darwinex-Demo', currency='USD', equity=100000.0, leverage=200, demo=True)


def run(members, *, account=None, symbols=None, spread=None, margins=None, equity=None, sets=None, **manifest_changes):
    """build_result over plain data: every member's broker symbol samples `spread` (default 8)."""
    symbols = symbols if symbols is not None else [symbol()]
    data = manifest([m for m, _ in members], **manifest_changes)
    sets = sets or {m['setSha256']: raw for m, raw in members}
    names = [s['name'] for s in symbols]
    series = spread if isinstance(spread, dict) else {name: samples((spread or 8,)) for name in names}
    return bf.build_result(data, sets, account=dict(account or ACCOUNT), symbols=symbols, samples=series,
                           margins=margins if margins is not None else {name: 1000.0 for name in names}, schema=SCHEMA,
                           utc_now=T0 + 300, equity=equity)


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
        # An exact name that is close-only falls back to the single tradable variant.
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD', trade_mode=3), symbol('EURUSD.r', currency_base='EUR', currency_profit='USD')]),
                         ('EURUSD.r', None))
        # A variant whose base/profit currencies are not the pair's halves is another instrument.
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSDm', currency_base='EUR', currency_profit='JPY')])[1][0], bf.SYMBOL_UNAVAILABLE)
        # Upper-case or digit tails are other instruments, never suffixes.
        self.assertFalse(bf.is_variant('US30', 'US3000'))
        self.assertFalse(bf.is_variant('EURUSD', 'EURUSDX'))
        self.assertEqual(bf.map_symbol('EURUSD', [symbol('EURUSD', trade_mode=0)])[1][0], bf.SYMBOL_UNAVAILABLE)

    def test_the_deploy_file_name_carries_the_broker_symbol(self):
        result = run([(member(KESTREL), KESTREL)], symbols=[symbol('EURUSD.raw', currency_base='EUR', currency_profit='USD')])
        self.assertEqual(one(result)['brokerSymbol'], 'EURUSD.raw')
        self.assertEqual(one(result)['deployFileName'], 'GOAT V1.49 EURUSD.raw,M1_EURUSD.M1.kestrel.set')


class SpreadTests(unittest.TestCase):
    def check(self, timeframe, spread, digits_point=None):
        facts = [symbol(**({} if digits_point is None else dict(digits=digits_point[0], point=digits_point[1],
                                                                 trade_tick_size=digits_point[1], trade_tick_value=digits_point[1] * 100000)))]
        raw = kestrel_with(**NEUTRAL) if digits_point else KESTREL
        return one(run([(member(raw, timeframe=timeframe), raw)], symbols=facts, spread=spread))

    def test_m1_and_m5_allow_125_percent_with_the_boundary_inside(self):
        for timeframe in ('M1', 'M5'):
            with self.subTest(timeframe=timeframe):
                self.assertEqual(self.check(timeframe, 10)['status'], 'fit')          # 10 / 8 = 1.25
                self.assertEqual(self.check(timeframe, 10)['spreadRatio'], 1.25)
                self.assertEqual(self.check(timeframe, 11)['code'], bf.SPREAD_TOO_WIDE)

    def test_m15_and_above_allow_150_percent_with_the_boundary_inside(self):
        for timeframe in ('M15', 'H1', 'H4', 'D1'):
            with self.subTest(timeframe=timeframe):
                self.assertEqual(self.check(timeframe, 12)['status'], 'fit')          # 12 / 8 = 1.5
                self.assertEqual(self.check(timeframe, 13)['code'], bf.SPREAD_TOO_WIDE)

    def test_the_median_is_used_never_a_snapshot(self):
        spikes = {'EURUSD': samples((8, 8, 8, 8, 40))}
        row = one(run([(member(KESTREL), KESTREL)], spread=spikes))
        self.assertEqual((row['status'], row['spread']['medianPoints']), ('fit', 8.0))
        wide = {'EURUSD': samples((11, 11, 11, 8))}
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], spread=wide))['code'], bf.SPREAD_TOO_WIDE)

    def test_a_broker_spread_is_normalised_to_the_reference_point(self):
        # A 4-digit broker quoting 1 point = 10 reference points.
        row = self.check('M15', 1, digits_point=(4, 0.0001))
        self.assertEqual((row['status'], row['spread']['referencePoints']), ('fit', 10.0))
        self.assertEqual(self.check('M15', 2, digits_point=(4, 0.0001))['code'], bf.SPREAD_TOO_WIDE)   # 20 / 8 = 2.5

    def test_samples_must_cover_the_window_outside_rollover_and_weekend_and_move(self):
        short = {'EURUSD': samples(count=30)}                               # 145 s of a 300 s window
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], spread=short))['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        # 16:30 New York (EDT) = 20:30 UTC on 2026-10-13: every sample is inside the rollover hour.
        rollover = {'EURUSD': samples(start=datetime(2026, 10, 13, 20, 30, tzinfo=timezone.utc).timestamp())}
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], spread=rollover))['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        frozen = {'EURUSD': [dict(s, quoteTime=1) for s in samples()]}
        row = one(run([(member(KESTREL), KESTREL)], spread=frozen))
        self.assertEqual(row['code'], bf.SPREAD_SAMPLE_UNAVAILABLE)
        self.assertIn('Market Watch', row['message'])

    def test_rollover_and_weekend_boundaries_follow_new_york_time(self):
        def utc(*args):
            return datetime(*args, tzinfo=timezone.utc).timestamp()
        # EDT (UTC-4) on 2026-10-13: 16:29 / 16:30 / 17:29 / 17:30 New York.
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 13, 20, 29)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 13, 20, 30)), 'rollover')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 13, 21, 29)), 'rollover')
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 13, 21, 30)))
        # EST (UTC-5) after 2026-11-01: 16:30 New York is 21:30 UTC.
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 11, 3, 21, 29)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 11, 3, 21, 30)), 'rollover')
        # Friday 2026-10-16 15:59 / 16:00 New York; Sunday 2026-10-18 17:59 / 18:00 New York.
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 16, 19, 59)))
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 16, 20, 0)), 'weekend')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 17, 12, 0)), 'weekend')
        self.assertEqual(bf.quiet_exclusion(utc(2026, 10, 18, 21, 59)), 'weekend')
        self.assertIsNone(bf.quiet_exclusion(utc(2026, 10, 18, 22, 0)))
        start = bf.next_quiet_window(utc(2026, 10, 16, 21, 0), 300)
        self.assertEqual(start, utc(2026, 10, 18, 22, 0))


class ScalingTests(unittest.TestCase):
    def test_scale_1_on_a_reference_identical_account_is_byte_identical(self):
        result = run([(member(KESTREL), KESTREL)])
        row = one(result)
        self.assertEqual((result['scale'], row['status'], row['edits']), (1.0, 'fit', {}))
        self.assertEqual(row['setSha256Deployed'], row['setSha256Reference'])
        self.assertEqual(row['setSha256Reference'], hashlib.sha256(KESTREL).hexdigest())
        self.assertEqual(bf.rewrite_set(KESTREL, row['edits']), KESTREL)
        self.assertEqual(row['scaled'], dict(Risk=500.0, Lots_Max=20.0, Lots_Max_Cum=50.0, Lots_Input=0.05, startLots=None))
        json.dumps(result, allow_nan=False)

    def test_risk_scales_and_the_lot_multipliers_do_not(self):
        # Lots_Max and Lots_Max_Cum multiply the start lot (EA mq5:1372, 1366), which already follows Risk: scaling them
        # too would scale the caps twice. Risk 500.0 at half the equity is 250.0; the multipliers stay 20.0 and 50.0.
        row = one(run([(member(KESTREL, ref=reference(startLots=0.2)), KESTREL)], equity=50000))
        self.assertEqual(row['edits'], dict(Risk='250.0'))
        self.assertEqual((row['scaled']['Risk'], row['scaled']['Lots_Max'], row['scaled']['Lots_Max_Cum']), (250.0, 20.0, 50.0))
        deployed = bf.rewrite_set(KESTREL, row['edits'])
        self.assertEqual(hashlib.sha256(deployed).hexdigest(), row['setSha256Deployed'])
        values = bf.set_values(deployed, SCHEMA)
        self.assertEqual((values['Risk'], values['Lots_Max'], values['Lots_Max_Cum'], values['Lots_Input']), ('250.0', '20.0', '50.0', '0.05'))

    def test_fixed_lots_round_down_to_the_volume_step(self):
        raw = kestrel_with(**FIXED)
        row = one(run([(member(raw), raw)], equity=75000))                    # 0.05 x 0.75 = 0.0375 -> 0.03
        self.assertEqual(row['edits'], dict(Risk='375.0', Lots_Input='0.03'))
        row = one(run([(member(raw), raw)], equity=99999))                    # 0.049999 -> 0.04, never 0.05
        self.assertEqual(row['edits']['Lots_Input'], '0.04')
        self.assertEqual(row['edits']['Risk'], '499.99')
        row = one(run([(member(raw), raw)], equity=250000))                   # scaling up rounds down too
        self.assertEqual(row['edits']['Lots_Input'], '0.12')

    def test_below_min_lot_never_rounds_up(self):
        raw = kestrel_with(**FIXED)
        self.assertEqual(one(run([(member(raw), raw)], equity=19999.99))['code'], bf.BELOW_MIN_LOT)   # 0.0099999 -> 0.00
        row = one(run([(member(raw), raw)], equity=20000))
        self.assertEqual((row['status'], row['edits']['Lots_Input']), ('fit', '0.01'))
        self.assertEqual(one(run([(member(raw), raw)], equity=19999.99))['message'], 'This set needs a larger account.')

    def test_risk_per_sequence_below_min_lot(self):
        # Without the reference start lot, the reference VOLUME_MIN is its only proven lower bound: below scale 1 the
        # member cannot be shown to trade without rounding up, so it is excluded.
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], equity=99000))['code'], bf.BELOW_MIN_LOT)
        # With reference.startLots = 0.1: 0.099 -> 0.09 trades; 0.0099 -> 0.00 does not.
        ref = reference(startLots=0.1)
        self.assertEqual(one(run([(member(KESTREL, ref=ref), KESTREL)], equity=99000))['status'], 'fit')
        self.assertEqual(one(run([(member(KESTREL, ref=ref), KESTREL)], equity=9900))['code'], bf.BELOW_MIN_LOT)
        # Risk under the EA's 10 is refused even with a large start lot (EA mq5:3253).
        self.assertEqual(one(run([(member(KESTREL, ref=reference(startLots=10)), KESTREL)], equity=1999))['code'], bf.BELOW_MIN_LOT)

    def test_a_lot_cap_below_volume_min_is_below_min_lot(self):
        raw = kestrel_with(**dict(FIXED, Lots_Input='0.02', Lots_Max='0.4'))   # cap = 0.4 x 0.02 = 0.008 < 0.01
        self.assertEqual(one(run([(member(raw), raw)]))['code'], bf.BELOW_MIN_LOT)

    def test_fixed_money_limits_are_not_scaled(self):
        raw = kestrel_with(MaxLossLocal='1000.0')
        self.assertEqual(one(run([(member(raw), raw)]))['status'], 'fit')     # scale 1: nothing to scale
        row = one(run([(member(raw, ref=reference(startLots=0.2)), raw)], equity=200000))
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

    def test_the_reference_account_is_offered_its_own_portfolio(self):
        result = run([(member(KESTREL), KESTREL)])
        self.assertEqual((result['minEquity'], result['offered']), (100000.0, True))

    def test_ninety_percent_of_risk_weight(self):
        # Ten RiskperSeq members (risk weights = Risk): nine on EURUSD, one on a symbol this broker lacks.
        rows = []
        for index in range(10):
            raw = kestrel_with(EA_Desc='R%02d' % index)
            canonical = 'GBPUSD' if index == 9 else 'EURUSD'
            rows.append((member(raw, member_id='m%d' % index, canonical=canonical), raw))
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
        # EURUSD bid 1.1 (the exact pair name wins): 200,000 EUR = 220,000 USD -> scale 2.2.
        self.assertEqual((result['scale'], result['conversion']), (2.2, dict(rate=1.1, symbol='EURUSD', side='bid')))
        # Lots follow the reference-currency equity: 0.05 x 2.2 = 0.11. Risk is money in EUR, the same fraction of
        # equity: 500 x 200,000 / 100,000 = 1000.0 (not x2.2, which would over-risk by the exchange rate).
        self.assertEqual(one(result)['edits'], dict(Lots_Input='0.11', Risk='1000.0'))
        # At 100,000 EUR: lots 0.055 -> 0.05 and Risk 500.0, so nothing changes.
        self.assertEqual(one(run([(member(raw), raw)], account=dict(account, equity=100000.0), symbols=[symbol()]))['edits'], {})

    def test_a_jpy_account_uses_the_inverse_pair_at_the_ask(self):
        account = dict(ACCOUNT, currency='JPY', equity=15000000.0)
        # A JPY account's EURUSD tick value is quoted in JPY (1 USD x 150).
        facts = [symbol(trade_tick_value=150.0), symbol('USDJPY', bid=149.9, ask=150.0, point=0.001, digits=3)]
        result = run([(member(KESTREL), KESTREL)], account=account, symbols=facts)
        self.assertEqual(result['conversion']['symbol'], 'USDJPY')
        self.assertAlmostEqual(result['scale'], 1.0)
        # Money inputs keep their fraction of equity exactly: 500 x 15,000,000 / 100,000 = 75,000 JPY.
        self.assertEqual(one(result)['edits'], dict(Risk='75000.0'))
        # The same EURUSD with a USD tick value on a JPY account is quoted differently: refused, never guessed.
        wrong = run([(member(KESTREL), KESTREL)], account=account, symbols=[symbol(), facts[1]])
        self.assertEqual(one(wrong)['code'], bf.CONTRACT_MISMATCH)

    def test_no_conversion_pair_refuses_every_member(self):
        account = dict(ACCOUNT, currency='CHF')
        result = run([(member(KESTREL), KESTREL), (member(KESTREL, member_id='b'), KESTREL)], account=account)
        self.assertEqual({row['code'] for row in result['members']}, {bf.ACCOUNT_CURRENCY_UNSUPPORTED})
        self.assertEqual((result['scale'], result['offered'], result['refusal']['code']), (None, False, bf.ACCOUNT_CURRENCY_UNSUPPORTED))


class BrokerSpecTests(unittest.TestCase):
    def test_non_demo_is_refused(self):
        with self.assertRaises(Refusal) as caught:
            run([(member(KESTREL), KESTREL)], account=dict(ACCOUNT, demo=False))
        self.assertEqual(caught.exception.code, bf.NOT_DEMO_ACCOUNT)

    def test_a_different_contract_size_is_corrected_exactly_for_fixed_lots(self):
        raw = kestrel_with(**FIXED)
        facts = [symbol(trade_contract_size=10000.0, trade_tick_value=0.1)]   # mini lots: same value per unit
        row = one(run([(member(raw), raw)], symbols=facts))
        self.assertEqual(row['edits'], dict(Lots_Input='0.5'))

    def test_a_differently_quoted_instrument_is_a_contract_mismatch(self):
        facts = [symbol(trade_tick_value=0.01)]                                # value per unit 1/100 of the reference
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], symbols=facts))['code'], bf.CONTRACT_MISMATCH)
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

    def test_server_offset_must_match_unless_the_member_is_offset_neutral(self):
        account = dict(ACCOUNT, server='Other-Demo')
        two = {'EURUSD': samples(offset=120)}
        # Kestrel trades session hours and closes on Friday: it depends on the server clock.
        row = one(run([(member(KESTREL), KESTREL)], account=account, spread=two))
        self.assertEqual(row['code'], bf.SERVER_OFFSET_MISMATCH)
        self.assertIn('session hours', row['serverOffset']['dependsOn'])
        neutral = kestrel_with(**NEUTRAL)
        self.assertEqual(one(run([(member(neutral), neutral)], account=account, spread=two))['status'], 'fit')
        # The same offset as Darwinex at that instant (UTC+3 in October) fits.
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], account=account))['status'], 'fit')
        # H4 charts, H4 indicators and stale quotes are never neutral or verifiable.
        self.assertEqual(one(run([(member(neutral, timeframe='H4'), neutral)], account=account, spread=two))['code'], bf.SERVER_OFFSET_MISMATCH)
        h4 = kestrel_with(**dict(NEUTRAL, RSI_TF_='240'))
        self.assertEqual(one(run([(member(h4), h4)], account=account, spread=two))['code'], bf.SERVER_OFFSET_MISMATCH)
        stale = {'EURUSD': [dict(s, quoteTime=s['quoteTime'] - 3600 * 5 - 600) for s in samples()]}
        self.assertEqual(one(run([(member(KESTREL), KESTREL)], account=account, spread=stale))['code'], bf.SERVER_OFFSET_MISMATCH)

    def test_offset_measurement_and_the_reference_model(self):
        self.assertEqual(bf.measured_server_offset_minutes(samples(offset=180)), 180)
        self.assertEqual(bf.reference_server_offset_minutes('Darwinex-Demo', T0), 180)
        self.assertEqual(bf.reference_server_offset_minutes('Darwinex-Demo', datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()), 120)
        self.assertIsNone(bf.reference_server_offset_minutes('Unknown-Server', T0))

    def test_costs_are_reported_not_refused(self):
        row = one(run([(member(KESTREL, ref=reference(swapLong=-5.0, swapShort=0.5)), KESTREL)],
                      symbols=[symbol(swap_long=-20.0, swap_short=-9.0)]))
        self.assertEqual(row['status'], 'fit')
        self.assertEqual(row['costs'], dict(swapLong=-20.0, swapShort=-9.0, referenceSwapLong=-5.0, referenceSwapShort=0.5,
                                            commission=None, commissionSource='not_exposed_by_mt5_sdk'))


class MarginTests(unittest.TestCase):
    def test_member_and_portfolio_margin(self):
        raw = kestrel_with(**dict(FIXED, Allow_Opposite_Seq='true'))
        # 0.05 x Lots_Max_Cum 50 = 2.5 lots, both directions = 5 lots, at 1,000 per lot = 5,000.
        row = one(run([(member(raw), raw)]))
        self.assertEqual(row['margin'], dict(perLot=1000.0, peakLots=5.0, required=5000.0, basis='ea_caps'))
        self.assertEqual(one(run([(member(raw), raw)], margins={'EURUSD': 30000.0}))['code'], bf.MARGIN_INSUFFICIENT)
        pair = [(member(raw), raw), (member(raw, member_id='b'), raw)]
        result = run(pair, margins={'EURUSD': 12000.0})                      # 60,000 each, 120,000 together
        self.assertEqual({r['status'] for r in result['members']}, {'fit'})
        self.assertEqual((result['offered'], result['refusal']['code'], result['margin']['required']), (False, bf.MARGIN_INSUFFICIENT, 120000.0))

    def test_unknown_start_lots_leave_margin_unverified(self):
        result = run([(member(KESTREL), KESTREL)])
        self.assertEqual((one(result)['margin']['basis'], result['margin']['verified'], result['offered']), ('start_lots_unknown', False, True))


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


class DeployRecordTests(unittest.TestCase):
    def test_entries_bytes_and_record(self):
        edits = dict(Risk='250.0')
        deployed = bf.rewrite_set(KESTREL, edits)
        block = dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, members=[dict(index=0, memberId='EURUSD.M1.kestrel',
                     setSha256Reference=hashlib.sha256(KESTREL).hexdigest(), setSha256Deployed=hashlib.sha256(deployed).hexdigest(), edits=edits)])
        entries = bf.deploy_entries(block, [object()])
        self.assertEqual(bf.deployed_bytes(KESTREL, entries[0]), deployed)
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


class FakeMT5:
    """The MetaTrader5 adapter as broker-fit reads it. No trading call exists here, and no symbol_select."""
    ACCOUNT_TRADE_MODE_DEMO = 0
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1

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
        now = self.clock()
        return None if facts is None else SimpleNamespace(**facts, spread=8, time=int(now) + DARWINEX_OFFSET * 60, visible=True)

    def order_calc_margin(self, action, name, volume, price):
        self.calls.append(('margin', action, name)); return 1000.0 * volume


class ReadBrokerTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.c = SimpleNamespace(root=self.folder / 'state', install=dict(terminal_executable=str(self.folder / 'MT5' / 'terminal64.exe'),
                                 terminal_data_root=str(self.folder / 'data'), ea_version='1.49'), schema=SCHEMA)
        self.session = dict(account=dict(login='123456', server='Darwinex-Demo'))
        self.now = [T0]

    def clock(self):
        return self.now[0]

    def sleep(self, seconds):
        self.now[0] += seconds

    def write_portfolio(self):
        data = manifest([member(KESTREL)])
        (self.folder / 'house.json').write_text(json.dumps(data))
        (self.folder / data['members'][0]['setSha256']).write_bytes(KESTREL)
        return self.folder / 'house.json'

    def test_the_cli_reads_samples_and_answers_without_writing(self):
        mt5 = FakeMT5(self.c, clock=self.clock)
        portfolio = self.write_portfolio()
        before = sorted(p.name for p in self.folder.rglob('*'))
        with patch('studio_onboarding.session_state', return_value=(self.session, None)):
            result = bf.broker_fit(self.c, portfolio, mt5=mt5, clock=self.clock, sleep=self.sleep)
        self.assertEqual((result['schema'], result['offered'], one(result)['status']), (bf.SCHEMA, True, 'fit'))
        self.assertEqual(one(result)['spread']['samples'], 61)
        self.assertEqual((mt5.calls[0], mt5.calls[-1]), ('initialize', 'shutdown'))
        self.assertEqual(one(result)['margin']['perLot'], 1000.0)
        after = sorted(p.name for p in self.folder.rglob('*') if 'state' not in p.parts)
        self.assertEqual(after, [name for name in before if name != 'state'] if 'state' in before else before)

    def test_non_demo_is_refused_before_any_sampling(self):
        mt5 = FakeMT5(self.c, trade_mode=2, clock=self.clock)
        with self.assertRaises(Refusal) as caught:
            bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock, sleep=self.sleep)
        self.assertEqual(caught.exception.code, bf.NOT_DEMO_ACCOUNT)
        self.assertNotIn(('margin', 0, 'EURUSD'), mt5.calls)
        self.assertEqual(mt5.calls[-1], 'shutdown')

    def test_rollover_and_weekend_refuse_before_attaching(self):
        mt5 = FakeMT5(self.c, clock=self.clock)
        self.now[0] = datetime(2026, 10, 13, 20, 28, tzinfo=timezone.utc).timestamp()   # the window reaches 16:30 New York
        with self.assertRaises(Refusal) as caught:
            bf.read_broker(self.c, self.session, manifest([member(KESTREL)]), mt5=mt5, clock=self.clock, sleep=self.sleep)
        self.assertEqual(caught.exception.code, bf.SPREAD_SAMPLE_UNAVAILABLE)
        self.assertEqual(caught.exception.fields['nextWindowUtc'], datetime(2026, 10, 13, 21, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(mt5.calls, [], 'MT5 is never initialized inside rollover or the weekend')

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
        self.assertEqual((contract['required'], contract['limits']['spread-window-seconds']), (['portfolio'], [300, 1800]))
        self.assertIn('NOT_DEMO_ACCOUNT', contract['effect'])
        self.assertIn('Never writes', contract['effect'])


if __name__ == '__main__':
    unittest.main()
