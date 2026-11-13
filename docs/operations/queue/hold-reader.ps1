# Ops 2026-11-12: the one hold reader for every machine queue (dot-source it; no copies of the logic).
#
# Hold rule (Claude-Mac goatai#2750 6816295031): only a Claude-Mac line that begins "HOLD:" and names the hunt holds; a later
# Claude-Mac line that begins "HOLD LIFTED:" lifts it.
#
# Why this file exists (goatai#2750 6831947464): the reader used to ask for `comments?per_page=100&since=<14 h ago>` and
# read that single page. GitHub returns the oldest first, so on a day with more than 100 comments every recent post was
# outside the page, and a hold posted at 18:00:35Z on 2026-11-12 was not seen at 18:02Z. This reader takes every page
# (gh --paginate), one comment per output line, and refuses (fails closed) when the read is not clean.
# 2026-11-13: a start is also held while C: is under the disk start floor (disk-floor.ps1, beside this file), so every queue
# that asks this reader before a start gets the floor too.
. (Join-Path $PSScriptRoot 'disk-floor.ps1')
$script:HoldGh = 'C:\Program Files\GitHub CLI\gh.exe'
$script:HoldIssueFile = 'G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt'

function Read-HoldComments([string]$Issue, [int]$Hours = 48, [string]$Gh = $script:HoldGh) {
  # Every comment of the window, all pages. Returns objects (id, body), or throws when the read is not clean.
  $since = [DateTime]::UtcNow.AddHours(-$Hours).ToString('yyyy-MM-ddTHH:mm:ssZ')
  $lines = @(& $Gh api --paginate --method GET "repos/algogoat/goatai/issues/$Issue/comments" -f per_page=100 -f "since=$since" --jq '.[] | {id, body} | tojson' 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "gh exit $LASTEXITCODE" }
  $rows = @($lines | Where-Object { "$_".Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
  if (-not $rows.Count) { throw 'no comments returned' }
  foreach ($r in $rows) { if (-not $r.id) { throw 'a comment without an id' } }
  return $rows
}

function Find-Hold($Comments, [long]$InboxAfter) {
  # Pure. The id of the Claude-Mac post whose hold is in force after $InboxAfter, or 0.
  $held = [long]0
  foreach ($cm in @($Comments | Where-Object { [long]$_.id -gt $InboxAfter -and "$($_.body)" -match '^\uFEFF?Claude-Mac' } | Sort-Object { [long]$_.id })) {
    foreach ($ln in ("$($cm.body)" -split "`r?`n")) {
      if ($ln -match '^\s*HOLD LIFTED:') { $held = [long]0 } elseif ($ln -match '^\s*HOLD:.*\bhunt\b') { $held = [long]$cm.id }
    }
  }
  return $held
}

function Get-HoldReason([long]$InboxAfter, [string]$Gh = $script:HoldGh, [string]$IssueFile = $script:HoldIssueFile, [int]$Hours = 48) {
  # $null = no hold. Any string = do not start (a hold, a read that cannot be trusted, or C: under the disk start floor).
  $disk = Get-DiskFloorReason
  if ($disk) { return $disk }
  try {
    $issue = [IO.File]::ReadAllText($IssueFile).Trim().TrimStart('#')
    if ($issue -notmatch '^\d+$') { return 'the inbox issue number could not be read' }
    $rows = Read-HoldComments -Issue $issue -Hours $Hours -Gh $Gh
  } catch { return "the inbox could not be read ($($_.Exception.Message))" }
  try { $held = Find-Hold $rows $InboxAfter } catch { return 'the inbox check threw' }
  if ($held) { return "inbox post $held asks for a hold" }
  return $null
}
