// Executes the production MQL core after syntax-only conversion. Workers use
// SharedArrayBuffer/Atomics as the terminal-global CAS adapter, not a second policy.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {Worker,isMainThread,parentPort,workerData}=require('node:worker_threads');
const source=fs.readFileSync(path.join(__dirname,'..','GOAT_DirectionGuardCore.mqh'),'utf8');
const code=source.replace(/bool (GoatGuard\w+)\(const string key,const double token,const int direction\)/g,'function $1(key,token,direction)').replace(/double owner=/g,'let owner=');
function policy(state,hook=()=>{}) {
 const i=key=>key==='B'?0:1;
 const api={
  GuardStoreEnsure:key=>{Atomics.compareExchange(state,i(key),-1,0);return true;},
  GuardStoreRead:key=>Atomics.load(state,i(key)),
  GuardStoreCAS:(key,value,expected)=>Atomics.compareExchange(state,i(key),expected,value)===expected,
  GuardOwnerAlive:token=>Atomics.load(state,8+token)!==0,
  GuardOwnerPending:(token,dir)=>Atomics.load(state,24+token*2+dir)!==0,
  GuardActualExposure:dir=>{hook(dir);return Atomics.load(state,4+dir)!==0;},
 };
 vm.runInNewContext(code+'\nthis.claim=GoatGuardClaim;this.release=GoatGuardRelease;',api);
 return api;
}
function adapter(state) {
 const text=fs.readFileSync(path.join(__dirname,'..','GOAT_DirectionGuard.mqh'),'utf8');
 function extract(name){
  const declaration=new RegExp('(?:bool|void) '+name+'\\(').exec(text);assert(declaration);
  const start=declaration.index+declaration[0].indexOf(' '),begin=text.indexOf('{',start);let depth=1,end=begin+1;
  while(depth&&end<text.length){if(text[end]==='{')depth++;if(text[end]==='}')depth--;end++;}
  let f='function'+text.slice(start,end);
  return f.replace(/const (?:int|bool|uint|ulong) /g,'').replace(/\b(?:int|string|bool|double) (\w+)=/g,'let $1=').replace(/\((?:int|ulong)\)/g,'');
 }
 const api=policy(state);
 Object.assign(api,{
  g_direction_guard_token:1,g_direction_guard_held:[false,false],g_direction_guard_keys:['B','S'],g_direction_guard_pending_order:[0,0],
  g_direction_guard_tracking:[false,false],g_direction_guard_manual_reconcile:[false,false],
  g_direction_guard_current_request:false,
  DashboardExposurePolicyMode:1,GOAT_EXPOSURE_SYMBOL_DIRECTION:1,OP_BUY:0,OP_SELL:1,MQL_TESTER:1,TERMINAL_CONNECTED:1,
  MQLInfoInteger:()=>true,TerminalInfoInteger:()=>true,GoatPortfolioGVName:()=>'',GlobalVariableCheck:()=>false,
  GoatDirectionGuardInit:()=>true,GoatDirectionGuardStatus:()=>{},GoatGuardOwnerKey:(token,field)=>24+token*2+(field==='PB'?0:1),
  GlobalVariableSet:(key,value)=>{state[key]=value;return 1;},GoatGuardClaim:api.claim,GoatGuardRelease:api.release,
  TRADE_RETCODE_DONE:10009,TRADE_RETCODE_DONE_PARTIAL:10010,
  ACCOUNT_MARGIN_MODE:10,ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:2,marginMode:2,
  GoatGuardDurablePending:dir=>state[62+dir]!==0,
  GoatGuardWritePending:dir=>{state[62+dir]=1;return true;},
  GoatGuardResolvePending:dir=>{state[62+dir]=0;return true;},
  GoatGuardPendingPath:dir=>dir,FileIsExist:dir=>state[62+dir]!==0,
  MAGIC1:123,_Symbol:'EURUSD',DEAL_MAGIC:1,DEAL_SYMBOL:2,DEAL_ENTRY:3,DEAL_ENTRY_IN:0,DEAL_TYPE:4,DEAL_ORDER:5,
  HistoryDealSelect:()=>true,HistoryDealGetString:()=> 'EURUSD',dealOrder:9,
 });
 api.HistoryDealGetInteger=(deal,field)=>({1:123,3:0,4:0,5:api.dealOrder}[field]);
 api.AccountInfoInteger=()=>api.marginMode;
 vm.runInNewContext(['GoatDirectionGuardBegin','GoatDirectionGuardResult','GoatDirectionGuardEnd','GoatDirectionGuardDeal'].map(extract).join('\n'),api);
 return api;
}
if(!isMainThread){
 const state=new Int32Array(workerData.buffer),p=policy(state);
 Atomics.add(state,60,1);Atomics.wait(state,61,0);
 parentPort.postMessage({token:workerData.token,won:p.claim('B',workerData.token,0)});
}else (async()=>{
 let count=0;const test=(name,fn)=>{fn();console.log('PASS '+name);count++;};
 const fresh=()=>{const s=new Int32Array(new SharedArrayBuffer(256));s[0]=s[1]=-1;for(let t=1;t<=8;t++)s[8+t]=1;return s;};
 test('non-destructive initialization and single owner',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));assert(!p.claim('B',2,0));assert.equal(s[0],1);});
 test('winner scaling and partial close retain sequence lock',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));s[4]=1;assert(p.claim('B',1,0));assert(!p.release('B',1,0));assert(!p.claim('B',2,0));assert.equal(s[0],1);});
 test('logical sequence holds while temporarily flat',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));assert(!p.claim('B',2,0));assert(p.claim('B',1,0));});
 test('sequence end permits immediate reentry without cooldown',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));assert(p.release('B',1,0));assert(p.claim('B',2,0));assert(!p.release('B',1,0));});
 test('buy and sell owners independent',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));assert(p.claim('S',2,1));});
 test('restart actual position or pending order prevents orphan reclaim',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));s[9]=0;s[4]=1;assert(!p.claim('B',2,0));s[4]=0;assert(p.claim('B',2,0));});
 test('vanished owner with uncertain request remains blocked even flat',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));s[9]=0;s[26]=1;assert(!p.claim('B',2,0));assert(!p.release('B',1,0));});
 test('definite failed send releases reservation when flat',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));s[26]=1;assert(!p.release('B',1,0));s[26]=0;assert(p.release('B',1,0));assert(p.claim('B',2,0));});
 test('disable cannot erase owner while exposure or request remains',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',1,0));s[4]=1;assert(!p.release('B',1,0));s[4]=0;s[26]=1;assert(!p.release('B',1,0));s[26]=0;assert(p.release('B',1,0));});
 test('fresh reservation rechecks actual exposure',()=>{const s=fresh();let calls=0;const p=policy(s,()=>{calls++;s[4]=1;});assert(!p.claim('B',1,0));assert.equal(s[0],0);assert.equal(calls,1);});
 test('CAS loser never releases winning token',()=>{const s=fresh(),p=policy(s);assert(p.claim('B',2,0));assert(!p.release('B',1,0));assert.equal(s[0],2);});
 test('toggle on preserves existing sequence and durably tracks its send; toggle off bypasses admission',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,true));assert.equal(s[0],-1);assert.equal(s[62],1);p.GoatDirectionGuardResult(0,10009,true,true);assert.equal(s[62],0);p.DashboardExposurePolicyMode=0;assert(p.GoatDirectionGuardBegin(0,false));assert.equal(s[0],-1);});
 test('broker timeout blocks second send; definitive rejection releases initial claim',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));assert.equal(s[26],1);p.GoatDirectionGuardResult(0,10012,false,false);assert(!p.GoatDirectionGuardBegin(0,false));assert.equal(s[62],1);const rejected=fresh(),q=adapter(rejected);assert(q.GoatDirectionGuardBegin(0,false));q.GoatDirectionGuardResult(0,10006,false,false);assert.equal(rejected[0],0);assert.equal(q.g_direction_guard_held[0],false);});
 test('rejected scaling add does not release a flat active sequence',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));p.GoatDirectionGuardResult(0,10009,true,false);assert(p.GoatDirectionGuardBegin(0,true));p.GoatDirectionGuardResult(0,10006,false,true);assert.equal(s[0],1);assert(p.g_direction_guard_held[0]);});
 test('partial first fill does not admit duplicate sequence before state reconciles',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));s[4]=1;p.GoatDirectionGuardResult(0,10010,false,false);assert(!p.GoatDirectionGuardBegin(0,false));assert.equal(s[0],1);});
 test('only exact accepted broker order clears pending marker',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));p.g_direction_guard_pending_order[0]=8;p.GoatDirectionGuardDeal(1,true,false);assert.equal(s[26],1);p.dealOrder=8;p.GoatDirectionGuardDeal(1,true,false);assert.equal(s[26],0);assert.equal(s[62],0);});
 test('terminal restart retains durable unresolved-send blockade',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));p.GoatDirectionGuardResult(0,10012,false,false);for(let i=0;i<62;i++)s[i]=0;s[0]=s[1]=-1;const restarted=adapter(s);assert.equal(s[62],1);assert(!restarted.GoatDirectionGuardBegin(0,false));assert.equal(s[0],-1);});
 test('uncertain late fill remains manual reconciliation even for an existing sequence',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,true));p.GoatDirectionGuardResult(0,10012,false,true);p.g_direction_guard_pending_order[0]=9;p.GoatDirectionGuardDeal(1,true,false);assert.equal(s[62],1);assert.equal(s[26],1);});
 test('netting account cannot start independent directional ownership',()=>{const s=fresh(),p=adapter(s);p.marginMode=0;assert(!p.GoatDirectionGuardBegin(0,false));assert.equal(s[0],-1);});
 test('disabled-filter unrelated send cannot resolve previous uncertain request',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));p.GoatDirectionGuardResult(0,10012,false,false);p.DashboardExposurePolicyMode=0;assert(p.GoatDirectionGuardBegin(0,false));p.GoatDirectionGuardResult(0,10009,true,false);assert.equal(s[62],1);assert.equal(s[26],1);});
 test('failed durable write prevents send and incomplete marker stays fail closed',()=>{const s=fresh(),p=adapter(s);p.GoatGuardWritePending=()=>false;assert(!p.GoatDirectionGuardBegin(0,false));assert.equal(s[0],0);assert.equal(s[26],0);const partial=fresh(),q=adapter(partial);q.GoatGuardWritePending=()=>{partial[62]=1;return false;};assert(!q.GoatDirectionGuardBegin(0,false));assert.equal(partial[62],1);assert.equal(partial[26],1);});
 test('accepted partial-fill result releases uncertainty but retains sequence ownership',()=>{const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));s[4]=1;p.GoatDirectionGuardResult(0,10010,true,false);assert.equal(s[62],0);assert.equal(s[26],0);assert.equal(s[0],1);assert(p.GoatDirectionGuardBegin(0,true));});
 for(let round=0;round<20;round++){
  const s=fresh(),workers=[],answers=[];
  for(let token=1;token<=8;token++){
   const w=new Worker(__filename,{workerData:{buffer:s.buffer,token}});workers.push(w);
   answers.push(new Promise((resolve,reject)=>{w.once('message',resolve);w.once('error',reject);}));
  }
  while(Atomics.load(s,60)!==8) await new Promise(resolve=>setTimeout(resolve,1));
  Atomics.store(s,61,1);Atomics.notify(s,61,8);
  const results=await Promise.all(answers);assert.equal(results.filter(x=>x.won).length,1);assert.equal(s[0],results.find(x=>x.won).token);
  await Promise.all(workers.map(w=>w.terminate()));
 }
 console.log('PASS 20 rounds x 8 simultaneous independent claims');count++;
 const main=fs.readFileSync(path.join(__dirname,'..','GOAT V1.47.mq5'),'utf8');
 test('actual partial-fill integration preserves confirmed metadata or retains durable recovery',()=>{
  const start=main.indexOf('   if(result.retcode==TRADE_RETCODE_DONE_PARTIAL)',main.indexOf('int OpenPosition('));
  const end=main.indexOf('   Pause_Flag=true;',start);assert(start>0&&end>start);
  const partial=main.slice(start,end).replace('bool mapped=','let mapped=').replace('ulong position_id=','let position_id=').replace(/\(ulong\)/g,'');
  for(const scenario of [{ticket:17,select:true,ok:true},{ticket:0,select:false,ok:false},{ticket:2147483648,select:true,ok:false},{ticket:17,select:true,wrong:true,ok:false}]){
   const s=fresh(),p=adapter(s);assert(p.GoatDirectionGuardBegin(0,false));
   const context={result:{retcode:10010,price:1.23,volume:0.2,order:scenario.wrong?18:17,deal:0},TRADE_RETCODE_DONE_PARTIAL:10010,
    resolvedPositionTicket:scenario.ticket,LastOrderTicket:scenario.ticket,LastOpen:0,Lots_Order:1,ret:1,OP:0,
    POSITION_PRICE_OPEN:1,POSITION_VOLUME:2,PositionSelectByTicket:()=>scenario.select,
    _Symbol:'EURUSD',magic:123,POSITION_IDENTIFIER:3,POSITION_MAGIC:4,POSITION_TYPE:5,POSITION_SYMBOL:6,
    PositionGetString:()=> 'EURUSD',PositionGetInteger:key=>({3:17,4:123,5:0}[key]),
    PositionGetDouble:key=>key===1?1.24:0.19,GoatDirectionGuardStatus:()=>{}};
   vm.runInNewContext(partial,context);
   assert.equal(context.ret,scenario.ok?1:0);
   assert.equal(context.Lots_Order,scenario.ok?0.19:0.2);assert.equal(context.LastOpen,scenario.ok?1.24:1.23);
   p.GoatDirectionGuardResult(0,10010,context.ret>0,false);
   assert.equal(s[62],scenario.ok?0:1);assert.equal(p.g_direction_guard_manual_reconcile[0],!scenario.ok);
  }
 });

 test('EA claim precedes send; lifecycle and transaction hooks are wired',()=>{
  assert.match(main,/GoatDirectionGuardBegin\(OP,guard_previously_traded\)[\s\S]{0,170}OrderSend\(request,result\)/);
  assert.match(main,/if\(!Virtual\) GoatDirectionGuardEnd\(dir\);/);
  assert.match(main,/GoatDirectionGuardDeal\(trans.deal,Seq_Buy.GuardRealStarted,Seq_Sell.GuardRealStarted\)/);
  assert.match(main,/GoatDirectionGuardMaintenance\(Seq_Buy.Active,Seq_Sell.Active\)/);
 });
 test('spread, stop-out and zero-volume exits precede reservation and cannot create phantom pending sends',()=>{
  const open=main.slice(main.indexOf('int OpenPosition('),main.indexOf('bool SetTypeFillingBySymbol('));
  const claim=open.indexOf('GoatDirectionGuardBegin(');
  for(const trigger of ['SYMBOL_SPREAD)>MaxSP','if(StopOut_Flag)','if(MathAbs(lots)<']) assert(open.indexOf(trigger)>=0&&open.indexOf(trigger)<claim);
  assert(open.indexOf('g_direction_guard_send_attempted=false;')<claim);
  assert.match(main,/if\(g_direction_guard_send_attempted\) GoatDirectionGuardResult/);
 });
 console.log(JSON.stringify({passed:count,concurrentRounds:20,claimsPerRound:8,scope:'production core with atomic adapter; not live broker verification'}));
})().catch(e=>{console.error(e);process.exitCode=1;});
