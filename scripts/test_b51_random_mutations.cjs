// Mutation check for B51's random-direction benchmark (B50-beta-1a): every rule of GoatSingleRandomSide,
// GoatSingleRandomEntry, SignalEntryTrigger's two B51 lines and the B51 OnInit refusals is load-bearing. Each mutant
// edits GOAT V1.49.mq5 in memory; test_b51_random.cjs, run on the mutated entrypoint (GOAT_EA_MAIN, read by
// scripts/b50_tick_harness.cjs and scripts/b51_random_reference.cjs), must then fail on an assertion. The first group is
// the ruling's four (a MathRand read, the seed dropped, the tick's time for the signal bar's, the side changed with the
// flag off); the rest guard the other rules the test proves.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b51_random.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const MUTANTS=[
 // (i) a MathRand read: in the side function, in place of it, and a reseed.
 ['the side function mixes in MathRand','   ulong b51_z=((ulong)seed)^((ulong)bar);','   ulong b51_z=((ulong)seed)^((ulong)bar)^((ulong)MathRand());'],
 ['the side is MathRand\'s low bit','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==0)','   if((MathRand()&1)==0)'],
 ['the entry reseeds MathSrand','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   if(!g_GoatSingleArmed[signal]) return; MathSrand(Random_Seed);'],
 // (ii) the seed dropped: at the call, and in the state.
 ['the call drops the seed','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==0)','   if(GoatSingleRandomSide(0,b51_bar)==0)'],
 ['the state drops the seed','   ulong b51_z=((ulong)seed)^((ulong)bar);','   ulong b51_z=((ulong)bar);'],
 ['the state adds the seed instead of XOR (seed 1 vs 2 differ, the golden does not)','   ulong b51_z=((ulong)seed)^((ulong)bar);','   ulong b51_z=((ulong)seed)+((ulong)bar)+1;'],
 // (iii) the tick's time (or the forming bar) in place of the signal bar's open time.
 ['the tick\'s time for the signal bar','iTime(_Symbol,PERIOD_CURRENT,(int)Shift_Sig);','TimeCurrent();'],
 ['the forming bar (shift 0) for the signal bar','iTime(_Symbol,PERIOD_CURRENT,(int)Shift_Sig);','iTime(_Symbol,PERIOD_CURRENT,0);'],
 ['the tick\'s second rounded to the minute is not the bar\'s open','iTime(_Symbol,PERIOD_CURRENT,(int)Shift_Sig);','(datetime)(TimeCurrent()-TimeCurrent()%60);'],
 // (iv) the side changes while the flag is off.
 ['the buy signal\'s random branch ignores the flag','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_BUY); else','     if(Engine_Mode==Engine_Single) GoatSingleRandomEntry(OP_BUY); else'],
 ['the sell signal\'s random branch ignores the flag','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_SELL); else','     if(Engine_Mode==Engine_Single) GoatSingleRandomEntry(OP_SELL); else'],
 ['the random branch ignores the engine (a grid with the flag off is unaffected; the flag on a grid would be refused)','     if(Engine_Mode==Engine_Single && Random_Direction) GoatSingleRandomEntry(OP_BUY); else','     if(Engine_Mode==Engine_Single || Random_Direction) GoatSingleRandomEntry(OP_BUY); else'],
 // SplitMix64 itself.
 ['the gamma\'s high half','((((ulong)0x9E3779B9)<<32)|((ulong)0x7F4A7C15))','((((ulong)0x9E3779B8)<<32)|((ulong)0x7F4A7C15))'],
 ['the gamma\'s halves joined by +32 shift error','((((ulong)0x9E3779B9)<<32)|((ulong)0x7F4A7C15))','((((ulong)0x9E3779B9)<<31)|((ulong)0x7F4A7C15))'],
 ['the first multiplier','((((ulong)0xBF58476D)<<32)|((ulong)0x1CE4E5B9))','((((ulong)0xBF58476D)<<32)|((ulong)0x1CE4E5B8))'],
 ['the second multiplier','((((ulong)0x94D049BB)<<32)|((ulong)0x133111EB))','((((ulong)0x94D049BB)<<32)|((ulong)0x133111EA))'],
 ['the first shift','   b51_z=(b51_z^(b51_z>>30))*','   b51_z=(b51_z^(b51_z>>31))*'],
 ['the second shift','   b51_z=(b51_z^(b51_z>>27))*','   b51_z=(b51_z^(b51_z>>26))*'],
 ['the final mix is dropped','   b51_z^=(b51_z>>31);\n',''],
 ['the second bit for the side','   return (int)(b51_z&1);','   return (int)((b51_z>>1)&1);'],
 ['the high bit for the side','   return (int)(b51_z&1);','   return (int)(b51_z>>63);'],
 ['the side inverted','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==0)','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==1)'],
 // The episode and the side's gates.
 ['the arm flag is not checked','   if(!g_GoatSingleArmed[signal]) return;                         // one position per signal episode, as alpha','   ;'],
 ['a buy open does not consume the episode','&& (Allow_Opposite_Seq || !Seq_Sell.Traded) && GoatSingleOpen(Seq_Buy,ask)) g_GoatSingleArmed[signal]=false;\n     }\n   else','&& (Allow_Opposite_Seq || !Seq_Sell.Traded) && GoatSingleOpen(Seq_Buy,ask)) ;\n     }\n   else'],
 ['a sell open does not consume the episode','&& (Allow_Opposite_Seq || !Seq_Buy.Traded) && GoatSingleOpen(Seq_Sell,bid)) g_GoatSingleArmed[signal]=false;\n     }\n  }','&& (Allow_Opposite_Seq || !Seq_Buy.Traded) && GoatSingleOpen(Seq_Sell,bid)) ;\n     }\n  }'],
 ['the open consumes the drawn side\'s flag, not the signal\'s','GoatSingleOpen(Seq_Buy,ask)) g_GoatSingleArmed[signal]=false;\n     }\n   else','GoatSingleOpen(Seq_Buy,ask)) g_GoatSingleArmed[OP_BUY]=false;\n     }\n   else'],
 ['Mode_Trade is not read for a buy flip','      if(DashboardEntryAllowed(OP_BUY) && !Seq_Buy_Virtual.Active && !Seq_Buy.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Long)\n','      if(DashboardEntryAllowed(OP_BUY) && !Seq_Buy_Virtual.Active && !Seq_Buy.Active\n'],
 ['Mode_Trade is not read for a sell flip','      if(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short)\n','      if(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active\n'],
 ['DashboardEntryAllowed is asked for the signal\'s side','      if(DashboardEntryAllowed(OP_SELL) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short)\n         && (Allow','      if(DashboardEntryAllowed(signal) && !Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short)\n         && (Allow'],
 ['Reverse_Seq swaps the coin','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==0)','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==(Reverse_Seq ? 1 : 0))'],
 ['the signal\'s direction steers the coin','   if(GoatSingleRandomSide(Random_Seed,b51_bar)==0)','   if((GoatSingleRandomSide(Random_Seed,b51_bar)^signal)==0)'],
 // OnInit.
 ['Random_Direction with Engine_Grid passes OnInit','   if(Random_Direction && Engine_Mode!=Engine_Single)   {','   if(false)   {'],
 ['a negative seed passes OnInit','   if(Random_Seed<0)                                    {','   if(false)                                    {'],
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
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 // Killed by an assertion of the test, never by a crash of the converted code.
 assert.match(r.stderr,/AssertionError \[ERR_ASSERTION\]/,`mutant "${label}" crashed instead of failing an assertion: `+r.stderr.slice(0,600));
 if(process.env.B51_MUTANT_DEBUG) console.log(label+': '+(r.stderr.match(/AssertionError \[ERR_ASSERTION\]:[^\n]*(\n[^\n]*){0,3}/)||[''])[0].replace(/\s+/g,' '));
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed,test:'b51_random_mutations'}));
