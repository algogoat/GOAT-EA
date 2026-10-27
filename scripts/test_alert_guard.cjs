// B44 condition 4 (goatai#2350 6127809765): the no-modal-Alert guard holds for the whole compile closure. Walking
// GOAT V1.49.mq5 in include order (each quoted include expanded where it is included, once, as MQL5 does), every
// Alert( token must come after `#define Alert(...)` and before `#undef Alert`, so an include pulled in before the
// define can never keep a raw modal Alert. The only Alert after the #undef is GoatDeployNotice's own fallback.
// The check is shown failing on mutated fixtures (an Alert-bearing include moved above the define, a raw Alert in the
// input header, a standard include above the define, an Alert after the #undef).
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const ENTRY='GOAT V1.49.mq5';
let passed=0;const ok=()=>passed++;

// Comments become spaces (newlines kept) and string literals empty, so only real code tokens remain.
function code(text){
 // Line by line (MQL5 strings and char literals never span lines); block comments carry across lines.
 let block=false;
 return text.split(/\r?\n/).map(line=>{
  let out='',i=0;
  while(i<line.length){
   if(block){const j=line.indexOf('*/',i);if(j<0){i=line.length;break;}block=false;i=j+2;continue;}
   const c=line[i];
   if(c==='"'){let j=i+1;while(j<line.length&&line[j]!=='"'){if(line[j]==='\\')j++;j++;}out+='""';i=j+1;continue;}
   if(c==="'"){let j=i+1;while(j<line.length&&line[j]!=="'"){if(line[j]==='\\')j++;j++;}out+="' '";i=j+1;continue;}
   if(line.startsWith('//',i))break;
   if(line.startsWith('/*',i)){block=true;i+=2;continue;}
   out+=c;i++;
  }
  return out;
 }).join('\n');
}// Returns {violations, alerts, includes}: every Alert( outside the define..undef span (except GoatDeployNotice's
// fallback after the #undef) and every standard <include> before the define.
function check(read){
 const seen=new Set(),violations=[];let defined=false,undefinedAfter=false,alerts=0;
 (function walk(file){
  if(seen.has(file))return;seen.add(file);
  const text=read(file),rawLines=text.split(/\r?\n/),lines=code(text).split(/\r?\n/);
  lines.forEach((line,n)=>{
   const where=file+':'+(n+1);
   if(/^\s*#define\s+Alert\s*\(/.test(line)){defined=true;return;}
   if(/^\s*#undef\s+Alert\b/.test(line)){defined=false;undefinedAfter=true;return;}
   // Include paths come from the raw line (code() blanks string literals).
   const inc=/^\s*#include\s+""/.test(line)&&(rawLines[n]||'').match(/^\s*#include\s+"([^"]*)"/);
   if(inc){walk(inc[1]);return;}
   if(/^\s*#include\s+</.test(line)&&!defined){violations.push(where+': standard include outside the Alert redirection');return;}
   for(const _ of line.matchAll(/(?<![\w.])Alert\s*\(/g)){
    alerts++;
    if(defined)continue;
    if(undefinedAfter&&file===ENTRY&&/\{Alert\(goat_notice_text\); return;\}/.test(rawLines[n]))continue;   // GoatDeployNotice's own fallback
    violations.push(where+': Alert( outside the redirection');
   }
  });
 })(ENTRY);
 return {violations,alerts,includes:seen.size};
}const disk=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^﻿/,'');
// 1) The real closure: every Alert( is inside the redirection.
{const r=check(disk);
 assert.deepEqual(r.violations,[],'no raw Alert in the compile closure');
 assert.ok(r.alerts>60,'Alert( calls seen: '+r.alerts);assert.ok(r.includes>=40,'files walked: '+r.includes);ok();
 console.log('  closure: '+r.includes+' files, '+r.alerts+' Alert( tokens, all after the define');}
// 2) Mutated fixtures: each must fail.
const main=disk(ENTRY);
const DEFINE='#define Alert(goat_alert_text) GoatDeployNotice(goat_alert_text)';
assert.equal(main.split(DEFINE).length,2);
for(const [label,mutate,file] of [
 ['an Alert-bearing include moved above the define',m=>m.replace(DEFINE,'#include "Dashboard.mqh"\n'+DEFINE),'Dashboard.mqh'],
 ['a raw Alert in the input header (included before the define)',null,'GOAT_Inputs_Definitions.mqh'],
 ['a standard include above the define',m=>m.replace(DEFINE,'#include <Trade\\Trade.mqh>\n'+DEFINE),ENTRY],
 ['an Alert after the #undef',m=>m+'\nvoid Late(){Alert("late");}\n',ENTRY]]){
 const read=f=>{
  if(f===ENTRY&&mutate)return mutate(main);
  if(!mutate&&f==='GOAT_Inputs_Definitions.mqh')return disk(f)+'\nvoid GoatRawAlert(){Alert("raw");}\n';
  return disk(f);
 };
 const r=check(read);
 assert.ok(r.violations.length>0,label+': the guard must fail');
 assert.ok(r.violations.some(v=>v.startsWith(file+':')),label+': names '+file+' ('+r.violations.join('; ')+')');
 console.log('  mutant fails as expected ('+label+'): '+r.violations[0]);ok();
}
console.log(JSON.stringify({passed,closureChecked:true}));
