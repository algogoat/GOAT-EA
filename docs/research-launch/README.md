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
2. MT5 is created with `CREATE_SUSPENDED | <priority class> | CREATE_NO_WINDOW`.
3. MT5 is assigned to the job while it is still suspended. The tester agents are its child processes, so they join the job, and so does the EA's own MT5 relaunch chain.
4. MT5 is resumed.

If step 3 or 4 fails, including with `ERROR_ACCESS_DENIED` when the controller runs inside a job that refuses nesting, the suspended process is terminated, nothing ran, and the launch is refused with a plain sentence. There is never a fallback launch at Normal.

- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is never set, and every limit is read back after it is set. MT5 outlives the controller, which exits all the time.
- A NULL job handle never reaches Windows, which would apply the call to the caller's own job. On the owner PC that job is the Claude desktop app's, and it contains T2.

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

### Staging (owner only)

- The cap starts at the first stage.
- It widens one stage once every watched publisher has finished a cycle within budget that started after the current stage was applied.
- A cycle over budget is a breach, also while that cycle is still running. A starved cycle can take 12 minutes to log END.
- One breach steps the cap back down. A second breach pauses the lane:
  - a seed hunt pauses between members, through the seed pause marker;
  - a native batch gets the ordinary safe-point `batch-pause`, with `requested_by: research_launch_guard`.
- The next launch starts again at the first stage.
- History: `research-launch\history.jsonl`. Guard state: `research-launch\guard.json`, which only the keeper writes.

## research-status

`research-status` and `research-launch` report these fields:

- `research_launch`:
  - the profile, creation priority and agent priority;
  - the planned cap;
  - `last_launch`: what was set and read back at launch;
  - `job`: the live limits, including `kill_on_job_close`, the CPU rate and active processes, while the keeper holds the job;
  - `keeper`;
  - `guard`: stage, cap, breaches and paused;
  - `agents`: the newest fan-out in the Tester log, with agent restarts and agent-loss lines.
- `enabled_mt5_workers`: the number of local agents MT5 really started (`Core NN agent process started` lines).

## Unchanged

- Trading, deploy, onboarding and monitor launches: `studio_demo_deploy`, `studio_onboarding`, the demo agent's monitor restarts, `studio_rejected_monitor` and `studio_human_launch`. A required test pins this.
- The EA, SETs, Windows services and the MetaTester service agents.

## Proof on a real MT5

See [T3-PROOF.md](T3-PROOF.md). It has not been run yet.
