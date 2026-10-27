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
  assert.ok(b.closes<=7&&b.closes>=6,label+': '+b.closes+' tries');
  assert.equal(b.acks.at(-1)[1],ACK.GOAT_DASH_ACK_EXPIRED,label+': expired');assert.equal(b.DashboardPortfolioCommandIdApplied,0);}
 {// A new command is never held back by an earlier command's retry spacing.
  const b=child(main,{refuse:1});b.DashboardBusApplyCommand(ID,type,0,EXP);b.now++;b.DashboardBusApplyCommand(ID+1,type,0,EXP+5);
  assert.equal(b.closes,2,label+': the new command closes at once');}
}
ok();

// ---- 2. The dashboard: a risk breach ----
const BREACH={GOAT_RISK_BREACH_NONE:0,GOAT_RISK_BREACH_LOW_EQUITY:1,GOAT_RISK_BREACH_RUNNING_LOSS:2,GOAT_RISK_BREACH_DAILY_LOSS:3,GOAT_RISK_BREACH_EQUITY_TARGET:4,GOAT_RISK_BREACH_DAILY_TARGET:5};
// Linked child charts (magic and symbol) and the account's positions; SendPortfolioCommand reaches every linked chart.
function dashboard(text,{pending=false,linked=true,positions=[[77,'EURUSD'],[78,'GBPUSD']],runningLoss=600}={}){
 const c={...BREACH,GOAT_DASH_CMD_PORTFOLIO_CLOSE:2,GOAT_PORTFOLIO_RUN_PAUSED:2,now:5000,audits:[],cmdAudits:[],sends:[],
  m_risk_policy_armed:true,m_risk_policy_breached:false,m_risk_policy_breach_code:0,m_risk_policy_breach_time:0,
  m_risk_breach_last_send:0,m_risk_breach_flat_logged:false,m_portfolio_command_pending:pending,m_portfolio_run_state:0,
  m_risk_low_equity_stop:0,m_risk_running_loss_limit:500,m_risk_daily_loss_limit:0,m_risk_equity_target:0,m_risk_daily_target_limit:0,
  Port_RunningLoss:runningLoss,Port_DailyLoss:0,Port_DailyTarget:0,positions:positions.slice(),
  g_sets:[{magic:77,sym:'EURUSD',cid:linked?101:0},{magic:78,sym:'GBPUSD',cid:linked?102:0}],
  AccountInfoDouble:()=>10000,ACCOUNT_EQUITY:0,POSITION_MAGIC:1,POSITION_SYMBOL:2,
  GlobalVariableSet:()=>true,GoatPortfolioGVName:n=>n,SaveRiskPolicyState:()=>{},PrintFormat:()=>{},UpdateHeaderStateButtons:()=>{},
  RiskBreachText:code=>'breach'+code,IntegerToString:String,ArraySize:a=>a.length,PositionsTotal:null};
 c.TimeCurrent=()=>c.now;
 c.AppendRiskPolicyAudit=(stage,reason,detail)=>c.audits.push(stage);
 c.AppendPortfolioCommandAudit=stage=>c.cmdAudits.push(stage);
 c.SendPortfolioCommand=(type,value,label)=>{if(!c.g_sets.some(s=>s.cid>0))return false;c.sends.push([c.now,label]);c.m_portfolio_command_pending=true;return true;};
 let selected=null;
 c.PositionsTotal=()=>c.positions.length;c.PositionGetTicket=i=>{selected=c.positions[i];return 1000+i;};
 c.PositionGetInteger=()=>selected[0];c.PositionGetString=()=>selected[1];
 vm.createContext(c);
 let code=fn('EvaluateRiskPolicy',[],bodyOf(text,'void CGOATDashboard::EvaluateRiskPolicy(void)'));
 if(text.includes('void CGOATDashboard::FollowRiskBreachClose(void)'))
  code+=fn('FollowRiskBreachClose',[],bodyOf(text,'void CGOATDashboard::FollowRiskBreachClose(void)'))
   +fn('LinkedOpenPositions',[],bodyOf(text,'int CGOATDashboard::LinkedOpenPositions(void)'));
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
{// No linked child chart: ACTION_FAILED, then RETRY_FAILED at most once a minute, and the close goes once a chart links.
 const b=dashboard(dash,{linked:false});b.EvaluateRiskPolicy();assert.deepEqual(b.audits,['BREACH','ACTION_FAILED']);
 for(let s=0;s<125;s++){b.now++;b.EvaluateRiskPolicy();}
 assert.deepEqual(b.audits.filter(x=>x==='RETRY_FAILED').length,2);
 b.g_sets[0].cid=101;b.now+=61;b.EvaluateRiskPolicy();assert.deepEqual([b.sends.length,b.audits.at(-1)],[1,'RETRY']);
 ok();}
{// A breach restored from saved state (a dashboard restart) is followed at once while positions are open.
 const b=dashboard(dash);b.m_risk_policy_armed=false;b.m_risk_policy_breached=true;b.m_risk_policy_breach_code=2;
 b.EvaluateRiskPolicy();assert.deepEqual([b.sends.length,b.audits],[1,['RETRY']]);
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f3b',b49aCompared:true}));
