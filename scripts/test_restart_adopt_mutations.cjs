// Mutation check for B49a's F1-lite (restart adoption, manage-only, the restart record): every guard is
// load-bearing. Each mutant edits GOAT V1.49.mq5 in memory; test_restart_adopt.cjs, run on the mutated entrypoint
// (GOAT_EA_MAIN), must then fail. Anchors sit on F1-lite lines, never on the build ID or marker lines.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_restart_adopt.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 // Adoption: whose positions, which record.
 ['adoption takes the other side\'s positions','     if((dir==OP_BUY && type!=POSITION_TYPE_BUY) || (dir==OP_SELL && type!=POSITION_TYPE_SELL)) continue;\n',''],
 ['adoption takes another magic\'s positions','tk==0 || PositionGetInteger(POSITION_MAGIC)!=MAGIC1 || PositionGetString','tk==0 || PositionGetString'],
 ['adoption overrides a running sequence','    if(!PersistLive() || Active) return false;\n    ulong tickets[]','    if(!PersistLive()) return false;\n    ulong tickets[]'],
 ['every record matches','    bool matched=false;','    bool matched=true;'],
 ['the start-time rule is dropped (ticket only)','     matched=(opened[0]>=(long)rec_t && PersistRead("N",rec_n) && count<=(int)rec_n);','     matched=false;'],
 ['the count bound is dropped (Claude-Mac 6428447507)','     matched=(opened[0]>=(long)rec_t && PersistRead("N",rec_n) && count<=(int)rec_n);','     matched=(opened[0]>=(long)rec_t);'],
 ['the ticket rule is dropped (start time only)','     for(int i=0; i<count && !matched; i++) if(tickets[i]==(ulong)rec_tk) matched=true;\n',''],
 ['sentinel sizes are restored','    for(int i=0; i<5 && sizes; i++) if(size[i]==1234.5 || !MathIsValidNumber(size[i])) sizes=false;\n',''],
 ['the realized P/L is not restored','     SequenceRealizedPL=(Ledger_Mode==Ledger_PositionJoin ? RealizedFromHistory((long)rec_t,rec_r) : rec_r);','     SequenceRealizedPL=0.0;'],
 ['closes made while down are not recounted (P2-2)','(Ledger_Mode==Ledger_PositionJoin ? RealizedFromHistory((long)rec_t,rec_r) : rec_r)','rec_r'],
 ['the recount ignores exit fees','     realized+=ClosedDealPL(deal)+HistoryDealGetDouble(deal,DEAL_FEE);','     realized+=ClosedDealPL(deal);'],
 ['the recount takes the other side\'s entries','     if(HistoryDealGetInteger(deal,DEAL_TYPE)!=(dir==OP_BUY ? DEAL_TYPE_BUY : DEAL_TYPE_SELL)) continue;\n',''],
 ['an adopted basket is not active','    Active=Traded=true;\n    Adopted=true;','    Traded=true;\n    Adopted=true;'],
 ['an unmatched basket keeps the stale record','     PersistStart(tickets[0]);           // deletes the record','     ;           // deletes the record'],
 // Not a mutant: `if(sizes) UpdateLockTPSL(...)` in AdoptOpenPositions is defence in depth. UpdateLockTPSL returns
 // first for an adopted basket without sizes ("the stops guard is gone" below kills that guard's removal).
 // P1-a, P1-b, P2-1.
 ['GetSize never refills an empty ATR_Buf (P1-a)',' || ArraySize(ATR_Buf)==0) // B49a (F1-lite)',') // B49a (F1-lite)'],
 ['an adopted basket\'s SL can be loosened (P1-b)','       if(Adopted) Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);','       ;'],
 ['the trailing level is not seeded','    for(int i=0; i<count; i++) Level_TSL=TighterBiasStop(Level_TSL,TradeLevels[i].sl);','    ;'],
 ['the position count is not seeded (P2-1)','    if(dir==OP_BUY) LastTradeCountBuy=count; else LastTradeCountSell=count;','    ;'],
 // Claude-Mac's re-check of 1c8cc21: OnInit's first tick before the ATR indicator is ready.
 ['the adopted buy runs the grid check','      if(Seq_Buy.Adopted) LastBuyTradeSignal = false; else // B49a','      // B49a'],
 ['the adopted sell runs the grid check','      if(Seq_Sell.Adopted) LastSellTradeSignal = false; else // B49a','      // B49a'],
 ['GetSize indexes an empty ATR_Buf','   if(ArraySize(ATR_Buf)==0) {if(GoatSizeNeedsAtr(type)) return GoatAtrUnavailable(type);} else g_goat_atr_unavailable_logged=false;','   ;'],
 ['the shift-1 ATR_Pips reads an empty buffer','CopyBuffer(ATR_MA_handle,0,1,1,ATR_Buf); if(ArraySize(ATR_Buf)>0) ATR_Pips','CopyBuffer(ATR_MA_handle,0,1,1,ATR_Buf); ATR_Pips'],
 ['the shift-0 ATR_Pips reads an empty buffer','CopyBuffer(ATR_MA_handle,0,0,1,ATR_Buf); if(ArraySize(ATR_Buf)>0) ATR_Pips','CopyBuffer(ATR_MA_handle,0,0,1,ATR_Buf); ATR_Pips'],
 ['a pips-mode size answers the sentinel','   if(type==OP_SL)      return SL_Pips_<0;','   if(type==OP_SL)      return true;'],
 ['the unavailable log is never re-armed','} else g_goat_atr_unavailable_logged=false; // B49a','} // B49a'],
 ['every unavailable size is logged','   if(!g_goat_atr_unavailable_logged)\n','   if(true)\n'],
 ['a start on an unread ATR size goes ahead','     if(SizesUnavailable()) return false; // B49a','     // B49a'],
 ['a refused start keeps the sentinel size','    if(Size_Grid==GOAT_ATR_UNAVAILABLE) Size_Grid=1234.5;\n',''],
 ['known sizes are refused too','       && Size_SL!=GOAT_ATR_UNAVAILABLE && Size_TSL!=GOAT_ATR_UNAVAILABLE) return false;','       && Size_SL!=GOAT_ATR_UNAVAILABLE && Size_TSL!=GOAT_ATR_UNAVAILABLE) return true;'],
 // Codex GOAT-EA#267 P2: the trade count (C).
 ['the start record has no C','&& PersistWrite("C",(double)Trades_Count) && PersistWrite("R",SequenceRealizedPL)','&& PersistWrite("R",SequenceRealizedPL)'],
 ['a later level does not update C','    if(PersistWrite("N",(double)Level_Count) && PersistWrite("C",(double)Trades_Count)) {PersistedLevels','    if(PersistWrite("N",(double)Level_Count)) {PersistedLevels'],
 ['the flush does not update C',' || !PersistWrite("C",(double)Trades_Count)) return;',') return;'],
 ['the end keeps C','{"T","TK","G","L","TP","SL","TS","N","C","R"}','{"T","TK","G","L","TP","SL","TS","N","R"}'],
 ['adoption keeps the survivor count','     if(PersistRead("C",rec_c) && (int)rec_c>=count) Trades_Count=(int)rec_c;','     ;'],
 ['C may lower the count below the live positions','     if(PersistRead("C",rec_c) && (int)rec_c>=count) Trades_Count=(int)rec_c;','     if(PersistRead("C",rec_c)) Trades_Count=(int)rec_c;'],
 // Not a mutant: GoatSizeNeedsAtr's GRID_VALID rule is defence in depth. Without it GRID_VALID reads GRID_MIN and
 // GRID_MAX through GetSize, which answer the sentinel themselves, so the result is the sentinel or a pips clamp.
 // Manage-only.
 ['manage-only does not freeze adds','    if(!Adopted && !PersistFailed && !g_GoatStateFailed && g_GoatManageOnly==GOAT_MANAGE_NONE) {ManageOnlyLogged=false; return false;}','    {ManageOnlyLogged=false; return false;}'],
 ['the freeze logs every add','    if(!ManageOnlyLogged)\n','    if(true)\n'],
 ['Add_Level does not consult manage-only','    if(!Virtual && ManageOnlyFrozen(Level_Count+1)) return false;','    if(false) return false;'],
 ['the stops guard is gone','    if(Adopted && !AdoptSizes) return; // B49a (F1-lite): an adopted basket without its frozen sizes keeps its broker SL/TP\n    Level_Lock','    Level_Lock'],
 // The record.
 ['the record is written in the tester','    if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return false;\n    return(Mode_Operation','    return(Mode_Operation'],
 ['T is written first','    if(!(PersistWrite("TK",(double)PersistFirstTicket)','    if(!(PersistWrite("T",(double)start_msc) && PersistWrite("TK",(double)PersistFirstTicket)'],
 ['a start keeps the older record (P2-3)','    PersistEnd();\n    if(PersistWriteAll(start_msc)) PersistStartMsc=start_msc;','    if(PersistWriteAll(start_msc)) PersistStartMsc=start_msc;'],
 ['later levels do not update the level count','{if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket); else PersistLevels();}','{if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket);}'],
 ['a level the hook does not see never reaches N (Codex)',' && Level_Count==PersistedLevels) return;',') return;'],
 ['the record is not flushed to disk','    GlobalVariablesFlush();\n    PersistedRealized=SequenceRealizedPL; PersistedLevels=Level_Count;\n    PersistTouchedDay','    PersistedRealized=SequenceRealizedPL; PersistedLevels=Level_Count;\n    PersistTouchedDay'],
 ['a realized write is not flushed to disk','    GlobalVariablesFlush();\n    PersistedRealized=SequenceRealizedPL; PersistedLevels=Level_Count;\n   }','    PersistedRealized=SequenceRealizedPL; PersistedLevels=Level_Count;\n   }'],
 ['the deletion is not flushed to disk','    for(int i=0; i<ArraySize(fields); i++) GlobalVariableDel(PersistKey(fields[i]));\n    GlobalVariablesFlush();','    for(int i=0; i<ArraySize(fields); i++) GlobalVariableDel(PersistKey(fields[i]));'],
 ['no daily rewrite (the 4-week expiry)','    bool touch=(TimeGMT()-TimeGMT()%86400!=PersistTouchedDay);','    bool touch=false;'],
 ['the daily rewrite ignores the rate bound','    if(!force && GetTickCount()-PersistFlushedMs<GOAT_SQ_FLUSH_MS) return;\n','    if(!force && GetTickCount()-PersistFlushedMs<GOAT_SQ_FLUSH_MS && TimeGMT()-TimeGMT()%86400==PersistTouchedDay) return;\n'],
 ['the flush is not rate-bound','    if(!force && GetTickCount()-PersistFlushedMs<GOAT_SQ_FLUSH_MS) return;\n',''],
 ['a failed write does not freeze','    PersistFailed=true;\n    return false;','    return false;'],
 ['the end keeps the record','     PersistEnd(); PersistReset(); // B49a (F1-lite)','     PersistReset(); // B49a (F1-lite)'],
 ['OnInit does not adopt','     Seq_Buy.AdoptOpenPositions(); Seq_Sell.AdoptOpenPositions();','     ;'],
 // B49b PR-0: P-B49b-start-nonfinite-distances.
 ['a RiskperSeq start on an unusable distance goes ahead','      if(Mode_Lots==RiskperSeq && StartDistancesUnavailable()) return false; // B49b','      // B49b'],
 ['only non-finite distances are refused (the sentinel passes)','     if(!MathIsValidNumber(Distances[i]) || Distances[i]>=GOAT_ATR_UNAVAILABLE) unavailable=true;','     if(!MathIsValidNumber(Distances[i])) unavailable=true;'],
 ['a NaN distance passes','     if(!MathIsValidNumber(Distances[i]) || Distances[i]>=GOAT_ATR_UNAVAILABLE) unavailable=true;','     if(Distances[i]>=GOAT_ATR_UNAVAILABLE) unavailable=true;'],
 ['a refused start keeps its sizing','    if(!Active && !Traded)\n    {\n     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;','    if(false)\n    {\n     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;'],
 ['an active sequence loses its sizing','    if(!Active && !Traded)\n    {\n     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;','    if(true)\n    {\n     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;'],
 ['the refusal logs every time','    if(!g_goat_start_distances_logged[side])\n','    if(true)\n'],
 ['the refusal log is never re-armed','    if(!unavailable) {g_goat_start_distances_logged[side]=false; return false;}','    if(!unavailable) return false;'],
 ['both sides share one log flag','    int side=(dir==OP_SELL) ? 1 : 0;\n    bool unavailable=false;','    int side=0;\n    bool unavailable=false;'],
 // B49b PR-0: P-B49b-adopt-rescue-tp.
 ['an adopted basket\'s TP can be loosened','       if(Adopted) Level_TP_ = TighterTakeProfit(PositionGetDouble(POSITION_TP),Level_TP_);','       ;'],
 ['a buy keeps the farther TP','    if(dir==OP_BUY)  return MathMin(first_tp,second_tp);','    if(dir==OP_BUY)  return MathMax(first_tp,second_tp);'],
 ['a sell keeps the farther TP','    if(dir==OP_SELL) return MathMax(first_tp,second_tp);','    if(dir==OP_SELL) return MathMin(first_tp,second_tp);'],
 ['a missing broker TP wins','    if(first_tp<=0.0)  return second_tp;','    if(first_tp<=0.0)  return first_tp;'],
 ['no TP from the sizes deletes the broker TP','    if(second_tp<=0.0) return first_tp;','    if(second_tp<=0.0) return second_tp;'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-adopt-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
const unmutated=runOn(MAIN);
assert.equal(unmutated.status,0,'the unmutated test passes on the scratch entrypoint: '+unmutated.stderr);
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
