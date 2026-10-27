// B49b PR-5 (F5, Gate_Recheck; anatomy 02 §5.7, EX-11; goatai#2587 6433828681, Claude-Mac 6433854745). The production code
// runs here from GOAT V1.49.mq5:
// 1. GoatFirstOrderGateReason: each start gate of OnTick's signal block and SignalEntryTrigger, for the position's side.
// 2. SEQUENCE::FirstOrderGatesRefused: Legacy never refuses (B49a); under Gate_AtFirstOrder a real sequence's first order
//    is refused when a gate is closed: an active (delayed-live) candidate ends with the gate named, an immediate start
//    keeps no sizing, and the side's flag is set. A Reverse_Seq position reads its own side's bias (EX-11).
// 3. The virtual promotion block of Add_Level, run as written: a promoted order the gates refused ends the virtual
//    candidate too; a promotion that simply did not happen (MustCheck) leaves it as B49a does.
// 4. Where the refusal sits: the first real order only, after every B49a add check and before the order.
// test_b49b_f5_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
let passed=0;const ok=()=>passed++;

function braceBody(text,from){
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',from),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 return braceBody(text,a);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
function js(text){
 return text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
  .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ');
}
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const GATE_SIG='string GoatFirstOrderGateReason(const int pos_dir,const bool opposite_traded)';
const K={OP_BUY:0,OP_SELL:1,Long_and_Short:0,Long:1,Short:2,Gate_Legacy:0,Gate_AtFirstOrder:1};
// Every gate open: what OnTick and SignalEntryTrigger require before an immediate start.
const OPEN={Active:true,Allow_New_Sequence:true,Sequence_New_Friday:true,Sequence_New_Dec:true,DashboardPortfolioPaused:false,
 Sequence_New_News:true,Sequence_New_Bias_B:true,Sequence_New_Bias_S:true,Mode_Trade:0,Allow_Opposite_Seq:true,
 trade:{0:true,1:true},entry:{0:true,1:true}};
function gates(over={}){
 const g={...K,...OPEN,...over};
 g.DashboardTradeAllowed=op=>g.trade[op];g.DashboardEntryAllowed=op=>g.entry[op];
 vm.createContext(g);vm.runInContext(fn('GoatFirstOrderGateReason',['pos_dir','opposite_traded'],bodyOf(main,GATE_SIG)),g);
 return g;
}

// 1. Each gate, for the position's side.
{assert.equal(gates().GoatFirstOrderGateReason(0,false),'','all open: no gate');
 assert.equal(gates().GoatFirstOrderGateReason(1,false),'');
 const closed=[[{Active:false},'session'],[{Allow_New_Sequence:false},'allow_new_sequence'],[{Sequence_New_Friday:false},'friday'],
  [{Sequence_New_Dec:false},'december'],[{DashboardPortfolioPaused:true},'dashboard_paused'],[{trade:{0:false,1:true}},'dashboard_direction'],
  [{Sequence_New_News:false},'news'],[{Sequence_New_Bias_B:false},'bias'],[{Mode_Trade:2},'mode_trade'],[{entry:{0:false,1:true}},'dashboard_entry']];
 for(const [over,reason] of closed) assert.equal(gates(over).GoatFirstOrderGateReason(0,false),reason,'buy: '+reason);
 // The position's own side: a buy ignores the sell side's bias, direction, entry permission, and the reverse.
 assert.equal(gates({Sequence_New_Bias_S:false,trade:{0:true,1:false},entry:{0:true,1:false},Mode_Trade:1}).GoatFirstOrderGateReason(0,false),'');
 assert.equal(gates({Sequence_New_Bias_S:false}).GoatFirstOrderGateReason(1,false),'bias','a sell reads the sell bias');
 assert.equal(gates({Sequence_New_Bias_B:false}).GoatFirstOrderGateReason(1,false),'','EX-11: a Reverse_Seq sell is not vetoed by the buy bias');
 assert.equal(gates({Mode_Trade:1}).GoatFirstOrderGateReason(1,false),'mode_trade');
 assert.equal(gates({trade:{0:true,1:false}}).GoatFirstOrderGateReason(1,false),'dashboard_direction');
 // The opposite sequence: refused only when Allow_Opposite_Seq is off and the other side has traded.
 assert.equal(gates({Allow_Opposite_Seq:false}).GoatFirstOrderGateReason(0,true),'opposite_sequence');
 assert.equal(gates({Allow_Opposite_Seq:false}).GoatFirstOrderGateReason(0,false),'');
 assert.equal(gates().GoatFirstOrderGateReason(0,true),'','Allow_Opposite_Seq on');
 ok();}

// 2. The refusal.
function sequence({dir=0,virtual=false,traded=false,active=false,gate=1,over={},oppositeTraded=false}={}){
 const g=gates(over);
 const s=Object.assign(g,{Gate_Recheck:gate,dir,Virtual:virtual,Traded:traded,Active:over.Active??true,logs:[],ends:[],Max_Seq_Trades:4,
  Seq_Buy:{Traded:dir===1?oppositeTraded:false},Seq_Sell:{Traded:dir===0?oppositeTraded:false},g_goat_first_order_refused:[false,false],
  Size_Grid:0.0012,Size_Lock:0.0008,Size_TP:0,Size_SL:0.003,Size_TSL:0.0004,StartLots:0.1,PeakLots:0.2,PeakCumLots:0.3,ScaleFactor:1,
  LotsRaw:[1],LotsNorm:[1],LotsCum:[1],Distances:[0,1],ArrayResize:(a,n)=>{a.length=n;return n;},
  Print:(...a)=>s.logs.push(a.join(''))});
 // SEQUENCE::Active is the member (the candidate is running); the session flag the gate reads is the global Active.
 const member={Active:active};
 vm.runInContext('var __member;function End_Sequence(desc){ends.push(desc);__member.Active=false;}',s);s.__member=member;
 const body=js(bodyOf(main,'   bool FirstOrderGatesRefused()')).replace(/\bActive\b(?!\s*:)/g,m=>'__member.Active')
  .replace(/GoatFirstOrderGateReason\(/g,'GoatFirstOrderGateReason(');
 vm.runInContext('function FirstOrderGatesRefused(){'+body+'}',s);
 s.member=member;return s;
}
{// Legacy never refuses, whatever is closed (B49a).
 const legacy=sequence({gate:0,over:{Active:false,Sequence_New_News:false}});
 assert.equal(legacy.FirstOrderGatesRefused(),false);assert.deepEqual([legacy.logs,legacy.ends,legacy.g_goat_first_order_refused],[[],[],[false,false]]);
 assert.equal(legacy.Size_Grid,0.0012,'and keeps its sizing');
 // A virtual candidate and an already-traded sequence are never refused here (adds are not first orders).
 assert.equal(sequence({virtual:true,over:{Active:false}}).FirstOrderGatesRefused(),false);
 assert.equal(sequence({traded:true,over:{Active:false}}).FirstOrderGatesRefused(),false);
 // All open: the order goes ahead.
 const open=sequence();assert.equal(open.FirstOrderGatesRefused(),false);assert.deepEqual(open.logs,[]);
 // An immediate start (the candidate not active yet) on a closed gate: refused, no sizing kept, the side's flag set.
 const start=sequence({over:{Sequence_New_Friday:false}});
 assert.equal(start.FirstOrderGatesRefused(),true);assert.deepEqual(start.ends,[],'nothing to end');
 assert.deepEqual([start.Size_Grid,start.Size_SL,start.StartLots,start.Distances.length,start.LotsCum.length],[1234.5,1234.5,0,0,0]);
 assert.deepEqual(start.g_goat_first_order_refused,[true,false]);
 assert.deepEqual(start.logs,['GOAT gates: first order refused side=BUY gate=friday (Gate_Recheck: every start gate holds at the first real order)']);
 // A delayed-live candidate (active, not traded): it ends with the gate named.
 const live=sequence({dir:1,active:true,over:{Active:false}});
 assert.equal(live.FirstOrderGatesRefused(),true);assert.deepEqual(live.ends,['Gate at first order: session']);
 assert.deepEqual(live.g_goat_first_order_refused,[false,true]);assert.match(live.logs[0],/side=SELL gate=session/);
 // EX-11: a Reverse_Seq sell started on a buy signal reads the sell bias.
 assert.equal(sequence({dir:1,over:{Sequence_New_Bias_B:false}}).FirstOrderGatesRefused(),false);
 assert.equal(sequence({dir:1,over:{Sequence_New_Bias_S:false}}).FirstOrderGatesRefused(),true);
 // The opposite side's Traded is the other sequence's.
 assert.equal(sequence({dir:0,oppositeTraded:true,over:{Allow_Opposite_Seq:false}}).FirstOrderGatesRefused(),true);
 assert.equal(sequence({dir:1,oppositeTraded:true,over:{Allow_Opposite_Seq:false}}).FirstOrderGatesRefused(),true);
 assert.equal(sequence({dir:1,oppositeTraded:false,over:{Allow_Opposite_Seq:false}}).FirstOrderGatesRefused(),false);
 ok();}

// 3. The virtual promotion block, as written in Add_Level.
const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
const PROMO_AT=ADD.indexOf('     if(Virtual && Level_Count==Delay_Trade && ((dir==OP_BUY&&!Seq_Buy.Active) || (dir==OP_SELL&&!Seq_Sell.Active)))');
assert.ok(PROMO_AT>0,'the promotion block');
const PROMO=braceBody(ADD,PROMO_AT);
function promote({dir=0,mustCheck=true,refused=false,started=false,stale=false}){
 const c={...K,dir,ask:1.1,bid:1.0999,MustCheck_Buy:mustCheck,MustCheck_Sell:mustCheck,ends:[],calls:0,
  g_goat_first_order_refused:[stale,stale],DashboardEntryAllowed:()=>true};
 const real={Active:false,Add_Level:()=>{c.calls++;if(refused)c.g_goat_first_order_refused[dir===1?1:0]=true;return started;}};
 c.Seq_Buy=real;c.Seq_Sell=real;c.End_Sequence=d=>c.ends.push(d);
 vm.createContext(c);vm.runInContext('function promote(){'+js(PROMO)+'}',c);c.promote();return c;
}
{assert.deepEqual(promote({started:true}).ends,['Real Sequence Start'],'promoted: the virtual ends as in B49a');
 assert.deepEqual(promote({refused:true}).ends,['Gate at first order'],'refused at the first order: the candidate ends too');
 assert.deepEqual(promote({dir:1,refused:true}).ends,['Gate at first order']);
 assert.deepEqual(promote({mustCheck:false}).ends,[],'not promoted (MustCheck): the candidate waits, as in B49a');
 assert.deepEqual(promote({mustCheck:false,stale:true}).ends,[],'a refusal left from an earlier candidate is cleared first');
 const r=promote({refused:false,started:false});assert.deepEqual([r.ends,r.calls],[[],1],'a promotion the real sequence declined for its own reasons: B49a');
 ok();}

// 4. Where the refusal sits: inside the real-order branch, after every B49a add check, before the order.
{const LINE='      if(FirstOrderGatesRefused()) return false; // B49b (F5): Gate_Recheck, the first real order passes every start gate';
 assert.equal(ADD.split(LINE).length-1,1,'once');
 const branch=ADD.indexOf('     if(!Virtual && Level_Count>=MathAbs(Delay_Trade_Live))');
 const at=ADD.indexOf(LINE);
 assert.ok(branch>0 && at>branch,'in the real-order branch');
 assert.ok(at>ADD.indexOf('if(BiasRescueActive && LotsToBeSent>0.0 && !AllowBiasRescuePositiveAdd(LotsToBeSent)) return false;'),'after B49a\'s add checks');
 assert.ok(at<ADD.indexOf('bool has_real_order=') && at<ADD.indexOf('OpenPosition('),'before the order');
 assert.equal((main.match(/FirstOrderGatesRefused\(\)/g)||[]).length,2,'defined once, called once');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f5'}));
