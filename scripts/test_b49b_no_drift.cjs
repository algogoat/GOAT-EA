// B49b no-drift guard (Track A, goatai#2587 6433828681 / Claude-Mac 6433854745). B49b = B49a + the B49a follow-ups
// (PR-0) + the rest of the B49 safety work (F7 remainder, F1 full, F3, F4, F5, F6, F8), each in its own reviewed PR into
// claude-pc/b49b. Against B49a (source 693cad0, the admitted candidate's sourceCommit, whose source hashes are committed
// in candidate-builds/beta17-B49a/identity.json):
// - every file of B49a's compile closure outside CHANGED is byte-identical to B49a;
// - in the CHANGED files, every line added or replaced since B49a carries the marker "B49b" or sits inside a
//   "// B49b:begin <item>" ... "// B49b:end <item>" block, so nothing changes unmarked; pure deletions are refused,
//   and every B49a line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure only gains the files in ADDED;
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json is exactly what studio_input_schema.discover reads from this header (test_studio_optimization_inputs);
//   inputs are append-only: B49a's inputs keep their type, default and enum choices, and new ones follow Ledger_Mode
//   (after B50-alpha's, once B49b is rebased onto it: Claude-Mac 6433854745 ruling 6);
// - until the assembly, the build is still named B49a (ID and marker unchanged); the assembly adds B49b's identity.
// Replaces test_b49a_no_drift.cjs (B49a's guard against B47), which pinned the tree to B49a by design.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B49b change is marked, listed and reviewable. A marked line
// or block can still change behaviour. Neutrality with the new inputs at their defaults is proven only by the tester
// parity on Banker (flags off, B49b against its baseline byte-identical), and the live-only parts by their demo drills.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B49A_SOURCE='693cad05dca3ca7d5c9549465c8973ba4d737d8a';
// Each item PR adds the files it changes or adds, so the review sees the list grow.
// PR-0: the entrypoint (the start-distance refusal, the adopted TP). PR-1: Fix_MoneyVolume (the header's input and
// WriteSet, the child audit, the Studio readback and type). One line: test_studio_start_protocol_candidate reads it.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATPortfolioChildAudit.mqh','GOATStudioSettingCompare.mqh','GOATStudioSettingTypes.mqh','Dashboard.mqh'];
const ADDED=[];
// Every B49a line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 'GOAT V1.49.mq5':[
  'if((RSI_Mode!=RSI_Disabled))','if(EMA_Sample.CheckTF(EMA_TF)) {','if(ADX_Sample.CheckTF(ADX_TF)) {','if(BB_Sample.CheckTF(BB_TF)) {',   // PR-1 (F7 SIG-02): each
  'if(MACD_Sample.CheckTF(MACD_TF)) {','if(RSI2_Sample.CheckTF(RSI2_TF)) {',
  'if(Sequence_New_News&&Sequence_New_Bias_B)','if(Sequence_New_News&&Sequence_New_Bias_S)',   // PR-5 (F5, GOAT-EA#271 P1): the bias pre-gate's side
  'if(!Sequence_New_Bias_B&&!LastBuySignal) {Sequence_Skipped_Bias_B++; GoatGateLog("VETO",OP_BUY);} // B44 item 4: log only',
  'if(!Sequence_New_Bias_S&&!LastSellSignal) {Sequence_Skipped_Bias_S++; GoatGateLog("VETO",OP_SELL);} // B44 item 4: log only',
  'closeErrors++;',   // PR-3 (F3 D4): a failed live close is logged
  'if(!Trade.PositionModify(TradeLevels[i].ticket,Level_SL_,Level_TP_)) TPmodifyErrors++; TPSLmodifieds++;',   // PR-3 (F3 D5): a failed live modify is logged
  '{TSLmodifyErrors++; PrintFormat("TSL BUY modify failed: ticket=%I64u newSL=%.6f ret=%d (%s)",TradeLevels[i].ticket,DoubleToString(SL,Digits()),Trade.ResultRetcode(),Trade.ResultRetcodeDescription());} TSLmodifieds++;',   // PR-3: %.6f takes the double
  'CopyBuffer(RSI_handle,0,shift+0,2,RSI_Buf);','for(int i=0;i<EMA_Count;i++)   CopyBuffer(EMA_handles[i],0,shift-0,1,EMAs[i].Buf);',   // Codex GOAT-EA#270 P2: one copy, in the check
  'CopyBuffer(ADX_handle,MAIN_LINE   ,shift+0,1,ADX_Main_Buf); ADX_Main_Buf[0] = NormalizeDouble(ADX_Main_Buf[0],_Digits);',
  'CopyBuffer(ADX_handle,PLUSDI_LINE ,shift+0,1,ADX_PLS_Buf);  ADX_PLS_Buf[0]  = NormalizeDouble(ADX_PLS_Buf[0],_Digits);',
  'CopyBuffer(ADX_handle,MINUSDI_LINE,shift+0,1,ADX_MNS_Buf);  ADX_MNS_Buf[0]  = NormalizeDouble(ADX_MNS_Buf[0],_Digits);',
  'CopyBuffer(BB_handle,BASE_LINE ,shift,2,BB_Mi_Buf);  BB_Mi_Buf[0] = NormalizeDouble(BB_Mi_Buf[0],_Digits);',
  'CopyBuffer(BB_handle,UPPER_BAND,shift,2,BB_Hi_Buf);  BB_Hi_Buf[0] = NormalizeDouble(BB_Hi_Buf[0],_Digits);',
  'CopyBuffer(BB_handle,LOWER_BAND,shift,2,BB_Lo_Buf);  BB_Lo_Buf[0] = NormalizeDouble(BB_Lo_Buf[0],_Digits);',
  'CopyBuffer(MACD_handle,1           ,shift+0,1,MACD_Clr_Buf);','CopyBuffer(RSI2_handle,0,shift+0,2,RSI2_Buf);',
  'if(SymbolInfoInteger(Symbol(),SYMBOL_SPREAD)>MaxSP) return 0;',   // PR-6 (F6): Max_Spread_Points tightens the fixed MaxSP when set
  'else {Print(Desc_lvl,": Price=",DoubleToString(Level_New,_Digits)," Lots=",DoubleToString(Lots_Order,2),"/",DoubleToString(MathMax(Lots_Calc,Lots_Delayed),2)',   // PR-6 (Mac #281 P2): no per-tick line for a pre-trade refusal
  'if(SymbolInfoInteger(Symbol(),SYMBOL_SPREAD)>=MaxSP)  ObjectSetText("05","Spread Filter Active, Sp="  +(string)SymbolInfoInteger(Symbol(),SYMBOL_SPREAD),Font_Size,"NULL",clrMagenta);',   // PR-6 (Mac #281 P3): the label shows the effective cap
  'DashboardPortfolioCommandIdApplied=command_id;','DashboardPortfolioCommandIdApplied=command_id;','close_errors++;','close_errors++;',   // PR-3b (both close commands, both bus helpers) (F3 DASH-04): applied only once flat; a failed bus close is logged
 ],
 'Dashboard.mqh':[
  'if(!m_risk_policy_armed || m_risk_policy_breached) return;','if(m_portfolio_command_pending) return;',   // PR-3b (F3 RISK-01): a breach is followed until flat
 ],
};
const NEW_INPUTS=['Fix_MoneyVolume','Gate_Recheck','Fix_ClosePath','Max_Spread_Points','Min_Margin_Level_PC','Fix_Clock'];   // PR-1 (F7), PR-5 (F5), PR-3 (F3), PR-6 (F6), PR-4 (F4/R2)
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const b49a=JSON.parse(read('candidate-builds/beta17-B49a/identity.json'));
let checks=0;

// 1. The baseline really is B49a: its commit's blobs (checked out as the tree would be) hash to B49a's identity.
assert.equal(b49a.build_id,'V1.49-BETA17-49');
for(const [f,h] of Object.entries(b49a.sources)){
 const blob=git(['show',B49A_SOURCE+':'+f]);
 assert.equal(sha(checkedOut(f,blob)),h,'B49a source '+B49A_SOURCE.slice(0,7)+' is the identity of '+f);
}
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
assert.deepEqual(closure(),[...b49aMql,...ADDED].sort(),'the compile closure is B49a\'s plus ADDED');checks++;

// 3. Outside CHANGED (and the new files), every B49a source is byte-identical.
for(const [f,h] of Object.entries(b49a.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B49a: '+f);
for(const f of CHANGED) assert.notEqual(sha(read(f)),b49a.sources[f],'CHANGED lists only files that changed: '+f);
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B49b:begin (\S+)/),end=line.match(/\/\/ B49b:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B49b block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B49b:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B49b block '+open);
 return inBlock;
}
for(const f of [...CHANGED,...ADDED]){
 const lines=read(f).toString('utf8').replace(/^﻿/,'').split(/\r\n/);
 const inBlock=markedBlocks(lines);
 if(ADDED.includes(f)){
  // A new file is B49b's throughout: it opens with a B49b block or every code line is marked.
  lines.forEach((text,i)=>assert.ok(!text.trim()||/B49b/.test(text)||inBlock[i],f+':'+(i+1)+' new without a B49b marker: '+text.trim()));
  continue;
 }
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
   assert.ok(/B49b/.test(text)||inBlock[n-1],f+':'+n+' changed since B49a without a B49b marker: '+text.trim());
  }
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B49a lines removed are exactly REMOVED');
}
checks++;

// 5. The input contract follows the tree, append-only against B49a.
const deps=JSON.parse(read('controller/contracts/v149/dependencies.json').toString('utf8').replace(/^﻿/,''));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
const schema=JSON.parse(read('controller/contracts/v149/inputs.json').toString('utf8').replace(/^﻿/,''));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(git(['show',B49A_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8').replace(/^﻿/,''));
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.equal(beforeNames[beforeNames.length-1],'Ledger_Mode','B49a\'s last input');
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B49a\'s inputs keep their order');
for(const name of beforeNames) assert.deepEqual(schema.inputs[name],before.inputs[name],'B49a input unchanged: '+name);
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (appended to the header)');
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B49A_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
checks++;

// 6. Until the assembly the build keeps B49a's name: the ID and marker lines are B49a's, once each.
const mainText=read('GOAT V1.49.mq5').toString('utf8');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_ID "'+b49a.build_id+'"').length,1,'the build ID is still B49a\'s');
assert.equal(mainText.split('\r\n').filter(l=>l==='#define   GOAT_BUILD_MARKER "'+b49a.build_marker+'"').length,1,'the marker is still B49a\'s');
assert.equal((mainText.match(/#define\s+GOAT_BUILD_(?:ID|MARKER)\b/g)||[]).length,2,'one build ID and one marker');
checks++;

console.log('b49b_no_drift: '+checks+' checks passed (B49a '+B49A_SOURCE.slice(0,7)+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+')');
