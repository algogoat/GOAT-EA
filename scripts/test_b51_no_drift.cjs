// B51 no-drift guard (B50-beta-1, docs/b50/B50_ALPHA_DESIGN.md section 8: beta-1a, the random-direction benchmark,
// then beta-1b, the single's break-even and trailing; the assembly after). B51 = B50-alpha + B50-beta-1, each in its own
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
// - the build identity is still B50-alpha's (V1.49-BETA17-50, marker B50): the assembly PR stamps beta-1's, as A4 did.
// test_b50_no_drift.cjs now proves B50-alpha's own commit, so the chain B49a -> B50 -> tree is checked end to end.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B51 change is marked, listed and reviewable. Neutrality with
// the new inputs at their defaults is proven by scripts/test_b51_parity.cjs (the converted OnTick region of B50-alpha
// and of this tree on the same fixtures, single and grid, and the WriteSet golden) and, natively, by the tester parity.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B50_SOURCE='32df4eb';
// Each item PR adds the files it changes, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATPortfolioChildAudit.mqh'];
const ADDED=[];
// Every B50-alpha line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOATStudioSettingTypes.mqh':[
  '+"Single_SL_ATR|Single_TP_ATR|Single_TP_R|Single_Exit_Opposite|Single_Time_Stop_Bars|Single_Time_Stop_TF|Rollover_Block_Minutes|"; // B50 (A0): the B50 optimization axes (NY_Session is a string, never one)', // beta-1a: the list continues with the B51 axes
 ],
};
// The B50-beta-1 inputs, appended at the very end in this order (beta-1a).
const NEW_INPUTS=['Random_Direction','Random_Seed'];
const NEW_DEFAULTS={Random_Direction:['sinput','bool','false'],Random_Seed:['input','int','1']};
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const b50=JSON.parse(git(['show',B50_SOURCE+':candidate-builds/beta17-B50/identity.json']).toString('utf8'));
git(['merge-base','--is-ancestor',B50_SOURCE,'HEAD']);   // throws unless the working tree descends from B50-alpha
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

// 3. Outside CHANGED, every B50-alpha source is byte-identical; every CHANGED file did change; each keeps BOM + CRLF.
for(const [f,h] of Object.entries(b50.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B50-alpha: '+f);
for(const f of CHANGED){
 assert.notEqual(sha(read(f)),b50.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B51:begin (\S+)/),end=line.match(/\/\/ B51:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B51 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B51:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B51 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines);
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
   assert.ok(/B51/.test(text)||inBlock[n-1],f+':'+n+' changed since B50-alpha without a B51 marker: '+text.trim());
  }
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B50-alpha lines removed are exactly REMOVED');
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
// The one allowance: the new inputs are exactly NEW_INPUTS, appended at the very end.
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (appended at the end of the header)');
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

// 6. The build identity is still B50-alpha's: the assembly stamps beta-1's (as A4 stamped B50's).
const mainText=read('GOAT V1.49.mq5').toString('utf8');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_ID "V1.49-BETA17-50"').length,1,'the build ID is B50-alpha\'s until the assembly');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_MARKER "B50"').length,1,'the marker is B50-alpha\'s until the assembly');
checks++;

console.log('b51_no_drift: '+checks+' checks passed (B50-alpha '+B50_SOURCE+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; new inputs: '+NEW_INPUTS.join(', ')+')');
