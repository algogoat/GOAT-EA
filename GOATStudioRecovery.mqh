#ifndef GOAT_STUDIO_RECOVERY_MQH
#define GOAT_STUDIO_RECOVERY_MQH
#ifdef GOAT_ORPHAN_RECOVERY_V149
// This action is available only in the forward-version inert research monitor.
// Host review is trusted-local coordination, not an OS-user security boundary.
string g_StudioRecoveryInstance="";
string GoatStudioRecoveryInstance(void)
  {
   if(g_StudioRecoveryInstance=="")
      g_StudioRecoveryInstance=(string)TimeLocal()+"-"+(string)GetTickCount64()+"-"+(string)ChartID();
   return g_StudioRecoveryInstance;
  }

bool GoatStudioRecoveryLocalTree(const string root,int &count,const int depth=0)
  {
   if(depth>12) return false;
   string name;long search=FileFindFirst(root+"\\*",name);
   if(search==INVALID_HANDLE) return false; // Unknown/empty roots are not proof.
   bool ok=true;
   do
     {
      if(++count>50000) {ok=false;break;}
      string path=root+"\\"+name,lower=name;StringToLower(lower);ResetLastError();bool file=FileIsExist(path);
      if(!file && GetLastError()==ERR_FILE_IS_DIRECTORY)
        {
         // Empty inboxes are normal; only descend where entries exist.
         string child;long found=FileFindFirst(path+"\\*",child);
         if(found!=INVALID_HANDLE)
           {FileFindClose(found);if(!GoatStudioRecoveryLocalTree(path,count,depth+1)) {ok=false;break;}}
        }
      else if(!file) {ok=false;break;}
      else if(lower=="controller.json" && path!="GOATStudio\\native-gate\\controller.json") {ok=false;break;}
      else if((lower=="request.json" || lower=="permit.json") && root!="GOATStudio\\native-gate") {ok=false;break;}
      else if(lower=="pending.json" || lower=="seed-active.json") {ok=false;break;}
     }
   while(FileFindNext(search,name));
   FileFindClose(search);return ok;
  }

bool GoatStudioRecoveryCommonClear(void)
  {
   string name;long search=FileFindFirst("GOAT\\*",name,FILE_COMMON);
   if(search==INVALID_HANDLE) return false;
   int count=0;bool ok=true;
   do
     {
      if(++count>10000) {ok=false;break;}
      string lower=name;StringToLower(lower);
      if(StringFind(lower,"goat v")!=0) continue;
      string base="GOAT\\"+name;
      string controls[]={"active_optimization_run.ini","active_optimization_config.ini",
                         "active_optimization_launch.ini","agent-native-control-owner.json"};
      for(int i=0;i<ArraySize(controls);i++)
         if(FileIsExist(base+"\\"+controls[i],FILE_COMMON)) {ok=false;break;}
      if(!ok) break;
     }
   while(FileFindNext(search,name));
   FileFindClose(search);return ok;
  }

// Journal-only diagnostics: memory is private to this loaded EA instance.
// Error values are observations, not a fresh error attribution: never reset _LastError.
string g_StudioRecoveryDiagnosticKeys[16];
int g_StudioRecoveryDiagnosticCount=0;
void GoatStudioRecoveryDiagnostic(const string context,const string reason,const int before,const int after)
  {
   if(g_StudioRecoveryDiagnosticCount>=16) return;
   string key=context+"|"+reason+"|"+(string)before+"|"+(string)after;
   for(int i=0;i<g_StudioRecoveryDiagnosticCount;i++)
      if(g_StudioRecoveryDiagnosticKeys[i]==key) return;
   g_StudioRecoveryDiagnosticKeys[g_StudioRecoveryDiagnosticCount++]=key;
   PrintFormat("GOAT ORPHAN DIAGNOSTIC context=%s reason=%s query_error_before=%d query_error_after=%d diagnostic_only%s",
               context,reason,before,after,
               context=="CURRENT_MONITOR_OBSERVATION" ? " NO_ACTION current_state_not_original_rejection" : "");
  }

bool GoatStudioRecoveryRuntimeCheck(const bool ok,const string code,string &reason)
  {
   if(!ok) reason=code;
   return ok;
  }

// Same ordered, short-circuit read guards used by recovery and current observation.
// Capturing the first failure adds no permission, effect or alternate acceptance path.
bool GoatStudioRecoveryRuntime(const string login,const string server,const string instance,
                               string &reason,int &before,int &after)
  {
   reason="CURRENT_GUARD_PASS";before=0;after=0;
   long chart=ChartFirst();int charts=0;bool own=false;
   while(chart>=0)
     {
      string expert,script;
      if(++charts>1000) {reason="CHART_LIMIT";return false;}
      int query_before=GetLastError();
      if(!ChartGetString(chart,CHART_EXPERT_NAME,expert))
        {after=GetLastError();before=query_before;reason="EXPERT_QUERY_FAILED";return false;}
      query_before=GetLastError();
      if(!ChartGetString(chart,CHART_SCRIPT_NAME,script))
        {after=GetLastError();before=query_before;reason="SCRIPT_QUERY_FAILED";return false;}
      if(script!="") {reason="SCRIPT_PRESENT";return false;}
      if(chart==ChartID()) own=true;
      else if(expert!="") {reason="OTHER_EXPERT_PRESENT";return false;}
      chart=ChartNext(chart);
     }
   if(!own) {reason="OWN_CHART_ABSENT";return false;}
   return GoatStudioRecoveryRuntimeCheck(!IsStopped(),"EA_STOPPED",reason)
      && GoatStudioRecoveryRuntimeCheck(g_GoatStudioReadOnlyMonitor,"NOT_READ_ONLY_MONITOR",reason)
      && GoatStudioRecoveryRuntimeCheck(!MQLInfoInteger(MQL_TESTER),"IN_TESTER",reason)
      && GoatStudioRecoveryRuntimeCheck(MQLInfoInteger(MQL_DLLS_ALLOWED),"DLL_NOT_ALLOWED",reason)
      && GoatStudioRecoveryRuntimeCheck(GoatStudioTesterState()=="idle","TESTER_NOT_IDLE",reason)
      && GoatStudioRecoveryRuntimeCheck(TerminalInfoInteger(TERMINAL_CONNECTED),"TERMINAL_DISCONNECTED",reason)
      && GoatStudioRecoveryRuntimeCheck(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED),"ALGO_TRADING_ENABLED",reason)
      && GoatStudioRecoveryRuntimeCheck(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO,"NOT_DEMO",reason)
      && GoatStudioRecoveryRuntimeCheck(login==(string)AccountInfoInteger(ACCOUNT_LOGIN),"ACCOUNT_CHANGED",reason)
      && GoatStudioRecoveryRuntimeCheck(server==AccountInfoString(ACCOUNT_SERVER),"SERVER_CHANGED",reason)
      && GoatStudioRecoveryRuntimeCheck(instance==GoatStudioRecoveryInstance(),"MONITOR_CHANGED",reason)
      && GoatStudioRecoveryRuntimeCheck(GlobalVariableGet("BatchOnGoing")!=0,"BATCH_FLAG_ABSENT",reason)
      && GoatStudioRecoveryRuntimeCheck(GlobalVariableGet("TerminalRunning")==0,"TERMINAL_RUNNING",reason)
      && GoatStudioRecoveryRuntimeCheck(GlobalVariableGet("GOAT_BatchRestartPending")==0,"RESTART_PENDING",reason);
  }

bool GoatStudioRecoveryRuntime(const string login,const string server,const string instance)
  {
   string reason;int before,after;
   bool ok=GoatStudioRecoveryRuntime(login,server,instance,reason,before,after);
   if(!ok) GoatStudioRecoveryDiagnostic("RECOVERY_RUNTIME_REJECTED",reason,before,after);
   return ok;
  }

void GoatStudioRecoveryObserveCurrent(void)
  {
   if(g_StudioRecoveryDiagnosticCount>=16) return;
   string reason;int before,after;
   GoatStudioRecoveryRuntime((string)AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),
                             GoatStudioRecoveryInstance(),reason,before,after);
   GoatStudioRecoveryDiagnostic("CURRENT_MONITOR_OBSERVATION",reason,before,after);
  }

string GoatStudioRecoverOrphan(const string body,const string hash)
  {
   SGOATJsonToken t[],s[];string id,terminal,run,owner,data,installation,program,login,server,version,instance;
   string snapshot_hash,owner_hash,active_hash;long schema,protocol,revision,generation,expires;
   if(!GOATJsonParse(body,t) || !GOATJsonGetInteger(body,t,0,"schema_version",schema) || schema!=1
      || !GOATJsonGetInteger(body,t,0,"recovery_protocol",protocol) || protocol!=1
      || !GOATJsonGetString(body,t,0,"request_id",id) || !GoatStudioId(id)
      || !GOATJsonGetString(body,t,0,"terminal_id",terminal) || terminal!=g_StudioBridge.TerminalId()
      || !GOATJsonGetString(body,t,0,"run_id",run) || run!=g_StudioBridge.RunId()
      || !GOATJsonGetString(body,t,0,"owner",owner) || owner!="agent"
      || !GOATJsonGetInteger(body,t,0,"revision",revision) || !GOATJsonGetInteger(body,t,0,"generation",generation)
      || !GOATJsonGetInteger(body,t,0,"expires_utc",expires) || expires<=(long)TimeGMT() || expires>(long)TimeGMT()+60
      || !GOATJsonGetString(body,t,0,"ea_version",version) || version!=GOAT_VERSION_LABEL
      || !GOATJsonGetString(body,t,0,"monitor_instance",instance)
      || !GOATJsonGetString(body,t,0,"data_path",data) || data!=TerminalInfoString(TERMINAL_DATA_PATH)
      || !GOATJsonGetString(body,t,0,"installation_path",installation) || installation!=TerminalInfoString(TERMINAL_PATH)
      || !GOATJsonGetString(body,t,0,"program_path",program) || program!=MQLInfoString(MQL_PROGRAM_PATH)
      || !GOATJsonGetString(body,t,0,"account_login",login) || !GOATJsonGetString(body,t,0,"account_server",server)
      || !GOATJsonGetString(body,t,0,"snapshot_sha256",snapshot_hash)
      || !GOATJsonGetString(body,t,0,"owner_file_sha256",owner_hash)
      || !GOATJsonGetString(body,t,0,"active_sha256",active_hash)) return "ORPHAN_REVIEW_REJECTED";
   string consumed="GOATStudio\\native-gate\\consumed-"+id+".json";
   if(FileIsExist(consumed)) return "ORPHAN_CONSUMED_RECONCILE";
   if(!GoatStudioRecoveryRuntime(login,server,instance)) return "ORPHAN_RUNTIME_REJECTED";
   string snapshot,actual,local_owner,active;
   if(!g_StudioBridge.ReadSnapshot(snapshot) || !GOATSha256Utf8(snapshot,actual) || actual!=snapshot_hash
      || !GOATJsonParse(snapshot,s,16384,2000000)
      || !GoatStudioReadUtf8("GOATStudio\\native-gate\\controller.json",local_owner)
      || !GOATSha256Utf8(local_owner,actual) || actual!=owner_hash
      || !GoatStudioReadUtf8("GOATStudio\\active.json",active)
      || !GOATSha256Utf8(active,actual) || actual!=active_hash) return "ORPHAN_BINDING_CHANGED";
   int state=GOATJsonFindField(snapshot,s,0,"state");long current_revision,current_generation;string current_owner;
   if(!GOATJsonGetString(snapshot,s,state,"owner",current_owner) || current_owner!=owner
      || !GOATJsonGetInteger(snapshot,s,state,"revision",current_revision) || current_revision!=revision
      || !GOATJsonGetInteger(snapshot,s,state,"generation",current_generation) || current_generation!=generation)
      return "ORPHAN_CONTROL_CHANGED";
   int queue=GOATJsonFindField(snapshot,s,state,"queue");
   if(queue<0 || s[queue].type!=GOAT_JSON_ARRAY) return "ORPHAN_QUEUE_UNKNOWN";
   for(int i=0;i<ArraySize(s);i++)
     {
      if(s[i].parent!=queue) continue;
      string status;
      if(s[i].type!=GOAT_JSON_OBJECT || !GOATJsonGetString(snapshot,s,i,"status",status)
         || (status!="pending" && status!="completed" && status!="failed" && status!="cancelled"
             && status!="removed" && status!="superseded")) return "ORPHAN_QUEUE_UNRESOLVED";
     }
   int count=0;
   if(!GoatStudioRecoveryLocalTree("GOATStudio",count) || !GoatStudioRecoveryCommonClear()) return "ORPHAN_FOREIGN_CONTROL";
   // Claim BEFORE any effect. A crash after this point is never automatically retried.
   if(!GoatStudioWriteUtf8(consumed,body)) return "ORPHAN_CLAIM_FAILED";
   if(expires<=(long)TimeGMT() || !GoatStudioRecoveryRuntime(login,server,instance)
      || !GoatStudioRecoveryCommonClear()) return "ORPHAN_CHANGED_AFTER_CLAIM";
   // Sole permitted effect; no stop/start, cancellation, queue or authority write.
   if(!GlobalVariableDel("BatchOnGoing")) return "ORPHAN_CLEAR_FAILED";
   GlobalVariablesFlush();
   if(GlobalVariableCheck("BatchOnGoing")) return "ORPHAN_READBACK_FAILED";
   return "ORPHAN_RECOVERED";
  }
#endif
#endif
