// Mutation check for the profile-staged deploy (goatai#1885 6033450916): every adoption guard, the
// deploy_next refusal, the disabled buttons and the retired template path are load-bearing. Each
// mutant edits one production source in memory; test_profile_staged_adoption.cjs must then fail.
const assert=require('node:assert/strict');
const {run,readSources}=require('./test_profile_staged_adoption.cjs');
const MUTANTS=[
 ['setup','period check dropped','|| ChartPeriod(adopt_chart)!=adopt_period',''],
 ['setup','period read from two characters','adopt_token+=ShortToString(adopt_c);','if(StringLen(adopt_token)<2) adopt_token+=ShortToString(adopt_c);'],
 ['setup','EA name check dropped','\n      || ChartGetString(adopt_chart,CHART_EXPERT_NAME)!=DashboardDialog.EA_Name_) return false;\n   long adopt_found=0;',') return false;\n   long adopt_found=0;'],
 ['setup','CID record not required','if(!GoatFindMagicByCid(adopt_sym,adopt_chart,adopt_found) || adopt_found<=0) return false;','GoatFindMagicByCid(adopt_sym,adopt_chart,adopt_found);'],
 ['setup','symbol check dropped','|| ChartSymbol(adopt_chart)!=adopt_sym ',''],
 ['setup','magic used by another row accepted','\n         || DashboardDialog.g_sets[adopt_other].magic==adopt_found',''],
 ['setup','chart claimed by another row accepted','DashboardDialog.g_sets[adopt_other].cid==adopt_chart\n','false\n'],
 ['setup','dashboard chart accepted','|| adopt_chart<=0 || adopt_chart==ChartID()) return false;\n   string adopt_sym','|| adopt_chart<=0) return false;\n   string adopt_sym'],
 ['setup','second match accepted','if(adopt_same_row==1 && adopt_same_chart==1)','if(adopt_same_row>=1)'],
 ['setup','adoption runs while not inert','if(!GoatAdoptInert() || adopt_rows<1','if(adopt_rows<1'],
 ['setup','inert ignores Algo Trading','&& TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)','&& TerminalInfoInteger(TERMINAL_CONNECTED)'],
 ['setup','inert ignores positions','&& PositionsTotal()==0 && OrdersTotal()==0);','&& OrdersTotal()==0);'],
 ['setup','fallback skips settingsMatch','if(adopt_shot=="" || !GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_shot,adopt_deployment)) continue;','if(adopt_shot=="") continue;'],
 ['setup','cid first skips settingsMatch','\n         && GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_snapshot,adopt_deployment)',''],
 ['setup','cid first removed','if(DashboardDialog.g_sets[adopt_row].magic>0 || adopt_hint<=0 || adopt_sources[adopt_row]=="") continue;','continue;'],
 ['setup','registered hash ignored','GoatChildSetSource(DashboardDialog.g_sets[adopt_row].path,adopt_hashes[adopt_row],adopt_text)','GoatChildSetSource(DashboardDialog.g_sets[adopt_row].path,"sha-"+DashboardDialog.g_sets[adopt_row].path,adopt_text)'],
 ['setup','hash count not checked','|| ArraySize(adopt_hashes)!=adopt_rows) return 0;',') return 0;'],
 ['setup','chart fingerprinted per row','if(!adopt_taken)\n         {','if(true)\n         {'],
 ['setup','start-up window shortened','#define GOAT_CHILD_START_WAIT_SECONDS 240','#define GOAT_CHILD_START_WAIT_SECONDS 60'],
 ['setup','never late','bool adopt_late=(TimeGMT()-GoatAdoptWindowStart>GOAT_CHILD_START_WAIT_SECONDS);','bool adopt_late=false;'],
 ['setup','child_not_started not recorded','if(adopt_late) GoatAdoptNote("child_not_started"','if(false) GoatAdoptNote("child_not_started"'],
 ['setup','ambiguity not recorded','else GoatAdoptNote("child_identity_ambiguous"','else if(false) GoatAdoptNote("child_identity_ambiguous"'],
 ['setup','unmatched look-alike not recorded','if(!adopt_claimed) GoatAdoptNote("child_unmatched"','if(false) GoatAdoptNote("child_unmatched"'],
 ['setup','deploy_next not refused','if(matched && action=="deploy_next") result="rejected_deploy_next_retired";\n   else ',''],
 ['setup','deploy_next refusal while not inert lost','if(matched && action=="deploy_next") result="rejected_deploy_next_retired";\n   else if(matched && action!="status" && !inert)','if(matched && action!="status" && !inert) result="rejected_not_inert";\n   else if(matched && action=="deploy_next") result="rejected_deploy_next_retired";\n   if(false)'],
 ['setup','mutations ignore inert','if(matched && inert && (action=="configure" || action=="link_children" || action=="apply_policy"))','if(matched && (action=="configure" || action=="link_children" || action=="apply_policy"))'],
 ['setup','link_children not mutation-class','|| action=="link_children" || action=="apply_policy"))','|| action=="apply_policy"))'],
 ['setup','link_children ignores AI policy','else if(DashboardDialog.m_ai_launch_mode!=ai','else if(action!="link_children" && DashboardDialog.m_ai_launch_mode!=ai'],
 ['setup','children_pending reported as linked','result=(all ? "children_linked" : "children_pending");','result="children_linked";'],
 ['setup','mutations lose their intent receipt','\n      if(!GoatSetupWrite(receipt,GoatPortfolioSnapshot(id,action,hash,"started"))){FileClose(owner);return;}',''],
 ['setup','unlinked row reports its cid hint','IntegerToString(magic>0 ? DashboardDialog.g_sets[i].cid : (long)0)','IntegerToString(DashboardDialog.g_sets[i].cid)'],
 ['setup','unlinked row reports a negative magic','IntegerToString(magic>0 ? magic : (long)0)','IntegerToString(magic)'],
 ['dashboard','unsaved identity kept','      g_sets[adopt_idx].cid=adopt_was_cid;\n      g_sets[adopt_idx].magic=adopt_was_magic;\n',''],
 ['dashboard','AdoptChild duplicate magic accepted','|| g_sets[adopt_other].magic==adopt_magic)) return false;',')) return false;'],
 ['dashboard','AdoptChild re-adopts a linked row','|| adopt_chart==ChartID() || g_sets[adopt_idx].magic>0) return false;','|| adopt_chart==ChartID()) return false;'],
 ['dashboard','pending registration not consumed','GlobalVariableDel(GoatChildGVName(adopt_magic,g_sets[adopt_idx].sym,GOAT_GV_FIELD_MAGIC));',''],
 ['dashboard','AI launch audit not written','AppendAILaunchAudit(adopt_idx,"ADOPTED");',''],
 ['dashboard','retired message changed','"Use Next in the app to deploy; dashboard deploy returns in the next update"','"Use Next in the app to deploy."'],
 ['dashboard','Deploy All silently ignored','      if(!AllRowsDeployed())\n         MessageBox(GOAT_DASH_DEPLOY_RETIRED_MESSAGE,"Portfolio",MB_OK|MB_ICONINFORMATION);\n',''],
 ['dashboard','per-row Activate silently ignored','      else\n         MessageBox(GOAT_DASH_DEPLOY_RETIRED_MESSAGE,"Portfolio",MB_OK|MB_ICONINFORMATION);\n\n      return(true);','\n      return(true);'],
 ['dashboard','Navigate lost','      if(btn_Action[row].Text()=="Navigate")\n         NavigateToSet(idx);\n      else\n','      if(false) {}\n      else\n'],
 ['dashboard','status event assigns a magic','            g_sets[idx].status=status;\n','            g_sets[idx].status=status;\n            if(g_sets[idx].magic<=0) g_sets[idx].magic=lparam;\n'],
 ['dashboard','template apply re-added','bool CGOATDashboard::NavigateToSet(const int idx)\n{','bool CGOATDashboard::NavigateToSet(const int idx)\n{\n   ChartApplyTemplate(0,"x.tpl");'],
 ['dashboard','chart opened again','bool CGOATDashboard::NavigateToSet(const int idx)\n{','bool CGOATDashboard::NavigateToSet(const int idx)\n{\n   long opened=ChartOpen("EURUSD",PERIOD_M1);'],
 ['dashboard','kernel32 copy plumbing re-added','#define GOAT_DASH_DEPLOY_RETIRED_MESSAGE','#import "kernel32.dll"\n   int CopyFileW(string src, string dst, int fail_if_exists);\n#import\n#define GOAT_DASH_DEPLOY_RETIRED_MESSAGE'],
 ['dashboard','portfolio button still says Activate all','string action_text=(all_deployed ? "All active" : "Deploy in app");','string action_text=(all_deployed ? "All active" : "Activate all");'],
 ['setup','adoption ignores the deployment nonce','GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_shot,adopt_deployment)','GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_shot,"")'],
 ['setup','cid first ignores the deployment nonce','GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_snapshot,adopt_deployment)','GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_snapshot,"")'],
 ['setup','unbound registration still adopts','if(!GOATIsLowerHex(adopt_deployment,32))\n   {','if(false)\n   {'],
 ['setup','registration deploymentId not bound','   if(reg_bound) GoatPortfolioDeployment=reg_deployment;\n',''],
 ['setup','registration accepts an invalid deploymentId','&& GOATIsLowerHex(reg_deployment,32);',';'],
 ['setup','registration requires a deploymentId','(!reg_bound && !GOATJsonExactFields(registration,reg,0,reg_fields))','!reg_bound'],
 ['setup','audit not given the nonce','GoatPortfolioChildSettingsMatch(i,GoatPortfolioExpectedHashes[i],GoatPortfolioDeployment)','GoatPortfolioChildSettingsMatch(i,GoatPortfolioExpectedHashes[i],"")'],
 ['setup','link_children not given the deployment','GoatPortfolioAdoptChildren(GoatPortfolioExpectedHashes,GoatPortfolioDeployment);','GoatPortfolioAdoptChildren(GoatPortfolioExpectedHashes,"");'],
 ['audit','nonce taken from the chart','if(deploy_tag!="" && omitted_names[n]=="Studio_MonitorRunPath") audit_pinned="deploy="+deploy_tag;','if(deploy_tag!="" && omitted_names[n]=="Studio_MonitorRunPath") {for(int k=0;k<ArraySize(actual_names);k++) if(actual_names[k]==omitted_names[n]) audit_pinned=actual_values[k];}'],
 ['audit','nonce never pinned','if(deploy_tag!="" && omitted_names[n]=="Studio_MonitorRunPath") audit_pinned="deploy="+deploy_tag;',''],
 ['audit','invalid id accepted by the audit','   if(deploy_tag!="" && !GOATIsLowerHex(deploy_tag,32)) return false;\n',''],
 ['audit','nonce dropped before the map compare','snapshot,expected_path,deploy_tag);','snapshot,expected_path);'], ['audit','template apply in the audit','bool saved=ChartSaveTemplate(cid,"\\\\Files\\\\"+filename);','bool saved=ChartSaveTemplate(cid,"\\\\Files\\\\"+filename); ChartApplyTemplate(cid,filename);'],
 ['main','template apply in the entrypoint','#define   GOAT_BUILD_MARKER "B43"','#define   GOAT_BUILD_MARKER "B43"\n// ChartApplyTemplate'],
];
const base=readSources();
assert.ok(run(base)>0,'the unmutated suite passes');
let killed=0;
for(const [file,label,from,to] of MUTANTS){
 const n=base[file].split(from).length-1;
 assert.equal(n,1,`mutant "${label}": its anchor must occur exactly once in ${file} (found ${n})`);
 const src={...base,[file]:base[file].replace(from,()=>to)};
 let survived=false;
 try{run(src);survived=true;}catch(e){killed++;}
 assert.ok(!survived,`mutant survived: ${label}`);
}
console.log(JSON.stringify({mutants:MUTANTS.length,killed}));
