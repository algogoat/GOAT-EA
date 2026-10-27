// B50 exits (B50-alpha A3, docs/b50/B50_ALPHA_DESIGN.md section 3 and the A3 row of section 4): the single's
// opposite-signal exit, its time stop, and the FastSpeed bypass in UpdateCurrentSignals. scripts/b50_tick_harness.cjs
// runs the real OnTick body (GoatTickBody), UpdateCurrentSignals, SignalEntryTrigger and the SEQUENCE methods converted
// from the tree (or from GOAT_EA_MAIN, the mutated entrypoint test_b50_exits_mutations.cjs points it at).
// - GoatSignalAll is SignalEntryTrigger's six-term condition, token for token (both directions), and B49a's;
// - the opposite exit fires under FastSpeed_Flag=true exactly when it fires in a visual run (the bypass before
//   UpdateCurrentSignals' optimization return), never while both signals read true (a range mode), honours
//   Reverse_Seq, runs out of session, and survives a restart (an adopted single exits);
// - the time stop counts bars of Single_Time_Stop_TF from the position's POSITION_TIME (mid-bar entries, H1 and D1),
//   survives a restart, and never closes on an unknown bar count (iBarShift -1), logging it once per position;
// - flags off (the grid engine, or the single without the opposite exit) the optimization return is B49a's.
// The entry path differs before and after A1 (Add_Level in A0's base, GoatSingleOpen after A1): every assertion here
// is about the first position and its exit, never the re-entry that follows.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
let passed=0;const ok=()=>passed++;

const H1=3600,M15=900,DAY=86400,MON=Date.UTC(2026,9,5)/1000;   // Monday 2026-10-05 00:00 server time
// Ticks every 20 s (7 s past the bar) over [from, to), at a flat price (no SL, TP or lock is ever reached).
function flat(from,to,bid=1.1000){const t=[];for(let s=from;s<to;s+=20)t.push([MON+s+7,bid+((s/20)%2)*0.00002]);return t;}
// Three EMAs give the trend its three states (MA0 fast .. MA2 slow): buy (fast above slow), neutral (crossed), sell.
const TREND={buy:[1.12,1.11,1.10],neutral:[1.10,1.12,1.09],sell:[1.08,1.09,1.10]};
// phases: [[seconds after MON, trend], ...] in time order; the trend before the first phase is 'sell'.
function emaIndicator(phases){
 return (name,buffer,shift,w)=>{
  if(name==='ATR_MA') return 0.0010;
  const m=name.match(/^MA(\d)$/);if(!m)return undefined;
  let trend='sell';for(const [at,tr] of phases) if(w.time-MON>=at) trend=tr;
  return TREND[trend][Number(m[1])];
 };
}
const BASE={Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Delay_Trade:0,Delay_Trade_Live:0,Mode_Bias:'Bias_Disabled',
 RSI_Mode:'RSI_Disabled',ADX_Mode:'Trade_Disabled',EMA_Mode:'Trade_Trend',EMA_Count:3,EMA_TF_:'TF_M15',Mode_Trade:'Long'};
function world(inputs,phases,opts={}){
 const W=H.build(undefined,{tester:opts.tester??true,fastSpeed:opts.fastSpeed??true,inputs:{...BASE,...inputs},
  indicator:emaIndicator(phases),start:opts.start??MON+H1,adopt:opts.adopt});
 // Every log line with its server time, so an exit is placed in time.
 W.events=[];const print=W.ctx.Print;
 W.ctx.Print=(...a)=>{print(...a);W.events.push({time:W.w.time,text:a.map(String).join('')});};
 return W;
}
const at=s=>MON+s;
const opens=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const ended=(W,reason)=>W.events.filter(e=>e.text.includes('Sequence Ended ('+reason+')'));
const OPP='Single Exit: opposite signal',TS='Single Exit: time stop';
// The first position: its open, and the first exit with its reason.
function firstExit(W){
 const open=opens(W)[0];if(!open)return null;
 const close=W.w.trace.find(x=>x.op==='PositionClose'&&x.time>=open.time);
 const end=W.events.find(e=>/Sequence Ended \(/.test(e.text)&&e.time>=open.time);
 return {open,close,end,reason:end?end.text.match(/Sequence Ended \((.*)\)/)[1]:null};
}

// 1. GoatSignalAll is SignalEntryTrigger's condition, token for token, for both directions, and B49a's.
{
 const conditions=(source,fn,head)=>{
  const C=H.compile(H.loadSources(source));const f=C.unit.functions.get(fn);assert.ok(f,fn+' in '+(source||'the tree'));
  const body=f[0].body.filter(t=>t.t!=='mark'),out=[];
  for(let i=0;i<body.length;i++){
   if(!(H.isId(body[i],head)&&H.isOp(body[i+1],'(')))continue;
   const close=H.matchClose(body,i+1),inner=body.slice(i+2,close).map(t=>t.v).join(' ');
   if(/RSI_Mode == RSI_Disabled/.test(inner)&&/RSI2_Mode/.test(inner))out.push(inner);
  }
  return out;
 };
 const entry=conditions(undefined,'SignalEntryTrigger','if'),all=conditions(undefined,'GoatSignalAll','return');
 assert.equal(entry.length,2,'SignalEntryTrigger has its buy and sell conditions');
 assert.deepEqual(all,entry,'GoatSignalAll(OP_BUY) and (OP_SELL) are SignalEntryTrigger\'s six terms, token for token');
 assert.deepEqual(conditions('65fde12','SignalEntryTrigger','if'),entry,'and B49a\'s');
 assert.match(entry[0],/RSI_Sig == 0 \)/);assert.match(entry[1],/RSI_Sig == 1 \)/);   // OP_BUY, OP_SELL (macros expanded)
 // Behaviour: every term is read (one term against the direction makes it false), and a range read is both.
 const W=world({EMA_Mode:'Trade_Trend_Range',ADX_Mode:'Trade_Trend',RSI_Mode:'RSI_OverBS'},[]),c=W.ctx;
 const set=(o)=>Object.assign(c,{RSI_Sig:0,EMA_Sig:0,ADX_Sig:0,BB_Sig:0,MACD_Sig:0,RSI2_Sig:0},o);
 set({});assert.equal(c.GoatSignalAll(0),true);assert.equal(c.GoatSignalAll(1),false);
 set({ADX_Sig:1});assert.equal(c.GoatSignalAll(0),false,'ADX against the buy');
 set({RSI_Sig:1,EMA_Sig:6,ADX_Sig:1});assert.equal(c.GoatSignalAll(1),true);assert.equal(c.GoatSignalAll(0),false);
 set({EMA_Sig:6,ADX_Sig:6,RSI_Sig:0});assert.equal(c.GoatSignalAll(0),true,'a range read (OP_BUYSELL) is a buy');
 set({EMA_Sig:6,ADX_Sig:6,RSI_Sig:1});assert.equal(c.GoatSignalAll(1),true,'and a sell');
 assert.equal(c.GoatSignalAll(2),false,'only OP_BUY and OP_SELL have a signal');
 ok();
}

// 2. The opposite exit fires under FastSpeed_Flag=true, at the same tick as in a visual run.
// A long-only single: once it trades, UpdateCurrentSignals' optimization return (both sides traded or disabled) would
// freeze the signals, so without the bypass the exit would fire only in visual runs (the latent bug of section 3).
const FLIP=[[2*H1+35*60,'buy'],[6*H1+5*60,'sell']];   // the buy trend from 02:35, the sell trend from 06:05
const flipInputs={Single_Exit_Opposite:true};
{
 const exits={};
 for(const fastSpeed of [true,false]){
  const W=world(flipInputs,FLIP,{fastSpeed});W.run(flat(H1,9*H1));
  const x=firstExit(W);assert.ok(x,'a single opened (FastSpeed '+fastSpeed+')');
  assert.equal(x.open.type,0,'a buy');assert.equal(x.open.time,at(2*H1+45*60)+7,'on the first M15 bar of the buy trend');
  assert.ok(x.close,'the single is closed (FastSpeed '+fastSpeed+')');
  assert.equal(x.reason,OPP,'by the opposite signal');
  assert.equal(x.close.time,at(6*H1+15*60)+7,'on the first M15 bar of the sell trend (FastSpeed '+fastSpeed+')');
  exits[fastSpeed]=x.close.time;
 }
 assert.equal(exits[true],exits[false],'optimization and visual runs exit on the same tick');
 ok();
}
// The bypass is the single engine's (coordinator ruling on the A1 finding): with or without the opposite exit, a
// FastSpeed single keeps its signals current, so its re-arm (A1: g_GoatSingleArmed re-arms on a false read while the
// position is open) runs in optimization as in visual runs. The grid engine keeps B49a's early return.
{
 for(const exit of [false,true]){
  const W=world({Single_Exit_Opposite:exit},FLIP,{fastSpeed:true});W.run(flat(H1,9*H1));
  assert.equal(W.ctx.EMA_Sig,1,'Single_Exit_Opposite='+exit+': a FastSpeed single\'s signals stay current (EMA_Sig is SELL)');
 }
 const G=world({Engine_Mode:'Engine_Grid',Single_Exit_Opposite:true,Grid_Size:200},FLIP,{fastSpeed:true});G.run(flat(H1,9*H1));
 assert.ok(opens(G).length>=1,'the grid started');assert.equal(G.ctx.EMA_Sig,0,'the grid engine keeps B49a\'s return (EMA_Sig stays BUY)');
 // Re-arm and reopen: the buy signal goes false and comes back while the single is open (03:05-03:35 sell), the time
 // stop closes it at 05:00, and the still-true buy signal reopens it on the next signal check. Without the bypass a
 // FastSpeed single never sees the false read (A1: never re-armed, no reopen), while a visual run reopens.
 const phases=[[2*H1+35*60,'buy'],[3*H1+5*60,'sell'],[3*H1+35*60,'buy']],traces={};
 for(const fastSpeed of [true,false]){
  const W=world({Single_Time_Stop_Bars:3,Single_Time_Stop_TF:'TF_H1'},phases,{fastSpeed});
  W.run(flat(H1,3*H1+20*60));
  assert.equal(W.ctx.EMA_Sig,1,'FastSpeed '+fastSpeed+': the sell read is seen while the single is open');
  W.run(flat(3*H1+20*60,5*H1+30*60));
  const o=opens(W);assert.equal(o.length,2,'FastSpeed '+fastSpeed+': the single reopened after its time stop');
  assert.equal(o[0].time,at(2*H1+45*60)+7);assert.equal(ended(W,TS)[0].time,at(5*H1)+7);
  assert.equal(o[1].time,at(5*H1+60)+7,'reopened on the first signal check after the close');
  traces[fastSpeed]=W.w.trace.map(({comment,...x})=>x);   // the order comment is blank under FastSpeed (OpenPosition)
 }
 assert.deepEqual(traces[true],traces[false],'optimization and visual runs trade the same (comments aside)');
 ok();
}

// 3. No exit while both signals read true (a range mode), then the exit once only the opposite one does.
{
 const phases=[[2*H1+35*60,'buy'],[4*H1+5*60,'neutral'],[7*H1+5*60,'sell']];
 for(const fastSpeed of [true,false]){
  const W=world({Single_Exit_Opposite:true,EMA_Mode:'Trade_Trend_Range'},phases,{fastSpeed});
  W.run(flat(H1,6*H1+30*60));
  assert.equal(W.ctx.EMA_Sig,6,'the range phase: EMA_Sig is OP_BUYSELL');
  assert.ok(W.ctx.GoatSignalAll(0)&&W.ctx.GoatSignalAll(1),'both signals read true');
  assert.equal(W.w.positions.length,1,'and the single is still open, three hours into the range phase');
  W.run(flat(6*H1+30*60,9*H1));
  const x=firstExit(W);assert.ok(x&&x.close,'a single opened and closed');
  assert.equal(x.reason,OPP);
  assert.equal(x.close.time,at(7*H1+15*60)+7,'no exit in the range phase (EMA_Sig BUYSELL: both signals true); the exit comes with the sell trend');
 }
 ok();
}

// 4. Reverse_Seq: a short-only single opens on the buy signal; its own signal is the buy one, so the sell signal exits it.
{
 for(const fastSpeed of [true,false]){
  const W=world({Single_Exit_Opposite:true,Reverse_Seq:true,Mode_Trade:'Short'},FLIP,{fastSpeed});W.run(flat(H1,9*H1));
  const x=firstExit(W);assert.ok(x,'a single opened');
  assert.equal(x.open.type,1,'Reverse_Seq: the buy signal opens a sell');assert.equal(x.open.time,at(2*H1+45*60)+7);
  assert.ok(x.close,'the sell is closed');assert.equal(x.reason,OPP);
  assert.equal(x.close.time,at(6*H1+15*60)+7,'by the sell signal, not at once by the buy signal that opened it');
 }
 ok();
}

// 5. Out of session and paused (ruling 5): the tick skips the RSI and signal refresh while paused, and the exit
// refreshes them itself. (a) Friday after the SESSION_AS end (11:00) with Action_Friday=Action_Pause: InActive, no
// entry check, Sequence_Pause_Close; (b) a news pause (Mode_News=News_Pause).
{
 const FRI=4*DAY,fri=[[FRI+2*H1+35*60,'buy'],[FRI+12*H1+5*60,'sell']];
 for(const fastSpeed of [true,false]){
  const W=world({Single_Exit_Opposite:true,Action_Friday:'Action_Pause',Active_Time_Friday:'SESSION_AS'},fri,{fastSpeed,start:MON+FRI+H1});
  W.run(flat(FRI+H1,FRI+12*H1));
  assert.equal(W.ctx.Sequence_Pause_Close,true,'Friday 12:00: out of session, paused');assert.equal(W.w.positions.length,1,'the single is open');
  W.run(flat(FRI+12*H1,FRI+14*H1));
  const x=firstExit(W);assert.ok(x&&x.close,'the single is closed out of session');assert.equal(x.reason,OPP);
  assert.equal(x.close.time,at(FRI+12*H1+15*60)+7,'on the first M15 bar of the sell trend, out of session');
 }
 // RSI signals: UpdateRSI is the other refresh the paused tick skips (RSI <= 30 buys, >= 70 sells; read at shift 1).
 {
  const rsi=t=>t<FRI+2*H1+35*60?50:(t<FRI+9*H1?25:(t<FRI+12*H1+5*60?50:80));
  const W=H.build(undefined,{tester:true,fastSpeed:true,start:MON+FRI+H1,inputs:{...BASE,EMA_Mode:'Trade_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
   Single_Exit_Opposite:true,Action_Friday:'Action_Pause',Active_Time_Friday:'SESSION_AS'},
   indicator:(name,buffer,shift,w)=>name==='ATR_MA'?0.0010:(name==='RSI'?rsi(w.time-MON):undefined)});
  W.run(flat(FRI+H1,FRI+12*H1));
  assert.equal(W.ctx.Sequence_Pause_Close,true,'out of session, paused');assert.equal(W.w.positions.length,1,'the RSI single is open');
  assert.equal(W.ctx.RSI_Sig,-1,'RSI_Sig neutral before the sell read');
  W.run(flat(FRI+12*H1,FRI+13*H1));
  const close=W.w.trace.find(x=>x.op==='PositionClose');
  assert.ok(close,'the RSI single is closed out of session');assert.equal(close.time,at(FRI+12*H1+5*60)+7,'on the first signal check of the overbought read');
 }
 const W=world({Single_Exit_Opposite:true,Mode_News:'News_Pause'},FLIP,{fastSpeed:true});
 W.w.news=t=>t-MON>=5*H1&&t-MON<8*H1;
 W.run(flat(H1,6*H1));
 assert.equal(W.ctx.Sequence_Pause_News,true,'the news pause holds');
 W.run(flat(6*H1,9*H1));
 const x=firstExit(W);assert.ok(x&&x.close,'a single opened and closed');assert.equal(x.reason,OPP);
 assert.equal(x.close.time,at(6*H1+15*60)+7,'the exit runs inside the news pause');
 ok();
}

// 6. Restart: a live chart opens the single, the terminal restarts, and the adopted single still exits (opposite signal,
// time stop counted from its POSITION_TIME, not from the restart).
function restarted(inputs,phases,openUntil,runTo){
 const first=world(inputs,phases,{tester:false,fastSpeed:false});
 first.run(flat(H1,openUntil));
 assert.equal(first.w.positions.length,1,'one single before the restart');
 const state={positions:JSON.parse(JSON.stringify(first.w.positions)),deals:JSON.parse(JSON.stringify(first.w.deals)),gv:[...first.w.gv],
  next:[first.w.nextTicket,first.w.nextDeal],balance:first.w.balance};
 const second=world(inputs,phases,{tester:false,fastSpeed:false,start:MON+openUntil,
  adopt:(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));
   for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;}});
 const seq=state.positions[0].type===0?second.ctx.Seq_Buy:second.ctx.Seq_Sell;
 assert.ok(seq.Adopted&&seq.Traded,'the single is adopted after the restart');
 assert.equal(seq.TradeLevels[0].ticket,state.positions[0].ticket,'TradeLevels[0] is the single');
 const ticket=state.positions[0].ticket;
 second.run(flat(openUntil,runTo));
 const close=second.w.trace.find(x=>x.op==='PositionClose'&&x.ticket===ticket);
 const end=second.events.find(e=>/Sequence Ended \(/.test(e.text));
 return {first,second,open:state.positions[0],close,reason:end?end.text.match(/Sequence Ended \((.*)\)/)[1]:null};
}
{
 const r=restarted(flipInputs,FLIP,4*H1,9*H1);
 assert.ok(r.close,'the adopted single is closed');assert.equal(r.reason,OPP);
 assert.equal(r.close.time,at(6*H1+15*60)+7,'by the opposite signal, after the restart');
 ok();
}

// 7. The time stop counts bars of Single_Time_Stop_TF from POSITION_TIME. The entry (02:45:07) is mid-H1-bar: the
// third H1 bar after it opens at 05:00, while three hours after it pass at 05:45 (and counted on new bars, at 06:00).
const STOP={Single_Time_Stop_Bars:3,Single_Time_Stop_TF:'TF_H1'};
const BUY_ALL=[[2*H1+35*60,'buy']];
{
 for(const fastSpeed of [true,false]){
  const W=world(STOP,BUY_ALL,{fastSpeed});W.run(flat(H1,8*H1));
  const x=firstExit(W);assert.ok(x,'a single opened');assert.equal(x.open.time,at(2*H1+45*60)+7);
  assert.ok(x.close,'the time stop closed it');assert.equal(x.reason,TS);
  assert.equal(x.close.time,at(5*H1)+7,'on the first tick of the third H1 bar after the entry bar');
 }
 // Bars=1 on D1: the single opened Monday 02:45 closes on Tuesday's first tick, not 24 h later.
 const D=world({Single_Time_Stop_Bars:1,Single_Time_Stop_TF:'TF_D1'},BUY_ALL,{fastSpeed:true});
 D.run(flat(H1,DAY+3*H1));
 const d=firstExit(D);assert.ok(d&&d.close,'the D1 time stop closed it');assert.equal(d.reason,TS);
 assert.equal(d.close.time,at(DAY)+7,'D1: one bar = the next day\'s first tick');
 // Off (Bars=0): nothing closes.
 const O=world({Single_Time_Stop_Bars:0,Single_Time_Stop_TF:'TF_H1'},BUY_ALL,{fastSpeed:true});O.run(flat(H1,8*H1));
 assert.equal(O.w.trace.filter(x=>x.op==='PositionClose').length,0,'Bars=0: no time stop');
 ok();
}
// The time stop survives a restart: the adopted single closes at 05:00 (from its POSITION_TIME), not 3 bars after the
// restart (04:10 -> 07:00).
{
 const r=restarted(STOP,BUY_ALL,4*H1+10*60,8*H1);
 assert.ok(r.close,'the adopted single is closed');assert.equal(r.reason,TS);
 assert.equal(r.open.time,at(2*H1+45*60)+7,'opened before the restart');
 assert.equal(r.close.time,at(5*H1)+7,'three H1 bars after its POSITION_TIME, across the restart');
 ok();
}

// 8. An unknown bar count (iBarShift -1) never closes: the single keeps its stop, and the EA logs it once per position.
{
 const W=world(STOP,BUY_ALL,{fastSpeed:true});
 const shift=W.ctx.iBarShift;let calls=0;W.ctx.iBarShift=(...a)=>{calls++;return -1;};
 W.run(flat(H1,3*H1));
 const x=firstExit(W);assert.ok(x,'a single opened');const sl=W.w.positions[0].sl;
 W.run(flat(3*H1,8*H1));
 assert.ok(calls>=5,'the time stop asked for the bar count on each new H1 bar ('+calls+')');
 assert.equal(W.w.trace.filter(x=>x.op==='PositionClose').length,0,'no close on -1');
 assert.equal(W.w.positions.length,1,'the single is still open');
 assert.equal(W.w.positions[0].sl,sl,'with its stop as it was');
 const logs=W.events.filter(e=>/time stop: no bar for the entry time/.test(e.text));
 assert.equal(logs.length,1,'logged once');
 // Once the count is known again, the time stop resumes.
 W.ctx.iBarShift=shift;W.run(flat(8*H1,9*H1+60));
 assert.ok(W.w.trace.some(x=>x.op==='PositionClose'),'the time stop resumes when the bar count is known');
 assert.equal(ended(W,TS).length,1);
 ok();
}

console.log(JSON.stringify({passed,test:'b50_exits'}));
