//+------------------------------------------------------------------+
//| Secure, one-file GOAT EA device activation                       |
//| The EA remains inert until an entitled portal user signs in and  |
//| confirms the MT5 account requested by this chart. The installed  |
//| user credential works only for linked, entitled MT5 accounts.    |
//+------------------------------------------------------------------+

enum ENUM_GOAT_DEVICE_ACTIVATION_STATE
  {
   GOAT_DEVICE_ACTIVATION_INACTIVE=0,
   GOAT_DEVICE_ACTIVATION_STARTING=1,
   GOAT_DEVICE_ACTIVATION_PENDING=2,
   GOAT_DEVICE_ACTIVATION_APPROVED=3,
   GOAT_DEVICE_ACTIVATION_BLOCKED=4
  };

ENUM_GOAT_DEVICE_ACTIVATION_STATE g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_INACTIVE;
string g_GOATDeviceActivationId="";
string g_GOATDeviceActivationCandidate="";
// Public short-lived challenge only; private credential candidate is never exported.
string g_GOATDeviceActivationUserCode="";
string g_GOATDeviceActivationServer="";
string g_GOATDeviceActivationAccountId="";
string g_GOATDeviceActivationBuildId="";
long   g_GOATDeviceActivationExpiresAtMs=0;
ulong  g_GOATDeviceActivationNextAttemptTick=0;
int    g_GOATDeviceActivationPollSeconds=5;
bool   g_GOATDeviceActivationReloadRequested=false;
bool   g_GOATDeviceActivationReplaceCredential=false;

// Status is operational metadata only: never tokens, connection codes or bodies.
void GOATDeviceActivationStatus(const string reason,const int http_status,const int native_error,const int retry_seconds)
  {
   FolderCreate(Key,FILE_COMMON);
   string path=Key+"\\activation-status-"+GoatTerminalToken()+".json";
   string temporary=path+"."+IntegerToString(ChartID())+"."+IntegerToString((long)GetTickCount64())+".pending";
   int h=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   string record="{\"accountId\":\""+g_GOATDeviceActivationAccountId+"\",\"buildId\":\""+g_GOATDeviceActivationBuildId+"\",\"reason\":\""+reason+"\",\"httpStatus\":"+IntegerToString(http_status)+",\"nativeError\":"+IntegerToString(native_error)+",\"retrySeconds\":"+IntegerToString(retry_seconds)+",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())+"}";
   uint written=FileWriteString(h,record);
   FileFlush(h);FileClose(h);
   if((int)written!=StringLen(record) || !FileMove(temporary,FILE_COMMON,path,FILE_COMMON|FILE_REWRITE))
      FileDelete(temporary,FILE_COMMON);
  }

int GOATDeviceActivationRetrySeconds(const int status)
  {
   if(status==429) return 900;
   if(status>=400 && status<500 && status!=408) return 0;
   return 60;
  }

void GOATDeviceActivationFailure(const int status,const int native_error,const bool starting=true)
  {
   int delay=GOATDeviceActivationRetrySeconds(status);
   g_GOATDeviceActivationNextAttemptTick=GetTickCount64()+(ulong)delay*1000;
   string reason=(status==409 ? (starting ? "build_not_admitted" : "activation_not_pending") : (status==429 ? "rate_limited" : (status==-1 && native_error==4014 ? "webrequest_permission_required" : (status<0 ? "network_error" : "service_error"))));
   if(delay==0)
     {
      g_GOATDeviceActivationUserCode="";
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_BLOCKED;
     }
   GOATDeviceActivationStatus(reason,status,native_error,delay);
   if(reason=="webrequest_permission_required") GOATDeviceActivationShowNetworkHelp();
   else if(status==409 && starting) GOATDeviceActivationShowRetry("This GOAT build is not approved. Install the latest GOAT.");
   else if(status==429) GOATDeviceActivationShowRetry("Too many sign-in attempts. GOAT retries in 15 minutes.");
   else if(delay==0) GOATDeviceActivationShowRetry("GOAT refused this sign-in (HTTP "+IntegerToString(status)+"). Contact GOAT support.");
   else GOATDeviceActivationShowRetry((status<0 ? "Can't reach goatedge.ai" : "GOAT service error (HTTP "+IntegerToString(status)+")")+". Retrying in 60 s.");
  }

// LC36 local pairing read: the connection code MT5 is already showing, shared with GOAT on
// this PC so the desktop and its agent read it without a screenshot. It is the short-lived
// public challenge only (never the credential candidate), on demo accounts only, in one file
// per terminal data folder in this Windows user's Common Files. It is withdrawn as soon as the
// code is cleared, expires, is approved or the chart closes, and is never printed or logged.
bool g_GOATDeviceActivationCodeShared=false;
string GOATDeviceActivationCodePath(void)
  {
   return Key+"\\activation-code-"+GoatTerminalToken()+".json";
  }

string GOATDeviceActivationCodeQuote(const string value)
  {
   string result="\"";
   for(int i=0;i<StringLen(value);i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(c=='\"' || c=='\\') result+="\\"+ShortToString(c);
      else if(c<32 || c>126) result+=StringFormat("\\u%04x",(int)c);
      else result+=ShortToString(c);
     }
   return result+"\"";
  }

// The same request MT5 shows: pending, a well-formed code, this login and server, unexpired.
bool GOATDeviceActivationCodeShareable(void)
  {
   string code=g_GOATDeviceActivationUserCode;
   if(StringLen(code)!=9 || StringGetCharacter(code,4)!='-') return false;
   for(int i=0;i<9;i++)
     {
      if(i==4) continue;
      ushort c=StringGetCharacter(code,i);
      if(!((c>='A' && c<='Z') || (c>='2' && c<='9'))) return false;
     }
   long now_ms=(long)TimeGMT()*1000;
   return(g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_PENDING
      && !MQLInfoInteger(MQL_TESTER)
      && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO
      && g_GOATDeviceActivationAccountId==IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))
      && g_GOATDeviceActivationServer==AccountInfoString(ACCOUNT_SERVER)
      && GOATIsSafeId(g_GOATDeviceActivationId,32,128)
      && g_GOATDeviceActivationExpiresAtMs>now_ms
      && g_GOATDeviceActivationExpiresAtMs<=now_ms+900000);
  }

void GOATDeviceActivationShareCode(void)
  {
   if(!GOATDeviceActivationCodeShareable()) return;
   FolderCreate(Key,FILE_COMMON);
   string path=GOATDeviceActivationCodePath();
   string temporary=path+"."+IntegerToString(ChartID())+"."+IntegerToString((long)GetTickCount64())+".pending";
   int h=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   string record="{\"schema\":1,\"accountId\":\""+g_GOATDeviceActivationAccountId
      +"\",\"server\":"+GOATDeviceActivationCodeQuote(g_GOATDeviceActivationServer)
      +",\"buildId\":"+GOATDeviceActivationCodeQuote(g_GOATDeviceActivationBuildId)
      +",\"activationId\":"+GOATDeviceActivationCodeQuote(g_GOATDeviceActivationId)
      +",\"userCode\":\""+g_GOATDeviceActivationUserCode
      +"\",\"expiresAtMs\":"+IntegerToString(g_GOATDeviceActivationExpiresAtMs)
      +",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())
      +",\"chart\":"+IntegerToString(ChartID())+"}";
   uint written=FileWriteString(h,record);
   FileFlush(h);FileClose(h);
   bool moved=((int)written==StringLen(record) && FileMove(temporary,FILE_COMMON,path,FILE_COMMON|FILE_REWRITE));
   if(!moved) FileDelete(temporary,FILE_COMMON);
   if(moved) g_GOATDeviceActivationCodeShared=true;
   record="";
  }

// Only this chart's own record is withdrawn; a newer code another chart shared stays.
void GOATDeviceActivationWithdrawCode(void)
  {
   if(!g_GOATDeviceActivationCodeShared) return;
   g_GOATDeviceActivationCodeShared=false;
   string path=GOATDeviceActivationCodePath(),body="";
   int h=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   ulong size=FileSize(h);
   uchar bytes[];
   if(size>0 && size<=4096 && ArrayResize(bytes,(int)size)==(int)size && FileReadArray(h,bytes)==(uint)size)
      body=CharArrayToString(bytes,0,(int)size,CP_UTF8);
   FileClose(h);
   if(StringFind(body,",\"chart\":"+IntegerToString(ChartID())+"}")>=0) FileDelete(path,FILE_COMMON);
   body="";
  }

// Every activation tick: a shared code that is no longer the one MT5 shows is withdrawn.
void GOATDeviceActivationSyncCode(void)
  {
   if(g_GOATDeviceActivationCodeShared && !GOATDeviceActivationCodeShareable()) GOATDeviceActivationWithdrawCode();
  }

bool GOATDeviceActivationOnly(void)
  {
   return(g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_INACTIVE);
  }

void GOATDeviceActivationScrub(void)
  {
   GOATDeviceActivationWithdrawCode();
   g_GOATDeviceActivationUserCode="";
   g_GOATDeviceActivationServer="";
   g_GOATDeviceActivationId="";
   g_GOATDeviceActivationCandidate="";
   g_GOATDeviceActivationAccountId="";
   g_GOATDeviceActivationBuildId="";
   g_GOATDeviceActivationExpiresAtMs=0;
   g_GOATDeviceActivationNextAttemptTick=0;
   g_GOATDeviceActivationPollSeconds=5;
   g_GOATDeviceActivationReloadRequested=false;
   g_GOATDeviceActivationReplaceCredential=false;
  }

bool GOATDeviceActivationValidCode(const string value)
  {
   if(StringLen(value)!=9 || StringGetCharacter(value,4)!='-') return false;
   for(int i=0;i<9;i++)
     {
      if(i==4) continue;
      ushort c=StringGetCharacter(value,i);
      if(!((c>='A' && c<='Z') || (c>='2' && c<='9'))) return false;
     }
   return true;
  }

int GOATDeviceActivationPostJson(const string path,const string headers,const string json,string &response)
  {
   response="";
   char post_data[],result[];
   int copied=StringToCharArray(json,post_data,0,WHOLE_ARRAY,CP_UTF8);
   if(copied<=0) return -2;
   if(post_data[copied-1]==0) ArrayResize(post_data,copied-1);
   string result_headers="";
   ResetLastError();
   int status=WebRequest("POST",URL_API+path,headers,timeout,post_data,result,result_headers);
   if(status>=0) response=CharArrayToString(result,0,-1,CP_UTF8);
   return status;
  }

bool GOATDeviceActivationPairingReadable(const long now_ms,const long account_id,const string server,const string build)
  {
   if(now_ms>=g_GOATDeviceActivationExpiresAtMs) g_GOATDeviceActivationUserCode="";
   return(g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_PENDING
      && GOATDeviceActivationValidCode(g_GOATDeviceActivationUserCode)
      && g_GOATDeviceActivationAccountId==IntegerToString(account_id)
      && g_GOATDeviceActivationBuildId==build && g_GOATDeviceActivationServer==server
      && g_GOATDeviceActivationExpiresAtMs>now_ms+15000
      && g_GOATDeviceActivationExpiresAtMs<=now_ms+900000);
  }

void GOATDeviceActivationShowNetworkHelp(void)
  {
   HidePrompt();
   ShowPrompt("Allow GOAT to reach goatedge.ai",
              "Tools > Options > Expert Advisors > Allow WebRequest",
              "Add the URL below and click OK. GOAT retries by itself.",URL_API);
  }

// The connection code is the hero line. The link carries it in the URL fragment
// (#ea-connect=), which browsers never send to a server, so it stays out of logs.
void GOATDeviceActivationShowCode(const string user_code,const string verification_url)
  {
   HidePrompt();
   // An absolute local time stays true while the card is shown; a countdown would go stale.
   datetime until=TimeLocal()+(int)((g_GOATDeviceActivationExpiresAtMs-(long)TimeGMT()*1000)/1000);
   ShowPrompt("Connection code: "+user_code,
               "Approve MT5 account "+g_GOATDeviceActivationAccountId+" in the GOAT portal (EA tab).",
               "Open the link below (code filled in). Valid until "+TimeToString(until,TIME_MINUTES)+".",
               verification_url+"#ea-connect="+user_code);
  }

void GOATDeviceActivationShowRetry(const string detail)
  {
   HidePrompt();
   ShowPrompt("GOAT is waiting to connect",detail,
              g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_BLOCKED ? "GOAT stays paused until this is fixed and re-attached." : "GOAT is safely paused and retries by itself.","");
  }

bool GOATDeviceActivationParseStart(const string response,string &activation_id,
                                    string &user_code,string &verification_url,
                                    long &expires_at_ms,int &poll_seconds,
                                    string &credential_candidate)
  {
   SGOATJsonToken tokens[];
   string expected[]={"ok","status","activationId","userCode","verificationUrl","expiresAtMs",
                      "pollIntervalSeconds","credentialCandidate"};
   bool ok=false;
   long response_status=0,poll_value=0;
   if(!GOATJsonParse(response,tokens)
      || !GOATJsonExactFields(response,tokens,0,expected)
      || !GOATJsonGetBoolean(response,tokens,0,"ok",ok) || !ok
      || !GOATJsonGetInteger(response,tokens,0,"status",response_status)
      || !GOATJsonGetString(response,tokens,0,"activationId",activation_id)
      || !GOATJsonGetString(response,tokens,0,"userCode",user_code)
      || !GOATJsonGetString(response,tokens,0,"verificationUrl",verification_url)
      || !GOATJsonGetInteger(response,tokens,0,"expiresAtMs",expires_at_ms)
      || !GOATJsonGetInteger(response,tokens,0,"pollIntervalSeconds",poll_value)
      || !GOATJsonGetString(response,tokens,0,"credentialCandidate",credential_candidate)) return false;

   long now_ms=(long)TimeGMT()*1000;
   poll_seconds=(int)poll_value;
   return(response_status==201
          && GOATIsSafeId(activation_id,32,128)
          && GOATDeviceActivationValidCode(user_code)
          && verification_url=="https://goatedge.ai/user-portal?tab=ea"
          && expires_at_ms>now_ms+30000
          && expires_at_ms<=now_ms+900000
          && poll_seconds>=3 && poll_seconds<=15
          && StringLen(credential_candidate)==72
          && StringFind(credential_candidate,"goat_ea_")==0
          && GOATIsSafeApiBearerToken(credential_candidate));
  }

bool GOATDeviceActivationWriteCredential(void)
  {
   if(StringLen(g_GOATDeviceActivationCandidate)!=72
      || StringFind(g_GOATDeviceActivationCandidate,"goat_ea_")!=0
      || !GOATIsSafeApiBearerToken(g_GOATDeviceActivationCandidate)) return false;
#ifdef GOAT_TERMINAL_ISOLATION_V149
   // One path for the whole write, from the account the user just approved. It
   // is never re-read mid-write, and the terminal must still be on that account.
   if(!GOATLoginDigitsValid(g_GOATDeviceActivationAccountId)
      || GOATAccountLoginDigits()!=g_GOATDeviceActivationAccountId) return false;
   string credential=GOATApiBearerFileFor(g_GOATDeviceActivationAccountId);
#else
   string credential=GOAT_API_BEARER_FILE;
#endif

   // Pre-isolation builds share one user-scoped FILE_COMMON credential; isolation
   // builds keep one per MT5 login (INV-CRED-01). The server
   // rechecks MT5-account membership and entitlement on every feed request.
   string directory="GOAT\\Credentials";
   string temporary=credential+".pending";
   FolderCreate(directory,FILE_COMMON);
   FileDelete(temporary,FILE_COMMON);
   int handle=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE) return false;
   uint written=FileWriteString(handle,g_GOATDeviceActivationCandidate);
   FileFlush(handle);
   FileClose(handle);
   if((int)written!=StringLen(g_GOATDeviceActivationCandidate))
     {
      FileDelete(temporary,FILE_COMMON);
      return false;
     }
   if(!FileMove(temporary,FILE_COMMON,credential,FILE_COMMON|FILE_REWRITE))
     {
      FileDelete(temporary,FILE_COMMON);
      return false;
     }
   string verification_headers="";
   bool stored=GOATBuildAuthenticatedRequestHeaders(verification_headers);
   verification_headers="";
   return stored;
  }

#ifdef GOAT_MONITOR_ONBOARDING_V149
// Chart-scoped durable restart ticket; no account ID, credential or grant.
// Two actual period changes are required. Queuing is never called success.
ulong g_GOATActivationReloadDeadline=0;
string GOATActivationReloadPath(void)
  {
   return "GOATStudio\\activation-reload-"+GOAT_BUILD_ID+"-"+(string)ChartID()+".json";
  }
void GOATActivationReloadReset(void)
  {
   // MT5 preserves globals across chart-change OnDeinit/OnInit.
   GOATDeviceActivationScrub();
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_INACTIVE;
   g_GOATActivationReloadDeadline=0;
  }
void GOATActivationReloadRequired(void)
  {
   // Preserve completed evidence even when a later attempt cannot write.
   // Failure still stays activation-only until a real normal OnInit.
   string completedBody,completedBuild,completedSymbol,completedPhase; SGOATJsonToken completed[];
   bool preserveCompleted=(GoatStudioReadUtf8(GOATActivationReloadPath(),completedBody) && GOATJsonParse(completedBody,completed)
      && GOATJsonGetString(completedBody,completed,0,"build",completedBuild) && completedBuild==GOAT_BUILD_ID
      && GOATJsonGetString(completedBody,completed,0,"symbol",completedSymbol) && completedSymbol==Symbol()
      && GOATJsonGetString(completedBody,completed,0,"phase",completedPhase) && completedPhase=="reinitialized");
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_APPROVED;
   g_GOATDeviceActivationReloadRequested=true;
   g_GOATActivationReloadDeadline=0;
   string body; SGOATJsonToken ticket[]; long original,temporary,expires;
   if(!preserveCompleted && GoatStudioReadUtf8(GOATActivationReloadPath(),body) && GOATJsonParse(body,ticket)
      && GOATJsonGetInteger(body,ticket,0,"original",original)
      && GOATJsonGetInteger(body,ticket,0,"temporary",temporary)
      && GOATJsonGetInteger(body,ticket,0,"expires",expires))
      GOATActivationReloadWrite("manual_required",original,temporary,expires);
   GOATDeviceActivationStatus("ACTIVATION_RELOAD_REQUIRED",0,0,0);
   HidePrompt();
   ShowPrompt("GOAT is connected","MT5 account "+(string)AccountInfoInteger(ACCOUNT_LOGIN)+" is approved.",
      "Change the chart timeframe once to finish starting GOAT.","");
  }
bool GOATActivationReloadWrite(const string phase,const long original,const long temporary,const long expires)
  {
   FolderCreate("GOATStudio");
   string body="{\"build\":"+GoatStudioQuote(GOAT_BUILD_ID)+",\"symbol\":"+GoatStudioQuote(Symbol())
      +",\"original\":"+(string)original+",\"temporary\":"+(string)temporary
      +",\"expires\":"+(string)expires+",\"phase\":"+GoatStudioQuote(phase)+"}";
   return GoatStudioWriteUtf8(GOATActivationReloadPath(),body,true);
  }
// Called from a real OnInit, before normal EA initialization. An intermediate
// period stays activation-only; no signals, orders, or optimization may run.
bool GOATActivationReloadPendingOnInit(void)
  {
   string path=GOATActivationReloadPath();
   if(MQLInfoInteger(MQL_TESTER) || !FileIsExist(path)) return false;
   string body,build,symbol,phase; long original,temporary,expires; SGOATJsonToken tokens[];
   if(!GoatStudioReadUtf8(path,body) || !GOATJsonParse(body,tokens)
      || !GOATJsonGetString(body,tokens,0,"build",build) || build!=GOAT_BUILD_ID
      || !GOATJsonGetString(body,tokens,0,"symbol",symbol) || symbol!=Symbol()
      || !GOATJsonGetString(body,tokens,0,"phase",phase)
      || !GOATJsonGetInteger(body,tokens,0,"original",original)
      || !GOATJsonGetInteger(body,tokens,0,"temporary",temporary)
      || !GOATJsonGetInteger(body,tokens,0,"expires",expires))
     {GOATActivationReloadRequired(); return true;}
   if(original==temporary || PeriodSeconds((ENUM_TIMEFRAMES)original)<=0
      || temporary!=(original==PERIOD_M1 ? PERIOD_M5 : PERIOD_M1))
     {GOATActivationReloadRequired(); return true;}
   if(phase=="reinitialized") return false;
   if(phase=="manual_required")
     {
      // This invocation itself proves a subsequent human/normal reload. Never
      // issue another automatic period change for the retained failed attempt.
      if(!GOATActivationReloadWrite("reinitialized",original,temporary,expires))
        {GOATActivationReloadRequired(); return true;}
      Print("GOAT activation: manual OnInit observed after bounded reload failure.");
      return false;
     }
   g_GOATDeviceActivationAccountId=(string)AccountInfoInteger(ACCOUNT_LOGIN);
   g_GOATDeviceActivationBuildId=GOAT_BUILD_ID;
   if(expires<(long)TimeGMT() || expires>(long)TimeGMT()+30)
     {
      // A later genuine human chart reload can initialize using the approved
      // credential. Do not issue another automatic chart change.
      if(!GOATActivationReloadWrite("reinitialized",original,temporary,expires))
        {GOATActivationReloadRequired(); return true;}
      Print("GOAT activation: later OnInit observed; automatic restart expired.");
      return false;
     }
   if(phase=="switch_requested" && Period()==temporary)
     {
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_APPROVED;
      g_GOATDeviceActivationReloadRequested=true;
      g_GOATActivationReloadDeadline=GetTickCount64()+(ulong)(expires-(long)TimeGMT())*1000;
      if(!GOATActivationReloadWrite("restore_requested",original,temporary,expires)
         || !ChartSetSymbolPeriod(ChartID(),Symbol(),(ENUM_TIMEFRAMES)original))
         GOATActivationReloadRequired();
      return true;
     }
   if(phase=="restore_requested" && Period()==original)
     {
      if(!GOATActivationReloadWrite("reinitialized",original,temporary,expires))
        {GOATActivationReloadRequired(); return true;}
      GOATDeviceActivationStatus("activation_oninit_observed",0,0,0);
      Print("GOAT activation: original timeframe restored; real OnInit observed.");
      return false;
     }
   GOATActivationReloadRequired(); return true;
  }
bool GOATActivationReloadOnInit(void)
  {
   if(GOATActivationReloadPendingOnInit()) return true;
   // Every non-pending path must release activation-only state, including a
   // missing ticket, an already completed ticket and a genuine manual reload.
   GOATActivationReloadReset();
   return false;
  }
#endif

void GOATDeviceActivationRequestReload(void)
  {
   g_GOATDeviceActivationUserCode="";
   GOATDeviceActivationWithdrawCode();
   if(g_GOATDeviceActivationReloadRequested) return;
   g_GOATDeviceActivationReloadRequested=true;
   HidePrompt();
#ifndef GOAT_MONITOR_ONBOARDING_V149
   ShowPrompt("GOAT activation complete","Your GOAT user credential is installed.",
               "Restarting V"+GOAT_VERSION_LABEL+" automatically...","");
#endif
   g_GOATDeviceActivationId="";
   g_GOATDeviceActivationCandidate="";
#ifdef GOAT_MONITOR_ONBOARDING_V149
   long original=(long)Period(),temporary=(Period()==PERIOD_M1 ? PERIOD_M5 : PERIOD_M1);
   long expires=(long)TimeGMT()+20;
   g_GOATActivationReloadDeadline=GetTickCount64()+20000;
   GOATDeviceActivationStatus("activation_reload_pending",0,0,20);
   ShowPrompt("GOAT is connected","MT5 account "+(string)AccountInfoInteger(ACCOUNT_LOGIN)+" is approved.",
      "Starting GOAT on this chart...","");
   if(!GOATActivationReloadWrite("switch_requested",original,temporary,expires)
      || !ChartSetSymbolPeriod(ChartID(),Symbol(),(ENUM_TIMEFRAMES)temporary))
      GOATActivationReloadRequired();
#else
   if(!ChartSetSymbolPeriod(ChartID(),Symbol(),Period()))
     {
      // Keep the request latched: activation-only mode remains inert and this
      // callback cannot retry or flood the log. A manual reattach re-enters OnInit.
      EventKillTimer();
      ShowPrompt("GOAT activation complete","Your GOAT user credential is installed.",
                  "Remove and add V"+GOAT_VERSION_LABEL+" once to finish setup.","");
     }
#endif
  }

// Exclusive handle is owned by the caller. Reserve before network IO so a
// crash cannot bypass the shared request budget. Never repair malformed state.
bool GOATDeviceActivationReserve(const int handle,const long deadline)
  {
   ResetLastError();
   if(!FileSeek(handle,0,SEEK_SET) || FileWriteLong(handle,deadline)!=8) return false;
   FileFlush(handle);
   if(GetLastError()!=0 || FileSize(handle)!=8 || !FileSeek(handle,0,SEEK_SET)) return false;
   long stored=FileReadLong(handle);
   return(GetLastError()==0 && stored==deadline);
  }

void GOATDeviceActivationAdmissionFailure(void)
  {
   g_GOATDeviceActivationUserCode="";
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_BLOCKED;
   GOATDeviceActivationStatus("activation_storage_error",0,0,0);
   GOATDeviceActivationShowRetry("MT5 can't save GOAT's sign-in timer in Common Files.");
  }

bool GOATDeviceActivationRequestStart(void)
  {
   ulong now_tick=GetTickCount64();
   if(now_tick<g_GOATDeviceActivationNextAttemptTick) return true;
   g_GOATDeviceActivationUserCode="";
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
   g_GOATDeviceActivationNextAttemptTick=now_tick+30000;

   string json="{\"accountId\":\""+g_GOATDeviceActivationAccountId
               +"\",\"buildId\":\""+g_GOATDeviceActivationBuildId+"\"}";
   string response="";
   // All terminals under this Windows user share one admission cooldown.
   // The exclusive file handle spans the request; never overwrite another lease.
   FolderCreate(Key,FILE_COMMON);
   FolderCreate(Key+"\\Credentials",FILE_COMMON);
   int admission=FileOpen(Key+"\\Credentials\\activation-admission.bin",FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(admission==INVALID_HANDLE)
     {
      GOATDeviceActivationStatus("waiting_for_host_activation",0,0,30);
      return true;
     }
   long now=(long)TimeGMT();
   ulong length=FileSize(admission);
   ResetLastError();
   long next=(length==8 ? FileReadLong(admission) : 0);
   if((length!=0 && length!=8) || GetLastError()!=0 || next<0 || next>now+900)
     {
      FileClose(admission);
      GOATDeviceActivationAdmissionFailure();
      return true;
     }
   if(next>now)
     {
      FileClose(admission);
      int wait=(int)MathMin(900.0,(double)(next-now));
      g_GOATDeviceActivationNextAttemptTick=GetTickCount64()+(ulong)wait*1000;
      GOATDeviceActivationStatus("host_activation_cooldown",0,0,wait);
      return true;
     }
   if(!GOATDeviceActivationReserve(admission,now+60))
     {
      FileClose(admission);
      GOATDeviceActivationAdmissionFailure();
      return true;
     }
   int status=GOATDeviceActivationPostJson("/api/ea/device/start",requestHeaders,json,response);
   int request_error=GetLastError();
   bool retained=(status!=429 || GOATDeviceActivationReserve(admission,(long)TimeGMT()+900));
   FileClose(admission);
   if(!retained)
     {
      GOATDeviceActivationAdmissionFailure();
      return true;
     }
   json="";
   if(status!=201)
     {
      GOATDeviceActivationFailure(status,request_error);
      return true;
     }

   string activation_id="",user_code="",verification_url="",credential_candidate="";
   long expires_at_ms=0;
   int poll_seconds=5;
   if(!GOATDeviceActivationParseStart(response,activation_id,user_code,verification_url,
                                      expires_at_ms,poll_seconds,credential_candidate))
     {
      response="";
      GOATDeviceActivationShowRetry("GOAT sent an unexpected sign-in reply.");
      return true;
     }
   response="";
   g_GOATDeviceActivationId=activation_id;
   g_GOATDeviceActivationUserCode=user_code;
   g_GOATDeviceActivationCandidate=credential_candidate;
   g_GOATDeviceActivationExpiresAtMs=expires_at_ms;
   g_GOATDeviceActivationPollSeconds=poll_seconds;
   g_GOATDeviceActivationNextAttemptTick=GetTickCount64()+(ulong)poll_seconds*1000;
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_PENDING;
   activation_id="";
   credential_candidate="";
   GOATDeviceActivationStatus("awaiting_approval",201,0,poll_seconds);
   GOATDeviceActivationShowCode(user_code,verification_url);
   GOATDeviceActivationShareCode();
   user_code="";
   return true;
  }

bool GOATDeviceActivationBegin(const long account_id,const string build_id,
                               const bool replace_existing=false)
  {
   if(account_id<=0 || !GOATIsSafeId(build_id,8,96)) return false;
   GOATDeviceActivationScrub();
   g_GOATDeviceActivationAccountId=(string)account_id;
   g_GOATDeviceActivationServer=AccountInfoString(ACCOUNT_SERVER);
   g_GOATDeviceActivationBuildId=build_id;
   g_GOATDeviceActivationReplaceCredential=replace_existing;
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
   g_GOATDeviceActivationNextAttemptTick=0;
   return GOATDeviceActivationRequestStart();
  }

void GOATDeviceActivationTimer(void)
  {
   if((long)TimeGMT()*1000>=g_GOATDeviceActivationExpiresAtMs) g_GOATDeviceActivationUserCode="";
   GOATDeviceActivationSyncCode();
#ifdef GOAT_MONITOR_ONBOARDING_V149
   if(g_GOATDeviceActivationReloadRequested && g_GOATActivationReloadDeadline>0
      && GetTickCount64()>=g_GOATActivationReloadDeadline) GOATActivationReloadRequired();
#endif
   if(!GOATDeviceActivationOnly() || g_GOATDeviceActivationReloadRequested) return;

   string existing_headers="";
   if(!g_GOATDeviceActivationReplaceCredential
      && GOATBuildAuthenticatedRequestHeaders(existing_headers))
     {
      existing_headers="";
      GOATDeviceActivationRequestReload();
      return;
     }
   existing_headers="";

   if(g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_BLOCKED) return;
   ulong now_tick=GetTickCount64();
   if(now_tick<g_GOATDeviceActivationNextAttemptTick) return;
   if(g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_PENDING)
     {
      GOATDeviceActivationRequestStart();
      return;
     }

   long now_ms=(long)TimeGMT()*1000;
   if(now_ms>=g_GOATDeviceActivationExpiresAtMs)
     {
      g_GOATDeviceActivationUserCode="";
      g_GOATDeviceActivationId="";
      g_GOATDeviceActivationCandidate="";
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
      g_GOATDeviceActivationNextAttemptTick=now_tick+1000;
      GOATDeviceActivationShowRetry("The connection code expired; getting a new one.");
      return;
     }

   string headers=requestHeaders+"Authorization: Bearer "+g_GOATDeviceActivationCandidate+"\r\n";
   string json="{\"activationId\":\""+g_GOATDeviceActivationId
               +"\",\"accountId\":\""+g_GOATDeviceActivationAccountId
               +"\",\"buildId\":\""+g_GOATDeviceActivationBuildId+"\"}";
   string response="";
   int status=GOATDeviceActivationPostJson("/api/ea/device/poll",headers,json,response);
   headers="";
   json="";
   g_GOATDeviceActivationNextAttemptTick=now_tick+(ulong)g_GOATDeviceActivationPollSeconds*1000;
   if(status==410)
     {
      g_GOATDeviceActivationUserCode="";
      g_GOATDeviceActivationId="";
      g_GOATDeviceActivationCandidate="";
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
      g_GOATDeviceActivationNextAttemptTick=now_tick+1000;
      return;
     }
   if(status!=200)
     {
      GOATDeviceActivationFailure(status,GetLastError(),false);
      return;
     }

   SGOATJsonToken tokens[];
   bool ok=false;
   string activation_status="";
   if(!GOATJsonParse(response,tokens)
      || !GOATJsonGetBoolean(response,tokens,0,"ok",ok) || !ok
      || !GOATJsonGetString(response,tokens,0,"status",activation_status))
     {
      response="";
      GOATDeviceActivationShowRetry("GOAT sent an unexpected sign-in reply.");
      return;
     }
   if(activation_status=="PENDING")
     {
      string expected[]={"ok","status","expiresAtMs","pollIntervalSeconds"};
      long expires_at_ms=0,poll_seconds=0;
      if(!GOATJsonExactFields(response,tokens,0,expected)
         || !GOATJsonGetInteger(response,tokens,0,"expiresAtMs",expires_at_ms)
         || !GOATJsonGetInteger(response,tokens,0,"pollIntervalSeconds",poll_seconds)
         || expires_at_ms!=g_GOATDeviceActivationExpiresAtMs
         || poll_seconds<3 || poll_seconds>15)
        {
         response="";
         GOATDeviceActivationShowRetry("GOAT sent an unexpected sign-in reply.");
         return;
        }
      g_GOATDeviceActivationPollSeconds=(int)poll_seconds;
      response="";
      return;
     }
   if(activation_status=="APPROVED")
     {
      string expected[]={"ok","status"};
      if(!GOATJsonExactFields(response,tokens,0,expected))
        {
         response="";
         GOATDeviceActivationShowRetry("GOAT sent an unexpected sign-in reply.");
         return;
        }
      response="";
      g_GOATDeviceActivationUserCode="";
      if(!GOATDeviceActivationWriteCredential())
        {
         GOATDeviceActivationShowRetry("MT5 could not save the GOAT sign-in file.");
         return;
        }
      GOATDeviceActivationStatus("approved",200,0,0);
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_APPROVED;
      GOATDeviceActivationRequestReload();
      return;
     }
   response="";
   GOATDeviceActivationShowRetry("GOAT sent an unexpected sign-in reply.");
  }

