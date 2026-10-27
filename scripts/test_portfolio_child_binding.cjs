// Execute the production child-binding (AdoptChild, beta.25) and freshness predicates with mocked GV IO.
// This is source-control-flow verification, not native terminal evidence. The adoption pass that
// chooses the chart is covered by test_profile_staged_adoption.cjs.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
function body(file, name){
  const src=fs.readFileSync(path.join(__dirname,'..',file),'utf8').replace(/\r\n/g,'\n');
  let start=src.indexOf(name+'('), begin=src.indexOf('{',start), end=begin+1, depth=1;
  assert.ok(start>=0,name);
  for(;depth;end++){if(src[end]==='{')depth++;if(src[end]==='}')depth--;}
  return src.slice(begin+1,end-1)
    .replace(/^\s*#(?:ifdef|endif).*$/gm,'')
    .replace(/\b(?:int|long|double|bool|string) /g,'let ').replace(/\((?:long|datetime)\)/g,'')
    .replace(/GoatFindMagicByCid\(([^,]+),([^,]+),(\w+)\)/g,'find($1,$2,v=>$3=v)')
    .replace(/GlobalVariableGet\((GoatChildGVName\([^\n]+?\)|pending),(\w+)\)/g,'get($1,v=>$2=v)')
    .replace(/(?<!\.)\bcid\/1000000000/g,'Math.trunc(cid/1000000000)');
}
const adopt=body('Dashboard.mqh','bool CGOATDashboard::AdoptChild');
const linked=body('GOATPortfolioSetupControl.mqh','bool GoatPortfolioRowLinked');
function fixture(){
  const rows=[{cid:0,magic:0,sym:'EURUSD',status:'Pending'}], vars=new Map(), deleted=[], saved=[];
  const c={row:0,g_sets:rows,DashboardDialog:{g_sets:rows},GOAT_GV_FIELD_MAGIC:'MAGIC',
    ArraySize:x=>x.length,GoatChildGVName:(m,s,f)=>`${m}/${s}/${f}`,ChartID:()=>1,
    find:(_s,_c,assign)=>{assign(9);return true;},get:(key,assign)=>{if(!vars.has(key))return false;assign(vars.get(key));return true;},
    GlobalVariableDel:key=>deleted.push(key),GlobalVariablesFlush:()=>{},ChartSymbol:()=> 'EURUSD',TimeGMT:()=>1000,
    SaveDashboardConfig:()=>{saved.push([rows[0].cid,rows[0].magic]);return c.saveOk;},saveOk:true,
    edt_Status:[],btn_Action:[],StatusColor:()=>0,AppendAILaunchAudit:()=>{},UpdateAILaunchControls:()=>{},GoatDeploymentPhase:()=>{}};
  vars.set('9/EURUSD/SETUP_CID_HI',2);vars.set('9/EURUSD/SETUP_CID_LO',17);vars.set('9/EURUSD/MAGIC',9);vars.set('9/EURUSD/SETUP_UTC',999);
  return{c,vars,rows,deleted,saved};
}
const call=(source,c,args)=>vm.runInNewContext(`(function(adopt_idx,adopt_chart,adopt_magic){${source}})(${args})`,c);
const run=(source,c)=>vm.runInNewContext(`(function(){${source}})()`,c);
let f=fixture();assert.equal(call(adopt,f.c,'0,2000000017,9'),true);assert.deepEqual([f.rows[0].cid,f.rows[0].magic],[2000000017,9]);
assert.deepEqual(f.deleted,['9/EURUSD/MAGIC']);assert.deepEqual(f.saved,[[2000000017,9]],'persisted before it counts');assert.equal(f.rows[0].status,'Linked');
assert.equal(run(linked,f.c),true,'an adopted child with a fresh setup heartbeat is linked');
f=fixture();f.c.saveOk=false;assert.equal(call(adopt,f.c,'0,2000000017,9'),false);assert.deepEqual([f.rows[0].cid,f.rows[0].magic],[0,0]);assert.equal(f.deleted.length,0);
f=fixture();f.rows.push({cid:123,magic:9,sym:'USDJPY'});assert.equal(call(adopt,f.c,'0,2000000017,9'),false,'magic held by another row');
f=fixture();f.rows.push({cid:2000000017,magic:0,sym:'USDJPY'});assert.equal(call(adopt,f.c,'0,2000000017,9'),false,'chart claimed by another row');
f=fixture();f.rows[0].cid=2000000017;f.rows[0].magic=9;
assert.equal(run(linked,f.c),true);
f.vars.set('9/EURUSD/SETUP_UTC',970);assert.equal(run(linked,f.c),false);
f.vars.set('9/EURUSD/SETUP_UTC',1001);assert.equal(run(linked,f.c),false);
for(const key of ['SETUP_CID_HI','SETUP_CID_LO']){f=fixture();f.rows[0].cid=2000000017;f.rows[0].magic=9;f.vars.set('9/EURUSD/'+key,999);assert.equal(run(linked,f.c),false,key);}
f=fixture();f.rows[0].cid=2000000017;f.rows[0].magic=9;f.c.ChartSymbol=()=> 'USDJPY';assert.equal(run(linked,f.c),false);
f=fixture();f.rows[0].cid=2000000017;f.rows[0].magic=9;f.c.find=()=>false;assert.equal(run(linked,f.c),false);
console.log('PASS 13 actual child-binding/freshness source fixtures; no native runtime claim');
