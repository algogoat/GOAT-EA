// B57 no-drift guard. B57 = B56 (the forward candidate V1.49-BETA17-56, claude-pc/b56-line 5a07056; its source hashes are
// committed in candidate-builds/beta17-B56/identity.json) plus reviewed, marked items, each in its own PR (Claude-Mac
// goatai#2943 7222542209: the line opens with GOAT-EA#361; the breakout start path, BRK_Start_Seq, follows on the same line).
// The first item is handle-reset (GOAT-EA#361): a closed global file handle is always reset, so OnTesterDeinit can no longer
// close the seed-farming XML through a stale FileTester_handle. Against B56:
// - every file of B56's compile closure outside CHANGED is byte-identical to B56;
// - in the CHANGED files, every line added or replaced since B56 carries the marker "B57" or sits inside a
//   "// B57:begin <item>" ... "// B57:end <item>" block, so nothing changes unmarked; pure deletions are refused, and every
//   B56 line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure gains no file (ADDED is empty);
// - the controller's v149 input contract is B56's: no input is added or changed, and dependencies.json pins the header and
//   the entrypoint the tree has (handle-reset moves the entrypoint's hash, so main_sha256 is re-pinned);
// - handle-reset: GoatFileCloseReset closes only a valid handle and always resets it, inside its block; every close of the
//   three globals that kept their number (FileTester_handle, FileCSV_handle, FileSET_handle) goes through it, or resets on
//   the same line (B49b's FileCSV_handle final row); controller/test_ea_file_handle_reset.py checks every global.
// test_b56_no_drift.cjs now proves B56's own tree (as test_b55_no_drift.cjs proves B55's), so the chain
// B49a -> B50 -> B53 -> B54 -> B55 -> B56 -> tree is checked end to end.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B57 change is marked, listed and reviewable. handle-reset touches
// no trading path: it changes how four functions close the tester fitness file, the equity CSV and the SET file.
'use strict';
const path=require('node:path'),crypto=require('node:crypto'),fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B56_SOURCE='5a07056fce93b00656d5a45d7fe36d543660032d';
// Each item PR adds the files it changes, so the review sees the list grow. handle-reset changes the entrypoint.
const CHANGED=['GOAT V1.49.mq5'];
const ADDED=[];
// Every B56 line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 // handle-reset: the seven closes that kept the handle's number (and OnTesterInit's unchecked write).
 'GOAT V1.49.mq5':[
  'if(FileCSV_handle!=INVALID_HANDLE) FileClose(FileCSV_handle);',
  'if(FileSET_handle!=INVALID_HANDLE) FileClose(FileSET_handle);',
  'FileWrite(FileTester_handle,0.02);',
  'FileClose(FileTester_handle);',
  'string stored=FileReadString(FileTester_handle); FileClose(FileTester_handle);',
  'if(FileTester_handle!=INVALID_HANDLE) {FileWrite(FileTester_handle,fitness); FileClose(FileTester_handle);}',
  'if(FileCSV_handle    != INVALID_HANDLE) {FileClose(FileCSV_handle);     Sleep(100);}',
  'if(FileTester_handle != INVALID_HANDLE) {FileClose(FileTester_handle);  Sleep(100);}',
 ],
};
// B56's identity lines stay until the B57 assembly replaces them (as test_b56_no_drift.cjs's IDENTITY_LINES for B56).
const B56_IDENTITY_LINES=['#define   GOAT_BUILD_ID "V1.49-BETA17-56"','#define   GOAT_BUILD_MARKER "B56"'];
const HANDLES=['FileTester_handle','FileCSV_handle','FileSET_handle'];
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const bom=text=>text.replace(/^﻿/,'');
git(['merge-base','--is-ancestor',B56_SOURCE,'HEAD']);   // throws unless the working tree descends from B56
const b56=JSON.parse(bom(git(['show',B56_SOURCE+':candidate-builds/beta17-B56/identity.json']).toString('utf8')));
let checks=0;

// 1. The baseline really is B56: its commit's blobs (checked out as the tree would be) hash to B56's identity, which the
// tree keeps unchanged.
for(const [f,h] of Object.entries(b56.sources)) assert.equal(sha(checkedOut(f,git(['show',B56_SOURCE+':'+f]))),h,'B56 source '+B56_SOURCE.slice(0,8)+' is the identity of '+f);
assert.equal(b56.build_id+' '+b56.build_marker,'V1.49-BETA17-56 B56');
assert.deepEqual(JSON.parse(bom(read('candidate-builds/beta17-B56/identity.json').toString('utf8'))),b56,'B56\'s identity file is unchanged');
checks++;

// 2. The compile closure: B56's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b56Mql=Object.keys(b56.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b56Mql,...ADDED].sort(),'the compile closure is B56\'s plus ADDED');
checks++;

// 3. Outside CHANGED, every B56 source is byte-identical; every CHANGED file did change and keeps BOM + CRLF.
for(const [f,h] of Object.entries(b56.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B56: '+f);
for(const f of CHANGED){
 assert.notEqual(sha(read(f)),b56.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B57:begin (\S+)/),end=line.match(/\/\/ B57:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B57 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B57:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B57 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=bom(read(f).toString('utf8')).split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B56_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B56');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B56 line(s) is unmarked');
  for(const n of added){const text=lines[n-1];assert.ok(/B57/.test(text)||inBlock[n-1],f+':'+n+' changed since B56 without a B57 marker: '+text.trim());}
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B56 lines removed are exactly REMOVED');
}
for(const f of Object.keys(REMOVED)) assert.ok(CHANGED.includes(f),'REMOVED names only CHANGED files: '+f);
{const main=bom(read('GOAT V1.49.mq5').toString('utf8')).split('\r\n');
 for(const l of B56_IDENTITY_LINES) assert.equal(main.filter(x=>x===l).length,1,'B56\'s identity line, once, until the B57 assembly: '+l);}
checks++;

// 5. handle-reset: the helper, inside its block, closes only a valid handle and always resets it; every close of the three
// globals goes through it or resets on the same line.
{const lines=bom(read('GOAT V1.49.mq5').toString('utf8')).split('\r\n');
 const begin=lines.indexOf('// B57:begin handle-reset'),end=lines.indexOf('// B57:end handle-reset');
 assert.ok(begin>0&&end>begin,'the handle-reset block exists');
 const block=lines.slice(begin,end+1);
 const def=block.indexOf('void GoatFileCloseReset(int &handle)');
 assert.ok(def>0,'GoatFileCloseReset(int &handle) is defined inside the block');
 assert.deepEqual(block.slice(def+1,def+5),['  {','   if(handle!=INVALID_HANDLE) FileClose(handle);','   handle=INVALID_HANDLE;','  }'],'the helper closes only a valid handle and always resets it');
 assert.equal(lines.filter(l=>/^\s*void\s+GoatFileCloseReset\s*\(/.test(l)).length,1,'the helper is defined once');
 for(const [i,l] of lines.entries()){
  const code=l.replace(/\/\/.*$/,'');
  for(const h of HANDLES) for(const m of code.matchAll(new RegExp('(?<![\\w:])FileClose\\(\\s*'+h+'\\s*\\)','g')))
   assert.ok(new RegExp('\\b'+h+'\\s*=\\s*INVALID_HANDLE').test(code.slice(m.index)),'GOAT V1.49.mq5:'+(i+1)+' closes '+h+' without resetting it: '+l.trim());
 }
 const calls=lines.filter(l=>/GoatFileCloseReset\(\s*(FileTester_handle|FileCSV_handle|FileSET_handle)\s*\)/.test(l.replace(/\/\/.*$/,''))).length;
 assert.equal(calls,7,'handle-reset replaces the seven closes (OnDeinit 2, OnTesterInit 1, OnTester 2, OnTesterDeinit 2)');
 checks++;}

// 6. The input contract is B56's: no input added or changed, and the pins match the header and entrypoint. handle-reset moves
// the entrypoint's hash, so main_sha256 is re-pinned; every other field of dependencies.json is B56's.
const deps=JSON.parse(bom(read('controller/contracts/v149/dependencies.json').toString('utf8')));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
assert.deepEqual({...deps,main_sha256:null},{...JSON.parse(bom(git(['show',B56_SOURCE+':controller/contracts/v149/dependencies.json']).toString('utf8'))),main_sha256:null},
 'dependencies.json is B56\'s but for the entrypoint pin');
assert.deepEqual(JSON.parse(bom(read('controller/contracts/v149/inputs.json').toString('utf8'))),
 JSON.parse(bom(git(['show',B56_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8'))),'inputs.json is B56\'s');
checks++;

console.log('b57_no_drift: '+checks+' checks passed (B56 '+B56_SOURCE.slice(0,8)+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; handle-reset: 7 closes)');
