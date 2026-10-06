// Export rule by FWD profit/DD and the research-only below_score export (GOAT-EA BS42, goatai#1885:
// Claude-Mac 6021965811, 6022008420, 6022264062, 6023896492 and 6025359910). Runs the production
// XmlProcessor ranking, the parameter-character, SAMPLE-correlation and SAMPLE-quality gates, the
// combiner, GoatExportSlots, StartBelowScoreExporter, the switched StartExporter and the V1.49
// OnTesterDeinit branch in a JS VM over simulated and REAL MT5 reports and equity CSVs and a stubbed
// Strategy Tester. MQL-free: no MetaEditor, MT5 or network. GOAT_EA_ROOT may point at another source
// tree (test_below_score_export_mutations.cjs runs every mutation through it). The slot-2 FOOS
// invariance check that must fail on the pre-fix code is test_slot2_foos_invariance.cjs.
process.env.GOAT_OUTCOME_HARNESS_ONLY='1';
process.env.GOAT_OUTCOME_EXTRA_DEFINES='GOAT_BELOW_SCORE_EXPORT_V149';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const H=require('./test_research_outcome.cjs');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const mainRaw=read('GOAT V1.49.mq5');
const FIXTURES=path.join(__dirname,'fixtures','below-score');
let passed=0;const check=fn=>{fn();passed++;};
const DEP=1000;   // tester deposit in the slot tests: the 0.25% drawdown floor is 2.5, below every test drawdown

// ---- The compile flags the V1.49 entrypoint really defines.
const FLAGS=new Set([...mainRaw.matchAll(/^#define\s+(\w+)/gm)].map(m=>m[1]));
check(()=>assert.ok(FLAGS.has('GOAT_BELOW_SCORE_EXPORT_V149'),'BS42 is on in V1.49'));
check(()=>assert.ok(!FLAGS.has('GOAT_EXPORT_RANK_FWD_PROFIT_DD'),'the normal-export ranking switch is OFF by default'));
check(()=>assert.match(mainRaw,/^\/\/#define GOAT_EXPORT_RANK_FWD_PROFIT_DD$/m,'the switch is one documented line'));
for(const version of ['1.47','1.48'])check(()=>assert.ok(!/GOAT_BELOW_SCORE_EXPORT_V149/.test(read('GOAT V'+version+'.mq5')),'older entrypoints untouched: '+version));

// ---- Ranking: FWD profit / max(FWD DD, 0.25% x deposit) among eligible passes.
const row=(o={})=>({pass:o.pass??1,back_result:o.back_result??0,back_profit:o.back_profit??500,back_PF:o.back_PF??1.5,back_RF:o.back_RF??3,
  back_SR:o.back_SR??1.2,back_DD_pc:o.back_DD_pc??5,back_trades:o.back_trades??120,forward_result:o.forward_result??0,forward_profit:o.forward_profit??100,
  forward_PF:o.forward_PF??1.3,forward_RF:o.forward_RF??1,forward_SR:o.forward_SR??1,forward_DD_pc:o.forward_DD_pc??4,forward_trades:o.forward_trades??40,
  Inputs:o.Inputs??'10,5',Score:o.Score??40,forward_seen:o.forward_seen??true});
const c=H.makeContext({});
const rank=(rows,min=-1,dep=DEP)=>{c.__rows=rows;const out=[];c.__out=out;vm.runInContext('GoatXmlFwdRank(__rows,'+min+','+dep+',__out)',c);return out.map(i=>rows[i].pass);};
const key=(r,dep)=>{c.__rows=[r];return vm.runInContext('GoatXmlFwdKey(__rows,0,'+dep+')',c);};
{
  const rows=[row({pass:1,forward_RF:1.2,Score:59}),row({pass:2,forward_RF:2.5,Score:12}),row({pass:3,forward_RF:0.8,Score:58}),
              row({pass:4,forward_RF:2.5,forward_profit:150,Score:5}),row({pass:5,forward_RF:9,forward_trades:29}),
              row({pass:6,forward_RF:9,forward_profit:-1}),row({pass:7,forward_RF:9,back_profit:0}),row({pass:8,forward_RF:9,back_trades:49}),
              row({pass:9,forward_RF:9,forward_seen:false}),row({pass:10,forward_RF:0,forward_profit:5}),row({pass:11,forward_RF:2.5,forward_profit:150})];
  check(()=>assert.deepEqual(rank(rows),[4,11,2,1,3],'FWD profit/DD first, then FWD profit, then the lower pass; the match score never ranks'));
  check(()=>assert.deepEqual(rank(rows,58),[1,3],'a score floor (normal exports) only filters'));
  check(()=>assert.deepEqual(rank(rows.slice().reverse()),[4,11,2,1,3],'row order never changes the ranking'));
  check(()=>assert.equal(vm.runInContext('__x=[];GoatXmlFwdRank([],-1,1000,__x)',c),0));
  check(()=>assert.deepEqual(rank(rows,-1,0),[],'an unknown tester deposit ranks nothing'));
  check(()=>assert.deepEqual(rank([row({pass:1,forward_trades:30}),row({pass:2,back_trades:50,forward_RF:0.5})]),[1,2]));
  // The drawdown floor (Claude-Mac 6025359910 item 6): $3 on a $0.10 drawdown (RF 30) never beats a robust pass.
  const tiny=row({pass:1,forward_profit:3,forward_RF:30}),robust=row({pass:2,forward_profit:400,forward_RF:2});
  check(()=>assert.deepEqual(rank([tiny,robust],-1,100000),[2,1],'floor = 0.25% of a 100,000 deposit = 250'));
  check(()=>assert.equal(key(tiny,100000),3/250));
  check(()=>assert.equal(key(robust,100000),400/250,'a 200 drawdown is also under the floor'));
  check(()=>assert.equal(key(row({forward_profit:900,forward_RF:2}),100000),2,'above the floor: profit / drawdown = RF'));
  // Every MQL row field outside eligibility and the FWD key never moves the order (randomised).
  let seed=7;const rnd=()=>((seed=(seed*1103515245+12345)%2147483648)/2147483648);
  for(let t=0;t<200;t++){
    const rows2=Array.from({length:12},(_,k)=>row({pass:k+1,forward_RF:Math.round(rnd()*40)/10,forward_profit:Math.round(rnd()*300)-20,
      forward_trades:20+Math.round(rnd()*40),back_profit:Math.round(rnd()*900)-50,back_trades:40+Math.round(rnd()*100),Score:rnd()*100}));
    const before=rank(rows2,-1,100000);
    for(const r of rows2){r.back_RF=rnd()*20;r.back_SR=rnd()*9;r.back_PF=rnd()*4;r.back_DD_pc=rnd()*30;r.back_result=rnd();r.forward_SR=rnd()*9;
      r.forward_PF=rnd()*4;r.forward_DD_pc=rnd()*30;r.forward_result=rnd();r.Score=rnd()*100;if(r.back_profit>0)r.back_profit=1+rnd()*5000;}
    check(()=>assert.deepEqual(rank(rows2,-1,100000),before,'a field outside the FWD key changed the order (trial '+t+')'));
  }
  const src=['GoatXmlFwdIneligibility','GoatXmlFwdEligible','GoatXmlFwdKey','GoatXmlFwdBetter','GoatXmlFwdRank'].map(n=>H.method(n)).join('\n');
  const fields=new Set([...src.matchAll(/\]\.(\w+)/g)].map(m=>m[1]));
  check(()=>assert.deepEqual([...fields].sort(),['Score','back_profit','back_trades','forward_RF','forward_profit','forward_seen','forward_trades','pass'].sort()));
}
// ---- MT5's Recovery Factor on a profitable pass with Equity DD % 0 (a REAL row; see the fixture's README).
{
  const xml=fs.readFileSync(path.join(FIXTURES,'mt5-profitable-zero-equity-dd-row.xml'),'utf8');
  const cells=[...xml.matchAll(/<Row>([\s\S]*?)<\/Row>/g)].map(m=>[...m[1].matchAll(/<Data ss:Type="\w+">([^<]*)<\/Data>/g)].map(x=>x[1]));
  const [head,values]=cells,get=n=>values[head.indexOf(n)];
  check(()=>assert.deepEqual([get('Profit'),get('Equity DD %'),get('Recovery Factor'),get('Trades')],['0.63','0.0000','0.62376238','1']));
  const real=row({forward_profit:+get('Profit'),forward_RF:+get('Recovery Factor')});
  check(()=>assert.ok(Math.abs(real.forward_profit/real.forward_RF-1.01)<1e-6,'MT5 still reports a 1.01 money drawdown: RF never 0 or infinite here'));
  check(()=>assert.equal(key(real,100000),0.63/250,'the floor ranks it by profit / 250'));
  check(()=>assert.ok(key(real,100000)<key(row({forward_profit:400,forward_RF:2}),100000)));
}

// ---- Parameter character (slot 2): the template's own key inputs.
{
  c.__names=['SL_Pips','TP_Pips','RSI_Mode','Grid_Size','TSL_Size','Mode_Trade','Lots_Exponent'];
  const diff=(a,b)=>vm.runInContext('GoatXmlCharacterDifference(__names,'+JSON.stringify(a)+','+JSON.stringify(b)+')',c);
  const base='0,2,1,-2.25,5,0,1.2';
  check(()=>assert.equal(diff(base,base),''));
  check(()=>assert.equal(diff(base,'0,2,1,-4.5,5,0,1.6'),'','grid and lots are not key inputs'));
  check(()=>assert.equal(diff(base,'10,2,1,-2.25,5,0,1.2'),'SL_Pips 0->10','a stop switched on'));
  check(()=>assert.equal(diff(base,'0,2,1,-2.25,9.9,0,1.2'),'','a size under twice the other'));
  check(()=>assert.equal(diff(base,'0,2,1,-2.25,10,0,1.2'),'TSL_Size 5->10','twice the size'));
  check(()=>assert.equal(diff(base,'0,2,1,-2.25,-5,0,1.2'),'TSL_Size 5->-5','pips vs ATR'));
  check(()=>assert.equal(diff(base,'0,2,2,-2.25,5,0,1.2'),'RSI_Mode 1->2','another entry mode'));
  check(()=>assert.equal(diff(base,'0,2,1,-2.25,5,1,1.2'),'Mode_Trade 0->1','another direction'));
  c.__names=['Grid_Size','Lots_Exponent'];
  check(()=>assert.equal(diff('1,2','5,9'),'','a template that optimizes no key input never differs in character'));
}

// ---- SAMPLE series: daily BALANCE closes, only days both curves logged (item 5).
const D=s=>H.epoch(s),DAY=86400;
function equityCsv(changes,{start='2025.01.06',skip=[],equity=(b)=>b-3}={}){
  const lines=['﻿<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'];
  let bal=100000,t=D(start);
  changes.forEach((x,k)=>{const day=H.date(t+k*DAY);bal+=x;if(skip.includes(k))return;   // a day without a row still trades
    lines.push(day+' 10:00\t'+bal.toFixed(2)+'\t'+equity(bal,k).toFixed(2)+'\t0.0',day+' 15:00\t'+bal.toFixed(2)+'\t'+equity(bal,k).toFixed(2)+'\t0.0');});
  return lines.join('\n');
}
vm.runInContext(H.method('GoatDailyReturnCorrelation').replace(/function GoatDailyReturnCorrelation\(([^)]*)\)/,'function GoatDailyReturnCorrelation(csvA,csvB,from,to)'),c);
const corr=(a,b,from=D('2025.01.01'),to=D('2026.01.01'))=>{c.n=0;c.__a=a;c.__b=b;const v=vm.runInContext('GoatDailyReturnCorrelation(__a,__b,'+from+','+to+')',c);return [v,c.n];};
const metrics=(csv,from,to)=>{c.__x=csv;c.__o=[];const ok=vm.runInContext('GoatEquityWindowMetrics(__x,'+from+','+to+',__o)',c);return ok?Array.from(c.__o):null;};
const wave=(n,f)=>Array.from({length:n},(_,k)=>f(k));
const A=wave(60,k=>Math.sin(k*0.7)*50+((k*37)%11)-5);
const B=wave(60,k=>Math.cos(k*1.9)*40+((k*53)%7)-3);
{
  const [same,n]=corr(equityCsv(A),equityCsv(A.map(x=>2*x+1)));
  check(()=>assert.ok(Math.abs(same-1)<1e-6,'a scaled copy correlates 1: '+same));
  check(()=>assert.equal(n,60,'60 commonly logged days'));
  check(()=>assert.ok(Math.abs(corr(equityCsv(A),equityCsv(A.map(x=>-x)))[0]+1)<1e-6));
  check(()=>assert.ok(Math.abs(corr(equityCsv(A),equityCsv(B))[0])<0.5,'independent curves'));
  const outside=A.map((x,k)=>k<30?x:-x);
  check(()=>assert.ok(Math.abs(corr(equityCsv(A),equityCsv(outside),D('2025.01.01'),D('2025.01.06')+30*DAY)[0]-1)<1e-6,'outside SAMPLE never counts'));
  // Balance, never the EQUITY cell (a throttled minute low): a noisy equity column changes nothing.
  check(()=>assert.ok(Math.abs(corr(equityCsv(A),equityCsv(A,{equity:(b,k)=>b-((k*7919)%97)}))[0]-1)<1e-6,'the EQUITY cell is never read'));
  // A day only one curve logged is not a common day: nothing is carried or filled in.
  const [gap,gn]=corr(equityCsv(A),equityCsv(A,{skip:[10]}));
  check(()=>assert.ok(Math.abs(gap-1)<1e-6&&gn===59,'59 common days, still the same curve: '+gap));
  // A sparse curve (logged every 3rd day) shares only 20 days with a dense one: the changes run day 0 -> 3 -> 6.
  const sparse=equityCsv(A,{skip:wave(60,k=>k).filter(k=>k%3)});
  const [rs,ns]=corr(equityCsv(A),sparse);
  check(()=>assert.ok(ns===20&&Math.abs(rs-1)<1e-6,'the same curve logged sparsely is still the same curve: '+[rs,ns]));
  check(()=>assert.equal(corr(equityCsv(A.slice(0,19)),equityCsv(A.slice(0,19)))[0],Number.MAX_VALUE,'19 common days: not shown different'));
  check(()=>assert.notEqual(corr(equityCsv(A.slice(0,20)),equityCsv(B.slice(0,20)))[0],Number.MAX_VALUE,'20 common days: measured'));
  check(()=>assert.equal(corr(equityCsv(A),equityCsv(A.map(()=>0)))[0],Number.MAX_VALUE,'a flat curve: unknown'));
  check(()=>assert.equal(corr('','')[0],Number.MAX_VALUE,'unreadable: unknown'));
  const backwards=equityCsv(A).split('\n');backwards.splice(9,0,'2025.01.06 23:00\t1\t1\t0');
  check(()=>assert.equal(corr(backwards.join('\n'),equityCsv(A))[0],Number.MAX_VALUE,'rows back in time: unreadable'));
}
// REAL export CSVs (two units of one AUDUSD member, R0605ee2d6f47; README.json has their provenance).
{
  const real=n=>fs.readFileSync(path.join(FIXTURES,n)).toString('utf16le').replace(/^﻿/,'');
  const a=real('real-AUDUSD-Trds184.csv'),b=real('real-AUDUSD-Trds287.csv');
  const from=D('2026.03.02'),to=D('2026.08.15');   // their SET headers' SAMPLE: 2026.03.02-2026.08.15, Days=120
  const [rho,common]=corr(a,b,from,to);
  check(()=>assert.equal(common,49,'49 days both units logged inside SAMPLE (the EA logs a row only on some days)'));
  check(()=>assert.ok(rho>0.85&&rho<0.87,'neighbours of one template: 0.862, not shown different: '+rho));
  const ma=metrics(a,from,to),mb=metrics(b,from,to);
  check(()=>assert.equal(Math.round(ma[0]),712,'SAMPLE net from balance closes = the SET header SAMPLE PL=712'));
  check(()=>assert.equal(Math.round(mb[0]),2140,'and PL=2140 for the other unit'));
  check(()=>assert.deepEqual([ma[4],mb[4]],[120,120],'120 weekdays, the header Days=120'));
  check(()=>assert.ok(ma[2]>2.5&&ma[3]>0.2&&mb[2]>2.5&&mb[3]>0.2,'both clear the bar over SAMPLE: '+JSON.stringify([ma,mb])));
}
// The window metrics on a hand-made curve.
{
  const steps=wave(20,k=>k%2?50:-20);   // 2024.01.08 (Mon) .. 2024.01.27
  const m=metrics(equityCsv(steps,{start:'2024.01.08'}),D('2024.01.09'),D('2024.01.27'));
  check(()=>assert.equal(m[0],steps.slice(1,19).reduce((s,v)=>s+v,0),'net from the close before the window'));
  check(()=>assert.equal(m[1],20,'drawdown from the peak of the closes'));
  check(()=>assert.equal(m[4],14,'weekdays in [Tue 9, Sat 27)'));
  check(()=>assert.ok(Math.abs(m[3]-Math.min(m[0]/m[1],25)/(14/21.7))<1e-9,'ARF = (net / drawdown) per 21.7 weekdays'));
  check(()=>assert.equal(metrics(equityCsv(steps,{start:'2024.01.08'}),D('2024.02.01'),D('2024.03.01')),null,'no row inside the window'));
  check(()=>assert.equal(metrics(equityCsv(wave(20,()=>10),{start:'2024.01.08'}),D('2024.01.09'),D('2024.01.27')),null,'a flat change series has no Sharpe'));
  check(()=>assert.equal(metrics(equityCsv(steps,{start:'2024.01.08'}),D('2024.01.09'),D('2024.01.13')),null,'under 5 weekdays'));
}

// ---- The combiner records how many report pairs it read; the pick comes after InitializeTester.
const cell=(type,v)=>'<Cell><Data ss:Type="'+type+'">'+v+'</Data></Cell>';
const TITLE='GOAT V1.49 USDCAD,M1 2024.01.08-2025.03.15';
const FOLDER='GOAT\\Rabcdef012345\\reports\\R0123456789abcdef0123\\USDCAD\\';
const back=(title=TITLE)=>FOLDER+title+' (2025.01.06).xml';
function backReport(rows,title=TITLE){
  const head=['Pass','Result','Profit','Expected Payoff','Profit Factor','Recovery Factor','Sharpe Ratio','Custom','Equity DD %','Trades'];
  const lines=['<?xml version="1.0"?>','<Workbook>','<DocumentProperties>','<Title>'+title+'</Title>','</DocumentProperties>','<Worksheet ss:Name="R">','<Table>','<Row>',
    ...head.map(h=>cell('String',h)),cell('String','SL_Pips'),cell('String','Grid_Size'),'</Row>'];
  for(const r of rows)lines.push('<Row>',cell('Number',r.pass),cell('Number',r.result),cell('Number',r.profit),cell('Number',0),cell('Number',1.4),
    cell('Number',2),cell('Number',1.5),cell('Number',0),cell('Number',5),cell('Number',r.trades),cell('Number',r.sl??0),cell('Number',r.grid??2),'</Row>');
  lines.push('</Table>','</Worksheet>','</Workbook>');return lines;
}
function forwardReport(rows){
  const head=['Pass','Forward Result','Back Result','Profit','Expected Payoff','Profit Factor','Recovery Factor','Sharpe Ratio','Custom','Equity DD %','Trades'];
  const lines=['<?xml version="1.0"?>','<Workbook>','<Worksheet ss:Name="R">','<Table>','<Row>',...head.map(h=>cell('String',h)),cell('String','SL_Pips'),cell('String','Grid_Size'),'</Row>'];
  for(const r of rows)lines.push('<Row>',cell('Number',r.pass),cell('Number',0.01),cell('Number',r.result),cell('Number',r.fprofit),cell('Number',0),
    cell('Number',1.1),cell('Number',r.frf),cell('Number',0.8),cell('Number',0),cell('Number',5),cell('Number',r.ftrades),cell('Number',r.sl??0),cell('Number',r.grid??2),'</Row>');
  lines.push('</Table>','</Worksheet>','</Workbook>');return lines;
}
const losing=n=>Array.from({length:n},(_,i)=>({pass:i,result:0.01,profit:-1500-i,trades:175,fprofit:-20,frf:-0.5,ftrades:30}));
const keptRow=k=>({pass:151+k,result:0.5+k/100,profit:600+10*k,trades:80,fprofit:k<5?30+k:-40,frf:[0.4,1.9,0.7,1.2,0.3,2,2][k],ftrades:40,grid:20+k});
function combine(pairs){
  const files={},names=[];
  for(const p of pairs){files[p.name]=p.back;names.push(p.name);const fwd=p.name.slice(0,-4)+'.forward.xml';files[fwd]=p.forward;names.push(fwd);}
  const ctx=H.makeContext(files,{realForward:true});ctx.__names=names;
  const ret=vm.runInContext('ReportAnalyzerCombiner(__names,false,"GOAT","GOAT V1.49","Darwinex-Demo")',ctx);
  return {ret,ctx};
}
const ctxRank=(ctx,dep=DEP)=>{const out=[];ctx.__o=out;vm.runInContext('GoatXmlFwdRank(Rows,-1,'+dep+',__o)',ctx);return out.map(i=>ctx.Rows[i].pass);};
const g6=(rows=Array.from({length:7},(_,k)=>keptRow(k)))=>({name:back(),back:backReport(losing(151).concat(rows)),forward:forwardReport(losing(151).concat(rows))});
{
  const {ret,ctx}=combine([g6()]);
  check(()=>assert.equal(ret,false));
  check(()=>assert.equal(ctx.outcome,'no_qualifying_rows'));
  check(()=>assert.equal(ctx.belowScorePairs,1));
  check(()=>assert.equal(ctxRank(ctx)[0],152,'pass 152: FWD profit/DD 1.9, the best profitable forward (k=5,6 lost in FWD)'));
  const resc=combine([g6(Array.from({length:7},(_,k)=>({...keptRow(k),profit:k===1?601:5000-100*k})))]).ctx;
  check(()=>assert.equal(ctxRank(resc)[0],152,'SAMPLE profit only gates'));
  const other='GOAT V1.49 USDCAD,M5 2024.01.08-2025.03.15';
  const two=combine([g6(),{...g6(),name:back(other),back:backReport(losing(151).concat(Array.from({length:7},(_,k)=>keptRow(k))),other)}]).ctx;
  check(()=>assert.equal(two.outcome,'no_qualifying_rows'));
  check(()=>assert.equal(two.belowScorePairs,2,'two pairs: below_score_reason=multiple_pairs later, never a pick'));
}

// ---- V1.49: GoatExportSlots, StartBelowScoreExporter and the deinit branch, with a stubbed tester.
const XMACROS=H.macros;
function preprocessWith(text,flags){
  const out=[],stack=[];let active=true;
  for(const line of text.split('\n')){
    const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
    if(m){
      if(m[1]==='ifdef'||m[1]==='ifndef'){const on=flags.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
      else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
      else active=stack.pop()[0];
      continue;
    }
    if(/^\s*#/.test(line))continue;
    if(active)out.push(line);
  }
  return out.join('\n');
}
function mainFunctions(flags){
  const P=H.stripComments(preprocessWith(mainRaw,flags));
  const fn=(pattern,name)=>H.extract(P,pattern,name,XMACROS).replace(/ExportRecord\s+(\w+)\[\];/g,'let $1=[];');
  return {P,fn};
}
const sha=t=>crypto.createHash('sha256').update(t).digest('hex');
{
  // Switch OFF: StartExporter is byte for byte the base branch's (4828036), preprocessed and comment-stripped.
  const {P}=mainFunctions(FLAGS);
  const at=P.indexOf('bool StartExporter(bool reportMode)'),[,end]=H.block(P,at);
  check(()=>assert.equal(sha(P.slice(at,end)),'d27080658b962586b883321c0f13f7a1843a780d82cb2e3be487c485c8fbcb78','StartExporter changed with the switch off'));
  const on=mainFunctions(new Set([...FLAGS,'GOAT_EXPORT_RANK_FWD_PROFIT_DD'])).P;
  const at2=on.indexOf('bool StartExporter(bool reportMode)'),[,end2]=H.block(on,at2);
  const switched=on.slice(at2,end2);
  check(()=>assert.ok(switched.includes('GoatXmlFwdRank(xmlData.Rows,MinScore,deposit,fwdRanked)')&&switched.includes('GoatExportSlots(fwdRanked,"",false,')));
  check(()=>assert.ok(!switched.includes('SortAndTrimExports(')&&!switched.includes('for(;i<MathMin(25'),'switched on: no match-score loop or trim'));
  check(()=>assert.ok(switched.includes('GoatSlotTrimLog(g_allExports,MinARF,MinSR)')));
  check(()=>assert.ok(!P.slice(at,end).includes('tier=')));
}
const ini=dep=>'[Tester]\r\nExpert=GOAT\\GOAT V1.49.ex5\r\nDeposit='+dep+'\r\nCurrency=USD\r\n';
function tester({plan=[],csv={},move=true,runPath='GOAT\\Rabcdef012345',evidence='2025.10.03',cancelAfter=null,settings={},switchOn=false,deposit=DEP}={}){
  const {fn}=mainFunctions(FLAGS);
  // MQL passes details, the correlation's day count and the out-strings by reference: in the VM they
  // become context globals (__slotDetails, __bsDetails, n), read back right after each call.
  const slots=fn(/^int\s+GoatExportSlots\s*\(/m,'GoatExportSlots')
    .replace(/function GoatExportSlots\(([^)]*)\)/,'function GoatExportSlots(ranked,metaTail,keepLosingSlot1,minSR,minARF,kept,__d,runs,lost,failed,reportMode)')
    .replace(/\bdetails\b/g,'__slotDetails').replace(/,days\);/,',days); days=n;');
  const start=fn(/^int\s+StartBelowScoreExporter\s*\(/m,'StartBelowScoreExporter')
    .replace(/function StartBelowScoreExporter\(([^)]*)\)/,'function StartBelowScoreExporter(reportMode)')
    .replace(/\bdetails\b/g,'__bsDetails')
    .replace('kept,slots,runs,lost,failed,reportMode);','kept,slots,runs,lost,failed,reportMode); slots=__slotDetails;');
  check(()=>assert.ok(slots.includes('days=n;')&&start.includes('slots=__slotDetails;'),'by-reference rewiring applied'));
  const runs=[],moves=[],deleted=[],logs=[],evidenceChecks=[];
  const ctx=Object.assign(H.makeContext({}),{runs,moves,deleted,logs,Key:'GOAT',EA_Name:'GOAT V1.49',Server:'Darwinex-Demo',OP_Standard:9,
    StringToInteger:s=>parseInt(s,10)||0,belowScorePairs:1,
    strT:{Strat:'R0123456789abcdef0123',Model:'4',fromDate:'',toDate:'',str_testerSettings:ini(deposit)},GOAT_BATCH_CANCELLED_GV:'cancel',__cancel:false,
    GoatOptReadIniValue:(text,k)=>{const m=String(text).match(new RegExp('^'+k+'=(.*)$','m'));return m?m[1].trim():'';},
    GlobalVariableGet:()=>ctx.__cancel?1:0,InitializeTester:()=>true,TimeTradeServer:()=>777000,TimeCurrent:()=>1,GetLastFridayDate:()=>'2025.10.03',
    FetchExportSetting:k=>({BackOOSDate:'2023.10.02',IncludeBackOOS:'1',MinARF:'0.2',MinSR:'2.5',EvidenceEnd:'auto',SetsToExport:'2',MinScore:'60',TargetDD:'100',AdjustLots:'0',...settings})[k]??'',
    MTTESTER:{IsReady:()=>true},Sleep:()=>{},ChartSetInteger:()=>{},CHART_BRING_TO_TOP:0,Print:()=>{},GOAT_BUILD_ID:'B42',g_allExports:[],
    StringFormat:(f,...a)=>{let k=0;return f.replace(/%[ds]/g,()=>String(a[k++]));},WriteLog:t=>logs.push(t),
    __boundary:[],GoatEvidenceEndToDate:(setting,now,windowEnd)=>{ctx.__boundary.push([setting,now,windowEnd]);return evidence;},GoatOptCurrentRunPath:()=>runPath,GoatOptDeployPath:()=>runPath+'\\deploy',ShowPrompt:()=>{},LogOrPrint:(m,t)=>logs.push(t),
    GoatEvidenceEndCheckExports:(arr)=>evidenceChecks.push(arr.length),FileNameOnly:p=>p.split('\\').pop(),
    GoatExportReadTextCommon:p=>csv[p]??'',
    DeleteExports:files=>{deleted.push(...files);return true;},
    MoveKeptExports:(arr,dst)=>{moves.push([dst,Array.from(arr,r=>r.setFile)]);return move;},
    RunAndStoreSet:(rowInd,mode,reportMode,arr,init,attempts,keepLosing=false)=>{
      if(init){runs.push({rowInd,pass:null,mode,keepLosing,init:true});return 1;}
      const unit=ctx.xmlData.RowsUnique[rowInd],step=plan[runs.filter(r=>!r.init).length]??{};
      runs.push({rowInd,pass:unit.pass,mode,keepLosing,init});
      if(cancelAfter===runs.length)ctx.__cancel=true;
      if(step.error)return -1;
      const prf=step.prf??100;
      if(!(prf>0)&&!keepLosing)return 0;
      arr.push({csvFile:'exports\\'+unit.pass+'.csv',setFile:'exports\\'+unit.pass+'.set',prf,sr:step.sr??3,arf:step.arf??0.3,dd:10,pf:1.2,trds:200,rowIndex:rowInd});
      return 1;
    }});
  vm.runInContext(H.method('GoatDailyReturnCorrelation').replace(/function GoatDailyReturnCorrelation\(([^)]*)\)/,'function GoatDailyReturnCorrelation(csvA,csvB,from,to)'),ctx);
  vm.runInContext(slots,ctx);vm.runInContext(start,ctx);
  if(switchOn){
    const on=mainFunctions(new Set([...FLAGS,'GOAT_EXPORT_RANK_FWD_PROFIT_DD']));
    const exporter=on.fn(/^bool\s+StartExporter\s*\(/m,'StartExporter').replace(/MTTESTER::/g,'MTTESTER.').replace(/const ExportRecord\s+/g,'const ')
      .replace('StartBelowScoreExporter(reportMode,belowScore);','StartBelowScoreExporter(reportMode); belowScore=__bsDetails;')
      .replace('profits=GoatExportSlots(fwdRanked,"",false,MinSR,MinARF,g_allExports,slotDetails,passes,losses,errors,reportMode);',
               '{profits=GoatExportSlots(fwdRanked,"",false,MinSR,MinARF,g_allExports,slotDetails,passes,losses,errors,reportMode); slotDetails=__slotDetails;}');
    check(()=>assert.ok(exporter.includes('belowScore=__bsDetails;')&&exporter.includes('slotDetails=__slotDetails;'),'switched exporter rewired'));
    vm.runInContext(exporter,ctx);
    vm.runInContext(on.fn(/^void\s+GoatSlotTrimLog\s*\(/m,'GoatSlotTrimLog'),ctx);
  }
  return ctx;
}
function loaded(ctx,rows,{end='2025.03.15'}={}){
  ctx.Rows=rows;ctx.RowsUnique=[];ctx.m_inputVarNames=['SL_Pips','Grid_Size'];
  ctx.startD=D('2024.01.08');ctx.forwardD=D('2024.01.08')+(D(end)-D('2024.01.08'))*0.8;ctx.endD=D(end);
  return ctx;
}
const pass=(n,frf,{sl=0,grid=2,score=40}={})=>row({pass:n,forward_RF:frf,Inputs:sl+','+grid,Score:score});
const sample=(changes)=>equityCsv(changes,{start:'2024.01.08'});
const Ad=A.map(x=>x+30), Bd=B.map(x=>x+30);   // with a positive drift: both clear the SAMPLE quality bar
{
  // Slot 1 only; kept even when its re-test lost money (keepLosing).
  const t=loaded(tester({plan:[{prf:-80}]}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',t),1));
  check(()=>assert.deepEqual(t.runs.map(r=>[r.pass,r.keepLosing]),[[5,true]],'one tester run; slot 1 kept whatever its BOOS/FOOS'));
  check(()=>assert.ok(t.runs[0].mode.includes(',tier=below_score}')&&t.runs[0].mode.includes('dt_FOOS_start=2025.03.16')));
  check(()=>assert.deepEqual(t.moves,[['GOAT\\Rabcdef012345\\below_score',['exports\\5.set']]],'research units go to <run>\\below_score, never deploy'));
  check(()=>assert.match(t.__bsDetails,/^;below_score=exported;below_score_kept=1;below_score_pass=5;below_score_fwd_profit_dd=2\.0000;/));
  check(()=>assert.match(t.__bsDetails,/;below_score_rank=fwd_profit_dd;below_score_dd_floor=0\.0025;below_score_min_fwd_trades=30;/));
  check(()=>assert.match(t.__bsDetails,/;slot1=kept;slot1_retest_profit=-80;slot2=none;slot2_reason=no other eligible pass$/));
  check(()=>assert.equal(t.strT.fromDate,'2023.10.02'));
  check(()=>assert.equal(t.strT.toDate,'2025.10.03'));
  check(()=>assert.deepEqual(t.__boundary.map(a=>Array.from(a)),[['auto',777000,D('2025.03.15')]],'EvidenceEnd on the broker server clock and the window end'));
  const legacy=loaded(tester({settings:{EvidenceEnd:''}}),[pass(5,2.0)]);
  vm.runInContext('StartBelowScoreExporter(false)',legacy);
  check(()=>assert.equal(legacy.__boundary.length,0));
  check(()=>assert.equal(legacy.strT.toDate,'2025.10.03','no setting: the legacy last-Friday end'));
  const staged=loaded(tester({evidence:'2025.09.27'}),[pass(5,2.0)]);
  vm.runInContext('StartBelowScoreExporter(false)',staged);
  check(()=>assert.equal(staged.strT.toDate,'2025.09.27','the staged EvidenceEnd wins'));
  // The pick uses the tester deposit's floor, read after InitializeTester.
  const floor=loaded(tester({deposit:100000}),[pass(5,30,{}),row({pass:6,forward_profit:400,forward_RF:2,Inputs:'0,2'})]);
  floor.Rows[0].forward_profit=3;
  vm.runInContext('StartBelowScoreExporter(false)',floor);
  check(()=>assert.equal(floor.runs[0].pass,6,'a $3 / $0.10 pass never beats a robust one'));
}
{
  // Slot 2, same character: decided on SAMPLE only; kept at correlation <= 0.5, skipped above it.
  for(const [label,curve2,want] of [['independent',Bd,'kept'],['near copy',Ad.map(x=>x*1.1+2),'skipped'],
                                      ['moderately correlated (about 0.71)',A.map((x,k)=>x+1.2*B[k]+30),'skipped']]){
    const t=loaded(tester({csv:{'exports\\5.csv':sample(Ad),'exports\\6.csv':sample(curve2)}}),[pass(5,2.0),pass(6,1.5)]);
    const k=vm.runInContext('StartBelowScoreExporter(false)',t);
    check(()=>assert.deepEqual(t.runs.map(r=>[r.pass,r.keepLosing]),[[5,true],[6,true]],label+': slot 2 runs kept whatever its full span made'));
    check(()=>assert.equal(k,want==='kept'?2:1,label+': '+t.__bsDetails));
    check(()=>assert.ok(t.__bsDetails.includes(';slot2='+want+';'),label+': '+t.__bsDetails));
    check(()=>assert.match(t.__bsDetails,/;slot2_sample_net=\d+;slot2_sample_sr=\d+\.\d\d;slot2_sample_arf=\d+\.\d{3};slot2_retest_profit=100;/,label));
    check(()=>assert.match(t.__bsDetails,/;slot2_correlation=-?\d\.\d{3};slot2_days=60;/,label+': the correlation is recorded'));
    check(()=>assert.ok(t.logs.some(l=>/^(✅ )?Export slot 2 (kept|skipped): .*SAMPLE correlation -?\d\.\d{3}, 60 days\)\.$/.test(l)),label+': and logged'));
    if(want==='skipped'){
      check(()=>assert.deepEqual(t.deleted,['exports\\6.csv','exports\\6.set'],'a skipped slot 2 is deleted'));
      const m=t.__bsDetails.match(/;slot2_reason=same character and SAMPLE correlation (\d\.\d{3}) above 0\.5$/);
      check(()=>assert.ok(m&&+m[1]>0.5,label+': '+t.__bsDetails));
    }else{
      check(()=>assert.deepEqual(t.deleted,[]));
      check(()=>assert.match(t.__bsDetails,/;slot2_reason=SAMPLE correlation -?0\.\d{3} at or below 0\.5$/));
      check(()=>assert.deepEqual(t.moves[0][1],['exports\\5.set','exports\\6.set']));
    }
  }
}
{
  // Slot 2, different character: preferred over a better same-character pass, kept even when correlated.
  const t=loaded(tester({csv:{'exports\\5.csv':sample(Ad),'exports\\7.csv':sample(Ad)}}),[pass(5,2.0),pass(6,1.9),pass(7,1.0,{sl:10})]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',t),2));
  check(()=>assert.deepEqual(t.runs.map(r=>r.pass),[5,7],'the different-character pass is slot 2'));
  check(()=>assert.match(t.__bsDetails,/;slot2_character=SL_Pips 0->10;.*;slot2_correlation=1\.000;slot2_days=60;slot2=kept;slot2_reason=different character: SL_Pips 0->10$/));
}
{
  // The quality bar over SAMPLE (net > 0, SR >= max(MinSR, 2.5), ARF >= max(MinARF, 0.2)) gates slot 2.
  const end='2024.03.07';   // a 60-day window: the curve covers it
  const sr=curve=>metrics(sample(curve),D('2024.01.08'),D(end)+DAY);
  let mid=null;
  for(let drift=0;drift<=40&&!mid;drift+=0.25){const curve=B.map(x=>x+drift),m=sr(curve);if(m&&m[0]>0&&m[2]>1.2&&m[2]<2.3&&m[3]>=0.25)mid=curve;}
  check(()=>assert.ok(mid,'a curve with SR between 1.2 and 2.3 and ARF >= 0.25 exists'));
  for(const [label,curve,settings] of [['losing over SAMPLE',B.map(x=>x-30),{}],['SR under 2.5',mid,{}],
                                       ['a looser run never lowers the bar',mid,{MinSR:'1.0'}],['a stricter MinARF raises it',Bd,{MinARF:'50'}],
                                       ['a stricter MinSR raises it',Bd,{MinSR:'30'}]]){
    const t=loaded(tester({settings,csv:{'exports\\5.csv':sample(Ad),'exports\\7.csv':sample(curve)}}),[pass(5,2.0),pass(7,1.0,{sl:10})],{end});
    check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',t),1,label+': '+t.__bsDetails));
    check(()=>assert.match(t.__bsDetails,/;slot2=skipped;slot2_reason=below the quality bar over SAMPLE \(net /,label));
    check(()=>assert.deepEqual(t.deleted,['exports\\7.csv','exports\\7.set'],label));
  }
  const ok=loaded(tester({settings:{MinSR:'1.0'},csv:{'exports\\5.csv':sample(Ad),'exports\\7.csv':sample(Bd)}}),[pass(5,2.0),pass(7,1.0,{sl:10})],{end});
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',ok),2,'a curve over the bar is kept: '+ok.__bsDetails));
  const unread=loaded(tester({csv:{'exports\\5.csv':sample(Ad)}}),[pass(5,2.0),pass(7,1.0,{sl:10})],{end});
  vm.runInContext('StartBelowScoreExporter(false)',unread);
  check(()=>assert.match(unread.__bsDetails,/;slot2=skipped;slot2_reason=SAMPLE metrics not measurable from its equity CSV$/));
}
{
  // Unknown correlation (fewer than 20 common SAMPLE days) never proves a same-character pass different.
  const t=loaded(tester({csv:{'exports\\5.csv':sample(Ad.slice(0,10)),'exports\\6.csv':sample(Bd.slice(0,10))}}),[pass(5,2.0),pass(6,1.5)],{end:'2024.01.17'});
  vm.runInContext('StartBelowScoreExporter(false)',t);
  check(()=>assert.match(t.__bsDetails,/;slot2_correlation=na;slot2_days=10;slot2=skipped;slot2_reason=same character and SAMPLE correlation unknown \(10 days\)$/));
  // A slot 2 whose full re-test lost money is judged on SAMPLE all the same (its FOOS never decides it).
  const lost=loaded(tester({plan:[{},{prf:-5,sr:0.1,arf:0.01}],csv:{'exports\\5.csv':sample(Ad),'exports\\6.csv':sample(Bd)}}),[pass(5,2.0),pass(6,1.5)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',lost),2));
  check(()=>assert.match(lost.__bsDetails,/;slot2_retest_profit=-5;.*;slot2=kept;/));
}
{
  // Errors and refusals: nothing left behind, nothing run without a pair, a run folder, a deposit or an evidence end.
  const none=loaded(tester(),[]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',none),0));
  check(()=>assert.equal(none.runs.length,0));
  check(()=>assert.equal(none.__bsDetails,';below_score=none;no_fwd_eligible_pass=1;rows=0;fwd_eligible=0;not_in_forward=0;sample_unprofitable_or_thin=0;fwd_unprofitable=0;fwd_trades_under_floor=0;fwd_dd_unmeasured=0;below_score_rank=fwd_profit_dd;below_score_dd_floor=0.0025;below_score_min_fwd_trades=30'));
  check(()=>assert.ok(none.logs.some(l=>/^NO_FWD_ELIGIBLE_PASS rows=0;/.test(l)),'switch off: NO_FWD_ELIGIBLE_PASS is logged with counts'));
  const thin=loaded(tester(),[row({pass:1,forward_trades:29}),row({pass:2,forward_profit:-5}),row({pass:3,forward_seen:false}),row({pass:4,back_trades:49}),row({pass:5,forward_RF:0})]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',thin),0));
  check(()=>assert.equal(thin.runs.length,0));
  check(()=>assert.match(thin.__bsDetails,/^;below_score=none;no_fwd_eligible_pass=1;rows=5;fwd_eligible=0;not_in_forward=1;sample_unprofitable_or_thin=1;fwd_unprofitable=1;fwd_trades_under_floor=1;fwd_dd_unmeasured=1;/));
  // Several report pairs (item 4): below_score_reason=multiple_pairs, never NO_FWD_ELIGIBLE_PASS from the last pair.
  for(const pairs of [2,0]){
    const multi=loaded(tester(),[pass(5,2.0)]);multi.belowScorePairs=pairs;
    check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',multi),0));
    check(()=>assert.equal(multi.runs.length,0));
    check(()=>assert.match(multi.__bsDetails,new RegExp('^;below_score=none;below_score_reason=multiple_pairs;below_score_pairs='+pairs+';below_score_rank=')));
    check(()=>assert.ok(!multi.logs.some(l=>/NO_FWD_ELIGIBLE_PASS/.test(l))));
  }
  const noDeposit=loaded(tester({deposit:0}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',noDeposit),-1));
  check(()=>assert.equal(noDeposit.runs.length,0));
  check(()=>assert.match(noDeposit.__bsDetails,/^;below_score=failed;below_score_reason=tester_deposit_unknown;/));
  const noRun=loaded(tester({runPath:''}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',noRun),-1));
  check(()=>assert.equal(noRun.runs.length,0));
  const refused=loaded(tester({evidence:''}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',refused),-1));
  check(()=>assert.equal(refused.runs.length,0));
  const unmoved=loaded(tester({move:false,csv:{'exports\\5.csv':sample(Ad),'exports\\7.csv':sample(Ad)}}),[pass(5,2.0),pass(7,1.0,{sl:10})]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',unmoved),-1));
  check(()=>assert.deepEqual(unmoved.deleted,['exports\\5.csv','exports\\5.set','exports\\7.csv','exports\\7.set'],'never left where normal exports are read'));
  check(()=>assert.match(unmoved.__bsDetails,/^;below_score=failed;/));
  const error=loaded(tester({plan:[{error:true}]}),[pass(5,2.0),pass(6,1.5)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',error),-1));
  check(()=>assert.deepEqual(error.runs.map(r=>r.pass),[5],'slot 1 is never replaced by another pass'));
  check(()=>assert.match(error.__bsDetails,/;slot1=failed;slot2=skipped;slot2_reason=no slot 1$/));
  const cancelled=loaded(tester({cancelAfter:1}),[pass(5,2.0),pass(6,1.5)]);
  vm.runInContext('StartBelowScoreExporter(false)',cancelled);
  check(()=>assert.deepEqual(cancelled.runs.map(r=>r.pass),[5],'a cancel stops before slot 2'));
}
{
  // GoatExportSlots for normal exports: no tier; a losing slot 1 is never replaced by the next pass.
  const t=loaded(tester({plan:[{prf:-10}]}),[pass(5,2.0,{score:70}),pass(6,1.5,{score:80})]);
  const out=[];t.__k=out;t.__ranked=[0,1];
  check(()=>assert.equal(vm.runInContext('GoatExportSlots(__ranked,"",false,2.5,0.2,__k,"",0,0,0,false)',t),0));
  check(()=>assert.deepEqual(t.runs.map(r=>[r.pass,r.keepLosing]),[[5,false]]));
  check(()=>assert.ok(!t.runs[0].mode.includes('tier=')));
  check(()=>assert.match(t.__slotDetails,/;slot1=lost;slot2=skipped;slot2_reason=no slot 1$/));
}
{
  // OnTesterDeinit: the NoQualifyingRows row keeps its status and counts; the facts ride in Details.
  const {P}=mainFunctions(FLAGS);
  const deinit=P.slice(P.indexOf('void OnTesterDeinit()'),P.indexOf('bool StartExporter(bool reportMode)'));
  const from=deinit.indexOf('else if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS)');
  const [b0,b1]=H.block(deinit,from);
  const body=H.convert(deinit.slice(b0,b1),{GOAT_XML_NO_QUALIFYING_ROWS:'"no_qualifying_rows"'})
    .replace('StartBelowScoreExporter(false,belowScore)','(__r=StartBelowScoreExporter(false,belowScore),belowScore=__bs,__r)');
  for(const [kept,want] of [[1,/ No qualifying exports; the best profitable pass \(FWD profit\/DD\) was kept for research only \(below_score\)\.$/],[0,/ No exports\.$/],[-1,/ No exports\.$/]]){
    const out={stats:[],logs:[]};
    const ctx={xmlData:{Rows:Array(7).fill({}),bestCombinedScore:48.1,passesSeen:158,OutcomeDetails:()=>'outcome=no_qualifying_rows;passes=158',
      OutcomeSentence:()=>'Tested 158 settings.',OutcomeWindow:()=>'w'},__bs:';below_score=exported;below_score_kept=1',__r:0,
      StartBelowScoreExporter:()=>kept,GlobalVariableGet:()=>0,GOAT_BATCH_CANCELLED_GV:'c',EA_Name:'GOAT V1.49',Server:'S',Key:'K',Strat:'R1',
      ArraySize:a=>a.length,Symbol:()=>'USDCAD',Sleep:()=>{},GoatOptAppendItemStats:(...a)=>out.stats.push(a),WriteLog:t=>out.logs.push(t),ShowPrompt:()=>{}};
    vm.runInNewContext('(function()'+body+')()',ctx);
    check(()=>assert.deepEqual(out.stats,[['GOAT V1.49','S','USDCAD','R1','NoQualifyingRows',7,0,48.1,0,'outcome=no_qualifying_rows;passes=158;below_score=exported;below_score_kept=1']],
      'NoQualifyingRows, XmlRows, UniqueRows 0, FinalExports 0: never counted as qualifying'));
    check(()=>assert.match(out.logs[0],want));
  }
  const ctx={xmlData:{Rows:[],OutcomeDetails:()=>'',OutcomeSentence:()=>'',OutcomeWindow:()=>''},__bs:'',__r:0,StartBelowScoreExporter:()=>1,
    GlobalVariableGet:()=>1,GOAT_BATCH_CANCELLED_GV:'c',ArraySize:a=>a.length,Symbol:()=>'X',GoatOptAppendItemStats:()=>{throw new Error('row after a cancel');},
    WriteLog:()=>{},ShowPrompt:()=>{},Sleep:()=>{}};
  check(()=>vm.runInNewContext('(function()'+body+')()',ctx));
}
{
  // The tier: parsed from EA_Desc and written into the SET header after the windows.
  const {P}=mainFunctions(FLAGS);
  check(()=>assert.ok(P.includes('if(names[i]=="tier" && values[i]==GOAT_XML_BELOW_SCORE)')));
  const header=P.slice(P.indexOf('temp="FOOS:   "'),P.indexOf('temp="--------',P.indexOf('temp="FOOS:   "')));
  check(()=>assert.ok(header.includes('if(g_goatBelowScoreExport) {')&&header.includes('temp="EXPORT: "+GOAT_XML_BELOW_SCORE+" research only')));
  check(()=>assert.equal(XMACROS.GOAT_XML_BELOW_SCORE,'"below_score"'));
  check(()=>assert.equal(XMACROS.GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES,'30'));
  check(()=>assert.equal(XMACROS.GOAT_EXPORT_FWD_DD_FLOOR,'0.0025'));
  check(()=>assert.ok(P.includes('const bool keepLosing=false)')&&P.includes('if(profit>0 || keepLosing)')));
  check(()=>assert.equal(P.split(',3,keepLosingSlot1)').length,2,'slot 1 passes keepLosingSlot1'));
  check(()=>assert.ok(P.includes('RunAndStoreSet(1,mode,reportMode,kept,false,3,true)'),'slot 2 always runs kept whatever its full span made'));
  check(()=>assert.ok(P.includes('GoatExportSlots(ranked,",tier="+GOAT_XML_BELOW_SCORE,true,')));
}
{
  // Switch ON (GOAT_EXPORT_RANK_FWD_PROFIT_DD), Claude-Mac 6023896492: a member never exports nothing silently.
  const exporterRun=(rows,opts={})=>{const t=loaded(tester({...opts,switchOn:true}),rows);t.outcome='';t.passesSeen=158;t.profitableSeen=7;
    t.tradedSeen=158;t.malformedSeen=0;t.reportClosed=true;t.forwardRows=158;t.bestProfit=660;t.bestResult=0.56;t.forwardMatched=rows.length;
    t.bestCombinedScore=Math.max(0,...rows.map(r=>r.Score));t.g_allExports=[];
    const ok=vm.runInContext('StartExporter(false)',t);return {t,ok};};
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_trades:20,forward_RF:9}),row({pass:6,Score:41,forward_RF:1.4}),row({pass:7,Score:30,forward_RF:2.2})]);
    check(()=>assert.equal(ok,false,'nothing qualifying is exported'));
    check(()=>assert.deepEqual(t.runs.filter(r=>!r.init).map(r=>[r.pass,r.keepLosing]),[[7,true],[6,true]],'below_score slot 1 = best FWD profit/DD among eligible passes'));
    check(()=>assert.ok(t.runs.filter(r=>!r.init).every(r=>r.mode.includes(',tier=below_score}'))));
    check(()=>assert.equal(t.g_goatFwdFallthrough,true));
    const d=t.g_goatFwdFallthroughDetails;
    check(()=>assert.match(d,/^outcome=no_fwd_eligible_rows;passes=158;/));
    check(()=>assert.match(d,/;back_rows=3;forward_matched=3;best_combined_score=72\.0;score_threshold=60\.0;score_qualifying_rows=1;below_score=exported;/));
    check(()=>assert.equal(t.outcome,'','the combine outcome is restored'));
    check(()=>assert.ok(t.logs.some(l=>/^No pass at or above MinScore 60\.0 is FWD-eligible \(rows=3;fwd_eligible=0;.*fwd_trades_under_floor=1;.*below_min_score=2;at_min_score=1\): falling through to the below_score export\.$/.test(l))));
    check(()=>assert.deepEqual(t.moves.map(m=>m[0]),['GOAT\\Rabcdef012345\\below_score'],'research only, never deploy'));
  }
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_trades:20}),row({pass:6,Score:41,forward_profit:-3})]);
    check(()=>assert.equal(ok,false));
    check(()=>assert.equal(t.runs.filter(r=>!r.init).length,0));
    check(()=>assert.ok(t.logs.some(l=>l.startsWith('NO_FWD_ELIGIBLE_PASS rows=2;fwd_eligible=0;not_in_forward=0;sample_unprofitable_or_thin=0;fwd_unprofitable=1;fwd_trades_under_floor=1;'))));
    check(()=>assert.match(t.g_goatFwdFallthroughDetails,/;score_qualifying_rows=1;below_score=none;no_fwd_eligible_pass=1;rows=2;/));
  }
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_RF:1.1}),row({pass:6,Score:41,forward_RF:9})]);
    check(()=>assert.equal(ok,true));
    check(()=>assert.deepEqual(t.runs.filter(r=>!r.init).map(r=>[r.pass,r.keepLosing]),[[5,false]],'only the 60+ pass; a better FWD pass under the score never takes it'));
    check(()=>assert.ok(!t.runs.some(r=>r.mode.includes('tier='))));
    check(()=>assert.equal(t.g_goatFwdFallthrough,false));
    check(()=>assert.deepEqual(t.moves,[['GOAT\\Rabcdef012345\\deploy',['exports\\5.set']]],'a normal export goes to deploy'));
    check(()=>assert.ok(t.logs.some(l=>/^SortAndTrimExports: Total=1 Passing=1 Kept=1 Trimmed=0$/.test(l)),'the EA-log cross-check line'));
  }
  {
    // The deposit floor applies to normal exports too, and an unknown deposit exports nothing (and says so).
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_RF:1.1})],{deposit:0});
    check(()=>assert.equal(ok,false));
    check(()=>assert.equal(t.runs.filter(r=>!r.init).length,0));
    check(()=>assert.equal(t.g_goatFwdFallthrough,false,'never a silent fall-through on an unreadable deposit'));
    check(()=>assert.ok(t.logs.some(l=>/The tester deposit could not be read: no export by FWD profit\/DD\.$/.test(l))));
    const floor=exporterRun([row({pass:5,Score:72,forward_profit:3,forward_RF:30}),row({pass:6,Score:70,forward_profit:400,forward_RF:2})],{deposit:100000}).t;
    check(()=>assert.equal(floor.runs.filter(r=>!r.init)[0].pass,6));
  }
  {
    const on=mainFunctions(new Set([...FLAGS,'GOAT_EXPORT_RANK_FWD_PROFIT_DD'])).P;
    const at=on.indexOf('double topScore=(ArraySize(xmlData.Rows)>0 ? xmlData.Rows[0].Score : 0.0);');
    const body=H.convert(on.slice(at,on.indexOf('Print("Deleting Empty Folders...");',at)),{});
    for(const [fall,details,status,want] of [[true,'outcome=no_fwd_eligible_rows;below_score=exported;below_score_kept=1','NoFwdEligibleRows',/kept for research only \(below_score\)\.$/],
                                             [true,'outcome=no_fwd_eligible_rows;below_score=none;no_fwd_eligible_pass=1','NoFwdEligibleRows',/nothing exported \(NO_FWD_ELIGIBLE_PASS\)\.$/],
                                             [false,'','Error',null]]){
      const out={stats:[],logs:[]};
      vm.runInNewContext(body,{xmlData:{Rows:[{Score:72}],RowsUnique:[]},error:true,g_goatFwdFallthrough:fall,g_goatFwdFallthroughDetails:details,EA_Name:'E',Server:'S',Key:'K',Strat:'R1',
        ArraySize:a=>a.length,Symbol:()=>'USDCAD',StringFind:(s,x)=>String(s).indexOf(x),g_allExports:[],
        GoatOptAppendItemStats:(...a)=>out.stats.push(a),WriteLog:x=>out.logs.push(x)});
      check(()=>assert.deepEqual(out.stats[0].slice(4),fall?[status,1,0,72,0,details]:[status,1,0,72,0,'Export cycle finished']));
      if(want)check(()=>assert.match(out.logs[0],want));
    }
  }
  check(()=>assert.match(mainRaw,/RESOLVE BY 2026-10-13, NOT A DORMANT FLAG/));
}
console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
