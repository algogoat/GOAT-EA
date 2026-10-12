# GOAT Research pilot: a 2-member customer batch on T3

**Purpose.** Prove on a real demo terminal what fixtures cannot:

- the first `/config` launch starts on the GOAT-built `GOAT Research` chart profile;
- its `[StartUp]` monitor expert keeps MT5's saved DLL permission, so the EA's `ShellExecuteW` member relaunch (`Tester.mqh` 85-91) works;
- the monitor profile is never touched during the batch;
- at the end the driver closes MT5 once and reopens the monitor through the fix-B record, with no click.

Design: Claude-Mac goatai#2350 6120004490 and Release 6119992056. Candidate: branch `claude-pc/research-profile`.

**Scope.**

- T3 only. Demo account only, Algo Trading off, no positions or orders.
- Never Banker: it stays untouched until the O3 FAT ends.
- Never Exp 02 or any Open Lab login.
- Every read on T3 goes through `goat-ro.ps1`. Every write is the controller's own command below.

Throughout, `GS` means `goat.exe studio --installation "<T3 installation receipt>"`, the customer lane (`authority_kind` `native_human_control`). `<state>` is the installation's `controller_state_root` and `<data>` is its `terminal_data_root`; `GS discover` prints both.

## 0. Install the candidate

Install only under the runbook rules: Claude-Mac APPROVE, a pin check, and server admission. Install only while Vince is not in a session.

Then check the EA credential expiry. A re-pair is Vince's step.

## 1. Preflight (read-only; any refusal = stop)

| # | Command | Must show |
|---|---|---|
| 1 | `GS onboarding-status` | `native_monitor` complete, demo, Algo off; `monitor_healthy_observation` observed |
| 2 | `GS deploy-preflight` | broker demo, Algo Trading off, 0 positions, 0 orders, tester idle |
| 3 | `GS research-profile-status` | `profile_last` = the `GOAT-Studio-…` monitor profile. `monitor_profile.files` = file names and SHA-256 (save the output). `migration.status` is `not_run` with its plan, or `clean`/`migrated`. `goat_research` is absent or listed |
| 4 | `GS research-status` and `GS research-queue` | no running batch, seed hunt, catch-up or hold-up test; no held slot |

**Before migrating, read the plan in step 3.**

- `plan.status` `movable` lists exactly the bare charts that will be moved aside: T3's 11 bare EURUSD/GBPJPY/GBPUSD charts, when the batch history holds those symbols.
- `refused` names each chart it will not touch (for example bare EURUSD H1 charts whose symbol no batch ever tested). The batch still runs, but the monitor profile stays as it is. Post the reasons in #2350 before going on.

Save these "before" captures, via `goat-ro`:

- `Get-FileHash` of every file in `<data>\MQL5\Profiles\Charts\GOAT-Studio-<session>\`;
- the `[Charts] ProfileLast` line of `<data>\config\common.ini`;
- `<state>\monitor-healthy-chart.json` (if present) and its SHA-256.

## 2. Prepare the 2-member batch

`GS prepare-batch --batch-id pilot-gr-<yyyymmdd>-1 --plan <plan.json>`

- The plan has exactly two members, on two different symbols, with short windows. Use the same plan shape as earlier T3 customer batches.
- Check `<state>\packages\pilot-gr-…\studio-plan.json`: `research_binding.research_profile` must be `"GOAT Research"` and `startup_monitor` present. Anything else = stop (a package bound to `GOAT-Studio-…` is refused at start anyway).

## 3. Run

1. Re-run preflight rows 1 and 2 right before the start.
2. Run `GS run-batch --job-id pilot-gr-<…>-1 --max-seconds 7200 --mt5-restart-consent`.
   - The consent covers one close and `/config` reopen at the start, and one close plus monitor-launch at the end (scope `close_and_reopen_selected_mt5_for_this_batch_start_and_end`).
3. Poll `GS batch-driver-status --job-id …` and `GS batch-status --batch-id …`. Never click Start in MT5 and never relaunch MT5 by hand.

## 4. Capture

| What | Where | Pass |
|---|---|---|
| Start receipt | `<state>\batch-drivers\<id>.json`: `start_route`, `mt5_restart_consent.scope`, `monitor_chart_record`, `monitor_profile_migration`, `research_profile` | `config_restart`; new scope; `monitor_chart_record.status` `recorded` (else its reason); migration `migrated`/`clean`/`already`; `research_profile.profile` = `GOAT Research` |
| GOAT Research reset | `research_profile.manifest_path` and `moved_aside` (`<state>\research-profiles\config-start-<attempt>\`) | `chart01.chr` SHA-256 = `research_profile.chart_sha256`; any previous GOAT Research is listed there whole |
| Migration | `<state>\research-profiles\monitor-profile-migration.json` and `…\<attempt>\monitor-profile\` | `before`/`after` hashes; `after` = `chart01.chr` only; every moved chart present byte for byte |
| Monitor profile during and after the batch | `Get-FileHash` of the `GOAT-Studio-<session>` folder at member 1, at member 2 and after the end | identical every time to the post-migration set (only `chart01.chr`, hash = `monitor_chart_record.chart_sha256`) |
| GOAT Research during the batch | `GS research-profile-status` → `goat_research.files` | `chart01.chr` plus one bare chart (id=0) per tested symbol; strays appear only here |
| ProfileLast | `[Charts] ProfileLast` in `<data>\config\common.ini` | `GOAT Research` while members run; the `GOAT-Studio-…` name after the end (`end_state.restore`, before/after copies under `<state>\research-profiles\restores\`) |
| DLL path | `<data>\MQL5\Logs\<yyyymmdd>.log` (Experts) and `<data>\Logs\<yyyymmdd>.log` (Journal) for the batch window | member 2 started by the EA's own relaunch (a second terminal64 start, then a second tester start); no line containing `DLL` with `not allowed`, `cannot load` or `cannot call`, and no `ShellExecuteW` error |
| End state | `end_state` in the driver journal and in the `run-batch` reply | `status` `monitor_relaunched`; `close.phase` `stopped` (`close.monitor_chart_record.reason` `foreign_profile` is expected); `restore.status` `restored`; `launch.observed_healthy_chart.chart_sha256` = the start's recorded hash |
| After | `GS onboarding-status` | `native_monitor` complete, demo, `terminal_trade_allowed` false, with no click |

## 5. Stop rules

A refusing guard is the answer: stop, report, and diagnose on fixtures. No wrapper reruns.

1. **Any preflight refusal, or a package not bound to `GOAT Research`:** do not start.
2. **The start returns `start_uncertain`:** follow `recovery.next_safe_action` only. Never start again under the same ID.
3. **The monitor profile's hashes change during the batch** (other than the migration's recorded move-aside): stop. Post the hashes.
4. **Any DLL error line, or member 2 never starts:** stop. Let `max-seconds` run out (the driver cancels), then `GS batch-stop --job-id …`. This disproves the DLL path; post the log lines.
5. **`end_state.status` is not `monitor_relaunched`:** do nothing by hand. Post `end_state` (it says whether MT5 was left open on GOAT Research, or closed and not reopened, and why).
   - Never `monitor-launch` again, never use File > Profiles, never edit common.ini.
6. **Anything touching another terminal, Banker, Exp 02, an Open Lab login, real money or credentials:** stop at once.

Post the capture table, filled in, to goatai#2350 (prefix `Claude-PC: [Release]`). Fix-B gates A and B on T3 follow only after Mac reviews it.
