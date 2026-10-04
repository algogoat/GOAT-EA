// AI bias: tester == live at every Bias_threshold (BR41, GOAT_RECORDED_BIAS_LIVE_GATE_V149,
// goatai#1885). The same wire timeline goes down both V1.49 decision paths:
//   live:   the current record (valid for 65 minutes after publishing, superseded by the next
//           publish), through CGOATAIWireV2::GetState (demo-raw authority, then
//           GOATFinalizeWireV2Actionability at the run's Bias_threshold) and the OnTick bias block;
//   tester: the timeline as goatai's export writes it to Common\Files\<Key>\BiasFiles\
//           GOAT_AI_Bias_<SYM>.csv (Time,Asset,SentimentScore; -999 when dark, and an explicit -999
//           row at validUntil when no publish came first), read by GOATBiasHistory::
//           LoadBacktestFileAndFillBias and GetCurentBiasScore, then the same block.
// Every decision the block makes (CurBias, Sequence_New/Pause_Bias_B/S, StopOut_Flag_B/S and the
// dashboard bias) must match at N = -10, 0, 1, 20, 40, 59, 60, 61, 80, 99, 100 and 150, in every
// bias mode and restriction, for both protocols, in the tester, optimization and forward contexts,
// at publishes, inside long gaps and on both sides of every expiry.
// Runs the production MQL translated to JS in a VM: no MetaEditor, MT5 or network. Source
// semantics only, not native proof. GOAT_EA_ROOT may point at another source tree
// (test_bias_reader_parity_mutations.cjs runs every guard mutation through this file).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const mainSource=read('GOAT V1.49.mq5'),inputsSource=read('GOAT_Inputs_Definitions.mqh');
const biasSource=read('NewsBiasFilter.mqh'),wireSource=read('GOATAIWireV2.mqh');
let checks=0;const check=fn=>{fn();checks++;};

// ---- Preprocess as V1.49 compiles: its own #defines, then each header's, in include order.
const DEFINED=new Set([...mainSource.matchAll(/^[ \t]*#define\s+(\w+)/gm)].map(m=>m[1]));
const MACROS={};
function preprocess(text){
  const out=[],stack=[];let active=true;
  for(const line of text.split('\n')){
    const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
    if(m){
      if(m[1]==='ifdef'||m[1]==='ifndef'){const on=DEFINED.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
      else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
      else active=stack.pop()[0];
      out.push('');continue;
    }
    const d=line.match(/^\s*#define\s+(\w+)\s*(.*?)\s*$/);
    if(d){if(active){DEFINED.add(d[1]);MACROS[d[1]]=d[2];}out.push('');continue;}
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
const I=stripComments(preprocess(inputsSource)),B=stripComments(preprocess(biasSource)),W=stripComments(preprocess(wireSource));
const M=stripComments(preprocess(mainSource));

// ---- MQL -> JS for the exact production functions under test.
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
const TYPES='string|bool|int|uint|long|ulong|datetime|double|color|ushort';
function convert(body,statics){
  body=body.replace(/\bBIAS_FILE\b/g,MACROS.BIAS_FILE);
  // MQL statics keep their value across calls: they move to the function's closure.
  body=body.replace(new RegExp('\\bstatic\\s+(?:'+TYPES+')\\s+(\\w+)\\s*=\\s*([^;]+);','g'),(_,n,v)=>{statics.push('let '+n+'='+v+';');return '';});
  body=body.replace(/'(\\.|[^'\\])'/g,(_,ch)=>String(({'\\n':10,'\\t':9,'\\\\':92,"\\'":39}[ch])??ch.charCodeAt(0)));
  body=body.replace(new RegExp('\\((?:'+TYPES+')\\)','g'),'');
  body=body.replace(/\bSGOATAIWireV2State\s+(\w+);/g,'let $1={};');
  return body.replace(new RegExp('(^|[;{(]|\\n)(\\s*)(?:const\\s+)?(?:'+TYPES+')\\s+(?=[A-Za-z_])','g'),'$1$2let ');
}
function once(text,from,to,label){
  assert.equal(text.split(from).length,2,'exactly one '+label);
  return text.replace(from,()=>to);
}
function extract(text,name,{cls='',patch=b=>b}={}){
  // A class method's definition, not its in-class declaration.
  const at=text.search(new RegExp('^[ \\t]*(?:bool|int|void|string|double)\\s+'+(cls?cls+'::':'')+name+'\\s*\\(','m'));
  assert.ok(at>=0,'missing production function '+name);
  const [brace,end]=block(text,at);
  assert.equal(text.slice(at,brace).includes(';'),false,name+' is a definition');
  const header=text.slice(at,brace),params=header.slice(header.indexOf('(')+1,header.lastIndexOf(')')).trim();
  const names=!params||params==='void'?[]:params.split(',').map(p=>p.replace(/=.*/,'').trim().split(/[\s&]+/).pop());
  const statics=[],body=convert(patch(text.slice(brace,end)),statics);
  return 'var '+name+'=(function(){'+statics.join('')+'return function '+name+'('+names.join(',')+')'+body+';})();';
}
// The OnTick bias block: CurBias from the wire (live) or the reader (tester), then every decision.
const regionStart=M.indexOf('int idx=0;\n    static int LastBias=0;');
const regionEnd=M.search(/\n[ \t]*if\(!FastSpeed_Flag\)\n[ \t]*\{\n[ \t]*if\(control_tower_v2 && Mode_Bias!=Bias_Disabled\)/);
assert.ok(regionStart>0&&regionEnd>regionStart,'the V1.49 OnTick bias block');
const regionStatics=[],regionBody=convert(M.slice(regionStart,regionEnd),regionStatics);
const code=[
  extract(W,'GOATResetWireV2State'),extract(W,'GOATUsingControlTowerBias'),extract(W,'GOATApplyWireV2DemoRawAuthority'),
  extract(W,'GOATFinalizeWireV2Actionability'),extract(W,'GOATRecordedBiasLiveScore'),
  // MQL struct assignment copies into the caller's reference.
  extract(W,'GetState',{patch:b=>once(b,'state=m_state;','Object.assign(state,m_state);','wire state copy')}),
  // `long avg = sum / cnt` is integer division in MQL.
  extract(B,'GetCurentBiasScore',{cls:'GOATBiasHistory',patch:b=>once(b,'avg = sum / cnt;','avg = Math.trunc(sum / cnt);','average spacing')}),
  extract(B,'LoadBacktestFileAndFillBias',{cls:'GOATBiasHistory'}),
  'var BiasRegion=(function(){'+regionStatics.join('')+'return function BiasRegion(){'+regionBody+'\nreturn CurBias;};})();',
].join('\n');
const script=new vm.Script(code,{filename:'bias-reader-parity.translated.js'});

// ---- Enums from the input header as V1.49 declares them.
const ENUMS={};
for(const [,,items] of I.matchAll(/enum\s+(\w+)\s*\{([^}]*)\}/g)){
  let next=0;
  for(const item of items.split(',').map(s=>s.trim()).filter(Boolean)){
    const [key,value]=item.split('=').map(s=>s.trim());
    ENUMS[key]=value===undefined?next:Number(value);next=ENUMS[key]+1;
  }
}
for(const key of ['Bias_Display','Bias_Disabled','Bias_Opens','Bias_Close_low','Bias_Close_med','Bias_Close_high','Bias_Seq','Bias_SeqTrade',
  'BiasProtocol_LegacyRecorded','BiasProtocol_ControlTowerV2','BiasProtocol_ControlTowerV2DemoRaw'])assert.equal(typeof ENUMS[key],'number',key);
const MODES=['Bias_Display','Bias_Disabled','Bias_Opens','Bias_Close_low','Bias_Close_med','Bias_Close_high'];

// ---- A fake terminal: one per run, so MQL statics start fresh like a new tester pass.
const FILE={FILE_READ:1,FILE_WRITE:2,FILE_SHARE_READ:4,FILE_CSV:8,FILE_COMMON:16,FILE_TXT:32};
const EXPECTED_FILE='GOAT\\BiasFiles\\GOAT_AI_Bias_EURUSD.csv';
const toTime=s=>Date.UTC(+s.slice(0,4),+s.slice(5,7)-1,+s.slice(8,10),+s.slice(11,13),+s.slice(14,16),+s.slice(17,19))/1000;
const toText=t=>new Date(t*1000).toISOString().replace('T',' ').slice(0,19).replace(/-/g,'.');
function terminal({flags=[],protocol,mode,trades,threshold,csv=null}){
  let tokens=[],pos=0;
  const c={...FILE,...ENUMS,INVALID_HANDLE:-1,MQL_TESTER:'tester',MQL_OPTIMIZATION:'optimization',MQL_FORWARD:'forward',MQL_VISUAL_MODE:'visual',
    ACCOUNT_TRADE_MODE:32,ACCOUNT_TRADE_MODE_DEMO:0,ACCOUNT_TRADE_MODE_CONTEST:1,ACCOUNT_TRADE_MODE_REAL:2,
    MQLInfoInteger:k=>flags.includes(k)?1:0,
    AccountInfoInteger:k=>{assert.equal(k,32);return 0;},
    Bias_Protocol:protocol,Mode_Bias:ENUMS[mode],Mode_Bias_Trades:ENUMS[trades],Bias_threshold:threshold,Bias_RegenerateMinutes:10,
    Key:'GOAT',Key_:'GOAT',Symbol:()=>'EURUSD',ConvertToGOATsymbol:s=>s,TimeCurrent:()=>c.__now,__now:0,
    MathMax:Math.max,MathMin:Math.min,MathAbs:Math.abs,MathRound:x=>Math.sign(x)*Math.round(Math.abs(x)),
    ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push({});a.length=n;return n;},
    Print(){},PrintFormat(){},Alert:m=>c.__alerts.push(String(m)),__alerts:[],GetLastError:()=>0,GetTickCount64:()=>1,
    GlobalVariableCheck:()=>false,DownloadAndFillBias:()=>true,LoadOrSaveBrokerTimeFiles:()=>true,IsInUSDST:()=>false,
    StringToInteger:s=>{const n=parseInt(s,10);return Number.isNaN(n)?0:n;},StringToTime:toTime,
    FileOpen:(name,flagsIn,delimiter)=>{
      assert.equal(name,EXPECTED_FILE,'the tester reads Common\\Files\\<Key>\\BiasFiles\\GOAT_AI_Bias_<SYM>.csv');
      assert.ok(flagsIn&FILE.FILE_CSV&&flagsIn&FILE.FILE_COMMON&&flagsIn&FILE.FILE_READ);assert.equal(delimiter,',');
      if(csv===null)return -1;
      tokens=csv.split(/\r?\n/).filter(Boolean).flatMap(line=>line.split(','));pos=0;return 1;
    },
    FileIsEnding:()=>pos>=tokens.length,FileReadString:()=>pos<tokens.length?tokens[pos++]:'',FileClose(){},
    // EA globals the bias block reads and writes.
    FastSpeed_Flag:true,DrawVLines:false,MAGIC1:0,DashboardBusBiasSentiment:0,
    Sequence_New_Bias_B:true,Sequence_New_Bias_S:true,Sequence_Pause_Bias_B:false,Sequence_Pause_Bias_S:false,StopOut_Flag_B:false,StopOut_Flag_S:false,
    Seq_Buy:{BiasRescueActive:false},Seq_Sell:{BiasRescueActive:false},
    BiasList:[],BrokerGMTOffsetSec:0,BrokerDSTEnabled:0,
    m_state:{},m_last_attempt_tick:0,m_verified_tick:0,m_read_at_ms:0,m_valid_until_ms:0,__served:null,
  };
  vm.createContext(c);script.runInContext(c);
  c.Bias={GetCurentBiasScore:(a,i)=>c.GetCurentBiasScore(a,i)};
  c.GOATBiasWireV2={GetState:(a,s)=>c.GetState(a,s)};
  // CGOATAIWireV2::Refresh fetched the served record; the state is what ParseAndVerify sets for it.
  c.Refresh=asset=>{assert.equal(asset,'EURUSD');c.m_state=servedState(c,c.__served);return c.m_state.verified;};
  return c;
}
// ParseAndVerify's verified state for a served record (GOATAIWireV2.mqh, the tail of ParseAndVerify).
// A record read at or after validUntil fails verification, so Refresh leaves the reset state.
function servedState(c,rec){
  const s={};c.GOATResetWireV2State(s,'REQUEST_FAILED');
  if(rec.kind==='expired')return s;
  const available=rec.kind==='available';
  Object.assign(s,{verified:true,directive_available:available,availability:available?'AVAILABLE':'WITHHELD',
    direction:available?rec.direction:'',source_direction:rec.direction,source_probability:rec.p/100,
    calibrated_probability:available?rec.p/100:0,decision_probability:available?rec.p/100:0,
    probability_authority:available?'ISOTONIC_CALIBRATED':'NONE',reason_code:available?'':rec.reason});
  return s;
}
// goatai scripts/export_bias_history_csv.cjs (goatai#2224, truncation from goatai#2230): the score
// is the signed probability percent TRUNCATED, signedProbabilityPercent: floor(100p + 1e-9), + for
// BULLISH, - for BEARISH (0 stays 0), 0 for NEUTRAL. AVAILABLE uses the calibrated probability;
// demo-raw (the default) also promotes a row whose only withhold is CALIBRATION_ARTIFACT_UNAVAILABLE;
// every other withhold is -999 (expiry rows: exportRows). rec.p is the probability in percent.
const TRUNCATE_EPSILON=1e-9;
function exportScore(rec,exportProtocol){
  const promoted=rec.kind==='available'||(exportProtocol==='demo-raw'&&rec.kind==='withheld'&&rec.reason==='CALIBRATION_ARTIFACT_UNAVAILABLE');
  if(!promoted)return -999;
  const percent=Math.floor((rec.p/100)*100+TRUNCATE_EPSILON);
  return rec.direction==='BULLISH'?percent:rec.direction==='BEARISH'?(percent===0?0:-percent):0;
}

// ---- The served records: every edge probability in both directions and both kinds, then a long
// deterministic mix with neutral and withheld records, runs of one sign and flips.
// A directional record below 0.5% exports as 0 (neutral): that is check 6's band, not this one's.
const EDGES=[1,19,20,21,39,40,41,50,59,60,61,79,80,81,99,100];
const RECORDS=[];
for(const p of EDGES)for(const direction of ['BULLISH','BEARISH']){
  RECORDS.push({kind:'withheld',reason:'CALIBRATION_ARTIFACT_UNAVAILABLE',direction,p});
  RECORDS.push({kind:'available',direction,p});
}
RECORDS.push({kind:'available',direction:'NEUTRAL',p:90},{kind:'withheld',reason:'CALIBRATION_ARTIFACT_UNAVAILABLE',direction:'NEUTRAL',p:70});
let seed=20261004;const rand=n=>{seed=(seed*1103515245+12345)%2147483648;return seed%n;};
for(let i=0;i<110;i++){
  const roll=rand(100),direction=rand(10)===0?'NEUTRAL':(rand(4)===0?(i%2?'BULLISH':'BEARISH'):(Math.floor(i/6)%2?'BULLISH':'BEARISH'));
  const p=rand(3)===0?EDGES[rand(EDGES.length)]:1+rand(100);
  if(roll<45)RECORDS.push({kind:'withheld',reason:'CALIBRATION_ARTIFACT_UNAVAILABLE',direction,p});
  else if(roll<85)RECORDS.push({kind:'available',direction,p});
  else RECORDS.push({kind:'withheld',reason:['BELIEF_MAXIMUM_AGE_EXCEEDED','EXPECTATION_VIOLATED_AFTER_LAST_WAKE','LIVE_PRICING_UNAVAILABLE'][rand(3)],direction,p});
}
// ---- The wire timeline: one publish per record, normally every 15 minutes. A record is valid for
// 65 minutes (validUntil) unless the next publish supersedes it. Some gaps are longer: 50 minutes
// (still valid when the next record lands: no expiry row, live keeps acting), exactly 65 minutes
// (the next publish lands on validUntil and supersedes the expiry), 90 and 150 minutes (the record
// expires first: the export writes an explicit -999 row at validUntil).
const T0=toTime('2026.09.29 00:00:29'),CADENCE=900,VALID=3900;
const GAP=i=>i%17===5?3000:i%19===7?5400:i%23===11?9000:i%29===13?3900:CADENCE;
const PUBLISHES=[];{let t=T0;RECORDS.forEach((rec,i)=>{PUBLISHES.push({t,rec});t+=GAP(i);});}
const END=PUBLISHES[PUBLISHES.length-1].t+5400;
// goatai#2224: a value lasts until the next publish; if none arrives before validUntil, a -999
// EXPIRED row at validUntil ends it (a publish in that same second wins the collapse).
function exportRows(exportProtocol){
  const rows=[];
  PUBLISHES.forEach(({t,rec},i)=>{
    rows.push([t,exportScore(rec,exportProtocol)]);
    const next=i+1<PUBLISHES.length?PUBLISHES[i+1].t:Infinity;
    if(next>t+VALID)rows.push([t+VALID,-999]);
  });
  return rows;
}
const csvFor=exportProtocol=>'Time,Asset,SentimentScore\r\n'+exportRows(exportProtocol).map(([t,s])=>toText(t)+',EURUSD,'+s).join('\r\n')+'\r\n';
// Evaluate at each publish, a minute later, through every gap (every 10 minutes at the regular
// cadence, every 5 inside a long gap) and a second either side of every expiry.
const INSTANTS=[];
PUBLISHES.forEach(({t},i)=>{
  const next=i+1<PUBLISHES.length?PUBLISHES[i+1].t:END,step=next-t>CADENCE?300:600,at=new Set([t,t+60]);
  for(let s=t+step;s<next;s+=step)at.add(s);
  for(const s of [t+VALID-1,t+VALID,t+VALID+1])at.add(s);
  for(const s of [...at].filter(s=>s<next).sort((a,b)=>a-b))INSTANTS.push({now:s,publish:i});
});
// What the live EA reads at `now`: the current record, or nothing once it has expired.
const served=({now,publish})=>now<PUBLISHES[publish].t+VALID?PUBLISHES[publish].rec:{kind:'expired'};
const decision=(c,cur)=>[cur,c.Sequence_New_Bias_B,c.Sequence_New_Bias_S,c.Sequence_Pause_Bias_B,c.Sequence_Pause_Bias_S,c.StopOut_Flag_B,c.StopOut_Flag_S,c.DashboardBusBiasSentiment];
const rescue=i=>({buy:i%11===4,sell:i%13===7});

function liveRun({protocol,mode,trades,threshold}){
  const c=terminal({protocol,mode,trades,threshold}),out=[];
  INSTANTS.forEach((instant,i)=>{
    c.__now=instant.now;c.__served=served(instant);c.Seq_Buy.BiasRescueActive=rescue(i).buy;c.Seq_Sell.BiasRescueActive=rescue(i).sell;
    c.GOATResetWireV2State(c.m_state,'NOT_FETCHED');c.m_last_attempt_tick=0;c.m_verified_tick=0;c.m_read_at_ms=0;c.m_valid_until_ms=0;
    out.push(decision(c,c.BiasRegion()));
  });
  return out;
}
function testerRun({flags,exportProtocol,mode,trades,threshold}){
  const c=terminal({flags,protocol:ENUMS.BiasProtocol_LegacyRecorded,mode,trades,threshold,csv:csvFor(exportProtocol)}),out=[];
  c.__now=T0;
  // OnInit: `if(Mode_Bias!=Bias_Disabled && Bias_Protocol==BiasProtocol_LegacyRecorded) Bias.Init(Key);`
  if(c.Mode_Bias!==ENUMS.Bias_Disabled){assert.equal(c.LoadBacktestFileAndFillBias(),true);assert.equal(c.BiasList.length,exportRows(exportProtocol).length);}
  INSTANTS.forEach((instant,i)=>{
    c.__now=instant.now;c.Seq_Buy.BiasRescueActive=rescue(i).buy;c.Seq_Sell.BiasRescueActive=rescue(i).sell;
    out.push(decision(c,c.BiasRegion()));
  });
  return out;
}

// 1. Structure: one switch, set only by V1.49 and before both headers; earlier releases unchanged.
check(()=>{
  const flag='#define GOAT_RECORDED_BIAS_LIVE_GATE_V149';
  assert.ok(mainSource.includes(flag+'\n'),'V1.49 enables the recorded live gate');
  for(const header of ['#include "Optimizer.mqh"','#include "GOATAIWireV2.mqh"'])assert.ok(mainSource.indexOf(flag)<mainSource.indexOf(header),'defined before '+header);
  for(const v of ['1.47','1.48'])assert.equal(read('GOAT V'+v+'.mq5').includes('GOAT_RECORDED_BIAS_LIVE_GATE_V149'),false,'V'+v+' is release history');
  assert.match(mainSource,/if\(Mode_Bias!=Bias_Disabled && Bias_Protocol==BiasProtocol_LegacyRecorded\) Bias\.Init\(Key\);/);
});
// 2. One gate: the reader calls the live helper with the live cutoff expression, not a copy of its logic.
check(()=>{
  const cutoff=W.match(/double configured_cutoff=(MathMax\(0\.0,MathMin\(100\.0,\(double\)Bias_threshold\)\)\/100\.0);\s*GOATFinalizeWireV2Actionability\(state,configured_cutoff\);/);
  assert.ok(cutoff,'GetState runs the live gate at the run\'s Bias_threshold');
  const at=W.indexOf('int GOATRecordedBiasLiveScore('),gate=W.slice(at,block(W,at)[1]);
  assert.ok(gate.includes('GOATFinalizeWireV2Actionability(state,'+cutoff[1]+');'),'the reader reuses the live gate and cutoff');
  assert.equal(/Bias_threshold\s*[<>]/.test(gate),false,'no second threshold comparison');
});

// 3. The gate alone, exhaustively: every whole-percent score at every N gives live's CurBias.
check(()=>{
  const c=terminal({flags:['tester'],protocol:ENUMS.BiasProtocol_ControlTowerV2,mode:'Bias_Opens',trades:'Bias_Seq',threshold:60});
  for(let n=-10;n<=150;n++){
    c.Bias_threshold=n;
    for(let s=-100;s<=100;s++){
      const state={};
      c.m_state={};c.GOATResetWireV2State(c.m_state,'NOT_FETCHED');c.m_last_attempt_tick=0;
      c.__served={kind:'available',direction:s>0?'BULLISH':s<0?'BEARISH':'NEUTRAL',p:Math.abs(s)};
      const verified=c.GetState('EURUSD',state),live=verified&&state.actionable?state.signed_probability_percent:-999;
      assert.equal(c.GOATRecordedBiasLiveScore(s),live,'score '+s+' at N='+n);
    }
    for(const s of [-999,-150,-101,101,150,999])assert.equal(c.GOATRecordedBiasLiveScore(s),-999,'dark '+s+' at N='+n);
  }
});

// 4. The full decision paths over the same timeline: identical decisions at every instant. Every N
// runs in the tester; N = 0, 60 and 150 also run in optimization and forward.
const THRESHOLDS=[-10,0,1,20,40,59,60,61,80,99,100,150];
const CONTEXTS=[['tester'],['tester','optimization'],['tester','forward']];
const PAIRS=[['demo-raw',ENUMS.BiasProtocol_ControlTowerV2DemoRaw],['strict',ENUMS.BiasProtocol_ControlTowerV2]];
let rowsCompared=0,heldInstants=0,expiredInstants=0;
for(const [exportProtocol,protocol] of PAIRS)for(const mode of MODES)for(const trades of ['Bias_Seq','Bias_SeqTrade'])for(const threshold of THRESHOLDS){
  const live=liveRun({protocol,mode,trades,threshold});
  for(const flags of [0,60,150].includes(threshold)?CONTEXTS:CONTEXTS.slice(0,1))check(()=>{
    const tester=testerRun({flags,exportProtocol,mode,trades,threshold});
    tester.forEach((row,i)=>assert.deepEqual(row,live[i],JSON.stringify({exportProtocol,mode,trades,threshold,flags,instant:i,
      sincePublish:INSTANTS[i].now-PUBLISHES[INSTANTS[i].publish].t,record:PUBLISHES[INSTANTS[i].publish].rec,
      fields:'CurBias,New_B,New_S,Pause_B,Pause_S,StopOut_B,StopOut_S,DashboardBias'})));
    rowsCompared+=tester.length;
  });
}
// The timeline reaches every case that motivated the fix.
check(()=>{
  const rows=exportRows('demo-raw'),spacing=(rows[rows.length-1][0]-rows[0][0])/(rows.length-1);
  const acting=({publish})=>exportScore(PUBLISHES[publish].rec,'demo-raw')!==-999;
  const since=({now,publish})=>now-PUBLISHES[publish].t;
  // Sign-only modes below the threshold.
  const below=RECORDS.filter(rec=>{const s=exportScore(rec,'demo-raw');return s!==-999&&Math.abs(s)<60;}).length;
  assert.ok(below>25,'below-threshold records: '+below);
  // A long gap with no -999 row: live still acts past twice the row spacing, so the tester must too.
  const held=INSTANTS.filter(x=>acting(x)&&since(x)>2*spacing&&since(x)<VALID).length;
  assert.ok(held>=10,'instants a spacing heuristic would have called stale while live acts: '+held);heldInstants=held;
  // Explicit expiry rows: live has nothing from validUntil until the next publish.
  const expired=INSTANTS.filter(x=>acting(x)&&since(x)>=VALID).length;
  expiredInstants=expired;
  assert.ok(expired>=10&&rows.filter(([,s])=>s===-999).length>RECORDS.filter(rec=>exportScore(rec,'demo-raw')===-999).length,'expiry rows: '+expired);
  // The 65-minute gap: the next publish lands on validUntil and no expiry row is written.
  assert.ok(PUBLISHES.some(({t},i)=>i+1<PUBLISHES.length&&PUBLISHES[i+1].t===t+VALID));
});

// 5. Live is unchanged: the live legacy reader still hands over every score and still applies its
// spacing staleness rule, and a dark live legacy point still never pauses additions. Only the
// tester takes the live gate and holds a point until the export's own -999 row.
check(()=>{
  const rows=[0,1,2].map(i=>({time:T0+i*CADENCE,asset:'EURUSD',sentiment_score:35}));
  const live=terminal({protocol:ENUMS.BiasProtocol_LegacyRecorded,mode:'Bias_Close_low',trades:'Bias_SeqTrade',threshold:60});
  const tester=terminal({flags:['tester'],protocol:ENUMS.BiasProtocol_LegacyRecorded,mode:'Bias_Close_low',trades:'Bias_SeqTrade',threshold:60});
  for(const c of [live,tester]){c.BiasList.push(...rows.map(r=>({...r})));c.__now=T0+2*CADENCE+60;}
  assert.equal(live.GetCurentBiasScore('EURUSD',0),35);
  assert.equal(tester.GetCurentBiasScore('EURUSD',0),-999);
  // Rows 15 minutes apart: live legacy calls a point stale after twice that (30 minutes).
  for(const c of [live,tester])c.Bias_threshold=20;
  for(const [after,legacy] of [[1500,35],[1799,35],[1801,-999],[3000,-999]]){
    for(const c of [live,tester])c.__now=T0+2*CADENCE+after;
    assert.equal(live.GetCurentBiasScore('EURUSD',0),legacy,'live legacy staleness at +'+after);
    assert.equal(tester.GetCurentBiasScore('EURUSD',0),35,'the gated tester holds the point at +'+after);
  }
  for(const c of [live,tester])c.Bias_threshold=60;
  for(const c of [live,tester]){c.BiasList.length=0;c.BiasRegion();}
  assert.deepEqual([live.Sequence_Pause_Bias_B,live.Sequence_Pause_Bias_S],[false,false],'live legacy keeps its old dark-point behaviour');
  assert.deepEqual([tester.Sequence_Pause_Bias_B,tester.Sequence_Pause_Bias_S],[true,true],'the tester pauses additions as live v2 does');
});

// 6. Sub-percent wire probabilities through the truncating export (goatai#2230): ZERO disagreements
// on acting at every N from 1 to 100 and above. floor(100p) >= N exactly when p >= N/100, so the
// tester acts exactly when live does, with the same sign and |CurBias| >= N on both sides, and every
// comparison in the bias block agrees. Only the displayed value can differ, by under one point (live
// shows MathRound(100p), the CSV holds the truncation). The probabilities are the wire's JSON
// decimals: every thousandth and every hundredth, as parsed.
const DECIMAL_PROBABILITIES=[...new Set([...Array.from({length:1001},(_,k)=>k/1000),...Array.from({length:101},(_,k)=>Number('0.'+String(k).padStart(2,'0'))),1])];
// Doubles that sit a float hair off a whole percent, as arithmetic produces them (0.7*0.1 is
// 0.06999999999999999, 0.1*3 is 0.30000000000000004).
const NOISY_PROBABILITIES=[...new Set([...Array.from({length:101},(_,k)=>(k/10)*0.1),...Array.from({length:101},(_,k)=>k*0.01),
  0.1*3,0.7-0.1,0.2+0.4,1-0.42,0.57*1,0.29*1])].filter(p=>p>=0&&p<=1);
function sweep(c,n,probabilities,visit,score=rec=>exportScore(rec,'strict')){
  c.Bias_threshold=n;
  for(const p of probabilities)for(const direction of ['BULLISH','BEARISH']){
    const state={},rec={kind:'available',direction,p:p*100};
    c.m_state={};c.GOATResetWireV2State(c.m_state,'NOT_FETCHED');c.m_last_attempt_tick=0;c.__served=rec;
    const verified=c.GetState('EURUSD',state),live=verified&&state.actionable?state.signed_probability_percent:-999;
    visit(p,direction,live,c.GOATRecordedBiasLiveScore(score(rec)));
  }
}
const PRACTICAL_N=[...Array.from({length:100},(_,i)=>i+1),150];
let swept=0;
check(()=>{
  const c=terminal({flags:['tester'],protocol:ENUMS.BiasProtocol_ControlTowerV2,mode:'Bias_Opens',trades:'Bias_Seq',threshold:60});
  for(const n of PRACTICAL_N)sweep(c,n,DECIMAL_PROBABILITIES,(p,direction,live,tester)=>{
    swept++;
    assert.equal(live===-999,tester===-999,'acting disagrees: p='+p+' '+direction+' N='+n);
    if(live===-999)return;
    assert.equal(Math.sign(live),Math.sign(tester));assert.ok(Math.abs(live-tester)<=1,'display rounding only');
    assert.ok(n>100?live===tester:Math.abs(live)>=n&&Math.abs(tester)>=n,'both clear the threshold');
  });
});
// 7. Bias_threshold <= 0 acts on any direction. The one thing the integer CSV cannot carry there is
// a directional probability below 1%: it truncates to 0, which is the CSV's NEUTRAL, so the tester
// sees no direction where live acts with CurBias 0 or 1. Nothing else differs.
check(()=>{
  const c=terminal({flags:['tester'],protocol:ENUMS.BiasProtocol_ControlTowerV2,mode:'Bias_Opens',trades:'Bias_Seq',threshold:0});
  let subPercent=0;
  for(const n of [-10,0])sweep(c,n,DECIMAL_PROBABILITIES,(p,direction,live,tester)=>{
    swept++;
    if((live===-999)!==(tester===-999)){
      subPercent++;assert.ok(p<0.01&&tester===-999&&Math.abs(live)<=1,'only a sub-1% direction: p='+p+' N='+n);return;
    }
    if(live!==-999){assert.equal(Math.sign(live),Math.sign(tester));assert.ok(Math.abs(live-tester)<=1);}
  });
  assert.ok(subPercent>0);
});
// 8. #2230's 1e-9 epsilon (so 0.57*100 = 56.999... still exports 57) also lifts a double a hair BELOW
// a whole percent to that percent: 0.7*0.1 = 0.06999999999999999 exports 7, while live compares
// 0.06999999999999999 >= 0.07 and does not act. That float band (< 1e-11 below the cutoff) is the only
// disagreement for noisy doubles. Stepping the truncation back when percent/100 > p closes it: with that
// exact rule there are zero disagreements on these doubles too.
check(()=>{
  const c=terminal({flags:['tester'],protocol:ENUMS.BiasProtocol_ControlTowerV2,mode:'Bias_Opens',trades:'Bias_Seq',threshold:60});
  const exact=rec=>{
    const s=exportScore(rec,'strict');if(s===-999||s===0)return s;
    const p=rec.p/100,k=Math.abs(s);return Math.sign(s)*(k/100>p?k-1:k);
  };
  let band=0;
  for(const n of PRACTICAL_N){
    const cutoff=Math.min(n,100)/100;
    sweep(c,n,NOISY_PROBABILITIES,(p,direction,live,tester)=>{
      swept++;
      if((live===-999)===(tester===-999))return;
      band++;assert.ok(live===-999&&p<cutoff&&cutoff-p<1e-11,'only the epsilon band: p='+p+' N='+n);
    });
    sweep(c,n,NOISY_PROBABILITIES,(p,direction,live,tester)=>assert.equal(live===-999,tester===-999,'exact rule: p='+p+' N='+n),exact);
  }
  assert.ok(band>0,'0.7*0.1 is in the epsilon band');
});
console.log(`test_bias_reader_parity: ${checks}/${checks} passed (${rowsCompared} instants compared; ${heldInstants} past twice the row spacing with no expiry row, ${expiredInstants} after an explicit -999 expiry row; ${swept} wire probabilities through the truncating export)`);
