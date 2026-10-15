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
const TYPES='(?:const )?(?:string|int|uint|long|ulong|bool|ushort|double)';
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
 claimOwner:bodyOf(main,'string GoatCidGuardClaimOwner(const long cidg_magic,const string cidg_symbol)'),
 claim:bodyOf(main,'void GoatCidGuardClaim(const string cidg_terminal)'),
 orphan:bodyOf(main,'bool GoatCidGuardOrphan('),
 evaluate:bodyOf(main,'string GoatCidGuardEvaluate(string &cidg_detail)'),
 refuses:bodyOf(main,'bool GoatCidGuardRefuses(const bool cidg_force=false)'),
 status:bodyOf(main,'string GoatCidGuardStatus(void)'),
};
const ENTRY=bodyOf(main,'bool DashboardEntryAllowed(const int op)');
const TRADE=bodyOf(main,'bool DashboardTradeAllowed(const int op)');
const RECHECK=Number((main.match(/^#define GOAT_CID_GUARD_RECHECK_MS (\d+)$/m)||[])[1]);assert.equal(RECHECK,5000);
const code=
 'function GoatParseChildGVName(gv_name,__m,__s,__f){let magic=0,symbol="",field="";'
  +js(once(PARSE,'return(symbol!="" && field!="");','__m(magic);__s(symbol);__f(field);return(symbol!="" && field!="");','parse return'))+'}\n'
 +fn('GoatTruncateCidValue',['cid'],TRUNC)+fn('GoatChildGVName',['magic','symbol','field'],GVNAME)+fn('GoatChildMagicSalt',[],SALT)
 +fn('GoatCidGuardHas',['cidg_list','cidg_value'],G.has)+fn('GoatCidGuardAdd',['cidg_list','cidg_value'],G.add)
 +fn('GoatCidGuardJoin',['cidg_list'],G.join)+fn('GoatCidGuardGoatComment',['cidg_comment'],G.comment)
 +fn('GoatCidGuardClaimPath',['cidg_magic','cidg_symbol'],G.claimPath)+fn('GoatCidGuardClaimOwner',['cidg_magic','cidg_symbol'],G.claimOwner)
 +fn('GoatCidGuardClaim',['cidg_terminal'],G.claim)
 +fn('GoatCidGuardOrphan',['cidg_magic','cidg_comment','cidg_mapped','cidg_known','cidg_terminal'],G.orphan)
 // The detail is a by-reference output: the converted body writes the enclosing cidg_detail.
 +'function GoatCidGuardEvaluate(__box){let cidg_detail="";const __r=(()=>{'+js(G.evaluate)+'})();__box.v=cidg_detail;return __r;}\n'
 +'function GoatCidGuardRefuses(cidg_force=false){'
  +once(js(G.refuses),'let cidg_reason=GoatCidGuardEvaluate(cidg_detail);','const __b={v:""};let cidg_reason=GoatCidGuardEvaluate(__b);cidg_detail=__b.v;','evaluate call')+'}\n'
 +fn('GoatCidGuardStatus',[],G.status)+fn('DashboardEntryAllowed',['op'],ENTRY)+fn('DashboardTradeAllowed',['op'],TRADE);

const KEY=(header.match(/^#define\s+Key\s+"(\w+)"/m)||[])[1];assert.equal(KEY,'GOAT');
const CID=(header.match(/^#define GOAT_GV_FIELD_CID\s+"(\w+)"/m)||[])[1];assert.equal(CID,'CID');
const DATA_A='C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\D0E8209F77C8CF37AD8BF550E51FF075';
const DATA_B='C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\5B9A1E3C0D44F2A7B61C93E8A02D7F11';
const CHART=128604373052183041n,OTHER_CHART=128604373052183077n,LOGIN=3000107825;
// One account (positions and orders), one PC (Common\Files); each terminal has its own GlobalVariables.
function account(){return {positions:[],orders:[],common:new Map()};}
function terminal({acct=account(),gv=new Map(),login=LOGIN,dataPath=DATA_A,chart=CHART,symbol='EURUSD',magic=0,tester=false,mode=0,strat='Trend'}={}){
 const logs=[],phases=[],reads={gv:0},handles=new Map();let next=0;
 const c={Key:KEY,GOAT_GV_FIELD_CID:CID,GOAT_CID_GUARD_RECHECK_MS:RECHECK,
  MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,MQLInfoInteger:k=>(k===1&&tester)?1:0,
  Mode_Operation:mode,Operation_Batch:6,Operation_Dash:7,Strat:strat,MAGIC1:magic,
  ACCOUNT_LOGIN:7,TERMINAL_DATA_PATH:8,AccountInfoInteger:k=>{assert.equal(k,7);return login;},
  TerminalInfoString:k=>{assert.equal(k,8);return dataPath;},
  StringFind:(s,t,from=0)=>s.indexOf(t,from),StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringGetCharacter:(s,i)=>s.charCodeAt(i),IntegerToString:v=>String(v),StringFormat:(f,v)=>{assert.equal(f,'%I64d');return String(v);},
  StringToInteger:s=>{const m=String(s).match(/^\s*-?\d+/);if(!m)return 0;const b=BigInt(m[0]);return b>=-(2n**53n)&&b<=2n**53n?Number(b):b;},
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},
  GlobalVariablesTotal:()=>{reads.gv++;return gv.size;},GlobalVariableName:i=>[...gv.keys()][i],GlobalVariableGet:k=>gv.get(k)??0,
  GlobalVariableCheck:k=>gv.has(k),GlobalVariableSet:(k,v)=>{gv.set(k,Number(v));return 1;},
  Symbol:()=>symbol,ChartID:()=>chart,
  POSITION_SYMBOL:11,POSITION_COMMENT:12,POSITION_MAGIC:13,ORDER_SYMBOL:21,ORDER_COMMENT:22,ORDER_MAGIC:23,
  PositionsTotal:()=>acct.positions.length,PositionGetTicket:i=>{c.selP=acct.positions[i];return c.selP.ticket;},
  PositionGetString:k=>{assert.ok(k===11||k===12);return k===11?c.selP.symbol:c.selP.comment;},
  PositionGetInteger:k=>{assert.equal(k,13);return c.selP.magic;},
  OrdersTotal:()=>acct.orders.length,OrderGetTicket:i=>{c.selO=acct.orders[i];return c.selO.ticket;},
  OrderGetString:k=>{assert.ok(k===21||k===22);return k===21?c.selO.symbol:c.selO.comment;},
  OrderGetInteger:k=>{assert.equal(k,23);return c.selO.magic;},
  FILE_READ:1,FILE_WRITE:2,FILE_TXT:16,FILE_ANSI:32,FILE_SHARE_READ:64,FILE_SHARE_WRITE:128,FILE_COMMON:4096,INVALID_HANDLE:-1,
  FileIsExist:(p,f)=>{assert.equal(f,4096,'Common files only');return acct.common.has(p);},
  FileOpen:(p,flags)=>{assert.ok(flags&4096,'Common files only');if(flags&2)acct.common.set(p,'');else if(!acct.common.has(p))return -1;handles.set(++next,p);return next;},
  FileReadString:h=>acct.common.get(handles.get(h)).split('\r\n')[0],
  FileWriteString:(h,s)=>{const p=handles.get(h);acct.common.set(p,acct.common.get(p)+s);return s.length;},
  FileClose:h=>{handles.delete(h);},FolderCreate:(p,f)=>{assert.equal(f,4096);return true;},
  Print:s=>logs.push(s),GoatDeploymentPhase:(phase,target,control)=>phases.push({phase,target,control}),
  now:500000,GetTickCount:()=>c.now,
  // DashboardEntryAllowed's other gates, open: only the B46 guard decides here.
  g_GoatStudioMonitorRunPath:'',GoatStagedChildMayOpen:()=>true,DashboardExposureConflict:()=>false,
  DashboardTradeAllowBuy:true,DashboardTradeAllowSell:true,OP_BUY:0,OP_SELL:1,
  g_GoatCidGuardReason:'',g_GoatCidGuardDetail:'',g_GoatCidGuardCheckedMs:0,g_GoatCidGuardChecked:false};
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
 assert.equal(acct.common.get(b.c.GoatCidGuardClaimPath(Y,'EURUSD')),b.c.GoatChildMagicSalt(),'B claimed Y');
 assert.equal(acct.common.get(a.c.GoatCidGuardClaimPath(M,'EURUSD')),a.c.GoatChildMagicSalt(),'A claimed M');
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
 assert.deepEqual(uses,['if(GoatCidGuardRefuses(true)) return false; // B46: a missing or duplicate CID record refuses new sequences (GoatCidGuardEvaluate)',
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

// 7. Source pins: B46 build identity; the input header (contract pin, and GoatFindMagicByCid in it) is unchanged.
{assert.match(main,/^#define   GOAT_BUILD_ID "V1\.49-BETA17-46"$/m);assert.match(main,/^#define   GOAT_BUILD_MARKER "B46"$/m);
 const sha=crypto.createHash('sha256').update(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'))).digest('hex');
 const deps=JSON.parse(fs.readFileSync(path.join(ROOT,'controller/contracts/v149/dependencies.json'),'utf8').replace(/^\uFEFF/,''));
 assert.equal(sha,deps.header_sha256,'GOAT_Inputs_Definitions.mqh is unchanged (input contract pin)');
 // No new input, and the guard's claim files stay inside Common\Files\GOAT\CidGuard.
 assert.ok(!/cidg|CidGuard/i.test(main.split('\n').filter(l=>/^\s*s?input\b/.test(l)).join('\n')),'no B46 input');
 assert.match(G.claimPath,/return "GOAT\\\\CidGuard\\\\"\+/);
 ok();}

console.log(JSON.stringify({passed,test:'cid_guard',productionFunctions:Object.keys(G).map(k=>'GoatCidGuard.'+k).concat(['DashboardEntryAllowed','DashboardTradeAllowed','GoatChildMagicSalt','GoatParseChildGVName','GoatTruncateCidValue','GoatChildGVName','GoatTickBody add branch'])}));
