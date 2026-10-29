// B51 random-direction benchmark (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8): Engine_Single with
// Random_Direction on the real OnTick path. scripts/b50_tick_harness.cjs converts this tree's GoatTickBody,
// SignalEntryTrigger, GoatSingleRandomEntry and GoatSingleOpen; scripts/b51_random_reference.cjs evaluates this tree's
// GoatSingleRandomSide with MQL's ulong rules (the harness does not model them) and is installed in its place.
// Fixture: RSI_OverBS drives one buy-signal episode per hour (RSI 25 for 40 minutes, then 50), each single closed by
// a 30-bar time stop on M1, from 02:00 to 22:00 on Monday and Tuesday (inside the default 01:30-22:30 session): 40
// episodes. The price is flat, so every single opens and closes at the same times whatever its side.
// Proves:
// - the side is splitmix64((ulong)Random_Seed XOR (ulong)signal-bar open time) & 1: the published SplitMix64 outputs,
//   fixed golden sequences for fixed seeds, and the tree's function equal to the JavaScript reference;
// - the signal bar is the chart's closed bar (shift Shift_Sig = 1), never the tick's time: the same bar flips the same
//   way under two tick models (a tick every 20 s, 7 s past, and every 3 s, 1 s past) and on a replay;
// - only the side changes: entry times, volumes, stops and exits are the flags-off run's;
// - MathRand and MathSrand are never called (the tester magic's stream is untouched);
// - the episode is the signal's (its own arm flag, Reverse_Seq does not move the side), and the drawn side's own gates
//   apply (Mode_Trade, DashboardEntryAllowed): a gated flip leaves the episode armed for the next signal check;
// - flags off (Random_Direction false, any seed) the tree trades exactly as B50-alpha (32df4eb);
// - OnInit refuses Random_Direction with Engine_Grid, outside the tester, and a negative seed.
// scripts/test_b51_random_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail it.
// What it does not prove: compile cleanliness or MT5's own ulong arithmetic. The MetaEditor compile and a native run
// (the deal table's sides against this file's reference) do.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const R=require('./b51_random_reference.cjs');
const B50_ALPHA='32df4eb';
let passed=0;const ok=()=>passed++;

const MON=Date.UTC(2026,9,5)/1000,H1=3600,M1=60;
// Ticks every `step` s (offset s past each step) over [from,to) seconds after MON, at a flat price.
const flat=(from,to,step=20,offset=7,bid=1.1000)=>{const t=[];for(let s=from;s<to;s+=step)t.push([MON+s+offset,bid]);return t;};
const DAY=86400,HOURS=[];for(const d of [0,1])for(let h=2;h<22;h++)HOURS.push(MON+d*DAY+h*H1);   // the 40 episode starts
const session=(step=20,offset=7)=>[0,1].flatMap(d=>flat(d*DAY+2*H1-10*M1,d*DAY+22*H1,step,offset));   // from 01:50 (no signal), so 02:00 is a new minute
// RSI: within each hour, `value` for the first 40 minutes, then 50 (no signal), which re-arms the episode.
const hourly=(value=25)=>(name,buffer,shift,w)=>{
 if(name==='ATR_MA') return shift===1?0.0010:0.0030;
 if(name==='RSI') return ((w.time-MON)%H1)<40*M1?value:50;
 return undefined;};
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500,Single_Time_Stop_Bars:30,Single_Time_Stop_TF:'TF_Cur'};
const RANDOM={Random_Direction:true,Random_Seed:1};
const SESSION_GOLDEN='0010000111111111101000000101101001011001';   // seed 1, the 40 episodes' signal bars
// A world on this tree (or `source`), with the MQL side function installed and MathRand/MathSrand counted.
function world({inputs={},value=25,source,tester=true,fastSpeed=true}={}){
 const W=H.build(source,{inputs:{...BASE,...inputs},tester,fastSpeed,indicator:hourly(value)});
 if(source===undefined){
  R.install(W);
  W.rand={rand:0,srand:0};let x=12345;
  W.ctx.MathRand=()=>{W.rand.rand++;x=(x*1103515245+12345)%32768;return x;};W.ctx.MathSrand=()=>{W.rand.srand++;};
 }
 return W;
}
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const strip=trace=>trace.map(x=>({...x}));
const sideString=W=>sends(W).map(s=>s.type).join('');
const signalBar=t=>Math.floor(t/M1)*M1-M1;   // the chart's (M1) closed bar at shift 1

// 1. The reference and the tree's function: SplitMix64's published outputs, the golden sequences, a seeded sweep.
{
 assert.equal(R.splitmix64(0n),0xE220A8397B1DCDAFn,'SplitMix64, state 0 (splitmix64.c first output)');
 assert.equal(R.splitmix64(0x9E3779B97F4A7C15n),0x6E789E6AA1B965F4n,'SplitMix64, the second output (state = gamma)');
 const mql=R.mqlRandomSide();
 assert.equal(mql(0,0).z,0xE220A8397B1DCDAFn,'the tree\'s GoatSingleRandomSide is SplitMix64 (state 0)');
 const seq=(f,seed,start,step,n)=>Array.from({length:n},(_,k)=>f(seed,start+k*step)).join('');
 const GOLDEN={
  's1 M1':[1,MON,M1,64,'0000000101010110000001000000000010111000110110011101011001000100'],
  's2 M1':[2,MON,M1,64,'0010110001101000110000100110101100001011101000000010011011000101'],
  's1 H1':[1,MON-M1,H1,48,'100010000111111111101000110000010110100101100101'],
 };
 // This file's 40 episodes: each opens on its hour's first tick, whose signal bar opens a minute before the hour.
 assert.equal(HOURS.map(h=>R.referenceSide(1,h-M1)).join(''),SESSION_GOLDEN,'the golden of the 40 episodes');
 assert.equal(HOURS.map(h=>mql(1,h-M1).side).join(''),SESSION_GOLDEN);
 for(const [name,[seed,start,step,n,bits]] of Object.entries(GOLDEN)){
  assert.equal(seq(R.referenceSide,seed,start,step,n),bits,'the JavaScript reference reproduces the golden '+name);
  assert.equal(seq((s,b)=>mql(s,b).side,seed,start,step,n),bits,'the tree\'s GoatSingleRandomSide reproduces the golden '+name);
 }
 let s=20261029;const rnd=()=>(s=(s*48271)%2147483647);
 let ones=0;
 for(let k=0;k<4000;k++){
  const seed=k<4?[0,1,2147483646,2147483647][k]:rnd(),bar=k%2?MON+60*(rnd()%500000):rnd()*2;
  const got=mql(seed,bar);
  assert.equal(got.side,R.referenceSide(seed,bar),'side for seed '+seed+', bar '+bar);
  assert.equal(got.z,R.splitmix64(BigInt(seed)^BigInt(bar)),'the whole 64-bit state for seed '+seed+', bar '+bar);
  ones+=got.side;
 }
 assert.ok(ones>1800&&ones<2200,'about half sells ('+ones+' of 4000)');
 ok();
}

// 2. On the tick path: one single per hourly episode, its side the reference's for the signal bar; both sides occur;
//    entry times, volumes, stop distances and exit times are the flags-off run's (only the side changes).
const DAY2=session();
const RUN=(()=>{const W=world({inputs:RANDOM});W.run(DAY2);return W;})();
{
 const s=sends(RUN);
 assert.equal(s.length,40,'one single per hourly episode: '+s.length);
 for(const [k,x] of s.entries()){
  assert.equal(x.time,HOURS[k]+7,'opens on the episode\'s first signal check (episode '+k+')');
  assert.equal(x.type,R.referenceSide(1,signalBar(x.time)),'hour '+k+': the side is the reference\'s for the signal bar');
 }
 assert.equal(sideString(RUN),SESSION_GOLDEN,'the golden sequence, through the real tick path');
 assert.ok(s.some(x=>x.type===0)&&s.some(x=>x.type===1),'both sides');
 const OFF=world({});OFF.run(DAY2);
 const o=sends(OFF);
 assert.equal(o.length,40);assert.ok(o.every(x=>x.type===0),'flags off, a buy signal buys');
 assert.deepEqual(s.map(x=>x.time),o.map(x=>x.time),'the same entry times');
 assert.deepEqual(s.map(x=>x.volume),o.map(x=>x.volume),'the same lots');
 assert.deepEqual(s.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),o.map(x=>Math.round(Math.abs(x.price-x.sl)*1e5)),'the same stop distance');
 const closes=W=>W.w.trace.filter(x=>x.op==='PositionClose').map(x=>x.time);
 assert.equal(closes(RUN).length,40);assert.deepEqual(closes(RUN),closes(OFF),'the same exits (the time stop)');
 assert.ok(RUN.w.logs.some(l=>/Single Exit: time stop/.test(l)));
 ok();
}

// 3. The signal bar, not the tick: a second tick model (every 3 s, 1 s past) and a replay flip every bar the same way.
{
 const FINE=world({inputs:RANDOM});FINE.run(session(3,1));
 const a=sends(RUN),b=sends(FINE);
 assert.equal(b.length,a.length);
 assert.notDeepEqual(b.map(x=>x.time),a.map(x=>x.time),'the two tick models open at different seconds');
 assert.deepEqual(b.map(x=>signalBar(x.time)),a.map(x=>signalBar(x.time)),'... of the same bars');
 assert.equal(sideString(FINE),sideString(RUN),'and flip every bar the same way');
 const REPLAY=world({inputs:RANDOM});REPLAY.run(DAY2);
 assert.deepEqual(strip(REPLAY.w.trace),strip(RUN.w.trace),'a replay trades exactly the same');
 // A different seed is a different benchmark.
 const S2=world({inputs:{...RANDOM,Random_Seed:2}});S2.run(DAY2);
 assert.equal(sends(S2).length,40);assert.notEqual(sideString(S2),sideString(RUN),'seed 2 differs from seed 1');
 assert.ok(sends(S2).every(x=>x.type===R.referenceSide(2,signalBar(x.time))),'seed 2 is the reference\'s');
 ok();
}

// 4. MathRand and MathSrand are never called (the tester magic owns that stream); the benchmark's code names neither.
{
 for(const W of [RUN]) assert.deepEqual(W.rand,{rand:0,srand:0},'no MathRand/MathSrand call on the tick path');
 const W=world({inputs:{...RANDOM,Random_Seed:7},value:80});W.run(flat(2*H1-10*M1,8*H1));
 assert.equal(sends(W).length,6);assert.equal(sideString(W),'000101','seed 7, the sell signal');assert.deepEqual(W.rand,{rand:0,srand:0});
 const main=H.readSource(undefined,H.MAIN);
 const block=main.slice(main.indexOf('// B51:begin b51-random'),main.indexOf('// B51:end b51-random'));
 assert.ok(block.length>1000,'the B51 random block');
 const code=block.split('\n').filter(l=>!/^\s*\/\//.test(l)).join('\n').replace(/\/\/[^\n]*/g,'');
 for(const banned of ['MathRand','MathSrand','TimeCurrent','TimeLocal','TimeGMT','TimeTradeServer','GetTickCount','GetMicrosecondCount'])
  assert.ok(!code.includes(banned),'the benchmark reads no '+banned);
 ok();
}

// 5. The episode is the signal's: a sell-signal episode consumes its own flag; Reverse_Seq does not move the side.
{
 const S=world({inputs:RANDOM,value:80});S.run(DAY2);
 const s=sends(S);assert.equal(s.length,40,'one single per sell-signal episode');assert.equal(sideString(S),SESSION_GOLDEN);
 assert.ok(s.every(x=>x.type===R.referenceSide(1,signalBar(x.time))),'the sell signal\'s side is the coin\'s too');
 assert.ok(s.some(x=>x.type===0)&&s.some(x=>x.type===1));
 // Inside an episode (minute 35): the sell signal's flag is consumed, the buy signal's is not.
 const mid=world({inputs:RANDOM,value:80});mid.run(flat(2*H1-10*M1,2*H1+35*M1));
 assert.equal(sends(mid).length,1);assert.deepEqual([...mid.ctx.g_GoatSingleArmed],[true,false],'the signal\'s own flag');
 const midB=world({inputs:RANDOM});midB.run(flat(2*H1-10*M1,2*H1+35*M1));assert.deepEqual([...midB.ctx.g_GoatSingleArmed],[false,true]);
 const REV=world({inputs:{...RANDOM,Reverse_Seq:true}});REV.run(DAY2);
 assert.equal(sideString(REV),sideString(RUN),'Reverse_Seq: the same coin');
 const REVoff=world({inputs:{Reverse_Seq:true}});REVoff.run(flat(2*H1-10*M1,4*H1));assert.ok(sends(REVoff).every(x=>x.type===1),'flags off, Reverse_Seq still sells the buy signal');
 ok();
}

// 6. The drawn side's own gates: Mode_Trade=Long refuses a sell flip; the episode stays armed and the next signal check
//    (the next bar, its own flip) opens a buy. DashboardEntryAllowed is asked for the drawn side.
{
 const L=world({inputs:{...RANDOM,Mode_Trade:'Long'}});L.run(DAY2);
 const s=sends(L);
 assert.ok(s.length>=30&&s.every(x=>x.type===0),'Mode_Trade=Long: buys only ('+s.length+')');
 for(const x of s){
  assert.equal(R.referenceSide(1,signalBar(x.time)),0,'it opens on a bar that flips buy');
  // every earlier minute of this episode flipped sell (gated), so nothing opened before
  const hour=Math.floor((x.time-MON)/H1)*H1+MON;
  for(let m=hour;m<Math.floor(x.time/M1)*M1;m+=M1) assert.equal(R.referenceSide(1,m-M1),1,'a gated sell flip at '+(m-MON)/M1);
 }
 assert.ok(s.some(x=>x.time>Math.floor((x.time-MON)/H1)*H1+MON+M1),'some episodes wait for a buy flip');
 const Sh=world({inputs:{...RANDOM,Mode_Trade:'Short'}});Sh.run(DAY2);
 assert.ok(sends(Sh).length>=30&&sends(Sh).every(x=>x.type===1&&R.referenceSide(1,signalBar(x.time))===1),'Mode_Trade=Short: sells only, on sell flips');
 const asked=[];const D=world({inputs:RANDOM});
 D.ctx.DashboardEntryAllowed=dir=>{asked.push([dir,D.w.time]);return false;};D.run(flat(2*H1-10*M1,4*H1));
 assert.equal(sends(D).length,0,'DashboardEntryAllowed refuses');
 assert.ok(asked.length>=60,'asked on every signal check of the two episodes ('+asked.length+')');
 assert.ok(asked.some(([d])=>d===0)&&asked.some(([d])=>d===1),'for both sides');
 for(const [dir,t] of asked) assert.equal(dir,R.referenceSide(1,signalBar(t)),'asked for the drawn side at '+(t-MON));
 assert.equal(D.ctx.g_GoatSingleArmed[0],true,'a refused flip leaves the episode armed');
 ok();
}

// 7. Flags off: Random_Direction false (with any seed) trades exactly as B50-alpha, single and grid alike.
{
 for(const [label,inputs,fixture] of [
  ['single',{},{}],
  ['single, seed 7, sell signal',{Random_Seed:7},{value:80}],
  ['single, Reverse_Seq',{Reverse_Seq:true},{}],
  ['grid',{Engine_Mode:'Engine_Grid',Random_Seed:9,Delay_Trade:0,Delay_Trade_Live:0,Grid_Size:-1.5,Lock_Profit_Size:-1.0,TP_Pips:3.0,TSL_Size:-0.4},{}]]){
  const own=Object.fromEntries(Object.entries(inputs).filter(([k])=>!/^Random_/.test(k)));
  const path=label==='grid'?[...flat(2*H1,3*H1),...flat(3*H1,6*H1,20,7,1.0960),...flat(6*H1,9*H1,20,7,1.1040)]:flat(2*H1,12*H1);
  const tree=world({inputs,...fixture}),alpha=H.build(B50_ALPHA,{inputs:{...BASE,...own},tester:true,fastSpeed:true,indicator:hourly(fixture.value||25)});
  tree.run(path);alpha.run(path);
  assert.ok(sends(alpha).length>=2,label+': the fixture trades');
  assert.deepEqual(strip(tree.w.trace),strip(alpha.w.trace),label+': Random_Direction off trades exactly as B50-alpha');
  assert.deepEqual(tree.w.positions,alpha.w.positions,label+': the same positions');
 }
 ok();
}

// 8. OnInit: Random_Direction needs the single engine and the tester; the seed is not negative.
{
 const refused=(inputs,tester=true)=>{try{world({inputs,tester});return null;}catch(e){assert.ok(e.initCode!==undefined,'an OnInit refusal, not a crash: '+e.message);return e;}};
 const g=refused({...RANDOM,Engine_Mode:'Engine_Grid'});
 assert.ok(g,'Random_Direction with Engine_Grid is refused');assert.equal(g.initCode,2,'INIT_PARAMETERS_INCORRECT');
 const live=refused(RANDOM,false);
 assert.ok(live,'Random_Direction on a live chart is refused');assert.equal(live.initCode,1,'INIT_FAILED');
 const neg=refused({Random_Seed:-1});assert.ok(neg,'a negative seed is refused');assert.equal(neg.initCode,2);
 assert.equal(refused({Engine_Mode:'Engine_Grid',Random_Seed:5}),null,'Random_Direction off: any non-negative seed passes');
 assert.equal(refused(RANDOM),null,'Engine_Single in the tester passes');
 assert.equal(refused({Random_Seed:0,...{Random_Direction:true}}),null,'seed 0 passes');
 // Each refusal alerts its reason (the harness throws before the alert can be read, so the source is checked).
 const main=H.readSource(undefined,H.MAIN);const init=main.slice(main.indexOf('// B51:begin b51-init'),main.indexOf('// B51:end b51-init'));
 for(const re of [/if\(Random_Direction && Engine_Mode!=Engine_Single\) +\{Alert\("Initialization Failed: Random_Direction needs the single-trade engine/,
  /if\(Random_Seed<0\) +\{Alert\("Initialization Failed: Random_Seed cannot be negative\."\); return INIT_PARAMETERS_INCORRECT;\}/,
  /if\(Random_Direction && !MQLInfoInteger\(MQL_TESTER\)\) +\{Alert\("Initialization Failed: Random_Direction is a strategy-tester benchmark/]) assert.match(init,re);
 ok();
}

console.log(JSON.stringify({passed,test:'b51_random'}));
