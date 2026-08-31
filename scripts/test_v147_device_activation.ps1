$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$main = [IO.File]::ReadAllText((Join-Path $repo 'GOAT V1.47.mq5'))
$activation = [IO.File]::ReadAllText((Join-Path $repo 'GOATEADeviceActivation.mqh'))

function Require([bool]$condition, [string]$message) {
    if (-not $condition) { throw $message }
}

Require ($main.Contains('#define   GOAT_BUILD_ID "V1.47-PERFORMANCE-AI-FILTER-R9"')) 'R9 build id missing'
Require ($main.Contains('#include "GOATEADeviceActivation.mqh"')) 'activation module is not included'
Require ($main.Contains('if(GOATDeviceActivationOnly()) return;')) 'capital-sensitive event guards missing'
Require ($main.Contains('GOATDeviceActivationTimer();')) 'activation timer is not wired'
Require ($main.Contains('Trading remains disabled until you sign in and confirm this MT5 account.')) 'activation-only safety and account-confirmation message missing'
Require ($main.Contains('LicenseKey==401 || LicenseKey==403')) 'rejected stored credentials cannot self-repair'
Require (-not $main.Contains('LicenseKey==401 || LicenseKey==403 || LicenseKey==503')) 'transient 503 must not replace a stored credential'
Require ($main.Contains('GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID,true)')) 'credential replacement flow missing'
Require ($main.Contains('return 403;')) 'HTTP 200 + no must map to typed entitlement rejection'
Require ($main.Contains('if(response_text=="no")')) 'legacy entitlement denial body must be matched exactly'
Require (-not $main.Contains('StringFind(response_text, "no")')) 'substring matching must not misclassify unexpected HTTP 200 bodies'
Require ($main.Contains('LicenseKey<0 || LicenseKey>=500')) 'transient license failures must remain fail-closed'
Require ($main.Contains('Stored credential was preserved; no reactivation was started.')) 'transient failure classification must be operator-visible'

foreach ($needle in @(
    '/api/ea/device/start',
    '/api/ea/device/poll',
    'Authorization: Bearer ',
    'GOAT_DEVICE_ACTIVATION_PENDING',
    'GOATDeviceActivationWriteCredential',
    'g_GOATDeviceActivationReplaceCredential',
    'FileMove(temporary,FILE_COMMON,GOAT_API_BEARER_FILE,FILE_COMMON|FILE_REWRITE)',
    'ChartSetSymbolPeriod(ChartID(),Symbol(),Period())'
)) {
    Require ($activation.Contains($needle)) "activation contract missing: $needle"
}

Require (-not $activation.Contains('Print(')) 'activation module must never log codes, request bodies, or credentials'
Require (-not $activation.Contains('Alert(')) 'activation module must keep pairing details inside the chart UI'
Require ($activation.Contains('StringLen(credential_candidate)==72')) 'account credential length must be exact'
Require ($activation.Contains('StringFind(credential_candidate,"goat_ea_")==0')) 'account credential prefix must be exact'
Require ($activation.Contains('verification_url=="https://goatedge.ai/user-portal?tab=ea"')) 'verification URL must be pinned'
Require ($activation.Contains('string expected[]={"ok","status","activationId","userCode","verificationUrl","expiresAtMs",')) 'start response exact-field contract must include numeric status'
Require ($activation.Contains('GOATJsonGetInteger(response,tokens,0,"status",response_status)')) 'start response status must be parsed as an integer'
Require ($activation.Contains('return(response_status==201')) 'start response must require HTTP-created status identity'
Require (-not $activation.Contains('account-bound credential')) 'credential wording must reflect user-scoped authorization'
Require ($activation.Contains('approve MT5 account "+g_GOATDeviceActivationAccountId')) 'EA must identify the requested account during activation'
Require ($activation.Contains('Your GOAT user credential is installed.')) 'installed credential must be described as user-scoped'
Require ($activation.Contains('rechecks MT5-account membership and entitlement on every feed request')) 'server-side account authorization contract must be documented'
Require ($activation.Contains('EventKillTimer();')) 'failed automatic chart reload must stop activation polling'
Require (-not [regex]::IsMatch($activation, 'ChartSetSymbolPeriod[\s\S]{0,300}g_GOATDeviceActivationReloadRequested=false;')) 'failed chart reload must stay latched instead of retrying'
Require ($activation.Contains('Remove and add V1.47 once to finish setup.')) 'manual one-time reload guidance missing'

Require ($main.Contains('GOATDeviceActivationChartEvent(id,sparam);')) 'activation button event is missing'
Require ($main.Contains('ObjectDelete(ChartID(), "Prompt_ConnectGOAT");')) 'activation button cleanup is missing'
Require ($activation.Contains('if(id!=CHARTEVENT_OBJECT_CLICK || object_name!="Prompt_ConnectGOAT") return;')) 'browser must only open on explicit Connect button clicks'
Require ($activation.Contains('if(!MQLInfoInteger(MQL_DLLS_ALLOWED))')) 'browser fallback must not require enabling DLLs'
Require ($activation.Contains('g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_PENDING')) 'expired/nonpending requests must not open'
Require ($activation.Contains('(long)TimeGMT()*1000>=g_GOATDeviceActivationExpiresAtMs')) 'expired link must fail closed'
Require ($activation.Contains('string connect_url="https://goatedge.ai/user-portal?tab=ea#ea-connect="+g_GOATDeviceActivationConnectCode;')) 'fixed-origin fragment link is required'
Require (-not $activation.Contains('Enter pairing code:')) 'new activation flow must not require typing a code'
Require (-not $activation.Contains('/api/ea/device/approve')) 'EA must never approve its own connection'
Write-Output 'V1.47 secure one-file activation and explicit Connect GOAT link contract passed.'
