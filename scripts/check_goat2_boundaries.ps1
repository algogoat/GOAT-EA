[CmdletBinding()]
param(
    [switch]$RequireGateway
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$v2Root = Join-Path $repoRoot "v2"
$gateway = Join-Path $v2Root "BrokerGateway.mqh"

if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
    throw "rg is required for the GOAT2 source-boundary audit"
}
if (-not (Test-Path -LiteralPath $v2Root)) {
    throw "V2 source folder not found: $v2Root"
}
if ($RequireGateway -and -not (Test-Path -LiteralPath $gateway)) {
    throw "Required broker boundary is missing: $gateway"
}

$files = @(
    & rg --files $v2Root -g "*.mq5" -g "*.mqh"
)
$rootEntrypoints = @(
    Get-ChildItem -LiteralPath $repoRoot -File -Filter "GOAT2 V*.mq5" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
)
$files = @($files + $rootEntrypoints | Sort-Object -Unique)
if ($files.Count -eq 0) {
    throw "No GOAT2 MQL source files were found"
}

$mutationPattern = '(?x)(?:\bOrderSend(?:Async)?\s*\(|\.(?:Buy|Sell|BuyLimit|BuyStop|BuyStopLimit|SellLimit|SellStop|SellStopLimit|PositionOpen|PositionModify|PositionClose|PositionClosePartial|PositionCloseBy|OrderOpen|OrderModify|OrderDelete)\s*\(|\#include\s*[<"]Trade[\\/]+Trade\.mqh[>"])'
$mutationHits = @(& rg -n --pcre2 $mutationPattern -- $files 2>$null)
$gatewayNormalized = $gateway.Replace('/', '\').ToLowerInvariant()
$bypasses = @()
foreach ($hit in $mutationHits) {
    # Keep the Windows drive colon and split on the `:line:` delimiter emitted
    # by ripgrep. Type-only mentions in OnTradeTransaction signatures are not
    # broker mutations and are intentionally excluded by the pattern above.
    $match = [regex]::Match($hit, '^(?<file>.+?):\d+:')
    if (-not $match.Success) {
        $bypasses += $hit
        continue
    }
    $filePart = $match.Groups['file'].Value
    try {
        $resolved = (Resolve-Path -LiteralPath $filePart).Path.Replace('/', '\').ToLowerInvariant()
    } catch {
        $resolved = $filePart.Replace('/', '\').ToLowerInvariant()
    }
    if ($resolved -ne $gatewayNormalized) {
        $bypasses += $hit
    }
}

$legacyPattern = '#include\s*[<"].*(GOAT_Inputs_Definitions|Dashboard|Optimizer|Tester|MTTester|XmlProcessor|NewsBiasFilter)\.mqh[>"]'
$legacyHits = @(& rg -n --pcre2 $legacyPattern -- $files 2>$null)

$secretPattern = '(?i)(Authorization\s*:\s*Bearer|Bearer\s+[A-Za-z0-9._-]{20,}|api[_-]?key\s*=\s*["''][^"'']{12,})'
$secretHits = @(& rg -n --pcre2 $secretPattern -- $files 2>$null)

$errors = 0
if ($bypasses.Count -gt 0) {
    Write-Error "Broker mutation bypasses detected outside v2/BrokerGateway.mqh:`n$($bypasses -join [Environment]::NewLine)" -ErrorAction Continue
    $errors += $bypasses.Count
}
if ($legacyHits.Count -gt 0) {
    Write-Error "Legacy V1 include dependencies detected in GOAT2:`n$($legacyHits -join [Environment]::NewLine)" -ErrorAction Continue
    $errors += $legacyHits.Count
}
if ($secretHits.Count -gt 0) {
    Write-Error "Possible embedded credential material detected in GOAT2 source. Inspect locally; values are intentionally not echoed." -ErrorAction Continue
    $errors += $secretHits.Count
}

Write-Output "GOAT2_BOUNDARY_AUDIT"
Write-Output "SOURCE_FILES=$($files.Count)"
Write-Output "GATEWAY_PRESENT=$([int](Test-Path -LiteralPath $gateway))"
Write-Output "MUTATION_HITS=$($mutationHits.Count)"
Write-Output "BYPASSES=$($bypasses.Count)"
Write-Output "LEGACY_INCLUDES=$($legacyHits.Count)"
Write-Output "POSSIBLE_SECRETS=$($secretHits.Count)"

if ($errors -gt 0) {
    exit 1
}

Write-Output "RESULT=PASS"
exit 0
