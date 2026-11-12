# Ops 2026-11-12: tests of hold-reader.ps1 against a fake gh that emits what `gh api --paginate --jq '.[]|{id,body}|tojson'`
# emits (one comment per line, every page). No network, no live inbox, no live state. Exit 0 = all pass.
param([string]$Work = (Join-Path $env:TEMP ("hold-reader-test-" + [Guid]::NewGuid().ToString('N'))))
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path $MyInvocation.MyCommand.Path) 'hold-reader.ps1')
$null = New-Item -ItemType Directory -Path $Work -Force
$issueFile = Join-Path $Work 'inbox-issue.txt'; [IO.File]::WriteAllText($issueFile, '#9999')
$fail = 0
function Check([string]$name, $got, [scriptblock]$want) {
  if (& $want $got) { "PASS  $name  -> $(if ($null -eq $got) { '<no hold>' } else { $got })" } else { "FAIL  $name  -> $got"; $script:fail++ }
}
function Day([int]$n, [hashtable]$special) {
  # $n comments, ids 1000+i, oldest first; $special maps an index to a body.
  0..($n - 1) | ForEach-Object {
    $body = if ($special.ContainsKey($_)) { $special[$_] } elseif ($_ % 3) { "Claude-PC: [Ops] line $_`nthe word HOLD: hunt in an Ops post never holds" } else { "Claude-Mac: [Ops] note $_`nno hold here; a HOLD: hunt in the middle of a line never holds" }
    [pscustomobject]@{ id = 1000 + $_; body = $body }
  }
}
function FakeGh([string]$name, $comments, [int]$exit = 0, [int]$first = 0) {
  # A gh.cmd that prints the fixture (only the first $first lines when $first > 0: the old one-page read) and exits $exit.
  $data = Join-Path $Work "$name.jsonl"
  $rows = @($comments | ForEach-Object { $_ | ConvertTo-Json -Compress }); if ($first) { $rows = @($rows | Select-Object -First $first) }
  [IO.File]::WriteAllLines($data, [string[]]$rows, (New-Object Text.UTF8Encoding $false))
  $cmd = Join-Path $Work "$name.cmd"
  [IO.File]::WriteAllText($cmd, "@echo off`r`ntype `"$data`"`r`nexit /b $exit`r`n", [Text.Encoding]::ASCII)
  return $cmd
}
$hold = "Claude-Mac: [Ops] hold for the install.`n`nHOLD: hunt`n`n- rulings follow"
$lift = "Claude-Mac: [Ops] done.`n`nHOLD LIFTED: hunt"

# 1. A 300-comment day, the hold in the last ten: held.
$d = Day 300 @{ 293 = $hold }
Check '300-comment day, hold in the last ten' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c1' $d) -IssueFile $issueFile) { param($g) $g -eq 'inbox post 1293 asks for a hold' }
# 2. The same day through the OLD read (first 100 only): the defect, shown, so this test is known to tell the two apart.
Check 'same day, first page only (the old read) misses it' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c2' $d 0 100) -IssueFile $issueFile) { param($g) $null -eq $g }
# 3. HOLD on page 1, HOLD LIFTED on a later page: not held.
$d = Day 300 @{ 40 = $hold; 251 = $lift }
Check 'hold on page 1, lift on page 3' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c3' $d) -IssueFile $issueFile) { param($g) $null -eq $g }
# 4. Lifted, then held again later: held by the later post.
$d = Day 300 @{ 40 = $hold; 151 = $lift; 288 = $hold }
Check 'hold, lift, hold again' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c4' $d) -IssueFile $issueFile) { param($g) $g -eq 'inbox post 1288 asks for a hold' }
# 5. No hold anywhere in 300 comments (HOLD words in Ops posts and mid-line): not held.
Check 'no hold in 300 comments' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c5' (Day 300 @{})) -IssueFile $issueFile) { param($g) $null -eq $g }
# 6. A hold that does not name the hunt: not held.
$d = Day 120 @{ 110 = "Claude-Mac: [Ops] x`nHOLD: publishers only" }
Check 'hold that does not name the hunt' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c6' $d) -IssueFile $issueFile) { param($g) $null -eq $g }
# 7. A hold at or before InboxAfter is the queue's starting knowledge: not held.
$d = Day 120 @{ 50 = $hold }
Check 'hold before InboxAfter' (Get-HoldReason -InboxAfter 1050 -Gh (FakeGh 'c7' $d) -IssueFile $issueFile) { param($g) $null -eq $g }
# 8. gh fails part-way (non-zero exit, some lines printed): refuses.
Check 'gh exits non-zero' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c8' (Day 150 @{}) 1) -IssueFile $issueFile) { param($g) "$g" -like 'the inbox could not be read*' }
# 9. gh returns nothing: refuses.
Check 'gh returns nothing' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c9' @()) -IssueFile $issueFile) { param($g) "$g" -like 'the inbox could not be read*' }
# 10. The issue file is unreadable: refuses.
Check 'no issue file' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c10' (Day 5 @{})) -IssueFile (Join-Path $Work 'missing.txt')) { param($g) "$g" -like 'the inbox*could not be read*' }
# 11. A body with a BOM and CRLF line ends: held.
$d = Day 110 @{ 105 = ([char]0xFEFF + "Claude-Mac: [Ops] x`r`n`r`nHOLD: hunt and publishers`r`n") }
Check 'BOM and CRLF' (Get-HoldReason -InboxAfter 1000 -Gh (FakeGh 'c11' $d) -IssueFile $issueFile) { param($g) $g -eq 'inbox post 1105 asks for a hold' }
"RESULT: $(if ($fail) { "$fail FAILED" } else { 'all passed' })"
exit $fail
