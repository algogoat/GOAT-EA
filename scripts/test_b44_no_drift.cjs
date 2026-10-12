// B44 no-drift guard (goatai#2350). Against B43 (e38791d6, whose source hashes are committed in
// candidate-builds/beta17-B43/identity.json; c708cae4 carries the same closure):
// - the compile closure is the same 41 files and only the six B44 files differ: the entrypoint, GOATAIWireV2.mqh
//   (item 2), GOATPortfolioChildAudit.mqh (items 3, 5), GOATPortfolioSetupControl.mqh (items 1, 3),
//   GOATSetupControl.mqh (item 11) and GOAT_SequenceExport.mqh (item 6);
// - the input header (the contract pin) and every other trade-path include are byte-identical, so no input, default or
//   enum of the header changes (BlindExport is declared last in the entrypoint, item 5);
// - with history: OnTick, OnTradeTransaction, OnTimer, DashboardTradeAllowed and DashboardEntryAllowed are B43's
//   exact units; GoatTickBody is B43's plus three marked lines: GoatRankTick() (item 5, a blind export run only)
//   and the gate log's state copy and reset (item 4, log only).
//   SignalEntryTrigger (item 4), StartExporter and RunAndStoreSet (item 5) are compared by their own item tests.
// Replaces test_b43_no_drift.cjs (B43's guard against B41), which pinned the tree to B43 by design.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B43_TREE='c708cae4';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const b43=JSON.parse(read('candidate-builds/beta17-B43/identity.json'));
const b44=JSON.parse(read('candidate-builds/beta17-B44/identity.json'));
let checks=0;
assert.deepEqual(Object.keys(b44.sources).sort(),Object.keys(b43.sources).sort(),'same compile closure as B43');checks++;
for(const [f,h] of Object.entries(b44.sources)) assert.equal(sha(read(f)),h,'B44 identity pins '+f);
checks++;
const differing=Object.keys(b44.sources).filter(f=>b44.sources[f]!==b43.sources[f]).sort();
assert.deepEqual(differing,['GOAT V1.49.mq5','GOATAIWireV2.mqh','GOATPortfolioChildAudit.mqh','GOATPortfolioSetupControl.mqh','GOATSetupControl.mqh','GOAT_SequenceExport.mqh'],
 'only the six B44 files differ from B43');checks++;
for(const f of ['GOAT_Inputs_Definitions.mqh','Optimizer.mqh','Tester.mqh','XmlProcessor.mqh','GOAT_DirectionGuard.mqh','GOAT_DirectionGuardCore.mqh','Dashboard.mqh',
                'NewsBiasFilter.mqh','GOAT_SequencePackage.mqh','GOATEvidenceEnd.mqh','GOATDeploymentDiagnostics.mqh','GOATLicenseInitRetry.mqh','GOATEADeviceActivation.mqh'])
 assert.equal(b44.sources[f],b43.sources[f],'trade-path or shared include unchanged: '+f);
checks++;
const main=read('GOAT V1.49.mq5').toString('utf8');
assert.equal((main.match(/#define   GOAT_BUILD_ID "V1\.49-BETA17-44"\r\n/g)||[]).length,1);
assert.equal((main.match(/#define   GOAT_BUILD_MARKER "B44"\r\n/g)||[]).length,1);
assert.equal(b44.build_id,'V1.49-BETA17-44');assert.equal(b44.build_marker,'B44');assert.equal(b44.supersedes_candidate,'beta17-B43');checks++;
// The input contract (header pin) is unchanged; the main pin follows the entrypoint.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,b43.sources['GOAT_Inputs_Definitions.mqh']);assert.equal(deps.main_sha256,b44.sources['GOAT V1.49.mq5']);checks++;
// With history: the trade-path units compared unit by unit (string- and comment-aware brace matching).
function body(text,signature){
 const start=text.indexOf(signature);assert.ok(start>=0,signature);
 let j=text.indexOf('{',start)+1,depth=1;
 while(depth&&j<text.length){
  const ch=text[j];
  if(ch==='"'){j++;while(j<text.length&&text[j]!=='"'){if(text[j]==='\\')j++;j++;}j++;continue;}
  if(ch==="'"){j+=text[j+1]==='\\'?4:3;continue;}
  if(ch==='/'&&text[j+1]==='/'){j=text.indexOf('\n',j);continue;}
  if(ch==='{')depth++;if(ch==='}')depth--;j++;
 }
 return text.slice(start,j);
}
let history=false;
try{
 const old=execFileSync('git',['show',B43_TREE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');
 history=true;
 // The blob is stored with LF (.gitattributes); the tree and the pins are CRLF.
 assert.equal(sha(Buffer.from(old.replace(/\r?\n/g,'\r\n'),'utf8')),b43.sources['GOAT V1.49.mq5'],B43_TREE+' carries the B43 entrypoint');
 const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
 for(const sig of ['void OnTick()','void OnTradeTransaction(','void OnTimer(void)','bool DashboardTradeAllowed(const int op)','bool DashboardEntryAllowed(const int op)'])
  {assert.equal(body(norm(main),sig),body(norm(old),sig),sig);checks++;}
 // GoatTickBody's B44 lines: GoatRankTick (item 5) and the gate log's state copy and reset (item 4), all marked.
 const tick=body(norm(main),'void GoatTickBody()').split('\n').filter(l=>!/B44 item [45]/.test(l)&&l!=='    g_GoatGateStateRead=false;').join('\n');
 assert.equal(body(norm(main),'void GoatTickBody()').split('\n').length-tick.split('\n').length,3,'three B44 lines in GoatTickBody');
 assert.equal(tick,body(norm(old),'void GoatTickBody()'),'GoatTickBody is B43 plus the GoatRankTick line and the gate-state copy and reset');checks++;
}catch(e){if(e instanceof assert.AssertionError)throw e;}
console.log(JSON.stringify({passed:checks,differing,unitHistoryCompare:history,base:'B43 '+B43_TREE}));
