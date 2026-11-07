B52 (to be `V1.49-BETA17-52`; the ID, marker, compile and pin come at its assembly) is the final build: B50-alpha
with GOAT-EA#292 (B51, `claude-mac/b50-alpha` 4fc885cf) merged with B49b and GOAT-EA#290 (`claude-pc/b49b` 808ff728),
on `claude-pc/b51-live`, plus the fixes from the independent read of that merge (goatai#2750 6705041540). **Draft
notes:** nothing here is compiled, qualified or admitted yet.

**The review fixes (B52-marked lines in `GOAT V1.49.mq5`; tests `scripts/test_b52_review.cjs` and its mutations)**
- P1: the New York clock is refused on a live chart at OnInit (INIT_FAILED). Its day end, Friday close and no-tick exits
  are not yet integrated with B49b's live protections. The tester runs it as before. **Must be tested before any live use.**
- P2: an open single adopted after OnInit (it waits for a demo reading) is held by OnInit's manage-only, the state file
  is not rewritten while it waits, and once adopted it takes back its own state section.
- P2: `Gate_AtFirstOrder` reads B50's entry block (rollover, live CLOCK MISMATCH): `clock_blocked`.
- P3: `Random_Direction` with `Gate_AtFirstOrder` is refused at OnInit (tester pair).

**The experiment's flags.** The rule: turn on only what is live-only or a live safety fix with no effect in the
tester, so the hunt's files carry over by `build_migration` re-test (reproduced) and need no new evidence.

| Input | Setting | Why |
|---|---|---|
| `Fix_FeedGuard` | **On** | Claude-Mac's ruling. Live only (`GoatFeedGuardLive`): no entry on a stale feed, server-time session ends, the owed Friday close. The lag fault of Exp 02/03. |
| `Fix_TickLoad` | Off | Claude-Mac's ruling. It changes exit and trail timing (partial, break-even and trail at most once a second). |
| `Fix_ClosePath` | **On** | A failed close no longer ends a sequence with positions open, and a stop is never loosened. In the tester closes do not fail, so it should reproduce; `build_migration` must show that per file before the experiment uses it. |
| `Fix_MoneyVolume` | Off | It changes sizing (money per price unit) in the tester too, so hunt files would need new evidence. |
| `Fix_Clock` | Off | It changes OnTick's second/minute/day blocks in the tester too. Same reason. |
| `Gate_Recheck` | `Gate_Legacy` | `Gate_AtFirstOrder` changes tester entries, and the benchmark refuses it. |
| `Max_Spread_Points`, `Min_Margin_Level_PC` | 0 (off) | The caps also act in the tester. Use them only after a broker-fit decision, as their own arm. |
| `Diag_TickTiming` | Off | Read-only diagnostic. It may be turned on for a lag investigation. |
| `Ledger_Mode` | each SET's own | A single with a partial close needs `Ledger_PositionJoin`, which OnInit enforces. The hunt designs carry their value. |

**Drills (demo, before go-live)**
1. Feed guard, single: with the feed held stale, no single opens; when it is fresh again with the signal still true, it
   opens once.
2. Feed guard, single: a Friday close owed past the cutoff is closed after Monday's open, and no single opens before
   that.
3. Close path, single: a refused close of a single is retried until the position is flat, and the sequence never ends
   while it is open.
4. F4's Friday close closes a single with no tick arriving (Claude-Mac). This is the failure B49b set out to fix.
5. B52 P2: a restart while a single is open and before the account has synchronized. Checks: OnInit counts it as held
   (manage-only with an expired or refused licence); the state file is not rewritten while it waits; after the first
   demo reading the single is adopted and its state section is back.
6. Not in this experiment: the New York clock with the feed guard is refused live (P1). It must be tested before any
   live use, as must a single under `Fix_ClosePath` with the New York clock.
