// Mutation check for the dashboard bus's one final acknowledgement per command id (GOAT-EA#328): every rule is
// load-bearing. Each mutant edits GOAT V1.49.mq5 in memory (or, for the publish order of Codex on GOAT-EA#330,
// Dashboard.mqh at all four publish sites); test_dash_ack_once.cjs, run on the mutated entrypoint (GOAT_EA_MAIN) or
// dashboard (GOAT_EA_DASH), must then fail. Anchors sit on the fix's own lines, never on the build ID or marker lines. Each
// mutant's line shows what the test saw (the guard removed: 120 acknowledgements and 120 flushes over 120 ticks).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_dash_ack_once.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const DASH=fs.readFileSync(path.join(ROOT,'Dashboard.mqh'),'utf8').replace(/\r\n/g,'\n');
const FINAL='return(ack_status==GOAT_DASH_ACK_APPLIED || ack_status==GOAT_DASH_ACK_REJECTED || ack_status==GOAT_DASH_ACK_EXPIRED);';
const MUTANTS=[
 // The guard: a command id with a final acknowledgement is not processed again.
 ['the guard is removed (every tick acknowledges and flushes again)','   if(GoatDashFinalAcked(command_id)) return; // B55 (GOAT-EA#328)','   // B55 (GOAT-EA#328)'],
 ['the guard knows only the applied id (expired and rejected still loop)','   if(GoatDashFinalAcked(command_id)) return; // B55 (GOAT-EA#328)','   if(command_id==DashboardPortfolioCommandIdApplied) return; // B55 (GOAT-EA#328)'],
 ['a final acknowledgement is never recorded','   GoatDashNoteFinalAck(command_id,ack_status); // B55 (GOAT-EA#328)','   // B55 (GOAT-EA#328)'],
 ['every acknowledgement is recorded as final (a close that is not flat is never retried)','   if(GoatDashAckIsFinal(ack_status)) g_goat_dash_final_ack_id=command_id;\n  }','   g_goat_dash_final_ack_id=command_id;\n  }'],
 ['the guard compares nothing (every tick acknowledges and flushes again)','   return(command_id==g_goat_dash_final_ack_id);','   return(false);'],
 // Which statuses are final.
 ['APPLIED is not final',FINAL,'return(ack_status==GOAT_DASH_ACK_REJECTED || ack_status==GOAT_DASH_ACK_EXPIRED);'],
 ['REJECTED is not final',FINAL,'return(ack_status==GOAT_DASH_ACK_APPLIED || ack_status==GOAT_DASH_ACK_EXPIRED);'],
 ['EXPIRED is not final',FINAL,'return(ack_status==GOAT_DASH_ACK_APPLIED || ack_status==GOAT_DASH_ACK_REJECTED);'],
 ['FAILED is final (a close that is not flat is never retried)',FINAL,'return(ack_status!=0);'],
 // The restart seeding.
 ['OnInit does not seed (a restart acknowledges the stored command again)','     GoatDashSeedFinalAck(); // B55 (GOAT-EA#328)','     // B55 (GOAT-EA#328)'],
 ['the seeding ignores the stored status (a close in progress is dropped at a restart)','   if(ack_id>0 && GoatDashAckIsFinal((int)GlobalVariableGet(ack_status_key))) g_goat_dash_final_ack_id=ack_id;','   if(ack_id>0) g_goat_dash_final_ack_id=ack_id;'],
 ['the seeding runs on batch and dashboard charts','void GoatDashSeedFinalAck(void)\n  {\n   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;\n','void GoatDashSeedFinalAck(void)\n  {\n'],
 // A retrying close: its acknowledgement is written and flushed only when its values change.
 ['the on-change check is removed (every failed retry rewrites and flushes)','   if(GoatDashCloseAckUnchanged(command_id,ack_status,closed_positions,close_errors,remaining)) return; // B55 (GOAT-EA#328)','   // B55 (GOAT-EA#328)'],
 ['the on-change check never remembers what it wrote','   g_goat_dash_close_ack_id=command_id;           g_goat_dash_close_ack_status=ack_status;\n',''],
 ['the on-change check ignores the command id (a new command\'s first FAILED is held back)','   if(!GoatDashAckIsFinal(ack_status) && command_id==g_goat_dash_close_ack_id && ','   if(!GoatDashAckIsFinal(ack_status) && '],
 ['the on-change check ignores the counts (a changed remaining count is not written)','      closed_positions==g_goat_dash_close_ack_closed && close_errors==g_goat_dash_close_ack_errors && remaining==g_goat_dash_close_ack_remaining) return true;','      true) return true;'],
 // Not a mutant: dropping `!GoatDashAckIsFinal(ack_status) &&` is equivalent. A final status differs from the FAILED
 // written before it, and the guard never lets a second final acknowledgement of one id through. It stays as the
 // explicit rule: a final acknowledgement is always written.
 // Codex on GOAT-EA#330: the id is read again after the fields.
 ['the id is not read again after the fields (a poll during a publish applies a torn command)','   if((long)GlobalVariableGet(cmd_id_key)==command_id) DashboardBusApplyCommand(','   DashboardBusApplyCommand('],
 // The acknowledgement keeps its flush (once per command now).
 ['the acknowledgement is not flushed to disk','(double)DashboardNormalizeExposurePolicyMode(DashboardExposurePolicyMode));\n   GlobalVariablesFlush();\n  }','(double)DashboardNormalizeExposurePolicyMode(DashboardExposurePolicyMode));\n  }'],
];
// Codex on GOAT-EA#330: the dashboard's publish order. Each edits all four publish sites (the anchors are counted below).
const CLEAR=/^      GlobalVariableSet\(GoatChildGVName\(g_sets\[idx\]\.magic,g_sets\[idx\]\.sym,GOAT_GV_FIELD_CMD_ID\),0\.0\);[^\n]*\n/gm;
const LAST=/^      GlobalVariableSet\(GoatChildGVName\(g_sets\[idx\]\.magic,g_sets\[idx\]\.sym,GOAT_GV_FIELD_CMD_ID\),\(double\)m_portfolio_command_id\);[^\n]*\n/gm;
const TYPELINE=/^(      GlobalVariableSet\(GoatChildGVName\(g_sets\[idx\]\.magic,g_sets\[idx\]\.sym,GOAT_GV_FIELD_CMD_TYPE\),[^\n]*\n)/gm;
const ID_LINE='      GlobalVariableSet(GoatChildGVName(g_sets[idx].magic,g_sets[idx].sym,GOAT_GV_FIELD_CMD_ID),(double)m_portfolio_command_id);\n';
const DASH_MUTANTS=[
 ['the dashboard does not clear the id first (a child mid-read takes the new fields under the older id)',d=>d.replace(CLEAR,'')],
 ['the dashboard writes the id before the fields (a child reads a new id with the older fields)',d=>d.replace(LAST,'').replace(TYPELINE,ID_LINE+'$1')],
 ['the dashboard publishes as B54 did: id first, no clear (Codex: a new id with an expired expiry is EXPIRED for good)',d=>d.replace(LAST,'').replace(CLEAR,ID_LINE)],
];
function runOn(mainText,dashText=DASH){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-dashack-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  const dashFile=path.join(dir,'Dashboard.mqh');
  fs.writeFileSync(dashFile,'﻿'+dashText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_MAIN:file,GOAT_EA_DASH:dashFile},encoding:'utf8',timeout:300000});
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
const count=re=>(DASH.match(re)||[]).length;
assert.deepEqual([count(CLEAR),count(LAST),count(TYPELINE)],[4,4,4],'the publish-order anchors occur at all four sites of Dashboard.mqh');
for(const [label,edit] of DASH_MUTANTS){
 const mutated=edit(DASH);
 assert.notEqual(mutated,DASH,'mutant "'+label+'" changes Dashboard.mqh');
 const r=runOn(MAIN,mutated);
 assert.notEqual(r.status,0,'mutant survived: '+label);
 const saw=(r.stderr.match(/AssertionError(?: \[\w+\])?: ([^\n]*)/)||[])[1]||r.stderr.trim().split('\n').find(l=>/Error/.test(l))||'failed';
 console.log('killed: '+label+'\n   -> '+saw);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length+DASH_MUTANTS.length,killed}));
