// Diagnostic-only startup breadcrumbs: local file, inert DEMO, no secrets.
bool g_GoatStartupTracing=false;
void GoatStartupTrace(const string phase)
{
   if(!g_GoatStartupTracing || MQLInfoInteger(MQL_TESTER)
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO
      || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return;
   string path="GOAT\\StartupTrace\\"+GOAT_BUILD_ID+"-"+IntegerToString(ChartID())+".tsv";
   int handle=FileOpen(path,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(handle==INVALID_HANDLE) return;
   FileWriteString(handle,IntegerToString((long)TimeGMT())+"\t"+IntegerToString(ChartID())+"\t"+Symbol()+"\t"+IntegerToString((int)Mode_Operation)+"\t"+phase+"\r\n");
   FileFlush(handle);
   FileClose(handle);
}
