# GOAT2 V2.0 Foundation Review Implementation Record

**Implementation date:** 2026-07-11
**Final evidence freeze:** 2026-07-12
**Review source:** `docs/GOAT_EA_V2_FOUNDATION_REVIEW.md`
**Reviewed baseline:** commit `95c4692` (`Build fresh GOAT2 V2.0 foundation`)
**Product entrypoint:** `GOAT2 V2.0.mq5`

## Outcome and certification posture

The foundation review fix pack has been implemented as a forward-only GOAT2 change set. No GOAT V1 source, include, binary, or release-history artifact is an implementation target for this work.

This record is a code-review handoff, not a live-trading approval. The production entrypoint intentionally retains:

```mql5
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 0
```

That compile-time lock keeps new exposure unavailable in the production candidate. A separate, independently reviewed certification build is required before it can ever be changed to `1`. The guarded gateway integration harness is a distinct tester-only executable; its local test macro does not alter the production binary or production lock.

The final production candidate and all three verification EAs compile with `0 errors, 0 warnings`. The unit contract passed 171/171 checks, the StateDB contract passed 21/21 checks, and the real gateway harness passed its EURUSD open/reconcile/high-water-latch-rearm/three-pass-re-promotion/force-reduce/reconcile-flat golden path. These passes close the review-fix proof surface they directly exercise; they do not close V1 PORT/PARITY, identical full-run corpus, adverse broker, crash/restart/corruption, retention, or full Phase-1 certification gates.

## Evidence labels used here

| Label | Meaning |
|---|---|
| `SOURCE_IMPLEMENTED` | The reviewed code path and its call sites were changed and inspected, but that fact alone is not runtime proof. |
| `STATIC_PASS` | A named static checker completed successfully against the current implementation surface. |
| `COMPILE_PASS` | The named MQL target compiled with `0 errors, 0 warnings`; runtime behavior is not implied. |
| `RUNTIME_PASS` | The exact named executable emitted a reviewed machine-readable PASS artifact for its stated scope. |
| `PENDING_FINAL_COMPILE` | The target must be rebuilt after the complete final source/encoding pass. |
| `PENDING_RUNTIME` | The executable test and result contract exist, but no reviewed PASS artifact is claimed here. |
| `OPEN_CERTIFICATION_GATE` | Broader demo, replay, fault-injection, parity, determinism, or operational evidence remains mandatory. |

No unevaluated `PENDING_RUNTIME` or `OPEN_CERTIFICATION_GATE` item is represented as PASS, and no scoped `RUNTIME_PASS` is generalized beyond its exercised path.

## Reviewer required-fix gate: implementation map

| Workstream | Review finding(s) | Implemented design | Primary files | Evidence state at this record |
|---|---|---|---|---|
| 1. Real reduction lineage and dust-safe close | §3.1, §4.11 | Reduction actions carry the broker `POSITION_IDENTIFIER`; sub-minimum real positions remain eligible for an exact full close; partial closes that would leave untradeable dust are promoted to full close. A guarded tester harness drives the real manager → safety kernel → gateway → broker → reconciliation path. | `v2/PortfolioManager.mqh`, `v2/BrokerGateway.mqh`, `v2/SafetyKernel.mqh`, `v2/tests/GOAT2_Gateway_Integration.mq5` | Harness `COMPILE_PASS` and `RUNTIME_PASS` for real EURUSD 0.01 open/reconcile/forced-full-reduction/flat; sub-minimum broker fixture remains open |
| 2. Uncertain broker outcomes | §3.2, §3.3 | Timeout/connection/indeterminate outcomes enter `RECONCILE_REQUIRED` even when `OrderSend` returns false; `GetLastError()` is retained as evidence. Initial entry and reduction submissions remain pending/manageable during uncertainty and do not manufacture `SEQUENCE_ENDED`. | `v2/BrokerGateway.mqh`, `v2/PortfolioManager.mqh`, `v2/Domain.mqh`, `v2/StateDB.mqh` | `SOURCE_IMPLEMENTED`; adverse broker/runtime injection remains `OPEN_CERTIFICATION_GATE` |
| 3. Lease correctness | §4.1 and lease-related medium findings | The exclusive lease sentinel uses `FILE_ANSI`, validates encoded bytes and file size, uses the V2 UTC clock, and fails closed on future/regressed heartbeats. A dedicated contract EA covers exclusive acquisition, denial while held, and takeover after release. | `v2/StateDB.mqh`, `v2/Clock.mqh`, `v2/tests/GOAT2_StateDB_ContractTests.mq5` | StateDB test `COMPILE_PASS`; 21/21 `RUNTIME_PASS` includes lease exclusivity/release behavior |
| 4. UTC and UTF-8 evidence | §4.14, §4.15 | Causal event, receipt, manifest, lease, recovered observations, and manager wall-clock writes use the shared UTC clock. Broker-history queries convert UTC boundaries back to broker-server time. UTF-8 helpers convert the whole encoded array and remove only the terminal NUL before hashing. External UTF-8 SHA vectors and receipt-determinism fixtures were added to the unit EA. | `v2/Clock.mqh`, `v2/Receipts.mqh`, `v2/ExperimentManifest.mqh`, `v2/PortfolioManager.mqh`, `v2/StateDB.mqh`, `v2/tests/GOAT2_Phase1_UnitTests.mq5` | Unit EA 171/171 `RUNTIME_PASS`; cross-offset live/demo and identical full-run corpus remain open |
| 5. StateDB write latch, migration, recovery, and checkpoints | §4.2, §4.3, §4.4 | Every public mutator is guarded by the writable contract; failed writes poison the writer and the manager reports `HALTED` read-only state. Schema v4 adds a named additive v3→v4 migration, immutable migration ledger, append-only journal guards, inherited verification checkpoints, canonical submission-status bridges, and canonical high-water comparison. Explicit/automatic read-only recovery, member snapshots, and offline-only repair plans preserve diagnostic access without authorizing broker mutation. | `v2/StateDB.mqh`, `v2/PortfolioManager.mqh`, `v2/tests/GOAT2_StateDB_ContractTests.mq5` | StateDB contract 21/21 `RUNTIME_PASS`; migration/corruption/full-disk/restart proof remains `OPEN_CERTIFICATION_GATE` |
| 6. Reconciliation stability and supervised re-promotion | §4.5–§4.8 | Deal tickets are snapshotted before nested history-selection calls; terminal initial-entry rejection can settle a flat active sequence; deal lookup is indexed; continuous broker matching requires empty ring/DB backlogs, strict physical-volume equality, and two stable mismatch passes. Only named transient states enter a fresh three-pass audit, the failing pass never counts, and re-promotion rechecks recovery, durability, gateway, run/compile, and retained broker-profile prerequisites. | `v2/PortfolioManager.mqh`, `v2/StateDB.mqh`, `v2/BrokerGateway.mqh` | Gateway `RUNTIME_PASS` proves writable high-water latch resynchronization and exactly three fresh healthy passes; actual poisoned-write recovery, broker timing, rejection, ordering, restart, and idempotency remain `OPEN_CERTIFICATION_GATE` |
| 7. V1 core fidelity corrections | §4.9, §4.10 and core medium findings | PeakSmart now returns `HOLD_WHILE_UNDERWATER`, `ADVANCE_WITHOUT_CLOSE`, or `CLOSE_AND_ADVANCE`; the manager advances only on the latter two. Flexibility above `1` is neutralized to the V1 factor. Disabled `Grid_Min` restores the V1 half-ATR floor; `Grid_Factor=0` fails closed; retrace lots round to nearest step; the basket contract receives explicit executed-trade count; V1 input pips translate as `10 × point`; `OrderCalcProfit` uses a valid calculation volume and scales the result. | `v2/Core_Sequence.mqh`, `v2/Core_Risk.mqh`, `v2/PortfolioManager.mqh`, `v2/tests/GOAT2_Phase1_UnitTests.mq5` | Unit fixtures `RUNTIME_PASS`; V1 PORT trace proof remains `OPEN_CERTIFICATION_GATE` |
| 8. Shared normalization, safety monotonicity, and intent enforcement | §4.11–§4.13 and kernel medium findings | Safety and gateway share one price normalizer with tick-size→point fallback. The exact final normalized request is rechecked immediately before submission. Safety validates stops/freeze constraints. Cancellation protectiveness is derived from the selected broker order. Production intent changes route through `CV2OrderIntentMachine`, with a matching persistence transition guard. | `v2/Normalization.mqh`, `v2/SafetyKernel.mqh`, `v2/BrokerGateway.mqh`, `v2/Domain.mqh`, `v2/PortfolioManager.mqh`, `v2/StateDB.mqh` | Unit matrix and normal 0.01 real-gateway path `RUNTIME_PASS`; adverse/dust matrix remains open |
| 9. Executable evidence surface | §4.16 | The deterministic unit surface was expanded to 171 assertions with independent constants, core fixtures, safety matrix cases, physical dust/fill completion, uncertainty/cancel correlation, source-age boundaries, UTF-8 vectors, receipt determinism, and input/mode contracts. Separate StateDB and real-gateway contract EAs emit machine-readable result artifacts. | `v2/tests/GOAT2_Phase1_UnitTests.mq5`, `v2/tests/GOAT2_StateDB_ContractTests.mq5`, `v2/tests/GOAT2_Gateway_Integration.mq5`, `v2/tests/cases.json` | All targets `COMPILE_PASS`; artifacts `RUNTIME_PASS` (171/171 unit, 21/21 StateDB, gateway golden path); identical full-run corpus remains `OPEN_CERTIFICATION_GATE` |
| 10. Negative-decision and operational receipts | Missing-receipt and support findings | `SEQ_START_SUPPRESSED`, `LEVEL_SKIP`, and `SHADOW_DECISION` are emitted with bar-level deduplication; operational-state transitions are also persisted as causal evidence. Feature snapshots carry actual closed-bar source ages. Shadow output is explicitly counterfactual and not presented as applied policy. | `v2/PortfolioManager.mqh`, `v2/Receipts.mqh`, `v2/Features.mqh`, `v2/Policy.mqh` | Unit receipt determinism `RUNTIME_PASS`; identical full-run corpus remains open |
| 11. Product operation modes | Blueprint/product-surface and domain/input findings | The exact public modes are `TRADING`, `PORTFOLIO_DASHBOARD`, `OPTIMIZATION_STUDIO`, and `REPORT_PROCESSOR`. Only `TRADING` constructs the portfolio manager or receives broker lifecycle events. The other modes are non-trading status placeholders with neutral tester score. `V2_RUN_DISABLED` is a halted, no-broker-work state rather than a manage-only alias. | `v2/OperationMode.mqh`, `v2/Inputs_V2.mqh`, `GOAT2 V2.0.mq5`, `v2/ChartHUD.mqh`, `v2/PortfolioManager.mqh`, `v2/ExperimentManifest.mqh` | Final product `COMPILE_PASS`; input/mode unit contract `RUNTIME_PASS`; full lifecycle/no-mutation mode matrix remains open |
| 12. Input/schema parity and generation contract | Input-contract and schema findings | The V2 input surface is organized into 17 groups and 81 fields. The schema deterministically generates the marker-bounded MQL declaration region, validates enum maps/defaults/order, embeds its pinned exact-byte SHA-256, and preserves UTF-8 BOM/CRLF. | `v2/Inputs_V2.mqh`, `v2/schema/inputs_v2.schema.json`, `v2/tests/cases.json`, `scripts/generate_goat2_inputs.py`, `scripts/check_goat2_input_schema.py`, `.gitattributes` | Declaration generation and 81/81 parity `STATIC_PASS`; executable default/boundary 171/171 `RUNTIME_PASS`; `.set`, validation, and documentation generation remain open |

## Detailed CRITICAL/HIGH finding crosswalk

| Finding | Disposition | Evidence still required |
|---|---|---|
| §3.1 dead forced-reduction path | Correct broker position identity is populated. The real gateway harness passed open → reconcile → forced full reduction → broker/runtime/DB flat. | Preserve the exact artifact; add adverse and sub-minimum broker fixtures. |
| §3.2 uncertain entry ended prematurely | `RECONCILE_REQUIRED` remains pending and manageable; only terminal rejection can close a flat initial sequence. | Timeout/late-fill demo or deterministic broker-fault injection. |
| §3.3 `OrderSend==false` uncertainty gap | Uncertainty classification uses retcode semantics independent of the boolean return and records terminal error evidence. | Timeout/connection/retcode-zero scenario matrix. |
| §4.1 lease sentinel availability | ANSI byte contract and exclusive-open behavior implemented; isolated StateDB contract passed 21/21 overall, including lease ownership/release cases. | Add stale/future-heartbeat, crash-owner, and real-terminal restart fixtures. |
| §4.2 writable latch bypass | Public mutation surface is guarded and write failures poison the writer. | Fault-injection sweep over every mutation family. |
| §4.3 no migration/read-only recovery | Additive v3→v4 migration and diagnostic read-only recovery exist; repair plans are deliberately offline-only. | Real v3 fixture migration, corrupt-row fixture, backup/restore drill, and operator procedure. |
| §4.4 O(N) verification at every open | A verified inherited checkpoint makes normal startup incremental; explicit full-genesis audit remains available. | Large-journal timing, tamper/corruption, and checkpoint-loss tests. |
| §4.5 history-pool corruption | Deal ticket IDs are snapshotted before any nested history call can reset selection state. | Multi-deal/out-of-order tester or demo trace. |
| §4.6 async rejection wedge | A terminal rejected initial entry can end the flat sequence after reconciliation proves no exposure. | Async rejection scenario proving the next sequence is not wedged. |
| §4.7 broker-match TOCTOU | Broker match waits for both in-memory and DB observation backlogs to drain and requires two stable mismatch samples. | Server-side TP/SL event racing `OnTimer`, plus backlog > ring capacity. |
| §4.8 one-way operational ratchet | A fresh audit of exactly three healthy supervision passes can restore named transient states; failing passes and pre-degradation health never count, and every baseline new-risk prerequisite is rechecked. The gateway harness passed writable high-water latch rearm and three-pass re-promotion probes. | Actual poisoned-write recovery remains a restart/fault-injection gate; broader degrade/recover matrix still required. |
| §4.9 PeakSmart underwater burn | Tri-state decision preserves the armed trigger while underwater; the deterministic unit fixture passed. | V1 PORT golden trace. |
| §4.10 flexibility >1 rejection | Values above `1` use neutral V1 behavior; non-finite and below-`-1` remain invalid; the unit fixture passed. | Migrated `.set` and V1 PORT fixture. |
| §4.11 sub-minimum full close | Exact full reduction preserves actual broker volume; residual-dust partial reductions become full close. | Gateway integration plus a broker/spec-change dust fixture. |
| §4.12 divergent normalizers/pre-check | One shared price normalizer is used and `OrderCheck` sees the final request. | Broken tick-size metadata and stops/freeze tester cases. |
| §4.13 ornamental intent machine | Production transitions use the domain machine; StateDB transactionally replays the canonical `PERSISTED → SUBMITTED → terminal/reconcile` path and rejects regressions. Cancel target tickets are persisted before submission. | Broader recovery/retry/fill/cancel transition fault matrix. |
| §4.14 server time presented as UTC | Causal wall clocks use `TimeGMT` through `v2/Clock.mqh`; history selection alone converts to server time. | Cross-offset live/demo evidence and identical-run corpus proof. |
| §4.15 UTF-8 truncation | Whole UTF-8 byte arrays are hashed after terminal-NUL removal; external vectors and receipt determinism passed in the 171-check artifact. | Cross-language corpus verifier and identical full-run evidence. |
| §4.16 insufficient/unexecuted tests | Unit suite and two isolated contract EAs were expanded/created, compiled 0/0, and emitted scoped PASS artifacts. | Full parity corpus, repeated-run hash identity, randomized/property coverage, and adverse fault-injection suites. |

## Medium-finding disposition

The review's medium findings were treated as engineering requirements where they could be closed safely inside this foundation iteration. This is the explicit disposition so a co-developer can distinguish completed work from carried risk.

### Closed in source, pending execution evidence

- StateDB intent-status regression prevention; ANSI/UTC/future-heartbeat lease behavior; writer poisoning; append-only guards; checkpoints; explicit read-only recovery; offline-only member repair planning.
- Indexed deal-event lookup, history-ticket snapshotting, two-pass broker mismatch confirmation, DB-backlog awareness, and supervised operational recovery.
- V1 half-ATR `Grid_Min` behavior, fail-closed zero `Grid_Factor`, V1 pip migration, nearest retrace volume rounding, explicit executed-trade count, and valid-volume `OrderCalcProfit` scaling.
- Broker-derived cancellation classification, stop/freeze validation, and terminal/account/tick-derived session, feed, and trade-authorization context.
- ENDED-sequence quarantine guard, real `REDUCE_ONLY` use, rejection of UNKNOWN/NEUTRAL fill effects, halted `V2_RUN_DISABLED`, and causal operational-state receipts.
- Negative-decision receipts, actual feature source ages, and honest counterfactual shadow semantics.

### Final adversarial hardening after the review crosswalk

- Broker rejection and uncertainty now persist every canonical intent state transactionally; the 21-check StateDB contract proves rejected and `RECONCILE_REQUIRED` outcomes can bridge from the durable pre-send intent and remain recoverable.
- Broker position presence, fill completion, level closure, reduction completion, recovery comparison, and sequence ending use a physical floating-point noise floor. A current broker volume step is never used to declare a smaller real position nonexistent.
- Recovered deal-observation timestamps are converted from broker-server time to UTC, and closed-bar feature ages begin at the value's availability boundary.
- Runtime writer poisoning is surfaced as `HALTED` diagnostic read-only state. No tick, timer, transaction, chart, or shutdown path gains broker-mutation authority from that state.
- Supervised re-promotion starts a new counter only for named transient causes, excludes the failing pass, requires three stable passes, and rechecks the retained broker-profile prerequisite before any certified new-risk state can return.
- Cancellation intent correlation preserves the target order ticket before `OrderSend`, including when the broker result omits `result.order`.

### Deliberately retained or still open

- The V1 compatibility MLPS overshoot behavior remains quarantined in the compatibility lane and must never be wired into live sizing.
- Projection/journal atomicity, full-disk behavior, restore/repair operations, telemetry capacity semantics, large-journal performance, and retention remain certification work even with the new guards.
- Manager throughput under sustained tick load, starvation/fairness under a repeatedly failing work item, stale cross-sequence intent recovery, and crash-timing permutations need executable stress evidence.
- Kernel error-budget weighting/persistence, independent worst-case sequence-loss computation, hedged-side gross-exposure semantics, and deposit/withdrawal-aware equity ratcheting remain design/certification items.
- Runtime magic-collision enforcement, the complete V1 signal surface, virtual/delayed sequences, MustCheck parity, and bias/state rescue remain governed by `docs/V1_TO_V2_DELTA.md`.
- Receipt serializer performance, journal/outbox scale, and the identical-run canonical corpus gate remain open.
- The manifest ID is a run-instance audit identity and may include creation time. Stable semantic comparison uses `inputValuesHash`; external evidence also records the literal `.set`, source, binary, tick-data, and broker-profile hashes. Identical-run certification compares normalized causal event/receipt corpora, not attach-time manifest identity.
- LOW findings remain governed by the independent review. None is silently closed merely because it is not repeated in the required-fix table.

## Verification ledger at handoff

| Check | Current evidence |
|---|---|
| V2 boundary audit | `STATIC_PASS`: 27 source files, one permitted raw mutation site in `v2/BrokerGateway.mqh`, zero bypasses, zero V1 includes, zero detected secrets. |
| Input/schema audit | `STATIC_PASS`: deterministic schema-to-MQL declaration generation and 81/81 parity pass across 17 groups; generated MQL embeds schema SHA-256 `4B440C02E7BC032F722230E657B80C0820C88366A0A7926F2E73C2A0992B3B29`. `.set`, validation, and documentation generation remain open. |
| Committed JSON documents | `STATIC_PASS`: schema and test-case JSON parse successfully. |
| Phase-1 unit EA compile | `COMPILE_PASS`: `0 errors, 0 warnings`; source SHA-256 `09B0492A424593CE2E165757A78B3894892598A8E8EE2C527441404E6687FD49`; binary SHA-256 `1F6A1EADABA52DC6733D6F02E5B9B8800202369D8A5614F506AF8AC6F0E6ED37`; 192,940 bytes at 2026-07-12 00:11:32. |
| StateDB contract EA compile | `COMPILE_PASS`: `0 errors, 0 warnings`; source SHA-256 `48F03F1A33AE49EFE95EAAF0B40572A3241B3BFE20C8532B30FA0A1BC4995FAD`; binary SHA-256 `55FC067872800E7FEED91AC2C818DEF7C3EF325AB9B00D16ABBAF6D2869E6378`; 149,500 bytes at 2026-07-12 00:11:40. |
| Gateway integration EA compile | `COMPILE_PASS`: `0 errors, 0 warnings`; source SHA-256 `93706A02B3AE66FC0B957EFE7ECADB84974AC5D061DD068AE74ADD7272BA9884`; binary SHA-256 `2BF2CF95DCF2664F23B4AF92E4CA6E4E3BFE886A1F0BC9F1CD7D89BD1502FE73`; 488,540 bytes at 2026-07-12 00:11:54. |
| Production EA final compile | `COMPILE_PASS`: `0 errors, 0 warnings`; entrypoint SHA-256 `F5BE49FA2ABB4DC78CBEF63AFE355CA31036636CA9D4312CD5B896849742D23C`; binary SHA-256 `8538C05F0CC6907BDA1CC9F2BC41C91925F6215218FA435F17C51F911B7F4047`; output 465,766 bytes at 2026-07-12 00:11:23. |
| Unit result | `RUNTIME_PASS`: 171/171, 0 failed, EURUSD. Artifact SHA-256 `627C28AC36753D9C97D6655CFD15970ACFFCFED49D414F9276E07C259A1E9CED`. |
| StateDB result | `RUNTIME_PASS`: 21/21, 0 failed. Artifact SHA-256 `3C2D75EE55B46EF76A0C6C13F0237E66D03AA803B6C3459F78D82C8DBD8A4A80`. |
| Gateway result | `RUNTIME_PASS`: real non-mock EURUSD LONG 0.01 open; broker/runtime/persisted volume reconciled to 0.01; writable high-water latch rearm and supervised three-pass re-promotion verified; forced full reduction; final broker/runtime/persisted volumes all zero; both sequence statuses ENDED; no pending execution. Artifact SHA-256 `A213CB5C992CE258ADA4587CB78DF11F412BA9BEA4FC3D32E1FC6A8C06605C56`. |
| Identical manifested full runs | `OPEN_CERTIFICATION_GATE`. |
| PORT/PARITY corpus | `OPEN_CERTIFICATION_GATE`. |
| Crash/restart/corruption/full-disk/broker-fault evidence | `OPEN_CERTIFICATION_GATE`. |

The ledger is intentionally time-scoped. The external release evidence must retain the exact artifact hashes, compile-log result lines, timestamps, tester model/window, terminal build, symbol/broker identity, and the git commit that produced them.

## Reviewer handoff map

Start with these files:

```text
GOAT2 V2.0.mq5
v2/Clock.mqh
v2/Normalization.mqh
v2/OperationMode.mqh
v2/Domain.mqh
v2/Core_Sequence.mqh
v2/Core_Risk.mqh
v2/SafetyKernel.mqh
v2/BrokerGateway.mqh
v2/StateDB.mqh
v2/PortfolioManager.mqh
v2/Receipts.mqh
v2/Features.mqh
v2/ExperimentManifest.mqh
v2/Inputs_V2.mqh
v2/schema/inputs_v2.schema.json
scripts/generate_goat2_inputs.py
scripts/check_goat2_input_schema.py
v2/tests/GOAT2_Phase1_UnitTests.mq5
v2/tests/GOAT2_StateDB_ContractTests.mq5
v2/tests/GOAT2_Gateway_Integration.mq5
v2/tests/cases.json
docs/GOAT_EA_V2_FOUNDATION_REVIEW.md
docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md
docs/V2_BUILD_STATUS.md
docs/V2_PHASE1_ACCEPTANCE.md
docs/V1_TO_V2_DELTA.md
```

The independent review remains the source of the original findings. This implementation record states their disposition and evidence level; it does not overwrite or weaken the review.

## Promotion boundary

Completion of this fix pack does not authorize:

- live new risk;
- changing `GOAT2_PHASE1_EXECUTION_CERTIFIED`;
- claiming V1 parity or performance improvement;
- multi-symbol/member production behavior;
- Feed v2, replay, ONNX influence, or GOAT Ops autonomy;
- treating a compile as a runtime PASS.

The complete promotion checklist remains in `docs/V2_BUILD_STATUS.md` and `docs/V2_PHASE1_ACCEPTANCE.md`.
