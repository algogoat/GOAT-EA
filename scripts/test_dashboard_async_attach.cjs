// Execute the production agent attach path (Dashboard.mqh + GOATPortfolioSetupControl.mqh)
// against a modelled MT5 in which ChartApplyTemplate only queues the template and the queue
// is processed after the requesting event handler returns (goatai#1885 6027754245), and in
// which a child's OnInit (license startup) can take up to a minute before it registers.
// This is source-control-flow verification, not native MT5 evidence: it proves the
// state machine completes and unwinds, not when a real terminal applies a template.
// GOAT_EA_ROOT points the harness at another source tree (the mutation check uses it).
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const dashboard=read('Dashboard.mqh'),setup=read('GOATPortfolioSetupControl.mqh'),license=read('GOATLicenseInitRetry.mqh');

function bodyOf(src,signature) {
 const start=src.indexOf(signature);assert.ok(start>=0,signature);
 const begin=src.indexOf('{',start+signature.length);let end=begin+1,depth=1;
 for(;depth;end++){if(src[end]==='{')depth++;if(src[end]==='}')depth--;}
 return src.slice(begin+1,end-1);
}
function enabled(text) {
 const stack=[];let active=true;
 return text.split('\n').filter(line=>{
  if(/^\s*#ifdef/.test(line)){stack.push(active);active=active&&line.includes('GOAT_DASH_AI_LAUNCH_POLICY_V147');return false;}
  if(/^\s*#else/.test(line)){active=stack.at(-1)&&!active;return false;}
  if(/^\s*#endif/.test(line)){active=stack.pop();return false;}
  return active;
 }).join('\n');
}
function js(text) {
 return enabled(text)
  .replace(/\bstring (\w+)\[\];/g,'let $1=[];')
  .replace(/\b(?:const )?(?:string|int|long|bool|uint|double|ENUM_TIMEFRAMES) (?=[A-Za-z_]\w*\s*[=;,])/g,'let ')
  .replace(/\((?:long|datetime)\)/g,'').replace(/__FUNCTION__/g,'"fn"')
  .replace(/StringReplace\(tplName,"\.set","\.tpl"\)/g,'tplName=tplName.split(".set").join(".tpl")')
  .replace(/GoatFindMagicByCid\(([^,]+),([^,]+),(\w+)\)/g,'find($1,$2,v=>$3=v)')
  .replace(/GlobalVariableGet\((GoatChildGVName\([^\n]+?\)|pending),(\w+)\)/g,'gvGet($1,v=>$2=v)')
  .replace(/g_sets\[idx\]\.cid\/1000000000/g,'Math.trunc(g_sets[idx].cid/1000000000)')
  .replace(/(?<![\w.\]])cid\/1000000000/g,'Math.trunc(cid/1000000000)');
}
const method=name=>bodyOf(dashboard,'CGOATDashboard::'+name);
const BUDGET=Number((dashboard.match(/#define GOAT_AGENT_ATTACH_BUDGET_MS (\d+)/)||[])[1]);
const FAILED=Number((dashboard.match(/#define GOAT_ATTACH_FAILED_MAGIC (-\d+)/)||[])[1]);
assert.ok(FAILED<-1,'the failed marker is distinct from the never-deployed -1');
const LICENSE_DEADLINE=Number((license.match(/ulong deadline=GetTickCount64\(\)\+(\d+);/)||[])[1]);
assert.ok(LICENSE_DEADLINE>0,'license startup deadline found');
const prepareCall='bool started=PrepareChildLaunch(idx,tf,tplName);';
const beginBody=method('AgentBeginDeployRow(const int idx)');assert.ok(beginBody.includes(prepareCall));
const deployBlock=bodyOf(setup,'else if(action=="deploy_next")');
const deferReturn='FileClose(owner);\n            return;';assert.ok(deployBlock.includes(deferReturn));
// The poll's first statement after building root: settle an in-flight attach or hold every request.
const pollBody=bodyOf(setup,'void GoatPortfolioSetupPoll(void)');
const holdLine=pollBody.split('\n').find(l=>l.includes('GoatPortfolioAttachContinue(root)'));assert.ok(holdLine,'poll must settle an in-flight attach first');
assert.ok(pollBody.indexOf(holdLine)<pollBody.indexOf('registration.json'),'the attach settles before any request is read');
// The stale-template sweep runs when a saved dashboard loads, after its rows are read.
const loadBody=method('LoadDashboardConfig(void)');
assert.ok(loadBody.includes('SweepStaleChildTemplates();')&&loadBody.indexOf('SweepStaleChildTemplates();')>loadBody.lastIndexOf('FileClose(h);'),
 'LoadDashboardConfig sweeps stale templates once its rows are loaded');
const production=[
 'function PrepareChildLaunch(idx){let tf,tplName;const ok=(()=>{'+js(bodyOf(dashboard,'bool PrepareChildLaunch(const int idx,ENUM_TIMEFRAMES &tf,string &tplName)'))+'})();return {ok,tf,tplName};}',
 'function AgentBeginDeployRow(idx){'+js(beginBody).replace(js(prepareCall),'const p=PrepareChildLaunch(idx);let started=p.ok;tf=p.tf;tplName=p.tplName;')+'}',
 'function AgentPollDeployRow(){'+js(method('AgentPollDeployRow(void)'))+'}',
 'function IsAgentAttachFailedChart(cid){'+js(method('IsAgentAttachFailedChart(const long cid)'))+'}',
 'function CloseFailedChildChart(idx){'+js(method('CloseFailedChildChart(const int idx)'))+'}',
 'function AgentUnwindFailedAttach(idx){'+js(method('AgentUnwindFailedAttach(const int idx)'))+'}',
 'function ResetFailedChildRow(idx,tplName){'+js(method('ResetFailedChildRow(const int idx,const string tplName)'))+'}',
 'function SweepStaleChildTemplates(){'+js(method('SweepStaleChildTemplates(void)'))+'}',
 'function BeginChildAttach(idx,tf,tplName){'+js(method('BeginChildAttach(const int idx,ENUM_TIMEFRAMES tf,const string tplName)'))+'}',
 'function ApplyTemplate(idx,tf,tplName){'+js(method('ApplyTemplate(const int idx,ENUM_TIMEFRAMES tf,const string tplName)'))+'}',
 'function FailChildAttachTimeout(idx,tplName){'+js(method('FailChildAttachTimeout(const int idx,const string tplName)'))+'}',
 'function CompleteChildAttach(idx,tplName){'+js(method('CompleteChildAttach(const int idx,const string tplName)'))+'}',
 'function NewSingleInstance(idx){'+js(method('NewSingleInstance(const int idx)'))+'}',
 // The dashboard's handler for a child's status event (HandleChartEvent).
 'function ChildStatusEvent(id,lparam,dparam,sparam){'+js(bodyOf(dashboard,'if(id==GOAT_EVENT_CHILD_STATUS)'))+'}',
 'function GoatPortfolioRowLinked(row){'+js(bodyOf(setup,'bool GoatPortfolioRowLinked(const int row)'))+'}',
 // Production template file I/O: write next to the SET, copy over Profiles\Templates, delete after.
 'function GoatDashboardCommonSetPath(path){'+js(bodyOf(dashboard,'string GoatDashboardCommonSetPath(const string path)'))+'}',
 'function SaveTemplateAndCopy(tplName,tplText){'+js(method('SaveTemplateAndCopy(const string tplName,const string tplText)'))+'}',
 'function DeleteCopiedTemplate(tplName){'+js(method('DeleteCopiedTemplate(const string tplName)'))+'}',
 'function GoatPortfolioAttachContinue(root){'+js(bodyOf(setup,'bool GoatPortfolioAttachContinue(const string root)'))+'}',
 'function settleOrHold(root){'+js(holdLine).replace(/return;/,'return true;')+'\nreturn false;}',
 'function deployNext(count,id,hash,owner){let result="started";'+js(deployBlock).replace(js(deferReturn),'FileClose(owner);return "pending";')+'\nreturn result;}',
].join('\n');

const control=()=>({t:'',Text(v){if(v===undefined)return this.t;this.t=v;},Color(){}});
const COMMON='C:\\Common',DATA='C:\\T3',SETS=COMMON+'\\Files\\GOAT\\Deployments\\d1';
const TEMPLATES='\\\\?\\'+DATA+'\\MQL5\\Profiles\\Templates\\';
const tplOf=i=>`GOAT V1.49 SYM${i},M1_B35-${i}.tpl`;
// templates: the terminal's MQL5\Profiles\Templates folder (name -> bytes), which outlives a dashboard session.
// childDelay: ms from the template applying to the end of the child's OnInit (license startup).
// registers=false: the child runs and reports status but never writes its pending registration.
// restored: charts MT5 brings back with the profile after a restart ({cid,sym,child:true|false}).
function world({members=35,childStarts=true,childDelay=0,registers=true,enqueueOk=true,templates=new Map(),rows=null,
                copyOk=()=>true,closeOk=true,restored=[]}={}) {
 const mt5={clock:1000,nextCid:66948585504739,charts:new Map(),queue:[],inits:[],templates,commonFiles:new Map(),gv:new Map(),
            cidField:new Map(),children:[],applied:[],algo:false,positions:0};
 const sets=rows||[...Array(members)].map((_,i)=>({name:`GOAT V1.49 SYM${i},M1_B35-${i}.set`,path:`${SETS}\\set${i}`,sym:'SYM'+(i%17),cid:0,magic:0,status:'Pending'}));
 const log={phases:[],audits:[],receipts:new Map(),saves:0,saved:null,ownerBusy:false,writeOk:true};
 let nextMagic=7000;
 const startChild=(chart)=>{ // end of OnInit: the child records its chart and its pending registration
  const magic=nextMagic++;
  mt5.cidField.set(chart.cid,magic);if(registers) mt5.gv.set(`${magic}/${chart.sym}/Magic`,magic);
  mt5.children.push({cid:chart.cid,sym:chart.sym,magic});
 };
 for(const r of restored){mt5.charts.set(r.cid,{cid:r.cid,sym:r.sym,expert:!!r.child,closed:false});if(r.child) startChild(mt5.charts.get(r.cid));}
 const processQueue=()=>{ // MT5 drains chart command queues once the handler has returned
  for(const cmd of mt5.queue.splice(0)) {
   const chart=mt5.charts.get(cmd.cid);
   if(chart.closed) continue;
   if(!mt5.templates.has(cmd.tpl)) {chart.missingTemplate=true;continue;}
   chart.appliedTemplate=mt5.templates.get(cmd.tpl);chart.expert=true;
   mt5.applied.push({cid:cmd.cid,tpl:cmd.tpl,bytes:chart.appliedTemplate});
   if(!childStarts) continue;
   if(childDelay===0) startChild(chart);else mt5.inits.push({chart,at:mt5.clock+childDelay});
  }
 };
 const ctx={
  g_sets:sets,edt_Status:[...Array(sets.length+2)].map(control),btn_Action:[...Array(sets.length+2)].map(control),
  EA_Path:'Experts\\GOAT-EA\\GOAT V1.49.ex5',EA_Name_:'GOAT V1.49',ChartId:1,PERIOD_M1:1,
  m_agent_setup_quiet:false,m_agent_attach_pending:false,m_agent_attach_idx:-1,m_agent_attach_tpl:'',m_agent_attach_start:0,m_child_attach_step:'',
  GOAT_AGENT_ATTACH_BUDGET_MS:BUDGET,GOAT_ATTACH_FAILED_MAGIC:FAILED,GOAT_EVENT_CHILD_STATUS:'child-status',
  GoatPortfolioAttachPending:false,GoatPortfolioAttachId:'',GoatPortfolioAttachHash:'',GoatPortfolioAttachResult:'',
  ACCOUNT_TRADE_MODE:1,ACCOUNT_TRADE_MODE_DEMO:0,TERMINAL_CONNECTED:2,TERMINAL_TRADE_ALLOWED:3,CHART_BRING_TO_TOP:4,
  MB_OK:0,MB_ICONWARNING:0,FILE_READ:1,FILE_WRITE:2,FILE_BIN:4,FILE_COMMON:8,INVALID_HANDLE:-1,GOAT_GV_FIELD_MAGIC:'Magic',
  AccountInfoInteger:()=>0,TerminalInfoInteger:k=>k===2?1:(k===3?(mt5.algo?1:0):0),
  PositionsTotal:()=>mt5.positions,OrdersTotal:()=>0,
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},
  StringFind:(s,f)=>s.indexOf(f),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringSplit:(s,sep,out)=>{out.length=0;out.push(...s.split(sep));return out.length;},
  EndsWith:(s,x)=>s.endsWith(x),TF:()=>1,StringFormat:(f,...a)=>a.join(' '),
  Print:()=>{},PrintFormat:()=>{},Alert:()=>{},MessageBox:()=>{throw new Error('agent path must not prompt');},
  ResetLastError:()=>{},GetLastError:()=>0,MarkStateDirty:()=>{},StatusColor:()=>0,UpdateAILaunchControls:()=>{},
  DisplayStatusForRow:i=>sets[i].status,TimeCurrent:()=>Math.floor(mt5.clock/1000),TimeGMT:()=>Math.floor(mt5.clock/1000),
  PrepareAILaunchPolicy:()=>true,BuildTemplate:(ea,eaPath,setFile)=>'<chart>fresh '+setFile,
  SetFolder:SETS,FILE_TXT:16,FILE_ANSI:32,TERMINAL_COMMONDATA_PATH:10,TERMINAL_DATA_PATH:11,
  TerminalInfoString:k=>k===10?COMMON:DATA,StringLen:s=>s.length,
  FileWriteString:(h,text)=>{mt5.commonFiles.set(h,text);return text.length;},
  FileDelete:rel=>mt5.commonFiles.delete(rel),
  CopyFileW:(src,dst,failIfExists)=>{ // src/dst carry the \\?\ prefix; 0 = overwrite an existing file
   const rel=src.slice(('\\\\?\\'+COMMON+'\\Files\\').length);
   if(!dst.startsWith(TEMPLATES)||!mt5.commonFiles.has(rel)) return 0;
   const name=dst.slice(TEMPLATES.length);
   if((failIfExists&&mt5.templates.has(name))||!copyOk(name)) return 0;
   mt5.templates.set(name,mt5.commonFiles.get(rel));return 1;},
  DeleteFileW:dst=>dst.startsWith(TEMPLATES)&&mt5.templates.delete(dst.slice(TEMPLATES.length))?1:0,
  // The saved dashboard state: a copy of every row, which is what a restart reloads.
  SaveDashboardConfig:()=>{log.saves++;log.saved=sets.map(s=>({...s}));return true;},
  AppendAILaunchAudit:(idx,stage)=>log.audits.push([idx,stage]),
  GoatDeploymentPhase:(phase,target=0,controlName='')=>log.phases.push({phase,target,control:controlName}),
  GetTickCount:()=>mt5.clock,Sleep:ms=>{mt5.clock+=ms;},
  ChartOpen:(sym)=>{const cid=mt5.nextCid++;mt5.charts.set(cid,{cid,sym,expert:false,closed:false});return cid;},
  ChartApplyTemplate:(cid,tpl)=>{if(!enqueueOk)return false;mt5.queue.push({cid,tpl});return true;},
  ChartClose:cid=>{ // closing a chart unloads its EA, including one still in OnInit
   const chart=mt5.charts.get(cid);if(!chart||!closeOk) return false;
   chart.closed=true;mt5.children=mt5.children.filter(c=>c.cid!==cid);return true;},
  ChartSymbol:cid=>{const chart=mt5.charts.get(cid);return chart&&!chart.closed?chart.sym:'';},
  ChartRedraw:()=>{},ChartSetInteger:()=>true,
  GoatChildGVName:(m,s,f)=>`${m}/${s}/${f}`,
  find:(sym,cid,assign)=>{if(!mt5.cidField.has(cid))return false;assign(mt5.cidField.get(cid));return true;},
  gvGet:(key,assign)=>{if(!mt5.gv.has(key))return false;assign(mt5.gv.get(key));return true;},
  GlobalVariableDel:key=>mt5.gv.delete(key),GlobalVariablesFlush:()=>{},
  // The owner lock answers busy/free; a template write returns its own relative path as the handle.
  FileOpen:(p,mode)=>p.endsWith('owner.lock')?(log.ownerBusy?-1:5):(mode&2?p:-1),FileClose:()=>{},
  GoatSetupWrite:(file,body)=>{if(!log.writeOk)return false;log.receipts.set(file,body);return true;},
  GoatPortfolioSnapshot:(id,action,hash,result)=>({id,action,hash,result}),
 };
 vm.createContext(ctx);vm.runInContext(production,ctx);
 vm.runInContext('var DashboardDialog={g_sets,AgentBeginDeployRow,AgentPollDeployRow};',ctx);
 const linked=i=>vm.runInContext('GoatPortfolioRowLinked('+i+')',ctx);
 const root='GOAT\\AgentPortfolio\\T3\\';let request=null;const setRequest=id=>{request=id;};
 const tick=()=>{ // one second: child OnInit/OnTimer, child status events, the dashboard's OnTimer, then the queue drains
  mt5.clock+=1000;
  for(const due of mt5.inits.filter(i=>i.at<=mt5.clock)){mt5.inits.splice(mt5.inits.indexOf(due),1);if(!due.chart.closed) startChild(due.chart);}
  for(const c of mt5.children){
   mt5.gv.set(`${c.magic}/${c.sym}/SETUP_UTC`,Math.floor(mt5.clock/1000));
   mt5.gv.set(`${c.magic}/${c.sym}/SETUP_CID_HI`,Math.trunc(c.cid/1e9));mt5.gv.set(`${c.magic}/${c.sym}/SETUP_CID_LO`,c.cid%1e9);
   ctx.ChildStatusEvent(ctx.GOAT_EVENT_CHILD_STATUS,c.magic,c.cid,c.sym+'|Running');
  }
  // Mirrors GoatPortfolioSetupPoll: settle an in-flight attach, else read one request.
  if(!ctx.settleOrHold(root)&&request&&!log.receipts.has(root+request+'.json')) {
   const id=request,file=root+id+'.json';
   log.receipts.set(file,{id,result:'started'});
   const result=ctx.deployNext(sets.length,id,'hash',5);
   if(result!=='pending') log.receipts.set(file,{id,result});
  }
  processQueue();
 };
 const deployNext=(id,maxTicks=100)=>{
  request=id;const file=root+id+'.json';
  for(let t=1;t<=maxTicks;t++){tick();const r=log.receipts.get(file);if(r&&r.result!=='started')return {result:r.result,ticks:t};}
  return {result:'receipt_timeout',ticks:maxTicks};
 };
 return {ctx,mt5,sets,log,tick,deployNext,setRequest,root,linked};
}

let passed=0;
{ // 0. The agent budget stays above the child's license startup deadline.
 assert.ok(BUDGET>LICENSE_DEADLINE+5000,`agent attach budget ${BUDGET} ms must exceed the ${LICENSE_DEADLINE} ms license startup`);passed++;
}
{ // 1. The B41 shape (wait inside the handler) reproduces T3: no child, template gone, chart left bare.
 const w=world({members:1});w.ctx.m_agent_setup_quiet=true;
 const tpl=tplOf(0);w.mt5.templates.set(tpl,'<chart>');
 const t0=w.mt5.clock;assert.equal(w.ctx.ApplyTemplate(0,1,tpl),false);
 assert.ok(w.mt5.clock-t0>20000);assert.ok(!w.mt5.templates.has(tpl));
 // the handler has returned; the queued template now finds nothing to apply
 w.tick();const chart=[...w.mt5.charts.values()][0];
 assert.equal(chart.expert,false);assert.equal(chart.missingTemplate,true);
 assert.deepEqual(w.log.phases.map(p=>p.phase).slice(-2),['handshake_begin','handshake_timeout']);passed++;
}
{ // 2. Async: all 35 Balanced35 members attach one deploy_next at a time, then all_attached.
 const w=world({members:35});
 for(let i=0;i<35;i++) {
  const r=w.deployNext('req'+i);assert.equal(r.result,'child_attached',`member ${i}`);assert.ok(r.ticks<=3,`member ${i} took ${r.ticks}s`);
  assert.ok(['Linked','Running'].includes(w.sets[i].status));assert.ok(w.sets[i].cid>0&&w.sets[i].magic>0);assert.ok(w.linked(i));
  assert.equal(w.ctx.m_agent_attach_pending,false);assert.equal(w.ctx.GoatPortfolioAttachPending,false);
 }
 assert.equal(new Set(w.sets.map(s=>s.magic)).size,35);assert.equal(new Set(w.sets.map(s=>s.cid)).size,35);
 assert.equal(w.mt5.templates.size,0,'every copied template is removed after linking');
 assert.equal(w.log.audits.filter(a=>a[1]==='LINKED').length,35);assert.equal(w.log.audits.filter(a=>a[1]==='APPLY_FAILED').length,0);
 assert.equal(w.deployNext('req-final').result,'all_attached');passed++;
}
{ // 3. The template is still on disk when MT5 drains the queue (it is deleted only after linking).
 const w=world({members:2});
 w.deployNext('a');const linkedAt=w.log.phases.findIndex(p=>p.phase==='handshake_linked');
 assert.ok(linkedAt>0);assert.equal([...w.mt5.charts.values()][0].missingTemplate,undefined);passed++;
}
{ // 4. Timeout unwinds cleanly: the child never registers; the budget runs on timer ticks; the chart is
  //    closed; its ID stays as the partial-deployment lock; the step is named.
 const w=world({members:3,childStarts:false});
 const r=w.deployNext('t');assert.equal(r.result,'child_attach_failed');
 assert.ok(r.ticks>=BUDGET/1000&&r.ticks<=BUDGET/1000+2,`ticks ${r.ticks}`);
 assert.equal(w.mt5.templates.size,0);assert.equal(w.sets[0].status,'Pending');
 assert.ok(w.sets[0].cid>0,'the chart identity stays persisted as a partial-deployment lock');
 assert.equal(w.mt5.charts.get(w.sets[0].cid).closed,true,'the failed child chart is closed');
 assert.equal(w.ctx.m_agent_attach_pending,false);assert.equal(w.ctx.GoatPortfolioAttachPending,false);
 assert.deepEqual(w.log.audits.map(a=>a[1]),['PREPARED','APPLY_FAILED']);
 assert.deepEqual(w.log.phases.slice(-3).map(p=>p.phase),['handshake_timeout','child_chart_closed','child_attach_failed']);
 assert.deepEqual(w.log.phases.at(-1),{phase:'child_attach_failed',target:w.sets[0].cid,control:'handshake_timeout'});
 assert.equal(w.deployNext('t2').result,'rejected_partial_deployment');passed++;
}
{ // 5. An enqueue failure answers in the same tick, names the step and leaves nothing pending.
 const w=world({members:2,enqueueOk:false});
 const r=w.deployNext('e');assert.equal(r.result,'child_attach_failed');assert.equal(r.ticks,1);
 assert.equal(w.mt5.templates.size,0);assert.equal(w.ctx.m_agent_attach_pending,false);
 assert.equal(w.log.phases.at(-1).control,'template_enqueue');passed++;
}
{ // 6. A busy owner lock keeps "started" and retries; no other request is read meanwhile.
 const w=world({members:2});
 const receipt=id=>w.log.receipts.get(w.root+id+'.json');
 w.setRequest('y');w.tick();
 assert.equal(receipt('y').result,'started');assert.equal(w.ctx.GoatPortfolioAttachPending,true);
 w.log.ownerBusy=true;w.tick();w.tick();
 assert.equal(receipt('y').result,'started');assert.equal(w.ctx.GoatPortfolioAttachResult,'child_attached');
 assert.equal(w.ctx.m_agent_attach_pending,false,'the dashboard side settled; only the receipt write is retried');
 w.setRequest('z');w.tick();assert.equal(receipt('z'),undefined);
 w.log.ownerBusy=false;w.tick();
 assert.equal(receipt('y').result,'child_attached');
 assert.equal(receipt('z').result,'started','the next request is read only after the first is answered');
 assert.equal(w.ctx.GoatPortfolioAttachId,'z');passed++;
}
{ // 7. A failed receipt write is retried the same way.
 const w=world({members:1});
 w.setRequest('q');w.tick();w.log.writeOk=false;w.tick();w.tick();
 assert.equal(w.log.receipts.get(w.root+'q.json').result,'started');
 w.log.writeOk=true;w.tick();assert.equal(w.log.receipts.get(w.root+'q.json').result,'child_attached');passed++;
}
// A dashboard restart mid-attach (goatai#1885 6028113003) can leave a copied template in
// MQL5\Profiles\Templates. The next session must never apply those stale bytes.
const staleName=tplOf(0),orphanName='GOAT V1.49 OLD,M1_B34-9.tpl';
{ // 8. A same-named stale template is overwritten before the template is queued; an orphan is never applied.
 const templates=new Map([[staleName,'<chart>STALE inputs from the previous session'],[orphanName,'<chart>STALE orphan']]);
 const w=world({members:2,templates});
 const r=w.deployNext('s');assert.equal(r.result,'child_attached');
 assert.equal(w.mt5.applied.length,1);
 assert.equal(w.mt5.applied[0].tpl,staleName);assert.equal(w.mt5.applied[0].bytes,'<chart>fresh '+SETS+'\\set0');
 assert.ok(!w.mt5.templates.has(staleName),'deleted after linking');
 assert.equal(w.deployNext('s2').result,'child_attached');
 assert.ok(w.mt5.applied.every(a=>a.tpl!==orphanName&&!a.bytes.includes('STALE')));
 assert.equal(w.mt5.templates.get(orphanName),'<chart>STALE orphan','an unrelated leftover is left alone, never queued');passed++;
}
{ // 9. If the copy over a stale template fails, nothing is opened or queued, and the row stays retryable.
 const templates=new Map([[staleName,'<chart>STALE']]);let copies=0;
 const w=world({members:1,templates,copyOk:()=>++copies>1});
 const r=w.deployNext('f');assert.equal(r.result,'child_attach_failed');assert.equal(r.ticks,1);
 assert.equal(w.mt5.charts.size,0);assert.equal(w.mt5.applied.length,0);assert.equal(w.sets[0].cid,0);
 assert.equal(w.log.phases.at(-1).control,'prepare');assert.equal(w.ctx.m_agent_attach_pending,false);
 assert.equal(w.mt5.templates.get(staleName),'<chart>STALE','the stale bytes are left as they were, unqueued');
 // The next deploy_next retries the same row: the copy succeeds and only fresh bytes are applied.
 const again=w.deployNext('f2');assert.equal(again.result,'child_attached');
 assert.equal(w.mt5.applied.length,1);assert.equal(w.mt5.applied[0].bytes,'<chart>fresh '+SETS+'\\set0');passed++;
}
{ // 10. Restart mid-attach: the old request stays "started" and is not re-run; at startup the stale
  //     template of the partial row is swept; a new request is refused before any chart or template.
 const templates=new Map([[orphanName,'<chart>STALE orphan']]);
 const a=world({members:3,templates,childStarts:false});
 a.setRequest('r');a.tick();
 assert.equal(a.log.receipts.get(a.root+'r.json').result,'started');assert.equal(a.ctx.m_agent_attach_pending,true);
 assert.ok(templates.has(staleName),'the copied template is on disk when the dashboard stops');
 // The dashboard EA re-initialises: in-memory attach state is gone; the saved rows and the receipt remain.
 // Row 1 is a linked member from before (its template already gone); row 2 was never deployed.
 const rows=a.sets.map(s=>({...s,magic:0}));rows[1]={...rows[1],cid:66948585509999,magic:7777};
 templates.set(tplOf(2),'<chart>row 2, never deployed');
 const b=world({members:3,templates,rows});
 b.ctx.SweepStaleChildTemplates(); // LoadDashboardConfig calls it once the saved rows are read (asserted above)
 assert.ok(!templates.has(staleName),'the partial row\'s stale template is removed at startup');
 assert.deepEqual(b.log.phases.map(p=>[p.phase,p.target]),[['stale_template_removed',rows[0].cid]]);
 assert.equal(templates.get(tplOf(2)),'<chart>row 2, never deployed','rows without a chart ID are not swept');
 assert.equal(templates.get(orphanName),'<chart>STALE orphan','files of no row are not touched');
 b.log.receipts.set(b.root+'r.json',{id:'r',result:'started'});
 b.setRequest('r');b.tick();b.tick();
 assert.equal(b.log.receipts.get(b.root+'r.json').result,'started','a request with a receipt is never re-executed');
 assert.equal(b.mt5.charts.size,0);
 assert.equal(b.deployNext('n').result,'rejected_partial_deployment');
 assert.equal(b.mt5.charts.size,0);assert.equal(b.mt5.applied.length,0,'nothing is queued by the new session');passed++;
}
// Late registration (Mac 6028209095): a child's OnInit can spend up to a minute on its license check.
for(const [delay,label] of [[25000,'25 s, after the old 20 s budget'],[70000,'70 s, just inside the agent budget']]) {
 // 11/12. A child that registers late but within the budget is linked; the receipt says child_attached.
 const w=world({members:2,childDelay:delay});
 const r=w.deployNext('late');assert.equal(r.result,'child_attached',label);
 assert.ok(r.ticks>delay/1000&&r.ticks<=BUDGET/1000,`${label}: ${r.ticks} ticks`);
 assert.ok(w.linked(0),label);assert.equal(w.mt5.templates.size,0);assert.ok(!w.ctx.IsAgentAttachFailedChart(w.sets[0].cid));passed++;
}
{ // 13. A child that would register after the budget: the chart is closed at the timeout, so the child
  //     never finishes OnInit, never reports, and the row never links while the receipt says failed.
 const w=world({members:2,childDelay:BUDGET+5000});
 const r=w.deployNext('slow');assert.equal(r.result,'child_attach_failed');
 const cid=w.sets[0].cid;assert.equal(w.mt5.charts.get(cid).closed,true);
 for(let t=0;t<15;t++) w.tick();
 assert.equal(w.mt5.children.length,0,'no child runs on the closed chart');
 assert.equal(w.sets[0].magic,FAILED);assert.ok(!w.linked(0));assert.equal(w.sets[0].cid,cid,'the lock stays');
 assert.equal(w.log.saved[0].magic,FAILED,'the failed marker is saved');
 assert.equal(w.deployNext('after').result,'rejected_partial_deployment');passed++;
}
{ // 14. Same, but the chart cannot be closed: the late child starts and reports status; the dashboard
  //     ignores it for the failed row, which stays unlinked and keeps refusing further deploys.
 const w=world({members:2,childDelay:BUDGET+5000,closeOk:false});
 const r=w.deployNext('stuck');assert.equal(r.result,'child_attach_failed');
 const cid=w.sets[0].cid;assert.equal(w.log.phases.at(-2).phase,'child_chart_close_failed');
 assert.ok(w.ctx.IsAgentAttachFailedChart(cid));
 for(let t=0;t<15;t++) w.tick();
 assert.equal(w.mt5.children.length,1,'the late child is running on the unclosed chart');
 assert.equal(w.sets[0].magic,FAILED,'its status event does not adopt it');assert.equal(w.sets[0].status,'Pending');
 assert.ok(!w.linked(0),'a failed row never becomes a live member');
 assert.equal(w.deployNext('after').result,'rejected_partial_deployment');passed++;
}
{ // 15. A child that reports status during the attach but never completes the handshake: its early
  //     magic is replaced by the failed marker at the timeout, so the saved row cannot reload as Linked.
 const w=world({members:1,registers:false,closeOk:false});
 w.setRequest('h');w.tick();w.tick();w.tick();
 assert.ok(w.sets[0].magic>0,'the status event adopted the magic early, before any handshake');
 const r=w.deployNext('h');assert.equal(r.result,'child_attach_failed');
 assert.equal(w.sets[0].magic,FAILED);assert.ok(w.sets[0].cid>0);
 for(let t=0;t<5;t++) w.tick();
 assert.equal(w.sets[0].magic,FAILED);assert.ok(!w.linked(0));assert.equal(w.log.saved[0].magic,FAILED);passed++;
}
{ // 16. Inertness is re-checked when the attach settles (Mac 6028472101). Algo Trading switched on, or a
  //     position opened, during the attach: the child registers, but it is unwound exactly like a timeout.
  //     The receipt says rejected_not_inert, the chart is closed, no child runs, and the row stays locked.
 for(const change of [m=>{m.algo=true;},m=>{m.positions=1;}]) {
  const w=world({members:2,childDelay:5000});
  w.setRequest('i');w.tick();const cid=w.sets[0].cid;change(w.mt5);
  const r=w.deployNext('i');assert.equal(r.result,'rejected_not_inert');
  assert.equal(w.ctx.GoatPortfolioAttachPending,false);assert.equal(w.ctx.m_agent_attach_pending,false);
  assert.equal(w.mt5.charts.get(cid).closed,true,'the child chart is closed');
  assert.equal(w.mt5.children.length,0,'no child is running');
  for(let t=0;t<5;t++) w.tick();
  assert.equal(w.mt5.children.length,0);assert.ok(!w.linked(0),'the row is not linked');
  assert.equal(w.sets[0].magic,FAILED);assert.equal(w.sets[0].cid,cid,'the lock stays');assert.equal(w.sets[0].status,'Pending');
  assert.equal(w.log.saved[0].magic,FAILED);assert.equal(w.mt5.templates.size,0);
  assert.deepEqual(w.log.audits.map(a=>a[1]),['PREPARED','APPLY_FAILED']);
  assert.deepEqual(w.log.phases.slice(-3).map(p=>[p.phase,p.control]),[['attach_not_inert',''],['child_chart_closed',''],['child_attach_failed','not_inert']]);
 }
 const w=world({members:2,childDelay:5000});
 assert.equal(w.deployNext('ok').result,'child_attached');passed++;
}
{ // 17. Restart after a failed attach whose chart could not be closed (Mac 6028472101 item 3): MT5
  //     restores the chart with its child. The saved marker survives, so on load the chart is closed
  //     again and the child's status never adopts the row.
 const a=world({members:2,childDelay:BUDGET+5000,closeOk:false});
 assert.equal(a.deployNext('x').result,'child_attach_failed');
 for(let t=0;t<10;t++) a.tick();
 const cid=a.sets[0].cid;assert.equal(a.mt5.children.length,1,'the child runs on the unclosable chart');
 const rows=a.log.saved.map(s=>({...s}));assert.equal(rows[0].magic,FAILED);
 // The terminal restarts: the profile restores that chart with its child; the saved rows reload.
 const b=world({members:2,rows,restored:[{cid,sym:rows[0].sym,child:true}]});
 assert.equal(b.mt5.children.length,1);
 b.ctx.SweepStaleChildTemplates(); // LoadDashboardConfig calls it once the saved rows are read
 assert.equal(b.mt5.charts.get(cid).closed,true,'the restored failed chart is closed on load');
 assert.equal(b.mt5.children.length,0,'its child is unloaded');
 for(let t=0;t<5;t++) b.tick();
 assert.equal(b.sets[0].magic,FAILED);assert.ok(!b.linked(0));
 // If the restored chart cannot be closed either, its child still never adopts the row.
 const c=world({members:2,rows:a.log.saved.map(s=>({...s})),restored:[{cid,sym:rows[0].sym,child:true}],closeOk:false});
 c.ctx.SweepStaleChildTemplates();
 assert.equal(c.log.phases.at(-1).phase,'child_chart_close_failed');
 for(let t=0;t<5;t++) c.tick();
 assert.equal(c.mt5.children.length,1);assert.equal(c.sets[0].magic,FAILED,'a restored child never adopts a failed row');
 assert.ok(!c.linked(0));assert.equal(c.deployNext('y').result,'rejected_partial_deployment');
 // A chart ID that now names another symbol's chart is never closed.
 const d=world({members:2,rows:a.log.saved.map(s=>({...s})),restored:[{cid,sym:'OTHER',child:false}]});
 d.ctx.SweepStaleChildTemplates();
 assert.equal(d.mt5.charts.get(cid).closed,false);assert.equal(d.log.phases.at(-1).phase,'child_chart_not_found');passed++;
}
console.log(JSON.stringify({passed,productionExtracted:true,nativeTemplateTimingVerified:false}));