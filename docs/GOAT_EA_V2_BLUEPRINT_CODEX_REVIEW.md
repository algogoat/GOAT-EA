# GOAT EA V2 — Reviewed Design Blueprint

**Status:** DRAFT v0.2 for Vince + Fable review. This revision preserves the original vision and incorporates Codex's implementation review before the plan becomes a standing build brief.
**Date:** 2026-07-11
**Authors:** Vince (vision/approval) + Fable/co-developer (architecture/review) + Codex (implementation review and lead build responsibility)
**Relationship to V1:** V1.4x remains a living, independently released product and will continue to evolve. V2 is a new internal product built without V1 compatibility pressure. The current V1.42 source and binary should be committed, then one explicit V1 reference commit will be selected for V2 parity work. That reference is a reproducible comparison anchor, not a freeze on future V1 development. Later V1 improvements may be intentionally evaluated and carried into V2 through a documented delta process. Nothing in this document authorizes changes to V1 entrypoints.

---

## Review changes incorporated in this revision

This revision keeps the original blueprint's direction and adds the following implementation-level clarifications:

1. A light Phase 0 selects a reproducible V1 comparison anchor without freezing the living V1 product.
2. A pure domain state machine and event vocabulary are defined before the SQLite schema.
3. All broker mutations pass through one action-aware Broker Gateway and Safety Kernel.
4. V2 is portfolio-capable internally from Phase 1, while initial parity testing remains single-symbol.
5. Feed v2 gains exact identity, availability-time, price-reference, quality, and anti-lookahead fields.
6. ONNX is positioned primarily as native execution intelligence, not as a second directional oracle competing with GOAT AI.
7. Golden-master testing compares decision traces as well as final metrics.
8. Receipts support shadow/counterfactual policy grading and marginal attribution of GOAT AI value.
9. Reproducible experiments carry complete environment and artifact manifests.
10. Recovery ambiguity, database failure, feed failure, model failure, and telemetry failure have explicit degraded operating states.

---

## 0. Mission and non-negotiables

V2 evolves GOAT EA from an excellent human-coded traditional EA into an AI-powered trading system that pushes MQL5/MT5 to its limits: the proprietary execution arm of the GOAT ecosystem.

- **GOAT AI** provides open market intelligence and evolving theses.
- **GOAT EA** converts intelligence into deterministic, broker-aware execution.
- **GOAT Ops** creates the evidence-gated self-improving loop.

Non-negotiables:

1. **Determinism owns safety.** The Safety Kernel's limits can never be overridden by AI state, policy logic, dashboard commands, ONNX output, or optimization results.
2. **Everything stays replayable and optimizable.** Every trading-relevant feature must run from immutable local artifacts in the MT5 Strategy Tester. No live-only input may affect a trading decision.
3. **Evidence gates; intelligence proposes.** Models and overlays argue. Deterministic validation, backtests, graded live cohorts, and hard limits rule.
4. **GOAT AI owns the market thesis; GOAT EA owns execution.** V2 may learn how best to execute a thesis, but execution outcomes must never be fed back into Sol's directional judgment.
5. **Risk-reducing actions remain available.** A stale feed, expired license, unavailable model, or blocked entry state may stop new risk, but must not prevent valid protective management or exposure reduction.
6. **Full autonomy is the goal, not the default.** GOAT Ops begins at Stage A (recommend-only). No promotion occurs without graded evidence, Vince's end-to-end understanding, and Vince's written approval.
7. **V1 and V2 evolve independently.** V1 remains live and may continue changing. V2 ports from an explicitly selected reference commit and accepts later V1 improvements only through deliberate review.
8. **Capital-critical engineering standard.** Every module is treated as capable of affecting live capital. Codex implements against the approved brief; Fable reviews architecture and merges; Vince approves phase and autonomy gates.

---

## 1. System overview

V2 uses five logical layers plus a single controlled broker boundary:

```text
INTELLIGENCE BUS  — Feed v2 live source / immutable replay pack, calendar,
                    thesis identity, era stamps, validity and quality
POLICY LAYER      — strategy/regime gating, shadow decisions, thesis reactions,
                    ONNX execution-quality interpretation
EXECUTION CORE    — direction-parameterized SEQUENCE v2, exposure math,
                    MLPS v2, basket exits, trailing, unwinding
SAFETY KERNEL     — action-aware invariants and deterministic veto/clamp logic
BROKER GATEWAY    — the only route to open, add, modify, close, or cancel
STATE/TELEMETRY   — event journal, projections, recovery, receipts, outbox,
                    heartbeat and experiment lineage
```

One versioned entrypoint, initially `GOAT2 V2.0.mq5`, wires the lifecycle. Shared V1 includes are never modified for V2.

Proposed layout:

```text
GOAT2 V2.0.mq5                  # thin lifecycle and event wiring
v2/Domain.mqh                   # commands, events, sequence/portfolio state machines
v2/Identity.mqh                 # deployment, member, sequence and broker identity
v2/Core_Sequence.mqh            # SEQUENCE v2 and exposure math
v2/Core_Risk.mqh                # MLPS v2 and full cost stack
v2/SafetyKernel.mqh             # deterministic action-aware safety decisions
v2/BrokerGateway.mqh            # sole trade-request/modify/close boundary
v2/Scheduler.mqh                # portfolio-capable per-symbol clocks and data readiness
v2/Features.mqh                 # FeatureFrame and native feature packs
v2/Policy.mqh                   # state gates, shadow mode, reactions and envelopes
v2/IntelligenceBus.mqh          # live state source and replay-source interface
v2/ReplayPack.mqh               # immutable indexed multi-asset state pack reader
v2/OnnxLayer.mqh                # model bundle validation and native inference
v2/StateDB.mqh                  # SQLite journal, projections and recovery
v2/Telemetry.mqh                # bounded outbox, uploads and heartbeat
v2/PortfolioManager.mqh         # portfolio coordination; present from Phase 1
v2/Inputs_V2.mqh                # generated input surface
v2/ExperimentManifest.mqh       # complete reproducibility and artifact lineage
v2/tests/                       # MQL5 unit/property/failure-injection runners
docs/GOAT_EA_V2_BLUEPRINT.md
docs/GOAT_EA_V2_BLUEPRINT_CODEX_REVIEW.md
docs/V1_TO_V2_DELTA.md          # intentional later V1-to-V2 intake decisions
```

Codex may propose naming changes, but not boundary changes, without approval.

---

## 2. Phase 0 — reference truth without freezing V1

V1.42 continues to evolve. V2 nevertheless needs one stable reference point so parity claims mean something.

Phase 0 deliverables:

1. Commit the current V1.42 `.mq5`, matching `.ex5`, updated shared input definition, and approved documentation.
2. Record one `v2_reference_commit` after its compile and baseline tests are verified.
3. Capture representative V1 reference `.set` files, symbols, windows, tick modes, and AI replay inputs.
4. Record an experiment manifest containing terminal build, broker/server fingerprint, account currency/leverage, symbol specifications, tick-data provenance, input hashes, and binary hash.
5. Capture V1 decision traces where practical: signal evaluations, sequence starts, level geometry, calculated lots, add/skip decisions, MLPS values, and exits.
6. Create `docs/V1_TO_V2_DELTA.md`. Future V1 changes remain free to ship; each material change is later marked `PORT`, `REDESIGN`, `NOT_APPLICABLE`, or `DEFER` for V2.

This creates reproducible comparison without turning V1.42 into a permanently frozen product.

---

## 3. Domain state and event contract — define before persistence

SQLite must persist the engine; it must not define the engine.

V2 first defines pure in-memory domain types and legal transitions:

- `PortfolioState`
- `StrategyMemberState`
- `SequenceState`
- `LevelState`
- `OrderIntentState`
- `ThesisBinding`
- `OperationalState`

Material transitions emit typed domain events, for example:

- `SEQUENCE_STARTED`
- `LEVEL_PLANNED`
- `ORDER_INTENT_CREATED`
- `ORDER_SUBMITTED`
- `ORDER_ACCEPTED`
- `FILL_PARTIAL`
- `FILL_COMPLETE`
- `ORDER_REJECTED`
- `LEVEL_CLOSED`
- `RETRACE_POINTER_MOVED`
- `RESCUE_ARMED`
- `SEQUENCE_ENDED`
- `RECOVERY_QUARANTINED`

The normal flow is:

```text
market/intelligence input
  → policy proposal
  → execution command
  → Safety Kernel decision
  → durable order intent
  → Broker Gateway submission
  → trade-transaction observations
  → reconciled domain events
  → state projections + receipts
```

`OrderSend()` success is treated only as request submission/acceptance evidence, never as proof of a completed fill. Request IDs, order tickets, deal tickets, and position identifiers remain distinct.

Acceptance: property tests prove that illegal transitions are rejected and that replaying the same ordered event stream reconstructs identical canonical state.

---

## 4. State and persistence (`StateDB.mqh`)

**Problem solved:** V1 sequences are primarily memory-resident, so restart recovery cannot reconstruct every management state reliably.

Use native MQL5 SQLite. Live operation uses one database per account and deployment in `FILE_COMMON`, with a single-writer ownership/lease rule. Tester operation uses an in-memory database for ordinary speed tests and a durable temporary database for recovery tests.

Initial tables/projections:

- `domain_events` — append-only canonical event journal
- `sequences` — current sequence projection
- `levels` — current level projection
- `seq_ledger` — realized P/L, commission and swap projection
- `order_intents` — request lifecycle and correlation IDs
- `trade_observations` — orders/deals/positions observed from MT5
- `receipts` — decision registry described in §8
- `slippage_log` — requested, accepted and filled prices plus latency/retcodes
- `intelligence_cache` — exact state rows used by policy
- `telemetry_outbox` — bounded idempotent upload queue
- `meta` — schema, deployment, broker profile, migration and integrity state

Write discipline:

- Persist the order intent before broker submission.
- Reconcile fills asynchronously from trade transactions and account/history scans.
- Keep `OnTradeTransaction()` short; journal a minimal observation and defer heavier work.
- Wrap related database writes in explicit transactions.
- All migrations are versioned, reversible where practical, and tested against copied databases.
- Ticket and identifier types remain `ulong` end to end.

Recovery contract:

1. Acquire the deployment writer lease.
2. Integrity-check and migrate the database.
3. Load the last canonical projections/event offset.
4. Scan open orders, positions and recent history.
5. Match by deployment/member identity, magic, symbol, position identifier and journal lineage.
6. Reconcile missing/late events idempotently.
7. If ownership is ambiguous, enter `RECOVERY_QUARANTINE`: block new adds, preserve protective management, alert, and upload evidence. Never guess silently.

Operational database failure behavior:

- Loss of durable writes → `MANAGE_ONLY`; block new exposure.
- Readable journal with failed telemetry → trading may continue within bounded local storage.
- Corruption or ambiguous ownership → quarantine affected members; do not contaminate unrelated members.

Acceptance: deterministic recovery fixtures, repeated recovery idempotency, forced database-failure tests, and a real demo-terminal restart prove that management resumes without manual reconstruction.

---

## 5. Identity scheme (`Identity.mqh`)

Identity must survive restarts, broker behavior, portfolio evolution and telemetry aggregation.

Required identities:

- `deploymentId` — stable installed portfolio deployment
- `portfolioGenerationId` — GOAT Ops generation/lineage
- `strategyMemberId` — stable portfolio member/strategy identity
- `sequenceId` — unique sequence instance
- `orderIntentId` — unique requested broker mutation
- MT5 request ID, order ticket, deal ticket and position identifier

Recommended magic scheme: a stable collision-checked 63-bit hash of product namespace + deployment + strategy member. Symbol and direction are metadata, not the sole identity. Broker comments are hints only and never the authoritative recovery key.

---

## 6. Safety Kernel and Broker Gateway

The Broker Gateway is the only code allowed to call raw trade functions or `CTrade` mutation methods. Every open, add, modify, partial close, full close and cancellation passes through the Safety Kernel.

The kernel is action-aware. It may return:

- `ALLOW`
- `ALLOW_REDUCE_ONLY`
- `DENY`
- `HALT_NEW_RISK`
- `FORCE_REDUCE`

Risk-reducing operations are not rejected merely because entry conditions such as feed freshness, license state, spread ceiling or session state have failed.

Checks include:

1. **Projected margin:** `OrderCheck` results plus a deterministic additional free-margin buffer.
2. **Spread and liquidity:** session-conditioned spread stress with an absolute emergency cap.
3. **Exposure:** per sequence, symbol, strategy, currency/factor bucket and total portfolio caps.
4. **Account mode:** refuse netting/exchange modes until explicitly implemented and validated.
5. **Stops/freeze/order permissions:** prices, distances, volume steps, filling mode and symbol trade permissions.
6. **Broker profile:** versioned commission, swap, triple-swap, conversion and symbol-contract assumptions.
7. **Error budget:** weighted error classes; predictable price changes are separated from infrastructure or repeated broker failures.
8. **Session, expiry and license:** new-risk controls only; protective management continues.
9. **Equity guards:** local/global running loss, daily loss/profit, equity floor/target and portfolio DD controls.
10. **Operational state:** `NORMAL`, `DEGRADED`, `MANAGE_ONLY`, `RECOVERY_QUARANTINE`, or `HALTED`.

Acceptance: unit tests cover each check and action class; fuzzing sends malformed/edge requests; static/search verification confirms no trade mutation bypasses the Broker Gateway.

---

## 7. Execution Core (`Core_Sequence.mqh`, `Core_Risk.mqh`)

**Port the crown jewels from the selected V1 reference; do not casually reinvent them.** Later V1 changes are evaluated through `V1_TO_V2_DELTA.md` rather than implicitly changing the parity target.

- SEQUENCE v2 is direction-parameterized (`dir ∈ {+1,-1}`) with one tested code path.
- Ported behavior includes the seven lot-progression models, Hermite Peak/PeakSmart curves, programmed unwinding, ladder rescaling to `Lots_Max_Cum`, frequency-space grid geometry, ATR-relative negative-input convention, VWAP basket Lock/TP/SL, flexibility scaling, trailing, CumPartial, SmartPeak retrace harvesting, virtual/delayed sequences, MustCheck revalidation, and bias/state rescue behavior.
- All transitions emit domain events and receipts.
- Portfolio-capable containers and scheduling exist from Phase 1, even while the first parity battery runs one symbol/member at a time.

**MLPS v2:** the worst-case solver includes spread, commission, accrued/projected swap, triple-swap day, realistic currency conversion, broker contract specifications, and expected close costs. Live calibration may update a versioned broker profile; backtests always use a pinned profile from the experiment manifest.

Golden-master requirement: with state/ONNX/new features disabled and V1-equivalent inputs, the single-symbol V2 engine must reproduce the selected V1 reference battery within approved event- and metric-level tolerances before new behavior is promoted.

---

## 8. Execution receipts — canonical decision registry

Every material decision writes a receipt locally before asynchronous upload.

Kinds include:

- `SEQ_START`
- `SEQ_START_SUPPRESSED`
- `LEVEL_ADD`
- `LEVEL_SKIP`
- `PARTIAL_CLOSE`
- `RESCUE_ARM`
- `SEQ_END`
- `KERNEL_VETO`
- `RECOVERY_ACTION`
- `SHADOW_DECISION`

Every receipt contains:

- deterministic `receiptId`, event time and canonical sequence number
- deployment/member/sequence/order-intent lineage
- symbol, direction and broker profile version
- FeatureFrame snapshot, readiness masks and feature schema version
- exact intelligence `stateId`, thesis/era, publication/validity times and content hash
- policy verdicts and reason codes
- kernel verdicts and invariant values
- ONNX bundle hash, input readiness, outputs and abstention/OOD result
- resulting request/order/deal/position details
- experiment manifest and portfolio generation IDs

On sequence end, add realized P/L, full costs, maximum adverse/favorable excursion in ATR, duration, level count and exit attribution.

Canonical serialization rules define field order, numeric quantization, UTC timestamps and semantic hashing so equivalent runs produce identical receipt hashes independent of database row order.

### 8.1 Shadow and counterfactual registry

When configured, V2 records what alternative modes would have proposed without sending orders:

- State disabled baseline
- State display/shadow
- State gate
- State execute
- ONNX disabled vs shadow/gated

This supports paired marginal attribution: did GOAT AI or ONNX improve the same strategy's decisions, rather than merely participating in a profitable strategy? Counterfactual results are clearly labeled as simulated and never treated as filled live trades.

---

## 9. Feature Layer (`Features.mqh`)

Indicators become a shared feature-engineering layer. Every field in `FeatureFrame` includes:

- normalized value
- validity/readiness bit
- observation count
- source data age
- feature/schema version

A missing or unready feature must never silently become a valid zero.

Initial packs:

1. **Microstructure:** spread EMA; session/minute-of-week conditioned spread percentile; tick rate and tick-direction imbalance; rollover/session-open stress; realized slippage and rejection statistics.
2. **Volatility regime:** ATR percentile, Parkinson and Garman-Klass realized-volatility estimates, squeeze/expansion state.
3. **Trend/momentum:** deliberately thin EMA-fan stacking/slope score and ADX trend quality; GOAT AI/Sol continues to own the broader 1–4h market map.
4. **Mean reversion:** RSI-family z-scores, Bollinger position z-score, and session tick-weighted VWAP proxy distance. Use real volume only when the instrument provides it reliably.
5. **Sequence self-awareness:** basket distance from entry VWAP in ATR, exposure-vs-planned-curve ratio, retrace velocity, level density, MLPS utilization and remaining exposure budget.
6. **Portfolio context:** currency/factor bucket exposure, correlated-cluster concentration, thesis overlap and remaining portfolio risk budget.

Implementation rules:

- Native calculations with copied series and MQL5 `vector`/`matrix` where justified.
- No black-box `.ex5` indicator resources.
- Incremental updates and bounded history/memory.
- One feature implementation shared by tester and live paths.
- Feature readiness behavior is explicitly tested during cold starts and missing-history conditions.

---

## 10. Intelligence Bus and Feed v2 contract

### 10.1 Typed state contract

The first typed contract is versioned as `goat-state-v1` even though it replaces the legacy feed and is served by Feed v2.

Required fields per asset/state:

| Field | Type | Purpose |
|---|---|---|
| schemaVersion | string | Contract compatibility |
| stateId | string | Immutable exact state identity |
| thesisId, revision | string/int | Thesis lifecycle and revision ordering |
| assetCanonical | string | Broker-independent GOAT asset identity |
| marketAsOf | ISO8601 | Latest market information used by GOAT AI |
| publishedAt | ISO8601 | Earliest time the state was actually available to the EA |
| validFrom, validUntil | ISO8601 | Authoritative activation/expiry window |
| era | string | Analyst/harness era stamp |
| regime | enum(5) | STRONG_BULLISH through STRONG_BEARISH |
| pBull, pNeutral, pBear | double | Calibrated probabilities; sum to 1 |
| actionability | enum | ACTIONABLE / NO_TRADE / RAW_ONLY etc. |
| signedScore | double | Back-compatible ±100 scalar, actionability-gated |
| locationState | enum | ENTER_NOW / WAIT_PULLBACK / WAIT_CONFIRM / RANGE_EDGE_ONLY / NO_TRADE |
| zoneLo, zoneHi | nullable double | Source-market reference zone |
| triggerType | enum | IMMEDIATE / ZONE_TOUCH / CONFIRMATION |
| entryInvalidation | nullable double | Source-market reference price |
| eaeAtr, eaeMinutes | nullable double | Expected adverse excursion and time definition |
| eaeQuantile | nullable double | Quantile represented by EAE |
| objective | nullable double | Source-market objective |
| thesisStatus | enum | CONTINUE / WEAKEN / NEUTRALIZE / REVERSE |
| referencePrice, referencePriceTs | double/ISO8601 | Price basis used by the state |
| referenceAtr, forecastHorizon | double/string | Normalization and horizon semantics |
| qualityFlags | bitset/list | Missingness, data-quality and calibration warnings |
| model/analyst versions | strings | Intelligence artifact lineage |
| contentHash | string | Immutable payload verification |

`publishedAt`, not `marketAsOf`, controls historical replay activation and prevents lookahead. Raw source-market prices are carried alongside ATR/tick-normalized offsets so policy can translate plans to broker quotes safely.

### 10.2 Live path

Poll `GET /api/ea/state?asset=&id=` on the approved cadence, parse typed JSON, verify schema/content, map the canonical asset to the broker symbol, and cache the exact row in StateDB.

- Stale or invalid state → `NO_STATE` for new entries.
- Existing sequences continue deterministic management.
- A valid thesis transition may influence management only through approved Policy modes and Safety Kernel bounds.
- Network work and parsing never block trade-transaction reconciliation.

### 10.3 Replay path

The downloader creates one immutable, indexed multi-asset GOAT State Pack where practical, registered as a static tester artifact. The pack contains schema version, generation timestamp, covered assets/window, ordered state rows, per-section checks and a manifest hash.

Replay uses a forward-only availability cursor and activates rows at `publishedAt`. Live and replay sources implement the same interface; all downstream policy logic is shared.

The EA refuses schema, hash, asset-map or time-order mismatches loudly. CSV export may remain available for inspection, but the canonical large-scale replay artifact should be compact and deterministic.

---

## 11. Policy Layer (`Policy.mqh`)

### 11.1 State modes

Master `Mode_State`:

- `Disabled` — no state consumption
- `Display` — show validated state only
- `Shadow` — compute and receipt policy decisions without affecting trades
- `Gate` — gate sequence starts/adds using approved deterministic rules
- `Execute` — translate location/thesis plans into bounded execution proposals

`Gate` uses regime-direction agreement, actionability, calibrated probability floors, feature readiness and freshness.

`Execute` may propose:

- entry timing/zone
- invalidation candidate
- objective candidate
- depth/exposure factor
- tighten/pause/rescue/exit reaction

These are expressed as a `PolicyEnvelope`. The envelope can reduce or constrain risk but cannot raise exposure beyond deterministic strategy/kernel maxima. Safety Kernel checks remain authoritative.

Thesis transitions use `thesisId`, revision ordering, hysteresis, minimum dwell/cooldown rules and explicit reversal confirmation to prevent scan-to-scan policy thrashing.

The input schema is defined once in a machine-readable source and generates input declarations, `.set` writing, validation and documentation. Generated artifacts carry a schema hash and are committed for reproducibility.

---

## 12. Native ONNX execution intelligence (`OnnxLayer.mqh`)

ONNX (Open Neural Network Exchange) lets a trained model run natively inside MetaTrader 5 and the Strategy Tester. In V2 its initial purpose is **execution intelligence**, not duplicating Sol's directional thesis.

Preferred first-model questions:

- What is the probability that this sequence reaches its objective before MLPS?
- What adverse-excursion distribution is expected under the current thesis, features and broker costs?
- How many levels and how much time are likely to be required?
- Is execution quality good enough to start now, wait, reduce size, or abstain?
- What bounded grid-depth/exposure factor is justified?

GOAT AI remains the source of market thesis. ONNX learns broker-, strategy- and sequence-specific execution translation.

### 12.1 Plain-English example

Assume GOAT AI reports:

> XAUUSD is bullish, actionable, but a pullback into a defined zone is preferred; expected adverse excursion is elevated before the four-hour objective.

The ONNX execution model receives that exact state together with current spread/liquidity, volatility regime, time/session, strategy family, planned grid, broker costs and current portfolio/sequence exposure. It might estimate:

- 72% probability of reaching the objective before the sequence's deterministic MLPS boundary
- likely adverse excursion of 1.4 ATR at the selected confidence quantile
- likely requirement for four sequence levels and approximately six hours to resolve
- poor execution quality at the current spread, but acceptable quality inside the pullback zone

Policy could then propose `WAIT`, or propose a smaller bounded starting exposure and shallower depth after the zone is reached. The Safety Kernel independently checks the proposal and may reduce or reject it. ONNX never bypasses policy, changes hard risk limits, or sends the order itself.

The same model runs against historical GOAT AI states and market data in the Strategy Tester. This makes the claimed benefit measurable: compare the identical strategy and thesis stream with ONNX disabled, in shadow, and gated. If it does not improve out-of-sample execution after costs, it is not promoted.

### 12.2 Model bundle and governance

A deployable model is a signed/hashed bundle, not only an `.onnx` file:

- ONNX model
- model card and intended-use limits
- exact feature schema and ordered input names
- preprocessing/scaler parameters
- input/output shapes and numeric types
- training-data cohort and time-window lineage
- code/experiment manifest
- validation metrics and baseline comparisons
- model/content hash and version

On load, V2 validates every component. A schema, shape, preprocessing or hash mismatch disables model influence and alerts; it does not improvise.

### 12.3 Modes and safety

`Mode_Onnx` begins as:

- `Disabled`
- `Shadow`
- `Gate`

ONNX never sends an order directly. It produces a bounded score/proposal consumed by Policy and then clamped by the Safety Kernel.

Replay rules:

- deterministic CPU inference for tester certification
- fixed preprocessing and numeric conversion
- immutable bundled model artifact
- explicit missing-feature and out-of-distribution detection
- abstention when readiness/confidence requirements fail

Training/validation rules:

- era-consistent, walk-forward evaluation
- purging/embargo around overlapping labels where required
- untouched final holdout windows
- comparison against state-disabled and no-model baselines
- champion/challenger shadow evaluation before capital influence
- no training-label leakage from future sequence outcomes

---

## 13. App-side GOAT AI requirements

V2 depends on platform work in the separate GOAT AI repository:

1. **`GET /api/ea/state`** — serves the §10 typed state with live and historical range modes. Actionability gating must match the authoritative export semantics.
2. **Historical State Pack/export service** — produces multi-year, era-stamped, availability-correct state data with hashes and clamped range requests.
3. **Receipts ingestion** — idempotent batched `POST /api/ea/receipts`, keyed by deployment/account/portfolio/member/sequence lineage.
4. **Portfolio tracking completion** — strategy breakdown, matched member identity, exact bucket windows, 365-day views and health configuration.
5. **Per-customer EA tokens** — issued through license handshake with rotation and revocation; no fleet-wide static secret.
6. **Security prerequisites** — protect history/details endpoints, enforce/alarm feed authentication, and remove inappropriate vendor/admin token equivalence.
7. **Model-bundle registry/distribution** — signed artifact metadata, staged rollout, revocation and rollback.
8. **GOAT Ops surfaces** — optimization queue, experiment registry, overseer memos, generation lineage, canary state, rollback and Vince approval UI.

---

## 14. GOAT Ops — evidence-gated autonomous loop

### 14.1 Loop

```text
live telemetry + receipts + shadow decisions + analyst-era changes
  → TRIGGER ENGINE
  → AI SPEC WRITER
  → OPTIMIZATION ORCHESTRATOR
  → DETERMINISTIC GATES
  → AI OVERSEER MEMO
  → PORTFOLIO BUILDER
  → CHAMPION/CHALLENGER SHADOW
  → STAGED CANARY DEPLOY
  → CAPITAL-FRACTION LADDER / ROLLBACK
  → graded receipts close the loop
```

Every experiment and generation has immutable lineage. Claims compare era-consistent cohorts and, where possible, paired incumbent/candidate decisions.

### 14.2 Optimization cadence

- **Fast lane:** weekly/biweekly narrow retune labs around incumbents.
- **Slow lane:** monthly/quarterly discovery seed farms.
- **Change budget:** minimum tenure, hysteresis and evidence thresholds prevent constant portfolio churn.
- **Untouched holdouts:** final holdout windows are not recycled into repeated candidate selection.

### 14.3 Trust ladder

| Stage | The loop may… | Promotion requires |
|---|---|---|
| **A — Recommend** | Run research and produce evidence/recommendation memos; every consequential action requires Vince's click. | Initial stage |
| **B — Auto-research** | Auto-run optimizations, model training and portfolio builds; deployment remains manual. | Graded Stage-A record, end-to-end review, written approval |
| **C — Auto-canary** | Auto-deploy approved candidates/models to capped canary accounts; fleet remains manual. | Positive Stage-B cohorts, shadow-to-canary correlation, written approval |
| **D — Bounded autonomy** | Fleet deployment inside permanent risk/change budgets; capital increases remain manual. | Proven canary-to-fleet relationship and written approval |

Demotion is immediate and unilateral. One deterministic configuration flag can return the system to Stage A or disable new-risk automation.

### 14.4 Never delegated

- Safety Kernel and Broker Gateway boundary
- portfolio DD and equity kill controls
- maximum capital fraction per generation
- maximum exposure and concentration limits
- canary-first ordering
- rollback retention of prior generation/model
- execution-to-Sol firewall
- Vince's authority over autonomy promotion and capital increases

---

## 15. Testing and verification

### 15.1 Golden-master regression

The initial battery compares V2 with the selected V1 reference commit—not with every future living V1 change.

For each strategy family × symbol × window:

- final metrics: trades, profit, DD, PF, sequence counts and costs
- semantic trace: signal, start/suppress, level geometry, lots, MLPS, add/skip and exit
- first-divergence report with event context

No new-behavior promotion occurs while required parity cases are red. Approved intentional differences are documented, never hidden inside tolerance widening.

### 15.2 Experiment manifest

Every certified result records:

- source and `.ex5` hashes
- terminal build and tester mode
- `.set`, state-pack, news/calendar and ONNX hashes
- broker/account/symbol specifications
- tick/bar data provenance and window
- feature/input/schema versions
- random seeds where applicable

“Same experiment” means the manifest matches, not merely that the `.set` file matches.

### 15.3 Property and fuzz tests

- cumulative lots never exceed caps
- ladder rescale preserves required monotonicity/cap behavior
- MLPS estimate covers simulated realized adverse-path loss including costs
- domain-event replay is deterministic
- recovery is idempotent
- ambiguous recovery enters quarantine
- kernel action classes enforce risk monotonicity
- no broker mutation bypasses the gateway
- replay activates intelligence at `publishedAt`
- two identical manifested runs produce identical canonical receipt hashes
- malformed feeds, models, databases and requests fail safely

### 15.4 Recovery and failure injection

Ordinary tester tests may use in-memory SQLite. Recovery tests use a durable temporary database and injected crash checkpoints. A demo terminal restart then verifies real adoption/reconciliation behavior.

Failure injection includes:

- database unavailable/corrupt/full
- live feed unavailable/stale/schema-mismatched
- model unavailable/hash/schema/OOD failure
- broker timeout/partial fill/out-of-order observations
- telemetry backlog/network failure
- missing symbol history or cold feature state

### 15.5 Live verification

Per phase: shadow observation → demo canary → small live canary → bounded widening. Receipts and heartbeats are reconciled against manifested tester expectations before promotion.

---

## 16. Revised phased roadmap

| Phase | Deliverables | Gate to next |
|---|---|---|
| **0 — Reference and contracts** | Commit current V1.42; select V2 reference commit; baseline manifests/traces; approve identity, event, feed and failure contracts; create V1-to-V2 delta register | Vince + Fable approval of contracts and target behavior |
| **1 — Deterministic foundation** | Thin entrypoint; portfolio-capable domain/scheduler; identity; Broker Gateway; Safety Kernel; StateDB/journal/recovery; SEQUENCE/MLPS port; canonical local receipts; single-symbol golden master | Parity battery green; gateway audit; recovery/failure demo; approval |
| **2 — Intelligence shadow and gate** | Feed v2; State Pack; live/replay parity; FeatureFrame foundation; `Display`/`Shadow`/`Gate`; counterfactual receipts | Anti-lookahead and replay determinism proven; marginal overlay evidence; approval |
| **3 — Native execution intelligence** | Feature packs complete; receipts upload; ONNX execution-quality training pipeline and model registry; shadow/champion-challenger; bounded `Execute` mapping | Model/execute modes beat no-model/state-only baselines on untouched and forward cohorts; approval |
| **4 — Portfolio production** | Multi-symbol live scheduling; portfolio MLPS/exposure/dependency controls; portfolio dashboard view; composed portfolio sets; multi-symbol tester reconciliation | Portfolio tests reconcile with member composition; demo/live canary evidence; approval |
| **5 — GOAT Ops** | Orchestrator, triggers, AI spec writer, overseer memos, experiment registry, staged deploy, rollback, lineage and approval UI; Stage A live | Stage-A record accumulating; governance and demotion controls proven |

Phase 1 is portfolio-capable by design, but Phase 4 activates and certifies full multi-symbol production behavior. This avoids a structural rewrite while keeping early scope controlled.

---

## 17. Decisions requested from Vince + Fable before implementation

1. **Portfolio architecture:** approve portfolio-capable internals from Phase 1 with single-symbol parity first. **Codex recommendation: approve.**
2. **ONNX role:** prioritize execution-quality prediction/translation rather than an independent directional model. **Codex recommendation: approve.**
3. **V1 reference policy:** commit current V1.42 and select a comparison commit while allowing V1 to keep evolving; later intake uses the delta register. **Codex recommendation: approve.**
4. **Netting accounts:** refuse through Phases 1–4 unless separately designed and tested. **Codex recommendation: approve refusal.**
5. **Identity:** approve deployment/member hashed magic with explicit collision checks and journal mapping. **Codex recommendation: approve concept; finalize exact hash/bit allocation in Phase 0.**
6. **Replay artifact:** one immutable indexed State Pack as canonical, with CSV as inspection/export. **Codex recommendation: approve after a small MT5 performance proof.**
7. **Safety semantics:** approve risk monotonicity and action-aware kernel decisions. **Codex recommendation: mandatory.**
8. **Receipt retention:** select local limits and server retention tiers after a volume estimate during Phase 1.
9. **Model distribution:** choose repo-bundled models for development and signed platform distribution for staged production. **Codex recommendation: this split.**

---

## 18. References

- Original `docs/GOAT_EA_V2_BLUEPRINT.md`
- Current V1.42 code and matching binary after commit
- `README.md` release and reproducibility rules
- GOAT AI `FINANCIAL_MARKETS_HARNESS_DESIGN.md`
- GOAT AI `docs/SOL_LIVE_EVOLUTION.md`
- GOAT AI `docs/PORTFOLIO_TRACKING_BACKEND_SPEC.md`
- `EA_SINGLE_URL_INTEGRATION_MANUAL.md`
- MQL5 capabilities: native SQLite, `OrderCheck`, `OnTradeTransaction`, `OnnxCreate`/`OnnxRun`, `vector`/`matrix`, `CopyTicks`, timers, multi-symbol tester and `#property tester_file`

---

## Final design principle

The EA of the future is not the EA that gives AI unrestricted control. It is the EA that captures the maximum useful intelligence from GOAT AI, translates it into execution-aware probability and timing, tests every claim reproducibly, and permits action only inside deterministic capital protection.

GOAT AI should make GOAT EA more informed. GOAT EA should make GOAT AI's intelligence executable. GOAT Ops should make the combined system measurably better without weakening its safety boundary.
