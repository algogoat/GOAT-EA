// The hourly policy touch (GOAT-EA#328 follow-up). MT5 deletes a GlobalVariable nothing accesses for 4 weeks. The
// every-second acknowledgement that dash-ack-once removed also re-set this chart's policy variables; without it a Buy
// Only or paused rule could age out of the terminal's store and come back as "allow both, not paused" at a restart.
// Once per UTC hour the one-second timer READS the five policy variables OnInit restores from. A read is an access
// (MQL5 Reference, "Global Variables of the Terminal"); a write-back would race the dashboard on the portfolio variables
// (Claude-Mac, GOAT-EA#330). The production code runs here from GOAT V1.49.mq5 (the dash-policy-touch block), as
// test_dash_ack_once.cjs runs the bus, against a modelled global-variable store whose every write path throws:
// 1. over ticks spanning 3 hours each of the five variables is read once an hour; nothing is written or flushed;
// 2. a missing variable is never read into existence or created;
// 3. batch, dashboard, optimization and forward charts, and a chart with no magic, do nothing;
// 4. the race: a dashboard pause (and a resume) landing between one chart's read and the next survives every touch, on
//    any number of charts;
// 5. the block names no write call at all (Set, SetOnCondition, Temp, Del, DeleteAll, Flush), and its comment quotes
//    the MQL5 reference that a read is an access;
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
const code=block.replace(/\/\/[^\n]*/g,'');
const blockGlobals=code.split('\n').filter(l=>/^(?:datetime|uint|bool|int)\s+g_goat_dash_policy_\w+=[^()]*;/.test(l)).join('\n');
assert.equal(blockGlobals.split('\n').length,1,'the touch keeps one state variable: the hour it last ran');

const CHILD=f=>'77|EURUSD|'+f,PORT=n=>'P|'+n;
const PAUSED=CHILD(DEF.GOAT_GV_FIELD_POLICY_PAUSED),MASK=CHILD(DEF.GOAT_GV_FIELD_POLICY_TRADE_MASK),EXPO=CHILD(DEF.GOAT_GV_FIELD_POLICY_EXPOSURE_MODE);
const P_PAUSED=PORT('DashboardPolicyPaused'),P_EXPO=PORT('DashboardExposurePolicyMode');
const FIVE=[PAUSED,MASK,EXPO,P_PAUSED,P_EXPO];
// A paused, Buy Only chart under a non-default exposure rule, plus two variables that are not the touch's.
const policy=()=>new Map([[PAUSED,1],[MASK,1],[EXPO,2],[P_PAUSED,1],[P_EXPO,2],[CHILD('CID'),123456],[PORT('Portfolio_StartTime'),1700000000]]);
const HOUR=3600,H0=Math.floor(1731400000/HOUR)*HOUR;   // a UTC hour boundary

// One EA instance on a chart: `now` is TimeGMT (s). Every write path of the terminal's store is modelled as MT5 does it
// (a Set writes, a Del deletes) and recorded: the touch must never reach one. `afterRead(key)` runs right after a read
// (another chart or the dashboard acting in between).
const WRITES=['GlobalVariableSet','GlobalVariableSetOnCondition','GlobalVariableTemp','GlobalVariableDel','GlobalVariablesDeleteAll','GlobalVariablesFlush'];
const EFFECT={GlobalVariableSet:(s,k,v)=>{s.set(k,v);return 1;},GlobalVariableSetOnCondition:(s,k,v)=>{s.set(k,v);return true;},GlobalVariableTemp:(s,k)=>{if(!s.has(k))s.set(k,0);return true;},
 GlobalVariableDel:(s,k)=>s.delete(k),GlobalVariablesDeleteAll:s=>{const n=s.size;s.clear();return n;},GlobalVariablesFlush:()=>{}};
function instance(store,{now=H0,mode=0,optimization=false,forward=false,magic=77,chart='EURUSD'}={}){
 const c={...DEF,MAGIC1:magic,Operation_Batch:1,Operation_Dash:2,Mode_Operation:mode,MQL_OPTIMIZATION:1,MQL_FORWARD:2,
  now,reads:[],checks:0,writes:[],store,afterRead:()=>{},
  Symbol:()=>chart,GoatPortfolioGVName:PORT,GoatChildGVName:(m,s,f)=>m+'|'+s+'|'+f,IntegerToString:String,GetLastError:()=>4501,Print:()=>{}};
 c.MQLInfoInteger=flag=>(flag===1&&optimization)||(flag===2&&forward)?1:0;
 c.TimeGMT=()=>c.now;c.GetTickCount=()=>((c.now-H0)*1000+5000)>>>0;
 c.GlobalVariableCheck=k=>{c.checks++;return store.has(k);};
 c.gvRead=k=>{const r=store.has(k)?[true,store.get(k)]:[false,0];c.reads.push([k,c.now]);c.afterRead(k);return r;};
 for(const w of WRITES) c[w]=(...a)=>{c.writes.push([w,...a]);return EFFECT[w](store,...a);};
 vm.createContext(c);
 vm.runInContext(js(blockGlobals)+'\n'
  +fn('GoatDashPolicyTouchOne',['dpt_name'],bodyOf(main,'void GoatDashPolicyTouchOne(const string dpt_name)'))
  +fn('GoatDashPolicyHourlyTouch',[],bodyOf(main,'void GoatDashPolicyHourlyTouch(void)')),c);
 c.ticks=n=>{for(let i=0;i<n;i++){c.GoatDashPolicyHourlyTouch();c.now++;}};   // the 1 s timer (GoatTimerBody)
 c.readsOf=k=>c.reads.filter(r=>r[0]===k);
 return c;
}

{// 1. Three hours of timer ticks, from an hour boundary: each of the five is read at the top of each hour (3 times);
 // nothing is written, flushed, created or changed.
 const store=policy(),before=new Map(store),c=instance(store);c.ticks(3*HOUR);
 for(const k of FIVE)
  assert.deepEqual(c.readsOf(k).map(r=>r[1]),[H0,H0+HOUR,H0+2*HOUR],k+': read at '+c.readsOf(k).map(r=>r[1]-H0).join(', ')+' s, want once an hour');
 assert.deepEqual([c.reads.length,c.writes],[15,[]],'3 hours: '+c.reads.length+' read(s) and '+c.writes.length+' write(s), want 15 reads and no write');
 assert.deepEqual([...store],[...before],'no value changed, nothing created');
 // From the middle of an hour: at the first tick, then at each hour boundary.
 const s2=policy(),m=instance(s2,{now:H0+1234});m.ticks(3*HOUR);
 assert.deepEqual(m.readsOf(MASK).map(r=>r[1]),[H0+1234,H0+HOUR,H0+2*HOUR,H0+3*HOUR],'from mid-hour: the first tick, then each hour');
 ok();}

{// 2. A missing variable is never read into existence or created: only what exists is read.
 const store=new Map([[MASK,1]]),c=instance(store);c.ticks(3*HOUR);
 assert.deepEqual([c.reads.map(r=>r[0]),[...store],c.writes],[[MASK,MASK,MASK],[[MASK,1]],[]],'only the trade mask exists: want 3 reads of it, nothing else read, nothing created');
 const empty=new Map(),e=instance(empty);e.ticks(3*HOUR);
 assert.deepEqual([e.reads,empty.size,e.writes,e.checks],[[],0,[],15],'an empty store: every name is checked, none is read, nothing is created');
 for(const k of FIVE){const one=new Map([[k,2]]),o=instance(one);o.ticks(HOUR+1);
  assert.deepEqual([o.reads.map(r=>r[0]),[...one]],[[k,k],[[k,2]]],k+' alone is read, at each hour');}
 ok();}

{// 3. Batch and dashboard charts, optimization and forward passes, and a chart without a magic: nothing.
 for(const [label,options] of [['batch',{mode:1}],['dashboard',{mode:2}],['optimization',{optimization:true}],['forward',{forward:true}],['no magic',{magic:0}]]){
  const store=policy(),before=[...store],c=instance(store,options);c.ticks(3*HOUR);
  assert.deepEqual([c.reads.length,c.checks,c.writes,[...store]],[0,0,[],before],label+': '+c.reads.length+' read(s), want nothing');
 }
 ok();}

{// 4. The race of GOAT-EA#330: the dashboard pauses the portfolio (and later resumes it) while 36 charts run their
 // hourly touch. The command lands right after one chart has read the variable and before its next read. With a
 // write-back the chart would put the stale value back; the touch must leave every dashboard value as set.
 const store=policy();store.set(P_PAUSED,0);
 const charts=Array.from({length:36},(_,i)=>instance(store,{chart:'SYM'+i}));
 let fired=0;
 charts[17].afterRead=k=>{if(k===P_PAUSED&&!fired){fired=1;store.set(P_PAUSED,1);}};   // pause, mid-touch of chart 17
 for(const c of charts) c.ticks(1);
 assert.deepEqual([store.get(P_PAUSED),fired],[1,1],'a pause set between a chart\'s read and its next step stays set (read '+store.get(P_PAUSED)+')');
 charts[5].afterRead=k=>{if(k===P_PAUSED&&fired===1){fired=2;store.set(P_PAUSED,0);}};    // resume, mid-touch of chart 5, next hour
 for(const c of charts){c.now=H0+HOUR;c.ticks(1);}
 assert.deepEqual([store.get(P_PAUSED),fired],[0,2],'a resume set mid-touch stays set');
 assert.deepEqual(charts.flatMap(c=>c.writes),[],'no chart wrote anything');
 ok();}

{// 5. Statically: the block's code names no write call; its comment quotes the MQL5 reference.
 for(const w of WRITES) assert.ok(!new RegExp('\\b'+w+'\\b').test(code),'the touch names '+w);
 assert.match(code,/\bGlobalVariableGet\(dpt_name,dpt_value\)/,'the touch reads with GlobalVariableGet');
 const comment=block.split('\n').filter(l=>/^\s*\/\//.test(l)).map(l=>l.replace(/^\s*\/\/\s?/,'')).join(' ').replace(/\s+/g,' ');
 assert.ok(comment.includes('https://www.mql5.com/en/docs/globals'),'the comment cites the MQL5 reference page');
 assert.ok(comment.includes('"Global variables are kept in the client terminal for 4 weeks since the last access, then they will be deleted automatically. An access to a global variable is not only setting of a new value, but reading of the global variable value, as well."'),
  'the comment quotes the reference that a read is an access');
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
 const touched=[...touch.matchAll(/GoatDashPolicyTouchOne\((.*?)\)\);/g)].map(m=>m[1]+')');
 assert.deepEqual(touched,['GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_PAUSED)','GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_TRADE_MASK)',
  'GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_POLICY_EXPOSURE_MODE)','GoatPortfolioGVName("DashboardPolicyPaused")','GoatPortfolioGVName("DashboardExposurePolicyMode")'],'the five variables');
 const timer=bodyOf(main,'void GoatTimerBody(void)');
 assert.match(timer,/\n      DashboardBusProcessCommands\(\);\n      GoatDashPolicyHourlyTouch\(\);/,'on the one-second timer, in the bus\'s live block');
 assert.equal(main.split('GoatDashPolicyHourlyTouch();').length-1,1,'called once');
 ok();}

console.log(JSON.stringify({passed,test:'dash_policy_touch',hours:3,charts:36}));
