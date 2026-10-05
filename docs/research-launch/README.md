# Research launch policy (goatai#1885 PR E)

## Why

On 2026-10-05 every T2 seed-member start froze the owner PC for about 12.5 minutes (12:12, 13:02, 13:46 and 14:20Z). Each Exp 01 publisher cycle that overlapped a start took 751–783 s instead of about 50 s.

- **The cause was CPU priority.** The publishers run as Task Scheduler priority-7 tasks, which is **BelowNormal**. T2's MT5 was launched by `subprocess.Popen` from a Normal shell, so MT5 and its 24 local tester agents ran at **Normal**.
- **The timing matched.** 24 Normal CPU-bound agents on 24 logical CPUs starve every BelowNormal thread for the whole first generation (24 agents × a batch of 5 passes). Each publisher hang ended within 11–47 s of T2's generation 0.
- **Banker never stalled.** Its driver is a priority-7 scheduled task, so its MT5 and agents inherit BelowNormal and share the CPU fairly with the publishers.
- **History load was not the cause.** Every agent logs `load 27 bytes of history data to synchronize`, because agents share one `bases` folder per terminal.

## What changed

The change is limited to research launches. Seed, catch-up and hold-up members go through `SeedRunner`. A native batch's first `/config` start goes through `studio_config_start`. Both wrap their process in `studio_seed_process.ResearchLaunch`, which starts MT5 through `studio_research_launch.launch`:

1. The job `Local\GOAT-Research-<sha256(terminal exe, data root)[:32]>` is created and configured. A failure here refuses before any process exists.
2. MT5 is created with `CREATE_SUSPENDED | <priority class> | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB` (see "Leaving the caller's job").
3. MT5 is assigned to the job while it is still suspended. The tester agents are its child processes, so they join the job, and so does the EA's own MT5 relaunch chain.
4. MT5 is resumed.

If step 3 or 4 fails, including with `ERROR_ACCESS_DENIED` when the controller runs inside a job that refuses nesting, the suspended process is terminated and the launch is refused with a plain sentence. There is never a fallback launch at Normal. "Nothing ran" is claimed only once the terminate is confirmed (see "A refused launch").

- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is never set, and every limit is read back after it is set. MT5 outlives the controller, which exits all the time.
- A NULL job handle never reaches Windows, which would apply the call to the caller's own job. On the owner PC that job is the Claude desktop app's, and it contains T2.

### Leaving the caller's job (Claude-Mac's note 5)

A detached lane driver (PR C) runs as a demand Task Scheduler task with `ExecutionTimeLimit = budget + 300 s`, and the driver itself starts MT5. Task Scheduler ends a stopped task, and a task past its time limit, by terminating the task's job. A child created inside that job stays in it, even when it is later assigned to the research job (nested jobs), so stopping the task would end MT5 and its tester agents mid-member.

- MT5 is therefore created with `CREATE_BREAKAWAY_FROM_JOB`. When the caller's job allows breakaway, the research job is MT5's only job, and a task stop or time limit cannot reach it.
- When the caller's job refuses breakaway, `CreateProcess` fails with `ERROR_ACCESS_DENIED` before any process exists. The same suspended, low-priority creation is then made once more without the flag, nested as before. This is not a priority fallback: the flags are otherwise identical, and the research job, its lock and its cap still apply before MT5 runs.
- `launch.json`, `history.jsonl` and `research-status` (`last_launch.broke_away`) record which happened. `last_launch.keeper.broke_away` records the same for the keeper.
- The real-Windows test `test_terminating_the_drivers_task_job_spares_research_mt5_that_broke_away` reproduces the mechanism with Python children: a driver in an outer job starts a research launch, the outer job is terminated, and the research child survives exactly when it broke away.
- Whether Task Scheduler's own job allows breakaway is proved on T3 (`-TaskStopCheck`, see T3-PROOF). If it does not (`broke_away: false`), the remaining fix is to make the driver task's time limit outlast the member and to treat an explicit task stop as an owner stop.

### The keeper

Windows removes a job's **name** when the last handle to it closes. The job itself and its limits stay with MT5. So owner launches start a small keeper:

```
pythonw studio_research_launch.py _keep --root <state> --job <name>
```

There is one keeper per job, enforced by a mutex. It:

- holds the handle, so `research-status` can read the live job;
- runs the CPU-cap staging;
- runs the idle_split agent priority;
- exits 90 s after the job empties.

If the keeper does not start, MT5 still keeps its locked priority and its first-stage cap.

## Profiles

The policy lives in `<controller state>\research-launch.json`. Read it or change it with `goat.exe studio --installation <receipt> research-launch [--keep-pc-responsive on|off | --policy <file>]`.

| Profile | MT5 created at | Job | CPU cap | Keeper |
|---|---|---|---|---|
| customer (default: no file) | BelowNormal | none | none | no |
| customer, `keep_pc_responsive: true` | BelowNormal | BelowNormal lock | 50% hard cap | no |
| owner (`agent_priority: idle`) | Idle | Idle lock | 17% → 33%, staged | yes |
| owner (`agent_priority: idle_split`) | BelowNormal | no priority lock | 17% → 33%, staged | yes; sets each `metatester64` to Idle |

No policy can choose Normal.

### Owner policy for T2 and T3

```json
{
  "schema": "goat-research-launch-v1",
  "profile": "owner",
  "agent_priority": "idle",
  "cpu_stages_percent": [17, 33],
  "publishers": [
    {"label": "Exp 01", "cycle_log": "G:\\GOAT-Build-Artifacts\\desktop-recovery-beta11-20260928\\publisher-fault-logging-a8a292aa-f20a-48e1-8367-5b59ccf41826\\original-six\\cycle-identities.jsonl", "max_seconds": 90},
    {"label": "Exp 02", "cycle_log": "G:\\GOAT-Build-Artifacts\\desktop-recovery-beta11-20260928\\publisher-fault-logging-a8a292aa-f20a-48e1-8367-5b59ccf41826\\pair\\cycle-identities.jsonl", "max_seconds": 45}
  ]
}
```

Banker keeps no policy file. Its research launches then get the customer default, BelowNormal with no cap, which is exactly what it runs at today.

### Staging (owner only: per member launch, publisher-gated)

Staging needs three things: an owner policy that lists publishers, a launch that created a job, and a keeper holding that job. It runs per launch, which for a seed hunt means per member.

- The cap starts at the first stage.
- It widens one stage once every watched publisher has finished a cycle within budget that started after the current stage was applied.
- A cycle over budget is a breach, also while that cycle is still running. A starved cycle can take 12 minutes to log END.
- One breach steps the cap back down. A second breach in the **same launch** pauses the lane:
  - a seed hunt pauses between members, through the seed pause marker;
  - a native batch gets the ordinary safe-point `batch-pause`, with `requested_by: research_launch_guard`.
- The next launch (the next seed member) starts again at the first stage, with no breaches. Breaches are **not** counted across members of a lane. That is a known limit; a per-lane breach count is a follow-up.
- Without publishers in the policy, the cap stays at the first stage and never pauses.
- When the keeper is not holding the job, the cap stays where it is and breaches are not counted.
- `research-status` reports which of these applies:
  - `staging`: `active`, `paused`, `off_no_publishers`, `stalled_no_keeper` or `no_launch`;
  - `staging_scope`: `per_member_launch`;
  - `staging_plain`: one sentence saying what that means.
- History: `research-launch\history.jsonl`. Guard state: `research-launch\guard.json`, which only the keeper writes.

## A refused launch

There are three outcomes, and each fits #163's unconfirmed-launch path (an MT5 that may run is observed, never launched again):

| What happened | Seed member | Native first `/config` start (restart phase) | Retried? |
|---|---|---|---|
| `ResearchLaunchRefused`: no process was created, or the suspended MT5 was confirmed terminated. Nothing ran. | stays `pending` (attempts 0), batch active, `launch_refused` recorded | `launch_refused`; `restart_recovery`: MT5 closed, nothing ran | Seed: the next drive starts it normally. Native: only `run-batch --resume`, which retries only the launch. |
| `ResearchLaunchUncertain`: refused, but the never-resumed MT5 was not confirmed gone (the terminate result is checked, with the job as a fallback). | `reconcile_required` with `launch_uncertain: true`; never "nothing ran" | `launch_uncertain`; `restart_recovery`: `suspended_uncertain`, a human checks for a windowless `terminal64` | Never. `_reidentify` never adopts it either: the process has this member's INI and launch window, but GOAT never resumed it. |
| #163's unseen identity (`Terminal startup identity not observed`, a WMI stall): MT5 was resumed and may run. | `reconcile_required`; `seed-resume`/`seed-reconcile` may re-identify it | stays `launch_issued`; `restart_recovery`: `reopen_uncertain` | Never launched again; observed and reconciled. |

The native retry (`retry_refused_launch`, reached only from `run-batch --resume` on a `launch_refused` journal) re-proves the same startup file and its receipt hash and the report bridge, requires the selected MT5 to be still closed, and on the customer lane requires the retained restart consent to be still valid. It never closes, arms or reserves again. A second refusal returns to `launch_refused`; an uncertain one moves to `launch_uncertain`.

## Not implemented (follow-ups)

- **Low IO and memory priority** for the research processes. The 2026-10-05 evidence pointed at CPU, so this PR sets no IO or memory priority.
- **A per-lane breach count** across seed members (see Staging).
- **If Task Scheduler's job refuses breakaway** (T3 `-TaskStopCheck` shows `broke_away: false` and MT5 ends): register the driver task with an `ExecutionTimeLimit` of at least the member's `job_timeout_seconds` plus a margin, treat an explicit task stop as an owner stop, and longer term drive lanes from a broker outside any task job.

## research-status

`research-status` and `research-launch` report these fields:

- `research_launch`:
  - the profile, creation priority and agent priority;
  - the planned cap;
  - `last_launch`: what was set and read back at launch, with `broke_away` for MT5 and `keeper.broke_away` for the keeper;
  - `job`: the live limits, including `kill_on_job_close`, the CPU rate and active processes, while the keeper holds the job;
  - `keeper`;
  - `guard`: stage, cap, breaches and paused;
  - `staging`, `staging_scope` and `staging_plain` (see Staging);
  - `agents`: the newest fan-out in the Tester log, with agent restarts and agent-loss lines.
- `enabled_mt5_workers`: the number of local agents MT5 really started (`Core NN agent process started` lines).

## Unchanged

- Trading, deploy, onboarding and monitor launches: `studio_demo_deploy`, `studio_onboarding`, the demo agent's monitor restarts, `studio_rejected_monitor` and `studio_human_launch`. A required test pins this.
- The EA, SETs, Windows services and the MetaTester service agents.

## Proof on a real MT5

See [T3-PROOF.md](T3-PROOF.md). It has not been run yet.
