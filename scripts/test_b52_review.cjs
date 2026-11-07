// B52: the final build's review fixes (the independent read of merge 6ef944f8; Claude-Mac goatai#2750 6705041540).
// - P2, an open single adopted after OnInit (it waits for a demo reading): GoatAdoptPending, the state file is never
//   rewritten while one waits (GoatStateFlush), it takes back its own state section once adopted (GoatStateRestoreLate,
//   from AdoptOpenPositions; GoatStateRestore marks OnInit's pass), and OnInit's manage-only counts it as held
//   (GoatManageOnlyAfterAdopt), as GoatManageOnlyTimer already does, for the single engine only;
// - the second read (P2-1, P2-2): the wait is OnInit's deferral (g_GoatSingleAccountPending), not the account's current
//   reading. On the harness's timer path (GoatTimerBody's order) and on a tick, a pre-sync restart keeps the single's
//   section through the sync; after the settling an orphan position with a disconnect still lets every flush through;
// - P3, Random_Direction with Gate_Recheck=Gate_AtFirstOrder is refused at OnInit (INIT_PARAMETERS_INCORRECT);
// - Claude-Mac's ask: a single held by the feed guard (GoatEntriesHeld) opens nothing and keeps its signal episode armed,
//   so it opens once when the hold lifts with the signal still true, on the real OnTick path (scripts/b50_tick_harness.cjs).
// The other B52 fixes have their tests where their code is: test_b49b_f5.cjs (Gate_Recheck reads B50's entry block),
// test_b50_clock.cjs (the New York clock is refused on a live chart) and test_studio_ea_init_rules.py (the mirror).
// scripts/test_b52_review_mutations.cjs runs this file (and those) on mutated entrypoints (GOAT_EA_MAIN): each must fail.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'')
 .replace(/\bstring\s+(\w+)\[\],(\w+)\[\];/g,'let $1=[],$2=[];')
 .replace(/\b(?:string|int|bool|long|double)\s+(?=\w)/g,'let ');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';
const define=name=>{const m=main.match(new RegExp('^#define '+name+'\\s+(\\d+)\\s*(?://.*)?$','m'));assert.ok(m,'missing #define '+name);return Number(m[1]);};
const run=(names,ctx)=>{vm.createContext(ctx);vm.runInContext(names,ctx);return ctx;};

// ---------------------------------------------------------------- 1. GoatAdoptPending
{
 const pending=({deferred=true,engine=1,buy=false,sell=false,buys=0,sells=0}={})=>run(fn('GoatAdoptPending',[],bodyOf(main,'bool GoatAdoptPending()')),
  {OP_BUY:0,OP_SELL:1,MAGIC1:77,Engine_Mode:engine,Engine_Single:1,g_GoatSingleAccountPending:deferred,Seq_Buy:{Active:buy},Seq_Sell:{Active:sell},
   GoatSingleAdoptHeld:()=>assert.fail('the wait never reads the account\'s current state (second read P2-1)'),
   FindNumberOfPositions:(op,m)=>{assert.equal(m,77,'this magic');return op===0?buys:op===1?sells:buys+sells;}}).GoatAdoptPending();
 assert.equal(pending({buys:1}),true,'a buy waits for its adoption');
 assert.equal(pending({sells:2}),true,'a sell too');
 assert.equal(pending({buys:1,buy:true}),false,'a running buy sequence holds its own positions');
 assert.equal(pending({buys:1,buy:true,sells:1}),true,'the sell side still waits');
 assert.equal(pending({deferred:false,buys:1,sells:1}),false,'after the settling (or never deferred): an orphan never holds a write (second read P2-2)');
 assert.equal(pending({engine:0,buys:1}),false,'the grid engine: nothing waits');
 assert.equal(pending(),false,'no position: nothing waits');
 ok();
}

// ---------------------------------------------------------------- 2. GoatStateRestoreLate, and OnInit's pass marks it
{
 const late=({restored,read=true})=>{const t={reads:0,buy:[],sell:[]};
  const c=run(fn('GoatStateRestoreLate',['dir'],bodyOf(main,'void GoatStateRestoreLate(const int dir)')),
   {OP_BUY:0,OP_SELL:1,g_GoatStateRestored:restored,t,
    GoatStateRead:(k,v)=>{t.reads++;if(!read)return false;k.push('B.start_msc');v.push('1');return true;},
    Seq_Buy:{StateRestore:(k,v)=>t.buy.push([...k])},Seq_Sell:{StateRestore:(k,v)=>t.sell.push([...k])}});
  return c;};
 {const c=late({restored:true});c.GoatStateRestoreLate(0);assert.deepEqual([c.t.reads,c.t.buy.length,c.t.sell.length],[1,1,0],'a late buy takes back its section');
  assert.deepEqual(c.t.buy[0],['B.start_msc'],'from the file');c.GoatStateRestoreLate(1);assert.deepEqual([c.t.buy.length,c.t.sell.length],[1,1],'a late sell its own');}
 {const c=late({restored:false});c.GoatStateRestoreLate(0);assert.deepEqual([c.t.reads,c.t.buy.length],[0,0],'before OnInit\'s GoatStateRestore: nothing (it restores itself)');}
 {const c=late({restored:true,read:false});c.GoatStateRestoreLate(0);assert.deepEqual([c.t.reads,c.t.buy.length],[1,0],'no readable file: nothing');}
 // GoatStateRestore marks OnInit's pass first, even when it has nothing to read.
 const r=run(fn('GoatStateRestore',[],bodyOf(main,'void GoatStateRestore()')),{g_GoatStateRestored:false,g_GoatDayRestorePending:true,GoatStateLive:()=>false});
 r.GoatStateRestore();assert.equal(r.g_GoatStateRestored,true,'OnInit\'s restore has run');assert.equal(r.g_GoatDayRestorePending,false);
 // AdoptOpenPositions hands every adoption to it, after the alert and the disarm, before it reports success.
 const adopt=bodyOf(main,'   bool AdoptOpenPositions()');
 const at=adopt.indexOf('GoatStateRestoreLate(dir);');assert.ok(at>0,'AdoptOpenPositions calls GoatStateRestoreLate(dir)');
 assert.ok(adopt.indexOf('GoatSingleAdoptedDisarm(dir);')<at&&at<adopt.lastIndexOf('return true;'),'after the disarm, before its success');
 // Second read P3-6: OnInit's own adoption block clears the mark first, so its adoptions restore nothing late (and a
 // re-init path that reached it could not restore twice); GoatStateRestore, right after, restores and marks again.
 const init=bodyOf(main,'int OnInit()').split('\n').map(l=>l.trim()).filter(l=>l&&!l.startsWith('//'));
 const k=init.findIndex(l=>l.startsWith('Seq_Buy.AdoptOpenPositions(); Seq_Sell.AdoptOpenPositions();'));assert.ok(k>0,'OnInit adopts');
 assert.match(init[k-1],/^g_GoatStateRestored=false;/,'the mark is cleared right before OnInit\'s adoptions');
 assert.match(init[k+1],/^GoatStateRestore\(\);/,'and GoatStateRestore follows them');
 ok();
}

// ---------------------------------------------------------------- 3. GoatStateFlush waits while an adoption is pending
{
 const flush=pending=>{const t={writes:0};
  const c=run(fn('GoatStateFlush',['force=false'],bodyOf(main,'void GoatStateFlush(const bool force=false)')),
   {t,GoatStateLive:()=>true,g_GoatStateDay:20400,GetTickCount:()=>99999,g_GoatStateWrittenMs:0,GOAT_SQ_FLUSH_MS:define('GOAT_SQ_FLUSH_MS'),
    GoatAdoptPending:()=>pending,GoatStateText:()=>'version=1\n',GoatCloseOwedText:()=>'',g_GoatStateLast:'',g_GoatStateFailed:false,
    AccountInfoInteger:()=>1,ACCOUNT_LOGIN:1,IntegerToString:String,FolderCreate:()=>true,FILE_COMMON:4096,GoatStatePath:()=>'p',
    GoatStateWrite:()=>{t.writes++;return true;},Print:()=>{},Alert:()=>{},g_GoatStateWriteError:0});
  c.GoatStateFlush();c.GoatStateFlush(true);return t.writes;};
 assert.equal(flush(false),1,'no adoption waits: the file is written');
 assert.equal(flush(true),0,'OnInit\'s deferral with an unadopted position: never rewritten, not even forced (OnDeinit), so the old file keeps its section');
 ok();
}

// ---------------------------------------------------------------- 4. OnInit's manage-only counts an unadopted position as held
{
 const NONE=define('GOAT_MANAGE_NONE'),REFUSED=define('GOAT_MANAGE_LICENCE_REFUSED'),EXPIRED=define('GOAT_MANAGE_EXPIRED'),CRED=define('GOAT_MANAGE_CREDENTIAL');
 const after=(state,positions,active=false,engine=1)=>{const t={announced:0,sleeps:[],activations:0,alerts:[]};
  const c=run(fn('GoatManageOnlyAfterAdopt',[],bodyOf(main,'int GoatManageOnlyAfterAdopt()')),
   {t,Engine_Mode:engine,Engine_Single:1,g_GoatManageOnly:state,GOAT_MANAGE_NONE:NONE,GOAT_MANAGE_EXPIRED:EXPIRED,GOAT_MANAGE_LICENCE_REFUSED:REFUSED,GOAT_MANAGE_CREDENTIAL:CRED,
    Seq_Buy:{Active:active},Seq_Sell:{Active:false},OP_BUYSELL:2,MAGIC1:77,FindNumberOfPositions:(op,m)=>{assert.deepEqual([op,m],[2,77]);return positions;},
    INIT_FAILED:1,INIT_SUCCEEDED:0,Alert:s=>t.alerts.push(s),TimeToString:String,Expiry:0,TIME_DATE:1,URL_Web:'u',Sleep:ms=>t.sleeps.push(ms),Print:()=>{},
    GOATDeviceActivationBegin:()=>{t.activations++;return true;},AccountInfoInteger:()=>1,ACCOUNT_LOGIN:1,GOAT_BUILD_ID:'B52-test',
    GoatManageOnlyAnnounce:()=>{t.announced++;}});
  return [c.GoatManageOnlyAfterAdopt(),c.t];};
 for(const s of [EXPIRED,REFUSED,CRED]){
  const [code,t]=after(s,1);assert.equal(code,-1,'state '+s+': an open position not adopted yet is held: init goes on, manage-only');
  assert.deepEqual([t.announced,t.sleeps.length,t.activations],[1,0,0],'state '+s+': announced, no 20 s wait, no replacement');
 }
 assert.equal(after(EXPIRED,0)[0],1,'nothing to manage: an expired build fails, as B49a');
 assert.deepEqual(after(REFUSED,0)[1].sleeps,[20000],'nothing to manage: a refused licence waits 20 s and fails');
 assert.equal(after(CRED,0)[0],0,'nothing to manage: a rejected credential starts the replacement');
 assert.equal(after(EXPIRED,0,true)[0],-1,'a running sequence: held, as before');
 assert.equal(after(NONE,1)[0],-1,'not manage-only: init goes on');
 // The grid engine keeps B49b's rule (second read P3-1): an orphan on a live re-init changes nothing there.
 assert.equal(after(EXPIRED,1,false,0)[0],1,'grid: an expired build with only an orphan fails, as B49b');
 assert.deepEqual(after(REFUSED,1,false,0)[1].sleeps,[20000],'grid: a refused licence waits 20 s and fails');
 assert.equal(after(CRED,1,false,0)[0],0,'grid: a rejected credential starts the replacement');
 ok();
}

// ---------------------------------------------------------------- the harness: one EURUSD single (test_b50_single.cjs's world)
const MON=Date.UTC(2026,9,5)/1000,H1=3600;
function path_(start,points){const ticks=[];for(let k=1;k<points.length;k++){const [t0,p0]=points[k-1],[t1,p1]=points[k];for(let t=t0;t<t1;t+=20)ticks.push([start+t+7,p0+(p1-p0)*(t-t0)/(t1-t0)]);}return ticks;}
const BASE={EMA_Mode:'Trade_Disabled',ADX_Mode:'Trade_Disabled',Mode_Bias:'Bias_Disabled',RSI_Mode:'RSI_OverBS',RSI_Level:70,
 Engine_Mode:'Engine_Single',Single_SL_ATR:1.5,Mode_Lots:'RiskperSeq',Risk:500};
const single=({inputs={},tester=true,fastSpeed=true,world={},adopt,start,bid,accountSettled}={})=>H.build(undefined,{inputs:{...BASE,...inputs},tester,fastSpeed,world,adopt,start,bid,accountSettled,
 indicator:(name,buffer,shift)=>name==='ATR_MA'?(shift===1?0.0010:(shift===0?0.0030:undefined)):(name==='RSI'?25:undefined)});
const sends=W=>W.w.trace.filter(x=>x.op==='OrderSend');

// ---------------------------------------------------------------- 5. Claude-Mac: a held single keeps its episode armed
{
 const W=single();let held=true;W.ctx.GoatEntriesHeld=()=>held;   // the feed guard holding entries (GoatEntriesHeld), then lifting
 const first=path_(MON,[[2*H1,1.1000],[3*H1,1.1000]]),second=path_(MON,[[3*H1,1.1000],[4*H1,1.1000]]);
 W.run(first);
 assert.equal(sends(W).length,0,'held: no single opens on the signal');
 assert.equal(W.ctx.g_GoatSingleArmed[0],true,'held: the buy episode stays armed (a refused open never disarms it)');
 held=false;W.run(second);
 assert.equal(sends(W).length,1,'the hold lifts with the signal still true: the single opens, once');
 assert.equal(W.ctx.g_GoatSingleArmed[0],false,'the open used the episode');
 // Never held: it opens at the signal, as test_b50_single.cjs proves.
 const N=single();N.run(first);assert.equal(sends(N).length,1);
 ok();
}

// ---------------------------------------------------------------- 6. P3: no random benchmark under the first-order gate
{
 const RANDOM={Random_Direction:true,Single_Flat_Only:true,Mode_Trade:'Long_and_Short'};
 let code=null;try{single({inputs:{...RANDOM,Gate_Recheck:'Gate_AtFirstOrder'}});}catch(e){code=e.initCode;}
 assert.equal(code,2,'Random_Direction with Gate_AtFirstOrder: INIT_PARAMETERS_INCORRECT');
 assert.match(main,/Initialization Failed: Random_Direction cannot run with Gate_Recheck=Gate_AtFirstOrder/);
 single({inputs:{...RANDOM,Gate_Recheck:'Gate_Legacy'}});   // the benchmark as before
 single({inputs:{Gate_Recheck:'Gate_AtFirstOrder'}});       // the gate without the benchmark
 ok();
}

// ---------------------------------------------------------------- 7. A pre-sync restart keeps the single's section through the sync
// The harness's timer (GoatTimerBody's order: the flush, then the account watch) and its file model: the EA's own text is
// written, read back and restored (GoatStateFlush, GoatStateRead, GoatStateRestore, GoatStateRestoreLate, StateRestore).
// Second read P2-1: when the account's first demo reading lands on a timer pass, the flush runs before the watch adopts.
const RETRACE=1.0987,ADDS=3;   // markers in the single's section (nothing a single reads)
const PATHS=W=>[...W.w.files.keys()].filter(p=>/^GOAT\\State\\/.test(p));
function liveSingle(){   // a settled live demo with one open buy single and its state file written
 const a=single({tester:false,fastSpeed:false});a.run(path_(MON,[[2*H1,1.1000],[2*H1+120,1.1000]]));assert.equal(sends(a).length,1,'live: a single opened');
 Object.assign(a.ctx.Seq_Buy,{Level_Retrace:RETRACE,BiasRescuePositiveAdds:ADDS});
 a.timer(a.w.time+1);assert.equal(PATHS(a).length,1,'the timer wrote the state file');
 assert.match(a.w.files.get(PATHS(a)[0]),/\nB\.level_retrace=1\.09870000\n[\s\S]*\nB\.rescue_positive_adds=3\n/,'with the single\'s section');
 return a;
}
function restartPreSync(a){   // the terminal restarts before the account has synchronized, the single still open
 const state={positions:JSON.parse(JSON.stringify(a.w.positions)),deals:JSON.parse(JSON.stringify(a.w.deals)),gv:[...a.w.gv],files:[...a.w.files],
  next:[a.w.nextTicket,a.w.nextDeal],time:a.w.time+60};
 const W=single({tester:false,fastSpeed:false,start:state.time,bid:1.1000,accountSettled:false,world:{preSync:true},
  adopt:(ctx,w)=>{w.positions.push(...state.positions);w.deals.push(...state.deals);for(const [k,v] of state.gv)w.gv.set(k,v);for(const [k,v] of state.files)w.files.set(k,v);[w.nextTicket,w.nextDeal]=state.next;}});
 assert.equal(W.ctx.g_GoatSingleAccountPending,true,'OnInit defers the single (the account reads unknown)');
 assert.equal(W.ctx.Seq_Buy.Active,false,'the open single waits for its adoption');
 assert.equal(W.ctx.g_GoatStateRestored,true,'OnInit\'s GoatStateRestore ran');
 W.tick(state.time+1,1.1000);   // as OnInit's own OnTick: the new-day block stamps the day, so flushes are allowed
 assert.ok(W.ctx.g_GoatStateDay>0,'the day is stamped');assert.equal(W.ctx.Seq_Buy.Active,false,'still pre-sync');
 W.timer(state.time+2);assert.equal(W.w.stateWrites||0,0,'pre-sync: the file is not rewritten');
 W.w.preSync=false;   // the account synchronizes: it reads as a demo from here on
 return {W,t:state.time+3,file:PATHS(W)[0],before:W.w.files.get(PATHS(W)[0])};
}
const restored=(W,what)=>{
 assert.equal(W.ctx.Seq_Buy.Active,true,what+': adopted on the first demo reading');
 assert.equal(W.ctx.Seq_Buy.Level_Retrace,RETRACE,what+': the single\'s retrace is back');
 assert.equal(W.ctx.Seq_Buy.BiasRescuePositiveAdds,ADDS,what+': and its counters');
};
{
 const a=liveSingle();
 // Timer first: the flush (still deferred, the single unadopted: skipped), then the watch adopts and restores.
 {const {W,t,file,before}=restartPreSync(a);
  W.timer(t);
  assert.equal(W.w.files.get(file),before,'timer first: the flush before the watch did not rewrite the file');
  restored(W,'timer first');
  W.timer(t+6);assert.equal(W.w.stateWrites,1,'the next pass writes');
  assert.match(W.w.files.get(file),/\nB\.level_retrace=1\.09870000\n/,'and the single\'s section is in it');}
 // Tick first: the tick's watch adopts before anything is written.
 {const {W,t,file,before}=restartPreSync(a);
  W.tick(t,1.1000);assert.equal(W.w.files.get(file),before);
  restored(W,'tick first');
  W.timer(t+1);assert.match(W.w.files.get(file),/\nB\.level_retrace=1\.09870000\n/,'tick first: the next flush keeps the section');}
 // The order the harness ran is the tree's (GoatTimerBody: the flush, then the watch).
 assert.deepEqual(a.C.timerOrder,['GoatStateFlush','GoatSingleAccountWatch'],'GoatTimerBody flushes before the watch');
 ok();
}

// ---------------------------------------------------------------- 8. After the settling, an orphan never stops a write (P2-2)
{
 const S=liveSingle();
 assert.equal(S.ctx.g_GoatSingleAccountPending,false,'settled');
 const p=S.w.positions[0];S.w.positions.push({...p,ticket:p.ticket+77,identifier:p.ticket+77,type:1});   // a sell of this magic no sequence runs
 assert.equal(S.ctx.Seq_Sell.Active,false);
 Object.assign(S.w,{connected:0,accountTradeAllowed:0});   // and the account reads as not tradeable (a disconnect)
 const writes=S.w.stateWrites,file=PATHS(S)[0];
 S.ctx.Seq_Buy.Level_Retrace=1.2345;S.timer(S.w.time+6);
 assert.equal(S.w.stateWrites,writes+1,'the timer\'s flush still writes');
 assert.match(S.w.files.get(file),/\nB\.level_retrace=1\.23450000\n/,'with the running single\'s section');
 S.ctx.Seq_Buy.Level_Retrace=1.3456;S.ctx.GoatStateFlush(true);   // OnDeinit's forced flush
 assert.match(S.w.files.get(file),/\nB\.level_retrace=1\.34560000\n/,'and OnDeinit\'s forced flush too');
 ok();
}

console.log(JSON.stringify({passed,test:'b52_review'}));
