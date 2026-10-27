// B44 item 6 (goatai#2350): the sequence capture no longer stops at 2,000,000 rows. Past 1,000,000 rows the minute
// marks go to every 5 minutes (marks_downsampled, marks_interval_changed_at); deals and every event frame are still
// written in full; the 512 MiB byte bound stays. This runs the production GoatTraceWritten and GoatTraceTimer after a
// syntax-only MQL-to-JS conversion against a modelled clock and writer, and pins the completion and manifest fields.
// The controller side reads them in controller/test_studio_trace_marks_downsampled.py.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const src=fs.readFileSync(path.join(ROOT,'GOAT_SequenceExport.mqh'),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
let passed=0;const ok=()=>passed++;
function unit(signature){
 const a=src.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 let i=src.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<src.length;j++){if(src[j]==='{')depth++;if(src[j]==='}')depth--;}
 return src.slice(i+1,j-1);
}
const defines=Object.fromEntries([...src.matchAll(/^#define (GOAT_TRACE_MARKS_\w+)\s+(\d+)$/gm)].map(m=>[m[1],Number(m[2])]));
assert.deepEqual(defines,{GOAT_TRACE_MARKS_DOWNSAMPLE_ROWS:1000000,GOAT_TRACE_MARKS_COARSE_SECONDS:300});
const js=t=>t.replace(/\/\/.*$/gm,'').replace(/\blong now=/g,'let now=').replace(/\(long\)/g,'');
function model(){
 const frames=[],prints=[];
 const c={...defines,g_trace_enabled:true,g_trace_rows:0,g_trace_bytes:0,g_trace_last_frame:-1,g_trace_dirty:false,
  g_trace_marks_seconds:60,g_trace_marks_changed_at:0,g_trace_failed:false,g_trace_error:'',clock:0,
  TimeTradeServer:()=>c.clock,GoatTraceClock:()=>c.clock*1000,Print:(...a)=>prints.push(a.join('')),
  GoatTraceFail:r=>{c.g_trace_failed=true;c.g_trace_error=c.g_trace_error||r;},
  GoatTraceFlush:()=>{},GoatTraceBoundary:()=>{frames.push(['event',c.clock]);c.g_trace_dirty=false;c.GoatTraceWritten(40);c.GoatTraceWritten(40);},
  GoatTraceMarks:reason=>{frames.push([reason,c.clock]);c.GoatTraceWritten(60);c.GoatTraceWritten(60);}};
 vm.createContext(c);
 vm.runInContext('function GoatTraceWritten(bytes){'+js(unit('void GoatTraceWritten(const uint bytes)'))+'}',c);
 vm.runInContext('function GoatTraceTimer(){'+js(unit('void GoatTraceTimer()'))+'}',c);
 return {c,frames,prints};
}
// 1) Below the threshold: a mark every minute, as before.
{const m=model();for(let t=0;t<600;t++){m.c.clock=1760000000+t*10;m.c.GoatTraceTimer();}
 const minutes=m.frames.filter(f=>f[0]==='minute');assert.equal(minutes.length,100);assert.ok(minutes.every(f=>f[1]%60===0));
 assert.equal(m.c.g_trace_marks_changed_at,0);ok();}
// 2) Past 1,000,000 rows: every 5 minutes from the next frame on, recorded once; deals (event frames) every minute.
{const m=model();m.c.g_trace_rows=999998;
 for(let t=0;t<180;t++){m.c.clock=1760000040+t*60;if(t%2)m.c.g_trace_dirty=true;m.c.GoatTraceTimer();}
 const minutes=m.frames.filter(f=>f[0]==='minute').map(f=>f[1]),events=m.frames.filter(f=>f[0]==='event');
 const change=m.c.g_trace_marks_changed_at/1000;
 assert.ok(change>0,'recorded');assert.equal(m.prints.filter(p=>p.includes('marks_downsampled')).length,1,'announced once');
 assert.ok(minutes.filter(t=>t<change).every(t=>t%60===0)&&minutes.filter(t=>t>=change).every(t=>t%300===0),'coarser after the change');
 assert.ok(minutes.filter(t=>t>=change).length>=30);
 assert.equal(events.length,90,'every deal boundary still written');assert.equal(m.c.g_trace_failed,false);ok();}
// 3) No row stop: 2,000,001 rows is not a failure and the capture stays enabled; the byte bound still stops it.
{const m=model();m.c.g_trace_rows=2000000;m.c.GoatTraceWritten(10);
 assert.deepEqual([m.c.g_trace_failed,m.c.g_trace_enabled,m.c.g_trace_rows],[false,true,2000001]);
 m.c.g_trace_bytes=536870912;m.c.GoatTraceWritten(10);
 assert.deepEqual([m.c.g_trace_failed,m.c.g_trace_enabled],[true,false]);assert.match(m.c.g_trace_error,/512 MiB/);ok();}
// 4) Recorded in completion.csv and in the manifest's sampling block; the capture status itself is unchanged.
{assert.ok(!/2000000 row/.test(src),'the row stop is gone');
 assert.match(src,/GOAT_SEQ_FOOTER\("marks_status",\(g_trace_marks_changed_at>0 \? "marks_downsampled" : "full"\)\)\n   GOAT_SEQ_FOOTER\("marks_interval_changed_at",g_trace_marks_changed_at\)/);
 assert.match(src,/GOAT_SEQ_FOOTER\("capture_status",\(!g_trace_failed && g_trace_tester_finished && ok\)\?"complete-awaiting-external-reconciliation":"incomplete"\)/);
 assert.match(src,/\\"status\\":\\"marks_downsampled\\",\\"marksIntervalChangedAt\\":"\+\(string\)g_trace_marks_changed_at/);
 assert.match(src,/GoatSeqJson\(g_trace_failed\?"incomplete":"complete-awaiting-import-verification"\)/,'manifest status unchanged');ok();}
console.log(JSON.stringify({passed,nativeTester:false}));
