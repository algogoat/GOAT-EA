# GOAT agent start page

You are operating **this user's installation**. Discover its paths and capabilities
from the installation receipt created by GOAT Setup. Never assume a developer's
terminal, broker, account, folders, running jobs, credentials or research results
exist here. Never import another person's controller database or receipt.

GOAT Setup supplies the EA, this controller, optimization templates, the living
strategy/asset matrix, Portfolio Builder and Python runtime. Development tools,
private skills and source checkouts are unnecessary. Use `goat.exe` in the installed
agent kit; its `studio` command forwards to the controller below.

## Start safely and discover

In the installed suite, begin with [the complete beta agent workflow](goat-beta-agent-guide.md).
It covers setup, the living matrix, Studio exports, Portfolio Builder, exposure
filters and recovery. The [human quickstart](goat-beta-start-here.md) explains
the few MT5 steps the user performs. These two guides are added by the suite packager.

Use the receipt path shown by Setup's **Copy instructions for my agent** action:

```powershell
& '<installed agent kit>\goat.exe' studio --installation '<your installation.json>' discover
```

`discover` verifies the installed EA hash and returns machine-specific paths,
the complete input schema, export/tester fields, constraints and operations.
It does not bind a controller, change MT5, grant ownership or start work.
Use `--help` on the root or a subcommand for exact arguments. JSON replies use
`ok:true,result` or `ok:false,error,recovery`; exit code 2 means the operation
did not establish success. Preserve files and inspect receipts after errors.

There are two control surfaces:

- **Studio:** prepares and runs MT5 optimizations and selected fixed export
  backtests. Requires the chosen terminal, a connected demo account, the GOAT
  license, DLL permission and local tester workers. Algo Trading stays off.
- **Portfolio Builder:** imports existing results, searches portfolios and
  exports selected SETs through the authenticated desktop agent API. Its installed
  guide describes authentication, library and exposure methods. Importing or
  building a portfolio never starts an MT5 optimization or deploys live trading.

Read [the full Studio command and recovery guide](README.md) before the first run.
For new optimization files, follow [template creation and seed research](TEMPLATE-WORKFLOW.md).
Use the installed `validate-set` and `build-set` commands; preserve parent evidence,
document every change and register new candidates as untested local matrix forks.

## First session

1. Let the user choose their MT5 terminal and sign in to their own **demo**
   account. Resolve the exact broker symbol; do not guess suffixes.
2. Run `bootstrap --account-login <login> --account-server '<server>'` with
   the global `--installation` argument. It creates local state and an EA preset,
   prints its path, and leaves control with the human. It never launches MT5.
3. Run `onboarding-status`. With terminals stopped, run
   `monitor-prepare --symbol <exact broker symbol>` then
   `monitor-launch --attempt-id <new unique ID>`. These commands create and open
   a separate persistent monitor chart without editing existing profiles or
   granting permissions. The user approves DLL imports and the WebRequest URL
   shown by the EA, completes GOAT activation, and keeps Algo Trading off.
   See [onboarding and recovery](README.md#agent-assisted-monitor-onboarding).
4. Run `serve` in a separate process while using the Studio UI. Its bounded
   default is one hour; restart it explicitly when needed. It processes durable
   human/agent requests and refreshes the snapshot, not MT5 jobs. The user saves
   or reloads Studio settings and clicks **Give to Agent**. Agents cannot self-grant.
5. Inspect `state` and discuss the user's research goal. Select exact template/asset
   pairs and review all tester/export settings, validation history and compute limits.
6. Use `prepare-batch` with a complete plan to freeze the full native queue. Inspect
   every member and retain its template lineage. `prepare` also supports a focused
   single-file check. Save/load preserve `.goatbatch` plans under new identities.
7. `start --job-id <batch-id>` explicitly launches the aggregate batch; the EA
   advances its members. Use `batch-status` and `status` to reconcile progress.
   `cancel` stops the whole batch and must be reconciled. A request is not stop proof.
8. After terminal completion and idle, `finish` verifies every completed member's
   reports and exports and retains results. `resume-batch` prepares verified remaining
   work under a new ID after finish; failed retries require `--include-failed`.
   Never reset a database or rewrite active inputs to clear a busy batch.

For dedicated SeedFarming, read [the seed workflow](SEED-WORKFLOW.md) and use
`seed-prepare`, `seed-start`, `seed-status`, `seed-resume`, `seed-cancel` and
`seed-report`. It has a separate bounded driver and terminal lifecycle and produces
no-forward candidate XML. Ordinary portfolio exports come from the subsequent
full optimization/export batch. Check the exact release's native qualification.

The [capability reference](goat-agent-capabilities.md) maps all supported workflows.
The [input reference](INPUT-REFERENCE.md) lists all 114 inputs, enum values, source
defaults and the dependency checks that are actually implemented.

## The matrix is a living record

Before selection, read the current installed catalog revision and the user's own
results. Publisher findings are not this user's broker results. Every selectable
row must resolve to the catalog's exact SET and hash.

After every attempt, record each native batch member separately in **My results**:
completed, failed, cancelled, rejected or unknown. Match its verified member index,
run alias and frozen configuration to the retained template lineage. Use distinct
stable matrix attempt IDs (for example, native attempt ID plus `-m` plus member
index), and keep the aggregate attempt ID and alias in provenance. A completed
member keeps its own outcome if a later member fails. Resumed members have new
attempt IDs; cancelled/unstarted and unknown results remain explicit.
The matrix uses `interrupted` for native cancelled attempts; keep `unknown`
unresolved until reconciled. Use the matrix API's documented status vocabulary.
Use the `finish` result JSON as provenance, with the exact template revision/hash,
effective settings, EA/controller builds, broker/symbol, history/forward dates,
model, costs/sizing and available metrics. Mark missing measurements unavailable.
Add a short interpretation of what worked or failed and the evidence limitations.
Technical failure is not evidence that a strategy performed badly. An in-sample
result is not an out-of-sample claim.

For interrupted attempts that cannot yet finish, append an unresolved observation
and later reconcile it by the same run/attempt identity. Do not count it twice.
Preserve immutable histories, user template forks and old evidence. GOAT strategy
library updates may add templates and publisher evidence independently of EA
releases. Validate compatibility and hashes, review changes, and never replace a
queued job's frozen inputs. An update does not authorize new optimization work or
uploading user results.

Consult the installed matrix guide and its capability discovery for the supported
result/update commands. Do not invent endpoints if the installed version lacks a
capability; record the missing capability and preserve the result JSON for import.

## Sequence evidence

`IncludeSequenceData` defaults to true for older saved settings. It records the
selected fixed export backtests for later exposure-filter construction. It does
not record every genetic pass. False preserves ordinary CSV/SET export.
Enabled exports require extra time and storage: tested histories added roughly
8–16% to selected fixed-export time and 46–58 MB per strategy. Those measurements
are examples, not a guarantee for other histories/machines. Disabling it means
that result cannot support sequence-based filtering without new evidence.

The builder validates exact CSV/SET/package identities and common observation
coverage. Missing or rejected evidence must stay visible. Never borrow a package
from another result, silently reduce the requested pool, or start replay work
without user authorization. Keep the user's chosen diversification constraints.

## Authorization and handoff

Preparing, starting, cancelling, importing and deploying are separate actions.
Only start work within the user's authorized dates, assets, sizing and resource
budget. A portfolio export is not permission to attach it to a trading account.
Honour pause/stop instructions across sessions. Before handoff, record terminal
and run identities, ownership/revision/generation, job/attempt/request IDs, exact
observed state, result locations and the next safe action.
