// B49b PR-7 (F8: export integrity; goatai#2587 6433828681, Claude-Mac 6411161557, 6433854745 ruling 3, 6443122557).
// The production functions run here from GOAT V1.49.mq5, Tester.mqh and XmlProcessor.mqh, side by side with B49a's
// (source 693cad0) where B49a had the code:
// 1. OPT-01, the trim (SortAndTrimExports): B49a kept the top passCnt rows by ARF x SR whether they passed or not and
//    deleted the rest from disk. B49b keeps only passing rows (at most keepTop, ranked by ExportRank), deletes no
//    passing row it could keep, keeps the best-ranked row alone when none pass, and logs Passing= as the passing rows
//    kept (the controller's export-qualification cross-check reads that line). Where B49a's choice was already all
//    passers, B49b's ARFxSR choice is identical.
// 2. ExportRank (export settings): absent or ARFxSR ranks on ARF x SR, PF on the profit factor, anything else refuses
//    the export cycle before a tester run. PF rides to the export run as rank=pf, and the run stamps it.
// 3. OPT-04: a forward row that repeats its pass, or disagrees on the back result or the inputs, is marked and scores 0,
//    so WriteTopToXml (Score >= GOAT_XML_MIN_COMBINED_SCORE, sorted, stops below it) never exports it.
// 4. R16: BOOS, SAMPLE and FWD P/L include each window's last day (closed at the next window's open, or at the final
//    equity when the test ends inside it); FWD membership is by calendar day, so dt_FWD_end's own day counts, for the
//    days and the trades alike. B49a's P/L stopped at the last day's open.
// 5. R17: one final equity-CSV row at the test's end, unless that minute already has one.
// 6. R21: the wait for the tester after the top-set check is bounded (600 s), then refuses the export cycle.
// 7. The export-format stamp: "; EXPORT format:2 rank:arf_sr|pf", after the B44 stamp in both WriteSet branches, no "=".
// test_b49b_f8_mutations.cjs runs this file on mutated sources (GOAT_EA_MAIN, GOAT_EA_TESTER, GOAT_EA_XML).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
const clean=t=>t.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const read=(env,file)=>clean(fs.readFileSync(process.env[env]||path.join(ROOT,file),'utf8'));
const main=read('GOAT_EA_MAIN','GOAT V1.49.mq5'),tester=read('GOAT_EA_TESTER','Tester.mqh'),xml=read('GOAT_EA_XML','XmlProcessor.mqh');
const old=f=>clean(execFileSync('git',['show',B49A_SOURCE+':'+f],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8'));
const mainB49a=old('GOAT V1.49.mq5'),testerB49a=old('Tester.mqh');
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime|ExportRecord)';
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(/\bstring (\w+)\[\];/g,'let $1=[];')
 .replace(/\(long\)(\w+(?:\(\))?)\/(\d+)/g,'Math.floor($1/$2)')   // MQL's integer division
 .replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ').replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const fmt=(f,...a)=>{let i=0;return f.replace(/%%|%(\.\d+)?([dfs])/g,(m,p,t)=>{if(m==='%%')return '%';const v=a[i++];return t==='f'?Number(v).toFixed(p?Number(p.slice(1)):6):String(v);});};
const define=(text,name)=>{const m=text.match(new RegExp('^#define\\s+'+name+'\\s+(\\S+)','m'));assert.ok(m,'missing #define '+name);return Number(m[1]);};

// ---- 1-2. The trim, B49b's and B49a's, on the same records ----
const SIG_B49A='void SortAndTrimExports(const int keepTop,const double minARF,const double minSR,ExportRecord &expArr[])';
const SIG='void SortAndTrimExports(const int keepTop,const double minARF,const double minSR,ExportRecord &expArr[],const int rank=GOAT_EXPORT_RANK_ARFxSR)';
const RANK_ARFxSR=define(tester,'GOAT_EXPORT_RANK_ARFxSR'),RANK_PF=define(tester,'GOAT_EXPORT_RANK_PF');
function trimmer(b49a){
 const c={deleted:[],logs:[],strT:{_K:'k',_N:'n',_S:'s'},GOAT_EXPORT_RANK_ARFxSR:RANK_ARFxSR,GOAT_EXPORT_RANK_PF:RANK_PF,StringFormat:fmt,
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},DeleteExports:f=>{c.deleted.push(...f);},
  WriteLog:t=>{c.logs.push(t);},PrintFormat:()=>{}};
 vm.createContext(c);
 const src=b49a?fn('SortAndTrimExports',['keepTop','minARF','minSR','expArr'],bodyOf(testerB49a,SIG_B49A))
  :fn('GoatExportRankSetting',['value'],bodyOf(tester,'int GoatExportRankSetting(const string value)'))
   +fn('GoatExportRankScore',['r','rank'],bodyOf(tester,'double GoatExportRankScore(const ExportRecord &r,const int rank)'))
   +fn('GoatExportPasses',['r','minARF','minSR'],bodyOf(tester,'bool   GoatExportPasses(const ExportRecord &r,const double minARF,const double minSR)'))
   +fn('GoatExportBefore',['a','b','minARF','minSR','rank'],bodyOf(tester,'bool   GoatExportBefore(const ExportRecord &a,const ExportRecord &b,const double minARF,const double minSR,const int rank)'))
   +fn('SortAndTrimExports',['keepTop','minARF','minSR','expArr','rank=GOAT_EXPORT_RANK_ARFxSR'],bodyOf(tester,SIG));
 vm.runInContext(src,c);
 return c;
}
let seed=4242;const rnd=()=>((seed=(seed*1103515245+12345)%2147483648)/2147483648);
const rec=(i,arf,sr,pf)=>({csvFile:'c'+i,setFile:'s'+i,arf,sr,pf,trds:0,prf:1,dd:1,rowIndex:i});
const TRIMMERS={};   // one sandbox per build, reset per call
const trim=(b49a,records,keepTop,minARF,minSR,rank)=>{const c=TRIMMERS[b49a]||(TRIMMERS[b49a]=trimmer(b49a)),arr=records.map(r=>({...r}));
 c.deleted.length=0;c.logs.length=0;
 if(b49a)c.SortAndTrimExports(keepTop,minARF,minSR,arr);else c.SortAndTrimExports(keepTop,minARF,minSR,arr,rank);
 return {kept:arr.map(r=>r.rowIndex),deleted:[...c.deleted],log:c.logs.join('\n'),c};};
const passes=(r,a,s)=>r.arf>=a&&r.sr>=s;

{// 1a. The audit's case: ARF x SR ranks a failing row (SR below MinSR) above a passing one. B49a keeps the failing row and
 //     deletes the passing one; B49b keeps the passing one and deletes the failing one.
 const rows=[rec(0,2.0,2.0,1.2),rec(1,0.3,3.0,1.5)];   // MinARF 0.2, MinSR 2.5: row 0 fails (SR), row 1 passes
 const a=trim(true,rows,2,0.2,2.5),b=trim(false,rows,2,0.2,2.5,RANK_ARFxSR);
 assert.deepEqual(a.kept,[0],'B49a keeps the failing row');assert.deepEqual(a.deleted,['c1','s1'],'B49a deletes the passing row from disk');
 assert.deepEqual(b.kept,[1],'B49b keeps the passing row');assert.deepEqual(b.deleted,['c0','s0'],'and deletes the failing one');
 // Ties keep the earlier row, as B49a's strict > did (Claude-Mac 6470355579: a >= mutant must die).
 for(const rank of [RANK_ARFxSR,RANK_PF]){const tie=trim(false,[rec(0,1,3,2),rec(1,0.2,2.5,0.5),rec(2,1,3,2)],1,0.2,2.5,rank);assert.deepEqual(tie.kept,[0],'tie: the earlier row ('+rank+')');}
 const tieA=trim(true,[rec(0,1,3,2),rec(1,0.2,2.5,0.5),rec(2,1,3,2)],1,0.2,2.5);assert.deepEqual(tieA.kept,[0],'B49a too');
 // A row exactly at both bars passes, as B49a's >= (and the EA's own store comparison) has it.
 const bar=trim(false,[rec(0,0.2,2.5,1),rec(1,0.19,9,1)],2,0.2,2.5,RANK_ARFxSR);
 assert.deepEqual(bar.kept,[0],'at the bar: passing');assert.match(bar.log,/Passing=1 Kept=1/);
 ok();}
{// 1b. Properties, on random record sets (2..25 rows, keepTop 2..12, mixed pass rates).
 let differed=0,same=0;
 for(let t=0;t<1000;t++){
  const n=2+Math.floor(rnd()*24),keepTop=2+Math.floor(rnd()*11),minARF=0.2,minSR=2.5,pr=rnd();
  const rows=[...Array(n)].map((_,i)=>rec(i,rnd()<pr?0.2+rnd()*2:rnd()*0.2,rnd()<pr?2.5+rnd()*3:rnd()*2.5,0.5+rnd()*3));
  for(const rank of [RANK_ARFxSR,RANK_PF]){
   const b=trim(false,rows,keepTop,minARF,minSR,rank),pass=rows.filter(r=>passes(r,minARF,minSR));
   const score=r=>rank===RANK_PF?r.pf:r.arf*r.sr,byRank=[...pass].sort((x,y)=>score(y)-score(x));
   if(pass.length){
    assert.deepEqual(b.kept,byRank.slice(0,keepTop).map(r=>r.rowIndex),'kept = the top keepTop passing rows by rank, in rank order');
    const keptSet=new Set(b.kept);
    for(const r of pass) if(!keptSet.has(r.rowIndex)) assert.ok(byRank.indexOf(r)>=keepTop,'a passing row is deleted only beyond keepTop');
   } else {
    const best=[...rows].sort((x,y)=>score(y)-score(x))[0];
    assert.deepEqual(b.kept,[best.rowIndex],'none pass: the best-ranked row alone');
    assert.match(b.log,/fallback: none passed/,'and the log says so');
   }
   assert.equal(b.deleted.length,2*(n-b.kept.length),'every trimmed row loses its csv and set');
   const m=b.log.match(/SortAndTrimExports: Total=(\d+) Passing=(\d+) Kept=(\d+)/);   // studio_export_qualification _TRIM
   assert.ok(m,'the controller\'s trim regex reads the line');
   assert.deepEqual([+m[1],+m[2],+m[3]],[n,Math.min(pass.length,keepTop),b.kept.length],'Total, Passing (passing rows kept), Kept');
   assert.match(b.log,new RegExp(' Rank='+(rank===RANK_PF?'PF':'ARFxSR')+'\\b'));
   if(rank===RANK_ARFxSR){
    const a=trim(true,rows,keepTop,minARF,minSR);
    if(a.kept.every(i=>passes(rows[i],minARF,minSR))&&a.kept.length>0&&pass.length){assert.deepEqual(b.kept,a.kept,'B49a already right: same choice');same++;}
    else if(pass.length)differed++;
   }
  }
 }
 assert.ok(differed>100&&same>100,'both kinds of case reached ('+differed+' differed, '+same+' same)');
 ok();}
{// 1c. n <= 1: nothing to trim (no log, no delete), as B49a.
 for(const rows of [[],[rec(0,0,0,0)]]){const b=trim(false,rows,5,0.2,2.5,RANK_PF);assert.deepEqual(b.deleted,[]);assert.equal(b.log,'');}
 ok();}
{// 2. ExportRank: the setting, the refusal before any tester run, the meta and the stamp.
 const c=trimmer(false);
 for(const [v,want] of [['',RANK_ARFxSR],['ARFxSR',RANK_ARFxSR],['PF',RANK_PF],['pf',-1],['ARF',-1],[' PF',-1],['1',-1]]) assert.equal(c.GoatExportRankSetting(v),want,'ExportRank='+JSON.stringify(v));
 const exporter=bodyOf(main,'bool StartExporter(bool reportMode)');
 const refuse=exporter.indexOf('if(ExportRank<0) {LogOrPrint(reportMode,"❌ ExportRank in the export settings must be ARFxSR or PF; the export cycle did not start.",Key,EA_Name,Server); return false;}');
 assert.ok(refuse>0&&refuse<exporter.indexOf('RunAndStoreSet('),'an unknown ExportRank refuses before any tester run');
 assert.match(exporter,/int    ExportRank  = GoatExportRankSetting\(FetchExportSetting\("ExportRank",Key,EA_Name,Server\)\);/);
 assert.match(exporter,/fwdRangeMeta\+\(BlindExport \? ",blind=1" : ""\)\+\(ExportRank==GOAT_EXPORT_RANK_PF \? ",rank=pf" : ""\)\+"\}\\n"/,'rank=pf rides in the export run meta only for PF');
 assert.equal((exporter.match(/SortAndTrimExports\(SetsToExport,MinARF,MinSR,(?:g_allExports|AdjustedExports),ExportRank\);/g)||[]).length,2,'both trims use it');
 assert.equal((exporter.match(/SortAndTrimExports\(/g)||[]).length,2);
 assert.match(main,/if\(names\[i\]=="rank" && values\[i\]=="pf"\) g_GoatExportRank=GOAT_EXPORT_RANK_PF;/,'the export run reads it');
 ok();}

// ---- 3. OPT-04 ----
{const forward=bodyOf(xml,'bool ProcessForwardXml(const string filename)');
 assert.match(xml,/bool forward_mismatch;/);
 assert.match(bodyOf(xml,'SRowDefinition()'),/forward_mismatch=false;/,'a new row is clean');
 assert.match(bodyOf(xml,'SRowDefinition(const SRowDefinition &src)'),/forward_mismatch=src\.forward_mismatch;/,'a copy keeps the mark (topRowsNoDup, RowsUnique)');
 // Each of B49a's three mismatch counts now marks its row.
 const counts=[...forward.matchAll(/forwardMismatches\+\+;([^\n]*)/g)].map(m=>m[1]);
 assert.equal(counts.length,3,'three mismatch paths');
 for(const tail of counts) assert.match(tail,/^\s*(?:Rows\[bPos\]\.forward_mismatch=true;|\} \/\/)|Rows\[bPos\]\.forward_mismatch=true;/,'each marks the row');
 assert.match(forward,/if\(Rows\[bPos\]\.forward_seen\) \{forwardMismatches\+\+; Rows\[bPos\]\.forward_mismatch=true;\}/,'a repeated pass');
 assert.match(forward,/if\(Rows\[bPos\]\.back_result!=tmpBackResult\)\s*\{\s*forwardMismatches\+\+; Rows\[bPos\]\.forward_mismatch=true;/,'a back-result mismatch');
 assert.match(forward,/if\(Inputsforward!=Rows\[bPos\]\.Inputs\)\s*\{\s*forwardMismatches\+\+; Rows\[bPos\]\.forward_mismatch=true;/,'an inputs mismatch');
 // The rejection runs after the last score assignment of the row, so nothing re-scores it.
 const lastScore=forward.lastIndexOf('Rows[bPos].Score=CalculateCustomScore2('),reject=forward.indexOf('if(Rows[bPos].forward_mismatch)');
 assert.ok(lastScore>0&&reject>lastScore,'rejected after scoring');
 assert.match(forward.slice(reject),/^if\(Rows\[bPos\]\.forward_mismatch\)\s*\{\s*Rows\[bPos\]\.Score=0;/);
 assert.equal(forward.slice(reject).search(/Rows\[bPos\]\.Score=/),forward.slice(reject).indexOf('Rows[bPos].Score=0;'),'and its only later score write is 0');
 // A score of 0 is never exported: WriteTopToXml stops at the first row below minScore, called with the combined bar.
 const top=bodyOf(xml,'int WriteTopToXml(const string xmlFileName,int count = 100,double minScore = 70.0)');
 assert.match(top,/if\(s < minScore\) break;/);
 assert.ok(define(xml,'GOAT_XML_MIN_COMBINED_SCORE')>0);
 const combiner=bodyOf(xml,'bool ReportAnalyzerCombiner(string &Files[],bool reportMode,string Key_,string EA_Name_,string Server_)');
 assert.match(combiner,/WriteTopToXml \(baseName\+"_CombinedRows_Score="\+scorePostfix\+"\.xml",100,GOAT_XML_MIN_COMBINED_SCORE\)/);
 assert.ok(combiner.indexOf('SortRowsByScoreDescending')>=0||xml.indexOf('SortRowsByScoreDescending();')>=0,'rows are sorted before WriteTopToXml');
 ok();}

// ---- 4. R16: the window P/L, B49b's and B49a's day blocks on the same days ----
const DAY=86400;
function dayBlock(text){
 const body=bodyOf(text,'void GoatTickBody()');
 const a=body.indexOf('DStartEquity=AccountInfoDouble(ACCOUNT_EQUITY);'),b=body.indexOf('DLastTime=TimeCurrent();');
 assert.ok(a>0&&b>a,'the day block');
 return body.slice(a,b);
}
function windows(text,{days,boos,foos,fwdStart,fwdEnd,equity,finalEquity,tickAt=60}){
 const c={now:0,eq:0,dt_Back_OOS:boos*DAY,dt_Fwrd_OOS:foos?foos*DAY:0,dt_FWD_start:fwdStart*DAY,dt_FWD_end:fwdEnd*DAY,
  days_BOOS:0,days_IS:0,days_FOOS:0,days_FWD:0,eq_BOOS_start:0,eq_BOOS_end:0,eq_IS_start:0,eq_IS_end:0,eq_FOOS_start:0,eq_FWD_start:0,eq_FWD_end:0,
  dt_IS_end:0,DLastTime:0,DStartEquity:0,g_GoatFwdClosed:false,ACCOUNT_EQUITY:1,TimeCurrent:()=>c.now,AccountInfoDouble:()=>c.eq};
 vm.createContext(c);
 const b49b=text===main;
 vm.runInContext((b49b?fn('GoatFwdDay',['when'],bodyOf(main,'bool GoatFwdDay(const datetime when)'))
  +fn('GoatCloseOpenWindows',[],bodyOf(main,'void GoatCloseOpenWindows(void)')):'')
  +'function day(){'+js(dayBlock(text)).replace(/\blet DStartEquity\b/,'DStartEquity')+'}',c);
 for(let d=0;d<days;d++){c.now=d*DAY+tickAt;c.eq=equity[d];c.day();}
 c.eq=finalEquity;if(b49b)c.GoatCloseOpenWindows();
 return {BOOS:c.eq_BOOS_end-c.eq_BOOS_start,SAMPLE:c.eq_IS_end-c.eq_IS_start,FWD:c.eq_FWD_end-c.eq_FWD_start,days_FWD:c.days_FWD,days_IS:c.days_IS,days_BOOS:c.days_BOOS,c};
}
{// 4a. Every day moves the equity, so a missing day shows. Days 0-9 BOOS, 10-29 SAMPLE (FWD 20-29), FOOS from 30.
 const equity=[...Array(40)].map((_,d)=>10000+d*d*7+d*13),fin=99999;
 const spec={days:40,boos:10,foos:30,fwdStart:20,fwdEnd:29,equity,finalEquity:fin};
 const b=windows(main,spec),a=windows(mainB49a,spec);
 assert.equal(b.BOOS,equity[10]-equity[0],'BOOS: day 0 open to day 10 open (days 0-9)');
 assert.equal(b.SAMPLE,equity[30]-equity[10],'SAMPLE: day 10 open to the FOOS open (days 10-29)');
 assert.equal(b.FWD,equity[30]-equity[20],'FWD: day 20 open to day 30 open (days 20-29)');
 assert.equal(b.days_FWD,10,'FWD counts dt_FWD_end\'s own day');
 assert.equal(a.BOOS,equity[9]-equity[0],'B49a: BOOS stops at its last day\'s open');
 assert.equal(a.SAMPLE,equity[29]-equity[10],'B49a: SAMPLE too');
 assert.equal(a.FWD,equity[28]-equity[20],'B49a: FWD stops a day earlier still (dt_FWD_end\'s day is not FWD)');
 assert.equal(a.days_FWD,9);
 assert.deepEqual([b.days_BOOS,b.days_IS],[a.days_BOOS,a.days_IS],'BOOS and SAMPLE day counts unchanged');
 ok();}
{// 4b. The test ends inside a window: it closes at the final equity (as FOOS always did).
 const equity=[...Array(25)].map((_,d)=>5000+d*31),fin=7777;
 const inSample=windows(main,{days:25,boos:10,foos:30,fwdStart:20,fwdEnd:29,equity,finalEquity:fin});
 assert.equal(inSample.SAMPLE,fin-equity[10]);assert.equal(inSample.FWD,fin-equity[20]);assert.equal(inSample.BOOS,equity[10]-equity[0]);
 const inBoos=windows(main,{days:8,boos:10,foos:30,fwdStart:20,fwdEnd:29,equity,finalEquity:fin});
 assert.equal(inBoos.BOOS,fin-equity[0],'BOOS open at the end');assert.equal(inBoos.days_IS,0);
 const noFoos=windows(main,{days:25,boos:10,foos:0,fwdStart:15,fwdEnd:19,equity,finalEquity:fin});
 assert.equal(noFoos.SAMPLE,fin-equity[10],'no FOOS: SAMPLE to the end');assert.equal(noFoos.FWD,equity[20]-equity[15],'FWD closed at day 20\'s open');
 const noBoos=windows(main,{days:25,boos:0,foos:30,fwdStart:20,fwdEnd:22,equity,finalEquity:fin});
 assert.equal(noBoos.BOOS,0,'no BOOS: no BOOS P/L');assert.equal(noBoos.SAMPLE,fin-equity[0]);assert.equal(noBoos.FWD,equity[23]-equity[20]);
 // Claude-Mac 6470355579: BOOS straight into FOOS (no SAMPLE day) closes at the FOOS open.
 const boosFoos=windows(main,{days:25,boos:10,foos:10,fwdStart:0,fwdEnd:0,equity,finalEquity:fin});
 assert.equal(boosFoos.days_IS,0);assert.equal(boosFoos.BOOS,equity[10]-equity[0],'BOOS: day 0 open to the FOOS open');
 const noFwd=windows(main,{days:25,boos:10,foos:30,fwdStart:0,fwdEnd:0,equity,finalEquity:fin});
 assert.equal(noFwd.days_FWD,0);assert.equal(noFwd.FWD,0);
 ok();}
{// 4c. GoatFwdDay and the FWD trade count share one calendar-day window.
 const c={dt_FWD_start:20*DAY,dt_FWD_end:29*DAY};vm.createContext(c);vm.runInContext(fn('GoatFwdDay',['when'],bodyOf(main,'bool GoatFwdDay(const datetime when)')),c);
 for(const [t,want] of [[20*DAY-1,false],[20*DAY,true],[29*DAY,true],[29*DAY+DAY-1,true],[30*DAY,false]]) assert.equal(c.GoatFwdDay(t),want,'t='+t);
 c.dt_FWD_end=0;assert.equal(c.GoatFwdDay(25*DAY),false,'off without both dates');
 assert.match(main,/if\(GoatFwdDay\(TimeCurrent\(\)\)\) trd_FWD\+\+;/,'trd_FWD by the same window');
 assert.match(dayBlock(main),/if\(GoatFwdDay\(TimeCurrent\(\)\)\)/,'days_FWD by the same window');
 assert.ok(!/TimeCurrent\(\)<=dt_FWD_end/.test(main),'no clock comparison with dt_FWD_end\'s midnight is left');
 // OnTester closes open windows before it prints them.
 const onTester=bodyOf(main,'double OnTester()');
 const close=onTester.indexOf('GoatCloseOpenWindows();');assert.ok(close>0&&close<onTester.indexOf('temp="BOOS:   "'),'closed before the window lines');
 ok();}

// ---- 5. R17: the equity CSV's final row ----
{const mk=(last,values='')=>{const c={rows:[],FileCSV_handle:7,INVALID_HANDLE:-1,g_GoatCsvLastMinute:last,g_GoatCsvLastValues:values,now:1000*60+30,ACCOUNT_BALANCE:1,ACCOUNT_EQUITY:2,TIME_DATE:1,TIME_MINUTES:2,
  TimeCurrent:()=>c.now,TimeToString:t=>'T'+t,DoubleToString:(v,d)=>Number(v).toFixed(d),AccountInfoDouble:k=>k===1?1000:987.65,FileWrite:(h,...a)=>c.rows.push([h,...a])};
  vm.createContext(c);vm.runInContext(fn('GoatEquityCsvFinalRow',[],bodyOf(main,'void GoatEquityCsvFinalRow(void)')),c);return c;};
 const c=mk(999,'1000.00\t990.00');c.GoatEquityCsvFinalRow();
 assert.deepEqual(c.rows,[[7,'T60030','1000.00','987.65',0]],'one row: time, balance, equity, deposit load as the minute rows');
 assert.equal(c.g_GoatCsvLastMinute,1000);c.GoatEquityCsvFinalRow();assert.equal(c.rows.length,1,'never twice for one state');
 const d=mk(1000,'1000.00\t987.65');d.GoatEquityCsvFinalRow();assert.deepEqual(d.rows,[],'the last row already says this, this minute');
 // Claude-Mac 6470355579: a shared minute whose equity (or balance) changed still gets the final row.
 const g=mk(1000,'1000.00\t990.00');g.GoatEquityCsvFinalRow();assert.deepEqual(g.rows,[[7,'T60030','1000.00','987.65',0]],'same minute, equity changed');
 const h=mk(1000,'999.00\t987.65');h.GoatEquityCsvFinalRow();assert.equal(h.rows.length,1,'same minute, balance changed');
 const e=mk(-1);e.FileCSV_handle=-1;e.GoatEquityCsvFinalRow();assert.deepEqual(e.rows,[],'no file, no row');
 const onTester=bodyOf(main,'double OnTester()');
 assert.match(onTester,/if\(FileCSV_handle != INVALID_HANDLE\) \{GoatEquityCsvFinalRow\(\); FileClose\(FileCSV_handle\); FileCSV_handle=INVALID_HANDLE;\}/,'written before the close');
 const tick=bodyOf(main,'void GoatTickBody()');
 assert.match(tick,/,0\.0\);\/\/\(AccountInfoDouble\(ACCOUNT_MARGIN\)\/AccountInfoDouble\(ACCOUNT_EQUITY\)\)\*100\.0;\n\s*g_GoatCsvLastMinute=\(long\)TimeCurrent\(\)\/60; g_GoatCsvLastValues=DoubleToString\(AccountInfoDouble\(ACCOUNT_BALANCE\),2\)\+"\\t"\+DoubleToString\(MinuteLowEquity,2\);/,'every minute row records its minute and the values it wrote');
 ok();}
// ---- 6. R21: the bounded tester wait ----
{const exporter=bodyOf(main,'bool StartExporter(bool reportMode)');
 assert.equal(define(main,'GOAT_TESTER_READY_WAIT_MS'),600000);
 const w=exporter.indexOf('while(!MTTESTER::IsReady())');assert.ok(w>0);
 assert.match(exporter.slice(exporter.lastIndexOf('\n',exporter.lastIndexOf('\n',w)-1),w),/ulong readyDeadline=GetTickCount64\(\)\+GOAT_TESTER_READY_WAIT_MS;/,'the deadline is set right before the loop');
 const loop=exporter.slice(w,exporter.indexOf('}',exporter.indexOf('Sleep(1000);',w)));
 assert.match(loop,/if\(GetTickCount64\(\)>readyDeadline\) \{LogOrPrint\([^;]*\); return false;\}/,'past it, the export cycle refuses');
 assert.ok(loop.indexOf('return false;}')<loop.indexOf('Sleep(1000);'),'checked every pass');
 // Simulated: a tester that never becomes ready returns false after the bound, a ready one goes on.
 const run=(readyAfterMs)=>{let t=0;const c={GetTickCount64:()=>t,GlobalVariableGet:()=>0,GOAT_BATCH_CANCELLED_GV:'x',GOAT_TESTER_READY_WAIT_MS:600000,
  MTTESTER:{IsReady:()=>t>=readyAfterMs},Sleep:ms=>{t+=ms;},LogOrPrint:()=>{},IntegerToString:String,reportMode:false,Key:'',EA_Name:'',Server:''};
  vm.createContext(c);return vm.runInContext('(function(){'+js(exporter.slice(exporter.lastIndexOf('\n',exporter.lastIndexOf('\n',w)-1),exporter.indexOf('}',exporter.indexOf('Sleep(1000);',w))+1)).replace(/MTTESTER::/g,'MTTESTER.')+' return true;})()',c);};
 assert.equal(run(5000),true,'ready after 5 s');assert.equal(run(1e12),false,'never ready: refused');
 ok();}

// ---- 7. The export-format stamp ----
{const line=rank=>{const c={g_GoatExportRank:rank,GOAT_EXPORT_FORMAT:define(main,'GOAT_EXPORT_FORMAT'),GOAT_EXPORT_RANK_PF:RANK_PF,IntegerToString:String};
  vm.createContext(c);vm.runInContext(fn('GoatExportFormatLine',[],bodyOf(main,'string GoatExportFormatLine(void)')),c);return c.GoatExportFormatLine();};
 assert.equal(line(RANK_ARFxSR),'; EXPORT format:2 rank:arf_sr');assert.equal(line(RANK_PF),'; EXPORT format:2 rank:pf');
 for(const l of [line(0),line(1)]){assert.ok(!l.includes('='),'no = (every controller writer drops it)');assert.ok(l.startsWith('; EXPORT'),'the deploy writers\' stamp prefix');}
 assert.match(main,/int    g_GoatExportRank=GOAT_EXPORT_RANK_ARFxSR;/,'ARFxSR unless the run says rank=pf');
 assert.match(main,/if\(g_GoatBlindExport\) WriteSet\(GoatBlindDesc\(desc\)\+"\\n"\+GoatExportFormatLine\(\)\);[^\n]*\n\s+else\s+WriteSet\(desc\+"\\n; EXPORT blind:0 ranked:full_span sr:mt5_stat\\n"\+GoatExportFormatLine\(\)\);/,'both branches, after the B44 stamp');
 // B49a wrote no format line: its exports are format 1.
 assert.ok(!/EXPORT format:/.test(mainB49a));
 ok();}

// ---- 8. The rank:pf read-back (Claude-Mac 6469934085): with ExportRank=PF, an export whose stamp does not say
//      rank:pf (a meta cut short) is refused before it is moved or stored, never kept mislabelled ----
{const says=(()=>{const c={GOAT_EXPORT_FORMAT:define(main,'GOAT_EXPORT_FORMAT'),IntegerToString:String,StringFind:(s,t)=>s.indexOf(t),
  StringSplit:(s,ch,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(ch)));return out.length;}};
  vm.createContext(c);vm.runInContext(fn('GoatExportStampSays',['text','rank'],bodyOf(main,'bool GoatExportStampSays(const string text,const string rank)'))
   .replace(/StringTrimLeft\((\w+)\)/g,'$1=$1.trimStart()').replace(/StringTrimRight\((\w+)\)/g,'$1=$1.trimEnd()').replace(/'\\n'/g,'10'),c);return c.GoatExportStampSays;})();
 const head='; SAMPLE: x\r\n'+'; EXPORT blind:0 ranked:full_span sr:mt5_stat\r\n';
 assert.equal(says(head+'; EXPORT format:2 rank:pf\r\nRisk=500\r\n','pf'),true,'stamped pf');
 assert.equal(says(head+'; EXPORT format:2 rank:arf_sr\r\n','pf'),false,'stamped arf_sr (a meta cut short)');
 assert.equal(says(head,'pf'),false,'no format line');
 assert.equal(says(head+'; EXPORT format:1 rank:pf\r\n','pf'),false,'another format');
 assert.equal(says(head+'; EXPORT format:2 rank:pf\r\n; EXPORT format:2 rank:pf\r\n','pf'),false,'two format lines');
 assert.equal(says(head+'; EXPORT format:2 rank:pf extra\r\n','pf'),false,'trailing text');
 // Where it sits: after the blind read, before the move and the store; set from the exporter's own setting.
 const store=bodyOf(main,'int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false,const int startAttempts=20)');
 const check=store.indexOf('if(g_GoatExporterRank==GOAT_EXPORT_RANK_PF)');
 assert.ok(check>store.indexOf('profit=rank_pl;')&&check<store.indexOf('if(profit>0)')&&check<store.indexOf('MoveExportsFromRoot('),'before the floor, the move and the store');
 assert.ok(check>store.indexOf('if(Init &&'),'the top-set verification run is not checked (it is never stored)');
 assert.match(store.slice(check),/^if\(g_GoatExporterRank==GOAT_EXPORT_RANK_PF\)\s*\{\s*string stamp_set="";\s*for\(int k=0;k<ArraySize\(exports\);k\+\+\) if\(StringFind\(exports\[k\],"\.set",0\)!=-1\) stamp_set=exports\[k\];\s*if\(stamp_set=="" \|\| !GoatExportStampSays\(GoatExportReadTextCommon\(stamp_set,0\),"pf"\)\)\s*\{LogOrPrint\([^;]*\); return -1;\}/,'no set or a wrong stamp: refused');
 const exporter=bodyOf(main,'bool StartExporter(bool reportMode)');
 const set=exporter.indexOf('g_GoatExporterRank=ExportRank;');
 assert.ok(set>exporter.indexOf('if(ExportRank<0)')&&set<exporter.indexOf('RunAndStoreSet('),'set from the setting before any export run');
 assert.match(main,/int    g_GoatExporterRank=GOAT_EXPORT_RANK_ARFxSR;/,'ARFxSR (no read-back) outside the exporter');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f8'}));
