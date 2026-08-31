param(
    [string]$FixturePath = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$optimizerPath = Join-Path $repoRoot 'Optimizer.mqh'
$optimizerSource = Get-Content -LiteralPath $optimizerPath -Raw

$deprecatedKeys = @(
    'Bias_V2_Win_Payoff_R',
    'Bias_V2_Loss_Payoff_R',
    'Bias_V2_Round_Trip_Cost_R',
    'Bias_V2_Min_Expected_R'
)
$legacyHeadings = @(
    '; ==========NEWS AND AI FILTER==========',
    '; ==========NEWS AND AI BIAS FILTER==========',
    '; ==========GOAT AI CONTROL TOWER=========='
)
$signalHeading = '; ==========GOAT AI SIGNAL FILTER=========='
$newsHeading = '; ================GOAT NEWS FILTER================'

function Convert-V147TesterInputs {
    param([Parameter(Mandatory)][string]$Text)

    $sourceLines = @($Text -split "`r?`n")
    $biasProtocolLines = @($sourceLines | Where-Object { $_.Trim().StartsWith('Bias_Protocol=') })
    $hasSignalHeading = @($sourceLines | Where-Object {
        $_.Trim() -in @($legacyHeadings[0], $legacyHeadings[1], $signalHeading)
    }).Count -gt 0
    $modeNewsLines = @($sourceLines | Where-Object { $_.Trim().StartsWith('Mode_News=') })
    $output = [Collections.Generic.List[string]]::new()
    $signalHeadingWritten = $false
    $newsHeadingWritten = $false
    foreach ($rawLine in $sourceLines) {
        $line = $rawLine.TrimEnd("`r")
        $trimmed = $line.Trim()
        if ($trimmed -in @($legacyHeadings[0], $legacyHeadings[1], $signalHeading)) {
            if (-not $signalHeadingWritten) {
                $output.Add($signalHeading)
                if ($biasProtocolLines.Count -eq 1) { $output.Add($biasProtocolLines[0].Trim()) }
                $signalHeadingWritten = $true
            }
            continue
        }
        if ($trimmed -eq $legacyHeadings[2]) { continue }
        if ($trimmed -eq $newsHeading -and $modeNewsLines.Count -gt 0) { continue }

        $equals = $trimmed.IndexOf('=')
        if ($equals -gt 0 -and $trimmed.Substring(0, $equals).Trim() -eq 'Bias_Protocol' -and $hasSignalHeading -and $biasProtocolLines.Count -eq 1) { continue }
        if ($equals -gt 0 -and $trimmed.Substring(0, $equals).Trim() -eq 'Mode_News' -and -not $newsHeadingWritten) {
            $output.Add($newsHeading)
            $newsHeadingWritten = $true
        }
        if ($equals -gt 0 -and $trimmed.Substring(0, $equals).Trim() -in $deprecatedKeys) { continue }
        $output.Add($line)
    }
    return $output -join "`r`n"
}

function Get-InputMap {
    param([Parameter(Mandatory)][string]$Text)

    $map = [ordered]@{}
    foreach ($line in ($Text -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith(';')) { continue }
        $equals = $trimmed.IndexOf('=')
        if ($equals -le 0) { continue }
        $key = $trimmed.Substring(0, $equals).Trim()
        if ($key -in $deprecatedKeys) { continue }
        $map[$key] = $trimmed.Substring($equals + 1)
    }
    return $map
}

function Get-Sha256Text {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $hasher.ComputeHash($bytes)
        return ([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
}

$fixture = @'
Mode_Operation=9
; ==========NEWS AND AI FILTER==========
Mode_Bias=1||1||0||1||N
Mode_Bias_Trades=0||0||0||2||N
Mode_Bias_Exit=0||0||0||2||N
Bias_Exit_Max_Exposure_Adds=-1||-1||1||5||N
Bias_threshold=60||50||5||60||N
Mode_News=0||0||0||4||N
; ==========GOAT AI CONTROL TOWER==========
Bias_Protocol=1||0||0||1||N
Bias_V2_Win_Payoff_R=1.0||1.0||0.1||10.0||N
Bias_V2_Loss_Payoff_R=1.0||1.0||0.1||10.0||N
Bias_V2_Round_Trip_Cost_R=0.02||0.02||0.002||0.2||N
Bias_V2_Min_Expected_R=0.0||0.0||0.0||0.0||N
Mode_Opti=5||5||0||5||N
'@
if ($FixturePath) {
    $fixture = Get-Content -LiteralPath $FixturePath -Raw
}

$normalized = Convert-V147TesterInputs -Text $fixture
$deprecatedOccurrences = 0
foreach ($key in $deprecatedKeys) {
    $deprecatedOccurrences += ([regex]::Matches($fixture, "(?m)^$([regex]::Escape($key))=")).Count
    if ($normalized -match "(?m)^$([regex]::Escape($key))=") {
        throw "Deprecated V1.47 input survived normalization: $key"
    }
    if ($optimizerSource -notmatch [regex]::Escape('key=="' + $key + '"')) {
        throw "Optimizer source does not register deprecated V1.47 key: $key"
    }
}
if ($deprecatedOccurrences -ne $deprecatedKeys.Count) {
    throw "Fixture must contain exactly the four excluded V1.47 payoff rows; found $deprecatedOccurrences."
}
$legacyHeadingOccurrences = 0
foreach ($heading in $legacyHeadings) {
    $legacyHeadingOccurrences += ([regex]::Matches($fixture, [regex]::Escape($heading))).Count
    if ($normalized.Contains($heading)) { throw "Legacy V1.47 heading survived normalization: $heading" }
}
if (([regex]::Matches($normalized, [regex]::Escape($signalHeading))).Count -ne 1) {
    throw 'Normalized fixture must contain exactly one GOAT AI SIGNAL FILTER heading.'
}
if (([regex]::Matches($normalized, [regex]::Escape($newsHeading))).Count -ne 1) {
    throw 'Normalized fixture must contain exactly one GOAT NEWS FILTER heading.'
}

$beforeMap = Get-InputMap -Text $fixture
$afterMap = Get-InputMap -Text $normalized
if ($beforeMap.Count -ne $afterMap.Count) {
    throw 'Active V1.47 input key count changed during normalization.'
}
foreach ($key in $beforeMap.Keys) {
    if (-not $afterMap.Contains($key) -or $afterMap[$key] -ne $beforeMap[$key]) {
        throw "Active V1.47 input changed during normalization: $key"
    }
}
foreach ($required in @('Mode_Bias', 'Mode_Bias_Trades', 'Mode_Bias_Exit', 'Bias_Exit_Max_Exposure_Adds', 'Bias_threshold', 'Bias_Protocol')) {
    if (-not $afterMap.Contains($required)) { throw "Required V1.47 input missing after normalization: $required" }
}
$normalizedLines = @($normalized -split "`r?`n")
$signalIndex = [Array]::IndexOf($normalizedLines, $signalHeading)
$newsIndex = [Array]::IndexOf($normalizedLines, $newsHeading)
$protocolIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith('Bias_Protocol=') })
$modeBiasIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith('Mode_Bias=') })
$biasThresholdIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith('Bias_threshold=') })
$modeNewsIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith('Mode_News=') })
if ($protocolIndex -ne ($signalIndex + 1) -or $modeBiasIndex -le $protocolIndex) {
    throw 'Bias_Protocol must be the first active key in the normalized GOAT AI SIGNAL FILTER section.'
}
if ($newsIndex -le $biasThresholdIndex -or $modeNewsIndex -ne ($newsIndex + 1)) {
    throw 'GOAT NEWS FILTER must form the exact boundary between AI inputs and Mode_News.'
}
foreach ($key in @('Bias_Protocol', 'Mode_Bias', 'Mode_Bias_Trades', 'Mode_Bias_Exit', 'Bias_Exit_Max_Exposure_Adds', 'Bias_threshold')) {
    $keyIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith("$key=") })
    if ($keyIndex -le $signalIndex -or $keyIndex -ge $newsIndex) {
        throw "AI input is outside the exact GOAT AI SIGNAL FILTER group: $key"
    }
}
foreach ($key in @('Mode_News', 'News_threshold', 'News_beforeMinutes', 'News_afterMinutes')) {
    if (-not $afterMap.Contains($key)) { continue }
    $keyIndex = [Array]::FindIndex($normalizedLines, [Predicate[string]] { param($line) $line.Trim().StartsWith("$key=") })
    if ($keyIndex -le $newsIndex) {
        throw "News input is outside the exact GOAT NEWS FILTER group: $key"
    }
}
$renormalized = Convert-V147TesterInputs -Text $normalized
if ($renormalized -ne $normalized) {
    throw 'V1.47 input-surface normalization must be exactly idempotent.'
}
$inputLineCount = ($fixture -split "`r?`n").Count
$normalizedLineCount = ($normalized -split "`r?`n").Count
if ($normalizedLineCount -ne ($inputLineCount - $deprecatedKeys.Count)) {
    throw 'Normalization must remove only the four excluded payoff rows; group-heading replacement is line-count neutral.'
}
$activeMapCanonical = (($afterMap.Keys | Sort-Object | ForEach-Object { "$_=$($afterMap[$_])" }) -join "`n")

$callCount = ([regex]::Matches($optimizerSource, 'GoatOptNormalizeTesterInputSurface\(')).Count
if ($callCount -lt 5) {
    throw "Expected the V1.47 normalizer definition plus four producer/consumer call sites; found $callCount occurrences."
}
if ($optimizerSource -notmatch '#ifndef GOAT_AI_SIGNAL_FILTER_V147') {
    throw 'V1.47 input normalization must remain compile-time scoped to GOAT_AI_SIGNAL_FILTER_V147.'
}
if ($optimizerSource -notmatch [regex]::Escape('if(key=="Mode_News" && !news_header_written)')) {
    throw 'Optimizer source must insert the current news-group boundary immediately before Mode_News.'
}
if (([regex]::Matches($optimizerSource, [regex]::Escape($newsHeading))).Count -lt 2) {
    throw 'Optimizer source must both recognize and emit the exact GOAT NEWS FILTER heading.'
}

[pscustomobject]@{
    status = 'PASS'
    fixture = if ($FixturePath) { (Resolve-Path -LiteralPath $FixturePath).Path } else { 'embedded' }
    activeInputCount = $afterMap.Count
    deprecatedKeyVariantsCovered = $deprecatedKeys.Count
    deprecatedKeyOccurrencesRemoved = $deprecatedOccurrences
    legacyHeadingVariantsCovered = $legacyHeadings.Count
    legacyHeadingOccurrencesRemoved = $legacyHeadingOccurrences
    normalizationOccurrences = $callCount
    modeBias = $afterMap.Mode_Bias
    biasProtocol = $afterMap.Bias_Protocol
    inputLineCount = $inputLineCount
    normalizedLineCount = $normalizedLineCount
    inputSha256 = Get-Sha256Text -Text $fixture
    normalizedSha256 = Get-Sha256Text -Text $normalized
    preservedActiveInputMapSha256 = Get-Sha256Text -Text $activeMapCanonical
} | ConvertTo-Json -Depth 3
