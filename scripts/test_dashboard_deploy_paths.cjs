// Execute production path/deployment blocks with file, chart and UI stubs.
// This verifies decisions and constructed paths, not native MT5 template loading.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../Dashboard.mqh'),'utf8').replace(/\r\n/g,'\n');
function between(start,end) {
 const a=source.indexOf(start);assert.ok(a>=0,start);
 const b=source.indexOf(end,a+start.length);assert.ok(b>a,end);
 return source.slice(a+start.length,b);
}
function enabled(text) {
 const stack=[];let active=true;
 return text.split('\n').filter(line=>{
  if(/^\s*#ifdef/.test(line)){stack.push(active);active=active&&line.includes('GOAT_DASH_AI_LAUNCH_POLICY_V147');return false;}
  if(/^\s*#else/.test(line)){active=stack.at(-1)&&!active;return false;}
  if(/^\s*#endif/.test(line)){active=stack.pop();return false;}
  return active;
 }).join('\n');
}
function js(text) {
 return enabled(text).replace(/\b(?:const )?(?:string|int|long|bool|ENUM_TIMEFRAMES) /g,'let ')
  .replace(/\(int\)/g,'').replace(/\bvar\b/g,'inputName');
}
const flags=between('void           SetFlags(', '   virtual bool   OnEvent');
const flagsBody=flags.slice(flags.indexOf('{')+1,flags.lastIndexOf('}'));
const folder=between('string FolderOf(const string p) {','\n');
const folderBody=folder.slice(0,folder.lastIndexOf('}'));
const common=between('string GoatDashboardCommonSetPath(const string path)\n{','\n}\n');
const build=between('string CGOATDashboard::BuildTemplate(const string eaName,const string eaPath,const string setFile)\n{','\n}\n');
const save=between('bool CGOATDashboard::SaveTemplateAndCopy(const string tplName,const string tplText)\n{','\n}\n');
const activate=between('   void DoActivate(int idx)\n   {','   void CalcDayWeekStart');
const activateBody=activate.slice(0,activate.lastIndexOf('}'));
const pickerFolder=source.match(/SetFolder=FolderOf\(picked\[0\]\);/);assert.ok(pickerFolder);
assert.ok(!between('   int LoadSetFiles()', '//––––– activate row').includes('EA_Path='));
const savedFolder=source.match(/SetFolder=FolderOf\(g_sets\[0\]\.path\);/);assert.ok(savedFolder);
const commonRoot='C:\\Users\\Fixture\\Common',terminal='C:\\Demo 01';
const folderPath=commonRoot+'\\Files\\GOAT Portfolios\\Frozen 33';
const filename='GOAT V1.47 EURUSD,M1.set',setPath=folderPath+'\\'+filename;
const exactExpert='Experts\\GOAT Experiment\\GOAT V1.47.ex5';
function harness({program='C:\\Demo 01\\MQL5\\'+exactExpert,cid=0,magic=0,quiet=true,copyOkay=true}={}) {
 const calls=[],writes=[],copies=[],writePaths=[];let cursor=0;const input=['EA_Desc=Fixture','Mode_Bias=1'];
 const ctx={EA_Path:'',SetFolder:'',Key_:'',EA_Name_:'',Server_:'',Version:0,Font_Size:0,ChartId:0,
  _Key_:'GOAT',_EA_Name_:'GOAT V1.47',_Server_:'Demo',_Version_:'1.47',_Font_Size_:8,Id:1,
  MQL_PROGRAM_PATH:1,TERMINAL_COMMONDATA_PATH:2,TERMINAL_DATA_PATH:3,
  FILE_READ:1,FILE_WRITE:2,FILE_TXT:4,FILE_ANSI:8,FILE_COMMON:16,INVALID_HANDLE:-1,
  MB_OK:0,MB_ICONWARNING:0,m_agent_setup_quiet:quiet,m_ai_launch_mode:0,m_ai_launch_threshold:50,m_ai_launch_protocol:2,
  g_sets:[{path:setPath,name:filename,sym:'EURUSD',cid,magic}],btn_Action:[],picked:[setPath],
  MQLInfoString:()=>program,TerminalInfoString:kind=>kind===2?commonRoot:terminal,
  StringFind:(s,find)=>s.indexOf(find),StringSubstr:(s,start,length)=>length===undefined?s.slice(start):s.slice(start,start+length),
  StringLen:s=>s.length,StringToDouble:Number,ArraySize:a=>a.length,EndsWith:(s,suffix)=>s.endsWith(suffix),StringTrim:s=>s.trim(),
  Print:()=>calls.push('print'),PrintFormat:()=>{},MessageBox:()=>calls.push('message'),GetLastError:()=>0,Sleep:()=>{},
  PrepareAILaunchPolicy:()=>{calls.push('prepare');return true;},TF:()=>1,
  AppendAILaunchAudit:()=>{},UpdateAILaunchControls:()=>{},
  GoatApplyAILaunchPolicy:text=>text,
  FileOpen:(p,mode)=>{calls.push(mode&2?'writeOpen':'readOpen');if(mode&2)writePaths.push(p);else cursor=0;return mode&2?12:11;},
  FileIsEnding:()=>cursor>=input.length,FileReadString:()=>input[cursor++],FileClose:()=>{},
  FileWriteString:(h,text)=>{writes.push(text);return text.length;},FileDelete:p=>{calls.push('delete:'+p);return true;},
  CopyFileW:(from,to)=>{copies.push([from,to]);return copyOkay?1:0;},
  ApplyTemplate:()=>{calls.push('chart');return true;}};
 vm.createContext(ctx);
 vm.runInContext('function FolderOf(p){'+js(folderBody)+'}\n'+
  'function GoatDashboardCommonSetPath(path){'+js(common)+'}\n'+
  'function BuildTemplate(eaName,eaPath,setFile){'+js(build)+'}\n'+
  'function SaveTemplateAndCopy(tplName,tplText){'+js(save)+'}\n'+
  'function Activate(idx){'+js(activateBody).replace(/StringReplace\(tplName,"\.set","\.tpl"\)/,'tplName=tplName.split(".set").join(".tpl")')+'}',ctx);
 return {ctx,calls,writes,copies,writePaths,initialize(flow='saved') {
  vm.runInContext(js(flagsBody),ctx);
  vm.runInContext(flow==='saved'?savedFolder[0]:pickerFolder[0],ctx);
 },activate(){vm.runInContext('Activate(0)',ctx);}};
}
let passed=0;
for(const flow of ['saved','picker']) {
 const h=harness(flow==='picker'?{program:exactExpert}:{});h.initialize(flow);assert.equal(h.ctx.EA_Path,exactExpert);assert.equal(h.ctx.SetFolder,folderPath);
 h.activate();assert.deepEqual(h.calls.filter(c=>c==='chart'),['chart']);
 assert.ok(h.writes[0].includes('path='+exactExpert+'\r\n'));assert.ok(h.writes[0].includes('EA_Desc=Fixture'));
 const tpl=filename.replace('.set','.tpl');
 assert.deepEqual(h.copies,[[ '\\\\?\\'+folderPath+'\\'+tpl,'\\\\?\\'+terminal+'\\MQL5\\Profiles\\Templates\\'+tpl ]]);
 assert.deepEqual(h.writePaths,['GOAT Portfolios\\Frozen 33\\'+tpl]);
 assert.equal('\\\\?\\'+commonRoot+'\\Files\\'+h.writePaths[0],h.copies[0][0]);
 assert.ok(h.calls.includes('delete:GOAT Portfolios\\Frozen 33\\'+tpl));passed++;
}
for(const program of ['', 'C:\\Other\\GOAT V1.47.ex5','C:\\MQL5\\Experts\\Other.ex5','C:\\MQL5\\Experts\\']) {
 const h=harness({program});h.initialize();h.activate();
 assert.deepEqual(h.calls,['print']);assert.equal(h.writes.length,0);assert.equal(h.copies.length,0);passed++;
}
for(const identity of [{cid:123,magic:0},{cid:0,magic:456},{cid:123,magic:456}]) {
 const h=harness(identity);h.initialize();h.activate();
 assert.deepEqual(h.calls,[]);assert.equal(h.copies.length,0);assert.equal(h.ctx.g_sets[0].cid,identity.cid);passed++;
}
for(const badFolder of ['C:\\Outside\\Portfolio',folderPath+'\\..\\Escape','']) {
 const h=harness();h.initialize();h.ctx.SetFolder=badFolder;h.activate();
 assert.ok(!h.calls.includes('writeOpen'));assert.ok(!h.calls.includes('chart'));assert.equal(h.copies.length,0);passed++;
}
const failed=harness({copyOkay:false});failed.initialize();failed.activate();
assert.equal(failed.copies.length,1);assert.ok(!failed.calls.includes('chart'));passed++;
console.log(JSON.stringify({passed,productionExtracted:true,nativeTemplateAndIoVerified:false}));
