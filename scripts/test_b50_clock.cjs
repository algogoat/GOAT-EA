// B50 A2: the New York clock (docs/b50/B50_ALPHA_DESIGN.md section 3; GOAT_NYClock.mqh). The real MQL5 of
// GOAT_NYClock.mqh runs converted by scripts/b50_tick_harness.cjs (A0), inside the tree's OnTick region, against the
// harness terminal (live: TimeGMT = server - serverOffset h; tester: TimeGMT = server).
// Expected:
// - DST: the US and EU transition instants of every year 2007-2035 against a fixed list (computed independently with
//   Python's calendar module, not with the code under test), with the instants on both sides;
// - the three server-clock models: the NYClose identity (NY = server - 7 h, and the derived UTC round-trips to it),
//   Fixed and EUDST against an independent model built from the fixed list, the US/EU shoulder weeks included;
// - the NY session: a plain and a midnight-crossing window, Mon-Fri NY dates keyed to the start date, Active/InActive
//   and Sequence_Pause_Close as the server block sets them (under Clock_NewYork A0's guard keeps the server session
//   block from running, so a shut server session neither forces InActive nor clears the pause), the NY weekday's
//   Sequence_New_Friday, the NY day-end and Friday actions;
// - the rollover window: symmetric around 17:00 NY to the second, under either clock, and it really blocks entries;
// - the live self-check: a clock fault blocks new entries live (with "CLOCK MISMATCH" on the panel, once a minute,
//   failing closed with no clock) but never in the tester;
// - Clock_Server with no rollover block: GoatNYClockApply changes nothing (every global, the log, the panel), and a
//   live run trades exactly as A0's stub (GoatNYClockApply with an empty body).
// Mutants (each must fail at least one expected check): first Sunday for second, offset 6, a midnight-crossing window
// treated as empty, the tester check inverted, EU/US DST mixed up (two places), and more below; one mutates A0's
// server-session guard in the entrypoint (the server block running under Clock_NewYork).
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const NYFILE='GOAT_NYClock.mqh';
const SRC=H.readSource(undefined,NYFILE),MAINSRC=H.readSource(undefined,H.MAIN);
// A0's stub (9584d7b), rebuilt from the tree so the test needs no history: GoatNYClockApply changes nothing.
const STUB=(()=>{const a=SRC.indexOf('void GoatNYClockApply(const int k)\n  {'),b=SRC.indexOf('\n  }\n#endif');
 assert.ok(a>0&&b>a,'GoatNYClockApply is the last function of '+NYFILE);return SRC.slice(0,a)+'void GoatNYClockApply(const int k)\n  {\n   return;'+SRC.slice(b);})();
const U=(y,m,d,h=0,mi=0,s=0)=>Date.UTC(y,m-1,d,h,mi,s)/1000;
const HOUR=3600,DAY=86400;

// [year, US start (2nd Sunday of March), US end (1st Sunday of November), EU start (last Sunday of March),
//  EU end (last Sunday of October)]: python3 calendar, see the commit message.
const DST=[[2007,11,4,25,28],[2008,9,2,30,26],[2009,8,1,29,25],[2010,14,7,28,31],[2011,13,6,27,30],[2012,11,4,25,28],
 [2013,10,3,31,27],[2014,9,2,30,26],[2015,8,1,29,25],[2016,13,6,27,30],[2017,12,5,26,29],[2018,11,4,25,28],[2019,10,3,31,27],
 [2020,8,1,29,25],[2021,14,7,28,31],[2022,13,6,27,30],[2023,12,5,26,29],[2024,10,3,31,27],[2025,9,2,30,26],[2026,8,1,29,25],
 [2027,14,7,28,31],[2028,12,5,26,29],[2029,11,4,25,28],[2030,10,3,31,27],[2031,9,2,30,26],[2032,14,7,28,31],[2033,13,6,27,30],
 [2034,12,5,26,29],[2035,11,4,25,28]];
const usStart=r=>U(r[0],3,r[1],7),usEnd=r=>U(r[0],11,r[2],6),euStart=r=>U(r[0],3,r[3],1),euEnd=r=>U(r[0],10,r[4],1);
const rowOf=utc=>DST.find(r=>r[0]===new Date(utc*1000).getUTCFullYear());
// The independent model (from the list): UTC -> NY, and server -> NY per clock model.
const usDst=utc=>{const r=rowOf(utc);return utc>=usStart(r)&&utc<usEnd(r);};
const euDst=utc=>{const r=rowOf(utc);return utc>=euStart(r)&&utc<euEnd(r);};
const nyOfUtc=utc=>utc-(usDst(utc)?4:5)*HOUR;
const transitions=DST.flatMap(r=>[usStart(r),usEnd(r),euStart(r),euEnd(r)]);
const nearTransition=(t,margin)=>transitions.some(x=>Math.abs(t-x)<margin);

const quiet={RSI_Mode:'RSI_Disabled',EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',Delay_Trade:0,Delay_Trade_Live:0};
const atr=(name)=>name==='ATR_MA'?0.0010:undefined;
const sourceWith=(text,file=NYFILE)=>({files:H.loadSources(undefined,{[file]:text})});
// A world over a source: tester (default) or live; serverOffset is the live terminal's real server offset (TimeGMT).
function world(source,{inputs={},tester=true,serverOffset=2,start}={}){
 const W=H.build(source,{tester,inputs:{...quiet,...inputs},indicator:atr,start,world:{serverOffset}});
 W.panel=[];const setEdit=W.ctx.SetEdit;W.ctx.SetEdit=(field,text,...rest)=>{W.panel.push(String(text));return setEdit(field,text,...rest);};
 W.apply=t=>{W.w.time=t;W.ctx.GoatNYClockApply(0);return W.ctx;};   // the call alone (as if the server block were off)
 return W;
}
// Ticks every 20 s between [t, bid] points (as test_b50_parity.cjs).
function path(start,points){const ticks=[];for(let k=1;k<points.length;k++){const [t0,p0]=points[k-1],[t1,p1]=points[k];
 for(let t=t0;t<t1;t+=20)ticks.push([start+t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);}return ticks;}
const snapshot=W=>{const o={};for(const g of W.C.globals){const v=W.ctx[g.name];if(v===null||typeof v!=='object'&&typeof v!=='function')o[g.name]=v;
 else if(Array.isArray(v))o[g.name]=JSON.stringify(v.map(x=>typeof x==='object'?null:x));}return o;};

// ---------------------------------------------------------------------------------------------------------------
// The expected checks. Each takes a source and reports failures (so a mutant is "killed" when any check fails).
const CHECKS={
 dst_dates_2007_2035(src,fail){
  const {ctx}=world(src);
  for(const r of DST){
   const y=r[0];
   const pairs=[['US start',ctx.GoatNYUSDSTStart(y),usStart(r)],['US end',ctx.GoatNYUSDSTEnd(y),usEnd(r)],
    ['EU start',ctx.GoatNYEUDSTStart(y),euStart(r)],['EU end',ctx.GoatNYEUDSTEnd(y),euEnd(r)]];
   for(const [what,got,want] of pairs) if(got!==want) fail(y+' '+what+': '+new Date(got*1000).toISOString()+' != '+new Date(want*1000).toISOString());
   for(const [fn,s,e] of [['GoatNYUSDST',usStart(r),usEnd(r)],['GoatNYEUDST',euStart(r),euEnd(r)]]){
    const exp=[[s-1,false],[s,true],[e-1,true],[e,false],[U(y,1,15,12),false],[U(y,7,15,12),true],[U(y,12,24,12),false]];
    for(const [t,v] of exp) if(ctx[fn](t)!==v) fail(fn+'('+new Date(t*1000).toISOString()+') should be '+v);
   }
  }
 },
 nyclose_identity(src,fail){
  const {ctx}=world(src,{inputs:{Server_Clock_Model:'ServerClock_NYClose'}});
  let n=0;
  for(let t=U(2007,1,2,0,13);t<U(2035,12,30);t+=5*HOUR+17*60+11){
   n++;
   if(ctx.GoatNYTime(t)!==t-7*HOUR){fail('NYClose: GoatNYTime('+t+') != server - 7 h');break;}
   const utc=ctx.GoatNYServerToUTC(t);
   if(!nearTransition(utc,3*HOUR)&&(utc!==t-7*HOUR+(usDst(utc)?4:5)*HOUR||ctx.GoatNYFromUTC(utc)!==t-7*HOUR)){fail('NYClose: the derived UTC of '+t+' does not round-trip');break;}
  }
  if(n<45000) fail('NYClose: too few samples '+n);
  // 17:00 NY is 00:00 server all year: the shoulder weeks too.
  for(const t of [U(2026,3,10,0),U(2026,3,30,0),U(2026,10,28,0),U(2026,11,2,0),U(2026,7,1,0),U(2026,1,5,0)]) if(new Date(ctx.GoatNYTime(t)*1000).getUTCHours()!==17) fail('NYClose: server 00:00 is not 17:00 NY');
 },
 fixed_and_eudst_models(src,fail){
  for(const off of [2,3,0,-5]){
   const fixed=world(src,{inputs:{Server_Clock_Model:'ServerClock_Fixed',Server_UTC_Offset:off}}).ctx;
   const eu=world(src,{inputs:{Server_Clock_Model:'ServerClock_EUDST',Server_UTC_Offset:off}}).ctx;
   let bad=0;
   for(let t=U(2007,1,2,0,7);t<U(2035,12,30)&&bad<3;t+=7*HOUR+3*60+1){
    const fu=t-off*HOUR,eutc=euDst(t-(off+1)*HOUR)?t-(off+1)*HOUR:t-off*HOUR;
    if(nearTransition(fu,3*HOUR)||nearTransition(eutc,3*HOUR)) continue;
    if(fixed.GoatNYServerToUTC(t)!==fu||fixed.GoatNYTime(t)!==nyOfUtc(fu)){bad++;fail('Fixed '+off+': NY of server '+new Date(t*1000).toISOString());}
    if(eu.GoatNYServerToUTC(t)!==eutc||eu.GoatNYTime(t)!==nyOfUtc(eutc)){bad++;fail('EUDST '+off+': NY of server '+new Date(t*1000).toISOString());}
   }
  }
  // The shoulder weeks by hand (Server_UTC_Offset 2): US DST on and EU DST off, then both on, then EU off and US on.
  const eu=world(src,{inputs:{Server_Clock_Model:'ServerClock_EUDST',Server_UTC_Offset:2}}).ctx;
  const fx=world(src,{inputs:{Server_Clock_Model:'ServerClock_Fixed',Server_UTC_Offset:2}}).ctx;
  const hand=[[eu,U(2026,1,15,12),5],[eu,U(2026,3,10,12),6],[eu,U(2026,3,30,12),5],[eu,U(2026,7,15,12),5],[eu,U(2026,10,28,12),6],[eu,U(2026,11,2,12),5],
   [fx,U(2026,1,15,12),5],[fx,U(2026,3,10,12),6],[fx,U(2026,7,15,12),6],[fx,U(2026,11,2,12),5]];
  for(const [c,t,h] of hand){const got=new Date(c.GoatNYTime(t)*1000);if(got.getUTCHours()!==h||got.getUTCMinutes()!==0)fail('server '+new Date(t*1000).toISOString()+' should be '+h+':00 NY, got '+got.toISOString());}
 },
 session_phase(src,fail){
  const {ctx}=world(src);
  const SUN=0,MON=1,TUE=2,WED=3,THU=4,FRI=5,SAT=6;
  // The FX trade-date convention (GOAT-EA#273 P2): a start at or after 17:00 NY trades the next NY date; Friday's
  // session ends by 16:55 NY Friday (P1).
  const cases=[ // [dow, minute, start, end, phase, session_dow]
   // 09:30-16:00
   [MON,569,570,960,0,MON],[MON,570,570,960,1,MON],[MON,959,570,960,1,MON],[MON,960,570,960,2,MON],[MON,1439,570,960,2,MON],
   [SUN,600,570,960,0,SUN],[SAT,600,570,960,0,SAT],[FRI,1000,570,960,2,FRI],[FRI,1014,570,960,2,FRI],
   // 18:00-02:00: Sunday 18:00 is Monday's session, Thursday 18:00 Friday's, Friday 18:00 Saturday's (none)
   [SUN,1080,1080,120,1,MON],[MON,60,1080,120,1,MON],[MON,120,1080,120,2,MON],[MON,1079,1080,120,2,MON],[SUN,1079,1080,120,0,MON],
   [MON,1080,1080,120,1,TUE],[TUE,60,1080,120,1,TUE],[TUE,119,1080,120,1,TUE],[TUE,120,1080,120,2,TUE],
   [THU,1080,1080,120,1,FRI],[FRI,60,1080,120,1,FRI],[FRI,120,1080,120,2,FRI],[FRI,1079,1080,120,2,FRI],
   [FRI,1080,1080,120,0,SAT],[SAT,60,1080,120,0,SAT],[SAT,130,1080,120,0,SAT],[SAT,1100,1080,120,0,SUN],[SUN,60,1080,120,0,SUN],
   // 18:00-16:00: Monday through Friday sessions, Friday's from Thursday 18:00 to Friday 16:00
   [SUN,1080,1080,960,1,MON],[MON,959,1080,960,1,MON],[MON,960,1080,960,2,MON],[THU,1100,1080,960,1,FRI],[FRI,959,1080,960,1,FRI],
   [FRI,960,1080,960,2,FRI],[FRI,1080,1080,960,0,SAT],[SAT,600,1080,960,0,SAT],
   // 09:30-20:00: Friday's session is cut at 16:55 NY; Thursday's is not
   [THU,1015,570,1200,1,THU],[THU,1199,570,1200,1,THU],[FRI,1014,570,1200,1,FRI],[FRI,1015,570,1200,2,FRI],[FRI,1199,570,1200,2,FRI],
   // 09:00-02:00 (a start before 17:00 that crosses midnight): Friday's session is cut at 16:55, its Saturday tail too
   [FRI,1014,540,120,1,FRI],[FRI,1015,540,120,2,FRI],[SAT,30,540,120,2,FRI],[SAT,130,540,120,2,FRI],[FRI,60,540,120,1,THU],[FRI,130,540,120,2,THU],
   // 17:00-23:00 (a start at exactly 17:00 trades the next date)
   [SUN,1020,1020,1380,1,MON],[FRI,1020,1020,1380,0,SAT],[THU,1020,1020,1380,1,FRI],[THU,1380,1020,1380,2,FRI]];
  for(const [dow,m,s,e,phase,sd] of cases){const box={v:-1};const got=ctx.GoatNYSessionPhase(dow,m,s,e,box);
   if(got!==phase||(phase!==0&&box.v!==sd)) fail('phase(dow '+dow+', '+m+', '+s+'-'+e+') = '+got+'/'+box.v+', expected '+phase+'/'+sd);}
 },
 ny_session_active(src,fail){
  // NYClose: server = NY + 7 h. 2026-10-05 is a Monday. A crossing window 18:00-02:00 NY, FX trade dates: Sunday 18:00
  // opens Monday's session, Friday 18:00 would be Saturday's (none).
  const W=world(src,{inputs:{Clock_Mode:'Clock_NewYork',NY_Session:'18:00-02:00'}});
  const ny=(d,h,m=0)=>U(2026,10,d,h,m)+7*HOUR;
  const exp=[[ny(4,17,59),false],[ny(4,18,0),true],[ny(5,1,0),true],[ny(5,2,0),false],[ny(5,17,59),false],[ny(5,18,0),true],[ny(5,23,0),true],
   [ny(6,1,30),true],[ny(6,2,0),false],[ny(8,19,0),true],[ny(9,1,0),true],[ny(9,2,0),false],
   [ny(9,19,0),false],[ny(10,1,0),false],[ny(10,19,0),false],[ny(11,1,0),false],[ny(11,19,0),true],[ny(12,1,0),true],[ny(12,19,0),true]];   // 4 Sun, 9 Fri, 10 Sat, 11 Sun, 12 Mon
  for(const [t,a] of exp){W.apply(t);if(W.ctx.Active!==a)fail('NY '+new Date((t-7*HOUR)*1000).toISOString()+': Active should be '+a);
   if(!a&&W.ctx.InActive!==true)fail('outside the session InActive is true');}
  // through the real tick: the server session (SESS_AS, 01:30-11:00 server) is shut while the NY session runs.
  const T=world(src,{inputs:{Clock_Mode:'Clock_NewYork',Active_Time_Weekday:'SESS_AS'}});
  // IsNewSecond compares the second of the minute only: every tick here has a second of its own.
  T.tick(ny(5,9,29)+1,1.1);if(T.ctx.Active!==false)fail('tick: before 09:30 NY inactive');
  T.tick(ny(5,9,30)+2,1.1);if(T.ctx.Active!==true)fail('tick: 09:30 NY active although the server session is shut');
  T.tick(ny(5,9,31)+3,1.1);   // the first signal check in the session clears InActive
  if(T.ctx.InActive!==false)fail('tick: the first in-session signal check clears InActive');
  T.tick(ny(5,9,31)+24,1.1);  // the shut server session does not force InActive=true: its block does not run (A0's guard)
  if(T.ctx.InActive!==false)fail('tick: InActive survives the shut server session ('+T.ctx.InActive+')');
  T.tick(ny(5,16,0)+5,1.1);if(T.ctx.Active!==false||T.ctx.InActive!==true)fail('tick: 16:00 NY inactive');
  // Action_Dayend=Pause through the real tick: the pause set at the NY day end holds overnight (the server session
  // opens at 01:30 server = 18:30 NY, but its block, which would clear the pause while InActive, does not run under
  // Clock_NewYork), until the next NY session.
  const P=world(src,{inputs:{Clock_Mode:'Clock_NewYork',Active_Time_Weekday:'SESS_AS',Action_Dayend:'Action_Pause'}});
  P.tick(ny(5,15,59)+6,1.1);if(P.ctx.Sequence_Pause_Close)fail('tick: no pause inside the session');
  P.tick(ny(5,16,0)+7,1.1);if(!P.ctx.Sequence_Pause_Close)fail('tick: the NY day end pauses');
  P.tick(ny(6,0,30)+8,1.1);if(!P.ctx.Sequence_Pause_Close)fail('tick: the pause holds after NY midnight');
  P.tick(ny(6,9,29)+9,1.1);if(!P.ctx.Sequence_Pause_Close)fail('tick: the pause holds until the session');
  P.tick(ny(6,9,30)+10,1.1);if(P.ctx.Sequence_Pause_Close||!P.ctx.Active)fail('tick: the next NY session clears the pause');
 },
 pause_and_day_end(src,fail){
  const ny=(d,h,m=0,s=7)=>U(2026,10,d,h,m,s)+7*HOUR;
  const W=world(src,{inputs:{Clock_Mode:'Clock_NewYork',Action_Dayend:'Action_Close',Action_Friday:'Action_Pause'}});
  W.apply(ny(5,15,59));if(W.ctx.StopOut_Flag)fail('no day end inside the session');
  W.apply(ny(5,16,0));if(!W.ctx.StopOut_Flag)fail('the NY day end closes (Action_Dayend)');
  if(W.ctx.Sequence_Pause_Close)fail('Action_Friday is not Monday\'s');
  W.ctx.StopOut_Flag=false;W.apply(ny(6,9,0));if(W.ctx.StopOut_Flag)fail('no day end before Tuesday\'s session');
  W.apply(ny(9,16,30));if(!W.ctx.Sequence_Pause_Close)fail('the NY Friday close pauses (Action_Friday)');
  W.apply(ny(12,9,30));if(W.ctx.Sequence_Pause_Close)fail('the next session clears Sequence_Pause_Close');
  // Crossing 18:00-02:00: Friday's session (from Thursday 18:00) ends at 02:00 Friday NY, the Friday close;
  // Thursday's (from Wednesday 18:00) ends at 02:00 Thursday, not the Friday close.
  const X=world(src,{inputs:{Clock_Mode:'Clock_NewYork',NY_Session:'18:00-02:00',Action_Friday:'Action_Close'}});
  X.apply(ny(8,3,0));if(X.ctx.StopOut_Flag)fail('crossing: Thursday\'s session end is not the Friday close');
  X.apply(ny(9,2,0));if(!X.ctx.StopOut_Flag)fail('crossing: Friday\'s session ends Friday 02:00 NY, the Friday close');
  // 09:00-02:00: Thursday's session ends on calendar Friday 02:00 (not the Friday close); Friday's is cut at 16:55.
  const Y=world(src,{inputs:{Clock_Mode:'Clock_NewYork',NY_Session:'09:00-02:00',Action_Friday:'Action_Close'}});
  Y.apply(ny(9,3,0));if(Y.ctx.StopOut_Flag)fail('09:00-02:00: Thursday\'s session end on Friday 03:00 is not the Friday close');
  Y.apply(ny(9,16,54));if(Y.ctx.StopOut_Flag||!Y.ctx.Active)fail('09:00-02:00: Friday 16:54 still in session');
  Y.apply(ny(9,16,55));if(!Y.ctx.StopOut_Flag||Y.ctx.Active)fail('09:00-02:00: the 16:55 cutoff ends Friday\'s session and closes');
 },
 new_friday_ny_weekday(src,fail){
  const ny=(d,h,m=0)=>U(2026,10,d,h,m,7)+7*HOUR;
  const W=world(src,{inputs:{Clock_Mode:'Clock_NewYork',Trade_Friday:false}});
  W.apply(ny(8,19,0));if(W.ctx.Sequence_New_Friday!==true)fail('Thursday 19:00 NY (server Friday 02:00) is not Friday');
  W.apply(ny(9,10,0));if(W.ctx.Sequence_New_Friday!==false)fail('Friday 10:00 NY is Friday');
  const X=world(src,{inputs:{Clock_Mode:'Clock_NewYork',Trade_Friday:false,NY_Session:'18:00-02:00'}});
  X.apply(ny(7,19,0));if(X.ctx.Sequence_New_Friday!==true||X.ctx.Active!==true)fail('crossing: Wednesday 19:00 NY is Thursday\'s session');
  X.apply(ny(8,19,0));if(X.ctx.Sequence_New_Friday!==false||X.ctx.Active!==true)fail('crossing: Thursday 19:00 NY is Friday\'s session');
  X.apply(ny(9,1,0));if(X.ctx.Sequence_New_Friday!==false||X.ctx.Active!==true)fail('crossing: Friday 01:00 NY is Friday\'s session');
  X.apply(ny(4,19,0));if(X.ctx.Sequence_New_Friday!==true||X.ctx.Active!==true)fail('crossing: Sunday 19:00 NY is Monday\'s session');
 },
 friday_close_all_windows(src,fail){
  // GOAT-EA#273 P1 through the real tick: Action_Friday=Close, a trading run from Thursday 12:00 NY to Friday 17:30 NY;
  // every window has closed everything before 17:00 NY Friday and opens nothing after its Friday close.
  // [window, the Friday close (NY, Friday 2026-10-09)]: the session end, or the 16:55 cutoff when that is earlier.
  const nyT=(d,h,m=0)=>U(2026,10,d,h,m)+7*HOUR;
  for(const [win,closeAt] of [['18:00-02:00',nyT(9,2)],['18:00-16:00',nyT(9,16)],['09:30-20:00',nyT(9,16,55)],['09:30-16:00',nyT(9,16)]]){
   const W=world(src,{inputs:{Clock_Mode:'Clock_NewYork',NY_Session:win,Action_Friday:'Action_Close',Mode_Restart:'Restart_1'}});
   const start=nyT(8,12),end=nyT(9,17,30);let openBefore=0,openAt1659=-1;
   // ticks every 97 s (IsNewSecond compares the second of the minute), the price swinging 60 points every 2 h
   for(let t=start,i=0;t<end;t+=97,i++){
    W.tick(t,1.1+0.0030*Math.sin(i*97*Math.PI/7200));
    if(t<closeAt) openBefore=Math.max(openBefore,W.w.positions.length);
    if(t>=nyT(9,16,59)&&t<nyT(9,17)) openAt1659=W.w.positions.length;
   }
   const sends=W.w.trace.filter(x=>x.op==='OrderSend');
   if(!openBefore){fail(win+': the run opens a position before the Friday close');continue;}
   if(openAt1659!==0) fail(win+': '+openAt1659+' position(s) still open at 16:59 NY Friday');
   if(W.w.positions.length) fail(win+': positions held over the weekend');
   const closes=W.w.trace.filter(x=>x.op==='PositionClose'&&x.time>=closeAt&&x.time<closeAt+600);
   if(!closes.length) fail(win+': the Friday close closes at '+new Date((closeAt-7*HOUR)*1000).toISOString().slice(11,16)+' NY');
   if(sends.some(x=>x.time>=closeAt)) fail(win+': no new entry after the Friday close');
  }
 },
 rollover_symmetric(src,fail){
  const {ctx}=world(src);
  const at17=U(2026,10,6,17);
  for(let x=-1000;x<=1000;x++){const b=ctx.GoatNYRolloverBlocked(at17+x,15);if(b!==(Math.abs(x)<900)){fail('rollover at 17:00'+(x>=0?'+':'')+x+' s: '+b);break;}}
  for(const t of [U(2026,10,6,0),U(2026,10,6,23,59,59),U(2026,10,6,5),U(2026,10,6,4,59)]) if(ctx.GoatNYRolloverBlocked(t,15)) fail('rollover far from 17:00');
  if(ctx.GoatNYRolloverBlocked(at17,0)) fail('Rollover_Block_Minutes=0 blocks nothing');
  if(ctx.GoatNYRolloverBlocked(U(2026,10,6,5),720)||!ctx.GoatNYRolloverBlocked(U(2026,10,6,5,0,1),720)||!ctx.GoatNYRolloverBlocked(U(2026,10,6,4,59,59),720)) fail('rollover 720: only 05:00:00 NY is free');
  // Through GoatNYClockApply, under either clock: EUDST offset 2 in the March shoulder week (17:00 NY = 23:00 server).
  for(const mode of ['Clock_NewYork','Clock_Server']){
   const W=world(src,{inputs:{Clock_Mode:mode,Rollover_Block_Minutes:15,Server_Clock_Model:'ServerClock_EUDST',Server_UTC_Offset:2}});
   const s17=U(2026,3,10,23);
   for(const [t,b] of [[s17-900,false],[s17-899,true],[s17,true],[s17+899,true],[s17+900,false],[U(2026,3,11,0),false],[U(2026,7,15,0),true],[U(2026,7,14,23),false]])
    if(W.apply(t).g_GoatEntryBlocked!==b) fail(mode+': entry block at server '+new Date(t*1000).toISOString()+' should be '+b);
  }
  // It really blocks entries: a run that trades with no block opens nothing when every second but 05:00:00 NY is blocked.
  const MON=U(2026,10,5),H1=HOUR,p=path(MON,[[2*H1,1.1000],[5*H1,1.0940],[6*H1,1.0965],[8*H1,1.0925]]);
  const free=world(src),blocked=world(src,{inputs:{Rollover_Block_Minutes:720}});
  free.run(p);blocked.run(p);
  if(!free.w.trace.some(x=>x.op==='OrderSend')) fail('the free run trades');
  if(blocked.w.trace.some(x=>x.op==='OrderSend')) fail('the rollover block stops every new entry');
 },
 live_self_check(src,fail){
  // NYClose in October 2026 (US DST): the broker is UTC+3. A live terminal at UTC+3 agrees; at UTC+2 it does not.
  const t0=U(2026,10,6,12,0,7);
  const good=world(src,{tester:false,serverOffset:3,inputs:{Clock_Mode:'Clock_NewYork'}});
  good.apply(t0);if(good.ctx.g_GoatEntryBlocked)fail('live, agreeing clock: no block');
  if(good.panel.includes('CLOCK MISMATCH'))fail('live, agreeing clock: no panel flag');
  const bad=world(src,{tester:false,serverOffset:2,inputs:{Clock_Mode:'Clock_NewYork'}});
  bad.apply(t0);if(!bad.ctx.g_GoatEntryBlocked)fail('live, 1 h clock fault: entries blocked');
  if(!bad.panel.includes('CLOCK MISMATCH'))fail('live, clock fault: "CLOCK MISMATCH" on the panel');
  if(bad.w.logs.filter(l=>/CLOCK MISMATCH/.test(l)).length!==1)fail('live, clock fault: logged once');
  // once a minute: a server-time fault (TimeTradeServer 1 h off, GMT steady) cleared at +30 s still blocks until the
  // check at +60 s (a GMT that jumps backwards is checked at once)
  const srv=world(src,{tester:false,serverOffset:3,inputs:{Clock_Mode:'Clock_NewYork'}});
  srv.ctx.TimeTradeServer=()=>srv.w.time+HOUR;srv.apply(t0);if(!srv.ctx.g_GoatEntryBlocked)fail('live, server-time fault: entries blocked');
  srv.ctx.TimeTradeServer=()=>srv.w.time;srv.apply(t0+30);if(!srv.ctx.g_GoatEntryBlocked)fail('the check runs once a minute (still blocked at +30 s)');
  srv.apply(t0+59);if(!srv.ctx.g_GoatEntryBlocked)fail('the check runs once a minute (still blocked at +59 s)');
  srv.apply(t0+60);if(srv.ctx.g_GoatEntryBlocked)fail('the next check passes and lifts the block');
  if(!srv.w.logs.some(l=>/passes again/.test(l)))fail('the recovery is logged');
  // a gap of 90 s passes, 91 s fails
  for(const [gap,b] of [[90,false],[91,true],[-91,true]]){
   const W=world(src,{tester:false,serverOffset:3,inputs:{Clock_Mode:'Clock_NewYork'}});W.ctx.TimeGMT=()=>W.w.time-3*HOUR-gap;
   if(W.apply(t0).g_GoatEntryBlocked!==b)fail('a gap of '+gap+' s: blocked '+b);
  }
  // no clock fails closed
  const none=world(src,{tester:false,serverOffset:3,inputs:{Clock_Mode:'Clock_NewYork'}});none.ctx.TimeGMT=()=>0;
  if(!none.apply(t0).g_GoatEntryBlocked)fail('no GMT: fails closed');
  // Live under Clock_Server the self-check guards the rollover block's model too.
  const rs=world(src,{tester:false,serverOffset:2,inputs:{Rollover_Block_Minutes:15}});
  if(!rs.apply(t0).g_GoatEntryBlocked)fail('live, rollover under the server clock, clock fault: blocked');
  // The tester never checks: its TimeGMT is the server time (a 3 h "gap"), and it trusts the model.
  const tst=world(src,{tester:true,inputs:{Clock_Mode:'Clock_NewYork'}});
  tst.apply(t0);tst.apply(t0+60);
  if(tst.ctx.g_GoatEntryBlocked)fail('the tester never blocks on the self-check');
  if(tst.panel.includes('CLOCK MISMATCH'))fail('the tester never flags a mismatch');
  if(tst.w.logs.filter(l=>/the tester has no GMT, so it trusts Server_Clock_Model=0/.test(l)).length!==1)fail('the tester logs the trusted model once');
  // through the real tick: a live fault stops a run that trades with the clock in order.
  const MON=U(2026,10,5),H1=HOUR,p=path(MON,[[2*H1,1.1000],[5*H1,1.0940],[6*H1,1.0965],[8*H1,1.0925]]);
  const in_order=world(src,{tester:false,serverOffset:3,inputs:{Rollover_Block_Minutes:1}}),fault=world(src,{tester:false,serverOffset:2,inputs:{Rollover_Block_Minutes:1}});
  in_order.run(p);fault.run(p);
  if(!in_order.w.trace.some(x=>x.op==='OrderSend'))fail('live, clock in order: trades');
  if(fault.w.trace.some(x=>x.op==='OrderSend'))fail('live, clock fault: no new entry');
 },
 clock_server_noop(src,fail){
  // GoatNYClockApply with the flags off changes nothing, live or tester, with a clock that would fail the self-check.
  for(const tester of [true,false]){
   const W=world(src,{tester,serverOffset:5});
   for(const t of [U(2026,10,5,0,0,7),U(2026,10,6,17,0,7),U(2026,10,9,23,30,7),U(2026,10,10,12)]){
    W.w.time=t;W.ctx.Active=true;W.ctx.InActive=false;W.ctx.Sequence_New_Friday=false;
    const before=snapshot(W),logs=W.w.logs.length,panel=W.panel.length;
    W.ctx.GoatNYClockApply(4);
    const after=snapshot(W);
    for(const k of Object.keys(before)) if(before[k]!==after[k]){fail('Clock_Server ('+(tester?'tester':'live')+') changed '+k);break;}
    if(W.w.logs.length!==logs||W.panel.length!==panel)fail('Clock_Server logs or paints nothing');
   }
  }
  // A live run with the flags off trades exactly as A0's stub (B49a's behaviour), even with a clock that disagrees.
  const MON=U(2026,10,5),H1=HOUR,p=path(MON,[[2*H1,1.1000],[5*H1,1.0940],[6*H1,1.0965],[8*H1,1.0925],[9*H1,1.0960],[11*H1,1.1030]]);
  const stub=world(sourceWith(STUB),{tester:false,serverOffset:5}),tree=world(src,{tester:false,serverOffset:5});
  stub.run(p);tree.run(p);
  if(!stub.w.trace.some(x=>x.op==='OrderSend'))fail('the stub run trades');
  try{assert.deepEqual(tree.w.trace,stub.w.trace);}catch{fail('Clock_Server live: the trace differs from A0\'s stub');}
 },
};

function runAll(src){
 const failures=[];
 for(const [name,check] of Object.entries(CHECKS)){
  try{check(src,msg=>failures.push(name+': '+msg));}
  catch(e){failures.push(name+': threw '+String(e&&e.message||e).split('\n')[0]);}
 }
 return failures;
}

// 1. The tree passes every check.
const treeFailures=runAll(undefined);
assert.deepEqual(treeFailures,[],'GOAT_NYClock.mqh: the expected checks');
// The mutants' route (the file's text as an override) passes too, so a kill below is the mutation's, not the route's.
assert.deepEqual(runAll(sourceWith(SRC)),[],'the override route of the unmutated file passes');
assert.deepEqual(runAll(sourceWith(MAINSRC,H.MAIN)),[],'the override route of the unmutated entrypoint passes');
let passed=Object.keys(CHECKS).length+1;

// 2. Each mutant is killed. [name, from, to, replaceAll]
const MUTANTS=[
 ['first Sunday of March for the second','GoatNYNthSunday(year,3,2)','GoatNYNthSunday(year,3,1)'],
 ['NYClose offset 6 h','server_time-7*3600','server_time-6*3600',true],
 ['a midnight-crossing window treated as empty','   if(start_min<end_min || minute>=start_min)','   if(start_min>end_min) return 0;\n   if(start_min<end_min || minute>=start_min)'],
 ['the tester check inverted','bool live=(MQLInfoInteger(MQL_TESTER)==0 && MQLInfoInteger(MQL_OPTIMIZATION)==0);','bool live=!(MQLInfoInteger(MQL_TESTER)==0 && MQLInfoInteger(MQL_OPTIMIZATION)==0);'],
 ['EU DST for US DST (UTC to NY)','if(GoatNYUSDST(utc)) return utc-4*3600;','if(GoatNYEUDST(utc)) return utc-4*3600;'],
 ['US DST for EU DST (the EUDST server model)','if(GoatNYEUDST(utc_summer)) return utc_summer;','if(GoatNYUSDST(utc_summer)) return utc_summer;'],
 ['the 2nd Sunday of November for the 1st','GoatNYNthSunday(year,11,1)','GoatNYNthSunday(year,11,2)'],
 ['the 4th Sunday of March for the last (EU)','GoatNYLastSunday(year,3,31)','GoatNYNthSunday(year,3,4)'],
 ['US DST start at 06:00 UTC','GoatNYNthSunday(year,3,2))+7*3600','GoatNYNthSunday(year,3,2))+6*3600'],
 ['the rollover window one-sided','   if(gap<0) gap=-gap;\n   return (gap<minutes*60);','   return (gap<minutes*60);'],
 ['the rollover edge inclusive','return (gap<minutes*60);','return (gap<=minutes*60);'],
 ['the flags-off return dropped','   if(Clock_Mode!=Clock_NewYork && Rollover_Block_Minutes<=0) return;','   '],
 ['the self-check tolerance 1 h','return (gap<=90);','return (gap<=3600);'],
 ['the self-check every second','gmt-g_GoatNYClockChecked>=60','gmt-g_GoatNYClockChecked>=0'],
 ['the mismatch never blocks','g_GoatEntryBlocked=(g_GoatNYClockMismatch || ','g_GoatEntryBlocked=(false || '],
 ['the Friday close keyed to the NY date','if(InActive && phase==2 && session_dow==5)','if(InActive && phase==2 && nst.day_of_week==5)'],
 ['Sequence_New_Friday from the server weekday','int new_dow=(phase==1 ? session_dow : nst.day_of_week);','int new_dow=stm_cur.day_of_week;'],
 ['the Friday 16:55 cutoff removed','   if(phase==1 && session_dow==5 && (dow==6 || (dow==5 && minute>=16*60+55))) phase=2;   // the Friday cutoff\n','   '],
 ['the cutoff at 17:00','minute>=16*60+55','minute>=17*60'],
 ['no FX trade date (a session belongs to its calendar start date)','int next_date=(start_min>=17*60 ? 1 : 0);','int next_date=0;'],
 ['the trade date from 18:00, not 17:00','int next_date=(start_min>=17*60 ? 1 : 0);','int next_date=(start_min>=18*60 ? 1 : 0);'],
 ['a weekend session date counts','   if(session_dow<1 || session_dow>5) return 0;\n','   '],
 // A0's guard (GOAT V1.49.mq5, B50 block b50-server-session): the server session block must not run under Clock_NewYork.
 ['the server session block runs under Clock_NewYork','    if(Clock_Mode!=Clock_NewYork)\n    {\n    if((stm_cur.hour>Hour_Start[k]','    if(true)\n    {\n    if((stm_cur.hour>Hour_Start[k]',false,H.MAIN],
];
const killed={};
for(const [name,from,to,all,file=NYFILE] of MUTANTS){
 const src=file===NYFILE?SRC:MAINSRC;
 if(!all) assert.equal(src.split(from).length,2,'the mutant site is unique: '+name);
 const text=all?src.split(from).join(to):src.replace(from,to);
 assert.notEqual(text,src,'the mutant applies: '+name);
 const f=runAll(sourceWith(text,file));
 assert.ok(f.length>0,'mutant killed: '+name);
 killed[name]=f[0];passed++;
}

// 3. The tree's region calls the NY clock (the call site A0 placed) and the file is the one the harness inlines.
{const C=H.compile(H.loadSources());
 for(const f of ['GoatNYClockApply','GoatNYTime','GoatNYUSDST','GoatNYEUDST','GoatNYServerToUTC','GoatNYSessionPhase','GoatNYRolloverBlocked','GoatNYClockAgrees'])
  assert.ok(C.functions.includes(f),'converted: '+f);
 passed++;}

console.log(JSON.stringify({passed,test:'b50_clock',checks:Object.keys(CHECKS).length,mutants:MUTANTS.length,killed},null,1));
