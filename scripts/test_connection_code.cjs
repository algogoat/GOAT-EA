// Connection code prompt: runs the production GOATDeviceActivationShowCode and the retry
// cards with a mocked chart. The web app reads the code from the #ea-connect= fragment,
// which browsers never send to a server. MQL-free; no MT5 or network is used.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const src=fs.readFileSync(path.join(root,'GOATEADeviceActivation.mqh'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
function extract(name){
  const at=src.indexOf('void '+name+'('),start=src.lastIndexOf('\n',at)+1,brace=src.indexOf('{',at);
  assert.ok(at>=0,'missing '+name);
  let depth=1,i=brace+1;for(;depth;i++){if(src[i]==='{')depth++;if(src[i]==='}')depth--;}
  return src.slice(start,i).replace(/^void /,'function ').replace(/const (?:bool|string|int|long) /g,'')
    .replace(/\(void\)/,'()').replace(/\b(?:long|datetime) (\w+)=/g,'let $1=').replace(/\((?:long|string|datetime|int)\)/g,'').replace(/\/60000;/g,'/60000|0;'); // MQL long division truncates
}
let passed=0;const check=fn=>{fn();passed++;};
const prompts=[];
const c={g_GOATDeviceActivationAccountId:'3000107825',g_GOATDeviceActivationExpiresAtMs:(1_800_000_000+900)*1000,
  g_GOATDeviceActivationState:2,GOAT_DEVICE_ACTIVATION_BLOCKED:4,URL_API:'https://goatedge.ai',
  TimeGMT:()=>1_800_000_000,TimeLocal:()=>1_800_000_000+7200,TIME_MINUTES:2,
  TimeToString:(t)=>new Date(t*1000).toISOString().slice(11,16),HidePrompt:()=>{},ShowPrompt:(...a)=>prompts.push(a)};
vm.createContext(c);
for(const name of ['GOATDeviceActivationShowCode','GOATDeviceActivationShowRetry','GOATDeviceActivationShowNetworkHelp'])vm.runInContext(extract(name),c);
c.GOATDeviceActivationShowCode('ABCD-2345','https://goatedge.ai/user-portal?tab=ea');
const [title,line1,line2,link]=prompts.pop();
check(()=>assert.equal(title,'Connection code: ABCD-2345','the code is the hero line'));
check(()=>assert.equal(link,'https://goatedge.ai/user-portal?tab=ea#ea-connect=ABCD-2345'));
check(()=>{const url=new URL(link);assert.equal(url.searchParams.get('tab'),'ea');assert.equal(url.hash,'#ea-connect=ABCD-2345');
  assert.ok(![...url.searchParams.keys()].some(k=>k!=='tab'),'the code never travels in the query string');});
check(()=>assert.match(line1,/MT5 account 3000107825/));
check(()=>assert.match(line2,/Valid until 10:15\.$/),'expiry is an absolute local time (15 min after now)');
check(()=>assert.ok([title,line1,line2,link].every(text=>text.length<=63),'MT5 cuts chart edit text at 63 characters'));
c.GOATDeviceActivationShowRetry('The connection code expired; getting a new one.');
check(()=>assert.deepEqual(prompts.pop(),['GOAT is waiting to connect','The connection code expired; getting a new one.','GOAT is safely paused and retries by itself.','']));
c.g_GOATDeviceActivationState=4;c.GOATDeviceActivationShowRetry('x');
check(()=>assert.match(prompts.pop()[2],/until this is fixed and re-attached/));
c.GOATDeviceActivationShowNetworkHelp();
check(()=>assert.equal(prompts.pop()[3],'https://goatedge.ai','the WebRequest card still shows the URL to allow'));
// Every chart string says "connection code"; the server contract stays pinned.
const strings=[...src.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(m=>m[1]);
check(()=>assert.ok(!strings.some(s=>/pairing code/i.test(s)),'no "pairing code" left on the chart'));
check(()=>assert.ok(src.includes('verification_url=="https://goatedge.ai/user-portal?tab=ea"'),'server verification URL contract is unchanged'));
check(()=>assert.ok(src.includes('"#ea-connect="+user_code'),'the fragment is composed only from the validated code'));
const retries=[...src.matchAll(/GOATDeviceActivationShowRetry\("([^"]+)"\)/g)].map(m=>m[1]);
check(()=>assert.ok(retries.length>=8&&retries.every(s=>s.length<=60),'retry details fit one line'));
console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
