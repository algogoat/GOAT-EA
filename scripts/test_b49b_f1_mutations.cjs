// Mutation check for B49b PR-2 (F1 full): every manage-only gate, state-file check and hook is load-bearing. Each
// mutant edits GOAT V1.49.mq5 in memory; test_b49b_f1.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must fail.
// Equivalent, not listed: dropping GoatStateDayRestore's "pending=false" (IsNewDay fires once per server day, and a
// later day's section is refused by the day check anyway).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..');
const F1=path.join(__dirname,'test_b49b_f1.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const MUTANTS=[
 // 1. Who is manage-only.
 ['manage-only opens new sequences','   if(g_GoatManageOnly!=GOAT_MANAGE_NONE) return false; // B49b (F1): manage-only',''],
 ['the report tool goes manage-only','   return(Mode_Operation==Operation_Standard && Mode!="EXPORT");','   return(Mode_Operation!=Operation_Batch && Mode_Operation!=Operation_Dash);'],
 ['the export run goes manage-only','Mode_Operation==Operation_Standard && Mode!="EXPORT"','Mode_Operation==Operation_Standard'],
 ['the tester goes manage-only','   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return false;\n   return(Mode_Operation==Operation_Standard','   return(Mode_Operation==Operation_Standard'],
 ['401 goes manage-only','key==LICENSE_VALID || key==401 || key==403) return false;','key==LICENSE_VALID || key==403) return false;'],
 ['403 goes manage-only','key==LICENSE_VALID || key==401 || key==403) return false;','key==LICENSE_VALID || key==401) return false;'],
 ['an unchecked licence goes manage-only','!GoatManageOnlyLive() || key==0 || key==LICENSE_VALID','!GoatManageOnlyLive() || key==LICENSE_VALID'],
 ['a 5xx outage reads as a refusal','((key<0 || key>=500) ? GOAT_MANAGE_LICENCE_DOWN','((key<0) ? GOAT_MANAGE_LICENCE_DOWN'],
 ['a network failure reads as a refusal','((key<0 || key>=500) ? GOAT_MANAGE_LICENCE_DOWN','((key>=500) ? GOAT_MANAGE_LICENCE_DOWN'],
 ['an outage lifts expiry','   if(g_GoatManageOnly!=GOAT_MANAGE_EXPIRED) g_GoatManageOnly=((key','   g_GoatManageOnly=((key'],
 ['the retry clock does not start at init','   g_GoatLicenceRetriedMs=GetTickCount();\n   Print("GOAT manage-only: reason=",GoatManageOnlyReason()," licence_status="','   Print("GOAT manage-only: reason=",GoatManageOnlyReason()," licence_status="'],
 ['the tester expires manage-only','   if(!GoatManageOnlyLive()) return false;\n   if(g_GoatManageOnly!=GOAT_MANAGE_EXPIRED)\n','   if(g_GoatManageOnly!=GOAT_MANAGE_EXPIRED)\n'],
 // 2. The sequence's section.
 ['a tester or batch writes a section','    if(!PersistLive() || !Active || !Traded || PersistStartMsc==0) return "";','    if(!Active || !Traded || PersistStartMsc==0) return "";'],
 ['an unrecorded sequence writes a section','    if(!PersistLive() || !Active || !Traded || PersistStartMsc==0) return "";','    if(!PersistLive() || !Active || !Traded) return "";'],
 ['the reason keeps its newlines','    StringReplace(reason,"\\n"," "); StringReplace(reason,"\\r"," ");\n','    StringReplace(reason,"\\r"," ");\n'],
 ['an unmatched basket takes a section','    if(!Adopted || !AdoptMatched) return;','    if(!Adopted) return;'],
 ['another start is restored','v[0]!=IntegerToString(PersistStartMsc) || v[1]','v[1]'],
 ['another first ticket is restored',' || v[1]!=IntegerToString((long)PersistFirstTicket))\n',')\n'],
 ['an incomplete section is restored','    if(present<ArraySize(fields) || v[0]','    if(v[0]'],
 ['the trailing flag is not restored','Trailing=(v[9]=="1");','Trailing=false;'],
 ['the rescue is not restored','    BiasRescueActive=(v[4]=="1"); ','    '],
 ['the deferred close is not restored','ClosePendingReason=GoatStateValue(keys,values,p+"close_reason");','ClosePendingReason="";'],
 ['the stops move without frozen sizes','    if(AdoptSizes) UpdateLockTPSL(Trades_Count); // the rescue BE','    UpdateLockTPSL(Trades_Count); // the rescue BE'],
 ['the restored state waits for a tick','    if(AdoptSizes) UpdateLockTPSL(Trades_Count); // the rescue BE','    // the rescue BE'],
 // Adds.
 ['manage-only adds','&& !g_GoatStateFailed && g_GoatManageOnly==GOAT_MANAGE_NONE) {ManageOnlyLogged=false; return false;}','&& !g_GoatStateFailed) {ManageOnlyLogged=false; return false;}'],
 ['an unwritten state file adds','!PersistFailed && !g_GoatStateFailed && g_GoatManageOnly','!PersistFailed && g_GoatManageOnly'],
 // 4. The live re-init.
 ['a live re-init resets the running sequence','    if(!(Active && !Virtual && GoatManageOnlyLive())) {','    if(true) {'],
 ['a virtual re-init keeps its state','    if(!(Active && !Virtual && GoatManageOnlyLive())) {','    if(!(Active && GoatManageOnlyLive())) {'],
 ['an idle re-init keeps its state','    if(!(Active && !Virtual && GoatManageOnlyLive())) {','    if(!(!Virtual && GoatManageOnlyLive())) {'],
 // 3. The file.
 ['the file is written before the day is stamped','   if(!GoatStateLive() || g_GoatStateDay==0) return;','   if(!GoatStateLive()) return;'],
 ['the tester writes the file','   if(!GoatStateLive() || g_GoatStateDay==0) return;','   if(g_GoatStateDay==0) return;'],
 ['the flush interval is ignored','   if(!force && GetTickCount()-g_GoatStateWrittenMs<GOAT_SQ_FLUSH_MS) return;\n   string text=GoatStateText();','   string text=GoatStateText();'],
 ['unchanged text is rewritten','   if(text==g_GoatStateLast && !g_GoatStateFailed) return;\n',''],
 ['a failed write leaves adds running','   g_GoatStateFailed=true;\n  }\n// The file\'s key=value lines','  }\n// The file\'s key=value lines'],
 ['a good write keeps adds frozen','g_GoatStateLast=text; g_GoatStateFailed=false;','g_GoatStateLast=text;'],
 ['the file is shared across logins','"GOAT\\\\State\\\\"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))+"\\\\"+IntegerToString(MAGIC1)','"GOAT\\\\State\\\\"+IntegerToString(MAGIC1)'],
 ['another version is read','GoatStateValue(keys,values,"version")!=IntegerToString(GOAT_STATE_VERSION) || GoatStateValue','GoatStateValue'],
 ['another login is read',' || GoatStateValue(keys,values,"login")!=IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))\n','\n'],
 ['another magic is read','      || GoatStateValue(keys,values,"magic")!=IntegerToString(MAGIC1) || ','      || '],
 ['another symbol is read',' || GoatStateValue(keys,values,"symbol")!=_Symbol)',')'],
 ['the tester reads the file','   g_GoatDayRestorePending=false;\n   if(!GoatStateLive()) return;\n','   g_GoatDayRestorePending=false;\n'],
 ['the day section is never kept','   g_GoatDayRestorePending=true;\n  }',' }'],
 // The day.
 ['yesterday\'s day state is restored','   if(v[0]!=IntegerToString(g_GoatStateDay)) {','   if(false) {'],
 ['a day without a start equity is restored','   if(!(StringToDouble(v[2])>0.0)) {','   if(false) {'],
 ['an incomplete day section is restored','      if(v[i]=="") {Print("GOAT state: the day section has no ",f[i],"; the day starts fresh"); return;}\n',''],
 ['the stop-out is not restored','   StopOut_Flag=(v[1]=="1"); ','   '],
 ['the daily start equity is not restored','DStartEquity=StringToDouble(v[2]); ',''],
 ['the restart cooldown is not restored','   LastStopoutTime=(datetime)StringToInteger(v[5]); ','   '],
 ['the bias edge is not restored',' g_GoatLastStopOutB=(v[6]=="1");',''],
 ['the day is never stamped','   g_GoatStateDay=(long)tm_cur/86400;\n','\n'],
 // 5. OnInit after adoption, the timer.
 ['an expired build with nothing open keeps running','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_EXPIRED) {','   if(false) {'],
 ['a refused licence with nothing open keeps running','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_LICENCE_REFUSED) {Sleep(20000); return false;}\n',''],
 ['an outage with nothing open stops','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_LICENCE_REFUSED) {','   if(!holding && g_GoatManageOnly!=GOAT_MANAGE_EXPIRED) {'],
 ['the licence is retried on every timer','      if(GetTickCount()-g_GoatLicenceRetriedMs<GOAT_LICENCE_RETRY_MS) return;\n',''],
 ['the retry does not reset its clock','      g_GoatLicenceRetriedMs=GetTickCount();\n      int key=','      int key='],
 ['a valid licence keeps manage-only','if(key==LICENSE_VALID) {g_GoatManageOnly=GOAT_MANAGE_NONE;','if(key==LICENSE_VALID) {'],
 ['a refusal stays an outage','      if(key<0 || key>=500) return;\n      g_GoatManageOnly=GOAT_MANAGE_LICENCE_REFUSED;','      return;\n      g_GoatManageOnly=GOAT_MANAGE_LICENCE_REFUSED;'],
 ['an outage removes the EA','      if(key<0 || key>=500) return;\n','      if(key<0 || key>=500) {}\n'],
 ['the EA is removed with a basket open','   if(Seq_Buy.Active || Seq_Sell.Active) return;\n   removing=true;','   removing=true;'],
 ['the sell side does not hold','   if(Seq_Buy.Active || Seq_Sell.Active) return;\n   removing=true;','   if(Seq_Buy.Active) return;\n   removing=true;'],
 ['a normal chart removes itself when flat','   if(g_GoatManageOnly==GOAT_MANAGE_NONE || removing) return;','   if(removing) return;'],
 ['the removal repeats','   removing=true;\n',''],
 // 6. Where it sits.
 ['an outage still fails init',' || GoatLicenceManageOnly(LicenseKey)) // B49b (F1)',') // B49b (F1)'],
 ['the expired Add_Level adds','{if(GoatExpiryManageOnly()) return false; Alert(','{GoatExpiryManageOnly(); Alert('],
 ['the signal block removes an expired EA','     if(TimeCurrent()>Expiry && !GoatExpiryManageOnly()) {Alert','     if(TimeCurrent()>Expiry) {Alert'],
 ['OnInit ignores the after-adoption check','   if(!GoatManageOnlyAfterAdopt()) return INIT_FAILED;','   GoatManageOnlyAfterAdopt();'],
 ['adoption is not followed by the restore','     GoatStateRestore(); // B49b (F1)','     // B49b (F1)'],
 ['the new day never restores','    if(GoatStateLive()) GoatStateDayRestore(); // B49b (F1)','    // B49b (F1)'],
 ['the timer never writes the file','   GoatStateFlush(); GoatManageOnlyTimer(); // B49b (F1)','   GoatManageOnlyTimer(); // B49b (F1)'],
 ['the timer never retries','   GoatStateFlush(); GoatManageOnlyTimer(); // B49b (F1)','   GoatStateFlush(); // B49b (F1)'],
 ['OnDeinit never writes the file','   GoatStateFlush(true); // B49b (F1): and the state file','   // B49b (F1): and the state file'],
 ['the bias edge is a static again','    if(StopOut_Flag_B && !g_GoatLastStopOutB)','    static bool Last_StopOut_Flag_B = false;\n    if(StopOut_Flag_B && !g_GoatLastStopOutB)'],
 ['adoption publishes blocked exposure','    GuardRealStarted=true; // B49b (F1)','    // B49b (F1)'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f1-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[F1],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
{const r=runOn(MAIN);assert.equal(r.status,0,'the unmutated test_b49b_f1.cjs passes on the scratch entrypoint: '+r.stderr);}
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
