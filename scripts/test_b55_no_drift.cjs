// B55 no-drift guard (docs/b55/BREAKOUT_SEQUENCE_SPEC.md section 6.3). B55 = B54 (the research build V1.49-BETA17-54, merge
// a8c6766 of GOAT-EA#306; its source hashes are committed in candidate-builds/beta17-B54/identity.json) plus a breakout as a
// grid sequence's first order, each part in its own reviewed PR. PR A0 (gate 0, section 6.2) declares the one input
// (BRK_Start_Seq), WriteSet's line, the Studio type and default and the child audit's name, and adds the entrypoint's
// b55-init block (spec 3.7) with line 5128 narrowed: OnInit refusals only, the switch itself refused as not built; no
// trading logic reads the input yet. Against B54:
// - every file of B54's compile closure outside CHANGED is byte-identical to B54;
// - in the CHANGED files, every line added or replaced since B54 carries the marker "B55" or sits inside a
//   "// B55:begin <item>" ... "// B55:end <item>" block, so nothing changes unmarked; pure deletions are refused, and every
//   B54 line removed inside a changed hunk is listed verbatim in REMOVED;
// - the compile closure gains no file (ADDED is empty);
// - the controller's v149 input contract follows the tree: dependencies.json pins this header and entrypoint, and
//   inputs.json was read from this header (test_studio_optimization_inputs and test_b55_gate0.py prove it is exactly what
//   discover reads); inputs are append-only: B54's 159 header inputs keep their order, type, default and enum choices,
//   and the new ones are exactly NEW_INPUTS, in order, at the very end, in their own group, the header's last. That is
//   this guard's one explicit allowance;
// - each later B55 PR adds the files and REMOVED lines it changes (section 6.1: PR A replaces line 5070, the ATR handles;
//   the assembly replaces B54's two identity defines), so the review sees the lists grow. A0 keeps B54's build ID and marker.
// test_b54_no_drift.cjs now proves B54's own commit (as test_b51_no_drift.cjs proves B53's), so the chain
// B49a -> B50 -> B53 -> B54 -> tree is checked end to end.
// VISIBILITY, NOT NEUTRALITY: this guard proves that every B55 change is marked, listed and reviewable. Neutrality with the
// switch off is proven by gate 0 (scripts/test_b55_gate0.cjs and controller/test_b55_gate0.py, on every pool SET) and,
// later, by scripts/test_b55_parity.cjs and the native Banker parity on every pool file (spec 6.3; Claude-Mac goatai#2750
// 6789761790).
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B54_SOURCE='a8c6766243ff577bdcfc90495a6de33ce0797c88';
// Each item PR adds the files it changes, so the review sees the list grow.
const CHANGED=['GOAT V1.49.mq5','GOAT_Inputs_Definitions.mqh','GOATStudioSettingTypes.mqh','GOATPortfolioChildAudit.mqh',
 'Dashboard.mqh'];   // dash-ack-once, Codex on GOAT-EA#330: each publish clears the child's command id first and writes it last
const ADDED=[];
// Every B54 line a changed hunk removes, verbatim (trimmed), per file.
const REMOVED={
 // A0 (spec 3.7): line 5128 gains "&& !BRK_Start_Seq" (and its B55 note), so B54's line is replaced. Alert and code stay.
 'GOAT V1.49.mq5':[
  'if(BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single) {Alert("Initialization Failed: BRK_Mode needs the single-trade engine (Engine_Mode=Engine_Single)."); return INIT_PARAMETERS_INCORRECT;}',
  // dash-ack-once (GOAT-EA#328): four blank lines each replaced by one marked call, so no line above OnInit's rules moves
  // (gate 0 compares B54's refusal text, cited lines included): in DashboardBusAckCommand, DashboardBusAckCloseCommand,
  // DashboardBusProcessCommands, and after OnInit's policy restore.
  '','','','',
  // Codex on GOAT-EA#330: the poll reads the command id again after the fields and applies only if it is unchanged.
  'DashboardBusApplyCommand(command_id,command_type,command_value,expires_at);',
 ],
 // Codex on GOAT-EA#330: at each of the four publish sites the id's first write (the value) becomes a clear (0.0), and
 // the value is written after the other three fields.
 'Dashboard.mqh':Array(4).fill('GlobalVariableSet(GoatChildGVName(g_sets[idx].magic,g_sets[idx].sym,GOAT_GV_FIELD_CMD_ID),(double)m_portfolio_command_id);'),
};
// The B55 input (spec section 3.1), appended at the very end.
const NEW_INPUTS=['BRK_Start_Seq'];
const NEW_DEFAULTS={BRK_Start_Seq:['sinput','bool','false']};
const GROUP='====BREAKOUT SEQUENCE START (B55)====';
// A0 keeps B54's identity lines (the assembly replaces them and lists them in REMOVED): each appears exactly once.
const B54_IDENTITY_LINES=['#define   GOAT_BUILD_ID "V1.49-BETA17-54"','#define   GOAT_BUILD_MARKER "B54"'];
const read=f=>fs.readFileSync(path.join(ROOT,f));
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const git=args=>execFileSync('git',args,{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']});
// .mq5/.mqh check out as CRLF (.gitattributes), so a blob hashes as the tree would.
const checkedOut=(name,data)=>/\.mq[5h]$/.test(name)?Buffer.from(data.toString('utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'),'utf8'):data;
const bom=text=>text.replace(/^\uFEFF/,'');
git(['merge-base','--is-ancestor',B54_SOURCE,'HEAD']);   // throws unless the working tree descends from B54
const b54=JSON.parse(bom(git(['show',B54_SOURCE+':candidate-builds/beta17-B54/identity.json']).toString('utf8')));
let checks=0;

// 1. The baseline really is B54: its commit's blobs (checked out as the tree would be) hash to B54's identity, which the
// tree keeps unchanged.
for(const [f,h] of Object.entries(b54.sources)) assert.equal(sha(checkedOut(f,git(['show',B54_SOURCE+':'+f]))),h,'B54 source '+B54_SOURCE.slice(0,8)+' is the identity of '+f);
assert.equal(b54.build_id+' '+b54.build_marker,'V1.49-BETA17-54 B54');
assert.deepEqual(JSON.parse(bom(read('candidate-builds/beta17-B54/identity.json').toString('utf8'))),b54,'B54\'s identity file is unchanged');
checks++;

// 2. The compile closure: B54's files plus ADDED, nothing else.
function closure(){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  const text=read(f).toString('utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  for(const m of text.matchAll(/^\s*#include\s+"([^"]+)"/gm)){const inc=m[1].replace(/\\/g,'/');if(fs.existsSync(path.join(ROOT,inc)))todo.push(inc);}
 }
 return [...seen].sort();
}
const b54Mql=Object.keys(b54.sources).filter(f=>/\.mq[5h]$/.test(f)).sort();
assert.deepEqual(closure(),[...b54Mql,...ADDED].sort(),'the compile closure is B54\'s plus ADDED');
checks++;

// 3. Outside CHANGED, every B54 source is byte-identical; every CHANGED file did change and keeps BOM + CRLF.
for(const [f,h] of Object.entries(b54.sources)) if(!CHANGED.includes(f)) assert.equal(sha(read(f)),h,'unchanged since B54: '+f);
for(const f of CHANGED){
 assert.notEqual(sha(read(f)),b54.sources[f],'CHANGED lists only files that changed: '+f);
 const buf=read(f);assert.deepEqual([...buf.subarray(0,3)],[0xef,0xbb,0xbf],f+': UTF-8 with BOM');
 assert.ok(!/(^|[^\r])\n/.test(buf.toString('utf8')),f+': CRLF only');
}
checks++;

// 4. Every changed line is marked.
function markedBlocks(lines){
 const inBlock=new Array(lines.length).fill(false);let open=null;
 lines.forEach((line,i)=>{
  const begin=line.match(/\/\/ B55:begin (\S+)/),end=line.match(/\/\/ B55:end (\S+)/);
  if(begin){assert.equal(open,null,'nested B55 block at line '+(i+1));open=begin[1];}
  if(open!==null)inBlock[i]=true;
  if(end){assert.equal(end[1],open,'B55:end '+end[1]+' closes '+open+' at line '+(i+1));open=null;}
 });
 assert.equal(open,null,'unclosed B55 block '+open);
 return inBlock;
}
for(const f of CHANGED){
 const lines=bom(read(f).toString('utf8')).split(/\r\n/);
 const inBlock=markedBlocks(lines);
 const diff=git(['diff','--no-color','--no-ext-diff','-U0',B54_SOURCE,'--',f]).toString('utf8').split('\n');
 let newLine=0,hunk=null;const hunks=[],removedLines=[];
 for(const line of diff){
  const h=line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(h){hunk={added:[],removed:0};hunks.push(hunk);newLine=Number(h[1]);continue;}
  if(!hunk||line.startsWith('+++')||line.startsWith('---'))continue;
  if(line.startsWith('+')){hunk.added.push(newLine);newLine++;}
  else if(line.startsWith('-')){hunk.removed++;removedLines.push(line.slice(1).replace(/\r$/,'').trim());}
 }
 assert.ok(hunks.length>0,f+' differs from B54');
 for(const {added,removed} of hunks){
  assert.ok(added.length>0,f+': a pure deletion of '+removed+' B54 line(s) is unmarked');
  for(const n of added){const text=lines[n-1];assert.ok(/B55/.test(text)||inBlock[n-1],f+':'+n+' changed since B54 without a B55 marker: '+text.trim());}
 }
 assert.deepEqual([...removedLines].sort(),[...(REMOVED[f]||[])].sort(),f+': the B54 lines removed are exactly REMOVED');
}
{const main=read('GOAT V1.49.mq5').toString('utf8').split('\r\n');
 for(const l of B54_IDENTITY_LINES) assert.equal(main.filter(x=>x===l).length,1,'A0 keeps B54\'s identity line, once: '+l);
 // The replaced line keeps B54's alert and code (spec 3.1: B54's refusal for every SET that does not ask for a sequence).
 const narrowed=main.filter(x=>x.includes('BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single'));
 assert.equal(narrowed.length,1,'line 5128, once');
 const tail=REMOVED['GOAT V1.49.mq5'][0].slice(REMOVED['GOAT V1.49.mq5'][0].indexOf('{Alert('));
 assert.ok(narrowed[0].trim().startsWith('if(BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single && !BRK_Start_Seq) '+tail),'line 5128: B54\'s alert and code, narrowed by the switch only');
 checks++;}
for(const f of Object.keys(REMOVED)) assert.ok(CHANGED.includes(f),'REMOVED names only CHANGED files: '+f);
checks++;

// 5. The input contract follows the tree, append-only against B54, with exactly NEW_INPUTS at the end in their own group.
const deps=JSON.parse(bom(read('controller/contracts/v149/dependencies.json').toString('utf8')));
assert.equal(deps.header_sha256,sha(read('GOAT_Inputs_Definitions.mqh')),'dependencies.json pins this header');
assert.equal(deps.main_sha256,sha(read('GOAT V1.49.mq5')),'dependencies.json pins this entrypoint');
const schema=JSON.parse(bom(read('controller/contracts/v149/inputs.json').toString('utf8')));
assert.equal(schema.source_sha256,deps.header_sha256,'inputs.json was read from this header');
const before=JSON.parse(bom(git(['show',B54_SOURCE+':controller/contracts/v149/inputs.json']).toString('utf8')));
assert.equal(before.source_sha256,b54.sources['GOAT_Inputs_Definitions.mqh'],'the baseline schema was read from B54\'s header');
const names=Object.keys(schema.inputs),beforeNames=Object.keys(before.inputs);
assert.equal(beforeNames.length,159,'B54 declares 159 header inputs');assert.equal(beforeNames.at(-1),'ORB_Max_Range_ATR');
assert.deepEqual(names.slice(0,beforeNames.length),beforeNames,'B54\'s inputs keep their order');
for(const name of beforeNames) assert.deepEqual(schema.inputs[name],before.inputs[name],'B54 input unchanged: '+name);
assert.deepEqual(schema.defines,before.defines,'the defines are B54\'s');
// The one allowance: the new inputs are exactly NEW_INPUTS, appended at the very end, as the spec declares them.
assert.deepEqual(names.slice(beforeNames.length),NEW_INPUTS,'new inputs (at the end of the header)');
for(const name of NEW_INPUTS){
 const [declaration,type,def]=NEW_DEFAULTS[name],d=schema.inputs[name];
 assert.deepEqual([d.declaration,d.type,d.default_expression,d.optimizable,d.enum_choices],[declaration,type,def,false,null],'B55 input definition (an sinput, never an axis): '+name);
}
// They sit in their own input group, the header's last; no enum is declared or extended (the header's enum blocks are B54's).
const header=read('GOAT_Inputs_Definitions.mqh').toString('utf8');
const groups=[...header.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/^input\s+group\s+"([^"]*)"/gm)].map(m=>m[1]);
assert.equal(groups.at(-1),GROUP,'the B55 group is the last');
assert.equal(groups.filter(g=>g===GROUP).length,1,'once');
const enums=text=>[...text.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/^\s*enum\s+\w+[\s\S]*?\}/gm)].map(m=>m[0].replace(/\s+/g,' '));
assert.deepEqual(enums(header),enums(checkedOut('GOAT_Inputs_Definitions.mqh',git(['show',B54_SOURCE+':GOAT_Inputs_Definitions.mqh'])).toString('utf8')),'no enum added or changed');
const declared=text=>[...text.matchAll(/^\s*(?:input|sinput)\s+\w+\s+(\w+)/gm)].map(m=>m[1]);
assert.deepEqual(declared(read('GOAT V1.49.mq5').toString('utf8')),declared(git(['show',B54_SOURCE+':GOAT V1.49.mq5']).toString('utf8')),'no input added to the entrypoint');
checks++;

console.log('b55_no_drift: '+checks+' checks passed (B54 '+B54_SOURCE.slice(0,8)+', changed: '+CHANGED.join(', ')+(ADDED.length?'; added: '+ADDED.join(', '):'')+'; new inputs: '+NEW_INPUTS.join(', ')+')');
