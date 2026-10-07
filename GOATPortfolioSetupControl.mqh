// Bounded demo portfolio setup. Registration binds every source byte and policy.
// No trade-enable, order, close-position or credential commands. No chart is opened,
// closed or given a template: children reach charts only through a profile MT5 loads.
string GoatPortfolioExpectedHashes[];
// The registration's deploymentId (32 lowercase hex), or "" for a registration that binds none.
string GoatPortfolioDeployment="";

// ---- Live-before-adoption gate (beta.25, goatai#1885 6035859714) ----
// A profile-staged child carries "deploy=<deploymentId>" in Studio_MonitorRunPath, and MT5 starts it with
// expertmode=5, so it could trade the moment someone turns Algo Trading on, before the dashboard has adopted
// it and applied its exposure policy. Such a child opens nothing new (no sequence start, real or virtual, and
// no virtual-to-real promotion: every path through DashboardEntryAllowed) until the dashboard has written its
// <Key>_ID_<magic>_<symbol>_PDEPLOY marker for that deployment. The dashboard writes the marker only after it
// has seen the child acknowledge the exposure policy apply_policy dispatched. Adds to an existing sequence,
// closes, trailing and stops never pass through this gate. A child without the "deploy=" prefix (every
// normal SET, tester runs, the Exp terminals) returns true at the first line, exactly as before.
#define GOAT_GV_FIELD_POLICY_DEPLOYMENT "PDEPLOY"

// The marker value: the deployment id's first 13 hex digits (52 bits, exact in a GlobalVariable double).
long GoatDeployMarker(const string marker_id)
{
   if(StringLen(marker_id)<13) return -1;
   long marker_value=0;
   for(int marker_i=0;marker_i<13;marker_i++)
   {
      ushort marker_c=StringGetCharacter(marker_id,marker_i);
      int marker_digit=-1;
      if(marker_c>='0' && marker_c<='9') marker_digit=marker_c-'0';
      else if(marker_c>='a' && marker_c<='f') marker_digit=marker_c-'a'+10;
      if(marker_digit<0) return -1;
      marker_value=marker_value*16+marker_digit;
   }
   return marker_value;
}

// Child side, called first by DashboardEntryAllowed with the chart's own Studio_MonitorRunPath.
bool GoatStagedChildMayOpen(const string staged_run_path,const long staged_magic,const string staged_symbol)
{
   if(StringFind(staged_run_path,"deploy=")!=0) return true;
   string staged_id=StringSubstr(staged_run_path,7);
   double staged_marker=0;
   return GOATIsLowerHex(staged_id,32) && staged_magic>0
      && GlobalVariableGet(GoatChildGVName(staged_magic,staged_symbol,GOAT_GV_FIELD_POLICY_DEPLOYMENT),staged_marker)
      && (long)staged_marker==GoatDeployMarker(staged_id);
}
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

// ---- Profile-staged deploy (beta.25, goatai#1885 6033450916) ----
// MT5 loads every child chart from the staged deploy profile at start-up. The dashboard only
// adopts the children it finds. A child is adopted when its symbol and period equal the row's,
// it runs this EA, its CID record names a magic no other row holds, and its saved-template
// snapshot reproduces the row's frozen SET (the settingsMatch rule). The TSV cid is tried first
// (a profile that restores a saved chart keeps its id); otherwise every chart is fingerprinted
// once and adopted only on a one-to-one match. Adoption runs only on an inert demo terminal and
// never opens, closes or applies anything to a chart. A row still without a child once the
// start-up window has passed is child_not_started (chartId 0, magic 0 in every receipt).
#define GOAT_CHILD_START_WAIT_SECONDS 240
datetime GoatAdoptWindowStart=0;
string   GoatAdoptNoted[];

// The chart period a member needs, from the token after the comma in its SET name
// ("GOAT V1.49 EURUSD,M15_..."). Anything else is PERIOD_CURRENT, which no chart reports.
ENUM_TIMEFRAMES GoatAdoptSetPeriod(const string adopt_name)
{
   int adopt_comma=StringFind(adopt_name,",");
   if(adopt_comma<0) return PERIOD_CURRENT;
   string adopt_token="";
   for(int adopt_i=adopt_comma+1;adopt_i<StringLen(adopt_name);adopt_i++)
   {
      ushort adopt_c=StringGetCharacter(adopt_name,adopt_i);
      if(!((adopt_c>='A' && adopt_c<='Z') || (adopt_c>='0' && adopt_c<='9'))) break;
      adopt_token+=ShortToString(adopt_c);
   }
   if(adopt_token=="M1")  return PERIOD_M1;
   if(adopt_token=="M5")  return PERIOD_M5;
   if(adopt_token=="M15") return PERIOD_M15;
   if(adopt_token=="M30") return PERIOD_M30;
   if(adopt_token=="H1")  return PERIOD_H1;
   if(adopt_token=="H4")  return PERIOD_H4;
   if(adopt_token=="D1")  return PERIOD_D1;
   return PERIOD_CURRENT;
}

bool GoatAdoptInert(void)
{
   return(Mode_Operation==Operation_Dash && !MQLInfoInteger(MQL_TESTER)
          && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO
          && TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
          && PositionsTotal()==0 && OrdersTotal()==0);
}

// Deployment diagnostics, once per distinct event (no SET paths, account IDs or credentials).
void GoatAdoptNote(const string adopt_phase,const long adopt_target,const string adopt_detail)
{
   string adopt_key=adopt_phase+"|"+IntegerToString(adopt_target)+"|"+adopt_detail;
   int adopt_n=ArraySize(GoatAdoptNoted);
   for(int adopt_i=0;adopt_i<adopt_n;adopt_i++) if(GoatAdoptNoted[adopt_i]==adopt_key) return;
   if(adopt_n>=512) return;
   ArrayResize(GoatAdoptNoted,adopt_n+1); GoatAdoptNoted[adopt_n]=adopt_key;
   GoatDeploymentPhase(adopt_phase,adopt_target,adopt_detail);
}

// The cheap identity checks, before any template snapshot: the row's symbol and period, this EA,
// and a CID record naming a magic that no other row holds on a chart no other row claims.
bool GoatAdoptChartFits(const int adopt_row,const long adopt_chart,long &adopt_magic)
{
   adopt_magic=0;
   int adopt_rows=ArraySize(DashboardDialog.g_sets);
   if(adopt_row<0 || adopt_row>=adopt_rows || adopt_chart<=0 || adopt_chart==ChartID()) return false;
   string adopt_sym=DashboardDialog.g_sets[adopt_row].sym;
   ENUM_TIMEFRAMES adopt_period=GoatAdoptSetPeriod(DashboardDialog.g_sets[adopt_row].name);
   if(adopt_period==PERIOD_CURRENT || ChartSymbol(adopt_chart)!=adopt_sym || ChartPeriod(adopt_chart)!=adopt_period
      || ChartGetString(adopt_chart,CHART_EXPERT_NAME)!=DashboardDialog.EA_Name_) return false;
   long adopt_found=0;
   if(!GoatFindMagicByCid(adopt_sym,adopt_chart,adopt_found) || adopt_found<=0) return false;
   for(int adopt_other=0;adopt_other<adopt_rows;adopt_other++)
      if(adopt_other!=adopt_row && (DashboardDialog.g_sets[adopt_other].cid==adopt_chart
         || DashboardDialog.g_sets[adopt_other].magic==adopt_found)) return false;
   adopt_magic=adopt_found;
   return true;
}

// One adoption pass over the rows that have no child yet. Returns the number of rows linked.
// adopt_deployment is the registration's deploymentId: only a child whose Studio_MonitorRunPath holds
// "deploy=<that id>" was started by this deployment, so a hand-added chart with the same SET never links.
int GoatPortfolioAdoptChildren(const string &adopt_hashes[],const string adopt_deployment)
{
   int adopt_rows=ArraySize(DashboardDialog.g_sets),adopt_count=0;
   if(!GoatAdoptInert() || adopt_rows<1 || ArraySize(adopt_hashes)!=adopt_rows) return 0;
   if(!GOATIsLowerHex(adopt_deployment,32))
   {
      GoatAdoptNote("child_deploy_unbound",0,"registration has no deploymentId");
      return 0;
   }
   if(GoatAdoptWindowStart==0) GoatAdoptWindowStart=TimeGMT();
   // Each pending row's frozen SET, read once per pass and only at its registered sha256.
   string adopt_sources[];
   ArrayResize(adopt_sources,adopt_rows);
   for(int adopt_row=0;adopt_row<adopt_rows;adopt_row++)
   {
      string adopt_text="";
      adopt_sources[adopt_row]="";
      if(DashboardDialog.g_sets[adopt_row].magic<=0
         && GoatChildSetSource(DashboardDialog.g_sets[adopt_row].path,adopt_hashes[adopt_row],adopt_text))
         adopt_sources[adopt_row]=adopt_text;
   }
   // 1) cid first: the TSV cid is the chart id whenever a profile restores a saved chart.
   for(int adopt_row=0;adopt_row<adopt_rows;adopt_row++)
   {
      long adopt_hint=DashboardDialog.g_sets[adopt_row].cid,adopt_magic=0;
      string adopt_snapshot="";
      if(DashboardDialog.g_sets[adopt_row].magic>0 || adopt_hint<=0 || adopt_sources[adopt_row]=="") continue;
      if(GoatAdoptChartFits(adopt_row,adopt_hint,adopt_magic)
         && GoatChildChartSnapshot(adopt_hint,adopt_snapshot)
         && GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_snapshot,adopt_deployment)
         && DashboardDialog.AdoptChild(adopt_row,adopt_hint,adopt_magic)) adopt_count++;
   }
   // 2) Fallback: walk every chart. A chart is fingerprinted once, then compared with each row it fits.
   long adopt_pair_chart[],adopt_pair_magic[];
   int  adopt_pair_row[];
   int  adopt_walked=0;
   for(long adopt_chart=ChartFirst();adopt_chart>=0 && adopt_walked<1000;adopt_chart=ChartNext(adopt_chart))
   {
      adopt_walked++;
      string adopt_shot="";
      bool adopt_taken=false,adopt_matched=false;
      for(int adopt_row=0;adopt_row<adopt_rows;adopt_row++)
      {
         long adopt_found=0;
         if(DashboardDialog.g_sets[adopt_row].magic>0 || adopt_sources[adopt_row]==""
            || !GoatAdoptChartFits(adopt_row,adopt_chart,adopt_found)) continue;
         if(!adopt_taken)
         {
            adopt_taken=true;
            if(!GoatChildChartSnapshot(adopt_chart,adopt_shot)) adopt_shot="";
         }
         if(adopt_shot=="" || !GoatChildSnapshotMatchesSet(adopt_sources[adopt_row],adopt_shot,adopt_deployment)) continue;
         int adopt_n=ArraySize(adopt_pair_chart);
         ArrayResize(adopt_pair_chart,adopt_n+1); ArrayResize(adopt_pair_magic,adopt_n+1); ArrayResize(adopt_pair_row,adopt_n+1);
         adopt_pair_chart[adopt_n]=adopt_chart; adopt_pair_magic[adopt_n]=adopt_found; adopt_pair_row[adopt_n]=adopt_row;
         adopt_matched=true;
      }
      // A chart running this EA that no row claims and no pending row matches (other inputs, symbol or
      // period, or a look-alike of a linked member) is never adopted, only recorded.
      if(!adopt_matched && adopt_chart!=ChartID() && ChartGetString(adopt_chart,CHART_EXPERT_NAME)==DashboardDialog.EA_Name_)
      {
         bool adopt_claimed=false;
         for(int adopt_r=0;adopt_r<adopt_rows;adopt_r++)
            if(DashboardDialog.g_sets[adopt_r].cid==adopt_chart && DashboardDialog.g_sets[adopt_r].magic>0) adopt_claimed=true;
         if(!adopt_claimed) GoatAdoptNote("child_unmatched",adopt_chart,ChartSymbol(adopt_chart));
      }
   }
   // 3) Only a one-to-one match links. A row with two children, or a chart fitting two rows, stays pending.
   int adopt_pairs=ArraySize(adopt_pair_chart);
   for(int adopt_p=0;adopt_p<adopt_pairs;adopt_p++)
   {
      int adopt_same_row=0,adopt_same_chart=0;
      for(int adopt_q=0;adopt_q<adopt_pairs;adopt_q++)
      {
         if(adopt_pair_row[adopt_q]==adopt_pair_row[adopt_p]) adopt_same_row++;
         if(adopt_pair_chart[adopt_q]==adopt_pair_chart[adopt_p]) adopt_same_chart++;
      }
      int adopt_target=adopt_pair_row[adopt_p];
      if(adopt_same_row==1 && adopt_same_chart==1)
      {
         if(DashboardDialog.AdoptChild(adopt_target,adopt_pair_chart[adopt_p],adopt_pair_magic[adopt_p])) adopt_count++;
      }
      else GoatAdoptNote("child_identity_ambiguous",adopt_pair_chart[adopt_p],DashboardDialog.g_sets[adopt_target].sym+" row="+IntegerToString(adopt_target));
   }
   // 4) The dashboard names what is still missing. Past the start-up window it is child_not_started.
   bool adopt_late=(TimeGMT()-GoatAdoptWindowStart>GOAT_CHILD_START_WAIT_SECONDS);
   for(int adopt_row=0;adopt_row<adopt_rows;adopt_row++)
   {
      if(DashboardDialog.g_sets[adopt_row].magic>0) continue;
      DashboardDialog.g_sets[adopt_row].status=(adopt_late ? "Not started" : "Pending");
      if(adopt_late) GoatAdoptNote("child_not_started",0,DashboardDialog.g_sets[adopt_row].sym+" row="+IntegerToString(adopt_row));
   }
   return adopt_count;
}

// Dashboard side, every poll with a registration that binds a deployment: mark each linked child whose
// acknowledgement of the dispatched exposure policy the dashboard has read. Runs before the request, so the
// audit that follows the controller's acknowledgement poll always sees the markers.
void GoatPortfolioMarkPolicyApplied(const string marker_deployment,const long marker_exposure)
{
   if(!GOATIsLowerHex(marker_deployment,32) || DashboardDialog.m_portfolio_command_id<=0
      || DashboardDialog.m_portfolio_command_type!=GOAT_DASH_CMD_EXPOSURE_POLICY) return;
   long marker_value=GoatDeployMarker(marker_deployment);
   for(int marker_row=0;marker_row<ArraySize(DashboardDialog.g_sets);marker_row++)
   {
      long marker_magic=DashboardDialog.g_sets[marker_row].magic;
      if(marker_magic<=0) continue;
      string marker_name=GoatChildGVName(marker_magic,DashboardDialog.g_sets[marker_row].sym,GOAT_GV_FIELD_POLICY_DEPLOYMENT);
      double marker_have=0;
      if(GlobalVariableGet(marker_name,marker_have) && (long)marker_have==marker_value) continue;
      if(!GoatPortfolioRowLinked(marker_row)) continue;
      DashboardDialog.ReadChildSnapshotIntoRow(marker_row);
      if(DashboardDialog.g_sets[marker_row].last_ack_id!=DashboardDialog.m_portfolio_command_id
         || DashboardDialog.g_sets[marker_row].last_ack_status!=GOAT_DASH_ACK_APPLIED
         || DashboardDialog.g_sets[marker_row].exposure_policy_mode!=marker_exposure) continue;
      GlobalVariableSet(marker_name,(double)marker_value);
      GlobalVariablesFlush();
      GoatAdoptNote("child_policy_marked",DashboardDialog.g_sets[marker_row].cid,DashboardDialog.g_sets[marker_row].sym);
   }
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
         +",\"chartId\":"+IntegerToString(magic>0 ? DashboardDialog.g_sets[i].cid : (long)0)
         +",\"magic\":"+IntegerToString(magic>0 ? magic : (long)0)+",\"linkedFresh\":"+(linked ? "true" : "false")
         +",\"exposureMode\":"+IntegerToString(DashboardDialog.g_sets[i].exposure_policy_mode)
         +",\"ackId\":"+IntegerToString(DashboardDialog.g_sets[i].last_ack_id)
         +",\"ackStatus\":"+IntegerToString(DashboardDialog.g_sets[i].last_ack_status)
         +",\"settingsMatch\":"+(action=="audit" && result=="observed" && linked && i<ArraySize(GoatPortfolioExpectedHashes) && GoatPortfolioChildSettingsMatch(i,GoatPortfolioExpectedHashes[i],GoatPortfolioDeployment) ? "true" : "false");
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
   // A profile-staged deploy also binds its deploymentId (contract section 3); older registrations bind none.
   string reg_bound_fields[]={"schema","account","server","directory","buildId","expiresAtUtc","aiMode","aiThreshold","aiProtocol","exposureMode","members","deploymentId"};
   string reg_deployment="";
   GoatPortfolioDeployment="";
   bool reg_parsed=GOATJsonParse(registration,reg,4096,131072);
   bool reg_bound=reg_parsed && GOATJsonExactFields(registration,reg,0,reg_bound_fields)
      && GOATJsonGetString(registration,reg,0,"deploymentId",reg_deployment) && GOATIsLowerHex(reg_deployment,32);
   if(!reg_parsed || (!reg_bound && !GOATJsonExactFields(registration,reg,0,reg_fields))
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
   if(reg_bound) GoatPortfolioDeployment=reg_deployment;
   GoatPortfolioMarkPolicyApplied(GoatPortfolioDeployment,exposure);
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
      || (action!="status" && action!="audit" && action!="configure" && action!="link_children"
          && action!="deploy_next" && action!="apply_policy")
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
   // deploy_next attached children with a dashboard-issued template, which MT5 accepts and never
   // performs (goatai#1885). It is retired: the request gets this refusal and changes nothing.
   if(matched && action=="deploy_next") result="rejected_deploy_next_retired";
   else if(matched && action!="status" && !inert) result="rejected_not_inert";
   // link_children is mutation-class like apply_policy: controller/contracts/profile-deploy.md section 3
   // (the contract lands with the controller half, algogoat/GOAT-EA#193).
   if(matched && inert && (action=="configure" || action=="link_children" || action=="apply_policy"))
   {
      // Retained intent prevents another issuance after interruption or timeout.
      if(!GoatSetupWrite(receipt,GoatPortfolioSnapshot(id,action,hash,"started"))){FileClose(owner);return;}
      if(action=="configure") result=(DashboardDialog.AgentConfigureAI((int)ai,(int)threshold,(int)protocol) ? "configured" : "configure_failed");
      else if(DashboardDialog.m_ai_launch_mode!=ai || DashboardDialog.m_ai_launch_threshold!=threshold || DashboardDialog.m_ai_launch_protocol!=protocol) result="rejected_ai_policy_mismatch";
      else if(action=="link_children")
      {
         // One adoption pass, then the normal snapshot. Never children_linked while any row is unlinked.
         GoatPortfolioAdoptChildren(GoatPortfolioExpectedHashes,GoatPortfolioDeployment);
         bool all=true;for(int i=0;i<count;i++) if(!GoatPortfolioRowLinked(i)) all=false;
         result=(all ? "children_linked" : "children_pending");
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
