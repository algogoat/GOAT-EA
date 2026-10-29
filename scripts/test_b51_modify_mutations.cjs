// Mutation check for B51's single break-even and trailing (B50-beta-1b): every rule of GoatSingleModify,
// GoatSingleModifySequence, GoatSingleModifySend, their call site and the B51 OnInit refusal is load-bearing. Each mutant
// edits GOAT V1.49.mq5 in memory; test_b51_modify.cjs, run on the mutated entrypoint (GOAT_EA_MAIN, read by
// scripts/b50_tick_harness.cjs), must then fail on an assertion. The first group is the ruling's four (the back-off
// removed, a log field dropped, an SL that can move against the trade, break-even or trailing firing with its input at
// 0); the rest guard the other rules the test proves. Equivalent mutants are not listed: dropping the early return
// when both inputs are 0, the grid-engine check in GoatSingleModify (OnInit refuses the three inputs with the grid
// engine, review P3-10) and the one-point check (every remaining move is a waived move to the entry, whose gain is
// positive, or one of at least the minimum step).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b51_modify.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const SEND='GoatSingleModifySend(SEQUENCE &s,const ulong tk,const double sl,const double cur_sl,const double cur_tp)';
const MUTANTS=[
 // The back-off removed or weakened.
 ['the back-off is removed (no wait)','   if(b51_k>=0 && b51_now<b51_next[b51_k]) return false;   // backing off: no attempt, no line','   ;'],
 ['the wait is never set','      b51_next[b51_k]=b51_now+b51_wait;\n','\n'],
 ['the back-off starts after 6 failures','#define GOAT_SINGLE_MODIFY_FAIL_LIMIT  5','#define GOAT_SINGLE_MODIFY_FAIL_LIMIT  6'],
 ['the first wait is 2 s','#define GOAT_SINGLE_BACKOFF_1_S        1','#define GOAT_SINGLE_BACKOFF_1_S        2'],
 ['the third wait is 60 s','#define GOAT_SINGLE_BACKOFF_3_S       30','#define GOAT_SINGLE_BACKOFF_3_S       60'],
 ['the steady wait is 30 s','#define GOAT_SINGLE_BACKOFF_STEADY_S  60','#define GOAT_SINGLE_BACKOFF_STEADY_S  30'],
 ['a stuck ticket goes silent (no line after the steady step starts)','   Print(b51_line);\n   return false;','   if(b51_count<GOAT_SINGLE_MODIFY_FAIL_LIMIT+4) Print(b51_line);\n   return false;'],
 ['a line per tick inside the wait','   if(b51_k>=0 && b51_now<b51_next[b51_k]) return false;   // backing off: no attempt, no line','   if(b51_k>=0 && b51_now<b51_next[b51_k]) {Print(s.Desc,": Single SL modify failed: backing off"); return false;}'],
 // A dropped log field (each one).
 ['the ticket is dropped from the line','": Single SL modify failed: ticket="+IntegerToString((long)tk)','": Single SL modify failed: "'],
 ['the bid is dropped','+" bid="+DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_BID),_Digits)','+""'],
 ['the ask is dropped','+" ask="+DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_ASK),_Digits)','+""'],
 ['the stops level is dropped','                   +" stops_level="+IntegerToString(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL))\n','\n'],
 ['the freeze level is dropped','                   +" freeze_level="+IntegerToString(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL))\n','\n'],
 ['the freeze level logs the stops level','" freeze_level="+IntegerToString(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL))','" freeze_level="+IntegerToString(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL))'],
 ['the current SL is dropped','+" sl="+DoubleToString(cur_sl,_Digits)','+""'],
 ['the TP is dropped','+" tp="+DoubleToString(cur_tp,_Digits)','+""'],
 ['the requested SL is dropped','+" requested_sl="+DoubleToString(sl,_Digits)','+""'],
 ['the return code is dropped','+" retcode="+IntegerToString((int)b51_trade.ResultRetcode())','+""'],
 ['the consecutive count is dropped','+" consecutive="+IntegerToString(b51_count);','+"";'],
 // An SL that can move against the trade, or outside the legal band.
 ['break-even ignores the current SL (always a break-even move)','      bool   b51_be_move=(b51_be && MathAbs(b51_target-b51_open)<b51_eps && (b51_sl==0.0 || (b51_buy ? b51_sl<b51_open-b51_eps : b51_sl>b51_open+b51_eps)));','      bool   b51_be_move=b51_be;'],
 ['the clamp is removed','      if(b51_buy ? b51_target>b51_legal : b51_target<b51_legal) b51_target=b51_legal; // the nearest legal level\n','\n'],
 ['the freeze level is not in the clamp','   int    b51_lvl=(int)MathMax((long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),(long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL));','   int    b51_lvl=(int)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);'],
 ['the sell trails on the wrong side','b51_px+Single_Trail_ATR*b51_atr,_Digits);','b51_px-Single_Trail_ATR*b51_atr,_Digits);'],
 // Firing with an input at 0.
 ['break-even fires with Single_BE_ATR=0','      bool   b51_be=(Single_BE_ATR>0.0 && b51_favour','      bool   b51_be=(Single_BE_ATR>=0.0 && b51_favour'],
 ['trailing fires with Single_Trail_ATR=0','      bool   b51_trail=(Single_Trail_ATR>0.0 && b51_favour','      bool   b51_trail=(Single_Trail_ATR>=0.0 && b51_favour'],
 // The thresholds and targets.
 ['break-even fires a point early','b51_be=(Single_BE_ATR>0.0 && b51_favour>=Single_BE_ATR*b51_atr-b51_eps);','b51_be=(Single_BE_ATR>0.0 && b51_favour>=Single_BE_ATR*b51_atr-_Point*1.001);'],
 ['break-even fires a point late','b51_be=(Single_BE_ATR>0.0 && b51_favour>=Single_BE_ATR*b51_atr-b51_eps);','b51_be=(Single_BE_ATR>0.0 && b51_favour>Single_BE_ATR*b51_atr+b51_eps);'],
 ['break-even adds the spread','      double b51_target=b51_open;','      double b51_target=(b51_buy ? b51_open+(ask-bid) : b51_open-(ask-bid));'],
 ['the trailing starts at the break-even threshold','b51_trail=(Single_Trail_ATR>0.0 && b51_favour>=Single_Trail_Start_ATR*b51_atr-b51_eps);','b51_trail=(Single_Trail_ATR>0.0 && b51_favour>=Single_BE_ATR*b51_atr-b51_eps);'],
 ['the trailing distance is the start','b51_px-Single_Trail_ATR*b51_atr : b51_px+Single_Trail_ATR*b51_atr','b51_px-Single_Trail_Start_ATR*b51_atr : b51_px+Single_Trail_Start_ATR*b51_atr'],
 ['the ATR is the stop size (not divided by Single_SL_ATR)','   double b51_atr=s.Size_SL/Single_SL_ATR;','   double b51_atr=s.Size_SL;'],
 ['the ATR is the forming bar\'s','   double b51_atr=s.Size_SL/Single_SL_ATR;','   double b51_atr_buf[]; double b51_atr=(CopyBuffer(ATR_MA_handle,0,0,1,b51_atr_buf)==1 ? b51_atr_buf[0] : 0.0);'],
 ['the TP is not kept','   if(b51_trade.PositionModify(tk,sl,cur_tp))','   if(b51_trade.PositionModify(tk,sl,0.0))'],
 ['no minimum step for the trailing','      if(!b51_be_move && b51_gain<b51_min_step-b51_eps) continue;\n','\n'],
 // The count, the slots and the tickets.
 ['a success does not clear the count','         b51_tk[b51_k]=0; b51_fails[b51_k]=0; b51_next[b51_k]=0;\n','\n'],
 ['the tickets share one back-off','   for(int j=0;j<GOAT_SINGLE_MODIFY_SLOTS;j++) if(b51_tk[j]==tk) b51_k=j;','   for(int j=0;j<GOAT_SINGLE_MODIFY_SLOTS;j++) if(b51_tk[j]!=0) b51_k=j;'],
 ['a failure keeps no count','   int b51_count=(b51_k>=0 ? ++b51_fails[b51_k] : 1);','   int b51_count=1;'],
 ['the recovery is not logged','         Print(s.Desc,": Single SL modify recovered: ticket="','         if(false) Print(s.Desc,": Single SL modify recovered: ticket="'],
 // The sequence and its state.
 ['an adopted single without its sizes is modified','   if(s.Adopted && !s.AdoptSizes) return;                    // as TrailingStoploss: no frozen sizes, the broker SL/TP stay','   ;'],
 ['Level_SL does not follow','{s.TradeLevels[i].sl=b51_target; s.Level_SL=b51_target;}','{s.TradeLevels[i].sl=b51_target;}'],
 ['only the buy sequence is managed','   GoatSingleModifySequence(Seq_Sell);\n','\n'],
 ['the call site is dropped','    GoatSingleModify(); // B51 (beta-1b)','    ; // B51 (beta-1b)'],
 // The review's (GOAT-EA#287) mutants, and its P3-9/P3-10 rules.
 ['the sell clamp reads the bid (reviewer)','NormalizeDouble(ask+b51_lvl*_Point,_Digits)','NormalizeDouble(bid+b51_lvl*_Point,_Digits)'],
 ['the sell favour reads the bid (reviewer)','   double b51_px=(b51_buy ? bid : ask);','   double b51_px=bid;'],
 ['a stale slot is never reused (reviewer)','if(b51_tk[j]==0 || !PositionSelectByTicket(b51_tk[j]))','if(b51_tk[j]==0)'],
 ['the wait ends a second late (reviewer)','if(b51_k>=0 && b51_now<b51_next[b51_k]) return false;','if(b51_k>=0 && b51_now<=b51_next[b51_k]) return false;'],
 ['the move to the entry waits for the minimum step (reviewer)','      if(!b51_be_move && b51_gain<b51_min_step-b51_eps) continue;','      if(b51_gain<b51_min_step-b51_eps) continue;'],
 ['no tolerance on the break-even threshold (reviewer)','b51_favour>=Single_BE_ATR*b51_atr-b51_eps);','b51_favour>=Single_BE_ATR*b51_atr);'],
 ['a clamped break-even moves by any point (P3-9)','      bool   b51_be_move=(b51_be && MathAbs(b51_target-b51_open)<b51_eps && (','      bool   b51_be_move=(b51_be && ('],
 ['attempts are not counted (P3-10)','   TSLmodifieds++;                                          // the run','   ;                                          // the run'],
 ['failures are not counted (P3-10)','   TSLmodifyErrors++;\n','\n'],
 ['a trailing start without a distance passes OnInit (P3-10)','   if(Single_Trail_Start_ATR>0.0 && !(Single_Trail_ATR>0.0)) {','   if(false) {'],
 ['the grid engine with break-even passes OnInit (P3-10)','   if(Engine_Mode!=Engine_Single && (Single_BE_ATR>0.0 ||','   if(false && (Single_BE_ATR>0.0 ||'],
 ['the grid engine with trailing passes OnInit (P3-10)','|| Single_Trail_Start_ATR>0.0 || Single_Trail_ATR>0.0)) {Alert("Initialization Failed: Single_BE_ATR, Single_Trail_Start_ATR and Single_Trail_ATR need','|| Single_Trail_Start_ATR>0.0)) {Alert("Initialization Failed: Single_BE_ATR, Single_Trail_Start_ATR and Single_Trail_ATR need'],
 ['OnInit accepts a negative distance','   if(Single_BE_ATR<0.0 || Single_Trail_Start_ATR<0.0 || Single_Trail_ATR<0.0) {','   if(false) {'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b51-modify-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:300000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
assert.ok(MAIN.includes(SEND),'GoatSingleModifySend is in the entrypoint');
const unmutated=runOn(MAIN);
assert.equal(unmutated.status,0,'the unmutated test passes on the scratch entrypoint: '+unmutated.stderr);
let killed=0;const survivors=[];
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 if(r.status===0){survivors.push(label);continue;}   // every survivor is reported at the end
 // Killed by an assertion of the test, never by a crash of the converted code.
 assert.match(r.stderr,/AssertionError \[ERR_ASSERTION\]/,`mutant "${label}" crashed instead of failing an assertion: `+r.stderr.slice(0,600));
 if(process.env.B51_MUTANT_DEBUG) console.log(label+': '+(r.stderr.match(/AssertionError \[ERR_ASSERTION\]:[^\n]*(\n[^\n]*){0,3}/)||[''])[0].replace(/\s+/g,' '));
 killed++;
}
assert.deepEqual(survivors,[],'mutants survived');
console.log(JSON.stringify({mutants:MUTANTS.length,killed,test:'b51_modify_mutations'}));
