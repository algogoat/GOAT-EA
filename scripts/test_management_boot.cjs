// Executes production MQL functions with deterministic MT5 adapters, not a second policy.
// Syntax adaptation is explicit. This is not a native terminal/broker rehearsal.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.env.GOAT_TEST_ROOT || path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8');
const main=read(process.env.GOAT_TEST_MAIN || 'GOAT V1.48.mq5'),boot=read('GOATManagementBoot.mqh'),recovery=read('GOATSequenceRecovery.mqh');
function extract(src,name){
 const start=src.search(new RegExp('\\b(?:bool|void|string|int|double) '+name+'\\('));assert(start>=0,name);
 const begin=src.indexOf('{',start);let depth=1,end=begin+1;
 for(;depth;end++){if(src[end]==='{')depth++;if(src[end]==='}')depth--;assert(end<src.length);}
 return src.slice(start,end);
}
function adapt(src){
 return src.replace(/\bstatic /g,'').replace(/\/\/[^\n]*/g,'')
 .replace(/\b(?:bool|void|string|int|double) (\w+)\(([^)]*)\)/g,(_,n,args)=>`function ${n}(${args.split(',').filter(x=>x.trim()).map(x=>x.trim().replace(/\[\]/g,'').replace(/^(?:const )?\w+\s*&?/,'')).join(',')})`)
 .replace(/\b(?:const )?(?:ulong|long|uint|int|bool|double|string|char) (\w+)\[\]/g,'let $1=[]')
 .replace(/,(\w+)\[\]/g,',$1=[]')
 .replace(/\b(?:const )?(?:ulong|long|uint|int|bool|double|string|char|CTrade) /g,'let ')
 .replace(/let (\w+);/g,'let $1=0;')
 .replace(/\(string\)(\w+\(\))/g,'String($1)')
 .replace(/\(string\)([A-Za-z_][\w.]*)/g,'String($1)')
 .replace(/\((?:int|long|ulong|uint|bool|double)\)/g,'')
 .replace(/seq\.(\w+)\[i\]=StringToDouble/g,'seq.$1[i]=StringToDouble')
 .replace('GOATBuildAuthenticatedRequestHeaders(headers)','((headers=buildHeaders())!==null)')
 .replace('StringTrimLeft(reply);StringTrimRight(reply);','reply=reply.trim();')
 .replace('let Trade=0;','let Trade=new TradeAdapter();');
}
let passed=0;
function test(name,fn){try{fn();passed++;}catch(e){e.message=name+': '+e.message;throw e;}}
const scalarFields={bool:'Active Traded Trailing Virtual Retrace_Triggered GuardRealStarted BiasRescueActive BiasRescueBEProtected',int:'dir Level_Count Trades_Count BiasRescuePositiveAdds',double:'Level_Last Level_Retrace Level_Lock Level_TP Level_SL Level_TSL Level_Entry LotsTotal Size_Grid Size_Lock Size_TP Size_SL Size_TSL StartLots PeakLots PeakCumLots ScaleFactor SequenceRealizedPL BiasRescueBEPrice BiasRescueSLPrice'};
function sequence(dir=0){const s={TradeLevels:[],LotsRaw:[],LotsNorm:[],LotsCum:[],Distances:[],Desc:'Test'};for(const [type,fields] of Object.entries(scalarFields))for(const f of fields.split(' '))s[f]=type==='bool'?false:0;s.dir=dir;return s;}
function harness({status=200,reply='9271 - yes',ai=false,feed=true}={}){
 let clock=1000,account=9271,server='Demo',selected=null,requests=0;const positions=new Map(),events=[];
 const c={g_GOATManager:true,g_GOATManagerReady:true,g_GOATManagementTimerPass:false,g_GOATWireHealthy:true,g_GOATRecoveryDegraded:false,g_GOATRecoveryWriteFailed:false,
 g_GOATManagerAccount:9271,g_GOATManagerServer:'Demo',g_GOATAuthUntil:0,g_GOATAuthNext:0,g_GOATAuthReason:'AUTH_PENDING',g_GOATAuthFailures:0,MathMin:Math.min,MathPow:Math.pow,
 Mode_Bias:ai?1:0,Bias_Disabled:0,Bias_Display:2,GOATBiasWireV2:{EntryFeedReady:()=>feed},
 ACCOUNT_LOGIN:1,ACCOUNT_SERVER:2,ACCOUNT_EQUITY:3,MQL_TESTER:4,MQL_OPTIMIZATION:5,MQL_FORWARD:6,
 POSITION_MAGIC:10,POSITION_SYMBOL:11,POSITION_TYPE:12,POSITION_VOLUME:13,POSITION_SL:14,POSITION_TP:15,POSITION_PROFIT:16,POSITION_SWAP:17,
 SYMBOL_TRADE_STOPS_LEVEL:20,SYMBOL_TRADE_FREEZE_LEVEL:21,OP_BUY:0,OP_SELL:1,OP_BUYSELL:2,
 WHOLE_ARRAY:-1,CP_UTF8:65001,URL_API:'https://fixture.invalid',
 g_PerformanceProfileTester:false,Sequence_MLPS_Hard_Close:true,Risk:100,MAGIC1:123,_Symbol:'EURUSD',
 _Point:0.00001,_Digits:5,bid:1.11,ask:1.1101,TSL_Size_:10,Mode_Operation:0,Operation_Standard:0,Max_Seq_Levels:99,Max_Seq_Trades:10,
 g_PerfMLPSUS:0,g_PerfMLPSCalls:0,g_PerfTrailingUS:0,g_PerfTrailingCalls:0,TSLmodifyErrors:0,TSLmodifieds:0,g_TSLBuySkipped:0,g_TSLSellSkipped:0,
 clrBlue:0,STYLE_DASHDOT:0,TimeCurrent:()=>1800000000,
 TERMINAL_CONNECTED:99,TerminalInfoInteger:()=>true,AccountInfoInteger:()=>account,AccountInfoString:()=>server,MQLInfoInteger:()=>false,GetTickCount64:()=>clock,ChartID:()=>123,
 Print:(...x)=>events.push(['log',...x]),PrintFormat:(...x)=>events.push(['log',...x]),Comment:()=>{},
 StringLen:s=>s.length,IntegerToString:v=>String(typeof v==="boolean"?Number(v):v),StringToInteger:s=>Number.parseInt(s,10),StringToDouble:Number,
 DoubleToString:(n,d)=>Number(n).toFixed(d),MathIsValidNumber:Number.isFinite,MathAbs:Math.abs,MathMax:Math.max,
 StringToCharArray:(s,a)=>a.push(...Buffer.from(s+'\0')),CharArrayToString:a=>Buffer.from(a).toString(),
 StringSplit:(s,delimiter,a)=>{a.push(...s.split(delimiter));return a.length;},ArraySize:a=>a.length,
 ArrayResize:(a,n)=>{while(a.length<n)a.push({ticket:0,price_level:0,price_trade:0,sl:0,tp:0,lots:0});a.length=n;return n;},
 buildHeaders:()=> 'opaque-fixture',WebRequest:(m,url,h,timeout,b,r)=>{requests++;assert.equal(timeout,1000);r.push(...Buffer.from(reply));return status;},
 PositionSelectByTicket:t=>{selected=positions.get(t);return !!selected;},PositionGetDouble:k=>selected?.[k]??0,
 PositionGetInteger:k=>selected?.[k]??0,PositionGetString:k=>selected?.[k]??'',SymbolInfoInteger:()=>10,NormalizeDouble:(x,d)=>Number(x.toFixed(d)),
 FindNumberOfPositions:d=>[...positions.values()].filter(p=>(d===2||p[12]===d)&&p[10]===123&&p[11]==='EURUSD').length,
 CloseAllPositions:d=>{for(const [id,p] of positions)if(p[12]===d&&p[10]===123&&p[11]==='EURUSD'){events.push(['exit',id]);positions.delete(id);}},
 GoatPerformanceRecord:()=>{},HLineCreate:()=>{},Digits:()=>5};
 c.TradeAdapter=class{PositionModify(t,sl,tp){const p=positions.get(t);if(!p)return false;p[14]=sl;p[15]=tp;events.push(['modify',t,sl,tp]);return true;}};
 vm.createContext(c);
 for(const n of ['GOATCanAddRisk','GOATManagementStatus','GOATManagementAuthPoll'])vm.runInContext(adapt(extract(boot,n)),c);
 for(const n of ['GOATEncodeSequence','GOATDecodeSequence','GOATSequenceMatchesBroker'])vm.runInContext(adapt(extract(recovery,n)),c);
 for(const n of ['EnforceSequenceMLPS','CloseSequencePositions','TrailingStoploss']){
   // Class fields are implicit names in MQL. Resolve them explicitly to this in JS.
   let code=adapt(extract(main,n));
   const names=[...Object.values(scalarFields).join(' ').split(' '),'Desc','TradeLevels','CurrentSequencePL','CloseSequencePositions','End_Sequence','IsBiasRescueBEReached','IsBiasRescueStopLegal','TighterBiasStop'];
   for(const field of names)code=code.replace(new RegExp('(?<![.\\w])'+field+'\\b','g'),`this.${field}`);
   code=code.replace(`function this.${n}(`,`function ${n}(`).replace("C'225,68,29'",'0');
   vm.runInContext(code,c);
 }
 function attach(s){s.EnforceSequenceMLPS=c.EnforceSequenceMLPS;s.CloseSequencePositions=c.CloseSequencePositions;s.TrailingStoploss=c.TrailingStoploss;s.CurrentSequencePL=()=>s.SequenceRealizedPL+[...positions.values()].filter(p=>p[12]===s.dir&&p[10]===123).reduce((a,p)=>a+p[16],0);s.End_Sequence=()=>{s.Active=s.Traded=false;};return s;}
 function position(t,dir,profit=-101){positions.set(t,{10:123,11:'EURUSD',12:dir,13:0.1,14:dir?1.13:1.08,15:dir?1.07:1.14,16:profit,17:0});}
 function restart(dir){
   const before=sequence(dir);Object.assign(before,{Active:true,Traded:true,GuardRealStarted:true,Level_Count:1,Trades_Count:1,Level_Last:1.10,Level_Entry:1.10,Level_Lock:1.105,Size_TSL:0.001,Size_Lock:0.005,Size_Grid:0.001});
   before.TradeLevels=[{ticket:77,price_level:1.10,price_trade:1.10,sl:1.08,tp:1.14,lots:0.1}];
   before.LotsRaw=[0.1];before.LotsNorm=[0.1];before.LotsCum=[0.1];before.Distances=[0];
   const encoded=c.GOATEncodeSequence(before),after=sequence(dir);
   assert(c.GOATDecodeSequence(encoded,after));assert.equal(c.GOATEncodeSequence(after),encoded);
   c.g_GOATAuthUntil=0;position(77,dir);assert(c.GOATSequenceMatchesBroker(after,dir));return attach(after);
 }
 return {c,events,positions,restart,position,setClock:x=>clock=x,setAccount:x=>account=x,setServer:x=>server=x,requests:()=>requests,setTransport:(s,r)=>{status=s;reply=r;}};
}
for(const [name,options] of Object.entries({auth_failure:{status:401},entitlement_expired:{reply:'no'},server_outage:{status:-1},build_revoked:{status:403}})){
 for(const dir of [0,1]){
   test(`${name}: restart with ${dir?'sell':'buy'} still executes loss exit`,()=>{const h=harness(options),seq=h.restart(dir);h.c.GOATManagementAuthPoll();assert.equal(h.c.GOATCanAddRisk(),false);assert.equal(seq.EnforceSequenceMLPS('restart fixture'),true);assert.equal(h.positions.size,0);assert(h.events.some(x=>x[0]==='exit'));});
   test(`${name}: trailing modification survives restart`,()=>{const h=harness(options),seq=h.restart(dir);h.c.GOATManagementAuthPoll();seq.TrailingStoploss();assert(h.events.some(x=>x[0]==='modify'));assert.equal(h.positions.get(77)[15],dir?1.07:1.14);assert.equal(h.c.GOATCanAddRisk(),false);});
 }
}
test('AI OFF never requires AI feed',()=>{const h=harness({feed:false});h.c.GOATManagementAuthPoll();assert(h.c.GOATCanAddRisk());});
test('auth gate leaves AI decisions to unchanged existing policy',()=>{const h=harness({ai:true,feed:false});h.c.GOATManagementAuthPoll();assert(h.c.GOATCanAddRisk());});
test('grant expires monotonically without a timer event',()=>{const h=harness();h.c.GOATManagementAuthPoll();h.setClock(46001);assert(!h.c.GOATCanAddRisk());});
test('restart never restores authorization from disk',()=>{const h=harness();h.c.GOATManagementAuthPoll();h.restart(0);assert(!h.c.GOATCanAddRisk());});
test('strict account-bound parser rejects ambiguous success',()=>{for(const reply of ['999 - yes','9271 yes','bad9271 - yes','yes','']){const h=harness({reply});h.c.GOATManagementAuthPoll();assert(!h.c.GOATCanAddRisk());}});
test('account or server drift blocks send',()=>{const h=harness();h.c.GOATManagementAuthPoll();h.setAccount(999);assert(!h.c.GOATCanAddRisk());h.setAccount(9271);h.setServer('Other');assert(!h.c.GOATCanAddRisk());});
test('checkpoint failure and degraded legacy recovery block entries',()=>{const h=harness();h.c.GOATManagementAuthPoll();h.c.g_GOATRecoveryWriteFailed=true;assert(!h.c.GOATCanAddRisk());h.c.g_GOATRecoveryWriteFailed=false;h.c.g_GOATRecoveryDegraded=true;assert(!h.c.GOATCanAddRisk());});
test('foreign magic, volume drift and direction cannot be recovered as this sequence',()=>{for(const [key,value] of [[10,999],[13,0.2],[12,1]]){const h=harness(),s=h.restart(0);h.positions.get(77)[key]=value;assert(!h.c.GOATSequenceMatchesBroker(s,0));}});
test('truncated checkpoints are rejected',()=>{const h=harness(),s=h.restart(0),encoded=h.c.GOATEncodeSequence(s);for(const size of [0,10,encoded.length-30])assert(!h.c.GOATDecodeSequence(encoded.slice(0,size),sequence()));});
test('trade submission has a final exposure gate before broker send',()=>{const f=extract(main,'OpenPosition');assert(f.indexOf('!GOATCanAddRisk()')<f.indexOf('OrderSend('));assert.equal((main.match(/OrderSend\(request,result\)/g)||[]).length,2);});
test('negative-lot unwind precedes entry gate',()=>{const f=extract(main,'Add_Level');assert(f.indexOf('if(closeLots(lotsToCut))')<f.indexOf('if(!GOATCanAddRisk()) return false;'));});
test('trading initialization skips activation and completes restoration',()=>{const f=extract(main,'OnInit');assert(f.includes('if(!test_context && !g_GOATManager)'));assert(f.includes('if(LicenseKey==LICENSE_VALID || g_GOATManager)'));assert(f.indexOf('Seq_Buy.Init')<f.indexOf('GOATTryManagementRecovery()'));const r=extract(recovery,'GOATTryManagementRecovery');assert(r.indexOf('GOATRestoreManagement()')<r.indexOf('g_GOATManagerReady=true'));});
test('no calendar expiry remains in current entrypoint',()=>{assert(!main.includes('Expiry'));assert(read('GOAT_Inputs_Definitions.mqh').includes('#ifndef GOAT_MANAGEMENT_ONLY_BOOT\r\ndatetime Expiry'));});
test('management precedes bounded auth/feed IO',()=>{const f=extract(main,'OnTimer');assert(f.indexOf('OnTick();')<f.indexOf('GOATManagementAuthPoll();'));assert(main.includes('GetState(Symbol(),control_tower_state)')); });
test('timer management cannot create an entry from an old quote',()=>{const h=harness();h.c.GOATManagementAuthPoll();h.c.g_GOATManagementTimerPass=true;assert(!h.c.GOATCanAddRisk());});
for(const status of [-1,401,403,409,429,500,503])test('failed refresh clears a prior grant: '+status,()=>{const h=harness({status});h.c.g_GOATAuthUntil=999999;h.c.GOATManagementAuthPoll();assert.equal(h.c.g_GOATAuthUntil,0);assert(!h.c.GOATCanAddRisk());});
test('missing credential performs no network request',()=>{const h=harness();h.c.buildHeaders=()=>null;h.c.GOATManagementAuthPoll();assert.equal(h.requests(),0);assert(!h.c.GOATCanAddRisk());});
// Execute production checkpoint IO with each native storage boundary failing.
for(const fault of [null,'hash','open','short-write','flush','move','readback'])test('checkpoint boundary '+fault,()=>{
 const h=harness(),c=h.c;const writes=[];let stored='',err=0;
 Object.assign(c,{g_GOATRecoveryPath:'fixture.state',g_GOATRecoverySettings:'inputs',g_GOATRecoveryLast:'',Seq_Buy:h.restart(0),Seq_Sell:sequence(1),
  FILE_WRITE:1,FILE_READ:2,FILE_TXT:4,FILE_UNICODE:8,FILE_REWRITE:16,INVALID_HANDLE:-1,
  hash:s=>fault==='hash'?'':require('node:crypto').createHash('sha256').update(s).digest('hex'),
  FileOpen:(p,flags)=>{writes.push(['open',p]);return fault==='open'?-1:flags===14?2:1;},
  FileWriteString:(id,s)=>{stored=s;return fault==='short-write'?2:s.length*2;},FileFlush:()=>{if(fault==='flush')err=1;},
  ResetLastError:()=>err=0,GetLastError:()=>err,FileClose:()=>{},FileMove:()=>{writes.push(['move']);return fault!=='move';},FileReadString:()=>fault==='readback'?'torn':stored});
 let code=adapt(extract(recovery,'GOATSaveManagement')).replace('GOATSha256Utf8(payload,digest)','((digest=hash(payload))!=="")');vm.runInContext(code,c);
 c.GOATSaveManagement();assert.equal(c.g_GOATRecoveryWriteFailed,!!fault);
 if(fault){assert.equal(c.g_GOATRecoveryLast,'');assert(!c.GOATCanAddRisk());assert(c.Seq_Buy.EnforceSequenceMLPS('storage failure'));}
 else{assert(c.g_GOATRecoveryLast);const before=writes.length;c.GOATSaveManagement();assert.equal(writes.length,before);}
});
test('recovery codec covers every persisted sequence field and array',()=>{
 const h=harness(),s=h.restart(0);Object.assign(s,{Trailing:true,Retrace_Triggered:true,BiasRescueActive:true,BiasRescueBEProtected:true,BiasRescuePositiveAdds:2,SequenceRealizedPL:24.125,Level_Retrace:1.0999,Level_TSL:1.1077,PeakLots:0.2,PeakCumLots:0.35,ScaleFactor:0.9});
 const saved=h.c.GOATEncodeSequence(s),restored=sequence();assert(h.c.GOATDecodeSequence(saved,restored));assert.equal(h.c.GOATEncodeSequence(restored),saved);
});
test('disconnected boot defers state writes without failing initialization',()=>{
 const h=harness(),c=h.c;let restored=0,saved=0;c.g_GOATManagerReady=false;c.TerminalInfoInteger=()=>false;
 c.GOATRestoreManagement=()=>restored++;c.GOATSaveManagement=()=>saved++;
 vm.runInContext(adapt(extract(recovery,'GOATTryManagementRecovery')),c);
 assert.equal(c.GOATTryManagementRecovery(),false);assert.equal(restored,0);assert.equal(saved,0);
 c.TerminalInfoInteger=()=>true;assert.equal(c.GOATTryManagementRecovery(),true);assert.equal(restored,1);assert.equal(saved,1);
 assert.equal(c.GOATTryManagementRecovery(),true);assert.equal(restored,1);
});
for(const fault of [null,'checksum','inputs','account','volume','oversize'])test('production restore envelope '+fault,()=>{
 const h=harness(),c=h.c,hash=s=>require('node:crypto').createHash('sha256').update(s).digest('hex');
 const before=h.restart(0),sell=sequence(1),identity='9271|Demo|EURUSD|123|123',key=hash(identity);
 const binding=hash(key+'|'+(fault==='inputs'?'other-inputs':'inputs'));
 let payload=binding+'|'+c.GOATEncodeSequence(before)+'|'+c.GOATEncodeSequence(sell)+'|0';
 let record=(fault==='checksum'?'wrong':hash(payload))+'|'+payload,fallbacks=0;
 c.Seq_Buy=sequence(0);c.Seq_Sell=sequence(1);c.Seq_Sell.End_Sequence=()=>{};
 Object.assign(c,{g_GOATRecoveryPath:'',g_GOATRecoverySettings:'',GOATRecoverySettings:()=>'inputs',hash,
 FILE_READ:1,FILE_TXT:2,FILE_UNICODE:4,INVALID_HANDLE:-1,FileOpen:p=>fault==='account'?-1:1,
 FileSize:()=>fault==='oversize'?3000000:record.length*2,FileReadString:()=>record,FileClose:()=>{},
 GOATRecoverBrokerSequence:()=>{fallbacks++;c.g_GOATRecoveryDegraded=true;}});
 if(fault==='volume')h.positions.get(77)[13]=0.05;
 let code=adapt(extract(recovery,'GOATRestoreManagement'))
 .replace('GOATSha256Utf8(identity,key)','((key=hash(identity))!=="")')
 .replace('GOATSha256Utf8(key+"|"+g_GOATRecoverySettings,binding)','((binding=hash(key+"|"+g_GOATRecoverySettings))!=="")')
 .replace('GOATSha256Utf8(payload,digest)','((digest=hash(payload))!=="")');
 vm.runInContext(code,c);c.GOATRestoreManagement();assert.equal(fallbacks,fault?2:0);
 if(!fault)assert.equal(c.GOATEncodeSequence(c.Seq_Buy),c.GOATEncodeSequence(before));
});
test('all current inputs participate in the recovery fingerprint',()=>{
 const defs=read('GOAT_Inputs_Definitions.mqh').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
 const fingerprint=extract(recovery,'GOATRecoverySettings');
 for(const m of defs.matchAll(/^\s*s?input\s+\w+\s+(\w+)\s*=/gm))assert(fingerprint.includes(m[1]),m[1]);
});
test('retry backoff is bounded and deferred calls do not send',()=>{
 const h=harness({status:503});let previous=0;
 for(let i=0;i<10;i++){h.c.GOATManagementAuthPoll();const delay=h.c.g_GOATAuthNext-previous;assert(delay<=301000);assert(!h.c.GOATCanAddRisk());const sent=h.requests();h.c.GOATManagementAuthPoll();assert.equal(h.requests(),sent);previous=h.c.g_GOATAuthNext;h.setClock(previous);}
});
test('recovery resumes permission without restart and resets failure backoff',()=>{
 const h=harness({status:503});h.c.GOATManagementAuthPoll();assert(!h.c.GOATCanAddRisk());
 h.setClock(h.c.g_GOATAuthNext);h.setTransport(200,'9271 - yes');h.c.GOATManagementAuthPoll();
 assert(h.c.GOATCanAddRisk());assert.equal(h.c.g_GOATAuthFailures,0);
 h.setClock(h.c.g_GOATAuthNext);h.setTransport(403,'no');h.c.GOATManagementAuthPoll();
 assert(!h.c.GOATCanAddRisk());assert.equal(h.c.g_GOATAuthFailures,1);
});
test('management-only is explicit in chart status',()=>{
 assert(boot.includes('"MANAGEMENT-ONLY: "'));assert(!boot.includes('EntryFeedReady'));
});
test('AI wire is unchanged against the admitted R2 source',()=>{
 const baseline=require('node:child_process').execFileSync('git',['show',(process.env.GOAT_TEST_BASE || '6705df9')+':GOATAIWireV2.mqh'],{cwd:path.join(__dirname,'..'),encoding:'utf8'});
 assert.equal(read('GOATAIWireV2.mqh').replace(/\r\n/g,'\n'),baseline.replace(/\r\n/g,'\n'));
});
console.log(JSON.stringify({passed,productionFunctions:true,nativeExecution:false}));
