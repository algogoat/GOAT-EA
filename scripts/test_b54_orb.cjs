// B54 PR B (docs/b54/BREAKOUT_ENTRIES_SPEC.md 4.2-4.5, 6.3): entry B, the session opening-range breakout, through
// scripts/b50_tick_harness.cjs (the real UpdateCurrentSignals, SignalEntryTrigger, GoatTickBody and OnInit's slices).
// 1. The clock: GoatOrbAnchor (GoatNYTime and GoatLondonTime of GOAT_NYClock.mqh) against an independent reference of the
//    US and EU rules (in force since 2007), for every year 2007-2035, under all three server models and both anchors, on
//    the weekdays around each DST change (so the March and October mismatch weeks) and in mid-winter and mid-summer. The
//    reference's own dates are pinned to the published ones for 2007, 2026 and 2035.
// 2. The signal (GoatOrbSignal on closed trigger bar s = 1), New York anchor on an NYClose server (09:30-10:00 NY is
//    16:30-17:00 server): the range is the M1 bars opening in [S, S+R), so the S bar is in and the S+R bar out; a fresh
//    cross of H or L, strictly; no evaluation and no range read before S+R; the buffer's ATR and atr_r found by time, so a
//    restart mid-session with ATR moving keeps the day's B8/B9 verdict; the entry window's end (ORB_Entry_Minutes, else
//    17:00 NY, and 16:55 NY on a Friday); no session on a weekend trade date; the M1-count rule (ceil(R/2) bars); unreadable
//    data gives OP_NULL, logged once, and an unreadable range is read again on the next bar.
// 3. Clocks in use: the New York anchor on a Fixed server either side of the US change; the London anchor's 08:00 window on
//    Fixed and EU DST servers in the March and October mismatch weeks and in summer; under the London anchor the entry
//    window still ends at 17:00 NY, in both DST states.
// 4. OnInit: the evidence line (spec 4.4); Lim in both DST states (1020 New York, 1260 London). The other refusals
//    (alignment, pre-2007 test starts, the live chart) are scripts/test_b54_init.cjs's.
// 5. Ticks: one single per signal direction per trade date T (ruling 11). After the up-cross's buy is stopped out, a second
//    up-cross the same T opens nothing, the down-cross opens a sell, and the next T's up-cross opens a buy. Under Reverse_Seq
//    the up-cross opens a sell, the second up-cross is latched and the down-cross opens a buy (the latch is the signal's).
//    Random_Direction, seeds 1-3: the latched up-cross opens nothing whichever side was drawn. The opposite exit is the
//    opposite break. FastSpeed true and false trade alike.
// 6. OnInit's rebuild of the T latch from deal history: flipped under Reverse_Seq, another magic ignored, the next T clean,
//    and an unreadable history latches the first T read both ways.
// 7. Load-bearing: the spec's mutants (6.3: atr_r read at evaluation time, London from the US rule, New York time from raw
//    server time, the first Sunday in place of the second, Lim = 1320, the range built from ticks, S+R included in the
//    range) plus the S bar left out, the latch removed, the latch keyed by position side, the Friday cutoff dropped, 17:00
//    NY read on the anchor's clock, the M1-count rule dropped, a weekend trade date traded, GoatSignalAll without entry B's
//    term, the buffer's ATR read at evaluation time, the fresh cross dropped, an unreadable range held as a no-ORB day, and
//    the trigger bar evaluated before S+R. Each must be caught.
// What it does not prove: compile cleanliness (MetaEditor), MT5's own CopyRates and bar history, or the native tester.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const K=H.API_CONSTANTS,MIN=60,HR=3600,DAY=86400;
const T=(y,m,d,h=0,mi=0,s=0)=>Date.UTC(y,m-1,d,h,mi,s)/1000;
const SEC={[K.PERIOD_M1]:60,[K.PERIOD_M5]:300,[K.PERIOD_M15]:900,[K.PERIOD_M30]:1800,[K.PERIOD_H1]:3600,[K.PERIOD_H4]:14400,[K.PERIOD_D1]:86400};
const bar=(open,high,low,close)=>({open,high,low,close});
const FLAT=bar(1.1,1.1,1.1,1.1);
// bars: {seconds per bar: {open time: bar}}; every other bar is flat at 1.1000.
const seriesOf=bars=>(tf,shift,barTime)=>((bars[SEC[tf]]||{})[barTime])||FLAT;
const CLOCK='GOAT_NYClock.mqh';
const tree=H.loadSources();
const OP=(()=>{const m=H.compile(tree).macros;return {BUY:Number(m.get('OP_BUY').body),SELL:Number(m.get('OP_SELL').body),NULL:Number(m.get('OP_NULL').body)};})();
const name=v=>v===OP.BUY?'BUY':v===OP.SELL?'SELL':v===OP.NULL?'NULL':String(v);
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',RSI_Mode:'RSI_Disabled',Mode_Bias:'Bias_Disabled',
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,ORB_Mode:'ORB_Breakout',ORB_TF_:'TF_M5',ORB_Start_Minute:570,ORB_Range_Minutes:30,
 Server_Clock_Model:'ServerClock_NYClose',Server_UTC_Offset:2};
function world(files,{inputs={},at,m1={},m5={},atr=()=>0.0010,fastSpeed=true,w={}}={}){
 return H.build({files},{tester:true,fastSpeed,start:at,inputs:{...BASE,...inputs},series:seriesOf({60:m1,300:m5}),
  indicator:(n,buffer,shift,ww)=>n==='ATR_MA'?atr(shift,ww):undefined,world:w});
}
// The M1 bars of a 30-minute range opening at server time s0: H 1.1020 on the S bar, L 1.0980 at S+15, every other bar of
// W 1.1005 / 1.0995. The bar before S and the S+R bar reach further, and lie outside W.
function rangeBars(s0){
 const b={[s0-MIN]:bar(1.1,1.1040,1.0960,1.1)};
 for(let k=0;k<30;k++) b[s0+k*MIN]=bar(1.1,1.1005,1.0995,1.1);
 b[s0]=bar(1.1,1.1020,1.0995,1.1);b[s0+15*MIN]=bar(1.1,1.1005,1.0980,1.1);b[s0+30*MIN]=bar(1.1,1.1050,1.0950,1.1);
 return b;
}
// An M5 trigger bar opening at t, closing at close, after a bar closing at prev.
const cross=(t,prev,close)=>({[t-300]:bar(prev,prev,prev,prev),[t]:bar(prev,Math.max(prev,close),Math.min(prev,close),close)});

// 1. The clock, against an independent reference (JS dates, the published rules).
const nthSunday=(y,m,n)=>1+(7-new Date(Date.UTC(y,m-1,1)).getUTCDay())%7+7*(n-1);
const lastSunday=(y,m)=>{const last=new Date(Date.UTC(y,m,0));return last.getUTCDate()-last.getUTCDay();};
const US=y=>[T(y,3,nthSunday(y,3,2),7),T(y,11,nthSunday(y,11,1),6)],EU=y=>[T(y,3,lastSunday(y,3),1),T(y,10,lastSunday(y,10),1)];
const yearOf=u=>new Date(u*1000).getUTCFullYear();
const usDST=u=>{const [a,b]=US(yearOf(u));return u>=a&&u<b;},euDST=u=>{const [a,b]=EU(yearOf(u));return u>=a&&u<b;};
const nyOf=u=>u-(usDST(u)?4:5)*HR,londonOf=u=>u+(euDST(u)?HR:0);
// The server time of UTC u under each model: 0 NYClose (New York + 7 h), 1 Fixed (UTC + offset), 2 EU DST (+1 h in EU DST).
const serverOf=(u,model,offset)=>model===0?nyOf(u)+7*HR:model===1?u+offset*HR:u+offset*HR+(euDST(u)?HR:0);
function clock(files){
 const P=[];
 const day=t=>new Date(t*1000).toISOString().slice(5,10);
 for(const [y,want] of [[2007,'03-11 11-04 03-25 10-28'],[2026,'03-08 11-01 03-29 10-25'],[2035,'03-11 11-04 03-25 10-28']]){
  const got=[...US(y),...EU(y)].map(day).join(' ');if(got!==want) P.push('reference '+y+': '+got+', published '+want);}
 const days=new Set();
 for(let y=2007;y<=2035;y++) for(const mark of [T(y,1,15),T(y,7,15),...US(y),...EU(y)]) for(let d=-8;d<=8;d++){
  const t=Math.floor(mark/DAY)*DAY+d*DAY,wd=new Date(t*1000).getUTCDay();if(wd>=1&&wd<=5) days.add(t);}
 const W=world(files,{at:T(2026,10,6,12)}),c=W.ctx;let checks=0;
 for(const model of [0,1,2]) for(const anchor of [0,1]){
  W.setInput('Server_Clock_Model',model);W.setInput('Server_UTC_Offset',2);W.setInput('ORB_Clock',anchor);
  const bad=[];
  for(const t of days) for(const h of [3,12,21]){
   const u=t+h*HR,server=serverOf(u,model,2),got=c.GoatOrbAnchor(server),want=anchor?londonOf(u):nyOf(u);checks++;
   if(got!==want) bad.push(new Date(u*1000).toISOString().slice(0,16)+'Z: '+(got-want)/HR+' h');
  }
  if(bad.length) P.push('clock: model '+model+', '+(anchor?'London':'New York')+' anchor: '+bad.length+' wrong ('+bad.slice(0,3).join('; ')+')');
 }
 return {P,checks};
}

// 2. The signal: New York anchor, NYClose server, Tuesday 2026-10-06; S = 570 (09:30 NY = 16:30 server), R = 30.
function signal(files){
 const P=[],expect=(what,got,want)=>{if(got!==want)P.push(what+': '+name(got)+', wanted '+name(want));};
 const tue=(h,m=0)=>T(2026,10,6,h,m),S0=tue(16,30),M1=rangeBars(S0);
 // The trigger bar opens at t (default 17:00, 10:00 NY, the first bar after S+R) and the check runs 7.5 min later, so the
 // newest closed M1 bar then is 17:06 while the one closed at bar s's close (17:05) is 17:04.
 const sigW=(close,{prev=1.1000,t=tue(17),at=t+450,m1=M1,...o}={})=>{const W=world(files,{at,m1,m5:cross(t,prev,close),...o});return {v:W.ctx.GoatOrbSignal(1),W};};
 const sig=(close,o)=>sigW(close,o).v;
 expect('up-cross of H',sig(1.1025),OP.BUY);
 expect('a close at H is no break',sig(1.1020),OP.NULL);
 expect('below H (the S bar\'s high is in the range)',sig(1.1015),OP.NULL);
 expect('down-cross of L',sig(1.0975),OP.SELL);
 expect('a close at L is no break',sig(1.0980),OP.NULL);
 expect('no fresh cross',sig(1.1030,{prev:1.1022}),OP.NULL);
 {const {v,W}=sigW(1.1025,{t:tue(16,55)});
  expect('before S+R (bar s opens 09:55 NY)',v,OP.NULL);
  if(W.ctx.g_GoatOrbRangeDay!==0) P.push('before S+R: the range was read ('+W.ctx.g_GoatOrbRangeDay+')');}
 {const {W}=sigW(1.1025);
  if(W.ctx.g_GoatOrbDay!==T(2026,10,6)||W.ctx.g_GoatOrbHigh!==1.1020||W.ctx.g_GoatOrbLow!==1.0980) P.push('the range: T '+W.ctx.g_GoatOrbDay+', H '+W.ctx.g_GoatOrbHigh+', L '+W.ctx.g_GoatOrbLow+', wanted Tuesday, 1.1020, 1.0980');}
 // The buffer: 1.0 x the ATR of the M1 bar closed at bar s's close (shift 3 at 17:07:30), 0.0010; every other bar 0.05.
 const byTime=shift=>shift===3?0.0010:0.0500;
 expect('inside the 1.0 x ATR buffer',sig(1.1029,{inputs:{ORB_Buffer_ATR:1.0},atr:byTime}),OP.NULL);
 expect('past the 1.0 x ATR buffer (ATR found by time)',sig(1.1031,{inputs:{ORB_Buffer_ATR:1.0},atr:byTime}),OP.BUY);
 // The entry window: ORB_Entry_Minutes=30 ends at 10:30 NY (17:30 server); 0 runs to 17:00 NY (00:00 server).
 expect('E: the last bar closing by S+R+30',sig(1.1025,{t:tue(17,25),inputs:{ORB_Entry_Minutes:30}}),OP.BUY);
 expect('E: a bar closing after S+R+30',sig(1.1025,{t:tue(17,30),inputs:{ORB_Entry_Minutes:30}}),OP.NULL);
 expect('E: ORB_Entry_Minutes=0 runs on',sig(1.1025,{t:tue(17,30)}),OP.BUY);
 expect('E: the last bar closing by 17:00 NY',sig(1.1025,{t:tue(23,55)}),OP.BUY);
 expect('E: the bar opening at 17:00 NY (still Tuesday\'s T)',sig(1.1025,{t:T(2026,10,7,0,0)}),OP.NULL);
 // Friday 10-09: E ends at 16:55 NY (23:55 server).
 const FRI=rangeBars(T(2026,10,9,16,30));
 expect('Friday: the last bar closing by 16:55 NY',sig(1.1025,{t:T(2026,10,9,23,50),m1:FRI}),OP.BUY);
 expect('Friday: the bar closing at 17:00 NY',sig(1.1025,{t:T(2026,10,9,23,55),m1:FRI}),OP.NULL);
 // Saturday 10-10 has no session, whatever its bars.
 expect('a weekend trade date',sig(1.1025,{t:T(2026,10,10,17),m1:rangeBars(T(2026,10,10,16,30))}),OP.NULL);
 // The M1-count rule: R = 30 needs 15 bars. Bars S+1.. are missing (a short day).
 const drop=n=>({missingRates:(tf,t)=>tf===K.PERIOD_M1&&t>S0&&t<=S0+n*MIN});
 {const {v,W}=sigW(1.1025,{w:drop(16)});W.ctx.GoatOrbSignal(1);
  expect('14 of 30 M1 bars: no ORB that day',v,OP.NULL);
  const n=W.w.logs.filter(l=>/GOAT signals: ORB no trade on 2026\.10\.06: only 14 of 30 M1 bars/.test(l)).length;if(n!==1) P.push('the short range logged '+n+' times, wanted once');}
 expect('15 of 30 M1 bars: an ORB',sig(1.1025,{w:drop(15)}),OP.BUY);
 // B8/B9: the range is 0.0040. ATR moves: 0.0010 on the bars closed by 17:00 (t* = S+R), 0.0100 after.
 const moving=(shift,w)=>(Math.floor(w.time/MIN)*MIN-shift*MIN<=tue(16,59)?0.0010:0.0100);
 const rf=(inputs,o={})=>sig(1.1025,{inputs,atr:moving,...o});
 expect('B8: 4 ATR >= ORB_Min_Range_ATR 3',rf({ORB_Min_Range_ATR:3}),OP.BUY);
 expect('B8: 4 ATR < ORB_Min_Range_ATR 5',rf({ORB_Min_Range_ATR:5}),OP.NULL);
 expect('B9: 4 ATR <= ORB_Max_Range_ATR 5',rf({ORB_Max_Range_ATR:5}),OP.BUY);
 expect('B9: 4 ATR > ORB_Max_Range_ATR 3',rf({ORB_Max_Range_ATR:3}),OP.NULL);
 // A restart at 19:00:30, the ATR ten times larger by then: the day's verdict is still read at t*.
 expect('B8 after a restart mid-session (atr_r found by time)',rf({ORB_Min_Range_ATR:3},{t:tue(18,55),at:tue(19,0)+30}),OP.BUY);
 // Unreadable data.
 {const {v,W}=sigW(1.1025,{w:{rejectRates:()=>true}});W.ctx.GoatOrbSignal(1);
  expect('M1 range unreadable',v,OP.NULL);
  const n=W.w.logs.filter(l=>/GOAT signals: ORB M1 range unreadable/.test(l)).length;if(n!==1) P.push('M1 range unreadable logged '+n+' times, wanted once');
  W.w.rejectRates=null;expect('the range is read again once it reads',W.ctx.GoatOrbSignal(1),OP.BUY);}
 expect('ATR unreadable',sig(1.1025,{atr:()=>undefined}),OP.NULL);
 return P;
}

// 3. Clocks in use. Each window's range bars sit at the server times the clock gives; a close of 1.1015 is inside them, and
// a window read an hour off sees flat bars (H = L = 1.1000), so it would break there.
function clocks(files){
 const P=[];
 const at=(label,inputs,s0,t,want1025,want1015=OP.NULL)=>{
  for(const [close,want] of [[1.1025,want1025],[1.1015,want1015]]){
   const W=world(files,{inputs,at:t+450,m1:rangeBars(s0),m5:cross(t,1.1,close)});const got=W.ctx.GoatOrbSignal(1);
   if(got!==want) P.push(label+', close '+close+': '+name(got)+', wanted '+name(want));}
 };
 const FIXED={Server_Clock_Model:'ServerClock_Fixed',Server_UTC_Offset:2},EUDST={Server_Clock_Model:'ServerClock_EUDST',Server_UTC_Offset:2};
 // New York 09:30 on a Fixed UTC+2 server: 13:30 UTC (EDT) before the US change of 2026-11-01, 14:30 UTC (EST) after it.
 at('New York anchor, Fixed, 10-27 (EDT)',FIXED,T(2026,10,27,15,30),T(2026,10,27,16),OP.BUY);
 at('New York anchor, Fixed, 11-03 (EST)',FIXED,T(2026,11,3,16,30),T(2026,11,3,17),OP.BUY);
 // London 08:00 (S = 480): GMT in the mismatch weeks (US on DST, the EU not), BST in summer.
 const LON={ORB_Clock:'ORB_Clock_London',ORB_Start_Minute:480};
 at('London anchor, Fixed, 03-10 (mismatch week)',{...FIXED,...LON},T(2026,3,10,10),T(2026,3,10,10,30),OP.BUY);
 at('London anchor, Fixed, 10-27 (mismatch week)',{...FIXED,...LON},T(2026,10,27,10),T(2026,10,27,10,30),OP.BUY);
 at('London anchor, Fixed, 07-07 (BST)',{...FIXED,...LON},T(2026,7,7,9),T(2026,7,7,9,30),OP.BUY);
 at('London anchor, EU DST, 03-10 (mismatch week)',{...EUDST,...LON},T(2026,3,10,10),T(2026,3,10,10,30),OP.BUY);
 at('London anchor, EU DST, 07-07 (BST)',{...EUDST,...LON},T(2026,7,7,10),T(2026,7,7,10,30),OP.BUY);
 // Under the London anchor, ORB_Entry_Minutes=0 still ends E at 17:00 NY (23:00 server, Fixed UTC+2): 21:00 London in the
 // mismatch week, 22:00 London in summer. S = 1140 (19:00 London).
 const EVE={...FIXED,ORB_Clock:'ORB_Clock_London',ORB_Start_Minute:1140};
 for(const [label,s0,d] of [['03-10, 17:00 NY = 21:00 London',T(2026,3,10,21),[2026,3,10]],['07-07, 17:00 NY = 22:00 London',T(2026,7,7,20),[2026,7,7]]]){
  at('London anchor, '+label+': the last bar closing by 17:00 NY',EVE,s0,T(...d,22,55),OP.BUY);
  at('London anchor, '+label+': the bar opening at 17:00 NY',EVE,s0,T(...d,23,0),OP.NULL);
 }
 return P;
}

// 4. OnInit: the evidence line, and Lim in both DST states.
function init(files){
 const P=[];
 const result=(inputs,start)=>{const alerts=[];try{const W=H.build({files},{tester:true,inputs:{...BASE,...inputs},indicator:()=>undefined,start,world:{alerts}});return {ok:true,W};}
  catch(e){if(e.initCode===undefined)throw e;return {ok:false,alert:alerts.at(-1)};}};
 {const r=result({},T(2026,10,6,12));
  if(!r.ok||!r.W.w.logs.some(l=>/^GOAT signals: ORB clock: the tester trusts Server_Clock_Model=0, Server_UTC_Offset=2, ORB_Clock=0 /.test(l))) P.push('OnInit logs the ORB clock line');}
 const WINDOW='Initialization Failed: ORB_Entry_Minutes must be between 0 and Lim, and the entry window must end by Lim (ORB_Start_Minute+ORB_Range_Minutes+ORB_Entry_Minutes <= Lim).';
 for(const start of [T(2026,1,13,12),T(2026,7,7,12)]){
  const d=new Date(start*1000).toISOString().slice(0,10);
  for(const [label,inputs,lim] of [['New York',{},1020],['London',{ORB_Clock:'ORB_Clock_London'},1260]]){
   const at=e=>result({...inputs,ORB_Start_Minute:lim-10,ORB_Range_Minutes:5,ORB_Entry_Minutes:e},start);
   if(!at(5).ok) P.push(label+' Lim, '+d+': S+R+E = '+lim+' is refused ('+at(5).alert+')');
   if(at(6).ok||at(6).alert!==WINDOW) P.push(label+' Lim, '+d+': S+R+E = '+(lim+1)+' is accepted');
  }
 }
 return P;
}

// 5. Ticks, New York anchor, NYClose server. Each day's M5 closes: 16:55 1.1000, 17:00 1.1025 (an up-cross), 17:05 and
// 17:10 1.1010 (inside), 17:15 1.1030 (a second up-cross), 17:20 1.0990, 17:25 1.0970 (a down-cross); the rest flat.
function path(points,step=20){   // a tick every step s (7 s past), linear between [time, bid] points
 const ticks=[];
 for(let k=1;k<points.length;k++){const [t0,p0]=points[k-1],[t1,p1]=points[k];for(let t=t0;t<t1;t+=step) ticks.push([t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);}
 return ticks;
}
const tue=(h,m=0)=>T(2026,10,6,h,m),wed=(h,m=0)=>T(2026,10,7,h,m);
const dayBars=d=>({[d(16,55)]:bar(1.1,1.1,1.1,1.1000),[d(17)]:bar(1.1,1.1025,1.1,1.1025),[d(17,5)]:bar(1.1025,1.1025,1.101,1.1010),
 [d(17,10)]:bar(1.101,1.101,1.101,1.1010),[d(17,15)]:bar(1.101,1.103,1.101,1.1030),[d(17,20)]:bar(1.103,1.103,1.099,1.0990),
 [d(17,25)]:bar(1.099,1.099,1.097,1.0970)});
const TICK_M1={...rangeBars(tue(16,30)),...rangeBars(wed(16,30))},TICK_M5={...dayBars(tue),...dayBars(wed)};
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');
const stamp=t=>new Date(t*1000).toISOString().slice(8,16).replace('T',' ');
const kinds=W=>sends(W).map(x=>(x.type===0?'buy':'sell')+'@'+stamp(x.time)).join(',');
function ticks(files){
 const P=[];
 const run=(inputs,points,fastSpeed=true)=>{const W=world(files,{inputs,at:tue(16,59),m1:TICK_M1,m5:TICK_M5,fastSpeed});W.run(points);return W;};
 // The buy from the 17:00 up-cross is stopped out by 17:10 (SL 1.5 x 0.0010); a 60-bar time stop closes the 17:30 sell.
 const DOWN=[...path([[tue(17),1.1000],[tue(17,5),1.1000],[tue(17,8),1.1000],[tue(17,12),1.0970],[tue(17,45),1.0990]]),
  ...path([[tue(17,45),1.0990],[wed(16,59),1.1000]],600),...path([[wed(16,59),1.1000],[wed(17,10),1.1000]])];
 const STOP={Single_Time_Stop_Bars:60,Single_Time_Stop_TF:'TF_Cur'};
 const W=run(STOP,DOWN);
 if(kinds(W)!=='buy@06 17:05,sell@06 17:30,buy@07 17:05') P.push('one single per direction per T: orders '+kinds(W)+', wanted buy@06 17:05,sell@06 17:30,buy@07 17:05');
 // Reverse_Seq: the up-cross opens a sell (stopped out as the price rises), the second up-cross is latched, the down-cross
 // opens a buy.
 const UP=path([[tue(17),1.1000],[tue(17,5),1.1000],[tue(17,8),1.1000],[tue(17,12),1.1030],[tue(17,45),1.1010]]);
 const R=run({Reverse_Seq:true},UP);
 if(kinds(R)!=='sell@06 17:05,buy@06 17:30') P.push('Reverse_Seq: orders '+kinds(R)+', wanted sell@06 17:05,buy@06 17:30');
 // FastSpeed both ways: the same orders, prices, stops, closes and times (only the order comment differs, as on B53).
 const bare=X=>JSON.stringify(X.w.trace.map(({comment,...x})=>x));
 for(const [label,inputs,points] of [['plain',STOP,DOWN],['Reverse_Seq',{Reverse_Seq:true},UP]])
  if(bare(run(inputs,points,true))!==bare(run(inputs,points,false))) P.push('FastSpeed true and false trade alike ('+label+')');
 // The opposite exit is the opposite break (spec 5): on a flat path the 17:05 buy is closed at 17:30 by the 17:25 down-cross.
 const FLATP=path([[tue(17),1.1000],[tue(17,45),1.1000]]);
 const E=run({Single_Exit_Opposite:true},FLATP);
 const closes=E.w.trace.filter(x=>/^(PositionClose|BrokerStop|BrokerTake)$/.test(x.op)).map(x=>stamp(x.time));
 if(kinds(E)!=='buy@06 17:05,sell@06 17:30'||closes[0]!=='06 17:30') P.push('opposite exit: orders '+kinds(E)+', first close at '+closes[0]+', wanted buy@06 17:05,sell@06 17:30 and a 17:30 close');
 // Random_Direction (spec 3.5 item 4, 4.5): a 10-bar time stop frees the first single by 17:15, and the latched 17:15
 // up-cross opens nothing, whichever side the first draw took; the down-cross is its own episode.
 for(const seed of [1,2,3]){
  const D=run({Random_Direction:true,Single_Flat_Only:true,Single_Time_Stop_Bars:10,Single_Time_Stop_TF:'TF_Cur',Random_Seed:seed},FLATP);
  const at=sends(D).map(x=>stamp(x.time)).join(',');
  if(at!=='06 17:05,06 17:30') P.push('Random_Direction seed '+seed+': entries at '+at+', wanted 06 17:05,06 17:30');
 }
 return {P,W};
}

// 6. OnInit's rebuild of the T latch from deal history (the ticks world: a buy at Tue 17:05, a sell at 17:30, a buy Wed 17:05).
function rebuild(files,W){
 const P=[],c=W.ctx,TUE=T(2026,10,6),WED=T(2026,10,7);
 const latch=()=>[...c.g_GoatOrbLatchDay].join(',');
 const at=(t,want,label)=>{W.w.time=t;c.GoatOrbLatchRebuild();if(latch()!==want) P.push('rebuild '+label+': '+latch()+', wanted '+want);};
 at(tue(17,27),TUE+',0','at 17:27: the 17:05 buy latches the buy signal');
 if(c.g_GoatOrbDay!==TUE) P.push('rebuild: T is '+c.g_GoatOrbDay+', wanted Tuesday');
 W.setInput('Reverse_Seq',true);at(tue(17,27),'0,'+TUE,'under Reverse_Seq: the buy position was a sell signal');W.setInput('Reverse_Seq',false);
 const t=++W.w.nextDeal;W.w.deals.push({ticket:t,order:0,position:t,symbol:W.w.symbol,magic:c.MAGIC1+1,type:1,entry:0,volume:0.1,price:1.1,
  profit:0,commission:0,swap:0,fee:0,time:tue(17,21),time_msc:tue(17,21)*1000,reason:3,comment:''});
 at(tue(17,27),TUE+',0','another magic\'s sell is ignored');
 at(tue(17,40),TUE+','+TUE,'at 17:40: both of Tuesday\'s entries');
 at(wed(17,2),'0,0','Wednesday before its entry');
 at(wed(17,20),WED+',0','Wednesday after its buy');
 const select=c.HistorySelect;c.HistorySelect=()=>false;W.w.time=wed(17,20);c.GoatOrbLatchRebuild();c.HistorySelect=select;
 if(!c.g_GoatOrbLatchUnread) P.push('rebuild: an unreadable history is noted');
 c.GoatOrbSignal(1);
 if(latch()!==WED+','+WED||c.g_GoatOrbLatchUnread) P.push('rebuild: an unreadable history latches the first T read both ways ('+latch()+')');
 return P;
}

let clockChecks=0;
const all=files=>{const k=clock(files);clockChecks=k.checks;const t=ticks(files);return [...k.P,...signal(files),...clocks(files),...init(files),...t.P,...rebuild(files,t.W)];};
const problems=all(tree);
assert.deepEqual(problems,[],'entry B on the tree');

// 7. Mutants: [label, [[file, from, to, count?], ...], must?]; must (a pattern) names a problem the mutant has to raise.
const mutate=pairs=>{const out={...tree};
 for(const [file,from,to,count=1] of pairs){assert.equal(out[file].split(from).length-1,count,'mutant anchor '+JSON.stringify(from));out[file]=out[file].split(from).join(to);}
 return out;};
const M=H.MAIN;
const MUTANTS=[
 ['atr_r read at evaluation time',[[M,'double atr_r=(t_star>0 ? GoatBrkATR(t_star) : 0.0);','double atr_r=GoatBrkATR(TimeCurrent());']],/^B8 after a restart mid-session/],
 ['London from the US rule',[[CLOCK,'if(GoatNYEUDST(utc)) return utc+3600;','if(GoatNYUSDST(utc)) return utc+3600;']],/London anchor/],
 ['New York time from raw server time',[[M,'   return GoatNYTime(server_time);','   return server_time;']],/New York anchor/],
 ['the first Sunday in place of the second',[[CLOCK,'return GoatNYDate(year,3,GoatNYNthSunday(year,3,2))+7*3600;','return GoatNYDate(year,3,GoatNYNthSunday(year,3,1))+7*3600;']],/^clock: model 1, New York anchor/],
 ['Lim = 1320',[[M,'? 1260 : 1020','? 1320 : 1020',4]],/^London Lim/],
 ['the range built from ticks',[[M,'int      ORB_Sig=OP_NULL;','int      ORB_Sig=OP_NULL;\ndatetime g_MutTickDay=0;\ndouble   g_MutTickH=0.0,g_MutTickL=0.0;'],
  [M,'    if(ORB_Sample.CheckTF(TF2TF(ORB_TF_))) ORB_Sig=GoatOrbSignal(shift);','    {double tb=SymbolInfoDouble(_Symbol,SYMBOL_BID); datetime ta=GoatOrbAnchor(TimeCurrent()); datetime td=(datetime)(ta-ta%86400);\n'+
   '     if(ta>=td+ORB_Start_Minute*60 && ta<td+(ORB_Start_Minute+ORB_Range_Minutes)*60) {if(g_MutTickDay!=td) {g_MutTickDay=td; g_MutTickH=tb; g_MutTickL=tb;} if(tb>g_MutTickH) g_MutTickH=tb; if(tb<g_MutTickL) g_MutTickL=tb;}}\n'+
   '    if(ORB_Sample.CheckTF(TF2TF(ORB_TF_))) ORB_Sig=GoatOrbSignal(shift);'],
  [M,'g_GoatOrbRangeDay=day; g_GoatOrbRangeOk=ok; g_GoatOrbHigh=hi; g_GoatOrbLow=lo;','g_GoatOrbRangeDay=day; g_GoatOrbRangeOk=ok; g_GoatOrbHigh=(g_MutTickDay==day ? g_MutTickH : 0.0); g_GoatOrbLow=(g_MutTickDay==day ? g_MutTickL : 0.0);']],
  /^one single per direction per T/],
 ['S+R included in the range',[[M,'if(r[i].time<w0 || r[i].time>=w1) continue;','if(r[i].time<w0 || r[i].time>w1) continue;'],[M,'datetime w_last=(datetime)(w1-1);','datetime w_last=w1;']],/^up-cross of H/],
 ['the S bar left out',[[M,'if(r[i].time<w0 ||','if(r[i].time<=w0 ||']],/^below H/],
 ['the latch removed',[[M,'return(ORB_Mode==ORB_Breakout && g_GoatOrbDay>0 && g_GoatOrbLatchDay[signal]==g_GoatOrbDay);','return(false);']],/^one single per direction per T/],
 ['the latch keyed by position side',[[M,'g_GoatOrbLatchDay[Reverse_Seq ? 1-side : side]=day;','g_GoatOrbLatchDay[side]=day;']],/^rebuild under Reverse_Seq/],
 ['the Friday cutoff dropped',[[M,'if(dow==5 && e_end>','if(false && e_end>']],/^Friday: the bar closing at 17:00 NY/],
 ['17:00 NY read on the anchor\'s clock',[[M,'day+17*3600-off_ny','day+17*3600-off']],/^London anchor, 03-10, 17:00 NY = 21:00 London: the last bar/],
 ['the M1-count rule dropped',[[M,'bool ok=(2*m>=ORB_Range_Minutes);','bool ok=(m>0);']],/^14 of 30 M1 bars/],
 ['a weekend trade date traded',[[M,'if(dow<1 || dow>5) return OP_NULL;','if(dow<0) return OP_NULL;']],/^a weekend trade date/],
 ['GoatSignalAll without entry B\'s sell term',[[M,'            && ( ORB_Mode==ORB_Disabled  || ORB_Sig==OP_SELL)); // B54 (spec 5)','            ); // B54 (spec 5)']],/^opposite exit/],
 ['the buffer\'s ATR read at evaluation time',[[M,'double atr=GoatBrkATR(close_t);','double atr=GoatBrkATR(TimeCurrent());']],/^past the 1.0 x ATR buffer/],
 ['the fresh cross dropped',[[M,'if(close_s>g_GoatOrbHigh+buf && prev<=g_GoatOrbHigh+buf) return OP_BUY;','if(close_s>g_GoatOrbHigh+buf) return OP_BUY;']],/^no fresh cross/],
 ['an unreadable range held as a no-ORB day',[[M,'if(n<0) {GoatOrbNull("M1 range unreadable"); return false;}','if(n<0) n=0;']],/^the range is read again/],
 ['the trigger bar evaluated before S+R',[[M,'if(a<day+sr*60) return OP_NULL;','if(false) return OP_NULL;']],/^before S\+R/],
];
const caught=[];
for(const [label,pairs,must] of MUTANTS){
 const found=all(mutate(pairs));
 assert.ok(found.length>0,'mutant "'+label+'" is caught');
 if(must) assert.ok(found.some(m=>must.test(m)),'mutant "'+label+'" raises '+must+' ('+found.slice(0,6).join(' | ')+')');
 caught.push(label+': '+(must?found.find(m=>must.test(m)):found[0]));
}
console.log(JSON.stringify({test:'b54_orb',passed:true,clockChecks,mutants:caught}));
