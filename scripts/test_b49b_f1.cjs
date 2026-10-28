// B49b PR-2 (F1 full; split goatai#2587 6433828681 row 2, design 6474780229). The production code runs here from
// GOAT V1.49.mq5 (syntax-only MQL-to-JS conversion) against a modelled terminal, files and licence service:
// 1. Manage-only: which charts it applies to (the trading chart, live), how VerifyLicense's answer at OnInit maps to it
//    (an outage -> licence_unavailable, another refusal -> licence_refused, 401/403 and a valid licence unchanged), that
//    an expired build stays expired, that DashboardEntryAllowed refuses every new sequence and ManageOnlyFrozen every add.
// 2. The state file: each sequence's retrace, rescue, trailing and deferred-close section, written atomically, restored
//    all or nothing onto the basket its restart record matched; anything else (another basket's section, an incomplete
//    one, another login/magic/symbol/version, an unreadable file) is ignored. Nothing is written before the first tick
//    stamps the day; a failed write freezes adds until a write succeeds.
// 3. The day state (stop-out, daily baselines, restart cooldown, bias stop-out edges): back on the first tick's new-day
//    block only when the file is from that server day.
// 4. A live re-init (an input change) of a running sequence keeps its retrace, rescue and realized P/L.
// 5. OnInit after adoption and the timer: an outage retries every 5 minutes and ends on a valid licence; a refused
//    licence or an expired build with nothing open keeps B49a's INIT_FAILED, and removes the EA once flat.
// 6. Where it sits in OnInit, OnTick, OnTimer and OnDeinit, and the expiry paths.
// Live-only by construction (GoatManageOnlyLive): the tester's paths are B49a's, asserted in 1, 4 and 6.
// test_b49b_f1_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
 .replace(/^\s*static\s+bool\s+removing=false;\s*$/m,'')                    // GoatManageOnlyTimer's static lives in the context
 .replace(/\(long\)(\w+)\/86400/g,'Math.floor($1/86400)')                    // MQL long division
 .replace(/StringReplace\((\w+(?:\[\w+\])?),("(?:\\.|[^"])*"),("(?:\\.|[^"])*")\);/g,'$1=$1.split($2).join($3);') // by reference
 .replace(/GoatSetupRead\(([^,]+\)),(\w+)\)/g,'GoatSetupReadRef($1,v=>$2=v)')
 .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]\\s*=\\s*\\{([^}]*)\\};','g'),'let $1=[$2];')
 .replace(/\bstring\s+(\w+)\[\],(\w+)\[\];/g,'let $1=[],$2=[];')
 .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]','g'),'let $1=[]')
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
 .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const define=name=>{const m=main.match(new RegExp('^#define '+name+'\\s+(\\d+)\\s*$','m'));assert.ok(m,'missing #define '+name);return Number(m[1]);};
const NONE=define('GOAT_MANAGE_NONE'),DOWN=define('GOAT_MANAGE_LICENCE_DOWN'),REFUSED=define('GOAT_MANAGE_LICENCE_REFUSED'),EXPIRED=define('GOAT_MANAGE_EXPIRED');
const RETRY_MS=define('GOAT_LICENCE_RETRY_MS'),VERSION=define('GOAT_STATE_VERSION'),FLUSH_MS=define('GOAT_SQ_FLUSH_MS');
assert.deepEqual([NONE,DOWN,REFUSED,EXPIRED,RETRY_MS,VERSION,FLUSH_MS],[0,1,2,3,300000,1,5000]);
const VALID=Number((clean(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8')).match(/^#define LICENSE_VALID\s+(\d+)/m)||[])[1]);
assert.equal(VALID,1505);

const SIG={
 live:'bool GoatManageOnlyLive()',reason:'string GoatManageOnlyReason()',expiry:'bool GoatExpiryManageOnly()',
 licence:'bool GoatLicenceManageOnly(const int key)',value:'string GoatStateValue(const string &keys[],const string &values[],const string key)',
 entry:'bool DashboardEntryAllowed(const int op)',path:'string GoatStatePath()',stateLive:'bool GoatStateLive()',text:'string GoatStateText()',
 flush:'void GoatStateFlush(const bool force=false)',read:'bool GoatStateRead(string &keys[],string &values[])',restore:'void GoatStateRestore()',
 day:'void GoatStateDayRestore()',after:'bool GoatManageOnlyAfterAdopt()',timer:'void GoatManageOnlyTimer()',
 seqText:'   string StateText()',seqRestore:'   void StateRestore(const string &keys[],const string &values[])',
 frozen:'   bool ManageOnlyFrozen(const int level)',persistLive:'   bool PersistLive()',init:'   void Init(int OP,bool v)',reset:'   void ResetSequenceRiskState()',
};
const FLAGS=fn('GoatManageOnlyLive',[],bodyOf(main,SIG.live))+fn('GoatManageOnlyReason',[],bodyOf(main,SIG.reason))
 +fn('GoatExpiryManageOnly',[],bodyOf(main,SIG.expiry))+fn('GoatLicenceManageOnly',['key'],bodyOf(main,SIG.licence))
 +fn('GoatStateValue',['keys','values','key'],bodyOf(main,SIG.value));
const K={OP_BUY:0,OP_SELL:1,MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,Operation_Standard:0,Operation_Report:5,Operation_Batch:6,Operation_Dash:7,
 GOAT_MANAGE_NONE:NONE,GOAT_MANAGE_LICENCE_DOWN:DOWN,GOAT_MANAGE_LICENCE_REFUSED:REFUSED,GOAT_MANAGE_EXPIRED:EXPIRED,GOAT_LICENCE_RETRY_MS:RETRY_MS,
 GOAT_STATE_VERSION:VERSION,GOAT_SQ_FLUSH_MS:FLUSH_MS,LICENSE_VALID:VALID,FILE_COMMON:4096,ACCOUNT_LOGIN:'login',ACCOUNT_NAME:'name',ACCOUNT_SERVER:'server',
 TIME_DATE:1,URL_Web:'https://goatedge.ai',Expiry:1798675200,MAGIC1:1843920117,_Symbol:'EURUSD',_Digits:5};
const common=t=>({IntegerToString:v=>String(v),DoubleToString:(v,d)=>Number(v).toFixed(d),StringToDouble:s=>Number(s)||0,
 StringToInteger:s=>Math.trunc(Number(s)||0),StringFind:(s,x)=>s.indexOf(x),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.substr(a,n),
 StringSplit:(s,sep,arr)=>{arr.length=0;arr.push(...s.split(sep));return arr.length;},TimeToString:v=>'D'+v,
 ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push('');a.length=n;return n;},ArrayCopy:(d,s)=>{d.length=0;d.push(...s);return s.length;},
 MQLInfoInteger:k=>(k===1&&t.tester)?1:0,Print:(...a)=>t.logs.push(a.join('')),Alert:(...a)=>t.alerts.push(a.join('')),GetTickCount:()=>t.now});

// ---------------------------------------------------------------- 1. who is manage-only, and why
function flags({tester=false,mode=0,Mode='',state=NONE}={}){
 const t={tester,logs:[],alerts:[],now:1000};
 const c={...K,...common(t),Mode_Operation:mode,Mode,g_GoatManageOnly:state,g_GoatLicenceRetriedMs:0,t};
 vm.createContext(c);vm.runInContext(FLAGS,c);return c;
}
{// GoatManageOnlyLive: the trading chart, live; never the tester, the report/export tools, a batch or the dashboard.
 assert.equal(flags().GoatManageOnlyLive(),true);
 for(const o of [{tester:true},{mode:5},{mode:6},{mode:7},{Mode:'EXPORT'}]) assert.equal(flags(o).GoatManageOnlyLive(),false,JSON.stringify(o));
 // VerifyLicense's answers.
 for(const [key,want] of [[-1,DOWN],[-2,DOWN],[500,DOWN],[503,DOWN],[1001,DOWN],[1003,DOWN],[400,REFUSED],[402,REFUSED],[200,REFUSED]]){
  const c=flags();c.t.now=7777;assert.equal(c.GoatLicenceManageOnly(key),true,'key '+key);
  assert.equal(c.g_GoatManageOnly,want,'key '+key);assert.equal(c.g_GoatLicenceRetriedMs,7777,'the retry clock starts at init');
  assert.match(c.t.logs.at(-1),new RegExp('^GOAT manage-only: reason='+(want===DOWN?'licence_unavailable':'licence_refused')+' licence_status='+key+' new_trades=refused'));
 }
 for(const key of [VALID,401,403,0]){const c=flags();assert.equal(c.GoatLicenceManageOnly(key),false,'key '+key);assert.equal(c.g_GoatManageOnly,NONE);}
 for(const o of [{tester:true},{mode:5},{mode:7}]){const c=flags(o);assert.equal(c.GoatLicenceManageOnly(503),false);assert.equal(c.g_GoatManageOnly,NONE,'B49a INIT_FAILED stays off the trading chart');}
 // An expired build stays expired when the licence is also down: a licence that comes back never lifts expiry.
 {const c=flags({state:EXPIRED});assert.equal(c.GoatLicenceManageOnly(503),true);assert.equal(c.g_GoatManageOnly,EXPIRED);}
 // GoatExpiryManageOnly: live, once; the tester keeps B49a's expiry.
 {const c=flags();assert.equal(c.GoatExpiryManageOnly(),true);assert.equal(c.GoatExpiryManageOnly(),true);assert.equal(c.g_GoatManageOnly,EXPIRED);
  assert.equal(c.t.logs.filter(l=>/reason=expired/.test(l)).length,1,'said once');}
 {const c=flags({state:DOWN});c.GoatExpiryManageOnly();assert.equal(c.g_GoatManageOnly,EXPIRED,'expiry outranks an outage');}
 {const c=flags({tester:true});assert.equal(c.GoatExpiryManageOnly(),false);assert.equal(c.g_GoatManageOnly,NONE);}
 assert.deepEqual([NONE,DOWN,REFUSED,EXPIRED].map(s=>flags({state:s}).GoatManageOnlyReason()),['none','licence_unavailable','licence_refused','expired']);
 ok();}
{// DashboardEntryAllowed: every start path passes through it (Add_Level's virtual->real hand-off and the signal block).
 const run=(state,{cid=false}={})=>{const c={g_GoatManageOnly:state,GOAT_MANAGE_NONE:NONE,MAGIC1:1,g_GoatStudioMonitorRunPath:'',Symbol:()=>'EURUSD',
  GoatCidGuardRefuses:()=>cid,GoatStagedChildMayOpen:()=>true,DashboardTradeAllowed:()=>true,DashboardExposureConflict:()=>false};
  vm.createContext(c);vm.runInContext(fn('DashboardEntryAllowed',['op'],bodyOf(main,SIG.entry)),c);return c.DashboardEntryAllowed(0);};
 assert.equal(run(NONE),true);for(const s of [DOWN,REFUSED,EXPIRED]) assert.equal(run(s),false,'manage-only '+s+' opens nothing');
 assert.equal(run(NONE,{cid:true}),false,'B46 still refuses');
 const body=bodyOf(main,SIG.entry).split('\n').filter(l=>l.trim());
 assert.match(body[0],/GoatCidGuardRefuses\(true\)\) return false; \/\/ B46/,'B46 stays the first refusal');
 const callers=main.split('DashboardEntryAllowed(').length-2;assert.equal(callers,7,'the start paths are the same seven callers');
 ok();}

// ---------------------------------------------------------------- 2. one SEQUENCE (its own context, as an MQL object)
function sequence(ea,{dir=0,virtual=false,active=true,traded=true,adopted=true,matched=true,sizes=true,start=1792054800000,ticket=901}={}){
 const t=ea.t;
 const c={...K,...common(t),dir,Virtual:virtual,Active:active,Traded:traded,Adopted:adopted,AdoptMatched:matched,AdoptSizes:sizes,
  Desc:'Trend '+(dir?'Sell':'Buy'),Strat:'Trend',PersistStartMsc:start,PersistFirstTicket:ticket,PersistFailed:false,ManageOnlyLogged:false,
  Level_Retrace:0,Retrace_Triggered:false,BiasRescueActive:false,BiasRescueBEProtected:false,BiasRescuePositiveAdds:0,BiasRescueBEPrice:0,
  BiasRescueSLPrice:0,Trailing:false,ClosePendingReason:'',ClosePendingTried:0,SequenceRealizedPL:0,Trades_Count:3,Level_Count:3,
  LedgerPositions:[],LedgerDeals:[],TradeLevels:[],Ledger_Mode:0,Ledger_PositionJoin:1,updates:0,UpdateLockTPSL:n=>{c.updates++;},
  LedgerAddPosition:()=>{},
  get Mode_Operation(){return ea.Mode_Operation;},get Mode(){return ea.Mode;},
  get g_GoatManageOnly(){return ea.g_GoatManageOnly;},get g_GoatStateFailed(){return ea.g_GoatStateFailed;},
  GoatManageOnlyReason:()=>ea.GoatManageOnlyReason()};
 vm.createContext(c);
 vm.runInContext(FLAGS.split('function GoatExpiryManageOnly')[0]+fn('GoatStateValue',['keys','values','key'],bodyOf(main,SIG.value))
  +fn('PersistLive',[],bodyOf(main,SIG.persistLive))+fn('StateText',[],bodyOf(main,SIG.seqText))
  +fn('StateRestore',['keys','values'],bodyOf(main,SIG.seqRestore))+fn('ManageOnlyFrozen',['level'],bodyOf(main,SIG.frozen))
  +fn('ResetSequenceRiskState',[],bodyOf(main,SIG.reset))+fn('Init',['OP','v'],bodyOf(main,SIG.init)),c);
 return c;
}
// ---------------------------------------------------------------- the EA: globals, the state file, the licence service
function ea({tester=false,mode=0,state=NONE,files=new Map(),licence=[]}={}){
 const t={tester,logs:[],alerts:[],now:100000,files,writes:0,failWrite:false,unreadable:false,licence:[...licence],verifies:0,removed:0,sleeps:[]};
 const c={...K,...common(t),t,Mode_Operation:mode,Mode:'',g_GoatManageOnly:state,g_GoatLicenceRetriedMs:0,g_GoatStateFailed:false,
  g_GoatLastStopOutB:false,g_GoatLastStopOutS:false,g_GoatStateLast:'',g_GoatStateWrittenMs:0,g_GoatStateDay:0,g_GoatDayRestorePending:false,
  g_GoatDayKeys:[],g_GoatDayValues:[],removing:false,StopOut_Flag:false,DStartEquity:10000,DStartLocalLoss:99999,DStartTime:0,LastStopoutTime:0,
  tm_cur:1792054800+3600,AccountInfoInteger:k=>k==='login'?907113355:0,AccountInfoString:k=>k,
  FolderCreate:()=>true,FileIsExist:p=>t.files.has(p),
  GoatSetupWrite:(p,body)=>{t.writes++;if(t.failWrite)return false;t.files.set(p,body);return true;},
  GoatSetupReadRef:(p,set)=>{if(t.unreadable||!t.files.has(p))return false;set(t.files.get(p));return true;},
  GetLastError:()=>5004,Sleep:ms=>t.sleeps.push(ms),ExpertRemove:()=>{t.removed++;},
  VerifyLicense:()=>{t.verifies++;return t.licence.length?t.licence.shift():503;}};
 vm.createContext(c);
 vm.runInContext(FLAGS+['path','stateLive','text','read','restore','day','after','timer'].map(k=>{
  const name=SIG[k].match(/\s(\w+)\(/)[1],args=(SIG[k].match(/\((.*)\)/)[1].match(/(\w+)(?:\[\])?(?:=\w+)?(?=,|$)/g)||[]).map(a=>a.replace('[]',''));
  return fn(name,args,bodyOf(main,SIG[k]));}).join('')+fn('GoatStateFlush',['force=false'],bodyOf(main,SIG.flush)),c);
 c.Seq_Buy=sequence(c,{dir:0});c.Seq_Sell=sequence(c,{dir:1,active:false,traded:false,adopted:false,matched:false});
 return c;
}
const PATH='GOAT\\State\\907113355\\1843920117_EURUSD.txt';

{// StateText / StateRestore: the round trip, all or nothing, onto the matched basket only.
 const a=ea();const s=a.Seq_Buy;
 Object.assign(s,{Level_Retrace:1.08765,Retrace_Triggered:true,BiasRescueActive:true,BiasRescueBEProtected:true,BiasRescuePositiveAdds:2,
  BiasRescueBEPrice:1.0912,BiasRescueSLPrice:1.0855,Trailing:true,ClosePendingReason:'Day/Weekend\nClose',ClosePendingTried:1792058400});
 const text=s.StateText();
 assert.match(text,/^B\.start_msc=1792054800000\nB\.first_ticket=901\n/);assert.match(text,/\nB\.close_reason=Day\/Weekend Close\n$/,'one line, newline-free');
 assert.equal(a.Seq_Sell.StateText(),'','an idle sequence writes no section');
 const parse=x=>{const k=[],v=[];for(const l of x.split('\n')){const e=l.indexOf('=');if(e>0){k.push(l.slice(0,e));v.push(l.slice(e+1));}}return [k,v];};
 const fresh=()=>sequence(a,{dir:0});
 {const r=fresh();r.StateRestore(...parse(text));
  assert.deepEqual([r.Level_Retrace,r.Retrace_Triggered,r.BiasRescueActive,r.BiasRescueBEProtected,r.BiasRescuePositiveAdds,r.BiasRescueBEPrice,r.BiasRescueSLPrice,r.Trailing,r.ClosePendingReason,r.ClosePendingTried],
   [1.08765,true,true,true,2,1.0912,1.0855,true,'Day/Weekend Close',1792058400]);
  assert.equal(r.updates,1,'the rescue BE and trailing apply at once');assert.match(a.t.logs.at(-1),/^GOAT state: Trend Buy restored retrace=1\.08765 triggered=1 rescue=1 be_protected=1 trailing=1 close_pending=Day\/Weekend Close$/);}
 {const r=sequence(a,{dir:0,sizes:false});r.StateRestore(...parse(text));assert.equal(r.updates,0,'without frozen sizes the broker SL/TP stay untouched');assert.equal(r.Trailing,true);}
 // Another basket's section (start or first ticket differ), an incomplete one, an unmatched or unadopted basket: nothing.
 for(const [label,mut] of [['another start',x=>x.replace('B.start_msc=1792054800000','B.start_msc=1792054800001')],['another first ticket',x=>x.replace('B.first_ticket=901','B.first_ticket=902')],
  ['incomplete',x=>x.replace(/B\.trailing=1\n/,'')]]){
  const r=fresh();r.StateRestore(...parse(mut(text)));assert.deepEqual([r.Level_Retrace,r.Trailing,r.BiasRescueActive,r.updates],[0,false,false,0],label);
  assert.match(a.t.logs.at(-1),/section ignored/,label);}
 for(const o of [{matched:false},{adopted:false}]){const r=sequence(a,{dir:0,...o});r.StateRestore(...parse(text));assert.equal(r.Trailing,false,JSON.stringify(o));}
 {const r=sequence(a,{dir:1});r.StateRestore(...parse(text));assert.equal(r.Trailing,false,'a sell takes only S. lines');}
 // Not live (the tester, a virtual sequence, a batch) or not yet recorded: no section.
 assert.equal(ea({tester:true}).Seq_Buy.StateText(),'');assert.equal(sequence(a,{virtual:true}).StateText(),'');
 assert.equal(sequence(a,{start:0}).StateText(),'');assert.equal(ea({mode:6}).Seq_Buy.StateText(),'');
 ok();}
{// ManageOnlyFrozen: manage-only and an unwritten state file freeze adds too.
 const a=ea();const s=sequence(a,{adopted:false});
 assert.equal(s.ManageOnlyFrozen(4),false);
 for(const [set,why] of [[()=>{a.g_GoatManageOnly=DOWN;},'licence_unavailable'],[()=>{a.g_GoatManageOnly=EXPIRED;},'expired'],[()=>{a.g_GoatStateFailed=true;},'state_unwritten']]){
  a.g_GoatManageOnly=NONE;a.g_GoatStateFailed=false;s.ManageOnlyFrozen(4);set();
  assert.equal(s.ManageOnlyFrozen(4),true,why);assert.match(a.t.logs.at(-1),new RegExp('^GOAT restart: add_frozen='+why+' side=BUY'),why);}
 a.g_GoatManageOnly=NONE;a.g_GoatStateFailed=false;assert.equal(s.ManageOnlyFrozen(4),false,'adds resume when both clear');
 ok();}
{// Init: a live re-init (an input change) of a running real sequence keeps retrace, rescue and realized P/L (GOAT-EA#266 P3).
 const run=o=>{const a=ea(o.ea);const s=sequence(a,{adopted:false,active:o.active!==false,virtual:!!o.virtual});
  Object.assign(s,{Level_Retrace:1.2,Retrace_Triggered:true,BiasRescueActive:true,SequenceRealizedPL:-86.5});s.Init(0,!!o.virtual);
  return [s.Level_Retrace,s.Retrace_Triggered,s.BiasRescueActive,s.SequenceRealizedPL];};
 assert.deepEqual(run({}),[1.2,true,true,-86.5]);
 for(const o of [{active:false},{virtual:true},{ea:{tester:true}},{ea:{mode:7}}]) assert.deepEqual(run(o),[0,false,false,0],'B49a reset: '+JSON.stringify(o));
 ok();}

// ---------------------------------------------------------------- 3. the file and the day state across a restart
{const files=new Map();const a=ea({files});
 // Before the first tick has stamped the day nothing is written (a fresh init never overwrites the file it restores).
 a.GoatStateFlush(true);assert.equal(a.t.writes,0);
 a.GoatStateDayRestore();assert.equal(a.g_GoatStateDay,Math.floor((1792054800+3600)/86400));
 Object.assign(a,{StopOut_Flag:true,DStartEquity:10250.5,DStartLocalLoss:-12.25,DStartTime:1792051200,LastStopoutTime:1792054000,g_GoatLastStopOutB:true});
 Object.assign(a.Seq_Buy,{Level_Retrace:1.0877,Retrace_Triggered:true,Trailing:true});
 a.GoatStateFlush();assert.equal(a.t.writes,1);const body=files.get(PATH);
 assert.ok(body.startsWith('version=1\nlogin=907113355\nmagic=1843920117\nsymbol=EURUSD\nday='+a.g_GoatStateDay+'\nstopout=1\ndstart_equity=10250.50\n'),body);
 assert.match(body,/\nB\.level_retrace=1\.08770000\n/);assert.doesNotMatch(body,/\nS\./,'no section for the idle sell');
 // A change waits for GOAT_SQ_FLUSH_MS unless forced; unchanged text is never rewritten, forced or not.
 a.Seq_Buy.Trailing=false;a.t.now+=1;a.GoatStateFlush();assert.equal(a.t.writes,1,'within the flush interval');
 a.t.now+=FLUSH_MS;a.GoatStateFlush();assert.equal(a.t.writes,2);
 a.t.now+=FLUSH_MS;a.GoatStateFlush();a.GoatStateFlush(true);assert.equal(a.t.writes,2,'unchanged');
 a.Seq_Buy.Retrace_Triggered=false;a.GoatStateFlush(true);assert.equal(a.t.writes,3,'forced');a.Seq_Buy.Retrace_Triggered=true;
 // A failed write freezes adds (said once) until a write succeeds.
 a.t.failWrite=true;a.Seq_Buy.Trailing=true;a.GoatStateFlush(true);a.GoatStateFlush(true);
 assert.equal(a.g_GoatStateFailed,true);assert.equal(a.t.alerts.filter(x=>/GOAT state file not written/.test(x)).length,1);
 a.t.failWrite=false;a.GoatStateFlush(true);assert.equal(a.g_GoatStateFailed,false);assert.match(a.t.logs.at(-1),/written again/);
 // The restart: a fresh EA over the same files; the matched buy takes its section back; the day waits for the first tick.
 const b=ea({files});b.Seq_Buy=sequence(b,{dir:0});b.GoatStateRestore();
 assert.deepEqual([b.Seq_Buy.Level_Retrace,b.Seq_Buy.Retrace_Triggered,b.Seq_Buy.Trailing],[1.0877,true,true]);
 assert.equal(b.g_GoatDayRestorePending,true);assert.equal(b.StopOut_Flag,false,'not before the new-day block');
 // The first tick's new-day block (its resets, then the restore): today's day state is back.
 Object.assign(b,{LastStopoutTime:0,StopOut_Flag:false,DStartLocalLoss:99999,DStartEquity:9999});b.GoatStateDayRestore();
 assert.deepEqual([b.StopOut_Flag,b.DStartEquity,b.DStartLocalLoss,b.DStartTime,b.LastStopoutTime,b.g_GoatLastStopOutB,b.g_GoatLastStopOutS],[true,10250.5,-12.25,1792051200,1792054000,true,false]);
 assert.equal(b.g_GoatDayRestorePending,false);
 // Only once: a later new day keeps its own reset.
 Object.assign(b,{StopOut_Flag:false,tm_cur:b.tm_cur+86400});b.GoatStateDayRestore();assert.equal(b.StopOut_Flag,false);
 // A file from yesterday: the new day starts fresh.
 const c=ea({files});c.GoatStateRestore();c.tm_cur+=86400;Object.assign(c,{StopOut_Flag:false,DStartEquity:9999});c.GoatStateDayRestore();
 assert.deepEqual([c.StopOut_Flag,c.DStartEquity],[false,9999]);assert.match(c.t.logs.at(-1),/not today's/);
 // An incomplete day section, or one without a start equity: fresh.
 for(const [label,mut] of [['no stopout line',x=>x.replace(/\nstopout=1/,'')],['no start equity',x=>x.replace(/dstart_equity=10250\.50/,'dstart_equity=0.00')]]){
  const f=new Map([[PATH,mut(files.get(PATH))]]);const d=ea({files:f});d.GoatStateRestore();Object.assign(d,{DStartEquity:9999,LastStopoutTime:0});d.GoatStateDayRestore();
  assert.deepEqual([d.StopOut_Flag,d.DStartEquity,d.LastStopoutTime],[false,9999,0],label+': nothing comes back');}
 // Another login, magic, symbol or version, or an unreadable file: ignored, B49a behaviour.
 for(const [label,mut] of [['login',x=>x.replace('login=907113355','login=1')],['magic',x=>x.replace('magic=1843920117','magic=2')],['symbol',x=>x.replace('symbol=EURUSD','symbol=GBPUSD')],['version',x=>x.replace('version=1','version=2')]]){
  const f=new Map([[PATH,mut(files.get(PATH))]]);const d=ea({files:f});d.Seq_Buy=sequence(d,{dir:0});d.GoatStateRestore();
  assert.deepEqual([d.Seq_Buy.Trailing,d.g_GoatDayRestorePending],[false,false],label);assert.match(d.t.logs.at(-1),/another version, login, magic or symbol's/,label);}
 {const d=ea({files});d.t.unreadable=true;d.Seq_Buy=sequence(d,{dir:0});d.GoatStateRestore();assert.equal(d.Seq_Buy.Trailing,false);assert.match(d.t.logs.at(-1),/unreadable/);}
 {const d=ea({files:new Map()});d.GoatStateRestore();assert.equal(d.g_GoatDayRestorePending,false);assert.deepEqual(d.t.logs,[],'no file: nothing said');}
 // The tester, a batch, the dashboard: never read or written.
 for(const o of [{tester:true},{mode:6},{mode:7}]){const d=ea({...o,files});d.g_GoatStateDay=5;d.GoatStateFlush(true);d.GoatStateRestore();
  assert.deepEqual([d.t.writes,d.g_GoatDayRestorePending],[0,false],JSON.stringify(o));}
 ok();}

// ---------------------------------------------------------------- 5. OnInit after adoption, and the timer
{const holding=(a,h)=>{a.Seq_Buy.Active=h;a.Seq_Sell.Active=false;};
 {const a=ea();assert.equal(a.GoatManageOnlyAfterAdopt(),true);assert.deepEqual(a.t.alerts,[]);}
 {const a=ea({state:EXPIRED});holding(a,false);assert.equal(a.GoatManageOnlyAfterAdopt(),false,'expired and flat: INIT_FAILED');assert.match(a.t.alerts[0],/^This version expired on D1798675200\. Go to /);}
 {const a=ea({state:EXPIRED});holding(a,true);assert.equal(a.GoatManageOnlyAfterAdopt(),true);assert.match(a.t.alerts[0],/expired .* GOAT manages its open positions .* it stops once they are closed\.$/);}
 {const a=ea({state:REFUSED});holding(a,false);assert.equal(a.GoatManageOnlyAfterAdopt(),false);assert.deepEqual(a.t.sleeps,[20000],'B49a: the refused licence waits 20 s');}
 {const a=ea({state:REFUSED});holding(a,true);assert.equal(a.GoatManageOnlyAfterAdopt(),true);assert.match(a.t.alerts[0],/refused this account\. GOAT manages/);}
 for(const h of [false,true]){const a=ea({state:DOWN});holding(a,h);assert.equal(a.GoatManageOnlyAfterAdopt(),true,'an outage stays and retries');assert.match(a.t.alerts[0],/can't be reached .* until the licence is verified\.$/);}
 // The outage retry: one attempt every GOAT_LICENCE_RETRY_MS; a valid licence ends manage-only.
 {const a=ea({state:DOWN,licence:[503,VALID]});holding(a,true);a.g_GoatLicenceRetriedMs=a.t.now;
  a.t.now+=RETRY_MS-1;a.GoatManageOnlyTimer();assert.equal(a.t.verifies,0);
  a.t.now+=1;a.GoatManageOnlyTimer();assert.deepEqual([a.t.verifies,a.g_GoatManageOnly],[1,DOWN]);
  a.t.now+=1000;a.GoatManageOnlyTimer();assert.equal(a.t.verifies,1,'the next retry waits the full interval');
  a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.t.verifies,a.g_GoatManageOnly,a.t.removed],[2,NONE,0]);}
 // Flat while the outage lasts: it keeps retrying, never removes itself.
 {const a=ea({state:DOWN,licence:[-1]});holding(a,false);a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.g_GoatManageOnly,a.t.removed],[DOWN,0]);}
 // The service answers with a refusal: licence_refused; once flat the EA stops, once.
 {const a=ea({state:DOWN,licence:[403]});holding(a,true);a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.g_GoatManageOnly,a.t.removed],[REFUSED,0]);
  holding(a,false);a.GoatManageOnlyTimer();a.GoatManageOnlyTimer();assert.equal(a.t.removed,1);assert.match(a.t.alerts.at(-1),/refused this account\. No positions are left to manage/);}
 for(const s of [EXPIRED,REFUSED]){const a=ea({state:s});holding(a,true);a.GoatManageOnlyTimer();assert.equal(a.t.removed,0,'holding');
  a.Seq_Sell.Active=true;a.Seq_Buy.Active=false;a.GoatManageOnlyTimer();assert.equal(a.t.removed,0,'either side holds');
  a.Seq_Sell.Active=false;a.GoatManageOnlyTimer();assert.equal(a.t.removed,1,'flat: removed');assert.equal(a.t.verifies,0,'no licence call');}
 {const a=ea();holding(a,false);a.GoatManageOnlyTimer();assert.deepEqual([a.t.removed,a.t.verifies],[0,0],'not manage-only: nothing');}
 ok();}

// ---------------------------------------------------------------- 6. where it sits
{const line=re=>{const m=main.split('\n').filter(l=>re.test(l));assert.equal(m.length,1,String(re));return m[0];};
 // The licence answer: a valid licence or manage-only takes the full init path; 401/403 and the rest are unchanged.
 assert.match(line(/LicenseKey==LICENSE_VALID/),/^    if\(LicenseKey==LICENSE_VALID \|\| GoatLicenceManageOnly\(LicenseKey\)\) \/\/ B49b \(F1\)/);
 assert.match(main,/else if\(LicenseKey==401 \|\| LicenseKey==403\)\n    \{\n     Print\("Stored GOAT user credential was rejected/);
 // The four expiry paths: OnInit, Add_Level (returns before any add), the signal block, the panel.
 const exp=main.split('\n').filter(l=>/TimeCurrent\(\)>Expiry/.test(l));assert.equal(exp.length,4);
 for(const l of exp) assert.match(l,/GoatExpiryManageOnly\(\)/,l.trim().slice(0,60));
 assert.match(bodyOf(main,'   bool Add_Level(double Level_New)').split('\n').find(l=>l.trim()),/^    if\(TimeCurrent\(\)>Expiry\) \{if\(GoatExpiryManageOnly\(\)\) return false; /);
 assert.match(line(/TimeCurrent\(\)>Expiry && !GoatExpiryManageOnly\(\)\) \{Alert\(.*return INIT_FAILED/),/^   if\(/);
 // OnInit: the restore right after adoption; the manage-only check after the magic block, before the export setup.
 const init=bodyOf(main,'int OnInit()');
 assert.match(init,/Seq_Buy\.AdoptOpenPositions\(\); Seq_Sell\.AdoptOpenPositions\(\);[^\n]*\n     GoatStateRestore\(\);/);
 assert.match(init,/    GlobalVariablesFlush\(\);\n   \}\n   if\(!GoatManageOnlyAfterAdopt\(\)\) return INIT_FAILED;[^\n]*\n\/\/-+\n \/\/if\(Mode_Operation==Operation_Export\)\n   if\(Mode=="EXPORT"\)/);
 assert.ok(init.indexOf('GoatLicenceManageOnly(LicenseKey)')<init.indexOf('GoatManageOnlyAfterAdopt()'),'the licence answer comes first');
 // OnTick: the day restore right after the new-day block's resets; the bias edges are globals, no statics.
 assert.match(main,/   if\(IsNewDay\(\)\)\n   \{\n    days\+\+;\n[\s\S]{0,200}?    LastStopoutTime=0;\n    StopOut_Flag = false;\n    DStartLocalLoss = 99999;\n[\s\S]{0,160}?    DStartEquity=AccountInfoDouble\(ACCOUNT_EQUITY\);\n    if\(GoatStateLive\(\)\) GoatStateDayRestore\(\);/);
 assert.doesNotMatch(main,/static bool Last_StopOut_Flag_[BS]/);
 assert.match(main,/    if\(StopOut_Flag_B && !g_GoatLastStopOutB\)[^\n]*\n    \{\n     HandleBiasExitBuy\(Buys\);\n    \}\n    g_GoatLastStopOutB = StopOut_Flag_B;/);
 assert.match(main,/    if\(StopOut_Flag_S && !g_GoatLastStopOutS\)[^\n]*\n    \{\n     HandleBiasExitSell\(Sells\);\n    \}\n    g_GoatLastStopOutS = StopOut_Flag_S;/);
 // OnTimer and OnDeinit, beside the restart record's flush.
 assert.match(bodyOf(main,'void OnTimer(void)'),/^\s*GoatTimerBody\(\);/,'OnTimer runs GoatTimerBody');
 assert.match(bodyOf(main,'void GoatTimerBody(void)'),/Seq_Buy\.PersistFlush\(\); Seq_Sell\.PersistFlush\(\);[^\n]*\n   GoatStateFlush\(\); GoatManageOnlyTimer\(\);/);
 assert.match(bodyOf(main,'void OnDeinit(const int reason)'),/Seq_Buy\.PersistFlush\(true\); Seq_Sell\.PersistFlush\(true\);[^\n]*\n   GoatStateFlush\(true\);/);
 // Adoption marks the direction guard's existing-sequence state (no claim: the core refuses a claim over live exposure).
 assert.match(bodyOf(main,'   bool AdoptOpenPositions()'),/    Adopted=true; AdoptMatched=matched; AdoptSizes=sizes;\n    GuardRealStarted=true;/);
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f1'}));
