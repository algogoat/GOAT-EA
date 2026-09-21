// Execute the production startup decision block with mocked native/UI calls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../GOAT V1.47.mq5'),'utf8');
let block=src.slice(src.indexOf('      bool fresh_dashboard_launch=false;'),src.indexOf('       ChartSetInteger(0, CHART_EVENT_MOUSE_WHEEL'));
block=block.replace(/\"(\s*)\"/g,'\"+$1\"').replace(/\b(?:bool|int|string|long) /g,'let ')+ '\nreturn 0;\n}';
function run({resume=true,first=true,saved=true,count=33,answer=6}={}) {
 const calls=[];const ctx={Dashboard_Resume_Saved:resume,Mode_Operation:8,Operation_Dash:8,
 Key:'k',EA_Name:'n',Server:'s',version_:'1.47',Font_Size:8,INIT_FAILED:-1,IDYES:6,IDNO:7,
 MB_YESNO:0,MB_YESNOCANCEL:0,MB_ICONQUESTION:0,MB_DEFBUTTON1:0,
 ChartID:()=>1,ChartFirst:()=>first?1:2,ChartNext:()=>-1,ChartClose:()=>calls.push('closeChart'),ChartRedraw:()=>{},
 Print:()=>calls.push('print'),Alert:()=>calls.push('alert'),ShowPrompt:()=>calls.push('prompt'),Sleep:()=>{},ExpertRemove:()=>{},
 MessageBox:()=>{calls.push('message');return answer;},GoatDeleteDashboardBusData:()=>calls.push('deleteBus'),
 DashboardDialog:{ResetPortfolioTrackingState:()=>calls.push('reset'),SetFlags:()=>calls.push('flags'),DashboardStateExists:()=>{assert.equal(calls[0],'flags');return saved;},
 LoadDashboardConfig:()=>{calls.push('loadSaved');return count;},LoadSetFiles:()=>{calls.push('picker');return count;},DeleteDashboardConfig:()=>calls.push('deleteConfig')}};
 vm.createContext(ctx);const result=vm.runInContext('(function(){'+block+'})()',ctx);return {result,calls};
}
for(const config of [{},{count:1}]){const r=run(config);assert.equal(r.result,0);assert.deepEqual(r.calls,['flags','loadSaved']);}
for(const config of [{first:false},{saved:false},{count:0}]){const r=run(config);assert.equal(r.result,-1);for(const forbidden of ['message','picker','deleteBus','deleteConfig','closeChart','reset'])assert.ok(!r.calls.includes(forbidden));}
assert.ok(run({resume:false,saved:false}).calls.includes('picker'));
assert.ok(run({resume:false}).calls.includes('message'));
assert.ok(run({resume:false,answer:7}).calls.includes('deleteConfig'));
console.log(JSON.stringify({passed:8,productionDecisionBlock:true,nativeRestart:false}));
