// Opt-in, demo-only setup RPC. No trading or credential-install commands.
string GoatSetupQuote(const string value)
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

bool GoatSetupDirectoryMatches(string value)
{
   string actual=TerminalInfoString(TERMINAL_DATA_PATH);
   StringReplace(value,"/","\\");StringReplace(actual,"/","\\");
   return(StringCompare(value,actual,false)==0);
}

bool GoatSetupRead(const string path,string &body)
{
   body="";
   int h=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON);
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h);
   if(size==0 || size>4096){FileClose(h);return false;}
   uchar bytes[];ArrayResize(bytes,(int)size);
   uint got=FileReadArray(h,bytes);FileClose(h);
   if(got!=size) return false;
   body=CharArrayToString(bytes,0,(int)size,CP_UTF8);
   return true;
}

bool GoatSetupWrite(const string path,const string body)
{
   static long serial=0;
   string temporary=path+"."+IntegerToString(ChartID())+"."+IntegerToString((long)GetTickCount64())+"."+IntegerToString(++serial)+".pending";
   // Never truncate a retained temporary from another attempt or unknown writer.
   if(FileIsExist(temporary,FILE_COMMON)) return false;
   int h=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return false;
   ResetLastError();
   uint written=FileWriteString(h,body);FileFlush(h);
   bool okay=(written==StringLen(body) && GetLastError()==0);
   FileClose(h);
   return(okay && FileMove(temporary,FILE_COMMON,path,FILE_COMMON|FILE_REWRITE));
}

// Only a complete, expired, identity-bound pairing payload can be scrubbed.
// Malformed/foreign files remain evidence; a receipt ID is never deleted.
bool GoatSetupExpiredPairing(const string path,const string expected_id,string &tombstone)
{
   string body="";
   tombstone="";
   if(!GoatSetupRead(path,body)) return false;
   SGOATJsonToken tokens[];
   string fields[]={"schema","id","result","account","server","directory","buildId","observedAtUtc",
      "connected","tradingAllowed","activationOnly","positions","orders","charts",
      "userCode","activationId","responseExpiresAtUtc","pairingExpiresAtMs"};
   long schema=0,account=0,observed=0,expiry=0,pairing_expiry=0,positions=0,order_count=0,charts=0;
   string id="",result="",server="",directory="",build="",code="",activation="";
   bool connected=false,trading=false,activation_only=false;
   long now=(long)TimeGMT();
   if(!GOATJsonParse(body,tokens) || !GOATJsonExactFields(body,tokens,0,fields)
      || !GOATJsonGetInteger(body,tokens,0,"schema",schema) || schema!=1
      || !GOATJsonGetString(body,tokens,0,"id",id) || id!=expected_id
      || !GOATJsonGetString(body,tokens,0,"result",result) || result!="pairing_available"
      || !GOATJsonGetInteger(body,tokens,0,"account",account) || account!=AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetString(body,tokens,0,"server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(body,tokens,0,"directory",directory) || !GoatSetupDirectoryMatches(directory)
      || !GOATJsonGetString(body,tokens,0,"buildId",build) || build!=GOAT_BUILD_ID
      || !GOATJsonGetInteger(body,tokens,0,"observedAtUtc",observed) || observed<0 || observed>now
      || !GOATJsonGetInteger(body,tokens,0,"responseExpiresAtUtc",expiry) || expiry<=observed || expiry>observed+60 || expiry>now
      || !GOATJsonGetInteger(body,tokens,0,"pairingExpiresAtMs",pairing_expiry)
      || pairing_expiry<=observed*1000 || pairing_expiry>(observed+900)*1000 || expiry>pairing_expiry/1000
      || !GOATJsonGetBoolean(body,tokens,0,"connected",connected) || !connected
      || !GOATJsonGetBoolean(body,tokens,0,"tradingAllowed",trading) || trading
      || !GOATJsonGetBoolean(body,tokens,0,"activationOnly",activation_only) || !activation_only
      || !GOATJsonGetInteger(body,tokens,0,"positions",positions) || positions!=0
      || !GOATJsonGetInteger(body,tokens,0,"orders",order_count) || order_count!=0
      || !GOATJsonGetInteger(body,tokens,0,"charts",charts) || charts<0 || charts>2147483647
      || !GOATJsonGetString(body,tokens,0,"userCode",code) || !GOATDeviceActivationValidCode(code)
      || !GOATJsonGetString(body,tokens,0,"activationId",activation) || StringLen(activation)!=32) return false;
   for(int i=0;i<32;i++)
     {
      ushort c=StringGetCharacter(activation,i);
      if(!((c>='a' && c<='z') || (c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_' || c=='-')) return false;
     }
   tombstone="{\"schema\":1,\"id\":"+GoatSetupQuote(id)+",\"result\":\"pairing_consumed\",\"account\":"+IntegerToString(account)
      +",\"server\":"+GoatSetupQuote(server)+",\"directory\":"+GoatSetupQuote(directory)+",\"buildId\":"+GoatSetupQuote(build)
      +",\"observedAtUtc\":"+IntegerToString(observed)+",\"connected\":true,\"tradingAllowed\":false,\"activationOnly\":true"
      +",\"positions\":0,\"orders\":0,\"charts\":"+IntegerToString(charts)+"}";
   code="";activation="";body="";
   return true;
}

void GoatSetupCleanupExpiredPairing(const string root)
{
   // Runs independently of registration expiry, but only for the retained
   // pairing request's exact ID. No directory-wide cleanup or unknown deletion.
   int lock=FileOpen(root+"owner.lock",FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(lock==INVALID_HANDLE) return;
   string request="",id="",action="",server="",directory="",build="";
   long schema=0,account=0,expires=0;
   SGOATJsonToken tokens[];
   string fields[]={"schema","id","account","server","directory","buildId","expiresAtUtc","action"};
   if(!GoatSetupRead(root+"request.json",request) || !GOATJsonParse(request,tokens)
      || !GOATJsonExactFields(request,tokens,0,fields)
      || !GOATJsonGetInteger(request,tokens,0,"schema",schema) || schema!=2
      || !GOATJsonGetString(request,tokens,0,"action",action) || action!="pairing"
      || !GOATJsonGetString(request,tokens,0,"id",id) || StringLen(id)!=32
      || !GOATJsonGetInteger(request,tokens,0,"expiresAtUtc",expires) || expires<0
      || !GOATJsonGetInteger(request,tokens,0,"account",account) || account!=AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetString(request,tokens,0,"server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(request,tokens,0,"directory",directory) || !GoatSetupDirectoryMatches(directory)
      || !GOATJsonGetString(request,tokens,0,"buildId",build) || build!=GOAT_BUILD_ID)
     {FileClose(lock);return;}
   for(int i=0;i<32;i++)
     {
      ushort c=StringGetCharacter(id,i);
      if(!((c>='a' && c<='f') || (c>='0' && c<='9'))){FileClose(lock);return;}
     }
   string receipt=root+id+".json",tombstone="";
   if(GoatSetupExpiredPairing(receipt,id,tombstone)) GoatSetupWrite(receipt,tombstone);
   string name="",prefix=id+".json.";
   long search=FileFindFirst(root+prefix+"*.pending",name,FILE_COMMON);
   if(search!=INVALID_HANDLE)
     {
      int examined=0;
      do
        {
         if(++examined>16) break;
         int digits=StringLen(name)-StringLen(prefix)-8;
         bool known=(StringFind(name,prefix)==0 && digits>0 && digits<=62
            && StringSubstr(name,StringLen(name)-8)==".pending");
         int parts=1,part_digits=0;
         for(int i=0;known && i<digits;i++)
           {
            ushort c=StringGetCharacter(name,StringLen(prefix)+i);
            if(c=='.')
              {
               if(part_digits==0 || part_digits>20) known=false;
               parts++;part_digits=0;
              }
            else if(c<'0' || c>'9') known=false;
            else part_digits++;
           }
         known=known && part_digits>0 && part_digits<=20 && (parts==1 || parts==3);
         if(known && GoatSetupExpiredPairing(root+name,id,tombstone))
           {
            // Reserve the receipt ID before scrubbing an orphaned write.
            // Preserve any existing receipt, including unknown evidence.
            bool reserved=FileIsExist(receipt,FILE_COMMON) || GoatSetupWrite(receipt,tombstone);
            if(reserved && FileIsExist(root+name,FILE_COMMON)) GoatSetupWrite(root+name,tombstone);
           }
        }
      while(FileFindNext(search,name));
      FileFindClose(search);
     }
   FileClose(lock);
}

void GoatSetupControlPoll(void)
{
   if(Mode_Operation!=Operation_Dash || MQLInfoInteger(MQL_TESTER)) return;
   string root="GOAT\\AgentSetup\\"+GoatTerminalToken()+"\\";
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO) GoatSetupCleanupExpiredPairing(root);
   string registration="",request="";
   if(!GoatSetupRead(root+"registration.json",registration)) return;
   SGOATJsonToken reg[];
   string reg_fields[]={"schema","account","server","directory","buildId","expiresAtUtc"};
   string pairing_reg_fields[]={"schema","account","server","directory","buildId","expiresAtUtc","allowPairingRead"};
   long schema=0,account=0,expires=0;
   bool allow_pairing=false;
   string build="",server="",directory="";
   if(!GOATJsonParse(registration,reg) || !GOATJsonGetInteger(registration,reg,0,"schema",schema)) return;
   if(schema==1)
     {
      if(!GOATJsonExactFields(registration,reg,0,reg_fields)) return;
     }
   else if(schema==2)
     {
      if(!GOATJsonExactFields(registration,reg,0,pairing_reg_fields)
         || !GOATJsonGetBoolean(registration,reg,0,"allowPairingRead",allow_pairing) || !allow_pairing) return;
     }
   else return;
   if(!GOATJsonGetInteger(registration,reg,0,"account",account) || account!=AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetInteger(registration,reg,0,"expiresAtUtc",expires)
      || !GOATJsonGetString(registration,reg,0,"server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(registration,reg,0,"directory",directory) || !GoatSetupDirectoryMatches(directory)
      || !GOATJsonGetString(registration,reg,0,"buildId",build) || build!=GOAT_BUILD_ID
      || expires<(long)TimeGMT() || expires>(long)TimeGMT()+86400
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO) return;
   if(allow_pairing && expires>(long)TimeGMT()+900) return;
   long registration_expires=expires;
   int lock=FileOpen(root+"owner.lock",FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(lock==INVALID_HANDLE) return;
   if(!GoatSetupRead(root+"request.json",request)){FileClose(lock);return;}
   SGOATJsonToken tok[];
   string fields[]={"schema","id","account","server","directory","buildId","expiresAtUtc","action"};
   string id="",action="";
   if(!GOATJsonParse(request,tok) || !GOATJsonExactFields(request,tok,0,fields)
      || !GOATJsonGetString(request,tok,0,"id",id) || StringLen(id)!=32)
     {FileClose(lock);return;}
   for(int i=0;i<32;i++)
     {
      ushort c=StringGetCharacter(id,i);
      if(!((c>='0' && c<='9') || (c>='a' && c<='f'))){FileClose(lock);return;}
     }
   string receipt=root+id+".json";
   if(FileIsExist(receipt,FILE_COMMON)){FileClose(lock);return;}
   long request_schema=0;
   bool valid=GOATJsonGetInteger(request,tok,0,"schema",request_schema) && (request_schema==1 || request_schema==2)
      && GOATJsonGetInteger(request,tok,0,"account",account) && account==AccountInfoInteger(ACCOUNT_LOGIN)
      && GOATJsonGetString(request,tok,0,"server",server) && server==AccountInfoString(ACCOUNT_SERVER)
      && GOATJsonGetString(request,tok,0,"directory",directory) && GoatSetupDirectoryMatches(directory)
      && GOATJsonGetString(request,tok,0,"buildId",build) && build==GOAT_BUILD_ID
      && GOATJsonGetInteger(request,tok,0,"expiresAtUtc",expires)
      && expires>=(long)TimeGMT() && expires<=(long)TimeGMT()+300
      && GOATJsonGetString(request,tok,0,"action",action)
      && ((request_schema==1 && (action=="status" || action=="shutdown"))
         || (request_schema==2 && action=="pairing" && allow_pairing));
   bool inert=TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && PositionsTotal()==0 && OrdersTotal()==0;
   string result=(!valid ? "rejected_envelope" : (action=="shutdown" && !inert ? "rejected_not_inert" : (action=="shutdown" ? "shutdown_requested" : "observed")));
   bool pairing_available=false;
   if(valid && action=="pairing")
     {
      pairing_available=inert && GOATDeviceActivationPairingReadable((long)TimeGMT()*1000,
         AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),GOAT_BUILD_ID);
      result=(!inert ? "rejected_not_inert" : (pairing_available ? "pairing_available" : "pairing_unavailable"));
     }
   int charts=0;
   for(long cid=ChartFirst();cid>=0;cid=ChartNext(cid)) charts++;
   string body="{\"schema\":1,\"id\":\""+id+"\",\"result\":\""+result+"\",\"account\":"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))
      +",\"server\":"+GoatSetupQuote(AccountInfoString(ACCOUNT_SERVER))+",\"directory\":"+GoatSetupQuote(TerminalInfoString(TERMINAL_DATA_PATH))+",\"buildId\":\""+GOAT_BUILD_ID+"\",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())
      +",\"connected\":"+(TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false")
      +",\"tradingAllowed\":"+(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "true" : "false")
      +",\"activationOnly\":"+(GOATDeviceActivationOnly() ? "true" : "false")
      +",\"positions\":"+IntegerToString(PositionsTotal())+",\"orders\":"+IntegerToString(OrdersTotal())+",\"charts\":"+IntegerToString(charts)+"}";
   if(pairing_available)
     {
      body=StringSubstr(body,0,StringLen(body)-1)
         +",\"userCode\":"+GoatSetupQuote(g_GOATDeviceActivationUserCode)
         +",\"activationId\":"+GoatSetupQuote(g_GOATDeviceActivationId)
         +",\"responseExpiresAtUtc\":"+IntegerToString((long)MathMin(MathMin((double)expires,(double)registration_expires),MathMin((double)((long)TimeGMT()+60),(double)(g_GOATDeviceActivationExpiresAtMs/1000))))
         +",\"pairingExpiresAtMs\":"+IntegerToString(g_GOATDeviceActivationExpiresAtMs)+"}";
     }
   bool saved=GoatSetupWrite(receipt,body);
   if(saved && result=="shutdown_requested") TerminalClose(0);
   FileClose(lock);
}
