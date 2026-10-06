// Mutation check for scripts/test_below_score_export.cjs and test_slot2_foos_invariance.cjs (GOAT-EA BS42,
// goatai#1885): every guard of the FWD profit/DD export rule, the slot-2 gates and the research-only
// below_score export is removed or weakened in a temporary copy of the production sources, and one of the
// two harnesses must fail. MQL-free; the repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['XmlProcessor.mqh','GOAT V1.49.mq5','Optimizer.mqh','GOAT V1.47.mq5','GOAT V1.48.mq5'];
const R=String.raw;
const X='XmlProcessor.mqh',M='GOAT V1.49.mq5';
// [label, file, from, to]
const mutations=[
  // Eligibility: FWD and SAMPLE profitable, trade floors, a measurable FWD profit/DD.
  ['a pass missing from the forward report ranks',X,R`if(!rows[i].forward_seen) return 1;`,''],
  ['SAMPLE profit not required',X,R`if(!(rows[i].back_profit>0) || rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return 2;`,R`if(rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return 2;`],
  ['SAMPLE trade floor dropped',X,R`if(!(rows[i].back_profit>0) || rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return 2;`,R`if(!(rows[i].back_profit>0)) return 2;`],
  ['FWD profit not required',X,R`if(!(rows[i].forward_profit>0)) return 3;`,''],
  ['FWD trade floor dropped',X,R`if(rows[i].forward_trades<GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES) return 4;`,''],
  ['FWD profit/DD need not be positive',X,R`if(!(rows[i].forward_RF>0)) return 5;`,''],
  ['the score floor ignored (normal exports)',X,R`if(minScore>=0 && rows[i].Score<minScore) return 6;`,''],
  ['eligibility read inverted',X,R`return GoatXmlFwdIneligibility(rows,i,minScore)==0;`,R`return GoatXmlFwdIneligibility(rows,i,minScore)!=1;`],
  ['counts merge two reasons',X,R`      else if(why==3) fwdLoss++;`,R`      else if(why==3) fwdThin++;`],
  ['counts drop the at-score count',X,R`if(minScore>=0 && rows[i].Score>=minScore) scoreOk++;`,''],
  // Ranking: FWD profit / max(FWD DD, 0.25% x deposit); never the match score or SAMPLE.
  ['ranked by the match score',X,R`   if(ka!=kb) return ka>kb;`,R`   if(rows[a].Score!=rows[b].Score) return rows[a].Score>rows[b].Score;`],
  ['ranked on the SAMPLE drawdown',X,R`double drawdown=rows[i].forward_profit/rows[i].forward_RF;`,R`double drawdown=rows[i].back_profit/rows[i].back_RF;`],
  ['the drawdown floor dropped',X,R`return rows[i].forward_profit/MathMax(drawdown,GOAT_EXPORT_FWD_DD_FLOOR*deposit);`,R`return rows[i].forward_profit/drawdown;`],
  ['the drawdown floor ten times smaller',X,R`#define GOAT_EXPORT_FWD_DD_FLOOR 0.0025`,R`#define GOAT_EXPORT_FWD_DD_FLOOR 0.00025`],
  ['an unknown deposit still ranks',X,R`   if(!(deposit>0)) return 0;`,''],
  ['FWD profit tie-break dropped',X,R`if(rows[a].forward_profit!=rows[b].forward_profit) return rows[a].forward_profit>rows[b].forward_profit;`,''],
  ['pass-number tie-break reversed',X,R`return rows[a].pass<rows[b].pass;`,R`return rows[a].pass>rows[b].pass;`],
  // Parameter character (slot 2).
  ['a different mode is the same character',X,R`if(va!=vb) return names[k]+" "+va+"->"+vb;`,''],
  ['a size under twice the other differs',X,R`>=2.0*MathMin(MathAbs(x),MathAbs(y))`,R`>=1.2*MathMin(MathAbs(x),MathAbs(y))`],
  ['a stop switched on is the same character',X,R`bool distinct=((x==0)!=(y==0)) || (x*y<0);`,R`bool distinct=(x*y<0);`],
  ['pips vs ATR is the same character',X,R`bool distinct=((x==0)!=(y==0)) || (x*y<0);`,R`bool distinct=((x==0)!=(y==0));`],
  ['a non-key input sets the character',X,R`if(StringFind(GOAT_CHARACTER_SIZES,key)<0) continue;`,''],
  // SAMPLE series (item 5): daily BALANCE closes on commonly logged days.
  ['the EQUITY cell read',X,R`double balance=StringToDouble(cells[1]);`,R`double balance=StringToDouble(cells[2]);`],
  ['fewer than 20 common days still correlate',X,R`if(n<GOAT_EXPORT_CORRELATION_MIN_DAYS || changes<2) return EMPTY_VALUE;`,R`if(changes<2) return EMPTY_VALUE;`],
  ['a day one curve skipped counts as common',X,R`      if(da[i]<db[j]) {i++; continue;}`,R`      if(da[i]<db[j]) {lastA=ca[i]; i++; continue;}`],
  ['a flat curve correlates',X,R`if(!(vx>0) || !(vy>0)) return EMPTY_VALUE;`,''],
  ['days outside SAMPLE count',X,R`if(day<=0 || day<from || day>=to) continue;`,R`if(day<=0) continue;`],
  ['rows back in time accepted',X,R`if(n>0 && day<days[n-1]) return -1;`,''],
  // SAMPLE quality of slot 2 (item 1): its own CSV over [BOOS end, FOOS start).
  // Measured exactly as the controller's window_metrics (Claude-Mac 6026738987): EQUITY rows, intraday, from the deposit.
  ['window metrics read BALANCE in the window',X,R`      double value=StringToDouble(cells[2]);`,R`      double value=StringToDouble(cells[1]);`],
  ['window metrics open on BALANCE',X,R`      opening=StringToDouble(cells[2]);`,R`      opening=StringToDouble(cells[1]);`],
  ['window metrics open on the first row inside (the first day dropped)',X,R`      if(at>=from) break;`,R`      if(at>=from) {if(opening==initial) opening=StringToDouble(cells[2]); break;}`],
  ['window metrics ignore rows before the window',X,R`      if(at>=from) break;`,R`      break;`],
  ['window metrics drawdown from day closes only',X,R`      level=value; peak=MathMax(peak,value); drawdown=MathMax(drawdown,peak-value);`,R`      level=value; peak=MathMax(peak,value);`],
  ['window metrics returns over the level, not the deposit',X,R`returns[weekdays]=(value-previous)/initial;`,R`returns[weekdays]=(value-previous)/previous;`],
  ['window metrics population variance',X,R`   variance/=(weekdays-1);`,R`   variance/=weekdays;`],
  ['window metrics rows back in time accepted',X,R`      if(at<last) return false;
      last=at;
      if(at<from) continue;`,R`      last=at;
      if(at<from) continue;`],
  ['slot 2 measured without the tester deposit',M,R`GoatEquityWindowMetrics(csv2,sampleFrom,sampleTo,deposit,sample);`,R`GoatEquityWindowMetrics(csv2,sampleFrom,sampleTo,100000,sample);`],
  ['weekends in the Sharpe',X,R`if(dow!=0 && dow!=6)`,R`if(true)`],
  ['no Sharpe on a flat series accepted',X,R`   if(!(variance>0)) return false;`,R`   if(!(variance>0)) variance=1;`],
  ['ARF not per month',X,R`out[3]=recovery/(weekdays/21.7);`,R`out[3]=recovery;`],
  ['SAMPLE runs into FOOS',M,R`const datetime sampleFrom=xmlData.startD, sampleTo=xmlData.endD+24*60*60;`,R`const datetime sampleFrom=xmlData.startD, sampleTo=xmlData.endD+60*24*60*60;`],
  ['slot 2 judged on its full re-test',M,R`bool quality=(measured && sample[0]>0 && sample[2]>=barSR && sample[3]>=barARF);`,R`bool quality=(kept[1].prf>0 && kept[1].sr>=barSR && kept[1].arf>=barARF);`],
  ['slot 2 dropped on a losing full span',M,R`RunAndStoreSet(1,mode,reportMode,kept,false,3,true);`,R`RunAndStoreSet(1,mode,reportMode,kept,false,3);`],
  // (net > 0 is implied by ARF >= 0.2: ARF > 0 needs net / drawdown > 0, so that mutant is equivalent and not listed.)
  ['an unmeasurable SAMPLE reported as a quality miss',M,R`if(!measured) reason=`,R`if(false) reason=`],
  // The slot rule.
  ['slot 2 ignores the character preference',M,R`if(diff!="") {second=ranked[k]; character=diff;}`,''],
  ['slot 2 correlation bar loosened',M,R`corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION));`,R`corr<=0.95));`],
  ['an unknown correlation proves a difference',M,R`(corr!=EMPTY_VALUE && corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION)`,R`(corr==EMPTY_VALUE || corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION)`],
  ['slot 2 quality bar dropped',M,R`bool quality=(measured && sample[0]>0 && sample[2]>=barSR && sample[3]>=barARF);`,R`bool quality=true;`],
  ['a looser run lowers the SR bar',M,R`double barSR=MathMax(minSR,GOAT_EXPORT_SLOT2_MIN_SR)`,R`double barSR=minSR`],
  ['a stricter run never raises the SR bar',M,R`double barSR=MathMax(minSR,GOAT_EXPORT_SLOT2_MIN_SR)`,R`double barSR=GOAT_EXPORT_SLOT2_MIN_SR`],
  ['a stricter run never raises the ARF bar',M,R`barARF=MathMax(minARF,GOAT_EXPORT_SLOT2_MIN_ARF);`,R`barARF=GOAT_EXPORT_SLOT2_MIN_ARF;`],
  ['a skipped slot 2 stays on disk',M,"   DeleteExports(files);\r\n   ArrayResize(kept,1);","   ArrayResize(kept,1);"],
  ['slot 2 kept whatever the gates',M,R`if(quality && different)`,R`if(true)`],
  ['slot 1 of below_score dropped on a loss',M,R`RunAndStoreSet(0,mode,reportMode,kept,false,3,keepLosingSlot1);`,R`RunAndStoreSet(0,mode,reportMode,kept,false,3);`],
  ['a cancel still runs slot 2',M,"   if(!reportMode && GlobalVariableGet(GOAT_BATCH_CANCELLED_GV)!=0.0) return 1;\r\n   details+=\";slot2_pass=","   details+=\";slot2_pass="],
  // The research-only export.
  ['several pairs still pick (item 4)',M,R`   if(xmlData.belowScorePairs!=1)`,R`   if(false)`],
  ['the combiner records one pair always',X,R`   xmlData.belowScorePairs=pairs;`,R`   xmlData.belowScorePairs=1;`],
  ['below_score ignores the tester deposit',M,R`GoatXmlFwdRank(xmlData.Rows,-1.0,deposit,ranked)`,R`GoatXmlFwdRank(xmlData.Rows,-1.0,1.0,ranked)`],
  ['below_score units untagged',M,R`GoatExportSlots(ranked,",tier="+GOAT_XML_BELOW_SCORE,true,`,R`GoatExportSlots(ranked,"",true,`],
  ['below_score units moved to deploy',M,R`MoveKeptExports(kept,runPath+"\\"+GOAT_XML_BELOW_SCORE)`,R`MoveKeptExports(kept,GoatOptDeployPath(EA_Name,Server))`],
  ['a failed move leaves research units behind',M,"    DeleteExports(files);\r\n    details=\";below_score=failed\"+facts+slots;","    details=\";below_score=failed\"+facts+slots;"],
  ['no run folder still exports',M,R`if(runPath=="") {`,R`if(false) {`],
  ['below_score on the last-tick clock',M,R`GoatEvidenceEndToDate(boundarySetting,TimeTradeServer(),`,R`GoatEvidenceEndToDate(boundarySetting,TimeCurrent(),`],
  ['below_score window end not passed',M,R`const datetime windowEnd=xmlData.endD;`,R`const datetime windowEnd=0;`],
  ['below_score ignores EvidenceEnd',M,R`strT.toDate=(boundaryToDate!="" ? boundaryToDate : GetLastFridayDate());`,R`strT.toDate=GetLastFridayDate();`],
  ['below_score loses the legacy end',M,R`strT.toDate=(boundaryToDate!="" ? boundaryToDate : GetLastFridayDate());`,R`strT.toDate=boundaryToDate;`],
  ['a refused evidence end still exports',M,R`if(boundaryToDate=="") {LogOrPrint(reportMode,"❌ "+boundaryError+". No below_score export was run.",Key,EA_Name,Server); return -1;}`,''],
  ['below_score counted as a final export',M,R`xmlData.bestCombinedScore,0,xmlData.OutcomeDetails()+belowScore`,R`xmlData.bestCombinedScore,1,xmlData.OutcomeDetails()+belowScore`],
  ['below_score facts not recorded',M,R`xmlData.OutcomeDetails()+belowScore)`,R`xmlData.OutcomeDetails())`],
  ['a cancel still writes the row',M,"             if(GlobalVariableGet(GOAT_BATCH_CANCELLED_GV)!=0.0) return;\r\n#endif\r\n             GoatOptAppendItemStats","#endif\r\n             GoatOptAppendItemStats"],
  ['the tier never reaches the SET header',M,R`if(g_goatBelowScoreExport) {`,R`if(false) {`],
  ['the tier key reads as the mode',M,R`if(names[i]=="tier" && values[i]==GOAT_XML_BELOW_SCORE)`,R`if(names[i]=="mode_tier" && values[i]==GOAT_XML_BELOW_SCORE)`],
  ['switch off: NO_FWD_ELIGIBLE_PASS not logged',M,R`LogOrPrint(reportMode,"NO_FWD_ELIGIBLE_PASS "+counts`,R`Print("NO_FWD_ELIGIBLE_PASS "+counts`],
  ['switch off: no counts in the row',M,R`details=";below_score=none;no_fwd_eligible_pass=1;"+counts+rule;`,R`details=";below_score=none"+rule;`],
  // Switch ON: the gap closed; never export nothing silently; the deposit floor applies.
  ['switch on: no fall-through',M,R`      StartBelowScoreExporter(reportMode,belowScore);`,''],
  ['switch on: fall-through not flagged',M,R`      g_goatFwdFallthrough=true;`,''],
  ['switch on: outcome left changed',M,R`      xmlData.outcome=outcomeWas;`,''],
  ['switch on: fall-through row written as Error',M,R`Strat,"NoFwdEligibleRows",`,R`Strat,"Error",`],
  ['switch on: no score-qualifying count',M,R`+";score_qualifying_rows="+(string)scoreRows+belowScore;`,R`+belowScore;`],
  ['switch on: an unknown deposit falls through',M,R`if(!(deposit>0)) {errors++;`,R`if(false) {errors++;`],
  ['switch resolve-by date dropped',M,R`// RESOLVE BY 2026-10-13, NOT A DORMANT FLAG`,R`// Resolve later`],
  ['the ranking switch on by default',M,"//#define GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n","#define GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n"],
  ['the match-score export changed with the switch off',M,"#else\r\n    for(;i<MathMin(25,ArraySize(xmlData.RowsUnique));i++)","#else\r\n    for(;i<MathMin(24,ArraySize(xmlData.RowsUnique));i++)"],
  ['the switched path keeps the match-score trim',M,"#ifdef GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n     GoatSlotTrimLog(g_allExports,MinARF,MinSR);","#ifdef GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n     SortAndTrimExports(SetsToExport,MinARF,MinSR,g_allExports);"],
];
const harnesses=['test_below_score_export.cjs','test_slot2_foos_invariance.cjs'];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-below-score-mutation-'));
function run(dir,harness){return spawnSync(process.execPath,[path.join(__dirname,harness)],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:120000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  for(const harness of harnesses){const clean=run(base,harness);if(clean.status!==0)throw new Error('unmutated sources fail '+harness+':\n'+clean.stdout+clean.stderr);}
  mutations.forEach(([label,file,rawFrom,rawTo],n)=>{
    // Sources are CRLF; template literals are LF. Match and write CRLF either way.
    const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file),text=fs.readFileSync(target,'utf8');
    if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
    fs.writeFileSync(target,text.replace(from,()=>to));
    if(harnesses.every(h=>run(dir,h).status===0))survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
