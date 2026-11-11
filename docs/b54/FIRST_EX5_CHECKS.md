# B54: native checks owed with the first EX5

The harness tests (`scripts/test_b54_*.cjs`) run the real MQL5 converted to JavaScript. They do not prove MT5's own
OnInit, its SET reader, `CopyRates` on real history, 32-bit integer arithmetic, or the tester. These checks run once,
on the PC, on the first B54 EX5 that Claude-Mac admits, before any B54 SET with a mode on reaches a run.

Conditions 2 and 7 of Claude-Mac's ruling 6761445724 still bind:
- no B54 identity and no EX5 off the PC;
- no SET with a mode on is run before PR B lands;
- the goatai strict readers learn the 14 inputs before any B54 SET reaches goatai;
- no demo or live admission until Claude-Mac rules.

| # | Check | Expected | Source |
|---|---|---|---|
| 1 | Native OnInit of `scripts/fixtures/b54-axes/orb-entry-int-max.set` at its three probes | current and `ORB_Entry_Minutes@start` accepted; `@stop` (2147483647) refused with `INIT_PARAMETERS_INCORRECT` and the `ORB_ENTRY_WINDOW` alert, so the bound holds before the 32-bit sum can wrap | Claude-Mac 6766613697, note 4 |
| 2 | Native OnInit of every synthetic axis SET (18) at each probe | the code and alert `axes.json` names, as `scripts/test_b54_init.cjs` checks in the harness | condition 4 |
| 3 | The ORB evidence line at OnInit, once per anchor | `GOAT signals: ORB clock: the tester trusts Server_Clock_Model=..., Server_UTC_Offset=..., ORB_Clock=...` in the tester journal | spec 4.4 |
| 4 | One ORB tester pass per anchor on real M1 history, across a US/EU mismatch week and a short day | the range read once per trade date; a short day logged as no ORB (`only m of R M1 bars`); no entry after E's end or the Friday 16:55 NY cutoff | spec 4.2-4.3, ruling 14 |
| 5 | Native Banker parity on all 61 with both families off, against B53's EX5 | identical deal tables and export CSVs | ruling 3, design:127 (Claude-Mac's) |

Check 4 needs Claude-Mac's go-ahead for a SET with a mode on. A live-chart OnInit (ORB's `INIT_FAILED`, ruling 7)
stays harness-only until Claude-Mac rules on attaching a B54 EX5 to any chart.

## How the checks run (Claude-Mac goatai#2750 6782928064 and 6782978672)

- **The binary and the terminal.** B54 `5744034e` is installed on T3 only, for the tester, by `demo_agent install-build`
  with its sha (demo, Algo off, flat, every B54 input at its default on the monitor chart). This is the chart attach above,
  granted for T3 and this build only. B51 is restored by the same verb afterwards, and both readbacks are posted.
- **The route** is the product's hold-up lane (`holdup-validate`, `-prepare`, `-start`, `-report`), one frozen SET and one
  MT5 pass per test, run through this tree's controller (its `PINNED_BUILDS` and input contract know B54).
- **The rendering rule for native probes.** Each probe is rendered from its `axes.json` entry with **`Mode_Bias=1`** and
  every `||Y` collapsed to the probe's value. The fixture SETs carry `Mode_Bias=2` with `Bias_Protocol=2`, which the EA
  refuses natively in any tester (`GOAT V1.49.mq5`, the bias block before b54-init), and the hold-up lane refuses
  (`HOLDUP_AI_BIAS_ON`). Probes with identical values (they differ only in the SET's comment line) run once.
- **The refused probes** cannot reach MT5 through the product today: every lane runs the controller's own init mirror
  first (`check_ea_init`), so `holdup-validate` answers `EA_INIT_REFUSED` with the rule. That is the mirror's answer, not
  native evidence. The native proof comes with a hold-up `expect_init_refusal: <rule>` field (its own PR, Claude-Mac
  reviews it), with `orb-entry-int-max@stop` as the case that must refuse natively. It blocks Claude-Mac's demo/live ruling,
  not the research hunt.
- **Check 4** runs `orb-ny-inside` and `orb-london-inside` at their values on EURUSD M1, Model 1, 2025-11-24 to 2026-03-28,
  then 2026-10-19 to 2026-11-07. The range evidence is deals-based (B54 logs no range that read fine): for each anchor, two
  days (an ordinary day and a mismatch-week day) chosen so one entry is a buy and one a sell. For each: the `[S, S+R)` M1
  high and low read independently from the terminal's own history, the trigger bar's close and the bar before it, and that
  it is the first `ORB_TF_` bar after S+R to cross H+buf or L-buf.
- **Owed with the next EA change to B54** (not a build of its own; before Claude-Mac's demo/live ruling, not before the
  hunt): a tester-only success line `ORB range <date>: H= L= m= of R`, once per trade date, and the "M1 history reaches
  S+R" read check below.

## Before any demo or live use of ORB

From Claude-Mac's notes on GOAT-EA#305 (6777812433). These do not block the tester build.
1. **The range read:** a `CopyRates` read with too few bars is held as a no-ORB day. In the tester that is a real short
   day. On a live chart an M1 series not yet synchronised looks the same. So the read needs a check that M1 history
   reaches S+R, and if it does not, the read must return unreadable instead.
2. **A transient unreadable input** (a bar or the ATR) loses that bar's cross, as entry A does.
