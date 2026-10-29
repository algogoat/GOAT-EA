// B51 flags-off parity (B50-beta-1, docs/b50/B50_ALPHA_DESIGN.md section 8). With every B50-beta input at its default
// (no random direction, seed 1; beta-1b: no break-even, no trailing, also with a trailing start but no distance), this
// tree must trade exactly as B50-alpha
// (V1.49-BETA17-50, source 32df4eb, EX5 8364a371), with the grid engine and with the single-trade engine alike.
// scripts/b50_tick_harness.cjs converts B50-alpha's real source and this tree's (OnTick's whole body with
// SignalEntryTrigger, the single's entry and exits, OpenPosition, the SEQUENCE methods and the transaction path) and
// runs both on the same fixtures: every OrderSend, PositionModify, close and broker SL/TP fill must be identical, in
// order. Each fixture first proves it exercises what it names (a parity of nothing proves nothing).
// Fixtures: the grid's (an ATR-mode grid, Delay_Trade virtual entries, CumPartial, PeakSmart, SmartRescue, the day-end
// and Friday close, News_Close) and the single's (a stop, a TP in R, the opposite-signal exit and the time stop, a
// Reverse_Seq sell, an adopted single after a live restart), each with FastSpeed_Flag true and false; also with a
// non-default seed (the seed is read only when Random_Direction is on).
// The WriteSet golden: a default SET written by this tree is B50-alpha's, byte for byte; each B50-beta input is
// written, only when it differs from its default, in the form MT5 reads back, after B50-alpha's lines.
// Native tester parity (flags off, this build against 8364a371) is the native proof.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B50_ALPHA='32df4eb';
let passed=0;const ok=()=>passed++;

const DAY=86400,MON=Date.UTC(2026,9,5)/1000,H1=3600,M1=60;
function path(start,points){
 const ticks=[];
 for(let k=1;k<points.length;k++){
  const [t0,p0]=points[k-1],[t1,p1]=points[k];
  for(let t=t0;t<t1;t+=20) ticks.push([start+t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);
 }
 return ticks;
}
const quiet={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled'};
const atr=(name,buffer,shift)=>name==='ATR_MA'?0.0010:undefined;
const has=(trace,op,n=1)=>trace.filter(x=>x.op===op).length>=n;
const logged=(w,re)=>w.logs.some(l=>re.test(l));
// The single: RSI_OverBS (<=30 buy, >=70 sell); ATR 0.0010 on the closed bar.
const single={...quiet,RSI_Mode:'RSI_OverBS',RSI_Level:70,Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500};
const rsi=sched=>(name,buffer,shift,w)=>{if(name==='ATR_MA')return shift===1?0.0010:0.0030;if(name!=='RSI')return undefined;let v=50;for(const [from,x] of sched)if(w.time-MON>=from)v=x;return v;};
const FIXTURES={
 atr_grid:{inputs:{Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4,Mode_Bias:'Bias_Disabled',Delay_Trade:0,
   RSI_Mode:'RSI_OverBS',RSI_Level:70,EMA_Mode:'Trade_Trend',EMA_Count:2,ADX_Mode:'Trade_Trend',ADX_Level:20},
  indicator:(name,buffer,shift,w)=>{
   if(name==='ATR_MA') return 0.0010;
   const t=w.time-MON;
   if(name==='RSI') return t<5*H1?25:(t<9*H1?50:80);
   if(name==='MA0') return t<9*H1?1.12:1.08;
   if(name==='MA1') return 1.10;
   if(name==='ADX') return buffer===0?30:(buffer===1?(t<9*H1?25:15):(t<9*H1?15:25));
   return undefined;},
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0960],[8*H1,1.1060],[10*H1,1.1020],[12*H1,1.0990]]),
  expect:(t,w)=>has(t,'OrderSend',2)&&has(t,'PositionModify',10)&&has(t,'BrokerTake')&&logged(w,/Sell Sequence Started/)},
 delay_virtual:{inputs:{...quiet,Delay_Trade:2,Delay_Trade_Live:1,Delay_Lots_Add:true},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[6*H1,1.0930],[8*H1,1.1010]]),
  expect:(t,w)=>has(t,'OrderSend',2)&&logged(w,/Real Sequence Start/)},
 cum_partial:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_Lots_Prog:'Lots_Prog_CumPartial',Partial_Profit_Factor:40.0,Max_Seq_Trades:12},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0940],[6*H1,1.0965],[8*H1,1.0925],[9*H1,1.0960],[11*H1,1.1030]]),
  expect:(t,w)=>has(t,'OrderSend',3)&&has(t,'PositionClosePartial')},
 peak_smart:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_Lots:'RiskperSeq',Risk:800,Mode_Lots_Prog:'Lots_Prog_PeakSmart',
   Peak_Smart_Release_PC:60.0,Peak_Smart_Max_Close_PC:40.0,Max_Seq_Trades:10},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0945],[6*H1,1.0970],[8*H1,1.0930],[9*H1,1.0965],[11*H1,1.1040]]),
  expect:(t,w)=>has(t,'OrderSend',3)&&has(t,'PositionClosePartial')&&logged(w,/Smart Peak harvest/)},
 smart_rescue:{inputs:{...quiet,Mode_Bias:'Bias_Close_low',Bias_Protocol:'BiasProtocol_LegacyRecorded',Bias_threshold:60,
   Mode_Bias_Exit:'BiasExit_SmartRescue',Mode_Lots:'RiskperSeq',Risk:800,Delay_Trade:0,Delay_Trade_Live:0},indicator:atr,
  bias:t=>(t-MON)<5*H1?75:-75,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0950],[7*H1,1.0985],[9*H1,1.0940],[11*H1,1.1010]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&logged(w,/SmartRescue armed/)&&logged(w,/Bias Rescue Exit/)},
 day_friday_close:{start:MON+3*DAY+20*H1,inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Action_Dayend:'Action_Close',Action_Friday:'Action_Close',Mode_Restart:'Restart_1'},indicator:atr,
  path:path(MON+3*DAY,[[20*H1,1.1000],[22*H1+40*60,1.0970],[DAY+2*H1,1.0990],[DAY+6*H1,1.0950],[DAY+13*H1,1.0960]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&has(t,'PositionClose',4)&&w.logs.filter(l=>/Day\/Weekend Close/.test(l)).length>=2},
 news_close:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_News:'News_Close'},indicator:atr,
  news:t=>(t-MON)>=6*H1&&(t-MON)<7*H1,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0960],[9*H1,1.0990]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&has(t,'PositionClose',2)&&logged(w,/Day\/Weekend Close/)},
 // The single: its stop, then a second episode's TP in R.
 single_stop_tp:{inputs:{...single,Single_TP_R:1.5},indicator:rsi([[0,25],[3*H1,50],[4*H1,25]]),
  path:path(MON,[[2*H1-600,1.1000],[2*H1+1800,1.0980],[3*H1+1800,1.0980],[5*H1,1.1020],[6*H1,1.1020]]),
  expect:(t,w)=>has(t,'OrderSend',2)&&has(t,'BrokerStop')&&has(t,'BrokerTake')},
 // The opposite-signal exit and the time stop.
 single_exits:{inputs:{...single,Single_Exit_Opposite:true,Single_Time_Stop_Bars:45,Single_Time_Stop_TF:'TF_Cur'},
  indicator:rsi([[0,25],[2*H1+20*M1,80],[3*H1,50],[4*H1,25]]),
  path:path(MON,[[2*H1-600,1.1000],[6*H1,1.1003]]),
  expect:(t,w)=>has(t,'OrderSend',3)&&logged(w,/Single Exit: opposite signal/)&&logged(w,/Single Exit: time stop/)},
 // Reverse_Seq: the buy signal sells.
 single_reverse:{inputs:{...single,Reverse_Seq:true,Single_TP_ATR:2},indicator:rsi([[0,25]]),
  path:path(MON,[[2*H1-600,1.1000],[3*H1,1.0970],[4*H1,1.0970]]),
  expect:(t,w)=>has(t,'OrderSend',1)&&t.find(x=>x.op==='OrderSend').type===1&&has(t,'BrokerTake')},
};
// The adopted single: a live chart opens a single with B50-alpha's source, the terminal restarts, and both sources adopt
// the same position, deals and restart record (manage-only), then run the same ticks to its TP.
function adoptedSingle(){
 const inputs={...single,Single_TP_R:2};
 const first=H.build(B50_ALPHA,{tester:false,fastSpeed:false,inputs,indicator:rsi([[0,25]])});
 first.run(path(MON,[[2*H1-600,1.1000],[2*H1+600,1.1005]]));
 assert.equal(first.w.positions.length,1,'the single before the restart');
 const state={positions:JSON.parse(JSON.stringify(first.w.positions)),deals:JSON.parse(JSON.stringify(first.w.deals)),gv:[...first.w.gv],
  next:[first.w.nextTicket,first.w.nextDeal],balance:first.w.balance,time:first.w.time,bid:first.w.bid};
 return {tester:false,inputs,indicator:rsi([[0,25]]),start:state.time,bid:state.bid,
  adopt:(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));
   for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;},
  path:path(state.time-2*H1-600-7,[[2*H1+620,1.1005],[4*H1,1.1040],[5*H1,1.1040]]),
  expect:(t,w)=>w.alerts.some(a=>/adopted 1 open position/.test(a))&&has(t,'BrokerTake')};
}
const ALL=[...Object.entries(FIXTURES),['adopted_single',adoptedSingle()]];
const BETA_OFF={Random_Seed:1,Single_BE_ATR:0,Single_Trail_Start_ATR:0,Single_Trail_ATR:0};   // this tree's B50-beta inputs, at their defaults (spelt out)
function worldFor(source,fx,fastSpeed,extra={}){return H.build(source,{...fx,inputs:{...fx.inputs,...(source===undefined?extra:{})},fastSpeed,tester:fx.tester??true});}
const runs={};
for(const [name,fx0] of ALL){
 for(const fastSpeed of [true,false]){
  for(const [variant,extra] of [['defaults',BETA_OFF],['seed 9',{Random_Seed:9}],['a trailing start without a distance',{Single_Trail_Start_ATR:1.5}]]){
   if(variant!=='defaults'&&!fastSpeed) continue;
   if(variant.startsWith('a trailing')&&!/^single|adopted/.test(name)) continue;
   const label=name+(fastSpeed?' FastSpeed':' visual')+(variant==='defaults'?'':' ('+variant+')');
   const before=worldFor(B50_ALPHA,fx0,fastSpeed),after=worldFor(undefined,fx0,fastSpeed,extra);
   before.run(fx0.path);after.run(fx0.path);
   assert.ok(fx0.expect(before.w.trace,before.w,before.ctx),label+': the fixture exercises what it names (B50-alpha): '+JSON.stringify(before.w.trace.slice(0,4))+' '+before.w.logs.slice(-6).join(' | '));
   assert.deepEqual(after.w.trace,before.w.trace,label+': B51 flags off trades exactly as B50-alpha (OrderSend, PositionModify, closes, broker fills)');
   assert.deepEqual(after.w.positions,before.w.positions,label+': the same positions at the end');
   assert.equal(after.w.balance,before.w.balance,label+': the same balance');
   runs[label]=before.w.trace.length;ok();
  }
 }
}

// The harness is load-bearing: a tree whose random branch ignores its flag, or whose seed changes the side with the
// flag off, is caught by the same comparison on the single fixtures.
const killed=[];
{const main=H.readSource(undefined,H.MAIN);
 const swap=(text,from,to)=>{assert.equal(text.split(from).length,2,'the mutant site is unique: '+from);return text.replace(from,to);};
 const mutants=[
  ['the random branch ignores Random_Direction',swap(main,'     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_BUY); else','     if(Engine_Mode==Engine_Single) GoatSingleRandomEntry(OP_BUY); else'),['single_stop_tp','single_reverse']],
  ['the random branch is taken for the sell signal flags off',swap(main,'     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_SELL); else','     if(Engine_Mode==Engine_Single || Random_Direction) GoatSingleRandomEntry(OP_SELL); else'),['single_exits']],
  // beta-1b: the modify runs with its inputs at 0 (break-even at 0 ATR in favour moves the stop to the entry).
  ['the break-even ignores Single_BE_ATR=0',swap(main,'      bool   b51_be=(Single_BE_ATR>0.0 && b51_favour>=Single_BE_ATR*b51_atr-b51_eps);','      bool   b51_be=(b51_favour>=Single_BE_ATR*b51_atr-b51_eps);')
   .replace('   if(Engine_Mode!=Engine_Single || !(Single_SL_ATR>0.0) || (!(Single_BE_ATR>0.0) && !(Single_Trail_ATR>0.0))) return;','   if(Engine_Mode!=Engine_Single || !(Single_SL_ATR>0.0)) return;'),['single_stop_tp','single_reverse']],
 ];
 for(const [what,text,fixtures] of mutants){
  const files=H.loadSources(undefined,{[H.MAIN]:text});
  for(const name of fixtures){
   const fx=FIXTURES[name];const base=worldFor(B50_ALPHA,fx,true),m=H.build({files},{...fx,inputs:{...fx.inputs,Random_Seed:9},fastSpeed:true,tester:true});
   base.run(fx.path);m.run(fx.path);
   assert.notDeepEqual(m.w.trace,base.w.trace,'mutant caught: '+what+' ('+name+')');
  }
  killed.push(what);
 }
 ok();}

// WriteSet golden: a default SET written by this tree is B50-alpha's, line for line; each B50-beta input differing from
// its default adds exactly one line, after B50-alpha's, in the form the Studio and the controller read back.
function writeSet(source,inputs={}){
 const W=H.build(source,{inputs:quiet});for(const [k,v] of Object.entries(inputs))W.setInput(k,v);const lines=[];
 W.ctx.FileWrite=(h,...a)=>{lines.push(a.map(String).join(''));return 1;};W.ctx.FileClose=()=>{};
 W.ctx.FileSET_handle=7;W.ctx.WriteSet('; GOAT harness');return lines;
}
const CHANGED_SET={Random_Direction:[true,'Random_Direction=true'],Random_Seed:[42,'Random_Seed=42'],Single_BE_ATR:[1.25,'Single_BE_ATR=1.25'],
 Single_Trail_Start_ATR:[2,'Single_Trail_Start_ATR=2'],Single_Trail_ATR:[0.5,'Single_Trail_ATR=0.5']};
{const base=writeSet(B50_ALPHA),tree=writeSet(undefined);
 assert.ok(base.length>120,'WriteSet wrote the SET ('+base.length+' lines)');
 assert.deepEqual(tree,base,'a default SET is B50-alpha\'s');
 assert.equal(tree.filter(l=>/^(Random_Direction|Random_Seed|Single_BE_ATR|Single_Trail_Start_ATR|Single_Trail_ATR)=/.test(l)).length,0);
 // An alpha SET with the single engine on is alpha's too.
 const singleOn={Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Single_TP_R:2};
 assert.deepEqual(writeSet(undefined,singleOn),writeSet(B50_ALPHA,singleOn),'a B50-alpha single SET is B50-alpha\'s');
 for(const [name,[value,line]] of Object.entries(CHANGED_SET)){
  const out=writeSet(undefined,{[name]:value});
  assert.deepEqual(out.filter(l=>!base.includes(l)),[line],name+': one line, only when it differs');
  assert.equal(out.length,base.length+1,name);
 }
 const all=writeSet(undefined,Object.fromEntries(Object.entries(CHANGED_SET).map(([k,[v]])=>[k,v])));
 assert.deepEqual(all.slice(base.length),Object.values(CHANGED_SET).map(([,l])=>l),'in input order, after B50-alpha\'s lines');
 ok();}

console.log(JSON.stringify({passed,test:'b51_parity',baseline:B50_ALPHA,fixtures:runs,mutantsKilled:killed}));
