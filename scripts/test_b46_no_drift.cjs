// B46 no-drift guard (Claude-Mac's B45 review, goatai#2350 6186284858). Against B45 (1cd2ca91, whose source hashes are
// committed in candidate-builds/beta17-B45/identity.json):
// - the compile closure is the same 41 files and only the entrypoint differs (every B46 item lives in GOAT V1.49.mq5);
// - the input header (the contract pin, GoatFindMagicByCid included) and every other include are byte-identical, so no
//   input, default or enum changes and BlindExport stays the last input;
// - with history: OnTick, OnTradeTransaction, GoatTradeTransactionBody, OnTimer, DashboardTradeAllowed and
//   SignalEntryTrigger are B45's exact units; DashboardEntryAllowed and GoatTickBody are B45's plus the marked
//   "// B46:" lines only (the guard at the entry gate, the panel line and the dashboard row status). The guard itself
//   (GoatCidGuard*) is new and is exercised by test_cid_guard.cjs.
// Replaces test_b45_no_drift.cjs (B45's guard against B44), which pinned the tree to B45 by design.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B45_TREE='1cd2ca91';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const b45=JSON.parse(read('candidate-builds/beta17-B45/identity.json'));
const b46=JSON.parse(read('candidate-builds/beta17-B46/identity.json'));
let checks=0;
assert.deepEqual(Object.keys(b46.sources).sort(),Object.keys(b45.sources).sort(),'same compile closure as B45');checks++;
for(const [f,h] of Object.entries(b46.sources)) assert.equal(sha(read(f)),h,'B46 identity pins '+f);
checks++;
const differing=Object.keys(b46.sources).filter(f=>b46.sources[f]!==b45.sources[f]).sort();
assert.deepEqual(differing,['GOAT V1.49.mq5'],'only the entrypoint differs from B45');checks++;
const main=read('GOAT V1.49.mq5').toString('utf8');
assert.equal((main.match(/#define   GOAT_BUILD_ID "V1\.49-BETA17-46"\r\n/g)||[]).length,1);
assert.equal((main.match(/#define   GOAT_BUILD_MARKER "B46"\r\n/g)||[]).length,1);
assert.equal(b46.build_id,'V1.49-BETA17-46');assert.equal(b46.build_marker,'B46');assert.equal(b46.supersedes_candidate,'beta17-B45');checks++;
// The input contract (header pin) is unchanged; the main pin follows the entrypoint.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,b45.sources['GOAT_Inputs_Definitions.mqh']);assert.equal(deps.main_sha256,b46.sources['GOAT V1.49.mq5']);checks++;
const lastInput=[...main.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].at(-1);
assert.equal(lastInput[1],'BlindExport','no input added after BlindExport');checks++;
// With history: units compared unit by unit (string- and comment-aware brace matching).
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
const MARKED=/\n[^\n]*\/\/ B46: [^\n]*/g;
try{
 const old=execFileSync('git',['show',B45_TREE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');
 history=true;
 // The blob is stored with LF (.gitattributes); the tree and the pins are CRLF.
 assert.equal(sha(Buffer.from(old.replace(/\r?\n/g,'\r\n'),'utf8')),b45.sources['GOAT V1.49.mq5'],B45_TREE+' carries the B45 entrypoint');
 const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
 for(const sig of ['void OnTick()','void OnTradeTransaction(','void GoatTradeTransactionBody(','void OnTimer(void)','bool DashboardTradeAllowed(const int op)','void SignalEntryTrigger()'])
  {assert.equal(body(norm(main),sig),body(norm(old),sig),sig);checks++;}
 // DashboardEntryAllowed and GoatTickBody: B45's with the marked B46 lines taken out, and exactly these marked lines.
 const marked={'bool DashboardEntryAllowed(const int op)':['   if(GoatCidGuardRefuses(true)) return false; // B46: a missing or duplicate CID record refuses new sequences (GoatCidGuardEvaluate)'],
  'void GoatTickBody()':['    if(GoatCidGuardRefuses()) SetEdit(PanelDialog.m_edit_Info_2,"REFUSED: "+g_GoatCidGuardReason,clrRed,Font_Size); // B46: CID refusal on the panel',
   '     if(GoatCidGuardStatus()!="") dashboard_status=GoatCidGuardStatus(); // B46: the dashboard row shows a CID refusal']};
 for(const [sig,lines] of Object.entries(marked)){
  const now=body(norm(main),sig),was=body(norm(old),sig);
  assert.deepEqual((now.match(MARKED)||[]).map(l=>l.slice(1)),lines,sig+': the marked B46 lines');
  assert.equal(now.replace(MARKED,''),was,sig+' is B45 plus the marked B46 lines');checks++;
 }
 // Outside the new GoatCidGuard block and the marked lines, the entrypoint is B45's except the build ID and marker.
 const strip=t=>norm(t).replace(/\n\/\/-{20,}\n\/\/ B46 \(goatai#2350[\s\S]*?\n(?=\/\/-{20,}\n\/\/ Atomic asset-direction ownership)/,'\n').replace(MARKED,'')
  .replace(/"V1\.49-BETA17-4[56]"/,'"<id>"').replace(/GOAT_BUILD_MARKER "B4[56]"/,'GOAT_BUILD_MARKER "<m>"');
 assert.equal(strip(main),strip(old),'the entrypoint is B45 plus the GoatCidGuard block, the marked lines and the build identity');checks++;
}catch(e){if(e instanceof assert.AssertionError)throw e;}
console.log(JSON.stringify({passed:checks,differing,unitHistoryCompare:history,base:'B45 '+B45_TREE}));
