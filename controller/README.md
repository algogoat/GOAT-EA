# GOAT Studio controller 1.49 beta candidate

## Recover a stopped same-EA update without editing session files

An older desktop update could rewrite `installation.json` while MT5 was closed
even though Studio already had a session. The new receipt changes its binding
hash, so normal controller commands refuse. Keep the desktop's
`ea-update-backups/<plan-id>/installation.json` and all native attempt files.
First reconcile any outstanding start/cancel request using the original
receipt and the supported owned-attempt commands. Do not delete a request or
permit to make this step pass. Then, with the selected terminal stopped, run:

```text
goat.exe studio --installation <current installation.json> same-ea-rebind
```

This demo-only metadata repair finds exactly one preserved receipt matching
the bound session, requires a forward numbered private-beta update with
identical EA bytes and all non-metadata receipt fields, a settled queue,
no native request/permit, no pending human control,
at least 5 GiB free disk and no running selected terminal. It backs up the
prior session, changes only its installation hash,
keeps the database unchanged and writes an append-only action log. It never
grants control, launches MT5, clears an attempt or qualifies a batch. If it
refuses, preserve its evidence and inspect the original attempt; do not edit
the session or receipt by hand.

## Recovery after native takeover of an internal research continuation

For the existing owner demo continuation only, a genuine native TAKE CONTROL
followed by a fresh native GIVE TO AGENT can create one additive research epoch.
The original scope remains immutable and revoked. The new scope retains the
same account, plan and build and has a fresh 48-hour lifetime. No CLI actor or
confirmation flag can create the native grant.

`research-monitor-repair-revoked-report --job-id <original>` repairs the proven
derived Report baseline mismatch while retaining human ownership. It closes and
relaunches the idle selected monitor through its retained recovery transaction.
`research-regrant-status` verifies native/editor readiness for a real grant; it
does not grant control. Existing permission bytes and user settings are retained.

After the genuine grant, `research-retire-never-started --job-id <original>`
requires an expired, rejected, never-consumed original start, unchanged queued
native members, no output and a stopped prior publisher. It archives the evidence,
normally closes the idle monitor once, restores only the original owned controls,
reconciles the generated Report root, records `retired_never_started`, and
relaunches/reverifies once. It never invents a native cancellation receipt or
deletes the historical queue. Repeating the command resumes the same transaction.

Only that verified retirement permits one exact-plan replacement. Its driver
receives the new epoch's 172800-second budget and at least 5 GiB free-space guard;
host/process recovery never resets its deadline. The original driver's record
is unchanged. Actual native execution still requires consumed START and tester
activity; source fixtures and read-only rehearsal are not native qualification.

If that replacement's Start was consumed but returned exactly
`SETTINGS_NOT_VERIFIED` before any start/arm intent, the stopped driver and
canonical `CANCELLED_RECONCILE` finish may permit one more exact-plan successor.
Preparation, reservation and dispatch independently recheck the original
retirement, consumed refusal, all cancelled native members, absence of work
output and tester cache, restored controls, stopped driver and unchanged grant.
The prior request, result, queue and deadline stay retained; no consumed
request is replayed. A third successor or uncertain/native-started outcome
refuses. The new driver's 48-hour maximum and disk reserve are pinned to the
same genuine native research epoch; this is not proof of native execution.

These bounded owner-recovery commands are the current implementation, not the
general customer setup/recovery toolset. See the proposed
[customer agent tool contract](../docs/operations/AGENT-RECOVERY-TOOLS.md).

This portable Windows controller uses the installed receipt and bundled Python.
Only `goat_studio.py` is the public Studio entrypoint. The other Python modules
implement its validation and durable storage; do not invoke internal helpers or
construct native permits manually. No API accepts a caller-supplied “safe” flag.

For interrupted legacy monitor startup and protected peer handling, see
[the migration guide](LEGACY-MONITOR-MIGRATION.md). A reviewable source candidate
is not an installed or natively qualified release.

The 1.49 controller accepts existing 1.48 installation receipts and uses their
1.48 input contracts and installed EA hash. Local controller development does not
require publishing a new desktop installer or replacing the EA. The selected
EA's normal activation, MT5 permissions and human control grant still apply.

In the unified agent kit, prefix each command below with:

```powershell
& '<agent kit>\goat.exe' studio --installation '<Setup receipt.json>'
```

The standalone equivalent is `python.exe controller\goat_studio.py` followed by
the same arguments, using the bundled runtime rather than a system Python.

## Measure a pilot before committing a research budget

With the installed executable and receipt prefix above:

```text
resource-profile
benchmark-report --batch-id <completed-pilot-batch-id>
```

`resource-profile` works before bootstrap. It observes the current Windows CPU
model, physical/logical processor counts, total/available RAM and the free/total
capacity of the filesystems containing the selected terminal data, Common Files
and controller state. Each observation is timestamped. Paths on the same volume
share capacity: do not add their free space together. Missing inventory stays
unavailable. CPU count is neither enabled MT5 worker count nor a speed estimate;
`enabled_mt5_workers` is null. The Windows CIM probe uses the absolute system
PowerShell path and no console window, without requiring PowerShell on PATH.

Discuss the user's available wall-clock window and disk headroom before preparing
a full batch. Select representative asset/timeframe/settings groups, preserving
exact broker symbols, dates, tester model, forward split, optimization axes and
export settings. Use `prepare-batch` for a small timing pilot, including a
one-member pilot, then the normal authorized `start`, observation and successful
`finish` workflow. Preparation and either inspection command do not launch work.
The user still controls broker login, permissions, pairing and Give to Agent.

After `finish`, `benchmark-report` reads the retained completed job, frozen
preparation receipt, exact attempt/result, native inputs/queue and verified
back/forward reports. It never opens/migrates controller storage, pumps the human
inbox, finishes/reconciles a job, grants authority or launches a terminal.
Incomplete work and changed or mismatched artifacts return an error; preserve
the receipts and investigate the exact batch. Legacy `prepare` jobs without a
batch preparation receipt are not benchmark inputs.

The timing reader requires exactly one ordered native `OnGoing`/`Completed`
QUEUE_STATE pair per frozen alias, with valid nondecreasing local timestamps.
Duplicate, regressing, retry, cancelled, incomplete or foreign-member timelines
leave `timing.status: timing_unknown` and member `elapsed_seconds: null`.
Absence is not zero. Valid observations return `native_timeline_observed`, member
elapsed seconds, `observed_batch_span_seconds` and `between_member_seconds`.
These one-second local wall-clock stamps include native report migration and
selected exports, but exclude initial launch and final controller finish.
Timezone, DST and forward clock adjustments are not attested. Historical
hardware, enabled workers, background load and cache state remain unknown; a
current resource snapshot cannot fill those fields.

Use `workload_sha256`, the exact tester/export settings and active axes to match
observations. `actual_back_report_rows` and `actual_forward_report_rows` describe
retained XML rows, not total genetic passes. Summarize repeated comparable pilots
with their observed range and sample count; label a single sample as provisional.
Build the user's scenario table by workload group and planned member count,
explicitly marking unmeasured groups and additional restart/export/storage
uncertainty. Do not extrapolate SeedFarming to full optimization, apply a blanket
M1 multiplier, or promise linear speedup from processor counts. The command
returns no future estimate or launch permission.

`artifact_bytes` totals only the exact frozen package, completion result, native
queue/inputs, report XML, timeline and alias/symbol SET/CSV exports examined. It
excludes tick/history caches, tester agents and temporary storage and is not a
future disk requirement. Reads are bounded to 64 MiB per file and 512 MiB per
artifact group; package/export inventories also have file-count limits. At most
100 members are included inline, with `members_omitted` identifying larger
batches. Prefer small representative pilots. Missing timing does not qualify a
workload just because its reports exist.

A larger pool of diverse, independently validated strategies can give portfolio
construction more alternatives across assets, regimes and behavior. Duplicated
or correlated strategies and overfit results do not establish useful diversity;
more candidates do not guarantee better portfolios or returns. Use measured
research cost and independent validation to choose the next increment with the
user, then revisit the budget as evidence accumulates.

## Agent-assisted monitor onboarding

After desktop sign-in, use desktop `onboarding.status` for beta access and the
user's own linked account. These Studio commands operate the selected installed
terminal and do not enroll a tester, approve EA pairing, or collect passwords.
The user signs in to their own demo directly in MT5, turns Algo Trading off, and
closes that terminal normally when setup requires a stopped terminal. Never stop
another terminal to satisfy setup checks; arrange an isolated research session.

With the usual executable and global installation prefix above:

```text
bootstrap --account-login <own-demo-login> --account-server <exact-broker-server>
onboarding-status
monitor-prepare --symbol <exact-broker-symbol>
monitor-launch --attempt-id first-monitor-open
serve --watch-seconds 3600
```

`monitor-prepare` writes a dedicated `GOAT-Studio-<session>` profile, including
one persistent chart and the actual installed EA path. It selects Studio's
read-only monitor inputs and leaves DLL and trading permissions disabled on the
chart. It neither changes the user's existing profile nor edits `common.ini`.
`monitor-launch` supplies an immutable, hashed `/config` with explicit StartUp
expert and verified monitor preset, keeping the dedicated saved profile. The
saved account must match the session and Algo Trading must remain off. This
operation requires the selected terminal to be stopped and never enables trading.
An explicitly reviewed protected peer may be stopped; a different process still
requires a new review.

MT5 saves the GOAT input group headings as equals-framed label rows with an
empty value inside the expert's input block. The saved-profile verifier accepts
that heading syntax; it still rejects duplicate real input keys, scripts, changed
EA paths, non-monitor inputs and changed permission flags. In particular, a
saved `expertmode=4` remains refused: this parsing correction does not approve
permissions or qualify a native relaunch. Preserve the saved chart and follow
the reported human review/reopen instruction instead of editing its flags.

If an MT5 update discarded the startup arguments, `monitor-repair --attempt-id
<unique-id>` can recover an empty, never-started monitor session. The official
MetaTrader5 Python adapter must be available in the controller runtime. It checks
the exact existing selected process, saved demo identity, connection, zero open
positions/orders, Algo off and a positively idle native tester before issuing
one normal close. It preserves the original profile and journals the close and
new explicit startup. An uncertain close is never resent, a replacement process
is never adopted, and native campaign flags/grants are untouched. The SDK is
available in the local developer probe environment; inclusion in the customer
installer remains a packaging requirement.

`monitor-stop --attempt-id <unique-id>` uses the same idle-demo checks for an
authorized upgrade, closes normally once and retains the result without changing
the profile or relaunching. Reuse the same ID to inspect an uncertain outcome;
a reopened terminal is refused, never closed again or adopted.

V1.49 MONITOR-ONBOARDING-5 corrects the compact agent connection screen for an
empty session and small charts. A genuine human handoff is possible before the
agent creates settings; no default trading/test settings are invented. Existing
saved drafts and partial/malformed states still require recovery. Fresh OnInit
and UI observations, not a queued chart command, establish activation progress.
Automatic activation reload is bounded to20seconds and reports
`ACTIVATION_RELOAD_REQUIRED` on failure. The controller exposes the same reason
for a fresh matching activation status. Native qualification is still pending.
The -4 native screen exposed an overlapping legacy form because controls were
registered in the dialog client area, not its empty backdrop. The -5 layout
hides actual client children before showing only connection controls. The
production-layout regression covers recursive reveal, compact sizes and all
four stages after widening. Native visual acceptance of -5 is still pending.

WebRequest setup uses only `https://goatedge.ai`. The agent provides that exact
URL and checks readiness after the user's MT5 approval. DLL imports are separate
from live trading permission. Automated permission-dialog navigation and scoped
permission preparation are tracked in CTRL-012; they are not implemented here.

The human approves DLL imports and the exact WebRequest URL displayed by GOAT,
completes legitimate GOAT device activation, and clicks **Give to Agent** in
Studio while `serve` runs. Run `onboarding-status` again to inspect the resulting
state. It does not consume pending human requests; `serve` performs that step.
A stale monitor, changed account, enabled Algo Trading, unknown tester state or
mismatched owner/revision/generation remains blocked. `local_monitor_ready`
means these local observations match; `execution_ready:false` and
`native_qualification:false` remain explicit. Job start still rechecks runtime,
ownership, license-dependent initialization and frozen artifacts. Desktop beta
eligibility and actual native execution qualification are separate evidence.

A launch attempt ID is never replayed. The same ID returns its retained result,
even after process exit. After a normal close, a new explicit attempt ID may
reopen the saved monitor; the controller revalidates the chart's EA path, inert
Studio inputs, symbol, permission flags and absence of extra charts/indicators.
MT5 metadata changes can persist. Automated launch accepts only the original
zero permission flags until actual MT5 fixtures qualify their bit meanings. If
the human's DLL approval changes saved flags, the human must review and reopen
that saved profile in MT5; the controller never resets or guesses permission
bits. A launch error or crash retains `launch_intent`
and blocks new attempts until the uncertain effect has been inspected. Preserve
that evidence and use support if it cannot be resolved; do not delete it to
force a retry. Partial profile staging is also preserved and never overwritten.

The profile format follows the repository's existing persistent-chart bootstrap.
Only fixture acceptance has been run for these commands. Real broker-symbol
acceptance, human permissions/activation, normal-close persistence and at least
two native members still require the exact packaged build's MT5 qualification.
MT5's [startup documentation](https://www.metatrader5.com/en/terminal/help/start_advanced/start)
distinguishes precreated `/profile` charts from disposable `[StartUp]` charts.

## Commands and effects

| Command | Required options | Effect |
|---|---|---|
| `discover` | None | Read-only installation/hash/schema/capability inspection |
| `validate-set` | `--set`, optional `--require-optimization` | Read-only encoding, complete input, active range and partial dependency validation |
| `build-set` | `--source`, `--output`, `--spec` | Clone a real SET with narrow typed replacements; new unique identity, support notes and provenance |
| `bootstrap` | `--account-login`, `--account-server` | Create local human-owned binding and monitor preset; never launch |
| `onboarding-status` | None | Read-only local binding, process, fresh monitor and human ownership stages; exact recovery steps |
| `monitor-prepare` | `--symbol` | Stage a separate persistent inert monitor profile while terminals are stopped; preserve other profiles |
| `monitor-launch` | `--attempt-id` | One retained launch of the prepared profile; verify saved account, Algo-off, process and job state |
| `serve` | Optional `--watch-seconds` | Process Studio inboxes; default 3600, range 0–3600; zero is one cycle |
| `state` | None | Process pending UI commands then return drafts/queue/ownership |
| `submit` | `--request` JSON file | Submit exact versioned agent command envelope; no actor override |
| `prepare` | `--job-id`, `--set`, `--configuration` | Freeze complete inputs, queue job and stage immutable native package |
| `prepare-batch` | `--batch-id`, `--plan` | Freeze all file/asset members of a complete native queue; no launch |
| `batch-status` | `--batch-id` | Reconcile native queue and every member's progress |
| `save-batch` | `--batch-id`, `--output` | Save a standard `.goatbatch` outside controller state; never overwrite |
| `load-batch` | New `--batch-id`, `--file` | Validate a saved `.goatbatch` as new unstarted work on this installation |
| `resume-batch` | `--source-batch-id`, new `--batch-id`, optional `--include-failed` | Prepare verified unfinished members after original completion/cancellation; no launch |
| `start` | `--job-id` | Recheck demo/runtime/binary/ownership, reserve, activate and publish one start |
| `status` / `reconcile` | `--job-id` | Inspect retained native attempt, dispatch, runtime and report evidence |
| `cancel` | `--job-id` | Cancel pending job or publish owned native stop; reconcile before claiming stopped |
| `finish` | `--job-id` | Confirm terminal idle and terminal queue outcome, retain result, restore owned controls |
| `seed-prepare` | `--batch-id`, `--plan` | Validate and freeze a dedicated bounded SeedFarming campaign |
| `seed-start` / `seed-resume` | `--batch-id`, optional `--max-seconds` | Drive selected-terminal seed work for a bounded call; retain running work at call timeout |
| `seed-status` | `--batch-id` | Observe retained seed campaign progress |
| `seed-cancel` | `--batch-id` | Request owned seed stop; verify exit before reporting stopped |
| `seed-report` | `--batch-id` | Read actual seed evidence and per-job provenance, including unknown or missing results |

Read the installed [complete runbook](goat-beta-agent-guide.md) for a full native
batch plan, save/load/revision examples and per-member matrix reporting. Read
[SeedFarming](SEED-WORKFLOW.md) for its separate mode, no-forward plan, limits,
terminal closure and recovery. All [114 EA inputs](INPUT-REFERENCE.md) and
[public capabilities](goat-agent-capabilities.md) are included in this kit.

`start` supports the **first pending controller job**, which can contain a full
native batch of frozen file/asset members. The beta uses local genetic
optimization (`Optimization=2`, criterion 6), a custom forward date (`ForwardMode=4`),
nonvisual testing, local workers enabled and remote/cloud workers disabled.
Only the chosen MT5 executable may be running for native activation. If another
terminal is open, stop here and let the user close it normally; do not kill it.
The controller does not install a service or automatically start a separate
controller job. A native batch starts once; Optimization Studio advances its
native queue across the frozen members. Initial activation queues the first
member and retains the rest as Pending. Every member's settings, input hashes,
native progress and report evidence are independently checked. Native terminal
restart/continuation still requires actual lifecycle qualification; controller
unit tests do not prove runtime acceptance.

Batch progress includes member status counts, completed/finished totals and the
active member indices. Cancel disarms the entire owned native batch and cancels
its unfinished rows while preserving completed rows. Finish requires all members
to reach a terminal state and verifies reports for every completed member, even
when another member failed or was cancelled. Results retain each member outcome;
never present a partly completed batch as entirely successful. Save/load creates
new frozen work through the installed batch API; resume must preserve prior
outcomes and use a new explicit attempt for selected unfinished members.

## Configuration

For creating and validating files, read [template creation and seed research](TEMPLATE-WORKFLOW.md).
These commands require the installation receipt but no Studio binding or running terminal.

`prepare --configuration settings.json` requires exactly two top-level sections:

```json
{
  "tester": {
    "Expert": "GOAT-EA\\GOAT V1.48.ex5", "Symbol": "EURUSD", "Period": "M15",
    "Model": 1, "ExecutionMode": 0, "Optimization": 2, "OptimizationCriterion": 6,
    "FromDate": "2025.01.01", "ToDate": "2026.01.01",
    "ForwardMode": 4, "ForwardDate": "2025.10.01",
    "Deposit": 10000, "Currency": "USD", "Leverage": "1:100",
    "UseLocal": 1, "UseRemote": 0, "UseCloud": 0, "Visual": 0
  },
  "export": {
    "SetsToExport": 2, "MinScore": 60, "TargetDD": 100, "AdjustLots": false,
    "BackOOSDate": "2024.01.01", "MinARF": 0.2, "MinSR": 2.5,
    "IncludeBackOOS": true, "IncludeSequenceData": true
  }
}
```

These are illustrative settings, not a recommendation or the user's broker
symbol. Read `discover` for authoritative fields. All 18 tester fields are
required; use the receipt's exact Expert. Models 0/1/2/4 are allowed. Execution
delay is -1 through 600000; deposit must be positive and finite. Currency is three
uppercase letters, leverage uses `1:N`, and dates use `YYYY.MM.DD`.
Start < forward < end; native package preparation additionally requires the BOOS
date before start even when BOOS export is off. Unsupported combinations fail
before activation. Period choices are returned by discovery.

Nine export fields are supported. SetsToExport >=2; MinScore >=60; TargetDD >=100;
MinARF >=0.2; MinSR >=2.5. AdjustLots, IncludeBackOOS and IncludeSequenceData must
be JSON booleans. Older eight-field settings normalize to IncludeSequenceData=true.
Unknown keys are rejected. Explicitly choosing false disables capture. Native
selected fixed exports use their existing real-tick policy independently of the
genetic search model. Adjusted-lot export results retain a qualification notice
until the builder verifies their exact evidence.

SET files retain UTF-16 LE BOM, CRLF, scalar values and full optimization tuples.
The only native staging change is the unique EA_Desc attempt alias; the package
retains source hash and unchanged canonical trading inputs. Every active axis is
checked for type, enum ladder and range geometry. Partial indicator-mode dependency
checks catch disabled indicators with active axes; they do not prove all possible
strategy interactions or profitability.

## Draft API

`submit` consumes an envelope with exactly `schema_version:1`, `request_id`,
`terminal_id`, `run_id`, `expected_revision`, `generation`, `command`, `payload`.
Use values from `state`; the actor is always agent. A human must Give to Agent.
The same request ID plus exact envelope replays its durable receipt; changed
content with the same ID is rejected. Keep the original request file for retry.

Commands: `draft.replace_tester` (complete tester object), `draft.replace_export`
(complete export object), `draft.replace_configuration` (`tester` and `export`),
`draft.replace_strategy` (`schema_hash` plus complete input `values`),
`queue.enqueue` (`job_id`), `queue.revise` (`job_id`, `replaces_job_id`),
`queue.cancel` / `queue.remove` (`job_id`, pending only), `queue.reorder`
(`job_ids`, every pending ID exactly once), `queue.reserve` (job ID plus
configuration and package SHA-256), `queue.release_reservation` (job ID plus
reservation ID, only before launch intent). Normal users should use `prepare`
and `start`; reservation methods are recovery primitives, not launch shortcuts.

UI snapshots contain queue **summaries**. Only the controller database retains
full executable frozen configurations. Never reconstruct tester settings from a
summary or use stale ownership to replay a launch.

## States, stopping and recovery

Draft saved → pending → reserved → starting → running → verifying → completed
are distinct observations. A sent Start message is not proof of running, and a
completed optimization queue is not proof of profitable or usable exports.
`reconcile_required` means inspect the retained evidence before doing more work.

| Situation | Action |
|---|---|
| Human owns state | In V1.49's verified fresh empty session, user may Give to Agent before drafts; reload saved drafts and recover partial/malformed state. Never forge a human command |
| Interrupted same-version EA build update | Preserve the installer inputs and PARK archive. The authenticated installer must recheck admission, then reconcile that exact `switch-replace-build` transaction. Never delete its pending fence or edit the EA/receipt pair |
| No UI receipt | Keep serve running; inspect inbox/processing/outbox. Never delete pending recovery files |
| Stale revision/generation | Read state; reconcile human changes. Old authority is revoked |
| Prepare interrupted | Retry same job/input identities; preserved envelopes replay. Partial package requires inspection |
| Missing/stale runtime observation | Check monitor preset, selected terminal and demo connection; do not bypass freshness |
| Start publication uncertain | Use status. Existing intent/issued/consumed receipt forbids another start |
| Request expired before native consumption | Preserve attempt, inspect status, then cancel/reconcile; never renew old permit manually |
| User asks stop | `cancel`, then status. Native cancellation persists before stopping and disables continuation |
| Cancel issued but no receipt | Monitor may be unavailable. Use native Studio Stop; retain attempt, verify idle, then reconcile |
| Queue complete but reports missing/changing | Wait/reconcile exact reports. Missing output is not “zero qualifiers” |
| Finish rejected | Correct the stated evidence/ownership issue. Do not delete native owner, DB or queue |
| Another installation/update selected | Keep old session and frozen inputs; repair/rebind only after unresolved work is reconciled |

Finished outputs remain under the unique Common Files run; `finish` returns a
result JSON with native artifacts, configuration and observed report/export
evidence. Append it to My results using the attempt ID. It does not upload data,
claim independent performance verification or automatically import a portfolio.
The original SET, package, request envelopes and result receipts remain retained.

The local receipt/database protocol trusts processes running as this Windows
user; it is an ownership and recovery mechanism, not a security sandbox.

## Release engineering verification

Run `python -m unittest discover -s controller -p "test_*.py"` for portable
receipt/prepare/ownership checks. These tests do not launch MT5. Native source
must also compile without warnings and be qualified with actual bound MT5
start/status/cancel/finish before a release claims that lifecycle is verified.
Customer documentation describes supported process; qualification evidence
belongs in the release notes rather than copying a developer's paths here.

## Safe switching and restoration

### Clear pending work and prepare a fresh batch

Use `clear-queue` to preview pending job IDs and the current revision. To remove
that pending work, use `clear-queue --apply --request-id <unique-id>
--expected-revision <preview-revision>`. Retry the exact same identity and revision
after a transport failure. The operation is atomic and requires current agent
ownership. A changed queue/revision requires a fresh review and a new request ID.
It marks pending jobs removed while retaining their packages, configuration and
history. Completed results, other settled jobs and drafts are unchanged. It refuses
unresolved attempts across controller bindings, active seed work and unconsumed
native requests/permits; it never treats clearing a queue as stopping a tester.

Then run `prepare-batch --batch-id <new-id> --plan <plan.json>`, inspect
`batch-status --batch-id <new-id>`, and explicitly `start --job-id <new-id>` when
ready. Clearing and preparation never launch work. Old job IDs remain reserved
for provenance; do not reuse them for a new experiment.

For inconsistent native flags, run `native-recovery-status`. It reports runtime
identity/readiness failures and remaining controls without clearing anything.
`cancel` requires an exact owned attempt; `finish` requires its observed native
completion and idle runtime. Neither repairs an orphan `BatchOnGoing` flag. A
possible orphan requires the matching V1.49 reviewed native recovery capability;
do not edit global-variable files, call Start/Stop as a reset or fabricate a launch
receipt. See [native recovery contract](NATIVE-RECOVERY-CONTRACT.md).

### Time-budgeted batch execution

After preparing and checking a batch, `run-batch --job-id <id> --max-seconds 86400`
drives its existing owned start/status/cancel/finish operations with a durable
deadline (1..86400 seconds). At the deadline it requests cancellation once and
waits a bounded grace period for native stop/readback. It never equates issuing
cancel with confirmed stop and never force-kills MT5. Keep the driver process
running: an agent/process crash is not an autonomous native deadline mechanism.
`batch-driver-status --job-id <id>` reads progress; `run-batch --job-id <id> --resume`
uses the original deadline without replenishing its budget or retrying uncertain
starts. Driver authority remains tied to the original generation. A changed
grant, configuration or native identity requires reconciliation.

The driver also requires 5 GiB of free space on each terminal-data, Common-files
and controller-state filesystem. `--min-free-bytes <positive integer>` selects a
reserve for a new run; zero cannot disable protection. Low capacity or an
unavailable probe refuses dispatch before a start journal or native start is
issued. During execution either condition requests cancellation of the exact
owned attempt through the same one-shot cancel/readback path. The journal and
status retain `min_free_bytes`, `disk_observation` and `cancel_reason` even after
confirmed completion. Resume preserves both the original deadline and reserve;
omit both options. Active legacy journals without a retained disk guard require
reviewed recovery rather than automatic resume; their status remains readable
and explicitly reports `disk_guard_available: false`.

Capacity is sampled by the running driver, not an independent native watchdog.
The reserve is headroom for cancellation/evidence, not a prediction of required
history or tester-agent storage. A rapid disk loss or failed journal write can
still leave stop unconfirmed. Never infer a stopped tester from a cancellation
request or delete history/queues to manufacture free space.

### Pausing and resuming a batch

`batch-pause --job-id <id>` (demo lane: `demo batch-pause --batch-id <id>`) is the
supported way to stop research without losing work. It sends one cancel only at
a safe point while the bound monitor reports, waits for the EA's own
`CANCEL_REJECTED` before sending exactly one successor for an expired cancel,
never sets the driver journal's `cancel_issued`, keeps the driver's disk guard
and finish running, and records `paused` with a resume token. A journal left at
`stop_unconfirmed` is adopted. `batch-resume --job-id <id>` prepares the
remaining members as `<id>-rN` with lineage (the demo lane also starts it).
`research-status` is the read-only lane view. Rules and states:
[AGENT-START-HERE.md](AGENT-START-HERE.md) and [DEMO-AGENT-TOOLS.md](DEMO-AGENT-TOOLS.md).

### Evidence end and OOS catch-up

An export's evidence ends where its export test ended, so exports from different
weeks end on different dates. The **evidence end** ("front OOS" end) is either
`auto`, the latest fully closed Friday on the broker's New York-close clock
(UTC+3 in US daylight time, UTC+2 otherwise; the week closes at server Saturday
00:00, so on a Friday before the close `auto` is still last Friday), or an
explicit broker date that has already closed. Dates are inclusive server dates;
MT5 `ToDate` is exclusive, so evidence ending on day D tests with `ToDate` D+1.

- `evidence-end [--value auto|YYYY-MM-DD] [--broker-clock ny-close|utc+N]`
  resolves it (read-only) and shows what this EA build ends batch exports at now:
  the EA's own last Friday as `ToDate`, so Thursday evidence. The current EA has no
  EvidenceEnd export setting (`ea_evidence_end_setting.supported: false`).
- A batch plan may carry `"evidence_end": "auto"` (or a date). `prepare-batch`
  records the resolved target in `studio-plan.json` (`native_batch.evidence_end`),
  `resume-batch` keeps the original request, and `batch-status` shows it. The EA
  still ends its exports natively; catch-up brings them to the target.
- `evidence-scan --source <run, deploy or member folder, or .set> [...]
  [--evidence-end auto|date] [--include-below-threshold]` reads every kept export
  (SET header windows, equity CSV, `.goatseq` manifest; never `account.csv`) and
  classifies it against the target: `behind` (needs catch-up), `current`, `ahead`
  (already ends later; clip it to the shared end, no re-test), `caught_up` (a
  retained catch-up version already ends there) or `ineligible` with reasons
  (below the run's MinARF/MinSR thresholds, another broker server, unknown tester
  settings, not standard mode). The capture's observed end is authoritative; a
  capture stopped by the row limit falls back to the SET header's FOOS end.
- `catchup-validate --plan` previews and `catchup-prepare --catchup-id --plan`
  freezes a plan `{schema_version:1, evidence_end, sets:[absolute .set paths],
  job_timeout_seconds[, broker_clock, assume:{ExecutionMode}, include_below_threshold]}`.
  Each behind export becomes one member: its exact kept SET (frozen values, no
  optimization) from the export's original start to the evidence end, with the
  original deposit, currency, leverage and delay from the run's `manifest.json`
  (a library copy without its run folder needs `assume.ExecutionMode`, recorded as
  assumed and checked by the reproduction test below). Original exports are never
  changed.
- `catchup-start`/`catchup-resume` (`--max-seconds` 1..3600), `catchup-status`,
  `catchup-cancel` and `catchup-report` drive and read it.

How it runs natively, with no EA change: the native Studio queue only runs
optimizations, so catch-up reuses the SeedRunner process driver. Each member is one
MT5 start with a `/config` INI: `[Tester]` `Optimization=0`, `Model=4`,
`ForwardMode=0`, `ShutdownTerminal=1`, `FromDate` = original start, `ToDate` =
evidence end + 1; `[TesterInputs]` = the frozen values plus the EA's own export
inputs (`EA_Desc=<alias>@{mode=EXPORT,dt_BOOS_end,dt_FOOS_start,dt_FWD_start,dt_FWD_end}`
and `Sequence_Export_*`, exactly as `RunAndStoreSet` passes them). The runner
stages the capture's `GOATSequencePending\<id>\source-inputs.set` before launch;
the EA writes its usual SET/CSV/`.goatseq` unit into `Common Files\TEMP\SQ\<token>`
and the runner moves it to `<controller state>\evidence\<catch-up id>\<alias>\`
with an `evidence-version.json` that links the original (same `values_sha256`, new
end date). Catch-up shares the seed terminal slot (`seed-active.json`), owner STOP,
pause and broker-verified start record rules, and stops after any failed member.
It is `native_launch_qualified: false` until a native proof run shows: the EA
accepts a `/config` single pass with plain-valued `[TesterInputs]` and writes the
export unit to the attempt root; MT5 exits after the pass; the moved unit's
`effective-inputs.set` and equity rows reproduce the original before the new weeks.

New-weeks-only verdict (`goat-catchup-verdict-v1`, `studio_catchup_verdict.py`):
only the days after the original evidence end are judged; the original forward
window measured inside the same re-test gives the pace. `not_comparable` (inputs
differ), `failed` (a new worst drawdown, or at least 5 trades with a loss and PF
below 0.8), `too_few_trades` (fewer than 5 trades opened), `held_up` (profitable,
PF at least 1, drawdown within what it had already shown, and at least half the
forward profit pace) or `weakened`. Every verdict carries the trades, net, PF,
drawdown, the forward pace, whether the re-test reproduced the original export
(equity rows and deals before the new weeks) and `confidence` (`low` unless at
least 20 trades over 10 trading days reproduced). A few weeks is a small sample.
`evidence-versions` lists retained versions.

### Reviewed orphan continuation recovery (V1.49)

`orphan-recovery-prepare` freezes exact idle demo/runtime and single-owner evidence.
After the user explicitly approves that review, `orphan-recovery-apply --review-id
<id> --confirm-reviewed` publishes the one native action. Use
`orphan-recovery-status --review-id <id>` for the retained receipt and fresh
readback. The native action clears only the positively reviewed BatchOnGoing flag;
it never starts/stops trading or testing, changes grants, clears queues, or edits
native control files. Ambiguous delivery remains fenced and requires review.
Legacy monitors and foreign gate owners are refused. Native Windows qualification
and a compatible installed monitor are still required before promotion.

If the exact retained receipt is `ORPHAN_REVIEW_REJECTED`, `ORPHAN_RUNTIME_REJECTED` or
`ORPHAN_FOREIGN_CONTROL`, no consumption exists
anywhere in the selected local Studio tree, and the request has expired, review
that rejection before using `orphan-recovery-reconcile-rejection --review-id
<original-id> --confirm-reviewed` within authorized recovery maintenance. This
separate command in its default running mode requires the original process, monitor, account, agent grant,
state and idle orphan flag to match. It supports only an originally empty native
gate; other results or prior controls remain fenced.

Recovery publication uses a 45-second expiry inside the EA's unchanged 60-second
ceiling. Before writing transport, the controller requires a valid terminal UTC
observation whose timestamp differs from its file write time by at most five
seconds. This compares both clocks when feedback was written; fifteen-second-old
feedback with matching clocks remains valid under the separate, unchanged
20-second runtime freshness check. Check clock synchronization for a skew refusal
or fresh monitor feedback for a freshness refusal, then retry only an unissued,
still-valid review. Issued or uncertain requests are never resent. This prevents
a zero-margin expiry rejection; it does not prove the cause of any tester report.

ORPHAN_REVIEW_REJECTED is an initial native request-validation refusal, before
the runtime and foreign-control checks. It does not identify which schema,
identity, path or expiry predicate failed. Preserve the original request and
native result to diagnose that difference; do not attribute it to a runtime
script or foreign file without evidence. Settlement only retires the expired
transport after all existing checks, and leaves BatchOnGoing unchanged.

Older installed controllers may refuse this status. Use a released controller
that explicitly supports it; do not edit the allowlist or install loose Python
files in a signed/hash-verified bundle. Authorization is either explicit human
approval of this exact settlement (`--confirm-reviewed`) or the separately
audited, owner-scoped `--owner-research` route, including its typed research
authority checks. The latter does not represent human confirmation; its original
grant, account/session and operation scope must still verify. Neither route
authorizes a new recovery attempt. If process/account/state has changed, the
preserving checks still refuse: retain evidence for supported recovery.

Settlement retains the original review, issued/result receipts and transport
bytes plus a durable cleanup intent. It removes only the exact rejected request
and permit, marks `rejected_settled`, then removes that review's pending fence.
It does not clear BatchOnGoing or retry recovery. Resume interrupted cleanup with
the same command and review ID; never remove evidence manually. A status call
only reports an interrupted rejection settlement and cannot finish it. Diagnose
the rejection before preparing any later recovery, which needs a fresh review
and the applicable explicit human or audited owner-research authorization.
These controller fixtures are not native qualification.

### Explicit stopped-terminal rejection settlement

Missing-permit handling is evidence-bound: a released controller can settle an
initially absent `permit.json` only with the exact retained issuance/request,
expired supported native rejection, no consumption and unchanged stopped
identity. It records absence in the existing settlement intent and never
creates a replacement permit. Missing or uncertain outcomes remain fenced;
settlement does not grant permission, recover flags or start work.

A released controller that includes this feature can use
`orphan-recovery-reconcile-rejection --review-id <original-id> --confirm-reviewed
--terminal-stopped` after the user approves this exact stopped cleanup. This is
an explicit alternative to the default same-process route, never an automatic
fallback. It does not stop or reopen MT5. Native qualification and matched
packaged delivery remain required; source tests alone do not make it available
in an older installed beta.

The selected terminal must be positively absent from a complete process
inventory at every cleanup boundary. Unmapped or ambiguous processes, changed
protected peers, pending human commands, changed installation/session/account
bindings or local state, and any native consumption refuse cleanup. The original
byte-exact rejected result stays in place as the EA's one-shot replay barrier.
No old monitor feedback is represented as a current idle/account/flag readback,
and no normal-exit receipt is invented. The existing local ownership, transport,
consumption, archive and permit-before-request checks still apply under the same
locks. No native flag, history, queue, file outside this transport, or grant is
changed.

The journal records this stopped mode and the actual process-absence observation.
Interrupted cleanup must resume with the same mode and review ID.
If MT5 starts during cleanup, settlement remains pending with its fence and
remaining transport retained. Stop that terminal again before resuming the same
review; do not create a replacement review or switch to the running mode.
The stopped scan reads all Windows-visible executable paths and refuses every
executable under the selected installation/data roots, including renamed copies.
It also retains named-terminal checks for unmapped paths and changed protected
peers. The receipt records the number of unreadable process paths: unrelated
system processes may hide their paths, so this is not a security boundary against
privileged or hidden processes. A named terminal with an unreadable path refuses.
The original process observation is archived and hashed before cleanup intent;
resumption validates its exact roots/counts/visibility fields and compares it
with that retained copy. Later absence scans do not rewrite the original proof.
Historical status cannot retire a later fence. The offline route requires explicit human
confirmation; neither `--owner-research` nor typed research-continuation authority
is accepted offline. After settlement, reopen through a supported path and obtain
a fresh native observation and new recovery review. Never reuse the rejected
request or its old observation, and never treat settlement as recovery or start.

### Current monitor journal diagnostics (V1.49 internal -6)

`V1.49-ORPHAN-DIAGNOSTIC-6` adds journal-only visibility into the existing
orphan-recovery runtime guard. A rejected runtime check records its first fixed
reason. A bound, loaded, read-only monitor with `BatchOnGoing` set also observes
the same guard during the existing managed observation cadence. Those messages
say `CURRENT_MONITOR_OBSERVATION`, `NO_ACTION`, and
`current_state_not_original_rejection`: they describe the current monitor, not
the cause of an earlier request's rejection. `CURRENT_GUARD_PASS` does not approve
or perform recovery. Settle any retained rejected request through its supported
review before a monitor upgrade; never resend it to obtain diagnostics.

Only fixed reason labels and numeric chart-query error values are logged; no
account, server, monitor, request or path identifiers are printed. Query errors
are captured before and after the failed read without resetting `_LastError`,
so unchanged values can be stale and are not proof of a fresh platform error.
Repeated identical diagnostic tuples are suppressed, with at most 16 journal
messages per EA load. No new timer, request, receipt, observation field, flag
change, grant or trading action is introduced. All original recovery guards,
statuses and the reviewed native recovery action remain in place.

Source contracts in `test_studio_recovery_diagnostics_source.py` check guard
ordering, unchanged recovery action/observation bytes and logging boundaries.
These tests do not execute MQL5 or qualify a native monitor. The V1.49 dependency
policy pins this distinct -6 main source (SHA-256
`838b4a8e0698b1ccbaecf5819655b8a4ceb142ea2d1ae519f87cd71f7bbdbb1e`);
that source provenance alone is not compilation or admission.

Internal `V1.49-ORPHAN-DIAGNOSTIC-7` retains the same refusal and adds a local
`GOAT ORPHAN SCRIPT` journal line when `CHART_SCRIPT_NAME` is nonempty. It names
the chart ID, whether that chart hosts this EA, and MT5's reported script name
before returning `SCRIPT_PRESENT`. This diagnoses a persistent native refusal;
it does not clear the flag, authorize recovery, or change trading. Treat script
names in the local MT5 journal as diagnostic data. The -7 V1.49 dependency
policy pins main source SHA-256
`824f23628a400c896097c0aab47b04868bd79b9e996c224a1f6019b22af15477`.

Root compiled clean source commit
`94cf75f640ab014f885b7126980f94bbcab4e47a` with MetaEditor 5.0.0.6230:
**0 errors, 0 warnings**. The source and staged main hashes matched. This PR
tracks the resulting 2,255,896-byte candidate, SHA-256
`30ae456630a962de99711de6321f465df9ef6dcd3dc53258cd57aeb8cf419d6c`.
The retained compile receipt SHA-256 is
`e64d428a733e019cd17456370924724cc23d2f7f3e42bbdfda1edec99670521d`.
The admitted -5 artifact remains preserved in Git history at the compiled source
commit, SHA-256
`62a882c362880fe2682a9d427125f9a551727eabe1463f00a6523c60cd429f61`.
No MQL source changed when the compiled candidate was promoted into this PR.
This candidate is **not admitted or installed** and still requires admission
and reviewed native qualification before use.

### Park and restore an entire research session

If bootstrap refuses an existing Studio activation, never delete active.json,
permits, gate owners, databases or pending jobs. Stop the selected MT5, MetaEditor
and relevant controller/runner processes first. A separately reviewed protected
peer may remain running with its exact recorded identity. Without that policy,
all terminals must be stopped. The installed public CLI supports:

```
goat.exe studio --installation <installation.json> switch-plan
goat.exe studio --installation <installation.json> switch-status --review-id <id>
goat.exe studio --installation <installation.json> switch-apply --review-id <id> --confirm-reviewed
```

Explain every affected binding/database and pending-job count before the user
confirms. An agent may use `--confirm-reviewed` only after that explicit user
instruction. In the desktop app, the agent prepares `onboarding.prepareSwitch`
and the user confirms the displayed review themselves; there is no agent
confirmation RPC. Reviews expire after ten minutes and changes invalidate them.
The next successful review prunes expired, never-applied review metadata only;
completed/recoverable receipts and parked research are retained.

Ordinary commands hold a shared session lock, so `serve` and bounded seed drivers
can coexist with `state`, onboarding checks and cancellation. Handover apply takes
the exclusive counterpart and refuses while any ordinary command is running;
ordinary commands refuse while apply is in progress. Existing native mutation
gates continue to serialize individual commits.

The handover refuses the running selected terminal, unknown or changed peer
processes, controller writers, unresolved native jobs,
seed ownership, unconsumed requests/permits, shared/ambiguous databases and
filesystem aliases. It revokes old agent generations, then parks the entire
terminal GOATStudio directory and app controller state under an attempt-specific
archive outside both directories. The installation receipt remains registered.
Queues, drafts, results, profiles outside GOATStudio, Common Files and credentials
are not discarded. No process is stopped or launched automatically.

Older unscoped campaign completions embed their outcome in the queue rather than
using the newer `completion_path`. Offline handover verifies their consumed
request, exact package and terminal binding, retained outcome, restored control
transaction and absent control files. This compatibility route preserves the
original evidence and grants no current worker clearance; a missing or mismatched
proof still blocks switching. Ordinary queue mutations retain their current
completion contract.

After parking, run ordinary bootstrap for the explicitly selected demo account.
The new session is human-owned and requires the user's fresh Give to Agent.
Restoration is also reviewed: `switch-plan --restore-id <completed park id>` then
apply that NEW review ID. This parks the newer session before restoring the old
files. Old control remains human-owned. A changed app/EA installation or externally
changed archived database requires a compatible migration; restoration refuses it.

Keep the returned recovery ID. After any timeout or interrupted directory move,
inspect `switch-status` and retry ONLY `switch-apply` with that same review ID.
The journal can recover even if the original installation receipt is temporarily
inside the parked state directory. Normal controller commands refuse until the
retained handover completes. Never manufacture a new attempt to clear the fence.
When the terminal and app state are on different volumes, the same reviewed
handover uses a retained `.studio-transfer-*` journal beside the destination.
It copies into staging on that destination volume, fsyncs each file and verifies
the complete reviewed SHA-256 inventory before publishing the directory. Only
then does it remove matching source files and their known empty directories.
Interrupted copying, publication or source cleanup resumes under the same review
ID; unexpected files, links or changed hashes retain both sides and refuse further
cleanup. Keep the transfer journal and any staging/scratch evidence for recovery.
Same-volume handovers retain the atomic directory rename. Tests cover operation
interruption and disk-full failure; file fsync does not establish directory
metadata or sudden power-loss durability.
This is a trusted-local-user coordination protocol, not an OS security boundary.
Native MT5 lifecycle qualification is still required separately from fixture tests.

### Protect one other running terminal

Use `peer-prepare --terminal-executable <absolute terminal64.exe> --data-root
<absolute MT5 data root>` before setup or switching when another terminal must
remain untouched. Inspect the returned exact paths, PID and creation time; within
the user's authorized setup scope, confirm that exact review using `peer-apply --review-id <id> --confirm-reviewed`.
Preparation and apply do not close, launch, grant control over or write to the peer.

The retained policy verifies its executable hash, origin/data binding and
nonoverlapping paths. It lives outside both parked session directories and
survives a session switch or EA version upgrade on the same installation target.
Onboarding, switch reviews and native package process checks require the exact
recorded peer process. A restart, binary update, changed path or unknown additional
terminal blocks further work; obtain and inspect a fresh review before confirming it.
This is one protected peer, not an arbitrary process ignore list. It does not
release legacy worker claims or startup slots, reconcile native work or substitute
for idle/setup checks on the selected terminal.

### Desktop client during a parked receipt upgrade

The desktop installer may invoke `switch-verify-park`, `switch-replace-receipt`
and `switch-replace-build`
while its requesting `goat.exe desktop suite.installInternalQualification` client
waits for the RPC response. That client is separate from the installer's native
child process; it is not an MT5 runner. Only those parked-installation operations
can recognize one exact launcher/embedded-Python pair from the executing bundle.
The files on disk (executable, entrypoint and controller) must match the bundle's manifest,
arguments must name internal qualification for this same terminal, and the child
must forward the exact arguments. Unrecognized, changed or concurrent clients
remain blocked. Ordinary session review/park/restore still rejects every unrelated
launcher. This recognition grants no account admission, native control or trading
permission and does not retry an interrupted installation. The file hashes do not
attest the running image: process inventory precedes hashing. This is coordination
among trusted local tools, not protection against a same-user actor replacing files.
Portable mode is derived from the installed data/executable paths, including older
receipts without an explicit portable field.

For a corrected build with the same full EA version, `switch-replace-build`
receives a staged candidate EA and receipt, the completed PARK review ID and the
exact old receipt SHA-256. The installer checks fresh own-account admission and
bundle identity before invoking it; the native command grants neither. The
command holds the exclusive session gate and external parked database locks
across verification and both EA/receipt writes. Original bytes, candidate bytes
and the exact publication journal remain in the PARK archive.

On Windows, the PARK verifier reads archived files through extended-length paths
while retaining the original relative names and SHA-256 comparison in the
review receipt. A completed PARK remains the authority if an older verifier
refused a deep archive path: install the corrected controller and retry
`switch-verify-park` or the supported migration with the **same review ID**.
Do not park again, move archived files, clear the fence or create a new session.
Any changed archive byte still blocks verification.

An interruption leaves a durable pending fence outside active session state.
Ordinary controller operations and desktop updates must stop there. After fresh
admission, only explicit reconciliation of the same journal-bound old/new pair
may finish forward; unknown bytes or changed research state remain blocked.
This narrow entrypoint can reconcile before the ordinary receipt hash loader,
which continues to reject a mismatched installed EA. It never launches MT5,
creates a session, grants agent control or resumes research. Source fixture tests
cover these boundaries; native qualification of the packaged command is still
required before claiming a successful installed upgrade.

### Historical UI pointers before orphan recovery

An older UI-created run may leave `active_optimization_run.ini` after every
member finishes. It has no controller owner transaction, so `finish` cannot
claim it. Both host and EA orphan-recovery guards continue to reject it.

With every MT5 terminal, MetaEditor and controller writer stopped, use
`historical-pointers-prepare`, inspect the exact listed historical runs, then
`historical-pointers-apply --review-id <id> --confirm-reviewed`. Only older,
pointer-only Version 1 UI runs with completed/error/cancelled queue members are
eligible. Current-version controls, launch/config/owner files, unknown queue
states, active worker claims and known controller references block retirement.
Unrelated paused pending jobs are preserved. Positively identified Windows
tester services may remain only with no established service connections.

The command locks shared maintenance, selected session and known controller
databases, freezes run contents, backs up exact pointer bytes and moves only
those pointers into a retained Common Files archive. Run folders, results,
queues, session and agent grant remain unchanged. Interrupted operations retain
their fence and must reconcile the same review; never delete it or create a
replacement review. Restart the prepared monitor through supported commands,
then separately review native orphan recovery. This operation never clears
`BatchOnGoing`, launches work or resumes a campaign. Fixture coverage is source
evidence; packaged native qualification remains required.

Before maintenance, every supported app/agent controller entrypoint must use the
same verified controller bundle containing this pending-fence contract. Do not
run a newer external maintenance CLI while the app still spawns an older
controller that cannot recognize its fence. Updating an idle app's reviewed
controller resources does not change the admitted EA binary or installed session.

### Empty chart program names (V1.49 internal -8)

`V1.49-ORPHAN-EMPTY-NAME-8` corrects the chart-name presence checks in orphan
recovery. MQL5 `NULL` and `""` are distinct strings. On September 27, the native
`controller/tests/native/ChartStringProbe.mq5` probe on Banker build 6230 read
its existing GOAT chart: the script query succeeded, returned `NULL`, and had
length zero. The old `script!=""` predicate was true and caused the false
`SCRIPT_PRESENT` refusal. The probe's own chart returned `ChartStringProbe`,
length 16, and was correctly recognized as occupied. Explicit `NULL`, empty,
and named-string cases were also executed. The temporary script performed no
trading, recovery, grant or EA replacement; MT5 exited after completion.

The corrected checks use `StringLen(name)>0` for script and other-chart expert
names. Query failures still refuse recovery, every nonzero-length name still
refuses (including whitespace), and all later runtime guards, reviewed recovery
effects and wire fields are unchanged. The native probe validates the string
and chart-query behavior; source contracts bind the fix to the guard. Neither
is proof that the complete corrected EA has been installed or run a batch.
That native qualification remains required after its exact internal admission.

Reference: https://www.mql5.com/en/book/basis/builtin_types/strings

Compiled candidate: clean source `ead17629e88b6e599da81430426f52845eddd8c9`,
MetaEditor 6230, zero errors and warnings; EX5 SHA-256
`931212a291c6296e46525cd11972cabe9568bcde7f50cf91966cf23cb6c2e449`
(2,256,830 bytes), compile receipt SHA-256
`b0499f6839d3112414f016711c78bb7949379c1a5e42be4d591bc137007639b5`.
The full 391 controller fixtures passed; nine focused source/identity checks
passed again after binding this binary. Corrected-EA native qualification is pending.

## Native directory enumeration correction

Internal `V1.49-ORPHAN-DIRECTORY-9` normalizes the trailing directory separator
returned by native FileFindFirst/Next before joining recovery inventory paths.
Previously the resulting doubled separator caused the sole legitimate native
controller file to fail its exact path check as foreign. File bounds, nested
foreign owners/requests, pending work and Common Files controls still refuse.
The standalone native fixture exercises actual filesystem enumeration and both
accepted and rejected trees; Python source tests alone do not qualify the EA.
Rejection settlement accepts the additional pre-consumption FOREIGN_CONTROL
outcome only with unchanged exact evidence and a fresh clear host inventory.
It never clears a flag or retries recovery; exact human confirmation remains.

Native MT5 build6230 fixture result:27 checks,0 failures, including an actual
trailing-separator enumeration and a held native lock. This qualifies the
isolated inventory functions, not a complete Banker recovery or batch launch.

### Finite owner recovery authority (internal qualification only)

The reviewed `contracts/owner_research_maintenance.json` scope permits only the
named owner's existing demo terminal/session and exact original human grant to
use `--owner-research` instead of `--confirm-reviewed` for
`orphan-recovery-apply` and `orphan-recovery-reconcile-rejection`. This is a
separate authorization route, not a claim that a human confirmed a review.
It requires the original human-channel archive and committed receipt, unchanged
revocation generation, exact account/server/terminal/build pins, fresh matching
native ownership, idle connected demo, Algo Trading off and zero positions/orders.
Pending human control requests block it. Authority is checked under the existing
locks and recorded separately without altering original recovery evidence.

This first slice does not authorize PARK, install, migration, bootstrap, grant
creation or trading. Other accounts, replacement grants and changed sessions are
refused. Ordinary explicit-review behavior is unchanged. It is not customer
standing consent, and it is not native qualification. Subsequent maintenance
continuity requires a separate reviewed change; never copy grants or submit a
human command on the user's behalf. Machine review expiry, exact consumption,
foreign-control guards and uncertain-outcome reconciliation remain enforced.

### Owner-internal maintenance record (2026-09-27)

`owner-maintenance-prepare` is limited to the committed Banker demo policy. It
verifies the original genuine human grant, current native idle demo, Algo OFF,
zero positions/orders, empty unstarted research and no native controls. It mints
one four-hour record bound to the original account/terminal/session/epoch, exact
corrective9 SHA, frozen batch-plan SHA, a planned replacement session and nonce.
The record references the grant; it does not copy it or manufacture confirmation.

After the supported `monitor-stop` proves the same observed terminal exited,
`switch-apply --review-id <id> --owner-maintenance <record-id>` can authorize only
that exact PARK. The normal stopped-writer, exclusive-lock, inventory, database,
archive and crash-reconciliation guards remain. A takeover, pending human event,
changed research, expired record, different review after consumption or uncertain
identity refuses. Human revocation permanently retires the chain. Repeated use of
the same completed identity only reads/verifies completion; it never repeats an
effect. Original grant evidence and research remain in the verified PARK archive.

This slice does **not** authorize installation, bootstrap, a replacement-session
grant or research dispatch. Those require the separately reviewed continuation
implementation. Ordinary `--confirm-reviewed` remains a distinct explicit human
route. This finite owner policy is not customer standing consent.

### Owner-internal restricted research continuation

After owner maintenance PARK, `owner-maintenance-install-prepare --record-id <id>`
freezes the exact input for the existing authenticated desktop internal installer.
The installer still verifies the server admission and uses its normal byte/CAS
upgrade journal. `owner-maintenance-bootstrap --record-id <id> --plan <frozen.json>`
independently verifies that completed target build, the original grant/archive and
stop evidence, unchanged terminal/account and saved Algo OFF. It publishes only the
record's pre-bound replacement session while native writers are stopped.

The replacement has immutable `research_continuation` authority, not a copied or
synthetic human grant. The existing native `owner=agent` field remains a research
transport identity. A central CLI dispatcher and command-store boundary default to
refusing unlisted operations, including future operations. Only the frozen plan,
member settings and resulting configuration may be prepared and dispatched. Missing
or unknown authority on an agent-owned session refuses rather than becoming full
control. New normal sessions are explicitly classified `native_human_control` and
remain human-owned until an actual human grant. Legacy classification requires no
typed authority markers and an actor-bound archived human grant matching its
committed receipt and generation. Genuine new human grants classify atomically;
missing evidence never classifies an agent. SQLite insert/update/delete guards
and independent session/file checks prevent authority downgrade.

A human takeover permanently revokes the continuation; no subsequent grant/promotion
is available through it. The human channel can always submit a validated takeover,
even when authority evidence is damaged. Human cancellation and reviewed PARK/restore
remain available after takeover. Typed recovery refuses human-confirmation flags.
An expired continuation can supervise/cancel/finish its retained batch, but cannot
reserve or dispatch new work. Native dispatch rechecks the broker-confirmed demo, account,
Algo OFF, empty positions/orders and idle tester. Recovery has its own distinct typed
authorization and keeps every native recovery guard. Bootstrap starts no terminal,
batch or trade. Use the supported monitor prepare/launch, verify actual native
recovery, then prepare/start the frozen batch. Unknown or interrupted identities
remain fenced. A completed maintenance record is retired and cannot mint another
session; its journals and original grant evidence remain available for inspection.

Validation is source/fixture coverage until an actual native result is recorded;
these owner-only paths are not a customer rollout or general standing consent.

Fresh agent batch snapshots project complete tester/export settings from the hash-verified queued configuration when both editor drafts are absent. This fills the existing native display fields without inventing defaults, editing stored human drafts, changing native protocol fields, granting control or replaying a launch. Partial editor drafts remain visibly incomplete.

### Rejected owner-demo monitor recovery

`research-monitor-restart --job-id <id>` is a one-shot recovery for the typed owner research continuation when an expired start has an exact native pre-consumption `REQUEST_REJECTED`, no consumed start exists, and the frozen native queue has no work outputs or checkpoints. It journals a graceful Ctrl+C of only the identified old controller console, verifies exit and lock release without changing its budget, then normally closes and relaunches the exact idle demo monitor using its retained monitor-only config. It keeps the draft, session, authority and every native receipt. Algo OFF, zero positions/orders and the same account/process are checked through the SDK before close and after restart. An uncertain close or launch is never repeated. `research-monitor-restart-status` can only reverify an already launched process.

If the original stop expired while the monitor was blocked, `cancel-rejected-successor --job-id <id>` requires its native, expired, unconsumed `CANCEL_REJECTED` plus the reverified recovery before publishing one new stop identity. Both old receipts remain immutable; observations and finish bind explicitly to the successor. A second successor refuses. Source tests do not establish native recovery; verify native `CANCELLED_RECONCILE`, every member cancelled and idle before finish. This does not authorize another research start.

A typed owner continuation may prepare one replacement batch only after its original start has an exact unconsumed pre-start rejection, its cancellation has a consumed `CANCELLED_RECONCILE`, every native member is cancelled, canonical finish restored the controls, no work output exists and its original supervisor journal is stopped. Every original job and receipt stays retained. The replacement must have the same frozen plan, members and configuration; a second replacement refuses. `run-batch` inherits the original start/deadline/budget and at least its disk reserve, even if a caller supplies a new full duration. Only the live run-batch operation with its initial start intent may dispatch either original or replacement typed research; a retained failed journal never authorizes direct start. A suspended original supervisor remains stopped=false: finish its native cancellation using run-batch --resume before preparing the replacement. Preparation, reservation and dispatch recheck the predecessor; no uncertain start is retried.
If Windows loses an exiting MT5 process's executable metadata after the normal close was issued, preserve the `close_issued` record. `research-monitor-restart-resume --job-id <id>` verifies that the original publisher remains suspended with the same journal, positively observes terminal absence, and performs only that record's never-issued first monitor relaunch. It never resends close and refuses any record whose launch has already been issued. The saved config/profile/preset, protected session/authority/draft hashes and post-launch SDK checks remain mandatory. This is recovery of the same attempt, not another restart.
Before close and the first relaunch, recovery inventories every goat/python process and refuses any other publisher referencing this installation/root. Only the current recovery caller and its own exact launcher are excluded. Resume also preserves the active-seed exclusion. A changed retained draft remains a refusal requiring inspection; it is never rewritten automatically.

Concurrent CLI and resident bridge pumps wait up to one second to acquire the exclusive worker lock. This waits before processing requests, never retries a mutation, and still refuses persistent contention.

For a saved-profile permission refusal after a recorded owner-demo stop, `research-monitor-reopen-prepare --job-id <original>` audits before/after common.ini bytes and changes only Charts/ProfileLast to the existing typed-session profile while MT5 is stopped. Saved account and terminal-wide Algo OFF remain mandatory. It never launches MT5 or changes permissions. The user opens Banker normally; only after the user actually confirms that action may `research-monitor-adopt-reopen --job-id <original> --human-reopened` observe the exact newer terminal once. It verifies unchanged protected files and chart/config bytes, current native session and SDK demo/Algo OFF/zero trades/idle. Undocumented chart flag bits remain opaque; only this observation of an already human-opened monitor accepts them, never onboarding or automated launch. An interrupted adopted_unverified record can use research-monitor-restart-status to reverify that same PID; it never adopts a second process. Original cancellation and finish still must complete before the frozen replacement can run.

For the proven generated-report editor discrepancy on that retained recovery,
`research-monitor-repair-derived-report --job-id <original>` owns the normal
close, stopped draft repair and monitor reopen. It needs no new human reopen or
grant. It accepts only an unsubmitted retained draft whose sole difference from
its baseline is the legacy report root becoming the exact package-owned scoped
root. It archives both versions and the original restart, then changes only the
baseline while the editor is stopped. The EA must subsequently acknowledge the
real controller revision; the controller never writes a native revision.

The transaction preserves the saved expert's exact `expertmode` row and all
bytes of the common.ini Experts section. It compares these before close, after
close and after launch; a difference refuses launch or acknowledgement. Opaque
bits are preserved, not interpreted as grants. Structural checks still require
the same inert EA, exact preset/config, same demo, Algo OFF, no trades and idle
tester. The newly launched PID/creation/executable comes from the controller's
own one-shot launch record, with fresh native feedback; Explorer or a fabricated
human witness is never used. Resume reconciles known file/publication phases;
an uncertain issued close/start is not repeated. Completion links the archived
repair into the original recovery before its cancellation can continue.

Adoption also records the original Explorer parent, its earlier creation time, the same active console session, and the exact executable command line (only the required `/portable` flag is allowed). Native feedback must have been written after this process started, both at adoption and re-verification. This evidence corroborates the user's actual reopen; it cannot substitute for that confirmation. Interrupted pointer publication can resume the exact retained before/after compare-and-swap while the terminal remains stopped, including an identical staged temporary file or already-published after bytes. The audit and its original time stay unchanged; any different bytes refuse. CR, LF and CRLF endings are preserved.

New pointer receipts retain their complete original bytes in an exclusive publication-intent file before the receipt copy is written. Resumption compares every receipt byte against that intent, including its timestamp and permission/launch declarations. An interrupted receipt copy uses the original intent without resetting its time. Earlier completed schema-1 receipts remain observable through the existing adoption checks, but cannot resume pointer publication without original intent evidence; never manufacture that evidence retroactively.

The human-launch checks are corroboration, not proof against a deliberate agent using the same Windows user token. Never substitute a scheduled task, shell handoff or other synthetic launch for the user's actual action. The current check requires the active physical-console session and refuses RDP sessions, different-case portable flags and short-path aliases. Initial adoption requires the original Explorer parent to be present. Re-verification retains that original evidence if Explorer exits, while rechecking the exact live target's identity, session and command line against it and the active console. It never substitutes a new parent or adopts a second process. No account or IAM changes are authorized by this workflow.

Both adoption and re-verification also require the message's native observed_terminal_utc to be at least the process creation time minus one second, allowing its whole-second timestamp precision. A fresh file modification time cannot make an observation from the previous process acceptable. Existing runtime age, account, path, idle and Algo OFF checks still apply.

The bounded driver accepts up to172800seconds (48hours). Existing resume never resets a deadline. This limit grants no control and does not extend a typed scope; a fresh window after takeover requires a genuine new native grant and supported renewal.

## Optimization model standard

Use **1 minute OHLC (`Model=1`) for new optimization plans** unless the user explicitly requests another model. The Studio editor already selects OHLC for a fresh draft. Saved drafts and immutable jobs retain their explicit model; revise them into a new batch when the user changes the model. Keep export/replay model settings separate from the optimization model. Agent and human views show the model and each member of the active batch, including completed, failed, cancelled and remaining counts. These are native observations, not export qualification.

### Stop when the selected MT5 has exited

`demo_agent.py --installation <receipt> stop --monitor-config <existing-monitor-only.ini>` may reopen the exact previously verified demo monitor solely to consume an owned cancellation. It retains STOP, verifies genuine retained ownership and exact binary/preset, refuses a live supervisor, validates the existing attempt and publishes cancel before launch. The INI must contain no Tester section and must keep Algo Trading off. It never creates a grant or starts research. Expired, consumed, foreign or refused cancellation evidence is not replayed. Success still requires the normal broker/native finish readback; monitor launch alone is not a confirmed stop.

### Report-capable first-member startup

The direct-demo bounded driver prepares a new package with the selected passive monitor profile and starts its first member through /config. This applies configuration-only Report settings that an in-place tester Start click cannot establish. It reuses the actual grant and the existing deadline. Native arming, close issuance, confirmed exit and launch issuance are retained separately; interrupted starts are never replayed. The exact native attempt is saved before any close so the normal stop/reconcile tools can recover it.

MT5 resolves configured reports relative to its installation while GOAT reads its local data sandbox. A fresh, audited per-run junction connects only those owned report locations when they differ. Existing output directories or links are not overwritten. Paths and startup bytes are rechecked before launch. Older prepared packages remain unchanged and must be copied into a new preparation for this route. Native report pair/export completion must qualify the installed build; source tests and process launch do not establish that result.

### Direct demo stale-flag repair

`demo_agent.py --installation <receipt> recover-orphan` performs one bounded repair of an idle native `BatchOnGoing` flag. It requires the exact existing paired demo account and server, current agent ownership with its archived genuine grant, fresh broker proof, Algo Trading OFF, zero positions/orders, no active driver/worker, and every existing orphan protocol check. The broker's demo flag is authoritative; an account switch, live account or masked account ID refuses. The former Banker account constant is no longer a restriction.

An existing native human-control session can use this recovery without replacing its session, binary or grant. This narrowly scoped adapter entry cannot reserve or start research. It retains the before-state and exact native request, then waits up to 15 seconds for receipt plus readback. No human-confirmation flag or new grant is generated.

### Recover a rejected, never-started customer attempt

Before replacing EA bytes, an authorized local updater can invoke
`goat.exe studio --installation <current-receipt> self-repair --job-id <retained-job> --action-id <stable-uuid> --linked-login <full-own-linked-login>`.
The app verifies that login belongs to its signed-in user. The controller then requires the same exact login/server from the official native adapter, DEMO, Algo Trading OFF, idle tester and no positions/orders. The old session opens only through its unique preserved same-EA receipt, with a forward metadata-only beta update. Live, changed binaries/paths, human ownership/STOP/TAKE, low disk, another publisher/operation and uncertain execution refuse.

The command republishes actual ledger settings so the EA can observe the existing expired transport. It never resends or extends that transport. Settlement additionally requires both exact native pre-consumption start/cancel rejections, no consumed/start/arm marker, unarmed activation, byte-exact staged native queue/inputs, no reports or tester cache and unchanged owned controls. After normal close, it checks the same proof again, archives the exact request/permit and restores the original controls. The job becomes a local `failed` / `retired_never_started` result with zero executed members and `native_cancellation_claimed:false`. Original configurations, native queue, issuance, rejections, grant and human latch remain retained.

Success leaves MT5 stopped for the updater's separately verified inert-monitor reopen. It starts no research or trading and does not claim native qualification. The updater must not automatically resume the retired attempt. The preserved research stop may require the human to press Start once in GOAT Studio. An uncertain close or partial restoration resumes only its recorded phase and never sends a second close.

Stdout returns `{ok,result}`. Only `result.repair` is the sanitized server repair payload; `local_reason` and the surrounding machine/account evidence must never be sent to support. Use `result.report_action_id` with the own-ticket `support.appendRepair` RPC and the current report revision. It is stable for an identical outcome; a changed interrupted-repair outcome has a new report identity. `result.action_id` remains the local repair journal identity. Fixture tests establish the recovery transitions and refusals, not native customer qualification.

A config restart-arm start the EA refused before consuming it settles through the same command and the same close, restore and settle steps. An example is `START_PROTOCOL_NOT_QUALIFIED` from an older build gate, which the driver records as `start_uncertain`. Here the proof is the EA's own receipt for that exact `arm_restart` request. It must be one of the refusals `GOATStudioDispatch.mqh` returns only before it writes `consumed-<id>` or touches the tester: `START_PROTOCOL_NOT_QUALIFIED`, `RESTART_INTENT_REJECTED`, `INVALID_TESTER_INI` or `ACTION_REJECTED`. `HUMAN_CANCEL_RETAINED` is excluded because the EA also returns it after consumption, and a retained human cancel stays the human's. `NATIVE_CONTROL_DRIFT` is excluded because it contradicts the byte-exact control proof. All of the following must also hold:
- no consumed file or arm intent exists;
- the request has expired, and `request.json` is byte-exact;
- an issued cancel, if any, is rejected or expired and unconsumed;
- the restart controls are unchanged and owned;
- the staged native queue and run folders are untouched, with no reports or tester cache.

Settlement also retires that run's own report junction through its journaled receipt. The support summary says in plain words that the refused start never ran and that any stop the tester set is still in place. Settlement never clears a STOP, TAKE, human cancel or latch, and never grants a new run. A success or unknown receipt, any consumption or any drift refuses, with nothing changed.

For the reported `ORPHAN_REVIEW_REJECTED`, `consumed=false` case, the same command settles only the exact expired, unconsumed rejection after fresh checks, preserves its request/result archive, and prepares one new recovery identity. A retained link prevents automatic successor chains. Consumed, uncertain or other refusals remain fenced and are never resent. `--review-id` always observes only. Native customer qualification and installer delivery remain separate from these source/fixture checks.

## Windows supervisor lifetime

The candidate Windows demo launcher hosts its bounded supervisor in a
windowless, demand-only task for the current interactive user. It does not
add a recurring trigger, store a Windows password or enable trading. The
native driver still proves the selected demo account and honors human STOP,
disk, ownership and its original deadline. Task execution allowance includes
shutdown grace; it never renews the research window.

A registration timeout or missing bootstrap receipt preserves the launch
envelope and refuses a second launch or ordinary process fallback. Inspect
that exact task/nonce before recovery. Start/completion receipts prove only
the supervisor process; obtain fresh MT5 and batch evidence before reporting
that optimization is running. Final customer rehearsal is still pending.