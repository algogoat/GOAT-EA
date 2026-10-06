// Export rule by FWD profit/DD and the research-only below_score export (GOAT-EA BS42, goatai#1885:
// Claude-Mac 6021965811, 6022008420 and 6022264062). Runs the production XmlProcessor ranking, the
// parameter-character and SAMPLE-correlation gates, the combiner, GoatExportSlots,
// StartBelowScoreExporter and the V1.49 OnTesterDeinit branch in a JS VM over simulated MT5 reports,
// equity CSVs and a stubbed Strategy Tester. MQL-free: no MetaEditor, MT5 or network. GOAT_EA_ROOT may
// point at another source tree (test_below_score_export_mutations.cjs runs every mutation through it).
process.env.GOAT_OUTCOME_HARNESS_ONLY='1';
process.env.GOAT_OUTCOME_EXTRA_DEFINES='GOAT_BELOW_SCORE_EXPORT_V149';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const H=require('./test_research_outcome.cjs');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const mainRaw=read('GOAT V1.49.mq5');
let passed=0;const check=fn=>{fn();passed++;};

// ---- The compile flags the V1.49 entrypoint really defines.
const FLAGS=new Set([...mainRaw.matchAll(/^#define\s+(\w+)/gm)].map(m=>m[1]));
check(()=>assert.ok(FLAGS.has('GOAT_BELOW_SCORE_EXPORT_V149'),'BS42 is on in V1.49'));
check(()=>assert.ok(!FLAGS.has('GOAT_EXPORT_RANK_FWD_PROFIT_DD'),'the normal-export ranking switch is OFF by default'));
check(()=>assert.match(mainRaw,/^\/\/#define GOAT_EXPORT_RANK_FWD_PROFIT_DD$/m,'the switch is one documented line'));
for(const version of ['1.47','1.48'])check(()=>assert.ok(!/GOAT_BELOW_SCORE_EXPORT_V149/.test(read('GOAT V'+version+'.mq5')),'older entrypoints untouched: '+version));

// ---- Ranking: FWD profit/DD among eligible passes; never BOOS, FOOS or the match score.
const row=(o={})=>({pass:o.pass??1,back_result:0,back_profit:o.back_profit??500,back_PF:1.5,back_RF:o.back_RF??3,back_SR:1.2,back_DD_pc:5,
  back_trades:o.back_trades??120,forward_result:0,forward_profit:o.forward_profit??100,forward_PF:1.3,forward_RF:o.forward_RF??1,
  forward_SR:1,forward_DD_pc:4,forward_trades:o.forward_trades??40,Inputs:o.Inputs??'10,5',Score:o.Score??40,forward_seen:o.forward_seen??true,
  // Every other window a pass has (none is in the optimization reports): changing them must change nothing.
  boos_profit:o.boos_profit??0,boos_RF:o.boos_RF??0,foos_profit:o.foos_profit??0,foos_RF:o.foos_RF??0,foos_trades:o.foos_trades??0});
const c=H.makeContext({});
const rank=(rows,min=-1)=>{c.__rows=rows;const out=[];c.__out=out;vm.runInContext('GoatXmlFwdRank(__rows,'+min+',__out)',c);return out.map(i=>rows[i].pass);};
{
  const rows=[row({pass:1,forward_RF:1.2,Score:59}),row({pass:2,forward_RF:2.5,Score:12}),row({pass:3,forward_RF:0.8,Score:58}),
              row({pass:4,forward_RF:2.5,forward_profit:150,Score:5}),row({pass:5,forward_RF:9,forward_trades:29}),
              row({pass:6,forward_RF:9,forward_profit:-1}),row({pass:7,forward_RF:9,back_profit:0}),row({pass:8,forward_RF:9,back_trades:49}),
              row({pass:9,forward_RF:9,forward_seen:false}),row({pass:10,forward_RF:0,forward_profit:5}),row({pass:11,forward_RF:2.5,forward_profit:150})];
  check(()=>assert.deepEqual(rank(rows),[4,11,2,1,3],'FWD profit/DD first, then FWD profit, then the lower pass; the match score never ranks'));
  check(()=>assert.deepEqual(rank(rows,58),[1,3],'a score floor (normal exports) only filters'));
  check(()=>assert.deepEqual(rank(rows.slice().reverse()),[4,11,2,1,3],'row order never changes the ranking'));
  check(()=>assert.equal(vm.runInContext('__x=[];GoatXmlFwdRank([],-1,__x)',c),0));
  // Eligibility edges: the FWD trade floor is 30, the SAMPLE floor 50, profits strictly positive.
  check(()=>assert.deepEqual(rank([row({pass:1,forward_trades:30}),row({pass:2,back_trades:50,forward_RF:0.5})]),[1,2]));
  // FOOS (and BOOS) invariance (Claude-Mac 6022008420 point 1): randomised, the pick never moves.
  let seed=7;const rnd=()=>((seed=(seed*1103515245+12345)%2147483648)/2147483648);
  for(let t=0;t<300;t++){
    const rows2=Array.from({length:12},(_,k)=>row({pass:k+1,forward_RF:Math.round(rnd()*40)/10,forward_profit:Math.round(rnd()*300)-20,
      forward_trades:20+Math.round(rnd()*40),back_profit:Math.round(rnd()*900)-50,back_trades:40+Math.round(rnd()*100),Score:rnd()*100}));
    const before=rank(rows2);
    for(const r of rows2){r.foos_profit=rnd()*1e4-5e3;r.foos_RF=rnd()*20-10;r.foos_trades=Math.round(rnd()*200);r.boos_profit=rnd()*1e4-5e3;r.boos_RF=rnd()*20-10;}
    check(()=>assert.deepEqual(rank(rows2),before,'FOOS/BOOS numbers changed the pick (trial '+t+')'));
    // SAMPLE figures are eligibility only: a different (still eligible) SAMPLE profit or RF never re-ranks.
    for(const r of rows2){if(r.back_profit>0)r.back_profit=1+rnd()*5000;r.back_RF=rnd()*9;r.Score=rnd()*100;}
    check(()=>assert.deepEqual(rank(rows2),before,'SAMPLE or the match score changed the order (trial '+t+')'));
  }
  // Statically: the ranking reads only these fields of a pass.
  const src=['GoatXmlFwdIneligibility','GoatXmlFwdEligible','GoatXmlFwdBetter','GoatXmlFwdRank'].map(n=>H.method(n)).join('\n');
  const fields=new Set([...src.matchAll(/\]\.(\w+)/g)].map(m=>m[1]));
  check(()=>assert.deepEqual([...fields].sort(),['Score','back_profit','back_trades','forward_RF','forward_profit','forward_seen','forward_trades','pass'].sort()));
  check(()=>assert.ok(!/foos|boos|FOOS|BOOS|forward_SR|back_RF|back_SR/.test(src)));
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

// ---- SAMPLE daily-return correlation from two equity CSVs (the EA's own CSV layout).
const D=s=>H.epoch(s),DAY=86400;
function equityCsv(changes,{start='2025.01.06',skip=[]}={}){
  const lines=['﻿<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'];
  let eq=100000,t=D(start);
  changes.forEach((x,k)=>{const day=H.date(t+k*DAY);if(skip.includes(k))return;eq+=x;
    lines.push(day+' 10:00\t'+eq.toFixed(2)+'\t'+(eq-3).toFixed(2)+'\t0.0',day+' 15:00\t'+eq.toFixed(2)+'\t'+eq.toFixed(2)+'\t0.0');});
  return lines.join('\n');
}
const corr=(a,b,from=D('2025.01.01'),to=D('2026.01.01'))=>{c.n=0;const v=vm.runInContext('GoatDailyReturnCorrelation('+JSON.stringify(a)+','+JSON.stringify(b)+','+from+','+to+')',c);return [v,c.n];};
const wave=(n,f)=>Array.from({length:n},(_,k)=>f(k));
const A=wave(60,k=>Math.sin(k*0.7)*50+((k*37)%11)-5);
{
  // The VM keeps n as a context global (MQL passes it by reference).
  const src=H.method('GoatDailyReturnCorrelation').replace('function GoatDailyReturnCorrelation(csvA,csvB,from,to,n)','function GoatDailyReturnCorrelation(csvA,csvB,from,to)');
  vm.runInContext(src,c);
  const [same,n]=corr(equityCsv(A),equityCsv(A.map(x=>2*x+1)));
  check(()=>assert.ok(Math.abs(same-1)<1e-6,'a scaled copy correlates 1: '+same));
  check(()=>assert.equal(n,59,'59 daily changes from 60 closes'));
  const [neg]=corr(equityCsv(A),equityCsv(A.map(x=>-x)));
  check(()=>assert.ok(Math.abs(neg+1)<1e-6));
  const B=wave(60,k=>Math.cos(k*1.9)*40+((k*53)%7)-3);
  const [mixed]=corr(equityCsv(A),equityCsv(B));
  check(()=>assert.ok(Math.abs(mixed)<0.5,'independent curves: '+mixed));
  // Only SAMPLE days count: a curve that matches inside the window but not outside still correlates 1.
  const outside=A.map((x,k)=>k<30?x:-x);
  const [inWindow]=corr(equityCsv(A),equityCsv(outside),D('2025.01.01'),D('2025.01.06')+30*DAY);
  check(()=>assert.ok(Math.abs(inWindow-1)<1e-6,'outside SAMPLE never counts: '+inWindow));
  // A day missing from one curve carries its last close.
  const [gap,gn]=corr(equityCsv(A),equityCsv(A,{skip:[10]}));
  check(()=>assert.ok(gap>0.5&&gn===59,'a missing day is carried: '+gap));
  check(()=>assert.equal(corr(equityCsv(A.slice(0,15)),equityCsv(A.slice(0,15)))[0],Number.MAX_VALUE,'fewer than 20 changes: unknown'));
  check(()=>assert.equal(corr(equityCsv(A),equityCsv(A.map(()=>0)))[0],Number.MAX_VALUE,'a flat curve: unknown'));
  check(()=>assert.equal(corr('','')[0],Number.MAX_VALUE,'unreadable: unknown'));
  const backwards=equityCsv(A).split('\n');backwards.splice(9,0,'2025.01.06 23:00\t1\t1\t0');
  check(()=>assert.equal(corr(backwards.join('\n'),equityCsv(A))[0],Number.MAX_VALUE,'rows back in time: unreadable'));
}

// ---- The combiner: slot 1 of a no-qualifier pair (Banker g6-r1b shape) is the FWD profit/DD leader.
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
const kept=k=>({pass:151+k,result:0.5+k/100,profit:600+10*k,trades:80,fprofit:k<5?30+k:-40,frf:[0.4,1.9,0.7,1.2,0.3,2,2][k],ftrades:40,grid:20+k});
function combine(pairs){
  const files={},names=[];
  for(const p of pairs){files[p.name]=p.back;names.push(p.name);const fwd=p.name.slice(0,-4)+'.forward.xml';files[fwd]=p.forward;names.push(fwd);}
  const ctx=H.makeContext(files,{realForward:true});ctx.__names=names;
  const ret=vm.runInContext('ReportAnalyzerCombiner(__names,false,"GOAT","GOAT V1.49","Darwinex-Demo")',ctx);
  return {ret,ctx};
}
const g6=(keptRows=Array.from({length:7},(_,k)=>kept(k)))=>({name:back(),back:backReport(losing(151).concat(keptRows)),forward:forwardReport(losing(151).concat(keptRows))});
{
  const {ret,ctx}=combine([g6()]);
  check(()=>assert.equal(ret,false));
  check(()=>assert.equal(ctx.outcome,'no_qualifying_rows'));
  check(()=>assert.ok(ctx.bestCombinedScore<60));
  check(()=>assert.equal(ctx.Rows[ctx.belowScoreRow].pass,152,'pass 152: FWD profit/DD 1.9, the best profitable forward (k=5,6 lost in FWD)'));
  // FOOS never in the reports; changing the match score's inputs that are not FWD profit/DD keeps the pick.
  const resc=combine([g6(Array.from({length:7},(_,k)=>({...kept(k),profit:k===1?601:5000-100*k})))]).ctx;
  check(()=>assert.equal(resc.Rows[resc.belowScoreRow].pass,152,'SAMPLE profit only gates'));
  // Two pairs: never below_score (the details describe one pair).
  const other='GOAT V1.49 USDCAD,M5 2024.01.08-2025.03.15';
  const two=combine([g6(),{...g6(),name:back(other),back:backReport(losing(151).concat(Array.from({length:7},(_,k)=>kept(k))),other)}]).ctx;
  check(()=>assert.equal(two.outcome,'no_qualifying_rows'));
  check(()=>assert.equal(two.belowScoreRow,-1));
  // Nothing FWD-eligible (every forward too short): no pick.
  const short=combine([g6(Array.from({length:7},(_,k)=>({...kept(k),ftrades:29})))]).ctx;
  check(()=>assert.equal(short.outcome,'no_qualifying_rows'));
  check(()=>assert.equal(short.belowScoreRow,-1));
  // A pair with a pass at the export score is a normal export: never a below_score pick.
  const strong={pass:160,result:0.9,profit:600,trades:161,fprofit:112,frf:0.373,ftrades:30,grid:40};
  const qual=combine([g6(Array.from({length:7},(_,k)=>kept(k)).concat([strong]))]);
  check(()=>assert.equal(qual.ctx.outcome,''));
  check(()=>assert.ok(qual.ctx.bestCombinedScore>=60,'the strong pass scores 60+: '+qual.ctx.bestCombinedScore));
  check(()=>assert.equal(qual.ctx.belowScoreRow,-1));
  // A no-profitable-passes pair never picks.
  const none=combine([{name:back(),back:backReport(losing(20)),forward:forwardReport(losing(20))}]).ctx;
  check(()=>assert.equal(none.outcome,'no_profitable_passes'));
  check(()=>assert.equal(none.belowScoreRow,-1));
}

// ---- V1.49: GoatExportSlots, StartBelowScoreExporter and the deinit branch, with a stubbed tester.
const XMACROS=H.macros;
function mainFunctions(flags){
  const P=H.stripComments(preprocessWith(mainRaw,flags));
  const fn=(pattern,name)=>H.extract(P,pattern,name,XMACROS).replace(/ExportRecord\s+(\w+)\[\];/g,'let $1=[];');
  return {P,fn};
}
function preprocessWith(text,flags){
  // test_research_outcome's preprocess reads its own DEFINED; run the same rules with these flags.
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
const sha=t=>crypto.createHash('sha256').update(t).digest('hex');
{
  // Switch default = current behaviour: with the flags V1.49 really defines, StartExporter is byte for
  // byte the base branch's (4828036, codex/v148-research-planning) once preprocessed and comments removed.
  const {P}=mainFunctions(FLAGS);
  const at=P.indexOf('bool StartExporter(bool reportMode)'),[,end]=H.block(P,at);
  check(()=>assert.equal(sha(P.slice(at,end)),'d27080658b962586b883321c0f13f7a1843a780d82cb2e3be487c485c8fbcb78','StartExporter changed with the switch off'));
  const on=mainFunctions(new Set([...FLAGS,'GOAT_EXPORT_RANK_FWD_PROFIT_DD'])).P;
  const at2=on.indexOf('bool StartExporter(bool reportMode)'),[,end2]=H.block(on,at2);
  const switched=on.slice(at2,end2);
  check(()=>assert.ok(switched.includes('GoatXmlFwdRank(xmlData.Rows,MinScore,fwdRanked)')&&switched.includes('GoatExportSlots(fwdRanked,"",false,')));
  check(()=>assert.ok(!switched.includes('SortAndTrimExports(')&&!switched.includes('for(;i<MathMin(25'),'switched on: no match-score loop or trim'));
  check(()=>assert.ok(switched.includes('GoatSlotTrimLog(g_allExports,MinARF,MinSR)')));
  check(()=>assert.ok(!P.slice(at,end).includes('tier=')));
}
function tester({plan=[],csv={},move=true,runPath='GOAT\\Rabcdef012345',evidence='2025.10.03',cancelAfter=null,settings={},switchOn=false}={}){
  const {fn}=mainFunctions(FLAGS);
  // MQL passes details, the correlation's day count and the out-strings by reference: in the VM they
  // become context globals (__slotDetails, __bsDetails, n), read back right after each call.
  const slots=fn(/^int\s+GoatExportSlots\s*\(/m,'GoatExportSlots')
    .replace(/function GoatExportSlots\(([^)]*)\)/,'function GoatExportSlots(ranked,metaTail,keepLosingSlot1,minSR,minARF,kept,__d,runs,lost,failed,reportMode)')
    .replace(/\bdetails\b/g,'__slotDetails')
    .replace('xmlData.startD,xmlData.endD+24*60*60,days);','xmlData.startD,xmlData.endD+24*60*60,days); days=n;');
  const start=fn(/^int\s+StartBelowScoreExporter\s*\(/m,'StartBelowScoreExporter')
    .replace(/function StartBelowScoreExporter\(([^)]*)\)/,'function StartBelowScoreExporter(reportMode)')
    .replace(/\bdetails\b/g,'__bsDetails')
    .replace('kept,slots,runs,lost,failed,reportMode);','kept,slots,runs,lost,failed,reportMode); slots=__slotDetails;');
  check(()=>assert.ok(slots.includes('days=n;')&&start.includes('slots=__slotDetails;'),'by-reference rewiring applied'));
  const runs=[],moves=[],deleted=[],logs=[],evidenceChecks=[];
  const ctx=Object.assign(H.makeContext({}),{runs,moves,deleted,logs,Key:'GOAT',EA_Name:'GOAT V1.49',Server:'Darwinex-Demo',OP_Standard:9,
    StringToInteger:s=>parseInt(s,10)||0,
    strT:{Strat:'R0123456789abcdef0123',Model:'4',fromDate:'',toDate:''},GOAT_BATCH_CANCELLED_GV:'cancel',__cancel:false,
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
  // The correlation keeps its day count in the context global n (by reference in MQL).
  vm.runInContext(H.method('GoatDailyReturnCorrelation').replace(/function GoatDailyReturnCorrelation\(([^)]*)\)/,'function GoatDailyReturnCorrelation(csvA,csvB,from,to)'),ctx);
  vm.runInContext(slots,ctx);vm.runInContext(start,ctx);
  if(switchOn){
    // The switched StartExporter (GOAT_EXPORT_RANK_FWD_PROFIT_DD defined) and its trim log, by-reference strings rewired.
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
function loaded(ctx,rows){
  ctx.Rows=rows;ctx.RowsUnique=[];ctx.m_inputVarNames=['SL_Pips','Grid_Size'];
  ctx.startD=D('2024.01.08');ctx.forwardD=D('2025.01.06');ctx.endD=D('2025.03.15');
  const out=[];ctx.__r=out;vm.runInContext('GoatXmlFwdRank(Rows,-1,__r)',ctx);ctx.belowScoreRow=out.length?out[0]:-1;
  return ctx;
}
const pass=(n,frf,{sl=0,grid=2,score=40}={})=>row({pass:n,forward_RF:frf,Inputs:sl+','+grid,Score:score});
const sample=(changes)=>equityCsv(changes,{start:'2024.01.08'});
{
  // Slot 1 only (no other eligible pass); kept even when its re-test lost money (keepLosing).
  const t=loaded(tester({plan:[{prf:-80}]}),[pass(5,2.0)]);
  const k=vm.runInContext('StartBelowScoreExporter(false,"")',t);
  check(()=>assert.equal(k,1));
  check(()=>assert.deepEqual(t.runs.map(r=>[r.pass,r.keepLosing]),[[5,true]],'one tester run; slot 1 kept whatever its BOOS/FOOS'));
  check(()=>assert.ok(t.runs[0].mode.includes(',tier=below_score}')&&t.runs[0].mode.includes('dt_FOOS_start=2025.03.16')));
  check(()=>assert.deepEqual(t.moves,[['GOAT\\Rabcdef012345\\below_score',['exports\\5.set']]],'research units go to <run>\\below_score, never deploy'));
  check(()=>assert.match(t.__bsDetails,/^;below_score=exported;below_score_kept=1;below_score_pass=5;below_score_fwd_profit_dd=2\.0000;/));
  check(()=>assert.match(t.__bsDetails,/;slot1=kept;slot1_retest_profit=-80;slot2=none;slot2_reason=no other eligible pass$/));
  check(()=>assert.equal(t.strT.fromDate,'2023.10.02'));
  check(()=>assert.equal(t.strT.toDate,'2025.10.03'));
  check(()=>assert.deepEqual(t.__boundary.map(a=>Array.from(a)),[['auto',777000,D('2025.03.15')]],'EvidenceEnd on the broker server clock and the window end, as StartExporter'));
  const legacy=loaded(tester({settings:{EvidenceEnd:''}}),[pass(5,2.0)]);
  vm.runInContext('StartBelowScoreExporter(false)',legacy);
  check(()=>assert.equal(legacy.__boundary.length,0));
  check(()=>assert.equal(legacy.strT.toDate,'2025.10.03','no setting: the legacy last-Friday end'));
  const staged=loaded(tester({evidence:'2025.09.27'}),[pass(5,2.0)]);
  vm.runInContext('StartBelowScoreExporter(false)',staged);
  check(()=>assert.equal(staged.strT.toDate,'2025.09.27','the staged EvidenceEnd wins'));
}
{
  // Slot 2, same character: kept at SAMPLE correlation <= 0.5, skipped above it; logged either way.
  const B=wave(60,k=>Math.cos(k*1.9)*40+((k*53)%7)-3);
  for(const [label,curve2,want] of [['independent',B,'kept'],['near copy',A.map(x=>x*1.1+2),'skipped'],
                                      ['moderately correlated (about 0.71)',A.map((x,k)=>x+1.2*B[k]),'skipped']]){
    const t=loaded(tester({csv:{'exports\\5.csv':sample(A),'exports\\6.csv':sample(curve2)}}),[pass(5,2.0),pass(6,1.5)]);
    const k=vm.runInContext('StartBelowScoreExporter(false,"")',t);
    check(()=>assert.deepEqual(t.runs.map(r=>[r.pass,r.keepLosing]),[[5,true],[6,false]],label+': slot 2 is the next best, kept only when profitable'));
    check(()=>assert.equal(k,want==='kept'?2:1,label));
    check(()=>assert.ok(t.__bsDetails.includes(';slot2='+want+';'),label+': '+t.__bsDetails));
    check(()=>assert.match(t.__bsDetails,/;slot2_correlation=-?\d\.\d{3};slot2_days=59;/,label+': the correlation is recorded'));
    check(()=>assert.ok(t.logs.some(l=>/^(✅ )?Export slot 2 (kept|skipped): .*SAMPLE correlation -?\d\.\d{3}, 59 days\)\.$/.test(l)),label+': and logged'));
    if(want==='skipped'){
      check(()=>assert.deepEqual(t.deleted,['exports\\6.csv','exports\\6.set'],'a skipped slot 2 is deleted'));
      const m=t.__bsDetails.match(/;slot2_reason=same character and SAMPLE correlation (\d\.\d{3}) above 0\.5$/);
      check(()=>assert.ok(m&&+m[1]>0.5,label+': '+t.__bsDetails));
      check(()=>assert.deepEqual(t.moves[0][1],['exports\\5.set']));
    }else{
      check(()=>assert.deepEqual(t.deleted,[]));
      check(()=>assert.match(t.__bsDetails,/;slot2_reason=SAMPLE correlation -?0\.\d{3} at or below 0\.5$/));
      check(()=>assert.deepEqual(t.moves[0][1],['exports\\5.set','exports\\6.set']));
    }
  }
}
{
  // Slot 2, different character: preferred over a better same-character pass, kept even when correlated.
  const t=loaded(tester({csv:{'exports\\5.csv':sample(A),'exports\\7.csv':sample(A)}}),[pass(5,2.0),pass(6,1.9),pass(7,1.0,{sl:10})]);
  const k=vm.runInContext('StartBelowScoreExporter(false,"")',t);
  check(()=>assert.deepEqual(t.runs.map(r=>r.pass),[5,7],'the different-character pass is slot 2'));
  check(()=>assert.equal(k,2));
  check(()=>assert.match(t.__bsDetails,/;slot2_character=SL_Pips 0->10;slot2_correlation=1\.000;slot2_days=59;slot2=kept;slot2_reason=different character: SL_Pips 0->10$/));
}
{
  // The quality bar (SR >= 2.5, ARF >= 0.2, or the run's stricter MinSR/MinARF) gates slot 2 either way.
  const B=wave(60,k=>Math.cos(k*1.9)*40+((k*53)%7)-3);
  for(const [label,step,settings] of [['SR under 2.5',{sr:2.49},{}],['ARF under 0.2',{arf:0.19},{}],
                                      ['a looser run never lowers the bar',{sr:2.4},{MinSR:'1.0'}],['a stricter run raises it',{sr:2.9},{MinSR:'3.0'}]]){
    const t=loaded(tester({plan:[{},step],settings,csv:{'exports\\5.csv':sample(A),'exports\\7.csv':sample(B)}}),[pass(5,2.0),pass(7,1.0,{sl:10})]);
    const k=vm.runInContext('StartBelowScoreExporter(false,"")',t);
    check(()=>assert.equal(k,1,label));
    check(()=>assert.match(t.__bsDetails,/;slot2=skipped;slot2_reason=below the quality bar \(SR /,label));
    check(()=>assert.deepEqual(t.deleted,['exports\\7.csv','exports\\7.set'],label));
  }
}
{
  // Unknown correlation (too few SAMPLE days) never proves a same-character pass different.
  const t=loaded(tester({csv:{'exports\\5.csv':sample(A.slice(0,10)),'exports\\6.csv':sample(A.slice(0,10))}}),[pass(5,2.0),pass(6,1.5)]);
  vm.runInContext('StartBelowScoreExporter(false,"")',t);
  check(()=>assert.match(t.__bsDetails,/;slot2_correlation=na;slot2_days=9;slot2=skipped;slot2_reason=same character and SAMPLE correlation unknown \(9 days\)$/));
  // A slot 2 whose re-test lost money is never stored (not kept losing), and its correlation is not measured.
  const lost=loaded(tester({plan:[{},{prf:-5}]}),[pass(5,2.0),pass(6,1.5)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',lost),1));
  check(()=>assert.match(lost.__bsDetails,/;slot2=skipped;slot2_correlation=na;slot2_reason=re-test lost money$/));
}
{
  // Errors and refusals: nothing left behind, nothing run without a run folder, an evidence end or a pick.
  const none=loaded(tester(),[]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',none),0));
  check(()=>assert.equal(none.runs.length,0));
  check(()=>assert.equal(none.__bsDetails,';below_score=none;no_fwd_eligible_pass=1;rows=0;fwd_eligible=0;not_in_forward=0;sample_unprofitable_or_thin=0;fwd_unprofitable=0;fwd_trades_under_floor=0;fwd_dd_unmeasured=0;below_score_rank=fwd_profit_dd;below_score_min_fwd_trades=30'));
  check(()=>assert.ok(none.logs.some(l=>/^NO_FWD_ELIGIBLE_PASS rows=0;/.test(l)),'switch off: NO_FWD_ELIGIBLE_PASS is logged with counts'));
  // Profitable passes, none FWD-eligible: never silent, each counted under its first reason.
  const thin=loaded(tester(),[row({pass:1,forward_trades:29}),row({pass:2,forward_profit:-5}),row({pass:3,forward_seen:false}),row({pass:4,back_trades:49}),row({pass:5,forward_RF:0})]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false)',thin),0));
  check(()=>assert.equal(thin.runs.length,0));
  check(()=>assert.match(thin.__bsDetails,/^;below_score=none;no_fwd_eligible_pass=1;rows=5;fwd_eligible=0;not_in_forward=1;sample_unprofitable_or_thin=1;fwd_unprofitable=1;fwd_trades_under_floor=1;fwd_dd_unmeasured=1;/));
  check(()=>assert.ok(thin.logs.some(l=>l.startsWith('NO_FWD_ELIGIBLE_PASS rows=5;fwd_eligible=0;not_in_forward=1;'))));
  const noRun=loaded(tester({runPath:''}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',noRun),-1));
  check(()=>assert.equal(noRun.runs.length,0));
  const refused=loaded(tester({evidence:''}),[pass(5,2.0)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',refused),-1));
  check(()=>assert.equal(refused.runs.length,0));
  const unmoved=loaded(tester({move:false,csv:{'exports\\5.csv':sample(A),'exports\\7.csv':sample(A)}}),[pass(5,2.0),pass(7,1.0,{sl:10})]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',unmoved),-1));
  check(()=>assert.deepEqual(unmoved.deleted,['exports\\5.csv','exports\\5.set','exports\\7.csv','exports\\7.set'],'never left where normal exports are read'));
  check(()=>assert.match(unmoved.__bsDetails,/^;below_score=failed;/));
  const error=loaded(tester({plan:[{error:true}]}),[pass(5,2.0),pass(6,1.5)]);
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',error),-1));
  check(()=>assert.deepEqual(error.runs.map(r=>r.pass),[5],'slot 1 is never replaced by another pass'));
  check(()=>assert.match(error.__bsDetails,/;slot1=failed;slot2=skipped;slot2_reason=no slot 1$/));
  const moved=loaded(tester(),[pass(5,2.0)]);
  moved.belowScoreRow=0;moved.Rows.push(pass(6,9.0));
  check(()=>assert.equal(vm.runInContext('StartBelowScoreExporter(false,"")',moved),-1,'the ranking must still start with the combine pick'));
  const cancelled=loaded(tester({cancelAfter:1}),[pass(5,2.0),pass(6,1.5)]);
  vm.runInContext('StartBelowScoreExporter(false,"")',cancelled);
  check(()=>assert.deepEqual(cancelled.runs.map(r=>r.pass),[5],'a cancel stops before slot 2'));
}
{
  // Normal exports with the switch on: same slot rule, no tier, slot 1 kept only when profitable, and a
  // losing slot 1 is never replaced by the next pass (no FOOS selection).
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
  // The tier: parsed from EA_Desc (a key without "mode") and written into the SET header after the windows.
  const {P}=mainFunctions(FLAGS);
  check(()=>assert.ok(P.includes('if(names[i]=="tier" && values[i]==GOAT_XML_BELOW_SCORE)')));
  check(()=>assert.ok(!/mode/i.test('tier'),'"tier" never reads as the export mode key'));
  const header=P.slice(P.indexOf('temp="FOOS:   "'),P.indexOf('temp="--------',P.indexOf('temp="FOOS:   "')));
  check(()=>assert.ok(header.includes('if(g_goatBelowScoreExport) {')&&header.includes('temp="EXPORT: "+GOAT_XML_BELOW_SCORE+" research only')));
  check(()=>assert.equal(XMACROS.GOAT_XML_BELOW_SCORE,'"below_score"'));
  check(()=>assert.equal(XMACROS.GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES,'30'));
  // RunAndStoreSet keeps a losing re-test only for an explicit keepLosing caller.
  check(()=>assert.ok(P.includes('const bool keepLosing=false)')&&P.includes('if(profit>0 || keepLosing)')));
  check(()=>assert.equal(P.split(',3,keepLosingSlot1)').length,2,'only slot 1 of GoatExportSlots passes keepLosing'));
  check(()=>assert.equal(P.split('keepLosing').length-P.split('keepLosingSlot1').length,2,'otherwise only RunAndStoreSet declares and reads it'));
  check(()=>assert.ok(P.includes('GoatExportSlots(ranked,",tier="+GOAT_XML_BELOW_SCORE,true,')));
}
{
  // Switch ON (GOAT_EXPORT_RANK_FWD_PROFIT_DD), Claude-Mac 6023896492: a member never exports nothing silently.
  const exporterRun=(rows,opts={})=>{const t=loaded(tester({...opts,switchOn:true}),rows);t.outcome='';t.passesSeen=158;t.profitableSeen=7;
    t.tradedSeen=158;t.malformedSeen=0;t.reportClosed=true;t.forwardRows=158;t.bestProfit=660;t.bestResult=0.56;t.forwardMatched=rows.length;
    t.bestCombinedScore=Math.max(0,...rows.map(r=>r.Score));t.g_allExports=[];
    const ok=vm.runInContext('StartExporter(false)',t);return {t,ok};};
  // (a) Score-qualifying passes exist but none is FWD-eligible: fall through to below_score, the best FWD profit/DD pass.
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_trades:20,forward_RF:9}),row({pass:6,Score:41,forward_RF:1.4}),row({pass:7,Score:30,forward_RF:2.2})]);
    check(()=>assert.equal(ok,false,'nothing qualifying is exported'));
    check(()=>assert.deepEqual(t.runs.filter(r=>!r.init).map(r=>[r.pass,r.keepLosing]),[[7,true],[6,false]],'below_score slot 1 = best FWD profit/DD among eligible passes, whatever its score'));
    check(()=>assert.ok(t.runs.filter(r=>!r.init).every(r=>r.mode.includes(',tier=below_score}'))));
    check(()=>assert.equal(t.g_goatFwdFallthrough,true));
    const d=t.g_goatFwdFallthroughDetails;
    check(()=>assert.match(d,/^outcome=no_fwd_eligible_rows;passes=158;/));
    check(()=>assert.match(d,/;back_rows=3;forward_matched=3;best_combined_score=72\.0;score_threshold=60\.0;score_qualifying_rows=1;below_score=exported;/));
    check(()=>assert.equal(t.outcome,'','the combine outcome is restored'));
    check(()=>assert.ok(t.logs.some(l=>/^No pass at or above MinScore 60\.0 is FWD-eligible \(rows=3;fwd_eligible=0;.*fwd_trades_under_floor=1;.*below_min_score=2;at_min_score=1\): falling through to the below_score export\.$/.test(l))));
    check(()=>assert.deepEqual(t.moves.map(m=>m[0]),['GOAT\\Rabcdef012345\\below_score'],'research only, never deploy'));
  }
  // (b) Nothing FWD-eligible at all: NO_FWD_ELIGIBLE_PASS with counts, no tester run beyond the top-set check.
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_trades:20}),row({pass:6,Score:41,forward_profit:-3})]);
    check(()=>assert.equal(ok,false));
    check(()=>assert.equal(t.runs.filter(r=>!r.init).length,0));
    check(()=>assert.ok(t.logs.some(l=>l.startsWith('NO_FWD_ELIGIBLE_PASS rows=2;fwd_eligible=0;not_in_forward=0;sample_unprofitable_or_thin=0;fwd_unprofitable=1;fwd_trades_under_floor=1;'))));
    check(()=>assert.match(t.g_goatFwdFallthroughDetails,/;score_qualifying_rows=1;below_score=none;no_fwd_eligible_pass=1;rows=2;/));
  }
  // (c) A FWD-eligible pass at or above MinScore: the normal slot rule, no tier, no fall-through.
  {
    const {t,ok}=exporterRun([row({pass:5,Score:72,forward_RF:1.1}),row({pass:6,Score:41,forward_RF:9})]);
    check(()=>assert.equal(ok,true));
    check(()=>assert.deepEqual(t.runs.filter(r=>!r.init).map(r=>[r.pass,r.keepLosing]),[[5,false]],'only the 60+ pass; a better FWD pass under the score never takes it'));
    check(()=>assert.ok(!t.runs.some(r=>r.mode.includes('tier='))));
    check(()=>assert.equal(t.g_goatFwdFallthrough,false));
    check(()=>assert.deepEqual(t.moves,[['GOAT\\Rabcdef012345\\deploy',['exports\\5.set']]],'a normal export goes to deploy'));
    check(()=>assert.ok(t.logs.some(l=>/^SortAndTrimExports: Total=1 Passing=1 Kept=1 Trimmed=0$/.test(l)),'the EA-log cross-check line'));
  }
  // The OnTesterDeinit row with the switch on: NoFwdEligibleRows with the fall-through details, never "Completed".
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
  // The switch carries its resolve-by date, and stays off.
  check(()=>assert.match(mainRaw,/RESOLVE BY 2026-10-13, NOT A DORMANT FLAG/));
}console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
