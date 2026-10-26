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
 // Manage-only.
 ['manage-only does not freeze adds','    if(!Adopted && !PersistFailed) {ManageOnlyLogged=false; return false;}','    {ManageOnlyLogged=false; return false;}'],
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
