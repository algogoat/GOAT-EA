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
 ['main','the no-tick clock stays on the stale tick','   if(g_GoatFeedSynced) g_GoatLastTickTime=GoatServerClock();\n',''],
 ['main','OnTick never stamps it','   GoatFeedGuardStamp(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 // The guard.
 ['main','the threshold is not 30 s','#define GOAT_FEED_AGE_GUARD_S 30','#define GOAT_FEED_AGE_GUARD_S 60'],
 ['main','the guard is inclusive','g_GoatClockSlowHeld || g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);','g_GoatClockSlowHeld || g_GoatFeedAgeS<0 || g_GoatFeedAgeS>=GOAT_FEED_AGE_GUARD_S);'],
 ['main','an unreadable tick passes','return(g_GoatCloseOwed || g_GoatClockSlowHeld || g_GoatFeedAgeS<0 || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);','return(g_GoatCloseOwed || g_GoatClockSlowHeld || g_GoatFeedAgeS>GOAT_FEED_AGE_GUARD_S);'],
 ['main','an owed close does not hold entries','return(g_GoatCloseOwed || g_GoatClockSlowHeld || g_GoatFeedAgeS<0','return(g_GoatClockSlowHeld || g_GoatFeedAgeS<0'],
 ['main','a slow clock does not hold entries','return(g_GoatCloseOwed || g_GoatClockSlowHeld || g_GoatFeedAgeS<0','return(g_GoatCloseOwed || g_GoatFeedAgeS<0'],
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
 ['main','it is sent into a closed session on its day','return((long)g_GoatServerNow/86400==(long)g_GoatCloseOwedSince/86400 && GoatNoTickSessionOpen(_Symbol,g_GoatServerNow));','return((long)g_GoatServerNow/86400==(long)g_GoatCloseOwedSince/86400);'],
 ['main','the back-off is ignored','   if(now_ms<g_GoatCloseOwedNextMs) return false;\n   if(g_GoatCloseOwedQuoteMs!=0)','   if(g_GoatCloseOwedQuoteMs!=0)'],
 ['main','it goes after the weekend with no wait','if(g_GoatCloseOwedQuoteMs!=0) return(now_ms-g_GoatCloseOwedQuoteMs>=GOAT_CLOSE_OWED_SETTLE_MS);','if(g_GoatCloseOwedQuoteMs!=0) return(true);'],
 ['main','the wait is exclusive','return(now_ms-g_GoatCloseOwedQuoteMs>=GOAT_CLOSE_OWED_SETTLE_MS);','return(now_ms-g_GoatCloseOwedQuoteMs>GOAT_CLOSE_OWED_SETTLE_MS);'],
 ['main','the wait is not 5 min','#define GOAT_CLOSE_OWED_SETTLE_MS 300000','#define GOAT_CLOSE_OWED_SETTLE_MS 60000'],
 ['main','after the weekend it still reads the session table','return(now_ms-g_GoatCloseOwedQuoteMs>=GOAT_CLOSE_OWED_SETTLE_MS);','return(now_ms-g_GoatCloseOwedQuoteMs>=GOAT_CLOSE_OWED_SETTLE_MS && GoatNoTickSessionOpen(_Symbol,g_GoatServerNow));'],
 ['main','the first quote never starts the wait','   GoatCloseOwedQuoteWatch(feed_held,now_ms);\n',''],
 ['main','a shut market leaves the wait spent','   g_GoatCloseOwedQuoteMs=0; // the market was not open after all: the next tick starts the wait again\n',''],
 ['main','a requote restarts the wait','   if(!market_shut) {g_GoatCloseOwedNextMs=now_ms+GOAT_CLOSE_OWED_RETRY_MS; return;}\n   g_GoatCloseOwedQuoteMs=0;','   g_GoatCloseOwedQuoteMs=0;\n   if(!market_shut) {g_GoatCloseOwedNextMs=now_ms+GOAT_CLOSE_OWED_RETRY_MS; return;}\n  '],
 ['main','a stray tick spends the wait','   if(g_GoatCloseOwedTickMs!=0 && now_ms-g_GoatCloseOwedTickMs>=GOAT_CLOSE_OWED_QUOTE_GAP_MS) g_GoatCloseOwedQuoteMs=0; // that quote was not the open\n',''],
 ['main','the gap is exclusive','now_ms-g_GoatCloseOwedTickMs>=GOAT_CLOSE_OWED_QUOTE_GAP_MS','now_ms-g_GoatCloseOwedTickMs>GOAT_CLOSE_OWED_QUOTE_GAP_MS'],
 ['main','the gap is short enough to stall a quiet market','#define GOAT_CLOSE_OWED_QUOTE_GAP_MS 1800000','#define GOAT_CLOSE_OWED_QUOTE_GAP_MS 60000'],
 ['main','the last tick is never kept','   g_GoatCloseOwedTickMs=now_ms;\n',''],
 ['main','settling keeps the last tick','g_GoatCloseOwedQuoteMs=0; g_GoatCloseOwedTickMs=0;\n','g_GoatCloseOwedQuoteMs=0;\n'],
 ['main','the same day counts as after the weekend','(long)feed_tick.time/86400>owed_day','(long)feed_tick.time/86400>=owed_day'],
 ['main','a backlog over the open never starts the wait','   if(!later_quote && !stale_open) return;\n','   if(!later_quote) return;\n'],
 ['main','a closed session starts the wait in a backlog','bool stale_open=(feed_held && (long)g_GoatServerNow/86400>owed_day && GoatNoTickSessionOpen(_Symbol,g_GoatServerNow));','bool stale_open=(feed_held && (long)g_GoatServerNow/86400>owed_day);'],
 ['main','the quote keeps the old pacing','   g_GoatCloseOwedQuoteMs=now_ms; g_GoatCloseOwedNextMs=0; g_GoatCloseOwedBackoffMs=0;\n','   g_GoatCloseOwedQuoteMs=now_ms;\n'],
 // Clock sync.
 ['main','the body runs on an unknown clock','   if(GoatFeedUnsynced() && !g_GoatNoTickRun) return; // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','the gate switches off the no-tick exits','if(GoatFeedUnsynced() && !g_GoatNoTickRun) return;','if(GoatFeedUnsynced()) return;'],
 ['main','OnInit\'s own tick counts as real','   if(g_GoatFeedInitDone && TerminalInfoInteger(TERMINAL_CONNECTED)!=0) g_GoatFeedSynced=true;','   if(TerminalInfoInteger(TERMINAL_CONNECTED)!=0) g_GoatFeedSynced=true;'],
 ['main','a tick while disconnected counts','   if(g_GoatFeedInitDone && TerminalInfoInteger(TERMINAL_CONNECTED)!=0) g_GoatFeedSynced=true;','   if(g_GoatFeedInitDone) g_GoatFeedSynced=true;'],
 ['main','a tick never syncs','   if(g_GoatFeedInitDone && TerminalInfoInteger(TERMINAL_CONNECTED)!=0) g_GoatFeedSynced=true;\n',''],
 ['main','a disconnect keeps the clock','if(GoatFeedGuardLive() && TerminalInfoInteger(TERMINAL_CONNECTED)==0) g_GoatFeedSynced=false;','if(false) g_GoatFeedSynced=false;'],
 ['main','the timer never watches the connection','   GoatFeedSyncWatch(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','OnInit never marks its tick','   GoatFeedInitMark(false); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','OnInit never ends its mark','   GoatFeedInitMark(true); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','the gate ignores its flag','return(GoatFeedGuardLive() && !g_GoatFeedSynced);','return(!g_GoatFeedSynced);'],
 // The clock's skew.
 ['main','a slow clock is logged at -10','if(g_GoatClockSkewS<-GOAT_CLOCK_SLOW_LOG_S && !g_GoatClockSlowLogged','if(g_GoatClockSkewS<=-GOAT_CLOCK_SLOW_LOG_S && !g_GoatClockSlowLogged'],
 ['main','a slow clock logs every tick','if(g_GoatClockSkewS<-GOAT_CLOCK_SLOW_LOG_S && !g_GoatClockSlowLogged &&','if(g_GoatClockSkewS<-GOAT_CLOCK_SLOW_LOG_S &&'],
 ['main','the slow-clock line is once for life','   if(g_GoatClockSkewS>=-GOAT_CLOCK_SLOW_LOG_S) g_GoatClockSlowLogged=false; // cleared: the next episode says so too\n',''],
 ['main','a flap logs every clear','&& (g_GoatClockSlowLogMs==0 || now_ms-g_GoatClockSlowLogMs>=60000))',')'],
 ['main','the hold threshold is inclusive','   if(g_GoatClockSkewS>=-GOAT_CLOCK_SLOW_HOLD_S)\n','   if(g_GoatClockSkewS>-GOAT_CLOCK_SLOW_HOLD_S)\n'],
 ['main','a slow clock holds at once','now_ms-g_GoatClockSlowSinceMs<GOAT_CLOCK_SLOW_HOLD_MS) return;','now_ms-g_GoatClockSlowSinceMs<0) return;'],
 ['main','a break does not restart the minute','     {\n      g_GoatClockSlowSinceMs=0;\n','     {\n'],
 ['main','the hold never lifts','      g_GoatClockSlowHeld=false;\n',''],
 ['main','the skew reads the floored clock','g_GoatClockSkewS=(long)TimeTradeServer()-(long)TimeCurrent();','g_GoatClockSkewS=(long)GoatServerClock()-(long)TimeCurrent();'],
 ['main','the watch never runs','   GoatClockSkewWatch(now_ms);\n',''],
 ['main','the status file has no raw skew','"\\nclock_skew_s="+IntegerToString((long)TimeTradeServer()-(long)TimeCurrent())','""'],
 ['main','the floor is the last reading','if(!g_GoatClockFloorSet || g_GoatClockSkewS<g_GoatClockFloorS) {','if(true) {'],
 ['main','the floor never restarts','{g_GoatStatusFailLogged=false; g_GoatClockFloorSet=false; return;}','{g_GoatStatusFailLogged=false; return;}'],
 // A hold ends virtual candidates.
 ['main','the watch never runs in the body','   GoatEntriesHoldWatch(); // B49b (LAG-A)','   // B49b (LAG-A)'],
 ['main','it ends candidates on every tick of a hold','if(hold_now && !g_GoatEntriesWereHeld)','if(hold_now)'],
 ['main','it leaves the sell candidate','      if(Seq_Sell_Virtual.Active) Seq_Sell_Virtual.End_Sequence("Feed guard hold");\n',''],
 ['main','a paper-level buy survives a hold','      if(Seq_Buy.Active && !Seq_Buy.Traded)   Seq_Buy.End_Sequence("Feed guard hold");\n',''],
 ['main','a paper-level sell survives a hold','      if(Seq_Sell.Active && !Seq_Sell.Traded) Seq_Sell.End_Sequence("Feed guard hold");\n',''],
 ['main','a hold ends a sequence with positions','if(Seq_Buy.Active && !Seq_Buy.Traded)   Seq_Buy.End_Sequence','if(Seq_Buy.Active)   Seq_Buy.End_Sequence'],
 ['main','a timer run ends candidates','if(!GoatFeedGuardLive() || g_GoatNoTickRun) return;\n   bool hold_now','if(!GoatFeedGuardLive()) return;\n   bool hold_now'],
 // Another stop is never hidden or withheld.
 ['main','the owed stop is never lowered','    GoatCloseOwedStopLower(); // B49b (LAG-A)','    // B49b (LAG-A)'],
 ['main','another stop\'s close is withheld','return(g_GoatCloseOwed && GoatFeedGuardLive() && !g_GoatCloseRealStop && !GoatCloseOwedDue());','return(g_GoatCloseOwed && GoatFeedGuardLive() && !GoatCloseOwedDue());'],
 ['main','the real stop is never noted','    GoatCloseRealStopNote(); // B49b (LAG-A)','    // B49b (LAG-A)'],
 ['main','the Friday stop is not the owed close\'s own','      if(!g_GoatCloseRealStop) {g_GoatCloseOwedStop=true; g_GoatCloseOwedStopTime=LastStopoutTime;} // the Friday stop','      // the Friday stop'],
 ['main','a real stop re-alerts each pass','      if(!g_GoatCloseRealStop) {g_GoatCloseOwedStop=true;','      {g_GoatCloseOwedStop=true;'],
 ['main','an ignored restore keeps the owed state','GoatCloseOwedClear(); return;} // a re-init','return;} // a re-init'],
 // The daily stops select once.
 ['main','the daily deals are selected twice','if(GoatFeedGuardLive()) HistorySelect(DStartTime,g_GoatServerNow); else //','if(GoatFeedGuardLive()) HistorySelect(DStartTime,g_GoatServerNow); //'],
 ['main','an open position lets it settle','   if(!g_GoatCloseOwed || open_count>0) return;\n','   if(!g_GoatCloseOwed) return;\n'],
 ['main','it arms with nothing open','if(fired && open_count>0)','if(fired)'],
 ['main','it is silent when armed','      Print(owed_line); Alert(owed_line);\n      return;\n','      return;\n'],
 ['main','closeErrors is not surfaced','" position(s) open on "+_Symbol+", close_errors="+IntegerToString(closeErrors)','" position(s) open on "+_Symbol'],
 ['main','settling lowers another stop','   if(g_GoatCloseOwedStop) {StopOut_Flag=false; LastStopoutTime=g_GoatCloseOwedStopTime;}','   {StopOut_Flag=false; LastStopoutTime=g_GoatCloseOwedStopTime;}'],
 ['main','settling wipes the cooldown','LastStopoutTime=g_GoatCloseOwedStopTime;} // only its own stop','LastStopoutTime=0;} // only its own stop'],
 ['main','settling leaves its stop up','   if(g_GoatCloseOwedStop) {StopOut_Flag=false; LastStopoutTime=g_GoatCloseOwedStopTime;} // only its own stop, and a Mode_Restart cooldown stays\n',''],
 ['main','the assert forgets the stop is its own','   StopOut_Flag=true; g_GoatCloseOwedStop=true; g_GoatCloseOwedStopTime=LastStopoutTime;\n','   StopOut_Flag=true; g_GoatCloseOwedStopTime=LastStopoutTime;\n'],
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
 ['main','the deals stop at the feed\'s clock','     if(GoatFeedGuardLive()) HistorySelect(DStartTime,g_GoatServerNow); else // B49b (LAG-A)','     // B49b (LAG-A)'],
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
 // Timing: off by default, read-only, counted.
 ['header','timing defaults On','Diag_TickTiming               =                   GoatFix_Off;','Diag_TickTiming               =                   GoatFix_On;'],
 ['main','timing ignores its flag','return(Diag_TickTiming==GoatFix_On && GoatManageOnlyLive());','return(GoatManageOnlyLive());'],
 ['main','timing runs in the tester','return(Diag_TickTiming==GoatFix_On && GoatManageOnlyLive());','return(Diag_TickTiming==GoatFix_On);'],
 ['main','timing reads the clock when off','return(GoatTimingLive() ? GetMicrosecondCount() : 0);','return(GetMicrosecondCount());'],
 ['main','timing touches a trade','   g_GoatTimingTicks++; g_GoatTimingTickUS+=spent_us;','   StopOut_Flag=true; g_GoatTimingTicks++; g_GoatTimingTickUS+=spent_us;'],
 ['main','timing arms the guard','return((GoatFeedGuardLive() || GoatTimingLive()) && MAGIC1>0);','return(GoatFeedGuardLive() && MAGIC1>0);'],
 ['main','the status file loses the timing','+GoatTimingText();','+"";'],
 ['main','the max is not the max','   if(spent_us>g_GoatTimingTickMaxUS) g_GoatTimingTickMaxUS=spent_us;\n','   g_GoatTimingTickMaxUS=spent_us;\n'],
 ['main','a section counts twice in the window','   if(slot==6) g_GoatTimingWindowUS+=spent_us;\n','   g_GoatTimingWindowUS+=spent_us;\n'],
 ['main','OnTimer is not in the window','   if(slot==6) g_GoatTimingWindowUS+=spent_us;\n',''],
 ['main','the log is not once a minute','   if(now_ms-g_GoatTimingWindowMs<GOAT_TIMING_LOG_MS) return;\n',''],
 ['main','the window never restarts','   g_GoatTimingWindowMs=now_ms; g_GoatTimingWindowUS=0; g_GoatTimingWindowTicks=0;\n',''],
 ['main','busy is measured wrongly','100.0*(double)g_GoatTimingWindowUS/((double)window_ms*1000.0)','100.0*(double)g_GoatTimingWindowUS/(double)window_ms'],
 ['main','a timing slot is not bounds-checked','if(started_us==0 || slot<0 || slot>=GOAT_TIMING_SLOTS) return;','if(started_us==0) return;'],
 ['main','OnTick is not timed','   GoatTimingTick(timing_tick); // B49b (LAG-T)','   // B49b (LAG-T)'],
 ['main','the per-second block is not timed','    GoatTimingSlot(0,timing_second); // B49b (LAG-T)','    // B49b (LAG-T)'],
 ['main','the exits are not timed','   GoatTimingSlot(4,timing_exits); // B49b (LAG-T)','   // B49b (LAG-T)'],
 // Group B: off by default, bounded, and A never needs it.
 ['header','load changes default On','Fix_TickLoad                  =                   GoatFix_Off;','Fix_TickLoad                  =                   GoatFix_On;'],
 ['main','load changes ignore their flag','return(Fix_TickLoad==GoatFix_On && GoatManageOnlyLive());','return(GoatManageOnlyLive());'],
 ['main','load changes run in the tester','return(Fix_TickLoad==GoatFix_On && GoatManageOnlyLive());','return(Fix_TickLoad==GoatFix_On);'],
 ['main','the hold is not a second','#define GOAT_TICK_LOAD_HOLD_MS 1000','#define GOAT_TICK_LOAD_HOLD_MS 5000'],
 ['main','the hold never lets anything through','   g_GoatTickLoadMs[slot]=now_ms;\n',''],
 ['main','the hold never holds','if(g_GoatTickLoadMs[slot]!=0 && now_ms-g_GoatTickLoadMs[slot]<GOAT_TICK_LOAD_HOLD_MS) return true;','if(false) return true;'],
 ['header','the per-second block is not bounded','   if(GoatTickLoadHold(0)) return false; // B49b (LAG-B)','   // B49b (LAG-B)'],
 ['header','the hold runs before the no-tick run','   if(g_GoatNoTickRun) return true; // B49b (F4): the no-tick timer runs the per-second block, leaving the tick\'s clock state as it was\n   if(GoatTickLoadHold(0)) return false;','   if(GoatTickLoadHold(0)) return false;\n   if(g_GoatNoTickRun) return true; // B49b (F4): the no-tick timer runs the per-second block, leaving the tick\'s clock state as it was\n  '],
 ['main','MLPS is not bounded','    if(context=="tick" && GoatTickLoadHold(dir==OP_BUY ? 2 : 3)) return false; // B49b (LAG-B)','    // B49b (LAG-B)'],
 ['main','an add can skip MLPS','if(context=="tick" && GoatTickLoadHold(dir==OP_BUY ? 2 : 3)) return false;','if(GoatTickLoadHold(dir==OP_BUY ? 2 : 3)) return false;'],
 ['main','the pump is not bounded','    if(GoatTickLoadHold(dir==OP_BUY ? 4 : 5)) return; // B49b (LAG-B)','    // B49b (LAG-B)'],
 ['main','the limit is not five','#define GOAT_TRAIL_FAIL_LIMIT 5','#define GOAT_TRAIL_FAIL_LIMIT 3'],
 ['main','the back-off ignores its flag','bool GoatTrailHeld(const ulong ticket)\n  {\n   if(!GoatTickLoadLive()) return false;\n','bool GoatTrailHeld(const ulong ticket)\n  {\n'],
 ['main','the reset writes with its flag off','void GoatTrailReset(const int side)\n  {\n   if(!GoatTickLoadLive()) return;\n','void GoatTrailReset(const int side)\n  {\n'],
 ['main','the reset indexes by side','for(int t=0;t<ArraySize(g_GoatTrailTicket);t++) if(g_GoatTrailTicket[t]!=0 && g_GoatTrailSide[t]==side) {g_GoatTrailTicket[t]=0; g_GoatTrailFails[t]=0; g_GoatTrailNextMs[t]=0;}','g_GoatTrailFails[side]=0;'],
 ['main','the reset clears every side','if(g_GoatTrailTicket[t]!=0 && g_GoatTrailSide[t]==side) {','if(g_GoatTrailTicket[t]!=0) {'],
 ['main','a hold slot is not bounds-checked','if(!GoatTickLoadLive() || slot<0 || slot>=GOAT_TICK_LOAD_SLOTS) return false;','if(!GoatTickLoadLive()) return false;'],
 ['main','one refused ticket holds the whole side','   for(int t=0;t<ArraySize(g_GoatTrailTicket);t++) if(g_GoatTrailTicket[t]==ticket) return t;\n','   for(int t=0;t<ArraySize(g_GoatTrailTicket);t++) if(g_GoatTrailTicket[t]!=0 || ticket==0) return t;\n'],
 ['main','a row is never reused','      trail_slot=GoatTrailSlot(0);\n      if(trail_slot<0)\n        {','      trail_slot=-1;\n      if(trail_slot<0)\n        {'],
 ['main','NO_CHANGES counts as a refusal','if(retcode==TRADE_RETCODE_DONE || retcode==TRADE_RETCODE_NO_CHANGES)','if(retcode==TRADE_RETCODE_DONE)'],
 ['main','PLACED counts as a refusal','if(!GoatTickLoadLive() || retcode==TRADE_RETCODE_PLACED || retcode==TRADE_RETCODE_DONE_PARTIAL) return;','if(!GoatTickLoadLive() || retcode==TRADE_RETCODE_DONE_PARTIAL) return;'],
 ['main','DONE_PARTIAL counts as a refusal','if(!GoatTickLoadLive() || retcode==TRADE_RETCODE_PLACED || retcode==TRADE_RETCODE_DONE_PARTIAL) return;','if(!GoatTickLoadLive() || retcode==TRADE_RETCODE_PLACED) return;'],
 ['main','the note ignores its flag','if(!GoatTickLoadLive() || retcode==TRADE_RETCODE_PLACED','if(retcode==TRADE_RETCODE_PLACED'],
 ['main','a refusal clears it','if(retcode==TRADE_RETCODE_DONE || retcode==TRADE_RETCODE_NO_CHANGES)','if(retcode==TRADE_RETCODE_DONE || retcode==TRADE_RETCODE_NO_CHANGES || retcode==TRADE_RETCODE_INVALID_STOPS)'],
 ['main','a success never clears it','      g_GoatTrailTicket[trail_slot]=0; g_GoatTrailFails[trail_slot]=0; g_GoatTrailNextMs[trail_slot]=0;\n      return;\n','      return;\n'],
 ['main','recovery is silent','      if(g_GoatTrailFails[trail_slot]>=GOAT_TRAIL_FAIL_LIMIT) Print("GOAT trail back-off: recovered','      if(false) Print("GOAT trail back-off: recovered'],
 ['main','the schedule is flat','int wait_s=(back_step==0 ? 1 : back_step==1 ? 5 : back_step==2 ? 30 : 60);','int wait_s=60;'],
 ['main','the schedule has no 60 s floor','int wait_s=(back_step==0 ? 1 : back_step==1 ? 5 : back_step==2 ? 30 : 60);','int wait_s=(back_step==0 ? 1 : back_step==1 ? 5 : 30);'],
 ['main','an end keeps the back-off','    if(!Virtual) GoatTrailReset(dir); // B49b (LAG-B)','    // B49b (LAG-B)'],
 ['main','group A reads group B','return(g_GoatCloseOwed && GoatFeedGuardLive() && !g_GoatCloseRealStop && !GoatCloseOwedDue());','return(g_GoatCloseOwed && (GoatTickLoadLive() || GoatFeedGuardLive()) && !g_GoatCloseRealStop && !GoatCloseOwedDue());'],
 // A steady fast clock gets a line, and no refusal.
 ['main','the fast clock never logs','   GoatClockFastWatch();\n',''],
 ['main','it logs at once','if(g_GoatClockFastLogged || g_GoatClockFastWrites<GOAT_CLOCK_FAST_WRITES) return;','if(g_GoatClockFastLogged) return;'],
 ['main','it logs every write','if(g_GoatClockFastLogged || g_GoatClockFastWrites<GOAT_CLOCK_FAST_WRITES) return;','if(g_GoatClockFastWrites<GOAT_CLOCK_FAST_WRITES) return;'],
 ['main','a fresh tick does not end the episode','{g_GoatClockFastWrites=0; g_GoatClockFastLogged=false; return;}','return;'],
 ['main','the threshold is not 10 s','#define GOAT_CLOCK_FAST_LOG_S 10','#define GOAT_CLOCK_FAST_LOG_S 8'],
 ['main','a fast clock holds entries','return(g_GoatCloseOwed || g_GoatClockSlowHeld ||','return(g_GoatClockFastLogged || g_GoatCloseOwed || g_GoatClockSlowHeld ||'],
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
