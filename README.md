## GOAT-EA

Expert Advisor (EA) project for MetaTrader 5, maintained in the `GOAT-EA` repository.

### GOAT2 V2.0 development foundation

`GOAT2 V2.0` is a fresh product line with its own entrypoint, include graph, input contract, persistence layer, tests, and binary. It does not include or modify the GOAT V1 implementation. The current candidate is deliberately scoped as a **single-symbol, single-member Phase 0/1 development foundation**. It is not a certified live release and is not yet a production multi-symbol portfolio engine.

New exposure is physically disabled in this source tree by:

```mql5
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 0
```

Changing runtime inputs cannot bypass that compile-time gate. It may be changed only through the controlled certification workflow after the PORT/PARITY, cost-risk, replay, crash/recovery, broker/demo, and other evidence gates in [the V2 build status](docs/V2_BUILD_STATUS.md) are complete.

The V2 product surface is isolated under these paths:

```text
GOAT2 V2.0.mq5                  thin lifecycle entrypoint and certification lock
GOAT2 V2.0.ex5                  matching compiled candidate binary
v2/Domain.mqh                   domain events and legal state transitions
v2/Identity.mqh                 deployment, member, sequence, intent, and magic identity
v2/Clock.mqh                    shared UTC wall-clock and broker-time conversion helpers
v2/Normalization.mqh            shared tick-size/point price normalization contract
v2/OperationMode.mqh            public product modes and execution-path permissions
v2/Inputs_V2.mqh                V2-only input declarations and validation
v2/Core_Sequence.mqh            grid, lot, basket, trailing, and retrace geometry
v2/Core_Risk.mqh                V1 compatibility lane and cost-complete MLPS lane
v2/SafetyKernel.mqh             deterministic, action-aware safety decisions
v2/BrokerGateway.mqh            only permitted raw broker-mutation boundary
v2/StateDB.mqh                  SQLite journal, projections, lease, and recovery records
v2/Receipts.mqh                 canonical local execution receipts
v2/ExperimentManifest.mqh       runtime and external experiment lineage
v2/Telemetry.mqh                bounded local telemetry outbox contract
v2/Scheduler.mqh                current single-symbol work scheduler
v2/Features.mqh                 deterministic Phase-1 feature frame and signal adapter
v2/IntelligenceBus.mqh          disabled/shadow interface for later Feed v2 work
v2/Policy.mqh                   deterministic policy envelope
v2/ReplayPack.mqh               disabled Phase-2 replay-pack interface
v2/OnnxLayer.mqh                disabled Phase-3 ONNX interface
v2/ChartHUD.mqh                 local canvas HUD foundation
v2/ChartOverlay.mqh             chart-overlay foundation
v2/PortfolioManager.mqh         current single-member lifecycle coordinator
v2/schema/                      committed input and intelligence contracts
v2/reference/                   pinned V1.42 comparison manifest
v2/tests/                       unit, StateDB, and real-gateway tester contracts
scripts/check_goat2_boundaries.ps1
scripts/check_goat2_input_schema.py
scripts/generate_goat2_inputs.py
scripts/make_goat2_start_config.py
docs/GOAT_EA_V2_BLUEPRINT.md
docs/GOAT_EA_V2_FOUNDATION_REVIEW.md
docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md
docs/V2_PHASE1_ACCEPTANCE.md
docs/V2_BUILD_STATUS.md
docs/V1_TO_V2_DELTA.md
```

#### Compile and static verification

Use the designated Terminal 2 - GOAT MetaEditor through the reliable compile wrapper. GOAT2 must be selected explicitly because the wrapper's default auto-detection targets the latest `GOAT V*.mq5` V1 entrypoint.

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\GOAT2 V2.0.mq5"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\check_goat2_boundaries.ps1 -RequireGateway

python .\scripts\check_goat2_input_schema.py

python .\scripts\generate_goat2_inputs.py --check
```

Compile each MQL verification EA separately. The gateway target is a guarded
tester-only executable; its certification macro does not alter the production
entrypoint or production binary:

```powershell
python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_Phase1_UnitTests.mq5"

python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_StateDB_ContractTests.mq5"

python C:\Users\web\.codex\skills\mt5-goat-compile\scripts\compile_goat_ea.py `
  --source "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA\v2\tests\GOAT2_Gateway_Integration.mq5"
```

A compile claim is valid only when the relevant log ends in `Result: 0 errors, 0 warnings`, the expected `.ex5` exists beside its source, and its timestamp is newer than every source/include used by that build. Compile logs and tester results are verification artifacts, not repository source.

The runtime result contracts are:

- `v2/tests/GOAT2_Phase1_UnitTests.mq5` → `FILE_COMMON\GOAT2\tests\phase1-unit-result.json`
- `v2/tests/GOAT2_StateDB_ContractTests.mq5` → `FILE_COMMON\GOAT2\tests\state-db-contract-result.json`
- `v2/tests/GOAT2_Gateway_Integration.mq5` → `FILE_COMMON\GOAT2\tests\gateway-integration-result.json`

A clean compile is not a runtime PASS. Result files, tester logs, temporary `.set` files, and compile logs are verification artifacts, not repository source. See [the V2 build status](docs/V2_BUILD_STATUS.md) for the current evidence state and remaining gates, and [the implementation record](docs/GOAT_EA_V2_FOUNDATION_IMPLEMENTATION.md) for the reviewer-finding crosswalk.

#### V2 operation modes

The public operation-mode tokens are `TRADING`, `PORTFOLIO_DASHBOARD`, `OPTIMIZATION_STUDIO`, and `REPORT_PROCESSOR`. Only `TRADING` constructs `CV2PortfolioManager` or receives broker lifecycle events. The other three modes are deliberately non-trading status placeholders for later phases and return a neutral tester score. They are not represented as completed dashboard, optimizer, or report-processing products.

`V2_RUN_DISABLED` is a halted, no-broker-mutation state. It is not an alias for `MANAGE_ONLY`. In every mode, the production compile-time certification lock remains authoritative.

#### V2 durability and experiment identity

Every broker submission requires a durable intent. This candidate has **no process-memory-only emergency broker exception**, including for reductions. If durable persistence becomes unavailable, broker submission fails closed and the EA moves to `MANAGE_ONLY`; existing broker-hosted protective orders, where present, remain the fail-safe. Live certification must prove adequate broker-hosted protection for every permitted exposure because a database outage also prevents a new reduction request.

The causal event/receipt journal is intentionally unbounded for this development candidate and is never silently truncated. A storage-capacity or database-write failure fails closed. Retention, backup, restore, proactive disk monitoring, and production volume budgets are mandatory pre-certification work.

The runtime manifest stores a normalized hash of trading/runtime inputs while excluding expected and external lineage fields. This prevents the lineage values from creating a self-hash cycle and provides a stable semantic input identity. The literal SHA-256 of the `.set` file remains a separate required artifact in the external certification evidence bundle; it is not replaced by the normalized input hash.

The **GOAT V1 release line** keeps the main trading logic for each released version in a single `.mq5` file, and there can be **multiple versions** of this main file present in the repository at the same time. Supporting V1 logic is implemented in one or more shared `.mqh` include files. GOAT2 uses the separate layout and evidence contract above.

### GOAT V1 repository structure and versioning rules

- **One main `.mq5` per version**
  - For each EA version there is exactly one main `.mq5` source file.
  - The file name encodes the version, for example:
    - `GOAT V1.35.mq5`
    - `GOAT V1.36.mq5`
  - When a new version is created, a **new** `.mq5` file is added (for example, `GOAT V1.36.mq5`) and the previous version file (for example, `GOAT V1.35.mq5`) is **kept** in the repository.
  - Over time, the repo will contain multiple versioned `.mq5` files side by side. This is **intentional** and required for historical reproducibility.

- **Include files (`.mqh`)**
  - Common and modular logic is held in `.mqh` include files.
  - The project currently uses multiple `.mqh` files (for example, 7 include files), and **more `.mqh` files may be added in the future** as the EA evolves.
  - All `.mqh` files that belong to this EA are expected to be tracked in git.

- **Compiled binaries and assets**
  - The compiled EA binary for each version (for example, `GOAT V1.35.ex5`) **must be committed** and remain under version control.
  - Icon and image assets (`.ico`, `.png`) **must be committed** and remain under version control.

### Git / repository saving rules

These rules apply whenever changes are saved or pushed to this repository:

- **Always keep historical main version files**
  - Do **not** delete older main `.mq5` files when adding a new version.
  - Each new version should add a new `.mq5` file whose name clearly encodes the version number.

- **Track all project source and assets**
  - Always track:
    - All EA main `.mq5` files.
    - All EA `.mqh` include files.
    - All corresponding compiled `.ex5` files for versions that are in use.
    - All `.ico` and `.png` assets used by the EA.

- **Future versions**
  - Future versions (for example, moving from `GOAT V1.35.mq5` to `GOAT V1.36.mq5`, `GOAT V1.37.mq5`, etc.) should follow the same pattern:
    - Add the new versioned `.mq5` file alongside the previous ones.
    - Optionally update or add `.mqh` include files as needed.
    - Commit the updated/new compiled `.ex5` binary and any new assets.

### Version branch push workflow

Use this workflow when the current branch has standing GOAT changes that should become the next released version:

1. Create a dedicated release branch named after the target version before merging to `main`.
   - In Codex sessions, use the required prefixed branch format such as `codex/GOAT-V1.36`.
2. Copy the current modified main file into the new versioned entrypoint.
   - Example: copy the current `GOAT V1.35.mq5` working copy to `GOAT V1.36.mq5`.
3. Restore the previous versioned main file back to the tracked baseline content.
   - Example: restore `GOAT V1.35.mq5` from `HEAD` or `main` after the copy is made.
4. Keep version metadata stable per main file.
   - Each versioned `.mq5` should define its own `GOAT_VERSION_LABEL` before including `GOAT_Inputs_Definitions.mqh`.
   - `GOAT_Inputs_Definitions.mqh` should carry the newest default version label so the current release still initializes correctly in MT5.
5. Leave shared `.mqh` improvements in place when they belong to the new release, but verify that both the old and new `.mq5` entrypoints still compile.
6. Re-read the diff, update this README when the workflow changes, and do not stage logs, tester caches, or scratch reports.
7. Compile and verify the target release before claiming success.

### Reproducibility note

Keeping multiple versioned `.mq5` files side by side preserves the released entrypoints, but it does not fully freeze historical behavior if shared `.mqh` files continue to evolve.

If exact historical reproducibility becomes important, version the shared include graph together with each main `.mq5` release or keep release tags that point to the exact source tree used for that version.

Following these rules ensures the repository remains a complete, reproducible history of all GOAT-EA versions, source code, binaries, and visual assets.

