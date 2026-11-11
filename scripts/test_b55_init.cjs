// B55 PR A0 (docs/b55/BREAKOUT_SEQUENCE_SPEC.md 3.7; Claude-Mac goatai#2750 6789761790): the EA half of the b55-init block
// and of the narrowed line 5128, through scripts/b50_tick_harness.cjs (OnInit's real slices, the blocks included as written).
// 1. The synthetic axis SETs (scripts/fixtures/b55-axes, never pool files): at each probe (the SET's values, then each Y
//    axis at its start and at its stop, the others at their values) OnInit reports exactly the rule axes.json names: the
//    same INIT code and alert as that rule of the controller's EA_INIT_RULES. controller/test_b55_init.py gives the same
//    files to validate_strategy and checks the same table, so the EA and its mirror agree on every probe.
// 2. Spec 3.7's table on committed files: B54's synthetic single (b54-axes/brk-nbar-ends.set) and a pool sequence
//    (b54-pool/01-EURCAD-sequence.set), each as committed (must pass) and with the named lines changed (must refuse).
// 3. The switch while the tree has no sequence start path: refused at OnInit, in the tester (the not-built line) and on a
//    live chart (INIT_FAILED either way; the tester-only line comes first there). The tree has a start path when code
//    outside the two init blocks reads BRK_Start_Seq; the commit that adds one removes the not-built line, or this test
//    fails both ways. A0 has none.
// 4. The live-chart rule (NOT_PORTED): the tester-only alert on a live chart, next to its accepted neighbour (the same
//    chart with the switch off).
// 5. Load-bearing: mutants of the entrypoint (line 5128's narrowing dropped, line 5128 dropped, each b55-init rule
//    disabled, the delay rule reading one delay only, the not-built line removed) must each be caught.
// What it does not prove: compile cleanliness (MetaEditor), MT5's own SET reader, or any trade. Flags-off equality with
// B54 on the pool is gate 0 (scripts/test_b55_gate0.cjs, controller/test_b55_gate0.py).
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const DIR=path.join(__dirname,'fixtures','b55-axes');
const TABLE=JSON.parse(fs.readFileSync(path.join(DIR,'axes.json'),'utf8'));
const CODE={INIT_FAILED:H.API_CONSTANTS.INIT_FAILED,INIT_PARAMETERS_INCORRECT:H.API_CONSTANTS.INIT_PARAMETERS_INCORRECT};
const SEQ_LIVE='Initialization Failed: BRK_Start_Seq is tester-only in B55; use BRK_Start_Seq=false on a live chart.';
const NOT_BUILT='BRK_SEQ_NOT_BUILT';

// A SET as MT5 writes it (UTF-16LE with a BOM): name=value, or name=value||start||step||stop||Y/N.
function parse(buf,name){
 assert.deepEqual([...buf.subarray(0,2)],[0xFF,0xFE],name+': UTF-16LE with a BOM');
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
function typer(files){
 const datetime=new Set(H.compile(files).globals.filter(g=>g.input&&g.type==='datetime').map(g=>g.name));
 return (name,v)=>{
  const m=datetime.has(name)&&String(v).match(/^(\d{4})\.(\d{2})\.(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/);
  return m?Date.UTC(+m[1],m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0))/1000:value(v);
 };
}
// OnInit once: ok, or the INIT code and the last alert (the harness world shares this alerts array).
function init(files,inputs,fx={}){
 const alerts=[];
 try{H.build({files},{tester:fx.tester??true,inputs,indicator:()=>undefined,world:{alerts,...(fx.world||{})}});return {ok:true};}
 catch(e){if(e.initCode===undefined)throw e;return {ok:false,code:e.initCode,alert:alerts.at(-1)};}
}
const show=r=>r.ok?'ok':'code '+r.code+' "'+r.alert+'"';
function rule(r){
 if(r.ok)return 'ok';
 const id=Object.keys(TABLE.alerts).find(k=>TABLE.alerts[k]===r.alert&&CODE[TABLE.codes[k]]===r.code);
 return id||'unlisted refusal: '+show(r);
}
const current=(files,file)=>{const typed=typer(files),rows=parse(fs.readFileSync(file),path.basename(file));
 return {rows,typed,values:Object.fromEntries(rows.map(r=>[r.name,typed(r.name,r.cur)]))};};

// 1. The synthetic axis SETs.
function axes(files){
 const problems=[];let runs=0;
 for(const entry of TABLE.sets){
  const {rows,typed,values}=current(files,path.join(DIR,entry.file));
  const probes=[['current',values]];
  for(const r of rows) if(r.opt){probes.push([r.name+'@start',{...values,[r.name]:typed(r.name,r.start)}]);probes.push([r.name+'@stop',{...values,[r.name]:typed(r.name,r.stop)}]);}
  const seen={};
  for(const [probe,inputs] of probes){seen[probe]=rule(init(files,inputs));runs++;}
  for(const probe of new Set([...Object.keys(seen),...Object.keys(entry.probes)]))
   if(seen[probe]!==entry.probes[probe]) problems.push(entry.file+' '+probe+': OnInit gives '+seen[probe]+', axes.json '+entry.probes[probe]);
 }
 return {problems,runs};
}

// 2. Spec 3.7's table on committed files.
const B54_SINGLE=path.join(__dirname,'fixtures','b54-axes','brk-nbar-ends.set'),POOL_SEQUENCE=path.join(__dirname,'fixtures','b54-pool','01-EURCAD-sequence.set');
function table(files){
 const problems=[],expect=(what,r,want)=>{const got=rule(r);if(got!==want)problems.push('spec table, '+what+': '+show(r)+', wanted '+want);};
 const single=current(files,B54_SINGLE).values,pool=current(files,POOL_SEQUENCE).values;
 const seq=current(files,path.join(DIR,'seq-nbar-inside.set')).values,pday=current(files,path.join(DIR,'seq-pday-inside.set')).values;
 const grid={...single,Engine_Mode:0};
 expect('BRK_WITHOUT_SINGLE must refuse brk-nbar-ends.set on the grid engine',init(files,grid),'BRK_WITHOUT_SINGLE');
 expect('BRK_WITHOUT_SINGLE must pass it with the switch and both delays 0',init(files,{...grid,BRK_Start_Seq:true,Delay_Trade:0,Delay_Trade_Live:0}),NOT_BUILT);   // A0; PR A: ok
 expect('BRK_WITHOUT_SINGLE must pass brk-nbar-ends.set',init(files,single),'ok');
 expect('BRK_SEQ_WITHOUT_BRK must refuse the pool sequence with the switch',init(files,{...pool,BRK_Start_Seq:true}),'BRK_SEQ_WITHOUT_BRK');
 expect('BRK_SEQ_WITHOUT_BRK must pass the pool sequence',init(files,pool),'ok');
 expect('BRK_SEQ_WITH_SINGLE must refuse brk-nbar-ends.set with the switch',init(files,{...single,BRK_Start_Seq:true}),'BRK_SEQ_WITH_SINGLE');
 expect('BRK_SEQ_WITH_SINGLE must refuse it with both delays 0 too',init(files,{...single,BRK_Start_Seq:true,Delay_Trade:0,Delay_Trade_Live:0}),'BRK_SEQ_WITH_SINGLE');
 expect('BRK_SEQ_WITH_DELAY must refuse seq-nbar-inside.set with Delay_Trade=1',init(files,{...seq,Delay_Trade:1}),'BRK_SEQ_WITH_DELAY');
 expect('BRK_SEQ_WITH_DELAY must refuse seq-nbar-inside.set with Delay_Trade_Live=1',init(files,{...seq,Delay_Trade_Live:1}),'BRK_SEQ_WITH_DELAY');
 expect('BRK_SEQ_WITH_DELAY must refuse a negative delay',init(files,{...seq,Delay_Trade:-1}),'BRK_SEQ_WITH_DELAY');
 expect('BRK_SEQ_WITH_DELAY must pass seq-nbar-inside.set',init(files,seq),NOT_BUILT);   // A0; PR A: ok
 expect('BRK_SEQ_WITH_DELAY must pass seq-pday-inside.set',init(files,pday),NOT_BUILT);  // A0; PR A: ok
 return problems;
}

// 3. The switch and the start path.
function startPath(main){
 let block=null;
 for(const line of main.split('\n')){
  const begin=line.match(/\/\/ (B5[45]):begin (b54-init|b55-init)\b/),end=line.match(/\/\/ (B5[45]):end (b54-init|b55-init)\b/);
  if(begin){block=begin[2];continue;}
  if(end){block=null;continue;}
  if(block===null&&/\bBRK_Start_Seq\b/.test(line.replace(/\/\/.*$/,''))) return true;
 }
 return false;
}
function notBuilt(files){
 const problems=[],seq=current(files,path.join(DIR,'seq-nbar-inside.set')).values;
 const tester=init(files,seq),live=init(files,seq,{tester:false});
 if(!startPath(files[H.MAIN])){
  if(rule(tester)!==NOT_BUILT) problems.push('the tree has no sequence start path, but the tester gives '+show(tester));
  if(live.ok||live.code!==CODE.INIT_FAILED) problems.push('the tree has no sequence start path, but a live chart gives '+show(live));
 }else{
  if(!tester.ok) problems.push('the tree has a sequence start path, but the tester gives '+show(tester));
 }
 return problems;
}

// 4. The live chart (NOT_PORTED), next to its accepted neighbour.
function live(files){
 const problems=[],expect=(what,r,want)=>{const got=r.ok?'ok':r.alert;if(got!==want||(!r.ok&&r.code!==CODE.INIT_FAILED))problems.push(what+': '+show(r)+', wanted '+want);};
 const seq=current(files,path.join(DIR,'seq-nbar-inside.set')).values,pday=current(files,path.join(DIR,'seq-pday-inside.set')).values;
 expect('the N-bar sequence on a live chart',init(files,seq,{tester:false}),SEQ_LIVE);
 expect('the prior-day sequence on a live chart',init(files,pday,{tester:false}),SEQ_LIVE);
 expect('the same chart, the switch off, no breakout',init(files,{...seq,BRK_Start_Seq:false,BRK_Mode:0},{tester:false}),'ok');
 return problems;
}

const all=files=>[...axes(files).problems,...table(files),...notBuilt(files),...live(files)];

// The tree.
const tree=H.loadSources();
assert.ok(tree[H.MAIN].indexOf('// B55:begin b55-init')>tree[H.MAIN].indexOf('// B54:end b54-init'),'the b55-init block follows the b54-init block');
assert.ok(tree[H.MAIN].indexOf('// B55:end b55-init')<tree[H.MAIN].indexOf('GoatBrkLatchRebuild();'),'and comes before the latch rebuild');
const {runs}=axes(tree);
const problems=all(tree);
assert.deepEqual(problems,[],'b55-init on the tree');
assert.equal(startPath(tree[H.MAIN]),false,'A0: no code outside the init blocks reads BRK_Start_Seq (the start path is PR A\'s)');

// 5. Mutants.
const mutate=(from,to,count=1)=>{const n=tree[H.MAIN].split(from).length-1;assert.equal(n,count,'mutant anchor '+JSON.stringify(from));return {...tree,[H.MAIN]:tree[H.MAIN].split(from).join(to)};};
const MUTANTS=[
 ['line 5128\'s narrowing dropped (B54\'s line back)',mutate('Engine_Mode!=Engine_Single && !BRK_Start_Seq)','Engine_Mode!=Engine_Single)'),'seq-nbar-inside.set current: OnInit gives BRK_WITHOUT_SINGLE'],
 ['line 5128 dropped, not just narrowed',mutate('if(BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq)','if(false && BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq)'),'grid-nbar-switch-off.set current: OnInit gives ok'],
 ['the grid-engine rule disabled (the switch on a single)',mutate('if(BRK_Start_Seq && Engine_Mode==Engine_Single)','if(false && BRK_Start_Seq && Engine_Mode==Engine_Single)'),'seq-single.set current: OnInit gives BRK_SEQ_NOT_BUILT'],
 ['the breakout-mode rule disabled',mutate('if(BRK_Start_Seq && BRK_Mode==BRK_Disabled)','if(false && BRK_Start_Seq && BRK_Mode==BRK_Disabled)'),'seq-no-mode.set current: OnInit gives BRK_SEQ_NOT_BUILT'],
 ['the delay rule dropped',mutate('if(BRK_Start_Seq && (Delay_Trade!=0 || Delay_Trade_Live!=0))','if(false && BRK_Start_Seq && (Delay_Trade!=0 || Delay_Trade_Live!=0))'),'seq-nbar-delay-trade.set current: OnInit gives BRK_SEQ_NOT_BUILT'],
 ['the delay rule reads Delay_Trade only',mutate('(Delay_Trade!=0 || Delay_Trade_Live!=0)','(Delay_Trade!=0)'),'seq-nbar-delay-live.set Delay_Trade_Live@stop: OnInit gives BRK_SEQ_NOT_BUILT'],
 ['the delay rule reads Delay_Trade_Live only',mutate('(Delay_Trade!=0 || Delay_Trade_Live!=0)','(Delay_Trade_Live!=0)'),'seq-nbar-delay-trade.set current: OnInit gives BRK_SEQ_NOT_BUILT'],
 ['the live-chart rule disabled',mutate('if(BRK_Start_Seq && !MQLInfoInteger(MQL_TESTER))','if(false && BRK_Start_Seq && !MQLInfoInteger(MQL_TESTER))'),'the N-bar sequence on a live chart'],
 ['the not-built line removed, no start path',mutate('if(BRK_Start_Seq)                                        {Alert(','if(false && BRK_Start_Seq) {Alert('),'the tree has no sequence start path, but the tester gives ok'],
];
for(const [name,files,want] of MUTANTS){
 const found=all(files);
 assert.ok(found.some(p=>p.includes(want)),'mutant "'+name+'" is caught ('+want+'): '+JSON.stringify(found.slice(0,3)));
}
// The other way: a start path without the not-built line removed (the switch read outside the init blocks) is caught too.
{const withPath={...tree,[H.MAIN]:tree[H.MAIN].replace('// B55:end b55-init','// B55:end b55-init\n   if(BRK_Start_Seq) Print("B55 mutant: a start path");')};
 assert.equal(startPath(withPath[H.MAIN]),true);
 assert.ok(notBuilt(withPath).some(p=>p.includes('the tree has a sequence start path, but the tester gives')),'a start path beside the not-built line is caught');}
console.log('b55_init: '+TABLE.sets.length+' axis SETs, '+runs+' OnInit probes as axes.json names; '+table(tree).length+' spec-table problems; the switch refused as not built (tester and live); '
 +live(tree).length+' live-chart problems; '+(MUTANTS.length+1)+' mutants caught');
