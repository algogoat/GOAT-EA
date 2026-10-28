// Mutation check for B49b PR-7 (F8, export integrity): every rule is load-bearing. Each mutant edits one source in
// memory (GOAT V1.49.mq5, Tester.mqh or XmlProcessor.mqh); test_b49b_f8.cjs, run on the mutated file (GOAT_EA_MAIN,
// GOAT_EA_TESTER, GOAT_EA_XML), must then fail.
'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),TEST=path.join(__dirname,'test_b49b_f8.cjs');
const FILES={main:['GOAT V1.49.mq5','GOAT_EA_MAIN'],tester:['Tester.mqh','GOAT_EA_TESTER'],xml:['XmlProcessor.mqh','GOAT_EA_XML']};
const TEXT=Object.fromEntries(Object.entries(FILES).map(([k,[f]])=>[k,fs.readFileSync(path.join(ROOT,f),'utf8').replace(/\r\n/g,'\n')]));
const MUTANTS=[
 // OPT-01, the trim.
 ['tester','failing rows are not put last (B49a\'s order)','   if(pass_a!=pass_b) return pass_a;\n',''],
 ['tester','failing rows first','   if(pass_a!=pass_b) return pass_a;','   if(pass_a!=pass_b) return pass_b;'],
 ['tester','lowest score first','return (GoatExportRankScore(a,rank)>GoatExportRankScore(b,rank));','return (GoatExportRankScore(a,rank)<GoatExportRankScore(b,rank));'],
 ['tester','PF ranks on ARF x SR','return (rank==GOAT_EXPORT_RANK_PF ? r.pf : r.arf*r.sr);','return (r.arf*r.sr);'],
 ['tester','ARF x SR ranks on PF','return (rank==GOAT_EXPORT_RANK_PF ? r.pf : r.arf*r.sr);','return (r.pf);'],
 ['tester','a row passes on ARF alone','return (r.arf>=minARF && r.sr>=minSR);','return (r.arf>=minARF);'],
 ['tester','a row at the bar fails','return (r.arf>=minARF && r.sr>=minSR);','return (r.arf>minARF && r.sr>minSR);'],
 ['tester','keepTop is ignored','   for(int i = 0; i < n && passCnt < keepTop; ++i)\n   {\n      if(GoatExportPasses','   for(int i = 0; i < n; ++i)\n   {\n      if(GoatExportPasses'],
 ['tester','none passing keeps nothing','   else            keepCnt = 1;       // nothing passes','   else            keepCnt = 0;       // nothing passes'],
 ['tester','the fallback is not logged','(passCnt>0 ? "" : " (fallback: none passed, the best-ranked row kept)")','""'],
 ['tester','the log\'s Passing is every passing row',' Rank=%s%s",n,passCnt,keepCnt,',' Rank=%s%s",n,passCnt+(n>keepCnt && passCnt>0 ? 1 : 0),keepCnt,'],
 ['tester','the log hides the rank','(rank==GOAT_EXPORT_RANK_PF ? "PF" : "ARFxSR")','"ARFxSR"'],
 ['tester','pf is a valid setting','   if(value=="PF") return GOAT_EXPORT_RANK_PF;','   if(value=="PF" || value=="pf") return GOAT_EXPORT_RANK_PF;'],
 ['tester','an unknown setting falls back to ARF x SR','   return -1;\n  }\ndouble GoatExportRankScore','   return GOAT_EXPORT_RANK_ARFxSR;\n  }\ndouble GoatExportRankScore'],
 ['main','an unknown ExportRank runs the exports','No exports were run.",Key,EA_Name,Server); return false;} // B49b (F8)','No exports were run.",Key,EA_Name,Server);} // B49b (F8)'],
 ['main','rank=pf is never sent','(ExportRank==GOAT_EXPORT_RANK_PF ? ",rank=pf" : "")','""'],
 ['main','the export run ignores rank=pf','if(names[i]=="rank" && values[i]=="pf") g_GoatExportRank=GOAT_EXPORT_RANK_PF;','if(false) g_GoatExportRank=GOAT_EXPORT_RANK_PF;'],
 ['main','the adjusted trim ranks on ARF x SR','SortAndTrimExports(SetsToExport,MinARF,MinSR,AdjustedExports,ExportRank);','SortAndTrimExports(SetsToExport,MinARF,MinSR,AdjustedExports);'],
 // OPT-04.
 ['xml','a repeated pass is not rejected','{forwardMismatches++; Rows[bPos].forward_mismatch=true;} // B49b (F8 OPT-04)','{forwardMismatches++;} // B49b (F8 OPT-04)'],
 ['xml','a back-result mismatch is not rejected','forwardMismatches++; Rows[bPos].forward_mismatch=true; // B49b (F8 OPT-04)\n               LogOrPrint(reportMode,"❌ Back result','forwardMismatches++; // B49b (F8 OPT-04)\n               LogOrPrint(reportMode,"❌ Back result'],
 ['xml','an inputs mismatch is not rejected','forwardMismatches++; Rows[bPos].forward_mismatch=true; // B49b (F8 OPT-04)\n               LogOrPrint(reportMode,"❌ Inputs','forwardMismatches++; // B49b (F8 OPT-04)\n               LogOrPrint(reportMode,"❌ Inputs'],
 ['xml','a mismatched row keeps its score','               Rows[bPos].Score=0;\n','\n'],
 ['xml','a copy drops the mark','      forward_mismatch=src.forward_mismatch; // B49b (F8 OPT-04)\n',''],
 ['xml','a new row starts marked','forward_seen=false; forward_mismatch=false; // B49b (F8 OPT-04)','forward_seen=false; forward_mismatch=true; // B49b (F8 OPT-04)'],
 // R16.
 ['main','BOOS leaves its last day out','     if(days_IS==0 && days_BOOS>0) eq_BOOS_end = DStartEquity;','     if(false) eq_BOOS_end = DStartEquity;'],
 ['main','SAMPLE leaves its last day out','     if(days_FOOS==0 && days_IS>0) eq_IS_end = DStartEquity;','     if(false) eq_IS_end = DStartEquity;'],
 ['main','FWD leaves its last day out','    else if(days_FWD>0 && !g_GoatFwdClosed) {eq_FWD_end = DStartEquity; g_GoatFwdClosed=true;}','    else if(false) {eq_FWD_end = DStartEquity; g_GoatFwdClosed=true;}'],
 ['main','FWD keeps closing on later days','    else if(days_FWD>0 && !g_GoatFwdClosed) {eq_FWD_end = DStartEquity; g_GoatFwdClosed=true;}','    else if(days_FWD>0) {eq_FWD_end = DStartEquity;}'],
 ['main','FWD by the clock (B49a)','   return (day>=(long)dt_FWD_start/86400 && day<=(long)dt_FWD_end/86400);','   return (when>=dt_FWD_start && when<=dt_FWD_end);'],
 ['main','FWD trades by the clock (B49a)','   if(GoatFwdDay(TimeCurrent())) trd_FWD++;','   if(dt_FWD_start!=0 && dt_FWD_end!=0 && TimeCurrent()>=dt_FWD_start && TimeCurrent()<=dt_FWD_end) trd_FWD++;'],
 ['main','an open SAMPLE stays at its last day\'s open','   if(days_IS>0 && days_FOOS==0)                  eq_IS_end=final_equity;\n',''],
 ['main','an open FWD stays at its last day\'s open','   if(days_FWD>0 && !g_GoatFwdClosed)             {eq_FWD_end=final_equity; g_GoatFwdClosed=true;}\n',''],
 ['main','an open BOOS stays at its last day\'s open','   if(days_BOOS>0 && days_IS==0 && days_FOOS==0) eq_BOOS_end=final_equity;\n',''],
 ['main','windows are closed after they print','   GoatCloseOpenWindows(); // B49b (F8 R16): a window still open at the test\'s end closes at its final equity\n',''],
 // R17.
 ['main','no final row','{GoatEquityCsvFinalRow(); FileClose(FileCSV_handle);','{FileClose(FileCSV_handle);'],
 ['main','the final row repeats a written minute','   if((long)TimeCurrent()/60==g_GoatCsvLastMinute) return;\n',''],
 ['main','minute rows do not record their minute','       g_GoatCsvLastMinute=(long)TimeCurrent()/60; // B49b (F8 R17): the final row never repeats this minute\n',''],
 ['main','the final row writes the balance as equity','                           ,DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)\n                           ,0.0);','                           ,DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2)\n                           ,0.0);'],
 // R21.
 ['main','the tester wait is unbounded (B49a)','      if(GetTickCount64()>readyDeadline) {','      if(false) {'],
 ['main','a timed-out wait goes on exporting','s after the top-set check. No exports were run.",Key,EA_Name,Server); return false;} // B49b (F8 R21)','s after the top-set check. No exports were run.",Key,EA_Name,Server);} // B49b (F8 R21)'],
 // The stamp.
 ['main','the stamp says format 1','#define GOAT_EXPORT_FORMAT        2','#define GOAT_EXPORT_FORMAT        1'],
 ['main','the stamp holds =','   return "; EXPORT format:"+IntegerToString(GOAT_EXPORT_FORMAT)+" rank:"','   return "; EXPORT format="+IntegerToString(GOAT_EXPORT_FORMAT)+" rank:"'],
 ['main','the stamp hides the rank','(g_GoatExportRank==GOAT_EXPORT_RANK_PF ? "pf" : "arf_sr")','"arf_sr"'],
 ['main','a blind export carries no stamp','WriteSet(GoatBlindDesc(desc)+"\\n"+GoatExportFormatLine());','WriteSet(GoatBlindDesc(desc));'],
 // The rank:pf read-back (Claude-Mac 6469934085).
 ['main','a PF export is never read back','   if(g_GoatExporterRank==GOAT_EXPORT_RANK_PF)\n   {\n    string stamp_set="";','   if(false)\n   {\n    string stamp_set="";'],
 ['main','a mislabelled PF export is kept','"pf"))\n    {LogOrPrint(reportMode,"❌ Export is not stamped rank:pf while ExportRank=PF: "+FileNameOnly(exports[0])+". Skipping...",Key,EA_Name,Server); return -1;}','"pf"))\n    {LogOrPrint(reportMode,"❌ Export is not stamped rank:pf while ExportRank=PF: "+FileNameOnly(exports[0])+". Skipping...",Key,EA_Name,Server);}'],
 ['main','the exporter never sets its rank','    g_GoatExporterRank=ExportRank; // B49b (F8): RunAndStoreSet reads each PF export\'s stamp back\n',''],
 ['main','a repeated format line passes','   return (found==1 && match);','   return (match);'],
 ['main','any format line passes','      match=(line=="; EXPORT format:"+IntegerToString(GOAT_EXPORT_FORMAT)+" rank:"+rank);','      match=true;'],
 ['main','a full-span export carries no stamp','ranked:full_span sr:mt5_stat\\n"+GoatExportFormatLine());','ranked:full_span sr:mt5_stat");'],
];
function runOn(which,text){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'goat-f8-'));
 try{
  const [name,env]=FILES[which],file=path.join(dir,name);
  fs.writeFileSync(file,'﻿'+text.replace(/\n/g,'\r\n'),'utf8');
  return spawnSync(process.execPath,[TEST],{cwd:ROOT,env:{...process.env,[env]:file},encoding:'utf8',timeout:120000});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
for(const which of Object.keys(FILES)){const r=runOn(which,TEXT[which]);assert.equal(r.status,0,'the unmutated test passes on the scratch '+which+': '+r.stderr);}
let killed=0;
for(const [which,label,from,to] of MUTANTS){
 const n=TEXT[which].split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${FILES[which][0]} (found ${n})`);
 const r=runOn(which,TEXT[which].replace(from,()=>to));
 assert.notEqual(r.status,0,`mutant survived: ${label}`);
 killed++;
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
