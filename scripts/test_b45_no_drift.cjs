// B45 no-drift guard (Claude-Mac's GOAT-EA#227 review). Against B44 (9d48236b, whose source hashes are committed in
// candidate-builds/beta17-B44/identity.json):
// - the compile closure is the same 41 files and only the entrypoint differs (every B45 item lives in GOAT V1.49.mq5);
// - the input header (the contract pin) and every other include are byte-identical, so no input, default or enum
//   changes and BlindExport stays the last input;
// - with history: OnTick, OnTradeTransaction, GoatTickBody, OnTimer, DashboardTradeAllowed and DashboardEntryAllowed
//   are B44's exact units; GoatTradeTransactionBody is B44's plus one marked line (trd_FOOS from dt_Fwrd_OOS, item 2).
//   The blind measurement (items 1-3) and the magic salt (item 4) are compared by test_blind_export.cjs and
//   test_child_magic_unique.cjs.
// Replaces test_b44_no_drift.cjs (B44's guard against B43), which pinned the tree to B44 by design.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B44_TREE='9d48236b';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const b44=JSON.parse(read('candidate-builds/beta17-B44/identity.json'));
const b45=JSON.parse(read('candidate-builds/beta17-B45/identity.json'));
let checks=0;
assert.deepEqual(Object.keys(b45.sources).sort(),Object.keys(b44.sources).sort(),'same compile closure as B44');checks++;
for(const [f,h] of Object.entries(b45.sources)) assert.equal(sha(read(f)),h,'B45 identity pins '+f);
checks++;
const differing=Object.keys(b45.sources).filter(f=>b45.sources[f]!==b44.sources[f]).sort();
assert.deepEqual(differing,['GOAT V1.49.mq5'],'only the entrypoint differs from B44');checks++;
const main=read('GOAT V1.49.mq5').toString('utf8');
assert.equal((main.match(/#define   GOAT_BUILD_ID "V1\.49-BETA17-45"\r\n/g)||[]).length,1);
assert.equal((main.match(/#define   GOAT_BUILD_MARKER "B45"\r\n/g)||[]).length,1);
assert.equal(b45.build_id,'V1.49-BETA17-45');assert.equal(b45.build_marker,'B45');assert.equal(b45.supersedes_candidate,'beta17-B44');checks++;
// The input contract (header pin) is unchanged; the main pin follows the entrypoint.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,b44.sources['GOAT_Inputs_Definitions.mqh']);assert.equal(deps.main_sha256,b45.sources['GOAT V1.49.mq5']);checks++;
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
try{
 const old=execFileSync('git',['show',B44_TREE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');
 history=true;
 // The blob is stored with LF (.gitattributes); the tree and the pins are CRLF.
 assert.equal(sha(Buffer.from(old.replace(/\r?\n/g,'\r\n'),'utf8')),b44.sources['GOAT V1.49.mq5'],B44_TREE+' carries the B44 entrypoint');
 const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
 for(const sig of ['void OnTick()','void OnTradeTransaction(','void GoatTickBody()','void OnTimer(void)','bool DashboardTradeAllowed(const int op)','bool DashboardEntryAllowed(const int op)'])
  {assert.equal(body(norm(main),sig),body(norm(old),sig),sig);checks++;}
 // GoatTradeTransactionBody: B44's with the one B45 line (FOOS from dt_Fwrd_OOS) put back as B44 wrote it.
 const now=body(norm(main),'void GoatTradeTransactionBody('),was=body(norm(old),'void GoatTradeTransactionBody(');
 const b45Line='   else if(TimeCurrent()>=dt_Fwrd_OOS && dt_Fwrd_OOS!=0) trd_FOOS++; // B45 item 2: FOOS starts at dt_Fwrd_OOS, as days_FOOS and the RANKED window';
 assert.equal(now.split(b45Line).length,2,'one marked B45 line');
 assert.equal(now.replace(b45Line,'   else if(TimeCurrent()>dt_Fwrd_OOS && dt_Fwrd_OOS!=0) trd_FOOS++;'),was,'GoatTradeTransactionBody is B44 plus the trd_FOOS boundary');checks++;
}catch(e){if(e instanceof assert.AssertionError)throw e;}
console.log(JSON.stringify({passed:checks,differing,unitHistoryCompare:history,base:'B44 '+B44_TREE}));
