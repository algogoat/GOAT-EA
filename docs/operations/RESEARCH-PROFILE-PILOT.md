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

## 4. Capture (the readout)

Take every hash and file read through `goat-ro`. "Launch" means four moments:

- the start's `/config` launch;
- each EA member relaunch;
- the end close;
- the end-state monitor-launch.

| What | Where | Pass |
|---|---|---|
| **Monitor-profile hash before, at each member, and after** | `Get-FileHash` of every file in `<data>\MQL5\Profiles\Charts\GOAT-Studio-<session>\`. Take it before the start (step 1), right after the migration (`monitor_profile_migration.after`), while member 1 runs, while member 2 runs, and after the end-state monitor-launch. | From the migration on, every set is identical: only `chart01.chr`, with hash = `monitor_chart_record.chart_sha256`. The only change from "before" is the migration's recorded move-aside. |
| Start receipt | `<state>\batch-drivers\<id>.json`: `start_route`, `mt5_restart_consent.scope`, `monitor_chart_record`, `monitor_profile_migration`, `research_profile`, `batch_process` | `config_restart`; scope `close_and_reopen_selected_mt5_for_this_batch_start_and_end`; `monitor_chart_record.status` `recorded` (else its reason); migration `migrated`/`clean`/`already`; `research_profile.profile` = `GOAT Research`; `batch_process` = pid and `created_utc` of the launched MT5, `source` `config_start` |
| GOAT Research reset | `research_profile.manifest_path` and `moved_aside` (`<state>\research-profiles\<UTC stamp>-<hash>\`) | `chart01.chr` SHA-256 = `research_profile.chart_sha256`; any previous GOAT Research is kept there whole |
| Migration | `<state>\research-profiles\monitor-profile-migration.json` and `<state>\research-profiles\<UTC stamp>-<hash>\monitor-profile\` | `before`/`after` hashes; `after` = `chart01.chr` only; every moved chart present byte for byte |
| **GOAT Research chart list after** | `GS research-profile-status` → `goat_research.files` (name, bytes, SHA-256) after the end | `chart01.chr` plus one bare chart (`id=0`) per tested symbol; stray charts appear only here |
| ProfileLast | `[Charts] ProfileLast` in `<data>\config\common.ini`, before, during members and after | the monitor profile before; `GOAT Research` while members run; the monitor profile after the end (`end_state.close.research_profile_restore` `restored`; before/after copies under `<state>\research-profiles\restores\`) |
| **DLL relaunch lines** | `<data>\MQL5\Logs\<yyyymmdd>.log` (Experts) and `<data>\Logs\<yyyymmdd>.log` (Journal) for the batch window. Quote the lines verbatim with timestamps. | Member 2 is started by the EA's own relaunch: the member-1 tester finish, MT5 exit, a new terminal64 start, then the member-2 tester start. No line containing `DLL` with `not allowed`, `cannot load` or `cannot call`, and no `ShellExecuteW` error. |
| **End-state monitor-launch receipt + fix-B match** | `end_state` in the driver journal and the `run-batch` reply, and `<state>\monitor-launches\batch-end-<attempt32>.json` | `status` `monitor_relaunched`. `batch_process.status` `batch_process`, with `source` `ea_member_relaunch` after a member relaunch (the journal's `batch_process` now names that last launch). `close.phase` `stopped`. `close.monitor_chart_record.reason` `foreign_profile` (expected: a GOAT Research close never records). `close.research_profile_restore` `restored`. **`launch.observed_healthy_chart.chart_sha256` = the start's `monitor_chart_record.chart_sha256` = the monitor-launch record's `saved_chart_sha256`.** |
| **Exp 01/02/03 cycle durations around each launch** | Each Exp publisher's cycle log (Ops: watch.ps1 output and the publisher cycle records) | For each of the four launches above: the duration of the cycle before, the cycle spanning the launch, and the cycle after, per experiment. Flag any cycle over its budget or any OVERDUE. |
| After | `GS onboarding-status` | `native_monitor` complete, demo, `terminal_trade_allowed` false, with no click |

## 5. Stop rules

A refusing guard is the answer: stop, report, and diagnose on fixtures. No wrapper reruns.

0. **Review gate:** this script and these stop rules are posted to goatai#2350 for Claude-Mac's review. Nothing runs on T3 before that review.
1. **Any preflight refusal, or a package not bound to `GOAT Research`:** do not start.
   - The driver refuses an older package with `refusal_code` `PACKAGE_PREDATES_RESEARCH_PROFILE` ("This batch was prepared by an older GOAT; it will be prepared again."). Re-prepare under a new ID; never edit the package.
2. **The start returns `start_uncertain`:** follow `recovery.next_safe_action` only. Never start again under the same ID.
3. **The monitor profile's hashes change during the batch** (other than the migration's recorded move-aside): stop. Post the hashes.
4. **Any DLL error line, or member 2 never starts:** stop. Let `max-seconds` run out (the driver cancels), then `GS batch-stop --job-id …`. This disproves the DLL path; post the log lines.
5. **`end_state.status` is not `monitor_relaunched`:** do nothing by hand. Post `end_state`.
   - `skipped` with `END_STATE_SKIPPED:not_batch_process` means the running MT5 was not the batch's own launch, so it was left open. The next GOAT stop (`close-terminal`) restores ProfileLast lazily.
   - `left_as_is` or `closed_not_reopened` carry their reason.
   - Never `monitor-launch` again, never use File > Profiles, never edit common.ini.
6. **Any Exp 01/02/03 cycle overruns its budget around a launch:** stop after the batch. Post the durations before fix-B gates A and B.
7. **Anything touching another terminal, Banker, Exp 02, an Open Lab login, real money or credentials:** stop at once.

Post the filled-in readout to goatai#2350 (prefix `Claude-PC: [Release]`). Fix-B gates A and B on T3 follow only after Mac reviews it.