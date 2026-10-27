// B50 no-drift guard (B50-alpha, docs/b50/B50_ALPHA_DESIGN.md section 4: the A0 scaffold, then A1-A3, then the A4
// assembly). B50 = B49a + the single-trade engine, D1 and the New York clock, each in its own reviewed PR. Against B49a
// (source 65fde12, GOAT-EA#267 merged; its source hashes are committed in candidate-builds/beta17-B49a/identity.json):
// - every file of B49a's compile closure outside CHANGED is byte-identical to B49a;
// - in the CHANGED files, every line added or replaced since B49a carries the marker "B50" or sits inside a
//   "// B50:begin <item>" ... "// B50:end <item>" block, so nothing changes unmarked; pure deletions are refused, and
//   every B49a line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure only gains the files in ADDED (GOAT_NYClock.mqh, A2's file);
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json is exactly what studio_input_schema.discover reads from this header; inputs are append-only: B49a's 115
//   inputs keep their order, type, default and enum choices, except that each ENUM_MODE_TFs input gains exactly
//   {"TF_D1":1440} (Claude-Mac ruling 1), and the new ones are exactly NEW_INPUTS, in order, after Ledger_Mode;
// - until the A4 assembly the build identity is B49a's (A4 moves the build ID and marker and adds IDENTITY_LINES).
// Replaces test_b49a_no_drift.cjs as the tree's guard; that one now proves B49a's own commit (65fde12).
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B50 change is marked, listed and reviewable. Neutrality with
// the new inputs at their defaults is proven by scripts/test_b50_parity.cjs (the converted OnTick region of B49a and
// of this tree on the same fixtures, and the WriteSet golden) and, natively, by the tester parity on Banker (flags off,
// B50 against B49a e43ed98e, identical deal tables on the 48 templates and sampled exports).
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='65fde12';
// Each item PR adds the files it changes or adds, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATStudioSettingCompare.mqh','GOATPortfolioChildAudit.mqh'];
const ADDED=['GOAT_NYClock.mqh'];   // A0's stub; A2 fills it
// Every B49a line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOAT V1.49.mq5':[
  'if(InActive && stm_cur.hour>=Hour_End[k])//&& FindNumberOfPositions(OP_BUYSELL,MAGIC1)>0)',                        // A0: the NY clock's day end
  'if(InActive && stm_cur.day_of_week==5 && stm_cur.hour>=Hour_End[k])//&& FindNumberOfPositions(OP_BUYSELL,MAGIC1)>0)', // A0: the NY clock's Friday
  'if(!DashboardPortfolioPaused&&Allow_New_Sequence&&Sequence_New_Friday&&Sequence_New_Dec&&(DashboardTradeAllowBuy||DashboardTradeAllowSell)) SignalEntryTrigger();//Buys,Sells);', // A0: g_GoatEntryBlocked
 ],
 'GOATStudioSettingTypes.mqh':[
  'return "|Trailing_Sample_Period|Allow_Opposite_Seq|Reverse_Seq|Mode_Trade|Grid_Size|Grid_Min|Grid_Max|Grid_Exponent|Grid_Factor|Lock_Profit_Size|Lock_Profit_Flexibility|TP_Pips|SL_Pips|RRR|Mode_RRR|TSL_Size|Mode_Trail|Delay_Trade|Delay_Trade_Live|Delay_Lots_Add|Max_Seq_Trades|CloseAtMaxLevels|ATR_TF_|ATR_Period|ATR_Method|Lots_Input|Lots_Max|Lots_Max_Cum|Lots_Exponent|Lots_Factor|Mode_Lots_Prog|Peak_Lots_Pos_PC|Partial_Profit_Factor|Peak_Smart_Release_PC|Peak_Smart_Max_Close_PC|MaxDailyLossLocal|MaxDailyProfitLocal|RSI_Mode|RSI_TF_|RSI_Period|RSI_Price|RSI_Level|EMA_Mode|EMA_TF_|EMA_Method|EMA_Price|EMA_Count|EMA_Period|EMA_Exponent|EMA_MustCheck|ADX_Mode|ADX_TF_|ADX_Period|ADX_Level|ADX_MustCheck|BB_Mode|BB_TF_|BB_Period|BB_Deviation|BB_MustCheck|MACD_Mode|MACD_Mode_Trend|MACD_TF_|MACD_Fast|MACD_Slow|MACD_Signal|MACD_Deviations|MACD_Price|MACD_MustCheck|RSI2_Mode|RSI2_TF_|RSI2_Period|RSI2_Price|RSI2_Level|RSI2_MustCheck|Active_Time_Weekday|Active_Time_Friday|Action_Dayend|Action_Friday|Trade_Friday|Bias_Protocol|Mode_Bias|Mode_Bias_Trades|Mode_Bias_Exit|Bias_Exit_Max_Exposure_Adds|Bias_threshold|Mode_News|News_threshold|News_beforeMinutes|News_afterMinutes|";', // A0: the B50 optimization axes
 ],
};
// The B50-alpha inputs (design note section 2, items 1-12), appended after Ledger_Mode in this order (ruling 8).
const NEW_INPUTS=['Engine_Mode','Single_SL_ATR','Single_TP_ATR','Single_TP_R','Single_Exit_Opposite','Single_Time_Stop_Bars',
 'Single_Time_Stop_TF','Clock_Mode','Server_Clock_Model','Server_UTC_Offset','NY_Session','Rollover_Block_Minutes'];
const NEW_DEFAULTS={Engine_Mode:['sinput','ENUM_ENGINE_MODE','Engine_Grid'],Single_SL_ATR:['input','double','0.0'],Single_TP_ATR:['input','double','0.0'],
 Single_TP_R:['input','double','0.0'],Single_Exit_Opposite:['input','bool','false'],Single_Time_Stop_Bars:['input','int','0'],
 Single_Time_Stop_TF:['input','ENUM_MODE_TFs','TF_Cur'],Clock_Mode:['sinput','ENUM_CLOCK_MODE','Clock_Server'],
 Server_Clock_Model:['sinput','ENUM_SERVER_CLOCK_MODEL','ServerClock_NYClose'],Server_UTC_Offset:['sinput','int','2'],
 NY_Session:['input','string','"09:30-16:00"'],Rollover_Block_Minutes:['input','int','0']};
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const b49a=JSON.parse(read('candidate-builds/beta17-B49a/identity.json'));
let checks=0;

// 1. The baseline really is B49a: its commit's blobs (checked out as the tree would be) hash to B49a's identity.
for(const [f,h] of Object.entries(b49a.sources)){
 const blob=git(['show',B49A_SOURCE+':'+f]);
 assert.equal(sha(checkedOut(f,blob)),h,'B49a source '+B49A_SOURCE+' is the identity of '+f);
}
assert.equal((b49a.build_id+' '+b49a.build_marker),'V1.49-BETA17-49 B49a');
checks++;

// 2. The compile closure: B49a's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b49aMql=Object.keys(b49a.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b49aMql,...ADDED].sort(),'the compile closure is B49a\'s plus ADDED');
// An added file is a tracked GOAT source like the others: UTF-8 with BOM, CRLF, carrying the marker.
for(const f of ADDED){
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');assert.match(buf.toString('utf8'),/B50/,f+': marked');
}
checks++;

// 3. Outside CHANGED (and the new files), every B49a source is byte-identical.
for(const [f,h] of Object.entries(b49a.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B49a: '+f);
for(const f of CHANGED) assert.notEqual(sha(read(f)),b49a.sources[f],'CHANGED lists only files that changed: '+f);
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B50:begin (\S+)/),end=line.match(/\/\/ B50:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B50 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B50:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B50 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B49A_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B49a');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B49a line(s) is unmarked');
  for(const n of added){
   const text=lines[n-1];
   assert.ok(/B50/.test(text)||inBlock[n-1],f+':'+n+' changed since B49a without a B50 marker: '+text.trim());
  }
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B49a lines removed are exactly REMOVED');
}
checks++;

// 5. The input contract follows the tree, append-only against B49a, with the TF_D1 allowance.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
const schema=JSON.parse(read('controller/contracts/v149/inputs.json').toString('utf8').replace(/^﻿/,''));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(git(['show',B49A_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^﻿/,''));
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.equal(beforeNames.length,115,'B49a declares 115 header inputs');assert.equal(beforeNames.at(-1),'Ledger_Mode');
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B49a\'s inputs keep their order');
const tfInputs=beforeNames.filter(n=>before.inputs[n].type==='ENUM_MODE_TFs');
assert.deepEqual(tfInputs,['ATR_TF_','RSI_TF_','EMA_TF_','ADX_TF_','BB_TF_','MACD_TF_','RSI2_TF_'],'the existing timeframe inputs');
for(const name of beforeNames){
 const was=before.inputs[name],now=schema.inputs[name];
 if(was.type==='ENUM_MODE_TFs'){
  // Ruling 1: TF_D1 is appended to ENUM_MODE_TFs, so each existing timeframe input gains exactly that one choice.
  assert.deepEqual(now,{...was,enum_choices:{...was.enum_choices,TF_D1:1440}},'B49a timeframe input gains exactly TF_D1: '+name);
  assert.deepEqual(Object.keys(now.enum_choices),[...Object.keys(was.enum_choices),'TF_D1'],'TF_D1 is appended last: '+name);
 }
 else assert.deepEqual(now,was,'B49a input unchanged: '+name);
}
// The header's new inputs are exactly NEW_INPUTS, appended after B49a's; the entrypoint's own inputs are B49a's.
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (appended to the header, after Ledger_Mode)');
for(const name of NEW_INPUTS){
 const [declaration,type,def]=NEW_DEFAULTS[name],d=schema.inputs[name];
 assert.deepEqual([d.declaration,d.type,d.default_expression],[declaration,type,def],'B50 input definition: '+name);
}
assert.deepEqual(schema.inputs.Single_Time_Stop_TF.enum_choices,schema.inputs.ATR_TF_.enum_choices,'the time stop uses the same ladder');
assert.deepEqual(schema.inputs.Engine_Mode.enum_choices,{Engine_Grid:0,Engine_Single:1});
assert.deepEqual(schema.inputs.Clock_Mode.enum_choices,{Clock_Server:0,Clock_NewYork:1});
assert.deepEqual(schema.inputs.Server_Clock_Model.enum_choices,{ServerClock_NYClose:0,ServerClock_Fixed:1,ServerClock_EUDST:2});
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B49A_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
// TF2TF maps the new choice to PERIOD_D1.
const header=read('GOAT_Inputs_Definitions.mqh').toString('utf8');
assert.match(header,/\r\n    case TF_H4:   return PERIOD_H4;\r\n    case TF_D1:   return PERIOD_D1; \/\/ B50/,'TF2TF: TF_D1 is PERIOD_D1');
checks++;

// 6. Until the A4 assembly the build identity stays B49a's; A4 moves it (and adds IDENTITY_LINES and identity checks).
const mainText=read('GOAT V1.49.mq5').toString('utf8');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_ID "'+b49a.build_id+'"').length,1,'the build ID is B49a\'s until A4');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_MARKER "'+b49a.build_marker+'"').length,1,'the marker is B49a\'s until A4');
checks++;

console.log('b50_no_drift: '+checks+' checks passed (B49a '+B49A_SOURCE+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+')');
