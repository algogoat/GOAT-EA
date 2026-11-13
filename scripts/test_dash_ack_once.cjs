// Dashboard command bus, one final acknowledgement per command id (GOAT-EA#328). The child chart's one-second timer
// re-read its stored command id and acknowledged it again every second, for ever: applied, expired (every stored command
// after any restart) and rejected alike, and each acknowledgement ends in GlobalVariablesFlush, a rewrite of the
// terminal's whole global-variable store (33 rewrites a second on a 36-chart terminal).
// The production code runs here from GOAT V1.49.mq5 (as test_b49b_f3b.cjs runs it): DashboardBusProcessCommands,
// DashboardBusApplyCommand, DashboardBusAckCommand, DashboardBusAckCloseCommand, the B49b close retry and the
// dash-ack-once block, plus OnInit's own policy-restore lines for a restart, against a modelled global-variable store
// that outlives the EA instance. Over 120 timer ticks:
// (a) an applied command, (b) a stored expired command after a restart, (c) a rejected type: ONE acknowledgement and ONE
//     flush each; a restart on a command this chart already gave a final acknowledgement: none;
// (d) a close that is not flat at first keeps being retried (B49b F3 DASH-04) until flat, then APPLIED once;
// (e) a new command id after a final one is processed normally;
// (f) a close that keeps failing retries as before (every 5 s until the command expires) and writes and flushes its
//     acknowledgement only when the acknowledgement's values change;
// (g) Codex on GOAT-EA#330: a child poll that runs WHILE the dashboard publishes a command. The dashboard's write order is
//     read from Dashboard.mqh's four publish sites (the id cleared first, written last); every interleaving of those writes
//     with one poll's reads is tried, for a child that already finished the older command and for one that had not read
//     it yet. Every command the child applies must be one whole command (no new id with an older command's fields, no
//     older id with the new one's), and the new command must end APPLIED, never EXPIRED from an older expiry.
// test_dash_ack_once_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN) and dashboards (GOAT_EA_DASH):
// each must fail.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const header=clean(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
const dash=clean(fs.readFileSync(process.env.GOAT_EA_DASH||path.join(ROOT,'Dashboard.mqh'),'utf8'));
let passed=0,interleaving=null;const ok=()=>passed++;

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

// The header's own values: the acknowledgement statuses, the command types and the field names.
const DEF={};
for(const m of header.matchAll(/^#define\s+(GOAT_DASH_ACK_\w+|GOAT_DASH_CMD_\w+|GOAT_GV_FIELD_\w+|GOAT_DASH_TRADE_ALLOW_\w+|GOAT_CLOSE_SCOPE_ALL|GOAT_EXPOSURE_ALLOW)\s+("[^"]*"|-?\d+)\s*(?:\/\/.*)?$/gm))
 DEF[m[1]]=m[2].startsWith('"')?m[2].slice(1,-1):Number(m[2]);
for(const k of ['GOAT_DASH_ACK_APPLIED','GOAT_DASH_ACK_REJECTED','GOAT_DASH_ACK_FAILED','GOAT_DASH_ACK_EXPIRED','GOAT_DASH_CMD_PORTFOLIO_PAUSE','GOAT_DASH_CMD_PORTFOLIO_CLOSE',
 'GOAT_DASH_CMD_TRADE_PERMISSIONS','GOAT_DASH_CMD_EXPOSURE_POLICY','GOAT_DASH_CMD_CLOSE_SCOPE','GOAT_GV_FIELD_CMD_ID','GOAT_GV_FIELD_CMD_TYPE','GOAT_GV_FIELD_CMD_VALUE',
 'GOAT_GV_FIELD_CMD_EXPIRES','GOAT_GV_FIELD_ACK_ID','GOAT_GV_FIELD_ACK_STATUS','GOAT_GV_FIELD_ACK_TIME','GOAT_GV_FIELD_ACK_CLOSED','GOAT_GV_FIELD_ACK_ERRORS','GOAT_GV_FIELD_ACK_REMAINING',
 'GOAT_GV_FIELD_POLICY_PAUSED','GOAT_GV_FIELD_POLICY_TRADE_MASK','GOAT_GV_FIELD_POLICY_EXPOSURE_MODE','GOAT_DASH_TRADE_ALLOW_BUY','GOAT_DASH_TRADE_ALLOW_SELL','GOAT_CLOSE_SCOPE_ALL'])
 assert.ok(k in DEF,'GOAT_Inputs_Definitions.mqh defines '+k);
const A=DEF.GOAT_DASH_ACK_APPLIED,R=DEF.GOAT_DASH_ACK_REJECTED,F=DEF.GOAT_DASH_ACK_FAILED,X=DEF.GOAT_DASH_ACK_EXPIRED;
const PAUSE=DEF.GOAT_DASH_CMD_PORTFOLIO_PAUSE,CLOSE=DEF.GOAT_DASH_CMD_PORTFOLIO_CLOSE,PERM=DEF.GOAT_DASH_CMD_TRADE_PERMISSIONS,EXPO=DEF.GOAT_DASH_CMD_EXPOSURE_POLICY,SCOPE=DEF.GOAT_DASH_CMD_CLOSE_SCOPE;

// The dash-ack-once block (its globals and helpers) and OnInit's policy restore, as text.
const blockMatch=main.match(/\/\/ B55:begin dash-ack-once\n([\s\S]*?)\/\/ B55:end dash-ack-once\n/);
assert.ok(blockMatch,'the dash-ack-once block');
const blockGlobals=blockMatch[1].split('\n').filter(l=>/^(?:long|int|bool|datetime)\s+g_goat_dash_\w+=[^()]*;/.test(l)).join('\n');
assert.match(blockGlobals,/g_goat_dash_final_ack_id=0/,'the last final acknowledgement starts at 0');
const onInit=bodyOf(main,'int OnInit()');
const restoreFrom=onInit.indexOf('if(GlobalVariableCheck(GoatPortfolioGVName("DashboardPolicyPaused")))'),restoreTo=onInit.indexOf('Seq_Buy.Init(OP_BUY,false);');
assert.ok(restoreFrom>=0&&restoreTo>restoreFrom,'OnInit\'s policy restore');
const initRestore=onInit.slice(restoreFrom,restoreTo);
const KEY=f=>'77|EURUSD|'+f;

// One EA instance on a chart. `store` is the terminal's global-variable store: it outlives the instance (a restart
// makes a new instance on the same store). Each close attempt fails while `refuse` lasts, then closes everything.
function instance(store,{positions=0,refuse=0,now=1000,mode=0}={}){
 const c={...DEF,MAGIC1:77,OP_BUYSELL:2,Operation_Batch:1,Operation_Dash:2,Mode_Operation:mode,MQL_OPTIMIZATION:1,MQL_FORWARD:2,
  now,open:positions,refuse,closes:0,acks:[],flushes:0,ackWrites:0,status:[],store,
  DashboardPortfolioCommandIdApplied:0,DashboardPortfolioPaused:false,DashboardTradeAllowBuy:true,DashboardTradeAllowSell:true,
  DashboardExposurePolicyMode:DEF.GOAT_EXPOSURE_ALLOW??0,
  Symbol:()=>'EURUSD',MQLInfoInteger:()=>0,GoatPortfolioGVName:n=>'P|'+n,GoatChildGVName:(m,s,f)=>m+'|'+s+'|'+f,
  GoatCloseCommandScope:v=>v,GoatCloseCommandTradeMask:()=>3,DashboardNormalizeExposurePolicyMode:v=>v};
 c.TimeCurrent=()=>c.now;
 c.GlobalVariableCheck=k=>store.has(k);c.GlobalVariableGet=k=>store.get(k)??0;
 c.GlobalVariableSet=(k,v)=>{store.set(k,v);
  if(k===KEY(DEF.GOAT_GV_FIELD_ACK_STATUS)){c.ackWrites++;c.acks.push([store.get(KEY(DEF.GOAT_GV_FIELD_ACK_ID)),v]);}
  return c.now;};
 c.GlobalVariablesFlush=()=>{c.flushes++;};
 c.DashboardTradePermissionMask=()=>(c.DashboardTradeAllowBuy?DEF.GOAT_DASH_TRADE_ALLOW_BUY:0)|(c.DashboardTradeAllowSell?DEF.GOAT_DASH_TRADE_ALLOW_SELL:0);
 c.closeAttempt=()=>{c.closes++;if(c.refuse>0){c.refuse--;return [0,c.open];}const n=c.open;c.open=0;return [n,0];};
 c.FindNumberOfPositions=()=>c.open;c.DashboardBusCountCloseScopePositions=()=>c.open;
 c.DashboardBusSendStatus=s=>c.status.push(s);
 vm.createContext(c);
 compiled().runInContext(c);
 c.ticks=n=>{for(let i=0;i<n;i++){c.DashboardBusProcessCommands();c.now++;}};   // the 1 s timer (GoatTimerBody)
 return c;
}
// The production code, extracted and compiled once (every instance runs the same script in its own context).
let script=null;
function compiled(){
 if(script)return script;
 const apply=bodyOf(main,'void DashboardBusApplyCommand(const long command_id,const int command_type,const int command_value,const datetime expires_at)')
  .replace(/int closed_positions=DashboardBusClose(?:Own|Scope)Positions\([^)]*\);/g,'let [closed_positions,__e]=closeAttempt(); close_errors=__e;');
 let code=js(blockGlobals)+'\nlet g_goat_dash_close_try_id=0,g_goat_dash_close_try_at=0;\n'
  +fn('GoatDashAckIsFinal',['ack_status'],bodyOf(main,'bool GoatDashAckIsFinal(const int ack_status)'))
  +fn('GoatDashSeedFinalAck',[],bodyOf(main,'void GoatDashSeedFinalAck(void)'))
  +fn('GoatDashNoteFinalAck',['command_id','ack_status'],bodyOf(main,'void GoatDashNoteFinalAck(const long command_id,const int ack_status)'))
  +fn('GoatDashFinalAcked',['command_id'],bodyOf(main,'bool GoatDashFinalAcked(const long command_id)'))
  +fn('GoatDashCloseAckUnchanged',['command_id','ack_status','closed_positions','close_errors','remaining'],
      bodyOf(main,'bool GoatDashCloseAckUnchanged(const long command_id,const int ack_status,const int closed_positions,const int close_errors,const int remaining)'))
  +fn('GoatDashCloseRetryWait',['command_id'],bodyOf(main,'bool GoatDashCloseRetryWait(const long command_id)'))
  +fn('DashboardBusAckCommand',['command_id','ack_status'],bodyOf(main,'void DashboardBusAckCommand(const long command_id,const int ack_status)'))
  +fn('DashboardBusAckCloseCommand',['command_id','ack_status','closed_positions','close_errors','remaining'],
      bodyOf(main,'void DashboardBusAckCloseCommand(const long command_id,const int ack_status,const int closed_positions,const int close_errors,const int remaining)'))
  +fn('DashboardBusApplyCommand',['command_id','command_type','command_value','expires_at'],apply)
  +fn('DashboardBusProcessCommands',[],bodyOf(main,'void DashboardBusProcessCommands(void)'))
  +fn('InitPolicyRestore',[],initRestore)
  +'function finalAckId(){return g_goat_dash_final_ack_id;}\n';
 script=new vm.Script(code);
 return script;
}
// The dashboard's side: a command is four variables on the child's chart (Dashboard.mqh, SendPortfolioCommand).
function send(store,id,type,value,expires){
 store.set(KEY(DEF.GOAT_GV_FIELD_CMD_ID),id);store.set(KEY(DEF.GOAT_GV_FIELD_CMD_TYPE),type);
 store.set(KEY(DEF.GOAT_GV_FIELD_CMD_VALUE),value);store.set(KEY(DEF.GOAT_GV_FIELD_CMD_EXPIRES),expires);
}
// A restart: a new instance on the same store, OnInit's policy restore (which seeds the last final acknowledgement).
function restart(store,options){const c=instance(store,options);c.InitPolicyRestore();return c;}
const counts=c=>c.acks.length+' acknowledgement(s) and '+c.flushes+' flush(es)';
const once=(c,id,status,label)=>{
 assert.deepEqual([c.acks,c.flushes],[[[id,status]],1],label+': '+counts(c)+' over 120 timer ticks, want exactly 1 and 1');
};
const none=(c,label)=>assert.deepEqual([c.acks,c.flushes],[[],0],label+': '+counts(c)+' over 120 timer ticks, want none');
const ID=1731400000123,TICKS=120;

{// (a) An applied command: one acknowledgement and one flush over 120 ticks, whatever its type.
 for(const [label,type,value] of [['pause',PAUSE,1],['currency rules',PERM,DEF.GOAT_DASH_TRADE_ALLOW_BUY],['exposure policy',EXPO,1]]){
  const store=new Map(),c=instance(store);send(store,ID,type,value,c.now+30);c.ticks(TICKS);
  once(c,ID,A,'(a) applied '+label);
  assert.equal(c.DashboardPortfolioCommandIdApplied,ID,label+': applied');assert.equal(c.finalAckId(),ID);
 }
 const store=new Map(),c=instance(store);send(store,ID,PAUSE,1,c.now+30);c.ticks(TICKS);
 assert.equal(c.DashboardPortfolioPaused,true);assert.equal(store.get('P|DashboardPolicyPaused'),1);assert.equal(store.get(KEY(DEF.GOAT_GV_FIELD_POLICY_PAUSED)),1);
 // No stored command, or a zero id: nothing, as before.
 const e=instance(new Map());e.ticks(TICKS);none(e,'no command');
 const z=instance(new Map());send(z.store,0,PAUSE,1,z.now+30);z.ticks(TICKS);none(z,'command id 0');
 ok();}

{// (b) A restart. The stored command id stays in the terminal's store; the instance's applied id starts at 0 again.
 // b1. This chart applied the command before the restart: no new acknowledgement, no flush, the stored status stays
 // APPLIED (it was overwritten EXPIRED every second), and the pause comes back from its own variable, not a re-apply.
 {const store=new Map(),first=instance(store);send(store,ID,PAUSE,1,first.now+30);first.ticks(3);once(first,ID,A,'before the restart');
  const c=restart(store,{now:5000});
  const seeded=c.finalAckId();
  c.ticks(TICKS);none(c,'(b) restart on an already acknowledged (applied) command');
  assert.equal(seeded,ID,'(b) OnInit seeds the last final acknowledgement from the chart\'s ACKID');
  assert.equal(store.get(KEY(DEF.GOAT_GV_FIELD_ACK_STATUS)),A,'the stored acknowledgement stays APPLIED');
  assert.deepEqual([c.DashboardPortfolioPaused,c.DashboardPortfolioCommandIdApplied],[true,0],'paused restored from DashboardPolicyPaused; nothing re-applied');}
 // b2. The same inside the command's 30 s: the applied command is not applied a second time.
 {const store=new Map(),first=instance(store);send(store,ID,PAUSE,1,first.now+30);first.ticks(3);
  const c=restart(store,{now:1010});c.ticks(TICKS);none(c,'(b) restart inside the 30 s on an applied command');
  assert.equal(c.DashboardPortfolioPaused,true);}
 // b3. Stored EXPIRED and REJECTED acknowledgements are final too.
 for(const status of [X,R]){const store=new Map();send(store,ID,PAUSE,1,1030);store.set(KEY(DEF.GOAT_GV_FIELD_ACK_ID),ID);store.set(KEY(DEF.GOAT_GV_FIELD_ACK_STATUS),status);
  const c=restart(store,{now:5000});c.ticks(TICKS);none(c,'(b) restart on a stored final status '+status);}
 // b4. A stored expired command this chart never acknowledged (it arrived while the EA was down): EXPIRED once.
 {const store=new Map();send(store,ID,PAUSE,1,1030);
  const c=restart(store,{now:5000});assert.equal(c.finalAckId(),0);c.ticks(TICKS);
  once(c,ID,X,'(b) stored expired command after a restart');assert.equal(c.DashboardPortfolioPaused,false,'an expired pause is not applied');}
 // b5. The stored acknowledgement is another command's (an older id): the newer stored command is not skipped.
 {const store=new Map(),first=instance(store);send(store,ID-5,PAUSE,0,first.now+30);first.ticks(3);
  send(store,ID,PAUSE,1,5030);
  const c=restart(store,{now:5000});assert.equal(c.finalAckId(),ID-5);c.ticks(TICKS);
  once(c,ID,A,'(b) a command sent while the EA was down, unexpired');assert.equal(c.DashboardPortfolioPaused,true);}
 // b6. A close still in progress at the restart (stored FAILED) is not final: not seeded. Inside its 30 s it is retried
 // until flat; after them it is EXPIRED once.
 {const store=new Map(),first=instance(store,{positions:2,refuse:99});send(store,ID,CLOSE,0,first.now+30);first.ticks(3);
  assert.deepEqual(first.acks,[[ID,F]]);
  const c=restart(store,{now:1004,positions:2});assert.equal(c.finalAckId(),0,'a FAILED acknowledgement is not seeded');
  c.ticks(TICKS);
  assert.deepEqual([c.closes,c.open,c.acks,c.flushes],[1,0,[[ID,A]],1],'(b) a close in progress at the restart is retried, then APPLIED once');
  const late=restart(new Map(store).set(KEY(DEF.GOAT_GV_FIELD_ACK_STATUS),F),{now:5000,positions:2});late.ticks(TICKS);
  assert.deepEqual([late.closes,late.acks,late.flushes],[0,[[ID,X]],1],'(b) a failed close after its expiry: EXPIRED once');}
 // b7. A stored id without a status, or a zero id, seeds nothing.
 {const store=new Map([[KEY(DEF.GOAT_GV_FIELD_ACK_ID),ID]]);assert.equal(restart(store).finalAckId(),0);
  const zero=new Map([[KEY(DEF.GOAT_GV_FIELD_ACK_ID),0],[KEY(DEF.GOAT_GV_FIELD_ACK_STATUS),A]]);assert.equal(restart(zero).finalAckId(),0);}
 // The seeding is OnInit's, with the policy restore (the block that runs once per EA load, after MAGIC1 is known).
 assert.match(initRestore,/^\s*GoatDashSeedFinalAck\(\);/m,'OnInit seeds');
 ok();}

{// (c) A rejected (unknown) command type: REJECTED once.
 const store=new Map(),c=instance(store);send(store,ID,99,0,c.now+30);c.ticks(TICKS);
 once(c,ID,R,'(c) rejected command type');
 // An expired command with no restart (sent already expired): EXPIRED once.
 const s2=new Map(),e=instance(s2);send(s2,ID,PAUSE,1,e.now-1);e.ticks(TICKS);once(e,ID,X,'an expired command');
 ok();}

{// (f) in one line: a close that keeps failing and never expires is tried every 5 s (24 times in 120 ticks), and its
 // unchanged FAILED acknowledgement is written and flushed once. The loop below has the detail.
 const s=new Map(),n=instance(s,{positions:2,refuse:999});send(s,ID,CLOSE,0,0);n.ticks(TICKS);
 assert.deepEqual([n.closes,n.acks.length,n.flushes],[24,1,1],'(f) a close that keeps failing, '+n.closes+' tries (want 24: every 5 s, no expiry): '+counts(n)+' over 120 timer ticks, want 1 and 1');}
for(const [label,type] of [['portfolio close',CLOSE],['close scope',SCOPE]]){
 {// (d) A close that is not flat on the first tries is retried every 5 s (B49b F3 DASH-04) until flat, then APPLIED once.
  const store=new Map(),c=instance(store,{positions:2,refuse:2});send(store,ID,type,0,c.now+30);
  c.ticks(10);
  assert.deepEqual([c.closes,c.open,c.acks,c.flushes,c.DashboardPortfolioCommandIdApplied,c.finalAckId()],[2,2,[[ID,F]],1,0,0],'(d) '+label+': failed twice (0 s, 5 s), still in progress: '+counts(c)+', want FAILED written and flushed once');
  c.ticks(1);
  assert.deepEqual([c.closes,c.open,c.acks.at(-1),c.DashboardPortfolioCommandIdApplied,c.finalAckId()],[3,0,[ID,A],ID,ID],'(d) '+label+': flat on the third try (10 s), applied');
  c.ticks(TICKS-11);
  assert.deepEqual([c.closes,c.acks,c.flushes],[3,[[ID,F],[ID,A]],2],'(d) '+label+': '+counts(c)+', want FAILED once, APPLIED once, then nothing');
  assert.equal(store.get(KEY(DEF.GOAT_GV_FIELD_ACK_REMAINING)),0);assert.equal(store.get(KEY(DEF.GOAT_GV_FIELD_ACK_CLOSED)),2);
  // A close that is flat at once: one try, APPLIED once.
  const s2=new Map(),o=instance(s2,{positions:2});send(s2,ID,type,0,o.now+30);o.ticks(TICKS);
  assert.equal(o.closes,1);once(o,ID,A,'(d) '+label+' flat at once');}
 {// (f) A close that keeps failing: tried as before, 7 times in the command's 30 s (0, 5, ..., 30 s), then EXPIRED once.
  // Its unchanged FAILED acknowledgement is written and flushed once, not 7 times.
  const store=new Map(),c=instance(store,{positions:2,refuse:999});send(store,ID,type,0,c.now+30);c.ticks(TICKS);
  assert.equal(c.closes,7,'(f) '+label+': '+c.closes+' close tries, want 7 (0, 5, ..., 30 s), as B49b');
  assert.deepEqual([c.acks,c.flushes],[[[ID,F],[ID,X]],2],'(f) '+label+' that keeps failing: '+counts(c)+', want FAILED once and EXPIRED once');
  assert.equal(c.DashboardPortfolioCommandIdApplied,0);assert.equal(c.finalAckId(),ID,'EXPIRED is final');
  // Without an expiry (expires_at 0) the retry never stops: every 5 s over the 120 ticks, still one write and flush.
  const s2=new Map(),n=instance(s2,{positions:2,refuse:999});send(s2,ID,type,0,0);n.ticks(TICKS);
  assert.equal(n.closes,24,'(f) '+label+' with no expiry: '+n.closes+' close tries, want 24 (every 5 s)');
  assert.deepEqual([n.acks,n.flushes,n.finalAckId()],[[[ID,F]],1,0],'(f) '+label+' with no expiry, unchanged values: '+counts(n)+', want 1 and 1');
  // The values change (a position goes: remaining 2 -> 1, errors 2 -> 1): written and flushed again, once.
  const s3=new Map(),v=instance(s3,{positions:2,refuse:999});send(s3,ID,type,0,0);v.ticks(50);v.open=1;v.ticks(TICKS-50);
  assert.deepEqual([v.acks,v.flushes],[[[ID,F],[ID,F]],2],'(f) '+label+', remaining 2 then 1: '+counts(v)+', want one per change');
  assert.deepEqual([s3.get(KEY(DEF.GOAT_GV_FIELD_ACK_REMAINING)),s3.get(KEY(DEF.GOAT_GV_FIELD_ACK_ERRORS))],[1,1],'the stored acknowledgement is the latest');
  // A new failing close command with the same values is its own acknowledgement.
  send(s3,ID+1,type,0,0);v.ticks(TICKS);
  assert.deepEqual([v.acks.at(-1),v.flushes],[[ID+1,F],3],'(f) '+label+': a new command\'s first FAILED is written');}
 ok();
}

{// (e) A new command id after a final one is processed normally, each once.
 const store=new Map(),c=instance(store);send(store,ID,PAUSE,1,c.now+30);c.ticks(60);
 send(store,ID+1,PAUSE,0,c.now+30);c.ticks(60);
 assert.deepEqual([c.acks,c.flushes,c.DashboardPortfolioPaused],[[[ID,A],[ID+1,A]],2,false],'(e) a new command after a final one: '+counts(c));
 // After a rejected and after an expired one too.
 const s2=new Map(),r=instance(s2);send(s2,ID,99,0,r.now+30);r.ticks(60);send(s2,ID+1,-1,0,r.now-1);r.ticks(60);send(s2,ID+2,EXPO,1,r.now+30);r.ticks(TICKS);
 assert.deepEqual([r.acks,r.flushes],[[[ID,R],[ID+1,X],[ID+2,A]],3],'(e) rejected, expired, applied: '+counts(r));
 // After a restart on an acknowledged command, the next command is processed.
 const c2=restart(store,{now:9000});c2.ticks(10);send(store,ID+2,PAUSE,1,c2.now+30);c2.ticks(TICKS);
 once(c2,ID+2,A,'(e) a new command after a restart');
 ok();}

{// (g) A poll during a publish (Codex on GOAT-EA#330). The dashboard writes one child's command as consecutive
 // GlobalVariableSet lines; their order, and whether a line clears the id (0.0) or writes the value, come from each of
 // Dashboard.mqh's publish sites, which must all agree.
 const sites=[];let site=null,prev=-2;
 dash.split('\n').forEach((line,i)=>{
  const m=line.match(/^\s*GlobalVariableSet\(GoatChildGVName\(g_sets\[idx\]\.magic,g_sets\[idx\]\.sym,(GOAT_GV_FIELD_CMD_\w+)\),([^;]*)\);/);
  if(!m)return;if(i!==prev+1){site=[];sites.push(site);}prev=i;
  site.push([DEF[m[1]],m[2].trim()==='0.0'?'clear':'value']);
 });
 assert.equal(sites.length,4,'Dashboard.mqh has four command publish sites (currency rules, close scope, exposure policy, portfolio)');
 for(const s of sites)assert.deepEqual(s,sites[0],'every publish site writes the command in one order');
 const WRITES=sites[0];
 for(const f of [DEF.GOAT_GV_FIELD_CMD_TYPE,DEF.GOAT_GV_FIELD_CMD_VALUE,DEF.GOAT_GV_FIELD_CMD_EXPIRES,DEF.GOAT_GV_FIELD_CMD_ID])
  assert.ok(WRITES.some(([g,k])=>g===f&&k==='value'),'a publish writes '+f);
 // Every way to spread the publish's writes over one poll's reads (k writes before the poll's r-th read; the rest after
 // the poll): compositions of the writes into the poll's read slots plus one slot after it. READS = what one poll of a
 // whole new command reads (the store's reads counted), so every slot is a real read.
 const OLD=[ID,PERM,DEF.GOAT_DASH_TRADE_ALLOW_BUY],NEW=[ID+1,PAUSE,1];
 const READS=(()=>{const store=new Map(),c=instance(store);send(store,NEW[0],NEW[1],NEW[2],c.now+30);let n=0;
  const g=c.GlobalVariableGet,k=c.GlobalVariableCheck;c.GlobalVariableGet=x=>{n++;return g(x);};c.GlobalVariableCheck=x=>{n++;return k(x);};c.ticks(1);return n;})();
 assert.ok(READS>=5&&READS<=12,'one poll reads the command ('+READS+' reads)');
 function* spreads(left,slots){if(slots===1){yield [left];return;}for(let k=0;k<=left;k++)for(const rest of spreads(left-k,slots-1))yield [k,...rest];}
 const choose=(n,k)=>{let r=1;for(let i=1;i<=k;i++)r=r*(n-k+i)/i;return Math.round(r);};
 let tried=0;
 for(const seen of [true,false]){   // the child finished the older command already / it had not read it yet
  for(const spread of spreads(WRITES.length,READS+1)){
   const store=new Map(),c=instance(store);
   const oldExpires=seen?c.now+30:c.now+20;send(store,OLD[0],OLD[1],OLD[2],oldExpires);
   if(seen){c.ticks(40);assert.deepEqual(c.acks,[[ID,A]]);}   // applied, then its expiry passes: 40 s later, as Codex's case
   const newExpires=c.now+30,value={[DEF.GOAT_GV_FIELD_CMD_ID]:NEW[0],[DEF.GOAT_GV_FIELD_CMD_TYPE]:NEW[1],[DEF.GOAT_GV_FIELD_CMD_VALUE]:NEW[2],[DEF.GOAT_GV_FIELD_CMD_EXPIRES]:newExpires};
   const queue=WRITES.map(([f,k])=>[KEY(f),k==='clear'?0:value[f]]);
   const applied=[];const realApply=c.DashboardBusApplyCommand;
   c.DashboardBusApplyCommand=(...a)=>{applied.push(a);return realApply(...a);};
   const realGet=c.GlobalVariableGet,realCheck=c.GlobalVariableCheck;let r=0;
   const step=()=>{const n=r<READS?spread[r]:0;r++;for(let i=0;i<n;i++){const [k,v]=queue.shift();store.set(k,v);}};
   c.GlobalVariableGet=k=>{step();return realGet(k);};c.GlobalVariableCheck=k=>{step();return realCheck(k);};
   c.ticks(1);   // the one poll the publish runs through
   c.GlobalVariableGet=realGet;c.GlobalVariableCheck=realCheck;
   while(queue.length){const [k,v]=queue.shift();store.set(k,v);}   // the publish ends
   c.ticks(60);
   const whole=[[...OLD,oldExpires],[...NEW,newExpires]].map(x=>JSON.stringify(x));
   for(const a of applied)assert.ok(whole.includes(JSON.stringify(a)),'(g) '+(seen?'after':'before')+' the older command, writes spread '+spread.join('')+': the child applied '+JSON.stringify(a)+', not one whole command');
   assert.deepEqual(c.acks.filter(([id])=>id===ID+1),[[ID+1,A]],'(g) '+(seen?'after':'before')+' the older command, writes spread '+spread.join('')+': the new command\'s acknowledgements '+JSON.stringify(c.acks)+', want APPLIED once');
   assert.equal(c.DashboardPortfolioPaused,true,'(g) the new pause is in force');
   tried++;
  }
 }
 assert.equal(tried,2*choose(WRITES.length+READS,READS),'(g) every interleaving of '+WRITES.length+' writes with '+READS+' reads, twice');
 interleaving={reads:READS,writes:WRITES.length,tried};
 ok();}

{// Batch and dashboard charts never use the bus: nothing is seeded, processed or flushed there.
 for(const mode of [1,2]){const store=new Map();send(store,ID,PAUSE,1,5030);store.set(KEY(DEF.GOAT_GV_FIELD_ACK_ID),ID-1);store.set(KEY(DEF.GOAT_GV_FIELD_ACK_STATUS),A);
  const c=restart(store,{now:5000,mode});assert.equal(c.finalAckId(),0);c.ticks(TICKS);none(c,'mode '+mode);}
 // The acknowledgement still flushes (once per command now), and the timer and the dashboard's event still call the bus.
 assert.match(bodyOf(main,'void DashboardBusAckCommand(const long command_id,const int ack_status)'),/GlobalVariablesFlush\(\);\s*$/,'the acknowledgement flushes');
 assert.equal(main.split('DashboardBusProcessCommands();').length-1,2,'the timer and the dashboard command event');
 ok();}

console.log(JSON.stringify({passed,test:'dash_ack_once',ticks:TICKS,interleaving}));
