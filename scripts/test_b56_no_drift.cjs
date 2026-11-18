// B56 no-drift guard. B56 = B55 (the demo candidate V1.49-BETA17-55, claude-pc/b55-assembly 41396df; its source hashes are
// committed in candidate-builds/beta17-B55/identity.json) plus reviewed, marked items, each in its own PR. The first item is
// swap-spec (swap guard step 3, INV-SWAP-01; Claude-Mac goatai#2750 6978371254): the run.csv header of a sequence capture
// records the symbol spec the run is charged from (seven keys, appended after initial_orders). Against B55:
// - every file of B55's compile closure outside CHANGED is byte-identical to B55;
// - in the CHANGED files, every line added or replaced since B55 carries the marker "B56" or sits inside a
//   "// B56:begin <item>" ... "// B56:end <item>" block, so nothing changes unmarked; pure deletions are refused, and every
//   B55 line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure gains no file (ADDED is empty);
// - the controller's v149 input contract is B55's: no input is added or changed, and dependencies.json still pins the
//   header and the entrypoint the tree has;
// - swap-spec writes exactly the seven accepted keys, in order, once each, inside its block, right after initial_orders;
//   the mode, the 3-day rollover and the digits as the integers the terminal returns, every double at full precision;
// - the items keep B55's build ID and marker (the B56 assembly replaces them and lists them in REMOVED).
// test_b55_no_drift.cjs now proves B55's own tree (as test_b54_no_drift.cjs proves B54's), so the chain
// B49a -> B50 -> B53 -> B54 -> B55 -> tree is checked end to end.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B56 change is marked, listed and reviewable. That swap-spec only
// adds run.csv keys (no trading path reads them) is visible in its block: seven FileWrite calls to the run file.
'use strict';
const path=require('node:path'),crypto=require('node:crypto'),fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B55_SOURCE='41396df479fd7fb1a9095d74a11735e48b8ee8b0';
// Each item PR adds the files it changes, so the review sees the list grow.
const CHANGED=['GOAT_SequenceExport.mqh'];   // swap-spec
const ADDED=[];
// Every B55 line a changed hunk removes, verbatim (trimmed), per file. swap-spec only adds lines.
const REMOVED={};
// The items keep B55's identity lines (the assembly replaces them and lists them in REMOVED): each appears exactly once.
const B55_IDENTITY_LINES=['#define   GOAT_BUILD_ID "V1.49-BETA17-55"','#define   GOAT_BUILD_MARKER "B55"'];
// swap-spec: the seven keys Claude-Mac accepted (6978371254), in order, with the expression each is written from.
const SWAP_SPEC=[
 ['symbol_swap_mode','SymbolInfoInteger(_Symbol,SYMBOL_SWAP_MODE)'],
 ['symbol_swap_long','DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_SWAP_LONG),-16)'],
 ['symbol_swap_short','DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_SWAP_SHORT),-16)'],
 ['symbol_swap_rollover3days','SymbolInfoInteger(_Symbol,SYMBOL_SWAP_ROLLOVER3DAYS)'],
 ['symbol_contract_size','DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),-16)'],
 ['symbol_digits','SymbolInfoInteger(_Symbol,SYMBOL_DIGITS)'],
 ['symbol_point','DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_POINT),-16)'],
];
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const bom=text=>text.replace(/^﻿/,'');
git(['merge-base','--is-ancestor',B55_SOURCE,'HEAD']);   // throws unless the working tree descends from B55
const b55=JSON.parse(bom(git(['show',B55_SOURCE+':candidate-builds/beta17-B55/identity.json']).toString('utf8')));
let checks=0;

// 1. The baseline really is B55: its commit's blobs (checked out as the tree would be) hash to B55's identity, which the
// tree keeps unchanged.
for(const [f,h] of Object.entries(b55.sources)) assert.equal(sha(checkedOut(f,git(['show',B55_SOURCE+':'+f]))),h,'B55 source '+B55_SOURCE.slice(0,8)+' is the identity of '+f);
assert.equal(b55.build_id+' '+b55.build_marker,'V1.49-BETA17-55 B55');
assert.deepEqual(JSON.parse(bom(read('candidate-builds/beta17-B55/identity.json').toString('utf8'))),b55,'B55\'s identity file is unchanged');
checks++;

// 2. The compile closure: B55's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b55Mql=Object.keys(b55.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b55Mql,...ADDED].sort(),'the compile closure is B55\'s plus ADDED');
checks++;

// 3. Outside CHANGED, every B55 source is byte-identical; every CHANGED file did change and keeps BOM + CRLF.
for(const [f,h] of Object.entries(b55.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B55: '+f);
for(const f of CHANGED){
 assert.notEqual(sha(read(f)),b55.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B56:begin (\S+)/),end=line.match(/\/\/ B56:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B56 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B56:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B56 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=bom(read(f).toString('utf8')).split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B55_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B55');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B55 line(s) is unmarked');
  for(const n of added){const text=lines[n-1];assert.ok(/B56/.test(text)||inBlock[n-1],f+':'+n+' changed since B55 without a B56 marker: '+text.trim());}
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B55 lines removed are exactly REMOVED');
}
for(const f of Object.keys(REMOVED)) assert.ok(CHANGED.includes(f),'REMOVED names only CHANGED files: '+f);
{const main=read('GOAT V1.49.mq5').toString('utf8').split('\r\n');
 for(const l of B55_IDENTITY_LINES) assert.equal(main.filter(x=>x===l).length,1,'the items keep B55\'s identity line, once: '+l);}
checks++;

// 5. swap-spec: exactly the seven keys, in order, once each, inside its block, right after initial_orders.
{const lines=bom(read('GOAT_SequenceExport.mqh').toString('utf8')).split('\r\n');
 const begin=lines.indexOf('   // B56:begin swap-spec'),end=lines.indexOf('   // B56:end swap-spec');
 assert.ok(begin>0&&end>begin,'the swap-spec block exists');
 assert.equal(lines[begin-1],'   GoatTraceWritten(FileWrite(g_trace_files[0],"initial_orders",OrdersTotal()));','swap-spec follows initial_orders');
 const writes=lines.slice(begin+1,end).filter(l=>!/^\s*\/\//.test(l));
 assert.deepEqual(writes,SWAP_SPEC.map(([key,expr])=>'   GoatTraceWritten(FileWrite(g_trace_files[0],"'+key+'",'+expr+'));'),'swap-spec writes the seven keys, in order, and nothing else');
 const text=lines.join('\n');
 for(const [key] of SWAP_SPEC) assert.equal(text.split('"'+key+'"').length-1,1,'the key is written once: '+key);
 checks++;}

// 6. The input contract is B55's: no input added or changed, and the pins still match the header and entrypoint.
const deps=JSON.parse(bom(read('controller/contracts/v149/dependencies.json').toString('utf8')));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
assert.deepEqual(deps,JSON.parse(bom(git(['show',B55_SOURCE+':controller/contracts/v149/dependencies.json']).toString('utf8'))),'dependencies.json is B55\'s');
assert.deepEqual(JSON.parse(bom(read('controller/contracts/v149/inputs.json').toString('utf8'))),
 JSON.parse(bom(git(['show',B55_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8'))),'inputs.json is B55\'s');
checks++;

console.log('b56_no_drift: '+checks+' checks passed (B55 '+B55_SOURCE.slice(0,8)+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; swap-spec keys: '+SWAP_SPEC.length+')');
