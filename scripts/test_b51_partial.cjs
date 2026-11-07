// B51 single partial close and demo gate (docs/b50/B50_ALPHA_DESIGN.md sections 8.3 and 8.4), on the real OnTick path:
// scripts/b50_tick_harness.cjs converts this tree's GoatTickBody, GoatSingleOpen, GoatSinglePartial*, GoatSingleModify*,
// GoatSingleAccountRefusal, OnInit's B50 and B51 blocks and the SEQUENCE methods, and runs them against the modelled
// terminal (EURUSD, 5 digits, spread 10 points, volume minimum and step 0.01).
// The single: a buy at ask 1.10010 (sell: at bid 1.10000) on RSI_OverBS, ATR 0.0010 on the closed bar (0.0030 on the
// forming one), Single_SL_ATR 1.5, Risk 500: 3.33 lots.
// Proves:
// - the partial fires at Single_Partial_ATR x the entry's ATR in favour and not a point before, closes
//   floor(fraction x volume / step) x step, leaves the ticket, SL and TP alone, and fires once, tester and live;
// - illegal volumes (the close or the remainder below the minimum, the close above the maximum, a remainder off the step,
//   no minimum or step, a broker's invalid-volume refusal) skip it for good with one line;
// - a refused close logs one line per attempt and waits 5, 30, then 60 s per ticket; recovery closes once; a true return
//   is not a fill: the retcode must say so and the position's volume must confirm it (TRADE_RETCODE_DONE_PARTIAL counts);
// - a restart, a lost reply, a manual close: the broker's history decides, so nothing closes twice; an unreadable history
//   sends nothing; a restart before the partial still closes once at the frozen ATR;
// - the remainder keeps its break-even, trailing, TP, time stop and broker stop; the ledger books the partial once;
// - Single_Partial_BE moves the stop to the entry at the fill, retries, survives a restart, and never clamps;
// - at 0 the tree trades exactly as B50-alpha (32df4eb); the OnInit refusals;
// - quotes: an empty quote, a last tick over 30 s old and OnInit's own tick trigger nothing (partial, break-even, trailing);
// - a late fill: reconciled below the trigger, never closed twice, and a close never clamps into the whole remainder;
// - the demo gate: a live chart opens only on a connected demo with a login, a server and no read error. A positively read
//   non-demo fails OnInit and removes the EA once; an unreadable account stays loaded with exits running and opens refused,
//   and is adopted once verified; the tester contexts pass; no input is read; the grid is untouched; Random_Direction stays
//   tester-only.
// scripts/test_b51_partial_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail it.
// What it does not prove: compile cleanliness, a real broker's fills, MT5's history timing or a real ACCOUNT_TRADE_MODE
// read. The MetaEditor compile and the PR's Windows and MT5 acceptance list do.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B50_ALPHA='32df4eb';
let passed=0;const ok=()=>passed++;

const MON=Date.UTC(2026,9,5)/1000,H1=3600,T0=MON+2*H1;
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500,Ledger_Mode:'Ledger_PositionJoin'};
const PARTIAL={Single_Partial_ATR:1,Single_Partial_Fraction:0.5};
const PBE0={...PARTIAL,Single_Partial_BE:true};
const live=(wx,inputs=PARTIAL)=>({inputs,tester:false,fastSpeed:false,world:wx});
const indicator=rsi=>(name,buffer,shift,w)=>{
 if(name==='ATR_MA') return shift===1?0.0010:0.0030;
 if(name==='RSI') return typeof rsi==='function'?rsi(w.time):rsi;
 return undefined;};
function ticks(points,step=1){const t=[];for(let k=1;k<points.length;k++){const [a,p]=points[k-1],[b,q]=points[k];for(let s=a;s<b;s+=step)t.push([T0+s,p+(q-p)*(s-a)/(b-a)]);}return t;}
const OPEN=ticks([[-600,1.1000],[0,1.1000]],20);
function world({inputs=PARTIAL,rsi=25,source,tester=true,optimization=false,fastSpeed=true,world:wx={},adopt,start,bid,spread,accountSettled}={}){
 try{return H.build(source,{inputs:{...BASE,...inputs},tester,optimization,fastSpeed,indicator:indicator(rsi),world:wx,adopt,start,bid,spread,accountSettled});}
 catch(e){if(e.initCode!==undefined) assert.fail('OnInit refused a world this test needs: code '+e.initCode);throw e;}
}
const gridWorld=fx=>{try{return H.build(undefined,fx);}catch(e){if(e.initCode!==undefined) assert.fail('OnInit refused the grid: code '+e.initCode);throw e;}};
const closes=W=>W.w.trace.filter(x=>x.op==='PositionClosePartial');
const mods=W=>W.w.trace.filter(x=>x.op==='PositionModify');
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const lines=(W,re)=>W.w.logs.filter(l=>re.test(l));
const field=(line,name)=>{const m=line.match(new RegExp('(?:^|\\s)'+name+'=([^\\s:]+)'));assert.ok(m,'the line carries '+name+': '+line);return m[1];};
const near=(a,b,eps=1e-9)=>Math.abs(a-b)<=eps;
function opened(W,type=0){W.run(OPEN);const s=sends(W);assert.equal(s.length,1,'the single opens');assert.equal(s[0].type,type);return {...W.w.positions[0]};}
const refused=({inputs=PARTIAL,tester=true,optimization=false,fastSpeed=true,world:wx={}}={})=>{
 try{H.build(undefined,{inputs:{...BASE,...inputs},tester,optimization,fastSpeed,indicator:indicator(25),world:wx});return null;}
 catch(e){assert.ok(e.initCode!==undefined,e.message);return e.initCode;}};

// 1. The trigger, the fraction and once only: buy and sell, tester and live.
for(const live of [false,true]){
 const W=world({inputs:{...PARTIAL,Single_TP_R:9},tester:!live,fastSpeed:!live});const p=opened(W);
 assert.ok(near(p.volume,3.33)&&near(p.open,1.10010)&&near(p.sl,1.09860),'3.33 lots at 1.10010, SL 1.09860: '+p.volume);
 W.run(ticks([[0,1.1000],[60,1.10109],[120,1.10109]]));          // 99 points in favour
 assert.equal(closes(W).length,0,'nothing one point short of Single_Partial_ATR x ATR');
 W.run(ticks([[120,1.10110],[180,1.10110]]));
 assert.equal(closes(W).length,1,'at the threshold, once');
 const c=closes(W)[0];assert.equal(c.time,T0+120,'on the first check at the threshold');assert.equal(c.ticket,p.ticket);
 assert.ok(near(c.volume,1.66),'floor(3.33 x 0.5 / 0.01) x 0.01 = 1.66, never rounded up: '+c.volume);
 const q=W.w.positions[0];assert.equal(W.w.positions.length,1);assert.equal(q.ticket,p.ticket,'the ticket stays');
 assert.ok(near(q.volume,1.67),'the remainder: '+q.volume);assert.equal(q.sl,p.sl,'the SL stays');assert.equal(q.tp,p.tp,'the TP stays');
 assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,1.67),'the level holds the remainder');assert.equal(W.ctx.Seq_Buy.Active,true,'the single runs on');
 assert.equal(lines(W,/Single partial close: ticket=/).length,1,'one line');assert.equal(W.ctx.Pclosed,1,'the run counts it');
 W.run(ticks([[180,1.10110],[300,1.1050],[500,1.1000],[800,1.1060],[900,1.1060]]));
 assert.equal(closes(W).length,1,'once per position: never again, whatever the price does');
 assert.equal(lines(W,/already done/).length,0,'its own fill needs no second look');
 ok();
}
{
 // The sell: favour is open - ask, so the spread counts.
 const S=world({inputs:PARTIAL,rsi:80});const q=opened(S,1);assert.ok(near(q.open,1.10000));
 S.run(ticks([[0,1.1000],[60,1.09891],[120,1.09891]]));assert.equal(closes(S).length,0,'ask 1.09901: 99 points');
 S.run(ticks([[120,1.09890],[180,1.09890]]));assert.equal(closes(S).length,1,'ask 1.09900: 100 points');assert.ok(near(closes(S)[0].volume,1.66));
 // A fractional trigger (1.035 ATR = 103.5 points) needs 104 points; the entry's ATR, not the forming bar's (300 points).
 const F=world({inputs:{Single_Partial_ATR:1.035,Single_Partial_Fraction:0.5}});opened(F);
 F.run(ticks([[0,1.1000],[30,1.10113],[90,1.10113]]));assert.equal(closes(F).length,0,'103 points < 103.5');
 F.run(ticks([[90,1.10114],[120,1.10114]]));assert.equal(closes(F).length,1,'104 points');
 // Another stop multiple, the same ATR: 2 ATR is 200 points under Single_SL_ATR 3 too.
 const A=world({inputs:{Single_SL_ATR:3,Single_Partial_ATR:2,Single_Partial_Fraction:0.5}});opened(A);
 A.run(ticks([[0,1.1000],[30,1.10209],[60,1.10209]]));assert.equal(closes(A).length,0,'199 points');
 A.run(ticks([[60,1.10210],[90,1.10210]]));assert.equal(closes(A).length,1,'200 points: Size_SL / Single_SL_ATR');
 ok();
}

// 2. Legal volumes: illegal is skipped for good, with one line and no attempt; legal volumes close exactly.
{
 const skip=(what,inputs,change,re)=>{
  const W=world({inputs:{...PARTIAL,...inputs}});const p=opened(W);Object.assign(W.w,change);
  W.run(ticks([[0,1.10110],[400,1.1050]]));
  assert.equal(closes(W).length,0,what+': no attempt');
  const l=lines(W,/Single partial close skipped/);assert.equal(l.length,1,what+': one line, never one per check');assert.match(l[0],re);
  assert.equal(field(l[0],'ticket'),String(p.ticket),what);
  assert.ok(near(W.w.positions[0].volume,3.33),what+': the position keeps its volume');
  // It stays skipped when the volumes become legal again: never an open-ended retry.
  Object.assign(W.w,{volumeMin:0.01,volumeStep:0.01,volumeMax:100});W.run(ticks([[400,1.1050],[500,1.1050]]));assert.equal(closes(W).length,0,what+': skipped for this position');
  ok();
 };
 skip('the close below the minimum',{},{volumeMin:2},/close is below the volume minimum/);
 skip('the remainder below the minimum',{Single_Partial_Fraction:0.9},{volumeMin:1},/remainder is below the volume minimum/);
 skip('the close above the maximum',{},{volumeMax:1},/close is above the volume maximum/);
 skip('a remainder off the step',{},{volumeStep:0.5},/not a multiple of the volume step/);
 skip('no volume step',{},{volumeStep:0},/no volume minimum or step/);
 skip('no volume minimum',{},{volumeMin:0},/no volume minimum or step/);
 // The smallest legal split, and values that binary rounding could tip: floored, never over the fraction.
 for(const [lots,f,cut,rest] of [[0.03,0.5,0.01,0.02],[0.10,0.3,0.03,0.07],[0.10,0.7,0.07,0.03],[0.29,0.5,0.14,0.15],[1.00,0.1,0.10,0.90]]){
  const W=world({inputs:{Mode_Lots:'FixedLots',Lots_Input:lots,Single_Partial_ATR:1,Single_Partial_Fraction:f}});opened(W);
  W.run(ticks([[0,1.10110],[30,1.10110]]));
  assert.equal(closes(W).length,1,lots+' x '+f);assert.ok(near(closes(W)[0].volume,cut,1e-9),lots+' x '+f+' closes '+closes(W)[0].volume);
  assert.ok(near(W.w.positions[0].volume,rest,1e-9),lots+' x '+f+' leaves '+W.w.positions[0].volume);
 }
 // 0.01 lots has no legal split.
 const T=world({inputs:{Mode_Lots:'FixedLots',Lots_Input:0.01,...PARTIAL}});opened(T);T.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(T).length,0);assert.equal(lines(T,/skipped/).length,1);
 // The broker refuses the volume after all: one attempt, skipped.
 const B=world({world:{partialRetcode:10014,rejectPartial:()=>true}});opened(B);B.run(ticks([[0,1.10110],[300,1.10110]]));
 assert.equal(closes(B).length,1,'TRADE_RETCODE_INVALID_VOLUME: one attempt');assert.match(lines(B,/skipped/)[0],/retcode=10014/);
 assert.equal(lines(B,/partial close failed/).length,0);
 ok();
}

// 3. A refused close: one line per attempt, 5 s, 30 s, then 60 s steady; a recovery closes once.
{
 const W=world({world:{partialRetcode:10018,rejectPartial:()=>true}});const p=opened(W);
 W.w.stopsLevel=7;W.w.freezeLevel=9;W.run(ticks([[0,1.10110],[400,1.10110]]));
 const times=closes(W).map(x=>x.time-T0);
 assert.deepEqual(times,[0,5,35,95,155,215,275,335,395],'attempts at '+times.join(','));
 const f=lines(W,/Single partial close failed/);assert.equal(f.length,times.length,'one line per attempt, none inside a wait');
 assert.deepEqual(f.map(l=>Number(field(l,'consecutive'))),times.map((_,i)=>i+1));
 assert.deepEqual(f.slice(0,4).map(l=>field(l,'backoff')),['5s','30s','60s','60s'],'from the first failure');
 for(const [k,v] of [['ticket',String(p.ticket)],['bid','1.10110'],['ask','1.10120'],['volume','3.33'],['close','1.66'],['retcode','10018']]) assert.equal(field(f[0],k),v,k);
 assert.equal(W.ctx.PcloseErrors,times.length,'the run counts each failure');assert.equal(W.ctx.Pclosed,times.length,'and each attempt');
 assert.ok(near(W.w.positions[0].volume,3.33),'nothing filled');
 // It heals: one more attempt, one close, no more lines, and the count clears.
 W.w.rejectPartial=null;W.run(ticks([[400,1.10110],[600,1.10110]]));
 assert.equal(closes(W).length,times.length+1,'one attempt after it heals');assert.ok(near(W.w.positions[0].volume,1.67));
 assert.equal(lines(W,/Single partial close failed/).length,f.length);assert.equal(lines(W,/Single partial close: ticket=/).length,1);
 assert.equal(W.ctx.g_GoatPartialFails[0],0,'a fill clears the count');assert.equal(W.ctx.g_GoatPartialNext[0],0,'and the wait');
 // A close that took the whole position (a broker's clamp): filled, and the sequence ends by its transaction.
 const Whole=world({world:{partialFilled:(t,v,wd)=>wd.positions[0].volume}});opened(Whole);Whole.run([[T0,1.10110],[T0+1,1.10110]]);
 assert.equal(Whole.w.positions.length,0);assert.equal(Whole.ctx.g_GoatPartialState[0],2,'done');assert.equal(Whole.ctx.PcloseErrors,0,'no failure');assert.equal(Whole.ctx.Seq_Buy.Active,false);
 // No retry once the price has left: the wait passes, and nothing is due.
 const L=world({world:{rejectPartial:()=>true}});opened(L);L.run(ticks([[0,1.10110],[3,1.10110],[4,1.1000],[100,1.1000]]));
 assert.equal(closes(L).length,1,'retried only while due');
 ok();
}
// A true return is not a fill: only the retcode says so, and the position's volume confirms it (review of GOAT-EA#287).
for(const retcode of [10004,10006,10018,10021,10025]){
 const W=world({inputs:PBE0,world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:retcode}});const p=opened(W);
 W.run(ticks([[0,1.10110],[100,1.10110]]));
 assert.deepEqual(closes(W).map(x=>x.time-T0),[0,5,35,95],retcode+': the failure path and its back-off');
 assert.equal(lines(W,/Single partial close failed/).length,4,retcode+': one line per attempt');assert.equal(field(lines(W,/Single partial close failed/)[0],'retcode'),String(retcode));
 assert.equal(lines(W,/Single partial close: ticket=/).length,0,retcode+': no success line');
 assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),false,retcode+': the once-only state is not set');assert.equal(mods(W).length,0,retcode+': no break-even without a fill');
 assert.ok(near(W.w.positions[0].volume,3.33));assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,3.33),retcode+': the level keeps the volume');
 W.w.rejectPartial=null;W.run(ticks([[100,1.10110],[200,1.10110]]));
 assert.equal(closes(W).length,5,retcode+': it heals and closes once');assert.ok(near(W.w.positions[0].volume,1.67));assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),true);assert.equal(W.w.positions[0].sl,p.open);
 ok();
}
{
 // The server says DONE, the position's volume has not moved: not confirmed and not a failure. A read that later shows the fill
 // ends it with no second send; a volume that never moves is retried after the long wait.
 const W=world({inputs:PBE0,world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10009}});const p=opened(W);
 W.run(ticks([[0,1.10110],[3,1.10110]]));
 assert.equal(closes(W).length,1);assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),false,'DONE without less volume is not done');assert.equal(mods(W).length,0);
 assert.equal(W.ctx.PcloseErrors,0,'a lagging view is no failure');assert.equal(lines(W,/partial close failed/).length,0);assert.equal(lines(W,/partial close unconfirmed/).length,1);
 W.w.positions[0].volume=1.67;W.run(ticks([[3,1.10110],[10,1.10110]]));
 assert.equal(closes(W).length,1,'the fill shows up: no second send');assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),true,'recognised within seconds, inside the 120 s wait');assert.equal(lines(W,/already done/).length,1);assert.equal(W.w.positions[0].sl,p.open,'and the stop moves');
 // Refused at 0 s, a timeout at 5 s, the fill visible at 7 s: the read timer restarts at each failed send, so the stop moves in seconds.
 const TO=world({inputs:PBE0,world:{rejectPartial:()=>true,partialRetcode:10006}});const tp=opened(TO);TO.run([[T0,1.10110]]);TO.w.partialRetcode=10012;TO.run(ticks([[1,1.10110],[7,1.10110]]));
 assert.deepEqual(closes(TO).map(x=>x.time-T0),[0,5],'refused, then a timeout');TO.w.positions[0].volume=1.67;TO.run(ticks([[7,1.10110],[15,1.10110]]));
 assert.equal(closes(TO).length,2,'no third send');assert.equal(TO.ctx.GoatSinglePartialDone(tp.ticket),true,'recognised within seconds');assert.equal(TO.w.positions[0].sl,tp.open,'the stop moved, not at +65 s');
 // A read during the wait never sends: nothing goes before the 120 s, every 5 s it only reads.
 let rd=0;const RW=world({world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10009}});opened(RW);RW.run([[T0,1.10110]]);RW.w.rejectHistory=()=>{rd++;return false;};RW.run(ticks([[1,1.10110],[100,1.10110]]));
 assert.equal(closes(RW).length,1);assert.ok(rd>=18&&rd<=21,'a read every 5 s in the wait: '+rd);
 const N=world({world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10009}});opened(N);N.run(ticks([[0,1.10110],[130,1.10110]]));
 assert.deepEqual(closes(N).map(x=>x.time-T0),[0,120],'it never filled: retried after the long wait');
 // Every answer that leaves the outcome open waits 120 s, returned true or false.
 for(const [ret,yes] of [[10008,true],[10011,false],[10012,false],[10010,true],[0,false]]){
  const U=world({world:{rejectPartial:()=>true,partialReturnsTrue:yes,partialRetcode:ret}});opened(U);U.run(ticks([[0,1.10110],[130,1.10110]]));
  assert.deepEqual(closes(U).map(x=>x.time-T0),[0,120],ret+': the long wait');assert.equal(field(lines(U,/partial close unconfirmed/)[0],'backoff'),'120s');
 }
 // TRADE_RETCODE_DONE_PARTIAL: less than asked, still the one partial; the real figures are logged and kept.
 const D=world({inputs:PBE0,world:{partialFilled:()=>0.5}});const q=opened(D);D.run(ticks([[0,1.10110],[300,1.1050]]));
 assert.equal(closes(D).length,1,'a partial fill is the partial: never a second close');assert.ok(near(closes(D)[0].volume,1.66),'asked 1.66');
 assert.ok(near(D.w.positions[0].volume,2.83),'filled 0.50');assert.ok(near(D.ctx.Seq_Buy.TradeLevels[0].lots,2.83));assert.equal(D.ctx.GoatSinglePartialDone(q.ticket),true);assert.equal(D.w.positions[0].sl,q.open,'the break-even follows');
 assert.equal(lines(D,/Single partial close: ticket=/).length,1,'a partial fill logs its one line');const l=lines(D,/Single partial close: ticket=/)[0];assert.equal(field(l,'closed'),'0.50');assert.equal(field(l,'remainder'),'2.83');assert.equal(field(l,'retcode'),'10010');
 // An invalid-volume rejection that returns true is still skipped.
 const B=world({world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10014}});opened(B);B.run(ticks([[0,1.10110],[300,1.10110]]));assert.equal(closes(B).length,1);assert.equal(lines(B,/skipped/).length,1);
 ok();
}
// Two tickets keep their own count and wait; a refused buy does not hold the sell.
{
 const W=world({rsi:50,spread:0,world:{}});W.run(OPEN);
 assert.equal(W.ctx.GoatSingleOpen(W.ctx.Seq_Buy,W.w.ask),true);
 W.w.time+=1;assert.equal(W.ctx.GoatSingleOpen(W.ctx.Seq_Sell,W.w.bid),true);
 const buy=W.ctx.Seq_Buy.TradeLevels[0].ticket,sell=W.ctx.Seq_Sell.TradeLevels[0].ticket;
 W.w.rejectPartial=t=>t===buy;
 W.run([[T0,1.1010]]);                                            // the buy is due and refused: it waits 5 s
 assert.deepEqual(closes(W).map(x=>x.ticket),[buy]);
 W.run([[T0+1,1.0990]]);                                          // the sell is due one second later, inside the buy's wait
 assert.deepEqual(closes(W).map(x=>x.ticket),[buy,sell],'the sell closes at once');
 assert.ok(near(W.w.positions.find(p=>p.ticket===sell).volume,1.67));
 W.run([[T0+2,1.1010],[T0+4,1.1010]]);assert.equal(closes(W).length,2,'the buy still waits');
 W.w.rejectPartial=null;W.run([[T0+5,1.1010],[T0+6,1.1010]]);
 assert.deepEqual(closes(W).map(x=>x.ticket),[buy,sell,buy],'its own wait ends');assert.ok(near(W.w.positions.find(p=>p.ticket===buy).volume,1.67));
 ok();
}
// Slots: more positions in turn than slots, each with its own partial (a slot whose position is gone is reused).
{
 const W=world({rsi:50,spread:0});W.run(OPEN);let t=T0;
 for(let k=0;k<12;k++){
  W.w.time=t;assert.equal(W.ctx.GoatSingleOpen(W.ctx.Seq_Buy,W.w.ask),true,'position '+k);
  const tk=W.ctx.Seq_Buy.TradeLevels[0].ticket;
  W.run([[t,1.1000]]);assert.equal(closes(W).filter(x=>x.ticket===tk).length,0,'position '+k+': at its entry, nothing is due');
  W.run([[t+1,1.1010],[t+2,1.1010]]);assert.equal(closes(W).filter(x=>x.ticket===tk).length,1,'position '+k+' has its partial');
  W.ctx.Seq_Buy.CloseSequencePositions('test');W.pump();W.run([[t+3,1.1000]]);assert.equal(W.w.positions.length,0);t+=5;
 }
 assert.equal(closes(W).length,12);
 ok();
}

// 4. Once only across a restart, a lost reply and a close made elsewhere: the broker's history decides.
function restart(first,inputs,extra={}){
 const state={positions:JSON.parse(JSON.stringify(first.w.positions)),deals:JSON.parse(JSON.stringify(first.w.deals)),gv:[...first.w.gv].filter(([k])=>!(extra.dropSizes&&/_B_SL$/.test(k))),
  next:[first.w.nextTicket,first.w.nextDeal],balance:first.w.balance,time:first.w.time,bid:first.w.bid};
 return world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,world:extra.world||{},
  adopt:(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));
   for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;}});
}
{
 // After the partial: never again, at any price.
 const a=world({tester:false,fastSpeed:false});opened(a);a.run(ticks([[0,1.10110],[30,1.10110]]));assert.equal(closes(a).length,1);
 const W=restart(a,PARTIAL);assert.equal(W.ctx.Seq_Buy.AdoptSizes,true);assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,1.67),'adopted with the remainder');
 W.run(ticks([[31,1.10110],[300,1.1050],[400,1.1050]]));
 assert.equal(closes(W).length,0,'no second close after a restart');assert.ok(near(W.w.positions[0].volume,1.67));
 assert.equal(lines(W,/already done/).length,1,'one line');
 // A second restart is the same.
 const X=restart(W,PARTIAL);X.run(ticks([[401,1.1050],[500,1.1050]]));assert.equal(closes(X).length,0);
 // Before the partial: it closes once, from the frozen ATR (a forming-bar read would need 300 points).
 const b=world({tester:false,fastSpeed:false});opened(b);b.run(ticks([[0,1.1005],[30,1.1005]]));assert.equal(closes(b).length,0);
 const Y=restart(b,PARTIAL);Y.run(ticks([[31,1.10109],[60,1.10109]]));assert.equal(closes(Y).length,0,'99 points');
 Y.run(ticks([[60,1.10110],[90,1.10110],[300,1.1050]]));assert.equal(closes(Y).length,1,'100 points, once');assert.ok(near(closes(Y)[0].volume,1.66));
 // No frozen sizes: no entry ATR, so it is left alone (as the break-even and trailing).
 const N=restart(b,PARTIAL,{dropSizes:true});assert.equal(N.ctx.Seq_Buy.AdoptSizes,false);
 N.ctx.Seq_Buy.Size_SL=0.0015;N.run(ticks([[31,1.1050],[100,1.1050]]));assert.equal(closes(N).length,0,'an adopted single without its sizes keeps its volume');
 ok();
}
{
 // A fill whose reply never came: the retry reads the history and sends nothing.
 const W=world({world:{lostPartialReply:()=>true}});opened(W);
 W.run(ticks([[0,1.10110],[130,1.10110]]));
 assert.equal(closes(W).length,1,'one send');assert.ok(near(W.w.positions[0].volume,1.67),'it filled once');
 assert.equal(lines(W,/already done/).length,1);assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,1.67),'the level follows');
 // A close made elsewhere, with its deal not in the history yet: the volume alone shows it.
 const V=world({});opened(V);V.w.positions[0].volume=2;V.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(V).length,0,'less volume than its entry: it has had one');assert.equal(lines(V,/already done/).length,1);
 // The same read below the trigger, in a new run (the slot empty): the volume alone marks it done, and the stop follows.
 const VB=world({inputs:PBE0});const vb=opened(VB);VB.ctx.g_GoatPartialState[0]=0;VB.w.positions[0].volume=2;VB.run([[T0+1,1.1005]]);
 assert.equal(VB.ctx.GoatSinglePartialDone(vb.ticket),true,'less volume than its entry, below the trigger');assert.equal(VB.w.positions[0].sl,vb.open);
 // A close made elsewhere, with its exit deal in the history.
 const E=world({});opened(E);E.w.deals.push({...E.w.deals[0],ticket:1,entry:1,volume:0.5});E.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(E).length,0,'an exit deal: it has had one');
 const O=world({});opened(O);O.w.deals.push({...O.w.deals[0],ticket:1,entry:3,volume:0.5});O.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(O).length,0,'a close-by counts as an exit deal');
 ok();
}
{
 // An unreadable history sends nothing: one line, then it closes once it can read.
 const W=world({world:{rejectHistory:()=>true}});opened(W);W.run(ticks([[0,1.10110],[100,1.10110]]));
 assert.equal(closes(W).length,0,'no read, no close');const held=lines(W,/partial close held/);assert.equal(held.length,1,'one line');
 W.w.rejectHistory=null;W.run(ticks([[100,1.10110],[130,1.10110]]));assert.equal(closes(W).length,1,'once it can read');
 // Below the trigger an unreadable history is silent.
 const Q=world({world:{rejectHistory:()=>true}});opened(Q);Q.run(ticks([[0,1.1005],[50,1.1005]]));assert.equal(lines(Q,/partial close held/).length,0);
 // No entry deal in the loaded history yet: unknown too.
 const D=world({});opened(D);const deals=D.w.deals.splice(0);D.run(ticks([[0,1.10110],[50,1.10110]]));
 assert.equal(closes(D).length,0,'no entry deal: unknown');assert.equal(lines(D,/partial close held/).length,1);
 D.w.deals.push(...deals);D.run(ticks([[50,1.10110],[60,1.10110]]));assert.equal(closes(D).length,1);
 // The history is read before every send, not only the first: a fill seen between two attempts stops the second.
 const R=world({world:{rejectPartial:()=>true}});opened(R);R.run(ticks([[0,1.10110],[3,1.10110]]));assert.equal(closes(R).length,1);
 R.w.positions[0].volume=2;R.run(ticks([[3,1.10110],[60,1.10110]]));assert.equal(closes(R).length,1,'no second send');
 // It is read once per position while nothing is due, not on every check.
 let reads=0;const C=world({world:{rejectHistory:()=>{reads++;return false;}}});opened(C);assert.equal(reads,1,'one read of a new position');C.run(ticks([[0,1.1005],[100,1.1005]]));assert.equal(reads,1,'and none while nothing is due');
 ok();
}

// 5. The remainder: its break-even and trailing carry on, its TP, its stop, its time stop; the ledger books the partial once.
{
 const W=world({inputs:{...PARTIAL,Single_BE_ATR:2,Single_Trail_Start_ATR:3,Single_Trail_ATR:0.5,Single_TP_R:30}});const p=opened(W);
 W.run(ticks([[0,1.10110],[30,1.10110]]));assert.equal(closes(W).length,1);assert.equal(mods(W).length,0,'the partial moves no stop');
 W.run(ticks([[30,1.10210],[60,1.10210]]));assert.ok(mods(W).length>=1,'break-even at 2 ATR');assert.equal(mods(W)[0].sl,p.open,'break-even on the remainder at 2 ATR');
 W.run(ticks([[60,1.10210],[300,1.1045],[310,1.1045]]));const m=mods(W);assert.ok(m.length>=5,'the trailing carries on');
 for(const x of m) assert.ok(near(x.tp,p.tp),'the TP stays');assert.ok(near(W.w.positions[0].volume,1.67),'a modify leaves the volume');
 W.run(ticks([[310,1.1045],[400,1.1030],[500,1.1030]]));
 const stop=W.w.trace.find(x=>x.op==='BrokerStop');assert.ok(stop,'the trailed stop');assert.ok(near(stop.volume??1.67,1.67),'the broker closes the remainder');
 assert.equal(W.ctx.Seq_Buy.Active,false,'the sequence ends on the remainder\'s stop');assert.equal(closes(W).length,1);
 // UpdateLockTPSL still runs once per single: a partial never re-derives the stop.
 const U=world({inputs:{...PARTIAL,Single_BE_ATR:2}});const b=U.ctx.Seq_Buy;let calls=0;const orig=b.UpdateLockTPSL.bind(b);b.UpdateLockTPSL=(...a)=>{calls++;return orig(...a);};
 U.run([...OPEN,...ticks([[0,1.1030],[100,1.1030]])]);assert.equal(closes(U).length,1);assert.equal(calls,1);
 // The next episode has its own partial.
 const N=world({rsi:t=>(t<T0+1200||t>=T0+1800)?25:50,inputs:{...PARTIAL,Single_BE_ATR:1}});opened(N);
 N.run(ticks([[0,1.1012],[60,1.1012],[300,1.0990],[1200,1.0990],[1800,1.0990],[2100,1.1010],[2400,1.1010]]));
 assert.equal(sends(N).length,2,'two singles');const tk=closes(N).map(x=>x.ticket);assert.equal(new Set(tk).size,2,'each with its own partial');assert.equal(tk.length,2);
 // The time stop and the opposite exit close the remainder.
 const S=world({inputs:{...PARTIAL,Single_Time_Stop_Bars:1,Single_Time_Stop_TF:'TF_H1'}});opened(S);S.run(ticks([[0,1.1012],[60,1.1012],[3700,1.1012]],20));
 const closed=S.w.trace.filter(x=>x.op==='PositionClose');assert.equal(closed.length,1,'the time stop');assert.ok(near(closed[0].volume,1.67),'closes the remainder');
 assert.equal(closes(S).length,1);
 ok();
}
{
 // Ledger_PositionJoin books the partial's profit once (the close helper, then the transaction); MLPS reads it.
 const J=world({});opened(J);const before=J.ctx.Seq_Buy.SequenceRealizedPL;
 J.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.ok(near(J.ctx.Seq_Buy.SequenceRealizedPL-before,166,1e-6),'1.66 lots x 100 points at 1 USD: '+(J.ctx.Seq_Buy.SequenceRealizedPL-before));
 assert.equal(J.w.deals.filter(d=>d.entry===1)[0].magic,J.ctx.MAGIC1,'the close carries MAGIC1');
 assert.ok(near(J.ctx.Seq_Buy.CurrentSequencePL(),166+167,1e-6),'realized + the remainder\'s open P/L');
 // The dashboard counts exit deals: the partial and the remainder's exit are two, and each deal's P/L counts once.
 const D=world({inputs:{...PARTIAL,Single_TP_R:9},tester:false,fastSpeed:false});opened(D);const count0=D.ctx.DashboardBusClosedTradesTotal,pl0=D.ctx.DashboardBusClosedPLTotal;
 D.run(ticks([[0,1.10110],[30,1.10110]]));assert.equal(D.ctx.DashboardBusClosedTradesTotal-count0,1,'the partial is one exit deal, once');
 assert.ok(near(D.ctx.DashboardBusClosedPLTotal-pl0,166,1e-6),'its P/L once');
 D.ctx.Seq_Buy.CloseSequencePositions('test');D.pump();assert.equal(D.ctx.DashboardBusClosedTradesTotal-count0,2,'the remainder\'s exit is the second');
 ok();
}

// 6. Single_Partial_BE: the remainder's stop goes to the entry when the partial fills, and never clamps.
const PBE={...PARTIAL,Single_Partial_BE:true};
{
 const W=world({inputs:{...PBE,Single_TP_R:9}});const p=opened(W);
 W.run(ticks([[0,1.10109],[30,1.10109]]));assert.equal(mods(W).length,0,'nothing before the fill');
 W.run(ticks([[30,1.10110],[60,1.10110]]));assert.equal(mods(W).length,1,'once');
 const i=W.w.trace.findIndex(x=>x.op==='PositionClosePartial'),j=W.w.trace.findIndex(x=>x.op==='PositionModify');assert.ok(i>=0&&j===i+1,'the partial, then the stop');assert.equal(W.w.trace[j].time,W.w.trace[i].time,'in one check');
 assert.equal(mods(W)[0].sl,p.open,'the entry exactly');assert.ok(near(mods(W)[0].tp,p.tp),'the TP stays');
 assert.equal(W.ctx.Seq_Buy.Level_SL,p.open);
 W.run(ticks([[60,1.1000],[200,1.1030],[300,1.1030]]));assert.ok(W.w.trace.some(x=>x.op==='BrokerStop'),'the price comes back to the entry: stopped there');
 assert.equal(mods(W).length,1);
 // Off: the partial alone moves nothing, with or without the rest of GoatSingleModify on.
 const O=world({});opened(O);O.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(closes(O).length,1);assert.equal(mods(O).length,0,'Single_Partial_BE off');
 const O2=world({inputs:{...PARTIAL,Single_BE_ATR:9}});opened(O2);O2.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(closes(O2).length,1);assert.equal(mods(O2).length,0,'Single_Partial_BE off, Single_BE_ATR on');
 // The sell.
 const S=world({inputs:PBE,rsi:80});const q=opened(S,1);S.run(ticks([[0,1.09890],[30,1.09890]]));assert.equal(closes(S).length,1);assert.equal(mods(S).length,1,'the sell moves once');assert.equal(mods(S)[0].sl,q.open,'the sell\'s entry');
 // A skipped partial moves no stop: it did not fill.
 const K=world({inputs:PBE});opened(K);K.w.volumeMin=2;K.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(closes(K).length,0);assert.equal(mods(K).length,0,'no fill, no move');
 // A refused modify retries under its back-off; a failed close moves nothing.
 const R=world({inputs:PBE});const r=opened(R);R.w.rejectModify=()=>true;R.run(ticks([[0,1.1012],[10,1.1012]]));assert.ok(mods(R).length>=2,'it retries');
 R.w.rejectModify=null;R.run(ticks([[10,1.1012],[80,1.1012]]));assert.equal(R.w.positions[0].sl,r.open,'then it moves');
 const F=world({inputs:PBE,world:{rejectPartial:()=>true}});opened(F);F.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(mods(F).length,0,'no fill, no move');
 ok();
}
{
 // Never clamped: the stops level is above the trigger, so the entry is not yet a legal stop. It waits, then goes exactly.
 const W=world({inputs:PBE});const p=opened(W);W.w.stopsLevel=150;
 W.run(ticks([[0,1.10110],[30,1.10110],[60,1.10159],[90,1.10159]]));assert.equal(closes(W).length,1);assert.equal(mods(W).length,0,'149 points: the entry is not legal, nothing is sent');
 W.run(ticks([[90,1.10160],[120,1.10160]]));assert.equal(mods(W).length,1,'150 points: it moves');assert.equal(mods(W)[0].sl,p.open,'150 points: the entry exactly');
 // The sell: the entry must clear ask + the level.
 const S=world({inputs:PBE,rsi:80});const q=opened(S,1);S.w.stopsLevel=150;
 S.run(ticks([[0,1.09890],[30,1.09890],[60,1.09841],[90,1.09841]]));assert.equal(closes(S).length,1);assert.equal(mods(S).length,0,'149 points');
 S.run(ticks([[90,1.09840],[120,1.09840]]));assert.equal(mods(S).length,1,'150 points: it moves');assert.equal(mods(S)[0].sl,q.open,'150 points');
 // After a reversal under the entry, a stop cannot go to the entry: no clamped stop just under the price.
 const V=world({inputs:PBE});const v=opened(V);V.w.rejectModify=()=>true;V.run(ticks([[0,1.1012],[2,1.1012]]));const n=mods(V).length;
 V.w.rejectModify=null;V.run(ticks([[2,1.1000],[100,1.1000]]));assert.equal(mods(V).length,n,'no move while the entry is not legal');assert.equal(V.w.positions[0].sl,v.sl);
 V.run(ticks([[100,1.1005],[130,1.1005]]));assert.equal(V.w.positions[0].sl,v.open,'back in favour: the entry');
 // With trailing, the better stop wins; a stop already past the entry never goes back.
 const T=world({inputs:{...PBE,Single_Trail_Start_ATR:0,Single_Trail_ATR:0.2}});const t=opened(T);T.run(ticks([[0,1.1020],[100,1.1020],[150,1.1019],[200,1.1019]]));
 for(const x of mods(T)) assert.ok(x.sl>=t.sl);assert.ok(T.w.positions[0].sl>t.open,'the trailed stop stays above the entry: '+T.w.positions[0].sl);
 // A restart between the fill and the move: the broker's history brings the move back, below the trigger too.
 const A=world({inputs:PBE,tester:false,fastSpeed:false,world:{rejectModify:()=>true}});const a=opened(A);A.run(ticks([[0,1.10110],[3,1.10110]]));
 assert.equal(closes(A).length,1);assert.equal(A.w.positions[0].sl,a.sl,'the move failed');
 const B=restart(A,PBE);B.run(ticks([[4,1.1005],[20,1.1005]]));assert.equal(closes(B).length,0);assert.equal(B.w.positions[0].sl,a.open,'moved after the restart');
 // After a move, a restart sends nothing more.
 const D=restart(B,PBE);D.run(ticks([[21,1.1005],[60,1.1005]]));assert.equal(mods(D).length,0);assert.equal(closes(D).length,0);
 ok();
}

// 7. Off at 0: the tree trades as B50-alpha, partial never runs, no history read for it. tester and live.
for(const live of [false,true]){
 const run=source=>{const W=world({source,inputs:{Single_TP_R:9},tester:!live,fastSpeed:!live});W.run([...OPEN,...ticks([[0,1.1030],[400,1.1060],[800,1.0950],[900,1.0950]],5)]);return W;};
 const tree=run(undefined),base=run(B50_ALPHA);
 assert.deepEqual(tree.w.trace,base.w.trace,'flags off: the trace is B50-alpha\'s');assert.equal(closes(tree).length,0);assert.equal(mods(tree).length,0);
 assert.ok(sends(tree).length>=1);
 ok();
}
{
 let reads=0;const W=world({inputs:{},world:{rejectHistory:()=>{reads++;return false;}}});opened(W);reads=0;W.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(reads,0,'off: no read');
 // The grid engine, default inputs: no partial, whatever the price.
 const G=gridWorld({inputs:{EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70},tester:true,fastSpeed:true,indicator:indicator(25)});
 G.run([...OPEN,...ticks([[0,1.1030],[60,1.1030]])]);assert.equal(closes(G).length,0);
 ok();
}

// 8. OnInit refusals (INIT_PARAMETERS_INCORRECT).
{
 const P={...BASE};
 for(const [name,inputs] of [['a negative trigger',{Single_Partial_ATR:-1,Single_Partial_Fraction:0.5}],['a negative fraction',{Single_Partial_ATR:1,Single_Partial_Fraction:-0.5}],
  ['a negative trigger alone',{Single_Partial_ATR:-1}],['a negative fraction alone',{Single_Partial_Fraction:-0.5}],['both negative',{Single_Partial_ATR:-1,Single_Partial_Fraction:-0.5}],
  ['a fraction of 1',{Single_Partial_ATR:1,Single_Partial_Fraction:1}],['a fraction above 1',{Single_Partial_ATR:1,Single_Partial_Fraction:1.5}],
  ['the partial under Ledger_Legacy',{...PARTIAL,Ledger_Mode:'Ledger_Legacy'}],
  ['a trigger without a fraction',{Single_Partial_ATR:1}],['a fraction without a trigger',{Single_Partial_Fraction:0.5}],
  ['Single_Partial_BE without a trigger',{Single_Partial_BE:true}],
  ['the grid engine with the partial',{Engine_Mode:'Engine_Grid',Single_Partial_ATR:1,Single_Partial_Fraction:0.5}],
  ['the grid engine with Single_Partial_BE and the partial',{Engine_Mode:'Engine_Grid',Single_Partial_ATR:1,Single_Partial_Fraction:0.5,Single_Partial_BE:true}],
  ['the grid engine with the fraction alone',{Engine_Mode:'Engine_Grid',Single_Partial_Fraction:0.5}],
  ['the grid engine with Single_Partial_BE alone',{Engine_Mode:'Engine_Grid',Single_Partial_BE:true}]])
  assert.equal(refused({inputs:{...P,...inputs}}),2,name);
 assert.equal(refused({inputs:{...P,Single_Partial_ATR:1,Single_Partial_Fraction:0.99,Single_Partial_BE:true}}),null,'a coherent SET passes');
 ok();
}

// 9. Quotes: an empty quote, a stale one and OnInit's own tick trigger nothing, and each comes back once it is fresh.
{
 const W=world({...live({},{...PBE0,Single_BE_ATR:1})});const p=opened(W);W.w.tickAge=31;
 W.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(closes(W).length,0,'a last tick 31 s old: no partial');assert.equal(mods(W).length,0,'and no stop');
 assert.equal(lines(W,/are holding/).length,1,'one line');assert.equal(field(lines(W,/are holding/)[0],'last_tick_age'),'31s');assert.equal(W.ctx.g_GoatSingleQuotesStale,true);
 W.w.tickAge=30;W.run(ticks([[60,1.1030],[70,1.1030]]));assert.equal(closes(W).length,1,'30 s old is fresh');assert.equal(mods(W)[0].sl,p.open);assert.equal(W.ctx.g_GoatSingleQuotesStale,false);
 // A clock ahead reads as stale for as long as it lasts: the line repeats, and the dashboard row says so.
 const R=world(live({},{...PBE0,Single_BE_ATR:1}));opened(R);R.w.tickAge=40;const seen=[];const send=R.ctx.DashboardBusSendStatus;R.ctx.DashboardBusSendStatus=s=>{seen.push(s);send(s);};
 R.run(ticks([[0,1.1030],[1000,1.1030]],5));
 assert.equal(closes(R).length,0);assert.equal(mods(R).length,0);assert.equal(lines(R,/are holding/).length,4,'at 0, 300, 600 and 900 s: '+lines(R,/are holding/).length);
 // The dashboard row says so, and only when it would have said Active: paused, inactive and a CID refusal say more.
 const row=(setup,age=40)=>{const W=world(live({}));opened(W);W.w.gv.set('Dashboard_ChartID',7);const sent=[];W.ctx.DashboardBusSendStatus=s=>{sent.push(s);};W.ctx.Pause_Flag=false;setup(W);W.w.tickAge=age;W.run([[T0+1,1.1005],[T0+2,1.1005]]);return sent.at(-1);};
 assert.equal(row(()=>{},0),'Active','fresh quotes: Active');
 assert.equal(row(()=>{}),'Stale quotes','stale quotes on an active row');
 assert.equal(row(W=>{W.ctx.DashboardPortfolioPaused=true;}),'Paused','paused stays paused');
 assert.equal(row(W=>{W.ctx.GoatCidGuardStatus=()=>'CID duplicate';}),'CID duplicate','a CID refusal stays');
 assert.equal(row(W=>{W.ctx.Active=false;W.ctx.InActive=true;}),'Inactive','inactive stays inactive');
 const T=world(live({},{Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5}));opened(T);T.w.tickAge=31;T.run(ticks([[0,1.1030],[60,1.1030]]));assert.equal(mods(T).length,0,'no trailing on a stale quote');
 // A failed tick read is not fresh.
 const K=world(live({}));opened(K);K.w.rejectTick=true;K.run(ticks([[0,1.1030],[20,1.1030]]));assert.equal(closes(K).length,0,'SymbolInfoTick failed');assert.equal(lines(K,/are holding/).length,1);
 K.w.rejectTick=false;K.run([[T0+21,1.1030]]);assert.equal(closes(K).length,1);
 // A failed attempt does not let a stale quote send.
 const F=world({...live({rejectPartial:()=>true})});opened(F);F.run([[T0,1.1030]]);assert.equal(closes(F).length,1);F.w.tickAge=31;F.run(ticks([[10,1.1030],[100,1.1030]]));assert.equal(closes(F).length,1,'no retry on a stale quote');
 // The tester's clock is the tick's: it reads no age, so its trades cannot depend on one.
 const Y=world({inputs:PBE0,world:{tickAge:999,rejectTick:true}});opened(Y);Y.run([[T0+1,1.1030]]);assert.equal(closes(Y).length,1,'the tester reads no age');
 // An empty quote: a sell's ask of 0 reads as all favour.
 const S=world({inputs:PBE0,rsi:80});opened(S,1);S.run([[T0+1,1.1000,0],[T0+2,1.1000,0]]);assert.equal(closes(S).length,0,'ask 0: never due');assert.equal(mods(S).length,0);
 S.run([[T0+3,1.09890]]);assert.equal(closes(S).length,1,'a real ask');
 const Z=world({inputs:PBE0});const zp=opened(Z);Z.run([[T0+1,1.1030]]);assert.equal(closes(Z).length,1);
 const n=mods(Z).length;Z.w.positions[0].sl=zp.sl;Z.run([[T0+2,1.1030,0]]);assert.equal(mods(Z).length,n,'an empty ask moves no stop');
 const B=world({inputs:{...PARTIAL,Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5},rsi:25});opened(B);B.ctx.bid=0;assert.equal(B.ctx.GoatSingleQuotesFresh(),false,'bid 0');
 B.ctx.bid=1.1;B.ctx.ask=0;assert.equal(B.ctx.GoatSingleQuotesFresh(),false,'ask 0');B.ctx.ask=1.1001;assert.equal(B.ctx.GoatSingleQuotesFresh(),true,'both');
 // OnInit's own tick: the same, silently, and OnInit raises the flag around exactly that OnTick.
 const I=world({inputs:{...PBE0,Single_BE_ATR:1}});opened(I);I.ctx.g_GoatSingleInitTick=true;I.run([[T0+1,1.1030]]);
 assert.equal(closes(I).length,0,'no partial on OnInit\'s tick');assert.equal(mods(I).length,0,'no stop');assert.equal(lines(I,/are holding/).length,0,'no line');
 I.ctx.g_GoatSingleInitTick=false;I.run([[T0+2,1.1030]]);assert.equal(closes(I).length,1,'the next real tick');
 const src=H.readSource(undefined,H.MAIN);assert.match(src,/g_GoatSingleInitTick=true;[^\n]*\n   OnTick\(\); Sleep\(50\);\n   g_GoatSingleInitTick=false;/,'OnInit flags its own tick');
 assert.equal((src.match(/^\s*OnTick\(\);/gm)||[]).length,1,'the only direct OnTick call');
 ok();
}
// Break-even and trailing on normal ticks: this tree against #287's merge (82c269a), tester and live, the same trace.
for(const isLive of [false,true]) for(const inputs of [{Single_BE_ATR:1},{Single_Trail_Start_ATR:0.5,Single_Trail_ATR:0.5},{Single_BE_ATR:1,Single_Trail_Start_ATR:2,Single_Trail_ATR:1,Single_TP_R:9}]){
 const run=source=>{const W=world({source,inputs,tester:!isLive,fastSpeed:!isLive});W.run([...OPEN,...ticks([[0,1.1030],[400,1.1060],[800,1.0950],[900,1.0950]],5)]);return W.w.trace;};
 assert.deepEqual(run(undefined),run('82c269ae35eee4b18c3d02c0e79ad605a7071127'),'break-even and trailing as at #287: '+JSON.stringify(inputs)+(isLive?' live':' tester'));
 ok();
}
// Tester trades carry forward from the build the D1 hunt ran on (41e1fb9f): the same trace with partials, break-even and trailing.
for(const inputs of [PARTIAL,{...PBE0,Single_Partial_Fraction:0.6},{...PARTIAL,Single_BE_ATR:2,Single_Trail_Start_ATR:3,Single_Trail_ATR:0.5,Single_TP_R:9}]){
 const run=source=>{const W=world({source,inputs});W.run([...OPEN,...ticks([[0,1.1012],[300,1.103],[600,1.1015],[900,1.106],[1200,1.095],[1800,1.095]],5)]);return W.w.trace;};
 assert.deepEqual(run(undefined),run('41e1fb9f669db09cfe4b787aed057a6f1cf841cf'),'tester trades as at 41e1fb9f: '+JSON.stringify(inputs));ok();
}
// A partial on normal ticks in the tester: at the first tick at the trigger, then as #287's break-even and trailing would have it.
{const W=world({inputs:{...PARTIAL,Single_BE_ATR:2}});opened(W);W.run(ticks([[0,1.1012],[60,1.1012]]));assert.equal(closes(W)[0].time,T0,'the first tick at the trigger');ok();}

// 10. A late fill (the stubs fill at once otherwise; a close above the position's volume closes it all, as CTrade clamps).
{
 // Fills after the reply was lost, before the retry: fraction 0.6, so a stale 1.99 lots would take the whole 1.34 left.
 const LATE={...PBE,Single_Partial_Fraction:0.6};
 const W=world({inputs:LATE,world:{rejectPartial:()=>true,partialRetcode:10012}});const p=opened(W);
 W.w.lateFills=[{at:T0+2,ticket:p.ticket,volume:1.99}];
 W.run(ticks([[0,1.10110],[130,1.10110]]));
 assert.equal(closes(W).length,1,'one send, no retry');assert.ok(near(closes(W)[0].volume,1.99));
 assert.ok(near(W.w.positions[0].volume,1.34),'the remainder survives: '+W.w.positions[0].volume);assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),true);
 assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,1.34),'the level follows');assert.equal(W.w.positions[0].sl,p.open,'the break-even follows');
 assert.ok(near(W.ctx.Seq_Buy.SequenceRealizedPL,199,1e-6),'booked once, by its transaction: '+W.ctx.Seq_Buy.SequenceRealizedPL);
 // The review's exact case: a timeout, then the fill landing after a short retry would have gone, at +6 s. The wait holds it.
 const X=world({inputs:{...PARTIAL,Single_Partial_Fraction:0.6},world:{rejectPartial:(t,v,wd)=>wd.time<T0+5,partialRetcode:10012}});const xp=opened(X);
 X.w.lateFills=[{at:T0+6,ticket:xp.ticket,volume:1.99}];X.run(ticks([[0,1.10110],[130,1.10110]]));
 assert.deepEqual(closes(X).map(x=>x.time-T0),[0],'no retry inside the wait');assert.ok(near(X.w.positions[0].volume,1.34),'the remainder survives: '+X.w.positions.map(q=>q.volume));
 // An order of this position still open: nothing is sent, whatever the wait (by position id, or by magic, symbol and side).
 for(const order of [{ticket:7,position:'P'},{ticket:7,position:0,magic:'M',type:1}]){
  const O=world({world:{rejectPartial:()=>true,partialRetcode:10006}});const op=opened(O);O.run([[T0,1.10110]]);assert.equal(closes(O).length,1);
  O.w.rejectPartial=null;O.w.orders=[{...order,position:order.position==='P'?op.identifier:order.position,magic:order.magic==='M'?O.ctx.MAGIC1:0}];
  O.run(ticks([[5,1.10110],[60,1.10110]]));assert.equal(closes(O).length,1,'held by an open order');assert.equal(lines(O,/an order of this position is still open/).length,1,'one line');
  O.w.orders=[];O.run(ticks([[60,1.10110],[70,1.10110]]));assert.equal(closes(O).length,2,'gone: it sends');assert.ok(near(O.w.positions[0].volume,1.67));
 }
 // The sell: its close is a buy of this chart; a sell of this chart holds nothing.
 const SO=world({rsi:80});opened(SO,1);SO.w.orders=[{ticket:7,magic:SO.ctx.MAGIC1,type:0}];SO.run([[T0,1.0989]]);assert.equal(closes(SO).length,0,'a sell held by a buy-side close of this chart');assert.equal(lines(SO,/an order of this position is still open/).length,1);
 SO.w.orders=[];SO.run(ticks([[5,1.0989],[10,1.0989]]));assert.equal(closes(SO).length,1,'gone: it sends');
 const SQ=world({rsi:80});opened(SQ,1);SQ.w.orders=[{ticket:7,magic:SQ.ctx.MAGIC1,type:1}];SQ.run([[T0,1.0989]]);assert.equal(closes(SQ).length,1,'a sell-side order of this chart is no close of a sell');
 // Not this position's: a buy-side order of the same chart, or another chart's or symbol's close, holds nothing.
 for(const other of [{ticket:7,magic:'M',type:0},{ticket:7,magic:5,type:1},{ticket:7,magic:'M',type:1,symbol:'GBPUSD'}]){
  const Q=world({});opened(Q);Q.w.orders=[{...other,magic:other.magic==='M'?Q.ctx.MAGIC1:other.magic}];Q.run([[T0,1.10110]]);assert.equal(closes(Q).length,1,JSON.stringify(other));
 }
 // Fills after the history read, before the send: the volume read at the send stops it.
 const G=world({inputs:LATE});const g=opened(G);let once=true;
 G.w.afterHistory=(id,w)=>{if(once&&w.bid>=1.1011){once=false;w.positions[0].volume=1.34;}};
 G.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(G).length,0,'nothing is sent on a volume that just fell');assert.ok(near(G.w.positions[0].volume,1.34));assert.equal(G.ctx.GoatSinglePartialDone(g.ticket),true);
 assert.equal(lines(G,/a late fill/).length,1);assert.equal(G.w.positions[0].sl,g.open);
 // A reply lost, then the price leaves the trigger: the history is read once the wait ends, and the stop still moves.
 const R=world({inputs:PBE,world:{lostPartialReply:()=>true}});const r=opened(R);
 R.run(ticks([[0,1.10110],[2,1.10110],[3,1.10060],[10,1.10060]]));
 assert.equal(closes(R).length,1);assert.equal(R.ctx.GoatSinglePartialDone(r.ticket),true,'below the trigger, reconciled');assert.equal(R.w.positions[0].sl,r.open,'the remainder is protected');
 // A refusal, then the price leaves: nothing is sent below the trigger, the reads stay bounded, and it retries when due.
 let reads=0;const B=world({world:{rejectPartial:()=>true,rejectHistory:()=>{reads++;return false;}}});opened(B);B.run(ticks([[0,1.10110],[1,1.10110]]));reads=0;
 B.run(ticks([[1,1.10060],[400,1.10060]]));assert.equal(closes(B).length,1,'never below the trigger');assert.ok(reads>=6&&reads<=10,'a read a minute after its wait: '+reads);
 B.w.rejectPartial=null;B.w.rejectHistory=null;const back=T0+400;B.run(ticks([[400,1.10110],[402,1.10110]]));assert.equal(closes(B).length,2,'due again: it retries at once');assert.equal(closes(B)[1].time,back,'not after the slow read');assert.ok(near(B.w.positions[0].volume,1.67));
 // cid_duplicate freezes the partial too; its stop still moves.
 const C=world({inputs:{...PARTIAL,Single_BE_ATR:1}});const cp=opened(C);C.ctx.GoatCidGuardAddFrozen=()=>true;C.run([[T0,1.1020],[T0+1,1.1020]]);assert.equal(closes(C).length,0,'frozen');assert.equal(C.w.positions[0].sl,cp.open,'the stop still moves');
 C.ctx.GoatCidGuardAddFrozen=()=>false;C.run([[T0+2,1.1020]]);assert.equal(closes(C).length,1,'unfrozen');
 // The run's statistics count a position once: a partial adds no position and no duration.
 const St=world({});opened(St);St.run([[T0,1.1012]]);St.ctx.Seq_Buy.CloseSequencePositions('test');St.pump();assert.equal(St.ctx.Positions,1,'one position');assert.equal(St.ctx.Position_Durations.length,1);
 ok();
}

// 11. The demo gate.
const FAILED=1;
const UNKNOWN=[['an unreadable mode (reads 0, which is demo)',{accountError:4301}],['not connected',{connected:0}],['no login',{login:0}],['a bad login',{login:-1}],['no balance',{balance:0}],['no trade permission',{accountTradeAllowed:0}],
 ['the pre-sync second',{preSync:true}],['an unreadable mode on a real account',{accountError:4301,tradeMode:2}],['no login on a real account',{login:0,tradeMode:2}]];
const GOOD={accountError:0,connected:1,login:12345678,balance:100000,accountTradeAllowed:1,preSync:false,tradeMode:0};
{
 assert.equal(refused(live({})),null,'a connected demo with a login and a server: loaded');
 assert.equal(refused(live({tradeMode:2})),FAILED,'a real account');
 assert.equal(refused(live({tradeMode:1})),FAILED,'a contest account');
 assert.equal(refused(live({tradeMode:2,connected:0})),FAILED,'a real account stays refused while disconnected');
 assert.equal(refused(live({preSync:true,tradeMode:2})),null,'a real account in its pre-sync second reads as unknown, so it loads');
 // The server name is no proof either way.
 {const N=world(live({accountServer:''}));N.run(OPEN);assert.equal(sends(N).length,1,'an empty server name does not stop a synced demo');
  const X=world(live({preSync:true,accountServer:'Broker-Demo'}));X.run(OPEN);assert.equal(sends(X).length,0,'a demo-looking server name does not pass an unsynced one');}
 assert.equal(refused({inputs:PARTIAL,tester:true,world:{marginMode:0}}),FAILED,'alpha\'s netting refusal, in the tester');
 assert.equal(refused(live({marginMode:0})),null,'a live margin read is not trusted at OnInit');
 // Refused on a real account whatever the single's inputs: nothing in a SET opens it.
 for(const inputs of [{},{Single_Flat_Only:true},{Mode_Trade:'Long'},{Mode_Bias_Exit:0}]) assert.equal(refused(live({tradeMode:2},inputs)),FAILED,JSON.stringify(inputs));
 // A stale error from an earlier call is not this read's.
 const S=world(live({lastError:4301}));S.run(OPEN);assert.equal(sends(S).length,1,'only the account reads\' own error counts');
 // The tester contexts pass, whatever the account reads, with no settling.
 for(const [what,args] of [['the tester',{inputs:PARTIAL,tester:true,world:{tradeMode:2,connected:0,login:0}}],['optimization',{inputs:PARTIAL,tester:false,optimization:true,world:{tradeMode:2,connected:0}}],['forward',{inputs:PARTIAL,tester:false,world:{forward:true,tradeMode:2,connected:0}}]]){
  const W=world({...args,accountSettled:false,start:T0-600});assert.equal(W.ctx.g_GoatSingleAccountPending,false,what);assert.equal(W.ctx.GoatSingleAccountReady({v:''}),true,what+': ready with no settling');W.run(OPEN);assert.equal(sends(W).length,1,what+' opens');assert.ok(!W.w.removed,what);
 }
 // The grid is not gated, on any account.
 for(const wx of [{tradeMode:2},{accountError:4301,connected:0}]){const G=gridWorld({inputs:{EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70},tester:false,fastSpeed:false,indicator:indicator(25),world:wx});
  assert.equal(G.ctx.g_GoatSingleAccountPending,false);G.run(ticks([[-120,1.1000],[-60,1.1000]],20));assert.ok(!G.w.removed,'the grid is never removed');assert.equal(G.ctx.GoatSingleAccountWatch(),false);}
 ok();
}
{
 // The probed sequence on a real account: mode 0, no error, login and server filled, nothing else, then all at once its real
 // mode. Loaded, not one order and not a settling clock in that second, then removed on the first synced read.
 const SY=world({...live({preSync:true,tradeMode:2}),accountSettled:false,start:T0-200,bid:1.1});
 assert.equal(SY.ctx.g_GoatSingleAccountPending,true);assert.equal(SY.ctx.g_GoatSingleDemoSinceMs,0,'the pre-sync read starts no settling');
 SY.run(ticks([[-200,1.1],[-199,1.1]],1));assert.equal(sends(SY).length,0);assert.ok(!SY.w.removed);assert.equal(SY.ctx.g_GoatSingleDemoSinceMs,0);
 SY.w.preSync=false;SY.run([[T0-199,1.1],[T0-198,1.1]]);assert.equal(SY.w.removed,true,'its real mode removes it');assert.equal(sends(SY).length,0,'never an order');
 // The same sequence on a demo: the settling starts at the sync, not before.
 const SD=world({...live({preSync:true}),accountSettled:false,start:T0-200,bid:1.1});SD.run(ticks([[-200,1.1],[-199,1.1]],1));SD.w.preSync=false;
 SD.run(ticks([[-199,1.1],[-140,1.1]],1));assert.equal(sends(SD).length,0,'59 s after the sync');SD.run(ticks([[-140,1.1],[-138,1.1]],1));assert.equal(SD.ctx.g_GoatSingleAccountPending,false,'settled 60 s after it');SD.run(ticks([[-138,1.1],[-100,1.1]],1));assert.equal(sends(SD).length,1,'it opens at its next signal check');
 // Each sync field alone holds the settling back, and losing one restarts it.
 for(const [what,loss,back] of [['the connection',{connected:0},{connected:1}],['the balance',{balance:0},{balance:100000}],['the trade permission',{accountTradeAllowed:0},{accountTradeAllowed:1}]]){
  const L=world({...live({}),accountSettled:false,start:T0-300,bid:1.1});L.run(ticks([[-300,1.1],[-260,1.1]],1));Object.assign(L.w,loss);L.w.time=T0-260;L.ctx.GoatSingleAccountWatch();Object.assign(L.w,back);
  L.run(ticks([[-259,1.1],[-201,1.1]],1));assert.equal(sends(L).length,0,what+': the settling restarted');L.run(ticks([[-200,1.1],[-110,1.1]],1));assert.equal(sends(L).length,1,what+': then it opens');
 }
 // The read after the settling must agree: another login restarts it.
 const AG=world({...live({}),accountSettled:false,start:T0-300,bid:1.1});AG.run(ticks([[-300,1.1],[-250,1.1]],1));AG.w.login=999;AG.run(ticks([[-250,1.1],[-195,1.1]],1));assert.equal(sends(AG).length,0,'a new login, 105 s after OnInit and 55 s after the change');
 AG.run(ticks([[-195,1.1],[-170,1.1]],1));assert.equal(sends(AG).length,1);
 // The race past the sync fields: a real account whose mode still answers 0 once they fill. No order inside the settling, then removed.
 const RACE=world({...live({connected:0}),accountSettled:false});RACE.w.connected=1;RACE.run(ticks([[-200,1.1],[-150,1.1]],1));
 assert.equal(sends(RACE).length,0,'50 s of a demo reading: no order');assert.equal(RACE.ctx.g_GoatSingleAccountPending,true);
 RACE.w.tradeMode=2;RACE.run([[T0-149,1.1],[T0-148,1.1]]);assert.equal(sends(RACE).length,0);assert.equal(RACE.w.removed,true,'the real reading removes it');
 // The settling, to the second, from OnInit: 59 s no order, 60 s it opens.
 const A=world({...live({}),accountSettled:false,start:T0-110,bid:1.1});A.run(ticks([[-100,1.1],[-50,1.1]],1));assert.equal(sends(A).length,0,'59 s');assert.equal(A.ctx.g_GoatSingleAccountPending,true,'still settling at 59 s');
 A.run(ticks([[-50,1.1],[-49,1.1]],1));assert.equal(A.ctx.g_GoatSingleAccountPending,false,'60 s from OnInit, not from its first tick');A.run(ticks([[-49,1.1],[10,1.1]],1));assert.equal(sends(A).length,1,'it opens');
 // A dropout restarts it, seen by the timer's watch even with no tick.
 const D=world({...live({}),accountSettled:false,start:T0-300,bid:1.1});D.run(ticks([[-300,1.1],[-280,1.1]],1));D.w.connected=0;D.w.time=T0-275;D.ctx.GoatSingleAccountWatch();D.w.connected=1;
 D.run(ticks([[-270,1.1],[-225,1.1]],1));assert.equal(sends(D).length,0,'45 s after the reconnect, 75 s after OnInit');D.run(ticks([[-225,1.1],[-170,1.1]],1));assert.equal(sends(D).length,1,'after 60 s from the reconnect');
 // A dropout on a settled chart, too: a partial and an order both wait again.
 const P=world(live({},PBE0));opened(P);P.w.connected=0;P.run([[T0+1,1.1000]]);P.w.connected=1;P.run(ticks([[2,1.1012],[50,1.1012]]));assert.equal(closes(P).length,0,'a partial waits for the settling too');
 P.run(ticks([[50,1.1012],[70,1.1012]]));assert.equal(closes(P).length,1,'then it goes');
 const src=H.readSource(undefined,H.MAIN),timer=src.slice(src.indexOf('void GoatTimerBody(void)'));assert.ok(timer.slice(0,timer.indexOf('\n  }\n')).includes('   GoatSingleAccountWatch(); // B51'),'the timer watches');
 // Unknown stays loaded: no order, one line, armed, not removed. Verified and settled, it opens.
 for(const [what,wx] of UNKNOWN){
  const R=world(live(wx));assert.equal(R.ctx.g_GoatSingleAccountPending,true,what+': pending');R.run(OPEN);
  assert.equal(sends(R).length,0,what+': no order');assert.equal(R.ctx.Seq_Buy.Active,false);assert.equal(R.ctx.g_GoatSingleArmed[0],true,what+': the episode stays armed');
  assert.equal(lines(R,/Single refused/).length,1,what+': one line');assert.ok(!R.w.removed,what+': still loaded');
  Object.assign(R.w,GOOD);R.run(ticks([[0,1.1000],[59,1.1000]]));assert.equal(sends(R).length,0,what+': settling');
  R.run(ticks([[59,1.1000],[120,1.1000]]));assert.equal(R.ctx.g_GoatSingleAccountPending,false,what+': settled');assert.equal(sends(R).length,1,what+': then it opens');assert.ok(!R.w.removed);
 }
 // Positively read as not demo later: removed once, nothing opens, and that tick does nothing more.
 for(const [what,start,later] of [['unknown, then real',{connected:0},{connected:1,tradeMode:2}],['unknown, then contest',{accountError:4301},{accountError:0,tradeMode:1}],['demo, then real',{},{tradeMode:2}],['unknown, then real while disconnected',{connected:0},{tradeMode:2}]]){
  const R=world(live(start));Object.assign(R.w,later);R.run(OPEN);
  assert.equal(R.w.removed,true,what+': removed');assert.equal(sends(R).length,0,what+': no order');assert.equal(R.w.alerts.filter(a=>/removing the EA/.test(a)).length,1,what+': one alert');
 }
 ok();
}
{
 // The tick that removes the EA touches nothing: a partial, a stop, a time stop and an opposite exit were all due.
 const inputs={...PBE0,Single_BE_ATR:1,Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5,Single_Exit_Opposite:true,Single_Time_Stop_Bars:1,Single_Time_Stop_TF:'TF_H1'};
 const a=world({inputs,tester:false,fastSpeed:false});opened(a);
 const U=restart(a,inputs);assert.equal(U.ctx.Seq_Buy.Adopted,true);U.w.tradeMode=2;const n=U.w.trace.length;
 U.run([[T0+9000,1.1040]]);
 assert.equal(U.w.removed,true);assert.deepEqual(U.w.trace.slice(n),[],'nothing on the tick that removes it');assert.equal(U.w.positions[0].volume,a.w.positions[0].volume);
 assert.equal(U.ctx.GoatSingleAccountWatch(),true,'and it keeps saying so');
 // Unknown: exits and stops run, partials do not.
 const b=world({inputs:{...PBE0,Single_BE_ATR:1},tester:false,fastSpeed:false});const bp=opened(b);
 b.w.connected=0;b.run(ticks([[1,1.1030],[30,1.1030]]));
 assert.equal(closes(b).length,0,'no partial on an unknown account');assert.equal(b.w.positions[0].sl,bp.open,'a running single\'s break-even still moves');
 ok();
}
{
 // A VPS reboot with a running single: the EA stays loaded and its broker SL and TP hold. Nothing touches the position while the
 // account is unread, as adoption can send a stop modify. The first demo reading adopts it; opens and partials wait for the settling.
 const inputs={...PARTIAL,Single_Time_Stop_Bars:2,Single_Time_Stop_TF:'TF_H1'};
 const a=world({inputs,tester:false,fastSpeed:false});opened(a);a.run(ticks([[0,1.1005],[30,1.1005]]));
 const state={positions:JSON.parse(JSON.stringify(a.w.positions)),deals:JSON.parse(JSON.stringify(a.w.deals)),gv:[...a.w.gv],next:[a.w.nextTicket,a.w.nextDeal],balance:a.w.balance,time:a.w.time,bid:a.w.bid};
 const load=(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;};
 const U=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,world:{connected:0},adopt:load});
 assert.equal(U.ctx.Seq_Buy.Active,false,'not adopted while the account is unread');assert.equal(U.ctx.g_GoatSingleAccountPending,true);
 U.run(ticks([[31,1.1005],[40,1.1005]]));assert.equal(U.ctx.Seq_Buy.Active,false);assert.equal(U.w.trace.length,0,'nothing touches it');assert.ok(!U.w.removed);
 U.w.connected=1;U.run([[T0+41,1.1012]]);assert.equal(U.ctx.Seq_Buy.Adopted,true,'the first demo reading adopts it, inside the settling');assert.equal(U.ctx.g_GoatSingleAccountPending,true,'still settling');
 assert.equal(closes(U).length,0,'a partial waits for the settling');U.run(ticks([[42,1.1012],[105,1.1012]]));assert.equal(closes(U).length,1,'then it goes');
 U.run(ticks([[105,1.1012],[9000,1.1012]],20));assert.equal(U.w.trace.filter(x=>x.op==='PositionClose').length,1,'its time stop runs');
 // The terminal had not loaded the positions at OnInit: adopted once they read, never a second position beside them.
 const L=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,world:{connected:0},adopt:()=>{}});assert.equal(L.ctx.Seq_Buy.Active,false);
 load(L.ctx,L.w);L.w.connected=1;L.run(ticks([[31,1.1005],[150,1.1005]]));
 assert.equal(L.ctx.Seq_Buy.Adopted,true,'adopted');assert.equal(sends(L).length,0,'nothing opens beside it');assert.equal(L.ctx.g_GoatSingleAccountPending,false);assert.equal(L.w.positions.length,1);
 // No signal needed: the watch adopts them by itself.
 const L2=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,world:{connected:0},adopt:()=>{}});load(L2.ctx,L2.w);L2.w.connected=1;L2.run([[T0+31,1.1005]]);assert.equal(L2.ctx.Seq_Buy.Adopted,true,'adopted with no open attempt, on its first demo reading');
 // The positions arrive after the account has settled: GoatSingleOpen adopts them rather than open.
 const E=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:()=>{}});E.run([[state.time+1,1.1005]]);assert.equal(E.ctx.g_GoatSingleAccountPending,false);
 load(E.ctx,E.w);assert.equal(E.ctx.GoatSingleOpen(E.ctx.Seq_Buy,E.w.ask),false,'no second position');assert.equal(E.ctx.Seq_Buy.Adopted,true);assert.equal(sends(E).length,0);
 // cid_duplicate comes first: frozen, it neither adopts nor opens.
 const FZ=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:()=>{}});FZ.run([[state.time+1,1.1005]]);load(FZ.ctx,FZ.w);FZ.ctx.GoatCidGuardAddFrozen=()=>true;
 assert.equal(FZ.ctx.GoatSingleOpen(FZ.ctx.Seq_Buy,FZ.w.ask),false);assert.equal(FZ.ctx.Seq_Buy.Adopted,false,'frozen: not adopted');
 // Single_Flat_Only: a late buy holds a sell signal too. Without it, the sell may open beside it, as hedging allows.
 const SF=world({inputs:{...inputs,Single_Flat_Only:true},tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:()=>{}});SF.run([[state.time+1,1.1005]]);load(SF.ctx,SF.w);
 assert.equal(SF.ctx.GoatSingleOpen(SF.ctx.Seq_Sell,SF.w.bid),false,'flat-only: no sell beside a late buy');assert.equal(SF.ctx.Seq_Buy.Adopted,true,'it adopts the buy');assert.equal(sends(SF).length,0);
 // A late sell and a buy signal under Single_Flat_Only, the mirror.
 const sa=world({inputs,tester:false,fastSpeed:false,rsi:80});opened(sa,1);
 const sst={positions:JSON.parse(JSON.stringify(sa.w.positions)),deals:JSON.parse(JSON.stringify(sa.w.deals)),gv:[...sa.w.gv],next:[sa.w.nextTicket,sa.w.nextDeal],balance:sa.w.balance};
 const sload=(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(sst.positions)));w.deals.push(...JSON.parse(JSON.stringify(sst.deals)));for(const [k,v] of sst.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=sst.next;w.balance=sst.balance;};
 const SB=world({inputs:{...inputs,Single_Flat_Only:true},tester:false,fastSpeed:false,start:sa.w.time,bid:sa.w.bid,rsi:50,adopt:()=>{}});SB.run([[sa.w.time+1,1.1000]]);sload(SB.ctx,SB.w);
 assert.equal(SB.ctx.GoatSingleOpen(SB.ctx.Seq_Buy,SB.w.ask),false,'flat-only: no buy beside a late sell');assert.equal(SB.ctx.Seq_Sell.Adopted,true,'it adopts the sell');assert.equal(sends(SB).length,0);
 // Allow_Opposite_Seq off holds it too: no sell beside a late buy, and no buy beside a late sell.
 const AO=world({inputs:{...inputs,Allow_Opposite_Seq:false},tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:()=>{}});AO.run([[state.time+1,1.1005]]);load(AO.ctx,AO.w);
 assert.equal(AO.ctx.GoatSingleOpen(AO.ctx.Seq_Sell,AO.w.bid),false,'Allow_Opposite_Seq off: no sell beside a late buy');assert.equal(AO.ctx.Seq_Buy.Adopted,true);assert.equal(sends(AO).length,0);
 const AS=world({inputs:{...inputs,Allow_Opposite_Seq:false},tester:false,fastSpeed:false,start:sa.w.time,bid:sa.w.bid,rsi:50,adopt:()=>{}});AS.run([[sa.w.time+1,1.1000]]);sload(AS.ctx,AS.w);
 assert.equal(AS.ctx.GoatSingleOpen(AS.ctx.Seq_Buy,AS.w.ask),false,'Allow_Opposite_Seq off: no buy beside a late sell');assert.equal(AS.ctx.Seq_Sell.Adopted,true);assert.equal(sends(AS).length,0);
 const NF=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:()=>{}});NF.run([[state.time+1,1.1005]]);load(NF.ctx,NF.w);
 assert.equal(NF.ctx.GoatSingleOpen(NF.ctx.Seq_Sell,NF.w.bid),true,'no flat-only: the sell opens');assert.equal(NF.ctx.Seq_Buy.Adopted,true,'and the buy is managed');
 // An adopted single used up its episode: when it ends with the signal still true, no second single; a new episode opens one.
 const rsiAt=f=>f;let rv=25;const EP=H.build(undefined,{inputs:{...BASE,...inputs},tester:false,fastSpeed:false,indicator:indicator(()=>rv),start:state.time,bid:state.bid,adopt:load});
 assert.equal(EP.ctx.Seq_Buy.Adopted,true);assert.equal(EP.ctx.g_GoatSingleArmed[0],false,'disarmed');
 EP.ctx.Seq_Buy.CloseSequencePositions('test');EP.pump();EP.run(ticks([[31,1.1005],[300,1.1005]]));assert.equal(sends(EP).length,0,'the signal is still true: no second single');
 rv=50;EP.run(ticks([[300,1.1005],[420,1.1005]]));rv=25;EP.run(ticks([[420,1.1005],[540,1.1005]]));assert.equal(sends(EP).length,1,'a new episode opens');
 // Reversed: the buy was opened by the sell signal, so that one is disarmed.
 const RV=world({inputs:{...inputs,Reverse_Seq:true},tester:false,fastSpeed:false,start:state.time,bid:state.bid,rsi:50,adopt:load});assert.deepEqual([RV.ctx.g_GoatSingleArmed[0],RV.ctx.g_GoatSingleArmed[1]],[true,false],'under Reverse_Seq');
 // The grid is not held from adopting, whatever the account reads.
 {const G=gridWorld({inputs:{EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70},tester:false,fastSpeed:false,indicator:indicator(50),world:{connected:0},
   adopt:(ctx,w)=>{w.positions.push({ticket:5000001,identifier:5000001,symbol:'EURUSD',magic:ctx.MAGIC1,type:0,volume:0.1,open:1.1,sl:0,tp:0,time:w.time,time_msc:w.time*1000,comment:'',swap:0,commission:0});}});assert.equal(G.ctx.Seq_Buy.Adopted,true,'the grid adopts');}
 // A Studio or dashboard chart on a netting demo never trades, so it is never removed for netting.
 for(const mode of ['Operation_Dash','Operation_Batch']){const CH=world({...live({marginMode:0},{...PARTIAL,Mode_Operation:mode}),accountSettled:false});CH.w.time=T0;assert.equal(CH.ctx.GoatSingleAccountWatch(),false,mode);CH.w.time=T0+100;assert.equal(CH.ctx.GoatSingleAccountWatch(),false,mode);assert.ok(!CH.w.removed,mode+' stays');}
 // Netting: only on a settled read. A hedging demo whose margin mode answers 0 for a tick stays; one that keeps answering it goes.
 const M=world({...live({marginMode:0}),accountSettled:false,start:T0-300,bid:1.1});M.run(ticks([[-300,1.1],[-290,1.1]],1));assert.ok(!M.w.removed,'not unsettled');M.w.marginMode=2;M.run(ticks([[-290,1.1],[-200,1.1]],1));assert.ok(!M.w.removed,'a hedging demo stays');assert.equal(sends(M).length,1,'and trades');
 const N=world({...live({marginMode:0}),accountSettled:false,start:T0-300,bid:1.1});N.run(ticks([[-300,1.1],[-200,1.1]],1));assert.equal(N.w.removed,true,'netting, settled');assert.equal(sends(N).length,0);
 // A demo that drops mid-run: new opens refused, and back on after the settling, it opens.
 const D=world(live({}));D.w.connected=0;D.run(OPEN);assert.equal(sends(D).length,0);assert.ok(!D.w.removed);D.w.connected=1;D.run(ticks([[0,1.1000],[120,1.1000]]));assert.equal(sends(D).length,1);
 // Pending alone refuses an open, whatever the account reads now.
 const P=world(live({}));P.ctx.g_GoatSingleAccountPending=true;assert.equal(P.ctx.GoatSingleOpen(P.ctx.Seq_Buy,P.w.ask),false,'pending refuses');
 ok();
}
{
 const RD={Random_Direction:true,Single_Flat_Only:true,Mode_Trade:'Long_and_Short'};
 assert.equal(refused(live({},RD)),FAILED,'Random_Direction on a demo chart');
 assert.equal(refused(live({connected:0},RD)),FAILED,'and on an unread one');
 assert.equal(refused({inputs:RD,tester:true}),null,'Random_Direction in the tester');
 // In the source: its refusal reads MQL_TESTER alone, and the gate reads no input and has no switch.
 const main=H.readSource(undefined,H.MAIN),C=H.compile(H.loadSources());
 assert.ok(main.includes('if(Random_Direction && !MQLInfoInteger(MQL_TESTER))  {Alert("Initialization Failed: Random_Direction is a strategy-tester benchmark'),'the benchmark\'s gate');
 const body=main.slice(main.indexOf('int GoatSingleAccountState(string &b51_why)'));const fn=body.slice(0,body.indexOf('// Adoption can send a stop modify'));
 const inputs=C.globals.filter(g=>g.input).map(g=>g.name);assert.ok(inputs.length>100);
 for(const name of inputs) assert.ok(!new RegExp('\\b'+name+'\\b').test(fn),'the gate reads no input: '+name);
 assert.ok(!/#if/.test(fn),'no conditional can turn it off');assert.deepEqual([...new Set(fn.match(/\bg_\w+/g))],['g_GoatSingleDemoSinceMs','g_GoatSingleDemoLogin'],'the only globals it reads are the settling clock and its login');
 // The grid's own partial closes still count as positions, as they always have (test_b51_parity compares the counts).
 assert.ok(main.includes('else if(Engine_Mode!=Engine_Single || j==HistoryDealsTotal()-1) // B51'),'only a single skips them');
 // A live re-init keeps EA globals: OnInit clears them all; the partial's close carries the join's magic.
 assert.ok(main.includes('g_GoatSingleAccountPending=false; g_GoatSingleAccountRemoved=false; g_GoatSingleDemoSinceMs=0; // a live re-init keeps EA globals'),'OnInit resets the gate');
 // The single's only way to a position, and the gate comes first in it.
 const open=main.slice(main.indexOf('bool GoatSingleOpen(SEQUENCE &s,double price)'));
 assert.ok(open.indexOf('GoatSingleAccountReady(')<open.indexOf('OpenPosition('),'asked before the order');
 ok();
}

console.log(JSON.stringify({passed,test:'b51_partial'}));
