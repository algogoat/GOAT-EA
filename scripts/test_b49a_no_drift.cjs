// B49a no-drift guard (WEEKEND-1031, goatai#2587 6427654059 / 6427772701). B49a = B47 + B48's CID touch + F2 (ledger
// position join) + F1-lite (restart adoption, manage-only) + 64-bit tickets, each in its own reviewed PR into
// claude-pc/b49a. Against B47 (source ccb0a07, whose source hashes are committed in
// candidate-builds/beta17-B47/identity.json):
// - every file of B47's compile closure outside CHANGED is byte-identical to B47;
// - in the CHANGED files, every line added or replaced since B47 carries the marker "B49a" or sits inside a
//   "// B49a:begin <item>" ... "// B49a:end <item>" block, so nothing changes unmarked; pure deletions are refused;
// - the compile closure only gains the files in ADDED;
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json is exactly what studio_input_schema.discover reads from this header (test_studio_optimization_inputs);
//   inputs are append-only: B47's 114 inputs keep their type, default and enum choices, and new ones follow BlindExport.
// Replaces test_b47_no_drift.cjs (B47's guard against B46), which pinned the tree to B47 by design. The B49a
// assembly PR adds the compiled identity and binds the tree to it.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B47_SOURCE='ccb0a07';
// Each item PR adds the files it changes or adds, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh'];
const ADDED=[];
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
 let newLine=0,hunk=null;const hunks=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-'))hunk.removed++;
 }
 assert.ok(hunks.length>0,f+' differs from B47');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B47 line(s) is unmarked');
  for(const n of added){
   const text=lines[n-1];
   assert.ok(/B49a/.test(text)||inBlock[n-1],f+':'+n+' changed since B47 without a B49a marker: '+text.trim());
  }
 }
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
// New inputs are declared after BlindExport, B47's last input in the entrypoint.
const declared=[...read('GOAT V1.49.mq5').toString('utf8').matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
const blind=declared.indexOf('BlindExport');assert.ok(blind>=0,'BlindExport is declared');
for(const name of declared.slice(0,blind+1)) assert.ok(!names.includes(name)||beforeNames.includes(name),'new input before BlindExport: '+name);
checks++;

console.log('b49a_no_drift: '+checks+' checks passed (B47 '+B47_SOURCE+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+')');
