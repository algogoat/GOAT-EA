# Spec draft: breakout entries for Engine_Single (N-bar / prior day, session opening range)

Status: DRAFT for review (Claude-Mac). No code is written, and nothing is built, run or pushed until it is approved.
Source read: GOAT-EA B53, the final build `V1.49-BETA17-53` (`candidate-builds/beta17-B53/identity.json`, EX5 sha256
`4733511303cf216f8ec513556abc89f492176063001dd77c8405c79a995cc068`), merge `216e1622` (GOAT-EA#296). I read it in the
checkout `C:\GOAT-Evidence\ea-builds-20261107\src\b51-live-trial` at `5cfb789`, which has the same tree
(`git diff --quiet 5cfb789 216e162` exits 0). Short names used below: `main` = `GOAT V1.49.mq5`,
`inputs` = `GOAT_Inputs_Definitions.mqh`, `clock` = `GOAT_NYClock.mqh`, `design` = `docs/b50/B50_ALPHA_DESIGN.md`.
Line numbers are at that commit. The build's working name is B54 (Q1).

## 1 Purpose and non-goals

Two new entry families for `Engine_Single`, the only engine they run on: **A**, an N-bar or prior-day high/low
breakout, and **B**, a session opening-range breakout (ORB). Each adds one term to the combined entry signal. With its
mode at `Disabled` the term always reads true, so every existing SET trades byte-identically to B53.

Non-goals: grid or sequence variants (OnInit refuses them); new oscillators (Stochastic, CCI, Williams); carry;
patterns; new exit or stop logic; any change to an existing input, enum value or default.

## 2 Existing mechanics relied on

- **Combined signal.** `SignalEntryTrigger` ANDs six terms for a buy (main:8699-8705) and six for a sell
  (main:8743-8749); a disabled mode's term reads true. The Single branch opens through `GoatSingleOpen` at once, with
  no virtual leg, so `Delay_Trade` is never read (main:8718, 8726, 8761, 8769; design:14).
- **One single per episode.** `g_GoatSingleArmed[signal]` is cleared on an open and re-armed when that signal's combined
  condition reads false (main:8740, 8783; inputs:859-862; design:30; ruling 5, design:161).
- **Gates before an open.** News and bias (main:8708, 8752); `Reverse_Seq`, `Mode_Trade`, `DashboardEntryAllowed` and
  `Allow_Opposite_Seq` (main:8712-8728); `Single_Flat_Only` (main:8717, 8973-8977); `Random_Direction` takes the
  episode's place (main:8707, 8711).
- **Cadence.** `CheckSignalNow` on `Signal_Sample_Period` (inputs:654, default M1; inputs:1536-1547), `Shift_Sig=1`
  (main:8237). `SignalEntryTrigger` runs only while `Active`, with the start flags set and `!g_GoatEntryBlocked`
  (main:8247, 8260). Each indicator is refreshed on a new bar of its own TF via `INTERVAL::CheckTF` (inputs:430-435,
  e.g. main:8466-8467). `Engine_Single` skips the `FastSpeed_Flag` early return (main:8457-8458).
- **Closed bars only.** Every term reads closed bars, so the entry moment does not depend on the tick model
  (design:249-258).
- **Opposite exit.** `GoatSignalAll` is a verbatim copy of the six terms; `scripts/test_b50_exits.cjs` asserts the text
  matches (main:10203-10222). The exit is at main:10227-10252.
- **Sizes.** `Size_SL = Single_SL_ATR x ATR`, where ATR is the closed bar (shift 1) of `ATR_MA_handle`, read into a local
  buffer; the TP by R, else by ATR; stops-level refusals (main:8819-8839). Single mode creates ATR handles whatever the
  grid mode (main:5070-5082). The ATR inputs are at inputs:681-683.
- **Exits on a single.** Break-even and trailing (`GoatSingleModify`, main:9117-9123, design 8.2); the partial close
  (main:8176, design 8.3); the time stop, counted from `POSITION_TIME` (main:10253-10307); MLPS (main:8279-8280); the
  broker SL/TP.
- **New York clock.**
  - `GoatNYTime(server)` follows `Server_Clock_Model`. NYClose means server - 7 h, with no DST maths. Fixed and EUDST
    go through UTC and the US DST rule in force since 2007 (clock:13-23, 66-123).
  - `GoatNYClockApply` runs a live self-check once a minute: the model's UTC must be within 90 s of `TimeGMT`, or
    `g_GoatEntryBlocked` is set. The tester trusts the model and logs it (clock:167-220). The function returns at its
    first line unless `Clock_NewYork` or a rollover block is on (clock:189).
  - Trade dates are Mon-Fri only, with the Friday cutoff at 16:55 NY (clock:126-153). `Clock_NewYork` is tester-only
    in B53 (main:5120); the pre-2007 refusal is at main:5053.
- **D1.** `TF_D1=1440` and `TF2TF` (inputs:104-130). D1 bars start at server midnight, so `broker_fit` treats D1 as
  offset-dependent (controller/studio_broker_fit.py:127-130, 582-607).
- **Defaults that matter.** `RSI_Mode=RSI_OverBS` and `EMA_Mode=ADX_Mode=Trade_Trend` (inputs:713, 719, 729); BB, MACD
  and RSI2 default to disabled (inputs:735, 742, 752).
- **Append-only practice.** Groups are appended after `Ledger_Mode`, then B50, B49b and B51 (inputs:813-950).
  `WriteSet` writes an appended input only when it differs from its default (inputs:589-626).

## 3 Entry A: N-bar / prior-day breakout

### 3.1 Inputs (new group, appended after `Single_Partial_BE`, inputs:933)

An input is an optimisable axis when it is declared `input` and is not a string; an `sinput` never is
(controller/studio_input_schema.py:73).

| # | Name | Decl | Type | Default | Range (OnInit) | Axis | Meaning |
|---|---|---|---|---|---|---|---|
|A1|BRK_Mode|sinput|ENUM_MODE_BRK {BRK_Disabled=0, BRK_NBar=1, BRK_PriorDay=2}|BRK_Disabled|enum|no|Family off / N-bar / prior day|
|A2|BRK_TF_|input|ENUM_MODE_TFs|TF_H1|any; PriorDay: not TF_D1|Y|Trigger bar TF (NBar: also the level TF)|
|A3|BRK_Bars|input|int|20|2..500 (NBar)|Y|N, the channel length|
|A4|BRK_Buffer_ATR|input|double|0.0|0..5|Y|The close must clear the level by this x ATR|
|A5|BRK_Once_Per_Level|input|bool|true|-|Y|At most one single per signal direction per level|

### 3.2 Signal (s = Shift_Sig = 1, tf = TF2TF(BRK_TF_))

`atr` is the closed-bar ATR exactly as `GoatSingleOpen` reads it (main:8820-8823); `buf = BRK_Buffer_ATR x atr`.
- **NBar.** `up = max(High[tf, s+1..s+N])` and `dn = min(Low[tf, s+1..s+N])`, so bars 2..N+1 (N = BRK_Bars).
  `BRK_Sig = OP_BUY` if `Close[tf,s] > up+buf`, `OP_SELL` if `Close[tf,s] < dn-buf`, otherwise `OP_NULL`. Level id =
  (direction, the open time of the bar that set `up` or `dn`, the newest one on a tie).
- **PriorDay.** `D` is the newest completed D1 bar (shift >= 1) whose server weekday is Mon-Fri, which skips the Sunday
  stub bar of a GMT-offset broker; `PDH` and `PDL` are its high and low. Buy if `Close[tf,s] > PDH+buf` and
  `Close[tf,s+1] <= PDH+buf`, a fresh cross. A day that gaps above PDH still fires on its first trigger bar, because
  that bar's predecessor closed inside D. A sell is the mirror image. Level id = (direction, D's open time).
- **Unreadable data.** A short copy, an invalid ATR, fewer than N+1 bars, or no Mon-Fri D1 bar in the last 7 gives
  `OP_NULL` (never a stale buy), logged once per cause. Whether this goes through B49b's `GoatSignalReady` (main:8418)
  is left to the PR.

### 3.3 Evaluation timing

Bar close only. The term is computed in a new marked block of `UpdateCurrentSignals`, after RSI2's (after main:8645,
before the MustCheck lines at main:8647), under its own `static INTERVAL BRK_Sample; BRK_Sample.CheckTF(tf)`, as the
six existing terms are. It is recomputed once per new trigger bar and held for that bar. The single opens at the first
signal check during that bar where every gate holds, at ask or bid through `GoatSingleOpen`, never at the level.
Nothing reads `Close[0]`, the bid or the forming bar, so there is no intrabar or stop-order entry and no tick-model
dependence. Refused: `Signal_Sample_Period=M_Current` with a trigger TF shorter than the chart, which would skip
trigger bars.

### 3.4 Level timeframe

NBar levels come from `BRK_TF_` (`TF_Cur` is the chart's TF). PriorDay levels come from broker D1, which starts at
server midnight; for an NYClose broker that is 17:00 NY, the FX trade date (clock:15). Entry A never reads the New York
clock.

### 3.5 Direction

An up break is a buy signal and a down break a sell signal. `Mode_Trade`, `Reverse_Seq` (the existing global flip,
which here fades the break), `Allow_Opposite_Seq`, `DashboardEntryAllowed` and `Single_Flat_Only` apply unchanged
(main:8712-8728). `Random_Direction` runs on breakout episodes unchanged (main:8707, 8711), which gives the family its
random-direction benchmark for free.

### 3.6 Re-entry and one trade per level

1. **Episode.** Consecutive true checks are one episode (main:8740, 8783), so a run of breakout bars opens at most one
   single.
2. **One per level.** With `BRK_Once_Per_Level=true`, once a single has opened for signal direction d on level id L,
   no further single opens for d while the current level id is still L; a new channel extreme or a new prior day
   allows one again. The latch is keyed by the signal, as `g_GoatSingleArmed` is, so `Reverse_Seq` keeps it. A marked
   skip line before each Single branch and before `GoatSingleRandomEntry` checks it, following the `Single_Flat_Only`
   pattern (main:8717).
3. **Restart.** The NBar latch lives in memory only, so a live restart forgets it (the tester has no restarts). The
   PriorDay latch is rebuilt at OnInit from deal history: any `DEAL_ENTRY_IN` of this `MAGIC1` and side since the
   current D1 bar opened. That reads history rather than keeping state, as design:396-399 does. An adopted single
   disarms its signal until it reads false (design:490-491).

### 3.7 Interaction with existing filters

The term is ANDed with the six existing ones. EMA or ADX in `Trade_Trend` gives a trend-aligned break; the
`Trade_Range` and `Counter` modes filter the break by its context; BB and MACD combine the same way. RSI and RSI2 are
ANDed too, and since `RSI_Mode` defaults to `RSI_OverBS` (inputs:713), a breakout template must set
`RSI_Mode=RSI_Disabled` explicitly (Q4). `*_MustCheck` and `MustCheck_Buy/Sell` (main:8647-8657) feed only the grid's
virtual promotion (main:2598-2599) and get no new term. The session, Friday, December, rollover, clock-mismatch and
dashboard gates hold the entry as usual (main:8247, 8260). Singles do not read `Delay_Trade` or `Delay_Trade_Live`.

## 4 Entry B: session opening-range breakout

### 4.1 Inputs (same group, after Entry A's)

| # | Name | Decl | Type | Default | Range (OnInit) | Axis | Meaning |
|---|---|---|---|---|---|---|---|
|B1|ORB_Mode|sinput|ENUM_MODE_ORB {ORB_Disabled=0, ORB_Breakout=1}|ORB_Disabled|enum|no|Family off / on|
|B2|ORB_TF_|input|ENUM_MODE_TFs|TF_M5|resolves to M1..H1|Y|Trigger bar TF|
|B3|ORB_Start_Minute|input|int|570 (09:30 NY)|0..1015; multiple of the B2 minutes|Y|Range start, minutes after NY midnight|
|B4|ORB_Range_Minutes|input|int|30|5..240; multiple of the B2 minutes; B3+B4 <= 1020|Y|Range length|
|B5|ORB_Entry_Minutes|input|int|0|0..1015; B3+B4+B5 <= 1020|Y|Entry window after the range (0 = until 17:00 NY)|
|B6|ORB_Buffer_ATR|input|double|0.0|0..5|Y|The close must clear the range by this x ATR|
|B7|ORB_Min_Range_ATR|input|double|0.0|>=0|Y|No trade that day if the range is below this x ATR (0 = off)|
|B8|ORB_Max_Range_ATR|input|double|0.0|>=0; > B7 when both are > 0|Y|No trade that day if the range is above this x ATR (0 = off)|

### 4.2 Session definition

- **Windows.** The trade date T is the NY calendar date, Mon-Fri only (`GoatNYWeekday`). The range window is
  `W = [S, S+R)` in NY minutes on T, where S = `ORB_Start_Minute` and R = `ORB_Range_Minutes`. The entry window is
  `E = [S+R, S+R+ORB_Entry_Minutes)`, or `[S+R, 17:00)` when that input is 0; on a Friday E ends no later than 16:55 NY,
  the clock's Friday cutoff (clock:151). With S+R+E <= 17:00 NY, every window sits inside one NY calendar date and one
  FX trade date, never crossing 17:00 or midnight (Asian windows: Q6). S and R must be multiples of the trigger TF's
  minutes, so under an NYClose model or any whole-hour offset the trigger bars align with W.
- **Range.** H and L are the high and low of the M1 bars whose NY open time `GoatNYTime(bar time)` falls in W. They
  are computed once per T, at the first evaluation after S+R, from M1 history (`CopyRates`, PERIOD_M1), and never
  accumulated from ticks, so a restart and the tick model do not change them. The range is valid only with at least
  ceil(R/2) M1 bars; with fewer, that day has no ORB, logged once (a holiday or a data gap). It must also pass B7/B8,
  measured against the closed-bar ATR at that evaluation.

### 4.3 Signal and evaluation timing

The term is evaluated on each new bar of `TF2TF(ORB_TF_)` (`static INTERVAL ORB_Sample`), in the same
`UpdateCurrentSignals` block as Entry A, at bar close only, as in 3.3. Bar s is eligible when its NY open is >= S+R and
its NY close is <= the end of E. Then `ORB_Sig = OP_BUY` if `Close[s] > H+buf` and `Close[s+1] <= H+buf`, and
`OP_SELL` is the mirror image against L, with `buf = ORB_Buffer_ATR x atr`. Unreadable data gives `OP_NULL`, logged
once per cause, as in 3.2.

### 4.4 Clock and DST

- **Source.** NY time comes from `GoatNYTime` under `Server_Clock_Model` (clock:119-123), not from `Clock_Mode`.
  Entry B needs no `Clock_NewYork` and does not change which clock sets `Active`: the server table (main:7927-7936)
  or the NY session (clock:229-235).
- **DST.** Under NYClose the server already moves with US DST (server = NY + 7 h, clock:15), so a 09:30 NY window is the
  same server time all year. Under Fixed and EUDST, UTC comes from the declared offset (plus EU DST for EUDST) and NY
  from the US rule, the 2nd Sunday of March 07:00 UTC to the 1st Sunday of November 06:00 UTC (clock:13-18), so the
  window moves in server time on the US dates. The ambiguous hours fall on a Sunday, while the market is shut
  (clock:19). Under Fixed or EUDST, a tester start before 2007-03-11 is refused, by extending main:5053 to `ORB_Mode`.
- **Live.** `GoatNYClockApply`'s first line (clock:189) gains `&& ORB_Mode==ORB_Disabled`, so the once-a-minute
  self-check runs whenever ORB is on, and a mismatch blocks new entries (clock:220, main:8260).
- **Tester.** It has no GMT, so it trusts the model and logs it (clock:209-217). The evidence must record
  `Server_Clock_Model`, and ruling 2 (design:158) applies to ORB as it does to `Clock_NewYork` (Q8).

### 4.5 Direction, re-entry, filters

Direction is as in 3.5. Re-entry: at most one single per signal direction per T. The latch is keyed by T and rebuilt
at OnInit from that day's deal history, like PriorDay's. A buy and a sell on the same T are both allowed unless
`Single_Flat_Only` forbids the overlap, and the episode rule from 3.6 applies. Filters are as in 3.7. An entry also
needs `Active`, so a SET whose session excludes E never trades (Q10). The rollover block applies.

### 4.6 OnInit refusals (block `b54-init`, after main:5121; each ported to EA_INIT_RULES)

Each is INIT_PARAMETERS_INCORRECT unless noted: either family with `Engine_Mode!=Engine_Single`; both families on in
one SET; any range or alignment rule in 3.1 or 4.1; `BRK_PriorDay` with `BRK_TF_=TF_D1` (degenerate); the M_Current
cadence rule (3.3); ORB with Fixed or EUDST before 2007-03-11; ORB on a live chart (INIT_FAILED, tester-only like
main:5120, `NOT_PORTED`; Q7).

## 5 Exits (reuse of Engine_Single, no new exit code)

- **Stop and TP.** `Size_SL = Single_SL_ATR x ATR` on the closed bar, and the TP from `Single_TP_R` or `Single_TP_ATR`
  (main:8819-8839), with the same lot rules and refusals. The stop is never placed at the range or the level (Q9).
- **Break-even, trailing, partial.** `Single_BE_ATR`, `Single_Trail_Start_ATR`, `Single_Trail_ATR` (main:9117-9123) and
  `Single_Partial_*` (main:8176) are unchanged.
- **Time stop.** `Single_Time_Stop_Bars` and `_TF` (main:10253-10307). To be flat by the session end, use the time stop
  or `Action_Dayend`.
- **Opposite exit.** `Single_Exit_Opposite`: the family's term is added to `GoatSignalAll` in lockstep with
  `SignalEntryTrigger`, so the opposite exit means the opposite break (main:10227-10252).
- **Broker SL/TP, MLPS, news and Friday actions** are unchanged. MLPS firing early by the entry commission is accepted
  (ruling 3, design:159).
- **Template note.** `ATR_TF_` defaults to `TF_M1`, period 100 (inputs:681-683), so a breakout template sets ATR's TF to
  suit both its stop and its buffer.

## 6 Compatibility and proof plan

### 6.1 Rules

One new group, `input group "====SINGLE BREAKOUT ENTRIES (B54)===="`, is appended after the B51 block (after
inputs:950). The new enums have explicit numbers, and no existing enum gains a value. `WriteSet` gets one marked line
per new input, written only when it differs from its default, after inputs:626. With both modes disabled, both terms
are constant true, so the combined conditions, `GoatSignalAll` and the arm flags read as in B53, and
`GoatNYClockApply` returns where it does in B53. Markers alone prove no neutrality: a marked line can still change
behaviour (test_b49b_no_drift.cjs:20-22). Only 6.2 and 6.3 prove it.

### 6.2 Gate 0, before anything else: effective-input equality on the 61 pool files

It runs in the first PR (A0: inputs, enums, WriteSet, the regenerated contracts/v149, the `B54_INPUTS` group, the
setting types, the child audit and the init rules, with both terms stubbed). Nothing else merges until it passes.

- **Pool.** The 61 SETs of `G:\GOAT-Build-Artifacts\interim-ops-20261108\nonrr-round08\qualified-inventory-final.json`
  (sha256 `f4337e1bd296f7a4de3c5e53d6f7acab9d7454d8b6172739eb5729183984936c`; 59 sequence and 2 single; captured on
  B51, `audit_cashflow_correlation61.py:10,25`). Each SET's sha256 is frozen in a committed manifest, as
  test_hunt_sets_init.cjs:3-4 and 17-29 do (Q2).
- **Baseline.** B53's `contracts/v149` at 216e1622 (`S53`) against the new schema (`S54`).

The checks, per file:
1. The SET names none of the 13 new inputs (one that does fails, because B53 never wrote it).
2. `pinned_tester_inputs(values,S54)`, restricted to S53's keys, equals `pinned_tester_inputs(values,S53)` byte for
   byte (studio_tester_report.py:320-331). The remaining keys are exactly the 13 new names, each at `appended_default`
   (studio_strategy_settings.py:90-98), the optimisable ones spelled `d||d||0||d||N`.
3. `explicit_optimization_inputs(text,S54)` equals the S53 result plus only the new optimisable lines, in order
   (studio_optimization_inputs.py:16-40). `verify_explicit_inputs` with the SET's frozen axes passes under both (:43-63),
   so no axis is added.
4. `validate_strategy` accepts the file under both schemas, with the same axes (studio_strategy_settings.py:112-121).
5. On the EA side, `b50_tick_harness` runs OnInit on B53 and on B54 at the SET's values and at each Y axis's start and
   stop, the method of test_hunt_sets_init.cjs:5-9. The init result is the same; after OnInit, B53's input globals are
   equal and the new ones are at their defaults.
6. `WriteSet` bytes from each file's values are the same on B54 as on B53.

Output: a receipt JSON with each file's sha256 and per-check result, kept on this PC, plus an inline summary in the
post, since Mac cannot read G:.

### 6.3 Neutrality and behaviour proofs (after gate 0)

- **`scripts/test_b54_no_drift.cjs` against 216e1622.** Every changed line carries `B54` or sits in a `// B54:begin`
  block. `REMOVED` lists the closing-paren lines of the combined conditions (main:8705, 8749) and of `GoatSignalAll`
  (main:10213, 10220). NEW_INPUTS is exactly the 13, in order, at the end, and B53's inputs keep their type, default
  and enum choices.
- **`scripts/test_b54_parity.cjs`.** The harness runs flags off against B53 on the grid and single fixtures of
  test_b51_parity.cjs:8-11, with `FastSpeed_Flag` both true and false, plus the default-SET `WriteSet` golden.
- **Native Banker parity.** The B54 EX5 against the B53 EX5 on all 61 files: flags off, the same window, Model 4. The
  deal tables (time, type, volume, price, SL, TP, profit, commission, swap, comment) and the export CSVs must be
  identical, following design:127 (Q3).
- **`test_b54_breakout.cjs`** (with mutants). It covers NBar levels at bars 2..N+1; PriorDay's Sunday stub skipped, its
  cross and its gap-open case; the buffer; the latch across a stop-out and after a new extreme; `Reverse_Seq`,
  `Random_Direction` and `Single_Flat_Only`; the EMA-trend AND; the opposite exit on the opposite break; unreadable
  data giving `OP_NULL`; FastSpeed both ways; and every OnInit refusal. Mutants: `Close[0]`, bar 1 included in the
  level, `>=` for `>`, the Sunday stub kept, the latch dropped, the latch keyed by position side.
- **`test_b54_orb.cjs`** (with mutants). It covers the window boundaries (S included, S+R excluded); the M1 count rule;
  B7/B8; the Friday 16:55 cutoff; the entry-window end; the latch for each T; DST dates 2007-2035 under all three
  models, including the London/NY mismatch weeks; the live mismatch block and the tester trusting the model; the
  pre-2007 refusal. Mutants: NY time from raw server time, the first Sunday in place of the second, the range from
  ticks, S+R included, the self-check line left unchanged.
- **Updated tests.** `test_b50_exits` (the 8-term text match); `test_studio_appended_inputs`,
  `test_studio_ea_init_rules`, `test_studio_pinned_tester_inputs` (the new axes), `test_studio_optimization_inputs` and
  `test_studio_broker_fit`; `test_portfolio_child_audit`, `test_studio_setting_compare` and `test_hunt_sets_init`
  (which must still init).

## 7 Controller and catalog impact

- **Schema.** `B54_INPUTS` (the 13 names, in order) is appended to `APPENDED_INPUTS` and `APPENDED_GROUPS`, so a schema
  declares all of the group or none of it (studio_strategy_settings.py:79-87). `contracts/v149` `inputs.json` and
  `dependencies.json` are regenerated from the header. The init rules and their line anchors are regenerated once, in
  A0 (studio_ea_init_rules.py:378-380 shows the form; design:148).
- **EA-side Studio.** The type lists and the optimization-name allowlist (GOATStudioSettingTypes.mqh:17-18, 36, 43-44)
  and the defaults (:58-68); the child audit's names (GOATPortfolioChildAudit.mqh:213-214 and 240 show the pattern).
  The readback still accepts an omitted appended input only at its default (studio_strategy_settings.py:64-69).
- **Pinned inputs.** An older SET launched on B54 gets every optimisable new input fixed at its default as
  `d||d||0||d||N` (studio_tester_report.py:320-331), and the explicit native config does the same
  (studio_optimization_inputs.py:26-39). That is what gate 0 proves.
- **Axes.** Y: `BRK_TF_`, `BRK_Bars`, `BRK_Buffer_ATR`, `BRK_Once_Per_Level`, `ORB_TF_`, `ORB_Start_Minute`,
  `ORB_Range_Minutes`, `ORB_Entry_Minutes`, `ORB_Buffer_ATR`, `ORB_Min_Range_ATR`, `ORB_Max_Range_ATR`. Never an axis:
  `BRK_Mode` and `ORB_Mode`, which are sinputs, so a template fixes its family. The exits keep the existing `Single_*`
  axes.
- **broker_fit.** `TF_INPUTS` (studio_broker_fit.py:127) gains `BRK_TF_` and `ORB_TF_`. `BRK_PriorDay` is a D1 offset
  reason, and ORB on is a NY-clock reason, as `Clock_NewYork` is (:604-607).
- **Catalog.** Three template families, built through the app's own build-set and seed loop: `single-brk-nbar`,
  `single-brk-pday` and `single-orb`. Each has `Engine_Single`, `RSI_Mode=RSI_Disabled`, EMA and ADX as an optional
  context axis, and an explicit `ATR_TF_`. Family labels stay out of public feeds until the installed desktop's strict
  readers accept them. controller/INPUT-REFERENCE.md gains the 13 inputs.

## 8 Open questions

1. **Build identity.** A research-only V1.49 candidate, marker `B54`? Must it wait for B53's evidence week?
2. **The pool.** Is it the `nonrr-round08` inventory above (captured on B51)? Commit the SETs as fixtures, or PC only?
3. **Native parity cost.** All 61 files need Banker time. Is a sample acceptable?
4. **RSI as an AND term.** Should OnInit refuse `RSI_OverBS` with a breakout, or leave it to the templates?
5. **Prior day.** Broker D1 (proposed) or the NY trade date for non-NYClose brokers? Skip Sat/Sun-dated D1 bars?
6. **ORB clock.** NY only (proposed)? London 08:00 is 03:00 NY, 04:00 in the mismatch weeks; Asia crosses 17:00 NY.
7. **ORB on demo.** Tester-only at first, like `Clock_NewYork` (main:5120), or demo with the self-check?
8. **Ruling 2.** No controller check found (`Server_Clock_Model` is only at studio_ea_init_rules.py:489-495). Build it?
9. **Stops and chasing.** A range- or level-based stop later? A chase limit such as `BRK_Max_Chase_ATR`?
10. **Session vs entry window.** Should the Studio refuse an ORB SET whose trading session cannot overlap E?
11. **ORB re-entry.** A second entry on the same side and T after a stop, or a first-break-only option?
12. **Cool-down.** Is GOAT-EA#246's re-entry cool-down (item 5, still open) needed for the breakouts?
13. **Restarts.** Is losing NBar's latch on a live restart acceptable? And rebuilding PriorDay/ORB's from history?
14. **Holidays.** There is no calendar; the ceil(R/2) M1 rule is the only guard. Is it enough?
15. **Families on the same chart.** One family per SET is proposed. Should the two be allowed together?
16. **Dashboard.** Should the panel show the new terms? It has 6 indicator rows (e.g. main:8449).
