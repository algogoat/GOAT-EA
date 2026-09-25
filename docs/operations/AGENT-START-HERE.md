# GOAT agent operations

Start here for terminal setup, portfolio loading and dashboard control. Use the
controller/CLI for operations; use a screenshot only to inspect the finished UI
when requested. A missing controller operation is an implementation gap, not a
reason to quietly substitute repeated mouse clicks.

## Choose the task

These instructions apply to the current user's installation. Discover installed
tools and paths locally; private skills and internal research files are optional
references, not prerequisites. Use current capabilities and the user's chosen
settings. See the [unified setup proposal](GOAT-SETUP-BUNDLE.md) for the planned
EA, controller, optimization files and matrix distribution.

| Goal | Entry point | What it proves |
|---|---|---|
| Compile an EA | `mt5-goat-compile` skill | Source, compiler, output hash and clean compile log |
| Connect an owned inert demo | `scripts/goat_demo_connection.py --help` and [connection contract](DEMO-CONNECTION.md) | Process/hash preflight, one login attempt, exact native account readback; login and encrypted-provider reconnection verified on the local preview host |
| Inspect installed setup evidence | `scripts/goat_setup_status.py --help` | Saved observations and optional disk hash; not live readiness |
| Native terminal status, pairing, orderly shutdown | `scripts/goat_setup_control.py --help` | Scoped request and matching native receipt |
| Configure and attach a frozen portfolio | `scripts/goat_portfolio_setup.py --help` | Per-operation native receipts, then full input audit |
| Install/connect/persist a demo on VPS | `goat-vps-setup` skill and its portfolio reference | Host-specific setup procedure; still requires current runtime proof |
| Inspect active trading/exposure | `goat-vps-trade-audit` skill | Observed positions, deals, inputs and effective policies |
| Create or benchmark optimization inputs | `goat-opt-file-create`, `goat-seed-farming` | File integrity, bounded tests and scoped post-run cleanup |
| Operate Optimization Studio settings, queue and controller | [Studio controller guide](OPTIMIZATION-STUDIO-CONTROLLER.md) | Local/managed controls, exact research command schema, persistence, ownership, receipts, recovery and explicit V1.48 capability gaps |
| Inspect current machine and completed pilot cost | Installed `goat.exe studio --installation <receipt>` with `resource-profile` and `benchmark-report --batch-id <completed-id>`; [command contract](../../controller/README.md#measure-a-pilot-before-committing-a-research-budget) | Current CPU/RAM/filesystem facts and exact completed batch/report/timeline observations; no throughput prediction, native worker count or launch |
| Launch an optimization | `mt5-goat-optimize` and the campaign's current continuation | Exact retained queue, controller ownership, native results |
| Operate the Electron portfolio builder | Its authenticated local agent API and repo operating docs | Saved pool/job/portfolio IDs and exports; no screen dependency |

The skill names above are discovery routes, not an assumption that every host
has them installed. The native clients in this repository are available locally.
Run them on the terminal host; for VPS installations use the authorized SSH
connection. Do not copy a previous campaign's host paths, PIDs or account count.

Read [the native controller runbook](NATIVE-CONTROLLER-RUNBOOK.md) before issuing
commands. Read [the V1.48 verification notes](V1.48-DASHBOARD-VERIFICATION.md) for
the current dashboard change and its unfinished verification.

## Agree a measured research budget

Before a large optimization, run `resource-profile` and discuss the user's
wall-clock window and available disk space. CPU specifications do not establish
MT5 worker availability or optimization speed. Prepare a small representative
pilot with `prepare-batch` (even for one member), run it through the normal
explicit start/finish workflow, then inspect `benchmark-report --batch-id`.
Match exact assets, timeframes, dates, models, forward settings, input axes and
exports. Retain the batch ID and returned evidence hashes. Missing or ambiguous
timing remains unknown; do not substitute guessed genetic pass counts or a
universal timeframe multiplier. These inspection commands neither consume human
control requests nor start, finish or reconcile work.

Use comparable completed pilots to present a provisional scenario table with
sample count, observed range, unmeasured groups and storage/restart uncertainty.
Current machine facts do not prove past worker/cache/load conditions. Agree the
next batch scope with the user before committing its budget. Larger diverse,
independently validated pools can offer more portfolio choices; merely adding
correlated or overfit candidates does not demonstrate improvement. Explain the
tradeoff between research cost, useful diversity and validation quality.

## First five observations

1. Read the user's current request and installed tool capabilities. For an
   explicitly resumed run, read its selected manifest and any continuation or
   pause note. A new installation needs no research `CONTINUE.md`.
2. Resolve the exact executable, data directory, Common Files directory, account,
   server, build ID, EX5 hash and process creation time. A terminal nickname is
   not a sufficient identity.
3. Read active requests, receipts, producer ownership and expiry. Do not create
   another request while an earlier mutation has an unresolved outcome.
4. Check current native account, connection, trading state and position/order
   counts. Do not treat a stale JSON file or open window as a current observation.
5. State the intended outcome: **preview**, **attached but inert**, or **trading**.
   These are different states and need different evidence.

## What a new agent should be told

> Use the GOAT agent operating guide and the selected run's latest continuation.
> Inspect existing process/controller state first. Load the specified frozen
> portfolio into the named local demo terminal with trading disabled. Operate
> through native controllers and CLI; use the screen only for final visual QA.
> Verify the actual account, build, membership and effective settings. Preserve
> unrelated terminals and active positions. Report the exact achieved state and
> any failed or unsupported stage; do not deploy or enable trading implicitly.

Replace the named portfolio/terminal with a specific manifest or immutable ID.
This prompt is an operating objective, not a claim that fresh installation,
broker login, activation and portfolio import are already one atomic command.

## Improvement rule

After a real operating failure, improve the smallest relevant tool or reference.
Record the symptom, diagnosis/evidence, recovery, scope and verified result. Keep
host-specific receipts/logs outside Git. Keep portable command contracts and
failure rules in the repo and link them from the relevant skill. Label proposed
commands explicitly; never document a planned command as available.
