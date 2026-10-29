// Mutation check for B49b PR-2 (F1 full): every manage-only gate, state-file check and hook is load-bearing. Each
// mutant edits GOAT V1.49.mq5 in memory; test_b49b_f1.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must fail.
// Equivalent, not listed: dropping GoatStateDayRestore's "pending=false" (IsNewDay fires once per server day, and a
// later day's section is refused by the day check anyway).
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const ROOT=path.join(__dirname,'..');
const F1=path.join(__dirname,'test_b49b_f1.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const MUTANTS=[
 // 1. Who is manage-only.
 ['manage-only opens new sequences','   if(g_GoatManageOnly!=GOAT_MANAGE_NONE) return false; // B49b (F1): manage-only',''],
 ['the report tool goes manage-only','   return(Mode_Operation==Operation_Standard && Mode!="EXPORT");','   return(Mode_Operation!=Operation_Batch && Mode_Operation!=Operation_Dash);'],
 ['the export run goes manage-only','Mode_Operation==Operation_Standard && Mode!="EXPORT"','Mode_Operation==Operation_Standard'],
 ['the tester goes manage-only','   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return false;\n   return(Mode_Operation==Operation_Standard','   return(Mode_Operation==Operation_Standard'],
 ['401 is not a rejected credential','(key==401 || key==403) ? GOAT_MANAGE_CREDENTIAL : GoatLicenceTransient(key)','(key==403) ? GOAT_MANAGE_CREDENTIAL : GoatLicenceTransient(key)'],
 ['403 is not a rejected credential','(key==401 || key==403) ? GOAT_MANAGE_CREDENTIAL : GoatLicenceTransient(key)','(key==401) ? GOAT_MANAGE_CREDENTIAL : GoatLicenceTransient(key)'],
 ['init ignores the transient set','GOAT_MANAGE_CREDENTIAL : GoatLicenceTransient(key) ? GOAT_MANAGE_LICENCE_DOWN','GOAT_MANAGE_CREDENTIAL : (key<0 || key>=500) ? GOAT_MANAGE_LICENCE_DOWN'],
 ['manage-only opens a sell (Claude-Mac #284 P3)','   if(g_GoatManageOnly!=GOAT_MANAGE_NONE) return false; // B49b (F1): manage-only','   if(op==OP_BUY && g_GoatManageOnly!=GOAT_MANAGE_NONE) return false; // B49b (F1): manage-only'],
 ['a real first level is never frozen (Claude-Mac #284 P3)','    if(!Virtual && ManageOnlyFrozen(Level_Count+1)) return false;','    if(!Virtual && Level_Count>0 && ManageOnlyFrozen(Level_Count+1)) return false;'],
 ['a rejected credential stays out of manage-only','!GoatManageOnlyLive() || key==0 || key==LICENSE_VALID) return false;','!GoatManageOnlyLive() || key==0 || key==LICENSE_VALID || key==401 || key==403) return false;'],
 ['manage-only is carried over a re-init','   g_GoatManageOnly=GOAT_MANAGE_NONE; g_GoatLicenceRetriedMs=0; // B49b (F1): manage-only is re-derived','   // B49b (F1): manage-only is re-derived'],
 ['an unchecked licence goes manage-only','!GoatManageOnlyLive() || key==0 || key==LICENSE_VALID','!GoatManageOnlyLive() || key==LICENSE_VALID'],
 ['a 5xx outage reads as a refusal','   return(key<0 || key>=500 || key==408 || key==429);','   return(key<0 || key==408 || key==429);'],
 ['a network failure reads as a refusal','   return(key<0 || key>=500 || key==408 || key==429);','   return(key>=500 || key==408 || key==429);'],
 ['a 408 reads as a refusal (Claude-Mac #284 P2-2)','   return(key<0 || key>=500 || key==408 || key==429);','   return(key<0 || key>=500 || key==429);'],
 ['a 429 reads as a refusal (Claude-Mac #284 P2-2)','   return(key<0 || key>=500 || key==408 || key==429);','   return(key<0 || key>=500 || key==408);'],
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
 ['a refused licence with nothing open keeps running','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_LICENCE_REFUSED) {Sleep(20000); return INIT_FAILED;}\n',''],
 ['an outage with nothing open stops','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_LICENCE_REFUSED) {','   if(!holding && g_GoatManageOnly!=GOAT_MANAGE_EXPIRED && g_GoatManageOnly!=GOAT_MANAGE_CREDENTIAL) {'],
 ['a rejected credential with nothing open goes manage-only','   if(!holding && g_GoatManageOnly==GOAT_MANAGE_CREDENTIAL)','   if(false)'],
 ['the credential replacement keeps manage-only','      g_GoatManageOnly=GOAT_MANAGE_NONE;\n      Print("Stored GOAT user credential','      Print("Stored GOAT user credential'],
 ['a replacement that cannot begin succeeds','      if(!GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID,true)) return INIT_FAILED;','      GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID,true);'],
 ['a held basket under manage-only is not announced at init','   GoatManageOnlyAnnounce();\n   return -1;','   return -1;'],
 // The announcement.
 ['the announcement repeats','      g_GoatManageOnlyAnnounced=GoatManageOnlyReason();\n','\n'],
 ['no chart prompt','      GoatManageOnlyPrompt();\n      g_GoatManageOnlyStatusMs=0;','      g_GoatManageOnlyStatusMs=0;'],
 ['the prompt is another one','   ShowPrompt("GOAT is managing only",','   ShowPrompt("GOAT",'],
 ['the row is never resent','   if(g_GoatManageOnlyStatusMs!=0 && GetTickCount()-g_GoatManageOnlyStatusMs<60000) return;','   if(g_GoatManageOnlyStatusMs!=0) return;'],
 ['the row is sent on every timer','   if(g_GoatManageOnlyStatusMs!=0 && GetTickCount()-g_GoatManageOnlyStatusMs<60000) return;','   ;'],
 ['no dashboard row','   DashboardBusSendStatus("Managing only");','   ;'],
 ['the end keeps the prompt and the row','{g_GoatManageOnlyAnnounced=""; HidePrompt(); DashboardBusSendStatus("Linked");}','{g_GoatManageOnlyAnnounced="";}'],
 ['the timer never announces','   if(removing) return;\n   GoatManageOnlyAnnounce();','   if(removing) return;'],
 ['a refusal from the service is not announced','      Print("GOAT manage-only: reason=",GoatManageOnlyReason()," licence_status=",IntegerToString(key));\n      GoatManageOnlyAnnounce();','      Print("GOAT manage-only: reason=",GoatManageOnlyReason()," licence_status=",IntegerToString(key));'],
 ['the end is not announced','new trades and adds resume"); GoatManageOnlyAnnounce(); return;}','new trades and adds resume"); return;}'],
 ['a credential answer reads as refused','      g_GoatManageOnly=((key==401 || key==403) ? GOAT_MANAGE_CREDENTIAL : GOAT_MANAGE_LICENCE_REFUSED);','      g_GoatManageOnly=GOAT_MANAGE_LICENCE_REFUSED;'],
 ['the licence is retried on every timer','      if(GetTickCount()-g_GoatLicenceRetriedMs<GOAT_LICENCE_RETRY_MS) return;\n',''],
 ['the retry does not reset its clock','      g_GoatLicenceRetriedMs=GetTickCount();\n      int key=','      int key='],
 ['a valid licence keeps manage-only','if(key==LICENSE_VALID) {g_GoatManageOnly=GOAT_MANAGE_NONE;','if(key==LICENSE_VALID) {'],
 ['a refusal stays an outage','      if(GoatLicenceTransient(key)) {GoatManageOnlyPrompt(); return;}','      {GoatManageOnlyPrompt(); return;}'],
 ['an outage removes the EA','      if(GoatLicenceTransient(key)) {GoatManageOnlyPrompt(); return;}','      if(GoatLicenceTransient(key)) {GoatManageOnlyPrompt();}'],
 ['the retry leaves VerifyLicense\'s prompt (Claude-Mac #284 P3)','      if(GoatLicenceTransient(key)) {GoatManageOnlyPrompt(); return;}','      if(GoatLicenceTransient(key)) {return;}'],
 ['the EA is removed with a basket open','   if(Seq_Buy.Active || Seq_Sell.Active) return;\n   // Claude-Mac #284 P2-1','   // Claude-Mac #284 P2-1'],
 ['the sell side does not hold','   if(Seq_Buy.Active || Seq_Sell.Active) return;\n   // Claude-Mac #284 P2-1','   if(Seq_Buy.Active) return;\n   // Claude-Mac #284 P2-1'],
 ['open positions without a sequence are removed (Claude-Mac #284 P2-1)','   if(open_positions>0)\n','   if(false)\n'],
 ['one leftover position is removed (Claude-Mac #284 APPROVE item 2)','   if(open_positions>0)\n','   if(open_positions>1)\n'],
 ['only buys count as open','int open_positions=FindNumberOfPositions(OP_BUYSELL,MAGIC1);','int open_positions=FindNumberOfPositions(OP_BUY,MAGIC1);'],
 ['any magic counts as open','int open_positions=FindNumberOfPositions(OP_BUYSELL,MAGIC1);','int open_positions=FindNumberOfPositions(OP_BUYSELL);'],
 ['"not removed" is said every timer','      g_GoatManageOnlyHeldLogged=true;\n',''],
 // The state writer (Claude-Mac #284 P1).
 ['the state file goes through B49a\'s TXT writer','   if(GoatStateWrite(GoatStatePath(),text))','   if(GoatSetupWrite(GoatStatePath(),text))'],
 ['the state writer opens FILE_TXT','FileOpen(temporary,FILE_WRITE|FILE_BIN|FILE_COMMON)','FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON)'],
 ['the byte count is the character count','   int size=StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8)-1;','   int size=StringLen(body); StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8);'],
 ['the terminating 0 is written','   int size=StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8)-1;','   int size=StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8);'],
 ['a short write passes','   bool okay=(written==(uint)size && GetLastError()==0);','   bool okay=true;'],
 ['a full-size write with an error passes (Claude-Mac #284 APPROVE item 3)','   bool okay=(written==(uint)size && GetLastError()==0);','   bool okay=(written==(uint)size);'],
 ['the move never replaces the file (Claude-Mac #284 APPROVE item 1)','FileMove(temporary,FILE_COMMON,path,FILE_COMMON|FILE_REWRITE)','FileMove(temporary,FILE_COMMON,path,FILE_COMMON)'],
 ['a failed write keeps its .pending','   FileDelete(temporary,FILE_COMMON);\n   return false;','   return false;'],
 ['the move error is lost','   if(okay) g_GoatStateWriteError=GetLastError();\n',''],
 ['the open error is lost','   if(h==INVALID_HANDLE) {g_GoatStateWriteError=GetLastError(); return false;}','   if(h==INVALID_HANDLE) return false;'],
 ['another writer\'s .pending is truncated','   if(FileIsExist(temporary,FILE_COMMON)) {g_GoatStateWriteError=-1; return false;}',''],
 ['empty text is written','   if(size<=0) {g_GoatStateWriteError=-2; return false;}',''],
 ['the folder levels are not created','FolderCreate("GOAT",FILE_COMMON); FolderCreate("GOAT\\\\State",FILE_COMMON); FolderCreate("GOAT\\\\State\\\\"+login','FolderCreate("GOAT\\\\State\\\\"+login'],
 // The dashboard row through acks and heartbeats (Claude-Mac #284 P3).
 ['a manage-only row shows the heartbeat\'s status','   if(g_GoatManageOnly!=GOAT_MANAGE_NONE && status!="Offline"','   if(false && status!="Offline"'],
 ['a manage-only row hides Offline',' && status!="Offline" && status!="Close Failed") {',' && status!="Close Failed") {'],
 ['a manage-only row hides Close Failed',' && status!="Offline" && status!="Close Failed") {',' && status!="Offline") {'],
 ['a normal chart removes itself when flat','   if(g_GoatManageOnly==GOAT_MANAGE_NONE) return;\n   if(g_GoatManageOnly==GOAT_MANAGE_LICENCE_DOWN)','   if(g_GoatManageOnly==GOAT_MANAGE_LICENCE_DOWN)'],
 ['the removal repeats','   removing=true;\n',''],
 // 6. Where it sits.
 ['an outage still fails init',' || GoatLicenceManageOnly(LicenseKey)) // B49b (F1)',') // B49b (F1)'],
 ['the expired Add_Level adds','{if(GoatExpiryManageOnly()) return false; Alert(','{GoatExpiryManageOnly(); Alert('],
 ['the signal block removes an expired EA','     if(TimeCurrent()>Expiry && !GoatExpiryManageOnly()) {Alert','     if(TimeCurrent()>Expiry) {Alert'],
 ['OnInit ignores a failed manage-only init','   if(manage_only_init==INIT_FAILED) return INIT_FAILED;','   ;'],
 ['OnInit ignores the credential replacement','   if(manage_only_init==INIT_SUCCEEDED) return INIT_SUCCEEDED;','   ;'],
 ['adoption is not followed by the restore','     GoatStateRestore(); // B49b (F1)','     // B49b (F1)'],
 ['the new day never restores','    if(GoatStateLive()) GoatStateDayRestore(); // B49b (F1)','    // B49b (F1)'],
 ['the timer never writes the file','   GoatStateFlush(); GoatManageOnlyTimer(); // B49b (F1)','   GoatManageOnlyTimer(); // B49b (F1)'],
 ['the timer never retries','   GoatStateFlush(); GoatManageOnlyTimer(); // B49b (F1)','   GoatStateFlush(); // B49b (F1)'],
 ['OnDeinit never writes the file','   GoatStateFlush(true); // B49b (F1): and the state file','   // B49b (F1): and the state file'],
 ['the bias edge is a static again','    if(StopOut_Flag_B && !g_GoatLastStopOutB)','    static bool Last_StopOut_Flag_B = false;\n    if(StopOut_Flag_B && !g_GoatLastStopOutB)'],
 ['adoption publishes blocked exposure','    GuardRealStarted=true; // B49b (F1)','    // B49b (F1)'],
 // The dashboard (Dashboard.mqh).
 ['the dashboard hides a managing-only row','      if(g_sets[idx].manage_only && row_status!="No Ack"','      if(false && row_status!="No Ack"','dash'],
 // Claude-Mac #284 APPROVE item 5: the row's flag, not its status (which the dashboard's own command writes replace).
 ['the row shows its status, not the flag (the #284 round 2 code)','      if(g_sets[idx].manage_only && row_status!="No Ack" && row_status!="Command Failed" && row_status!="Close Failed" && row_status!="Closed") return "Managing only";',
  '      if(row_status=="Managing only") return "Managing only";','dash'],
 ['a command\'s outcome is hidden','      if(g_sets[idx].manage_only && row_status!="No Ack" && row_status!="Command Failed" && row_status!="Close Failed" && row_status!="Closed") return "Managing only";',
  '      if(g_sets[idx].manage_only) return "Managing only";','dash'],
 ['a failed close ends manage-only','            else if(status!="Close Failed") g_sets[idx].manage_only=false;','            else g_sets[idx].manage_only=false;','dash'],
 ['the child never ends manage-only','            else if(status!="Close Failed") g_sets[idx].manage_only=false;   // B49b (F1)\n','','dash'],
 ['the child never starts manage-only','            if(status=="Managing only") g_sets[idx].manage_only=true;','            if(false) g_sets[idx].manage_only=true;','dash'],
 ['an adopted chart keeps the old row\'s flag','   g_sets[adopt_idx].manage_only=false;','   ;','dash'],
 ['a new row starts manage-only','        manage_only=false;   // B49b (F1)\n','        manage_only=true;   // B49b (F1)\n','dash'],
 ['a managing-only row counts as active','      if(row_status=="Active" || row_status=="Linked") active_count++;','      if(row_status=="Active" || row_status=="Linked" || row_status=="Managing only") active_count++;','dash'],
];
const DASH=fs.readFileSync(path.join(ROOT,'Dashboard.mqh'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
// B49b tidy (#285 CI): the mutants run in parallel, one test process per core, so the step fits the controller job's 45 min
// on a 4-core runner (serially, 127 mutants ran past it). Each mutant still gets its own scratch copy and its own process;
// a mutant is killed when its run fails, times out (status null, as spawnSync reported) or crashes.
function runOn(mainText,dashText=DASH){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f1-'));
 const file=path.join(dir,'GOAT V1.49.mq5'),dashFile=path.join(dir,'Dashboard.mqh');
 fs.writeFileSync(file,'\uFEFF'+mainText.replace(/\n/g,'\r\n'),'utf8');fs.writeFileSync(dashFile,dashText.replace(/\n/g,'\r\n'),'utf8');
 return new Promise(resolve=>{
  const child=spawn(process.execPath,[F1],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file,GOAT_EA_DASH:dashFile},stdio:['ignore','ignore','pipe']});
  let stderr='';child.stderr.setEncoding('utf8');child.stderr.on('data',d=>{stderr+=d;});
  const timer=setTimeout(()=>child.kill(),120000);
  const done=status=>{clearTimeout(timer);fs.rmSync(dir,{recursive:true,force:true});resolve({status,stderr});};
  child.on('error',()=>done(null));child.on('close',code=>done(code));
 });
}
(async()=>{
 {const r=await runOn(MAIN);assert.equal(r.status,0,'the unmutated test_b49b_f1.cjs passes on the scratch entrypoint: '+r.stderr);}
 // Every anchor is checked before any mutant runs.
 const jobs=MUTANTS.map(([label,from,to,target])=>{
  const text=target==='dash'?DASH:MAIN;
  const n=text.split(from).length-1;
  assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${target==='dash'?'Dashboard.mqh':'GOAT V1.49.mq5'} (found ${n})`);
  return target==='dash'?{label,main:MAIN,dash:text.replace(from,()=>to)}:{label,main:text.replace(from,()=>to),dash:DASH};
 });
 const width=Math.max(1,Math.min(jobs.length,typeof os.availableParallelism==='function'?os.availableParallelism():os.cpus().length));
 const results=new Array(jobs.length);let next=0;
 await Promise.all(Array.from({length:width},async()=>{while(next<jobs.length){const i=next++;results[i]=await runOn(jobs[i].main,jobs[i].dash);}}));
 let killed=0;
 jobs.forEach((job,i)=>{assert.notEqual(results[i].status,0,`mutant survived: ${job.label}`);killed++;});
 console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
})().catch(error=>{console.error(error);process.exitCode=1;});