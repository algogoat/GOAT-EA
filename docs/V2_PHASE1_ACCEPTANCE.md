# GOAT2 V2.0 Phase 0/1 Acceptance Contract

## Product boundary

`GOAT2 V2.0.mq5` is a fresh EA product. The current candidate is a single-symbol, single-member Phase 0/1 development foundation. It does not claim completed Phase-1 certification, live readiness, or portfolio-capable production behavior. Feed v2, State Pack, ONNX influence, multi-symbol/member production, and GOAT Ops remain disabled or deferred until their later gates are satisfied.

The public operation modes are `TRADING`, `PORTFOLIO_DASHBOARD`, `OPTIMIZATION_STUDIO`, and `REPORT_PROCESSOR`. Only `TRADING` may construct the portfolio manager or receive broker lifecycle events. The other modes are non-trading placeholders for later product phases; their presence is not acceptance of a completed dashboard, optimizer, or report processor.

Virtual/delayed sequences, complete MustCheck revalidation, bias/state rescue, and the complete active V1 signal surface are also deferred. A PORT/PARITY case that depends on one of those behaviors cannot be represented as green until the relevant behavior has an approved `PORT`, `REDESIGN`, `DEFER`, or `NOT_APPLICABLE` disposition and the test matrix reflects it.

## Mandatory build gates

1. The V2 entrypoint and all V2 includes compile with `0 errors, 0 warnings` on the designated GOAT MetaEditor.
2. No V1 `.mq5`, `.mqh`, or `.ex5` artifact changes.
3. New risk is physically disabled in this candidate by `GOAT2_PHASE1_EXECUTION_CERTIFIED=0`. Runtime inputs cannot override the compile-time gate.
4. Non-hedging accounts fail initialization before any new-risk path is available.
5. All order opens, adds, modifications, partial closes, full closes, and cancellations route through `CV2BrokerGateway`.
6. `OrderSend` success is recorded as submission evidence, never as fill completion.
7. Broker/order/deal/position identifiers remain `ulong`; identifiers serialized to JSON are strings.
8. Safety decisions are action-aware: entry failure conditions cannot block legitimate exposure reduction.
9. A durable order intent and receipt are recorded before every broker submission.
10. Ambiguous recovery enters `RECOVERY_QUARANTINE`; it never silently adopts exposure.
11. A timeout, connection loss, or otherwise uncertain broker outcome remains `RECONCILE_REQUIRED`; it cannot end a possibly exposed sequence as though rejection were proven.
12. Read-only recovery exposes diagnostic state only. It never authorizes manager work or a broker mutation.
13. The exact normalized request evaluated by the safety kernel is passed through final `OrderCheck` before `OrderSend`.
14. Causal timestamps are UTC, while broker-history boundaries use an explicit UTC-to-server conversion. Canonical hashes use the complete UTF-8 byte sequence.
15. `V2_RUN_DISABLED` is halted and performs no broker work. It is not a manage-only alias.

There is no process-memory-only emergency broker exception. If durable persistence is unavailable, every broker submission fails closed and the EA enters or remains in `MANAGE_ONLY`; a poisoned writer is surfaced as `HALTED` diagnostic read-only recovery. This includes full closes, partial closes, protective modifications, and cancellations as well as opens and adds. Existing broker-hosted protective orders, where present, are the persistence-independent fail-safe while the database is unavailable. Certification must therefore prove that every permitted exposure has adequate broker-hosted protection for this failure mode.

The causal event and receipt journal is append-only and unbounded for this development candidate. It is never silently pruned. Storage-capacity and database-write failures fail closed. Production retention, archival, proactive disk monitoring, backup, restore, and full-disk testing are mandatory pre-certification gates.

## Deterministic verification

- Domain transition tests reject illegal event sequences and replay the same event stream to identical canonical state.
- Lot-ladder tests cover every progression mode, normalization step, cap, and pathological input.
- Risk tests compare projected adverse loss with `OrderCalcProfit`-based path calculations including configured costs.
- Safety tests cover every action class and operational state.
- Static source audit finds no broker mutation outside `v2/BrokerGateway.mqh`.
- The authoritative input schema deterministically regenerates the marker-bounded MQL declaration block, whose embedded SHA-256 matches the pinned LF schema artifact; 81/81 declaration parity also passes.
- Two identical manifested tester runs produce identical canonical event/receipt hashes.
- Recovery tests prove repeated reconciliation is idempotent.
- The isolated StateDB contract proves ANSI lease exclusivity, explicit read-only access, denied mutation, diagnostic reads, and full-audit availability.
- The guarded real-gateway harness proves open → reconciliation → forced full reduction → broker/runtime/persistence reconciliation to flat, writable high-water readiness rearm, and exactly three fresh healthy passes before supervised re-promotion on a hedging Strategy Tester account.

The executable contracts emit these machine-readable summaries:

```text
FILE_COMMON\GOAT2\tests\phase1-unit-result.json
FILE_COMMON\GOAT2\tests\state-db-contract-result.json
FILE_COMMON\GOAT2\tests\gateway-integration-result.json
```

The test source or a clean compile is not acceptance. Each applicable result must be PASS, tied to the exact final binary and tester identity, and independently reviewed.

Golden-master verification has two deliberately separate lanes:

- **PORT/PARITY:** recorded V1 commands drive the V2 execution core with fixed starting lots and legacy news/bias disabled. Level geometry, lot deltas, sequence events, and exits are compared directly.
- **MLPS CERTIFICATION:** cost-complete V2 risk sizing is verified against adverse `OrderCalcProfit` paths plus spread, commissions, swap, and close costs. Metric divergence from V1 is an approved redesign delta, not tolerance widening.

End-to-end V1 signal parity is not represented by V2's disabled-by-default generic signal adapter. Certification uses recorded V1 command/signal traces until the complete active V1 signal surface has a separately approved port disposition.

The experiment manifest records a normalized, non-lineage `inputValuesHash`. Expected and external lineage inputs are excluded to avoid a self-hash cycle. Its `manifestId` is a run-instance audit identity and may include creation time; it is not the stable equality key for two runs. The literal SHA-256 of the `.set` file is a separate required artifact in the external certification evidence bundle. Certification requires the semantic input hash, literal artifact hash, and normalized causal event/receipt comparison; none replaces another.

## Review-fix evidence boundary

The implementation disposition for every independent foundation-review finding is maintained in `docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md`. At the review-fix handoff:

- the V2 mutation-boundary audit, 81/81 input/schema audit, and schema-to-MQL declaration generator are static passes;
- the final production candidate and all three verification EAs compile with `0 errors, 0 warnings` and fresh outputs;
- the unit artifact is PASS at 171/171, the StateDB artifact is PASS at 21/21, and the real gateway artifact is PASS for a non-mock EURUSD 0.01 open/reconcile/writable-high-water-latch-rearm/three-pass-re-promotion/forced-full-reduction/reconcile-flat path;
- the compile-time production certification lock remains `0` regardless of any tester-only harness result.

These scoped passes and their hashes are recorded in `docs/V2_BUILD_STATUS.md` and `docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md`. They do not imply V1 parity, identical full-run corpus determinism, adverse broker-path coverage, crash/restart proof, or Phase-1 certification.

## Evidence still requiring external/runtime assets

- Eight representative V1 `.set` artifacts have been locally inventoried and hash-matched in `v2/tests/cases.json`; a portable evidence bundle and the corresponding V1 decision/command traces remain required.
- Demo-account restart, actual poisoned-write recovery, partial-fill, broker-spec-change dust close, timeout/late-fill, out-of-order transaction, and broker-profile tests.
- Repeated-run event/receipt hash identity; crash/recovery fixtures; full-disk/write-failure evidence; and adverse broker paths beyond the passed golden-path harness.
- Schema v3→v4 migration fixtures, corruption/read-only recovery, large-journal checkpoint timing, offline repair procedure, and backup/restore proof.
- Lifecycle/no-mutation proof for all four operation modes and halted `V2_RUN_DISABLED`.
- HUD/overlay interaction, pixel, and render-budget verification for any promoted UI scope.
- Feed v2 exact-availability State Packs and GOAT AI app endpoints (Phase 2).
- Signed ONNX model bundles and platform registry (Phase 3).
- Portfolio canary and platform command surfaces (Phase 4).

No missing external or runtime evidence is converted into a success claim. It remains an explicit open gate. The live matrix is maintained in `docs/V2_BUILD_STATUS.md`.
