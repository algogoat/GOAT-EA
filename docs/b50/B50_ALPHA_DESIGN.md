# B50 design note: the single-trade engine (B50-alpha now, B50-beta later)

Source: `origin/codex/v148-research-planning` @ 65fde12 (B49a). `main` means `GOAT V1.49.mq5` and `inputs` means `GOAT_Inputs_Definitions.mqh`. I read the clone only and changed nothing.

## 1. Architecture

**A single is a one-level SEQUENCE.** Every single runs inside `Seq_Buy`/`Seq_Sell`. That way it inherits, without new code:
- the ledger (main:1503-1575);
- MLPS (main:1848);
- restart adoption and persistence (main:1586-1800);
- the direction and CID guards, tracing and the dashboard GVs;
- the end on the broker SL/TP through `OnTradeTransaction` (main:5978-5992).

**The entry path is new, and `Add_Level` is not reused.** `Add_Level` (main:2338) cannot send a first order when `Delay_Trade_Live>=1` (main:2416, default 1). Signals also go through virtual sequences when `Delay_Trade>0` (main:7273-7283, default 1). So a new free function, `GoatSingleOpen(SEQUENCE &s,double price)`, copies `Add_Level`'s real-order branch (main:2420-2485) in the same order:
1. `GoatCidGuardAddFrozen`, then `ManageOnlyFrozen`;
2. tracing, then `OpenPosition`, then `GoatDirectionGuardResult` (a denial resets the sizes);
3. `Active=Traded`, `Sequences++`, `TradeLevels[0]`;
4. `LedgerAddPosition` and `AccumulateSequenceDealPL`, then `PersistStart`, then `UpdateLockTPSL`.

**Sizes at start:**
- `Size_SL = Single_SL_ATR×ATR`, where ATR is the closed bar (shift 1) of `ATR_MA_handle`, read into a local buffer so `ATR_Buf` and `GetSize` state never change.
- `Size_TP = Single_TP_R×Size_SL` if `Single_TP_R>0`, else `Single_TP_ATR×ATR`, else 0.
- `Size_Lock = Size_TSL = Size_Grid = 0`. `UpdateLockTPSL` then sets `Level_Lock` to 999999 (buy) or 0 (sell) (main:2582-2586), so the trailing at main:6823-6834 never fires. Trailing comes back in B50-beta.

**Lots:**
- `RiskperSeq`: `Risk / (Size_SL × s.PriceValuePerPointPerLot())`, floored to the volume step and capped at the volume max. If the result is below the volume minimum, the trade is refused and logged; it is never rounded up past the risk.
- `FixedLots` and `ScaledLots`: as at main:2371-2372.
- No ATR (a read under 1), or a stop inside `SYMBOL_TRADE_STOPS_LEVEL` plus the spread: the trade is refused.

**Signal pipeline.** Signals are levels computed in `UpdateCurrentSignals` (main:7056), and every `*_TF_` ladder works on D1 through `INTERVAL::CheckTF` (inputs:426). Whatever drives a grid start drives a single, through the same gating in `SignalEntryTrigger` (main:7259: news, bias, `DashboardEntryAllowed`, `Mode_Trade`, `Reverse_Seq`, `Allow_Opposite_Seq`, the gate log). There is one position per signal episode: a per-direction flag `g_GoatSingleArmed[2]` is cleared on open and re-armed when that direction's combined signal reads false.

**Do not touch:** `Add_Level`, `UpdateLockTPSL`, `TrailingStoploss`, `closeLots*`, the lot builders and solver, `GetSize` (main:7839), `EnforceSequenceMLPS`, the ledger, persist and adopt code, `OpenPosition` (main:7455), `OnTradeTransaction`, the session parse (main:3950-4030), and the existing `WriteSet` lines.

## 2. Inputs (B50-alpha)

D1 first: append `TF_D1=1440` after inputs:111 and add `case TF_D1: return PERIOD_D1;` after inputs:123.

The new inputs are appended after `Ledger_Mode` (inputs:783) under `input group "====SINGLE / CLOCK (B50)===="`. `WriteSet` writes each one only when it differs from its default, after inputs:585, following the Ledger pattern.

| # | Name | Type | Default | Meaning |
|---|---|---|---|---|
|1|Engine_Mode|sinput ENUM_ENGINE_MODE{Engine_Grid=0,Engine_Single=1}|Engine_Grid|Engine|
|2|Single_SL_ATR|input double|0.0|Stop in ATR multiples (must be >0 when Single)|
|3|Single_TP_ATR|input double|0.0|TP in ATR multiples (0 = off)|
|4|Single_TP_R|input double|0.0|TP in R; wins over 3 when >0|
|5|Single_Exit_Opposite|input bool|false|Opposite-signal exit|
|6|Single_Time_Stop_Bars|input int|0|Time stop after N bars (0 = off)|
|7|Single_Time_Stop_TF|input ENUM_MODE_TFs|TF_Cur|Bar timeframe for 6 (H1 = hours)|
|8|Clock_Mode|sinput ENUM_CLOCK_MODE{Clock_Server=0,Clock_NewYork=1}|Clock_Server|Session clock|
|9|Server_Clock_Model|sinput{ServerClock_NYClose=0,ServerClock_Fixed=1,ServerClock_EUDST=2}|NYClose|Broker clock model (read only when 8 or 12 is on)|
|10|Server_UTC_Offset|sinput int|2|Winter offset for models 1 and 2|
|11|NY_Session|input string|"09:30-16:00"|NY window; start>end crosses midnight|
|12|Rollover_Block_Minutes|input int|0|No new entries within ±N minutes of 17:00 NY|

Inputs 2-7, 11 and 12 go into `GoatStudioOptimizationNames` (GOATStudioSettingTypes.mqh:17) and the type allowlist (:13).

## 3. Algorithms and touch points

**D1.** `TF2TF` gets the case above. `controller/studio_broker_fit.py:128,593` must treat `TF_D1` like `TF_H4` (its bars depend on the broker's offset).

**New York clock** (new `GOAT_NYClock.mqh`, pure functions):
- US DST runs from the second Sunday of March at 07:00 UTC to the first Sunday of November at 06:00 UTC. EU DST runs from the last Sunday of March to the last Sunday of October, both at 01:00 UTC.
- `NYClose` model: NY = server − 7 h all year, because the broker follows US DST. No DST maths is needed.
- `Fixed` model: UTC = server − offset. `EUDST` model: the same, with 1 h more while EU DST is active.
- For both, NY = UTC − (US DST ? 4 : 5) h.
- The ambiguous transition hours fall on a Sunday while the market is shut.

**Live self-check (live only).** Once a minute, compare the derived UTC of `TimeTradeServer()` with `TimeGMT()`. A gap over 90 s sets `g_GoatEntryBlocked` and puts "CLOCK MISMATCH" on the panel, so the EA fails closed. The tester's `TimeGMT` is the server time, so the tester trusts the model, and the evidence must record it.

**Session in NY time.** The window counts on Mon-Fri NY dates, taken from the date the session starts. `GoatNYClockApply(k)` sets `Active`, `InActive` and `Sequence_Pause_Close` in the same way as main:6594-6600. It also recomputes `Sequence_New_Friday` from the NY weekday and runs the NY day-end and Friday actions in place of main:6736 and main:6743.

**Rollover.** Any new entry, grid or single, is blocked while |NY − 17:00| < N minutes.

**Time stop.** On each new bar of `Single_Time_Stop_TF`, read `POSITION_TIME` of `TradeLevels[0].ticket`, which survives restarts. If `iBarShift(…, entry, false) >= N`, call `CloseSequencePositions("Single Exit: time stop")`. A result of −1 means no close: the position keeps its SL, and the EA logs once.

**Opposite-signal exit.** `GoatSignalAll(op)` copies the six-term condition at main:7262-7268 (a test asserts the text matches). The exit fires when the opposite signal is true and the position's own signal is false, so range modes, where both can be true, never exit at once; under `Reverse_Seq` the two are swapped. It runs on the signal cadence before the entry check, inside or outside the session. If `checked` is false it calls `UpdateCurrentSignals` first and sets `checked` (passed by reference).

**Latent bug fixed here.** main:7058 returns early in optimization (`FastSpeed_Flag`) once a single is traded. Without a fix, the opposite exit would never fire in optimization but would fire in visual runs. Insert before that line: `if(Engine_Mode!=Engine_Single || !Single_Exit_Opposite)`.

## 4. PR split for B50-alpha (target Sun 11-01)

**A0 scaffold** (one agent, merged first). It owns every shared line, with stub functions so A1-A3 only fill in function bodies:
- the inputs file: enums, `TF_D1`, `TF2TF`, the inputs, `WriteSet`, and the globals `g_GoatSingleArmed`, `g_GoatEntryBlocked`, `g_GoatNYStartMin`/`EndMin`;
- `GOATStudioSettingTypes.mqh`, and `GOATPortfolioChildAudit.mqh:199-208` (a child that carries the new inputs while its SET does not must hold the defaults);
- the controller: `APPENDED_INPUTS`, a regenerated `contracts/v149`, the init rules plus their anchors, `broker_fit`;
- `scripts/test_b50_no_drift.cjs`, and `scripts/b50_tick_harness.cjs`, which converts the real `GoatTickBody` region from main:6878 to the end, plus `SignalEntryTrigger`, `UpdateCurrentSignals`, `GetSize` and the SEQUENCE methods, against modelled positions, deals and indicator buffers.

A0's edits in main:
- an OnInit block after main:4427: the refusals (`Single_SL_ATR<=0` in Single mode; a negative TP, bars or rollover value; a bad `NY_Session`; an offset outside −12..14), the NY window parse, and the ATR handles when Single mode is on (the existing gate at main:4418 creates them only for an ATR-mode grid);
- insert `GoatNYClockApply(k)` after main:6607;
- prefix `Clock_Mode!=Clock_NewYork &&` on main:6736 and main:6743, and add `&&!g_GoatEntryBlocked` to main:6904 (all three listed in REMOVED);
- insert `GoatSingleSignalExits(checked)` after main:6889 and `GoatSingleTimeStop()` before main:6918;
- insert `if(Engine_Mode==Engine_Single) LastBuyTradeSignal=false; else` before main:6937, and the sell twin before main:6973;
- stubs: `GoatSingleOpen` after main:7333, the exit stubs before main:7927, and an include of the stub `GOAT_NYClock.mqh` at the end of the file.

**Parallel PRs, each on top of A0:**

| PR | Owns | Test files |
|---|---|---|
| A1 single core | `GoatSingleOpen` body; Single branches in `SignalEntryTrigger` (main:7273-7283, 7305-7316) | `test_b50_single.cjs` + mutations |
| A2 clock | `GOAT_NYClock.mqh` only | `test_b50_clock.cjs` + mutations |
| A3 exits | `GoatSignalAll`, `GoatSingleSignalExits`, `GoatSingleTimeStop`; the line before main:7058 | `test_b50_exits.cjs` + mutations |

**A4 assembly:** build ID, marker `B50`, identity, compile receipt, binary, PINNED_BUILDS row.

**Merge order:** A0, then A1, A2, A3 (each rebased; there is no shared hunk), then A4.

**Gates every PR must pass:**
- MetaEditor compile with 0 errors and **0 warnings**, checked in the log, together with the `.ex5` timestamp.
- `test_b50_no_drift`: outside CHANGED, everything is byte-identical to 65fde12. Every change carries the `B50` marker. NEW_INPUTS is exactly items 1-12 in order. B49a's 115 inputs are unchanged, except that each `ENUM_MODE_TFs` input gains exactly `{"TF_D1":1440}`.
- Flags-off OnTick parity: the harness runs B49a's region (65fde12) and the PR's region on the same fixtures and asserts identical `OrderSend`, `PositionModify` and close call traces. Fixtures: ATR-mode grid, `Delay_Trade` virtual entries, CumPartial, PeakSmart, SmartRescue, Day/Friday close, `News_Close`, an adopted basket, with `FastSpeed_Flag` both true and false.

**Per-PR flags-on tests (each also kills its mutants):**
- **A1:**
  - Expected: lots ≤ Risk/(SL×value); refusal below the volume minimum; no grid add; no virtual leg; re-arm on the signal edge; the ledger and persist hooks are called.
  - Mutants: rounding up, ATR read from shift 0, a dropped arm flag, the grid guard removed, the CID-freeze check skipped, `TP_R` ignored.
- **A2:**
  - Expected: DST dates 2007-2035 against a fixed list; NYClose identity; a midnight-crossing window; a symmetric rollover window; a fault blocks entries live but never in the tester.
  - Mutants: first Sunday in place of the second, offset 6, a midnight-crossing window treated as empty, the tester check inverted.
- **A3:**
  - Expected: the exit fires under `FastSpeed_Flag=true`; exits survive a restart (POSITION_TIME); no exit when both signals are true.
  - Mutants: the 7058 bypass removed, `Reverse_Seq` ignored, close on −1, hours counted from `TimeCurrent()`.

**A0 and A4 also need:**
- `WriteSet` golden: a default SET written by B50 is byte-identical to B49a's;
- `test_studio_appended_inputs`, `test_studio_ea_init_rules`, `test_portfolio_child_audit` and `test_studio_setting_compare` pass;
- native Banker parity: the B50 binary against B49a (`e43ed98e`) on the 48 templates plus sampled exports, flags off, with identical deal tables (time, type, volume, price, SL, TP, profit, commission, swap, comment) and export CSVs (magic normalised). A1-A3 each run an 8-template subset of the fixture families above.

## 5. B50-beta (later, sketched only)

- **Break-even and trailing as separate inputs** (`Single_BE_ATR`, `Single_Trail_Start_ATR`, `Single_Trail_ATR`) in a new modify function. `TrailingStoploss` stays untouched. Plus the session-close flag.
- **Random-direction benchmark.** Direction = `hash(Random_Seed, signal-bar time) & 1`, using a stateless hash (splitmix64). It must not use `MathRand`: `MathSrand(GetTickCount())` (main:4451) and the tester's magic (main:4463) consume that stream. Replaying the same bar gives the same flip in any tick model.
- **E3 exposure guard** in `OpenPosition`, before `GoatDirectionGuardBegin` (main:7508, main:7562):
  - It scans every account position. Its risk is |open − SL| × volume × tick value; a position with no SL counts as unbounded, so the guard denies.
  - Legs come from `DashboardSymbolCurrencies` and `DashboardCurrencySideForTrade` (main:201, main:211), with JPY, AUD and NZD as one group.
  - Limits: ≤2% per file (magic to file via the child GVs), ≤6% per leg and direction.
  - Any failed read denies (a new `LastRetCode`), so it fails closed.
- **Grid reducers, vote and smooth mode.**

## 6. Risks and open questions

1. **`TF_D1` changes the contract.** It adds an enum choice to 7 existing inputs. That keeps old SETs valid, but it breaks the current no-drift rule, so the test needs the explicit allowance above. The alternative is a separate enum.
2. **Wrong broker model in the tester.** The tester has no `TimeGMT`, so a wrong model shifts every NY session silently. The Studio should refuse `Clock_NewYork` unless the model was verified live.
3. **MLPS can fire slightly early.** The P/L includes the entry commission, so MLPS at −Risk (main:1862) fires just before the broker stop. Options: use `Sequence_MLPS_Hard_Close=false` for singles, or accept it.
4. **SmartRescue on a single.** It moves the stop to rescue levels (main:6103/6150). Should Single mode force HardClose?
5. **Session rules to confirm:** opposite exits outside the session; one position per signal episode; whether a session starting Sunday evening counts. Netting accounts are not supported.
6. **Version.** Keep this as a V1.49 candidate build (research-only) or call it V1.50 (AGENTS.md, Version Targeting)?
7. **Init-rule anchors.** Only A0 may touch OnInit or any line above it, so the anchors in `studio_ea_init_rules.py` are regenerated once.

### Critical files for implementation
- /Users/vincenteger/Documents/GOAT Development Worktrees/GOAT-EA-ro/GOAT V1.49.mq5
- /Users/vincenteger/Documents/GOAT Development Worktrees/GOAT-EA-ro/GOAT_Inputs_Definitions.mqh
- /Users/vincenteger/Documents/GOAT Development Worktrees/GOAT-EA-ro/scripts/test_b49a_no_drift.cjs
- /Users/vincenteger/Documents/GOAT Development Worktrees/GOAT-EA-ro/controller/studio_strategy_settings.py
- /Users/vincenteger/Documents/GOAT Development Worktrees/GOAT-EA-ro/controller/studio_ea_init_rules.py
## 7. Claude-Mac rulings (2026-10-27 04:4xZ), binding
1. `TF_D1` is appended to `ENUM_MODE_TFs`, with the explicit no-drift allowance (each existing TF input gains exactly `{"TF_D1":1440}`). No separate enum.
2. The Studio/controller refuses `Clock_Mode=Clock_NewYork` for a broker whose `Server_Clock_Model` hasn't been verified live (a recorded live self-check pass). The evidence records the model.
3. MLPS firing early by the entry commission on singles is accepted for alpha, and documented. MLPS code is not touched.
4. `Engine_Single` together with SmartRescue on is an init refusal: incompatible, with a logged reason.
5. Session rules: opposite exits run outside the session; one position per signal episode; a session belongs to its start date's NY weekday; netting is not supported (refused).
6. Version: a V1.49 candidate build `V1.49-BETA17-50`, marker `B50`, research-only. V1.50 is reserved for a public release.
7. Only A0 touches OnInit or any line above it. A0 regenerates the init-rule anchors once.
8. Input order: the B50-alpha inputs (items 1–12 above) are appended right after `Ledger_Mode`. B49b's inputs come after them.
9. The compile gate (MetaEditor, 0 errors and 0 warnings) runs on Release's PC for every PR head. The Mac builders run the node/python suites plus mutants.

## 8. B50-beta-1 (B51): binding rulings and the choices made

Rulings: Claude-Mac, goatai#2587 comment 6501903173. Research-only, tester-only code. With every new input at its
default, the build trades exactly as B50-alpha (`V1.49-BETA17-50`, source `32df4eb`, EX5 `8364a371`). Every changed line
carries the marker `B51` or sits in a `// B51:begin` ... `// B51:end` block; `scripts/test_b51_no_drift.cjs` guards the
tree against B50-alpha, and `scripts/test_b50_no_drift.cjs` now proves B50-alpha's own commit.

**Build identity.** Unchanged here (`V1.49-BETA17-50`, marker `B50`). As A4 (#278) did for B50, the assembly PR stamps the
build: proposed `V1.49-BETA17-51`, marker `B51` (the marker the lines already carry).

**Inputs.** One new group, `input group "====SINGLE EXITS / BENCHMARK (B50-beta)===="`, appended at the very end of the
inputs (after B50-alpha's). B49b's inputs slot in between B50-alpha's and these when the lines merge; names are what
matter. Append-only: no existing input moves or changes. `WriteSet` writes each one only when it differs from its default,
so a default SET is B50-alpha's bytes (`scripts/test_b51_parity.cjs`). The controller lists them as their own appended
group (`B51_INPUTS`, `APPENDED_GROUPS`): a B50-alpha schema carries none of their rules, a B51 schema that lost one fails
closed.

| # | Name | Type | Default | PR | Axis | Meaning |
|---|---|---|---|---|---|---|
|1|Random_Direction|sinput bool|false|1a|no|Random-direction benchmark (Engine_Single, tester only)|
|2|Random_Seed|input int|1|1a|yes|Benchmark seed (a seed sweep is an optimization over it)|

### 8.1 beta-1a: the random-direction benchmark

Revised after the review of GOAT-EA#286 (P1-1, P1-2, P2-3, P2-4, P3-5; coordinator rulings). The first version let a
gated draw stay armed and draw again on every bar: with `Allow_Opposite_Seq` on it hedged the running single (sides
0101..., late entries), and its opposite-signal exit read the side, so an against-signal single died in about 60 s.

**The moment.** Only when `Engine_Mode==Engine_Single && Random_Direction`. `SignalEntryTrigger` hands each signal
episode (after the signal's news and bias gates) to `GoatSingleRandomEntry(signal)`, which opens only when B50-alpha's
own branch would open for that signal: alpha's gates for alpha's trade side T of the signal (T = signal, or its
opposite under `Reverse_Seq`): the arm flag, `DashboardEntryAllowed(T)`, no virtual sequence on T, no running single of
this signal (alpha's `!Seq_T.Active`), and `Allow_Opposite_Seq` or no running single of the other signal (alpha's
`!Seq_other.Traded`). A running single counts for the signal of the episode that opened it (`g_GoatRandomSignal`), not
for its side, so these are alpha's gates whatever side the coin gave, and the benchmark's moments are alpha's.

**The draw.** Made once per episode, at that moment, never redrawn:

```
state = (ulong)seed XOR (ulong)bar XOR ((ulong)signal << 62)
z = state + 0x9E3779B97F4A7C15                (mod 2^64)
z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9      (mod 2^64)
z = (z ^ (z >> 27)) * 0x94D049BB133111EB      (mod 2^64)
z = z ^ (z >> 31)
side = z & 1                                  (0 = buy, 1 = sell)
```

One step of SplitMix64 (Vigna's `splitmix64.c`; its first output for the state 0 is `0xE220A8397B1DCDAF`). `bar` is
the episode-start signal bar: the open time of `iTime(_Symbol, PERIOD_CURRENT, Shift_Sig)` (the chart's closed bar) at
the episode's first signal check, recorded in `SignalEntryTrigger` (`g_GoatRandomEpisodeBar[signal]`) and cleared on the
signal's false edge. So a moment late in an episode (alpha's single of the last episode ended inside it) still draws from
the episode's first bar, a refused order is retried with the same draw, and a buy-signal and a sell-signal episode that
start on the same bar draw independently (the signal bit). The same episode draws the same side in every tick model and
on every replay. `MathRand` and `MathSrand` are never called. Each 64-bit constant is built from its two 32-bit halves.

**The drawn side's own gates.** `DashboardEntryAllowed(side)`, no virtual and no running sequence on that side
(alpha's `Allow_Opposite_Seq` gate above already implies the other side's). If they block it, the episode is consumed
with no trade, counted (`g_GoatRandomGated`) and logged `B51 random: drawn side gated (signal, drawn, bar, count)`:
no redraw, no waiting. With `Allow_Opposite_Seq` on, that happens when a sell-signal episode draws the side a running
buy-signal single holds (alpha hedges there). So the benchmark's entry moments are a subset of alpha's, and its trade
count is at most alpha's, on the same market path while exits match. Caveat: an exit that depends on the side (the
stop, the TP) can end a random single earlier or later than alpha's, and the moments that follow can then differ.

**Exits.** `GoatSingleSignalExits` reads, for a random single, the signal of the episode that opened it: it exits when
the other signal reads true and its own reads false, exactly when alpha's single of that episode would. The time stop
is the single's own (by bars). `Reverse_Seq` does not change the side (a reversed coin flip is still a coin flip); it
only decides alpha's trade side T for the gates above.

**OnInit refusals** (block `b51-init`, after `b50-init`; it also resets the B51 globals for a live re-init):
`Random_Direction` without `Engine_Single`; a negative `Random_Seed` (no question of how MQL sign-extends a negative int
into a ulong); `Random_Direction` with `Mode_Trade` other than `Long_and_Short` (a coin flip needs both sides; review
P2-3) (each INIT_PARAMETERS_INCORRECT, ported to `EA_INIT_RULES`); `Random_Direction` outside the strategy tester
(INIT_FAILED, `NOT_PORTED`: run context). The later OnInit refusal anchors in `controller/studio_ea_init_rules.py` are
regenerated with the block.

**Tests.** `scripts/test_b51_random.cjs` (+ `test_b51_random_mutations.cjs`) compares the benchmark, the tree's
flags-off run and B50-alpha on the same ticks, on the hourly, overlap (the review's exp3), late-moment, opposite-exit
(exp1, and one where the opposite signal comes), buy-then-sell (`Allow_Opposite_Seq` on and off) and M5-chart fixtures:
entry moments are alpha's (or a subset by exactly the gated episodes, each counted and logged), exits are alpha's, the
sides are the reference's draws for each episode's first bar and signal, never forced; plus the SplitMix64 goldens, the
tree's function equal to a BigInt reference (`scripts/b51_random_reference.cjs`, MQL's ulong rules), two tick models
and a replay, no `MathRand`/`MathSrand`, the drawn side's gates, flags off identical to B50-alpha, and the refusals.
`scripts/test_b51_parity.cjs`: the flags-off parity with B50-alpha on grid fixtures (with the adopted basket and both
day-end/Friday mixes) and single fixtures, and the WriteSet golden.
