// B49b lag hotfix (the terminals that fall behind, goatai#2587): source-level tests, no compiler. The production code runs
// here from GOAT V1.49.mq5 and GOAT_Inputs_Definitions.mqh, with the terminal stubbed. What this cannot show is listed in the
// PR: that it compiles, MT5's real timer and tick queue, TimeTradeServer's behaviour in a backlog, and the bench's numbers.
// 0. Flags off is the base: every hotfix line is marked, and without the marked lines both sources ARE be341e5's, byte for
//    byte. Each added call is a no-op with its flag off, or in the tester with its flag on.
// A. Fix_FeedGuard (safeguards): 1 the clock swap; 2 the Friday close on the server clock in a backlog; 3 the owed close across
//    the weekend; 4 a backlog over the open; 5 a restart; 6 the guard's thresholds; 7 exits never read it; 8 the status file;
//    9 the daily stops' window; 10 the no-tick clock; 10b a rejection that returned true; 19 clock sync; 20 a slow or fast clock;
//    21 a hold ends virtual candidates; 22 the owed close never hides or withholds a real stop.
// T. Diag_TickTiming: read-only, counted, and written with the guard off (11-13).
// B. Fix_TickLoad: truly bounded, the back-off, what changes with it on, and A never needs B (14-18).
// test_b49b_lag_mutations.cjs runs this file on mutated sources (GOAT_EA_MAIN, GOAT_EA_HEADER).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),BASE='be341e5c91650c3fa2bf67da0d2fc72ad240677d';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const header=clean(fs.readFileSync(process.env.GOAT_EA_HEADER||path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
const atBase=f=>clean(execFileSync('git',['show',BASE+':'+f],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
const js=text=>text.replace(/\(long\)([\w.]+)\/(\d+)/g,'Math.floor($1/$2)').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(/\bstatic\s+/g,'')
 .replace(/\bMqlTick (\w+);/g,'let $1={};').replace(/\bstring slot_names\[GOAT_TIMING_SLOTS\]=\{/g,'let slot_names=[').replace(/"timer"\};/g,'"timer"];')
 .replace(/TimeToStruct\(tm_cur,stm_cur\)/g,'stm_cur=__struct(tm_cur)').replace(/TimeCurrent\(stm_cur\)/g,'stm_cur=__struct(TimeCurrent())')
 .replace(/MqlDateTime (\w+); TimeToStruct\((\w+),\1\);/g,'let $1=__struct($2);')
 .replace(/SymbolInfoSessionTrade\((\w+),\(ENUM_DAY_OF_WEEK\)(\w+)\.day_of_week,(\w+),(\w+),(\w+)\)/g,'((__r=__session($1,$2.day_of_week,$3))!==null&&(($4=__r[0]),($5=__r[1]),true))')
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ').replace(/\blet (\w+)\[\]/g,'let $1=[]')
 .replace(/\((?:long|int|uint|ulong|double|datetime|bool)\)/g,'');
const struct=t=>{const d=new Date(t*1000);return {sec:d.getUTCSeconds(),min:d.getUTCMinutes(),hour:d.getUTCHours(),day:d.getUTCDate(),day_of_week:d.getUTCDay(),mon:d.getUTCMonth()+1};};
// A fixture array as MQL5 treats one: an index out of range removes the EA.
const bounded=a=>new Proxy(a,{get(t,p,r){if(typeof p==='string'&&/^-?\d+$/.test(p)&&(+p<0||+p>=t.length))throw new Error('array out of range: '+p);return Reflect.get(t,p,r);},set(t,p,v,r){if(typeof p==='string'&&/^-?\d+$/.test(p)&&(+p<0||+p>=t.length))throw new Error('array out of range: '+p);return Reflect.set(t,p,v,r);}});
const FX={0:[[79200,86400]],1:[[0,86400]],2:[[0,86400]],3:[[0,86400]],4:[[0,86400]],5:[[0,79200]],6:[]};
const FNS=[
 ['bool GoatManageOnlyLive()',''],
 ['bool GoatFeedGuardLive(void)',''],['datetime GoatServerClock(void)',''],['int GoatFeedAge(const datetime srv_clock)','srv_clock'],
 ['void GoatFeedGuardStamp(void)',''],['void GoatFeedInitMark(const bool init_done)','init_done'],['bool GoatFeedUnsynced(void)',''],['void GoatFeedSyncWatch(void)',''],['void GoatClockSkewWatch(const ulong now_ms)','now_ms'],['void GoatCloseOwedQuoteWatch(const bool feed_held,const ulong now_ms)','feed_held,now_ms'],['void GoatEntriesHoldWatch(void)',''],['void GoatCloseOwedStopLower(void)',''],['void GoatCloseRealStopNote(void)',''],['void GoatCloseOwedClear(void)',''],
 ['void GoatFeedGuardTick(void)',''],['void GoatFeedClockServer(void)',''],['void GoatFeedClockFeed(void)',''],
 ['bool GoatEntriesHeld(void)',''],['bool GoatCloseOwedDue(void)',''],['bool GoatCloseOwedHeld(void)',''],['void GoatCloseOwedAssert(const int open_count)','open_count'],
 ['void GoatCloseOwedAfter(const int open_count)','open_count'],['void GoatCloseOwedRefused(const uint retcode)','retcode'],['string GoatCloseOwedText(void)',''],
 ['void GoatCloseOwedRestore(const string &keys[],const string &values[])','keys,values'],['bool GoatStatusLive(void)',''],['string GoatStatusText(void)',''],['void GoatStatusFlush(void)',''],
 ['bool GoatModifyRejected(const uint retcode,const bool counted,const ulong ticket,const string what,const string description)','retcode,counted,ticket,what,description'],['bool GoatCloseRejected(const uint retcode,const bool counted,const ulong ticket,const string description)','retcode,counted,ticket,description'],
 ['bool GoatTickLoadLive(void)',''],['bool GoatTickLoadHold(const int slot)','slot'],['int GoatTrailSlot(const ulong ticket)','ticket'],['bool GoatTrailHeld(const ulong ticket)','ticket'],['void GoatTrailNote(const int side,const ulong ticket,const uint retcode)','side,ticket,retcode'],['void GoatTrailReset(const int side)','side'],
 ['bool GoatTimingLive(void)',''],['ulong GoatTimingStart(void)',''],['void GoatTimingSlot(const int slot,const ulong started_us)','slot,started_us'],['void GoatTimingTick(const ulong started_us)','started_us'],['string GoatTimingText(void)',''],['void GoatTimingFlush(void)',''],
 ['string GoatStateValue(const string &keys[],const string &values[],const string key)','keys,values,key'],
 ['bool GoatNoTickSessionOpen(const string symbol,const datetime clock)','symbol,clock'],
];
const TRADE_CODES=b=>Object.assign(b,{TRADE_RETCODE_NO_CHANGES:10025,TRADE_RETCODE_INVALID_STOPS:10016});
const nameOf=sig=>sig.match(/(\w+)\(/)[1];
const TICK=bodyOf(main,'void GoatTickBody()');
// The production day block and per-second block, in GoatTickBody's order; the minute block sits between them and is not run.
const PREFIX=TICK.slice(TICK.indexOf('if(GoatFeedUnsynced()) return;'),TICK.indexOf('static double MinuteLowEquity'));
const SECOND='if(IsNewSecond())\n{'+bodyOf(TICK,'if(IsNewSecond())')+'}';
const CLOSE=bodyOf(main,'void CloseAllPositions(int OP,int magic=0)').replace(/\bCTrade m_trade;/,'');
const HELPERS=['IsNewSecond','IsNewDay'];

// One chart on a stubbed terminal. feed: the newest tick the terminal has processed; server: TimeTradeServer.
function chart({flag=1,tester=0,action=1,positions=2,hourEnd=21,dailyLoss=0,timing=0,tickload=0,minLevel=0}={}){
 const list=[];for(let i=0;i<positions;i++)list.push({ticket:11+i,symbol:'EURUSD',magic:7,type:i%2,volume:0.1});
 const b={MQL_TESTER:6,MQL_OPTIMIZATION:61,MQL_FORWARD:62,Operation_Standard:0,Operation_Batch:1,Operation_Dash:2,Mode_Operation:0,Mode:'',
  Fix_FeedGuard:flag,Diag_TickTiming:timing,Fix_TickLoad:tickload,GOAT_TICK_LOAD_HOLD_MS:0,GOAT_TICK_LOAD_SLOTS:0,GOAT_TRAIL_FAIL_LIMIT:0,g_GoatTickLoadMs:bounded(Array(6).fill(0)),g_GoatTrailTicket:bounded([]),g_GoatTrailNextMs:bounded([]),g_GoatTrailSide:bounded([]),g_GoatTrailFails:bounded([]),Fix_Clock:0,g_GoatTimingSlotUS:bounded(Array(7).fill(0)),g_GoatTimingSlotCalls:bounded(Array(7).fill(0)),g_GoatTimingTicks:0,g_GoatTimingTickUS:0,g_GoatTimingTickMaxUS:0,g_GoatTimingWindowMs:0,g_GoatTimingWindowUS:0,g_GoatTimingWindowTicks:0,GOAT_TIMING_SLOTS:7,GOAT_TIMING_LOG_MS:0,us:0,GetMicrosecondCount:null,GoatFix_Off:0,GoatFix_On:1,GOAT_FEED_AGE_GUARD_S:0,GOAT_CLOSE_OWED_RETRY_MS:0,GOAT_STATUS_VERSION:0,GOAT_STATUS_WRITE_MS:0,
  GOAT_NO_TICK_BACKOFF_MIN_MS:60000,GOAT_NO_TICK_BACKOFF_MAX_MS:900000,
  g_GoatServerNow:0,g_GoatFeedTmSaved:0,g_GoatFeedStmSaved:null,g_GoatFeedAgeS:-1,g_GoatFeedHeldLogged:false,g_GoatFeedLogMs:0,g_GoatCloseOwed:false,g_GoatCloseOwedStop:false,g_GoatCloseFridayFired:false,
  g_GoatCloseOwedSince:0,g_GoatCloseOwedNextMs:0,g_GoatCloseOwedBackoffMs:0,g_GoatCloseOwedQuoteMs:0,g_GoatCloseOwedStopTime:0,g_GoatCloseRealStop:false,g_GoatFeedSynced:false,g_GoatFeedInitDone:true,g_GoatEntriesWereHeld:false,g_GoatClockSkewS:0,g_GoatClockFloorS:0,g_GoatClockFloorSet:false,g_GoatClockSlowLogged:false,g_GoatClockSlowHeld:false,g_GoatClockSlowSinceMs:0,GOAT_CLOSE_OWED_SETTLE_MS:0,GOAT_CLOCK_SLOW_LOG_S:0,GOAT_CLOCK_SLOW_HOLD_S:0,GOAT_CLOCK_SLOW_HOLD_MS:0,g_GoatStatusWrittenMs:0,g_GoatStatusFailLogged:false,g_GoatLastTickMs:0,g_GoatLastTickTime:0,g_GoatStateWriteError:0,
  g_GoatNoTickRun:false,tm_cur:0,stm_cur:{},TRADE_RETCODE_DONE:10009,TRADE_RETCODE_DONE_PARTIAL:10010,TRADE_RETCODE_PLACED:10008,TRADE_RETCODE_MARKET_CLOSED:10018,TRADE_RETCODE_TRADE_DISABLED:10017,
  SYMBOL_TRADE_MODE:8,SYMBOL_TRADE_MODE_DISABLED:0,TERMINAL_CONNECTED:7,ACCOUNT_LOGIN:9,TIME_DATE:1,TIME_SECONDS:4,FILE_COMMON:4096,_Symbol:'EURUSD',MAGIC1:7,GOAT_BUILD_ID:'b49b',
  closed:0,closeErrors:0,TSLmodifieds:3,TSLmodifyErrors:2,Hour_Start:[8,8,8,8,8,8,8],Minute_Start:[0,0,0,0,0,0,0],Hour_End:Array(7).fill(hourEnd),Minute_End:[0,0,0,0,0,0,0],
  InActive:false,Active:true,Sequence_Pause_Close:false,Trade_Friday:true,Trade_December:true,FastSpeed_Flag:true,POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,OP_BUYSELL:2,
  StopOut_Flag:false,StopOut_Flag_B:false,StopOut_Flag_S:false,LastStopoutTime:0,Mode_Restart:0,g_GoatLastStopOutB:false,g_GoatLastStopOutS:false,
  DStartLocalLoss:0,DStartTime:0,DStartEquity:10000,MaxEquity:10000,DDs_PC:[0],DDs_Actual:[0],CurrentDD:0,CurrentDDD:0,dt_Back_OOS:0,dt_Fwrd_OOS:0,
  MaxLossLocal:0,MaxLossGlobal:0,MaxDailyLossLocal:dailyLoss,MaxDailyProfitLocal:0,MinLevelEquity:minLevel,MaxLevelEquity:0,Ledger_Mode:0,Ledger_PositionJoin:1,
  Action_Close:1,Action_Pause:2,Action_Dayend:0,Action_Friday:action,Key:'K',days:0,LastEquity:0,Pause_Flag:false,
  feed:0,server:0,tickTime:0,tickReadable:true,nowMs:1000000,tester,retcode:10009,tradeMode:4,sessions:FX,prints:[],alerts:[],sends:[],ended:[],history:[],writes:[],writeOk:true,folders:[],__r:null,positions:list,serverReads:0,
  Math,Number,String,Array,JSON,undefined,NaN,Infinity};
 const ctx=new Proxy(b,{has:()=>true,get(t,p){if(p in t)return t[p];if(typeof p==='symbol')return undefined;return function stub(){return 0;};},set(t,p,v){t[p]=v;return true;}});
 vm.createContext(ctx);b.__ctx=ctx;
 for(const m of main.matchAll(/^#define (GOAT_(?:FEED_AGE_GUARD_S|CLOSE_OWED_RETRY_MS|STATUS_VERSION|STATUS_WRITE_MS|CLOSE_OWED_SETTLE_MS|CLOCK_SLOW_LOG_S|CLOCK_SLOW_HOLD_S|CLOCK_SLOW_HOLD_MS|TIMING_SLOTS|TIMING_LOG_MS|TICK_LOAD_HOLD_MS|TICK_LOAD_SLOTS|TRAIL_FAIL_LIMIT)) (\d+)(?:\s+\/\/.*)?$/gm))b[m[1]]=Number(m[2]);
 b.__struct=struct;b.__session=(s,dow,i)=>{const l=b.sessions[dow]||[];return i<l.length?l[i]:null;};
 b.TimeCurrent=()=>b.feed;b.TimeTradeServer=()=>{b.serverReads++;return b.server;};
 b.MQLInfoInteger=k=>k===6?b.tester:0;b.GetTickCount64=()=>b.nowMs;b.SymbolInfoInteger=(s,k)=>k===8?b.tradeMode:0;
 b.SymbolInfoTick=(s,t)=>{if(!b.tickReadable)return false;t.time=b.tickTime;return true;};
 b.GetMicrosecondCount=()=>b.us;b.StringFormat=(f,...a)=>{let i=0;return f.replace(/%(?:I64)?(\.\d+)?([dfsu])/g,(m,p,t)=>{const v=a[i++];return t==='f'?Number(v).toFixed(p?Number(p.slice(1)):6):String(v);});};b.ArraySize=a=>a.length;b.ArrayResize=(a,n)=>{a.length=n;return n;};TRADE_CODES(b); b.IntegerToString=v=>String(v);b.TimeToString=t=>String(t);b.StringToInteger=s=>Number(s)||0;
 b.Print=(...a)=>b.prints.push(a.join(''));b.Alert=s=>b.alerts.push(s);b.equity=10000;b.AccountInfoDouble=()=>b.equity;b.AccountInfoInteger=()=>555;b.PositionsTotal=()=>b.positions.length;b.TerminalInfoInteger=()=>1;
 let sel=null;
 b.m_position={SelectByIndex:i=>{sel=b.positions[i];return !!sel;},Symbol:()=>sel.symbol,Magic:()=>sel.magic,Volume:()=>sel.volume,PositionType:()=>sel.type,Profit:()=>0,Commission:()=>0,Swap:()=>0,Ticket:()=>sel.ticket};
 b.FindNumberOfPositions=()=>b.positions.length;
 b.Seq_Buy=b.Seq_Sell=b.Seq_Buy_Virtual=b.Seq_Sell_Virtual={End_Sequence:d=>b.ended.push(d)};
 b.HistorySelect=(f,t)=>{b.history.push([f,t]);return true;};b.HistoryDealsTotal=()=>0;
 b.GoatStateWrite=(p,t)=>{b.writes.push([p,t]);return b.writeOk;};b.FolderCreate=p=>{b.folders.push(p);return true;};
 for(const [sig,params] of FNS)vm.runInContext('function '+nameOf(sig)+'('+params+'){'+js(bodyOf(main,sig))+'}',ctx);
 vm.runInContext('function CloseAllPositions(OP,magic){var m_trade={SetExpertMagicNumber(){},PositionClose:t=>{__send(t);return __closeTrue()||__retcode()===10009;},ResultRetcode:()=>__retcode(),ResultRetcodeDescription:()=>"x"};'+js(CLOSE)+'}',ctx);
 b.__closeTrue=()=>b.closeReturnsTrue===true;b.closeLogged=[];b.GoatCloseFailureLog=(t,r,d)=>b.closeLogged.push([t,r]);b.PrintFormat=(f,...a)=>{let i=0;b.prints.push(f.replace(/%(?:I64)?(\.\d+)?([dfsu])/g,(m,p,t)=>{const v=a[i++];return t==='f'?Number(v).toFixed(p?Number(p.slice(1)):6):String(v);}));};
 b.__send=t=>{b.sends.push(t);if(b.retcode===10009)b.positions=b.positions.filter(p=>p.ticket!==t);};b.__retcode=()=>b.retcode;
 for(const name of HELPERS){
  const sigBody=bodyOf(header,'bool '+name+'()').replace(/\(long\)tm_cur\/(\d+)/g,'Math.floor(tm_cur/$1)');
  const statics=[...sigBody.matchAll(/\bstatic\s+(?:int|long|datetime)\s+(\w+)(?:\s*=\s*([-\d]+))?/g)];
  const decl=statics.map(m=>'let '+m[1]+'='+(m[2]||'0')+';').join('');
  const inner=js(sigBody).replace(/\blet (\w+)(=[-\d]+)?;/g,(m,v)=>statics.some(s=>s[1]===v)?'':m);
  vm.runInContext('var '+name+'=(function(){'+decl+'return function(){'+inner+'};})();',ctx);
 }
 b.stm_cur={sec:59,day:0};b.IsNewSecond();b.g_GoatTickLoadMs[0]=0;   // MQL statics start at 0: a first tick on second :00 would read as "not new"
 vm.runInContext('function TickBody(){'+js(PREFIX).replace(/\(long\)/g,'')+js(SECOND)+'}',ctx);
 // One real tick: the terminal has processed up to `feed`; the server's clock reads `server`. The tick's stamps, as OnTick.
 b.step=(feed,server,{tickTime=feed,ms=1000}={})=>{b.feed=feed;b.server=server;b.tickTime=tickTime;b.nowMs+=ms;b.g_GoatLastTickMs=b.nowMs;b.g_GoatLastTickTime=feed;b.GoatFeedGuardStamp();b.TickBody();return b;};
 return b;
}
const at=(mo,d,h,mi=0,s=0)=>Date.UTC(2026,mo,d,h,mi,s)/1000;
const FRI=(h,mi=0,s=0)=>at(9,30,h,mi,s),SAT=(h,mi=0,s=0)=>at(9,31,h,mi,s),SUN=(h,mi=0,s=0)=>at(10,1,h,mi,s),MON=(h,mi=0,s=0)=>at(10,2,h,mi,s);

{// 0. Flags off is the base: the sources without the marked lines are be341e5's, byte for byte.
 const strip=text=>{let block=false;return text.split('\n').filter(line=>{
   if(/\/\/ B49b:begin lag-/.test(line)){block=true;return false;}
   if(/\/\/ B49b:end lag-/.test(line)){block=false;return false;}
   if(block)return false;
   if(/\/\/ B49b \(LAG-[ABT]\)/.test(line))return false;
   return !/^sinput\s+ENUM_GOAT_FIX\s+(Fix_FeedGuard|Diag_TickTiming|Fix_TickLoad)\b/.test(line);
  }).join('\n');};
 assert.equal(strip(main),atBase('GOAT V1.49.mq5'),'GOAT V1.49.mq5 without the hotfix lines is the base');
 assert.equal(strip(header),atBase('GOAT_Inputs_Definitions.mqh'),'the header without the hotfix lines is the base');
 assert.ok(main.includes('// B49b:begin lag-a'),'the strip above is not vacuous');
 // Each flag is an appended sinput, default Off, written to a SET only when on.
 for(const name of ['Fix_FeedGuard','Diag_TickTiming','Fix_TickLoad']){
  assert.match(header,new RegExp('^sinput\\s+ENUM_GOAT_FIX\\s+'+name+'\\s*=\\s*GoatFix_Off;','m'),name+' defaults Off');
  assert.match(header,new RegExp('^if\\('+name+'!=GoatFix_Off\\) FileWrite\\(FileSET_handle,"'+name+'="','m'),name+' is written only when on');
 }
 // Off, and On in the tester, optimization or a forward pass: every LAG-A call is a no-op that never reads the server clock.
 for(const [flag,tester,label] of [[0,0,'flag off, live'],[1,1,'flag on, tester'],[0,1,'flag off, tester']]){
  const c=chart({flag,tester});
  c.TimeTradeServer=()=>{throw new Error('the server clock is read: '+label);};
  c.feed=FRI(10);c.tm_cur=FRI(10);c.stm_cur=struct(FRI(10));c.g_GoatLastTickTime=FRI(9);
  c.GoatFeedGuardStamp();assert.equal(c.g_GoatLastTickTime,FRI(9),label+': the no-tick clock is untouched');
  c.GoatFeedGuardTick();c.GoatFeedClockServer();assert.equal(c.tm_cur,FRI(10),label+': the clock is not swapped');c.GoatFeedClockFeed();assert.equal(c.tm_cur,FRI(10));
  assert.equal(c.GoatEntriesHeld(),false,label+': nothing is held');assert.equal(c.GoatCloseOwedHeld(),false);
  c.GoatCloseOwedAssert(2);assert.equal(c.StopOut_Flag,false);c.g_GoatCloseFridayFired=true;c.GoatCloseOwedAfter(2);assert.equal(c.g_GoatCloseOwed,false,label+': nothing becomes owed');
  assert.equal(c.GoatStatusLive(),false);c.GoatStatusFlush();assert.equal(c.writes.length,0,label+': no status file');assert.equal(c.GoatCloseOwedText(),'','and the state file gains nothing');
 }
 for(const k of ['MQL_OPTIMIZATION','MQL_FORWARD']){const c=chart();const v=c[k];c.MQLInfoInteger=i=>i===v?1:0;assert.equal(c.GoatFeedGuardLive(),false,k);}
 for(const mode of [1,2]){const c=chart();c.Mode_Operation=mode;assert.equal(c.GoatFeedGuardLive(),false,'batch or dashboard');}
 {const c=chart();c.Mode='EXPORT';assert.equal(c.GoatFeedGuardLive(),false,'an export');}
 // Tester parity over a whole backlog timeline: flag on in the tester is flag off, tick for tick.
 const trace=c=>{const out=[];for(const [f,s] of [[FRI(10),FRI(21,0,30)],[FRI(10,0,1),SAT(1)],[FRI(10,0,2),MON(1)],[MON(1,0,1),MON(1,0,1)]]){c.step(f,s);out.push([c.StopOut_Flag,c.sends.length,c.Active,c.InActive,c.tm_cur,JSON.stringify(c.stm_cur)]);}return out;};
 const off=trace(chart({flag:0})),testerOn=chart({flag:1,tester:1});testerOn.TimeTradeServer=()=>{throw new Error('tester reads the server clock');};
 assert.deepEqual(trace(testerOn),off,'tester, flag on: the same trace as flag off');
 ok();}

{// 1. The clock swap: session logic on the server clock inside the blocks, the samplers' clock put back after each.
 const c=chart({positions:0});
 c.step(FRI(10,5,7),FRI(10,5,50),{tickTime:FRI(10,5,7)});
 assert.equal(c.tm_cur,FRI(10,5,7),'after the blocks tm_cur is the feed\'s again');
 assert.deepEqual(c.stm_cur,struct(FRI(10,5,7)),'and stm_cur: CheckNewSecond/Minute and the bar samplers read the feed, as before');
 assert.equal(c.g_GoatServerNow,FRI(10,5,50));
 // The clock is never earlier than the broker's last tick, whatever the PC says.
 c.feed=FRI(10);c.server=FRI(9);assert.equal(c.GoatServerClock(),FRI(10),'a PC clock behind the broker: the broker\'s tick');
 c.server=FRI(11);assert.equal(c.GoatServerClock(),FRI(11));
 // The per-second block is entered exactly as before: on the feed's seconds, not the server's.
 const d=chart({positions:0});let entered=0;const real=d.IsNewSecond;d.IsNewSecond=()=>{const r=real();if(r)entered++;return r;};
 d.step(FRI(10,0,1),FRI(12,0,0));d.step(FRI(10,0,1),FRI(12,0,5));assert.equal(entered,1,'the same feed second: not re-entered, however far the server clock moved');
 d.step(FRI(10,0,2),FRI(12,0,5));assert.equal(entered,2,'a new feed second enters it');
 ok();}

{// 2. A backlog on a Friday: the tick being processed is 11 h old, the server's clock is past the session end.
 const run=flag=>{const c=chart({flag});c.step(FRI(10,0,0),FRI(21,0,30));return c;};
 const on=run(1),off=run(0);
 assert.deepEqual([on.StopOut_Flag,on.InActive,on.sends],[true,true,[12,11]],'on: the Friday close goes on the server clock, into an open market');
 assert.deepEqual([off.StopOut_Flag,off.sends],[false,[]],'off: the old tick is inside the session, so nothing closes (the measured defect)');
 assert.deepEqual(on.ended,['Day/Weekend Close','Day/Weekend Close','Day/Weekend Close','Day/Weekend Close'],'flat: the sequences end through B49a\'s own path');
 assert.equal(on.g_GoatCloseOwed,false,'and nothing is owed');
 assert.equal(run(1).alerts.length,0,'no alert when it went through');
 // Action_Friday not Close: no close and nothing owed, whatever the clock.
 const pause=chart({action:2});pause.step(FRI(10),FRI(21,0,30));assert.deepEqual([pause.sends,pause.g_GoatCloseOwed,pause.Sequence_Pause_Close],[[],false,true],'Pause pauses on the server clock too');
 ok();}

{// 3. The owed close: refused at the session end, held through the weekend, and after the first later quote sent on the first
 // tick at least 5 min on, unconditionally (the ruling: no spread check, which could stall it indefinitely).
 const week=flag=>{
  const c=chart({flag});c.retcode=10018;
  c.step(FRI(21,0,30),FRI(21,0,30));
  const out={first:[...c.sends],owed:c.g_GoatCloseOwed,alerts:c.alerts.length,errors:c.closeErrors};
  c.step(FRI(21,0,31),FRI(21,0,31));out.second=c.sends.length;                 // the next second, still inside the broker's session: retried, refused, backing off
  out.backoff=c.g_GoatCloseOwedBackoffMs;
  c.step(FRI(21,0,40),FRI(21,0,40));out.third=c.sends.length;                  // inside the back-off: not sent
  c.step(FRI(21,0,41),SAT(0,0,5));out.stopAfterReset=c.StopOut_Flag;           // the backlog runs on past midnight: the day resets on the server clock
  out.owedAfterReset=c.g_GoatCloseOwed;
  const sat=c.sends.length;for(let i=2;i<400;i++)c.step(FRI(21,0,40+i),SAT(1,0,i));out.satSends=c.sends.length-sat;   // a closed market is not asked
  c.step(FRI(21,8,0),SUN(21,59,59));out.beforeOpen=c.sends.length-sat;out.quoteBefore=c.g_GoatCloseOwedQuoteMs;
  c.retcode=10009;
  c.step(SUN(22,0,2),SUN(22,0,2));out.atQuote=c.sends.length-sat;              // the first quote after the weekend: the wait starts, nothing is sent
  out.quoteAt=c.g_GoatCloseOwedQuoteMs;
  c.step(SUN(22,4,59),SUN(22,4,59),{ms:299999});out.justBefore=c.sends.length-sat;   // 299,999 ms on: one short of 5 min
  c.sessions={};c.step(SUN(22,5,0),SUN(22,5,0),{ms:1});                        // 5 min on, the session table reading closed: sent, since nothing but the wait gates it
  return {...out,c};
 };
 const on=week(1),off=week(0);
 assert.deepEqual(on.first,[12,11],'both closes are tried at the session end');
 assert.equal(on.owed,true,'refused: owed');
 assert.equal(on.alerts,1,'loudly, once');assert.match(on.c.prints.find(l=>/left 2 position/.test(l)),/close_errors=2/,'closeErrors surfaced');
 assert.equal(on.errors,2,'closeErrors counts the refusals');
 assert.deepEqual([on.second,on.backoff],[4,60000],'retried, then a market-closed refusal backs off 60 s');
 assert.equal(on.third,4,'inside the back-off nothing is sent');
 assert.deepEqual([on.stopAfterReset,on.owedAfterReset],[false,true],'the day reset clears StopOut_Flag and the close stays owed (the dropped close)');
 assert.equal(on.satSends,0,'no send on Saturday');assert.deepEqual([on.beforeOpen,on.quoteBefore],[0,0],'nor before the open: a stale tick in a closed session starts nothing');
 assert.equal(on.atQuote,0,'the first quote sends nothing');assert.ok(on.quoteAt>0,'it starts the wait');assert.equal(on.justBefore,0,'one millisecond short of 5 min: not sent');
 const c=on.c;
 assert.ok(c.prints.some(l=>/first quote after the weekend/.test(l)),'said');
 assert.ok(c.prints.some(l=>/sending the Friday close owed since/.test(l)),'sent, logged');
 assert.deepEqual(c.positions,[],'from 5 min on the close goes and fills, whatever the session table says');
 assert.deepEqual([c.g_GoatCloseOwed,c.StopOut_Flag,c.LastStopoutTime,c.g_GoatCloseOwedQuoteMs],[false,false,0,0],'settled: the stop it raised is lowered, so Monday trades as after a normal Friday close');
 assert.ok(c.prints.some(l=>/settled, flat on EURUSD/.test(l)));
 assert.equal(c.ended.filter(d=>d==='Day/Weekend Close').length,4,'the sequences end through B49a\'s own path');
 for(const sig of ['bool GoatCloseOwedDue(void)','void GoatCloseOwedAssert(const int open_count)','bool GoatCloseOwedHeld(void)'])assert.ok(!/SPREAD/.test(bodyOf(main,sig)),'no spread check: '+sig);
 assert.equal(off.owed,false,'off: never owed');
 assert.equal(off.c.positions.length,2,'off: the refused close is dropped and Monday still holds the positions (the measured defect)');
 // After the wait a refusal still paces: 60 s, doubling; a tick never sends inside it.
 const p=chart();p.g_GoatCloseOwed=true;p.g_GoatCloseOwedSince=FRI(21);p.retcode=10018;p.step(MON(9),MON(9));const q=p.g_GoatCloseOwedQuoteMs;assert.ok(q>0);
 p.step(MON(9,5,1),MON(9,5,1),{ms:300000});assert.equal(p.sends.length,2,'the first attempt, both tickets');p.step(MON(9,5,2),MON(9,5,2));assert.equal(p.sends.length,2,'then paced');
 // A refusal other than a closed market retries after a second; a stop that was not the owed close's own stays up.
 const r=chart();r.step(MON(9),MON(9));r.nowMs=5000000;r.GoatCloseOwedRefused(10004);assert.equal(r.g_GoatCloseOwedNextMs,5001000,'a requote: a second');
 r.nowMs=5002000;r.GoatCloseOwedRefused(10009);assert.equal(r.g_GoatCloseOwedNextMs,5001000,'a fill never paces');r.nowMs=5000000;
 const steps=[];r.g_GoatCloseOwedNextMs=0;for(let i=0;i<6;i++){r.nowMs=r.g_GoatCloseOwedNextMs||r.nowMs;r.GoatCloseOwedRefused(i%2?10017:10018);steps.push(r.g_GoatCloseOwedBackoffMs);}
 assert.deepEqual(steps,[60000,120000,240000,480000,900000,900000],'closed or disabled: doubling to 15 min');
 const own=chart();own.retcode=10009;own.step(MON(9),MON(9));own.g_GoatCloseOwed=true;own.StopOut_Flag=true;own.step(MON(9,0,1),MON(9,0,1));
 assert.equal(own.StopOut_Flag,true,'a money stop already up is not the owed close\'s to lower');
 // A fresh tick caps the wait at 60 s (quotes can outlast the trade session, so it never clears it); a stale one leaves it.
 const f=chart({positions:0});f.g_GoatCloseOwedNextMs=9e12;f.g_GoatCloseOwedBackoffMs=60000;f.step(FRI(10),FRI(12));assert.equal(f.g_GoatCloseOwedNextMs,9e12,'stale: stays');
 f.step(FRI(12,0,1),FRI(12,0,1));assert.deepEqual([f.g_GoatCloseOwedNextMs,f.g_GoatCloseOwedBackoffMs],[f.nowMs+60000,0],'fresh: capped at 60 s');
 f.step(FRI(12,0,2),FRI(12,0,2));assert.equal(f.g_GoatCloseOwedNextMs,f.nowMs+59000,'and a later fresh tick never pushes it out');
 ok();}

{// 4. A backlog over the open: no later tick has been processed, so the server day and the session table stand in for the first
 // quote; the wait still applies, the send does not need a fresh tick, and entries stay held until the feed catches up.
 const c=chart();c.g_GoatCloseOwed=true;c.g_GoatCloseOwedSince=FRI(21);
 c.step(FRI(23,0,0),MON(0,5,0));
 assert.ok(c.g_GoatCloseOwedQuoteMs>0,'the wait starts on the stale tick, the session open at the server clock');assert.equal(c.positions.length,2,'nothing is sent yet');
 c.step(FRI(23,0,1),MON(0,10,0),{ms:300000});
 assert.deepEqual(c.positions,[],'the guard never blocks an exit: sent on a stale tick');
 assert.equal(c.g_GoatCloseOwed,false,'and settled');
 assert.equal(c.GoatEntriesHeld(),true,'the feed is still behind: entries stay held');
 c.step(MON(0,10,1),MON(0,10,1));assert.equal(c.GoatEntriesHeld(),false,'caught up: they resume');
 // The quote's wait replaces any pacing left from Friday.
 const paced=chart();paced.g_GoatCloseOwed=true;paced.g_GoatCloseOwedSince=FRI(21);paced.g_GoatCloseOwedNextMs=9e12;paced.g_GoatCloseOwedBackoffMs=900000;paced.step(FRI(23),MON(0,5,0));assert.deepEqual([paced.g_GoatCloseOwedNextMs,paced.g_GoatCloseOwedBackoffMs],[0,0],'cleared');
 // Same day and a closed session: not the weekend's quote, and no fallback.
 const d=chart();d.g_GoatCloseOwed=true;d.g_GoatCloseOwedSince=FRI(21);d.step(FRI(21,30),FRI(23,30));assert.equal(d.g_GoatCloseOwedQuoteMs,0,'Friday\'s own tail never starts the wait');
 ok();}

{// 5. A restart: the state file carries the owed close, whatever the day; flag off ignores it.
 const a=chart();a.g_GoatCloseOwed=true;a.g_GoatCloseOwedSince=FRI(21);a.g_GoatCloseOwedStop=true;
 const text=a.GoatCloseOwedText();assert.equal(text,'close_owed=1\nclose_owed_since='+FRI(21)+'\nclose_owed_stop=1\nclose_owed_stop_time=0\n');
 const lines=text.trim().split('\n').map(l=>l.split('='));const keys=lines.map(l=>l[0]),values=lines.map(l=>l[1]);
 const b=chart();b.GoatCloseOwedRestore(keys,values);
 assert.deepEqual([b.g_GoatCloseOwed,b.g_GoatCloseOwedSince,b.g_GoatCloseOwedStop],[true,FRI(21),true],'restored');
 assert.equal(b.alerts.length,1,'loudly');
 const noFlag=chart({flag:0});noFlag.g_GoatCloseOwed=true;noFlag.g_GoatCloseOwedStop=true;noFlag.GoatCloseOwedRestore(keys,values);assert.deepEqual([noFlag.g_GoatCloseOwed,noFlag.g_GoatCloseOwedStop],[false,false],'flag off: ignored, and a re-init\'s kept globals cleared with it');assert.equal(noFlag.GoatCloseOwedText(),'','so the state file drops it');assert.match(noFlag.prints[0],/ignored/);
 const pause=chart({action:2});pause.GoatCloseOwedRestore(keys,values);assert.equal(pause.g_GoatCloseOwed,false,'Action_Friday no longer Close: ignored');
 const none=chart();none.GoatCloseOwedRestore(['stopout'],['1']);assert.equal(none.g_GoatCloseOwed,false,'no section: nothing owed');
 // Placement: restored in GoatStateRestore (not day-gated), the state file's text gains it in the flush, and adoption is untouched.
 const restore=bodyOf(main,'void GoatStateRestore()');
 assert.ok(restore.indexOf('GoatCloseOwedRestore(keys,values);')>restore.indexOf('Seq_Buy.StateRestore(keys,values)'),'after the sequences\' sections');
 assert.ok(!/GoatCloseOwed/.test(bodyOf(main,'void GoatStateDayRestore()')),'never day-gated');
 assert.ok(!/GoatCloseOwed|GoatFeed|GoatEntriesHeld/.test(bodyOf(main,'bool AdoptOpenPositions()')),'restart adoption reads none of it');
 assert.match(bodyOf(main,'void GoatStateFlush(const bool force=false)'),/string text=GoatStateText\(\);\n   text\+=GoatCloseOwedText\(\);/,'the flush compares and writes it');
 ok();}

{// 6. The guard: read at each real tick; over the threshold or unreadable holds entries; the threshold is the bench's 30 s.
 const c=chart({positions:0});
 assert.equal(c.GOAT_FEED_AGE_GUARD_S,30,'30 s');
 assert.equal(c.GoatEntriesHeld(),true,'before any tick: unknown, held');
 for(const [age,held] of [[0,false],[29,false],[30,false],[31,true],[50000,true]]){
  c.feed=FRI(12);c.step(FRI(12),FRI(12)+age);assert.equal(c.g_GoatFeedAgeS,age);assert.equal(c.GoatEntriesHeld(),held,'age '+age);
 }
 c.tickReadable=false;c.step(FRI(12),FRI(12));assert.deepEqual([c.g_GoatFeedAgeS,c.GoatEntriesHeld()],[-1,true],'an unreadable tick: held');c.tickReadable=true;
 c.step(FRI(12),FRI(12));assert.equal(c.GoatEntriesHeld(),false);
 c.g_GoatCloseOwed=true;assert.equal(c.GoatEntriesHeld(),true,'a Friday close owed holds entries');c.g_GoatCloseOwed=false;
 // It reads the chart symbol's newest tick, not TimeCurrent (another symbol's) and never a negative age.
 c.step(FRI(12,0,40),FRI(12,0,40),{tickTime:FRI(12,0,0)});assert.equal(c.g_GoatFeedAgeS,40,'this symbol\'s tick');
 c.step(FRI(12),FRI(11),{tickTime:FRI(12,0,5)});assert.equal(c.g_GoatFeedAgeS,0,'a tick ahead of the clock is age 0');
 // A timer run never moves the age: it is read from real ticks, and entries run only on them.
 c.step(FRI(12),FRI(12));c.g_GoatNoTickRun=true;c.tm_cur=FRI(13);c.GoatFeedGuardTick();c.g_GoatNoTickRun=false;assert.equal(c.g_GoatFeedAgeS,0,'a timer run leaves the age');assert.equal(c.g_GoatServerNow,FRI(13),'and takes the timer\'s clock');
 // One log line per change, at most once a minute.
 const l=chart({positions:0});l.step(FRI(12),FRI(13));assert.equal(l.prints.filter(p=>/feed_age_s=3600 guard_s=30/.test(p)).length,1,'said');
 for(let i=0;i<30;i++)l.step(FRI(12),FRI(13));assert.equal(l.prints.filter(p=>/GOAT feed guard/.test(p)).length,1,'once');
 l.step(FRI(13),FRI(13),{ms:1000});assert.equal(l.prints.filter(p=>/GOAT feed guard/.test(p)).length,1,'a change inside the minute waits');
 l.step(FRI(12),FRI(13),{ms:1000});l.step(FRI(12),FRI(13),{ms:61000});assert.equal(l.prints.filter(p=>/GOAT feed guard/.test(p)).length,1,'no change: no line, however long');
 l.step(FRI(13),FRI(13),{ms:1000});assert.ok(l.prints.some(p=>/back within guard_s=30/.test(p)),'a change after the minute says it');
 ok();}

{// 7. Placement: entries and adds pass the guard; no exit path reads it.
 const entry=bodyOf(main,'bool DashboardEntryAllowed(const int op)');
 assert.ok(/if\(GoatEntriesHeld\(\)\) return false;/.test(entry),'new sequences and promotions');
 const add=bodyOf(main,'   bool Add_Level(double Level_New)');
 assert.ok(add.indexOf('if(GoatEntriesHeld()) return false;')>=0 && add.indexOf('if(GoatEntriesHeld()) return false;')<add.indexOf('if(Level_Count<Max_Seq_Levels'),'adds, before anything is built');
 assert.equal((main.replace(/\/\/.*$/gm,'').match(/\bOpenPosition\(/g)||[]).length,2,'OpenPosition: one definition and one caller, inside Add_Level');
 assert.ok(add.includes('OpenPosition('),'so every order passes the guard');
 const users=[...main.replace(/\/\/.*$/gm,'').matchAll(/\bGoatEntriesHeld\(/g)].length;
 assert.equal(users,5,'the definition, the two gates, the hold watch and the status text: nothing else reads it');
 for(const [sig,label] of [['void CloseAllPositions(int OP,int magic=0)','closes'],['   void TrailingStoploss()','trailing'],['   bool EnforceSequenceMLPS(const string context)','MLPS'],['   void ClosePendingPump()','the close pump']])
  assert.ok(!/GoatEntriesHeld|g_GoatFeedAgeS/.test(bodyOf(main,sig)),label+' never read the guard');
 assert.ok(!/GoatEntriesHeld|g_GoatFeedAgeS/.test(bodyOf(TICK,'if(IsNewSecond())')),'nor the per-second block\'s stops');
 // OnTick stamps, then the guard stamps, before the body runs; the body's guard read precedes both blocks.
 assert.ok(bodyOf(main,'void OnTick()').replace(/\/\/.*$/gm,'').replace(/\s+/g,'').indexOf('GoatNoTickStamp();GoatFeedGuardStamp();GoatTickBody();')>=0);
 const i=s=>{const a=TICK.indexOf(s);assert.ok(a>=0,s);return a;};
 assert.ok(i('GoatFeedGuardTick();')<i('GoatFeedClockServer();')&&i('GoatFeedClockServer();')<i('if(IsNewDay())')&&i('if(IsNewDay())')<i('GoatFeedClockFeed();')&&i('GoatFeedClockFeed();')<i('if(IsNewMinute())'),'the day block alone on the server clock');
 const block=bodyOf(TICK,'if(IsNewSecond())').split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l));
 assert.match(block[0],/GoatFeedClockServer\(\);/,'the per-second block\'s first statement');assert.match(block[block.length-1],/GoatFeedClockFeed\(\);/,'and its last');
 assert.ok(!/\breturn\b/.test(bodyOf(TICK,'if(IsNewSecond())').replace(/\/\/.*$/gm,'')),'the block has no return that could leave the clock swapped');
 const tickNoIsNewDay=bodyOf(TICK,'if(IsNewDay())');assert.ok(!/\breturn\b/.test(tickNoIsNewDay.replace(/\/\/.*$/gm,'')),'nor the day block');
 ok();}

{// 8. The status file.
 const c=chart({positions:2});c.step(FRI(10),FRI(10,1,40));c.closeErrors=5;
 const text=c.GoatStatusText();const kv=Object.fromEntries(text.trim().split('\n').map(l=>l.split('=')));
 assert.equal(kv.feed_age_s,'100','the feed age');assert.equal(kv.server_time,String(FRI(10,1,40)));assert.equal(kv.tick_time,String(FRI(10)));
 assert.equal(kv.guard_s,'30');assert.equal(kv.entries_held,'1');assert.equal(kv.close_errors,'5','closeErrors surfaced');assert.equal(kv.close_owed,'0');assert.equal(kv.magic,'7');assert.equal(kv.symbol,'EURUSD');
 assert.equal(kv.positions_account,'2');assert.equal(kv.tsl_modifies,'3');assert.equal(kv.tsl_modify_errors,'2');assert.equal(kv.session_open,'1');assert.equal(kv.last_ontick_age_ms,'0');
 c.g_GoatStatusWrittenMs=0;c.GoatStatusFlush();assert.equal(c.writes.length,1,'written');assert.equal(c.writes[0][0],'GOAT\\State\\555\\7_EURUSD.status.txt','beside the state file, never over it');
 c.nowMs+=14999;c.GoatStatusFlush();assert.equal(c.writes.length,1,'at most every 15 s');c.nowMs+=1;c.GoatStatusFlush();assert.equal(c.writes.length,2);
 c.writeOk=false;c.nowMs+=15000;c.g_GoatStateFailed=false;c.GoatStatusFlush();c.nowMs+=15000;c.GoatStatusFlush();
 assert.equal(c.prints.filter(p=>/status file not written/.test(p)).length,1,'a failed write logs once');assert.equal(c.g_GoatStateFailed,false,'and freezes nothing, unlike the restart state file');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('GoatStatusFlush();'),'from the timer');
 const noMagic=chart();noMagic.MAGIC1=0;noMagic.GoatStatusFlush();assert.equal(noMagic.writes.length,0,'never before the chart has a magic');
 ok();}

{// 9. The daily stops' window: a day that reset on the server clock starts on it, and a stale end would miss today's deals.
 const c=chart({positions:0,dailyLoss:100});c.DStartLocalLoss=99999;c.step(FRI(10),FRI(14));
 assert.equal(c.DStartTime,FRI(14),'the day starts on the server clock');
 assert.deepEqual(c.history,[[FRI(14),FRI(14)]],'its deals are selected once, up to the server clock');
 const off=chart({flag:0,positions:0,dailyLoss:100});off.DStartLocalLoss=99999;off.step(FRI(10),FRI(14));
 assert.equal(off.DStartTime,FRI(10),'off: B49a');assert.deepEqual(off.history,[[FRI(10),FRI(10)]],'off: one select, on the feed\'s clock');
 ok();}

{// 10. The no-tick clock counts from the server clock at the last tick, so F4's timer is not hours late either.
 const c=chart({positions:0});c.feed=FRI(10);c.server=FRI(21,30);c.GoatFeedGuardStamp();assert.equal(c.g_GoatLastTickTime,FRI(21,30));
 const off=chart({flag:0,positions:0});off.feed=FRI(10);off.server=FRI(21,30);off.g_GoatLastTickTime=FRI(10);off.GoatFeedGuardStamp();assert.equal(off.g_GoatLastTickTime,FRI(10),'off: F4\'s clock');
 ok();}

// The production grid trailing on a stubbed basket: every level's modify answers as the fixture says.
const TRAIL=js(bodyOf(main,'   void TrailingStoploss()').replace(/\bCTrade Trade;/,'').replace(/C'\d+,\d+,\d+'/g,'0'));
function basket({flag=1,tester=0,dir=0,levels=3,answer=()=>[true,10009],tickload=0,timing=0}={}){
 const c=chart({flag,tester,timing,positions:0});
 c.Fix_TickLoad=tickload;c.dir=dir;c.OP_BUY=0;c.OP_SELL=1;c.Virtual=false;c.Traded=true;c.Adopted=false;c.AdoptSizes=true;c.TSL_Size_=1;c.Size_TSL=0.001;c.Level_TSL=0;c.Trailing=false;
 c.BiasRescueActive=false;c.BiasRescueBEProtected=false;c.BiasRescueSLPrice=0;c.bid=1.2;c.ask=1.2001;c._Point=0.00001;c._Digits=5;c.Level_Count=levels;c.g_TSLBuySkipped=0;c.g_TSLSellSkipped=0;c.Mode_Operation=0;
 c.TradeLevels=[];for(let i=0;i<levels;i++)c.TradeLevels.push({ticket:100+i});
 c.NormalizeDouble=(v,d)=>Number(v.toFixed(d));c.MathMax=Math.max;c.PositionSelectByTicket=()=>true;c.POSITION_SL=1;c.POSITION_TP=2;c.PositionGetDouble=k=>k===1?0:1.3;c.SymbolInfoInteger=()=>0;
 c.modifies=[];let last=[true,10009];
 c.Trade={SetExpertMagicNumber(){},PositionModify:(t,sl,tp)=>{c.modifies.push(t);last=answer(c.modifies.length-1,t);return last[0];},ResultRetcode:()=>last[1],ResultRetcodeDescription:()=>'desc'};
 vm.runInContext('function TrailingStoploss(){'+TRAIL+'}',c.__ctx);
 c.tick=()=>c.TrailingStoploss();
 return c;
}

{// 10b. A modify that returned true but was rejected: only counters and the log depend on it, and only under the flag.
 const reject=()=>[true,10016],fill=()=>[true,10009],refuse=()=>[false,10016];
 const on=basket({answer:reject});on.tick();
 assert.equal(on.TSLmodifyErrors,5,'on: three rejections counted on top of the fixture\'s two');
 assert.equal(on.prints.filter(p=>/TSL BUY modify rejected though it returned true: ticket=10\d ret=10016 \(desc\)/.test(p)).length,3,'and each logged with its retcode');
 const off=basket({flag:0,answer:reject});off.tick();
 assert.equal(off.TSLmodifyErrors,2,'off: B49a books them as successes');assert.equal(off.prints.length,0,'silently');
 const tester=basket({tester:1,answer:reject});tester.tick();assert.equal(tester.TSLmodifyErrors,2,'the tester: B49a');
 const bool=basket({answer:refuse});bool.tick();
 assert.equal(bool.TSLmodifyErrors,5,'a false answer is counted once, not twice');
 assert.equal(bool.prints.filter(p=>/rejected though/.test(p)).length,0,'and logged by the existing line alone');
 assert.equal(bool.prints.filter(p=>/TSL BUY modify failed/.test(p)).length,3);
 const good=basket({answer:fill});good.tick();assert.deepEqual([good.TSLmodifyErrors,good.prints.length],[2,0],'an accepted modify changes nothing');
 const sell=basket({dir:1,answer:reject});sell.tick();assert.equal(sell.TSLmodifyErrors,5,'the sell side');assert.ok(sell.prints.some(p=>/TSL SELL modify rejected/.test(p)));
 // Nothing but the counters depends on the answer: the sequence's stop state is the same whether it was accepted or rejected.
 assert.deepEqual([on.Level_TSL,on.Trailing,on.TSLmodifieds,on.modifies],[good.Level_TSL,good.Trailing,good.TSLmodifieds,good.modifies],'the same stop state, attempts and tickets');
 assert.equal(on.Trailing,true);
 // The fourth site, TP/SL: same rule, placed after its modify.
 const lock=main.slice(main.indexOf('int tp_errors_before=TPmodifyErrors;'),main.indexOf('"TP/SL",Trade.ResultRetcodeDescription())) TPmodifyErrors++;'));
 assert.ok(/PositionModify\(TradeLevels\[i\]\.ticket,Level_SL_,Level_TP_\)/.test(lock),'the TP/SL modify sits between the snapshot and the check');
 assert.ok(/GoatModifyRejected\(Trade\.ResultRetcode\(\),TPmodifyErrors!=tp_errors_before/.test(lock),'and the check reads its own counter');
 // The close: a rejection that returned true is counted and reaches F3's log; the owed logic reads positions, never the bool.
 const c=chart();c.retcode=10018;c.closeReturnsTrue=true;c.step(FRI(21,0,30),FRI(21,0,30));
 assert.equal(c.closeErrors,2,'on: counted');assert.deepEqual(c.closeLogged,[[12,10018],[11,10018]],'and logged through F3\'s failure log');assert.equal(c.g_GoatCloseOwed,true,'and owed: the position is still open');
 const o=chart({flag:0});o.retcode=10018;o.closeReturnsTrue=true;o.step(FRI(21,0,30),FRI(21,0,30));assert.equal(o.closeErrors,0,'off: B49a books it as closed');
 assert.equal(c.GoatCloseRejected(10009,false),false);assert.equal(c.GoatCloseRejected(10010,false),false,'a partial close was accepted');assert.equal(c.GoatCloseRejected(10008,false),false);assert.equal(c.GoatCloseRejected(10018,true),false,'already counted');
 ok();}

{// 11. Timing is off by default and, off, reads no clock; the tester never runs it, flag on or not.
 assert.match(header,/^sinput\s+ENUM_GOAT_FIX\s+Diag_TickTiming\s*=\s*GoatFix_Off;/m,'off by default');
 for(const [timing,tester,label] of [[0,0,'off, live'],[1,1,'on, tester']]){
  const c=chart({timing,tester,flag:0});c.GetMicrosecondCount=()=>{throw new Error('the clock is read: '+label);};
  assert.equal(c.GoatTimingStart(),0,label);c.GoatTimingSlot(0,0);c.GoatTimingTick(0);c.GoatTimingFlush();
  assert.equal(c.GoatTimingText(),'',label+': nothing in the status file');assert.equal(c.GoatStatusLive(),false,label+': no status file');
  assert.equal(c.g_GoatTimingTicks,0);assert.equal(c.prints.length,0,label+': no log line');
 }
 ok();}

{// 12. On: it counts, writes the status file with the guard off, logs once a minute, and leaves trading alone.
 const c=chart({timing:1,flag:0});
 c.us=1000;let t=c.GoatTimingStart();assert.equal(t,1000);
 c.us=1400;c.GoatTimingSlot(0,t);c.us=1500;c.GoatTimingTick(t);
 c.us=2000;t=c.GoatTimingStart();c.us=2100;c.GoatTimingTick(t);
 assert.deepEqual([c.g_GoatTimingTicks,c.g_GoatTimingTickUS,c.g_GoatTimingTickMaxUS],[2,600,500],'ticks, total and max');
 assert.deepEqual([c.g_GoatTimingSlotUS[0],c.g_GoatTimingSlotCalls[0]],[400,1],'a section');
 assert.equal(c.g_GoatTimingWindowUS,600,'a section inside a tick is not counted twice');
 t=(c.us=3000,c.GoatTimingStart());c.us=3250;c.GoatTimingSlot(6,t);assert.equal(c.g_GoatTimingWindowUS,850,'OnTimer is outside OnTick, so it counts');
 assert.equal(c.GoatStatusLive(),true,'the status file is written for it with the guard off');
 c.feed=FRI(10);c.server=FRI(10,0,40);c.tickTime=FRI(10);
 const kv=Object.fromEntries(c.GoatStatusText().trim().split('\n').map(l=>l.split('=')));
 assert.deepEqual([kv.timing_ticks,kv.timing_tick_us,kv.timing_tick_max_us,kv.timing_second_us,kv.timing_second_calls,kv.timing_timer_us],['2','600','500','400','1','250'],'in the file');
 assert.deepEqual([kv.timing_minute_calls,kv.timing_trailing_calls,kv.timing_signal_calls,kv.timing_exits_calls,kv.timing_sequence_calls],['0','0','0','0','0'],'every section named');
 assert.equal(kv.feed_age_s,'40','the feed age, measured');assert.equal(kv.feed_guard,'0','and not enforced');assert.equal(kv.entries_held,'0','the guard stays off');
 // One line a minute; the window then restarts.
 c.nowMs=1000000;c.GoatTimingFlush();assert.equal(c.prints.length,0,'the first call opens the window');
 c.g_GoatTimingWindowUS=600000;c.g_GoatTimingWindowTicks=7;c.nowMs+=59999;c.GoatTimingFlush();assert.equal(c.prints.length,0,'inside the minute');
 c.nowMs+=1;c.GoatTimingFlush();assert.equal(c.prints.length,1);
 assert.match(c.prints[0],/^GOAT tick timing: symbol=EURUSD window_ms=60000 ticks=7 busy_pct=1\.00 tick_max_us=500 feed_age_s=40 positions_account=2$/);
 assert.deepEqual([c.g_GoatTimingWindowUS,c.g_GoatTimingWindowTicks,c.g_GoatTimingWindowMs],[0,0,c.nowMs],'the window restarts');
 // A backlog timeline with timing on and the guard off is the flags-off trace, tick for tick.
 const trace=d=>{const out=[];for(const [f,s] of [[FRI(10),FRI(21,0,30)],[FRI(10,0,1),SAT(1)],[FRI(10,0,2),MON(1)],[MON(1,0,1),MON(1,0,1)]]){d.step(f,s);out.push([d.StopOut_Flag,d.sends.length,d.Active,d.InActive,d.tm_cur,JSON.stringify(d.stm_cur)]);}return out;};
 assert.deepEqual(trace(chart({flag:0,timing:1})),trace(chart({flag:0})),'it never changes a trade');
 ok();}

{// 13. Read-only by construction, and each section is measured once, where it runs.
 for(const slot of [-2,-1,7,8]){const t=chart({timing:1,flag:0});t.us=100;t.GoatTimingSlot(slot,50);assert.deepEqual([...t.g_GoatTimingSlotCalls],Array(7).fill(0),'a slot out of range writes nothing: '+slot);}
 const block=main.slice(main.indexOf('// B49b:begin lag-t'),main.indexOf('// B49b:end lag-t')).replace(/\/\/.*$/gm,'');
 assert.ok(!/OrderSend|PositionModify|PositionClose|PositionSelect|PositionGetTicket|HistorySelect|FileOpen|GoatStateWrite|CloseAllPositions|StopOut_Flag|Add_Level|End_Sequence|GlobalVariableSet/.test(block),'no trade, selection, file or stop call');
 for(const m of block.replace(/"(?:\\.|[^"\\\n])*"/g,'""').matchAll(/(?:^|[;{\s])([A-Za-z_]\w*)(?:\[\w+\])?\s*(?:\+=|=(?!=)|\+\+)/gm)){
  const name=m[1];
  assert.ok(/^g_GoatTiming/.test(name)||['spent_us','now_ms','window_ms','timing_text','s','slot_names'].includes(name)||/^(ulong|string|int)$/.test(name),'it writes only its own counters: '+name);
 }
 const on=(sig,text)=>{const b=bodyOf(TICK,sig);assert.ok(b.includes(text),sig+': '+text);};
 const once=text=>assert.equal(main.split(text).length-1,1,'once: '+text);
 for(const [slot,name] of [[0,'timing_second'],[1,'timing_minute'],[2,'timing_trailing'],[3,'timing_signal'],[4,'timing_exits'],[5,'timing_sequence']]){
  once('ulong '+name+'=GoatTimingStart();');once('GoatTimingSlot('+slot+','+name+');');
  assert.ok(TICK.includes('ulong '+name+'=GoatTimingStart();')&&TICK.indexOf('ulong '+name+'=GoatTimingStart();')<TICK.indexOf('GoatTimingSlot('+slot+','+name+');'),name+' opens before it closes');
 }
 on('if(IsNewSecond())','GoatTimingSlot(0,timing_second);');on('if(IsNewMinute())','GoatTimingSlot(1,timing_minute);');on('if(CheckTrailingLockTPNow())','GoatTimingSlot(2,timing_trailing);');on('if( CheckSignalNow() )','GoatTimingSlot(3,timing_signal);');
 const tickFn=bodyOf(main,'void OnTick()').replace(/\/\/.*$/gm,'').replace(/\s+/g,'');
 assert.ok(tickFn.startsWith('ulongtiming_tick=GoatTimingStart();')&&tickFn.endsWith('GoatTimingTick(timing_tick);'),'OnTick is timed whole');
 const timerFn=bodyOf(main,'void OnTimer(void)').replace(/\/\/.*$/gm,'').replace(/\s+/g,'');
 assert.equal(timerFn,'ulongtiming_timer=GoatTimingStart();GoatTimerBody();GoatTraceTimer();GoatTimingSlot(6,timing_timer);','OnTimer too');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('GoatTimingFlush();'),'the log line from the timer');
 // No early return between a section's open and close, or the section would silently lose its time.
 for(const sig of ['if(IsNewSecond())','if(IsNewMinute())','if(CheckTrailingLockTPNow())','if( CheckSignalNow() )'])assert.ok(!/\breturn\b/.test(bodyOf(TICK,sig).replace(/\/\/.*$/gm,'')),sig+' has no return');
 ok();}

{// 14. Off, or on in the tester: no hold, no clock read, every modify sent.
 assert.match(header,/^sinput\s+ENUM_GOAT_FIX\s+Fix_TickLoad\s*=\s*GoatFix_Off;/m,'off by default');
 for(const [tickload,tester,label] of [[0,0,'off, live'],[1,1,'on, tester'],[0,1,'off, tester']]){
  const c=chart({tickload,tester,flag:0});c.GetTickCount64=()=>{throw new Error('the clock is read: '+label);};
  for(let s=0;s<6;s++)for(let i=0;i<3;i++)assert.equal(c.GoatTickLoadHold(s),false,label);
  c.g_GoatTrailTicket=bounded([100]);c.g_GoatTrailSide=bounded([0]);c.g_GoatTrailFails=bounded([9]);c.g_GoatTrailNextMs=bounded([9e15]);assert.equal(c.GoatTrailHeld(100),false,label+': a count is never read');
  c.GoatTrailNote(0,100,10016);c.GoatTrailNote(0,101,10016);assert.deepEqual([[...c.g_GoatTrailTicket],[...c.g_GoatTrailFails]],[[100],[9]],label+': nothing counted');
  c.GoatTrailReset(0);c.GoatTrailReset(-2);assert.deepEqual([...c.g_GoatTrailTicket],[100],label+': nothing reset');
  const b=basket({tickload,tester,flag:0,levels:50,answer:()=>[false,10016]});for(let i=0;i<3;i++)b.tick();assert.equal(b.modifies.length,150,label+': every level, every pass, as the base');
 }
 const trace=d=>{const out=[];for(const [f,s] of [[FRI(10),FRI(21,0,30)],[FRI(10,0,1),SAT(1)],[FRI(10,0,2),MON(1)],[MON(1,0,1),MON(1,0,1)]]){d.step(f,s,{ms:1});out.push([d.StopOut_Flag,d.sends.length,d.Active,d.InActive,d.tm_cur,JSON.stringify(d.stm_cur)]);}return out;};
 assert.deepEqual(trace(chart({flag:0,tickload:1,tester:1})),trace(chart({flag:0})),'the tester, flag on: the flags-off trace at any tick spacing');
 ok();}

{// 15. Truly bounded: however many ticks and feed seconds arrive, the account scan runs at most once per real second.
 const storm=tickload=>{const c=chart({flag:0,tickload});let scans=0;c.PositionsTotal=()=>{scans++;return c.positions.length;};
  for(let i=0;i<3000;i++)c.step(FRI(10)+i,FRI(10)+i,{ms:1});   // 3,000 ticks, each a new feed second, in 3 real seconds: a backlog
  return scans;};
 assert.equal(storm(0),3000,'off: once per feed second: every tick');
 assert.equal(storm(1),3,'on: once per real second, whatever the tick rate');
 assert.equal(chart({flag:0,tickload:1}).GOAT_TICK_LOAD_HOLD_MS,1000,'a second');
 // A hold leaves the second new, so the next tick after it runs the block; the slots are independent.
 const c=chart({flag:0,tickload:1});assert.equal(c.GoatTickLoadHold(0),false);assert.equal(c.GoatTickLoadHold(0),true,'held');assert.equal(c.GoatTickLoadHold(1),false,'another slot');
 c.nowMs+=999;assert.equal(c.GoatTickLoadHold(0),true);c.nowMs+=1;assert.equal(c.GoatTickLoadHold(0),false,'a second later');
 // F4's timer run is never held: it is the path that catches a chart with no ticks.
 const t=chart({flag:0,tickload:1});t.GoatTickLoadHold(0);t.g_GoatNoTickRun=true;assert.equal(t.IsNewSecond(),true,'a no-tick run goes through');
 ok();}

{// 16. What changes with it on: a stop waits for the next real second; it is delayed, never lost.
 const off=chart({flag:0,minLevel:9000}),on=chart({flag:0,tickload:1,minLevel:9000});
 for(const c of [off,on])c.step(FRI(10,0,1),FRI(10,0,1),{ms:5000});
 for(const c of [off,on]){c.equity=8000;c.step(FRI(10,0,2),FRI(10,0,2),{ms:10});}
 assert.deepEqual([off.StopOut_Flag,off.sends.length],[true,2],'off: the equity stop fires on this tick\'s feed second');
 assert.deepEqual([on.StopOut_Flag,on.sends.length],[false,0],'on: 10 ms after the last evaluation, it waits (a declared change)');
 on.step(FRI(10,0,3),FRI(10,0,3),{ms:1000});assert.deepEqual([on.StopOut_Flag,on.sends.length],[true,2],'and fires at the next real second: delayed, never lost');
 ok();}

{// 17. The grid's trailing back-off, per ticket.
 const reject=()=>[false,10016];
 // One refused pass on a big basket trips nothing; five on a ticket do.
 const big=basket({tickload:1,flag:0,levels:50,answer:reject});big.tick();
 assert.equal(big.modifies.length,50,'one refused pass: every level was tried');for(let t=100;t<150;t++)assert.equal(big.GoatTrailHeld(t),false,'and none is held');
 for(let i=0;i<4;i++)big.tick();assert.equal(big.modifies.length,250,'five passes');assert.equal(big.GoatTrailHeld(100),true,'the fifth holds');
 big.tick();assert.equal(big.modifies.length,250,'then the pass waits');assert.equal(big.Trailing,true,'the sequence\'s own trailing level still moves');
 // The schedule, on one ticket: 1, 5, 30, then 60 s steady.
 const c=basket({tickload:1,flag:0,levels:1,answer:reject});for(let i=0;i<5;i++)c.tick();assert.equal(c.modifies.length,5);
 const at=[];let last=5;const start=c.nowMs;
 for(let s=1;s<=300;s++){c.nowMs=start+s*1000;c.tick();if(c.modifies.length>last){at.push(s);assert.equal(c.modifies.length-last,1,'one attempt a window');last=c.modifies.length;}}
 assert.deepEqual(at,[1,6,36,96,156,216,276],'1, 5, 30, then 60 s steady');
 assert.equal(c.modifies.length,12,'bounded: five, then a request a minute per stuck ticket (09 sent 2,610 an hour)');
 assert.ok(c.prints.some(p=>/GOAT trail back-off: ticket=100 symbol=EURUSD consecutive=5 retcode=10016 wait_s=1/.test(p)),'each attempt\'s wait is logged');
 // A persistently refused first ticket never blocks the healthy levels behind it.
 const s=basket({tickload:1,flag:0,levels:4,answer:(n,t)=>t===100?[false,10016]:[true,10009]});for(let i=0;i<20;i++)s.tick();
 assert.equal(s.modifies.filter(t=>t===100).length,5,'the refused ticket stops after five');for(const t of [101,102,103])assert.equal(s.modifies.filter(x=>x===t).length,20,'the healthy level goes every pass: '+t);
 assert.deepEqual([...s.g_GoatTrailTicket],[100],'only the refused ticket has a row');
 // A rejection that returned true counts; only a real refusal does.
 const t=basket({tickload:1,flag:0,levels:1,answer:()=>[true,10016]});for(let i=0;i<5;i++)t.tick();assert.equal(t.GoatTrailHeld(100),true,'true on a rejection is a refusal');
 const noRefusal=(ret)=>{const n=basket({tickload:1,flag:0,levels:1,answer:()=>[true,ret]});for(let i=0;i<9;i++)n.tick();return n;};
 for(const ret of [10025,10008,10010,10009]){const n=noRefusal(ret);assert.equal(n.modifies.length,9,'never held: '+ret);assert.deepEqual([...n.g_GoatTrailTicket],[],'no row: '+ret);}
 for(const ret of [10006,10016,10029,10018,10017,10004,10024]){const n=noRefusal(ret);assert.equal(n.modifies.length,5,'a refusal: '+ret);}
 // NO_CHANGES and DONE clear a ticket; PLACED and DONE_PARTIAL leave it as it was.
 for(const [ret,row] of [[10009,0],[10025,0],[10008,3],[10010,3]]){const u=chart({flag:0,tickload:1});for(let i=0;i<3;i++)u.GoatTrailNote(0,100,10016);u.GoatTrailNote(0,100,ret);assert.equal(u.g_GoatTrailFails[0],row,'the count after '+ret);}
 // One DONE clears a held ticket, said; its row is reused, so the table only holds what is refused.
 let accept=false;const r=basket({tickload:1,flag:0,levels:1,answer:()=>accept?[true,10009]:[false,10016]});for(let i=0;i<5;i++)r.tick();
 accept=true;r.nowMs+=1000;r.tick();assert.equal(r.GoatTrailHeld(100),false,'cleared');assert.deepEqual([...r.g_GoatTrailTicket],[0],'the row is freed');assert.ok(r.prints.some(p=>/recovered ticket=100/.test(p)),'said');
 r.GoatTrailNote(0,200,10016);assert.deepEqual([...r.g_GoatTrailTicket],[200],'and reused');
 // Under the limit nothing waits; a success resets the run; the tickets and the sides are independent; an ended sequence starts clean.
 const u=chart({flag:0,tickload:1});for(let i=0;i<4;i++)u.GoatTrailNote(0,100,10016);assert.equal(u.GoatTrailHeld(100),false,'four refusals: no wait');
 u.GoatTrailNote(0,100,10009);u.GoatTrailNote(0,100,10016);assert.equal(u.g_GoatTrailFails[u.GoatTrailSlot(100)],1,'consecutive');
 for(let i=0;i<5;i++){u.GoatTrailNote(1,200,10016);u.GoatTrailNote(0,300,10016);}assert.deepEqual([u.GoatTrailHeld(100),u.GoatTrailHeld(200),u.GoatTrailHeld(300)],[false,true,true],'per ticket');
 u.GoatTrailReset(1);assert.deepEqual([u.GoatTrailHeld(200),u.GoatTrailHeld(300)],[false,true],'a reset clears its own side only');
 const end=bodyOf(main,'   void End_Sequence(string desc)');assert.ok(end.indexOf('if(!Virtual) GoatTrailReset(dir);')>end.indexOf('if(EndDeferredUntilFlat(desc)) return;'),'an ended real sequence resets its side');
 // MLPS and the deferred-close pump: bounded on the tick path; an add still checks; the production bodies, on a stub.
 const mlps=js(bodyOf(main,'   bool EnforceSequenceMLPS(const string context)'));
 const m=basket({tickload:1,flag:0});m.Sequence_MLPS_Hard_Close=true;m.Risk=100;m.Active=true;let walks=0;m.CurrentSequencePL=()=>{walks++;return 0;};m.g_PerformanceProfileTester=false;
 vm.runInContext('function EnforceSequenceMLPS(context){'+mlps+'}',m.__ctx);
 for(let i=0;i<100;i++)m.EnforceSequenceMLPS('tick');assert.equal(walks,1,'the tick path: once in the second');
 m.EnforceSequenceMLPS('add level');assert.equal(walks,2,'an add always checks');
 m.nowMs+=1000;m.EnforceSequenceMLPS('tick');assert.equal(walks,3,'the next second');
 const mo=basket({tickload:0,flag:0});mo.Sequence_MLPS_Hard_Close=true;mo.Risk=100;mo.Active=true;let w0=0;mo.CurrentSequencePL=()=>{w0++;return 0;};mo.g_PerformanceProfileTester=false;
 vm.runInContext('function EnforceSequenceMLPS(context){'+mlps+'}',mo.__ctx);for(let i=0;i<100;i++)mo.EnforceSequenceMLPS('tick');assert.equal(w0,100,'off: every tick');
 const pump=js(bodyOf(main,'   void ClosePendingPump()'));
 const scan=tickload=>{const p=basket({tickload,flag:0});p.Active=true;p.ClosePendingReason='x';p.ClosePendingTried=0;let n=0;p.FindNumberOfPositions=()=>{n++;return 1;};p.CloseAllPositions=()=>{};
  vm.runInContext('function ClosePendingPump(){'+pump+'}',p.__ctx);for(let i=0;i<100;i++)p.ClosePendingPump();return n;};
 assert.ok(scan(0)>=100,'off: the account walked every tick while a close is deferred');assert.ok(scan(1)<=2,'on: at most once in the second');
 ok();}

{// 18. A never needs B, B never needs A, and they compose.
 const blockOf=name=>main.slice(main.indexOf('// B49b:begin '+name),main.indexOf('// B49b:end '+name)).replace(/\/\/.*$/gm,'');
 for(const name of ['lag-a','lag-t'])assert.ok(!/TickLoad|GoatTrail/.test(blockOf(name)),name+' reads nothing of group B');
 assert.ok(!/FeedGuard|ServerClock|TimeTradeServer|g_GoatServerNow|GoatEntriesHeld|GoatCloseOwed|Timing/.test(blockOf('lag-b')),'group B reads nothing of group A or the timing');
 const noB=line=>!/GoatTickLoad|GoatTrail/.test(line);
 for(const line of main.split('\n'))if(/\(LAG-A\)/.test(line))assert.ok(noB(line),'no group A line calls group B: '+line.trim());
 for(const line of main.split('\n'))if(/\(LAG-B\)/.test(line))assert.ok(!/GoatFeed|GoatEntriesHeld|GoatCloseOwed|g_GoatServerNow/.test(line),'no group B line calls group A: '+line.trim());
 // B alone never reads the server clock; a hold never reaches the guard.
 const onlyB=chart({flag:0,tickload:1});onlyB.TimeTradeServer=()=>{throw new Error('group B reads the server clock');};onlyB.step(FRI(10),FRI(10));assert.equal(onlyB.GoatEntriesHeld(),false);
 // A's whole weekend with B on, at ticks a second apart: the same owed close, sent at the first tradable tick.
 const c=chart({tickload:1});c.retcode=10018;c.step(FRI(21,0,30),FRI(21,0,30));assert.equal(c.g_GoatCloseOwed,true,'owed');
 c.step(FRI(21,0,41),SAT(0,0,5));assert.equal(c.StopOut_Flag,false,'the day reset');assert.equal(c.g_GoatCloseOwed,true);
 c.retcode=10009;c.step(MON(0,0,6),MON(0,0,6));assert.ok(c.g_GoatCloseOwedQuoteMs>0,'the first quote');c.step(MON(0,5,7),MON(0,5,7),{ms:300000});assert.deepEqual([c.positions,c.g_GoatCloseOwed,c.StopOut_Flag],[[],false,false],'and settled');
 // The guard and the server clock hold on ticks B holds back: the guard is read before any block.
 const g=chart({tickload:1,positions:0});g.step(FRI(12),FRI(13),{ms:1});g.step(FRI(12),FRI(13),{ms:1});assert.equal(g.GoatEntriesHeld(),true,'held, on a tick inside the second');
 ok();}

{// 19. Clock sync: nothing runs until the first real tick after connect. TimeTradeServer has no known offset before it.
 const boot=({trueTime,unsynced,lastTick,hourEnd=21})=>{const c=chart({hourEnd});c.dayStamps=[];c.GoatStateLive=()=>true;c.GoatStateDayRestore=()=>c.dayStamps.push(Math.floor(c.tm_cur/86400));
  c.retcode=10018;c.feed=lastTick;c.server=unsynced;c.tickTime=lastTick;c.trueTime=trueTime;
  c.GoatFeedInitMark(false);c.GoatFeedGuardStamp();c.TickBody();c.GoatFeedInitMark(true);return c;};   // OnInit's own OnTick() call
 // A restart in the first 2 h of a server day, UTC+2: the unsynced clock reads yesterday. The day must not be stamped from it.
 const r=boot({trueTime:at(9,29,0,30),unsynced:at(9,28,22,30),lastTick:at(9,28,21,0)});
 assert.deepEqual(r.dayStamps,[],'OnInit\'s tick stamps no day, so the state file\'s day section and its latched stop wait');
 assert.equal(r.g_GoatFeedSynced,false);
 r.step(at(9,29,0,30),at(9,29,0,30));assert.deepEqual(r.dayStamps,[Math.floor(at(9,29,0,30)/86400)],'the first real tick stamps the true server day, and restores it');
 assert.equal(r.g_GoatFeedSynced,true);
 // A true Saturday 00:00-02:00, UTC+2: the unsynced clock reads Friday night. No Friday close may arm from it.
 const s=boot({trueTime:SAT(1),unsynced:FRI(23),lastTick:FRI(21,59,58)});
 assert.deepEqual([s.sends,s.StopOut_Flag,s.g_GoatCloseOwed,s.alerts],[[],false,false,[]],'no close, no stop, nothing owed');
 const t=s;t.nowMs+=300000;t.GoatFeedSyncWatch();assert.equal(t.g_GoatFeedSynced,false,'and no tick all weekend keeps it so');
 // A negative-offset server, UTC-5: the unsynced clock reads ahead, past the session end. Nothing closes early.
 const n=boot({trueTime:FRI(18),unsynced:FRI(23),lastTick:FRI(17,59,59)});assert.deepEqual([n.sends,n.StopOut_Flag,n.g_GoatCloseOwed],[[],false,false],'negative offset');
 n.step(FRI(18),FRI(18));assert.deepEqual([n.sends,n.StopOut_Flag],[[],false],'the first real tick reads the true clock: inside the session');
 // A UTC broker reads TTS minus TimeGMT of 0: the gate never asks.
 const u=chart();u.TimeGMT=()=>{throw new Error('the gate reads TimeGMT');};u.step(FRI(10),FRI(10));assert.equal(u.g_GoatFeedSynced,true,'a UTC broker syncs on its first real tick');
 assert.ok(!/TimeGMT/.test(main.slice(main.indexOf('// B49b:begin lag-a'),main.indexOf('// B49b:end lag-a')).replace(/\/\/.*$/gm,'')),'group A never reads TimeGMT');
 // A real tick while disconnected is not a sync; a disconnect re-arms it, and the next real tick ends it.
 const d=chart();d.TerminalInfoInteger=()=>0;d.GoatFeedGuardStamp();assert.equal(d.g_GoatFeedSynced,false,'disconnected');d.TerminalInfoInteger=()=>1;
 d.step(FRI(10),FRI(10));assert.equal(d.g_GoatFeedSynced,true);d.TerminalInfoInteger=()=>0;d.GoatFeedSyncWatch();assert.equal(d.g_GoatFeedSynced,false,'a disconnect loses the clock');d.TerminalInfoInteger=()=>1;d.GoatFeedSyncWatch();assert.equal(d.g_GoatFeedSynced,false,'reconnecting is not enough');
 d.step(FRI(10,0,1),FRI(10,0,1));assert.equal(d.g_GoatFeedSynced,true,'the next real tick is');
 // Flag off, or the tester: never gated.
 for(const [flag,tester] of [[0,0],[1,1]]){const o=chart({flag,tester});assert.equal(o.GoatFeedUnsynced(),false);}
 // Placement: first in the body, and OnInit brackets its own call.
 const lines=TICK.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l));assert.match(lines[2],/if\(GoatFeedUnsynced\(\)\) return;/,'right after the mode returns, before the clock');
 const init=bodyOf(main,'int OnInit()');assert.ok(init.indexOf('GoatFeedInitMark(false);')>=0&&init.indexOf('GoatFeedInitMark(false);')<init.indexOf('OnTick(); Sleep(50);')&&init.indexOf('OnTick(); Sleep(50);')<init.indexOf('GoatFeedInitMark(true);'),'OnInit brackets its own OnTick()');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('GoatFeedSyncWatch();'),'the timer watches the connection');
 ok();}

{// 20. A slow clock is provable and holds; a fast one is only reported. Raw skew, whatever GoatServerClock's floor hides.
 const c=chart({positions:0});
 c.step(FRI(12),FRI(12));assert.equal(c.g_GoatClockSkewS,0);
 c.step(FRI(12),FRI(12)-10);assert.equal(c.prints.filter(p=>/GOAT clock:/.test(p)).length,0,'-10 s: within tolerance');
 c.step(FRI(12),FRI(12)-11);assert.equal(c.g_GoatClockSkewS,-11);assert.equal(c.prints.filter(p=>/GOAT clock:/.test(p)).length,1,'below -10 s: logged');
 for(let i=0;i<5;i++)c.step(FRI(12),FRI(12)-11);assert.equal(c.prints.filter(p=>/GOAT clock:/.test(p)).length,1,'once');
 assert.equal(c.GoatEntriesHeld(),false,'not held at -11');
 c.step(FRI(12),FRI(12)-30);assert.equal(c.g_GoatClockSlowSinceMs,0,'-30 is not below -30');
 c.step(FRI(12),FRI(12)-31);const since=c.g_GoatClockSlowSinceMs;assert.ok(since>0);assert.equal(c.GoatEntriesHeld(),false,'not sustained yet');
 c.step(FRI(12),FRI(12)-31,{ms:59999});assert.equal(c.GoatEntriesHeld(),false,'59.999 s');
 c.step(FRI(12),FRI(12)-31,{ms:1});assert.deepEqual([c.g_GoatClockSlowHeld,c.GoatEntriesHeld()],[true,true],'sustained for a minute: entries held, and the feed age alone reads 0');
 assert.equal(c.g_GoatFeedAgeS,0,'the floor hid it from the age');
 c.step(FRI(12),FRI(12)-5);assert.deepEqual([c.g_GoatClockSlowHeld,c.GoatEntriesHeld()],[false,false],'recovered');
 c.step(FRI(12),FRI(12)-31);c.step(FRI(12),FRI(12)-5);c.step(FRI(12),FRI(12)-31,{ms:61000});assert.equal(c.g_GoatClockSlowHeld,false,'a break restarts the minute');
 // A timer run reads none of it.
 const t=chart({positions:0});t.step(FRI(12),FRI(12));t.g_GoatNoTickRun=true;t.tm_cur=FRI(12)-99;t.server=FRI(12)-99;t.GoatFeedGuardTick();t.g_GoatNoTickRun=false;assert.equal(t.g_GoatClockSkewS,0,'a timer run never moves the skew');
 // A fast clock: reported steady, never refused on, since it cannot be told from lag.
 const f=chart({positions:0});for(let i=0;i<20;i++)f.step(FRI(12,0,i),FRI(12,0,i)+25,{tickTime:FRI(12,0,i)});
 assert.equal(f.GoatEntriesHeld(),false,'25 s ahead: not refused');
 let kv=Object.fromEntries(f.GoatStatusText().trim().split('\n').map(l=>l.split('=')));
 assert.deepEqual([kv.clock_skew_s,kv.clock_skew_floor_s,kv.clock_slow_held,kv.clock_synced],['25','25','0','1'],'steady positive: the floor says so');
 // A backlog's skew is not steady: one fresh tick drops the floor, so the two read apart.
 f.step(FRI(12,1,0),FRI(12,1,0));kv=Object.fromEntries(f.GoatStatusText().trim().split('\n').map(l=>l.split('=')));assert.equal(kv.clock_skew_floor_s,'0','the lowest since the last write');
 f.step(FRI(12,1,1),FRI(12,1,1)+25,{tickTime:FRI(12,1,1)});kv=Object.fromEntries(f.GoatStatusText().trim().split('\n').map(l=>l.split('=')));assert.deepEqual([kv.clock_skew_floor_s,kv.clock_skew_s],['0','25'],'a later higher reading leaves the floor');
 f.g_GoatStatusWrittenMs=0;f.GoatStatusFlush();assert.equal(f.g_GoatClockFloorSet,false,'each write restarts it');kv=Object.fromEntries(f.GoatStatusText().trim().split('\n').map(l=>l.split('=')));assert.equal(kv.clock_skew_floor_s,'na','no reading yet');
 f.writeOk=false;f.step(FRI(12,1,1),FRI(12,1,1));f.nowMs+=15000;f.GoatStatusFlush();assert.equal(f.g_GoatClockFloorSet,true,'a failed write keeps it');
 // The status field is raw: a PC behind reads negative though the clock is floored.
 const s=chart({positions:0});s.step(FRI(12),FRI(12)-40);kv=Object.fromEntries(s.GoatStatusText().trim().split('\n').map(l=>l.split('=')));assert.equal(kv.clock_skew_s,'-40','raw');assert.equal(kv.server_time,String(FRI(12)),'floored');
 ok();}

{// 21. A hold that starts ends the virtual candidates, so none is promoted on an old signal when it lifts.
 const run=flag=>{const c=chart({flag,positions:0});c.Seq_Buy_Virtual={Active:true,End_Sequence(d){this.Active=false;c.ended.push('B:'+d);}};c.Seq_Sell_Virtual={Active:true,End_Sequence(d){this.Active=false;c.ended.push('S:'+d);}};return c;};
 const c=run(1);c.step(FRI(12),FRI(12));assert.deepEqual(c.ended,[],'no hold: candidates live');
 c.step(FRI(12),FRI(13));assert.deepEqual(c.ended,['B:Feed guard hold','S:Feed guard hold'],'the hold starts: both end, with the reason');
 c.Seq_Buy_Virtual.Active=true;c.step(FRI(12),FRI(13));assert.equal(c.ended.length,2,'once per hold');
 c.step(FRI(13),FRI(13));c.step(FRI(13,0,1),FRI(14));assert.deepEqual(c.ended.slice(2),['B:Feed guard hold'],'the next hold, only what is active');
 const o=run(1);o.step(FRI(12),FRI(12));o.g_GoatCloseOwed=true;o.step(FRI(12,0,1),FRI(12,0,1));assert.equal(o.ended.length,2,'an owed close starts a hold too');
 const off=run(0);off.step(FRI(12),FRI(13));assert.deepEqual(off.ended,[],'flag off: never');
 const tester=run(1);tester.tester=1;tester.step(FRI(12),FRI(13));assert.deepEqual(tester.ended,[],'the tester: never');
 const timer=run(1);timer.step(FRI(12),FRI(12));timer.g_GoatFeedAgeS=999;timer.g_GoatNoTickRun=true;timer.GoatEntriesHoldWatch();timer.g_GoatNoTickRun=false;assert.deepEqual(timer.ended,[],'a timer run: never');
 // The watch runs right after the guard's read, before anything can promote.
 assert.ok(TICK.indexOf('GoatFeedGuardTick();')<TICK.indexOf('GoatEntriesHoldWatch();')&&TICK.indexOf('GoatEntriesHoldWatch();')<TICK.indexOf('SignalEntryTrigger();'));
 ok();}

{// 22. The owed close never hides or withholds another stop.
 const owing=opts=>{const c=chart({minLevel:9000,...opts});c.step(MON(9),MON(9));c.g_GoatCloseOwed=true;c.g_GoatCloseOwedSince=FRI(21);c.g_GoatCloseOwedQuoteMs=c.nowMs-300000;return c;};
 // A real stop that fires while the owed close's own stop is up owns the flag: settling leaves it, and its stamp.
 const m=owing();m.retcode=10004;m.step(MON(9,0,1),MON(9,0,1));assert.deepEqual([m.StopOut_Flag,m.g_GoatCloseOwedStop],[true,true],'its own stop');
 m.equity=8000;m.nowMs+=1000;m.step(MON(9,0,2),MON(9,0,2));assert.deepEqual([m.StopOut_Flag,m.g_GoatCloseOwedStop],[true,false],'the equity stop fired under it, and owns the flag');assert.equal(m.alerts.filter(a=>/Low Equity/.test(a)).length,1,'said');
 m.retcode=10009;m.nowMs+=1000;m.step(MON(9,0,3),MON(9,0,3));assert.deepEqual(m.positions,[],'flat');assert.equal(m.g_GoatCloseOwed,false,'settled');
 assert.equal(m.StopOut_Flag,true,'and the real stop stays up');assert.ok(m.LastStopoutTime>0,'with its time');
 // A Mode_Restart cooldown stamped before the owed close survives its settling.
 const k=owing();k.LastStopoutTime=1234;k.step(MON(9,0,1),MON(9,0,1));assert.deepEqual(k.positions,[],'sent');assert.deepEqual([k.g_GoatCloseOwed,k.StopOut_Flag,k.LastStopoutTime],[false,false,1234],'its own stop down, the cooldown kept');
 // Another stop's close always goes: not when the session table reads closed, not inside a back-off.
 const w=owing();w.g_GoatCloseOwedQuoteMs=0;w.sessions={};w.g_GoatCloseOwedNextMs=9e12;w.equity=8000;w.step(MON(9,0,1),MON(9,0,1));
 assert.equal(w.g_GoatCloseRealStop,true,'a real stop');assert.deepEqual(w.positions,[],'its close is sent though the owed close is not due');
 // The Friday stop itself is withheld when not due, so a closed market is not asked every second.
 const fr=chart();fr.retcode=10018;fr.step(FRI(21,0,1),FRI(21,0,1));const n=fr.sends.length;fr.sessions={};for(let i=2;i<10;i++)fr.step(FRI(21,0,i),FRI(21,0,i));
 assert.equal(fr.sends.length,n,'the session table closed: not asked');assert.equal(fr.StopOut_Flag,true,'and the Friday stop stands');
 // A money stop is evaluated on the tick its own stop was up for: it was never skipped as already stopped.
 assert.ok(bodyOf(TICK,'if(IsNewSecond())').indexOf('GoatCloseOwedStopLower();')<bodyOf(TICK,'if(IsNewSecond())').indexOf('if(!StopOut_Flag && MaxLossLocal'),'lowered before the stops are read');
 assert.ok(bodyOf(TICK,'if(IsNewSecond())').indexOf('GoatCloseRealStopNote();')<bodyOf(TICK,'if(IsNewSecond())').indexOf('// End of Day/session'),'noted before the day and Friday actions');
 ok();}

{// 23. Never-Init-ed sequences (Delay_Trade=0): dir stays OP_NIL (-2) and Virtual false, and every stop-out still calls End_Sequence on
 // them. In MQL5 an out-of-range index removes the EA, so the fixture's arrays throw on one. This is the flags-off promise.
 const OP_NIL=Number(header.match(/#define OP_NIL\s+(-?\d+)/)[1]);assert.equal(OP_NIL,-2);
 const END=js(bodyOf(main,'   void End_Sequence(string desc)').replace(/C'\d+,\d+,\d+'/g,'0'));
 for(const [tickload,flag,timing,tester] of [[0,0,0,0],[1,0,0,0],[0,1,0,0],[0,0,1,0],[1,1,1,0],[1,1,1,1]]){
  const c=basket({tickload,flag,timing,tester});c.dir=OP_NIL;c.Virtual=false;c.Active=false;
  vm.runInContext('function End_Sequence(desc){'+END+'}',c.__ctx);
  c.End_Sequence('Day/Weekend Close');   // the production body, on the never-Init-ed sequence
  c.GoatTrailNote(0,100,10016);c.End_Sequence('Day/Weekend Close');
  if(tickload&&!tester)assert.deepEqual([...c.g_GoatTrailTicket],[100],'it clears no real side\'s row');
  // Every new index in the hotfix, from any value a caller could hold.
  for(const v of [OP_NIL,-1,2,6,99]){c.GoatTrailReset(v);c.GoatTrailHeld(v);c.GoatTrailSlot(v);assert.equal(c.GoatTickLoadHold(v),false,'hold '+v);}
 }
 // The stop-out itself, on the production per-second block, with the virtuals never Init-ed.
 const s=chart({flag:0,minLevel:9000});let calls=0;const nil={dir:OP_NIL,End_Sequence(d){calls++;s.GoatTrailReset(OP_NIL);}};s.Seq_Buy_Virtual=nil;s.Seq_Sell_Virtual=nil;s.retcode=10009;s.equity=8000;s.step(FRI(10,0,1),FRI(10,0,1));
 assert.ok(calls>0,'End_Sequence ran on them');assert.equal(s.StopOut_Flag,true);
 ok();}

//@@NEXT@@
console.log(JSON.stringify({passed,test:'b49b_lag',baseCompared:BASE.slice(0,7)}));
