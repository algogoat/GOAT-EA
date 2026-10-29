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
const ENTRY_DECISION='   if(!GoatSingleBothFree()) return;                              // the decision, before the draw: both sides free (Single_Flat_Only)\n';
const MUTANTS=[
 // (i) a MathRand read: in the side function, in place of it, and a reseed.
 ['the side function mixes in MathRand','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62)^((ulong)MathRand());'],
 ['the side is MathRand\'s low bit','   int  b51_side=GoatSingleRandomSide(Random_Seed,b51_bar,signal);','   int  b51_side=(MathRand()&1);'],
 ['the entry reseeds MathSrand','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   if(!g_GoatSingleArmed[signal]) return; MathSrand(Random_Seed);'],
 // (ii) the seed dropped: at the call, and in the state.
 ['the call drops the seed','GoatSingleRandomSide(Random_Seed,b51_bar,signal);','GoatSingleRandomSide(0,b51_bar,signal);'],
 ['the state drops the seed','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)bar)^(((ulong)signal)<<62);'],
 ['the state adds the seed instead of XOR','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)+((ulong)bar)+1^(((ulong)signal)<<62);'],
 ['the state drops the signal bit (reviewer)','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)^((ulong)bar);'],
 ['the signal bit at 63, not 62 (reviewer)','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<62);','   ulong b51_z=((ulong)seed)^((ulong)bar)^(((ulong)signal)<<63);'],
 ['the call passes the other signal','GoatSingleRandomSide(Random_Seed,b51_bar,signal);','GoatSingleRandomSide(Random_Seed,b51_bar,1-signal);'],
 // (iii) the episode-start signal bar: the tick's time, the forming bar, shift 2, M1 instead of the chart, re-read, never cleared.
 ['the tick\'s time for the signal bar (buy)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig));','g_GoatRandomEpisodeBar[OP_BUY]=TimeCurrent();'],
 ['the tick\'s time for the signal bar (sell)','g_GoatRandomEpisodeBar[OP_SELL]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig));','g_GoatRandomEpisodeBar[OP_SELL]=TimeCurrent();'],
 ['the forming bar (shift 0)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig));','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,0);'],
 ['the bar at shift 2 (reviewer)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig));','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig)+1);'],
 ['the bar on PERIOD_M1, not the chart\'s (reviewer)','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_CURRENT,(int)(Shift_Sig));','g_GoatRandomEpisodeBar[OP_BUY]=iTime(_Symbol,PERIOD_M1,(int)(Shift_Sig));'],
 ['the bar is re-read at every check (reviewer: a redraw per bar)','    if(Engine_Mode==Engine_Single && Random_Direction && g_GoatRandomEpisodeBar[OP_BUY]==0) g_GoatRandomEpisodeBar[OP_BUY]=','    if(Engine_Mode==Engine_Single && Random_Direction) g_GoatRandomEpisodeBar[OP_BUY]='],
 ['the episode bar is never cleared (reviewer)','   if(!LastBuySignal) g_GoatRandomEpisodeBar[OP_BUY]=0;','   if(false) g_GoatRandomEpisodeBar[OP_BUY]=0;'],
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
 // The episode.
 ['the arm flag is not checked','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   ;'],
 ['an open does not consume the episode','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal; g_GoatSingleArmed[signal]=false;}','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal;}'],
 ['an open does not record its episode\'s signal (reviewer)','   if(b51_opened) {g_GoatRandomSignal[b51_side]=signal; g_GoatSingleArmed[signal]=false;}','   if(b51_opened) {g_GoatSingleArmed[signal]=false;}'],
 // The re-review: the draw must not decide eligibility; both sides; flat-only off is alpha.
 ['the draw decides eligibility (only the drawn side must be free)',ENTRY_DECISION+'   datetime b51_bar=g_GoatRandomEpisodeBar[signal];',
  '   datetime b51_bar=g_GoatRandomEpisodeBar[signal];'],
 ['the benchmark ignores flat-only (no decision at all)',ENTRY_DECISION,''],
 ['the drawn side is checked after the draw (a draw-dependent gate)','   int  b51_side=GoatSingleRandomSide(Random_Seed,b51_bar,signal); // the draw only picks the side\n',
  '   int  b51_side=GoatSingleRandomSide(Random_Seed,b51_bar,signal); // the draw only picks the side\n   if(b51_side==OP_BUY ? Seq_Buy.Active : Seq_Sell.Active) {g_GoatSingleArmed[signal]=false; return;}\n'],
 ['both-free reads the buy side only','   return(!Seq_Buy.Active && !Seq_Sell.Active && !Seq_Buy_Virtual.Active && !Seq_Sell_Virtual.Active\n          && DashboardEntryAllowed(OP_BUY) && DashboardEntryAllowed(OP_SELL));','   return(!Seq_Buy.Active && !Seq_Buy_Virtual.Active && DashboardEntryAllowed(OP_BUY));'],
 ['both-free ignores a running sell','   return(!Seq_Buy.Active && !Seq_Sell.Active &&','   return(!Seq_Buy.Active &&'],
 ['both-free ignores a running buy','   return(!Seq_Buy.Active && !Seq_Sell.Active &&','   return(!Seq_Sell.Active &&'],
 ['both-free ignores a virtual sell','&& !Seq_Buy_Virtual.Active && !Seq_Sell_Virtual.Active\n','&& !Seq_Buy_Virtual.Active\n'],
 ['both-free ignores a virtual buy','&& !Seq_Buy_Virtual.Active && !Seq_Sell_Virtual.Active\n','&& !Seq_Sell_Virtual.Active\n'],
 ['both-free ignores the sell permission','          && DashboardEntryAllowed(OP_BUY) && DashboardEntryAllowed(OP_SELL));','          && DashboardEntryAllowed(OP_BUY));'],
 ['both-free ignores the buy permission','          && DashboardEntryAllowed(OP_BUY) && DashboardEntryAllowed(OP_SELL));','          && DashboardEntryAllowed(OP_SELL));'],
 ['flat-only leaks into flags off (buy signal)','      if(Engine_Mode==Engine_Single && Single_Flat_Only && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_BUY]',
  '      if(Engine_Mode==Engine_Single && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_BUY]'],
 ['flat-only leaks into flags off (sell signal)','      if(Engine_Mode==Engine_Single && Single_Flat_Only && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_SELL]',
  '      if(Engine_Mode==Engine_Single && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_SELL]'],
 ['the strategy ignores flat-only (buy signal)','      if(Engine_Mode==Engine_Single && Single_Flat_Only && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_BUY]',
  '      if(false) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_BUY]'],
 ['the strategy ignores flat-only (sell signal)','      if(Engine_Mode==Engine_Single && Single_Flat_Only && !GoatSingleBothFree()) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_SELL]',
  '      if(false) {} else // B51 (beta-1a): Single_Flat_Only: a single opens only while both sides are free\n      if(Engine_Mode==Engine_Single) {if(g_GoatSingleArmed[OP_SELL]'],
 // The opposite-signal exit reads the opening episode's signal (reviewer P1-2).
 ['the random exit reads the side (alpha\'s rule) (reviewer)','   if(Random_Direction)\n     {\n      if(Seq_Buy.Traded','   if(false)\n     {\n      if(Seq_Buy.Traded'],
 ['the random sell exit reads the side','      if(Seq_Sell.Traded && GoatSignalAll(1-g_GoatRandomSignal[OP_SELL]) && !GoatSignalAll(g_GoatRandomSignal[OP_SELL]))','      if(Seq_Sell.Traded && GoatSignalAll(OP_BUY) && !GoatSignalAll(OP_SELL))'],
 // OnInit.
 ['Random_Direction with Engine_Grid passes OnInit','   if(Random_Direction && Engine_Mode!=Engine_Single)   {','   if(false)   {'],
 ['a negative seed passes OnInit','   if(Random_Seed<0)                                    {','   if(false)                                    {'],
 ['Random_Direction with one direction passes OnInit','   if(Random_Direction && Mode_Trade!=Long_and_Short)   {','   if(false)   {'],
 ['Random_Direction without Single_Flat_Only passes OnInit','   if(Random_Direction && !Single_Flat_Only)            {','   if(false)            {'],
 ['Single_Flat_Only with the grid passes OnInit','   if(Single_Flat_Only && Engine_Mode!=Engine_Single)   {','   if(false)   {'],
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
