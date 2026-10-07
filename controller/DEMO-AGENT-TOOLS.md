# Demo agent tools (owner and maintainer lane)

**Customers and their agents: do not use these tools.** Follow [AGENT-START-HERE.md](AGENT-START-HERE.md) (`goat.exe studio ...`) and [GOAT-OPERATING-MODEL.md](GOAT-OPERATING-MODEL.md). This lane exists for GOAT's own demo research and for reviewed build installs; its commands refuse to drive Studio until `install-build --enter-demo-lane` has converted the selected session to this lane. Without `--enter-demo-lane`, `install-build` keeps the session's lane: the desktop app's update with MT5 open uses it on customer terminals, and a customer (`native_human_control`) session stays on the customer lane.

`demo_agent.py` (installed as `goat.exe demo --installation <receipt> <command>`) operates one selected MT5 installation from its existing `installation.json`. It never sends trades or turns on Algo Trading. It drives the EA's existing Studio queue and optimizer; there is no second tester or portfolio engine.

The account is the demo login and server already paired in that installation's controller session (from `bootstrap`); there is no built-in account. Every command that can change the terminal or its files requires a fresh broker-reported demo account matching that pairing, the selected process, Algo Trading off, an idle native tester, at least 5 GiB free on the terminal-data, Common Files and controller-state volumes, and no owner STOP or pending human TAKE CONTROL. A real account always refuses. `demo-agent/actions.jsonl` records intent and readback events.

Output: success prints `{"ok":true,"result":...}` to stdout (exit 0). Errors print `{"ok":false,"code":"REFUSED"|"IO_ERROR"|"INTERNAL_ERROR","error":"..."}` to stderr (exit 1). `stop` that cannot confirm the stop prints `code: STOP_UNCONFIRMED` (exit 2). Some refusals also carry a stable `refusal_code` (and fields such as `batch_id` or `moved_by`) beside the unchanged `error` sentence; `code` stays `REFUSED` (see "restore-lane refusal codes"). `settle-refused-start` errors and refusals carry `native_action`.

```powershell
& $goat demo --installation $receipt status          # process, broker, EA hash, owner feedback age, driver journals
& $goat demo --installation $receipt disk-status     # free bytes against the 5 GiB reserve
& $goat demo --installation $receipt preflight       # read-only; reports ready_for_install, ready_for_batch and readback_refresh_on_start
& $goat demo --installation $receipt credential-recovery-preflight   # read-only; the desktop's update for an EA that lost its GOAT sign-in
& $goat demo --installation $receipt install-build --candidate '<reviewed .ex5>' --sha256 '<64 hex>' --monitor-config '<existing monitor-only .ini>'   # owner enrollment: add --enter-demo-lane
& $goat demo --installation $receipt restore-lane     # preview (says moved_by); --apply returns a customer session an app update moved to demo_direct; an owner enrollment also needs --owner-confirmed
& $goat demo --installation $receipt settle-refused-start --batch-id '<id>'   # a restart-arm start the EA refused before consuming it; closes MT5 normally
& $goat demo --installation $receipt launch-terminal  # optional: --monitor-config '<monitor-only .ini>'; default: the saved GOAT Studio profile
& $goat demo --installation $receipt prepare-batch --batch-id '<new id>' --plan '<plan.json>'
& $goat demo --installation $receipt run-batch --batch-id '<id>' --max-seconds 172800
& $goat demo --installation $receipt resume-batch --batch-id '<id>'
& $goat demo --installation $receipt batch-status --batch-id '<id>'
& $goat demo --installation $receipt batch-driver-status --batch-id '<id>'
& $goat demo --installation $receipt stop            # optional: --monitor-config '<monitor-only .ini>'
& $goat demo --installation $receipt clear-stop
& $goat demo --installation $receipt recover-orphan  # optional: --review-id '<id>' to observe only
& $goat demo --installation $receipt research-status # read-only lane: activity, pace/ETA, pause, driver, disk, monitor
& $goat demo --installation $receipt research-queue  # read-only queue: every batch, seed hunt and catch-up; optional: --finished 0..50, --job-id '<id>' (repeatable)
& $goat demo --installation $receipt batch-pause --batch-id '<id>'    # optional: --immediate
& $goat demo --installation $receipt batch-resume --batch-id '<id>'   # optional: --new-batch-id, --resume-token, --max-seconds, --clear-stop, --include-failed
& $goat demo --installation $receipt compact-evidence   # preview; --apply moves finished in-row evidence history to verified logs
& $goat demo --installation $receipt compact-receipts   # preview; --apply archives legacy full-queue receipts and keeps their queue digest
```

- `compact-evidence` and `compact-receipts` are local store maintenance with no native effect. Each previews by default and, with `--apply`, refuses while any batch is starting or running (checked before any archive and again inside each transaction). Archives are temp-written, fsynced, sha256-verified and atomically renamed, and are never deleted. Run `compact-evidence --apply` first, then `compact-receipts --apply`. Neither shrinks `studio.sqlite` on disk: that needs a separate reviewed `VACUUM`. Both change the store's content hash, so prepare a handover or owner-maintenance record after compacting, not before.

- `install-build` verifies the candidate hash and the inert monitor INI (only Charts/Experts/StartUp monitor keys; account, tester and script directives refuse before MT5 closes), archives the old EX5 and identity files, closes only the selected idle demo terminal, copies the EX5, relaunches its monitor and reads back the physical hash, demo account, EA feedback and Algo-off state within 120 seconds. Repeating it with the same candidate and hash returns `already_installed` or completes an interrupted swap; an uncertain relaunch never dispatches a batch. It rebinds the session to the new receipt and keeps the session's lane (`authority_kind`): only `--enter-demo-lane` (the owner enrolling one of GOAT's own demo terminals) writes `demo_direct`, and it refuses together with the app's `--bundle-version`/`--agent-guide-path`, so an app update never changes a lane. Each `local_identity_verified` row in `actions.jsonl` records `authority_kind` and `previous_authority_kind`, and `enter_demo_lane: true` for an enrollment. It also rebinds the prepared `monitor-profile.json` to the new receipt (row `monitor_profile_rebound`, old receipt kept as `backups/monitor-profile-<sha256>.json`), but only for this session's own profile and an installation that differs only in what an update rewrites (EA hash, bundle version, guide path, install time). Before this, `monitor-launch` refused after every desktop update with `Monitor profile receipt belongs to another installation/session`. `studio monitor-launch` and `monitor-prepare` apply the same rebind from the retained `installation-*.json` backups, which heals a profile an earlier controller left behind. Anything else still refuses.
- Credential recovery (goatai#1885, T2 2026-10-04). An EA whose GOAT sign-in was rejected (`License not valid for this MT5 account`) waits for a new connection and never loads its Studio UI, so `preflight` refuses with `Fresh EA owner feedback unavailable`. The refusal JSON then carries `"reason":"ea_feedback_unavailable"`, which is the only refusal the desktop app answers with recovery.
  - `credential-recovery-preflight` (read-only) proves the account from MT5 itself (the `MetaTrader5` package: demo trade mode, the exact paired login and server on an allowlisted server, currently `Darwinex-Demo`). It also requires Algo Trading off, an idle tester, a **strictly flat** account (0 positions and 0 pending orders; no read-only allowance) and the registered EA.
  - It proves agent ownership from the last EA observation at any age, the unchanged session and `active.json`, and the controller store's owner. That observation must come from the installed build: it names the installed EX5 file, it was written after GOAT last placed those exact bytes (the EX5's write time and the latest `binary_replaced` row), and its `build` marker matches the one GOAT's verified readback recorded for these bytes, when there is one. Verified readbacks now record `build` in `verified-build.json`.
  - It refuses while the EA is reporting, and after **2 recoveries for this login on the same UTC day**: "a person should look at this terminal". It counts only the `credential_recovery_close` rows, written after every check and right before MT5 is closed, so a refused attempt never spends the allowance.
  - `install-build --credential-recovery` (desktop only, with `--require-running` and `--linked-login`, never `--enter-demo-lane`) uses those checks before the close instead of fresh feedback, including the daily limit. It installs only a different build.
  - The readback after the relaunch is unchanged (a verified owner readback, or `pairing_required` for the new build). The desktop separately requires the login to be linked to the signed-in user and covered by their "Let my agent connect my own demo terminals" consent.
- `restore-lane` repairs a customer terminal that an app update moved into this lane before that rule (goatai#1885: Terminal 3 updated beta.17 to beta.18 with MT5 open, and its `studio close-terminal` then refused with `Demo mutation requires the broker-verified agent tool`). Without `--apply` it is a read-only review; with `--apply` it rewrites only `session.json`'s `authority_kind` back to `native_human_control`, keeps the current `installation_sha256`, saves the `demo_direct` session bytes in `demo-agent/backups/` and logs `restore_lane`. MT5, the EA, the receipt and `studio.sqlite` are untouched. It refuses unless every proof holds: the session is `demo_direct` and bound to the current receipt; `demo-agent/backups/` holds this tool's own backup of this exact session on `native_human_control` (file content matching its name), or a legacy backup of this exact session written before sessions carried `authority_kind` (beta.14-era customer installs; the review then reports `evidence_kind: legacy-session-without-authority-kind`, and the store's customer authority below is what proves the lane); `studio.sqlite` still holds the customer lane's `native_human_control` authority for the binding; no `research-authority.json`; `actions.jsonl` has an `install_build` identity row and only update steps (`install_build`, `launch_terminal`, `readback_refresh`, `recover_orphan`, `restore_lane`), never owner demo-lane work, so an owner terminal that has run demo research refuses; and no owner STOP, active native batch, live driver or seed/catch-up holds the terminal. A restored session is a customer session again: `goat.exe studio` mutations and the desktop's `suite.closeTerminal` work, and `goat.exe demo` research commands refuse.
  - One exception (goatai#1885, tester a649295d): the logged steps of a batch whose only start **provably never ran** (`studio_prepare_batch`, `studio_run_batch`, `detached_driver`, `retire_unactivated`, `settle_refused_start`, each with its `batch_id`). Every such batch needs its settlement record for the job's exact attempt: `retired-starts/<job>-<attempt16>.json` from `retire-unactivated` (job `cancelled`, `retired_never_activated`), or `refused-starts/<job>-<attempt16>.json` from `settle-refused-start` (job `failed`, `retired_never_started`, its `self-repair/<action>/transaction.json` `complete`). A batch that activated, never started, or is still open refuses, and so does any other operation (a seed, a deploy, `stop_batch`, `clear_stop`, `continue_batch` ...). A `retire_unactivated` intent whose proof refused, and a `settle_refused_start` that refused before any native action, change nothing and are ignored. The preview lists the accepted batches in `never_started_batches`.
  - **Who moved the session: `moved_by`** (goatai#2272). The preview, the apply result and every refusal after the action-log check report `moved_by`: `app_update`, `owner_enrollment` or `unknown`, with `moved_by_evidence` (the deciding `actions.jsonl` row) on a preview. It is read from the lane rows of `actions.jsonl` in order (`install_build`/`local_identity_verified` and `restore_lane`/`restored`); the first move into the current `demo_direct` stint decides, and `restore_lane`/`restored` or a row that leaves `demo_direct` ends the stint:
    - `app_update`: an identity row **without** `previous_authority_kind`. Bundles beta.15 to beta.18 (GOAT-EA before #143) forced `demo_direct` on every `install-build` and logged only `ea_sha256`, `installation_sha256` and `session_sha256`; there was no owner enrollment then. The desktop's update also logged `install_build`/`bundle_identity_verified` (`bundle_version`, reported in the evidence, not required).
    - `owner_enrollment`: an identity row **with** `previous_authority_kind` that moves the session into `demo_direct` (from `native_human_control` or a legacy session without `authority_kind`). From beta.19 (#143) only `install-build --enter-demo-lane` writes such a row. From this version the row also says `enter_demo_lane: true`, which makes the stint the owner's even on a session an old update had already moved.
    - `unknown`: no row moves the lane (an empty or older log, the legacy session of goatai support edc7e808 whose update predates the identity row, or a log that starts with the session already `demo_direct`).
  - `--apply` on `moved_by: owner_enrollment` refuses (`RESTORE_OWNER_ENROLLED`) unless `--owner-confirmed` is also passed: a person or agent asking deliberately. The preview then says `owner_confirmation_required: true` and its `next_action` names the flag. `app_update` and `unknown` apply as before. The desktop's self-heal applies only `app_update`. The `restore_lane` row records `moved_by` and `owner_confirmed`.
  - **restore-lane refusal codes.** Each refusal keeps its sentence and adds `refusal_code` (the CLI's `code` stays `REFUSED`). Stable; new codes are only appended:

    | `refusal_code` | Sentence starts | Extra fields |
    |---|---|---|
    | `RESTORE_INVALID_ARGUMENT` | `restore-lane --apply must be boolean` / `--owner-confirmed must be boolean` | |
    | `RESTORE_NOT_DEMO_DIRECT` | `restore-lane returns only a demo_direct session` | |
    | `RESTORE_NOT_BOUND_TO_RECEIPT` | `Session is not bound to the current receipt` | |
    | `RESTORE_NO_BACKUP` | `No retained customer-lane backup of this exact session` | |
    | `RESTORE_RESEARCH_BOUND` | `A typed research continuation is bound here` | |
    | `RESTORE_STORE_UNREADABLE` | `Controller store unreadable` | |
    | `RESTORE_NO_CUSTOMER_AUTHORITY` | `The controller store holds no customer-lane authority` | |
    | `RESTORE_ACTION_LOG_UNREADABLE` | `Demo action log unreadable` | |
    | `RESTORE_NO_INSTALL_RECORD` | `No retained install-build record for this session` | `moved_by` |
    | `RESTORE_EA_DIFFERS_FROM_RECEIPT` | `No retained install-build record and the installed EA differs` | `moved_by` |
    | `RESTORE_OWNER_DEMO_WORK` | `This session has done owner demo-lane work (...)` | `operations`, `moved_by` |
    | `RESTORE_BATCH_NOT_PROVEN_NEVER_STARTED` | `Batch <id> is not proven never-started` | `batch_id`, `moved_by` |
    | `RESTORE_OWNER_STOP` | `Owner STOP is set` | `moved_by` |
    | `RESTORE_ACTIVE_BATCH` | `Batch <ids> is active; restore-lane waits` | `batch_ids`, `moved_by` |
    | `RESTORE_LIVE_DRIVER` | `A live demo batch driver owns this terminal` | `moved_by` |
    | `RESTORE_SEED_RUNNING` | `A seed or catch-up run holds this terminal` | `moved_by` |
    | `RESTORE_OWNER_ENROLLED` | `The owner enrolled this terminal in the demo lane` (apply only) | `moved_by` |

    Other failures (an unreadable file, an internal error) have no `refusal_code`.
- `settle-refused-start --batch-id <id>` settles a config (restart-arm) start the EA refused **before consuming it**: restart phase `controls_installed`, an EA receipt for exactly this arm with `consumed: false` and a pre-consumption refusal (`START_PROTOCOL_NOT_QUALIFIED`, `RESTART_INTENT_REJECTED`, `INVALID_TESTER_INI`, `ACTION_REJECTED`), the driver `start_uncertain`, the queue `reconcile_required`. `retire-unactivated` refuses that shape (the controls were installed). It reuses the reviewed self-repair proof (no consumed start, no start or arm intent, the issued arm request matching and expired, the native queue and run folders untouched, no tester output, the attempt's controls installed and untouched, an SDK-confirmed idle demo with Algo off and no positions or orders) and its settlement: MT5 is closed normally, the original controls are restored, `request.json`/`permit.json` are archived under `self-repair/<action>/`, and the batch is recorded `failed` / `retired_never_started` with every receipt kept. Earlier settled batches may stay in the queue; another batch that may hold native work refuses, as do owner STOP and a pending human TAKE CONTROL. It writes `refused-starts/<job>-<attempt16>.json`, logs `settle_refused_start` (`intent`, then `settled`, `refused` or `failed`) and is replay-safe (one action per attempt; a retry never closes MT5 twice). Nothing runs or trades. Reopen MT5 afterwards with `launch-terminal`.
  - **`native_action`** (goatai#2272) in every refusal and error JSON (and `complete` on success) says how far a settlement of this attempt got, from its journal `self-repair/<action>/transaction.json`. It names the last journaled step; the next one may have partly run:

    | `native_action` | Journal phase | Meaning |
    |---|---|---|
    | `none` | none, or `prepared` | MT5 was not touched by this settlement (evidence copies only) |
    | `mt5_close_issued` | `close_issued` | the normal close was sent; MT5 may still be exiting |
    | `mt5_closed` | `stopped` | MT5 exited; the controls may be partly restored |
    | `controls_restored` | `controls_restored` | the original controls are back; the batch is not recorded yet |
    | `queue_settled` | `settled` | the batch is recorded `failed` / `retired_never_started`; the outcome and record are not written yet |
    | `complete` | `complete` | settled; only the `refused-starts/` record may be missing |
    | `unknown` | unreadable or unexpected | inspect the journal |

    The `actions.jsonl` row keeps its boolean `native_action` (what restore-lane reads) and adds `native_step` with this value.
  - **An interrupted settlement finishes with MT5 closed** (GOAT-EA#170 review). If a settlement stopped after the close (MT5 took over 150 s to exit, or the caller was killed) or after restoring the controls, run the same `settle-refused-start` again **with MT5 still closed**. When the journal is at `close_issued` or later and MT5 is not running, it skips the broker readback (a closed MT5 cannot answer) and uses the demo account proof the settlement journaled on the live process before the close (`account_proof`): it must name this session's exact paired login and server, `demo: true`, and the very process the settlement closed, for this job's exact attempt, its fixed action ID and this receipt. A missing or mismatched proof refuses and changes nothing. Everything else is re-checked as before (owner STOP, a pending TAKE CONTROL, ownership, the controller revision, the retained evidence and controls). The `intent` row then says `account_proof_source: journal`, and the result `resumed_from_journal: true`. While another MT5 runs it refuses ("close it normally, then run settle-refused-start again"); a `complete` settlement still replays its outcome with MT5 open.
- **Recovery recipe: a customer terminal moved to demo_direct with a refused restart-arm start** (tester a649295d). Symptoms: `goat.exe studio batch-status` refuses `Demo mutation requires the broker-verified agent tool`; the driver shows `start_uncertain` with `Native arming refused`; the EA receipt is `START_PROTOCOL_NOT_QUALIFIED`; the batch is `reconcile_required` and nothing ran.
  1. Diagnose (read-only): `goat.exe demo research-status`, `goat.exe demo batch-driver-status --batch-id <id>`, `goat.exe studio native-recovery-status`.
  2. MT5 open on the bound demo, connected, Algo Trading off, no positions or orders, tester idle.
  3. `goat.exe demo settle-refused-start --batch-id <id>` (MT5 closes normally).
  4. `goat.exe demo launch-terminal`.
  5. The app's bundle update (rebinds the session to the current receipt).
  6. `goat.exe demo restore-lane`, then `restore-lane --apply`.
  7. A new pilot on the customer lane under a new batch ID.

  Do **not** run `stop`, `clear-stop` or `retire-unactivated` on this shape: `stop` sets owner STOP, which the settlement refuses, `clear-stop` is owner work restore-lane never accepts, and `retire-unactivated` refuses it.
- `launch-terminal` reopens a stopped registered demo terminal and requires fresh broker, Algo-off, idle-tester and EA feedback afterwards. Without `--monitor-config` it opens the saved GOAT Studio profile (`monitor-profile.json`) through the same monitor-only INI `monitor-launch` writes (kept content-addressed in `demo-agent/monitor-restarts/monitor-<sha>.ini`). Given the retained `dll-granted-<sha>.ini` from an install, it launches that file's monitor-only original: the DLL grant is never re-asserted, and the readback refuses if MT5 no longer allows DLL imports. On a running terminal it only re-reads the build (the manual readback refresh).
- After GOAT's own MT5 relaunch (a batch's /config start, the EA's member-boundary restart, a seed or catch-up member, or `launch-terminal`) `verified-build.json` still names the previous process. The next `prepare-batch`/`start`/`continue` re-reads the build on the new process by itself when the proof is for the same EA bytes, the new process runs the same terminal executable (the broker proves the data root and paired demo), it started later, and its command line has a `/config:` INI inside the controller state or Common Files folders. A person's reopen (no such `/config`) is never refreshed silently: run `launch-terminal`. `preflight` reports `readback_refresh_on_start`.
- After the last seed or catch-up member MT5 stays closed; `seed-start`/`seed-resume` (and the catch-up commands) then reopen it on the saved GOAT Studio profile and read the build back (`monitor_reopen`), unless owner STOP, a pause or a person stopped the run. If that reopen cannot be confirmed the batch result is unchanged and `next_action` says to run `launch-terminal`.
- `run-batch` (`--max-seconds` required, 1..172800) starts a detached Windows worker and returns when its journal exists; that is not proof that native work runs. Repeating it returns the original worker and never resets the deadline. `resume-batch` attaches a new worker to the retained attempt and original deadline and never starts a pending job.
- **An unconfirmed launch.** `run-batch` or `resume-batch` may answer "Detached batch driver launch unconfirmed": the Windows task was registered, but its driver did not report within 60 s. Never start another driver by hand.
  - Run `batch-driver-status`. Its `worker` shows the reservation, with `alive`.
  - If the task is still running or queued, the launch is unresolved and every new start refuses. Wait.
  - Once the task reports, its driver is the one running: it is not a duplicate. A task that starts only after the 60 s wait (Python slow to start under load) still drives: its bootstrap is accepted for the same nonce, and the driver re-checks that nonce under the terminal lock.
  - If Windows proves the task never ran, `launch_never_started: true`. The proof needs: no started receipt; the task is gone, or exists and is not running or queued; it has not run since the envelope; and its last result is `SCHED_S_TASK_HAS_NOT_RUN` (267011). Then the same `run-batch` (or `resume-batch`) is allowed again.
  - That retry first removes the old task under the terminal lock and confirms it is gone. If the removal can't be confirmed, it refuses. The retry then logs `detached_driver`/`launch_never_started` with the task info, keeps the envelope, and reserves a fresh nonce, so a late bootstrap of the old envelope is refused.
  - This is the same rule as a driver journal's `start_uncertain` with no `attempt_id` (refused before anything reached MT5, so the same command runs again). Both mean "retry only what provably never ran".
- **A stalled Windows process query.** The process inventory behind every check (`Get-CimInstance Win32_Process`) is retried through a stall.
  - A check that gates a launch or a close gets 4 attempts of 20 s, with 2, 5 and 10 s pauses. Each pause varies by up to 25% either way, so two GOAT drivers caught by the same stall don't retry in lockstep.
  - Status reads (`status`, `batch-driver-status`, `seed-status` and the catch-up and hold-up status commands, including their broker readback) and probes bound each inventory to 25 s.
  - A driver loop or a close wait that hits a stall waits for the full retry (about 100 s per inventory), and a member launch can add the 90 s identity wait, so one foreground drive of `--max-seconds N` can take about N+200 s. The detached drivers aren't affected by a caller timeout; keep a `--foreground` call's tool timeout well above its budget.
  - Every `Get-CimInstance` runs with `-ErrorAction Stop`, so a WMI error is a failed attempt (retried, then raised), never an empty process list.
  - Each failed attempt is logged in `demo-agent/process-query.jsonl` (`<controller state>\process-query.jsonl` for `goat.exe studio`). The log rotates at 1 MB.
  - Only if every attempt fails does the check fail, closed, as before.
  - Stalls cluster at an MT5 launch. After a seed, catch-up or hold-up member launch, GOAT waits up to 90 s for that MT5's identity. A stalled query, or a row without its path, means "not seen yet". A different PID, two processes or an MT5 exit refuse at once.
  - A row WMI lists without its path is read from the process itself (bound to the row by its creation time) before GOAT refuses "Unknown terminal executable". A process it can't open still refuses.
- `stop` writes the owner STOP marker and waits for the exact cancellation readback; it returns `cancelled`, another verified terminal result or `stop_unconfirmed`. The live driver watches for STOP every 0.5 s between its passes and, once a cancel of its attempt is out, re-reads every second, so a running batch settles in seconds (the EA answers a cancel in about 1.5 s); the readback itself is unchanged. `clear-stop` removes only a STOP written by this tool, after a verified idle demo and a terminal batch state.
- Treat `start_uncertain` or `stop_unconfirmed` as "inspect the native state", never as completion. A `stop_unconfirmed` batch is settled with `batch-pause`, which adopts its outstanding stop.
- **A stalled batch** (goatai#1885, Banker 2026-10-05). When no member has run for 15 minutes, the tester is idle and members are still queued, `research-status` reports `activity.status: stalled` and `batch-driver-status` reports `status: stalled`. Each carries a `stall` with a plain sentence and `fix.commands`. The usual cause: a member ended on the EA's tester-idle timeout while the tester was still busy, and the EA's deferred MT5 restart for the next member was never retried (`restart_pending` stays true). Neither the safe point nor `--immediate` lets `batch-pause` land while that restart is pending. Recover with `stop`, then `continue --batch-id <id> --clear-stop` (add `--include-failed` to retry the failed member). The cancel clears the EA's batch and its pending restart, finish keeps every finished member, and the remaining members run as `<id>-rN`. If `stop` answers `stop_unconfirmed`, run `batch-pause --batch-id <id>` (it adopts that stop), then `continue`.
- **Driver CPU.** An observing pass (reconcile plus a finish attempt) can cost a minute of CPU on a large store. While nothing changes, the driver waits 30, 60, then 120 s between passes, and always at least twice the last pass, up to 300 s, so it uses at most about a third of one core. Any change returns it to 30 s. STOP, TAKE CONTROL, a published cancel and a new pause request still wake it within 0.5 s. The driver thread runs one step below the publishers (BelowNormal class, below-normal thread). The process class and MT5's priority are unchanged. `batch-driver-status` shows `observe` (`quiet_since_wall`, `quiet_passes`, `last_pass_seconds`, `next_wait_seconds`).

## Research operations: status, pause and resume

`research-status` is one read-only call per installation, built for a UI lane or
an agent loop. It never takes the terminal lock, opens the mutable store,
launches, closes or signals MT5. It returns the terminal (process, build), the
paired account, the EA build, the current batch or seed hunt (`status`,
`members_done`/`members_total`, `qualifying` = completed members with at least
one kept SET that passed the run's own export thresholds, `last_member`,
`current_member`, `pace.minutes_per_member`, `pace.eta_utc`, `lineage`,
`pause`, a one-sentence `headline`), driver health (`unsupervised` when a running
batch has no live driver), disk headroom against the driver's reserve, owner
STOP, and the monitor: `ticking`, `relaunching` (an ordinary member-boundary
restart), or a `blocker` with `code`, `message` and `fix`. Codes include
`terminal_closed`, `monitor_unlicensed` (the EA's sign-in status is newer than
its last heartbeat; when another terminal's sign-in was approved after it, the
message is "This terminal's GOAT sign-in was replaced by another terminal —
re-pair it."), `monitor_build_not_admitted`, `monitor_webrequest_permission_required`,
`monitor_unbound`, `human_took_control` and `monitor_silent`.

A batch's export counts follow `goat-export-qualification-v1` (`qualifying_basis`;
see "Export qualification" below):

- `qualifying` and `passing_sets`: members and sets that passed;
- `below_threshold_members` and `below_threshold_sets`: the EA keeps its best set
  even when nothing passed (`SortAndTrimExports: Passing=0 Kept=1`); a best-effort
  result, shown apart and never counted as qualifying;
- `unknown_members` and `unknown_sets`: at the cut-off, or no thresholds found;
- `exported_sets`: every kept set; `thresholds`: the `min_sr`/`min_arf` judged against.

The headline reads "98 qualifying (SR ≥ 2.5, ARF ≥ 0.2), 205 more kept below
threshold". Before `qualifying_basis`, `qualifying` counted every completed member
with any kept SET, which overstated g6 as 303 members when 98 had passed.

`research-queue` lists every job beside that one activity, one row each, so the
desktop's Research queue and an agent see everything the terminal has run, runs
and will run from one call (goatai#2240). It reads the same retained state as
`research-status` and is just as read-only:

- **Refine**: native batches from the session's queue rows.
- **Explore**: seed hunts from `seeds\<id>\state.json` and `manifest.json`.
- **Prove**: OOS catch-ups from `catchups\<id>\`.

Each row has `batch_id`, `kind` (`batch`, `seed`, `catchup`) and `stage`
(`refine`, `explore`, `prove`). Its `state` is `queued`, `running`, `pausing`,
`paused`, `blocked` (nothing runs until someone acts, such as a seed member that
needs `seed-reconcile` or a start refused before MT5 was touched), `finished`,
`stopped` or `failed`. A row also carries:

- the queue or runner `status` and a plain `note`;
- `symbols` and `timeframes` in member order;
- `members_done` (ran to a result or a failure; a cancelled member never ran) and
  `members_total`;
- `started_utc` and `finished_utc`;
- `eta_utc`, only while `running` and only from members that already finished;
- the results: `qualifying` (seed: candidates with qualifying passes; batch:
  members whose kept SETs passed the run's export thresholds), `qualifying_candidates`,
  `held_up` (catch-ups), `members_no_edge` and `members_failed`; a batch row also has
  `passing_sets`, `below_threshold_members`, `unknown_members`, `thresholds` and
  `qualifying_basis`.

Unfinished jobs are always listed. Only the `--finished` most recent ended jobs
are kept (default 5, 0..50). `--job-id <id>` (repeatable, up to 20) also lists that
queue batch however long ago it ended, after the kept ends and without displacing
any of them, for example the batch a restore-lane refusal names (`batch_id`);
the reply then has `job_ids` and `job_ids_missing` (IDs that are not queue batches). A run whose files cannot be read whole, or whose
state and manifest disagree, is listed in `skipped` with its reason, never
guessed. Every row names its run, so the held-out guard redacts each row's
results and note per strategy key and window, exactly as it does for
`research-status`; progress, dates and state stay readable.

A member whose optimization ran (at least one pass traded) and whose back and forward
reports are whole, but had no pass profitable with 50+ trades, is a research result for its
tested window, not a failure. A report whose EA never traded, that cannot be read, or that is
partial stays a real error and `--include-failed` retries it. The EA keeps its native
queue status `Error` (no protocol change) and writes a `NoProfitablePasses` row to
the run's `item_stats.tsv` (passes, profitable count, best profit, best score and
the back-test window). `research-status` reports these as `members_no_edge` (with
`no_edge` details and `no_edge_window`) apart from `members_failed`; the headline
says `N tested with no edge in <window>`, and `last_member.status` is
`no_profitable_passes` with a one-line `summary`. `finish` records them as
`research_outcomes` for the scoreboard, a pause whose only errors are no-edge members
is `finished`, and `--include-failed` never re-runs them; `--include-no-edge` (`batch-resume`,
or `resume-batch` for a batch already recorded finished) deliberately re-runs them. Always quote the window:
"no profitable settings in this window" never means "this strategy never works".

The sibling result: profitable passes with 50+ trades were kept, every one was found in a
whole forward report with matching back values and inputs, and none reached the export score
(60) once the forward period was included. Before B40 this ended as `No Rows!` and a combine
error. The EA writes a `NoQualifyingRows` row (outcome `no_qualifying_rows`, plus
`back_rows`, `forward_matched`, `forward_discarded`, `best_combined_score`, `score_threshold`)
and the controller counts it in `members_no_edge` exactly like `no_profitable_passes`;
`last_member.status` is `no_qualifying_rows` and its `summary` says "tested, nothing qualified
in <window>" with the best score. A forward report that is partial, unreadable, missing a kept
pass, or disagrees with the back report stays a real error.

The third result: sets scored 60+ with the forward period, but every set re-tested over the
export window ran to the end and lost money, so nothing was exported. The EA writes only a
plain `Error` row (`Export cycle finished`, `FinalExports` 0) here, the same row it writes when
MT5 fails during the export cycle, so the controller reads the run's own EA log (`log.GOAT`)
for that member's last attempt (matched to the timeline's start and end). Only when it shows
the reports combined once, the top set reproduced its report, one export sequence with every
attempt a logged loss (`N attempts – 0 profitable, N losses, 0 errors`, `Export Profit=<negative>`)
and no other `❌` line is it outcome `no_profitable_exports` (plus `export_window`,
`sets_retested`, `export_losses`, `best_export_profit`, `unique_sets`, `best_combined_score`,
`score_threshold`), counted in `members_no_edge`, recorded by `finish` and skipped by
`--include-failed` like the others. A tester or export timeout, a start or move failure, an
export error, a kept export or an unreadable log stays a real failure.

`no_edge_counts` gives `members_no_edge` per outcome. When every such member had no profitable
settings the headline keeps `N tested with no edge in <window>`; otherwise it says
`N tested, nothing qualified in <window> (a with no profitable settings, b none scored 60+ once
the forward period was included, c lost money on the export re-test)`, because those members
did have settings profitable in-sample.

`batch-pause` needs no terminal lock (like `stop`): it writes one durable pause
intent (`batch-pauses/<id>.json`) and returns `state: pausing`. A live driver
honours it on its next tick; otherwise one bounded pause supervisor starts
(`_drive-batch ... --pause-seconds 21600`, its own Windows demand task). The
safety rules, in `studio_batch_pause.py`:

- One stop is published only at a safe point while the bound monitor reports:
  within the first 5 minutes of a member that just turned OnGoing (never inside
  its last 3 minutes once the pace is known), or with no member active and the
  tester idle after the between-member relaunch. Owner STOP, a pending human
  TAKE, low disk, a clock rollback or the driver deadline drop the member-age
  rule, never the reporting-monitor rule.
- An expired, unconsumed stop is never replaced while unanswered. The EA answers
  it with `CANCEL_REJECTED` on its first bound tick; only that exact receipt,
  observed after expiry, admits exactly one successor identity, linked first in
  `cancel-successors/<attempt>.json` under the `cancel-rejected-successor`
  identity rules, so `finish` binds it. Both stop receipts are kept. A rejection
  observed before expiry (an identity check), a rejected successor or any other
  refusal ends in `pause_failed` with one sentence and its fix.
- The driver never records `cancel_issued` for a pause, so its journal is never
  poisoned. It keeps the disk guard and finish throughout, and a resumed driver
  keeps supervising. A journal an owner STOP left at `stop_unconfirmed` is
  adopted: its outstanding stop becomes the pause's (`adopted_stop: true`).
- After MT5 confirms, finish harvests the completed members and the pause records
  `paused` with `resume_token`; a batch that completed every member first records
  `finished`. A failed pause hands the batch back to normal supervision.

`batch-resume` refuses in plain words while the batch is still pausing, failed,
finished, its monitor has a blocker, or an owner STOP is set (pass `--clear-stop`
to lift a STOP written by this tool). Otherwise it re-verifies the paused result
and token, refreshes `verified-build.json` after a terminal restart, accepts the
protected peer when only its process instance restarted, closed or reopened (same
reviewed executable bytes, data root and origin; anything else still needs
`peer-prepare`/`peer-apply`; see "Protected peer restarts" below), builds the remaining members from per-member native evidence, prepares them as a
successor (`<id>-rN`, fixed in the pause record before preparation so a retry
reuses it), records `batch-lineage/<successor>.json`, and starts the successor
under the bounded driver with the original budget (or `--max-seconds`). Repeating
it returns the same successor.

If that reserved successor was settled without ever running (retired by
`retire-unactivated`, retired never-started, or cancelled while still pending),
`continue` and `batch-resume` release it first: one line with the retirement
proof is appended to `batch-lineage-releases/<id>.jsonl`, the pause goes back to
`paused` (same result and token), and the next free `-rN` is prepared and started.
No `--new-batch-id` is needed; an explicit new ID is also accepted. The released
successor and its files are kept. A successor that actually ran (even if it was
cancelled later) is not released: `continue --batch-id <successor>` continues its
own remaining members.

### Protected peer restarts

Two MT5 terminals on one PC run independently. The reviewed peer is identified
by its executable (path and bytes), data root and `origin.txt` binding, not by a
PID. When this lane runs an isolated EA (V1.49: per-terminal/login batch folder)
and the peer's data root hashes to a different batch folder, a peer that
restarted, closed or reopened is the same reviewed peer:

- `continue`, `batch-resume` and every start accept it with no review. Each new
  instance is appended to `peer-instances.jsonl` in the peer policy folder
  (`previous_pid`, `pid`, review ID, peer hash, source). `policy.json` is never
  rewritten for a restart.
- A closed peer never blocks this lane (`peer_closed`).
- Package bindings carry `protected_peer_sha256`, not a PID, so a peer restart
  never invalidates a prepared or sealed package. A package prepared by the
  older exact-instance code still verifies when a retained reviewed policy with
  its recorded hash names the same unchanged peer.
- A running driver takes no terminal inventory: MT5 advances members itself, so
  a peer restart never touches a running batch.

Still refused: an unknown MT5 (different executable), two processes of the
peer, a changed peer executable, data root or `origin.txt` (review again with
`peer-prepare`/`peer-apply`). Without the isolation proof (older EA builds) the
exact-instance rule is unchanged.

### GOAT peers: more than one other MT5 (goatai#1885)

`policy.json` holds one reviewed peer, and reviewing another **replaces** it.
Every other GOAT-owned MT5 on this PC is a **GOAT peer** instead: it may run,
start, restart or close at any time without blocking this terminal. GOAT never
reads, closes, launches or writes to it, and it never shares this terminal's
batch folder (the isolation preflight still refuses at every start). It is
never part of a package binding, so adding or removing one never invalidates a
prepared batch, and it can be done while a batch runs.

- **Automatic:** every terminal with a GOAT installation receipt on this PC
  (`%LOCALAPPDATA%\GOAT Portfolio Desktop\suite\*\installation.json`) is a GOAT
  peer. Nothing to run: opening T3 no longer blocks Banker.
- **Explicit:** `& $goat demo --installation $receipt peer-add --terminal "<its terminal64.exe>" [--data-root "<its data folder>"]`
  previews the data folder, its `origin.txt` binding and the batch namespace
  hash the peer is held to. With the owner's yes, repeat it with
  `--confirm-reviewed`. The peer need not be running. The command uses the
  broker-verified scope (selected MT5 running, demo, Algo off) but not the
  terminal lock, so it works beside a running driver.
- `peer-remove --terminal "<exe>" --confirm-reviewed` stops exempting it (and
  excludes it from auto-recognition). `peer-list` (read-only) shows the
  reviewed peer, every GOAT peer with eligible or the reason not, and which
  running MT5 would block.
- **Owner STOP refuses `peer-add` and `peer-remove`.** `peer-list` still works.

A running terminal64.exe counts as a GOAT peer only when all of these hold:

- this lane runs V1.49 (isolated batch folders);
- its data folder has `MQL5` and an `origin.txt` naming its program folder (or it is a portable MT5's own folder);
- it overlaps none of this terminal's folders;
- it hashes to a different batch namespace;
- its `terminal64.exe` has a Valid Authenticode signature from MetaQuotes Ltd.;
- every record naming it (`peers.json`, receipts) gives the same data folder.

An MT5 live update (new bytes, same signer) is accepted, and the next start journals it as `peer_binary_changed` in `peer-roster.jsonl`. The reviewed `policy.json` peer keeps its strict executable-bytes rule.

**Files:** `peers.json` and the append-only `peer-roster.jsonl`, in the same `.studio-peer-policy` folder as `policy.json`. `policy.json`, its reviews and `peer-instances.jsonl` are never rewritten.

A seed hunt pauses between members: `batch-pause` writes `seeds/<id>/pause.json`,
the running member finishes and is kept, no new member starts and pending members
stay pending (never cancelled). `seed-resume` honours the pause; `batch-resume`
releases it (the marker is retained as `pause-released-<ms>.json`) and continues.

## Export qualification: what passed, and what was only kept

```powershell
& $goat demo --installation $receipt export-qualification --source "$common\GOAT\R5da875ff24f5"          # read-only
& $goat demo --installation $receipt export-qualification --source "$common\GOAT\R5da875ff24f5" --write  # + append a record
```

The EA keeps its best set even when nothing passed its export thresholds
(`SortAndTrimExports: Passing=0 Kept=1`, `Tester.mqh:715-716`). Every surface that
counts exports uses one judgement, `studio_export_qualification.qualify`, and each
kept set gets one stamp (`goat-export-qualification-v1`):

- `status`: `passed`, `below_threshold` or `unknown`. An unknown set never counts as passed.
- `thresholds`: `min_sr`/`min_arf` and their `source`. They come from the run's
  `export_settings.GOAT` (the file the EA read), or the job's frozen `export` block
  for `finish`. With no thresholds the set is `unknown` (`thresholds_unavailable`):
  the EA would have compared against 0.0.
- `checks[]`: per metric (`Profit`, `SR`, `ARF`): `value`, its `source` (`file_name`
  or `set_header`), `decimals`, `op`, `threshold`, `passed` (true, false or null),
  `margin` and `at_cutoff`.
- `missed`: the metrics it failed, or `at_cutoff`, `thresholds_unavailable`,
  `metrics_unavailable`, `header_disagrees` or `log_crosscheck_mismatch`.
- `ea_native_passed`: the EA's own decision, reproduced exactly.
- `selection`: `passed_gate`, `best_of_failed_search` or `unknown`.
- `set_sha256`: what the desktop matches.

**Cut-off fidelity.** The EA compares the **rounded file-name values**, not the full
double. It prints `_SR=` with 2 decimals and `_ARF=` with 3 (`GOAT V1.49.mq5:4244-4245`),
reads them back with `FetchMetric` (`Tester.mqh:787-817`, into `expArr[n].sr/.arf` at
`GOAT V1.49.mq5:4751-4752`), and tests `arf>=MinARF && sr>=MinSR` (`:4566`). So
`ea_native_passed` matches the log's "N passed thresholds". `status` is stricter:

1. A value within half a unit of its printed precision of the threshold (file name:
   SR 0.005, ARF 0.0005) could lie on either side. The SET header's
   `; PF=… SR=x.xxx ARF=x.xxx` line (`:4056`, 3 decimals) decides it.
2. If the header is also within its half unit (0.0005), or it disagrees with the
   file name, the set is `unknown`, never `passed`.

For example, file SR 2.50 with header SR 2.495 is `below_threshold`; header 2.505
passes; header 2.500 is `unknown`. ARF has no extra header precision, so a file ARF
of 0.200 against 0.2 is `unknown`.

**Back-fill.** `export-qualification` stamps every kept set of each `--source` run
folder and cross-checks the stamps against the passing sets the EA's own `log.GOAT`
says it **kept**, per export cycle:

- the `SortAndTrimExports: Total= Passing= Kept=` line after that cycle's
  "Export sequence complete" line (with `AdjustLots`, the trim after the "Export
  Adjustment" line);
- for a cycle with one stored set or none, which logs no trim line
  (`Tester.mqh:694`, `GOAT V1.49.mq5:4602`), the cycle's own "N passed thresholds"
  count (0 or 1). "Stored" is the line's "profitable" count, exactly the sets
  `RunAndStoreSet` kept. A cycle that stored 2 or more but logged no trim line is
  `trim_missing`: its kept passes are unknown and the run is a mismatch.

The "passed thresholds" count of a trimmed cycle counts passes before trimming, so
it never decides. The check compares the summed sets and the members with any
pass; `log_bases` says how many cycles used each rule. If the log disagrees or is
unreadable, every `passed` in that run becomes `unknown` (`log_crosscheck_mismatch`).
A mismatch can also mean the EA kept a non-passer over a passer (it keeps the top
`Passing=` sets by ARF × SR); the log cannot attribute that, so it also fails
closed.

The reply passes the held-out guard like every other demo_agent reply. Each
`--source` is resolved to an absolute, canonical path first, because the guard
recognises an export by its absolute `.set` path. A locked export loses its
`qualification` and its metric tokens; its run loses `counts` and `log_crosscheck`,
and the reply loses its totals. Without a readable `--installation` nothing is
printed. `--write` appends a new
`<controller state>/export-qualification/<run>/<UTC>.json` (exclusive create).
Receipts and earlier records are never rewritten; a correction is a newer record.
Each entry in `runs[].stamps[]` is `{set_path, set_name, set_sha256, member, symbol,
qualification}`.

Re-derived on this PC on 2026-10-05 (read only; one g6 batch was still running):

| Run | Kept: sets / members | Passed: sets / members | Below threshold: sets |
|---|---|---|---|
| g6 (9 batches) | 339 / 306 | 132 / 99 | 207 |
| bd28-persistent | 57 / 56 | 8 / 7 | 49 |

The old count reported every kept member as qualifying (306 and 56). Every log
cross-check matched. No kept set sat at the cut-off.

### Below-threshold sets: what a portfolio needs before it counts as proven (preregistered)

Below-threshold sets stay visible and sift-eligible, labelled with what they missed
("SR 2.91 passes · ARF 0.12 < 0.2 misses"). They are the best of a **failed**
search, so they cannot ride on the evidence that chose them.

Saving a portfolio and deploying it to a demo are allowed. Their receipts list the
member as `unproven_members: [{set_sha256, missed, selection: 'best_of_failed_search'}]`.
Two conditions, (a) and (b), are a **hard** requirement only on a real-money deploy
path and on any promotion of a portfolio to "proven". Neither path exists in the app
today; the rule is written now so it cannot be tuned to a result later.

**(a) Unseen weeks.** The window starts after the SET's selection, i.e. after its
FOOS end or export date. One window rule covers all three sources:

- at least **20 weekdays** (4 weeks): a month, so one good week cannot carry it;
- at least **30 trades**: the library's `minWindowTrades`, below which a window is
  "too few to judge". g6 kept sets trade a median 8.6 a week (p25 4.8), so this
  usually takes 4–6 weeks;
- **net > 0** and **PF ≥ 1.3**. The g6 below-threshold sets reached a median PF of
  only 1.25 (p25 1.11) on the very data that selected them; passers reached 2.00
  (p25 1.79). Unseen weeks must beat the failed group's own in-sample median.
  Catch-up's `failed_pf` 0.8 is a failure floor, not a pass bar.

The window can come from any of three sources:

1. **Catch-up:** a comparable `goat-catchup-verdict-v2` `held_up`, run with
   `verdict_rules: {min_trades: 30}`. Its new weeks must meet the window rule, from
   `signals.weekdays`, `signals.trades`, `signals.pf` and net.
2. **holdup-test v1** (GOAT-EA#161): `relation: after_selection` (role catch-up L3,
   clean), `evidence` not null (MT5 history quality ≥ 90%), `Model` 4 (real ticks, as
   the EA's own export pass), and the export's deposit, currency and leverage. MT5's
   own report must meet the window rule.
3. **Demo forward:** only the member's own deals, opened after both its deploy and
   its export date, on a broker-verified demo account, meeting the window rule.

**(b) Diversification benefit, measured out of sample.** On the **same** unseen
window as (a), never on the selection windows, the equal-weight portfolio's
profit ÷ max drawdown with the member must be at least **1.10×** the ratio without it.
If the ratio without it is ≤ 0, the ratio with it must be above 0.

- It is the builder's own ranking metric.
- 10%: one member in a 3–8 member equal-weight basket carries 11–25% of the
  weight, so a smaller change on a 4-week window is re-weighting noise.
- A correlation ceiling was rejected. Daily-P&L ρ over 20 weekdays has a standard
  error near 0.22, too wide to separate 0.3 from 0.7, and a low-ρ member that loses
  money still hurts.

## Gate calibration: qualification gates from our own evidence

The export gates (`MinScore 60`, `MinSR 2.5`, `MinARF 0.2`, `SetsToExport 2`,
`TargetDD 100`) and the EA back-row filter (in-sample profit > 0.001, >= 50
trades) were fixed by hand. `gate-recommend` replaces "fixed" with "chosen per run
from what our past exports actually did". It is read only: it opens the export
folders under Common Files for reading and writes nothing except `--output`. It
needs no terminal, lock, session or broker.

`--installation` is read, for the held-out guard only. `gate-recommend` and
`gate-stamp` aggregate every export on this PC, and their numbers cannot be
attributed to one strategy or window. So both refuse before reading evidence or
writing a file when:

- the installation is unreadable, or the registry cannot be verified
  (`HELDOUT_REGISTRY_UNAVAILABLE`);
- any held-out lock is active (`HELDOUT_LOCKED_WINDOW`, with `locked_windows`).

Their replies also pass `guard_output`. `guard_output` itself fails closed: when its
context cannot be built, it redacts every derived value instead of returning the
reply unchanged.

```powershell
& $py $tool --installation $install gate-recommend --target forward --min-survival 0.8
& $py $tool --installation $install gate-recommend --target post --min-survival 0.75 --runs 'Rad870a22d237,Re7e282f93d41' --output 'C:/gates/rec.json'
& $py $tool --installation $install gate-recommend --target held_up --verdicts 'C:/catchup/verdicts' --output 'C:/gates/held.json'
& $py $tool --installation $install gate-stamp --plan 'C:/plan.json' --recommendation 'C:/gates/held.json' --output 'C:/plan-gated.json'
```

How it decides (`studio_gate_calibration.py`, schema `goat-gate-calibration-v2`):

- Every finished sequence capture in `<run>/deploy` and `<run>/exports` is split by
  server date into back OOS `[BackOOSDate, FromDate)`, in-sample `[FromDate,
  ForwardDate)`, forward `[ForwardDate, ToDate)` and post `[ToDate, end of the
  export run]`, from `deals.csv` (trades = positions opened in the window; PF over
  only those positions, as in `goat-catchup-verdict-v2`) and the exported equity
  CSV (net, drawdown, recovery, daily Sharpe, monthly ARF-style ratio). The
  optimizer's own in-sample columns and Score come from the member's `UniqueRows`
  XML. A capture that hit its row limit keeps its equity numbers; its trades and PF
  after the cut are unknown, never partial. Only byte-identical evidence (same
  inputs AND same deals and equity files) collapses across runs.
- Survival: `forward`/`post` need at least `--min-trades` (default 5) positions in
  the window and then net > 0 (post also >= 10 weekdays); fewer trades = not
  judged. `held_up` uses catch-up verdicts matched by the exported SET's SHA-256,
  accepted only as schema `goat-catchup-verdict-v2`, `comparability.comparable`
  true and default rules (`rules.id` v2, nothing `overridden`); for one SET the
  newest evidence end wins. `too_few_trades`/`not_comparable` are not judged.
- **Only `held_up` is actionable.** Forward and post lie inside the export run the
  EA already judged, so they are diagnostics: they report what would validate but
  never move a plan field, and `gate-stamp` refuses them.
- Leakage rule: a predictor may only use data the target window could not have
  influenced. Forward: in-sample, back OOS and the optimizer's in-sample columns;
  never the forward window, the Score (built from in-sample and forward results)
  or the file-name metrics (measured over the whole export run). Post also allows
  forward and Score; held_up also allows the file-name metrics, so `MinScore`,
  `MinSR` and `MinARF` can only move on held_up; every other gate is a portfolio
  qualification gate. Plan fields never drop below the controller floors.
- Selection is paid for. Outcomes are averaged per optimization member first (a
  member's sets are near copies), and runs (`--cluster run`, or the stricter
  `period`) are the independent unit. A metric is a candidate only when survivors
  beat failures **inside the same run** (run-bootstrap AUC range above 0.5), so a
  difference between runs cannot fake a signal. A threshold is chosen (loosest,
  most sets kept) only where a **simultaneous** lower band over the whole
  threshold grid (sup-t over a run bootstrap, also capped by the member Wilson
  bound) clears `--min-survival`, with `--min-sets` sets from `--min-members`
  members in at least two runs.
- **Leave one run out:** the whole selection is repeated without each run and the
  gate it picks is judged on that run. The gate validates only when the pooled
  held-out lower bound (the lowest of a cluster t interval, Wilson and a bootstrap
  over held-out runs) clears the target, at least `--min-clusters` (default 4)
  runs were judged, and no run with enough members clearly misses (its Wilson
  upper bound under the target). The recommended threshold is the strictest one any
  fold chose for that metric. If that threshold does not clear the full-data band,
  the result is `fallback_not_validated` (fail closed); the looser full-data
  threshold is never stamped in its place.
- Status: `validated`, `defaults_already_meet_target`,
  `fallback_no_qualifying_gate`, `fallback_not_validated` or
  `fallback_thin_evidence` (fewer than `--min-sets` judged sets, `--min-members`
  members or `--min-clusters` runs). Every fallback keeps today's values and says
  why in `summary`. Symbol classes and run designs are calibrated alone with the
  same procedure and only get their own gate when they validate.
- Fillers (sets the EA exported below its run's own MinSR/MinARF to fill
  `SetsToExport`) are labelled `filler`, never excluded. `fillers` in the result
  compares passed and filler sets inside each run and symbol on held_up only
  (Mantel-Haenszel risk difference, run bootstrap); the pooled gap is confounded by
  construction.
- Simulation (`CoverageSimulationTests`): when a gate validates, its true survival
  clears the target at the nominal 97.5% one-sided rate, also with run-level shocks.
- **"Validated" is per draw, not per gate.** Across evidence draws, few validate a
  gate that really misses the target. Among the gates that do validate, a larger
  share is still slightly under it (correlated proxies, judged on fresh periods).
  `scripts/gate_calibration_coverage.py` measures both; the numbers live in
  `VALIDATED_GATE_MISS` and travel as `validation_meaning` in every recommendation,
  summary, `<plan>.gates.json` stamp and report. A miss over-tightens, never loosens.
- `evidence_digest` is a SHA-256 over the judged sets, outcomes and features, so
  the same evidence gives the same digest in any order.

`gate-stamp` writes a NEW plan (never the source, never an existing file) and
**only tightens**: it accepts only a `held_up` recommendation; each recommended
field becomes `max(plan value, recommended value)`, every other field keeps the
plan's own value, and when nothing tightens (or the recommendation is a fallback)
the plan is copied byte for byte. The new plan is validated by the same
`validate_export` as preparation; `<plan>.gates.json` holds
`gates={values (with export_applied), method, evidence_digest, generated_at,
plan_sha256, source_plan_sha256}`. The stamp is a sidecar because `prepare-batch`
accepts only `schema_version`, `export` and `members`; the plan itself stays a
normal plan. Pass `--generated-at` for a byte-identical repeat. `apply_qualify`
checks one exported set against the stamped qualification gates (a missing number
fails).

`scripts/gate_calibration_report.py --out-dir <new folder>` writes the full
evidence report (`report.md`, `report.json`) for several targets;
`scripts/test_gate_calibration_mutations.py` checks that the guards above are
each covered by a failing test.

## Pairing code on the demo lane

`goat.exe studio pairing-code --build-id <id>` is a read and runs on a `demo_direct`
installation too. There it reads only the code the EA shares in
`Common\Files\GOAT\activation-code-<data folder>.json` (EA builds that share their pending code), after the same fresh
broker demo proof, inert check (Algo Trading off, no positions or orders), protected-login refusal
and exact build/login/server match. It never registers the setup-mailbox pairing capability on the
demo lane; when no shared code is there it answers `no_pending_pairing` or `no_native_answer` with
one plain next step. Approval stays with GOAT desktop.

## Seed Farming on the demo lane

On a `demo_direct` installation the raw `goat.exe studio seed-*` mutations
refuse with `Demo mutation requires the broker-verified agent tool`. Use these
tools instead. They drive the same `SeedRunner` and the same frozen plan format
as [SEED-WORKFLOW.md](SEED-WORKFLOW.md); nothing about seed evidence changes.
Read-only studio commands still run there with the raw CLI: `validate-set`,
`benchmark-report`, `research-status`, `onboarding-status`, `state`, `discover`
and the other reads. So do the SET builders `starter-set` and `build-set`
(goatai#1885): they read the source SET and write only new, create-only files at
the `--output` path outside the catalog (the SET, its `.md` notes and its
`.build.json` or `.starter.json` receipt), before the controller opens
`studio.sqlite`, so they have no store, queue, terminal or mailbox effect. A
demo-only agent builds its SETs with `goat.exe studio build-set`; there is no
`demo build-set` twin. A `reconcile_required` seed or catch-up is settled with `seed-reconcile --batch-id <id>` (`catchup-reconcile`) under the broker check; see [SEED-WORKFLOW.md](SEED-WORKFLOW.md).

```powershell
& $py $tool --installation $install seed-validate --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-prepare --batch-id 'seed-weekend-01' --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-start --batch-id 'seed-weekend-01' --max-seconds 3600    # detached driver
& $py $tool --installation $install seed-resume --batch-id 'seed-weekend-01' --max-seconds 3600   # after the driver returned
& $py $tool --installation $install seed-status --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-cancel --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-report --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-promote --batch-id 'seed-weekend-01' --candidate '<candidate_sha256>' --name 'My EURUSD discovery'
```

`seed-validate` checks the whole plan and every SET it names (tester rules,
frame target, exact axis precision, duplicates, size limits) and writes nothing:
no SET, startup INI or seed folder, and no terminal, process or broker access.
Only the validation itself is appended to `actions.jsonl`.

`seed-promote` (`--neighborhood` 1..5, default 1; add `--member <alias>` when
the candidate appears in several members) writes `fixed.set` and
`robustness.set` for one verified candidate under the same checks as
`seed-report`, with no terminal effect, and appends `written`, or `retained`
when a repeat returns the existing receipt. The robustness SET is a local
stability check around the candidate; only the forward window is out-of-sample.

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

The detached driver supervises the run for its budget. After it returns with
`driver_budget_exhausted`, nothing supervises the member: its job timeout, a human
TAKE and the disk check are acted on only by the next `seed-resume`. `--max-seconds`
is the budget for that one driver, not an autonomous hard stop, and no background
service enforces anything between drivers.
Owner STOP is a separate explicit path: `stop` works at any time. Keep calling
`seed-resume` until the batch reports `completed` or `stopped`, or holds
`reconcile_required` for inspection.

**`seed-start` and `seed-resume` detach** (also `catchup-*` and `holdup-*`).

Before PR C, these commands drove inside the calling process, and MT5 ran as that
process's child. A tool that timed out and killed its process tree killed MT5
mid-member (T2 `seedhunt-t2-4-b41`, 2026-10-05). Now the caller only checks and
hands over; the drive runs in a detached driver.

1. **The caller checks.** `seed-start` still takes its broker check and writes its
   start record in the caller, so a refusal (owner STOP, TAKE, wrong account, disk,
   another driver) comes back at once. `seed-resume` checks that the batch has
   started and has its start record.
2. **The drive is handed over.** The drive goes to the same Windows demand-task host
   as `run-batch` (`studio_durable_driver`), outside the caller's job and process tree,
   for up to `--max-seconds` (1..3600).
3. **The reply** is `driver_starting` with the worker record. The record lives in
   `demo-agent/lane-workers/<kind>-<id>.json`, with its nonce, pid and log.
4. **The driver re-runs every check** before it drives, exactly like the foreground
   command. When it ends, it records `returned` (with `result_status`) or `failed`
   (with the refusal) in that worker record.
5. **Poll.** `seed-status` shows the run and its `driver` (record plus `alive`). Once
   the driver has `returned` and the run is neither `completed` nor `stopped`, call
   `seed-resume` again. Repeating a start or resume while the driver lives returns
   `already_supervising`. Any other seed, catch-up or hold-up work refuses while one
   detached driver owns the terminal. Only the `<kind>-<id>.json` records count: the
   durable host's `<kind>-<id>-<nonce>.launch|started|finished.json` receipts beside
   them are never read as drivers, and a driver never refuses its own record (beta.23
   read its own started receipt and refused itself, goatai#1885).

`--foreground` keeps the old in-process drive for at most 120 s. A longer foreground
budget is refused, because it would die with the calling tool.

If a start or resume answers that the detached driver launch could not be confirmed, the
`run-batch` rule above applies. Never start another driver by hand. `seed-status`
shows the `driver` once its task starts, or `launch_never_started: true` once Windows
proves the task never ran. Only then does the same `seed-start` (or `seed-resume`) run
again: under the terminal lock it removes the old task, confirms it is gone, logs
`detached_driver`/`launch_never_started` and reserves a fresh nonce. The detached driver
waits up to 120 s for the terminal lock; if it stays busy, the worker record says so
(`failed`).

**Don't run `demo launch-terminal` during a seed, catch-up or hold-up batch.** The
driver owns the MT5 close and reopen between members, and it reopens MT5 on the GOAT
profile after the last one. An MT5 started by anyone else between members makes the
batch `reconcile_required` ("Unowned selected-terminal process appeared between seed
members"). Close that MT5. With MT5 closed, `seed-reconcile` or `seed-resume` re-inspects
and settles the doubt under the terminal lock. A `seed-status` read never settles it.
- **It settles only** when nothing anywhere runs a member.
- **It settles as a stop, only in the demo lane.** The hunt becomes `stopped` with `stopped_reason` `unowned_settled`. The runner journals it in `actions.jsonl` (`seed_resume` or `seed_reconcile` / `unowned_settled`) before it saves the state, and the next `seed-resume` re-activates the pending members under the start-grade check: MT5 open on the GOAT monitor, a fresh broker readback, STOP/TAKE and idle.
- **Stray output fails that member.** A pending member that already has output (the unowned MT5 may have run it) becomes `failed` ("Output present before its start") and is never collected.
- **While the MT5 stays open**, the doubt stays, and `seed-reconcile` names this fix.

**A member whose launch was never confirmed.** If the identity wait runs out after a
member launch, the member becomes `reconcile_required` ("Terminal startup identity not
observed") while its MT5 may well be running the tester. Don't close that MT5. The next
`seed-resume` or `seed-reconcile` (never `seed-status`) adopts it as that member's own
launch, under the terminal lock, only when all of this is read true now:
- exactly one member is uncertain, its start was sent but never confirmed, and there is no batch-level doubt;
- the selected MT5 runs this installation's `terminal64.exe` and was created inside that member's launch window (from 2 s before its start record);
- its command line names that member's own `/config:` INI, and it is the only terminal64 anywhere that does;
- the INI is still the bytes the batch wrote.

Adoption records `reidentified` on the member and a `seed_resume` (or `seed_reconcile`)
`reidentified` row in `actions.jsonl`; nothing is closed, launched or re-run. The driver
then collects the member when MT5 finishes and continues the pending members. Otherwise
the member stays `reconcile_required`, and its `reidentify.reason` says which proof failed.

A failed, timed-out or output-less member fails only itself, with a plain `error`.
The batch continues, unless 3 attempted members in a row failed or at least half of
4 or more attempted members failed. It then stops with `stopped_reason` (see
[SEED-WORKFLOW.md](SEED-WORKFLOW.md#run-resume-and-cancel)). After fixing the cause,
`seed-resume` re-activates a stopped batch whose remaining members are pending. It
uses the same fresh broker, owner, idle, STOP/TAKE, disk and free-terminal checks as
`seed-start`, and the original start record must still match. Completed and failed
members are never re-run. A `cancelled` member still stops the batch for good.
STOP is never cleared by these tools, and `clear-stop` refuses until the seed
run has reached a verified terminal state. Real native qualification of this
lane is still pending; every seed result keeps `native_launch_qualified: false`.

## OOS catch-up on the demo lane

Bring kept exports to one evidence end before building a portfolio (rules and
verdicts: [README.md](README.md#evidence-end-and-oos-catch-up)). The read-only
tools need no broker; the rest use the seed lane's checks, start record
(`demo-agent/catchup-starts/<id>.json`), slot, STOP, pause and slices unchanged.

```powershell
& $py $tool --installation $install evidence-end                       # auto = latest closed Friday
& $py $tool --installation $install evidence-scan --source 'C:/.../Common/Files/GOAT/Re7e282f93d41' --source 'C:/.../GOAT/Rad870a22d237'
& $py $tool --installation $install catchup-validate --plan 'C:/catchup-plan.json'
& $py $tool --installation $install catchup-prepare --catchup-id 'catchup-20261002' --plan 'C:/catchup-plan.json'
& $py $tool --installation $install catchup-start --catchup-id 'catchup-20261002' --max-seconds 3600
& $py $tool --installation $install catchup-resume --catchup-id 'catchup-20261002' --max-seconds 3600
& $py $tool --installation $install catchup-report --catchup-id 'catchup-20261002'
```

The plan is `{"schema_version":1,"evidence_end":"auto","sets":[<absolute .set
paths of the behind exports>],"job_timeout_seconds":1800}`. A catch-up closes the
selected MT5 and relaunches it once per member like a seed run; tell the owner
first, then start it (that sentence replaces waiting for a yes). `batch-pause --batch-id <catchup id>` pauses between members and
`batch-resume` continues. `research-status` shows it as an OOS catch-up.

Live decisions (gate check, basket FOOS test on add or swap, manual re-optimize,
hard-stop replacement) use `"evidence_end":"auto_day"`: the latest closed trading day,
resolved once at prepare, recorded in the manifest and stamped as `evidenceEnd` on every
result and `oos_rule`. Every other run of the same decision passes that explicit date.
Catch-up only: batch exports and `oos_windows` stay Friday-anchored and refuse `auto_day`.
Catch-up days after the export Friday count toward the FOOS 30-trade floor.
Every stamp pairs the nominal `evidenceEnd` with `evidenceEndEffective` (the last day the test
covered: MT5 ToDate is exclusive) and `evidenceEndMode` (`auto`, `auto_day`, `explicit`,
`explicit_day`, `legacy_explicit`, `legacy_thursday_cut`, `oos_windows`). `legacy_thursday_cut`
means an older EA build's exports cover only through Thursday: catch them up to the Friday.

## OOS window formula on the demo lane (BOOS, SAMPLE, FWD, FOOS from O)

Banker batches, demo Algo research and seed hunts derive every date from O and the
export Friday (`goat-oos-windows-v1`; full rule, rounding and worked example:
[docs/operations/OOS-WINDOW-FORMULA.md](../docs/operations/OOS-WINDOW-FORMULA.md)).
O = SAMPLE + FWD in whole weeks (a month = 13/3 weeks). BOOS = 1/2 O before SAMPLE,
SAMPLE = 2/3 O, FWD = 1/3 O, FOOS = 1/4 O ending at the export Friday (default
`auto`, the latest closed Friday). BOOS, FWD and FOOS round up; SAMPLE takes the rest.

- Plan: add `"oos_windows":{"optimization_months":12}` (or `optimization_weeks`,
  optional `export_friday`) to a batch or seed plan and leave the dates out; dates
  you do give must equal the formula. O = 12 months at export Friday 2026-10-02 gives
  `BackOOSDate=2025.01.04`, `FromDate=2025.07.05`, `ForwardDate=2026.02.28`,
  `ToDate=2026.07.04`, `EvidenceEnd=2026.07.04`; FOOS is 2026-07-04 to 2026-10-02.
  Seed jobs read SAMPLE only (`ToDate` = `ForwardDate`, `ForwardMode=0`).
- FOOS is held out with existing EA inputs: the batch export stops at the optimization
  end (`EvidenceEnd` = `ToDate`), so the EA's export pass test and trim never read
  FOOS. It needs an FU35+ EA (`goat-evidence-end-v1`); older builds refuse the formula.
- After the batch, run the FOOS replay: a catch-up whose `evidence_end` is the export
  Friday (`batch-status` → `oos_windows.foos_replay`). `catchup-report` rows carry
  `oos_rule`: `pass`, `fail`, `not_eligible_yet`, `no_data` or `not_measured`\r
  (`not_applicable` for non-formula exports). Catch-up weeks after the export\r
  Friday count toward FOOS.
- The rule per OOS window: at least 30 trades (fewer = `not_eligible_yet`; never
  shorten a window or change O to reach it), then PF ≥ 1.0 and DD ≤ 1.5 × SAMPLE DD.
  PF ≥ 1.0 is net of all costs ≥ 0; DD is an equity drawdown. `no_data` and\r
  `not_measured` are never a pass. Every `oos_rule` has `boosContaminatedBy: "ea_trim"`:
  the EA's export trim partly selects on BOOS, so show "BOOS: partial" and lead with FOOS.
  This evaluator is the source of truth; the\r
  desktop sift matches it through `controller/fixtures/oos-holdout-gate-cases.json`.\r
  It sits next
  to the export qualification stamp and the catch-up verdict; neither changed.
- Demo after export continues FOOS but does not scale with O: at least 4 weeks AND at
  least 30 trades, decision due by 6 weeks; under 30 trades at 6 weeks is "too slow to
  judge here" (never promote on thin data); M1 and other high-frequency sets are judged
  mainly on execution parity (live vs backtest, same weeks, real spread, slippage and
  commission); PF ≥ 1.0 at the portfolio level. Not automated yet.
- Exact pre-FOOS metrics: each kept set in `finish` → `reports` → `exports.files[]`
  carries `window_metrics` with `preFoos` (export start to the optimization end),
  `selectionWindow` (SAMPLE + FWD) and `fullExport`, each `{from, to, days, profit,`r
  `pf, pfNote, trades, tradeSource, maxDd, ddPct, arf, sharpe, recoveryFactor, equityNet}`,
  computed by the controller from the equity CSV and capture deals with the same PF/DD
  definitions (`sharpe` is daily-equity based, not the header SR).
- On #1885 and to Vince: give the windows with dates, call FOOS "held out" (never a
  ranking reason), and say "not eligible yet: N of 30 FOOS trades" rather than failed.

## Hold-up test on the demo lane (Prove)

A hold-up test answers "does this exact SET hold on weeks it never saw?". It runs
one frozen SET as one MT5 tester pass (no optimization, no forward window) over a
window you choose, and reads the result from **MT5's own report**, never from EA
output. It writes no export, promotion, library or ledger entry. It uses the seed
lane's checks, start record (`demo-agent/holdup-starts/<id>.json`), slot, STOP,
pause, slices and member-failure rules unchanged, and is the **owner demo lane only**
in v1 (goatai#1885, Claude-Mac 5989126739).

```powershell
& $py $tool --installation $install holdup-validate --plan 'C:/holdup-plan.json'
& $py $tool --installation $install holdup-prepare --holdup-id 'r3-eagle-usdjpy-2023' --plan 'C:/holdup-plan.json'
& $py $tool --installation $install holdup-start --holdup-id 'r3-eagle-usdjpy-2023' --max-seconds 3600
& $py $tool --installation $install holdup-resume --holdup-id 'r3-eagle-usdjpy-2023' --max-seconds 3600
& $py $tool --installation $install holdup-report --holdup-id 'r3-eagle-usdjpy-2023'
```

The plan (1..50 tests):

```json
{"schema_version": 1, "job_timeout_seconds": 3600,
 "tests": [{"set_path": "C:\\...\\GOAT V1.49 USDJPY,M1_Trds=....set", "set_sha256": "<sha256 of that file>",
            "window": {"start": "2023-01-02", "end": "2025-01-06", "split": "2024-07-01"},
            "tester": {"Model": 1, "ExecutionMode": 0, "Deposit": 10000, "Currency": "USD", "Leverage": "1:100"},
            "symbol": "USDJPY", "period": "M1", "strategy_ref": {"strategy_key": "...", "...": "..."}}]}
```

- **`set_sha256` is required.** Prepare refuses a file whose bytes differ. The frozen
  copy changes only `EA_Desc` (to the test's alias, with no `@{mode=...}`), so the
  EA runs a plain test.
- **The window is broker days, half-open `[start, end)`.** `end: "auto"` is the day
  after the last closed Friday; a later end is refused. The optional `split`
  reports the deals before and after it as two segments.
- **Symbol and period** come from an export's file name or a seed promotion's
  `promotion.json`. Otherwise give them in the plan; if two sources disagree, it
  refuses. `tester` is explicit: the price model is yours to choose, and the
  result records its `model_tag`.
- **Refused before any effect:**
  - a SET that still searches an input (freeze one candidate first);
  - `RISK_NOT_CHOSEN` and the risk-per-sequence rule;
  - `Mode_Operation` other than 9;
  - a GOAT starter;
  - AI bias on (`HOLDUP_AI_BIAS_ON`; only `Mode_Bias=Bias_Disabled`);
  - a random execution delay;
  - `heldout_reveal` (`HELDOUT_REVEAL_NOT_IN_V1`: reveals wait for the native T3 proof);
  - any test that overlaps an active held-out lock. This is checked again before each launch.
- **Result checks.** A test completes only when MT5's report passes every check: its
  inputs equal the frozen SET's values one by one; Expert, symbol, period, dates,
  deposit, currency and leverage match; every deal's balance follows from the one
  before; the deals add up to the totals row and Total Net Profit; the last
  balance is the deposit plus the net; and the deal counts match Total Deals and
  Total Trades. Otherwise that test fails with the reason, and the others continue.
  The report must be in English.
- **What a completed test keeps:** `<alias>.result.json` (`goat-holdup-result-v1`), a
  copy of MT5's report and `<alias>.deals.json`. The result holds:
  - `metrics`: MT5's figures, with drawdown from MT5's equity and balance, never the EA CSV;
  - `per_week` and `daily` realised P/L, and the `segments`;
  - `relation`: whether the window is before, after or overlapping the SET's own
    selection windows (export header or seed window), or unknown;
  - `evidence`: the ledger hint for `evidence.record`. After maps to catch-up L3,
    before to back-oos L2, overlapping to in-sample L0, and unknown to back-oos L2
    with contamination `unknown`, which counts as contaminated. Below 90 % MT5
    history quality, `evidence` is `null`, with `evidence_reason`.
- **`trial-journal` counts every dispatched hold-up test as a peek** (kind `single-pass`),
  so re-running a winner until it looks good is visible. `research-queue` shows it as
  Prove (kind `holdup`, results `profitable`).
- MT5 closes and relaunches once per test, like a seed run, so tell the owner first,
  then start it (that sentence replaces waiting for a yes).
  `native_launch_qualified: false` until the T3 proof.

This is the first Tier A slice. Terminal discovery, compile, SET editing,
report parsing and exports will be separate tools wrapping existing MT5/EA
features. Native smoke evidence is required before calling this lane qualified.
