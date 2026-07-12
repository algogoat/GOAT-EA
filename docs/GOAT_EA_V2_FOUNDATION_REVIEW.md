# GOAT2 V2.0 Foundation — Independent Code Review

**Reviewer:** Claude "Fable" (architecture/review seat)
**Date:** 2026-07-11
**Subject:** commit `95c4692` "Build fresh GOAT2 V2.0 foundation" — 37 files, ~14,600 insertions
**Method:** line-by-line review of all ~12,500 new MQL5 lines by six parallel deep-review passes (domain/identity/inputs; StateDB; execution core vs V1.42 originals; safety kernel/gateway; portfolio manager; receipts/support/tests), followed by adversarial re-verification of every CRITICAL finding directly in source; independent re-run of both static gates; independent recompile of both binaries; hash verification of all documented evidence values.
**Standard:** `docs/GOAT_EA_V2_BLUEPRINT.md` v1.1 + `docs/V2_PHASE1_ACCEPTANCE.md` + AGENTS.md capital-critical rules.

---

## 1. Verdict

**Architecture: approved. Candidate: not yet certifiable — and Codex's own status doc already says so correctly.**

The foundation is genuinely strong capital-critical engineering: the five-layer separation is real, the single-`OrderSend` choke point holds under static audit, durable-intent-before-send is enforced with no memory-only exception, the event journal is hash-chained and transactional, the compile-time new-risk lock is airtight (independently traced by two reviewers — no path enables new risk in this build), the V1 exposure-math port is term-by-term faithful in its static formulas, and `docs/V2_BUILD_STATUS.md` is honest rather than promotional — every "unproven/open" self-assessment I attacked held up.

However, the review found **2 CRITICAL and ~14 HIGH defects**, concentrated in exactly the places unit-type review always finds them: the reconciliation edges, the wiring between correct modules, and contract machinery that exists but is not enforced. The two criticals form a dangerous pair: the system's **active de-risking arm cannot execute at all** (§3.1), and an **uncertain broker outcome can journal a live position out of management forever** (§3.2). Nearly every other defect fails *safe* (toward false quarantine / refusing to trade rather than uncontrolled exposure) — the failure-direction discipline is real.

Because `GOAT2_PHASE1_EXECUTION_CERTIFIED=0` physically prevents new exposure, **no defect in this list can lose money in the committed build**. Severity ratings below are for the certification path.

## 2. Independent verification of Codex's claims

| Claim | My verification | Result |
|---|---|---|
| Source SHA-256 `BBB99B5B…39C0B3F` / binary `118604FD…0A371E3` | Recomputed via Get-FileHash | **MATCH** |
| Binary newer than sources | Timestamps checked | **PASS** |
| Product compiles 0 errors / 0 warnings | Independently recompiled via designated wrapper | **PASS** (0/0) |
| Unit-test EA compiles 0/0 | Independently recompiled | **PASS** (0/0) |
| Boundary audit (gateway-only mutations, no V1 includes, no secrets) | Re-ran `check_goat2_boundaries.ps1 -RequireGateway` | **PASS** (1 mutation hit, 0 bypasses) |
| Input/schema sync 80=80 | Re-ran `check_goat2_input_schema.py` | **PASS** |
| No V1 artifact changed | `git diff HEAD~1` over all V1 files | **CLEAN** |
| V1 reference hashes in `v1_42_reference_manifest.json` | Spot-checked V1.42 source hash | **MATCH** |
| Unit tests never executed | No result artifact anywhere in Common\Files | **CONFIRMED — top open gate** |

Committed binaries were restored to their committed state after my recompiles.

## 3. CRITICAL findings (must fix before any certification work)

### 3.1 The forced-reduction path is dead — every CLOSE/PARTIAL_CLOSE is rejected by the gateway
**`v2/PortfolioManager.mqh:1832-1845` (SubmitNextReduction) × `v2/BrokerGateway.mqh:157-162` (PrepareAction). VERIFIED IN SOURCE.**
`PrepareAction` requires `action.position_id != 0` and equal to live `POSITION_IDENTIFIER` for CLOSE/PARTIAL_CLOSE/MODIFY, else fails `POSITION_JOURNAL_LINEAGE_MISMATCH`. `SubmitNextReduction` populates `position_ticket` but never `position_id` (the only assignment in the manager is in `ModifyProtection`, line 1960). Consequence: equity-floor breach, drawdown limit, MLPS hard close, retrace harvesting, and sequence-ending closes **all fail at the gateway**; `reduction_remaining` never drains; the only real protection left is broker-hosted SL/TP. The current tests cannot catch this (kernel is tested directly with synthetic actions; `PrepareAction` never sees a live position; no positions ever open under the compile lock). **Fix:** one line (`action.position_id=target.position_id;`) plus a test that exercises `PrepareAction` against a real tester position. This must also become a golden-path integration test (open → force-reduce → verify broker flat).

### 3.2 Uncertain entry outcome manufactures SEQUENCE_ENDED while exposure may exist
**`v2/PortfolioManager.mqh:1695-1700` × `v2/BrokerGateway.mqh:595-683` × `v2/Domain.mqh:407-413`. VERIFIED IN SOURCE.**
A timeout-class retcode is correctly classified `V2_GATEWAY_RECONCILE_REQUIRED` ("may have executed"). But `SubmitLevel` treats every non-SUBMITTED status identically: standing volume is still zero, so it calls `EndSequence("ENTRY_NOT_SUBMITTED:…")` — journaling ENDED while the order may fill seconds later. When the fill arrives: `Domain.CanApply` rejects fills on ENDED (`SEQUENCE_NOT_MANAGEABLE`) → permanent re-failing quarantine loop; `ManageProtection` early-returns on ENDED → **no basket TP/SL sync, no equity floor, no MLPS for the live position**; with `V2_StopLossSize=0` the position is naked. Aggravated by **3.3**. **Fix:** on RECONCILE_REQUIRED hold the sequence open (or quarantine it) pending intent settlement; only a *proven* rejection may end it — the code already documents this exact principle for the crash window (comment at 1542-1545) and violates it on the synchronous path.

### 3.3 (HIGH, feeds 3.2) `OrderSend==false` with timeout/connection retcode classified as clean rejection
**`v2/BrokerGateway.mqh:595-601`.** `uncertain = submitted && RetcodeRequiresReconciliation(...)` — the reconciliation lane exists but is only reachable when `submitted==true`. `OrderSend` returning `false` with `TRADE_RETCODE_TIMEOUT` records `V2_INTENT_REJECTED` with no reconciliation and no MANAGE_ONLY, opening an orphaned-fill window. **Fix:** `uncertain = (submitted || RetcodeRequiresReconciliation(retcode))`, disambiguating retcode 0 via `GetLastError()`.

## 4. HIGH findings

**Persistence/recovery (StateDB):**
- **4.1 Lease acquisition may reject every durable Open** — `v2/StateDB.mqh:252-265`: sentinel opened `FILE_BIN` without `FILE_ANSI` (Unicode mode); the guard `FileWriteString(...)!=StringLen(...)` likely fails when the write is counted in bytes (2×chars). Fail-closed (EA won't start in FULL_DURABLE) but a hard availability defect. **Must be empirically verified on a terminal before anything else in the live plan; fix by opening `FILE_ANSI` or accepting `>0`.**
- **4.2 `m_writable` fail-closed latch bypassed by most write methods** — `SaveSequenceProjection`/`SaveLevelProjection`/`StoreTradeObservation`/8 more (`StateDB.mqh:1536` etc.) don't check the latch; after a poisoned commit, an auto-commit projection write can reference a rolled-back event → `PROJECTION_JOURNAL_LINEAGE_MISMATCH` at next open → DB permanently un-openable (see 4.3). **Fix:** gate every mutating method on `m_open && m_writable`.
- **4.3 No migration, repair, or member-scoped quarantine** — `StateDB.mqh:815-912, 1022-1056`: any schema/integrity trip hard-fails `Open()` forever; blueprint §4's "quarantine affected members, don't contaminate unrelated" and "versioned migrations" are unimplemented. One damaged row = permanent loss of even persisted manage-only context.
- **4.4 O(N) whole-journal SHA re-verification on every Open** — `StateDB.mqh:815-859` over an unbounded journal: restart latency grows without bound; positions unmanaged during verification. Needs checkpointed/incremental verification.

**Manager/reconciliation:**
- **4.5 History-pool corruption in `ReconcileUnsettledIntents`** — `PortfolioManager.mqh:1465-1506`: the deal loop's own callees (`HistoryDealSelect`, nested `HistorySelect`) reset the history pool mid-iteration → deals skipped → false `RECOVERY_STANDING_VOLUME_MISMATCH` quarantine during exactly the crash-recovery scenario the system exists for. **Fix:** snapshot deal tickets first.
- **4.6 Async-rejected entry wedges flat-ACTIVE forever** — `PortfolioManager.mqh:1565-1578, 2126-2183`: intent settles REJECTED, nothing ends the sequence; `MaybeAddLevel` and `MaybeStartNewSequence` both blocked → EA silently stops trading until restart.
- **4.7 TOCTOU in continuous broker match** — `PortfolioManager.mqh:2266-2271`: ring-only pending check races the terminal's async position table (a normal server-side TP fill during OnTimer can trigger `RECOVERY_STANDING_VOLUME_MISMATCH`); also deterministic variant when >128 observations back up. Quarantine has no exit path (4.8). **Fix:** require zero unprocessed DB observations + mismatch persistence across two passes.
- **4.8 Operational state is a one-way ratchet; DEGRADED/HALTED unreachable** — `PortfolioManager.mqh:275-287`: transient causes (telemetry capacity, one failed high-water write) drop to MANAGE_ONLY permanently; no re-promotion path; two blueprint states never assigned. Combined with 4.7, routine events become indefinite silent outages.

**Execution core (port fidelity):**
- **4.9 PeakSmart retrace trigger burned while underwater** — `v2/Core_Sequence.mqh:789` + `PortfolioManager.mqh:2105-2107` vs V1:1370-1371: V1 holds the trigger armed until P/L>0 then harvests; V2 advances the pointer and permanently skips that de-risking close. Behavioral regression on a claimed-PORT crown jewel. The planner's single `0.0` return conflates V1's three distinct outcomes (advance/hold/advance) — needs a tri-state result.
- **4.10 `lock_flexibility>1` fails the whole basket build** — `Core_Sequence.mqh:668-671` vs V1's neutral treatment (V1:1711-1715): a migrated V1 preset with flexibility >1 means Lock/TP/SL are never placed/updated on open baskets. Clamp instead of reject.

**Gateway/kernel:**
- **4.11 Full close denied below `volume_min`** — `BrokerGateway.mqh:82-86,173-181`: dust/spec-change positions can never be flattened through the gateway — a risk-monotonicity violation (exit treated like an entry).
- **4.12 Divergent price normalizers can zero SL/TP** — `SafetyKernel.mqh:148-153` returns 0.0 when `tick_size<=0` while the gateway falls back to `SYMBOL_POINT`; Execute overwrites the request with kernel-normalized values (`BrokerGateway.mqh:542-546`) — a protective modify becomes protection *removal* on broken symbol metadata; `OrderCheck` also runs pre-overwrite (margin evidence computed for a different request). One shared normalizer with fallback.

**Contract/evidence layer:**
- **4.13 Order-intent state machine is ornamental** — `Domain.mqh:625-677`: `CV2OrderIntentMachine` is used only by tests; all 10 production status writes are direct field assignments — illegal transitions (FILLED→CANCELLED) are unpreventable, corrupting the evidence trail certification depends on. Route all writes through `Apply()`.
- **4.14 Broker-server-time vs UTC conflation** — all timestamps derive from `TimeCurrent()` (server time, typically UTC+2/3) while blueprint §8 mandates UTC and `IntelligenceBus.HasValidState` compares `published_at <= now` — a wired-in future lookahead bug for Phase 2 and a receipts-corpus contamination issue now. Fix before receipts accumulate.
- **4.15 UTF-8-truncating hash helpers** — `Receipts.mqh:107,123` (`StringToCharArray` capped at `StringLen`): any non-ASCII content (broker comments!) is hashed truncated → external verifiers compute different SHA-256s → the audit chain breaks exactly when used. `Identity.mqh:14-29` already does it correctly; unify.
- **4.16 Test suite cannot measure the gates it exists for** — tests never executed (no PASS artifact — top open gate, honestly reported); zero receipt/manifest/telemetry/feature coverage; lot-ladder tests are cap-only against one fixture (a materially wrong progression passes); kernel `Evaluate` has 2 cases; promotion gate #6 (identical-run receipt hashes) has no instrument at all.

## 5. MEDIUM findings (summary — full details in the six per-module review transcripts)

- **StateDB:** intent-status regressions permitted (no monotonic lattice); lease heartbeat on raw `TimeLocal()` (DST/NTP step blocks takeover ~1h; `lease_stale_seconds` unvalidated); journal-vs-projection atomicity is caller convention; outbox-exhausted reported as configured-OK.
- **Manager:** `FindPersistedDealEvent` full-journal scan per deal on the tick path (O(N), unbounded) and dedup disabled in REDUCED mode (double-apply on retry); per-tick SQL SELECT + per-extreme durable writes (optimization-throughput tax vs §4.1 intent); first failing work item starves housekeeping/watchdogs and drops consumed bar/housekeeping tokens; stale unsettled intent from a non-current sequence bricks every restart; quarantine event can collide state_version when recovery aborts early; `mlps_used` mutated outside the persistence path.
- **Core:** disabled GRID_MIN loses V1's 0.5×ATR floor (stacked-levels geometry V1 never produces); pip conversion differs 10× on 2-digit symbols vs V1 (settings-migration trap — document or translate); retrace close volumes floor instead of nearest-round (systematically under-harvests vs V1); compat MLPS overshoot quirk faithfully ported (must never wire into live sizing — corrected engine verified as the live path); `OrderCalcProfit` fed sub-step volumes (broker-dependent hard-fail); Grid_Factor==0 silently rewritten to a third geometry; Lock_Factor count basis levels-vs-trades drift.
- **Kernel/gateway:** CANCEL protectiveness trusts a caller flag (spoofable classification); error budget unweighted/reset-by-any-accept/volatile across restarts; `SEQUENCE_LOSS_LIMIT` honor-system (kernel never computes independent worst case; field semantically overloaded); stops/freeze levels captured but never validated; session/feed/license context hardcoded `true` (scaffold; note: **V2 currently has no expiry gate at all**); close-of-hedged-side is always RISK_DECREASE (gross-lots model — trap for the V1 rescue port); peak-equity ratchet ignores deposits/withdrawals.
- **Domain/inputs:** ENDED sequence resurrectable to QUARANTINED (wildcard transition → no-new-sequences deadlock until restart); `V2_RUN_DISABLED` behaviorally = ManageOnly (mislabeled; still mutates broker state); magic "collision-checked" claim unenforced at runtime (`MagicCollides` dead code); `V2_SEQ_REDUCE_ONLY` unreachable; fills with UNKNOWN/NEUTRAL risk_effect journal-but-mutate-nothing (latent hole); operational-state changes only `Print`ed — never journaled/receipted (forensics gap vs §8).
- **Support:** receipt kinds `SEQ_START_SUPPRESSED`/`LEVEL_SKIP`/`SHADOW_DECISION` declared never emitted (golden-master first-divergence will be blind to negative decisions); `Features` `source_age_msc` hardcoded 0 (violates §9's no-silent-freshness rule); Policy SHADOW behaviorally identical to DISABLED while receipts label it shadow (overstates evidence); serializer hot-path costs (O(n²) escape; double Build/SHA per receipt; triple outbox aggregate scans); manifest `createdAtMsc` inside its own hash (live "same experiment ⇒ same manifest" becomes attach-time-sensitive — decide and document).

Plus ~20 LOW items (dead alternate ReceiptId scheme, stale `cases.json` requires list, HUD hit-test coupling, runtime-gated-not-compiled-out UI, silent-zero environment hashing, second-resolution `_msc` fields, schema looseness, `TimeCurrent()`-frozen weekend timeouts, benign double-Shutdown, one-way new-risk flag propagation, broker-profile "verified" substring heuristic, etc.) — enumerated in the per-module transcripts.

## 6. What verified as genuinely excellent

- **Compile lock airtight** — traced independently by two reviewers across every path: gateway initialized `enable_new_risk=false` hardcoded; the sole `SetNewRiskEnabled(true)` call is macro-guarded; non-NORMAL states clear the flag; HUD can only degrade. (Defense-in-depth note: the lock lives in the manager — the gateway's setter itself is unguarded for future callers.)
- **Durable-intent-before-send is real** — own committed transaction before `OrderSend`, refuses inside ambient transactions, no memory-only exception anywhere, duplicate intent → MANAGE_ONLY.
- **Port fidelity of the static math** — Hermite construction (term-by-term incl. pivot ordering and micro-corrections), negative-lot unwinding, cumulative rescale, frequency-space grid, signed nearest lot normalization, VWAP, compat MLPS: **EQUIVALENT to V1 line-for-line**, quirks included and correctly quarantined in a compat engine that the live path does not use.
- **Corrected MLPS engine** — cost stack complete and sign-correct (stressed spread, both-side slippage/commissions, triple-swap projection, terminal adverse extension, pre/post-action liquidation nets, worst-case snapping throughout); solver never rounds risk above budget.
- **SQL hygiene and identity discipline** — bound parameters everywhere (no injection surface), `ulong` tickets as overflow-checked decimal TEXT end-to-end, 53-bit masked magic with string transport (`MagicTransport`) exactly per blueprint §5.
- **Fail-closed philosophy held under attack** — IntelligenceBus/Policy/ONNX/ReplayPack genuinely inert; telemetry genuinely bounded; certification bookkeeping can't resolve to REDUCED; almost every defect fails toward refusing to trade, not toward exposure.
- **Honest evidence culture** — `V2_BUILD_STATUS.md`'s self-assessment matched code reality in every case I checked; the two-lane PORT-vs-REDESIGN golden-master design and the delta register are exactly right.

## 7. Required-fix gate (my recommendation for the next iteration)

**Block-everything (fix before any further evidence work):**
1. §3.1 position_id on the reduction path + integration test that actually closes a position.
2. §3.2 + §3.3 uncertain-outcome handling (hold/quarantine, never END; widen the uncertainty classification).
3. §4.1 lease write-guard — empirical verification + `FILE_ANSI` fix.
4. §4.14 UTC time base + §4.15 UTF-8 hash fix — before any receipt corpus accumulates.

**Before Phase-1 certification (add to Codex's promotion-gate list, which remains valid):**
5. §4.2/4.3 writable-latch enforcement + a minimal repair/READ_ONLY open path.
6. §4.5-4.8 reconciliation fixes + a supervised re-promotion path for transient MANAGE_ONLY.
7. §4.9/4.10 PeakSmart tri-state + flexibility clamp, with golden-trace fixtures for: underwater retrace cross, 2-digit symbol, Grid_Factor=0, Grid_Min=0, LockFlexibility>1.
8. §4.11-4.13 gateway monotonicity for dust closes, shared normalizer, intent-machine enforcement.
9. §4.16 test hardening: execute the suite (produce the PASS artifact), receipt-determinism test (gate #6's instrument), independent-expected-value lot-ladder tests, kernel Evaluate matrix.
10. Emit the three missing receipt kinds so golden-master divergence reports can see negative decisions.

**Explicitly carried as open (agreed posture, not defects):** Feed v2/replay, ONNX influence, multi-symbol, GOAT Ops, session/license context wiring, retention policy — all correctly deferred and honestly labeled by Codex.

**Product directives added after Vince's hands-on inspection (2026-07-11, blueprint v1.2 — not review defects, but standing work items):**
11. **Operation modes are core product surfaces** — implement `V2_Mode_Operation` (TRADING / PORTFOLIO_DASHBOARD / OPTIMIZATION_STUDIO / REPORT_PROCESSOR) per blueprint §13.4. The mode selector and honest status placeholders for not-yet-built modes should appear in the very next iteration so the product surface is visible in the terminal; Dashboard mode reaches V1 capability parity at Phase 4, Studio/Report at Phase 5. Delta-register dispositions revised accordingly.
12. **Input reorganization** — regrade `Inputs_V2.mqh` + `inputs_v2.schema.json` into fine-grained V1-style groups (sequence settings, ATR, position sizing, risk management, per-indicator/feature sections, schedule, intelligence/state, ONNX, lineage) with group metadata in the schema as the generation source, per blueprint §11. The current four coarse groups (notably "Strategy and sequence" mixing indicator params with grid geometry) are below standard.

## 8. Bottom line

Codex delivered a foundation whose architecture, discipline, and honesty exceed the V1 codebase and most production MQL5 I have reviewed — and simultaneously a candidate whose two critical defects would have made its safety story partially fictional the day the compile lock lifted: the de-risking arm cannot fire, and the one scenario event-sourcing exists for (an uncertain broker outcome) is mishandled on the synchronous path. Both are cheap, surgical fixes; both were invisible to the current test battery — which is the real lesson. The next iteration should pair every fix with the test that would have caught it, and the promotion gates should add: **"an integration test has closed a real tester position through the full manager→kernel→gateway path."**

Recommended immediate sequence: fix pack (items 1-4) → execute unit tests + new integration test in the tester → re-review of the diff (small, fast) → then resume the Phase-1 evidence program per `V2_BUILD_STATUS.md`.
