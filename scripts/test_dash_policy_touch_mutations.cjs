// Mutation check for the hourly policy touch (GOAT-EA#328 follow-up): every rule is load-bearing. Each mutant edits
// GOAT V1.49.mq5 in memory; test_dash_policy_touch.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must then fail.
// Anchors sit on the touch's own lines, never on the build ID or marker lines. Each mutant's line shows what the test
// saw (the hour gate removed: a write every tick).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_dash_policy_touch.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const GATE='   if(dpt_hour<=0 || dpt_hour==g_goat_dash_policy_touched_hour) return;';
const HEAD='void GoatDashPolicyHourlyTouch(void)\n  {\n';
const GUARDS=HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n   if(MAGIC1<=0)                                                         return;\n';
const MUTANTS=[
 // The hour gate.
 ['the hour gate is removed (a touch every tick)',GATE,'   if(dpt_hour<=0) return;'],
 ['the hour is never marked done (a touch every tick)','   g_goat_dash_policy_touched_hour=dpt_hour;\n','   ;\n'],
 ['the gate is a day, not an hour','   datetime dpt_hour=dpt_gmt-dpt_gmt%3600;','   datetime dpt_hour=dpt_gmt-dpt_gmt%86400;'],
 ['the gate is a minute','   datetime dpt_hour=dpt_gmt-dpt_gmt%3600;','   datetime dpt_hour=dpt_gmt-dpt_gmt%60;'],
 // No flush, nothing created, no value changed.
 ['the touch flushes','   g_goat_dash_policy_touched_hour=dpt_hour;\n','   g_goat_dash_policy_touched_hour=dpt_hour;\n   GlobalVariablesFlush();\n'],
 ['the touch creates a missing variable','   if(!GlobalVariableCheck(dpt_name))          return true; // missing: never created here\n   if(!GlobalVariableGet(dpt_name,dpt_value))  return true;','   GlobalVariableGet(dpt_name,dpt_value);'],
 // Not a mutant: dropping the GlobalVariableCheck line alone is equivalent (the by-reference read answers false for a
 // missing variable and the touch returns). It stays as GoatCidDailyTouch's explicit check before the read.
 ['a variable gone between the check and the read is re-created at 0','   if(!GlobalVariableGet(dpt_name,dpt_value))  return true;','   GlobalVariableGet(dpt_name,dpt_value);'],
 ['the touch writes a different value (0)','   return(GlobalVariableSet(dpt_name,dpt_value)!=0);','   return(GlobalVariableSet(dpt_name,0.0)!=0);'],
 ['the touch writes a different value (1)','   return(GlobalVariableSet(dpt_name,dpt_value)!=0);','   return(GlobalVariableSet(dpt_name,1.0)!=0);'],
 ['the touch only reads (nothing is re-set)','   return(GlobalVariableSet(dpt_name,dpt_value)!=0);','   return true;'],
 // The five variables.
 ['the chart\'s paused variable is not touched','   bool dpt_ok=GoatDashPolicyTouchOne(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_PAUSED));','   bool dpt_ok=true;'],
 ['the chart\'s trade mask is not touched','   if(!GoatDashPolicyTouchOne(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_TRADE_MASK)))    dpt_ok=false;\n',''],
 ['the chart\'s exposure mode is not touched','   if(!GoatDashPolicyTouchOne(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE))) dpt_ok=false;\n',''],
 ['the portfolio\'s paused variable is not touched','   if(!GoatDashPolicyTouchOne(GoatPortfolioGVName("DashboardPolicyPaused")))                        dpt_ok=false;\n',''],
 ['the portfolio\'s exposure mode is not touched','   if(!GoatDashPolicyTouchOne(GoatPortfolioGVName("DashboardExposurePolicyMode")))                  dpt_ok=false;\n',''],
 // Live only.
 ['the touch runs on batch and dashboard charts',GUARDS,HEAD+'   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n   if(MAGIC1<=0)                                                         return;\n'],
 ['the touch runs in optimization and forward passes',GUARDS,HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MAGIC1<=0)                                                         return;\n'],
 ['the touch runs without a magic',GUARDS,HEAD+'   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;\n'],
 // A failed write.
 ['a failed write marks the hour done','      g_goat_dash_policy_touch_failed_ms=dpt_now;\n      return;','      g_goat_dash_policy_touch_failed_ms=dpt_now;\n      g_goat_dash_policy_touched_hour=dpt_hour;\n      return;'],
 ['a failed write retries every tick','   if(g_goat_dash_policy_touch_failed && dpt_now-g_goat_dash_policy_touch_failed_ms<GOAT_DASH_POLICY_TOUCH_RETRY_MS) return;\n',''],
 ['a failed write is never retried within the hour','      g_goat_dash_policy_touch_failed=true;\n      g_goat_dash_policy_touch_failed_ms=dpt_now;\n      return;','      g_goat_dash_policy_touched_hour=dpt_hour;\n      return;'],
 ['a failure is logged every time','      if(!g_goat_dash_policy_touch_failed)\n','      if(true)\n'],
 ['a failure is never logged again','   g_goat_dash_policy_touch_failed=false;\n   g_goat_dash_policy_touched_hour=dpt_hour;','   g_goat_dash_policy_touched_hour=dpt_hour;'],
 ['a failed write goes unnoticed','   if(!GoatDashPolicyTouchOne(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE))) dpt_ok=false;','   GoatDashPolicyTouchOne(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE));'],
 // On the timer.
 ['the touch is not on the timer','      GoatDashPolicyHourlyTouch(); // B55 (GOAT-EA#328)','      // B55 (GOAT-EA#328)'],
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
