// Mutation check for B50's exits (B50-alpha A3, docs/b50/B50_ALPHA_DESIGN.md section 4, the A3 row): every A3 line
// is load-bearing. Each mutant edits GOAT V1.49.mq5 in memory; test_b50_exits.cjs, run on the mutated entrypoint
// (GOAT_EA_MAIN), must then fail. Anchors sit on A3's own lines (the b50-exits block and the bypass line), and, with A1
// in the tree, on A1's re-arm, which the re-arm/reopen check exercises.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b50_exits.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
// The entry read, on both sides (the time-stop mutants below edit both).
const ENTRY='datetime b50_entry=(datetime)PositionGetInteger(POSITION_TIME);\n      int b50_bars=iBarShift(_Symbol,b50_tf,b50_entry,false);';
const MUTANTS=[
 // The design's four (section 4, A3).
 ['the FastSpeed bypass (main:7058) is removed','   if(Engine_Mode!=Engine_Single) // B50 (A3): a single keeps its signals current in optimization (FastSpeed_Flag), or its opposite exit and its re-arm would run only in visual runs\n',''],
 ['the bypass needs the opposite exit again (|| !Single_Exit_Opposite)','   if(Engine_Mode!=Engine_Single) // B50 (A3)','   if(Engine_Mode!=Engine_Single || !Single_Exit_Opposite) // B50 (A3)'],
 ['the bypass reaches the grid engine','   if(Engine_Mode!=Engine_Single) // B50 (A3)','   if(false) // B50 (A3)'],
 ['Reverse_Seq is ignored','   bool b50_rev=Reverse_Seq;','   bool b50_rev=false;'],
 ['the time stop closes on -1','         b50_unknown_buy=b50_tk_buy;\n','         b50_unknown_buy=b50_tk_buy; b50_due_buy=b50_tk_buy;\n'],
 ['the time stop counts from TimeCurrent() (no entry time)',ENTRY,'datetime b50_entry=TimeCurrent();\n      int b50_bars=iBarShift(_Symbol,b50_tf,b50_entry,false);',2],
 ['the time stop counts hours elapsed since the entry (TimeCurrent() - entry), not bars',ENTRY,'datetime b50_entry=(datetime)PositionGetInteger(POSITION_TIME);\n      int b50_bars=(int)((TimeCurrent()-b50_entry)/PeriodSeconds(b50_tf));',2],
 ['the time stop counts from the first TimeCurrent() it sees (lost on a restart)',ENTRY,'static datetime b50_seen=0; if(b50_seen==0) b50_seen=TimeCurrent();\n      datetime b50_entry=b50_seen;\n      int b50_bars=iBarShift(_Symbol,b50_tf,b50_entry,false);',2],
 // The rest of A3's lines.
 ['a range read exits (the own-signal term dropped)','   if(Seq_Buy.Traded  && b50_short && !b50_long)  Seq_Buy','   if(Seq_Buy.Traded  && b50_short)  Seq_Buy'],
 ['the sell exits on its own signal','   if(Seq_Sell.Traded && b50_long  && !b50_short) Seq_Sell','   if(Seq_Sell.Traded && b50_short  && !b50_long) Seq_Sell'],
 ['the exit does not refresh unchecked signals','      UpdateCurrentSignals(Shift_Sig);\n      checked=true;\n','      checked=true;\n'],
 ['the paused exit reads a stale RSI','      if(Sequence_Pause_Close || Sequence_Pause_News) UpdateRSI(Shift_Sig);','      ;'],
 ['the exit runs only in session','   if(!Seq_Buy.Traded && !Seq_Sell.Traded) return; // no single','   if((!Seq_Buy.Traded && !Seq_Sell.Traded) || Sequence_Pause_Close || Sequence_Pause_News) return; // no single'],
 ['GoatSignalAll drifts from the entry condition (MACD range read dropped)','            && (MACD_Mode==Trade_Disabled||MACD_Sig==OP_BUY||MACD_Sig==OP_BUYSELL)\n            && (RSI2_Mode==RSI_Disabled  ||RSI2_Sig==OP_BUY','            && (MACD_Mode==Trade_Disabled||MACD_Sig==OP_BUY)\n            && (RSI2_Mode==RSI_Disabled  ||RSI2_Sig==OP_BUY'],
 ['GoatSignalAll answers a non-direction','   return false;\n  }\n// GoatSingleSignalExits','   return true;\n  }\n// GoatSingleSignalExits'],
 ['the unknown bar count is logged on every tick','         if(b50_unknown_buy!=b50_tk_buy) Print(','         Print('],
 ['the time stop is off by one bar','         if(b50_bars>=Single_Time_Stop_Bars) b50_due_buy','         if(b50_bars>Single_Time_Stop_Bars) b50_due_buy'],
 ['the time stop reads the chart timeframe','   ENUM_TIMEFRAMES b50_tf=TF2TF(Single_Time_Stop_TF);','   ENUM_TIMEFRAMES b50_tf=PERIOD_CURRENT;'],
 ['the time stop is off','   bool b50_newbar=b50_TimeStop_Sample.CheckTF(b50_tf);','   bool b50_newbar=false;'],
 // GOAT-EA#274 P2: a due stop and an unknown count are retried every tick; the marks end with the position.
 ['a due close waits for the next bar (not retried every tick)','   if(b50_tk_buy!=0 && b50_due_buy==b50_tk_buy) Seq_Buy','   if(b50_tk_buy!=0 && b50_due_buy==b50_tk_buy && b50_newbar) Seq_Buy'],
 ['the due mark is dropped after one attempt','   if(b50_due_buy!=b50_tk_buy)     b50_due_buy=0;','   b50_due_buy=0;'],
 ['the due mark outlives its position','   if(b50_due_buy!=b50_tk_buy)     b50_due_buy=0;','   ;'],
 ['an unknown count waits for the next bar','(b50_newbar || b50_unknown_buy==b50_tk_buy)','(b50_newbar)'],
 ['the every-tick gate ignores the due marks','   if(!b50_newbar && b50_due_buy==0 && b50_due_sell==0 && b50_unknown_buy==0','   if(!b50_newbar && b50_unknown_buy==0'],
 // A1's re-arm (SignalEntryTrigger), through the re-arm/reopen check: removed, the single never reopens; run on every
 // tick instead of on a false read, it reopens with no false read (the control).
 ['A1\'s re-arm is removed (buy)','   if(!LastBuySignal) g_GoatSingleArmed[OP_BUY]=true;','   if(false) g_GoatSingleArmed[OP_BUY]=true;'],
 ['A1\'s re-arm ignores the false read (buy)','   if(!LastBuySignal) g_GoatSingleArmed[OP_BUY]=true;','   g_GoatSingleArmed[OP_BUY]=true;'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b50-exits-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:300000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
// The unmutated tree passes (through the same GOAT_EA_MAIN path).
{const r=runOn(MAIN);assert.equal(r.status,0,'the unmutated entrypoint passes: '+(r.stderr||r.stdout).slice(0,2000));}
const survived=[];
for(const [name,from,to,count=1] of MUTANTS){
 assert.equal(MAIN.split(from).length-1,count,'mutant anchor found exactly '+count+'x: '+name);
 const r=runOn(MAIN.split(from).join(to));
 if(r.status===0) survived.push(name);
 else{const m=(r.stderr||'').match(/AssertionError \[ERR_ASSERTION\]: ([^\n]*)/)||(r.stderr||'').match(/^(\w*Error[^\n]*)/m);console.log('killed: '+name+' -- '+(m?m[1].slice(0,140):'exit '+r.status));}
}
assert.deepEqual(survived,[],'every A3 mutant is killed');
console.log(JSON.stringify({killed:MUTANTS.length,total:MUTANTS.length,test:'b50_exits_mutations'}));
