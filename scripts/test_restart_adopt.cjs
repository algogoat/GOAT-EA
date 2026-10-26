// B49a (F1-lite; roadmap F1/D8, WEEKEND-1031 goatai#2587 6427772701 / 6428370704): restart adoption, manage-only.
// Through B47 OnInit re-created empty sequences, so after a restart an open basket kept only its broker TP/SL: MLPS
// never fired again and a new sequence could start beside it. Now, on live charts only:
// - a restart record per magic + symbol + direction (terminal GlobalVariables): the first level's ticket and the five
//   sizes frozen at start (written once), the realized P/L (flushed from the timer at most every GOAT_SQ_FLUSH_MS), the
//   first position's open time in ms (written last); the sequence's end deletes it; a failed write freezes adds;
// - OnInit adopts an open basket with no running sequence: levels rebuilt from the live positions, the sequence Active,
//   Traded and manage-only (adds frozen). A matching record (its first ticket still live, or every live position opened
//   at or after its start) restores the realized P/L, so MLPS sees realized + open, and the frozen sizes, so Lock/TP/SL
//   and trailing resume. Without them the EA leaves that basket's broker SL/TP untouched.
// This runs the production SEQUENCE methods (syntax-only MQL-to-JS conversion) against modelled positions and
// GlobalVariables, one fresh SEQUENCE per "terminal start". Source semantics only: Ops' kill-and-restart drill on T2
// is the native check (MLPS fires at -Risk, adds stay frozen, no second same-direction sequence).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
// test_restart_adopt_mutations.cjs points GOAT_EA_MAIN at a mutated entrypoint.
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 let i=text.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<text.length;j++){if(text[j]==='{')depth++;if(text[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
function js(text){
 return text.replace(/\/\/.*$/gm,'')
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
 ['PersistStart',['first_ticket'],'   void PersistStart(const ulong first_ticket)'],
 ['PersistLevels',[],'   void PersistLevels()'],
 ['PersistFlush',['force=false'],'   void PersistFlush(const bool force=false)'],
 ['PersistEnd',[],'   void PersistEnd()'],
 ['ManageOnlyFrozen',['level'],'   bool ManageOnlyFrozen(const int level)'],
 ['PersistRead',['field','value'],'   bool PersistRead(const string field,double &value)'],
 ['AdoptOpenPositions',[],'   bool AdoptOpenPositions()'],
 ['LedgerHasPosition',['position_id'],'   bool LedgerHasPosition(const ulong position_id)'],
 ['LedgerAddPosition',['position_ticket'],'   void LedgerAddPosition(const ulong position_ticket)'],
];
const FLUSH_MS=Number((main.match(/^#define GOAT_SQ_FLUSH_MS (\d+)$/m)||[])[1]);assert.equal(FLUSH_MS,5000);
const UPDATE_GUARD='    if(Adopted && !AdoptSizes) return; // B49a (F1-lite): an adopted basket without its frozen sizes keeps its broker SL/TP';
const firstStatement=body=>body.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l))[0];

// ---- the modelled terminal: positions (account-wide), GlobalVariables (this terminal), the clock ----
const M=1843920117,Y=907113355,SYM='EURUSD',T0=1792054800000;
const K={POSITION_MAGIC:'magic',POSITION_SYMBOL:'symbol',POSITION_TYPE:'type',POSITION_TIME_MSC:'msc',POSITION_PRICE_OPEN:'open',
 POSITION_VOLUME:'volume',POSITION_SL:'sl',POSITION_TP:'tp',POSITION_IDENTIFIER:'identifier',POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,
 OP_BUY:0,OP_SELL:1,Key:'GOAT',Ledger_Legacy:0,Ledger_PositionJoin:1,Operation_Batch:6,Operation_Dash:7,MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3};
const GMT0=Math.floor(T0/1000)+3600;   // TimeGMT() at the first level
function terminal({positions=[],gv=new Map(),tester=false,mode=0,ledger=1}={}){return {positions,gv,tester,mode,ledger,now:1000,gmt:GMT0,flushes:0,writes:[],failWrites:new Set(),logs:[],alerts:[]};}
const pos=(ticket,{magic=M,type=0,msc=T0,open=1.1,volume=0.1,sl=0,tp=0,symbol=SYM}={})=>({ticket,magic,type,msc,open,volume,sl,tp,symbol,identifier:ticket});
// One SEQUENCE in a terminal start (a restart is a fresh SEQUENCE over the same terminal).
function sequence(t,{dir=0,virtual=false}={}){
 let sel=null;
 const levels=[];levels.objects=true;
 const c={...K,MAGIC1:M,_Symbol:SYM,dir,Virtual:virtual,Desc:'Trend '+(dir?'Sell':'Buy'),Ledger_Mode:t.ledger,Mode_Operation:t.mode,
  Max_Seq_Levels:64,GOAT_SQ_FLUSH_MS:FLUSH_MS,TradeLevels:levels,LedgerPositions:[],LedgerDeals:[],
  Active:false,Traded:false,Level_Count:0,Trades_Count:0,Level_Last:0,Level_SL:0,SequenceRealizedPL:0,
  Size_Grid:1234.5,Size_Lock:1234.5,Size_TP:1234.5,Size_SL:1234.5,Size_TSL:1234.5,updates:[],
  MQLInfoInteger:k=>(k===1&&t.tester)?1:0,GetTickCount:()=>t.now,TimeCurrent:()=>Math.floor(T0/1000)+3600,TimeGMT:()=>t.gmt,
  GlobalVariablesFlush:()=>{t.flushes++;},
  IntegerToString:v=>String(v),DoubleToString:(v,d)=>Number(v).toFixed(d),MathIsValidNumber:v=>Number.isFinite(v),GetLastError:()=>4501,
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push(a.objects?{ticket:0,price_level:0,price_trade:0,lots:0,sl:0,tp:0}:0);a.length=n;return n;},
  Print:(...a)=>t.logs.push(a.join('')),Alert:(...a)=>t.alerts.push(a.join('')),
  GlobalVariableSet:(k,v)=>{t.writes.push(k);if(t.failWrites.has(k.split('_').pop())||t.failWrites.has('*'))return 0;t.gv.set(k,Number(v));return 1;},
  GlobalVariableGetRef:(k,set)=>{if(!t.gv.has(k))return false;set(t.gv.get(k));return true;},
  GlobalVariableDel:k=>t.gv.delete(k),
  PositionsTotal:()=>t.positions.length,PositionGetTicket:i=>{sel=t.positions[i];return sel?sel.ticket:0;},
  PositionSelectByTicket:tk=>{sel=t.positions.find(p=>p.ticket===tk)||null;return !!sel;},
  PositionGetInteger:k=>sel[k],PositionGetString:k=>sel[k],PositionGetDouble:k=>sel[k],
 };
 c.UpdateLockTPSL=n=>c.updates.push(n);   // its own first statement is checked from the source (section 6)
 vm.createContext(c);
 vm.runInContext(METHODS.map(([n,a,s])=>fn(n,a,bodyOf(main,s))).join(''),c);
 c.PersistReset();
 return c;
}
const key=(field,dir='B',magic=M)=>'GOAT_SQ_'+magic+'_'+SYM+'_'+dir+'_'+field;
// A sequence's first real level, as Add_Level leaves it (sizes frozen, Level_Count 1, the hook's PersistStart), and
// each later real level (the hook's PersistLevels).
function startSequence(s,t,ticket,sizes=[0.0012,0.0008,0,0.0030,0.0004]){
 [s.Size_Grid,s.Size_Lock,s.Size_TP,s.Size_SL,s.Size_TSL]=sizes;s.Active=s.Traded=true;s.Level_Count=1;s.PersistStart(ticket);
}
const addLevel=s=>{s.Level_Count++;s.PersistLevels();};

// 1. The record: written at the first level (T last), its level count with each later level, the realized P/L at
//    most every 5 s, every field re-set once per UTC day, each write flushed to disk, deleted at the end.
{const t=terminal({positions:[pos(1001,{msc:T0})]}),s=sequence(t);
 startSequence(s,t,1001);
 assert.deepEqual(t.writes,['TK','G','L','TP','SL','TS','N','R','T'].map(f=>key(f)),'the start record, T written last');
 assert.equal(t.gv.get(key('T')),T0);assert.equal(t.gv.get(key('TK')),1001);assert.equal(t.gv.get(key('TS')),0.0004);
 assert.equal(t.gv.get(key('N')),1);assert.equal(t.flushes,1,'flushed to gvariables.dat');
 addLevel(s);addLevel(s);assert.equal(t.gv.get(key('N')),3,'each later level updates the level count');assert.equal(t.flushes,3);
 t.writes.length=0;s.SequenceRealizedPL=-12.5;
 s.PersistFlush();assert.deepEqual(t.writes,[],'within 5 s of the last write nothing is written');
 for(let i=0;i<10;i++){s.SequenceRealizedPL-=1;t.now+=400;s.PersistFlush();}
 assert.deepEqual(t.writes,[key('R')],'ten changes inside 5 s: one write');assert.equal(t.flushes,4);
 t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.writes.length,1,'unchanged: no write');
 // The next UTC day: one read-and-set of every field (the 4-week expiry), inside the same rate bound, then flushed.
 s.SequenceRealizedPL-=1;t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.flushes,5);    // a write, now
 t.writes.length=0;t.gmt+=86400;s.PersistFlush();assert.deepEqual(t.writes,[],'within 5 s of that write: not yet');
 t.now+=FLUSH_MS;s.PersistFlush();
 assert.deepEqual(t.writes,['R','TK','G','L','TP','SL','TS','N','T'].map(f=>key(f)),'every field re-set once that day');
 assert.equal(t.gv.get(key('T')),T0,'with its own value');assert.equal(t.flushes,6);
 t.writes.length=0;t.now+=FLUSH_MS;s.PersistFlush();assert.deepEqual(t.writes,[],'not again that day');
 s.SequenceRealizedPL=-30;s.PersistFlush(true);assert.equal(t.gv.get(key('R')),-30,'OnDeinit forces the flush');
 s.PersistEnd();assert.equal(t.gv.size,0,'the end deletes the record');assert.equal(t.flushes,8,'and flushes the deletion');
 ok();}

// 2. A restart mid-basket (CumPartial: level 1 partly harvested at a loss, realized -41.5): matched, everything back.
function midBasket(){
 const t=terminal({positions:[pos(1002,{msc:T0+60000,open:1.0985,volume:0.2,sl:1.0900}),pos(1001,{msc:T0,open:1.1,volume:0.05,sl:1.0900}),
  pos(1003,{msc:T0+120000,open:1.0970,volume:0.3,sl:1.0900})]});
 const before=sequence(t);startSequence(before,t,1001);addLevel(before);addLevel(before);
 before.SequenceRealizedPL=-41.5;t.now+=FLUSH_MS;before.PersistFlush();
 return t;
}
{const t=midBasket(),s=sequence(t);   // the terminal restarts: a fresh SEQUENCE, the same positions and GlobalVariables
 assert.equal(s.AdoptOpenPositions(),true);
 assert.deepEqual([s.Active,s.Traded,s.Adopted,s.AdoptMatched,s.AdoptSizes],[true,true,true,true,true]);
 assert.equal(s.SequenceRealizedPL,-41.5,'MLPS sees realized + open, not open only');
 assert.deepEqual(s.TradeLevels.map(l=>l.ticket),[1001,1002,1003],'levels by open time');
 assert.deepEqual(s.TradeLevels.map(l=>[l.price_level,l.lots,l.sl]),[[1.1,0.05,1.09],[1.0985,0.2,1.09],[1.097,0.3,1.09]]);
 assert.deepEqual([s.Level_Count,s.Trades_Count,s.Level_Last],[3,3,1.097]);
 assert.deepEqual([s.Size_Grid,s.Size_Lock,s.Size_TP,s.Size_SL,s.Size_TSL],[0.0012,0.0008,0,0.0030,0.0004],'the frozen sizes');
 assert.deepEqual(s.updates,[3],'Lock/TP/SL recomputed from the frozen sizes');
 assert.deepEqual(s.LedgerPositions,[1001,1002,1003],'the positions join F2\'s ledger');
 assert.equal(t.alerts.length,1);assert.match(t.alerts[0],/adopted 3 open position\(s\) of magic 1843920117 as manage-only \(adds frozen\)\. Record matched: MLPS sees realized -41\.50 \+ open P\/L\. Lock\/TP\/SL and trailing resume/);
 // Manage-only: adds frozen (logged once), closes and MLPS untouched; the record is the same sequence's.
 assert.equal(s.ManageOnlyFrozen(4),true);assert.equal(s.ManageOnlyFrozen(4),true);
 assert.deepEqual(t.logs.filter(l=>l.startsWith('GOAT restart: add_frozen=')),['GOAT restart: add_frozen=manage_only side=BUY magic=1843920117 symbol=EURUSD level=4 closes_stops_mlps=continue']);
 assert.equal(t.gv.get(key('T')),T0,'the record carries on');
 // The first level was closed by a harvest: every live position opened at or after the start still matches.
 const t2=midBasket();t2.positions=t2.positions.filter(p=>p.ticket!==1001);const s2=sequence(t2);s2.AdoptOpenPositions();
 assert.deepEqual([s2.AdoptMatched,s2.SequenceRealizedPL,s2.Level_Count],[true,-41.5,2]);
 // A start time stamped late (PositionSelectByTicket failed at the start, so TimeCurrent stood in): the oldest live
 // position predates the record, and its first ticket, still live, is what matches.
 const t3=midBasket();t3.gv.set(key('T'),T0+5000);const s3=sequence(t3);s3.AdoptOpenPositions();
 assert.deepEqual([s3.AdoptMatched,s3.SequenceRealizedPL],[true,-41.5]);
 // Claude-Mac 6428447507: the start-time rule also needs the live count within the record's level count, so a later,
 // unrelated basket on the same key (more positions than the stale record ever had) does not match it.
 const t4=midBasket();t4.gv.set(key('N'),2);t4.gv.set(key('TK'),999);const s4=sequence(t4);s4.AdoptOpenPositions();
 assert.deepEqual([s4.AdoptMatched,s4.SequenceRealizedPL],[false,0],'3 live positions, a record of 2 levels, its ticket gone');
 const t5=midBasket();t5.gv.set(key('N'),2);const s5=sequence(t5);s5.AdoptOpenPositions();
 assert.equal(s5.AdoptMatched,true,'its first ticket still live: the ticket rule matches');
 ok();}

// 3. No matching record: open P/L only, broker SL/TP untouched, the stale record replaced by this basket's.
{const t=midBasket();t.gv.set(key('T'),T0+600000);t.gv.set(key('TK'),999);   // a later sequence's record, ticket gone
 const s=sequence(t);s.AdoptOpenPositions();
 assert.deepEqual([s.Adopted,s.AdoptMatched,s.AdoptSizes,s.SequenceRealizedPL],[true,false,false,0]);
 assert.deepEqual(s.updates,[],'no Lock/TP/SL write from guessed sizes');
 assert.match(t.alerts[0],/No matching record: MLPS sees open P\/L only\. The EA leaves this basket's broker SL\/TP untouched\./);
 assert.equal(t.gv.get(key('T')),T0,'a new record starts at the oldest live position');assert.equal(t.gv.get(key('TK')),1001);
 assert.equal(t.gv.get(key('G')),1234.5,'its sizes are unknown (the sentinel)');
 // The stale record is deleted before the new one is written: if the new start time cannot be written, no stale T
 // is left to pair with the new fields at the next restart (the record reads as incomplete, so unmatched).
 const f=midBasket();f.gv.set(key('T'),T0+600000);f.gv.set(key('TK'),999);f.failWrites.add('T');
 const fs1=sequence(f);fs1.AdoptOpenPositions();
 assert.equal(f.gv.has(key('T')),false,'no stale start time survives');assert.equal(fs1.PersistFailed,true,'adds frozen');
 // The next restart matches that record, but its sizes stay unknown: the stops stay untouched.
 const s2=sequence(t);s2.AdoptOpenPositions();assert.deepEqual([s2.AdoptMatched,s2.AdoptSizes,s2.updates.length],[true,false,0]);
 // No record at all, or an incomplete one (no T, the field written last): the same as unmatched.
 for(const drop of [['T','TK','G','L','TP','SL','TS','R'],['T']]){
  const u=midBasket();for(const f of drop)u.gv.delete(key(f));const x=sequence(u);x.AdoptOpenPositions();
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

// 5. A failed record write freezes adds (logged and alerted once) until a write succeeds.
{const t=terminal({positions:[pos(1001)]});t.failWrites.add('*');const s=sequence(t);
 startSequence(s,t,1001);
 assert.equal(s.PersistFailed,true);assert.equal(t.alerts.length,1);assert.match(t.alerts[0],/restart record not written .*Adds are frozen until a write succeeds/);
 assert.equal(s.ManageOnlyFrozen(2),true);assert.match(t.logs.at(-1),/add_frozen=record_unwritten/);
 t.now+=FLUSH_MS;s.PersistFlush();assert.equal(t.alerts.length,1,'alerted once');assert.equal(s.PersistFailed,true);
 t.failWrites.clear();t.now+=FLUSH_MS;s.PersistFlush();
 assert.equal(s.PersistFailed,false,'the retried start succeeded');assert.equal(t.gv.get(key('T')),T0);
 assert.equal(s.ManageOnlyFrozen(2),false,'adds resume');
 // A later realized write fails: frozen again, then resumes.
 t.failWrites.add('R');s.SequenceRealizedPL=-5;t.now+=FLUSH_MS;s.PersistFlush();assert.equal(s.ManageOnlyFrozen(2),true);
 t.failWrites.clear();t.now+=FLUSH_MS;s.PersistFlush();assert.equal(s.ManageOnlyFrozen(2),false);assert.equal(t.gv.get(key('R')),-5);
 ok();}

// 6. Where it sits in the source.
{const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 const lines=ADD.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l)).map(l=>l.trim());
 assert.ok(lines[1].startsWith('if(!Virtual && GoatCidGuardAddFrozen('),'B47\'s freeze');
 assert.equal(lines[2],'if(!Virtual && ManageOnlyFrozen(Level_Count+1)) return false; // B49a (F1-lite): an adopted basket, or a failed restart record, freezes adds');
 assert.ok(ADD.includes('        if(LastOrderTicket>0) {if(PersistStartMsc==0) PersistStart((ulong)LastOrderTicket); else PersistLevels();} // B49a (F1-lite): the first real level starts the restart record, each later one updates its level count'));
 assert.equal(firstStatement(bodyOf(main,'   void UpdateLockTPSL(int count=0)')),UPDATE_GUARD);
 assert.equal(firstStatement(bodyOf(main,'   void TrailingStoploss()')),UPDATE_GUARD);
 assert.ok(main.includes('                                  Seq_Buy.Init(OP_BUY,false);        Seq_Sell.Init(OP_SELL,false);\n     Seq_Buy.AdoptOpenPositions(); Seq_Sell.AdoptOpenPositions();'),'OnInit adopts right after the sequences\' Init');
 assert.equal((main.match(/\.AdoptOpenPositions\(\)/g)||[]).length,2,'adoption: OnInit only');
 assert.ok(bodyOf(main,'void GoatTimerBody(void)').includes('   GoatCidGuardHeartbeat(); // B47: the claim heartbeat (every GOAT_CID_CLAIM_HEARTBEAT_MS; live trading charts only)\n   Seq_Buy.PersistFlush(); Seq_Sell.PersistFlush();'),'the timer flushes');
 assert.ok(bodyOf(main,'void OnDeinit(const int reason)').includes('   Seq_Buy.PersistFlush(true); Seq_Sell.PersistFlush(true);'),'OnDeinit forces it');
 const END=bodyOf(main,'   void End_Sequence(string desc)');
 assert.ok(END.indexOf('PersistEnd(); PersistReset();')>END.indexOf('GoatTraceEnd(TraceSequenceID,desc);')&&END.indexOf('PersistEnd(); PersistReset();')<END.indexOf('Active=Traded=Trailing=Retrace_Triggered=false;'),'the end deletes the record while the sequence is still known');
 // MLPS needs Active, Traded and a real sequence, which adoption provides.
 assert.ok(bodyOf(main,'   bool EnforceSequenceMLPS(const string context)').includes('if(Virtual || !Active || !Traded)'));
 ok();}

console.log(JSON.stringify({passed,test:'restart_adopt'}));
