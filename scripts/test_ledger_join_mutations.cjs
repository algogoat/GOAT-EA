// Mutation check for B49a's F2 (Ledger_Mode): every part of the position join, and the Legacy gate, is load-bearing.
// Each mutant edits GOAT V1.49.mq5 in memory; test_ledger_join.cjs, run on the mutated entrypoint (GOAT_EA_MAIN),
// must then fail. Anchors sit on F2 lines, never on the build ID or marker lines.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_ledger_join.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 ['Legacy takes the join path','    if(Ledger_Mode==Ledger_PositionJoin) {AccumulateJoinedDealPL(deal_ticket); return;}','    {AccumulateJoinedDealPL(deal_ticket); return;}'],
 ['a deal is booked twice','    for(int i=ArraySize(LedgerDeals)-1; i>=0; i--) if(LedgerDeals[i]==deal_ticket) return false;\n',''],
 ['the entry commission is not booked','    if(deal_entry==DEAL_ENTRY_IN) SequenceRealizedPL += HistoryDealGetDouble(deal_ticket,DEAL_COMMISSION);','    if(deal_entry==DEAL_ENTRY_IN) SequenceRealizedPL += 0.0;'],
 ['any position joins the sequence','    if(!LedgerHasPosition((ulong)HistoryDealGetInteger(deal_ticket,DEAL_POSITION_ID))) return;\n',''],
 ['a non-trading deal joins','    if(deal_type!=DEAL_TYPE_BUY && deal_type!=DEAL_TYPE_SELL) return;\n    if(!LedgerHasPosition(','    if(!LedgerHasPosition('],
 ['the level hook does not join its position','{LedgerAddPosition((ulong)LastOrderTicket); AccumulateSequenceDealPL((ulong)LastDealTicket);}','{AccumulateSequenceDealPL((ulong)LastDealTicket);}'],
 ['OnTradeTransaction does not book exits','{Seq_Buy.AccumulateSequenceDealPL(trans.deal); Seq_Sell.AccumulateSequenceDealPL(trans.deal);}','{}'],
 ['the dashboard transaction ignores joined exits','!=MAGIC1 && !GoatLedgerJoinedExit(trans.deal)) return;','!=MAGIC1) return;'],
 ['the daily P/L ignores joined exits','     for(int j=0;j<ArraySize(joinPositions);j++) if(GoatLedgerPositionMine(joinPositions[j])) PL_Closed+=joinProfits[j];','     ;'],
 ['the daily P/L counts every magic-0 exit','if(GoatLedgerPositionMine(joinPositions[j])) PL_Closed+=joinProfits[j];','PL_Closed+=joinProfits[j];'],
 ['the owner is anyone\'s entry','      mine=(HistoryDealGetInteger(deal,DEAL_MAGIC)==MAGIC1 && HistoryDealGetString(deal,DEAL_SYMBOL)==_Symbol);','      mine=true;'],
 ['owners are never cached','      if(g_GoatLedgerOwnerPosition[i]==position_id) return g_GoatLedgerOwnerMine[i];','      ;'],
 ['the owner cache is unbounded','   if(n>=GOAT_LEDGER_OWNER_CACHE)','   if(false)'],
 ['the rebuild ignores joined exits','      if(!GoatLedgerPositionMine(joinPositions[j])) continue;\n      DashboardBusClosedPLTotal+=joinProfits[j];','      continue;\n      DashboardBusClosedPLTotal+=joinProfits[j];'],
 // Not a mutant: GoatLedgerCollectExit's entry filter only saves a lookup. An entry deal the magic filter skipped
 // defines a position that is not this chart's, so GoatLedgerPositionMine excludes it either way (equivalent).
 // Claude-Mac GOAT-EA#265 round: fees, the owner cache, the re-init join.
 ['the ledger ignores fees','    SequenceRealizedPL += HistoryDealGetDouble(deal_ticket,DEAL_FEE);','    ;'],
 ['the daily P/L ignores a MAGIC1 deal\'s fee','       if(Ledger_Mode==Ledger_PositionJoin) PL_Closed+=HistoryDealGetDouble(ticket,DEAL_FEE);','       ;'],
 ['a joined exit ignores its fee','             +HistoryDealGetDouble(deal,DEAL_FEE);','             ;'],
 ['the rebuild ignores a MAGIC1 exit\'s fee','      if(Ledger_Mode==Ledger_PositionJoin) closed_pl+=HistoryDealGetDouble(ticket,DEAL_FEE);','      ;'],
 ['the transaction path ignores the fee','    if(Ledger_Mode==Ledger_PositionJoin) closed_pl+=HistoryDealGetDouble(trans.deal,DEAL_FEE);','    ;'],
 ['"not mine" is cached before the entry is seen','   if(!seen) return false;\n',''],
 ['OnInit keeps the owner cache','     GoatLedgerOwnerReset(); // B49a (F2)','     ; // B49a (F2)'],
 ['the owner reset clears nothing','   ArrayResize(g_GoatLedgerOwnerPosition,0);\n   ArrayResize(g_GoatLedgerOwnerMine,0);','   ;'],
 ['a re-init into PositionJoin joins nothing','    if(Active && Ledger_Mode==Ledger_PositionJoin) for(int i=0; i<Level_Count; i++) if(TradeLevels[i].ticket>0) LedgerAddPosition((ulong)TradeLevels[i].ticket);','    ;'],
 ['Legacy closes carry MAGIC1','if(Ledger_Mode==Ledger_PositionJoin) tr.SetExpertMagicNumber(MAGIC1);','tr.SetExpertMagicNumber(MAGIC1);'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-ledger-'));
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
 // A mutant may target every CTrade line at once (its anchor repeats by design).
 assert.ok(n>=1,`mutant "${label}": its anchor must occur in GOAT V1.49.mq5`);
 if(!label.includes('MAGIC1')) assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once (found ${n})`);
 const r=runOn(MAIN.split(from).join(to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
