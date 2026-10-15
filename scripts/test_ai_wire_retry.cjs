// B44: AI wire v2 retries quickly after a failed or unverified fetch (2026-10-12, goatai#2350). Exp 02's CADJPY
// child failed one fetch at 02:06:15Z (HTTP_NON_200 1003: a WebRequest timeout on a slow 200) and stayed
// unverified until 02:17Z, because an unverified state was retried only after the full Bias_RegenerateMinutes.
// Now: 30 s, 60 s, 120 s, ... doubling, capped at the normal refresh interval; a verified fetch resets it.
// Runs the production CGOATAIWireV2::GetState, CGOATAIWireV2::Refresh, Reset and GOATWireV2RetryDelayMs (plus
// the helpers they call) after a syntax-only MQL-to-JS conversion, against a modelled clock and server
// (WebRequest, ParseAndVerify and the auth header are stubs). Where git history is present, the B43 pin
// (606e54a9) runs the same timelines: a verified wire and the tester attempt at exactly the same instants.
// Source semantics only: no MetaEditor, MT5 or network.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const B43='606e54a9b4b8fa0c6c277b3b693a3aa340576f5c';
const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const read=f=>norm(fs.readFileSync(path.join(ROOT,f),'utf8'));
let passed=0;const check=fn=>{fn();passed++;};

// ---- Preprocess as V1.49 compiles (its #defines first), as test_bias_reader_parity.cjs does.
function preprocess(text,defined){
 const out=[],stack=[];let active=true;
 for(const line of text.split('\n')){
  const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
  if(m){
   if(m[1]==='ifdef'||m[1]==='ifndef'){const on=defined.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
   else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
   else active=stack.pop()[0];
   out.push('');continue;
  }
  const d=line.match(/^\s*#define\s+(\w+)/);
  if(d){if(active)defined.add(d[1]);out.push('');continue;}
  out.push(!active||/^\s*#/.test(line)?'':line);
 }
 return out.join('\n');
}
function stripComments(text){
 let out='',i=0,quote='';
 while(i<text.length){
  const c=text[i];
  if(quote){out+=c;if(c==='\\'){out+=text[i+1];i+=2;continue;}if(c===quote)quote='';i++;continue;}
  if(c==='"'||c==="'"){quote=c;out+=c;i++;continue;}
  if(c==='/'&&text[i+1]==='/'){while(i<text.length&&text[i]!=='\n')i++;continue;}
  if(c==='/'&&text[i+1]==='*'){const end=text.indexOf('*/',i+2);i=end<0?text.length:end+2;continue;}
  out+=c;i++;
 }
 return out;
}
function block(text,from){
 const brace=text.indexOf('{',from);let depth=1,end=brace+1,quote='';
 while(depth){
  assert.ok(end<text.length,'unbalanced block');
  const ch=text[end];
  if(quote){if(ch==='\\')end++;else if(ch===quote)quote='';}
  else if(ch==='"'||ch==="'")quote=ch;
  else if(ch==='{')depth++;
  else if(ch==='}')depth--;
  end++;
 }
 return [brace,end];
}
const TYPES='string|bool|int|uint|long|ulong|datetime|double|color|ushort|char';
function convert(body){
 body=body.replace(new RegExp('\\((?:'+TYPES+')\\)','g'),'');
 body=body.replace(/\bSGOATAIWireV2State\s+(\w+);/g,'let $1={};');
 body=body.replace(new RegExp('\\b(?:'+TYPES+')\\s+(\\w+)\\[\\];','g'),'let $1=[];');
 return body.replace(new RegExp('(^|[;{(]|\\n)(\\s*)(?:const\\s+)?(?:'+TYPES+')\\s+(?=[A-Za-z_])','g'),'$1$2let ');
}
function extract(text,name,{cls='',patch=b=>b}={}){
 const at=text.search(new RegExp('^[ \\t]*(?:bool|int|void|string|double|ulong)\\s+'+(cls?cls+'::':'')+name+'\\s*\\(','m'));
 assert.ok(at>=0,'missing production function '+name);
 const [brace,end]=block(text,at);
 const head=text.slice(at,brace);assert.equal(head.includes(';'),false,name+' is a definition');
 const params=head.slice(head.indexOf('(')+1,head.lastIndexOf(')')).trim();
 const names=!params||params==='void'?[]:params.split(',').map(p=>p.replace(/=.*/,'').trim().split(/[\s&]+/).pop());
 return 'function '+name+'('+names.join(',')+')'+convert(patch(text.slice(brace,end)))+'\n';
}
const once=(text,from,to,label)=>{assert.equal(text.split(from).length,2,'exactly one '+label);return text.replace(from,()=>to);};

// The wire as a given tree compiles it.
function wireCode(mainText,wireText){
 const defined=new Set([...mainText.matchAll(/^[ \t]*#define\s+(\w+)/gm)].map(m=>m[1]));
 const W=stripComments(preprocess(wireText,defined));
 const has=name=>new RegExp('^[ \\t]*(?:bool|int|void|string|double|ulong)\\s+'+name+'\\s*\\(','m').test(W);
 const parts=[extract(W,'GOATResetWireV2State'),extract(W,'GOATApplyWireV2DemoRawAuthority'),
  extract(W,'GOATFinalizeWireV2Actionability'),
  // authoritative_now is an output: the converted body writes it through a setter.
  'function GOATWireV2AuthoritativeNow(read_at_ms,verified_tick,now_tick,__set){let authoritative_now=0;const __r=(function()'
   +convert(W.slice(...block(W,W.indexOf('bool GOATWireV2AuthoritativeNow('))))+')();__set(authoritative_now);return __r;}\n',
  extract(W,'Reset'),
  extract(W,'GetState',{patch:b=>once(once(b,'state=m_state;','Object.assign(state,m_state);','state copy'),
   'GOATWireV2AuthoritativeNow(m_read_at_ms,m_verified_tick,now_tick,authoritative_now)','GOATWireV2AuthoritativeNow(m_read_at_ms,m_verified_tick,now_tick,v=>authoritative_now=v)','authoritative now')}),
  extract(W,'Refresh',{cls:'CGOATAIWireV2',patch:b=>b
   .replace(/GOATParseCanonicalIsoMs\(m_state\.(\w+),(\w+)\)/g,'GOATParseCanonicalIsoMs(m_state.$1,v=>$2=v)')
   .replace('m_state=parsed;','m_state=Object.assign({},parsed);')}),
  extract(W,'DetailLine')];
 if(has('GOATWireV2RetryDelayMs'))parts.push(extract(W,'GOATWireV2RetryDelayMs'));
 if(new RegExp('^[ \\t]*int\\s+GOATWireV2RetryJitterPermille\\s*\\(','m').test(W))parts.push(extract(W,'GOATWireV2RetryJitterPermille'));
 return {code:parts.join('\n'),W,defined};
}

// ---- A modelled terminal: a millisecond tick, a server that answers each request, and the EA's globals.
const CHART=133098787211876843n;
function terminal(code,{flags=[],minutes=10,server,chart=CHART}){
 const requests=[],refreshes=[];
 const c={ChartID:()=>chart,StringLen:s=>s.length,StringGetCharacter:(s,i)=>s.charCodeAt(i),MQL_TESTER:'tester',MQL_OPTIMIZATION:'optimization',MQL_FORWARD:'forward',MQLInfoInteger:k=>flags.includes(k)?1:0,
  ACCOUNT_TRADE_MODE:32,ACCOUNT_TRADE_MODE_DEMO:0,ACCOUNT_LOGIN:7,AccountInfoInteger:k=>k===7?123456:0,
  Bias_RegenerateMinutes:minutes,Bias_Protocol:1,BiasProtocol_ControlTowerV2:1,BiasProtocol_ControlTowerV2DemoRaw:2,Bias_threshold:60,
  Bias_V2_Win_Payoff_R:1,Bias_V2_Loss_Payoff_R:1,Bias_V2_Round_Trip_Cost_R:0.02,Bias_V2_Min_Expected_R:0,
  MathMax:Math.max,MathMin:Math.min,MathAbs:Math.abs,MathRound:x=>Math.sign(x)*Math.round(Math.abs(x)),IntegerToString:String,
  ConvertToGOATsymbol:s=>s,URL_API:'https://example.invalid',timeout:5000,CP_UTF8:65001,
  tick:1_000_000,GetTickCount64:()=>c.tick,Print(){},PrintFormat(){},ResetLastError(){},GetLastError:()=>5203,
  ArrayResize:(a,n)=>{a.length=n;return n;},CharArrayToString:a=>a.join(''),
  GOATBuildAuthenticatedRequestHeaders:()=>true,
  WebRequest:(method,url,headers,ms,body,result)=>{requests.push(c.tick);const r=server(c.tick,requests.length);result.push(JSON.stringify(r));return r.http;},
  ParseAndVerify:(json,asset,duration,state)=>{const r=JSON.parse(json);if(!r.ok)return false;
   c.GOATResetWireV2State(state,'');Object.assign(state,{verified:true,directive_available:true,availability:'AVAILABLE',direction:'BULLISH',
    decision_probability:0.7,read_at:'r',valid_until:'v',__read:r.readMs,__valid:r.validMs});return true;},
  GOATParseCanonicalIsoMs:(value,set)=>{set(value==='r'?c.m_state.__read:c.m_state.__valid);return true;},
  m_state:{},m_last_attempt_tick:0,m_verified_tick:0,m_read_at_ms:0,m_valid_until_ms:0,m_failed_fetches:0};
 vm.createContext(c);vm.runInContext(code,c);
 const refresh=c.Refresh;c.Refresh=a=>{refreshes.push(c.tick);return refresh(a);};
 c.Reset();
 // OnTick/OnTimer call GetState about once a second; run the wire for `seconds`.
 const run=seconds=>{const seen=[];for(let s=0;s<seconds;s++){const st={};const v=c.GetState('CADJPY',st);seen.push(v);c.tick+=1000;}return seen;};
 return {c,requests,refreshes,run,at:list=>list.map(t=>(t-1_000_000)/1000)};
}
// Server answers: ok (a fresh record valid for validFor seconds after it is read) or a failure.
const OK=(validFor=3900)=>tick=>({http:200,ok:true,readMs:1_760_000_000_000+tick,validMs:1_760_000_000_000+tick+validFor*1000});
const FAIL=code=>()=>({http:code,ok:false});
const script=(...steps)=>(tick,n)=>{const s=(tick-1_000_000)/1000;for(const [until,answer] of steps)if(s<until)return answer(tick,n);return steps[steps.length-1][1](tick,n);};

const mainText=read('GOAT V1.49.mq5'),wireText=read('GOATAIWireV2.mqh');
const now=wireCode(mainText,wireText);
let old=null,oldWireText=null;
try{
 const show=f=>norm(execFileSync('git',['show',B43+':'+f],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
 oldWireText=show('GOATAIWireV2.mqh');
 old=wireCode(show('GOAT V1.49.mq5'),oldWireText);
}catch(e){if(e instanceof assert.AssertionError)throw e;}

// The schedule a chart with jitter j (per mille) is expected to follow while every fetch fails, polled once a
// second: the k-th retry waits min(base_k + base_k*j/1000, refresh), base_k = 30 s * 2^(k-1).
const BASES=[30000,60000,120000,240000,480000,960000];
const expectedDelay=(k,j,refresh=600000)=>{const b=Math.min(30000*2**(k-1),2**31);return Math.min(b+b*Math.min(Math.max(j,0),999)/1000,refresh);};
function expectedFailTimes(j,count,refresh=600000,start=0){
 const at=[start];for(let k=1;at.length<count;k++)at.push(at[at.length-1]+Math.ceil(expectedDelay(Math.min(k,16),j,refresh)/1000));return at;
}
const JITTER=terminal(now.code,{server:FAIL(-1)}).c.GOATWireV2RetryJitterPermille(CHART);

// 1. The schedule itself. Jitter 0: 30 s, 60 s, 120 s, 240 s, 480 s, then the refresh interval. Any jitter: each
// step within [base, 2*base), monotone, capped at the refresh interval; never 0.
check(()=>{
 const t=terminal(now.code,{server:FAIL(-1)});
 const d=(n,j=0,r=600000)=>t.c.GOATWireV2RetryDelayMs(n,r,j);
 assert.deepEqual([0,1,2,3,4,5,6,7,16,1000].map(n=>d(n)),[600000,30000,60000,120000,240000,480000,600000,600000,600000,600000]);
 assert.deepEqual([0,1,2,3].map(n=>d(n,0,60000)),[60000,30000,60000,60000],'Bias_RegenerateMinutes=1: capped at 60 s');
 assert.deepEqual([1,2].map(n=>d(n,999,20000)),[20000,20000],'never above the refresh interval');
 for(let j=0;j<1000;j++){
  let prev=0;
  for(let n=1;n<=20;n++){
   const v=d(n,j),base=BASES[Math.min(n,6)-1];
   assert.ok(v>=prev,'monotone j='+j);prev=v;
   if(base<600000)assert.ok(v===600000||(v>=base&&v<2*base),'within [base,2*base) j='+j+' n='+n);
   assert.ok(v>0&&v<=600000);assert.equal(v,expectedDelay(n,j),'j='+j+' n='+n);
  }
  assert.equal(d(0,j),600000,'no failure: the normal interval');
 }
 assert.equal(d(1,-5),30000);assert.equal(d(1,5000),59970,'out-of-range jitter is clamped');
 // The jitter is a fixed per-chart value in [0,999], read from the chart id only.
 for(const id of [1n,71300508715022n,CHART]){const j=t.c.GOATWireV2RetryJitterPermille(id);assert.ok(Number.isInteger(j)&&j>=0&&j<=999);}
 const jit=now.W.slice(...block(now.W,now.W.search(/^[ \t]*int\s+GOATWireV2RetryJitterPermille\s*\(/m)));
 for(const banned of ['GetTickCount','MathRand','MathSrand','TimeLocal','TimeCurrent','TimeGMT','GetMicrosecondCount','ChartID'])assert.ok(!jit.includes(banned),banned);
 // The self-test carries the same numbers: every pin it checks holds here.
 const selfTest=now.W.slice(...block(now.W,now.W.indexOf('bool SelfTest()')));
 const pins=[...selfTest.matchAll(/GOATWireV2RetryDelayMs\((\d+),(\d+),(\d+)\)!=(\d+)/g)];
 assert.ok(pins.length>=12,'SelfTest checks the retry schedule');
 for(const [,a,b,j,want] of pins)assert.equal(d(+a,+j,+b),+want,'SelfTest pin '+a+','+b+','+j);
 const jpins=[...selfTest.matchAll(/GOATWireV2RetryJitterPermille\((\d+)\)!=(\d+)/g)];
 assert.equal(jpins.length,3);
 for(const [,id,want] of jpins)assert.equal(t.c.GOATWireV2RetryJitterPermille(BigInt(id)),+want,'SelfTest jitter pin '+id);
});

// 2. The 2026-10-12 incident: a verified wire, one failed refresh (HTTP 1003), the server healthy again 1 s later.
// B44 is verified again 30-60 s after the failure (this chart's jitter); B43 stayed unverified until the next
// 10-minute refresh.
const incident=script([600,OK()],[601,FAIL(1003)],[Infinity,OK()]);
check(()=>{
 const t=terminal(now.code,{server:incident});const seen=t.run(1900);
 const r1=Math.ceil(expectedDelay(1,JITTER)/1000);assert.ok(r1>=30&&r1<=60);
 assert.deepEqual(t.at(t.requests),[0,600,600+r1,1200+r1,1800+r1].filter(s=>s<1900),'retry 30 s + jitter after the failure, then the normal 600 s cadence');
 assert.equal(seen.filter(v=>!v).length,r1,'unverified for '+r1+' s, not 600 s');
 assert.equal(t.c.m_failed_fetches,0,'a verified fetch resets the backoff');
 if(old){const o=terminal(old.code,{server:incident});const s=o.run(1900);
  assert.deepEqual(o.at(o.requests),[0,600,1200,1800],'B43: the retry waited the full interval');assert.equal(s.filter(v=>!v).length,600);}
});

// 3. A long outage: the jittered doubling schedule, then every 600 s; recovery resets; a later failure starts at
// the first step again.
check(()=>{
 let oks=0,failedOnce=false;
 const server=(tick,n)=>{const s=(tick-1_000_000)/1000;if(s<3000)return FAIL(-1)();
  if(oks===1&&!failedOnce){failedOnce=true;return FAIL(1003)();}oks++;return OK()(tick);};
 const t=terminal(now.code,{server});t.run(6000);
 const at=t.at(t.requests),outage=at.filter(s=>s<3000);
 assert.deepEqual(outage,expectedFailTimes(JITTER,outage.length),'jittered doubling backoff, capped at the 600 s refresh');
 assert.ok(outage.length>=7);
 const r=at[outage.length],r1=Math.ceil(expectedDelay(1,JITTER)/1000);
 assert.deepEqual(at.slice(outage.length,outage.length+5),[r,r+600,r+600+r1,r+1200+r1,r+1800+r1],
  'the first fetch after recovery is verified; the next refresh fails and retries at the first step again');
 // DetailLine while unverified is unchanged.
 const st={};t.c.GOATResetWireV2State(st,'HTTP_NON_200');assert.equal(t.c.DetailLine(st),'Retrying automatically');
});

// 4. Verified wire: identical to B43 at every instant (no early refresh, refresh at Bias_RegenerateMinutes or at
// validUntil, whichever first; the tick wrap still forces a refresh).
check(()=>{
 for(const [label,server,minutes,expect] of [
  ['long validity',OK(),10,[0,600,1200,1800,2400,3000,3600]],
  ['short validity',OK(65),10,[0,65,130,195,260,325,390]],
  ['1-minute regenerate',OK(),1,null]]){
  const t=terminal(now.code,{server,minutes});t.run(3700);
  if(expect)assert.deepEqual(t.at(t.requests).slice(0,7),expect,label);
  assert.equal(t.c.m_failed_fetches,0,label);
  if(old){const o=terminal(old.code,{server,minutes});o.run(3700);assert.deepEqual(t.requests,o.requests,'same instants as B43: '+label);}
 }
 const t=terminal(now.code,{server:OK()});t.run(10);t.c.tick=t.c.m_last_attempt_tick-1000;const before=t.requests.length;t.run(1);
 assert.equal(t.requests.length,before+1,'a tick that went backwards refreshes');
});

// 5. Tester, optimization and forward: Refresh never requests, and GetState calls it exactly as B43 did (every
// Bias_RegenerateMinutes): the backoff counts live fetches only.
check(()=>{
 for(const flags of [['tester'],['tester','optimization'],['tester','forward']]){
  const t=terminal(now.code,{flags,server:()=>assert.fail('the tester never requests')});const seen=t.run(1900);
  assert.deepEqual(t.requests,[]);assert.ok(seen.every(v=>!v));
  assert.deepEqual(t.at(t.refreshes),[0,600,1200,1800],JSON.stringify(flags));assert.equal(t.c.m_failed_fetches,0);
  assert.equal(t.c.m_state.reason_code,'LIVE_WIRE_UNAVAILABLE_IN_TESTER');
  if(old){const o=terminal(old.code,{flags,server:()=>assert.fail()});o.run(1900);assert.deepEqual(o.refreshes,t.refreshes,'same as B43: '+flags);}
 }
});

// 6. Every live failure kind backs off the same way, including a missing auth token (no request at all) and a
// 200 whose body does not verify; Reset() clears the backoff.
check(()=>{
 const five=expectedFailTimes(JITTER,5);
 for(const server of [FAIL(-1),FAIL(1003),FAIL(500),()=>({http:200,ok:false})]){
  const t=terminal(now.code,{server});t.run(five[4]+1);assert.deepEqual(t.at(t.requests),five);
 }
 const t=terminal(now.code,{server:FAIL(-1)});t.c.GOATBuildAuthenticatedRequestHeaders=()=>false;t.run(five[4]+1);
 assert.deepEqual(t.requests,[]);assert.deepEqual(t.at(t.refreshes),five,'no token: retried on the same schedule');
 assert.equal(t.c.m_state.reason_code,'AUTH_TOKEN_UNAVAILABLE');
 t.c.Reset();assert.equal(t.c.m_failed_fetches,0);assert.equal(t.c.m_last_attempt_tick,0);
 const capped=terminal(now.code,{server:FAIL(-1)});capped.run(20000);assert.equal(capped.c.m_failed_fetches,16,'the counter is bounded');
});

// 7. No lockstep: 280 charts (35 on each of 8 terminals) fail at the same instant (serveApi slow or down).
// Through the first six retry steps no wall-clock second holds more than 10% of that step's retries. Two id sets:
// realistic random 18-digit MT5 chart ids, and ids opened one after another (consecutive per terminal).
const lockstep={};
check(()=>{
 let seed=0x2026_1012n;
 const nextId=()=>{seed=(seed*6364136223846793005n+1442695040888963407n)&((1n<<64n)-1n);return 128000000000000000n+(seed%(10n**17n));};
 const sets={random:Array.from({length:280},nextId),
  consecutive:Array.from({length:280},(_,i)=>133098787211876000n+BigInt(Math.floor(i/35))*1000000n+BigInt(i%35))};
 for(const [name,ids] of Object.entries(sets)){
  assert.equal(new Set(ids).size,280);
  const steps=Array.from({length:6},()=>[]);
  for(const chart of ids){
   const t=terminal(now.code,{server:FAIL(-1),chart});t.run(2500);
   const at=t.at(t.requests);
   for(let k=1;k<=6;k++)steps[k-1].push(at[k]);
   assert.deepEqual(at.slice(0,7),expectedFailTimes(t.c.GOATWireV2RetryJitterPermille(chart),7),'chart '+chart);
  }
  lockstep[name]=steps.map((times,k)=>{
   assert.ok(times.every(Number.isFinite),'every chart reached retry '+(k+1));
   const perSecond=new Map();for(const s of times)perSecond.set(s,(perSecond.get(s)||0)+1);
   const max=Math.max(...perSecond.values()),share=max/times.length;
   assert.ok(share<=0.10,name+' retry '+(k+1)+': '+max+' of '+times.length+' in one second ('+(100*share).toFixed(1)+'%)');
   return +(100*share).toFixed(1);
  });
  // Without jitter, every chart would hit the same second at every step (100%).
  const flat=new Set(ids.map(()=>expectedFailTimes(0,7)[3]));assert.equal(flat.size,1);
 }
 console.log('  max share of one wall-clock second per retry step (%), steps 1-6: '+JSON.stringify(lockstep));
});

// 8. The same chart id always gives the same schedule: on another terminal instance, after Reset(), and in a
// second outage; another id gives its own.
check(()=>{
 const times=chart=>{const t=terminal(now.code,{server:FAIL(-1),chart});t.run(2000);return t.requests;};
 const a=times(CHART);assert.deepEqual(times(CHART),a);
 const t=terminal(now.code,{server:FAIL(-1)});t.run(2000);t.c.Reset();const first=t.requests.length;t.run(2000);
 const second=t.requests.slice(first).map(x=>x-t.requests[first]),again=a.map(x=>x-a[0]).filter(x=>x<2000);
 assert.deepEqual(second.slice(0,again.length),again,'same schedule after Reset()');
 assert.equal(terminal(now.code,{server:FAIL(-1)}).c.GOATWireV2RetryJitterPermille(CHART),JITTER);
 assert.notDeepEqual(times(71300508715022n),a);
});

// 9. Source pins: the interval expression and the verified checks are B43's; only the wait for an unverified
// state and the counter are new; no input was added.
check(()=>{
 const get=now.W.slice(...block(now.W,now.W.search(/^[ \t]*bool\s+GetState\s*\(/m)));
 assert.ok(get.includes('ulong refresh_ms=(ulong)MathMax(1,Bias_RegenerateMinutes)*60000;'));
 assert.ok(/ulong wait_ms=\(m_state\.verified \|\| m_failed_fetches<=0 \? refresh_ms\s*: GOATWireV2RetryDelayMs\(m_failed_fetches,refresh_ms,GOATWireV2RetryJitterPermille\(ChartID\(\)\)\)\);/.test(get));
 assert.ok(get.includes('|| authoritative_now>=m_valid_until_ms) refresh=true;'));
 assert.ok(/else if\(!MQLInfoInteger\(MQL_TESTER\) && !MQLInfoInteger\(MQL_OPTIMIZATION\) && !MQLInfoInteger\(MQL_FORWARD\)\s*&& m_failed_fetches<16\) m_failed_fetches\+\+;/.test(get));
 const inputs=t=>(t.match(/^\s*s?input\b[^\n]*/gm)||[]).map(l=>l.trim());
 if(oldWireText)assert.deepEqual(inputs(wireText),inputs(oldWireText),'no input added, removed or changed');
 assert.ok(!/input[^\n]*(?:Retry|Backoff)/i.test(wireText));
 for(const text of ['"Retrying automatically"','"AI bias temporarily unavailable"'])assert.ok(wireText.includes(text));
});

console.log(JSON.stringify({passed,test:'ai_wire_retry',b43Compared:!!old}));
