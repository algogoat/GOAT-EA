// Mutation check for B49b PR-3b (F3 dashboard half: RISK-01, DASH-04): every rule is load-bearing. Each mutant edits
// GOAT V1.49.mq5 (MAIN) or Dashboard.mqh (DASH) in memory; test_b49b_f3b.cjs, run on the mutated source
// (GOAT_EA_MAIN / GOAT_EA_DASHBOARD), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f3b.cjs');
const SOURCES={MAIN:['GOAT V1.49.mq5','GOAT_EA_MAIN'],DASH:['Dashboard.mqh','GOAT_EA_DASHBOARD']};
const text=Object.fromEntries(Object.entries(SOURCES).map(([k,[f]])=>[k,fs.readFileSync(path.join(ROOT,f),'utf8').replace(/\r\n/g,'\n')]));
const MUTANTS=[
 // The child (DASH-04).
 ['a portfolio close is marked applied before it closes','      // B49b (F3 DASH-04): applied only once the close left nothing open (below), so a failed close is retried\n','      DashboardPortfolioCommandIdApplied=command_id;\n','MAIN'],
 ['a scope close is marked applied before it closes','      // B49b (F3 DASH-04): applied only once the close left nothing open in the scope (below), so a failed close is retried\n','      DashboardPortfolioCommandIdApplied=command_id;\n','MAIN'],
 ['a flat portfolio close is never marked applied','      if(ack_status==GOAT_DASH_ACK_APPLIED) DashboardPortfolioCommandIdApplied=command_id; // B49b (F3 DASH-04): flat, so done\n','','MAIN'],
 ['a failed close is marked applied too','      if(ack_status==GOAT_DASH_ACK_APPLIED) DashboardPortfolioCommandIdApplied=command_id; // B49b (F3 DASH-04): flat in scope, so done\n','      DashboardPortfolioCommandIdApplied=command_id;\n','MAIN'],
 ['the retry is not spaced','   if(command_id==g_goat_dash_close_try_id && TimeCurrent()-g_goat_dash_close_try_at<5) return true;\n','','MAIN'],
 ['the retry spacing holds back a new command','   if(command_id==g_goat_dash_close_try_id && TimeCurrent()-g_goat_dash_close_try_at<5) return true;','   if(TimeCurrent()-g_goat_dash_close_try_at<5) return true;','MAIN'],
 ['the portfolio close is never retried','      if(GoatDashCloseRetryWait(command_id)) return; // B49b (F3 DASH-04): a failed close is retried, at most every 5 s\n      DashboardPortfolioPaused=true;','      if(true) return;\n      DashboardPortfolioPaused=true;','MAIN'],
 // The dashboard (RISK-01).
 ['a pending command hides the breach again','   if(!m_risk_policy_armed) return; // B49b','   if(!m_risk_policy_armed || m_portfolio_command_pending) return; // B49b','DASH'],
 ['a breach is never followed','   if(m_risk_policy_breached) {FollowRiskBreachClose(); return;}','   if(m_risk_policy_breached) {return;}','DASH'],
 ['the follow-up resends while a command is pending','   if(m_risk_breach_follow_ended || m_portfolio_command_pending) return;','   if(m_risk_breach_follow_ended) return;','DASH'],
 ['the follow ignores its end latch','   if(m_risk_breach_follow_ended || m_portfolio_command_pending) return;','   if(m_portfolio_command_pending) return;','DASH'],
 ['the follow-up resends every check','   if(m_risk_breach_last_send>0 && TimeCurrent()-m_risk_breach_last_send<60) return;\n','','DASH'],
 ['the follow-up ignores flat','   if(open_positions==0 && unreachable==0)\n   {','   if(false)\n   {','DASH'],
 ['a Resume request does not end the follow (a partial Resume is flattened)','   {\n      m_risk_breach_follow_ended=true;\n      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("RESUMED",RiskBreachText(m_risk_policy_breach_code),"Resume requested','   {\n      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("RESUMED",RiskBreachText(m_risk_policy_breach_code),"Resume requested','DASH'],
 ['a Pause request ends the follow too','   if(!pause && m_risk_policy_breached && !m_risk_breach_follow_ended)','   if(m_risk_policy_breached && !m_risk_breach_follow_ended)','DASH'],
 ['an orphaned row is counted as reachable','            if((g_sets[idx].cid>0)==reachable) open_positions++;','            open_positions++;','DASH'],
 ['unreachable positions end the follow as FLAT','   if(open_positions==0 && unreachable==0)\n','   if(open_positions==0)\n','DASH'],
 ['UNREACHABLE is audited every check','   if(unreachable>0 && !m_risk_breach_unreachable_logged)','   if(unreachable>0)','DASH'],
 ['a superseded currency/exposure command is not kept','      m_policy_unsynced_type=(m_portfolio_command_type==GOAT_DASH_CMD_CLOSE_SCOPE ? GOAT_DASH_CMD_TRADE_PERMISSIONS : m_portfolio_command_type);','      m_policy_unsynced_type=0;','DASH'],
 ['a superseded close is kept as unsynced','(m_portfolio_command_type==GOAT_DASH_CMD_TRADE_PERMISSIONS || m_portfolio_command_type==GOAT_DASH_CMD_EXPOSURE_POLICY || m_portfolio_command_type==GOAT_DASH_CMD_CLOSE_SCOPE)) // B49b','(true)) // B49b','DASH'],
 ['a superseded scoped close is not kept (Codex #280 4388200990)',' || m_portfolio_command_type==GOAT_DASH_CMD_CLOSE_SCOPE)) // B49b',')) // B49b','DASH'],
 ['a superseded scoped close is resent as a scoped close','(m_portfolio_command_type==GOAT_DASH_CMD_CLOSE_SCOPE ? GOAT_DASH_CMD_TRADE_PERMISSIONS : m_portfolio_command_type)','m_portfolio_command_type','DASH'],
 ['the resync does not wait for Resume or re-arm','   if(!m_policy_resync_due || m_policy_unsynced_type==0 || m_portfolio_command_pending) return;','   if(m_policy_unsynced_type==0 || m_portfolio_command_pending) return;','DASH'],
 ['the resync talks over a pending command','   if(!m_policy_resync_due || m_policy_unsynced_type==0 || m_portfolio_command_pending) return;','   if(!m_policy_resync_due || m_policy_unsynced_type==0) return;','DASH'],
 ['the resync is not quiet','   bool quiet=m_agent_setup_quiet;\n   m_agent_setup_quiet=true;\n','   bool quiet=m_agent_setup_quiet;\n','DASH'],
 ['the resync never clears','   m_policy_unsynced_type=0;\n   m_policy_resync_due=false;\n','','DASH'],
 ['Resume does not ask for the resend','   if(!pause && m_policy_unsynced_type!=0) m_policy_resync_due=true;','   if(false) m_policy_resync_due=true;','DASH'],
 ['the unsynced policy is not saved','   GlobalVariableSet(GoatPortfolioGVName(prefix+"Unsynced"),(double)m_policy_unsynced_type); // B49b (F3 RISK-01, #280)\n','','DASH'],
 ['the unsynced policy is not loaded','   if(GlobalVariableCheck(GoatPortfolioGVName(prefix+"Unsynced")))      m_policy_unsynced_type=(int)GlobalVariableGet(GoatPortfolioGVName(prefix+"Unsynced")); // B49b (#280)\n','','DASH'],
 ['the risk button hides an unsynced policy','    if(m_policy_unsynced_type!=0) return (m_risk_policy_breached ? "Breach/Unsynced" : "Policy Unsynced"); // B49b (F3 RISK-01, #280)\n','','DASH'],
 ['re-arming does not ask for the resend','   if(m_policy_unsynced_type!=0) m_policy_resync_due=true; // B49b (F3 RISK-01, #280): re-arming','   if(false) m_policy_resync_due=true; // B49b (F3 RISK-01, #280): re-arming','DASH'],
 ['the follow never ends at FLAT','      m_risk_breach_follow_ended=true;\n      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("FLAT"','      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("FLAT"','DASH'],
 ['a resumed portfolio is still closed by the follow-up','   if(m_portfolio_run_state!=GOAT_PORTFOLIO_RUN_PAUSED)\n   {','   if(false)\n   {','DASH'],
 ['the follow never ends at RESUMED (a later manual pause is flattened)','      m_risk_breach_follow_ended=true;\n      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("RESUMED",reason,','      SaveRiskPolicyState();\n      AppendRiskPolicyAudit("RESUMED",reason,','DASH'],
 ['a new breach is not followed','   m_risk_breach_follow_ended=false; // B49b (F3 RISK-01): this breach is followed (saved below)\n','','DASH'],
 ['an older build\'s breach is followed','(!GlobalVariableCheck(GoatPortfolioGVName(prefix+"FollowEnded")) || GlobalVariableGet','(GlobalVariableGet','DASH'],
 ['the end latch is not saved','   GlobalVariableSet(GoatPortfolioGVName(prefix+"FollowEnded"),(m_risk_breach_follow_ended ? 1.0 : 0.0)); // B49b (F3 RISK-01)\n','','DASH'],
 ['the breach send does not start the resend clock','   m_risk_breach_last_send=TimeCurrent(); // B49b (F3 RISK-01): the follow-up resends from here\n','','DASH'],
 ['positions of another symbol count','g_sets[idx].magic==position_magic && g_sets[idx].sym==position_symbol)','g_sets[idx].magic==position_magic)','DASH'],
 ['a superseded command is not audited','   if(m_portfolio_command_pending) AppendPortfolioCommandAudit("SUPERSEDED",0,0,0,"A risk breach close replaces the pending command"); // B49b (F3 RISK-01)\n','','DASH'],
];
function runOn(key,mutated){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f3b-'));
 try{
  const [file,env]=SOURCES[key],out=path.join(dir,file);
  fs.writeFileSync(out,'﻿'+mutated.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,[env]:out},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
for(const key of Object.keys(SOURCES)){const r=runOn(key,text[key]);assert.equal(r.status,0,'the unmutated test passes on the scratch '+key+': '+r.stderr);}
let killed=0;
for(const [label,from,to,key] of MUTANTS){
 const n=text[key].split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${SOURCES[key][0]} (found ${n})`);
 const r=runOn(key,text[key].replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
