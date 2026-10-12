# Deploy timing profile (`goat-deploy-timing-v1`) and resume robustness: the controller contract (remote deploy v0)

Status: **v0, beta.38**.

- The design is goatai `docs/remote-deploy-design.md`: section 3.1 (controller), section 5 (the v0 cut) and the trap
  map in section 2.3.
- Claude-Mac approved it for beta.38 on goatai#2350 (comment 6129098775).
- The reference validator is goatai `tools/remote-deploy/deploy_timing_profile.cjs`. The Python port is
  `studio_deploy_timing.py`, and the two must agree exactly.
- The shared goldens are in `deploy-timing-fixtures/`. `profile-cases.json` holds 35 cases, and the `.cjs` reference
  gives the same verdict on every one of them.

## 1. The parameter

`studio deploy-load`, `deploy-stop` and `close-terminal` take `--timing-profile <id|file>`.

- **No flag.** The controller uses today's module constants, and the deploy is unchanged byte for byte. The golden
  `deploy-timing-fixtures/desktop-load-golden.json` was captured on the controller before this change. It records
  every request timeout, sleep, close call, launch argument, staged file and journal value.
- **A built-in id.** `desktop` (the same values as having no flag) or `vps-cold-36`. A built-in id wins over a file
  of the same name.
- **A file.** One JSON object of at most 16 KB. Duplicate keys, `NaN` and `Infinity` are refused. A file may not reuse
  a built-in id with different waits (`TIMING_BUILTIN_ID_MISMATCH`).
- **Validation.** The profile is checked before anything is opened, written or launched. An unknown id or a missing
  file is refused as `TIMING_PROFILE_NOT_FOUND`.

A host (or the app) bounds its `deploy-load` runner with `runner_timeout_ms(profile)`, the reference's
`runnerTimeoutMs`: 15 minutes for `desktop` and 26.5 minutes for `vps-cold-36`.

| Field | Bounds (s) | Used by | `desktop` | `vps-cold-36` |
|---|---|---|---|---|
| `closeWaitSeconds` | 10-600 | `close_terminal(wait_seconds=)` for the deploy's own close, its unwind, `deploy-stop` and `close-terminal` | 30 | 180 |
| `launchObserveSeconds` | 5-120 | the resume re-check's wait to see the journaled MT5 (section 3) | 30 | 30 |
| `dashboardWaitSeconds` | 60-1200 | the status poll after registration, and the status read on resume | 180 | 480 |
| `childStartWaitSeconds` | 60-1200 | the `link_children` window | 240 | 480 |
| `linkRequestSeconds` | 1-90 | one `link_children` request (`portfolio_request` caps any request at 90 s) | 20 | 85 |
| `ackWaitSeconds` | 30-600 | the exposure-policy acknowledgement poll | 90 | 90 |
| `auditWaitSeconds` | 30-600 | the settings audit poll | 90 | 90 |

`vps-cold-36` carries its evidence from the Exp 03 VPS on 2026-10-12, measured on 36 charts:

- a close of 79 s;
- a cold start of 190 s;
- a cold link of 88 s.

### Refusal codes

Every code below comes from the reference, in the reference's order of checks. A refusal is a `Refusal` (so the
CLI's `code` is `REFUSED` and its `refusal_code` is the code).

| Code | When |
|---|---|
| `TIMING_INVALID` | The profile is not an object, has an unknown field, or has a bad id. Or a wait is not an integer number of seconds (a JSON `true` is not, but `30.0` is). Or `evidence` is missing, or is neither `null` nor an object. Or an evidence measure is not a positive number. |
| `TIMING_SCHEMA` | `schema` is not `goat-deploy-timing-v1`. |
| `TIMING_OUT_OF_RANGE` | A wait is outside its bounds. |
| `TIMING_LINK_REQUEST_OVER_CAP` | `linkRequestSeconds` is above 90 (trap T3). |
| `TIMING_LINK_REQUEST_TOO_LONG` | `linkRequestSeconds` is not shorter than `childStartWaitSeconds`. |
| `TIMING_BELOW_EVIDENCE` | A wait is under 1.5 times its measured evidence: `closeSeconds` for the close wait, `coldStartSeconds` for the dashboard wait, `coldLinkSeconds` for the child start wait. |
| `TIMING_OVER_REGISTRATION` | The whole budget is not shorter than the 4 h registration. With today's bounds this cannot happen; the check is kept for the day the bounds change. |

### The record

The journal (`timing_profile`), the CLI result of `close-terminal` (`timing_profile`, only when the flag is given) and
the journal of `deploy-stop` (`stop_timing_profile`) record the profile like this:

```json
{"id": "vps-cold-36", "sha256": "5a665f0f...", "source": "builtin | file:<sha256 of the file bytes> | parameter | default",
 "values": {"closeWaitSeconds": 180, "...": 0}}
```

- **`sha256`.** It is computed over the canonical JSON of `{schema, the seven waits}`: sorted keys, no whitespace,
  integers. It names the waits, not the profile's name or its evidence.
- **The goldens.** `desktop` is `54519ff3a2bb795e3ed7534c56b2f29aed0bbeb8bb0ed8f987ba93684be2b8ea` and `vps-cold-36`
  is `5a665f0fd54e1ae898fb602a7f89a19f74186a0ab9d02debb2dd1e4759aabfe3`. Both canonical strings are in
  `profile-cases.json`.
- **A resume with a different profile.** The new profile becomes `timing_profile`, and the earlier one is kept in
  `earlier_timing_profiles`.

### Observed durations (goatai#2350 6130033743)

Each operation journals how long each phase actually took, next to `timing_profile`, so that a per-host profile can
later be derived from real deploys (open question M4, option ii). The durations are in seconds, rounded to the
millisecond, and measured on the same monotonic clock the waits use: `deploy-load`'s `clock`, and in
`close_terminal` the clock of its exit wait.

| Key in `observed_seconds` | From | To | The wait it informs |
|---|---|---|---|
| `close` | the close call (in `close_terminal`: the first close request) | MT5 seen gone | `closeWaitSeconds` |
| `launch_observe` | a fresh launch: just before `Popen`; a resume: the start of the re-check | `Popen` returned with the pid; on a resume, the journaled MT5 listed | `launchObserveSeconds` |
| `dashboard_first_answer` | the registration written | the first `observed` status | `dashboardWaitSeconds` |
| `child_start` | the link step starts | the first link receipt in which every row has a started chart | `childStartWaitSeconds` |
| `link` | the link step starts | every row linked fresh and unique | `childStartWaitSeconds` |
| `ack` | the policy dispatched | every row acknowledged | `ackWaitSeconds` |
| `audit` | the first audit request | the audit observed with every row matching | `auditWaitSeconds` |
| `unwind_close`, `stop_close`, `close_after_resume` | the unwind's close, `deploy-stop`'s close, a resumed close's wait | MT5 seen gone | `closeWaitSeconds` |

- **A failed phase.** Its duration up to the failure is still journaled, and the phase is named in
  `observed_cut_by_failure` (a lower bound, not a measurement). This covers a refusal that unwinds, a plain refusal
  (for example an ack timeout, which keeps the durable phase), a crash and a close that never confirmed.
- **A resume.** The durations already journaled are kept, and the phases run again overwrite theirs. A kill journals
  only what the last phase write carried.
- **Where they are.** `deploy-load` and `deploy-stop`: the deployment journal. `close-terminal`: its
  `terminal-closes/<attempt>.json`, which also carries `timing_profile` (the desktop record when no flag is given;
  other callers of `close_terminal` record the duration only).
- **The desktop golden diff.** A run without a profile gains exactly two journal keys over the pre-profile golden:
  `timing_profile` and `observed_seconds`. Every call, file and other journal value is unchanged.

## 2. The link race (traps T2, T9)

A cold dashboard answers a `link_children` request `started` while it is still adopting children. The next request
then finds that retained receipt, and `portfolio_request` refuses with `UnresolvedMutation`. Before v0 the link step
treated that as a refusal and unwound after about 31 s. Now, inside the `childStartWaitSeconds` window:

- **`UnresolvedMutation` is pending.** The retained receipt is re-read **read-only** every second (nothing is written,
  locked or archived) until it is no longer `started`. Then a fresh request is asked.
- **A `PermissionError` is pending.** This covers a read of the retained receipt or of `request.json`, and a whole
  request. It means the EA holds the file without read sharing, beyond the mailbox's own retry of about 1 s.
- **`RequestStillLive` is pending.** A locked read can leave the request it interrupted still live.
- **Every other refusal still ends the link at once.** Examples are another mailbox client or another registration.
  Any other `OSError` is a crash (section 4).
- **The window still ends the link.** At the end of the window the outcome is `timeout`, so the usual
  `child_not_started` or `child_not_linked` unwind follows.
- **The journal.** When anything was waited out, `attached` (or the failure) carries `link_race: {started_waits,
  locked_reads, live_waits}`.

`UnresolvedMutation` and `RequestStillLive` are `ValueError` subclasses with the old sentences unchanged.

## 3. Resume re-check (T5) and `resumeAllowed` (T6)

A `deploy-load` that finds its journal at `launched`, `registered` or `dashboard_ready` first re-proves what the
skipped phases proved. It records the result in `resume_check`.

1. **The terminal.** The MT5 running is the one this deployment launched: the journaled pid. It is observed for up to
   `launchObserveSeconds`. If none is running, the code is `RESUME_TERMINAL_GONE`. If another process is running, the
   code is `RESUME_TERMINAL_CHANGED`.
2. **The bytes.** Every staged SET still holds its reviewed bytes, or the code is `RESUME_BYTES_CHANGED`. The chart
   files and the resume file are not compared: MT5 and the dashboard rewrite them while they run.
3. **Only at `dashboard_ready`.** This is the one phase that never registers again (`launched` and `registered`
   register again, as before).
   - **The registration's age.** It comes from `registration.json` (`expiresAtUtc - 14400`) and must pass
     `resumeAllowed` for the profile in use. What is left of the deploy (child start, policy, ack and audit) must end
     before the expiry. A registration that is unreadable or missing is `RESUME_AGE_UNKNOWN`. One that is too old is
     `RESUME_REGISTRATION_TOO_OLD`.
   - **The same registration.** The registration must be exactly the one this deployment registered: the same sha,
     and the same content apart from the expiry. Otherwise the code is `RESUME_REGISTRATION_CHANGED`.
   - **A fresh status read.** It must be observed (`RESUME_DASHBOARD_NOT_READY`) and inert (`RESUME_NOT_INERT`).

Any refusal **unwinds** (D3), journals `failure` and `resume_check`, and raises a `Refusal` with the code. The next
`deploy-load` is then a fresh attempt with a new 4 h registration, once MT5 is open again: the same rule as every
auto-unwind. **Decided here (open question M5):** v0 unwinds and never registers again on resume, because a new
registration would touch the EA's registration contract.

## 4. Failure journaling

A crash in `deploy-load` that is not a `ValueError` (a bug, a `KeyError`, an unexpected `OSError`) is handled in one of
two ways:

- **Before the launch** (`validated`, `staged`, `closed`). `failure: {code: controller_crash, message, phase,
  exception}` is written to the journal as it was last written durably, never with a phase the crash interrupted. The
  original exception is raised again. The next `deploy-load` resumes the same plan and moves the old failure to
  `earlier_failures`.
- **From `launch_intent` on.** The deploy unwinds like any failure after the launch, and the CLI gets the `Refusal`
  `DEPLOY_CONTROLLER_CRASH`.

A process kill runs no handler. The journal then stays at its phase, and section 3 covers the resume.

**`refused_before_stage` keeps the attempt counter.** Before v0, a retry after a refusal before staging restarted at
attempt 1. It then reused attempt 1's retained close record (so no close was sent), and a later stop collided with the
kept `attempt-1.json`.

## 5. Deferred (not in v0)

From design section 3.1:

- **The fresh-launch observation and the other-terminal witness** (item 6, `LAUNCH_NOT_OBSERVED`,
  `PROTECTED_CHANGED`). Today `launchObserveSeconds` bounds only the resume's process observation, because a new step
  after `Popen` would change the desktop deploy.
- **Attach-only MT5** (item 5).
- **The generalized terminal lifecycle lock** (item 6).
- **The allowed-write scope invariant, the expertmode read-back and the pre-B44 duplicate-magic check** (item 6).
- **The `algo-on` and `algo-off` commands** (item 7).
- **The beta.38 3-5 s mailbox read window** (item 8, `P-beta38-mailbox-read-window`). v0 treats a `PermissionError`
  during the link as pending instead.
- **A resume re-check at `attached` and `policy_applied`.**
