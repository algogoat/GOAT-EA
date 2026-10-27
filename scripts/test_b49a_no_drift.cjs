// B49a no-drift guard (WEEKEND-1031, goatai#2587 6427654059 / 6427772701). B49a = B47 + B48's CID touch + F2 (ledger
// position join) + F1-lite (restart adoption, manage-only) + 64-bit tickets, each in its own reviewed PR into
// claude-pc/b49a. Against B47 (source ccb0a07, whose source hashes are committed in
// candidate-builds/beta17-B47/identity.json):
// - every file of B47's compile closure outside CHANGED is byte-identical to B47;
// - in the CHANGED files, every line added or replaced since B47 carries the marker "B49a" or sits inside a
//   "// B49a:begin <item>" ... "// B49a:end <item>" block, so nothing changes unmarked; pure deletions are refused,
//   and every B47 line removed inside a changed hunk is listed verbatim in REMOVED (Claude-Mac, GOAT-EA#263 P2);
// - the compile closure only gains the files in ADDED;
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json is exactly what studio_input_schema.discover reads from this header (test_studio_optimization_inputs);
//   inputs are append-only: B47's 114 inputs keep their type, default and enum choices, and new ones follow BlindExport.
// - the tree is B49a's identity (candidate-builds/beta17-B49a/identity.json): every source hashes to it, it differs from
//   B47 in exactly CHANGED, and the build ID and marker are its own. The build ID line is the one unmarked change
//   (IDENTITY_LINES): its value "V1.49-BETA17-49" is the build's name, so it cannot carry the marker inside the string.
// Replaces test_b47_no_drift.cjs (B47's guard against B46), which pinned the tree to B47 by design.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B49a change is marked, listed and reviewable. A marked line
// or a marked block can still change behaviour. Neutrality with the new inputs at their defaults is proven only by
// the tester parity on Banker (flags off, B49a against B47 byte-identical on the 48 templates and sampled exports).
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B47_SOURCE='ccb0a07';
// Each item PR adds the files it changes or adds, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATStudioSettingCompare.mqh','GOATPortfolioChildAudit.mqh'];   // F2: the Studio's input type allowlist and readback; the child audit's Ledger_Mode default (Codex #267)
const ADDED=[];
// Every B47 line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOAT V1.49.mq5':[
  'LastOrderTicket=(int)resolvedPositionTicket;','LastDealTicket=LastBuyTicket=(int)result.deal;',                // tickets
  'LastOrderTicket=(int)resolvedPositionTicket;','LastDealTicket=LastSellTicket=(int)result.deal;',               // tickets
  'if(HistoryDealGetInteger(ticket,DEAL_MAGIC)!=MAGIC1)       continue;',                                           // F2: dashboard rebuild
  'if(HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=MAGIC1) return;',                                              // F2: transaction path
  'if(HistoryDealGetInteger(ticket,DEAL_MAGIC) != MAGIC1)        continue;',                                        // F2: daily P/L
  'if((bid!=LastATRBid || ask!=LastATRAsk) && !Seq_Buy.Active && !Seq_Sell.Active)// && !Seq_Buy_Virtual.Active && !Seq_Sell_Virtual.Active)', // F1-lite: GetSize refills an empty ATR_Buf
  'CopyBuffer(ATR_MA_handle,0,1,1,ATR_Buf); ATR_Pips = NormalizeDouble(ATR_Buf[0]/(_Point*10.0),1);',            // F1-lite: never index an empty ATR_Buf
  'CopyBuffer(ATR_MA_handle,0,0,1,ATR_Buf); ATR_Pips = NormalizeDouble(ATR_Buf[0]/(_Point*10),1);',              // F1-lite: never index an empty ATR_Buf
  '#define   GOAT_BUILD_ID "V1.49-BETA17-47"','#define   GOAT_BUILD_MARKER "B47"',                                     // assembly: the build identity
 ],
 'GOAT_Inputs_Definitions.mqh':[
  'int      LastOrderTicket,LastDealTicket,LastBuyTicket,LastSellTicket,LastTradeCountBuy=0,LastTradeCountSell=0;', // tickets
 ],
};
const NEW_INPUTS=['Ledger_Mode'];   // F2
// The assembly's build ID line (exact text in GOAT V1.49.mq5); the marker line carries "B49a" in its value.
const IDENTITY_LINES=['#define   GOAT_BUILD_ID "V1.49-BETA17-49"'];
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const b47=JSON.parse(read('candidate-builds/beta17-B47/identity.json'));
let checks=0;

// 1. The baseline really is B47: its commit's blobs (checked out as the tree would be) hash to B47's identity.
for(const [f,h] of Object.entries(b47.sources)){
 const blob=git(['show',B47_SOURCE+':'+f]);
 assert.equal(sha(checkedOut(f,blob)),h,'B47 source '+B47_SOURCE+' is the identity of '+f);
}
checks++;

// 2. The compile closure: B47's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b47Mql=Object.keys(b47.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b47Mql,...ADDED].sort(),'the compile closure is B47\'s plus ADDED');checks++;

// 3. Outside CHANGED (and the new files), every B47 source is byte-identical.
for(const [f,h] of Object.entries(b47.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B47: '+f);
for(const f of CHANGED) assert.notEqual(sha(read(f)),b47.sources[f],'CHANGED lists only files that changed: '+f);
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B49a:begin (\S+)/),end=line.match(/\/\/ B49a:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B49a block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B49a:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B49a block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B47_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B47');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B47 line(s) is unmarked');
  for(const n of added){
   const text=lines[n-1];
   assert.ok(/B49a/.test(text)||inBlock[n-1]||(f==='GOAT V1.49.mq5'&&IDENTITY_LINES.includes(text)),f+':'+n+' changed since B47 without a B49a marker: '+text.trim());
  }
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B47 lines removed are exactly REMOVED');
}
checks++;

// 5. The input contract follows the tree, append-only against B47.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
const schema=JSON.parse(read('controller/contracts/v149/inputs.json').toString('utf8').replace(/^﻿/,''));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(git(['show',B47_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^﻿/,''));
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B47\'s inputs keep their order');
for(const name of beforeNames) assert.deepEqual(schema.inputs[name],before.inputs[name],'B47 input unchanged: '+name);
// The header's new inputs are exactly NEW_INPUTS, appended after B47's; the entrypoint's own inputs are B47's.
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (appended to the header)');
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B47_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
checks++;

// 6. The tree is B49a's identity.
const b49a=JSON.parse(read('candidate-builds/beta17-B49a/identity.json'));
assert.equal(b49a.build_id,'V1.49-BETA17-49');assert.equal(b49a.build_marker,'B49a');assert.equal(b49a.supersedes_candidate,'beta17-B47');
assert.deepEqual(Object.keys(b49a.sources).sort(),[...Object.keys(b47.sources),...ADDED].sort(),'B49a\'s identity covers B47\'s closure plus ADDED');
for(const [f,h] of Object.entries(b49a.sources)) assert.equal(sha(read(f)),h,'B49a identity pins '+f);
assert.deepEqual(Object.keys(b49a.sources).filter(f=>b49a.sources[f]!==b47.sources[f]).sort(),[...CHANGED,...ADDED].sort(),'B49a differs from B47 in exactly CHANGED and ADDED');
const mainText=read('GOAT V1.49.mq5').toString('utf8');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_ID "'+b49a.build_id+'"').length,1,'the build ID is the identity\'s');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_MARKER "'+b49a.build_marker+'"').length,1,'the marker is the identity\'s');
assert.equal((mainText.match(/#define\s+GOAT_BUILD_(?:ID|MARKER)\b/g)||[]).length,2,'one build ID and one marker');
assert.equal(deps.main_sha256,b49a.sources['GOAT V1.49.mq5'],'the contract pins the identity\'s entrypoint');
checks++;

console.log('b49a_no_drift: '+checks+' checks passed (B47 '+B47_SOURCE+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+')');
