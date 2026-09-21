const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'..','GOATEADeviceActivation.mqh'),'utf8');
function extract(name){const at=src.indexOf(name+'('),start=src.lastIndexOf('\n',at)+1,brace=src.indexOf('{',at);let depth=1,i=brace+1;for(;depth;i++){if(src[i]==='{')depth++;if(src[i]==='}')depth--;}return src.slice(start,i).replace(/^(?:bool|int|void) /,'function ').replace(/const (?:bool|string|int|long) /g,'').replace(/\b(?:long|int|string) (\w+)=/g,'let $1=').replace(/\(ulong\)/g,'');}
const events=[],c={g_GOATDeviceActivationState:1,GOAT_DEVICE_ACTIVATION_BLOCKED:4,GetTickCount64:()=>1000,IntegerToString:String,GOATDeviceActivationStatus:(...args)=>events.push(args),GOATDeviceActivationShowNetworkHelp:()=>{},GOATDeviceActivationShowRetry:()=>{}};
vm.createContext(c);vm.runInContext(extract('GOATDeviceActivationRetrySeconds')+'\n'+extract('GOATDeviceActivationFailure'),c);
for(const code of [400,401,403,404,409,410,422]){events.length=0;c.g_GOATDeviceActivationState=1;c.GOATDeviceActivationFailure(code,0);assert.equal(c.g_GOATDeviceActivationState,4);assert.equal(events[0][3],0);}
c.g_GOATDeviceActivationState=1;c.GOATDeviceActivationFailure(429,0);assert.equal(c.g_GOATDeviceActivationState,1);assert.equal(c.g_GOATDeviceActivationNextAttemptTick,901000);
for(const code of [-1,-2,408,500,503])assert.equal(c.GOATDeviceActivationRetrySeconds(code),60);
events.length=0;c.GOATDeviceActivationFailure(-1,4014);assert.equal(events[0][0],'webrequest_permission_required');
events.length=0;c.GOATDeviceActivationFailure(-1,5203);assert.equal(events[0][0],'network_error');
events.length=0;c.GOATDeviceActivationFailure(409,0,false);assert.equal(events[0][0],'activation_not_pending');
events.length=0;c.GOATDeviceActivationFailure(409,0,true);assert.equal(events[0][0],'build_not_admitted');
// Run the actual persistence helper against failures at every IO boundary.
for(const fault of [null,'seek','write','flush','size','read','mismatch']){
  let stored=0,error=0;
  const io={SEEK_SET:0,ResetLastError:()=>{error=0;},GetLastError:()=>error,
    FileSeek:()=>fault!=='seek',FileWriteLong:(_,value)=>{stored=value;return fault==='write'?4:8;},
    FileFlush:()=>{if(fault==='flush')error=1;},FileSize:()=>fault==='size'?4:8,
    FileReadLong:()=>{if(fault==='read')error=1;return fault==='mismatch'?stored+1:stored;}};
  vm.createContext(io);vm.runInContext(extract('GOATDeviceActivationReserve'),io);
  assert.equal(io.GOATDeviceActivationReserve(1,1234),fault===null,fault);
}
const status=src.slice(src.indexOf('void GOATDeviceActivationStatus'),src.indexOf('int GOATDeviceActivationRetrySeconds'));
for(const secret of ['CredentialCandidate','user_code','response','existing_headers'])assert(!status.includes(secret));
assert(src.includes('if(g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_BLOCKED) return;'));
assert(src.includes('FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON'));
assert(src.indexOf('if(!GOATDeviceActivationReserve(admission,now+60))')<src.indexOf('int status=GOATDeviceActivationPostJson("/api/ea/device/start"'));
assert(src.includes('(length!=0 && length!=8)'));
assert(src.includes('IntegerToString(ChartID())'));
console.log('PASS activation permanent failures, rate limiting, transient retry, permission distinction, credential-free status and host admission contract');
