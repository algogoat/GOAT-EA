// B49a (F2; roadmap D1/D6/D15, WEEKEND-1031 goatai#2587 6427654059 / 6427772701): Ledger_Mode. Through B47 the
// sequence ledger (MLPS, BE, Smart Peak), the daily P/L (MaxDaily*) and the dashboard's closed P/L counted only deals
// carrying MAGIC1, and every CTrade the EA closes with carries magic 0 (GOAT_SequenceExport.mqh's own comment), so the
// EA's own closes were invisible: over 61 B43 captures, 31% of exits (net -$88.5k) never reached the ledger.
// Under Ledger_PositionJoin an exit joins its sequence by DEAL_POSITION_ID (the export trace's join), each deal is
// booked once, entry commission is booked (D15), the daily P/L and the dashboard's closed P/L use the same join, and
// the EA's CTrade closes carry MAGIC1. Ledger_Legacy (the default) must reproduce B47 exactly.
// This runs the production functions (syntax-only MQL-to-JS conversion) against a modelled deal history whose
// selection rules are MT5's: HistorySelect selects a window, HistorySelectByPosition one position's deals,
// HistoryDealSelect one deal, and a getter on a deal outside the current selection throws, so a walk that asked for
// an owner mid-walk (replacing the selection) would fail here. B47's own source (ccb0a07) runs on the same fixtures.
// Source semantics only: native MT5 history and CTrade are not exercised.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B47_SOURCE='ccb0a07';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
// test_ledger_join_mutations.cjs points GOAT_EA_MAIN at a mutated entrypoint.
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const header=clean(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
const mainB47=clean(execFileSync('git',['show',B47_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
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
 return text.slice(a,b+end.length);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
function js(text){
 return text.replace(/\/\/.*$/gm,'')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]','g'),'let $1=[]')
  .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
  .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
}
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';

// ---- the modelled account: deals, positions, and MT5's history selection ----
const M=1843920117,Y=907113355,SYM='EURUSD',DAY0=1792022400;   // this chart's magic, another chart's; 2026-10-15 00:00
const K={DEAL_ENTRY_IN:0,DEAL_ENTRY_OUT:1,DEAL_ENTRY_INOUT:2,DEAL_ENTRY_OUT_BY:3,DEAL_TYPE_BUY:0,DEAL_TYPE_SELL:1,DEAL_TYPE_BALANCE:2,
 DEAL_MAGIC:'magic',DEAL_SYMBOL:'symbol',DEAL_ENTRY:'entry',DEAL_TYPE:'type',DEAL_POSITION_ID:'position',DEAL_TIME:'time',
 DEAL_PROFIT:'profit',DEAL_COMMISSION:'commission',DEAL_SWAP:'swap',DEAL_FEE:'fee',DEAL_VOLUME:'volume',DEAL_REASON:'reason',DEAL_REASON_EXPERT:3,
 POSITION_IDENTIFIER:'identifier',OP_BUY:0,OP_SELL:1,Ledger_Legacy:0,Ledger_PositionJoin:1,TRADE_TRANSACTION_DEAL_ADD:6,
 MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3};
function account(){
 const deals=new Map(),positions=new Map(),calls={byPosition:0,window:0,dealSelect:0};
 let sel=[];
 const need=t=>{if(!sel.includes(t))throw new Error('deal '+t+' read outside the current history selection ['+sel.join(',')+']');return deals.get(t);};
 const api={
  HistorySelect:(from,to)=>{calls.window++;sel=[...deals.values()].filter(d=>d.time>=from&&d.time<=to).map(d=>d.ticket);return true;},
  HistorySelectByPosition:p=>{calls.byPosition++;sel=[...deals.values()].filter(d=>d.position===p).map(d=>d.ticket);return sel.length>0;},
  HistoryDealSelect:t=>{calls.dealSelect++;if(!deals.has(t)){sel=[];return false;}sel=[t];return true;},
  HistoryDealsTotal:()=>sel.length,HistoryDealGetTicket:i=>sel[i]??0,
  HistoryDealGetInteger:(t,k)=>need(t)[k],HistoryDealGetString:(t,k)=>need(t)[k],HistoryDealGetDouble:(t,k)=>need(t)[k],
  PositionSelectByTicket:t=>{api.__pos=positions.get(t);return !!api.__pos;},PositionGetInteger:k=>api.__pos[k],
 };
 let nextDeal=5001;
 const deal=(d)=>{const t=d.ticket??nextDeal++;deals.set(t,{ticket:t,symbol:SYM,type:0,commission:0,swap:0,fee:0,profit:0,volume:0.1,reason:3,...d,ticket:t});return t;};
 const open=(ticket,{magic=M,type=0,time=DAY0+3600,commission=-3.5,symbol=SYM}={})=>{
  positions.set(ticket,{identifier:ticket});return deal({position:ticket,entry:0,type,magic,time,commission,symbol});};
 const close=(ticket,{magic=0,profit=0,commission=-1,swap=0,time=DAY0+7200,full=true,type=1,symbol=SYM}={})=>{
  if(full)positions.delete(ticket);return deal({position:ticket,entry:1,type,magic,time,profit,commission,swap,symbol});};
 return {api,deals,positions,calls,open,close,deal};
}

// ---- the production units, converted ----
const SEQ_METHODS=[
 ['ClosedDealPL',['deal_ticket'],'   double ClosedDealPL(const ulong deal_ticket)'],
 ['AccumulateSequenceDealPL',['deal_ticket'],'   void AccumulateSequenceDealPL(const ulong deal_ticket)'],
 ['LedgerHasPosition',['position_id'],'   bool LedgerHasPosition(const ulong position_id)'],
 ['LedgerAddPosition',['position_ticket'],'   void LedgerAddPosition(const ulong position_ticket)'],
 ['LedgerBook',['deal_ticket'],'   bool LedgerBook(const ulong deal_ticket)'],
 ['AccumulateJoinedDealPL',['deal_ticket'],'   void AccumulateJoinedDealPL(const ulong deal_ticket)'],
 ['Init',['OP','v'],'   void Init(int OP,bool v)'],
 ['ResetSequenceRiskState',[],'   void ResetSequenceRiskState()'],
];
const DEFINE=(text,name)=>Number((text.match(new RegExp('^#define\\s+'+name+'\\s+(\\d+)','m'))||[])[1]);
const OWNER_CACHE=DEFINE(main,'GOAT_LEDGER_OWNER_CACHE');assert.equal(OWNER_CACHE,256);
function common(acct,mode){
 return {...K,...acct.api,_Symbol:SYM,MAGIC1:M,Ledger_Mode:mode,Max_Seq_Levels:64,
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},ArrayRemove:(a,s,n)=>{a.splice(s,n);return true;}};
}
// One SEQUENCE: its members and methods in their own context (tree or B47 source).
function sequence(acct,mode,text=main){
 const c={...common(acct,mode),SequenceRealizedPL:0,LedgerPositions:[],LedgerDeals:[],Active:false,Traded:false,BiasRescueActive:false,ended:[],
  Strat:'Trend',dir:0,Virtual:false,Desc:'',Retrace_Triggered:false,Level_Retrace:0,BiasRescueBEProtected:false,BiasRescuePositiveAdds:0,
  BiasRescueBEPrice:0,BiasRescueSLPrice:0,Level_Count:0,TradeLevels:[]};
 c.End_Sequence=d=>{c.ended.push(d);c.Active=c.Traded=false;};
 vm.createContext(c);
 const methods=text===main?SEQ_METHODS:SEQ_METHODS.filter(([n])=>n==='ClosedDealPL'||n==='AccumulateSequenceDealPL');
 vm.runInContext(methods.map(([n,a,s])=>fn(n,a,bodyOf(text,s))).join(''),c);
 return c;
}
// The chart: two sequences and the global units.
function chart(acct,mode,text=main){
 const buy=sequence(acct,mode,text),sell=sequence(acct,mode,text);
 const g={...common(acct,mode),Seq_Buy:buy,Seq_Sell:sell,g_GoatLedgerOwnerPosition:[],g_GoatLedgerOwnerMine:[],GOAT_LEDGER_OWNER_CACHE:OWNER_CACHE,
  DashboardBusDayStart:DAY0,DashboardBusWeekStart:DAY0-3*86400,DashboardBusClosedPLDaily:0,DashboardBusClosedPLWeekly:0,
  DashboardBusClosedPLTotal:0,DashboardBusClosedTradesTotal:0,
  GoatBrokerDayStart:()=>DAY0,GoatBrokerWeekStart:()=>DAY0-3*86400,TimeCurrent:()=>DAY0+86000,
  g_GoatStudioReadOnlyMonitor:false,GOATDeviceActivationOnly:()=>false,GoatDirectionGuardDeal:()=>{},
  open:{buy:0,sell:0},FindNumberOfPositions:(op)=>op===0?g.open.buy:g.open.sell,LastTradeCountBuy:0,LastTradeCountSell:0,
  MQLInfoInteger:()=>0,DashboardBusRollClosedBuckets:()=>{},dt_Back_OOS:0,dt_Fwrd_OOS:0,dt_FWD_start:0,dt_FWD_end:0,
  trd_BOOS:0,trd_FOOS:0,trd_IS:0,trd_FWD:0,
  DStartTime:DAY0,PL_Total:0,DStartLocalLoss:0};
 vm.createContext(g);
 let code=fn('DashboardBusRebuildClosedStats',[],bodyOf(text,'void DashboardBusRebuildClosedStats(void)'))
  +fn('GoatTradeTransactionBody',['trans','request','result'],bodyOf(text,'void GoatTradeTransactionBody('))
  // The daily P/L block of the per-tick status pass (MaxDaily*), run as a unit.
  +'function DailyClosedPL(){let PL_Closed=0,PL_Today=0;'
   +js(region(text,'     HistorySelect(DStartTime,TimeCurrent());','     PL_Today = PL_Total-DStartLocalLoss+PL_Closed;'))+'return PL_Closed;}\n';
 if(text===main) code+=fn('GoatLedgerPositionMine',['position_id'],bodyOf(text,'bool GoatLedgerPositionMine(const ulong position_id)'))
  +fn('GoatLedgerCollectExit',['deal','positions','profits','times'],bodyOf(text,'void GoatLedgerCollectExit(const ulong deal,ulong &positions[],double &profits[],datetime &times[])'))
  +fn('GoatLedgerJoinedExit',['deal'],bodyOf(text,'bool GoatLedgerJoinedExit(const ulong deal)'))
  +fn('GoatLedgerOwnerReset',[],bodyOf(text,'void GoatLedgerOwnerReset()'));
 vm.runInContext(code,g);
 // The level hook in SEQUENCE::Add_Level, after a real order: join its position, book its entry commission.
 const HOOK=text===main?(main.match(/^ {8}(if\(Ledger_Mode==Ledger_PositionJoin && LastOrderTicket>0\) \{LedgerAddPosition\(\(ulong\)LastOrderTicket\); AccumulateSequenceDealPL\(\(ulong\)LastDealTicket\);\})/m)||[])[1]:null;
 const level=(seq,positionTicket,dealTicket)=>{
  seq.Active=seq.Traded=true;
  if(HOOK){seq.LastOrderTicket=positionTicket;seq.LastDealTicket=dealTicket;vm.runInContext(js(HOOK),seq);}
 };
 const trans=deal=>g.GoatTradeTransactionBody({type:6,deal},{},{});
 return {g,buy,sell,level,trans};
}
const HOOK_LINE='        if(Ledger_Mode==Ledger_PositionJoin && LastOrderTicket>0) {LedgerAddPosition((ulong)LastOrderTicket); AccumulateSequenceDealPL((ulong)LastDealTicket);} // B49a (F2): join the position, book its entry commission';
assert.ok(main.includes('        TradeLevels[Level_Count-1].ticket      = LastOrderTicket;\n'+HOOK_LINE+'\n'),'the hook follows the new level\'s ticket in Add_Level');
assert.equal(main.split('LedgerAddPosition(').length-1,5,'LedgerAddPosition: defined once, called by the Add_Level hook, the Init backfill, F1-lite adoption (test_restart_adopt.cjs) and the single\'s entry (B50, test_b50_single.cjs)');
// B50 (A1): GoatSingleOpen carries the same hook on its one level (test_b50_single.cjs runs it).
assert.ok(main.includes('   if(Ledger_Mode==Ledger_PositionJoin && LastOrderTicket>0) {s.LedgerAddPosition((ulong)LastOrderTicket); s.AccumulateSequenceDealPL((ulong)LastDealTicket);}'),'the single\'s entry joins its position');

// A buy sequence of three levels; a CumPartial harvest closes part of level 1 at a loss with the close helper's magic.
function harvest(mode,{exitMagic,text=main}={}){
 const a=account(),x=chart(a,mode,text);
 const entries=[1001,1002,1003].map(p=>{const d=a.open(p);x.level(x.buy,p,d);return d;});
 for(const d of entries)x.trans(d);                                   // the entries' DEAL_ADD transactions
 const out=a.close(1001,{magic:exitMagic,profit:-40,commission:-1,full:false});
 x.buy.AccumulateSequenceDealPL(out);                                 // closeLots books its ResultDeal()
 x.trans(out);                                                        // then OnTradeTransaction sees the same deal
 return {a,x,out};
}

// 1. B47 (and Legacy) are blind to the EA's magic-0 harvest; PositionJoin books it once, with the entry commissions.
{const b47=harvest(0,{exitMagic:0,text:mainB47}),legacy=harvest(0,{exitMagic:0}),join=harvest(1,{exitMagic:M});
 assert.equal(b47.x.buy.SequenceRealizedPL,0,'B47: the magic-0 harvest never reaches the ledger');
 assert.equal(legacy.x.buy.SequenceRealizedPL,0,'Legacy reproduces B47');
 assert.equal(join.x.buy.SequenceRealizedPL,-41-3*3.5,'PositionJoin: the harvest (-40 - 1 commission) once, plus 3 entry commissions');
 assert.deepEqual(join.x.buy.LedgerPositions,[1001,1002,1003]);
 assert.equal(join.x.buy.LedgerDeals.length,4,'3 entries + 1 exit, each booked once');
 // An exit that does carry MAGIC1 (a broker stop, say): B47 books it without entry commissions, and so does Legacy.
 const b47Magic=harvest(0,{exitMagic:M,text:mainB47}),legacyMagic=harvest(0,{exitMagic:M});
 assert.equal(b47Magic.x.buy.SequenceRealizedPL,-41,'B47 books a MAGIC1 exit');
 assert.equal(legacyMagic.x.buy.SequenceRealizedPL,-41,'Legacy reproduces B47');
 assert.deepEqual(legacyMagic.x.buy.LedgerPositions,[],'Legacy keeps no join state');
 // A close that still carries magic 0 (a dashboard or manual close) joins the same way.
 const zero=harvest(1,{exitMagic:0});assert.equal(zero.x.buy.SequenceRealizedPL,-41-3*3.5);
 // MLPS reads realized + open: with -20 open and Risk 50 only the joined ledger reaches -Risk.
 const OPEN=-20,RISK=50;
 assert.equal(legacy.x.buy.SequenceRealizedPL+OPEN<=-RISK,false,'Legacy: MLPS sees -20 and holds');
 assert.equal(join.x.buy.SequenceRealizedPL+OPEN<=-RISK,true,'PositionJoin: MLPS sees -71.5 and fires');
 ok();}

// 2. A broker stop, the other side's exits and foreign deals.
{const a=account(),x=chart(a,1);
 const b=a.open(1001);x.level(x.buy,1001,b);const s=a.open(2001,{type:1});x.level(x.sell,2001,s);
 const foreignOpen=a.open(3001,{magic:Y});const foreignClose=a.close(3001,{magic:0,profit:500});   // another chart, same symbol
 const otherSymbol=a.close(1001,{symbol:'GBPUSD',profit:900,full:false});
 const stop=a.close(1001,{magic:M,profit:-25,commission:0});   // a broker SL: only OnTradeTransaction sees it
 for(const d of [b,s,foreignOpen,foreignClose,otherSymbol,stop])x.trans(d);
 assert.equal(x.buy.SequenceRealizedPL,-3.5-25,'the broker stop joins the buy sequence');
 assert.equal(x.sell.SequenceRealizedPL,-3.5,'the sell sequence books only its own entry');
 const balance=a.deal({position:0,entry:0,type:2,magic:0,profit:1000});x.trans(balance);
 // Defensive: a non-trading deal never joins, even should a server attach a sequence position's id to a charge.
 const charge=a.deal({position:1001,entry:1,type:2,magic:0,profit:-1000});x.trans(charge);
 assert.equal(x.buy.SequenceRealizedPL+x.sell.SequenceRealizedPL,-3.5-25-3.5,'non-trading deals join nothing');
 ok();}

// 3. The daily P/L (MaxDaily*): a position opened yesterday and closed today by the EA (magic 0) counts; another
//    chart's exit on the same symbol does not; Legacy equals B47. The owner lookup runs after the window walk.
function dailyFixture(mode,text=main){
 const a=account(),x=chart(a,mode,text);
 a.open(1001,{time:DAY0-7200});a.close(1001,{magic:0,profit:-30,commission:-1,time:DAY0+600});      // overnight, EA close
 const today=a.open(1002,{time:DAY0+900});a.close(1002,{magic:M,profit:12,commission:-1,time:DAY0+1800});
 a.open(3001,{magic:Y,time:DAY0-7200});a.close(3001,{magic:0,profit:400,time:DAY0+2400});           // another chart
 a.close(1003,{magic:0,profit:7,time:DAY0+2500,symbol:'GBPUSD'});
 return {a,x,today};
}
{const b47=dailyFixture(0,mainB47),legacy=dailyFixture(0),join=dailyFixture(1);
 const LEGACY=-3.5+12-1;                 // today's entry commission and the MAGIC1 exit only
 assert.equal(b47.x.g.DailyClosedPL(),LEGACY,'B47: the overnight EA close is invisible to MaxDaily*');
 assert.equal(legacy.x.g.DailyClosedPL(),LEGACY,'Legacy reproduces B47');
 assert.equal(join.x.g.DailyClosedPL(),LEGACY-31,'PositionJoin: the overnight EA close counts; the other chart\'s does not');
 const lookups=join.a.calls.byPosition;assert.equal(lookups,2,'two unknown positions looked up once each');
 join.x.g.DailyClosedPL();assert.equal(join.a.calls.byPosition,lookups,'owners are cached across passes');
 ok();}

// 4. The dashboard's closed P/L (rebuild and transaction paths): the same join, Legacy equals B47.
{const run=(mode,text)=>{const f=dailyFixture(mode,text);f.x.g.DashboardBusRebuildClosedStats();
  const g=f.x.g;return [g.DashboardBusClosedPLTotal,g.DashboardBusClosedTradesTotal,g.DashboardBusClosedPLDaily,g.DashboardBusClosedPLWeekly];};
 assert.deepEqual(run(0),run(0,mainB47),'Legacy rebuild reproduces B47');
 assert.deepEqual(run(0),[11,1,11,11]);
 assert.deepEqual(run(1),[11-31,2,11-31,11-31],'PositionJoin rebuild adds this chart\'s magic-0 exit');
 const live=mode=>{const a=account(),x=chart(a,mode);const d=a.open(1001);x.level(x.buy,1001,d);x.trans(d);
  x.trans(a.close(1001,{magic:0,profit:-9,commission:-1,time:DAY0+60}));
  return [x.g.DashboardBusClosedPLTotal,x.g.DashboardBusClosedTradesTotal];};
 assert.deepEqual(live(0),[0,0],'Legacy: the EA close never reaches the dashboard (as B47)');
 assert.deepEqual(live(1),[-10,1],'PositionJoin: it does');
 ok();}

// 5. The owner cache: bounded, newest kept, an unknown position never cached.
{const a=account(),x=chart(a,1);
 for(let p=1;p<=OWNER_CACHE+10;p++){a.open(9000+p,{magic:p%2?M:Y});x.g.GoatLedgerPositionMine(9000+p);}
 assert.equal(x.g.g_GoatLedgerOwnerPosition.length,OWNER_CACHE);assert.equal(x.g.g_GoatLedgerOwnerPosition[0],9011,'the oldest are dropped');
 assert.equal(x.g.GoatLedgerPositionMine(9000+OWNER_CACHE+9),true);assert.equal(x.g.GoatLedgerPositionMine(9000+OWNER_CACHE+10),false);
 const before=a.calls.byPosition;x.g.GoatLedgerPositionMine(424242);x.g.GoatLedgerPositionMine(424242);
 assert.equal(a.calls.byPosition,before+2,'an unknown position is asked again');
 ok();}

// 6. The EA's closes carry MAGIC1 under PositionJoin only: every CTrade is followed by the marked line.
{const trades=[...main.matchAll(/^([ \t]*)CTrade\s+(\w+);\n(.*)$/gm)];
 assert.equal(trades.length,8,'the 8 CTrade instances of B47');
 for(const [,indent,name,next] of trades)
  assert.equal(next,indent+'if(Ledger_Mode==Ledger_PositionJoin) '+name+'.SetExpertMagicNumber(MAGIC1); // B49a (F2): the EA\'s closes carry MAGIC1');
 assert.equal((main.match(/SetExpertMagicNumber\(/g)||[]).length,8);
 assert.equal((mainB47.match(/SetExpertMagicNumber\(/g)||[]).length,0,'B47 never set a magic');
 ok();}

// 7. The input: appended last to the header, default Legacy.
{assert.match(header,/enum ENUM_LEDGER_MODE\n  \{\n   Ledger_Legacy=0, +\/\/ Legacy \(magic only\)\n   Ledger_PositionJoin=1  \/\/ Position join\n  \};\nsinput   ENUM_LEDGER_MODE        Ledger_Mode                   =                 Ledger_Legacy;/);
 const inputs=[...header.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
 assert.equal(inputs.indexOf('Ledger_Mode'),114,'appended after B47\'s 114 header inputs');
 // B50 (A0) appends its twelve after it (scripts/test_b50_no_drift.cjs pins them).
 assert.deepEqual(inputs.slice(115),['Engine_Mode','Single_SL_ATR','Single_TP_ATR','Single_TP_R','Single_Exit_Opposite','Single_Time_Stop_Bars',
  'Single_Time_Stop_TF','Clock_Mode','Server_Clock_Model','Server_UTC_Offset','NY_Session','Rollover_Block_Minutes'],'then B50\'s');
 ok();}

// 8. Claude-Mac GOAT-EA#265 P2-1: a fee-charging broker's DEAL_FEE counts wherever the join sums (the ledger, the
//    daily P/L, the dashboard's closed P/L), as the export and GoatRankPF count it. Legacy (B47) never read it.
{const FEE=-0.75;
 const ledger=mode=>{const a=account(),x=chart(a,mode);const d=a.open(1001,{commission:-3.5});a.deals.get(d).fee=FEE;x.level(x.buy,1001,d);x.trans(d);
  const out=a.close(1001,{magic:M,profit:-40,commission:-1});a.deals.get(out).fee=FEE;x.trans(out);return x.buy.SequenceRealizedPL;};
 assert.equal(ledger(1),-3.5+FEE-41+FEE,'PositionJoin: entry and exit fees');
 const daily=(mode,text=main)=>{const f=dailyFixture(mode,text);for(const d of f.a.deals.values())d.fee=FEE;return f.x.g.DailyClosedPL();};
 assert.equal(daily(1),-3.5+12-1-31+3*FEE,'PositionJoin daily: the MAGIC1 deals and the joined exit, each with its fee');
 assert.equal(daily(0),daily(0,mainB47),'Legacy daily: as B47, no fee');assert.equal(daily(0),-3.5+12-1);
 const rebuild=mode=>{const f=dailyFixture(mode);for(const d of f.a.deals.values())d.fee=FEE;f.x.g.DashboardBusRebuildClosedStats();return f.x.g.DashboardBusClosedPLTotal;};
 assert.equal(rebuild(1),11-31+2*FEE,'PositionJoin rebuild: both exits with their fee');assert.equal(rebuild(0),11,'Legacy rebuild: no fee');
 const live=mode=>{const a=account(),x=chart(a,mode);const d=a.open(1001);x.level(x.buy,1001,d);x.trans(d);
  const out=a.close(1001,{magic:M,profit:-9,commission:-1,time:DAY0+60});a.deals.get(out).fee=FEE;x.trans(out);return x.g.DashboardBusClosedPLTotal;};
 assert.equal(live(1),-10+FEE);assert.equal(live(0),-10);
 ok();}

// 9. Claude-Mac GOAT-EA#265 P2-2/P2-3: an owner is cached only once its entry deal has been seen (an exit whose entry
//    is not in the loaded history is asked again next time), and the cache is cleared at every OnInit (a live re-init
//    may restore another MAGIC1).
{const a=account(),x=chart(a,1);
 a.close(7001,{magic:0,profit:-20,time:DAY0+60});                   // its entry is not in the loaded history yet
 assert.equal(x.g.GoatLedgerPositionMine(7001),false);assert.ok(!x.g.g_GoatLedgerOwnerPosition.includes(7001),'not cached');
 a.open(7001,{time:DAY0-60});                                         // the entry arrives
 assert.equal(x.g.GoatLedgerPositionMine(7001),true,'asked again: this chart\'s');
 assert.ok(x.g.g_GoatLedgerOwnerPosition.includes(7001));
 x.g.GoatLedgerOwnerReset();assert.deepEqual([x.g.g_GoatLedgerOwnerPosition.length,x.g.g_GoatLedgerOwnerMine.length],[0,0]);
 assert.ok(main.includes('                                  Seq_Buy.Init(OP_BUY,false);        Seq_Sell.Init(OP_SELL,false);\n     GoatLedgerOwnerReset();'),
  'OnInit clears it right after the sequences\' Init (MAGIC1 is settled above)');
 ok();}

// 10. Codex GOAT-EA#265: a live re-init into PositionJoin (an input change keeps EA globals) joins the running
//     sequence's positions, so their later closes are booked; a fresh start joins nothing.
{const a=account(),x=chart(a,1);
 a.open(1001);a.open(1002);
 const seq=x.buy;seq.Active=true;seq.Level_Count=2;seq.TradeLevels=[{ticket:1001},{ticket:1002}];
 seq.Init(0,false);
 assert.deepEqual(seq.LedgerPositions,[1001,1002],'the running sequence\'s positions join');
 const out=a.close(1002,{magic:M,profit:-41,commission:0});x.trans(out);assert.equal(seq.SequenceRealizedPL,-41,'and a later close is booked');
 const legacy=chart(account(),0).buy;legacy.Active=true;legacy.Level_Count=1;legacy.TradeLevels=[{ticket:1001}];legacy.Init(0,false);
 assert.deepEqual(legacy.LedgerPositions,[],'Legacy keeps no join');
 const fresh=chart(account(),1).buy;fresh.Init(0,false);assert.deepEqual(fresh.LedgerPositions,[]);
 ok();}

// 11. Codex GOAT-EA#267 P1: the canonical SET writer (WriteSet: OnTester's export and the trace's effective-inputs.set)
//     records a PositionJoin run's ledger, so the exported SET reloads with the accounting that produced it. A Legacy
//     SET is B47's bytes exactly (an omitted Ledger_Mode reads as Legacy: the controller's APPENDED_INPUTS, the child
//     audit's Legacy default). WriteSet's last lines run here, with the same tail cut from B47's header as the control.
{const writeSet=bodyOf(header,'void WriteSet(string desc)');
 // B50 (A0) writes its own lines after this one; they are tested in scripts/test_b50_parity.cjs (the WriteSet golden).
 const tail=text=>text.slice(text.indexOf('FileWrite(FileSET_handle,"Trade_December="'),text.includes('// B50:begin b50-writeset')?text.indexOf('// B50:begin b50-writeset'):text.indexOf('FileClose(FileSET_handle);'));
 const run=(text,mode)=>{const lines=[];const c={FileSET_handle:1,Trade_December:true,Ledger_Mode:mode,Ledger_Legacy:0,Ledger_PositionJoin:1,
  FileWrite:(h,s)=>lines.push(s)};vm.createContext(c);vm.runInContext(js(tail(text).replace(/\(string\)(?:\(int\))?(\w+)/g,'String($1)')),c);return lines;};
 assert.deepEqual(run(writeSet,0),['Trade_December=true'],'Legacy: no Ledger_Mode line, as B47');
 assert.deepEqual(run(writeSet,1),['Trade_December=true','Ledger_Mode=1'],'PositionJoin: recorded');
 const headerB47=clean(execFileSync('git',['show',B47_SOURCE+':GOAT_Inputs_Definitions.mqh'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
 assert.deepEqual(run(bodyOf(headerB47,'void WriteSet(string desc)'),1),['Trade_December=true'],'B47 never wrote it');
 // Load-bearing: without the Legacy gate a Legacy SET gains a line (B47 parity broken); without the line nothing is recorded.
 const line=writeSet.split('\n').find(l=>l.includes('"Ledger_Mode="'));assert.ok(line&&/^if\(Ledger_Mode!=Ledger_Legacy\) /.test(line),line);
 assert.deepEqual(run(writeSet.replace('if(Ledger_Mode!=Ledger_Legacy) ',''),0),['Trade_December=true','Ledger_Mode=0'],'mutant: ungated');
 assert.equal(writeSet.indexOf(line)<writeSet.indexOf('FileClose(FileSET_handle);'),true,'written before the file closes');
 ok();}

console.log(JSON.stringify({passed,test:'ledger_join'}));
