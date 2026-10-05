# T3 integration proof for the research launch policy (PR E)

**Status:** written, not run. Claude-PC Release schedules it with Ops. Nothing here runs from CI.

**Script:** `scripts/research_launch_t3_proof.ps1` (PowerShell only, no Git Bash).

**What it does:** runs one real one-member seed hunt on Terminal 3 through the PR E controller checkout (`SeedRunner` → `ResearchLaunch` → job), once per mode. While each member runs, it samples the PC.

## What it proves

1. A research MT5 starts suspended, low priority, inside `Local\GOAT-Research-<hash>`, and is resumed only after assignment. This works from wherever Ops runs it, including inside the Claude desktop app's job (MT5 breaks away when that job allows it, and nests otherwise).
2. `kill_on_job_close` is false in the live job, and MT5 outlives every `seed-resume` call that launched or watched it.
3. Every T3 `terminal64.exe` and `metatester64.exe` runs at the planned priority:
   - mode A: both Idle;
   - mode B: terminal BelowNormal, agents Idle.
4. **Agent liveness under Idle** (Claude-Mac's must-have 3). The script reports:
   - agent-loss lines in the terminal Tester log and in every agent log (`connection … lost`, `authorized tester agent … disconnected`, `task rejected by tester agent`, `connect timeout`, `platform info was not received`);
   - agent restarts (a core started again in the same run);
   - passes per minute from the agent logs.
5. The publishers keep their budget for every cycle that overlaps the member: Exp 01 ≤ 90 s, Exp 02 ≤ 45 s. A WMI `Win32_Process` query stays under 5 s.
6. The real local agent count (`enabled_mt5_workers`) and the CPU-cap staging history (`guard`) appear in `research-launch` / `research-status`. So does `staging`, the state it is really in: `active`, `paused`, `off_no_publishers` or `stalled_no_keeper`.
7. **The driver's Task Scheduler job (Claude-Mac's note 5, `-TaskStopCheck`).** On the demo lane (PR C), the seed driver runs as a demand Task Scheduler task with `ExecutionTimeLimit = budget + 300 s`, and it starts MT5. Task Scheduler ends a stopped task, and one past its time limit, by terminating the task's job. The PR E follow-up creates research MT5 with `CREATE_BREAKAWAY_FROM_JOB`, so MT5 leaves the task's job whenever that job allows it (see README, "Leaving the caller's job"). This check proves it on the real task.
   - The check waits until the member has run `-TaskStopAfterMinutes` (default 3).
   - It finds this batch's own driver task exactly: the lane worker record (`demo-agent\lane-workers\seed-<batch>.json`), then its launch envelope (task name), then its started receipt (driver PID).
   - It records the task state and time limit, the driver PID, T3's `terminal64` and `metatester64` PIDs, and `last_launch.broke_away` (MT5) and `last_launch.keeper.broke_away` (keeper).
   - It runs `Stop-ScheduledTask` on that task, waits 20 s, then checks that the driver PID ended (otherwise the result is `inconclusive`) and whether T3's `terminal64` PID and its agents survived.
   - Reaching `ExecutionTimeLimit` stops the task the same way, so this one check covers both.
   - **If MT5 survives:** the script runs `seed-resume` to re-supervise the member, and the member must still complete.
   - **If MT5 ends:** the mode FAILS with `task-stop-check.json`. Expect `broke_away: false` in that case; the remaining fix (README, "Not implemented") goes to Claude-Mac before T2 resumes.
   - The check passes only when it really measured: a task that was not running, a driver PID that was not alive, or a member that ended before the check is a FAIL, not a pass.

## Modes

| Mode | Policy written for T3 | Expectation |
|---|---|---|
| A | owner, `agent_priority: idle`, stages 17 → 33, both publishers watched | Idle everywhere; cap starts at 17% |
| B | owner, `agent_priority: idle_split` | MT5 BelowNormal; each `metatester64` set to Idle within about 2 s of starting |
| C (optional) | customer default (BelowNormal, no cap) | Control for the A/B comparison. Run only if A and B pass and Ops agrees. With Banker running, this is the riskiest mode |

Order: A, then B, then C only if wanted. Between modes:

- the script waits for T3 to exit;
- it waits for the keeper heartbeat to show `stopped`, or 2 minutes to pass;
- it waits 2 publisher cycles.

## Preconditions (Ops checks; the script re-checks the ones it can)

- **Ops** approved the slot on #1885.
- **T2:** no member running. Record whether Banker runs: running is the realistic worst case, and it is fine.
- **T3:**
  - closed;
  - its receipt and EA B41 are installed;
  - its peer registration is agreed with Ops, as for any T3 opening;
  - a one-member seed plan exists for it: the same shape as `plan-seedhunt-t2-*.json`, with one member, 3-year M1 and Model 1, like the storming T2 members.
- **Publishers:** no `PAUSE` marker; their last cycles are within budget.
- **Controller under test:** this branch's checkout, run with the controller test Python (`python313._pth` pointed at the checkout's `controller`). The installed bundle does not contain PR E yet. The script refuses at preflight when `-Python` imports `studio_research_launch` from anywhere else or without the follow-up's breakaway (for example `G:\GOAT-Build-Artifacts\claude-pc-ops\test-python-research-launch`, whose `._pth` still names the old `research-launch-policy` worktree: re-point its last line, or pass `-Python`).

## Run

```powershell
$s = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\pr-e-followup\scripts\research_launch_t3_proof.ps1'
& $s -Receipt '<T3 installation.json>' -Plan '<one-member T3 seed plan.json>' -Mode A -DryRun   # preflight only, launches nothing
& $s -Receipt '<T3 installation.json>' -Plan '<one-member T3 seed plan.json>' -Mode A
& $s -Receipt '<T3 installation.json>' -Plan '<one-member T3 seed plan.json>' -Mode B
& $s -Receipt '<T3 installation.json>' -Plan '<one-member T3 seed plan.json>' -Mode A -TaskStopCheck -DryRun   # note 5 preflight
& $s -Receipt '<T3 installation.json>' -Plan '<one-member T3 seed plan.json>' -Mode A -TaskStopCheck          # note 5, a separate run
```

`-TaskStopCheck` needs `-Lane demo` (the default) and a member that runs longer than `-TaskStopAfterMinutes` (default 3).

The default `-Lane demo` uses PR C's detached driver:

- `seed-start` returns at once;
- the script polls `seed-status` every 30 s;
- it runs `seed-resume` only after the driver has returned with the member still running.

`-Lane studio` keeps the blocking 30 s `seed-start` / `seed-resume` calls.

Output goes to `G:\GOAT-Build-Artifacts\claude-pc-ops\research-launch-proof\<UTC>-<mode>\`:

- `samples.jsonl`: every 30 s, the T3 process priorities, the WMI latency and `research-launch`;
- `report.json`: from `proof-report`;
- `verdict.json`;
- the seed command replies.

## Abort rules (built into the script)

- **A publisher cycle over budget, or still running past it.** The script runs `seed-cancel` (a normal close of the member's MT5), marks the mode FAIL and stops. It never kills a process.
- **The research launch refuses.** That is a FAIL with nothing started. Record the message.
- **`-MaxMinutes` passes.** The script runs `seed-cancel` and marks the mode FAIL.
- **If `seed-cancel` itself refuses** (for example, the live detached driver holds the terminal lock), the script logs it. Ops then uses the lane's documented stop: `goat.exe demo stop`, or the owner STOP.
- **The `-TaskStopCheck` run ends MT5.** That is a FAIL by design: it is the finding the check exists for.

## Pass rules (written to `verdict.json`)

- Every overlapping Exp 01 cycle took ≤ 90 s, and every Exp 02 cycle ≤ 45 s.
- Every WMI sample took ≤ 5 s.
- `kill_on_job_close` was false in every sample that read the live job.
- All T3 processes ran at the mode's priorities.
- There were 0 agent-loss lines and 0 agent restarts.
- The member completed with its output (`seed-status`).
- `enabled_mt5_workers` was recorded. 24 is expected on this PC; the value is reported, not judged.
- With `-TaskStopCheck`: the task stop ended the driver, T3's `terminal64` survived it, and the member still completed.

**A/B decision for Claude-Mac:**

- If mode A passes with 0 agent losses, keep `idle`.
- If mode A shows losses or restarts and mode B does not, switch the owner policy to `idle_split`.
- If both show losses, PR E needs a follow-up before T2 resumes.
- Passes per minute for A, B and (if run) C go in the same comment.

## Still to prove later (a separate slot)

- **Native batch relaunch.** A native batch's MT5 relaunch through the EA (`Tester.mqh` AddCommand → PowerShell `Start-Process`) stays inside the job. Prove it with a two-member native batch on T3 (`run-batch`): check `research-launch` after the member-2 relaunch shows the job still running, with the new terminal at Idle.
- **Staging under a real breach.** The breach → step-down → pause path is covered by fixtures and the mutation check, not on the PC. Do not provoke a real publisher breach to prove it.
