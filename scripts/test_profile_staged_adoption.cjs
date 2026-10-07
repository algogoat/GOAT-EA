// Profile-staged deploy (beta.25, goatai#1885 6033450916): execute the production adoption pass,
// AdoptChild, the link_children/deploy_next dispatch, the receipt row identity and the disabled
// dashboard buttons, after a syntax-only MQL-to-JS conversion, against a modelled terminal (charts,
// CID records, saved-template snapshots, inert state). Source checks pin the retired template path.
// This is decision-level evidence: native ChartSaveTemplate, profile loading and MT5 chart ids are
// proven on T3 (P1-P7), not here. GoatChildAuditMaps itself is covered by test_portfolio_child_audit.cjs.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const FILES={setup:'GOATPortfolioSetupControl.mqh',dashboard:'Dashboard.mqh',audit:'GOATPortfolioChildAudit.mqh',main:'GOAT V1.49.mq5'};
const MESSAGE='Use Next in the app to deploy; dashboard deploy returns in the next update';

function readSources(){
 const out={};for(const [k,f] of Object.entries(FILES)) out[k]=fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
 return out;
}
function region(text,start,end){
 const a=text.indexOf(start);assert.ok(a>=0,'missing '+start);
 const b=text.indexOf(end,a+start.length);assert.ok(b>a,'missing '+end);
 return text.slice(a,b);
}
function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 let i=text.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<text.length;j++){if(text[j]==='{')depth++;if(text[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
// #ifdef GOAT_DASH_AI_LAUNCH_POLICY_V147 is defined in V1.49; every other #if block is dropped.
function enabled(text){
 const stack=[];let active=true;
 return text.split('\n').filter(line=>{
  if(/^\s*#ifdef/.test(line)){stack.push(active);active=active&&line.includes('GOAT_DASH_AI_LAUNCH_POLICY_V147');return false;}
  if(/^\s*#else/.test(line)){active=stack.at(-1)&&!active;return false;}
  if(/^\s*#endif/.test(line)){active=stack.pop();return false;}
  return active&&!/^\s*#/.test(line);
 }).join('\n');
}
const TYPES='(?:const )?(?:string|int|long|bool|ushort|datetime|double|ulong|color|ENUM_TIMEFRAMES)';
function js(text){
 return enabled(text)
  .replace(/'([^'\\])'/g,(_,c)=>String(c.charCodeAt(0)))
  .replace(new RegExp('\\b'+TYPES+' ','g'),'let ')
  .replace(/\b(\w+)\[\](?=[,;])/g,'$1=[]')
  .replace(/\((?:long|int|double|ulong|datetime)\)/g,'')
  // By-reference outputs become setter callbacks.
  .replace(/GoatFindMagicByCid\(([^,()]+),([^,()]+),(\w+)\)/g,'GoatFindMagicByCid($1,$2,v=>$3=v)')
  .replace(/GoatChildChartSnapshot\(([^,()]+),(\w+)\)/g,'GoatChildChartSnapshot($1,v=>$2=v)')
  .replace(/GoatChildSetSource\(([^,()]+),([^,()]+),(\w+)\)/g,'GoatChildSetSource($1,$2,v=>$3=v)')
  .replace(/(?<!function )GoatAdoptChartFits\(([^,()]+),([^,()]+),(\w+)\)/g,'GoatAdoptChartFits($1,$2,v=>$3=v)');
}
// Free functions and globals of the adoption section, converted. The &adopt_magic output of
// GoatAdoptChartFits is a setter in JS.
function adoptionScript(setup){
 const section=region(setup,'// ---- Profile-staged deploy','string GoatPortfolioSnapshot(');
 const defines={};for(const m of section.matchAll(/^#define\s+(\w+)\s+(.+)$/gm)) defines[m[1]]=Number(m[2]);
 let code=section.replace(/^(?:datetime|string)\s+(Goat\w+)(\[\])?(?:=([^;]+))?;$/gm,(_,n,arr,v)=>'var '+n+'='+(arr?'[]':(v??'0'))+';');
 code=code.replace(/^(?:ENUM_TIMEFRAMES|bool|void|int|string) (Goat\w+)\(([^)]*)\)\n\{/gm,(_,name,args)=>
  'function '+name+'('+args.split(',').map(a=>a.trim().replace(/^.*?(\w+)(\[\])?$/,'$1')).filter(a=>a&&a!=='void').join(',')+')\n{');
 code=js(code);
 // Only GoatAdoptChartFits receives adopt_magic as an output; elsewhere it is a local.
 const start=code.indexOf('function GoatAdoptChartFits(');assert.ok(start>=0);
 const end=code.indexOf('\nfunction ',start+10);
 const fits=code.slice(start,end).replace(/\badopt_magic=([^;]+);/g,'adopt_magic($1);');
 assert.equal((fits.match(/adopt_magic\(/g)||[]).length,2,'GoatAdoptChartFits writes its output twice');
 return {code:code.slice(0,start)+fits+code.slice(end),defines};
}
const PERIOD={PERIOD_CURRENT:0,PERIOD_M1:1,PERIOD_M5:5,PERIOD_M15:15,PERIOD_M30:30,PERIOD_H1:16385,PERIOD_H4:16388,PERIOD_D1:16408};

// A modelled terminal: the dashboard chart (id 1) and child charts loaded from a profile.
function terminal(src,{rows,charts,algo=false,positions=0,saveOk=true,clock=1000}){
 const notes=[],saves=[],snapshots=[],deleted=[],audits=[],sourcesRead=[];
 const all=[{id:1,sym:'EURUSD',period:1,expert:'GOAT V1.49',magic:0,snapshot:''},...charts];
 const g_sets=rows.map(r=>({cid:0,magic:0,status:'Pending',...r}));
 const ctx={...PERIOD,ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},StringFind:(s,t)=>s.indexOf(t),StringLen:s=>s.length,
  StringGetCharacter:(s,i)=>s.charCodeAt(i),ShortToString:c=>String.fromCharCode(c),IntegerToString:String,
  Mode_Operation:8,Operation_Dash:8,MQL_TESTER:1,MQLInfoInteger:()=>0,ACCOUNT_TRADE_MODE:1,ACCOUNT_TRADE_MODE_DEMO:0,AccountInfoInteger:()=>0,
  TERMINAL_CONNECTED:1,TERMINAL_TRADE_ALLOWED:2,TerminalInfoInteger:k=>k===1?1:(algo?1:0),PositionsTotal:()=>positions,OrdersTotal:()=>0,
  TimeGMT:()=>ctx.now,now:clock,ChartID:()=>1,
  ChartFirst:()=>all[0].id,ChartNext:id=>{const i=all.findIndex(c=>c.id===id);return i>=0&&i+1<all.length?all[i+1].id:-1;},
  ChartSymbol:id=>all.find(c=>c.id===id)?.sym??'',ChartPeriod:id=>all.find(c=>c.id===id)?.period??0,
  CHART_EXPERT_NAME:'expert',ChartGetString:(id,p)=>{assert.equal(p,'expert');return all.find(c=>c.id===id)?.expert??'';},
  GoatFindMagicByCid:(sym,id,set)=>{const c=all.find(x=>x.id===id&&(x.recordSym??x.sym)===sym);if(!c||!c.magic)return false;set(c.magic);return true;},
  GoatChildSetSource:(p,hash,set)=>{sourcesRead.push([p,hash]);const r=g_sets.find(x=>x.path===p);if(!r||hash!=='sha-'+r.path)return false;set(r.set);return true;},
  GoatChildChartSnapshot:(id,set)=>{snapshots.push(id);const c=all.find(x=>x.id===id);if(!c||!c.snapshot)return false;set(c.snapshot);return true;},
  GoatChildSnapshotMatchesSet:(source,snapshot)=>source!==''&&source===snapshot,
  GoatDeploymentPhase:(phase,target,detail)=>notes.push([phase,target,detail??'']),
  // AdoptChild's environment (the production method runs below with these as members).
  g_sets,edt_Status:[],btn_Action:[],SaveDashboardConfig:()=>{saves.push(g_sets.map(r=>[r.cid,r.magic]));return saveOk;},
  GlobalVariableDel:k=>deleted.push(k),GlobalVariablesFlush:()=>{},GoatChildGVName:(m,s,f)=>`${m}_${s}_${f}`,GOAT_GV_FIELD_MAGIC:'Magic',
  StatusColor:()=>0,AppendAILaunchAudit:(i,stage)=>audits.push([i,stage]),UpdateAILaunchControls:()=>{}};
 ctx.DashboardDialog={g_sets,EA_Name_:'GOAT V1.49',m_ai_launch_mode:2,m_ai_launch_threshold:50,m_ai_launch_protocol:2};
 vm.createContext(ctx);
 const {code,defines}=adoptionScript(src.setup);Object.assign(ctx,defines);
 vm.runInContext(code,ctx);
 const adopt=bodyOf(src.dashboard,'bool CGOATDashboard::AdoptChild(const int adopt_idx,const long adopt_chart,const long adopt_magic)');
 ctx.DashboardDialog.AdoptChild=vm.runInContext('(function(adopt_idx,adopt_chart,adopt_magic){'+js(adopt)+'})',ctx);
 const hashes=g_sets.map(r=>'sha-'+r.path);
 return {ctx,g_sets,notes,saves,snapshots,deleted,audits,sourcesRead,pass:(h=hashes)=>ctx.GoatPortfolioAdoptChildren(h)};
}
const row=(i,sym='EURUSD',tf='M1',set='Risk=500\nMode_Bias=2\n')=>({path:`C:\\Common\\Files\\GOAT\\set${i}.set`,name:`GOAT V1.49 ${sym},${tf}_B${i}.set`,sym,set});
const child=(id,r,over={})=>({id,sym:r.sym,period:PERIOD['PERIOD_'+(r.name.match(/,([A-Z0-9]+)_/)[1])],expert:'GOAT V1.49',magic:9000+id,snapshot:r.set,...over});

function run(src=readSources()){
 let passed=0;const ok=()=>passed++;
 // ---- adoption: cid first, fallback, missing, mismatch, identity guards ----
 {const r=[row(1)];r[0].cid=501;const t=terminal(src,{rows:r,charts:[child(501,r[0]),child(502,r[0])]});
  assert.equal(t.pass(),1);assert.deepEqual([t.g_sets[0].cid,t.g_sets[0].magic],[501,9501],'cid first adopts the TSV chart id');
  assert.deepEqual(t.snapshots,[501],'only the hinted chart is fingerprinted');assert.equal(t.g_sets[0].status,'Linked');
  assert.deepEqual(t.deleted,['9501_EURUSD_Magic']);assert.deepEqual(t.audits,[[0,'ADOPTED']]);ok();}
 {const r=[row(1)];r[0].cid=777;const t=terminal(src,{rows:r,charts:[child(502,r[0])]});
  assert.equal(t.pass(),1);assert.deepEqual([t.g_sets[0].cid,t.g_sets[0].magic],[502,9502],'a stale cid falls back to matching');ok();}
 {const r=[row(1),row(2,'USDJPY','M15'),row(3,'XAUUSD','H1')];
  const t=terminal(src,{rows:r,charts:[child(503,r[2]),child(501,r[0]),child(502,r[1])]});
  assert.equal(t.pass(),3);assert.deepEqual(t.g_sets.map(x=>[x.cid,x.magic]),[[501,9501],[502,9502],[503,9503]],'fallback match, any chart order');
  assert.deepEqual([...t.snapshots].sort(),[501,502,503],'each chart fingerprinted once');
  assert.deepEqual(t.sourcesRead.map(x=>x[1]),r.map(x=>'sha-'+x.path),'each SET read once at its registered sha256');
  assert.equal(t.pass(),0,'a second pass adopts nothing twice');assert.equal(t.saves.length,3);ok();}
 {const r=[row(1),row(2,'USDJPY')];const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  assert.equal(t.pass(),1);assert.deepEqual([t.g_sets[1].cid,t.g_sets[1].magic,t.g_sets[1].status],[0,0,'Pending'],'missing child stays pending in the window');
  t.ctx.now+=240;t.pass();assert.equal(t.g_sets[1].status,'Pending','240 s is still inside the window');
  t.ctx.now+=1;t.pass();assert.equal(t.g_sets[1].status,'Not started');
  assert.ok(t.notes.some(n=>n[0]==='child_not_started'&&n[2]==='USDJPY row=1'),'child_not_started is named per row');
  assert.ok(!t.notes.some(n=>n[0]==='child_not_started'&&n[2].includes('row=0')));ok();}
 {const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0],{snapshot:'Risk=900\nMode_Bias=2\n'})]});
  assert.equal(t.pass(),0);assert.deepEqual([t.g_sets[0].cid,t.g_sets[0].magic],[0,0],'settingsMatch mismatch is never adopted');
  assert.ok(t.notes.some(n=>n[0]==='child_unmatched'&&n[1]===501&&n[2]==='EURUSD'));ok();}
 {const r=[row(1)];r[0].cid=501;const t=terminal(src,{rows:r,charts:[child(501,r[0],{snapshot:'Risk=900\n'})]});
  assert.equal(t.pass(),0,'a hinted chart must also match settings');assert.equal(t.g_sets[0].magic,0);ok();}
 for(const [label,over] of [['period mismatch',{period:5}],['another EA',{expert:'GOAT V1.48'}],['no CID record',{magic:0}],['other symbol',{sym:'GBPUSD',recordSym:'EURUSD'}]]){
  // recordSym: a chart switched to another symbol keeps its old CID record (the GV name holds the symbol).
  const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0],over)]});
  assert.equal(t.pass(),0,label);assert.equal(t.g_sets[0].magic,0,label);assert.deepEqual(t.snapshots,[],label+': rejected before any snapshot');ok();
 }
 {const r=[row(1,'EURUSD','M15')];const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  assert.equal(t.g_sets.length,1);assert.equal(t.pass(),1,'M15 is read as M15, not its first two characters');ok();}
 for(const tf of ['M2','W1','MN1','M1X']){
  const r=[row(1,'EURUSD',tf)];const t=terminal(src,{rows:r,charts:[{id:501,sym:'EURUSD',period:1,expert:'GOAT V1.49',magic:9501,snapshot:r[0].set}]});
  assert.equal(t.pass(),0,'unknown period token '+tf);ok();
 }
 {const r=[row(1),row(2,'USDJPY')];r[1].magic=9501;r[1].cid=600;
  const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  assert.equal(t.pass(),0,'a magic another row holds is never adopted');assert.equal(t.g_sets[0].magic,0);assert.deepEqual(t.snapshots,[]);ok();}
 {const r=[row(1),row(2,'USDJPY')];r[1].magic=9600;r[1].cid=501;
  const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  assert.equal(t.pass(),0,'a chart another row claims is never adopted');assert.deepEqual(t.snapshots,[]);ok();}
 {const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0]),child(502,r[0])]});
  assert.equal(t.pass(),0,'two matching charts for one row');assert.equal(t.g_sets[0].magic,0);
  assert.ok(t.notes.some(n=>n[0]==='child_identity_ambiguous'));ok();}
 {const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  t.ctx.ChartID=()=>501;assert.equal(t.pass(),0,'the dashboard chart itself is never a child');assert.deepEqual(t.snapshots,[]);ok();}
 for(const state of [{algo:true},{positions:1}]){
  const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0])],...state});
  assert.equal(t.pass(),0,'not inert: '+JSON.stringify(state));assert.deepEqual(t.snapshots,[]);assert.equal(t.saves.length,0);ok();
 }
 {const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0])],saveOk:false});
  assert.equal(t.pass(),0);assert.deepEqual([t.g_sets[0].cid,t.g_sets[0].magic],[0,0],'an unsaved identity never counts');
  assert.deepEqual(t.deleted,[]);ok();}
 {const r=[row(1)];const t=terminal(src,{rows:r,charts:[child(501,r[0])]});
  assert.equal(t.pass(['sha-wrong']),0,'a SET that does not hash to the registration is never compared');ok();
  assert.equal(t.pass([]),0,'no registration hashes, no adoption');
  assert.equal(t.pass(['sha-'+r[0].path,'sha-extra']),0,'hashes for another member count, no adoption');ok();}
 {const r=[row(1,'EURUSD','M1','Risk=1\n'),row(2,'EURUSD','M1','Risk=2\n')];const t=terminal(src,{rows:r,charts:[child(501,r[0]),child(502,r[1])]});
  assert.equal(t.pass(),2,'two members on one symbol and period, told apart by their inputs');
  assert.deepEqual(t.g_sets.map(x=>x.cid),[501,502]);assert.deepEqual([...t.snapshots].sort(),[501,502],'a chart fitting two rows is fingerprinted once');ok();}
 {const r=[row(1),row(2,'USDJPY')];r[1].cid=502;r[1].magic=9502;
  const t=terminal(src,{rows:r,charts:[child(501,r[0]),child(502,r[1]),child(503,r[1])]});
  assert.equal(t.pass(),1);assert.ok(t.notes.some(n=>n[0]==='child_unmatched'&&n[1]===503),'a look-alike of a linked member is recorded');
  assert.ok(!t.notes.some(n=>n[1]===502));ok();}

 // ---- AdoptChild directly ----
 {const r=[row(1),row(2,'USDJPY')];r[1].cid=501;r[1].magic=0;const t=terminal(src,{rows:r,charts:[]});
  assert.equal(t.ctx.DashboardDialog.AdoptChild(0,501,9501),false,'chart claimed by another row');
  assert.equal(t.ctx.DashboardDialog.AdoptChild(0,0,9501),false);assert.equal(t.ctx.DashboardDialog.AdoptChild(0,601,0),false);
  assert.equal(t.ctx.DashboardDialog.AdoptChild(0,1,9501),false,'own chart');
  t.g_sets[1].magic=9700;assert.equal(t.ctx.DashboardDialog.AdoptChild(0,602,9700),false,'magic another row holds');t.g_sets[1].magic=0;
  assert.equal(t.ctx.DashboardDialog.AdoptChild(0,601,9601),true);assert.equal(t.ctx.DashboardDialog.AdoptChild(0,602,9602),false,'already adopted');ok();}

 // ---- link_children / deploy_next dispatch (the production block of GoatPortfolioSetupPoll) ----
 const dispatch=region(src.setup,'   bool inert=','   GoatSetupWrite(receipt,GoatPortfolioSnapshot(id,action,hash,result));');
 function poll(action,{inert=true,ai=2,linked=[true],matched=true}={}){
  const writes=[],calls=[];
  const c={action,matched,count:linked.length,receipt:'r.json',id:'x',hash:'h',ai,threshold:50,protocol:2,exposure:1,result:matched?'observed':'rejected_portfolio_mismatch',
   TERMINAL_CONNECTED:1,TERMINAL_TRADE_ALLOWED:2,TerminalInfoInteger:k=>k===1?1:(inert?0:1),PositionsTotal:()=>0,OrdersTotal:()=>0,
   GoatSetupWrite:(f,b)=>{writes.push(b);return true;},GoatPortfolioSnapshot:(i,a,h,res)=>res,FileClose:()=>{},owner:1,
   GoatPortfolioExpectedHashes:['sha'],GoatPortfolioAdoptChildren:h=>{calls.push('adopt');return 0;},GoatPortfolioRowLinked:i=>linked[i],
   DashboardDialog:{m_ai_launch_mode:2,m_ai_launch_threshold:50,m_ai_launch_protocol:2,
    AgentConfigureAI:()=>{calls.push('configure');return true;},AgentExposurePolicy:()=>{calls.push('policy');return true;}}};
  const result=vm.runInNewContext('(function(){'+js(dispatch)+'\nreturn result;})()',c);
  return {result,writes,calls};
 }
 for(const inert of [true,false]){
  const d=poll('deploy_next',{inert});assert.equal(d.result,'rejected_deploy_next_retired');assert.deepEqual(d.writes,[]);assert.deepEqual(d.calls,[],'deploy_next changes nothing');ok();
 }
 assert.equal(poll('deploy_next',{matched:false}).result,'rejected_portfolio_mismatch');ok();
 {const d=poll('link_children');assert.equal(d.result,'children_linked');assert.deepEqual(d.calls,['adopt']);assert.deepEqual(d.writes,['started'],'mutation-class: the intent receipt comes first (contract section 3)');ok();}
 {const d=poll('link_children',{linked:[true,false]});assert.equal(d.result,'children_pending');assert.deepEqual(d.writes,['started']);ok();}
 {const d=poll('link_children',{linked:[false,false,false]});assert.equal(d.result,'children_pending','never children_linked while any row is unlinked');ok();}
 {const d=poll('link_children',{inert:false});assert.equal(d.result,'rejected_not_inert');assert.deepEqual(d.calls,[],'no adoption unless inert');assert.deepEqual(d.writes,[]);ok();}
 {const d=poll('link_children',{ai:0});assert.equal(d.result,'rejected_ai_policy_mismatch');assert.deepEqual(d.calls,[]);assert.deepEqual(d.writes,['started']);ok();}
 {const d=poll('configure');assert.equal(d.result,'configured');assert.deepEqual(d.writes,['started']);ok();}
 {const d=poll('apply_policy');assert.equal(d.result,'policy_dispatched');assert.deepEqual(d.writes,['started']);assert.deepEqual(d.calls,['policy']);ok();}
 for(const a of ['status','audit']){const d=poll(a,{inert:false});assert.equal(d.result,a==='status'?'observed':'rejected_not_inert');assert.deepEqual(d.calls,[]);ok();}
 assert.match(src.setup,/action!="status" && action!="audit" && action!="configure" && action!="link_children"\n\s+&& action!="deploy_next" && action!="apply_policy"/);ok();

 // ---- receipt rows: an unadopted row reports chartId 0 and magic 0, fields unchanged ----
 {const snap=bodyOf(src.setup,'string GoatPortfolioSnapshot(const string id,const string action,const string hash,const string result)');
  const rows=[{cid:501,magic:0,sym:'EURUSD'},{cid:502,magic:9502,sym:'USDJPY'},{cid:-1,magic:-1,sym:'XAUUSD'}];
  const c={IntegerToString:String,ArraySize:a=>a.length,GoatSetupQuote:s=>JSON.stringify(s),GoatPortfolioRowLinked:i=>i===1,
   DashboardDialog:{g_sets:rows.map(r=>({...r,exposure_policy_mode:0,last_ack_id:0,last_ack_status:0})),ReadChildSnapshotIntoRow:()=>{},m_ai_launch_mode:2,m_ai_launch_threshold:50,m_ai_launch_protocol:2,m_portfolio_command_id:0,m_portfolio_command_pending:false},
   GoatPortfolioExpectedHashes:[],GoatPortfolioChildSettingsMatch:()=>true,GlobalVariableGet:()=>false,GoatChildGVName:()=>'',
   AccountInfoInteger:()=>1,AccountInfoString:()=>'s',TerminalInfoString:()=>'d',TerminalInfoInteger:()=>0,TimeGMT:()=>1,TimeCurrent:()=>1,
   PositionsTotal:()=>0,OrdersTotal:()=>0,GOAT_BUILD_ID:'b',ACCOUNT_LOGIN:1,ACCOUNT_SERVER:2,TERMINAL_DATA_PATH:3,TERMINAL_CONNECTED:4,TERMINAL_TRADE_ALLOWED:5};
  const receipt=JSON.parse(vm.runInNewContext('(function(id,action,hash,result){'+js(snap).replace(/let fields=\[\]=\{([^}]+)\};/,'let fields=[$1];').replace(/let fields\[\]=\{([^}]+)\};/,'let fields=[$1];')+'})',c)('i','link_children','h','children_pending'));
  assert.deepEqual(receipt.rows.map(r=>[r.chartId,r.magic,r.linkedFresh]),[[0,0,false],[502,9502,true],[0,0,false]]);
  assert.deepEqual(Object.keys(receipt.rows[0]),['index','symbol','chartId','magic','linkedFresh','exposureMode','ackId','ackStatus','settingsMatch',
   'AI_MODE','AI_PROTOCOL','AI_THRESHOLD','AI_SCOPE','AI_VERIFIED','AI_AVAILABLE','AI_AT','EA_TRADE_ALLOWED'],'row fields unchanged (controller ROW_FIELDS)');
  assert.deepEqual(Object.keys(receipt),['schema','id','action','registrationSha256','result','account','server','directory','buildId','observedAtUtc','brokerTime',
   'connected','tradingAllowed','positions','orders','aiMode','aiThreshold','aiProtocol','commandId','commandPending','rows'],'envelope unchanged');ok();}

 // ---- the human Activate / Deploy All buttons are disabled with the exact message ----
 {const m=src.dashboard.match(/#define GOAT_DASH_DEPLOY_RETIRED_MESSAGE "([^"]*)"/);assert.ok(m);assert.equal(m[1],MESSAGE);
  const click=bodyOf(src.dashboard,'bool CGOATDashboard::HandleObjectClick(const string control_name)');
  for(const [rows,button,want] of [[[{cid:0,magic:0}],'all',['message']],[[{cid:5,magic:6}],'all',[]],[[{cid:5,magic:0}],'all',['message']],
                                    [[{cid:0,magic:0}],'row0',['message']],[[{cid:5,magic:6}],'row0',['navigate:0']]]){
   const calls=[];const c={g_sets:rows,ArraySize:a=>a.length,HandleTableViewClick:()=>false,HandleHeaderClick:()=>false,HandleHeaderStateButtonClick:()=>false,
    AllRowsDeployed:()=>rows.every(r=>r.cid>0&&r.magic>0),GOAT_DASH_DEPLOY_RETIRED_MESSAGE:MESSAGE,MB_OK:0,MB_ICONINFORMATION:0,
    MessageBox:(text,title)=>{assert.equal(text,MESSAGE);assert.equal(title,'Portfolio');calls.push('message');return 1;},
    NavigateToSet:i=>{calls.push('navigate:'+i);return true;},
    btn_Action:[{Name:()=>'h'},{Name:()=>'all'},{Name:()=>'row0',Text:()=>rows[0].cid>0&&rows[0].magic>0?'Navigate':'Pending'}]};
   for(const forbidden of ['DeployAll','DoActivate','AgentDeployRow','ApplyTemplate']) assert.ok(!click.includes(forbidden),forbidden);
   assert.equal(vm.runInNewContext('(function(control_name){'+js(click)+'})',c)(button),true);assert.deepEqual(calls,want,JSON.stringify([rows,button]));ok();
  }
  const metrics=bodyOf(src.dashboard,'void CGOATDashboard::UpdateRowMetrics(const int idx,const int gui_row)');
  assert.match(metrics,/Text\(row_linked \? "Navigate" : "Pending"\)/);assert.match(metrics,/row_linked \? "Bring this child chart to the front" : GOAT_DASH_DEPLOY_RETIRED_MESSAGE/);ok();
  const portfolio=bodyOf(src.dashboard,'void CGOATDashboard::UpdatePortfolioRow()');
  assert.match(portfolio,/string action_text=\(all_deployed \? "All active" : "Deploy in app"\);/);
  assert.match(portfolio,/OBJPROP_TOOLTIP,\(all_deployed \? "Every member is linked" : GOAT_DASH_DEPLOY_RETIRED_MESSAGE\)/);ok();
  assert.ok(src.dashboard.includes('CreateButtonCtrl2(btn_Action[1]  ,prefix+"BTN",x,y,Width_Action,m_controlHeight,"Deploy in app");'));
  assert.ok(src.dashboard.includes('? "Navigate" : "Pending"));'));ok();
  // Navigate, pause and statistics keep their handlers.
  for(const kept of ['bool CGOATDashboard::NavigateToSet(const int idx)','bool CGOATDashboard::SendPortfolioPauseCommand(const bool pause)',
                     'void CGOATDashboard::CalcHistoryStatsFast(','void CGOATDashboard::UpdateRowMetrics(','void CGOATDashboard::ProcessTimerCycle(void)',
                     'bool CGOATDashboard::HandleTableViewClick(','bool CGOATDashboard::SendPortfolioCloseCommand(void)','bool CGOATDashboard::ArmRiskPolicyFromHeader(void)'])
   assert.ok(src.dashboard.includes(kept),kept);
  ok();}

 // ---- a status event never assigns a magic: only adoption links a row ----
 {const ev=region(src.dashboard,'   if(id==GOAT_EVENT_CHILD_STATUS)','   if(id==CHARTEVENT_OBJECT_CLICK)');
  assert.ok(!/\.magic\s*=\s*lparam/.test(ev));assert.match(ev,/cid_match=\(g_sets\[idx\]\.cid>0 && g_sets\[idx\]\.magic>0 && /);ok();}

 // ---- the template attach path is retired, not dormant ----
 const identity=JSON.parse(fs.readFileSync(path.join(ROOT,'candidate-builds/beta17-B43/identity.json'),'utf8'));
 const closure=Object.keys(identity.sources).filter(f=>/\.mq[5h]$/.test(f));
 assert.ok(closure.length>30 && closure.includes('Dashboard.mqh') && closure.includes('GOAT V1.49.mq5'));
 for(const f of closure){
  const text=f==='Dashboard.mqh'?src.dashboard:f===FILES.setup?src.setup:f===FILES.audit?src.audit:fs.readFileSync(path.join(ROOT,f),'utf8');
  assert.ok(!/ChartApplyTemplate/.test(text),'ChartApplyTemplate in '+f);
 }
 ok();
 for(const [f,text] of [['Dashboard.mqh',src.dashboard],[FILES.setup,src.setup],[FILES.audit,src.audit]]){
  for(const gone of [/\bChartOpen\s*\(/,/\bChartClose\s*\(/,/\bCopyFileW\b/,/\bDeleteFileW\b/,/#import/,/Profiles\\\\Templates/,/\bApplyTemplate\b/,/\bBuildTemplate\b/,
                     /\bSaveTemplateAndCopy\b/,/\bDeleteCopiedTemplate\b/,/\bNewSingleInstance\b/,/\bDoActivate\b/,/\bDeployAll\b/,/\bAgentDeployRow\b/,/\bChartSetSymbolPeriod\b/])
   assert.ok(!gone.test(text),f+': '+gone);
 }
 ok();
 assert.ok(!src.main.includes('ChartApplyTemplate'));assert.ok(!fs.existsSync(path.join(ROOT,'scripts/mql5/GOATSetupBootstrap.mq5')),'bootstrap script deleted');
 const setupDoc=fs.readFileSync(path.join(ROOT,'docs/AGENT-SETUP.md'),'utf8');
 assert.ok(!setupDoc.includes('Persistent bootstrap')&&!setupDoc.includes('GOATSetupBootstrap'),'bootstrap doc section deleted');ok();
 const liveness=fs.readFileSync(path.join(ROOT,'docs/operations/DEPLOYMENT-STARTUP-LIVENESS.md'),'utf8');
 for(const must of ['## Open question: the dashboard\'s own template applies (do not re-add)','**The cause is unknown.**','attach-mechanism-experiment','b41-3-t3-proof','algogoat/GOAT-EA#186'])
  assert.ok(liveness.includes(must),must);
 ok();
 // The only template call left is the audit's ChartSaveTemplate, and adoption reaches charts only through it.
 assert.equal((src.audit.match(/ChartSaveTemplate\(/g)||[]).length,1);assert.equal((src.setup.match(/ChartSaveTemplate\(/g)||[]).length,0);ok();

 // ---- MetaEditor warning 62: no new local shadows a global ----
 const added=new Set();
 for(const text of [region(src.setup,'// ---- Profile-staged deploy','string GoatPortfolioSnapshot('),bodyOf(src.dashboard,'bool CGOATDashboard::AdoptChild(const int adopt_idx,const long adopt_chart,const long adopt_magic)')])
  for(const m of text.matchAll(/\b(adopt_\w+)\b/g)) added.add(m[1]);
 for(const n of ['snapshot_read','set_path','row_linked']) added.add(n);
 const others=closure.filter(f=>!['Dashboard.mqh',FILES.setup,FILES.audit].includes(f)).map(f=>fs.readFileSync(path.join(ROOT,f),'utf8')).join('\n');
 for(const n of added){
  assert.ok(!new RegExp('\\b'+n+'\\b').test(others),n+' appears outside the new code');
  for(const [f,text] of [['Dashboard.mqh',src.dashboard],[FILES.setup,src.setup],[FILES.audit,src.audit]])
   assert.ok(!new RegExp('^\\s*(?:static\\s+)?(?:string|int|long|bool|double|datetime)\\s+'+n+'\\b[^(]*;','m').test(text.split('\n').filter(l=>!/^\s/.test(l)).join('\n')),n+' declared at file scope in '+f);
 }
 assert.ok(added.size>40);ok();
 return passed;
}
module.exports={run,readSources};
if(require.main===module){const n=run();console.log(JSON.stringify({passed:n,productionBlocks:true,nativeProfileLoad:false}));}
