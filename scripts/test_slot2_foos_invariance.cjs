// Slot 2 is never decided by FOOS (Claude-Mac 6025359910, blocking items 1 and 2). Runs the production
// GoatExportSlots (GOAT V1.49.mq5) in a JS VM with a stubbed Strategy Tester. Two re-tests of slot 2 that are
// IDENTICAL up to the FOOS start and differ only after it (a good FOOS, a crash in FOOS) must lead to the same
// slot-2 decision. The full-span re-test figures MT5 would report (profit, SR, ARF over BOOS + SAMPLE + FWD +
// FOOS) follow the FOOS, as they do in MT5. This check FAILS on the pre-fix head 045b38c (it judged slot 2 on
// those full-span figures and dropped a losing full span) and passes once slot 2 is judged on its own equity
// CSV over [BOOS end, FOOS start). GOAT_EA_ROOT may point at another source tree.
process.env.GOAT_OUTCOME_HARNESS_ONLY='1';
process.env.GOAT_OUTCOME_EXTRA_DEFINES='GOAT_BELOW_SCORE_EXPORT_V149';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const H=require('./test_research_outcome.cjs');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const mainRaw=fs.readFileSync(path.join(root,'GOAT V1.49.mq5'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const FLAGS=new Set([...mainRaw.matchAll(/^#define\s+(\w+)/gm)].map(m=>m[1]));
function preprocessWith(text,flags){
  const out=[],stack=[];let active=true;
  for(const line of text.split('\n')){
    const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
    if(m){
      if(m[1]==='ifdef'||m[1]==='ifndef'){const on=flags.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
      else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
      else active=stack.pop()[0];
      continue;
    }
    if(/^\s*#/.test(line))continue;
    if(active)out.push(line);
  }
  return out.join('\n');
}
const P=H.stripComments(preprocessWith(mainRaw,FLAGS));
// The call is built from the function's own parameter names, so the same test runs on the pre-fix tree (no
// deposit parameter) and on the fix (Claude-Mac 6026738987: the deposit opens the window as in window_metrics).
let params=[];
const slots=H.extract(P,/^int\s+GoatExportSlots\s*\(/m,'GoatExportSlots',H.macros).replace(/ExportRecord\s+(\w+)\[\];/g,'let $1=[];')
  .replace(/function GoatExportSlots\(([^)]*)\)/,(all,list)=>{params=list.split(',').map(p=>p.trim()).map(p=>p==='details'?'__d':p);return 'function GoatExportSlots('+params.join(',')+')';})
  .replace(/\bdetails\b/g,'__slotDetails').replace(/,days\);/,',days); days=n;');
assert.ok(slots.includes('days=n;'),'by-reference rewiring applied');
const DEPOSIT=100000;   // the re-tests' curves below start at the tester deposit
const ARGS={ranked:'__ranked',metaTail:'",tier=below_score"',keepLosingSlot1:'true',minSR:'2.5',minARF:'0.2',deposit:String(DEPOSIT),
  kept:'__kept',__d:'""',runs:'0',lost:'0',failed:'0',reportMode:'false'};
assert.ok(params.length>0&&params.every(p=>p in ARGS),'every GoatExportSlots parameter is known: '+params);
const CALL='GoatExportSlots('+params.map(p=>ARGS[p]).join(',')+')';

const D=s=>H.epoch(s),DAY=86400;
const START='2024.01.08',FOOS_START='2024.04.01';   // SAMPLE = [2024.01.08, 2024.04.01): 84 days
const days=120;                                       // the re-test runs on into FOOS until 2024.05.06
function csv(changes){
  const lines=['﻿<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>'];let bal=DEPOSIT;
  changes.forEach((x,k)=>{bal+=x;const day=H.date(D(START)+k*DAY);lines.push(day+' 10:00\t'+bal.toFixed(2)+'\t'+(bal-3).toFixed(2)+'\t0.0',day+' 15:00\t'+bal.toFixed(2)+'\t'+bal.toFixed(2)+'\t0.0');});
  return lines.join('\n');
}
const inFoos=k=>D(START)+k*DAY>=D(FOOS_START);
const slot1=Array.from({length:days},(_,k)=>Math.sin(k*0.7)*50+((k*37)%11)-5+30);
const slot2Sample=k=>Math.cos(k*1.9)*40+((k*53)%7)-3+30;   // independent of slot 1 and of quality over SAMPLE
const variants={
  // FOOS good: MT5's full-span figures look fine.
  'FOOS good':{changes:Array.from({length:days},(_,k)=>inFoos(k)?slot2Sample(k):slot2Sample(k)),full:{prf:2900,sr:3.4,arf:0.42}},
  // FOOS crash, full span still profitable: the full-span SR/ARF fall under the bar.
  'FOOS crash (full span SR 1.1)':{changes:Array.from({length:days},(_,k)=>inFoos(k)?-60:slot2Sample(k)),full:{prf:350,sr:1.1,arf:0.06}},
  // FOOS crash, full span loses money: the pre-fix code never stored it.
  'FOOS crash (full span loses)':{changes:Array.from({length:days},(_,k)=>inFoos(k)?-110:slot2Sample(k)),full:{prf:-1500,sr:-0.4,arf:-0.05}},
};
for(const v of Object.values(variants))
  assert.equal(csv(v.changes).split('\n').filter(l=>l.slice(0,10)<FOOS_START.replace(/\./g,'.')).join('\n'),
               csv(variants['FOOS good'].changes).split('\n').filter(l=>l.slice(0,10)<FOOS_START).join('\n'),'identical before the FOOS start');

function decide(name){
  const v=variants[name];
  const files={'exports\\5.csv':csv(slot1),'exports\\6.csv':csv(v.changes)};
  const ctx=Object.assign(H.makeContext({}),{Key:'GOAT',EA_Name:'GOAT V1.49',Server:'S',OP_Standard:9,strT:{Strat:'R1'},
    GOAT_BATCH_CANCELLED_GV:'c',GlobalVariableGet:()=>0,LogOrPrint:()=>{},DeleteExports:()=>true,GoatExportReadTextCommon:p=>files[p]??''});
  ctx.RunAndStoreSet=(rowInd,mode,reportMode,arr,init,attempts,keepLosing=false)=>{
    const unit=ctx.RowsUnique[rowInd],full=unit.pass===6?v.full:{prf:900,sr:3,arf:0.3};
    if(!(full.prf>0)&&!keepLosing)return 0;
    arr.push({csvFile:'exports\\'+unit.pass+'.csv',setFile:'exports\\'+unit.pass+'.set',prf:full.prf,sr:full.sr,arf:full.arf,dd:10,pf:1.2,trds:200,rowIndex:rowInd});
    return 1;
  };
  vm.runInContext(H.method('GoatDailyReturnCorrelation').replace(/function GoatDailyReturnCorrelation\(([^)]*)\)/,'function GoatDailyReturnCorrelation(csvA,csvB,from,to)'),ctx);
  vm.runInContext(slots,ctx);
  const row=(p,rf)=>({pass:p,back_result:0,back_profit:500,back_PF:1.5,back_RF:3,back_SR:1.2,back_DD_pc:5,back_trades:120,forward_result:0,
    forward_profit:100,forward_PF:1.3,forward_RF:rf,forward_SR:1,forward_DD_pc:4,forward_trades:40,Inputs:'0,2',Score:40,forward_seen:true});
  Object.assign(ctx,{Rows:[row(5,2),row(6,1.5)],RowsUnique:[],m_inputVarNames:['SL_Pips','Grid_Size'],startD:D(START),forwardD:D('2024.03.04'),
    endD:D(FOOS_START)-DAY,__ranked:[0,1],__kept:[]});
  const count=vm.runInContext(CALL,ctx);
  const d=ctx.__slotDetails,pick=k=>(d.match(new RegExp(';'+k+'=([^;]*)'))||[])[1];
  return {kept:count,slot2:pick('slot2'),reason:pick('slot2_reason')};
}
const results=Object.fromEntries(Object.keys(variants).map(name=>[name,decide(name)]));
console.log(JSON.stringify(results));
const base=results['FOOS good'];
assert.equal(base.slot2,'kept','the slot-2 pass is good and different over SAMPLE: '+JSON.stringify(base));
for(const [name,result] of Object.entries(results))
  assert.deepEqual(result,base,'slot 2 decided by FOOS: "'+name+'" '+JSON.stringify(result)+' vs "FOOS good" '+JSON.stringify(base));
console.log(JSON.stringify({passed:Object.keys(results).length,slot2FoosInvariant:true,nativeExecution:false}));
