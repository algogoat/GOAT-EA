// Entry authorization is deliberately independent of position management.
// Included only by the current V1.48 entrypoint; historical binaries are unchanged.
bool g_GOATManager=false,g_GOATManagerReady=false,g_GOATWireHealthy=true;
bool g_GOATRecoveryDegraded=false,g_GOATManagementTimerPass=false;
long g_GOATManagerAccount=0;
string g_GOATManagerServer="",g_GOATAuthReason="AUTH_PENDING";
ulong g_GOATAuthUntil=0,g_GOATAuthNext=0;

bool GOATCanAddRisk()
  {
   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return true;
   if(!g_GOATManager || !g_GOATManagerReady || g_GOATRecoveryDegraded || g_GOATRecoveryWriteFailed || g_GOATManagementTimerPass) return false;
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=g_GOATManagerAccount || AccountInfoString(ACCOUNT_SERVER)!=g_GOATManagerServer) return false;
   if(g_GOATAuthUntil==0 || GetTickCount64()>=g_GOATAuthUntil) return false;
   if(Mode_Bias!=Bias_Disabled && Mode_Bias!=Bias_Display)
      return(g_GOATWireHealthy && GOATBiasWireV2.EntryFeedReady());
   return true;
  }

void GOATManagementStatus()
  {
   if(!g_GOATManager || g_GOATManagementTimerPass) return;
   string reason=g_GOATAuthReason;
   if(g_GOATRecoveryWriteFailed) reason="CHECKPOINT_WRITE_FAILED";
   else if(g_GOATRecoveryDegraded) reason="RECOVERY_REVIEW_REQUIRED";
   else if(g_GOATAuthUntil>0 && GetTickCount64()>=g_GOATAuthUntil) reason="AUTH_REFRESH_OVERDUE";
   else if(g_GOATAuthUntil>0 && Mode_Bias!=Bias_Disabled && Mode_Bias!=Bias_Display &&
           (!g_GOATWireHealthy || !GOATBiasWireV2.EntryFeedReady())) reason="AI_UNAVAILABLE_OR_STALE";
   string state=GOATCanAddRisk() ? "ENTRY AUTHORIZED" : "MANAGEMENT ONLY / "+reason;
   static string previous="";
   if(state!=previous) {Print("GOAT ",state,"; existing positions remain managed.");previous=state;}
   // Comment occupies its own chart surface; normal panel updates cannot erase it.
   Comment("GOAT ",state,"\nExisting positions: managed | New exposure: ",GOATCanAddRisk() ? "eligible under strategy rules" : "blocked");
  }

void GOATManagementAuthPoll()
  {
   if(!g_GOATManager || !g_GOATManagerReady) return;
   ulong now=GetTickCount64();
   if(now<g_GOATAuthNext) return;
   g_GOATAuthNext=now+30000+(ulong)(ChartID()%10000);
   // A failed refresh immediately invalidates the old grant. No restart-time grace.
   g_GOATAuthUntil=0;
   g_GOATAuthReason="AUTH_UNAVAILABLE";
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=g_GOATManagerAccount || AccountInfoString(ACCOUNT_SERVER)!=g_GOATManagerServer)
     {g_GOATAuthReason="ACCOUNT_CHANGED";return;}
   string headers="";
   if(!GOATBuildAuthenticatedRequestHeaders(headers)) {g_GOATAuthReason="CREDENTIAL_MISSING";return;}
   char body[],result[];
   string response_headers="";
   StringToCharArray("{\"id\":\""+(string)g_GOATManagerAccount+"\"}",body,0,WHOLE_ARRAY,CP_UTF8);
   ArrayResize(body,ArraySize(body)-1);
   int status=WebRequest("POST",URL_API+"/api/ea/check",headers,1000,body,result,response_headers);
   headers="";
   string reply=CharArrayToString(result,0,-1,CP_UTF8);
   StringTrimLeft(reply);StringTrimRight(reply);
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=g_GOATManagerAccount || AccountInfoString(ACCOUNT_SERVER)!=g_GOATManagerServer)
     {g_GOATAuthReason="ACCOUNT_CHANGED";return;}
   if(status==200 && reply==(string)g_GOATManagerAccount+" - yes")
     {g_GOATAuthUntil=GetTickCount64()+45000;g_GOATAuthReason="AUTHORIZED";}
   else if(status==401) g_GOATAuthReason="AUTH_REJECTED";
   else if(status==403 || status==409 || (status==200 && reply=="no")) g_GOATAuthReason="ENTITLEMENT_OR_BUILD_DENIED";
   else g_GOATAuthReason="AUTH_SERVICE_UNAVAILABLE";
  }
