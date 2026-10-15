// B44 item 5 (goatai#2350): BlindExport. Off by default, appended as the last input (append-only, WriteSet never
// writes it). On: the exporter adds blind=1 to each export run's EA_Desc @{...}; that tester run measures the fit+FWD
// window (SAMPLE: dt_BOOS_end to dt_FOOS_start) and writes "; EXPORT blind:1 ranked:fit+fwd sr:daily_ann" plus a "; RANKED" line;
// RunAndStoreSet's profit floor and the SR/ARF it stores (so the MinSR/MinARF count and SortAndTrimExports) come from
// that line. Off: every export is stamped "; EXPORT blind:0 ranked:full_span sr:mt5_stat" and nothing else changes. Neither line
// holds "=" (goatai#2350 6128225191), so no controller writer copies them into a deployed chart.
// This runs the production GoatRankTick / GoatRankLine / GoatReadRankedLine after a syntax-only MQL-to-JS conversion
// against modelled equity streams, compares them with an independent implementation of the definitions, and pins the
// wiring and the blind=0 no-drift against c708cae4. Native tester runs are not exercised here.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
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
 .replace(/^void (\w+)\(const double (\w+)\)/gm,'function $1($2)').replace(/^void (\w+)\(void\)/gm,'function $1()')
 .replace(/^string (\w+)\(void\)/gm,'function $1()').replace(/^double (\w+)\(void\)/gm,'function $1()')
 .replace(/^string GoatBlindDesc\(const string rank_desc\)/m,'function GoatBlindDesc(rank_desc)')
 .replace(/^bool GoatReadRankedLine\(const string rank_text,double &rank_pl,double &rank_sr,double &rank_arf\)/m,'function GoatReadRankedLine(rank_text,out)');
const reader=unit(code,'function GoatReadRankedLine(rank_text,out)');
code=code.replace(reader,reader.replace(/\brank_(pl|sr|arf)\b/g,'out.$1'));
code=code.replace(/\(long\)rank_now\/86400/g,'Math.floor(rank_now/86400)')
 .replace(/\bdouble dds\[5\];/g,'let dds=[];').replace(/\bstring (\w+)\[\];/g,'let $1=[];').replace(/\bstring (\w+)\[\],/g,'let $1=[],')
 .replace(/\(datetime\)/g,'').replace(/\bulong (?=\w+=)/g,'let ')
 .replace(/\b(?:const )?(?:string|double|int|long|bool|datetime) (?=[a-z_]\w*\s*[=;,])/g,'let ')
 .replace(/StringTrimLeft\((\w+)\)/g,'$1=$1.trimStart()').replace(/StringTrimRight\((\w+)\)/g,'$1=$1.trimEnd()')
 .replace(/'\\n'/g,'10').replace(/' '/g,'32');
const date=s=>{const d=new Date(s*1000);return d.getUTCFullYear()+'.'+String(d.getUTCMonth()+1).padStart(2,'0')+'.'+String(d.getUTCDate()).padStart(2,'0');};
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
// An independent implementation of the definitions (controller studio_window_metrics.py ea_mean_dd + daily Sharpe).
function reference(points,from,to){
 const inside=points.filter(([t])=>(from===0||t>=from)&&(to===0||t<to));
 const open=inside[0][1],close=inside.at(-1)[1];
 let peak=open,ep=0;const eps=[];
 for(const [,e] of inside){if(e>peak){if(ep>0)eps.push(ep);peak=e;ep=0;}ep=Math.max(ep,peak-e);}
 if(ep>0)eps.push(ep);
 const d=[...eps].sort((a,b)=>b-a).slice(0,5);while(d.length<5)d.push(0);
 let mean;
 if(d[0]===0)mean=999999;else if(d[1]===0||d[1]<0.1*d[0]||d[1]<0.5*d[0])mean=d[0];
 else if(d[2]===0||d[2]<0.1*d[0]||d[2]<0.5*d[1])mean=(d[0]*6+d[1]*5)/11;else if(d[3]===0||d[3]<0.1*d[0]||d[3]<0.5*d[2])mean=(d[0]*7+d[1]*6+d[2]*5)/18;
 else if(d[4]===0||d[4]<0.1*d[0]||d[4]<0.5*d[3])mean=(d[0]*8+d[1]*7+d[2]*6+d[3]*5)/26;else mean=(d[0]*9+d[1]*8+d[2]*7+d[3]*6+d[4]*5)/35;
 const ret=(close-open)/open;if(ret<0)mean=d[0];if(mean===0)mean=open/2;
 const days=new Set(inside.map(([t])=>Math.floor(t/86400)));
 const arf=(ret/(mean/open))/(days.size/21.7);
 // Day marks: the first equity of each day; returns between marks, then the close against the last mark.
 const marks=[];let last=null;for(const [t,e] of inside){const day=Math.floor(t/86400);if(day!==last){marks.push(e);last=day;}}
 const rets=[];for(let i=1;i<marks.length;i++)rets.push(marks[i]/marks[i-1]-1);rets.push(close/marks.at(-1)-1);
 let sr=0;if(rets.length>=2){const m=rets.reduce((a,b)=>a+b,0)/rets.length;const v=rets.reduce((a,b)=>a+(b-m)**2,0)/(rets.length-1);if(v>0)sr=m/Math.sqrt(v)*Math.sqrt(252);}
 return {pl:close-open,arf,sr,days:days.size};
}
const parse=line=>{assert.ok(!line.includes('='),'a RANKED line holds no =: '+line);return Object.fromEntries(line.split(' ').filter(x=>x.includes(':')).map(x=>x.split(':')));};
let seed=20261012;const rnd=()=>(seed=(seed*48271)%2147483647)/2147483647;
function stream(days=180,ticks=40){const out=[];let e=100000,t=Date.UTC(2025,0,6)/1000;
 for(let d=0;d<days;d++){const day=t+d*86400;if([0,6].includes(new Date(day*1000).getUTCDay()))continue;
  for(let k=0;k<ticks;k++){e+=(rnd()-0.48)*120;out.push([day+k*600,Math.round(e*100)/100]);}}
 return out;}

// 1) The RANKED line equals the independent definitions on random equity, inside the window only.
for(let run=0;run<6;run++){
 const pts=stream(200);const boos=pts[Math.floor(pts.length*0.2)][0]-pts[Math.floor(pts.length*0.2)][0]%86400;
 const foos=pts[Math.floor(pts.length*0.85)][0]-pts[Math.floor(pts.length*0.85)][0]%86400;
 const c=harness({boos,foos});for(const [t,e] of pts){c.now=t;c.equity=e;c.GoatRankTick();}
 const line=c.GoatRankLine(),got=parse(line),want=reference(pts,boos,foos);
 assert.ok(line.startsWith('; RANKED fit+fwd '+date(boos)+'-'+date(foos)+' '),line);
 assert.equal(Number(got.Days),want.days);assert.equal(got.Trades,'7');
 assert.equal(got.PL,want.pl.toFixed(2));assert.equal(got.SR,want.sr.toFixed(3),'SR run '+run);assert.equal(got.ARF,want.arf.toFixed(3),'ARF run '+run);
 ok();
}
// 2) Off (blind=0 or no blind key): nothing is measured.
{const c=harness({blind:false});for(const [t,e] of stream(20)){c.now=t;c.equity=e;c.GoatRankTick();}
 assert.equal(c.g_GoatRankOpened,false);assert.equal(c.g_GoatRankDays,0);ok();}
// 3) A losing window: Return < 0 uses the deepest episode, as OnTester does; a flat window is ARF 0.
{const pts=[[86400*20000,100000],[86400*20000+60,99000],[86400*20001,99500],[86400*20002,98000]];
 const c=harness();for(const [t,e] of pts){c.now=t;c.equity=e;c.GoatRankTick();}
 const got=parse(c.GoatRankLine()),want=reference(pts,0,0);
 assert.deepEqual([got.PL,got.ARF,got.SR],[want.pl.toFixed(2),want.arf.toFixed(3),want.sr.toFixed(3)]);assert.ok(Number(got.ARF)<0);
 const flat=harness();for(let i=0;i<5;i++){flat.now=86400*(20000+i);flat.equity=100000;flat.GoatRankTick();}
 assert.deepEqual([parse(flat.GoatRankLine()).ARF,parse(flat.GoatRankLine()).PL],['0.000','0.00']);ok();}
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
// 7) A blind export is blind (goatai#2350 6127809765, condition 1): replace every FOOS bar and deal (a different
//    holdout) and the blind=1 export's file name and full SET content, lots after AdjustLots included, are byte-identical.
//    The same two runs exported with blind=0 differ (the fixture does reach the full-span lines).
{const tester=norm(fs.readFileSync(path.join(ROOT,'Tester.mqh'),'utf8'));
 let fetch=unit(tester,'double FetchMetric(string filename, string metric)');
 fetch=fetch.replace(/^double FetchMetric\(string filename, string metric\)/,'function FetchMetric(filename,metric)').replace(/\/\/.*$/gm,'')
  .replace(/\bint pos = -1, last = -1;/,'let pos=-1,last=-1;').replace(/\bstring parts\[\];/,'let parts=[];').replace(/'_'/g,'95')
  .replace(/\b(?:int|string) (?=\w+\s*=)/g,'let ');
 const fx={StringFind:(s,q,from=0)=>s.indexOf(q,from),StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),StringLen:s=>s.length,
  StringSplit:(s,ch,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(ch)));return out.length;},StringToDouble:s=>{const v=parseFloat(s);return Number.isFinite(v)?v:0;}};
 vm.createContext(fx);vm.runInContext(fetch,fx);
 assert.match(main,/double Lots_Adjusted = NormalizeLots\(Lots_Old \* \(TargetDD \/ MathMax\(r\.dd,1\.0\)\),strT\.symbol\);/,'AdjustLots scales on the record DD');
 assert.match(main,/expArr\[n\]\.dd       = FetchMetric\(exports\[0\],"DD"\);/,'which is the file name DD');
 seed=777;const shared=stream(160),day=86400;
 const boos=shared[Math.floor(shared.length*0.25)][0]-shared[Math.floor(shared.length*0.25)][0]%day;
 const foos=shared[shared.length-1][0]-shared[shared.length-1][0]%day+day;
 const holdout=(s,drift)=>{seed=s;const out=[];let e=shared.at(-1)[1];for(let k=1;k<=400;k++){e+=(rnd()-drift)*150;out.push([foos+k*600,Math.round(e*100)/100]);}return out;};
 const deals=pts=>pts.filter((_,i)=>i%37===0).map(([time],i)=>({time,type:i%5===4?2:i%2,profit:((i*7919)%400)-180,commission:-1.5}));
 function exportOf(post,blind){
  const pts=[...shared,...post],c=harness({boos,foos,blind,trdIS:41});c.deals=deals(pts);
  for(const [t,e] of pts){c.now=t;c.equity=e;c.GoatRankTick();}
  c.now=pts.at(-1)[0];
  const net=pts.at(-1)[1]-pts[0][1],foosPL=pts.at(-1)[1]-shared.at(-1)[1];
  // OnTester's description: full-span lines, the window lines (fixed before FOOS), the FOOS line, the news line.
  const desc=['; '+'-'.repeat(40),'; GOAT V1.49 EURUSD,M1','; Days=210 Weeks=42.0 Months=9.7','; Trades=88 Sequences=12','; PF=1.234 RF=2.000 SR=1.500 ARF='+(net/1e5).toFixed(3),
   '; Return='+net.toFixed(0)+' MonthlyRet=1 DD=900','; '+'-'.repeat(40),'; BOOS:   2025.01.06-'+date(boos)+' Days=30 Trades=9 PL=120',
   '; SAMPLE: '+date(boos)+'-'+date(foos)+' Days=100 Trades=41 PL=640','; FWD:    2025.04.01-2025.05.30 Days=40 Trades=12 PL=200',
   '; FOOS:   '+date(foos)+'-'+date(pts.at(-1)[0])+' Days=20 Trades=7 PL='+foosPL.toFixed(0),'; '+'-'.repeat(40)+'\n; NEWS: News Events=3 SkippedSequenceStarts='+post.length%7].join('\n');
  const full='_Trds=88_Prf='+net.toFixed(0)+'_DD=900_PF=1.23_SR=1.50_ARF='+(net/1e5).toFixed(3);
  const metrix=blind?c.GoatRankMetrix():full,name='GOAT V1.49 EURUSD,M1'+metrix+'.set';
  const lots=Math.round(0.10*(1000/Math.max(fx.FetchMetric(name,'DD'),1.0))*100)/100;
  const head=blind?c.GoatBlindDesc(desc):desc+'\n; EXPORT blind:0 ranked:full_span sr:mt5_stat';
  const content=(head+'\r\n; ===========GENERAL SETTINGS============\r\nMode_Operation=9\r\nEA_Desc=R0001\r\nLots_Input='+lots.toFixed(2)+'\r\nGrid_Size=-2.25\r\n');
  return {name,content,lots};
 }
 const a=exportOf(holdout(1,0.40),true),b=exportOf(holdout(2,0.62),true);
 assert.equal(a.name,b.name,'file name');assert.equal(a.content,b.content,'full SET content, lots included');assert.equal(a.lots,b.lots);
 assert.match(a.content,/; EXPORT blind:1 ranked:fit\+fwd sr:daily_ann\n; RANKED fit\+fwd /);
 assert.ok(a.content.split('\n').filter(l=>/^; (EXPORT|RANKED)/.test(l)).every(l=>!l.includes('=')),'neither line holds =');
 assert.ok(!/FOOS|NEWS|Return=|PF=1\.234/.test(a.content),'no full-span, FOOS or news line in a blind SET');
 assert.match(a.content,/; BOOS:.*\n; SAMPLE:.*\n; FWD:/,'the window lines stay');
 const a0=exportOf(holdout(1,0.40),false),b0=exportOf(holdout(2,0.62),false);
 assert.notEqual(a0.name,b0.name,'blind=0 names do depend on FOOS (sanity)');assert.notEqual(a0.content,b0.content);
 // The ranking metrics in the name are the window's: Prf is the RANKED PL, SR and ARF its SR and ARF.
 const ranked=parse(a.content.split('\n').find(l=>l.startsWith('; RANKED ')).replace(/\r$/,''));
 assert.equal(fx.FetchMetric(a.name,'Prf'),Math.round(Number(ranked.PL)));assert.equal(fx.FetchMetric(a.name,'Trds'),41);
 assert.equal(fx.FetchMetric(a.name,'SR').toFixed(2),Number(ranked.SR).toFixed(2));ok();}// 6) blind=0 no-drift: with the B44 lines taken out, StartExporter and RunAndStoreSet are c708cae4's text.
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
console.log(JSON.stringify({passed,b43UnitsCompared:compared,nativeTester:false}));
