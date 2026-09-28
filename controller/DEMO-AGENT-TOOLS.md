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
It keeps the old research proof as history. A retry with the same installed
hash returns `already_installed`; an uncertain relaunch is an explicit error,
never a reason to launch another process blindly.

```powershell
& $py $tool --installation $install prepare-batch `
  --batch-id 'new-unique-batch-id' --plan 'C:/frozen-plan.json'
& $py $tool --installation $install run-batch `
  --batch-id 'new-unique-batch-id' --max-seconds 172800
& $py $tool --installation $install batch-status --batch-id 'new-unique-batch-id'
& $py $tool --installation $install batch-driver-status --batch-id 'new-unique-batch-id'
& $py $tool --installation $install stop
```

`prepare-batch` uses Studio's native batch preparation and verifies the queued
member count. `run-batch` uses the existing bounded Studio driver; it can run
for up to 48 hours. Repeating its start call returns the original driver
status and never resets the deadline. `batch-status` reads the EA's member
state; `batch-driver-status` reads the retained driver journal. `stop` is
idempotent and always writes the owner stop marker, including while the driver
holds the terminal lock; the driver requests cancellation of its exact EA
attempt and verifies the result. An MT5 tester Stop or human TAKE also prevents
further agent dispatch. Treat `start_uncertain` or `stop_unconfirmed` as needing
native inspection, not as completion.

This is the first Tier A slice. Terminal discovery, compile, SET editing,
report parsing and exports will be separate tools wrapping existing MT5/EA
features. Native smoke evidence is required before calling this lane qualified.
