# Purpose: GOAT Research pilot on T3 (GOAT-EA#223): a 2-member customer batch with the candidate controller, run phase by
#          phase, every step receipted, every refusal a stop. Procedure + stop rules: docs/operations/RESEARCH-PROFILE-PILOT.md.
# Safety class: OPERATOR (reviewed by Claude-Mac before any phase other than -Phase stage/check runs)
# Owner: EA_OPERATIONS
#
# Rules this script enforces:
#   * T3 only: the installation receipt is pinned below; every controller command gets it. Never Banker, T2, Exp 02, Open Lab.
#   * The candidate runs from its own staged copy (never the installed goat-suite, which Banker's FAT loop uses).
#   * Every read of T3's files goes through goat-ro.ps1 (AGENT-RO-01). The only writes are the controller's own commands and
#     this folder's receipts.
#   * Each phase stops on the first refusal and prints the reason; nothing is retried or worked around.
# Phases (run one at a time, in order): stage, preflight, prepare, run, capture -Label <name>, poll.
param(
    [Parameter(Mandatory)][ValidateSet('stage', 'preflight', 'prepare', 'run', 'capture', 'poll')][string]$Phase,
    [string]$Label = 'adhoc'
)
$ErrorActionPreference = 'Stop'
$Root = 'G:\GOAT-Build-Artifacts\claude-pc-ops\pilot-gr-20261012'
$Suite = "$Root\goat-suite-candidate"
$Goat = "$Suite\goat.exe"
$Receipt = "$env:LOCALAPPDATA\GOAT Portfolio Desktop\suite\1ce0354662e44e997a61\installation.json"   # T3 Tester only
$T3Login = '3000110122'
$OpenLab = @('3000109268', '3000109269', '3000109270', '3000109271', '3000109272', '3000109273', '3000109427', '3000109421', '3000110705', '3000110706')
$Data = 'C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\0DC0AC2C6DE123294E3E59C8DC9C3541'
$MonitorProfile = 'GOAT-Studio-5938f6836a814787a24221db64e31e6b'
$CandidateRepo = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\research-profile'
$CandidateCommit = 'a6e39516c57345f1006606a3d6547b7d79633c5a'
$GoatRo = 'G:\GOAT-Build-Artifacts\claude-pc-ops\tools\goat-ro.ps1'
$BatchId = 'pilot-gr-20261012-1'
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'

function Write-PilotReceipt([string]$Name, $Object) {
    $path = Join-Path $Root ("{0}-{1}.json" -f ((Get-Date).ToUniversalTime().ToString('HHmmss')), $Name)
    [System.IO.File]::WriteAllText($path, ($Object | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding $false))
    $path
}
function Invoke-PilotStudio([string]$Name, [string[]]$StudioArgs, [string]$Surface = 'studio') {
    $t0 = (Get-Date).ToUniversalTime()
    $out = & $Goat $Surface --installation $Receipt @StudioArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $text = $out -join "`n"
    $parsed = $null; try { $parsed = $text | ConvertFrom-Json } catch {}
    $path = Write-PilotReceipt $Name ([ordered]@{ called_utc = $t0.ToString('o'); returned_utc = (Get-Date).ToUniversalTime().ToString('o'); exit_code = $code; argv = @($Surface) + $StudioArgs; output = $text })
    [pscustomobject]@{ Code = $code; Json = $parsed; Text = $text; Path = $path }
}
function Stop-Pilot([string]$Why) { "STOP: $Why"; exit 3 }
function Invoke-PilotRead([string]$Name, [string]$Script) {
    $file = Join-Path $Root "ro-$Name.ps1"
    [System.IO.File]::WriteAllText($file, $Script, (New-Object System.Text.UTF8Encoding $true))
    $out = & powershell.exe -NoProfile -NonInteractive -File $GoatRo -ScriptPath $file 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch 'CLIXML|<Objs|</Objs' }
    if ($LASTEXITCODE -ne 0) { Stop-Pilot "goat-ro refused or failed ($Name): $($out -join ' | ')" }
    $out
}
function Get-PilotCapture([string]$Tag) {
    $read = @"
Get-ChildItem -LiteralPath '$Data\MQL5\Profiles\Charts\$MonitorProfile' -File | ForEach-Object { 'monitor ' + `$_.Name + ' ' + (Get-FileHash -LiteralPath `$_.FullName).Hash }
Select-String -LiteralPath '$Data\config\common.ini' -Pattern '^ProfileLast=' -Encoding Unicode | ForEach-Object { 'common.ini ' + `$_.Line }
Test-Path -LiteralPath '$Data\MQL5\Profiles\Charts\GOAT Research' | ForEach-Object { 'goat_research_exists ' + `$_ }
Get-ChildItem -LiteralPath '$Data\MQL5\Profiles\Charts' -Directory | Where-Object { `$_.Name -eq 'GOAT Research' } | ForEach-Object { Get-ChildItem -LiteralPath `$_.FullName -File } | ForEach-Object { 'research ' + `$_.Name + ' ' + `$_.Length + ' ' + (Get-FileHash -LiteralPath `$_.FullName).Hash }
"@
    $lines = Invoke-PilotRead "capture-$Tag" $read
    $path = Write-PilotReceipt "capture-$Tag" ([ordered]@{ tag = $Tag; utc = (Get-Date).ToUniversalTime().ToString('o'); lines = $lines })
    $lines; "receipt: $path"
}

switch ($Phase) {
    'stage' {
        # The candidate controller from the reviewed commit, overlaid on a COPY of the installed suite (bundle-only files kept).
        if (Test-Path $Suite) { Stop-Pilot "stage exists: $Suite" }
        $tree = git -C $CandidateRepo rev-parse "${CandidateCommit}:controller"
        & robocopy 'C:\Users\web\AppData\Local\Programs\GOAT Command Center Optimizer\resources\goat-suite' $Suite /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { Stop-Pilot "robocopy failed $LASTEXITCODE" }
        Rename-Item "$Suite\controller" 'controller-installed'
        git -C $CandidateRepo archive --format=zip -o "$Root\controller-$($CandidateCommit.Substring(0,8)).zip" $CandidateCommit controller
        Expand-Archive "$Root\controller-$($CandidateCommit.Substring(0,8)).zip" -DestinationPath $Suite
        foreach ($f in 'goat_agent.py', 'goat_cockpit_reader.py', 'desktop-agent-workflow.md', 'goat-agent-capabilities.md', 'goat-beta-agent-guide.md', 'goat-beta-start-here.md', 'integrated-sequence-export.md', 'portfolio-exposure-replay.md', 'strategy-library-agent-guide.md') {
            Copy-Item "$Suite\controller-installed\$f" "$Suite\controller\$f"
        }
        Write-PilotReceipt 'stage' ([ordered]@{ commit = $CandidateCommit; controller_tree = $tree; suite = $Suite })
        "staged $CandidateCommit (controller tree $tree)"
    }
    'preflight' {
        $o = Invoke-PilotStudio 'pre-onboarding-status' @('onboarding-status')
        if ($o.Code -ne 0 -or -not $o.Json.ok) { Stop-Pilot "onboarding-status: $($o.Text)" }
        $nm = $o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }
        if ($nm.state -ne 'complete') { Stop-Pilot "native_monitor $($nm.state)" }
        if ($o.Json.result.account.login -ne $T3Login -or $OpenLab -contains $o.Json.result.account.login) { Stop-Pilot "login $($o.Json.result.account.login)" }
        $d = Invoke-PilotStudio 'pre-deploy-preflight' @('deploy-preflight')
        if ($d.Code -ne 0) { Stop-Pilot "deploy-preflight: $($d.Text)" }
        $p = Invoke-PilotStudio 'pre-demo-preflight' @('preflight') 'demo'
        $b = $p.Json.result.broker
        if ($p.Code -ne 0 -or -not $b.demo -or $b.algo_trading -or $b.positions -ne 0 -or $b.orders -ne 0 -or $b.login -ne $T3Login -or $b.tester_state -ne 'idle') { Stop-Pilot "demo preflight: $($p.Text)" }
        $r = Invoke-PilotStudio 'pre-research-profile-status' @('research-profile-status')
        if ($r.Code -ne 0) { Stop-Pilot "research-profile-status: $($r.Text)" }
        $s = Invoke-PilotStudio 'pre-research-status' @('research-status')
        $q = Invoke-PilotStudio 'pre-research-queue' @('research-queue')
        Get-PilotCapture 'before'
        "preflight OK. Migration plan (post it if anything is refused):"
        ($r.Json.result.migration | ConvertTo-Json -Depth 6)
        "research-status: $($s.Path)"; "research-queue: $($q.Path)"
    }
    'prepare' {
        $plan = [ordered]@{ schema_version = 1; members = @(
            [ordered]@{ set_path = 'C:\Users\web\AppData\Local\GOAT Portfolio Desktop\strategy-library-1.49\selections\sel-r3-creek\creek-range-rebound.set'
                tester = [ordered]@{ Expert = 'GOAT-EA\GOAT V1.49.ex5'; Symbol = 'GBPUSD'; Period = 'M1'; Model = 1; ExecutionMode = 0; Optimization = 2; OptimizationCriterion = 6
                    FromDate = '2026.04.01'; ToDate = '2026.10.09'; ForwardMode = 4; ForwardDate = '2026.08.01'; Deposit = 10000; Currency = 'USD'; Leverage = '1:100'; UseLocal = 1; UseRemote = 0; UseCloud = 0; Visual = 0 } },
            [ordered]@{ set_path = 'C:\Users\web\AppData\Local\GOAT Portfolio Desktop\strategy-library-1.49\selections\sel-r3-compass\compass-trend-pullback.set'
                tester = [ordered]@{ Expert = 'GOAT-EA\GOAT V1.49.ex5'; Symbol = 'EURUSD'; Period = 'M1'; Model = 1; ExecutionMode = 0; Optimization = 2; OptimizationCriterion = 6
                    FromDate = '2026.04.01'; ToDate = '2026.10.09'; ForwardMode = 4; ForwardDate = '2026.08.01'; Deposit = 10000; Currency = 'USD'; Leverage = '1:100'; UseLocal = 1; UseRemote = 0; UseCloud = 0; Visual = 0 } }
        ); export = [ordered]@{ SetsToExport = 2; MinScore = 60; TargetDD = 100; AdjustLots = $false; BackOOSDate = '2026.01.01'; MinARF = 0.2; MinSR = 2.5; IncludeBackOOS = $true; IncludeSequenceData = $true } }
        $planPath = "$Root\plan-$BatchId.json"
        [System.IO.File]::WriteAllText($planPath, ($plan | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding $false))
        $o = Invoke-PilotStudio 'prepare-batch' @('prepare-batch', '--batch-id', $BatchId, '--plan', $planPath)
        if ($o.Code -ne 0 -or -not $o.Json.ok) { Stop-Pilot "prepare-batch: $($o.Text)" }
        $state = (Get-Content $Receipt -Raw | ConvertFrom-Json).controller_state_root
        $lines = Invoke-PilotRead 'package' "Get-Content -LiteralPath '$state\packages\$BatchId\studio-plan.json' -Raw | ConvertFrom-Json | ForEach-Object { 'research_profile ' + `$_.research_binding.research_profile; 'startup_monitor ' + [bool]`$_.startup_monitor }"
        $lines
        if (-not ($lines -contains 'research_profile GOAT Research')) { Stop-Pilot 'package not bound to GOAT Research' }
        "prepared $BatchId"
    }
    'run' {
        # Re-run preflight rows 1 and 2, then start with consent. The driver runs detached; poll with -Phase poll.
        $o = Invoke-PilotStudio 'run-onboarding-status' @('onboarding-status')
        if (($o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }).state -ne 'complete') { Stop-Pilot "native_monitor not complete: $($o.Path)" }
        $p = Invoke-PilotStudio 'run-demo-preflight' @('preflight') 'demo'
        $b = $p.Json.result.broker
        if (-not $b.demo -or $b.algo_trading -or $b.positions -ne 0 -or $b.orders -ne 0 -or $b.login -ne $T3Login) { Stop-Pilot "demo preflight: $($p.Path)" }
        $r = Invoke-PilotStudio 'run-batch' @('run-batch', '--job-id', $BatchId, '--max-seconds', '7200', '--mt5-restart-consent')
        if ($r.Code -ne 0 -or -not $r.Json.ok) { Stop-Pilot "run-batch: $($r.Text)" }
        "run-batch accepted: $($r.Path)"
    }
    'poll' {
        $d = Invoke-PilotStudio "poll-driver-$Label" @('batch-driver-status', '--job-id', $BatchId)
        $s = Invoke-PilotStudio "poll-batch-$Label" @('batch-status', '--batch-id', $BatchId)
        $d.Text; '---'; $s.Text
    }
    'capture' { Get-PilotCapture $Label }
}
