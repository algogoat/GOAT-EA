B54 (`V1.49-BETA17-54`) is the **research build for breakout entries**: B53 (the final build, `V1.49-BETA17-53`,
`candidate-builds/beta17-B53/`) plus entry A (N-bar / prior-day breakout, GOAT-EA#304) and entry B (the session opening-range
breakout, GOAT-EA#305) on `Engine_Single`, per `docs/b54/BREAKOUT_ENTRIES_SPEC.md`. **Research only** (Claude-Mac goatai#2750
6781557904): it supersedes no candidate, B53 stays the experiments' final build, there is no demo or live admission until
Claude-Mac rules, and ORB stays tester-only (it refuses a live chart at OnInit, ruling 7).

**Build**
- `GOAT_BUILD_ID` is `V1.49-BETA17-54`, marker `B54` (commit dbcbcf7: the two defines and the tests bound to them).
- **Compiled once** from dbcbcf7a with the pinned portable MetaEditor (sha256 `cf2750bd…`), Idle, outside every terminal folder,
  B47's include root copied hash-equal: `Result: 0 errors, 0 warnings, 35384 ms elapsed, cpu='X64 Regular'`, 42-file closure.
- `GOAT V1.49.ex5`: sha256 **`5744034eeb1085f0fd6b3e40bf93e4395c8149f7527151e3e87489582e00cad5`**, 2,701,902 bytes. MetaEditor
  output is not byte-reproducible, so this is the one binary to use.
- Entrypoint `GOAT V1.49.mq5` sha256 `12fffe15…` (pinned in `controller/contracts/v149/dependencies.json`), input header
  `728d7b3b…`: B53's 145 header inputs unchanged and in order, then the 14 B54 inputs (159).
- Against B53 the closure differs in exactly five files (`GOAT V1.49.mq5`, `GOAT_Inputs_Definitions.mqh`, `GOAT_NYClock.mqh`,
  `GOATPortfolioChildAudit.mqh`, `GOATStudioSettingTypes.mqh`). Every changed line carries the marker `B54` or sits in a marked
  block, and the two identity lines are the one unmarked change (`scripts/test_b54_no_drift.cjs`).
- `controller/studio_installed_build.py` pins this binary as `V1.49-BETA17-54`. B53's row stays.

**With every new input at its default it trades as B53.** Harness proof: `scripts/test_b54_parity.cjs` (flags-off parity on every
fixture, FastSpeed both ways) and gate 0 on the 61 pool SETs (`scripts/test_b54_gate0.cjs`, `controller/test_b54_gate0.py`).
Native proof is owed: Banker parity on all 61 pool SETs, trade for trade against B53 (ruling 3; Claude-Mac rules on it).

**Not done.** No native qualification, no externals manifest, no admission row. The root `GOAT V1.49.ex5` is unchanged.
The checks owed on this binary, before any SET with a mode on is run, are `docs/b54/FIRST_EX5_CHECKS.md`:
1. native OnInit of `scripts/fixtures/b54-axes/orb-entry-int-max.set` at its three probes;
2. native OnInit of every synthetic axis SET at each probe;
3. the ORB evidence line at OnInit, once per anchor;
4. one ORB tester pass per anchor on real M1 history (a mode on: needs Claude-Mac's go-ahead);
5. native Banker parity on all 61 with both families off.

**Flags.** Every B54 input defaults off (`BRK_Mode=BRK_Disabled`, `ORB_Mode=ORB_Disabled`). B53's experiment flags and their
reasons are unchanged (`candidate-builds/beta17-B53/README.md`).
