// B43 no-drift guard (beta.25 profile-staged deploy, goatai#1885 6033450916). Against B41 (278ec109,
// the admitted baseline whose source hashes are committed in candidate-builds/beta17-B41/identity.json):
// - only Dashboard.mqh, GOATPortfolioSetupControl.mqh and GOATPortfolioChildAudit.mqh differ;
// - the entrypoint differs in its GOAT_BUILD_ID and GOAT_BUILD_MARKER lines and in exactly ONE trade-path line: the
//   staged-child gate added as the first line of DashboardEntryAllowed (goatai#1885 6035859714). With those three
//   lines restored the entrypoint is B41's exact bytes, so StartExporter, OnTick, OnTradeTransaction, OnTimer,
//   GoatTickBody, SignalEntryTrigger and every other unit are byte-identical. The gate returns true at its first
//   line for any child without a "deploy=" nonce (test_profile_staged_adoption.cjs proves the answers equal B41's);
// - the input header and every trade-path include are byte-identical, so no input, default or SET changes.
// Needs no git history: B41's hashes are in the repo. With history, the trade-path units are also compared
// against `git show 278ec109` directly.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B41='278ec109be4e95a6e934d4897a91cb28ed71345c';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const b41=JSON.parse(read('candidate-builds/beta17-B41/identity.json'));
const b43=JSON.parse(read('candidate-builds/beta17-B43/identity.json'));
let checks=0;
assert.deepEqual(Object.keys(b43.sources).sort(),Object.keys(b41.sources).sort(),'same compile closure as B41');checks++;
for(const [f,h] of Object.entries(b43.sources)) assert.equal(sha(read(f)),h,'B43 identity pins '+f);
checks++;
const differing=Object.keys(b43.sources).filter(f=>b43.sources[f]!==b41.sources[f]).sort();
assert.deepEqual(differing,['Dashboard.mqh','GOAT V1.49.mq5','GOATPortfolioChildAudit.mqh','GOATPortfolioSetupControl.mqh'],'only the deploy path, the audit and the entrypoint differ');checks++;
for(const f of ['GOAT_Inputs_Definitions.mqh','Optimizer.mqh','Tester.mqh','XmlProcessor.mqh','GOAT_DirectionGuard.mqh','GOAT_DirectionGuardCore.mqh',
                'NewsBiasFilter.mqh','GOATAIWireV2.mqh','GOAT_SequenceExport.mqh','GOAT_SequencePackage.mqh','GOATEvidenceEnd.mqh','GOATDeploymentDiagnostics.mqh'])
 assert.equal(b43.sources[f],b41.sources[f],'trade-path or shared include unchanged: '+f);
checks++;
// The entrypoint, with its two identity lines put back to B41's, is B41's exact bytes.
const main=read('GOAT V1.49.mq5').toString('utf8');
const GATE='   if(!GoatStagedChildMayOpen(g_GoatStudioMonitorRunPath,MAGIC1,Symbol())) return false; // beta.25: a profile-staged child opens nothing before its dashboard policy (GOATPortfolioSetupControl.mqh)\r\n';
assert.equal(main.split(GATE).length-1,1,'the gate line occurs exactly once');
assert.ok(main.includes('bool DashboardEntryAllowed(const int op)\r\n  {\r\n'+GATE+'   if(!DashboardTradeAllowed(op)) return false;'),'the gate is the first line of DashboardEntryAllowed');
assert.equal((main.match(/GoatStagedChildMayOpen|g_GoatStudioMonitorRunPath,MAGIC1/g)||[]).length,2,'no other reference to the gate in the entrypoint');
assert.equal((main.match(/#define   GOAT_BUILD_ID "V1\.49-BETA17-43"\r\n/g)||[]).length,1);
assert.equal((main.match(/#define   GOAT_BUILD_MARKER "B43"\r\n/g)||[]).length,1);
const restored=main.replace(GATE,'').replace('#define   GOAT_BUILD_ID "V1.49-BETA17-43"','#define   GOAT_BUILD_ID "V1.49-BETA17-41"').replace('#define   GOAT_BUILD_MARKER "B43"','#define   GOAT_BUILD_MARKER "B41"');
assert.equal(sha(Buffer.from(restored,'utf8')),b41.sources['GOAT V1.49.mq5'],'the entrypoint differs from B41 only in its build ID, marker and the one gate line');checks++;
assert.equal(b43.build_id,'V1.49-BETA17-43');assert.equal(b43.build_marker,'B43');assert.equal(b43.supersedes_candidate,'beta17-B41');checks++;
// The input contract and the dependency header pin are unchanged; the main pin follows the entrypoint.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,b41.sources['GOAT_Inputs_Definitions.mqh']);assert.equal(deps.main_sha256,b43.sources['GOAT V1.49.mq5']);checks++;
// With history: StartExporter, OnTick, OnTradeTransaction and OnTimer compared unit by unit.
function body(text,signature){
 const start=text.indexOf(signature);assert.ok(start>=0,signature);
 let i=text.indexOf('{',start),depth=1;for(i++;depth;i++){if(text[i]==='{')depth++;if(text[i]==='}')depth--;}
 return text.slice(start,i);
}
let history=false;
try{
 const old=execFileSync('git',['show',B41+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');
 history=true;
 const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
 for(const sig of ['bool StartExporter(bool reportMode)','void OnTick()','void GoatTickBody()','void OnTradeTransaction(','void OnTimer(void)','void SignalEntryTrigger()','bool DashboardTradeAllowed(const int op)'])
  {assert.equal(body(norm(main),sig),body(norm(old),sig),sig);checks++;}
 // DashboardEntryAllowed: B41's body plus the gate line, nothing else.
 assert.equal(body(norm(main),'bool DashboardEntryAllowed(const int op)').replace(norm(GATE),''),body(norm(old),'bool DashboardEntryAllowed(const int op)'));checks++;
}catch(e){if(e instanceof assert.AssertionError)throw e;}
console.log(JSON.stringify({passed:checks,differing,entrypointDelta:"build ID, marker, staged-child gate line",unitHistoryCompare:history,base:B41.slice(0,8)}));
