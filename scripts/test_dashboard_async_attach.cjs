// Execute the production agent attach path (Dashboard.mqh + GOATPortfolioSetupControl.mqh)
// against a modelled MT5 in which ChartApplyTemplate only queues the template and the queue
// is processed after the requesting event handler returns (goatai#1885 6027754245).
// This is source-control-flow verification, not native MT5 evidence: it proves the
// state machine completes and unwinds, not when a real terminal applies a template.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const read=f=>fs.readFileSync(path.join(__dirname,'..',f),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const dashboard=read('Dashboard.mqh'),setup=read('GOATPortfolioSetupControl.mqh');

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
  .replace(/\b(?:const )?(?:string|int|long|bool|uint|double|ENUM_TIMEFRAMES) (?=[A-Za-z_]\w*\s*[=;,])/g,'let ')
  .replace(/\((?:long|datetime)\)/g,'').replace(/__FUNCTION__/g,'"fn"')
  .replace(/StringReplace\(tplName,"\.set","\.tpl"\)/g,'tplName=tplName.split(".set").join(".tpl")')
  .replace(/GoatFindMagicByCid\(([^,]+),([^,]+),(\w+)\)/g,'find($1,$2,v=>$3=v)')
  .replace(/GlobalVariableGet\((GoatChildGVName\([^\n]+?\)|pending),(\w+)\)/g,'gvGet($1,v=>$2=v)')
  .replace(/g_sets\[idx\]\.cid\/1000000000/g,'Math.trunc(g_sets[idx].cid/1000000000)');
}
const method=name=>bodyOf(dashboard,'CGOATDashboard::'+name);
const prepareCall='bool started=PrepareChildLaunch(idx,tf,tplName);';
const beginBody=method('AgentBeginDeployRow(const int idx)');assert.ok(beginBody.includes(prepareCall));
const deployBlock=bodyOf(setup,'else if(action=="deploy_next")');
const deferReturn='FileClose(owner);\n            return;';assert.ok(deployBlock.includes(deferReturn));
// The poll's first statement after building root: settle an in-flight attach or hold every request.
const pollBody=bodyOf(setup,'void GoatPortfolioSetupPoll(void)');
const holdLine=pollBody.split('\n').find(l=>l.includes('GoatPortfolioAttachContinue(root)'));assert.ok(holdLine,'poll must settle an in-flight attach first');
assert.ok(pollBody.indexOf(holdLine)<pollBody.indexOf('registration.json'),'the attach settles before any request is read');
const production=[
 'function PrepareChildLaunch(idx){let tf,tplName;const ok=(()=>{'+js(bodyOf(dashboard,'bool PrepareChildLaunch(const int idx,ENUM_TIMEFRAMES &tf,string &tplName)'))+'})();return {ok,tf,tplName};}',
 'function AgentBeginDeployRow(idx){'+js(beginBody).replace(js(prepareCall),'const p=PrepareChildLaunch(idx);let started=p.ok;tf=p.tf;tplName=p.tplName;')+'}',
 'function AgentPollDeployRow(){'+js(method('AgentPollDeployRow(void)'))+'}',
 'function BeginChildAttach(idx,tf,tplName){'+js(method('BeginChildAttach(const int idx,ENUM_TIMEFRAMES tf,const string tplName)'))+'}',
 'function ApplyTemplate(idx,tf,tplName){'+js(method('ApplyTemplate(const int idx,ENUM_TIMEFRAMES tf,const string tplName)'))+'}',
 'function FailChildAttachTimeout(idx,tplName){'+js(method('FailChildAttachTimeout(const int idx,const string tplName)'))+'}',
 'function CompleteChildAttach(idx,tplName){'+js(method('CompleteChildAttach(const int idx,const string tplName)'))+'}',
 'function NewSingleInstance(idx){'+js(method('NewSingleInstance(const int idx)'))+'}',
 'function GoatPortfolioAttachContinue(root){'+js(bodyOf(setup,'bool GoatPortfolioAttachContinue(const string root)'))+'}',
 'function settleOrHold(root){'+js(holdLine).replace(/return;/,'return true;')+'\nreturn false;}',
 'function deployNext(count,id,hash,owner){let result="started";'+js(deployBlock).replace(js(deferReturn),'FileClose(owner);return "pending";')+'\nreturn result;}',
].join('\n');

const control=()=>({t:'',Text(v){if(v===undefined)return this.t;this.t=v;},Color(){}});
function world({members=35,applies='afterHandler',childStarts=true,enqueueOk=true}={}) {
 const mt5={clock:1000,nextCid:66948585504739,charts:new Map(),queue:[],templates:new Set(),gv:new Map(),cidField:new Map(),children:[]};
 const sets=[...Array(members)].map((_,i)=>({name:`GOAT V1.49 SYM${i},M1_B35-${i}.set`,path:`C:\\set${i}`,sym:'SYM'+(i%17),cid:0,magic:0,status:'Pending'}));
 const log={phases:[],audits:[],receipts:new Map(),saves:0,ownerBusy:false,writeOk:true};
 const startChild=(chart)=>{
  const magic=7000+mt5.children.length;
  // OnInit: the child records its chart and its pending registration.
  mt5.cidField.set(chart.cid,magic);mt5.gv.set(`${magic}/${chart.sym}/Magic`,magic);
  mt5.children.push({cid:chart.cid,sym:chart.sym,magic,timerSeen:false});chart.expert=true;
 };
 const processQueue=()=>{ // MT5 drains chart command queues once the handler has returned
  for(const cmd of mt5.queue.splice(0)) {
   const chart=mt5.charts.get(cmd.cid);
   if(!mt5.templates.has(cmd.tpl)) {chart.missingTemplate=true;continue;}
   if(childStarts) startChild(chart);
  }
 };
 const ctx={
  g_sets:sets,edt_Status:[...Array(members+2)].map(control),btn_Action:[...Array(members+2)].map(control),
  EA_Path:'Experts\\GOAT-EA\\GOAT V1.49.ex5',EA_Name_:'GOAT V1.49',ChartId:1,PERIOD_M1:1,
  m_agent_setup_quiet:false,m_agent_attach_pending:false,m_agent_attach_idx:-1,m_agent_attach_tpl:'',m_agent_attach_start:0,m_child_attach_step:'',
  GoatPortfolioAttachPending:false,GoatPortfolioAttachId:'',GoatPortfolioAttachHash:'',GoatPortfolioAttachResult:'',
  ACCOUNT_TRADE_MODE:1,ACCOUNT_TRADE_MODE_DEMO:0,TERMINAL_CONNECTED:2,TERMINAL_TRADE_ALLOWED:3,CHART_BRING_TO_TOP:4,
  MB_OK:0,MB_ICONWARNING:0,FILE_READ:1,FILE_WRITE:2,FILE_BIN:4,FILE_COMMON:8,INVALID_HANDLE:-1,GOAT_GV_FIELD_MAGIC:'Magic',
  AccountInfoInteger:()=>0,TerminalInfoInteger:k=>k===2?1:0,PositionsTotal:()=>0,OrdersTotal:()=>0,
  ArraySize:a=>a.length,StringFind:(s,f)=>s.indexOf(f),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  EndsWith:(s,x)=>s.endsWith(x),TF:()=>1,StringFormat:(f,...a)=>a.join(' '),
  Print:()=>{},PrintFormat:()=>{},Alert:()=>{},MessageBox:()=>{throw new Error('agent path must not prompt');},
  ResetLastError:()=>{},GetLastError:()=>0,MarkStateDirty:()=>{},StatusColor:()=>0,UpdateAILaunchControls:()=>{},
  PrepareAILaunchPolicy:()=>true,BuildTemplate:()=>'<chart>',
  SaveTemplateAndCopy:name=>{mt5.templates.add(name);return true;},
  DeleteCopiedTemplate:name=>mt5.templates.delete(name),
  SaveDashboardConfig:()=>{log.saves++;return true;},
  AppendAILaunchAudit:(idx,stage)=>log.audits.push([idx,stage]),
  GoatDeploymentPhase:(phase,target=0,controlName='')=>log.phases.push({phase,target,control:controlName}),
  GetTickCount:()=>mt5.clock,Sleep:ms=>{mt5.clock+=ms;},
  ChartOpen:(sym)=>{const cid=mt5.nextCid++;mt5.charts.set(cid,{cid,sym,expert:false});return cid;},
  ChartApplyTemplate:(cid,tpl)=>{if(!enqueueOk)return false;mt5.queue.push({cid,tpl});if(applies==='immediately')processQueue();return true;},
  ChartClose:()=>true,ChartRedraw:()=>{},ChartSetInteger:()=>true,
  GoatChildGVName:(m,s,f)=>`${m}/${s}/${f}`,
  find:(sym,cid,assign)=>{if(!mt5.cidField.has(cid))return false;assign(mt5.cidField.get(cid));return true;},
  gvGet:(key,assign)=>{if(!mt5.gv.has(key))return false;assign(mt5.gv.get(key));return true;},
  GlobalVariableDel:key=>mt5.gv.delete(key),GlobalVariablesFlush:()=>{},
  FileOpen:()=>log.ownerBusy?-1:5,FileClose:()=>{},
  GoatSetupWrite:(file,body)=>{if(!log.writeOk)return false;log.receipts.set(file,body);return true;},
  GoatPortfolioSnapshot:(id,action,hash,result)=>({id,action,hash,result}),
  GoatPortfolioRowLinked:i=>sets[i].cid>0&&sets[i].magic>0&&mt5.children.some(c=>c.cid===sets[i].cid&&c.timerSeen),
 };
 vm.createContext(ctx);vm.runInContext(production,ctx);
 vm.runInContext('var DashboardDialog={g_sets,AgentBeginDeployRow,AgentPollDeployRow};',ctx);
 const root='GOAT\\AgentPortfolio\\T3\\';let request=null;const setRequest=id=>{request=id;};
 const tick=()=>{ // one second: child timers, then the dashboard's OnTimer, then the queue drains
  mt5.clock+=1000;
  for(const c of mt5.children){c.timerSeen=true;
   mt5.gv.set(`${c.magic}/${c.sym}/SETUP_CID_HI`,Math.trunc(c.cid/1e9));mt5.gv.set(`${c.magic}/${c.sym}/SETUP_CID_LO`,c.cid%1e9);}
  // Mirrors GoatPortfolioSetupPoll: settle an in-flight attach, else read one request.
  if(!ctx.settleOrHold(root)&&request&&!log.receipts.has(root+request+'.json')) {
   const id=request,file=root+id+'.json';
   log.receipts.set(file,{id,result:'started'});
   const result=ctx.deployNext(members,id,'hash',5);
   if(result!=='pending') log.receipts.set(file,{id,result});
  }
  processQueue();
 };
 const deployNext=(id,maxTicks=40)=>{
  request=id;const file=root+id+'.json';
  for(let t=1;t<=maxTicks;t++){tick();const r=log.receipts.get(file);if(r&&r.result!=='started')return {result:r.result,ticks:t};}
  return {result:'receipt_timeout',ticks:maxTicks};
 };
 return {ctx,mt5,sets,log,tick,deployNext,setRequest,root};
}

let passed=0;
{ // 1. The B41 shape (wait inside the handler) reproduces T3: no child, template gone, chart left bare.
 const w=world({members:1});w.ctx.m_agent_setup_quiet=true;
 const tpl='GOAT V1.49 SYM0,M1_B35-0.tpl';w.mt5.templates.add(tpl);
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
  assert.equal(w.sets[i].status,'Linked');assert.ok(w.sets[i].cid>0&&w.sets[i].magic>0);
  assert.equal(w.ctx.m_agent_attach_pending,false);assert.equal(w.ctx.GoatPortfolioAttachPending,false);
 }
 assert.equal(new Set(w.sets.map(s=>s.magic)).size,35);assert.equal(new Set(w.sets.map(s=>s.cid)).size,35);
 assert.equal(w.mt5.templates.size,0,'every copied template is removed after linking');
 assert.equal(w.log.audits.filter(a=>a[1]==='LINKED').length,35);assert.equal(w.log.audits.filter(a=>a[1]==='APPLY_FAILED').length,0);
 assert.equal(w.deployNext('req-final').result,'all_attached');passed++;
}
{ // 3. The template is still on disk when MT5 drains the queue (it is deleted only after linking).
 const w=world({members:2});
 w.deployNext('a');const linked=w.log.phases.findIndex(p=>p.phase==='handshake_linked');
 assert.ok(linked>0);assert.equal([...w.mt5.charts.values()][0].missingTemplate,undefined);passed++;
}
{ // 4. Timeout unwinds cleanly: child never registers, 20 s budget on timer ticks, step named.
 const w=world({members:3,childStarts:false});
 const r=w.deployNext('t');assert.equal(r.result,'child_attach_failed');assert.ok(r.ticks>=20&&r.ticks<=22,`ticks ${r.ticks}`);
 assert.equal(w.mt5.templates.size,0);assert.equal(w.sets[0].status,'Pending');
 assert.ok(w.sets[0].cid>0,'the chart identity stays persisted as a partial-deployment lock');
 assert.equal(w.ctx.m_agent_attach_pending,false);assert.equal(w.ctx.GoatPortfolioAttachPending,false);
 assert.deepEqual(w.log.audits.map(a=>a[1]),['PREPARED','APPLY_FAILED']);
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
}console.log(JSON.stringify({passed,productionExtracted:true,nativeTemplateTimingVerified:false}));
