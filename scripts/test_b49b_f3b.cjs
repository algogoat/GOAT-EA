// B49b PR-3b (F3 dashboard half: RISK-01, DASH-04; audit 06 Other issue 1; Claude-Mac goatai#2587 6436092625). Live
// only, no input. The production code runs here from GOAT V1.49.mq5 and Dashboard.mqh, side by side with B49a's
// (source 693cad0):
// 1. The child's DashboardBusApplyCommand: B49a marked a close command applied BEFORE closing, so after a failed close
//    the one-second re-poll acknowledged APPLIED and nothing retried it. B49b marks it applied only once nothing is left
//    open, retries a failed close at most every 5 s until the command expires, and acks EXPIRED after that. A close that
//    succeeds at once is B49a's exactly.
// 2. The dashboard's EvaluateRiskPolicy: B49a skipped the breach check while any command was pending, sent ONE
//    emergency close and then stopped looking. B49b checks a breach even while a command is pending (the close
//    supersedes it), and while breached sends the close again every 60 s until the linked child charts are flat (FLAT
//    audited once); no linked child is RETRY_FAILED, also at most once a minute.
// test_b49b_f3b_mutations.cjs runs this file on mutated sources (GOAT_EA_MAIN, GOAT_EA_DASHBOARD).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const readTree=(env,file)=>clean(fs.readFileSync(process.env[env]||path.join(ROOT,file),'utf8'));
const readB49a=file=>clean(execFileSync('git',['show',B49A_SOURCE+':'+file],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
const main=readTree('GOAT_EA_MAIN','GOAT V1.49.mq5'),dash=readTree('GOAT_EA_DASHBOARD','Dashboard.mqh');
const mainB49a=readB49a('GOAT V1.49.mq5'),dashB49a=readB49a('Dashboard.mqh');
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
 .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';

// ---- 1. The child: a dashboard close command ----
const ACK={GOAT_DASH_ACK_APPLIED:1,GOAT_DASH_ACK_FAILED:2,GOAT_DASH_ACK_EXPIRED:3,GOAT_DASH_ACK_REJECTED:4};
const CMD={GOAT_DASH_CMD_PORTFOLIO_PAUSE:1,GOAT_DASH_CMD_PORTFOLIO_CLOSE:2,GOAT_DASH_CMD_CLOSE_SCOPE:3,GOAT_DASH_CMD_TRADE_PERMISSIONS:4,GOAT_DASH_CMD_EXPOSURE_POLICY:5};
// The child's own positions: each close attempt fails while `refuse` lasts, then closes them all.
function child(text,{positions=2,refuse=0}={}){
 const c={...ACK,...CMD,MAGIC1:77,OP_BUYSELL:2,now:1000,open:positions,refuse,closes:0,acks:[],status:[],
  DashboardPortfolioCommandIdApplied:0,DashboardPortfolioPaused:false,DashboardTradeAllowBuy:true,DashboardTradeAllowSell:true,
  GOAT_CLOSE_SCOPE_ALL:0,GOAT_DASH_TRADE_ALLOW_BUY:1,GOAT_DASH_TRADE_ALLOW_SELL:2,GOAT_GV_FIELD_POLICY_PAUSED:'P',GOAT_GV_FIELD_POLICY_TRADE_MASK:'M',
  Symbol:()=>'EURUSD',GlobalVariableSet:()=>true,GoatPortfolioGVName:n=>n,GoatChildGVName:(m,s,f)=>f,
  GoatCloseCommandScope:v=>v,GoatCloseCommandTradeMask:()=>0,DashboardTradePermissionMask:()=>0};
 c.TimeCurrent=()=>c.now;
 c.closeAttempt=()=>{c.closes++;if(c.refuse>0){c.refuse--;return [0,c.open];}const n=c.open;c.open=0;return [n,0];};
 c.FindNumberOfPositions=()=>c.open;c.DashboardBusCountCloseScopePositions=()=>c.open;
 c.DashboardBusAckCommand=(id,s)=>c.acks.push([id,s]);
 c.DashboardBusAckCloseCommand=(id,s,closed,errors,remaining)=>c.acks.push([id,s,closed,errors,remaining]);
 c.DashboardBusSendStatus=s=>c.status.push(s);
 vm.createContext(c);
 // The two bus closes return the count and fill close_errors by reference: modelled as one attempt per call.
 const apply=bodyOf(text,'void DashboardBusApplyCommand(const long command_id,const int command_type,const int command_value,const datetime expires_at)')
  .replace(/int closed_positions=DashboardBusClose(?:Own|Scope)Positions\([^)]*\);/g,'let [closed_positions,__e]=closeAttempt(); close_errors=__e;');
 let code=fn('DashboardBusApplyCommand',['command_id','command_type','command_value','expires_at'],apply);
 code+=text.includes('bool GoatDashCloseRetryWait(const long command_id)')
  ?'let g_goat_dash_close_try_id=0,g_goat_dash_close_try_at=0;\n'+fn('GoatDashCloseRetryWait',['command_id'],bodyOf(text,'bool GoatDashCloseRetryWait(const long command_id)'))
  :'function GoatDashCloseRetryWait(){return false;}\n';
 vm.runInContext(code,c);
 return c;
}
const ID=5555,EXP=1030;
for(const type of [CMD.GOAT_DASH_CMD_PORTFOLIO_CLOSE,CMD.GOAT_DASH_CMD_CLOSE_SCOPE]){
 const label=type===CMD.GOAT_DASH_CMD_PORTFOLIO_CLOSE?'portfolio close':'close scope';
 {// A close that succeeds at once: B49a's exactly (one attempt, APPLIED, the command marked applied, the re-poll re-acks).
  const a=child(mainB49a),b=child(main);
  for(const c of [a,b]){c.DashboardBusApplyCommand(ID,type,0,EXP);c.now++;c.DashboardBusApplyCommand(ID,type,0,EXP);}
  assert.deepEqual([b.closes,b.acks,b.status,b.DashboardPortfolioCommandIdApplied],[a.closes,a.acks,a.status,a.DashboardPortfolioCommandIdApplied],label+': as B49a');
  assert.equal(b.closes,1);assert.equal(b.acks[1][1],ACK.GOAT_DASH_ACK_APPLIED);}
 {// B49a: a failed close, then the re-poll acknowledges APPLIED with the positions still open (audit 06 Other issue 1).
  const a=child(mainB49a,{refuse:1});a.DashboardBusApplyCommand(ID,type,0,EXP);
  assert.equal(a.acks[0][1],ACK.GOAT_DASH_ACK_FAILED);a.now++;a.DashboardBusApplyCommand(ID,type,0,EXP);
  assert.deepEqual([a.closes,a.acks[1][1],a.open],[1,ACK.GOAT_DASH_ACK_APPLIED,2],label+': B49a acks APPLIED with 2 open and never retries');}
 {// B49b: FAILED, not marked applied; the re-poll waits 5 s, then retries; flat is APPLIED; the next re-poll re-acks without closing.
  const b=child(main,{refuse:1});b.DashboardBusApplyCommand(ID,type,0,EXP);
  assert.equal(b.acks[0][1],ACK.GOAT_DASH_ACK_FAILED);assert.equal(b.DashboardPortfolioCommandIdApplied,0,label+': not applied');
  for(let s=1;s<5;s++){b.now++;b.DashboardBusApplyCommand(ID,type,0,EXP);}
  assert.deepEqual([b.closes,b.acks.length],[1,1],label+': no retry inside 5 s');
  b.now++;b.DashboardBusApplyCommand(ID,type,0,EXP);
  assert.deepEqual([b.closes,b.acks[1][1],b.open,b.DashboardPortfolioCommandIdApplied],[2,ACK.GOAT_DASH_ACK_APPLIED,0,ID],label+': retried, flat, applied');
  b.now++;b.DashboardBusApplyCommand(ID,type,0,EXP);
  assert.deepEqual([b.closes,b.acks[2][1]],[2,ACK.GOAT_DASH_ACK_APPLIED],label+': applied re-acks without closing');}
 {// B49b: a close that keeps failing is tried at most 6 times in the command's 30 s, then EXPIRED.
  const b=child(main,{refuse:99});
  for(let s=0;s<=35;s++){b.DashboardBusApplyCommand(ID,type,0,EXP);b.now++;}
  assert.equal(b.closes,7,label+': 7 tries (0, 5, ..., 30 s)');
  assert.equal(b.acks.at(-1)[1],ACK.GOAT_DASH_ACK_EXPIRED,label+': expired');assert.equal(b.DashboardPortfolioCommandIdApplied,0);}
 {// A new command is never held back by an earlier command's retry spacing.
  const b=child(main,{refuse:1});b.DashboardBusApplyCommand(ID,type,0,EXP);b.now++;b.DashboardBusApplyCommand(ID+1,type,0,EXP+5);
  assert.equal(b.closes,2,label+': the new command closes at once');}
}
ok();

// ---- 2. The dashboard: a risk breach ----
const BREACH={GOAT_DASH_CMD_CLOSE_SCOPE:3,GOAT_DASH_CMD_TRADE_PERMISSIONS:4,GOAT_DASH_CMD_EXPOSURE_POLICY:5,GOAT_DASH_CMD_PORTFOLIO_PAUSE:1,GOAT_RISK_BREACH_NONE:0,GOAT_RISK_BREACH_LOW_EQUITY:1,GOAT_RISK_BREACH_RUNNING_LOSS:2,GOAT_RISK_BREACH_DAILY_LOSS:3,GOAT_RISK_BREACH_EQUITY_TARGET:4,GOAT_RISK_BREACH_DAILY_TARGET:5};
// Linked child charts (magic and symbol) and the account's positions; SendPortfolioCommand reaches every linked chart.
function dashboard(text,{pending=false,linked=true,positions=[[77,'EURUSD'],[78,'GBPUSD']],runningLoss=600}={}){
 const c={...BREACH,GOAT_DASH_CMD_PORTFOLIO_CLOSE:2,GOAT_PORTFOLIO_RUN_PAUSED:2,now:5000,audits:[],cmdAudits:[],sends:[],
  m_risk_policy_armed:true,m_risk_policy_breached:false,m_risk_policy_breach_code:0,m_risk_policy_breach_time:0,
  m_risk_breach_last_send:0,m_risk_breach_follow_ended:true,m_risk_breach_unreachable_logged:false,m_policy_unsynced_type:0,m_policy_resync_due:false,m_agent_setup_quiet:false,m_portfolio_command_type:0,m_exposure_policy_mode:0,resyncs:[],m_portfolio_command_pending:pending,m_portfolio_run_state:0,
  m_risk_low_equity_stop:0,m_risk_running_loss_limit:500,m_risk_daily_loss_limit:0,m_risk_equity_target:0,m_risk_daily_target_limit:0,
  Port_RunningLoss:runningLoss,Port_DailyLoss:0,Port_DailyTarget:0,positions:positions.slice(),
  g_sets:[{magic:77,sym:'EURUSD',cid:linked?101:0},{magic:78,sym:'GBPUSD',cid:linked?102:0}],
  AccountInfoDouble:()=>10000,ACCOUNT_EQUITY:0,POSITION_MAGIC:1,POSITION_SYMBOL:2,
  GlobalVariableSet:()=>true,GoatPortfolioGVName:n=>n,SaveRiskPolicyState:()=>{},PrintFormat:()=>{},UpdateHeaderStateButtons:()=>{},
  RiskBreachText:code=>'breach'+code,IntegerToString:String,ArraySize:a=>a.length,PositionsTotal:null};
 c.TimeCurrent=()=>c.now;
 c.AppendRiskPolicyAudit=(stage,reason,detail)=>c.audits.push(stage);
 c.AppendPortfolioCommandAudit=stage=>c.cmdAudits.push(stage);
 c.SendPortfolioCommand=(type,value,label)=>{if(!c.g_sets.some(s=>s.cid>0))return false;c.sends.push([c.now,label]);c.m_portfolio_command_pending=true;c.m_portfolio_command_type=type;return true;};
 c.SendCurrencyRulesCommand=()=>{c.resyncs.push(['currency',c.m_agent_setup_quiet]);c.m_portfolio_command_pending=true;return true;};
 c.SendExposurePolicyCommand=m=>{c.resyncs.push(['exposure',c.m_agent_setup_quiet,m]);c.m_portfolio_command_pending=true;return true;};
 let selected=null;
 c.PositionsTotal=()=>c.positions.length;c.PositionGetTicket=i=>{selected=c.positions[i];return 1000+i;};
 c.PositionGetInteger=()=>selected[0];c.PositionGetString=()=>selected[1];
 vm.createContext(c);
 let code=fn('EvaluateRiskPolicy',[],bodyOf(text,'void CGOATDashboard::EvaluateRiskPolicy(void)'));
 if(text.includes('void CGOATDashboard::FollowRiskBreachClose(void)'))
  code+=fn('FollowRiskBreachClose',[],bodyOf(text,'void CGOATDashboard::FollowRiskBreachClose(void)'))
   +fn('LinkedOpenPositions',['reachable'],bodyOf(text,'int CGOATDashboard::LinkedOpenPositions(const bool reachable)'))
   +fn('ResyncUnsyncedPolicy',[],bodyOf(text,'void CGOATDashboard::ResyncUnsyncedPolicy(void)'))
   +fn('SendPortfolioPauseCommand',['pause'],bodyOf(text,'bool CGOATDashboard::SendPortfolioPauseCommand(const bool pause)'))
   +fn('RiskPolicyButtonText',[],bodyOf(text,'string RiskPolicyButtonText(void) const'));
 vm.runInContext(code,c);
 return c;
}
{// No breach: nothing sent, B49a's exactly.
 for(const t of [dashB49a,dash]){const c=dashboard(t,{runningLoss:100});c.EvaluateRiskPolicy();assert.deepEqual([c.sends,c.audits,c.m_risk_policy_breached],[[],[],false]);}
 // A breach with nothing pending: one close, B49a's exactly.
 const a=dashboard(dashB49a),b=dashboard(dash);a.EvaluateRiskPolicy();b.EvaluateRiskPolicy();
 assert.deepEqual([b.sends,b.audits,b.m_risk_policy_breached,b.m_risk_policy_armed],[a.sends,a.audits,true,false]);
 assert.deepEqual(b.audits,['BREACH','ACTION']);
 ok();}
{// B49a: a pending command hides the breach (audit 06 Other issue 2). B49b: the breach close supersedes it.
 const a=dashboard(dashB49a,{pending:true});a.EvaluateRiskPolicy();
 assert.deepEqual([a.sends.length,a.m_risk_policy_breached],[0,false],'B49a: no breach while a command is pending');
 const b=dashboard(dash,{pending:true});b.EvaluateRiskPolicy();
 assert.deepEqual([b.sends.length,b.m_risk_policy_breached,b.cmdAudits],[1,true,['SUPERSEDED']]);
 ok();}
{// B49a: one close, then nothing however long the positions stay open. B49b: resent every 60 s once the command completed.
 const a=dashboard(dashB49a);a.EvaluateRiskPolicy();a.m_portfolio_command_pending=false;
 for(let s=0;s<600;s++){a.now++;a.EvaluateRiskPolicy();}
 assert.equal(a.sends.length,1,'B49a never resends');
 const b=dashboard(dash);b.EvaluateRiskPolicy();
 for(let s=1;s<=35;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.equal(b.sends.length,1,'no resend while the command is pending');
 b.m_portfolio_command_pending=false;
 for(let s=36;s<=59;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.equal(b.sends.length,1,'not before 60 s');
 b.now++;b.EvaluateRiskPolicy();
 assert.deepEqual([b.sends.length,b.audits.at(-1)],[2,'RETRY'],'resent at 60 s');
 b.m_portfolio_command_pending=false;b.now+=30;b.EvaluateRiskPolicy();assert.equal(b.sends.length,2,'at most once a minute');
 // A command still pending (another dashboard action, or one not yet acknowledged) is never talked over, past 60 s too.
 b.m_portfolio_command_pending=true;for(let s=0;s<120;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.equal(b.sends.length,2,'no resend while a command is pending');b.m_portfolio_command_pending=false;
 // Flat: FLAT once, nothing more sent.
 b.positions=[];for(let s=0;s<200;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.sends.length,b.audits.filter(x=>x==='FLAT').length],[2,1]);
 ok();}
{// Positions of unlinked charts or other symbols are not the breach's: only linked magic+symbol counts.
 const b=dashboard(dash,{positions:[[77,'GBPUSD'],[99,'EURUSD']]});b.EvaluateRiskPolicy();b.m_portfolio_command_pending=false;
 b.now+=61;b.EvaluateRiskPolicy();assert.deepEqual([b.sends.length,b.audits.at(-1)],[1,'FLAT']);
 ok();}
{// No linked child chart: ACTION_FAILED, then UNREACHABLE once (#280: nothing is resent to a row with no chart), and the close goes once a chart links.
 const b=dashboard(dash,{linked:false});b.EvaluateRiskPolicy();assert.deepEqual(b.audits,['BREACH','ACTION_FAILED']);
 for(let s=0;s<125;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.audits.filter(x=>x==='UNREACHABLE').length,b.audits.includes('RETRY_FAILED'),b.sends.length],[1,false,0]);
 b.g_sets[0].cid=101;b.now+=61;b.EvaluateRiskPolicy();assert.deepEqual([b.sends.length,b.audits.at(-1)],[1,'RETRY']);
 ok();}
{// A breach restored from saved state (a dashboard restart, the portfolio still paused) is followed at once while
 // positions are open.
 const b=dashboard(dash);b.m_risk_policy_armed=false;b.m_risk_policy_breached=true;b.m_risk_policy_breach_code=2;
 b.m_portfolio_run_state=b.GOAT_PORTFOLIO_RUN_PAUSED;b.m_risk_breach_follow_ended=false;   // saved by this build: FollowEnded=0
 b.EvaluateRiskPolicy();assert.deepEqual([b.sends.length,b.audits],[1,['RETRY']]);
 // A breach saved by an older build (no FollowEnded GV: loaded as ended) is never followed, paused or not.
 const o=dashboard(dash);o.m_risk_policy_armed=false;o.m_risk_policy_breached=true;o.m_risk_policy_breach_code=2;o.m_portfolio_run_state=o.GOAT_PORTFOLIO_RUN_PAUSED;
 for(let s=0;s<300;s++){o.now++;o.EvaluateRiskPolicy();}assert.deepEqual([o.sends.length,o.audits],[0,[]]);
 ok();}
{// Resume Portfolio does not clear the latched breach: a person who resumed (an equity target reached, a new day) is
 // trading on purpose, so the follow-up never closes a resumed portfolio. RESUMED once; pausing again resumes the follow.
 const b=dashboard(dash);b.EvaluateRiskPolicy();b.m_portfolio_command_pending=false;
 b.m_portfolio_run_state=0;   // Resume Portfolio (GOAT_PORTFOLIO_RUN_ACTIVE)
 for(let s=0;s<300;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.sends.length,b.audits.filter(x=>x==='RESUMED').length,b.audits.includes('RETRY')],[1,1,false]);
 // Paused again by hand later (Claude-Mac's reviewer, #280): the stale latched breach never flattens it; the follow ended at RESUMED.
 b.m_portfolio_run_state=b.GOAT_PORTFOLIO_RUN_PAUSED;for(let s=0;s<300;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.sends.length,b.audits.filter(x=>x==='RESUMED').length],[1,1],'paused by hand after a resume: never followed');
 // A restored breach on a portfolio that was resumed before the restart: nothing is sent.
 const r=dashboard(dash);r.m_risk_policy_armed=false;r.m_risk_policy_breached=true;r.m_risk_policy_breach_code=4;r.m_portfolio_run_state=0;r.m_risk_breach_follow_ended=false;
 r.EvaluateRiskPolicy();assert.deepEqual([r.sends.length,r.audits],[0,['RESUMED']]);
 ok();}

{// #280 item 1: the Resume REQUEST ends the follow, even when the Resume is only partly acknowledged (FAILED/TIMEOUT
 // leaves the run state PAUSED while some children already trade): their new trades are never closed.
 const b=dashboard(dash);b.EvaluateRiskPolicy();b.m_portfolio_command_pending=false;
 b.SendPortfolioPauseCommand(false);b.m_portfolio_command_pending=false;   // the Resume completed partly: run state stays PAUSED
 assert.equal(b.m_portfolio_run_state,b.GOAT_PORTFOLIO_RUN_PAUSED);
 b.positions.push([77,'EURUSD']);                                          // a new trade on the child that acked the Resume
 for(let s=0;s<300;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.sends.map(x=>x[1]),b.audits.filter(x=>x==='RESUMED').length,b.audits.includes('RETRY')],[['RiskBreachClose','PortfolioPause'],1,false]);
 // Pausing (not resuming) leaves the follow running.
 const q=dashboard(dash);q.EvaluateRiskPolicy();q.m_portfolio_command_pending=false;q.SendPortfolioPauseCommand(true);q.m_portfolio_command_pending=false;
 q.now+=61;q.EvaluateRiskPolicy();assert.equal(q.audits.at(-1),'RETRY');
 ok();}
{// #280 item 2: a row whose chart is gone (cid 0) is never sent the close: UNREACHABLE once, no RETRY on its account,
 // nothing pending every minute; its positions keep the breach open (no FLAT) until they are gone.
 const b=dashboard(dash);b.g_sets[1].cid=0;b.EvaluateRiskPolicy();b.m_portfolio_command_pending=false;
 b.now+=61;b.EvaluateRiskPolicy();assert.deepEqual(b.audits.slice(-2),['UNREACHABLE','RETRY'],'the live row is resent to');
 b.m_portfolio_command_pending=false;b.positions=[[78,'GBPUSD']];        // the live row is flat; only the orphaned row holds a position
 const sent=b.sends.length;for(let s=0;s<600;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual([b.sends.length-sent,b.audits.filter(x=>x==='UNREACHABLE').length,b.audits.includes('FLAT'),b.m_portfolio_command_pending],[0,1,false,false]);
 b.positions=[];b.now++;b.EvaluateRiskPolicy();assert.equal(b.audits.at(-1),'FLAT');
 ok();}
{// #280 item 3: a breach that supersedes a pending currency-rules or exposure command keeps it unsynced (shown on the
 // risk button, persisted) and sends it again, quietly, once a Resume or re-arm is asked and nothing is pending.
 for(const [type,kind,unsynced] of [[4,'currency',4],[5,'exposure',5],[3,'currency',4]]){   // a superseded scoped close paused a currency: resent as currency rules (Codex #280 4388200990)
  const b=dashboard(dash,{pending:true});b.m_portfolio_command_type=type;b.EvaluateRiskPolicy();
  assert.deepEqual([b.m_policy_unsynced_type,b.RiskPolicyButtonText()],[unsynced,'Breach/Unsynced']);
  b.m_portfolio_command_pending=false;for(let s=0;s<120;s++){b.now++;b.EvaluateRiskPolicy();b.m_portfolio_command_pending=false;}
  assert.deepEqual(b.resyncs,[],kind+': not before a Resume or re-arm');
  b.SendPortfolioPauseCommand(false);b.EvaluateRiskPolicy();assert.deepEqual(b.resyncs,[],kind+': not while the Resume is pending');
  b.m_portfolio_command_pending=false;b.now++;b.EvaluateRiskPolicy();
  assert.equal(b.resyncs.length,1);assert.deepEqual(b.resyncs[0].slice(0,2),[kind,true],kind+': resent, quietly');
  assert.deepEqual([b.m_policy_unsynced_type,b.m_policy_resync_due,b.audits.at(-1)],[0,false,'RESYNC']);
  b.m_portfolio_command_pending=false;b.now++;b.EvaluateRiskPolicy();assert.equal(b.resyncs.length,1,kind+': once');
 }
 // A superseded portfolio close or pause needs nothing (the breach's own close and pause cover them).
 for(const type of [1,2]){const b=dashboard(dash,{pending:true});b.m_portfolio_command_type=type;b.EvaluateRiskPolicy();assert.equal(b.m_policy_unsynced_type,0);}
 // Re-arming asks for the resend too (ArmRiskPolicyFromHeader is a dialog; its line is checked in place).
 assert.match(bodyOf(dash,'bool CGOATDashboard::ArmRiskPolicyFromHeader(void)'),/if\(m_policy_unsynced_type!=0\) m_policy_resync_due=true;/);
 ok();}
{// LoadRiskPolicyState: FollowEnded missing (a breach an older build saved) loads as ended; 0 loads as followed.
 const load=gv=>{const c={m_risk_policy_armed:false,m_risk_policy_breached:false,m_risk_policy_breach_code:0,m_risk_policy_breach_time:0,
  m_risk_running_loss_limit:0,m_risk_daily_loss_limit:0,m_risk_daily_target_limit:0,m_risk_low_equity_stop:0,m_risk_equity_target:0,
  m_risk_breach_follow_ended:false,m_policy_unsynced_type:0,GoatPortfolioGVName:n=>n,GlobalVariableCheck:n=>n in gv,GlobalVariableGet:n=>gv[n]};
  vm.createContext(c);vm.runInContext(fn('LoadRiskPolicyState',[],bodyOf(dash,'void CGOATDashboard::LoadRiskPolicyState(void)')),c);c.LoadRiskPolicyState();return c;};
 const base={DashboardRisk_Breached:1,DashboardRisk_BreachCode:2};
 assert.equal(load(base).m_risk_breach_follow_ended,true,'no FollowEnded: never followed');
 assert.equal(load({...base,DashboardRisk_FollowEnded:0}).m_risk_breach_follow_ended,false,'FollowEnded=0: followed');
 assert.equal(load({...base,DashboardRisk_FollowEnded:1}).m_risk_breach_follow_ended,true,'FollowEnded=1: ended');
 assert.equal(load({...base,DashboardRisk_FollowEnded:0,DashboardRisk_Unsynced:4}).m_policy_unsynced_type,4,'unsynced restored');
 assert.match(bodyOf(dash,'void CGOATDashboard::SaveRiskPolicyState(void)'),/GlobalVariableSet\(GoatPortfolioGVName\(prefix\+"FollowEnded"\),\(m_risk_breach_follow_ended \? 1\.0 : 0\.0\)\)/,'saved');
 assert.match(bodyOf(dash,'void CGOATDashboard::SaveRiskPolicyState(void)'),/GlobalVariableSet\(GoatPortfolioGVName\(prefix\+"Unsynced"\),\(double\)m_policy_unsynced_type\)/,'unsynced saved');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f3b',b49aCompared:true}));
