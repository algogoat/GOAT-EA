#property strict

input long ExpectedAccount=0;
input string DashboardTemplate="GOAT Agent Dashboard.tpl";

string ReceiptPath()
{
   string path=TerminalInfoString(TERMINAL_DATA_PATH);
   int last=-1;
   for(int i=0;i<StringLen(path);i++) if(path[i]=='\\' || path[i]=='/') last=i;
   return "GOAT\\setup-bootstrap-v3-"+StringSubstr(path,last+1)+".json";
}

bool Receipt(const string phase,const long chart_id,const int error)
{
   FolderCreate("GOAT",FILE_COMMON);
   string path=ReceiptPath();
   int h=FileOpen(path+".pending",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return false;
   string body="{\"phase\":\""+phase+"\",\"account\":"+IntegerToString(ExpectedAccount)+",\"chartId\":"+IntegerToString(chart_id)+",\"error\":"+IntegerToString(error)+",\"observedAtUtc\":"+IntegerToString((long)TimeGMT())+"}";
   uint n=FileWriteString(h,body);FileFlush(h);FileClose(h);
   return(n==StringLen(body) && FileMove(path+".pending",FILE_COMMON,path,FILE_COMMON|FILE_REWRITE));
}

void OnStart()
{
   // One-shot setup only. Never issue an order or change trading permissions.
   if(ExpectedAccount<=0 || DashboardTemplate!="GOAT Agent Dashboard.tpl") return;
   for(int i=0;i<60 && (!TerminalInfoInteger(TERMINAL_CONNECTED) || AccountInfoInteger(ACCOUNT_LOGIN)!=ExpectedAccount);i++) Sleep(1000);
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) || AccountInfoInteger(ACCOUNT_LOGIN)!=ExpectedAccount
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO
      || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || PositionsTotal()!=0 || OrdersTotal()!=0)
     {Receipt("preflight_rejected",0,0);return;}

   // A retained receipt requires inspection, never a blind repeat of ChartOpen.
   if(FileIsExist(ReceiptPath(),FILE_COMMON)) return;
   for(long cid=ChartFirst();cid>=0;cid=ChartNext(cid))
      if(cid!=ChartID() && StringFind(ChartGetString(cid,CHART_EXPERT_NAME),"GOAT")>=0)
        {
         if(ChartGetString(cid,CHART_EXPERT_NAME)!="GOAT V1.47")
           {Receipt("existing_expert_requires_inspection",cid,0);return;}
         // Preserve the existing chart instead of creating another. The caller
         // must inspect the saved template and prove restart restoration.
         if(!ChartSaveTemplate(cid,"GOAT Existing Dashboard.tpl"))
           {Receipt("existing_template_save_failed",cid,GetLastError());return;}
         if(!Receipt("existing_expert_saved_restart_required",cid,0)) return;
         Sleep(2000);
         if(!TerminalClose(0)) Receipt("terminal_close_failed",cid,GetLastError());
         return;
        }
   if(!Receipt("reserved",0,0)) return;
   long dashboard=ChartOpen("EURUSD",PERIOD_M1);
   if(dashboard==0){Receipt("chart_open_failed",0,GetLastError());return;}
   if(!Receipt("chart_created",dashboard,0)) return;
   if(!ChartApplyTemplate(dashboard,DashboardTemplate))
     {Receipt("template_failed",dashboard,GetLastError());return;}
   for(int i=0;i<30 && ChartGetString(dashboard,CHART_EXPERT_NAME)!="GOAT V1.47";i++) Sleep(1000);
   if(ChartGetString(dashboard,CHART_EXPERT_NAME)!="GOAT V1.47")
     {Receipt("expert_not_observed",dashboard,0);return;}
   if(!Receipt("expert_attached_restart_required",dashboard,0)) return;
   // This is a normal ChartOpen chart, not the disposable /config startup chart.
   // Native orderly shutdown saves it to the persistent profile.
   Sleep(2000);
   if(!TerminalClose(0)) Receipt("terminal_close_failed",dashboard,GetLastError());
}
