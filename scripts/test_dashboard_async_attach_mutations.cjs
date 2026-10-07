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
  ['timeout leaves the child chart open','Dashboard.mqh',[[R`         bool closed=ChartClose(failed_cid);`,R`         bool closed=true;`]]],
  ['late child status adopts a failed row','Dashboard.mqh',[[R`            if(!magic_match && IsAgentAttachFailedChart(g_sets[idx].cid)) break;`,'']]],
  ['failed chart not remembered','Dashboard.mqh',[[R`         m_agent_attach_failed_cids[failed]=failed_cid;`,R`         m_agent_attach_failed_cids[failed]=0;`]]],
  ['early status magic kept on a failed row','Dashboard.mqh',[[R`      g_sets[idx].magic=0;`+'\n','']]],
  ['timeout keeps the copied template','Dashboard.mqh',[[R`   MarkStateDirty();
   DeleteCopiedTemplate(tplName);
}`,R`   MarkStateDirty();
}`]]],
  ['settle does not re-check inertness','GOATPortfolioSetupControl.mqh',[[R`(inert ? "child_attached" : "rejected_not_inert")`,R`"child_attached"`]]],
  ['settle ignores open positions','GOATPortfolioSetupControl.mqh',[[R`                 && PositionsTotal()==0 && OrdersTotal()==0;`,R`                 && OrdersTotal()==0;`]]],
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
