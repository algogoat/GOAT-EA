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
const num=v=>v==='true'?1:v==='false'?0:Number(v);   // MT5 reads a bool input as 0/1
function load(text){for(const line of text.split(/\r?\n/)){const eq=line.indexOf('=');if(eq<1)continue;const n=line.slice(0,eq);if(!names.includes(n))continue;const p=line.slice(eq+1).split('||');const prev=native.get(n)||[false,0,0,0,0];native.set(n,p.length===5?[p[4]==='Y',num(p[0]),num(p[1]),num(p[2]),num(p[3])]:[prev[0],num(p[0]),...prev.slice(2)]);}}
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
// B50 (A0, GOAT-EA#269 P1): a real pool SET written before B50 (a B49a-era WriteSet export, the r8 USDCHF member)
// omits the seven B50 axes. The native config writes each one explicitly at its default, fixed (N), so a stale Y flag in
// the terminal's tester profile is cleared, and OnTesterInit accepts the SET; without those lines it is refused.
{const pool=fs.readFileSync(path.join(root,'controller/fixtures/oosc/r8/deploy/R1696f82a0d700d5c7279/USDCHF/GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set')).toString('utf16le').replace(/^\uFEFF/,'');
 // B51 (B50-beta-1a): the benchmark seed is an appended axis too, written the same way (Random_Direction is an sinput).
 const B50={Single_SL_ATR:'0.0',Single_TP_ATR:'0.0',Single_TP_R:'0.0',Single_Exit_Opposite:'false',Single_Time_Stop_Bars:'0',Single_Time_Stop_TF:'0',Rollover_Block_Minutes:'0',
  Random_Seed:'1',Single_BE_ATR:'0.0',Single_Trail_Start_ATR:'0.0',Single_Trail_ATR:'0.0'};   // beta-1b: the break-even and trailing axes
 const desc=pool.match(/^EA_Desc=(.*?)\r?$/m)[1];
 for(const n of Object.keys(B50)) assert.ok(!pool.includes('\n'+n+'='),'the pool SET predates '+n);
 assert.deepEqual(names.filter(n=>!pool.includes('\n'+n+'=')).sort(),Object.keys(B50).sort(),'it carries every other axis');
 const stale=()=>{native.clear();for(const n of Object.keys(B50))native.set(n,[true,1,0.5,0.5,3]);};
 stale();load(pool);verify(pool,desc,false,'Single_SL_ATR');   // the raw SET leaves the stale flags in place
 const explicit=c.GoatStudioExplicitOptimizationInputs(pool);
 for(const [n,d] of Object.entries(B50)) assert.ok(explicit.includes('\r\n'+n+'='+d+'||'+d+'||0||'+d+'||N\r\n'),'explicit line for '+n);
 stale();load(explicit);verify(pool,desc,true);
 for(const [n,d] of Object.entries(B50)) assert.deepEqual(native.get(n).slice(0,2),[false,num(d)],n+' fixed at its default');
 assert.equal(c.GoatStudioExplicitOptimizationInputs(explicit),explicit,'idempotent');
 // A SET that carries a B50 axis keeps its own tuple and gains no second line for it.
 const own=pool.replace('\r\nEA_Desc=','\r\nSingle_SL_ATR=1.0||0.5||0.5||2.0||Y\r\nEA_Desc=');
 const ownExplicit=c.GoatStudioExplicitOptimizationInputs(own);
 assert.equal(ownExplicit.split('\nSingle_SL_ATR=').length,2);assert.ok(ownExplicit.includes('Single_SL_ATR=1.0||0.5||0.5||2.0||Y'));
 stale();load(ownExplicit);verify(own,desc,true);
 // Every pre-B50 axis is still required.
 verify(pool.replace(/\r\nGrid_Size=[^\r]*/,''),desc,false,'Missing selected input: Grid_Size');
 // Load-bearing: without the explicit B50 lines the stale flags survive and OnTesterInit refuses the SET.
 const src=fs.readFileSync(path.join(root,'GOATOptimizationInputs.mqh'),'utf8');
 assert.ok(src.includes('// B50:begin b50-explicit')&&src.includes('// B50 (A0, GOAT-EA#269 P1): a B50 axis may be omitted'));
}
const ea=fs.readFileSync(path.join(root,'GOAT V1.49.mq5'),'utf8');const init=ea.slice(ea.indexOf('int OnTesterInit()'));
assert.ok(init.indexOf('GoatStudioVerifyOptimizationInputs')<init.indexOf('g_batchStartupAccepted=true'));
assert.match(init,/optimization refused before passes/);
assert.match(fs.readFileSync(path.join(root,'Optimizer.mqh'),'utf8'),/testerInputs=GoatStudioExplicitOptimizationInputs\(testerInputs\)/);
console.log('Production MQL normalizer/readback consecutive-strategy carryover, all-input coverage, wrong value/range/missing-readback and integration PASS');
