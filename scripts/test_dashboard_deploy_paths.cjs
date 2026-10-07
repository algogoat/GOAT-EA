// Execute the production dashboard path blocks with file, chart and UI stubs (rewritten for beta.25,
// goatai#1885 6033450916). The template deploy path (DoActivate, BuildTemplate, SaveTemplateAndCopy,
// ApplyTemplate) is deleted: this checks what remains, the expert path and SET folder the dashboard
// still derives, and that no deploy, chart-open or template-copy path survives. Adoption is covered by
// test_profile_staged_adoption.cjs. Not native MT5 evidence.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../Dashboard.mqh'),'utf8').replace(/\r\n/g,'\n');
function between(start,end) {
 const a=source.indexOf(start);assert.ok(a>=0,start);
 const b=source.indexOf(end,a+start.length);assert.ok(b>a,end);
 return source.slice(a+start.length,b);
}
const js=text=>text.replace(/\b(?:const )?(?:string|int|long|bool|ENUM_TIMEFRAMES) /g,'let ').replace(/\(int\)/g,'');
const flags=between('void           SetFlags(', '   virtual bool   OnEvent');
const flagsBody=flags.slice(flags.indexOf('{')+1,flags.lastIndexOf('}'));
const folder=between('string FolderOf(const string p) {','\n');
const folderBody=folder.slice(0,folder.lastIndexOf('}'));
const common=between('string GoatDashboardCommonSetPath(const string path)\n{','\n}\n');
const pickerFolder=source.match(/SetFolder=FolderOf\(picked\[0\]\);/);assert.ok(pickerFolder);
assert.ok(!between('   int LoadSetFiles()', '   void CalcDayWeekStart()').includes('EA_Path='));
const savedFolder=source.match(/SetFolder=FolderOf\(g_sets\[0\]\.path\);/);assert.ok(savedFolder);
const commonRoot='C:\\Users\\Fixture\\Common',folderPath=commonRoot+'\\Files\\GOAT Portfolios\\Frozen 33';
const exactExpert='Experts\\GOAT Experiment\\GOAT V1.47.ex5';
function harness(program='C:\\Demo 01\\MQL5\\'+exactExpert){
 const ctx={EA_Path:'',SetFolder:'',Key_:'',EA_Name_:'',Server_:'',Version:0,Font_Size:0,ChartId:0,
  _Key_:'GOAT',_EA_Name_:'GOAT V1.47',_Server_:'Demo',_Version_:'1.47',_Font_Size_:8,Id:1,MQL_PROGRAM_PATH:1,TERMINAL_COMMONDATA_PATH:2,
  g_sets:[{path:folderPath+'\\GOAT V1.47 EURUSD,M1.set'}],picked:[folderPath+'\\GOAT V1.47 EURUSD,M1.set'],
  MQLInfoString:()=>program,TerminalInfoString:()=>commonRoot,StringFind:(s,f)=>s.indexOf(f),
  StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),StringLen:s=>s.length,StringToDouble:Number};
 vm.createContext(ctx);
 vm.runInContext('function FolderOf(p){'+js(folderBody)+'}\nfunction GoatDashboardCommonSetPath(path){'+js(common)+'}',ctx);
 return ctx;
}
let passed=0;
for(const flow of ['saved','picker']){
 const ctx=harness(flow==='picker'?exactExpert:undefined);vm.runInContext(js(flagsBody),ctx);
 vm.runInContext(flow==='saved'?savedFolder[0]:pickerFolder[0],ctx);
 assert.equal(ctx.EA_Path,exactExpert);assert.equal(ctx.SetFolder,folderPath);
 assert.equal(vm.runInContext('GoatDashboardCommonSetPath(SetFolder+"\\\\x.set")',ctx),'GOAT Portfolios\\Frozen 33\\x.set');passed++;
}
for(const bad of ['C:\\Outside\\Portfolio\\x.set',folderPath+'\\..\\Escape.set','','\\lead.set']){
 const ctx=harness();assert.equal(vm.runInContext('GoatDashboardCommonSetPath('+JSON.stringify(bad)+')',ctx),'',bad);passed++;
}
// The deploy path is gone, not dormant.
for(const gone of ['void DoActivate(','BuildTemplate(','SaveTemplateAndCopy(','DeleteCopiedTemplate(','ApplyTemplate(','NewSingleInstance(','DeployAll(',
                   'AgentDeployRow(','ChartOpen(','ChartApplyTemplate','CopyFileW','DeleteFileW','Profiles\\\\Templates','#import','ENUM_TIMEFRAMES TF('])
 {assert.ok(!source.includes(gone),gone);passed++;}
assert.ok(source.includes('#define GOAT_DASH_DEPLOY_RETIRED_MESSAGE "Use Next in the app to deploy; dashboard deploy returns in the next update"'));passed++;
console.log(JSON.stringify({passed,productionExtracted:true,templatePathRetired:true,nativeTemplateAndIoVerified:false}));
