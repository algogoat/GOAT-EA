# GOAT Studio controller 1.48 beta

This portable Windows controller uses the installed receipt and bundled Python.
Only `goat_studio.py` is the public Studio entrypoint. The other Python modules
implement its validation and durable storage; do not invoke internal helpers or
construct native permits manually. No API accepts a caller-supplied “safe” flag.

In the unified agent kit, prefix each command below with:

```powershell
& '<agent kit>\goat.exe' studio --installation '<Setup receipt.json>'
```

The standalone equivalent is `python.exe controller\goat_studio.py` followed by
the same arguments, using the bundled runtime rather than a system Python.

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
`monitor-launch` uses MT5 `/profile`, with `/portable` only when the installation
receipt identifies portable mode; it does not use a disposable `/config` startup
chart. The saved broker login/server must match the controller binding, saved
Algo Trading must be off, and nonportable installations must have matching
`origin.txt`. All terminal processes must be stopped for this conservative beta
setup path. No command closes a terminal or enables trading.

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
MT5 metadata changes and the human's DLL approval can persist; chart trading
permission remains disallowed. A launch error or crash retains `launch_intent`
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
| Human owns state | User saves/reloads then clicks Give to Agent; never forge a human command |
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
