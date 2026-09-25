# GOAT Setup: unified customer distribution

Status: proposed customer flow and required bundle scope, September 25, 2026.
This is a delivery specification, not an available installer or CLI contract.
The user requested one easy download with the EA, controller, optimization files
and the strategy/asset selection matrix. The portfolio builder and agent guide
belong in that same installation.

## Customer experience

1. Download **GOAT Setup** from the entitled Command Center download page.
2. Install and sign in. Setup discovers local MT5 installations and displays
   enough information to choose the intended terminal. If discovery cannot find
   a portable installation, let the user select its folder and verify it.
3. Review the destination and install the compatible EA, controller, optimization
   suites and matrix. Keep existing user files and settings intact.
4. Open **Optimization Studio**, **Strategy/Asset Matrix**, or **Portfolio Builder**.
   A visible **Set up my agent** action copies instructions pointing to this
   user's installed guide and discovery entry point.
5. Select strategies/assets in the matrix, inspect optimization settings and
   sequence-export cost, prepare a batch and explicitly start it. Import results
   into the portfolio builder through the documented workflow.

Setup completion does not start optimization or enable trading. Broker MT5
installation/account access and GOAT sign-in remain user-specific prerequisites;
the product should explain missing prerequisites at the point they are needed.

## Required contents

| Component | Packaging requirement |
|---|---|
| GOAT EA | Reviewed EX5 with its exact program filename, source/build identity and hash; V1.48 is the current target |
| Native/Studio controller | Versioned supported executable and required runtimes; customers do not install development Python/Node or clone research scripts |
| Portfolio builder | Existing Windows desktop app, native sidecar and verified runtime DLLs |
| Optimization files | Explicit release selection of complete `.set` suites, family descriptions, dependencies and hashes; preserve encoding, ranges and identities |
| Strategy/asset selection matrix | Human-readable view and machine-readable catalog tied to the exact included SET IDs/hashes; available from setup and agent discovery |
| Agent guide | Installed start page, controls/options/defaults, complete workflows, examples, errors, recovery and capability discovery; no developer-specific setup assumptions |
| Bundle manifest | Bundle/component versions, compatibility requirements, exact filenames/hashes, suite/matrix revision and installation destinations |

The matrix must describe strategy/family, intended asset or asset class, direction,
timeframe and linked optimization file. Where evidence is supplied, include its
history window, broker/model and source reference, and distinguish tested,
exploratory, unsupported and unknown entries. These are selection aids, not
performance guarantees. Resolve the user's exact broker symbol before queuing;
do not silently guess suffixes or claim an unsupported asset is tested.

Every selectable matrix row must resolve to a shipped file. Validate file hashes,
input dependencies and EA compatibility when building the bundle and when
preparing a batch. A missing or mismatched row must produce an actionable error.
Never bundle every dated research/trial folder simply because it exists locally.
The final suite and matrix release selection must be explicit and versioned.

## Living matrix and ongoing releases

The strategy/asset selection matrix is a maintained record, not a static list.
After every completed run, the agent must reconcile the native completion and
exports, then append the result to the user's local matrix history. Interrupted,
failed, rejected and no-qualifying-export runs belong there too, with their actual
status; a technical failure is not evidence that the strategy performed badly.
Record pending/unknown when completion cannot yet be verified. Resume by run and
attempt identity so one result is not counted twice.

Each result references the exact template ID/revision/hash and effective settings,
EA/controller versions, broker/server and exact symbol, timeframe, dates/forward
window, tester model, deposit/currency, sizing and costs. Retain available metrics,
quality-gate outcomes, exported artifacts and evidence hashes. Record missing
metrics as unavailable. A short summary explains what worked, what failed and
the limits of the evidence. Append new observations; do not erase old results
or convert a successful in-sample run into an out-of-sample claim.

Keep two distinct layers in one view:

- **GOAT catalog:** publisher-owned, versioned matrix entries, optimization files,
  descriptions and supporting evidence. These are a starting point and an update
  channel; they are not measurements from the user's broker or installation.
- **My results:** user-owned observations, template forks, preferences and notes.
  Agents update this layer after authorized work. It remains local unless the
  user explicitly chooses a supported sharing flow. Installing updates is not
  authorization to upload trading results or settings.

Generate the human matrix view, CSV export and agent query results from the same
versioned catalog and result history. A new observation must be visible in every
view after refresh, with the same status and evidence identity. Avoid separately
hand-maintained HTML/CSV snapshots that omit newer trial notes. An older published
snapshot may remain available, but must display its date/revision and scope.

GOAT can publish independent **strategy-library updates** containing new files,
new matrix entries, updated evidence and corrected/deprecated templates. These
do not require a new EA or controller when declared compatibility is unchanged.
The app should show the revision, changes, compatible builds and evidence scope,
and offer an **Update strategy library** action. This feed and action are planned
capabilities; the current download manifest does not implement them.

Bind each published catalog revision to immutable template revisions and hashes.
Validate the whole update before atomically activating its catalog. Retain the
previous revision for rollback. New jobs can select the new revision; queued or
running work keeps its frozen inputs. Preserve user-edited files as forks rather
than overwriting them. If a template changes, old results stay attached to its
old revision and are visible as historical evidence, not retests of the new one.
Unknown compatibility or unresolved file collisions prevent activation with a
clear explanation; the prior valid catalog remains usable.

Use evidence labels such as untested, tested with stated conditions, qualifying
exports, or no qualifying exports. Show recency and evidence window. Avoid a
universal "working" score detached from costs, sizing, broker and sample period.
Agents should recommend next tests from the user's goal and observed gaps, but
must not launch another optimization solely because a matrix update arrived.

## Installation and agent discovery

Extend the existing signed Windows NSIS desktop installer rather than adding a
second public installer. Stage the release assets with the application; perform
terminal discovery and destination selection in first-run setup. Existing
desktop packaging already supports extra resources and an installed agent kit.
This is an implementation route, not evidence that terminal setup is finished.

Write a user-local installation receipt containing the selected terminal and
data/Common Files directories, installed component identities, suite/matrix
locations and documented controller discovery location. Paths come from this
machine. Accounts, passwords, tokens, developer paths and research databases are
not release payloads. Agents consume supported discovery results and schemas,
not private skills or a previous campaign's IDs.

Package a runtime-independent controller entry point for agents. Its help and
capability response should describe supported operations, exact parameter
schemas, defaults, effects and recovery. Do not invent command names in the
customer guide before implementing them. Preserve the existing authenticated
desktop API and native ownership/receipt contracts behind the packaged entry
point. The installed guide must distinguish both control surfaces clearly.

Install the EA in the selected terminal's Experts tree and suites in its verified
Common Files location, preserving the expected folder architecture. Keep matrix
paths relative to their catalog root and resolve them from the installation
receipt. Detect collisions; preserve user-edited templates and older release
files. Update/repair must not overwrite an active run's inputs or replace a
running EA without the supported explicit transition.

## Work remaining before delivery

- Complete CTRL-004: package the native Studio controller, negotiate versions,
  support the sequence-data setting end to end and remove development-path
  assumptions from dispatch.
- Implement first-run terminal discovery, install/repair receipts and the agent
  setup action. Keep setup separate from launching a batch.
- Select and validate the released optimization suites and linked matrix;
  carry templates forward only after actual V1.48 input compatibility checks.
- Implement the living matrix's append-only local results and independently
  versioned publisher update feed, including idempotent result reconciliation,
  provenance labels, compatibility, user forks and rollback.
- Extend the release manifest and entitlement-gated download flow to publish
  the compatible set as one installer with truthful release notes.
- Test the built installer on a clean Windows account without developer tools:
  discover/select MT5, install, discover agent capabilities, select a matrix row,
  prepare/start/monitor/cancel/recover a small batch, record sequence data on/off,
  import results and build/export a portfolio. Verify repair/upgrade preserves
  user edits and run receipts. Verify signing, hashes and runtime dependencies.

Passing existing local EA/consumer tests does not prove this installer flow.
Record fresh-install results separately from native export evidence. The customer
guide should describe supported processes and options; release engineering notes
hold developer paths, experiments and unfinished implementation details.
