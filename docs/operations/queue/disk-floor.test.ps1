# Ops 2026-11-13: tests of disk-floor.ps1, run-catchup.ps1's floor stop and disk-floor-watch.ps1, with stubbed free space and a
# fake gh (no live volume read decides anything, nothing is posted). Exit 0 = all pass.
param([string]$Work = (Join-Path $env:TEMP ("disk-floor-test-" + [Guid]::NewGuid().ToString('N'))))
$ErrorActionPreference = 'Stop'
$here = Split-Path $MyInvocation.MyCommand.Path
. (Join-Path $here 'disk-floor.ps1')
$null = New-Item -ItemType Directory -Path $Work -Force
$fail = 0
function Check([string]$name, [bool]$ok, $got) { if ($ok) { "PASS  $name  -> $got" } else { "FAIL  $name  -> $got"; $script:fail++ } }
# 1-4. The floor function.
$script:DiskFreeBytes = { param($d) 14.99GB }; $g = Get-DiskFloorReason; Check 'under 15 GB refuses' ($g -eq 'C: has 15.0 GB free, under the 15 GB start floor') $g
$script:DiskFreeBytes = { param($d) 15GB }; $g = Get-DiskFloorReason; Check 'exactly 15 GB starts' ($null -eq $g) $g
$script:DiskFreeBytes = { param($d) throw 'x' }; $g = Get-DiskFloorReason; Check 'unreadable refuses' ($g -eq 'C: free space could not be read') $g
$script:DiskFreeBytes = { param($d) if ($d -eq 'G') { 1GB } else { 99GB } }; $g = Get-DiskFloorReason -Drive 'G'; Check 'another drive is read when named' ("$g" -like 'G: has 1.0 GB free*') $g
# 5. run-catchup.ps1 stops before any verb when the floor refuses (the floor check sits before the first caller call).
$rc = [IO.File]::ReadAllText((Join-Path $here 'run-catchup.ps1'))
$iFloor = $rc.IndexOf('Get-DiskFloorReason'); $iVerb = $rc.IndexOf('Step "validate-')
Check 'run-catchup reads the floor before its first verb' ($iFloor -gt 0 -and $iVerb -gt $iFloor -and $rc.Contains('exit 2 }')) "floor at $iFloor, first verb at $iVerb"
# 6-9. The watcher: posts once under 20, not again while still under, re-arms above 22, posts again on the next fall.
$state = Join-Path $Work 'w.json'; $issue = Join-Path $Work 'issue.txt'; [IO.File]::WriteAllText($issue, '#9999')
$log = Join-Path $Work 'gh.log'; $gh = Join-Path $Work 'gh.cmd'; [IO.File]::WriteAllText($gh, "@echo off`r`necho %* >> `"$log`"`r`nexit /b 0`r`n", [Text.Encoding]::ASCII)
function Watch([double]$gb) { $ErrorActionPreference = 'Continue'; (& (Join-Path $here 'disk-floor-watch.ps1') -State $state -IssueFile $issue -Gh $gh -FreeBytes ([scriptblock]::Create("param(`$d) $gb * 1GB"))) -join ' ' }
$o = Watch 19.5; Check 'under 20 posts' ($o -cmatch 'POSTED' -and (Get-Content $log).Count -eq 1) $o
$o = Watch 18;   Check 'still under: no second post' ($o -cnotmatch 'POSTED' -and (Get-Content $log).Count -eq 1) $o
$o = Watch 21;   Check 'between 20 and 22: not re-armed' ($o -notmatch 're-armed' -and (Get-Content $log).Count -eq 1) $o
$o = Watch 23;   Check 'above 22 re-arms' ($o -match 're-armed') $o
$o = Watch 19;   Check 'falls again: posts again' ($o -cmatch 'POSTED' -and (Get-Content $log).Count -eq 2) $o
$o = (& (Join-Path $here 'disk-floor-watch.ps1') -State (Join-Path $Work 'dry.json') -IssueFile $issue -Gh $gh -DryRun -FreeBytes { param($d) 5GB }) -join ' '
Check 'dry run posts nothing and writes no state' ($o -match 'DRY RUN post' -and (Get-Content $log).Count -eq 2 -and -not (Test-Path (Join-Path $Work 'dry.json'))) $o
"RESULT: $(if ($fail) { "$fail FAILED" } else { 'all passed' })"
exit $fail
