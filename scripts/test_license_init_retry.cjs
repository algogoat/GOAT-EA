// Execute production MQL retry/wait/identity functions with deterministic native stubs.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../GOATLicenseInitRetry.mqh'),'utf8');
const main=fs.readFileSync(path.join(__dirname,'../GOAT V1.47.mq5'),'utf8');
let code=source.replace(/\b(?:bool|int) (GOAT\w+)\(([\s\S]*?)\)\r?\n  \{/g,(_,name,args)=>
 `function ${name}(${args.split(',').map(x=>x.trim().replace(/\[\]/g,'').match(/\w+$/)[0]).join(',')}) {`)
 .replace(/\(uint\)\(ChartID\(\)>>32\)/g,'u32(Math.floor(ChartID()/4294967296))')
 .replace(/\(uint\)ChartID\(\)/g,'u32(ChartID())').replace(/\(uint\)account/g,'u32(account)')
 .replace('spread*=2654435761;','spread=Math.imul(spread,2654435761)>>>0;')
 .replace(/\b(?:const )?(?:bool|int|long|ulong|uint|string) (\w+)\[\];/g,'let $1=[];')
 .replace(/\b(?:bool|int|long|ulong|uint|string) /g,'let ')
 .replace(/\((?:int|long|ulong|double)\)/g,'')
 .replace('GOATBuildAuthenticatedRequestHeaders(headers)','((headers=buildHeaders())!==null)')
 .replace('status=WebRequest("POST",url,headers,request_timeout,body,result,response_headers);',
          '({status,response_headers}=WebRequest("POST",url,headers,request_timeout,body,result,response_headers));')
 .replace('StringSplit(response_headers,\'\\n\',retry_header_lines)','(retry_header_lines=response_headers.split("\\n")).length')
 .replace('StringToLower(header);','header=header.toLowerCase();')
 .replace('StringTrimLeft(seconds); StringTrimRight(seconds);','seconds=seconds.trim();');
function run(options={}) {
 let clock=0,requests=0,authReads=0,lastError=0;const logs=[],sleeps=[],timeouts=[];
 let account=options.account??9271,server='Demo',stopped=false;
 const responses=options.responses??[{status:200}];
 const ctx={Math,IsStopped:()=>stopped,ACCOUNT_LOGIN:1,ACCOUNT_SERVER:2,MQL_TESTER:3,MQL_OPTIMIZATION:4,MQL_FORWARD:5,
 AccountInfoInteger:()=>account,AccountInfoString:()=>server,MQLInfoInteger:x=>(options.context??[]).includes(x),
 GetTickCount64:()=>clock,ChartID:()=>options.chart??53904251912009,u32:x=>x>>>0,
 MathMin:Math.min,MathMax:Math.max,timeout:options.timeout??5000,
 Sleep:n=>{assert.ok(n>0&&n<=100);clock+=n;sleeps.push(n);options.onSleep?.({clock,setAccount:v=>account=v,setServer:v=>server=v,stop:()=>stopped=true});},
 buildHeaders:()=>{authReads++;return options.noAuth || authReads===(options.revokeAt??-1)?null:'test-opaque-header';},
 ArrayResize:(a,n)=>a.length=n,ResetLastError:()=>lastError=0,GetLastError:()=>lastError,
 WebRequest:(method,url,headers,timeout)=>{assert.equal(headers,'test-opaque-header');assert.equal(account,9271);assert.equal(server,'Demo');
   assert.ok(timeout>=1&&timeout<=60000-clock);timeouts.push(timeout);const r=responses[Math.min(requests++,responses.length-1)];
   lastError=r.error??0;clock+=r.elapsed??0;if(r.drift)account=999;if(r.stop)stopped=true;
   return {status:r.status,response_headers:r.headers??''};},
 StringLen:s=>s.length,StringFind:(s,q)=>s.indexOf(q),StringSubstr:(s,n)=>s.slice(n),
 StringGetCharacter:(s,n)=>s[n],StringToInteger:s=>Number.parseInt(s,10),Print:(...x)=>logs.push(x.join(''))};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 const status=ctx.GOATLicenseAuthenticatedRequest(9271,'Demo',options.initializing??true,'https://test.invalid',[],[],'',0);
 return {status,requests,authReads,clock,logs,sleeps,timeouts};
}
let passed=0;function test(name,fn){try{fn();passed++;}catch(e){e.message=name+': '+e.message;throw e;}}
test('native success',()=>assert.equal(run().requests,1));
for(const status of [1003,408,429,500,503,599])test('transient '+status,()=>{const r=run({responses:[{status},{status:200}]});assert.equal(r.status,200);assert.equal(r.requests,2);});
for(const error of [5201,5202,5203])test('transport '+error,()=>assert.equal(run({responses:[{status:-1,error},{status:200}]}).requests,2));
for(const status of [200,400,401,403,404,409,499,600,1001])test('no retry '+status,()=>{const r=run({responses:[{status}]});assert.equal(r.requests,1);assert.equal(r.status,status);});
for(const error of [0,4014,5200])test('no retry native '+error,()=>assert.equal(run({responses:[{status:-1,error}]}).requests,1));
test('exhaustion stays failed',()=>{const r=run({responses:[{status:1003,elapsed:5000}]});assert.equal(r.requests,4);assert.equal(r.status,1003);assert.ok(r.clock<=60000);});
test('no auth performs no request',()=>{const r=run({noAuth:true});assert.equal(r.status,401);assert.equal(r.requests,0);});
test('credential removed between attempts',()=>{const r=run({responses:[{status:503}],revokeAt:2});assert.equal(r.status,401);assert.equal(r.requests,1);});
test('account drift during initial wait',()=>{const r=run({onSleep:x=>x.setAccount(999)});assert.equal(r.requests,0);assert.equal(r.status,-2);});
test('server drift during initial wait',()=>assert.equal(run({onSleep:x=>x.setServer('Other')}).requests,0));
test('stopped during initial wait',()=>assert.equal(run({onSleep:x=>x.stop()}).requests,0));
test('account drift after successful response',()=>assert.equal(run({responses:[{status:200,drift:true}]}).status,-2));
test('stopped after response',()=>assert.equal(run({responses:[{status:200,stop:true}]}).status,-2));
test('budget clamps native timeout',()=>{const r=run({timeout:120000,responses:[{status:503,elapsed:59000}]});assert.ok(r.timeouts[0]<=60000);assert.equal(r.requests,1);assert.equal(r.status,-2);});
for(const context of [[3],[4],[5]])test('tester context no stagger or retry '+context,()=>{const r=run({context,responses:[{status:503}]});assert.equal(r.requests,1);assert.equal(r.sleeps.length,0);});
test('non-init no stagger or retry',()=>{const r=run({initializing:false,responses:[{status:1003}]});assert.equal(r.requests,1);assert.equal(r.sleeps.length,0);});
test('Retry-After seconds honored',()=>{const r=run({responses:[{status:429,headers:'Retry-After: 20\r\n'},{status:200}]});assert.ok(r.clock>=20000);assert.equal(r.requests,2);});
for(const headers of ['Retry-After: 120','Retry-After: Tue, 22 Sep 2026 01:00:00 GMT','Retry-After: invalid','Retry-After: -1','x'.repeat(8193)])
 test('unsupported or excessive delay stops '+headers.slice(0,30),()=>assert.equal(run({responses:[{status:429,headers}]}).requests,1));
test('jitter separates adjacent chart ids',()=>assert.ok(new Set(Array.from({length:33},(_,i)=>run({chart:53904251912009+i}).clock)).size>25));
test('no secret logging',()=>{const r=run({responses:[{status:503,headers:'SECRET-HEADER'},{status:200}]});assert.ok(!JSON.stringify(r.logs).includes('SECRET'));assert.ok(!JSON.stringify(r.logs).includes('opaque'));});
test('main integration preserves existing parser',()=>{assert.ok(main.includes('GOATLicenseAuthenticatedRequest(AccNum,AccServer,init,URL,post_data,result,result_headers,native_error)'));assert.ok(main.includes('if(response_text=="no")'));assert.ok(main.includes('return 403;'));assert.ok(main.includes('LicenseKey<0 || LicenseKey>=500'));assert.ok(!main.includes('"License check HTTP response "+(string)res+": "+CharArrayToString'));});
const parser=main.slice(main.indexOf('   if(res == 200)'),main.indexOf('//+------------------------------------------------------------------+\r\nbool IsVersionExpired'))
 .replace(/\(string\)(\w+)/g,'String($1)');
function parse(status,body) {
 const ctx={res:status,response_text:body,AccNum:9271,Key:'GOAT',LICENSE_VALID:1505,LastLicenseCheckTime:0,
 StringFind:(s,q)=>s.indexOf(q),TimeCurrent:()=>123,Print:()=>{},ShowPrompt:()=>{},URL_Web:'test.invalid'};
 vm.createContext(ctx);return vm.runInContext('(function(){'+parser+')()',ctx);
}
test('production parser accepts only bound license success',()=>assert.equal(parse(200,'9271 - yes'),1505));
test('production parser rejects revoked account body',()=>assert.equal(parse(200,'no'),403));
test('production parser rejects wrong account',()=>assert.equal(parse(200,'999 - yes'),200));
test('production parser rejects malformed success',()=>assert.equal(parse(200,'unexpected'),200));
test('production parser preserves denied401',()=>assert.equal(parse(401,'no'),401));
test('production parser preserves denied403',()=>assert.equal(parse(403,'no'),403));
console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
