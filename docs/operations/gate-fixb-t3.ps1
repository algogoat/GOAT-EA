# Purpose: The fix-B gates on T3 against the merged integration head (GOAT-EA#222 + #223, merge 3cb9aa92):
#          gate A (close-terminal variant) and gate B (batch-start variant), phase by phase, every step receipted,
#          every refusal a stop. Reviewed by sha before any phase other than stage runs (Claude-Mac goatai#2350 6123126270).
# Safety class: OPERATOR
# Owner: EA_OPERATIONS
#
# Rules this script enforces (the same as pilot-gr-t3.ps1):
#   * T3 only: the installation receipt is pinned; never Banker, T2, Exp 02, Open Lab.
#   * The candidate runs from its own staged copy (git archive of the merged commit), never the installed goat-suite.
#   * Every read of T3's files goes through goat-ro.ps1 (AGENT-RO-01); the only writes are the controller's own commands
#     and this folder's receipts.
#   * The T3 throttle runs pinned to CPUs 20-23 at Idle (Claude-Mac 6123131876); started separately with -Cpus 4.
#   * Each phase stops on the first refusal; nothing is retried or worked around.
# Phases, in order: stage, preflight, a1, a2, a3, a4, prepare, run, poll, capture -Label <name>.
param(
    [Parameter(Mandatory)][ValidateSet('stage', 'preflight', 'a1', 'a2', 'a3', 'a4', 'prepare', 'run', 'poll', 'capture')][string]$Phase,
    [string]$Label = 'adhoc'
)
$ErrorActionPreference = 'Stop'
$Root = 'G:\GOAT-Build-Artifacts\claude-pc-ops\gates-fixb-20261012'
$Suite = "$Root\goat-suite-candidate"
$Goat = "$Suite\goat.exe"
$Receipt = "$env:LOCALAPPDATA\GOAT Portfolio Desktop\suite\1ce0354662e44e997a61\installation.json"   # T3 Tester only
$T3Login = '3000110122'
$OpenLab = @('3000109268', '3000109269', '3000109270', '3000109271', '3000109272', '3000109273', '3000109427', '3000109421', '3000110705', '3000110706')
$Data = 'C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\0DC0AC2C6DE123294E3E59C8DC9C3541'
$MonitorProfile = 'GOAT-Studio-5938f6836a814787a24221db64e31e6b'
$CandidateRepo = 'C:\Users\web\Documents\GOAT Development Worktrees\GOAT-EA\research-profile'
$CandidateCommit = '3cb9aa924388d54e438d644b8bc9d560faf50ea5'
$GoatRo = 'G:\GOAT-Build-Artifacts\claude-pc-ops\tools\goat-ro.ps1'
$BatchId = 'gate-b-20261012-1'
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'

function Write-GateReceipt([string]$Name, $Object) {
    $path = Join-Path $Root ("{0}-{1}.json" -f ((Get-Date).ToUniversalTime().ToString('HHmmss')), $Name)
    [System.IO.File]::WriteAllText($path, ($Object | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding $false))
    $path
}
function Invoke-GateStudio([string]$Name, [string[]]$StudioArgs, [string]$Surface = 'studio') {
    $t0 = (Get-Date).ToUniversalTime()
    $out = & $Goat $Surface --installation $Receipt @StudioArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $text = $out -join "`n"
    $parsed = $null; try { $parsed = $text | ConvertFrom-Json } catch {}
    $path = Write-GateReceipt $Name ([ordered]@{ called_utc = $t0.ToString('o'); returned_utc = (Get-Date).ToUniversalTime().ToString('o'); exit_code = $code; argv = @($Surface) + $StudioArgs; output = $text })
    [pscustomobject]@{ Code = $code; Json = $parsed; Text = $text; Path = $path }
}
function Stop-Gate([string]$Why) { "STOP: $Why"; exit 3 }
function Invoke-GateRead([string]$Name, [string]$Script) {
    $file = Join-Path $Root "ro-$Name.ps1"
    [System.IO.File]::WriteAllText($file, $Script, (New-Object System.Text.UTF8Encoding $true))
    $out = & powershell.exe -NoProfile -NonInteractive -File $GoatRo -ScriptPath $file 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch 'CLIXML|<Objs|</Objs' }
    if ($LASTEXITCODE -ne 0) { Stop-Gate "goat-ro refused or failed ($Name): $($out -join ' | ')" }
    $out
}
function Get-Chart01Sha {
    $line = Invoke-GateRead 'chart01' "Get-FileHash -LiteralPath '$Data\MQL5\Profiles\Charts\$MonitorProfile\chart01.chr' | ForEach-Object { 'sha ' + `$_.Hash }"
    (($line | Where-Object { $_ -like 'sha *' }) -replace '^sha ', '').ToLower()
}
function Get-GateCapture([string]$Tag) {
    $read = @"
Get-ChildItem -LiteralPath '$Data\MQL5\Profiles\Charts\$MonitorProfile' -File | ForEach-Object { 'monitor ' + `$_.Name + ' ' + (Get-FileHash -LiteralPath `$_.FullName).Hash }
Select-String -LiteralPath '$Data\config\common.ini' -Pattern '^ProfileLast=' -Encoding Unicode | ForEach-Object { 'common.ini ' + `$_.Line }
Get-ChildItem -LiteralPath '$Data\MQL5\Profiles\Charts' -Directory | Where-Object { `$_.Name -eq 'GOAT Research' } | ForEach-Object { Get-ChildItem -LiteralPath `$_.FullName -File } | ForEach-Object { 'research ' + `$_.Name + ' ' + `$_.Length + ' ' + (Get-FileHash -LiteralPath `$_.FullName).Hash }
"@
    $lines = Invoke-GateRead "capture-$Tag" $read
    $path = Write-GateReceipt "capture-$Tag" ([ordered]@{ tag = $Tag; utc = (Get-Date).ToUniversalTime().ToString('o'); lines = $lines })
    $lines; "receipt: $path"
}
function Assert-SafeDemo([string]$Name) {
    $p = Invoke-GateStudio $Name @('preflight') 'demo'
    $b = $p.Json.result.broker
    if ($p.Code -ne 0 -or -not $b.demo -or $b.algo_trading -or $b.positions -ne 0 -or $b.orders -ne 0 -or $b.login -ne $T3Login -or $OpenLab -contains $b.login) { Stop-Gate "demo preflight: $($p.Path)" }
    $b
}

switch ($Phase) {
    'stage' {
        if (Test-Path $Suite) { Stop-Gate "stage exists: $Suite" }
        $tree = git -C $CandidateRepo rev-parse "${CandidateCommit}:controller"
        & robocopy 'C:\Users\web\AppData\Local\Programs\GOAT Command Center Optimizer\resources\goat-suite' $Suite /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { Stop-Gate "robocopy failed $LASTEXITCODE" }
        Rename-Item "$Suite\controller" 'controller-installed'
        git -C $CandidateRepo archive --format=zip -o "$Root\controller-$($CandidateCommit.Substring(0,8)).zip" $CandidateCommit controller
        Expand-Archive "$Root\controller-$($CandidateCommit.Substring(0,8)).zip" -DestinationPath $Suite
        foreach ($f in 'goat_agent.py', 'goat_cockpit_reader.py', 'desktop-agent-workflow.md', 'goat-agent-capabilities.md', 'goat-beta-agent-guide.md', 'goat-beta-start-here.md', 'integrated-sequence-export.md', 'portfolio-exposure-replay.md', 'strategy-library-agent-guide.md') {
            Copy-Item "$Suite\controller-installed\$f" "$Suite\controller\$f"
        }
        Write-GateReceipt 'stage' ([ordered]@{ commit = $CandidateCommit; controller_tree = $tree; suite = $Suite })
        "staged $CandidateCommit (controller tree $tree)"
    }
    'preflight' {
        $o = Invoke-GateStudio 'pre-onboarding-status' @('onboarding-status')
        if ($o.Code -ne 0 -or -not $o.Json.ok) { Stop-Gate "onboarding-status: $($o.Text)" }
        if (($o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }).state -ne 'complete') { Stop-Gate "native_monitor not complete: $($o.Path)" }
        if ($o.Json.result.account.login -ne $T3Login) { Stop-Gate "login $($o.Json.result.account.login)" }
        $b = Assert-SafeDemo 'pre-demo-preflight'
        if ($b.tester_state -ne 'idle') { Stop-Gate "tester $($b.tester_state)" }
        $r = Invoke-GateStudio 'pre-research-profile-status' @('research-profile-status')
        if ($r.Code -ne 0) { Stop-Gate "research-profile-status: $($r.Text)" }
        Invoke-GateStudio 'pre-research-status' @('research-status') | Out-Null
        Invoke-GateStudio 'pre-research-queue' @('research-queue') | Out-Null
        Get-GateCapture 'before'
        "preflight OK. profile_last=$($r.Json.result.profile_last) migration plan:"
        ($r.Json.result.migration.plan | ConvertTo-Json -Depth 4)
    }
    'a1' {
        # A1: healthy observation (evidence only; never authorises a launch).
        $o = Invoke-GateStudio 'a1-onboarding-status' @('onboarding-status')
        if (($o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }).state -ne 'complete') { Stop-Gate "A1 native_monitor not complete: $($o.Path)" }
        $obs = $o.Json.result.monitor_healthy_observation
        "A1 monitor_healthy_observation: $($obs | ConvertTo-Json -Compress -Depth 4)"
        if ($obs.authorises_launch -ne $false) { Stop-Gate 'A1 observation must say authorises_launch false' }
        if ($obs.status -notin @('observed', 'current')) { Stop-Gate "A1 observation status $($obs.status)" }
    }
    'a2' {
        # A2: close-terminal records the post-close chart bytes; they must equal Get-FileHash after the stop.
        Assert-SafeDemo 'a2-demo-preflight' | Out-Null
        $c = Invoke-GateStudio 'a2-close-terminal' @('close-terminal', '--attempt-id', ('gate-a-close-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')))
        if ($c.Code -ne 0 -or -not $c.Json.ok) { Stop-Gate "A2 close-terminal: $($c.Text)" }
        $res = $c.Json.result
        if ($res.phase -ne 'stopped') { Stop-Gate "A2 phase $($res.phase)" }
        $rec = $res.monitor_chart_record
        "A2 monitor_chart_record: $($rec | ConvertTo-Json -Compress -Depth 4)"
        if ($rec.status -ne 'recorded') { Stop-Gate "A2 record status $($rec.status) $($rec.reason)" }
        $disk = Get-Chart01Sha
        "A2 chart01 on disk after stop: $disk"
        if ($disk -ne $rec.chart_sha256) { Stop-Gate "A2 record $($rec.chart_sha256) != disk $disk" }
    }
    'a3' {
        # A3: monitor-launch accepts the recorded bytes; the startup ini forces Enabled=0 / AllowLiveTrading=0.
        $l = Invoke-GateStudio 'a3-monitor-launch' @('monitor-launch', '--attempt-id', ('gate-a-launch-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')))
        if ($l.Code -ne 0 -or -not $l.Json.ok) { Stop-Gate "A3 monitor-launch: $($l.Text)" }
        $res = $l.Json.result
        "A3 status $($res.status) observed_healthy_chart $($res.observed_healthy_chart.chart_sha256) saved $($res.saved_chart_sha256)"
        if ($res.observed_healthy_chart.chart_sha256 -ne $res.saved_chart_sha256) { Stop-Gate 'A3 observed != saved' }
        $ini = Invoke-GateRead 'a3-ini' "Select-String -LiteralPath '$($res.startup_config)' -Pattern '^(Enabled|AllowLiveTrading)=' | ForEach-Object { `$_.Line }"
        $ini
        if (-not ($ini -contains 'Enabled=0') -or -not ($ini -contains 'AllowLiveTrading=0')) { Stop-Gate 'A3 startup ini does not force Enabled=0 and AllowLiveTrading=0' }
    }
    'a4' {
        # A4: readback once MT5 has loaded (run at least 60 s after a3).
        $o = Invoke-GateStudio 'a4-onboarding-status' @('onboarding-status')
        $steps = ($o.Json.result.steps | ForEach-Object { "$($_.id)=$($_.state)" }) -join ' '
        "A4 $steps"
        if (($o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }).state -ne 'complete') { Stop-Gate "A4 native_monitor not complete: $($o.Path)" }
        $b = Assert-SafeDemo 'a4-demo-preflight'
        "A4 broker demo=$($b.demo) algo=$($b.algo_trading) positions=$($b.positions) orders=$($b.orders)"
        Get-GateCapture 'after-a'
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
        $o = Invoke-GateStudio 'prepare-batch' @('prepare-batch', '--batch-id', $BatchId, '--plan', $planPath)
        if ($o.Code -ne 0 -or -not $o.Json.ok) { Stop-Gate "prepare-batch: $($o.Text)" }
        $state = (Get-Content $Receipt -Raw | ConvertFrom-Json).controller_state_root
        $lines = Invoke-GateRead 'package' "Get-Content -LiteralPath '$state\packages\$BatchId\studio-plan.json' -Raw | ConvertFrom-Json | ForEach-Object { 'research_profile ' + `$_.research_binding.research_profile; 'startup_monitor ' + [bool]`$_.research_binding.startup_monitor }"
        $lines
        if (-not ($lines -contains 'research_profile GOAT Research') -or -not ($lines -contains 'startup_monitor True')) { Stop-Gate 'package not bound to GOAT Research with a startup monitor' }
        "prepared $BatchId"
    }
    'run' {
        $o = Invoke-GateStudio 'run-onboarding-status' @('onboarding-status')
        if (($o.Json.result.steps | Where-Object { $_.id -eq 'native_monitor' }).state -ne 'complete') { Stop-Gate "native_monitor not complete: $($o.Path)" }
        Assert-SafeDemo 'run-demo-preflight' | Out-Null
        $r = Invoke-GateStudio 'run-batch' @('run-batch', '--job-id', $BatchId, '--max-seconds', '7200', '--mt5-restart-consent')
        if ($r.Code -ne 0 -or -not $r.Json.ok) { Stop-Gate "run-batch: $($r.Text)" }
        "run-batch returned: $($r.Path)"
        "status $($r.Json.result.status) end_state $($r.Json.result.end_state.status)"
    }
    'poll' {
        $d = Invoke-GateStudio "poll-driver-$Label" @('batch-driver-status', '--job-id', $BatchId)
        $d.Text
    }
    'capture' { Get-GateCapture $Label }
}
