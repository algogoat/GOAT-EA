// Execute the production child-binding and freshness predicates with mocked GV IO.
// This is source-control-flow verification, not native terminal evidence.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
function body(file, name){
  const src=fs.readFileSync(path.join(__dirname,'..',file),'utf8');
  let start=src.indexOf(name+'('), begin=src.indexOf('{',start), end=begin+1, depth=1;
  for(;depth;end++){if(src[end]==='{')depth++;if(src[end]==='}')depth--;}
  return src.slice(begin+1,end-1)
    .replace(/\b(?:int|long|double|bool|string) /g,'let ').replace(/\((?:long|datetime)\)/g,'')
    .replace(/GoatFindMagicByCid\(([^,]+),([^,]+),(\w+)\)/g,'find($1,$2,v=>$3=v)')
    .replace(/GlobalVariableGet\((GoatChildGVName\([^\n]+?\)|pending),(\w+)\)/g,'get($1,v=>$2=v)')
    .replace(/g_sets\[idx\]\.cid\/1000000000/g,'Math.trunc(g_sets[idx].cid/1000000000)')
    .replace(/(?<!\.)\bcid\/1000000000/g,'Math.trunc(cid/1000000000)');
}
const bind=body('Dashboard.mqh','bool CGOATDashboard::NewSingleInstance');
const linked=body('GOATPortfolioSetupControl.mqh','bool GoatPortfolioRowLinked');
function fixture(){
  const rows=[{cid:2000000017,magic:0,sym:'EURUSD'}], vars=new Map(), deleted=[];
  const c={idx:0,row:0,g_sets:rows,DashboardDialog:{g_sets:rows},GOAT_GV_FIELD_MAGIC:'MAGIC',
    ArraySize:x=>x.length,GoatChildGVName:(m,s,f)=>`${m}/${s}/${f}`,
    find:(_s,_c,assign)=>{assign(9);return true;},get:(key,assign)=>{if(!vars.has(key))return false;assign(vars.get(key));return true;},
    GlobalVariableDel:key=>deleted.push(key),GlobalVariablesFlush:()=>{},ChartSymbol:()=> 'EURUSD',TimeGMT:()=>1000};
  vars.set('9/EURUSD/SETUP_CID_HI',2);vars.set('9/EURUSD/SETUP_CID_LO',17);vars.set('9/EURUSD/MAGIC',9);vars.set('9/EURUSD/SETUP_UTC',999);
  return{c,vars,rows,deleted};
}
const run=(source,c)=>vm.runInNewContext(`(function(){${source}})()`,c);
let f=fixture();assert.equal(run(bind,f.c),true);assert.equal(f.rows[0].magic,9);assert.deepEqual(f.deleted,['9/EURUSD/MAGIC']);
for(const key of ['SETUP_CID_HI','SETUP_CID_LO','MAGIC']){
  f=fixture();f.vars.set('9/EURUSD/'+key,999);assert.equal(run(bind,f.c),false);assert.equal(f.deleted.length,0);
}
f=fixture();f.rows.push({cid:123,magic:9,sym:'USDJPY'});assert.equal(run(bind,f.c),false);
f=fixture();f.c.find=()=>false;assert.equal(run(bind,f.c),false);
f=fixture();f.rows[0].magic=9;assert.equal(run(linked,f.c),true);
f.vars.set('9/EURUSD/SETUP_UTC',970);assert.equal(run(linked,f.c),false);
f.vars.set('9/EURUSD/SETUP_UTC',1001);assert.equal(run(linked,f.c),false);
f=fixture();f.rows[0].magic=9;f.c.ChartSymbol=()=> 'USDJPY';assert.equal(run(linked,f.c),false);
console.log('PASS 10 actual child-binding/freshness source fixtures; no native runtime claim');
