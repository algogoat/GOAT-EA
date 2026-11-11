# Spec: a breakout as a sequence's first order (N-bar / prior day on Engine_Grid)

Status: APPROVED to proceed to PR A0 by Claude-Mac (goatai#2750 6789761790, item 2), with the recommendation on each of
the 13 questions of section 8 and three additions, folded in below and listed at the head of section 8. Spec only: no
code, build, test or input change. Scope ruled in goatai#2750 6789186029: "the two existing breakout terms allowed as a
sequence's first-order signal, every new input default off, flags-off parity with B54 as gate 0." Issue: GOAT-EA#310.

Source read: GOAT-EA B54, `V1.49-BETA17-54` (`candidate-builds/beta17-B54/identity.json`: entrypoint sha256 `12fffe15...`,
header `728d7b3b...`, EX5 `5744034e...`), merge `a8c6766` (GOAT-EA#306). Line numbers are at that commit. Short names:
`main` = `GOAT V1.49.mq5`, `inputs` = `GOAT_Inputs_Definitions.mqh`, `rules` = `controller/studio_ea_init_rules.py`,
`b54` = `docs/b54/BREAKOUT_ENTRIES_SPEC.md`, `checks` = `docs/b54/FIRST_EX5_CHECKS.md`. A statement marked *(inferred)* was
reasoned from the lines cited, not read or run. Proposed build: a research-only V1.49 candidate, marker `B55` (Q9).

## 1 Purpose and non-goals

With one new switch on, an N-bar or prior-day break (B54's entry A, unchanged) opens the FIRST position of a grid
sequence. From there the existing sequence code adds, locks, trails and closes, untouched. With the switch off, every
SET behaves as on B54, refusals included.

Non-goals:
- any change to the breakout signal itself (levels, buffer, fresh cross, D);
- ORB on a sequence (stays single-only, main:5129);
- any change to grid adds, lot progression, lock profit, trailing, rescue, MLPS or the closes;
- a breakout term in the adds, in `MustCheck_*` or in the virtual promotion;
- delayed starts (`Delay_Trade`, `Delay_Trade_Live`) on a breakout sequence (refused, 3.7);
- dashboard work (b54 ruling 16 stands), any demo or live use (Q8);
- any change to main:7972 (`Trade_Friday`; addition 3, its own issue GOAT-EA#312);
- any change to an existing input, enum value, default or alert text.

## 2 Existing mechanics relied on

### 2.1 The breakout term on the single-trade engine today

- **Inputs.** `BRK_Mode` (sinput; Disabled / NBar / PriorDay), `BRK_TF_`, `BRK_Bars`, `BRK_Buffer_ATR`,
  `BRK_Once_Per_Level`: inputs:974-979, 991-995. WriteSet writes each only off its default (inputs:629-633).
- **Validation** (main:5128-5135): single engine only (5128); not with ORB (5130); `BRK_Bars` 2..500 for NBar (5131);
  buffer 0..5 (5132); PriorDay not on `TF_D1` (5133) nor on `TF_Cur` of a D1 chart (5134); `Signal_Sample_Period=M_Current`
  with a `BRK_TF_` shorter than the chart is refused (5135). Controller mirror: rules:505-535; 5134 and 5135 are
  `NOT_PORTED` (rules:705-710).
- **Signal** (`GoatBrkSignal`, main:8498-8545), on closed trigger bar s = `Shift_Sig` = 1 (main:8269):
  - an ATR above 0 is required whatever the buffer (main:8504-8505; `GoatBrkATR`, main:8473-8481, reads `ATR_MA_handle`);
  - NBar: `Close[s]` beyond the max high / min low of bars s+1..s+N, plus the buffer (main:8507-8525). Consecutive bars
    can each be a break: the previous break bar's high is inside the next channel;
  - PriorDay: a fresh cross of D's high or low: bar s closes beyond the level and bar s+1 did not (main:8526-8543). So
    it reads true for one trigger bar only. D is the newest Mon-Fri D1 bar before the one holding bar s
    (main:8484-8497); `g_GoatBrkDay` keeps D's open (main:8537).
- **Sampling.** `UpdateCurrentSignals` computes `BRK_Sig` once per new `BRK_TF_` bar and holds it for that bar
  (main:8973-8977; `INTERVAL::CheckTF`, inputs:430-435). The held value is the newest closed trigger bar's, however long
  ago the last check ran.
- **AND.** The term is the seventh of the buy condition (main:9041-9048) and of the sell condition (main:9092-9099);
  the others are RSI, EMA, ADX, BB, MACD and RSI2, each true when its mode is off. `GoatSignalAll` repeats the terms for
  the single's opposite exit (main:10560-10581, 10586-10611).
- **One single per episode.** `g_GoatSingleArmed[signal]` is cleared when a single opens (main:9064, 9072, 9114, 9122)
  and re-armed when that signal's combined condition reads false (main:9088, 9138); OnInit resets it (main:5047).
- **Prior-day latch.** With `BRK_Once_Per_Level`, one single per signal direction per D: skipped before the branches
  (main:9055, 9106), recorded after an open (main:9076, 9126; `GoatBrkLatched`, `GoatBrkLatch`, main:8549-8556). OnInit
  rebuilds it from every `DEAL_ENTRY_IN` of `MAGIC1` whose trigger bar reads the current D (main:8561-8585, called at 5151).
  Every latch line is conditioned on `Engine_Mode==Engine_Single` (main:9054-9056, 9105-9107).
- **Reverse_Seq.** A buy signal opens `Seq_Sell` at the bid and a sell signal `Seq_Buy` at the ask (main:9058-9067,
  9109-9118). The arm flag and the latch stay keyed by the SIGNAL's direction (main:9064, 9076).
- **Gates on a start.** Session `Active` and the pre-conditions (pause, `Allow_New_Sequence`, Friday, December, dashboard
  permission, clock block: main:8279, 8292); news and bias (main:9051; the bias side under `Gate_Recheck`, main:9027-9035);
  per side `DashboardEntryAllowed` (main:739-748), `Mode_Trade`, and no real or virtual sequence on that side
  (main:9061, 9069, 9111, 9119); `Allow_Opposite_Seq` (main:9064, 9072); `Single_Flat_Only` (main:9063).
- **Cadence.** The signal block runs on `Signal_Sample_Period` (inputs:671, 1591-1602); `SignalEntryTrigger` runs only
  while `Active` (main:8279-8292). In the tester `FastSpeed_Flag` is on (main:4675; off in visual mode, main:5264).
  Under the grid engine `UpdateCurrentSignals` then returns before any term while every enabled side is `Traded`
  (main:8781-8782); the single engine is exempt.

### 2.2 How a sequence starts, adds and closes today (Engine_Grid)

- **Start.** The same `SignalEntryTrigger` conditions and gates as 2.1. In the grid branch a true condition starts a
  sequence whenever that side has none: `Seq_X_Virtual.Add_Level` when `Delay_Trade` is not 0, else `Seq_X.Add_Level`
  when `Allow_Opposite_Seq` or the other side is not `Traded` (main:9065-9066, 9073-9074, 9115-9116, 9123-9124).
  - It is level-triggered. No arm flag is read: while the condition stays true and the side is free, each signal check
    can start the next sequence.
  - One real and one virtual sequence per side per chart (the guards above; `GoatGateActiveMask`, main:3344-3347). There
    is no other "max sequences" input.
- **First real order** (`SEQUENCE::Add_Level`, main:2571-2776).
  - `Delay_Trade` (default 1, inputs:691): the signal starts a virtual sequence; at level `Delay_Trade` it promotes to a
    real start only if `MustCheck_Buy/Sell` and `DashboardEntryAllowed` hold (main:2582-2603). `MustCheck_*` has no
    breakout term (main:8988-8998).
  - `Delay_Trade_Live` (default 1, inputs:692): the real sequence's first levels are untraded "Delayed" levels; the
    first order goes out at level `Delay_Trade_Live`+1 (main:2679, 2741-2764), a grid step against the signal.
  - With both 0, as in all 61 pool SETs (`scripts/fixtures/b54-pool`, tallied), the signal's own tick sends the order:
    sizes from `GetSize` (main:2605-2610), start lots (main:2618-2626), `FirstOrderGatesRefused` (main:2691),
    `OpenPosition` (main:2698), then `Active=Traded=true` and the journal lines "Sequence Started @" and "Lvl 01 ...
    Filled" (main:2716-2735).
- **Adds are by distance, not by the entry signal** (main:8318-8392, on `Sequence_Sample_Period`, inputs:1604-1611):
  a level is added when the price is a grid step beyond `Level_Last` (`GetSize(GRID_VALID)`, main:10513-10527) and
  `RSI_Mode` is off or `RSI_Sig` agrees with the position's side (main:8333, 8370). News, bias and dashboard pauses
  apply (main:8335-8345). No other entry term, and no breakout term, is read. Caps: `Max_Seq_Levels`, `Max_Seq_Trades`
  (main:2579); `CloseAtMaxLevels` (main:2766-2774).
- **Closes.** Broker SL/TP of the averaged entry and the lock level (`UpdateLockTPSL`, main:2778-2904); trailing once
  past the lock (main:8205-8219; `TrailingStoploss`, main:2923-3000); the sequence ends when its positions are flat
  (main:7322-7334; `End_Sequence`, main:867-933); MLPS (main:8311-8312, 1985-2010); stop-outs, day end and Friday
  (main:8060-8143); bias exits and Smart Rescue (call sites main:8148-8159; bodies not read); partial-retrace harvests
  (main:8326-8329).
- **ATR handles under the grid** exist only when a size input is negative, an ATR multiple (main:5033-5043). The single
  engine creates them always (main:5070-5082).

### 2.3 Why the init rule exists

The single-only scope was stated in the brief and carried into the spec. I found no argued reason and no ruling on it:
- Claude-Mac, goatai#2750 6759396135: "Brief Release for two entries on `Engine_Single`: (1) N-bar / prior-day high-low
  breakout, (2) session opening-range breakout." Its stated motive: "The catalog is spent and RR share is the problem,
  so entry diversity has to come from the EA."
- b54:14 "Two new entry families, for `Engine_Single` only"; b54:19 non-goal "grid or sequence variants (refused at
  OnInit)"; b54:270 "either family without `Engine_Single`".
- The spec ruling (GOAT-EA#302 comment 6759774556, read in full) rules 16 questions; none is about sequences. The A0,
  PR A, PR B and identity rulings (6761445724, 6764975563, 6766613697, 6776358707, 6777812433, 6778011862, 6781557904)
  contain no line about sequences or the grid (searched).

So this spec argues against a scope choice, not against a safety finding. What the rule does protect today: a breakout
SET that reaches the grid engine by mistake is refused instead of trading the grid's defaults. 3.1 keeps that.

**Ruled (6789761790, addition 2):** the single-only scope was Claude-Mac's brief choice, not a safety finding, and this
spec is the right way to lift it.

## 3 Design: the break starts a sequence

### 3.1 Input (one, in a new group appended after `ORB_Max_Range_ATR`, inputs:1004)

| # | Name | Decl | Type | Default | Axis | Meaning |
|---|---|---|---|---|---|---|
|S1|BRK_Start_Seq|sinput|bool|false|no|Breakout A starts a grid sequence: the break opens its first position|

- Group `input group "====BREAKOUT SEQUENCE START (B55)===="`; WriteSet writes `BRK_Start_Seq=true` only when on, after
  inputs:642.
- **sinput, never an axis,** as `Engine_Mode` and `BRK_Mode` are (inputs:864, 991): it selects the template's shape.
- **Why not zero inputs.** `Engine_Mode` is an appended input written only off its default (inputs:593), and MT5 fills a
  missing input with its default. Without a switch, a B54 single-breakout SET that loses its `Engine_Mode=1` line would
  stop being refused (main:5128) and trade as a grid at the grid's defaults. 3.7's delay rule would not catch it: single
  SETs carry both delays at 0 (`controller/studio_template_tools.py:215-216`). The switch keeps main:5128 as the guard
  for every SET that does not ask for a sequence, with B54's alert text and code.
- **Why not more.** Re-entry (3.5) needs no choice, and the prior-day latch reuses `BRK_Once_Per_Level`.
- `BRK_Once_Per_Level`'s declaration and comment (inputs:995, "one single per direction per day") stay byte-identical;
  `controller/INPUT-REFERENCE.md` says it also bounds sequence starts.

### 3.2 Signal

Unchanged: `GoatBrkSignal` as built (main:8498-8545), same inputs, same ranges (main:5131-5135). Two additions inside
the `brk-signal` block, neither read with the switch off: the evaluated trigger bar's open time and the level it
cleared (buffer included) are kept in globals beside `g_GoatBrkDay` (main:8454), for 3.5 and the evidence line (3.3).

### 3.3 Evaluation timing and the start

- **Init.** main:5128's condition gains `&& !BRK_Start_Seq`. With the switch on, `BRK_Mode` runs under `Engine_Grid`.
- **ATR handles.** main:5070's condition becomes "single engine OR `BRK_Start_Seq`", so the handles exist when every
  grid size is in pips. Otherwise `ATR_MA_handle` is never created (inputs:1128; main:5033-5043 is the only other
  creation) and every evaluation would end at "ATR unreadable" (main:8504-8505) *(inferred)*. Pip sizes never read ATR
  (`GoatSizeNeedsAtr`, main:10444-10455), so the handles change no size.
- **Start.** In `SignalEntryTrigger`'s grid branch the combined condition (main:9041-9048, 9092-9099) already holds the
  term. With the switch on, a start additionally needs 3.5's two skips to be clear. The order is the existing
  `Seq_X.Add_Level` (main:9066, 9074, 9116, 9124) at the ask or bid, on the first signal check after the trigger bar
  closes at which every gate holds. Never at the level, never intrabar (b54 3.3).
- **Recorded** when that block's own start made a sequence active (the test main:9078 and 9128 already make for the
  gate log): the trigger bar and, for PriorDay, D are marked for that signal direction (3.5), and one line is printed:
  `GOAT signals: BRK sequence start signal=<BUY|SELL> side=<BUY|SELL> mode=<NBar|PriorDay> bar=<trigger bar open>
  close=<its close> level=<level cleared> symbol=<symbol>`. A refused or failed order records nothing and stays
  eligible, as a refused single stays armed (main:9064).
- **Stale by construction, as today:** after a session gap the first check reads the last closed trigger bar (2.1), so
  with a long `BRK_TF_` a break can be up to one trigger bar old when it starts a sequence. The single engine has the
  same property.
- **FastSpeed.** main:8781-8782 is not changed. The skip in 3.5 is keyed by the trigger bar's time, and `BRK_Sig` is
  re-read before any start once a side is free, so the tester, a visual run and a live chart decide alike *(inferred;
  check 5 in 6.4 tests it natively)*.

### 3.4 Direction, Reverse_Seq, Allow_Opposite_Seq

- An up break is a buy signal, a down break a sell signal. `Reverse_Seq` is the existing flip (main:9058-9067,
  9109-9118), so it starts the faded sequence: an up break opens `Seq_Sell`.
- Both directions run under the existing rules. `Allow_Opposite_Seq=false` (55 of the 61 pool SETs): a break against a
  traded opposite sequence starts nothing (main:9066, 9074) and records nothing; the next break of that direction is
  free. `true`: both sequences can run at once. `Mode_Trade` restricts the POSITION's side (main:9061, 9069).
- Every mark in 3.5 is keyed by the signal's direction, as b54 3.5 item 3: under `Reverse_Seq` an up break that started
  a sell blocks a second faded sell on that bar or D, and leaves the down break free to start a buy.
- `Random_Direction` and `Single_Flat_Only` cannot be combined: both need the single engine (main:5089, 5093).

### 3.5 Re-entry after a sequence closes; the prior-day latch

Without a rule the grid would restart: `BRK_Sig` is held for the whole trigger bar (2.1), and the grid start is
level-triggered (2.2). A sequence that takes its lock profit ten minutes into an H1 break bar would start again at the
next signal check, on the same, now stale, break, and again after each close until the bar ends.

1. **One start per signal direction per trigger bar** (both modes). Once a sequence started on trigger bar s for signal
   direction d, no further sequence starts for d until `BRK_Sig` is computed from a newer trigger bar. So a new
   sequence needs a new break bar: for NBar a later bar that again closes beyond its channel, for PriorDay a new fresh
   cross. Reset at OnInit beside `GoatBrkLatchRebuild` (main:5151: a live re-init keeps EA globals).
2. **Prior-day latch, reused.** With `BRK_Once_Per_Level=true` (the default), once a sequence started for d on D, no
   further sequence starts for d until D changes: `GoatBrkLatched` / `GoatBrkLatch` as built (main:8549-8556), called
   from the grid branch when the switch is on. `false`: each fresh cross may start one (item 1 still applies).
3. **A sequence that closes and wants to reopen** on the same D and direction: refused by item 2 at the default; with
   the latch off it needs a new fresh cross. NBar: it needs a new break bar (item 1).
4. **The rebuild after a restart** (main:8561-8585) is not changed, and it counts grid adds as entries, so after a live
   restart it can latch a D on which only an add was made. It over-blocks, never under-blocks. It cannot run in B55
   (Q8: the switch is tester-only, and a tester pass starts with no deal history); the exact rule (count first orders
   only; live comments carry "Lvl 01", main:10113, 10167) is owed with any demo or live admission.

### 3.6 Interaction with existing filters and gates

- **Other entry terms:** ANDed, as today (main:9041-9048). No refusal for any combination (b54 ruling 4). Templates set
  `RSI_Mode=RSI_Disabled`: the default `RSI_OverBS` (inputs:730) would AND an oversold reading with an up break, and
  RSI also gates every add (main:8333, 8370).
- **Sessions and pauses:** unchanged (main:8279, 8292; day end and Friday, main:8110-8123; `Trade_Friday`, main:7972).
- **News, bias, dashboard, CID, feed guard, first-order gates:** unchanged (main:9051, 739-748, 2575-2578, 2691).
- **Single_* inputs** are not read under the grid (main:10588, 10619); the single's exits are refused there (main:5097, 5102).
- **Export.** The exported SET is written by `WriteSet` (main:6076-6077), so the one new line carries the switch; without
  it the export would be refused by main:5128 on its next run. `GoatBlindDesc` filters header lines only (main:4077-4090)
  and the evidence-end check compares end dates only (main:6282-6298). Neither reads `Engine_Mode` or a `BRK_*` input
  (grep of `main`).
- **Dashboard, CID, telemetry.** No dashboard or include file names `BRK_*` or `Engine_Mode` except the child audit and
  the Studio type lists (grep of `*.mqh`: `GOATPortfolioChildAudit.mqh:213, 253`, `GOATStudioSettingTypes.mqh`). Nothing
  there assumes a breakout implies a single. The run statistics treat the sequence as any grid sequence (main:888).

### 3.7 OnInit refusals (block `b55-init`, after main:5147; ported to EA_INIT_RULES unless noted)

Each returns INIT_PARAMETERS_INCORRECT unless noted. "Must refuse" and "must pass" are the two proofs the controller port
needs. Pool files are real SETs; `b54-axes` files are B54's committed synthetic SETs; `b55-axes` files are new (a valid
breakout sequence per mode, at the schema's defaults plus the lines 7 lists for the templates).

| Rule | Condition | Alert | Must refuse | Must pass |
|---|---|---|---|---|
|BRK_WITHOUT_SINGLE (changed)|`BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq`|unchanged (main:5128)|`b54-axes/brk-nbar-ends.set` with `Engine_Mode=0`|the same with `BRK_Start_Seq=true`, `Delay_Trade=0`, `Delay_Trade_Live=0`; and `brk-nbar-ends.set` itself|
|BRK_SEQ_WITHOUT_BRK|`BRK_Start_Seq && BRK_Mode==BRK_Disabled`|"Initialization Failed: BRK_Start_Seq needs a breakout mode (BRK_Mode=BRK_NBar or BRK_PriorDay)."|`b54-pool/01-EURCAD-sequence.set` plus `BRK_Start_Seq=true`|that pool file as committed, and all 61|
|BRK_SEQ_WITH_SINGLE|`BRK_Start_Seq && Engine_Mode==Engine_Single`|"Initialization Failed: BRK_Start_Seq needs the grid engine (Engine_Mode=Engine_Grid)."|`b54-axes/brk-nbar-ends.set` (a valid single, `axes.json`: current and ladder ok) plus `BRK_Start_Seq=true`|that file as committed|
|BRK_SEQ_WITH_DELAY|`BRK_Start_Seq && (Delay_Trade!=0 \|\| Delay_Trade_Live!=0)`|"Initialization Failed: BRK_Start_Seq needs Delay_Trade=0 and Delay_Trade_Live=0 (the break opens the sequence's first position)."|`b55-axes/seq-nbar-inside.set` with `Delay_Trade=1`; and with `Delay_Trade_Live=0\|\|0\|\|1\|\|1\|\|Y` (reachable through the ladder)|`b55-axes/seq-nbar-inside.set`, `seq-pday-inside.set`|
|BRK_SEQ_LIVE (INIT_FAILED, NOT_PORTED)|`BRK_Start_Seq && !MQLInfoInteger(MQL_TESTER)`|"Initialization Failed: BRK_Start_Seq is tester-only in B55; use BRK_Start_Seq=false on a live chart."|harness only, as ORB's (checks:21-22)|the same SET in the tester|

- ORB needs no rule: the switch needs `BRK_Mode` on, and `BRK_Mode` with `ORB_Mode` is refused (main:5130). ORB under the
  grid stays refused (main:5129).
- Existing rules still apply to a breakout sequence, for example RiskperSeq with `Max_Seq_Trades<=1` (main:4926).
- **Not-built refusal (A0).** Until PR A adds the start path, `BRK_Start_Seq=true` is refused outright (INIT_FAILED,
  ported), the last line of the block; PR A's commit removes it (the pattern of b54:283-288).
- **Before any new guard is trusted:** all 61 pool SETs, the 18 `b54-axes` SETs and the hunt-d1 fixtures validate
  exactly as on B54 under the new schema (set-compatibility rule 5).

### 3.8 What does not change

`GoatBrkSignal`'s levels and conditions; the six other terms; `GoatSignalAll`; `MustCheck_*`; main:8781-8782; every line
conditioned on `Engine_Single` (main:9054-9057, 9063-9064, 9076-9077 and their sell twins); `Add_Level`,
`UpdateLockTPSL`, `TrailingStoploss`, `End_Sequence`; the add block (main:8318-8407); ORB (main:8587-8739, 5129, 5136-5146).

## 4 ORB

Out of scope and unchanged: single-only (main:5129), tester-only (main:5146). The two ORB items owed "with the next EA
change to B54" (checks:45-47) are Q10.

## 5 Adds and exits (reuse of Engine_Grid, no new code)

- **Adds:** by grid distance from the last level, RSI-gated only when RSI is on (main:8333, 8370); lots by the existing
  progression (main:2629-2640).
- **Exits:** lock profit and trailing, TP, SL, MLPS, day end and Friday, bias exits, harvests: 2.2, unchanged.
- The break never closes or adds to a sequence. An opposite break only starts the opposite sequence, if allowed (3.4).

## 6 Compatibility and proof plan

### 6.1 Rules

- **Inputs.** B54's 159 header inputs keep their order, type, default and enum choices; exactly one is appended, in its
  own group, the header's last. No enum gains a value.
- **Defaults.** With `BRK_Start_Seq=false`: main:5128 refuses exactly as B54, main:5070 creates the same handles, and no
  new line in `SignalEntryTrigger` or the `brk-signal` block changes a decision.
- **Replaced lines** (listed verbatim in the no-drift guard's `REMOVED`): main:5128, main:5070, and B54's two identity
  defines. Everything else is an added, marked line.

### 6.2 Gate 0, before anything else: effective-input equality on the pool

In CI, in PR A0. A0 carries the input, the group, the WriteSet line, the regenerated `contracts/v149`, `B55_INPUTS`, the
Studio type and default, the child audit name, the init rules and their mirror, with the start path not built (3.7).

- **Baseline.** `S54`, B54's `contracts/v149` at `a8c6766`, against `S55`.
- **Pool (Q7, with addition 1).** Every file in the pool at A0's merge, not only the 61: the 61 of
  `scripts/fixtures/b54-pool` (manifest.json), every SET admitted before A0 merges, and B54's own breakout SETs with
  `BRK_Mode` on under `Engine_Single`. "Flags off" here means `BRK_Start_Seq=false`, not `BRK_Mode` off, so B54's breakout
  behaviour is inside the parity claim. The native Banker parity (6.3, 6.4 check 2) runs on the same files.
- **Per file,** b54 6.2 items 1-6 with one new name: the SET does not name it; `pinned_tester_inputs` restricted to S54's
  keys is byte-equal, and the one extra key is `BRK_Start_Seq` at its `appended_default`; `explicit_optimization_inputs`
  is unchanged (an sinput adds no line); `validate_strategy` accepts with the same axes; OnInit gives the same result on
  B54 and B55 at the SET's values and at each Y axis's ends; `WriteSet` writes the same bytes.

### 6.3 Neutrality and behaviour proofs

- **`scripts/test_b55_no_drift.cjs`** (against `a8c6766`, the pattern of `scripts/test_b54_no_drift.cjs`): every changed
  line carries `B55` or sits in a `// B55:begin` block; `REMOVED` is 6.1's list; `NEW_INPUTS` is exactly
  `['BRK_Start_Seq']`; the compile closure gains no file.
- **`scripts/test_b55_parity.cjs`.** Switch off against B54 on `test_b51_parity.cjs`'s grid and single fixtures and on
  B54's breakout and ORB tick fixtures, `FastSpeed_Flag` both ways; the default-SET WriteSet golden; and B54's refusal:
  `BRK_Mode` on under the grid with the switch off gives main:5128's code and alert.
- **Native Banker parity,** once, on the final candidate EX5 against B54's EX5 `5744034e`: every pool file of 6.2, switch
  off, same window, Model 4; deal tables and export CSVs identical (b54 ruling 3).
- **`scripts/test_b55_brk_sequence.cjs`** with mutants (b50_tick_harness, as `test_b54_breakout.cjs`):
  - a break opens level 1 of a grid sequence at the ask/bid on the first check after the trigger bar; adds follow at
    grid distance with no break; the lock, trail and flat-end run as on a non-breakout sequence with the same sizes;
  - 3.5 item 1: a sequence closed inside its break bar does not restart on it; the next break bar starts one; a
    refused first order records nothing and the same bar can still start;
  - 3.5 item 2: PriorDay up-cross, sequence closes, dip, second up-cross the same D is latched (`false` trades it);
  - `Reverse_Seq`: the up break starts a sell, the second faded sell is blocked, the down break starts a buy;
  - `Allow_Opposite_Seq` both ways; `Mode_Trade` long-only and short-only; pip-only sizes still read the buffer's ATR;
  - `FastSpeed_Flag` both ways give the same orders; the single engine's fixtures are untouched by the switch;
  - every refusal of 3.7, each next to its accepted neighbour;
  - **mutants that must fail:** the bar skip removed; the skip keyed by position side; the latch not called under the
    grid; a start recorded on a refused order; the term read by the add block; `ORB_Mode` let through main:5129;
    main:5128 dropped (not just narrowed); the ATR handles not created for pip sizes; the delay rule dropped.
- **Updated tests:** `test_b54_no_drift` (its baseline becomes a commit proof, as `test_b51_no_drift` did for B53),
  `test_b54_init` and `controller/test_b54_init.py` (unchanged verdicts), `test_studio_appended_inputs`,
  `test_studio_ea_init_rules`, `test_studio_pinned_tester_inputs`, `test_studio_optimization_inputs`,
  `test_portfolio_child_audit`, `test_studio_setting_compare`, `test_hunt_sets_init`, `test_studio_catchup`.

### 6.4 First-EX5 checks (become `docs/b55/FIRST_EX5_CHECKS.md` at assembly)

Run once on the PC, on the first B55 EX5 Claude-Mac admits, through the hold-up lane, one frozen SET and one pass per
test, rendered with `Mode_Bias=1` (checks:29-34). No SET with the switch on runs before PR A lands and Claude-Mac says go.

| # | Check | Expected |
|---|---|---|
|1|Native OnInit of each `b55-axes` SET at each probe|the code and alert `axes.json` names. Refused probes need the hold-up `expect_init_refusal` field, still owed (checks:35-39; not in `controller/studio_holdup.py` today); until then they are the mirror's answer|
|2|Native Banker parity, switch off, against B54's EX5, all pool files of 6.2|identical deal tables and export CSVs|
|3|Four tester passes on real history: NBar and PriorDay, each as built and with `Reverse_Seq`; M1 chart, `BRK_TF_` above M1, `Active_Time_Weekday=SESS_ALL`, no news or bias, `RSI_Disabled`, Model 1 (as checks:40); symbol and window named in the go-ahead|journal: each `BRK sequence start` line is followed in the same second by "Sequence Started @" and "Lvl 01 ... Filled" on the side it names; no "Lvl 01" without one; no `BRK sequence start` beside a "Lvl 02"+ line; at most one per signal direction per trigger bar, and for PriorDay per D; every "Sequence Ended" reason is an existing one|
|4|Independent replay of check 3's entries: a script outside the EA recomputes the break bars from the terminal's own bar history by b54 3.2|(a) every start's bar, signal and level equal a replayed break, and its deal lies in the bar after it; (b) every replayed break on which the journal shows that side free (and the other side flat when `Allow_Opposite_Seq=false`) has a start; (c) every add is at least one grid step beyond the previous level|
|5|One SET of check 3 again in visual mode (`FastSpeed_Flag` off, main:5264), a two-week window|the same deal table as the normal pass|
|6|One pass with every size in pips|at least one start, and no "ATR unreadable" line after warm-up|
|7|One EXPORT run of a breakout-sequence SET|the exported SET carries `BRK_Start_Seq=true`; validate-set and the catch-up check accept it|

## 7 Controller and catalog impact (list)

- **Schema.** `B55_INPUTS = ('BRK_Start_Seq',)` joins `APPENDED_INPUTS` and `APPENDED_GROUPS`
  (`controller/studio_strategy_settings.py:82-92`); `contracts/v149` `inputs.json` and `dependencies.json` regenerated.
- **Init-rule port** (rules:505-509 changed, three added, one `NOT_PORTED`), each with 3.7's two proofs.
  - **Trap:** `applicable_rules` drops a rule that names an input of an absent appended group (rules:814-822). If
    `BRK_WITHOUT_SINGLE` simply gains `BRK_Start_Seq`, a B54 schema loses the rule and fails open. The port must keep
    B54's condition for a schema without the B55 group. Third proof: B54's `inputs.json` (`a8c6766`) still refuses
    `BRK_Mode` on under the grid.
- **EA Studio side.** `GOATStudioSettingTypes.mqh`: type `bool` (as :42), appended default `false` (as :83), not in the
  optimisation names (:52). `GOATPortfolioChildAudit.mqh`: one name, value `false` (as :250-263).
- **Pinned and explicit inputs.** An older SET gets `BRK_Start_Seq=false` pinned; no explicit optimisation line (an
  sinput is never an axis). `controller/studio_catchup.py:731-740` already accepts an omitted appended input at its default.
- **Axes for the hunt.** Unchanged: `BRK_TF_`, `BRK_Bars`, `BRK_Buffer_ATR`, `BRK_Once_Per_Level` plus the grid's own.
  One SET per trigger timeframe (`check_enum_ladders`, b54:411-413).
- **Strategy settings.** `check_risk_sizing` already requires `Max_Seq_Trades>=2` for RiskperSeq under the grid
  (`controller/studio_strategy_settings.py:296`; main:4926). `broker_fit` already flags `BRK_PriorDay` and `BRK_TF_`
  (`controller/studio_broker_fit.py:127-130, 610-616`): no change.
- **Templates** `seq-brk-nbar` and `seq-brk-pday`, each as built and reversed, through build-set and the seed loop.
  - Built from the sequence starter, which keeps `Delay_Trade=1` and `Delay_Trade_Live=1`
    (`controller/studio_template_tools.py:218-223`): the template must set `Delay_Trade=0`, `Delay_Trade_Live=0` and
    `Delay_Lots_Add=false`, as the single starter does (:215-217), or the EA refuses it.
  - `Engine_Mode` stays `Engine_Grid`; `BRK_Start_Seq=true`; `RSI_Mode=RSI_Disabled`; an explicit `ATR_TF_`; at most
    4 axes, declared before any run in their own prereg section with the B55 build pin.
- **Build rows.** `candidate-builds/beta17-B55/` (identity, compile receipt, README) and the `PINNED_BUILDS` row
  (`controller/studio_installed_build.py:42-56`); `controller/INPUT-REFERENCE.md` and `TEMPLATE-WORKFLOW.md`.
- **goatai.** The strict readers learn `BRK_Start_Seq` before any B55 SET reaches goatai (checks:10); family labels stay
  out of public feeds until the installed desktop accepts them (b54:416).
- **Register rows:** the restart rebuild under a sequence (3.5 item 4) and the tester-only refusal, both tied to the
  demo/live ruling; dashboard work (b54 ruling 16).

## 8 Questions, decided (recommendation first)

**Ruling (Claude-Mac, goatai#2750 6789761790, item 2):** GOAT-EA#311 is approved to proceed to PR A0 with the
recommendation on all 13 questions below, and three additions:

1. **Gate-0 and native pool** = every file in the pool at A0's merge, not only the 61 (Q7; 6.2, 6.3, 6.4 check 2).
2. **The single-only scope** of B54 was Claude-Mac's brief choice, not a safety finding, and this spec is the right way to
   lift it (2.3).
3. **No change to main:7972 in B55.** It behaves as `==5`, and changing it alters every file's trading, so it gets its own
   issue (GOAT-EA#312) and its own parity read (section 9).

Each question is decided as its recommendation reads (the first sentence of its item); each item ends with the decision.

1. **One sinput `BRK_Start_Seq`, or no input (the engine alone decides)?** One. It keeps main:5128 guarding a breakout
   SET that lost its `Engine_Mode` line (3.1). Zero inputs would need no schema change, but turns that mistake into a
   live grid.
   **Decided as recommended (6789761790).**
2. **Re-entry.** (b) one start per signal direction per trigger bar (3.5 item 1). (a) Nothing, the grid's rule today:
   restarts on a stale break for the rest of a long trigger bar. (c) The single's episode rule (false, then true): needs
   signals kept current under FastSpeed (main:8781) or the tester and a visual run diverge, and, since the flag re-arms
   only where `SignalEntryTrigger` runs (main:9088; in session, main:8279-8292), a new break after a session gap can
   read as the old episode *(inferred)*. (b) is keyed by bar time, so it cannot depend on the run mode.
   **Decided as recommended (6789761790).**
3. **Prior-day latch: reuse `BRK_Once_Per_Level` for sequences?** Yes, no new input. At the default: at most one
   sequence start per signal direction per D.
   **Decided as recommended (6789761790).**
4. **Refuse `Delay_Trade` / `Delay_Trade_Live` not 0?** Refuse. Otherwise the first real order is not on the break
   (2.2), `MustCheck_*` decides the promotion without the term, and the latch would have to count virtual starts the
   history cannot show. All 61 pool SETs have both at 0.
   **Decided as recommended (6789761790).**
5. **Other entry terms: AND as today, no refusal?** Yes, as b54 ruling 4. Templates set `RSI_Disabled`.
   **Decided as recommended (6789761790).**
6. **Pip-only grid sizes: create the ATR handles (3.3), or refuse?** Create: one condition widened, no new rule, and
   `BRK_Buffer_ATR` keeps one meaning on both engines.
   **Decided as recommended (6789761790).**
7. **Gate-0 and native pool.** The 61, plus every SET admitted before A0 merges, plus B54's breakout SETs with a mode on
   under the single engine (the round 13a wave 3 pilot's eight). The last group is what proves B54's own behaviour
   unchanged.
   **Decided as recommended, with addition 1: every file in the pool at A0's merge, not only the 61 (6789761790).**
8. **Tester-only in B55?** Yes: refuse the switch on a live chart (INIT_FAILED), as ORB (main:5146). Then the rebuild's
   over-latch (3.5 item 4) cannot run, and it is fixed with the live admission, not now.
   **Decided as recommended (6789761790).**
9. **Identity.** Research-only V1.49 candidate `V1.49-BETA17-55`, marker `B55`, baseline B54 `a8c6766`; no demo or live
   admission until ruled; B53 stays the experiments' final build.
   **Decided as recommended (6789761790).**
10. **ORB's owed items** (success line, "M1 history reaches S+R" read check; checks:45-47 say "with the next EA change
    to B54"). Not in B55's PRs: the read check changes ORB-on behaviour and needs its own parity proof. A separate
    small PR, in this build only if you want it there.
    **Decided as recommended (6789761790).**
11. **The evidence line at each start (3.3).** Include it. B54 logged nothing on the healthy path and its range check
    had to be rebuilt from deals (checks:40-44).
    **Decided as recommended (6789761790).**
12. **PR split.** A0 (input, WriteSet, rules and mirror, gate 0, no-drift, switch refused as not built), then A (the
    start path, 3.5, tests, parity). Spec PR to you first, as GOAT-EA#302.
    **Decided as recommended (6789761790).**
13. **Dashboard.** b54 ruling 16 stands: none in B55, required before any breakout SET reaches a tester-facing build.
    **Decided as recommended (6789761790).**

## 9 Found while reading (not part of this change)

- main:7972: `stm_cur.day_of_week==5 || stm_cur.day_of_week==5`, the same operand twice (`Trade_Friday`). Harmless as
  written; the second was probably meant to be another day. **Ruled (6789761790, addition 3):** not changed in B55. It
  behaves as `==5`, and changing it alters every file's trading, so it has its own issue (GOAT-EA#312) and its own parity
  read.
- main:8774 and 8967: `cond ? "BUY" : cond2 ? "SELL" : "NEUTRAL"+" ("+value+")"`. The value is appended to NEUTRAL only
  (operator precedence). Panel text, no trading effect.
- `controller/contracts/v149/dependencies.json`: no rule ties `BRK_*` or `ORB_*` inputs to their mode (its coverage says
  "indicator_mode_gates_only"), so an axis on a disabled family's input is not flagged. b54:396 says the file was
  regenerated; only its two hashes changed.
- main:8561-8585: the latch rebuild counts every `MAGIC1` entry. Correct for a single; under a sequence it counts adds
  (3.5 item 4).

## 10 Not verified

- Nothing was compiled or run: every statement about B55 is design, and the *(inferred)* marks (3.3 twice, Q2) are
  reasoning from cited lines.
- Whether B54's own native parity against B53 on the 61 (checks:19) has been run.
- The round 13a wave 3 pilot SETs and the 41 provisional files (GOAT-EA#310): not in this tree, not read.
- Where the catalog templates and the register live (no `single-brk-*` file exists in this tree outside b54).
- The bodies of the bias-exit and Smart Rescue functions (main:7442-7535, 2012-2158): call sites only.
- `docs/b50/B50_ALPHA_DESIGN.md` was not re-read; b54's citations of it are taken as given.
