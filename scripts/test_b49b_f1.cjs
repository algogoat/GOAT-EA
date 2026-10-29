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
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime|uchar)';
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
 .replace(/^\s*static\s+bool\s+removing=false;\s*$/m,'')                    // GoatManageOnlyTimer's static lives in the context
 .replace(/^\s*static\s+long\s+serial=0;\s*$/m,'')                          // so do the writers' .pending serials
 .replace(/\(long\)(\w+)\/86400/g,'Math.floor($1/86400)')                    // MQL long division
 .replace(/StringReplace\((\w+(?:\[\w+\])?),("(?:\\.|[^"])*"),("(?:\\.|[^"])*")\);/g,'$1=$1.split($2).join($3);') // by reference
 .replace(/GoatSetupRead\(([^,]+\)),(\w+)\)/g,'GoatSetupReadRef($1,v=>$2=v)')
 .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]\\s*=\\s*\\{([^}]*)\\};','g'),'let $1=[$2];')
 .replace(/\bstring\s+(\w+)\[\],(\w+)\[\];/g,'let $1=[],$2=[];')
 .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]','g'),'let $1=[]')
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
 .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const define=name=>{const m=main.match(new RegExp('^#define '+name+'\\s+(\\d+)\\s*(?://.*)?$','m'));assert.ok(m,'missing #define '+name);return Number(m[1]);};
const NONE=define('GOAT_MANAGE_NONE'),DOWN=define('GOAT_MANAGE_LICENCE_DOWN'),REFUSED=define('GOAT_MANAGE_LICENCE_REFUSED'),EXPIRED=define('GOAT_MANAGE_EXPIRED');
const CRED=define('GOAT_MANAGE_CREDENTIAL');
const RETRY_MS=define('GOAT_LICENCE_RETRY_MS'),VERSION=define('GOAT_STATE_VERSION'),FLUSH_MS=define('GOAT_SQ_FLUSH_MS');
assert.deepEqual([NONE,DOWN,REFUSED,EXPIRED,CRED,RETRY_MS,VERSION,FLUSH_MS],[0,1,2,3,4,300000,1,5000]);
// test_b49b_f1_mutations.cjs points GOAT_EA_DASH at a mutated Dashboard.mqh.
const dash=clean(fs.readFileSync(process.env.GOAT_EA_DASH||path.join(ROOT,'Dashboard.mqh'),'utf8'));
const VALID=Number((clean(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8')).match(/^#define LICENSE_VALID\s+(\d+)/m)||[])[1]);
assert.equal(VALID,1505);

const SIG={
 live:'bool GoatManageOnlyLive()',reason:'string GoatManageOnlyReason()',expiry:'bool GoatExpiryManageOnly()',
 licence:'bool GoatLicenceManageOnly(const int key)',value:'string GoatStateValue(const string &keys[],const string &values[],const string key)',
 entry:'bool DashboardEntryAllowed(const int op)',path:'string GoatStatePath()',stateLive:'bool GoatStateLive()',text:'string GoatStateText()',
 flush:'void GoatStateFlush(const bool force=false)',read:'bool GoatStateRead(string &keys[],string &values[])',restore:'void GoatStateRestore()',
 day:'void GoatStateDayRestore()',why:'string GoatManageOnlyWhy()',announce:'void GoatManageOnlyAnnounce()',
 after:'int GoatManageOnlyAfterAdopt()',timer:'void GoatManageOnlyTimer()',
 transient:'bool GoatLicenceTransient(const int key)',write:'bool GoatStateWrite(const string path,const string body)',prompt:'void GoatManageOnlyPrompt()',
 sendStatus:'void DashboardBusSendStatus(const string status)',
 seqText:'   string StateText()',seqRestore:'   void StateRestore(const string &keys[],const string &values[])',
 frozen:'   bool ManageOnlyFrozen(const int level)',persistLive:'   bool PersistLive()',init:'   void Init(int OP,bool v)',reset:'   void ResetSequenceRiskState()',
};
const FLAGS=fn('GoatManageOnlyLive',[],bodyOf(main,SIG.live))+fn('GoatManageOnlyReason',[],bodyOf(main,SIG.reason))
 +fn('GoatExpiryManageOnly',[],bodyOf(main,SIG.expiry))+fn('GoatLicenceManageOnly',['key'],bodyOf(main,SIG.licence))
 +fn('GoatLicenceTransient',['key'],bodyOf(main,SIG.transient))+fn('GoatStateValue',['keys','values','key'],bodyOf(main,SIG.value));
// The MQL file API (Common files), modelled on the terminal: FILE_TXT writes "\r\n" for each bare "\n" and leaves an
// existing "\r\n" as it is (the probe's cases 1 and 2b), and FileWriteString returns what it wrote (Claude-Mac #284 P1);
// FILE_BIN writes the bytes given. A file appears at FileOpen, as on MT5. FileMove refuses to replace an existing file
// without FILE_REWRITE, as MT5 does (Claude-Mac #284 APPROVE item 1). The error codes of the injected failures are the model's.
const FILE_TXT=16,FILE_REWRITE=512;
const fileApi=t=>({INVALID_HANDLE:-1,FILE_READ:1,FILE_WRITE:2,FILE_BIN:4,FILE_TXT,FILE_ANSI:32,FILE_SHARE_READ:64,FILE_REWRITE,WHOLE_ARRAY:-1,CP_UTF8:65001,
 ChartID:()=>131,GetTickCount64:()=>t.now,ResetLastError:()=>{t.err=0;},GetLastError:()=>t.err,StringLen:s=>s.length,
 FileIsExist:p=>t.files.has(p),
 FileOpen:(p,flags)=>{if(p.endsWith('.pending'))t.writes=(t.writes||0)+1;if(t.failOpen){t.err=5004;return -1;}t.handles.push({p,flags,data:''});t.files.set(p,'');return t.handles.length;},
 FileWriteArray:(h,bytes,start,count)=>{if(t.failWrite){t.err=5020;return 0;}t.handles[h-1].data+=Buffer.from(bytes.slice(start,start+count)).toString('utf8');
  if(t.errAfterWrite)t.err=5026;return count;},   // errAfterWrite: every byte reported written, but an error is set
 FileWriteString:(h,s)=>{const o=t.handles[h-1];const w=(o.flags&FILE_TXT)?s.replace(/\r?\n/g,'\r\n'):s;o.data+=w;return w.length;},
 FileFlush:()=>{},FileClose:h=>{const o=t.handles[h-1];t.files.set(o.p,o.data);},
 FileMove:(a,af,b,bf)=>{if(t.failMove){t.err=5021;return false;}if(t.files.has(b)&&!(bf&FILE_REWRITE)){t.err=5022;return false;}
  t.files.set(b,t.files.get(a));t.files.delete(a);return true;},
 FileDelete:p=>{t.files.delete(p);t.deleted.push(p);return true;},
 StringToCharArray:(s,arr)=>{arr.length=0;arr.push(...Buffer.from(s,'utf8'),0);return arr.length;}});
const pending=files=>[...files.keys()].filter(k=>k.endsWith('.pending'));
const K={OP_BUY:0,OP_SELL:1,OP_BUYSELL:2,MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,Operation_Standard:0,Operation_Report:5,Operation_Batch:6,Operation_Dash:7,
 GOAT_MANAGE_NONE:NONE,GOAT_MANAGE_LICENCE_DOWN:DOWN,GOAT_MANAGE_LICENCE_REFUSED:REFUSED,GOAT_MANAGE_EXPIRED:EXPIRED,GOAT_MANAGE_CREDENTIAL:CRED,
 GOAT_LICENCE_RETRY_MS:RETRY_MS,INIT_SUCCEEDED:0,INIT_FAILED:1,GOAT_BUILD_ID:'B49b-test',
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
 const WORD={[DOWN]:'licence_unavailable',[REFUSED]:'licence_refused',[CRED]:'credential_rejected'};
 // 408 and 429 are an outage too: GOATLicenseInitRetry.mqh retries them as transient (Claude-Mac #284 P2-2).
 for(const [key,want] of [[-1,DOWN],[-2,DOWN],[500,DOWN],[503,DOWN],[1001,DOWN],[1003,DOWN],[408,DOWN],[429,DOWN],[400,REFUSED],[402,REFUSED],[404,REFUSED],[200,REFUSED],[401,CRED],[403,CRED]]){
  const c=flags();c.t.now=7777;assert.equal(c.GoatLicenceManageOnly(key),true,'key '+key);
  assert.equal(c.g_GoatManageOnly,want,'key '+key);assert.equal(c.g_GoatLicenceRetriedMs,7777,'the retry clock starts at init');
  assert.match(c.t.logs.at(-1),new RegExp('^GOAT manage-only: reason='+WORD[want]+' licence_status='+key+' new_trades=refused'));
 }
 for(const key of [VALID,0]){const c=flags();assert.equal(c.GoatLicenceManageOnly(key),false,'key '+key);assert.equal(c.g_GoatManageOnly,NONE);}
 for(const o of [{tester:true},{mode:5},{mode:7}]){const c=flags(o);assert.equal(c.GoatLicenceManageOnly(503),false);assert.equal(c.g_GoatManageOnly,NONE,'B49a INIT_FAILED stays off the trading chart');}
 // An expired build stays expired when the licence is also down: a licence that comes back never lifts expiry.
 for(const key of [503,403]){const c=flags({state:EXPIRED});assert.equal(c.GoatLicenceManageOnly(key),true);assert.equal(c.g_GoatManageOnly,EXPIRED,'key '+key);}
 // GoatExpiryManageOnly: live, once; the tester keeps B49a's expiry.
 {const c=flags();assert.equal(c.GoatExpiryManageOnly(),true);assert.equal(c.GoatExpiryManageOnly(),true);assert.equal(c.g_GoatManageOnly,EXPIRED);
  assert.equal(c.t.logs.filter(l=>/reason=expired/.test(l)).length,1,'said once');}
 {const c=flags({state:DOWN});c.GoatExpiryManageOnly();assert.equal(c.g_GoatManageOnly,EXPIRED,'expiry outranks an outage');}
 {const c=flags({tester:true});assert.equal(c.GoatExpiryManageOnly(),false);assert.equal(c.g_GoatManageOnly,NONE);}
 assert.deepEqual([NONE,DOWN,REFUSED,EXPIRED,CRED].map(s=>flags({state:s}).GoatManageOnlyReason()),['none','licence_unavailable','licence_refused','expired','credential_rejected']);
 ok();}
{// DashboardEntryAllowed: every start path passes through it (Add_Level's virtual->real hand-off and the signal block).
 const run=(state,{cid=false,op=0}={})=>{const c={g_GoatManageOnly:state,GOAT_MANAGE_NONE:NONE,MAGIC1:1,g_GoatStudioMonitorRunPath:'',Symbol:()=>'EURUSD',
  GoatCidGuardRefuses:()=>cid,GoatStagedChildMayOpen:()=>true,DashboardTradeAllowed:()=>true,DashboardExposureConflict:()=>false};
  vm.createContext(c);vm.runInContext(fn('DashboardEntryAllowed',['op'],bodyOf(main,SIG.entry)),c);return c.DashboardEntryAllowed(op);};
 // Both sides (Claude-Mac #284 P3: a sell-side refusal was untested).
 for(const op of [0,1]){assert.equal(run(NONE,{op}),true);for(const s of [DOWN,REFUSED,EXPIRED,CRED]) assert.equal(run(s,{op}),false,'manage-only '+s+' opens nothing, side '+op);}
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
 const t={tester,logs:[],alerts:[],now:100000,files,writes:0,failWrite:false,failMove:false,failOpen:false,unreadable:false,licence:[...licence],verifies:0,removed:0,sleeps:[],
  prompts:[],hidden:0,statuses:[],activations:[],activationOk:true,handles:[],deleted:[],err:0,errAfterWrite:false,folders:[],positions:0,counted:[]};
 const c={...K,...common(t),...fileApi(t),t,Mode_Operation:mode,g_GoatStateWriteError:0,serial:0,g_GoatManageOnlyHeldLogged:false,
  FindNumberOfPositions:(op,magic)=>{t.counted.push([op,magic]);return t.positions;},Mode:'',g_GoatManageOnly:state,g_GoatLicenceRetriedMs:0,g_GoatStateFailed:false,
  g_GoatLastStopOutB:false,g_GoatLastStopOutS:false,g_GoatStateLast:'',g_GoatStateWrittenMs:0,g_GoatStateDay:0,g_GoatDayRestorePending:false,
  g_GoatDayKeys:[],g_GoatDayValues:[],removing:false,StopOut_Flag:false,DStartEquity:10000,DStartLocalLoss:99999,DStartTime:0,LastStopoutTime:0,
  tm_cur:1792054800+3600,AccountInfoInteger:k=>k==='login'?907113355:0,AccountInfoString:k=>k,
  FolderCreate:p=>{t.folders.push(p);return true;},
  GoatSetupReadRef:(p,set)=>{if(t.unreadable||!t.files.has(p))return false;set(t.files.get(p));return true;},
  Sleep:ms=>t.sleeps.push(ms),ExpertRemove:()=>{t.removed++;},
  VerifyLicense:()=>{t.verifies++;return t.licence.length?t.licence.shift():503;},
  g_GoatManageOnlyAnnounced:'',g_GoatManageOnlyStatusMs:0,ShowPrompt:(...a)=>t.prompts.push(a),HidePrompt:()=>{t.hidden++;},
  DashboardBusSendStatus:s=>t.statuses.push(s),GOATDeviceActivationBegin:(login,build,replace)=>{t.activations.push([login,build,replace]);return t.activationOk;}};
 vm.createContext(c);
 vm.runInContext(FLAGS+['path','stateLive','text','write','read','restore','day','why','prompt','announce','after','timer'].map(k=>{
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
 // Claude-Mac #284 P3: a real sequence's FIRST level (Level_Count 0, a direct start) is refused too. Add_Level's own
 // refusal prefix runs here, up to its sizing block ("reached" = it would go on to size and open).
 const body=bodyOf(main,'   bool Add_Level(double Level_New)'),cut=body.indexOf('    if(Level_Count<Max_Seq_Levels && Trades_Count<Max_Seq_Trades)');
 assert.ok(cut>0);
 const f=sequence(a,{adopted:false});Object.assign(f,{Level_Count:0,TimeCurrent:()=>1,GoatCidGuardAddFrozen:()=>false});
 vm.runInContext(fn('AddLevelPrefix',['Level_New'],body.slice(0,cut)+'    return "reached";\n'),f);
 assert.equal(f.AddLevelPrefix(1.1),'reached','not manage-only: the first level goes on');
 for(const [set,why] of [[()=>{a.g_GoatManageOnly=DOWN;},'licence_unavailable'],[()=>{a.g_GoatManageOnly=CRED;},'credential_rejected'],[()=>{a.g_GoatStateFailed=true;},'state_unwritten']]){
  a.g_GoatManageOnly=NONE;a.g_GoatStateFailed=false;f.AddLevelPrefix(1.1);set();
  assert.equal(f.AddLevelPrefix(1.1),false,'first level, '+why);assert.match(a.t.logs.at(-1),new RegExp('add_frozen='+why+' side=BUY .* level=1 '),why);}
 a.g_GoatManageOnly=NONE;a.g_GoatStateFailed=false;
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
 assert.deepEqual(a.t.folders,['GOAT','GOAT\\State','GOAT\\State\\907113355'],'each folder level, as the CID claim (Claude-Mac #284 P3)');
 assert.deepEqual(pending(files),[],'no .pending left');assert.equal(body,a.GoatStateText(),'the file is exactly the text: no "\\r" added');
 assert.ok(body.startsWith('version=1\nlogin=907113355\nmagic=1843920117\nsymbol=EURUSD\nday='+a.g_GoatStateDay+'\nstopout=1\ndstart_equity=10250.50\n'),body);
 assert.match(body,/\nB\.level_retrace=1\.08770000\n/);assert.doesNotMatch(body,/\nS\./,'no section for the idle sell');
 // A change waits for GOAT_SQ_FLUSH_MS unless forced; unchanged text is never rewritten, forced or not.
 a.Seq_Buy.Trailing=false;a.t.now+=1;a.GoatStateFlush();assert.equal(a.t.writes,1,'within the flush interval');
 a.t.now+=FLUSH_MS;a.GoatStateFlush();assert.equal(a.t.writes,2);
 // The second write replaces the file (FILE_REWRITE): without it MT5's FileMove refuses and every write after the first
 // fails (Claude-Mac #284 APPROVE item 1).
 assert.deepEqual([a.g_GoatStateFailed,files.get(PATH),pending(files)],[false,a.GoatStateText(),[]],'the existing file is replaced');
 a.t.now+=FLUSH_MS;a.GoatStateFlush();a.GoatStateFlush(true);assert.equal(a.t.writes,2,'unchanged');
 a.Seq_Buy.Retrace_Triggered=false;a.GoatStateFlush(true);assert.equal(a.t.writes,3,'forced');a.Seq_Buy.Retrace_Triggered=true;
 // A failed write freezes adds (said once) until a write succeeds.
 const lastGood=files.get(PATH);
 a.t.failWrite=true;a.Seq_Buy.Trailing=true;a.GoatStateFlush(true);a.GoatStateFlush(true);
 assert.equal(a.g_GoatStateFailed,true);assert.equal(a.t.alerts.filter(x=>/GOAT state file not written/.test(x)).length,1);
 assert.match(a.t.alerts.find(x=>/not written/.test(x)),/, error 5020\)/,'the write error, kept past the cleanup');
 assert.deepEqual(pending(files),[],'a failed write leaves no .pending (Claude-Mac #284 P1)');assert.equal(files.get(PATH),lastGood,'the last good file stays');
 a.t.failWrite=false;a.GoatStateFlush(true);assert.equal(a.g_GoatStateFailed,false);assert.match(a.t.logs.at(-1),/written again/);
 // A failed move (and a failed open, and a write that reports every byte but sets an error: item 3) leaves no .pending
 // either, and the last good file stands.
 const good=files.get(PATH);
 for(const [flag,err] of [['failMove',5021],['failOpen',5004],['errAfterWrite',5026]]){a.t[flag]=true;a.Seq_Buy.Trailing=!a.Seq_Buy.Trailing;a.GoatStateFlush(true);
  assert.deepEqual([a.g_GoatStateFailed,a.g_GoatStateWriteError,pending(files),files.get(PATH)],[true,err,[],good],flag);
  a.t[flag]=false;a.Seq_Buy.Trailing=!a.Seq_Buy.Trailing;a.GoatStateFlush(true);assert.equal(a.g_GoatStateFailed,false,flag+': recovered');}
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

{// Claude-Mac #284 P1: why the state file has its own writer. B49a's GoatSetupWrite (FILE_TXT|FILE_ANSI, written ==
 // StringLen) refuses any multi-line LF text, since TXT mode writes "\r\n" for each "\n", and leaves its .pending
 // behind; its single-line JSON callers are fine. GoatStateWrite (FILE_BIN, exact UTF-8 bytes) writes the text as is.
 // Both run here from source on the modelled file API; the real-terminal bytes are the probe's (goatai#2587 6479771092).
 const setupSrc=clean(fs.readFileSync(path.join(ROOT,'GOATSetupControl.mqh'),'utf8'));
 const t={now:5000,files:new Map(),handles:[],deleted:[],err:0};
 const c={...fileApi(t),IntegerToString:v=>String(v),FILE_COMMON:4096,serial:0,g_GoatStateWriteError:0};
 vm.createContext(c);
 vm.runInContext(fn('GoatSetupWrite',['path','body'],bodyOf(setupSrc,'bool GoatSetupWrite(const string path,const string body)'))
  +fn('GoatStateWrite',['path','body'],bodyOf(main,SIG.write)),c);
 const a=ea();a.GoatStateDayRestore();a.Seq_Sell=sequence(a,{dir:1});
 Object.assign(a.Seq_Sell,{ClosePendingReason:'Day/Weekend Close',ClosePendingTried:1792058400,BiasRescueActive:true,Trailing:true});
 const text=a.GoatStateText();
 assert.ok(text.split('\n').length>20 && /\nS\.close_reason=/.test(text),'both sides\' sections: '+text.split('\n').length+' lines');
 assert.ok(Buffer.byteLength(text)<2048,'well under GoatSetupRead\'s 4096-byte cap: '+Buffer.byteLength(text));
 assert.equal(c.GoatSetupWrite('X\\setup.txt',text),false,'B49a\'s writer refuses the multi-line text');
 assert.equal(pending(t.files).length,1,'and leaves its .pending (B49a behaviour, untouched)');
 // TXT mode leaves an existing "\r\n" alone (the probe's case 2b: CRLF text in, the same 326 bytes out, no "\r\r").
 const crlf=text.replace(/\n/g,'\r\n');
 assert.equal(c.GoatSetupWrite('X\\setup-crlf.txt',crlf),true);assert.equal(t.files.get('X\\setup-crlf.txt'),crlf,'CRLF text written as is');
 // The model's own FileMove: an existing target is replaced only with FILE_REWRITE (item 1).
 t.files.set('X\\m.a','new');t.files.set('X\\m.b','old');
 assert.deepEqual([c.FileMove('X\\m.a',4096,'X\\m.b',4096),t.err,t.files.get('X\\m.b')],[false,5022,'old'],'no FILE_REWRITE: refused');
 assert.deepEqual([c.FileMove('X\\m.a',4096,'X\\m.b',4096|FILE_REWRITE),t.files.get('X\\m.b'),t.files.has('X\\m.a')],[true,'new',false]);
 const json='{"schema":1,"id":"r","result":"ok"}';
 assert.equal(c.GoatSetupWrite('X\\receipt.json',json),true);assert.equal(t.files.get('X\\receipt.json'),json,'its single-line JSON is unchanged');
 t.files=new Map();
 assert.equal(c.GoatStateWrite('X\\state.txt',text),true);assert.equal(t.files.get('X\\state.txt'),text,'the state writer: exact bytes');
 assert.deepEqual(pending(t.files),[]);
 const accented='symbol=DAX40€\n';assert.equal(c.GoatStateWrite('X\\utf8.txt',accented),true);assert.equal(t.files.get('X\\utf8.txt'),accented,'UTF-8 bytes counted, not characters');
 // Another writer's .pending with this exact name is never truncated.
 t.files.set('X\\state.txt.131.5000.'+(c.serial+1)+'.pending','theirs');
 assert.deepEqual([c.GoatStateWrite('X\\state.txt','a=1\n'),c.g_GoatStateWriteError,t.files.get('X\\state.txt.131.5000.'+c.serial+'.pending')],[false,-1,'theirs']);
 assert.deepEqual([c.GoatStateWrite('X\\empty.txt',''),c.g_GoatStateWriteError],[false,-2],'nothing to write');
 // The mode is binary: the model's FileWriteArray cannot tell (the real terminal's bytes are the probe's), so it is pinned.
 assert.match(bodyOf(main,SIG.write),/int h=FileOpen\(temporary,FILE_WRITE\|FILE_BIN\|FILE_COMMON\);/);
 assert.doesNotMatch(bodyOf(main,SIG.write),/FILE_TXT|FILE_ANSI|FileWriteString/);
 // GoatStateFlush writes through GoatStateWrite only; GoatSetupWrite keeps only its B49a callers.
 assert.match(bodyOf(main,SIG.flush),/if\(GoatStateWrite\(GoatStatePath\(\),text\)\)/);assert.doesNotMatch(bodyOf(main,SIG.flush),/GoatSetupWrite/);
 assert.equal(main.split('GoatSetupWrite(').length-1,0,'the entrypoint never calls GoatSetupWrite');
 ok();}

// ---------------------------------------------------------------- 5. OnInit after adoption, and the timer
{const holding=(a,h)=>{a.Seq_Buy.Active=h;a.Seq_Sell.Active=false;};
 const GOON=-1;
 {const a=ea();assert.equal(a.GoatManageOnlyAfterAdopt(),GOON);assert.deepEqual([a.t.alerts,a.t.prompts,a.t.statuses],[[],[],[]]);}
 {const a=ea({state:EXPIRED});holding(a,false);assert.equal(a.GoatManageOnlyAfterAdopt(),1,'expired and flat: INIT_FAILED');assert.match(a.t.alerts[0],/^This version expired on D1798675200\. Go to /);}
 {const a=ea({state:EXPIRED});holding(a,true);assert.equal(a.GoatManageOnlyAfterAdopt(),GOON);assert.match(a.t.alerts[0],/expired .* GOAT manages its open positions .* it stops once they are closed\.$/);}
 {const a=ea({state:REFUSED});holding(a,false);assert.equal(a.GoatManageOnlyAfterAdopt(),1);assert.deepEqual(a.t.sleeps,[20000],'B49a: the refused licence waits 20 s');}
 {const a=ea({state:REFUSED});holding(a,true);assert.equal(a.GoatManageOnlyAfterAdopt(),GOON);assert.match(a.t.alerts[0],/refused this account\. GOAT manages/);}
 for(const h of [false,true]){const a=ea({state:DOWN});holding(a,h);assert.equal(a.GoatManageOnlyAfterAdopt(),GOON,'an outage stays and retries');assert.match(a.t.alerts[0],/can't be reached .* until the licence is verified\.$/);}
 // A rejected credential (401/403): with an open basket, manage-only (Claude-Mac 6475450194); with none, B49a's secure
 // replacement, unchanged (INIT_SUCCEEDED in activation-only mode, INIT_FAILED when it cannot begin).
 {const a=ea({state:CRED});holding(a,true);assert.equal(a.GoatManageOnlyAfterAdopt(),GOON);assert.equal(a.g_GoatManageOnly,CRED);
  assert.match(a.t.alerts[0],/^The GOAT sign-in for this MT5 account was rejected .* it stops once they are closed\.$/);assert.deepEqual(a.t.activations,[]);}
 for(const okBegin of [true,false]){const a=ea({state:CRED});a.t.activationOk=okBegin;holding(a,false);
  assert.equal(a.GoatManageOnlyAfterAdopt(),okBegin?0:1);assert.deepEqual(a.t.activations,[[907113355,'B49b-test',true]]);
  assert.equal(a.g_GoatManageOnly,NONE);assert.match(a.t.logs.at(-1),/^Stored GOAT user credential was rejected\. Starting secure replacement/);assert.deepEqual(a.t.alerts,[]);}
 // The announcement: once per reason (an Alert and the chart prompt), the dashboard row "Managing only" every minute.
 {const a=ea({state:EXPIRED});holding(a,true);a.GoatManageOnlyAfterAdopt();
  assert.deepEqual([a.t.alerts.length,a.t.prompts.length,a.t.statuses],[1,1,['Managing only']]);assert.equal(a.t.prompts[0][0],'GOAT is managing only');
  a.t.now+=59999;a.GoatManageOnlyTimer();assert.deepEqual([a.t.alerts.length,a.t.statuses.length],[1,1],'not within the minute');
  a.t.now+=1;a.GoatManageOnlyTimer();assert.deepEqual([a.t.alerts.length,a.t.statuses],[1,['Managing only','Managing only']],'resent, never re-alerted');}
 {const a=ea({state:DOWN,licence:[VALID]});holding(a,true);a.GoatManageOnlyAfterAdopt();a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();
  assert.deepEqual([a.g_GoatManageOnly,a.t.hidden,a.t.statuses.at(-1)],[NONE,1,'Linked'],'the end: the prompt goes, the row is Linked again');
  const sent=a.t.statuses.length;a.t.now+=60000;a.GoatManageOnlyTimer();assert.deepEqual([a.t.hidden,a.t.statuses.length],[1,sent],'said once');}
 // The outage retry: one attempt every GOAT_LICENCE_RETRY_MS; a valid licence ends manage-only.
 {const a=ea({state:DOWN,licence:[503,VALID]});holding(a,true);a.g_GoatLicenceRetriedMs=a.t.now;
  a.t.now+=RETRY_MS-1;a.GoatManageOnlyTimer();assert.equal(a.t.verifies,0);
  a.t.now+=1;a.GoatManageOnlyTimer();assert.deepEqual([a.t.verifies,a.g_GoatManageOnly],[1,DOWN]);
  a.t.now+=1000;a.GoatManageOnlyTimer();assert.equal(a.t.verifies,1,'the next retry waits the full interval');
  a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.t.verifies,a.g_GoatManageOnly,a.t.removed],[2,NONE,0]);}
 // Flat while the outage lasts: it keeps retrying, never removes itself.
 {const a=ea({state:DOWN,licence:[-1]});holding(a,false);a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.g_GoatManageOnly,a.t.removed],[DOWN,0]);}
 // The service answers with a refusal: credential_rejected (401/403) or licence_refused, said; once flat the EA stops, once.
 for(const [key,want,re] of [[403,CRED,/sign-in for this MT5 account was rejected/],[402,REFUSED,/refused this account/]]){
  const a=ea({state:DOWN,licence:[key]});holding(a,true);a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();assert.deepEqual([a.g_GoatManageOnly,a.t.removed],[want,0]);
  assert.match(a.t.alerts.at(-1),re,'the new reason is announced');
  holding(a,false);a.GoatManageOnlyTimer();a.GoatManageOnlyTimer();assert.equal(a.t.removed,1);
  assert.match(a.t.alerts.at(-1),new RegExp(re.source+'.*\\. No positions are left to manage, so GOAT stops on this chart\\.$'));}
 for(const s of [EXPIRED,REFUSED,CRED]){const a=ea({state:s});holding(a,true);a.GoatManageOnlyTimer();assert.equal(a.t.removed,0,'holding');
  a.Seq_Sell.Active=true;a.Seq_Buy.Active=false;a.GoatManageOnlyTimer();assert.equal(a.t.removed,0,'either side holds');
  a.Seq_Sell.Active=false;a.GoatManageOnlyTimer();assert.equal(a.t.removed,1,'flat: removed');assert.equal(a.t.verifies,0,'no licence call');}
 // Claude-Mac #284 P2-1: no sequence active but positions of this magic still open on the symbol (a failed close whose
 // sequence ended anyway): never removed, said once; removed once those positions are gone.
 // One leftover position holds too (Claude-Mac #284 APPROVE item 2).
 for(const s of [EXPIRED,REFUSED,CRED]) for(const n of [1,2]){const a=ea({state:s});holding(a,false);a.t.positions=n;
  a.GoatManageOnlyTimer();a.GoatManageOnlyTimer();assert.equal(a.t.removed,0,n+' position(s) open: not removed');
  assert.deepEqual(a.t.counted.at(-1),[2,1843920117],'both directions, this magic (FindNumberOfPositions on _Symbol)');
  assert.equal(a.t.logs.filter(l=>new RegExp('^GOAT manage-only: not removed: '+n+' position\\(s\\) of magic 1843920117 are still open on EURUSD').test(l)).length,1,'said once');
  a.t.positions=0;a.GoatManageOnlyTimer();assert.equal(a.t.removed,1,'flat: removed');}
 // Claude-Mac #284 P2-2: a 408 or 429 from the recovering service is still an outage, never a refusal; and the retry
 // puts the manage-only prompt back over VerifyLicense's "re-attach" prompt (P3).
 for(const key of [408,429,503,-1]){const a=ea({state:DOWN,licence:[key]});holding(a,false);a.GoatManageOnlyAfterAdopt();
  a.VerifyLicense=()=>{a.t.verifies++;a.t.prompts.push(['Can\'t reach goatedge.ai']);return key;};
  a.t.now+=RETRY_MS;a.GoatManageOnlyTimer();
  assert.deepEqual([a.g_GoatManageOnly,a.t.removed,a.t.verifies],[DOWN,0,1],'key '+key);
  assert.equal(a.t.prompts.at(-1)[0],'GOAT is managing only','key '+key+': the manage-only prompt is shown again');}
 {const a=ea();holding(a,false);a.GoatManageOnlyTimer();assert.deepEqual([a.t.removed,a.t.verifies],[0,0],'not manage-only: nothing');}
 ok();}

{// Claude-Mac #284 P3: a manage-only row stays "Managing only" through every ack and heartbeat. DashboardBusSendStatus
 // sends it in place of any other status (the heartbeat's "Active"/"Paused", an ack's "Paused"/"Active", a guard
 // status) while manage-only; Offline (deinit) and Close Failed still show; otherwise B49a's exactly.
 const send=(state,status)=>{const sent=[];const c={...K,g_GoatManageOnly:state,Mode_Operation:0,Operation_Batch:6,Operation_Dash:7,
  MQLInfoInteger:()=>0,GlobalVariableCheck:()=>true,GlobalVariableGet:()=>555,ChartID:()=>131,Symbol:()=>'EURUSD',GOAT_EVENT_CHILD_STATUS:9,
  EventChartCustom:(cid,ev,magic,chart,text)=>{sent.push([cid,ev,magic,chart,text]);return true;}};
  vm.createContext(c);vm.runInContext(fn('DashboardBusSendStatus',['status'],bodyOf(main,SIG.sendStatus)),c);c.DashboardBusSendStatus(status);return sent;};
 for(const status of ['Active','Paused','Inactive','Asset Buy: blocked','Deploying','Linked']){
  assert.deepEqual(send(NONE,status),[[555,9,1843920117,131,'EURUSD|'+status]],'not manage-only: '+status);
  for(const s of [DOWN,REFUSED,EXPIRED,CRED]) assert.deepEqual(send(s,status),[[555,9,1843920117,131,'EURUSD|Managing only']],status+' while manage-only '+s);}
 for(const status of ['Offline','Close Failed']) assert.deepEqual(send(DOWN,status),[[555,9,1843920117,131,'EURUSD|'+status]],status+' still shows');
 ok();}
{// Claude-Mac #284 APPROVE item 5: the dashboard's own writes. A command's start sets the row to Syncing and its ack to
 // Active, Paused or a policy label, before the child's next heartbeat; the row still shows "Managing only" (so it is never
 // counted active) because only the child sets or clears its manage_only flag. A command's outcome still shows until the
 // next heartbeat. Dashboard.mqh's child-status handler and DisplayStatusForRow run here from source.
 const handler=bodyOf(dash,'   if(id==GOAT_EVENT_CHILD_STATUS)');
 const shown=[];const c={GOAT_EVENT_CHILD_STATUS:9,GOAT_DASH_TRADE_ALLOW_BUY:1,GOAT_DASH_TRADE_ALLOW_SELL:2,GOAT_EXPOSURE_ALLOW:0,GOAT_EXPOSURE_SYMBOL_DIRECTION:3,
  m_portfolio_command_pending:false,now:5000,TimeCurrent:()=>5000,ArraySize:a=>a.length,StringSplit:(s,sep,arr)=>{arr.length=0;arr.push(...s.split(sep));return arr.length;},
  MarkStateDirty:()=>{},StatusColor:()=>0,ExposurePolicyLabelForMode:m=>'Exposure '+m,CurrencyPolicyLabelForMask:m=>'Mask '+m,
  edt_Status:[0,1,2].map(()=>({Text(v){if(v===undefined)return this.v;this.v=v;shown.push(v);},Color(){}})),
  g_sets:[{magic:1843920117,cid:131,sym:'EURUSD',status:'Linked',manage_only:false,heartbeat_ts:4990,policy_paused:false,trade_allow_mask:3,exposure_policy_mode:0}]};
 vm.createContext(c);
 vm.runInContext(fn('DisplayStatusForRow',['idx','now'],bodyOf(dash,'string DisplayStatusForRow(const int idx,const datetime now) const'))
  +fn('ChildStatus',['id','lparam','dparam','sparam'],'if(id==GOAT_EVENT_CHILD_STATUS)'+'{'+handler+'}'),c);
 const row=c.g_sets[0],child=s=>c.ChildStatus(9,1843920117,131,'EURUSD|'+s),show=()=>c.DisplayStatusForRow(0,5000);
 child('Managing only');assert.deepEqual([row.manage_only,show(),shown.at(-1)],[true,'Managing only','Managing only']);
 // The dashboard's own writes: a command's start, then its ack's Active, Paused or a policy label.
 for(const [label,set] of [['Syncing',()=>{row.status='Syncing';}],['Active',()=>{row.status='Active';}],['Paused',()=>{row.status='Paused';row.policy_paused=true;}],
  ['an exposure label',()=>{row.status='Exposure 1';row.exposure_policy_mode=1;}],['a currency label',()=>{row.status='Mask 1';row.trade_allow_mask=1;}]]){
  set();assert.equal(show(),'Managing only',label);Object.assign(row,{policy_paused:false,exposure_policy_mode:0,trade_allow_mask:3});}
 // A command's outcome shows until the next heartbeat; a stale heartbeat still says so first.
 for(const s of ['No Ack','Command Failed','Close Failed','Closed']){row.status=s;assert.equal(show(),s,s);}
 row.status='Active';row.heartbeat_ts=4900;assert.equal(show(),'Update delayed');row.heartbeat_ts=4990;
 // The child: a failed close leaves manage-only; the next "Managing only" shows it again; anything else ends it.
 child('Close Failed');assert.deepEqual([row.manage_only,show()],[true,'Close Failed']);
 child('Managing only');assert.equal(show(),'Managing only');
 for(const s of ['Active','Offline','Linked']){child('Managing only');child(s);assert.deepEqual([row.manage_only,show()],[false,s],s);}
 // A new row starts clear, and an adopted chart's row is cleared (it says for itself).
 assert.match(dash,/\n        policy_paused=false;\n        manage_only=false;   \/\/ B49b \(F1\)\n/);
 assert.match(dash,/\n   g_sets\[adopt_idx\]\.status="Linked";\n   g_sets\[adopt_idx\]\.manage_only=false;/);
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
 assert.match(init,/    GlobalVariablesFlush\(\);\n   \}\n   int manage_only_init=GoatManageOnlyAfterAdopt\(\);[^\n]*\n   if\(manage_only_init==INIT_FAILED\) return INIT_FAILED;[^\n]*\n   if\(manage_only_init==INIT_SUCCEEDED\) return INIT_SUCCEEDED;[^\n]*\n\/\/-+\n \/\/if\(Mode_Operation==Operation_Export\)\n   if\(Mode=="EXPORT"\)/);
 assert.ok(init.indexOf('GoatLicenceManageOnly(LicenseKey)')<init.indexOf('GoatManageOnlyAfterAdopt()'),'the licence answer comes first');
 // Re-derived at every init (Claude-Mac 6475450194): the first thing OnInit does after the no-tick reset, before the expiry check.
 assert.match(init,/^\s*GoatNoTickForget\(\);[^\n]*\n   g_GoatManageOnly=GOAT_MANAGE_NONE; g_GoatLicenceRetriedMs=0;/);
 assert.ok(init.indexOf('g_GoatManageOnly=GOAT_MANAGE_NONE;')<init.indexOf('TimeCurrent()>Expiry'),'reset before the expiry check');
 // The dashboard: a "Managing only" row is never counted active (section 7 runs the row's display).
 assert.match(dash,/\n      if\(row_status=="Active" \|\| row_status=="Linked"\) active_count\+\+;\n/,'only Active/Linked rows count as active');
 assert.match(dash,/if\(status=="Managing only"\)\s+return clrOrangeRed;/);
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
