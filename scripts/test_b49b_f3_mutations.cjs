// Mutation check for B49b PR-3 (F3, Fix_ClosePath): every guard of the close path is load-bearing. Each mutant edits
// GOAT V1.49.mq5 in memory; test_b49b_f3.cjs (or test_restart_adopt.cjs for the monotonic SL), run on the mutated
// entrypoint (GOAT_EA_MAIN), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..');
const F3=path.join(__dirname,'test_b49b_f3.cjs'),ADOPT=path.join(__dirname,'test_restart_adopt.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 // The deferral.
 ['Off defers too','    if(Fix_ClosePath!=GoatFix_On || Virtual || !Active || !Traded) return false;','    if(Virtual || !Active || !Traded) return false;',F3],
 ['a virtual sequence defers','    if(Fix_ClosePath!=GoatFix_On || Virtual || !Active || !Traded) return false;','    if(Fix_ClosePath!=GoatFix_On || !Active || !Traded) return false;',F3],
 ['an untraded sequence defers','    if(Fix_ClosePath!=GoatFix_On || Virtual || !Active || !Traded) return false;','    if(Fix_ClosePath!=GoatFix_On || Virtual || !Active) return false;',F3],
 ['a flat sequence defers','    if(FindNumberOfPositions(dir,MAGIC1)==0) return false;\n    if(ClosePendingReason=="")','    if(ClosePendingReason=="")',F3],
 ['the deferral is never logged','    if(ClosePendingReason=="")\n       Print(Desc,": ",desc,','    if(false)\n       Print(Desc,": ",desc,',F3],
 ['the deferral logs every request','    if(ClosePendingReason=="")\n       Print(Desc,": ",desc,','    if(true)\n       Print(Desc,": ",desc,',F3],
 ['the reason is not kept','    ClosePendingReason=desc;\n    return true;','    return true;',F3],
 // The pump.
 ['the pump never ends a flat sequence','    string reason=ClosePendingReason;\n    ClosePendingReason=""; ClosePendingTried=0;\n    End_Sequence(reason);','    ClosePendingReason=""; ClosePendingTried=0;',F3],
 ['the pump ends before flat','     if(FindNumberOfPositions(dir,MAGIC1)>0) return;\n    }','    }',F3],
 ['the pump is not rate-bound','     if(now==ClosePendingTried) return;   // once per server second (deterministic in the tester)\n','',F3],
 ['the pump never retries the close','     CloseAllPositions(dir,MAGIC1);\n     if(FindNumberOfPositions(dir,MAGIC1)>0) return;','     if(FindNumberOfPositions(dir,MAGIC1)>0) return;',F3],
 ['an inactive pending is kept','    if(!Active) {ClosePendingReason=""; ClosePendingTried=0; return;}','    if(!Active) return;',F3],
 // Placement.
 ['End_Sequence never defers','    if(EndDeferredUntilFlat(desc)) return; // B49b (F3): Fix_ClosePath, a sequence ends only when its positions are flat\n','',F3],
 ['an end leaves the reason','     ClosePendingReason=""; ClosePendingTried=0; // B49b (F3)\n     ResetSequenceRiskState();','     ResetSequenceRiskState();',F3],
 ['adds go on while a close is pending','    if(!Virtual && ClosePendingReason!="") return false; // B49b (F3): no add while an end waits for its close\n','',F3],
 ['OnTick never pumps','   Seq_Buy.ClosePendingPump(); Seq_Sell.ClosePendingPump(); // B49b (F3): an end deferred until flat retries its close\n','',F3],
 // The logs.
 ['a failed close logs in the tester','{closeErrors++; if(!MQLInfoInteger(MQL_TESTER)) PrintFormat("Close failed:','{closeErrors++; PrintFormat("Close failed:',F3],
 ['a failed modify stays silent','{TPmodifyErrors++; if(!MQLInfoInteger(MQL_TESTER)) PrintFormat("TP/SL modify failed:','{TPmodifyErrors++; if(false) PrintFormat("TP/SL modify failed:',F3],
 // The monotonic SL (restart_adopt section 16).
 ['a broker SL can be loosened','       if(Fix_ClosePath==GoatFix_On) Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);','       ;',ADOPT],
 ['the monotonic SL runs with the flag off','       if(Fix_ClosePath==GoatFix_On) Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);','       Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);',ADOPT],
];
function runOn(test,mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f3-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[test],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
for(const test of [F3,ADOPT]){const r=runOn(test,MAIN);assert.equal(r.status,0,'the unmutated '+path.basename(test)+' passes on the scratch entrypoint: '+r.stderr);}
let killed=0;
for(const [label,from,to,test] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(test,MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
