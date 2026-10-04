// Mutation check for scripts/test_bias_reader_parity.cjs: every part of the recorded live gate
// (BR41) is removed or weakened in a temporary copy of the production sources and the harness must
// fail. MQL-free; the repository files are never modified. GOAT_MUTATION_TMP picks the temp root.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['GOAT V1.47.mq5','GOAT V1.48.mq5','GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','NewsBiasFilter.mqh','GOATAIWireV2.mqh'];
const R=String.raw;
const FLAG='#define GOAT_RECORDED_BIAS_LIVE_GATE_V149\n';
const TESTER_PAUSE=R`     if(!control_tower_v2 && (MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)))
        pause_v2_additions=(bias_filter_active && Mode_Bias_Trades==Bias_SeqTrade);
`;
// [label, file, [[from, to], ...]]
const mutations=[
  ['tester reader hands over every score again','NewsBiasFilter.mqh',[[R`   if(is_tester) return GOATRecordedBiasLiveScore(latest_score);`,'']]],
  ['gate also applied to the live legacy reader','NewsBiasFilter.mqh',[[R`   if(is_tester) return GOATRecordedBiasLiveScore(latest_score);`,R`   return GOATRecordedBiasLiveScore(latest_score);`]]],
  ['V1.49 no longer enables the gate','GOAT V1.49.mq5',[[FLAG,'']]],
  ['gate enabled only after the headers are included','GOAT V1.49.mq5',[[FLAG,''],['#include "GOATStudioUI.mqh"\n','#include "GOATStudioUI.mqh"\n'+FLAG]]],
  ['V1.48 release history also gated','GOAT V1.48.mq5',[['#define   GOAT_AI_SIGNAL_FILTER_V147 1\n','#define   GOAT_AI_SIGNAL_FILTER_V147 1\n'+FLAG]]],
  ['out-of-range score not dark','GOATAIWireV2.mqh',[[R`   if(recorded_score<-100 || recorded_score>100) return -999;`,'']]],
  ['neutral treated as a direction','GOATAIWireV2.mqh',[[R`(recorded_score<0 ? "BEARISH" : "NEUTRAL")`,R`(recorded_score<0 ? "BEARISH" : "BULLISH")`]]],
  ['recorded state not verified','GOATAIWireV2.mqh',[["   state.verified=true;\n   state.directive_available=true;\n","   state.directive_available=true;\n"]]],
  ['probability scaled wrongly','GOATAIWireV2.mqh',[[R`state.decision_probability=MathAbs(recorded_score)/100.0;`,R`state.decision_probability=MathAbs(recorded_score)/101.0;`]]],
  ['threshold not clamped like live','GOATAIWireV2.mqh',[[R`GOATFinalizeWireV2Actionability(state,MathMax(0.0,MathMin(100.0,(double)Bias_threshold))/100.0);`,R`GOATFinalizeWireV2Actionability(state,(double)Bias_threshold/100.0);`]]],
  ['below-threshold score passed through','GOATAIWireV2.mqh',[[R`return(state.actionable ? state.signed_probability_percent : -999);`,R`return(state.directive_available ? state.signed_probability_percent : -999);`]]],
  ['gated tester keeps the spacing staleness heuristic','NewsBiasFilter.mqh',[
    ["#ifdef GOAT_RECORDED_BIAS_LIVE_GATE_V149\n   if(!is_tester) // the gated tester path below uses no spacing average\n#endif\n",''],
    [R`   if(is_tester) return GOATRecordedBiasLiveScore(latest_score);
#endif
   //--- staleness check: if selected bias is too old relative to typical cadence, treat as neutral
   if(avg > 0 && (now - latest_time) > (datetime)(2 * avg)) return -999;
`,R`#endif
   if(avg > 0 && (now - latest_time) > (datetime)(2 * avg)) return -999;
#ifdef GOAT_RECORDED_BIAS_LIVE_GATE_V149
   if(is_tester) return GOATRecordedBiasLiveScore(latest_score);
#endif
`]]],
  ['live legacy loses its spacing average','NewsBiasFilter.mqh',[[R`   if(!is_tester) // the gated tester path below uses no spacing average`,R`   if(false)`]]],
  ['tester dark point does not pause additions','GOAT V1.49.mq5',[[TESTER_PAUSE,'']]],
  ['tester pauses additions under Bias_Seq too','GOAT V1.49.mq5',[[R`pause_v2_additions=(bias_filter_active && Mode_Bias_Trades==Bias_SeqTrade);`,R`pause_v2_additions=bias_filter_active;`]]],
  ['live legacy dark point pauses additions','GOAT V1.49.mq5',[[R`if(!control_tower_v2 && (MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)))`,R`if(!control_tower_v2)`]]],
];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-bias-parity-mutation-'));
function run(dir){return spawnSync(process.execPath,[path.join(__dirname,'test_bias_reader_parity.cjs')],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:120000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  const clean=run(base);if(clean.status!==0)throw new Error('unmutated sources fail:\n'+clean.stdout+clean.stderr);
  mutations.forEach(([label,file,pairs],n)=>{
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file);let text=fs.readFileSync(target,'utf8');
    for(const [rawFrom,rawTo] of pairs){
      // Sources are CRLF; template literals are LF. Match and write CRLF either way.
      const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
      if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
      text=text.replace(from,()=>to);
    }
    fs.writeFileSync(target,text);
    if(run(dir).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
