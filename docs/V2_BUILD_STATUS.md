# GOAT2 V2.0 Build and Evidence Status

**Product state:** Phase 0/1 development foundation
**Scope:** one strategy member, one chart symbol, hedging accounts only
**Certification state:** not certified for live new risk or multi-symbol portfolio use
**Last evidence review:** 2026-07-11, after the final clean rebuild and static evidence pass

## Executive status

`GOAT2 V2.0` is a fresh, isolated EA product. Its lifecycle, V2-only input surface, event-sourced domain, SQLite state store, broker boundary, deterministic safety kernel, execution geometry, receipts, manifest, and UI foundations now exist independently of GOAT V1.

This is an engineering candidate, not a trading-performance claim. It is intentionally limited to one member and one symbol. The terms **portfolio-capable**, **Phase 1 complete**, **parity green**, **recovery proven**, **certified**, and **production ready** must not be used for this candidate.

New exposure is physically locked at compile time:

```mql5
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 0
```

The entrypoint defines the lock before including `v2/PortfolioManager.mqh`, and the manager checks it when deriving both requested and effective new-risk state. Runtime inputs cannot enable new exposure while the constant remains `0`. Promotion to `1` requires a separately reviewed certification build after every mandatory gate below is green.

## Current evidence matrix

| Area | Current status | Evidence presently available | Required before certification |
|---|---|---|---|
| Fresh V2 product boundary | **Implemented** | `GOAT2 V2.0.mq5` includes only `v2/PortfolioManager.mqh`; the V2 tree is separate from V1 | Keep the static boundary audit green on the final commit |
| V1 preservation | **Static pass** | Pinned V1.42 source, binary, and shared-input hashes match `v2/reference/v1_42_reference_manifest.json` | Recheck hashes immediately before commit |
| Compile-time execution lock | **Active** | `GOAT2_PHASE1_EXECUTION_CERTIFIED=0` in the entrypoint; manager derives new-risk enablement from the same macro | Controlled certification review and rebuild are required before changing it |
| Final production-EA compile | **Static pass** | Designated GOAT MetaEditor: `0 errors, 0 warnings`; entrypoint SHA-256 `BBB99B5B...39C0B3F`; binary SHA-256 `118604FD...0A371E3`; binary timestamp is newer than every final MQL source | Preserve the exact source/binary pair in the final commit and external evidence bundle |
| Broker mutation boundary | **Static pass** | `scripts/check_goat2_boundaries.ps1 -RequireGateway`: one mutation hit in `v2/BrokerGateway.mqh`, zero bypasses, zero V1 includes, zero detected secrets | Repeat against the final commit and include the output in the evidence bundle |
| Input/schema synchronization | **Static pass** | `scripts/check_goat2_input_schema.py`: 80 declarations and 80 schema fields; names, primitive types, and committed defaults agree | Extend schema QA to executable range and enum-value validation |
| MQL unit-test compile | **Static pass** | Designated GOAT MetaEditor: `0 errors, 0 warnings`; source SHA-256 `A9E64084...6B05B3E`; binary SHA-256 `4E3EE719...CF3F20`; binary timestamp is newer than final source | Execute the exact final test binary in Strategy Tester |
| MQL unit-test execution | **Not run / no PASS artifact** | Expected output is `FILE_COMMON\GOAT2\tests\phase1-unit-result.json`; no reviewed runtime result exists | Run the final test binary and archive its manifested PASS result |
| Domain, identity, grid, lot, basket, trailing, retrace, and safety unit surface | **Implemented; runtime evidence open** | Test source covers deterministic ordering, durable reduction mandates and atomic retrace advancement, intent transitions, seven progressions, grid geometry, safety classes, basket/retrace geometry, identity, defaults, and certification-bookkeeping validation | Execute final tests; add randomized/property coverage and replay-equivalence proof |
| Cost-complete MLPS | **Implemented; not certified** | `v2/Core_Risk.mqh` uses `OrderCalcProfit` plus pinned cost-profile inputs | Cost fixtures across approved symbols/broker profiles, adverse-path coverage, and budget-safe lot-step proof |
| StateDB, lease, journal, projections, and recovery | **Implemented foundation; unproven** | Fresh schema v3 persists immutable sequence bindings, reduction mandates, retrace obligations, events, projections, and exact ticket identities; ambiguous ownership is designed to quarantine | Durable crash checkpoints, restart fixtures, repeated-recovery idempotency, corruption/full-disk tests, and demo restart |
| Durable-before-send contract | **Implemented fail-closed** | `AuthorizeBrokerSubmission` denies submission when durable intent/receipt persistence fails | Failure-injection tests proving opens, adds, modifications, reductions, closes, and cancellations cannot bypass durability |
| Process-memory emergency broker exception | **Not present by design** | Persistence failure returns denial and requires `MANAGE_ONLY`; no broker submission is authorized from memory alone | Retain this invariant unless a future design receives explicit capital-safety approval |
| Broker transaction reconciliation | **Foundation present; runtime gate open** | Deal observations, server SL/TP/stop-out synthesis, comment-token crash-window correlation, terminal modification handling, partial-remainder quarantine, watchdogs, and continuous broker matching exist | Partial fills, remainder cancellation, order deletion/rejection, modification acknowledgement, timeouts, and out-of-order observation demo tests |
| Canonical receipts | **Implemented foundation; proof open** | Local receipts carry event, decision, kernel-veto, broker, feature, cost, and outcome context | Slippage linkage, identical-run receipt hashes, and sequence outcome reconciliation |
| Experiment manifest | **Implemented foundation; external lineage open** | Runtime manifest records environment, normalized non-lineage input identity, symbol/broker fingerprints, and supplied lineage | External verification of source/binary/`.set`/tick/profile hashes and two identical manifested runs |
| V1 PORT/PARITY corpus | **Inventory only** | Eight representative local V1 `.set` paths and SHA-256 values are recorded in `v2/tests/cases.json` and were locally hash-matched | Portable evidence bundle, V1 decision/command traces, V2 trace adapter, tolerances, and first-divergence reports |
| Generic EMA/RSI signal adapter | **Development-only, disabled by default** | Isolated in `v2/Features.mqh`; it is not represented as V1 signal parity | Complete V1 signal disposition or command-trace certification before any performance claim |
| Chart HUD and overlay | **Foundation only** | Canvas HUD and limited overlay compile into the candidate and are disabled in non-visual optimization | Pixel/interaction verification, render budget, DPI/brand work, command-path audit, and zero-cost non-visual optimization proof |
| Feed v2 and replay pack | **Deferred / disabled** | Typed interfaces and schema placeholders exist; replay loader fails closed | Phase 2 State Pack, exact-availability semantics, anti-lookahead proof, live/replay identity, and app endpoints |
| ONNX execution intelligence | **Deferred / disabled** | Phase-3 interface returns a disabled/abstained proposal | Signed model bundle, schema/hash/OOD validation, deterministic tester inference, and untouched-cohort evidence |
| Multi-symbol/member portfolio engine | **Deferred** | Current manager and scheduler own one member and `_Symbol`; portfolio names are lineage metadata, not a production portfolio container | Phase 4 member/symbol containers, scheduling, aggregate exposure, portfolio MLPS, recovery, HUD, and canary proof |
| GOAT Ops autonomy | **Deferred** | No autonomous deploy or capital-increase path exists | Phase 5 evidence registry, canary/rollback controls, Stage-A record, and written promotion approval |
| Journal retention and capacity | **Pre-certification gate open** | Causal events/receipts are unbounded and never automatically deleted; telemetry outbox is separately bounded | Production volume estimate, disk monitor, retention/archive policy, backup/restore drill, and full-disk failure test |

## Exact source and verification layout

```text
GOAT2 V2.0.mq5
GOAT2 V2.0.ex5
v2/BrokerGateway.mqh
v2/ChartHUD.mqh
v2/ChartOverlay.mqh
v2/Core_Risk.mqh
v2/Core_Sequence.mqh
v2/Domain.mqh
v2/ExperimentManifest.mqh
v2/Features.mqh
v2/Identity.mqh
v2/Inputs_V2.mqh
v2/IntelligenceBus.mqh
v2/OnnxLayer.mqh
v2/Policy.mqh
v2/PortfolioManager.mqh
v2/Receipts.mqh
v2/ReplayPack.mqh
v2/SafetyKernel.mqh
v2/Scheduler.mqh
v2/StateDB.mqh
v2/Telemetry.mqh
v2/reference/v1_42_reference_manifest.json
v2/schema/goat_state_v1.schema.json
v2/schema/inputs_v2.schema.json
v2/tests/cases.json
v2/tests/GOAT2_Phase1_UnitTests.mq5
v2/tests/GOAT2_Phase1_UnitTests.ex5
scripts/check_goat2_boundaries.ps1
scripts/check_goat2_input_schema.py
scripts/make_goat2_start_config.py
```

Compile the product candidate with the designated GOAT wrapper:

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\GOAT2 V2.0.mq5"
```

Compile the MQL test EA independently:

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_Phase1_UnitTests.mq5"
```

Run the current static gates from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\check_goat2_boundaries.ps1 -RequireGateway

python .\scripts\check_goat2_input_schema.py
```

For each compile, verify rather than infer:

1. The relevant `compile-codex.log` exists and ends with `Result: 0 errors, 0 warnings`.
2. The expected `.ex5` exists beside its `.mq5`.
3. The binary timestamp is newer than the entrypoint and every included source file.
4. The evidence bundle records the final source and binary SHA-256 values.
5. MT5 runtime evidence prints the expected build ID and `MQL_PROGRAM_PATH` after the EA is removed and reattached.

## Certification identity and `.set` hashing

The runtime experiment manifest deliberately maintains two different concepts:

- `inputValuesHash` is the SHA-256 of canonical runtime/trading controls. Expected-hash and external-lineage fields are excluded so inserting a hash does not change the object being hashed.
- the literal `.set` file SHA-256 belongs to the external certification evidence bundle generated before the run. It proves the exact bytes delivered to MT5, including encoding and tester serialization.

The normalized hash is not a substitute for the literal artifact hash. A certified run requires both, plus the final source hash, `.ex5` hash, git commit, V1 reference commit, tick-data identity, test model/window, broker-profile identity, and any active State Pack/calendar/model hashes.

## Durability, capacity, and retention

Every broker mutation requires a durable order intent and receipt before submission. This includes actions that reduce risk. V2.0 does not submit a close, partial close, modification, cancellation, open, or add from a process-memory-only emergency record. If SQLite cannot durably write, the operation is denied and the engine moves to `MANAGE_ONLY`. Existing broker-hosted stops and targets, where present, remain the crash-independent protection layer. Because a database outage also prevents a new reduction request, live certification must prove that every allowed exposure has adequate broker-hosted protection before this durability policy can be promoted.

For this candidate, the causal domain journal and receipt registry are append-only and unbounded. They are not automatically pruned because deleting causal evidence before its recovery and audit contract is proven would be unsafe. A capacity or write failure is fail-closed; it is not permission to bypass the journal.

Before certification, the project must approve and test:

- expected event, receipt, observation, and manifest volume by member/day;
- disk-space warning and hard-stop thresholds;
- archival boundaries that preserve the recovery horizon and hash-chain auditability;
- encrypted backup, restore, and corruption-recovery procedures;
- telemetry-outbox retention independent of the canonical local journal;
- full-disk and database-write failure behavior on a demo terminal.

## Deferred execution and portfolio work

The following V1 behaviors are not silently represented as complete:

- virtual and delayed sequence execution;
- complete MustCheck revalidation semantics;
- bias/state rescue behavior;
- the complete active V1 signal surface;
- multi-member and multi-symbol scheduling, exposure, recovery, and portfolio risk.

They are explicitly registered as deferred work in `docs/V1_TO_V2_DELTA.md`. A parity case that depends on one of them cannot be waived or tolerance-adjusted; the behavior must first be ported, redesigned with approval, or removed from that case with a documented reason.

## Promotion gates

`GOAT2_PHASE1_EXECUTION_CERTIFIED` must remain `0` until all of the following are complete and independently reviewed:

1. Final production and unit-test binaries compile with `0 errors, 0 warnings` and fresh timestamps.
2. Final static boundary and schema gates pass.
3. The MQL unit-test EA emits a manifested PASS result.
4. Cost-complete MLPS fixtures pass across the approved broker/symbol matrix.
5. PORT/PARITY command traces are green or every divergence has an approved delta disposition.
6. Two identical manifested tester runs produce identical canonical event and receipt hashes.
7. Crash, restart, corruption, write-failure, and repeated-recovery tests pass.
8. Partial-fill, cancellation, rejection, timeout, and out-of-order demo tests pass.
9. Broker-profile, session, feed, licence, and protective-management prerequisites are verified, including broker-hosted protection during database loss.
10. HUD/overlay interaction and performance gates pass for the scope being promoted.
11. Journal retention, capacity monitoring, backup, and restore policies are approved and tested.
12. The final evidence pack is reviewed and the certification macro change receives explicit written approval.

Phase 2 Feed v2/replay, Phase 3 ONNX, Phase 4 multi-symbol portfolio production, and Phase 5 GOAT Ops retain their own later approval gates. Phase-1 certification does not authorize those capabilities.
