// B54 gate 0 (docs/b54/BREAKOUT_ENTRIES_SPEC.md section 6.2), the EA half: effective-input equality on the pool.
// The pool (ruling 2) is the 61 qualified SETs (59 sequence, 2 single), committed byte-identical under
// scripts/fixtures/b54-pool (-text in .gitattributes) with manifest.json, one sha256 per file, as test_hunt_sets_init.cjs
// keeps the D1 hunt SETs. B53 (216e1622, V1.49-BETA17-53) and this tree each run through scripts/b50_tick_harness.cjs (the
// entrypoint with the input header inlined, OnInit's real slices, WriteSet as written). Per file:
// 1. the SET names none of the 14 B54 inputs, and every line of it is an input of both sources;
// 5. OnInit at the SET's values and, for each optimized axis (Y), at the range's start and at its stop (every other input at
//    the SET's value): the result is the same on both; where it inits, B53's input globals are equal and the 14 new inputs
//    hold their declared defaults (the spec's tables);
// 6. WriteSet writes the same bytes from the file's values on B54 as on B53.
// Before the files: this tree declares B53's inputs in B53's order, then exactly the 14, in the spec's order (the EA side
// of item 0). The A0 WriteSet lines (spec 6.1): each B54 input that differs from its default adds exactly one line, in the
// form MT5 reads back, after B53's lines, in input order.
// Load-bearing: header mutants (an existing default changed, two existing inputs reordered, a B54 WriteSet line written
// unconditionally, a B54 default changed) must each fail the same checks on two probe files.
// Items 0 and 2-4 (the controller's contracts, pinned inputs, explicit optimization lines, verify_explicit_inputs,
// validate_strategy and the init-rule mirror) are controller/test_b54_gate0.py.
// What it does not prove: compile cleanliness (MetaEditor), MT5's own SET reader, or trades (the native Banker parity on all
// 61, ruling 3, and test_b54_parity.cjs, spec 6.3, do).
// B55 (PR A0, docs/b55/BREAKOUT_SEQUENCE_SPEC.md section 6.2): B54 is merged (a8c6766, GOAT-EA#306) and B55 appends its own
// input after the 14, so "this tree" above is now B54's own commit (B54_TREE), read from history as B53 is, header mutants
// included. scripts/test_b55_gate0.cjs is the gate from B54 to the working tree: the chain B53 -> B54 -> tree, end to end.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B53='216e16225441cfc1bfe0546c1c70adaf327405cf';
const B54_TREE='a8c6766243ff577bdcfc90495a6de33ce0797c88';   // B55 (A0): the candidate, B54's own commit
const DIR=path.join(__dirname,'fixtures','b54-pool');
// The spec's tables (3.1, 4.1): each new input at its declared default, as the harness holds it (enums by value).
const NEW={BRK_Mode:0,BRK_TF_:60,BRK_Bars:20,BRK_Buffer_ATR:0,BRK_Once_Per_Level:true,ORB_Mode:0,ORB_Clock:0,ORB_TF_:5,
 ORB_Start_Minute:570,ORB_Range_Minutes:30,ORB_Entry_Minutes:0,ORB_Buffer_ATR:0,ORB_Min_Range_ATR:0,ORB_Max_Range_ATR:0};
const NAMES=Object.keys(NEW);
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
// A SET as MT5 writes it (UTF-16LE with a BOM): name=value, or name=value||start||step||stop||Y/N.
function parse(buf,name){
 assert.deepEqual([...buf.subarray(0,2)],[0xFF,0xFE],name+': UTF-16LE with a BOM, as MT5 writes it');
 const rows=[];
 for(const line of buf.subarray(2).toString('utf16le').split(/\r?\n/)){
  if(!line||line.startsWith(';'))continue;
  const e=line.indexOf('=');if(e<1)continue;
  const f=line.slice(e+1).split('||');
  rows.push({name:line.slice(0,e),cur:f[0],start:f[1],stop:f[3],opt:f[4]==='Y'});
 }
 return rows;
}
const value=v=>v==='true'?true:v==='false'?false:(v!==''&&!isNaN(Number(v))?Number(v):v);
// A datetime input (Download_StartDate) as MQL holds it: StringToTime of the SET's yyyy.mm.dd[ hh:mi[:ss]] text, in seconds.
const DATETIME=new Set(H.compile(H.loadSources(B53)).globals.filter(g=>g.input&&g.type==='datetime').map(g=>g.name));
function typed(name,v){
 const m=DATETIME.has(name)&&String(v).match(/^(\d{4})\.(\d{2})\.(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/);
 return m?Date.UTC(+m[1],m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0))/1000:value(v);
}
const inputsOf=files=>H.compile(files).globals.filter(g=>g.input).map(g=>g.name);
function init(files,inputs){
 try{return {result:'ok',W:H.build({files},{tester:true,inputs,indicator:()=>undefined})};}
 catch(e){return {result:e.initCode!==undefined?'OnInit refused: code '+e.initCode:'error: '+String(e.message).split('\n')[0]};}
}
function writeSet(W){
 const lines=[];W.ctx.FileWrite=(h,...a)=>{lines.push(a.map(String).join(''));return 1;};W.ctx.FileClose=()=>{};
 W.ctx.FileSET_handle=7;W.ctx.WriteSet('; GOAT B54 gate 0');return lines;
}
// A world at the SET's values even when OnInit refuses them (the same on both sources, item 5): build at the defaults, then
// set the values, as test_b51_parity's WriteSet golden does.
function atValues(files,inputs,probe){
 if(probe.W)return probe.W;
 const W=H.build({files},{tester:true,inputs:{},indicator:()=>undefined});
 for(const [k,v] of Object.entries(inputs))W.setInput(k,v);W.ctx.Strat=W.ctx.EA_Desc;return W;
}

const manifest=JSON.parse(fs.readFileSync(path.join(DIR,'manifest.json'),'utf8'));
const POOL=manifest.files.map(row=>row.file);
assert.equal(POOL.length,61,'the pool is the 61 (ruling 2)');
assert.equal(manifest.inventory.sha256,'f4337e1bd296f7a4de3c5e53d6f7acab9d7454d8b6172739eb5729183984936c','the spec\'s inventory');
assert.deepEqual(fs.readdirSync(DIR).filter(f=>f!=='manifest.json').sort(),[...POOL].sort(),'the fixtures are exactly the manifest\'s');
const raw={};
for(const row of manifest.files){
 raw[row.file]=fs.readFileSync(path.join(DIR,row.file));
 assert.equal(sha(raw[row.file]),row.sha256,row.file+': byte-identical to the pool SET');
}
const SOURCES53=H.loadSources(B53);
const INPUTS53=inputsOf(SOURCES53);

// The gate for one tree source (files54) over the given pool files: a list of problems, empty when it passes.
function gate(files54,names,stats){
 const problems=[];
 const inputs54=inputsOf(files54),set53=new Set(INPUTS53),set54=new Set(inputs54);
 // The header's inputs come first and the entrypoint's own (Studio_*, BlindExport, ...) after them, so the 14 sit right
 // after B53's last header input (Single_Partial_BE) and before the entrypoint's.
 const at=inputs54.indexOf(NAMES[0]);
 if(at<1||inputs54[at-1]!=='Single_Partial_BE'||JSON.stringify(inputs54.slice(at,at+NAMES.length))!==JSON.stringify(NAMES)
  ||JSON.stringify([...inputs54.slice(0,at),...inputs54.slice(at+NAMES.length)])!==JSON.stringify(INPUTS53))
  problems.push('inputs are not B53\'s in order plus exactly the 14 after its header\'s last: '+JSON.stringify(inputs54.slice(Math.max(at,1)-2,at+16)));
 for(const name of names){
  const rows=parse(raw[name],name);
  for(const r of rows){                                                                        // 1
   if(NAMES.includes(r.name))problems.push(name+': names '+r.name);
   if(!set53.has(r.name)||!set54.has(r.name))problems.push(name+': '+r.name+' is not an input of both sources');
  }
  const base=Object.fromEntries(rows.map(r=>[r.name,typed(r.name,r.cur)]));
  const probes=[['current values',base]];
  for(const r of rows.filter(r=>r.opt))for(const [end,v] of [['start',r.start],['stop',r.stop]])
   probes.push([r.name+'='+v+' ('+end+')',{...base,[r.name]:typed(r.name,v)}]);
  let first=null;
  for(const [what,inputs] of probes){                                                          // 5
   const a=init(SOURCES53,inputs),b=init(files54,inputs);
   if(first===null)first=[a,b,inputs];   // the SET's own values: WriteSet's input (item 6)
   if(stats){stats.inits+=2;stats[a.result==='ok'?'ok':'refused']++;}
   if(a.result!==b.result){problems.push(name+' at '+what+': B53 '+a.result+', B54 '+b.result);continue;}
   if(a.result==='ok'){
    for(const n of INPUTS53)if(!Object.is(a.W.ctx[n],b.W.ctx[n])&&JSON.stringify(a.W.ctx[n])!==JSON.stringify(b.W.ctx[n]))
     problems.push(name+' at '+what+': input '+n+' B53 '+JSON.stringify(a.W.ctx[n])+', B54 '+JSON.stringify(b.W.ctx[n]));
    for(const n of NAMES)if(b.W.ctx[n]!==NEW[n])problems.push(name+' at '+what+': '+n+'='+JSON.stringify(b.W.ctx[n])+', not its default '+NEW[n]);
   }
  }
  const [a,b,inputs]=first;                                                                    // 6
  const w53=writeSet(atValues(SOURCES53,inputs,a)),w54=writeSet(atValues(files54,inputs,b));
  const bytes=lines=>Buffer.from(lines.map(l=>l+'\r\n').join(''),'utf16le');
  if(sha(bytes(w54))!==sha(bytes(w53))){
   const at=w54.findIndex((l,i)=>l!==w53[i]);
   problems.push(name+': WriteSet differs at line '+at+': B53 '+JSON.stringify(w53[at])+', B54 '+JSON.stringify(w54[at]));
  }
  if(stats){stats.writeSetLines+=w53.length;if(w53.length<100)problems.push(name+': WriteSet wrote only '+w53.length+' lines');}
 }
 return problems;
}

let passed=0;
const stats={inits:0,ok:0,refused:0,writeSetLines:0};
const TREE=H.loadSources(B54_TREE);
{const problems=gate(TREE,POOL,stats);
 assert.deepEqual(problems,[],'gate 0 (items 1, 5, 6) on every pool SET');
 assert.ok(stats.ok>0,'the pool inits (the comparison is not vacuous)');passed++;}

// The A0 WriteSet lines (spec 6.1): a default SET is B53's; each B54 input that differs from its default adds one line.
const CHANGED={BRK_Mode:[1,'BRK_Mode=1'],BRK_TF_:[15,'BRK_TF_=15'],BRK_Bars:[55,'BRK_Bars=55'],BRK_Buffer_ATR:[0.25,'BRK_Buffer_ATR=0.25'],
 BRK_Once_Per_Level:[false,'BRK_Once_Per_Level=false'],ORB_Mode:[1,'ORB_Mode=1'],ORB_Clock:[1,'ORB_Clock=1'],ORB_TF_:[15,'ORB_TF_=15'],
 ORB_Start_Minute:[480,'ORB_Start_Minute=480'],ORB_Range_Minutes:[60,'ORB_Range_Minutes=60'],ORB_Entry_Minutes:[120,'ORB_Entry_Minutes=120'],
 ORB_Buffer_ATR:[0.1,'ORB_Buffer_ATR=0.1'],ORB_Min_Range_ATR:[0.5,'ORB_Min_Range_ATR=0.5'],ORB_Max_Range_ATR:[3.5,'ORB_Max_Range_ATR=3.5']};
assert.deepEqual(Object.keys(CHANGED),NAMES);
{const quiet={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled'};
 const at=(files,inputs={})=>{const W=H.build({files},{inputs:quiet});for(const [k,v] of Object.entries(inputs))W.setInput(k,v);return writeSet(W);};
 const base=at(SOURCES53),tree=at(TREE);
 assert.ok(base.length>120,'WriteSet wrote the SET ('+base.length+' lines)');
 assert.deepEqual(tree,base,'a default SET is B53\'s');
 for(const [name,[v,line]] of Object.entries(CHANGED)){
  const out=at(TREE,{[name]:v});
  assert.deepEqual(out.filter(l=>!base.includes(l)),[line],name+': one line, only when it differs from its default');
  assert.equal(out.length,base.length+1,name);
 }
 const all=at(TREE,Object.fromEntries(Object.entries(CHANGED).map(([k,[v]])=>[k,v])));
 assert.deepEqual(all.slice(base.length),Object.values(CHANGED).map(([,l])=>l),'in input order, after B53\'s lines');
 passed++;}

// The gate is load-bearing: each header mutant fails it on the probe files (a SET from before B50, which omits Single_SL_ATR,
// and a single, which carries B50-beta's inputs).
const killed=[];
{const header=H.readSource(B54_TREE,H.HEADER);
 const swap=(text,from,to)=>{assert.equal(text.split(from).length,2,'the mutant site is unique: '+from);return text.replace(from,to);};
 const decl=name=>{const m=header.match(new RegExp('^[^\\n]*\\b'+name+'\\s+=[^\\n]*$','m'));assert.ok(m,name);return m[0];};
 const probes=[POOL.find(n=>!raw[n].subarray(2).toString('utf16le').includes('\nSingle_SL_ATR=')),manifest.files.find(r=>r.engine==='single').file];
 assert.ok(probes.every(Boolean),'probe files');
 const mutants=[
  ['an existing default changed (Single_SL_ATR 0.0 -> 0.5)',swap(header,decl('Single_SL_ATR'),decl('Single_SL_ATR').replace('0.0;','0.5;'))],
  ['two existing inputs reordered (Single_BE_ATR, Single_Trail_Start_ATR)',swap(header,decl('Single_BE_ATR')+'\n'+decl('Single_Trail_Start_ATR'),decl('Single_Trail_Start_ATR')+'\n'+decl('Single_BE_ATR'))],
  ['a B54 WriteSet line written at its default (BRK_Bars compared with 21)',swap(header,'if(BRK_Bars!=20)','if(BRK_Bars!=21)')],
  ['a B54 default changed (BRK_Bars 20 -> 21)',swap(header,decl('BRK_Bars'),decl('BRK_Bars').replace('20;','21;'))],
 ];
 for(const [what,text] of mutants){
  const problems=gate(H.loadSources(B54_TREE,{[H.HEADER]:text}),probes);
  assert.ok(problems.length>0,'mutant caught: '+what);
  killed.push(what+' ('+problems.length+': '+problems[0].slice(0,90)+')');
 }
 passed++;}

console.log(JSON.stringify({passed,test:'b54_gate0',baseline:B53,candidate:B54_TREE,pool:POOL.length,inits:stats.inits,initOk:stats.ok,initRefused:stats.refused,
 writeSetLines:stats.writeSetLines,mutantsKilled:killed}));
