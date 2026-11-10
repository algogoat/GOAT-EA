// B54 PR A (docs/b54/BREAKOUT_ENTRIES_SPEC.md 3.2-3.6, 6.3): entry A, the N-bar / prior-day breakout, through
// scripts/b50_tick_harness.cjs (the real UpdateCurrentSignals, SignalEntryTrigger and GoatTickBody, OnInit's slices).
// 1. The signal (GoatBrkSignal on closed trigger bar s = 1):
//    - N-bar levels are bars 2..N+1: a high at bar N+2 and bar s's own high are outside; the forming bar is never read;
//      a close equal to the level is no break; the buffer is BRK_Buffer_ATR x the ATR of the newest ATR_TF bar closed at
//      or before bar s's close, found by time.
//    - prior day: D is the newest Mon-Fri D1 bar before the one holding bar s, found from bar s's open (a Monday skips a
//      Sunday stub; the first tick after midnight still reads the previous day's D); a fresh cross only; a gap past the
//      level fires on the day's first trigger bar.
//    - unreadable data is OP_NULL, logged once per cause.
// 2. Ticks: a prior-day up-cross opens one single; after it is stopped out, a second up-cross the same day is latched
//    (BRK_Once_Per_Level=false trades it: the control). Under Reverse_Seq the up-cross opens a sell, the second is latched,
//    and a down-cross the same day opens a buy (the latch is keyed by the signal's direction, spec 3.5 item 3).
// 3. OnInit's rebuild from deal history: the signal direction of each MAGIC1 entry whose trigger bar lies in the current
//    trigger bar's day (flipped under Reverse_Seq; a deal just after midnight belongs to the previous day's trigger bar);
//    other magics are ignored; an unreadable history latches the first day read both ways.
// 4. Load-bearing: the spec's mutants (6.3: the latch removed, the latch keyed by position side, Close[0] read, bar 1 inside
//    the level, >= for >, the Sunday stub kept, D taken at evaluation time) plus the ATR read at evaluation time and the
//    fresh-cross condition dropped must each be caught.
// Also: FastSpeed both ways; the opposite exit as the opposite break; Random_Direction with the latch, for five seeds.
// Flags-off parity against B53 is scripts/test_b54_parity.cjs.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const K=H.API_CONSTANTS,HR=3600;
const T=(y,m,d,h=0,mi=0,s=0)=>Date.UTC(y,m-1,d,h,mi,s)/1000;
const SEC={[K.PERIOD_M1]:60,[K.PERIOD_M5]:300,[K.PERIOD_M15]:900,[K.PERIOD_M30]:1800,[K.PERIOD_H1]:3600,[K.PERIOD_H4]:14400,[K.PERIOD_D1]:86400};
const bar=(open,high,low,close)=>({open,high,low,close});
const FLAT=bar(1.1,1.1,1.1,1.1);
// bars: {seconds per bar: {open time: bar}}; every other bar is flat at 1.1000.
const seriesOf=bars=>(tf,shift,barTime)=>((bars[SEC[tf]]||{})[barTime])||FLAT;
const tree=H.loadSources();
const OP=(()=>{const m=H.compile(tree).macros;return {BUY:Number(m.get('OP_BUY').body),SELL:Number(m.get('OP_SELL').body),NULL:Number(m.get('OP_NULL').body)};})();
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',RSI_Mode:'RSI_Disabled',Mode_Bias:'Bias_Disabled',
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,BRK_TF_:'TF_H1'};
function world(files,{inputs={},at,bars={},atr=()=>0.0010,fastSpeed=true}={}){
 return H.build({files},{tester:true,fastSpeed,start:at,inputs:{...BASE,...inputs},series:seriesOf(bars),
  indicator:(name,buffer,shift,w)=>name==='ATR_MA'?atr(shift,w):undefined});
}
const name=v=>v===OP.BUY?'BUY':v===OP.SELL?'SELL':v===OP.NULL?'NULL':String(v);

// 1. The signal.
function signal(files){
 const P=[],expect=(what,got,want)=>{if(got!==want)P.push(what+': '+name(got)+', wanted '+name(want));};
 // N-bar, N=3, Tuesday 2026-10-06 10:30:30: s is the 09:00 bar, the channel 06:00-08:00 (high 1.1050, low 1.0950); the
 // 05:00 bar (N+2) and bar s itself reach further, and the forming 10:00 bar closes at 1.0.
 const tue=h=>T(2026,10,6,h);
 const nbar=c=>({[HR]:{[tue(5)]:bar(1.1,1.2,1.0,1.1),[tue(6)]:bar(1.1,1.1040,1.0960,1.1),[tue(7)]:bar(1.1,1.1050,1.0950,1.1),
  [tue(8)]:bar(1.1,1.1030,1.0970,1.1),[tue(9)]:bar(1.1,1.1070,1.0930,c),[tue(10)]:bar(1.1,1.1,1.0,1.0)}});
 const at=T(2026,10,6,10,30,30);
 const nb=(c,inputs={},atr)=>world(files,{inputs:{BRK_Mode:'BRK_NBar',BRK_Bars:3,...inputs},at,bars:nbar(c),atr}).ctx.GoatBrkSignal(1);
 expect('N-bar: close above bars 2..N+1',nb(1.1060),OP.BUY);
 expect('N-bar: close at the channel high',nb(1.1050),OP.NULL);
 expect('N-bar: close below bars 2..N+1',nb(1.0940),OP.SELL);
 expect('N-bar: close at the channel low',nb(1.0950),OP.NULL);
 // The M1 ATR bar closed at or before 10:00:00 (bar s's close) is the 09:59 bar, shift 31 at 10:30:30; every other 0.05.
 const byTime=shift=>shift===31?0.0010:0.0500;
 expect('N-bar: inside the 1.0 x ATR buffer',nb(1.1059,{BRK_Buffer_ATR:1.0},byTime),OP.NULL);
 expect('N-bar: past the 1.0 x ATR buffer (ATR found by time)',nb(1.1061,{BRK_Buffer_ATR:1.0},byTime),OP.BUY);
 {const W=world(files,{inputs:{BRK_Mode:'BRK_NBar',BRK_Bars:3},at,bars:nbar(1.1060),atr:()=>undefined});
  expect('N-bar: ATR unreadable',W.ctx.GoatBrkSignal(1),OP.NULL);W.ctx.GoatBrkSignal(1);
  const n=W.w.logs.filter(l=>/GOAT signals: BRK ATR unreadable/.test(l)).length;if(n!==1)P.push('ATR unreadable logged '+n+' times, wanted once');}
 // Prior day. Friday 2026-10-09 high 1.1000 / low 1.0900; the Sunday stub 10-11 high 1.1050 / low 1.0950; Monday 10-12.
 const d1={[T(2026,10,9)]:bar(1.095,1.1000,1.0900,1.095),[T(2026,10,11)]:bar(1.1,1.1050,1.0950,1.1),[T(2026,10,12)]:bar(1.099,1.1060,1.0950,1.105)};
 const mon=h=>T(2026,10,12,h);
 const pd=(at,h1)=>world(files,{inputs:{BRK_Mode:'BRK_PriorDay'},at,bars:{[HR]:h1,[86400]:d1}});
 const sig=(at,h1)=>pd(at,h1).ctx.GoatBrkSignal(1);
 expect('prior day: Monday crosses Friday\'s high, the Sunday stub skipped',sig(T(2026,10,12,10,30,30),{[mon(8)]:bar(1.099,1.099,1.099,1.0990),[mon(9)]:bar(1.099,1.103,1.099,1.1020)}),OP.BUY);
 expect('prior day: already above, no fresh cross',sig(T(2026,10,12,10,30,30),{[mon(8)]:bar(1.101,1.101,1.101,1.1010),[mon(9)]:bar(1.101,1.103,1.101,1.1020)}),OP.NULL);
 expect('prior day: Monday crosses Friday\'s low',sig(T(2026,10,12,10,30,30),{[mon(8)]:bar(1.0905,1.0905,1.0905,1.0905),[mon(9)]:bar(1.0905,1.0905,1.088,1.0890)}),OP.SELL);
 // At 00:00:30 Tuesday, s is Monday's 23:00 bar: D is Friday (high 1.1000), not Monday (1.1060).
 {const W=pd(T(2026,10,13,0,0,30),{[mon(22)]:bar(1.099,1.099,1.099,1.0990),[mon(23)]:bar(1.099,1.1055,1.099,1.1050)});
  expect('prior day: the first tick after midnight reads bar s\'s day',W.ctx.GoatBrkSignal(1),OP.BUY);
  if(W.ctx.g_GoatBrkDay!==T(2026,10,12)) P.push('prior day: the latch day is '+W.ctx.g_GoatBrkDay+', wanted Monday');}
 // Tuesday's first bar gaps past Monday's high (1.1060); its predecessor (Monday 23:00) lies in D.
 expect('prior day: a gap fires on the day\'s first trigger bar',sig(T(2026,10,13,1,0,30),{[mon(23)]:bar(1.099,1.1055,1.099,1.1050),[T(2026,10,13,0)]:bar(1.107,1.108,1.107,1.1075)}),OP.BUY);
 return P;
}

// 2. Ticks. Monday 2026-10-05's D1 bar: high 1.1000, low 1.0900. Tuesday's H1 closes: 08:00 1.0990, 09:00 1.1010 (an up-cross),
// 10:00 1.0995, 11:00 1.1012 (a second up-cross), 12:00 1.0895 (a down-cross); the rest flat at 1.1000.
const DAY_BARS={[86400]:{[T(2026,10,5)]:bar(1.095,1.1000,1.0900,1.095)},[HR]:{[T(2026,10,6,8)]:bar(1.099,1.099,1.099,1.0990),
 [T(2026,10,6,9)]:bar(1.099,1.101,1.099,1.1010),[T(2026,10,6,10)]:bar(1.1,1.1,1.099,1.0995),[T(2026,10,6,11)]:bar(1.0995,1.1012,1.0995,1.1012),
 [T(2026,10,6,12)]:bar(1.1012,1.1012,1.0895,1.0895)}};
function path(points){   // a tick every 20 s (7 s past), linear between [time, bid] points
 const ticks=[];
 for(let k=1;k<points.length;k++){const [t0,p0]=points[k-1],[t1,p1]=points[k];for(let t=t0;t<t1;t+=20) ticks.push([t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);}
 return ticks;
}
const at=(h,m=0)=>T(2026,10,6,h,m);
function ticks(files){
 const P=[];
 const run=(inputs,points,fastSpeed=true)=>{const W=world(files,{inputs:{BRK_Mode:'BRK_PriorDay',...inputs},at:at(9,59),bars:DAY_BARS,fastSpeed});W.run(path(points));return W;};
 const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
 // The buy from the 09:00 up-cross is stopped out at 10:40 (SL 1.5 x 0.0010 below); the 11:00 up-cross is the same day's.
 const down=[[at(10),1.1000],[at(10,30),1.1000],[at(10,40),1.0970],[at(14),1.0990]];
 // The 12:00 down-cross is a sell signal of its own (not latched by the buys): it opens a sell at 13:00.
 const kinds=W=>sends(W).map(x=>(x.type===0?'buy':'sell')+'@'+new Date(x.time*1000).toISOString().slice(11,13)).join(',');
 const W=run({},down);
 if(kinds(W)!=='buy@10,sell@13') P.push('one up-cross per day: orders '+kinds(W)+', wanted buy@10,sell@13');
 const C=run({BRK_Once_Per_Level:false},down);
 if(!kinds(C).startsWith('buy@10,buy@12')) P.push('control: BRK_Once_Per_Level=false trades the second up-cross (orders '+kinds(C)+', wanted buy@10,buy@12 first)');
 // Reverse_Seq: the up-cross opens a sell (stopped out as the price rises), the second up-cross is latched, and the 12:00
 // down-cross opens a buy at 13:00.
 const up=[[at(10),1.1000],[at(10,30),1.1000],[at(10,40),1.1030],[at(14),1.1010]];
 const R=run({Reverse_Seq:true},up);
 const types=sends(R).map(x=>x.type===0?'buy':'sell');
 if(types.join(',')!=='sell,buy') P.push('Reverse_Seq: orders '+types.join(',')+', wanted sell,buy');
 // FastSpeed both ways: the same orders, prices, stops, closes and times. Only the order comment differs (FastSpeed sends
 // none, as B53 does), so it is left out of the comparison.
 const bare=W=>JSON.stringify(W.w.trace.map(({comment,...x})=>x));
 for(const [label,inputs,points] of [['plain',{},down],['Reverse_Seq',{Reverse_Seq:true},up]]){
  const fast=run(inputs,points,true),visual=run(inputs,points,false);
  if(bare(fast)!==bare(visual)) P.push('FastSpeed true and false trade alike ('+label+')');
 }
 // The opposite exit is the opposite break (spec 5): with Single_Exit_Opposite the 10:00 buy, never stopped on a flat
 // path, is closed at 13:00 by the 12:00 down-cross (GoatSignalAll carries the term), and the sell opens then.
 const E=run({Single_Exit_Opposite:true},[[at(10),1.1000],[at(14),1.1000]]);
 const closes=E.w.trace.filter(x=>/^(PositionClose|BrokerStop|BrokerTake)$/.test(x.op)).map(x=>new Date(x.time*1000).toISOString().slice(11,13));
 if(kinds(E)!=='buy@10,sell@13'||closes[0]!=='13') P.push('opposite exit: orders '+kinds(E)+', first close at '+closes[0]+', wanted buy@10,sell@13 and a 13:00 close');
 // Random_Direction (spec 3.5 item 4): the latch is checked before the draw and recorded for the signal, so for every
 // seed the day's second up-cross opens nothing, whichever side the first draw took (a 30-bar time stop frees the
 // first by 10:31); with BRK_Once_Per_Level=false it opens at 12:00.
 const RD={Random_Direction:true,Single_Flat_Only:true,Single_Time_Stop_Bars:30,Single_Time_Stop_TF:'TF_Cur'};
 const flat=[[at(10),1.1000],[at(12,30),1.1000]];
 for(const seed of [1,2,3,4,5]){
  const L=run({...RD,Random_Seed:seed},flat),O=run({...RD,Random_Seed:seed,BRK_Once_Per_Level:false},flat);
  const hours=W=>sends(W).map(x=>new Date(x.time*1000).toISOString().slice(11,13)).join(',');
  if(hours(L)!=='10') P.push('Random_Direction seed '+seed+': entries at '+hours(L)+', wanted 10 only');
  if(hours(O)!=='10,12') P.push('Random_Direction seed '+seed+', latch off: entries at '+hours(O)+', wanted 10,12');
 }
 return {P,W};
}

// 3. OnInit's rebuild from deal history.
function rebuild(files,W){
 const P=[],c=W.ctx,day=T(2026,10,6);
 const deal=(time,type,magic=c.MAGIC1)=>{const t=++W.w.nextDeal;W.w.deals.push({ticket:t,order:0,position:t,symbol:W.w.symbol,magic,type,entry:0,volume:0.1,price:1.1,
  profit:0,commission:0,swap:0,fee:0,time,time_msc:time*1000,reason:3,comment:''});};
 W.w.time=at(12,30);c.GoatBrkLatchRebuild();
 if(c.g_GoatBrkLatchDay[OP.BUY]!==day||c.g_GoatBrkLatchDay[OP.SELL]!==0) P.push('rebuild: the 10:00 buy latches the buy signal ('+[...c.g_GoatBrkLatchDay]+')');
 W.setInput('Reverse_Seq',true);c.GoatBrkLatchRebuild();
 if(c.g_GoatBrkLatchDay[OP.SELL]!==day||c.g_GoatBrkLatchDay[OP.BUY]!==0) P.push('rebuild under Reverse_Seq: the buy position was a sell signal ('+[...c.g_GoatBrkLatchDay]+')');
 W.setInput('Reverse_Seq',false);
 // Wednesday 00:30: s is Tuesday's 23:00 bar. A sell entered at 00:00:10 came from that bar (Tuesday's); another magic's
 // buy is ignored; the 10:00 buy is Tuesday's too.
 deal(T(2026,10,7,0,0,10),1);deal(T(2026,10,7,0,0,20),0,c.MAGIC1+1);
 W.w.time=T(2026,10,7,0,30);c.GoatBrkLatchRebuild();
 if(c.g_GoatBrkLatchDay[OP.SELL]!==day||c.g_GoatBrkLatchDay[OP.BUY]!==day) P.push('rebuild after midnight: both of Tuesday\'s entries ('+[...c.g_GoatBrkLatchDay]+')');
 W.w.time=T(2026,10,7,2,30);c.GoatBrkLatchRebuild();
 if(c.g_GoatBrkLatchDay[OP.SELL]!==0||c.g_GoatBrkLatchDay[OP.BUY]!==0) P.push('rebuild on Wednesday 02:30: nothing of Wednesday\'s day ('+[...c.g_GoatBrkLatchDay]+')');
 const select=c.HistorySelect;c.HistorySelect=()=>false;c.GoatBrkLatchRebuild();c.HistorySelect=select;
 if(!c.g_GoatBrkLatchUnread) P.push('rebuild: an unreadable history is noted');
 W.w.time=T(2026,10,6,10,30,30);c.GoatBrkSignal(1);
 if(c.g_GoatBrkLatchDay[OP.BUY]!==day||c.g_GoatBrkLatchDay[OP.SELL]!==day||c.g_GoatBrkLatchUnread) P.push('rebuild: an unreadable history latches the first day read both ways ('+[...c.g_GoatBrkLatchDay]+')');
 return P;
}

const all=files=>{const t=ticks(files);return [...signal(files),...t.P,...rebuild(files,t.W)];};
const problems=all(tree);
assert.deepEqual(problems,[],'entry A on the tree');

// 4. Mutants.
const mutate=(from,to)=>{const text=tree[H.MAIN];assert.equal(text.split(from).length-1,1,'mutant anchor '+JSON.stringify(from));return {...tree,[H.MAIN]:text.replace(from,to)};};
const MUTANTS=[
 ['the latch removed','return(BRK_Mode==BRK_PriorDay && BRK_Once_Per_Level && g_GoatBrkDay>0 && g_GoatBrkLatchDay[signal]==g_GoatBrkDay);','return(false);'],
 ['the latch keyed by position side','g_GoatBrkLatchDay[Reverse_Seq ? 1-side : side]=day;','g_GoatBrkLatchDay[side]=day;'],
 ['Close[0] read','double close_s=iClose(_Symbol,tf,s);','double close_s=iClose(_Symbol,tf,0);'],
 ['bar 1 inside the level','for(int i=s+1;i<=s+BRK_Bars;i++)','for(int i=s;i<s+BRK_Bars;i++)'],
 ['>= for >','if(close_s>up+buf) return OP_BUY;','if(close_s>=up+buf) return OP_BUY;'],
 ['the Sunday stub kept','if(dt.day_of_week>=1 && dt.day_of_week<=5) d=j;','d=j;'],
 ['D taken at evaluation time','int k=GoatBrkBarAt(PERIOD_D1,open_s);','int k=GoatBrkBarAt(PERIOD_D1,TimeCurrent());'],
 ['the ATR read at evaluation time','double atr=GoatBrkATR(open_s+PeriodSeconds(tf));','double atr=GoatBrkATR(TimeCurrent());'],
 ['the fresh cross dropped','if(close_s>pdh+buf && prev<=pdh+buf) return OP_BUY;','if(close_s>pdh+buf) return OP_BUY;'],
 ['GoatSignalAll without the sell term','            && ( BRK_Mode==BRK_Disabled  || BRK_Sig==OP_SELL)); // B54 (spec 5)','            ); // B54 (spec 5)'],
];
const caught=[];
for(const [label,from,to] of MUTANTS){const found=all(mutate(from,to));assert.ok(found.length>0,'mutant "'+label+'" is caught');caught.push(label+': '+found[0]);}
console.log(JSON.stringify({test:'b54_breakout',passed:true,mutants:caught}));
