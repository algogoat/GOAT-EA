// Mutation check for B49a's F1-lite (restart adoption, manage-only, the restart record): every guard is
// load-bearing. Each mutant edits GOAT V1.49.mq5 in memory; test_restart_adopt.cjs, run on the mutated entrypoint
// (GOAT_EA_MAIN), must then fail. Anchors sit on F1-lite lines, never on the build ID or marker lines.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_restart_adopt.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 ['adoption takes the other side\'s positions','     if((dir==OP_BUY && type!=POSITION_TYPE_BUY) || (dir==OP_SELL && type!=POSITION_TYPE_SELL)) continue;\n',''],
 ['adoption takes another magic\'s positions','tk==0 || PositionGetInteger(POSITION_MAGIC)!=MAGIC1 || PositionGetString','tk==0 || PositionGetString'],
 ['adoption overrides a running sequence','    if(!PersistLive() || Active) return false;\n    ulong tickets[]','    if(!PersistLive()) return false;\n    ulong tickets[]'],
 ['every record matches','    bool matched=false;','    bool matched=true;'],
 ['the start-time rule is dropped (ticket only)','     matched=(opened[0]>=(long)rec_t && PersistRead("N",rec_n) && count<=(int)rec_n);','     matched=false;'],
 ['the count bound is dropped (Claude-Mac 6428447507)','     matched=(opened[0]>=(long)rec_t && PersistRead("N",rec_n) && count<=(int)rec_n);','     matched=(opened[0]>=(long)rec_t);'],
 ['later levels do not update the level count','{if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket); else PersistLevels();}','{if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket);}'],
 ['the start record is not flushed to disk','    GlobalVariablesFlush();\n    PersistStartMsc=start_msc;','    PersistStartMsc=start_msc;'],
 ['a realized write is not flushed to disk','    GlobalVariablesFlush();\n    PersistedRealized=SequenceRealizedPL;','    PersistedRealized=SequenceRealizedPL;'],
 ['the deletion is not flushed to disk','    for(int i=0; i<ArraySize(fields); i++) GlobalVariableDel(PersistKey(fields[i]));\n    GlobalVariablesFlush();','    for(int i=0; i<ArraySize(fields); i++) GlobalVariableDel(PersistKey(fields[i]));'],
 ['no daily read-and-set (the 4-week expiry)','    bool touch=(day!=PersistTouchedDay);','    bool touch=false;'],
 ['the daily touch ignores the rate bound','    if(!force && GetTickCount()-PersistFlushedMs<GOAT_SQ_FLUSH_MS) return;\n','    if(!force && GetTickCount()-PersistFlushedMs<GOAT_SQ_FLUSH_MS && TimeGMT()-TimeGMT()%86400==PersistTouchedDay) return;\n'],
 ['the ticket rule is dropped (start time only)','     for(int i=0; i<count && !matched; i++) if(tickets[i]==(ulong)rec_tk) matched=true;\n',''],
 ['sentinel sizes are restored','    for(int i=0; i<5 && sizes; i++) if(size[i]==1234.5 || !MathIsValidNumber(size[i])) sizes=false;\n',''],
 ['the realized P/L is not restored','     SequenceRealizedPL=rec_r;\n','     SequenceRealizedPL=0.0;\n'],
 ['an adopted basket is not active','    Active=Traded=true;\n    Adopted=true;','    Traded=true;\n    Adopted=true;'],
 ['an unmatched basket keeps the stale record','     PersistEnd();                       // a record that does not match','     ;                       // a record that does not match'],
 ['Lock/TP/SL is rewritten from guessed sizes','    if(sizes) UpdateLockTPSL(Trades_Count);','    UpdateLockTPSL(Trades_Count);'],
 ['manage-only does not freeze adds','    if(!Adopted && !PersistFailed) {ManageOnlyLogged=false; return false;}','    {ManageOnlyLogged=false; return false;}'],
 ['the freeze logs every add','    if(!ManageOnlyLogged)\n','    if(true)\n'],
 ['Add_Level does not consult manage-only','    if(!Virtual && ManageOnlyFrozen(Level_Count+1)) return false;','    if(false) return false;'],
 ['the stops guard is gone','    if(Adopted && !AdoptSizes) return; // B49a (F1-lite): an adopted basket without its frozen sizes keeps its broker SL/TP\n    Level_Lock','    Level_Lock'],
 ['the record is written in the tester','    if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return false;\n    return(Mode_Operation','    return(Mode_Operation'],
 ['T is written first','    if(!(PersistWrite("TK",(double)first_ticket)','    if(!(PersistWrite("T",(double)start_msc) && PersistWrite("TK",(double)first_ticket)'],
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
