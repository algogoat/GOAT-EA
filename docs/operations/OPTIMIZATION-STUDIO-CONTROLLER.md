# Optimization Studio: controls and controller contract

The customer beta now has a portable, receipt-bound controller and installed
[agent start guide](../../controller/AGENT-START-HERE.md) with the full
[command and recovery contract](../../controller/README.md). Its entrypoint is
`controller/goat_studio.py`, not the historical research scripts described below.
It includes nine-field sequence export settings, portable binding/preparation,
owned native start/cancel and retained completion results. Native lifecycle
qualification is recorded separately in release evidence; portable unit tests do
not establish a clean-machine MT5 qualification.

Use this guide to prepare settings, select strategies, maintain a queue, run a
local batch, and recover uncertain commands. It describes the tracked V1.48
Studio and the separately installed research controller as inspected on
September 25, 2026. It is not an installer or an assertion that every host has
the research controller. See [sequence export](V1.48-SEQUENCE-EXPORT.md) for the
package contract, native qualification and measured recording cost.

## Choose the actual operating surface

Start with the user's installation, not the development environment. Discover
their terminal/data/Common Files paths, installed builds and controller
capabilities. Use their selected optimization suites, matrix, symbols and dates.
There is no required developer drive, VPS, account, research database or private
agent skill. Example paths and request IDs are placeholders. A fresh user has
no previous run to resume; create new work only through the installed tool's
supported setup flow. Existing campaign manifests apply only when that user
explicitly selects that campaign.

| Surface | How to identify it | Available operations |
|---|---|---|
| Local Optimization Studio | V1.48 chart in `Mode_Operation=Operation_Batch`, `Studio_ReadOnlyMonitor=false`; buttons **START BATCH** and **TERMINATE** | Select inputs, edit local settings, save/reload batches, manage queue, explicitly start/restart or terminate native work, export selected results |
| Unmanaged read-only monitor | `Studio_ReadOnlyMonitor=true`, optional `Studio_MonitorRunPath`; no valid managed binding | Observe an existing run; do not treat it as the local execution panel |
| Managed Studio | Read-only monitor plus terminal-local `MQL5\Files\GOATStudio\active.json` and valid matching bridge binding; buttons **TAKE CONTROL**, **GIVE TO AGENT**, **SAVE SETTINGS** | Shared drafts, ownership and pending queue actions with receipts; its buttons are not local start/stop buttons |
| Research agent CLI | Existing `scripts/studio_agent.py`, `--help` lists `discover`, `state`, `submit` | Existing controller binding only; draft and queue mutations after human grant; no terminal launch or self-grant |
| Native research adapters | Separately provisioned gate, controller database, run manifests and native receipts | Campaign-specific staging, dispatch, restart and reconciliation; not a generic V1.48 launch command |

The tracked MQL UI/bridge is in this repository. The research Python files
described below are **not included in this V1.48 source release**. Their sections
document an optional legacy integration, not a customer installation prerequisite.
Only use them if that integration is installed and advertises the documented
contract. Do not search for the developer's workspace or copy its database.

The [native controller runbook](NATIVE-CONTROLLER-RUNBOOK.md) covers terminal
setup/portfolio operations. Those commands are not interchangeable with the
Studio draft/queue protocol.

## First use: local Studio

1. Identify the intended terminal executable/data folder, Common Files folder,
   account/server, EA build and EX5 hash. Confirm the tester is idle and the
   terminal is the one authorized for optimization. Do not borrow another run's
   queue, PID or active pointer.
2. Open the installed, verified V1.48 in **Optimization Studio** operation mode
   on a chart. Local batch operation uses the native tester/DLL integration;
   a monitor chart has a different role. Attaching a monitor does not start a
   batch. This guide does not prescribe a fresh-terminal installation command.
3. In **01 SETUP**, give the run a useful name and **Select** its optimization
   `.set` from Common Files. Inspect the derived strategy and expert. Choose the
   exact broker symbol and period, or a deliberately selected symbol preset.
4. Set dates/forward split in **02 TIMELINE**; model, delay, deposit, currency and
   leverage in **03 EXECUTION**. Inspect restored values instead of assuming
   newly displayed defaults are the intended campaign settings.
5. In **04 EXPORT & DATA**, set the quality gates, sizing/OOS options and
   **Include sequence data**. Leave it on when this new library must support
   exposure-filter construction. Review history coverage using the data tools.
6. **Add to Queue** saves a job for the selected symbol, or one job per symbol
   in the selected preset. Inspect the queue before continuing. Selection,
   changing settings and queuing are preparation; none is a launch command.
7. **START BATCH** checks run/queue/input state, idle tester and news freshness,
   saves the batch, and asks to restart the terminal with the pending count.
   Accepting this prompt is the execution step. The deferred restart waits for
   tester idle. Observe actual tester progress and the run's results.
8. Retain the saved `.goatbatch`, run settings, original input SETs, output
   CSV/SET pairs and any matching `.goatseq` directories. Import the containing
   folder/ZIP into a compatible portfolio builder; see the sequence guide.
9. Update the user's strategy/asset matrix with the verified run outcome,
   exact template/settings identity, broker/model/dates, available metrics and
   evidence locations. Preserve failures and no-qualifying-export results too.
   If the installed tools have no matrix-write operation, retain an explicit
   result receipt for reconciliation and report that the matrix update remains
   pending; do not invent an API or silently rewrite an unknown file format.
   The [living matrix contract](GOAT-SETUP-BUNDLE.md#living-matrix-and-ongoing-releases)
   separates local results from GOAT's versioned catalog updates.

For agent operation, use an available controller and its verified campaign
procedure. If the required controller operation is absent, report that gap;
do not silently substitute a mouse-driven launch loop.

## Local control map

| Control | Effect and persistence |
|---|---|
| Run Name | Names the run folder/package. Renaming can rehome the run and rewrite queue paths; retain the resulting manifest/path |
| Select `.set` | Loads strategy input values, including optimization ranges; may ask before replacing a strategy or appending its saved queue |
| Select `.goatbatch` | Restores embedded inputs, export settings and queue into a new `Reload` run; may prompt for timeline adjustment. This is not resumption under the old run identity |
| Expert / Strategy | Expert path and derived strategy identify what the queued inputs belong to; Strategy is read-only |
| Symbol / period | Symbol list uses Market Watch plus presets; initial visible period choices are M1, M5, M15, M30, H1 |
| Set Presets | Opens the symbol preset folder. Files under Common Files `GOAT\Symbol Presets\` are `.txt` names containing `preset`; symbols may be line/comma/space separated; `#` and `//` comments are ignored |
| Add to Queue | Validates current input/settings and persists queue/package; a preset expands into individual symbol jobs |
| Queue selection | Displays the selected queued tester configuration; inspect before edits/actions |
| Up / Down | Reorders local queue rows |
| Cancel | Marks the selected queue row Cancelled. It is not the active tester-stop operation |
| Activate | Makes the selected local row Pending again; use deliberately when a rerun is intended |
| Delete / Delete All | Removes local row(s). Delete All also clears local batch markers/configuration state; it is not a recovery or orderly cancellation command |
| START BATCH | Explicit validation, save and terminal restart into pending native work; disabled while batch is running |
| TERMINATE | Confirmation stops the running optimization and cancels Pending/Queued/OnGoing rows. Sets persistent cancellation first, clears deferred restart/launch state, requests native tester stop and persists cancellation |
| Progress / errors | Observation, not proof that a particular package is complete; verify matching run and export evidence |
| Sync AI Bias History | Requests history synchronization and shows coverage/result; can take time and change local history files |
| View AI Bias History | Displays locally observed coverage/status |
| Sync News History | Reports existing fresh coverage or requests a sync when stale; reports failure rather than making old history fresh |

Do not delete queue files or kill a terminal as the routine way to cancel.
After an interrupted stop, inspect tester state and cancellation/queue evidence
before an intentional new start. A normal accepted new start clears the old
cancellation latch; refreshing the UI does not authorize a restart.

### Settings, encodings and defaults

Dates serialize as `YYYY.MM.DD`. Tester settings serialize in `[Tester]` and
export preferences in `[Export]`. Saved `.goatbatch` version 1 contains run
metadata, `GOAT_EXPORT_SETTINGS`, `GOAT_QUEUE` and embedded strategy inputs.
Local export preferences are run/batch settings, not live trading inputs.

| UI setting | Serialized field / meaning | New local UI fallback |
|---|---|---|
| Date from / to | `FromDate`, `ToDate`; explicit test window | Inspect loaded dates |
| Forward | Intended `ForwardMode`: 0 No, 1 half, 2 third, 3 quarter, 4 Custom; `ForwardDate` for Custom; see local limitation below | Custom selected; inspect actual date |
| Delays | `ExecutionMode`, milliseconds | 0; UI offers 10, 20, 50, 100, 200, 500 |
| Modeling | `Model`: 2 open prices, 1 minute OHLC, 0 every tick, 4 real ticks | 1 minute OHLC |
| Deposit / currency / leverage | `Deposit`, `Currency`, `Leverage` | 100000 / USD / 1:500 |
| Optimization | `Optimization=2`, fast genetic; `OptimizationCriterion=6` | Fixed supported mode |
| # of Sets to Export | `SetsToExport`, selected export count | At least 2 |
| Min OPT Score | `MinScore`, export gate | At least 60 |
| Target Drawdown | `TargetDD`, target used by lot adjustment | At least 100 |
| Adjust Lots to DD | `AdjustLots` | False if missing |
| Back OOS Date | `BackOOSDate` | 2024.01.08 if missing |
| Min ARF / Min SR | `MinARF`, `MinSR`, export gates | At least 0.2 / 2.5 |
| Include Back OOS | `IncludeBackOOS` | False if missing |
| Include sequence data | `IncludeSequenceData` | **True if missing**, including older saved settings |

These are implementation fallbacks/minima, not recommended risk settings.
Restored run settings take precedence. A managed controller validates complete
objects and can reject values that local UI code merely clamps on load.

Local serialization concerns pending native qualification: **No** forward maps to numeric 0 only
in managed mode; ordinary local serialization currently writes `ForwardMode=No`.
Do not assume a no-forward local run is qualified without inspecting native
readback. The local serializer also omits `UseLocal`, `UseRemote`, and `UseCloud`,
so its worker policy cannot be inferred from the research adapter's explicit
local-only schema. Inspect the native worker configuration for the actual run.
These are source observations, not demonstrated native failures in this audit.

### Sequence recording on and off

**On** adds sequence evidence during selected fixed export backtests, including
separate adjusted-lot exports. Preliminary checks, genetic optimization passes
and live trading do not record through this option. Recording adds export time
and disk use. The complete manifest is published last and binds the exact CSV
and final SET; tester idle alone does not make an on-mode package ready.

**Off** persists `IncludeSequenceData=0`, produces ordinary matching CSV/SET,
skips sequence capture and does not wait for a manifest. It still uses unique
attempt/routing markers to prevent collisions; it does not promise zero
temporary files. A later capture is required for exposure-filter construction
from these strategies. Turning this option on does not enable a live exposure
filter, and cannot retrofit evidence into existing exports.

In managed mode the option is available only when the controller's
`snapshot.state.export_draft` advertises `IncludeSequenceData`. A legacy
eight-field controller receives eight fields, with the checkbox disabled and
the message **This controller cannot change sequence-data export settings.**
Do not add a ninth field to its request or use internal
`Sequence_Export_Enabled` as a substitute user preference.

## Managed Studio: ownership and saved drafts

The monitor must be in `Operation_Batch`, outside the Strategy Tester. Its
terminal-local `GOATStudio\active.json` identifies `directory_id`, `terminal_id`,
`run_id` and exact `terminal_data_path`. The bridge root is
`MQL5\Files\GOATStudio\<directory_id>`; `binding.json` and `snapshot.json`
must match protocol version 1 and the same terminal/run. These are terminal-local
Files, unlike the ordinary Common Files optimization outputs. Do not create
an active pointer by copying one from another terminal.

1. **TAKE CONTROL** requests human ownership and a new generation. Wait for its
   receipt/current snapshot. This does not stop native work already running.
2. Select a complete strategy SET. The managed picker accepts a Common Files
   `.set`, validates its encoding/assignments and submits
   `draft.replace_strategy` against the discovered schema hash.
3. Edit settings, then **SAVE SETTINGS**. This submits tester and export objects
   together with the observed revision/generation. Wait for validation/receipt.
4. **Queue saved** enqueues the saved strategy/settings. Unsaved edits prevent
   queueing. **Remove**, **Cancel**, Up and Down apply only to pending managed
   jobs. **Delete All** and local native-start controls are not available here.
5. **LOAD SAVED** reloads committed controller settings; unresolved commands or
   damaged recovery drafts require resolution first. It is not a batch loader.
6. **GIVE TO AGENT** requires saved/reloaded settings and explicitly grants agent
   ownership. Human editors become read-only while the agent owns the binding.

The UI keeps its local draft in `human\ui-draft.json` under an exclusive editor
lock, and records a pending command in `human\pending.json` before publishing
it. Preserve those files after a crash. A newer snapshot must not silently
overwrite unsaved work. An unresolved receipt is not permission to send a new
mutation with a new request ID.

## Research CLI: discover, read and submit

The inspected CLI intentionally has no actor override, bind, install, start,
stop, takeover or self-grant flag. Its schema/policy discovery is pinned to
`GOAT V1.47.mq5` and V1.47 preprocessor definitions. Successful discovery does
not attest a V1.48 binary. Its old UI-integration limitation text also predates
the tracked UI; use the surface table above rather than extrapolating that text.

First-use PowerShell commands (replace host paths/identities from the selected
existing controller manifest; do not run `state` against a newly invented DB):

```powershell
$studioPython = 'C:\path\to\python.exe'
$studioWorkspace = 'C:\path\to\existing-research-workspace'
$studioCli = Join-Path $studioWorkspace 'scripts\studio_agent.py'
& $studioPython $studioCli --help
& $studioPython $studioCli discover --workspace $studioWorkspace

$studioDatabase = 'C:\path\from\selected-controller-manifest\controller.sqlite'
$studioTerminal = 'terminal-id-from-manifest'
$studioRun = 'run-id-from-manifest'
& $studioPython $studioCli state --workspace $studioWorkspace `
  --database $studioDatabase --terminal $studioTerminal --run $studioRun
```

`discover` lists commands, exact tester/export fields, periods, input schema,
schema hash and dependency policy. `state` returns owner, revision, generation,
tester/export/strategy drafts and full queue. They do not launch native work.
The controller store may initialize its SQL schema when opened; this is not a
binary/runtime readiness check. Output is JSON `{ok:true,result:...}` with exit
0, or `{ok:false,error:...}` with exit 2.

Each `submit` JSON has exactly these fields; the numbers below are illustrative
and must be replaced with the current snapshot values:

```json
{
  "schema_version": 1,
  "request_id": "queue-example-unique-id",
  "terminal_id": "terminal-id-from-manifest",
  "run_id": "run-id-from-manifest",
  "expected_revision": 7,
  "generation": 2,
  "command": "queue.enqueue",
  "payload": {"job_id": "example-job-001"}
}
```

This example freezes already validated, complete drafts; it does not create
them. After a human grant, save the intended request as UTF-8 JSON and submit:

```powershell
& $studioPython $studioCli submit --workspace $studioWorkspace `
  --database $studioDatabase --terminal $studioTerminal --run $studioRun `
  --request 'C:\path\to\reviewed-request.json'
```

Retain the exact request and response. Matching `status:applied` plus its updated
state is evidence of the mutation; `execution_effect:false` is explicit evidence
that it did not launch the tester. Refresh state before preparing the next
command. Retries of uncertain outcomes use the **same ID and identical body**;
changed content under the same ID is rejected. Do not automatically retry stale
revision/generation errors with fresh values: first reconcile the user's edits.

### Complete command/payload map

| Command | Exact payload shape / effect |
|---|---|
| `draft.replace_tester` | Complete tester object described below; not a partial patch |
| `draft.replace_export` | Complete export object; cross-checked against current tester dates |
| `draft.replace_configuration` | `{"tester":{...},"export":{...}}`; atomic validation of both |
| `draft.replace_strategy` | `{"schema_hash":"<discovered hash>","values":{...}}`; complete input-name to SET-value-string map |
| `queue.enqueue` | `{"job_id":"<new ID>"}`; freezes current validated drafts/configuration hash, status pending |
| `queue.revise` | `{"job_id":"<new ID>","replaces_job_id":"<pending ID>"}`; supersedes old immutable history using current drafts |
| `queue.cancel` | `{"job_id":"<pending ID>"}`; cancelled, not native stop |
| `queue.remove` | `{"job_id":"<pending ID>"}`; removed with history retained |
| `queue.reorder` | `{"job_ids":[...]}`; every pending ID exactly once; nonpending positions retained |
| `queue.reserve` | `{"job_id":"<first pending>","configuration_sha256":"<hash>","package_sha256":"<hash>"}`; exact frozen/staged identities; reservation still has `launch_permitted:false` |
| `queue.release_reservation` | `{"job_id":"<reserved ID>","reservation_id":"<exact ID>"}`; only before launch intent exists; returns to pending and records release history |
| `control.takeover` / `control.grant_agent` | `{}`; trusted **human** adapter only, unavailable through agent CLI |

Job IDs use 1–100 letters, digits, `_` or `-`; maximum queue size is 10000.
Reservation refuses while another job in the same controller database is
reserved, starting, running, reconcile_required or verifying, even in a different
run. Reservation is not a bypass around native readiness.

Strategy values preserve complete SET strings, including
`value||start||step||stop||Y/N` optimization tuples and large integer identifiers.
Do not coerce every value to a floating-point JSON number, omit dormant inputs,
or replace the discovered dependency policy with guessed input relationships.
Duplicate JSON fields and requests over 2,000,000 bytes are rejected.

### Exact research settings contract

The current research validator requires these **18 tester fields**, with no
missing/unknown keys:

```text
Expert Symbol Period Model ExecutionMode Optimization OptimizationCriterion
FromDate ToDate ForwardMode ForwardDate Deposit Currency Leverage
UseLocal UseRemote UseCloud Visual
```

Use the discovered `tester_fields` array as the machine authority when the
controller version changes.

- `Expert`: relative `.ex5` path, no drive/root/`..`; `Symbol`: nonempty broker
  name. Strings cannot contain CR, LF, NUL, semicolon or equals.
- `Period`: M1/M2/M3/M4/M5/M6/M10/M12/M15/M20/M30,
  H1/H2/H3/H4/H6/H8/H12, D1/W1/MN1.
- `Model`: 0, 1, 2 or 4; `ExecutionMode`: integer -1 through 600000.
- `Optimization=2`, `OptimizationCriterion=6`, `UseLocal=1`, `UseRemote=0`,
  `UseCloud=0`, `Visual=0`: this adapter supports local genetic/nonvisual work.
- `Deposit`: finite positive number; `Currency`: three uppercase letters;
  `Leverage`: string `1:<positive integer>`.
- `FromDate < ToDate`; `ForwardMode` 0–4; `ForwardDate` must be empty unless
  mode 4, when it must lie strictly inside the window.

The legacy **eight export fields** are `SetsToExport` (integer >=2), `MinScore`
(finite >=60), `TargetDD` (finite >=100), `AdjustLots` (boolean), `BackOOSDate`
(date), `MinARF` (finite >=0.2), `MinSR` (finite >=2.5), and `IncludeBackOOS`
(boolean). With back OOS enabled its date must precede `FromDate`.
`IncludeSequenceData` is an **unsupported field in this research validator**.
INI serialization uses CRLF; booleans become 0/1; empty ForwardDate is omitted.

## Bridge and native execution boundaries

The research `studio_bridge.py` processes a bounded inbox cycle. Its CLI takes
`--workspace`, `--database`, `--root`, `--terminal`, `--run`, optional `--limit`
(default 32, range 1–256), `--watch-seconds` (default 0, one cycle), and
`--interval` (default 0.5 seconds). Run it only for an already provisioned binding
when inbox processing is intended; it commits pending commands and writes files.
Starting this worker is not a native launch and does not install a service.

The root contains `binding.json`, `snapshot.json`, `worker.lock` and separate
`human`/`agent` channels with `inbox`, `processing`, `outbox`, `archive`.
Requests are written to a temporary file then renamed to `<request_id>.json`;
channel selection determines actor, not request content. Human commands are
processed first. Failed publication after a committed mutation leaves recovery
evidence in `processing`, so a retry returns the durable original receipt.
Do not remove it to make the queue appear clear.

UI `snapshot.json` queue entries are **display summaries only**: their nested
tester data contains Symbol/Period, not complete executable configurations.
Native adapters must fetch and verify the frozen full configuration from the
controller store. This trusted local protocol is not a security boundary against
other processes running as the same OS user.

Tracked `GOATStudioDispatch.mqh` separately supports native `start` and
`arm_restart` request handling. It verifies terminal/data/install/account/server
identity, current owner/revision/generation, starting job/configuration hash,
short-lived expiry, config/queue/input/owner hashes, native idle state and
full input readback. Its research gate also requires connected demo, DLL support
and terminal Algo Trading off. A consumed record precedes native effects.
These checks are additional to a successful draft/queue receipt.

However, this dispatch implementation still refers to Common Files
`GOAT\GOAT V1.47-<server>`, and the inspected research discovery is pinned to
V1.47. The helper modules (`studio_native_stage`, `studio_native_request`,
`studio_launch_intent`, dispatch/restart adapters, reconciliation and completion
observers) are integration components, not evidence of a shipped V1.48 agent
launcher. Use only a campaign's explicitly qualified native procedure; do not
fabricate dispatch JSON or relabel old evidence to make V1.48 appear supported.

The research `studio_readiness.py --config <existing-config.json>` inspects
binding/ownership, native gate, process/runtime identities, binary hashes and
inventory. It reports blockers and `launch_permitted:false`; it never grants
control or starts a batch. Its config comes from the selected research setup,
not from this guide or an unrelated campaign.

## Recovery and acceptance checks

| Symptom | Next action |
|---|---|
| Unknown terminal/run, missing DB/binding | Resolve the existing controller manifest. There is no agent auto-bind flag |
| Human owns state | Ask the user to save/reload then Give to Agent; do not forge human-channel commands |
| Stale revision / revoked generation | Read current state and reconcile changes; old authority is no longer valid |
| Pending save/no receipt | Preserve pending/request files; inspect matching outbox/processing and controller health; replay identical request only when appropriate |
| Bad local draft/another editor lock | Preserve recovery file, close only the identified competing editor normally, inspect before discarding |
| SET/schema/dependency validation failure | Refresh discovery from the correct source, retain complete tuples, correct the specified input conflict |
| Unsupported IncludeSequenceData | Use supported local V1.48 settings or a qualified controller update; do not strip the error and pretend off was applied |
| Reserved/starting/running/reconcile_required/verifying | Inspect exact native attempt, receipts/process/tester/output state; do not release/reset after a launch intent to force a second dispatch |
| Batch cancelled/interrupted | Verify tester idle and persistent cancellation, retain queue/package, then intentionally choose which work to reactivate |
| CSV/SET exists but on-mode package missing/incomplete | Retain pending/source evidence and logs; do not mark complete, rename an incomplete manifest or borrow another SET's evidence |
| Copy/path failure | Preserve source and compare exact output identities; consult sequence guide. Never silently trim/discard package members to force success |
| Builder cannot construct filtered portfolio | Check complete verified sequence evidence, identity and common observed coverage; import never starts MT5 to repair it |

At handoff record build/hash, exact terminal/run, ownership/revision/generation,
request/receipt IDs, intended vs observed queue state, and output paths/hashes.
Distinguish **draft saved**, **queued**, **reserved**, **native started**,
**tester finished**, **exports verified**, and **builder imported**. One state
does not prove the next.

## Source map and verification scope

| Source | Contract to inspect when behavior changes |
|---|---|
| [Optimizer.mqh](../../Optimizer.mqh) | Local control handlers, settings defaults/serialization, queue, start/stop, batch save/load |
| [GOATStudioUI.mqh](../../GOATStudioUI.mqh) | Managed controls, SET selection, capability-aware export fields, draft/receipt recovery |
| [GOATStudioBridge.mqh](../../GOATStudioBridge.mqh) | Terminal-local binding, snapshots, durable human transport |
| [GOATStudioDispatch.mqh](../../GOATStudioDispatch.mqh) | Native request identity, expiry, ownership, consumption and restart gates |
| [GOATStudioWorkers.mqh](../../GOATStudioWorkers.mqh), [GOATStudioCompletion.mqh](../../GOATStudioCompletion.mqh) | Worker policy and native completion observation |
| [Tester.mqh](../../Tester.mqh) | Selected/adjusted export loops and readiness/move behavior |
| [GOAT_SequenceExport.mqh](../../GOAT_SequenceExport.mqh), [GOAT_SequencePackage.mqh](../../GOAT_SequencePackage.mqh) | Recorder lifecycle, unique attempt routing and complete package publication |
| [Source tests](../../tests/test_sequence_export_source_contract.py), [native harness](../../tests/sequence_export_package_harness.mq5) | Optional setting/protocol source checks; ordinary-pair readiness and off/on filesystem behavior |

Documentation verification: inspected the tracked implementation through optional
setting commit `24bf5ff`, and ran the existing research CLI's `--help` and
`discover` successfully. Discovery reported `execution_ready:false` and the
eight-field export schema. No command in this documentation audit launched work,
created a binding or changed the research controller. Native qualification and
release evidence belong in the [V1.48 sequence notes](V1.48-SEQUENCE-EXPORT.md).

Outstanding portable-controller work is explicit: package/version the research
tools, remove or negotiate V1.47 source/path assumptions, implement the ninth
export field end to end, and qualify fresh binding, native dispatch, cancellation
and recovery for V1.48. These are capability gaps, not available CLI flags.
