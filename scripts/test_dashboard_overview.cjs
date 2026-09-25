// Execute production MQL presentation/navigation/control visibility with native stubs.
// Compiling and native layout inspection complement these decision tests.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const ui=fs.readFileSync(path.join(root,'Dashboard.mqh'),'utf8').replace(/\r/g,'');
const helper=fs.readFileSync(path.join(root,'GOAT_DashboardOverview.mqh'),'utf8').replace(/\r/g,'');
function body(src,name){const at=src.indexOf(name+'(');assert.ok(at>=0,name);let a=src.indexOf('{',at),depth=1,b=a+1;for(;depth&&b<src.length;b++){if(src[b]==='{')depth++;if(src[b]==='}')depth--;}return src.slice(a+1,b-1);}
function js(s){return s.replace(/^\s*#.*$/gm,'').replace(/\b(?:const )?(?:bool|string|int|long|datetime|color) /g,'let ').replace(/\((?:int|long|double)\)/g,'').replace(/C'[^']+'/g,'1').replace(/\(void\)/g,'()');}
const base={IntegerToString:String,DoubleToString:(x,n)=>Number(x).toFixed(n),StringFind:(s,t)=>s.indexOf(t),StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),ArraySize:a=>a.length};
function fn(src,name,args,ctx){return vm.runInNewContext('(function('+args+'){'+js(body(src,name))+'})',ctx);}
let cases=0;
const ai=fn(helper,'GoatDashboardAILabel','mode,protocol,threshold',base);
for(const [v,result] of [[[1,2,50],'OFF'],[[2,2,50],'ON / DEMO / 50%'],[[2,1,80],'ON / LIVE / 80%'],[[0,2,50],'DISPLAY / DEMO'],[[5,1,60],'ON + exits / LIVE / 60%'],[[99,2,50],'Unknown configuration'],[[2,2,0],'Unknown configuration']]){assert.equal(ai(...v),result);cases++;}
for(const scenario of [
 {charts:[2,9,14],hint:2,dash:[9],want:9},
 {charts:[2,9,14],hint:9,dash:[9],want:9},
 {charts:[2,14],hint:99,dash:[],want:-1},
 {charts:[2,9,14],dash:[9,14],want:-1},
]){
 const c={...base,GlobalVariableCheck:()=>scenario.hint!==undefined,GlobalVariableGet:()=>scenario.hint,GoatIsDashboardChart:id=>scenario.dash.includes(id),ChartFirst:()=>scenario.charts[0],ChartNext:id=>scenario.charts[scenario.charts.indexOf(id)+1]??-1};
 assert.equal(fn(helper,'GoatFindDashboardChart','key',c)('GOAT'),scenario.want);cases++;
}
const visibility=body(ui,'CGOATDashboard::ApplyControlsView');
const names=[...visibility.matchAll(/GoatDashboardControlVisible\((\w+),/g)].map(m=>m[1]);
for(const [view,editor] of [[0,false],[4,false],[4,true],[2,true]]){
 const visible={};const c={...base,m_table_view:view,GOAT_DASH_VIEW_CONTROLS:4,m_currency_rules_editor_visible:editor,m_close_scope_editor_visible:false,
 GoatDashboardControlVisible:(o,v)=>visible[o.id]=v,btn_ViewControls:{Name:()=>'',Text:()=>{}},...Object.fromEntries(names.map(n=>[n,{id:n}]))};
 vm.runInNewContext(js(visibility),c);
 assert.equal(visible.edt_RunningLossLimit,view===4);assert.equal(visible.btn_PortfolioPause,view===4&&!editor);assert.equal(visible.btn_EURClose,view===4&&editor);assert.equal(visible.btn_AILaunchFeed,view===4);cases++;
}
// Exercise the production summary against live/mixed/missing/stale telemetry.
function summary({modes=[1,1],feeds=[2,2],thresholds=[50,50],exposures=[0,0],old=-1,missing=-1,pending=false}={}){
 const rows=modes.map((mode,i)=>({magic:i+1,cid:i+100,sym:'EURUSD',heartbeat_ts:i===old?1:100,bias_label:'Off'}));
 const gv={};rows.forEach((r,i)=>{gv[`${r.magic}:AI_MODE`]=modes[i];gv[`${r.magic}:AI_PROTOCOL`]=feeds[i];gv[`${r.magic}:AI_THRESHOLD`]=thresholds[i];gv[`${r.magic}:exposure`]=exposures[i];});if(missing>=0)delete gv[`${missing+1}:AI_MODE`];
 const out={};const edit=k=>({Name:()=>k,Text:t=>out[k]=t,Color:()=>{}});
 const c={...base,g_sets:rows,TimeCurrent:()=>100,ChartSymbol:()=>'EURUSD',GoatChildGVName:(id,sym,f)=>`${id}:${f}`,GlobalVariableCheck:k=>k in gv,GlobalVariableGet:k=>gv[k],
 GoatDashboardAILabel:ai,GoatDashboardExposureLabel:fn(helper,'GoatDashboardExposureLabel','mode',base),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE:'exposure',GOAT_AI_LAUNCH_AS_OPTIMIZED:0,GOAT_AI_LAUNCH_ENTRY_FILTER:2,m_ai_launch_mode:0,m_ai_launch_protocol:2,m_ai_launch_threshold:50,
 m_exposure_policy_mode:0,m_portfolio_command_pending:pending,m_portfolio_command_type:7,GOAT_DASH_CMD_EXPOSURE_POLICY:7,clrOrange:2,m_chart_id:1,OBJPROP_TOOLTIP:1,ObjectSetString:()=>{},edt_AISummary:edit('ai'),edt_ExposureSummary:edit('exposure')};
 vm.runInNewContext('(function(){'+js(body(ui,'CGOATDashboard::UpdatePolicySummary'))+'})()',c);return out;
}
assert.equal(summary().ai,'AI: OFF');cases++;
assert.equal(summary({modes:[2,2]}).ai,'AI: ON / DEMO / 50%');cases++;
assert.match(summary({modes:[1,2]}).ai,/MIXED/);cases++;
assert.match(summary({missing:1}).ai,/confirmed 1\/2/);cases++;
assert.match(summary({old:0}).ai,/confirmed 1\/2/);cases++;
assert.match(summary({exposures:[0,1],pending:true}).exposure,/MIXED \/ Applying/);cases++;
assert.match(summary({exposures:[1,1]}).exposure,/ON \/ differs from setup/);cases++;
// Five permanently silent children previously monopolized every timer cycle.
const condition=ui.match(/if\(best==-1 \|\| g_sets\[idx\]\.last_scan<best_scan[^\n]+/)[0].slice(3,-1);
const rows=Array.from({length:35},(_,i)=>({last_scan:0,hb:i<5?0:100}));const seen=new Set();
for(let cycle=1;cycle<=7;cycle++){
 const used=new Set();for(let n=0;n<5;n++){
  const c={best:-1,best_scan:9999,best_hb:9999,g_sets:rows,idx:0,hb:0};
  for(let idx=0;idx<35;idx++){if(used.has(idx))continue;c.idx=idx;c.hb=rows[idx].hb;if(vm.runInNewContext(condition,c)){c.best=idx;c.best_scan=rows[idx].last_scan;c.best_hb=rows[idx].hb;}}
  used.add(c.best);seen.add(c.best);rows[c.best].last_scan=cycle;
 }
}
assert.equal(seen.size,35);cases++;
const overview=ui.slice(ui.indexOf('if(m_table_view==GOAT_DASH_VIEW_OVERVIEW)\n'),ui.indexOf('else if(m_table_view==GOAT_DASH_VIEW_DIAGNOSTICS)\n'));
assert.ok(!overview.includes('LayoutTableEdit(edt_Status'));assert.ok(overview.includes('LayoutTableEdit(edt_Positions'));cases++;
// Activation must not rely on display strings or retry partial attachment.
for(const [rows,want] of [[[{cid:0,magic:0}],1],[[{cid:100,magic:10}],0],[[{cid:100,magic:0},{cid:0,magic:0}],0],[[{cid:0,magic:10}],0]]){
 let activated=0;const c={...base,g_sets:rows,HandleTableViewClick:()=>false,HandleHeaderClick:()=>false,HandleHeaderStateButtonClick:()=>false,
 btn_Action:[{}, {Name:()=> 'all'}],MessageBox:()=>{},MB_OK:0,MB_ICONINFORMATION:0,DeployAll:()=>activated++};
 fn(ui,'CGOATDashboard::HandleObjectClick','control_name',c)('all');assert.equal(activated,want);cases++;
}
for(const [rows,wantAction,wantAI] of [
 [[{cid:0,magic:0,bias_label:'OFF'}],'ActivateAll','OFF'],
 [[{cid:1,magic:2,bias_label:'ON / DEMO / 50%'},{cid:3,magic:4,bias_label:'ON / DEMO / 50%'}],'Activated','ON / DEMO / 50%'],
 [[{cid:1,magic:0,bias_label:'OFF'}],'ActivateAll','OFF'],
 [[{cid:1,magic:2,bias_label:'OFF'},{cid:3,magic:4,bias_label:'ON / DEMO / 50%'}],'Activated','Mixed']]){
 const out={};const control=k=>({Text:v=>out[k]=v,Color:()=>{}});const rows2=rows.map(r=>({...r,strat:'Example',risk_lots_label:'500 $',open_trades:0,open_lots:0,Trades_total:0,open_pl:0,PL_daily:0,PL_weekly:0,PL_total:0}));
 const names=['edt_Symbol','edt_Strategy','btn_Action','edt_Comment','edt_News','edt_AIBias','edt_RiskLots','edt_Status','edt_HistDD','edt_Trades','edt_Positions','edt_Lots','edt_PL_Open','edt_PL_D1','edt_PL_W1','edt_PL_All'];
 const c={...base,g_sets:rows2,TimeCurrent:()=>100,DisplayStatusForRow:()=> 'Not deployed',m_portfolio_command_pending:false,m_portfolio_run_state:0,GOAT_PORTFOLIO_RUN_PAUSED:1,clrRed:1,clrWhite:2,StatusColor:()=>1,Portfolio_Target_DD:'2000',StringToDouble:Number,FormatIntegerText:String,UpdatePortfolioInfoHeader:()=>{},m_ai_launch_mode:0,GOAT_AI_LAUNCH_AS_OPTIMIZED:0,...Object.fromEntries(names.map(n=>[n,[{},control(n)]]))};
 vm.runInNewContext('(function(){'+js(body(ui,'CGOATDashboard::UpdatePortfolioRow')).replace(/\bdouble /g,'let ')+'})()',c);
 assert.equal(out.btn_Action,wantAction);assert.equal(out.edt_AIBias,wantAI);cases++;
}
console.log(JSON.stringify({passed:cases,productionBlocks:true,nativeTrading:false}));
