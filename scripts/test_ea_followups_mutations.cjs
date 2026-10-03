// Mutation check for scripts/test_ea_followups.cjs: every FU35 guard below is removed or
// weakened in a temporary copy of the production sources and the harness must fail.
// MQL-free; the repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['GOATEvidenceEnd.mqh','GOATTesterStopConfirm.mqh','GOAT V1.49.mq5','GOAT V1.47.mq5','GOAT V1.48.mq5','GOATStudioDispatch.mqh','GOATStudioUI.mqh','Optimizer.mqh'];
const R=String.raw;
const E='GOATEvidenceEnd.mqh',S='GOATTesterStopConfirm.mqh',M='GOAT V1.49.mq5',D='GOATStudioDispatch.mqh',U='GOATStudioUI.mqh',O='Optimizer.mqh';
// [label, file, from, to]
const mutations=[
  ['Friday counted as a closed week',E,R`return back==0 ? 7 : back;`,R`return back;`],
  ['weekday off by one',E,R`int back=(day_of_week+2)%7;`,R`int back=(day_of_week+1)%7;`],
  ['epoch weekday wrong',E,R`(((long)today/GOAT_EVIDENCE_DAY_SECONDS+4)%7)`,R`(((long)today/GOAT_EVIDENCE_DAY_SECONDS+3)%7)`],
  ['ToDate not exclusive (last evidence day dropped)',E,R`return TimeToString(end+GOAT_EVIDENCE_DAY_SECONDS,TIME_DATE);`,R`return TimeToString(end,TIME_DATE);`],
  ['ToDate two days out',E,R`return TimeToString(end+GOAT_EVIDENCE_DAY_SECONDS,TIME_DATE);`,R`return TimeToString(end+2*GOAT_EVIDENCE_DAY_SECONDS,TIME_DATE);`],
  ['open broker day accepted',E,R`if(end>=today)`,R`if(end>today)`],
  ['future day accepted',E,R`if(end>=today) {error=`,R`if(false) {error=`],
  ['window end not enforced',E,R`if(window_end>0 && end<GoatEvidenceDay(window_end))`,R`if(false)`],
  ['window end day refused',E,R`end<GoatEvidenceDay(window_end)`,R`end<=GoatEvidenceDay(window_end)`],
  ['window end compared to the minute',E,R`end<GoatEvidenceDay(window_end)`,R`end<window_end`],
  ['AUTO skips the window rule',E,R`   if(window_end>0 && end<GoatEvidenceDay(window_end))
     {`,R`   if(value!="AUTO" && window_end>0 && end<GoatEvidenceDay(window_end))
     {`],
  ['impossible date accepted',E,R`return day>0 && TimeToString(day,TIME_DATE)==text;`,R`return day>0;`],
  ['zero time accepted',E,R`return day>0 && TimeToString`,R`return TimeToString`],
  ['value not trimmed',E,R`   StringTrimLeft(value);
`,''],
  ['lower-case auto refused',E,R`value=="AUTO" || value=="auto" || value=="Auto"`,R`value=="AUTO"`],
  ['missing server clock accepted',E,R`if(server_now<=0) {error="EvidenceEnd: broker server time is unavailable";return "";}`,''],
  ['refusal keeps a partial end',E,R`   evidence_end=TimeToString(end,TIME_DATE);
   return`,R`   return`],
  ['capability renamed',E,R`"goat-evidence-end-v1"`,R`"goat-evidence-end"`],
  ['single idle read confirms',S,R`#define GOAT_STOP_CONFIRM_STABLE  3`,R`#define GOAT_STOP_CONFIRM_STABLE  1`],
  ['wait unbounded beyond 10 s',S,R`#define GOAT_STOP_CONFIRM_POLLS   40`,R`#define GOAT_STOP_CONFIRM_POLLS   400`],
  ['wait cut to the old single read',S,R`#define GOAT_STOP_CONFIRM_POLLS   40`,R`#define GOAT_STOP_CONFIRM_POLLS   1`],
  ['poll interval changed',S,R`#define GOAT_STOP_CONFIRM_POLL_MS 250`,R`#define GOAT_STOP_CONFIRM_POLL_MS 100`],
  ['unknown caption counts as idle',S,R`if(state=="idle")`,R`if(state!="running")`],
  ['Stop toggled on a non-running read',S,R`if(state=="running" && armed`,R`if(armed`],
  ['Stop toggled on every running read',S,R`            armed=false;
`,''],
  ['new run after idle not stopped',S,R`         stable++;
         armed=true;`,R`         stable++;`],
  ['click count unbounded',S,R` && g_GoatStopConfirmClicks<GOAT_STOP_CONFIRM_CLICKS`,''],
  ['idle reads not consecutive',S,R`         stable=0;
         if(state=="running"`,R`         if(state=="running"`],
  ['keeps polling after confirmation',S,R`      if(stable>=GOAT_STOP_CONFIRM_STABLE) break;
`,''],
  ['elapsed time not measured',S,R`g_GoatStopConfirmElapsedMs=GetTickCount64()-started;`,R`g_GoatStopConfirmElapsedMs=0;`],
  ['click diagnostics not reset',S,R`   g_GoatStopConfirmClicks=0;
   for`,R`   for`],
  ['result ignores the stable count',S,R`   return stable>=GOAT_STOP_CONFIRM_STABLE;`,R`   return true;`],
  // B38 click guard (Claude-Mac fold-in 1 on #122).
  ['guard back to ClickStop (IsIdle fallback can send Start)',S,R`            && GoatTesterSendStopIfRunning())`,R`            && MTTESTER::ClickStop(1))`],
  ['toggle sent without the fresh running re-read',S,R`   if(GoatStudioTesterState()!="running") return false;
`,''],
  ['toggle sent on a blank caption',S,R`if(GoatStudioTesterState()!="running") return false;`,R`if(GoatStudioTesterState()=="idle") return false;`],
  ['disarmed although nothing was sent',S,R`            && GoatTesterSendStopIfRunning())`,R`            && (GoatTesterSendStopIfRunning() || true))`],
  ['toggle not sent to the tester pane',S,R`   if(handle!=0) handle=user32::GetDlgItem(handle,0x804E);
`,''],
  ['pane path ignores the terminal build',S,R`TerminalInfoInteger(TERMINAL_BUILD)<=5000`,R`TerminalInfoInteger(TERMINAL_BUILD)>5000`],
  ['wrong toggle message',S,R`user32::SendMessageW(handle,message,0x31,0);`,R`user32::SendMessageW(handle,message,0x32,0);`],
  ['send reported although no pane',S,R`   if(handle==0) return false;
`,''],
  // B38 EvidenceEnd writer and finish check (Claude-Mac fold-in 2 on #122).
  ['Studio save drops EvidenceEnd',O,R`   exportSettings=GoatEvidenceEndCarry(exportSettings,GetFileContent(Path_ExportSettings));
`,''],
  ['rename drops EvidenceEnd',O,R`   exportSettings=GoatEvidenceEndCarry(exportSettings,GetFileContent(oldExportSettingsPath));
`,''],
  ['rename carries from the new folder',O,R`GoatEvidenceEndCarry(exportSettings,GetFileContent(oldExportSettingsPath))`,R`GoatEvidenceEndCarry(exportSettings,GetFileContent(Path_ExportSettings))`],
  ['carry overrides a value already written',E,R`if(rewritten=="" || GoatEvidenceSettingValue(rewritten)!="") return rewritten;`,R`if(rewritten=="") return rewritten;`],
  ['carry turns an empty rewrite into a header-less file',E,R`if(rewritten=="" || GoatEvidenceSettingValue`,R`if(GoatEvidenceSettingValue`],
  ['setting key matched mid-line',E,R`string key="\nEvidenceEnd=";`,R`string key="EvidenceEnd=";`],
  ['setting value not trimmed',E,R`   StringTrimLeft(found);
`,''],
  ['carry doubles the newline',E,R`=="\n" ? "" : "\n");`,R`=="\n" ? "\n" : "\n");`],
  ['export end read from the range start',E,R`string end=StringSubstr(set_text,dash+1,10);`,R`string end=StringSubstr(set_text,dash-10,10);`],
  ['SAMPLE fallback lost',E,R`: GoatEvidenceHeaderEnd(set_text,"; SAMPLE:"));`,R`: "");`],
  ['malformed export end accepted',E,R`   if(!GoatEvidenceParseDay(end,day)) return "";
`,''],
  ['absent EvidenceEnd is silent',M,R`     Print("GOAT_EVIDENCE_END_ABSENT build_id="+GOAT_BUILD_ID+" legacy_to_date="+GetLastFridayDate());
`,''],
  ['kept exports not checked at finish',M,R`      GoatEvidenceEndCheckExports(g_allExports,evidenceEnd,reportMode);
`,''],
  ['adjusted exports not checked at finish',M,R`       GoatEvidenceEndCheckExports(AdjustedExports,evidenceEnd,reportMode);
`,''],
  ['a mismatched end counts as matched',M,R`if(end==evidenceEnd) {matched++; continue;}`,R`{matched++; continue;}`],
  ['a later end counts as earlier',M,R`if(StringToTime(end)>staged) later++; else earlier++;`,R`if(StringToTime(end)<staged) later++; else earlier++;`],
  ['check journal line missing',M,R`   Print("GOAT_EVIDENCE_END_CHECK build_id="`,R`   ("GOAT_EVIDENCE_END_CHECK build_id="`],  ['cancel back to one 100 ms read',D,R`   bool stopped=GoatTesterStopConfirmed();`,R`   bool stopped=MTTESTER::ClickStop(1);`],
  ['receipt ignores the stop',D,R`return (stopped && saved && cleared) ? "CANCELLED_RECONCILE"`,R`return (saved && cleared) ? "CANCELLED_RECONCILE"`],
  ['timing not journaled',D,R`         +" elapsed_ms="+(string)g_GoatStopConfirmElapsedMs);`,R`         );`],
  ['stop confirm header not included',D,R`#include "GOATTesterStopConfirm.mqh"`,''],
  ['stop confirm not enabled',M,R`#define GOAT_STOP_CONFIRM_V149
`,''],
  ['evidence end not enabled',M,R`#define GOAT_EVIDENCE_END_V149
`,''],
  ['refused EvidenceEnd falls back',M,R`No exports were run.",Key,EA_Name,Server); return false;}`,R`No exports were run.",Key,EA_Name,Server);}`],
  ['last-tick clock instead of server clock',M,R`GoatEvidenceEndToDate(evidenceSetting,TimeTradeServer(),`,R`GoatEvidenceEndToDate(evidenceSetting,TimeCurrent(),`],
  ['window end not passed',M,R`TimeTradeServer(),xmlData.endD,`,R`TimeTradeServer(),0,`],
  ['exports ignore EvidenceEnd',M,R`strT.toDate=(evidenceToDate!="" ? evidenceToDate : GetLastFridayDate());`,R`strT.toDate=GetLastFridayDate();`],
  ['legacy end lost when setting absent',M,R`strT.toDate=(evidenceToDate!="" ? evidenceToDate : GetLastFridayDate());`,R`strT.toDate=evidenceToDate;`],
  ['capability not advertised',U,R`   body+=",\"evidence_end\":"+GoatStudioQuote(GOAT_EVIDENCE_END_CAPABILITY);
`,''],
];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-fu35-mutation-'));
const harness=path.join(__dirname,'test_ea_followups.cjs');
function run(dir){return spawnSync(process.execPath,[harness],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:60000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  const clean=run(base);if(clean.status!==0)throw new Error('unmutated sources fail:\n'+clean.stdout+clean.stderr);
  mutations.forEach(([label,file,rawFrom,rawTo],n)=>{
    // Sources are CRLF; template literals are LF. Match and write CRLF either way.
    const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file),text=fs.readFileSync(target,'utf8');
    if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
    fs.writeFileSync(target,text.replace(from,()=>to));
    if(run(dir).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
