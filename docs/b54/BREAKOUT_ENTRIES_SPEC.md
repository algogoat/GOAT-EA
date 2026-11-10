# Spec: breakout entries for Engine_Single (N-bar / prior day, session opening range)

Status: APPROVED to proceed to PR A0 (gate 0) by Claude-Mac 6759774556; changes 1-5 folded in.

Source read: GOAT-EA B53, the final build `V1.49-BETA17-53` (`candidate-builds/beta17-B53/identity.json`, EX5 sha256
`4733511303cf216f8ec513556abc89f492176063001dd77c8405c79a995cc068`), merge `216e1622` (GOAT-EA#296). I read it in the
checkout `C:\GOAT-Evidence\ea-builds-20261107\src\b51-live-trial` at `5cfb789`, which has the same tree
(`git diff --quiet 5cfb789 216e162` exits 0). Line numbers are at that commit. Short names: `main` = `GOAT V1.49.mq5`,
`inputs` = `GOAT_Inputs_Definitions.mqh`, `clock` = `GOAT_NYClock.mqh`, `design` = `docs/b50/B50_ALPHA_DESIGN.md`.
Build: a research-only V1.49 candidate, marker `B54` (ruling 1).

## 1 Purpose and non-goals

Two new entry families, for `Engine_Single` only: **A**, an N-bar or prior-day high/low breakout, and **B**, a session
opening-range breakout (ORB). Each family adds one term to the combined entry signal. With its mode at `Disabled`, the
term always reads true, so every existing SET trades byte-identically to B53.

Non-goals:
- grid or sequence variants (refused at OnInit);
- new oscillators (Stochastic, CCI, Williams), carry, or patterns;
- new exit or stop logic, including a range-edge stop or a chase limit (ruling 9);
- a cool-down (ruling 12);
- Asian ORB windows (V2);
- dashboard work (ruling 16);
- any change to an existing input, enum value or default.

## 2 Existing mechanics relied on

- **Combined signal.** `SignalEntryTrigger` ANDs six terms for a buy (main:8699-8705) and six for a sell
  (main:8743-8749); a disabled mode's term reads true. The Single branch opens through `GoatSingleOpen` at once, with
  no virtual leg, so `Delay_Trade` is never read (main:8718, 8726, 8761, 8769; design:14).
- **One single per episode.** `g_GoatSingleArmed[signal]` is cleared on an open and re-armed when that signal's
  combined condition reads false (main:8740, 8783; inputs:859-862; design:30, 161). The flag belongs to the signal,
  not to the position side: under `Reverse_Seq` a buy signal opens `Seq_Sell` and clears `g_GoatSingleArmed[OP_BUY]`
  (main:8718, 8761).
- **Gates.**
  - news and bias (main:8708, 8752);
  - `Reverse_Seq`, `Mode_Trade`, `DashboardEntryAllowed` and `Allow_Opposite_Seq` (main:8712-8728);
  - `Single_Flat_Only` (main:8717, 8973-8977).
- **Random direction.** `GoatSingleRandomEntry` takes the episode's place (main:8707, 8711). It checks the arm flag
  and `GoatSingleBothFree` before the draw (main:8982-8986). On an open it clears the signal's flag, whatever side was
  drawn (main:8990).
- **Cadence.** `CheckSignalNow` runs on `Signal_Sample_Period` (inputs:654, default M1; inputs:1536-1547), with
  `Shift_Sig=1` (main:8237).
  - `SignalEntryTrigger` runs only while `Active`, the start flags hold and `!g_GoatEntryBlocked` (main:8247, 8260).
  - Each term is refreshed on a new bar of its own TF via `INTERVAL::CheckTF` (inputs:430-435; e.g. main:8466-8467).
  - `Engine_Single` skips the `FastSpeed_Flag` early return (main:8457-8458).
  - Terms read closed bars only, so the result does not depend on the tick model (design:249-258).
- **Opposite exit.** `GoatSignalAll` is a verbatim copy of the six terms, and `scripts/test_b50_exits.cjs` asserts that
  it matches (main:10203-10222). The exit itself is at main:10227-10252.
- **Sizes.**
  - `Size_SL = Single_SL_ATR x ATR`, where ATR is the closed bar (shift 1) of `ATR_MA_handle`, read into a local buffer.
  - The TP is in R, else in ATR, and the stops-level refusals apply (main:8819-8839).
  - Single mode creates the ATR handles whatever the grid mode (main:5070-5082). ATR inputs: inputs:681-683.
- **Single exits.**
  - break-even and trailing (main:9117-9123, design 8.2);
  - the partial close (main:8176, design 8.3);
  - the time stop, counted from `POSITION_TIME` (main:10253-10307);
  - MLPS (main:8279-8280), and the broker SL and TP.
- **Clock module.**
  - DST rules (clock:13-14, 66-91). US: from the 2nd Sunday of March 07:00 UTC to the 1st Sunday of November
    06:00 UTC. EU: from the last Sunday of March to the last Sunday of October, both at 01:00 UTC.
  - `GoatNYServerToUTC` follows `Server_Clock_Model`; under NYClose it goes through the US rule (clock:101-117).
  - `GoatNYTime`: NYClose is server - 7 h; the other models go UTC to NY (clock:95-99, 119-123).
  - The ambiguous hours fall on a Sunday (clock:19). The rules hold from 2007 on (clock:20-23).
  - The trade date is Mon-Fri, and the Friday cutoff is 16:55 NY (clock:126-153).
  - Self-check and tester trust: clock:167-220. The function returns at once unless `Clock_NewYork` or a rollover
    block is on (clock:189).
  - `Clock_NewYork` is tester-only in B53 (main:5120). The pre-2007 refusal is at main:5053.
- **D1.** `TF_D1=1440` and `TF2TF` are at inputs:104-130. D1 bars start at server midnight, so `broker_fit` treats D1
  as offset-dependent (controller/studio_broker_fit.py:127-130, 582-607).
- **Defaults.** `RSI_Mode=RSI_OverBS`, and `EMA_Mode=ADX_Mode=Trade_Trend` (inputs:713, 719, 729). BB, MACD and RSI2
  are disabled (inputs:735, 742, 752).
- **Append-only.** Input groups follow `Ledger_Mode`, then B50, B49b and B51 (inputs:813-950). `WriteSet` writes an
  appended input only when it differs from its default (inputs:589-626).

## 3 Entry A: N-bar / prior-day breakout

### 3.1 Inputs (new group, appended after `Single_Partial_BE`, inputs:933)

An axis is an `input` that is not a string; an `sinput` never is (controller/studio_input_schema.py:73).

| # | Name | Decl | Type | Default | Range (OnInit) | Axis | Meaning |
|---|---|---|---|---|---|---|---|
|A1|BRK_Mode|sinput|ENUM_MODE_BRK {BRK_Disabled=0, BRK_NBar=1, BRK_PriorDay=2}|BRK_Disabled|enum|no|Family off / N-bar / prior day|
|A2|BRK_TF_|input|ENUM_MODE_TFs|TF_H1|any; PriorDay: not TF_D1, and not TF_Cur on a chart of D1 or longer|Y|Trigger bar TF (NBar: also the level TF)|
|A3|BRK_Bars|input|int|20|2..500 (NBar)|Y|N, the channel length|
|A4|BRK_Buffer_ATR|input|double|0.0|0..5|Y|The close must clear the level by this x ATR|
|A5|BRK_Once_Per_Level|input|bool|true|-|Y|PriorDay only: at most one single per signal direction per day D (NBar ignores it)|

### 3.2 Signal (s = Shift_Sig = 1, tf = TF2TF(BRK_TF_))

`buf = BRK_Buffer_ATR x atr`. `atr` is the `ATR_MA_handle` value of the newest `ATR_TF_` bar closed at or before bar
s's close, found by time, so it does not depend on when the check runs.

- **NBar.** `up = max(High[tf, s+1..s+N])` and `dn = min(Low[tf, s+1..s+N])` (bars 2..N+1). `BRK_Sig = OP_BUY` if
  `Close[tf,s] > up+buf`, `OP_SELL` if `Close[tf,s] < dn-buf`, else `OP_NULL`.
- **PriorDay.** D is the newest completed Mon-Fri broker D1 bar before the D1 bar that contains bar s, found by time
  from bar s's open (ruling 5; this skips a GMT broker's Sunday stub). PDH and PDL are D's high and low.
  - Buy if `Close[tf,s] > PDH+buf` and `Close[tf,s+1] <= PDH+buf`, a fresh cross. A gap above PDH still fires on the
    day's first trigger bar, because its predecessor lies in D.
  - A sell is the mirror image.
- **Unreadable data.** A short copy, an invalid ATR, fewer than N+1 bars, or no Mon-Fri D1 bar in the last 7 gives
  `OP_NULL` (never a stale buy), logged once per cause. Whether this goes through B49b's `GoatSignalReady`
  (main:8418) is left to the PR.

### 3.3 Evaluation timing

Bar close only. The term is computed in a new marked block of `UpdateCurrentSignals`, after RSI2 (after main:8645,
before the MustCheck lines at main:8647). It runs under `static INTERVAL BRK_Sample; BRK_Sample.CheckTF(tf)`, as the
six terms do: computed once per new trigger bar and held for that bar.
- **Entry.** The first signal check in that bar at which every gate holds opens the trade, at ask or bid through
  `GoatSingleOpen`, never at the level.
- **No intrabar entry.** `Close[0]`, the bid and the forming bar are never read, so there is no intrabar or stop-order
  entry and no tick-model dependence.
- **Refused:** `Signal_Sample_Period=M_Current` with a trigger TF shorter than the chart's (trigger bars would be
  skipped).

### 3.4 Level timeframe and direction

- **Levels.** NBar levels come from `BRK_TF_` (`TF_Cur` is the chart's TF). PriorDay levels come from broker D1, which
  starts at server midnight (17:00 NY for an NYClose broker, clock:15). Entry A never reads the clock module.
- **Direction.** An up break is a buy signal and a down break a sell signal. `Mode_Trade`, `Allow_Opposite_Seq`,
  `DashboardEntryAllowed` and `Single_Flat_Only` apply unchanged (main:8712-8728). `Reverse_Seq` is the existing
  global flip, so it fades the break.

### 3.5 Re-entry, latch, Reverse_Seq, Random_Direction

1. **NBar.** Re-entry follows the existing episode rule alone: the signal must read false and then true again
   (main:8740, 8783), plus `Single_Flat_Only` if set. There is no latch, because a breakout bar's own high becomes the
   next channel extreme (change 1).
2. **PriorDay latch.** With `BRK_Once_Per_Level=true`, once a single opens for signal direction d on day D, no further
   single opens for d until D changes.
   - It is checked by a marked skip line before each Single branch and before `GoatSingleRandomEntry`, in the
     `Single_Flat_Only` pattern (main:8717).
   - It is rebuilt at OnInit from deal history: any `DEAL_ENTRY_IN` of this `MAGIC1` and side since the current D1
     bar opened. This reads history, not state, as design:396-399 does (ruling 13).
3. **Reverse_Seq.** The episode flag and the latch stay keyed by the signal direction, as `g_GoatSingleArmed` is
   (main:8718, 8761). So an up-cross that opened a faded sell blocks a second faded sell on the same D and leaves the
   down-cross free to open a buy.
4. **Random_Direction.** The flag and the latch are checked before the draw, and the latch is recorded for the signal
   whatever side is drawn (main:8982-8990). Whether a day's break trades never depends on the draw; the draw only
   picks the side.

### 3.6 Interaction with existing filters

The term is ANDed with the six existing terms:
- **EMA and ADX.** `Trade_Trend` gives a trend-aligned break; `Trade_Range` and `Counter` filter the break by context.
- **BB, MACD, RSI and RSI2** combine the same way. There is no refusal for `RSI_OverBS`; the templates set
  `RSI_Disabled` (ruling 4).
- **`*_MustCheck` and `MustCheck_Buy/Sell`** (main:8647-8657) feed only the grid's virtual promotion (main:2598-2599),
  so they get no new term.
- **Other gates.** Session, Friday, December, rollover, clock-mismatch and dashboard gates hold as usual (main:8247,
  8260).

## 4 Entry B: session opening-range breakout

### 4.1 Inputs (same group, after Entry A's)

Lim = 1020 (17:00 NY) under the NewYork anchor, and 1260 (21:00 London) under the London anchor; 4.4 explains why.

| # | Name | Decl | Type | Default | Range (OnInit) | Axis | Meaning |
|---|---|---|---|---|---|---|---|
|B1|ORB_Mode|sinput|ENUM_MODE_ORB {ORB_Disabled=0, ORB_Breakout=1}|ORB_Disabled|enum|no|Family off / on|
|B2|ORB_Clock|sinput|ENUM_ORB_CLOCK {ORB_Clock_NewYork=0, ORB_Clock_London=1}|ORB_Clock_NewYork|enum|no|Clock anchor for B4-B6|
|B3|ORB_TF_|input|ENUM_MODE_TFs|TF_M5|TF_M1, TF_M5, TF_M15 or TF_H1; TF_Cur is refused (B4 and B5 count in minutes the SET names)|Y|Trigger bar TF|
|B4|ORB_Start_Minute|input|int|570|0..Lim-5; multiple of the B3 minutes|Y|Range start, minutes after the anchor's midnight|
|B5|ORB_Range_Minutes|input|int|30|5..240; multiple of the B3 minutes; B4+B5 < Lim|Y|Range length|
|B6|ORB_Entry_Minutes|input|int|0|0..Lim, checked before the sum (a 32-bit int sum can wrap); B4+B5+B6 <= Lim|Y|Entry window after the range (0 = until 17:00 NY)|
|B7|ORB_Buffer_ATR|input|double|0.0|0..5|Y|The close must clear the range by this x ATR|
|B8|ORB_Min_Range_ATR|input|double|0.0|>=0|Y|No trade that day if the range < this x atr_r (0 = off)|
|B9|ORB_Max_Range_ATR|input|double|0.0|>=0; > B8 when both > 0|Y|No trade that day if the range > this x atr_r (0 = off)|

### 4.2 Session definition

- **Anchor time.** NewYork uses `GoatNYTime(server)` (clock:119-123). London uses a new pure
  `GoatLondonTime(server) = utc + (GoatNYEUDST(utc) ? 3600 : 0)`, with `utc = GoatNYServerToUTC(server)`, in a marked
  B54 block of the clock module (clock:87-91, 101-117). The UK changes clocks on the EU dates (clock:14, 74-81).
- **Windows.**
  - The trade date T is the anchor's calendar date, Mon-Fri only.
  - Range window: `W = [S, S+R)` in anchor minutes on T, where S = B4 and R = B5.
  - Entry window: `E = [S+R, S+R+B6)`, or from S+R until 17:00 NY that day when B6 = 0. On a Friday, E ends no later
    than 16:55 NY under either anchor (clock:151).
  - S and R are multiples of the trigger TF's minutes, so trigger bars line up with W.
- **Range.** H and L are the high and low of the M1 bars whose anchor-local open falls in W. They are read once per T
  from M1 history (`CopyRates`, PERIOD_M1) at the first evaluation after S+R, never built up from ticks.
  - The range is valid only with at least ceil(R/2) M1 bars; otherwise that day has no ORB, logged once (ruling 14).
- **Range filter (B8/B9), restart-invariant.** t* is the close of the last completed `ORB_TF_` bar at or before S+R,
  found by time.
  - `atr_r` is the `ATR_MA_handle` value of the newest `ATR_TF_` bar closed at or before t*, located with `iBarShift`,
    never by a shift from the current bar.
  - So a restart mid-session cannot change the day's verdict (change 2).

### 4.3 Signal and evaluation timing

The term is evaluated on each new bar of `TF2TF(ORB_TF_)` (`static INTERVAL ORB_Sample`), in the same block as Entry
A, at bar close only, as in 3.3.
- **Eligible bar.** Bar s is eligible when its anchor-local open is at or after S+R and its close is at or before E's
  end.
- **Signal.** `ORB_Sig = OP_BUY` if `Close[s] > H+buf` and `Close[s+1] <= H+buf`. A sell is the mirror image against
  L. Here `buf = ORB_Buffer_ATR x atr`, with `atr` as in 3.2.
- **Unreadable data** gives `OP_NULL`, logged once per cause.

### 4.4 Clock and DST

- **NewYork anchor.** Under NYClose the server moves with US DST (server = NY + 7 h, clock:15), so a 09:30 NY window
  has the same server time all year. Under Fixed and EUDST, UTC comes from the declared offset (plus EU DST under
  EUDST) and NY from the US rule (clock:13, 101-117), so the window moves in server time on the US dates.
- **London anchor.** The window follows the EU dates, so 08:00 London stays 08:00 London through the US/EU mismatch
  weeks. Those run from the 2nd Sunday to the last Sunday of March, and from the last Sunday of October to the 1st
  Sunday of November; about three of them fall in the hunt's O window (change 4).
- **No window crosses 17:00 NY.**
  - 17:00 NY is 22:00 London when both rules agree, and 21:00 London while the US is on DST and the EU is not. The EU
    is never on DST while the US is off.
  - So Lim = 1260 under the London anchor.
  - London midnight is already past 17:00 NY of the previous NY date (19:00 or 20:00 NY).
  - So under either anchor a window stays inside trade date T and never crosses 17:00 NY in either DST state. OnInit
    refuses any B4-B6 combination that could (4.1).
- **Pre-2007.** A tester start before 2007-03-11 is refused for ORB with the NewYork anchor under Fixed or EUDST, as
  main:5053 does. Under the London anchor it is refused under every model, because NYClose derives UTC through the
  2007 US rule (clock:103-109).
- **Tester only (ruling 7).** The tester trusts `Server_Clock_Model` (clock:209-217). The ORB block logs one line at
  OnInit with `Server_Clock_Model`, `Server_UTC_Offset` and `ORB_Clock` for the evidence.
  - B54 leaves clock:189 unchanged.
  - The live self-check for ORB belongs to the controller clock-model PR and a later live admission (ruling 8).

### 4.5 Direction, re-entry, filters

- **Direction** works as in 3.4.
- **Re-entry.** One entry per direction per trade date T (ruling 11).
  - The latch is keyed by T and the signal direction, so 3.5 items 3 and 4 apply unchanged.
  - It is rebuilt at OnInit from T's deal history (ruling 13).
  - A buy and a sell on the same T are both allowed unless `Single_Flat_Only` forbids the overlap.
- **Filters** work as in 3.6. An entry also needs `Active`.
  - There is no Studio refusal for a session that misses E (ruling 10).
  - The rollover block applies.

### 4.6 OnInit refusals (block `b54-init`, after main:5121; each ported to EA_INIT_RULES)

Each returns INIT_PARAMETERS_INCORRECT unless noted:
- either family without `Engine_Single`;
- both modes on (one family per SET, ruling 15);
- any range, alignment or Lim rule in 3.1 or 4.1;
- `BRK_PriorDay` with `BRK_TF_=TF_D1`;
- the M_Current cadence rule (3.3);
- the pre-2007 rules (4.4);
- ORB on a live chart: INIT_FAILED, `NOT_PORTED`, as at main:5120 (ruling 7).

As built in PR A (GOAT-EA#304; Claude-Mac 6764975563):
- **Scope.** A family's range, alignment and Lim rules apply only while its mode is on; a disabled family's inputs are
  never read.
- **Bounds before sums.** Each input is bounded on its own before a sum reads it: B4 and B5 before B4+B5 < Lim, and B6
  <= Lim before B4+B5+B6 <= Lim, because a 32-bit int sum can wrap.
- **Not-built refusals.** Until a mode value has its signal term, the tree refuses it outright with INIT_FAILED, in the
  tester and on a live chart (the ruling on GOAT-EA#303, condition 3).
  - Each is ported to EA_INIT_RULES, since it reads one input value, so validate-set refuses such a SET first.
  - They are the block's last lines, so the range and Lim rules stay reachable and tested.
  - The commit that adds a value's term removes its line. PR A removed `BRK_NBar`'s and `BRK_PriorDay`'s; PR B removes
    `ORB_Breakout`'s.
- **Mirror.** Ported to EA_INIT_RULES: the rules on input values. TESTER_INIT_RULES: the two pre-2007 test starts.
  NOT_PORTED: the M_Current cadence (3.3) and PriorDay on TF_Cur (A2), which read the chart's timeframe, and ORB on a live
  chart.

## 5 Exits (reuse of Engine_Single, no new exit code; ruling 9)

- **Stop and TP.** `Size_SL = Single_SL_ATR x ATR` on the closed bar, and the TP from `Single_TP_R` or `Single_TP_ATR`
  (main:8819-8839). The lot rules and refusals are the same.
- **Break-even, trailing, partial.** `Single_BE_ATR`, `Single_Trail_Start_ATR` and `Single_Trail_ATR`
  (main:9117-9123), and `Single_Partial_*` (main:8176), are unchanged.
- **Time stop.** `Single_Time_Stop_Bars` and `_TF` (main:10253-10307), or `Action_Dayend`, keep the account flat by
  the session end.
- **Opposite exit.** `Single_Exit_Opposite`: each family's term goes into `GoatSignalAll` in lockstep with
  `SignalEntryTrigger`, so the opposite exit is the opposite break (main:10227-10252).
- **MLPS** may fire early by the entry commission; this is accepted (design:159).
- **ATR timeframe.** `ATR_TF_` defaults to `TF_M1` with period 100 (inputs:681-683), so templates set it explicitly.

## 6 Compatibility and proof plan

### 6.1 Rules

- **Inputs.** One new group, `input group "====SINGLE BREAKOUT ENTRIES (B54)===="`, after the B51 block (after
  inputs:950), with 14 inputs: A1-A5 and B1-B9.
- **Enums.** The new enums take explicit numbers. No existing enum gains a value.
- **WriteSet.** One marked line per input, written only when it differs from its default, after inputs:626.
- **Defaults.** With both modes disabled, both terms are constant true. The combined conditions, `GoatSignalAll`, the
  arm flags and `GoatNYClockApply` then read as in B53.
- **Markers.** They prove visibility, not neutrality (test_b49b_no_drift.cjs:20-22). Neutrality is proven by 6.2 and
  6.3 only.

### 6.2 Gate 0, before anything else: effective-input equality on the pool

Gate 0 runs in CI in PR A0. A0 carries the inputs, enums, WriteSet, the regenerated contracts/v149, `B54_INPUTS`, the
setting types, the child audit and the init rules, with both terms stubbed. Nothing else merges until gate 0 passes.

- **Pool (ruling 2).** The 61 SETs of
  `G:\GOAT-Build-Artifacts\interim-ops-20261108\nonrr-round08\qualified-inventory-final.json` (sha256
  `f4337e1bd296f7a4de3c5e53d6f7acab9d7454d8b6172739eb5729183984936c`; 59 sequence, 2 single), plus every SET rounds 11
  and 12 admit before A0 merges. They are committed byte-identical as fixtures with a sha256 manifest, as
  test_hunt_sets_init.cjs:3-4 and 17-29 do.
- **Baseline.** `S53`, B53's `contracts/v149` at 216e1622, against `S54`, the new schema.

Per file:
1. The SET names none of the 14 new inputs.
2. `pinned_tester_inputs(values,S54)`, restricted to S53's keys, equals `pinned_tester_inputs(values,S53)` byte for
   byte (studio_tester_report.py:320-331). The other keys are exactly the 14 new names, each at `appended_default`
   (studio_strategy_settings.py:90-98), with the optimisable ones as `d||d||0||d||N`.
3. `explicit_optimization_inputs(text,S54)` equals the S53 result plus only the new optimisable lines, in order
   (studio_optimization_inputs.py:16-40). `verify_explicit_inputs` with the SET's frozen axes passes under both schemas
   (:43-63).
4. `validate_strategy` accepts the file under both schemas with the same axes (studio_strategy_settings.py:112-121).
5. `b50_tick_harness` runs OnInit on B53 and on B54, at the SET's values and at each Y axis's start and stop
   (test_hunt_sets_init.cjs:5-9). The result is the same, B53's input globals are equal, and the new inputs are at
   their defaults.
6. `WriteSet` writes the same bytes from each file's values on B54 as on B53.

### 6.3 Neutrality and behaviour proofs

- **`scripts/test_b54_no_drift.cjs`** (against 216e1622).
  - Every changed line is marked `B54` or sits in a `// B54:begin` block.
  - `REMOVED` lists the closing-paren lines (main:8705, 8749, 10213, 10220).
  - `NEW_INPUTS` is exactly the 14, in order, at the end.
  - B53's inputs are unchanged.
- **`scripts/test_b54_parity.cjs`.** Flags off against B53 on test_b51_parity.cjs:8-11's grid and single fixtures,
  with `FastSpeed_Flag` both ways, plus the default-SET WriteSet golden.
- **Native Banker parity on all 61 (ruling 3).** It runs once, on the final candidate EX5 against B53's EX5, after the
  hunt rounds drain: flags off, same window, Model 4. The deal tables (time, type, volume, price, SL, TP, profit,
  commission, swap, comment) and the export CSVs must be identical (design:127).
- **`test_b54_breakout.cjs`** with mutants.
  - **Levels:** NBar levels at bars 2..N+1; D found from bar s, including a Monday after a Sunday stub; the PriorDay
    cross and gap open; the buffer ATR found by time; NBar re-entry only after the signal reads false, with and
    without `Single_Flat_Only`.
  - **The latch** blocks a second PriorDay entry on the same D (up-cross, stop-out, dip, second up-cross) and is
    rebuilt from history after a restart.
  - **`Reverse_Seq`:** the second faded sell on D is blocked, and the down-cross opens a buy.
  - **`Random_Direction`:** for each seed, the entry times equal the strategy's, the latch blocks the second entry
    whichever side was drawn, and the sides are the reference's draws.
  - **Also:** the opposite exit, unreadable data, FastSpeed both ways, and every refusal.
  - **Mutants that must fail:** the latch removed, the latch keyed by position side, `Close[0]` read, bar 1 inside
    the level, `>=` for `>`, the Sunday stub kept, D taken at evaluation time.
- **`test_b54_orb.cjs`** with mutants.
  - **Windows:** the window edges (S in, S+R out); the M1-count rule; B8/B9; the Friday 16:55 NY cutoff; the entry
    window's end; one entry per direction per T.
  - **Restarts:** a restart mid-session after S+R, with ATR moving, keeps the day's B8/B9 verdict, and the T latch is
    rebuilt from history.
  - **Clocks:** DST dates 2007-2035 for both anchors under all three models; a London 08:00 window inside the March
    and October mismatch weeks; the Lim refusals under both DST states; the pre-2007 refusals; the live INIT_FAILED.
  - **Mutants that must fail:** atr_r read at evaluation time, London from the US rule, NY time from raw server time,
    the first Sunday in place of the second, Lim = 1320, the range built from ticks, S+R included in the range.
- **Updated tests:** `test_b50_exits` (8-term text match), `test_studio_appended_inputs`, `test_studio_ea_init_rules`,
  `test_studio_pinned_tester_inputs`, `test_studio_optimization_inputs`, `test_studio_broker_fit`,
  `test_portfolio_child_audit`, `test_studio_setting_compare`, `test_hunt_sets_init`.

## 7 Controller and catalog impact

- **Schema.** `B54_INPUTS` (the 14 names, in order) joins `APPENDED_INPUTS` and `APPENDED_GROUPS`
  (studio_strategy_settings.py:79-87). `contracts/v149` `inputs.json` and `dependencies.json` are regenerated. The init
  rules and their anchors are regenerated once, in A0 (studio_ea_init_rules.py:378-380; design:148).
- **EA Studio side.** The type lists, the optimisation-name allowlist and the defaults (GOATStudioSettingTypes.mqh:17-18,
  36, 43-44, 58-68), and the child audit's names (GOATPortfolioChildAudit.mqh:213-214, 240 show the pattern). The
  readback still accepts an omitted appended input only at its default (studio_strategy_settings.py:64-69).
- **Pinned inputs.** An older SET launched on B54 gets each optimisable new input fixed at its default
  (studio_tester_report.py:320-331; studio_optimization_inputs.py:26-39). Gate 0 proves this.
- **Axes.** Y: `BRK_TF_`, `BRK_Bars`, `BRK_Buffer_ATR`, `BRK_Once_Per_Level`, `ORB_TF_`, `ORB_Start_Minute`,
  `ORB_Range_Minutes`, `ORB_Entry_Minutes`, `ORB_Buffer_ATR`, `ORB_Min_Range_ATR`, `ORB_Max_Range_ATR`. Never axes
  (sinputs): `BRK_Mode`, `ORB_Mode`, `ORB_Clock`.
- **broker_fit.** `TF_INPUTS` (studio_broker_fit.py:127) gains `BRK_TF_` and `ORB_TF_`. `BRK_PriorDay` counts as a D1
  offset reason, and ORB being on as a clock reason, as `Clock_NewYork` is (:604-607).
- **Templates:** `single-brk-nbar`, `single-brk-pday` and `single-orb`.
  - Each sets `Engine_Single`, `RSI_Mode=RSI_Disabled` and an explicit `ATR_TF_`.
  - Each declares at most 4 axes before any run (the 81-frame grid), in its own prereg section with the B54 build pin.
  - One SET per trigger timeframe. `check_enum_ladders` admits only step-1 runs of consecutive enum values, which on
    `ENUM_MODE_TFs` (0, 1, 5, 15, 60, 240, 1440) leaves only `TF_Cur..TF_M1`. So `BRK_TF_` and `ORB_TF_` are never a
    ladder across timeframes, as in the hunt-d1 SETs.
  - They go through the app's build-set and seed loop, with no added strategy gates; only product qualification
    applies.
  - Family labels stay out of public feeds until the installed desktop's strict readers accept them.
  - controller/INPUT-REFERENCE.md gains the 14 inputs.
- **Separate work and order.**
  - The controller clock-model check is its own PR. It blocks any live or demo use of ORB or `Clock_NewYork`, and does
    not block the tester build (ruling 8).
  - There is no dashboard work in B54. It is required before any breakout SET reaches a tester-facing build
    (ruling 16).
  - The hunt stays on B51 for rounds 11 and 12, and B54 work does not preempt the tester fix or a money incident.
  - Codex credits are out, so merge gates cite 6759774556 for the spec. A0 gets its own ruling.

## 8 Rulings (Claude-Mac 6759774556)

| # | Ruling |
|---|---|
| 1 | Build identity: research-only V1.49 candidate, marker **B54**. The build does not wait for B53's evidence week. No demo or live admission until I rule separately. |
| 2 | Pool = the 61, plus anything rounds 11/12 admit before A0 merges. Commit the SETs as fixtures with a sha manifest so gate 0 runs in CI, not only on Banker. |
| 3 | Native deal-table parity on **all 61**, once, on the final candidate EX5, after the hunt rounds drain. Not a sample. |
| 4 | No OnInit refusal for `RSI_OverBS`. Templates set `RSI_Disabled`. |
| 5 | Prior day = broker D1 bar, skipping Sat/Sun bars. |
| 6 | NY plus the London anchor in change 4. |
| 7 | ORB is tester-only in B54 (INIT_FAILED on a live chart stands). |
| 8 | Build the controller clock-model check as a separate PR. It blocks any live or demo use of ORB or `Clock_NewYork`; it does not block the tester build. |
| 9 | No range-edge stop and no chase limit in V1. Exits stay Engine_Single's. |
| 10 | No Studio refusal for session vs entry window in V1. |
| 11 | One entry per direction per NY trade date T. |
| 12 | No cool-down. #246 stays open on its own. |
| 13 | Moot for NBar after change 1. Rebuild from history is right for PriorDay and ORB. |
| 14 | The M1-count rule is enough for holidays and short days. |
| 15 | One family per SET. Refuse both modes on. |
| 16 | No dashboard work in B54. Required before any breakout SET reaches a tester-facing build. |
