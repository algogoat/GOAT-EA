// B49b PR-6 (F6: pre-trade checks that can fire; goatai#2587 6433828681, Claude-Mac 6433854745). The production
// functions run here from GOAT V1.49.mq5, side by side with B49a's OpenPosition spread line (source 693cad0):
// 1. GoatSpreadRefused: Max_Spread_Points 0 is B49a's fixed MaxSP check exactly; set, it replaces MaxSP (refuses above it,
//    allows at it), and logs at most once a minute, live only.
// 2. GoatMarginLevelRefused: Min_Margin_Level_PC 0 never refuses (B49a has no margin check). Set, it refuses an order whose
//    projected margin level, equity / (current margin + OrderCalcMargin of this order) x 100, would fall below it, allows
//    at it, refuses when the margin cannot be computed, and logs at most once a minute, live only.
// 3. Where they sit: OpenPosition's spread line is replaced by GoatSpreadRefused(); the margin check comes after the
//    requested volume and the below-minimum early return, and refuses with LastRetCode 741.
// 4. OnInit refuses Mode_Lots RiskperSeq with Max_Seq_Trades <= 1 (validate-set's RISK_PER_SEQUENCE_NEEDS_TWO_TRADES), right
//    after B49a's Risk<10 refusal. Ops' scan (10-27): 0 of 382 SETs we run have the pair.
// test_b49b_f6_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const mainB49a=clean(execFileSync('git',['show',B49A_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
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
const fmt=(f,...a)=>{let i=0;return f.replace(/%%|%(\.\d+)?([dfs])/g,(m,p,t)=>{if(m==='%%')return '%';const v=a[i++];return t==='f'?Number(v).toFixed(p?Number(p.slice(1)):6):String(v);});};   // printf, as MQL's StringFormat

function ctx({spread=20,maxSP=9999,maxSpread=0,minMargin=0,margin=0,equity=10000,need=500,calc=true,tester=false}={}){
 const c={MaxSP:maxSP,Max_Spread_Points:maxSpread,Min_Margin_Level_PC:minMargin,POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,ORDER_TYPE_BUY:0,ORDER_TYPE_SELL:1,
  SYMBOL_SPREAD:1,SYMBOL_ASK:2,SYMBOL_BID:3,ACCOUNT_MARGIN:4,ACCOUNT_EQUITY:5,MQL_TESTER:6,_Symbol:'EURUSD',now:1000,logs:[],calcs:[],
  g_goat_pretrade_logged:[0,0],Symbol:()=>'EURUSD',MathIsValidNumber:Number.isFinite,StringFormat:fmt};
 c.SymbolInfoInteger=(s,k)=>k===1?spread:0;c.SymbolInfoDouble=(s,k)=>k===2?1.1002:1.1000;
 c.AccountInfoDouble=k=>k===4?margin:equity;c.MQLInfoInteger=k=>k===6&&tester?1:0;c.TimeCurrent=()=>c.now;
 c.Print=(...a)=>c.logs.push(a.join(''));
 c.OrderCalcMargin=(type,sym,vol,price,_out)=>{c.calcs.push([type,vol,price]);c.__need=need;return calc;};
 vm.createContext(c);
 // OrderCalcMargin fills `need` by reference: modelled by reading __need after the call.
 const margin_fn=bodyOf(main,'bool GoatMarginLevelRefused(const int op,const double volume)')
  .replace(/!OrderCalcMargin\(([^;]*?),need\)/,'!(OrderCalcMargin($1,0)&&((need=__need),true))');
 vm.runInContext(fn('GoatPreTradeRefusal',['kind','text'],bodyOf(main,'void GoatPreTradeRefusal(const int kind,const string text)'))
  +fn('GoatSpreadRefused',[],bodyOf(main,'bool GoatSpreadRefused(void)'))+fn('GoatMarginLevelRefused',['op','volume'],margin_fn),c);
 return c;
}
// B49a's spread line, as a predicate: true = refused.
const b49aLine=mainB49a.split('\n').find(l=>l.includes('SYMBOL_SPREAD)>MaxSP) return 0;'));
assert.ok(b49aLine,'B49a has the fixed MaxSP line');
const b49aRefused=(spread,maxSP)=>spread>maxSP;

{// 1. Spread. Off: B49a exactly, for every spread around MaxSP.
 for(const maxSP of [9999,15])for(const spread of [0,14,15,16,9998,9999,10000]){
  const c=ctx({spread,maxSP});assert.equal(c.GoatSpreadRefused(),b49aRefused(spread,maxSP),'off '+spread+'/'+maxSP);assert.deepEqual(c.logs,[]);}
 // Set: replaces MaxSP (even a lower MaxSP), refuses above it, allows at it.
 for(const [spread,want] of [[29,false],[30,false],[31,true],[500,true]]){const c=ctx({spread,maxSpread:30,maxSP:9999});assert.equal(c.GoatSpreadRefused(),want,'set '+spread);}
 assert.equal(ctx({spread:20,maxSpread:30,maxSP:15}).GoatSpreadRefused(),false,'the input replaces MaxSP, never adds to it');
 // Logged once a minute, live only.
 {const c=ctx({spread:50,maxSpread:30});for(let s=0;s<120;s++){c.GoatSpreadRefused();c.now++;}
  assert.equal(c.logs.length,2);assert.match(c.logs[0],/^GOAT pre-trade: order refused: spread 50 > Max_Spread_Points 30 symbol=EURUSD$/);}
 {const c=ctx({spread:50,maxSpread:30,tester:true});c.GoatSpreadRefused();assert.deepEqual(c.logs,[],'never in the tester');}
 ok();}

{// 2. Margin. Off: never refuses, never computes.
 const off=ctx({minMargin:0,margin:9000,equity:100});assert.equal(off.GoatMarginLevelRefused(0,1),false);assert.deepEqual(off.calcs,[]);
 // Set: projected level = equity / (margin + need) x 100. 10000 / (1500+500) = 500%.
 for(const [floor,want] of [[499,false],[500,false],[501,true]]){const c=ctx({minMargin:floor,margin:1500,equity:10000,need:500});assert.equal(c.GoatMarginLevelRefused(0,0.5),want,'floor '+floor);}
 // No margin used and none needed: nothing to protect.
 assert.equal(ctx({minMargin:150,margin:0,need:0}).GoatMarginLevelRefused(1,0.1),false);
 // A buy prices at the ask, a sell at the bid, with the requested volume.
 {const b=ctx({minMargin:100});b.GoatMarginLevelRefused(0,0.37);assert.deepEqual(b.calcs[0],[0,0.37,1.1002]);
  const s=ctx({minMargin:100});s.GoatMarginLevelRefused(1,0.37);assert.deepEqual(s.calcs[0],[1,0.37,1.1]);}
 // The margin cannot be computed: refused (the floor is set), logged.
 {const c=ctx({minMargin:150,calc:false});assert.equal(c.GoatMarginLevelRefused(0,1),true);assert.match(c.logs[0],/its margin could not be computed/);}
 {const c=ctx({minMargin:150,need:NaN});assert.equal(c.GoatMarginLevelRefused(0,1),true,'a non-finite margin is refused');}
 // Logged once a minute, live only.
 {const c=ctx({minMargin:600,margin:1500,need:500});for(let s=0;s<120;s++){c.GoatMarginLevelRefused(0,1);c.now++;}
  assert.equal(c.logs.length,2);assert.match(c.logs[0],/^GOAT pre-trade: order refused: margin level after it 500\.0% < Min_Margin_Level_PC 600\.0% symbol=EURUSD$/);}
 {const c=ctx({minMargin:600,margin:1500,need:500,tester:true});assert.equal(c.GoatMarginLevelRefused(0,1),true);assert.deepEqual(c.logs,[],'never in the tester');}
 ok();}

{// 3. Where they sit in OpenPosition.
 const open=bodyOf(main,'int OpenPosition(int OP,int magic,double lots,double Level_SL,double Size_SL,double Size_TP,string desc,const bool guard_previously_traded)');
 const at=s=>{const i=open.indexOf(s);assert.ok(i>=0,'missing in OpenPosition: '+s);return i;};
 assert.equal(open.includes('SYMBOL_SPREAD)>MaxSP'),false,'the fixed MaxSP line is replaced');
 const spread=at('if(GoatSpreadRefused()) return 0;'),stop=at('if(StopOut_Flag)');
 const volume=at('double requestedVolume = GetNormalizedLots(Lots_Order);'),min=at('// 0 lots added successfully');
 const marginLine=at('if(GoatMarginLevelRefused(OP,requestedVolume)) {LastRetCode=741; return 0;}');
 const send=at('MqlTradeRequest request;');
 assert.ok(spread<stop,'the spread check stays first, where B49a had it');
 assert.ok(volume<marginLine && min<marginLine && marginLine<send,'the margin check runs on the requested volume, after the below-minimum return, before any request');
 ok();}

{// 4. OnInit refuses RiskperSeq with fewer than 2 sequence trades (new in B49b), right after B49a's Risk<10 refusal.
 const init=bodyOf(main,'int OnInit()').split('\n'),riskLine='if(Mode_Lots == RiskperSeq && Risk<10)';
 const at=init.findIndex(l=>l.includes(riskLine));assert.ok(at>=0,'the Risk<10 refusal is still in OnInit');
 const line=init[at+1].replace(/\/\/.*$/,'').trim(),m=/^if\((.*?)\) \{Alert\("([^"]*)"\); return INIT_PARAMETERS_INCORRECT;\}$/.exec(line);
 assert.ok(m,'the next OnInit line is the single-trade refusal: '+line);
 assert.equal(mainB49a.includes('Max_Seq_Trades<=1'),false,'B49a had no such refusal');
 const refused=new Function('Mode_Lots','Max_Seq_Trades','const FixedLots=0,ScaledLots=1,RiskperSeq=2;return '+m[1]+';');
 for(const [lots,trades,want] of [[2,1,true],[2,0,true],[2,-1,true],[2,2,false],[2,10,false],[0,1,false],[1,1,false]])
  assert.equal(refused(lots,trades),want,'Mode_Lots '+lots+', Max_Seq_Trades '+trades);
 assert.match(m[2],/^Initialization Failed: Risk per Sequence lot sizing needs at least 2 sequence trades/);
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f6',b49aCompared:true}));
