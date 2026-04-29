#include "MTTester.mqh"
#include "XmlProcessor.mqh"

#import "shell32.dll"
int ShellExecuteW(int hWnd, string lpOperation, string lpFile, string lpParameters, string lpDirectory, int nShowCmd);
#import
// Import the Windows API function to get the current process ID
//#import "kernel32.dll"
////int GetCurrentProcessId();
//#import
//+------------------------------------------------------------------+
string PowerShellSingleQuoted(string text)
  {
   StringReplace(text,"'","''");
   return text;
  }
//+------------------------------------------------------------------+
void AddCommand(string path)
  {
   //if(!TerminalInfoInteger(TERMINAL_DLLS_ALLOWED)) MessageBox()
   string terminal_path = TerminalInfoString(TERMINAL_PATH) + "\\terminal64.exe";
   string config_path   = TerminalInfoString(TERMINAL_COMMONDATA_PATH)+"\\Files\\"+path+"\\config.ini";
   // Get the current terminal's PID for the 'Wait-Process'
   uint    pid      = GetCurrentProcessId();
   string pidStr   = IntegerToString(pid);
   //string psPath = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";
   // Build a PowerShell command to:
   //  1) Wait for this process to exit
   //  2) Launch a new terminal64 with the /config parameter
   string psCommand = 
       "$ErrorActionPreference='SilentlyContinue'; " +
       "$tp='" + PowerShellSingleQuoted(terminal_path) + "'; " +
       "$cp='" + PowerShellSingleQuoted(config_path) + "'; " +
       "Wait-Process -Id " + pidStr + " -ErrorAction SilentlyContinue; " +
       "Start-Sleep -Milliseconds 500; " +
       "$q=[char]34; " +
       "Start-Process -FilePath $tp -ArgumentList ('/config:'+$q+$cp+$q)";
   // Parameters to run PowerShell in no-profile, bypass execution policy
   string parameters = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command \"" + psCommand + "\"";
   // Launch PowerShell
   ShellExecuteW(0, "open", "powershell.exe", parameters, "", 0);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
struct SettingsStrings
  {
   string _K,_N,_S;
   string str_testerSettings,str_Inputs,Strat,Expert,symbol,period_,Optimization,Model,fromDate,toDate,ForwardMode,ForwardDate,ExecutionMode,Visual;
   SettingsStrings() {str_testerSettings="";str_Inputs="";Expert="";symbol="";period_="";Optimization="";Model="";fromDate="";toDate="";ForwardMode="";ForwardDate="";ExecutionMode="";Visual="";}
  };
SettingsStrings strT;
//----------------------------------------------------------------------------------------------------------------------------------------------------
struct ExportRecord
  {
   string csvFile,setFile;       // full TARGET paths in TEMP2
   double trds,prf,dd,pf,sr,arf;
   int    rowIndex;              // xmlData.RowsUnique[] index that produced it
   ExportRecord()
   {
      csvFile = ""; setFile = "";
      trds=prf=dd=pf=sr=arf = 0.0;
      rowIndex = -1;
   }
   ExportRecord(const ExportRecord &src)
   {
      csvFile = src.csvFile; setFile = src.setFile;
      trds=src.trds; prf=src.prf; dd=src.dd; pf=src.pf; sr=src.sr;arf=src.arf;
      rowIndex= src.rowIndex;
   }
  };
ExportRecord g_allExports[];
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool InitializeTester(string Key_,string EA_Name_,string Server_,bool reportMode)
  {
   strT._K=Key_; strT._N=EA_Name_; strT._S=Server_;
   
   int Attempts=5;
   for(int cycle=1; cycle<=Attempts; ++cycle)
   {
    if(!MTTESTER::GetSettings2(strT.str_testerSettings))
    {
     if(cycle==Attempts) {LogOrAlert(reportMode,StringFormat("❌ Error retrieving tester settings via DLL! after %d Attempts – Aborting...",Attempts),strT._K,strT._N,strT._S); return false;}
     else                {LogOrAlert(reportMode,StringFormat("❌ Error retrieving tester settings via DLL! Attempt %d/%d: failed, Retrying...",cycle,Attempts),strT._K,strT._N,strT._S); continue;}
    }
   }
   string Lines[];
   int n = StringSplit(strT.str_testerSettings,'\n',Lines);
   for(int i=0;i<n;i++)
     {
      string ln=StringTrim(Lines[i]);
      if(StringFind(ln,"EA_Desc=")==0)
        {
         string val=StringSubstr(ln,StringLen("EA_Desc="));
         StringTrimRight(val);
         strT.Strat=val;
        }
     }
   // 2) Extract the [Tester] config lines into your variables //xmlData.
   ExtractConfigSettings(strT.str_testerSettings,strT.Expert,strT.symbol,strT.period_,strT.Optimization,strT.Model,strT.fromDate,strT.toDate,strT.ForwardMode,strT.ExecutionMode,strT.Visual);
   //Print(Expert);Print(symbol);Print(period_);Print(Optimization);Print(Model);Print(fromDate);Print(toDate);Print(ForwardMode);Print(ExecutionMode);Print(Visual);
   int pos = StringFind(strT.Expert, "\\", -1);
   string s_EA=(pos>=0)?StringSubstr(strT.Expert, pos+1):strT.Expert; 
   EA_Name_+=".ex5";
   if(s_EA!=EA_Name_)                     LogOrAlert(reportMode,"⚠️ EA Name in strategy tester does not match. EA name:"+EA_Name_+" Tester:"+s_EA,strT._K,strT._N,strT._S);
   if(strT.symbol!=xmlData.symbol_)       LogOrAlert(reportMode,"⚠️ Symbol in strategy tester does not match. Symbol:"+xmlData.symbol_+" Tester:"+strT.symbol,strT._K,strT._N,strT._S);
   if(strT.period_!=xmlData.TF_)          LogOrAlert(reportMode,"⚠️ Period in strategy tester does not match. Period:"+xmlData.TF_+" Tester:"+strT.period_,strT._K,strT._N,strT._S);
   strT.Optimization="0";  // Disabled
   
   if(reportMode) {strT.fromDate=TimeToString(xmlData.startD,TIME_DATE); strT.toDate=TimeToString(xmlData.endD,TIME_DATE);}
   
   if(strT.fromDate!=TimeToString(xmlData.startD,TIME_DATE))   LogOrAlert(reportMode,"⚠️ Start Date in strategy tester does not match. StartD:"
                                                                                        +TimeToString(xmlData.startD,TIME_DATE)+" Tester:"+strT.fromDate,strT._K,strT._N,strT._S);
   if(strT.toDate!=TimeToString(xmlData.endD,TIME_DATE))       LogOrAlert(reportMode,"⚠️ End Date in strategy tester does not match. EndD:"
                                                                                        +TimeToString(xmlData.endD,TIME_DATE)+" Tester:"+strT.toDate,strT._K,strT._N,strT._S);
   strT.ForwardMode="0";   // Disabled
   strT.ForwardDate="";
 //strT.ExecutionMode="0";
   strT.Visual="0";        // Disabled
   if(reportMode) {int ret=MessageBox("Set these parameters in the strategy tester manually:\n\nDelay\nDeposit\nCurrency\nLeverage\n\nThen Press OK","Info",MB_OK|MB_ICONINFORMATION);}
   LogOrAlert(reportMode,"Initializing Tester Settings.",strT._K,strT._N,strT._S);
   ReplaceSettingsInputs(strT.str_testerSettings,"",strT.Expert,strT.symbol,strT.period_,strT.Optimization,strT.Model,strT.fromDate,strT.toDate,
                                                    strT.ForwardMode,strT.ForwardDate,strT.ExecutionMode,strT.Visual); //Print(str_testerSettings);
   if(VerifyTesterSettings(reportMode,5))
   {
    LogOrAlert(reportMode,"Tester Settings Initialized.",strT._K,strT._N,strT._S); Sleep(50);
   }
   else {LogOrAlert(reportMode,"❌ Tester Settings not adjusted – aborting exports...",strT._K,strT._N,strT._S);  return false;}
   return true;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool StartTester(int rowInd,string mode,bool reportMode,const int Attempts=20)
  {
   // SAFEGUARD: do not touch Strategy Tester while it's running
   const datetime t0 = TimeLocal();
   while(!MTTESTER::IsIdle())
   {
    Sleep(500);
    if(TimeLocal()-t0 > 500) // 500 sec watchdog
    {
     LogOrAlert(reportMode,"❌ Strategy Tester running for 500 seconds timed out waiting to become idle – Unable to start the test",strT._K,strT._N,strT._S);
     return(false);
    }
   }
   strT.str_Inputs = mode+xmlData.getInputsSettingString(rowInd); //Print("Inputs for row "+(string)rowInd+":",strT.str_Inputs);
   //strT.Optimization = "0";
   // 4) Replace only those matching lines in the [TesterInputs] section with the new values from str_Inputs, and also reflect updated config lines in the [Tester] section if you changed them above.
   ReplaceSettingsInputs(strT.str_testerSettings,strT.str_Inputs,strT.Expert,strT.symbol,strT.period_,strT.Optimization,strT.Model,strT.fromDate,strT.toDate,
                                                                 strT.ForwardMode,strT.ForwardDate,strT.ExecutionMode,strT.Visual); //Print(str_testerSettings);
   string wantedIni = strT.str_testerSettings;//;
   
   for(int cycle=1; cycle<=Attempts; ++cycle)
   {
    Sleep(100);
    if(!MTTESTER::SetSettings2(strT.str_testerSettings))
    {
     LogOrAlert(reportMode,StringFormat("Setting Attempt %d/%d: failed",cycle,Attempts),strT._K,strT._N,strT._S); continue;
    }
    Sleep(50);
    string loadedIni = "";
    if(!MTTESTER::GetSettings2(loadedIni))
    {
     LogOrAlert(reportMode,StringFormat("Reading Attempt %d/%d: failed",cycle,Attempts),strT._K,strT._N,strT._S); continue;
    }
    Sleep(50);
    //if(CanonicalIni(NormalizeIni(loadedIni)) == CanonicalIni(NormalizeIni(strT.str_testerSettings)))
    if(CompareCanonicalIni(loadedIni,strT.str_testerSettings))
    {
     LogOrPrint(reportMode,StringFormat("Attempt %d/%d: Settings verified – starting tester",cycle,Attempts),strT._K,strT._N,strT._S);
     for(int i=0;i<Attempts;i++)
     {
      Sleep(100);
      if(MTTESTER::ClickStart())
      {
       Sleep(200);
       if(!MTTESTER::SelectTesterGraphTab()) LogOrPrint(reportMode,"⚠️ Tester Graph tab selection request failed; export continues.",strT._K,strT._N,strT._S);
       return true;
      }
      else                       LogOrPrint(reportMode,"❌ Failed to Click the Strategy Tester Start Button.",strT._K,strT._N,strT._S);
     }
     return false;
    }
    else
    {
     LogOrAlert(reportMode,StringFormat("❌ Attempt %d/%d: Mismatch – retrying...",cycle,Attempts),strT._K,strT._N,strT._S);
    }
    if(rowInd==0)
    {
      // debugging log 
      //string loadedInifile=strT._K+"\\"+strT._N+"-"+strT._S+"\\loaded."+strT._K;
      //int handle = FileOpen(loadedInifile,FILE_WRITE|FILE_COMMON);
      //FileWrite(handle,loadedIni); FileClose(handle);
      //string inputsfile=strT._K+"\\"+strT._N+"-"+strT._S+"\\inputss."+strT._K;
      //handle = FileOpen(inputsfile,FILE_WRITE|FILE_COMMON);
      //FileWrite(handle,strT.str_testerSettings); FileClose(handle);
    }
   }
   LogOrAlert(reportMode,StringFormat("❌ Unable to synchronise tester settings after %d Attempts – aborting...",Attempts),strT._K,strT._N,strT._S);
   return false;
   //if(!MTTESTER::SetSettings2(strT.str_testerSettings)) {LogOrAlert(reportMode,"Error adjusting tester settings via DLL!",strT._K,strT._N,strT._S); return false;}
   //return MTTESTER::ClickStart();
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//  WRITE tester settings  →  READ back  →  VERIFY  (retry-once)
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool VerifyTesterSettings(const bool reportMode,const int MAX_ATTEMPTS = 5)
  {
   for(int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)
     {
      //--- 1) WRITE -------------------------------------------------------------------------------------------------
      if(!MTTESTER::SetSettings2(strT.str_testerSettings))
        {
         LogOrAlert(reportMode,"Error writing tester settings via DLL",strT._K,strT._N,strT._S);
         return(false);                           // cannot retry if write itself failed
        } Sleep(50);                                 // allow terminal to flush
      //--- 2) READ --------------------------------------------------------------------------------------------------
      string settingsRead = "";
      if(!MTTESTER::GetSettings2(settingsRead))
        {
         LogOrAlert(reportMode,"Error reading tester settings back via DLL",strT._K,strT._N,strT._S);
         return(false);
        } Sleep(50);
      //--- 3) PARSE -------------------------------------------------------------------------------------------------
      string                             chkExpert,chkSymbol,chkPeriod,chkOpt,chkModel,chkFrom,chkTo,chkFwdMode,chkExecMode,chkVisual;
      ExtractConfigSettings(settingsRead,chkExpert,chkSymbol,chkPeriod,chkOpt,chkModel,chkFrom,chkTo,chkFwdMode,chkExecMode,chkVisual);
      // normalise fields that may be absent when set to '0'
      if(chkOpt     == "") chkOpt     = "0";
      if(chkFwdMode == "") chkFwdMode = "0";
      if(chkVisual  == "") chkVisual  = "0";
      if(strT.Visual== "") strT.Visual= "0";   // safety
      //--- 4) COMPARE ----------------------------------------------------------------------------------------------
      bool ok = true;
      #define _VERIFY(lhs,rhs,field) if((lhs)!=(rhs)) {LogOrAlert(reportMode,"Mismatch in '"+field+"' – wrote '"+lhs+"' read '"+rhs+"'",strT._K,strT._N,strT._S); ok = false;}
      _VERIFY(strT.Expert       , chkExpert   , "Expert");
      _VERIFY(strT.symbol       , chkSymbol   , "Symbol");
      _VERIFY(strT.period_      , chkPeriod   , "Period");
      _VERIFY(strT.Optimization , chkOpt      , "Optimization");
      _VERIFY(strT.Model        , chkModel    , "Model");
      _VERIFY(strT.fromDate     , chkFrom     , "FromDate");
      _VERIFY(strT.toDate       , chkTo       , "ToDate");
      _VERIFY(strT.ForwardMode  , chkFwdMode  , "ForwardMode");
      _VERIFY(strT.ExecutionMode, chkExecMode , "ExecutionMode");
      _VERIFY(strT.Visual       , chkVisual   , "Visual");
      #undef  _VERIFY
      if(ok) return(true);                        // ✅ all settings verified
      else LogOrAlert(reportMode,"Tester Settings not adjusted – retrying...",strT._K,strT._N,strT._S);
     }
   return(false);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CompareCanonicalIni(const string iniA,const string iniB)
  {
   // --- Parse iniA into a map "Section|Key" -> "Value"
   string mapAKeys[], mapAValues[];
   int countA = 0;
   {
    string linesA[];
    int linesCountA = StringSplit(iniA,'\n',linesA);
    string currentSectionA="";
    for(int i=0; i<linesCountA; i++)
      {
       string ln=StringTrim(linesA[i]);
       if(ln=="" || ln[0]==';') continue; // skip blank or comment
       if(ln[0]=='[')
         {
          currentSectionA=ln;
          continue;
         }
       int eqPos = StringFind(ln,"=");
       if(eqPos>0)
         {
          string key=StringTrim(StringSubstr(ln,0,eqPos));
          string val=StringTrim(StringSubstr(ln,eqPos+1));
          // optionally remove "||..." if present
          int tail=StringFind(val,"||");
          if(tail>=0) val=StringSubstr(val,0,tail);
          // unify numeric "0.0" => "0", etc.
          double d = StringToDouble(val);
          if(MathAbs(d) < 0.0000001) val="0";
          else if(MathAbs(d-1.0) < 0.0000001) val="1";
          if(val=="") val="0"; // treat blank as "0"
          ArrayResize(mapAKeys,countA+1);
          ArrayResize(mapAValues,countA+1);
          mapAKeys[countA]   = currentSectionA+"|"+key; 
          mapAValues[countA] = val;
          countA++;
         }
      }
   }
   // --- Parse iniB into mapB
   string mapBKeys[], mapBValues[];
   int countB = 0;
   {
    string linesB[];
    int linesCountB = StringSplit(iniB,'\n',linesB);
    string currentSectionB="";
    for(int i=0; i<linesCountB; i++)
      {
       string ln=StringTrim(linesB[i]);
       if(ln=="" || ln[0]==';') continue;
       if(ln[0]=='[')
         {
          currentSectionB=ln;
          continue;
         }
       int eqPos = StringFind(ln,"=");
       if(eqPos>0)
         {
          string key=StringTrim(StringSubstr(ln,0,eqPos));
          string val=StringTrim(StringSubstr(ln,eqPos+1));
          int tail=StringFind(val,"||");
          if(tail>=0) val=StringSubstr(val,0,tail);
          double d = StringToDouble(val);
          if(MathAbs(d) < 0.0000001) val="0";
          else if(MathAbs(d-1.0) < 0.0000001) val="1";
          if(val=="") val="0";
          ArrayResize(mapBKeys,countB+1);
          ArrayResize(mapBValues,countB+1);
          mapBKeys[countB]   = currentSectionB+"|"+key; 
          mapBValues[countB] = val;
          countB++;
         }
      }
   }
   // --- Compare only keys that appear in both A & B
   for(int i=0; i<countA; i++)
     {
      string aKey = mapAKeys[i];
      string aVal = mapAValues[i];
      // find same key in B
      int indexB=-1;
      for(int j=0; j<countB; j++)
        {
         if(aKey==mapBKeys[j])
           { indexB=j; break; }
        }
      // if found in B, compare values
      if(indexB>=0)
        {
         if(StringCompare(aVal,mapBValues[indexB])!=0)
           {
            LogOrPrint(false,StringFormat("Mismatch in %s, loaded value is %s intended value is %s",aKey,aVal,mapBValues[indexB]),strT._K,strT._N,strT._S);
            return false;  // mismatch found
           }
        }
      // if not found in B => ignore (treat as matched)
     }
   return true;           // no mismatches found
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void ExtractConfigSettings(const string settings,string &Expert,string &symbol,string &period_,string &Optimization,string &Model,
                                       string &fromDate,string &toDate,string &ForwardMode,string &ExecutionMode,string &Visual)
{
   // Split settings into lines
   string Lines[];
   int count = StringSplit(settings, (ushort)10, Lines);
   
   bool inTesterSection = false;
   
   for(int i = 0; i < count; i++)
   {
      string line = StringTrim(Lines[i]);
      if(line == "")
         continue;
      // Check if we entered the [Tester] section
      if(StringFind(line, "[Tester]") == 0)
      {
         inTesterSection = true;
         continue;
      }
      // Check if we exited the [Tester] section
      if(StringFind(line, "[TesterInputs]") == 0)
      {
         inTesterSection = false;
         continue;
      }
      // If we are inside the [Tester] section, parse each "Key=Value"
      if(inTesterSection)
      {
         // For instance: "Expert=SomeEA.ex5"
         int pos = StringFind(line, "=");
         if(pos > 0)
         {
            string key   = StringTrim(StringSubstr(line, 0, pos));
            string value = StringTrim(StringSubstr(line, pos+1));
            
                 if(key == "Expert")   Expert        = value;
            else if(key == "Symbol")   symbol        = value;
            else if(key == "Period")   period_       = value;
            else if(key == "Optimization")  Optimization = value;
            else if(key == "Model")    Model         = value;
            else if(key == "FromDate") fromDate      = value;
            else if(key == "ToDate")   toDate        = value;
            else if(key == "ForwardMode")   ForwardMode   = value;
            else if(key == "ExecutionMode") ExecutionMode = value;
            else if(key == "Visual")   Visual        = value;
         }
      }
   }
}
string StringTrim(string str) {StringTrimLeft(str); StringTrimRight(str); return str;}
//+------------------------------------------------------------------+
//| 2) Function: ReplaceSettingsInputs                               |
//|    Replaces matching lines in the [TesterInputs] section with    |
//|    those in str_Inputs; also optionally updates the [Tester]     |
//|    section using the config variables (Expert, Symbol, etc.).    |
//+------------------------------------------------------------------+
bool ReplaceSettingsInputs(string &settings,
                           const string inputs,
                           const string expertValue,
                           const string symbolValue,
                           const string periodValue,
                           const string optimizationValue,
                           const string modelValue,
                           const string fromDateValue,
                           const string toDateValue,
                           const string forwardModeValue,
                           const string forwardDateValue,
                           const string executionModeValue,
                           const string visualValue)
  {
   // 2a) Build a map of key->newValue from inputs
   //     lines look like: "Grid_Size=-5"
   string inpLines[];
   int inpCount=StringSplit(inputs,(ushort)10,inpLines);
   
   string keys[], newValues[];
   ArrayResize(keys,inpCount);
   ArrayResize(newValues,inpCount);
   
   for(int j=0; j<inpCount; j++)
     {
      string line=StringTrim(inpLines[j]);
      if(line=="") continue;
      int eqPos=StringFind(line,"=");
      if(eqPos>0)
        {
         string k=StringTrim(StringSubstr(line,0,eqPos));
         string v=StringTrim(StringSubstr(line,eqPos+1));
         keys[j]=k;
         newValues[j]=v;
        }
     }
   // 2b) Split the big 'settings' string into lines
   string tsLines[];
   int tsCount=StringSplit(settings,(ushort)10,tsLines);
   bool inTesterSection=false;
   bool inTesterInputs=false;
   // 2c) Rebuild line by line
   for(int i=0; i<tsCount; i++)
     {
      string line=StringTrim(tsLines[i]);
      // Section headers
      if(StringFind(line,"[Tester]")==0)
        {
         inTesterSection=true;
         inTesterInputs=false;
         continue;
        }
      if(StringFind(line,"[TesterInputs]")==0)
        {
         inTesterSection=false;
         inTesterInputs=true;
         continue;
        }
      // If in [Tester] section, optionally replace or remove lines
      if(inTesterSection && line!="" && line[0]!=';')
        {
         int eqPos=StringFind(line,"=");
         if(eqPos>0)
           {
            string key=StringTrim(StringSubstr(line,0,eqPos));
            string val=StringTrim(StringSubstr(line,eqPos+1));
                 if(key=="Expert" && expertValue!="")                tsLines[i]="Expert="+expertValue;
            else if(key=="Symbol" && symbolValue!="")                tsLines[i]="Symbol="+symbolValue;
            else if(key=="Period" && periodValue!="")                tsLines[i]="Period="+periodValue;
            else if(key=="Optimization" && optimizationValue!="")    tsLines[i]="Optimization="+optimizationValue;
            else if(key=="Model" && modelValue!="")                  tsLines[i]="Model="+modelValue;
            else if(key=="FromDate" && fromDateValue!="")            tsLines[i]="FromDate="+fromDateValue;
            else if(key=="ToDate" && toDateValue!="")                tsLines[i]="ToDate="+toDateValue;
            else if(key=="ForwardMode" && forwardModeValue!="")      tsLines[i]="ForwardMode="+forwardModeValue;
            else if(key=="ExecutionMode" && executionModeValue!="")  tsLines[i]="ExecutionMode="+executionModeValue;
            else if(key=="Visual" && visualValue!="")                tsLines[i]="Visual="+visualValue;
            else if(key=="ForwardDate") // new key
              {
               if(forwardDateValue!="")                              tsLines[i]="ForwardDate="+forwardDateValue;
               else                                                  tsLines[i]="DELETELINE"; // remove if empty
              }
           }
        }
      // If in [TesterInputs] section, replace lines matching str_Inputs
      if(inTesterInputs && line!="" && line[0]!=';')
        {
         int eqPos=StringFind(line,"=");
         if(eqPos>0)
           {
            string key=StringTrim(StringSubstr(line,0,eqPos));
            string valuePart=StringTrim(StringSubstr(line,eqPos+1));
            // Check for possible "||" remainder
            string remainder="";
            int sepPos=StringFind(valuePart,"||");
            if(sepPos>=0) remainder=StringSubstr(valuePart,sepPos);
            // Compare to new values
            for(int k=0; k<inpCount; k++)
              {
               if(key==keys[k] && keys[k]!="")
                 {
                  /*if(key=="EA_Desc" && StringFind(newValues[k],"@{")>0)
                    {// append instead of replace
                     tsLines[i]=key+"="+valuePart+newValues[k]+remainder;
                    }
                  else */tsLines[i]=key+"="+newValues[k]+remainder;
                  break;
                 }
              }
           }
        }
     }
   // 2d) Reconstruct the settings string, skipping DELETELINE
   string finalSettings="";
   for(int i=0; i<tsCount; i++)
     {
      if(tsLines[i]=="DELETELINE") continue;
      finalSettings+=tsLines[i]+"\n";
     }
   settings=finalSettings;
   Print("Tester Config and Inputs Adjustments Generated.");
   return(true);
  }
//-------------------------------------------------------------------------
//  keepTop   – desired maximum records to keep
//  minARF    – minimum acceptable ARF
//  minSR     – minimum acceptable SR
//  expArr[]  – array of collected ExportRecord objects (will be modified)
//-------------------------------------------------------------------------
void SortAndTrimExports(const int keepTop,const double minARF,const double minSR,ExportRecord &expArr[])        // highest (ARF*SR) first
  {
   const int n = ArraySize(expArr);
   if(n <= 1) return;
   /* ---------- sort by ARF*SR (selection sort) ---------- */
   for(int i = 0; i < n-1; ++i)
   {
      int    best = i;
      double top  = expArr[i].arf * expArr[i].sr;
      for(int j = i+1; j < n; ++j)
      {
         double score = expArr[j].arf * expArr[j].sr;
         if(score > top) { best = j; top = score; }
      }
      if(best != i) {ExportRecord tmp = expArr[i]; expArr[i] = expArr[best]; expArr[best] = tmp;}
   }
   /* ---------- decide how many to keep ---------- */
   int passCnt = 0;                                       // # of rows passing the thresholds
   for(int i = 0; i < n && passCnt < keepTop; ++i)
   {
      if(expArr[i].arf >= minARF && expArr[i].sr >= minSR) ++passCnt;
   }
   // rule-set logic
   int keepCnt = 0;
   if(passCnt > 0) keepCnt = passCnt; // at least one row passes → keep the (≤keepTop) passing rows
   else            keepCnt = 1;       // nothing passes → keep only the very first row
   WriteLog(StringFormat("SortAndTrimExports: Total=%d Passing=%d Kept=%d Trimmed=%d",n,passCnt,keepCnt,n-keepCnt),false,strT._K,strT._N,strT._S);
   /* ---------- trim anything beyond keepCnt ---------- */
   if(n <= keepCnt) return;      // nothing to delete
   string files[];
   ArrayResize(files, 2*(n - keepCnt));
   int k = 0;
   for(int i = keepCnt; i < n; ++i)
   {
      files[k++] = expArr[i].csvFile;
      files[k++] = expArr[i].setFile;
   }
   DeleteExports(files);         // remove from disk
   ArrayResize(expArr, keepCnt); // shrink in-memory list
   PrintFormat("SortAndTrimExports: deleted %d file pairs (csv+set)",(n - keepCnt));
  }
//--------------------------------------------------------------------
//  MoveKeptExports – relocate every file that survived the trimming
//  • dstKey  … relative path under <Common\Files> (e.g.  "TEMP2\\BEST")
//  • relies on your existing  MoveExports(), EnsureCommonPath(), …
//--------------------------------------------------------------------
bool MoveKeptExports(ExportRecord &expArr[],const string dstKey)
  {
   const int n = ArraySize(expArr);
   if(n == 0) return false;                    // nothing to move
   /* ---- build flat file list ----------------------------------- */
   string files[];
   ArrayResize(files, 2 * n);
   int k = 0;
   for(int i = 0; i < n; ++i)
     {
      files[k++] = expArr[i].csvFile;
      files[k++] = expArr[i].setFile;
     }
   /* ---- move on disk ------------------------------------------- */
   if(!MoveExports(dstKey, files))            // your helper updates files[]
      return false;                           // error already printed inside
   /* ---- reflect new paths back into expArr[] ------------- */
   k = 0;
   for(int i = 0; i < n; ++i)
     {
      expArr[i].csvFile = files[k++];
      expArr[i].setFile = files[k++];
     }
   return true;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
// --- pull the “Lots=” line from a .set file (rudimentary INI reader)
string ParseSetFileForInput(const string key,const string file)
  {
   int h=FileOpen(file,FILE_READ|FILE_COMMON); if(h==INVALID_HANDLE) return("-1.0");
   const int keyLen=StringLen(key);
   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringFind(ln,key,0)==0)
      {
         string v = StringSubstr(ln,keyLen); StringTrimLeft(v); FileClose(h); return(v);
      }
   }
   FileClose(h); return("-1.0");
  }
double FetchMetric(string filename, string metric)
  {
   // 1) Strip path by finding the last '\' or '/'
   int pos = -1, last = -1;
   // scan for backslashes
   while((pos = StringFind(filename, "\\", pos + 1)) >= 0) last = pos;
   // scan for forward slashes
   pos = -1;
   while((pos = StringFind(filename, "/", pos + 1)) >= 0) last = pos;
   if(last >= 0)  filename = StringSubstr(filename, last + 1);
   // 2) Strip extension by finding the last '.'
   pos = -1; last = -1;
   while((pos = StringFind(filename, ".", pos + 1)) >= 0) last = pos;
   if(last >= 0) filename = StringSubstr(filename, 0, last);
   // 3) Split on '_' to isolate each metric token
   string parts[];
   int count = StringSplit(filename, '_', parts);
   // 4) Locate the one that begins with e.g. "PF="
   string key = metric + "=";
   for(int i = 0; i < count; i++)
   {
      if(StringFind(parts[i], key) == 0)
      {
         // grab what's after the '=' and convert
         string val = StringSubstr(parts[i], StringLen(key));
         return StringToDouble(val);
      }
   }
   // not found → return 0 (or change to NaN / error code)
   return 0.0;
  }
//+------------------------------------------------------------------+
double NormalizeLots(double lot,const string sym)
{
   double min = SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN);
   double max = SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX);
   double step= SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP);

   lot = MathMax(min,MathMin(lot,max));
   lot = MathFloor((lot+step*0.5)/step)*step;
   return(lot);
}
//+------------------------------------------------------------------+
//| Returns the most recent Friday (including today if Friday) at    |
//| 00:00, formatted as “YYYY.MM.DD”                                 |
//+------------------------------------------------------------------+
string GetLastFridayDate()
  {
   // 1) Get current server time
   datetime now = TimeCurrent();
   // 2) Break it into components
   MqlDateTime tm;
   if(!TimeToStruct(now, tm))            // decompose into tm.day_of_week etc.
      return("");                       // on error, return empty
   // 3) Normalize to today at midnight
   tm.hour = tm.min = tm.sec = 0;
   datetime today = StructToTime(tm);    // rebuild datetime from tm
   // 4) Compute how many days back to Friday
   //    day_of_week: Sunday=0 … Thursday=4, Friday=5, Saturday=6
   int dow      = tm.day_of_week;
   int daysBack = (dow >= 5 ? dow - 5 : dow + 2);
   // 5) Subtract that many days
   datetime lastFri = today - daysBack * 24 * 3600;
   // 6) Format as date-only string
   return TimeToString(lastFri, TIME_DATE);  // YYYY.MM.DD
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//  EnsureCommonPath – create every level of Common\Files\<relDir>
//--------------------------------------------------------------------
void EnsureCommonPath(const string relDir)
  {
   if(relDir=="") return;
   string part="";
   for(int i=0;i<StringLen(relDir);i++)
     {
      uchar ch=(uchar)StringGetCharacter(relDir,i);
      if(ch=='\\')
        {
         if(part!="") FolderCreate(part,FILE_COMMON);
        }
      part+=CharToString(ch);
     }
   FolderCreate(relDir,FILE_COMMON);      // final leaf
  }
//-------------- helper: does this filename look like a finished export? -----
bool IsExportFile(const string fname)
  {
   // all metrics must exist
   return (StringFind(fname,"_Trds=")  != -1 &&
           StringFind(fname,"_Prf=")   != -1 &&
           StringFind(fname,"_PF=")    != -1 &&
           StringFind(fname,"_DD=")    != -1);
  }
//-------------- recursive collector (unchanged except for the filter) -------
bool WalkKey(const string folder,string &arr[])
  {
   string filter = folder + "\\*";
   string ent    = "";
   long   h      = FileFindFirst(filter, ent, FILE_COMMON);
   if(h == INVALID_HANDLE) return false;
   
   bool any = false;
   do{
       string path = folder + "\\" + ent;
       ResetLastError();
       FileIsExist(path, FILE_COMMON);

       if(GetLastError() == ERR_FILE_IS_DIRECTORY)    any |= WalkKey(path, arr);            // recurse
       else{
          // extract bare filename for the filter test
          int lastSep = StringFind(path,"\\",StringLen(path)-1);
          string fname = (lastSep==-1)?path:StringSubstr(path,lastSep+1);

          if(IsExportFile(fname)){
             int n = ArraySize(arr);
             ArrayResize(arr, n+1);
             arr[n] = path;                     // store relative path
             any = true;
          }
       }
     }while(FileFindNext(h, ent));
   FileFindClose(h);
   return any;
  }
//-------------- public wrapper (same API) -----------------------------------
bool FindExports(const string srcKey,string &out[])
  {
   ArrayResize(out,0);
   return WalkKey(srcKey,out);                 // true  ⇨ at least 1 file kept
  }
//--------------------------------------------------------------------
//  MoveExports – move list collected from Key1 to Key2 (any depth)
//--------------------------------------------------------------------
bool MoveExports(const string dstKey,string &files[])
  {
   bool ok=true;
   for(int i=0;i<ArraySize(files);i++)
     {
      string src=files[i];                        // Key1\...\file
      // Relative part after first '\'
      int sep=StringFind(src,"\\");
      string rel=(sep==-1)?src:StringSubstr(src,sep+1);
      string dst=dstKey+"\\"+rel;                 // Key2\...\file
      /* --- build directory part of dst and create it --- */
      int lastSep=StringLen(dst)-1;
      while(lastSep>=0 && StringGetCharacter(dst,lastSep)!='\\') lastSep--;
      string dstDir=(lastSep>0)?StringSubstr(dst,0,lastSep):"";
      EnsureCommonPath(dstDir);
      // remove existing file to avoid "already open"
      if(FileIsExist(dst,FILE_COMMON)) FileDelete(dst,FILE_COMMON);
      if(!FileMove(src,FILE_COMMON,dst,FILE_COMMON|FILE_REWRITE))
      {
       if(GlobalVariableGet("BatchOnGoing")!=0) WriteLog("❌ Move failed: "+FileErrorString(GetLastError()),false,strT._K,strT._N,strT._S);
       Print("Move failed: ",src," → ",dst," err=",GetLastError()); ok=false;}
      else files[i]=dst;                            // update array
     }
   return ok;
  }
//+------------------------------------------------------------------+
bool DeleteExports(string &files[])
  {
   bool ok=true;
   for(int i=0;i<ArraySize(files);i++)
      if(!FileDelete(files[i],FILE_COMMON))
        {if(GlobalVariableGet("BatchOnGoing")!=0) WriteLog("❌ Delete failed: "+FileErrorString(GetLastError())+": "+files[i],false,strT._K,strT._N,strT._S);
         Print("Delete failed: ",files[i]," err=",GetLastError()); ok=false;}
   return ok;
  }
//+------------------------------------------------------------------+
//| DeleteEmptyFolders                                                |
//| Recursively removes every empty sub‑folder under Common\Files\<keyFolder>.
//| If <keyFolder> itself becomes empty after the cleanup, it is deleted as well.                                          |
//| Returns true if the folder passed in *was* deleted,               |
//| false if it still contains at least one file after the scan.      |
//+------------------------------------------------------------------+
bool DeleteEmptyFolders(const string keyFolder)
  {
   string filter = keyFolder + "\\*";
   string entry  = "";
   long   h      = FileFindFirst(filter, entry, FILE_COMMON);
   bool   hasContent = false;              // assume empty until proven otherwise
   
   if(h != INVALID_HANDLE)
     {
      do{
         string path = keyFolder + "\\" + entry;
         ResetLastError();
         FileIsExist(path, FILE_COMMON);
         if(GetLastError() == ERR_FILE_IS_DIRECTORY)
           {
            // Recurse into sub‑directory; if it is emptied it deletes itself.
            if(!DeleteEmptyFolders(path))    hasContent = true;   // sub‑folder still contains something
           }
         else                                hasContent = true;   // regular file found
        }
      while(FileFindNext(h, entry));
      FileFindClose(h);
     }
   // If nothing left, remove this directory as well.
   if(!hasContent)
     {
      FolderDelete(keyFolder, FILE_COMMON); Sleep(50);
      return true;                         // this folder removed
     }
   // else Sleep(50);
   return false;                           // kept because it still had content
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//+------------------------------------------------------------------+
//| Return human-readable text for MQL5 file-related runtime errors  |
//+------------------------------------------------------------------+
string FileErrorString(const int err)
{
   switch(err)
   {
      /* --- File operations --------------------------------------- */
      case ERR_TOO_MANY_FILES       : return "More than 64 files are already open";
      case ERR_WRONG_FILENAME       : return "Invalid file name";
      case ERR_TOO_LONG_FILENAME    : return "File name is too long";
      case ERR_CANNOT_OPEN_FILE     : return "Could not open or create the file";
      case ERR_FILE_CACHEBUFFER_ERROR: return "Not enough memory for file cache";
      case ERR_CANNOT_DELETE_FILE   : return "Unable to delete file";
      case ERR_INVALID_FILEHANDLE   : return "File handle is invalid or already closed";
      case ERR_WRONG_FILEHANDLE     : return "Wrong file handle";
      case ERR_FILE_NOTTOWRITE      : return "File must be opened for writing";
      case ERR_FILE_NOTTOREAD       : return "File must be opened for reading";
      case ERR_FILE_NOTBIN          : return "File must be opened in binary mode";
      case ERR_FILE_NOTTXT          : return "File must be opened in text mode";
      case ERR_FILE_NOTTXTORCSV     : return "File must be opened as text or CSV";
      case ERR_FILE_NOTCSV          : return "File must be opened as CSV";
      case ERR_FILE_READERROR       : return "File read error";
      case ERR_FILE_BINSTRINGSIZE   : return "String size must be specified (binary file)";
      case ERR_INCOMPATIBLE_FILE    : return "Incompatible file type";
      case ERR_FILE_IS_DIRECTORY    : return "This is a directory, not a file";
      case ERR_FILE_NOT_EXIST       : return "File does not exist";
      case ERR_FILE_CANNOT_REWRITE  : return "File cannot be rewritten";
      case ERR_WRONG_DIRECTORYNAME  : return "Invalid directory name";
      case ERR_DIRECTORY_NOT_EXIST  : return "Directory does not exist";
      case ERR_FILE_ISNOT_DIRECTORY : return "This is a file, not a directory";
      case ERR_CANNOT_DELETE_DIRECTORY: return "Directory cannot be removed";
      case ERR_CANNOT_CLEAN_DIRECTORY : return "Directory cleanup failed";
      case ERR_FILE_WRITEERROR      : return "File write error";
      case ERR_FILE_ENDOFFILE       : return "CSV read reached end of file";
      /* --- fall-back ---------------------------------------------- */
      default                       : return "Cannot find File function error type"; // built-in helper
   }
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
//==============================================================================
//  Helper – trim CR characters and trailing whitespace so clipboard–echo
//  comparisons are immune to “\r\n” vs “\n” or stray spaces.
//==============================================================================
/*string NormalizeIni(string ini)
{
   StringReplace(ini, "\r", "");              // keep only '\n'
   // right–trim
   while(StringLen(ini) &&
        (ini[StringLen(ini)-1]=='\n' || ini[StringLen(ini)-1]==' ' ))
         StringSetCharacter(ini, StringLen(ini)-1, 0);
   return ini;
}
//------------------------------------------------------------------------------
// CanonicalIni()  – normalises an .ini string for logic-only comparison
// • Keeps only   Section|key=value            (order-insensitive)
//  • treats missing Visual / Optimization / ForwardMode as "key=0"
// • Strips       whitespace, blank lines, “|| …” metadata tails
// • Skips        comment lines starting with ‘;’
// • Treats       missing/empty value as “0”   (MT5 omits flags when they are 0)
//------------------------------------------------------------------------------
string CanonicalIni(const string iniRaw)
  {
   string liness[];
   int cnt = StringSplit(iniRaw, (ushort)10, liness);
   string canonLines[];          // dynamic
   int    outCnt         = 0;
   string currentSection = "";
   for(int i = 0; i < cnt; i++)
     {
      string ln = StringTrim(liness[i]);
      if(ln == "")      continue;          // blank
      if(ln[0] == ';')  continue;          // comment
      if(ln[0] == '[')                     // section header
        { currentSection = ln; continue; }
      int eq = StringFind(ln, "=");
      if(eq <= 0)       continue;          // malformed
      string key   = StringTrim(StringSubstr(ln, 0, eq));
      string value = StringTrim(StringSubstr(ln, eq + 1));
      // Strip metadata tail “|| …”
      int tail = StringFind(value, "||");
      if(tail >= 0)  value = StringSubstr(value, 0, tail);
      // Collapse numeric variants (0.0 → 0, 1.00 → 1)
      double d = StringToDouble(value);
      if(StringTrim(DoubleToString(d, 8)) == "0") value = "0";
      else if(StringTrim(DoubleToString(d, 8)) == "1") value = "1";
      if(value == "") value = "0";        // absent-means-zero
      ArrayResize(canonLines, outCnt + 1);
      canonLines[outCnt++] = currentSection + "|" + key + "=" + value;
     }
   SortStrings(canonLines, outCnt);
   string canon = "";
   for(int j = 0; j < outCnt; j++) canon += canonLines[j] + "\n";
   return canon;
  }
void SortStrings(string &arr[], const int n)
  {
   for(int i = 0; i < n - 1; i++)
     {
      for(int j = i + 1; j < n; j++)
        {
         if(StringCompare(arr[i], arr[j]) > 0)   // arr[i] > arr[j] ?
           {
            string tmp = arr[i];
            arr[i] = arr[j];
            arr[j] = tmp;
           }
        }
     }
  }*/
//----------------------------------------------------------------------------------------------------------------------------------------------------
