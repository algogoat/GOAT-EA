// B52: the final build's review fixes (the independent read of merge 6ef944f8; Claude-Mac goatai#2750 6705041540).
// - P2, an open single adopted after OnInit (it waits for a demo reading): GoatAdoptPending, the state file is never
//   rewritten while one waits (GoatStateFlush), it takes back its own state section once adopted (GoatStateRestoreLate,
//   from AdoptOpenPositions; GoatStateRestore marks OnInit's pass), and OnInit's manage-only counts it as held
//   (GoatManageOnlyAfterAdopt), as GoatManageOnlyTimer already does;
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
 const pending=({held=true,buy=false,sell=false,buys=0,sells=0}={})=>run(fn('GoatAdoptPending',[],bodyOf(main,'bool GoatAdoptPending()')),
  {OP_BUY:0,OP_SELL:1,MAGIC1:77,GoatSingleAdoptHeld:()=>held,Seq_Buy:{Active:buy},Seq_Sell:{Active:sell},
   FindNumberOfPositions:(op,m)=>{assert.equal(m,77,'this magic');return op===0?buys:op===1?sells:buys+sells;}}).GoatAdoptPending();
 assert.equal(pending({buys:1}),true,'a buy waits for its adoption');
 assert.equal(pending({sells:2}),true,'a sell too');
 assert.equal(pending({buys:1,buy:true}),false,'a running buy sequence holds its own positions');
 assert.equal(pending({buys:1,buy:true,sells:1}),true,'the sell side still waits');
 assert.equal(pending({held:false,buys:1}),false,'no hold (the grid, the tester, a demo reading): nothing waits');
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
 assert.equal(flush(true),0,'an adoption waits: never rewritten, not even forced (OnDeinit)');
 ok();
}

// ---------------------------------------------------------------- 4. OnInit's manage-only counts an unadopted position as held
{
 const NONE=define('GOAT_MANAGE_NONE'),REFUSED=define('GOAT_MANAGE_LICENCE_REFUSED'),EXPIRED=define('GOAT_MANAGE_EXPIRED'),CRED=define('GOAT_MANAGE_CREDENTIAL');
 const after=(state,positions,active=false)=>{const t={announced:0,sleeps:[],activations:0,alerts:[]};
  const c=run(fn('GoatManageOnlyAfterAdopt',[],bodyOf(main,'int GoatManageOnlyAfterAdopt()')),
   {t,g_GoatManageOnly:state,GOAT_MANAGE_NONE:NONE,GOAT_MANAGE_EXPIRED:EXPIRED,GOAT_MANAGE_LICENCE_REFUSED:REFUSED,GOAT_MANAGE_CREDENTIAL:CRED,
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

// ---------------------------------------------------------------- 7. A deferred adoption takes back its state section (live)
{
 const a=single({tester:false,fastSpeed:false});a.run(path_(MON,[[2*H1,1.1000],[2*H1+120,1.1000]]));assert.equal(sends(a).length,1,'live: a single opened');
 const state={positions:JSON.parse(JSON.stringify(a.w.positions)),deals:JSON.parse(JSON.stringify(a.w.deals)),gv:[...a.w.gv],next:[a.w.nextTicket,a.w.nextDeal],time:a.w.time};
 const W=single({tester:false,fastSpeed:false,start:state.time,bid:1.1000,accountSettled:false,world:{preSync:true},
  adopt:(ctx,w)=>{w.positions.push(...state.positions);w.deals.push(...state.deals);for(const [k,v] of state.gv)w.gv.set(k,v);[w.nextTicket,w.nextDeal]=state.next;}});
 assert.equal(W.ctx.Seq_Buy.Active,false,'the account reads unknown (pre-sync): the open single waits for its adoption');
 assert.deepEqual(W.w.lateRestores||[],[],'nothing adopted, nothing restored');
 W.w.preSync=false;W.run(path_(state.time-7,[[20,1.1000],[100,1.1000]]));
 assert.equal(W.ctx.Seq_Buy.Active,true,'the first demo reading adopts it');
 assert.deepEqual(W.w.lateRestores,[0],'and it takes back its own (buy) state section');
 ok();
}

console.log(JSON.stringify({passed,test:'b52_review'}));
