// B49b lag hotfix (the terminals that fall behind, goatai#2587): source-level tests, no compiler. The production code runs
// here from GOAT V1.49.mq5 and GOAT_Inputs_Definitions.mqh, with the terminal stubbed. What this cannot show is listed in the
// PR: that it compiles, MT5's real timer and tick queue, TimeTradeServer's behaviour in a backlog, and the bench's numbers.
// 0. Flags off is the base: every hotfix line is marked, and without the marked lines both sources ARE be341e5's, byte for
//    byte. Each added call is a no-op with its flag off, or in the tester with its flag on.
// A. Fix_FeedGuard (safeguards): 1 the clock swap; 2 the Friday close on the server clock in a backlog; 3 the owed close across
//    the weekend; 4 a backlog over the open; 5 a restart; 6 the guard's thresholds; 7 exits never read it; 8 the status file;
//    9 the daily stops' window; 10 the no-tick clock; 10b a rejection that returned true.
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
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(/\bstatic\s+/g,'')
 .replace(/\bMqlTick (\w+);/g,'let $1={};')
 .replace(/TimeToStruct\(tm_cur,stm_cur\)/g,'stm_cur=__struct(tm_cur)').replace(/TimeCurrent\(stm_cur\)/g,'stm_cur=__struct(TimeCurrent())')
 .replace(/MqlDateTime (\w+); TimeToStruct\((\w+),\1\);/g,'let $1=__struct($2);')
 .replace(/SymbolInfoSessionTrade\((\w+),\(ENUM_DAY_OF_WEEK\)(\w+)\.day_of_week,(\w+),(\w+),(\w+)\)/g,'((__r=__session($1,$2.day_of_week,$3))!==null&&(($4=__r[0]),($5=__r[1]),true))')
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ').replace(/\blet (\w+)\[\]/g,'let $1=[]')
 .replace(/\((?:long|int|uint|ulong|double|datetime|bool)\)/g,'');
const struct=t=>{const d=new Date(t*1000);return {sec:d.getUTCSeconds(),min:d.getUTCMinutes(),hour:d.getUTCHours(),day:d.getUTCDate(),day_of_week:d.getUTCDay(),mon:d.getUTCMonth()+1};};
const FX={0:[[79200,86400]],1:[[0,86400]],2:[[0,86400]],3:[[0,86400]],4:[[0,86400]],5:[[0,79200]],6:[]};
const FNS=[
 ['bool GoatManageOnlyLive()',''],
 ['bool GoatFeedGuardLive(void)',''],['datetime GoatServerClock(void)',''],['int GoatFeedAge(const datetime srv_clock)','srv_clock'],
 ['void GoatFeedGuardStamp(void)',''],['void GoatFeedGuardTick(void)',''],['void GoatFeedClockServer(void)',''],['void GoatFeedClockFeed(void)',''],
 ['bool GoatEntriesHeld(void)',''],['bool GoatCloseOwedDue(void)',''],['bool GoatCloseOwedHeld(void)',''],['void GoatCloseOwedAssert(const int open_count)','open_count'],
 ['void GoatCloseOwedAfter(const int open_count)','open_count'],['void GoatCloseOwedRefused(const uint retcode)','retcode'],['string GoatCloseOwedText(void)',''],
 ['void GoatCloseOwedRestore(const string &keys[],const string &values[])','keys,values'],['bool GoatStatusLive(void)',''],['string GoatStatusText(void)',''],['void GoatStatusFlush(void)',''],
 ['bool GoatModifyRejected(const uint retcode,const bool counted,const ulong ticket,const string what,const string description)','retcode,counted,ticket,what,description'],['bool GoatCloseRejected(const uint retcode,const bool counted,const ulong ticket,const string description)','retcode,counted,ticket,description'],
 ['string GoatStateValue(const string &keys[],const string &values[],const string key)','keys,values,key'],
 ['bool GoatNoTickSessionOpen(const string symbol,const datetime clock)','symbol,clock'],
];
const nameOf=sig=>sig.match(/(\w+)\(/)[1];
const TICK=bodyOf(main,'void GoatTickBody()');
// The production day block and per-second block, in GoatTickBody's order; the minute block sits between them and is not run.
const PREFIX=TICK.slice(TICK.indexOf('tm_cur = TimeCurrent(); TimeCurrent(stm_cur);'),TICK.indexOf('static double MinuteLowEquity'));
const SECOND='if(IsNewSecond())\n{'+bodyOf(TICK,'if(IsNewSecond())')+'}';
const CLOSE=bodyOf(main,'void CloseAllPositions(int OP,int magic=0)').replace(/\bCTrade m_trade;/,'');
const HELPERS=['IsNewSecond','IsNewDay'];

// One chart on a stubbed terminal. feed: the newest tick the terminal has processed; server: TimeTradeServer.
function chart({flag=1,tester=0,action=1,positions=2,hourEnd=21,dailyLoss=0}={}){
 const list=[];for(let i=0;i<positions;i++)list.push({ticket:11+i,symbol:'EURUSD',magic:7,type:i%2,volume:0.1});
 const b={MQL_TESTER:6,MQL_OPTIMIZATION:61,MQL_FORWARD:62,Operation_Standard:0,Operation_Batch:1,Operation_Dash:2,Mode_Operation:0,Mode:'',
  Fix_FeedGuard:flag,Fix_Clock:0,GoatFix_Off:0,GoatFix_On:1,GOAT_FEED_AGE_GUARD_S:0,GOAT_CLOSE_OWED_RETRY_MS:0,GOAT_STATUS_VERSION:0,GOAT_STATUS_WRITE_MS:0,
  GOAT_NO_TICK_BACKOFF_MIN_MS:60000,GOAT_NO_TICK_BACKOFF_MAX_MS:900000,
  g_GoatServerNow:0,g_GoatFeedTmSaved:0,g_GoatFeedStmSaved:null,g_GoatFeedAgeS:-1,g_GoatFeedHeldLogged:false,g_GoatFeedLogMs:0,g_GoatCloseOwed:false,g_GoatCloseOwedStop:false,g_GoatCloseFridayFired:false,
  g_GoatCloseOwedSince:0,g_GoatCloseOwedNextMs:0,g_GoatCloseOwedBackoffMs:0,g_GoatStatusWrittenMs:0,g_GoatStatusFailLogged:false,g_GoatLastTickMs:0,g_GoatLastTickTime:0,g_GoatStateWriteError:0,
  g_GoatNoTickRun:false,tm_cur:0,stm_cur:{},TRADE_RETCODE_DONE:10009,TRADE_RETCODE_DONE_PARTIAL:10010,TRADE_RETCODE_PLACED:10008,TRADE_RETCODE_MARKET_CLOSED:10018,TRADE_RETCODE_TRADE_DISABLED:10017,
  SYMBOL_TRADE_MODE:8,SYMBOL_TRADE_MODE_DISABLED:0,TERMINAL_CONNECTED:7,ACCOUNT_LOGIN:9,TIME_DATE:1,TIME_SECONDS:4,FILE_COMMON:4096,_Symbol:'EURUSD',MAGIC1:7,GOAT_BUILD_ID:'b49b',
  closed:0,closeErrors:0,TSLmodifieds:3,TSLmodifyErrors:2,Hour_Start:[8,8,8,8,8,8,8],Minute_Start:[0,0,0,0,0,0,0],Hour_End:Array(7).fill(hourEnd),Minute_End:[0,0,0,0,0,0,0],
  InActive:false,Active:true,Sequence_Pause_Close:false,Trade_Friday:true,Trade_December:true,FastSpeed_Flag:true,POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,OP_BUYSELL:2,
  StopOut_Flag:false,StopOut_Flag_B:false,StopOut_Flag_S:false,LastStopoutTime:0,Mode_Restart:0,g_GoatLastStopOutB:false,g_GoatLastStopOutS:false,
  DStartLocalLoss:0,DStartTime:0,DStartEquity:10000,MaxEquity:10000,DDs_PC:[0],DDs_Actual:[0],CurrentDD:0,CurrentDDD:0,dt_Back_OOS:0,dt_Fwrd_OOS:0,
  MaxLossLocal:0,MaxLossGlobal:0,MaxDailyLossLocal:dailyLoss,MaxDailyProfitLocal:0,MinLevelEquity:0,MaxLevelEquity:0,Ledger_Mode:0,Ledger_PositionJoin:1,
  Action_Close:1,Action_Pause:2,Action_Dayend:0,Action_Friday:action,Key:'K',days:0,LastEquity:0,Pause_Flag:false,
  feed:0,server:0,tickTime:0,tickReadable:true,nowMs:1000000,tester,retcode:10009,tradeMode:4,sessions:FX,prints:[],alerts:[],sends:[],ended:[],history:[],writes:[],writeOk:true,folders:[],__r:null,positions:list,serverReads:0,
  Math,Number,String,Array,JSON,undefined,NaN,Infinity};
 const ctx=new Proxy(b,{has:()=>true,get(t,p){if(p in t)return t[p];if(typeof p==='symbol')return undefined;return function stub(){return 0;};},set(t,p,v){t[p]=v;return true;}});
 vm.createContext(ctx);b.__ctx=ctx;
 for(const m of main.matchAll(/^#define (GOAT_(?:FEED_AGE_GUARD_S|CLOSE_OWED_RETRY_MS|STATUS_VERSION|STATUS_WRITE_MS)) (\d+)$/gm))b[m[1]]=Number(m[2]);
 b.__struct=struct;b.__session=(s,dow,i)=>{const l=b.sessions[dow]||[];return i<l.length?l[i]:null;};
 b.TimeCurrent=()=>b.feed;b.TimeTradeServer=()=>{b.serverReads++;return b.server;};
 b.MQLInfoInteger=k=>k===6?b.tester:0;b.GetTickCount64=()=>b.nowMs;b.SymbolInfoInteger=(s,k)=>k===8?b.tradeMode:0;
 b.SymbolInfoTick=(s,t)=>{if(!b.tickReadable)return false;t.time=b.tickTime;return true;};
 b.ArraySize=a=>a.length; b.IntegerToString=v=>String(v);b.TimeToString=t=>String(t);b.StringToInteger=s=>Number(s)||0;
 b.Print=(...a)=>b.prints.push(a.join(''));b.Alert=s=>b.alerts.push(s);b.AccountInfoDouble=()=>10000;b.AccountInfoInteger=()=>555;b.PositionsTotal=()=>b.positions.length;b.TerminalInfoInteger=()=>1;
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
 b.stm_cur={sec:59,day:0};b.IsNewSecond();   // MQL statics start at 0: a first tick on second :00 would read as "not new"
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
 for(const name of ['Fix_FeedGuard']){
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

{// 3. The owed close: refused at the session end, held through the weekend, sent at the first tradable tick.
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
  c.step(SUN(21,59,0),SUN(21,59,59));out.beforeOpen=c.sends.length-sat;
  c.retcode=10009;
  c.step(MON(0,0,6),MON(0,0,6));
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
 assert.equal(on.satSends,0,'no send on Saturday');assert.equal(on.beforeOpen,0,'nor before the session opens');
 const c=on.c;
 assert.ok(c.prints.some(l=>/sending the Friday close owed since/.test(l)),'sent, logged');
 assert.deepEqual(c.positions,[],'at the first tradable tick the close goes and fills');
 assert.deepEqual([c.g_GoatCloseOwed,c.StopOut_Flag,c.LastStopoutTime],[false,false,0],'settled: the stop it raised is lowered, so Monday trades as after a normal Friday close');
 assert.ok(c.prints.some(l=>/settled, flat on EURUSD/.test(l)));
 assert.equal(c.ended.filter(d=>d==='Day/Weekend Close').length,4,'the sequences end through B49a\'s own path');
 assert.equal(off.owed,false,'off: never owed');
 assert.equal(off.c.positions.length,2,'off: the refused close is dropped and Monday still holds the positions (the measured defect)');
 // A refusal other than a closed market retries after a second; a stop that was not the owed close's own stays up.
 const r=chart();r.g_GoatCloseOwed=true;r.step(MON(9),MON(9));r.nowMs=5000000;r.GoatCloseOwedRefused(10004);assert.equal(r.g_GoatCloseOwedNextMs,5001000,'a requote: a second');
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

{// 4. A backlog over the open: the owed close is not held for fresh ticks, and entries stay held until the feed catches up.
 const c=chart();c.g_GoatCloseOwed=true;c.g_GoatCloseOwedSince=FRI(21);
 c.step(FRI(23,0,0),MON(0,5,0));
 assert.deepEqual(c.positions,[],'the guard never blocks an exit: sent on the stale tick once the session is open');
 assert.equal(c.g_GoatCloseOwed,false,'and settled');
 assert.equal(c.GoatEntriesHeld(),true,'the feed is still behind: entries stay held');
 c.step(MON(0,5,1),MON(0,5,1));assert.equal(c.GoatEntriesHeld(),false,'caught up: they resume');
 ok();}

{// 5. A restart: the state file carries the owed close, whatever the day; flag off ignores it.
 const a=chart();a.g_GoatCloseOwed=true;a.g_GoatCloseOwedSince=FRI(21);a.g_GoatCloseOwedStop=true;
 const text=a.GoatCloseOwedText();assert.equal(text,'close_owed=1\nclose_owed_since='+FRI(21)+'\nclose_owed_stop=1\n');
 const lines=text.trim().split('\n').map(l=>l.split('='));const keys=lines.map(l=>l[0]),values=lines.map(l=>l[1]);
 const b=chart();b.GoatCloseOwedRestore(keys,values);
 assert.deepEqual([b.g_GoatCloseOwed,b.g_GoatCloseOwedSince,b.g_GoatCloseOwedStop],[true,FRI(21),true],'restored');
 assert.equal(b.alerts.length,1,'loudly');
 const noFlag=chart({flag:0});noFlag.GoatCloseOwedRestore(keys,values);assert.equal(noFlag.g_GoatCloseOwed,false,'flag off: ignored');assert.match(noFlag.prints[0],/ignored/);
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
 assert.equal(users,4,'the definition, the two gates and the status text: nothing else reads it');
 for(const [sig,label] of [['void CloseAllPositions(int OP,int magic=0)','closes'],['   void TrailingStoploss()','trailing'],['   bool EnforceSequenceMLPS(const string context)','MLPS'],['   void ClosePendingPump()','the close pump']])
  assert.ok(!/GoatEntriesHeld|g_GoatFeedAgeS/.test(bodyOf(main,sig)),label+' never read the guard');
 assert.ok(!/GoatEntriesHeld|g_GoatFeedAgeS/.test(bodyOf(TICK,'if(IsNewSecond())')),'nor the per-second block\'s stops');
 // OnTick stamps, then the guard stamps, before the body runs; the body's guard read precedes both blocks.
 assert.equal(bodyOf(main,'void OnTick()').replace(/\/\/.*$/gm,'').replace(/\s+/g,'').indexOf('GoatNoTickStamp();GoatFeedGuardStamp();GoatTickBody();'),0);
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
 assert.deepEqual(c.history[c.history.length-1],[FRI(14),FRI(14)],'its deals are selected up to the server clock');
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

//@@NEXT@@
console.log(JSON.stringify({passed,test:'b49b_lag',baseCompared:BASE.slice(0,7)}));
