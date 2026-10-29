// B49b PR-4 (F4: exits without a tick; R2: Fix_Clock. goatai#2587 6433828681, Claude-Mac 6433854745 ruling 2: the
// no-tick timer is live-only with no input; Fix_Clock is an appended flag, Off = B49a; round 2, Claude-Mac 6463573729).
// The production code runs here from GOAT V1.49.mq5 and GOAT_Inputs_Definitions.mqh:
// 1. GoatNoTickDue: never in the tester, a read-only monitor, batch or dashboard mode, while disconnected, before the
//    first real tick or while backing off; due once no tick has arrived for 5 s, then at most once per 5 s.
// 2. GoatNoTickTimer with every production gate: it runs GoatTickBody under g_GoatNoTickRun on the last tick's clock plus
//    the elapsed time (never the PC's TimeTradeServer), never past the last tick's server midnight, never in a closed
//    session or on a disabled symbol, never after OnInit forgets the tick; a timer run never counts as a tick.
// 3. The IsNew* helpers under the timer: IsNewSecond is true (the per-second block runs), IsNewDay and IsNewMinute are
//    false, and none of them moves the tick's own clock state.
// 4. Fix_Clock Off is B49a's IsNewSecond/IsNewMinute/IsNewDay exactly (source 693cad0) over a timeline built from the
//    aliasing gaps; On sees every gap: a tick exactly 60 s, an hour or a month later is new.
// 5. Placement: OnTick stamps the real tick; OnInit forgets the tick first and right after its own OnTick() call;
//    GoatTickBody takes the timer's clock under it and returns right after the per-second block (before trailing,
//    signals and entries); nothing between the clock line and that block runs ungated, and the minute's low equity
//    counts real ticks only; GoatTimerBody calls GoatNoTickTimer; CloseAllPositions logs and reports each attempt.
// 6. A no-tick fixture: the production per-second block, run through the timer's clock at a Friday session end with no
//    tick: the Friday action closes every position of this chart, each attempt is logged, and B49a's tick clock (the
//    last tick, still inside the session) would have left them open. A timer run never handles a bias edge.
// 7. A weekend under the timer: an equity dip below MinLevelEquity all weekend never latches a stop (the session gate),
//    while the same dip inside an open session does.
// 8. GoatNoTickSessionOpen: session bounds (end exclusive), several sessions, a session past midnight, a disabled symbol.
// 9. GoatNoTickRefused: market closed or trade disabled backs off 60 s, doubling to 15 min, one step per window; other
//    refusals never; a real tick clears it.
// 10. GoatNoTickCloseLog: once a minute per ticket, 16 tickets a minute, on the timer's clock.
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

// The F4 block's functions, all from production, in one context with the terminal stubbed. MQL integer division and the
// by-reference outputs (TimeToStruct, SymbolInfoSessionTrade) are the only rewrites.
const F4=[['void GoatNoTickStamp(void)','GoatNoTickStamp',''],['void GoatNoTickForget(void)','GoatNoTickForget',''],
 ['datetime GoatNoTickClock(const ulong now_ms)','GoatNoTickClock','now_ms'],
 ['bool GoatNoTickDue(const bool tester,const bool monitor,const bool connected,const ulong now_ms)','GoatNoTickDue','tester,monitor,connected,now_ms'],
 ['bool GoatNoTickSameDay(const datetime clock)','GoatNoTickSameDay','clock'],['bool GoatNoTickSessionOpen(const string symbol,const datetime clock)','GoatNoTickSessionOpen','symbol,clock'],
 ['void GoatNoTickTimer(void)','GoatNoTickTimer',''],['void GoatNoTickRefused(const uint retcode)','GoatNoTickRefused','retcode'],
 ['void GoatNoTickCloseLog(const ulong ticket,const int op)','GoatNoTickCloseLog','ticket,op']];
const mql=t=>t.replace(/\(long\)(\w+)\/(\d+)/g,'Math.floor($1/$2)').replace(/\(datetime\)\(\((\w+)-(\w+)\)\/1000\)/g,'Math.floor(($1-$2)/1000)')
 .replace(/MqlDateTime (\w+); TimeToStruct\((\w+),\1\);/g,'let $1=__struct($2);')
 .replace(/SymbolInfoSessionTrade\((\w+),\(ENUM_DAY_OF_WEEK\)(\w+)\.day_of_week,(\w+),(\w+),(\w+)\)/g,'((__r=__session($1,$2.day_of_week,$3))!==null&&(($4=__r[0]),($5=__r[1]),true))');
const struct=t=>{const d=new Date(t*1000);return {sec:d.getUTCSeconds(),min:d.getUTCMinutes(),hour:d.getUTCHours(),day:d.getUTCDate(),day_of_week:d.getUTCDay(),mon:d.getUTCMonth()+1};};
// An FX week on the broker's sessions: Sunday 22:00 to Friday 22:00, nothing on Saturday.
const FX={0:[[79200,86400]],1:[[0,86400]],2:[[0,86400]],3:[[0,86400]],4:[[0,86400]],5:[[0,79200]],6:[]};
function f4(){
 const c={g_GoatNoTickRun:false,g_GoatLastTickMs:0,g_GoatLastNoTickRunMs:0,g_GoatNoTickBackoffUntilMs:0,g_GoatNoTickBackoffMs:0,g_GoatLastTickTime:0,
  g_GoatNoTickLogTicket:Array(16).fill(0),g_GoatNoTickLogMs:Array(16).fill(0),g_GoatStudioReadOnlyMonitor:false,
  Mode_Operation:0,Operation_Batch:1,Operation_Dash:2,MQL_TESTER:6,TERMINAL_CONNECTED:7,SYMBOL_TRADE_MODE:8,SYMBOL_TRADE_MODE_DISABLED:0,
  TRADE_RETCODE_MARKET_CLOSED:10018,TRADE_RETCODE_TRADE_DISABLED:10017,TIME_DATE:1,TIME_SECONDS:4,_Symbol:'EURUSD',MAGIC1:7,GOAT_BUILD_ID:'b49b',
  now:0,server:0,tester:0,connected:1,tradeMode:4,sessions:FX,runs:[],prints:[],__r:null,Math};
 for(const m of main.matchAll(/^#define (GOAT_NO_TICK_\w+) (\d+)$/gm))c[m[1]]=Number(m[2]);
 assert.deepEqual([c.GOAT_NO_TICK_MS,c.GOAT_NO_TICK_BACKOFF_MIN_MS,c.GOAT_NO_TICK_BACKOFF_MAX_MS],[5000,60000,900000],'5 s, backing off 60 s to 15 min');
 c.GetTickCount64=()=>c.now;c.TimeCurrent=()=>c.server;c.MQLInfoInteger=k=>k===6?c.tester:0;c.TerminalInfoInteger=k=>k===7?c.connected:0;
 c.SymbolInfoInteger=(s,k)=>k===8?c.tradeMode:0;c.__struct=struct;c.__session=(s,dow,i)=>{const l=c.sessions[dow]||[];return i<l.length?l[i]:null;};
 c.TimeTradeServer=()=>{throw new Error('the PC\'s clock is never the timer\'s');};
 c.GoatTickBody=()=>c.runs.push({flag:c.g_GoatNoTickRun,clock:c.GoatNoTickClock(c.g_GoatLastNoTickRunMs)});
 c.Print=s=>c.prints.push(s);c.StringFormat=fmt;c.TimeToString=t=>new Date(t*1000).toISOString();
 vm.createContext(c);
 for(const [sig,name,params] of F4)vm.runInContext('function '+name+'('+params+'){'+js(mql(bodyOf(main,sig)))+'}',c);
 // A real tick at server time t on the PC's monotonic ms clock.
 c.tick=(ms,t)=>{c.now=ms;c.server=t;c.GoatNoTickStamp();};
 c.timerAt=ms=>{c.now=ms;const n=c.runs.length;c.GoatNoTickTimer();return c.runs.length>n;};
 return c;
}
const WED_NOON=Date.UTC(2026,9,28,12,0,0)/1000;

{// 1. GoatNoTickDue.
 const c=f4();
 assert.equal(c.GoatNoTickDue(false,false,true,100000),false,'before the first tick');
 c.tick(100000,WED_NOON);
 for(const [age,want] of [[0,false],[4999,false],[5000,true],[60000,true]])assert.equal(c.GoatNoTickDue(false,false,true,100000+age),want,'age '+age);
 assert.equal(c.GoatNoTickDue(true,false,true,200000),false,'never in the tester');
 assert.equal(c.GoatNoTickDue(false,true,true,200000),false,'never on a read-only monitor');
 assert.equal(c.GoatNoTickDue(false,false,false,200000),false,'never while disconnected');
 for(const mode of [1,2]){c.Mode_Operation=mode;assert.equal(c.GoatNoTickDue(false,false,true,200000),false,'never in batch or dashboard mode');}
 c.Mode_Operation=0;c.g_GoatLastNoTickRunMs=198000;
 assert.equal(c.GoatNoTickDue(false,false,true,200000),false,'at most once per 5 s');
 assert.equal(c.GoatNoTickDue(false,false,true,203000),true);
 c.g_GoatNoTickBackoffUntilMs=260000;
 assert.equal(c.GoatNoTickDue(false,false,true,259999),false,'never while backing off');
 assert.equal(c.GoatNoTickDue(false,false,true,260000),true);
 ok();}

{// 2. GoatNoTickTimer and its gates.
 let c=f4();
 assert.equal(c.timerAt(500000),false,'no tick since OnInit: nothing runs');
 c.tick(500000,WED_NOON);
 assert.equal(c.timerAt(504999),false,'a tick under 5 s ago: nothing runs');
 assert.equal(c.timerAt(505400),true,'5 s without a tick: it runs');
 assert.deepEqual(c.runs[0],{flag:true,clock:WED_NOON+5},'under the flag, on the last tick\'s clock plus the elapsed time');
 assert.equal(c.g_GoatNoTickRun,false,'the flag is cleared');assert.equal(c.g_GoatLastNoTickRunMs,505400,'the run is stamped');
 assert.equal(c.timerAt(509000),false,'at most once per 5 s');
 assert.equal(c.timerAt(510400),true);assert.equal(c.runs[1].clock,WED_NOON+10,'a timer run is not a tick: the clock keeps counting from the real one');
 c.connected=0;assert.equal(c.timerAt(520000),false,'disconnected: nothing runs');c.connected=1;
 c.tester=1;assert.equal(c.timerAt(530000),false,'the tester: nothing runs');c.tester=0;
 c.g_GoatStudioReadOnlyMonitor=true;assert.equal(c.timerAt(540000),false,'a read-only monitor: nothing runs');c.g_GoatStudioReadOnlyMonitor=false;
 c.tradeMode=0;assert.equal(c.timerAt(550000),false,'a disabled symbol: nothing runs');c.tradeMode=4;
 assert.equal(c.timerAt(560000),true);
 c.GoatNoTickForget();assert.equal(c.timerAt(570000),false,'after OnInit forgets the tick (a re-init, or OnInit\'s own OnTick call): nothing runs');
 // P1: never past the last real tick's server midnight (IsNewDay has not reset the day's start).
 c=f4();const LATE=Date.UTC(2026,9,28,23,59,50)/1000;c.tick(1000000,LATE);
 assert.equal(c.timerAt(1006000),true,'23:59:56, the tick\'s day: it runs');
 assert.equal(c.timerAt(1015000),false,'00:00:05 the next day: nothing runs');
 for(let ms=1020000;ms<=1000000+6*3600*1000;ms+=60000)assert.equal(c.timerAt(ms),false,'never on the new day without a tick');
 c.tick(1000000+6*3600*1000,LATE+6*3600);assert.equal(c.timerAt(1000000+6*3600*1000+5000),true,'a real tick on the new day re-arms it');
 // P2: never in a closed session (Friday 22:00 here), nor on the PC's clock (TimeTradeServer throws if read).
 c=f4();const FRI_LATE=Date.UTC(2026,9,30,21,59,58)/1000;c.tick(2000000,FRI_LATE);
 assert.equal(c.timerAt(2005000),false,'Friday 22:00:03, the session has closed: nothing runs');
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
 const clock=at('tm_cur = TimeCurrent(); TimeCurrent(stm_cur);');
 const server=at('if(g_GoatNoTickRun) {tm_cur=GoatNoTickClock(g_GoatLastNoTickRunMs); TimeToStruct(tm_cur,stm_cur);}');
 const second=at('if(IsNewSecond())'),back=at('if(g_GoatNoTickRun) return;'),trail=at('if(CheckTrailingLockTPNow())'),entry=at('SignalEntryTrigger();');
 assert.ok(mode<clock && clock<server && server<second,'the timer\'s clock right after the tick clock');
 assert.ok(!/GoatNoTickStamp|g_GoatLastTickMs\s*=/.test(tick),'GoatTickBody never stamps a tick: the timer runs it too');
 const f4block=main.slice(main.indexOf('// B49b:begin F4'),main.indexOf('// B49b:end F4'));
 assert.ok(!/TimeTradeServer/.test(f4block+tick),'the PC\'s clock is never the timer\'s');
 // Only a real OnTick event stamps; OnInit forgets the tick first (a re-init keeps the EA's globals) and right after its
 // own OnTick() call.
 assert.equal(bodyOf(main,'void OnTick()').replace(/\/\/.*$/gm,'').replace(/\s+/g,''),'GoatNoTickStamp();GoatTickBody();GoatTraceBoundary();','OnTick stamps, then runs the tick');
 const init=bodyOf(main,'int OnInit()'),initCode=init.replace(/\/\/.*$/gm,'').trim();
 assert.ok(initCode.startsWith('GoatNoTickForget();'),'OnInit forgets the tick first');
 assert.match(init,/\n   OnTick\(\); Sleep\(50\);\n   GoatNoTickForget\(\);/,'and right after its own OnTick() call');
 assert.equal((init.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').match(/\bOnTick\(\)/g)||[]).length,1,'OnInit calls OnTick once');
 // The return follows the per-second block's closing brace directly, and precedes trailing and entries.
 const block=bodyOf(tick,'if(IsNewSecond())'),blockEnd=tick.indexOf(block)+block.length;
 assert.equal(tick.slice(blockEnd,back).replace(/\s+/g,''),'}','the return sits right after the per-second block');
 assert.ok(back<trail && trail<entry,'before trailing and entries');
 // Between the clock line and the per-second block, every top-level statement is gated by an IsNew* helper the timer
 // answers false, or touches no position (the rank tick returns at once outside blind exports; the minute's low equity).
 const between=tick.slice(server,second).split('\n').slice(1);let depth=0;const top=[];
 for(const line of between){const code=line.replace(/\/\*.*?\*\//g,'').replace(/\/\/.*$/,'').replace(/"[^"]*"/g,'');const t=code.trim();
  if(depth===0&&t&&t!=='{'&&t!=='}')top.push(t);depth+=(code.match(/\{/g)||[]).length-(code.match(/\}/g)||[]).length;}
 assert.deepEqual(top.filter(t=>!/^if\(IsNew(Day|Minute)\(\)\)$/.test(t)),['GoatRankTick();','static double MinuteLowEquity = DBL_MAX;','if(!g_GoatNoTickRun) MinuteLowEquity = MathMin(MinuteLowEquity,AccountInfoDouble(ACCOUNT_EQUITY));'],'ungated statements between the clock and the per-second block; the minute\'s low equity counts real ticks only');
 const timer=bodyOf(main,'void GoatTimerBody(void)');
 assert.ok(timer.includes('GoatNoTickTimer();'),'the timer body runs the no-tick check');
 assert.ok(timer.indexOf('GoatNoTickTimer();')>timer.indexOf('GOATDeviceActivationTimer();'),'after the activation-only return');
 const close=bodyOf(main,'void CloseAllPositions(int OP,int magic=0)');
 const log=close.indexOf('if(g_GoatNoTickRun) GoatNoTickCloseLog(m_position.Ticket(),OP);');
 assert.ok(log>close.indexOf('continue;',close.indexOf('OP != OP_BUYSELL')) && log<close.indexOf('m_trade.PositionClose('),'each attempt is logged after the filters, before the close');
 const refused=close.indexOf('if(g_GoatNoTickRun) GoatNoTickRefused(m_trade.ResultRetcode());');
 assert.ok(refused>close.indexOf('m_trade.PositionClose(') && refused<close.indexOf('closed++;'),'each attempt\'s retcode reaches the back-off');
 ok();}

// The production per-second block on a fixture account: four positions, two of them this chart's (EURUSD, magic 7).
const BLOCK=js(bodyOf(bodyOf(main,'void GoatTickBody()'),'if(IsNewSecond())'));
const CLOSE=js(bodyOf(main,'void CloseAllPositions(int OP,int magic=0)')).replace(/\bCTrade m_trade;/,'');
function perSecond({clock,noTick=true,lastTick=clock,equity=10000,minLevel=0,biasB=false}){
 const positions=[{ticket:11,symbol:'EURUSD',magic:7,type:0,volume:0.1},{ticket:12,symbol:'EURUSD',magic:7,type:1,volume:0.2},{ticket:13,symbol:'GBPUSD',magic:7,type:0,volume:0.1},{ticket:14,symbol:'EURUSD',magic:9,type:0,volume:0.1}];
 const state={closed:[],logs:[],refused:[],bias:[]};
 const base={Hour_Start:[8,8,8,8,8,8,8],Minute_Start:[0,0,0,0,0,0,0],Hour_End:[21,21,21,21,21,21,21],Minute_End:[0,0,0,0,0,0,0],
  InActive:false,Active:true,Sequence_Pause_Close:false,Trade_Friday:true,Trade_December:true,FastSpeed_Flag:true,MAGIC1:7,_Symbol:'EURUSD',
  POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,OP_BUYSELL:2,StopOut_Flag:false,StopOut_Flag_B:biasB,StopOut_Flag_S:false,LastStopoutTime:0,Mode_Restart:0,
  g_GoatLastStopOutB:false,g_GoatLastStopOutS:false,   // the bias edges (B49b F1 globals, OnTick statics before), false at start
  DStartLocalLoss:0,DStartTime:0,DStartEquity:10000,MaxEquity:10000,DDs_PC:[0],DDs_Actual:[0],CurrentDD:0,CurrentDDD:0,
  MaxLossLocal:0,MaxLossGlobal:0,MaxDailyLossLocal:0,MaxDailyProfitLocal:0,MinLevelEquity:minLevel,MaxLevelEquity:0,
  Action_Close:1,Action_Pause:2,Action_Dayend:0,Action_Friday:1,Key:'K',g_GoatNoTickRun:noTick,
  Math,Number,String,Array,JSON,undefined,NaN,Infinity};
 const ctx=new Proxy(base,{has:()=>true,get(t,p){if(p in t)return t[p];if(typeof p==='symbol')return undefined;return function stub(){return 0;};},set(t,p,v){t[p]=v;return true;}});
 vm.createContext(ctx);
 base.stm_cur=struct(clock);
 let selected=null;
 base.PositionsTotal=()=>positions.length;
 base.m_position={SelectByIndex:i=>{selected=positions[i];return !!selected;},Symbol:()=>selected.symbol,Magic:()=>selected.magic,Volume:()=>selected.volume,
  PositionType:()=>selected.type,Profit:()=>0,Commission:()=>0,Swap:()=>0,Ticket:()=>selected.ticket};
 base.AccountInfoDouble=()=>equity;base.TimeCurrent=()=>lastTick;
 base.GoatNoTickCloseLog=(ticket,op)=>state.logs.push([ticket,op]);base.GoatNoTickRefused=ret=>state.refused.push(ret);
 base.HandleBiasExitBuy=n=>state.bias.push(['B',n]);base.HandleBiasExitSell=n=>state.bias.push(['S',n]);
 // The production CloseAllPositions body, with the trade call recorded (it succeeds: retcode 10009).
 vm.runInContext('function CloseAllPositions(OP,magic){var m_trade={SetExpertMagicNumber(){},PositionClose:t=>{__closed.push(t);return true;},ResultRetcode:()=>10009,ResultRetcodeDescription:()=>"done"};'+CLOSE+'}',ctx);
 base.__closed=state.closed;
 base.FindNumberOfPositions=()=>positions.length-state.closed.length;
 base.Seq_Buy=base.Seq_Sell=base.Seq_Buy_Virtual=base.Seq_Sell_Virtual={End_Sequence(){}};
 vm.runInContext(BLOCK,ctx);
 return {...state,stop:base.StopOut_Flag};
}

{// 6. A no-tick fixture: the production per-second block, run through the timer's clock at a Friday session end.
 const FRI_END=Date.UTC(2026,9,30,21,0,30)/1000,LAST_TICK=Date.UTC(2026,9,30,20,59,10)/1000;   // the EA's session ends 21:00
 // The timer's clock (the last tick plus 80 s, 21:00:30 Friday): the session has ended, so the Friday action closes this
 // chart's two EURUSD positions (never another symbol's or magic's), each attempt logged and reported to the back-off.
 const timerRun=perSecond({clock:FRI_END,lastTick:LAST_TICK});
 assert.equal(timerRun.stop,true,'Friday session end: stop out');
 assert.deepEqual(timerRun.closed,[12,11],'both of this chart\'s positions, newest index first');
 assert.deepEqual(timerRun.logs,[[12,2],[11,2]],'each close attempt is logged');
 assert.deepEqual(timerRun.refused,[10009,10009],'and its retcode reaches the back-off');
 // B49a's clock without a tick is the last tick, still inside the session: nothing closes.
 const tickClock=perSecond({clock:LAST_TICK});
 assert.deepEqual([tickClock.stop,tickClock.closed],[false,[]],'on the stale tick clock the session is still open');
 // A bias stop-out edge: a real tick handles it; a timer run leaves it for the next real tick (no rescue, no SL/TP move).
 assert.deepEqual(perSecond({clock:WED_NOON,noTick:false,biasB:true}).bias,[['B',1]],'a real tick handles the bias edge');
 assert.deepEqual(perSecond({clock:WED_NOON,biasB:true}).bias,[],'a timer run never does');
 ok();}

{// 7. A weekend under the timer: an equity dip below MinLevelEquity never latches a stop (Claude-Mac 6463573729 P2-3).
 const run=(lastTickTime,fromMs,toMs)=>{
  const c=f4();let latched=0,runs=0;
  c.GoatTickBody=()=>{runs++;if(perSecond({clock:c.GoatNoTickClock(c.g_GoatLastNoTickRunMs),equity:8500,minLevel:9000}).stop)latched++;};
  c.tick(fromMs,lastTickTime);for(let ms=fromMs+1000;ms<=toMs;ms+=1000)c.timerAt(ms);
  return {runs,latched};
 };
 // The last EURUSD tick Friday 21:59:58; then the timer every second to Sunday 23:00 while crypto moves the account.
 const FRI_LAST=Date.UTC(2026,9,30,21,59,58)/1000;
 assert.deepEqual(run(FRI_LAST,1e7,1e7+(49*3600)*1000),{runs:0,latched:0},'the whole weekend: no run, no latch');
 // The same dip inside an open session does latch, so the gate above is what holds it.
 assert.deepEqual(run(WED_NOON,1e7,1e7+6000),{runs:1,latched:1},'Wednesday noon, the session open: the dip stops out');
 ok();}

{// 8. GoatNoTickSessionOpen.
 const c=f4(),at=(y,mo,d,h,mi,s)=>Date.UTC(y,mo,d,h,mi,s)/1000,open=t=>c.GoatNoTickSessionOpen('EURUSD',t);
 assert.equal(open(at(2026,9,26,10,0,0)),true,'Monday 10:00');
 assert.equal(open(at(2026,9,30,21,59,59)),true,'Friday 21:59:59');
 assert.equal(open(at(2026,9,30,22,0,0)),false,'Friday 22:00: the session end is exclusive');
 assert.equal(open(at(2026,9,31,12,0,0)),false,'Saturday');
 assert.equal(open(at(2026,10,1,21,59,59)),false,'Sunday before the open');
 assert.equal(open(at(2026,10,1,22,0,0)),true,'Sunday 22:00');
 c.sessions={3:[[0,3600],[7200,86400]]};
 assert.deepEqual([at(2026,9,28,0,30,0),at(2026,9,28,1,30,0),at(2026,9,28,2,30,0)].map(open),[true,false,true],'two sessions with a break');
 c.sessions={3:[[79200,3600]]};
 assert.deepEqual([at(2026,9,28,23,0,0),at(2026,9,28,0,30,0),at(2026,9,28,2,0,0)].map(open),[true,true,false],'a session past midnight');
 c.sessions=FX;c.tradeMode=0;assert.equal(open(at(2026,9,26,10,0,0)),false,'a disabled symbol is closed');
 ok();}

{// 9. GoatNoTickRefused: the back-off.
 const c=f4();c.tick(1000,WED_NOON);
 c.now=100000;c.GoatNoTickRefused(10004);assert.equal(c.g_GoatNoTickBackoffUntilMs,0,'a requote never backs off');
 c.GoatNoTickRefused(10018);assert.deepEqual([c.g_GoatNoTickBackoffMs,c.g_GoatNoTickBackoffUntilMs],[60000,160000],'market closed: 60 s');
 c.now=100001;c.GoatNoTickRefused(10018);assert.equal(c.g_GoatNoTickBackoffUntilMs,160000,'one step per window, however many tickets');
 const steps=[];for(let i=0;i<6;i++){c.now=c.g_GoatNoTickBackoffUntilMs;c.GoatNoTickRefused(i%2?10017:10018);steps.push(c.g_GoatNoTickBackoffMs);}
 assert.deepEqual(steps,[120000,240000,480000,900000,900000,900000],'doubling to 15 min; trade disabled counts too');
 c.now=c.g_GoatNoTickBackoffUntilMs-1;assert.equal(c.GoatNoTickDue(false,false,true,c.now),false,'not due while backing off');
 c.tick(c.now,WED_NOON+3600);assert.deepEqual([c.g_GoatNoTickBackoffMs,c.g_GoatNoTickBackoffUntilMs],[0,0],'a real tick clears it');
 ok();}

{// 10. GoatNoTickCloseLog: once a minute per ticket, on the timer's clock.
 const c=f4();c.tick(1000,WED_NOON);c.g_GoatLastNoTickRunMs=7000;
 for(const ms of [7000,12000,66999])c.now=ms,c.GoatNoTickCloseLog(11,2);
 assert.equal(c.prints.length,1,'one line in the minute');
 assert.match(c.prints[0],/^GOAT no-tick close: ticket=11 op=2 magic=7 clock=2026-10-28T12:00:06\.000Z last_tick_age_ms=6000 build_id=b49b$/);
 c.now=67000;c.GoatNoTickCloseLog(11,2);assert.equal(c.prints.length,2,'the next minute logs again');
 c.prints.length=0;for(let t=100;t<117;t++)c.GoatNoTickCloseLog(t,2);
 assert.equal(c.prints.length,15,'16 slots: ticket 11 holds one, so 15 new tickets log and the 17th waits');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f4',b49aCompared:true}));
