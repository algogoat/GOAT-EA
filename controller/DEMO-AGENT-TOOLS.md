# Demo MT5 agent tools

`demo_agent.py` is the demo-account tool entry point. It operates one selected
MT5 installation from its existing `installation.json`. It never sends trades
or turns on Algo Trading. Its Studio calls control the EA's existing
`Mode_Operation=11` Studio queue and `Mode_Operation=9` Optimizer/MTTester;
there is no second tester or portfolio engine.

The first lane is intentionally bound to the Banker demo login `3000082754`
and the installation's exact server and data folder. Mutations require a fresh
broker-reported `ACCOUNT_TRADE_MODE_DEMO`, the selected process, an idle native
tester, Algo Trading off, at least 5 GiB free on every output volume, and no
owner STOP or pending human TAKE. A real-account report always refuses. The
`demo-agent/actions.jsonl` file only appends intent and readback events. Each
command prints one JSON object; errors include a `code` and message.

Use the Python runtime bundled with a GOAT suite. Replace `python.exe`,
`installation.json`, the candidate EX5, and the plan paths with the selected
installation's absolute paths. These examples are PowerShell commands:

```powershell
$py = 'C:/path/to/goat-suite/python/python.exe'
$tool = 'C:/path/to/goat-suite/controller/demo_agent.py'
$install = 'C:/path/to/GOAT Portfolio Desktop/suite/selected/installation.json'
& $py $tool --installation $install status
& $py $tool --installation $install disk-status
& $py $tool --installation $install preflight
```

`status` reads process, broker account, binary hash, EA owner feedback with its
age, and retained batch driver journals. A journal alone does not prove the
native tester is running.
`disk-status` reads free bytes and the 5 GiB reserve. `preflight` positively
checks demo/owner/tester/space without changing MT5. It reports separate
`ready_for_install` and `ready_for_batch` flags; an old installation can be
safe to update while still unable to start the batch.

```powershell
& $py $tool --installation $install install-build `
  --candidate 'C:/reviewed-build/GOAT V1.49.ex5' `
  --sha256 '<64 lowercase hex characters>' `
  --monitor-config 'C:/existing-state/monitor-launches/exact-monitor.ini'
```

`install-build` verifies the candidate hash and inert monitor profile, archives
the old EX5 and local identity files, normally closes only the selected idle
demo terminal, copies the EX5, relaunches its existing monitor and reads back
the physical hash, connected demo account, EA feedback and Algo-off state.
The restart INI accepts only the retained Charts/Experts/StartUp monitor keys;
account, tester, script and other directives are refused before MT5 closes.
It keeps the old research proof as history. A retry with the same installed
hash returns `already_installed` only with readback from that exact process.
A 120-second readback allows normal broker and EA startup time. If MT5 exits
after a swap, retrying `install-build` with the same candidate and hash brings
back the exact inert monitor. If it exited before the swap, the retry first
recovers the registered old build, then performs the install. An uncertain
relaunch remains explicit and never dispatches a batch.

```powershell
& $py $tool --installation $install launch-terminal `
  --monitor-config 'C:/existing-state/monitor-launches/exact-monitor.ini'
```

`launch-terminal` recovers a stopped registered demo terminal using its prior
EA/agent ownership evidence and exact monitor config. It requires fresh broker,
Algo-off, idle tester and EA feedback after startup. It cannot start a real
account or an unregistered binary.

```powershell
& $py $tool --installation $install prepare-batch `
  --batch-id 'new-unique-batch-id' --plan 'C:/frozen-plan.json'
& $py $tool --installation $install run-batch `
  --batch-id 'new-unique-batch-id' --max-seconds 172800
& $py $tool --installation $install resume-batch `
  --batch-id 'new-unique-batch-id'
& $py $tool --installation $install batch-status --batch-id 'new-unique-batch-id'
& $py $tool --installation $install batch-driver-status --batch-id 'new-unique-batch-id'
& $py $tool --installation $install stop
& $py $tool --installation $install clear-stop
```

`prepare-batch` uses Studio's native batch preparation and verifies the queued
member count. `run-batch` starts a detached Windows worker and returns when its
durable journal appears, without claiming native work is running. The worker
uses the existing bounded Studio driver for up to 48 hours. `resume-batch`
attaches a new detached worker to the retained attempt and original deadline;
it never starts a pending job. Repeating `run-batch` returns the original
worker/journal status and never resets the deadline. `batch-status` reads the
EA's member state; `batch-driver-status` reads the retained driver journal.
`stop` writes the owner STOP marker even while a worker holds the lock. It
waits for the exact cancellation readback; if the worker died, it resumes the
retained journal and requests cancellation through the existing EA path.
It returns `cancelled`, another verified terminal result, or `stop_unconfirmed`,
never an unverified “requested” success. `clear-stop` removes only a STOP marker
written by this tool after a verified idle demo and terminal batch state. A
human TAKE also prevents further agent dispatch. Treat `start_uncertain` or
`stop_unconfirmed` as needing native inspection, not as completion.

## Seed Farming on the demo lane

On a `demo_direct` installation the raw `goat.exe studio seed-*` mutations
refuse with `Demo mutation requires the broker-verified agent tool`. Use these
tools instead. They drive the same `SeedRunner` and the same frozen plan format
as [SEED-WORKFLOW.md](SEED-WORKFLOW.md); nothing about seed evidence changes.

```powershell
& $py $tool --installation $install seed-validate --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-prepare --batch-id 'seed-weekend-01' --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-start --batch-id 'seed-weekend-01' --max-seconds 600
& $py $tool --installation $install seed-resume --batch-id 'seed-weekend-01' --max-seconds 600
& $py $tool --installation $install seed-status --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-cancel --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-report --batch-id 'seed-weekend-01'
```

`seed-validate` checks the whole plan and every SET it names (tester rules,
frame target, exact axis precision, duplicates, size limits) and writes nothing:
no SET, startup INI or seed folder, and no terminal, process or broker access.
Only the validation itself is appended to `actions.jsonl`.

`seed-prepare` and `seed-start` need the same fresh checks as batches: the
terminal lock, a broker-reported demo account on the exact paired login and
server, Algo Trading off, an idle tester, no open positions or orders on a
trade-capable account, no owner STOP or pending human TAKE, 5 GiB free on every
volume, and the registered EA with its native readback. They also refuse while
any ordinary native batch is active or a live batch worker exists. While a seed
run owns the terminal, ordinary batches stay blocked by `seed-active.json`.

`seed-start` writes `demo-agent/seed-starts/<batch-id>.json` once, before any
effect: the manifest hash, generation, paired account and the broker readback.
A second `seed-start` for a started batch refuses; continue with `seed-resume`.
A seed run closes the selected MT5 and relaunches it per member, so between
members no live broker can answer. `seed-resume`, `seed-status`,
`seed-cancel` and `seed-report` then continue only that original attempt, and
only when its start record matches this installation, the registered EA and the
exact paired demo account. When MT5 is running they take a fresh broker readback
instead. Completed or attempted members are never retried. A batch that is still
`prepared` has had no native effect: `seed-status`, `seed-cancel` and
`seed-report` work on it with a fresh broker readback while MT5 runs. They keep
working after it is cancelled before any start, and a repeated cancel is
idempotent, but only while the retained files prove no native effect ever
happened: no start record, slot, generation, process, attempt, result or seed
output. Anything else without a start record refuses.

Start and resume drive in short slices of a few seconds within `--max-seconds`
(1..3600, default 60). Before every slice they check owner STOP, a pending human
TAKE and free disk. If any appears, they request a normal close of the exact
owned member, cancel the pending members and return `stopped_by` with the
reason. `stop` also settles a seed run that no command is currently driving.

Nothing supervises a member between commands. After `driver_budget_exhausted`,
the member's job timeout, a human TAKE and the disk check are only acted on by
the next `seed-resume`. `--max-seconds` is the budget for that one call, not an
autonomous hard stop, and no background service enforces anything between calls.
Owner STOP is a separate explicit path: `stop` works at any time. Keep calling
`seed-resume` until the batch reports `completed` or `stopped`, or holds
`reconcile_required` for inspection.
STOP is never cleared by these tools, and `clear-stop` refuses until the seed
run has reached a verified terminal state. Real native qualification of this
lane is still pending; every seed result keeps `native_launch_qualified: false`.

This is the first Tier A slice. Terminal discovery, compile, SET editing,
report parsing and exports will be separate tools wrapping existing MT5/EA
features. Native smoke evidence is required before calling this lane qualified.
