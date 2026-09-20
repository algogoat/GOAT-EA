#ifndef GOAT_STUDIO_DISPATCH_MQH
#define GOAT_STUDIO_DISPATCH_MQH
#include "GOATStudioWorkers.mqh"
// Included after Studio UI helpers. Requests are terminal-local and require the
// same exclusive launch.lock used by every configured controller transaction.
bool GoatStudioCommonDigest(const string path,const string expected)
  {
   int h=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h); uchar data[],key[],digest[];
   if(size==0 || size>2000000) {FileClose(h);return false;}
   uint read=FileReadArray(h,data,0,(uint)size);FileClose(h);
   if(read!=size || CryptEncode(CRYPT_HASH_SHA256,data,key,digest)!=32) return false;
   string hex="";for(int i=0;i<32;i++) hex+=StringFormat("%02x",digest[i]);
   return hex==expected;
  }

string GoatStudioExecuteRequest(const string body,const string request_hash)
  {
   SGOATJsonToken t[],snapshot_tokens[];
   string id,terminal,run,owner,job_id,config_hash,ini,ini_hash,expected_data,installation,login,server,native_run,alias;
   long version,revision,generation,expires;
   if(!GOATJsonParse(body,t)
      || !GOATJsonGetInteger(body,t,0,"schema_version",version) || version!=1
      || !GOATJsonGetString(body,t,0,"request_id",id) || !GoatStudioId(id)
      || !GOATJsonGetString(body,t,0,"terminal_id",terminal) || terminal!=g_StudioBridge.TerminalId()
      || !GOATJsonGetString(body,t,0,"run_id",run) || run!=g_StudioBridge.RunId()
      || !GOATJsonGetString(body,t,0,"owner",owner)
      || !GOATJsonGetString(body,t,0,"job_id",job_id)
      || !GOATJsonGetString(body,t,0,"configuration_sha256",config_hash)
      || !GOATJsonGetInteger(body,t,0,"revision",revision)
      || !GOATJsonGetInteger(body,t,0,"generation",generation)
      || !GOATJsonGetInteger(body,t,0,"expires_utc",expires)
      || expires<=(long)TimeGMT() || expires>(long)TimeGMT()+120
      || !GOATJsonGetString(body,t,0,"data_path",expected_data) || expected_data!=TerminalInfoString(TERMINAL_DATA_PATH)
      || !GOATJsonGetString(body,t,0,"installation_path",installation) || installation!=TerminalInfoString(TERMINAL_PATH)
      || !GOATJsonGetString(body,t,0,"account_login",login) || login!=(string)AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetString(body,t,0,"account_server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(body,t,0,"tester_ini",ini)
      || !GOATJsonGetString(body,t,0,"tester_ini_sha256",ini_hash)
      || !GOATJsonGetString(body,t,0,"native_run",native_run)
      || !GOATJsonGetString(body,t,0,"alias",alias)) return "REQUEST_REJECTED";
   if(StringLen(native_run)!=18 || StringFind(native_run,"GOAT\\R")!=0 || StringLen(alias)!=21 || StringSubstr(alias,0,1)!="R") return "NATIVE_PATH_REJECTED";
   string hexadecimal=StringSubstr(native_run,6)+StringSubstr(alias,1);
   for(int i=0;i<StringLen(hexadecimal);i++) if(StringFind("0123456789abcdef",StringSubstr(hexadecimal,i,1))<0) return "NATIVE_PATH_REJECTED";
   if(IsStopped() || !MQLInfoInteger(MQL_DLLS_ALLOWED) || !TerminalInfoInteger(TERMINAL_CONNECTED) || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO || GoatStudioTesterState()!="idle"
      || GlobalVariableGet("BatchOnGoing")!=0 || GlobalVariableGet("GOAT_BatchRestartPending")!=0) return "RUNTIME_NOT_READY";
   string snapshot,actual_hash,state_owner;long state_revision,state_generation;
   if(!GOATSha256Utf8(ini,actual_hash) || actual_hash!=ini_hash || !g_StudioBridge.ReadSnapshot(snapshot)
      || !GOATJsonParse(snapshot,snapshot_tokens,16384,2000000)) return "CONFIG_OR_SNAPSHOT_REJECTED";
   int state=GOATJsonFindField(snapshot,snapshot_tokens,0,"state");
   if(!GOATJsonGetString(snapshot,snapshot_tokens,state,"owner",state_owner) || state_owner!=owner
      || !GOATJsonGetInteger(snapshot,snapshot_tokens,state,"revision",state_revision) || state_revision!=revision
      || !GOATJsonGetInteger(snapshot,snapshot_tokens,state,"generation",state_generation) || state_generation!=generation) return "CONTROL_REVOKED";
   int queue=GOATJsonFindField(snapshot,snapshot_tokens,state,"queue");bool matched=false;
   for(int i=0;i<ArraySize(snapshot_tokens);i++)
     {
      if(snapshot_tokens[i].parent!=queue || snapshot_tokens[i].type!=GOAT_JSON_OBJECT) continue;
      string current_id,current_hash,current_status;
      if(GOATJsonGetString(snapshot,snapshot_tokens,i,"job_id",current_id) && current_id==job_id
         && GOATJsonGetString(snapshot,snapshot_tokens,i,"configuration_sha256",current_hash) && current_hash==config_hash
         && GOATJsonGetString(snapshot,snapshot_tokens,i,"status",current_status) && current_status=="starting") matched=true;
     }
   if(!matched) return "JOB_NOT_STARTING";
   // Absent action retains the existing open-terminal protocol. Unknown actions
   // must never fall through to a native Start click.
   string action="start",startup_hash="";
   int action_token=GOATJsonFindField(body,t,0,"action");
   if(action_token>=0 && !GOATJsonGetString(body,t,0,"action",action)) return "ACTION_REJECTED";
   if(action!="start" && action!="arm_restart") return "ACTION_REJECTED";
   bool restart_matched=false,has_restart=false;
   for(int i=0;i<ArraySize(snapshot_tokens);i++)
     {
      if(snapshot_tokens[i].parent!=queue || snapshot_tokens[i].type!=GOAT_JSON_OBJECT) continue;
      string current_id,phase,attempt,expected_startup;
      if(!GOATJsonGetString(snapshot,snapshot_tokens,i,"job_id",current_id) || current_id!=job_id) continue;
      has_restart=(GOATJsonFindField(snapshot,snapshot_tokens,i,"restart_phase")>=0);
      restart_matched=GOATJsonGetString(snapshot,snapshot_tokens,i,"restart_phase",phase) && phase=="controls_installed"
         && GOATJsonGetString(snapshot,snapshot_tokens,i,"restart_attempt_id",attempt) && attempt==id
         && GOATJsonGetString(snapshot,snapshot_tokens,i,"restart_startup_sha256",expected_startup)
         && GOATJsonGetString(body,t,0,"startup_sha256",startup_hash)
         && StringLen(startup_hash)==64 && startup_hash==expected_startup;
     }
   if(action=="start" && has_restart) return "RESTART_ROUTE_SELECTED";
   if(action=="arm_restart" && !restart_matched) return "RESTART_INTENT_REJECTED";
   string base="GOAT\\GOAT V1.47-"+server;
   string paths[]={native_run+"\\queue.GOAT",native_run+"\\inputs\\"+alias+"\\Inputs.GOAT",
                   base+"\\active_optimization_run.ini",base+"\\active_optimization_config.ini",
                   base+"\\active_optimization_launch.ini",base+"\\agent-native-control-owner.json"};
   string fields[]={"queue_sha256","inputs_sha256","pointer_sha256","native_config_sha256","guard_sha256","native_owner_sha256"};
   for(int i=0;i<ArraySize(paths);i++)
     {
      string hash;if(!GOATJsonGetString(body,t,0,fields[i],hash) || !GoatStudioCommonDigest(paths[i],hash)) return "NATIVE_CONTROL_DRIFT";
     }
   string error,entries[];
   if(!GoatStudioINIEntries(ini,entries,error)) return "INVALID_TESTER_INI";
   // This immutable record precedes even setting the tester; any interruption
   // after consumption must be reconciled, never automatically sent again.
   if(!GoatStudioWriteUtf8("GOATStudio\\native-gate\\consumed-"+id+".json",body)) return "ALREADY_CONSUMED_OR_CLAIM_FAILED";
   if(action=="arm_restart")
     {
      // Consumption and intent precede the only effect. No clipboard settings,
      // tester Start message, terminal close or legacy restart helper here.
      if(IsStopped() || expires<=(long)TimeGMT() || GoatStudioTesterState()!="idle"
         || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_CONNECTED)
         || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO
         || login!=(string)AccountInfoInteger(ACCOUNT_LOGIN) || server!=AccountInfoString(ACCOUNT_SERVER)
         || GlobalVariableGet("BatchOnGoing")!=0 || GlobalVariableGet("GOAT_BatchRestartPending")!=0
         || GlobalVariableGet(GOAT_BATCH_CANCELLED_GV)!=0) return "RESTART_RUNTIME_CHANGED";
      if(!GoatStudioWriteUtf8("GOATStudio\\native-gate\\arm-intent-"+id+".json",
         "{\"request_sha256\":"+GoatStudioQuote(request_hash)+",\"startup_sha256\":"+GoatStudioQuote(startup_hash)+"}")) return "ARM_INTENT_WRITE_FAILED";
      if(GlobalVariableSet("BatchOnGoing",1.0)==0) return "ARM_FAILED";
      GlobalVariablesFlush();
      return "RESTART_ARMED_RECONCILE";
     }
   string observed;
   if(!MTTESTER::SetSettings2(ini,1) || !MTTESTER::GetSettingsManaged(observed)
      || !GoatStudioINIEqual(ini,observed,error)) return "SETTINGS_NOT_VERIFIED";
   bool worker_local,worker_remote,worker_cloud;
   if(!GoatStudioReadWorkerPolicy(worker_local,worker_remote,worker_cloud)
      || !worker_local || worker_remote || worker_cloud) return "WORKER_POLICY_NOT_VERIFIED";
   if(IsStopped() || expires<=(long)TimeGMT() || !MQLInfoInteger(MQL_DLLS_ALLOWED)
      || GoatStudioTesterState()!="idle" || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO
      || GlobalVariableGet("BatchOnGoing")!=0 || GlobalVariableGet("GOAT_BatchRestartPending")!=0
      || !TerminalInfoInteger(TERMINAL_CONNECTED) || login!=(string)AccountInfoInteger(ACCOUNT_LOGIN)
      || server!=AccountInfoString(ACCOUNT_SERVER)) return "RUNTIME_CHANGED_BEFORE_START";
   // Recheck native controls after settings work while still holding the gate.
   for(int i=0;i<ArraySize(paths);i++)
     {
      string hash;if(!GOATJsonGetString(body,t,0,fields[i],hash) || !GoatStudioCommonDigest(paths[i],hash)) return "NATIVE_CONTROL_DRIFT";
     }
   // Persist intent before arming: a failed receipt must not leave a batch armed.
   if(IsStopped() || expires<=(long)TimeGMT()) return "REQUEST_EXPIRED_BEFORE_START";
   if(!GoatStudioWriteUtf8("GOATStudio\\native-gate\\start-intent-"+id+".json",
       "{\"request_sha256\":"+GoatStudioQuote(request_hash)+"}")) return "START_INTENT_WRITE_FAILED";
   if(GlobalVariableSet("BatchOnGoing",1.0)==0) return "ARM_FAILED";
   GlobalVariablesFlush();
   // Check=false avoids helper retries/UI heuristics; one native start message.
   MTTESTER::ClickStart(false,1);
   return "START_SIGNAL_SENT_RECONCILE";
  }

void GoatStudioDispatch(void)
  {
   string root="GOATStudio\\native-gate";
   if(!g_StudioBound || !FileIsExist(root+"\\permit.json")) return;
   int gate=FileOpen(root+"\\launch.lock",FILE_READ|FILE_WRITE|FILE_BIN);
   if(gate==INVALID_HANDLE) return;
   string permit,body,expected,hash,id;SGOATJsonToken t[];
   if(GoatStudioReadUtf8(root+"\\permit.json",permit) && GOATJsonParse(permit,t)
      && GOATJsonGetString(permit,t,0,"request_sha256",expected)
      && GoatStudioReadUtf8(root+"\\request.json",body) && GOATSha256Utf8(body,hash) && hash==expected
      && GOATJsonParse(body,t) && GOATJsonGetString(body,t,0,"request_id",id) && GoatStudioId(id))
     {
      string receipt=root+"\\result-"+id+".json";
      if(!FileIsExist(receipt))
        {
         string outcome=GoatStudioExecuteRequest(body,hash);
         GoatStudioWriteUtf8(receipt,"{\"request_id\":"+GoatStudioQuote(id)+",\"request_sha256\":"+GoatStudioQuote(hash)
            +",\"status\":"+GoatStudioQuote(outcome)+",\"observed_utc\":"+GoatStudioQuote(TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS))+"}");
        }
     }
   FileClose(gate);
  }
#endif
