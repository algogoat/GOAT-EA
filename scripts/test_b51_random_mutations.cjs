// Mutation check for B51's random-direction benchmark (B50-beta-1a): every rule of GoatSingleRandomSide,
// GoatSingleRandomEntry, SignalEntryTrigger's two B51 lines and the B51 OnInit refusals is load-bearing. Each mutant
// edits GOAT V1.49.mq5 in memory; test_b51_random.cjs, run on the mutated entrypoint (GOAT_EA_MAIN, read by
// scripts/b50_tick_harness.cjs and scripts/b51_random_reference.cjs), must then fail on an assertion. The first groups
// are the ruling's four (a MathRand read, the seed dropped, the tick's time for the signal bar's, the side changed with
// the flag off); the rest guard the other rules the test proves, the review's (GOAT-EA#286) included.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b51_random.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const MUTANTS=[
 // (i) a MathRand read: in the side function, in place of it, and a reseed.
 ['the side function mixes in MathRand','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62)^((ulong)MathRand());'],
 ['the side is MathRand\'s low bit','   int  b51_side=GoatSingleRandomSide(Random_Seed,b51_bar,signal);','   int  b51_side=(MathRand()&1);'],
 ['the entry reseeds MathSrand','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   if(!g_GoatSingleArmed[signal]) return; MathSrand(Random_Seed);'],
 // (ii) the seed dropped: at the call, and in the state.
 ['the call drops the seed','GoatSingleRandomSide(Random_Seed,b51_bar,signal);','GoatSingleRandomSide(0,b51_bar,signal);'],
 ['the state drops the seed','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)bar)^(((ulong)signal)<<62);'],
 ['the state adds the seed instead of XOR','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)+((ulong)bar)+1^(((ulong)signal)<<62);'],
 ['the state drops the signal bit','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)^((ulong)bar);'],
 ['the call passes the drawn side\'s guess for the signal','GoatSingleRandomSide(Random_Seed,b51_bar,signal);','GoatSingleRandomSide(Random_Seed,b51_bar,b51_t);'],
 // (iii) the episode-start signal bar: the tick's time, the forming bar, shift 2, M1 instead of the chart, the latest bar.
 ['the tick\'s time for the signal bar (buy)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig);','g_GoatRandomEpisodeBar[OP_BUY]=TimeCurrent();'],
 ['the tick\'s time for the signal bar (sell)','g_GoatRandomEpisodeBar[OP_SELL]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig);','g_GoatRandomEpisodeBar[OP_SELL]=TimeCurrent();'],
 ['the forming bar (shift 0)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig);','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,0);'],
 ['the bar at shift 2 (reviewer)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig);','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig+1);'],
 ['the bar on PERIOD_M1, not the chart\'s (reviewer)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,Shift_Sig);','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_M1,Shift_Sig);'],
 ['the bar is re-read at every check, not the episode\'s first','    if(Engine_Mode==Engine_Single && Random_Direction && g_GoatRandomEpisodeBar[OP_BUY]==0) g_GoatRandomEpisodeBar[OP_BUY]=','    if(Engine_Mode==Engine_Single && Random_Direction) g_GoatRandomEpisodeBar[OP_BUY]='],
 ['the episode bar is never cleared (one draw for every episode)','   if(!LastBuySignal) g_GoatRandomEpisodeBar[OP_BUY]=0;','   if(false) g_GoatRandomEpisodeBar[OP_BUY]=0;'],
 // (iv) the side changes while the flag is off.
 ['the buy signal\'s random branch ignores the flag','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_BUY); else','     if(Engine_Mode==Engine_Single) GoatSingleRandomEntry(OP_BUY); else'],
 ['the sell signal\'s random branch ignores the flag','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_SELL); else','     if(Engine_Mode==Engine_Single) GoatSingleRandomEntry(OP_SELL); else'],
 ['the random branch ignores the engine','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_BUY); else','     if(Engine_Mode==Engine_Single || Random_Direction) GoatSingleRandomEntry(OP_BUY); else'],
 // SplitMix64 itself.
 ['the gamma\'s high half','((((ulong)0x9E3779B9)<<32)|((ulong)0x7F4A7C15))','((((ulong)0x9E3779B8)<<32)|((ulong)0x7F4A7C15))'],
 ['the gamma\'s high half shifted by 31','((((ulong)0x9E3779B9)<<32)|((ulong)0x7F4A7C15))','((((ulong)0x9E3779B9)<<31)|((ulong)0x7F4A7C15))'],
 ['the first multiplier','((((ulong)0xBF58476D)<<32)|((ulong)0x1CE4E5B9))','((((ulong)0xBF58476D)<<32)|((ulong)0x1CE4E5B8))'],
 ['the second multiplier','((((ulong)0x94D049BB)<<32)|((ulong)0x133111EB))','((((ulong)0x94D049BB)<<32)|((ulong)0x133111EA))'],
 ['the first shift','   b51_z=(b51_z^(b51_z>>30))*','   b51_z=(b51_z^(b51_z>>31))*'],
 ['the second shift','   b51_z=(b51_z^(b51_z>>27))*','   b51_z=(b51_z^(b51_z>>26))*'],
 ['the final mix is dropped','   b51_z^=(b51_z>>31);\n',''],
 ['the second bit for the side','   return (int)(b51_z&1);','   return (int)((b51_z>>1)&1);'],
 ['the side inverted','   if(b51_side==OP_BUY) b51_opened=GoatSingleOpen(Seq_Buy,ask);\n   else                 b51_opened=GoatSingleOpen(Seq_Sell,bid);','   if(b51_side!=OP_BUY) b51_opened=GoatSingleOpen(Seq_Buy,ask);\n   else                 b51_opened=GoatSingleOpen(Seq_Sell,bid);'],
 // Alpha's moment (its gates for its trade side, every single counted for its episode's signal).
 ['the arm flag is not checked','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   ;'],
 ['an open does not consume the episode','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal; g_GoatSingleArmed[signal]=false;}','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal;}'],
 ['an open does not record its episode\'s signal','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal; g_GoatSingleArmed[signal]=false;}','   if(b51_opened) {g_GoatSingleArmed[signal]=false;}'],
 ['alpha\'s gate reads the side, not the episode (reviewer P1-1)','   bool b51_mine=((Seq_Buy.Active && g_GoatRandomSignal[OP_BUY]==signal) || (Seq_Sell.Active && g_GoatRandomSignal[OP_SELL]==signal));','   bool b51_mine=(b51_t==OP_BUY ? Seq_Buy.Active : Seq_Sell.Active);'],
 ['alpha\'s running-single gate is dropped','|| b51_mine\n','\n'],
 ['alpha\'s Allow_Opposite_Seq gate is dropped (reviewer)','\n      || !(Allow_Opposite_Seq || !b51_other)) return;',') return;'],
 ['alpha\'s Allow_Opposite_Seq gate reads the side','   bool b51_other=((Seq_Buy.Traded && g_GoatRandomSignal[OP_BUY]!=signal) || (Seq_Sell.Traded && g_GoatRandomSignal[OP_SELL]!=signal));','   bool b51_other=(b51_t==OP_BUY ? Seq_Sell.Traded : Seq_Buy.Traded);'],
 ['alpha\'s DashboardEntryAllowed is not asked','   if(!DashboardEntryAllowed(b51_t) ||','   if('],
 ['alpha\'s virtual gate is dropped (reviewer)','(b51_t==OP_BUY ? Seq_Buy_Virtual.Active : Seq_Sell_Virtual.Active) || b51_mine','b51_mine'],
 ['Reverse_Seq is ignored for alpha\'s trade side','   int  b51_t=(Reverse_Seq ? 1-signal : signal);','   int  b51_t=signal;'],
 // The drawn side's gates: consumed, counted, logged; no redraw, no waiting.
 ['a gated draw waits (the episode stays armed)','      g_GoatSingleArmed[signal]=false; g_GoatRandomGated++;       // consumed: no redraw, no waiting','      g_GoatRandomGated++;'],
 ['a gated draw is not counted','      g_GoatSingleArmed[signal]=false; g_GoatRandomGated++;       // consumed: no redraw, no waiting','      g_GoatSingleArmed[signal]=false;'],
 ['a gated draw is not logged','      Print((signal==OP_BUY ? Seq_Buy.Desc : Seq_Sell.Desc),": B51 random: drawn side gated (signal "','      if(false) Print((signal==OP_BUY ? Seq_Buy.Desc : Seq_Sell.Desc),": B51 random: drawn side gated (signal "'],
 ['a gated draw opens the other side instead','   if(!b51_free)\n     {','   if(!b51_free) b51_side=1-b51_side;\n   if(false)\n     {'],
 ['the drawn buy ignores a running buy','(DashboardEntryAllowed(OP_BUY) && !Seq_Buy_Virtual.Active && !Seq_Buy.Active)','(DashboardEntryAllowed(OP_BUY) && !Seq_Buy_Virtual.Active)'],
 ['the drawn sell ignores a running sell','(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active)','(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active)'],
 ['the drawn sell ignores DashboardEntryAllowed','(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active)','(!Seq_Sell_Virtual.Active && !Seq_Sell.Active)'],
 ['the drawn sell ignores a virtual sell (reviewer)','(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active)','(DashboardEntryAllowed(OP_SELL) && !Seq_Sell.Active)'],
 // The opposite-signal exit reads the opening episode's signal (reviewer P1-2).
 ['the random exit reads the side (alpha\'s rule)','   if(Random_Direction)\n     {\n      if(Seq_Buy.Traded','   if(false)\n     {\n      if(Seq_Buy.Traded'],
 ['the random sell exit reads the side','      if(Seq_Sell.Traded && GoatSignalAll(1-g_GoatRandomSignal[OP_SELL]) && !GoatSignalAll(g_GoatRandomSignal[OP_SELL]))','      if(Seq_Sell.Traded && GoatSignalAll(OP_BUY) && !GoatSignalAll(OP_SELL))'],
 // OnInit.
 ['Random_Direction with Engine_Grid passes OnInit','   if(Random_Direction && Engine_Mode!=Engine_Single)   {','   if(false)   {'],
 ['a negative seed passes OnInit','   if(Random_Seed<0)                                    {','   if(false)                                    {'],
 ['Random_Direction with one direction passes OnInit','   if(Random_Direction && Mode_Trade!=Long_and_Short)   {','   if(false)   {'],
 ['Random_Direction passes OnInit on a live chart','   if(Random_Direction && !MQLInfoInteger(MQL_TESTER))  {','   if(false)  {'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b51-random-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:300000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
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
console.log(JSON.stringify({mutants:MUTANTS.length,killed,test:'b51_random_mutations'}));
