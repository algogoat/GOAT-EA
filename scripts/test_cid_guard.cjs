// B46 (goatai#2350 6186284858, Claude-Mac's review of B45): a missing or duplicate CID record fails closed.
// Before B46 a chart with no CID record derived a fresh magic (GoatDeriveChildMagic skips the magics of open positions)
// and could start a new sequence on top of positions it no longer manages, and two CID records for one chart and symbol
// were settled by GoatFindMagicByCid's first match. GOAT V1.49.mq5 now refuses NEW sequences (DashboardEntryAllowed)
// while GoatCidGuardEvaluate finds orphan_suspected or cid_duplicate, and only new sequences.
// This runs the production functions (GoatCidGuard*, DashboardEntryAllowed, DashboardTradeAllowed, GoatChildMagicSalt,
// and the real GoatParseChildGVName, GoatTruncateCidValue and GoatChildGVName from the input header) after a
// syntax-only MQL-to-JS conversion, against a modelled terminal: GlobalVariables, the account's positions and orders,
// and Common\Files shared by the terminals of one PC. It also runs GoatTickBody's add-to-a-running-sequence branch
// while the guard refuses. Source semantics only: native MT5 GlobalVariables, files and trading are not exercised.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const main=read('GOAT V1.49.mq5'),header=read('GOAT_Inputs_Definitions.mqh');
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 let i=text.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<text.length;j++){if(text[j]==='{')depth++;if(text[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
function region(text,start,end){
 const a=text.indexOf(start);assert.ok(a>=0,'missing '+start);assert.equal(text.indexOf(start,a+1),-1,'one '+start);
 const b=text.indexOf(end,a+start.length);assert.ok(b>a,'missing '+end);
 return text.slice(a,b);
}
const once=(text,from,to,label)=>{assert.equal(text.split(from).length,2,'exactly one '+label);return text.replace(from,()=>to);};
const TYPES='(?:const )?(?:string|int|uint|long|ulong|bool|ushort|double|datetime)';
function js(text){
 return text.replace(/\/\/.*$/gm,'')
  .replace(/'([^'\\])'/g,(_,c)=>String(c.charCodeAt(0)))   // MQL char literals ('_') are ushort codes
  .replace(new RegExp('\\b'+TYPES+' ','g'),'let ')
  .replace(/\((?:long|int|uint|ulong|double)\)/g,'')
  .replace(/\b(cidg_\w+)\[\]/g,'$1=[]')
  // By-reference outputs become setter callbacks.
  .replace(/GoatParseChildGVName\((\w+),(\w+),(\w+),(\w+)\)/g,'GoatParseChildGVName($1,v=>$2=v,v=>$3=v,v=>$4=v)');
}
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';

// ---- the production functions, converted ----
const PARSE=bodyOf(header,'bool GoatParseChildGVName(const string gv_name,long &magic,string &symbol,string &field)');
const TRUNC=bodyOf(header,'long GoatTruncateCidValue(const long cid)');
const GVNAME=bodyOf(header,'string GoatChildGVName(const long magic,const string symbol,const string field)');
const SALT=bodyOf(main,'string GoatChildMagicSalt(void)');
const G={
 has:bodyOf(main,'bool GoatCidGuardHas(const long &cidg_list[],const long cidg_value)'),
 add:bodyOf(main,'void GoatCidGuardAdd(long &cidg_list[],const long cidg_value)'),
 join:bodyOf(main,'string GoatCidGuardJoin(const long &cidg_list[])'),
 comment:bodyOf(main,'bool GoatCidGuardGoatComment(const string cidg_comment)'),
 claimPath:bodyOf(main,'string GoatCidGuardClaimPath(const long cidg_magic,const string cidg_symbol)'),
 claimRead:bodyOf(main,'int GoatCidGuardClaimRead(const long cidg_magic,const string cidg_symbol,string &cidg_owner)'),
 claimState:bodyOf(main,'string GoatCidGuardClaimState(const int cidg_state)'),
 claim:bodyOf(main,'void GoatCidGuardClaim(const string cidg_terminal,const bool cidg_force)'),
 liveCharts:bodyOf(main,'void GoatCidGuardLiveCharts(long &cidg_live[])'),
 orphan:bodyOf(main,'bool GoatCidGuardOrphan('),
 evaluate:bodyOf(main,'string GoatCidGuardEvaluate(string &cidg_detail)'),
 refuses:bodyOf(main,'bool GoatCidGuardRefuses(const bool cidg_force=false)'),
 status:bodyOf(main,'string GoatCidGuardStatus(void)'),
 heartbeat:bodyOf(main,'void GoatCidGuardHeartbeat(void)'),
 touch:bodyOf(main,'void GoatCidDailyTouch(void)'),   // B49a (B48)
 addFrozen:bodyOf(main,'bool GoatCidGuardAddFrozen(const int cidg_dir,const int cidg_level)'),
};
const ENTRY=bodyOf(main,'bool DashboardEntryAllowed(const int op)');
const TRADE=bodyOf(main,'bool DashboardTradeAllowed(const int op)');
// Every GOAT_CID_* define (B46 cadence, B47 thresholds and claim states), named as in the source.
const DEFS=Object.fromEntries([...main.matchAll(/^#define (GOAT_CID_\w+)\s+(\d+)/gm)].map(m=>[m[1],Number(m[2])]));
const RECHECK=DEFS.GOAT_CID_GUARD_RECHECK_MS;assert.equal(RECHECK,5000);
assert.deepEqual([DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS,DEFS.GOAT_CID_CLAIM_STALE_SEC,DEFS.GOAT_CID_CLAIM_FUTURE_SEC,DEFS.GOAT_CID_ADD_RECHECK_MS],[5000,180,30,1000]);
// By-reference outputs: the converted body writes an enclosing variable, handed back through a setter.
const byRef=(name,args,body,out,init)=>'function '+name+'('+args.join(',')+',__o){let '+out+'='+init+';const __r=(()=>{'+js(body)+'})();__o('+out+');return __r;}\n';
const refArgs=t=>t.replace(/GoatCidGuardClaimRead\(([^,()]+),([^,()]+\(\)),(\w+)\)/g,'GoatCidGuardClaimRead($1,$2,v=>$3=v)')
 .replace(/GoatCidGuardOrphan\(([^;]*?),cidg_terminal,cidg_claim\)/g,'GoatCidGuardOrphan($1,cidg_terminal,v=>cidg_claim=v)');
const code=
 'function GoatParseChildGVName(gv_name,__m,__s,__f){let magic=0,symbol="",field="";'
  +js(once(PARSE,'return(symbol!="" && field!="");','__m(magic);__s(symbol);__f(field);return(symbol!="" && field!="");','parse return'))+'}\n'
 +fn('GoatTruncateCidValue',['cid'],TRUNC)+fn('GoatChildGVName',['magic','symbol','field'],GVNAME)+fn('GoatChildMagicSalt',[],SALT)
 +fn('GoatCidGuardHas',['cidg_list','cidg_value'],G.has)+fn('GoatCidGuardAdd',['cidg_list','cidg_value'],G.add)
 +fn('GoatCidGuardJoin',['cidg_list'],G.join)+fn('GoatCidGuardGoatComment',['cidg_comment'],G.comment)
 +fn('GoatCidGuardClaimPath',['cidg_magic','cidg_symbol'],G.claimPath)
 +byRef('GoatCidGuardClaimRead',['cidg_magic','cidg_symbol'],G.claimRead,'cidg_owner','""')
 +fn('GoatCidGuardClaimState',['cidg_state'],G.claimState)
 +fn('GoatCidGuardClaim',['cidg_terminal','cidg_force'],refArgs(G.claim))
 +fn('GoatCidGuardLiveCharts',['cidg_live'],G.liveCharts)
 +byRef('GoatCidGuardOrphan',['cidg_magic','cidg_comment','cidg_mapped','cidg_known','cidg_terminal'],refArgs(G.orphan),'cidg_claim','0')
 // The detail is a by-reference output: the converted body writes the enclosing cidg_detail.
 +'function GoatCidGuardEvaluate(__box){let cidg_detail="";const __r=(()=>{'+js(refArgs(G.evaluate))+'})();__box.v=cidg_detail;return __r;}\n'
 +'function GoatCidGuardRefuses(cidg_force=false){'
  +once(js(G.refuses),'let cidg_reason=GoatCidGuardEvaluate(cidg_detail);','const __b={v:""};let cidg_reason=GoatCidGuardEvaluate(__b);cidg_detail=__b.v;','evaluate call')+'}\n'
 +fn('GoatCidGuardStatus',[],G.status)+fn('GoatCidGuardHeartbeat',[],G.heartbeat)+fn('GoatCidGuardAddFrozen',['cidg_dir','cidg_level'],G.addFrozen)
 // B49a (B48): the bool GlobalVariableGet(name,&value) overload becomes a setter callback.
 +fn('GoatCidDailyTouch',[],G.touch.replace(/GlobalVariableGet\((\w+),(\w+)\)/g,'GlobalVariableGetRef($1,v=>$2=v)'))
 +fn('DashboardEntryAllowed',['op'],ENTRY)+fn('DashboardTradeAllowed',['op'],TRADE);

const KEY=(header.match(/^#define\s+Key\s+"(\w+)"/m)||[])[1];assert.equal(KEY,'GOAT');
const CID=(header.match(/^#define GOAT_GV_FIELD_CID\s+"(\w+)"/m)||[])[1];assert.equal(CID,'CID');
const DATA_A='C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\D0E8209F77C8CF37AD8BF550E51FF075';
const DATA_B='C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\5B9A1E3C0D44F2A7B61C93E8A02D7F11';
const CHART=128604373052183041n,OTHER_CHART=128604373052183077n,LOGIN=3000107825;
const GMT0=1792050000;   // a TimeGMT() on 2026-10-15
// One account (positions and orders), one PC (Common\Files, one clock); each terminal has its own GlobalVariables
// and charts. A chart is {id, expert}: the open chart walk (ChartFirst/ChartNext) and CHART_EXPERT_NAME.
function account(){return {positions:[],orders:[],common:new Map(),clock:{gmt:GMT0},locked:new Set()};}
function terminal({acct=account(),gv=new Map(),login=LOGIN,dataPath=DATA_A,chart=CHART,symbol='EURUSD',magic=0,tester=false,mode=0,strat='Trend',
  charts=[{id:CHART,expert:'GOAT V1.49'},{id:OTHER_CHART,expert:'GOAT V1.49'}]}={}){
 const logs=[],phases=[],reads={gv:0,files:0,writes:0},handles=new Map();let next=0;
 const c={...DEFS,Key:KEY,GOAT_GV_FIELD_CID:CID,
  MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,MQLInfoInteger:k=>(k===1&&tester)?1:0,
  Mode_Operation:mode,Operation_Batch:6,Operation_Dash:7,Strat:strat,MAGIC1:magic,
  ACCOUNT_LOGIN:7,TERMINAL_DATA_PATH:8,AccountInfoInteger:k=>{assert.equal(k,7);return c.login;},login,
  TerminalInfoString:k=>{assert.equal(k,8);return dataPath;},
  StringFind:(s,t,from=0)=>s.indexOf(t,from),StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringGetCharacter:(s,i)=>s.charCodeAt(i),IntegerToString:v=>String(v),StringFormat:(f,v)=>{assert.equal(f,'%I64d');return String(v);},
  StringToInteger:s=>{const m=String(s).match(/^\s*-?\d+/);if(!m)return 0;const b=BigInt(m[0]);return b>=-(2n**53n)&&b<=2n**53n?Number(b):b;},
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},
  GlobalVariablesTotal:()=>{reads.gv++;return gv.size;},GlobalVariableName:i=>[...gv.keys()][i],GlobalVariableGet:k=>gv.get(k)??0,
  // B49a (B48): wipeAfterCheck deletes the named record right after GlobalVariableCheck answers (a dashboard reset
  // between the check and the read); GlobalVariableGetRef is the bool GlobalVariableGet(name,&value) overload.
  GlobalVariableCheck:k=>{const has=gv.has(k);if(c.wipeAfterCheck===k){gv.delete(k);c.wipeAfterCheck=null;}return has;},wipeAfterCheck:null,
  GlobalVariableGetRef:(k,set)=>{if(!gv.has(k))return false;set(gv.get(k));return true;},
  GlobalVariablesFlush:()=>{reads.gvFlush=(reads.gvFlush||0)+1;},
  // B49a (B48): every write is counted; gvSetFails makes the terminal refuse writes (GlobalVariableSet returns 0).
  GlobalVariableSet:(k,v)=>{reads.gvSet=(reads.gvSet||0)+1;if(c.gvSetFails)return 0;gv.set(k,Number(v));return 1;},gvSetFails:false,
  GetLastError:()=>4501,TIME_DATE:1,
  TimeToString:(t,f)=>{assert.equal(f,1);return new Date(Number(t)*1000).toISOString().slice(0,10).replace(/-/g,'.');},
  g_GoatCidTouchedDay:0,g_GoatCidTouchFailedMs:0,g_GoatCidTouchFailed:false,
  Symbol:()=>symbol,ChartID:()=>chart,charts,CHART_EXPERT_NAME:31,
  ChartFirst:()=>c.charts.length?c.charts[0].id:-1n,
  ChartNext:id=>{const i=c.charts.findIndex(x=>x.id===id);return i>=0&&i+1<c.charts.length?c.charts[i+1].id:-1n;},
  ChartGetString:(id,k)=>{assert.equal(k,31);const x=c.charts.find(x=>x.id===id);return x?x.expert:'';},
  TimeGMT:()=>acct.clock.gmt,
  POSITION_SYMBOL:11,POSITION_COMMENT:12,POSITION_MAGIC:13,ORDER_SYMBOL:21,ORDER_COMMENT:22,ORDER_MAGIC:23,
  PositionsTotal:()=>acct.positions.length,PositionGetTicket:i=>{c.selP=acct.positions[i];return c.selP.ticket;},
  PositionGetString:k=>{assert.ok(k===11||k===12);return k===11?c.selP.symbol:c.selP.comment;},
  PositionGetInteger:k=>{assert.equal(k,13);return c.selP.magic;},
  OrdersTotal:()=>acct.orders.length,OrderGetTicket:i=>{c.selO=acct.orders[i];return c.selO.ticket;},
  OrderGetString:k=>{assert.ok(k===21||k===22);return k===21?c.selO.symbol:c.selO.comment;},
  OrderGetInteger:k=>{assert.equal(k,23);return c.selO.magic;},
  FILE_READ:1,FILE_WRITE:2,FILE_TXT:16,FILE_ANSI:32,FILE_SHARE_READ:64,FILE_SHARE_WRITE:128,FILE_COMMON:4096,INVALID_HANDLE:-1,
  FileIsExist:(p,f)=>{assert.equal(f,4096,'Common files only');return acct.common.has(p);},
  // A text file: FileReadString reads its next line; FileWrite appends a line ending with CRLF.
  FileOpen:(p,flags)=>{assert.ok(flags&4096,'Common files only');if(acct.locked.has(p))return -1;
   if(flags&2){acct.common.set(p,'');reads.writes++;}else{if(!acct.common.has(p))return -1;reads.files++;}
   handles.set(++next,{p,lines:(flags&2)?[]:acct.common.get(p).split('\r\n'),at:0});return next;},
  FileReadString:h=>{const x=handles.get(h);return x.at<x.lines.length?x.lines[x.at++]:'';},
  FileIsEnding:h=>{const x=handles.get(h);return x.at>=x.lines.length||(x.at===x.lines.length-1&&x.lines[x.at]==='');},
  FileWrite:(h,s)=>{const x=handles.get(h);acct.common.set(x.p,acct.common.get(x.p)+s+'\r\n');return s.length+2;},
  FileClose:h=>{handles.delete(h);},FolderCreate:(p,f)=>{assert.equal(f,4096);return true;},
  Print:s=>logs.push(s),GoatDeploymentPhase:(phase,target,control)=>phases.push({phase,target,control}),
  now:500000,GetTickCount:()=>c.now,
  // DashboardEntryAllowed's other gates, open: only the guard decides here.
  g_GoatStudioMonitorRunPath:'',GoatStagedChildMayOpen:()=>true,DashboardExposureConflict:()=>false,
  DashboardTradeAllowBuy:true,DashboardTradeAllowSell:true,OP_BUY:0,OP_SELL:1,
  g_GoatCidGuardReason:'',g_GoatCidGuardDetail:'',g_GoatCidGuardCheckedMs:0,g_GoatCidGuardChecked:false,
  g_GoatCidGuardClaimedMs:0,g_GoatCidGuardClaimed:false,g_GoatCidGuardFreezeLogged:[false,false]};
 vm.createContext(c);vm.runInContext(code,c);
 const record=(m,sym,cid)=>gv.set(KEY+'_ID_'+m+'_'+sym+'_'+CID,Number(c.GoatTruncateCidValue(cid)));
 // OnInit's own CID record write (GOAT V1.49.mq5, the MAGIC1==0 block).
 if(magic>0&&!tester)record(magic,symbol,chart);
 const refusal=()=>logs.filter(l=>l.startsWith('GOAT CID guard v1: refusal='));
 return {c,gv,acct,logs,phases,reads,record,refusal,entry:(op=0)=>c.DashboardEntryAllowed(op)};
}
const pos=(ticket,magic,comment='Trend Buy Lvl 01',symbol='EURUSD')=>({ticket,magic,comment,symbol});
const M=1843920117,O=907113355,Y=1210448821;   // this chart's magic, an orphaned magic, a sibling chart's magic

// 1. Orphan present -> refused. A GOAT magic on Symbol() that no CID record here maps and no other terminal claimed:
// new sequences are refused, orphan_suspected is logged once with the magic and the tickets, and it holds until resolved.
{const t=terminal({magic:M});t.acct.positions=[pos(501,O),pos(502,O,'Trend Buy Lvl 02'),pos(503,M)];
 assert.equal(t.entry(0),false,'buy entry refused');assert.equal(t.entry(1),false,'sell entry refused');
 assert.equal(t.c.g_GoatCidGuardReason,'orphan_suspected');assert.equal(t.c.GoatCidGuardStatus(),'Orphan Suspected');
 assert.equal(t.c.g_GoatCidGuardDetail,'orphan_magics='+O+' positions=502,501 orders=none');
 assert.deepEqual(t.refusal(),['GOAT CID guard v1: refusal=orphan_suspected magic='+M+' symbol=EURUSD orphan_magics='+O+' positions=502,501 orders=none'
  +' new_sequences=refused management=continues resolve=close_them_or_give_their_chart_a_CID_record_for_that_magic'],'one line per change');
 assert.deepEqual(t.phases.map(p=>p.phase),['orphan_suspected']);assert.equal(t.phases[0].target,CHART);
 // Still refused later, with no new line while nothing changed.
 t.c.now+=60000;assert.equal(t.entry(0),false);assert.equal(t.refusal().length,1);
 // Resolved by closing them: the next entry decision is allowed and the clearance is logged.
 t.acct.positions=[pos(503,M)];assert.equal(t.entry(0),true);
 assert.equal(t.refusal().at(-1),'GOAT CID guard v1: refusal=none magic='+M+' symbol=EURUSD cleared=orphan_suspected');
 assert.equal(t.c.GoatCidGuardStatus(),'');
 // Or resolved by a CID record that maps it (the chart that should manage it).
 const r=terminal({magic:M});r.acct.positions=[pos(501,O)];assert.equal(r.entry(0),false);
 r.record(O,'EURUSD',OTHER_CHART);assert.equal(r.entry(0),true);assert.match(r.refusal().at(-1),/refusal=none .* cleared=orphan_suspected$/);
 ok();}

// 1b. What counts as a GOAT magic: a positive 31-bit magic with GOAT evidence. Each kind of evidence refuses alone.
{const cases=[
  ['GOAT level comment, sell side',t=>{t.acct.positions=[pos(601,O,'MR fade Sell Lvl 07')];}],
  ['a GOAT record of any other field (HB) for that magic',t=>{t.acct.positions=[pos(601,O,'from #12345')];t.gv.set(KEY+'_ID_'+O+'_EURUSD_HB',1);}],
  ['a zeroed CID record (known, maps no chart)',t=>{t.acct.positions=[pos(601,O,'')];t.gv.set(KEY+'_ID_'+O+'_EURUSD_'+CID,0);}],
  ['this chart\'s own tag cut by the broker',t=>{t.c.Strat='EURUSD_O3_eagle_trend_breakout_v2';t.acct.positions=[pos(601,O,'EURUSD_O3_eagle_trend_breakout')];}],
  ['a pending order',t=>{t.acct.orders=[pos(901,O,'Trend Sell Lvl 01')];}],
  ['this terminal\'s own claim file (its chart ran it, the record is gone)',t=>{t.acct.positions=[pos(601,O,'x')];t.acct.common.set(t.c.GoatCidGuardClaimPath(O,'EURUSD'),t.c.GoatChildMagicSalt());}]];
 for(const [label,setup] of cases){const t=terminal({magic:M});setup(t);
  assert.equal(t.entry(0),false,label);assert.equal(t.c.g_GoatCidGuardReason,'orphan_suspected',label);}
 const o=terminal({magic:M});o.acct.orders=[pos(901,O,'Trend Sell Lvl 01')];o.entry(0);assert.equal(o.c.g_GoatCidGuardDetail,'orphan_magics='+O+' positions=none orders=901');
 // Many tickets: 16 listed, the count kept.
 const many=terminal({magic:M});many.acct.positions=Array.from({length:20},(_,i)=>pos(700+i,O));many.entry(0);
 assert.match(many.c.g_GoatCidGuardDetail,/^orphan_magics=907113355 positions=(\d+,){15}\d+ orders=none listed=16\/20$/);
 ok();}

// 2. Another chart's valid magic -> not refused (normal multi-chart use), nor anything that is not a GOAT magic.
{const allowed=[
  ['another chart on this symbol maps it',t=>{t.record(Y,'EURUSD',OTHER_CHART);t.acct.positions=[pos(801,Y)];}],
  ['a CID record of another symbol maps it',t=>{t.record(Y,'GBPUSD',OTHER_CHART);t.acct.positions=[pos(801,Y)];}],
  ['this chart\'s own magic',t=>{t.acct.positions=[pos(801,M),pos(802,M,'Trend Sell Lvl 03')];}],
  ['a manual trade (magic 0)',t=>{t.acct.positions=[pos(801,0,'Trend Buy Lvl 01')];}],
  ['another EA\'s trade (no GOAT evidence)',t=>{t.acct.positions=[pos(801,777,'grid bot #3')];t.acct.orders=[pos(802,778,'')];}],
  ['an orphan on another symbol',t=>{t.acct.positions=[pos(801,O,'Trend Buy Lvl 01','GBPUSD')];}],
  ['a magic above the 31-bit range',t=>{t.acct.positions=[pos(801,4294967296,'Trend Buy Lvl 01')];}]];
 for(const [label,setup] of allowed){const t=terminal({magic:M});setup(t);
  assert.equal(t.entry(0),true,label);assert.equal(t.c.g_GoatCidGuardReason,'',label);assert.deepEqual(t.refusal(),[],label);}
 // Same-login second terminal (B45 lifted the same-login two-terminal deploy): its chart claims its magic in
 // Common\Files, so this terminal does not call that terminal's positions orphans. Its own orphan still refuses.
 const acct=account(),a=terminal({acct,magic:M}),b=terminal({acct,dataPath:DATA_B,chart:OTHER_CHART,magic:Y});
 acct.positions=[pos(801,Y),pos(802,M)];
 // Cold start: until B's chart has run its check once, A cannot tell B's positions from orphans, so A refuses (fail closed).
 assert.equal(a.entry(0),false,'terminal A before B has claimed Y');assert.equal(a.c.g_GoatCidGuardDetail,'orphan_magics='+Y+' positions=801 orders=none');
 assert.equal(b.entry(0),true,'terminal B: M is claimed by terminal A, Y is its own');
 // B47: a claim is the terminal, then its TimeGMT() heartbeat.
 assert.equal(acct.common.get(b.c.GoatCidGuardClaimPath(Y,'EURUSD')),b.c.GoatChildMagicSalt()+'\r\n'+GMT0+'\r\n','B claimed Y');
 assert.equal(acct.common.get(a.c.GoatCidGuardClaimPath(M,'EURUSD')),a.c.GoatChildMagicSalt()+'\r\n'+GMT0+'\r\n','A claimed M');
 assert.notEqual(a.c.GoatChildMagicSalt(),b.c.GoatChildMagicSalt());
 assert.match(b.c.GoatCidGuardClaimPath(Y,'EURUSD'),/^GOAT\\CidGuard\\3000107825\\1210448821_EURUSD\.txt$/);
 assert.equal(a.entry(0),true,'terminal A: Y is claimed by terminal B on this login');
 acct.positions.push(pos(803,O));assert.equal(a.entry(0),false,'an unclaimed orphan still refuses on A');
 assert.equal(a.c.g_GoatCidGuardDetail,'orphan_magics='+O+' positions=803 orders=none');
 // A claim never moves: A does not overwrite B's claim file, and a claim by this same terminal is no exemption (1b).
 const before=new Map(acct.common);a.c.MAGIC1=Y;a.entry(0);assert.equal(acct.common.get(b.c.GoatCidGuardClaimPath(Y,'EURUSD')),before.get(b.c.GoatCidGuardClaimPath(Y,'EURUSD')));
 // Tester, optimization and forward passes never evaluate (no GlobalVariable read; backtests unchanged).
 const tester=terminal({tester:true,magic:M});tester.acct.positions=[pos(801,O)];
 assert.equal(tester.entry(0),true);assert.equal(tester.reads.gv,0);assert.deepEqual(tester.logs,[]);
 // The dashboard and Studio charts trade nothing and are never evaluated.
 for(const mode of [6,7]){const d=terminal({mode,magic:M});d.acct.positions=[pos(801,O)];assert.equal(d.c.GoatCidGuardRefuses(true),false);assert.equal(d.reads.gv,0);}
 ok();}

// 3. Existing-position management still runs while new sequences are refused. GoatTickBody's add-to-a-running-sequence
// branch is run as written: it never consults DashboardEntryAllowed, so the add still happens; only a new sequence or a
// virtual-to-real promotion (DashboardEntryAllowed) is refused.
{const t=terminal({magic:M});t.acct.positions=[pos(501,O),pos(502,M)];
 assert.equal(t.entry(0),false,'the guard refuses');assert.equal(t.c.DashboardTradeAllowed(0),true,'the add branch gate is unaffected');
 const BRANCH=region(main,'    if(Seq_Buy.Active)\n    {\n     if(buyMlpsExit)','//--------\n    if(Seq_Sell.Active)');
 for(const banned of ['DashboardEntryAllowed','GoatCidGuard'])assert.ok(!BRANCH.includes(banned),'the add branch never reads '+banned);
 const adds=[];
 Object.assign(t.c,{buyMlpsExit:false,LastBuyTradeSignal:false,Mode_Lots_Prog:0,Lots_Prog_CumPartial:1,Lots_Prog_PeakSmart:2,Partial_Profit_Factor:0,
  Peak_Smart_Release_PC:0,ask:1.0850,bid:1.0848,GRID_VALID:3,GetSize:()=>0.0020,RSI_Mode:0,RSI_Disabled:0,RSI_Sig:-1,
  Sequence_Pause_News:false,Sequence_Pause_Bias_B:false,Trades_Skipped_News:0,Trades_Skipped_Bias_B:0,DashboardPortfolioPaused:false,
  Seq_Buy:{Active:true,Traded:true,Level_Last:1.0900,Level_Count:2,Size_Grid:0.0020,Level_Retrace:0,BiasRescueActive:false,
   Add_Level:p=>{adds.push(p);return true;},HandlePartialRetrace(){},HandlePeakSmartRetrace(){}}});
 vm.runInContext('(function(){'+js(BRANCH)+'})()',t.c);
 assert.deepEqual(adds,[1.0850],'the running sequence adds its next level while new sequences are refused');
 // The guard's code changes no position, order or sequence.
 for(const [name,body] of Object.entries(G))
  for(const banned of ['OrderSend','PositionClose','PositionModify','OrderDelete','CTrade','Add_Level','End_Sequence','CloseAllPositions','ExpertRemove','Seq_'])
   assert.ok(!body.includes(banned),'GoatCidGuard '+name+' must not call '+banned);
 // DashboardEntryAllowed is the gate of every new sequence and of every virtual-to-real promotion, and of nothing else:
 // four SignalEntryTrigger starts and the two promotions in SEQUENCE::Add_Level.
 const calls=main.replace(/\/\/.*$/gm,'').split('\n').filter(l=>/DashboardEntryAllowed\(OP_(BUY|SELL)\)/.test(l)).map(l=>l.trim());
 assert.equal(calls.length,6);
 assert.equal(calls.filter(l=>/Seq_(Buy|Sell)(_Virtual)?\.Active/.test(l)&&/Mode_Trade/.test(l)).length,4,'SignalEntryTrigger: new real or virtual sequences');
 assert.equal(calls.filter(l=>/MustCheck_(Buy|Sell)\s*&&\s*DashboardEntryAllowed/.test(l)).length,2,'Add_Level: virtual-to-real promotion');
 const SIGNAL=bodyOf(main,'void SignalEntryTrigger()');assert.equal((SIGNAL.match(/DashboardEntryAllowed\(/g)||[]).length,4);
 // The guard is consulted at the entry gate (forced) and by the panel line (throttled); the status by the dashboard row.
 assert.equal(ENTRY.trim().split('\n')[0].trim(),'if(GoatCidGuardRefuses(true)) return false; // B46: a missing or duplicate CID record refuses new sequences (GoatCidGuardEvaluate)');
 const uses=main.split('\n').filter(l=>/GoatCidGuardRefuses\(|GoatCidGuardStatus\(\)/.test(l)&&!/^\s*(bool|string) GoatCidGuard/.test(l)&&!/^\s*\/\//.test(l)).map(l=>l.trim());
 assert.deepEqual(uses,[
  // B47: the add freeze (above the entry gate in the file) re-evaluates when its last check is older than GOAT_CID_ADD_RECHECK_MS.
  'GoatCidGuardRefuses(!g_GoatCidGuardChecked || GetTickCount()-g_GoatCidGuardCheckedMs>=GOAT_CID_ADD_RECHECK_MS);',
  'if(GoatCidGuardRefuses(true)) return false; // B46: a missing or duplicate CID record refuses new sequences (GoatCidGuardEvaluate)',
  'if(GoatCidGuardRefuses()) SetEdit(PanelDialog.m_edit_Info_2,"REFUSED: "+g_GoatCidGuardReason,clrRed,Font_Size); // B46: CID refusal on the panel',
  'if(GoatCidGuardStatus()!="") dashboard_status=GoatCidGuardStatus(); // B46: the dashboard row shows a CID refusal']);
 ok();}

// 4. Duplicate CID -> refused. Two records name this chart and symbol (GoatFindMagicByCid, unchanged in the pinned input
// header, would take whichever it meets first): new sequences are refused with cid_duplicate until one is removed.
{const t=terminal({magic:M});t.record(Y,'EURUSD',CHART);
 assert.equal(t.entry(0),false);assert.equal(t.c.g_GoatCidGuardReason,'cid_duplicate');assert.equal(t.c.GoatCidGuardStatus(),'CID Duplicate');
 const want='chart_cid='+t.c.GoatTruncateCidValue(CHART)+' record_magics='+Y+','+M+' records=GOAT_ID_<magic>_EURUSD_CID';
 assert.equal(t.c.g_GoatCidGuardDetail,want);
 assert.deepEqual(t.refusal(),['GOAT CID guard v1: refusal=cid_duplicate magic='+M+' symbol=EURUSD '+want
  +' new_sequences=refused management=continues resolve=keep_one_CID_record_for_this_chart_then_reattach']);
 assert.deepEqual(t.phases.map(p=>p.phase),['cid_duplicate']);
 t.gv.delete(KEY+'_ID_'+Y+'_EURUSD_'+CID);assert.equal(t.entry(0),true,'resolved');assert.match(t.refusal().at(-1),/cleared=cid_duplicate$/);
 // A duplicate outranks an orphan (the chart's own identity is in doubt first).
 const both=terminal({magic:M});both.record(Y,'EURUSD',CHART);both.acct.positions=[pos(501,O)];both.entry(0);assert.equal(both.c.g_GoatCidGuardReason,'cid_duplicate');
 // This chart's one record names another magic than the one it runs: refused too. (Its own record is restored first,
 // so this is two records, e.g. a hand-made record for the old magic while the chart runs a newly derived one.)
 const other=terminal({magic:M});other.gv.clear();other.record(O,'EURUSD',CHART);
 assert.equal(other.entry(0),false);assert.equal(other.c.g_GoatCidGuardReason,'cid_duplicate');
 assert.ok(other.gv.has(KEY+'_ID_'+M+'_EURUSD_'+CID),'its own record restored');
 // Not a duplicate: the same chart id under another symbol, or another chart's record on this symbol.
 const fine=terminal({magic:M});fine.record(Y,'GBPUSD',CHART);fine.record(O,'EURUSD',OTHER_CHART);assert.equal(fine.entry(0),true);
 ok();}

// 5. A dashboard launch or removal deletes every GOAT_ID_ record (GoatDeleteDashboardBusData). Running charts re-write
// their own CID record, so a sibling chart's positions are refused only until that sibling has run its check.
{const acct=account(),gv=new Map();
 const a=terminal({acct,gv,magic:Y,chart:OTHER_CHART}),b=terminal({acct,gv,magic:M});
 acct.positions=[pos(801,Y),pos(802,M)];
 assert.equal(a.entry(0),true);assert.equal(b.entry(0),true);
 for(const k of [...gv.keys()])if(k.startsWith(KEY+'_ID_'))gv.delete(k);
 assert.equal(b.entry(0),false,'right after the wipe, the sibling\'s positions have no record yet');
 assert.equal(b.c.g_GoatCidGuardReason,'orphan_suspected');assert.ok(gv.has(KEY+'_ID_'+M+'_EURUSD_'+CID),'b restored its own record');
 assert.ok(b.logs.includes('GOAT CID guard v1: restored this chart\'s missing CID record GOAT_ID_'+M+'_EURUSD_CID'));
 assert.equal(a.entry(0),true,'a restores its record');assert.equal(gv.get(KEY+'_ID_'+Y+'_EURUSD_'+CID),Number(a.c.GoatTruncateCidValue(OTHER_CHART)));
 assert.equal(b.entry(0),true,'and b clears');assert.match(b.refusal().at(-1),/cleared=orphan_suspected$/);
 ok();}

// 6. Re-check cadence: an entry decision always re-evaluates; the panel's per-second call re-reads at most every 5 s.
{const t=terminal({magic:M});
 assert.equal(t.c.GoatCidGuardRefuses(),false);const first=t.reads.gv;
 t.acct.positions=[pos(501,O)];t.c.now+=RECHECK-1;assert.equal(t.c.GoatCidGuardRefuses(),false,'cached within 5 s');assert.equal(t.reads.gv,first);
 t.c.now+=1;assert.equal(t.c.GoatCidGuardRefuses(),true,'re-read at 5 s');
 t.acct.positions=[];assert.equal(t.c.GoatCidGuardRefuses(),true,'cached');assert.equal(t.c.GoatCidGuardRefuses(true),false,'forced');
 ok();}

// 7. Source pins: the build identity (B49a); the input header (contract pin, and GoatFindMagicByCid in it) is unchanged.
{assert.match(main,/^#define   GOAT_BUILD_ID "V1\.49-BETA17-49"$/m);assert.match(main,/^#define   GOAT_BUILD_MARKER "B49a"$/m);
 const sha=crypto.createHash('sha256').update(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'))).digest('hex');
 const deps=JSON.parse(fs.readFileSync(path.join(ROOT,'controller/contracts/v149/dependencies.json'),'utf8').replace(/^\uFEFF/,''));
 assert.equal(sha,deps.header_sha256,'the input contract pins this GOAT_Inputs_Definitions.mqh (B49a changes it; test_b49a_no_drift.cjs)');
 // No new input, and the guard's claim files stay inside Common\Files\GOAT\CidGuard.
 assert.ok(!/cidg|CidGuard/i.test(main.split('\n').filter(l=>/^\s*s?input\b/.test(l)).join('\n')),'no B46/B47 input');
 assert.match(G.claimPath,/return "GOAT\\\\CidGuard\\\\"\+/);
 ok();}

// ---- B47 (Claude-Mac's B46 review): the remaining masking paths ----
const claimPath=(t,m)=>t.c.GoatCidGuardClaimPath(m,'EURUSD');
const addLogs=t=>t.logs.filter(l=>l.startsWith('GOAT CID guard v1: add_frozen='));

// 8. Stale CID records no longer mask an orphan. A record maps its magic only while its chart is open in this terminal
// with an EA on it (ChartFirst/ChartNext, compared as the truncated id the record stores).
{const closed=terminal({magic:M,charts:[{id:CHART,expert:'GOAT V1.49'}]});closed.record(O,'EURUSD',OTHER_CHART);closed.acct.positions=[pos(501,O)];
 assert.equal(closed.entry(0),false,'the record\'s chart was closed with trades open: refused');
 assert.equal(closed.c.g_GoatCidGuardDetail,'orphan_magics='+O+' positions=501 orders=none stale_records='+O);
 // The chart is reopened under a new chart id (MT5 gives a new chart a new id): the old record still names the old id.
 closed.c.charts.push({id:128604373052199999n,expert:'GOAT V1.49'});assert.equal(closed.entry(0),false,'reopened under a new id: still refused');
 // The record's chart open again: it maps, and the refusal clears.
 closed.c.charts.push({id:OTHER_CHART,expert:'GOAT V1.49'});assert.equal(closed.entry(0),true);assert.match(closed.refusal().at(-1),/cleared=orphan_suspected$/);
 // The chart is open but its EA was removed: the record maps nothing.
 const bare=terminal({magic:M,charts:[{id:CHART,expert:'GOAT V1.49'},{id:OTHER_CHART,expert:''}]});bare.record(O,'EURUSD',OTHER_CHART);bare.acct.positions=[pos(501,O,'manual note')];
 assert.equal(bare.entry(0),false,'chart open without an EA: refused (the record itself is GOAT evidence)');
 // A record of any symbol still maps while its chart is live (normal multi-chart use, B46 section 2 unchanged).
 const live=terminal({magic:M});live.record(O,'GBPUSD',OTHER_CHART);live.acct.positions=[pos(501,O)];assert.equal(live.entry(0),true);
 // The walk compares truncated ids: an 18-digit chart id matches the 16-digit value its record stores.
 assert.equal(live.c.GoatTruncateCidValue(OTHER_CHART),8604373052183077);
 // The walk is bounded.
 const many=terminal({magic:M,charts:Array.from({length:1500},(_,i)=>({id:128604373052100000n+BigInt(i),expert:'GOAT V1.49'})).concat([{id:CHART,expert:'GOAT V1.49'}])});
 const ids=[];many.c.GoatCidGuardLiveCharts(ids);assert.equal(ids.length,DEFS.GOAT_CID_CHART_WALK_MAX);
 ok();}

// 9. Claims carry a heartbeat (TimeGMT, the PC's one clock), re-stamped every 5 s from OnTimer; a claim older than
// GOAT_CID_CLAIM_STALE_SEC is unowned, and a stamp more than GOAT_CID_CLAIM_FUTURE_SEC ahead is unreadable.
{const acct=account(),a=terminal({acct,magic:M}),b=terminal({acct,dataPath:DATA_B,chart:OTHER_CHART,magic:Y});
 acct.positions=[pos(801,Y),pos(802,M)];
 b.c.GoatCidGuardHeartbeat();a.c.GoatCidGuardHeartbeat();
 assert.equal(acct.common.get(claimPath(b,Y)),b.c.GoatChildMagicSalt()+'\r\n'+GMT0+'\r\n','the timer heartbeat writes the claim');
 assert.equal(a.entry(0),true,'B\'s fresh claim exempts Y on A');
 acct.clock.gmt+=DEFS.GOAT_CID_CLAIM_STALE_SEC;assert.equal(a.entry(0),true,'exactly 180 s old: still owned');
 acct.clock.gmt+=1;assert.equal(a.entry(0),false,'B\'s chart stopped its heartbeat 181 s ago: unowned, refused');
 assert.equal(a.c.g_GoatCidGuardDetail,'orphan_magics='+Y+' positions=801 orders=none claims='+Y+':stale');
 // B's heartbeat: at most every 5 s (no write 4.999 s after the last), then it re-stamps and A clears.
 const w=b.reads.writes;b.c.now+=DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS-1;b.c.GoatCidGuardHeartbeat();assert.equal(b.reads.writes,w,'no write within 5 s');
 b.c.now+=1;b.c.GoatCidGuardHeartbeat();assert.equal(b.reads.writes,w+1,'re-stamped at 5 s');
 assert.equal(acct.common.get(claimPath(b,Y)),b.c.GoatChildMagicSalt()+'\r\n'+(GMT0+181)+'\r\n');
 assert.equal(a.entry(0),true,'fresh again');assert.match(a.refusal().at(-1),/cleared=orphan_suspected$/);
 // Clock skew on one PC (the clock stepped back): a stamp up to 30 s ahead is fresh, further ahead is unreadable.
 acct.common.set(claimPath(b,Y),b.c.GoatChildMagicSalt()+'\r\n'+(acct.clock.gmt+DEFS.GOAT_CID_CLAIM_FUTURE_SEC)+'\r\n');assert.equal(a.entry(0),true,'30 s ahead: fresh');
 acct.common.set(claimPath(b,Y),b.c.GoatChildMagicSalt()+'\r\n'+(acct.clock.gmt+DEFS.GOAT_CID_CLAIM_FUTURE_SEC+1)+'\r\n');assert.equal(a.entry(0),false,'31 s ahead: unreadable');
 assert.match(a.c.g_GoatCidGuardDetail,/ claims=1210448821:unreadable$/);
 // A stale claim by another terminal is taken over by the chart that runs the magic; a fresh one never is.
 const c2=terminal({acct,dataPath:DATA_B,chart:OTHER_CHART,magic:Y});
 acct.common.set(claimPath(b,Y),a.c.GoatChildMagicSalt()+'\r\n'+(acct.clock.gmt-DEFS.GOAT_CID_CLAIM_STALE_SEC-1)+'\r\n');c2.c.GoatCidGuardHeartbeat();
 assert.equal(acct.common.get(claimPath(b,Y)),b.c.GoatChildMagicSalt()+'\r\n'+acct.clock.gmt+'\r\n','stale claim re-stamped by its running chart');
 const fresh=a.c.GoatChildMagicSalt()+'\r\n'+acct.clock.gmt+'\r\n';acct.common.set(claimPath(b,Y),fresh);c2.c.now+=DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS;c2.c.GoatCidGuardHeartbeat();
 assert.equal(acct.common.get(claimPath(b,Y)),fresh,'another terminal\'s fresh claim is never overwritten');
 // The source clock is TimeGMT() for both the stamp and the age, and the heartbeat runs on the timer.
 assert.ok(G.claim.includes('IntegerToString((long)TimeGMT())')&&G.claimRead.includes('(long)TimeGMT()-cidg_stamp'));
 for(const body of Object.values(G))assert.ok(!/TimeCurrent|TimeLocal|TimeTradeServer/.test(body),'one clock: TimeGMT only');
 const TIMER=bodyOf(main,'void GoatTimerBody(void)');
 assert.match(TIMER,/    GOATDeviceActivationTimer\(\);\n    return;\n   \}\n   GoatCidGuardHeartbeat\(\); \/\/ B47: /,'the heartbeat runs on every timer tick after the activation-only return');
 ok();}

// 10. An unreadable claim (cannot be opened, empty, no stamp, a B46 one-line claim) is GOAT evidence with no owner: it
// refuses. It never counts as "no claim".
{const base=terminal({magic:M});base.acct.positions=[pos(501,O,'manual note')];
 assert.equal(base.entry(0),true,'no claim, no record, no GOAT comment: not a GOAT magic');
 const cases=[['locked (cannot be opened)',t=>{t.acct.common.set(claimPath(t,O),'x\r\n'+GMT0+'\r\n');t.acct.locked.add(claimPath(t,O));}],
  ['empty',t=>t.acct.common.set(claimPath(t,O),'')],
  ['no stamp (a B46 claim)',t=>t.acct.common.set(claimPath(t,O),'3000107825@1179426635')],
  ['garbled stamp',t=>t.acct.common.set(claimPath(t,O),'3000107825@1179426635\r\n17920x0000\r\n')],
  ['no owner',t=>t.acct.common.set(claimPath(t,O),'\r\n'+GMT0+'\r\n')]];
 for(const [label,setup] of cases){const t=terminal({magic:M});t.acct.positions=[pos(501,O,'manual note')];setup(t);
  assert.equal(t.entry(0),false,label);assert.equal(t.c.g_GoatCidGuardDetail,'orphan_magics='+O+' positions=501 orders=none claims='+O+':unreadable',label);}
 ok();}

// 11. No claim is written while the account login is 0 (not yet connected); it is written once the login is known.
{const t=terminal({magic:M,login:0});t.c.GoatCidGuardHeartbeat();t.entry(0);
 assert.equal(t.acct.common.size,0);assert.equal(t.reads.writes,0);
 t.c.login=LOGIN;t.c.GoatCidGuardHeartbeat();assert.ok(t.acct.common.has(claimPath(t,M)));assert.match(claimPath(t,M),/^GOAT\\CidGuard\\3000107825\\/);
 for(const opts of [{tester:true},{mode:6},{mode:7}]){const x=terminal({magic:M,...opts});x.c.GoatCidGuardHeartbeat();assert.equal(x.reads.writes,0,JSON.stringify(opts));}
 ok();}

// 12. Under cid_duplicate the running sequence's adds (grid and rescue: every real SEQUENCE::Add_Level) are frozen and
// logged once per side; closes, stops, trailing and MLPS never consult the freeze. orphan_suspected does not freeze.
{const t=terminal({magic:M});
 assert.equal(t.c.GoatCidGuardAddFrozen(0,3),false,'no duplicate: adds run');assert.deepEqual(addLogs(t),[]);
 t.record(Y,'EURUSD',CHART);
 t.c.now+=DEFS.GOAT_CID_ADD_RECHECK_MS-1;assert.equal(t.c.GoatCidGuardAddFrozen(0,3),false,'within 1 s the cached state holds');
 t.c.now+=1;assert.equal(t.c.GoatCidGuardAddFrozen(0,3),true,'re-evaluated at 1 s: frozen');
 assert.equal(t.c.GoatCidGuardAddFrozen(0,4),true);assert.equal(t.c.GoatCidGuardAddFrozen(1,2),true);
 assert.deepEqual(addLogs(t),['GOAT CID guard v1: add_frozen=cid_duplicate side=BUY magic='+M+' symbol=EURUSD level=3 '+t.c.g_GoatCidGuardDetail+' closes_stops_trailing=continue',
  'GOAT CID guard v1: add_frozen=cid_duplicate side=SELL magic='+M+' symbol=EURUSD level=2 '+t.c.g_GoatCidGuardDetail+' closes_stops_trailing=continue'],'once per side');
 assert.deepEqual(t.phases.map(p=>p.phase),['cid_duplicate','add_frozen','add_frozen']);
 t.gv.delete(KEY+'_ID_'+Y+'_EURUSD_'+CID);t.c.now+=DEFS.GOAT_CID_ADD_RECHECK_MS;
 assert.equal(t.c.GoatCidGuardAddFrozen(0,4),false,'resolved: adds run again');
 t.record(Y,'EURUSD',CHART);t.c.now+=DEFS.GOAT_CID_ADD_RECHECK_MS;assert.equal(t.c.GoatCidGuardAddFrozen(0,4),true);assert.equal(addLogs(t).length,3,'a new episode logs again');
 const orphan=terminal({magic:M});orphan.acct.positions=[pos(501,O)];assert.equal(orphan.c.GoatCidGuardAddFrozen(0,3),false,'orphan_suspected: the chart\'s own sequence keeps adding');
 assert.equal(orphan.c.g_GoatCidGuardReason,'orphan_suspected');
 const tester=terminal({tester:true,magic:M});tester.record(Y,'EURUSD',CHART);assert.equal(tester.c.GoatCidGuardAddFrozen(0,3),false,'never in the tester');
 // Where it sits: the first statement of SEQUENCE::Add_Level after the expiry check, for real sequences only. Every
 // order goes through it: OpenPosition's one caller is Add_Level, which also counts the rescue adds.
 const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 assert.deepEqual(ADD.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l)).slice(0,2).map(l=>l.trim().slice(0,40)),
  ['if(TimeCurrent()>Expiry) {Alert("This ve','if(!Virtual && GoatCidGuardAddFrozen(dir']);
 assert.ok(ADD.includes('    if(!Virtual && GoatCidGuardAddFrozen(dir,Level_Count+1)) return false; // B47: '));
 assert.ok(ADD.includes('OpenPosition(dir,MAGIC1,')&&ADD.includes('BiasRescuePositiveAdds++'));
 assert.equal((main.match(/\bOpenPosition\(/g)||[]).length,2,'OpenPosition: defined once, called once (in Add_Level)');
 assert.equal((main.match(/GoatCidGuardAddFrozen\(/g)||[]).length,2,'the freeze: defined once, called once (in Add_Level)');
 ok();}

// 13. B49a (B48): the daily CID touch. MT5 drops a GlobalVariable after 4 weeks without access, so once per UTC day
// the timer heartbeat re-sets this chart's own record to its own value (a missing one is restored to this chart's id).
// A failed write is logged once and retried no sooner than 60 s. Live charts only, through the B47 heartbeat.
{const DAY=86400,own=KEY+'_ID_'+M+'_EURUSD_'+CID;
 assert.equal(DEFS.GOAT_CID_TOUCH_RETRY_MS,60000);
 const touchLogs=t=>t.logs.filter(l=>l.startsWith('GOAT CID touch: '));
 const t=terminal({magic:M});const value=t.gv.get(own);assert.ok(value>0,'OnInit wrote the record');
 const sets=()=>t.reads.gvSet||0;
 t.c.GoatCidGuardHeartbeat();
 assert.equal(sets(),1,'the first heartbeat of the UTC day re-sets the record');assert.equal(t.gv.get(own),value,'to its own value');
 assert.equal(t.reads.gvFlush,1,'and flushes it to disk (Ops/Mac GOAT-EA#264: a hard kill keeps the renewal)');
 assert.deepEqual(touchLogs(t),['GOAT CID touch: renewed '+own+' for UTC day 2026.10.15']);
 t.c.now+=DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS;t.acct.clock.gmt+=DAY/2;t.c.GoatCidGuardHeartbeat();
 assert.equal(sets(),1,'not again the same UTC day');
 t.acct.clock.gmt+=DAY/2;t.c.now+=DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS;t.c.GoatCidGuardHeartbeat();
 assert.equal(sets(),2,'once on the next UTC day');assert.equal(touchLogs(t).at(-1),'GOAT CID touch: renewed '+own+' for UTC day 2026.10.16');
 // A missing record (dropped by MT5) is restored to this chart's id, the value GoatCidGuardEvaluate writes.
 t.gv.delete(own);t.acct.clock.gmt+=DAY;t.c.GoatCidGuardHeartbeat();
 assert.equal(t.gv.get(own),Number(t.c.GoatTruncateCidValue(CHART)));
 assert.equal(touchLogs(t).at(-1),'GOAT CID touch: restored missing '+own+' for UTC day 2026.10.17');
 // A refused write: logged once, retried no sooner than 60 s, and the day is only marked once a write succeeds.
 t.acct.clock.gmt+=DAY;t.c.gvSetFails=true;const before=sets();
 t.c.GoatCidGuardHeartbeat();assert.equal(sets(),before+1);
 assert.equal(touchLogs(t).at(-1),'GOAT CID touch: write failed for '+own+' (error 4501); retrying');
 assert.equal(t.reads.gvFlush,3,'a refused write is not flushed');
 t.c.now+=DEFS.GOAT_CID_TOUCH_RETRY_MS-1;t.c.GoatCidGuardHeartbeat();assert.equal(sets(),before+1,'no retry within 60 s');
 t.c.now+=1;t.c.GoatCidGuardHeartbeat();assert.equal(sets(),before+2,'retried at 60 s');
 assert.equal(touchLogs(t).filter(l=>l.includes('write failed')).length,1,'the failure is logged once');
 t.c.gvSetFails=false;t.c.now+=DEFS.GOAT_CID_TOUCH_RETRY_MS;t.c.GoatCidGuardHeartbeat();assert.equal(sets(),before+3);
 assert.equal(touchLogs(t).at(-1),'GOAT CID touch: renewed '+own+' for UTC day 2026.10.18');
 t.c.now+=DEFS.GOAT_CID_TOUCH_RETRY_MS;t.c.GoatCidGuardHeartbeat();assert.equal(sets(),before+3,'done for the day');
 // Claude-Mac GOAT-EA#264 P2: a record wiped between the check and the read is never re-set to 0 (that would orphan
 // this chart's positions at the next restart); the touch skips, and the next heartbeat restores it to the chart id.
 {const w=terminal({magic:M}),wsets=()=>w.reads.gvSet||0;
  w.c.wipeAfterCheck=own;w.c.GoatCidGuardHeartbeat();
  assert.equal(wsets(),0,'no write after the record vanished between check and read');assert.equal(w.gv.has(own),false);
  assert.equal(w.c.g_GoatCidTouchedDay,0,'the day is not marked');
  w.c.now+=DEFS.GOAT_CID_CLAIM_HEARTBEAT_MS;w.c.GoatCidGuardHeartbeat();
  assert.equal(w.gv.get(own),Number(w.c.GoatTruncateCidValue(CHART)),'the next heartbeat restores the chart id, never 0');
  // A record that holds 0 or less is not renewed either (it is not this chart's id).
  const z=terminal({magic:M});z.gv.set(own,0);z.c.GoatCidGuardHeartbeat();
  assert.equal(z.reads.gvSet||0,0,'a 0 record is never re-set');assert.equal(z.gv.get(own),0);}
 // Never in the tester, a batch or the dashboard (the B47 heartbeat returns first), and never without a magic.
 for(const opts of [{tester:true,magic:M},{mode:6,magic:M},{mode:7,magic:M},{magic:0}]){
  const x=terminal(opts);x.c.GoatCidGuardHeartbeat();assert.equal(x.reads.gvSet||0,0,JSON.stringify(opts));
 }
 // Where it runs: GoatCidGuardHeartbeat, which only GoatTimerBody calls, so it needs no tick.
 assert.ok(G.heartbeat.includes('   GoatCidDailyTouch(); // B49a (B48): the daily CID record touch'));
 assert.equal((main.match(/\bGoatCidDailyTouch\(/g)||[]).length,2,'GoatCidDailyTouch: defined once, called once (the heartbeat)');
 assert.equal((main.match(/\bGoatCidGuardHeartbeat\(\);/g)||[]).length,1,'the heartbeat: called once');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('GoatCidGuardHeartbeat();'),'from the timer');
 ok();}

console.log(JSON.stringify({passed,test:'cid_guard',productionFunctions:Object.keys(G).map(k=>'GoatCidGuard.'+k).concat(['DashboardEntryAllowed','DashboardTradeAllowed','GoatChildMagicSalt','GoatParseChildGVName','GoatTruncateCidValue','GoatChildGVName','GoatTickBody add branch'])}));
