const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),globals=new Map();let flushHook=null,sleepHook=null,clickHook=null,fileHook=null,clicks=0,seed=false;
let helper=fs.readFileSync(path.join(root,'GOATBatchCancelOrigin.mqh'),'utf8').replace(/^\uFEFF/,'').replace(/^#.*$/gm,'').replace(/\b(?:void|bool) (GoatBatch\w+)\(void\)/g,'function $1()').replace(/\bdouble /g,'let ');
const c={GOAT_BATCH_CANCELLED_GV:'cancel',GOAT_BATCH_HUMAN_CANCEL_GV:'human',GlobalVariableGet:k=>globals.get(k)??0,GlobalVariableCheck:k=>globals.has(k),GlobalVariableSet:(k,v)=>{globals.set(k,v);return 1;},GlobalVariableDel:k=>globals.delete(k),GlobalVariableTemp:k=>{if(!globals.has(k))globals.set(k,0);return true;},GlobalVariableSetOnCondition:(k,v,old)=>{if(globals.get(k)!==old)return false;globals.set(k,v);return true;},GlobalVariablesFlush:()=>{if(flushHook){const f=flushHook;flushHook=null;f();}},clickStart:()=>{clicks++;clickHook?.();},INIT_FAILED:1,INIT_SUCCEEDED:0,EA_Name:'fixture',EA_Desc:'fixture',Key:'GOAT',Server:'Demo',Symbol:()=> 'EURUSD',Print:()=>{},Sleep:ms=>sleepHook?.(ms),SeedFarmingPrepareReceiver:()=>seed,GetFileContent:()=>'',GoatOptStrategyDir:()=>'',GoatStudioVerifyOptimizationInputs:()=>true,WriteLog:()=>{},ShowPrompt:()=>{},MigrateLeftOverFilesToCommon:()=>false,GoatOptReportRoot:()=>'',GoatOptLeftoverPath:()=>'',GoatOptMigrateLegacyBatchState:()=>'',GoatOptTesterFitnessFile:()=>'GOAT\\Tester-fixture.txt',UpdateBatchQueueAndWriteConfigFile:()=>true,Mode_Opti:0,Opti_PF_MRFp:1,Opti_PF_MRF_SRp:2,FILE_TXT:1,FILE_WRITE:2,FILE_READ:4,FILE_SHARE_READ:8,FILE_SHARE_WRITE:16,FILE_COMMON:32,FileOpen:()=>1,FileWrite:()=>{},FileClose:()=>fileHook?.(),ArraySize:x=>x.length};
vm.createContext(c);vm.runInContext(helper,c);
const dispatch=fs.readFileSync(path.join(root,'GOATStudioDispatch.mqh'),'utf8').replace(/\r\n/g,'\n');
for(const [name,result] of [['arm','RESTART_ARMED_RECONCILE'],['start','START_SIGNAL_SENT_RECONCILE']]){
 const end=dispatch.indexOf(`return "${result}";`)+`return "${result}";`.length;
 const start=dispatch.lastIndexOf('if(!GoatBatchReleaseControllerCancel())',end);
 assert.ok(start>=0&&end>start);
 let block=dispatch.slice(start,end).replace(/^#else\n[\s\S]*?^#endif/gm,'').replace(/^#.*$/gm,'').replace(/MTTESTER::ClickStart\(false,1\)/g,'clickStart()');
 vm.runInContext(`function dispatch_${name}(){${block}}`,c);
}
let ea=fs.readFileSync(path.join(root,'GOAT V1.49.mq5'),'utf8');let init=ea.slice(ea.indexOf('int OnTesterInit()'),ea.indexOf('double OnTester()'));
init=init.replace(/\/\/[^\n]*/g,'').replace('int OnTesterInit()','function OnTesterInit()').replace(/\b(bool|string|int)\s+([^;]+);/g,(_,type,s)=>'let '+s.replace(/(\w+)\[\]/g,'$1=[]')+';');vm.runInContext(init,c);
function stop(){globals.set('human',1);globals.set('cancel',1);globals.delete('BatchOnGoing');}
function reset(){globals.clear();flushHook=sleepHook=clickHook=fileHook=null;clicks=0;seed=false;c.Mode_Opti=0;c.g_batchStartupAccepted=false;}
let passed=0;
for(const name of ['arm','start']){
 reset();assert.equal(c['dispatch_'+name](),name==='arm'?'RESTART_ARMED_RECONCILE':'START_SIGNAL_SENT_RECONCILE');assert.equal(globals.get('BatchOnGoing'),1);passed++;
 reset();flushHook=stop;assert.equal(c['dispatch_'+name](),'HUMAN_CANCEL_RETAINED');assert.equal(clicks,0);assert.equal(globals.get('human'),1);assert.equal(globals.get('cancel'),1);assert.ok(!globals.has('BatchOnGoing'));passed++;
}
// Stop arrives after the post-arm helper but at the click boundary: the actual
// OnTesterInit must reject, rather than falling through to ordinary optimization.
reset();clickHook=stop;assert.equal(c.dispatch_start(),'START_SIGNAL_SENT_RECONCILE');assert.equal(clicks,1);assert.equal(c.OnTesterInit(),1);passed++;
for(const mode of ['manual','batch','seed']){
 reset();seed=mode==='seed';if(mode==='batch')globals.set('BatchOnGoing',1);
 assert.equal(c.OnTesterInit(),0,mode);passed++;
 reset();seed=mode==='seed';if(mode==='batch')globals.set('BatchOnGoing',1);sleepHook=ms=>{if(ms===100)stop();};assert.equal(c.OnTesterInit(),1,mode+' stop during initial wait');passed++;
 reset();seed=mode==='seed';if(mode==='batch')globals.set('BatchOnGoing',1);c.Mode_Opti=1;fileHook=stop;assert.equal(c.OnTesterInit(),1,mode+' stop during final work');assert.equal(c.g_batchStartupAccepted,false);passed++;
}
reset();globals.set('BatchOnGoing',1);sleepHook=ms=>{if(ms===500)stop();};assert.equal(c.OnTesterInit(),1);assert.equal(c.g_batchStartupAccepted,false);passed++;
for(const value of [1,2,99]){reset();globals.set('cancel',value);assert.equal(c.OnTesterInit(),1);assert.equal(globals.get('cancel'),value);passed++;}
console.log(`${passed} actual native dispatch/OnTesterInit interleavings and no-stop manual/batch/seed controls PASS`);
