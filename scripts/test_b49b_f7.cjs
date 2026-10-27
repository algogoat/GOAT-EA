// B49b PR-1 (F7: money, volume, indicator handles and buffers; goatai#2587 6433828681, Claude-Mac 6433854745). The
// production functions run here from GOAT V1.49.mq5, side by side with B49a's (source 693cad0):
// 1. PriceValuePerPointPerLot over a symbol matrix (EX-04). Fix_MoneyVolume Off returns exactly B49a's value on every
//    path; On returns money per 1.0 price unit per lot on every fallback, which is what the fast path and every caller
//    use (B49a's fallbacks return money per tick or per point).
// 2. GetNormalizedLots, the order volume (EX-05/R9): Off is B49a's; On rounds to VOLUME_STEP and clamps to
//    VOLUME_MIN..VOLUME_MAX, never raising a size below the minimum.
// 3. UpdateRSI and UpdateCurrentSignals (SIG-02) with CopyBuffer modelled: on valid data (and on a failed copy over a
//    buffer that already holds every value read) B49b takes B49a's branch exactly; where B49a reads past an empty or
//    short buffer (MT5 removes the EA; modelled as an array that throws) B49b sets that signal NEUTRAL, logs once per
//    indicator and evaluates again once the indicator reads.
// 4. OnInit checks every enabled signal indicator's handle (SIG-01), as it checks ATR's.
// test_b49b_f7_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const mainB49a=clean(execFileSync('git',['show',B49A_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
// The pre-fix helper (a probe copy thrown away, then the caller's own copy; Codex GOAT-EA#270 P2), for the regression
// proof in section 3. Skipped on a mutated entrypoint run (GOAT_EA_MAIN), whose subject is the tree's own source.
const PROBE=process.env.GOAT_EA_MAIN?null:clean(execFileSync('git',['show','b5069ffe1b5411188d9431734a66f57d82df1db0:GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
function js(text){
 return text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
  .replace(/^\s*static\s+INTERVAL\s+\w+;\s*$/gm,'')                      // the samplers live in the context
  .replace(/\bstatic\s+(?=(?:string|bool|int|double)\b)/g,'')              // a function's own static: a local here
  .replace(/SymbolInfoString\((\w+),\s*(\w+),\s*(\w+)\)/g,'$3=SymInfoStr($1,$2)')   // by-reference output
  .replace(/\bENUM_\w+\s+(?=\w+\s*[=;])/g,'let ')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]\\s*=\\s*\\{([^}]*)\\};','g'),'let $1=[$2];')
  .replace(new RegExp('\\b'+TYPE+'\\s+(\\w+)\\[\\]','g'),'let $1=[]')
  .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
  .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
}
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const MathRound=v=>Math.sign(v)*Math.round(Math.abs(v));   // MQL: half away from zero
const NormalizeDouble=(v,d)=>Number(Number(v).toFixed(d));

// ---- 1. Money per price unit (EX-04) ----
// sym: tick value/size, point, calc mode, currencies, bid; rates: from->to multipliers for ConvertCurrencyAmount.
const SYMS={
 fast:   {tv:1,ts:0.00001,point:0.00001,calc:'fx',base:'EUR',quote:'USD',bid:1.1,truth:100000},
 noTick: {tv:1,ts:0,point:0.00001,calc:'fx',base:'EUR',quote:'USD',bid:1.1,truth:100000},           // tick value per point, no tick size
 fxQuote:{tv:0,ts:0.00001,point:0.00001,calc:'fx',base:'EUR',quote:'USD',bid:1.1,truth:100000},     // EURUSD on a USD account
 fxBase: {tv:0,ts:0.001,point:0.001,calc:'fx',base:'USD',quote:'JPY',bid:150,truth:100000/150},     // USDJPY on a USD account
 fxCross:{tv:0,ts:0.001,point:0.001,calc:'fx',base:'AUD',quote:'JPY',bid:98,truth:100000/150},      // AUDJPY: JPY->USD at 1/150
 index:  {tv:0,ts:0,point:0.01,calc:'cfd',base:'',quote:'USD',bid:20000,truth:1/0.01},             // nothing to go on: 1 per point
};
function moneyContext(sym,fix){
 const c={_Symbol:'X',_Point:sym.point,_Digits:5,Fix_MoneyVolume:fix,GoatFix_On:1,GoatFix_Off:0,logs:[],
  SYMBOL_POINT:'point',SYMBOL_TRADE_TICK_VALUE:'tv',SYMBOL_TRADE_TICK_SIZE:'ts',SYMBOL_TRADE_CONTRACT_SIZE:'contract',SYMBOL_BID:'bid',SYMBOL_ASK:'ask',
  SYMBOL_TRADE_CALC_MODE:'calc',SYMBOL_CALC_MODE_FOREX:'fx',SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE:'fxnl',SYMBOL_CURRENCY_BASE:'base',SYMBOL_CURRENCY_PROFIT:'quote',
  ACCOUNT_CURRENCY:'acc',AccountInfoString:()=>'USD',MathIsValidNumber:Number.isFinite,
  SymbolInfoDouble:(s,k)=>k==='contract'?100000:k==='ask'?sym.bid:sym[k],SymbolInfoInteger:(s,k)=>sym[k],SymInfoStr:(s,k)=>sym[k],
  ConvertCurrencyAmount:(amount,from,to)=>from==='JPY'&&to==='USD'?amount/150:0,
  DoubleToString:(v,d)=>Number(v).toFixed(d),Print:(...a)=>c.logs.push(a.join(''))};
 return c;
}
function money(text,sym,fix){
 const c=moneyContext(sym,fix);vm.createContext(c);
 vm.runInContext(fn('PriceValuePerPointPerLot',[],bodyOf(text,'   double PriceValuePerPointPerLot()')),c);
 return c.PriceValuePerPointPerLot();
}
{for(const [name,sym] of Object.entries(SYMS)){
  const b49a=money(mainB49a,sym,0),off=money(main,sym,0),on=money(main,sym,1);
  assert.equal(off,b49a,name+': Off is B49a\'s value');
  assert.ok(Math.abs(on-sym.truth)<=1e-9*sym.truth,name+': On is money per price unit ('+on+' vs '+sym.truth+')');
 }
 assert.equal(money(main,SYMS.fast,1),money(mainB49a,SYMS.fast,0),'the fast path is unchanged');
 // B49a's fallbacks are off by one point's worth: per tick or per point.
 for(const name of ['noTick','fxQuote','fxBase','fxCross','index'])
  assert.ok(Math.abs(money(mainB49a,SYMS[name],0)/SYMS[name].truth-SYMS[name].point)<1e-12,name+': B49a returns money per point');
 ok();}

// ---- 2. The order volume (EX-05/R9) ----
function lots(text,size,{vmin,step,vmax},fix){
 const c={Fix_MoneyVolume:fix,GoatFix_On:1,GoatFix_Off:0,Symbol:()=>'X',SYMBOL_VOLUME_MIN:'min',SYMBOL_VOLUME_MAX:'max',SYMBOL_VOLUME_STEP:'step',
  SymbolInfoDouble:(s,k)=>({min:vmin,max:vmax,step})[k],MathRound,MathFloor:Math.floor,MathAbs:Math.abs,NormalizeDouble};
 vm.createContext(c);
 const step_fn=text.includes('double GoatStepNormalizedLots(double size)')?fn('GoatStepNormalizedLots',['size'],bodyOf(text,'double GoatStepNormalizedLots(double size)')):'';
 vm.runInContext(step_fn+fn('GetNormalizedLots',['size'],bodyOf(text,'double GetNormalizedLots(double size)')),c);
 return c.GetNormalizedLots(size);
}
{const FX={vmin:0.01,step:0.01,vmax:100},CFD={vmin:0.1,step:0.01,vmax:50};
 const cases=[[FX,0.15],[FX,0.153],[FX,0.155],[FX,0.004],[FX,250],[CFD,0.15],[CFD,0.155],[CFD,0.13],[CFD,0.17],[CFD,60],[CFD,-0.15],[CFD,0.05],[CFD,49.996]];
 for(const [sym,size] of cases) assert.equal(lots(main,size,sym,0),lots(mainB49a,size,sym,0),'Off is B49a\'s volume for '+size);
 const on=(sym,size)=>lots(main,size,sym,1);
 assert.equal(on(FX,0.153),0.15);assert.equal(on(CFD,0.15),0.15,'min 0.10, step 0.01: 0.15 stays 0.15');
 assert.notEqual(lots(mainB49a,0.15,CFD,0),0.15,'B49a rounds it to a multiple of the minimum');
 // Claude-Mac GOAT-EA#270: a risk-solved lot never rounds UP past its risk; it floors to the step.
 assert.equal(on(FX,0.155),0.15,'0.155 floors to 0.15 (rounding would send 0.16)');assert.equal(on(CFD,0.155),0.15);
 assert.equal(on(CFD,0.13),0.13,'0.13/0.01 is 12.999... in binary: still 13 steps');assert.equal(on(CFD,0.17),0.17);
 assert.equal(on(FX,0.29),0.29);assert.equal(on(FX,0.57),0.57);assert.equal(on(FX,1.13),1.13);   // more values a bare floor would lose a step on
 assert.equal(on(CFD,60),50,'clamped to VOLUME_MAX');assert.equal(lots(mainB49a,60,CFD,0),60,'B49a sends 60 (a 10014 refusal)');
 assert.equal(on(FX,250),100);assert.equal(on(CFD,49.996),49.99,'floored, never rounded up');
 assert.equal(on(CFD,-0.155),-0.15,'sign kept, the size floors toward zero');
 assert.equal(on(CFD,0.05),0,'a size below the minimum is never raised to it');assert.equal(on(FX,0.004),0);
 assert.equal(on({vmin:0.1,step:0,vmax:50},0.27),0.2,'no step: the minimum is the step');
 ok();}

// ---- 3. Indicator buffers (SIG-02) ----
const OP={OP_BUY:0,OP_SELL:1,OP_NULL:-1,OP_BUYSELL:2};
const MODES={RSI_Disabled:0,RSI_OverBS:1,RSI_OverBSCross:2,RSI_OBSCEngulf:3,Trade_Disabled:0,Trade_Trend:1,Trade_Counter:2,Trade_Range:3,
 Trade_Trend_Range:4,Trade_Counter_Range:5,BB_Disabled:0,BB_Channel:1,BB_OverBS:2,BB_Trend:3,MAIN_LINE:0,PLUSDI_LINE:1,MINUSDI_LINE:2,
 BASE_LINE:0,UPPER_BAND:1,LOWER_BAND:2,PERIOD_CURRENT:0};
// MT5's dynamic series array: a read past its end is a critical error (the EA is removed).
const series=values=>new Proxy([...values],{get(a,p){if(typeof p==='string'&&/^\d+$/.test(p)&&Number(p)>=a.length)throw new Error('array out of range');return Reflect.get(a,p);}});
// feed: "handle:buffer" -> {n, values}: n<0 fails (the array untouched), else n values copied (the array resized to n).
function signals(text,{modes,feed,buffers={},closes=[1.1,1.09],opens=[1.095,1.1]}){
 const H={RSI:11,EMA:[21,22,23],ADX:31,BB:41,MACD:51,RSI2:61};
 const buf=name=>series(buffers[name]||[]);
 const c={...OP,...MODES,logs:[],copies:0,Symbol:()=>'X',_Symbol:'X',_Digits:5,FastSpeed_Flag:false,Buy_EN:true,Sell_EN:true,
  Seq_Buy:{Traded:false},Seq_Sell:{Traded:false},SetEdit:()=>{},PanelDialog:{},clr_Text:0,clr_Buy:0,clr_Sell:0,clr_Null:0,Font_Size:8,
  iClose:(s,tf,sh)=>closes[sh-1]??closes[0],iOpen:(s,tf,sh)=>opens[sh-1]??opens[0],NormalizeDouble,DoubleToString:(v,d)=>Number(v).toFixed(d),
  IntegerToString:v=>String(v),GetLastError:()=>4806,Print:(...a)=>c.logs.push(a.join('')),ArraySize:a=>a.length,
  RSI_TF:1,EMA_TF:1,ADX_TF:1,BB_TF:1,MACD_TF:1,RSI2_TF:1,RSI_Level:70,RSI2_Level:70,ADX_Level:25,EMA_Count:3,
  EMA_MustCheck:true,ADX_MustCheck:true,BB_MustCheck:true,MACD_MustCheck:true,RSI2_MustCheck:true,
  RSI_Sig:9,EMA_Sig:9,ADX_Sig:9,BB_Sig:9,MACD_Sig:9,RSI2_Sig:9,MustCheck_Buy:null,MustCheck_Sell:null,
  RSI_handle:H.RSI,EMA_handles:H.EMA,ADX_handle:H.ADX,BB_handle:H.BB,MACD_handle:H.MACD,RSI2_handle:H.RSI2,
  RSI_Buf:buf('RSI'),ADX_Main_Buf:buf('ADX0'),ADX_PLS_Buf:buf('ADX1'),ADX_MNS_Buf:buf('ADX2'),BB_Mi_Buf:buf('BB0'),BB_Hi_Buf:buf('BB1'),
  BB_Lo_Buf:buf('BB2'),MACD_Clr_Buf:buf('MACD'),RSI2_Buf:buf('RSI2'),EMAs:[0,1,2].map(i=>({Buf:buf('EMA'+i)})),
  g_goat_signal_short_logged:[false,false,false,false,false,false],
  EMA_Sample:{CheckTF:()=>true},ADX_Sample:{CheckTF:()=>true},BB_Sample:{CheckTF:()=>true},MACD_Sample:{CheckTF:()=>true},RSI2_Sample:{CheckTF:()=>true},
  CopyBuffer:(h,b,shift,count,arr)=>{c.copies++;let f=feed[h+':'+b]||{n:count,values:[]};
   if(f.seq){f.i=(f.i??-1)+1;f=f.seq[Math.min(f.i,f.seq.length-1)];}   // per-call results: a copy that succeeds, then one that fails
   if(f.n<0)return -1;
   const n=Math.min(f.n,count);arr.length=0;for(let i=0;i<n;i++)arr.push(f.values[i]??0);return n;},
  ...modes};
 vm.createContext(c);
 let code=fn('UpdateRSI',['shift'],bodyOf(text,'void UpdateRSI(int shift)'))+fn('UpdateCurrentSignals',['shift'],bodyOf(text,'void UpdateCurrentSignals(int shift)'));
 if(text.includes('// B49b:begin signal-ready'))
  code+=fn('GoatSignalBufferReady',['handle','buffer','shift','count','need','buf'],bodyOf(text,text.includes('const int need,double &buf[])')
   ?'bool GoatSignalBufferReady(const int handle,const int buffer,const int shift,const int count,const int need,double &buf[])'
   :'bool GoatSignalBufferReady(const int handle,const int buffer,const int shift,const int count,const int need,const double &buf[])'))   // the pre-#270-P2 probe (PROBE)
   +'function GoatSignalReady(id,name,ready){'+js(bodyOf(text,'bool GoatSignalReady(const int id,const string name,const bool ready,int &sig)')).replace(/\bsig=OP_NULL;/,'')+'}\n'
   +fn('GoatEmaBuffersReady',['shift'],bodyOf(text,'bool GoatEmaBuffersReady(const int shift)'));
 // GoatSignalReady's by-reference sig: the caller's signal is set NEUTRAL when the probe is not ready.
 code=code.replace(/GoatSignalReady\((\d),("\w+"),([\s\S]*?),(\w+_Sig)\)\)/g,(m,id,name,ready,sig)=>'(GoatSignalReady('+id+','+name+','+ready+')||(('+sig+'=OP_NULL),false)))');
 vm.runInContext(code,c);
 return c;
}
const H={RSI:11,EMA:[21,22,23],ADX:31,BB:41,MACD:51,RSI2:61};
function run(text,cfg){
 const c=signals(text,cfg);
 try{c.UpdateRSI(1);c.UpdateCurrentSignals(1);}catch(e){if(/array out of range/.test(e.message))return {crash:true,c};throw e;}
 const out={RSI:c.RSI_Sig,EMA:c.EMA_Sig,ADX:c.ADX_Sig,BB:c.BB_Sig,MACD:c.MACD_Sig,RSI2:c.RSI2_Sig,buy:c.MustCheck_Buy,sell:c.MustCheck_Sell};
 return {crash:false,out,c};
}
// A deterministic generator (no Math.random: the same cases every run).
let seed=20261027;const rnd=()=>((seed=(seed*1103515245+12345)%2147483648)/2147483648);
const pick=a=>a[Math.floor(rnd()*a.length)];
function randomCase(){
 const modes={RSI_Mode:pick([0,1,2,3]),EMA_Mode:pick([0,1,2,3,4,5]),ADX_Mode:pick([0,1,2,3,4,5]),BB_Mode:pick([0,1,2,3]),MACD_Mode:pick([0,1,2,3,4,5]),RSI2_Mode:pick([0,1,2,3])};
 const feed={},two=()=>[rnd()*100,rnd()*100],one=()=>[1+rnd()*0.02];
 feed[H.RSI+':0']={n:2,values:two()};feed[H.RSI2+':0']={n:2,values:two()};
 H.EMA.forEach(h=>feed[h+':0']={n:1,values:one()});
 feed[H.ADX+':0']={n:1,values:[rnd()*50]};feed[H.ADX+':1']={n:1,values:[rnd()*40]};feed[H.ADX+':2']={n:1,values:[rnd()*40]};
 feed[H.BB+':0']={n:2,values:[1.1,1.1]};feed[H.BB+':1']={n:2,values:[1.1+rnd()*0.02-0.01,0]};feed[H.BB+':2']={n:2,values:[1.09+rnd()*0.02-0.01,0]};
 feed[H.MACD+':1']={n:1,values:[pick([1,2,3,4])]};
 return {modes,feed,closes:[1.09+rnd()*0.02,1.1],opens:[1.1,1.09+rnd()*0.02]};
}
{// Valid data: 400 cases, every mode, identical signals and MustCheck flags.
 for(let i=0;i<400;i++){
  const cfg=randomCase(),a=run(mainB49a,cfg),b=run(main,cfg);
  assert.equal(a.crash,false);assert.deepEqual(b.out,a.out,'case '+i);assert.deepEqual(b.c.logs,[],'nothing logged on valid data');
 }
 ok();}
{// A failed copy over buffers that already hold every value read: B49a reuses them, and so does B49b.
 for(let i=0;i<200;i++){
  const cfg=randomCase();
  const stale={RSI:[30,40],RSI2:[75,60],EMA0:[1.1],EMA1:[1.09],EMA2:[1.08],ADX0:[30],ADX1:[25],ADX2:[10],BB0:[1.1,1],BB1:[1.12,1],BB2:[1.08,1],MACD:[3]};
  const failing={...cfg,buffers:stale,feed:Object.fromEntries(Object.keys(cfg.feed).map(k=>[k,{n:-1}]))};
  const a=run(mainB49a,failing),b=run(main,failing);
  assert.equal(a.crash,false);assert.deepEqual(b.out,a.out,'stale case '+i);
 }
 ok();}
{// Where B49a reads past an empty or short buffer, B49b's signal is NEUTRAL and nothing is read out of range.
 const all={RSI_Mode:2,EMA_Mode:1,ADX_Mode:1,BB_Mode:2,MACD_Mode:1,RSI2_Mode:3};
 const base=()=>{const cfg=randomCase();cfg.modes=all;return cfg;};
 const breaks=[
  ['RSI','RSI:0',{n:-1},'RSI'],['RSI','RSI:0',{n:1,values:[25]},'RSI'],              // empty; partial (a cross reads [1])
  ['EMA',H.EMA[1]+':0',{n:-1},'EMA'],['EMA',H.EMA[2]+':0',{n:-1},'EMA'],['ADX',H.ADX+':2',{n:-1},'ADX'],['BB',H.BB+':1',{n:-1},'BB'],['BB',H.BB+':0',{n:0},'BB'],
  ['MACD',H.MACD+':1',{n:-1},'MACD'],['RSI2',H.RSI2+':0',{n:1,values:[25]},'RSI2'],['RSI2',H.RSI2+':0',{n:-1},'RSI2'],
 ];
 const LOG_NAME={RSI:'RSI',EMA:'EMA',ADX:'ADX',BB:'BB',MACD:'MACD',RSI2:'RSI2'};
 for(const [label,key,f,sig] of breaks){
  const cfg=base();const k=key.startsWith('RSI:')?H.RSI+':0':key;cfg.feed[k]=f;
  assert.equal(run(mainB49a,cfg).crash,true,label+' '+JSON.stringify(f)+': B49a reads out of range');
  const b=run(main,cfg);assert.equal(b.crash,false,label+': B49b does not');
  assert.equal(b.out[sig],OP.OP_NULL,label+': NEUTRAL');
  assert.equal(b.c.logs.length,1,label+': one log line');assert.match(b.c.logs[0],new RegExp('^GOAT signals: '+LOG_NAME[sig]+' buffer not ready err=4806 symbol=X'));
  if(sig!=='RSI'){assert.equal(b.out.buy,false,label+': MustCheck blocks the buy');assert.equal(b.out.sell,false,label+': and the sell');}
 }
 // A partial RSI copy of one value is enough for OverBS (it reads [0] only): B49a and B49b agree.
 {const cfg=base();cfg.modes={...all,RSI_Mode:1};cfg.feed[H.RSI+':0']={n:1,values:[25]};
  const a=run(mainB49a,cfg),b=run(main,cfg);assert.equal(a.crash,false);assert.deepEqual(b.out,a.out);}
 // Logged once per indicator until it reads again; then re-armed.
 {const cfg=base();cfg.feed[H.ADX+':0']={n:-1};const b=signals(main,cfg);
  b.UpdateRSI(1);b.UpdateCurrentSignals(1);b.UpdateCurrentSignals(1);assert.equal(b.logs.length,1,'logged once');
  cfg.feed[H.ADX+':0']={n:1,values:[30]};b.UpdateCurrentSignals(1);assert.equal(b.g_goat_signal_short_logged[2],false,'re-armed');
  cfg.feed[H.ADX+':0']={n:-1};b.ADX_Main_Buf.length=0;b.UpdateCurrentSignals(1);assert.equal(b.logs.length,2,'logged again after a recovery');}
 ok();}
{// Codex GOAT-EA#270 P2: the check copies into the buffer the evaluation reads, once. A copy that succeeds and then a
 // copy that fails (same tick, an indicator recalculating) over an empty buffer: B49a copies once and reads the values;
 // B49b reads the same values. The pre-fix probe (PROBE, b5069ff) threw the first copy away, re-copied, and read out of
 // range: proof that this section sees the regression.
 const all={RSI_Mode:2,EMA_Mode:1,ADX_Mode:1,BB_Mode:2,MACD_Mode:1,RSI2_Mode:3};
 const flaky=(n,values)=>({seq:[{n,values},{n:-1}]});
 const cases=[['RSI',H.RSI+':0',flaky(2,[25,35])],['EMA',H.EMA[0]+':0',flaky(1,[1.1])],['ADX',H.ADX+':1',flaky(1,[30])],
  ['BB',H.BB+':2',flaky(2,[1.09,0])],['MACD',H.MACD+':1',flaky(1,[3])],['RSI2',H.RSI2+':0',flaky(2,[75,65])],
  ['RSI short',H.RSI+':0',{seq:[{n:2,values:[25,35]},{n:1,values:[25]}]}],['RSI2 short',H.RSI2+':0',{seq:[{n:2,values:[75,65]},{n:1,values:[75]}]}]];   // the second copy short (Mac 6438067335)
 let probeCrashes=0;
 for(const [label,key,f] of cases){
  const base=randomCase();base.modes=all;base.feed[key]=f;
  const mk=()=>JSON.parse(JSON.stringify(base));   // one case, a fresh copy (and fresh per-call results) for each source
  const a=run(mainB49a,mk()),b=run(main,mk());
  assert.equal(a.crash,false,label+': B49a copies once');assert.equal(b.crash,false,label+': B49b copies once too');
  assert.deepEqual(b.out,a.out,label+': the same signals as B49a');assert.deepEqual(b.c.logs,[],label+': nothing logged');
  if(PROBE&&run(PROBE,mk()).crash)probeCrashes++;
 }
 if(PROBE)assert.equal(probeCrashes,cases.length,'the pre-fix probe reads out of range in every case');
 // One copy per buffer per evaluation, as in B49a.
 {const cfg=randomCase();cfg.modes=all;const a=run(mainB49a,cfg),b=run(main,cfg);assert.equal(b.c.copies,a.c.copies,'B49a\'s copy count');}
 ok();}

// ---- 4. Every enabled signal indicator's handle is checked at OnInit (SIG-01) ----
{const INIT=bodyOf(main,'int OnInit()');
 const block=INIT.slice(INIT.indexOf('// B49b:begin signal-handles'),INIT.indexOf('// B49b:end signal-handles'));
 assert.ok(INIT.indexOf('RSI2_handle    = iRSI   (Symbol(),RSI2_TF,RSI2_Period,RSI2_Price);')<INIT.indexOf('// B49b:begin signal-handles'),'after every handle is created');
 for(const [mode,check] of [['RSI_Mode != RSI_Disabled','RSI_handle == INVALID_HANDLE'],['EMA_Mode != Trade_Disabled','EMA_handles[i] == INVALID_HANDLE'],
  ['ADX_Mode != Trade_Disabled','ADX_handle == INVALID_HANDLE'],['BB_Mode  != BB_Disabled','BB_handle == INVALID_HANDLE'],
  ['MACD_Mode!= Trade_Disabled','MACD_handle == INVALID_HANDLE'],['RSI2_Mode!= RSI_Disabled','RSI2_handle == INVALID_HANDLE']]){
  const line=block.split('\n').find(l=>l.includes(check));assert.ok(line,'checked: '+check);
  assert.ok(line.includes(mode),check+' only when enabled');assert.match(line,/return\(INIT_FAILED\);\}$/,check+' refuses');
 }
 assert.ok(block.includes('for(int i=0;i<EMA_Count;i++) if(EMA_handles[i] == INVALID_HANDLE)'),'every EMA of the ladder');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f7',b49aCompared:true}));
