// Mutation check for the hourly policy touch (GOAT-EA#328 follow-up): every rule is load-bearing. Each mutant edits
// GOAT V1.49.mq5 in memory; test_dash_policy_touch.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must then fail.
// Anchors sit on the touch's own lines, never on the build ID or marker lines. Each mutant's line shows what the test
// saw. The write mutants are the point of Claude-Mac's review on GOAT-EA#330: a write-back races the dashboard.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_dash_policy_touch.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const GATE='   if(dpt_hour<=0 || dpt_hour==g_goat_dash_policy_touched_hour) return;';
const READ='   if(GlobalVariableCheck(dpt_name)) GlobalVariableGet(dpt_name,dpt_value); // a read only: it renews the lifetime';
const DONE='   g_goat_dash_policy_touched_hour=dpt_hour;\n';
const HEAD='void GoatDashPolicyHourlyTouch(void)\n  {\n';
const GUARDS=HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n   if(MAGIC1<=0)                                                         return;\n';
const touchLine=arg=>'   GoatDashPolicyTouchOne('+arg+');\n';
const MUTANTS=[
 // Nothing is written: Claude-Mac's required change, and its neighbours.
 ['the touch writes the value back (the race of GOAT-EA#330)',READ,'   if(GlobalVariableCheck(dpt_name) && GlobalVariableGet(dpt_name,dpt_value)) GlobalVariableSet(dpt_name,dpt_value);'],
 ['the touch writes 0',READ,'   if(GlobalVariableCheck(dpt_name)) GlobalVariableSet(dpt_name,0.0);'],
 ['the touch writes with a condition',READ,'   if(GlobalVariableCheck(dpt_name) && GlobalVariableGet(dpt_name,dpt_value)) GlobalVariableSetOnCondition(dpt_name,dpt_value,dpt_value);'],
 ['the touch deletes the variable',READ,'   if(GlobalVariableCheck(dpt_name)) GlobalVariableDel(dpt_name);'],
 ['the touch creates a missing variable',READ,'   if(!GlobalVariableCheck(dpt_name)) GlobalVariableTemp(dpt_name); GlobalVariableGet(dpt_name,dpt_value);'],
 ['the touch flushes',DONE,DONE+'   GlobalVariablesFlush();\n'],
 ['the touch reads nothing',READ,'   GlobalVariableCheck(dpt_name);'],
 // Not a mutant: dropping the GlobalVariableCheck alone is equivalent in MT5 (a read of a missing variable answers false
 // and creates nothing). It stays as GoatCidDailyTouch's explicit check before the read.
 // The hour gate.
 ['the hour gate is removed (a read every tick)',GATE,'   if(dpt_hour<=0) return;'],
 ['the hour is never marked done (a read every tick)',DONE,'   ;\n'],
 ['the gate is a day, not an hour','   datetime dpt_hour=dpt_gmt-dpt_gmt%3600;','   datetime dpt_hour=dpt_gmt-dpt_gmt%86400;'],
 ['the gate is a minute','   datetime dpt_hour=dpt_gmt-dpt_gmt%3600;','   datetime dpt_hour=dpt_gmt-dpt_gmt%60;'],
 // The five variables.
 ['the chart\'s paused variable is not read',touchLine('GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_PAUSED)'),''],
 ['the chart\'s trade mask is not read',touchLine('GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_TRADE_MASK)'),''],
 ['the chart\'s exposure mode is not read',touchLine('GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE)'),''],
 ['the portfolio\'s paused variable is not read',touchLine('GoatPortfolioGVName("DashboardPolicyPaused")'),''],
 ['the portfolio\'s exposure mode is not read',touchLine('GoatPortfolioGVName("DashboardExposurePolicyMode")'),''],
 // Live only.
 ['the touch runs on batch and dashboard charts',GUARDS,HEAD+'   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n   if(MAGIC1<=0)                                                         return;\n'],
 ['the touch runs in optimization and forward passes',GUARDS,HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MAGIC1<=0)                                                         return;\n'],
 ['the touch runs without a magic',GUARDS,HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n'],
 // On the timer.
 ['the touch is not on the timer','      GoatDashPolicyHourlyTouch(); // B55 (GOAT-EA#328)','      // B55 (GOAT-EA#328)'],
 // The reference the read relies on stays quoted in the code.
 ['the MQL5 reference is no longer quoted','// setting of a new value, but reading of the global variable value, as well."','// setting of a new value."'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-dashtouch-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
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
 const saw=(r.stderr.match(/AssertionError(?: \[\w+\])?: ([^\n]*)/)||[])[1]||r.stderr.trim().split('\n').find(l=>/Error/.test(l))||'failed';
 console.log('killed: '+label+'\n   -> '+saw);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
