// B50 integration (B50-alpha, the assembled tree: A0 + A0 fix2 + A1 + A2 + A3; docs/b50/B50_ALPHA_DESIGN.md). The
// pieces are each tested on their own branch; this test runs them together through scripts/b50_tick_harness.cjs
// (the tree's converted GoatTickBody, SignalEntryTrigger, GoatSingleOpen, GoatNYClockApply and the exits).
// Expected:
// 1. The clock's entry block holds for the single engine (A0's g_GoatEntryBlocked, set by A2's GoatNYClockApply, versus
//    A1's GoatSingleOpen, which SignalEntryTrigger alone calls): a single whose signal turns true inside the rollover
//    window does not open until the window ends (with and without Delay_Trade: a single has no virtual leg), under
//    either clock; and a live clock mismatch blocks every single until a later self-check passes.
// 2. A full week under the New York clock (09:30-20:00 NY, Action_Friday=Close): A1's entries only in session on Mon-Fri
//    trade dates, one position at a time, A3's exits (opposite signal on the first M15 bar of the opposite trend, the
//    time stop five H1 bars after the entry bar), A2's Friday cutoff (the single open at 16:55 NY Friday is closed then,
//    and nothing opens until Monday's session), and the same trades under FastSpeed as in a visual run.
// Mutants (each must fail at least one expected check): A0's entry guard dropped, the Friday cutoff dropped, A3's
// FastSpeed bypass dropped, A1's re-arm dropped, the opposite exit dropped, GoatNYClockApply's block dropped (all of it,
// and the mismatch alone).
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const NYFILE='GOAT_NYClock.mqh';
const SRC={[H.MAIN]:H.readSource(undefined,H.MAIN),[NYFILE]:H.readSource(undefined,NYFILE)};
const H1=3600,DAY=86400,MON=Date.UTC(2026,9,5)/1000;   // Monday 2026-10-05 00:00 server time
const TREND={buy:[1.12,1.11,1.10],neutral:[1.10,1.12,1.09],sell:[1.08,1.09,1.10]};
// The EMA trend (MA0 fast .. MA2 slow) by phase: [[server time, trend], ...] in time order, 'sell' before the first.
const emaIndicator=phases=>(name,buffer,shift,w)=>{
 if(name==='ATR_MA') return 0.0010;
 const m=name.match(/^MA(\d)$/);if(!m)return undefined;
 let trend='sell';for(const [at,tr] of phases) if(w.time>=at) trend=tr;
 return TREND[trend][Number(m[1])];
};
const BASE={Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Delay_Trade:0,Delay_Trade_Live:0,Mode_Bias:'Bias_Disabled',
 RSI_Mode:'RSI_Disabled',ADX_Mode:'Trade_Disabled',EMA_Mode:'Trade_Trend',EMA_Count:3,EMA_TF_:'TF_M15',Mode_Trade:'Long'};
function world(source,inputs,phases,opts={}){
 const W=H.build(source,{tester:opts.tester??true,fastSpeed:opts.fastSpeed??(opts.tester??true),inputs:{...BASE,...inputs},
  indicator:emaIndicator(phases),start:opts.start??MON,world:opts.world});
 W.panel=[];const setEdit=W.ctx.SetEdit;W.ctx.SetEdit=(field,text,...rest)=>{W.panel.push(String(text));return setEdit(field,text,...rest);};
 W.events=[];const print=W.ctx.Print;
 W.ctx.Print=(...a)=>{print(...a);W.events.push({time:W.w.time,text:a.map(String).join('')});};
 W.maxOpen=0;
 W.ticks=(from,to)=>{for(let s=from;s<to;s+=20){W.tick(MON+s+7,1.1000+((s/20)%2)*0.00002);W.maxOpen=Math.max(W.maxOpen,W.w.positions.length);}};
 return W;
}
const opens=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const closes=W=>W.w.trace.filter(x=>x.op==='PositionClose');
// NYClose: server = NY + 7 h all year.
const NY=t=>t-7*H1,SRV=nyOffset=>MON+7*H1+nyOffset;   // SRV(seconds after Monday 00:00 NY) is a server time
const nyText=t=>new Date(NY(t)*1000).toISOString().slice(5,19);

const CHECKS={
 // 1a. The rollover window (17:00 NY +- 30 min) holds a single back, under the New York clock (in session) and the
 // server clock, with and without Delay_Trade; the unblocked twin opens inside the window.
 rollover_blocks_the_single(src,fail){
  // Tuesday 17:00 NY: under NYClose (the New York clock, 09:30-20:00 NY) that is Wednesday 00:00 server; under Fixed
  // UTC+8 (the server clock, whose default session runs 01:30-11:00 server) it is Wednesday 05:00 server.
  const CASES=[[{Clock_Mode:'Clock_NewYork',NY_Session:'09:30-20:00',Server_Clock_Model:'ServerClock_NYClose'},2*DAY],
   [{Clock_Mode:'Clock_Server',Server_Clock_Model:'ServerClock_Fixed',Server_UTC_Offset:8},2*DAY+5*H1]];
  for(const [clock,at17] of CASES){
   const buyFrom=MON+at17-25*60,from=MON+at17-30*60,to=MON+at17+30*60;
   for(const delay of [0,2]){
    const what=clock.Clock_Mode+' Delay_Trade='+delay;
    const inputs={...clock,Delay_Trade:delay};
    const free=world(src,{...inputs,Rollover_Block_Minutes:0},[[buyFrom,'buy']]);free.ticks(at17-3*H1,at17+3*H1);
    const fo=opens(free)[0];
    if(!fo||fo.time<from||fo.time>=to){fail(what+': the unblocked single opens inside the window ('+(fo?nyText(fo.time):'none')+')');continue;}
    const W=world(src,{...inputs,Rollover_Block_Minutes:30},[[buyFrom,'buy']]);W.ticks(at17-3*H1,at17+3*H1);
    const o=opens(W);
    if(o.some(x=>x.time>=from&&x.time<to)) fail(what+': a single opened inside the rollover window at server '+new Date(o.find(x=>x.time>=from&&x.time<to).time*1000).toISOString());
    if(!o.length) fail(what+': the single opens after the window');
    else if(o[0].time>=to+15*60) fail(what+': the single opens on the first signal check after the window, not at '+nyText(o[0].time));
    if(W.maxOpen>1) fail(what+': one position at a time');
   }
  }
 },
 // 1b. Live, a clock that fails the self-check blocks every single (both clocks); once a check passes the single opens.
 mismatch_blocks_the_single(src,fail){
  // Monday 02:35 server (Clock_Server, in the default server session) and Monday 10:35 NY (Clock_NewYork).
  for(const [clock,start] of [[{Clock_Mode:'Clock_Server',Rollover_Block_Minutes:1},H1],[{Clock_Mode:'Clock_NewYork',NY_Session:'09:30-20:00'},16*H1]]){
   const what='live '+clock.Clock_Mode,buyFrom=MON+start+H1+35*60,fixAt=start+3*H1;
   // October 2026 is US DST: under NYClose the broker is UTC+3. A terminal at UTC+3 agrees, at UTC+2 it does not.
   const good=world(src,clock,[[buyFrom,'buy']],{tester:false,world:{serverOffset:3}});good.ticks(start,fixAt);
   if(!opens(good).length){fail(what+': the agreeing clock trades');continue;}
   const bad=world(src,clock,[[buyFrom,'buy']],{tester:false,world:{serverOffset:2}});bad.ticks(start,fixAt);
   if(opens(bad).length) fail(what+': a clock mismatch blocks the single (opened at '+nyText(opens(bad)[0].time)+' NY)');
   if(!bad.ctx.g_GoatEntryBlocked) fail(what+': the mismatch is the block');
   if(!bad.panel.includes('CLOCK MISMATCH')) fail(what+': "CLOCK MISMATCH" on the panel');
   bad.w.serverOffset=3;bad.ticks(fixAt,fixAt+H1);   // the terminal's clock is right again: the next check passes
   const o=opens(bad);
   if(o.length!==1) fail(what+': the single opens once the self-check passes ('+o.length+')');
   else if(o[0].time<MON+fixAt||o[0].time>=MON+fixAt+16*60) fail(what+': within a signal check of the recovery, not '+nyText(o[0].time));
  }
 },
 // 2. A full week, Monday 2026-10-05 to Monday 2026-10-12, under the New York clock.
 full_week(src,fail){
  // NY hours after Monday 00:00 NY; :35 past, so each turn is read on the :45 M15 bar.
  const turns=[];const cycle=['buy','sell','neutral','buy','buy','sell'];
  for(let h=0,i=0;h<4*24+5;h+=5,i++) turns.push([h,cycle[i%cycle.length]]);
  // Friday: sell from 08:35, buy from 14:35 (open at the cutoff), sell 17:35 and buy 19:35 (after the cutoff, still
  // inside 09:30-20:00), then a sell on Monday 10:35.
  turns.push([4*24+8,'sell'],[4*24+14,'buy'],[4*24+17,'sell'],[4*24+19,'buy'],[7*24+10,'sell']);
  const phases=turns.map(([h,tr])=>[SRV(h*H1+35*60),tr]);
  const inputs={Clock_Mode:'Clock_NewYork',NY_Session:'09:30-20:00',Server_Clock_Model:'ServerClock_NYClose',Mode_Trade:'Long_and_Short',
   Single_Exit_Opposite:true,Single_Time_Stop_Bars:5,Single_Time_Stop_TF:'TF_H1',Action_Friday:'Action_Close',Mode_Restart:'Restart_1'};
  const runs={};
  for(const fastSpeed of [true,false]){
   const W=world(src,inputs,phases,{fastSpeed});
   W.ticks(0,5*DAY);W.ticks(7*DAY-7*H1,7*DAY+20*H1);   // Mon-Fri server days, then Sunday 17:00 NY to Monday 13:00 NY
   runs[fastSpeed]=W;
  }
  const W=runs[true];
  try{assert.deepEqual(runs[true].w.trace.map(({comment,...x})=>x),runs[false].w.trace.map(({comment,...x})=>x));}
  catch{fail('FastSpeed and visual runs trade the same week');}
  const o=opens(W),c=closes(W),ends=W.events.filter(e=>/Sequence Ended \(/.test(e.text));
  if(o.length<10) fail('the week trades ('+o.length+' singles)');
  if(W.maxOpen>1) fail('one position at a time ('+W.maxOpen+')');
  const FRI_CUT=SRV(4*DAY+16*H1+55*60),MON_OPEN=SRV(7*DAY+9*H1+30*60);
  for(const x of o){
   const ny=new Date(NY(x.time)*1000),dow=ny.getUTCDay(),min=ny.getUTCHours()*60+ny.getUTCMinutes();
   if(dow<1||dow>5||min<9*60+30||min>=20*60) fail('an entry outside the NY session: '+nyText(x.time));
   if(x.time>=FRI_CUT&&x.time<MON_OPEN) fail('an entry after the Friday cutoff: '+nyText(x.time));
  }
  // Every close is an exit with its reason; each of the three kinds happens.
  const reasons=ends.map(e=>e.text.match(/Sequence Ended \((.*)\)/)[1]);
  if(c.length!==ends.length) fail('every close ends its sequence ('+c.length+' closes, '+ends.length+' ends)');
  for(const r of ['Single Exit: opposite signal','Single Exit: time stop','Day/Weekend Close']) if(!reasons.includes(r)) fail('the week sees the exit: '+r);
  for(const r of reasons) if(!['Single Exit: opposite signal','Single Exit: time stop','Day/Weekend Close'].includes(r)) fail('an unexpected exit: '+r);
  // Each single: closed by the time stop on the first tick of the fifth H1 bar after its entry bar, by the opposite
  // signal on the first M15 bar of a turn against it, or by the Friday close at 16:55 NY.
  for(const x of o){
   const close=c.find(y=>y.time>=x.time&&y.ticket===x.ticket)||c.find(y=>y.time>=x.time);
   if(!close){if(x.time<MON_OPEN) fail('the single of '+nyText(x.time)+' is closed before the weekend');continue;}
   const end=ends.find(e=>e.time===close.time);const reason=end&&end.text.match(/Sequence Ended \((.*)\)/)[1];
   if(reason==='Single Exit: time stop'&&close.time!==Math.floor(x.time/H1)*H1+5*H1+7) fail('time stop of '+nyText(x.time)+' at '+nyText(close.time));
   if(reason==='Single Exit: opposite signal'&&!phases.some(([t])=>close.time===Math.ceil(t/900)*900+7)) fail('opposite exit of '+nyText(x.time)+' off the turn bar: '+nyText(close.time));
   if(reason==='Day/Weekend Close'&&close.time!==FRI_CUT+7) fail('the Friday close at 16:55 NY, not '+nyText(close.time));
  }
  // The Friday cutoff: the buy opened at 14:45 NY Friday is closed at 16:55:07 NY, the book is flat over the weekend, and
  // Monday's first single opens in Monday's session.
  const fri=o.find(x=>x.time===SRV(4*DAY+14*H1+45*60)+7);
  if(!fri) fail('the Friday 14:45 NY single opens');
  if(!c.some(x=>x.time===FRI_CUT+7)) fail('a close at 16:55:07 NY Friday');
  const after=o.filter(x=>x.time>FRI_CUT);
  if(!after.length||after[0].time<MON_OPEN) fail('the next single opens in Monday\'s session ('+(after[0]?nyText(after[0].time):'none')+')');
 },
};

function runAll(source){
 const failures=[];
 for(const [name,check] of Object.entries(CHECKS)){
  try{check(source,msg=>failures.push(name+': '+msg));}
  catch(e){failures.push(name+': threw '+String(e&&e.message||e).split('\n')[0]);}
 }
 return failures;
}
const withFile=(file,text)=>({files:H.loadSources(undefined,{[file]:text})});

// 1. The tree passes every check, and so does the mutant route with the unmutated files.
assert.deepEqual(runAll(undefined),[],'the assembled tree: the expected checks');
for(const f of [H.MAIN,NYFILE]) assert.deepEqual(runAll(withFile(f,SRC[f])),[],'the override route of the unmutated '+f+' passes');
let passed=Object.keys(CHECKS).length+1;

// 2. Each mutant is killed. [name, file, from, to]
const MUTANTS=[
 ['A0: the entry guard dropped (SignalEntryTrigger runs while blocked)',H.MAIN,'&&!g_GoatEntryBlocked) SignalEntryTrigger();',') SignalEntryTrigger();'],
 ['A2: the clock never blocks',NYFILE,'g_GoatEntryBlocked=(g_GoatNYClockMismatch || ','g_GoatEntryBlocked=(false && '],
 ['A2: a clock mismatch never blocks',NYFILE,'g_GoatEntryBlocked=(g_GoatNYClockMismatch || ','g_GoatEntryBlocked=(false || '],
 ['A2: the Friday cutoff dropped',NYFILE,'   if(phase==1 && session_dow==5 && (dow==6 || (dow==5 && minute>=16*60+55))) phase=2;','   '],
 ['A3: the FastSpeed bypass dropped',H.MAIN,'   if(Engine_Mode!=Engine_Single) // B50 (A3)','   if(true) // B50 (A3)'],
 ['A3: the opposite exit dropped',H.MAIN,'   if(Engine_Mode!=Engine_Single || !Single_Exit_Opposite) return;','   return;'],
 ['A1: the re-arm dropped (buy)',H.MAIN,'   if(!LastBuySignal) g_GoatSingleArmed[OP_BUY]=true;','   if(false) g_GoatSingleArmed[OP_BUY]=true;'],
];
const killed={};
for(const [name,file,from,to] of MUTANTS){
 assert.equal(SRC[file].split(from).length,2,'the mutant site is unique: '+name);
 const f=runAll(withFile(file,SRC[file].replace(from,to)));
 assert.ok(f.length>0,'mutant killed: '+name);
 killed[name]=f[0];passed++;
}
console.log(JSON.stringify({passed,test:'b50_integration',checks:Object.keys(CHECKS).length,mutants:MUTANTS.length,killed},null,1));
