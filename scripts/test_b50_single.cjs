// B50 single core (B50-alpha A1, docs/b50/B50_ALPHA_DESIGN.md sections 1 and 4): Engine_Mode=Engine_Single on the
// real OnTick path. scripts/b50_tick_harness.cjs converts this tree's GoatTickBody, SignalEntryTrigger,
// UpdateCurrentSignals, OpenPosition, the SEQUENCE methods and GoatSingleOpen, and runs them against the modelled
// terminal (hedging, EURUSD, 1 USD per point per lot: 100000 per price unit per lot). RSI_OverBS drives the signal
// (RSI <= 30 buy, >= 70 sell, else neither); ATR_MA answers 0.0010 on the closed bar (shift 1) and 0.0030 on the
// forming bar (shift 0), so a read of the wrong bar shows in the stop.
// Proves: lots <= Risk / (SL x value), floored to the step, capped at the maximum, refused below the minimum; the
// TP_R / TP_ATR precedence; the ATR of shift 1, read without touching ATR_Buf; no virtual leg (Delay_Trade=1), no grid
// add, one position per signal episode (re-armed only on the signal's false edge); Add_Level's order (CID freeze,
// manage-only, OpenPosition, direction guard, then the ledger join, the entry commission, the restart record and
// UpdateLockTPSL); the refusals (no ATR, a stop inside the stops level plus the spread) logged once.
// scripts/test_b50_single_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail it.
// What it does not prove: compile cleanliness, MT5's fills. The MetaEditor compile and the native runs do.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
let passed=0;const ok=()=>passed++;

const MON=Date.UTC(2026,9,5)/1000,H1=3600,VALUE=1e5;   // Monday 2026-10-05 00:00 server time; money per price unit per lot
function path(start,points){   // a tick every 20 s (7 s past), linear between [seconds after start, bid] points
 const ticks=[];
 for(let k=1;k<points.length;k++){
  const [t0,p0]=points[k-1],[t1,p1]=points[k];
  for(let t=t0;t<t1;t+=20) ticks.push([start+t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);
 }
 return ticks;
}
// rsi: [[from seconds after MON, value], ...] (the last entry whose start has passed).
const rsiAt=(sched,t)=>{let v=50;for(const [from,x] of sched)if(t-MON>=from)v=x;return v;};
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500};
// tickSize: SYMBOL_TRADE_TICK_SIZE when it differs from the point (the model answers the point); bid, spread: the quote.
function single({inputs={},rsi=[[0,25]],atr1=0.0010,atr0=0.0030,fastSpeed=true,tester=true,world={},tickSize,bid,spread}={}){
 const W=H.build(undefined,{inputs:{...BASE,...inputs},fastSpeed,tester,world,bid,spread,
  indicator:(name,buffer,shift,w)=>{
   if(name==='ATR_MA') return shift===1?atr1:(shift===0?atr0:undefined);
   if(name==='RSI') return rsiAt(rsi,w.time);
   return undefined;}});
 if(tickSize!==undefined){
  const orig=W.ctx.SymbolInfoDouble,K=W.ctx.SYMBOL_TRADE_TICK_SIZE;assert.equal(typeof K,'number');
  W.ctx.SymbolInfoDouble=(sym,k,box)=>{if(k!==K)return orig(sym,k,box);if(box){box.v=tickSize;return true;}return tickSize;};
 }
 return W;
}
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const refusals=W=>W.w.logs.filter(l=>/Single refused/.test(l));
const near=(a,b,eps=1e-9)=>Math.abs(a-b)<=eps;
const FLAT=path(MON,[[2*H1,1.1000],[3*H1,1.1000]]);

// 1. RiskperSeq: floor(Risk / (Size_SL x value)) to the step; never above the risk; the cap; the volume-minimum grid.
{
 // SL = 1.8 x 0.0010 = 0.0018: 500 / 180 = 2.777.. lots, floored to 2.77 (2.78 would risk 500.4).
 const W=single({inputs:{Single_SL_ATR:1.8}});W.run(FLAT);
 const s=sends(W);assert.equal(s.length,1,'one single opens');
 assert.equal(s[0].volume,2.77,'floored to the volume step');
 assert.ok(s[0].volume*0.0018*VALUE<=500+1e-6,'lots x SL x value <= Risk');
 assert.ok(near(s[0].price-s[0].sl,0.0018,1e-8),'the stop is Single_SL_ATR x ATR');
 assert.equal(W.ctx.Seq_Buy.StartLots,2.77);
 // 500 / 150 = 3.333.. -> 3.33
 const W2=single();W2.run(FLAT);assert.equal(sends(W2)[0].volume,3.33);
 assert.ok(sends(W2)[0].volume*0.0015*VALUE<=500+1e-6);
 // The volume maximum caps it.
 const W3=single({world:{volumeMax:2}});W3.run(FLAT);assert.equal(sends(W3)[0].volume,2,'capped at the volume maximum');
 // OpenPosition sends multiples of the volume minimum: 2.77 would go out as 2.8 (above the risk), so 2.7 is sent.
 const W4=single({inputs:{Single_SL_ATR:1.8},world:{volumeMin:0.1,volumeStep:0.01}});W4.run(FLAT);
 assert.equal(sends(W4)[0].volume,2.7,'never rounded up past the risk by the volume-minimum grid');
 assert.ok(sends(W4)[0].volume*0.0018*VALUE<=500+1e-6);
 assert.equal(W4.ctx.Seq_Buy.StartLots,2.7,'the single records what is sent');
 // ... and never rounded down from what it records (GOAT-EA#272 P3): 500 / 183 = 2.73 would go out as 2.7.
 const W5=single({inputs:{Single_SL_ATR:1.83},world:{volumeMin:0.1,volumeStep:0.01}});W5.run(FLAT);
 assert.equal(sends(W5)[0].volume,2.7);assert.equal(W5.ctx.Seq_Buy.StartLots,2.7,'StartLots is the volume sent');
 ok();
}
// 1b. GOAT-EA#272 P1: the money per price unit is SYMBOL_TRADE_TICK_VALUE / SYMBOL_TRADE_TICK_SIZE and nothing else.
// PriceValuePerPointPerLot's fallbacks answer per tick or per point, which sized EURUSD with no tick size at the
// volume maximum (Risk 500, SL 0.0015, tv 1: 333333 lots). No tick value or no tick size: refused, nothing sent.
{
 const ts0=single({tickSize:0});ts0.run(FLAT);
 assert.equal(sends(ts0).length,0,'no tick size: refused, never sized at the volume maximum');
 assert.equal(refusals(ts0).length,1);assert.match(refusals(ts0)[0],/no tick value or tick size/);
 const tv0=single({world:{tickValue:0}});tv0.run(FLAT);
 assert.equal(sends(tv0).length,0,'no tick value: refused');assert.match(refusals(tv0)[0],/no tick value or tick size/);
 for(const bad of [NaN,-0.00001]){const B=single({tickSize:bad});B.run(FLAT);assert.equal(sends(B).length,0,'tick size '+bad+': refused');}
 // FX (EURUSD, USD account): tv 1 per 0.00001 -> 100000 per price unit; 500 / (0.0015 x 100000) = 3.33.
 const fx=single();fx.run(FLAT);assert.equal(sends(fx)[0].volume,3.33,'FX');
 // JPY (USDJPY at 150, USD account): tick 0.001 worth 0.6667 USD -> 666.7 per price unit; ATR 0.30, SL 0.45:
 // 500 / (0.45 x 666.7) = 1.6666 -> 1.66.
 const jpyPath=path(MON,[[2*H1,150.000],[3*H1,150.000]]);
 const jpy=single({atr1:0.30,atr0:0.90,bid:150,spread:0.01,world:{point:0.001,digits:3,tickValue:0.6667}});jpy.run(jpyPath);
 assert.ok(near(sends(jpy)[0].volume,1.66),'JPY: '+sends(jpy).map(x=>x.volume));
 assert.ok(near(sends(jpy)[0].price-sends(jpy)[0].sl,0.45,1e-6));
 // A metal (XAUUSD at 2400, 100 oz): tick 0.01 worth 1 USD -> 100 per price unit; ATR 5, SL 7.5: 500 / 750 = 0.666 -> 0.66.
 const xauPath=path(MON,[[2*H1,2400.00],[3*H1,2400.00]]);
 const xau=single({atr1:5,atr0:15,bid:2400,spread:0.20,world:{point:0.01,digits:2,tickValue:1}});xau.run(xauPath);
 assert.ok(near(sends(xau)[0].volume,0.66),'metal: '+sends(xau).map(x=>x.volume));
 // A tick size that is not the point (an index: point 0.01, tick 0.25 worth 12.5 -> 50 per price unit, not 1250):
 // ATR 10, SL 15: 500 / (15 x 50) = 0.666 -> 0.66 (tv / point would give 0.02).
 const idxPath=path(MON,[[2*H1,18000.00],[3*H1,18000.00]]);
 const idx=single({atr1:10,atr0:30,bid:18000,spread:1,tickSize:0.25,world:{point:0.01,digits:2,tickValue:12.5}});idx.run(idxPath);
 assert.ok(near(sends(idx)[0].volume,0.66),'a tick size other than the point: '+sends(idx).map(x=>x.volume));
 ok();
}
// 1c. The lot never exceeds Risk / (SL x tv / ts), whatever the tick value, tick size, ATR, risk and volume grid:
// GoatSingleOpen called directly on an idle sequence over a seeded sweep; when it opens, the lot is the largest
// step multiple within the risk (or the maximum, or the volume-minimum grid below it).
{
 const W=single();let seed=20261027;const rnd=()=>(seed=(seed*48271)%2147483647)/2147483647;
 const pick=a=>a[Math.floor(rnd()*a.length)];
 let opened=0,refused=0;
 for(let n=0;n<400;n++){
  const point=pick([1e-5,1e-3,1e-2,1]),ts=point*pick([1,1,5,25]),tv=pick([0.01,0.6667,1,2.5,12.5,0])*pick([1,1,10]);
  const step=pick([0.01,0.01,0.1,1]),vmin=step*pick([1,1,5,10]),vmax=pick([5,50,100,1000]);
  const atr=point*pick([20,100,333,1500]),risk=pick([10,250,500,5000,123456]);
  Object.assign(W.w,{point,digits:Math.max(0,Math.round(-Math.log10(point))),tickValue:tv,volumeStep:step,volumeMin:vmin,volumeMax:vmax,stopsLevel:0});
  const K=W.ctx.SYMBOL_TRADE_TICK_SIZE,orig=W.w.__sid||(W.w.__sid=W.ctx.SymbolInfoDouble);
  W.ctx.SymbolInfoDouble=(sym,k,box)=>{if(k!==K)return orig(sym,k,box);if(box){box.v=ts;return true;}return ts;};
  W.ctx._Point=point;W.ctx._Digits=W.w.digits;
  W.w.bid=1000*point*pick([1,10,100]);W.w.ask=W.w.bid;   // no spread: the stops check reads the stop alone
  W.w.indicator=(name,b,shift)=>name==='ATR_MA'&&shift===1?atr:undefined;
  W.setInput('Risk',risk);
  const before=sends(W).length,b=W.ctx.Seq_Buy;
  const did=W.ctx.GoatSingleOpen(b,W.w.ask);
  const sl=1.5*atr,cap=tv>0&&ts>0?risk/(sl*(tv/ts)):0;
  if(!did){assert.equal(sends(W).length,before,'a refusal sends nothing');refused++;continue;}
  const vol=sends(W).at(-1).volume;opened++;
  assert.ok(tv>0&&ts>0,'opened only with a tick value and size');
  assert.ok(vol<=cap*(1+1e-9)+1e-12,`lot ${vol} <= Risk/(SL x tv/ts) = ${cap} (tv ${tv}, ts ${ts}, sl ${sl}, risk ${risk})`);
  assert.ok(vol>=vmin-1e-12&&vol<=vmax+1e-12,'within the volume limits');
  const floorStep=Math.min(Math.floor(cap/step+1e-9)*step,vmax);
  assert.ok(vol>=Math.floor(floorStep/vmin+1e-9)*vmin-1e-9,`and the largest lot the grid allows (${vol} vs ${floorStep})`);
  b.End_Sequence('sweep');W.w.positions.length=0;
 }
 assert.ok(opened>=100&&refused>=40,'the sweep exercises both ('+opened+' opened, '+refused+' refused)');
 ok();
}
// 2. Below the volume minimum: refused, logged once, nothing sent, still armed; a later SET that fits opens.
{
 const W=single({inputs:{Risk:10,Single_SL_ATR:100}});   // 10 / (0.1 x 1e5) = 0.001 lots < 0.01
 W.run(FLAT);
 assert.equal(sends(W).length,0,'refused below the volume minimum: never rounded up to it');
 assert.equal(refusals(W).length,1,'the refusal is logged once while it repeats: '+refusals(W).join(' | '));
 assert.match(refusals(W)[0],/below the volume minimum/);
 assert.equal(W.ctx.Seq_Buy.Active,false);assert.equal(W.ctx.g_GoatSingleArmed[0],true,'a refusal does not consume the episode');
 W.setInput('Risk',200);W.run(path(MON,[[3*H1,1.1000],[3*H1+80,1.1000]]));   // 200 / 10000 = 0.02 lots
 assert.equal(sends(W).length,1);assert.equal(sends(W)[0].volume,0.02);
 ok();
}
// 3. FixedLots and ScaledLots, as Add_Level: the lot input, normalized.
{
 const F=single({inputs:{Mode_Lots:'FixedLots',Lots_Input:0.37}});F.run(FLAT);assert.equal(sends(F)[0].volume,0.37,'FixedLots');
 const S=single({inputs:{Mode_Lots:'ScaledLots',Lots_Input:0.5}});S.run(FLAT);
 assert.equal(sends(S)[0].volume,0.5,'ScaledLots at the starting equity');
 const Z=single({inputs:{Mode_Lots:'FixedLots',Lots_Input:0.004}});Z.run(FLAT);
 assert.equal(sends(Z).length,0,'FixedLots below the volume minimum is refused, never sent as 0 lots');
 assert.equal(refusals(Z).length,1);
 ok();
}
// 4. The ATR of the closed bar (shift 1), read into a local buffer: ATR_Buf and ATR_Pips never change.
{
 const W=single();
 const buf=JSON.stringify(W.ctx.ATR_Buf),pips=W.ctx.ATR_Pips;
 W.run(FLAT);
 const s=sends(W)[0];
 assert.ok(near(s.price-s.sl,0.0015,1e-8),'SL from shift 1 (0.0010 x 1.5), not the forming bar (0.0030): '+(s.price-s.sl));
 assert.ok(near(W.ctx.Seq_Buy.Size_SL,0.0015,1e-12));
 assert.equal(JSON.stringify(W.ctx.ATR_Buf),buf,'ATR_Buf untouched');assert.equal(W.ctx.ATR_Pips,pips,'ATR_Pips untouched');
 // No ATR on the closed bar (the read fails, or reads 0): refused, logged once.
 for(const atr1 of [null,0]){   // null: CopyBuffer fails
  const N=single({atr1});N.run(FLAT);
  assert.equal(sends(N).length,0,'no ATR: refused ('+atr1+')');assert.equal(refusals(N).length,1);assert.match(refusals(N)[0],/no ATR/);
 }
 ok();
}
// 5. Size_TP: Single_TP_R x Size_SL wins over Single_TP_ATR x ATR; else the ATR TP; else none.
{
 const tp=inputs=>{const W=single({inputs});W.run(FLAT);const s=sends(W)[0];return {d:s.tp?s.tp-s.price:0,size:W.ctx.Seq_Buy.Size_TP,W};};
 const r=tp({Single_TP_R:2,Single_TP_ATR:5});
 assert.ok(near(r.d,0.0030,1e-8)&&near(r.size,0.0030,1e-12),'TP_R wins: 2 x 0.0015 ('+r.d+')');
 assert.ok(near(r.W.ctx.Seq_Buy.Level_TP,sends(r.W)[0].price+0.0030,1e-8),'UpdateLockTPSL: Level_TP at the entry + Size_TP');
 const a=tp({Single_TP_ATR:5});assert.ok(near(a.d,0.0050,1e-8)&&near(a.size,0.0050,1e-12),'the ATR TP: 5 x 0.0010 ('+a.d+')');
 const n=tp({});assert.equal(sends(n.W)[0].tp,0,'no TP');assert.equal(n.size,0);assert.equal(n.W.ctx.Seq_Buy.Level_TP,999999);
 ok();
}
// 6. The stop must clear the stops level plus the spread (10 points here).
{
 const T=single({world:{stopsLevel:150}});T.run(FLAT);   // 0.0015 <= (150 + 10) x 1e-5
 assert.equal(sends(T).length,0,'stop inside the stops level + spread: refused');
 assert.equal(refusals(T).length,1);assert.match(refusals(T)[0],/inside the stops level plus the spread/);
 const E=single({world:{stopsLevel:140}});E.run(FLAT);   // 0.0015 <= 0.0015: on the boundary, refused
 assert.equal(sends(E).length,0,'a stop on the boundary is refused');
 const O=single({world:{stopsLevel:100}});O.run(FLAT);   // 0.0015 > 0.0011
 assert.equal(sends(O).length,1,'a stop outside opens');
 // The TP too (GOAT-EA#272 P3): Size_TP + the spread must clear the stops level.
 const P=single({inputs:{Single_TP_ATR:0.9},world:{stopsLevel:100}});P.run(FLAT);   // 0.0009 + 0.0001 <= 0.0010
 assert.equal(sends(P).length,0,'a TP inside the stops level: refused');assert.match(refusals(P)[0],/take profit .* inside the stops level/);
 const Q=single({inputs:{Single_TP_ATR:1},world:{stopsLevel:100}});Q.run(FLAT);   // 0.0010 + 0.0001 > 0.0010
 assert.equal(sends(Q).length,1,'a TP outside opens');
 ok();
}
// 7. No virtual leg (Delay_Trade=1, Delay_Trade_Live=1, the defaults), no grid add, one level; the sizes at start.
for(const fastSpeed of [true,false]){
 const W=single({fastSpeed});
 assert.equal(W.ctx.Delay_Trade,1);assert.equal(W.ctx.Delay_Trade_Live,1);
 const p=path(MON,[[2*H1,1.1000],[6*H1,1.0988],[9*H1,1.0990]]);   // falls 12 points of a 15-point stop: a grid would add
 let firstSend=null;
 for(const [t,bid] of p){W.tick(t,bid);if(firstSend===null&&sends(W).length)firstSend=t;
  assert.equal(W.ctx.Seq_Buy_Virtual.Active,false,'no virtual leg');assert.equal(W.ctx.Seq_Sell_Virtual.Active,false);}
 assert.ok(firstSend!==null&&firstSend<=p[0][0]+120,'the single opens on the signal\'s first minute, with no virtual level before it');
 assert.equal(sends(W).length,1,'no grid add (fastSpeed='+fastSpeed+')');
 const b=W.ctx.Seq_Buy;
 assert.equal(b.Level_Count,1);assert.equal(b.Trades_Count,1);assert.equal(b.Active&&b.Traded,true);
 assert.equal(b.Size_Grid,0);assert.equal(b.Size_Lock,0);assert.equal(b.Size_TSL,0);
 assert.equal(b.Level_Lock,999999,'the lock is parked: nothing trails');
 assert.equal(W.w.trace.filter(x=>x.op==='PositionModify').length,0,'no trailing modify');
 assert.equal(W.ctx.Sequences,1,'Sequences++');
 assert.ok(!W.w.logs.some(l=>/Virtual|Delayed/.test(l)),'no virtual or delayed level logged');
 assert.equal(b.TradeLevels[0].ticket,W.w.positions[0].ticket);assert.equal(b.TradeLevels[0].lots,3.33);
 assert.ok(near(b.Level_SL,W.w.positions[0].sl,1e-12),'Level_SL is the broker stop');
 // GoatSingleOpen itself refuses a sequence that is already running (no add onto a single).
 assert.equal(W.ctx.GoatSingleOpen(b,W.w.ask),false,'GoatSingleOpen on a running sequence');
 assert.equal(sends(W).length,1);
 ok();
}
// 8. One position per signal episode: after the single's TP the buy signal still holds, so nothing opens; the signal
// reads false (RSI 50), which re-arms; the next episode opens one more.
for(const fastSpeed of [true,false]){
 const W=single({fastSpeed,inputs:{Single_TP_R:1},rsi:[[0,25],[4*H1,50],[5*H1,25]]});
 W.run(path(MON,[[2*H1,1.1000],[3*H1,1.1030],[9*H1,1.1030]]));
 const s=sends(W);
 assert.ok(W.w.trace.some(x=>x.op==='BrokerTake'),'the first single takes its profit inside the episode');
 assert.equal(s.length,2,'one single per episode (fastSpeed='+fastSpeed+'): '+s.map(x=>(x.time-MON)/H1).join(','));
 assert.ok(s[1].time>=MON+5*H1,'the second opens only after the false edge');
 assert.ok(s[1].time<MON+5*H1+120,'and at once in the next episode');
 assert.equal(W.ctx.g_GoatSingleArmed[0],false,'disarmed by the open');assert.equal(W.ctx.g_GoatSingleArmed[1],true,'the sell side stays armed');
 ok();
}
// 9. Sell, and Reverse_Seq: the buy signal opens a sell single; the episode is the signal's.
{
 const S=single({rsi:[[0,80]]});S.run(FLAT);
 const s=sends(S)[0];assert.equal(s.type,1,'a sell');assert.equal(s.price,S.w.positions[0].open);
 assert.ok(near(s.sl-s.price,0.0015,1e-8),'the sell stop is above');assert.equal(S.ctx.Seq_Sell.Level_Lock,0,'the sell lock is parked at 0');
 assert.equal(S.ctx.g_GoatSingleArmed[1],false);
 const R=single({inputs:{Reverse_Seq:true}});R.run(FLAT);
 assert.equal(sends(R).length,1);assert.equal(sends(R)[0].type,1,'Reverse_Seq: the buy signal sells');
 assert.equal(R.ctx.g_GoatSingleArmed[0],false,'the buy-signal episode is consumed');assert.equal(R.ctx.g_GoatSingleArmed[1],true);
 const L=single({inputs:{Mode_Trade:'Long'},rsi:[[0,80]]});L.run(FLAT);assert.equal(sends(L).length,0,'Mode_Trade gates a single');
 ok();
}
// 10. The gating chain stays SignalEntryTrigger's: DashboardEntryAllowed and the news gate refuse a single.
{
 const D=single();D.ctx.DashboardEntryAllowed=()=>false;D.run(FLAT);assert.equal(sends(D).length,0,'DashboardEntryAllowed');
 assert.equal(D.ctx.g_GoatSingleArmed[0],true);
 const M=single({inputs:{Mode_News:'News_Pause'}});M.w.news=()=>true;M.run(FLAT);assert.equal(sends(M).length,0,'the news gate');
 ok();
}
// 11. Add_Level's freezes, in order before the order: the CID freeze, then manage-only.
{
 const C=single();const cid=[];C.ctx.GoatCidGuardAddFrozen=(d,l)=>{cid.push([d,l]);return true;};
 C.run(FLAT.slice(0,30));
 assert.equal(sends(C).length,0,'cid_duplicate freezes a single');assert.deepEqual(cid[0],[0,1],'asked for the buy side, level 1');
 C.ctx.GoatCidGuardAddFrozen=()=>false;C.run(FLAT.slice(30,34));assert.equal(sends(C).length,1,'the episode opens once the freeze lifts');
 const M=single();M.ctx.Seq_Buy.PersistFailed=true;M.run(FLAT.slice(0,30));
 assert.equal(sends(M).length,0,'an unwritten restart record freezes a single (manage-only)');
 assert.ok(M.w.logs.some(l=>/add_frozen=record_unwritten/.test(l)));
 ok();
}
// 11b. The build's expiry, checked first as in Add_Level: an expired build opens nothing and removes itself.
{
 const W=single();W.ctx.Expiry=MON;W.run(FLAT.slice(0,6));
 assert.equal(sends(W).length,0,'an expired build opens no single');assert.equal(W.w.removed,true,'ExpertRemove');
 assert.ok(W.w.alerts.some(a=>/expired/.test(a)));
 ok();
}
// 12. The direction guard: a denial sends nothing and keeps no sizes; the episode stays armed.
{
 const W=single();W.ctx.GoatDirectionGuardBegin=()=>false;
 W.run(FLAT.slice(0,10));
 assert.equal(sends(W).length,0);assert.equal(W.w.positions.length,0);
 const b=W.ctx.Seq_Buy;
 for(const k of ['Size_Grid','Size_Lock','Size_TP','Size_SL','Size_TSL']) assert.equal(b[k],1234.5,'a denial resets '+k);
 assert.equal(b.StartLots,0);assert.equal(b.Active,false);assert.equal(W.ctx.g_GoatSingleArmed[0],true);
 assert.ok(!W.w.logs.some(l=>/order failed/.test(l)),'a denial is not a failed order');
 W.ctx.GoatDirectionGuardBegin=()=>true;W.run(FLAT.slice(10,14));   // SignalEntryTrigger runs once a minute here
assert.equal(sends(W).length,1);
 // A rejected order: nothing starts, the sizes go back to the sentinel, the failure is logged.
 const R=single({world:{rejectOrders:true}});R.run(FLAT.slice(0,6));assert.ok(R.w.trace.some(x=>x.op==='OrderSend'),'the order was sent');
 assert.equal(R.ctx.Seq_Buy.Active,false);assert.equal(R.ctx.Seq_Buy.Size_SL,1234.5);
 R.run(FLAT.slice(6,40));assert.ok(sends(R).length>=5,'retried on each signal check while armed');
 assert.equal(R.w.logs.filter(l=>/Single refused \(order failed/.test(l)).length,1,'a failed order is logged once while it repeats (GOAT-EA#272 P3)');
 ok();
}
// 13. The ledger join, the entry commission, the restart record and UpdateLockTPSL run after the order, in order.
{
 const W=single({tester:false,fastSpeed:false,inputs:{Ledger_Mode:'Ledger_PositionJoin'},world:{commissionPerLot:7}});
 const calls=[];const b=W.ctx.Seq_Buy;
 for(const m of ['LedgerAddPosition','AccumulateSequenceDealPL','PersistStart','PersistLevels','UpdateLockTPSL']){
  const orig=b[m].bind(b);b[m]=(...a)=>{calls.push(m);return orig(...a);};
 }
 const send=W.ctx.OrderSend;W.ctx.OrderSend=(q,r)=>{calls.push('OrderSend');return send(q,r);};
 W.run(FLAT.slice(0,5));
 assert.equal(sends(W).length,1);
 const i=calls.indexOf('OrderSend');
 assert.deepEqual(calls.slice(i,i+5),['OrderSend','LedgerAddPosition','AccumulateSequenceDealPL','PersistStart','UpdateLockTPSL'],'Add_Level\'s order: '+calls.slice(i,i+6));
 const pos=W.w.positions[0];
 assert.deepEqual([...b.LedgerPositions],[pos.identifier],'the position joins the single');
 assert.ok(near(b.SequenceRealizedPL,-7*pos.volume,1e-9),'the entry commission is booked once: '+b.SequenceRealizedPL);
 const key=[...W.w.gv.keys()].find(k=>/_SQ_\d+_EURUSD_B_T$/.test(k));
 assert.ok(key,'the restart record is written: '+[...W.w.gv.keys()].join(','));
 const sl=[...W.w.gv].find(([k])=>/_SQ_\d+_EURUSD_B_SL$/.test(k));
 assert.ok(sl&&near(sl[1],0.0015,1e-12),'it freezes the single\'s stop size');
 const tk=[...W.w.gv].find(([k])=>/_SQ_\d+_EURUSD_B_TK$/.test(k));assert.equal(tk[1],pos.ticket);
 ok();
}
// 14. The grid engine never reaches GoatSingleOpen, and a single never arms anything the grid reads (flags off).
{
 const G=H.build(undefined,{inputs:{...BASE,Engine_Mode:'Engine_Grid',Delay_Trade:0,Delay_Trade_Live:0},indicator:(n,b,sh,w)=>n==='ATR_MA'?0.0010:(n==='RSI'?25:undefined)});
 const calls=[];const orig=G.ctx.GoatSingleOpen;G.ctx.GoatSingleOpen=(...a)=>{calls.push(1);return orig(...a);};
 G.run(FLAT);assert.equal(calls.length,0,'Engine_Grid never calls GoatSingleOpen');assert.ok(sends(G).length>=1,'the grid opens as before');
 assert.ok(!G.w.logs.some(l=>/Single (Filled|refused)/.test(l)));
 ok();
}

console.log(JSON.stringify({passed,test:'b50_single'}));
