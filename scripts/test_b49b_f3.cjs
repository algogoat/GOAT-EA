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
const js=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'').replace(new RegExp('\\b'+TYPE+'\\s+(?=\\w)','g'),'let ');
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
 assert.match(CLOSE,/\{closeErrors\+\+; if\(!MQLInfoInteger\(MQL_TESTER\)\) PrintFormat\("Close failed: ticket=%I64u ret=%u \(%s\)",m_position\.Ticket\(\),m_trade\.ResultRetcode\(\),m_trade\.ResultRetcodeDescription\(\)\);\}/);
 const UPD=bodyOf(main,'   void UpdateLockTPSL(int count=0)');
 assert.match(UPD,/\{TPmodifyErrors\+\+; if\(!MQLInfoInteger\(MQL_TESTER\)\) PrintFormat\("TP\/SL modify failed:/);
 assert.ok(!/TPmodifyErrors\+\+; TPSLmodifieds\+\+/.test(UPD),'B49a\'s silent form is gone');
 const TSL=bodyOf(main,'   void TrailingStoploss()');
 assert.ok(TSL.includes('PrintFormat("TSL BUY modify failed: ticket=%I64u newSL=%.6f ret=%d (%s)",TradeLevels[i].ticket,SL,'),'the %.6f gets the double');
 ok();}

console.log(JSON.stringify({passed,test:'b49b_f3'}));
