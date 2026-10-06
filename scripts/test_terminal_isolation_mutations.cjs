// Mutation check for scripts/test_terminal_isolation.cjs: every guard below is removed
// or weakened in a temporary copy of the production sources, and the test must fail.
// MQL-free; the repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['GOAT_Inputs_Definitions.mqh','GOATEADeviceActivation.mqh','GOAT V1.49.mq5','GOATStudioSettingCompare.mqh'];
const R=String.raw;
// [label, file, from, to, occurrence (1-based)]
const mutations=[
  ['base is shared again','GOAT_Inputs_Definitions.mqh',R`return GoatOptLegacyBasePath(ea_name,server_name)+"-"+GoatOptLoginToken()+"-"+GoatOptTerminalHash();`,R`return GoatOptLegacyBasePath(ea_name,server_name);`],
  ['hash ignores case','GOAT_Inputs_Definitions.mqh',R`for(int i=0;i<total;i++) if(chars[i]>='A' && chars[i]<='Z') chars[i]=(ushort)(chars[i]+32);`,''],
  ['no account check on pairing','GOATEADeviceActivation.mqh',R`|| GOATAccountLoginDigits()!=g_GOATDeviceActivationAccountId) return false;`,R`|| false) return false;`],
  ['credential path re-read at the move','GOATEADeviceActivation.mqh',R`FileMove(temporary,FILE_COMMON,credential,FILE_COMMON|FILE_REWRITE)`,R`FileMove(temporary,FILE_COMMON,GOAT_API_BEARER_FILE,FILE_COMMON|FILE_REWRITE)`],
  ['no-account falls back to the shared file','GOAT_Inputs_Definitions.mqh',R`if(login=="") return "GOAT\\Credentials\\no-account.token";`,R`if(login=="") return GOAT_API_BEARER_LEGACY_FILE;`],
  // INV-CRED-02: one slot per login, terminal and build; legacy files never adopted.
  ['slot ignores the terminal','GOAT_Inputs_Definitions.mqh',R`return terminal+"-"+build;`,R`return "x-"+build;`],
  ['slot ignores the build','GOAT_Inputs_Definitions.mqh',R`return terminal+"-"+build;`,R`return terminal+"-x";`],
  ['new build reads the per-login file (pre-slot behaviour)','GOAT_Inputs_Definitions.mqh',R`return stem+"-"+login+"-"+slot+".token";`,R`return stem+"-"+login+".token";`],
  ['slot without a terminal hash','GOAT_Inputs_Definitions.mqh',R`if(StringLen(terminal)!=8 || terminal=="00000000" || build=="") return "";`,R`if(build=="") return "";`],
  ['pairing stores into the no-slot name','GOATEADeviceActivation.mqh',R`if(credential=="GOAT\\Credentials\\no-account.token") return false;`,''],
  ['build token keeps unsafe characters','GOATEADeviceActivation.mqh',R`|| (c>='0' && c<='9') || c=='-');`,R`|| (c>='0' && c<='9') || c=='-' || c=='.' || c=='/');`],
  ['overlong build accepted','GOATEADeviceActivation.mqh',R`if(length<1 || length>64) return "";`,R`if(length<1) return "";`],
  ['legacy notice repeats every request','GOAT_Inputs_Definitions.mqh',R`   g_GOATCredentialMigrationChecked=true;
   if(FileIsExist(GOATApiBearerFileFor(login),FILE_COMMON)) return;`,R`   if(FileIsExist(GOATApiBearerFileFor(login),FILE_COMMON)) return;`],
  ['batch mover ignores both-exist','GOAT_Inputs_Definitions.mqh',R`if(existing!="")`,R`if(false)`],
  ['batch mover takes another terminal batch','GOAT_Inputs_Definitions.mqh',R`if(!here)`,R`if(false)`],
  ['batch mover moves owned controls','GOAT_Inputs_Definitions.mqh',R`if(FileIsExist(legacy+"\\agent-native-control-owner.json",FILE_COMMON))`,R`if(false)`],
  ['guard keeps the old config path','GOAT_Inputs_Definitions.mqh',R`StringReplace(guard,"ConfigPath="+legacy+"\\active_optimization_config.ini","ConfigPath="+base+"\\active_optimization_config.ini");`,''],
  ['claim ignored on resume','GOAT_Inputs_Definitions.mqh',R`if(!GoatOptIsolationClaim(legacy,base,holder))`,R`if(!GoatOptIsolationClaim(legacy,base,holder) && false)`,1],
  ['claim ignored on a fresh move','GOAT_Inputs_Definitions.mqh',R`if(!GoatOptIsolationClaim(legacy,base,holder))`,R`if(!GoatOptIsolationClaim(legacy,base,holder) && false)`,2],
  ['claim is not create-only','GOAT_Inputs_Definitions.mqh',R`&& !FileMove(temporary,FILE_COMMON,claim,FILE_COMMON))`,R`&& !FileMove(temporary,FILE_COMMON,claim,FILE_COMMON|FILE_REWRITE))`],
  ['receipt names not validated','GOAT_Inputs_Definitions.mqh',R`if(!known) return`,R`if(false) return`],
  ['interrupted guard move not completed','GOAT_Inputs_Definitions.mqh',R`if(GoatOptReadTextFile(target)!=expected)`,R`if(true)`],
  ['plain file in both folders not refused','GOAT_Inputs_Definitions.mqh',R`if(have_target)`,R`if(false)`,2],
  ['wrapper ignores a missing account','GOAT_Inputs_Definitions.mqh',R`if(MQLInfoInteger(MQL_TESTER) || GoatOptLoginToken()=="0") return "";`,R`if(MQLInfoInteger(MQL_TESTER)) return "";`],
  ['wrapper ignores the chart lock','GOAT_Inputs_Definitions.mqh',R`if(!held) return`,R`if(false) return`],
  ['wrapper ignores the native gate','GOAT_Inputs_Definitions.mqh',R`if(gate==INVALID_HANDLE)`,R`if(false)`],
  ['wrapper re-takes the lock after a decision','GOAT_Inputs_Definitions.mqh',R`if(decided!="" && decided!="moving") return "";`,''],
  ['foreign check compares whole names','GOAT_Inputs_Definitions.mqh',R`if(ShortArrayToString(chars,0,total)==own_hash) return false;`,''],
  ['foreign check accepts shared folders','GOAT_Inputs_Definitions.mqh',R`return (c=='-' && digits>0);`,R`return true;`],
  ['fitness maximum written without a read','GOAT V1.49.mq5',R`if(fitness_read && fitness>readVal)`,R`if(fitness>readVal)`],
  ['empty fitness read trusted','GOAT V1.49.mq5',R`fitness_read=(stored!="");`,R`fitness_read=true;`],
  ['fitness wait unbounded','GOAT V1.49.mq5',R`while(FileTester_handle==INVALID_HANDLE && GetTickCount64()<fitness_deadline)`,R`while(FileTester_handle==INVALID_HANDLE)`,1],
  ['nonce not handed to agents','GOAT V1.49.mq5',R`if(!ParameterSetRange("GOAT_FitnessRunNonce",false,g_goat_fitness_nonce,g_goat_fitness_nonce,1,g_goat_fitness_nonce))`,R`if(false)`],
  ['agents ignore the nonce','GOAT V1.49.mq5',R`GoatOptTesterFitnessFile(EA_Desc,Symbol(),GOAT_FitnessRunNonce)`,R`GoatOptTesterFitnessFile(EA_Desc,Symbol(),0)`],
  ['nonce readback accepts an optimized axis','GOATStudioSettingCompare.mqh',R`parts[8]=="N"`,R`parts[8]!=""`],
  ['transient claim recorded as another terminal winning','GOAT_Inputs_Definitions.mqh',R`if(g_goat_opt_claim_transient)`,R`if(false)`],
  ['unreadable holder not treated as transient','GOAT_Inputs_Definitions.mqh',R`g_goat_opt_claim_transient=(holder!=me && !GoatOptIsolationHolderValid(holder));`,R`g_goat_opt_claim_transient=false;`],
  ['refused nonce keeps a key the agents never see','GOAT V1.49.mq5',R`g_goat_fitness_nonce=GOAT_FitnessRunNonce;`,''],
  ['keyless agents skip the de-noise step','GOAT V1.49.mq5',R`string fitness_file=GoatOptTesterFitnessFile(EA_Desc,Symbol(),GOAT_FitnessRunNonce);`,
   R`if(GOAT_FitnessRunNonce==0) return fitness; string fitness_file=GoatOptTesterFitnessFile(EA_Desc,Symbol(),GOAT_FitnessRunNonce);`],
  ['keyless agents keep the noisy fitness','GOAT V1.49.mq5',R`fitness = AdjustFitness(fitness_real,trades,mean_duration);`,R`if(GOAT_FitnessRunNonce!=0) fitness = AdjustFitness(fitness_real,trades,mean_duration);`],
  ['fallback seeds a key the agents never read','GOAT V1.49.mq5',R`FileOpen(GoatOptTesterFitnessFile(EA_Desc,Symbol(),g_goat_fitness_nonce),FILE_TXT|FILE_WRITE`,R`FileOpen(GoatOptTesterFitnessFile(EA_Desc,Symbol(),g_goat_fitness_nonce+1),FILE_TXT|FILE_WRITE`],
];
const work=fs.mkdtempSync(path.join(os.tmpdir(),'goat-isolation-mutation-'));
let caught=0;
try{
  for(const [label,file,from,to,occurrence=1] of mutations){
    fs.rmSync(work,{recursive:true,force:true});fs.mkdirSync(work,{recursive:true});
    for(const f of files){
      let text=fs.readFileSync(path.join(repo,f),'utf8');
      if(f===file){
        text=text.replace(/\r\n/g,'\n');let at=-1;
        for(let n=0;n<occurrence;n++){at=text.indexOf(from,at+1);if(at<0)throw new Error('mutation anchor missing: '+label);}
        text=text.slice(0,at)+to+text.slice(at+from.length);
      }
      fs.writeFileSync(path.join(work,f),text);
    }
    const r=spawnSync(process.execPath,[path.join(__dirname,'test_terminal_isolation.cjs')],{encoding:'utf8',timeout:30000,env:{...process.env,GOAT_EA_ROOT:work}});
    // Caught means a failed assertion (or a hang the test bounds), never a broken harness.
    const timedOut=!!r.error&&r.error.code==='ETIMEDOUT',asserted=/AssertionError/.test(r.stderr||'');
    const failed=r.status!==0&&(timedOut||asserted);caught+=failed;
    console.log((failed?'CAUGHT ':'MISSED ')+label+(timedOut?' (hang)':asserted?'':' (status '+r.status+')'));
  }
}finally{fs.rmSync(work,{recursive:true,force:true});}
console.log(caught+'/'+mutations.length+' mutations caught');
process.exit(caught===mutations.length?0:1);
