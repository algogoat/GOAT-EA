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
