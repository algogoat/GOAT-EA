<#
.SYNOPSIS
  Owner T3 integration proof for the research launch policy (goatai#1885 PR E). NOT run by CI.

.DESCRIPTION
  One real one-member seed hunt on Terminal 3, through this branch's controller checkout
  (SeedRunner -> ResearchLaunch -> Local\GOAT-Research-<hash> job), for one mode:
    A  owner, agent_priority idle        (MT5 and agents Idle, staged 17 -> 33 % cap)
    B  owner, agent_priority idle_split  (MT5 BelowNormal, each metatester64 set to Idle)
    C  customer default                  (BelowNormal, no cap; optional control)
  While the member runs it samples every 30 s: T3 process priorities, a timed WMI
  Win32_Process query and the research-launch report. It then writes report.json (proof-report)
  and verdict.json. See docs/research-launch/T3-PROOF.md.

  -TaskStopCheck (demo lane, Claude-Mac's note 5): once the member has run -TaskStopAfterMinutes,
  Stop-ScheduledTask ends the batch's own detached driver task (found through its worker record and
  launch envelope), exactly as its ExecutionTimeLimit would. The check passes only when the stop ended
  the driver and T3's terminal64 kept running; seed-resume then re-supervises the member.

  Safety: PowerShell only. Never kills a process: an abort uses seed-cancel (normal close); the
  only stop is -TaskStopCheck's Stop-ScheduledTask of this batch's own driver task.
  Never touches T1/T2, services, priorities or affinity of other processes. Restores T3's
  research-launch.json afterwards (the proof's own file is kept beside it, never deleted).
  -DryRun runs the read-only preflight and launches nothing.

.EXAMPLE
  & .\research_launch_t3_proof.ps1 -Receipt '<T3 installation.json>' -Plan '<plan.json>' -Mode A -DryRun
#>
param(
  [Parameter(Mandatory = $true)][string]$Receipt,
  [Parameter(Mandatory = $true)][string]$Plan,
  [Parameter(Mandatory = $true)][ValidateSet('A', 'B', 'C')][string]$Mode,
  [ValidateSet('studio', 'demo')][string]$Lane = 'demo',
  [string]$Python = 'G:\GOAT-Build-Artifacts\claude-pc-ops\test-python-research-launch\python\python.exe',
  [string]$Controller = (Join-Path (Split-Path -Parent $PSScriptRoot) 'controller'),
  [string]$Exp01Log = 'G:\GOAT-Build-Artifacts\desktop-recovery-beta11-20260928\publisher-fault-logging-a8a292aa-f20a-48e1-8367-5b59ccf41826\original-six\cycle-identities.jsonl',
  [string]$Exp02Log = 'G:\GOAT-Build-Artifacts\desktop-recovery-beta11-20260928\publisher-fault-logging-a8a292aa-f20a-48e1-8367-5b59ccf41826\pair\cycle-identities.jsonl',
  [int]$Exp01Budget = 90,
  [int]$Exp02Budget = 45,
  [int]$MaxMinutes = 45,
  [string]$OutRoot = 'G:\GOAT-Build-Artifacts\claude-pc-ops\research-launch-proof',
  [switch]$TaskStopCheck,          # note 5: stop the driver's Task Scheduler task mid-member and see whether MT5 survives
  [int]$TaskStopAfterMinutes = 3,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out = Join-Path $OutRoot "$stamp-$Mode"
[void](New-Item -ItemType Directory -Force -Path $out)
function Note([string]$Text) { $line = '{0:u} {1}' -f (Get-Date).ToUniversalTime(), $Text; $line; Add-Content -LiteralPath (Join-Path $out 'run.log') -Value $line }
function Save([string]$Name, $Value) { [IO.File]::WriteAllText((Join-Path $out $Name), (ConvertTo-Json -InputObject $Value -Depth 30), $utf8) }
function Ctl([string[]]$A) {
  $script = if ($Lane -eq 'demo') { Join-Path $Controller 'demo_agent.py' } else { Join-Path $Controller 'goat_studio.py' }
  $text = (& $Python -B $script --installation $Receipt @A) -join "`n"
  Add-Content -LiteralPath (Join-Path $out 'commands.log') -Value ("> " + ($A -join ' ') + "`n" + $text)
  if (-not $text) { throw "controller $($A[0]) printed nothing" }
  $r = $text | ConvertFrom-Json
  if ($null -ne $r.ok) { if (-not $r.ok) { throw "controller $($A[0]) refused: $($r.error)" }; return $r.result }
  return $r }
function Proof([string[]]$A) {
  $text = (& $Python -B (Join-Path $Controller 'studio_research_launch.py') @A --installation $Receipt) -join "`n"
  if (-not $text) { throw "studio_research_launch $($A[0]) printed nothing" }
  return ($text | ConvertFrom-Json) }
function LastCycle([string]$Log) {
  $rows = @(Get-Content -LiteralPath $Log -Tail 20 | ForEach-Object { try { $_ | ConvertFrom-Json } catch { } })
  $start = $rows | Where-Object { $_.event -eq 'START' } | Select-Object -Last 1
  if (-not $start) { return $null }
  $end = $rows | Where-Object { $_.event -eq 'END' -and $_.startedAt -eq $start.startedAt } | Select-Object -Last 1
  $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  if ($end) { return [pscustomobject]@{ running = $false; seconds = [math]::Round(($end.endedAt - $start.startedAt) / 1000) } }
  return [pscustomobject]@{ running = $true; seconds = [math]::Round(($nowMs - $start.startedAt) / 1000) } }

# ---------------------------------------------------------------- preflight (read-only)
if ($TaskStopCheck -and $Lane -ne 'demo') { throw '-TaskStopCheck needs -Lane demo: only the demo lane drives members from a Task Scheduler task' }
if ($TaskStopCheck -and $TaskStopAfterMinutes -ge $MaxMinutes) { throw '-TaskStopAfterMinutes must be below -MaxMinutes' }
$install = Get-Content -Raw -LiteralPath $Receipt | ConvertFrom-Json
$t3Folder = Split-Path -Parent $install.terminal_executable
Note "mode $Mode; T3 $($install.terminal_executable); controller $Controller; lane $Lane"
if (-not (Test-Path -LiteralPath (Join-Path $Controller 'studio_research_launch.py'))) { throw 'Controller checkout has no studio_research_launch.py (PR E)' }
# The test Python's ._pth decides which controller is imported (an embedded Python never adds the script folder):
# it must be this checkout, with the PR E follow-up (breakaway), or the proof would measure older code.
$probe = @(& $Python -B -c "import os,studio_research_launch as r; print(os.path.dirname(os.path.abspath(r.__file__))); print(hasattr(r, '_create_suspended'))")
if ($probe.Count -ne 2 -or $probe[0] -ne [IO.Path]::GetFullPath($Controller).TrimEnd('\') -or $probe[1] -ne 'True') {
  throw "-Python imports the research launch from '$($probe -join ' ')', not $Controller with the PR E follow-up: point the last line of its python313._pth at $Controller" }
$running = @(Get-Process -Name terminal64, metatester64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($t3Folder, [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) { throw "T3 is running ($($running.Count) processes): close it normally first" }
$others = @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Path })
Note ("other MT5 running: " + ($others -join '; '))
foreach ($pair in @(@('Exp 01', $Exp01Log, $Exp01Budget), @('Exp 02', $Exp02Log, $Exp02Budget))) {
  $c = LastCycle $pair[1]
  if (-not $c) { throw "$($pair[0]) has no cycle in $($pair[1])" }
  if ($c.seconds -gt $pair[2]) { throw "$($pair[0]) last cycle took $($c.seconds) s (> $($pair[2]) s): not a clean slot" }
  Note "$($pair[0]) last cycle $($c.seconds) s (running=$($c.running))" }
$policyPath = Join-Path $install.controller_state_root 'research-launch.json'
$backup = $null
if (Test-Path -LiteralPath $policyPath) { $backup = Get-Content -Raw -LiteralPath $policyPath; Note 'existing research-launch.json saved for restore' }
$publishers = @(@{ label = 'Exp 01'; cycle_log = $Exp01Log; max_seconds = $Exp01Budget }, @{ label = 'Exp 02'; cycle_log = $Exp02Log; max_seconds = $Exp02Budget })
$policy = switch ($Mode) {
  'A' { @{ schema = 'goat-research-launch-v1'; profile = 'owner'; agent_priority = 'idle'; cpu_stages_percent = @(17, 33); publishers = $publishers } }
  'B' { @{ schema = 'goat-research-launch-v1'; profile = 'owner'; agent_priority = 'idle_split'; cpu_stages_percent = @(17, 33); publishers = $publishers } }
  'C' { @{ schema = 'goat-research-launch-v1'; profile = 'customer'; keep_pc_responsive = $false } } }
$policyFile = Join-Path $out 'policy.json'; [IO.File]::WriteAllText($policyFile, (ConvertTo-Json -InputObject $policy -Depth 10), $utf8)
$planValue = Get-Content -Raw -LiteralPath $Plan | ConvertFrom-Json
Save 'preflight.json' @{ mode = $Mode; t3 = $install.terminal_executable; others = $others; plan = $Plan; policy = $policy; restore = [bool]$backup;
  lane = $Lane; task_stop_check = [bool]$TaskStopCheck; task_stop_after_minutes = $TaskStopAfterMinutes }
if ($DryRun) { Note 'DryRun: preflight passed; nothing written to T3, nothing launched'; return }

# ---------------------------------------------------------------- policy, prepare, start
$batch = "rlproof-$($Mode.ToLower())-$stamp"
$verdict = [ordered]@{ mode = $Mode; batch_id = $batch; pass = $false; reasons = @() }
try {
  [void](Ctl @('research-launch', '--policy', $policyFile))   # studio lane; on the demo lane the file is written below
} catch {
  # demo_agent has no research-launch command: write the validated policy through the module instead.
  & $Python -B -c "import json,sys; sys.path.insert(0, sys.argv[1]); import studio_research_launch as r; r.write_policy(sys.argv[2], json.load(open(sys.argv[3], encoding='utf-8-sig')))" $Controller $install.controller_state_root $policyFile
  if ($LASTEXITCODE -ne 0) { throw 'Could not write the proof research-launch.json' } }
Save 'research-launch-before.json' (Proof @('proof-status'))
[void](Ctl @('seed-prepare', '--batch-id', $batch, '--plan', $Plan))
$since = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
$samples = Join-Path $out 'samples.jsonl'
$deadline = (Get-Date).AddMinutes($MaxMinutes)
$abort = $null; $state = $null; $taskCheck = $null; $memberSince = $null
function SeedOf($r) { if ($null -ne $r.seed) { return $r.seed } return $r }   # demo lane wraps seed-status as {broker, driver, seed}
function T3Terminals { @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($t3Folder, [StringComparison]::OrdinalIgnoreCase) }) }
function T3Agents { @(Get-Process -Name metatester64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($t3Folder, [StringComparison]::OrdinalIgnoreCase) }) }
function DriverTask {
  # The current detached seed driver of this batch (PR C): worker record -> launch envelope -> task name and started PID.
  try {
    $worker = Get-Content -Raw -LiteralPath (Join-Path $install.controller_state_root "demo-agent\lane-workers\seed-$batch.json") | ConvertFrom-Json
    $envelope = Get-Content -Raw -LiteralPath $worker.launch_envelope | ConvertFrom-Json
    $started = Get-Content -Raw -LiteralPath $envelope.started | ConvertFrom-Json
    if ($started.nonce -ne $worker.nonce) { throw 'started receipt belongs to another driver' }
    return [pscustomobject]@{ task_name = $envelope.task_name; pid = [int]$started.pid; nonce = $worker.nonce; error = $null }
  } catch { return [pscustomobject]@{ task_name = $null; pid = $null; nonce = $null; error = $_.Exception.Message } } }
try {
  # demo lane (PR C): seed-start detaches its driver as a demand Task Scheduler task and returns at once.
  # studio lane: a blocking 30 s foreground drive, resumed every loop.
  $budget = if ($Lane -eq 'demo') { "$([math]::Min(3600, $MaxMinutes * 60))" } else { '30' }
  $state = SeedOf (Ctl @('seed-start', '--batch-id', $batch, '--max-seconds', $budget))
  while ($true) {
    if ($Lane -eq 'demo') { Start-Sleep -Seconds 30 }
    $status = Ctl @('seed-status', '--batch-id', $batch); $state = SeedOf $status
    # ---- one sample
    $t3 = @(Get-Process -Name terminal64, metatester64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($t3Folder, [StringComparison]::OrdinalIgnoreCase) } |
      ForEach-Object { [pscustomobject]@{ pid = $_.Id; name = $_.ProcessName; priority = [string]$_.PriorityClass } })
    if ($t3.Count -and -not $memberSince) { $memberSince = Get-Date }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $wmiOk = $true
    try { [void](Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" -OperationTimeoutSec 20) } catch { $wmiOk = $false }
    $wmi = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    $launch = $null; try { $launch = Proof @('proof-status') } catch { $launch = @{ error = $_.Exception.Message } }
    $c1 = LastCycle $Exp01Log; $c2 = LastCycle $Exp02Log
    $row = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('o'); processes = $t3; wmi_seconds = $wmi; wmi_ok = $wmiOk;
      exp01 = $c1; exp02 = $c2; job = $launch.job; keeper = $launch.keeper; mt5_broke_away = $launch.last_launch.broke_away;
      keeper_broke_away = $launch.last_launch.keeper.broke_away;
      staging = $launch.staging; guard = $launch.guard; agents = $launch.agents; enabled_mt5_workers = $launch.enabled_mt5_workers;
      seed_status = $state.status; driver = $status.driver }
    Add-Content -LiteralPath $samples -Value (ConvertTo-Json -InputObject $row -Depth 12 -Compress)
    Note ("sample: {0} T3 processes, wmi {1}s, Exp01 {2}s{3}, Exp02 {4}s{5}, cap {6}, agents {7}, staging {8}" -f $t3.Count, $wmi, $c1.seconds,
      $(if ($c1.running) { '+' } else { '' }), $c2.seconds, $(if ($c2.running) { '+' } else { '' }), $launch.job.cpu_rate_percent,
      $launch.enabled_mt5_workers, $launch.staging)
    # ---- abort rules
    if ($c1 -and $c1.seconds -gt $Exp01Budget) { $abort = "Exp 01 cycle at $($c1.seconds) s > $Exp01Budget s" }
    elseif ($c2 -and $c2.seconds -gt $Exp02Budget) { $abort = "Exp 02 cycle at $($c2.seconds) s > $Exp02Budget s" }
    elseif ((Get-Date) -gt $deadline) { $abort = "MaxMinutes $MaxMinutes reached" }
    if ($abort) { break }
    if ($state.status -in @('completed', 'stopped', 'reconcile_required')) { break }
    # ---- Claude-Mac note 5: does ending the driver's Task Scheduler task end MT5 mid-member?
    # Task Scheduler ends a stopped task, and one past its ExecutionTimeLimit, by terminating the task's job, so
    # one Stop-ScheduledTask measures both. The check is valid only when the stop really ended the driver.
    if ($TaskStopCheck -and -not $taskCheck -and $memberSince -and ((Get-Date) - $memberSince).TotalMinutes -ge $TaskStopAfterMinutes) {
      $driver = DriverTask
      $task = $null; if ($driver.task_name) { $task = Get-ScheduledTask -TaskName $driver.task_name -ErrorAction SilentlyContinue }
      $before = @(T3Terminals | ForEach-Object { $_.Id }); $agentsBefore = @(T3Agents | ForEach-Object { $_.Id })
      $taskCheck = [ordered]@{ task = $driver.task_name; task_state_before = [string]$task.State;
        execution_time_limit = [string]$task.Settings.ExecutionTimeLimit; driver_pid = $driver.pid;
        driver_alive_before = [bool]($driver.pid -and (Get-Process -Id $driver.pid -ErrorAction SilentlyContinue));
        terminal_pids_before = $before; agent_pids_before = $agentsBefore;
        mt5_broke_away = $launch.last_launch.broke_away; keeper_broke_away = $launch.last_launch.keeper.broke_away }
      if (-not $task -or [string]$task.State -ne 'Running' -or -not $taskCheck.driver_alive_before -or -not $before.Count) {
        $taskCheck.result = 'not_checked: the driver task is not running, its driver PID is not alive, or T3 MT5 is not running'
        Note "TASK STOP CHECK: $($taskCheck.result) ($($driver.error))"
      } else {
        Note "TASK STOP CHECK: stopping driver task $($task.TaskName) (limit $($taskCheck.execution_time_limit), driver PID $($driver.pid)); T3 MT5 $($before -join ','), MT5 broke_away $($taskCheck.mt5_broke_away)"
        Stop-ScheduledTask -TaskName $task.TaskName
        Start-Sleep -Seconds 20
        $after = @(T3Terminals | ForEach-Object { $_.Id }); $agentsAfter = @(T3Agents | ForEach-Object { $_.Id })
        $taskCheck.task_state_after = [string](Get-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue).State
        $taskCheck.driver_ended = -not (Get-Process -Id $driver.pid -ErrorAction SilentlyContinue)
        $taskCheck.terminal_pids_after = $after; $taskCheck.agent_pids_after = $agentsAfter
        $taskCheck.agents_survived = @($agentsBefore | Where-Object { $agentsAfter -contains $_ }).Count
        $taskCheck.mt5_survived = [bool](@($before | Where-Object { $after -contains $_ }).Count)
        $taskCheck.result = if (-not $taskCheck.driver_ended) { 'inconclusive: the task stop did not end the driver' }
          elseif ($taskCheck.mt5_survived) { 'MT5 survived the task stop' } else { 'MT5 ENDED with the task stop' }
        Note "TASK STOP CHECK: $($taskCheck.result) (agents $($taskCheck.agents_survived)/$($agentsBefore.Count) survived)"
        Save 'task-stop-check.json' $taskCheck
        if (-not $taskCheck.mt5_survived) { $abort = 'task stop ended MT5 mid-member (note 5): see task-stop-check.json'; break }
        if ($taskCheck.driver_ended) { $state = SeedOf (Ctl @('seed-resume', '--batch-id', $batch, '--max-seconds', $budget)) }   # re-supervise
      }
      Save 'task-stop-check.json' $taskCheck
      continue
    }
    if ($Lane -eq 'demo') {
      # Re-detach only when the driver returned and the member still runs (the driver budget ended).
      if ($status.driver -and $status.driver.alive -eq $false) { $state = SeedOf (Ctl @('seed-resume', '--batch-id', $batch, '--max-seconds', $budget)) }
    } else { $state = SeedOf (Ctl @('seed-resume', '--batch-id', $batch, '--max-seconds', '30')) }
  }
} catch {
  $abort = 'controller: ' + $_.Exception.Message
}
if ($abort) {
  Note "ABORT: $abort"
  $verdict.reasons += "aborted: $abort"
  try { Save 'seed-cancel.json' (Ctl @('seed-cancel', '--batch-id', $batch)) } catch { Note "seed-cancel: $($_.Exception.Message)" }
}
$until = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
Start-Sleep -Seconds 5
try { $final = Ctl @('seed-status', '--batch-id', $batch); Save 'seed-status.json' $final; $state = SeedOf $final } catch { Note "seed-status: $($_.Exception.Message)" }
$report = Proof @('proof-report', '--since-wall', "$since", '--until-wall', "$until")
Save 'report.json' $report

# ---------------------------------------------------------------- verdict
$rows = @(Get-Content -LiteralPath $samples -ErrorAction SilentlyContinue | ForEach-Object { $_ | ConvertFrom-Json })
$expect = switch ($Mode) { 'A' { @{ terminal64 = 'Idle'; metatester64 = 'Idle' } } 'B' { @{ terminal64 = 'BelowNormal'; metatester64 = 'Idle' } } 'C' { @{ terminal64 = 'BelowNormal'; metatester64 = 'BelowNormal' } } }
foreach ($p in $report.publishers) { if ($p.over_budget -gt 0) { $verdict.reasons += "$($p.label): $($p.over_budget) cycle(s) over $($p.budget_seconds) s (max $($p.max_seconds) s)" } }
if (@($rows | Where-Object { -not $_.wmi_ok -or $_.wmi_seconds -gt 5 }).Count) { $verdict.reasons += 'a WMI Win32_Process query took over 5 s' }
if (@($rows | Where-Object { $_.job -and $_.job.state -eq 'running' -and $_.job.kill_on_job_close }).Count) { $verdict.reasons += 'kill_on_job_close was true' }
# idle_split lowers each agent within ~2 s of its start: a first sample may still see BelowNormal agents.
$late = if ($Mode -eq 'B') { 1 } else { 0 }
$wrong = @($rows | Select-Object -Skip $late | ForEach-Object { $_.processes } | Where-Object { $_ -and $_.priority -ne $expect[$_.name] })
if ($wrong.Count) { $verdict.reasons += "$($wrong.Count) process samples at an unexpected priority" }
$agents = $report.status.agents
if ($agents -and ($agents.agent_losses -gt 0 -or $agents.agent_restarts -gt 0)) { $verdict.reasons += "tester log: $($agents.agent_losses) agent loss line(s), $($agents.agent_restarts) restart(s)" }
if ($report.agent_log_losses -gt 0) { $verdict.reasons += "agent logs: $($report.agent_log_losses) agent loss line(s)" }
if ($state.status -ne 'completed') { $verdict.reasons += "seed status $($state.status), not completed" }
$verdict.enabled_mt5_workers = $report.status.enabled_mt5_workers
$verdict.passes = $report.passes
$verdict.publishers = $report.publishers
$verdict.guard = $report.status.guard
$verdict.staging = $report.status.staging
$verdict.task_stop_check = $taskCheck
if ($TaskStopCheck) {
  # -TaskStopCheck passes only on a real measurement: the stop ended the driver and T3's MT5 survived it.
  if (-not $taskCheck) { $verdict.reasons += 'task stop check never ran (the member ended before -TaskStopAfterMinutes)' }
  elseif ($taskCheck.result -ne 'MT5 survived the task stop') { $verdict.reasons += "task stop check: $($taskCheck.result) (note 5)" }
}
$verdict.pass = ($verdict.reasons.Count -eq 0)
Save 'verdict.json' $verdict
Note ("VERDICT mode {0}: {1}; workers {2}; passes/min {3}" -f $Mode, $(if ($verdict.pass) { 'PASS' } else { 'FAIL: ' + ($verdict.reasons -join '; ') }), $verdict.enabled_mt5_workers, $report.passes.passes_per_minute)

# ---------------------------------------------------------------- restore T3's own policy
$kept = Join-Path $install.controller_state_root ("research-launch.json.proof-$stamp")
if (Test-Path -LiteralPath $policyPath) { Move-Item -LiteralPath $policyPath -Destination $kept }
if ($backup) { [IO.File]::WriteAllText($policyPath, $backup, $utf8); Note 'restored the previous research-launch.json' }
else { Note "T3 back on the customer default; the proof policy is kept at $kept" }
