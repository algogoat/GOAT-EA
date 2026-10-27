// Mutation check for B49b PR-6 (F6, the pre-trade caps): every rule is load-bearing. Each mutant edits GOAT V1.49.mq5 in
// memory; test_b49b_f6.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f6.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 // Spread.
 ['the input never tightens MaxSP','(Max_Spread_Points>0 && Max_Spread_Points<MaxSP) ? (long)Max_Spread_Points : (long)MaxSP','(long)MaxSP'],
 ['the input can loosen MaxSP (Mac #281 P2)','(Max_Spread_Points>0 && Max_Spread_Points<MaxSP) ?','(Max_Spread_Points>0) ?'],
 ['a negative input is a cap','(Max_Spread_Points>0 && Max_Spread_Points<MaxSP) ?','(Max_Spread_Points!=0 && Max_Spread_Points<MaxSP) ?'],
 ['the cap refuses at it, not above it','   if(spread<=GoatSpreadCap()) return false;','   if(spread<GoatSpreadCap()) return false;'],
 ['a MaxSP refusal is logged and coded (B49a is silent)','   if(Max_Spread_Points>0)\n     {\n      LastRetCode=742;','   if(true)\n     {\n      LastRetCode=742;'],
 ['a spread refusal keeps code 0','      LastRetCode=742;\n','\n'],
 // Margin.
 ['the margin floor is checked when off','   if(!(Min_Margin_Level_PC>0.0)) return false;\n   double need','   double need'],
 ['a negative margin is allowed (Mac #281 P3)',' || !MathIsValidNumber(need) || need<0.0)',' || !MathIsValidNumber(need))'],
 ['an uncomputable margin is allowed','      GoatPreTradeRefusal(1,"order refused: its margin could not be computed (Min_Margin_Level_PC is set)");\n      return true;','      return false;'],
 ['this order\'s margin is left out','   double margin=AccountInfoDouble(ACCOUNT_MARGIN)+need;','   double margin=AccountInfoDouble(ACCOUNT_MARGIN);'],
 ['the floor refuses at it, not below it','   if(level>=Min_Margin_Level_PC) return false;','   if(level>Min_Margin_Level_PC) return false;'],
 ['a sell is priced at the ask','(op==POSITION_TYPE_BUY ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID))','SymbolInfoDouble(_Symbol,SYMBOL_ASK)'],
 // The log.
 ['the log is not throttled','   if(MQLInfoInteger(MQL_TESTER) || TimeCurrent()-g_goat_pretrade_logged[kind]<60) return;','   if(MQLInfoInteger(MQL_TESTER)) return;'],
 ['the log prints in the tester','   if(MQLInfoInteger(MQL_TESTER) || TimeCurrent()-g_goat_pretrade_logged[kind]<60) return;','   if(TimeCurrent()-g_goat_pretrade_logged[kind]<60) return;'],
 // Placement.
 ['the margin check is not called','   if(GoatMarginLevelRefused(OP,requestedVolume)) {LastRetCode=741; return 0;}','   if(false) {LastRetCode=741; return 0;}'],
 // The per-tick failure line and the label (Mac #281 P2/P3).
 ['the failure line prints for a pre-trade refusal','else {if(!GoatPreTradeRefusalCode(LastRetCode)) Print(','else {Print('],
 ['a spread refusal is not a pre-trade code','return(code==741 || code==742);','return(code==741);'],
 ['a broker failure is skipped too','return(code==741 || code==742);','return(code!=0);'],
 ['the label tests MaxSP','SYMBOL_SPREAD)>GoatSpreadCap())  ObjectSetText','SYMBOL_SPREAD)>=MaxSP)  ObjectSetText'],
 // The OnInit refusal.
 ['a single trade is allowed','Mode_Lots == RiskperSeq && Max_Seq_Trades<=1)','Mode_Lots == RiskperSeq && Max_Seq_Trades<1)'],
 ['two trades are refused','Mode_Lots == RiskperSeq && Max_Seq_Trades<=1)','Mode_Lots == RiskperSeq && Max_Seq_Trades<=2)'],
 ['fixed lots are refused too','Mode_Lots == RiskperSeq && Max_Seq_Trades<=1)','Max_Seq_Trades<=1)'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f6-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
{const r=runOn(MAIN);assert.equal(r.status,0,'the unmutated test passes on the scratch entrypoint: '+r.stderr);}
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
