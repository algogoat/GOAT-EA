// B49a (F1-lite; roadmap F1/D8, WEEKEND-1031 goatai#2587 6427772701 / 6428370704 / 6428447507): restart adoption.
// Through B47 OnInit re-created empty sequences, so after a restart an open basket kept only its broker TP/SL: MLPS
// never fired again and a new sequence could start beside it. Now, on live charts only:
// - a restart record per magic + symbol + direction (terminal GlobalVariables): the first level's ticket and the five
//   sizes frozen at start, the level count, the realized P/L (the timer, at most every GOAT_SQ_FLUSH_MS), the first
//   position's open time in ms (written last); the whole record rewritten from memory once per UTC day; every write
//   flushed to gvariables.dat; deleted at the end, and before a new start; a failed write freezes adds;
// - OnInit adopts an open basket with no running sequence: levels from the live positions, Active, Traded and
//   manage-only (adds frozen). A matching record (its first ticket still live, or every live position opened at or after
//   its start with their count within its level count) restores the realized P/L (under PositionJoin recounted from
//   history, so closes made while the EA was down count) and the frozen sizes; the stops are never loosened. Without a
//   match the EA leaves that basket's broker SL/TP untouched.
// This runs the production SEQUENCE methods, UpdateLockTPSL included, and GetSize (syntax-only MQL-to-JS conversion)
// against modelled positions, deals and GlobalVariables, one fresh SEQUENCE per "terminal start"; B47's GetSize runs
// on the same state. Source semantics only: Ops' drill on T2 is the native check (ATR-mode SET; MLPS fires at -Risk,
// adds stay frozen, no second same-direction sequence, a trailed SL survives a hard kill, no array out of range).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B47_SOURCE='ccb0a07';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
// test_restart_adopt_mutations.cjs points GOAT_EA_MAIN at a mutated entrypoint.
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const mainB47=clean(execFileSync('git',['show',B47_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 // Braces are counted outside comments and strings (UpdateLockTPSL keeps commented-out code with braces).
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
function js(text){
 return text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
  .replace(/C'\d+,\d+,\d+'/g,'0')                                   // MQL color literals
  .replace(/^\s*static\s+double\s+LastATRBid,LastATRAsk;\s*$/m,'')   // GetSize's statics live in the context
  .replace(/\bCTrade\s+(\w+);/g,'let $1=CTrade();')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]\\s*=\\s*\\{([^}]*)\\};','g'),'let $1=[$2];')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[(\\d+)\\];','g'),'let $1=new Array($2).fill(0);')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]','g'),'let $1=[]')
  .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
  .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'')
  // By-reference outputs become setter callbacks.
  .replace(/PersistRead\(("\w+"|\w+\[\w+\]),(\w+(?:\[\d\])?)\)/g,'PersistRead($1,v=>$2=v)')
  .replace(/GlobalVariableGet\(([^,()]+(?:\([^()]*\))?),(\w+)\)/g,'GlobalVariableGetRef($1,$2)');
}
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const METHODS=[
 ['PersistReset',[],'   void PersistReset()'],['PersistLive',[],'   bool PersistLive()'],
 ['PersistKey',['field'],'   string PersistKey(const string field)'],
 ['PersistWrite',['field','value'],'   bool PersistWrite(const string field,const double value)'],
 ['PersistWriteAll',['start_msc'],'   bool PersistWriteAll(const long start_msc)'],
 ['PersistStart',['first_ticket'],'   void PersistStart(const ulong first_ticket)'],
 ['PersistLevels',[],'   void PersistLevels()'],
 ['PersistFlush',['force=false'],'   void PersistFlush(const bool force=false)'],
 ['PersistEnd',[],'   void PersistEnd()'],
 ['ManageOnlyFrozen',['level'],'   bool ManageOnlyFrozen(const int level)'],
 ['PersistRead',['field','value'],'   bool PersistRead(const string field,double &value)'],
 ['RealizedFromHistory',['start_msc','fallback'],'   double RealizedFromHistory(const long start_msc,const double fallback)'],
 ['AdoptOpenPositions',[],'   bool AdoptOpenPositions()'],
 ['LedgerHasPosition',['position_id'],'   bool LedgerHasPosition(const ulong position_id)'],
 ['LedgerAddPosition',['position_ticket'],'   void LedgerAddPosition(const ulong position_ticket)'],
 ['LedgerBook',['deal_ticket'],'   bool LedgerBook(const ulong deal_ticket)'],
 ['ClosedDealPL',['deal_ticket'],'   double ClosedDealPL(const ulong deal_ticket)'],
 ['TighterBiasStop',['first_sl','second_sl'],'   double TighterBiasStop(const double first_sl,const double second_sl)'],
 ['UpdateLockTPSL',['count=0'],'   void UpdateLockTPSL(int count=0)'],
 ['SizesUnavailable',[],'   bool SizesUnavailable()'],
 ['EnforceSequenceMLPS',['context'],'   bool EnforceSequenceMLPS(const string context)'],
 // B49b (PR-0): the start-distance refusal over the real solver path, and the adopted TP.
 ['TighterTakeProfit',['first_tp','second_tp'],'   double TighterTakeProfit(const double first_tp,const double second_tp)'],
 ['StartDistancesUnavailable',[],'   bool StartDistancesUnavailable()'],
 ['BuildDistances',[],'   void BuildDistances()'],
 ['FindCumLoss',[],'   double FindCumLoss()'],
 ['EvalLossForStart',['L0'],'   double EvalLossForStart(double L0)'],
 ['SolveStartLotsByRisk',['targetLoss'],'   double SolveStartLotsByRisk(double targetLoss)'],
];
const FLUSH_MS=Number((main.match(/^#define GOAT_SQ_FLUSH_MS (\d+)$/m)||[])[1]);assert.equal(FLUSH_MS,5000);
const UPDATE_GUARD='    if(Adopted && !AdoptSizes) return; // B49a (F1-lite): an adopted basket without its frozen sizes keeps its broker SL/TP';
const firstStatement=body=>body.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l))[0];

// ---- the modelled terminal: positions and deals (account-wide), GlobalVariables (this terminal), the clocks ----
const M=1843920117,Y=907113355,SYM='EURUSD',T0=1792054800000;
const K={POSITION_MAGIC:'magic',POSITION_SYMBOL:'symbol',POSITION_TYPE:'type',POSITION_TIME_MSC:'msc',POSITION_PRICE_OPEN:'open',
 POSITION_VOLUME:'volume',POSITION_SL:'sl',POSITION_TP:'tp',POSITION_IDENTIFIER:'identifier',POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,
 DEAL_ENTRY:'entry',DEAL_ENTRY_IN:0,DEAL_ENTRY_OUT:1,DEAL_ENTRY_OUT_BY:3,DEAL_TYPE:'type',DEAL_TYPE_BUY:0,DEAL_TYPE_SELL:1,DEAL_MAGIC:'magic',
 DEAL_SYMBOL:'symbol',DEAL_POSITION_ID:'position',DEAL_TIME_MSC:'msc',DEAL_PROFIT:'profit',DEAL_COMMISSION:'commission',DEAL_SWAP:'swap',
 DEAL_FEE:'fee',OP_BUY:0,OP_SELL:1,Key:'GOAT',Ledger_Legacy:0,Ledger_PositionJoin:1,Operation_Batch:6,Operation_Dash:7,Operation_Standard:0,
 MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,Lots_Prog_CumPartial:5,Lots_Prog_PeakSmart:6};
const GMT0=Math.floor(T0/1000)+3600;   // TimeGMT() at the first level
function terminal({positions=[],gv=new Map(),tester=false,mode=0,ledger=1}={}){
 return {positions,gv,tester,mode,ledger,deals:[],now:1000,gmt:GMT0,flushes:0,writes:[],failWrites:new Set(),logs:[],alerts:[],modifies:[],
  counts:{buy:0,sell:0},closes:[]};
}
const pos=(ticket,{magic=M,type=0,msc=T0,open=1.1,volume=0.1,sl=0,tp=0,symbol=SYM}={})=>({ticket,magic,type,msc,open,volume,sl,tp,symbol,identifier:ticket});
// A deal in the account history (entries carry the opening magic; exits may carry any).
const deal=(t,d)=>{const ticket=5000+t.deals.length+1;t.deals.push({ticket,symbol:SYM,commission:0,swap:0,fee:0,profit:0,...d,ticket});return ticket;};
// One SEQUENCE in a terminal start (a restart is a fresh SEQUENCE over the same terminal).
function sequence(t,{dir=0,virtual=false}={}){
 let sel=null,history=[];
 const levels=[];levels.objects=true;
 const c={...K,MAGIC1:M,_Symbol:SYM,dir,Virtual:virtual,Desc:'Trend '+(dir?'Sell':'Buy'),Ledger_Mode:t.ledger,Mode_Operation:t.mode,
  Max_Seq_Levels:64,Max_Seq_Trades:10,Lock_Profit_Flexibility:1.0,Mode_Lots_Prog:5,_Digits:5,GOAT_SQ_FLUSH_MS:FLUSH_MS,TradeLevels:levels,
  LedgerPositions:[],LedgerDeals:[],Active:false,Traded:false,BiasRescueActive:false,Level_Count:0,Trades_Count:0,Level_Last:0,Level_SL:0,
  Level_TSL:0,Level_Lock:0,Level_TP:0,Level_Entry:0,LotsTotal:0,SequenceRealizedPL:0,TPmodifyErrors:0,TPSLmodifieds:0,
  Size_Grid:1234.5,Size_Lock:1234.5,Size_TP:1234.5,Size_SL:1234.5,Size_TSL:1234.5,
  get LastTradeCountBuy(){return t.counts.buy;},set LastTradeCountBuy(v){t.counts.buy=v;},
  get LastTradeCountSell(){return t.counts.sell;},set LastTradeCountSell(v){t.counts.sell=v;},
  MQLInfoInteger:k=>(k===1&&t.tester)?1:0,GetTickCount:()=>t.now,TimeCurrent:()=>Math.floor(T0/1000)+3600,TimeGMT:()=>t.gmt,
  GlobalVariablesFlush:()=>{t.flushes++;},NormalizeDouble:(v,d)=>Number(Number(v).toFixed(d)),MathMax:Math.max,MathMin:Math.min,MathPow:Math.pow,
  IntegerToString:v=>String(v),DoubleToString:(v,d)=>Number(v).toFixed(d),MathIsValidNumber:v=>Number.isFinite(v),GetLastError:()=>4501,
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push(a.objects?{ticket:0,price_level:0,price_trade:0,lots:0,sl:0,tp:0}:0);a.length=n;return n;},
  Print:(...a)=>t.logs.push(a.join('')),Alert:(...a)=>t.alerts.push(a.join('')),
  HLineCreate:()=>true,HLineDelete:()=>true,ObjectFind:()=>-1,clrAqua:0,clrBlue:0,STYLE_DASHDOT:0,STYLE_SOLID:0,STYLE_DASH:0,
  GlobalVariableSet:(k,v)=>{t.writes.push(k);if(t.failWrites.has(k.split('_').pop())||t.failWrites.has('*'))return 0;t.gv.set(k,Number(v));return 1;},
  GlobalVariableGetRef:(k,set)=>{if(!t.gv.has(k))return false;set(t.gv.get(k));return true;},
  GlobalVariableDel:k=>t.gv.delete(k),
  PositionsTotal:()=>t.positions.length,PositionGetTicket:i=>{sel=t.positions[i];return sel?sel.ticket:0;},
  PositionSelectByTicket:tk=>{sel=t.positions.find(p=>p.ticket===tk)||null;return !!sel;},
  PositionGetInteger:k=>sel[k],PositionGetString:k=>sel[k],PositionGetDouble:k=>sel[k],
  CTrade:()=>({SetExpertMagicNumber:()=>{},PositionModify:(tk,sl,tp)=>{const p=t.positions.find(x=>x.ticket===tk);t.modifies.push({ticket:tk,from:p.sl,sl,tp});p.sl=sl;p.tp=tp;return true;}}),
  HistorySelect:(from,to)=>{history=t.deals.filter(d=>d.msc/1000>=from&&d.msc/1000<=to).map(d=>d.ticket);return true;},
  HistoryDealsTotal:()=>history.length,HistoryDealGetTicket:i=>history[i]??0,
  HistoryDealGetInteger:(d,k)=>t.deals.find(x=>x.ticket===d)[k],HistoryDealGetDouble:(d,k)=>t.deals.find(x=>x.ticket===d)[k],
  HistoryDealGetString:(d,k)=>t.deals.find(x=>x.ticket===d)[k],
  // EnforceSequenceMLPS: the sequence's P/L (realized + open) is modelled; a breach closes the basket.
  GOAT_ATR_UNAVAILABLE:Number.MAX_VALUE,Sequence_MLPS_Hard_Close:true,Risk:500,g_PerformanceProfileTester:false,GoatPerformanceRecord:()=>{},g_PerfMLPSUS:0,g_PerfMLPSCalls:0,
  OpenPL:0,CurrentSequencePL:()=>c.SequenceRealizedPL+c.OpenPL,CloseSequencePositions:why=>{t.closes.push(why);},
  // B49b (PR-0): the lot arrays, the per-side refusal log flags (an MQL global: zero-initialized), the solver's math.
  Distances:[],LotsRaw:[],LotsNorm:[],LotsCum:[],StartLots:0,PeakLots:0,PeakCumLots:0,ScaleFactor:0,
  g_goat_start_distances_logged:[false,false],ArrayInitialize:(a,v)=>{a.fill(v);},MathFloor:Math.floor,MathAbs:Math.abs,DBL_MAX:Number.MAX_VALUE,
  Fix_ClosePath:0,GoatFix_Off:0,GoatFix_On:1,   // B49b PR-3 (F3): UpdateLockTPSL's monotonic SL (section 16)
 };
 vm.createContext(c);
 vm.runInContext(METHODS.map(([n,a,s])=>fn(n,a,bodyOf(main,s))).join(''),c);
 c.PersistReset();
 return c;
}
const key=(field,dir='B',magic=M)=>'GOAT_SQ_'+magic+'_'+SYM+'_'+dir+'_'+field;
// A sequence's first real level, as Add_Level leaves it (sizes frozen, Level_Count 1, the hook's PersistStart), and
// each later real level (the hook's PersistLevels).
function startSequence(s,t,ticket,sizes=[0.0012,0.0008,0,0.0030,0.0004]){
 [s.Size_Grid,s.Size_Lock,s.Size_TP,s.Size_SL,s.Size_TSL]=sizes;s.Active=s.Traded=true;s.Level_Count=s.Trades_Count=1;s.PersistStart(ticket);
}
const addLevel=s=>{s.Level_Count++;s.Trades_Count++;s.PersistLevels();};

// 1. The record: written at the first level (T last, any earlier record deleted first), its level count with each
//    later level, the realized P/L and level count at most every 5 s, the whole record from memory once per UTC day,
//    every write flushed to disk, deleted at the end.
{const t=terminal({positions:[pos(1001,{msc:T0})]}),s=sequence(t);
 t.gv.set(key('T'),T0-999);   // a stale record from an older sequence on the same key
 startSequence(s,t,1001);
 assert.deepEqual(t.writes,['TK','G','L','TP','SL','TS','N','C','R','T'].map(f=>key(f)),'the start record, T written last');
 assert.equal(t.gv.get(key('T')),T0,'the stale record went first');assert.equal(t.gv.get(key('TK')),1001);assert.equal(t.gv.get(key('TS')),0.0004);
 assert.equal(t.gv.get(key('N')),1);assert.equal(t.flushes,2,'the deletion and the record, each flushed to gvariables.dat');
 addLevel(s);addLevel(s);assert.equal(t.gv.get(key('N')),3,'each later level updates the level count');assert.equal(t.gv.get(key('C')),3,'and the trade count');assert.equal(t.flushes,4);
 t.writes.length=0;s.SequenceRealizedPL=-12.5;
 s.PersistFlush();assert.deepEqual(t.writes,[],'within 5 s of the last write nothing is written');
 for(let i=0;i<10;i++){s.SequenceRealizedPL-=1;t.now+=400;s.PersistFlush();}
 assert.deepEqual(t.writes,[key('R'),key('N'),key('C')],'ten changes inside 5 s: one write');assert.equal(t.flushes,5);
 t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.writes.length,3,'unchanged: no write');
 s.SequenceRealizedPL-=1;t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.flushes,6);    // a write, now
 // The next UTC day: the whole record from memory (every field's 4-week expiry), inside the same rate bound.
 t.writes.length=0;t.gmt+=86400;s.PersistFlush();assert.deepEqual(t.writes,[],'within 5 s of that write: not yet');
 t.gv.set(key('N'),1);   // a stale field (a lost write): the daily rewrite repairs it from memory (Claude-Mac P3)
 t.now+=FLUSH_MS;s.PersistFlush();
 assert.deepEqual(t.writes,['TK','G','L','TP','SL','TS','N','C','R','T'].map(f=>key(f)),'the whole record once that day');
 assert.equal(t.gv.get(key('N')),3,'from memory');assert.equal(t.gv.get(key('T')),T0);assert.equal(t.flushes,7);
 t.writes.length=0;t.now+=FLUSH_MS;s.PersistFlush();assert.deepEqual(t.writes,[],'not again that day');
 // A level the Add_Level hook does not see (the CumPartial unwind branch appends a virtual level row) reaches N at the
 // next flush, with the realized P/L unchanged.
 s.Level_Count++;s.Trades_Count++;t.writes.length=0;t.now+=FLUSH_MS;s.PersistFlush();
 assert.deepEqual(t.writes,[key('R'),key('N'),key('C')]);assert.equal(t.gv.get(key('N')),4);assert.equal(t.gv.get(key('C')),4);
 s.SequenceRealizedPL=-30;s.PersistFlush(true);assert.equal(t.gv.get(key('R')),-30,'OnDeinit forces the flush');
 s.PersistEnd();assert.equal(t.gv.size,0,'the end deletes the record');assert.equal(t.flushes,10,'and flushes the deletion');
 ok();}

// A basket mid-way (CumPartial: level 1 partly harvested at a loss) whose terminal stops; the stops are at the levels'
// computed SL or tighter (a trailed one), as the EA left them.
const SIZES=[0.0012,0.0008,0,0.0030,0.0004];
function midBasket({sl=[0,0,0],tp=[0,0,0],ledger=1,sizes=SIZES}={}){
 const t=terminal({ledger,positions:[pos(1002,{msc:T0+60000,open:1.0985,volume:0.2,sl:sl[1],tp:tp[1]}),pos(1001,{msc:T0,open:1.1,volume:0.05,sl:sl[0],tp:tp[0]}),
  pos(1003,{msc:T0+120000,open:1.0970,volume:0.3,sl:sl[2],tp:tp[2]})]});
 for(const [p,msc] of [[1001,T0],[1002,T0+60000],[1003,T0+120000]]) deal(t,{entry:0,type:0,magic:M,position:p,msc,commission:-3.5});
 deal(t,{entry:1,type:1,magic:M,position:1001,msc:T0+150000,profit:-40,commission:-1});   // the harvest
 const before=sequence(t);startSequence(before,t,1001,sizes);addLevel(before);addLevel(before);
 before.SequenceRealizedPL=-51.5;t.now+=FLUSH_MS;before.PersistFlush();   // the join ledger: 3 entry commissions + the harvest
 t.modifies.length=0;t.alerts.length=0;t.logs.length=0;
 return t;
}
// The levels' computed SL (Level_Entry - Size_SL): what UpdateLockTPSL writes on a basket that never trailed.
const ENTRY=(1.1*0.05+1.0985*0.2+1.0970*0.3)/0.55, COMPUTED=Number((ENTRY-0.0030).toFixed(5));

// 2. A restart mid-basket: matched, everything back, nothing loosened.
{const t=midBasket({sl:[COMPUTED,COMPUTED,COMPUTED]}),s=sequence(t);   // a fresh SEQUENCE, the same positions, deals and GVs
 assert.equal(s.AdoptOpenPositions(),true);
 assert.deepEqual([s.Active,s.Traded,s.Adopted,s.AdoptMatched,s.AdoptSizes],[true,true,true,true,true]);
 assert.equal(s.SequenceRealizedPL,-51.5,'MLPS sees realized + open (recounted from history under PositionJoin: the same here)');
 assert.deepEqual(s.TradeLevels.map(l=>l.ticket),[1001,1002,1003],'levels by open time');
 assert.deepEqual([s.Level_Count,s.Trades_Count,s.Level_Last],[3,3,1.097]);
 assert.deepEqual([s.Size_Grid,s.Size_Lock,s.Size_TP,s.Size_SL,s.Size_TSL],SIZES,'the frozen sizes');
 assert.equal(s.Level_Lock,Number((ENTRY+0.0008).toFixed(5)),'Lock recomputed from the frozen sizes');
 assert.deepEqual(t.modifies,[],'the stops already at the computed SL: nothing written');
 assert.deepEqual(s.LedgerPositions,[1001,1002,1003],'the positions join F2\'s ledger');
 assert.equal(t.alerts.length,1);assert.match(t.alerts[0],/adopted 3 open position\(s\) of magic 1843920117 as manage-only \(adds frozen\)\. Record matched: MLPS sees realized -51\.50 \+ open P\/L\. Lock\/TP\/SL and trailing resume/);
 assert.equal(s.ManageOnlyFrozen(4),true);assert.equal(s.ManageOnlyFrozen(4),true);
 assert.deepEqual(t.logs.filter(l=>l.startsWith('GOAT restart: add_frozen=')),['GOAT restart: add_frozen=manage_only side=BUY magic=1843920117 symbol=EURUSD level=4 closes_stops_mlps=continue']);
 assert.equal(t.gv.get(key('T')),T0,'the record carries on');
 // The first level was closed by a harvest: every live position opened at or after the start still matches.
 const t2=midBasket();t2.positions=t2.positions.filter(p=>p.ticket!==1001);const s2=sequence(t2);s2.AdoptOpenPositions();
 assert.deepEqual([s2.AdoptMatched,s2.Level_Count],[true,2]);
 // A start time stamped late (PositionSelectByTicket failed at the start, so TimeCurrent stood in): the oldest live
 // position predates the record, and its first ticket, still live, is what matches.
 const t3=midBasket();t3.gv.set(key('T'),T0+5000);const s3=sequence(t3);s3.AdoptOpenPositions();assert.equal(s3.AdoptMatched,true);
 // Claude-Mac 6428447507: the start-time rule also needs the live count within the record's level count.
 const t4=midBasket();t4.gv.set(key('N'),2);t4.gv.set(key('TK'),999);const s4=sequence(t4);s4.AdoptOpenPositions();
 assert.deepEqual([s4.AdoptMatched,s4.SequenceRealizedPL],[false,0],'3 live positions, a record of 2 levels, its ticket gone');
 const t5=midBasket();t5.gv.set(key('N'),2);const s5=sequence(t5);s5.AdoptOpenPositions();
 assert.equal(s5.AdoptMatched,true,'its first ticket still live: the ticket rule matches');
 ok();}

// 3. No matching record: open P/L only, broker SL/TP untouched, the stale record replaced by this basket's.
{const t=midBasket({sl:[1.08,1.08,1.08]});t.gv.set(key('T'),T0+600000);t.gv.set(key('TK'),999);   // a later sequence's record, ticket gone
 const s=sequence(t);s.AdoptOpenPositions();
 assert.deepEqual([s.Adopted,s.AdoptMatched,s.AdoptSizes,s.SequenceRealizedPL],[true,false,false,0]);
 s.UpdateLockTPSL(3);assert.deepEqual(t.modifies,[],'no Lock/TP/SL write from guessed sizes, even when asked');
 assert.match(t.alerts[0],/No matching record: MLPS sees open P\/L only\. The EA leaves this basket's broker SL\/TP untouched\./);
 assert.equal(t.gv.get(key('T')),T0,'a new record starts at the oldest live position');assert.equal(t.gv.get(key('TK')),1001);
 assert.equal(t.gv.get(key('G')),1234.5,'its sizes are unknown (the sentinel)');
 // The stale record is deleted before the new one is written: if the new start time cannot be written, no stale T
 // is left to pair with the new fields at the next restart (Claude-Mac P2-3: no mixed record).
 const f=midBasket();f.gv.set(key('T'),T0+600000);f.gv.set(key('TK'),999);f.failWrites.add('T');
 const fs1=sequence(f);fs1.AdoptOpenPositions();
 assert.equal(f.gv.has(key('T')),false,'no stale start time survives');assert.equal(fs1.PersistFailed,true,'adds frozen');
 // The next restart matches that record, but its sizes stay unknown: the stops stay untouched.
 const s2=sequence(t);s2.AdoptOpenPositions();s2.UpdateLockTPSL(3);assert.deepEqual([s2.AdoptMatched,s2.AdoptSizes,t.modifies.length],[true,false,0]);
 // No record at all, or an incomplete one (no T, the field written last): the same as unmatched.
 for(const drop of [['T','TK','G','L','TP','SL','TS','N','C','R'],['T']]){
  const u=midBasket();for(const fl of drop)u.gv.delete(key(fl));const x=sequence(u);x.AdoptOpenPositions();
  assert.deepEqual([x.Adopted,x.AdoptMatched,x.SequenceRealizedPL],[true,false,0],'dropped '+drop.join(','));
 }
 ok();}

// 4. Only this chart's basket on this side; nothing in the tester, a batch, the dashboard, a virtual sequence.
{const t=terminal({positions:[pos(2001,{type:1}),pos(3001,{magic:Y}),pos(4001,{symbol:'GBPUSD'})]});
 const buy=sequence(t);assert.equal(buy.AdoptOpenPositions(),false,'no buy position of MAGIC1 on EURUSD');assert.equal(buy.Active,false);
 const sell=sequence(t,{dir:1});assert.equal(sell.AdoptOpenPositions(),true);assert.deepEqual(sell.TradeLevels.map(l=>l.ticket),[2001]);
 for(const opts of [{tester:true},{mode:6},{mode:7}]){
  const x=terminal({positions:[pos(1001)],...opts}),s=sequence(x);
  assert.equal(s.AdoptOpenPositions(),false,JSON.stringify(opts));startSequence(s,x,1001);assert.equal(x.writes.length,0,'no record '+JSON.stringify(opts));
 }
 const v=terminal({positions:[pos(1001)]}),vs=sequence(v,{virtual:true});assert.equal(vs.AdoptOpenPositions(),false);
 // A running sequence (a live re-init keeps EA globals) is never adopted over.
 const r=terminal({positions:[pos(1001)]}),rs=sequence(r);rs.Active=true;assert.equal(rs.AdoptOpenPositions(),false);
 ok();}

// 5. A failed record write freezes adds (alerted once) until everything pending is written; a failed level-count
//    write is retried before adds resume (Codex GOAT-EA#266).
{const t=terminal({positions:[pos(1001)]});t.failWrites.add('*');const s=sequence(t);
 startSequence(s,t,1001);
 assert.equal(s.PersistFailed,true);assert.equal(t.alerts.length,1);assert.match(t.alerts[0],/restart record not written .*Adds are frozen until a write succeeds/);
 assert.equal(s.ManageOnlyFrozen(2),true);assert.match(t.logs.at(-1),/add_frozen=record_unwritten/);
 t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.alerts.length,1,'alerted once');assert.equal(s.PersistFailed,true);
 t.failWrites.clear();t.now+=FLUSH_MS;s.PersistFlush();
 assert.equal(s.PersistFailed,false,'the retried start succeeded');assert.equal(t.gv.get(key('T')),T0);
 assert.equal(s.ManageOnlyFrozen(2),false,'adds resume');
 // A later level whose count cannot be written: frozen; the timer rewrites the whole record (N included) before resuming.
 t.failWrites.add('N');addLevel(s);assert.equal(t.gv.get(key('N')),1);assert.equal(s.ManageOnlyFrozen(3),true);
 t.now+=FLUSH_MS;s.PersistFlush();assert.equal(s.ManageOnlyFrozen(3),true,'still failing: still frozen');
 t.failWrites.clear();t.now+=FLUSH_MS;s.PersistFlush();
 assert.deepEqual([t.gv.get(key('N')),s.PersistFailed,s.ManageOnlyFrozen(3)],[2,false,false],'N repaired before adds resume');
 // A later realized write fails: frozen again, then resumes.
 t.failWrites.add('R');s.SequenceRealizedPL=-5;t.now+=FLUSH_MS;s.PersistFlush();assert.equal(s.ManageOnlyFrozen(3),true);
 t.failWrites.clear();t.now+=FLUSH_MS;s.PersistFlush();assert.equal(s.ManageOnlyFrozen(3),false);assert.equal(t.gv.get(key('R')),-5);
 ok();}

// 6. Where it sits in the source.
{const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 const lines=ADD.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l)).map(l=>l.trim());
 assert.ok(lines[1].startsWith('if(!Virtual && GoatCidGuardAddFrozen('),'B47\'s freeze');
 assert.equal(lines[2],'if(!Virtual && ManageOnlyFrozen(Level_Count+1)) return false; // B49a (F1-lite): an adopted basket, or a failed restart record, freezes adds');
 assert.ok(ADD.includes('        if(LastOrderTicket>0) {if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket); else PersistLevels();} // B49a (F1-lite): the first real level starts the restart record, each later one updates its level count'));
 assert.equal(firstStatement(bodyOf(main,'   void UpdateLockTPSL(int count=0)')),UPDATE_GUARD);
 assert.equal(firstStatement(bodyOf(main,'   void TrailingStoploss()')),UPDATE_GUARD);
 assert.ok(main.includes('                                  Seq_Buy.Init(OP_BUY,false);        Seq_Sell.Init(OP_SELL,false);\n     GoatLedgerOwnerReset();'
  +' // B49a (F2): owners are cached per MAGIC1 (a live re-init may restore another)\n     Seq_Buy.AdoptOpenPositions(); Seq_Sell.AdoptOpenPositions();'),
  'OnInit adopts right after the sequences\' Init (and F2\'s owner-cache reset)');
 assert.equal((main.match(/\.AdoptOpenPositions\(\)/g)||[]).length,2,'adoption: OnInit only');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('   GoatCidGuardHeartbeat(); // B47: the claim heartbeat (every GOAT_CID_CLAIM_HEARTBEAT_MS; live trading charts only)\n   Seq_Buy.PersistFlush(); Seq_Sell.PersistFlush();'),'the timer flushes');
 assert.ok(bodyOf(main,'void OnDeinit(const int reason)').includes('   Seq_Buy.PersistFlush(true); Seq_Sell.PersistFlush(true);'),'OnDeinit forces it');
 const END=bodyOf(main,'   void End_Sequence(string desc)');
 assert.ok(END.indexOf('PersistEnd(); PersistReset();')>END.indexOf('GoatTraceEnd(TraceSequenceID,desc);')&&END.indexOf('PersistEnd(); PersistReset();')<END.indexOf('Active=Traded=Trailing=Retrace_Triggered=false;'),'the end deletes the record while the sequence is still known');
 // Alert is a one-argument macro (#define Alert(goat_alert_text) GoatDeployNotice(...)): a second argument is a
 // compile warning and the rest of the text is lost, so every Alert in the F1-lite block passes one string.
 assert.match(main,/^#define Alert\(goat_alert_text\) GoatDeployNotice\(goat_alert_text\)$/m);
 const block=main.slice(main.indexOf('// B49a:begin f1-lite'),main.indexOf('// B49a:end f1-lite'));
 for(const m of block.matchAll(/\bAlert\(/g)){
  let depth=0,commas=0,i=m.index+6;
  for(;i<block.length;i++){const ch=block[i];if(ch==='"'){i=block.indexOf('"',i+1);continue;}
   if(ch==='(')depth++;else if(ch===')'){if(depth===0)break;depth--;}else if(ch===','&&depth===0)commas++;}
  assert.equal(commas,0,'one-argument Alert: '+block.slice(m.index,m.index+60));
 }
 // MLPS needs Active, Traded and a real sequence, which adoption provides.
 assert.ok(bodyOf(main,'   bool EnforceSequenceMLPS(const string context)').includes('if(Virtual || !Active || !Traded)'));
 ok();}

// 7. Claude-Mac GOAT-EA#266 P1-a: an adopted basket is active from OnInit, and GetSize refreshed ATR_Buf only while no
//    sequence was active, so in ATR mode its next read was out of range and MT5 removed the EA (worse than B47). Now an
//    empty ATR_Buf is refilled on any call. B47's GetSize runs on the same state and crashes; MT5's out-of-range read is
//    modelled by an array that throws.
function getSize(text,{active=true,ready=true,context=null}={}){
 const buf=new Proxy([],{get(a,p){if(typeof p==='string'&&/^\d+$/.test(p)&&Number(p)>=a.length)throw new Error('array out of range');return Reflect.get(a,p);}});
 const g=Object.assign(context||{},{GRID:121,GRID_MIN:122,GRID_MAX:123,GRID_VALID:124,LOCK:125,TSL:126,OP_SL:1,OP_TP:2,
  Grid_Size:-1.5,LP_Size_:-0.8,SL_Pips_:0,TP_Pips_:0,TSL_Size_:-0.4,Grid_Min_:-0.5,Grid_Max_:-6,Grid_Exponent:1.2,Grid_Factor:1.0,Max_Seq_Trades:10,
  bid:1.0950,ask:1.0951,LastATRBid:0,LastATRAsk:0,Seq_Buy:{Active:active},Seq_Sell:{Active:false},ATR_MA_handle:7,ATR_Buf:buf,ATR_Pips:0,
  ready,copies:0,sizeCalls:0,logs:[],
  CopyBuffer:(h,b,shift,n,arr)=>{g.copies++;if(!g.ready)return -1;arr.length=0;arr.push(0.0010);return 1;},ArraySize:a=>a.length,
  NormalizeDouble:(v,d)=>Number(Number(v).toFixed(d)),_Point:0.00001,Point:()=>0.00001,FastSpeed_Flag:true,SetEdit:()=>{},PanelDialog:{},
  MathPow:Math.pow,MathMax:Math.max,MathMin:Math.min,
  // B49a's atr-ready block (B47 has none): GOAT_ATR_UNAVAILABLE is MQL's EMPTY_VALUE (DBL_MAX).
  GOAT_ATR_UNAVAILABLE:Number.MAX_VALUE,g_goat_atr_unavailable_logged:false,_Symbol:SYM,GetLastError:()=>4806,IntegerToString:v=>String(v),
  Print:(...a)=>g.logs.push(a.join(''))});
 vm.createContext(g);
 const atr=text.includes('// B49a:begin atr-ready')?fn('GoatSizeNeedsAtr',['type'],bodyOf(text,'bool GoatSizeNeedsAtr(const int type)'))
  +fn('GoatAtrUnavailable',['type'],bodyOf(text,'double GoatAtrUnavailable(const int type)')):'';
 vm.runInContext(atr+fn('GetSizeBody',['type','level_count=0','grid_size=0'],bodyOf(text,'double GetSize(int type,int level_count=0,double grid_size=0)'))
  +'function GetSize(type,level_count=0,grid_size=0){sizeCalls++;return GetSizeBody(type,level_count,grid_size);}\n',g);
 return g;
}
{const tree=getSize(main),b47=getSize(mainB47);
 assert.throws(()=>b47.GetSize(124,3,0.0015),/array out of range/,'B47: the GRID_VALID compare after adoption crashes');
 assert.throws(()=>b47.GetSize(121),/array out of range/,'B47: so does the opposite side\'s start');
 const valid=tree.GetSize(124,3,0.0015);assert.ok(Number.isFinite(valid)&&valid>0,'B49a: the buffer is refilled');
 assert.equal(tree.GetSize(121),0.0015,'GRID = 1.5 x ATR');assert.equal(tree.ATR_Buf.length,1);
 // Unchanged while a sequence is active and the buffer is full (the frozen-ATR rule of B47).
 tree.ATR_Buf[0]=0.0020;tree.bid=1.0960;assert.equal(tree.GetSize(121),0.003,'no refresh over a full buffer while active');
 assert.match(bodyOf(main,'double GetSize(int type,int level_count=0,double grid_size=0)'),/\|\| ArraySize\(ATR_Buf\)==0\) \/\/ B49a \(F1-lite\)/);
 // Claude-Mac's re-check: the indicator not ready yet (CopyBuffer fails, as on OnInit's own first tick after a restart).
 // B47 indexes the empty array (MT5 removes the EA). B49a never does: every ATR-mode size answers the sentinel
 // (EMPTY_VALUE), logged once until the buffer fills; a pips-mode size is unaffected.
 assert.throws(()=>getSize(mainB47,{ready:false}).GetSize(121),/array out of range/,'B47 crashes');
 const cold=getSize(main,{ready:false});
 for(const type of [121,122,123,125,126]) assert.equal(cold.GetSize(type),Number.MAX_VALUE,'ATR-mode size '+type+': the sentinel');
 assert.equal(cold.GetSize(124,3,0.0015),Number.MAX_VALUE,'GRID_VALID (its min and max read ATR)');
 assert.equal(cold.GetSize(1),0,'SL in pips mode (0): read without ATR, unchanged');
 assert.equal(cold.ATR_Buf.length,0);assert.ok(cold.copies>0,'each call tried CopyBuffer');
 assert.deepEqual(cold.logs,['GOAT sizes: atr_unavailable type=121 symbol=EURUSD err=4806 (the ATR indicator is not ready: no add and no start on an ATR size until it is; closes, stops and MLPS continue)'],'logged once');
 // A grid compare against the sentinel never adds (buy: ask < last - size; sell: bid > last + size).
 assert.equal(1.0951<1.1-Number.MAX_VALUE,false);assert.equal(1.2>1.1+Number.MAX_VALUE,false);
 // A frozen base grid with pips min/max needs no ATR: a real distance, even with the buffer empty.
 const mixed=getSize(main,{ready:false});mixed.Grid_Min_=5;mixed.Grid_Max_=60;
 const d=mixed.GetSize(124,3,0.0015);assert.ok(d>=0.0005&&d<=0.006,'clamped to the pips min/max: '+d);assert.deepEqual(mixed.logs,[]);
 // The indicator ready: the next call fills the buffer, and a later failure logs again.
 cold.ready=true;assert.equal(cold.GetSize(121),0.0015);assert.equal(cold.g_goat_atr_unavailable_logged,false,'re-armed');
 ok();}

// 8. Claude-Mac GOAT-EA#266 P1-b (Ops' case D): a trailed SL survives a restart. The matched restore recomputes
//    Lock/TP/SL, and for an adopted basket each position keeps the tighter of its broker SL and the computed one; a
//    looser broker SL is tightened to the computed level, never the other way. The trailing level starts there.
{const TRAILED=1.0990;
 const t=midBasket({sl:[TRAILED,TRAILED,TRAILED]}),s=sequence(t);s.AdoptOpenPositions();
 assert.ok(COMPUTED<TRAILED,'the trailed SL is above the computed one (a buy)');
 assert.deepEqual(t.modifies,[],'case D: the trailed SL is unchanged');assert.deepEqual(t.positions.map(p=>p.sl),[TRAILED,TRAILED,TRAILED]);
 assert.equal(s.Level_TSL,TRAILED,'the trailing level starts at the tightest broker SL');
 const loose=midBasket({sl:[1.0800,COMPUTED,1.0990]}),l=sequence(loose);l.AdoptOpenPositions();
 assert.deepEqual(loose.modifies.map(m=>[m.ticket,m.from,m.sl]),[[1001,1.08,COMPUTED]],'only a looser SL moves, and only tighter');
 assert.deepEqual(loose.positions.map(p=>[p.ticket,p.sl]).sort(),[[1001,COMPUTED],[1002,COMPUTED],[1003,1.099]]);
 assert.equal(l.Level_TSL,1.099);
 // A sell keeps the lower of the two.
 const sellT=terminal({positions:[pos(2001,{type:1,open:1.1,sl:1.0960,msc:T0})]});deal(sellT,{entry:0,type:1,magic:M,position:2001,msc:T0,commission:-3.5});
 const sb=sequence(sellT,{dir:1});startSequence(sb,sellT,2001,SIZES);sellT.modifies.length=0;
 const sa=sequence(sellT,{dir:1});sa.AdoptOpenPositions();assert.deepEqual(sellT.modifies,[],'a trailed sell SL below the computed one stays');
 assert.equal(sa.Level_TSL,1.096);
 assert.ok(bodyOf(main,'   void UpdateLockTPSL(int count=0)').includes('       if(Adopted) Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);'));
 ok();}

// 9. Claude-Mac GOAT-EA#266 P2-1: the transaction path's position count starts at the adopted basket's, so a broker
//    close that empties the side ends the sequence instead of leaving a manage-only zombie.
{const t=midBasket();const s=sequence(t);s.AdoptOpenPositions();assert.deepEqual([t.counts.buy,t.counts.sell],[3,0]);
 const sell=terminal({positions:[pos(2001,{type:1}),pos(2002,{type:1,msc:T0+1})]});sequence(sell,{dir:1}).AdoptOpenPositions();assert.equal(sell.counts.sell,2);
 const BODY=bodyOf(main,'void GoatTradeTransactionBody(');
 assert.ok(BODY.includes('if(Seq_Buy.Active && LastTradeCountBuy!=TradeCount && TradeCount==0 && Seq_Buy.Traded)'),'B47\'s end rule, which needs a non-zero last count');
 ok();}

// 10. Claude-Mac GOAT-EA#266 P2-2: under PositionJoin a matched basket's realized P/L is recounted from history, so a
//     close made while the EA was down (or after its last flush) counts; fees included. Legacy keeps the record's R.
{const down=t=>{t.positions.push(pos(1004,{msc:T0+130000,open:1.0960,volume:0.3}));
  deal(t,{entry:0,type:0,magic:M,position:1004,msc:T0+130000,commission:-3.5,fee:-0.25});
  t.positions=t.positions.filter(p=>p.ticket!==1004);                                   // a broker stop closed it while down
  deal(t,{entry:1,type:1,magic:M,position:1004,msc:T0+170000,profit:-30,commission:-1,fee:-0.25});};
 const t=midBasket();t.gv.set(key('N'),4);down(t);const s=sequence(t);s.AdoptOpenPositions();
 assert.equal(s.SequenceRealizedPL,-51.5-3.5-0.25-31-0.25,'the record\'s -51.5 plus the close made while down, fees included');
 assert.ok(s.LedgerDeals.length>=6,'every counted deal is booked, so it is never counted twice');
 const legacy=midBasket({ledger:0});legacy.gv.set(key('N'),4);down(legacy);const l=sequence(legacy);l.AdoptOpenPositions();
 assert.equal(l.SequenceRealizedPL,-51.5,'Legacy: the record\'s R (the B47 ledger never booked such a close)');
 // A foreign position (another magic) and the opposite side never count.
 const f=midBasket();deal(f,{entry:0,type:0,magic:Y,position:9001,msc:T0+1000,commission:-9});deal(f,{entry:1,type:1,magic:0,position:9001,msc:T0+2000,profit:-99});
 deal(f,{entry:0,type:1,magic:M,position:9002,msc:T0+1000,commission:-9});deal(f,{entry:1,type:0,magic:M,position:9002,msc:T0+2000,profit:-99});
 const fs1=sequence(f);fs1.AdoptOpenPositions();assert.equal(fs1.SequenceRealizedPL,-51.5);
 ok();}

// 11. Claude-Mac GOAT-EA#266 P2-3: a start that fails midway never leaves a mix of two records (the older one is
//     deleted first), so a later restart reads it as incomplete.
{const t=terminal({positions:[pos(1001,{msc:T0})]});
 for(const f of ['T','TK','G','L','TP','SL','TS','N','C','R'])t.gv.set(key(f),f==='T'?T0-5000:f==='TK'?777:1);
 t.failWrites.add('SL');const s=sequence(t);startSequence(s,t,1001);
 assert.equal(t.gv.has(key('T')),false,'the older record\'s T is gone');assert.equal(t.gv.get(key('TK')),1001,'the new fields so far');
 assert.equal(t.gv.has(key('N')),false,'nothing after the failed field');
 const x=sequence(t);x.AdoptOpenPositions();assert.equal(x.AdoptMatched,false,'incomplete: unmatched');
 ok();}

// 12. Claude-Mac's re-check of 1c8cc21 (P1): OnInit's own OnTick runs right after adoption, before the ATR indicator is
//     ready (CopyBuffer fails). OnTick's production MLPS and grid-check segment runs here over the adopted basket (the
//     real SEQUENCE methods, GetSize with CopyBuffer failing): no out-of-range read, the adopted side never reaches
//     GetSize, an active non-adopted side refuses its add against the sentinel, and MLPS still fires at -Risk on that
//     same tick. A start whose ATR sizes could not be read is refused and recomputed next time.
const TICK_START='   bool buyMlpsExit=false,sellMlpsExit=false;\n',TICK_END='\n//-------------------------------------------------------------------------\n   return;\n  }\n';
function firstTick(text,buy,sell,{ready=false}={}){
 const a=text.indexOf(TICK_START);assert.ok(a>0&&text.indexOf(TICK_START,a+1)<0,'one MLPS and grid-check segment');
 const b=text.indexOf(TICK_END,a);assert.ok(b>a);
 const k=getSize(text,{ready,context:{}});
 Object.assign(k,{Seq_Buy:buy,Seq_Sell:sell,Seq_Buy_Virtual:{Active:false},Seq_Sell_Virtual:{Active:false},adds:[],
  GoatDirectionGuardMaintenance:()=>{},CheckSequenceNow:()=>true,Sequence_Pause_Close:false,Sequence_Pause_News:false,
  Sequence_Pause_Bias_B:false,Sequence_Pause_Bias_S:false,DashboardPortfolioPaused:false,DashboardTradeAllowed:()=>true,
  Mode_Lots_Prog:0,Lots_Prog_CumPartial:5,Lots_Prog_PeakSmart:6,Partial_Profit_Factor:0,Peak_Smart_Release_PC:0,
  RSI_Mode:0,RSI_Disabled:0,RSI_Sig:-1,OP_BUY:0,OP_SELL:1,Trades_Skipped_News:0,Trades_Skipped_Bias_B:0,Trades_Skipped_Bias_S:0,
  LastBuyTradeSignal:true,LastSellTradeSignal:true,bid:1.2000,ask:1.0000});
 for(const s of [buy,sell]) if(s.Add_Level===undefined) s.Add_Level=p=>{k.adds.push([s.dir,p]);return true;};
 vm.runInContext('function Tick(){'+js(text.slice(a,b))+'}',k);
 return k;
}
{const t=midBasket(),s=sequence(t);s.AdoptOpenPositions();s.Add_Level=p=>{throw new Error('an adopted basket was added to at '+p);};
 // An unrelated active sell (not adopted, frozen sizes) far beyond its grid: its compare reads the sentinel.
 const sell={dir:1,Active:true,Traded:true,Adopted:false,Level_Last:1.1,Level_Count:2,Size_Grid:0.0012,Level_Retrace:0,EnforceSequenceMLPS:()=>false};
 const k=firstTick(main,s,sell);
 k.Tick();
 assert.deepEqual(k.adds,[],'no add on either side');assert.equal(k.LastBuyTradeSignal,false);
 assert.equal(k.ATR_Buf.length,0,'the buffer is still empty (and was never indexed)');
 assert.equal(k.sizeCalls>0,true,'the non-adopted sell reached GetSize');assert.equal(k.LastSellTradeSignal,false,'and refused its add');
 assert.equal(k.logs.length,1,'atr_unavailable logged once');assert.deepEqual(t.closes,[],'P/L above -Risk: nothing closed');
 // The adopted side never reaches GetSize: with the sell flat, no size is read at all on this tick.
 const k2=firstTick(main,s,{dir:1,Active:false});k2.Tick();assert.equal(k2.sizeCalls,0,'the adopted buy skips the grid check');
 const st=terminal({positions:[pos(2001,{type:1,open:1.1})]}),ss=sequence(st,{dir:1});ss.AdoptOpenPositions();
 ss.Add_Level=p=>{throw new Error('an adopted sell was added to at '+p);};
 const k4=firstTick(main,{dir:0,Active:false},ss);k4.Tick();
 assert.deepEqual([k4.sizeCalls,k4.LastSellTradeSignal],[0,false],'the adopted sell skips it too');
 // MLPS on that same first tick: realized -51.5 plus open -450 breaches -Risk (500), and the basket closes.
 s.OpenPL=-450;const k3=firstTick(main,s,{dir:1,Active:false});k3.Tick();
 assert.deepEqual(t.closes,['Sequence Exit: MLPS breached']);assert.equal(k3.LastBuyTradeSignal,false);
 // B47's segment over the same adopted state reaches GetSize, and B47's GetSize indexes the empty buffer.
 s.OpenPL=0;assert.throws(()=>firstTick(mainB47,s,{dir:1,Active:false}).Tick(),/array out of range/,'B47 crashes here');
 // A start whose ATR sizes could not be read: refused, and the unknown sizes go back to the sentinel 1234.5.
 const f=sequence(terminal());Object.assign(f,{Size_Grid:Number.MAX_VALUE,Size_Lock:Number.MAX_VALUE,Size_TP:0,Size_SL:0.003,Size_TSL:Number.MAX_VALUE});
 assert.equal(f.SizesUnavailable(),true);assert.deepEqual([f.Size_Grid,f.Size_Lock,f.Size_TP,f.Size_SL,f.Size_TSL],[1234.5,1234.5,0,0.003,1234.5]);
 assert.equal(f.SizesUnavailable(),false,'known sizes start');
 const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 assert.ok(ADD.includes('     if(Size_TSL ==1234.5) Size_TSL  = GetSize(TSL);\n     if(SizesUnavailable()) return false; // B49a (F1-lite)'),'refused right after the sizes are read, before any order');
 ok();}

// 13. Codex GOAT-EA#267 P2: the record keeps the trade count (C, the progression the lock flexibility reads; closed
//     levels are never subtracted from it), and a matched basket resumes with it, not with its survivor count. With
//     Lock_Profit_Flexibility < 1 the lock factor then equals the one the basket had before the restart.
{const factor=c=>1-(1-0.5)*Math.pow(c/10,2);
 const t=midBasket();assert.equal(t.gv.get(key('C')),3,'three levels traded');
 t.positions=t.positions.filter(p=>p.ticket!==1001);   // level 1 closed before the restart: two survivors
 const s=sequence(t);s.Lock_Profit_Flexibility=0.5;s.AdoptOpenPositions();
 assert.deepEqual([s.AdoptMatched,s.Level_Count,s.Trades_Count],[true,2,3],'the progression count is restored');
 const entry=(1.0985*0.2+1.0970*0.3)/0.5;
 assert.equal(s.Level_Lock,Number((entry+0.0008*factor(3)).toFixed(5)),'the lock uses the 3-level factor');
 assert.notEqual(Number((entry+0.0008*factor(3)).toFixed(5)),Number((entry+0.0008*factor(2)).toFixed(5)),'and the survivor count would differ');
 // A record without C (or one below the live count) keeps the live count; an unmatched basket uses the live count.
 const n=midBasket();n.gv.delete(key('C'));n.positions=n.positions.filter(p=>p.ticket!==1001);
 const ns=sequence(n);ns.AdoptOpenPositions();assert.equal(ns.Trades_Count,2);
 const low=midBasket();low.gv.set(key('C'),1);const ls=sequence(low);ls.AdoptOpenPositions();assert.equal(ls.Trades_Count,3,'never below the live count');
 const u=midBasket();u.positions=u.positions.filter(p=>p.ticket!==1001);u.gv.set(key('TK'),999);u.gv.set(key('N'),1);
 const us=sequence(u);us.AdoptOpenPositions();
 assert.deepEqual([us.AdoptMatched,us.Trades_Count],[false,2],'unmatched: the live count (its record\'s C=3 is not this basket\'s)');
 // The end deletes C with the rest.
 ls.PersistEnd();assert.equal(low.gv.has(key('C')),false);
 ok();}

// 14. B49b PR-0, P-B49b-start-nonfinite-distances (Claude-Mac GOAT-EA#266 6430221100): a pips Grid_Size with an ATR
//     Grid_Min_/Grid_Max_ while the ATR indicator is not ready (CopyBuffer failing). The real GetSize answers the
//     sentinel for GRID_VALID, the real BuildDistances stores it (Distances[1] = EMPTY_VALUE, finite; later ones
//     infinite), and the real solver settles on the minimum volume. The start is refused, logged once per side, and
//     keeps no sizing; once the buffer fills the same start solves to its risk volume. The lot ladder (BuildRawLots and
//     its scaling) is modelled as standing lots L0, 2xL0, 3xL0, ...; the solver, its loss and the distances are the EA's.
const VMIN=0.01,VSTEP=0.01,VMAX=100,PER_UNIT=100000;   // EURUSD on a USD account: $1 per 0.00001 per lot
function solverSequence({dir=0,trades=4,ready=false}={}){
 const s=sequence(terminal(),{dir}),g=getSize(main,{ready,active:false});
 Object.assign(g,{Grid_Size:15,Grid_Min_:-0.5,Grid_Max_:-6});        // a 15-pip base grid clamped to 0.5-6 x ATR
 Object.assign(s,{Max_Seq_Trades:trades,GRID:121,GRID_VALID:124,GetSize:(...a)=>g.GetSize(...a),Size_Grid:0.0015,Size_SL:0.003,
  SymbolInfoDouble:(sym,k)=>({VMIN,VMAX,VSTEP})[k],SYMBOL_VOLUME_MIN:'VMIN',SYMBOL_VOLUME_MAX:'VMAX',SYMBOL_VOLUME_STEP:'VSTEP',
  NormalizedLots:v=>Math.round(v/VSTEP)*VSTEP,PriceValuePerPointPerLot:()=>PER_UNIT,GetMicrosecondCount:()=>0,g_PerfLotSolverUS:0,g_PerfLotSolverCalls:0,
  BuildRawLots:()=>{},ScaleRawLots:()=>{},BuildNormalizedLots:()=>{},
  BuildCumulativeLots:()=>{s.LotsCum.length=0;for(let i=0;i<s.Max_Seq_Trades;i++)s.LotsCum.push(s.StartLots*(i+1));}});
 s.Print=(...a)=>s.logs.push(a.join(''));s.logs=[];
 return {s,g};
}
{const {s,g}=solverSequence();
 const cold=s.SolveStartLotsByRisk(500);
 assert.equal(cold,VMIN,'the solver settles on the minimum volume: the under-sized start the row describes');
 assert.equal(s.Distances[1],Number.MAX_VALUE,'the sentinel distance');assert.equal(s.Distances[2],Infinity,'then infinite');
 assert.equal(s.StartDistancesUnavailable(),true,'refused');
 assert.deepEqual(s.logs,['GOAT sizes: start_refused reason=grid_distance_unavailable side=BUY symbol=EURUSD (RiskperSeq needs every grid distance and the ATR indicator is not ready: no order; the next start solves again)']);
 assert.deepEqual([s.Size_Grid,s.Size_SL,s.StartLots,s.Distances.length,s.LotsCum.length],[1234.5,1234.5,0,0,0],'no sizing kept (a denied candidate)');
 s.Size_Grid=0.0015;s.SolveStartLotsByRisk(500);assert.equal(s.StartDistancesUnavailable(),true);assert.equal(s.logs.length,1,'logged once per side');
 // Two trades: the only distance is the sentinel itself, which is finite; still refused.
 const two=solverSequence({trades:2}).s;two.SolveStartLotsByRisk(500);
 assert.deepEqual([two.Distances.length,Number.isFinite(two.Distances[1])],[2,true]);assert.equal(two.StartDistancesUnavailable(),true,'the finite sentinel is refused too');
 const nan=solverSequence().s;nan.Distances.push(0,0.001,NaN);assert.equal(nan.StartDistancesUnavailable(),true,'a NaN distance too');
 // The buffer fills: the same start solves to its risk volume and goes ahead; the log is re-armed.
 g.ready=true;s.Size_Grid=0.0015;const solved=s.SolveStartLotsByRisk(500);
 assert.ok(solved>VMIN*10,'solved to the risk volume: '+solved);assert.ok(s.Distances.every(Number.isFinite)&&s.Distances[1]<0.01,'real distances');
 assert.ok(Math.abs(s.EvalLossForStart(solved)-500)<500*0.05,'its planned loss is the risk');
 assert.equal(s.StartDistancesUnavailable(),false,'goes ahead');assert.equal(s.g_goat_start_distances_logged[0],false,'re-armed');
 assert.equal(s.Size_Grid,0.0015,'its sizing stays');
 // A sell logs on its own side; an active sequence (never at a start) keeps its sizing.
 const sell=solverSequence({dir:1}).s;sell.g_goat_start_distances_logged=[true,false];sell.SolveStartLotsByRisk(500);
 assert.equal(sell.StartDistancesUnavailable(),true);assert.equal(sell.logs.length,1,'the buy flag does not silence the sell');assert.match(sell.logs[0],/side=SELL/);
 const act=solverSequence().s;act.Active=act.Traded=true;act.SolveStartLotsByRisk(500);act.StartDistancesUnavailable();assert.equal(act.Size_Grid,0.0015);
 // Where it sits: right after the solver at the first level, before the ladder is built and before any order.
 const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 const GUARD='      if(Mode_Lots==RiskperSeq && StartDistancesUnavailable()) return false; // B49b: P-B49b-start-nonfinite-distances (Claude-Mac GOAT-EA#266)';
 assert.ok(ADD.includes('      else if(Mode_Lots==RiskperSeq)     Lots_Calc = StartLots = SolveStartLotsByRisk(Risk);\n'+GUARD+'\n\n      BuildRawLots(StartLots);'),'right after the solver');
 assert.ok(ADD.indexOf(GUARD)<ADD.indexOf('OpenPosition('),'before any order');
 assert.equal((main.match(/StartDistancesUnavailable\(\)/g)||[]).length,2,'defined once, called once');
 ok();}

// 15. B49b PR-0, P-B49b-adopt-rescue-tp (Claude-Mac GOAT-EA#266 6429693333): with the lock off, a bias rescue moves the
//     TP to its break-even price, which is nearer than the normal TP. After a restart the matched restore recomputes the
//     normal TP from the frozen sizes; each position keeps the nearer of its broker TP and that one, so the rescue TP
//     stays. A basket on its normal TP is unchanged; a farther broker TP comes in to the normal one.
{const LOCKOFF=[0.0012,0,0.0025,0.0030,0.0004],NORMAL=Number((ENTRY+0.0025).toFixed(5)),RESCUE=1.0990;
 assert.ok(RESCUE<NORMAL,'the rescue break-even TP is nearer (a buy)');
 const t=midBasket({sl:[COMPUTED,COMPUTED,COMPUTED],tp:[RESCUE,RESCUE,RESCUE],sizes:LOCKOFF}),s=sequence(t);s.AdoptOpenPositions();
 assert.deepEqual([s.AdoptMatched,s.AdoptSizes,s.Level_TP],[true,true,NORMAL],'matched, and the recomputed TP is the normal one');
 assert.deepEqual(t.modifies,[],'no modify loosens the rescue TP');assert.deepEqual(t.positions.map(p=>p.tp),[RESCUE,RESCUE,RESCUE]);
 const n=midBasket({sl:[COMPUTED,COMPUTED,COMPUTED],tp:[NORMAL,NORMAL,NORMAL],sizes:LOCKOFF});sequence(n).AdoptOpenPositions();
 assert.deepEqual(n.modifies,[],'a basket on its normal TP is unchanged');
 const far=midBasket({sl:[COMPUTED,COMPUTED,COMPUTED],tp:[1.1100,NORMAL,0],sizes:LOCKOFF});sequence(far).AdoptOpenPositions();
 assert.deepEqual(far.modifies.map(m=>[m.ticket,m.tp]).sort(),[[1001,NORMAL],[1003,NORMAL]],'a farther or missing broker TP comes in to the normal one');
 // A sell keeps the higher of the two.
 const sellT=terminal({positions:[pos(2001,{type:1,open:1.1,sl:1.1030,tp:1.0990,msc:T0})]});deal(sellT,{entry:0,type:1,magic:M,position:2001,msc:T0,commission:-3.5});
 const sb=sequence(sellT,{dir:1});startSequence(sb,sellT,2001,LOCKOFF);sellT.modifies.length=0;
 const sa=sequence(sellT,{dir:1});sa.AdoptOpenPositions();assert.equal(sa.Level_TP,1.0975);
 assert.deepEqual(sellT.modifies,[],'a sell rescue TP above the normal one stays');
 // Lock and TP both off: the rescue's break-even TP is the only TP the basket ever had. The frozen sizes give none (0);
 // B49a would send 0 and delete it, an adopted basket keeps it.
 const off=midBasket({sl:[COMPUTED,COMPUTED,COMPUTED],tp:[RESCUE,RESCUE,RESCUE],sizes:[0.0012,0,0,0.0030,0.0004]});sequence(off).AdoptOpenPositions();
 assert.deepEqual(off.modifies,[],'no TP from the sizes: the broker TP stays');
 assert.ok(bodyOf(main,'   void UpdateLockTPSL(int count=0)').includes('       if(Adopted) Level_TP_ = TighterTakeProfit(PositionGetDouble(POSITION_TP),Level_TP_);'));
 ok();}

// 16. B49b PR-3 (F3 D2, Fix_ClosePath): a running (not adopted) basket's UpdateLockTPSL never loosens a broker SL. B49a
//     writes the computed SL onto every position: over a trailed stop that moves it back (and with no SL size it writes
//     the level SL as it stands, 0 on a basket that never had one, deleting the trailed stop). Off is B49a.
{const TRAILED=1.0990;
 const run=fix=>{const t=midBasket({sl:[TRAILED,TRAILED,TRAILED]}),s=sequence(t);s.AdoptOpenPositions();
  s.Adopted=false;s.Fix_ClosePath=fix;t.modifies.length=0;s.UpdateLockTPSL(s.Trades_Count);return t;};
 const off=run(0);
 assert.deepEqual(off.modifies.map(m=>[m.from,m.sl]),[[TRAILED,COMPUTED],[TRAILED,COMPUTED],[TRAILED,COMPUTED]],'B49a: the trailed stop is moved back to the computed SL');
 const on=run(1);assert.deepEqual(on.modifies,[],'Fix_ClosePath: the trailed stop stays');
 // No SL size and no level SL: B49a sends SL 0 (the trailed stop is deleted); the fix keeps it.
 const zero=fix=>{const t=midBasket({sl:[TRAILED,TRAILED,TRAILED],sizes:[0.0012,0.0008,0,0,0.0004]}),s=sequence(t);s.AdoptOpenPositions();
  s.Adopted=false;s.Level_SL=0;s.Fix_ClosePath=fix;t.modifies.length=0;s.UpdateLockTPSL(s.Trades_Count);return t;};
 assert.deepEqual(zero(0).modifies.map(m=>m.sl),[0,0,0],'B49a: SL 0 deletes the trailed stop');
 assert.deepEqual(zero(1).modifies,[],'Fix_ClosePath: kept');
 // A looser broker SL still comes in to the computed one (the rule only forbids loosening).
 const t=midBasket(),s=sequence(t);s.AdoptOpenPositions();s.Adopted=false;s.Fix_ClosePath=1;
 t.positions.forEach(p=>{p.sl=1.0800;});t.modifies.length=0;s.UpdateLockTPSL(s.Trades_Count);
 assert.deepEqual(t.modifies.map(m=>m.sl),[COMPUTED,COMPUTED,COMPUTED],'tightened');
 assert.ok(bodyOf(main,'   void UpdateLockTPSL(int count=0)').includes('       if(Fix_ClosePath==GoatFix_On) Level_SL_ = TighterBiasStop(PositionGetDouble(POSITION_SL),Level_SL_);'));
 ok();}

console.log(JSON.stringify({passed,test:'restart_adopt'}));
