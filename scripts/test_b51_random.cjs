// B51 random-direction benchmark (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8.1): Engine_Single with
// Single_Flat_Only and Random_Direction on the real OnTick path. scripts/b50_tick_harness.cjs converts this tree's
// GoatTickBody, SignalEntryTrigger, GoatSingleRandomEntry, GoatSingleBothFree, GoatSingleSignalExits and GoatSingleOpen;
// scripts/b51_random_reference.cjs evaluates this tree's GoatSingleRandomSide with MQL's ulong rules (the harness does
// not model them) and is installed in its place.
// The comparison (re-review of GOAT-EA#286): the strategy S (Single_Flat_Only on, Random_Direction off) against the
// benchmark B (both on), under the same eligibility: a single opens only while both sides are free and permitted, and
// that decision is made before the draw, which only picks the side. Each fixture also runs the tree flags off (O) and
// B50-alpha (A): O is A, byte for byte. Fixtures (RSI_OverBS; ATR 0.0010 on the closed bar; flat price unless noted):
// - hourly: one buy-signal (or sell-signal) episode per hour, 02:00-22:00 Mon and Tue: 40; singles end on a 30-bar stop;
// - overlap (the reviewer's exp3) and late moments: an episode starts while the last single still runs;
// - opposite (exp1, and one where the opposite signal really comes): Single_Exit_Opposite on;
// - pairs and exp4: a buy-signal then a sell-signal episode in each cycle (alpha hedges, flat-only does not);
// - exp5: an uptrend with SL 1.5 ATR and TP 2R over 12 seeds (side-dependent exits);
// - an M5 chart (the signal bar is the chart's).
// Proves:
// - the side is splitmix64((ulong)seed ^ (ulong)bar ^ ((ulong)signal << 62) ^ ((ulong)ordinal << 40)) & 1: SplitMix64's
//   published outputs, golden sequences for fixed seeds and both signals, the tree's function equal to the reference;
// - one draw per episode, from the episode's first signal bar (PERIOD_CURRENT, shift 1) and its ordinal among the
//   signal's episodes on that bar: the same under two tick models and on a replay; never the tick's time, the forming
//   bar or another timeframe; several episodes in one H1 bar draw independently (exp7: the sell share stays fair);
// - B's entries are S's (no divergent entry while the exits do not depend on the side; counted under exp5), and its
//   exits are S's; no trade ever opens while another single runs; the sides are the draws', never forced: in the exp5
//   uptrend the sell share stays within 3 standard errors of 50%;
// - flat-only on, random off (S) against flags off (O): S's entries are O's, minus only entries O made while a single
//   was running;
// - MathRand and MathSrand are never called; flags off (any seed) the tree trades exactly as B50-alpha;
// - OnInit refuses Random_Direction with Engine_Grid, outside the tester, with Mode_Trade other than Long_and_Short,
//   without Single_Flat_Only, a negative seed, and Single_Flat_Only with Engine_Grid.
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
// Ticks every `step` s (offset s past each step) over [from,to) seconds after MON, at a flat price (or rising by rate per s).
const flat=(from,to,step=20,offset=7,bid=1.1000,rate=0)=>{const t=[];for(let s=from;s<to;s+=step)t.push([MON+s+offset,bid+rate*(s-from)]);return t;};
const HOURS=[];for(const d of [0,1])for(let h=2;h<22;h++)HOURS.push(MON+d*DAY+h*H1);   // the 40 hourly episode starts
const session=(step=20,offset=7)=>[0,1].flatMap(d=>flat(d*DAY+2*H1-10*M1,d*DAY+22*H1,step,offset));   // from 01:50 (no signal)
const atr=shift=>shift===1?0.0010:0.0030;
const byRsi=f=>(name,buffer,shift,w)=>name==='ATR_MA'?atr(shift):(name==='RSI'?f(w.time-MON):undefined);
const hourly=(value=25)=>byRsi(t=>(t%H1)<40*M1?value:50);
const overlap=byRsi(t=>(t%(20*M1))<10*M1?25:50);                                     // exp3
const pairs=byRsi(t=>{const m=(t%(40*M1))/M1;return m<5?25:(m<10?80:50);});          // a buy, then a sell episode
const pairsSellFirst=byRsi(t=>{const m=(t%(40*M1))/M1;return m<5?80:(m<10?25:50);});   // a sell, then a buy episode
const exp4=byRsi(t=>{const m=(t%(40*M1))/M1;return m<10?25:(m>=20&&m<30?80:50);});   // exp4/exp5: buy 0-10, sell 20-30
const opposite=byRsi(t=>{const m=(t%H1)/M1;return m<10?25:(m<15?80:50);});           // a buy episode, then the opposite signal
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500,Single_Time_Stop_Bars:30,Single_Time_Stop_TF:'TF_Cur'};
const FLAT={Single_Flat_Only:true};
const RANDOM={Random_Direction:true,Random_Seed:1,Single_Flat_Only:true};
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
const alpha=(inputs,indicator,wx)=>H.build(B50_ALPHA,{inputs:{...BASE,...Object.fromEntries(Object.entries(inputs).filter(([k])=>!/^(Random_|Single_Flat_Only)/.test(k)))},tester:true,fastSpeed:true,indicator,world:wx});
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const closes=W=>W.w.trace.filter(x=>x.op==='PositionClose'||x.op==='BrokerStop'||x.op==='BrokerTake');
const sideString=W=>sends(W).map(s=>s.type).join('');
const barOf=(t,p=M1)=>Math.floor(t/p)*p-p;   // the chart's closed bar at shift 1
// The trade times opened while another single of the same run was still open (one position per OrderSend).
function heldAtOpen(W){let n=0;const out=[];for(const x of W.w.trace){if(x.op==='OrderSend'){if(n>0)out.push(x.time);n++;}if(x.op==='PositionClose'||x.op==='BrokerStop'||x.op==='BrokerTake')n--;}return out;}
function episodes(path,indicator){
 const out=[];let last=[false,false],lastMin=-1;
 for(const [t] of path){
  const m=Math.floor(t/M1);if(m===lastMin)continue;lastMin=m;   // the M1 signal cadence: the first tick of each minute
  const v=indicator('RSI',0,1,{time:t});const now=[v<=30,v>=70];
  for(const s of [0,1]){if(now[s]&&!last[s])out.push([t,s]);}last=now;
 }
 return out;
}
// Runs a fixture as B, S, O and A; checks B against S (the same eligibility) and O against A (flags off).
function compare(label,{inputs={},indicator,path,wx,divergent=0}){
 const B=world({inputs:{...RANDOM,...inputs},indicator,world:wx}),S=world({inputs:{...FLAT,...inputs},indicator,world:wx}),
  O=world({inputs,indicator,world:wx}),A=alpha(inputs,indicator,wx);
 B.run(path);S.run(path);O.run(path);A.run(path);
 assert.deepEqual(O.w.trace,A.w.trace,label+': flags off is B50-alpha');
 assert.ok(sends(S).length>=5,label+': the fixture trades ('+sends(S).length+')');
 const at=new Set(sends(S).map(x=>x.time)),off=sends(B).filter(x=>!at.has(x.time));
 if(divergent!==null) assert.equal(off.length,divergent,label+': benchmark entries not at a strategy moment: '+off.map(x=>(x.time-MON)/M1).join(','));
 if(divergent===0){
  assert.deepEqual(sends(B).map(x=>x.time),sends(S).map(x=>x.time),label+': the benchmark opens exactly at the strategy\'s moments');
  assert.deepEqual(closes(B).map(x=>x.time),closes(S).map(x=>x.time),label+': and exits when it does');
 }
 assert.deepEqual(heldAtOpen(B),[],label+': the benchmark never opens while a single runs');
 assert.deepEqual(heldAtOpen(S),[],label+': nor does the flat-only strategy');
 assert.deepEqual(B.rand,{rand:0,srand:0},label+': no MathRand/MathSrand call');
 assert.ok(!B.w.logs.some(l=>/gated/.test(l)),label+': nothing is consumed by a draw');
 return {B,S,O,A,off};
}

// 1. The reference and the tree's function: SplitMix64's published outputs, golden sequences, a seeded sweep.
{
 assert.equal(R.splitmix64(0n),0xE220A8397B1DCDAFn,'SplitMix64, state 0 (splitmix64.c first output)');
 assert.equal(R.splitmix64(0x9E3779B97F4A7C15n),0x6E789E6AA1B965F4n,'SplitMix64, the second output (state = gamma)');
 const mql=R.mqlRandomSide();
 assert.equal(mql(0,0,0,0).z,0xE220A8397B1DCDAFn,'the tree\'s GoatSingleRandomSide is SplitMix64 (state 0)');
 assert.equal(R.state(5,7,1),(5n^7n)|(1n<<62n),'the state: seed ^ bar ^ signal << 62');
 assert.equal(R.state(5,7,1,3),(5n^7n)|(1n<<62n)|(3n<<40n),'... ^ ordinal << 40');
 const ordGolden=[0,1,2,3,4,5].map(o=>R.referenceSide(1,MON,0,o)).join('');
 assert.equal(ordGolden,'001000','the golden of six episodes of one signal on one bar');
 assert.equal([0,1,2,3,4,5].map(o=>mql(1,MON,0,o).side).join(''),ordGolden);
 for(let k=0;k<500;k++){const o=k%7,b=MON+3600*k;assert.equal(mql(k,b,k%2,o).side,R.referenceSide(k,b,k%2,o));assert.equal(mql(k,b,k%2,o).z,R.splitmix64(R.state(k,b,k%2,o)));}
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

// 2. The hourly fixture: one single per episode at the strategy's moment, its side the episode's draw; the same lots,
//    stops and exits as the strategy (both sides occur). With no overlap, flat-only changes nothing (S is O).
const DAY2=session();
const HOURLY=compare('hourly',{indicator:hourly(),path:DAY2}),RUN=HOURLY.B;
{
 const s=sends(RUN);
 assert.equal(s.length,40,'one single per hourly episode: '+s.length);
 for(const [k,x] of s.entries()) assert.equal(x.time,HOURS[k]+7,'opens on the episode\'s first signal check (episode '+k+')');
 assert.equal(sideString(RUN),SESSION_GOLDEN,'the golden sequence, through the real tick path');
 assert.deepEqual(HOURLY.S.w.trace,HOURLY.O.w.trace,'no overlap: flat-only is flags off');
 const o=sends(HOURLY.S);assert.ok(o.every(x=>x.type===0),'the strategy: a buy signal buys');
 assert.deepEqual(s.map(x=>x.volume),o.map(x=>x.volume),'the same lots');
 assert.deepEqual(s.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),o.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),'the same stop distance');
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

// 4. MathRand and MathSrand are never called; the benchmark's code names neither, nor any clock; the decision comes
//    before the draw.
{
 const main=H.readSource(undefined,H.MAIN);
 const block=main.slice(main.indexOf('// B51:begin b51-random'),main.indexOf('// B51:end b51-random'));
 assert.ok(block.length>1000,'the B51 random block');
 const code=block.split('\n').filter(l=>!/^\s*\/\//.test(l)).join('\n').replace(/\/\/[^\n]*/g,'');
 for(const banned of ['MathRand','MathSrand','TimeCurrent','TimeLocal','TimeGMT','TimeTradeServer','GetTickCount','GetMicrosecondCount'])
  assert.ok(!code.includes(banned),'the benchmark reads no '+banned);
 const rec=code.slice(code.indexOf('void GoatSingleRandomRecord'),code.indexOf('bool GoatSingleBothFree'));
 assert.equal((code.match(/iTime\(/g)||[]).length,1,'one bar read in the block');
 assert.ok(rec.includes('iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig))'),'... in GoatSingleRandomRecord: the chart\'s closed bar');
 const entry=code.slice(code.indexOf('void GoatSingleRandomEntry'));
 assert.ok(entry.indexOf('GoatSingleBothFree()')>0&&entry.indexOf('GoatSingleBothFree()')<entry.indexOf('GoatSingleRandomSide('),'the eligibility is decided before the draw');
 assert.ok(!/b51_side[^;]*\.Active|Active[^;]*b51_side/.test(entry),'and nothing after the draw reads a side\'s occupancy');
 ok();
}

// 5. Sell-signal episodes draw with their own signal bit; the episode is the signal's; Reverse_Seq keeps the coin.
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

// 6. Overlapping episodes (exp3) and late moments: an episode starts while the last single runs; both arms open only
//    once it has ended, the benchmark with its episode's draw: no hedge, not forced to alternate, one draw per episode.
{
 const {B,S,O}=compare('overlap',{indicator:overlap,path:DAY2});
 assert.deepEqual(S.w.trace,O.w.trace,'only buy signals: flat-only changes nothing here');
 const ep=episodes(DAY2,overlap).filter(([,s])=>s===0);
 const draws=sends(B).map(x=>{const e=ep.filter(([t])=>t<=x.time).at(-1);return R.referenceSide(1,barOf(e[0]),0);});
 assert.equal(sideString(B),draws.join(''),'each side is its episode\'s draw');
 assert.notEqual(sideString(B),'01'.repeat(sends(B).length/2),'not forced to alternate');
 const late=byRsi(t=>(t%(20*M1))<15*M1?25:50);
 const L=compare('late moments',{indicator:late,path:DAY2});
 assert.ok(sends(L.B).filter(x=>(x.time-MON)%(20*M1)>=M1).length>=20,'most entries late in their episode');
 const leps=episodes(DAY2,late).filter(([,s])=>s===0);
 const ldraws=sends(L.B).map(x=>{const e=leps.filter(([t])=>t<=x.time).at(-1);return R.referenceSide(1,barOf(e[0]),0);});
 assert.equal(sideString(L.B),ldraws.join(''),'each drawn from its episode\'s first signal bar');
 assert.notEqual(sideString(L.B),sends(L.B).map(x=>R.referenceSide(1,barOf(x.time),0)).join(''),'not from the bar of the late moment');
 ok();
}

// 7. The opposite-signal exit reads the opening episode's signal: exits are the strategy's (exp1, where no opposite
//    signal comes, and a fixture where it does, 10 minutes into each episode).
{
 const n=compare('opposite, none comes',{inputs:{Single_Exit_Opposite:true},indicator:hourly(),path:DAY2});
 assert.ok(sends(n.B).some(x=>x.type===1),'against-signal sides occur');
 const c=compare('opposite, it comes',{inputs:{Single_Exit_Opposite:true},indicator:opposite,path:DAY2});
 assert.ok(c.S.w.logs.filter(l=>/Single Exit: opposite signal/.test(l)).length>=20,'the strategy exits on the opposite signal');
 assert.ok(c.B.w.logs.filter(l=>/Single Exit: opposite signal/.test(l)).length>=20,'and so does every benchmark single, whatever its side');
 ok();
}

// 8. A buy then a sell episode (pairs, exp4). Flags off, alpha hedges (the second episode opens while the first single
//    runs); flat-only skips exactly those entries, in both arms, so no trade opens while the other holds a position.
// Reverse_Seq too (review round 3, P2-B): the strategy's reversed branches carry their own flat-only lines.
for(const [label,ind,n,rev] of [['pairs',pairs,120,false],['exp4',exp4,null,false],['pairs, Reverse_Seq',pairs,120,true],['exp4, Reverse_Seq',exp4,null,true],
 ['pairs (sell first)',pairsSellFirst,120,false],['pairs (sell first), Reverse_Seq',pairsSellFirst,120,true]]){
 const {S,O,B}=compare(label,{inputs:rev?{Reverse_Seq:true}:{},indicator:ind,path:DAY2});
 if(n) assert.equal(sends(O).length,n,label+': alpha hedges every cycle');
 const held=heldAtOpen(O);assert.ok(held.length>=20,label+': flags off opens while a single runs ('+held.length+')');
 const oT=new Set(sends(O).map(x=>x.time)),sT=new Set(sends(S).map(x=>x.time));
 assert.ok([...sT].every(t=>oT.has(t)),label+': every flat-only entry is a flags-off entry');
 const skipped=[...oT].filter(t=>!sT.has(t));
 assert.ok(skipped.length>=20&&skipped.every(t=>held.includes(t)),label+': it skips only entries flags off made while a single ran ('+skipped.length+')');
 const second=sends(B).filter(x=>(x.time-MON)%(40*M1)>=5*M1);
 assert.equal(second.length,0,label+': no second-episode trade at all (none opens while the other arm holds a position)');
 const firstSignal=ind===pairsSellFirst?1:0;   // the signal of each cycle's first episode
 if(rev) assert.ok(sends(S).every(x=>x.type===1-firstSignal),label+': the reversed strategy trades against its first signal');
 const offA=compare(label+', Allow_Opposite_Seq off',{inputs:{Allow_Opposite_Seq:false,...(rev?{Reverse_Seq:true}:{})},indicator:ind,path:DAY2});
 assert.deepEqual(sends(offA.S).map(x=>x.time),sends(offA.O).map(x=>x.time),label+', Allow off: alpha already refuses them');
}
ok();

// 9. Both sides' gates, for both arms: a dashboard that forbids the sell, or a virtual sequence on either side, keeps
//    every single closed, whatever the draw (alpha's own gate asks only the trade side).
{
 for(const label of ['S','B']){
  const inputs=label==='B'?RANDOM:FLAT;
  for(const allowed of [0,1]){
   const D=world({inputs});D.ctx.DashboardEntryAllowed=dir=>dir===allowed;D.run(DAY2);
   assert.equal(sends(D).length,0,label+': a forbidden '+(allowed?'buy':'sell')+' side stops every entry');
  }
  for(const seq of ['Seq_Sell_Virtual','Seq_Buy_Virtual']){
   const V=world({inputs});const v=V.ctx[seq];let inside=false;let stored=v.Active;
   Object.defineProperty(v,'Active',{get:()=>inside||stored,set:z=>{stored=z;},configurable:true});
   const fn=label==='B'?'GoatSingleRandomEntry':'SignalEntryTrigger';const orig=V.ctx[fn];
   V.ctx[fn]=(...a)=>{inside=true;try{return orig(...a);}finally{inside=false;}};
   V.run(flat(2*H1-10*M1,5*H1));
   assert.equal(sends(V).length,0,label+': a virtual sequence on '+seq+' stops every entry');
  }
 }
 const O=world({});O.ctx.DashboardEntryAllowed=dir=>dir===0;O.run(flat(2*H1-10*M1,5*H1));
 assert.equal(sends(O).length,3,'flags off, alpha asks only its trade side (control)');
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

// 11. Flags off: Random_Direction and Single_Flat_Only false (with any seed) trade exactly as B50-alpha.
{
 for(const [label,inputs,indicator,path] of [
  ['single',{},hourly(),flat(2*H1-10*M1,12*H1)],
  ['single, seed 7, sell signal',{Random_Seed:7},hourly(80),flat(2*H1-10*M1,12*H1)],
  ['single, Reverse_Seq, Mode_Trade=Short',{Reverse_Seq:true,Mode_Trade:'Short'},hourly(),flat(2*H1-10*M1,12*H1)],
  ['single, opposite exit',{Single_Exit_Opposite:true,Random_Seed:3},opposite,flat(2*H1-10*M1,12*H1)],
  ['single, pairs (hedges)',{},pairs,flat(2*H1-10*M1,12*H1)],
  ['grid',{Engine_Mode:'Engine_Grid',Random_Seed:9,Delay_Trade:0,Delay_Trade_Live:0,Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4},hourly(),
   [...flat(2*H1,3*H1),...flat(3*H1,6*H1,20,7,1.0960),...flat(6*H1,9*H1,20,7,1.1040)]]]){
  const tree=world({inputs,indicator}),a=alpha(inputs,indicator);
  tree.run(path);a.run(path);
  assert.ok(sends(a).length>=2,label+': the fixture trades');
  assert.deepEqual(tree.w.trace,a.w.trace,label+': flags off trades exactly as B50-alpha');
  assert.deepEqual(tree.w.positions,a.w.positions,label+': the same positions');
 }
 ok();
}

// 12. OnInit: Random_Direction needs the single engine, the tester, both directions and Single_Flat_Only; the seed is
//     not negative; Single_Flat_Only needs the single engine.
{
 const refused=(inputs,tester=true)=>{try{world({inputs,tester});return null;}catch(e){assert.ok(e.initCode!==undefined,'an OnInit refusal, not a crash: '+e.message);return e;}};
 const g=refused({...RANDOM,Engine_Mode:'Engine_Grid'});assert.ok(g&&g.initCode===2,'Random_Direction with Engine_Grid');
 const live=refused(RANDOM,false);assert.ok(live&&live.initCode===1,'Random_Direction on a live chart: INIT_FAILED');
 for(const m of ['Long','Short']){const e=refused({...RANDOM,Mode_Trade:m});assert.ok(e&&e.initCode===2,'Random_Direction with Mode_Trade='+m);}
 const nf=refused({...RANDOM,Single_Flat_Only:false});assert.ok(nf&&nf.initCode===2,'Random_Direction without Single_Flat_Only');
 const fg=refused({Single_Flat_Only:true,Engine_Mode:'Engine_Grid'});assert.ok(fg&&fg.initCode===2,'Single_Flat_Only with Engine_Grid');
 assert.equal(refused({Mode_Trade:'Long'}),null,'Mode_Trade=Long without the benchmark passes');
 assert.equal(refused(FLAT),null,'the flat-only strategy passes');
 const neg=refused({Random_Seed:-1});assert.ok(neg&&neg.initCode===2,'a negative seed');
 assert.equal(refused({Engine_Mode:'Engine_Grid',Random_Seed:5}),null,'Random_Direction off: any non-negative seed passes');
 assert.equal(refused(RANDOM),null);assert.equal(refused({...RANDOM,Random_Seed:0}),null,'seed 0 passes');
 const main=H.readSource(undefined,H.MAIN);const init=main.slice(main.indexOf('// B51:begin b51-init'),main.indexOf('// B51:end b51-init'));
 for(const re of [/if\(Random_Direction && Engine_Mode!=Engine_Single\) +\{Alert\("Initialization Failed: Random_Direction needs the single-trade engine/,
  /if\(Random_Seed<0\) +\{Alert\("Initialization Failed: Random_Seed cannot be negative\."\); return INIT_PARAMETERS_INCORRECT;\}/,
  /if\(Random_Direction && Mode_Trade!=Long_and_Short\) +\{Alert\("Initialization Failed: Random_Direction needs Mode_Trade=Long_and_Short/,
  /if\(Random_Direction && !Single_Flat_Only\) +\{Alert\("Initialization Failed: Random_Direction needs Single_Flat_Only=true/,
  /if\(Single_Flat_Only && Engine_Mode!=Engine_Single\) +\{Alert\("Initialization Failed: Single_Flat_Only needs the single-trade engine/,
  /if\(Random_Direction && !MQLInfoInteger\(MQL_TESTER\)\) +\{Alert\("Initialization Failed: Random_Direction is a strategy-tester benchmark/]) assert.match(init,re);
 ok();
}

// 13. exp5: an uptrend (+200 points per 20 minutes) with SL 1.5 ATR and TP 2R, the exp4 episodes, 12 seeds. The draw
//     does not decide whether an episode trades, so the executed sides stay a fair coin: the sell share is within 3
//     standard errors of 50% (a draw-dependent gate gave 59.9%). Entries that diverge from the strategy's (the exits
//     depend on the side here) are counted.
{
 const RATE=0.0020/1200,path=flat(2*H1-10*M1,22*H1,20,7,1.1000,RATE);
 const inputs={Single_TP_R:2,Single_Time_Stop_Bars:0};
 let n=0,sells=0,divergent=0,strategy=0;
 for(let seed=1;seed<=12;seed++){
  const r=compare('exp5 seed '+seed,{inputs:{...inputs,Random_Seed:seed},indicator:exp4,path,divergent:null});
  n+=sends(r.B).length;sells+=sends(r.B).filter(x=>x.type===1).length;divergent+=r.off.length;strategy+=sends(r.S).length;
  assert.ok(r.B.w.trace.some(x=>x.op==='BrokerTake')&&r.B.w.trace.some(x=>x.op==='BrokerStop'),'exp5 seed '+seed+': side-dependent exits occur');
 }
 const share=sells/n,se=Math.sqrt(0.25/n);
 assert.ok(n>=200,'enough trades ('+n+')');
 assert.ok(Math.abs(share-0.5)<=3*se,'sell share '+share.toFixed(3)+' within 3 SE ('+se.toFixed(3)+') of 50% over '+n+' trades');
 assert.ok(divergent<n,'divergent entries are counted: '+divergent+' of '+n+' (the strategy made '+strategy+')');
 console.log(JSON.stringify({exp5:{trades:n,sellShare:Number(share.toFixed(4)),se:Number(se.toFixed(4)),divergentEntries:divergent,strategyTrades:strategy}}));
 ok();
}

// 14. Several episodes of one signal inside one chart bar (an H1 chart, a buy signal 5 minutes in every 10: six
//     episodes per bar; review round 3, P1-A). Each draws with its ordinal on the bar: independent draws, the
//     reference's, reset on each new bar. Then exp7 (the same on an uptrend with SL 1.5 ATR and TP 2R, 20 seeds): the
//     sell share stays within 3 standard errors of 50% (one draw per bar gave 0.656).
const toggling=byRsi(t=>(t%(10*M1))<5*M1?25:50);
{
 const wx={period:16385},inputs={Single_Time_Stop_Bars:3,Single_Time_Stop_TF:'TF_M1'};
 const {B}=compare('H1 chart, toggling',{inputs,indicator:toggling,path:DAY2,wx});
 const ep=episodes(DAY2,toggling).filter(([,s])=>s===0);
 const ordinals=new Map();const ordOf=new Map();
 for(const [t] of ep){const b=barOf(t,3600);const o=ordinals.has(b)?ordinals.get(b)+1:0;ordinals.set(b,o);ordOf.set(t,[b,o]);}
 assert.equal(sends(B).length,ep.length,'every episode opens');
 const exp=sends(B).map(x=>{const e=ep.filter(([t])=>t<=x.time).at(-1);const [b,o]=ordOf.get(e[0]);return R.referenceSide(1,b,0,o);});
 assert.equal(sideString(B),exp.join(''),'each episode\'s draw: its H1 bar and its ordinal on that bar');
 assert.ok(Math.max(...ordinals.values())===5,'six episodes per bar (ordinals 0-5)');
 const perBar=new Map();for(const x of sends(B)){const b=barOf(x.time,3600);perBar.set(b,(perBar.get(b)||'')+x.type);}
 assert.ok([...perBar.values()].filter(v=>/0/.test(v)&&/1/.test(v)).length>=20,'same-bar episodes take both sides');
 const noOrd=sends(B).map(x=>{const e=ep.filter(([t])=>t<=x.time).at(-1);return R.referenceSide(1,barOf(e[0],3600),0,0);}).join('');
 assert.notEqual(sideString(B),noOrd,'not one draw per bar');
 // A failed bar read at an episode's first check records nothing: the next check records it, with the next ordinal.
 const X=world({inputs:{...RANDOM,...inputs},indicator:toggling,world:wx});const iTime=X.ctx.iTime;
 X.ctx.iTime=(sym,tf,sh)=>{const m=(X.w.time-MON)%3600;return (tf===0&&m>=600&&m<660)?0:iTime(sym,tf,sh);};
 X.run(DAY2);
 const second=sends(X).filter(x=>(x.time-MON)%3600>=600&&(x.time-MON)%3600<1200);
 assert.ok(second.length>=30,'the second episode of each bar opens a minute late ('+second.length+')');
 for(const x of second) assert.equal(x.type,R.referenceSide(1,barOf(x.time,3600),0,1),'... with ordinal 1 at '+(x.time-MON)/M1);
 // The ordinals come from the signal checks, which follow closed bars: a second tick model counts them the same way.
 const F=world({inputs:{...RANDOM,...inputs},indicator:toggling,world:wx});F.run(session(3,1));
 assert.deepEqual(sends(F).map(x=>barOf(x.time)),sends(B).map(x=>barOf(x.time)),'the same entry minutes under a second tick model');
 assert.equal(sideString(F),sideString(B),'and the same draws (the same ordinals)');
 const RATE=0.0020/1200,path=flat(2*H1-10*M1,22*H1,20,7,1.1000,RATE);
 let n=0,sells=0;
 for(let seed=1;seed<=20;seed++){
  const W=world({inputs:{...RANDOM,Random_Seed:seed,Single_TP_R:2,Single_Time_Stop_Bars:0},indicator:toggling,world:wx});W.run(path);
  assert.deepEqual(heldAtOpen(W),[],'exp7 seed '+seed+': flat only');
  n+=sends(W).length;sells+=sends(W).filter(x=>x.type===1).length;
 }
 const share=sells/n,se=Math.sqrt(0.25/n);
 assert.ok(n>=300,'exp7: enough trades ('+n+')');
 assert.ok(Math.abs(share-0.5)<=3*se,'exp7: sell share '+share.toFixed(3)+' within 3 SE ('+se.toFixed(3)+') of 50% over '+n+' trades');
 console.log(JSON.stringify({exp7:{trades:n,sellShare:Number(share.toFixed(4)),se:Number(se.toFixed(4))}}));
 ok();
}

console.log(JSON.stringify({passed,test:'b51_random'}));
