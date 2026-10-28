// Mutation check for B49b PR-4 (F4, the no-tick timer; R2, Fix_Clock): every rule is load-bearing. Each mutant edits GOAT
// V1.49.mq5 or GOAT_Inputs_Definitions.mqh in memory; test_b49b_f4.cjs, run on the mutated sources (GOAT_EA_MAIN,
// GOAT_EA_HEADER), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f4.cjs');
const SOURCES={main:fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n'),
 header:fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'),'utf8').replace(/\r\n/g,'\n')};
const MUTANTS=[
 // The trigger.
 ['main','no tick-age gate','return now_ms-g_GoatLastTickMs>=GOAT_NO_TICK_MS && now_ms-g_GoatLastNoTickRunMs>=GOAT_NO_TICK_MS;','return now_ms-g_GoatLastNoTickRunMs>=GOAT_NO_TICK_MS;'],
 ['main','no 5 s throttle','return now_ms-g_GoatLastTickMs>=GOAT_NO_TICK_MS && now_ms-g_GoatLastNoTickRunMs>=GOAT_NO_TICK_MS;','return now_ms-g_GoatLastTickMs>=GOAT_NO_TICK_MS;'],
 ['main','runs in the tester','if(tester || monitor || g_GoatLastTickMs==0) return false;','if(monitor || g_GoatLastTickMs==0) return false;'],
 ['main','runs on a read-only monitor','if(tester || monitor || g_GoatLastTickMs==0) return false;','if(tester || g_GoatLastTickMs==0) return false;'],
 ['main','runs before the first tick','if(tester || monitor || g_GoatLastTickMs==0) return false;','if(tester || monitor) return false;'],
 ['main','runs in batch or dashboard mode','   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return false;\n',''],
 ['main','the threshold is not 5 s','#define GOAT_NO_TICK_MS 5000','#define GOAT_NO_TICK_MS 1000'],
 // The run.
 ['main','the flag is never set','   g_GoatNoTickRun=true;\n   GoatTickBody();','   GoatTickBody();'],
 ['main','the flag is left set','   GoatTickBody();\n   g_GoatNoTickRun=false;','   GoatTickBody();'],
 ['main','the run is not stamped','   g_GoatLastNoTickRunMs=now_ms;\n',''],
 ['main','the timer never runs it','   GoatNoTickTimer(); // B49b (F4): exits without a tick (live trading charts only)\n',''],
 // GoatTickBody.
 ['main','a timer run counts as a tick','if(!g_GoatNoTickRun) g_GoatLastTickMs=GetTickCount64();','g_GoatLastTickMs=GetTickCount64();'],
 ['main','the timer keeps the stale tick clock','   if(g_GoatNoTickRun) {tm_cur=TimeTradeServer(); TimeToStruct(tm_cur,stm_cur);}',''],
 ['main','the timer goes on to trailing, signals and entries','   if(g_GoatNoTickRun) return; // B49b (F4)','   // B49b (F4)'],
 // The log.
 ['main','a close attempt is not logged','     if(g_GoatNoTickRun) GoatNoTickCloseLog(m_position.Ticket(),OP);',''],
 ['main','every tick close is logged too','if(g_GoatNoTickRun) GoatNoTickCloseLog(','if(true) GoatNoTickCloseLog('],
 // The IsNew* helpers under the timer.
 ['header','the timer skips the per-second block','   if(g_GoatNoTickRun) return true; // B49b (F4)','   if(g_GoatNoTickRun) return false; // B49b (F4)'],
 ['header','the timer runs the minute block','bool IsNewMinute()\n  {\n   if(g_GoatNoTickRun) return false;','bool IsNewMinute()\n  {\n   if(g_GoatNoTickRun) return true;'],
 ['header','the timer runs the day block','bool IsNewDay()\n  {\n   if(g_GoatNoTickRun) return false;','bool IsNewDay()\n  {\n   if(g_GoatNoTickRun) return true;'],
 ['header','the timer consumes the tick\'s second','   if(g_GoatNoTickRun) return true; // B49b (F4)','   if(false) return true; // B49b (F4)'],
 // Fix_Clock.
 ['header','On is ignored','if(Fix_Clock==GoatFix_On) {static long lastSecondTime','if(false) {static long lastSecondTime'],
 ['header','On still compares the second field','long curSecondTime=(long)tm_cur;','long curSecondTime=(long)stm_cur.sec;'],
 ['header','On still compares the minute field','long curMinuteTime=(long)tm_cur/60;','long curMinuteTime=(long)stm_cur.min;'],
 ['header','On still compares the day of the month','long curDayTime=(long)tm_cur/86400;','long curDayTime=(long)stm_cur.day;'],
 ['header','Off takes the full-timestamp path','if(Fix_Clock==GoatFix_On) {static long lastMinuteTime','if(Fix_Clock!=GoatFix_On) {static long lastMinuteTime'],
];
function runOn(texts){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f4-'));
 try{
  const files={main:path.join(dir,'GOAT V1.49.mq5'),header:path.join(dir,'GOAT_Inputs_Definitions.mqh')};
  for(const k of Object.keys(files))fs.writeFileSync(files[k],'﻿'+texts[k].replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:files.main,GOAT_EA_HEADER:files.header},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
{const r=runOn(SOURCES);assert.equal(r.status,0,'the unmutated test passes on the scratch sources: '+r.stderr);}
let killed=0;
for(const [file,label,from,to] of MUTANTS){
 const n=SOURCES[file].split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${file} (found ${n})`);
 const r=runOn({...SOURCES,[file]:SOURCES[file].replace(from,()=>to)});
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
