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
   GOAT_DEVICE_ACTIVATION_APPROVED=3
  };

ENUM_GOAT_DEVICE_ACTIVATION_STATE g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_INACTIVE;
string g_GOATDeviceActivationId="";
string g_GOATDeviceActivationCandidate="";
string g_GOATDeviceActivationAccountId="";
string g_GOATDeviceActivationBuildId="";
long   g_GOATDeviceActivationExpiresAtMs=0;
ulong  g_GOATDeviceActivationNextAttemptTick=0;
int    g_GOATDeviceActivationPollSeconds=5;
bool   g_GOATDeviceActivationReloadRequested=false;
bool   g_GOATDeviceActivationReplaceCredential=false;
string g_GOATDeviceActivationConnectCode="";
ulong  g_GOATDeviceActivationNextOpenTick=0;

bool GOATDeviceActivationOnly(void)
  {
   return(g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_INACTIVE);
  }

void GOATDeviceActivationScrub(void)
  {
   g_GOATDeviceActivationId="";
   g_GOATDeviceActivationCandidate="";
   g_GOATDeviceActivationAccountId="";
   g_GOATDeviceActivationBuildId="";
   g_GOATDeviceActivationExpiresAtMs=0;
   g_GOATDeviceActivationNextAttemptTick=0;
   g_GOATDeviceActivationPollSeconds=5;
   g_GOATDeviceActivationReloadRequested=false;
   g_GOATDeviceActivationReplaceCredential=false;
   g_GOATDeviceActivationConnectCode="";
   g_GOATDeviceActivationNextOpenTick=0;
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
   g_GOATDeviceActivationConnectCode="";
   if(!GOATDeviceActivationValidCode(user_code)
      || verification_url!="https://goatedge.ai/user-portal?tab=ea") return;
   g_GOATDeviceActivationConnectCode=user_code;
   // Only the short-lived request code enters the URL fragment, never a bearer credential.
   string connect_url=verification_url+"#ea-connect="+user_code;
   ShowPrompt("Connect GOAT",
               "Sign in and approve MT5 account "+g_GOATDeviceActivationAccountId+".",
               "No code entry. If the browser cannot open, use the link below.",connect_url);
   int left=(int)ObjectGetInteger(ChartID(),"Prompt_Edit",OBJPROP_XDISTANCE);
   int top=(int)ObjectGetInteger(ChartID(),"Prompt_Edit",OBJPROP_YDISTANCE);
   ObjectSetInteger(ChartID(),"Prompt_Rect",OBJPROP_YSIZE,174);
   ObjectSetInteger(ChartID(),"Prompt_Edit",OBJPROP_YDISTANCE,top+38);
   ObjectSetInteger(ChartID(),"Prompt_Edit",OBJPROP_READONLY,true);
   ObjectCreate(ChartID(),"Prompt_ConnectGOAT",OBJ_BUTTON,0,0,0);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_XDISTANCE,left);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_YDISTANCE,top);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_XSIZE,180);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_YSIZE,28);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_COLOR,clrWhite);
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_BGCOLOR,C'17,47,68');
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_FONTSIZE,10);
   ObjectSetString(ChartID(),"Prompt_ConnectGOAT",OBJPROP_TEXT,"Connect GOAT");
   ChartRedraw();
  }

void GOATDeviceActivationChartEvent(const int id,const string object_name)
  {
   if(id!=CHARTEVENT_OBJECT_CLICK || object_name!="Prompt_ConnectGOAT") return;
   ObjectSetInteger(ChartID(),"Prompt_ConnectGOAT",OBJPROP_STATE,false);
   if(g_GOATDeviceActivationState!=GOAT_DEVICE_ACTIVATION_PENDING
      || g_GOATDeviceActivationReloadRequested
      || (long)TimeGMT()*1000>=g_GOATDeviceActivationExpiresAtMs
      || !GOATDeviceActivationValidCode(g_GOATDeviceActivationConnectCode)) return;
   ulong tick=GetTickCount64();
   if(tick<g_GOATDeviceActivationNextOpenTick) return;
   g_GOATDeviceActivationNextOpenTick=tick+2000;
   if(!MQLInfoInteger(MQL_DLLS_ALLOWED))
     {
      ObjectSetString(ChartID(),"Prompt_Descp2",OBJPROP_TEXT,"Open the full link below in your browser; no code entry.");
      ChartRedraw();
      return;
     }
   string connect_url="https://goatedge.ai/user-portal?tab=ea#ea-connect="+g_GOATDeviceActivationConnectCode;
   // Fixed HTTPS origin and validated code only. Never execute prompt text or server-supplied commands.
   int opened=ShellExecuteW(0,"open",connect_url,"","",1);
   if(opened<=32)
      ObjectSetString(ChartID(),"Prompt_Descp2",OBJPROP_TEXT,"Browser could not open. Open the full link below instead.");
   ChartRedraw();
  }

void GOATDeviceActivationShowRetry(const string detail)
  {
   if(g_GOATDeviceActivationState==GOAT_DEVICE_ACTIVATION_PENDING
      && (long)TimeGMT()*1000<g_GOATDeviceActivationExpiresAtMs
      && GOATDeviceActivationValidCode(g_GOATDeviceActivationConnectCode))
     {
      string pending_code=g_GOATDeviceActivationConnectCode;
      GOATDeviceActivationShowCode(pending_code,"https://goatedge.ai/user-portal?tab=ea");
      ObjectSetString(ChartID(),"Prompt_Descp2",OBJPROP_TEXT,detail);
      return;
     }
   g_GOATDeviceActivationConnectCode="";
   HidePrompt();
   ShowPrompt("GOAT activation is waiting",detail,
              "The EA is safely paused and will retry automatically.",URL_API);
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

bool GOATDeviceActivationRequestStart(void)
  {
   ulong now_tick=GetTickCount64();
   if(now_tick<g_GOATDeviceActivationNextAttemptTick) return true;
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
   g_GOATDeviceActivationNextAttemptTick=now_tick+30000;

   string json="{\"accountId\":\""+g_GOATDeviceActivationAccountId
               +"\",\"buildId\":\""+g_GOATDeviceActivationBuildId+"\"}";
   string response="";
   int status=GOATDeviceActivationPostJson("/api/ea/device/start",requestHeaders,json,response);
   json="";
   if(status==-1)
     {
      GOATDeviceActivationShowNetworkHelp();
      return true;
     }
   if(status!=201)
     {
      GOATDeviceActivationShowRetry("The activation service returned status "+IntegerToString(status)+".");
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
   g_GOATDeviceActivationCandidate=credential_candidate;
   g_GOATDeviceActivationExpiresAtMs=expires_at_ms;
   g_GOATDeviceActivationPollSeconds=poll_seconds;
   g_GOATDeviceActivationNextAttemptTick=GetTickCount64()+(ulong)poll_seconds*1000;
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_PENDING;
   activation_id="";
   credential_candidate="";
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
   g_GOATDeviceActivationBuildId=build_id;
   g_GOATDeviceActivationReplaceCredential=replace_existing;
   g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
   g_GOATDeviceActivationNextAttemptTick=0;
   return GOATDeviceActivationRequestStart();
  }

void GOATDeviceActivationTimer(void)
  {
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
      g_GOATDeviceActivationId="";
      g_GOATDeviceActivationCandidate="";
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
      g_GOATDeviceActivationNextAttemptTick=now_tick+1000;
      GOATDeviceActivationShowRetry("The connection link expired; requesting a fresh link.");
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
   if(status==-1)
     {
      GOATDeviceActivationShowNetworkHelp();
      return;
     }
   if(status==410)
     {
      g_GOATDeviceActivationId="";
      g_GOATDeviceActivationCandidate="";
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_STARTING;
      g_GOATDeviceActivationNextAttemptTick=now_tick+1000;
      return;
     }
   if(status!=200)
     {
      GOATDeviceActivationShowRetry("The activation service returned status "+IntegerToString(status)+".");
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
      if(!GOATDeviceActivationWriteCredential())
        {
         GOATDeviceActivationShowRetry("MT5 could not store the GOAT user credential.");
         return;
        }
      g_GOATDeviceActivationState=GOAT_DEVICE_ACTIVATION_APPROVED;
      GOATDeviceActivationRequestReload();
      return;
     }
   response="";
   GOATDeviceActivationShowRetry("The activation state was invalid.");
  }

