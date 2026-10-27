// Replay the production report reader and research-outcome guards over COPIES of real
// MT5 optimization reports (never a terminal folder). Usage:
//   node scripts/replay_research_outcome.cjs <copied run folder> [alias ...]
// The folder holds reports\<alias>\<symbol>\*.xml (back + forward) and optionally
// queue.GOAT. Prints one JSON line per member and a totals line. Read-only.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
process.env.GOAT_OUTCOME_HARNESS_ONLY='1';
const {makeContext}=require('./test_research_outcome.cjs');
const run=process.argv[2];
if(!run||!fs.existsSync(path.join(run,'reports'))){console.error('usage: replay_research_outcome.cjs <copied run folder> [alias ...]');process.exit(2);}
const lower=run.toLowerCase();
if(lower.includes('\\metaquotes\\terminal\\')||lower.includes('/metaquotes/terminal/')){console.error('refusing to read a terminal folder: copy the reports first');process.exit(2);}
const only=new Set(process.argv.slice(3));
const readText=p=>{if(!fs.existsSync(p))return '';const b=fs.readFileSync(p);return b[0]===0xff&&b[1]===0xfe?b.toString('utf16le').slice(1):b.toString('utf8').replace(/^﻿/,'');};
const queueText=readText(path.join(run,'queue.GOAT'));
const queueStatus=alias=>{const m=queueText.match(new RegExp(';(\\w+?)_[^;\\x1f]*:'+alias+';'));return m?m[1]:null;};
const rows=[];
for(const alias of fs.readdirSync(path.join(run,'reports')).sort()){
  if(only.size&&!only.has(alias))continue;
  for(const symbol of fs.readdirSync(path.join(run,'reports',alias))){
    const dir=path.join(run,'reports',alias,symbol);
    const names=fs.readdirSync(dir).filter(n=>n.endsWith('.xml')&&!/_CombinedRows_|_UniqueRows_/.test(n));
    if(!names.length)continue;
    const files={},list=[];
    for(const n of names){const key='GOAT\\'+alias+'\\'+n;files[key]=fs.readFileSync(path.join(dir,n),'utf8').replace(/^\uFEFF/,'').split(/\r?\n/);list.push(key);}
    const c=makeContext(files,{realForward:true});
    // The writers export rows scoring at least 60; count exactly what they would write.
    c.WriteTopToXml=()=>{c.calls.push('top');return c.Rows.filter(r=>r.Score>=60).length;};
    c.WriteUniqueRowsToXml=()=>{c.calls.push('unique');return c.Rows.some(r=>r.Score>=60);};
    const ret=vm.runInContext('ReportAnalyzerCombiner(__names,false,"GOAT","GOAT V1.49","replay")',Object.assign(c,{__names:list}));
    const details=c.outcome?c.OutcomeDetails():'';
    rows.push({alias,symbol,queue:queueStatus(alias),combined:ret,outcome:c.outcome||(ret?'combined':'error'),
      passes:c.passesSeen,profitable:c.profitableSeen,kept:c.Rows.length,malformed:c.malformedSeen,complete:c.reportClosed,
      forward_rows:c.forwardRows,forward_matched:c.forwardMatched,forward_mismatches:c.forwardMismatches,forward_malformed:c.forwardMalformed,
      best_combined_score:Number(c.bestCombinedScore.toFixed(1)),errors:c.logs.filter(l=>/❌/.test(l)).slice(0,3),details,
      sentence:c.outcome?c.OutcomeSentence():''});
  }
}
for(const r of rows)console.log(JSON.stringify(r));
const totals={};for(const r of rows)totals[r.outcome]=(totals[r.outcome]||0)+1;
console.log(JSON.stringify({members:rows.length,totals}));
