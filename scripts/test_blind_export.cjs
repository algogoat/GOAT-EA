// B44 item 5 (goatai#2350): BlindExport. Off by default, appended as the last input (append-only, WriteSet never
// writes it). On: the exporter adds blind=1 to each export run's EA_Desc @{...}; that tester run measures the fit+FWD
// window (SAMPLE: dt_BOOS_end to dt_FOOS_start) and writes "; EXPORT: blind=1 ranked=fit+fwd" plus a "; RANKED:" line;
// RunAndStoreSet's profit floor and the SR/ARF it stores (so the MinSR/MinARF count and SortAndTrimExports) come from
// that line. Off: every export is stamped "; EXPORT: blind=0 ranked=full_span" and nothing else changes.
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
 .replace(/^string (\w+)\(void\)/gm,'function $1()')
 .replace(/^bool GoatReadRankedLine\(const string rank_text,double &rank_pl,double &rank_sr,double &rank_arf\)/m,'function GoatReadRankedLine(rank_text,out)');
const reader=unit(code,'function GoatReadRankedLine(rank_text,out)');
code=code.replace(reader,reader.replace(/\brank_(pl|sr|arf)\b/g,'out.$1'));
code=code.replace(/\(long\)rank_now\/86400/g,'Math.floor(rank_now/86400)')
 .replace(/\bdouble dds\[5\];/g,'let dds=[];').replace(/\bstring (\w+)\[\];/g,'let $1=[];')
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
  StringToDouble:s=>{const v=parseFloat(s);return Number.isFinite(v)?v:0;},MathIsValidNumber:Number.isFinite};
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
const parse=line=>Object.fromEntries(line.split(' ').filter(x=>x.includes('=')).map(x=>x.split('=')));
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
 assert.ok(line.startsWith('; RANKED: fit+fwd '+date(boos)+'-'+date(foos)+' '),line);
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
 const good='; SAMPLE: x\n; EXPORT: blind=1 ranked=fit+fwd\r\n; RANKED: fit+fwd 2025.01.01-2025.06.01 Days=100 Trades=40 PL=-12.50 SR=1.234 ARF=0.456\r\nRisk=500\n';
 assert.deepEqual(read(good),[true,-12.5,1.234,0.456]);
 for(const [label,text] of [['no stamp',good.replace('; EXPORT: blind=1 ranked=fit+fwd\r\n','')],['blind=0 stamp',good.replace('blind=1 ranked=fit+fwd','blind=0 ranked=full_span')],
  ['no ranked line',good.replace(/; RANKED:.*\r\n/,'')],['two ranked lines',good.replace(/(; RANKED:.*\r\n)/,'$1$1')],['no SR',good.replace(' SR=1.234','')],
  ['empty ARF',good.replace('ARF=0.456','ARF=')],['empty file','']]) {assert.equal(read(text)[0],false,label);}
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
 assert.match(main,/if\(g_GoatBlindExport\) WriteSet\(desc\+"\\n; EXPORT: blind=1 ranked=fit\+fwd\\n"\+GoatRankLine\(\)\);\n\s+else\s+WriteSet\(desc\+"\\n; EXPORT: blind=0 ranked=full_span"\);/);
 assert.match(main,/GoatRankTick\(\); \/\/ B44 item 5/);
 const store=unit(main,'int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false,const int startAttempts=20)');
 assert.ok(store.indexOf('profit=rank_pl;')<store.indexOf('if(profit>0)'),'the floor reads the fit+FWD PL');
 assert.match(store,/expArr\[n\]\.sr       = \(BlindExport \? rank_sr  : FetchMetric\(exports\[0\],"SR"\)\);/);
 assert.match(store,/expArr\[n\]\.arf      = \(BlindExport \? rank_arf : FetchMetric\(exports\[0\],"ARF"\)\);/);
 const tester=norm(fs.readFileSync(path.join(ROOT,'Tester.mqh'),'utf8'));
 assert.match(unit(tester,'void SortAndTrimExports(const int keepTop,const double minARF,const double minSR,ExportRecord &expArr[])'),/expArr\[i\]\.arf \* expArr\[i\]\.sr/,'the trim ranks on the stored (fit+FWD when blind) ARF x SR');
 ok();}
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
console.log(JSON.stringify({passed,b43UnitsCompared:compared,nativeTester:false}));
