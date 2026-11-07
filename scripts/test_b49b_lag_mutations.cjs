// Mutation check for the B49b lag hotfix: every rule is load-bearing. Each mutant edits GOAT V1.49.mq5 or
// GOAT_Inputs_Definitions.mqh in memory; test_b49b_lag.cjs, run on the mutated sources (GOAT_EA_MAIN, GOAT_EA_HEADER), must
// then fail. Run in parallel, as the F1 mutants are (the controller job has a time cap).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_lag.cjs');
const SOURCES={main:fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n'),
 header:fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n')};
const MUTANTS=[
 // Group A: live-only and flagged.
 ['main','the guard ignores its flag','return(Fix_FeedGuard==GoatFix_On && GoatManageOnlyLive());','return(GoatManageOnlyLive());'],
 ['main','the guard runs in the tester','return(Fix_FeedGuard==GoatFix_On && GoatManageOnlyLive());','return(Fix_FeedGuard==GoatFix_On);'],
 ['main','an unmarked line changes the base','   if(GoatEntriesHeld()) return false; // B49b (LAG-A): the feed is behind or a Friday close is owed, nothing new opens\n','   if(GoatEntriesHeld()) return false;\n'],
 ['header','the flag defaults On','Fix_FeedGuard                 =                   GoatFix_Off;','Fix_FeedGuard                 =                   GoatFix_On;'],
 ['header','the SET always records it','if(Fix_FeedGuard!=GoatFix_Off) FileWrite(FileSET_handle,"Fix_FeedGuard="','FileWrite(FileSET_handle,"Fix_FeedGuard="'],
 // The clock.
 ['main','the clock can be earlier than the broker','return(srv_clock>srv_last ? srv_clock : srv_last);','return(srv_clock);'],
 ['main','the clock is the feed\'s','return(srv_clock>srv_last ? srv_clock : srv_last);','return(srv_last);'],
 ['main','the day block stays on the feed','   GoatFeedClockServer(); // B49b (LAG-A): the day resets on the server clock\n','   // B49b (LAG-A): the day resets on the server clock\n'],
 ['main','the second block stays on the feed','    GoatFeedClockServer(); // B49b (LAG-A): session, Friday and day-end logic on the server clock\n','    // B49b (LAG-A): session, Friday and day-end logic on the server clock\n'],
 ['main','the second block leaves the clock swapped','    GoatFeedClockFeed(); // B49b (LAG-A)\n','    // B49b (LAG-A)\n'],
 ['main','the day block leaves the clock swapped','   GoatFeedClockFeed(); // B49b (LAG-A): the samplers below stay on the feed\'s clock\n','   // B49b (LAG-A): the samplers below stay on the feed\'s clock\n'],
 ['main','the restore loses the struct','   tm_cur=g_GoatFeedTmSaved; stm_cur=g_GoatFeedStmSaved;\n','   tm_cur=g_GoatFeedTmSaved;\n'],
 ['main','a timer run reads the server clock','g_GoatServerNow=(g_GoatNoTickRun ? tm_cur : GoatServerClock());','g_GoatServerNow=GoatServerClock();'],
 ['main','the no-tick clock stays on the stale tick','   if(GoatFeedGuardLive()) g_GoatLastTickTime=GoatServerClock();\n',''],
 ['main','OnTick never stamps it','   GoatFeedGuardStamp(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 // The guard.
 ['main','the threshold is not 30 s','#define GOAT_FEED_AGE_GUARD_S 30','#define GOAT_FEED_AGE_GUARD_S 60'],
 ['main','the guard is inclusive','g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);\n  }\nbool GoatCloseOwedDue','g_GoatFeedAgeS<0 || g_GoatFeedAgeS>=GOAT_FEED_AGE_GUARD_S);\n  }\nbool GoatCloseOwedDue'],
 ['main','an unreadable tick passes','return(g_GoatCloseOwed || g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);','return(g_GoatCloseOwed || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);'],
 ['main','an owed close does not hold entries','return(g_GoatCloseOwed || g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);','return(g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);'],
 ['main','the age reads the last tick of any symbol','if(!SymbolInfoTick(_Symbol,feed_tick) || feed_tick.time==0) return -1;\n   long feed_age=(long)srv_clock-(long)feed_tick.time;','if(!SymbolInfoTick(_Symbol,feed_tick) || feed_tick.time==0) return -1;\n   long feed_age=(long)srv_clock-(long)TimeCurrent();'],
 ['main','a negative age','return (feed_age<0 ? 0 : (int)feed_age);','return ((int)feed_age);'],
 ['main','a timer run moves the age','   if(g_GoatNoTickRun) return;\n   g_GoatFeedAgeS=GoatFeedAge(g_GoatServerNow);','   g_GoatFeedAgeS=GoatFeedAge(g_GoatServerNow);'],
 ['main','adds are not gated','    if(GoatEntriesHeld()) return false; // B49b (LAG-A): no add,','    // B49b (LAG-A): no add,'],
 ['main','starts are not gated','   if(GoatEntriesHeld()) return false; // B49b (LAG-A): the feed is behind','   // B49b (LAG-A): the feed is behind'],
 ['main','the log is not once a minute','   if(g_GoatFeedLogMs!=0 && now_ms-g_GoatFeedLogMs<60000) return;\n',''],
 ['main','the log repeats every tick','   if(feed_held==g_GoatFeedHeldLogged) return;\n',''],
 // The owed close.
 ['main','the Friday action never arms it','     if(Action_Friday==Action_Close && GoatFeedGuardLive()) g_GoatCloseFridayFired=true; // B49b (LAG-A)','     // B49b (LAG-A)'],
 ['main','the owed close is never re-sent','    GoatCloseOwedAssert(Trades); // B49b (LAG-A)','    // B49b (LAG-A)'],
 ['main','it never settles or arms','    GoatCloseOwedAfter(Trades); // B49b (LAG-A)','    // B49b (LAG-A)'],
 ['main','a held close is sent anyway','      if(!GoatCloseOwedHeld()) // B49b (LAG-A)','      // B49b (LAG-A)'],
 ['main','it is sent into a closed session','return(GoatNoTickSessionOpen(_Symbol,g_GoatServerNow) && GetTickCount64()>=g_GoatCloseOwedNextMs);','return(GetTickCount64()>=g_GoatCloseOwedNextMs);'],
 ['main','the back-off is ignored','return(GoatNoTickSessionOpen(_Symbol,g_GoatServerNow) && GetTickCount64()>=g_GoatCloseOwedNextMs);','return(GoatNoTickSessionOpen(_Symbol,g_GoatServerNow));'],
 ['main','an open position lets it settle','   if(!g_GoatCloseOwed || open_count>0) return;\n','   if(!g_GoatCloseOwed) return;\n'],
 ['main','it arms with nothing open','if(fired && open_count>0 && !g_GoatCloseOwed)','if(fired && !g_GoatCloseOwed)'],
 ['main','it is silent when armed','      Print(owed_line); Alert(owed_line);\n      return;\n','      return;\n'],
 ['main','closeErrors is not surfaced','" position(s) open on "+_Symbol+", close_errors="+IntegerToString(closeErrors)','" position(s) open on "+_Symbol'],
 ['main','settling lowers another stop','   if(g_GoatCloseOwedStop) {StopOut_Flag=false; LastStopoutTime=0;}\n','   StopOut_Flag=false; LastStopoutTime=0;\n'],
 ['main','settling leaves its stop up','   if(g_GoatCloseOwedStop) {StopOut_Flag=false; LastStopoutTime=0;}\n',''],
 ['main','the assert forgets the stop is its own','   StopOut_Flag=true; g_GoatCloseOwedStop=true;\n','   StopOut_Flag=true;\n'],
 ['main','a refusal never reaches the pacing','     if(g_GoatCloseOwed) GoatCloseOwedRefused(m_trade.ResultRetcode());','     '],
 ['main','a fill paces the retries','   if(retcode==TRADE_RETCODE_DONE || retcode==TRADE_RETCODE_DONE_PARTIAL || retcode==TRADE_RETCODE_PLACED) return;\n',''],
 ['main','a requote backs off like a closed market','   if(!market_shut) {g_GoatCloseOwedNextMs=now_ms+GOAT_CLOSE_OWED_RETRY_MS; return;}\n',''],
 ['main','the owed back-off never doubles','ulong owed_wait=g_GoatCloseOwedBackoffMs*2;','ulong owed_wait=0;'],
 ['main','the owed back-off has no cap','   if(owed_wait>GOAT_NO_TICK_BACKOFF_MAX_MS) owed_wait=GOAT_NO_TICK_BACKOFF_MAX_MS;\n',''],
 ['main','a fresh tick clears the wait outright','if(!feed_held && g_GoatCloseOwedNextMs>now_ms+GOAT_NO_TICK_BACKOFF_MIN_MS) {g_GoatCloseOwedNextMs=now_ms+GOAT_NO_TICK_BACKOFF_MIN_MS; g_GoatCloseOwedBackoffMs=0;}','if(!feed_held) {g_GoatCloseOwedNextMs=0; g_GoatCloseOwedBackoffMs=0;}'],
 ['main','a stale tick caps the wait','if(!feed_held && g_GoatCloseOwedNextMs>now_ms+GOAT_NO_TICK_BACKOFF_MIN_MS)','if(g_GoatCloseOwedNextMs>now_ms+GOAT_NO_TICK_BACKOFF_MIN_MS)'],
 // Restart.
 ['main','the state text drops it','   text+=GoatCloseOwedText(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','the state text always carries it','   if(!g_GoatCloseOwed) return "";\n',''],
 ['main','a restart forgets it','   GoatCloseOwedRestore(keys,values); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','it restores with the flag off','if(!GoatFeedGuardLive() || Action_Friday!=Action_Close) {Print("GOAT close owed: the state file','if(Action_Friday!=Action_Close) {Print("GOAT close owed: the state file'],
 ['main','it restores when Friday no longer closes','if(!GoatFeedGuardLive() || Action_Friday!=Action_Close) {Print("GOAT close owed: the state file','if(!GoatFeedGuardLive()) {Print("GOAT close owed: the state file'],
 // The status file and the daily stops.
 ['main','the status file has no feed age','"\\nfeed_age_s="+IntegerToString(GoatFeedAge(srv_clock))','""'],
 ['main','the status file has no close errors','"\\nclose_errors="+IntegerToString(closeErrors)','""'],
 ['main','the status file is not throttled','   if(g_GoatStatusWrittenMs!=0 && now_ms-g_GoatStatusWrittenMs<GOAT_STATUS_WRITE_MS) return;\n',''],
 ['main','the status file overwrites the state file','"_"+_Symbol+".status.txt"','"_"+_Symbol+".txt"'],
 ['main','a failed status write freezes adds','   g_GoatStatusFailLogged=true;\n','   g_GoatStatusFailLogged=true; g_GoatStateFailed=true;\n'],
 ['main','the timer never writes it','   GoatStatusFlush(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','the day starts on the feed\'s clock','     if(DStartLocalLoss==99999 && GoatFeedGuardLive()) {DStartLocalLoss=PL_Total; DStartTime=g_GoatServerNow;} // B49b (LAG-A)','     // B49b (LAG-A)'],
 ['main','the deals stop at the feed\'s clock','     if(GoatFeedGuardLive()) HistorySelect(DStartTime,g_GoatServerNow); // B49b (LAG-A)','     // B49b (LAG-A)'],
 // A rejection that returned true.
 ['main','the retcode is ignored','if(!GoatFeedGuardLive() || counted || retcode==TRADE_RETCODE_DONE) return false;','return false;'],
 ['main','a rejection counts when the flag is off','if(!GoatFeedGuardLive() || counted || retcode==TRADE_RETCODE_DONE) return false;','if(counted || retcode==TRADE_RETCODE_DONE) return false;'],
 ['main','a false answer counts twice','if(!GoatFeedGuardLive() || counted || retcode==TRADE_RETCODE_DONE) return false;','if(!GoatFeedGuardLive() || retcode==TRADE_RETCODE_DONE) return false;'],
 ['main','an accepted modify counts as rejected','if(!GoatFeedGuardLive() || counted || retcode==TRADE_RETCODE_DONE) return false;','if(!GoatFeedGuardLive() || counted) return false;'],
 ['main','a rejection is silent','   PrintFormat("%s modify rejected though it returned true: ticket=%I64u ret=%u (%s)",what,ticket,retcode,description);\n',''],
 ['main','the close rejection is not counted','     if(GoatCloseRejected(m_trade.ResultRetcode(),closeErrors!=close_errors_before,m_position.Ticket(),m_trade.ResultRetcodeDescription())) closeErrors++;','     if(false) closeErrors++;'],
 ['main','the close rejection is not logged','   GoatCloseFailureLog(ticket,retcode,description);\n',''],
 ['main','the buy side is not checked','(ulong)TradeLevels[i].ticket,"TSL BUY",Trade.ResultRetcodeDescription())) TSLmodifyErrors++;','(ulong)TradeLevels[i].ticket,"TSL BUY",Trade.ResultRetcodeDescription())) {}'],
 ['main','the sell side is not checked','(ulong)TradeLevels[i].ticket,"TSL SELL",Trade.ResultRetcodeDescription())) TSLmodifyErrors++;','(ulong)TradeLevels[i].ticket,"TSL SELL",Trade.ResultRetcodeDescription())) {}'],
 ['main','the TP/SL site reads the wrong counter','TPmodifyErrors!=tp_errors_before,(ulong)TradeLevels[i].ticket,"TP/SL"','TSLmodifyErrors!=tp_errors_before,(ulong)TradeLevels[i].ticket,"TP/SL"'],
//@@NEXT@@
];
function runOn(texts){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-lag-'));
 const files={main:path.join(dir,'GOAT V1.49.mq5'),header:path.join(dir,'GOAT_Inputs_Definitions.mqh')};
 for(const k of Object.keys(files))fs.writeFileSync(files[k],'﻿'+texts[k].replace(/\n/g,'\r\n'),'utf8');
 return new Promise(resolve=>{
  const child=spawn(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:files.main,GOAT_EA_HEADER:files.header},stdio:['ignore','ignore','pipe']});
  let err='';child.stderr.on('data',d=>{err+=d;});
  child.on('close',code=>{fs.rmSync(dir,{recursive:true,force:true});resolve({status:code,stderr:err});});
 });
}
(async()=>{
 const base=await runOn(SOURCES);assert.equal(base.status,0,'the unmutated test passes on the scratch sources: '+base.stderr);
 for(const [file,label,from] of MUTANTS){const n=SOURCES[file].split(from).length-1;assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${file} (found ${n})`);}
 let next=0,killed=0;const survivors=[];
 const worker=async()=>{while(next<MUTANTS.length){const [file,label,from,to]=MUTANTS[next++];
   const r=await runOn({...SOURCES,[file]:SOURCES[file].replace(from,()=>to)});
   if(r.status===0)survivors.push(label);else killed++;}};
 await Promise.all(Array.from({length:Math.max(2,Math.min(8,os.cpus().length))},worker));
 assert.deepEqual(survivors,[],'mutants survived');
 console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
})().catch(e=>{console.error(e);process.exit(1);});
