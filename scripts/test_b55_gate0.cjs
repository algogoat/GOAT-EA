// B55 gate 0 (docs/b55/BREAKOUT_SEQUENCE_SPEC.md section 6.2), the EA half: effective-input equality with B54.
// The files (question 7; Claude-Mac goatai#2750 6789761790: every file in the pool at A0's merge, not only the 61):
// - every pool folder under scripts/fixtures (a folder named *-pool with a manifest.json, one sha256 per file). Today that is
//   b54-pool, the 61 qualified SETs (59 sequence, 2 single). A SET admitted later joins by landing in such a folder with its
//   manifest row; this file and controller/test_b55_gate0.py then read it with no code change;
// - B54's own breakout SETs, a mode on under Engine_Single: scripts/fixtures/b54-axes (18 synthetic optimisation SETs, each
//   BRK and ORB axis at Y). "Flags off" means BRK_Start_Seq=false, not BRK_Mode off: B54's breakout behaviour is in the claim;
// - the 11 preregistered D1 hunt SETs (scripts/fixtures/hunt-d1).
// B54 (a8c6766, V1.49-BETA17-54) and this tree each run through scripts/b50_tick_harness.cjs (the entrypoint with the input
// header inlined, OnInit's real slices, WriteSet as written). Per file:
// 1. the SET does not name BRK_Start_Seq, and every line of it is an input of both sources;
// 5. OnInit at the SET's values and, for each optimized axis (Y), at the range's start and at its stop (every other input at
//    the SET's value): the result is the same on both, an init or the same code and alert; where it inits, B54's input
//    globals are equal and BRK_Start_Seq holds its declared default (false);
// 6. WriteSet writes the same bytes from the file's values on this tree as on B54.
// Before the files: this tree declares B54's inputs in B54's order, then exactly BRK_Start_Seq (the EA side of item 0).
// After them: B54's refusal stands (a breakout on the grid engine with the switch off gives line 5128's code and alert on
// both sources), and the A0 WriteSet line (spec 3.1): the switch on adds exactly one line, in the form MT5 reads back, after
// B54's lines; off, a SET is B54's.
// Load-bearing: mutants (an existing default changed, two existing inputs reordered, the B55 WriteSet line written when
// off, the B55 default changed, line 5128 dropped, a b55-init rule that fires with the switch off) must each fail the same
// checks on three probe files.
// Items 0 and 2-4 (the controller's contracts, pinned inputs, explicit optimization lines, verify_explicit_inputs,
// validate_strategy and the init-rule mirror) are controller/test_b55_gate0.py.
// What it does not prove: compile cleanliness (MetaEditor), MT5's own SET reader, or trades (the native Banker parity on
// every pool file and test_b55_parity.cjs, spec 6.3, do).
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B54='a8c6766243ff577bdcfc90495a6de33ce0797c88';
const FIXTURES=path.join(__dirname,'fixtures');
const OTHER_FOLDERS=['b54-axes','hunt-d1'];   // B54's own breakout SETs (a mode on under Engine_Single); the D1 hunt SETs
// The spec's table (3.1): the new input at its declared default, as the harness holds it.
const NEW={BRK_Start_Seq:false};
const NAMES=Object.keys(NEW);
const LINE_5128='Initialization Failed: BRK_Mode needs the single-trade engine (Engine_Mode=Engine_Single).';
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
// A SET as MT5 writes it (UTF-16LE with a BOM): name=value, or name=value||start||step||stop||Y/N.
function parse(buf,name){
 assert.deepEqual([...buf.subarray(0,2)],[0xFF,0xFE],name+': UTF-16LE with a BOM, as MT5 writes it');
 const rows=[];
 for(const line of buf.subarray(2).toString('utf16le').split(/\r?\n/)){
  if(!line||line.startsWith(';'))continue;
  const e=line.indexOf('=');if(e<1)continue;
  const f=line.slice(e+1).split('||');
  rows.push({name:line.slice(0,e),cur:f[0],start:f[1],stop:f[3],opt:f.length===5&&f[4]==='Y'});
 }
 return rows;
}
const value=v=>v==='true'?true:v==='false'?false:(v!==''&&!isNaN(Number(v))?Number(v):v);
// A datetime input (Download_StartDate) as MQL holds it: StringToTime of the SET's yyyy.mm.dd[ hh:mi[:ss]] text, in seconds.
const DATETIME=new Set(H.compile(H.loadSources(B54)).globals.filter(g=>g.input&&g.type==='datetime').map(g=>g.name));
function typed(name,v){
 const m=DATETIME.has(name)&&String(v).match(/^(\d{4})\.(\d{2})\.(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/);
 return m?Date.UTC(+m[1],m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0))/1000:value(v);
}
const inputsOf=files=>H.compile(files).globals.filter(g=>g.input).map(g=>g.name);
// OnInit once: ok and the world, or the INIT code and the last alert (the harness world shares this alerts array).
function init(files,inputs){
 const alerts=[];
 try{return {result:'ok',W:H.build({files},{tester:true,inputs,indicator:()=>undefined,world:{alerts}})};}
 catch(e){return {result:e.initCode!==undefined?'OnInit refused: code '+e.initCode+' "'+alerts.at(-1)+'"':'error: '+String(e.message).split('\n')[0]};}
}
function writeSet(W){
 const lines=[];W.ctx.FileWrite=(h,...a)=>{lines.push(a.map(String).join(''));return 1;};W.ctx.FileClose=()=>{};
 W.ctx.FileSET_handle=7;W.ctx.WriteSet('; GOAT B55 gate 0');return lines;
}
// A world at the SET's values even when OnInit refuses them (the same on both sources, item 5; a b54-axes SET whose own
// values are outside a bound): build on inputs that init (QUIET), then set the SET's values, which name QUIET's four too,
// as test_b51_parity's WriteSet golden does.
const QUIET={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled'};
function atValues(files,inputs,probe){
 if(probe.W)return probe.W;
 for(const k of Object.keys(QUIET))assert.ok(k in inputs,'the SET names '+k);
 let W;
 try{W=H.build({files},{tester:true,inputs:QUIET,indicator:()=>undefined});}
 catch(e){if(e.initCode===undefined)throw e;return null;}   // a source whose own defaults are refused (a mutant): reported by gate()
 for(const [k,v] of Object.entries(inputs))W.setInput(k,v);W.ctx.Strat=W.ctx.EA_Desc;return W;
}

// The files: every pool folder (by its manifest), then the other folders' SETs.
const raw={},POOLS={};
for(const folder of fs.readdirSync(FIXTURES).filter(d=>/-pool$/.test(d)&&fs.existsSync(path.join(FIXTURES,d,'manifest.json'))).sort()){
 const manifest=JSON.parse(fs.readFileSync(path.join(FIXTURES,folder,'manifest.json'),'utf8'));
 POOLS[folder]=manifest.files;
 assert.deepEqual(fs.readdirSync(path.join(FIXTURES,folder)).filter(f=>f!=='manifest.json').sort(),manifest.files.map(r=>r.file).sort(),folder+': the fixtures are exactly the manifest\'s');
 for(const row of manifest.files){
  raw[folder+'/'+row.file]=fs.readFileSync(path.join(FIXTURES,folder,row.file));
  assert.equal(sha(raw[folder+'/'+row.file]),row.sha256,folder+'/'+row.file+': byte-identical to the pool SET');
 }
}
assert.equal((POOLS['b54-pool']||[]).length,61,'the 61 qualified SETs are in the pool');
const POOL=Object.keys(raw);
for(const folder of OTHER_FOLDERS) for(const f of fs.readdirSync(path.join(FIXTURES,folder)).filter(f=>f.endsWith('.set')).sort()) raw[folder+'/'+f]=fs.readFileSync(path.join(FIXTURES,folder,f));
const FILES=Object.keys(raw);
assert.equal(FILES.length,POOL.length+18+11,'every pool file, the 18 b54-axes SETs, the 11 D1 hunt SETs');
const SOURCES54=H.loadSources(B54);
const INPUTS54=inputsOf(SOURCES54);
const GRID_BREAKOUT=(()=>{const rows=parse(raw['b54-axes/brk-nbar-ends.set'],'brk-nbar-ends.set');return {...Object.fromEntries(rows.map(r=>[r.name,typed(r.name,r.cur)])),Engine_Mode:0};})();

// The gate for one tree source (files55) over the given files: a list of problems, empty when it passes.
function gate(files55,names,stats){
 const problems=[];
 const inputs55=inputsOf(files55),set54=new Set(INPUTS54),set55=new Set(inputs55);
 // The header's inputs come first and the entrypoint's own (Studio_*, BlindExport, ...) after them, so the switch sits right
 // after B54's last header input (ORB_Max_Range_ATR) and before the entrypoint's.
 const at=inputs55.indexOf(NAMES[0]);
 if(at<1||inputs55[at-1]!=='ORB_Max_Range_ATR'||JSON.stringify(inputs55.slice(at,at+NAMES.length))!==JSON.stringify(NAMES)
  ||JSON.stringify([...inputs55.slice(0,at),...inputs55.slice(at+NAMES.length)])!==JSON.stringify(INPUTS54))
  problems.push('inputs are not B54\'s in order plus exactly BRK_Start_Seq after its header\'s last: '+JSON.stringify(inputs55.slice(Math.max(at,2)-2,at+3)));
 for(const name of names){
  const rows=parse(raw[name],name);
  for(const r of rows){                                                                        // 1
   if(NAMES.includes(r.name))problems.push(name+': names '+r.name);
   if(!set54.has(r.name)||!set55.has(r.name))problems.push(name+': '+r.name+' is not an input of both sources');
  }
  const base=Object.fromEntries(rows.map(r=>[r.name,typed(r.name,r.cur)]));
  const probes=[['current values',base]];
  for(const r of rows.filter(r=>r.opt))for(const [end,v] of [['start',r.start],['stop',r.stop]])
   probes.push([r.name+'='+v+' ('+end+')',{...base,[r.name]:typed(r.name,v)}]);
  let first=null;
  for(const [what,inputs] of probes){                                                          // 5
   const a=init(SOURCES54,inputs),b=init(files55,inputs);
   if(first===null)first=[a,b,inputs];   // the SET's own values: WriteSet's input (item 6)
   if(stats){stats.inits+=2;stats[a.result==='ok'?'ok':'refused']++;}
   if(a.result!==b.result){problems.push(name+' at '+what+': B54 '+a.result+', B55 '+b.result);continue;}
   if(a.result==='ok'){
    for(const n of INPUTS54)if(!Object.is(a.W.ctx[n],b.W.ctx[n])&&JSON.stringify(a.W.ctx[n])!==JSON.stringify(b.W.ctx[n]))
     problems.push(name+' at '+what+': input '+n+' B54 '+JSON.stringify(a.W.ctx[n])+', B55 '+JSON.stringify(b.W.ctx[n]));
    for(const n of NAMES)if(b.W.ctx[n]!==NEW[n])problems.push(name+' at '+what+': '+n+'='+JSON.stringify(b.W.ctx[n])+', not its default '+NEW[n]);
   }
  }
  const [a,b,inputs]=first;                                                                    // 6
  const W54=atValues(SOURCES54,inputs,a),W55=atValues(files55,inputs,b);
  if(!W54||!W55){problems.push(name+': OnInit refuses the declared defaults ('+(W54?'':'B54 ')+(W55?'':'B55')+'), so WriteSet cannot be compared');continue;}
  const w54=writeSet(W54),w55=writeSet(W55);
  const bytes=lines=>Buffer.from(lines.map(l=>l+'\r\n').join(''),'utf16le');
  if(sha(bytes(w55))!==sha(bytes(w54))){
   const at=w55.findIndex((l,i)=>l!==w54[i]);
   problems.push(name+': WriteSet differs at line '+at+': B54 '+JSON.stringify(w54[at])+', B55 '+JSON.stringify(w55[at]));
  }
  if(stats){stats.writeSetLines+=w54.length;if(w54.length<100)problems.push(name+': WriteSet wrote only '+w54.length+' lines');}
 }
 // B54's refusal stands: a breakout on the grid engine with the switch off (b54-axes/brk-nbar-ends.set with Engine_Mode=0).
 {const a=init(SOURCES54,GRID_BREAKOUT),b=init(files55,GRID_BREAKOUT),want='OnInit refused: code '+H.API_CONSTANTS.INIT_PARAMETERS_INCORRECT+' "'+LINE_5128+'"';
  if(a.result!==want||b.result!==want)problems.push('a breakout on the grid engine, the switch off: B54 '+a.result+', B55 '+b.result+', wanted line 5128\'s refusal on both');}
 return problems;
}

let passed=0;
const stats={inits:0,ok:0,refused:0,writeSetLines:0};
const TREE=H.loadSources();
{const problems=gate(TREE,FILES,stats);
 assert.deepEqual(problems,[],'gate 0 (items 1, 5, 6) on every file');
 assert.ok(stats.ok>=POOL.length,'every pool SET inits (the comparison is not vacuous)');
 assert.ok(stats.refused>0,'and refusals are compared too (the b54-axes probes outside their bounds)');passed++;}

// The A0 WriteSet line (spec 3.1): a SET with the switch off is B54's; the switch on adds one line, after B54's.
{const at=(files,inputs={})=>{const W=H.build({files},{inputs:QUIET});for(const [k,v] of Object.entries(inputs))W.setInput(k,v);return writeSet(W);};
 const base=at(SOURCES54),tree=at(TREE);
 assert.ok(base.length>120,'WriteSet wrote the SET ('+base.length+' lines)');
 assert.deepEqual(tree,base,'a default SET is B54\'s');
 assert.deepEqual(at(TREE,{BRK_Start_Seq:false,BRK_Mode:1}),at(SOURCES54,{BRK_Mode:1}),'a breakout SET with the switch off is B54\'s');
 const on=at(TREE,{BRK_Start_Seq:true});
 assert.deepEqual(on.slice(0,base.length),base,'B54\'s lines first');
 assert.deepEqual(on.slice(base.length),['BRK_Start_Seq=true'],'then one line, only when the switch is on');
 const both=at(TREE,{BRK_Mode:1,ORB_Max_Range_ATR:3.5,BRK_Start_Seq:true});
 assert.deepEqual(both.slice(-3),['BRK_Mode=1','ORB_Max_Range_ATR=3.5','BRK_Start_Seq=true'],'in input order, after B54\'s lines');
 passed++;}

// The gate is load-bearing: each mutant fails it on the probe files (a pool sequence, which omits every appended input of
// B50 and later; a pool single; and a B54 breakout single with its axes at Y).
const killed=[];
{const header=H.readSource(undefined,H.HEADER),main=H.readSource(undefined,H.MAIN);
 const swap=(text,from,to)=>{assert.equal(text.split(from).length,2,'the mutant site is unique: '+from);return text.replace(from,to);};
 const decl=name=>{const m=header.match(new RegExp('^[^\\n]*\\b'+name+'\\s+=[^\\n]*$','m'));assert.ok(m,name);return m[0];};
 const probes=[POOL.find(n=>!raw[n].subarray(2).toString('utf16le').includes('\nSingle_SL_ATR=')),'b54-pool/'+POOLS['b54-pool'].find(r=>r.engine==='single').file,'b54-axes/brk-nbar-ends.set'];
 assert.ok(probes.every(n=>raw[n]),'probe files');
 const mutants=[
  ['an existing default changed (BRK_Bars 20 -> 21)',{[H.HEADER]:swap(header,decl('BRK_Bars'),decl('BRK_Bars').replace('20;','21;'))}],
  ['two existing inputs reordered (ORB_Min_Range_ATR, ORB_Max_Range_ATR)',{[H.HEADER]:swap(header,decl('ORB_Min_Range_ATR')+'\n'+decl('ORB_Max_Range_ATR'),decl('ORB_Max_Range_ATR')+'\n'+decl('ORB_Min_Range_ATR'))}],
  ['the B55 WriteSet line written when the switch is off',{[H.HEADER]:swap(header,'if(BRK_Start_Seq)  ','if(!BRK_Start_Seq) ')}],
  ['the B55 default changed (BRK_Start_Seq false -> true)',{[H.HEADER]:swap(header,decl('BRK_Start_Seq'),decl('BRK_Start_Seq').replace('false;','true;'))}],
  ['line 5128 dropped',{[H.MAIN]:swap(main,'if(BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq)','if(false && BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq)')}],
  ['a b55-init rule that fires with the switch off (the delay rule)',{[H.MAIN]:swap(main,'if(BRK_Start_Seq && (Delay_Trade!=0 || Delay_Trade_Live!=0))','if(Delay_Trade!=0 || Delay_Trade_Live!=0)')}],
 ];
 for(const [what,overrides] of mutants){
  const problems=gate(H.loadSources(undefined,overrides),probes);
  assert.ok(problems.length>0,'mutant caught: '+what);
  killed.push(what+' ('+problems.length+': '+problems[0].slice(0,110)+')');
 }
 passed++;}

console.log(JSON.stringify({passed,test:'b55_gate0',baseline:B54,pools:Object.fromEntries(Object.entries(POOLS).map(([k,v])=>[k,v.length])),files:FILES.length,
 inits:stats.inits,initOk:stats.ok,initRefused:stats.refused,writeSetLines:stats.writeSetLines,mutantsKilled:killed}));
