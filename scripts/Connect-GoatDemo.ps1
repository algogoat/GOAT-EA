# Requires PowerShell 7. Passwords stay out of command-line arguments and files.
# DPAPI store is a current-user ConvertFrom-SecureString encoding of a JSON array
# of {login, masterPassword, investorPassword}. Provision it securely outside Git.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$Receipt,
    [Parameter(Mandatory)][string]$CredentialStore,
    [Parameter(Mandatory)][string]$Python,
    [string]$SdkPath
)
$ErrorActionPreference='Stop'
$secretPointer=[IntPtr]::Zero
$child=$null
try {
    if($PSVersionTable.PSVersion.Major -lt 7) {throw 'PowerShell 7 required'}
    if(Test-Path -LiteralPath $Receipt) {throw 'Existing receipt; inspect before any new attempt'}
    $manifestData=Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    if($manifestData.schemaVersion -ne 'goat-demo-connection-v1' -or $manifestData.purpose -ne 'isolated-demo-setup') {throw 'Invalid connection manifest'}
    if($manifestData.credentialRole -notin @('investor','trader')) {throw 'Explicit credential role required'}
    $encrypted=ConvertTo-SecureString ([IO.File]::ReadAllText($CredentialStore))
    $secretPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($encrypted)
    $accounts=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer) | ConvertFrom-Json
    $selected=@($accounts | Where-Object { [string]$_.login -eq [string]$manifestData.account })
    if($selected.Count -ne 1) {throw 'Credential account missing or ambiguous'}
    $field=if($manifestData.credentialRole -eq 'investor') {'investorPassword'} else {'masterPassword'}
    if($selected[0].$field -isnot [string] -or !$selected[0].$field) {throw 'Selected role has no credential'}
    $payload=@{account=[long]$manifestData.account;role=$manifestData.credentialRole;password=$selected[0].$field} | ConvertTo-Json -Compress
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=$Python
    foreach($arg in @((Join-Path $PSScriptRoot 'goat_demo_connection.py'),'connect','--manifest',$Manifest,'--receipt',$Receipt)) {$start.ArgumentList.Add($arg)}
    if($SdkPath) {$start.ArgumentList.Add('--sdk-path');$start.ArgumentList.Add($SdkPath)}
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true
    $child=[Diagnostics.Process]::Start($start)
    $child.StandardInput.WriteLine($payload)
    $child.StandardInput.Close()
    $payload=$null;$selected=$null;$accounts=$null
    $child.WaitForExit()
    exit $child.ExitCode
} catch {
    # Fixed message only: neither secret envelopes nor raw exceptions are logged.
    Write-Error 'GOAT demo connection failed. Inspect its nonsecret receipt; no automatic retry was attempted.'
    exit 1
} finally {
    if($secretPointer -ne [IntPtr]::Zero) {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)}
    $payload=$null;$selected=$null;$accounts=$null;$encrypted=$null
    if($child) {$child.Dispose()}
}
