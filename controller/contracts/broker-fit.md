# broker-fit contract v1 (controller side)

Shared by the GOAT-EA controller and the goatai app. Rulings: Claude-Mac goatai#1885 6008137980 (2026-10-06), manifest
`goat-house-portfolio-v1` (#1885 6005691928 / 6005730237), reviewer additions goatai#2350 6128283375 (2026-10-12, these
override the original text where they differ). Implementation: `controller/studio_broker_fit.py`; deploy hook:
`controller/studio_demo_deploy.py` (`validate_plan`, `load`); tests: `controller/test_studio_broker_fit.py`,
`controller/test_studio_broker_fit_deploy.py`. Section "Decisions" records every point the contract left open.

## Command (controller, READ-ONLY)

```
goat.exe studio --installation <receipt> broker-fit --portfolio <house manifest .json> [--equity <number>]
    [--sets <folder>] [--spread-window-seconds 300]
```

- Reads the bound DEMO terminal through the MT5 SDK, under the installation's terminal lease (the same
  initialize/terminal/account checks as `broker_proof`): account currency, equity and leverage; `symbols_get()` once;
  `symbol_info()` per mapped symbol every 5 s over the spread window; `order_calc_margin()` for 1.0 lot buy and sell.
- Never writes a file, never selects a symbol into Market Watch, never opens a chart, never trades. Refuses
  `NOT_DEMO_ACCOUNT` on a non-demo account (before any sampling).
- `--equity` overrides the account equity (account currency) for planning; still read-only.
- `--sets`: the folder holding the member SET files, each named `<setSha256>` (the app's house cache) or by `setName`;
  default the manifest's folder. Every file must hash to `setSha256` and have `setBytes` bytes (`PORTFOLIO_INVALID`
  otherwise, naming the members).
- `--spread-window-seconds` 300..1800 (default 300). A window that would touch the rollover hour or the weekend is
  refused up front with `SPREAD_SAMPLE_UNAVAILABLE` and `nextWindowUtc`, before MT5 is attached.
- The terminal lease is held for the whole window (about 5 minutes): a batch driver that wants the terminal meanwhile
  waits or refuses as it does for any other read. While a driver holds it, broker-fit answers `BROKER_READ_DEFERRED`.

Command-level refusals (`ok: false`, `refusal_code`): `NOT_DEMO_ACCOUNT`, `PORTFOLIO_INVALID`, `RISK_SCALING_UNSUPPORTED`
(`riskScaling` other than `equity_linear`), `EA_VERSION_MISMATCH` (manifest `ea.eaVersion` differs from the installed
EA), `SPREAD_SAMPLE_UNAVAILABLE` (rollover or weekend), `BROKER_READ_DEFERRED`.

## Reply `{ ok, result: BrokerFitResult }`

```
BrokerFitResult = {
  schema: 'goat-broker-fit-v1',
  account: { login, server, currency, equity, leverage, demo: true },
  reference: { equity, currency, server },              // referenceAccount.startingBalance / currency / server
  scale: number|null,                                    // equity_linear: account equity in reference currency / reference equity
  scaleMode: 'equity_linear',                            // additive
  conversion: { rate, symbol, side }|null,               // additive: 1 account-currency unit in the reference currency
  minEquity: number|null,                                // account currency; smallest equity where >= 90% of the risk trades
  manifestMinEquity: number|null,                        // additive: the manifest's own floor (reference currency)
  offered: boolean,
  refusal: null|{ code, message },                       // additive: why offered is false
  tradableRiskShare: number,                             // 0..1 at this equity
  riskWeighting: 'risk'|'equal',                         // additive
  margin: { required, equity, verified, level },         // additive: portfolio worst case
  serverOffset: { brokerMinutes, referenceMinutes },     // additive
  members: [{
    memberId, canonicalSymbol, brokerSymbol|null, period,
    status: 'fit'|'excluded',
    code: null|'SYMBOL_UNAVAILABLE'|'SYMBOL_AMBIGUOUS'|'SPREAD_TOO_WIDE'|'SPREAD_SAMPLE_UNAVAILABLE'|'BELOW_MIN_LOT'
          |'CONTRACT_MISMATCH'|'POINT_SIZE_MISMATCH'|'SERVER_OFFSET_MISMATCH'|'MARGIN_INSUFFICIENT'
          |'ACCOUNT_CURRENCY_UNSUPPORTED',
    message: null|string,                                // one plain sentence
    spreadRatio: number|null,                            // broker median spread (reference points) / typicalSpreadPts
    scaled: { Risk, Lots_Max, Lots_Max_Cum, Lots_Input, startLots }|null,   // the values the deployed SET holds
    setSha256Reference, setSha256Deployed|null,
    deployFileName: string|null,                         // additive: setName with the broker symbol (the deploy plan's fileName)
    edits: { input: text }|null,                         // additive: what the deploy changes in the reference SET
    spread: { medianPoints, referencePoints, typicalSpreadPts, limit, samples }|null,      // additive
    pointConversion: { referencePoint, brokerPoint, factor, inputs }|null,                 // additive
    serverOffset: { sameServer, brokerMinutes, referenceMinutes, offsetNeutral, dependsOn }|null,  // additive
    costs: { swapLong, swapShort, referenceSwapLong, referenceSwapShort, commission: null, commissionSource }|null,
    margin: { perLot, peakLots, required, basis }|null   // additive
  }]
}
```

Member checks run in this order and the first failing one is the member's code: currency, symbol, contract, point
size, server clock, spread sample, spread, fixed money limits, equity rules (`BELOW_MIN_LOT`), margin.

Portfolio refusal (first that applies): `ACCOUNT_CURRENCY_UNSUPPORTED`, `PORTFOLIO_BROKER_UNFIT` (less than 90% of the
risk can trade on this broker at any equity), `PORTFOLIO_NEEDS_LARGER_ACCOUNT` (equity < minEquity),
`MARGIN_INSUFFICIENT` (fit members' worst-case margin together exceeds equity), `PORTFOLIO_BROKER_UNFIT` (share < 90%).

## Rules

- **Symbol map:** canonical symbol -> exact name when it is tradable (trade mode FULL) and, for a six-letter pair, its
  base/profit currencies are the pair's halves; else exactly one such variant among `symbols_get()`: canonical plus a
  suffix (`.raw`, `_i`, `#`, `-x`, or 1-4 lower-case letters such as `m`, `pro`, `ecn`) or a prefix (`#`, `.`, `_`, or
  1-4 lower-case letters with an optional `.`/`_`). None -> `SYMBOL_UNAVAILABLE`; more than one -> `SYMBOL_AMBIGUOUS`
  (the message lists them). Upper-case or digit tails (`EURUSDX`, `US3000`) are other instruments.
- **Spread fit:** the MEDIAN of samples taken every 5 s over at least 300 s, outside the rollover hour and the weekend,
  never a snapshot. In reference points (`median x brokerPoint / referencePoint`) it must be <= 1.25 x
  `typicalSpreadPts` for M1/M5 and <= 1.5 x for M15 and above (the boundary itself fits); else `SPREAD_TOO_WIDE`.
  Fewer than 20 valid samples, a span shorter than the window minus 10 s, or a quote that never changed (a symbol
  outside Market Watch) -> `SPREAD_SAMPLE_UNAVAILABLE` for that member ("add it to Market Watch").
  - **Rollover hour:** 16:30-17:30 New York time every day (30 minutes either side of the 17:00 New York FX rollover;
    23:30-00:30 on a NY-close server such as Darwinex).
  - **Weekend:** Friday 16:00 to Sunday 18:00 New York time (an hour either side of the weekly close and open).
  - New York time is UTC-4 from the second Sunday of March 02:00 to the first Sunday of November 02:00, else UTC-5.
- **Scaling (`equity_linear`):** scale = account equity x rate / reference equity. Per EA mode (see "EA semantics"):
  - `Risk` (money, account currency) x account equity / reference equity, rounded DOWN to the cent; every mode.
  - `Lots_Input` x scale x (reference contract size / broker contract size), rounded DOWN to the broker volume step
    (and to VOLUME_MAX); FixedLots and ScaledLots only. RiskperSeq needs no lot edit: the EA solves the start lot from
    Risk on the broker's own tick value.
  - `Lots_Max`, `Lots_Max_Cum`: never scaled (they multiply the start lot).
  - An unchanged value is never rewritten, so scale 1.0 on a reference-identical account is byte-identical.
- **BELOW_MIN_LOT, never round up (no tolerance):** excluded when the scaled `Lots_Input` is below VOLUME_MIN; when
  `Lots_Max x start lot` is below VOLUME_MIN; when Risk is used (RiskperSeq, `Sequence_MLPS_Hard_Close`, Smart Peak,
  Smart Rescue) and the scaled Risk is below the EA's 10 (mq5:3253-3260); and for RiskperSeq when the start lot cannot be
  proven >= VOLUME_MIN: with `reference.startLots` it is `startLots x lot factor` rounded down; without it the only
  proven bound is `reference.volumeMin x lot factor` (the EA never solves below VOLUME_MIN), so below the reference
  equity such a member is excluded. Message: "This set needs a larger account."
- **Contract specs:** value of one price unit per contract unit (`tickValue / tickSize / contractSize`, broker side
  converted to the reference currency) must be within 0.8-1.25 of the reference; outside it the instrument is quoted
  differently -> `CONTRACT_MISMATCH`. A different contract SIZE is corrected exactly through the lot factor. A member
  reference with a null or invalid key a rule needs (`digits, point, tickSize, tickValue, contractSize, volumeMin,
  volumeStep, typicalSpreadPts, currency`) or a reference currency other than `referenceAccount.currency` ->
  `CONTRACT_MISMATCH` ("reference broker details are missing").
- **Digits/point:** positive distance inputs are `value x 10 x Point()` (GetSize, mq5:6709-6794); negative ones are ATR
  multiples and point-neutral. When the broker point differs, `Grid_Size, Grid_Min, Grid_Max, Lock_Profit_Size,
  SL_Pips, TSL_Size` (positive only) are multiplied by `referencePoint / brokerPoint` when that ratio is an exact power
  of ten AND no EA minimum-size clamp (mq5:3318-3323) changes outcome; otherwise `POINT_SIZE_MISMATCH`. `TP_Pips`
  multiplies the lock size and is not converted. The converted inputs are reported in `pointConversion.inputs`.
- **Server time offset:** the broker offset is measured from the freshest quote (`symbol_info.time` minus UTC, rounded
  to 15 minutes, trusted when the quote is at most 120 s old). The reference offset is the reference server's model:
  `Darwinex*` = NY-close (UTC+2, UTC+3 while New York observes DST); unknown servers have no model. Same server name as
  the reference, or equal offsets -> fine. Otherwise `SERVER_OFFSET_MISMATCH` unless the member is offset-neutral and
  both offsets are known and differ by whole hours. **Offset-neutral** = chart M1/M5/M15/M30/H1; no `*_TF_` input on
  TF_H4 (240); `Active_Time_Weekday` = SESS_ALL and `Active_Time_Friday` = SESSION_ALL or SESSION_FRI and the three
  session strings spanning 00:00-24:00 (the EA's earliest start to latest end); `Action_Dayend` = `Action_Friday` =
  Action_Null; `Trade_Friday` = true; `Mode_News` Display or Disabled; `MaxDailyLossLocal` = `MaxDailyProfitLocal` = 0.
  The reasons are reported in `serverOffset.dependsOn`.
- **Costs:** swap long/short per member from the SDK beside the reference `swapLong`/`swapShort` (optional reference
  keys). Commission is `null` with `commissionSource: 'not_exposed_by_mt5_sdk'`. Shown, never refused.
- **Margin:** per member, the SDK's `order_calc_margin` for 1.0 lot (worse of buy at ask and sell at bid, account
  currency, this account's leverage) x the worst-case lots at the EA caps: `start lot x Lots_Max_Cum` (or
  `start lot x Lots_Max x Max_Seq_Trades` when there is no cumulative cap), x2 when `Mode_Trade` = Long_and_Short and
  `Allow_Opposite_Seq` = true. **Both levels:** a member whose own worst case exceeds equity is excluded
  `MARGIN_INSUFFICIENT`; when every fit member's worst case is known and their SUM (all at their worst case at once)
  exceeds equity, the portfolio is refused `MARGIN_INSUFFICIENT`. A RiskperSeq member without `reference.startLots` has
  no known start lot: its margin is `null` (`basis: 'start_lots_unknown'`) and `margin.verified` is false.
- **Currency:** account currency != reference currency -> rate from a quoted pair on the terminal (exact pair name
  preferred), at the side that values the account LOWER (bid when the account currency is the base, 1/ask when it is
  the quote). None -> `ACCOUNT_CURRENCY_UNSUPPORTED` for every member, `scale: null`, `offered: false`.
- **minEquity / offered:** each member's minimum equity is found exactly on the cent grid by bisection over the same
  equity rules. minEquity = the smallest equity where members worth >= 90% of the risk are tradable (members excluded
  for any non-equity reason never count), raised to the manifest's `minEquity` (converted, rounded up to the cent) when
  that is stricter. Risk weights are each member's reference `Risk` when every member is RiskperSeq, else equal.
- **Scaled SET bytes:** written only by the deploy. broker-fit reports `setSha256Deployed` computed in memory. The
  encoding (UTF-16LE or UTF-8), the BOM (or its absence) and every line end are kept byte for byte; only the first field
  of each edited input changes (`value||start||step||stop||N` keeps its ladder). Scale 1.0 on a reference-identical
  account => `setSha256Deployed == setSha256Reference`.
- **Deploy:** see "Deploy hook".

## EA semantics (GOAT V1.49.mq5, read 2026-10-12)

| Input | Meaning in the EA | Scaled by broker-fit |
|---|---|---|
| `Risk` | Money in the account currency in every mode (Inputs:644). RiskperSeq: the solver's target loss per sequence (mq5:617, 1669, 781-827). Every mode: the MLPS amount for `Sequence_MLPS_Hard_Close` (mq5:1146-1169), Smart Peak and Smart Rescue. Minimum 10 when used (mq5:3253-3260). Never a percentage. | Yes, x equity / reference equity, down to the cent |
| `Lots_Input` | FixedLots: the start lot (mq5:3251, 1666). ScaledLots: `Lots_Input x equity_now / equity_at_init` (mq5:3252, 1667), relative to the chart's own start, not to account size. RiskperSeq: unused. | FixedLots/ScaledLots: x scale x contract ratio, down to the volume step |
| `Lots_Max` | Multiplier: per-trade cap = `Lots_Max x StartLots` (mq5:1372, 1559, 1732) | Never |
| `Lots_Max_Cum` | Multiplier: cumulative cap = `StartLots x Lots_Max_Cum` (mq5:1018, 1366, 1553) | Never |
| `MaxLossLocal`, `MaxLossGlobal`, `MaxDailyLossLocal`, `MaxDailyProfitLocal`, `MinLevelEquity`, `MaxLevelEquity` | Fixed money amounts / equity levels (mq5:5595-5630) | Never; a non-zero one off the reference equity excludes the member (`CONTRACT_MISMATCH`) |
| `Grid_Size`, `Grid_Min`, `Grid_Max`, `Lock_Profit_Size`, `SL_Pips`, `TSL_Size` | `value x 10 x Point()` when positive, ATR multiples when negative (mq5:6709-6794) | Only for a point-size difference, exactly |

## Deploy hook (`studio_demo_deploy`)

The `goat-demo-deploy-v1` plan gains one optional key. A plan without it validates, stages and journals exactly as
before (golden test: `test_scale_one_stages_byte_identical_files_golden`).

```
brokerFit: {
  schema: 'goat-broker-fit-deploy-v1',
  scale: number,                                           // the broker-fit result's scale
  members: [{ index, memberId, setSha256Reference, setSha256Deployed, edits }]   // one per plan member, in order
}
```

- With `brokerFit`, each plan member's `contentBase64`/`sha256` are the REFERENCE SET (as the house store serves it),
  its `fileName` is the result's `deployFileName` and its `symbol` the broker symbol. The plan lists fit members only.
- The controller writes the scaled SET itself: `rewrite_set(reference, edits)`; `edits` may only name `Risk`,
  `Lots_Input` and the six point distances, with plain decimal values. The reference must hash to
  `setSha256Reference` and the result to `setSha256Deployed`, else the plan is refused before anything is written.
- The money-safety checks (`check_member_values`), the chart writer and the duplicate check all run on the DEPLOYED
  bytes; the journal, registration and dashboard audit carry the deployed sha256.
- The journal gains `broker_fit: { schema, scale, members: [{ memberId, setSha256Reference, setSha256Deployed, scale }] }`.
- At scale 1.0 with no edits, deployed == reference, so every staged file is byte-identical to today's.

## Decisions (points the contract left open or got wrong)

1. **Lots_Max / Lots_Max_Cum are NOT scaled** (contract said "Risk, Lots_Max and Lots_Max_Cum all scale by the same
   factor"). In the EA both multiply the start lot, which already follows Risk (RiskperSeq) or the scaled `Lots_Input`;
   scaling them too would scale the caps by scale squared. `scaled` still reports them (unchanged).
2. **Money vs lots under a currency difference:** lots scale by `scale` (reference-currency equity), money inputs by
   `account equity / reference equity` (account currency). The contract's single factor would over- or under-risk by
   the exchange rate.
3. **`Lots_Input` scales in FixedLots and ScaledLots** (not named by the contract): ScaledLots is relative to the
   chart's own starting equity, so it does not follow account size by itself.
4. **No tolerance for rounding up** (reviewer ruling 1). RiskperSeq without `reference.startLots` is excluded below
   the reference equity because no smaller start lot can be proven tradable.
5. **Fixed money limits** (`MaxLoss*`, `MaxDaily*`, `Min/MaxLevelEquity`) are not scaled; non-zero off the reference
   equity -> `CONTRACT_MISMATCH` with its own sentence. Balanced35 has them all at 0.
6. **New member codes** `SPREAD_SAMPLE_UNAVAILABLE`, `POINT_SIZE_MISMATCH`, `SERVER_OFFSET_MISMATCH`,
   `MARGIN_INSUFFICIENT` (reviewer); **new portfolio refusal** `PORTFOLIO_BROKER_UNFIT` (< 90% tradable on this broker
   at any equity: "needs a larger account" would be false).
7. **Missing reference keys** (the manifest allows null "where unknown") -> `CONTRACT_MISMATCH`, never a guess.
8. **The manifest's `minEquity`** is a floor: the effective minEquity is the stricter of it and the computed one.
9. **Reference server clock** comes from a server-name model (`Darwinex*` = NY-close); the manifest has no field for it.
10. **Input file:** a manifest `.json` plus verified SET files (`<setSha256>` or `setName`). `setBytes` is the file size
    (the manifest validator's meaning), not base64 content. `.goatportfolio` packages are refused for now.
11. **Additive result keys** (marked above) carry what the app needs to deploy and explain: `deployFileName`, `edits`,
    `refusal`, `spread`, `pointConversion`, `serverOffset`, `costs`, `margin`, `conversion`, `manifestMinEquity`.
