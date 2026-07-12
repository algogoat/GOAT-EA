# GOAT2 V2.0 Build and Evidence Status

**Product state:** Phase 0/1 development foundation
**Scope:** one strategy member, one chart symbol, hedging accounts only
**Certification state:** not certified for live new risk or multi-symbol portfolio use
**Last evidence review:** 2026-07-12, after final review-fix rebuild, static gates, and three manifested tester PASS results

## Executive status

`GOAT2 V2.0` is a fresh, isolated EA product. Its lifecycle, V2-only input surface, event-sourced domain, SQLite state store, broker boundary, deterministic safety kernel, execution geometry, receipts, manifest, and UI foundations now exist independently of GOAT V1.

This is an engineering candidate, not a trading-performance claim. It is intentionally limited to one member and one symbol. The terms **portfolio-capable**, **Phase 1 complete**, **parity green**, **recovery proven**, **certified**, and **production ready** must not be used for this candidate.

The independent findings and their current dispositions are paired in
`docs/GOAT_EA_V2_FOUNDATION_REVIEW.md` and
`docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md`. In the matrix below, a static
or compile pass never implies tester-runtime success. Explicit pending labels
remain pending until the named machine-readable artifact has been reviewed.

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
| Final production-EA compile | **Compile pass** | Designated GOAT MetaEditor: `0 errors, 0 warnings`; entrypoint SHA-256 `F5BE49FA...742D23C`; binary SHA-256 `8538C05F...7F4047`; output 465,766 bytes at 2026-07-12 00:11:23, newer than final source | Preserve the exact source/binary pair in the commit and external evidence bundle |
| Broker mutation boundary | **Static pass** | Final-surface audit observed 27 source files, one permitted mutation hit in `v2/BrokerGateway.mqh`, zero bypasses, zero V1 includes, and zero detected secrets | Repeat against the exact commit and archive the output |
| Input/schema synchronization | **Static declaration-generation pass; broader generation open** | `scripts/generate_goat2_inputs.py --check` and `scripts/check_goat2_input_schema.py` pass: 81 declarations/81 fields across 17 groups, exact enum/default ordering, UTF-8 BOM/CRLF, and embedded exact-byte schema SHA-256 `4B440C02...2B3B29` | Preserve declaration generation; `.set`, validation, and documentation generation remain explicit §11 gates |
| MQL unit-test compile | **Compile pass** | Designated GOAT MetaEditor: `0 errors, 0 warnings`; source SHA-256 `09B0492A...87FD49`; binary SHA-256 `1F6A1EAD...E6ED37`, 192,940 bytes at 2026-07-12 00:11:32 | Preserve the exact binary and compile log with the evidence bundle |
| MQL unit-test execution | **Runtime pass** | `phase1-unit-result.json`: PASS, 171/171 checks, 0 failed, EURUSD; artifact SHA-256 `627C28AC...1E9CED` | Retain artifact/run identity; add randomized/property coverage and replay-equivalence proof |
| StateDB contract compile | **Compile pass** | Designated GOAT MetaEditor: `0 errors, 0 warnings`; source SHA-256 `48F03F1A...995FAD`; binary SHA-256 `55FC0678...9E6378`, 149,500 bytes at 2026-07-12 00:11:40 | Preserve the exact binary and compile log with the evidence bundle |
| StateDB contract execution | **Runtime pass** | `state-db-contract-result.json`: PASS, 21/21 checks, 0 failed; artifact SHA-256 `3C2D75EE...D8A4A80` | Add v3 migration, corruption, full-disk, restart, and large-journal fixtures |
| Real gateway integration | **Compile and runtime pass for the golden path** | Tester-only binary compiled `0 errors, 0 warnings` (source `93706A02...A9884`, binary `2BF2CF95...02FE73`, 488,540 bytes at 2026-07-12 00:11:54). Artifact `A213CB5C...05C56` proves real, non-mock EURUSD 0.01 open; broker/runtime/DB reconciled to 0.01; durable high-water readiness rearmed without regression; supervised re-promotion waited for three fresh healthy passes; forced full reduction finished all projections at zero/ENDED with no pending execution | Add partial/rejected/uncertain/out-of-order and broker-spec-change dust scenarios; actual poisoned-write recovery remains a restart/fault-injection gate; production remains compile-locked |
| Domain, identity, grid, lot, basket, trailing, retrace, safety, receipt, and input unit surface | **Runtime pass for current deterministic suite** | Expanded 171-check suite passed independent expected values, canonical intent bridges, uncertainty classification, cancel-ticket persistence, PeakSmart tri-state, V1 geometry/migration edges, safety matrix, physical dust accounting, source-age boundaries, UTF-8 vectors, receipt determinism, operation modes, and certification bookkeeping | Add randomized/property coverage, V1 PORT traces, and replay-equivalence proof |
| Cost-complete MLPS | **Implemented; not certified** | `v2/Core_Risk.mqh` uses `OrderCalcProfit` plus pinned cost-profile inputs | Cost fixtures across approved symbols/broker profiles, adverse-path coverage, and budget-safe lot-step proof |
| StateDB, lease, journal, projections, and recovery | **Isolated contract pass; broader recovery proof open** | Schema v4 adds additive v3→v4 migration, immutable migration ledger, append-only guards, inherited verification checkpoints, writer poisoning, read-only recovery, member snapshots, canonical submission bridges, and offline-only repair plans; the 21-check contract passed | Prove real migrations, crash checkpoints, repeated recovery, corruption/full-disk behavior, backup/restore, and demo restart |
| Durable-before-send contract | **Implemented fail-closed** | `AuthorizeBrokerSubmission` denies submission when durable intent/receipt persistence fails | Failure-injection tests proving opens, adds, modifications, reductions, closes, and cancellations cannot bypass durability |
| Process-memory emergency broker exception | **Not present by design** | Persistence failure returns denial and requires `MANAGE_ONLY`; a poisoned writer transitions to diagnostic `HALTED` read-only recovery; no broker submission is authorized from memory alone | Retain this invariant unless a future design receives explicit capital-safety approval |
| Broker transaction reconciliation | **Golden-path runtime pass; adverse gates open** | Real open and forced full reduction reconciled broker/runtime/persistence to the same 0.01 open volume and then to flat; uncertain-outcome, history snapshot, indexed fill, backlog, two-pass mismatch, and supervised recovery changes are wired | Partial fills, remainder cancellation, order deletion/rejection, modification acknowledgement, timeout/late-fill, out-of-order, and restart demo tests |
| Canonical receipts | **Deterministic unit pass; corpus proof open** | UTC/UTF-8 receipt helpers, operational-state evidence, negative-decision receipts, real feature ages, bar-level deduplication, external UTF-8 vectors, and receipt determinism passed the current unit suite | Link slippage, compare identical full-run receipt hashes, and reconcile sequence outcomes |
| Experiment manifest | **Implemented foundation; external lineage open** | Manifest records operation mode, environment, normalized non-lineage input identity, symbol/broker fingerprints, supplied lineage, and a run-instance audit identity | External verification of source/binary/`.set`/tick/profile hashes and two identical normalized causal corpora |
| Product operation modes | **Implemented; lifecycle matrix open** | Only `TRADING` constructs the manager; `PORTFOLIO_DASHBOARD`, `OPTIMIZATION_STUDIO`, and `REPORT_PROCESSOR` are non-trading status placeholders; `V2_RUN_DISABLED` is halted; the input/mode unit contract passed | Execute all mode/lifecycle cases and prove no broker mutation outside `TRADING` |
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
v2/Clock.mqh
v2/Domain.mqh
v2/ExperimentManifest.mqh
v2/Features.mqh
v2/Identity.mqh
v2/Inputs_V2.mqh
v2/IntelligenceBus.mqh
v2/OnnxLayer.mqh
v2/Normalization.mqh
v2/OperationMode.mqh
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
v2/tests/GOAT2_StateDB_ContractTests.mq5
v2/tests/GOAT2_StateDB_ContractTests.ex5
v2/tests/GOAT2_Gateway_Integration.mq5
v2/tests/GOAT2_Gateway_Integration.ex5
docs/GOAT_EA_V2_FOUNDATION_REVIEW.md
docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md
scripts/check_goat2_boundaries.ps1
scripts/check_goat2_input_schema.py
scripts/generate_goat2_inputs.py
scripts/make_goat2_start_config.py
```

Compile the product candidate with the designated GOAT wrapper:

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\GOAT2 V2.0.mq5"
```

Compile each MQL verification EA independently:

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_Phase1_UnitTests.mq5"

python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_StateDB_ContractTests.mq5"

python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_Gateway_Integration.mq5"
```

The gateway target is tester-only and intentionally enables the test build
behind `GOAT2_TEST_HOOKS`. It must never replace `GOAT2 V2.0.ex5` or be treated
as evidence that the production certification lock is open.

Run the current static gates from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\check_goat2_boundaries.ps1 -RequireGateway

python .\scripts\check_goat2_input_schema.py

python .\scripts\generate_goat2_inputs.py --check
```

For each compile, verify rather than infer:

1. The relevant `compile-codex.log` exists and ends with `Result: 0 errors, 0 warnings`.
2. The expected `.ex5` exists beside its `.mq5`.
3. The binary timestamp is newer than the entrypoint and every included source file.
4. The evidence bundle records the final source and binary SHA-256 values.
5. MT5 runtime evidence prints the expected build ID and `MQL_PROGRAM_PATH` after the EA is removed and reattached.

The three runtime summaries are expected at:

```text
FILE_COMMON\GOAT2\tests\phase1-unit-result.json
FILE_COMMON\GOAT2\tests\state-db-contract-result.json
FILE_COMMON\GOAT2\tests\gateway-integration-result.json
```

All three files contain the exact PASS results recorded in the evidence matrix
above. They remain external verification artifacts: tester results, temporary
`.set` files, and compile logs are not repository source. Preserve their hashes
and run identity in the external evidence bundle rather than committing the
mutable `FILE_COMMON` copies.

## Certification identity and `.set` hashing

The runtime experiment manifest deliberately maintains three different concepts:

- `inputValuesHash` is the SHA-256 of canonical runtime/trading controls. Expected-hash and external-lineage fields are excluded so inserting a hash does not change the object being hashed.
- `manifestId` is a run-instance audit identity and may include creation time. It is not the stable key for comparing two otherwise identical runs.
- the literal `.set` file SHA-256 belongs to the external certification evidence bundle generated before the run. It proves the exact bytes delivered to MT5, including encoding and tester serialization.

The normalized hash is not a substitute for the literal artifact hash. A certified run requires both, plus the final source hash, `.ex5` hash, git commit, V1 reference commit, tick-data identity, test model/window, broker-profile identity, and any active State Pack/calendar/model hashes. Identical-run certification compares normalized causal event and receipt corpora; it does not require two attach-time manifest IDs to be equal.

## Durability, capacity, and retention

Every broker mutation requires a durable order intent and receipt before submission. This includes actions that reduce risk. V2.0 does not submit a close, partial close, modification, cancellation, open, or add from a process-memory-only emergency record. If SQLite cannot durably write, the operation is denied and the engine moves to `MANAGE_ONLY`; a poisoned writer is labeled `HALTED` and remains diagnostic/read-only until a reviewed reopen/restart. Existing broker-hosted stops and targets, where present, remain the crash-independent protection layer. Because a database outage also prevents a new reduction request, live certification must prove that every allowed exposure has adequate broker-hosted protection before this durability policy can be promoted.

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

1. Final production, unit, StateDB-contract, and gateway-integration binaries compile with `0 errors, 0 warnings` and fresh timestamps.
2. Final static boundary, schema parity, and schema-to-MQL declaration-generation gates pass.
3. The unit, StateDB-contract, and real-gateway EAs each emit their manifested PASS result; the gateway result proves broker/runtime/persistence reconciliation to flat.
4. Cost-complete MLPS fixtures pass across the approved broker/symbol matrix.
5. PORT/PARITY command traces are green or every divergence has an approved delta disposition.
6. Two identical manifested tester runs produce identical canonical event and receipt hashes.
7. Crash, restart, corruption, write-failure, and repeated-recovery tests pass.
8. Partial-fill, cancellation, rejection, timeout/late-fill, sub-minimum dust close, and out-of-order demo tests pass.
9. Broker-profile, session, feed, licence, and protective-management prerequisites are verified, including broker-hosted protection during database loss.
10. All public operation modes pass lifecycle/no-mutation tests, and HUD/overlay interaction and performance gates pass for the scope being promoted.
11. Journal retention, capacity monitoring, backup, and restore policies are approved and tested.
12. The final evidence pack is reviewed and the certification macro change receives explicit written approval.

Phase 2 Feed v2/replay, Phase 3 ONNX, Phase 4 multi-symbol portfolio production, and Phase 5 GOAT Ops retain their own later approval gates. Phase-1 certification does not authorize those capabilities.
