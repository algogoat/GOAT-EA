param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Manifest,
  [Parameter(Mandatory=$true)][ValidateSet(7,8)][int]$Terminal,
  [Parameter(Mandatory=$true)][string]$VaultPath,
  [Parameter(Mandatory=$true)][string]$SdkPath,
  [Parameter(Mandatory=$true)][string]$AttemptDirectory,
  [Parameter(Mandatory=$true)][string]$ProtectedWitness,
  [ValidateSet('CurrentUser','LocalMachine')][string]$VaultScope='CurrentUser',
  [switch]$InitialLogin,
  [string]$AdmissionProof,
  [string]$AdmissionSha256,
  [string]$PersistenceProof,
  [string]$PersistenceSha256,
  [switch]$AllowClosed
)
$ErrorActionPreference='Stop'
$vaultItem=Get-Item -LiteralPath $VaultPath
if($vaultItem.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Vault alias refused'}
if($vaultItem.Length -gt 65536){throw 'Vault size refused'}
# DPAPI ciphertext created under this Windows user only. The payload is a JSON
# array of exactly the two explicit login/server/master records. The Python
# client validates the pair, and the decrypted JSON exists in memory/stdin only.
$secure=$null
$plainBytes=$null
if($VaultScope -eq 'CurrentUser'){
  $secure=Get-Content -LiteralPath $vaultItem.FullName -Raw | ConvertTo-SecureString
}else{
  Add-Type -AssemblyName System.Security
  $allowed=@('S-1-5-18','S-1-5-32-544')
  $own=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  foreach($access in (Get-Acl -LiteralPath $vaultItem.FullName).Access){
    $sid=$access.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if($access.AccessControlType -eq 'Allow' -and $sid -notin ($allowed+@($own))){throw 'Machine vault ACL too broad'}
  }
  $plainBytes=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($vaultItem.FullName),$null,[Security.Cryptography.DataProtectionScope]::LocalMachine)
}
$pointer=[IntPtr]::Zero
try {
  if($VaultScope -eq 'CurrentUser'){
    $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $payload=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  }else{$payload=[Text.Encoding]::UTF8.GetString($plainBytes)}
  $psi=[Diagnostics.ProcessStartInfo]::new()
  $psi.FileName=$Python
  $psi.UseShellExecute=$false
  $psi.CreateNoWindow=$true
  $psi.RedirectStandardInput=$true
  $psi.RedirectStandardOutput=$true
  $psi.RedirectStandardError=$true
  # Windows argv quoting; compatible with Windows PowerShell5. No shell or secrets.
  $argumentValues= @('-B',(Join-Path $PSScriptRoot 'goat_demo_pair_connection.py'),'--manifest',$Manifest,'--terminal',[string]$Terminal,'--sdk-path',$SdkPath,'--attempt-dir',$AttemptDirectory,'--protected-witness',$ProtectedWitness)
  if($AllowClosed){$argumentValues+=@('--allow-closed')}
  if($InitialLogin){$argumentValues+=@('--initial-login')}
  if($AdmissionProof){$argumentValues+=@('--admission-proof',$AdmissionProof,'--admission-sha256',$AdmissionSha256)}
  if($PersistenceProof){$argumentValues+=@('--persistence-proof',$PersistenceProof,'--persistence-sha256',$PersistenceSha256)}
  $quotedArguments=foreach($item in $argumentValues){
    $value=[string]$item
    $value=[regex]::Replace($value,'(\\*)"','$1$1\"')
    $value=[regex]::Replace($value,'(\\+)$','$1$1')
    '"'+$value+'"'
  }
  $psi.Arguments=$quotedArguments -join ' '
  $process=[Diagnostics.Process]::Start($psi)
  $process.StandardInput.Write($payload)
  $process.StandardInput.Close()
  $payload=$null
  $outTask=$process.StandardOutput.ReadToEndAsync()
  $errTask=$process.StandardError.ReadToEndAsync()
  if(-not $process.WaitForExit(90000)){throw 'Connection observer timed out; inspect retained intent and process before any retry'}
  [Console]::Out.Write($outTask.GetAwaiter().GetResult())
  if($process.ExitCode -ne 0){throw 'Connection failed; inspect retained nonsecret receipt'}
} finally {
  $payload=$null
  if($pointer -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
  if($secure){$secure.Dispose()}
  if($plainBytes){[Array]::Clear($plainBytes,0,$plainBytes.Length)}
}
