param(
    [string]$SetRoot = 'C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\Common\Files\GOAT\GOAT V1.47-Darwinex-Demo',
    [int]$MaxFiles = 500
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$baselineCommit = '67cd046c3b3b43d4e535ea6955b826891445f315' # Released V1.47 R5; stable after later revisions are committed.
$helper = [IO.File]::ReadAllText((Join-Path $repo 'GOAT_DashboardAILaunchPolicy.mqh'))
$dashboard = [IO.File]::ReadAllText((Join-Path $repo 'Dashboard.mqh'))
$main = [IO.File]::ReadAllText((Join-Path $repo 'GOAT V1.47.mq5'))
function Require([bool]$condition, [string]$message) {
    if (-not $condition) { throw $message }
}

# Execute the production pure helper through a small MQL string/array syntax
# shim. Business logic and the built-in self-test are not reimplemented here.
# This complements (does not replace) the native MetaEditor compile.
$cs = [regex]::Replace($helper, '(?m)^#.*\r?\n', '')
$cs = [regex]::Replace($cs, '(?s)enum ENUM_GOAT_AI_LAUNCH_MODE\s*\{.*?\};', @'
const int GOAT_AI_LAUNCH_AS_OPTIMIZED=0;
const int GOAT_AI_LAUNCH_DISPLAY_ONLY=1;
const int GOAT_AI_LAUNCH_ENTRY_FILTER=2;
'@)
$cs = $cs.Replace('const string ', 'string ').Replace('const int ', 'int ')
$cs = [regex]::Replace($cs, '(?m)^(int|string|bool) (Goat\w+)\(', 'public static $1 $2(')
$cs = [regex]::Replace($cs, '(?m)^int (GOAT_AI_LAUNCH_\w+)=', 'const int $1=')
$cs = $cs.Replace('int &threshold', 'ref int threshold')
$cs = $cs.Replace('(void)', '()')
$cs = [regex]::Replace($cs, '(GoatParseAILaunchThreshold\([^,]+),threshold\)', '$1,ref threshold)')
$cs = $cs.Replace('StringTrimLeft(raw);', 'raw=raw.TrimStart();').Replace('StringTrimRight(raw);', 'raw=raw.TrimEnd();')
$cs = $cs.Replace('string names[4]', 'string[] names').Replace('bool found[4]', 'bool[] found')
$cs = $cs.Replace('string input_lines[];', 'string[] input_lines;')
$cs = $cs.Replace("StringSplit(source,'\n',input_lines)", "StringSplit(source,'\n',out input_lines)")
Add-Type -TypeDefinition @"
using System;
using System.Globalization;
public static class GoatAILaunchPolicyTest {
    static int StringLen(string s) { return s.Length; }
    static int StringGetCharacter(string s,int i) { return s[i]; }
    static int StringFind(string s,string value) { return s.IndexOf(value,StringComparison.Ordinal); }
    static string StringSubstr(string s,int start) { return s.Substring(start); }
    static string StringSubstr(string s,int start,int count) { return s.Substring(start,count); }
    static long StringToInteger(string s) { return long.Parse(s,CultureInfo.InvariantCulture); }
    static string IntegerToString(int n) { return n.ToString(CultureInfo.InvariantCulture); }
    static int StringSplit(string s,char separator,out string[] values) { values=s.Split(separator); return values.Length; }
$cs
}
"@
Require ([GoatAILaunchPolicyTest]::GoatAILaunchPolicySelfTest()) 'Production self-test failed'

$aiKeys = 'Mode_Bias|Bias_threshold|Bias_Protocol|Mode_Bias_Trades'
$stripAI = "(?m)^(?:$aiKeys)=.*\r\n"
function Check-Inputs([string]$source, [string]$label) {
    Require ([GoatAILaunchPolicyTest]::GoatApplyAILaunchPolicy($source,0,75) -ceq $source) "As Optimized changed inputs: $label"
    foreach ($mode in @(1,2)) {
        foreach ($threshold in @(1,60,100)) {
            $actual = [GoatAILaunchPolicyTest]::GoatApplyAILaunchPolicy($source,$mode,$threshold)
            Require ([regex]::Replace($actual,$stripAI,'') -ceq [regex]::Replace($source,$stripAI,'')) "Non-AI input changed: $label"
            $expectedMode = if ($mode -eq 1) { '0' } else { '2' }
            $expected = @{ Mode_Bias=$expectedMode; Bias_threshold="$threshold"; Bias_Protocol='1'; Mode_Bias_Trades='0' }
            foreach ($key in $expected.Keys) {
                $values = [regex]::Matches($actual,"(?m)^$key=([^\r\n]*)")
                Require ($values.Count -gt 0) "Missing override $key : $label"
                foreach ($value in $values) {
                    Require ($value.Groups[1].Value -ceq $expected[$key]) "Wrong override $key : $label"
                }
            }
        }
    }
}
Check-Inputs "EA_Desc=Unicode-test-金`r`nMode_Bias=5||1||1||5||Y`r`nMode_Bias=3`r`nBias_Protocol=2`r`nMode_Bias_Trades=1`r`nMode_Bias_Exit=1`r`nBias_Exit_Max_Exposure_Adds=2`r`nMode_News=4`r`nNews_threshold=85`r`nRisk=100`r`n" 'duplicate/optimization/Unicode fixture'

# Read-only check against representative exports from every available deploy
# folder, including the preceding V1.45-suite and newer unique-file runs.
$files = @()
if (Test-Path -LiteralPath $SetRoot) {
    $all = @(rg --files -g '*.set' $SetRoot | Where-Object { $_ -match '\\deploy\\' } | Sort-Object)
    if ($all.Count -le $MaxFiles -or $MaxFiles -le 0) { $files=$all }
    else {
        $files = @(for ($i=0; $i -lt $MaxFiles; $i++) { $all[[int][Math]::Floor($i*$all.Count/$MaxFiles)] })
    }
}
foreach ($file in $files) {
    $before=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    $raw=[IO.File]::ReadAllText($file)
    $inputLines=@($raw -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_.IndexOf('=') -gt 0 })
    $inputs=($inputLines -join "`r`n")+"`r`n"
    Check-Inputs $inputs $file
    Require ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ceq $before) "Source set was modified: $file"
}

$overrideNames=@([regex]::Matches($helper,'if\(name=="([^"]+)"\)') | ForEach-Object { $_.Groups[1].Value })
Require (($overrideNames -join ',') -ceq 'Mode_Bias,Bias_threshold,Bias_Protocol,Mode_Bias_Trades') 'Override allowlist changed'
Require ($main.Contains('#define GOAT_DASH_AI_LAUNCH_POLICY_V147 1')) 'V1.47 feature gate missing'
Require ($dashboard.Contains('if(AnyAILaunchRowsDeployed()) return true;')) 'Launch policy lock missing'
Require ($dashboard.Contains('edt_AILaunchThreshold.ReadOnly(locked || m_ai_launch_mode==GOAT_AI_LAUNCH_AS_OPTIMIZED);')) 'Threshold lock missing'
Require ($dashboard.Contains('if(PrepareAILaunchPolicy()) UpdateAILaunchControls();')) 'Invalid threshold must not silently reset before a queued activation'
Require ($dashboard.Contains('if(header=="#GOAT_AI_LAUNCH_V147_1")') -and $dashboard.Contains('SaveAILaunchPolicyState();') -and $dashboard.Contains('DeleteAILaunchPolicyState();')) 'Resume/new-portfolio policy lifecycle missing'
Require ($dashboard.Contains('AppendAILaunchAudit(idx,"PREPARED");') -and $dashboard.Contains('"LINKED" : "APPLY_FAILED"')) 'Launch audit stages missing'
Require ($dashboard.Contains('if(tplText=="") return;') -and $dashboard.Contains('if(inputs=="")')) 'Unreadable/empty export launch guard missing'
Require ($dashboard.Contains('if(next_mode!=GOAT_AI_LAUNCH_AS_OPTIMIZED && !PrepareAILaunchPolicy()) return true;')) 'Invalid threshold must not prevent returning to As Optimized'
$applyStart=$dashboard.IndexOf('bool CGOATDashboard::ApplyTemplate(')
$applyEnd=$dashboard.IndexOf('bool CGOATDashboard::NewSingleInstance(',$applyStart)
$applyBody=$dashboard.Substring($applyStart,$applyEnd-$applyStart)
Require ($applyBody.IndexOf('g_sets[idx].cid=cid;') -lt $applyBody.IndexOf('if(!SaveDashboardConfig())')) 'Child identity must be assigned before persisting'
Require ($applyBody.IndexOf('if(!SaveDashboardConfig())') -lt $applyBody.IndexOf('if(!ChartApplyTemplate(cid, tplName))')) 'Partial deployment lock must be persisted before the child EA can run'
Require ($applyBody.Contains('if(ChartClose(cid)) g_sets[idx].cid=-1;')) 'Failed durable save must block child launch'
Require ($dashboard.Contains('if(written==0)') -and $dashboard.Contains('if(!FileMove(write_path,FILE_COMMON,rel_path,FILE_COMMON|FILE_REWRITE)) return false;')) 'Dashboard snapshot must fail closed on partial write/replacement failure'
Require ($dashboard.Contains('if(FileWrite(h,"#GOAT_AI_LAUNCH_V147_1",IntegerToString(m_ai_launch_mode),IntegerToString(m_ai_launch_threshold))==0)')) 'Policy must be written atomically with child identities, not depend on terminal globals'
Require ($dashboard.Contains('No duplicate EA will be launched.')) 'Unlinked persisted child identity must not allow a duplicate launch'
Require ($dashboard.Contains('Legacy split AI policy state cannot be resumed safely; inspect existing child charts.')) 'Unproven legacy split policy must fail closed'

Push-Location $repo
try {
    $inputDiff=git diff $baselineCommit -- GOAT_Inputs_Definitions.mqh
    Require (-not $inputDiff) 'EA input definitions changed'
    $oldMain=(git show "${baselineCommit}:GOAT V1.47.mq5") -join "`n"
    $newMain=$main.Replace("`r`n","`n").TrimEnd("`n")
    $newMain=$newMain.Replace('V1.47-PERFORMANCE-AI-FILTER-R9','V1.47-PERFORMANCE-AI-FILTER-R5').Replace('GOAT_BUILD_MARKER "R9"','GOAT_BUILD_MARKER "R5"')
    $newMain=$newMain.Replace("#define GOAT_DASH_AI_LAUNCH_POLICY_V147 1`n",'')
    $newMain=$newMain.Replace("   ObjectDelete(ChartID(), `"Prompt_ConnectGOAT`");`n",'')
    $newMain=$newMain.Replace("   if(GOATDeviceActivationOnly())`n   {`n    GOATDeviceActivationChartEvent(id,sparam);`n    return;`n   }",'   if(GOATDeviceActivationOnly()) return;')
    Require ($newMain -ceq $oldMain.TrimStart([char]0xFEFF)) 'V1.47 trading/optimization code changed outside the approved build/gate lines'
} finally { Pop-Location }
Write-Output "PASS: production self-test, boundary/invalid thresholds, both override modes, duplicate/missing keys, and $($files.Count) unchanged source exports."
Write-Output 'PASS: four-field allowlist, launch lock, resume lifecycle, audit, empty-export guard, unchanged EA input schema and trading/optimization body.'
