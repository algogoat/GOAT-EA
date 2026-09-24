const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');const read=n=>fs.readFileSync(path.join(root,n),'utf8');
const main=read('GOAT V1.48.mq5'),old=read('GOAT V1.47.mq5'),defs=read('GOAT_Inputs_Definitions.mqh'),activation=read('GOATEADeviceActivation.mqh');
const pair=JSON.parse(main.match(/#define GOAT_API_BEARER_FILE ("[^"]+")/)[1]);
const legacy='GOAT\\Credentials\\api-bearer.token';assert.notEqual(pair,legacy);
assert.ok(main.indexOf('#define GOAT_API_BEARER_FILE')<main.indexOf('#include "GOAT_Inputs_Definitions.mqh"'));
assert.ok(!old.includes('#define GOAT_API_BEARER_FILE'));assert.match(defs,/#ifndef GOAT_API_BEARER_FILE\s+#define\s+GOAT_API_BEARER_FILE/);
const writer=activation.slice(activation.indexOf('bool GOATDeviceActivationWriteCredential(void)'),activation.indexOf('void GOATDeviceActivationRequestReload(void)'));
let b=writer.slice(writer.indexOf('{')+1,writer.lastIndexOf('}')).replace(/\b(?:string|bool|int|uint) /g,'let ').replace(/\(int\)/g,'');
let passed=0;
for(const tokenPath of [legacy,pair])for(const failure of ['none','open','short','move']){
 const touched=[];const c={GOAT_API_BEARER_FILE:tokenPath,g_GOATDeviceActivationCandidate:'goat_ea_'+'a'.repeat(64),StringLen:s=>s.length,StringFind:(s,t)=>s.indexOf(t),GOATIsSafeApiBearerToken:()=>true,FolderCreate:()=>{},FileDelete:p=>touched.push(p),FileOpen:p=>{touched.push(p);return failure==='open'?-1:1;},FileWriteString:()=>failure==='short'?12:72,FileFlush:()=>{},FileClose:()=>{},FileMove:(from,a,to)=>{touched.push(from,to);return failure!=='move';},GOATBuildAuthenticatedRequestHeaders:()=>true,FILE_COMMON:1,FILE_WRITE:2,FILE_TXT:4,FILE_ANSI:8,FILE_REWRITE:16,INVALID_HANDLE:-1};
 assert.equal(vm.runInNewContext('(function(){'+b+'})()',c),failure==='none');
 assert.ok(touched.every(p=>p===tokenPath||p===tokenPath+'.pending'));
 if(tokenPath===pair)assert.ok(!touched.includes(legacy)&&!touched.includes(legacy+'.pending'));passed++;
}
// The management-boot revision intentionally changes the trading handler.
// Keep the unrelated strategy/exit calculations identical after stripping only
// the reviewed safety hooks (behavior tested separately in test_management_boot).
const a=old.indexOf('void OnTick()'),b0=old.indexOf('class CPanelDialog',a),c=main.indexOf('void OnTick()'),d=main.indexOf('class CPanelDialog',c);
function withoutSafetyHooks(s){return s
 .replace(/^.*if\(TimeCurrent\(\)>Expiry\).*\r?\n/gm,'')
 .replace(/^.*(?:GOATSaveManagement\(\);|GOATManagementStatus\(\);|if\(!GOATCanAddRisk\(\)\)).*\r?\n/gm,'')
 .replace('g_GOATWireHealthy && GOATBiasWireV2.GetState(Symbol(),control_tower_state,!g_GOATManager)','GOATBiasWireV2.GetState(Symbol(),control_tower_state)')
 .replace(/^.*if\(g_GOATManager && !GOATTryManagementRecovery\(\)\) return;\r?\n/gm,'')
 .replaceAll(' && (!g_GOATManager || GOATCanAddRisk())','')
 .replace('if(!g_GOATManagementTimerPass) DashboardBusSendStatus(dashboard_status);','DashboardBusSendStatus(dashboard_status);');}
assert.ok(a>0&&b0>a&&c>0&&d>c);assert.equal(withoutSafetyHooks(old.slice(a,b0)),withoutSafetyHooks(main.slice(c,d)));passed++;
console.log(JSON.stringify({passed,legacyAndPairNamespacesIsolated:true,strategyCalculationsUnchanged:true,nativePairing:false}));
