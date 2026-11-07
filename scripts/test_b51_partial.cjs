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
// - the demo gate: a live chart trades only on a connected demo with a login, a server and no read error; real, contest,
//   unreadable and disconnected are refused at OnInit and at every open; the tester contexts pass; no input is read;
//   the grid is untouched; Random_Direction stays tester-only.
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
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500};
const PARTIAL={Single_Partial_ATR:1,Single_Partial_Fraction:0.5};
const PBE0={...PARTIAL,Single_Partial_BE:true};
const indicator=rsi=>(name,buffer,shift,w)=>{
 if(name==='ATR_MA') return shift===1?0.0010:0.0030;
 if(name==='RSI') return typeof rsi==='function'?rsi(w.time):rsi;
 return undefined;};
function ticks(points,step=1){const t=[];for(let k=1;k<points.length;k++){const [a,p]=points[k-1],[b,q]=points[k];for(let s=a;s<b;s+=step)t.push([T0+s,p+(q-p)*(s-a)/(b-a)]);}return t;}
const OPEN=ticks([[-600,1.1000],[0,1.1000]],20);
function world({inputs=PARTIAL,rsi=25,source,tester=true,optimization=false,fastSpeed=true,world:wx={},adopt,start,bid,spread}={}){
 return H.build(source,{inputs:{...BASE,...inputs},tester,optimization,fastSpeed,indicator:indicator(rsi),world:wx,adopt,start,bid,spread});
}
const closes=W=>W.w.trace.filter(x=>x.op==='PositionClosePartial');
const mods=W=>W.w.trace.filter(x=>x.op==='PositionModify');
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const lines=(W,re)=>W.w.logs.filter(l=>re.test(l));
const field=(line,name)=>{const m=line.match(new RegExp('(?:^|\\s)'+name+'=([^\\s:]+)'));assert.ok(m,'the line carries '+name+': '+line);return m[1];};
const near=(a,b,eps=1e-9)=>Math.abs(a-b)<=eps;
function opened(W,type=0){W.run(OPEN);const s=sends(W);assert.equal(s.length,1,'the single opens');assert.equal(s[0].type,type);return {...W.w.positions[0]};}
const refused=(args)=>{try{world(args);return null;}catch(e){assert.ok(e.initCode!==undefined,e.message);return e.initCode;}};

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
 // It heals: one more attempt, one close, no more lines.
 W.w.rejectPartial=null;W.run(ticks([[400,1.10110],[600,1.10110]]));
 assert.equal(closes(W).length,times.length+1,'one attempt after it heals');assert.ok(near(W.w.positions[0].volume,1.67));
 assert.equal(lines(W,/Single partial close failed/).length,f.length);assert.equal(lines(W,/Single partial close: ticket=/).length,1);
 // No retry once the price has left: the wait passes, and nothing is due.
 const L=world({world:{rejectPartial:()=>true}});opened(L);L.run(ticks([[0,1.10110],[3,1.10110],[4,1.1000],[100,1.1000]]));
 assert.equal(closes(L).length,1,'retried only while due');
 ok();
}
// A true return is not a fill: only the retcode says so, and the position's volume confirms it (review of GOAT-EA#287).
for(const retcode of [10004,10006,10008,10018,10021,10025]){
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
 // The server says DONE, the position's volume has not moved: not confirmed. A read that later shows the fill ends it with no
 // second send; a volume that never moves is retried under the back-off.
 const W=world({inputs:PBE0,world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10009}});const p=opened(W);
 W.run(ticks([[0,1.10110],[3,1.10110]]));
 assert.equal(closes(W).length,1);assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),false,'DONE without less volume is not done');assert.equal(mods(W).length,0);
 W.w.positions[0].volume=1.67;W.run(ticks([[3,1.10110],[60,1.10110]]));
 assert.equal(closes(W).length,1,'the fill shows up: no second send');assert.equal(W.ctx.GoatSinglePartialDone(p.ticket),true);assert.equal(lines(W,/already done/).length,1);assert.equal(W.w.positions[0].sl,p.open);
 const N=world({world:{rejectPartial:()=>true,partialReturnsTrue:true,partialRetcode:10009}});opened(N);N.run(ticks([[0,1.10110],[40,1.10110]]));
 assert.deepEqual(closes(N).map(x=>x.time-T0),[0,5,35],'it never filled: retried under the back-off');
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
 W.run(ticks([[0,1.10110],[100,1.10110]]));
 assert.equal(closes(W).length,1,'one send');assert.ok(near(W.w.positions[0].volume,1.67),'it filled once');
 assert.equal(lines(W,/already done/).length,1);assert.ok(near(W.ctx.Seq_Buy.TradeLevels[0].lots,1.67),'the level follows');
 // A close made elsewhere, with its deal not in the history yet: the volume alone shows it.
 const V=world({});opened(V);V.w.positions[0].volume=2;V.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.equal(closes(V).length,0,'less volume than its entry: it has had one');assert.equal(lines(V,/already done/).length,1);
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
 const J=world({inputs:{...PARTIAL,Ledger_Mode:'Ledger_PositionJoin'}});opened(J);const before=J.ctx.Seq_Buy.SequenceRealizedPL;
 J.run(ticks([[0,1.10110],[30,1.10110]]));
 assert.ok(near(J.ctx.Seq_Buy.SequenceRealizedPL-before,166,1e-6),'1.66 lots x 100 points at 1 USD: '+(J.ctx.Seq_Buy.SequenceRealizedPL-before));
 assert.equal(J.w.deals.filter(d=>d.entry===1)[0].magic,J.ctx.MAGIC1,'the close carries MAGIC1');
 assert.ok(near(J.ctx.Seq_Buy.CurrentSequencePL(),166+167,1e-6),'realized + the remainder\'s open P/L');
 // Ledger_Legacy books what the grid's partial books there: nothing, as the deal has no magic (documented in 8.3).
 const L=world({});opened(L);L.run(ticks([[0,1.10110],[30,1.10110]]));assert.equal(L.ctx.Seq_Buy.SequenceRealizedPL,0);
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
 const G=H.build(undefined,{inputs:{EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70},tester:true,fastSpeed:true,indicator:indicator(25)});
 G.run([...OPEN,...ticks([[0,1.1030],[60,1.1030]])]);assert.equal(closes(G).length,0);
 ok();
}

// 8. OnInit refusals (INIT_PARAMETERS_INCORRECT).
{
 const P={...BASE};
 for(const [name,inputs] of [['a negative trigger',{Single_Partial_ATR:-1,Single_Partial_Fraction:0.5}],['a negative fraction',{Single_Partial_ATR:1,Single_Partial_Fraction:-0.5}],
  ['a negative trigger alone',{Single_Partial_ATR:-1}],['a negative fraction alone',{Single_Partial_Fraction:-0.5}],['both negative',{Single_Partial_ATR:-1,Single_Partial_Fraction:-0.5}],
  ['a fraction of 1',{Single_Partial_ATR:1,Single_Partial_Fraction:1}],['a fraction above 1',{Single_Partial_ATR:1,Single_Partial_Fraction:1.5}],
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

// 9. The demo gate.
const live=(wx,inputs=PARTIAL)=>({inputs,tester:false,fastSpeed:false,world:wx});
const FAILED=1;
{
 assert.equal(refused(live({})),null,'a connected demo with a login and a server: allowed');
 assert.equal(refused(live({tradeMode:2})),FAILED,'a real account');
 assert.equal(refused(live({tradeMode:1})),FAILED,'a contest account');
 assert.equal(refused(live({accountError:4301})),FAILED,'an unreadable mode reads 0, which is demo: refused');
 assert.equal(refused(live({connected:0})),FAILED,'not connected');
 assert.equal(refused(live({login:0})),FAILED,'no login');
 assert.equal(refused(live({login:-1})),FAILED,'a bad login');
 assert.equal(refused(live({accountServer:''})),FAILED,'no server');
 // Refused on a real account whatever the single's inputs: nothing in a SET opens it.
 for(const inputs of [{},{Single_Flat_Only:true},{Mode_Trade:'Long'},{Mode_Bias_Exit:0}]) assert.equal(refused(live({tradeMode:2},inputs)),FAILED,JSON.stringify(inputs));
 // A stale error from an earlier call is not this read's.
 assert.equal(refused(live({lastError:4301})),null,'only the account reads\' own error counts');
 // The tester contexts pass, whatever the account reads.
 assert.equal(refused({inputs:PARTIAL,tester:true,world:{tradeMode:2,connected:0,login:0}}),null,'the tester');
 assert.equal(refused({inputs:PARTIAL,tester:false,optimization:true,world:{tradeMode:2,connected:0}}),null,'optimization');
 assert.equal(refused({inputs:PARTIAL,tester:false,world:{forward:true,tradeMode:2,connected:0}}),null,'forward');
 // The grid and the build's other refusals are untouched: the grid runs on a real account.
 assert.equal(refused({inputs:{Engine_Mode:'Engine_Grid'},tester:false,fastSpeed:false,world:{tradeMode:2}}),null,'the grid is not gated');
 assert.equal(refused({inputs:{Engine_Mode:'Engine_Grid'},tester:false,fastSpeed:false,world:{accountError:4301,connected:0}}),null,'nor when it cannot read');
 ok();
}
{
 // Every open asks again, and a refusal is one line, leaves the episode armed, and sends nothing.
 for(const [what,wx] of [['real',{tradeMode:2}],['contest',{tradeMode:1}],['unreadable',{tradeMode:0,accountError:4301}],['disconnected',{tradeMode:0,accountError:0,connected:0}],['no login',{connected:1,login:0}],['no server',{login:12345678,accountServer:''}]]){
  const R=world(live({}));Object.assign(R.w,wx);R.run(OPEN);
  assert.equal(sends(R).length,0,what+': no order');assert.equal(R.ctx.Seq_Buy.Active,false);assert.equal(R.ctx.g_GoatSingleArmed[0],true,what+': the episode stays armed');
  assert.equal(lines(R,/Single refused/).length,1,what+': one line');
 }
 const R=world(live({}));Object.assign(R.w,{tradeMode:2});R.run(OPEN);assert.equal(sends(R).length,0);
 Object.assign(R.w,{tradeMode:0});R.run(ticks([[0,1.1000],[120,1.1000]]));assert.equal(sends(R).length,1,'back on a demo: it opens');
 // A demo trades live, end to end, partial included.
 const D=world(live({}));opened(D);D.run(ticks([[0,1.1012],[30,1.1012]]));assert.equal(closes(D).length,1);
 // Random_Direction stays tester-only, on a demo too; it still runs in the tester.
 const RD={Random_Direction:true,Single_Flat_Only:true,Mode_Trade:'Long_and_Short'};
 assert.equal(refused(live({},RD)),FAILED,'Random_Direction on a demo chart');
 assert.equal(refused({inputs:RD,tester:true}),null,'Random_Direction in the tester');
 // In the source: its refusal reads MQL_TESTER alone, and the gate reads no input and has no switch.
 const main=H.readSource(undefined,H.MAIN),C=H.compile(H.loadSources());
 assert.ok(main.includes('if(Random_Direction && !MQLInfoInteger(MQL_TESTER))  {Alert("Initialization Failed: Random_Direction is a strategy-tester benchmark'),'the benchmark\'s gate');
 const body=main.slice(main.indexOf('string GoatSingleAccountRefusal()'));const fn=body.slice(0,body.indexOf('// B51:end b51-account'));
 const inputs=C.globals.filter(g=>g.input).map(g=>g.name);assert.ok(inputs.length>100);
 for(const name of inputs) assert.ok(!new RegExp('\\b'+name+'\\b').test(fn),'the gate reads no input: '+name);
 assert.ok(!/\bg_\w+|#if/.test(fn),'no global or conditional can turn it off');
 // The single's only way to a position, and the gate comes first in it.
 const open=main.slice(main.indexOf('bool GoatSingleOpen(SEQUENCE &s,double price)'));
 assert.ok(open.indexOf('GoatSingleAccountRefusal()')<open.indexOf('OpenPosition('),'asked before the order');
 const init=main.slice(main.indexOf('// B51:begin b51-init'),main.indexOf('// B51:end b51-init'));
 assert.match(init,/if\(Engine_Mode==Engine_Single && GoatSingleAccountRefusal\(\)!=""\) \{Alert\([^\n]*return INIT_FAILED;\}/,'OnInit refuses on it');
 ok();
}

console.log(JSON.stringify({passed,test:'b51_partial'}));
