B53 (`V1.49-BETA17-53`) is the final build: B51 (B50-alpha with GOAT-EA#292, `claude-mac/b50-alpha`) merged with B49b
and GOAT-EA#290 (`claude-pc/b49b` 808ff728) on `claude-pc/b51-live`, plus the fixes from two independent reads of that merge
(goatai#2750 6705041540), GOAT-EA#294 (controller only) and Codex's three fixes on GOAT-EA#296. **Not yet qualified:** no
tester or chart run of this binary, no admission row; live use is demo only, after the drills below.

**Known history.** B52 (`V1.49-BETA17-52`, binary `e108b09a`, `candidate-builds/beta17-B52/`) was this build before Codex's
fixes. **It refuses every RiskperSeq single at OnInit** (B49b F6, Codex GOAT-EA#296 4502334956), so it is superseded and
must never be installed; `studio_installed_build` pins no row for it (an installed `e108b09a` is `INSTALLED_BUILD_UNKNOWN`).
B53 is a new identity, not B52 rebuilt, because a binary is never pinned under an older build's name.

**Build**
- `GOAT_BUILD_ID` is `V1.49-BETA17-53`, marker `B53`. Against the re-read tree (`claude-pc/b51-live` 1391c78) the compile
  closure differs in those two defines only; `studio_equivalence` normalizes exactly those two.
- **Compiled once** from d2e4be46 with the pinned portable MetaEditor (sha256 `cf2750bd…`), Idle, outside every
  terminal folder, B47's include root copied hash-equal: `Result: 0 errors, 0 warnings, 33392 ms elapsed, cpu='X64 Regular'`, 42-file closure.
- `GOAT V1.49.ex5`: sha256 **`4733511303cf216f8ec513556abc89f492176063001dd77c8405c79a995cc068`**, 2,678,442 bytes. MetaEditor output is not
  byte-reproducible, so this is the one binary to use.
- Entrypoint `GOAT V1.49.mq5` sha256 `8c7d2899…` (pinned in `controller/contracts/v149/dependencies.json`),
  input header `b5c462ed…` (B50-alpha's 127 inputs, B49b's 9, then B51's 9: 145).
- `controller/studio_installed_build.py` pins this binary as `V1.49-BETA17-53`.

**Not done.** No native qualification, no externals manifest, no admission row. The root `GOAT V1.49.ex5` is unchanged.

**The review fixes (B52-marked lines in `GOAT V1.49.mq5`; tests `scripts/test_b52_review.cjs` and its mutations)**
- P1: the New York clock is refused on every live chart at OnInit (INIT_FAILED), whatever the feed guard. Its day end,
  Friday close and no-tick exits are not yet integrated with B49b's live protections. The tester runs it as before.
  **Must be tested before any live use.**
- P2, a single still open at a restart before the account has synchronized (OnInit defers it until the account settles
  as a demo, `g_GoatSingleAccountPending`):
  - OnInit's manage-only counts it as held (single engine only; the grid engine keeps B49b's rule);
  - while the deferral lasts and the position is not adopted, the state file is not rewritten, not even by OnDeinit's
    forced flush. The hold is the deferral itself, not the account's current reading, so it lasts to the adoption on
    the timer path too. Tested with the timer first and with a tick first;
  - once adopted it takes back its own state section;
  - after the settling, nothing holds a write: an orphan position with a disconnect still flushes.
- P2: `Gate_AtFirstOrder` reads B50's entry block (rollover, live CLOCK MISMATCH): `clock_blocked`.
- P3: `Random_Direction` with `Gate_AtFirstOrder` is refused at OnInit (tester pair).

**Codex on GOAT-EA#296 (B53's fixes over B52; tests `scripts/test_b52_review.cjs`, `test_b49b_f5.cjs`, `test_b49b_f6.cjs`,
`test_hunt_sets_init.cjs`)**
- 4502334956: B49b F6's OnInit refusal (`Mode_Lots=RiskperSeq` with `Max_Seq_Trades<=1`) is the grid engine's only. A single
  sizes RiskperSeq from its own stop, so every hunt single (prereg section 2) inits; B52 refused them all.
- 4502419410: under `Gate_AtFirstOrder` the first-order gate exempts a sequence once a real order opened (`GuardRealStarted`),
  not once `Traded` (a ladder whose first levels were below the volume minimum traded nothing real).
- 4502419403: `GoatPreTradeRefusalCode` (one use) is inlined at its caller (AGENTS.md one-line-helper rule).
- The method fix: `scripts/test_hunt_sets_init.cjs` replays the 11 preregistered D1 hunt design SETs (byte-identical
  fixtures) through the harness's real OnInit, at their values and at each optimized axis's start and stop.

**The experiment's flags.** The rule: turn on only what is live-only or a live safety fix with no effect in the
tester, so the hunt's files carry over by `build_migration` re-test (reproduced) and need no new evidence.

| Input | Setting | Why |
|---|---|---|
| `Fix_FeedGuard` | **On** | Claude-Mac's ruling. Live only (`GoatFeedGuardLive`): no entry on a stale feed, server-time session ends, the owed Friday close. The lag fault of Exp 02/03. |
| `Fix_TickLoad` | Off | Claude-Mac's ruling. It is live-only (`GoatTickLoadLive`), so the rule above would allow it, but it changes live exit and trail timing (partial, break-even and trail at most once a second), which the experiment must not change. |
| `Fix_ClosePath` | **On**, if `build_migration` reproduces | Not live-gated: both clauses also act in the tester. A requested end waits until the positions are flat (`EndDeferredUntilFlat`), and the tester can refuse a close outside the symbol's trade session. A trailed or rescued stop is never moved back, and no stop is deleted by a computed SL of 0 (`UpdateLockTPSL`). So it is on only once `build_migration` shows each hunt file reproduces with it; any file that does not stays Off. |
| `Fix_MoneyVolume` | Off | It changes sizing (money per price unit) in the tester too, so hunt files would need new evidence. |
| `Fix_Clock` | Off | It changes OnTick's second/minute/day blocks in the tester too. Same reason. |
| `Gate_Recheck` | `Gate_Legacy` | `Gate_AtFirstOrder` changes tester entries, and the benchmark refuses it. |
| `Max_Spread_Points`, `Min_Margin_Level_PC` | 0 (off) | The caps also act in the tester. Use them only after a broker-fit decision, as their own arm. |
| `Diag_TickTiming` | Off | Read-only diagnostic. It may be turned on for a lag investigation. |
| `Ledger_Mode` | each SET's own | A single with a partial close needs `Ledger_PositionJoin`, which OnInit enforces. The hunt designs carry their value. |

**Drills (demo, before go-live)**
1. Feed guard, single, on a live demo chart: let the feed go stale past `GOAT_FEED_AGE_GUARD_S` (or disconnect). The
   feed guard itself must hold: the journal says so and no single opens. When the feed is fresh again with the signal
   still true, it opens once. The node test holds entries by hand in the tester, where the feed guard is always off, so
   only this drill proves the guard.
2. Feed guard, single: a Friday close owed past the cutoff is closed after Monday's open, and no single opens before
   that.
3. Close path, single: a refused close of a single is retried until the position is flat, and the sequence never ends
   while it is open.
4. F4's Friday close closes a single with no tick arriving (Claude-Mac). This is the failure B49b set out to fix.
5. B52 P2: a restart while a single is open and before the account has synchronized.
   - First, from the journal: the terminal lists the position before "terminal synchronized". Both protections read
     `PositionsTotal()`; if it is empty before sync, manage-only still fails at init and the flush is not held.
   - OnInit counts it as held (manage-only with an expired or refused licence).
   - The state file is not rewritten before the adoption (compare its time and contents).
   - After the first demo reading, the single is adopted and its state section is back.
   - Run it once on a quiet market (no tick until well after sync, so the timer adopts) and once with ticks.
6. Not in this experiment: the New York clock is refused on every live chart (P1), whatever the feed guard. Before any
   live use it must be tested with the feed guard on and off, and under `Fix_ClosePath`.
