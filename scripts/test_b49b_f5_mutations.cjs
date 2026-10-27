// Mutation check for B49b PR-5 (F5, Gate_Recheck): every gate, guard and placement is load-bearing. Each mutant edits
// GOAT V1.49.mq5 in memory; test_b49b_f5.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f5.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const gate=(text)=>['the '+text.split('return "')[1].replace(/";.*/,'')+' gate is gone','   '+text+'\n',''];
const MUTANTS=[
 gate('if(!Active)                                    return "session";'),
 gate('if(!Allow_New_Sequence)                        return "allow_new_sequence";'),
 gate('if(!Sequence_New_Friday)                       return "friday";'),
 gate('if(!Sequence_New_Dec)                          return "december";'),
 gate('if(DashboardPortfolioPaused)                   return "dashboard_paused";'),
 gate('if(!DashboardTradeAllowed(pos_dir))            return "dashboard_direction";'),
 gate('if(!Sequence_New_News)                         return "news";'),
 ['the buy bias gate is gone','   if(pos_dir==OP_BUY  && !Sequence_New_Bias_B)   return "bias";\n',''],
 ['the sell bias gate is gone','   if(pos_dir==OP_SELL && !Sequence_New_Bias_S)   return "bias";\n',''],
 ['a sell reads the buy bias (EX-11 unfixed)','   if(pos_dir==OP_SELL && !Sequence_New_Bias_S)   return "bias";','   if(pos_dir==OP_SELL && !Sequence_New_Bias_B)   return "bias";'],
 ['the buy direction gate is gone','   if(pos_dir==OP_BUY  && !(Mode_Trade==Long_and_Short || Mode_Trade==Long))  return "mode_trade";\n',''],
 ['the sell direction gate is gone','   if(pos_dir==OP_SELL && !(Mode_Trade==Long_and_Short || Mode_Trade==Short)) return "mode_trade";\n',''],
 gate('if(!Allow_Opposite_Seq && opposite_traded)     return "opposite_sequence";'),
 ['the opposite gate ignores Allow_Opposite_Seq','   if(!Allow_Opposite_Seq && opposite_traded)     return "opposite_sequence";','   if(opposite_traded)     return "opposite_sequence";'],
 gate('if(!DashboardEntryAllowed(pos_dir))            return "dashboard_entry";'),
 // The refusal.
 ['Legacy refuses too','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual || Traded) return false;','    if(Virtual || Traded) return false;'],
 ['a traded sequence is refused (adds gated)','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual || Traded) return false;','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual) return false;'],
 ['a virtual candidate is refused','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual || Traded) return false;','    if(Gate_Recheck!=Gate_AtFirstOrder || Traded) return false;'],
 ['the opposite side is this side','(dir==OP_BUY) ? Seq_Sell.Traded : Seq_Buy.Traded','(dir==OP_BUY) ? Seq_Buy.Traded : Seq_Sell.Traded'],
 ['the side flag is not set','    g_goat_first_order_refused[side]=true;\n',''],
 ['the side flag is always the buy side','    int side=(dir==OP_SELL) ? 1 : 0;\n    string reason=GoatFirstOrderGateReason','    int side=0;\n    string reason=GoatFirstOrderGateReason'],
 ['a delayed-live candidate is not ended','    if(Active) End_Sequence("Gate at first order: "+reason);','    if(Active) ;'],
 ['an immediate start keeps its sizing','    else\n    {\n     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;\n     StartLots=PeakLots=PeakCumLots=ScaleFactor=0.0;\n     ArrayResize(LotsRaw,0,Max_Seq_Trades); ArrayResize(LotsNorm,0,Max_Seq_Trades); ArrayResize(LotsCum,0,Max_Seq_Trades); ArrayResize(Distances,0,Max_Seq_Trades);\n    }\n    return true;\n   }\n// B49b:end first-order-gates','    return true;\n   }\n// B49b:end first-order-gates'],
 ['the refusal is not logged','    Print("GOAT gates: first order refused side=",','    if(false) Print("GOAT gates: first order refused side=",'],
 // The promotion block and the placement.
 ['a stale refusal is not cleared','      g_goat_first_order_refused[(dir==OP_SELL) ? 1 : 0]=false; // B49b (F5)\n',''],
 ['a refused promotion leaves its candidate waiting','      else if(g_goat_first_order_refused[(dir==OP_SELL) ? 1 : 0]) End_Sequence("Gate at first order");','      ;'],
 ['the first order is not gated','      if(FirstOrderGatesRefused()) return false; // B49b (F5): Gate_Recheck, the first real order passes every start gate\n',''],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f5-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
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
