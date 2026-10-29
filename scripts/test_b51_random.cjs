// B51 random-direction benchmark (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8.1): Engine_Single with
// Random_Direction on the real OnTick path. scripts/b50_tick_harness.cjs converts this tree's GoatTickBody,
// SignalEntryTrigger, GoatSingleRandomEntry, GoatSingleSignalExits and GoatSingleOpen; scripts/b51_random_reference.cjs
// evaluates this tree's GoatSingleRandomSide with MQL's ulong rules (the harness does not model them) and is installed
// in its place. The price is flat in every fixture, so a single opens and closes at the same times whatever its side,
// and the benchmark is compared with B50-alpha (32df4eb) and with this tree's own flags-off run on the same ticks.
// Fixtures (RSI_OverBS; ATR 0.0010 on the closed bar; singles closed by a 30-bar time stop):
// - hourly: one buy-signal (or sell-signal) episode per hour, RSI 25 (80) for 40 minutes, 02:00-22:00 Mon and Tue: 40;
// - overlap (the reviewer's exp3): a buy-signal episode every 20 minutes lasting 10, so an episode starts while the
//   last single still runs;
// - opposite (exp1, and one where the opposite signal really comes): Single_Exit_Opposite on;
// - pairs: a buy-signal episode (minutes 0-5) then a sell-signal one (5-10) every 40 minutes, Allow_Opposite_Seq on
//   (alpha hedges) and off (alpha refuses the second);
// - an M5 chart (the signal bar is the chart's).
// Proves:
// - the side is splitmix64((ulong)seed ^ (ulong)episode-start signal bar ^ ((ulong)signal << 62)) & 1: SplitMix64's
//   published outputs, golden sequences for fixed seeds and both signals, the tree's function equal to the reference;
// - the draw is made once per episode, at alpha's moment, from the episode's first signal bar (PERIOD_CURRENT, shift
//   1): the same under two tick models and on a replay; never the tick's time, the forming bar or another timeframe;
// - the entry moments are alpha's (a subset when a drawn side is gated: the episode is consumed, counted and logged,
//   with no redraw and no waiting), so the trade count is at most alpha's; the side sequence is the draws', never
//   forced by an open single; the opposite-signal exit reads the opening episode's signal, so exits are alpha's;
// - MathRand and MathSrand are never called;
// - flags off (any seed) the tree trades exactly as B50-alpha;
// - OnInit refuses Random_Direction with Engine_Grid, outside the tester, with Mode_Trade other than Long_and_Short,
//   and a negative seed.
// scripts/test_b51_random_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail it.
// What it does not prove: compile cleanliness or MT5's own ulong arithmetic. The MetaEditor compile and a native run
// (the deal table's sides against this file's reference) do.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const R=require('./b51_random_reference.cjs');
const B50_ALPHA='32df4eb';
let passed=0;const ok=()=>passed++;

const MON=Date.UTC(2026,9,5)/1000,H1=3600,M1=60,DAY=86400;
// Ticks every `step` s (offset s past each step) over [from,to) seconds after MON, at a flat price.
const flat=(from,to,step=20,offset=7,bid=1.1000)=>{const t=[];for(let s=from;s<to;s+=step)t.push([MON+s+offset,bid]);return t;};
const HOURS=[];for(const d of [0,1])for(let h=2;h<22;h++)HOURS.push(MON+d*DAY+h*H1);   // the 40 hourly episode starts
const session=(step=20,offset=7)=>[0,1].flatMap(d=>flat(d*DAY+2*H1-10*M1,d*DAY+22*H1,step,offset));   // from 01:50 (no signal)
const atr=shift=>shift===1?0.0010:0.0030;
const byRsi=f=>(name,buffer,shift,w)=>name==='ATR_MA'?atr(shift):(name==='RSI'?f(w.time-MON):undefined);
const hourly=(value=25)=>byRsi(t=>(t%H1)<40*M1?value:50);
const overlap=byRsi(t=>(t%(20*M1))<10*M1?25:50);                                     // exp3
const pairs=byRsi(t=>{const m=(t%(40*M1))/M1;return m<5?25:(m<10?80:50);});          // a buy, then a sell episode
const opposite=byRsi(t=>{const m=(t%H1)/M1;return m<10?25:(m<15?80:50);});           // a buy episode, then the opposite signal
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500,Single_Time_Stop_Bars:30,Single_Time_Stop_TF:'TF_Cur'};
const RANDOM={Random_Direction:true,Random_Seed:1};
const SESSION_GOLDEN='0010000111111111101000000101101001011001';        // seed 1, the 40 hourly buy-signal episodes
const SESSION_GOLDEN_SELL='1110101010110111100011110011111100010001';   // seed 1, the same bars, sell-signal episodes
// A world on this tree (or `source`), with the MQL side function installed and MathRand/MathSrand counted.
function world({inputs={},indicator=hourly(),source,tester=true,fastSpeed=true,world:wx}={}){
 const W=H.build(source,{inputs:{...BASE,...inputs},tester,fastSpeed,indicator,world:wx});
 if(source===undefined){
  R.install(W);
  W.rand={rand:0,srand:0};let x=12345;
  W.ctx.MathRand=()=>{W.rand.rand++;x=(x*1103515245+12345)%32768;return x;};W.ctx.MathSrand=()=>{W.rand.srand++;};
 }
 return W;
}
// B50-alpha on the same fixture (its inputs: this file's minus the B51 ones).
const alpha=(inputs,indicator,wx)=>H.build(B50_ALPHA,{inputs:{...BASE,...Object.fromEntries(Object.entries(inputs).filter(([k])=>!/^Random_/.test(k)))},tester:true,fastSpeed:true,indicator,world:wx});
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const closes=W=>W.w.trace.filter(x=>x.op==='PositionClose');
const sideString=W=>sends(W).map(s=>s.type).join('');
const gatedLogs=W=>W.w.logs.filter(l=>/B51 random: drawn side gated/.test(l));
const barOf=(t,p=M1)=>Math.floor(t/p)*p-p;   // the chart's closed bar at shift 1
// The episodes of a fixture: [start time, signal] for each first signal check where the signal reads true, from the
// indicator itself (the reference the tree is checked against).
function episodes(path,indicator){
 const out=[];let last=[false,false],lastMin=-1;
 for(const [t] of path){
  const m=Math.floor(t/M1);if(m===lastMin)continue;lastMin=m;   // the M1 signal cadence: the first tick of each minute
  const v=indicator('RSI',0,1,{time:t});const now=[v<=30,v>=70];
  for(const s of [0,1]){if(now[s]&&!last[s])out.push([t,s]);}last=now;
 }
 return out;
}
// Runs a fixture with the benchmark, flags off, and on B50-alpha; checks the benchmark against both.
function compare(label,{inputs={},indicator,path,wx}){
 const B=world({inputs:{...RANDOM,...inputs},indicator,world:wx}),O=world({inputs,indicator,world:wx}),A=alpha(inputs,indicator,wx);
 B.run(path);O.run(path);A.run(path);
 assert.deepEqual(O.w.trace,A.w.trace,label+': flags off is B50-alpha');
 const at=new Set(sends(A).map(x=>x.time));
 assert.ok(sends(A).length>=5,label+': the fixture trades ('+sends(A).length+')');
 assert.ok(sends(B).every(x=>at.has(x.time)),label+': every benchmark entry is at one of alpha\'s entry moments');
 assert.equal(sends(B).length+gatedLogs(B).length,sends(A).length,label+': alpha\'s moments are the benchmark\'s entries plus its gated episodes');
 assert.equal(B.ctx.g_GoatRandomGated,gatedLogs(B).length,label+': each gated episode is counted');
 assert.deepEqual(B.rand,{rand:0,srand:0},label+': no MathRand/MathSrand call');
 return {B,O,A};
}

// 1. The reference and the tree's function: SplitMix64's published outputs, golden sequences, a seeded sweep.
{
 assert.equal(R.splitmix64(0n),0xE220A8397B1DCDAFn,'SplitMix64, state 0 (splitmix64.c first output)');
 assert.equal(R.splitmix64(0x9E3779B97F4A7C15n),0x6E789E6AA1B965F4n,'SplitMix64, the second output (state = gamma)');
 const mql=R.mqlRandomSide();
 assert.equal(mql(0,0,0).z,0xE220A8397B1DCDAFn,'the tree\'s GoatSingleRandomSide is SplitMix64 (state 0)');
 assert.equal(R.state(5,7,1),(5n^7n)|(1n<<62n),'the state: seed ^ bar ^ signal << 62');
 const seq=(f,seed,start,step,n,signal)=>Array.from({length:n},(_,k)=>f(seed,start+k*step,signal)).join('');
 const GOLDEN={
  's1 M1 buy':[1,MON,M1,64,0,'0000000101010110000001000000000010111000110110011101011001000100'],
  's2 M1 buy':[2,MON,M1,64,0,'0010110001101000110000100110101100001011101000000010011011000101'],
  's1 M1 sell':[1,MON,M1,64,1,'1011001011010111111010100101001001000001000010111001011000010110'],
 };
 for(const [name,[seed,start,step,n,signal,bits]] of Object.entries(GOLDEN)){
  assert.equal(seq(R.referenceSide,seed,start,step,n,signal),bits,'the JavaScript reference reproduces the golden '+name);
  assert.equal(seq((s,b,g)=>mql(s,b,g).side,seed,start,step,n,signal),bits,'the tree\'s GoatSingleRandomSide reproduces the golden '+name);
 }
 assert.equal(HOURS.map(h=>mql(1,h-M1,0).side).join(''),SESSION_GOLDEN);assert.equal(HOURS.map(h=>mql(1,h-M1,1).side).join(''),SESSION_GOLDEN_SELL);
 let s=20261029;const rnd=()=>(s=(s*48271)%2147483647);
 let ones=0,differ=0;
 for(let k=0;k<4000;k++){
  const seed=k<4?[0,1,2147483646,2147483647][k]:rnd(),bar=k%2?MON+60*(rnd()%500000):rnd()*2,signal=k%3===0?1:0;
  const got=mql(seed,bar,signal);
  assert.equal(got.side,R.referenceSide(seed,bar,signal),'side for seed '+seed+', bar '+bar+', signal '+signal);
  assert.equal(got.z,R.splitmix64(R.state(seed,bar,signal)),'the whole 64-bit state');
  ones+=got.side;differ+=mql(seed,bar,0).side!==mql(seed,bar,1).side?1:0;
 }
 assert.ok(ones>1800&&ones<2200,'about half sells ('+ones+' of 4000)');
 assert.ok(differ>1800&&differ<2200,'the two signals of one bar draw independently ('+differ+' of 4000 differ)');
 ok();
}

// 2. The hourly fixture: one single per episode at alpha's moment, its side the episode's draw; the same lots, stops
//    and exits as alpha (both sides occur).
const DAY2=session();
const RUN=compare('hourly',{indicator:hourly(),path:DAY2}).B;
{
 const s=sends(RUN);
 assert.equal(s.length,40,'one single per hourly episode: '+s.length);
 for(const [k,x] of s.entries()) assert.equal(x.time,HOURS[k]+7,'opens on the episode\'s first signal check (episode '+k+')');
 assert.equal(sideString(RUN),SESSION_GOLDEN,'the golden sequence, through the real tick path');
 const OFF=world({});OFF.run(DAY2);const o=sends(OFF);
 assert.ok(o.every(x=>x.type===0),'flags off, a buy signal buys');
 assert.deepEqual(s.map(x=>x.volume),o.map(x=>x.volume),'the same lots');
 assert.deepEqual(s.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),o.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),'the same stop distance');
 assert.deepEqual(closes(RUN).map(x=>x.time),closes(OFF).map(x=>x.time),'the same exits (the time stop)');
 assert.equal(gatedLogs(RUN).length,0);
 ok();
}

// 3. The episode-start signal bar, not the tick: a second tick model and a replay draw every episode the same way.
{
 const FINE=world({inputs:RANDOM});FINE.run(session(3,1));
 const a=sends(RUN),b=sends(FINE);
 assert.equal(b.length,a.length);
 assert.notDeepEqual(b.map(x=>x.time),a.map(x=>x.time),'the two tick models open at different seconds');
 assert.deepEqual(b.map(x=>barOf(x.time)),a.map(x=>barOf(x.time)),'... on the same bars');
 assert.equal(sideString(FINE),sideString(RUN),'and draw every episode the same way');
 const REPLAY=world({inputs:RANDOM});REPLAY.run(DAY2);
 assert.deepEqual(REPLAY.w.trace,RUN.w.trace,'a replay trades exactly the same');
 const S2=world({inputs:{...RANDOM,Random_Seed:2}});S2.run(DAY2);
 assert.notEqual(sideString(S2),sideString(RUN),'seed 2 differs from seed 1');
 assert.equal(sideString(S2),HOURS.map(h=>R.referenceSide(2,h-M1,0)).join(''),'seed 2 is the reference\'s');
 ok();
}

// 4. MathRand and MathSrand are never called; the benchmark's code names neither, nor any clock.
{
 const main=H.readSource(undefined,H.MAIN);
 const block=main.slice(main.indexOf('// B51:begin b51-random'),main.indexOf('// B51:end b51-random'));
 assert.ok(block.length>1000,'the B51 random block');
 const code=block.split('\n').filter(l=>!/^\s*\/\//.test(l)).join('\n').replace(/\/\/[^\n]*/g,'');
 for(const banned of ['MathRand','MathSrand','TimeCurrent','TimeLocal','TimeGMT','TimeTradeServer','GetTickCount','GetMicrosecondCount','iTime'])
  assert.ok(!code.includes(banned),'the benchmark reads no '+banned+' (the episode bar is recorded in SignalEntryTrigger)');
 ok();
}

// 5. Sell-signal episodes draw with their own signal bit; the episode is the signal's; Reverse_Seq keeps the coin and
//    alpha's (reversed) moments.
{
 const S=compare('hourly sell',{indicator:hourly(80),path:DAY2}).B;
 assert.equal(sends(S).length,40);assert.equal(sideString(S),SESSION_GOLDEN_SELL,'the sell signal\'s golden (signal bit 1)');
 const W=world({inputs:{...RANDOM,Random_Seed:7},indicator:hourly(80)});W.run(flat(2*H1-10*M1,8*H1));
 assert.equal(sideString(W),'001101','seed 7, the sell signal');
 const mid=world({inputs:RANDOM,indicator:hourly(80)});mid.run(flat(2*H1-10*M1,2*H1+35*M1));
 assert.deepEqual([...mid.ctx.g_GoatSingleArmed],[true,false],'the sell signal consumes its own flag');
 assert.equal(mid.ctx.g_GoatRandomSignal[sends(mid)[0].type],1,'the single remembers its episode\'s signal');
 const REV=compare('hourly Reverse_Seq',{inputs:{Reverse_Seq:true},indicator:hourly(),path:DAY2}).B;
 assert.equal(sideString(REV),SESSION_GOLDEN,'Reverse_Seq: the same coin');
 ok();
}

// 6. Overlapping episodes (exp3): an episode starts while the last single runs. Alpha opens only once its single has
//    ended; so does the benchmark, whatever side that single took: no hedge, no late entry, the draws' sides.
{
 const {B,A}=compare('overlap',{indicator:overlap,path:DAY2});
 assert.deepEqual(sends(B).map(x=>x.time),sends(A).map(x=>x.time),'the benchmark opens exactly at alpha\'s moments');
 const eps=episodes(DAY2,overlap).filter(([,s])=>s===0);
 const draws=sends(B).map(x=>{const e=eps.filter(([t])=>t<=x.time).at(-1);return R.referenceSide(1,barOf(e[0]),0);});
 assert.equal(sideString(B),draws.join(''),'each side is its episode\'s draw');
 assert.notEqual(sideString(B),'01'.repeat(sends(B).length/2),'not forced to alternate');
 let open=0;for(const x of B.w.trace){if(x.op==='OrderSend'){assert.equal(open,0,'never two singles at once (no hedge) at '+(x.time-MON));open++;}if(x.op==='PositionClose')open--;}
 assert.ok(sends(B).every(x=>(x.time-MON)%(20*M1)<M1),'every entry on its episode\'s first minute');
 // Late moments: episodes of 15 minutes every 20, so alpha's single of minute 0 ends (minute 30) inside the episode of
 // minute 20, and alpha opens then: the draw is still the episode's first signal bar (minute 19), not minute 29's.
 const late=byRsi(t=>(t%(20*M1))<15*M1?25:50);
 const L=compare('late moments',{indicator:late,path:DAY2});
 assert.deepEqual(sends(L.B).map(x=>x.time),sends(L.A).map(x=>x.time),'alpha\'s moments');
 assert.ok(sends(L.B).filter(x=>(x.time-MON)%(20*M1)>=M1).length>=20,'most of them late in their episode');
 const leps=episodes(DAY2,late).filter(([,s])=>s===0);
 const ldraws=sends(L.B).map(x=>{const e=leps.filter(([t])=>t<=x.time).at(-1);return R.referenceSide(1,barOf(e[0]),0);});
 assert.equal(sideString(L.B),ldraws.join(''),'each drawn from its episode\'s first signal bar');
 assert.notEqual(sideString(L.B),sends(L.B).map(x=>R.referenceSide(1,barOf(x.time),0)).join(''),'not from the bar of the late moment');
 ok();
}

// 7. The opposite-signal exit reads the opening episode's signal: exits are alpha's (exp1, where no opposite signal
//    comes, and a fixture where it does, 10 minutes into each episode).
{
 const {B,A}=compare('opposite, none comes',{inputs:{Single_Exit_Opposite:true},indicator:hourly(),path:DAY2});
 assert.ok(sends(B).some(x=>x.type===1),'against-signal sides occur');
 assert.deepEqual(closes(B).map(x=>x.time),closes(A).map(x=>x.time),'every single lives as long as alpha\'s (the time stop)');
 const c=compare('opposite, it comes',{inputs:{Single_Exit_Opposite:true},indicator:opposite,path:DAY2});
 assert.ok(c.A.w.logs.filter(l=>/Single Exit: opposite signal/.test(l)).length>=20,'alpha exits on the opposite signal');
 const buys=sends(c.A).filter(x=>(x.time-MON)%H1<M1).map(x=>x.time),bClose=closes(c.B).map(x=>x.time),aClose=closes(c.A).map(x=>x.time);
 const exitOf=(W,t)=>W.w.trace.find(x=>x.op==='PositionClose'&&x.time>t).time;
 for(const t of sends(c.B).filter(x=>(x.time-MON)%H1<M1).map(x=>x.time)) assert.equal(exitOf(c.B,t),exitOf(c.A,t),'the buy-signal single exits when alpha\'s does ('+(t-MON)/H1+')');
 assert.ok(buys.length>=20&&bClose.length>=20&&aClose.length>=20);
 ok();
}

// 8. A buy then a sell episode (pairs). Allow_Opposite_Seq on: alpha hedges; the benchmark's second episode draws on
//    its own, and when it draws the side the first holds, it is consumed (counted, logged), never redrawn or delayed.
//    Off: alpha refuses the second episode, and so does the benchmark.
{
 const {B,A}=compare('pairs, Allow_Opposite_Seq on',{indicator:pairs,path:DAY2});
 assert.equal(sends(A).length,120,'alpha: two singles per cycle (60 cycles)');
 const g=gatedLogs(B);assert.ok(g.length>=5&&sends(B).length>=65,'both: hedges ('+(sends(B).length-60)+') and gated episodes ('+g.length+')');
 for(const l of g){assert.match(l,/signal SELL, drawn (BUY|SELL)/);}
 const eps=episodes(DAY2,pairs);
 for(const [t,sig] of eps.filter(([,s])=>s===1)){
  const first=sends(B).find(x=>x.time<t&&x.time>t-6*M1),second=sends(B).find(x=>x.time>=t&&x.time<t+M1);
  const draw=R.referenceSide(1,barOf(t),1);
  if(draw===first.type) assert.ok(!second,'a draw of the held side opens nothing at '+(t-MON));
  else assert.ok(second&&second.type===draw,'a draw of the free side opens it at once at '+(t-MON));
 }
 assert.ok(!sends(B).some(x=>(x.time-MON)%(40*M1)>=6*M1),'never later in an episode (no waiting)');
 const off=compare('pairs, Allow_Opposite_Seq off',{inputs:{Allow_Opposite_Seq:false},indicator:pairs,path:DAY2});
 assert.equal(sends(off.A).length,60,'alpha: the second episode is refused');
 assert.deepEqual(sends(off.B).map(x=>x.time),sends(off.A).map(x=>x.time),'the benchmark too');
 assert.equal(gatedLogs(off.B).length,0,'refused by alpha\'s gate: not an episode of the benchmark');
 ok();
}

// 9. The drawn side's own gates: DashboardEntryAllowed and a virtual sequence on the drawn side consume the episode;
//    alpha's gate for its trade side is asked first.
{
 const D=world({inputs:RANDOM});const asked=[];
 D.ctx.DashboardEntryAllowed=dir=>{asked.push(dir);return dir===0;};D.run(DAY2);
 assert.equal(sideString(D),'0'.repeat(SESSION_GOLDEN.split('0').length-1),'only the buy draws open');
 assert.deepEqual(sends(D).map(x=>x.time),HOURS.filter((h,k)=>SESSION_GOLDEN[k]==='0').map(h=>h+7),'at their episodes\' first minute');
 assert.equal(gatedLogs(D).length,SESSION_GOLDEN.split('1').length-1,'each sell draw is one gated episode');
 assert.match(gatedLogs(D)[0],/^GOAT_Trading Buy: B51 random: drawn side gated \(signal BUY, drawn SELL, bar 2026\.10\.05 \d\d:59, episodes gated 1\)$/);
 assert.ok(asked.includes(1)&&asked.filter(d=>d===0).length>=40,'both asked');
 // Under Reverse_Seq alpha's trade side for a buy signal is the sell: a sell-only dashboard lets alpha's moment through,
 // and the buy draws are gated.
 const RV=world({inputs:{...RANDOM,Reverse_Seq:true}});RV.ctx.DashboardEntryAllowed=dir=>dir===1;RV.run(DAY2);
 assert.equal(sideString(RV),'1'.repeat(SESSION_GOLDEN.split('1').length-1),'Reverse_Seq, sells only: the sell draws open');
 assert.equal(gatedLogs(RV).length,SESSION_GOLDEN.split('0').length-1,'the buy draws are gated');
 // Alpha's own gate (its trade side) refuses first: no draw, the episode stays armed.
 const N=world({inputs:RANDOM});N.ctx.DashboardEntryAllowed=()=>false;N.run(flat(2*H1-10*M1,3*H1));
 assert.equal(sends(N).length,0);assert.equal(gatedLogs(N).length,0,'refused by alpha\'s gate: no draw');assert.equal(N.ctx.g_GoatSingleArmed[0],true);
 // A virtual sequence on the drawn side (never in single mode; forced while the entry runs) gates it.
 for(const [side,seq] of [[1,'Seq_Sell_Virtual'],[0,'Seq_Buy_Virtual']]){
  const V=world({inputs:RANDOM});const v=V.ctx[seq];let inside=false;const entry=V.ctx.GoatSingleRandomEntry;
  const real=Object.getOwnPropertyDescriptor(v,'Active');let stored=v.Active;
  Object.defineProperty(v,'Active',{get:()=>inside||stored,set:z=>{stored=z;},configurable:true});
  const alphaSide=0;   // a buy signal: alpha's trade side is the buy
  V.ctx.GoatSingleRandomEntry=sig=>{inside=side!==alphaSide;try{return entry(sig);}finally{inside=false;}};
  V.run(DAY2);
  if(side===1){
   assert.equal(sideString(V),'0'.repeat(SESSION_GOLDEN.split('0').length-1),'a virtual sell gates the sell draws');
   assert.equal(gatedLogs(V).length,SESSION_GOLDEN.split('1').length-1);
  }
  else assert.equal(sends(V).length,40,'(control)');
  Object.defineProperty(v,'Active',real||{value:stored,writable:true});
 }
 // A virtual buy sequence is alpha's own gate for a buy signal: no draw at all.
 const VB=world({inputs:RANDOM});const vb=VB.ctx.Seq_Buy_Virtual;let inB=false;const eB=VB.ctx.GoatSingleRandomEntry;let sb=vb.Active;
 Object.defineProperty(vb,'Active',{get:()=>inB||sb,set:z=>{sb=z;},configurable:true});
 VB.ctx.GoatSingleRandomEntry=sig=>{inB=true;try{return eB(sig);}finally{inB=false;}};VB.run(flat(2*H1-10*M1,3*H1));
 assert.equal(sends(VB).length,0);assert.equal(gatedLogs(VB).length,0,'alpha\'s virtual gate: no draw');
 ok();
}

// 10. An M5 chart: the episode bar is the chart's closed bar (PERIOD_CURRENT), not M1's.
{
 const wx={period:5},inputs={Single_Time_Stop_TF:'TF_M1'};
 const {B}=compare('M5 chart',{inputs,indicator:hourly(),path:DAY2,wx});
 const m5=HOURS.map(h=>R.referenceSide(1,barOf(h,300),0)).join(''),m1=HOURS.map(h=>R.referenceSide(1,barOf(h,60),0)).join('');
 assert.notEqual(m5,m1,'the fixture tells the two apart');
 assert.equal(sideString(B),m5,'the sides are the M5 bar\'s draws');
 ok();
}

// 11. Flags off: Random_Direction false (with any seed) trades exactly as B50-alpha, single and grid alike.
{
 for(const [label,inputs,indicator,path] of [
  ['single',{},hourly(),flat(2*H1-10*M1,12*H1)],
  ['single, seed 7, sell signal',{Random_Seed:7},hourly(80),flat(2*H1-10*M1,12*H1)],
  ['single, Reverse_Seq, Mode_Trade=Short',{Reverse_Seq:true,Mode_Trade:'Short'},hourly(),flat(2*H1-10*M1,12*H1)],
  ['single, opposite exit',{Single_Exit_Opposite:true,Random_Seed:3},opposite,flat(2*H1-10*M1,12*H1)],
  ['grid',{Engine_Mode:'Engine_Grid',Random_Seed:9,Delay_Trade:0,Delay_Trade_Live:0,Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4},hourly(),
   [...flat(2*H1,3*H1),...flat(3*H1,6*H1,20,7,1.0960),...flat(6*H1,9*H1,20,7,1.1040)]]]){
  const tree=world({inputs,indicator}),a=alpha(inputs,indicator);
  tree.run(path);a.run(path);
  assert.ok(sends(a).length>=2,label+': the fixture trades');
  assert.deepEqual(tree.w.trace,a.w.trace,label+': Random_Direction off trades exactly as B50-alpha');
  assert.deepEqual(tree.w.positions,a.w.positions,label+': the same positions');
 }
 ok();
}

// 12. OnInit: Random_Direction needs the single engine, the tester and both directions; the seed is not negative.
{
 const refused=(inputs,tester=true)=>{try{world({inputs,tester});return null;}catch(e){assert.ok(e.initCode!==undefined,'an OnInit refusal, not a crash: '+e.message);return e;}};
 const g=refused({...RANDOM,Engine_Mode:'Engine_Grid'});assert.ok(g&&g.initCode===2,'Random_Direction with Engine_Grid: INIT_PARAMETERS_INCORRECT');
 const live=refused(RANDOM,false);assert.ok(live&&live.initCode===1,'Random_Direction on a live chart: INIT_FAILED');
 for(const m of ['Long','Short']){const e=refused({...RANDOM,Mode_Trade:m});assert.ok(e&&e.initCode===2,'Random_Direction with Mode_Trade='+m+' is refused');}
 assert.equal(refused({Mode_Trade:'Long'}),null,'Mode_Trade=Long without the benchmark passes');
 const neg=refused({Random_Seed:-1});assert.ok(neg&&neg.initCode===2,'a negative seed');
 assert.equal(refused({Engine_Mode:'Engine_Grid',Random_Seed:5}),null,'Random_Direction off: any non-negative seed passes');
 assert.equal(refused(RANDOM),null);assert.equal(refused({...RANDOM,Random_Seed:0}),null,'seed 0 passes');
 const main=H.readSource(undefined,H.MAIN);const init=main.slice(main.indexOf('// B51:begin b51-init'),main.indexOf('// B51:end b51-init'));
 for(const re of [/if\(Random_Direction && Engine_Mode!=Engine_Single\) +\{Alert\("Initialization Failed: Random_Direction needs the single-trade engine/,
  /if\(Random_Seed<0\) +\{Alert\("Initialization Failed: Random_Seed cannot be negative\."\); return INIT_PARAMETERS_INCORRECT;\}/,
  /if\(Random_Direction && Mode_Trade!=Long_and_Short\) +\{Alert\("Initialization Failed: Random_Direction needs Mode_Trade=Long_and_Short/,
  /if\(Random_Direction && !MQLInfoInteger\(MQL_TESTER\)\) +\{Alert\("Initialization Failed: Random_Direction is a strategy-tester benchmark/]) assert.match(init,re);
 ok();
}

console.log(JSON.stringify({passed,test:'b51_random'}));
