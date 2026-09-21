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
   string temporary=path+"."+IntegerToString(ChartID())+".pending";
   int h=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return false;
   ResetLastError();
   uint written=FileWriteString(h,body);FileFlush(h);
   bool okay=(written==StringLen(body) && GetLastError()==0);
   FileClose(h);
   return(okay && FileMove(temporary,FILE_COMMON,path,FILE_COMMON|FILE_REWRITE));
}

void GoatSetupControlPoll(void)
{
   if(Mode_Operation!=Operation_Dash || MQLInfoInteger(MQL_TESTER)) return;
   string root="GOAT\\AgentSetup\\"+GoatTerminalToken()+"\\";
   string registration="",request="";
   if(!GoatSetupRead(root+"registration.json",registration)) return;
   SGOATJsonToken reg[];
   string reg_fields[]={"schema","account","server","directory","buildId","expiresAtUtc"};
   long schema=0,account=0,expires=0;
   string build="",server="",directory="";
   if(!GOATJsonParse(registration,reg) || !GOATJsonExactFields(registration,reg,0,reg_fields)
      || !GOATJsonGetInteger(registration,reg,0,"schema",schema) || schema!=1
      || !GOATJsonGetInteger(registration,reg,0,"account",account) || account!=AccountInfoInteger(ACCOUNT_LOGIN)
      || !GOATJsonGetInteger(registration,reg,0,"expiresAtUtc",expires)
      || !GOATJsonGetString(registration,reg,0,"server",server) || server!=AccountInfoString(ACCOUNT_SERVER)
      || !GOATJsonGetString(registration,reg,0,"directory",directory) || !GoatSetupDirectoryMatches(directory)
      || !GOATJsonGetString(registration,reg,0,"buildId",build) || build!=GOAT_BUILD_ID
      || expires<(long)TimeGMT() || expires>(long)TimeGMT()+86400
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO) return;
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
   bool valid=GOATJsonGetInteger(request,tok,0,"schema",schema) && schema==1
      && GOATJsonGetInteger(request,tok,0,"account",account) && account==AccountInfoInteger(ACCOUNT_LOGIN)
      && GOATJsonGetString(request,tok,0,"server",server) && server==AccountInfoString(ACCOUNT_SERVER)
      && GOATJsonGetString(request,tok,0,"directory",directory) && GoatSetupDirectoryMatches(directory)
      && GOATJsonGetString(request,tok,0,"buildId",build) && build==GOAT_BUILD_ID
      && GOATJsonGetInteger(request,tok,0,"expiresAtUtc",expires)
      && expires>=(long)TimeGMT() && expires<=(long)TimeGMT()+300
      && GOATJsonGetString(request,tok,0,"action",action)
      && (action=="status" || action=="shutdown");
   bool inert=TerminalInfoInteger(TERMINAL_CONNECTED) && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && PositionsTotal()==0 && OrdersTotal()==0;
   string result=(!valid ? "rejected_envelope" : (action=="shutdown" && !inert ? "rejected_not_inert" : (action=="shutdown" ? "shutdown_requested" : "observed")));
   int charts=0;
   for(long cid=ChartFirst();cid>=0;cid=ChartNext(cid)) charts++;
   string body="{\"schema\":1,\"id\":\""+id+"\",\"result\":\""+result+"\",\"account\":"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))
      +",\"server\":"+GoatSetupQuote(AccountInfoString(ACCOUNT_SERVER))+",\"directory\":"+GoatSetupQuote(TerminalInfoString(TERMINAL_DATA_PATH))+",\"buildId\":\""+GOAT_BUILD_ID+"\",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())
      +",\"connected\":"+(TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false")
      +",\"tradingAllowed\":"+(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "true" : "false")
      +",\"activationOnly\":"+(GOATDeviceActivationOnly() ? "true" : "false")
      +",\"positions\":"+IntegerToString(PositionsTotal())+",\"orders\":"+IntegerToString(OrdersTotal())+",\"charts\":"+IntegerToString(charts)+"}";
   bool saved=GoatSetupWrite(receipt,body);
   if(saved && result=="shutdown_requested") TerminalClose(0);
   FileClose(lock);
}
