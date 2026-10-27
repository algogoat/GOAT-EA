// EA follow-ups FU35. Runs the production MQL of GOATTesterStopConfirm.mqh (bounded idle
// confirmation before CANCELLED_RECONCILE) and GOATEvidenceEnd.mqh (EvidenceEnd export
// boundary) in a JS VM against a simulated tester caption and broker clock, then checks
// their V1.49 call sites. MQL-free: no MetaEditor, MT5 or network. GOAT_EA_ROOT may point
// at another source tree (test_ea_followups_mutations.cjs runs every mutation here).
// `--mirror` reads {window_end, cases:[{setting, server}]} on stdin and prints the EA's
// answers, for controller/test_studio_evidence_end_export.py to compare with Python.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');

function stripComments(text){
  let out='',i=0,quote='';
  while(i<text.length){
    const c=text[i];
    if(quote){out+=c;if(c==='\\'){out+=text[i+1];i+=2;continue;}if(c===quote)quote='';i++;continue;}
    if(c==='"'||c==="'"){quote=c;out+=c;i++;continue;}
    if(c==='/'&&text[i+1]==='/'){while(i<text.length&&text[i]!=='\n')i++;continue;}
    if(c==='/'&&text[i+1]==='*'){const end=text.indexOf('*/',i+2);i=end<0?text.length:end+2;continue;}
    out+=c;i++;
  }
  return out;
}
function splitArgs(text){
  const out=[];let depth=0,quote='',start=0;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(quote){if(c==='\\')i++;else if(c===quote)quote='';continue;}
    if(c==='"'||c==="'")quote=c;
    else if(c==='('||c==='[')depth++;
    else if(c===')'||c===']')depth--;
    else if(c===','&&depth===0){out.push(text.slice(start,i));start=i+1;}
  }
  out.push(text.slice(start));
  return out;
}
const TYPES='string|bool|int|uint|long|ulong|ushort|datetime|double|void';
// MQL -> JS for these two self-contained headers. By-reference parameters become
// {v} boxes; their call sites pass a getter/setter over the caller's variable.
function convert(source){
  const macros={};const lines=[];
  for(const line of stripComments(source).split('\n')){
    const d=line.match(/^\s*#define\s+(\w+)\s+(.+?)\s*$/);
    if(d){macros[d[1]]=d[2];continue;}
    if(/^\s*#/.test(line))continue;
    lines.push(line);
  }
  let text=lines.join('\n');
  for(const [name,value] of Object.entries(macros))text=text.replace(new RegExp('\\b'+name+'\\b','g'),value);
  text=text.replace(/'(\\.|[^'\\])'/g,(_,ch)=>String(ch.charCodeAt(0)));
  text=text.replace(/\((?:string|int|long|ulong|ushort|datetime|double)\)/g,'');
  text=text.replace(/MTTESTER::/g,'MTTESTER.').replace(/user32::/g,'user32.');
  const refs={};
  text=text.replace(new RegExp('^(?:'+TYPES+')\\s+(\\w+)\\(([^)]*)\\)','gm'),(_,name,params)=>{
    const names=[];const boxed=[];
    params.split(',').map(p=>p.trim()).filter(p=>p&&p!=='void').forEach((p,index)=>{
      const m=p.match(/(&?)\s*(\w+)$/);names.push(m[2]);if(m[1]||/&/.test(p))boxed.push([index,m[2]]);
    });
    if(boxed.length)refs[name]=boxed;
    return 'function '+name+'('+names.join(',')+')';
  });
  for(const [name,boxed] of Object.entries(refs)){
    // Inside the function, a reference parameter is its box's value.
    const at=text.indexOf('function '+name+'(');const open=text.indexOf('{',at);
    let depth=0,end=open;
    for(;end<text.length;end++){if(text[end]==='{')depth++;else if(text[end]==='}'&&--depth===0)break;}
    let body=text.slice(open,end+1);
    for(const [,param] of boxed)body=body.replace(new RegExp('\\b'+param+'\\b','g'),param+'.v');
    text=text.slice(0,open)+body+text.slice(end+1);
  }
  for(const [name,boxed] of Object.entries(refs)){
    text=text.replace(new RegExp('\\b'+name+'\\(([^()]*(?:\\([^()]*\\)[^()]*)*)\\)','g'),(call,args,offset,whole)=>{
      if(whole.slice(Math.max(0,offset-9),offset)==='function ')return call; // the definition itself
      const parts=splitArgs(args);
      for(const [index] of boxed){
        const id=parts[index].trim();
        if(!/^[A-Za-z_]\w*(\.v)?$/.test(id))return call;
        parts[index]='{get v(){return '+id+'},set v(x){'+id+'=x}}';
      }
      return name+'('+parts.join(',')+')';
    });
  }
  // Declarations: globals become var, locals let; MQL default-initializes strings to "".
  text=text.replace(new RegExp('(^|[;{(]|\\n)(\\s*)(?:const\\s+)?(?:'+TYPES+')\\s+(?=[A-Za-z_])','g'),'$1$2let ');
  text=text.replace(/^let /gm,'var ');
  text=text.replace(/let (\w+);/g,'let $1="";');
  text=text.replace(/StringTrimLeft\((\w+)\);/g,'$1=$1.replace(/^\\s+/,"");').replace(/StringTrimRight\((\w+)\);/g,'$1=$1.replace(/\\s+$/,"");');
  // Function declarations were renamed before the declaration pass; restore them.
  text=text.replace(/(?:let|var) function /g,'function ');
  return text;
}

// ---- Shims: broker server wall time is seconds since 1970 read as UTC.
const DAY=86400;
function mqlDate(t){const d=new Date(t*1000);return d.getUTCFullYear()+'.'+String(d.getUTCMonth()+1).padStart(2,'0')+'.'+String(d.getUTCDate()).padStart(2,'0');}
function stringToTime(text){
  const m=String(text).match(/^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$/);
  if(!m)return 0;
  return Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0))/1000;
}
// Simulated tester. Each poll takes one entry from `states`: a caption, or
// [first read, re-read] when the caption changes between the poll's read and the
// click guard's fresh re-read. Start and Stop are ONE MT5 message (0x31 to the
// tester pane), so a toggle sent while the tester is not really running is a
// Start: `starts` must stay 0 in every case. A blank ("unknown") caption hides
// an idle tester unless `unknownTruth` says otherwise.
const PANE=2000,ROOT=1000,TOGGLE_MESSAGE=0xC0DE;
const tester={states:[],clicks:0,starts:0,afterClick:null,polls:0,slept:0,clock:0,lastPoll:-1,current:null,reads:0,caption:'idle',unknownTruth:'idle',build:5100};
const context={
  TIME_DATE:1,TERMINAL_BUILD:5,
  StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.substr(a):s.substr(a,n),
  StringGetCharacter:(s,i)=>s.charCodeAt(i),StringToTime:stringToTime,
  StringFind:(s,v,from=0)=>s.indexOf(v,from),
  TimeToString:(t,mode)=>{assert.equal(mode,1);return mqlDate(t);},
  GetTickCount64:()=>tester.clock,
  Sleep:ms=>{tester.slept++;tester.clock+=ms;},
  TerminalInfoInteger:key=>{assert.equal(key,5);return tester.build;},
  GoatStudioTesterState:()=>{
    const poll=context.g_GoatStopConfirmPolls;
    if(poll!==tester.lastPoll){tester.lastPoll=poll;tester.reads=0;tester.current=tester.states.length?tester.states.shift():tester.rest;}
    const entry=tester.current;
    const s=Array.isArray(entry)?entry[Math.min(tester.reads,entry.length-1)]:entry;
    tester.reads++;tester.polls++;tester.caption=s;return s;
  },
  MTTESTER:{
    GetTerminalHandle:()=>ROOT,
    ClickStop:()=>{throw new Error('ClickStop re-enters IsIdle(), whose fallback can send Start; the guard must not call it');},
  },
  user32:{
    // Build 5000+ terminals have no 0xE81E frame between the root and the tester pane.
    GetDlgItem:(handle,id)=>tester.noPane?0:tester.build>5000
      ? (handle===ROOT&&id===0x804E?PANE:0)
      : (handle===ROOT&&id===0xE81E?1500:handle===1500&&id===0x804E?PANE:0),
    RegisterWindowMessageW:name=>name==='MetaTrader5_Internal_Message'?TOGGLE_MESSAGE:0,
    SendMessageW:(handle,message,wparam,lparam)=>{
      assert.deepEqual([handle,message,wparam,lparam],[PANE,TOGGLE_MESSAGE,0x31,0],'the shared Start/Stop toggle goes to the tester pane');
      const truth=tester.caption==='unknown'?tester.unknownTruth:tester.caption;
      if(truth!=='running')tester.starts++;
      tester.clicks++;if(tester.afterClick)tester.afterClick(tester.clicks);
      return 0;
    },
  },
};
vm.createContext(context);
vm.runInContext(convert(read('GOATEvidenceEnd.mqh')),context);
vm.runInContext(convert(read('GOATTesterStopConfirm.mqh')),context);

function evidence(setting,server,windowEnd=0){
  const box={evidence:'',error:''};
  const to=context.GoatEvidenceEndToDate(setting,typeof server==='string'?stringToTime(server):server,
    typeof windowEnd==='string'?stringToTime(windowEnd):windowEnd,
    {get v(){return box.evidence},set v(x){box.evidence=x}},{get v(){return box.error},set v(x){box.error=x}});
  return {to_date:to,evidence_end:box.evidence,error:box.error};
}

if(process.argv.includes('--mirror')){
  const request=JSON.parse(fs.readFileSync(0,'utf8'));
  process.stdout.write(JSON.stringify(request.cases.map(c=>evidence(c.setting,c.server,request.window_end))));
  process.exit(0);
}

let checks=0;
// ---- EvidenceEnd: AUTO = the last fully closed Friday on the server clock.
for(const [server,end] of [
  ['2026.10.02 18:00','2026.09.25'],['2026.10.02 23:59','2026.09.25'],['2026.10.03 00:00','2026.10.02'],
  ['2026.10.04 12:00','2026.10.02'],['2026.10.05 09:00','2026.10.02'],['2026.10.08 23:00','2026.10.02'],
  ['2026.10.09 00:00','2026.10.02'],['2026.10.10 00:00','2026.10.09'],['2026.12.31 10:00','2026.12.25'],
  ['2027.01.01 10:00','2026.12.25'],['2027.01.02 10:00','2027.01.01']]){
  for(const setting of ['AUTO','auto','Auto',' AUTO ']){
    const r=evidence(setting,server,'2026.06.01');
    assert.equal(r.evidence_end,end,setting+' at '+server);
    assert.equal(r.to_date,mqlDate(stringToTime(end)+DAY),'exclusive ToDate is the next day');
    assert.equal(r.error,'');checks++;
  }
}
for(let dow=0;dow<7;dow++)assert.equal(context.GoatEvidenceFridayDaysBack(dow),[2,3,4,5,6,7,1][dow]),checks++;
// Explicit dates: closed server days only, MT5 YYYY.MM.DD only, never before the window end.
const now='2026.10.03 09:00';
for(const [value,end] of [['2026.10.02','2026.10.02'],['2026.09.30','2026.09.30'],[' 2026.09.25 ','2026.09.25'],['2026.06.01','2026.06.01']]){
  const r=evidence(value,now,'2026.06.01');
  assert.deepEqual([r.evidence_end,r.to_date,r.error],[end,mqlDate(stringToTime(end)+DAY),'']);checks++;
}
for(const [value,reason] of [['2026.10.03','not a closed broker day'],['2026.10.04','not a closed broker day'],['2099.01.01','not a closed broker day'],
  ['2026.05.31','before the optimization window end'],['2026-10-02','must be AUTO or a date'],['2026.9.25','must be AUTO or a date'],
  ['2026.02.30','must be AUTO or a date'],['26.09.25','must be AUTO or a date'],['next friday','must be AUTO or a date'],
  ['2026.1O.02','must be AUTO or a date'],['AUTOMATIC','must be AUTO or a date']]){
  const r=evidence(value,now,'2026.06.01');
  assert.equal(r.to_date,'',value);assert.equal(r.evidence_end,'',value);assert.match(r.error,new RegExp(reason),value);checks++;
}
// AUTO is held to the same window rule; the window end day itself is allowed; no clock refuses.
assert.match(evidence('AUTO',now,'2026.10.03 00:00').error,/before the optimization window end/);checks++;
assert.equal(evidence('AUTO',now,'2026.10.02 00:00').evidence_end,'2026.10.02');checks++;
assert.equal(evidence('AUTO',now,'2026.10.02 15:00').evidence_end,'2026.10.02');checks++;
assert.equal(evidence('2026.10.02',now,0).evidence_end,'2026.10.02');checks++;
// StringToTime's failure value (time 0) is never an evidence end, even without a window.
assert.match(evidence('1970.01.01',now,0).error,/must be AUTO or a date/);checks++;
for(const value of ['2026.10.02 00:00','2026.10.2','2026/10/02'])assert.match(evidence(value,now,0).error,/must be AUTO or a date/,value),checks++;
assert.match(evidence('AUTO',0,'2026.06.01').error,/server time is unavailable/);checks++;
assert.equal(evidence('AUTO',0,'2026.06.01').to_date,'');checks++;

// ---- Stop confirmation against a simulated tester caption.
function stop(states,{rest='running',afterClick=null,unknownTruth='idle',build=5100,noPane=false}={}){
  Object.assign(tester,{states:[...states],rest,clicks:0,starts:0,afterClick,polls:0,slept:0,clock:0,lastPoll:-1,current:null,reads:0,caption:'idle',unknownTruth,build,noPane});
  const ok=context.GoatTesterStopConfirmed();
  // Whatever the captions did, the guard never sent the toggle to a tester that was not running.
  assert.equal(tester.starts,0,'a Stop toggle reached a tester that was not running (that is a Start)');
  assert.equal(context.g_GoatStopConfirmClicks,tester.clicks,'reported clicks are the toggles actually sent');
  return {ok,clicks:tester.clicks,polls:context.g_GoatStopConfirmPolls,reported:context.g_GoatStopConfirmClicks,slept:tester.slept,elapsed:context.g_GoatStopConfirmElapsedMs,read:tester.polls};
}
// Already idle: three reads, no click (Start and Stop share one toggle), no trailing sleep.
let r=stop([],{rest:'idle'});
assert.deepEqual([r.ok,r.clicks,r.polls,r.slept,r.elapsed],[true,0,3,2,500]);checks++;
// Running, MT5 takes 1.5 s to shut down after the click: one click, confirmed after it settles.
r=stop(['running','running','running','running','running','running'],{rest:'idle'});
assert.deepEqual([r.ok,r.clicks,r.reported,r.polls],[true,1,1,9]);checks++;
// The old single 100 ms read would have said "not stopped" here; the bounded check waits.
r=stop(Array(30).fill('running'),{rest:'idle'});
assert.deepEqual([r.ok,r.clicks,r.polls],[true,1,33]);checks++;
// Never stops: bounded at 40 polls / 10 s, one click, honest false.
r=stop([],{rest:'running'});
assert.deepEqual([r.ok,r.clicks,r.polls,r.slept,r.elapsed],[false,1,40,40,10000]);checks++;
// A blank or transient caption never counts as idle and never triggers a click.
r=stop([],{rest:'unknown'});
assert.deepEqual([r.ok,r.clicks,r.polls],[false,0,40]);checks++;
r=stop(['idle','idle','unknown','idle','idle','unknown','idle','idle','idle'],{rest:'running'});
assert.deepEqual([r.ok,r.clicks,r.polls],[true,0,9]);checks++;
// Idle reads must be consecutive: two idle reads then a run is not a confirmation.
r=stop(['idle','idle','running','running','idle','idle','idle'],{rest:'running'});
assert.deepEqual([r.ok,r.clicks,r.polls],[true,1,7]);checks++;
// An export run that started after an idle read (raced the cancel latch) is stopped again.
r=stop(['running','idle','running','running','idle','idle','idle'],{rest:'running'});
assert.deepEqual([r.ok,r.clicks,r.polls],[true,2,7]);checks++;
// Only one click per run observed: consecutive running reads never re-toggle.
r=stop(['running','running','unknown','running','idle','idle','idle'],{rest:'running'});
assert.deepEqual([r.ok,r.clicks],[true,1]);checks++;
// Restarts are bounded: at most three clicks in total.
r=stop(['running','idle','running','idle','running','idle','running','idle','running'],{rest:'running'});
assert.deepEqual([r.ok,r.clicks,r.polls],[false,3,40]);checks++;
// Diagnostics reset on every call.
stop([],{rest:'running'});r=stop([],{rest:'idle'});
assert.deepEqual([r.reported,r.polls],[0,3]);checks++;
// ---- B38 click guard: the toggle is sent directly, only on a fresh "running" re-read.
// The caption goes blank between the read and the re-read while the tester is really
// idle: nothing is sent (it would have been a Start), and the guard stays armed.
r=stop([['running','unknown'],'idle','idle','idle'],{rest:'idle'});
assert.deepEqual([r.ok,r.clicks],[true,0]);checks++;
// Same blank re-read on a tester that is still running: no send yet, still armed, so the
// next "running" poll sends exactly one Stop.
r=stop([['running','unknown'],'running','running','idle','idle','idle'],{rest:'idle',unknownTruth:'running'});
assert.deepEqual([r.ok,r.clicks,r.reported],[true,1,1]);checks++;
// The run ended between the read and the re-read: an idle re-read never toggles.
r=stop([['running','idle'],'idle','idle'],{rest:'idle'});
assert.deepEqual([r.ok,r.clicks,r.polls],[true,0,4]);checks++;
// A blank caption all along on an idle tester: 40 polls, no toggle, honest false, and
// one passive read per poll (the fresh re-read happens only after a "running" read).
r=stop([],{rest:'unknown'});
assert.deepEqual([r.ok,r.clicks,r.polls,r.read],[false,0,40,40]);checks++;
// Older terminals (build 5000 and below) reach the pane through the 0xE81E frame.
r=stop(['running','running'],{rest:'idle',build:4900});
assert.deepEqual([r.ok,r.clicks],[true,1]);checks++;
// No tester pane found: nothing is sent, nothing is counted, the guard stays armed.
r=stop([],{rest:'running',noPane:true});
assert.deepEqual([r.ok,r.clicks,r.reported],[false,0,0]);checks++;
// The guard never routes through MTTESTER::ClickStop (and its IsIdle() fallback).
const stopSource=read('GOATTesterStopConfirm.mqh').replace(/\/\/.*$/gm,'');
assert.doesNotMatch(stopSource,/ClickStop\s*\(/);
assert.match(stopSource,/bool GoatTesterSendStopIfRunning\(void\)\n  \{\n   if\(GoatStudioTesterState\(\)!="running"\) return false;/);checks++;

// ---- B38 fold-in 2: the Studio writer keeps EvidenceEnd, and finished exports are checked.
const controls='[Export]\nSetsToExport=6\nMinScore=60\nTargetDD=1000\nAdjustLots=0\nBackOOSDate=2024.01.08\nMinARF=0.2\nMinSR=2.5\nIncludeBackOOS=0\nIncludeSequenceData=1\n';
const staged='[Export]\r\nSetsToExport=6\r\nMinScore=60\r\nEvidenceEnd=2026.09.25\r\nIncludeSequenceData=1\r\n';
for(const [text,value] of [[staged,'2026.09.25'],['EvidenceEnd=2026.09.25',''+'2026.09.25'],['[Export]\nEvidenceEnd= 2026.10.02 \n','2026.10.02'],
  [controls,''],['',''],['[Export]\nNoEvidenceEnd=2026.09.25\n',''],['[Export]\nXEvidenceEnd=2026.09.25\n','']])
  assert.equal(context.GoatEvidenceSettingValue(text),value,JSON.stringify(text)),checks++;
// A rewrite from the controls carries the staged value; it never invents, doubles or overrides one.
assert.equal(context.GoatEvidenceEndCarry(controls,staged),controls+'EvidenceEnd=2026.09.25\n');checks++;
assert.equal(context.GoatEvidenceEndCarry(controls.slice(0,-1),staged),controls+'EvidenceEnd=2026.09.25\n','a missing trailing newline is added once');checks++;
assert.equal(context.GoatEvidenceEndCarry(controls,controls),controls,'nothing staged: legacy settings stay as they are');checks++;
assert.equal(context.GoatEvidenceEndCarry(controls,''),controls);checks++;
const already=controls+'EvidenceEnd=2026.10.02\n';
assert.equal(context.GoatEvidenceEndCarry(already,staged),already,'a value already in the rewrite wins');checks++;
assert.equal(context.GoatEvidenceEndCarry('',staged),'','an empty rewrite is never turned into a header-less file');checks++;
assert.equal(context.GoatEvidenceSettingValue(context.GoatEvidenceEndCarry(controls,staged)),'2026.09.25');checks++;
// The real end of an export, from its .set header.
const header=(foos,sample)=>'; ----\n; GOAT V1.49 EURUSD,M1\n'+(sample?'; SAMPLE: '+sample+' Days=80 Trades=12 PL=100\n':'')+(foos?'; FOOS:   '+foos+' Days=5 Trades=2 PL=10\n':'')+'; ----\nMode_Operation=0\n';
for(const [text,end] of [[header('2026.06.02-2026.09.25','2026.01.05-2026.06.02'),'2026.09.25'],[header('2026.06.02-2026.09.24','2026.01.05-2026.06.02'),'2026.09.24'],
  [header(null,'2026.01.05-2026.09.25'),'2026.09.25'],[header('2026.06.02-2026.9.25',null),''],[header('2026.06.02-',null),''],[header(null,null),''],['','']])
  assert.equal(context.GoatEvidenceExportEnd(text),end,text),checks++;

// ---- V1.49 call sites.
const main=read('GOAT V1.49.mq5'),dispatch=read('GOATStudioDispatch.mqh'),ui=read('GOATStudioUI.mqh');
assert.match(main,/#define GOAT_STOP_CONFIRM_V149\n/);assert.match(main,/#define GOAT_EVIDENCE_END_V149\n/);
assert.match(main,/#include "GOATEvidenceEnd.mqh"/);checks++;
const cancel=dispatch.slice(dispatch.indexOf('string GoatStudioCancelRequest('),dispatch.indexOf('string GoatStudioExecuteRequest('));
const guarded=cancel.slice(cancel.indexOf('#ifdef GOAT_STOP_CONFIRM_V149'),cancel.indexOf('#else',cancel.indexOf('#ifdef GOAT_STOP_CONFIRM_V149')));
assert.match(guarded,/bool stopped=GoatTesterStopConfirmed\(\);/);
assert.match(guarded,/GOAT_CANCEL_STOP_CONFIRM .*idle_confirmed=/);
assert.match(guarded,/elapsed_ms="\+\(string\)g_GoatStopConfirmElapsedMs/);checks++;
// The cancel latch and launch files are cleared before stopping; the queue is read after it.
assert.ok(cancel.indexOf('GoatBatchRecordControllerCancel();')<cancel.indexOf('GoatTesterStopConfirmed()'));
assert.ok(cancel.indexOf('FileDelete(cfg,FILE_COMMON)')<cancel.indexOf('GoatTesterStopConfirmed()'));
assert.ok(cancel.indexOf('GoatTesterStopConfirmed()')<cancel.indexOf('GetFileContent(native_run+"\\\\queue.GOAT")'));
assert.match(cancel,/return \(stopped && saved && cleared\) \? "CANCELLED_RECONCILE" : "CANCEL_SIGNAL_SENT_RECONCILE";/);checks++;
assert.match(dispatch,/#ifdef GOAT_STOP_CONFIRM_V149\n#include "GOATTesterStopConfirm.mqh"\n#endif/);checks++;
const exporter=main.slice(main.indexOf('bool StartExporter(bool reportMode)'),main.indexOf('int RunAndStoreSet('));
const resolve=exporter.indexOf('GoatEvidenceEndToDate(evidenceSetting,TimeTradeServer(),xmlData.endD,evidenceEnd,evidenceError)');
assert.ok(resolve>0,'EvidenceEnd resolved from the server clock and the optimization window end');
assert.ok(exporter.indexOf('FetchExportSetting("EvidenceEnd",Key,EA_Name,Server)')<resolve);
assert.ok(resolve<exporter.indexOf('Running top Score Set on back history only'),'resolved before any tester run');
assert.match(exporter,/if\(evidenceSetting!=""\)/);
assert.match(exporter,/if\(evidenceToDate==""\) \{LogOrPrint\(reportMode,"❌ "\+evidenceError\+"\. No exports were run\.",Key,EA_Name,Server\); return false;\}/);
assert.match(exporter,/strT\.toDate=\(evidenceToDate!="" \? evidenceToDate : GetLastFridayDate\(\)\);/);checks++;
const observation=ui.slice(ui.indexOf('void CStrategyTesterDialog::ManagedObservation('),ui.indexOf('void CStrategyTesterDialog::ManagedSave('));
assert.match(observation,/#ifdef GOAT_EVIDENCE_END_V149\n.*\n\s*body\+=",\\"evidence_end\\":"\+GoatStudioQuote\(GOAT_EVIDENCE_END_CAPABILITY\);\n#endif/);
assert.ok(observation.indexOf('GOAT_EVIDENCE_END_CAPABILITY')<observation.indexOf('observed_terminal_utc'));
assert.match(read('GOATEvidenceEnd.mqh'),/#define GOAT_EVIDENCE_END_CAPABILITY "goat-evidence-end-v1"/);checks++;
// B38: every Studio rewrite of export_settings.GOAT carries EvidenceEnd before it is written.
const optimizer=read('Optimizer.mqh');
const save=optimizer.slice(optimizer.indexOf('bool CStrategyTesterDialog::SaveCurrentBatchPackage(void)'),optimizer.indexOf('bool CStrategyTesterDialog::RehomeRunIfEditedNameChanged(void)'));
assert.match(save,/GetExportSettingsString\(\)\);\n#ifdef GOAT_EVIDENCE_END_V149\n   exportSettings=GoatEvidenceEndCarry\(exportSettings,GetFileContent\(Path_ExportSettings\)\);\n#endif\n   if\(exportSettings!="" && !GoatOptWriteTextFile\(Path_ExportSettings,exportSettings\)\) return false;/);checks++;
const rehome=optimizer.slice(optimizer.indexOf('bool CStrategyTesterDialog::RehomeRunIfEditedNameChanged(void)'),optimizer.indexOf('bool CStrategyTesterDialog::LoadBatchPackage('));
assert.match(rehome,/GetExportSettingsString\(\)\);\n#ifdef GOAT_EVIDENCE_END_V149\n   exportSettings=GoatEvidenceEndCarry\(exportSettings,GetFileContent\(oldExportSettingsPath\)\);\n#endif\n/);
assert.ok(rehome.indexOf('GoatEvidenceEndCarry(')<rehome.indexOf('GoatOptCreateRunPath('),'carried from the old run folder before it moves');checks++;
// Load and human Start both rewrite through SaveCurrentBatchPackage, after the package's own settings are on disk.
const load=optimizer.slice(optimizer.indexOf('bool CStrategyTesterDialog::LoadBatchPackage('),optimizer.indexOf('bool CStrategyTesterDialog::SaveStrategyInputsFromSet('));
assert.ok(load.indexOf('GoatOptWriteTextFile(Path_ExportSettings,exportSettings)')<load.indexOf('SaveCurrentBatchPackage();'));checks++;
assert.equal((optimizer.match(/GetExportSettingsString\(\)\);\n#ifdef GOAT_EVIDENCE_END_V149\n   exportSettings=GoatEvidenceEndCarry\(/g)||[]).length,2,'both control rewrites carry it');checks++;
// Absent settings are journaled; finished exports are checked after they are moved.
assert.match(exporter,/else\n    \{\n.*\n     Print\("GOAT_EVIDENCE_END_ABSENT build_id="\+GOAT_BUILD_ID\+" legacy_to_date="\+GetLastFridayDate\(\)\);/);checks++;
for(const [array,moved] of [['AdjustedExports','"✅ All Shortlisted and Adjusted Exports migrated & saved."'],['g_allExports','"✅ All Shortlisted Exports migrated & saved."']]){
  const at=exporter.indexOf(moved),check=exporter.indexOf('GoatEvidenceEndCheckExports('+array+',evidenceEnd,reportMode);');
  assert.ok(at>0 && check>at && check-at<400,array+' is checked right after it is moved');checks++;
}
const verify=main.slice(main.indexOf('void GoatEvidenceEndCheckExports('),main.indexOf('bool StartExporter(bool reportMode)'));
assert.match(verify,/GoatEvidenceExportEnd\(GoatExportReadTextCommon\(expArr\[i\]\.setFile,0\)\)/);
assert.match(verify,/if\(evidenceEnd==""\) return;/);
assert.match(verify,/Print\("GOAT_EVIDENCE_END_CHECK build_id="\+GOAT_BUILD_ID\+" staged="\+evidenceEnd/);
assert.match(verify,/if\(end==evidenceEnd\) \{matched\+\+; continue;\}/);
assert.match(verify,/if\(StringToTime\(end\)>staged\) later\+\+; else earlier\+\+;/);checks++;
// Older entrypoints keep their behaviour.
for(const version of ['1.47','1.48']){
  const old=read('GOAT V'+version+'.mq5');
  assert.doesNotMatch(old,/GOAT_STOP_CONFIRM_V149|GOAT_EVIDENCE_END_V149|GOATEvidenceEnd/);
}
checks++;
console.log(`${checks} FU35 stop-confirmation and evidence-end checks PASS`);
