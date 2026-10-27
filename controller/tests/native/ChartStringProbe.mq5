#property strict
#property description "Read-only chart/string diagnostic; no trading or permission changes."

void OnStart()
  {
   int file=FileOpen("chart-string-probe.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(file==INVALID_HANDLE) {Print("PROBE_FILE_FAILED ",GetLastError());return;}
   FileWrite(file,"kind","chart","read_ok","length","is_null","is_empty","old_reject","length_reject","value");
   string absent=NULL;
   string empty="";
   string present="KnownScript";
   FileWrite(file,"null",0,1,StringLen(absent),absent==NULL,absent=="",absent!="",StringLen(absent)>0,absent);
   FileWrite(file,"empty",0,1,StringLen(empty),empty==NULL,empty=="",empty!="",StringLen(empty)>0,empty);
   FileWrite(file,"present",0,1,StringLen(present),present==NULL,present=="",present!="",StringLen(present)>0,present);
   long chart=ChartFirst();int count=0;
   while(chart>=0 && count++<20)
     {
      string script;
      bool ok=ChartGetString(chart,CHART_SCRIPT_NAME,script);
      FileWrite(file,chart==ChartID()?"own_script_chart":"other_chart",chart,ok,StringLen(script),script==NULL,script=="",script!="",StringLen(script)>0,script);
      chart=ChartNext(chart);
     }
   FileFlush(file);FileClose(file);
   PrintFormat("CHART_STRING_PROBE_COMPLETE build=%d charts=%d null_old_reject=%s null_length=%d",__MQLBUILD__,count,absent!=""?"true":"false",StringLen(absent));
  }
