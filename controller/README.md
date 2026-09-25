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

## Commands and effects

| Command | Required options | Effect |
|---|---|---|
| `discover` | None | Read-only installation/hash/schema/capability inspection |
| `bootstrap` | `--account-login`, `--account-server` | Create local human-owned binding and monitor preset; never launch |
| `serve` | Optional `--watch-seconds` | Process Studio inboxes; default 3600, range 0–3600; zero is one cycle |
| `state` | None | Process pending UI commands then return drafts/queue/ownership |
| `submit` | `--request` JSON file | Submit exact versioned agent command envelope; no actor override |
| `prepare` | `--job-id`, `--set`, `--configuration` | Freeze complete inputs, queue job and stage immutable native package |
| `start` | `--job-id` | Recheck demo/runtime/binary/ownership, reserve, activate and publish one start |
| `status` / `reconcile` | `--job-id` | Inspect retained native attempt, dispatch, runtime and report evidence |
| `cancel` | `--job-id` | Cancel pending job or publish owned native stop; reconcile before claiming stopped |
| `finish` | `--job-id` | Confirm terminal idle and terminal queue outcome, retain result, restore owned controls |

`start` supports the **first pending** job only. The beta uses local genetic
optimization (`Optimization=2`, criterion 6), a custom forward date (`ForwardMode=4`),
nonvisual testing, local workers enabled and remote/cloud workers disabled.
Only the chosen MT5 executable may be running for native activation. If another
terminal is open, stop here and let the user close it normally; do not kill it.
The controller does not install a service, restart MT5 or auto-start the next job.
It supports one frozen job per native package and serial explicit starts.

## Configuration

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
