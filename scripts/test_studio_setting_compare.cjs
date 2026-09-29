const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
let mql = ['GOATStudioNative.mqh','GOATStudioSettingTypes.mqh','GOATStudioSettingValues.mqh','GOATStudioSettingCompare.mqh','GOATStudioExportDates.mqh']
 .map(n => fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'')).join('\n');
const testerSource=fs.readFileSync(path.join(root,'Tester.mqh'),'utf8').replace(/\r\n/g,'\n');
const exportStart=testerSource.indexOf('bool CompareCanonicalIni(');
const exportEnd=testerSource.indexOf('void ExtractConfigSettings(',exportStart);
assert.ok(exportStart>=0 && exportEnd>exportStart);
mql+='\n'+testerSource.slice(exportStart,exportEnd);
// Production MQL control flow runs with string/array/UTC intrinsics shimmed.
// MetaEditor compilation and actual native MT5 readback remain separate checks.
let js = mql.replace(/^#.*$/gm,'').replace(/\berror\b/g,'failure.value')
 .replace(/\b(bool|string) (GoatStudio\w+|CompareCanonicalIni)\(([^)]*)\)/g,(_,type,name,args) =>
  'function '+name+'('+args.replace(/failure\.value/g,'failure').replace(/\b(const|bool|string|int|long|ulong|ushort|datetime|double)\b\s*/g,'').replace(/&|\[\]/g,'')+')')
 .replace(/\(string\)\(long\)(\w+)/g,'String($1)').replace(/\(string\)(\w+)/g,'String($1)').replace(/\(int\)/g,'')
 .replace(/\b(?:string|bool|int|long|ulong|ushort|datetime|double)\s+([^;]+);/g,(_,declaration) =>
  'let '+declaration.replace(/\b(\w+)\[\]/g,'$1=[]')+';');
// MQL StringReplace mutates its first argument.
js = js.replace(/StringReplace\((\w+),([^,]+),([^\)]+)\);/g,'$1=$1.split($2).join($3);');
const c = {
 StringLen:s=>s.length, StringSubstr:(s,i,n)=>n===undefined?s.substring(i):s.substr(i,n),
 StringFind:(s,x,i=0)=>s.indexOf(x,i), StringGetCharacter:(s,i)=>s.charCodeAt(i),
 StringSplit:(s,sep,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(sep)));return out.length;},
 ArraySize:a=>a.length,ArrayResize:(a,n)=>{a.length=n;},
 StringToInteger:s=>Number(s), StringToTime:s=>Date.parse(s.replace(/\./g,'-').replace(' ','T')+(s.length===10?'T00:00:00Z':s.length===16?':00Z':'Z'))/1000,
 TimeToString:t=>Number.isFinite(t)?new Date(t*1000).toISOString().replace(/-/g,'.').replace('T',' ').slice(0,19):'', TIME_DATE:1,TIME_SECONDS:2,
};
js=js.replace(/GoatStudioINIEntries\(([^,]+),([^,]+),failure\.value\)/g,'GoatStudioINIEntries($1,$2,failure)');
// Native chars are integral. Strings are always double quoted in these modules.
js=js.replace(/'((?:\\.|[^'])*)'/g,(_,ch)=>String(JSON.parse('"'+ch+'"').charCodeAt(0)));
// Only existing parser trim calls mutate by reference.
js=js.replace(/StringTrimLeft\((\w+)\);/g,'$1=$1.trimStart();').replace(/StringTrimRight\((\w+)\);/g,'$1=$1.trimEnd();');
js=js.replace(/let date_error;/g,'let date_error={value:""};').replace(/LogOrPrint\(false,date_error,/g,'LogOrPrint(false,date_error.value,');
js=js.replace(/\bln\[0\]/g,'StringGetCharacter(ln,0)');
Object.assign(c,{StringTrim:s=>s.trim(),StringToDouble:s=>parseFloat(s)||0,MathAbs:Math.abs,
 StringCompare:(a,b)=>a===b?0:1,StringFormat:(...args)=>args.join(' '),LogOrPrint:()=>{},strT:{_K:'',_N:'',_S:''}});
vm.createContext(c);vm.runInContext(js,c);
const fixture=path.join(root,'controller/fixtures/tester-roundtrip');
const w=fs.readFileSync(path.join(fixture,'wanted.ini'),'utf8'),a=fs.readFileSync(path.join(fixture,'observed.ini'),'utf8');
let count=0;
function compare(wanted,observed,pass,key) {const e={value:''}; const result=c.GoatStudioSemanticINIEqual(wanted,observed,e); assert.equal(result,pass,e.value);if(key)assert.ok(e.value.includes(key),e.value);count++;}
compare(w,a,true);
for(const [old,value,key] of [
 ['Grid_Size=-4.0||-5||1||-3||Y','Grid_Size=-4.0||-5||2||-3||Y','Grid_Size'],
 ['Risk=500.0','Risk=501.0','Risk'], ['FromDate=2025.06.26','FromDate=2025.06.27','FromDate'],
 ['Download_StartDate=1735689600','Download_StartDate=1735776000','Download_StartDate'],
 ['Grid_Size=-4.0||-5||1||-3||Y','Grid_Size=-4.0||-5||1||-3||N','Grid_Size'],
 ['Reverse_Seq=false||false||0||true||N','Reverse_Seq=true||false||0||true||N','Reverse_Seq'],
 ['Sequence_Export_Enabled=false','Sequence_Export_Enabled=true','Sequence_Export_Enabled'],
 ['Studio_ReadOnlyMonitor=false','Studio_ReadOnlyMonitor=true','Studio_ReadOnlyMonitor'],
 ['Deposit=100000','Deposit=NaN','Deposit'], ['Risk=500.0','Risk=500.00000000000000001','Risk'],
]) {assert.ok(a.includes(old));compare(w,a.replace(old,value),false,key);}
compare(w,a+'\nUnlistedInput=0\n',false,'UnlistedInput');
compare(w,a.replace(/Risk=500\.0\r?\n/,''),false,'Risk');
compare(w,a+'\nRisk=500\n',false,'Risk');
compare(w,a.replace('Risk=500.0','Risk=5e2'),true);
compare(w,a.replace('Download_StartDate=1735689600','Download_StartDate=2025.01.01'),true);
compare(w,a.replace('Download_StartDate=1735689600','Download_StartDate=2025.02.30'),false,'Download_StartDate');
compare(w,a.replace('Grid_Size=-4.0||-5||1||-3||Y','Grid_Size=-4||-5.000||1.0||-3e0||Y'),true);
compare(w,a.replace('Risk=500.0','Risk=500||0||1||10||Y'),false,'Risk');
assert.equal(c.GoatStudioSettingValueEqual('text||Y','text||Y','string'),true);count++;
assert.equal(c.GoatStudioSettingValueEqual('text||Y','text','string'),false);count++;
for(const value of ['NaN','Infinity','1x','1e309','--1','','1||2',' 1','1 ']){assert.equal(c.GoatStudioDecimal(value),'#INVALID#');count++;}
assert.equal(c.GoatStudioDecimal('1.000',true),'1e0');count++;
assert.equal(c.GoatStudioDecimal('1.00001',true),'#INVALID#');count++;
const schema=JSON.parse(fs.readFileSync(path.join(root,'controller/contracts/v149/inputs.json'),'utf8'));
for(const [key,entry] of Object.entries(schema.inputs)) {
 const expectedType=entry.type.startsWith('ENUM_') || entry.type==='uint'?'int':entry.type;
 assert.equal(c.GoatStudioSettingType(key),expectedType,key);count++;
 assert.equal(c.GoatStudioSettingOptimizable(key),entry.optimizable,key);count++;
}
assert.equal(c.GoatStudioSettingType('UnknownFutureInput'),'');count++;
for(const value of ['-6||1||-3','-5||1||-2']) {
 compare(w,a.replace('Grid_Size=-4.0||-5||1||-3||Y','Grid_Size=-4.0||'+value+'||Y'),false,'Grid_Size');
}
compare(w.replace('Optimization=2','Optimization=0'),a.replace('Optimization=2','Optimization=0'),false,'Visual');
compare(w.replace('Optimization=2','Optimization=0'),w.replace('Optimization=2','Optimization=0'),true);
compare(w.replace('Optimization=2','Optimization=3'),a.replace('Optimization=2','Optimization=3'),false,'Optimization');

// Actual fixed-export comparison path, not just the shared normalization helper.
const exportWanted='[Tester]\nOptimization=0\nModel=4\n[TesterInputs]\nRisk=500\nSequence_Export_Enabled=true\nSequence_Export_Start=2025.06.26\nSequence_Export_End=2026.06.26\n';
const exportObserved=exportWanted.replace('2025.06.26','1750896000').replace('2026.06.26','1782432000');
assert.equal(c.CompareCanonicalIni(exportObserved,exportWanted),true);count++;
for(const changed of [
 exportObserved.replace('1750896000','1750982400'),
 exportObserved.replace('1782432000','1782518400'),
 exportObserved.replace('1750896000','2025.02.30'),
 exportObserved.replace('Sequence_Export_Start=1750896000\n',''),
 exportObserved+'Sequence_Export_Start=1750896000\n',
 exportObserved.replace('Risk=500','Risk=501'),
 exportObserved.replace('Model=4','Model=1'),
]) {assert.equal(c.CompareCanonicalIni(changed,exportWanted),false);count++;}
assert.equal(c.CompareCanonicalIni(exportObserved,exportWanted.replace('Sequence_Export_End=2026.06.26\n','')),false);count++;
assert.equal(c.CompareCanonicalIni('[TesterInputs]\nRisk=500','[TesterInputs]\nRisk=500'),true);count++;

assert.equal(c.CompareCanonicalIni('[TesterInputs]\nSequence_Export_Enabled=true','[TesterInputs]\nSequence_Export_Enabled=true'),false);count++;

// Execute the real export-ID producer expression against the real native
// consumer predicate. MQL datetime-to-string emits calendar text unless the
// producer explicitly converts datetime to an integer first.
const main=fs.readFileSync(path.join(root,'GOAT V1.49.mq5'),'utf8');
const producer=main.match(/string captureId=([^;]+);/)[1];
const expression=producer.replace(/\(string\)\(long\)TimeLocal\(\)/g,'String(epochSeconds)')
 .replace(/\(string\)TimeLocal\(\)/g,'dateText')
 .replace(/\(string\)GetMicrosecondCount\(\)/g,'String(micros)').replace(/\(string\)rowInd/g,'String(row)');
const makeId=new Function('epochSeconds','dateText','micros','row','return '+expression);
const sequenceSource=fs.readFileSync(path.join(root,'GOAT_SequencePackage.mqh'),'utf8');
let safeId=sequenceSource.slice(sequenceSource.indexOf('bool GoatSeqSafeId('),sequenceSource.indexOf('string GoatSeqJson('));
safeId=safeId.replace('bool GoatSeqSafeId(const string id)','function GoatSeqSafeId(id)')
 .replace(/\bstring allowed=/,'let allowed=').replace(/for\(int i=/,'for(let i=');
vm.runInContext(safeId,c);
const ids=new Set();
for(const stamp of [0,1790656341,32535215999]) for(const micros of [1,116518271]) for(const row of [0,1,29]) {
 const id=makeId(stamp,'2026.09.28 21:32:21',micros,row);
 assert.equal(c.GoatSeqSafeId(id),true,id);assert.equal(ids.has(id),false);ids.add(id);count++;
}
for(const id of ['export-2026.09.28 21:32:21-116518271-0','../old','x\\y','', 'x'.repeat(97)]) {
 assert.equal(c.GoatSeqSafeId(id),false);count++;
}
const runSet=main.slice(main.indexOf('int RunAndStoreSet(int rowInd'),main.indexOf('const datetime t0 =',main.indexOf('int RunAndStoreSet(int rowInd')));
assert.ok(runSet.indexOf('if(!GoatSeqSafeId(captureId))')<runSet.indexOf('GoatSeqMakePath(pendingRoot)'));
assert.ok(runSet.indexOf('if(!GoatSeqSafeId(captureId))')<runSet.indexOf('StartTester(rowInd'));
console.log(JSON.stringify({passed:count,nativeQualification:false}));
