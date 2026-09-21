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

// Status is operational metadata only: never tokens, pairing codes or bodies.
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
   else if(status==409 && starting) GOATDeviceActivationShowRetry("This EA build is not admitted. Update the approved build before retrying.");
   else if(status==429) GOATDeviceActivationShowRetry("Activation is rate limited. Automatic retry in 15 minutes; no action needed.");
   else GOATDeviceActivationShowRetry("Activation status "+IntegerToString(status)+(delay==0 ? ". Setup needs attention; automatic requests stopped." : ". Retrying in 60 seconds."));
  }

bool GOATDeviceActivationOnly(void)
  {
   return(g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_INACTIVE);
  }

void GOATDeviceActivationScrub(void)
  {
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
   ShowPrompt("GOAT activation needs one MT5 permission",
              "Tools > Options > Expert Advisors: enable WebRequest",
              "Add the URL shown below; the EA will retry automatically.",URL_API);
  }

void GOATDeviceActivationShowCode(const string user_code,const string verification_url)
  {
   HidePrompt();
   ShowPrompt("Activate GOAT V1.47",
               "Sign in and confirm MT5 account "+g_GOATDeviceActivationAccountId+".",
               "Enter pairing code: "+user_code,verification_url);
  }

void GOATDeviceActivationShowRetry(const string detail)
  {
   HidePrompt();
   ShowPrompt("GOAT activation is waiting",detail,
              g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_BLOCKED ? "The EA is paused. Resolve setup before reattaching." : "The EA is safely paused and will retry automatically.",URL_API);
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

   // One user-scoped FILE_COMMON credential is shared locally. The server
   // rechecks MT5-account membership and entitlement on every feed request.
   string directory="GOAT\\Credentials";
   string temporary=directory+"\\api-bearer.token.pending";
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
   if(!FileMove(temporary,FILE_COMMON,GOAT_API_BEARER_FILE,FILE_COMMON|FILE_REWRITE))
     {
      FileDelete(temporary,FILE_COMMON);
      return false;
     }
   string verification_headers="";
   bool stored=GOATBuildAuthenticatedRequestHeaders(verification_headers);
   verification_headers="";
   return stored;
  }

void GOATDeviceActivationRequestReload(void)
  {
   g_GOATDeviceActivationUserCode="";
   if(g_GOATDeviceActivationReloadRequested) return;
   g_GOATDeviceActivationReloadRequested=true;
   HidePrompt();
   ShowPrompt("GOAT activation complete","Your GOAT user credential is installed.",
               "Restarting V1.47 automatically...","");
   g_GOATDeviceActivationId="";
   g_GOATDeviceActivationCandidate="";
   if(!ChartSetSymbolPeriod(ChartID(),Symbol(),Period()))
     {
      // Keep the request latched: activation-only mode remains inert and this
      // callback cannot retry or flood the log. A manual reattach re-enters OnInit.
      EventKillTimer();
      ShowPrompt("GOAT activation complete","Your GOAT user credential is installed.",
                  "Remove and add V1.47 once to finish setup.","");
     }
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
   GOATDeviceActivationShowRetry("Activation cooldown storage needs repair. No further requests will be sent.");
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
      GOATDeviceActivationShowRetry("The activation response was invalid.");
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
      GOATDeviceActivationShowRetry("The pairing code expired; requesting a fresh code.");
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
      GOATDeviceActivationShowRetry("The activation response was invalid.");
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
         GOATDeviceActivationShowRetry("The activation response was invalid.");
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
         GOATDeviceActivationShowRetry("The approval response was invalid.");
         return;
        }
      response="";
      g_GOATDeviceActivationUserCode="";
      if(!GOATDeviceActivationWriteCredential())
        {
         GOATDeviceActivationShowRetry("MT5 could not store the GOAT user credential.");
         return;
        }
      GOATDeviceActivationStatus("approved",200,0,0);
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_APPROVED;
      GOATDeviceActivationRequestReload();
      return;
     }
   response="";
   GOATDeviceActivationShowRetry("The activation state was invalid.");
  }

