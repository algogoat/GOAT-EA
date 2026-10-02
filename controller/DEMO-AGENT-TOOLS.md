# Demo agent tools (owner and maintainer lane)

**Customers and their agents: do not use these tools.** Follow [AGENT-START-HERE.md](AGENT-START-HERE.md) (`goat.exe studio ...`) and [GOAT-OPERATING-MODEL.md](GOAT-OPERATING-MODEL.md). This lane exists for GOAT's own demo research and for reviewed build installs; its commands refuse to drive Studio until `install-build` has converted the selected session to this lane.

`demo_agent.py` (installed as `goat.exe demo --installation <receipt> <command>`) operates one selected MT5 installation from its existing `installation.json`. It never sends trades or turns on Algo Trading. It drives the EA's existing Studio queue and optimizer; there is no second tester or portfolio engine.

The account is the demo login and server already paired in that installation's controller session (from `bootstrap`); there is no built-in account. Every command that can change the terminal or its files requires a fresh broker-reported demo account matching that pairing, the selected process, Algo Trading off, an idle native tester, at least 5 GiB free on the terminal-data, Common Files and controller-state volumes, and no owner STOP or pending human TAKE CONTROL. A real account always refuses. `demo-agent/actions.jsonl` records intent and readback events.

Output: success prints `{"ok":true,"result":...}` to stdout (exit 0). Errors print `{"ok":false,"code":"REFUSED"|"IO_ERROR"|"INTERNAL_ERROR","error":"..."}` to stderr (exit 1). `stop` that cannot confirm the stop prints `code: STOP_UNCONFIRMED` (exit 2).

```powershell
& $goat demo --installation $receipt status          # process, broker, EA hash, owner feedback age, driver journals
& $goat demo --installation $receipt disk-status     # free bytes against the 5 GiB reserve
& $goat demo --installation $receipt preflight       # read-only; reports ready_for_install and ready_for_batch
& $goat demo --installation $receipt install-build --candidate '<reviewed .ex5>' --sha256 '<64 hex>' --monitor-config '<existing monitor-only .ini>'
& $goat demo --installation $receipt launch-terminal --monitor-config '<existing monitor-only .ini>'
& $goat demo --installation $receipt prepare-batch --batch-id '<new id>' --plan '<plan.json>'
& $goat demo --installation $receipt run-batch --batch-id '<id>' --max-seconds 172800
& $goat demo --installation $receipt resume-batch --batch-id '<id>'
& $goat demo --installation $receipt batch-status --batch-id '<id>'
& $goat demo --installation $receipt batch-driver-status --batch-id '<id>'
& $goat demo --installation $receipt stop            # optional: --monitor-config '<monitor-only .ini>'
& $goat demo --installation $receipt clear-stop
& $goat demo --installation $receipt recover-orphan  # optional: --review-id '<id>' to observe only
```

- `install-build` verifies the candidate hash and the inert monitor INI (only Charts/Experts/StartUp monitor keys; account, tester and script directives refuse before MT5 closes), archives the old EX5 and identity files, closes only the selected idle demo terminal, copies the EX5, relaunches its monitor and reads back the physical hash, demo account, EA feedback and Algo-off state within 120 seconds. Repeating it with the same candidate and hash returns `already_installed` or completes an interrupted swap; an uncertain relaunch never dispatches a batch.
- `launch-terminal` reopens a stopped registered demo terminal with its exact monitor INI and requires fresh broker, Algo-off, idle-tester and EA feedback afterwards.
- `run-batch` (`--max-seconds` required, 1..172800) starts a detached Windows worker and returns when its journal exists; that is not proof that native work runs. Repeating it returns the original worker and never resets the deadline. `resume-batch` attaches a new worker to the retained attempt and original deadline and never starts a pending job.
- `stop` writes the owner STOP marker and waits for the exact cancellation readback; it returns `cancelled`, another verified terminal result or `stop_unconfirmed`. `clear-stop` removes only a STOP written by this tool, after a verified idle demo and a terminal batch state.
- Treat `start_uncertain` or `stop_unconfirmed` as "inspect the native state", never as completion.

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
& $py $tool --installation $install seed-promote --batch-id 'seed-weekend-01' --candidate '<candidate_sha256>' --name 'My EURUSD discovery'
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
