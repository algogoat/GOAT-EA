# Ops 2026-11-11: an unattended chain of preregistered, merged seed batches for one machine, so it does not stand idle
# when the Ops session is down. Waits until the machine is free, then runs each seed plan in order with run-seed.ps1.
# Stops (and posts one [Watch] line on the inbox) on any refusal, or when a non-Ops inbox post since -InboxAfter asks for
# a hold. Steps: "<batch id>|<plan path>|<job count>". Seeds only: promotion and Prove need Ops.
param([Parameter(Mandatory)][ValidateSet('t3', 'banker')][string]$Machine, [Parameter(Mandatory)][string[]]$Steps, [Parameter(Mandatory)][long]$InboxAfter, [double]$Hours = 12)
$here = Split-Path $MyInvocation.MyCommand.Path
$tool = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\b54-identity\controller\demo_agent.py'
$caller = @{ t3 = 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\t3-call.ps1'; banker = 'G:\GOAT-Build-Artifacts\interim-ops-20261108\parallel-readiness\banker-call.ps1' }[$Machine]
$dir = Split-Path $caller; $until = [DateTime]::UtcNow.AddHours($Hours)
function Say($m) { '{0:HH:mm:ss}Z CHAIN {1}: {2}' -f [DateTime]::UtcNow, $Machine, $m }
function Post($m) {
  try { $issue = [IO.File]::ReadAllText('G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt').Trim().TrimStart('#'); $f = Join-Path $env:TEMP ("chain-$Machine-{0}.md" -f [DateTime]::UtcNow.ToString('HHmmss'))
        [IO.File]::WriteAllText($f, ("Claude-PC: [Watch] **seed chain on $Machine stopped.** " + $m), (New-Object Text.UTF8Encoding $false)); $null = & 'C:\Program Files\GitHub CLI\gh.exe' api "repos/algogoat/goatai/issues/$issue/comments" -F "body=@$f" 2>$null } catch {}
}
function Busy {
  $null = & $caller -Name "chain-$Machine" -Tool $tool -Chars 1 research-status
  $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir "chain-$Machine.out") -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
  if (-not $o -or -not $o.ok) { return $null }
  $a = $o.result.activity
  return ([bool]$o.result.driver.alive -or [bool]$a.current_member -or ("$($a.status)" -in 'running', 'starting', 'queued', 'active'))
}
function Held {
  # The one hold reader (every page of the inbox, fails closed): queue\tools\hold-reader.ps1, tested by hold-reader.test.ps1.
  try { . 'G:\GOAT-Build-Artifacts\claude-pc-ops\queue\tools\hold-reader.ps1'; return (Get-HoldReason -InboxAfter $InboxAfter) } catch { return 'the inbox check threw' }
}
foreach ($step in $Steps) {
  $id, $plan, $jobs = $step -split '\|'
  $free = 0
  while ($free -lt 2) {
    if ([DateTime]::UtcNow -ge $until) { Say 'hours elapsed while waiting'; exit 0 }
    $b = Busy
    if ($b -eq $false) { $free++ } else { $free = 0 }
    if ($free -lt 2) { Start-Sleep -Seconds 240 }
  }
  $h = Held; if ($h) { Say "STOP before $id`: $h"; Post "Not started: ``$id``. Reason: $h."; exit 3 }
  Say "starting $id ($jobs jobs)"
  $out = & (Join-Path $here 'run-seed.ps1') -Machine $Machine -Id $id -Plan $plan -Jobs ([int]$jobs) -Hours 8 2>&1
  $last = "$($out | Select-Object -Last 1)"
  Say "$id ended: $last"
  if (($out -join "`n") -match 'RUN-SEED STOP') { Post ("``$id`` was refused: " + (($out | Where-Object { "$_" -match 'RUN-SEED STOP' } | Select-Object -First 1) -replace '^(.{0,500}).*', '$1')); exit 2 }
  if ($last -notmatch 'LANE-LOOP END: completed') { Post "``$id`` ended without completing: $last"; exit 4 }
}
Say 'all steps done'
