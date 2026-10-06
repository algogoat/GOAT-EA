// No-profitable-passes research outcome (GOAT_RESEARCH_OUTCOME_V149). Runs the production
// XmlProcessor back-report reader, the classification guard and the combiner, the V1.49
// OnTesterDeinit branch and the batch summary in a JS VM over simulated MT5 XML reports.
// MQL-free: no MetaEditor, MT5 or network. GOAT_EA_ROOT may point at another source tree
// (test_research_outcome_mutations.cjs runs every guard mutation through this file).
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const xmlSource=read('XmlProcessor.mqh'),mainSource=read('GOAT V1.49.mq5'),optimizerSource=read('Optimizer.mqh');
// GOAT_OUTCOME_EXTRA_DEFINES (comma separated) adds flags, e.g. for test_below_score_export.cjs.
const DEFINED=new Set(['GOAT_RESEARCH_OUTCOME_V149','GOAT_MONITOR_ONBOARDING_V149','GOAT_CONTROL_FEEDBACK_V149',
  ...(process.env.GOAT_OUTCOME_EXTRA_DEFINES||'').split(',').filter(Boolean)]);

// ---- MQL -> JS for the exact production functions under test.
function preprocess(text,macros){
  const out=[],stack=[];let active=true;
  for(const line of text.split('\n')){
    const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
    if(m){
      if(m[1]==='ifdef'||m[1]==='ifndef'){const on=DEFINED.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
      else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
      else active=stack.pop()[0];
      continue;
    }
    const d=line.match(/^\s*#define\s+(\w+)\s+(.+?)\s*$/);
    if(d){if(active)macros[d[1]]=d[2];continue;}
    if(/^\s*#/.test(line))continue;
    if(active)out.push(line);
  }
  return out.join('\n');
}
function stripComments(text){
  let out='',i=0,quote='';
  while(i<text.length){
    const c=text[i];
    if(quote){out+=c;if(c==='\\'){out+=text[i+1];i+=2;continue;}if(c===quote)quote='';i++;continue;}
    if(c==='"'||c==="'"){quote=c;out+=c;i++;continue;}
    if(c==='/'&&text[i+1]==='/'){while(i<text.length&&text[i]!=='\n')i++;continue;}
    if(c==='/'&&text[i+1]==='*'){const end=text.indexOf('*/',i+2);i=end<0?text.length:end+2;continue;}
    out+=c;i++;
  }
  return out;
}
function block(text,from){
  let brace=text.indexOf('{',from),depth=1,end=brace+1,quote='';
  while(depth){
    assert.ok(end<text.length,'unbalanced block');
    const ch=text[end];
    if(quote){if(ch==='\\')end++;else if(ch===quote)quote='';}
    else if(ch==='"'||ch==="'")quote=ch;
    else if(ch==='{')depth++;
    else if(ch==='}')depth--;
    end++;
  }
  return [brace,end];
}
const TYPES='string|bool|int|uint|long|ulong|ushort|datetime|double|SBatchProgressStats';
function convert(body,macros){
  for(const [name,value] of Object.entries(macros))body=body.replace(new RegExp('\\b'+name+'\\b','g'),value);
  // MQL char literals are ushort codes ('\t', ':', ...); keep that type in JS.
  body=body.replace(/'(\\.|[^'\\])'/g,(_,ch)=>String(({'\\n':10,'\\t':9,'\\\\':92,"\\'":39}[ch])??ch.charCodeAt(0)));
  body=body.replace(/\((?:string|int|long|double|datetime|ulong|ushort)\)/g,'');
  body=body.replace(/\bSBatchProgressStats\s+(\w+);/g,'let $1={};');
  body=body.replace(new RegExp('(^|[;{(]|\\n)(\\s*)(?:const\\s+)?(?:'+TYPES+')\\s+(?=[A-Za-z_])','g'),'$1$2let ');
  body=body.replace(/let ([^;]*);/g,(m,decl)=>'let '+decl.replace(/(\w+)\[\]/g,'$1=[]')+';');
  body=body.replace(/let (\w+);/g,'let $1="";');
  body=body.replace(/StringTrimLeft\((\w+)\);/g,'$1=$1.replace(/^\\s+/,"");').replace(/StringTrimRight\((\w+)\);/g,'$1=$1.replace(/\\s+$/,"");');
  return body;
}
function extract(text,pattern,name,macros){
  const at=text.search(pattern);
  assert.ok(at>=0,'missing production function '+name);
  const [brace,end]=block(text,at);
  const header=text.slice(at,brace),params=header.slice(header.indexOf('(')+1,header.lastIndexOf(')'));
  const names=!params.trim()||params.trim()==='void'?[]:params.split(',').map(p=>p.replace(/=.*/,'').replace(/\[\]/g,'').trim().split(/[\s&]+/).pop());
  return 'function '+name+'('+names.join(',')+')'+convert(text.slice(brace,end),macros);
}
const macros={};
const X=stripComments(preprocess(xmlSource,macros));
const BELOW_SCORE_FUNCTIONS=['GoatXmlFwdEligible','GoatXmlFwdBetter','GoatXmlFwdRank','GoatXmlCharacterDifference','GoatEquityDailyCloses','GoatDailyReturnCorrelation'];
const method=name=>extract(X,new RegExp('^\\s*(?:bool|string|int|void|double)\\s+'+name+'\\s*\\(','m'),name,macros);
assert.equal(macros.GOAT_XML_MIN_BACK_TRADES,'50','the kept-pass trade filter and the reported minimum share one constant');
assert.match(X,/back_trades<GOAT_XML_MIN_BACK_TRADES|back_trades<50/);

// ---- Native stubs: Common Files as line arrays, MQL string/array/date helpers.
const DAY=86400;
const epoch=s=>Date.UTC(+s.slice(0,4),+s.slice(5,7)-1,+s.slice(8,10))/1000;
const date=t=>new Date(t*1000).toISOString().slice(0,10).replace(/-/g,'.');
function makeContext(files,{realForward=false}={}){
  const handles=[],logs=[],alerts=[],calls=[];
  const newRow=()=>({pass:-1,back_result:0,back_profit:0,back_PF:0,back_RF:0,back_SR:0,back_DD_pc:0,back_trades:0,
    forward_result:0,forward_profit:0,forward_PF:0,forward_RF:0,forward_SR:0,forward_DD_pc:0,forward_trades:0,Inputs:'',Score:0,forward_seen:false});
  const rows=[];rows.make=newRow;
  const c={logs,alerts,calls,Rows:rows,topRowsNoDup:[],RowsUnique:[],m_inputVarNames:[],
    reportMode:false,_K:'',_N:'',_S:'',Title:'',symbol_:'',TF_:'',startD:0,endD:0,forwardD:0,
    metadataWithWorkbookStart:'',DocumentProperties:'',WorksheetLine:'',InputsNames:'',
    passesSeen:0,profitableSeen:0,bestProfit:0,bestResult:0,outcome:'',tradedSeen:0,malformedSeen:0,forwardRows:0,reportClosed:false,
    forwardMatched:0,forwardMismatches:0,forwardMalformed:0,bestCombinedScore:0,pairOutcome:'',belowScoreRow:-1,
    MathLog:Math.log,MathAbs:Math.abs,MathMin:Math.min,MathMax:Math.max,double:x=>x,
    MathSqrt:Math.sqrt,EMPTY_VALUE:Number.MAX_VALUE,StringToTime:s=>/^\d{4}\.\d{2}\.\d{2}$/.test(String(s))?epoch(String(s)):0,
    FILE_READ:1,FILE_COMMON:2,FILE_ANSI:4,CP_UTF8:65001,INVALID_HANDLE:-1,TIME_DATE:1,__FUNCTION__:'SXmlData::ProcessBackXml',
    FileOpen:name=>{if(!(name in files))return -1;handles.push({lines:files[name],at:0});return handles.length-1;},
    FileIsEnding:h=>handles[h].at>=handles[h].lines.length,
    FileReadString:h=>{const f=handles[h];return f.at<f.lines.length?f.lines[f.at++]:'';},
    FileClose:()=>{},
    StringFind:(s,t,from=0)=>String(s).indexOf(t,from),StringLen:s=>String(s).length,
    StringSubstr:(s,a,n)=>n===undefined?String(s).slice(a):String(s).substr(a,n),
    StringGetCharacter:(s,k)=>String(s).charCodeAt(k),
    StringCompare:(a,b)=>a===b?0:(a<b?-1:1),StringToDouble:s=>parseFloat(s)||0,
    StringSplit:(s,sep,out)=>{out.length=0;out.push(...String(s).split(typeof sep==='number'?String.fromCharCode(sep):sep));return out.length;},
    ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push(a.make?a.make():'');a.length=n;return n;},
    DoubleToString:(x,n)=>Number(x).toFixed(n),TimeToString:t=>date(t),
    LogOrPrint:(mode,text)=>logs.push(text),Alert:text=>alerts.push(text),FileNameOnly:p=>p.split('\\').pop(),
    // Out-parameter helpers are not under test: parse exactly what the report title holds.
    ExtractTitleFromDocument:doc=>{const m=doc.match(/<Title>(.*)<\/Title>/);if(!m)return false;c.Title=m[1];return true;},
    ExtractDatesFromTitle:title=>{const m=title.match(/(\d{4}\.\d{2}\.\d{2})-(\d{4}\.\d{2}\.\d{2})$/);if(!m)return false;c.startD=epoch(m[1]);c.endD=epoch(m[2]);return true;},
    ExtractSymbolTfFromTitle:title=>{const m=title.match(/ (\S+),(\S+) \S+$/);if(!m)return false;c.symbol_=m[1];c.TF_=m[2];return true;},
    __forwardDate:name=>{const m=name.match(/\((\d{4}\.\d{2}\.\d{2})\)/);return m?epoch(m[1]):0;},
    // The forward merge and writers are unchanged; like production they refuse empty Rows.
    ProcessForwardXml:()=>{calls.push('forward');return c.Rows.length>0&&c.forwardOk!==false;},
    WriteTopToXml:()=>{calls.push('top');return c.Rows.length>0?(c.saved??3):0;},
    WriteUniqueRowsToXml:()=>{calls.push('unique');return c.Rows.length>0;},
  };
  vm.createContext(c);
  vm.runInContext('var xmlData=globalThis;',c);
  for(const name of ['ProcessBackXml','ExtractDataAsDouble','ExtractDataFromCell','ParseInputVariableNames','ResetData',
                     'OutcomeDetails','OutcomeWindow','OutcomeSentence','IsNumberCell','ForwardReportRows',
                     'GetBackPassRow','CalculateCustomScore','CalculateCustomScore2'])vm.runInContext(method(name),c);
  vm.runInContext(method('SortRowsByScoreDescending').replace(/\bSRowDefinition\s+temp=/,'let temp='),c);
  // The production forward merge and scoring (no-qualifying-rows cases); older cases keep the stub.
  if(realForward)vm.runInContext(method('ProcessForwardXml'),c);
  vm.runInContext(extract(X,/^string\s+GoatXmlResearchOutcome\s*\(/m,'GoatXmlResearchOutcome',macros),c);
  vm.runInContext(extract(X,/^string\s+GoatXmlNoQualifierOutcome\s*\(/m,'GoatXmlNoQualifierOutcome',macros),c);
  // The FWD profit/DD export rule (GOAT_BELOW_SCORE_EXPORT_V149) the combiner calls when that flag is on.
  if(DEFINED.has('GOAT_BELOW_SCORE_EXPORT_V149'))for(const name of BELOW_SCORE_FUNCTIONS)vm.runInContext(method(name),c);
  const combiner=extract(X,/^bool\s+ReportAnalyzerCombiner\s*\(/m,'ReportAnalyzerCombiner',macros)
    .replace('xmlData.ExtractForwardDate(fileMain,ForwardDate)','((ForwardDate=__forwardDate(fileMain))!=0)');
  assert.ok(combiner.includes('__forwardDate('),'forward date extraction still precedes the back report');
  vm.runInContext(combiner,c);
  return c;
}
// replay_research_outcome.cjs reuses the production functions over real report copies.
if(process.env.GOAT_OUTCOME_HARNESS_ONLY){module.exports={makeContext,extract,convert,block,preprocess,stripComments,method,X,macros,DEFINED,epoch,date};return;}
const HEAD=['Pass','Result','Profit','Expected Payoff','Profit Factor','Recovery Factor','Sharpe Ratio','Custom','Equity DD %','Trades'];
const cell=(type,v)=>'<Cell><Data ss:Type="'+type+'">'+v+'</Data></Cell>';
// A score cell: r.types[key] overrides its type, r.raw[key] its text (e.g. '1.#INF' typed Number).
const sc=(r,key,def)=>cell(r.types?.[key]??'Number',r.raw?.[key]??r[key]??def);
function report(title,rows){
  const lines=['<?xml version="1.0"?>','<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">',
    '<DocumentProperties xmlns="urn:schemas-microsoft-com:office:office">','<Title>'+title+'</Title>','<Author>MetaQuotes</Author>',
    '</DocumentProperties>','<Styles></Styles>','<Worksheet ss:Name="Tester Optimizator Results">','<Table>','<Row>',
    ...HEAD.map(h=>cell('String',h)),cell('String','InpPeriod'),'</Row>'];
  for(const r of rows)lines.push('<Row>',cell('Number',r.pass),cell('Number',r.result),sc(r,'profit'),cell('Number',0),
    sc(r,'pf',1),sc(r,'rf',1),sc(r,'sr',1),cell('Number',0),cell('Number',r.dd??5),sc(r,'trades'),
    cell('Number',r.input??10),'</Row>');
  lines.push('</Table>','</Worksheet>','</Workbook>');
  return lines;
}
function forwardReport(rows,closed=true){
  const lines=['<?xml version="1.0"?>','<Workbook>','<Table>','<Row>',cell('String','Pass'),'</Row>'];
  for(let i=0;i<rows;i++)lines.push('<Row>',cell('Number',i),cell('Number',0.01),cell('Number',0.01),'</Row>');
  if(closed)lines.push('</Table>','</Worksheet>','</Workbook>');
  return lines;
}
const TITLE='GOAT V1.49 USDCAD,M1 2024.01.08-2025.03.15';
const FOLDER='GOAT\\Rabcdef012345\\reports\\R0123456789abcdef0123\\USDCAD\\';
const back=(title=TITLE,forward='2025.01.06')=>FOLDER+title+(forward?' ('+forward+')':'')+'.xml';
const losing=n=>Array.from({length:n},(_,i)=>({pass:i,result:i===7?0.05:0.01,profit:i===7?-1261.09:-1500-i,pf:0.66,trades:175}));
function combine(pairs,{reportMode=false,saved,forwardOk,realForward=false}={}){
  const files={},names=[];
  for(const p of pairs){
    if(p.back!==null)files[p.name]=p.back;
    names.push(p.name);
    if(p.forward!==false){
      const fwd=p.name.slice(0,-4)+'.forward.xml',n=p.forwardRows??Math.max(1,p.back?p.back.filter(l=>l==='<Row>').length-1:1);
      files[fwd]=p.forwardLines??forwardReport(n);names.push(fwd);
    }
  }
  const c=makeContext(files,{realForward});
  if(saved!==undefined)c.saved=saved;
  if(forwardOk!==undefined)c.forwardOk=forwardOk;
  const ret=vm.runInContext('ReportAnalyzerCombiner(__names,'+reportMode+',"GOAT","GOAT V1.49","Darwinex-Demo")',Object.assign(c,{__names:names}));
  return {ret,c};
}
let passed=0;const check=fn=>{fn();passed++;};

// 1) The g6 case: 175 passes, none profitable, best -1,261.09 at score 0.05.
{
  const {ret,c}=combine([{name:back(),back:report(TITLE,losing(175))}]);
  check(()=>assert.equal(ret,false,'nothing combined: still not a success, so no export runs'));
  check(()=>assert.equal(c.outcome,'no_profitable_passes'));
  check(()=>assert.equal(c.passesSeen,175));
  check(()=>assert.equal(c.profitableSeen,0));
  check(()=>assert.equal(c.OutcomeDetails(),'outcome=no_profitable_passes;passes=175;profitable=0;traded=175;malformed=0;complete=1;forward_rows=175;best_profit=-1261.09;best_score=0.0500;min_trades=50;window_start=2024.01.08;window_end=2025.01.06;forward_end=2025.03.15'));
  check(()=>assert.ok(c.logs.includes('No further back <Row> Found. Rows Saved=0/175 (profitable=0, min trades=50)'),'log reports kept/total passes, never 0/0'));
  check(()=>assert.deepEqual(c.calls,[],'forward merge and combined writers are skipped for a no-edge pair'));
  check(()=>assert.match(c.OutcomeSentence(),/^Tested 175 settings on USDCAD M1 in 2024\.01\.08 to 2025\.01\.06: none was profitable with 50\+ trades \(best profit -1261\.09\)\. A result for this window, not an error\.$/));
  check(()=>assert.ok(!c.logs.some(l=>/No Rows!/.test(l)),'no "No Rows!" combine error is logged'));
}
// 2) Profitable passes that all have fewer than 50 trades are still no edge, and say so.
{
  const rows=losing(20).concat([{pass:90,result:0.2,profit:310.5,trades:12},{pass:91,result:0.3,profit:120,trades:49}]);
  const {c}=combine([{name:back(),back:report(TITLE,rows)}]);
  check(()=>assert.equal(c.outcome,'no_profitable_passes'));
  check(()=>assert.match(c.OutcomeDetails(),/;passes=22;profitable=2;traded=22;malformed=0;complete=1;forward_rows=22;best_profit=310\.50;best_score=0\.3000;/));
  check(()=>assert.match(c.OutcomeSentence(),/with 50\+ trades \(2 profitable on fewer, best profit 310\.50\)/),'never says "none was profitable" when some were');
}
// 2b) Proof of trading and a whole report are required (review HIGH + MEDIUM): a
// member whose EA never traded, a report that cannot be read, or a partial report is
// a real error that --include-failed retries, never "tested, no edge".
{
  const zero=Array.from({length:175},(_,i)=>({pass:i,result:-0.01,profit:0,trades:0}));
  const unreadable=[];let row=-1;
  for(const l of report(TITLE,losing(40))){if(l==='<Row>')row=0;else if(row>=0&&row<20)row++;unreadable.push(row===3?l.replace('ss:Type="Number"','ss:Type="String"'):l);}
  const truncated=report(TITLE,losing(30)).slice(0,-3);           // killed before the table closed
  const midRow=report(TITLE,losing(30)).slice(0,-8);              // ends inside a row
  const shortRows=report(TITLE,losing(5)).map(l=>l===cell('Number',175)?'</Row>':l); // rows end before Trades
  for(const [label,lines,extra] of [
    ['every pass has 0 trades (EA never traded)',report(TITLE,zero),{}],
    ['profit cells cannot be read',unreadable,{}],
    ['report truncated before its table closed',truncated,{}],
    ['report ends inside a row',midRow,{}],
    ['rows end before the Trades cell',shortRows,{}],
    ['trades cells cannot be read',report(TITLE,losing(30)).map((l,k,a)=>l===cell('Number',175)&&a.indexOf(l)!==k?cell('String',175):l),{}],
    ['results table interrupted (never closed)',report(TITLE,losing(30)).map(l=>l==='</Table>'?'</Worksheet>':l),{}],
    ['forward report never closed',report(TITLE,losing(30)),{forwardLines:forwardReport(30,false)}],
    ['forward report has no rows',report(TITLE,losing(30)),{forwardRows:0}],
    ['forward report has more rows than back passes',report(TITLE,losing(30)),{forwardRows:31}],
  ]){
    const {c}=combine([{name:back(),back:lines,...extra}]);
    check(()=>assert.equal(c.outcome,'',label));
    check(()=>assert.ok(!c.logs.some(l=>/^Tested \d+ settings/.test(l)),label));
  }
  const z=combine([{name:back(),back:report(TITLE,zero)}]).c;
  check(()=>assert.deepEqual([z.passesSeen,z.tradedSeen],[175,0],'zero-trade passes are counted, but never as traded'));
  const u=combine([{name:back(),back:unreadable}]).c;
  check(()=>assert.equal(u.malformedSeen,40));
  const t=combine([{name:back(),back:truncated}]).c;
  check(()=>assert.equal(t.reportClosed,false));
  // One real traded pass among zero-trade passes is enough proof that the EA ran.
  const mixed=combine([{name:back(),back:report(TITLE,zero.slice(0,10).concat(losing(1)))}]).c;
  check(()=>assert.equal(mixed.outcome,'no_profitable_passes'));
  check(()=>assert.match(mixed.OutcomeDetails(),/;passes=11;profitable=0;traded=1;malformed=0;complete=1;/));
}
// 3) Kept rows are never a research outcome, whatever happens after (unchanged errors).
for(const [saved,forwardOk,wantRet] of [[3,true,true],[0,true,false],[3,false,false]]){
  const rows=losing(3).concat([{pass:50,result:0.9,profit:900,trades:120},{pass:51,result:0.8,profit:400,trades:60}]);
  const {ret,c}=combine([{name:back(),back:report(TITLE,rows)}],{saved,forwardOk});
  check(()=>assert.equal(ret,wantRet));
  check(()=>assert.equal(c.outcome,''));
  check(()=>assert.ok(c.logs.includes('No further back <Row> Found. Rows Saved=2/5 (profitable=2, min trades=50)')));
  check(()=>assert.ok(c.calls.includes('forward')));
}
// 3b) A partial or unreadable back report never combines, even with kept rows (review
// APPROVE follow-up): the combine fails, the member stays a real error, never no-edge.
{
  const keptRows=losing(3).concat([{pass:50,result:0.9,profit:900,trades:120},{pass:51,result:0.8,profit:400,trades:60}]);
  const whole=report(TITLE,keptRows);
  const cutMidRow=whole.slice(0,-6);                                          // killed inside the last kept row
  const unclosed=whole.map(l=>l==='</Table>'?'</Worksheet>':l);               // table never closed
  const unreadable=whole.map((l,k)=>l===cell('Number',-1501)?cell('String',-1501):l); // one profit cell unreadable
  for(const [label,lines] of [['back report cut mid-row',cutMidRow],['back report table never closed',unclosed],
                              ['back report with an unreadable row',unreadable]]){
    const {ret,c}=combine([{name:back(),back:lines}],{saved:3,forwardOk:true});
    check(()=>assert.equal(ret,false,label+': the combine fails'));
    check(()=>assert.equal(c.outcome,'',label+': never no-edge'));
    check(()=>assert.ok(c.logs.some(l=>/^❌ Back report is partial or has unreadable rows/.test(l)),label+': says why'));
  }
  const ok=combine([{name:back(),back:whole}],{saved:3,forwardOk:true});
  check(()=>assert.equal(ok.ret,true,'a whole report with kept rows still combines'));
  check(()=>assert.ok(!ok.c.logs.some(l=>/partial or has unreadable rows/.test(l))));
}
// 4) Every other failure stays an error: no passes, no window, wrong file, missing evidence.
for(const [label,pair] of [
  ['report without passes',{name:back(),back:report(TITLE,[])}],
  ['title without a date range',{name:back('GOAT V1.49 USDCAD,M1'),back:report('GOAT V1.49 USDCAD,M1',losing(5))}],
  ['file name does not match the title',{name:back(),back:report('GOAT V1.49 EURUSD,M1 2024.01.08-2025.03.15',losing(5))}],
  ['no forward date in the file name',{name:back(TITLE,''),back:report(TITLE,losing(5))}],
  ['forward date outside the window',{name:back(TITLE,'2025.06.01'),back:report(TITLE,losing(5))}],
  ['no forward report',{name:back(),back:report(TITLE,losing(5)),forward:false}],
  ['back report cannot be opened',{name:back(),back:null}],
]){
  const {ret,c}=combine([pair]);
  check(()=>assert.equal(ret,false,label));
  check(()=>assert.equal(c.outcome,'',label));
  check(()=>assert.ok(!c.logs.some(l=>/^Tested \d+ settings/.test(l)),label+' is never described as a tested result'));
}
// The guard on its own: every input must hold, one at a time.
{
  const c=makeContext({}),W=[epoch('2024.01.08'),epoch('2025.01.06'),epoch('2025.03.15')];
  const guard=(...a)=>vm.runInContext('GoatXmlResearchOutcome('+a.map(v=>JSON.stringify(v)).join(',')+')',c);
  // args: back_read, title_matches, start, forward, end, passes, kept, traded, malformed, closed, forward_rows
  const ok=[true,true,...W,175,0,175,0,true,175];
  const at=(i,v)=>ok.map((x,k)=>k===i?v:x);
  check(()=>assert.equal(guard(...ok),'no_profitable_passes'));
  check(()=>assert.equal(guard(...at(7,1)),'no_profitable_passes','one traded pass is enough'));
  for(const [label,args] of [['back report unread',at(0,false)],['file name mismatch',at(1,false)],
    ['no window start',at(2,0)],['forward before start',[true,true,W[1],W[0],W[2],175,0,175,0,true,175]],
    ['forward after end',[true,true,W[0],W[2],W[1],175,0,175,0,true,175]],['no passes',[true,true,...W,0,0,0,0,true,1]],
    ['kept rows',at(6,1)],['no pass traded',at(7,0)],['more traded than passes',at(7,176)],['a row did not parse',at(8,1)],
    ['results table never closed',at(9,false)],['forward report unreadable or unclosed',at(10,-1)],['forward report empty',at(10,0)],
    ['forward rows exceed back passes',at(10,176)]])
    check(()=>assert.equal(guard(...args),'',label));
}
// 5) Several pairs: only all-no-edge is the outcome; a mix keeps the old error result.
{
  const other='GOAT V1.49 USDCAD,M5 2024.01.08-2025.03.15';
  const both=combine([{name:back(),back:report(TITLE,losing(4))},{name:back(other),back:report(other,losing(6))}]);
  check(()=>assert.equal(both.c.outcome,'no_profitable_passes'));
  const kept=[{pass:1,result:1,profit:500,trades:80}];
  const mixed=combine([{name:back(),back:report(TITLE,losing(4))},{name:back(other),back:report(other,kept)}]);
  check(()=>assert.equal(mixed.ret,false,'a no-edge pair still means nothing was combined for it'));
  check(()=>assert.equal(mixed.c.outcome,''));
  const broken=combine([{name:back(),back:report(TITLE,losing(4))},{name:back(other),back:report(other,losing(3)),forward:false}]);
  check(()=>assert.equal(broken.c.outcome,'','a real failure in another pair is never masked'));
}
// 6) Report mode (Optimization Processor) says what happened instead of "check Experts logs".
{
  const {c}=combine([{name:back(),back:report(TITLE,losing(9))}],{reportMode:true});
  check(()=>assert.deepEqual(c.alerts,[c.OutcomeSentence()]));
  const err=combine([{name:back(),back:report(TITLE,[])}],{reportMode:true});
  check(()=>assert.match(err.c.alerts[0],/One or more error/));
}

// ---- No qualifying rows (Banker g6-r1b, EX33): profitable back passes were kept, merged with
// the forward report by the production reader and scored, and none reached the export score.
// Before: WriteTopToXml wrote 0 rows, WriteUniqueRowsToXml logged "No Rows!", member Error.
const FHEAD=['Pass','Forward Result','Back Result','Profit','Expected Payoff','Profit Factor','Recovery Factor','Sharpe Ratio','Custom','Equity DD %','Trades'];
function forwardFull(rows,{closed=true}={}){
  const lines=['<?xml version="1.0"?>','<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">','<Worksheet ss:Name="Tester Optimizator Results">',
    '<Table>','<Row>',...FHEAD.map(h=>cell('String',h)),cell('String','InpPeriod'),'</Row>'];
  for(const r of rows)lines.push('<Row>',cell('Number',r.pass),cell('Number',r.fresult??0.01),cell(r.bresultType??'Number',r.bresult),
    r.profitType?cell(r.profitType,r.profit):sc(r,'profit'),cell('Number',0),sc(r,'pf',1),sc(r,'rf',1),sc(r,'sr',1),cell('Number',0),
    cell('Number',r.dd??5),sc(r,'trades'),cell('Number',r.input??10),'</Row>');
  if(closed)lines.push('</Table>','</Worksheet>','</Workbook>');
  return lines;
}
// 151 losing passes and 7 kept ones (profitable, 50+ trades). Kept passes go on trading in the
// forward period, but far below their in-sample pace: every combined score stays under 60.
const keptBack=k=>({pass:151+k,result:0.5+k/100,profit:600+10*k,pf:1.4,rf:2,sr:1.5,trades:80,input:20+k});
const weakForward=k=>({pass:151+k,bresult:0.5+k/100,profit:k<5?30+k:-40,pf:1.1,rf:0.15,sr:0.8,trades:15,input:20+k});
const strongForward=k=>{const b=keptBack(k),ratio=364/68;   // forward period matches the in-sample pace exactly
  return {pass:b.pass,bresult:b.result,profit:b.profit/ratio,pf:b.pf,rf:(b.profit/ratio)/(b.profit/b.rf),sr:b.sr,trades:Math.round(b.trades/ratio),input:b.input};};
const losingForward=n=>Array.from({length:n},(_,i)=>({pass:i,bresult:i===7?0.05:0.01,profit:-20,trades:30}));
const g6Back=()=>report(TITLE,losing(151).concat(Array.from({length:7},(_,k)=>keptBack(k))));
const g6Forward=(kept=Array.from({length:7},(_,k)=>weakForward(k)))=>losingForward(151).concat(kept);
const noQualifier=(forwardRows,opts={})=>combine([{name:back(),back:opts.back??g6Back(),forwardLines:forwardFull(forwardRows,opts)}],{realForward:true,saved:3});
{
  const {ret,c}=noQualifier(g6Forward());
  check(()=>assert.equal(ret,false,'nothing combined: still not a success, so no export runs'));
  check(()=>assert.equal(c.outcome,'no_qualifying_rows'));
  check(()=>assert.ok(c.logs.includes('No further back <Row> Found. Rows Saved=7/158 (profitable=7, min trades=50)')));
  check(()=>assert.ok(c.logs.includes('No further forward <Row> Found. Discarded=151/158'),'the production forward reader ran'));
  check(()=>assert.deepEqual([c.forwardMatched,c.forwardMismatches,c.forwardMalformed],[7,0,0]));
  check(()=>assert.ok(c.bestCombinedScore>30&&c.bestCombinedScore<60,'scored by the production formula, below the export score: '+c.bestCombinedScore));
  check(()=>assert.equal(c.bestCombinedScore,c.Rows[0].Score,'best is the top row after sorting'));
  check(()=>assert.equal(c.OutcomeDetails(),'outcome=no_qualifying_rows;passes=158;profitable=7;traded=158;malformed=0;complete=1;forward_rows=158;'
    +'best_profit=660.00;best_score=0.5600;min_trades=50;window_start=2024.01.08;window_end=2025.01.06;forward_end=2025.03.15;'
    +'back_rows=7;forward_matched=7;forward_discarded=151;forward_mismatches=0;forward_malformed=0;best_combined_score='+c.bestCombinedScore.toFixed(1)+';score_threshold=60.0'));
  check(()=>assert.equal(c.OutcomeSentence(),'Tested 158 settings on USDCAD M1 in 2024.01.08 to 2025.01.06: 7 were profitable with 50+ trades in-sample '
    +'but none scored 60+ once the forward period to 2025.03.15 was included (best '+c.bestCombinedScore.toFixed(1)+'). A result for this window, not an error.'));
  check(()=>assert.ok(c.logs.includes(c.OutcomeSentence()),'the plain sentence is logged'));
  check(()=>assert.deepEqual(c.calls,[],'the combined writers are skipped: no 0-row CombinedRows file, no "No Rows!"'));
  check(()=>assert.ok(!c.logs.some(l=>/No Rows!|❌/.test(l)),'no error is logged'));
  // One kept pass: singular wording.
  const one=combine([{name:back(),back:report(TITLE,losing(20).concat([keptBack(0)])),forwardLines:forwardFull(losingForward(20).concat([weakForward(0)]))}],{realForward:true});
  check(()=>assert.equal(one.c.outcome,'no_qualifying_rows'));
  check(()=>assert.match(one.c.OutcomeSentence(),/: 1 was profitable with 50\+ trades in-sample/));
  // Every kept pass lost in the forward period: best 0.0 says why, so it never reads as rounding.
  const zero=combine([{name:back(),back:g6Back(),forwardLines:forwardFull(g6Forward(Array.from({length:7},(_,k)=>({...weakForward(k),profit:-40}))))}],{realForward:true});
  check(()=>assert.equal(zero.c.outcome,'no_qualifying_rows'));
  check(()=>assert.match(zero.c.OutcomeSentence(),/ \(best 0\.0: the forward period scored zero\)\. A result for this window, not an error\.$/));
  check(()=>assert.ok(!/scored zero/.test(c.OutcomeSentence()),'only when the best is zero'));
  // Report mode says what happened.
  const rm=combine([{name:back(),back:g6Back(),forwardLines:forwardFull(g6Forward())}],{realForward:true,reportMode:true});
  check(()=>assert.deepEqual(rm.c.alerts,[rm.c.OutcomeSentence()]));
}
// A kept pass that holds up in the forward period still combines and exports as before.
{
  const kept=Array.from({length:7},(_,k)=>k===3?strongForward(k):weakForward(k));
  const {ret,c}=noQualifier(g6Forward(kept));
  check(()=>assert.ok(c.bestCombinedScore>=60,'the strong pass scores 60+: '+c.bestCombinedScore));
  check(()=>assert.equal(c.outcome,''));
  check(()=>assert.equal(ret,true));
  check(()=>assert.deepEqual(c.calls,['top','unique']));
  check(()=>assert.ok(!c.logs.some(l=>/in-sample but none scored/.test(l))));
}
// Real failures stay errors (retried by --include-failed), never "nothing qualified".
{
  const weak=g6Forward();
  const without=(i)=>weak.filter((_,k)=>k!==i);
  const edit=(i,patch)=>weak.map((r,k)=>k===i?{...r,...patch}:r);
  for(const [label,rows,opts] of [
    ['a kept pass is missing from the forward report',without(155),{}],
    ['forward back-result disagrees with the back report',edit(153,{bresult:0.99}),{}],
    ['forward inputs disagree with the back report',edit(154,{input:99}),{}],
    ['a kept pass appears twice in the forward report',without(3).concat([weakForward(2)]),{}],
    ['a forward profit cell cannot be read',edit(152,{profitType:'String'}),{}],
    ['forward report never closed',weak,{closed:false}],
    ['forward report cut inside a kept row',null,{cut:true}],
    ['forward report has more rows than back passes',weak.concat([{pass:999,bresult:0.01,profit:-1,trades:1}]),{}],
  ]){
    const lines=opts.cut?forwardFull(weak).slice(0,-12):forwardFull(rows,opts);
    const {ret,c}=combine([{name:back(),back:g6Back(),forwardLines:lines}],{realForward:true,saved:0});
    check(()=>assert.equal(c.outcome,'',label));
    check(()=>assert.equal(ret,false,label+': still an error'));
    check(()=>assert.ok(!c.logs.some(l=>/in-sample but none scored/.test(l)),label+' is never described as a tested result'));
  }
  // Codex P1: every cell the combined score reads must parse strictly, back and forward. An
  // unreadable PF, RF, SR, profit or trades cell would read as 0.0 and could pull the best
  // score under 60; it is a processing error, never "nothing qualified".
  for(const key of ['profit','pf','rf','sr','trades'])
    for(const [how,patch] of [['typed String',{types:{[key]:'String'}}],['not a number',{raw:{[key]:'1.#INF'}}],['empty',{raw:{[key]:''}}]]){
      const label='forward '+key+' cell '+how;
      const lines=forwardFull(weak.map((r,k)=>k===154?{...r,...patch}:r));
      const {ret,c}=combine([{name:back(),back:g6Back(),forwardLines:lines}],{realForward:true,saved:0});
      check(()=>assert.equal(c.outcome,'',label));
      check(()=>assert.equal(ret,false,label+': still an error'));
      check(()=>assert.ok(c.forwardMalformed>0,label+' is counted'));
    }
  for(const key of ['pf','rf','sr'])
    for(const [how,patch] of [['typed String',{types:{[key]:'String'}}],['not a number',{raw:{[key]:'n/a'}}]]){
      const label='back '+key+' cell '+how+' on a kept pass';
      const backLines=report(TITLE,losing(151).concat(Array.from({length:7},(_,k)=>k===2?{...keptBack(k),...patch}:keptBack(k))));
      const {ret,c}=combine([{name:back(),back:backLines,forwardLines:forwardFull(weak)}],{realForward:true,saved:0});
      check(()=>assert.equal(c.outcome,'',label));
      check(()=>assert.equal(ret,false,label+': still an error'));
      check(()=>assert.ok(c.malformedSeen>0&&c.logs.some(l=>/^❌ Back report is partial or has unreadable rows/.test(l)),label+' is counted and named'));
    }
  // The strict cell parser itself.
  {
    const p=makeContext({});
    const num=v=>vm.runInContext('IsNumberCell('+JSON.stringify(cell('Number',v))+')',p);
    for(const v of ['0','12','-1261.09','+3.5','0.03','1e5','1.5E-3','2.e+10','.5',' 7 '])check(()=>assert.equal(num(v),true,v));
    for(const v of ['','-','1.#INF','inf','nan','1,5','1.2.3','e5','1e','1e+','--1','1-2','12a'])check(()=>assert.equal(num(v),false,JSON.stringify(v)));
    check(()=>assert.equal(vm.runInContext('IsNumberCell('+JSON.stringify(cell('String','12'))+')',p),false,'String type'));
  }
  // A partial or unreadable back report with kept rows never becomes "nothing qualified".
  const whole=g6Back();
  for(const [label,lines] of [['back report table never closed',whole.map(l=>l==='</Table>'?'</Worksheet>':l)],
                              ['back report with an unreadable row',whole.map(l=>l===cell('Number',-1501)?cell('String',-1501):l)]]){
    const {c}=combine([{name:back(),back:lines,forwardLines:forwardFull(weak)}],{realForward:true,saved:0});
    check(()=>assert.equal(c.outcome,'',label));
  }
  // No forward date, or no forward report at all: errors as before.
  check(()=>assert.equal(combine([{name:back(TITLE,''),back:g6Back(),forwardLines:forwardFull(weak)}],{realForward:true,saved:0}).c.outcome,''));
  check(()=>assert.equal(combine([{name:back(),back:g6Back(),forward:false}],{realForward:true,saved:0}).c.outcome,''));
}
// Several pairs: all "nothing qualified" is the outcome; a mix with "no profitable passes"
// or with a real failure keeps the old error result.
{
  const other='GOAT V1.49 USDCAD,M5 2024.01.08-2025.03.15';
  const otherBack=report(other,losing(151).concat(Array.from({length:7},(_,k)=>keptBack(k))));
  const both=combine([{name:back(),back:g6Back(),forwardLines:forwardFull(g6Forward())},
                      {name:back(other),back:otherBack,forwardLines:forwardFull(g6Forward())}],{realForward:true});
  check(()=>assert.equal(both.c.outcome,'no_qualifying_rows'));
  const mixed=combine([{name:back(),back:report(TITLE,losing(4))},
                       {name:back(other),back:otherBack,forwardLines:forwardFull(g6Forward())}],{realForward:true});
  check(()=>assert.equal(mixed.c.outcome,'','mixed outcomes are not described by one pair\'s details'));
  check(()=>assert.equal(mixed.ret,false));
  const broken=combine([{name:back(),back:g6Back(),forwardLines:forwardFull(g6Forward())},
                        {name:back(other),back:otherBack,forward:false}],{realForward:true});
  check(()=>assert.equal(broken.c.outcome,'','a real failure in another pair is never masked'));
}
// The guard on its own: every input must hold, one at a time.
{
  const c=makeContext({}),W=[epoch('2024.01.08'),epoch('2025.01.06'),epoch('2025.03.15')];
  const guard=(...a)=>vm.runInContext('GoatXmlNoQualifierOutcome('+a.map(v=>Number.isNaN(v)?'NaN':JSON.stringify(v)).join(',')+')',c);
  // back_read, title_matches, start, forward, end, passes, kept, profitable, traded, malformed, closed,
  // forward_rows, forward_read, forward_matched, forward_mismatches, forward_malformed, best_score, min_score
  const ok=[true,true,...W,158,7,7,158,0,true,158,true,7,0,0,48.1,60];
  const at=(i,v)=>ok.map((x,k)=>k===i?v:x);
  check(()=>assert.equal(guard(...ok),'no_qualifying_rows'));
  check(()=>assert.equal(guard(...at(16,0)),'no_qualifying_rows','every kept pass lost in the forward period'));
  check(()=>assert.equal(guard(...at(8,7)),'no_qualifying_rows','only the kept passes traded'));
  for(const [label,args] of [['back report unread',at(0,false)],['file name mismatch',at(1,false)],
    ['no window start',at(2,0)],['forward before start',[true,true,W[1],W[0],W[2],...ok.slice(5)]],
    ['forward after end',[true,true,W[0],W[2],W[1],...ok.slice(5)]],['no passes',at(5,0)],
    ['no kept rows (that is no_profitable_passes)',at(6,0).map((x,k)=>k===13?0:x)],['more kept than profitable',at(6,8)],['more profitable than passes',at(7,159)],
    ['fewer traded than kept',at(8,6)],['more traded than passes',at(8,159)],['a row did not parse',at(9,1)],
    ['results table never closed',at(10,false)],['forward report unreadable or unclosed',at(11,-1)],['forward report empty',at(11,0)],
    ['forward rows exceed back passes',at(11,159)],['forward merge failed',at(12,false)],['a kept pass not in the forward report',at(13,6)],
    ['forward disagrees with back',at(14,1)],['a forward row did not parse',at(15,1)],
    ['best score reaches the threshold',at(16,60)],['best score above the threshold',at(16,72.5)],['negative score',at(16,-1)],
    ['score not a number',at(16,NaN)],['no threshold',at(17,0)]])
    check(()=>assert.equal(guard(...args),'',label));
}

// ---- V1.49 OnTesterDeinit: the outcome is written to item_stats apart from real errors.
const mainMacros={GOAT_XML_NO_PROFITABLE_PASSES:'"no_profitable_passes"',GOAT_XML_NO_QUALIFYING_ROWS:macros.GOAT_XML_NO_QUALIFYING_ROWS};
assert.equal(macros.GOAT_XML_NO_QUALIFYING_ROWS,'"no_qualifying_rows"');
assert.equal(macros.GOAT_XML_MIN_COMBINED_SCORE,'60.0','the export score and the reported threshold share one constant');
assert.match(X,/_CombinedRows_Score="\+scorePostfix\+"\.xml",100,GOAT_XML_MIN_COMBINED_SCORE\)/);
const M=stripComments(preprocess(mainSource,{}));
const deinit=M.slice(M.indexOf('void OnTesterDeinit()'),M.indexOf('bool StartExporter(bool reportMode)'));
const combineCall=deinit.indexOf('if(ReportAnalyzerCombiner(movedFiles,false,Key,EA_Name,Server))');
const branchStart=deinit.indexOf('else {error=true;',combineCall);
const branchEnd=deinit.indexOf('Sleep(999);}}',branchStart)+'Sleep(999);}}'.length;
check(()=>assert.ok(combineCall>0&&branchStart>combineCall&&branchEnd>branchStart,'outcome branch follows a failed combine only'));
check(()=>assert.ok(deinit.indexOf('UpdateBatchQueueAndWriteConfigFile(false,error,Key,EA_Name,Server)')>branchEnd,'queue status still follows error'));
const branch=convert(deinit.slice(branchStart+'else '.length,branchEnd),mainMacros);
function deinitRun(outcome){
  const out={stats:[],logs:[],prompts:[]};
  const qualifier=outcome==='no_qualifying_rows';
  const xmlData={outcome,passesSeen:qualifier?158:175,Rows:qualifier?Array(7).fill({}):[],bestCombinedScore:48.1,
    OutcomeDetails:()=>'outcome='+(outcome||'no_profitable_passes')+';passes='+(qualifier?158:175),
    OutcomeSentence:()=>qualifier
      ?'Tested 158 settings on USDCAD M1 in 2024.01.08 to 2025.01.06: 7 were profitable with 50+ trades in-sample but none scored 60+ once the forward period to 2025.03.15 was included (best 48.1). A result for this window, not an error.'
      :'Tested 175 settings on USDCAD M1 in 2024.01.08 to 2025.01.06: none was profitable with 50+ trades (best profit -1261.09). A result for this window, not an error.',
    OutcomeWindow:()=>'2024.01.08 to 2025.01.06'};
  const c={xmlData,error:false,EA_Name:'GOAT V1.49',Server:'Darwinex-Demo',Key:'GOAT',Strat:'R0123456789abcdef0123',ArraySize:a=>a.length,
    Symbol:()=>'USDCAD',Sleep:()=>{},GoatOptAppendItemStats:(...a)=>out.stats.push(a),WriteLog:t=>out.logs.push(t),ShowPrompt:(...a)=>out.prompts.push(a)};
  vm.runInNewContext(branch,c);
  return {...out,error:c.error};
}
{
  const r=deinitRun('no_profitable_passes');
  check(()=>assert.equal(r.error,true,'queue status stays Error: no wire change'));
  check(()=>assert.deepEqual(r.stats,[['GOAT V1.49','Darwinex-Demo','USDCAD','R0123456789abcdef0123','NoProfitablePasses',0,0,0,0,'outcome=no_profitable_passes;passes=175']]));
  check(()=>assert.ok(r.logs.length===1&&!/❌|Failed to Analyze/.test(r.logs[0])&&/2024\.01\.08 to 2025\.01\.06/.test(r.logs[0])));
  check(()=>assert.ok(r.prompts.length===1&&r.prompts[0].slice(0,3).every(line=>line.length<=60),'prompt lines fit the card'));
  check(()=>assert.match(r.prompts[0][1],/175 settings, 2024\.01\.08 to 2025\.01\.06/));
  const e=deinitRun('');
  check(()=>assert.deepEqual(e.stats,[]));
  check(()=>assert.ok(e.error&&/Failed to Analyze and Combine/.test(e.logs[0]),'a real combine error is unchanged'));
  // No qualifying rows: its own item_stats status, kept-row count and best combined score.
  const q=deinitRun('no_qualifying_rows');
  check(()=>assert.equal(q.error,true,'queue status stays Error: no wire change'));
  check(()=>assert.deepEqual(q.stats,[['GOAT V1.49','Darwinex-Demo','USDCAD','R0123456789abcdef0123','NoQualifyingRows',7,0,48.1,0,'outcome=no_qualifying_rows;passes=158']]));
  check(()=>assert.ok(q.logs.length===1&&!/❌|Failed to Analyze/.test(q.logs[0])&&/none scored 60\+/.test(q.logs[0])&&/ No exports\.$/.test(q.logs[0])));
  check(()=>assert.ok(q.prompts.length===1&&q.prompts[0].slice(0,3).every(line=>line.length<=60),'prompt lines fit the card'));
  check(()=>assert.deepEqual(q.prompts[0].slice(0,3),['Nothing qualified in this window','Tested 158 settings, 2024.01.08 to 2025.01.06.',
    '7 profitable, none scored 60+; kept as a result.']));
}

// ---- End-of-batch summary counts no-edge items apart from errors.
const O=stripComments(preprocess(optimizerSource,{}));
const summaryAt=O.search(/^void BuildOptimizationBatchPromptSummary\(/m);
const [sb,se]=block(O,summaryAt);
const summaryBody=convert(O.slice(sb,se),{});
// The native queue (char 31 separated); its Error items are the only ones a no-edge row may relabel.
const queueOf=states=>Object.entries(states).map(([alias,state])=>';'+state+'_USDCAD,M1 2024.01.08-2025.03.15_OHLC:'+alias+';\r\n[Tester]\r\nSymbol=USDCAD').join('\x1f')+'\x1f';
const ERRORS=queueOf(Object.fromEntries(Array.from({length:9},(_,i)=>['A'+i,'Error'])));
function summary(itemStats,stats={total:8,completed:3,errors:5,pending:0,queued:0,ongoing:0,cancelled:0},queue=ERRORS){
  const c={queueFile:'GOAT\\GOAT V1.49-Darwinex-Demo\\g6\\queue.GOAT',logFile:'log.GOAT',
    ReadBatchProgressStats:(q,s)=>{Object.assign(s,stats);return true;},
    GoatOptFolderOf:p=>p.slice(0,p.lastIndexOf('\\')),
    GoatOptReadTextFile:p=>p==='GOAT\\GOAT V1.49-Darwinex-Demo\\g6\\item_stats.tsv'?itemStats:'',
    GetFileContent:p=>p==='GOAT\\GOAT V1.49-Darwinex-Demo\\g6\\queue.GOAT'?queue:'',
    StringSplit:(s,sep,out)=>{out.length=0;out.push(...String(s).split(typeof sep==='number'?String.fromCharCode(sep):sep));return out.length;},
    StringFind:(s,t,from=0)=>String(s).indexOf(t,from),ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;return n;},
    StringGetCharacter:(s,k)=>String(s).charCodeAt(k),StringSubstr:(s,a,n)=>n===undefined?String(s).slice(a):String(s).substr(a,n),
    MathMin:Math.min,MathMax:Math.max,FileOpen:()=>-1,INVALID_HANDLE:-1,FILE_READ:1,FILE_SHARE_READ:2,FILE_SHARE_WRITE:4,FILE_TXT:8,FILE_COMMON:16,
    IntegerToString:String,StringFormat:(f,...a)=>{let k=0;return f.replace(/%d/g,()=>String(a[k++]));}};
  vm.runInNewContext('(function()'+summaryBody+')()',c);
  return c.line1;
}
const HEADER='LocalTime\tSymbol\tStrategy\tStatus\tXmlRows\tUniqueRows\tTopScore\tFinalExports\tDetails';
const row=(sym,alias,status)=>['2026.10.02 09:50:26',sym,alias,status,'0','0','0.0','0','outcome=no_profitable_passes'].join('\t');
check(()=>assert.equal(summary(''),'Runs OK: 3/8 | Errors: 5 | Left: 0'));
check(()=>assert.equal(summary([HEADER,row('USDCAD','A1','NoProfitablePasses'),row('USDCHF','A2','NoProfitablePasses'),
  row('USDCAD','A1','NoProfitablePasses'),row('EURUSD','A3','Completed'),row('NZDUSD','A4','NoProfitablePasses')].join('\n')),
  'Runs OK: 3/8 | No edge: 3 | Errors: 2 | Left: 0'));
check(()=>assert.equal(summary([HEADER,...Array.from({length:9},(_,i)=>row('S'+i,'A'+i,'NoProfitablePasses'))].join('\n')),
  'Runs OK: 3/8 | No edge: 5 | Errors: 0 | Left: 0','never more no-edge items than queue errors'));
// Status check (review LOW): a row whose queue item is not Error (completed on a rerun,
// still pending, or from another queue) is never counted.
check(()=>assert.equal(summary([HEADER,row('USDCAD','A1','NoProfitablePasses'),row('USDCHF','A2','NoProfitablePasses'),row('EURUSD','A3','NoProfitablePasses')].join('\n'),
  undefined,queueOf({A1:'Error',A2:'Completed',A3:'Pending',A4:'Error'})),'Runs OK: 3/8 | No edge: 1 | Errors: 4 | Left: 0'));
// Nothing qualified counts with no edge, apart from errors; other statuses still never do.
check(()=>assert.equal(summary([HEADER,row('USDCAD','A1','NoProfitablePasses'),row('USDCHF','A2','NoQualifyingRows'),row('EURUSD','A3','NoQualifyingRows'),
  row('NZDUSD','A4','Error'),row('AUDUSD','A5','Completed')].join('\n')),'Runs OK: 3/8 | No edge: 3 | Errors: 2 | Left: 0'));
console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
