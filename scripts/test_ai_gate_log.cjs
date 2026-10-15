// B44 item 4 (goatai#2350): the AI gate log. One Print-only line per bias decision on a new entry signal:
//   GOAT AI gate v1: decision=VETO|ALLOW side magic symbol direction probability cutoff authority availability
//                    reason code wire_read_at mode protocol
// VETO at the signal-onset sites that count Sequence_Skipped_Bias_*, ALLOW where the signal starts a sequence.
// This runs the production SignalEntryTrigger, GoatGateLog and GoatGateActiveMask after a syntax-only MQL-to-JS
// conversion against modelled sequences, and proves the trading decisions (every Add_Level call and counter) equal
// the B43 function's on the same inputs. Native Print and the wire itself are not exercised here.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=norm(fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const B43_SOURCE='c708cae4';   // codex/v148-research-planning when B44 was cut (B43 entrypoint plus #221-#225, none in this unit)
let passed=0;const ok=()=>passed++;

function unit(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);assert.equal(text.indexOf(signature,a+1),-1,'one '+signature);
 let i=text.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<text.length;j++){if(text[j]==='{')depth++;if(text[j]==='}')depth--;}
 return text.slice(a,j);
}
const body=u=>u.slice(u.indexOf('{')+1,u.lastIndexOf('}'));
function js(text){
 return text.replace(/\/\/.*$/gm,'').replace(/^\s*static bool LastBuySignal=false,LastSellSignal=false;$/m,'')
  .replace(/\b(?:const )?(?:string|int|bool|double) (?=\w+\s*=)/g,'let ')
  .replace(/\bbool gate_read=/g,'let gate_read=');
}
const SIGNAL=unit(main,'void SignalEntryTrigger()');
const LOG=unit(main,'void GoatGateLog(const string gate_decision,const int gate_side)');
const MASK=unit(main,'int GoatGateActiveMask(void)');

function seq(name,calls,{fail=false}={}){
 return {name,Active:false,Traded:false,Add_Level(price){calls.push(name+'@'+price);if(!fail)this.Active=this.Traded=true;return !fail;}};
}
const ENUMS={Bias_Disabled:0,Bias_Display:1,Bias_Opens:2,Bias_Close_low:3};
function model(source=SIGNAL,{tester=false,state=null,v2=true,mode='Bias_Opens',reverse=false,fail=false}={}){
 const calls=[],prints=[];
 const c={OP_BUY:0,OP_SELL:1,OP_BUYSELL:2,RSI_Disabled:0,Trade_Disabled:0,BB_Disabled:0,Long_and_Short:0,Long:1,Short:2,
  RSI_Mode:0,EMA_Mode:0,ADX_Mode:0,BB_Mode:0,MACD_Mode:0,RSI2_Mode:0,RSI_Sig:0,EMA_Sig:0,ADX_Sig:0,BB_Sig:0,MACD_Sig:0,RSI2_Sig:0,
  Sequence_New_News:true,Sequence_New_Bias_B:true,Sequence_New_Bias_S:true,Sequence_Skipped_News:0,Sequence_Skipped_Bias_B:0,Sequence_Skipped_Bias_S:0,
  Reverse_Seq:reverse,Mode_Trade:0,Delay_Trade:0,Allow_Opposite_Seq:true,bid:1.1,ask:1.2,MAGIC1:1342177,LastBuySignal:false,LastSellSignal:false,
  DashboardEntryAllowed:()=>true,MathAbs:Math.abs,...ENUMS,Mode_Bias:ENUMS[mode],Bias_Protocol:102,
  EnumToString:v=>v===c.Bias_Protocol?'BiasProtocol_ControlTowerV2DemoRaw':v===c.Mode_Bias?mode:String(v),
  GOATUsingControlTowerBias:()=>v2,MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,MQLInfoInteger:k=>(k===1&&tester)?1:0,
  IntegerToString:String,DoubleToString:(v,d)=>Number(v).toFixed(d),Symbol:()=>'EURUSD',Print:s=>prints.push(s),
  g_GoatGateStateRead:!!state,g_GoatGateState:state||{}};
 c.Seq_Buy=seq('Buy',calls,{fail});c.Seq_Sell=seq('Sell',calls,{fail});c.Seq_Buy_Virtual=seq('BuyV',calls,{fail});c.Seq_Sell_Virtual=seq('SellV',calls,{fail});
 vm.createContext(c);
 if(source===SIGNAL){
  vm.runInContext('function GoatGateActiveMask(){'+js(body(MASK))+'}',c);
  vm.runInContext('function GoatGateLog(gate_decision,gate_side){'+js(body(LOG))+'}',c);
 }
 const tick=vm.runInContext('(function(){'+js(body(source))+'})',c);
 const signal=side=>{c.RSI_Sig=side==='buy'?0:side==='sell'?1:-1;c.RSI_Mode=side?1:0;if(!side){c.RSI_Mode=1;c.RSI_Sig=-1;}};
 return {c,calls,prints,tick,signal};
}
const DEMO={verified:true,directive_available:true,actionable:false,direction:'BULLISH',decision_probability:0.58,probability_cutoff:0.6,
 probability_authority:'MODEL_REPORTED_DEMO_RAW',availability:'WITHHELD',reason_code:'CALIBRATION_ARTIFACT_UNAVAILABLE',read_at:'2026-10-12T14:00:01.000Z'};
const fields=line=>Object.fromEntries(line.replace('GOAT AI gate v1: ','').split(' ').map(kv=>kv.split('=')));

// 1) VETO once per signal onset, with every field, in the reviewer's order.
{const m=model(SIGNAL,{state:DEMO});m.c.Sequence_New_Bias_B=false;m.signal('buy');
 m.tick();m.tick();m.tick();
 assert.equal(m.prints.length,1,'one line per onset, not per tick');assert.equal(m.c.Sequence_Skipped_Bias_B,1);
 assert.equal(m.prints[0],'GOAT AI gate v1: decision=VETO side=BUY magic=1342177 symbol=EURUSD direction=BULLISH probability=0.5800 cutoff=0.6000 '
  +'authority=MODEL_REPORTED_DEMO_RAW availability=WITHHELD reason=below_cutoff code=CALIBRATION_ARTIFACT_UNAVAILABLE '
  +'wire_read_at=2026-10-12T14:00:01.000Z mode=Bias_Opens protocol=BiasProtocol_ControlTowerV2DemoRaw');
 assert.deepEqual(Object.keys(fields(m.prints[0])),['decision','side','magic','symbol','direction','probability','cutoff','authority','availability','reason','code','wire_read_at','mode','protocol']);
 m.signal(null);m.tick();m.signal('buy');m.tick();assert.equal(m.prints.length,2,'a new onset logs again');ok();}
// 2) ALLOW where the signal starts a sequence; nothing while it stays active, nothing when the start fails.
{const m=model(SIGNAL,{state:{...DEMO,actionable:true,decision_probability:0.72}});m.signal('sell');m.tick();m.tick();
 assert.deepEqual(m.calls,['Sell@1.1']);assert.equal(m.prints.length,1);
 assert.deepEqual([fields(m.prints[0]).decision,fields(m.prints[0]).side,fields(m.prints[0]).reason],['ALLOW','SELL','actionable']);
 const f=model(SIGNAL,{state:DEMO,fail:true});f.signal('buy');f.tick();assert.deepEqual([f.calls,f.prints],[['Buy@1.2'],[]],'a refused start is not an ALLOW');ok();}
// 3) Reverse_Seq: a buy signal starts the sell sequence; the line names the signal side the bias judged.
{const m=model(SIGNAL,{state:{...DEMO,actionable:true},reverse:true});m.signal('buy');m.tick();
 assert.deepEqual(m.calls,['Sell@1.1']);assert.equal(fields(m.prints[0]).side,'BUY');ok();}
// 4) Reasons: every state the gate can see.
for(const [label,opts,decision,reason] of [
 ['unverified',{state:{...DEMO,verified:false}},'VETO','unverified'],['withheld',{state:{...DEMO,directive_available:false}},'VETO','withheld'],
 ['neutral',{state:{...DEMO,direction:'NEUTRAL'}},'VETO','neutral'],['actionable but vetoed by the mode rule',{state:{...DEMO,actionable:true}},'VETO','bias_rule'],
 ['not read',{state:null},'VETO','not_read'],['legacy',{state:null,v2:false},'VETO','legacy_score'],['filter off',{state:DEMO,mode:'Bias_Display'},'ALLOW','filter_off']]){
 const m=model(SIGNAL,opts);if(decision==='VETO') m.c.Sequence_New_Bias_B=false;m.signal('buy');m.tick();
 const f=fields(m.prints[0]);assert.deepEqual([f.decision,f.reason],[decision,reason],label);
 if(!opts.state) assert.deepEqual([f.direction,f.probability,f.cutoff,f.authority,f.availability,f.code,f.wire_read_at],Array(7).fill('NONE'),label);ok();
}
// 5) Never in the tester, optimization or forward run; the decisions there are unchanged.
{const m=model(SIGNAL,{state:DEMO,tester:true});m.c.Sequence_New_Bias_B=false;m.signal('buy');m.tick();m.c.Sequence_New_Bias_B=true;m.signal(null);m.tick();m.signal('buy');m.tick();
 assert.deepEqual(m.prints,[]);assert.deepEqual([m.c.Sequence_Skipped_Bias_B,m.calls],[1,['Buy@1.2']]);ok();}
// 6) Trading unchanged: against the B43 function on the same random input stream, every Add_Level call and counter agree.
let b43Signal=null;
try{b43Signal=unit(norm(execFileSync('git',['show',B43_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8')),'void SignalEntryTrigger()');}catch(e){}
{const stripped=SIGNAL.split('\n').filter(l=>!/int gate_active_[bs]=GoatGateActiveMask\(\);|GoatGateLog\("ALLOW"/.test(l)).join('\n')
  .replace(/\{(Sequence_Skipped_Bias_[BS])\+\+; GoatGateLog\("VETO",OP_(?:BUY|SELL)\);\} \/\/ B44 item 4: log only/g,'$1++;');
 if(b43Signal){assert.equal(stripped,b43Signal,'SignalEntryTrigger is B43 plus the log lines only');ok();}
 let seed=20261012;const rnd=()=>(seed=(seed*48271)%2147483647)/2147483647;
 const reference=b43Signal||stripped;
 for(const reverse of [false,true]) for(const fail of [false,true]){
  const now=model(SIGNAL,{state:DEMO,reverse,fail}),old=model(reference,{reverse,fail});
  for(let t=0;t<4000;t++){
   const side=rnd()<0.45?'buy':rnd()<0.8?'sell':null,news=rnd()<0.9,bb=rnd()<0.5,bs=rnd()<0.5,close=rnd()<0.05;
   for(const m of [now,old]){m.signal(side);m.c.Sequence_New_News=news;m.c.Sequence_New_Bias_B=bb;m.c.Sequence_New_Bias_S=bs;
    if(close) for(const s of ['Seq_Buy','Seq_Sell','Seq_Buy_Virtual','Seq_Sell_Virtual']) m.c[s].Active=false;m.tick();}
  }
  assert.deepEqual(now.calls,old.calls,'same Add_Level calls');
  for(const k of ['Sequence_Skipped_News','Sequence_Skipped_Bias_B','Sequence_Skipped_Bias_S']) assert.equal(now.c[k],old.c[k],k);
  assert.ok(now.prints.length>0 && old.prints.length===0);ok();
 }
}
// 7) The fields are the wire state after the demo-raw rewrite: copied right after GetState, which applies it.
{assert.match(main,/control_tower_verified=GOATBiasWireV2\.GetState\(Symbol\(\),control_tower_state\);\n          g_GoatGateState=control_tower_state; g_GoatGateStateRead=true;/);
 assert.equal((main.match(/^ +g_GoatGateStateRead=false;/gm)||[]).length,1,'reset once per bias evaluation');
 assert.equal((main.match(/GoatGateLog\("/g)||[]).length,4,'two VETO and two ALLOW sites');
 const wire=norm(fs.readFileSync(path.join(ROOT,'GOATAIWireV2.mqh'),'utf8'));
 const get=unit(wire,'bool GetState(string asset,SGOATAIWireV2State &state)');
 assert.ok(get.indexOf('GOATApplyWireV2DemoRawAuthority(state,demo_raw_enabled);')<get.indexOf('return state.verified;'));ok();}
console.log(JSON.stringify({passed,b43UnitCompared:!!b43Signal,nativePrint:false}));
