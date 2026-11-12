// The hourly policy touch (GOAT-EA#328 follow-up). MT5 deletes a GlobalVariable nothing accesses for 4 weeks. The
// every-second acknowledgement that dash-ack-once removed also re-set this chart's policy variables; without it a Buy
// Only or paused rule could age out of the terminal's store and come back as "allow both, not paused" at a restart.
// Once per UTC hour the one-second timer re-sets the five policy variables OnInit restores from, each to the value it
// holds, without a flush. The production code runs here from GOAT V1.49.mq5 (the dash-policy-touch block), as
// test_dash_ack_once.cjs runs the bus, against a modelled global-variable store:
// 1. over ticks spanning 3 hours each of the five variables is re-set once an hour, values unchanged, zero flushes;
// 2. a missing variable is never created;
// 3. batch, dashboard, optimization and forward charts, and a chart with no magic, do nothing;
// 4. the value written is the one the variable holds at the touch (a command in between is kept, never undone);
// 5. a failed write is logged once, retried no sooner than a minute later, and the hour stays owed until it succeeds;
// 6. the five names are exactly what OnInit's policy restore reads, and the touch is on the timer, beside the bus.
// test_dash_policy_touch_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN): each must fail.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.join(__dirname,'..');
const clean=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=clean(fs.readFileSync(process.env.GOAT_EA_MAIN||path.join(ROOT,'GOAT V1.49.mq5'),'utf8'));
const header=clean(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8'));
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 const blank=text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.replace(/[^\n]/g,' '));
 let i=blank.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<blank.length;j++){if(blank[j]==='{')depth++;if(blank[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
// As test_dash_ack_once.cjs, plus MQL5's by-reference read: GlobalVariableGet(name,value) fills value and answers bool.
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
 .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'')
 .replace(/GlobalVariableGet\((\w+),(\w+)\)/g,'(([__ok,$2]=gvRead($1)),__ok)');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){let __ok;'+js(body)+'}\n';

const DEF={};
for(const m of header.matchAll(/^#define\s+(GOAT_GV_FIELD_POLICY_\w+)\s+"([^"]*)"/gm)) DEF[m[1]]=m[2];
for(const k of ['GOAT_GV_FIELD_POLICY_PAUSED','GOAT_GV_FIELD_POLICY_TRADE_MASK','GOAT_GV_FIELD_POLICY_EXPOSURE_MODE']) assert.ok(DEF[k],'GOAT_Inputs_Definitions.mqh defines '+k);
const block=(main.match(/\/\/ B55:begin dash-policy-touch\n([\s\S]*?)\/\/ B55:end dash-policy-touch\n/)||[])[1];
assert.ok(block,'the dash-policy-touch block');
const retryMs=Number((block.match(/^#define GOAT_DASH_POLICY_TOUCH_RETRY_MS\s+(\d+)\s*$/m)||[])[1]);
assert.equal(retryMs,60000,'a failed write is retried no sooner than a minute later');
const blockGlobals=block.split('\n').filter(l=>/^(?:datetime|uint|bool)\s+g_goat_dash_policy_\w+=[^()]*;/.test(l)).join('\n');
assert.equal(blockGlobals.split('\n').length,3,'the touch\'s three state variables');

const CHILD=f=>'77|EURUSD|'+f,PORT=n=>'P|'+n;
const PAUSED=CHILD(DEF.GOAT_GV_FIELD_POLICY_PAUSED),MASK=CHILD(DEF.GOAT_GV_FIELD_POLICY_TRADE_MASK),EXPO=CHILD(DEF.GOAT_GV_FIELD_POLICY_EXPOSURE_MODE);
const P_PAUSED=PORT('DashboardPolicyPaused'),P_EXPO=PORT('DashboardExposurePolicyMode');
const FIVE=[PAUSED,MASK,EXPO,P_PAUSED,P_EXPO];
// A paused, Buy Only chart under a non-default exposure rule, plus two variables that are not the touch's.
const policy=()=>new Map([[PAUSED,1],[MASK,1],[EXPO,2],[P_PAUSED,1],[P_EXPO,2],[CHILD('CID'),123456],[PORT('Portfolio_StartTime'),1700000000]]);
const HOUR=3600,H0=Math.floor(1731400000/HOUR)*HOUR;   // a UTC hour boundary

// One EA instance on a chart: `now` is TimeGMT (s); GetTickCount follows it in ms. `failing` names fail their write.
function instance(store,{now=H0,mode=0,optimization=false,forward=false,magic=77}={}){
 const c={...DEF,MAGIC1:magic,Operation_Batch:1,Operation_Dash:2,Mode_Operation:mode,MQL_OPTIMIZATION:1,MQL_FORWARD:2,
  GOAT_DASH_POLICY_TOUCH_RETRY_MS:retryMs,now,start:now,sets:[],flushes:0,prints:[],failing:new Set(),store,
  Symbol:()=>'EURUSD',GoatPortfolioGVName:PORT,GoatChildGVName:(m,s,f)=>m+'|'+s+'|'+f,IntegerToString:String,GetLastError:()=>4501};
 c.MQLInfoInteger=flag=>(flag===1&&optimization)||(flag===2&&forward)?1:0;
 c.TimeGMT=()=>c.now;c.GetTickCount=()=>((c.now-c.start)*1000+5000)>>>0;
 c.GlobalVariableCheck=k=>{const had=store.has(k);if(k===c.vanish)store.delete(k);return had;};   // `vanish`: deleted right after its check
 c.gvRead=k=>store.has(k)?[true,store.get(k)]:[false,0];
 c.GlobalVariableSet=(k,v)=>{c.sets.push([k,v,c.now]);if(c.failing.has(k))return 0;store.set(k,v);return c.now;};
 c.GlobalVariablesFlush=()=>{c.flushes++;};c.Print=s=>c.prints.push(s);
 vm.createContext(c);
 vm.runInContext(js(blockGlobals)+'\n'
  +fn('GoatDashPolicyTouchOne',['dpt_name'],bodyOf(main,'bool GoatDashPolicyTouchOne(const string dpt_name)'))
  +fn('GoatDashPolicyHourlyTouch',[],bodyOf(main,'void GoatDashPolicyHourlyTouch(void)')),c);
 c.ticks=n=>{for(let i=0;i<n;i++){c.GoatDashPolicyHourlyTouch();c.now++;}};   // the 1 s timer (GoatTimerBody)
 c.touches=k=>c.sets.filter(s=>s[0]===k);
 return c;
}
const summary=c=>c.sets.length+' write(s) and '+c.flushes+' flush(es)';

{// 1. Three hours of timer ticks, from an hour boundary: each of the five is re-set at the top of each hour (3 times),
 // to the value it holds; nothing else is written, nothing is flushed, nothing is created or changed.
 const store=policy(),before=new Map(store),c=instance(store);c.ticks(3*HOUR);
 for(const k of FIVE)
  assert.deepEqual(c.touches(k),[[k,before.get(k),H0],[k,before.get(k),H0+HOUR],[k,before.get(k),H0+2*HOUR]],
   k+': '+c.touches(k).length+' re-set(s) over 3 hours of ticks ('+summary(c)+' in all), want one an hour, at its own value');
 assert.deepEqual([c.sets.length,c.flushes,c.prints],[15,0,[]],'3 hours: '+summary(c)+', want 15 writes (5 an hour) and no flush');
 assert.deepEqual([...store],[...before],'no value changed, nothing created');
 // From the middle of an hour: at the first tick, then at each hour boundary.
 const s2=policy(),m=instance(s2,{now:H0+1234});m.ticks(3*HOUR);
 assert.deepEqual(m.touches(MASK).map(s=>s[2]),[H0+1234,H0+HOUR,H0+2*HOUR,H0+3*HOUR],'from mid-hour: the first tick, then each hour');
 assert.equal(m.flushes,0);
 ok();}

{// 2. A missing variable is never created: only what exists is touched.
 const store=new Map([[MASK,1]]),c=instance(store);c.ticks(3*HOUR);
 assert.deepEqual([c.sets.map(s=>s[0]),[...store]],[[MASK,MASK,MASK],[[MASK,1]]],'only the trade mask exists: '+summary(c)+', store size '+store.size+', want 3 writes of it and nothing created');
 const empty=new Map(),e=instance(empty);e.ticks(3*HOUR);
 assert.deepEqual([e.sets,empty.size,e.flushes],[[],0,0],'an empty store: '+summary(e)+', '+empty.size+' variable(s), want nothing written or created');
 // Each of the five on its own (none depends on another).
 for(const k of FIVE){const one=new Map([[k,2]]),o=instance(one);o.ticks(HOUR+1);
  assert.deepEqual([o.sets.map(s=>s.slice(0,2)),[...one]],[[[k,2],[k,2]],[[k,2]]],k+' alone is touched, at its value');}
 // A variable deleted between the touch's check and its read (a dashboard reset) is not re-created, at 0 or otherwise.
 const raced=policy(),r=instance(raced);r.vanish=MASK;r.ticks(HOUR+1);
 assert.deepEqual([r.touches(MASK),raced.has(MASK),r.touches(EXPO).length,r.prints],[[],false,2,[]],'a variable gone between the check and the read stays gone; the others are touched');
 ok();}

{// 3. Batch and dashboard charts, optimization and forward passes, and a chart without a magic: nothing.
 for(const [label,options] of [['batch',{mode:1}],['dashboard',{mode:2}],['optimization',{optimization:true}],['forward',{forward:true}],['no magic',{magic:0}]]){
  const store=policy(),before=[...store],c=instance(store,options);c.ticks(3*HOUR);
  assert.deepEqual([c.sets.length,c.flushes,[...store]],[0,0,before],label+': '+summary(c)+', want nothing');
 }
 ok();}

{// 4. The value written is the one held at the touch: a rule changed between two touches (a dashboard command, another
 // chart) is kept, and the old value is never written back.
 const store=policy(),c=instance(store);c.ticks(HOUR/2);
 store.set(MASK,3);store.set(P_PAUSED,0);store.set(PAUSED,0);   // resumed, both directions
 c.ticks(3*HOUR-HOUR/2);
 assert.deepEqual([c.touches(MASK).map(s=>s[1]),c.touches(P_PAUSED).map(s=>s[1]),c.touches(PAUSED).map(s=>s[1])],[[1,3,3],[1,0,0],[1,0,0]],'the touch writes what the variable holds');
 assert.deepEqual([store.get(MASK),store.get(P_PAUSED),store.get(PAUSED),store.get(EXPO)],[3,0,0,2]);
 // A variable deleted between two touches is not brought back.
 store.delete(EXPO);c.ticks(HOUR);
 assert.equal(store.has(EXPO),false,'a deleted variable stays deleted');
 ok();}

{// 5. A failed write: logged once, the other four still written, retried no sooner than a minute later (not every
 // tick), and the hour stays owed until every write succeeded.
 const store=policy(),c=instance(store);c.failing.add(EXPO);c.ticks(150);
 assert.deepEqual(c.touches(EXPO).map(s=>s[2]),[H0,H0+60,H0+120],'a failing write is retried each minute: tried at '+c.touches(EXPO).map(s=>s[2]-H0).join(', ')+' s');
 assert.deepEqual([c.touches(MASK).length,c.prints.length,c.flushes],[3,1,0],'the others are written with it; one log line');
 assert.match(c.prints[0],/^GOAT policy touch: a write failed for EURUSD \(error 4501\); retrying$/);
 c.failing.clear();c.ticks(HOUR);
 assert.deepEqual(c.touches(EXPO).map(s=>s[2]),[H0,H0+60,H0+120,H0+180,H0+HOUR],'succeeds at the next retry, then waits for the next hour');
 assert.equal(c.prints.length,1);
 // A later failure is logged again (the flag clears on success).
 c.failing.add(MASK);c.ticks(HOUR);assert.equal(c.prints.length,2);
 ok();}

{// 6. The five names are what OnInit's policy restore reads, and the touch runs on the timer beside the bus.
 const onInit=bodyOf(main,'int OnInit()');
 const restore=onInit.slice(onInit.indexOf('if(GlobalVariableCheck(GoatPortfolioGVName("DashboardPolicyPaused")))'),onInit.indexOf('Seq_Buy.Init(OP_BUY,false);'));
 const read=[...restore.matchAll(/GlobalVariableGet\((\w+|GoatPortfolioGVName\("\w+"\))\)/g)].map(m=>m[1]);
 assert.deepEqual(read,['GoatPortfolioGVName("DashboardPolicyPaused")','trade_mask_key','exposure_mode_key','GoatPortfolioGVName("DashboardExposurePolicyMode")'],
  'OnInit restores the pause from the portfolio variable, the trade mask and exposure mode from the chart\'s, and the exposure mode else from the portfolio\'s');
 assert.match(restore,/string trade_mask_key=GoatChildGVName\(MAGIC1,Symbol\(\),GOAT_GV_FIELD_POLICY_TRADE_MASK\);/);
 assert.match(restore,/string exposure_mode_key=GoatChildGVName\(MAGIC1,Symbol\(\),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE\);/);
 const touch=bodyOf(main,'void GoatDashPolicyHourlyTouch(void)');
 const touched=[...touch.matchAll(/GoatDashPolicyTouchOne\((.*?)\)\)/g)].map(m=>m[1]+')');
 assert.deepEqual(touched,['GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_PAUSED)','GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_TRADE_MASK)',
  'GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE)','GoatPortfolioGVName("DashboardPolicyPaused")','GoatPortfolioGVName("DashboardExposurePolicyMode")'],'the five variables');
 assert.ok(!/GlobalVariablesFlush/.test(block.replace(/\/\/[^\n]*/g,'')),'no flush in the touch');
 const timer=bodyOf(main,'void GoatTimerBody(void)');
 assert.match(timer,/\n      DashboardBusProcessCommands\(\);\n      GoatDashPolicyHourlyTouch\(\);/,'on the one-second timer, in the bus\'s live block');
 assert.equal(main.split('GoatDashPolicyHourlyTouch();').length-1,1,'called once');
 ok();}

console.log(JSON.stringify({passed,test:'dash_policy_touch',hours:3}));
