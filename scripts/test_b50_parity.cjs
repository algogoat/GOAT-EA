// B50 flags-off parity (B50-alpha A0, docs/b50/B50_ALPHA_DESIGN.md section 4, "Flags-off OnTick parity" and "WriteSet
// golden"). With every B50 input at its default (the grid engine, the server clock, no rollover block), B50 must trade
// exactly as B49a. scripts/b50_tick_harness.cjs converts B49a's real source (65fde12) and this tree's, OnTick's whole
// body with SignalEntryTrigger, UpdateCurrentSignals, GetSize, OpenPosition, the SEQUENCE methods and the transaction
// path, and runs both on the same fixtures: every OrderSend, PositionModify, close and broker SL/TP fill must be
// identical, in order. Each fixture first proves it exercises what it names (a parity of nothing proves nothing).
// Fixtures: an ATR-mode grid (EMA/ADX/RSI signals), Delay_Trade virtual entries, CumPartial, PeakSmart, SmartRescue,
// the day-end and Friday close, News_Close and an adopted basket, each with FastSpeed_Flag true and false.
// The WriteSet golden: a default SET written by this tree is B49a's, byte for byte; and each B50 input is written, only
// when it differs from its default, in the form MT5 reads back.
// A1-A3 keep this test green on their own heads (their flags off); native tester parity on Banker is the native proof.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B49A='65fde12';
let passed=0;const ok=()=>passed++;

const DAY=86400,MON=Date.UTC(2026,9,5)/1000;   // Monday 2026-10-05 00:00 server time
// Ticks every 20 s (7 s past), price moving linearly between the [seconds after start, bid] points.
function path(start,points){
 const ticks=[];
 for(let k=1;k<points.length;k++){
  const [t0,p0]=points[k-1],[t1,p1]=points[k];
  for(let t=t0;t<t1;t+=20) ticks.push([start+t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);
 }
 return ticks;
}
const H1=3600;
const quiet={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled'};
const atr=(name,buffer,shift)=>name==='ATR_MA'?0.0010:undefined;
const has=(trace,op,n=1)=>trace.filter(x=>x.op===op).length>=n;
const logged=(w,re)=>w.logs.some(l=>re.test(l));
const FIXTURES={
 // ATR-mode grid: grid, lock, TP and trailing in ATR multiples; EMA, ADX and RSI produce the signals.
 atr_grid:{inputs:{Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4,Mode_Bias:'Bias_Disabled',Delay_Trade:0,
   RSI_Mode:'RSI_OverBS',RSI_Level:70,EMA_Mode:'Trade_Trend',EMA_Count:2,ADX_Mode:'Trade_Trend',ADX_Level:20},
  indicator:(name,buffer,shift,w)=>{
   if(name==='ATR_MA') return 0.0010;
   const t=w.time-MON;
   if(name==='RSI') return t<5*H1?25:(t<9*H1?50:80);                 // oversold (buy), then neutral, then overbought (sell)
   if(name==='MA0') return t<9*H1?1.12:1.08;                         // the fast EMA above the slow one (buy), then below (sell)
   if(name==='MA1') return 1.10;
   if(name==='ADX') return buffer===0?30:(buffer===1?(t<9*H1?25:15):(t<9*H1?15:25));
   return undefined;},
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0960],[8*H1,1.1060],[10*H1,1.1020],[12*H1,1.0990]]),
  expect:(t,w)=>has(t,'OrderSend',2)&&has(t,'PositionModify',10)&&has(t,'BrokerTake')&&logged(w,/Sell Sequence Started/)},
 // Delay_Trade: virtual levels first, the real sequence starts at the third.
 delay_virtual:{inputs:{...quiet,Delay_Trade:2,Delay_Trade_Live:1,Delay_Lots_Add:true},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[6*H1,1.0930],[8*H1,1.1010]]),
  expect:(t,w)=>has(t,'OrderSend',2)&&logged(w,/Real Sequence Start/)},
 // CumPartial: cumulative lots with a partial close on each retrace level.
 cum_partial:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_Lots_Prog:'Lots_Prog_CumPartial',Partial_Profit_Factor:40.0,Max_Seq_Trades:12},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0940],[6*H1,1.0965],[8*H1,1.0925],[9*H1,1.0960],[11*H1,1.1030]]),
  expect:(t,w)=>has(t,'OrderSend',3)&&has(t,'PositionClosePartial')},
 // PeakSmart: risk per sequence; the smart peak harvests excess lots on a retrace.
 peak_smart:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_Lots:'RiskperSeq',Risk:800,Mode_Lots_Prog:'Lots_Prog_PeakSmart',
   Peak_Smart_Release_PC:60.0,Peak_Smart_Max_Close_PC:40.0,Max_Seq_Trades:10},indicator:atr,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0945],[6*H1,1.0970],[8*H1,1.0930],[9*H1,1.0965],[11*H1,1.1040]]),
  expect:(t,w)=>has(t,'OrderSend',3)&&has(t,'PositionClosePartial')&&logged(w,/Smart Peak harvest/)},
 // SmartRescue: the AI bias turns against an open buy basket; the rescue moves it to break-even or better.
 smart_rescue:{inputs:{...quiet,Mode_Bias:'Bias_Close_low',Bias_Protocol:'BiasProtocol_LegacyRecorded',Bias_threshold:60,
   Mode_Bias_Exit:'BiasExit_SmartRescue',Mode_Lots:'RiskperSeq',Risk:800,Delay_Trade:0,Delay_Trade_Live:0},indicator:atr,
  bias:t=>(t-MON)<5*H1?75:-75,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0950],[7*H1,1.0985],[9*H1,1.0940],[11*H1,1.1010]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&logged(w,/SmartRescue armed/)&&logged(w,/Bias Rescue Exit/)},
 // Day end and Friday close: the session ends at 22:30 on Thursday and 11:00 on Friday (SESSION_AS).
 day_friday_close:{start:MON+3*DAY+20*H1,inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Action_Dayend:'Action_Close',Action_Friday:'Action_Close',Mode_Restart:'Restart_1'},indicator:atr,
  path:path(MON+3*DAY,[[20*H1,1.1000],[22*H1+40*60,1.0970],[DAY+2*H1,1.0990],[DAY+6*H1,1.0950],[DAY+13*H1,1.0960]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&has(t,'PositionClose',4)&&w.logs.filter(l=>/Day\/Weekend Close/.test(l)).length>=2},
 // News_Close: a news window closes everything and pauses.
 news_close:{inputs:{...quiet,Delay_Trade:0,Delay_Trade_Live:0,Mode_News:'News_Close'},indicator:atr,
  news:t=>(t-MON)>=6*H1&&(t-MON)<7*H1,
  path:path(MON,[[2*H1,1.1000],[5*H1,1.0960],[9*H1,1.0990]]),
  expect:(t,w)=>has(t,'OrderSend',4)&&has(t,'PositionClose',2)&&logged(w,/Day\/Weekend Close/)},
};
// The adopted basket: a live chart opens a buy basket with B49a's source, the terminal restarts, and both sources adopt
// the same positions, deals and restart record (F1-lite, manage-only), then run the same ticks.
function adoptedFixture(){
 const inputs={...quiet,Delay_Trade:0,Delay_Trade_Live:0,Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4,
  Mode_Lots:'RiskperSeq',Risk:500,Sequence_MLPS_Hard_Close:true};
 const first=H.build(B49A,{tester:false,fastSpeed:false,inputs,indicator:atr});
 first.run(path(MON,[[2*H1,1.1000],[5*H1,1.0955]]));
 assert.ok(first.w.positions.length>=3,'the basket before the restart');
 const state={positions:JSON.parse(JSON.stringify(first.w.positions)),deals:JSON.parse(JSON.stringify(first.w.deals)),gv:[...first.w.gv],
  next:[first.w.nextTicket,first.w.nextDeal],balance:first.w.balance,time:first.w.time,bid:first.w.bid};
 return {tester:false,inputs,indicator:atr,start:state.time,bid:state.bid,
  adopt:(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));
   for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;},
  path:path(state.time-5*H1-7,[[5*H1+20,1.0955],[7*H1,1.0985],[9*H1,1.0900],[10*H1,1.0960]]),
  expect:(t,w,ctx)=>w.alerts.some(a=>/adopted \d+ open position/.test(a))&&(has(t,'PositionClose')||has(t,'BrokerStop')||has(t,'BrokerTake'))};
}

function worldFor(source,fx,fastSpeed){return H.build(source,{...fx,fastSpeed,tester:fx.tester??true});}
const runs={};
for(const [name,fx0] of [...Object.entries(FIXTURES),['adopted_basket',adoptedFixture()]]){
 for(const fastSpeed of [true,false]){
  const label=name+(fastSpeed?' FastSpeed':' visual');
  const before=worldFor(B49A,fx0,fastSpeed),after=worldFor(undefined,fx0,fastSpeed);
  before.run(fx0.path);after.run(fx0.path);
  if(process.env.B50_PARITY_DEBUG){const c={};for(const x of before.w.trace)c[x.op]=(c[x.op]||0)+1;console.log(label,JSON.stringify(c),before.w.logs.filter(l=>!/^(Mon|Tue|Wed|Thu|Fri):/.test(l)).slice(0,40).join(' | '));}
  assert.ok(fx0.expect(before.w.trace,before.w,before.ctx),label+': the fixture exercises what it names (B49a): '+JSON.stringify(before.w.trace.slice(0,4))+' '+before.w.logs.slice(-6).join(' | '));
  assert.deepEqual(after.w.trace,before.w.trace,label+': B50 trades exactly as B49a (OrderSend, PositionModify, closes, broker fills)');
  assert.deepEqual(after.w.positions,before.w.positions,label+': the same positions at the end');
  assert.equal(after.w.balance,before.w.balance,label+': the same balance');
  runs[label]=before.w.trace.length;ok();
 }
}

// The B50 lines are what the region adds: the tree's GoatTickBody has the A0 call sites, B49a's has none of them.
{const tree=H.compile(H.loadSources()),base=H.compile(H.loadSources(B49A));
 for(const f of ['GoatSingleOpen','GoatSignalAll','GoatSingleSignalExits','GoatSingleTimeStop','GoatNYClockApply','GoatNYTime']){
  assert.ok(tree.functions.includes(f),'converted from the tree: '+f);assert.ok(!base.functions.includes(f),'not in B49a: '+f);
 }
 const body=tree.code.slice(tree.code.indexOf('function GoatTickBody('));
 for(const call of ['GoatNYClockApply(k)','GoatSingleSignalExits(__ref(','GoatSingleTimeStop()','! g_GoatEntryBlocked','Engine_Mode == Engine_Single'])
  assert.ok(body.slice(0,body.indexOf('\nfunction ')).includes(call),'the tick region calls '+call);
 ok();}

// The harness is load-bearing: a B50 region that drops the grid engine (every add skipped, as if Engine_Single were the
// default) or blocks every entry is caught by the same comparison.
{const main=H.readSource(undefined,H.MAIN);
 const mutants=[
  ['every grid add skipped',main.replace('if(Engine_Mode==Engine_Single) LastBuyTradeSignal = false; else','if(true) LastBuyTradeSignal = false; else')],
  ['every new entry blocked',main.replace('&&!g_GoatEntryBlocked) SignalEntryTrigger();','&&g_GoatEntryBlocked) SignalEntryTrigger();')],
 ];
 const fx=FIXTURES.cum_partial;
 const base=worldFor(B49A,fx,true);base.run(fx.path);
 for(const [what,text] of mutants){
  assert.notEqual(text,main,what+': the mutant applies');
  const files=H.loadSources(undefined,{[H.MAIN]:text});
  const m=worldFor({files},fx,true);m.run(fx.path);
  assert.notDeepEqual(m.w.trace,base.w.trace,'mutant caught: '+what);
 }
 ok();}

// WriteSet golden: a default SET written by this tree is B49a's, line for line; each B50 input differing from its
// default adds exactly one line, in the form the Studio and the controller read back.
function writeSet(source,inputs={}){
 // Inputs set after OnInit: WriteSet writes what it is given (a Single SET without its stop would not pass OnInit).
 const W=H.build(source,{inputs:quiet});for(const [k,v] of Object.entries(inputs))W.setInput(k,v);const lines=[];
 W.ctx.FileWrite=(h,...a)=>{lines.push(a.map(String).join(''));return 1;};W.ctx.FileClose=()=>{};
 W.ctx.FileSET_handle=7;W.ctx.WriteSet('; GOAT harness');return lines;
}
{const base=writeSet(B49A),tree=writeSet(undefined);
 assert.ok(base.length>120,'WriteSet wrote the SET ('+base.length+' lines)');
 assert.deepEqual(tree,base,'a default SET is B49a\'s');
 assert.equal(tree.filter(l=>/^(Engine_Mode|Single_|Clock_Mode|Server_Clock_Model|Server_UTC_Offset|NY_Session|Rollover_Block_Minutes)=/.test(l)).length,0);
 const changed={Engine_Mode:['Engine_Single','Engine_Mode=1'],Single_SL_ATR:[1.5,'Single_SL_ATR=1.5'],Single_TP_ATR:[2,'Single_TP_ATR=2'],
  Single_TP_R:[1.5,'Single_TP_R=1.5'],Single_Exit_Opposite:[true,'Single_Exit_Opposite=true'],Single_Time_Stop_Bars:[12,'Single_Time_Stop_Bars=12'],
  Single_Time_Stop_TF:['TF_D1','Single_Time_Stop_TF=1440'],Clock_Mode:['Clock_NewYork','Clock_Mode=1'],Server_Clock_Model:['ServerClock_EUDST','Server_Clock_Model=2'],
  Server_UTC_Offset:[3,'Server_UTC_Offset=3'],NY_Session:['08:00-17:00','NY_Session=08:00-17:00'],Rollover_Block_Minutes:[15,'Rollover_Block_Minutes=15']};
 for(const [name,[value,line]] of Object.entries(changed)){
  const out=writeSet(undefined,{[name]:value});
  assert.deepEqual(out.filter(l=>!base.includes(l)),[line],name+': one line, only when it differs');
  assert.equal(out.length,base.length+1,name);
 }
 // The lines follow Ledger_Mode's, before the file closes.
 const all=writeSet(undefined,Object.fromEntries(Object.entries(changed).map(([k,[v]])=>[k,v])));
 assert.deepEqual(all.slice(base.length),Object.values(changed).map(([,l])=>l),'in input order, after B49a\'s lines');
 ok();}

console.log(JSON.stringify({passed,test:'b50_parity',baseline:B49A,fixtures:runs}));
