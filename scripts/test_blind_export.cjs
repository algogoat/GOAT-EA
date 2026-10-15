// B44 item 5 (goatai#2350): BlindExport. Off by default, appended as the last input (append-only, WriteSet never
// writes it). On: the exporter adds blind=1 to each export run's EA_Desc @{...}; that tester run measures the fit+FWD
// window (SAMPLE: dt_BOOS_end to dt_FOOS_start) and writes "; EXPORT blind:1 ranked:fit+fwd sr:daily_ann" plus a "; RANKED" line;
// RunAndStoreSet's profit floor and the SR/ARF it stores (so the MinSR/MinARF count and SortAndTrimExports) come from
// that line. Off: every export is stamped "; EXPORT blind:0 ranked:full_span sr:mt5_stat" and nothing else changes. Neither line
// holds "=" (goatai#2350 6128225191), so no controller writer copies them into a deployed chart.
// B45 (Claude-Mac's GOAT-EA#227 review): 1) window parity: the RANKED PL, SR, ARF, drawdown and Days are the controller's
// studio_window_metrics.equity_metrics on the same equity samples (the opening is the last equity before the window,
// each Mon-Fri day returns on its close, carried forward); section 1 runs the Python reference itself on the fixture.
// 2) BOOS-free: the blind SET has no BOOS line, the window is measured on the equity less the BOOS P/L (so the returns
// and the ARF denominator hold no BOOS result), and trd_FOOS starts at dt_Fwrd_OOS as the window does (section 8).
// 3) AdjustLots sizes a blind export on the drawdown over every non-FOOS tick (section 9).
// This runs the production GoatRankTick / GoatRankLine / GoatReadRankedLine after a syntax-only MQL-to-JS conversion
// against modelled equity streams and pins the wiring and the blind=0 no-drift against c708cae4. Native tester runs
// are not exercised here. Python: GOAT_PYTHON, else "python" on PATH (CI's setup-python).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync,spawnSync}=require('node:child_process');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const norm=t=>t.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const main=norm(fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const audit=norm(fs.readFileSync(path.join(ROOT,'GOATPortfolioChildAudit.mqh'),'utf8'));
const header=norm(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
const B43_SOURCE='c708cae4';
let passed=0;const ok=()=>passed++;
function unit(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);assert.equal(text.indexOf(signature,a+1),-1,'one '+signature);
 // Braces inside string literals and comments do not count (StartExporter's "@{mode=EXPORT,...}" spans two literals).
 let j=text.indexOf('{',a)+1,depth=1;
 while(depth&&j<text.length){
  const ch=text[j];
  if(ch==='"'){j++;while(j<text.length&&text[j]!=='"'){if(text[j]==='\\')j++;j++;}j++;continue;}
  if(ch==="'"){j+=text[j+1]==='\\'?4:3;continue;}
  if(ch==='/'&&text[j+1]==='/'){j=text.indexOf('\n',j);continue;}
  if(ch==='{')depth++;if(ch==='}')depth--;j++;
 }
 return text.slice(a,j);
}

// ---- the production measurement and parser, converted ----
const start=main.indexOf('bool   g_GoatBlindExport=false;'),end=main.indexOf('// B44 item 9 (goatai#2350): a failed panel');
assert.ok(start>0&&end>start);
let code=main.slice(start,end).replace(/\/\/.*$/gm,'');
code=code.replace(/^(?:bool|double|int|long)\s+(g_GoatRank\w+|g_GoatBlindExport)(\[5\])?=([^;]+);$/gm,(_,n,arr,v)=>'var '+n+'='+(arr?'['+v.replace(/[{}]/g,'')+']':v)+';')
 .replace(/^(double|int)\s+(g_Goat\w+=[^;]+);$/gm,'var $2;')
 .replace(/^void (\w+)\(const double (\w+)\)/gm,'function $1($2)').replace(/^void (\w+)\(const long (\w+)\)/gm,'function $1($2)')
 .replace(/^void (\w+)\(void\)/gm,'function $1()')
 .replace(/^string (\w+)\(void\)/gm,'function $1()').replace(/^double (\w+)\(void\)/gm,'function $1()')
 .replace(/^string GoatBlindDesc\(const string rank_desc\)/m,'function GoatBlindDesc(rank_desc)')
 .replace(/^bool GoatReadRankedLine\(const string rank_text,double &rank_pl,double &rank_sr,double &rank_arf\)/m,'function GoatReadRankedLine(rank_text,out)');
const reader=unit(code,'function GoatReadRankedLine(rank_text,out)');
code=code.replace(reader,reader.replace(/\brank_(pl|sr|arf)\b/g,'out.$1'));
code=code.replace(/\(long\)\(([^()]+)\)\/86400/g,'Math.floor(($1)/86400)').replace(/\(long\)(\w+)\/86400/g,'Math.floor($1/86400)')
 .replace(/\bdouble dds\[5\];/g,'let dds=[];').replace(/\bstring (\w+)\[\];/g,'let $1=[];').replace(/\bstring (\w+)\[\],/g,'let $1=[],')
 .replace(/\(datetime\)/g,'').replace(/\bulong (?=\w+=)/g,'let ')
 .replace(/\b(?:const )?(?:string|double|int|long|bool|datetime) (?=[a-z_]\w*\s*[=;,])/g,'let ')
 .replace(/StringTrimLeft\((\w+)\)/g,'$1=$1.trimStart()').replace(/StringTrimRight\((\w+)\)/g,'$1=$1.trimEnd()')
 .replace(/'\\n'/g,'10').replace(/' '/g,'32');
assert.ok(!/\(long\)/.test(code),'every (long) cast converted');
const date=s=>{const d=new Date(s*1000);return d.getUTCFullYear()+'.'+String(d.getUTCMonth()+1).padStart(2,'0')+'.'+String(d.getUTCDate()).padStart(2,'0');};
const iso=s=>date(s).replace(/\./g,'-');
function harness({blind=true,boos=0,foos=0,trdIS=7}={}){
 const c={now:0,equity:0,dt_Back_OOS:boos,dt_Fwrd_OOS:foos,trd_IS:trdIS,ACCOUNT_EQUITY:1,TIME_DATE:1,
  TimeCurrent:()=>c.now,AccountInfoDouble:()=>c.equity,MathMax:Math.max,MathSqrt:Math.sqrt,
  DoubleToString:(v,d)=>Number(v).toFixed(d),IntegerToString:String,TimeToString:d=>date(d),
  StringFind:(s,t)=>s.indexOf(t),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringSplit:(s,ch,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(ch)));return out.length;},
  StringToDouble:s=>{const v=parseFloat(s);return Number.isFinite(v)?v:0;},MathIsValidNumber:Number.isFinite,
  MQL_PROGRAM_NAME:1,MQLInfoString:()=>'GOAT V1.49',deals:[],selected:[],DEAL_TYPE:1,DEAL_TIME:2,DEAL_PROFIT:3,DEAL_SWAP:4,DEAL_COMMISSION:5,DEAL_FEE:6,
  DEAL_TYPE_BUY:0,DEAL_TYPE_SELL:1,DEAL_TYPE_BALANCE:2,
  HistorySelect:(a,b)=>{c.selected=c.deals.filter(d=>d.time>=a&&d.time<=b);return true;},HistoryDealsTotal:()=>c.selected.length,
  HistoryDealGetTicket:i=>i+1,HistoryDealGetInteger:(t,k)=>k===1?c.selected[t-1].type:c.selected[t-1].time,
  HistoryDealGetDouble:(t,k)=>({3:c.selected[t-1].profit,4:c.selected[t-1].swap??0,5:c.selected[t-1].commission??0,6:0})[k]};
 vm.createContext(c);vm.runInContext(code,c);c.g_GoatBlindExport=blind;
 return c;
}
const run=(pts,opts)=>{const c=harness(opts);for(const [t,e] of pts){c.now=t;c.equity=e;c.GoatRankTick();}return c;};

// ---- the controller's reference (studio_window_metrics.py), run by Python on the same samples ----
// The window is [first, last] (first = BOOS end day, else the first sample's day; last = the day before FOOS, else the
// last sample's day), measured on the equity less the BOOS P/L (the last equity before the window less the first
// equity); sizingDd is the controller's maxDd over every non-FOOS sample (the preFoos span), on the raw equity.
const PY=String.raw`
import json, sys
sys.path.insert(0, sys.argv[1])
from datetime import date, datetime
from studio_window_metrics import equity_samples, equity_metrics
out = []
for case in json.load(sys.stdin):
    rows = equity_samples(case['csv'].encode('utf-8'))
    first = date.fromisoformat(case['first']) if case['first'] else rows[0][0].date()
    last = date.fromisoformat(case['last']) if case['last'] else rows[-1][0].date()
    start = datetime.combine(first, datetime.min.time())
    before = [r for r in rows if r[0] < start]
    shift = (before[-1][1] - rows[0][1]) if before else 0.0
    window = equity_metrics([(t, e - shift) for t, e in rows], first, last)
    raw = equity_metrics(rows, first, last)
    sizing = equity_metrics(rows, rows[0][0].date(), last)
    out.append(dict(window=window, raw=raw, sizingDd=sizing['maxDd'], shift=shift))
print(json.dumps(out))
`;
const csvOf=pts=>'<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>\n'+pts.map(([t,e])=>{const d=new Date(t*1000);
 return date(t)+' '+String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0')+'\t'+e+'\t'+e+'\t0';}).join('\n')+'\n';
function python(cases){
 const exe=process.env.GOAT_PYTHON||'python';
 const r=spawnSync(exe,['-I','-B','-c',PY,path.join(ROOT,'controller')],{input:JSON.stringify(cases.map(({pts,boos,foos})=>({csv:csvOf(pts),
  first:boos?iso(boos):'',last:foos?iso(foos-86400):''}))),encoding:'utf8',maxBuffer:64<<20});
 assert.equal(r.status,0,'the Python reference ran ('+exe+'): '+(r.error||r.stderr));
 return JSON.parse(r.stdout);
}
const near=(got,want,label)=>assert.ok(Math.abs(got-want)<=2e-8+1e-12*Math.abs(want),label+': EA '+got+' vs controller '+want);
function parity(c,ref,label){
 const w=ref.window;assert.ok(w,label+': the controller measured the window');
 c.GoatRankFinish();
 near(c.g_GoatRankClose-c.g_GoatRankOpen,w.equityNet,label+' PL');
 near(c.g_GoatRankMaxDD,w.maxDd,label+' window drawdown');
 near(c.g_GoatRankARF,w.arf,label+' ARF');
 near(c.g_GoatRankSR,w.sharpe??0,label+' SR');
 assert.equal(c.g_GoatRankDays,w.days,label+' Days (Mon-Fri days of the window)');
 near(c.g_GoatRankSizeDD,ref.sizingDd,label+' sizing drawdown (all non-FOOS)');
 // PL and the drawdowns do not move with the BOOS P/L; the controller's unshifted window agrees on them.
 near(w.equityNet,ref.raw.equityNet,label+' PL is shift-free');near(w.maxDd,ref.raw.maxDd,label+' drawdown is shift-free');
}
const parse=line=>{assert.ok(!line.includes('='),'a RANKED line holds no =: '+line);return Object.fromEntries(line.split(' ').filter(x=>x.includes(':')).map(x=>x.split(':')));};
let seed=20261012;const rnd=()=>(seed=(seed*48271)%2147483647)/2147483647;
const DAY=86400,MON=Date.UTC(2025,0,6)/1000;
// Equity samples every 10 minutes (minute stamps, as the export CSV). weekends: crypto-style ticks on Sat/Sun;
// holidays: weekday indexes with no tick at all; jumps: {day index: amount} added at that day's first sample.
function stream(days=180,ticks=40,{weekends=false,holidays=[],jumps={},drift=0.48,from=MON,startEquity=100000}={}){
 const out=[];let e=startEquity;
 for(let d=0;d<days;d++){const day=from+d*DAY;
  if(!weekends&&[0,6].includes(new Date(day*1000).getUTCDay()))continue;if(holidays.includes(d))continue;
  if(jumps[d])e+=jumps[d];
  for(let k=0;k<ticks;k++){e+=(rnd()-drift)*120;out.push([day+k*600,Math.round(e*100)/100]);}}
 return out;}
const midnight=t=>t-t%DAY;

// 1) Parity: the EA's window metrics equal studio_window_metrics.equity_metrics on the same samples, across random
//    streams, a window opening on a Saturday, a weekday with no tick, weekend ticks, an equity jump between the last
//    BOOS sample and the first window sample (B44 seeded the window there), no BOOS, no FOOS, a losing and a flat window.
{const cases=[];
 for(let r=0;r<6;r++){const pts=stream(200);cases.push({label:'random '+r,pts,boos:midnight(pts[Math.floor(pts.length*0.2)][0]),foos:midnight(pts[Math.floor(pts.length*0.85)][0])});}
 {const pts=stream(120,30,{holidays:[51,66]});cases.push({label:'window opens on a Saturday, weekday holidays',pts,boos:MON+47*DAY,foos:MON+100*DAY});}
 {const pts=stream(90,24,{weekends:true});cases.push({label:'weekend ticks',pts,boos:MON+20*DAY,foos:MON+80*DAY+3*DAY});}
 {const pts=stream(80,30,{jumps:{30:2500}});cases.push({label:'jump at the window open',pts,boos:MON+30*DAY,foos:MON+70*DAY});}
 {const pts=stream(60,30);cases.push({label:'no BOOS',pts,boos:0,foos:MON+50*DAY});}
 {const pts=stream(60,30);cases.push({label:'no FOOS',pts,boos:MON+14*DAY,foos:0});}
 {const pts=stream(70,20,{drift:0.62});cases.push({label:'losing window',pts,boos:MON+21*DAY,foos:MON+63*DAY});}
 {const pts=[];for(let d=0;d<30;d++)if(![0,6].includes(new Date((MON+d*DAY)*1000).getUTCDay()))pts.push([MON+d*DAY+3600,100000]);
  cases.push({label:'flat window',pts,boos:MON+7*DAY,foos:MON+28*DAY});}
 const refs=python(cases);
 for(const [i,cs] of cases.entries()){
  const c=run(cs.pts,{boos:cs.boos,foos:cs.foos});parity(c,refs[i],cs.label);
  const got=parse(c.GoatRankLine()),w=refs[i].window;
  assert.equal(Number(got.Days),w.days);assert.equal(got.Trades,'7');
  for(const [k,v] of [['PL',w.equityNet],['SR',w.sharpe??0],['ARF',w.arf]])assert.ok(Math.abs(Number(got[k])-v)<=0.0051,cs.label+' RANKED '+k);
  if(cs.boos)assert.ok(c.GoatRankLine().startsWith('; RANKED fit+fwd '+date(cs.boos)+'-'+(cs.foos?date(cs.foos):'end')+' '));
 }
 // The jump case: PL is closing less the last BOOS equity (B44 used the first window sample, so the jump went missing).
 const j=cases.findIndex(cs=>cs.label==='jump at the window open'),jc=run(cases[j].pts,{boos:cases[j].boos,foos:cases[j].foos});
 const pre=cases[j].pts.filter(([t])=>t<cases[j].boos).at(-1)[1],first=cases[j].pts.find(([t])=>t>=cases[j].boos)[1];
 assert.ok(first-pre>2000,'the fixture jumps at the open');jc.GoatRankFinish();near(jc.g_GoatRankClose-jc.g_GoatRankOpen,refs[j].window.equityNet,'jump PL');
 const last=cases[j].pts.filter(([t])=>t<cases[j].foos).at(-1)[1];near(jc.g_GoatRankClose-jc.g_GoatRankOpen,last-pre,'PL = close - last equity before the window');
 const flat=cases.findIndex(cs=>cs.label==='flat window');assert.deepEqual([parse(run(cases[flat].pts,cases[flat]).GoatRankLine()).ARF],['0.000']);
 assert.ok(refs[cases.findIndex(cs=>cs.label==='losing window')].window.arf<0);
 ok();}
// 2) Off (blind=0 or no blind key): nothing is measured.
{const c=run(stream(20),{blind:false});
 assert.equal(c.g_GoatRankOpened,false);assert.equal(c.g_GoatRankDays,0);assert.equal(c.g_GoatRankHaveBase,false);ok();}
// 4) The exporter's reader: exactly one RANKED line after the blind=1 stamp, with PL, SR and ARF.
{const c=harness();const read=t=>{const out={};const r=c.GoatReadRankedLine(t,out);return [r,out.pl,out.sr,out.arf];};
 const good='; SAMPLE: x\n; EXPORT blind:1 ranked:fit+fwd sr:daily_ann\r\n; RANKED fit+fwd 2025.01.01-2025.06.01 Days:100 Trades:40 PL:-12.50 SR:1.234 ARF:0.456\r\nRisk=500\n';
 assert.deepEqual(read(good),[true,-12.5,1.234,0.456]);
 for(const [label,text] of [['no stamp',good.replace('; EXPORT blind:1 ranked:fit+fwd sr:daily_ann\r\n','')],['the pre-condition stamp',good.replace(' sr:daily_ann','')],
  ['the = form of the stamp',good.replace('; EXPORT blind:1 ranked:fit+fwd sr:daily_ann','; EXPORT: blind=1 ranked=fit+fwd sr=daily_ann')],['the = form of RANKED',good.replace(/Days:100 Trades:40 PL:-12.50 SR:1.234 ARF:0.456/,'Days=100 Trades=40 PL=-12.50 SR=1.234 ARF=0.456')],['blind:0 stamp',good.replace('blind:1 ranked:fit+fwd','blind:0 ranked:full_span')],
  ['no ranked line',good.replace(/; RANKED .*\r\n/,'')],['two ranked lines',good.replace(/(; RANKED .*\r\n)/,'$1$1')],['no SR',good.replace(' SR:1.234','')],
  ['empty ARF',good.replace('ARF:0.456','ARF:')],['empty file','']]) {assert.equal(read(text)[0],false,label);}
 ok();}
// 5) Wiring.
{const lastInput=[...main.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].at(-1);
 assert.equal(lastInput[1],'BlindExport','BlindExport is the last input of the entrypoint (after Studio_MonitorRunPath)');
 assert.match(main,/sinput string Studio_MonitorRunPath="";[^\n]*\n\/\/[^\n]*\ninput bool BlindExport=false;/);
 assert.ok(!/BlindExport/.test(unit(header,'void WriteSet(string desc)')),'WriteSet never writes it');
 assert.ok(!/BlindExport/.test(header),'the input header (contract pin) is unchanged by it');
 assert.match(audit,/"GOAT_FitnessRunNonce","BlindExport"\};\n   string declared_values\[7\]=\{"false","","0","0","4","0","false"\};/,'the child audit accepts it at its default only');
 assert.match(main,/fwdRangeMeta\+\(BlindExport \? ",blind=1" : ""\)\+"\}\\n"/,'blind=1 rides in the export run meta only when on');
 assert.match(main,/if\(names\[i\]=="blind" && values\[i\]=="1"\) \{g_GoatBlindExport=true;/);
 assert.match(main,/if\(g_GoatBlindExport\) WriteSet\(GoatBlindDesc\(desc\)\);\n\s+else\s+WriteSet\(desc\+"\\n; EXPORT blind:0 ranked:full_span sr:mt5_stat"\);/);
 assert.match(main,/    if\(g_GoatBlindExport\) metrix=GoatRankMetrix\(\);[^\n]*\n    newFile \+= metrix\+".csv";/,'a blind export is named by its window metrics');
 assert.match(main,/GoatRankTick\(\); \/\/ B44 item 5/);
 const store=unit(main,'int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false,const int startAttempts=20)');
 assert.ok(store.indexOf('profit=rank_pl;')<store.indexOf('if(profit>0)'),'the floor reads the fit+FWD PL');
 assert.match(store,/expArr\[n\]\.sr       = \(BlindExport \? rank_sr  : FetchMetric\(exports\[0\],"SR"\)\);/);
 assert.match(store,/expArr\[n\]\.arf      = \(BlindExport \? rank_arf : FetchMetric\(exports\[0\],"ARF"\)\);/);
 const tester=norm(fs.readFileSync(path.join(ROOT,'Tester.mqh'),'utf8'));
 assert.match(unit(tester,'void SortAndTrimExports(const int keepTop,const double minARF,const double minSR,ExportRecord &expArr[])'),/expArr\[i\]\.arf \* expArr\[i\]\.sr/,'the trim ranks on the stored (fit+FWD when blind) ARF x SR');
 ok();}
// FetchMetric (Tester.mqh), converted: the exporter reads a file name's metrics with it.
const tester=norm(fs.readFileSync(path.join(ROOT,'Tester.mqh'),'utf8'));
let fetch=unit(tester,'double FetchMetric(string filename, string metric)');
fetch=fetch.replace(/^double FetchMetric\(string filename, string metric\)/,'function FetchMetric(filename,metric)').replace(/\/\/.*$/gm,'')
 .replace(/\bint pos = -1, last = -1;/,'let pos=-1,last=-1;').replace(/\bstring parts\[\];/,'let parts=[];').replace(/'_'/g,'95')
 .replace(/\b(?:int|string) (?=\w+\s*=)/g,'let ');
const fx={StringFind:(s,q,from=0)=>s.indexOf(q,from),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),StringLen:s=>s.length,
 StringSplit:(s,ch,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(ch)));return out.length;},StringToDouble:s=>{const v=parseFloat(s);return Number.isFinite(v)?v:0;}};
vm.createContext(fx);vm.runInContext(fetch,fx);
assert.match(main,/double Lots_Adjusted = NormalizeLots\(Lots_Old \* \(TargetDD \/ MathMax\(r\.dd,1\.0\)\),strT\.symbol\);/,'AdjustLots scales on the record DD');
assert.match(main,/expArr\[n\]\.dd       = FetchMetric\(exports\[0\],"DD"\);/,'which is the file name DD');
// One export: OnTester's description (full-span lines, BOOS, SAMPLE, FWD, FOOS, news), the file name and the SET content,
// lots after AdjustLots (TargetDD 1000 on the name's DD) included.
function exportOf(pts,{boos,foos,blind,boosLine='; BOOS:   2025.01.06-'+date(boos)+' Days=30 Trades=9 PL=120',newsSkips=0}){
 const c=harness({boos,foos,blind,trdIS:41});
 c.deals=pts.filter((_,i)=>i%37===0).map(([time],i)=>({time,type:i%5===4?2:i%2,profit:((i*7919)%400)-180,commission:-1.5}));
 for(const [t,e] of pts){c.now=t;c.equity=e;c.GoatRankTick();}
 c.now=pts.at(-1)[0];
 const net=pts.at(-1)[1]-pts[0][1],foosStart=pts.find(([t])=>t>=foos),foosPL=pts.at(-1)[1]-(foosStart?foosStart[1]:pts.at(-1)[1]);
 const desc=['; '+'-'.repeat(40),'; GOAT V1.49 EURUSD,M1','; Days=210 Weeks=42.0 Months=9.7','; Trades=88 Sequences=12','; PF=1.234 RF=2.000 SR=1.500 ARF='+(net/1e5).toFixed(3),
  '; Return='+net.toFixed(0)+' MonthlyRet=1 DD=900','; '+'-'.repeat(40),boosLine,
  '; SAMPLE: '+date(boos)+'-'+date(foos)+' Days=100 Trades=41 PL=640','; FWD:    2025.04.01-2025.05.30 Days=40 Trades=12 PL=200',
  '; FOOS:   '+date(foos)+'-'+date(pts.at(-1)[0])+' Days=20 Trades=7 PL='+foosPL.toFixed(0),'; '+'-'.repeat(40)+'\n; NEWS: News Events=3 SkippedSequenceStarts='+newsSkips].join('\n');
 const full='_Trds=88_Prf='+net.toFixed(0)+'_DD=900_PF=1.23_SR=1.50_ARF='+(net/1e5).toFixed(3);
 const metrix=blind?c.GoatRankMetrix():full,name='GOAT V1.49 EURUSD,M1'+metrix+'.set';
 const lots=Math.round(0.10*(1000/Math.max(fx.FetchMetric(name,'DD'),1.0))*100)/100;
 const head=blind?c.GoatBlindDesc(desc):desc+'\n; EXPORT blind:0 ranked:full_span sr:mt5_stat';
 const content=(head+'\r\n; ===========GENERAL SETTINGS============\r\nMode_Operation=9\r\nEA_Desc=R0001\r\nLots_Input='+lots.toFixed(2)+'\r\nGrid_Size=-2.25\r\n');
 return {c,name,content,lots,ranked:content.split('\n').find(l=>l.startsWith('; RANKED '))};
}
// 7) A blind export is blind (goatai#2350 6127809765, condition 1): replace every FOOS bar and deal (a different
//    holdout) and the blind=1 export's file name and full SET content, lots after AdjustLots included, are byte-identical.
//    The same two runs exported with blind=0 differ (the fixture does reach the full-span lines).
{seed=777;const shared=stream(160);
 const boos=midnight(shared[Math.floor(shared.length*0.25)][0]),foos=midnight(shared.at(-1)[0])+DAY;
 const holdout=(s,drift)=>{seed=s;const out=[];let e=shared.at(-1)[1];for(let k=1;k<=400;k++){e+=(rnd()-drift)*150;out.push([foos+k*600,Math.round(e*100)/100]);}return out;};
 const h1=holdout(1,0.40),h2=holdout(2,0.62);
 const a=exportOf([...shared,...h1],{boos,foos,blind:true,newsSkips:1}),b=exportOf([...shared,...h2],{boos,foos,blind:true,newsSkips:2});
 assert.equal(a.name,b.name,'file name');assert.equal(a.content,b.content,'full SET content, lots included');assert.equal(a.lots,b.lots);
 assert.match(a.content,/; EXPORT blind:1 ranked:fit\+fwd sr:daily_ann\n; RANKED fit\+fwd /);
 assert.ok(a.content.split('\n').filter(l=>/^; (EXPORT|RANKED)/.test(l)).every(l=>!l.includes('=')),'neither line holds =');
 assert.ok(!/FOOS|NEWS|Return=|PF=1\.234/.test(a.content),'no full-span, FOOS or news line in a blind SET');
 assert.match(a.content,/; GOAT V1\.49 EURUSD,M1\n; -+\n; SAMPLE:.*\n; FWD:/,'the SAMPLE and FWD window lines stay');
 const a0=exportOf([...shared,...h1],{boos,foos,blind:false,newsSkips:1}),b0=exportOf([...shared,...h2],{boos,foos,blind:false,newsSkips:2});
 assert.notEqual(a0.name,b0.name,'blind=0 names do depend on FOOS (sanity)');assert.notEqual(a0.content,b0.content);
 // The ranking metrics in the name are the window's: Prf is the RANKED PL, SR and ARF its SR and ARF.
 const ranked=parse(a.ranked.replace(/\r$/,''));
 assert.equal(fx.FetchMetric(a.name,'Prf'),Math.round(Number(ranked.PL)));assert.equal(fx.FetchMetric(a.name,'Trds'),41);
 assert.equal(fx.FetchMetric(a.name,'SR').toFixed(2),Number(ranked.SR).toFixed(2));ok();}
// 6) blind=0 no-drift: with the B44 lines taken out, StartExporter and RunAndStoreSet are c708cae4's text.
let compared=false;
try{
 const old=norm(execFileSync('git',['show',B43_SOURCE+':GOAT V1.49.mq5'],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
 compared=true;
 const exporter=unit(main,'bool StartExporter(bool reportMode)').replace('+(BlindExport ? ",blind=1" : "")','');
 assert.equal(exporter,unit(old,'bool StartExporter(bool reportMode)'));
 let store=unit(main,'int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false,const int startAttempts=20)');
 const a=store.indexOf('   // B44 item 5: with BlindExport'),b=store.indexOf('   if(profit>0)');
 store=(store.slice(0,a)+store.slice(b)).replace('(BlindExport ? rank_sr  : FetchMetric(exports[0],"SR"))','FetchMetric(exports[0],"SR")')
  .replace('(BlindExport ? rank_arf : FetchMetric(exports[0],"ARF"))','FetchMetric(exports[0],"ARF")')
  .replace('\n                                                             +(BlindExport ? " (ranked on fit+FWD: PL="+DoubleToString(rank_pl,0)+")" : "")','')
  .replace('+(BlindExport ? " on fit+FWD" : "")','');
 const oldStore=unit(old,'int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false,const int startAttempts=20)');
 assert.equal(store.replace('\n\n   if(profit>0)','\n   if(profit>0)'),oldStore.replace('\n\n   if(profit>0)','\n   if(profit>0)'));
 ok();
}catch(e){if(e instanceof assert.AssertionError)throw e;}
// 8) B45 item 2: BOOS-free. (a) The blind SET carries no BOOS line. (b) Two runs whose BOOS differs (another P/L,
//    trade count and path; the window moves the same) give the same RANKED line, name and SET: the window is measured
//    on the equity less the BOOS P/L, so no return or ARF denominator holds a BOOS result. (c) trd_FOOS, trd_IS and
//    trd_BOOS split entries at the RANKED window's bounds: an entry at dt_Fwrd_OOS is FOOS (B44 counted it in trd_IS).
{seed=4242;const win=stream(100,30,{from:MON+35*DAY});const boos=MON+35*DAY,foos=MON+128*DAY;
 // BOOS runs that end at their high (no BOOS drawdown below the window's): the window moves are identical.
 const boosRun=(slope,start)=>{const out=[];let e=start;for(let d=0;d<35;d++){const day=MON+d*DAY;if([0,6].includes(new Date(day*1000).getUTCDay()))continue;
  for(let k=0;k<20;k++){out.push([day+k*600,Math.round(e*100)/100]);e+=slope;}}return out;};
 const glue=(pre)=>{const base=win[0][1],end=pre.at(-1)[1];return [...pre,...win.map(([t,e])=>[t,Math.round((e-base+end)*100)/100])];};
 const lowBoos=glue(boosRun(0.5,100000)),highBoos=glue(boosRun(40,100000));
 assert.ok(highBoos.find(([t])=>t>=boos)[1]-lowBoos.find(([t])=>t>=boos)[1]>9000,'the two BOOS P/L differ widely');
 const x=exportOf(lowBoos,{boos,foos,blind:true,boosLine:'; BOOS:   2025.01.06-'+date(boos)+' Days=25 Trades=3 PL=250'});
 const y=exportOf(highBoos,{boos,foos,blind:true,boosLine:'; BOOS:   2025.01.06-'+date(boos)+' Days=25 Trades=60 PL=20000'});
 assert.ok(!/BOOS/.test(x.content),'(a) no BOOS line or value in a blind SET');
 assert.equal(x.ranked,y.ranked,'(b) the RANKED line does not see the BOOS P/L');assert.equal(x.name,y.name);assert.equal(x.content,y.content);
 // The shift is the BOOS P/L; the controller's unshifted opening would hold it (its SR then differs).
 const refs=python([{pts:lowBoos,boos,foos},{pts:highBoos,boos,foos}]);
 assert.ok(refs[1].shift>refs[0].shift+9000);near(x.c.g_GoatRankShift,refs[0].shift,'low shift');near(y.c.g_GoatRankShift,refs[1].shift,'high shift');
 parity(x.c,refs[0],'BOOS low');parity(y.c,refs[1],'BOOS high');
 assert.ok(Math.abs((refs[1].raw.sharpe??0)-(refs[1].window.sharpe??0))>1e-6,'(the unshifted SR would have moved with the BOOS P/L)');
 // (c) The entry classification of OnTradeTransaction (GoatTradeTransactionBody), converted, against GoatRankTick's window.
 const tt=unit(main,'void GoatTradeTransactionBody(');
 const lines=tt.split('\n').filter(l=>/trd_(BOOS|FOOS|IS)\+\+/.test(l)).map(l=>l.replace(/\/\/.*$/,'').trim());
 assert.deepEqual(lines,['if(TimeCurrent()<dt_Back_OOS && dt_Back_OOS!=0) trd_BOOS++;','else if(TimeCurrent()>=dt_Fwrd_OOS && dt_Fwrd_OOS!=0) trd_FOOS++;',
  'else                                                 trd_IS++;']);
 const classify=new Function('TimeCurrent','dt_Back_OOS','dt_Fwrd_OOS','let trd_BOOS=0,trd_FOOS=0,trd_IS=0;'+lines.join('\n')+'\nreturn trd_BOOS?"BOOS":trd_FOOS?"FOOS":"IS";');
 for(const [t,want] of [[boos-1,'BOOS'],[boos,'IS'],[boos+1,'IS'],[foos-1,'IS'],[foos,'FOOS'],[foos+1,'FOOS']]){
  assert.equal(classify(()=>t,boos,foos),want,'entry at '+(t-boos)+'s from BOOS end');
  const c=harness({boos,foos});c.now=t;c.equity=100000;c.GoatRankTick();
  assert.equal(c.g_GoatRankOpened,want==='IS','the RANKED window at '+t+' agrees with trd_IS');
 }
 assert.equal(classify(()=>foos,0,0),'IS','no window dates: every entry is IS');
 ok();}
// 9) B45 item 3: blind + AdjustLots sizes on the drawdown over every non-FOOS tick. A BOOS drawdown deeper than any in
//    the window sets the name's DD (so the lots), the RANKED line still does not see it, and FOOS never does.
{seed=99;const win=stream(90,30,{from:MON+42*DAY});const boos=MON+42*DAY,foos=MON+120*DAY;
 const pre=(depth)=>{const out=[];for(let d=0;d<42;d++){const day=MON+d*DAY;if([0,6].includes(new Date(day*1000).getUTCDay()))continue;
  for(let k=0;k<20;k++){const v=100000-depth*Math.sin(Math.PI*(d*20+k)/(42*20));out.push([day+k*600,Math.round(v*100)/100]);}}return out;};
 const glue=(p)=>{const base=win[0][1],end=p.at(-1)[1];return [...p,...win.map(([t,e])=>[t,Math.round((e-base+end)*100)/100])];};
 const tail=(pts,s)=>{seed=s;const out=[];let e=pts.at(-1)[1];for(let k=1;k<=300;k++){e+=(rnd()-0.7)*400;out.push([foos+k*600,Math.round(e*100)/100]);}return [...pts,...out];};
 const shallow=glue(pre(10)),deep=glue(pre(6000));
 const s=exportOf(tail(shallow,5),{boos,foos,blind:true}),d=exportOf(tail(deep,5),{boos,foos,blind:true}),d2=exportOf(tail(deep,6),{boos,foos,blind:true});
 const refs=python([{pts:shallow,boos,foos},{pts:deep,boos,foos}]);
 assert.ok(refs[1].sizingDd>=5900&&refs[1].sizingDd>refs[1].window.maxDd*1.5,'the deep BOOS drawdown is the deepest non-FOOS one');
 near(fx.FetchMetric(d.name,'DD'),Math.round(refs[1].sizingDd),'the name DD is the non-FOOS drawdown');
 near(fx.FetchMetric(s.name,'DD'),Math.round(refs[0].sizingDd),'(shallow BOOS: the window drawdown dominates)');
 assert.ok(fx.FetchMetric(d.name,'DD')>d.c.g_GoatRankMaxDD+1000,'B44 named the window drawdown, which is smaller');
 assert.ok(d.lots<s.lots,'a deeper non-FOOS drawdown never gets larger lots: '+d.lots+' < '+s.lots);
 assert.equal(d.lots,Math.round(0.10*(1000/Math.round(refs[1].sizingDd))*100)/100,'lots = 0.10 x TargetDD / non-FOOS DD');
 assert.equal(d.ranked,s.ranked,'ranking stays BOOS-blind');assert.equal(d.content,d2.content,'and FOOS-blind');assert.equal(d.name,d2.name);
 assert.match(main,/"_DD="\+DoubleToString\(g_GoatRankSizeDD,0\)/,'GoatRankMetrix names g_GoatRankSizeDD');
 ok();}
console.log(JSON.stringify({passed,b43UnitsCompared:compared,pythonReference:'controller/studio_window_metrics.py',nativeTester:false}));
