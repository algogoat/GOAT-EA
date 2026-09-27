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

bool GoatStudioRecoveryRuntime(const string login,const string server,const string instance)
  {
   long chart=ChartFirst();int charts=0;bool own=false;
   while(chart>=0)
     {
      string expert,script;
      if(++charts>1000 || !ChartGetString(chart,CHART_EXPERT_NAME,expert)
         || !ChartGetString(chart,CHART_SCRIPT_NAME,script) || script!="") return false;
      if(chart==ChartID()) own=true;
      else if(expert!="") return false; // Another EA may own legacy continuation.
      chart=ChartNext(chart);
     }
   if(!own) return false;
   return !IsStopped() && g_GoatStudioReadOnlyMonitor && !MQLInfoInteger(MQL_TESTER)
      && MQLInfoInteger(MQL_DLLS_ALLOWED) && GoatStudioTesterState()=="idle"
      && TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO
      && login==(string)AccountInfoInteger(ACCOUNT_LOGIN) && server==AccountInfoString(ACCOUNT_SERVER)
      && instance==GoatStudioRecoveryInstance() && GlobalVariableGet("BatchOnGoing")!=0
      && GlobalVariableGet("TerminalRunning")==0 && GlobalVariableGet("GOAT_BatchRestartPending")==0;
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
