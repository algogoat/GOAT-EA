## GOAT-EA

Expert Advisor (EA) project for MetaTrader 5, maintained in the `GOAT-EA` repository.

### V1.47 behavior-neutral tester performance hotfix

`GOAT V1.47` removes normal per-tick `TSL BUY/SELL skipped` log lines and
replaces them with aggregate buy/sell counters. It also emits one tester-only
`GOAT PERF SUMMARY` covering the lot solver, exact MLPS enforcement, trailing,
and signal processing. Modification failures remain logged.

The MLPS calculation and cache policy are unchanged. Exact-control A/B tests on
the audited NZDUSD RangeFade fixture produced byte-identical OHLC and ETWRT HTML
reports, complete order/deal ledgers, tester statistics, GOAT CSV exports, and
GOAT SET exports. The hotfix removed 6,000 OHLC and 58,304 ETWRT skip lines;
ETWRT master/agent logs were about 87% smaller.

V1.47 also keeps the authenticated `Bias_Protocol` selector in the existing
**GOAT AI SIGNAL FILTER** settings group. `Bias_threshold` remains the stable
`.set`/optimizer input and is presented as **Minimum AI confidence to trade
(%)**. The separate win/loss/cost/expected-edge R inputs and their duplicate
break-even gate do not apply to V1.47; the EA's existing risk/reward and trade
management settings remain authoritative. Outside tester contexts, Demo raw is
accepted only on `ACCOUNT_TRADE_MODE_DEMO` accounts and still promotes only an
authenticated `CALIBRATION_ARTIFACT_UNAVAILABLE` response. An active bias filter
in tester, optimization, or forward contexts must explicitly select
`BiasProtocol_LegacyRecorded`; initialization otherwise fails with a clear
parameter error. Disabling AI bias remains valid, and the wire layer retains its
`LIVE_WIRE_UNAVAILABLE_IN_TESTER` fail-closed defense. Unavailable, stale,
neutral, unauthenticated, and all other withheld states remain non-actionable.
This is a same-version V1.47 source refresh; the V1.47 label is unchanged, and
the historical V1.43-V1.46 entrypoints retain their prior input surface and
actionability behavior.

The R4 portal hotfix removes obsolete `tester_file` metadata from the customer
binary. Those declarations made MT5 require 42 local data files before `OnInit`
even though the active news, time, and recorded-bias readers use `FILE_COMMON`.
V1.47 therefore remains a one-file portal install, retains `tester_no_cache`,
and does not change signal, trade, risk, or live-bias behavior.

### V1.47 R6 dashboard AI launch policy

Before activating any portfolio row, use the AI control beside the dashboard's
view tabs to cycle **As Optimized**, **Display Only**, and **Entry Filter**.
As Optimized is the default and preserves every exported input. For the two
override modes, enter a whole-number threshold from 1 to 100 (default 60).
The setting locks after the first child chart is opened and is retained when
resuming the saved dashboard; it is not a command to change running EAs.

Only temporary launch templates are changed: `Mode_Bias` becomes Display (0)
or Opens (2), `Bias_threshold` uses the selected value, `Bias_Protocol` is
calibrated Control Tower V2 (1), and `Mode_Bias_Trades` is sequence starts only
(0). Source `.set` files, the EA input schema, news settings, optimization
behavior, and all other strategy/risk/exit inputs remain unchanged. No AI close
or SmartRescue override is offered. Directly attaching a set bypasses this
dashboard policy. Entry Filter retains the existing fail-closed behavior when
calibrated AI data is unavailable; Display Only does not gate entries.

Each launch records source/effective AI values in
`Common\Files\GOAT\dashboard_ai_launch_audit.tsv` (under the configured GOAT
key). `PREPARED`, `LINKED`, and `APPLY_FAILED` distinguish template preparation
from child binding. This does not certify a trade or a healthy live feed.
Run `scripts/test_v147_ai_launch_policy.ps1` for the executable policy and
export-preservation checks, then compile V1.47 with the GOAT compile wrapper.

### V1.45 release-admitted Control Tower wire

`GOAT V1.45` carries the forward-only client for `/api/ea/bias/v2`
(`ea-wire-v2-calibrated-probability-v1`) without hard-pinning a short-lived era
name in the desktop binary. The authenticated API admits only its exact live
release pointer; the EA independently requires an exact schema, lowercase
SHA-256 checksum, asset match, expiry, safe era identifier, manifest hash, and
data/meta era-manifest equality. It never substitutes the legacy packed-score
feed.

`Bias_Protocol` defaults to `BiasProtocol_ControlTowerV2` and V1.45 defaults
`Mode_Bias` to `Bias_Opens`. A verified actionable Bullish/Bearish directive can
therefore govern new sequence risk immediately. Unavailable, WITHHELD, neutral,
or below-cutoff evidence blocks new sequence risk and, when configured, sequence
additions. A feed outage does not force-close an existing position. Actionable
calibrated probability must clear both `Bias_threshold` and the configured
payoff/cost break-even threshold.

### V1.44 Control Tower V54 wire

`GOAT V1.44` carries the forward-only client for
`/api/ea/bias/v2` (`ea-wire-v2-calibrated-probability-v1`). The client pins the
V54 era and immutable manifest, verifies the exact response shape and lowercase
SHA-256 checksum, and derives expiry from the server read time plus monotonic
elapsed time. It never substitutes the legacy packed-score feed.

`GOAT V1.43` remains the immutable V53-pinned predecessor release. It must not be
used against the V54 Control Tower because the exact era/manifest guard correctly
rejects cross-era directives.

`Bias_Protocol` defaults to `BiasProtocol_ControlTowerV2`, while V1.44's
`Mode_Bias` continues to default to `Bias_Disabled`. When bias filtering is enabled, unavailable,
WITHHELD, neutral, or below-cutoff V2 evidence blocks new sequence risk and, when
configured, sequence additions. It does not force-close an existing position.
Actionable calibrated Bullish/Bearish probability is passed into the existing bias
trade modes only when it clears both `Bias_threshold` and the configured
payoff/cost break-even threshold.

Tester and optimization runs deliberately treat V2 as unavailable. Historical
legacy bias testing requires the explicit
`BiasProtocol_LegacyRecorded` selection; that protocol is rejected on live charts.
Exported `.set` files append the selected protocol and the four V2 payoff inputs,
and an incomplete append causes the newly created artifact to be discarded.

Live API authentication is never stored in source or `.set` files. Provision the
rotated bearer as the only non-empty line in
`Common\Files\GOAT\Credentials\api-bearer.token` on each MT5 host. The EA
validates the local file and fails initialization when it is missing or malformed.
The production `LICENSE_GATEWAY_TOKEN` must be rotated whenever a prior token may
have appeared in repository history; deploy/provision the replacement before
retiring the old value to avoid an unsafe partial cutover.

The **main trading logic** for each released version is contained in a single `.mq5` file, and there can be **multiple versions** of this main file present in the repository at the same time. Supporting logic is implemented in one or more `.mqh` include files.

### Repository structure and versioning rules

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

