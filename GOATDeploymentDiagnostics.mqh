#ifndef GOAT_DEPLOYMENT_DIAGNOSTICS_MQH
#define GOAT_DEPLOYMENT_DIAGNOSTICS_MQH

// Startup breadcrumbs only. No chart queries, credentials, account IDs or SET paths.
// File I/O is synchronous too: these records diagnose a stall, not bound native calls.
void GoatDeploymentPhase(const string phase,const long target=0,const string control="",const int error=0)
{
#ifdef GOAT_DEPLOY_STARTUP_DIAGNOSTICS
   if(MQLInfoInteger(MQL_TESTER) || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO) return;
   long owner=ChartID();
   string line=StringFormat("utc=%I64d tick=%u owner=%I64d target=%I64d phase=%s control=%s error=%d",
                            (long)TimeGMT(),GetTickCount(),owner,target,phase,control,error);
   Print("GOAT DEPLOY "+line);
   string path="GOAT\\Diagnostics\\deployment_"+IntegerToString(owner)+".log";
   int h=FileOpen(path,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ,0,CP_UTF8);
   if(h==INVALID_HANDLE) return;
   // Never truncate retained evidence. Cap this diagnostic file at 4 MiB.
   if(FileSize(h)<4194304 && FileSeek(h,0,SEEK_END))
   {
      FileWrite(h,line);
      FileFlush(h);
   }
   FileClose(h);
#endif
}

bool GoatPanelCreateFailed(const string operation,const string control,const int error)
{
   GoatDeploymentPhase("panel_failed_"+operation,ChartID(),control,error);
   return false;
}

#endif
