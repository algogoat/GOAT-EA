// Mutation check for scripts/test_research_outcome.cjs and test_connection_code.cjs: every
// guard below is removed or weakened in a temporary copy of the production sources and the
// harness must fail. MQL-free; the repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['XmlProcessor.mqh','GOAT V1.49.mq5','Optimizer.mqh','GOATEADeviceActivation.mqh'];
const R=String.raw;
// [label, file, from, to, harness]
const outcome='test_research_outcome.cjs',code='test_connection_code.cjs';
const mutations=[
  ['unread back report classified','XmlProcessor.mqh',R`if(!back_read || !title_matches) return "";`,R`if(!title_matches) return "";`,outcome],
  ['mismatched file name classified','XmlProcessor.mqh',R`if(!back_read || !title_matches) return "";`,R`if(!back_read) return "";`,outcome],
  // Anchors that the nothing-qualified guard repeats start one line earlier to stay unique.
  ['unknown window classified','XmlProcessor.mqh',R`if(!back_read || !title_matches) return "";
   if(window_start<=0 || forward_date<=window_start || window_end<=forward_date) return "";`,R`if(!back_read || !title_matches) return "";`,outcome],
  ['forward date outside the window accepted','XmlProcessor.mqh',R`if(!back_read || !title_matches) return "";
   if(window_start<=0 || forward_date<=window_start || window_end<=forward_date) return "";`,R`if(!back_read || !title_matches) return "";
   if(window_start<=0) return "";`,outcome],
  ['kept rows classified','XmlProcessor.mqh',R`if(passes<=0 || kept!=0) return "";`,R`if(passes<=0) return "";`,outcome],
  ['mixed pairs classified','XmlProcessor.mqh',R`if(ret && noEdgePairs==pairs) xmlData.outcome`,R`if(ret) xmlData.outcome`,outcome],
  ['another failure masked','XmlProcessor.mqh',R`if(ret && noEdgePairs==pairs) xmlData.outcome`,R`if(noEdgePairs==pairs) xmlData.outcome`,outcome],
  ['no-edge reported as success','XmlProcessor.mqh',"xmlData.outcome=GOAT_XML_NO_QUALIFYING_ROWS;\r\n      ret=false;","xmlData.outcome=GOAT_XML_NO_QUALIFYING_ROWS;\r\n",outcome],
  ['no-edge pair still merged and written','XmlProcessor.mqh',"xmlData.pairOutcome=GOAT_XML_NO_PROFITABLE_PASSES;\r\n          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);\r\n          continue;","xmlData.pairOutcome=GOAT_XML_NO_PROFITABLE_PASSES;\r\n          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);\r\n",outcome],
  // No qualifying rows (Banker g6-r1b): kept passes merged with the forward report, none scored 60+.
  ['nothing-qualified pair still written','XmlProcessor.mqh',"xmlData.pairOutcome=GOAT_XML_NO_QUALIFYING_ROWS;\r\n          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);\r\n          continue;","xmlData.pairOutcome=GOAT_XML_NO_QUALIFYING_ROWS;\r\n          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);\r\n",outcome],
  ['mixed outcomes classified as nothing qualified','XmlProcessor.mqh',R`if(ret && noQualifierPairs==pairs) xmlData.outcome`,R`if(ret) xmlData.outcome`,outcome],
  ['nothing qualified masks another failure','XmlProcessor.mqh',R`if(ret && noQualifierPairs==pairs) xmlData.outcome`,R`if(noQualifierPairs==pairs) xmlData.outcome`,outcome],
  ['failed forward merge classified','XmlProcessor.mqh',R` || !forward_read) return "";`,R`) return "";`,outcome],
  ['nothing-qualified window not checked','XmlProcessor.mqh',R`!forward_read) return "";
   if(window_start<=0 || forward_date<=window_start || window_end<=forward_date) return "";`,R`!forward_read) return "";`,outcome],
  ['nothing kept classified as nothing qualified','XmlProcessor.mqh',R`if(passes<=0 || kept<=0 || kept>profitable || profitable>passes) return "";`,R`if(passes<=0 || kept>profitable || profitable>passes) return "";`,outcome],
  ['kept count unbounded','XmlProcessor.mqh',R`if(passes<=0 || kept<=0 || kept>profitable || profitable>passes) return "";`,R`if(passes<=0 || kept<=0) return "";`,outcome],
  ['nothing-qualified partial back report','XmlProcessor.mqh',R`profitable>passes) return "";
   if(!report_closed || malformed!=0) return "";`,R`profitable>passes) return "";`,outcome],
  ['kept passes need not have traded','XmlProcessor.mqh',R`if(traded<kept || traded>passes) return "";`,'',outcome],
  ['nothing-qualified forward rows unbounded','XmlProcessor.mqh',R`if(traded<kept || traded>passes) return "";
   if(forward_rows<=0 || forward_rows>passes) return "";`,R`if(traded<kept || traded>passes) return "";`,outcome],
  ['kept pass missing from forward accepted','XmlProcessor.mqh',R`if(forward_matched!=kept || forward_mismatches!=0 || forward_malformed!=0) return "";`,R`if(forward_mismatches!=0 || forward_malformed!=0) return "";`,outcome],
  ['back/forward disagreement accepted','XmlProcessor.mqh',R`if(forward_matched!=kept || forward_mismatches!=0 || forward_malformed!=0) return "";`,R`if(forward_matched!=kept || forward_malformed!=0) return "";`,outcome],
  ['unreadable forward rows accepted','XmlProcessor.mqh',R`if(forward_matched!=kept || forward_mismatches!=0 || forward_malformed!=0) return "";`,R`if(forward_matched!=kept || forward_mismatches!=0) return "";`,outcome],
  ['qualifying score classified','XmlProcessor.mqh',R`if(min_score<=0 || best_score<0 || !(best_score<min_score)) return "";`,R`if(min_score<=0 || best_score<0) return "";`,outcome],
  ['best combined score never recorded','XmlProcessor.mqh',R`bestCombinedScore=(ArraySize(Rows)>0 ? Rows[0].Score : 0.0);`,'',outcome],
  ['back-result mismatch not counted','XmlProcessor.mqh',R`forwardMismatches++;
               LogOrPrint(reportMode,"❌ Back result mismatch`,R`LogOrPrint(reportMode,"❌ Back result mismatch`,outcome],
  ['inputs mismatch not counted','XmlProcessor.mqh',R`forwardMismatches++;
               LogOrPrint(reportMode,"❌ Inputs mismatch`,R`LogOrPrint(reportMode,"❌ Inputs mismatch`,outcome],
  ['unreadable forward cells not counted','XmlProcessor.mqh',R`if(!IsNumberCell(profitCell) || !IsNumberCell(tradesCell)) forwardMalformed++;`,'',outcome],
  ['forward row loops forever at EOF','XmlProcessor.mqh',R`if(FileIsEnding(hForward)) {forwardMalformed++; break;}   // truncated report: never loop at EOF`,'',outcome],
  ['nothing qualified written as Error','GOAT V1.49.mq5',R`Strat,"NoQualifyingRows",`,R`Strat,"Error",`,outcome],
  ['real combine errors written as nothing qualified','GOAT V1.49.mq5',R`else if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS)`,R`else if(true)`,outcome],
  ['summary ignores nothing qualified','Optimizer.mqh',R` && fields[3]!="NoQualifyingRows"`,'',outcome],
  ['passes counted after the profit filter','XmlProcessor.mqh',"            passesSeen++;\r\n","",outcome],
  ['best profit only from kept rows','XmlProcessor.mqh',R`if(passesSeen==0 || Rows[i].back_profit>bestProfit) bestProfit=Rows[i].back_profit;`,'',outcome],
  ['log back to Rows Saved=0/0','XmlProcessor.mqh',R`"/"+(string)passesSeen`,R`"/"+(string)i`,outcome],
  ['report-mode alert says check logs','XmlProcessor.mqh',R`if(reportMode) Alert(xmlData.OutcomeSentence());`,'',outcome],
  ['outcome written as Error','GOAT V1.49.mq5',R`Strat,"NoProfitablePasses",`,R`Strat,"Error",`,outcome],
  ['real combine errors written as outcomes','GOAT V1.49.mq5',R`if(xmlData.outcome==GOAT_XML_NO_PROFITABLE_PASSES)`,R`if(true)`,outcome],
  ['queue status cleared for no-edge','GOAT V1.49.mq5',R`GoatOptAppendItemStats(EA_Name,Server,Symbol(),Strat,"NoProfitablePasses",`,R`error=false; GoatOptAppendItemStats(EA_Name,Server,Symbol(),Strat,"NoProfitablePasses",`,outcome],
  ['summary counts other statuses','Optimizer.mqh',R`fields[3]!="NoProfitablePasses"`,R`fields[3]==""`,outcome],
  ['summary counts repeated items','Optimizer.mqh',R`if(StringFind(seen,"\n"+itemKey)>=0) continue;`,'',outcome],
  ['summary not bounded by errors','Optimizer.mqh',R`noEdge=(int)MathMin(noEdge,stats.errors);`,'',outcome],
  // Review HIGH/MEDIUM: proof of trading and a whole report.
  ['zero-trade report classified','XmlProcessor.mqh',R`if(traded<=0 || traded>passes) return "";`,R`if(traded>passes) return "";`,outcome],
  ['traded count unbounded','XmlProcessor.mqh',R`if(traded<=0 || traded>passes) return "";`,R`if(traded<=0) return "";`,outcome],
  ['unparsed rows classified','XmlProcessor.mqh',R`if(passes<=0 || kept!=0) return "";
   if(!report_closed || malformed!=0) return "";`,R`if(passes<=0 || kept!=0) return "";
   if(!report_closed) return "";`,outcome],
  ['partial report classified','XmlProcessor.mqh',R`if(passes<=0 || kept!=0) return "";
   if(!report_closed || malformed!=0) return "";`,R`if(passes<=0 || kept!=0) return "";
   if(malformed!=0) return "";`,outcome],
  ['forward report not required','XmlProcessor.mqh',R`if(traded<=0 || traded>passes) return "";
   if(forward_rows<=0 || forward_rows>passes) return "";`,R`if(traded<=0 || traded>passes) return "";`,outcome],
  ['forward rows unbounded','XmlProcessor.mqh',R`if(traded<=0 || traded>passes) return "";
   if(forward_rows<=0 || forward_rows>passes) return "";`,R`if(traded<=0 || traded>passes) return "";
   if(forward_rows<=0) return "";`,outcome],
  ['losing passes counted as traded','XmlProcessor.mqh',R`else if(ExtractDataAsDouble(line)>0) tradedSeen++;`,R`else tradedSeen++;`,outcome],
  ['losing trades cell not checked','XmlProcessor.mqh',R`if(line=="</Row>" || !IsNumberCell(line)) malformedSeen++;`,R`if(false) malformedSeen++;`,outcome],
  ['unreadable profit not counted','XmlProcessor.mqh',R`if(!IsNumberCell(passCell) || !IsNumberCell(profitCell)) malformedSeen++;`,'',outcome],
  ['table closure assumed','XmlProcessor.mqh',R`reportClosed=(StringFind(rowStart,"</Table>")>=0);`,R`reportClosed=true;`,outcome],
  ['unclosed forward report accepted','XmlProcessor.mqh',R`return (table_closed && rows>0) ? rows-1 : -1;`,R`return rows>0 ? rows-1 : -1;`,outcome],
  ['skipped row loops forever at EOF','XmlProcessor.mqh',R`while(line!="</Row>" && !FileIsEnding(hBack))line=FileReadString(hBack);
               i--; continue;`,R`while(line!="</Row>")line=FileReadString(hBack);
               i--; continue;`,outcome],
  ['partial-trades sentence says none was profitable','XmlProcessor.mqh',R`(profitableSeen>0 ? (string)profitableSeen+" profitable on fewer, " : "")`,R`""`,outcome],
  ['summary counts items the queue does not mark Error','Optimizer.mqh',R`if(StringFind(errorAliases,"\n"+fields[2]+"\n")<0) continue;`,'',outcome],
  ['partial back report still combines','XmlProcessor.mqh',R`if(backRead && (!xmlData.reportClosed || xmlData.malformedSeen>0))`,R`if(false)`,outcome],
  ['unreadable rows still combine','XmlProcessor.mqh',R`(!xmlData.reportClosed || xmlData.malformedSeen>0))`,R`(!xmlData.reportClosed))`,outcome],
  ['code back in the query string','GOATEADeviceActivation.mqh',R`verification_url+"#ea-connect="+user_code`,R`verification_url+"&code="+user_code`,code],
  ['pairing wording returns','GOATEADeviceActivation.mqh',R`"Connection code: "+user_code`,R`"Enter pairing code: "+user_code`,code],
];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-outcome-mutation-'));
// A mutation that hangs (an EOF loop) is killed by the timeout and counts as caught.
function run(dir,harness){return spawnSync(process.execPath,[path.join(__dirname,harness)],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:60000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  for(const harness of [outcome,code]){const clean=run(base,harness);if(clean.status!==0)throw new Error('unmutated sources fail '+harness+':\n'+clean.stdout+clean.stderr);}
  mutations.forEach(([label,file,rawFrom,rawTo,harness],n)=>{
    // Sources are CRLF; template literals are LF. Match and write CRLF either way.
    const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file),text=fs.readFileSync(target,'utf8');
    if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
    fs.writeFileSync(target,text.replace(from,()=>to));
    if(run(dir,harness).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
