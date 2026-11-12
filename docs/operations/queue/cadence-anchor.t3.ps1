# Round 14a cadence walk-forward, SECOND SET (prereg goatai#2822 and its T3 amendment): ONE anchor on T3, from its finished seed batch to its trade re-tests.
# A copy of round14a-cadence\run\cadence-anchor.ps1 as it stood on 2026-11-12 (catch-up status at result.catchup, members[].result.summary.evidenceEnd; hold = Claude-Mac "HOLD:" lines naming the hunt).
# Changed for T3 only: the caller (t3-call.ps1), the ids (cad14a-t3-*), the journal names (j-cad14a-t3-*), T3's terminal data folder, the helper folder (queue\tools), the cell count in the yield line.
#   a. the seed batch is completed; T3 is free AND its monitor is reporting; no hold in the inbox
#   b. cad_promote.ps1 (dry run, then real); cad_prove_plan.ps1
#   c. prove-chain.ps1 (free terminal, name-set check, inbox hold check, prepare-batch, run-batch); wait for the batch to end
#   d. batch-status read by prove_summary.py (an unverified export stops everything); export-qualification --write; evidence-scan
#   e. "q" catch-up: every export over the bar, evidence end = the anchor (the product's verdict at the anchor); journal capture
#   f. cadence_choice.py -> anchors\<mmdd>\choice.json (primary and secondary file per cell, or flat, with every candidate)
#   g. "t" catch-up: the chosen files re-tested to -TradeEnd (one re-test per file serves every policy); journal capture
#   h. one yield line; anchors\<mmdd>\done.json
# Every verb goes through the B54 controller tree. Any refusal ends the script with ONE "Claude-PC: [Watch]" inbox post.
# A step whose output already exists is not repeated (resume); to redo a step, move its outputs to superseded\ (RUN-cadence.md).
# -Retry <suffix>: after a refused prepare, the batch and catch-up ids of this anchor get the suffix (a refused prepare keeps its package).
# -WhatIf: prints every verb, script and path this anchor would use and calls nothing (no verb, no gate read, no post).
param([Parameter(Mandatory)][ValidatePattern('^\d{4}$')][string]$Anchor, [Parameter(Mandatory)][long]$InboxAfter, [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$TradeEnd = '2026-11-06',
      [ValidatePattern('^[A-Za-z0-9]{0,6}$')][string]$Retry = '', [double]$Hours = 8, [switch]$WhatIf)
$here = Split-Path $MyInvocation.MyCommand.Path; $cad = Split-Path $here; $adir = Join-Path $cad "anchors\$Anchor"
$ops = 'G:\GOAT-Build-Artifacts\claude-pc-ops\queue\tools'
$tool = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\b54-identity\controller\demo_agent.py'
$caller = 'C:\GOAT-Evidence\d1-hunt-20261107\t3-seed\t3-call.ps1'; $dir = Split-Path $caller
$data = '0DC0AC2C6DE123294E3E59C8DC9C3541'; $py = 'C:\GOAT\python313-3.13.16\python.exe'; $until = [DateTime]::UtcNow.AddHours($Hours)
$close = 'G:\GOAT-Build-Artifacts\interim-ops-20261108\round13a\close'
$env:TEMP = 'G:\GOAT-Build-Artifacts\claude-pc-ops\tmp-20261024'; $env:TMP = $env:TEMP
$bs = [string][char]92; $utf8 = New-Object Text.UTF8Encoding $false
$sfx = if ($Retry) { "-$Retry" } else { '' }
$anchorIso = '2026-' + $Anchor.Substring(0, 2) + '-' + $Anchor.Substring(2)
$seedId = "cad14a-t3-$Anchor-seed"; $proveBase = "cad14a-t3-$Anchor-prove"; $proveId = "$proveBase$sfx"; $qId = "cad14a-t3-$Anchor-q$sfx"; $tId = "cad14a-t3-$Anchor-t$sfx"
$seedLineage = Join-Path $adir 'seed-lineage.json'; $provePlan = Join-Path $adir "prove-plan-$proveBase.json"; $proveLineage = Join-Path $adir "prove-lineage-$proveBase.json"
$receipt = Join-Path $adir "promote-$seedId.json"; $summary = Join-Path $adir "prove-summary-$proveId.json"
$qPlan = Join-Path $adir "catchup-plan-$qId.json"; $tPlan = Join-Path $adir "catchup-plan-$tId.json"; $choice = Join-Path $adir 'choice.json'; $doneFile = Join-Path $adir 'done.json'
# Say and Would write to the host, never to the pipeline: several functions below return an object, and a line written to the
# pipeline inside them would be swallowed (or returned with the object). Start the script with powershell.exe -File and redirect the process output.
function Say($m) { Write-Host ('{0:HH:mm:ss}Z CADENCE {1}: {2}' -f [DateTime]::UtcNow, $Anchor, $m) }
function Would($m) { Write-Host "  WOULD $m" }
function Post($m) {
  if ($WhatIf) { return }
  try { $issue = [IO.File]::ReadAllText('G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt').Trim().TrimStart('#'); $f = Join-Path $env:TEMP ("cadence-$Anchor-{0}.md" -f [DateTime]::UtcNow.ToString('HHmmss'))
        [IO.File]::WriteAllText($f, ("Claude-PC: [Watch] **Cadence walk-forward, second set, anchor $Anchor on T3 stopped.** " + $m), $utf8); $null = & 'C:\Program Files\GitHub CLI\gh.exe' api "repos/algogoat/goatai/issues/$issue/comments" -F "body=@$f" 2>$null } catch {}
}
function Halt($m) { Say "STOP: $m"; Post $m; exit 2 }
function Busy {
  $null = & $caller -Name 'cadt3-rs' -Tool $tool -Chars 1 research-status
  $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir 'cadt3-rs.out') -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
  if (-not $o -or -not $o.ok) { return $null }
  $a = $o.result.activity
  # As prove-chain.ps1 (11-11 19:20Z): while MT5 is up the terminal counts as free only when its monitor is reporting.
  $m = $o.result.monitor; $t = $o.result.terminal
  if ($t -and $t.running -and $m -and ("$($m.state)" -eq 'silent' -or [double]$m.heartbeat_age_seconds -gt 60)) { return $true }
  return ([bool]$o.result.driver.alive -or [bool]$a.current_member -or ("$($a.status)" -in 'running', 'starting', 'queued', 'active'))
}
function WaitFree([string]$what) {
  if ($WhatIf) { Would "wait until T3 is free and its monitor is reporting (research-status as cadt3-rs, twice in a row, 75 s apart) before $what"; return }
  $free = 0
  while ($free -lt 2) {
    if ([DateTime]::UtcNow -ge $until) { Halt "hours elapsed while waiting for a free terminal before $what" }
    $b = Busy; if ($b -eq $false) { $free++ } else { $free = 0 }
    if ($free -lt 2) { Start-Sleep -Seconds 75 }
  }
}
function Held {
  # The one hold reader (every page of the inbox, fails closed): queue\tools\hold-reader.ps1, tested by hold-reader.test.ps1.
  try { . 'G:\GOAT-Build-Artifacts\claude-pc-ops\queue\tools\hold-reader.ps1'; return (Get-HoldReason -InboxAfter $InboxAfter) } catch { return 'the inbox check threw' }
}
function HoldCheck([string]$what) {
  if ($WhatIf) { Would "re-read the inbox for a hold after post $InboxAfter before $what"; return }
  $h = Held; if ($h) { Halt "Not started: $what. Reason: $h." }
}
function Verb([string]$name, [string[]]$a) {
  if ($WhatIf) { Would ("verb  & `"$caller`" -Name $name -Tool `"$tool`" -Chars 1 " + ($a -join ' ') + "   -> $dir\$name.out"); return $null }
  $null = & $caller -Name $name -Tool $tool -Chars 1 @a
  $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir "$name.out") -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
  if (-not $o -or -not $o.ok) {
    $e = if ($o) { "$($o.code): $($o.error)" } else { (Get-Content -LiteralPath (Join-Path $dir "$name.err") -Tail 2 -ErrorAction SilentlyContinue) -join ' ' }
    Halt ("verb output $name was refused: " + "$e".Substring(0, [Math]::Min(400, "$e".Length)))
  }
  $o
}
function Saved([string]$name) { $o = $null; try { $o = Get-Content -LiteralPath (Join-Path $dir "$name.out") -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop } catch {}; if ($o -and $o.ok) { $o } else { $null } }
function Journal([string]$name, [int]$members) {
  # The tester journal, before anything else starts an optimisation on this terminal (MT5 rewrites the day log at each start).
  $list = Join-Path $close ('dumps' + $bs + 'lists' + $bs + $name + '.txt')
  $log = 'C:\Users\web\AppData\Roaming\MetaQuotes\Terminal' + $bs + $data + $bs + 'Tester' + $bs + 'logs' + $bs + (Get-Date).ToString('yyyyMMdd') + '.log'
  if ($WhatIf) { Would "journal  $close\tools\run_grep.ps1 -Name $name -ListFile $list  (gate read of $log)  -> $close\dumps\$name.out; stop if it holds fewer 'Test passed in' lines than members"; return }
  [IO.File]::WriteAllLines($list, [string[]]@($log))
  $patterns = @(('EA_Desc=C[0-9a-f]{16}_' + $bs + 'd{5}'), 'testing of Experts', 'Test passed in', 'generating based on real ticks', 'no real ticks|real ticks.*absent|ticks.*discarded|ticks.*mismatch|failed.*(?:history|ticks)|cannot.*(?:history|ticks)|history.*not found|tick.*unavailable')
  try { $null = & (Join-Path $close ('tools' + $bs + 'run_grep.ps1')) -Name $name -ListFile $list -Pattern $patterns } catch { Halt "The tester journal $name was not captured ($_). Nothing further was started on T3." }
  $dump = Join-Path $close ('dumps' + $bs + $name + '.out')
  $passed = @(Select-String -LiteralPath $dump -Pattern 'Test passed in' -ErrorAction SilentlyContinue).Count
  Say "journal captured: $dump sha256 $((Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLower()); Test passed lines $passed for $members member(s)"
  if ($passed -lt $members) { Halt "The tester journal $name holds $passed Test passed lines for $members members ($dump). Nothing further was started on T3." }
}
function Catchup([string]$id, [string]$plan, [string]$end, [string[]]$sets, [string]$journal) {
  # One catch-up: plan (create-only), run-catchup.ps1 (validate, prepare, start, lane-loop), journal, saved catchup-status.
  $done = Saved "cs-$id"
  if ($done -and "$($done.result.catchup.status)" -eq 'completed') { Say "catch-up ${id}: completed earlier (cs-$id.out); not repeated"; return $done }
  if ($WhatIf) {
    Would "write $plan  = {schema_version: 1, evidence_end: `"$end`", job_timeout_seconds: 1800, sets: [<the SET paths>]}"
    Would "run   $ops\run-catchup.ps1 -Machine t3 -Id $id -Plan $($plan.Replace($bs, '/')) -Hours 6   (catchup-validate as validate-$id, catchup-prepare as prepare-$id, catchup-start as start-$id, then lane-loop.ps1 -Kind catchup)"
    Journal $journal 0
    $null = Verb "cs-$id" @('catchup-status', '--catchup-id', $id); return $null
  }
  if (Test-Path -LiteralPath $plan) { Halt "the catch-up plan $plan exists already and $id has no completed status saved: inspect (RUN-cadence.md, resume)" }
  WaitFree "catch-up $id"
  [IO.File]::WriteAllText($plan, (([ordered]@{ schema_version = 1; evidence_end = $end; job_timeout_seconds = 1800; sets = @($sets) }) | ConvertTo-Json -Depth 4), $utf8)
  Say "catch-up ${id}: $($sets.Count) export(s), evidence end $end"
  $out = & (Join-Path $ops 'run-catchup.ps1') -Machine t3 -Id $id -Plan ($plan.Replace($bs, '/')) -Hours 6 2>&1
  $out | Select-Object -Last 4 | ForEach-Object { Write-Host "  $_" }
  $lastLine = "$($out | Select-Object -Last 1)"
  if (($out -join "`n") -match 'RUN-CATCHUP STOP' -or $lastLine -notmatch 'LANE-LOOP END: completed') { Halt "Catch-up $id did not complete: $lastLine" }
  Journal $journal $sets.Count
  $st = Verb "cs-$id" @('catchup-status', '--catchup-id', $id)
  if ("$($st.result.catchup.status)" -ne 'completed') { Halt "Catch-up $id reads $($st.result.catchup.status) after the lane loop ended" }
  $bad = @($st.result.catchup.members | Where-Object { $_.status -ne 'completed' })
  if ($bad.Count) { Say "catch-up ${id}: $($bad.Count) member(s) not completed: $(($bad | ForEach-Object { "$($_.alias) $($_.status)" }) -join '; ')" }
  $ends = @($st.result.catchup.members | Where-Object { $_.status -eq 'completed' } | ForEach-Object { "$($_.result.summary.evidenceEnd)" } | Sort-Object -Unique); if ($ends.Count -ne 1 -or $ends[0] -ne $end) { Halt "Catch-up $id ended $($ends -join ',')), not $end" }
  $st
}
function Finish([string]$line) {
  if ($WhatIf) { Would "write $doneFile and print the yield line"; return }
  [IO.File]::WriteAllText($doneFile, (([ordered]@{ anchor = $anchorIso; finished_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'); prove = $proveId; q = $qId; t = $tId; trade_end = $TradeEnd; yield = $line }) | ConvertTo-Json), $utf8)
  Say "YIELD $line"; exit 0
}
function Choose([string]$bsOut, [string]$esOut, [string]$qOut, [string]$note) {
  if ($WhatIf) { Would "choice  $py -I $here\cadence_choice.py $seedLineage $bsOut $esOut $qOut $choice `"$note`""; return $null }
  if (-not (Test-Path -LiteralPath $choice)) {
    $o = & $py -I (Join-Path $here 'cadence_choice.py') $seedLineage $bsOut $esOut $qOut $choice $note 2>&1; $code = $LASTEXITCODE
    $o | ForEach-Object { Write-Host "  $_" }
    if ($code -ne 0) { Halt "The file choice of anchor $Anchor failed (exit $code): $($o | Select-Object -Last 1)" }
  } else { Say "choice.json exists: used as it is" }
  Get-Content -LiteralPath $choice -Raw | ConvertFrom-Json
}

if (-not $WhatIf -and (Test-Path -LiteralPath $doneFile)) { Say "done.json exists: anchor finished earlier"; exit 0 }
if (-not (Test-Path -LiteralPath $seedLineage)) { "STOP: no anchor folder $adir"; exit 5 }
$nCells = @(Get-Content -LiteralPath $seedLineage -Raw | ConvertFrom-Json | ForEach-Object { $_ }).Count
Say ("start" + $(if ($WhatIf) { ' (WHAT-IF: nothing is called)' } else { '' }) + "; anchor $anchorIso; seed $seedId; Prove $proveId; q $qId (evidence end $anchorIso); t $tId (evidence end $TradeEnd)")

# ---- a. seed batch completed, free terminal, no hold ----
$ss = Verb "cst-$seedId" @('seed-status', '--batch-id', $seedId)
if (-not $WhatIf) { $st = "$($ss.result.seed.status)"; if (-not $st) { $st = "$($ss.result.status)" }; if ($st -ne 'completed') { Halt "The seed batch $seedId reads '$st', not completed" } }
WaitFree 'promotion'
HoldCheck "promotion of $seedId"

# ---- b. promotion (dry run, then real) and the Prove plan ----
$promoted = -1
if (-not $WhatIf -and (Test-Path -LiteralPath $receipt)) {
  $promoted = @((Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json) | ForEach-Object { $_ } | Where-Object { $_.note -eq 'promoted' }).Count
  Say "promotion receipt exists ($promoted promoted): not repeated"
} else {
  foreach ($mode in 'dry', 'real') {
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $cad 'cad_promote.ps1'), '-Anchor', $Anchor); if ($mode -eq 'dry') { $a += '-DryRun' }
    if ($WhatIf) { Would ("run   powershell.exe " + ($a -join ' ') + $(if ($mode -eq 'dry') { "   -> $adir\promote-dryrun-$seedId.json" } else { "   -> $receipt (seed-report as seed-report-$seedId, one seed-promote per candidate as spc14a-$Anchor-<alias>-k1)" })); continue }
    if ($mode -eq 'dry' -and (Test-Path -LiteralPath (Join-Path $adir "promote-dryrun-$seedId.json"))) { Say 'dry-run promotion file exists: not repeated'; continue }
    $out = & powershell.exe @a 2>&1; $code = $LASTEXITCODE; $last = "$($out | Select-Object -Last 1)"
    Say "promote ($mode): exit $code; $last"
    if ($code -ne 0 -or ($out -join "`n") -match '(?m)^STOP' -or $last -match 'failed [1-9]') { Halt "Promotion ($mode) of ${seedId}: exit $code; $($last.Substring(0, [Math]::Min(400, $last.Length)))" }
    if ($mode -eq 'real' -and $last -match 'promoted rows (\d+)') { $promoted = [int]$Matches[1] }
  }
}
if (-not $WhatIf -and $promoted -le 0) {
  $null = Choose '-' '-' '-' 'no seed candidate was promoted at this anchor: every cell is flat'
  Finish "anchor ${Anchor}: promoted 0 of $nCells cells; no Prove batch; every cell flat"
}
if ($WhatIf) { Would "run   powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cad\cad_prove_plan.ps1 -Anchor $Anchor   -> $provePlan and $proveLineage" }
elseif (-not (Test-Path -LiteralPath $provePlan)) {
  $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $cad 'cad_prove_plan.ps1') -Anchor $Anchor 2>&1; $code = $LASTEXITCODE
  $out | ForEach-Object { Write-Host "  $_" }
  if ($code -ne 0 -or -not (Test-Path -LiteralPath $provePlan)) { Halt "The Prove plan of anchor $Anchor was not built (exit $code): $($out | Select-Object -Last 1). If the seed SETs fell into several input-name groups the plans carry -g<N>: run those by hand." }
} else { Say 'Prove plan exists: not rebuilt' }

# ---- c. the Prove batch ----
$planFwd = $provePlan.Replace($bs, '/')
if ($WhatIf) {
  Would "run   $ops\prove-chain.ps1 -Machine t3 -Steps `"$proveId|$planFwd`" -InboxAfter $InboxAfter   (waits for a free terminal with a reporting monitor; $ops\prove-name-sets.ps1 -Plan $provePlan must print UNIFORM; inbox hold check; prepare-batch --batch-id $proveId --plan $planFwd as pb-$proveId; run-batch --batch-id $proveId --max-seconds 14400 as rb-$proveId; then 300 s)"
} elseif (Saved "rb-$proveId") { Say "run-batch of $proveId was accepted earlier (rb-$proveId.out): not started again" }
else {
  $out = & (Join-Path $ops 'prove-chain.ps1') -Machine t3 -Steps @("$proveId|$planFwd") -InboxAfter $InboxAfter 2>&1; $code = $LASTEXITCODE
  $out | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
  if ($code -ne 0 -or ($out -join "`n") -notmatch "started $([regex]::Escape($proveId))") { Say "STOP: the Prove batch $proveId was not started (exit $code); prove-chain posts its own [Watch] line"; exit 2 }
}
WaitFree "reading the Prove batch $proveId"

# ---- d. read the batch ----
$bsf = Verb "bsf-$proveId" @('batch-status', '--batch-id', $proveId)
$bsOut = Join-Path $dir "bsf-$proveId.out"; $esOut = '-'; $sets = @(); $files = 0
if ($WhatIf) {
  Would "read  $py -I $ops\prove_summary.py $bsOut $proveLineage $seedLineage $summary   (exit 3 = unverified exports: stop)"
  $null = Verb "eq-$proveId" @('export-qualification', '--source', '<the one run folder ...\Common\Files\GOAT\R<12 hex> named in the batch status>', '--write')
  $null = Verb "es-$proveId" @('evidence-scan', '--source', '<the same run folder>')
  Would "the q sets = evidence-scan exports with status 'behind' (over the export bar and eligible for a re-test)"
  $esOut = Join-Path $dir "es-$proveId.out"
} else {
  if (-not (Test-Path -LiteralPath $summary)) {
    $out = & $py -I (Join-Path $ops 'prove_summary.py') $bsOut $proveLineage $seedLineage $summary 2>&1; $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "  $_" }; $lastLine = "$($out | Select-Object -Last 1)"
    if ($code -eq 3) { Halt "Batch $proveId has unverified exports (inherited inputs, GOAT-EA#315): nothing was re-tested. $lastLine" }
    if ($code -ne 0) { Halt "Batch ${proveId}: the batch status could not be read against its lineage. $lastLine" }
  } else { Say 'Prove summary exists: used as it is' }
  $s = Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
  if ("$($s.batch_status)" -in 'running', 'starting', 'pending', 'reserved') { Halt "Batch $proveId is $($s.batch_status), not finished" }
  if ([int]$s.unverified -gt 0) { Halt "Batch $proveId has $($s.unverified) unverified export(s)" }
  if (@($s.lost).Count) { Say "${proveId}: LOST run(s), not judged: $((@($s.lost) | ForEach-Object { "$($_.index) $($_.symbol) $($_.template)" }) -join '; ')" }
  $files = [int]$s.files
  if ($files -gt 0) {
    $roots = @($s.run_roots); if ($roots.Count -ne 1) { Halt "Batch ${proveId}: $($roots.Count) run folders found, expected 1" }
    if (-not (Saved "es-$proveId")) { $null = Verb "eq-$proveId" @('export-qualification', '--source', $roots[0], '--write') }
    $es = Saved "es-$proveId"; if (-not $es) { $es = Verb "es-$proveId" @('evidence-scan', '--source', $roots[0]) }
    $esOut = Join-Path $dir "es-$proveId.out"
    $sets = @($es.result.exports | Where-Object { $_.status -eq 'behind' } | ForEach-Object { $_.set_path })
    $other = @($es.result.exports | Where-Object { $_.threshold_passing -and $_.status -ne 'behind' })
    Say "${proveId}: $files export file(s), $($sets.Count) over the bar and behind$(if ($other.Count) { "; $($other.Count) over the bar with status $(($other | ForEach-Object { $_.status } | Sort-Object -Unique) -join ',') (not re-tested: they get no verdict)" })"
  } else { Say "${proveId}: no export file" }
}

# ---- e. "q": the product's verdict at the anchor ----
$qOut = '-'
if ($WhatIf) { $null = Catchup $qId $qPlan $anchorIso @() "j-cad14a-t3-$Anchor-q$sfx"; $qOut = Join-Path $dir "cs-$qId.out" }
elseif ($sets.Count) { $null = Catchup $qId $qPlan $anchorIso $sets "j-cad14a-t3-$Anchor-q$sfx"; $qOut = Join-Path $dir "cs-$qId.out" }
else { Say 'no export over the bar: no "q" catch-up' }

# ---- f. the file choice ----
$note = if ($files -eq 0 -and -not $WhatIf) { 'the Prove batch kept no export file' } else { '' }
$ch = Choose $bsOut $esOut $qOut $note

# ---- g. "t": the chosen files through the trade weeks ----
$tsets = if ($WhatIf) { @() } else { @($ch.t_sets) }
if ($anchorIso -ge $TradeEnd) {
  Say "no `"t`" catch-up: the anchor $anchorIso has no closed trade week by $TradeEnd (run it with a later -TradeEnd once Friday $(([DateTime]::ParseExact($anchorIso, 'yyyy-MM-dd', $null)).AddDays(7).ToString('yyyy-MM-dd')) has closed; `"q`" already carries the files to $anchorIso)"
} elseif ($WhatIf) { $null = Catchup $tId $tPlan $TradeEnd @() "j-cad14a-t3-$Anchor-t$sfx" }
elseif ($tsets.Count) { $null = Catchup $tId $tPlan $TradeEnd $tsets "j-cad14a-t3-$Anchor-t$sfx" }
else { Say 'no file chosen: no "t" catch-up' }

# ---- h. yield ----
if ($WhatIf) { Finish ''; Say 'WHAT-IF end: nothing was called'; exit 0 }
Finish ("anchor ${Anchor}: promoted $promoted of $nCells cells; Prove export files $files; over the bar $($sets.Count); primary files $($ch.primary_files); secondary files $($ch.secondary_files); flat (primary) $(@($ch.flat_primary).Count); t re-tests $(if ($anchorIso -ge $TradeEnd) { 0 } else { $tsets.Count })")
