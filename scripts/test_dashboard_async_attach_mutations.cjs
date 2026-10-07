// Mutation check for scripts/test_dashboard_async_attach.cjs (AA41, goatai#1885): every guard of the
// asynchronous agent attach is removed or weakened in a temporary copy of the production sources and
// the harness must fail. MQL-free; the repository files are never modified. GOAT_MUTATION_TMP picks
// the temp root.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['Dashboard.mqh','GOATPortfolioSetupControl.mqh','GOATLicenseInitRetry.mqh'];
const R=String.raw;
// [label, file, [[from, to], ...]]
const mutations=[
  // Budget and timer-driven settle
  ['agent budget back to 20 s','Dashboard.mqh',[[R`#define GOAT_AGENT_ATTACH_BUDGET_MS 75000`,R`#define GOAT_AGENT_ATTACH_BUDGET_MS 20000`]]],
  ['agent budget below the license startup','Dashboard.mqh',[[R`#define GOAT_AGENT_ATTACH_BUDGET_MS 75000`,R`#define GOAT_AGENT_ATTACH_BUDGET_MS 62000`]]],
  ['poll waits inside the handler again','Dashboard.mqh',[[R`   bool linked=NewSingleInstance(idx);`,R`   bool linked=false; uint w0=GetTickCount(); while(!(linked=NewSingleInstance(idx)) && GetTickCount()-w0<=GOAT_AGENT_ATTACH_BUDGET_MS) Sleep(50);`]]],
  ['agent begin runs the blocking ApplyTemplate','Dashboard.mqh',[[R`      started=BeginChildAttach(idx,tf,tplName);`,R`      started=ApplyTemplate(idx,tf,tplName);`]]],
  ['attach never marked pending','Dashboard.mqh',[[R`   m_agent_attach_pending=true;`+'\n','']]],
  ['deploy_next answers before the attach settles','GOATPortfolioSetupControl.mqh',[[`            FileClose(owner);\n            return;\n`,'']]],
  ['other requests read while an attach is in flight','GOATPortfolioSetupControl.mqh',[[R`   if(GoatPortfolioAttachContinue(root) || GoatPortfolioAttachPending) return;`,R`   if(GoatPortfolioAttachContinue(root)) {}`]]],
  ['busy owner lock drops the final receipt','GOATPortfolioSetupControl.mqh',[[R`   if(owner==INVALID_HANDLE) return true;`,R`   if(owner==INVALID_HANDLE) {GoatPortfolioAttachPending=false; return false;}`]]],
  ['failed receipt write is not retried','GOATPortfolioSetupControl.mqh',[[R`   if(!written) return true;`,'']]],
  // Timeout unwind (Mac 6028209095)
  ['timeout leaves the child chart open','Dashboard.mqh',[[R`   bool chart_closed=ChartClose(cid);`,R`   bool chart_closed=true;`]]],
  ['failed marker not set','Dashboard.mqh',[[R`   g_sets[idx].magic=GOAT_ATTACH_FAILED_MAGIC;
   MarkStateDirty();`,R`   MarkStateDirty();`]]],
  ['failed marker cleared instead','Dashboard.mqh',[[R`   g_sets[idx].magic=GOAT_ATTACH_FAILED_MAGIC;
   MarkStateDirty();`,R`   g_sets[idx].magic=0;
   MarkStateDirty();`]]],
  ['failed marker not saved','Dashboard.mqh',[[R`   if(!SaveDashboardConfig())
      Print("Dashboard failed-attach state save failed; the row stays locked in memory.");`,'']]],
  ['close ignores the symbol check','Dashboard.mqh',[[R`   if(ChartSymbol(cid)!=g_sets[idx].sym)`,R`   if(false)`]]],
  ['restored failed chart not closed on load','Dashboard.mqh',[[R`      if(g_sets[idx].magic==GOAT_ATTACH_FAILED_MAGIC)
         CloseFailedChildChart(idx,true);`,'']]],
  ['failed-row guard reads only in-memory state','Dashboard.mqh',[[R`      if(g_sets[i].cid==cid && g_sets[i].magic==GOAT_ATTACH_FAILED_MAGIC) return true;`,'']]],
  // Not inert at settle (Mac 6028472101 blocker 1)
  ['settle does not re-check inertness','Dashboard.mqh',[[R`   if(linked && inert)`,R`   if(linked)`]]],
  ['settle ignores open positions','Dashboard.mqh',[[R`              && PositionsTotal()==0 && OrdersTotal()==0;`,R`              && OrdersTotal()==0;`]]],
  ['not-inert receipt string only (B41.1 at 0db8aea)','Dashboard.mqh',[[R`   if(linked && inert)`,R`   if(linked)`],[R`   return (!inert ? -2 : -1);`,R`   return -1;`]]],
  ['not-inert path skips the close','Dashboard.mqh',[[R`         ResetFailedChildRow(idx,tplName);
      }
      else
         FailChildAttachTimeout(idx,tplName);
      AgentUnwindFailedAttach(idx);`,R`         ResetFailedChildRow(idx,tplName);
         g_sets[idx].magic=GOAT_ATTACH_FAILED_MAGIC;
      }
      else
      {
         FailChildAttachTimeout(idx,tplName);
         AgentUnwindFailedAttach(idx);
      }`]]],
  ['inert checked only at link or timeout','Dashboard.mqh',[[R`   if(!linked && inert && GetTickCount()-m_agent_attach_start<=GOAT_AGENT_ATTACH_BUDGET_MS)`,R`   if(!linked && GetTickCount()-m_agent_attach_start<=GOAT_AGENT_ATTACH_BUDGET_MS)`]]],
  ['child trades not reported','Dashboard.mqh',[[R`         GoatDeploymentPhase("not_inert_child_trades",g_sets[idx].cid,ChildTradeSummary(idx));`,'']]],
  ['trade summary skips orders','Dashboard.mqh',[[R`      if(ticket==0 || OrderGetInteger(ORDER_MAGIC)!=magic) continue;`,R`      continue;`]]],
  ['trade summary lists other magics','Dashboard.mqh',[[R`      if(ticket==0 || PositionGetInteger(POSITION_MAGIC)!=magic) continue;`,R`      if(ticket==0) continue;`]]],
  ['on-load close skips the ours check','Dashboard.mqh',[[R`   if(on_load && !FailedChildChartIsOurs(idx))`,R`   if(false)`]]],
  ['ours check ignores the EA on the chart','Dashboard.mqh',[[R`   if(ChartGetString(cid,CHART_EXPERT_NAME)!=EA_Name_) return false;`,'']]],
  ['ours check ignores the handshake','Dashboard.mqh',[[R`          && (long)hi==cid/1000000000 && (long)lo==cid%1000000000);`,R`          || true);`]]],
  ['live unwind demands the on-load proof','Dashboard.mqh',[[R`   CloseFailedChildChart(idx,false);`,R`   CloseFailedChildChart(idx,true);`]]],
  // B41.2: refresh the pending child chart (T3 6030127717; Mac 6030140212, 6030329907)
  ['nudge dropped (B41.1 behaviour)','Dashboard.mqh',[[R`            ChartSetSymbolPeriod(g_sets[idx].cid,g_sets[idx].sym,m_agent_attach_tf);
            ChartRedraw(g_sets[idx].cid);
`,'']]],
  ['nudge also hits non-pending rows','Dashboard.mqh',[[R`            ChartSetSymbolPeriod(g_sets[idx].cid,g_sets[idx].sym,m_agent_attach_tf);
            ChartRedraw(g_sets[idx].cid);
`,R`            for(int r=0;r<ArraySize(g_sets);r++) if(g_sets[r].cid>0) {ChartSetSymbolPeriod(g_sets[r].cid,g_sets[r].sym,m_agent_attach_tf); ChartRedraw(g_sets[r].cid);}
`]]],
  ['nudge changes the timeframe','Dashboard.mqh',[[R`ChartSetSymbolPeriod(g_sets[idx].cid,g_sets[idx].sym,m_agent_attach_tf);`,R`ChartSetSymbolPeriod(g_sets[idx].cid,g_sets[idx].sym,PERIOD_H1);`]]],
  ['nudge every tick, no 2 s cadence','Dashboard.mqh',[[R`      if(!m_agent_attach_nudge_done && GetTickCount()-m_agent_attach_refresh>=2000)`,R`      if(!m_agent_attach_nudge_done)`]]],
  ['nudge keeps going after the expert appears','Dashboard.mqh',[[R`         if(child_expert!="")`,R`         if(false)`]]],
  ['nudge gate never closes','Dashboard.mqh',[[R`            m_agent_attach_nudge_done=true;
            GoatDeploymentPhase("attach_nudge_stopped"`,R`            GoatDeploymentPhase("attach_nudge_stopped"`]]],
  ['expert queried before the first refresh','Dashboard.mqh',[[R`         if(m_agent_attach_nudges>0) child_expert=`,R`         child_expert=`]]],
  ['nudge with the requested timeframe','Dashboard.mqh',[[R`   m_agent_attach_tf=(m_child_attach_period!=PERIOD_CURRENT ? m_child_attach_period : tf);`,R`   m_agent_attach_tf=tf;`]]],
  ['chart period not read after ChartOpen','Dashboard.mqh',[[R`   m_child_attach_period=(ENUM_TIMEFRAMES)ChartPeriod(cid);
`,'']]],
  ['nudges not logged','Dashboard.mqh',[[R`            GoatDeploymentPhase("attach_nudge",g_sets[idx].cid,StringFormat("n=%d expert=\"%s\"",m_agent_attach_nudges,child_expert));`,'']]],
  ['nudge stop not logged','Dashboard.mqh',[[R`            GoatDeploymentPhase("attach_nudge_stopped",g_sets[idx].cid,"expert=\""+child_expert+"\"");`,'']]],
  ['not-inert answered as a plain failure','GOATPortfolioSetupControl.mqh',[[R`(state==-2 ? "rejected_not_inert" : "child_attach_failed")`,R`"child_attach_failed"`]]],  ['late child status adopts a failed row','Dashboard.mqh',[[R`            if(!magic_match && IsAgentAttachFailedChart(g_sets[idx].cid)) break;`,'']]],
  ['timeout keeps the copied template','Dashboard.mqh',[[R`   MarkStateDirty();
   DeleteCopiedTemplate(tplName);
}`,R`   MarkStateDirty();
}`]]],
  // Stale templates (Mac 6028113003, 6028209095)
  ['copy refuses to overwrite a stale template','Dashboard.mqh',[[R`if(!CopyFileW(srcXL, dstXL, 0))`,R`if(!CopyFileW(srcXL, dstXL, 1))`]]],
  ['failed copy still queues the template','Dashboard.mqh',[[R`if(!CopyFileW(srcXL, dstXL, 0)) { Print("CopyFileW error ", GetLastError()); return false; }`,R`if(!CopyFileW(srcXL, dstXL, 0)) { Print("CopyFileW error ", GetLastError()); }`]]],
  ['startup sweep not called','Dashboard.mqh',[[`   SweepStaleChildTemplates();\n   m_state_dirty=false;`,`   m_state_dirty=false;`]]],
  ['startup sweep deletes nothing','Dashboard.mqh',[[R`      if(g_sets[idx].cid<=0 || g_sets[idx].magic>0) continue;`,R`      continue;`]]],
  ['startup sweep also deletes undeployed rows','Dashboard.mqh',[[R`      if(g_sets[idx].cid<=0 || g_sets[idx].magic>0) continue;`,R`      if(g_sets[idx].magic>0) continue;`]]],
];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-async-attach-mutation-'));
function run(dir){return spawnSync(process.execPath,[path.join(__dirname,'test_dashboard_async_attach.cjs')],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:120000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  const clean=run(base);if(clean.status!==0)throw new Error('unmutated sources fail:\n'+clean.stdout+clean.stderr);
  mutations.forEach(([label,file,pairs],n)=>{
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file);let text=fs.readFileSync(target,'utf8');
    for(const [rawFrom,rawTo] of pairs){
      // Sources are CRLF; literals are LF. Match and write CRLF either way.
      const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
      if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
      text=text.replace(from,()=>to);
    }
    fs.writeFileSync(target,text);
    if(run(dir).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
console.log(JSON.stringify({mutations:mutations.length,killed,survivors}));
if(survivors.length) process.exit(1);
