# Ops 2026-11-13 (Claude-Mac goatai#2750 6845747846): post ONCE on the inbox when C: falls under 20 GB free; re-arm only after
# it is back above 22 GB, so a level hovering near 20 posts once, not every run. Meant for a scheduled task every 10 minutes.
# The start floor itself (15 GB) is disk-floor.ps1; this is the early warning above it. -DryRun prints the post instead.
param([double]$WarnGB = 20, [double]$RearmGB = 22, [string]$Drive = 'C',
      [string]$State = 'G:\GOAT-Build-Artifacts\claude-pc-ops\state\disk-floor-watch.json',
      [string]$IssueFile = 'G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt',
      [string]$Gh = 'C:\Program Files\GitHub CLI\gh.exe', [switch]$DryRun, [scriptblock]$FreeBytes = { param($d) (Get-Volume -DriveLetter $d -ErrorAction Stop).SizeRemaining })
$now = [DateTime]::UtcNow
try { $gb = [double](& $FreeBytes $Drive) / 1GB } catch { '{0:yyyy-MM-ddTHH:mm:ss}Z DISK-WATCH: {1}: free space could not be read' -f $now, $Drive; exit 2 }
$st = @{ posted = $false }
try { if (Test-Path -LiteralPath $State) { $o = [IO.File]::ReadAllText($State) | ConvertFrom-Json -ErrorAction Stop; $st.posted = [bool]$o.posted } } catch {}
$line = '{0:yyyy-MM-ddTHH:mm:ss}Z DISK-WATCH: {1}: {2:N1} GB free (warn under {3}, re-arm above {4}); posted already: {5}' -f $now, $Drive, $gb, $WarnGB, $RearmGB, $st.posted
if ($gb -lt $WarnGB -and -not $st.posted) {
  $body = 'Claude-PC: [Watch] **{0}: is at {1:N1} GB free, under {2} GB.** Batch starts stop at 15 GB (disk-floor.ps1). Writers: run folders under Common\Files\GOAT, catch-up evidence in the suite, tester agent caches. This post repeats only after {0}: is back above {3} GB.' -f $Drive, $gb, $WarnGB, $RearmGB
  if ($DryRun) { "$line`nDRY RUN post: $body"; exit 0 }
  $issue = [IO.File]::ReadAllText($IssueFile).Trim().TrimStart('#')
  $f = Join-Path $env:TEMP ('disk-watch-{0:HHmmss}.md' -f $now); [IO.File]::WriteAllText($f, $body, (New-Object Text.UTF8Encoding $false))
  $null = & $Gh api "repos/algogoat/goatai/issues/$issue/comments" -F "body=@$f" 2>$null
  if ($LASTEXITCODE -ne 0) { "$line; POST FAILED (gh exit $LASTEXITCODE)"; exit 3 }
  $st.posted = $true; "$line; POSTED"
} elseif ($gb -gt $RearmGB -and $st.posted) { $st.posted = $false; "$line; re-armed" }
else { $line }
if (-not $DryRun) { [IO.File]::WriteAllText($State, (@{ posted = $st.posted; at = $now.ToString('o'); free_gb = [Math]::Round($gb, 2) } | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false)) }
exit 0
