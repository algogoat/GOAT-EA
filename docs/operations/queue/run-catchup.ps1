# Ops 2026-11-11: validate -> prepare -> start one catch-up plan on T3 or Banker (B54 controller tree), then drive it with
# lane-loop until it ends. Any refusal stops before the next step (guard refusal = stop). One line per step.
param([Parameter(Mandatory)][ValidateSet('t3', 'banker')][string]$Machine, [Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][string]$Plan, [double]$Hours = 6)
$tool = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\b54-identity\controller\demo_agent.py'
$caller = @{ t3 = 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\t3-call.ps1'; banker = 'G:\GOAT-Build-Artifacts\interim-ops-20261108\parallel-readiness\banker-call.ps1' }[$Machine]
$dir = Split-Path $caller
# 2026-11-13: no catch-up starts while C: is under the disk start floor (disk-floor.ps1, beside this file).
. (Join-Path $PSScriptRoot 'disk-floor.ps1')
$floor = Get-DiskFloorReason
if ($floor) { ('{0:HH:mm:ss}Z RUN-CATCHUP STOP before validate: {1}' -f [DateTime]::UtcNow, $floor); exit 2 }
function Step([string]$name, [string[]]$a) {
  $null = & $caller -Name $name -Tool $tool -Chars 1 @a
  $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir "$name.out") -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
  if (-not $o -or -not $o.ok) { $e = if ($o) { "$($o.code): $($o.error)" } else { (Get-Content -LiteralPath (Join-Path $dir "$name.err") -Tail 2 -ErrorAction SilentlyContinue) -join ' ' }; ('{0:HH:mm:ss}Z RUN-CATCHUP STOP at {1}: {2}' -f [DateTime]::UtcNow, $name, "$e".Substring(0, [Math]::Min(500, "$e".Length))); exit 2 }
  $o
}
$v = Step "validate-$Id" @('catchup-validate', '--plan', $Plan)
('{0:HH:mm:ss}Z validate ok: {1} member(s); {2}' -f [DateTime]::UtcNow, $v.result.member_count, "$($v.result.summary.plain)".Substring(0, [Math]::Min(240, "$($v.result.summary.plain)".Length)))
if ([int]$v.result.member_count -lt 1) { ('{0:HH:mm:ss}Z RUN-CATCHUP STOP: nothing to run' -f [DateTime]::UtcNow); exit 2 }
$null = Step "prepare-$Id" @('catchup-prepare', '--catchup-id', $Id, '--plan', $Plan)
$s = Step "start-$Id" @('catchup-start', '--catchup-id', $Id, '--max-seconds', '3600')
('{0:HH:mm:ss}Z started {1}: {2}' -f [DateTime]::UtcNow, $Id, $s.result.status)
if ($Machine -eq 'banker') { & 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\lane-loop.ps1' -Kind catchup -Id $Id -PollSec 120 -Hours $Hours -Tool $tool -Caller $caller }
else { & 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\lane-loop.ps1' -Kind catchup -Id $Id -PollSec 120 -Hours $Hours -Tool $tool }