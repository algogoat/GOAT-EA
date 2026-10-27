// Mutation check for B49b PR-1 (F7): every money, volume, handle and buffer guard is load-bearing. Each mutant edits
// GOAT V1.49.mq5 in memory; test_b49b_f7.cjs, run on the mutated entrypoint (GOAT_EA_MAIN), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f7.cjs');
const MAIN=fs.readFileSync(path.join(ROOT,'GOAT V1.49.mq5'),'utf8').replace(/\r\n/g,'\n');
const MUTANTS=[
 // EX-04: each fallback, and the flag's gate.
 ['the no-tick-size fallback stays per tick','      if(Fix_MoneyVolume==GoatFix_On && (!MathIsValidNumber(ts) || ts <= 0.0) && MathIsValidNumber(tv) && tv > 0.0) return tv/point;','      ;'],
 ['the account==quote fallback stays per point','            if(Fix_MoneyVolume==GoatFix_On && acc == quote && quote != "") return contract;','            ;'],
 ['the account==base fallback stays per point','            if(Fix_MoneyVolume==GoatFix_On && acc == base && base != "" && px > 0.0) return contract / px;','            ;'],
 ['the cross fallback stays per point','               if(Fix_MoneyVolume==GoatFix_On) return cross/point;','               ;'],
 ['the last-resort fallback stays per point','      if(Fix_MoneyVolume==GoatFix_On) return 1.0/point;','      ;'],
 ['a money fix runs with the flag off','      if(Fix_MoneyVolume==GoatFix_On && acc == quote && quote != "") return contract;','      if(acc == quote && quote != "") return contract;'],
 ['the no-tick fix divides by the tick size','tv > 0.0) return tv/point;','tv > 0.0) return tv;'],
 // EX-05/R9.
 ['the order volume keeps B49a\'s rounding','   if(Fix_MoneyVolume==GoatFix_On) return GoatStepNormalizedLots(size);','   ;'],
 ['the step volume runs with the flag off','   if(Fix_MoneyVolume==GoatFix_On) return GoatStepNormalizedLots(size);','   return GoatStepNormalizedLots(size);'],
 ['the volume is not clamped to the maximum','   if(vmax>0.0 && v>vmax) v=vmax;\n','\n'],
 ['a size below the minimum is raised to it','   if(vmin>0.0 && v<vmin) v=(MathAbs(size)>=vmin) ? vmin : 0.0;','   if(vmin>0.0 && v<vmin) v=vmin;'],
 ['the volume is rounded, not floored (Claude-Mac GOAT-EA#270)','   double v=MathFloor(MathAbs(size)/step+1e-9)*step;','   double v=MathRound(MathAbs(size)/step)*step;'],
 ['the floor loses a step to binary error','   double v=MathFloor(MathAbs(size)/step+1e-9)*step;','   double v=MathFloor(MathAbs(size)/step)*step;'],
 ['no step: the size is sent as it is','   if(!(step>0.0)) step=vmin;\n','\n'],
 ['the sign is lost','   return sign*NormalizeDouble(v,8);','   return NormalizeDouble(v,8);'],
 // SIG-02: each indicator's gate, the need, the stale rule, the log.
 ['RSI reads an empty buffer','   if((RSI_Mode!=RSI_Disabled) && GoatSignalReady(0,"RSI",GoatSignalBufferReady(RSI_handle,0,shift+0,2,(RSI_Mode==RSI_OverBS) ? 1 : 2,RSI_Buf),RSI_Sig))','   if((RSI_Mode!=RSI_Disabled))'],
 ['EMA reads an empty buffer','    if(EMA_Sample.CheckTF(EMA_TF) && GoatSignalReady(1,"EMA",GoatEmaBuffersReady(shift),EMA_Sig)) {','    if(EMA_Sample.CheckTF(EMA_TF)) {'],
 ['ADX reads an empty buffer','    if(ADX_Sample.CheckTF(ADX_TF) && GoatSignalReady(2,"ADX",GoatSignalBufferReady(ADX_handle,MAIN_LINE,shift+0,1,1,ADX_Main_Buf) // B49b (F7 SIG-02)\n       && GoatSignalBufferReady(ADX_handle,PLUSDI_LINE,shift+0,1,1,ADX_PLS_Buf) && GoatSignalBufferReady(ADX_handle,MINUSDI_LINE,shift+0,1,1,ADX_MNS_Buf),ADX_Sig)) {','    if(ADX_Sample.CheckTF(ADX_TF)) {'],
 ['one ADX line is not probed','       && GoatSignalBufferReady(ADX_handle,PLUSDI_LINE,shift+0,1,1,ADX_PLS_Buf) && GoatSignalBufferReady(ADX_handle,MINUSDI_LINE,shift+0,1,1,ADX_MNS_Buf),ADX_Sig)) {','       && GoatSignalBufferReady(ADX_handle,PLUSDI_LINE,shift+0,1,1,ADX_PLS_Buf),ADX_Sig)) {'],
 ['BB reads an empty buffer','    if(BB_Sample.CheckTF(BB_TF) && GoatSignalReady(3,"BB",GoatSignalBufferReady(BB_handle,BASE_LINE,shift,2,1,BB_Mi_Buf) // B49b (F7 SIG-02)\n       && GoatSignalBufferReady(BB_handle,UPPER_BAND,shift,2,1,BB_Hi_Buf) && GoatSignalBufferReady(BB_handle,LOWER_BAND,shift,2,1,BB_Lo_Buf),BB_Sig)) {','    if(BB_Sample.CheckTF(BB_TF)) {'],
 ['MACD reads an empty buffer','    if(MACD_Sample.CheckTF(MACD_TF) && GoatSignalReady(4,"MACD",GoatSignalBufferReady(MACD_handle,1,shift+0,1,1,MACD_Clr_Buf),MACD_Sig)) {','    if(MACD_Sample.CheckTF(MACD_TF)) {'],
 ['RSI2 reads an empty buffer','    if(RSI2_Sample.CheckTF(RSI2_TF) && GoatSignalReady(5,"RSI2",GoatSignalBufferReady(RSI2_handle,0,shift+0,2,(RSI2_Mode==RSI_OverBS) ? 1 : 2,RSI2_Buf),RSI2_Sig)) {','    if(RSI2_Sample.CheckTF(RSI2_TF)) {'],
 ['an RSI cross needs one value','2,(RSI_Mode==RSI_OverBS) ? 1 : 2,RSI_Buf)','2,1,RSI_Buf)'],
 ['RSI OverBS needs two values','2,(RSI_Mode==RSI_OverBS) ? 1 : 2,RSI_Buf)','2,2,RSI_Buf)'],
 ['an RSI2 cross needs one value','2,(RSI2_Mode==RSI_OverBS) ? 1 : 2,RSI2_Buf)','2,1,RSI2_Buf)'],
 ['a stale buffer is not reused','   return copied>=need || (copied<0 && ArraySize(buf)>=need);','   return copied>=need;'],
 ['a partial copy counts as ready','   return copied>=need || (copied<0 && ArraySize(buf)>=need);','   return copied>0 || (copied<0 && ArraySize(buf)>=need);'],
 ['a stale short buffer counts as ready','   return copied>=need || (copied<0 && ArraySize(buf)>=need);','   return copied>=need || copied<0;'],
 ['one EMA of the ladder is not probed','   for(int i=0;i<EMA_Count;i++) if(!GoatSignalBufferReady(EMA_handles[i],0,shift-0,1,1,EMAs[i].Buf)) return false;','   for(int i=0;i<EMA_Count-1;i++) if(!GoatSignalBufferReady(EMA_handles[i],0,shift-0,1,1,EMAs[i].Buf)) return false;'],
 ['the unready log repeats','   if(!g_goat_signal_short_logged[id])\n','   if(true)\n'],
 ['the unready log is never re-armed','   if(ready) {g_goat_signal_short_logged[id]=false; return true;}','   if(ready) return true;'],
 // SIG-01.
 ['RSI\'s handle is not checked','   if(RSI_Mode != RSI_Disabled && RSI_handle == INVALID_HANDLE) {Print("iRSI failed. err=",GetLastError()); return(INIT_FAILED);}\n',''],
 ['the EMA ladder\'s handles are not checked','   if(EMA_Mode != Trade_Disabled) for(int i=0;i<EMA_Count;i++) if(EMA_handles[i] == INVALID_HANDLE) {Print("iMA (EMA ",i+1,") failed. err=",GetLastError()); return(INIT_FAILED);}\n',''],
 ['ADX\'s handle is not checked','   if(ADX_Mode != Trade_Disabled && ADX_handle == INVALID_HANDLE) {Print("iADX failed. err=",GetLastError()); return(INIT_FAILED);}\n',''],
 ['BB\'s handle is not checked','   if(BB_Mode  != BB_Disabled && BB_handle == INVALID_HANDLE) {Print("iBands failed. err=",GetLastError()); return(INIT_FAILED);}\n',''],
 ['MACD\'s handle is not checked','   if(MACD_Mode!= Trade_Disabled && MACD_handle == INVALID_HANDLE) {Print("iCustom MACD failed. err=",GetLastError()," path=",MACD_Path); return(INIT_FAILED);}\n',''],
 ['RSI2\'s handle is not checked','   if(RSI2_Mode!= RSI_Disabled && RSI2_handle == INVALID_HANDLE) {Print("iRSI (RSI2) failed. err=",GetLastError()); return(INIT_FAILED);}\n',''],
 ['a disabled indicator\'s handle refuses','   if(ADX_Mode != Trade_Disabled && ADX_handle == INVALID_HANDLE)','   if(ADX_handle == INVALID_HANDLE)'],
];
function runOn(mainText){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f7-'));
 try{
  const file=path.join(dir,'GOAT V1.49.mq5');
  fs.writeFileSync(file,'﻿'+mainText.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,GOAT_EA_MAIN:file},encoding:'utf8',timeout:180000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
const unmutated=runOn(MAIN);
assert.equal(unmutated.status,0,'the unmutated test passes on the scratch entrypoint: '+unmutated.stderr);
let killed=0;
for(const [label,from,to] of MUTANTS){
 const n=MAIN.split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in GOAT V1.49.mq5 (found ${n})`);
 const r=runOn(MAIN.replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
