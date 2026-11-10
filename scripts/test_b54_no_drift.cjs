// B54 no-drift guard (docs/b54/BREAKOUT_ENTRIES_SPEC.md section 6.3). B54 = B53 (the final build V1.49-BETA17-53, merge
// 216e1622 of GOAT-EA#296; its source hashes are committed in candidate-builds/beta17-B53/identity.json) plus the breakout
// entries, each in its own reviewed PR. PR A0 (gate 0, section 6.2) declares the 14 inputs and their enums, WriteSet's
// lines, the Studio types, axes and defaults and the child audit's names; no trading logic reads the inputs yet. Against B53:
// - every file of B53's compile closure outside CHANGED is byte-identical to B53;
// - in the CHANGED files, every line added or replaced since B53 carries the marker "B54" or sits inside a
//   "// B54:begin <item>" ... "// B54:end <item>" block, so nothing changes unmarked; pure deletions are refused, and every
//   B53 line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure gains no file (ADDED is empty);
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json was read from this header (test_studio_optimization_inputs and test_b54_gate0.py prove it is exactly what
//   discover reads); inputs are append-only: B53's 145 header inputs keep their order, type, default and enum
//   choices, and the new ones are exactly NEW_INPUTS, in order, at the very end, in their own group, the header's last.
//   That is this guard's one explicit allowance;
// - each later B54 PR adds the files and REMOVED lines it changes (section 6.3: SignalEntryTrigger's and GoatSignalAll's
//   closing-paren lines), so the review sees the lists grow. A0 leaves the entrypoint byte-identical to B53's.
// test_b51_no_drift.cjs now proves B53's own commit (as test_b50_no_drift.cjs proves B50-alpha's), so the chain
// B49a -> B50 -> B53 -> tree is checked end to end.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B54 change is marked, listed and reviewable. Neutrality with the
// new inputs at their defaults is proven by gate 0 (scripts/test_b54_gate0.cjs and controller/test_b54_gate0.py, on the 61
// pool SETs) and, later, by scripts/test_b54_parity.cjs and the native Banker parity on all 61 (ruling 3).
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B53_SOURCE='216e16225441cfc1bfe0546c1c70adaf327405cf';
// Each item PR adds the files it changes, so the review sees the list grow.
const CHANGED=['GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATPortfolioChildAudit.mqh'];
const ADDED=[];
// Every B53 line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOATStudioSettingTypes.mqh':[
  '+"Random_Seed|Single_BE_ATR|Single_Trail_Start_ATR|Single_Trail_ATR|Single_Partial_ATR|Single_Partial_Fraction|Single_Partial_BE|"; // B51 (beta-1a, beta-1b, section 8.3): the B50-beta optimization axes (Random_Direction is an sinput, never one)', // A0: the list continues with the B54 axes
 ],
};
// The B54 inputs (spec sections 3.1 and 4.1), appended at the very end in this order: family A, then family B.
const NEW_INPUTS=['BRK_Mode','BRK_TF_','BRK_Bars','BRK_Buffer_ATR','BRK_Once_Per_Level','ORB_Mode','ORB_Clock','ORB_TF_',
 'ORB_Start_Minute','ORB_Range_Minutes','ORB_Entry_Minutes','ORB_Buffer_ATR','ORB_Min_Range_ATR','ORB_Max_Range_ATR'];
const NEW_DEFAULTS={BRK_Mode:['sinput','ENUM_MODE_BRK','BRK_Disabled'],BRK_TF_:['input','ENUM_MODE_TFs','TF_H1'],BRK_Bars:['input','int','20'],
 BRK_Buffer_ATR:['input','double','0.0'],BRK_Once_Per_Level:['input','bool','true'],ORB_Mode:['sinput','ENUM_MODE_ORB','ORB_Disabled'],
 ORB_Clock:['sinput','ENUM_ORB_CLOCK','ORB_Clock_NewYork'],ORB_TF_:['input','ENUM_MODE_TFs','TF_M5'],ORB_Start_Minute:['input','int','570'],
 ORB_Range_Minutes:['input','int','30'],ORB_Entry_Minutes:['input','int','0'],ORB_Buffer_ATR:['input','double','0.0'],
 ORB_Min_Range_ATR:['input','double','0.0'],ORB_Max_Range_ATR:['input','double','0.0']};
const NEW_ENUMS={ENUM_MODE_BRK:{BRK_Disabled:0,BRK_NBar:1,BRK_PriorDay:2},ENUM_MODE_ORB:{ORB_Disabled:0,ORB_Breakout:1},
 ENUM_ORB_CLOCK:{ORB_Clock_NewYork:0,ORB_Clock_London:1}};
const GROUP='====SINGLE BREAKOUT ENTRIES (B54)====';
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
git(['merge-base','--is-ancestor',B53_SOURCE,'HEAD']);   // throws unless the working tree descends from B53
const b53=JSON.parse(git(['show',B53_SOURCE+':candidate-builds/beta17-B53/identity.json']).toString('utf8').replace(/^﻿/,''));
let checks=0;

// 1. The baseline really is B53: its commit's blobs (checked out as the tree would be) hash to B53's identity, which the
// tree keeps unchanged.
for(const [f,h] of Object.entries(b53.sources)) assert.equal(sha(checkedOut(f,git(['show',B53_SOURCE+':'+f]))),h,'B53 source '+B53_SOURCE.slice(0,8)+' is the identity of '+f);
assert.equal(b53.build_id+' '+b53.build_marker,'V1.49-BETA17-53 B53');
assert.deepEqual(JSON.parse(read('candidate-builds/beta17-B53/identity.json').toString('utf8').replace(/^﻿/,'')),b53,'B53\'s identity file is unchanged');
checks++;

// 2. The compile closure: B53's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b53Mql=Object.keys(b53.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b53Mql,...ADDED].sort(),'the compile closure is B53\'s plus ADDED');
checks++;

// 3. Outside CHANGED, every B53 source is byte-identical; every CHANGED file did change and keeps BOM + CRLF.
for(const [f,h] of Object.entries(b53.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B53: '+f);
for(const f of CHANGED){
 assert.notEqual(sha(read(f)),b53.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B54:begin (\S+)/),end=line.match(/\/\/ B54:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B54 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B54:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B54 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B53_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B53');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B53 line(s) is unmarked');
  for(const n of added){const text=lines[n-1];assert.ok(/B54/.test(text)||inBlock[n-1],f+':'+n+' changed since B53 without a B54 marker: '+text.trim());}
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B53 lines removed are exactly REMOVED');
}
for(const f of Object.keys(REMOVED)) assert.ok(CHANGED.includes(f),'REMOVED names only CHANGED files: '+f);
checks++;

// 5. The input contract follows the tree, append-only against B53, with exactly NEW_INPUTS at the end in their own group.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
assert.equal(deps.main_sha256,b53.sources['GOAT V1.49.mq5'],'A0: the entrypoint is B53\'s');
const schema=JSON.parse(read('controller/contracts/v149/inputs.json').toString('utf8').replace(/^﻿/,''));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(git(['show',B53_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^﻿/,''));
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.equal(beforeNames.length,145,'B53 declares 145 header inputs');assert.equal(beforeNames.at(-1),'Single_Partial_BE');
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B53\'s inputs keep their order');
for(const name of beforeNames) assert.deepEqual(schema.inputs[name],before.inputs[name],'B53 input unchanged: '+name);
assert.deepEqual(schema.defines,before.defines,'the defines are B53\'s');
// The one allowance: the new inputs are exactly NEW_INPUTS, appended at the very end, as the spec declares them.
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (at the end of the header)');
for(const name of NEW_INPUTS){
 const [declaration,type,def]=NEW_DEFAULTS[name],d=schema.inputs[name];
 assert.deepEqual([d.declaration,d.type,d.default_expression],[declaration,type,def],'B54 input definition: '+name);
 assert.deepEqual(d.enum_choices,type==='ENUM_MODE_TFs'?before.inputs.ATR_TF_.enum_choices:(NEW_ENUMS[type]||null),'B54 input choices: '+name);
}
// No B53 enum gains a value (the new enums are new types, with their own labels).
for(const name of beforeNames) if(before.inputs[name].enum_choices) for(const t of Object.keys(NEW_ENUMS)) assert.notEqual(before.inputs[name].type,t,'a new enum, not an existing one: '+t);
// They sit in their own input group, the header's last.
const header=read('GOAT_Inputs_Definitions.mqh').toString('utf8');
const groups=[...header.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/^input\s+group\s+"([^"]*)"/gm)].map(m=>m[1]);
assert.equal(groups.at(-1),GROUP,'the B54 group is the last');
assert.equal(groups.filter(g=>g===GROUP).length,1,'once');
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B53_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
checks++;

console.log('b54_no_drift: '+checks+' checks passed (B53 '+B53_SOURCE.slice(0,8)+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; new inputs: '+NEW_INPUTS.join(', ')+')');
