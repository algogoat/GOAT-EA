// Bounded demo portfolio setup. Registration binds every source byte and policy.
// No trade-enable, order, close-position or credential commands.
string GoatPortfolioExpectedHashes[];
bool GoatPortfolioRead(const string path,string &body)
{
   body="";
   int h=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h);
   if(size==0 || size>131072){FileClose(h);return false;}
   uchar data[]; uint got=FileReadArray(h,data,0,(uint)size); FileClose(h);
   if(got!=size) return false;
   body=CharArrayToString(data,0,(int)size,CP_UTF8); return true;
}

bool GoatPortfolioFileMatches(const string path,const string expected)
{
   string common=TerminalInfoString(TERMINAL_COMMONDATA_PATH)+"\\Files\\";
   if(StringFind(path,common)!=0 || StringFind(path,"..")>=0 || StringFind(path,":",3)>=0
      || StringFind(path,"/")>=0 || !GOATIsLowerHex(expected,64)) return false;
   string relative=GoatDashboardCommonSetPath(path);
   if(relative=="") return false;
   int h=FileOpen(relative,FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h); uchar data[],key[],digest[];
   if(size==0 || size>2000000){FileClose(h);return false;}
   uint got=FileReadArray(h,data,0,(uint)size);FileClose(h);
   if(got!=size || CryptEncode(CRYPT_HASH_SHA256,data,key,digest)!=32) return false;
   string hex="";for(int i=0;i<32;i++) hex+=StringFormat("%02x",digest[i]);
   return hex==expected;
}

bool GoatPortfolioRowLinked(const int row)
{
   if(row<0 || row>=ArraySize(DashboardDialog.g_sets)) return false;
   long cid=DashboardDialog.g_sets[row].cid,magic=DashboardDialog.g_sets[row].magic,found=0;
   if(cid<=0 || magic<=0 || ChartSymbol(cid)!=DashboardDialog.g_sets[row].sym
      || !GoatFindMagicByCid(DashboardDialog.g_sets[row].sym,cid,found) || found!=magic) return false;
   for(int i=0;i<ArraySize(DashboardDialog.g_sets);i++)
      if(i!=row && (DashboardDialog.g_sets[i].cid==cid || DashboardDialog.g_sets[i].magic==magic)) return false;
   double hi=0,lo=0;
   if(!GlobalVariableGet(GoatChildGVName(magic,DashboardDialog.g_sets[row].sym,"SETUP_CID_HI"),hi)
      || !GlobalVariableGet(GoatChildGVName(magic,DashboardDialog.g_sets[row].sym,"SETUP_CID_LO"),lo)
      || (long)hi!=cid/1000000000 || (long)lo!=cid%1000000000) return false;
   double hb=0;
   if(!GlobalVariableGet(GoatChildGVName(magic,DashboardDialog.g_sets[row].sym,"SETUP_UTC"),hb)) return false;
   return(hb>0 && TimeGMT()>=(datetime)hb && TimeGMT()-(datetime)hb<=15);
}

string GoatPortfolioSnapshot(const string id,const string action,const string hash,const string result)
{
   string rows="[";
   for(int i=0;i<ArraySize(DashboardDialog.g_sets);i++)
   {
      if(i>0) rows+=",";
      bool linked=GoatPortfolioRowLinked(i);
      long magic=DashboardDialog.g_sets[i].magic;
      string sym=DashboardDialog.g_sets[i].sym;
      if(linked) DashboardDialog.ReadChildSnapshotIntoRow(i);
      rows+="{\"index\":"+IntegerToString(i)+",\"symbol\":"+GoatSetupQuote(sym)
         +",\"chartId\":"+IntegerToString(DashboardDialog.g_sets[i].cid)
         +",\"magic\":"+IntegerToString(magic)+",\"linkedFresh\":"+(linked ? "true" : "false")
         +",\"exposureMode\":"+IntegerToString(DashboardDialog.g_sets[i].exposure_policy_mode)
         +",\"ackId\":"+IntegerToString(DashboardDialog.g_sets[i].last_ack_id)
         +",\"ackStatus\":"+IntegerToString(DashboardDialog.g_sets[i].last_ack_status)
         +",\"settingsMatch\":"+(action=="audit" && result=="observed" && linked && i<ArraySize(GoatPortfolioExpectedHashes) && GoatPortfolioChildSettingsMatch(i,GoatPortfolioExpectedHashes[i]) ? "true" : "false");
      string fields[]={"AI_MODE","AI_PROTOCOL","AI_THRESHOLD","AI_SCOPE","AI_VERIFIED","AI_AVAILABLE","AI_AT","EA_TRADE_ALLOWED"};
      for(int f=0;f<ArraySize(fields);f++)
      {
         double value=0; bool present=linked && GlobalVariableGet(GoatChildGVName(magic,sym,fields[f]),value);
         rows+=",\""+fields[f]+"\":"+(present ? IntegerToString((long)value) : "null");
      }
      rows+="}";
   }
   rows+="]";
   return "{\"schema\":1,\"id\":"+GoatSetupQuote(id)+",\"action\":"+GoatSetupQuote(action)
      +",\"registrationSha256\":"+GoatSetupQuote(hash)+",\"result\":"+GoatSetupQuote(result)
      +",\"account\":"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))
      +",\"server\":"+GoatSetupQuote(AccountInfoString(ACCOUNT_SERVER))
      +",\"directory\":"+GoatSetupQuote(TerminalInfoString(TERMINAL_DATA_PATH))
      +",\"buildId\":"+GoatSetupQuote(GOAT_BUILD_ID)+",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())
      +",\"brokerTime\":"+IntegerToString((long)TimeCurrent())
      +",\"connected\":"+(TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false")
      +",\"tradingAllowed\":"+(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "true" : "false")
      +",\"positions\":"+IntegerToString(PositionsTotal())+",\"orders\":"+IntegerToString(OrdersTotal())
      +",\"aiMode\":"+IntegerToString(DashboardDialog.m_ai_launch_mode)
      +",\"aiThreshold\":"+IntegerToString(DashboardDialog.m_ai_launch_threshold)
      +",\"aiProtocol\":"+IntegerToString(DashboardDialog.m_ai_launch_protocol)
      +",\"commandId\":"+IntegerToString(DashboardDialog.m_portfolio_command_id)
      +",\"commandPending\":"+(DashboardDialog.m_portfolio_command_pending ? "true" : "false")
      +",\"rows\":"+rows+"}";
}

void GoatPortfolioSetupPoll(void)
{
   if(Mode_Operation!=Operation_Dash || MQLInfoInteger(MQL_TESTER) || GOATDeviceActivationOnly()
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO) return;
   string root="GOAT\\AgentPortfolio\\"+GoatTerminalToken()+"\\";
   string registration="",request="",hash="";
   if(!GoatPortfolioRead(root+"registration.json",registration) || !GOATSha256Utf8(registration,hash)) return;
   SGOATJsonToken reg[]; long schema=0,account=0,expires=0,ai=0,threshold=0,protocol=0,exposure=0;
   string server="",directory="",build="";
   string reg_fields[]={"schema","account","server","directory","buildId","expiresAtUtc","aiMode","aiThreshold","aiProtocol","exposureMode","members"};
   if(!GOATJsonParse(registration,reg,4096,131072) || !GOATJsonExactFields(registration,reg,0,reg_fields)
      || !GOATJsonGetInteger(registration,reg,0,"schema",schema) || schema!=1
      || !GOATJsonGetInteger(registration,reg,0,"account",account) || account!=AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetString(registration,reg,0,"server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(registration,reg,0,"directory",directory) || !GoatSetupDirectoryMatches(directory)
      || !GOATJsonGetString(registration,reg,0,"buildId",build) || build!=GOAT_BUILD_ID
      || !GOATJsonGetInteger(registration,reg,0,"expiresAtUtc",expires) || expires<(long)TimeGMT() || expires>(long)TimeGMT()+14400
      || !GOATJsonGetInteger(registration,reg,0,"aiMode",ai) || (ai!=0 && ai!=2)
      || !GOATJsonGetInteger(registration,reg,0,"aiThreshold",threshold) || threshold<1 || threshold>100
      || !GOATJsonGetInteger(registration,reg,0,"aiProtocol",protocol) || protocol!=2
      || !GOATJsonGetInteger(registration,reg,0,"exposureMode",exposure) || (exposure!=0 && exposure!=1)) return;
   int owner=FileOpen(root+"owner.lock",FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(owner==INVALID_HANDLE) return;
   if(!GoatSetupRead(root+"request.json",request)){FileClose(owner);return;}
   SGOATJsonToken req[]; string id="",action="",expected="";
   string req_fields[]={"schema","id","action","registrationSha256","expiresAtUtc"};
   long request_expires=0;
   if(!GOATJsonParse(request,req) || !GOATJsonExactFields(request,req,0,req_fields)
      || !GOATJsonGetInteger(request,req,0,"schema",schema) || schema!=1
      || !GOATJsonGetString(request,req,0,"id",id) || !GOATIsLowerHex(id,32)
      || !GOATJsonGetString(request,req,0,"action",action)
      || (action!="status" && action!="audit" && action!="configure" && action!="deploy_next" && action!="apply_policy")
      || !GOATJsonGetString(request,req,0,"registrationSha256",expected) || expected!=hash
      || !GOATJsonGetInteger(request,req,0,"expiresAtUtc",request_expires)
      || request_expires<(long)TimeGMT() || request_expires>(long)TimeGMT()+120){FileClose(owner);return;}
   string receipt=root+id+".json";
   if(FileIsExist(receipt,FILE_COMMON)){FileClose(owner);return;}
   int members=GOATJsonFindField(registration,reg,0,"members"),count=0;
   ArrayResize(GoatPortfolioExpectedHashes,0);
   bool matched=(members>=0 && reg[members].type==GOAT_JSON_ARRAY);
   string member_fields[]={"index","path","symbol","sha256"};
   for(int t=members+1;matched && t<ArraySize(reg);t++)
   {
      if(reg[t].parent!=members) continue;
      string path="",symbol="",digest=""; long index=-1;
      matched=count<100 && count<ArraySize(DashboardDialog.g_sets)
         && GOATJsonExactFields(registration,reg,t,member_fields)
         && GOATJsonGetInteger(registration,reg,t,"index",index) && index==count
         && GOATJsonGetString(registration,reg,t,"path",path) && path==DashboardDialog.g_sets[count].path
         && GOATJsonGetString(registration,reg,t,"symbol",symbol) && symbol==DashboardDialog.g_sets[count].sym
         && GOATJsonGetString(registration,reg,t,"sha256",digest) && GoatPortfolioFileMatches(path,digest);
      if(matched){ArrayResize(GoatPortfolioExpectedHashes,count+1);GoatPortfolioExpectedHashes[count]=digest;}
      count++;
   }
   matched=matched && count>0 && count==ArraySize(DashboardDialog.g_sets);
   string result=(matched ? "observed" : "rejected_portfolio_mismatch");
   bool inert=TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && PositionsTotal()==0 && OrdersTotal()==0;
   if(matched && action!="status" && !inert) result="rejected_not_inert";
   if(matched && action!="status" && action!="audit" && inert)
   {
      // Retained intent prevents another issuance after interruption or timeout.
      if(!GoatSetupWrite(receipt,GoatPortfolioSnapshot(id,action,hash,"started"))){FileClose(owner);return;}
      if(action=="configure") result=(DashboardDialog.AgentConfigureAI((int)ai,(int)threshold,(int)protocol) ? "configured" : "configure_failed");
      else if(DashboardDialog.m_ai_launch_mode!=ai || DashboardDialog.m_ai_launch_threshold!=threshold || DashboardDialog.m_ai_launch_protocol!=protocol) result="rejected_ai_policy_mismatch";
      else if(action=="deploy_next")
      {
         int next=-1; bool partial=false;
         for(int i=0;i<count;i++)
         {
            if(DashboardDialog.g_sets[i].cid>0 || DashboardDialog.g_sets[i].magic>0)
            {if(!GoatPortfolioRowLinked(i)) partial=true;}
            else if(next<0) next=i;
         }
         if(partial) result="rejected_partial_deployment";
         else if(next<0) result="all_attached";
         else result=(DashboardDialog.AgentDeployRow(next) ? "child_attached" : "child_attach_failed");
      }
      else if(action=="apply_policy")
      {
         bool all=true;for(int i=0;i<count;i++) if(!GoatPortfolioRowLinked(i)) all=false;
         result=(all && DashboardDialog.AgentExposurePolicy((int)exposure) ? "policy_dispatched" : "policy_not_dispatched");
      }
   }
   GoatSetupWrite(receipt,GoatPortfolioSnapshot(id,action,hash,result));
   FileClose(owner);
}
