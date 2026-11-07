B52 (to be `V1.49-BETA17-52`; the ID, marker, compile and pin come at its assembly) is the final build: B50-alpha
with GOAT-EA#292 (B51, `claude-mac/b50-alpha` 4fc885cf) merged with B49b and GOAT-EA#290 (`claude-pc/b49b` 808ff728),
on `claude-pc/b51-live`, plus the fixes from the independent read of that merge (goatai#2750 6705041540) and from the
second read of those fixes. **Draft notes:** nothing here is compiled, qualified or admitted yet.

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
