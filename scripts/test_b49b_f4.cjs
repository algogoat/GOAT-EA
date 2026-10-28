// B49b PR-4 (F4: exits without a tick; R2: Fix_Clock. goatai#2587 6433828681, Claude-Mac 6433854745 ruling 2: the
// no-tick timer is live-only with no input; Fix_Clock is an appended flag, Off = B49a). The production code runs here
// from GOAT V1.49.mq5 and GOAT_Inputs_Definitions.mqh:
// 1. GoatNoTickDue: never in the tester, a read-only monitor, batch or dashboard mode, or before the first tick; due once
//    no tick has arrived for 5 s, then at most once per 5 s.
// 2. GoatNoTickTimer runs GoatTickBody with g_GoatNoTickRun set, clears it, and stamps the run; not due, it runs nothing.
// 3. The IsNew* helpers under the timer: IsNewSecond is true (the per-second block runs), IsNewDay and IsNewMinute are
//    false, and none of them moves the tick's own clock state.
// 4. Fix_Clock Off is B49a's IsNewSecond/IsNewMinute/IsNewDay exactly (source 693cad0) over a timeline built from the
//    aliasing gaps; On sees every gap: a tick exactly 60 s, an hour or a month later is new.
// 5. Placement: GoatTickBody stamps the last real tick only off the timer, takes the trade server's clock under it, and
//    returns right after the per-second block (before trailing, signals and entries); nothing between the clock line and
//    that block runs ungated; GoatTimerBody calls GoatNoTickTimer; CloseAllPositions logs each attempt under the timer.
// 6. A no-tick fixture: the production per-second block, run through the timer's clock at a Friday session end with no
//    tick: the Friday action closes every position of this chart, each attempt is logged, and B49a's tick clock (the
//    last tick, still inside the session) would have left them open.
// test_b49b_f4_mutations.cjs runs this file on mutated sources (GOAT_EA_MAIN, GOAT_EA_HEADER).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const header=clean(fs.readFileSync(process.env.GOAT_EA_HEADER||path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
const headerB49a=clean(execFileSync('git',['show',B49A_SOURCE+':GOAT_Inputs_Definitions.mqh'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
// MQL statics become function-scoped `var`s hoisted out by the caller (`statics`), so a call keeps its state.
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(/\bstatic\s+/g,'')
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ').replace(/\blet (\w+)\[\]/g,'let $1=[]')
 .replace(/\((?:long|int|uint|ulong|double|datetime|bool)\)/g,'');
const fmt=(f,...a)=>{let i=0;return f.replace(/%%|%(?:I64)?(\.\d+)?([dfsu])/g,(m,p,t)=>{if(m==='%%')return '%';const v=a[i++];return t==='f'?Number(v).toFixed(p?Number(p.slice(1)):6):String(v);});};

{// 1. GoatNoTickDue.
 const c={g_GoatLastTickMs:0,g_GoatLastNoTickRunMs:0,Mode_Operation:0,Operation_Trade:0,Operation_Batch:1,Operation_Dash:2};vm.createContext(c);
 assert.match(main,/#define GOAT_NO_TICK_MS 5000\n/);c.GOAT_NO_TICK_MS=5000;
 vm.runInContext('function GoatNoTickDue(tester,monitor,now_ms){'+js(bodyOf(main,'bool GoatNoTickDue(const bool tester,const bool monitor,const ulong now_ms)'))+'}',c);
 assert.equal(c.GoatNoTickDue(false,false,100000),false,'before the first tick');
 c.g_GoatLastTickMs=100000;
 for(const [age,want] of [[0,false],[4999,false],[5000,true],[60000,true]])assert.equal(c.GoatNoTickDue(false,false,100000+age),want,'age '+age);
 assert.equal(c.GoatNoTickDue(true,false,200000),false,'never in the tester');
 assert.equal(c.GoatNoTickDue(false,true,200000),false,'never on a read-only monitor');
 for(const mode of [1,2]){c.Mode_Operation=mode;assert.equal(c.GoatNoTickDue(false,false,200000),false,'never in batch or dashboard mode');}
 c.Mode_Operation=0;c.g_GoatLastNoTickRunMs=198000;
 assert.equal(c.GoatNoTickDue(false,false,200000),false,'at most once per 5 s');
 assert.equal(c.GoatNoTickDue(false,false,203000),true);
 ok();}

{// 2. GoatNoTickTimer.
 const c={g_GoatNoTickRun:false,g_GoatLastNoTickRunMs:0,g_GoatStudioReadOnlyMonitor:false,MQL_TESTER:6,due:true,now:500000,runs:[],tester:0};vm.createContext(c);
 c.GetTickCount64=()=>c.now;c.MQLInfoInteger=k=>k===6?c.tester:0;c.GoatNoTickDue=(tester,monitor,now)=>{c.args=[tester,monitor,now];return c.due;};
 c.GoatTickBody=()=>c.runs.push(c.g_GoatNoTickRun);
 vm.runInContext('function GoatNoTickTimer(){'+js(bodyOf(main,'void GoatNoTickTimer(void)'))+'}',c);
 c.GoatNoTickTimer();
 assert.deepEqual(c.runs,[true],'the tick body runs once, under the flag');assert.equal(c.g_GoatNoTickRun,false,'and the flag is cleared');
 assert.equal(c.g_GoatLastNoTickRunMs,500000,'the run is stamped');assert.deepEqual(c.args,[false,false,500000]);
 c.tester=1;c.g_GoatStudioReadOnlyMonitor=true;c.due=false;c.now=600000;c.GoatNoTickTimer();
 assert.deepEqual(c.args,[true,true,600000],'the tester and monitor states reach the predicate');
 assert.deepEqual(c.runs,[true],'not due: nothing runs');assert.equal(c.g_GoatLastNoTickRunMs,500000,'and nothing is stamped');
 ok();}

// The IsNew* helpers, B49a's and this tree's, over the same clock.
const NEW=['IsNewSecond','IsNewMinute','IsNewDay'];
function helpers(text,fixClock){
 const c={stm_cur:{},tm_cur:0,g_GoatNoTickRun:false,Fix_Clock:fixClock,GoatFix_Off:0,GoatFix_On:1};vm.createContext(c);
 // Each MQL static is a closure variable of its own function, as MQL keeps it per function.
 for(const name of NEW){
  const body=bodyOf(text,'bool '+name+'()').replace(/\(long\)tm_cur\/(\d+)/g,'Math.floor(tm_cur/$1)');   // MQL's integer division
  const statics=[...body.matchAll(/\bstatic\s+(?:int|long|datetime)\s+(\w+)(?:\s*=\s*([-\d]+))?/g)];
  const decl=statics.map(m=>'let '+m[1]+'='+(m[2]||'0')+';').join('');
  const inner=js(body).replace(/\blet (\w+)(=[-\d]+)?;/g,(m,v)=>statics.some(s=>s[1]===v)?'':m);
  vm.runInContext('var '+name+'=(function(){'+decl+'return function(){'+inner+'};})();',c);
 }
 c.at=t=>{const d=new Date(t*1000);c.tm_cur=t;c.stm_cur={sec:d.getUTCSeconds(),min:d.getUTCMinutes(),hour:d.getUTCHours(),day:d.getUTCDate(),day_of_week:d.getUTCDay(),mon:d.getUTCMonth()+1};};
 return c;
}
// A timeline of tick times: ordinary ticks plus every aliasing gap (60 s, an hour, a day, 28/30/31 days).
const T0=Date.UTC(2026,9,2,10,15,7)/1000;
const timeline=[T0,T0+1,T0+2,T0+62,T0+122,T0+3722,T0+7322,T0+7323,T0+86400+7323,T0+32*86400+7323,T0+32*86400+7383,T0+62*86400+7383,T0+62*86400+7384];

{// 3. Under the timer: the per-second block runs, the day and minute blocks do not, and the tick clock state is untouched.
 for(const fixClock of [0,1]){
  const run=helpers(header,fixClock),ref=helpers(header,fixClock);
  for(const t of timeline){
   run.at(t);ref.at(t);
   run.g_GoatNoTickRun=true;
   assert.deepEqual([run.IsNewSecond(),run.IsNewMinute(),run.IsNewDay()],[true,false,false],'the timer runs only the per-second block');
   run.g_GoatNoTickRun=false;
   assert.deepEqual(NEW.map(n=>run[n]()),NEW.map(n=>ref[n]()),'a timer run between ticks changes no tick answer (Fix_Clock '+fixClock+', t '+t+')');
  }
 }
 ok();}

{// 4. Fix_Clock Off is B49a exactly; On sees every gap.
 const b49a=helpers(headerB49a,0),off=helpers(header,0),on=helpers(header,1);
 const seen={b49a:[],off:[],on:[]};
 for(const t of timeline){for(const [k,c] of Object.entries({b49a,off,on})){c.at(t);seen[k].push(NEW.map(n=>c[n]()));}}
 assert.deepEqual(seen.off,seen.b49a,'Off reproduces B49a tick for tick');
 // B49a's aliasing: a tick 60 s later has the same second, an hour later the same minute, a month later the same day.
 const at=(arr,t)=>arr[timeline.indexOf(t)];
 assert.equal(at(seen.b49a,T0+62)[0],false,'B49a: a tick 60 s later is not a new second');
 assert.equal(at(seen.b49a,T0+3722)[1],false,'B49a: a tick an hour later is not a new minute');
 assert.equal(at(seen.b49a,T0+32*86400+7323)[2],false,'B49a: a tick a month later is not a new day');
 for(const t of timeline.slice(1))assert.equal(at(seen.on,t)[0],true,'On: every later tick is a new second ('+t+')');
 assert.equal(at(seen.on,T0+3722)[1],true,'On: an hour later is a new minute');
 assert.equal(at(seen.on,T0+32*86400+7323)[2],true,'On: a month later is a new day');
 assert.equal(at(seen.on,T0+2)[1],false,'On: the same minute is not new');
 assert.equal(at(seen.on,T0+7323)[2],false,'On: the same day is not new');
 ok();}

{// 5. Placement.
 const tick=bodyOf(main,'void GoatTickBody()');
 const at=s=>{const i=tick.indexOf(s);assert.ok(i>=0,'missing in GoatTickBody: '+s);assert.equal(tick.indexOf(s,i+1),-1,'once: '+s);return i;};
 const mode=at('if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;');
 const stamp=at('if(!g_GoatNoTickRun) g_GoatLastTickMs=GetTickCount64();');
 const clock=at('tm_cur = TimeCurrent(); TimeCurrent(stm_cur);');
 const server=at('if(g_GoatNoTickRun) {tm_cur=TimeTradeServer(); TimeToStruct(tm_cur,stm_cur);}');
 const second=at('if(IsNewSecond())'),back=at('if(g_GoatNoTickRun) return;'),trail=at('if(CheckTrailingLockTPNow())'),entry=at('SignalEntryTrigger();');
 assert.ok(mode<stamp && stamp<clock && clock<server && server<second,'stamp after the mode return; the server clock right after the tick clock');
 // The return follows the per-second block's closing brace directly, and precedes trailing and entries.
 const block=bodyOf(tick,'if(IsNewSecond())'),blockEnd=tick.indexOf(block)+block.length;
 assert.equal(tick.slice(blockEnd,back).replace(/\s+/g,''),'}','the return sits right after the per-second block');
 assert.ok(back<trail && trail<entry,'before trailing and entries');
 // Between the clock line and the per-second block, every top-level statement is gated by an IsNew* helper the timer
 // answers false, or touches no position (the rank tick returns at once outside blind exports; the minute's low equity).
 const between=tick.slice(server,second).split('\n').slice(1);let depth=0;const top=[];
 for(const line of between){const code=line.replace(/\/\*.*?\*\//g,'').replace(/\/\/.*$/,'').replace(/"[^"]*"/g,'');const t=code.trim();
  if(depth===0&&t&&t!=='{'&&t!=='}')top.push(t);depth+=(code.match(/\{/g)||[]).length-(code.match(/\}/g)||[]).length;}
 assert.deepEqual(top.filter(t=>!/^if\(IsNew(Day|Minute)\(\)\)$/.test(t)),['GoatRankTick();','double MinuteLowEquity = DBL_MAX;'.replace('double','static double'),'MinuteLowEquity = MathMin(MinuteLowEquity,AccountInfoDouble(ACCOUNT_EQUITY));'],'ungated statements between the clock and the per-second block');
 const timer=bodyOf(main,'void GoatTimerBody(void)');
 assert.ok(timer.includes('GoatNoTickTimer();'),'the timer body runs the no-tick check');
 assert.ok(timer.indexOf('GoatNoTickTimer();')>timer.indexOf('GOATDeviceActivationTimer();'),'after the activation-only return');
 const close=bodyOf(main,'void CloseAllPositions(int OP,int magic=0)');
 const log=close.indexOf('if(g_GoatNoTickRun) GoatNoTickCloseLog(m_position.Ticket(),OP);');
 assert.ok(log>close.indexOf('continue;',close.indexOf('OP != OP_BUYSELL')) && log<close.indexOf('m_trade.PositionClose('),'each attempt is logged after the filters, before the close');
 ok();}

{// 6. A no-tick fixture: the production per-second block, run through the timer's clock at a Friday session end.
 const block=js(bodyOf(bodyOf(main,'void GoatTickBody()'),'if(IsNewSecond())'));
 const FRI_END=Date.UTC(2026,9,30,21,0,30)/1000,LAST_TICK=Date.UTC(2026,9,30,20,59,10)/1000;   // the session ends 21:00
 function run(clockTime){
  const positions=[{ticket:11,symbol:'EURUSD',magic:7,type:0,volume:0.1},{ticket:12,symbol:'EURUSD',magic:7,type:1,volume:0.2},{ticket:13,symbol:'GBPUSD',magic:7,type:0,volume:0.1},{ticket:14,symbol:'EURUSD',magic:9,type:0,volume:0.1}];
  const state={closed:[],logs:[]};
  const base={Hour_Start:[8,8,8,8,8,8,8],Minute_Start:[0,0,0,0,0,0,0],Hour_End:[21,21,21,21,21,21,21],Minute_End:[0,0,0,0,0,0,0],
   InActive:false,Active:true,Sequence_Pause_Close:false,Trade_Friday:true,Trade_December:true,FastSpeed_Flag:true,MAGIC1:7,_Symbol:'EURUSD',
   POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,OP_BUYSELL:2,StopOut_Flag:false,StopOut_Flag_B:false,StopOut_Flag_S:false,LastStopoutTime:0,Mode_Restart:0,
   DStartLocalLoss:0,DStartTime:0,DStartEquity:10000,MaxEquity:10000,DDs_PC:[0],DDs_Actual:[0],CurrentDD:0,CurrentDDD:0,
   MaxLossLocal:0,MaxLossGlobal:0,MaxDailyLossLocal:0,MaxDailyProfitLocal:0,MinLevelEquity:0,MaxLevelEquity:0,
   Action_Close:1,Action_Pause:2,Action_Dayend:0,Action_Friday:1,Key:'K',g_GoatNoTickRun:true,
   Last_StopOut_Flag_B:false,Last_StopOut_Flag_S:false,Math,Number,String,Array,JSON,undefined,NaN,Infinity};
  const ctx=new Proxy(base,{has:()=>true,get(t,p){if(p in t)return t[p];if(typeof p==='symbol')return undefined;return function stub(){return 0;};},set(t,p,v){t[p]=v;return true;}});
  vm.createContext(ctx);
  const d=new Date(clockTime*1000);base.stm_cur={sec:d.getUTCSeconds(),min:d.getUTCMinutes(),hour:d.getUTCHours(),day:d.getUTCDate(),day_of_week:d.getUTCDay(),mon:d.getUTCMonth()+1};
  let selected=null;
  base.PositionsTotal=()=>positions.length;
  base.m_position={SelectByIndex:i=>{selected=positions[i];return !!selected;},Symbol:()=>selected.symbol,Magic:()=>selected.magic,Volume:()=>selected.volume,
   PositionType:()=>selected.type,Profit:()=>0,Commission:()=>0,Swap:()=>0,Ticket:()=>selected.ticket};
  base.AccountInfoDouble=()=>10000;base.TimeCurrent=()=>LAST_TICK;
  base.GoatNoTickCloseLog=(ticket,op)=>state.logs.push([ticket,op]);
  // The production CloseAllPositions body, with the trade call recorded.
  vm.runInContext('function CloseAllPositions(OP,magic){var m_trade={SetExpertMagicNumber(){},PositionClose:t=>{__closed.push(t);return true;}};'
   +js(bodyOf(main,'void CloseAllPositions(int OP,int magic=0)')).replace(/\bCTrade m_trade;/,'')+'}',ctx);
  base.__closed=state.closed;
  base.FindNumberOfPositions=()=>positions.length-state.closed.length;
  base.Seq_Buy=base.Seq_Sell=base.Seq_Buy_Virtual=base.Seq_Sell_Virtual={End_Sequence(){}};
  vm.runInContext(block,ctx);
  return {...state,stop:base.StopOut_Flag};
 }
 // The timer's clock (the trade server, 21:00:30 Friday): the session has ended, so the Friday action closes this chart's
 // two EURUSD positions (never another symbol's or magic's), each attempt logged.
 const timerRun=run(FRI_END);
 assert.equal(timerRun.stop,true,'Friday session end: stop out');
 assert.deepEqual(timerRun.closed,[12,11],'both of this chart\'s positions, newest index first');
 assert.deepEqual(timerRun.logs,[[12,2],[11,2]],'each close attempt is logged');
 // B49a's clock without a tick is the last tick, still inside the session: nothing closes.
 const tickClock=run(LAST_TICK);
 assert.deepEqual([tickClock.stop,tickClock.closed],[false,[]],'on the stale tick clock the session is still open');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f4',b49aCompared:true}));
