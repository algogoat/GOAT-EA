// Mutation check for B52, the final build's review fixes: every one is load-bearing. Each mutant edits GOAT V1.49.mq5 in
// memory; the test that proves the fix (test_b52_review.cjs, or test_b49b_f5.cjs / test_b50_clock.cjs where the fix's
// test lives), run on the mutated entrypoint (GOAT_EA_MAIN), must then fail. Run in parallel, as the other mutation suites.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),MAIN=path.join(ROOT,'GOAT V1.49.mq5');
const SOURCE=fs.readFileSync(MAIN,'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const REVIEW='test_b52_review.cjs',F5='test_b49b_f5.cjs',CLOCK='test_b50_clock.cjs';
const MUTANTS=[
 // P2: the deferred adoption.
 [REVIEW,'the file is rewritten while an adoption waits','   if(GoatAdoptPending()) return; // B52','   // B52'],
 [REVIEW,'a running sequence does not hold its side','((!Seq_Buy.Active && FindNumberOfPositions(OP_BUY,MAGIC1)>0)','((FindNumberOfPositions(OP_BUY,MAGIC1)>0)'],
 // The second read: the wait is OnInit's deferral, not the account's reading (P2-1, P2-2), and the single engine's only.
 [REVIEW,'the wait reads the account, not the deferral (B52 as first sent)','   if(Engine_Mode!=Engine_Single || !g_GoatSingleAccountPending) return false;','   if(!GoatSingleAdoptHeld()) return false;'],
 [REVIEW,'the wait outlives the deferral (any orphan holds every write)','   if(Engine_Mode!=Engine_Single || !g_GoatSingleAccountPending) return false;','   if(Engine_Mode!=Engine_Single) return false;'],
 [REVIEW,'the grid engine waits too','   if(Engine_Mode!=Engine_Single || !g_GoatSingleAccountPending) return false;','   if(!g_GoatSingleAccountPending) return false;'],
 [REVIEW,'OnInit\'s adoptions keep an earlier mark','     g_GoatStateRestored=false; // B52 (second read P3)','     // B52 (second read P3)'],
 [REVIEW,'the sell side never waits','|| (!Seq_Sell.Active && FindNumberOfPositions(OP_SELL,MAGIC1)>0));','|| false);'],
 [REVIEW,'a late restore ignores OnInit\'s pass','   if(!g_GoatStateRestored) return;\n   string keys[],values[];','   string keys[],values[];'],
 [REVIEW,'a late restore writes both sides','   if(dir==OP_BUY) Seq_Buy.StateRestore(keys,values); else Seq_Sell.StateRestore(keys,values);','   Seq_Buy.StateRestore(keys,values); Seq_Sell.StateRestore(keys,values);'],
 [REVIEW,'OnInit\'s pass is never marked','   g_GoatStateRestored=true; // B52','   // B52'],
 [REVIEW,'a late adoption keeps no state','    GoatStateRestoreLate(dir); // B52','    // B52'],
 [REVIEW,'an unadopted position is not held at OnInit','   if(!holding && Engine_Mode==Engine_Single && FindNumberOfPositions(OP_BUYSELL,MAGIC1)>0) holding=true; // B52','   // B52'],
 [REVIEW,'the grid engine counts an orphan at OnInit','   if(!holding && Engine_Mode==Engine_Single && FindNumberOfPositions','   if(!holding && FindNumberOfPositions'],
 // P2: Gate_Recheck reads B50's entry block.
 [F5,'the first-order gate ignores the clock block','   if(g_GoatEntryBlocked)                         return "clock_blocked"; // B52','   // B52'],
 // P1 and P3: the OnInit refusals.
 [CLOCK,'the New York clock trades a live chart','   if(Clock_Mode==Clock_NewYork && !MQLInfoInteger(MQL_TESTER)) {','   if(false) {'],
 [CLOCK,'the New York clock is refused in the tester too','   if(Clock_Mode==Clock_NewYork && !MQLInfoInteger(MQL_TESTER)) {','   if(Clock_Mode==Clock_NewYork && true) {'],
 [REVIEW,'the benchmark runs under the first-order gate','   if(Random_Direction && Gate_Recheck==Gate_AtFirstOrder) {','   if(false) {'],
 // Codex on GOAT-EA#296: F6's refusal is the grid's only (4502334956); F5's exemption is a real order, not Traded (4502419410).
 [REVIEW,'a one-trade RiskperSeq single is refused at OnInit','   if(Engine_Mode!=Engine_Single && Mode_Lots == RiskperSeq && Max_Seq_Trades<=1) {','   if(Mode_Lots == RiskperSeq && Max_Seq_Trades<=1) {'],
 [F5,'the first-order exemption is Traded again','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual || GuardRealStarted) return false;','    if(Gate_Recheck!=Gate_AtFirstOrder || Virtual || Traded) return false;'],
 // Claude-Mac's ask: a held single opens nothing and keeps its episode armed. Two edits each: the start path's own hold
 // (DashboardEntryAllowed) refuses before the single is reached, so a regression has to pass it to show.
 [REVIEW,'the feed guard holds no single',[['   if(GoatEntriesHeld()) return false; // B49b (LAG-A): the feed is behind','   if(false) return false; // B49b (LAG-A): the feed is behind'],
  ['   if(GoatEntriesHeld()) return false;                            // B51 (merge with B49b)','   if(false) return false;                            // B51 (merge with B49b)']]],
 [REVIEW,'a held open disarms the episode',[['   if(GoatEntriesHeld()) return false; // B49b (LAG-A): the feed is behind','   if(false) return false; // B49b (LAG-A): the feed is behind'],
  ['   if(GoatEntriesHeld()) return false;                            // B51 (merge with B49b)','   if(GoatEntriesHeld()) {g_GoatSingleArmed[0]=false; g_GoatSingleArmed[1]=false; return false;} // B51 (merge with B49b)']]],
];
// A mutant is [test, label, from, to] or [test, label, [[from, to], ...]].
const edits=m=>Array.isArray(m[2])?m[2]:[[m[2],m[3]]];
function runOn(test,text){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-b52-'));
 const file=path.join(dir,'GOAT V1.49.mq5');fs.writeFileSync(file,'﻿'+text.replace(/\n/g,'\r\n'),'utf8');
 return new Promise(resolve=>{
  const child=spawn(process.execPath,[path.join(__dirname,test)],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},stdio:['ignore','ignore','pipe']});
  let err='';child.stderr.on('data',d=>{err+=d;});
  child.on('close',code=>{fs.rmSync(dir,{recursive:true,force:true});resolve({status:code,stderr:err});});
 });
}
(async()=>{
 for(const test of [REVIEW,F5,CLOCK]){const base=await runOn(test,SOURCE);assert.equal(base.status,0,test+': the unmutated test passes on the scratch source: '+base.stderr);}
 for(const m of MUTANTS)for(const [from] of edits(m)){const n=SOURCE.split(from).length-1;assert.equal(n,1,`mutant "${m[1]}": its anchor must occur exactly once (found ${n})`);}
 let next=0,killed=0;const survivors=[];
 const worker=async()=>{while(next<MUTANTS.length){const m=MUTANTS[next++],[test,label]=m;
   const r=await runOn(test,edits(m).reduce((text,[from,to])=>text.replace(from,()=>to),SOURCE));
   if(r.status===0)survivors.push(label);else killed++;}};
 await Promise.all(Array.from({length:Math.max(2,Math.min(8,os.cpus().length))},worker));
 assert.deepEqual(survivors,[],'mutants survived');
 console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
})().catch(e=>{console.error(e);process.exit(1);});
