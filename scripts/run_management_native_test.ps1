param(
 [Parameter(Mandatory=$true)][string]$TerminalRoot,
 [Parameter(Mandatory=$true)][string]$CompileReceipt,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][long]$AccountLogin,
 [Parameter(Mandatory=$true)][string]$BrokerServer
)
$ErrorActionPreference='Stop'
$terminalRootFull=[IO.Path]::GetFullPath($TerminalRoot)
$exe=Join-Path $terminalRootFull 'terminal64.exe'
if(!(Test-Path -LiteralPath (Join-Path $terminalRootFull '.management-tester-only'))){throw 'Missing isolated tester ownership marker'}
$running=@(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object {$_.ExecutablePath -eq $exe})
if($running.Count){throw 'Exact tester terminal already running; inspect retained attempt'}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Attempt directory already exists'}
$receipt=Get-Content -LiteralPath $CompileReceipt -Raw | ConvertFrom-Json
if($receipt.outcome -ne 'COMPILE_OK' -or $receipt.compile.resultLine -notmatch '0 errors, 0 warnings'){throw 'Compile not qualified'}
$source=$receipt.source.path
# The compile receipt's source path must contain the generated tester-only wrapper.
if(!(Test-Path -LiteralPath $source)){throw 'Source missing'}
$sourceText=[IO.File]::ReadAllText($source)
$bootText=[IO.File]::ReadAllText((Join-Path (Split-Path $source) 'GOATManagementBoot.mqh'))
if(!$sourceText.Contains('TESTER-ONLY: refuses charts/live/demo attachment') -or !$bootText.Contains('GOATFixtureWebRequest')){throw 'Not the expected tester-only harness'}
if($AccountLogin -le 0 -or $BrokerServer -notmatch '^[a-zA-Z0-9 _.-]*Demo[a-zA-Z0-9 _.-]*$'){throw 'Requires an explicit demo identity'}
if((Get-FileHash -LiteralPath $source).Hash.ToLower() -ne $receipt.source.sha256){throw 'Source changed since compile'}
$binary=Join-Path (Split-Path $CompileReceipt) ([IO.Path]::GetFileNameWithoutExtension($source)+'.ex5')
if((Get-FileHash -LiteralPath $binary).Hash.ToLower() -ne $receipt.output.sha256){throw 'Binary changed since compile'}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$expertName=[IO.Path]::GetFileName($binary)
Copy-Item -LiteralPath $binary -Destination (Join-Path $terminalRootFull ('MQL5\Experts\ManagementTest\'+$expertName))
$inputs="EA_Desc=Management native integration`r`nMode_Operation=9`r`nMode_Bias=1`r`nMode_News=1`r`nAllow_New_Sequence=false`r`nRisk=10`r`nSequence_MLPS_Hard_Close=true`r`n"
$setName='management-native-qualified.set'
[IO.File]::WriteAllText((Join-Path $terminalRootFull ('MQL5\Profiles\Tester\'+$setName)),$inputs,[Text.Encoding]::Unicode)
$configuration=@"
[Common]
Login=$AccountLogin
Server=$BrokerServer
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=1
[Tester]
Login=$AccountLogin
Expert=ManagementTest\$expertName
ExpertParameters=$setName
Symbol=EURUSD
Period=M1
Model=1
ExecutionMode=0
Optimization=0
FromDate=2026.09.14
ToDate=2026.09.15
ForwardMode=0
Report=management-native-test
ReplaceReport=1
ShutdownTerminal=1
Deposit=100000
Currency=USD
Leverage=1:100
Visual=0
UseLocal=1
UseRemote=0
UseCloud=0
"@
$cfg=Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'test.ini'
[IO.File]::WriteAllText($cfg,$configuration,[Text.Encoding]::Unicode)
$offsets=@{}
Get-ChildItem -LiteralPath (Join-Path $terminalRootFull 'Tester') -Recurse -Filter '*.log' | ForEach-Object {$offsets[$_.FullName]=$_.Length}
$p=Start-Process -FilePath $exe -ArgumentList @('/portable',('/config:"'+$cfg+'"')) -WindowStyle Hidden -PassThru
@{pid=$p.Id;exe=$exe;creationUtc=$p.StartTime.ToUniversalTime().ToString('o');sourceSha256=$receipt.source.sha256;binarySha256=$receipt.output.sha256;liveTrading=$false} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'process.json')
if(!$p.WaitForExit(60000)){throw 'Native test still running; retained process, do not relaunch'}
$fresh=''
Get-ChildItem -LiteralPath (Join-Path $terminalRootFull 'Tester') -Recurse -Filter '*.log' | Where-Object {$_.FullName -match 'Agent-'} | ForEach-Object {
 $bytes=[IO.File]::ReadAllBytes($_.FullName); $offset=0;if($offsets.ContainsKey($_.FullName)){$offset=$offsets[$_.FullName]}
 if($bytes.Length -lt $offset){throw 'Agent log truncated unexpectedly'}
 if($bytes.Length -gt $offset){$fresh += [Text.Encoding]::Unicode.GetString($bytes,[int]$offset,$bytes.Length-[int]$offset);Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $OutputDirectory 'full-agent.log')}
}
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'fresh-agent.log'),$fresh)
$passed=$fresh.Contains('NATIVE_MANAGEMENT_RESULT cases=6 failures=0') -and !$fresh.Contains('NATIVE_ASSERT FAIL') -and $fresh.Contains('OnTester result 1')
@{passed=$passed;cases=6;nativeOrderExecution=$true;authTransport='injected';restart='simulated reinit inside tester';coldTerminalRestart=$false;brokerFills=$false;binarySha256=$receipt.output.sha256;sourceSha256=$receipt.source.sha256;model='M1 OHLC';journalSha256=(Get-FileHash (Join-Path $OutputDirectory 'fresh-agent.log')).Hash.ToLower()} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'result.json')
Get-Content (Join-Path $OutputDirectory 'result.json')
if(!$passed){throw 'Native assertions did not all pass; inspect retained journal'}
