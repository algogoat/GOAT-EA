// Mutation check for scripts/test_below_score_export.cjs (GOAT-EA BS42, goatai#1885): every guard of the
// FWD profit/DD export rule, the slot-2 gates and the research-only below_score export is removed or
// weakened in a temporary copy of the production sources, and the harness must fail. MQL-free; the
// repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['XmlProcessor.mqh','GOAT V1.49.mq5','Optimizer.mqh','GOAT V1.47.mq5','GOAT V1.48.mq5'];
const R=String.raw;
const X='XmlProcessor.mqh',M='GOAT V1.49.mq5';
// [label, file, from, to]
const mutations=[
  // Eligibility: FWD and SAMPLE profitable, trade floors, a measurable FWD profit/DD.
  ['a pass missing from the forward report ranks',X,R`if(!rows[i].forward_seen) return false;`,''],
  ['SAMPLE profit not required',X,R`if(!(rows[i].back_profit>0) || rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return false;`,R`if(rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return false;`],
  ['SAMPLE trade floor dropped',X,R`if(!(rows[i].back_profit>0) || rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return false;`,R`if(!(rows[i].back_profit>0)) return false;`],
  ['FWD profit not required',X,R`if(!(rows[i].forward_profit>0) || rows[i].forward_trades`,R`if(rows[i].forward_trades`],
  ['FWD trade floor dropped',X,R`|| rows[i].forward_trades<GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES) return false;`,R`) return false;`],
  ['FWD profit/DD need not be positive',X,R`if(!(rows[i].forward_RF>0)) return false;`,''],
  ['the score floor ignored (normal exports)',X,R`return minScore<0 || rows[i].Score>=minScore;`,R`return true;`],
  // Ranking: FWD profit/DD, never the match score, SAMPLE, BOOS or FOOS.
  ['ranked by the match score',X,R`if(rows[a].forward_RF!=rows[b].forward_RF) return rows[a].forward_RF>rows[b].forward_RF;`,R`if(rows[a].Score!=rows[b].Score) return rows[a].Score>rows[b].Score;`],
  ['ranked by SAMPLE profit/DD',X,R`if(rows[a].forward_RF!=rows[b].forward_RF) return rows[a].forward_RF>rows[b].forward_RF;`,R`if(rows[a].back_RF!=rows[b].back_RF) return rows[a].back_RF>rows[b].back_RF;`],
  ['FWD profit tie-break dropped',X,R`if(rows[a].forward_profit!=rows[b].forward_profit) return rows[a].forward_profit>rows[b].forward_profit;`,''],
  ['pass-number tie-break reversed',X,R`return rows[a].pass<rows[b].pass;`,R`return rows[a].pass>rows[b].pass;`],
  ['a no-qualifier member of several pairs picks',X,R`if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS && pairs==1)`,R`if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS)`],
  ['every outcome picks',X,R`if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS && pairs==1)`,R`if(pairs==1)`],
  // Parameter character (slot 2).
  ['a different mode is the same character',X,R`if(va!=vb) return names[k]+" "+va+"->"+vb;`,''],
  ['a size under twice the other differs',X,R`>=2.0*MathMin(MathAbs(x),MathAbs(y))`,R`>=1.2*MathMin(MathAbs(x),MathAbs(y))`],
  ['a stop switched on is the same character',X,R`bool distinct=((x==0)!=(y==0)) || (x*y<0);`,R`bool distinct=(x*y<0);`],
  ['pips vs ATR is the same character',X,R`bool distinct=((x==0)!=(y==0)) || (x*y<0);`,R`bool distinct=((x==0)!=(y==0));`],
  ['a non-key input sets the character',X,R`if(StringFind(GOAT_CHARACTER_SIZES,key)<0) continue;`,''],
  // SAMPLE daily-return correlation.
  ['too few days still correlate',X,R`if(n<GOAT_EXPORT_CORRELATION_MIN_DAYS) return EMPTY_VALUE;`,''],
  ['a flat curve correlates',X,R`if(!(vx>0) || !(vy>0)) return EMPTY_VALUE;`,''],
  ['days outside SAMPLE count',X,R`if(day<=0 || day<from || day>=to) continue;`,R`if(day<=0) continue;`],
  ['rows back in time accepted',X,R`if(n>0 && day<days[n-1]) return -1;`,''],
  ['a missing day breaks the alignment',X,R`double a=(hasA ? ca[i] : lastA), b=(hasB ? cb[j] : lastB);`,R`double a=(hasA ? ca[i] : 0), b=(hasB ? cb[j] : 0);`],
  // The slot rule.
  ['slot 2 ignores the character preference',M,R`if(diff!="") {second=ranked[k]; character=diff;}`,''],
  ['slot 2 correlation bar loosened',M,R`corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION));`,R`corr<=0.95));`],
  ['an unknown correlation proves a difference',M,R`(corr!=EMPTY_VALUE && corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION)`,R`(corr==EMPTY_VALUE || corr<=GOAT_EXPORT_SLOT2_MAX_CORRELATION)`],
  ['slot 2 quality bar dropped',M,R`bool quality=(kept[1].sr>=barSR && kept[1].arf>=barARF);`,R`bool quality=true;`],
  ['a looser run lowers the SR bar',M,R`double barSR=MathMax(minSR,GOAT_EXPORT_SLOT2_MIN_SR)`,R`double barSR=minSR`],
  ['a stricter run never raises the SR bar',M,R`double barSR=MathMax(minSR,GOAT_EXPORT_SLOT2_MIN_SR)`,R`double barSR=GOAT_EXPORT_SLOT2_MIN_SR`],
  ['a skipped slot 2 stays on disk',M,"   DeleteExports(files);\r\n   ArrayResize(kept,1);","   ArrayResize(kept,1);"],
  ['slot 2 kept whatever the gates',M,R`if(quality && different)`,R`if(true)`],
  ['slot 1 of below_score dropped on a loss',M,R`RunAndStoreSet(0,mode,reportMode,kept,false,3,keepLosingSlot1);`,R`RunAndStoreSet(0,mode,reportMode,kept,false,3);`],
  ['slot 2 kept losing too',M,R`RunAndStoreSet(1,mode,reportMode,kept,false,3);`,R`RunAndStoreSet(1,mode,reportMode,kept,false,3,true);`],
  ['a cancel still runs slot 2',M,"   if(!reportMode && GlobalVariableGet(GOAT_BATCH_CANCELLED_GV)!=0.0) return 1;\r\n   details+=\";slot2_pass=","   details+=\";slot2_pass="],
  // The research-only export.
  ['below_score units untagged',M,R`GoatExportSlots(ranked,",tier="+GOAT_XML_BELOW_SCORE,true,`,R`GoatExportSlots(ranked,"",true,`],
  ['below_score units moved to deploy',M,R`MoveKeptExports(kept,runPath+"\\"+GOAT_XML_BELOW_SCORE)`,R`MoveKeptExports(kept,GoatOptDeployPath(EA_Name,Server))`],
  ['a failed move leaves research units behind',M,"    DeleteExports(files);\r\n    details=\";below_score=failed\"+facts+slots;","    details=\";below_score=failed\"+facts+slots;"],
  ['no run folder still exports',M,R`if(runPath=="") {`,R`if(false) {`],
  ['the combine pick need not lead the ranking',M,R` || ranked[0]!=pick)`,R`)`],
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
  // The normal-export switch stays off, and off means the match-score export exactly as before.
  ['the ranking switch on by default',M,"//#define GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n","#define GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n"],
  ['the match-score export changed with the switch off',M,"#else\r\n    for(;i<MathMin(25,ArraySize(xmlData.RowsUnique));i++)","#else\r\n    for(;i<MathMin(24,ArraySize(xmlData.RowsUnique));i++)"],
  ['the switched path keeps the match-score trim',M,"#ifdef GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n     GoatSlotTrimLog(g_allExports,MinARF,MinSR);","#ifdef GOAT_EXPORT_RANK_FWD_PROFIT_DD\r\n     SortAndTrimExports(SetsToExport,MinARF,MinSR,g_allExports);"],
];
const harness='test_below_score_export.cjs';
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-below-score-mutation-'));
function run(dir){return spawnSync(process.execPath,[path.join(__dirname,harness)],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:120000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  const clean=run(base);if(clean.status!==0)throw new Error('unmutated sources fail '+harness+':\n'+clean.stdout+clean.stderr);
  mutations.forEach(([label,file,rawFrom,rawTo],n)=>{
    // Sources are CRLF; template literals are LF. Match and write CRLF either way.
    const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file),text=fs.readFileSync(target,'utf8');
    if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
    fs.writeFileSync(target,text.replace(from,()=>to));
    if(run(dir).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
