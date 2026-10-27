// B49b PR-3 (F3, Fix_ClosePath; roadmap D2, D3/R14, D4, D5; goatai#2587 6433828681, Claude-Mac 6433854745). The
// production code runs here from GOAT V1.49.mq5:
// 1. SEQUENCE::EndDeferredUntilFlat and ClosePendingPump: Off never defers (B49a ends at once, even with positions
//    open). On: an end requested while this real sequence's positions are open is kept; the close is retried once per
//    server second; the sequence ends with the original reason once flat. Virtual, idle and flat sequences end at once.
// 2. Where it sits: End_Sequence's first statement defers; End_Sequence clears the pending reason; Add_Level freezes
//    adds while an end waits; OnTick pumps both sides before MLPS.
// 3. The live-only failure logs (D4: a failed close; D5: a failed TP/SL modify) never print in the tester.
// UpdateLockTPSL's monotonic SL (D2) runs on the restart_adopt harness (test_restart_adopt.cjs section 16).
// test_b49b_f3_mutations.cjs runs this file on mutated entrypoints (GOAT_EA_MAIN).
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
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
const TYPE='(?:const\\s+)?(?:string|int|uint|long|ulong|bool|double|datetime)';
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ')
 .replace(/\((?:long|int|uint|ulong|double|datetime)\)/g,'');
const fn=(name,args,body)=>'function '+name+'('+args.join(',')+'){'+js(body)+'}\n';

// A sequence with its own positions on the account; CloseAllPositions closes them unless the broker refuses.
function sequence({fix=1,virtual=false,active=true,traded=true,positions=2,refuse=0}={}){
 const c={OP_BUY:0,OP_SELL:1,MAGIC1:77,GoatFix_On:1,GoatFix_Off:0,Fix_ClosePath:fix,dir:0,Virtual:virtual,Active:active,Traded:traded,
  Desc:'Trend Buy',ClosePendingReason:'',ClosePendingTried:0,now:1000,open:positions,refuse,logs:[],ends:[],closes:0};
 c.FindNumberOfPositions=(op,magic)=>{assert.equal(op,0);assert.equal(magic,77);return c.open;};
 c.CloseAllPositions=(op,magic)=>{c.closes++;if(c.refuse>0)c.refuse--;else c.open=0;};
 c.TimeCurrent=()=>c.now;c.Print=(...a)=>c.logs.push(a.join(''));
 vm.createContext(c);
 // End_Sequence as written begins with the deferral; the rest of its body (the bookkeeping) is modelled as "ended".
 vm.runInContext(fn('EndDeferredUntilFlat',['desc'],bodyOf(main,'   bool EndDeferredUntilFlat(const string desc)'))
  +fn('ClosePendingPump',[],bodyOf(main,'   void ClosePendingPump()'))
  +'function End_Sequence(desc){if(EndDeferredUntilFlat(desc))return;if(Active){ends.push(desc);Active=Traded=false;ClosePendingReason="";ClosePendingTried=0;}}',c);
 return c;
}
// 1. The deferral and the pump.
{// Off: B49a ends at once, positions or not.
 const off=sequence({fix:0});off.End_Sequence('Bias StopOut');assert.deepEqual([off.ends,off.ClosePendingReason],[['Bias StopOut'],'']);
 // On, flat: ends at once.
 const flat=sequence({positions:0});flat.End_Sequence('Bias Profit Exit');assert.deepEqual(flat.ends,['Bias Profit Exit']);
 // Virtual, idle or never traded: never deferred.
 for(const over of [{virtual:true},{active:false},{traded:false}]){const s=sequence(over);s.End_Sequence('x');assert.equal(s.ClosePendingReason,'',JSON.stringify(over));}
 // On, positions open: deferred, logged once, the latest reason kept.
 const s=sequence({refuse:2});
 s.End_Sequence('Bias StopOut');assert.deepEqual([s.ends,s.ClosePendingReason,s.Active],[[],'Bias StopOut',true]);
 s.End_Sequence('Bias Rescue Exit: MLPS breached');assert.equal(s.ClosePendingReason,'Bias Rescue Exit: MLPS breached');
 assert.deepEqual(s.logs,['Trend Buy: Bias StopOut requested while positions remain open: the close is retried and the sequence ends when flat (Fix_ClosePath)']);
 // The pump: one close attempt per server second; refused twice, then flat, then the original end.
 s.ClosePendingPump();assert.equal(s.closes,1);s.ClosePendingPump();assert.equal(s.closes,1,'not twice in the same second');
 s.now++;s.ClosePendingPump();assert.deepEqual([s.closes,s.ends],[2,[]],'still refused: still waiting');
 s.now++;s.ClosePendingPump();assert.deepEqual([s.closes,s.ends,s.ClosePendingReason],[3,['Bias Rescue Exit: MLPS breached'],''],'flat: ended with the reason');
 s.now++;s.ClosePendingPump();assert.equal(s.closes,3,'nothing pending: nothing done');
 // Positions closed by someone else (a broker stop): the next pump ends it without a close.
 const ext=sequence({refuse:9});ext.End_Sequence('Bias StopOut');ext.open=0;ext.ClosePendingPump();assert.deepEqual([ext.closes,ext.ends],[0,['Bias StopOut']]);
 // A sequence that stopped being active some other way: the pending reason is dropped.
 const gone=sequence({refuse:9});gone.End_Sequence('x');gone.Active=false;gone.ClosePendingPump();assert.deepEqual([gone.ClosePendingReason,gone.closes],['',0]);
 ok();}

// 2. Where it sits.
{const END=bodyOf(main,'   void End_Sequence(string desc)');
 const first=END.split('\n').filter(l=>l.trim()&&!/^\s*\/\//.test(l))[0].trim();
 assert.equal(first,'if(EndDeferredUntilFlat(desc)) return; // B49b (F3): Fix_ClosePath, a sequence ends only when its positions are flat');
 assert.ok(END.includes('     Active=Traded=Trailing=Retrace_Triggered=false;\n     ClosePendingReason=""; ClosePendingTried=0; // B49b (F3)'),'an end clears it');
 const ADD=bodyOf(main,'   bool Add_Level(double Level_New)');
 const FREEZE='    if(!Virtual && ClosePendingReason!="") return false; // B49b (F3): no add while an end waits for its close';
 assert.ok(ADD.includes(FREEZE),'adds frozen');assert.ok(ADD.indexOf(FREEZE)<ADD.indexOf('OpenPosition('),'before any order');
 const TICK='   Seq_Buy.ClosePendingPump(); Seq_Sell.ClosePendingPump(); // B49b (F3): an end deferred until flat retries its close\n   bool buyMlpsExit=false,sellMlpsExit=false;';
 assert.equal(main.split(TICK).length-1,1,'OnTick pumps both sides, right before MLPS');
 assert.ok(bodyOf(main,'   SEQUENCE()').includes('    ClosePendingReason=""; ClosePendingTried=0; // B49b (F3)'),'constructed empty');
 ok();}

// 3. The failure logs are live-only (the tester never prints them; trades are unaffected either way).
{const CLOSE=bodyOf(main,'void CloseAllPositions(int OP,int magic=0)');
 assert.ok(CLOSE.includes('{closeErrors++; GoatCloseFailureLog(m_position.Ticket(),m_trade.ResultRetcode(),m_trade.ResultRetcodeDescription());}'),'a failed close goes to the throttled log');
 const UPD=bodyOf(main,'   void UpdateLockTPSL(int count=0)');
 assert.match(UPD,/\{TPmodifyErrors\+\+; if\(!MQLInfoInteger\(MQL_TESTER\)\) PrintFormat\("TP\/SL modify failed:/);
 assert.ok(!/TPmodifyErrors\+\+; TPSLmodifieds\+\+/.test(UPD),'B49a\'s silent form is gone');
 const TSL=bodyOf(main,'   void TrailingStoploss()');
 assert.ok(TSL.includes('PrintFormat("TSL BUY modify failed: ticket=%I64u newSL=%.6f ret=%d (%s)",TradeLevels[i].ticket,SL,'),'the %.6f gets the double');
 ok();}

// 4. The close-failure log is bounded (Claude-Mac GOAT-EA#276 P2): ClosePendingPump retries every second, so under a
//    closed market or disabled trading a per-failure line would flood. One Alert per run, then at most one line per
//    ticket per minute with the attempts since its last line; never in the tester.
function closeLog({tester=false}={}){
 const c={MQL_TESTER:1,tester,now:5000,lines:[],alerts:[],g_goat_close_fail_ticket:new Array(16).fill(0),g_goat_close_fail_time:new Array(16).fill(0),
  g_goat_close_fail_count:new Array(16).fill(0),g_goat_close_fail_alerted:false,IntegerToString:v=>String(v),
  g_goat_close_fail_overflow_time:0,g_goat_close_fail_overflow_count:0};
 c.MQLInfoInteger=k=>(k===1&&c.tester)?1:0;c.TimeCurrent=()=>c.now;c.Alert=s=>c.alerts.push(s);
 c.PrintFormat=(f,...a)=>{let i=0;c.lines.push(f.replace(/%(I64u|u|d|s)/g,()=>String(a[i++])));};
 vm.createContext(c);
 vm.runInContext(fn('GoatCloseFailureLog',['ticket','ret','desc'],bodyOf(main,'void GoatCloseFailureLog(const ulong ticket,const uint ret,const string desc)')),c);
 return c;
}
{const c=closeLog();
 c.GoatCloseFailureLog(1001,10018,'Market closed');
 assert.deepEqual(c.alerts,['GOAT: a close failed (ticket 1001, 10018 Market closed); the EA retries every second and logs each failing ticket once a minute']);
 assert.deepEqual(c.lines,['Close failed: ticket=1001 ret=10018 (Market closed), 1 attempt(s) since the last line']);
 for(let i=0;i<59;i++){c.now++;c.GoatCloseFailureLog(1001,10018,'Market closed');}
 assert.equal(c.lines.length,1,'quiet for the rest of the minute');
 c.now++;c.GoatCloseFailureLog(1001,10018,'Market closed');
 assert.equal(c.lines.length,2);assert.match(c.lines[1],/, 60 attempt\(s\) since the last line$/,'the attempts in between are counted');
 // Another ticket is logged on its own clock; the Alert is once per run.
 c.GoatCloseFailureLog(1002,10018,'Market closed');assert.equal(c.lines.length,3);assert.equal(c.alerts.length,1);
 // More failing tickets than slots: nothing breaks.
 for(let t=2000;t<2030;t++){c.now++;c.GoatCloseFailureLog(t,10018,'x');}
 assert.equal(c.alerts.length,1);
 // Codex GOAT-EA#276 P2: 20 tickets failing every second for 120 s. Evicting a slot used to reset its clock, so every
 // retry logged (1,815 lines). Now each tracked ticket logs at most once a minute and the rest share one overflow line a
 // minute: at most (16+1) lines per started minute, here 3 minutes.
 {const d=closeLog();
  for(let s=0;s<120;s++){d.now++;for(let t=3000;t<3020;t++)d.GoatCloseFailureLog(t,10018,'Trade disabled');}
  assert.ok(d.lines.length<=(16+1)*3,'bounded: '+d.lines.length+' lines');
  const overflow=d.lines.filter(l=>/beyond the 16 logged each minute/.test(l));
  assert.ok(overflow.length>=1&&overflow.length<=3,'one overflow line a minute: '+overflow.length);
  for(let t=3000;t<3020;t++){const own=d.lines.filter(l=>l.startsWith('Close failed: ticket='+t+' '));assert.ok(own.length<=3,'ticket '+t+': at most once a minute ('+own.length+')');}
  assert.match(overflow[0],/^Close failed: \d+ attempt\(s\) on positions beyond the 16 logged each minute, latest ticket=30\d\d ret=10018 \(Trade disabled\)$/);
  // Once a tracked ticket's minute has passed, its slot is reused (the ticket closed or still failing), never earlier.
  const e=closeLog();for(let t=1;t<=16;t++)e.GoatCloseFailureLog(t,1,'x');e.now+=30;e.GoatCloseFailureLog(99,1,'x');
  assert.equal(e.lines.filter(l=>/^Close failed: ticket=99 /.test(l)).length,0,'no slot free inside the minute: ticket 99 goes to the overflow line');
  e.now+=30;e.GoatCloseFailureLog(99,1,'x');assert.equal(e.lines.filter(l=>/^Close failed: ticket=99 /.test(l)).length,1,'after the minute it takes a slot');}
 // The tester never logs.
 const quiet=closeLog({tester:true});quiet.GoatCloseFailureLog(1,2,'x');assert.deepEqual([quiet.alerts,quiet.lines],[[],[]]);
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f3'}));
