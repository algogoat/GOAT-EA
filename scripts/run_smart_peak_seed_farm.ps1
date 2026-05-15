[CmdletBinding()]
param(
    [string]$SuiteDir = "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\Common\Files\GOAT OPT Files\V1.39 Smart Peak News MLPS 200-400",
    [string]$RepoRoot = "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483\MQL5\Experts\GOAT-EA",
    [string]$TerminalPath = "G:\MetaTrader5 Data\Terminals\Terminal 2 - GOAT\terminal64.exe",
    [string]$TerminalDataRoot = "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\BF132C3D361D44374EA9896A87302483",
    [string]$CommonFilesRoot = "C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\Common\Files",
    [int]$FrameTarget = 256,
    [string]$FromDate = "2025.05.01",
    [string]$ToDate = "2026.04.20",
    [string]$Period = "M1",
    [string]$ReportSubdir = "SmartPeakMLPS",
    [string]$ProgressCsvName = "smart_peak_mlps_seed_farm_progress.csv",
    [int]$TimeoutMinutes = 45,
    [switch]$Smoke,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"

$symbols = @(
    "EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD",
    "EURGBP","EURJPY","EURCHF","EURAUD","EURNZD","EURCAD",
    "GBPJPY","GBPCHF","GBPAUD","GBPCAD","GBPNZD",
    "AUDJPY","AUDNZD","AUDCAD","AUDCHF",
    "NZDJPY","NZDCAD","NZDCHF","CADJPY","CHFJPY"
)

if ($Smoke) {
    $symbols = @("EURUSD")
}

$makeConfig = "C:\Users\web\.codex\skills\mt5-goat-optimize\scripts\make_goat_start_config.py"
$seedXmlDir = Join-Path $CommonFilesRoot "GOAT\SeedFarmingXML"
$reportDir = Join-Path $CommonFilesRoot ("GOAT\SeedFarmingReports\" + $ReportSubdir)
$progressCsv = Join-Path $reportDir $ProgressCsvName

New-Item -ItemType Directory -Force -Path $seedXmlDir, $reportDir | Out-Null

function Get-SetLineValue {
    param([string]$Path, [string]$Prefix)
    $line = Select-String -LiteralPath $Path -Pattern ("^" + [regex]::Escape($Prefix)) | Select-Object -First 1
    if (-not $line) { return "" }
    return $line.Line.Substring($Prefix.Length)
}

function Get-SafePart {
    param([string]$Text)
    $safe = ($Text.ToCharArray() | Where-Object { $_ -match '[A-Za-z0-9]' }) -join ''
    if ([string]::IsNullOrWhiteSpace($safe)) { return "NA" }
    if ($safe.Length -gt 52) { return $safe.Substring(0, 52) }
    return $safe
}

function Stop-TerminalIfRunning {
    $running = Get-Process terminal64 -ErrorAction SilentlyContinue
    if (-not $running) { return }

    foreach ($p in $running) {
        try { [void]$p.CloseMainWindow() } catch {}
    }
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Process terminal64 -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    $still = Get-Process terminal64 -ErrorAction SilentlyContinue
    if ($still) {
        $still | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
}

function Clear-LocalGoatSeedFarmingLeftovers {
    $localGoat = Join-Path $TerminalDataRoot "MQL5\Files\GOAT"
    if (-not (Test-Path -LiteralPath $localGoat -PathType Container)) {
        Write-Host "Local GOAT seed-farming cleanup skipped; folder not found: $localGoat"
        return
    }

    $resolvedLocalGoat = (Resolve-Path -LiteralPath $localGoat).Path.TrimEnd('\')
    $blockedExtensions = @(".mq5", ".mqh", ".ex5", ".set", ".ico", ".png", ".md")
    $files = Get-ChildItem -LiteralPath $resolvedLocalGoat -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -match "SeedFarming" -or
            $_.FullName -match "@\{mode=SeedFarming" -or
            $_.FullName -match "_SF\d+"
        } |
        Where-Object {
            $_.FullName.StartsWith($resolvedLocalGoat + "\") -and
            -not ($blockedExtensions -contains $_.Extension.ToLowerInvariant())
        }

    foreach ($file in $files) {
        Remove-Item -LiteralPath $file.FullName -Force
    }

    Write-Host "Local GOAT seed-farming leftovers deleted: $($files.Count)"
}

function Find-SeedXml {
    param([string]$Symbol, [string]$StrategySafe)
    $pattern = "GOAT V1.39 $Symbol,$Period $FromDate-$ToDate $StrategySafe" + "_N$FrameTarget" + "_*.xml"
    Get-ChildItem -LiteralPath $seedXmlDir -File -Filter $pattern -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Add-ProgressRow {
    param(
        [string]$SetFile,
        [string]$Strategy,
        [string]$Risk,
        [string]$Symbol,
        [string]$Status,
        [double]$DurationMinutes,
        [string]$XmlPath,
        [string]$Message
    )
    $row = [pscustomobject]@{
        Timestamp = (Get-Date).ToString("s")
        SetFile = $SetFile
        Strategy = $Strategy
        Risk = $Risk
        Symbol = $Symbol
        Status = $Status
        DurationMinutes = [math]::Round($DurationMinutes, 2)
        XmlPath = $XmlPath
        Message = $Message
    }
    if (Test-Path -LiteralPath $progressCsv) {
        $row | Export-Csv -LiteralPath $progressCsv -NoTypeInformation -Append
    } else {
        $row | Export-Csv -LiteralPath $progressCsv -NoTypeInformation
    }
}

$sets = Get-ChildItem -LiteralPath $SuiteDir -File -Filter "*.set" | Sort-Object Name
if ($Smoke) {
    $sets = $sets | Select-Object -First 1
}
if (-not $sets) {
    throw "No .set files found in $SuiteDir"
}

$total = $sets.Count * $symbols.Count
$index = 0

foreach ($set in $sets) {
    $baseDesc = Get-SetLineValue -Path $set.FullName -Prefix "EA_Desc="
    $risk = Get-SetLineValue -Path $set.FullName -Prefix "Risk="
    if ([string]::IsNullOrWhiteSpace($baseDesc)) { throw "Missing EA_Desc in $($set.FullName)" }

    foreach ($symbol in $symbols) {
        $index++
        $strategy = "${baseDesc}_${symbol}"
        $strategySafe = Get-SafePart $strategy
        $existing = Find-SeedXml -Symbol $symbol -StrategySafe $strategySafe
        if ($Resume -and $existing) {
            Write-Host "[$index/$total] SKIP existing $($set.Name) $symbol -> $($existing.Name)"
            Add-ProgressRow -SetFile $set.Name -Strategy $baseDesc -Risk $risk -Symbol $symbol -Status "SkippedExisting" -DurationMinutes 0 -XmlPath $existing.FullName -Message "Resume found existing XML"
            continue
        }

        $eaDesc = "$strategy@{mode=SeedFarming,n=$FrameTarget,from=$FromDate,to=$ToDate}"
        $configName = "${strategySafe}_SF$FrameTarget.ini"
        $configPath = Join-Path (Join-Path $TerminalDataRoot "config") $configName

        Write-Host "[$index/$total] START $($set.Name) $symbol Risk=$risk"
        python $makeConfig `
            --set-file $set.FullName `
            --ea-desc $eaDesc `
            --symbol $symbol `
            --period $Period `
            --from-date $FromDate `
            --to-date $ToDate `
            --output-config $configPath | Out-Host

        Stop-TerminalIfRunning
        $start = Get-Date
        $proc = Start-Process -FilePath $TerminalPath -ArgumentList "/config:`"$configPath`"" -PassThru
        $status = "Unknown"
        $message = ""
        $xml = $null
        $deadline = $start.AddMinutes($TimeoutMinutes)

        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 15
            $xml = Find-SeedXml -Symbol $symbol -StrategySafe $strategySafe
            if ($xml) {
                $status = "Completed"
                $message = "Seed XML found"
                break
            }
            $live = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
            if (-not $live) {
                $xml = Find-SeedXml -Symbol $symbol -StrategySafe $strategySafe
                if ($xml) {
                    $status = "Completed"
                    $message = "Terminal exited and XML found"
                } else {
                    $status = "NoXml"
                    $message = "Terminal exited before XML appeared"
                }
                break
            }
        }

        if ($status -eq "Unknown") {
            $status = "Timeout"
            $message = "Timed out after $TimeoutMinutes minute(s)"
        }

        if ((Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
            try { (Get-Process -Id $proc.Id).CloseMainWindow() | Out-Null } catch {}
            Start-Sleep -Seconds 5
            if ((Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
                Stop-Process -Id $proc.Id -Force
            }
        }

        $duration = ((Get-Date) - $start).TotalMinutes
        $xmlPath = if ($xml) { $xml.FullName } else { "" }
        Add-ProgressRow -SetFile $set.Name -Strategy $baseDesc -Risk $risk -Symbol $symbol -Status $status -DurationMinutes $duration -XmlPath $xmlPath -Message $message
        Write-Host "[$index/$total] $status $($set.Name) $symbol $([math]::Round($duration,2))m"
    }
}

Clear-LocalGoatSeedFarmingLeftovers
Write-Host "Seed farming matrix complete. Progress CSV: $progressCsv"
