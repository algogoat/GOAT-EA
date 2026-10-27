// Mutation check for the CID guard (B46, B47; goatai#2350): every guard that keeps an orphan from being masked is
// load-bearing. Each mutant edits GOAT V1.49.mq5 in memory; test_cid_guard.cjs, run against a scratch tree holding the
// mutated entrypoint (GOAT_EA_ROOT), must then fail. Anchors sit on guard lines, never on the build ID or marker lines,
// so a build bump never breaks this check.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_cid_guard.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const COPIED=['GOAT_Inputs_Definitions.mqh','controller/contracts/v149/dependencies.json'];
const MUTANTS=[
 // B47 item 1: stale CID records.
 ['stale CID record maps again (stale-record masking re-opened)','if(GoatCidGuardHas(cidg_live,cidg_value)) GoatCidGuardAdd(cidg_mapped,cidg_magic);','GoatCidGuardAdd(cidg_mapped,cidg_magic);'],
 ['an open chart without an EA counts as live','      if(ChartGetString(cidg_c,CHART_EXPERT_NAME)=="") continue;\n',''],
 ['the open-chart walk is unbounded','cidg_c>=0 && cidg_walked<GOAT_CID_CHART_WALK_MAX;','cidg_c>=0;'],
 // B47 item 2: claim heartbeat expiry.
 ['claims never expire','return(cidg_age>GOAT_CID_CLAIM_STALE_SEC ? GOAT_CID_CLAIM_STALE : GOAT_CID_CLAIM_FRESH);','return GOAT_CID_CLAIM_FRESH;'],
 ['a claim exactly at the bar is stale','return(cidg_age>GOAT_CID_CLAIM_STALE_SEC ?','return(cidg_age>=GOAT_CID_CLAIM_STALE_SEC ?'],
 ['a stamp in the future is accepted','   if(cidg_age<-GOAT_CID_CLAIM_FUTURE_SEC) return GOAT_CID_CLAIM_UNREADABLE;\n',''],
 ['a stale claim of another terminal still exempts','if(cidg_claim==GOAT_CID_CLAIM_FRESH && cidg_owner!=cidg_terminal) return false;','if(cidg_owner!="" && cidg_owner!=cidg_terminal) return false;'],
 ['the heartbeat is not throttled','   if(!cidg_force && g_GoatCidGuardClaimed && cidg_now-g_GoatCidGuardClaimedMs<GOAT_CID_CLAIM_HEARTBEAT_MS) return;\n',''],
 ['another terminal\'s fresh claim is overwritten','if(GoatCidGuardClaimRead(MAGIC1,Symbol(),cidg_owner)==GOAT_CID_CLAIM_FRESH && cidg_owner!=cidg_terminal) return;','GoatCidGuardClaimRead(MAGIC1,Symbol(),cidg_owner);'],
 ['the heartbeat is not on the timer','   GoatCidGuardHeartbeat(); // B47:','   // GoatCidGuardHeartbeat(); // B47:'],
 ['the stamp is broker time','FileWrite(cidg_h,IntegerToString((long)TimeGMT()));','FileWrite(cidg_h,IntegerToString((long)TimeCurrent()));'],
 // B47 item 4: an unreadable claim refuses.
 ['an unopenable claim counts as no claim','if(cidg_h==INVALID_HANDLE) return GOAT_CID_CLAIM_UNREADABLE;','if(cidg_h==INVALID_HANDLE) return GOAT_CID_CLAIM_NONE;'],
 ['an unparsable claim counts as no claim','IntegerToString(cidg_stamp)!=cidg_when) return GOAT_CID_CLAIM_UNREADABLE;','IntegerToString(cidg_stamp)!=cidg_when) return GOAT_CID_CLAIM_NONE;'],
 ['an unowned claim is not GOAT evidence','if(cidg_claim!=GOAT_CID_CLAIM_NONE) return true;','if(false) return true;'],
 // B47 item 5: no claim under login 0.
 ['a claim is written under login 0','if(AccountInfoInteger(ACCOUNT_LOGIN)<=0 || MAGIC1<=0) return;','if(MAGIC1<=0) return;'],
 // B47 item 3: cid_duplicate freezes adds.
 ['cid_duplicate does not freeze adds','if(g_GoatCidGuardReason!="cid_duplicate")','if(true)'],
 ['orphan_suspected freezes adds too','if(g_GoatCidGuardReason!="cid_duplicate")','if(g_GoatCidGuardReason=="")'],
 ['Add_Level does not consult the freeze','    if(!Virtual && GoatCidGuardAddFrozen(dir,Level_Count+1)) return false;','    if(false) return false;'],
 ['the freeze logs every add','if(!g_GoatCidGuardFreezeLogged[cidg_side])','if(true)'],
 ['the freeze never re-evaluates','GoatCidGuardRefuses(!g_GoatCidGuardChecked || GetTickCount()-g_GoatCidGuardCheckedMs>=GOAT_CID_ADD_RECHECK_MS);','GoatCidGuardRefuses(false);'],
 // B49a (B48): the daily CID touch.
 ['the touch is not on the heartbeat','   GoatCidDailyTouch(); // B49a (B48)','   // GoatCidDailyTouch(); // B49a (B48)'],
 ['the touch runs every heartbeat','if(cidt_day<=0 || cidt_day==g_GoatCidTouchedDay) return;','if(cidt_day<=0) return;'],
 ['a failed write retries every heartbeat','if(g_GoatCidTouchFailed && cidt_now-g_GoatCidTouchFailedMs<GOAT_CID_TOUCH_RETRY_MS) return;','if(false) return;'],
 ['a failed write marks the day done','      g_GoatCidTouchFailedMs=cidt_now;\n      return;','      g_GoatCidTouchFailedMs=cidt_now;\n      g_GoatCidTouchedDay=cidt_day;\n      return;'],
 ['the touch overwrites the record\'s value','   if(cidt_had && (!GlobalVariableGet(cidt_own,cidt_value) || cidt_value<=0.0)) return;','   cidt_value=(double)cidt_chart+1;'],
 ['a record wiped between check and read is re-set to 0','   if(cidt_had && (!GlobalVariableGet(cidt_own,cidt_value) || cidt_value<=0.0)) return;','   if(cidt_had) GlobalVariableGet(cidt_own,cidt_value);'],
 ['a 0 record is renewed','   if(cidt_had && (!GlobalVariableGet(cidt_own,cidt_value) || cidt_value<=0.0)) return;','   if(cidt_had && !GlobalVariableGet(cidt_own,cidt_value)) return;'],
 ['the renewal is not flushed to disk','   GlobalVariablesFlush();   // to gvariables.dat now','   ;   // to gvariables.dat now'],
 ['the touch does not restore a missing record','   if(GlobalVariableSet(cidt_own,cidt_value)==0)','   if(!cidt_had || GlobalVariableSet(cidt_own,cidt_value)==0)'],
 // B46: the refusal itself.
 ['the entry gate is dropped','   if(GoatCidGuardRefuses(true)) return false; // B46: a missing or duplicate CID record refuses new sequences (GoatCidGuardEvaluate)\n',''],
 ['a duplicate CID record is not refused','if(ArraySize(cidg_mine)>1 || (ArraySize(cidg_mine)==1 && cidg_mine[0]!=MAGIC1))','if(false)'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-cidg-'));
 try{
  for(const rel of COPIED){fs.mkdirSync(path.dirname(path.join(dir,rel)),{recursive:true});fs.copyFileSync(path.join(ROOT,rel),path.join(dir,rel));}
  fs.writeFileSync(path.join(dir,'GOAT V1.49.mq5'),'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
const clean=runOn(MAIN);
assert.equal(clean.status,0,'the unmutated test passes on the scratch tree: '+clean.stderr);
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
