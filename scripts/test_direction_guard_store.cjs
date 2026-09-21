const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const text=fs.readFileSync(path.join(__dirname,'..','GOAT_DirectionGuard.mqh'),'utf8');
const body=text.match(/bool GuardStoreEnsure\(const string key\)\s*\{([\s\S]*?)\n\s*\}/)[1];
function check(tempResult,exists,expected){let writes=0;const context={GlobalVariableTemp:()=>tempResult,GlobalVariableCheck:()=>exists,GlobalVariableSet:()=>{writes++;}};vm.runInNewContext('function ensure(key){'+body+'};this.result=ensure("owned");',context);assert.equal(context.result,expected);assert.equal(writes,0);}
check(true,true,true);check(false,true,true);check(false,false,false);
console.log('PASS actual MQL store adapter: new, existing and unavailable locks; no destructive initialization');
