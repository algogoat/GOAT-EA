// B47 no-drift guard (Claude-Mac's B46 review, goatai#2350). Against B46 (b2980b1a, whose source hashes are committed
// in candidate-builds/beta17-B46/identity.json):
// - the compile closure is the same 41 files and only the entrypoint differs (every B47 item lives in GOAT V1.49.mq5);
// - the input header (the contract pin) and every other include are byte-identical, so no input, default or enum
//   changes and BlindExport stays the last input;
// - with history: OnTick, OnTradeTransaction, GoatTradeTransactionBody, OnTimer, DashboardTradeAllowed,
//   DashboardEntryAllowed, SignalEntryTrigger and GoatTickBody are B46's exact units; GoatTimerBody and
//   SEQUENCE::Add_Level are B46's plus the marked "// B47:" line only (the claim heartbeat, the cid_duplicate add
//   freeze). Outside the GoatCidGuard block (B46 + B47) and the marked lines, the entrypoint is B46's except the build
//   identity. The guard block is exercised by test_cid_guard.cjs and test_cid_guard_mutations.cjs.
// Replaces test_b46_no_drift.cjs (B46's guard against B45), which pinned the tree to B46 by design.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B46_TREE='b2980b1a';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const b46=JSON.parse(read('candidate-builds/beta17-B46/identity.json'));
const b47=JSON.parse(read('candidate-builds/beta17-B47/identity.json'));
let checks=0;
assert.deepEqual(Object.keys(b47.sources).sort(),Object.keys(b46.sources).sort(),'same compile closure as B46');checks++;
for(const [f,h] of Object.entries(b47.sources)) assert.equal(sha(read(f)),h,'B47 identity pins '+f);
checks++;
const differing=Object.keys(b47.sources).filter(f=>b47.sources[f]!==b46.sources[f]).sort();
assert.deepEqual(differing,['GOAT V1.49.mq5'],'only the entrypoint differs from B46');checks++;
const main=read('GOAT V1.49.mq5').toString('utf8');
assert.equal((main.match(/#define   GOAT_BUILD_ID "V1\.49-BETA17-47"\r\n/g)||[]).length,1);
assert.equal((main.match(/#define   GOAT_BUILD_MARKER "B47"\r\n/g)||[]).length,1);
assert.equal(b47.build_id,'V1.49-BETA17-47');assert.equal(b47.build_marker,'B47');assert.equal(b47.supersedes_candidate,'beta17-B46');checks++;
// The input contract (header pin) is unchanged; the main pin follows the entrypoint.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,b46.sources['GOAT_Inputs_Definitions.mqh']);assert.equal(deps.main_sha256,b47.sources['GOAT V1.49.mq5']);checks++;
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
const MARKED=/\n[^\n]*\/\/ B47: [^\n]*/g;
try{
 const old=execFileSync('git',['show',B46_TREE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');
 history=true;
 // The blob is stored with LF (.gitattributes); the tree and the pins are CRLF.
 assert.equal(sha(Buffer.from(old.replace(/\r?\n/g,'\r\n'),'utf8')),b46.sources['GOAT V1.49.mq5'],B46_TREE+' carries the B46 entrypoint');
 const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
 for(const sig of ['void OnTick()','void OnTradeTransaction(','void GoatTradeTransactionBody(','void OnTimer(void)','bool DashboardTradeAllowed(const int op)',
   'bool DashboardEntryAllowed(const int op)','void SignalEntryTrigger()','void GoatTickBody()'])
  {assert.equal(body(norm(main),sig),body(norm(old),sig),sig);checks++;}
 // GoatTimerBody and SEQUENCE::Add_Level: B46's with the marked B47 line taken out, and exactly that line.
 const marked={'void GoatTimerBody(void)':['   GoatCidGuardHeartbeat(); // B47: the claim heartbeat (every GOAT_CID_CLAIM_HEARTBEAT_MS; live trading charts only)'],
  '   bool Add_Level(double Level_New)':['    if(!Virtual && GoatCidGuardAddFrozen(dir,Level_Count+1)) return false; // B47: cid_duplicate freezes adds (grid and rescue) of a real sequence']};
 for(const [sig,lines] of Object.entries(marked)){
  const now=body(norm(main),sig),was=body(norm(old),sig);
  assert.deepEqual((now.match(MARKED)||[]).map(l=>l.slice(1)),lines,sig+': the marked B47 lines');
  assert.equal(now.replace(MARKED,''),was,sig+' is B46 plus the marked B47 line');checks++;
 }
 // Outside the GoatCidGuard block and the marked lines, the entrypoint is B46's except the build ID and marker.
 const strip=t=>norm(t).replace(/\n\/\/-{20,}\n\/\/ B46 \(goatai#2350[\s\S]*?\n(?=\/\/-{20,}\n\/\/ Atomic asset-direction ownership)/,'\n').replace(MARKED,'')
  .replace(/"V1\.49-BETA17-4[67]"/,'"<id>"').replace(/GOAT_BUILD_MARKER "B4[67]"/,'GOAT_BUILD_MARKER "<m>"');
 assert.equal(strip(main),strip(old),'the entrypoint is B46 plus the GoatCidGuard block changes, the marked lines and the build identity');checks++;
}catch(e){if(e instanceof assert.AssertionError)throw e;}
console.log(JSON.stringify({passed:checks,differing,unitHistoryCompare:history,base:'B46 '+B46_TREE}));
