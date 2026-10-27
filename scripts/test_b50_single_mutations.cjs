// Mutation check for B50's single core (A1): every rule of GoatSingleOpen and of SignalEntryTrigger's Single branches
// is load-bearing. Each mutant edits GOAT V1.49.mq5 in memory; test_b50_single.cjs, run on the mutated entrypoint
// (GOAT_EA_MAIN, read by scripts/b50_tick_harness.cjs), must then fail. The first six are the design note's
// (section 4, A1); the rest guard the other rules the test proves.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b50_single.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const MUTANTS=[
 // The design note's six.
 ['the risk lots round up','b50_lots=MathMin(MathFloor(b50_risk_lots/b50_vstep+1e-9)*b50_vstep,b50_vmax);','b50_lots=MathMin(MathCeil(b50_risk_lots/b50_vstep)*b50_vstep,b50_vmax);'],
 ['the risk lots round to the nearest step','b50_lots=MathMin(MathFloor(b50_risk_lots/b50_vstep+1e-9)*b50_vstep,b50_vmax);','b50_lots=MathMin(MathRound(b50_risk_lots/b50_vstep)*b50_vstep,b50_vmax);'],
 ['the ATR is read from shift 0 (the forming bar)','CopyBuffer(ATR_MA_handle,0,1,1,b50_atr_buf)','CopyBuffer(ATR_MA_handle,0,0,1,b50_atr_buf)'],
 ['the arm flag is not checked (buy)','{if(g_GoatSingleArmed[OP_BUY] && (Allow_Opposite_Seq || !Seq_Sell.Traded) && GoatSingleOpen(Seq_Buy,ask))','{if((Allow_Opposite_Seq || !Seq_Sell.Traded) && GoatSingleOpen(Seq_Buy,ask))'],
 ['the open does not clear the arm (buy)','GoatSingleOpen(Seq_Buy,ask)) g_GoatSingleArmed[OP_BUY]=false;}','GoatSingleOpen(Seq_Buy,ask)) ;}'],
 ['the open does not clear the arm (sell)','GoatSingleOpen(Seq_Sell,bid)) g_GoatSingleArmed[OP_SELL]=false;}','GoatSingleOpen(Seq_Sell,bid)) ;}'],
 ['the open does not clear the arm (Reverse_Seq, buy signal)','GoatSingleOpen(Seq_Sell,bid)) g_GoatSingleArmed[OP_BUY]=false;}','GoatSingleOpen(Seq_Sell,bid)) ;}'],
 ['the arm is re-armed on every tick, not on the false edge','   if(!LastBuySignal) g_GoatSingleArmed[OP_BUY]=true;','   g_GoatSingleArmed[OP_BUY]=true;'],
 ['the arm is never re-armed','   if(!LastBuySignal) g_GoatSingleArmed[OP_BUY]=true;','   if(false) g_GoatSingleArmed[OP_BUY]=true;'],
 ['the grid guard is removed (buy grid add in Single mode)','      if(Engine_Mode==Engine_Single) LastBuyTradeSignal = false; else // B50 (A0): a single never adds a grid level\n',''],
 ['GoatSingleOpen opens into a running sequence','   if(s.Virtual || s.Active || s.Traded) return false;','   if(s.Virtual) return false;'],
 ['the CID-freeze check is skipped','   if(GoatCidGuardAddFrozen(s.dir,s.Level_Count+1)) return false;','   ;'],
 ['TP_R is ignored','   if(Single_TP_R>0.0)        b50_size_tp=Single_TP_R*b50_size_sl;','   if(false)        b50_size_tp=Single_TP_R*b50_size_sl;'],
 ['TP_ATR wins over TP_R','   if(Single_TP_R>0.0)        b50_size_tp=Single_TP_R*b50_size_sl;','   if(Single_TP_R>0.0 && Single_TP_ATR<=0.0)        b50_size_tp=Single_TP_R*b50_size_sl;'],
 // Lots.
 ['below the minimum rounds up to the minimum','      b50_lots=NormalizeDouble(b50_lots,8);\n','      b50_lots=NormalizeDouble(MathMax(b50_lots,b50_vmin),8);\n'],
 ['the volume-minimum grid may round up past the risk','      if(b50_vmin>0.0 && MathAbs(GetNormalizedLots(b50_lots)-b50_lots)>b50_vstep*1e-6) b50_lots=MathFloor(b50_lots/b50_vmin+1e-9)*b50_vmin;','      ;'],
 ['a volume-minimum round-down is recorded, not sent (GOAT-EA#272 P3)','MathAbs(GetNormalizedLots(b50_lots)-b50_lots)>b50_vstep*1e-6','GetNormalizedLots(b50_lots)-b50_lots>b50_vstep*1e-6'],
 // GOAT-EA#272 P1: the money per price unit.
 ['the PriceValuePerPointPerLot path is restored (GOAT-EA#272 P1)','      double b50_value=((MathIsValidNumber(b50_tv) && MathIsValidNumber(b50_ts) && b50_tv>0.0 && b50_ts>0.0) ? b50_tv/b50_ts : 0.0);','      double b50_value=s.PriceValuePerPointPerLot();'],
 ['the value is per point, not per tick size','b50_tv>0.0 && b50_ts>0.0) ? b50_tv/b50_ts : 0.0);','b50_tv>0.0 && b50_ts>0.0) ? b50_tv/_Point : 0.0);'],
 ['no tick value is read as one','      double b50_value=((MathIsValidNumber(b50_tv) && MathIsValidNumber(b50_ts) && b50_tv>0.0 && b50_ts>0.0) ? b50_tv/b50_ts : 0.0);','      double b50_value=((MathIsValidNumber(b50_ts) && b50_ts>0.0) ? MathMax(b50_tv,1.0)/b50_ts : 0.0);'],
 // GOAT-EA#272 P3.
 ['the TP is not checked against the stops level','   if(b50_size_tp>0.0 && b50_size_tp+(double)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD)*_Point<=','   if(false && b50_size_tp+(double)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD)*_Point<='],
 ['a failed order is logged on every check','         GoatSingleRefusal(b50_side,1000+(int)LastRetCode,b50_desc,"order failed at "','         Print(b50_desc,": Single refused (order failed)"); GoatSingleRefusal(b50_side,0,b50_desc,"order failed at "'],
 ['no volume-maximum cap','b50_lots=MathMin(MathFloor(b50_risk_lots/b50_vstep+1e-9)*b50_vstep,b50_vmax);','b50_lots=MathFloor(b50_risk_lots/b50_vstep+1e-9)*b50_vstep;'],
 ['FixedLots below the minimum is sent','      if(b50_lots<=0.0 || b50_lots<b50_vmin) {GoatSingleRefusal(b50_side,4,s.Desc,"lots below the volume minimum "','      if(false) {GoatSingleRefusal(b50_side,4,s.Desc,"lots below the volume minimum "'],
 ['ScaledLots reads as FixedLots','      if(Mode_Lots==ScaledLots) b50_lots=Lots*AccountInfoDouble(ACCOUNT_EQUITY)/1000;','      if(Mode_Lots==ScaledLots) b50_lots=Lots;'],
 // Refusals.
 ['the stops-level check is dropped','   if(b50_size_sl<=b50_min_stop)\n','   if(false)\n'],
 ['a stop on the stops-level boundary is accepted','   if(b50_size_sl<=b50_min_stop)\n','   if(b50_size_sl<b50_min_stop)\n'],
 ['the spread is left out of the minimum stop','+(double)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD))*_Point;','+0.0)*_Point;'],
 ['a zero ATR is accepted','   if(!MathIsValidNumber(b50_atr) || b50_atr<=0.0 || b50_atr>=EMPTY_VALUE)','   if(!MathIsValidNumber(b50_atr) || b50_atr>=EMPTY_VALUE)'],
 ['a refusal is logged on every tick','   if(b50_logged[side]==code) return;\n',''],
 // Add_Level's order.
 ['the expiry is not checked','."); ExpertRemove(); return false;} // as Add_Level','."); ExpertRemove();} // as Add_Level'],
 ['manage-only is not consulted','   if(s.ManageOnlyFrozen(s.Level_Count+1)) return false;','   ;'],
 ['a denial keeps its sizes','      s.Size_Grid=s.Size_Lock=s.Size_TP=s.Size_SL=s.Size_TSL=1234.5;\n',''],
 ['the position does not join the ledger','{s.LedgerAddPosition((ulong)LastOrderTicket); s.AccumulateSequenceDealPL((ulong)LastDealTicket);}','{s.AccumulateSequenceDealPL((ulong)LastDealTicket);}'],
 ['the entry commission is not booked','{s.LedgerAddPosition((ulong)LastOrderTicket); s.AccumulateSequenceDealPL((ulong)LastDealTicket);}','{s.LedgerAddPosition((ulong)LastOrderTicket);}'],
 ['the restart record is not started','{if(s.PersistStartMsc==0) s.PersistStart((ulong)LastOrderTicket); else s.PersistLevels();}','{}'],
 ['UpdateLockTPSL is not called','   s.UpdateLockTPSL(s.Trades_Count);\n',''],
 ['the lock is not parked (a lock size)','s.Size_Lock=0.0; s.Size_TSL=0.0;','s.Size_Lock=s.Size_SL; s.Size_TSL=0.0;'],
 ['Sequences is not counted','   Sequences++;\n',''],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b50-single-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:300000});
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
 // Killed by an assertion of the test, never by a crash of the converted code.
 assert.match(r.stderr,/AssertionError \[ERR_ASSERTION\]/,`mutant "${label}" crashed instead of failing an assertion: `+r.stderr.slice(0,600));
 if(process.env.B50_MUTANT_DEBUG) console.log(label+': '+(r.stderr.match(/AssertionError \[ERR_ASSERTION\]:[^\n]*(\n[^\n]*){0,3}/)||[''])[0].replace(/\s+/g,' '));
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
