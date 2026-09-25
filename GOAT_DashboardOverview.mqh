#ifndef GOAT_DASHBOARD_OVERVIEW_MQH
#define GOAT_DASHBOARD_OVERVIEW_MQH

// Presentation only: these helpers never write policy or dispatch commands.
string GoatDashboardAILabel(const int mode,const int protocol,const int threshold)
  {
   if(mode==1) return "OFF";
   string feed=(protocol==2 ? "DEMO" : (protocol==1 ? "LIVE" : (protocol==0 ? "Recorded" : "Unknown feed")));
   if(mode==0) return "DISPLAY / "+feed;
   if(mode<2 || mode>5 || threshold<1 || threshold>100) return "Unknown configuration";
   string purpose=(mode==2 ? "ON" : "ON + exits");
   return purpose+" / "+feed+" / "+IntegerToString(threshold)+"%";
  }

string GoatDashboardExposureLabel(const int mode)
  {
   if(mode==0) return "OFF";
   if(mode==1) return "ON";
   if(mode==2) return "Currency mode";
   return "Unknown";
  }

bool GoatIsDashboardChart(const long cid)
  {
   if(cid<=0 || ChartSymbol(cid)=="") return false;
   // CAppDialog generates an instance-specific object prefix on each attach.
   // Inspect its caption rather than relying on chart order or a stale global.
   int count=ObjectsTotal(cid,0,-1);
   for(int i=0;i<count;i++)
     {
      string name=ObjectName(cid,i,0,-1);
      if(StringLen(name)<7 || StringSubstr(name,StringLen(name)-7)!="Caption") continue;
      string caption=ObjectGetString(cid,name,OBJPROP_TEXT);
      if(StringFind(caption,"GOAT  /  PORTFOLIO DASHBOARD  /")==0 ||
         StringFind(caption,"GOAT  /  PORTFOLIO COMMAND CENTER  /")==0) return true;
     }
   return false;
  }

long GoatFindDashboardChart(const string key)
  {
   if(GlobalVariableCheck("Dashboard_ChartID"))
     {
      long hint=(long)GlobalVariableGet("Dashboard_ChartID");
      if(GoatIsDashboardChart(hint)) return hint;
     }
   long found=-1;
   for(long cid=ChartFirst();cid>=0;cid=ChartNext(cid))
     {
      if(!GoatIsDashboardChart(cid)) continue;
      if(found>=0) return -1; // Ambiguous: do not navigate to an arbitrary chart.
      found=cid;
     }
   return found;
  }

void GoatDashboardControlVisible(CWnd &control,const bool visible)
  {
   if(control.Name()=="") return;
   if(visible) control.Show();
   else control.Hide();
  }

#endif
