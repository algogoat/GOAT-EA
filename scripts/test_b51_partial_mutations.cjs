// Mutation check for B51's single partial close and demo gate (docs/b50/B50_ALPHA_DESIGN.md sections 8.3 and 8.4): every
// clause of the gate and every rule of GoatSinglePartial* is load-bearing. Each mutant edits GOAT V1.49.mq5 in memory;
// test_b51_partial.cjs, run on the mutated entrypoint (GOAT_EA_MAIN, read by scripts/b50_tick_harness.cjs), must then fail
// on an assertion.
// Equivalent mutants, not listed: the runtime engine and Single_SL_ATR checks in GoatSinglePartial (OnInit refuses both
// combinations); the sentinel and validity checks on Size_SL (a running single has its size, as GoatSingleModifySequence);
// a lost slot (-1: two singles never fill eight slots); s.AccumulateSequenceDealPL in the close (the transaction books the
// same deal once, LedgerBook); b51_deal==0 and b51_id==0 (the model always answers them).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b51_partial.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const EXEMPT='   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return GOAT_ACCOUNT_DEMO_OK;';
const DUE='      bool   b51_due=((b51_buy ? b51_px-b51_open : b51_open-b51_px)>=Single_Partial_ATR*b51_atr-b51_eps);';
const PBE_LINE='      if(!b51_be && Single_Partial_BE && GoatSinglePartialDone(b51_tk) && (b51_buy ? b51_open<=b51_legal+b51_eps : b51_open>=b51_legal-b51_eps)) b51_be=true;';
const MUTANTS=[
 // The demo gate: every clause.
 ['the tester is not exempt',EXEMPT,EXEMPT.replace('MQLInfoInteger(MQL_TESTER) || ','')],
 ['optimization is not exempt',EXEMPT,EXEMPT.replace('MQLInfoInteger(MQL_OPTIMIZATION) || ','')],
 ['forward is not exempt',EXEMPT,EXEMPT.replace(' || MQLInfoInteger(MQL_FORWARD)','')],
 ['a live chart is exempt',EXEMPT,'   return GOAT_ACCOUNT_DEMO_OK;'],
 ['the connection is not checked','   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) {b51_why="the terminal is not connected to the broker"; return GOAT_ACCOUNT_UNKNOWN;}\n','\n'],
 ['a disconnected real account reads as unknown','   ResetLastError();\n   long   b51_login=','   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) {b51_why="not connected"; return GOAT_ACCOUNT_UNKNOWN;}\n   ResetLastError();\n   long   b51_login='],
 ['a stale error counts (no reset)','   ResetLastError();\n   long   b51_login=','   long   b51_login='],
 ['a read error is ignored','   if(b51_err!=0) {b51_why="the account mode cannot be read, error "+IntegerToString(b51_err); return GOAT_ACCOUNT_UNKNOWN;}\n','\n'],
 ['a read error reads as not demo','+IntegerToString(b51_err); return GOAT_ACCOUNT_UNKNOWN;}','+IntegerToString(b51_err); return GOAT_ACCOUNT_NOT_DEMO;}'],
 ['no login passes','   if(b51_login<=0 || b51_server=="") {','   if(b51_server=="") {'],
 ['login 0 passes','   if(b51_login<=0 || b51_server=="") {','   if(b51_login<0 || b51_server=="") {'],
 ['no server passes','   if(b51_login<=0 || b51_server=="") {','   if(b51_login<=0) {'],
 ['the mode is not checked','   if(b51_mode!=ACCOUNT_TRADE_MODE_DEMO) {b51_why="this account is not a demo account"; return GOAT_ACCOUNT_NOT_DEMO;}\n','\n'],
 ['a contest account passes','   if(b51_mode!=ACCOUNT_TRADE_MODE_DEMO) {b51_why=','   if(b51_mode==ACCOUNT_TRADE_MODE_REAL) {b51_why='],
 ['an input overrides the gate','   ResetLastError();\n   long   b51_login=','   if(Single_Flat_Only) return GOAT_ACCOUNT_DEMO_OK;\n   ResetLastError();\n   long   b51_login='],
 ['OnInit does not refuse','      if(b51_account==GOAT_ACCOUNT_NOT_DEMO) {Alert(','      if(false) {Alert('],
 ['OnInit refuses an unread account (unloads it)','      if(b51_account==GOAT_ACCOUNT_NOT_DEMO) {Alert(','      if(b51_account!=GOAT_ACCOUNT_DEMO_OK) {Alert('],
 ['OnInit refuses as a parameter error','account ("+b51_account_why+")."); return INIT_FAILED;}','account ("+b51_account_why+")."); return INIT_PARAMETERS_INCORRECT;}'],
 ['the grid is gated too','   if(Engine_Mode==Engine_Single)\n     {\n      string b51_account_why="";','   {\n      string b51_account_why="";'],
 ['OnInit leaves nothing pending','      g_GoatSingleAccountPending=(b51_account==GOAT_ACCOUNT_UNKNOWN);','      g_GoatSingleAccountPending=false;'],
 ['alpha\'s netting check unloads an unread account','   if(Engine_Mode==Engine_Single && !GoatSingleAccountUnknown() && AccountInfoInteger(ACCOUNT_MARGIN_MODE)','   if(Engine_Mode==Engine_Single && AccountInfoInteger(ACCOUNT_MARGIN_MODE)'],
 ['alpha\'s netting check is dropped','   if(Engine_Mode==Engine_Single && !GoatSingleAccountUnknown() && AccountInfoInteger(ACCOUNT_MARGIN_MODE)','   if(false && AccountInfoInteger(ACCOUNT_MARGIN_MODE)'],
 ['an open does not ask','   {string b51_why=""; if(GoatSingleAccountState(b51_why)!=GOAT_ACCOUNT_DEMO_OK || g_GoatSingleAccountPending) {','   {string b51_why=""; if(false) {'],
 ['an open opens on unknown','if(GoatSingleAccountState(b51_why)!=GOAT_ACCOUNT_DEMO_OK || g_GoatSingleAccountPending) {','if(GoatSingleAccountState(b51_why)==GOAT_ACCOUNT_NOT_DEMO || g_GoatSingleAccountPending) {'],
 ['an open ignores pending','!=GOAT_ACCOUNT_DEMO_OK || g_GoatSingleAccountPending) {','!=GOAT_ACCOUNT_DEMO_OK) {'],
 ['an open logs every refusal, not one per code','{GoatSingleRefusal(b50_side,8,s.Desc,(b51_why!="" ? b51_why : "the account is being verified")); return false;}','{Print(s.Desc,": Single refused"); return false;}'],
 ['the watch is never called','   GoatSingleAccountWatch(); // B51','   ; // B51'],
 ['a positive non-demo is not removed','   if(b51_state==GOAT_ACCOUNT_NOT_DEMO) {GoatSingleAccountRemove(b51_why); return;}\n','\n'],
 ['removal repeats','   if(g_GoatSingleAccountRemoved) return;\n','\n'],
 ['an unknown account is removed','   if(b51_state==GOAT_ACCOUNT_NOT_DEMO) {GoatSingleAccountRemove(b51_why); return;}','   if(b51_state!=GOAT_ACCOUNT_DEMO_OK) {GoatSingleAccountRemove(b51_why); return;}'],
 ['the watch removes the grid','   if(Engine_Mode!=Engine_Single) return;\n   string b51_why="";\n   int    b51_state','   string b51_why="";\n   int    b51_state'],
 ['netting is not checked once verified','   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) {GoatSingleAccountRemove("netting is not supported"); return;}\n','\n'],
 ['nothing is adopted once verified','   Seq_Buy.AdoptOpenPositions(); Seq_Sell.AdoptOpenPositions();\n  }\n','  }\n'],
 ['pending never clears','   g_GoatSingleAccountPending=false;\n   Print("Single-trade engine: the account is verified','   Print("Single-trade engine: the account is verified'],
 ['Random_Direction runs on a demo','   if(Random_Direction && !MQLInfoInteger(MQL_TESTER))  {Alert(','   if(Random_Direction && !MQLInfoInteger(MQL_TESTER) && AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)  {Alert('],
 // The trigger.
 ['the call site is dropped','    GoatSinglePartial(); // B51 (section 8.3)','    ; // B51 (section 8.3)'],
 ['the partial runs after the stop moves','    GoatSinglePartial(); // B51 (section 8.3): the single\'s one partial close, before its stop moves\n    GoatSingleModify(); // B51 (beta-1b): the single\'s break-even and trailing (TrailingStoploss never runs for a single: its lock is parked)\n','    GoatSingleModify(); // B51 (beta-1b): the single\'s break-even and trailing (TrailingStoploss never runs for a single: its lock is parked)\n    GoatSinglePartial(); // B51 (section 8.3)\n'],
 ['only the buy is managed','   GoatSinglePartialSequence(Seq_Sell,b51_fresh);\n','\n'],
 ['it fires a point early',DUE,DUE.replace('-b51_eps','-_Point*1.001')],
 ['it fires a point late',DUE,DUE.replace('>=Single_Partial_ATR*b51_atr-b51_eps','>Single_Partial_ATR*b51_atr+b51_eps')],
 ['the buy reads the ask','   GoatSinglePartialSequence(Seq_Buy,b51_fresh);\n','   {double b51_b=bid; bid=ask; GoatSinglePartialSequence(Seq_Buy,b51_fresh); bid=b51_b;}\n'],
 ['the sell reads the bid','   GoatSinglePartialSequence(Seq_Sell,b51_fresh);\n','   {double b51_a=ask; ask=bid; GoatSinglePartialSequence(Seq_Sell,b51_fresh); ask=b51_a;}\n'],
 ['the ATR is the stop size','   double b51_atr=s.Size_SL/Single_SL_ATR;                   // the entry\'s ATR, the same after a restart','   double b51_atr=s.Size_SL;'],
 ['the ATR is the forming bar\'s','   double b51_atr=s.Size_SL/Single_SL_ATR;                   // the entry\'s ATR, the same after a restart','   double b51_atr_buf[]; double b51_atr=(CopyBuffer(ATR_MA_handle,0,0,1,b51_atr_buf)==1 ? b51_atr_buf[0] : 0.0);'],
 ['an adopted single without its sizes closes','   if(s.Adopted && !s.AdoptSizes) return;                    // as GoatSingleModifySequence: no frozen sizes, no entry ATR\n','\n'],
 ['it runs at Single_Partial_ATR=0',' || !(Single_Partial_ATR>0.0)) return;\n',') return;\n'],
 // Legal volumes.
 ['the close rounds up','MathFloor(b51_vol*Single_Partial_Fraction/b51_vstep+1e-9)','MathCeil(b51_vol*Single_Partial_Fraction/b51_vstep-1e-9)'],
 ['binary rounding tips the close down','MathFloor(b51_vol*Single_Partial_Fraction/b51_vstep+1e-9)','MathFloor(b51_vol*Single_Partial_Fraction/b51_vstep-1e-9)'],
 ['no minimum for the close','   if(b51_cut<b51_vmin-1e-9)  return "the close is below the volume minimum "+DoubleToString(b51_vmin,2);\n','\n'],
 ['no minimum for the remainder','   if(b51_rest<b51_vmin-1e-9) return "the remainder is below the volume minimum "+DoubleToString(b51_vmin,2);\n','\n'],
 ['no maximum for the close','   if(b51_vmax>0.0 && b51_cut>b51_vmax+1e-9) return "the close is above the volume maximum "+DoubleToString(b51_vmax,2);\n','\n'],
 ['no step check on the remainder','   if(MathAbs(b51_rest/b51_vstep-MathRound(b51_rest/b51_vstep))>1e-6) return "the remainder is not a multiple of the volume step "+DoubleToString(b51_vstep,2);\n','\n'],
 ['no guard on the step','   if(!(b51_vmin>0.0) || !(b51_vstep>0.0)) return "no volume minimum or step";','   if(!(b51_vmin>0.0)) return "no volume minimum or step";'],
 ['no guard on the minimum','   if(!(b51_vmin>0.0) || !(b51_vstep>0.0)) return "no volume minimum or step";','   if(!(b51_vstep>0.0)) return "no volume minimum or step";'],
 ['an illegal volume is retried every check','   if(b51_why!="")\n     {\n      g_GoatPartialState[b51_slot]=GOAT_PARTIAL_SKIPPED;\n','   if(b51_why!="")\n     {\n'],
 ['an invalid-volume refusal retries','   if(b51_ret==TRADE_RETCODE_INVALID_VOLUME)\n','   if(false)\n'],
 // Once only: the slot and the broker's history.
 ['its own fill is not remembered','      g_GoatPartialState[b51_slot]=GOAT_PARTIAL_DONE; g_GoatPartialFails[b51_slot]=0; g_GoatPartialNext[b51_slot]=0;\n','      g_GoatPartialFails[b51_slot]=0; g_GoatPartialNext[b51_slot]=0;\n'],
 ['the history is not read (a restart closes again)','      int b51_truth=GoatSinglePartialTruth(b51_tk,b51_entry);\n','      int b51_truth=0;\n'],
 ['the history is read once, not before each send','      if(b51_state==GOAT_PARTIAL_PENDING && !b51_due && !b51_tried) continue;\n','      if(b51_state==GOAT_PARTIAL_PENDING && !b51_due && !b51_tried) continue;\n      if(b51_state==GOAT_PARTIAL_PENDING && b51_due) {if(TimeCurrent()>=g_GoatPartialNext[b51_k]) GoatSinglePartialClose(s,b51_k,b51_tk,PositionGetDouble(POSITION_VOLUME)); continue;}\n'],
 ['the history is read on every check','      if(b51_state==GOAT_PARTIAL_PENDING && !b51_due && !b51_tried) continue;\n','\n'],
 ['unknown sends','      if(b51_truth<0)\n        {','      if(false)\n        {'],
 ['a failed history read reads as none','   if(b51_id==0 || !HistorySelectByPosition(b51_id)) return -1;','   if(b51_id==0 || !HistorySelectByPosition(b51_id)) return 0;'],
 ['no entry deal reads as none','   if(!(b51_in>0.0)) return -1;\n','   if(!(b51_in>0.0)) return 0;\n'],
 ['an exit deal does not count','   if(b51_out) return 1;\n','\n'],
 ['a close-by does not count','else if(b51_kind==DEAL_ENTRY_OUT || b51_kind==DEAL_ENTRY_OUT_BY) b51_out=true;','else if(b51_kind==DEAL_ENTRY_OUT) b51_out=true;'],
 ['the volume does not count','   return (b51_vol<b51_in-1e-8 ? 1 : 0);','   return 0;'],
 // A late fill and the quotes (the review of GOAT-EA#289).
 ['the volume is not read at the send','   if(b51_vol<b51_entry-1e-8)\n','   if(false)\n'],
 ['a late fill below the trigger is not reconciled','      bool   b51_tried=(g_GoatPartialFails[b51_k]>0);','      bool   b51_tried=false;'],
 ['a close goes out below the trigger','      if(b51_due) GoatSinglePartialClose(s,b51_k,b51_tk,b51_entry);\n','      if(b51_due || b51_tried) GoatSinglePartialClose(s,b51_k,b51_tk,b51_entry);\n'],
 ['the reads below the trigger run every check','      else if(b51_tried) g_GoatPartialNext[b51_k]=TimeCurrent()+GOAT_SINGLE_BACKOFF_STEADY_S;','      else if(false) g_GoatPartialNext[b51_k]=TimeCurrent();'],
 ['a stale quote triggers the partial','      if(!b51_fresh) b51_due=false;\n','\n'],
 ['a stale quote moves a stop','   if(!GoatSingleQuotesFresh()) return; // B51 (section 8.3)','   ; // B51 (section 8.3)'],
 ['OnInit\'s tick counts','   if(g_GoatSingleInitTick) return false;\n','\n'],
 ['OnInit does not flag its tick','   g_GoatSingleInitTick=true;  // B51 (section 8.3)','   ;  // B51 (section 8.3)'],
 ['the flag stays up','   g_GoatSingleInitTick=false; // B51 (section 8.3)','   ; // B51 (section 8.3)'],
 ['an empty bid passes','(b51_read && bid>0.0 && ask>0.0 &&','(b51_read && ask>0.0 &&'],
 ['an empty ask passes','(b51_read && bid>0.0 && ask>0.0 &&','(b51_read && bid>0.0 &&'],
 ['the age is not read',' && (long)TimeTradeServer()-(long)b51_tick.time<=GOAT_SINGLE_QUOTE_MAX_AGE_S);',');'],
 ['31 s is fresh','#define GOAT_SINGLE_QUOTE_MAX_AGE_S 30','#define GOAT_SINGLE_QUOTE_MAX_AGE_S 31'],
 ['29 s is the limit','#define GOAT_SINGLE_QUOTE_MAX_AGE_S 30','#define GOAT_SINGLE_QUOTE_MAX_AGE_S 29'],
 ['the stale line repeats','   b51_stale=!b51_fresh;\n','\n'],
 ['the partial runs under Ledger_Legacy','   if(Single_Partial_ATR>0.0 && Ledger_Mode!=Ledger_PositionJoin) {','   if(false) {'],
 ['a history done is not remembered','      if(b51_truth>0)\n        {\n         g_GoatPartialState[b51_k]=GOAT_PARTIAL_DONE;\n','      if(b51_truth>0)\n        {\n'],
 ['the level keeps the old volume after a lost reply','         g_GoatPartialState[b51_k]=GOAT_PARTIAL_DONE;\n         s.RefreshTicketLots();\n','         g_GoatPartialState[b51_k]=GOAT_PARTIAL_DONE;\n'],
 ['the level keeps the old volume after a fill','      s.RefreshTicketLots();\n      Print(s.Desc,": Single partial close: ticket="','      Print(s.Desc,": Single partial close: ticket="'],
 ['a stale slot is never reused','      if(g_GoatPartialTicket[b51_j]==0 || !PositionSelectByTicket(g_GoatPartialTicket[b51_j]))','      if(g_GoatPartialTicket[b51_j]==0)'],
 ['a reused slot keeps its state','         g_GoatPartialTicket[b51_j]=tk; g_GoatPartialState[b51_j]=GOAT_PARTIAL_UNREAD; g_GoatPartialFails[b51_j]=0;','         g_GoatPartialTicket[b51_j]=tk; g_GoatPartialFails[b51_j]=0;'],
 ['the position is not selected after the slot search','      if(b51_k<0 || !PositionSelectByTicket(b51_tk)) continue;','      if(b51_k<0) continue;'],
 ['the held line repeats','         if(b51_due && !g_GoatPartialNoted[b51_k])\n','         if(b51_due)\n'],
 ['the held line prints below the trigger','         if(b51_due && !g_GoatPartialNoted[b51_k])\n','         if(!g_GoatPartialNoted[b51_k])\n'],
 // A refused close.
 ['no back-off','      if((b51_due || b51_tried) && TimeCurrent()<g_GoatPartialNext[b51_k]) continue;   // backing off: no read, no attempt, no line\n','\n'],
 ['the wait is never set','   g_GoatPartialNext[b51_slot]=TimeCurrent()+b51_wait;\n','\n'],
 ['the wait ends a second late','      if((b51_due || b51_tried) && TimeCurrent()<g_GoatPartialNext[b51_k]) continue;','      if((b51_due || b51_tried) && TimeCurrent()<=g_GoatPartialNext[b51_k]) continue;'],
 ['the first wait is 1 s','   int b51_wait=(b51_count==1 ? GOAT_SINGLE_BACKOFF_2_S :','   int b51_wait=(b51_count==1 ? GOAT_SINGLE_BACKOFF_1_S :'],
 ['the second wait is 60 s','(b51_count==2 ? GOAT_SINGLE_BACKOFF_3_S : GOAT_SINGLE_BACKOFF_STEADY_S)','(b51_count==2 ? GOAT_SINGLE_BACKOFF_STEADY_S : GOAT_SINGLE_BACKOFF_STEADY_S)'],
 ['the steady wait is 30 s','(b51_count==2 ? GOAT_SINGLE_BACKOFF_3_S : GOAT_SINGLE_BACKOFF_STEADY_S)','(b51_count==2 ? GOAT_SINGLE_BACKOFF_3_S : GOAT_SINGLE_BACKOFF_3_S)'],
 ['a failure keeps no count','   int b51_count=++g_GoatPartialFails[b51_slot];','   int b51_count=1;'],
 ['one back-off for every ticket','   for(int b51_j=0;b51_j<GOAT_SINGLE_PARTIAL_SLOTS;b51_j++) if(g_GoatPartialTicket[b51_j]==tk) return b51_j;\n','   for(int b51_j=0;b51_j<GOAT_SINGLE_PARTIAL_SLOTS;b51_j++) if(g_GoatPartialTicket[b51_j]!=0 && (g_GoatPartialTicket[b51_j]==tk || g_GoatPartialFails[b51_j]>0)) return b51_j;\n'],
 ['no line for a failure','   Print(s.Desc,": Single partial close failed: ticket=",','   if(false) Print(s.Desc,": Single partial close failed: ticket=",'],
 ['the attempts are not counted','   Pclosed++;\n   // True from','   // True from'],
 ['the failures are not counted','   PcloseErrors++;\n   if(b51_ret==TRADE_RETCODE_INVALID_VOLUME)','   if(b51_ret==TRADE_RETCODE_INVALID_VOLUME)'],
 // The retcode and the volume decide a fill (review of GOAT-EA#287).
 ['a true return is a fill whatever the retcode and volume','   if(b51_sent && (b51_ret==TRADE_RETCODE_DONE || b51_ret==TRADE_RETCODE_DONE_PARTIAL) && b51_left<b51_vol-1e-8)','   if(b51_sent)'],
 ['the volume is not confirmed',' || b51_ret==TRADE_RETCODE_DONE_PARTIAL) && b51_left<b51_vol-1e-8)',' || b51_ret==TRADE_RETCODE_DONE_PARTIAL))'],
 ['a partial fill is not a fill','(b51_ret==TRADE_RETCODE_DONE || b51_ret==TRADE_RETCODE_DONE_PARTIAL)','(b51_ret==TRADE_RETCODE_DONE)'],
 ['any lower volume is a fill, whatever the retcode','   if(b51_sent && (b51_ret==TRADE_RETCODE_DONE || b51_ret==TRADE_RETCODE_DONE_PARTIAL) && b51_left<b51_vol-1e-8)','   if(b51_left<b51_vol-1e-8)'],
 ['the line logs what was asked, not what filled','" closed=",DoubleToString(b51_vol-b51_left,2)','" closed=",DoubleToString(b51_cut,2)'],
 ['the line logs the planned remainder','" remainder=",DoubleToString(b51_left,2)," retcode="','" remainder=",DoubleToString(b51_rest,2)," retcode="'],
];
// Each field of the failure line.
for(const [name,from] of [['the bid','," bid=",DoubleToString(bid,_Digits)," ask=",DoubleToString(ask,_Digits),\n         " volume="'],['the retcode',' retcode=",IntegerToString(b51_ret),\n         " consecutive="'],['the count','" consecutive=",IntegerToString(b51_count)," backoff="'],['the wait','," backoff=",IntegerToString(b51_wait),"s");']]){
 const to={'the bid':',\n         " volume="','the retcode':' x=",IntegerToString(b51_ret),\n         " consecutive="','the count':'" backoff="','the wait':');'}[name];
 MUTANTS.push(['the failure line drops '+name,from,to]);
}
MUTANTS.push(
 ['the failure line drops the close','" volume=",DoubleToString(b51_vol,2)," close=",DoubleToString(b51_cut,2)," retcode="','" volume=",DoubleToString(b51_vol,2)," retcode="'],
 ['the failure line drops the volume','" volume=",DoubleToString(b51_vol,2)," close=",DoubleToString(b51_cut,2)," retcode="','" close=",DoubleToString(b51_cut,2)," retcode="'],
 // Single_Partial_BE.
 ['Single_Partial_BE alone never reaches the move',' && !Single_Partial_BE)) return; // B51 (section 8.3)',')) return; // B51 (section 8.3)'],
 ['the flag is ignored',PBE_LINE,PBE_LINE.replace('Single_Partial_BE && ','')],
 ['it moves before the fill',PBE_LINE,PBE_LINE.replace('GoatSinglePartialDone(b51_tk) && ','')],
 ['it clamps',PBE_LINE,PBE_LINE.replace(' && (b51_buy ? b51_open<=b51_legal+b51_eps : b51_open>=b51_legal-b51_eps)','')],
 ['the sell tests the wrong side',PBE_LINE,PBE_LINE.replace('b51_open>=b51_legal-b51_eps','b51_open<=b51_legal+b51_eps')],
 ['a skipped partial counts as done','      if(g_GoatPartialTicket[b51_j]==tk) return (g_GoatPartialState[b51_j]==GOAT_PARTIAL_DONE);','      if(g_GoatPartialTicket[b51_j]==tk) return (g_GoatPartialState[b51_j]>=GOAT_PARTIAL_DONE);'],
 ['any read position counts as done','      if(g_GoatPartialTicket[b51_j]==tk) return (g_GoatPartialState[b51_j]==GOAT_PARTIAL_DONE);','      if(g_GoatPartialTicket[b51_j]==tk) return (g_GoatPartialState[b51_j]>=GOAT_PARTIAL_PENDING);'],
 // OnInit.
 ['OnInit accepts a negative trigger or fraction','   if(Single_Partial_ATR<0.0 || Single_Partial_Fraction<0.0) {','   if(false) {'],
 ['OnInit accepts a negative fraction','   if(Single_Partial_ATR<0.0 || Single_Partial_Fraction<0.0) {','   if(Single_Partial_ATR<0.0) {'],
 ['OnInit accepts a fraction of 1','   if(Single_Partial_Fraction>=1.0) {','   if(Single_Partial_Fraction>1.0) {'],
 ['OnInit accepts half a partial','   if((Single_Partial_ATR>0.0)!=(Single_Partial_Fraction>0.0)) {','   if(false) {'],
 ['OnInit accepts Single_Partial_BE alone','   if(Single_Partial_BE && !(Single_Partial_ATR>0.0)) {','   if(false) {'],
 ['OnInit accepts the grid with a partial','   if(Engine_Mode!=Engine_Single && Single_Partial_ATR>0.0) {','   if(false) {'],
);
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b51-partial-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:300000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
const unmutated=runOn(MAIN);
assert.equal(unmutated.status,0,'the unmutated test passes on the scratch entrypoint: '+unmutated.stderr);
let killed=0;const survivors=[],crashed=[];
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 if(r.status===0){survivors.push(label);continue;}
 if(!/AssertionError \[ERR_ASSERTION\]/.test(r.stderr)){crashed.push(label+': '+r.stderr.slice(0,400));continue;}
 if(process.env.B51_MUTANT_DEBUG) console.log(label+': '+(r.stderr.match(/AssertionError \[ERR_ASSERTION\]:[^\n]*/)||[''])[0]);
 killed++;
}
assert.deepEqual(crashed,[],'mutants crashed instead of failing an assertion');
assert.deepEqual(survivors,[],'mutants survived');
console.log(JSON.stringify({mutants:MUTANTS.length,killed,test:'b51_partial_mutations'}));
