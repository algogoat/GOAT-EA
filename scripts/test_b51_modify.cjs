// B51 single break-even and trailing (B50-beta-1b, docs/b50/B50_ALPHA_DESIGN.md section 8.2): GoatSingleModify on the
// real OnTick path. scripts/b50_tick_harness.cjs converts this tree's GoatTickBody (GoatSingleModify runs on the
// trailing cadence, Trailing_Sample_Period=Second), GoatSingleOpen and the SEQUENCE methods, and runs them against the
// modelled terminal (EURUSD, 5 digits, spread 10 points; a refused PositionModify is world.rejectModify).
// The single: a buy at ask 1.10010 (sell: at bid 1.10000) on RSI_OverBS, ATR 0.0010 on the closed bar (0.0030 on the
// forming one, so a read of the wrong bar shows), Single_SL_ATR 1.5 (stop 15 points).
// Proves:
// - break-even fires at Single_BE_ATR x ATR in favour and not one point before, and sends the entry price exactly with
//   the TP unchanged; a fractional threshold rounds up to the next point;
// - trailing starts at Single_Trail_Start_ATR x ATR, trails Single_Trail_ATR x ATR behind the price, and the SL only
//   ever moves in the trade's favour (buy and sell); every SL is legal (max(STOPS_LEVEL, FREEZE_LEVEL, 1) points);
// - the entry's ATR is used (Size_SL / Single_SL_ATR), never the forming bar's;
// - flags off (all three 0) the tree trades exactly as B50-alpha (32df4eb); a trailing start without a distance and
//   any of the three with the grid engine are OnInit refusals;
// - a failed modify logs one line with the ticket, bid, ask, stops and freeze levels, the current SL and TP, the
//   requested SL, the return code and the consecutive count; from the 5th consecutive failure it backs off 1 s, 5 s,
//   30 s, then 60 s steady, one line per attempt and none inside a wait; one success clears the count; two tickets back
//   off independently; a stuck ticket keeps logging once a minute;
// - a moved SL survives a live restart (adoption keeps the broker SL; the trailing carries on from it), and an adopted
//   single without its frozen sizes is left alone; UpdateLockTPSL runs once per single (at its open);
// - the trailed stop ends the single through the broker (the sequence ends, the next episode opens);
// - OnInit refuses a negative distance; the sell's clamp, a clamped break-even's minimum step, nine failing tickets in
//   turn (slot reuse) and the run's TSL counters (review of GOAT-EA#287).
// scripts/test_b51_modify_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail it.
// What it does not prove: compile cleanliness or a real broker's modify rules. The MetaEditor compile and a native run do.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const B50_ALPHA='32df4eb';
let passed=0;const ok=()=>passed++;

const MON=Date.UTC(2026,9,5)/1000,H1=3600,PT=1e-5,T0=MON+2*H1;   // T0: 02:00, the single opens at 01:51 (below)
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500};
const indicator=rsiValue=>(name,buffer,shift,w)=>{
 if(name==='ATR_MA') return shift===1?0.0010:0.0030;
 if(name==='RSI') return typeof rsiValue==='function'?rsiValue(w.time):rsiValue;
 return undefined;};
// One tick per second along [seconds after T0, bid] points (linear), bids normalized by the harness.
function ticks(points,step=1){const t=[];for(let k=1;k<points.length;k++){const [a,p]=points[k-1],[b,q]=points[k];for(let s=a;s<b;s+=step)t.push([T0+s,p+(q-p)*(s-a)/(b-a)]);}return t;}
const OPEN=ticks([[-600,1.1000],[0,1.1000]],20);   // 01:50 to 02:00 at 1.10000: the single opens on the first signal check
function world({inputs={},rsi=25,source,tester=true,fastSpeed=true,world:wx={},adopt,start,bid,spread}={}){
 return H.build(source,{inputs:{...BASE,...inputs},tester,fastSpeed,indicator:indicator(rsi),world:wx,adopt,start,bid,spread});
}
const mods=W=>W.w.trace.filter(x=>x.op==='PositionModify');
const fails=W=>W.w.logs.filter(l=>/Single SL modify failed/.test(l));
const field=(line,name)=>{const m=line.match(new RegExp('(?:^|\\s)'+name+'=([^\\s]+)'));assert.ok(m,'the line carries '+name+': '+line);return m[1];};
const near=(a,b,eps=1e-9)=>Math.abs(a-b)<=eps;
function opened(W,type=0){W.run(OPEN);const s=W.w.trace.filter(x=>x.op==='OrderSend');assert.equal(s.length,1,'the single opens');assert.equal(s[0].type,type);
 assert.equal(mods(W).length,0,'no modify at the open');return {...W.w.positions[0]};}   // a copy: the position at its open

// 1. Break-even: at the threshold and not one point before; the entry exactly; the TP unchanged; sell too.
{
 const W=world({inputs:{Single_BE_ATR:1,Single_TP_R:3}});const p=opened(W);
 assert.ok(near(p.open,1.10010)&&near(p.sl,1.09860)&&near(p.tp,1.10460),'buy 1.10010, SL 1.09860, TP 1.10460');
 W.run(ticks([[0,1.1000],[60,1.10109],[120,1.10109]]));        // 99 points in favour: 1 point short of 1 ATR (100)
 assert.equal(mods(W).length,0,'nothing before Single_BE_ATR x ATR in favour (1 point short)');
 W.run(ticks([[120,1.10110],[180,1.10110]]));
 assert.equal(mods(W).length,1,'break-even at the threshold, once');
 const m=mods(W)[0];assert.equal(m.time,T0+120,'on the first check at the threshold');
 assert.equal(m.sl,p.open,'the SL goes to the entry exactly (no spread, no commission)');assert.ok(near(m.tp,1.10460),'the TP is unchanged');
 assert.equal(W.ctx.Seq_Buy.Level_SL,p.open,'Level_SL follows');assert.equal(W.ctx.Seq_Buy.TradeLevels[0].sl,p.open);
 W.run(ticks([[180,1.10110],[240,1.10040],[300,1.10120]]));
 assert.equal(mods(W).length,1,'never moved back, never sent twice');assert.equal(W.w.positions[0].sl,p.open);
 // A fractional threshold (1.035 ATR = 103.5 points) needs 104 points: 103 never fires.
 const F=world({inputs:{Single_BE_ATR:1.035}});opened(F);
 F.run(ticks([[0,1.1000],[30,1.10113],[90,1.10113]]));assert.equal(mods(F).length,0,'103 points < 103.5');
 F.run(ticks([[90,1.10114],[120,1.10114]]));assert.equal(mods(F).length,1,'104 points >= 103.5');
 // The sell: in favour is open - ask; the SL goes to the sell's entry (bid 1.10000).
 const S=world({inputs:{Single_BE_ATR:1},rsi:80});const q=opened(S,1);
 assert.ok(near(q.open,1.10000)&&near(q.sl,1.10150));
 S.run(ticks([[0,1.1000],[60,1.09891],[120,1.09891]]));assert.equal(mods(S).length,0,'ask 1.09901: 99 points, 1 short');
 S.run(ticks([[120,1.09890],[180,1.09890]]));assert.equal(mods(S).length,1);assert.equal(mods(S)[0].sl,q.open,'the sell\'s entry');
 ok();
}

// 2. Trailing: starts at Single_Trail_Start_ATR x ATR, trails Single_Trail_ATR x ATR behind, only ever in favour.
const TRAIL={Single_Trail_Start_ATR:2,Single_Trail_ATR:0.5};
{
 const W=world({inputs:TRAIL});const p=opened(W);
 const path=ticks([[0,1.1000],[300,1.10209],[400,1.1041],[600,1.1030],[800,1.1045],[1000,1.1035],[1200,1.1035]]);
 const bidAt=new Map(path.map(([t,b])=>[t,Number(b.toFixed(5))]));
 W.run(path);
 const m=mods(W);assert.ok(m.length>=10,'it trails ('+m.length+' modifies)');
 assert.ok(bidAt.get(m[0].time)-p.open>=0.0020-1e-9,'not before 2 ATR in favour');
 assert.ok(m[0].time>T0+300,'1.10209 is 199 points: no trailing yet');
 let prev=p.sl;
 for(const x of m){
  const b=bidAt.get(x.time);
  assert.ok(x.sl>prev,'the SL only moves up: '+x.sl+' after '+prev);
  assert.ok(near(x.sl,Number((b-0.0005).toFixed(5)),1e-9),'0.5 ATR behind the bid at '+(x.time-T0)+': '+x.sl+' vs '+b);
  assert.ok(x.sl<=b-PT+1e-9,'legal');
  if(prev!==p.sl) assert.ok(x.sl-prev>=Math.max(0.0001*b,5*PT)-1e-9,'by at least the minimum step');
  prev=x.sl;assert.ok(near(x.tp,0));
 }
 assert.ok(!m.some(x=>x.time>T0+400&&x.time<T0+700),'no modify while the price falls back');
 const stop=W.w.trace.find(x=>x.op==='BrokerStop');assert.ok(stop,'the trailed stop is hit');
 assert.ok(near(stop.price,m.at(-1).sl),'at the last trailed SL');
 assert.equal(W.ctx.Seq_Buy.Active,false,'the sequence ends on the broker stop');
 assert.ok(stop.price>p.open,'a locked profit');
 // The sell, mirrored: the SL only moves down.
 const S=world({inputs:TRAIL,rsi:80});const q=opened(S,1);
 const spath=ticks([[0,1.1000],[300,1.0960],[500,1.0975],[700,1.0975]]);
 const askAt=new Map(spath.map(([t,b])=>[t,Number((Number(b.toFixed(5))+0.0001).toFixed(5))]));
 S.run(spath);
 assert.ok(S.w.trace.some(x=>x.op==='BrokerStop'),'the trailed sell stop is hit');
 const n=mods(S);assert.ok(n.length>=10);let last=q.sl;
 for(const x of n){
  assert.ok(x.sl<last,'the sell SL only moves down');last=x.sl;
  assert.ok(near(x.sl,Number((askAt.get(x.time)+0.0005).toFixed(5)),1e-9),'0.5 ATR above the ask at '+(x.time-T0)+': '+x.sl);
 }
 ok();
}

// 3. Every SL is legal: stops 30 and freeze 50 points; break-even at 0.3 ATR (30 points) is clamped to bid - 50 points.
{
 const W=world({inputs:{Single_BE_ATR:0.3,...TRAIL},world:{stopsLevel:0}});opened(W);
 W.w.stopsLevel=30;W.w.freezeLevel=50;
 // At 1.10050 the clamped break-even is 1.10000; a dip to 1.10045 keeps break-even due (35 points in favour) while its
 // legal level (1.09995) is below the SL already set: the SL must stay, never step back.
 const path=ticks([[0,1.1000],[60,1.10050],[120,1.10050],[121,1.10045],[180,1.10045],[400,1.1045],[500,1.1045]]);
 const bidAt=new Map(path.map(([t,b])=>[t,Number(b.toFixed(5))]));
 W.run(path);
 const m=mods(W);assert.ok(m.length>=3);
 let prev=0;for(const x of m){assert.ok(x.sl>prev,'never back: '+x.sl+' after '+prev);prev=x.sl;}
 assert.ok(!m.some(x=>x.time>=T0+121&&x.time<T0+180),'no modify during the dip');
 for(const x of m) assert.ok(x.sl<=bidAt.get(x.time)-50*PT+1e-9,'at least the freeze level from the bid: '+x.sl+' vs '+bidAt.get(x.time));
 assert.ok(near(m[0].sl,Number((bidAt.get(m[0].time)-50*PT).toFixed(5))),'break-even clamped to the nearest legal level');
 assert.ok(m[0].sl<1.10010,'below the entry: the legal part of the move');
 ok();
}

// 3b. The sell's clamp (review P2-7): stops 30, freeze 50 and a spread of 10 points: every SL >= ask + 50 points.
{
 const W=world({inputs:{Single_BE_ATR:0.3,...TRAIL},rsi:80});const q=opened(W,1);
 W.w.stopsLevel=30;W.w.freezeLevel=50;
 const path=ticks([[0,1.1000],[60,1.09950],[120,1.09950],[400,1.0955],[500,1.0955]]);
 const askAt=new Map(path.map(([t,b])=>[t,Number((Number(b.toFixed(5))+0.0001).toFixed(5))]));
 W.run(path);
 const m=mods(W);assert.ok(m.length>=3,'the sell is managed ('+m.length+')');
 for(const x of m) assert.ok(x.sl>=askAt.get(x.time)+50*PT-1e-9,'at least the freeze level above the ask: '+x.sl+' vs '+askAt.get(x.time));
 assert.ok(near(m[0].sl,Number((askAt.get(m[0].time)+50*PT).toFixed(5))),'break-even clamped to ask + 50 points');
 assert.ok(m[0].sl>q.open,'above the entry: the legal part of the move');
 let prev=q.sl;for(const x of m){assert.ok(x.sl<prev,'the sell SL only moves down');prev=x.sl;}
 ok();
}

// 3c. A clamped break-even then moves by the minimum step (review P3-9): no modify a second while the price creeps up;
//     the move to the entry itself, once legal, goes at once (break-even is the entry, or the closest legal level).
{
 const W=world({inputs:{Single_BE_ATR:0.3}});const p=opened(W);
 W.w.stopsLevel=50;
 // 1.10050: clamped to 1.10000. Then a point a second up to 1.10059: each legal level only 1..9 points better.
 W.run(ticks([[0,1.10050],[30,1.10050]]));assert.equal(mods(W).length,1);assert.ok(near(mods(W)[0].sl,1.10000));
 W.run(ticks([[30,1.10050],[39,1.10059],[60,1.10059]]));
 assert.equal(mods(W).length,1,'no sub-step move of a clamped break-even (9 points < the 11-point minimum step)');
 // 1.10060: the entry (1.10010) is legal: the last 10 points go at once, to the entry exactly.
 W.run(ticks([[60,1.10060],[90,1.10060]]));
 assert.equal(mods(W).length,2,'the move to the entry itself');assert.equal(mods(W)[1].sl,p.open);
 W.run(ticks([[90,1.10200],[150,1.10200]]));assert.equal(mods(W).length,2,'break-even done (no trailing): nothing more');
 ok();
}

// 4. The entry's ATR: the forming bar's (0.0030) would put break-even at 300 points; it fires at 100.
{
 const W=world({inputs:{Single_BE_ATR:1}});opened(W);
 assert.ok(near(W.ctx.Seq_Buy.Size_SL/1.5,0.0010,1e-12));
 W.run(ticks([[0,1.1000],[30,1.10110],[60,1.10110]]));assert.equal(mods(W).length,1,'at 1 x the entry ATR');
 ok();
}

// 5. Flags off: the three inputs at 0 never modify; the tree trades as B50-alpha. A trailing start without a distance,
//    and any of the three with the grid engine, are OnInit refusals (review of GOAT-EA#287, P3-10).
{
 const path=[...OPEN,...ticks([[0,1.1000],[600,1.1060],[900,1.1010],[1200,1.1060]],5)];
 for(const [label,inputs] of [['all off',{}],['TP in R',{Single_TP_R:4}]]){
  const tree=world({inputs}),alpha=H.build(B50_ALPHA,{inputs:{...BASE,...inputs},indicator:indicator(25)});
  tree.run(path);alpha.run(path);
  assert.equal(mods(tree).length,0,label+': no modify');
  assert.deepEqual(tree.w.trace,alpha.w.trace,label+': as B50-alpha');
 }
 const refused=inputs=>{try{world({inputs});return null;}catch(e){assert.ok(e.initCode!==undefined,e.message);return e.initCode;}};
 assert.equal(refused({Single_Trail_Start_ATR:1}),2,'a trailing start without a distance is refused');
 assert.equal(refused({Single_Trail_Start_ATR:1,Single_Trail_ATR:0.5}),null,'with a distance it passes');
 assert.equal(refused({Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5}),null,'a distance without a start passes (trails from the entry)');
 for(const k of ['Single_BE_ATR','Single_Trail_ATR']) assert.equal(refused({Engine_Mode:'Engine_Grid',[k]:1,Single_Trail_ATR:1}),2,k+' with the grid engine is refused');
 assert.equal(refused({Engine_Mode:'Engine_Grid',Single_Trail_Start_ATR:1,Single_Trail_ATR:1}),2);
 assert.equal(refused({Engine_Mode:'Engine_Grid'}),null,'the grid engine with the three at 0 passes');
 ok();
}

// 6. A failed modify: one line with every field.
const reject=(W,pred=()=>true)=>{W.w.rejectModify=(t,sl,tp,w)=>pred(t,w);W.w.modifyRetcode=10016;};
{
 const W=world({inputs:{Single_BE_ATR:1,Single_TP_R:3}});const p=opened(W);
 W.w.stopsLevel=3;W.w.freezeLevel=7;reject(W);
 W.run(ticks([[0,1.10110],[1,1.10110]]));
 assert.equal(mods(W).length,1);const f=fails(W);assert.equal(f.length,1,'one line for one failure');
 const l=f[0];
 assert.match(l,/^GOAT_Trading Buy: Single SL modify failed: /);
 assert.equal(field(l,'ticket'),String(p.ticket));assert.equal(field(l,'bid'),'1.10110');assert.equal(field(l,'ask'),'1.10120');
 assert.equal(field(l,'stops_level'),'3');assert.equal(field(l,'freeze_level'),'7');
 assert.equal(field(l,'sl'),'1.09860');assert.equal(field(l,'tp'),'1.10460');assert.equal(field(l,'requested_sl'),'1.10010');
 assert.equal(field(l,'retcode'),'10016');assert.equal(field(l,'consecutive'),'1');assert.ok(!/backoff=/.test(l),'no back-off before the limit');
 assert.ok(near(W.w.positions[0].sl,p.sl),'the broker SL is unchanged');assert.ok(near(W.ctx.Seq_Buy.Level_SL,p.sl),'and so is Level_SL');
 ok();
}

// 7. The back-off: 5 attempts a second apart, then waits of 1, 5, 30 and 60 s; one line per attempt, none in a wait.
function schedule(start,until){const t=[];let at=start,n=0;while(at<=until){t.push(at);n++;at+=n<5?1:(n===5?1:(n===6?5:(n===7?30:60)));}return t;}
{
 const W=world({inputs:{Single_BE_ATR:1}});opened(W);reject(W);
 W.run(ticks([[0,1.10110],[1300,1.10110]]));
 const times=mods(W).map(x=>x.time-T0);
 assert.deepEqual(times,schedule(0,1299),'attempts at '+times.join(','));
 assert.deepEqual(times.slice(0,10),[0,1,2,3,4,5,10,40,100,160]);
 const f=fails(W);assert.equal(f.length,times.length,'one line per failed attempt (never one per tick)');
 assert.deepEqual(f.map(l=>Number(field(l,'consecutive'))),times.map((_,i)=>i+1));
 assert.deepEqual(f.slice(0,4).map(l=>/backoff=/.test(l)),[false,false,false,false],'no back-off before the 5th');
 assert.deepEqual(f.slice(4,9).map(l=>field(l,'backoff')),['1s','5s','30s','60s','60s'],'then 1 s, 5 s, 30 s and 60 s steady');
 // A stuck ticket stays visible: a line every minute.
 const late=f.filter((l,i)=>times[i]>=600);assert.ok(late.length>=11,'still logging after 10 minutes ('+late.length+')');
 assert.ok(late.every(l=>field(l,'backoff')==='60s'));
 ok();
}

// 8. One success clears the count: three failures, a success (logged as recovered), then a new failure is the first.
{
 const W=world({inputs:{Single_BE_ATR:1,...TRAIL}});const p=opened(W);
 let n=0;W.w.rejectModify=(t,sl,tp,w)=>{n++;return n<=3||w.time>=T0+400;};W.w.modifyRetcode=10006;
 W.run(ticks([[0,1.10110],[60,1.10110],[400,1.1045],[700,1.1045]]));
 const f=fails(W),rec=W.w.logs.filter(l=>/Single SL modify recovered/.test(l));
 assert.equal(rec.length,1,'one recovery line');assert.match(rec[0],new RegExp('ticket='+p.ticket+' after 3 consecutive failures, sl=1\\.10010'));
 const later=f.filter(l=>Number(field(l,'retcode'))===10006).slice(3);
 assert.ok(later.length>=5,'it fails again later');
 assert.equal(field(later[0],'consecutive'),'1','the count starts again from one');
 assert.ok(!/backoff=/.test(later[3]),'and backs off only from the 5th again');assert.equal(field(later[4],'backoff'),'1s');
 ok();
}

// 9. Two tickets back off independently: a buy and a sell single (no spread, trailing from the entry, so both want
//    their SL 0.5 ATR from the price at once), each refused from its own start.
{
 const W=world({inputs:{Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5},rsi:50,spread:0});W.run(OPEN);
 assert.equal(W.ctx.GoatSingleOpen(W.ctx.Seq_Buy,W.w.ask),true,'a buy single');
 reject(W);
 const path=ticks([[0,1.1000],[900,1.1000]]);let sellAt=null;
 for(const [t,b] of path){if(t===T0+37){assert.equal(W.ctx.GoatSingleOpen(W.ctx.Seq_Sell,W.w.bid),true,'a sell single 37 s later');sellAt=t;}W.tick(t,b);}
 const [buy,sell]=[W.ctx.Seq_Buy.TradeLevels[0].ticket,W.ctx.Seq_Sell.TradeLevels[0].ticket];
 const at=tk=>mods(W).filter(x=>x.ticket===tk).map(x=>x.time);
 const b0=at(buy)[0],s0=at(sell)[0];assert.ok(s0>=sellAt);
 assert.deepEqual(at(buy).map(t=>t-b0),schedule(0,T0+899-b0),'the buy ticket\'s own schedule');
 assert.deepEqual(at(sell).map(t=>t-s0),schedule(0,T0+899-s0),'the sell ticket\'s own schedule, unaffected by the buy\'s waits');
 const lines=tk=>fails(W).filter(l=>field(l,'ticket')===String(tk));
 assert.equal(lines(buy).length,at(buy).length);assert.equal(lines(sell).length,at(sell).length);
 assert.equal(field(lines(sell)[0],'consecutive'),'1','the sell starts its own count');
 // A success on one leaves the other's back-off in place.
 const Y=world({inputs:{Single_Trail_Start_ATR:0,Single_Trail_ATR:0.5},rsi:50,spread:0});Y.run(OPEN);
 Y.ctx.GoatSingleOpen(Y.ctx.Seq_Buy,Y.w.ask);Y.ctx.GoatSingleOpen(Y.ctx.Seq_Sell,Y.w.bid);
 const yb=Y.ctx.Seq_Buy.TradeLevels[0].ticket;reject(Y,t=>t===yb);
 Y.run(ticks([[0,1.1000],[300,1.1000]]));
 assert.equal(mods(Y).filter(x=>x.ticket!==yb).length,1,'the sell moves at once and once');
 assert.deepEqual(mods(Y).filter(x=>x.ticket===yb).map(x=>x.time-T0),schedule(0,299),'the buy backs off alone');
 ok();
}

// 9b. Nine failing tickets one after the other (review P3-8): a ticket whose position is gone frees its slot, so the
//     9th and later ones still get their own count and back-off (8 slots), never "untracked".
{
 const rsi=t=>((t-T0)%H1)<40*60?25:50;   // an episode every hour; the single's 30-bar time stop ends it
 const W=world({inputs:{Single_BE_ATR:1,Single_Time_Stop_Bars:30,Single_Time_Stop_TF:'TF_Cur'},rsi});W.run(OPEN);reject(W);
 const path=[];for(let h=0;h<11;h++)path.push(...ticks([[h*H1,1.1000],[h*H1+120,1.10110],[h*H1+2400,1.10110],[h*H1+3600,1.1000]]));
 W.run(path);
 const tickets=[...new Set(fails(W).map(l=>field(l,'ticket')))];
 assert.ok(tickets.length>=10,'ten tickets fail in turn ('+tickets.length+')');
 for(const tk of tickets){
  const l=fails(W).filter(x=>field(x,'ticket')===tk);
  assert.ok(l.length>=6,'ticket '+tk+' fails long enough to back off');
  assert.equal(field(l[0],'consecutive'),'1','ticket '+tk+' starts its own count');
  assert.equal(field(l[4],'backoff'),'1s','ticket '+tk+' backs off from its 5th failure');
  assert.ok(!l.some(x=>/untracked/.test(x)),'ticket '+tk+' is tracked');
 }
 ok();
}

// 9c. The run's trailing counters count a single's moves (TSL_Modified, TSLs at the end of a run): attempts and errors.
{
 const W=world({inputs:{Single_BE_ATR:1,...TRAIL}});opened(W);
 const [m0,e0]=[W.ctx.TSLmodifieds,W.ctx.TSLmodifyErrors];
 let n=0;W.w.rejectModify=()=>(++n<=2);
 W.run(ticks([[0,1.10110],[30,1.10110],[300,1.1045],[400,1.1045]]));
 assert.equal(W.ctx.TSLmodifieds-m0,mods(W).length,'every attempt is counted');
 assert.equal(W.ctx.TSLmodifyErrors-e0,2,'every failure is counted');
 assert.ok(mods(W).length>=5);
 ok();
}

// 10. A live restart: the break-even SL is the broker's, adoption keeps it, and the trailing carries on from it.
//     Without its frozen sizes the adopted single is left alone.
function restart({dropSizes=false}={}){
 const inputs={Single_BE_ATR:1,...TRAIL};
 const first=world({inputs,tester:false,fastSpeed:false});const p=opened(first);
 first.run(ticks([[0,1.10110],[30,1.10110]]));assert.equal(first.w.positions[0].sl,p.open,'break-even before the restart');
 const gv=[...first.w.gv].filter(([k])=>!(dropSizes&&/_B_SL$/.test(k)));
 const state={positions:JSON.parse(JSON.stringify(first.w.positions)),deals:JSON.parse(JSON.stringify(first.w.deals)),gv,
  next:[first.w.nextTicket,first.w.nextDeal],balance:first.w.balance,time:first.w.time,bid:first.w.bid};
 const W=world({inputs,tester:false,fastSpeed:false,start:state.time,bid:state.bid,
  adopt:(ctx,w)=>{w.positions.push(...JSON.parse(JSON.stringify(state.positions)));w.deals.push(...JSON.parse(JSON.stringify(state.deals)));
   for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;w.balance=state.balance;}});
 return {W,p};
}
{
 const {W,p}=restart();
 assert.ok(W.w.alerts.some(a=>/adopted 1 open position.*Lock\/TP\/SL and trailing resume/.test(a)),'adopted with its sizes');
 assert.equal(W.ctx.Seq_Buy.Adopted&&W.ctx.Seq_Buy.AdoptSizes,true);
 assert.ok(mods(W).every(x=>x.sl>=p.open),'adoption never loosens the stop');assert.equal(W.w.positions[0].sl,p.open,'the break-even SL stays');
 const path=ticks([[31,1.10110],[300,1.1045],[400,1.1045]]);W.run(path);
 const m=mods(W);assert.ok(m.length>=5,'the trailing carries on after the restart');
 let prev=p.open;for(const x of m){assert.ok(x.sl>prev,'only up from the break-even');prev=x.sl;}
 const last=W.w.positions[0].sl;
 assert.ok(last<=1.1040+1e-9&&last>1.1040-0.00012,'0.5 ATR (the frozen entry ATR) behind the price, within the minimum step: '+last);
 const {W:N}=restart({dropSizes:true});
 assert.equal(N.ctx.Seq_Buy.AdoptSizes,false,'no frozen stop size');
 N.ctx.Seq_Buy.Size_SL=0.0015;   // even with a stop size in memory: an untrusted adoption is left alone by the guard itself
 N.run(ticks([[31,1.10110],[300,1.1045],[400,1.1045]]));
 assert.equal(mods(N).length,0,'an adopted single without its sizes keeps its broker SL/TP');
 ok();
}

// 11. UpdateLockTPSL runs once per single (at its open): nothing later re-derives the stop from Size_SL.
{
 const W=world({inputs:{Single_BE_ATR:1,...TRAIL}});const b=W.ctx.Seq_Buy;let calls=0;
 const orig=b.UpdateLockTPSL.bind(b);b.UpdateLockTPSL=(...a)=>{calls++;return orig(...a);};
 W.run([...OPEN,...ticks([[0,1.1000],[300,1.1045],[600,1.1035],[700,1.1035]])]);
 assert.ok(mods(W).length>=10);assert.equal(calls,1,'UpdateLockTPSL: once, at the open');
 // With both on, once the SL is above the entry the break-even is done: every later move is a trailing one, by at
 // least the minimum step.
 const above=mods(W).filter(x=>x.sl>1.10010);assert.ok(above.length>=5);
 for(let k=1;k<above.length;k++) assert.ok(above[k].sl-above[k-1].sl>=0.0001*1.1-1e-9,'a trailing step of at least the minimum: '+above[k-1].sl+' -> '+above[k].sl);
 ok();
}

// 12. The trailed stop ends the single at the broker; the next episode opens a new one, which trails on its own.
{
 const rsi=t=>(t<T0+1200||t>=T0+1800)?25:50;
 const W=world({inputs:TRAIL,rsi});opened(W);
 W.run(ticks([[0,1.1000],[300,1.1045],[600,1.1030],[1200,1.1030],[1800,1.1030],[2100,1.1075],[2200,1.1075]]));
 const s=W.w.trace.filter(x=>x.op==='OrderSend');assert.equal(s.length,2,'two singles');
 assert.ok(W.w.trace.some(x=>x.op==='BrokerStop'&&x.time<s[1].time),'the first ended at its trailed stop');
 assert.ok(mods(W).filter(x=>x.time>s[1].time).length>=5,'the second trails');
 ok();
}

// 13. OnInit refuses a negative distance.
{
 for(const k of ['Single_BE_ATR','Single_Trail_Start_ATR','Single_Trail_ATR']){
  let e=null;try{world({inputs:{[k]:-0.5}});}catch(x){e=x;}
  assert.ok(e&&e.initCode===2,k+' < 0 is refused (INIT_PARAMETERS_INCORRECT)');
 }
 const main=H.readSource(undefined,H.MAIN);
 assert.match(main,/if\(Single_BE_ATR<0\.0 \|\| Single_Trail_Start_ATR<0\.0 \|\| Single_Trail_ATR<0\.0\) \{Alert\("Initialization Failed: Single_BE_ATR, Single_Trail_Start_ATR and Single_Trail_ATR cannot be negative\."\); return INIT_PARAMETERS_INCORRECT;\}/);
 // TrailingStoploss stays B50-alpha's, byte for byte.
 const body=(text,sig)=>{const a=text.indexOf(sig);let d=0,i=text.indexOf('{',a);for(;i<text.length;i++){if(text[i]==='{')d++;if(text[i]==='}'){d--;if(!d)break;}}return text.slice(a,i+1);};
 assert.equal(body(main,'   void TrailingStoploss()'),body(H.readSource(B50_ALPHA,H.MAIN),'   void TrailingStoploss()'),'TrailingStoploss is untouched');
 ok();
}

console.log(JSON.stringify({passed,test:'b51_modify'}));
