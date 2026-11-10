// B54 flags-off parity (docs/b54/BREAKOUT_ENTRIES_SPEC.md 6.3). With BRK_Mode and ORB_Mode off, this tree must trade
// exactly as B53 (V1.49-BETA17-53, merge 216e1622 of GOAT-EA#296), with the grid engine and the single-trade engine.
// scripts/b50_tick_harness.cjs converts B53's real source and this tree's (OnTick's whole body with UpdateCurrentSignals,
// SignalEntryTrigger, GoatSignalAll and the single's exits, the SEQUENCE methods, the transaction path, OnInit's slices) and
// runs both on test_b51_parity.cjs's fixtures (its grid and single fixtures, the adopted basket and single), each with
// FastSpeed_Flag true and false: every OrderSend, PositionModify, close and broker SL/TP fill must be identical, in order,
// and so must the positions, the balance and the run's position count.
// - Off means off: the same fixtures with every B54 input moved off its default (both modes still off) trade as B53 too,
//   so a disabled family reads none of its inputs.
// - The WriteSet golden: a default SET written by this tree is B53's, line for line; each B54 input that differs from its
//   default adds exactly one line, after B53's, in input order (A0 wrote them; gate 0 proves them on the 61 pool files).
// - Load-bearing: the term read with the mode off, and the prior-day latch read with the mode off, must each be caught.
// What it does not prove: the native tester (the Banker deal-table parity on all 61, ruling 3, on the final candidate EX5).
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const {ALL}=require('./test_b51_parity.cjs');
const B53='216e16225441cfc1bfe0546c1c70adaf327405cf';
let passed=0;const ok=()=>passed++;
// Every B54 input off its default, the two modes off (spec 3.1, 4.1).
const MOVED={BRK_TF_:'TF_M5',BRK_Bars:7,BRK_Buffer_ATR:1.5,BRK_Once_Per_Level:false,ORB_Clock:'ORB_Clock_London',ORB_TF_:'TF_M15',
 ORB_Start_Minute:480,ORB_Range_Minutes:45,ORB_Entry_Minutes:120,ORB_Buffer_ATR:0.5,ORB_Min_Range_ATR:0.5,ORB_Max_Range_ATR:3.0};
const world=(source,fx,fastSpeed,extra={})=>H.build(source,{...fx,inputs:{...fx.inputs,...extra},fastSpeed,tester:fx.tester??true});
function same(label,before,after){
 assert.deepEqual(after.w.trace,before.w.trace,label+': B54 flags off trades exactly as B53 (OrderSend, PositionModify, closes, broker fills)');
 assert.deepEqual(after.w.positions,before.w.positions,label+': the same positions at the end');
 assert.equal(after.w.balance,before.w.balance,label+': the same balance');
 assert.equal(after.ctx.Positions,before.ctx.Positions,label+': the same position count');
}
const runs={};
for(const [name,fx] of ALL){
 for(const fastSpeed of [true,false]){
  const label=name+(fastSpeed?' (FastSpeed)':' (visual)');
  const before=world(B53,fx,fastSpeed),after=world(undefined,fx,fastSpeed),moved=world(undefined,fx,fastSpeed,MOVED);
  before.run(fx.path);after.run(fx.path);moved.run(fx.path);
  assert.ok(fx.expect(before.w.trace,before.w,before.ctx),label+': the fixture exercises what it names (B53)');
  same(label,before,after);same(label+', every B54 input moved',before,moved);
  runs[label]=before.w.trace.length;ok();
 }
}
assert.equal(Object.keys(runs).length,ALL.length*2);

// Load-bearing: a term or a latch that reads with its mode off changes the single fixtures' trades.
const killed=[];
{const main=H.readSource(undefined,H.MAIN);
 const swap=(text,from,to)=>{assert.equal(text.split(from).length,2,'the mutant site is unique: '+from);return text.replace(from,to);};
 const mutants=[
  ['the buy term read with BRK_Mode off',swap(main,'      && ( BRK_Mode==BRK_Disabled  || BRK_Sig==OP_BUY)) // B54 (spec 3.6)','      && ( BRK_Sig==OP_BUY)) // B54 (spec 3.6)'),['single_stop_tp','single_reverse']],
  ['the latch read with BRK_Mode off',swap(main,'return(BRK_Mode==BRK_PriorDay && BRK_Once_Per_Level && g_GoatBrkDay>0 && g_GoatBrkLatchDay[signal]==g_GoatBrkDay);','return(g_GoatBrkLatchDay[signal]==g_GoatBrkDay);'),['single_stop_tp','single_exits']],
 ];
 const byName=Object.fromEntries(ALL);
 for(const [what,text,names] of mutants){
  const files=H.loadSources(undefined,{[H.MAIN]:text});
  for(const name of names){
   const fx=byName[name],base=world(B53,fx,true),m=H.build({files},{...fx,fastSpeed:true,tester:true});
   base.run(fx.path);m.run(fx.path);
   assert.notDeepEqual(m.w.trace,base.w.trace,'mutant caught: '+what+' ('+name+')');
  }
  killed.push(what);
 }
 ok();}

// WriteSet golden.
const quiet={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled'};
function writeSet(source,inputs={}){
 const W=H.build(source,{inputs:quiet});for(const [k,v] of Object.entries(inputs))W.setInput(k,v);const lines=[];
 W.ctx.FileWrite=(h,...a)=>{lines.push(a.map(String).join(''));return 1;};W.ctx.FileClose=()=>{};
 W.ctx.FileSET_handle=7;W.ctx.WriteSet('; GOAT harness');return lines;
}
{const base=writeSet(B53),tree=writeSet(undefined);
 assert.ok(base.length>120,'WriteSet wrote the SET ('+base.length+' lines)');
 assert.deepEqual(tree,base,'a default SET is B53\'s');
 const single={Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Single_TP_R:2};
 assert.deepEqual(writeSet(undefined,single),writeSet(B53,single),'a B53 single SET is B53\'s');
 const C=H.compile(H.loadSources()).unit.constants;
 const written=(k,v)=>k+'='+(typeof v==='string'?C.get(v):typeof v==='boolean'?String(v):String(v));
 const changes={BRK_Mode:'BRK_NBar',...MOVED,ORB_Mode:'ORB_Breakout'};
 for(const [name,value] of Object.entries(changes)){
  const out=writeSet(undefined,{[name]:value});
  assert.deepEqual(out.filter(l=>!base.includes(l)),[written(name,value)],name+': one line, only when it differs');
  assert.equal(out.length,base.length+1,name);
 }
 ok();}

console.log(JSON.stringify({passed,test:'b54_parity',baseline:B53,fixtures:runs,mutantsKilled:killed}));
