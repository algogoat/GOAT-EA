// B51 no-drift guard (B50-beta-1, docs/b50/B50_ALPHA_DESIGN.md section 8: beta-1a, the random-direction benchmark,
// then beta-1b, the single's break-even and trailing, then the partial close and the demo gate; the assembly after). B51 = B50-alpha + B50-beta-1, each in its own
// reviewed PR. Against B50-alpha (source 32df4eb, GOAT-EA#278 merged; its source hashes are committed in
// candidate-builds/beta17-B50/identity.json):
// - every file of B50-alpha's compile closure outside CHANGED is byte-identical to B50-alpha;
// - in the CHANGED files, every line added or replaced since B50-alpha carries the marker "B51" or sits inside a
//   "// B51:begin <item>" ... "// B51:end <item>" block, so nothing changes unmarked; pure deletions are refused, and
//   every B50-alpha line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure gains no file (ADDED is empty);
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json was read from this header (test_studio_optimization_inputs proves it is exactly what discover reads);
//   inputs are append-only: B50-alpha's 127 inputs keep their order, type, default and enum choices, and the new ones are
//   exactly NEW_INPUTS, in order, at the very end (ruling, goatai#2587 6501903173). That is this guard's one explicit
//   allowance. B49b's inputs will slot in between B50-alpha's and these when the two lines merge: the merge updates
//   the allowance to name them (names are what matter), never this file's NEW_INPUTS;
// - the tree is B51's identity (candidate-builds/beta17-B51/identity.json, the assembly, as A4 was B50's; goatai#2750
//   6702775712): every source hashes to it, its sources are exactly the compile closure, and the build ID and marker
//   are its own. The build ID line is the one unmarked change (IDENTITY_LINES). (On the final build's merge, until its
//   assembly: see below.)
// test_b50_no_drift.cjs now proves B50-alpha's own commit, so the chain B49a -> B50 -> tree is checked end to end.
// The final build (B50 + B51 with B49b: the merge of claude-pc/b49b 808ff728, GOAT-EA#290 at c5e2fee1) carries B49b's changes too.
// Against B50-alpha they are accepted exactly as B49b's tree has them: B49B_CHANGED names B49b's other files; a line
// changed since B50-alpha may instead carry the marker "B49b" or sit in a "// B49b:begin" block, and then it must be a
// line of B49b's own tree (scripts/test_b49b_no_drift.cjs proves that tree against B49a); the B50-alpha lines removed are
// REMOVED, B49b's own removals and MERGE_REMOVED; no line that B49b or B51 added is lost. B49b's inputs sit between
// B50-alpha's and NEW_INPUTS with B49b's own definitions (the allowance names them; NEW_INPUTS is unchanged). Until the
// final build's assembly the tree keeps B51's name: B51's identity is its assembly commit's tree (b4844b2), and the tree
// differs from it in exactly CHANGED and B49B_CHANGED (the entrypoint also carries GOAT-EA#292's follow-ups).
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B51 change is marked, listed and reviewable. Neutrality with
// the new inputs at their defaults is proven by scripts/test_b51_parity.cjs (the converted OnTick region of B50-alpha
// and of this tree on the same fixtures, single and grid, and the WriteSet golden) and, natively, by the tester parity.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B50_SOURCE='32df4eb';
// The final build: B49b (GOAT-EA#290's approved head), B49a as B49b's guard reads it, and B51's assembly (its identity).
const B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a',B49B_SOURCE='808ff728fcbfb3734b09a866b4ff2e5ae856f3da',B51_SOURCE='b4844b2ee7de273b5e4b5cec8955ddcba8296e43';
// The merge's B51 side: B51's assembly plus GOAT-EA#292's follow-ups (claude-mac/b50-alpha 4fc885cf, #292 at 46d8bceb).
const B51_LINE='4fc885cfe96e35501a3b01ff1f53da92aacf7ff5';
// Each item PR adds the files it changes, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATPortfolioChildAudit.mqh'];
// The final build: B49b's other CHANGED files (scripts/test_b49b_no_drift.cjs's CHANGED, less the four above).
const B49B_CHANGED=['GOATStudioSettingCompare.mqh','Dashboard.mqh','Tester.mqh','XmlProcessor.mqh'];
const ALL_CHANGED=[...CHANGED,...B49B_CHANGED];
const ADDED=[];
// Every B50-alpha line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOAT V1.49.mq5':[
  'if(!PersistLive() || Active) return false;',
  'Alert(adopted);',
  'else',
  '#define   GOAT_BUILD_ID "V1.49-BETA17-50"','#define   GOAT_BUILD_MARKER "B50"',                                     // the assembly: the build identity
  'if(Engine_Mode==Engine_Single && AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) {Alert("Initialization Failed: the single-trade engine needs a hedging account (netting is not supported)."); return INIT_FAILED;}',
 ],
 'GOATStudioSettingTypes.mqh':[
  '+"Single_SL_ATR|Single_TP_ATR|Single_TP_R|Single_Exit_Opposite|Single_Time_Stop_Bars|Single_Time_Stop_TF|Rollover_Block_Minutes|"; // B50 (A0): the B50 optimization axes (NY_Session is a string, never one)', // beta-1a: the list continues with the B51 axes
 ],
};
// The final build: the B50-alpha lines the merge itself replaces (each replacement carries "B51").
const MERGE_REMOVED={
 'GOAT V1.49.mq5':[
  'if(TimeCurrent()>Expiry) {Alert("This version expired on "+TimeToString(Expiry,TIME_DATE)+". Go to "+URL_Web+" to download the latest version."); ExpertRemove(); return false;} // as Add_Level',   // GoatSingleOpen: B49b F1's manage-only on expiry
 ],
};
// The final build: B49b's inputs, between B50-alpha's and NEW_INPUTS (scripts/test_b49b_no_drift.cjs's NEW_INPUTS; Claude-Mac
// 6433854745 ruling 6).
const B49B_INPUTS=['Fix_MoneyVolume','Gate_Recheck','Fix_ClosePath','Max_Spread_Points','Min_Margin_Level_PC','Fix_Clock','Fix_FeedGuard','Diag_TickTiming','Fix_TickLoad'];
// The B50-beta-1 inputs, appended at the very end in this order (beta-1a, beta-1b, then the partial close).
const NEW_INPUTS=['Random_Direction','Random_Seed','Single_Flat_Only','Single_BE_ATR','Single_Trail_Start_ATR','Single_Trail_ATR','Single_Partial_ATR','Single_Partial_Fraction','Single_Partial_BE'];
const NEW_DEFAULTS={Random_Direction:['sinput','bool','false'],Random_Seed:['input','int','1'],Single_Flat_Only:['sinput','bool','false'],
 Single_BE_ATR:['input','double','0.0'],Single_Trail_Start_ATR:['input','double','0.0'],Single_Trail_ATR:['input','double','0.0'],
 Single_Partial_ATR:['input','double','0.0'],Single_Partial_Fraction:['input','double','0.0'],Single_Partial_BE:['input','bool','false']};
// The assembly: the build ID line (exact text in GOAT V1.49.mq5) is the one unmarked change: its value "V1.49-BETA17-51"
// is the build's name, so it cannot carry the marker inside the string; the marker line carries "B51" in its value.
const IDENTITY_LINES=['#define   GOAT_BUILD_ID "V1.49-BETA17-51"'];
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const b50=JSON.parse(git(['show',B50_SOURCE+':candidate-builds/beta17-B50/identity.json']).toString('utf8'));
git(['merge-base','--is-ancestor',B50_SOURCE,'HEAD']);   // throws unless the working tree descends from B50-alpha
git(['merge-base','--is-ancestor',B49B_SOURCE,'HEAD']);   // the final build: and from B49b
git(['merge-base','--is-ancestor',B51_SOURCE,B51_LINE]);  // the B51 side carries B51's assembly
git(['merge-base','--is-ancestor',B51_LINE,'HEAD']);      // and the tree descends from it
// The final build: a file as B49b's commit checks it out (null when B49b does not have it).
const atB49b=f=>{try{return checkedOut(f,git(['show',B49B_SOURCE+':'+f])).toString('utf8').replace(/^\uFEFF/,'');}catch{return null;}};
// The lines a diff between two commits adds and removes, per file.
function diffLines(from,to,f){
 const added=[],removed=[];
 for(const line of git(['diff','--no-color','--no-ext-diff','-U0',from,to,'--',f]).toString('utf8').split('\n')){
  if(line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+'))added.push(line.slice(1).replace(/\r$/,''));
  else if(line.startsWith('-'))removed.push(line.slice(1).replace(/\r$/,'').trim());
 }
 return {added,removed};
}
let checks=0;

// 1. The baseline really is B50-alpha: its commit's blobs (checked out as the tree would be) hash to B50's identity.
for(const [f,h] of Object.entries(b50.sources)){
 const blob=git(['show',B50_SOURCE+':'+f]);
 assert.equal(sha(checkedOut(f,blob)),h,'B50-alpha source '+B50_SOURCE+' is the identity of '+f);
}
assert.equal(b50.build_id+' '+b50.build_marker,'V1.49-BETA17-50 B50');
checks++;

// 2. The compile closure: B50-alpha's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b50Mql=Object.keys(b50.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b50Mql,...ADDED].sort(),'the compile closure is B50-alpha\'s plus ADDED');
checks++;

// 3. Outside CHANGED (and, on the final build, B49B_CHANGED), every B50-alpha source is byte-identical; every one of them
// did change; each keeps BOM + CRLF.
for(const [f,h] of Object.entries(b50.sources)) if(!ALL_CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B50-alpha: '+f);
for(const f of ALL_CHANGED){
 assert.notEqual(sha(read(f)),b50.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines,tag='B51'){   // the final build: B49b's blocks are tracked on their own
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(new RegExp('// '+tag+':begin (\\S+)')),end=line.match(new RegExp('// '+tag+':end (\\S+)'));
  if(begin){assert.equal(open,null,'nested '+tag+' block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,tag+':end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed '+tag+' block '+open);
 return inBlock;
}
const count=list=>list.reduce((m,t)=>m.set(t,(m.get(t)||0)+1),new Map());
// The final build's review fixes (B52: the independent read of the merge, goatai#2750 6705041540) are marked "B52" or sit
// in "// B52:begin" blocks, and are accepted as B51's are; they only add lines.
for(const f of ALL_CHANGED){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines),inB49b=markedBlocks(lines,'B49b'),inB52=markedBlocks(lines,'B52');
 const b49bText=atB49b(f),b49bLines=new Set(b49bText===null?[]:b49bText.split('\r\n'));
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B50_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B50-alpha');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B50-alpha line(s) is unmarked');
  for(const n of added){
   const text=lines[n-1];
   if(/B51|B52/.test(text)||inBlock[n-1]||inB52[n-1]||(f==='GOAT V1.49.mq5'&&IDENTITY_LINES.includes(text)))continue;
   // The final build: otherwise it is a B49b change, exactly as B49b's own tree has it.
   assert.ok((/B49b/.test(text)||inB49b[n-1])&&b49bLines.has(text),f+':'+n+' changed since B50-alpha without a B51 marker or as B49b\'s own marked line: '+text.trim());
  }
 }
 // The final build: B51's removals, B49b's own (its guard proves they are exactly its REMOVED) and the merge's.
 const b49bRemoved=diffLines(B49A_SOURCE,B49B_SOURCE,f).removed;
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[]),...b49bRemoved,...(MERGE_REMOVED[f]||[])].sort(),f+': the B50-alpha lines removed are exactly REMOVED, B49b\'s own and MERGE_REMOVED');
 // The final build: no line B49b or B51 added is lost in the merge (as many copies as each side added).
 const tree=count(lines);
 for(const [label,from,to] of [['B49b',B49A_SOURCE,B49B_SOURCE],['B51',B50_SOURCE,B51_LINE]])
  for(const [text,n] of count(diffLines(from,to,f).added)) assert.ok((tree.get(text)||0)>=n,f+': a line '+label+' added is lost in the merge: '+text.trim());
}
checks++;

// 5. The input contract follows the tree, append-only against B50-alpha, with exactly NEW_INPUTS at the end.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
const schema=JSON.parse(read('controller/contracts/v149/inputs.json').toString('utf8').replace(/^﻿/,''));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(git(['show',B50_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^﻿/,''));
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.equal(beforeNames.length,127,'B50-alpha declares 127 header inputs');assert.equal(beforeNames.at(-1),'Rollover_Block_Minutes');
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B50-alpha\'s inputs keep their order');
for(const name of beforeNames) assert.deepEqual(schema.inputs[name],before.inputs[name],'B50-alpha input unchanged: '+name);
// The one allowance: the new inputs are exactly NEW_INPUTS, appended at the very end. The final build: B49b's come first,
// as B49b declares them.
assert.deepEqual(names.slice(beforeNames.length),[...B49B_INPUTS,...NEW_INPUTS],'new inputs (B49b\'s, then these at the end of the header)');
const b49bSchema=JSON.parse(git(['show',B49B_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^\uFEFF/,''));
for(const name of B49B_INPUTS) assert.deepEqual(schema.inputs[name],b49bSchema.inputs[name],'B49b input as B49b declares it: '+name);
for(const name of NEW_INPUTS){
 const [declaration,type,def]=NEW_DEFAULTS[name],d=schema.inputs[name];
 assert.deepEqual([d.declaration,d.type,d.default_expression],[declaration,type,def],'B51 input definition: '+name);
}
// They sit in their own input group, the header's last.
const header=read('GOAT_Inputs_Definitions.mqh').toString('utf8');
const groups=[...header.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/^input\s+group\s+"([^"]*)"/gm)].map(m=>m[1]);
assert.equal(groups.at(-1),'====SINGLE EXITS / BENCHMARK (B50-beta)====','the B50-beta group is the last');
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B50_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
checks++;

// 6. B51's identity is its own commit's (the assembly, GOAT-EA#293 head b4844b2e; goatai#2750 6702775712), as
// test_b50_no_drift.cjs proves B50-alpha's own commit: every identity source hashes to that commit's blob as it checks
// out, the identity file is unchanged, the tree descends from it, and its sources are the tree's compile closure. Later
// B51-line changes (GOAT-EA#292) differ from it only in marked lines (sections 3-4); the tree keeps B51's build ID and
// marker, once each, until the next assembly stamps its own. The final build (B49b merged in), until its assembly: the tree
// differs from B51's identity in exactly CHANGED and B49B_CHANGED, each checked line by line above (B51_SOURCE is defined
// with the merge's other commits, at the top).
git(['merge-base','--is-ancestor',B51_SOURCE,'HEAD']);   // throws unless the working tree descends from B51's identity commit
const b51Raw=git(['show',B51_SOURCE+':candidate-builds/beta17-B51/identity.json']);
const b51=JSON.parse(b51Raw.toString('utf8').replace(/^﻿/,''));
assert.deepEqual(JSON.parse(read('candidate-builds/beta17-B51/identity.json').toString('utf8').replace(/^﻿/,'')),b51,'B51\'s identity file is unchanged');
assert.equal(b51.build_id+' '+b51.build_marker,'V1.49-BETA17-51 B51');
assert.equal(b51.supersedes_candidate,'beta17-B50');
assert.deepEqual(Object.keys(b51.sources).sort(),closure(),'B51\'s identity names exactly the compile closure');
for(const [f,h] of Object.entries(b51.sources)) assert.equal(sha(checkedOut(f,git(['show',B51_SOURCE+':'+f]))),h,'B51 identity source at '+B51_SOURCE+': '+f);
assert.deepEqual(Object.keys(b51.sources).filter(f=>sha(read(f))!==b51.sources[f]).sort(),[...ALL_CHANGED].sort(),'the tree differs from B51\'s identity in exactly CHANGED and B49B_CHANGED');
const mainText=read('GOAT V1.49.mq5').toString('utf8');
assert.equal(mainText.split('\r\n').filter(l=>l===IDENTITY_LINES[0]).length,1,'the build ID is B51\'s');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_MARKER "B51"').length,1,'the marker is B51\'s');
checks++;

console.log('b51_no_drift: '+checks+' checks passed (B50-alpha '+B50_SOURCE+', changed: '+CHANGED.join(', ')+'; with B49b '+B49B_SOURCE.slice(0,8)+': '+B49B_CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; new inputs: '+NEW_INPUTS.join(', ')+')');
