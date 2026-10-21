const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
let source=['GOATStudioSettingTypes.mqh','GOATOptimizationInputs.mqh'].map(n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'')).join('\n');
let js=source.replace(/^#.*$/gm,'').replace(/\berror\b/g,'failure.value')
.replace(/\b(bool|string) (GoatStudio\w+)\(([^)]*)\)/g,(_,type,name,args)=>'function '+name+'('+args.replace(/failure\.value/g,'failure').replace(/\b(const|bool|string|int|long|double)\b\s*/g,'').replace(/&|\[\]/g,'')+')')
.replace(/\b(?:string|bool|int|long|double)\s+([^;]+);/g,(_,s)=>'let '+s.replace(/\b(\w+)\[\]/g,'$1=[]')+';')
.replace(/StringTrimLeft\((\w+)\);/g,'$1=$1.trimStart();').replace(/StringTrimRight\((\w+)\);/g,'$1=$1.trimEnd();')
.replace(/StringReplace\((\w+),([^,]+),([^\)]+)\);/g,'$1=$1.split($2).join($3);')
.replace(/ParameterGetRange\(name,enabled,(\w+),(\w+),(\w+),(\w+)\)/g,(_,a,b,c,d)=>`(()=>{const r=getNativeRange(name);if(!r)return false;[enabled,${a},${b},${c},${d}]=r;return true;})()`)
.replace(/'((?:\\.|[^'])*)'/g,(_,ch)=>String(JSON.parse('"'+ch+'"').charCodeAt(0)));
const native=new Map();const c={StringSubstr:(s,i,n)=>n===undefined?s.substring(i):s.substr(i,n),StringFind:(s,v)=>s.indexOf(v),StringSplit:(s,d,a)=>{a.splice(0,a.length,...s.split(String.fromCharCode(d)));return a.length;},ArraySize:a=>a.length,ArrayResize:(a,n)=>a.length=n,StringToDouble:Number,StringToInteger:Number,getNativeRange:n=>native.get(n)};vm.createContext(c);vm.runInContext(js,c);
const schema=JSON.parse(fs.readFileSync(path.join(root,'controller/contracts/v149/inputs.json'),'utf8'));
const names=Object.entries(schema.inputs).filter(([k,v])=>v.optimizable).map(([k])=>k).sort();
assert.deepEqual(Array.from(c.GoatStudioOptimizationNames().split('|').filter(Boolean)).sort(),names,'all typed optimizable inputs covered');
const make=(desc,axis)=>['; preserved source','EA_Desc='+desc,...names.map(n=>n+'='+(n===axis?'2||1||1||3||Y':'2'))].join('\r\n')+'\r\n';
// Emulate the observed MT5 load semantics: a bare scalar changes value but
// retains the previous enable/range state. Explicit N resets that state.
function load(text){for(const line of text.split(/\r?\n/)){const eq=line.indexOf('=');if(eq<1)continue;const n=line.slice(0,eq);if(!names.includes(n))continue;const p=line.slice(eq+1).split('||');const prev=native.get(n)||[false,0,0,0,0];native.set(n,p.length===5?[p[4]==='Y',Number(p[0]),Number(p[1]),Number(p[2]),Number(p[3])]:[prev[0],Number(p[0]),...prev.slice(2)]);}}
function verify(text,desc,expected,key){const e={value:''};assert.equal(c.GoatStudioVerifyOptimizationInputs(text,desc,e),expected,e.value);if(key)assert.ok(e.value.includes(key),e.value);}
const first=make('first','RSI_Period'),second=make('second','EMA_Period');
load(first);verify(first,'first',true);
load(second);verify(second,'second',false,'RSI_Period'); // Regression: stale flag before fix.
load(c.GoatStudioExplicitOptimizationInputs(second));verify(second,'second',true);
assert.deepEqual([...native].filter(([n,v])=>v[0]).map(([n])=>n),['EMA_Period']);
assert.equal(second,make('second','EMA_Period'),'original SET unchanged');
assert.ok(c.GoatStudioExplicitOptimizationInputs(second).includes('EMA_Period=2||1||1||3||Y'));
for(const axis of ['MACD_Fast','RSI2_Period','Grid_Size']){const next=make('next',axis);load(c.GoatStudioExplicitOptimizationInputs(next));verify(next,'next',true);assert.deepEqual([...native].filter(([n,v])=>v[0]).map(([n])=>n),[axis]);}
const active=make('next','Grid_Size');native.get('Grid_Size')[3]=2;verify(active,'next',false,'Grid_Size');load(c.GoatStudioExplicitOptimizationInputs(active));native.get('RSI_Period')[1]=999;verify(active,'next',false,'RSI_Period');load(c.GoatStudioExplicitOptimizationInputs(active));native.delete('RSI_Period');verify(active,'next',false,'RSI_Period');
verify(active,'wrong',false,'description');verify(active.replace('RSI_Period=2\r\n',''),'next',false,'Missing');
const ea=fs.readFileSync(path.join(root,'GOAT V1.49.mq5'),'utf8');const init=ea.slice(ea.indexOf('int OnTesterInit()'));
assert.ok(init.indexOf('GoatStudioVerifyOptimizationInputs')<init.indexOf('g_batchStartupAccepted=true'));
assert.match(init,/optimization refused before passes/);
assert.match(fs.readFileSync(path.join(root,'Optimizer.mqh'),'utf8'),/testerInputs=GoatStudioExplicitOptimizationInputs\(testerInputs\)/);
console.log('Production MQL normalizer/readback consecutive-strategy carryover, all-input coverage, wrong value/range/missing-readback and integration PASS');
