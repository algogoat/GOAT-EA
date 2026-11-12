# Ops 2026-11-11: an unattended chain of Prove batches for one machine: waits until the machine is free, checks the
# plan's members all state the same inputs (GOAT-EA#315 interim rule; exit 0 from prove-name-sets.ps1), re-reads the
# inbox for a hold, then prepare-batch + run-batch. Stops and posts one [Watch] line on any refusal. Steps: "<batch id>|<plan>".
# First thirds and plans that need no judgement only; early stop and second batches need Ops.
param([Parameter(Mandatory)][ValidateSet('t3', 'banker')][string]$Machine, [Parameter(Mandatory)][string[]]$Steps, [Parameter(Mandatory)][long]$InboxAfter, [double]$Hours = 12, [string]$ToolPath = '')
$here = Split-Path $MyInvocation.MyCommand.Path
$tool = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\b54-identity\controller\demo_agent.py'
# -ToolPath: another controller tree's demo_agent.py (11-11: the merged GOAT-EA#320 head, for members whose SET uses a native enum ladder).
if ($ToolPath) { if (-not (Test-Path -LiteralPath $ToolPath)) { "STOP: no controller at $ToolPath"; exit 5 }; $tool = $ToolPath }
$caller = @{ t3 = 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\t3-call.ps1'; banker = 'G:\GOAT-Build-Artifacts\interim-ops-20261108\parallel-readiness\banker-call.ps1' }[$Machine]
$dir = Split-Path $caller; $until = [DateTime]::UtcNow.AddHours($Hours)
function Say($m) { '{0:HH:mm:ss}Z PROVE-CHAIN {1}: {2}' -f [DateTime]::UtcNow, $Machine, $m }
function Post($m) {
  try { $issue = [IO.File]::ReadAllText('G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt').Trim().TrimStart('#'); $f = Join-Path $env:TEMP ("pchain-$Machine-{0}.md" -f [DateTime]::UtcNow.ToString('HHmmss'))
        [IO.File]::WriteAllText($f, ("Claude-PC: [Watch] **Prove chain on $Machine stopped.** " + $m), (New-Object Text.UTF8Encoding $false)); $null = & 'C:\Program Files\GitHub CLI\gh.exe' api "repos/algogoat/goatai/issues/$issue/comments" -F "body=@$f" 2>$null } catch {}
}
function Busy {
  $null = & $caller -Name "pchain-$Machine" -Tool $tool -Chars 1 research-status
  $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir "pchain-$Machine.out") -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
  if (-not $o -or -not $o.ok) { return $null }
  $a = $o.result.activity
  # 11-11 19:20Z: a batch started 90 s after the one before ended found the monitor chart unreadable (MT5 was still coming
  # back on its monitor profile), recorded no healthy pre-close observation, and could not finish at its end
  # (hunt-t3-wave5-prove-13a-p1: "Runtime feedback is stale", monitor_silent). While MT5 is up, the terminal counts as free
  # only when its monitor is reporting.
  $m = $o.result.monitor; $t = $o.result.terminal
  if ($t -and $t.running -and $m -and ("$($m.state)" -eq 'silent' -or [double]$m.heartbeat_age_seconds -gt 60)) { return $true }
  return ([bool]$o.result.driver.alive -or [bool]$a.current_member -or ("$($a.status)" -in 'running', 'starting', 'queued', 'active'))
}
function Held {
  # The one hold reader (every page of the inbox, fails closed): queue\tools\hold-reader.ps1, tested by hold-reader.test.ps1.
  try { . 'G:\GOAT-Build-Artifacts\claude-pc-ops\queue\tools\hold-reader.ps1'; return (Get-HoldReason -InboxAfter $InboxAfter) } catch { return 'the inbox check threw' }
}
function Step([string]$name, [string[]]$a) {
  $null = & $caller -Name $name -Tool $tool -Chars 1 @a
  $raw = Get-Content -LiteralPath (Join-Path $dir "$name.out") -Raw -ErrorAction SilentlyContinue
  if (-not $raw) { return ((Get-Content -LiteralPath (Join-Path $dir "$name.err") -Tail 2 -ErrorAction SilentlyContinue) -join ' ') }
  $o = $raw | ConvertFrom-Json; if (-not $o.ok) { return "$($o.code): $($o.error)" }
  return $null
}
foreach ($step in $Steps) {
  $id, $plan = $step -split '\|'
  $free = 0
  while ($free -lt 2) {
    if ([DateTime]::UtcNow -ge $until) { Say 'hours elapsed while waiting'; exit 0 }
    $b = Busy; if ($b -eq $false) { $free++ } else { $free = 0 }
    if ($free -lt 2) { Start-Sleep -Seconds 75 }
  }
  $h = Held; if ($h) { Say "STOP before $id`: $h"; Post "Not started: ``$id``. Reason: $h."; exit 3 }
  $null = & (Join-Path $here 'prove-name-sets.ps1') -Plan ($plan -replace '/', '\'); if ($LASTEXITCODE -ne 0) { Say "STOP before $id`: members do not all state the same inputs (exit $LASTEXITCODE)"; Post "Not started: ``$id``. Its members do not all state the same inputs (GOAT-EA#315); it needs a split."; exit 4 }
  $e = Step "pb-$id" @('prepare-batch', '--batch-id', $id, '--plan', $plan); if ($e) { Say "prepare-batch refused $id`: $e"; Post ("``$id`` was refused at prepare-batch: " + "$e".Substring(0, [Math]::Min(500, "$e".Length))); exit 2 }
  $e = Step "rb-$id" @('run-batch', '--batch-id', $id, '--max-seconds', '14400'); if ($e) { Say "run-batch refused $id`: $e"; Post ("``$id`` was refused at run-batch: " + "$e".Substring(0, [Math]::Min(500, "$e".Length))); exit 2 }
  Say "started $id"
  Start-Sleep -Seconds 300
}
Say 'all steps started'
