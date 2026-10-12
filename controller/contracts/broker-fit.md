# broker-fit contract v1 (controller side)

Shared by the GOAT-EA controller and the goatai app. Rulings: Claude-Mac goatai#1885 6008137980 (2026-10-06), manifest
`goat-house-portfolio-v1` (#1885 6005691928 / 6005730237), reviewer additions goatai#2350 6128283375 and rulings
goatai#2350 6129252646 (2026-10-12; these override the original text where they differ), and the GOAT-EA#228 review
6130418265 (round 2: see "Round 2" at the end, which overrides anything above it). Implementation:
`controller/studio_broker_fit.py`; deploy hook: `controller/studio_demo_deploy.py` (`validate_plan`, `load`); tests:
`controller/test_studio_broker_fit.py`, `controller/test_studio_broker_fit_deploy.py`. Section "Decisions" records every
point the contract left open.

## Command (controller, READ-ONLY)

```
goat.exe studio --installation <receipt> broker-fit --portfolio <house manifest .json> [--equity <number>] [--sets <folder>]
```

- One short MT5 SDK read (seconds) under the installation's terminal lease, ATTACH-ONLY: when no process of the
  selected `terminal64.exe` (exactly `install.terminal_executable`) is running it refuses `MT5_NOT_RUNNING` ("Start MT5
  and sign in to your demo account, then check again.") and calls nothing (`initialize(path)` would start MT5 and
  `shutdown()` would leave it running). Then the same initialize/terminal/account checks as `broker_proof`: account
  currency, equity and leverage; `symbols_get()` once; per mapped symbol and per conversion pair `symbol_info_tick()`;
  the mapped symbols' last ticks are re-read (every 0.25 s, at most 10 s) until one ARRIVES, which proves the broker's
  GMT offset; `copy_ticks_range(..., COPY_TICKS_INFO)` over the last 6 hours (the spread) and `order_calc_margin()` for
  1.0 lot buy and sell.
- Never writes a file, never selects a symbol into Market Watch, never opens a chart, never trades. Refuses
  `NOT_DEMO_ACCOUNT` on a non-demo account (before any tick is read).
- `--equity` overrides the account equity (account currency) for planning; still read-only.
- `--server-time-utc` (optional, unix seconds): a trusted UTC now; a PC clock more than 120 s off leaves the broker's
  offset unknown (Decision 10).
- `--sets`: the folder holding the member SET files, each named `<setSha256>` (the app's house cache) or by `setName`;
  default the manifest's folder. Every file must hash to `setSha256` and have `setBytes` bytes (`PORTFOLIO_INVALID`
  otherwise, naming the members).
- While a batch driver holds the terminal, broker-fit answers `BROKER_READ_DEFERRED` (nothing read).

Command-level refusals (`ok: false`, `refusal_code`): `NOT_DEMO_ACCOUNT`, `PORTFOLIO_INVALID`, `RISK_SCALING_UNSUPPORTED`
(`riskScaling` other than `equity_linear`), `EA_VERSION_MISMATCH` (manifest `ea.eaVersion` differs from the installed
EA), `BROKER_READ_DEFERRED`, `MT5_NOT_RUNNING`.

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
  margin: { required, equity, limit, verified: true, level },   // additive: portfolio worst case; limit = 50% of equity
  serverOffset: { brokerMinutes, referenceMinutes, referenceSource, memberSources, assumed },   // additive
  referenceIdentical: { applies, used, reason: 'REFERENCE_IDENTICAL_MARGIN'|null, conditions, liveEquity, liveScale,
                        equityTolerance },                // additive
  deployBasis: { schema: 'goat-broker-fit-deploy-v2', scale, equity, referenceEquity, accountCurrency, rate,
                 reviewedAtUtc, manifest,
                 referenceIdentical: { server, currency, leverage, startingBalance, reason }|null }|null,  // additive
  members: [{
    memberId, canonicalSymbol, brokerSymbol|null, period,
    status: 'fit'|'excluded',
    code: null|'SYMBOL_UNAVAILABLE'|'SYMBOL_AMBIGUOUS'|'SPREAD_TOO_WIDE'|'SPREAD_SAMPLE_UNAVAILABLE'|'BELOW_MIN_LOT'
          |'CONTRACT_MISMATCH'|'POINT_SIZE_MISMATCH'|'SERVER_OFFSET_MISMATCH'|'MARGIN_TOO_HIGH'|'MARGIN_UNKNOWN'
          |'MONEY_VALUE_UNREADABLE'|'EA_INIT_REFUSED'|'ACCOUNT_CURRENCY_UNSUPPORTED',
    message: null|string,                                // one plain sentence
    spreadRatio: number|null,                            // broker median spread (reference points) / typicalSpreadPts
    scaled: { Risk, Lots_Max, Lots_Max_Cum, Lots_Input, startLot }|null,    // the values the deployed SET holds
    setSha256Reference, setSha256Deployed|null,
    deployFileName: string|null,                         // additive: setName with the broker symbol (the deploy plan's fileName)
    edits: { input: text }|null,                         // additive: what the deploy changes in the reference SET
    deploy: { memberId, brokerSymbol, deployFileName, setSha256Reference, setSha256Deployed, edits, rules }|null,   // the plan's brokerFit entry
    startLotSource: string|null,                         // additive: reference.startLotSource, passed through
    spread: { medianPoints, referencePoints, typicalSpreadPts, limit, ticks, hours }|null,  // additive
    pointConversion: { referencePoint, brokerPoint, factor, inputs }|null,                 // additive
    serverOffset: { sameServer, brokerMinutes, referenceMinutes, referenceSource, offsetNeutral, dependsOn }|null,  // additive
    costs: { swapLong, swapShort, referenceSwapLong, referenceSwapShort, commission: null, commissionSource }|null,
    margin: { perLot, peakLots, required, basis, limit?, unknownBasis? }|null,   // additive
    marginReason: null|'REFERENCE_IDENTICAL_MARGIN'      // additive: the exemption, never silent
  }]
}
```

Member checks run in this order and the first failing one is the member's code: currency, money values
(`MONEY_VALUE_UNREADABLE`), symbol, contract, point size (`POINT_SIZE_MISMATCH`, `EA_INIT_REFUSED`), server clock,
spread history, spread, fixed money limits, unknown margin (`MARGIN_UNKNOWN`), equity rules (`BELOW_MIN_LOT`), margin
(`MARGIN_TOO_HIGH`).

Portfolio refusal (first that applies): `ACCOUNT_CURRENCY_UNSUPPORTED`, `PORTFOLIO_BROKER_UNFIT` (less than 90% of the
risk can trade on this broker at any equity), `PORTFOLIO_NEEDS_LARGER_ACCOUNT` (equity < minEquity),
`MARGIN_TOO_HIGH` (fit members' worst-case margin together exceeds 50% of equity), `PORTFOLIO_BROKER_UNFIT` (share < 90%).

## Rules

- **Symbol map:** canonical symbol -> exact name when it is tradable (trade mode FULL) and, for a six-letter pair, its
  base/profit currencies are reported and are the pair's halves; else exactly one such variant among `symbols_get()`: canonical plus a
  suffix (`.raw`, `_i`, `#`, `-x`, or 1-4 lower-case letters such as `m`, `pro`, `ecn`) or a prefix (`#`, `.`, `_`, or
  1-4 lower-case letters with an optional `.`/`_`). None -> `SYMBOL_UNAVAILABLE`; more than one -> `SYMBOL_AMBIGUOUS`
  (the message lists them). Upper-case or digit tails (`EURUSDX`, `US3000`) are other instruments.
- **Spread fit (Ops' method, `G:\GOAT-Build-Artifacts\claude-pc-ops\exp-vps\exp03_symbol_specs.py`, which measured the
  reference `typicalSpreadPts`):** the median of `(ask - bid) / point` over the real ticks of the last 6 hours
  (`copy_ticks_range`, `COPY_TICKS_INFO`; dates and tick times on the server clock), skipping ticks without a positive
  bid and ask and ticks in the rollover hours or the weekend, rounded to 0.1 point. In reference points
  (`median x brokerPoint / referencePoint`) it must be <= 1.25 x `typicalSpreadPts` for M1/M5 and <= 1.5 x for M15 and
  above (the boundary itself fits); else `SPREAD_TOO_WIDE`. `SPREAD_SAMPLE_UNAVAILABLE` only when fewer than 100 ticks
  remain (including a symbol with no history, e.g. not in Market Watch, and an unreadable server clock).
  - **Rollover hours:** 16:00-18:00 New York time every day. That is exactly the server 23:00-01:00 Ops skips on the
    NY-close reference server, written in New York time so it holds on any broker clock.
  - **Weekend:** Friday 16:00 to Sunday 18:00 New York time (contains the NY-close server's Saturday and Sunday).
  - Ticks are placed in UTC with the broker's measured offset. New York time is UTC-4 from the second Sunday of March
    02:00 to the first Sunday of November 02:00, else UTC-5.
- **Scaling (`equity_linear`):** scale = account equity x rate / reference equity. Per EA mode (see "EA semantics"):
  - `Risk` (money, account currency) x account equity / reference equity, rounded DOWN to the cent; every mode.
  - `Lots_Input` x scale x (reference contract size / broker contract size), rounded DOWN to the broker volume step
    (and to VOLUME_MAX), also at factor 1 (round 2, item 1); FixedLots and ScaledLots only.
  - RiskperSeq needs no lot edit (the EA solves the start lot from Risk). Its start lot for the checks is the EA's
    own pick (round 2, item 6) around the ideal `reference.startLot x lot factor x (deployed Risk / exactly scaled
    Risk)`: it follows the Risk actually written.
  - `Lots_Max`, `Lots_Max_Cum`: never scaled (they multiply the start lot).
  - An unchanged value is never rewritten, so scale 1.0 on a reference-identical account is byte-identical.
- **BELOW_MIN_LOT, never round up (no tolerance):** excluded when the scaled `Lots_Input` is below VOLUME_MIN; when the
  RiskperSeq ideal start lot (from `reference.startLot`) is below VOLUME_MIN; when `Lots_Max x start lot` is below
  VOLUME_MIN; and when Risk is used (RiskperSeq, `Sequence_MLPS_Hard_Close`, Smart Peak, Smart Rescue) and the scaled
  Risk is below the EA's 10 (mq5:3253-3260). Message: "This set needs a larger account."
- **reference.startLot / startLotSource (optional):** the publisher's reference start lot (the median opening lot of the
  first sequences in the reference backtest trace) and a sentence saying where it came from (passed through as
  `startLotSource`). With it a RiskperSeq member can be proven tradable below the reference equity. Without it the start
  lot, so the margin, is unknown: `MARGIN_UNKNOWN` (below).
- **Contract specs:** value of one price unit per contract unit (`tickValue / tickSize / contractSize`, broker side
  converted to the reference currency) must be within 0.8-1.25 of the reference; outside it the instrument is quoted
  differently -> `CONTRACT_MISMATCH`. A different contract SIZE is corrected exactly through the lot factor. A member
  reference with a null or invalid key a rule needs (`digits, point, tickSize, tickValue, contractSize, volumeMin,
  volumeStep, typicalSpreadPts, currency`) or a reference currency other than `referenceAccount.currency` ->
  `CONTRACT_MISMATCH` ("reference broker details are missing").
- **Digits/point:** positive distance inputs are `value x 10 x Point()` (GetSize, mq5:6709-6794); negative ones are ATR
  multiples and point-neutral. When the broker point differs, `Grid_Size, Grid_Min, Grid_Max, Lock_Profit_Size,
  SL_Pips, TSL_Size` (positive only) are multiplied by `referencePoint / brokerPoint` when that ratio is an exact power
  of ten AND no EA minimum-size clamp (mq5:3318-3323) changes outcome; otherwise `POINT_SIZE_MISMATCH`; a Grid_Size
  the EA refuses at init (mq5:3317) is `EA_INIT_REFUSED`. `TP_Pips`
  multiplies the lock size and is not converted. The converted inputs are reported in `pointConversion.inputs`.
- **Server GMT offset:** the broker offset is measured from a mapped symbol's tick seen ARRIVING during the read (tick
  time on the server clock minus UTC now, rounded to 15 minutes; round 2, item 8). The reference offset is,
  in order: the member's `reference.serverGmtOffset`, the manifest's `referenceAccount.serverGmtOffset`, and only when
  both are absent the server-name assumption (`Darwinex*` = `ny-close`), reported as `referenceSource:
  'server_name_assumption'` (and `serverOffset.assumed: true`). A `serverGmtOffset` is a number of hours (a fixed offset,
  quarter hours allowed) or `'ny-close'` (UTC+2, UTC+3 while New York observes DST). A field that is present but
  unreadable gives no reference offset and is never replaced by the assumption. Same server name as the reference, or
  equal offsets -> fine. Otherwise `SERVER_OFFSET_MISMATCH` unless the member is offset-neutral and both offsets are
  known and differ by whole hours. **Offset-neutral** = chart M1/M5/M15/M30/H1; no `*_TF_` input on TF_H4 (240);
  `Active_Time_Weekday` = SESS_ALL and `Active_Time_Friday` = SESSION_ALL or SESSION_FRI and the three session strings
  spanning 00:00-24:00 (the EA's earliest start to latest end); `Action_Dayend` = `Action_Friday` = Action_Null;
  `Trade_Friday` = true; `Mode_News` Display or Disabled; `MaxDailyLossLocal` = `MaxDailyProfitLocal` = 0. The reasons
  are reported in `serverOffset.dependsOn`.
- **Costs:** swap long/short per member from the SDK beside the reference `swapLong`/`swapShort` (optional reference
  keys). Commission is `null` with `commissionSource: 'not_exposed_by_mt5_sdk'`. Shown, never refused.
- **Margin:** per member, the SDK's `order_calc_margin` for 1.0 lot (worse of buy at ask and sell at bid, account
  currency, this account's leverage) x the worst-case lots at the EA caps: `start lot x Lots_Max_Cum` (or
  `start lot x Lots_Max x Max_Seq_Trades` when there is no cumulative cap), x2 when `Mode_Trade` = Long_and_Short and
  `Allow_Opposite_Seq` = true.
  - **Unknown = refused (fail closed), member level:** no margin per lot from the SDK (`margin_per_lot_unavailable`),
    no EA lot cap (`no_lot_cap`) or a RiskperSeq member without `reference.startLot` (`start_lot_unknown`) ->
    `MARGIN_UNKNOWN` ("GOAT cannot work out the most margin this set could need, so it is not offered."), at any equity.
  - **Reference-identical margin exemption** (goatai#2350 6130033743: a follower of the reference never regresses).
    A member whose margin is unknown passes the margin check, with the explicit reason `REFERENCE_IDENTICAL_MARGIN`
    (`marginReason`, `margin.basis`, the unknown basis kept in `margin.unknownBasis`; never silently), only when ALL of
    these hold:
    - same server as `referenceAccount.server`;
    - same account currency;
    - same leverage as `referenceAccount.leverage`;
    - the account's own (first-apply) equity in the one-sided band `startingBalance <= live <= startingBalance x
      1.05`, judged on the live equity even when `--equity` pins the plan (round 2, item 2);
    - scale exactly 1.0;
    - every member's deployed bytes unchanged (`setSha256Deployed == setSha256Reference`), portfolio-wide: one changed
      member, e.g. by a point conversion, revokes the exemption for all.

    Then the reference account's evidenced margin stands in. The result reports `referenceIdentical: { applies, used,
    reason, conditions{sameServer, sameCurrency, sameLeverage, equityWithinTolerance, scaleOne, bytesUnchanged},
    liveEquity, liveScale, equityTolerance }`, `margin.exemption`, and `deployBasis.referenceIdentical` (`{ server, currency,
    leverage, startingBalance, reason }`) for the deploy. An exempt member's minimum equity is the reference equity
    itself. Anything else still refuses `MARGIN_UNKNOWN`.
  - A member whose own worst case exceeds 50% of equity -> `MARGIN_TOO_HIGH`; the fit members' worst cases together
    exceeding 50% of equity -> portfolio refusal `MARGIN_TOO_HIGH` (round 2, item 9).
- **Currency:** account currency != reference currency -> rate from a quoted pair on the terminal (exact pair name
  preferred), at the side that values the account LOWER (bid when the account currency is the base, 1/ask when it is
  the quote), whose last tick is at most 120 s old (round 2, item 3). None -> `ACCOUNT_CURRENCY_UNSUPPORTED` for every
  member, `scale: null`, `offered: false`.
- **minEquity / offered:** each member's minimum equity is found exactly on the cent grid by bisection over the same
  equity rules. minEquity = the smallest equity where members worth >= 90% of the risk are tradable (members excluded
  for any non-equity reason, `MARGIN_UNKNOWN` included, never count), raised to the manifest's `minEquity` (converted,
  rounded up to the cent) when that is stricter. Risk weights are each member's reference `Risk` when every member is
  RiskperSeq, else equal.
- **Scaled SET bytes:** written only by the deploy. broker-fit reports `setSha256Deployed` computed in memory. The
  encoding (UTF-16LE or UTF-8), the BOM (or its absence) and every line end are kept byte for byte; only the first field
  of each edited input changes (`value||start||step||stop||N` keeps its ladder). Scale 1.0 on a reference-identical
  account => `setSha256Deployed == setSha256Reference`.

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
brokerFit: {                                   // = the broker-fit result's deployBasis, plus members
  schema: 'goat-broker-fit-deploy-v2',
  scale: number, equity: '50000.0', referenceEquity: '100000', accountCurrency: 'USD', rate: '1',  // exact decimal strings
  reviewedAtUtc: int,                          // the review's clock (unix seconds); plans expire after 15 minutes
  manifest: goat-house-portfolio-v1,           // the manifest broker-fit reviewed (the deploy re-derives from it)
  referenceIdentical: null|{ server, currency, leverage, startingBalance, reason: 'REFERENCE_IDENTICAL_MARGIN' },
  members: [{ index, memberId, brokerSymbol, deployFileName,                      // = each fit member's `deploy`, with
              setSha256Reference, setSha256Deployed, edits,                       //   its index in the plan
              rules: { volumeMin, volumeStep, volumeMax|null, contractRatio, referenceVolumeMin, referenceVolumeStep,
                       referenceVolumeMax|null, startLot|null } }],
  excludedSets: [{ memberId, contentBase64 }]  // round 3 item D: the reference SET of every manifest member the plan
}                                              //   leaves out (hash-bound to the manifest); added by the app
```

The inputs at deploy are `manifest`, the reference SET bytes (the plan members' and `excludedSets`, each hash-bound to
the manifest) and the planning `equity`. Every other value is a CLAIM the deploy compares with its own re-derivation
(round 2, review item 7). **The manifest itself is NOT verified yet** (re-review 6132018108 item A, open: the controller
runtime has no ed25519 library): a plan carrying a forged manifest (another `startingBalance`, `contractSize`,
`tickValue`, `startLot`) is re-derived from that forged manifest. Until A lands, the plan's manifest is trusted.

- With `brokerFit`, each plan member's `contentBase64`/`sha256` are the REFERENCE SET (as the house store serves it),
  its `fileName` is the result's `deployFileName` and its `symbol` the broker symbol. The plan lists fit members only.
- The controller writes the scaled SET itself: `rewrite_set(reference, edits)`; `edits` may only name `Risk`,
  `Lots_Input` and the six point distances, with plain decimal values. The reference must hash to
  `setSha256Reference` and the result to `setSha256Deployed`, else the plan is refused before anything is written.
- The money-safety checks (`check_member_values`), the chart writer and the duplicate check all run on the DEPLOYED
  bytes; the journal, registration and dashboard audit carry the deployed sha256.
- `deploy_entries` (validate_plan) checks the shape and what the plan must agree on itself: every entry names a
  distinct manifest member, `setSha256Reference` is that member's `setSha256`, and `brokerSymbol` / `deployFileName`
  are the plan member's `symbol` / `fileName` and the manifest `setName` with that symbol.
- **Deploy-time re-derivation (`FIT_STALE`, `stale_members`):** before anything is staged, deploy-load runs
  `broker_proof`, then one attach-only `read_broker` of the plan's members (live account, symbol facts, conversion
  price, proven clock, spread history, margin per lot) and runs `build_result` on the plan's manifest twice: at the
  planning `equity` and at the LIVE equity. Stale rows (`{memberId, input, reviewed, live}`):
  - `reviewedAtUtc`: the plan is more than 15 minutes old (or from the future by more than 120 s);
  - `account`: the account currency changed or no equity was read;
  - `rate`: no conversion price at most 120 s old;
  - `referenceEquity`, `scale` (one currency only), `referenceIdentical`: a block claim differs from the re-derivation;
  - at the planning equity on the live broker, a member that is not fit (its code), or any claim that differs:
    `brokerSymbol`, `deployFileName`, `setSha256Reference`, `rules`, each edited input, `setSha256Deployed`;
  - at the live equity, a member that is no longer fit (its code: money limits, minimum lot, margin <= 50%, ...), or a
    deployed `Risk` / `Lots_Input` ABOVE the live value (rounding up) or more than one cent / volume step BELOW it;
  - the portfolio no longer offered at the live equity (its refusal code).
  Any row refuses the whole deploy with `FIT_STALE`: "The account changed since the check; run the fit again.
  Nothing was written or launched." (fields `stale`, `liveEquity`, `liveCurrency`). The journal says
  `refused_before_stage`.
- **Reference-identical plans** (`brokerFit.referenceIdentical` not null) keep the exemption only while every
  condition holds on the live account (`referenceIdentical.<condition>` rows): same server, currency and leverage,
  live equity in the ONE-SIDED band `startingBalance <= live <= startingBalance x 1.05`, the re-derived scale of the
  deployed bytes exactly 1.0, every member's re-derived bytes the reference's. Exempt members deploy the reference
  bytes inside the band by design; their fixed money limits are judged on the live equity. Every other member gets the
  live-equity rules and the per-value check one-sided (reviewed <= live), and the portfolio must be offered at the
  planning equity.
- The journal gains `broker_fit: { schema, scale, deployIdentity, members: [{ memberId, setSha256Reference,
  setSha256Deployed, scale }] }`. `deployIdentity` is the app's house deploy identity (goatai#2500
  `houseDeployIdentity`): sha256 hex of the UTF-8 pre-image `goat-house-deploy-identity-v1|scale=<S>|<setSha256Deployed
  sorted ascending, duplicates kept, comma-joined>`, `S = format(scale, '.10f').rstrip('0').rstrip('.')`, no trailing
  newline. Shared vectors: `controller/contracts/deploy-identity/deploy-identity-cases.json`, vendored byte-identical
  from goatai `docs/fixtures/deploy-identity-cases.json` (sha256 `0ac65c40...301d6`); change it there first.
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
4. **No tolerance for rounding up** (reviewer ruling 1). The FIT_STALE tolerance is one-sided for the same reason: a
   reviewed value above the live one is refused at once; only a reviewed value up to one step (cent) below is accepted.
5. **RiskperSeq without `reference.startLot` is `MARGIN_UNKNOWN`** (rulings 1 and 2 together): its start lot is
   unknown, so its worst-case margin is unknown, and unknown margin fails closed, except under the reference-identical
   margin exemption (ruling goatai#2350 6130033743), so a follower of the reference account never regresses. Balanced35
   (all RiskperSeq) is therefore offered on a reference-identical account today and nowhere else until its publisher v2
   adds `startLot`. **Balanced35 has backtest traces** (`backtestTraceSha256` in its manifest), so the publisher can
   derive `startLot` from them (median opening lot of the first sequences). That is the publisher's work, not the
   controller's.
6. **Fixed money limits** (`MaxLoss*`, `MaxDaily*`, `Min/MaxLevelEquity`) are not scaled; non-zero off the reference
   equity -> `CONTRACT_MISMATCH` with its own sentence. Balanced35 has them all at 0.
7. **New codes** the app must mirror: member `SPREAD_SAMPLE_UNAVAILABLE`, `POINT_SIZE_MISMATCH`,
   `SERVER_OFFSET_MISMATCH`, `MARGIN_TOO_HIGH` (was `MARGIN_INSUFFICIENT`), `MARGIN_UNKNOWN`; portfolio `PORTFOLIO_BROKER_UNFIT` (< 90%
   tradable on this broker at any equity: "needs a larger account" would be false); deploy `FIT_STALE`.
8. **Missing reference keys** (the manifest allows null "where unknown") -> `CONTRACT_MISMATCH`, never a guess.
9. **The manifest's `minEquity`** is a floor: the effective minEquity is the stricter of it and the computed one.
10. **Offset measurement limit (updated round 3):** the offset is measured only from a tick seen arriving during the
    read (round 2 item 8), so an old last tick no longer reads as an offset. The residual risk is a skewed clock on this
    PC: the offset is the tick time minus the PC's UTC now. The app passes its own trusted server time
    (`--server-time-utc`, unix seconds, from the serveApi HTTP `Date`); when it differs from the PC clock by more than
    120 s no tick counts as arrived and the offset is unknown (clock-dependent members refuse). Without it, the PC clock
    is trusted as before.
11. **Input file:** a manifest `.json` plus verified SET files (`<setSha256>` or `setName`). `setBytes` is the file size
    (the manifest validator's meaning), not base64 content. `.goatportfolio` packages are refused for now.
12. **Additive result keys** (marked above) carry what the app needs to deploy and explain.

## Round 2 (GOAT-EA#228 review 6130418265, 2026-10-12)

These override the rules above where they differ.

1. **`Lots_Input` is always on the broker's step grid** (FixedLots/ScaledLots), also at lot factor 1: floored to
   VOLUME_STEP and capped at VOLUME_MAX. The EA's `NormalizedLots` (mq5:445-459) rounds an off-step value to the
   NEAREST step (0.25 on a 0.1 step opens 0.30), so GOAT writes the floor (0.2).
2. **Reference-identical band is one-sided:** `startingBalance <= live equity <= startingBalance x 1.05`
   (`equityWithinTolerance`); `liveScale` is reported. Below the reference the reference bytes would over-risk.
3. **Fresh rate, plan TTL:** the conversion pair's last tick must be at most 120 s old (judged with the proven server
   clock); otherwise there is no rate (`ACCOUNT_CURRENCY_UNSUPPORTED` at review, `rate` stale row at deploy). The
   deploy reads the rate again and re-derives every lot from it. A plan older than 15 minutes is `FIT_STALE`
   (`reviewedAtUtc`).
4. **Fixed money limits at deploy:** judged again on the LIVE equity (non-zero only at exactly the reference equity).
5. **`MONEY_VALUE_UNREADABLE`:** `Risk` or a fixed money limit (`MaxLossLocal`, `MaxLossGlobal`, `MaxDailyLossLocal`,
   `MaxDailyProfitLocal`, `MinLevelEquity`, `MaxLevelEquity`) that is missing or not a plain decimal (`9.5e4`, `1,000`,
   empty) excludes the member: "GOAT cannot read this set's {name} value, so it cannot check its money limits." It is
   never read as 0 ("no limit"). An unreadable `*_TF_` input makes the member not offset-neutral (it could be H4); an
   unreadable `Mode_Trade` / `Allow_Opposite_Seq` counts both directions in the margin.
6. **RiskperSeq start lot = the EA's own pick:** `ea_solve_start_lots` ports `SolveStartLotsByRisk` (mq5:781-827) line
   for line in IEEE doubles (bisection over step indices with both neighbours, strictly-closer wins, `kmax =
   floor((vmax - vmin) / vstep + 1e-9)`, 40 rounds) with `NormalizedLots` (mq5:445-459, MathRound = half away from
   zero). `EvalLossForStart` (mq5:829-838) is modelled as linear in the start lot, anchored at `reference.startLot`:
   loss per lot = reference Risk x money factor / (startLot x lot factor). The pick sizes the margin and the
   `Lots_Max x start lot` minimum; `BELOW_MIN_LOT` when the ideal start lot (deployed Risk / loss per lot) is under
   VOLUME_MIN (the EA would be forced up to VOLUME_MIN). `scaled.startLot` is the pick.
7. **The deploy trusts no plan value except the manifest** (Deploy hook above): block v2 carries `manifest`,
   `equity`, `reviewedAtUtc` and per member `brokerSymbol` / `deployFileName`; everything else is re-derived and
   compared. The manifest's signature is not verified yet (round 3 item A, open).
8. **Server clock from a tick seen arriving:** one tick time cannot prove its own age (3,600 s old on UTC+4 reads
   exactly UTC+3), so the offset is measured only from a mapped symbol's tick that arrives while `read_broker`
   re-reads them (at most 10 s, so its age is at most that). No arrival (closed market) = offset unknown: clock-
   dependent members refuse (`SERVER_OFFSET_MISMATCH`, `SPREAD_SAMPLE_UNAVAILABLE`), and with another account currency
   there is no rate.
9. **`MARGIN_TOO_HIGH`** replaces `MARGIN_INSUFFICIENT`: a member's worst case, and the fit members' together, may use
   at most 50% of the equity (margin level >= 200%); the boundary fits. Member: "This set could use more than half of
   this account's equity as margin." Portfolio: "Together these sets could use more than half of this account's equity
   as margin." `margin.limit` reports the 50%.
10. **A six-letter pair must report its base and profit currencies**; a symbol without them is not that pair.
11. **`EA_INIT_REFUSED`:** a member whose (converted) `Grid_Size` is inside (-0.5, 0.5) is excluded (the EA stops in
    OnInit, mq5:3317): "On this broker this set's Grid_Size would be 0.4, which the GOAT EA refuses to start with."
12. **Attach-only `MT5_NOT_RUNNING`** (Command above) for broker-fit and the deploy re-check read.
13. **Deploy identity** (Deploy hook above): the journal's `broker_fit.deployIdentity`, shared with the app.

New codes the app must mirror: member `MARGIN_TOO_HIGH` (replaces `MARGIN_INSUFFICIENT`), `MONEY_VALUE_UNREADABLE`,
`EA_INIT_REFUSED`; portfolio `MARGIN_TOO_HIGH`; command `MT5_NOT_RUNNING`; deploy block schema
`goat-broker-fit-deploy-v2` (a v1 block is refused as invalid).

## Round 3 (goatai#2350 6131884216 and re-review 6132018108, 2026-10-12)

Overrides anything above where they differ.

B. **The EA's own start lot and planned loss (EvalLossForStart, mq5:829-838), ported.** The lot ladder is in the SET:
   `BuildRawLots` (mq5:840-1004, all seven modes including the Peak / PeakSmart Hermite curve), `ScaleRawLots`
   (mq5:1006-1021), each level's `NormalizedLots` (mq5:1023: the nearest step, 0 below VOLUME_MIN) and
   `BuildCumulativeLots` (mq5:1025-1036). The distances come from `BuildDistances` (mq5:1603-1614) with
   `GetSize(GRID_VALID)` (mq5:6754-6767) after the init clamps (mq5:2986-2987, 3318-3319); `FindCumLoss`
   (mq5:1616-1634) is the max prefix of `distance x standing`. The ATR (or the 10 x Point unit) and the value per
   point per lot cancel in `loss(L) = reference Risk x G(L) / G(reference.startLot) / (contract ratio x rate)`, so no
   market data is needed, as long as `Grid_Size`, `Grid_Min_` and an enabled `Grid_Max_` are the same kind (all ATR or
   all points). The start lot is `SolveStartLotsByRisk` on this loss; `scaled.plannedLoss` (additive) reports its
   planned loss. `BELOW_MIN_LOT` when VOLUME_MIN itself plans to lose more than the deployed Risk (the EA would be
   forced over it). Kestrel: at 14,642 (Risk 73.21) the EA picks 0.02 (planned 105.66), not 0.01; the minimum equity
   is 8,120. Not computable (mixed grid kinds) -> `MARGIN_UNKNOWN` basis `loss_unknown`; an unreadable ladder input
   -> basis `lot_ladder_unknown` (replaces `no_lot_cap`).

B2. **Margin from the EA's ladder** (every mode, FixedLots and ScaledLots too): the most lots one sequence stands in,
   `ea_peak_standing`: the planned `LotsCum` peak, and for CumPartial also its run-time adds, which compound the ACTUAL
   standing (`CalcNextLotsCumPartial`, mq5:1539-1563, ported without retrace closes, which only lower what follows),
   x2 for both directions. FixedLots 0.01 on a CumPartial 1.6 ladder peaks at 0.26 lots, not 0.212 (+22.6%).
   Deploy rule facts gain `referenceVolumeStep` and `referenceVolumeMax` (compared at deploy like the others).

C. **The attach-only race is closed.** `read_broker` records the selected terminal's identity (pid and creation time
   of the exact `terminal_executable`) before `initialize`, and re-scans after it (whether it succeeded or not). Any
   other identity means `initialize` started MT5: `shutdown()`, nothing is read, refusal `MT5_STARTED_BY_CHECK` "GOAT
   started MT5 by accident; close it and check again." (fields `pidBefore`, `pidAfter`).

D. **The plan deploys exactly the review's fit set.** The block carries `excludedSets` (the reference SET of every
   manifest member the plan leaves out); with the plan members they must name every manifest member exactly once,
   each hash-bound to its manifest entry (`deploy_entries` refuses otherwise). The deploy re-derives the WHOLE manifest
   and adds a stale row `members` (reviewed = the plan's memberIds, live = the re-derived fit set) when they differ: a
   1-of-35 plan no longer passes the 90% rule at 100%, and a member the review excluded can never be added.

A. **Open: manifest signature verification** (`MANIFEST_UNVERIFIED`). The controller's runtime (the suite's pinned
   wheels: MetaTrader5 and numpy only, `controller/ci-requirements.txt`, goatai `desktop/tools/suiteRuntimeDependencies.cjs`)
   has no ed25519 implementation, and GOAT does not hand-roll crypto, so the manifest is not verified by the
   controller yet (see the Deploy hook note).

## Round 4 (goatai#2350 6132804177, 2026-10-12)

R2. **Risk is searched downwards (accepted rule).** For a RiskperSeq member with a computable planned loss, the
   deployed Risk' is the LARGEST value <= the equity-linear Risk, on the cent grid (Risk is floored to the cent) and
   >= the EA's 10 (mq5:3253-3260), at which the EA's own pick (`SolveStartLotsByRisk` on the ported loss) plans a loss
   <= the equity-linear Risk. The pick only steps up as Risk' grows, so a bisection over whole cents finds it. None at
   10 -> `BELOW_MIN_LOT` ("This set needs a larger account."). `scaled.Risk` is Risk', `scaled.riskSearched` the
   equity-linear Risk the search started from, `scaled.plannedLoss` the planned loss at the deployed pick; a lowered
   Risk' is written as the `Risk` edit, and the deploy re-check re-derives the same Risk'. Kestrel at 14,642 deploys
   Risk 73.12 (0.01 lots, planned 40.59 <= 73.21; at 73.13 the EA would pick 0.02 and plan 105.66).

R3. **The reviewer's four worst-case ladders are tests** (`test_the_reviewers_worst_case_ladders`): with Grid_Factor 1,
   Grid_Min 0 (clamped to -0.5 ATR, never binding) and Grid_Max 0 (disabled) the ported `GetSize(GRID_VALID)` is the
   reviewer's `Grid_Exponent^(i-1)`, and the port gives the reviewer's picks and losses before R2 (CumPartial 0.02 /
   116.60 against 74.68; Last 0.02 / 96.73 against 71.95; Cum 0.02 / 105.26 against 76.64; Start 0.03 / 155.41 against
   125.00). After R2 each deploys a Risk' whose planned loss is within the equity-linear Risk: 74.66 (0.01, 32.74),
   71.92 (0.01, 47.11), 76.62 (0.01, 47.99), 124.99 (0.02, 94.59).