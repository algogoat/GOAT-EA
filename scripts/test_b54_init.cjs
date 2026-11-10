// B54 PR A (docs/b54/BREAKOUT_ENTRIES_SPEC.md 4.6; Claude-Mac's ruling on GOAT-EA#303, conditions 3 and 4): the EA half of
// the b54-init block, through scripts/b50_tick_harness.cjs (OnInit's real slices, the block included as written).
// 1. The synthetic axis SETs (scripts/fixtures/b54-axes, never pool files): at each probe (the SET's values, then each Y
//    axis at its start and at its stop, the others at their values) OnInit reports exactly the rule axes.json names: the
//    same INIT code and alert as that rule of the controller's EA_INIT_RULES. controller/test_b54_init.py gives the same
//    files to validate_strategy and checks the same table, so the EA and its mirror agree on every probe.
// 2. Condition 3: every BRK_Mode / ORB_Mode value whose signal term this tree does not have is refused at OnInit, in the
//    tester and on a live chart; a value that has a term is not refused for it. A value has a term when code inside a
//    "// B54:begin <item>-signal" block of the entrypoint names its label; the commit that adds one removes the value's
//    *_NOT_BUILT line, or this test fails both ways.
// 3. The rules the controller cannot port: the chart's timeframe (PriorDay on TF_Cur, the M_Current cadence), ORB on a live
//    chart, and the two pre-2007 test starts, each refused and each next to an accepted neighbour.
// 4. Load-bearing: mutants of the entrypoint (a *_NOT_BUILT line removed, a term added without removing its line, Lim
//    1260 -> 1320, BRK_Bars' bound 500 -> 501, the D1 chart bound >= -> >) must each be caught.
// What it does not prove: compile cleanliness (MetaEditor), MT5's own SET reader, or any trade.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const DIR=path.join(__dirname,'fixtures','b54-axes');
const TABLE=JSON.parse(fs.readFileSync(path.join(DIR,'axes.json'),'utf8'));
const CODE={INIT_FAILED:H.API_CONSTANTS.INIT_FAILED,INIT_PARAMETERS_INCORRECT:H.API_CONSTANTS.INIT_PARAMETERS_INCORRECT};
const K=H.API_CONSTANTS;
const BASE={Engine_Mode:1,Single_SL_ATR:1.0,Mode_Bias_Exit:0};
const ORB_LIVE='Initialization Failed: ORB_Mode is tester-only in B54 (ruling 7); use ORB_Disabled on a live chart.';
const CHART={
 pdayCur:'Initialization Failed: BRK_Mode=BRK_PriorDay with BRK_TF_=TF_Cur needs a chart timeframe below D1.',
 brkCadence:'Initialization Failed: Signal_Sample_Period=M_Current checks once per chart bar, so a BRK_TF_ shorter than the chart\'s would skip trigger bars.',
 orbCadence:'Initialization Failed: Signal_Sample_Period=M_Current checks once per chart bar, so an ORB_TF_ shorter than the chart\'s would skip trigger bars.',
 ny2007:'Initialization Failed: ORB_Clock_NewYork with a fixed or EU DST server model needs a test start on or after 2007.03.11 (the US DST rules it applies).',
 london2007:'Initialization Failed: ORB_Clock_London needs a test start on or after 2007.03.11 under every server model (its UTC comes through the 2007 US DST rules).'};

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
 try{H.build({files},{tester:fx.tester??true,inputs,indicator:()=>undefined,start:fx.start,world:{alerts,...(fx.world||{})}});return {ok:true};}
 catch(e){if(e.initCode===undefined)throw e;return {ok:false,code:e.initCode,alert:alerts.at(-1)};}
}
const show=r=>r.ok?'ok':'code '+r.code+' "'+r.alert+'"';
function rule(r){
 if(r.ok)return 'ok';
 const id=Object.keys(TABLE.alerts).find(k=>TABLE.alerts[k]===r.alert&&CODE[TABLE.codes[k]]===r.code);
 return id||'unlisted refusal: '+show(r);
}

// 1. The synthetic axis SETs.
function axes(files){
 const problems=[],typed=typer(files);let runs=0;
 for(const entry of TABLE.sets){
  const rows=parse(fs.readFileSync(path.join(DIR,entry.file)),entry.file);
  const current=Object.fromEntries(rows.map(r=>[r.name,typed(r.name,r.cur)]));
  const probes=[['current',current]];
  for(const r of rows) if(r.opt){probes.push([r.name+'@start',{...current,[r.name]:typed(r.name,r.start)}]);probes.push([r.name+'@stop',{...current,[r.name]:typed(r.name,r.stop)}]);}
  const seen={};
  for(const [probe,inputs] of probes){seen[probe]=rule(init(files,inputs));runs++;}
  for(const probe of new Set([...Object.keys(seen),...Object.keys(entry.probes)]))
   if(seen[probe]!==entry.probes[probe]) problems.push(entry.file+' '+probe+': OnInit gives '+seen[probe]+', axes.json '+entry.probes[probe]);
 }
 return {problems,runs};
}

// 2. Condition 3: the mode values without a signal term.
function modeValues(files){
 const header=files[H.HEADER],out=[];
 for(const [input,type] of [['BRK_Mode','ENUM_MODE_BRK'],['ORB_Mode','ENUM_MODE_ORB']]){
  const body=header.match(new RegExp('enum\\s+'+type+'\\s*\\{([^}]*)\\}'));assert.ok(body,type+' is declared');
  for(const m of body[1].replace(/\/\/[^\n]*/g,'').matchAll(/(\w+)\s*=\s*(\d+)/g)) if(!/_Disabled$/.test(m[1])) out.push({input,label:m[1],value:Number(m[2])});
 }
 return out;
}
function terms(main){
 const out=new Set();let open=false;
 for(const line of main.split('\n')){
  if(/\/\/ B54:begin \S+-signal\b/.test(line)){open=true;continue;}
  if(/\/\/ B54:end \S+-signal\b/.test(line)){open=false;continue;}
  if(open) for(const m of line.replace(/\/\/.*$/,'').matchAll(/\b(BRK_NBar|BRK_PriorDay|ORB_Breakout)\b/g)) out.add(m[1]);
 }
 return out;
}
const notBuilt=label=>({BRK_NBar:'BRK_NBAR_NOT_BUILT',BRK_PriorDay:'BRK_PRIOR_DAY_NOT_BUILT',ORB_Breakout:'ORB_BREAKOUT_NOT_BUILT'})[label];
function condition3(files){
 const problems=[],have=terms(files[H.MAIN]),values=modeValues(files);
 if(values.length!==3) problems.push('mode values: '+values.map(v=>v.label).join(', '));
 for(const {input,label,value:v} of values){
  const inputs={...BASE,[input]:v};
  const tester=init(files,inputs),live=init(files,inputs,{tester:false});
  if(!have.has(label)){
   if(rule(tester)!==notBuilt(label)) problems.push(label+' has no signal term, but the tester gives '+show(tester));
   if(live.ok||live.code!==CODE.INIT_FAILED||![TABLE.alerts[notBuilt(label)],ORB_LIVE].includes(live.alert)) problems.push(label+' has no signal term, but a live chart gives '+show(live));
  }else{
   if(rule(tester)===notBuilt(label)) problems.push(label+' has a signal term and is still refused as not built');
  }
 }
 return problems;
}

// 3. The chart's timeframe, the live chart and the test start (NOT_PORTED and TESTER_INIT_RULES).
function chart(files){
 const problems=[],expect=(what,r,want)=>{const got=r.ok?'ok':r.alert;if(got!==want)problems.push(what+': '+show(r)+', wanted '+want);};
 const pday={...BASE,BRK_Mode:2,BRK_TF_:0},nbar={...BASE,BRK_Mode:1},orb={...BASE,ORB_Mode:1};
 const NB=TABLE.alerts.BRK_NBAR_NOT_BUILT,PB=TABLE.alerts.BRK_PRIOR_DAY_NOT_BUILT,OB=TABLE.alerts.ORB_BREAKOUT_NOT_BUILT;
 expect('PriorDay on TF_Cur, D1 chart',init(files,pday,{world:{period:K.PERIOD_D1}}),CHART.pdayCur);
 expect('PriorDay on TF_Cur, W1 chart',init(files,pday,{world:{period:K.PERIOD_W1}}),CHART.pdayCur);
 expect('PriorDay on TF_Cur, H4 chart',init(files,pday,{world:{period:K.PERIOD_H4}}),PB);
 expect('N-bar on TF_Cur, D1 chart',init(files,{...nbar,BRK_TF_:0},{world:{period:K.PERIOD_D1}}),NB);
 const cadence={Signal_Sample_Period:99},h1={world:{period:K.PERIOD_H1}};
 expect('N-bar M5 on an H1 chart, M_Current',init(files,{...nbar,...cadence,BRK_TF_:5},h1),CHART.brkCadence);
 expect('N-bar H4 on an H1 chart, M_Current',init(files,{...nbar,...cadence,BRK_TF_:240},h1),NB);
 expect('N-bar TF_Cur on an H1 chart, M_Current',init(files,{...nbar,...cadence,BRK_TF_:0},h1),NB);
 expect('N-bar M5 on an H1 chart, M1 sampling',init(files,{...nbar,Signal_Sample_Period:1,BRK_TF_:5},h1),NB);
 expect('ORB M5 on an H1 chart, M_Current',init(files,{...orb,...cadence,ORB_TF_:5},h1),CHART.orbCadence);
 expect('ORB H1 on an H1 chart, M_Current',init(files,{...orb,...cadence,ORB_TF_:60,ORB_Start_Minute:540,ORB_Range_Minutes:60},h1),OB);
 expect('ORB on a live chart',init(files,orb,{tester:false}),ORB_LIVE);
 const y2006=Date.UTC(2006,5,1)/1000,day2007=Date.UTC(2007,2,11)/1000;
 expect('ORB New York anchor, fixed model, 2006',init(files,{...orb,Server_Clock_Model:1},{start:y2006}),CHART.ny2007);
 expect('ORB New York anchor, EU DST model, 2006',init(files,{...orb,Server_Clock_Model:2},{start:y2006}),CHART.ny2007);
 expect('ORB New York anchor, NYClose model, 2006',init(files,{...orb,Server_Clock_Model:0},{start:y2006}),OB);
 expect('ORB New York anchor, fixed model, 2007.03.11',init(files,{...orb,Server_Clock_Model:1},{start:day2007}),OB);
 for(const model of [0,1,2]) expect('ORB London anchor, model '+model+', 2006',init(files,{...orb,ORB_Clock:1,Server_Clock_Model:model},{start:y2006}),CHART.london2007);
 expect('ORB London anchor, 2007.03.11',init(files,{...orb,ORB_Clock:1},{start:day2007}),OB);
 expect('both families off, 2006, D1 chart, live',init(files,{...BASE,ORB_Clock:1,Server_Clock_Model:1,BRK_TF_:0},{tester:false,start:y2006,world:{period:K.PERIOD_D1}}),'ok');
 return problems;
}

const all=files=>[...axes(files).problems,...condition3(files),...chart(files)];

// The tree.
const tree=H.loadSources();
const mark=tree[H.MAIN].indexOf('// B54:begin b54-init');assert.ok(mark>0,'the b54-init block is in the entrypoint');
const {runs}=axes(tree);
const problems=all(tree);
assert.deepEqual(problems,[],'b54-init on the tree');
assert.equal(terms(tree[H.MAIN]).size,0,'PR A commit 1: no signal term yet, so every mode value is refused');

// 4. Mutants.
const mutate=(from,to,count=1)=>{const text=tree[H.MAIN];const n=text.split(from).length-1;assert.equal(n,count,'mutant anchor '+JSON.stringify(from));return {...tree,[H.MAIN]:text.split(from).join(to)};};
const MUTANTS=[
 ['the N-bar not-built line removed',mutate('   if(BRK_Mode==BRK_NBar)                                   {Alert("Initialization Failed: BRK_Mode=BRK_NBar has no signal term in this build yet."); return INIT_FAILED;}\n',''),'BRK_NBar has no signal term, but the tester gives'],
 ['a term added, its line kept',mutate('// B54:begin b54-init','// B54:begin brk-signal\n   if(BRK_Mode==BRK_NBar) {}\n// B54:end brk-signal\n// B54:begin b54-init'),'BRK_NBar has a signal term and is still refused'],
 ['Lim 1260 -> 1320',mutate('? 1260 : 1020','? 1320 : 1020',3),'orb-london-lim.set ORB_Start_Minute@stop'],
 ['BRK_Bars bound 500 -> 501',mutate('BRK_Bars>500','BRK_Bars>501'),'brk-nbar-bars-ends.set BRK_Bars@stop'],
 ['D1 chart bound >= -> >',mutate('PeriodSeconds(PERIOD_CURRENT)>=PeriodSeconds(PERIOD_D1)','PeriodSeconds(PERIOD_CURRENT)>PeriodSeconds(PERIOD_D1)'),'PriorDay on TF_Cur, D1 chart'],
];
for(const [name,files,want] of MUTANTS){
 const found=all(files);
 assert.ok(found.some(p=>p.includes(want)),'mutant "'+name+'" is caught ('+want+'): '+JSON.stringify(found.slice(0,3)));
}
console.log('b54_init: '+TABLE.sets.length+' axis SETs, '+runs+' OnInit probes as axes.json names; condition 3 for '+modeValues(tree).length+
 ' mode values (tester and live); '+chart(tree).length+' chart/live/test-start problems; '+MUTANTS.length+' mutants caught');
