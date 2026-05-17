#include <ControlsPlus\WndClient.mqh>
#include <ControlsPlus\Dialog.mqh>
#include <ControlsPlus\Label.mqh>
#include <ControlsPlus\Edit.mqh>
#include <ControlsPlus\Button.mqh>
#include <Controls\Rect.mqh>
#include <ControlsPlus\BmpButton.mqh>
#include <ControlsPlus\ComboBox.mqh>
#include <ControlsPlus\DatePicker.mqh>
#include <ControlsPlus\CheckBox.mqh>
//#include "GOATdefinitions.mqh"
#include "Tester.mqh"
#include "NewsBiasFilter.mqh"

// === PRESETS: map display-name -> actual file (with .txt)  // NEW
string g_PresetDisplayNames[];
string g_PresetFileNames[];

// ShellExecute to open the presets folder                      // NEW
#import "shell32.dll"
int ShellExecuteW(int hwnd, string lpOperation, string lpFile, string lpParameters, string lpDirectory, int nShowCmd);
#import
//----------------------------------------------------------------------------------------------------------------------------------------------------
class CStrategyTesterDialog : public CAppDialog
{
//private:
public:
   CWndClient  c_Wnd_OPT,c_Wnd_Export;
   CLabel      m_lblHeading,m_lblExport;
   CLabel      m_lblRunName;
   CEdit       m_edtRunName;
   // (0) "Set File:" at top
   CEdit       m_edtSetFile;
   CLabel      m_lblStrategy;
   CEdit       m_edtStrategy;
   // (1) Expert
   CLabel      m_lblExpert;
   CComboBox   m_cmbExpert;
   // (2) Symbol
   CLabel      m_lblSymbol;
   CComboBox   m_cmbSymbol;
   // The now unlabeled "Period" combo to the right of Symbol
   CComboBox   m_cmbPeriod;
   // (4) Date Range (two labels, pickers later)
   CLabel      m_lblDateFrom;
   CLabel      m_lblDateTo;
   CDatePicker m_dtFrom;
   CDatePicker m_dtTo;
   // (5) Forward
   CLabel      m_lblForward;
   CComboBox   m_cmbForward;
   CDatePicker m_dtForward;
   // (6) Delays
   CLabel      m_lblDelay;
   CComboBox   m_cmbDelay;
   // (7) Modeling
   CLabel      m_lblModeling;
   CComboBox   m_cmbModel;
   // (8) Deposit, Currency(Edit), Leverage
   CLabel      m_lblDeposit;
   CEdit       m_edtDeposit;
   CEdit       m_edtCurrency;   // changed from combo to edit
   CComboBox   m_cmbLeverage;
   // (9) Optimization
   CLabel      m_lblOptimization;
   CComboBox   m_cmbOptimization;
   // RIGHT SIDE
   CLabel      m_lblQueue;//,m_lblStatus;
   CEdit       m_edtQueue[10],m_edtBatchProgress;//,m_edtStatus[10];
   CListView   m_listQueue;
   // Single button
   CButton     m_btnSelectFile,m_btnAddQueue,m_btnSetPresets,m_btnDelQ,m_btnDelQitem,m_btnUpQitem,m_btnDownQitem,m_btnCancelSelected,m_btnMakePending,m_btnStart,m_btnStop;
// Export Settings extra objects
   CLabel      m_lblSetsToExport,m_lblBackOOSDate,m_lblMinScore,m_lblMinARF,m_lblAdjustLots,m_lblMinSR,m_lblTargetDD,m_lblVerifyOOS,m_lblDataSync;
   CEdit       m_edtSetsToExport                 ,m_edtMinScore,m_edtMinARF                ,m_edtMinSR,m_edtTargetDD;
   CCheckBox   m_chkAdjustLots,m_chkVerifyOOS;
   
   CDatePicker m_dpBackOOS,m_dpFwdOOS;
   CButton     m_btnSyncBias,m_btnViewBias,m_btnSyncNews;
   // Layout parameters
   int         m_leftMargin,m_topMargin,m_labelWidth,m_GapHoriz,m_rowHeight,m_controlHeight,m_controlWidth;
   // Storing positions for date pickers so we can create them last
   int         m_xFrom, m_yFrom;
   int         m_xTo,   m_yTo;
   int         m_xForwardDt, m_yForwardDt;

   string Path_RunFolder,Path_QueueBatch,Path_QueueStrategy,Path_ExportSettings,Key_,EA_Name_,Server_,m_selectedSetPath;
   int D_Width,D_Height,Font_Size;
   bool m_dataSyncBusy,m_compactLayout,m_batchRunning;
 //color clr_CaptionBack,clr_CaptionBorder,clr_ClientBack,clr_ClientBorder,clr_Text;
   
   CStrategyTesterDialog();
  ~CStrategyTesterDialog();

   virtual bool   Create(const long chart_id, const string name,const int subwin,const int x1,const int y1,const int x2,const int y2);
   void           SetFlags(const string _Key_,const string _EA_Name_,const string _Server_,const int _Font_Size_,const int D_Width_,const int D_Height_);
   virtual bool   OnEvent(const int id, const long &lparam,const double &dparam, const string &sparam);
   void           SetCaptionClientColors();
   void           maximizeWindow();
   void           minimizeWindow();
   string         GetTESTERsettingsString(bool header);
   string         GetExportSettingsString(void);
   void           AddQueueSingle(void);   // ← NEW: extracted single-item logic
   void           OnClickSelectFile(void);
   void           OnClickAddQueue(void);
   void           OnClickSetPresets(void);
   void           OnClickDelQ(void);
   void           OnClickDelQitem(void);
   void           OnClickUpSelectedItem(void);
   void           OnClickDownSelectedItem(void);
   void           OnClickCancelSelectedItem(void);                // current line  →  Cancelled
   void           OnClickMakeSelectedPending(void);               // current line  →  Pending
   void           OnClickRefresh(bool init,bool select);
   void           OnClickSyncBias(void);
   void           OnClickViewBias(void);
   void           OnClickSyncNews(void);
   void           RefreshNewsSyncButton(void);
   void           RefreshBatchStartButtonState(void);
   void           UpdateBatchProgressText(void);
   void           OnClickStart(void);
   void           OnClickStop(void);
   void           ChangeItemTo(const int index,const string state); // generic state swapper
   //void           WriteLog(string text,bool print,string Key_,string EA_Name_,string Server_);
   //bool           UpdateBatchQueueAndWriteConfigFile(bool init)
private:
   void RefreshRunPaths(void);
   bool EnsureRunContext(const bool forceNew=false,const string runNameOverride="");
   bool SaveCurrentBatchPackage(void);
   bool LoadBatchPackage(const string packagePath);
   bool ApplyBatchTimelineAdjustment(string &queueContent,string &exportSettings,const string sourceRunPath);
   string BuildBatchInputsPackage(const string queueContent);
   bool RestoreBatchInputsPackage(const string packageBody);
   void ApplyExportSettingsToControls(const string exportSettings);
   bool SaveStrategyInputsFromSet(const string setPath,string &savedStrategy);
   bool EnsureInputsForStrategy(const string strategy,string &message);
   bool PreflightQueueInputs(const string queueContent,string &message);
   string BuildQueueTitle(const string state,const string symbol,const string period,const string fromDate,const string toDate,const string model,const string strategy);
   string BuildReportValue(const string strategy,const string symbol,const string period,const string fromDate,const string toDate,const string forwardDateText);
   bool RewriteQueueItemTimeline(string &item,const int mode,const datetime commonFrom,const datetime commonTo,const datetime oldEarliest,const datetime rollingAnchor);
   bool HasActiveBatchQueueItem(void);
   bool ResolveBatchRunningState(const bool clearStale);
   // Helper creation methods
   void CreateLabel(CLabel &lbl, const string text, int x, int y, int width=130);
   void CreateCombo(CComboBox &cmb, const string name, int x, int y, int width=160);
   void CreateDatePick(CDatePicker &dtp, const string name, int x, int y, int width=160);
   void CreateEditBox(CEdit &edt, const string name, int x, int y, int width=60, string def="");
   void CreateButtonCtrl(CButton &btn, const string name, int x, int y, int width, int height, string caption);
   void CreateListView(CListView &listV, const string name, int x, int y, int width, int height, string caption);
   bool ReadNewsHistoryRange(const string file_name,datetime &earliest_event_time,datetime &latest_event_time);
   bool ReadBiasHistoryFileStats(const string asset,SBiasAssetSyncResult &result);
   void BuildBiasHistoryStatus(SBulkBiasSyncResult &result);
   void ShowBiasHistorySummary(const SBulkBiasSyncResult &result);
   // Child control event handlers
   void OnDateFromChanged(void);
   void OnDateToChanged(void);
   void OnDateForwardChanged(void);
   void OnChange_cmbForward(void);
   // --- queue-item -> GUI synchronisation ---
   void           OnSelectQueueItem(void);
   //bool           ComboSelectByText(CComboBox &cmb,const string txt);   // helper
};
//+------------------------------------------------------------------+
EVENT_MAP_BEGIN(CStrategyTesterDialog)
  ON_EVENT(ON_CHANGE, m_dtFrom       ,OnDateFromChanged)
  ON_EVENT(ON_CHANGE, m_dtTo         ,OnDateToChanged)
  ON_EVENT(ON_CHANGE, m_dtForward    ,OnDateForwardChanged)
  ON_EVENT(ON_CHANGE, m_cmbForward   ,OnChange_cmbForward)
  ON_EVENT(ON_CHANGE, m_listQueue    ,OnSelectQueueItem)
  ON_EVENT(ON_CLICK,  m_btnSelectFile,OnClickSelectFile)
  ON_EVENT(ON_CLICK,  m_btnAddQueue  ,OnClickAddQueue)
  ON_EVENT(ON_CLICK,  m_btnSetPresets,OnClickSetPresets)
  ON_EVENT(ON_CLICK,  m_btnDelQ      ,OnClickDelQ)
  ON_EVENT(ON_CLICK,  m_btnDelQitem  ,OnClickDelQitem)
  ON_EVENT(ON_CLICK,  m_btnUpQitem   ,OnClickUpSelectedItem)     // ← ADD
  ON_EVENT(ON_CLICK,  m_btnDownQitem ,OnClickDownSelectedItem)   // ← ADD
//ON_EVENT(ON_CLICK,  m_btnRefresh   ,OnClickRefresh)
  ON_EVENT(ON_CLICK,  m_btnCancelSelected ,OnClickCancelSelectedItem)
  ON_EVENT(ON_CLICK,  m_btnMakePending ,OnClickMakeSelectedPending)
  ON_EVENT(ON_CLICK,  m_btnSyncBias ,OnClickSyncBias)
  ON_EVENT(ON_CLICK,  m_btnViewBias ,OnClickViewBias)
  ON_EVENT(ON_CLICK,  m_btnSyncNews ,OnClickSyncNews)
  ON_EVENT(ON_CLICK,  m_btnStart ,OnClickStart)
  ON_EVENT(ON_CLICK,  m_btnStop ,OnClickStop)
EVENT_MAP_END(CAppDialog)
//+------------------------------------------------------------------+
CStrategyTesterDialog::CStrategyTesterDialog()
{
   m_dataSyncBusy = false;
   m_compactLayout = false;
   m_batchRunning = false;
}
CStrategyTesterDialog::~CStrategyTesterDialog()
{
   // Typically Destroy is called in OnDeinit
}
void CStrategyTesterDialog::maximizeWindow(void)   {this.Maximize();}
void CStrategyTesterDialog::minimizeWindow(void)   {this.Minimize();}

void CStrategyTesterDialog::SetFlags(const string _Key_,const string _EA_Name_,const string _Server_,const int _Font_Size_,const int D_Width_,const int D_Height_)
{
   Key_=_Key_; EA_Name_=_EA_Name_; Server_=_Server_; Font_Size=_Font_Size_; D_Width=D_Width_; D_Height=D_Height_;
   RefreshRunPaths();
   News.Key_ = Key_;
   Bias.Key_ = Key_;
}
CEdit CaptionObjTester;
CStrategyTesterDialog TesterDialog;

string n_Expert,Strategy="",TesterInputs="";
//+------------------------------------------------------------------+
string GoatOptExtractSection(const string text,const string startTag,const string endTag)
  {
   int start=StringFind(text,startTag,0);
   if(start<0) return "";
   start+=StringLen(startTag);
   if(start<StringLen(text) && StringGetCharacter(text,start)=='\r') start++;
   if(start<StringLen(text) && StringGetCharacter(text,start)=='\n') start++;
   int end=StringFind(text,endTag,start);
   if(end<0) end=StringLen(text);
   string out=StringSubstr(text,start,end-start);
   StringTrimLeft(out);
   StringTrimRight(out);
   return out;
  }
//+------------------------------------------------------------------+
string GoatOptQueueValue(const string item,const string key)
  {
   string opt_lines[];
   int total=StringSplit(item,'\n',opt_lines);
   string prefix=key+"=";
   for(int i=0;i<total;++i)
   {
      string line=opt_lines[i];
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringFind(line,prefix,0)==0)
         return StringSubstr(line,StringLen(prefix));
   }
   return "";
  }
//+------------------------------------------------------------------+
string GoatOptSetIniValue(string text,const string key,const string value)
  {
   string opt_lines[];
   int total=StringSplit(text,'\n',opt_lines);
   string prefix=key+"=";
   bool changed=false;
   string out="";
   for(int i=0;i<total;++i)
   {
      string line=opt_lines[i];
      string trimmed=line;
      StringTrimLeft(trimmed);
      StringTrimRight(trimmed);
      if(StringFind(trimmed,prefix,0)==0)
      {
         line=prefix+value;
         changed=true;
      }
      out+=(out=="" ? "" : "\r\n")+line;
   }
   if(!changed) out+=(out=="" ? "" : "\r\n")+prefix+value;
   return out;
  }
//+------------------------------------------------------------------+
string GoatOptForwardTextFromMode(const string mode)
  {
        if(mode=="1") return "1/2";
   else if(mode=="2") return "1/3";
   else if(mode=="3") return "1/4";
   else if(mode=="4") return "Custom";
   return "No";
  }
//+------------------------------------------------------------------+
string GoatOptModelShortFromCode(const string model)
  {
        if(model=="2") return "OP";
   else if(model=="1") return "OHLC";
   else if(model=="0") return "ET";
   else if(model=="4") return "ETWRT";
   return model;
  }
//+------------------------------------------------------------------+
bool GoatOptCopyCommonTextTree(const string src,const string dst)
  {
   string entry="";
   long h=FileFindFirst(src+"\\*",entry,FILE_COMMON);
   if(h==INVALID_HANDLE) return false;
   bool ok=true;
   GoatOptEnsureCommonFolderTree(dst);
   do
   {
      string srcPath=src+"\\"+entry;
      string dstPath=dst+"\\"+entry;
      ResetLastError();
      FileIsExist(srcPath,FILE_COMMON);
      if(GetLastError()==ERR_FILE_IS_DIRECTORY)
      {
         if(!GoatOptCopyCommonTextTree(srcPath,dstPath)) ok=false;
      }
      else
      {
         string body=GoatOptReadTextFile(srcPath);
         if(!GoatOptWriteTextFile(dstPath,body)) ok=false;
      }
   }
   while(FileFindNext(h,entry));
   FileFindClose(h);
   return ok;
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::RefreshRunPaths(void)
  {
   Path_RunFolder      = GoatOptCurrentRunPath(EA_Name_,Server_);
   Path_QueueBatch     = GoatOptQueuePath(EA_Name_,Server_);
   Path_ExportSettings = GoatOptExportSettingsPath(EA_Name_,Server_);
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::EnsureRunContext(const bool forceNew=false,const string runNameOverride="")
  {
   string runName=runNameOverride;
   if(runName=="")
   {
      runName=m_edtRunName.Text();
      StringTrimLeft(runName);
      StringTrimRight(runName);
   }
   if(runName=="" || runName==" ") runName="Optimization Run";
   if(forceNew || GoatOptCurrentRunPath(EA_Name_,Server_)=="")
      Path_RunFolder=GoatOptCreateRunPath(EA_Name_,Server_,runName);
   RefreshRunPaths();
   if(Path_RunFolder=="") return false;
   GoatOptEnsureCommonFolderTree(Path_RunFolder);
   GoatOptEnsureCommonFolderTree(Path_RunFolder+"\\inputs");
   GoatOptEnsureCommonFolderTree(Path_RunFolder+"\\reports");
   GoatOptEnsureCommonFolderTree(Path_RunFolder+"\\exports");
   GoatOptEnsureCommonFolderTree(Path_RunFolder+"\\deploy");
   if(m_edtRunName.Text()=="" || m_edtRunName.Text()==" ") m_edtRunName.Text(GoatOptSafePathPart(runName));
   return true;
  }
//+------------------------------------------------------------------+
string CStrategyTesterDialog::BuildQueueTitle(const string state,const string symbol,const string period,const string fromDate,const string toDate,const string model,const string strategy)
  {
   return ";"+state+"_"+symbol+","+period+" "+fromDate+"-"+toDate+"_"+GoatOptModelShortFromCode(model)+":"+strategy+";";
  }
//+------------------------------------------------------------------+
string CStrategyTesterDialog::BuildReportValue(const string strategy,const string symbol,const string period,const string fromDate,const string toDate,const string forwardDateText)
  {
   string reportName=EA_Name_+" "+symbol+","+period+" "+fromDate+"-"+toDate+"_("+forwardDateText+").xml";
   string rel=GoatOptReportPath(EA_Name_,Server_,strategy,symbol,reportName);
   return "MQL5\\Files\\"+rel;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::RewriteQueueItemTimeline(string &item,const int mode,const datetime commonFrom,const datetime commonTo,const datetime oldEarliest,const datetime rollingAnchor)
  {
   string symbol=GoatOptQueueValue(item,"Symbol");
   string period=GoatOptQueueValue(item,"Period");
   string model =GoatOptQueueValue(item,"Model");
   string fmode =GoatOptQueueValue(item,"ForwardMode");
   string strategy=QueueItemStrategyName(item);
   datetime oldFrom=StringToTime(GoatOptQueueValue(item,"FromDate"));
   datetime oldTo  =StringToTime(GoatOptQueueValue(item,"ToDate"));
   datetime oldForward=StringToTime(GoatOptQueueValue(item,"ForwardDate"));
   if(symbol=="" || period=="" || strategy=="" || oldFrom<=0 || oldTo<=oldFrom) return false;

   datetime newFrom=oldFrom;
   datetime newTo=oldTo;
   if(mode==1)
   {
      newFrom=commonFrom;
      newTo=commonTo;
   }
   else if(mode==2)
   {
      int offset=(oldEarliest>0 ? (int)(oldFrom-oldEarliest) : 0);
      int duration=(int)(oldTo-oldFrom);
      newFrom=commonFrom+offset;
      newTo=newFrom+duration;
   }
   else if(mode==3)
   {
      newTo=commonTo;
   }
   else if(mode==4)
   {
      newTo=rollingAnchor;
      newFrom=newTo-730*86400;
      fmode="4";
   }
   if(newTo<=newFrom) return false;

   string fromDate=TimeToString(newFrom,TIME_DATE);
   string toDate=TimeToString(newTo,TIME_DATE);
   string forwardDateText="No Forward";
   string forwardDateLine="";
   if(mode==4)
   {
      datetime rollingForward=newTo-183*86400;
      if(rollingForward<=newFrom) rollingForward=newFrom+(newTo-newFrom)/2;
      forwardDateLine=TimeToString(rollingForward,TIME_DATE);
      forwardDateText=forwardDateLine;
      fmode="4";
   }
   else if(fmode=="4")
   {
      datetime custom=m_dtForward.Value();
      if(mode==2 && oldForward>0) custom=oldForward+(newFrom-oldFrom);
      else if(mode==3 && oldForward>0) custom=oldForward;
      if(custom<=newFrom || custom>=newTo) custom=newFrom+(newTo-newFrom)/2;
      forwardDateLine=TimeToString(custom,TIME_DATE);
      forwardDateText=forwardDateLine;
   }
   else if(fmode=="1" || fmode=="2" || fmode=="3")
   {
      string forwardModeText=GoatOptForwardTextFromMode(fmode);
      forwardDateText=TimeToString(GetForwardD(newFrom,newTo,forwardModeText),TIME_DATE);
   }

   string opt_lines[];
   int total=StringSplit(item,'\n',opt_lines);
   string out="";
   bool wroteForwardDate=false;
   for(int i=0;i<total;++i)
   {
      string line=opt_lines[i];
      StringTrimRight(line);
      string trimmed=line;
      StringTrimLeft(trimmed);
      StringTrimRight(trimmed);
      if(i==0 && StringFind(trimmed,";",0)==0)
         line=BuildQueueTitle("Pending",symbol,period,fromDate,toDate,model,strategy);
      else if(StringFind(trimmed,"FromDate=",0)==0)
         line="FromDate="+fromDate;
      else if(StringFind(trimmed,"ToDate=",0)==0)
         line="ToDate="+toDate;
      else if(StringFind(trimmed,"ForwardMode=",0)==0)
      {
         line="ForwardMode="+fmode;
         if(fmode=="4" && forwardDateLine!="")
         {
            out+=(out=="" ? "" : "\r\n")+line;
            out+="\r\nForwardDate="+forwardDateLine;
            wroteForwardDate=true;
            continue;
         }
      }
      else if(StringFind(trimmed,"ForwardDate=",0)==0)
      {
         if(fmode=="4" && !wroteForwardDate)
         {
            line="ForwardDate="+forwardDateLine;
            wroteForwardDate=true;
         }
         else continue;
      }
      else if(StringFind(trimmed,"Report=",0)==0)
         line="Report="+BuildReportValue(strategy,symbol,period,fromDate,toDate,forwardDateText);
      out+=(out=="" ? "" : "\r\n")+line;
   }
   item=out;
   return true;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::ApplyBatchTimelineAdjustment(string &queueContent,string &exportSettings,const string sourceRunPath)
  {
   string rows[];
   int total=StringSplit(queueContent,(ushort)31,rows);
   if(total<=0) return false;

   datetime oldEarliest=0;
   for(int i=0;i<total;++i)
   {
      datetime d=StringToTime(GoatOptQueueValue(rows[i],"FromDate"));
      if(d>0 && (oldEarliest==0 || d<oldEarliest)) oldEarliest=d;
   }

   int mode=1;
   int ret=MessageBox("Loaded portfolio batch:\n"+sourceRunPath+
                      "\n\nUse the visible Optimization Studio Date from / Date to / Forward controls to adjust the batch timeline?\n\n"+
                      "Yes = Rebuild Common Range\nNo = More timeline modes\nCancel = Keep Original Dates",
                      "Batch Timeline Adjuster",MB_YESNOCANCEL|MB_ICONQUESTION);
   if(ret==IDCANCEL) mode=0;
   else if(ret==IDNO)
   {
      int ret2=MessageBox("Choose alternate timeline mode:\n\n"+
                          "Yes = Shift Timeline to current Date from\n"+
                          "No = Extend End Date to current Date to\n"+
                          "Cancel = Rolling Window, 24M optimization + 6M forward ending at current Date to",
                          "Batch Timeline Adjuster",MB_YESNOCANCEL|MB_ICONQUESTION);
      if(ret2==IDYES) mode=2;
      else if(ret2==IDNO) mode=3;
      else mode=4;
   }

   datetime commonFrom=m_dtFrom.Value();
   datetime commonTo=m_dtTo.Value();
   datetime rollingAnchor=commonTo;
   if(mode!=0 && commonTo<=commonFrom)
   {
      MessageBox("Invalid timeline: Date to must be after Date from.","Timeline Error",MB_OK|MB_ICONERROR);
      return false;
   }

   string rebuilt="";
   for(int i=0;i<total;++i)
   {
      string item=rows[i];
      StringTrimLeft(item);
      StringTrimRight(item);
      if(item=="") continue;
      if(mode!=0 && !RewriteQueueItemTimeline(item,mode,commonFrom,commonTo,oldEarliest,rollingAnchor))
      {
         MessageBox("Unable to rewrite one queue item timeline. Batch load aborted.","Timeline Error",MB_OK|MB_ICONERROR);
         return false;
      }
      else if(mode==0)
      {
         string parts[];
         if(StringSplit(item,';',parts)==3)
         {
            int pos=StringFind(parts[1],"_",0);
            if(pos>=0) item=";Pending"+StringSubstr(parts[1],pos)+";"+parts[2];
         }
      }
      rebuilt+=(rebuilt=="" ? "" : "\r\n")+item+CharToString(31);
   }
   queueContent=rebuilt;

   bool includeBackOOS=(StringToInteger(GoatOptReadIniValue(exportSettings,"IncludeBackOOS"))!=0);
   if(includeBackOOS && (mode==1 || mode==2 || mode==4))
   {
      string backOOS=GoatOptReadIniValue(exportSettings,"BackOOSDate");
      if(backOOS!="")
      {
         datetime oldBack=StringToTime(backOOS);
         if(oldBack>0 && oldEarliest>0 && oldBack>=oldEarliest)
         {
            MessageBox("Invalid Back OOS date: Back OOS must be before the optimization start.","Timeline Error",MB_OK|MB_ICONERROR);
            return false;
         }
         datetime newBack=commonFrom;
         if(oldBack>0 && oldEarliest>0) newBack=oldBack+(commonFrom-oldEarliest);
         if(newBack>=commonFrom)
         {
            MessageBox("Invalid adjusted Back OOS date: Back OOS must be before the optimization start.","Timeline Error",MB_OK|MB_ICONERROR);
            return false;
         }
         exportSettings=GoatOptSetIniValue(exportSettings,"BackOOSDate",TimeToString(newBack,TIME_DATE));
      }
   }
   return true;
  }
//+------------------------------------------------------------------+
string CStrategyTesterDialog::BuildBatchInputsPackage(const string queueContent)
  {
   string out="[GOAT_INPUTS]\r\n";
   string seen=";";
   string queueItems[];
   int total=StringSplit(queueContent,(ushort)31,queueItems);
   for(int i=0;i<total;++i)
   {
      string strategy=QueueItemStrategyName(queueItems[i]);
      if(strategy=="") continue;
      string token=";"+strategy+";";
      if(StringFind(seen,token,0)>=0) continue;
      seen+=strategy+";";

      string inputsPath=GoatOptStrategyDir(EA_Name_,Server_,strategy)+"\\Inputs."+Key_;
      string inputs=GetFileContent(inputsPath);
      if(inputs=="") continue;

      out+="[GOAT_INPUT:"+GoatOptSafePathPart(strategy)+"]\r\n";
      out+=inputs+"\r\n";
      out+="[/GOAT_INPUT]\r\n";
   }
   out+="[/GOAT_INPUTS]\r\n";
   return out;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::RestoreBatchInputsPackage(const string packageBody)
  {
   const string startTag="[GOAT_INPUT:";
   const string endTag="[/GOAT_INPUT]";
   int pos=0;
   bool any=false;
   bool ok=true;
   while(true)
   {
      int start=StringFind(packageBody,startTag,pos);
      if(start<0) break;
      int nameStart=start+StringLen(startTag);
      int nameEnd=StringFind(packageBody,"]",nameStart);
      if(nameEnd<0) break;
      string strategy=StringSubstr(packageBody,nameStart,nameEnd-nameStart);
      StringTrimLeft(strategy);
      StringTrimRight(strategy);

      int contentStart=nameEnd+1;
      while(contentStart<StringLen(packageBody))
      {
         ushort ch=StringGetCharacter(packageBody,contentStart);
         if(ch!='\r' && ch!='\n') break;
         contentStart++;
      }
      int end=StringFind(packageBody,endTag,contentStart);
      if(end<0) break;
      string inputs=StringSubstr(packageBody,contentStart,end-contentStart);
      StringTrimLeft(inputs);
      StringTrimRight(inputs);
      if(strategy!="" && inputs!="")
      {
         string inputsPath=GoatOptStrategyDir(EA_Name_,Server_,strategy)+"\\Inputs."+Key_;
         if(!GoatOptWriteTextFile(inputsPath,inputs)) ok=false;
         else any=true;
      }
      pos=end+StringLen(endTag);
   }
   return (any && ok);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::ApplyExportSettingsToControls(const string exportSettings)
  {
   if(m_compactLayout || exportSettings=="") return;

   string val=GoatOptReadIniValue(exportSettings,"SetsToExport");
   if(val!="") m_edtSetsToExport.Text(val);
   val=GoatOptReadIniValue(exportSettings,"MinScore");
   if(val!="") m_edtMinScore.Text(val);
   val=GoatOptReadIniValue(exportSettings,"TargetDD");
   if(val!="") m_edtTargetDD.Text(val);
   val=GoatOptReadIniValue(exportSettings,"MinARF");
   if(val!="") m_edtMinARF.Text(val);
   val=GoatOptReadIniValue(exportSettings,"MinSR");
   if(val!="") m_edtMinSR.Text(val);
   val=GoatOptReadIniValue(exportSettings,"AdjustLots");
   if(val!="") m_chkAdjustLots.Checked(StringToInteger(val)!=0);
   val=GoatOptReadIniValue(exportSettings,"IncludeBackOOS");
   if(val!="") m_chkVerifyOOS.Checked(StringToInteger(val)!=0);
   val=GoatOptReadIniValue(exportSettings,"BackOOSDate");
   if(val!="")
   {
      datetime backDate=StringToTime(val);
      if(backDate>0) m_dpBackOOS.Value(backDate);
   }
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::SaveCurrentBatchPackage(void)
  {
   if(!EnsureRunContext(false)) return false;
   string queue=GetFileContent(Path_QueueBatch);
   string exportSettings=GetFileContent(Path_ExportSettings);
   if(exportSettings=="" && !m_compactLayout) exportSettings=GetExportSettingsString();
   string runName=m_edtRunName.Text();
   StringTrimLeft(runName);
   StringTrimRight(runName);
   if(runName=="") runName=GoatOptSafePathPart(Path_RunFolder);
   string body="[GOATBATCH]\r\n"
              +"Version=1\r\n"
               +"RunName="+runName+"\r\n"
               +"RunPath="+Path_RunFolder+"\r\n"
               +"EA="+EA_Name_+"\r\n"
               +"Server="+Server_+"\r\n"
               +"SavedAt="+TimeToString(TimeLocal(),TIME_DATE|TIME_SECONDS)+"\r\n"
               +"[GOAT_EXPORT_SETTINGS]\r\n"+exportSettings+"\r\n[/GOAT_EXPORT_SETTINGS]\r\n"
               +"[GOAT_QUEUE]\r\n"+queue+"\r\n[/GOAT_QUEUE]\r\n"
               +BuildBatchInputsPackage(queue);
   bool ok=GoatOptWriteTextFile(GoatOptPortfolioPath(EA_Name_,Server_),body);
   if(ok)
   {
      string manifest=GoatOptReadTextFile(Path_RunFolder+"\\manifest.ini");
      if(manifest=="") manifest="[OptimizationRun]\r\nRunName="+runName+"\r\nRunPath="+Path_RunFolder+"\r\n";
      GoatOptWriteTextFile(Path_RunFolder+"\\deploy\\portfolio_manifest.ini",manifest);
   }
   return ok;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::LoadBatchPackage(const string packagePath)
  {
   string body=GoatOptReadTextFile(packagePath);
   if(body=="")
   {
      MessageBox("Unable to read the selected portfolio batch file.","Error",MB_OK|MB_ICONERROR);
      return false;
   }
   string queue=GoatOptExtractSection(body,"[GOAT_QUEUE]","[/GOAT_QUEUE]");
   string exportSettings=GoatOptExtractSection(body,"[GOAT_EXPORT_SETTINGS]","[/GOAT_EXPORT_SETTINGS]");
   if(queue=="")
   {
      MessageBox("The selected portfolio batch does not contain a queue.","Error",MB_OK|MB_ICONERROR);
      return false;
   }
   string sourceRunPath=GoatOptFolderOf(packagePath);
   string runName=GoatOptReadIniValue(body,"RunName");
   if(runName=="") runName="Reloaded Batch";
   Path_RunFolder=GoatOptCreateRunPath(EA_Name_,Server_,runName+" Reload",sourceRunPath);
   RefreshRunPaths();
   m_edtRunName.Text(runName+" Reload");

   if(sourceRunPath!="")
      GoatOptCopyCommonTextTree(sourceRunPath+"\\inputs",Path_RunFolder+"\\inputs");
   RestoreBatchInputsPackage(body);

   if(!ApplyBatchTimelineAdjustment(queue,exportSettings,sourceRunPath)) return false;
   GoatOptWriteTextFile(Path_QueueBatch,queue);
   if(exportSettings!="") GoatOptWriteTextFile(Path_ExportSettings,exportSettings);
   ApplyExportSettingsToControls(exportSettings);
   SaveCurrentBatchPackage();
   Strategy="";
   m_edtStrategy.Text("Portfolio Batch");
   m_edtSetFile.Text(FileNameOnly(packagePath));
   OnClickRefresh(true,true);
   GoatOptAppendTimeline(EA_Name_,Server_,"BATCH_LOADED",FileNameOnly(packagePath),"Pending","Reloaded into "+Path_RunFolder);
   return true;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::SaveStrategyInputsFromSet(const string setPath,string &savedStrategy)
  {
   savedStrategy="";
   int handle = FileOpen(setPath,FILE_READ|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle==INVALID_HANDLE) return false;

   while(!FileIsEnding(handle))
     {
      string str=FileReadString(handle);
      if(StringFind(str,"EA_Desc=")!=0) continue;

      savedStrategy=NormalizeStrategyName(StringSubstr(str,8));
      if(savedStrategy=="") { FileClose(handle); return false; }

      string strategyDir = GoatOptStrategyDir(EA_Name_,Server_,savedStrategy);
      EnsureCommonFolderTree(strategyDir);
      string inputsPath = strategyDir+"\\Inputs."+Key_;
      ResetLastError();
      int handle_dest = FileOpen(inputsPath,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
      if(handle_dest==INVALID_HANDLE)
        {
         FileClose(handle);
         return false;
        }

      FileWrite(handle_dest,"Mode_Operation=9");
      FileWrite(handle_dest,str);
      while(!FileIsEnding(handle)) FileWrite(handle_dest,FileReadString(handle));
      FileClose(handle_dest);
      FileClose(handle);
      return (GetFileContent(inputsPath)!="");
     }

   FileClose(handle);
   return false;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::EnsureInputsForStrategy(const string strategy,string &message)
  {
   string cleanStrategy=NormalizeStrategyName(strategy);
   string inputsPath=GoatOptStrategyDir(EA_Name_,Server_,cleanStrategy)+"\\Inputs."+Key_;
   if(GetFileContent(inputsPath)!="")
      return true;

   if(cleanStrategy==NormalizeStrategyName(Strategy) && m_selectedSetPath!="")
     {
      string savedStrategy="";
      if(SaveStrategyInputsFromSet(m_selectedSetPath,savedStrategy) && NormalizeStrategyName(savedStrategy)==cleanStrategy && GetFileContent(inputsPath)!="")
         return true;
     }

   message="Missing strategy inputs for "+cleanStrategy+
           ".\nExpected file:\n"+inputsPath+
           "\n\nSelect that .set file again, then add the queue item again.";
   return false;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::PreflightQueueInputs(const string queueContent,string &message)
  {
   message="";
   string queueItems[];
   int total=StringSplit(queueContent,(ushort)31,queueItems);
   for(int i=0;i<total;i++)
     {
      string title=QueueItemTitle(queueItems[i]);
      if(StringFind(title,"Pending_")!=0 && StringFind(title,"Queued_")!=0 && StringFind(title,"OnGoing_")!=0)
         continue;

      string strategy=QueueItemStrategyName(queueItems[i]);
      string itemMessage="";
      bool ok=true;
      if(strategy=="")
        {
         itemMessage="Queue item has no strategy name:\n"+title;
         ok=false;
        }
      else if(!EnsureInputsForStrategy(strategy,itemMessage))
         ok=false;
      if(!ok)
        {
         if(message!="") message+="\n\n";
         message+=itemMessage;
        }
     }

   if(message=="") return true;
   message="Batch cannot start because one or more queue items are missing their saved tester inputs.\n\n"+message;
   return false;
  }
//+------------------------------------------------------------------+
string GetCurrentExpertRelativePath()
  {
   string path=MQLInfoString(MQL_PROGRAM_PATH);
   int ret=StringFind(path,"MQL5\\Experts");
   if(ret<0) return "";
   return StringSubstr(path,ret+StringLen("MQL5\\Experts")+1,-1);
  }
//+------------------------------------------------------------------+
string NormalizeExpertRelativePath(string expertPath)
  {
   StringTrimLeft(expertPath);
   StringTrimRight(expertPath);
   StringReplace(expertPath,"/","\\");
   while(StringFind(expertPath,"\\\\")>=0) StringReplace(expertPath,"\\\\","\\");

   string expertsRoot=TerminalInfoString(TERMINAL_DATA_PATH)+"\\MQL5\\Experts\\";
   if(expertPath!="" && MTTESTER::FileIsExist(expertsRoot+expertPath)) return expertPath;

   string currentExpert=GetCurrentExpertRelativePath();
   if(currentExpert!="" && MTTESTER::FileIsExist(expertsRoot+currentExpert)) return currentExpert;

   string parts[];
   int total=StringSplit(expertPath,'\\',parts);
   string fileName=(total>0)?parts[total-1]:expertPath;

   if(fileName!="" && MTTESTER::FileIsExist(expertsRoot+fileName)) return fileName;
   if(fileName!="" && MTTESTER::FileIsExist(expertsRoot+"GOAT-EA\\"+fileName)) return "GOAT-EA\\"+fileName;

   return expertPath;
  }
//+------------------------------------------------------------------+
string RepairTesterExpertPath(string testerConfig)
  {
   string cfgLines[];
   int count=StringSplit(testerConfig,'\n',cfgLines);
   if(count<1) return testerConfig;

   for(int i=0;i<count;i++)
   {
    string trimmed=cfgLines[i];
    StringTrimLeft(trimmed);
    StringTrimRight(trimmed);
    if(StringFind(trimmed,"Expert=")==0)
    {
     string expertValue=StringSubstr(trimmed,StringLen("Expert="));
     string repaired=NormalizeExpertRelativePath(expertValue);
     if(repaired!="" && repaired!=expertValue) cfgLines[i]="Expert="+repaired;
     break;
    }
   }

   string result="";
   for(int i=0;i<count;i++)
   {
    result+=cfgLines[i];
    if(i<count-1) result+="\n";
   }
   return result;
  }
//+------------------------------------------------------------------+
string QueueItemTitle(string queueItem)
  {
   string parts[];
   if(StringSplit(queueItem,';',parts)>=2) return parts[1];
   return queueItem;
  }
//+------------------------------------------------------------------+
string QueueItemSymbolName(string queueItem)
  {
   string title=QueueItemTitle(queueItem);
   int start=StringFind(title,"_",0);
   if(start<0) return "";
   start++;

   int end=StringLen(title);
   int comma=StringFind(title,",",start);
   int space=StringFind(title," ",start);
   if(comma>=0 && comma<end) end=comma;
   if(space>=0 && space<end) end=space;
   if(end<=start) return "";

   string symbol=StringSubstr(title,start,end-start);
   StringTrimLeft(symbol);
   StringTrimRight(symbol);
   return symbol;
  }
//+------------------------------------------------------------------+
string QueueItemStrategyName(string queueItem)
  {
   string title=QueueItemTitle(queueItem);
   int start=StringFind(title,":",0);
   if(start<0) return "";
   string strategy=StringSubstr(title,start+1);
   StringTrimLeft(strategy);
   StringTrimRight(strategy);
   return NormalizeStrategyName(strategy);
  }
//+------------------------------------------------------------------+
string ActiveQueueStrategyName()
  {
   string strategy=EA_Desc;
   int meta=StringFind(strategy,"@{",0);
   if(meta>=0) strategy=StringSubstr(strategy,0,meta);
   StringTrimLeft(strategy);
   StringTrimRight(strategy);
   return NormalizeStrategyName(strategy);
  }
//+------------------------------------------------------------------+
bool QueueItemMatchesCurrentRun(string queueItem)
  {
   string queuedSymbol=QueueItemSymbolName(queueItem);
   string queuedStrategy=QueueItemStrategyName(queueItem);
   string activeStrategy=ActiveQueueStrategyName();

   if(queuedSymbol!=Symbol()) return false;
   if(queuedStrategy=="" || activeStrategy=="") return true;
   return (queuedStrategy==activeStrategy);
  }
//+------------------------------------------------------------------+
struct SBatchProgressStats
  {
   int total;
   int completed;
   int errors;
   int pending;
   int queued;
   int ongoing;
   int cancelled;
   int other;
  };
//+------------------------------------------------------------------+
void ResetBatchProgressStats(SBatchProgressStats &stats)
  {
   stats.total=0;
   stats.completed=0;
   stats.errors=0;
   stats.pending=0;
   stats.queued=0;
   stats.ongoing=0;
   stats.cancelled=0;
   stats.other=0;
  }
//+------------------------------------------------------------------+
string BatchQueueStateFromTitle(string title)
  {
   StringTrimLeft(title);
   StringTrimRight(title);
   int split=StringFind(title,"_",0);
   string state=(split>0 ? StringSubstr(title,0,split) : title);
   StringTrimLeft(state);
   StringTrimRight(state);
   return state;
  }
//+------------------------------------------------------------------+
bool ReadBatchProgressStats(const string queueFile,SBatchProgressStats &stats)
  {
   ResetBatchProgressStats(stats);
   string content=GetFileContent(queueFile);
   if(content=="") return false;

   string rows[];
   int total=StringSplit(content,(ushort)31,rows);
   for(int i=0;i<total;i++)
   {
    string row=rows[i];
    StringTrimLeft(row);
    StringTrimRight(row);
    if(row=="" || StringLen(row)<9) continue;

    string parts[];
    if(StringSplit(row,';',parts)<2) continue;

    string state=BatchQueueStateFromTitle(parts[1]);
    stats.total++;

         if(state=="Completed") stats.completed++;
    else if(state=="Error")     stats.errors++;
    else if(state=="Pending")   stats.pending++;
    else if(state=="Queued")    stats.queued++;
    else if(state=="OnGoing")   stats.ongoing++;
    else if(state=="Cancelled") stats.cancelled++;
    else                        stats.other++;
   }
   return (stats.total>0);
  }
//+------------------------------------------------------------------+
string FormatBatchProgressText(const SBatchProgressStats &stats,const bool loaded)
  {
   if(!loaded || stats.total<=0) return "0/0 Completed";

   int left=stats.pending+stats.queued+stats.ongoing;
   string text=IntegerToString(stats.completed)+"/"+IntegerToString(stats.total)+" Completed";
   if(stats.errors>0)    text+=" | "+IntegerToString(stats.errors)+" Error";
   if(stats.cancelled>0) text+=" | "+IntegerToString(stats.cancelled)+" Cancelled";
   text+=" | "+IntegerToString(left)+" Left";
   return text;
  }
//+------------------------------------------------------------------+
string FormatDurationShort(const int seconds_in)
  {
   int seconds=(int)MathMax(seconds_in,0);
   int durationDays=seconds/86400;
   seconds%=86400;
   int hours=seconds/3600;
   seconds%=3600;
   int minutes=seconds/60;
   seconds%=60;

   if(durationDays>0) return IntegerToString(durationDays)+"d "+IntegerToString(hours)+"h";
   if(hours>0)   return IntegerToString(hours)+"h "+IntegerToString(minutes)+"m";
   if(minutes>0) return IntegerToString(minutes)+"m "+IntegerToString(seconds)+"s";
   return IntegerToString(seconds)+"s";
  }
//+------------------------------------------------------------------+
bool TryParseLogStamp(const string line,datetime &stamp)
  {
   if(StringLen(line)<19) return false;
   stamp=StringToTime(StringSubstr(line,0,19));
   return (stamp>0);
  }
//+------------------------------------------------------------------+
void BuildOptimizationBatchPromptSummary(const string queueFile,const string logFile,string &line1,string &line2,string &line3)
  {
   SBatchProgressStats stats;
   bool loaded=ReadBatchProgressStats(queueFile,stats);
   int left=stats.pending+stats.queued+stats.ongoing;

   if(loaded)
      line1=StringFormat("Runs OK: %d/%d | Errors: %d | Left: %d",stats.completed,stats.total,stats.errors,left);
   else
      line1="Runs OK: n/a | Queue not found";

   string logLines[];
   int lineCount=0;
   int h=FileOpen(logFile,FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_TXT|FILE_COMMON);
   if(h!=INVALID_HANDLE)
   {
    while(!FileIsEnding(h))
    {
     ArrayResize(logLines,lineCount+1);
     logLines[lineCount]=FileReadString(h);
     lineCount++;
    }
    FileClose(h);
   }

   int startIndex=-1;
   datetime batchStart=0;
   for(int i=lineCount-1;i>=0;i--)
   {
    if(StringFind(logLines[i],"Batch Start clicked and accepted",0)>=0)
    {
     startIndex=i;
     TryParseLogStamp(logLines[i],batchStart);
     break;
    }
   }

   int completedRuns=0,totalSeconds=0,xmlIssues=0,exportIssues=0;
   datetime currentStart=0,lastRunEnd=0;
   for(int i=(int)MathMax(startIndex,0);i<lineCount;i++)
   {
    string ln=logLines[i];
    datetime stamp=0;
    bool haveStamp=TryParseLogStamp(ln,stamp);

    if(StringFind(ln,"Batch Optimization Initialized",0)>=0)
    {
     if(haveStamp) currentStart=stamp;
     continue;
    }

    if(StringFind(ln,"Optimization Ended",0)>=0)
    {
     if(haveStamp)
     {
      lastRunEnd=stamp;
      if(currentStart>0 && stamp>=currentStart)
      {
       totalSeconds+=(int)(stamp-currentStart);
       completedRuns++;
      }
     }
     currentStart=0;
     continue;
    }

    if(StringFind(ln,"XML Migration not complete",0)>=0 ||
       StringFind(ln,"Some XML files failed to move",0)>=0 ||
       StringFind(ln,"Failed to Analyze and Combine",0)>=0 ||
       StringFind(ln,"Failed to analyze and combine",0)>=0)
       xmlIssues++;

    if(StringFind(ln,"Exports aborted",0)>=0 ||
       (StringFind(ln,"StartExporter",0)>=0 && StringFind(ln,"failed",0)>=0))
       exportIssues++;
   }

   if(completedRuns>0)
   {
    int avgSeconds=totalSeconds/completedRuns;
    int elapsedSeconds=(batchStart>0 && lastRunEnd>=batchStart ? (int)(lastRunEnd-batchStart) : totalSeconds);
    line2="Avg/run: "+FormatDurationShort(avgSeconds)+" | Total: "+FormatDurationShort(elapsedSeconds);
   }
   else
      line2="Avg/run: n/a | Total: n/a";

   line3=StringFormat("XML issues: %d | Export issues: %d",xmlIssues,exportIssues);
   if(loaded && stats.cancelled>0) line3+=" | Cancelled: "+IntegerToString(stats.cancelled);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnDateFromChanged(void)
{
   //Print(__FUNCTION__,": new from-date = ", TimeToString(m_dtFrom.Value(), TIME_DATE));
}
void CStrategyTesterDialog::OnDateToChanged(void)
{
   //Print(__FUNCTION__,": new to-date   = ", TimeToString(m_dtTo.Value(), TIME_DATE));
}
void CStrategyTesterDialog::OnDateForwardChanged(void)
{
   //Print(__FUNCTION__,": new forward-date = ", TimeToString(m_dtForward.Value(), TIME_DATE));
}
void CStrategyTesterDialog::OnChange_cmbForward(void)
{
   string ForwardMode= m_cmbForward.Select();
   if(ForwardMode=="1/2"||ForwardMode=="1/3"||ForwardMode=="1/4") m_dtForward.Value((datetime)TimeToString(GetForwardD(m_dtFrom.Value(),m_dtTo.Value(),ForwardMode),TIME_DATE));
}
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::Create(const long chart_id, const string name,const int subwin, int x1, int y1, int x2, int y2)
  {
   m_leftMargin   =(int)MathMax(6,(int)(0.020*D_Width));
   m_topMargin    =(int)MathMax(8,(int)(0.025*D_Height));
   m_labelWidth   =(int)MathMax(58,(int)(0.100*D_Width));
   m_GapHoriz     =(int)MathMax(4,(int)(0.010*D_Width));
   m_controlHeight=(int)MathMax(CONTROLS_COMBO_MIN_HEIGHT,(int)(0.043*D_Height));
   m_rowHeight    =(int)MathMax(m_controlHeight+4,(int)(0.051*D_Height));
   m_controlWidth =(int)MathMax(165,(int)(0.280*D_Width));
   m_batchRunning=ResolveBatchRunningState(true);
   m_compactLayout=false;
   
   int GapCtrl    =(int)(0.05*m_controlWidth);
   // 30+65+5=100
   double Ctrl_S = 0.300;     // 2 Cntrl smaller
   double Ctrl_L = 0.650;     // 2 Cntrl larger
   // 30+5+30+5+30=100
   double Ctrl_M = 0.300;     // 2 Cntrl larger
   
   GlobalVariableSet("CaptionHeight",0.05*D_Height);
   //int val=(int)GlobalVariableGet("CaptionHeight"); // Add in ControlsPlus\Dialog.mqh
   //int y2=y1+((val>1)?val:CONTROLS_DIALOG_CAPTION_HEIGHT);
   //int y1=off+((val>1)?val:CONTROLS_DIALOG_CAPTION_HEIGHT);
   if(!CAppDialog::Create(chart_id, name, subwin, x1, y1, x2, y2))
   {
      Print("Failed to create StrategyTesterDialog: ", GetLastError());
      return(false);
   }
   GlobalVariableDel("CaptionHeight");
   string buildLabel=EA_Name_;
   string buildPrefix=Key_+" ";
   if(StringFind(buildLabel,buildPrefix)==0) buildLabel=StringSubstr(buildLabel,StringLen(buildPrefix));
   if(buildLabel=="") buildLabel="V"+version_;
   Caption(Key_+" - Optimization Studio " + buildLabel);
   ChartSetInteger(0,CHART_SHOW_TRADE_HISTORY,0);
   SetCaptionClientColors();
   
   int settingsRowsWithActions=14; // heading, settings rows, and Add/Set action row
   int settingsPanelNeeded=m_topMargin+(settingsRowsWithActions*m_rowHeight)+MathMax(8,m_GapHoriz);
   int settingsPanelBase=(int)(D_Height*(m_compactLayout ? 0.985 : 0.69));
   int settingsPanelLimit=(int)(D_Height*(m_compactLayout ? 0.985 : 0.78));
   int optPanelBottom=(int)MathMin(settingsPanelLimit,MathMax(settingsPanelBase,settingsPanelNeeded));
   if(!c_Wnd_OPT.Create(m_chart_id,m_name+"Boundary",m_subwin,(int)(D_Width*0.01),(int)(D_Height*0.015),(int)(D_Width*0.42),optPanelBottom))  // left,top,right,bottom
   {
      Print("Failed to create boundary rect: ", GetLastError());
      return false;
   }
   c_Wnd_OPT.ColorBackground(clrGainsboro);
   c_Wnd_OPT.ColorBorder(clrBlack);
   Add(c_Wnd_OPT);
   
   int y = m_topMargin;
   //-------------------------------------------------------------
   CreateLabel(m_lblHeading,"Optimization Settings", m_leftMargin+(int)(D_Width*0.11), y, m_controlWidth); m_lblHeading.FontSize(m_lblHeading.FontSize()+1);
   y += m_rowHeight;
   //-------------------------------------------------------------
   CreateLabel(m_lblRunName, "Run Name:", m_leftMargin, y, m_labelWidth);
   string runNameDefault="";
   if(Path_RunFolder!="") runNameDefault=GoatOptSafePathPart(GoatOptReadIniValue(GoatOptReadTextFile(Path_RunFolder+"\\manifest.ini"),"RunName"));
   if(runNameDefault=="" || runNameDefault=="Optimization Run") runNameDefault="Optimization Run";
   CreateEditBox(m_edtRunName, "edtRunName",m_leftMargin + m_labelWidth + m_GapHoriz, y,m_controlWidth,runNameDefault);
   y += m_rowHeight;
   //-------------------------------------------------------------
 //CreateLabel(m_lblSetFile, "Set File:", m_leftMargin, y, m_labelWidth);
   CreateButtonCtrl(m_btnSelectFile, "btnSelectFile", m_leftMargin, y, m_labelWidth, m_controlHeight, "Select");
   CreateEditBox(m_edtSetFile, "edtSetFile",m_leftMargin + m_labelWidth + m_GapHoriz, y,m_controlWidth," "); // default text empty or "mysettings.set"
   m_edtSetFile.ReadOnly(true);
   y += m_rowHeight;
   //m_leftMargin   =(int)(0.030*D_Width);
   //m_GapHoriz=(int)(0.001*D_Width);
   //-------------------------------------------------------------
   CreateLabel(m_lblStrategy, "Strategy:", m_leftMargin, y, m_labelWidth);
   CreateEditBox(m_edtStrategy, "edtStrategy",m_leftMargin + m_labelWidth + m_GapHoriz, y,m_controlWidth," ");
   m_edtStrategy.ReadOnly(true);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (1) Expert
   //-------------------------------------------------------------
   CreateLabel(m_lblExpert, "Expert:", m_leftMargin, y, m_labelWidth);
   CreateCombo(m_cmbExpert, "cmbExpert", m_leftMargin + m_labelWidth + m_GapHoriz, y, m_controlWidth);
   // Example logic to show path
   string path = MQLInfoString(MQL_PROGRAM_PATH);
   int ret = StringFind(path, "MQL5\\Experts");
   if(ret >= 0) n_Expert = StringSubstr(path, ret + StringLen("MQL5\\Experts")+1, -1);
   n_Expert = NormalizeExpertRelativePath(n_Expert);
   if(ret >= 0) path = StringSubstr(path, MathMax(ret,(StringLen(path)-33)), -1);
   
   m_cmbExpert.AddItem(path);
   m_cmbExpert.Select(0);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (2) Symbol + Period on same row
   //-------------------------------------------------------------
   CreateLabel(m_lblSymbol, "Symbol:", m_leftMargin, y, m_labelWidth);
   // Symbol combo
   CreateCombo(m_cmbSymbol, "cmbSymbol", m_leftMargin+m_labelWidth+m_GapHoriz, y, (int)(m_controlWidth*Ctrl_L));
   // --- NEW: presets first, then normal symbols ---
   AddPresetsFirstToCombo(m_cmbSymbol, Key_);
   // Then append all normal symbols (market watch pool)
   for(int i=0; i < SymbolsTotal(true); i++) m_cmbSymbol.AddItem(SymbolName(i,true));
   // Default select the first entry (a preset if present)
   m_cmbSymbol.Select(0);
   // Now place the Period combo to the right, no label
   int periodX = m_leftMargin+m_labelWidth+m_GapHoriz+(int)(m_controlWidth*Ctrl_L)+GapCtrl;
   CreateCombo(m_cmbPeriod, "cmbPeriod", periodX, y, (int)(m_controlWidth*Ctrl_S));
   m_cmbPeriod.AddItem("M1");
   m_cmbPeriod.AddItem("M5");
   m_cmbPeriod.AddItem("M15");
   m_cmbPeriod.AddItem("M30");
   m_cmbPeriod.AddItem("H1");
   m_cmbPeriod.Select(0);
   // Done with this row
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (4) Date Range (store positions, create pickers later)
   //-------------------------------------------------------------
   // (a) From
   CreateLabel(m_lblDateFrom, "Date from:", m_leftMargin, y, m_labelWidth);
   m_xFrom = m_leftMargin + m_labelWidth + m_GapHoriz;
   m_yFrom = y;
   y += m_rowHeight;
   // (b) To
   CreateLabel(m_lblDateTo, "Date to:", m_leftMargin, y, m_labelWidth);
   m_xTo = m_leftMargin + m_labelWidth + m_GapHoriz;
   m_yTo = y;
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (5) Forward + forward date on same row
   //-------------------------------------------------------------
   CreateLabel(m_lblForward, "Forward:", m_leftMargin, y, m_labelWidth);
   // Compressed forward combo
   CreateCombo(m_cmbForward, "cmbForward",m_leftMargin + m_labelWidth + m_GapHoriz, y, (int)(m_controlWidth*Ctrl_S));
   m_cmbForward.AddItem("No");
   m_cmbForward.AddItem("1/2");
   m_cmbForward.AddItem("1/3");
   m_cmbForward.AddItem("1/4");
   m_cmbForward.AddItem("Custom");
   m_cmbForward.Select(4);
   // forward date to the right of that
   m_xForwardDt = m_leftMargin + m_labelWidth + m_GapHoriz + (int)(m_controlWidth*Ctrl_S) + GapCtrl;
   m_yForwardDt = y;
   // done with row
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (6) Delays
   //-------------------------------------------------------------
   CreateLabel(m_lblDelay, "Delays:", m_leftMargin, y, m_labelWidth);
   CreateCombo(m_cmbDelay, "cmbDelay", m_leftMargin + m_labelWidth + m_GapHoriz, y, m_controlWidth);
   m_cmbDelay.AddItem("Zero latency, ideal execution");
   m_cmbDelay.AddItem("10 ms delay");
   m_cmbDelay.AddItem("20 ms delay");
   m_cmbDelay.AddItem("50 ms delay");
   m_cmbDelay.AddItem("100 ms delay");
   m_cmbDelay.AddItem("200 ms delay");
   m_cmbDelay.AddItem("500 ms delay");
   //m_cmbDelay.AddItem("1 sec delay");
   m_cmbDelay.Select(0);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (7) Modeling
   //-------------------------------------------------------------
   CreateLabel(m_lblModeling, "Modeling:", m_leftMargin, y, m_labelWidth);
   CreateCombo(m_cmbModel, "cmbModel", m_leftMargin + m_labelWidth + m_GapHoriz, y, m_controlWidth);
   m_cmbModel.AddItem("Open prices only");
   m_cmbModel.AddItem("1 minute OHLC");
   m_cmbModel.AddItem("Every tick");
   m_cmbModel.AddItem("Every tick based on real ticks");
   m_cmbModel.Select(1);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (8) Deposit / Currency(edit) / Leverage
   //-------------------------------------------------------------
   CreateLabel(m_lblDeposit, "Deposit:", m_leftMargin, y, m_labelWidth);
   // deposit edit
   CreateEditBox(m_edtDeposit, "editDeposit" ,m_leftMargin+m_labelWidth+m_GapHoriz                                             , y, (int)(m_controlWidth*Ctrl_M), "100000");
   // currency edit, default "USD"
   CreateEditBox(m_edtCurrency, "edtCurrency",m_leftMargin+m_labelWidth+m_GapHoriz + (int)(m_controlWidth*Ctrl_M*1) +   GapCtrl, y, (int)(m_controlWidth*Ctrl_S), "USD");
   // leverage combo to the right
   CreateCombo(m_cmbLeverage, "comboLeverage",m_leftMargin+m_labelWidth+m_GapHoriz + (int)(m_controlWidth*Ctrl_M*2) + 2*GapCtrl, y, (int)(m_controlWidth*Ctrl_S));
   m_cmbLeverage.AddItem("1:100");
   m_cmbLeverage.AddItem("1:200");
   m_cmbLeverage.AddItem("1:500");
   m_cmbLeverage.AddItem("1:1000");
   m_cmbLeverage.Select(2);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (9) Optimization
   //-------------------------------------------------------------
   CreateLabel(m_lblOptimization, "Optimization:", m_leftMargin, y, m_labelWidth);
   CreateCombo(m_cmbOptimization, "comboOptimization", m_leftMargin + m_labelWidth + m_GapHoriz, y, m_controlWidth);
   //m_cmbOptimization.AddItem("Disabled");
   //m_cmbOptimization.AddItem("Slow complete");
   m_cmbOptimization.AddItem("Fast genetic based algorithm");
   m_cmbOptimization.Select(0);
   y += m_rowHeight;
   //-------------------------------------------------------------
   // (10) Single button at the bottom
   //-------------------------------------------------------------
   CreateButtonCtrl(m_btnAddQueue,  "btnAddQueue",   m_leftMargin, y, (m_labelWidth+m_controlWidth)/2, m_rowHeight, "Add to Queue");
   CreateButtonCtrl(m_btnSetPresets,"btnSetPresets", m_leftMargin+(m_labelWidth+m_controlWidth)/2+m_GapHoriz, y, (m_labelWidth+m_controlWidth)/2, m_rowHeight, "Set Presets");
   //-------------------------------------------------------------
   // Finally, create date pickers last in reversed order:
   // Forward → To → From
   //-------------------------------------------------------------
   // 1) Forward date
   CreateDatePick(m_dtForward, "dtForward", m_xForwardDt, m_yForwardDt, (int)(m_controlWidth*Ctrl_L));
   m_dtForward.Value(D'2025.01.06');
   // 2) DateTo
   CreateDatePick(m_dtTo, "dtTo", m_xTo, m_yTo, m_controlWidth);
   m_dtTo.Value(D'2025.03.15');
   // 3) DateFrom
   CreateDatePick(m_dtFrom, "dtFrom", m_xFrom, m_yFrom, m_controlWidth);
   m_dtFrom.Value(D'2024.01.08');
   //-------------------------------------------------------------
   int last_y=y;
   y = m_topMargin;
   CreateLabel(m_lblQueue, "Q U E U E" , m_leftMargin+m_labelWidth+m_GapHoriz+m_controlWidth+m_GapHoriz+(int)(D_Width*0.25), y, m_controlWidth); m_lblQueue.FontSize(m_lblQueue.FontSize()+2);
 //CreateLabel(m_lblStatus,"Status", m_leftMargin+m_labelWidth+2*m_controlWidth+60 , y, m_labelWidth/3);
   y += m_rowHeight;
   m_listQueue.ItemHeightFHD(m_rowHeight-1); // void              ItemHeightFHD(const int px) {m_item_height=px} // Add in ControlsPlus\ListView.mqh
   
   int indt_left = m_leftMargin+m_labelWidth+m_GapHoriz+m_controlWidth+m_GapHoriz+2*m_GapHoriz;
   int width_right = (int)(D_Width*0.98)-indt_left;
   
   int queueListTop=y;
   int layoutGap=MathMax(6,m_GapHoriz);
   int queueButtonY=optPanelBottom-m_rowHeight-layoutGap;
   int queueListHeight=MathMax(m_rowHeight*4,queueButtonY-queueListTop-layoutGap);
   int startStopHeight=(int)MathMax(m_rowHeight+10,MathMin(m_rowHeight*1.6,D_Height*0.075));
   int startY=optPanelBottom+MathMax(10,layoutGap);
   int stopY=startY+startStopHeight+MathMax(14,layoutGap*2);

   if(m_compactLayout)
   {
    int compactGap=MathMax(4,m_GapHoriz);
    startStopHeight=MathMax(m_controlHeight+8,(int)(m_rowHeight*1.6));
    int compactBottom=D_Height-m_topMargin;
    stopY=compactBottom-startStopHeight;
    startY=stopY-compactGap-startStopHeight;
    queueButtonY=startY-compactGap-m_rowHeight;
    queueListHeight=MathMax(m_rowHeight*4,queueButtonY-queueListTop-compactGap);
   }

   CreateListView(m_listQueue,"m_listQueue",indt_left, queueListTop,width_right,queueListHeight," ");
   y=queueButtonY; Ctrl_M=0.19;
 //CreateButtonCtrl(m_btnDelQ          , "m_btnDelQ"          ,indt_left,                                                       y, (int)(width_right*Ctrl_M), m_rowHeight, "Delete Queue");
 //CreateButtonCtrl(m_btnDelQitem      , "m_btnDelQitem"      ,indt_left+(int)(width_right*Ctrl_M*1)+1*(int)(width_right*0.05), y, (int)(width_right*Ctrl_M), m_rowHeight, "Delete Item");
 //CreateButtonCtrl(m_btnRefresh       , "m_btnRefresh"       ,indt_left+(int)(width_right*Ctrl_M*2)+2*(int)(width_right*0.05), y, (int)(width_right*Ctrl_M), m_rowHeight, "Refresh Queue");
   int qBtnGap=MathMax(8,(int)(width_right*0.014));
   int qArrowW=MathMax(52,(int)(width_right*0.075));
   int qActionW=(width_right-(qBtnGap*5)-(qArrowW*2))/4;
   int qx=indt_left;
   CreateButtonCtrl(m_btnDelQ          , "m_btnDelQ"          ,qx, y, qActionW, m_rowHeight, "Delete All"); qx+=qActionW+qBtnGap;
   CreateButtonCtrl(m_btnDelQitem      , "m_btnDelQitem"      ,qx, y, qActionW, m_rowHeight, "Delete");     qx+=qActionW+qBtnGap;
   CreateButtonCtrl(m_btnUpQitem       , "m_btnUpQitem"       ,qx, y, qArrowW , m_rowHeight, "▲");          qx+=qArrowW+qBtnGap;
   CreateButtonCtrl(m_btnDownQitem     , "m_btnDownQitem"     ,qx, y, qArrowW , m_rowHeight, "▼");          qx+=qArrowW+qBtnGap;
   CreateButtonCtrl(m_btnCancelSelected, "m_btnCancelSelected",qx, y, qActionW, m_rowHeight, "Cancel");     qx+=qActionW+qBtnGap;
   CreateButtonCtrl(m_btnMakePending   , "m_btnMakePending"   ,qx, y, qActionW, m_rowHeight, "Activate");
   
   Ctrl_M=0.30;
   y=startY;
   CreateButtonCtrl(m_btnStart   , "m_btnStart"    ,indt_left+(int)(width_right*Ctrl_M*2)+2*(int)(width_right*0.05), y, (int)(width_right*Ctrl_M), startStopHeight, m_batchRunning ? "RUNNING" : "START BATCH");
         m_btnStart.FontSize(m_btnStart.FontSize()+2); m_btnStart.Color(clrWhite); m_btnStart.ColorBackground(clrGreen); m_btnStart.ColorBorder(clrBlack);//C'15,23,42');
   if(m_batchRunning) m_btnStart.Disable();
   y=stopY;
   CreateButtonCtrl(m_btnStop    , "m_btnStop"     ,indt_left+(int)(width_right*Ctrl_M*2)+2*(int)(width_right*0.05), y, (int)(width_right*Ctrl_M), startStopHeight, "TERMINATE");
         m_btnStop.FontSize(m_btnStop.FontSize()+2); m_btnStop.Color(clrWhite); m_btnStop.ColorBackground(clrCrimson); m_btnStop.ColorBorder(clrBlack);//C'15,23,42');
   int progressY=y+startStopHeight+MathMax(4,(int)(m_GapHoriz*0.75));
   CreateEditBox(m_edtBatchProgress,"m_edtBatchProgress",indt_left+(int)(width_right*Ctrl_M*2)+2*(int)(width_right*0.05),progressY,(int)(width_right*Ctrl_M),"0/0 Completed");
   m_edtBatchProgress.ReadOnly(true);
   m_edtBatchProgress.Color(clrWhite);
   m_edtBatchProgress.ColorBackground(C'47,74,111');
   m_edtBatchProgress.ColorBorder(clrBlack);
   y += m_rowHeight;
   
   if(!m_compactLayout)
   {
  int exportPanelLeft   = (int)(D_Width*0.01);
  int exportPanelGap    = MathMax(6,(int)(m_GapHoriz*1.5));
  int exportPanelTop    = optPanelBottom+exportPanelGap;
  int exportPanelRight  = (int)(D_Width*0.80);
  int exportPanelBottom = (int)(D_Height*0.995);
  int minExportHeight   = MathMax(180,(int)(m_rowHeight*5.2));
  if(exportPanelTop>exportPanelBottom-minExportHeight)
     exportPanelTop=exportPanelBottom-minExportHeight;
  int exportPanelWidth  = exportPanelRight-exportPanelLeft;

  if(!c_Wnd_Export.Create(m_chart_id,m_name+"Export",m_subwin,exportPanelLeft,exportPanelTop,exportPanelRight,exportPanelBottom))  // left,top,right,bottom
  {
     Print("Failed to create export rect: ", GetLastError());
     return false;
   }
   c_Wnd_Export.ColorBackground(clrGainsboro);
   c_Wnd_Export.ColorBorder(clrBlack);
   Add(c_Wnd_Export);
   
   int exportContentY = exportPanelTop+MathMax(12,(int)(m_GapHoriz*2));
   int syncButtonHeight = MathMax(18,MathMin(28,(int)(m_controlHeight*0.78)));
   int syncButtonGap = MathMax(8,m_GapHoriz);
   int syncLabelWidth = MathMax(80,(int)(D_Width*0.09));
   int syncButtonWidth = MathMax(110,MathMin((int)(D_Width*0.20),(exportPanelWidth-syncLabelWidth-syncButtonGap*4)/3));
   int syncGroupWidth = syncLabelWidth+syncButtonGap+(syncButtonWidth*3)+(syncButtonGap*2);
   int syncGroupLeft = exportPanelLeft+MathMax(0,(exportPanelWidth-syncGroupWidth)/2);
   int syncY = exportPanelBottom-syncButtonHeight-MathMax(10,(int)(D_Height*0.014));
   int exportRowStep = (int)MathMax(28,MathMin(m_rowHeight-8,(syncY-exportContentY-MathMax(22,(int)(m_controlHeight*0.55))-8)/3));
   int exportCheckSize = MathMax(14,MathMin(20,(int)(m_controlHeight*0.55)));
   int exportCheckOffset = MathMax(0,(m_controlHeight-exportCheckSize)/2);
   y = exportContentY;
   // -----------------  EXPORT SETTINGS  -----------------------------
    string BackOOSDate = FetchExportSetting("BackOOSDate",Key_,EA_Name_,Server_);               if(BackOOSDate=="") BackOOSDate=TimeToString(D'2024.01.08',TIME_DATE);
    int    SetsToExport= (int)FetchExportSetting("SetsToExport",Key_,EA_Name_,Server_);         if(SetsToExport<2) SetsToExport=2;
    double MinScore    = StringToDouble(FetchExportSetting("MinScore",Key_,EA_Name_,Server_));  if(MinScore<60) MinScore=60.0;
    double MinARF      = StringToDouble(FetchExportSetting("MinARF",Key_,EA_Name_,Server_));    if(MinARF<0.2) MinARF=0.2;
    double MinSR       = StringToDouble(FetchExportSetting("MinSR",Key_,EA_Name_,Server_));     if(MinSR<2.5) MinSR=2.5;
    double TargetDD    = StringToDouble(FetchExportSetting("TargetDD",Key_,EA_Name_,Server_));  if(TargetDD<100) TargetDD=100;
    bool   AdjustLots  = StringToInteger(FetchExportSetting("AdjustLots",Key_,EA_Name_,Server_))!=0;//Print(AdjustLots);
    bool   InclBackOOS = StringToInteger(FetchExportSetting("IncludeBackOOS",Key_,EA_Name_,Server_))!=0;//Print(InclBackOOS);

   CreateLabel(m_lblExport,"Export Settings", m_leftMargin+(int)(D_Width*0.0), y, 10);
   m_lblExport.FontSize(m_lblExport.FontSize()+1);

   int exportLeftMargin  =(int)(m_leftMargin*8.0);
   int exportLabelWidth  =(int)(m_labelWidth*1.3);
   int exportControlWidth=(int)(m_controlWidth*0.5);
   int exportRow0 = exportContentY;
   int exportRow1 = exportRow0+exportRowStep;
   int exportRow2 = exportRow1+exportRowStep;
   int exportRow3 = exportRow2+exportRowStep;

   // ===== LEFT-COLUMN ITEMS  ========================================
   CreateLabel (m_lblSetsToExport ,"# of Sets to Export:", exportLeftMargin,exportRow0,exportLabelWidth);
   CreateEditBox(m_edtSetsToExport,"edtSetsToExport", exportLeftMargin+exportLabelWidth+m_GapHoriz,exportRow0,exportControlWidth,IntegerToString(SetsToExport));
   CreateLabel (m_lblMinScore ,"Min OPT Score:" ,exportLeftMargin,exportRow1,exportLabelWidth);
   CreateEditBox(m_edtMinScore,"edtMinScore",exportLeftMargin+exportLabelWidth+m_GapHoriz,exportRow1,exportControlWidth,DoubleToString(MinScore,1));
   CreateLabel (m_lblTargetDD ,"Target Drawdown:",exportLeftMargin,exportRow2,exportLabelWidth);
   CreateEditBox(m_edtTargetDD,"edtTargetDD",exportLeftMargin+exportLabelWidth+m_GapHoriz,exportRow2,exportControlWidth,DoubleToString(TargetDD,0));
   CreateLabel (m_lblAdjustLots ,"Adjust Lots to DD:",exportLeftMargin,exportRow3,exportLabelWidth);
   int adjustCheckX = exportLeftMargin+exportLabelWidth+m_GapHoriz;
   int adjustCheckY = exportRow3+exportCheckOffset;
   if(!m_chkAdjustLots.Create(m_chart_id,m_name+"chkAdjustLots",m_subwin,adjustCheckX,adjustCheckY,adjustCheckX+exportCheckSize,adjustCheckY+exportCheckSize))
      Print("CheckBox creation error:",GetLastError());
   Add(m_chkAdjustLots); m_chkAdjustLots.Text(""); m_chkAdjustLots.Checked(AdjustLots);

   // ===== RIGHT-COLUMN ITEMS  =======================================
   int xR = exportLeftMargin + exportLabelWidth + exportControlWidth + m_GapHoriz*4;
   CreateLabel (m_lblMinARF ,"Min ARF:",xR,exportRow1,exportLabelWidth);
   CreateEditBox(m_edtMinARF,"edtMinARF",xR+exportLabelWidth+m_GapHoriz,exportRow1,exportControlWidth,DoubleToString(MinARF,1));
   CreateLabel (m_lblMinSR ,"Min SR:",xR,exportRow2,exportLabelWidth);
   CreateEditBox(m_edtMinSR,"edtMinSR",xR+exportLabelWidth+m_GapHoriz,exportRow2,exportControlWidth,DoubleToString(MinSR,1));
   CreateLabel (m_lblVerifyOOS ,"Include Back OOS:",xR,exportRow3,exportLabelWidth);
   int oosCheckX = xR+exportLabelWidth+m_GapHoriz;
   int oosCheckY = exportRow3+exportCheckOffset;
   if(!m_chkVerifyOOS.Create(m_chart_id,m_name+"chkVerifyOOS",m_subwin,oosCheckX,oosCheckY,oosCheckX+exportCheckSize,oosCheckY+exportCheckSize))
      Print("CheckBox creation error:",GetLastError());
   Add(m_chkVerifyOOS); m_chkVerifyOOS.Text(""); m_chkVerifyOOS.Checked(InclBackOOS);

   CreateLabel (m_lblBackOOSDate ,"Back OOS Date:",xR,exportRow0,exportLabelWidth);
   CreateDatePick(m_dpBackOOS   ,"dpBackOOS", xR+exportLabelWidth+m_GapHoriz,exportRow0,exportControlWidth);
   if(BackOOSDate=="") BackOOSDate="2024.01.01";
   m_dpBackOOS.Value(StringToTime(BackOOSDate));

  int syncLabelX = syncGroupLeft;
  int syncButtonX = syncLabelX + syncLabelWidth + syncButtonGap;
  CreateLabel(m_lblDataSync,"Data Sync:",syncLabelX,syncY,syncLabelWidth);
  CreateButtonCtrl(m_btnSyncBias,"m_btnSyncBias",syncButtonX,syncY,syncButtonWidth,syncButtonHeight,"Sync AI Bias History");
  CreateButtonCtrl(m_btnViewBias,"m_btnViewBias",syncButtonX+syncButtonWidth+syncButtonGap,syncY,syncButtonWidth,syncButtonHeight,"View AI Bias History");
  CreateButtonCtrl(m_btnSyncNews,"m_btnSyncNews",syncButtonX+(syncButtonWidth+syncButtonGap)*2,syncY,syncButtonWidth,syncButtonHeight,"Sync News History");
   }
   // Show the dialog
   Show(); Sleep(50);
   OnClickRefresh(true);
   return(true);
}
//+------------------------------------------------------------------+
void CStrategyTesterDialog::SetCaptionClientColors(void)
  {
   string prefix=Name();
   int total=TesterDialog.ControlsTotal();
   for(int i=0;i<total;i++)
   {
    CWnd*obj=TesterDialog.Control(i);
    string name=obj.Name();
    //---
    if(name==prefix+"Caption")
    {
     CEdit *edit=(CEdit*) obj;
     CaptionObjTester = edit;
     //color clr=(color)GETRGB(XRGB(rand()%255,rand()%255,rand()%255));
     edit.ColorBackground(C'15,23,42');
     //edit.ColorBorder(clrWheat);
     edit.Color(clrWhite);
     //edit.Font(GetFontName(Font_Header));
     edit.FontSize(Font_Size+2);
     edit.TextAlign(ALIGN_CENTER);
    }
    //---
    if(name==prefix+"Client")
    {
     //CWndClient *wndclient=(CWndClient*) obj;
     //color clr=(color)GETRGB(XRGB(rand()%255,rand()%255,rand()%255));
     //wndclient.ColorBackground(clrWhite);
     //wndclient.ColorBorder(clrWheat);
    }
   }
   ChartRedraw();
   return;
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::CreateLabel(CLabel &lbl, const string text, int x, int y, int width)
{
   if(!lbl.Create(m_chart_id, text, m_subwin, x, y, x+width, y+m_controlHeight))
      Print("Label creation error:", GetLastError());
   if(Font_Size>0) lbl.FontSize(Font_Size);
   lbl.Text(text);
   Add(lbl);
}
void CStrategyTesterDialog::CreateCombo(CComboBox &cmb, const string name, int x, int y, int width)
{
   if(!cmb.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+m_controlHeight))
      Print("Combo creation error:", GetLastError());
   if(Font_Size>0) cmb.FontSizeFHD(Font_Size); //void      FontSizeFHD(const int px)   {m_edit.FontSize(px); m_list.FontSizeFHD(px);} // Add in ControlsPlus\ComboBox.mqh
   Add(cmb);
}
void CStrategyTesterDialog::CreateDatePick(CDatePicker &dtp, const string name, int x, int y, int width)
{
   GlobalVariableSet("TesterDatePickerFontSize",Font_Size*1.9);
   //int val=(int)GlobalVariableGet("TesterDatePickerFontSize");  // Add in ControlsPlus\DateDropList.mqh
   //m_canvas.FontSet(CONTROLS_FONT_NAME,(val>1)?val:CONTROLS_FONT_SIZE*(-10));
   if(!dtp.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+m_controlHeight)) Print("DatePicker creation error:", GetLastError());
   GlobalVariableDel("TesterDatePickerFontSize");
   if(Font_Size>0) dtp.FontSizeFHD(Font_Size); //void      FontSizeFHD(const int px) {m_edit.FontSize(px);} // Add in ControlsPlus\DatePicker.mqh
   Add(dtp);
}
void CStrategyTesterDialog::CreateEditBox(CEdit &edt, const string name, int x, int y, int width, string def)
{
   if(!edt.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+m_controlHeight)) Print("Edit creation error:", GetLastError());
   if(Font_Size>0) edt.FontSize(Font_Size);
   edt.Text(def);
   Add(edt);
}
void CStrategyTesterDialog::CreateButtonCtrl(CButton &btn, const string name, int x, int y, int width, int height, string caption)
{
   if(!btn.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+height)) Print("Button creation error:", GetLastError());
      btn.Color(clrPaleTurquoise); btn.ColorBackground(C'15,23,42'); btn.ColorBorder(clrBlack);//C'15,23,42');
   if(Font_Size>0) btn.FontSize(Font_Size);
   btn.Text(caption);
   Add(btn);
}
void CStrategyTesterDialog::CreateListView(CListView &listV, const string name, int x, int y, int width, int height, string caption)
{
   if(!listV.Create(m_chart_id,m_name+"ListView",m_subwin, x, y, x+width, y+height)) Print("ListView creation error:", GetLastError());
   if(Font_Size>0) listV.FontSizeFHD(Font_Size); //void FontSizeFHD(const int px) {for(int i=0;i<ArraySize(m_rows);i++) m_rows[i].FontSize(px);} // Add in ControlsPlus\ListView.mqh
   if(!Add(listV)) return;
   //for(int i=0;i<10;i++) if(!listV.AddItem(" - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ",0)) return;
   //listV.AddItem("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz",0);
   //m_listQueue.ItemColorsFHD(5,clrGreen,clrWheat); m_listQueue.Select(3); //m_listQueue.
}
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::ReadNewsHistoryRange(const string file_name,datetime &earliest_event_time,datetime &latest_event_time)
  {
   earliest_event_time = 0;
   latest_event_time = 0;

   if(!FileIsExist(file_name,FILE_COMMON)) return false;

   int h = FileOpen(file_name,FILE_READ|FILE_CSV|FILE_COMMON,",");
   if(h==INVALID_HANDLE) return false;

   for(int i=0; i<9 && !FileIsEnding(h); i++) FileReadString(h); // header

   while(!FileIsEnding(h))
     {
      string time_s = FileReadString(h);
      for(int i=0; i<8 && !FileIsEnding(h); i++) FileReadString(h);
      if(time_s == "") continue;

      datetime t = StringToTime(time_s);
      if(t <= 0) continue;

      if(earliest_event_time == 0) earliest_event_time = t;
      latest_event_time = t;
     }
   FileClose(h);

   return (latest_event_time > 0);
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::ReadBiasHistoryFileStats(const string asset,SBiasAssetSyncResult &result)
  {
   result.asset = asset;
   result.success = false;
   result.total_points = 0;
   result.earliest_time = 0;
   result.latest_time = 0;
   result.error_text = "";

   string file_name = BIAS_FILE+asset+".csv";
   if(!FileIsExist(file_name,FILE_COMMON))
     {
      result.error_text = "File missing";
      return false;
     }

   int h = FileOpen(file_name,FILE_READ|FILE_CSV|FILE_COMMON,",");
   if(h==INVALID_HANDLE)
     {
      result.error_text = "Open error=" + (string)GetLastError();
      return false;
     }

   for(int i=0; i<3 && !FileIsEnding(h); i++) FileReadString(h); // header

   while(!FileIsEnding(h))
     {
      string time_s = FileReadString(h);
      if(!FileIsEnding(h)) FileReadString(h);
      if(!FileIsEnding(h)) FileReadString(h);
      if(time_s == "") continue;

      datetime t = StringToTime(time_s);
      if(t <= 0) continue;

      if(result.total_points == 0) result.earliest_time = t;
      result.latest_time = t;
      result.total_points++;
     }
   FileClose(h);

   result.success = (result.total_points > 0);
   if(!result.success) result.error_text = "No bias points";
   return result.success;
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::BuildBiasHistoryStatus(SBulkBiasSyncResult &result)
  {
   result.success = false;
   result.assets_total = 0;
   result.assets_synced = 0;
   result.assets_failed = 0;
   result.error_text = "";
   ArrayResize(result.asset_results,0);

   string assets[];
   int total = GetGOATSupportedBiasAssets(assets);
   result.assets_total = total;
   ArrayResize(result.asset_results,total);

   for(int i=0; i<total; i++)
     {
      SBiasAssetSyncResult asset_result;
      if(ReadBiasHistoryFileStats(assets[i],asset_result)) result.assets_synced++;
      else                                                 result.assets_failed++;
      result.asset_results[i] = asset_result;
     }

   result.success = (result.assets_synced > 0);
   if(result.assets_failed > 0)
      result.error_text = (string)result.assets_failed + " assets missing or unreadable";
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::ShowBiasHistorySummary(const SBulkBiasSyncResult &result)
  {
   string summary = "AI Bias history";
   summary += "\nAvailable assets: " + (string)result.assets_synced + "/" + (string)result.assets_total;
   if(result.assets_failed > 0) summary += "\nMissing/failed assets: " + (string)result.assets_failed;
   summary += "\n\n";

   int total_assets = ArraySize(result.asset_results);
   int asset_width = 0;
   int points_digits = 1;
   int status_width = 0;
   for(int i = 0; i < total_assets; i++)
     {
      int asset_len = StringLen(result.asset_results[i].asset);
      if(asset_len > asset_width) asset_width = asset_len;

      string points_text = IntegerToString(result.asset_results[i].total_points);
      int points_len = StringLen(points_text);
      if(points_len > points_digits) points_digits = points_len;
     }
   for(int i = 0; i < total_assets; i++)
     {
      string status_field = "FAILED";
      if(result.asset_results[i].success)
        {
         string points_text = IntegerToString(result.asset_results[i].total_points);
         while(StringLen(points_text) < points_digits) points_text = " " + points_text;
         status_field = points_text + " bias points";
        }
      if(StringLen(status_field) > status_width) status_width = StringLen(status_field);
     }

   for(int i = 0; i < total_assets; i++)
     {
      string earliest = (result.asset_results[i].earliest_time == 0) ? "No Date" : TimeToString(result.asset_results[i].earliest_time, TIME_DATE);
      string latest = (result.asset_results[i].latest_time == 0) ? "No Date" : TimeToString(result.asset_results[i].latest_time, TIME_DATE);
      string asset_field = result.asset_results[i].asset;
      while(StringLen(asset_field) < asset_width) asset_field += " ";
      string status_field = "FAILED";
      if(result.asset_results[i].success)
        {
         string points_text = IntegerToString(result.asset_results[i].total_points);
         while(StringLen(points_text) < points_digits) points_text = " " + points_text;
         status_field = points_text + " bias points";
        }
      while(StringLen(status_field) < status_width) status_field += " ";
      summary += asset_field + ": " + status_field + ", Start: " + earliest + ", End: " + latest;
      if(!result.asset_results[i].success && result.asset_results[i].error_text != "")
         summary += " - " + result.asset_results[i].error_text;
      if(i < total_assets - 1) summary += "\n";
     }

   int icon = (result.assets_failed > 0) ? MB_ICONEXCLAMATION : MB_ICONINFORMATION;
   MessageBox(summary, "AI Bias History", MB_OK|icon);
  }
//+------------------------------------------------------------------+
//|  Sync GUI controls with the queue row that the user just clicked  |
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnSelectQueueItem(void)
  {
   /*------------------ 1. Identify the row & extract its INI block --*/
   const int row = m_listQueue.Current();
   if(row < 0) return;                                         // no row selected
   string qTxt = GetFileContent(Path_QueueBatch);              // helper already in codebase
   if(qTxt == "") return;
   string blocks[];
   const int nBlocks = StringSplit(qTxt,(ushort)31,blocks);
   if(row >= nBlocks) return;
   string block = blocks[row];
   /* drop the leading “;Pending_…;” line so we only have key=value */
   int pos = StringFind(block,"\n");
   if(pos < 0) return;
   string ini = StringSubstr(block,pos+1);
   /*------------------ 2. Parse key=value lines --------------------*/
   string liness[];
   const int nLines = StringSplit(ini,'\n',liness);
   for(int i=0;i<nLines;i++)
   {
      string kv[];
      if(StringSplit(liness[i],'=',kv) != 2) continue;
      string key = StringTrim(kv[0]);
      string val = StringTrim(kv[1]);
      /* ---- basic symbol / TF / dates -------------------------------- */
      if(key == "Symbol")              m_cmbSymbol .SelectByText(val);
      else if(key == "Period")         m_cmbPeriod .SelectByText(val);
      else if(key == "FromDate")       m_dtFrom    .Value((datetime)StringToTime(val));
      else if(key == "ToDate")         m_dtTo      .Value((datetime)StringToTime(val));
      /* ---- forward settings ----------------------------------------- */
      else if(key == "ForwardMode")
      {
         int fm = (int)StringToInteger(val);
         string fmTxt = (fm==0)?  "No"
                      : (fm==1)?  "1/2"
                      : (fm==2)?  "1/3"
                      : (fm==3)?  "1/4"
                      :            "Custom";
         m_cmbForward.SelectByText(fmTxt);
         OnChange_cmbForward();                              // keep dtForward logic
      }
      else if(key == "ForwardDate" && m_cmbForward.Select()=="Custom") m_dtForward.Value((datetime)StringToTime(val));
      /* ---- modelling & delays --------------------------------------- */
      else if(key == "Model")
      {
         int m = (int)StringToInteger(val);
         string mTxt = (m==0)?  "Every tick"
                     : (m==1)?  "1 minute OHLC"
                     : (m==2)?  "Open prices only"
                     :           "Every tick based on real ticks";
         m_cmbModel.SelectByText(mTxt);
      }
      else if(key == "ExecutionMode")
      {
         int d = (int)StringToInteger(val);                   // latency in ms
         string dTxt = (d==0) ? "Zero latency, ideal execution": (string)d + " ms delay";
         m_cmbDelay.SelectByText(dTxt);
      }
      /* ---- optimisation type ---------------------------------------- */
      else if(key == "Optimization") {m_cmbOptimization.SelectByText((val=="2") ? "Fast genetic based algorithm" : "Disabled");}
      /* ---- money management fields ---------------------------------- */
      else if(key == "Deposit")         m_edtDeposit .Text(val);
      else if(key == "Currency")        m_edtCurrency.Text(val);
      else if(key == "Leverage")        m_cmbLeverage.SelectByText("1:"+val);
   }
   ChartRedraw();                                               // instant UI update
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickSelectFile()
  {
   if(Strategy!="")
   {
    int ret = MessageBox("A set file is already selected.\nStrategy name: "+Strategy+"\n\nDo you want to select another?","Warning",MB_OKCANCEL|MB_ICONQUESTION);
    if(ret==IDCANCEL) return;
   }
   string Filenames[];
   int ret = FileSelectDialog("Select a "+Key_+" set or portfolio batch", NULL, "GOAT files (*.set;*.goatbatch)|*.set;*.goatbatch|Set files (*.set)|*.set|Portfolio batch files (*.goatbatch)|*.goatbatch|All files (*.*)|*.*" , FSD_FILE_MUST_EXIST|FSD_COMMON_FOLDER , Filenames, NULL); //FSD_ALLOW_MULTISELECT
   if(ret>0)
   {
     string picked=Filenames[0];
     string pickedLower=picked;
     StringToLower(pickedLower);
     if(EndsWith(pickedLower,".goatbatch"))
     {
      LoadBatchPackage(picked);
      return;
     }
     SBatchProgressStats stats;
     bool forceNewRun=false;
     if(ReadBatchProgressStats(Path_QueueBatch,stats) && stats.total>0 && stats.pending+stats.queued+stats.ongoing==0)
        forceNewRun=true;
     if(!EnsureRunContext(forceNewRun)) {MessageBox("Unable to create or recover an Optimization Run folder.","Error",MB_OK|MB_ICONERROR); return;}
      string savedStrategy="";
      if(!SaveStrategyInputsFromSet(picked,savedStrategy))
        {
         MessageBox("Unable to read and save strategy inputs from the selected "+Key_+" set file.\n\nFile:\n"+picked,"Error",MB_OK|MB_ICONERROR);
         return;
        }
      Strategy=savedStrategy;
      m_selectedSetPath=picked;
      m_edtStrategy.Text(Strategy);

      string strategyDir = GoatOptStrategyDir(EA_Name_,Server_,Strategy);
      EnsureCommonFolderTree(strategyDir);
      Path_QueueStrategy=strategyDir+"\\Queue."+Key_;
      string QueueContent_Strategy = GetFileContent(Path_QueueStrategy);
      if(QueueContent_Strategy!="")
        {
         int addRet = MessageBox("Some Queue Items already present.\nStrategy name: "+Strategy+"\n\nDo you want to add the items?","Warning",MB_OKCANCEL|MB_ICONQUESTION);
         if(addRet==IDOK)
           {
            string QueueContent_Batch=GetFileContent(Path_QueueBatch);
            QueueContent_Batch+=QueueContent_Strategy;
            int batchHandle = FileOpen(Path_QueueBatch,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
            if(batchHandle!=INVALID_HANDLE)
              {
               FileWrite(batchHandle,QueueContent_Batch);
               FileClose(batchHandle);
               OnClickRefresh(true);
              }
           }
        }

     if(Strategy=="") {MessageBox("No Strategy name or reference comment found. Invalid "+Key_+" set file.","Error",MB_OK|MB_ICONERROR); return;}
     int tailStart=(int)MathMax(0,StringLen(picked)-35);
     m_edtSetFile.Text(StringSubstr(picked,tailStart,-1));
     SaveCurrentBatchPackage();
     OnClickRefresh(true);
    }
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::AddQueueSingle(void)
  {
   if(Strategy=="") {MessageBox("Select a "+Key_+" set file first.","Error",MB_OK|MB_ICONERROR); return;}
   if(!EnsureRunContext(false)) {MessageBox("Unable to create or recover an Optimization Run folder.","Error",MB_OK|MB_ICONERROR); return;}
   string strategyDir=GoatOptStrategyDir(EA_Name_,Server_,Strategy);
   Path_QueueStrategy=strategyDir+"\\Queue."+Key_;
   EnsureCommonFolderTree(strategyDir);

   string inputMessage="";
   if(!EnsureInputsForStrategy(Strategy,inputMessage))
     {
      MessageBox(inputMessage,"Error",MB_OK|MB_ICONERROR);
      return;
     }

   string item=GetTESTERsettingsString();
   
   string QueueContent_Batch   =GetFileContent(Path_QueueBatch);
   string QueueContent_Strategy=GetFileContent(Path_QueueStrategy);
   
   QueueContent_Batch+=item+CharToString(31)+"\r\n";//((QueueContent=="")?"":"\n"); //Print(QueueContent);
   
   int handle = FileOpen(Path_QueueBatch,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);  // it overwrites the entire file
   if(handle==INVALID_HANDLE)
   {
    MessageBox("Unable to update the batch queue file.","Error",MB_OK|MB_ICONERROR);
    return;
   }
   FileWrite(handle,QueueContent_Batch); FileClose(handle);
   
   if(StringFind(QueueContent_Strategy,item)==-1)
   {
    QueueContent_Strategy+=item+CharToString(31)+"\r\n";//((QueueContent=="")?"":"\n"); //Print(QueueContent);

     int handle = FileOpen(Path_QueueStrategy,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);  // it overwrites the entire file
     if(handle==INVALID_HANDLE)
     {
      MessageBox("Unable to update the strategy queue file.","Error",MB_OK|MB_ICONERROR);
      return;
     }
     FileWrite(handle,QueueContent_Strategy); FileClose(handle);
    }
   SaveCurrentBatchPackage();
   OnClickRefresh(true,true);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickAddQueue(void)
  {
   if(Strategy=="") {MessageBox("Select a "+Key_+" set file first.","Error",MB_OK|MB_ICONERROR); return;}

   const string sel = m_cmbSymbol.Select();
   // If user picked a preset display item, resolve to real file
   string presetFile = ResolvePresetFileByDisplay(sel);
   if(presetFile != "")
   {
      string syms[];
      if(!LoadSymbolsFromPreset(Key_, presetFile, syms) || ArraySize(syms)==0)
      {
         MessageBox("Preset file is empty or cannot be read:\n"+presetFile,"Error",MB_OK|MB_ICONERROR);
         return;
      }
      int added = 0;
      for(int i=0;i<ArraySize(syms);i++)
      {
         string sym = syms[i];
         StringTrimLeft(sym); StringTrimRight(sym);
         if(sym=="") continue;
         // Ensure symbol exists in combo (covers symbols not in Market Watch list)
         if(!m_cmbSymbol.SelectByText(sym))
         {
            m_cmbSymbol.AddItem(sym);
            m_cmbSymbol.SelectByText(sym);
         }
         AddQueueSingle();
         added++;
      }
      MessageBox((string)added+" item(s) added from preset: "+StripTxtExt(presetFile),"Info",MB_OK|MB_ICONINFORMATION);
      return;
   }
   // Not a preset -> single-add (original behaviour)
   AddQueueSingle();
}
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickSetPresets(void)
{
   // Make sure default file/folder exists
   EnsureAllSymbolsPresetExists(Key_);
   // Absolute path for the MessageBox + ShellExecute
   string folderAbs = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + Key_ + "\\Symbol Presets\\";

   string msg =
      "This will open your Presets folder.\n\n"
      "• Edit *.txt files here to define symbol lists.\n"
      "• One symbol per line; commas or spaces on a line are also OK.\n"
      "• Lines starting with # or // are ignored.\n\n"
      "• File names must have the word preset in the name.\n\n"
      "Folder:\n" + folderAbs;
   MessageBox(msg, "Open Presets Folder", MB_OK|MB_ICONINFORMATION);
   // Open the folder in the OS file explorer
   int r = ShellExecuteW(0, "open", folderAbs, NULL, NULL, 1);
   // If needed, you could fallback to running Explorer manually:
   // if(r <= 32) { /* optional WinExec fallback if you import it */ }
}
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickDelQ(void)
  {
   if(FileIsExist(Path_QueueBatch,FILE_COMMON)) FileDelete(Path_QueueBatch,FILE_COMMON);//FILE_TXT
   else             MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR);
   
   if(FileIsExist(Key_+"\\OnGoingBatch."+Key_,FILE_COMMON)) FileDelete(Key_+"\\OnGoingBatch."+Key_,FILE_COMMON);//FILE_TXT
   GlobalVariableDel("BatchOnGoing");
   GlobalVariableDel("TerminalRunning");
   if(Path_RunFolder!="")
   {
      FileDelete(GoatOptActivePointerPath(EA_Name_,Server_),FILE_COMMON);
      g_goat_opt_active_run_path="";
      RefreshRunPaths();
   }
   OnClickRefresh(true,true);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickDelQitem()
  {
   string QueueContent=GetFileContent(Path_QueueBatch);
   
   if(m_listQueue.Current()==-1) 
   {
    MessageBox("No Item selected.","Error",MB_OK|MB_ICONERROR); return;
   }
   if(QueueContent=="")
   {
    MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR); return;
   }
   string results[];
   int total=StringSplit(QueueContent, (ushort)31, results);
   
   for(int i=0;i<total;i++)
   {
    if(m_listQueue.Current()==i)
    {
     results[i]="";//if(StringSplit(results[i],';',res)==3)
    }
   }
   ReconstructFile(Path_QueueBatch,results);
   OnClickRefresh(true,true);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickUpSelectedItem(void)
  {
   int idx = m_listQueue.Current();
   if(idx < 0)  { MessageBox("No Item selected.","Error",MB_OK|MB_ICONERROR); return; }
   if(idx == 0) return;                               // already at top

   string content = GetFileContent(Path_QueueBatch);
   if(content == "") { MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR); return; }

   string rows[];
   int total = StringSplit(content,(ushort)31,rows);
   if(idx >= total) return;

   // swap the two neighbouring rows
   string tmp      = rows[idx-1];
   rows[idx-1]     = rows[idx];
   rows[idx]       = tmp;

   ReconstructFile(Path_QueueBatch,rows);                 // write back
   OnClickRefresh(true,false);                        // redraw list
   m_listQueue.Select(idx-1);                         // re-select row
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickDownSelectedItem(void)
  {
   int idx = m_listQueue.Current();
   if(idx < 0)  { MessageBox("No Item selected.","Error",MB_OK|MB_ICONERROR); return; }

   string content = GetFileContent(Path_QueueBatch);
   if(content == "") { MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR); return; }

   string rows[];
   int total = StringSplit(content,(ushort)31,rows);
   if(idx >= total-1) return;                         // already at bottom

   // swap with the one below
   string tmp      = rows[idx+1];
   rows[idx+1]     = rows[idx];
   rows[idx]       = tmp;

   ReconstructFile(Path_QueueBatch,rows);
   OnClickRefresh(true,false);
   m_listQueue.Select(idx+1);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickCancelSelectedItem(void)
  {
   int idx=m_listQueue.Current();
   if(idx<0)
     {
      MessageBox("No Item selected.","Error",MB_OK|MB_ICONERROR);
      return;
     }
   ChangeItemTo(idx,"Cancelled"); WriteLog("❌ Batch Item Cancelled ❌",false,Key_,EA_Name_,Server_);
   OnClickRefresh(true,false);
   m_listQueue.Select(idx);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickMakeSelectedPending(void)
  {
   int idx=m_listQueue.Current();
   if(idx<0)
     {
      MessageBox("No Item selected.","Error",MB_OK|MB_ICONERROR);
      return;
     }
   ChangeItemTo(idx,"Pending");
   OnClickRefresh(true,false);
   m_listQueue.Select(idx);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickRefresh(bool init=false, bool select=false)
  {
   RefreshNewsSyncButton();
   string QueueContent=GetFileContent(Path_QueueBatch);
   
   m_listQueue.ItemsClear();
   if(QueueContent=="")
   {
    UpdateBatchProgressText();
    if(!init) MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR);
    return;
   }
   //for(int i=15;i>=0;i--) m_listQueue.TotalView   ItemDelete(i);
   string results[];
   int total=StringSplit(QueueContent, (ushort)31, results);
   ReconstructFile(Path_QueueBatch,results);
   
   int added=0;
   int select_index=-1;
   for(int i=0;i<total;i++)
   {
    string res[];
    if(StringSplit(results[i],';',res)==3)
    {
     if(m_listQueue.AddItem(res[1]))
     {
          if(StringFind(res[1],"Completed",0)>=0) {}//m_listQueue.ItemColorsFHD(added,clrGreen);}
     else if(StringFind(res[1],"OnGoing"  ,0)>=0) select_index=added;
     else                                         {}//m_listQueue.ItemColorsFHD(added,clrBlack);}
      added++;
     }
     //m_edtQueue[i].Text(res[1]); // error array out of bound
     //     if(StringFind(res[1],"Completed",0)>=0) m_edtQueue[i].Color(clrGreen);
     //else if(StringFind(res[1],"OnGoing"  ,0)>=0) m_edtQueue[i].Color(clrRed);
     //else                                         m_edtQueue[i].Color(clrBlack);
    }
   }
   if(select && added>0 && select_index<0) select_index=added-1;  // Select the latest displayed entry
   if(select_index>=0) m_listQueue.Select(select_index);
   // ItemsClear() hides the list scrollbar; show after refill so overflow is visible again.
   m_listQueue.Show();
   RefreshBatchStartButtonState();
   ChartRedraw(m_chart_id);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickSyncBias(void)
  {
   if(m_dataSyncBusy) return;
   m_dataSyncBusy = true;

   Bias.Key_ = Key_;
   m_btnSyncBias.Text("Sync Running...");
   m_btnSyncBias.Color(clrWhite);
   m_btnSyncBias.ColorBackground(C'210,105,30');
   m_btnSyncBias.ColorBorder(clrBlack);
   ChartRedraw();
   MessageBox("AI Bias history sync started.\n\nThis can take up to one minute.", "Data Sync", MB_OK|MB_ICONINFORMATION);

   SBulkBiasSyncResult result;
   bool sync_ok = Bias.SyncAllBiasHistory(result);

   m_dataSyncBusy = false;
   m_btnSyncBias.Text("Sync AI Bias History");
   m_btnSyncBias.Color(clrPaleTurquoise);
   m_btnSyncBias.ColorBackground(C'15,23,42');
   m_btnSyncBias.ColorBorder(clrBlack);
   RefreshNewsSyncButton();

   if(!sync_ok && result.assets_synced == 0)
     {
      string msg = "AI Bias history sync failed";
      if(result.error_text != "") msg += "\n\n" + result.error_text;
      MessageBox(msg, "AI Bias History", MB_OK|MB_ICONERROR);
      return;
     }

   ShowBiasHistorySummary(result);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickViewBias(void)
  {
   if(m_dataSyncBusy) return;

   SBulkBiasSyncResult result;
   BuildBiasHistoryStatus(result);
   ShowBiasHistorySummary(result);
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::RefreshNewsSyncButton(void)
  {
   if(m_compactLayout) return;
   datetime latest = 0;
   bool stale = IsNewsHistoryStale(NEWS_FILE, latest);

   if(stale)
     {
      m_btnSyncNews.Text("Sync News History");
      m_btnSyncNews.Color(clrWhite);
      m_btnSyncNews.ColorBackground(C'210,105,30');
      m_btnSyncNews.ColorBorder(clrBlack);
     }
   else
     {
      m_btnSyncNews.Text("News Fresh: " + TimeToString(latest, TIME_DATE));
      m_btnSyncNews.Color(clrWhite);
      m_btnSyncNews.ColorBackground(C'46,139,87');
      m_btnSyncNews.ColorBorder(clrBlack);
     }
   ChartRedraw();
   }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::HasActiveBatchQueueItem(void)
  {
   string QueueContent=GetFileContent(Path_QueueBatch);
   if(QueueContent=="") return false;

   string QueueItems[];
   int total=StringSplit(QueueContent,(ushort)31,QueueItems);
   for(int i=0;i<total;i++)
   {
    string item=QueueItems[i];
    StringTrimLeft(item);
    StringTrimRight(item);
    if(item=="") continue;

    string parts[];
    if(StringSplit(item,';',parts)==3)
    {
     if(StringFind(parts[1],"OnGoing",0)>=0 || StringFind(parts[1],"Queued",0)>=0) return true;
    }
    else if(StringFind(item,"OnGoing",0)>=0 || StringFind(item,"Queued",0)>=0) return true;
   }
   return false;
  }
//+------------------------------------------------------------------+
bool CStrategyTesterDialog::ResolveBatchRunningState(const bool clearStale)
  {
   if(GlobalVariableGet("BatchOnGoing")==0.0) return false;
   if(HasActiveBatchQueueItem()) return true;

   if(clearStale)
   {
    GlobalVariableDel("BatchOnGoing");
    GlobalVariableDel("TerminalRunning");
    WriteLog("Cleared stale BatchOnGoing flag: queue has no Queued or OnGoing item.",true,Key_,EA_Name_,Server_);
   }
   return false;
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::RefreshBatchStartButtonState(void)
  {
   m_batchRunning=ResolveBatchRunningState(true);
   m_btnStart.Text(m_batchRunning ? "RUNNING" : "START BATCH");
   if(m_batchRunning) m_btnStart.Disable();
   else               m_btnStart.Enable();
   UpdateBatchProgressText();
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::UpdateBatchProgressText(void)
  {
   SBatchProgressStats stats;
   bool loaded=ReadBatchProgressStats(Path_QueueBatch,stats);
   m_edtBatchProgress.Text(FormatBatchProgressText(stats,loaded));
   if(loaded && stats.errors>0)
      m_edtBatchProgress.ColorBackground(C'122,63,34');
   else if(loaded && stats.total>0 && stats.completed+stats.errors+stats.cancelled>=stats.total)
      m_edtBatchProgress.ColorBackground(C'46,139,87');
   else
      m_edtBatchProgress.ColorBackground(C'47,74,111');
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickSyncNews(void)
  {
   if(m_dataSyncBusy) return;
   News.Key_ = Key_;

   datetime earliest = 0;
   datetime latest = 0;
   ReadNewsHistoryRange(NEWS_FILE,earliest,latest);
   if(!IsNewsHistoryStale(NEWS_FILE, latest) && latest > 0)
     {
      string start_stamp = (earliest == 0) ? "No Date" : TimeToString(earliest, TIME_DATE);
      string end_stamp = TimeToString(latest, TIME_DATE|TIME_MINUTES);
      MessageBox("News history is up to date.\n\nStart: " + start_stamp + "\nEnd: " + end_stamp, "News History", MB_OK|MB_ICONINFORMATION);
      RefreshNewsSyncButton();
      return;
     }

   m_dataSyncBusy = true;
   m_btnSyncNews.Text("Sync Running...");
   m_btnSyncNews.Color(clrWhite);
   m_btnSyncNews.ColorBackground(C'210,105,30');
   m_btnSyncNews.ColorBorder(clrBlack);
   ChartRedraw();
   MessageBox("News history sync started.\n\nThis can take up to one minute.", "Data Sync", MB_OK|MB_ICONINFORMATION);

   SNewsSyncResult result;
   bool sync_ok = News.SyncFullHistory(result);

   m_dataSyncBusy = false;
   if(!sync_ok)
     {
      string msg = "News history sync failed";
      if(result.error_text != "") msg += "\n\n" + result.error_text;
      MessageBox(msg, "News History", MB_OK|MB_ICONERROR);
      RefreshNewsSyncButton();
      return;
     }

   earliest = 0;
   latest = 0;
   ReadNewsHistoryRange(NEWS_FILE,earliest,latest);
   string start_stamp = (earliest == 0) ? "No Date" : TimeToString(earliest, TIME_DATE);
   string end_stamp = (latest == 0 && result.latest_event_time > 0) ? TimeToString(result.latest_event_time, TIME_DATE|TIME_MINUTES)
                                                                     : ((latest == 0) ? "No Date" : TimeToString(latest, TIME_DATE|TIME_MINUTES));
   MessageBox("News history is up to date.\n\nStart: " + start_stamp + "\nEnd: " + end_stamp, "News History", MB_OK|MB_ICONINFORMATION);
   RefreshNewsSyncButton();
  }
//+------------------------------------------------------------------+
//|  Batch-Start button - final version (news-file check included)   |
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickStart(void)
  {
   if(!EnsureRunContext(false)) {MessageBox("Unable to create or recover an Optimization Run folder.","Error",MB_OK|MB_ICONERROR); return;}
   if(ResolveBatchRunningState(true)) {MessageBox("Batch is already running.","Info",MB_OK|MB_ICONINFORMATION); return;}
   if(!FileIsExist(Path_QueueBatch,FILE_COMMON)) {MessageBox("No Queue file found.","Error",MB_OK|MB_ICONERROR); return;}
   News.Key_ = Key_;
   Bias.Key_ = Key_;
   /* -------- 1)  make sure the economic-news CSV is fresh -------- */
   if(!EnsureFreshNewsFile(NEWS_FILE)) return; // user cancelled or hard error
   
   string QueueContent=GetFileContent(Path_QueueBatch);
   
   string QueueItems[];
   int pend=0,total=StringSplit(QueueContent, (ushort)31, QueueItems);
   for(int i=0;i<total;i++)
   {
    string res[];
    if(StringSplit(QueueItems[i],';',res)==3) if(StringFind(res[1],"Pending",0)>=0) pend++;
   }
   if(QueueContent==""||StringLen(QueueContent)<9||pend==0) {MessageBox("Batch Queue File is Empty or no pending item found","Error",MB_OK|MB_ICONERROR); return;}

   string preflightMessage="";
   if(!PreflightQueueInputs(QueueContent,preflightMessage))
     {
      MessageBox(preflightMessage,"Error",MB_OK|MB_ICONERROR);
      return;
     }

   // 2) export-settings -------------------------------------------------
   string exportSettings = GetExportSettingsString();        // <-- NEW
   int handle = FileOpen(Path_ExportSettings,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);  // it overwrites the entire file
   FileWrite(handle,exportSettings); FileClose(handle);
   SaveCurrentBatchPackage();

   int ret = MessageBox((string)pend+" Pending Queue Items Found.\n\nTerminal will restart, start batch now?","Info",MB_OKCANCEL|MB_ICONQUESTION);
   if(ret==IDCANCEL) return;
   
   WriteLog("🔵🔵🔵🔵🔵 Batch Start clicked and accepted 🔵🔵🔵🔵🔵",false,Key_,EA_Name_,Server_);
   GoatOptAppendTimeline(EA_Name_,Server_,"BATCH_START_CLICKED","Batch","Accepted",(string)pend+" pending item(s)");
   
   if(UpdateBatchQueueAndWriteConfigFile(false,false,Key_,EA_Name_,Server_))
   {
    WriteLog((string)pend+" Pending Queue Items Found.",false,Key_,EA_Name_,Server_);
    WriteLog("Batch Start clicked and started. Terminal Restart Initiated.",false,Key_,EA_Name_,Server_);
    GlobalVariableSet("GOAT_OPT_STUDIO_WIDTH",(double)D_Width);
    GlobalVariableSet("GOAT_OPT_STUDIO_HEIGHT",(double)D_Height);
    GlobalVariableSet("GOAT_OPT_STUDIO_FONT",(double)Font_Size);
    GlobalVariableSet("BatchOnGoing",1.0);
    RefreshBatchStartButtonState();
    //MessageBox("Terminal will restart now.","Info",MB_OK|MB_ICONINFORMATION);
    GlobalVariableDel("TerminalRunning");
    Sleep(500); TerminalClose(99);
   }
   else WriteLog("Batch Start clicked but could not start.",true,Key_,EA_Name_,Server_);
   //else MessageBox("OnGoing Batch file found.","Error",MB_OK|MB_ICONERROR);
   //else {Print("No more tasks found in the queue for strategy: ", Strategy);}
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::OnClickStop(void)
  {
   string fileContent = GetFileContent(Path_QueueBatch);
   if(fileContent=="")
   {
      MessageBox("No queue file found.","Error",MB_OK|MB_ICONERROR);
      return;
   }
   string items[];
   int    total = StringSplit(fileContent,(ushort)31,items);
   int pendingCount = 0;
   for(int i=0;i<total;i++)
   {
      string parts[];
      if(StringSplit(items[i],';',parts)==3 && StringFind(parts[1],"Pending",0)==0) pendingCount++;
   }
   GlobalVariableDel("TerminalRunning");
   if(pendingCount==0)
   {
      RefreshBatchStartButtonState();
      MessageBox("No Pending items found.","Info",MB_OK|MB_ICONINFORMATION); return;
   }
   string warn = StringFormat("All %d pending items will be cancelled.\n\nContinue?",pendingCount);
   int    res  = MessageBox(warn,"Confirmation",MB_YESNO|MB_ICONWARNING);
   if(res!=IDYES) return;
   bool changed = false;
   for(int i=0;i<total;i++)
   {
      string parts[];
      if(StringSplit(items[i],';',parts)==3)
      {
         if(StringFind(parts[1],"Pending",0)==0)
         {
            int underscore = StringFind(parts[1],"_");
            parts[1] = (underscore>=0) ? "Cancelled"+StringSubstr(parts[1],underscore): "Cancelled";
            items[i] = ";" + parts[1] + ";" + parts[2];
            changed  = true;
         }
      }
   }
   if(changed)
   {
      WriteLog("❌❌❌❌❌ Batch Terminated ❌❌❌❌❌",false,Key_,EA_Name_,Server_);
      ReconstructFile(Path_QueueBatch,items);
      OnClickRefresh(true,true);
      MessageBox(StringFormat("%d item(s) were cancelled.\nFeel Free to stop any running optimization.\nExports sequence wont run.",pendingCount),"Info",MB_OK|MB_ICONINFORMATION);
   }
  }
//+------------------------------------------------------------------+
void CStrategyTesterDialog::ChangeItemTo(const int index,const string newState)
  {
   string QueueContent=GetFileContent(Path_QueueBatch);
   if(QueueContent=="") return;
   string results[];
   int total=StringSplit(QueueContent,(ushort)31,results);
   if(index<0 || index>=total) return;
   string res[];
   if(StringSplit(results[index],';',res)==3)
   {
    // Extract whatever is after the first underscore, then reassign
    int pos=StringFind(res[1],"_",0);
    if(pos>=0)
    {
     string tail=StringSubstr(res[1],pos);
     res[1]=newState+tail;
    }
    else
    {
     // If no underscore was found, just override the entire field
     res[1]=newState;
    }
    results[index]=";"+res[1]+";"+res[2];
   }
   ReconstructFile(Path_QueueBatch,results);
  }
//+------------------------------------------------------------------+
bool UpdateBatchQueueAndWriteConfigFile(bool init,bool error,string Key_,string EA_Name_,string Server_)
  {
   string Path_QueueBatch = GoatOptQueuePath(EA_Name_,Server_);
   string QueueContent=GetFileContent(Path_QueueBatch);//TesterDialog.Path_QueueBatch);
   
   if(QueueContent=="") {WriteLog("Batch Queue File is Empty or does not exist.",true,Key_,EA_Name_,Server_); return false;}
   
   string QueueItems[];
   int total=StringSplit(QueueContent, (ushort)31, QueueItems); if(total<1) {WriteLog("No Items found in Batch Queue File.",true,Key_,EA_Name_,Server_); return false;}
   
   int ongoingIndex=-1, pendingIndex=-1, QueuedIndex=-1;
   
   for(int i=0; i<total; i++)
   {
    if(StringFind(QueueItems[i], "OnGoing", 0) >= 0)                    ongoingIndex = i;
    if(StringFind(QueueItems[i], "Pending", 0) >= 0 && pendingIndex<0)  pendingIndex = i;
    if(StringFind(QueueItems[i], "Queued" , 0) >= 0)                    QueuedIndex = i;
   }
   
   if(init)
   {
    if(ongoingIndex >= 0)
    {
     if(QueueItemMatchesCurrentRun(QueueItems[ongoingIndex]))
     {
      WriteLog("INIT: Recovered existing OnGoing queue item after terminal relaunch: "+QueueItems[ongoingIndex],false,Key_,EA_Name_,Server_);
      return true;
     }
     WriteLog("INIT: OnGoing queue item does not match current optimization. Queue="+QueueItemTitle(QueueItems[ongoingIndex])+
              " Current="+Symbol()+":"+ActiveQueueStrategyName(),true,Key_,EA_Name_,Server_);
     return false;
    }
    if(QueuedIndex  >= 0)
    {
     StringReplace(QueueItems[QueuedIndex] , "Queued", "OnGoing"); StringTrimLeft(QueueItems[QueuedIndex]);
     WriteLog("Queued->OnGoing: "+QueueItems[QueuedIndex],false,Key_,EA_Name_,Server_);
     GoatOptAppendTimeline(EA_Name_,Server_,"QUEUE_STATE",QueueItemTitle(QueueItems[QueuedIndex]),"OnGoing","Queued item recovered after restart");
     ReconstructFile(Path_QueueBatch,QueueItems);
     return true;
    }
   }
   else
   {
    if(ongoingIndex >= 0)
    {
     string status="Completed";
     if(error) status="Error";
     StringReplace(QueueItems[ongoingIndex], "OnGoing", status); StringTrimLeft(QueueItems[ongoingIndex]);
     WriteLog("OnGoing->"+status+": "+QueueItems[ongoingIndex],false,Key_,EA_Name_,Server_);
     GoatOptAppendTimeline(EA_Name_,Server_,"QUEUE_STATE",QueueItemTitle(QueueItems[ongoingIndex]),status,"Optimization item finished");
    }
    if(pendingIndex >= 0)
    {
      StringReplace(QueueItems[pendingIndex], "Pending", "Queued"); StringTrimLeft(QueueItems[pendingIndex]);
      WriteLog("Pending->Queued: "+QueueItems[pendingIndex],false,Key_,EA_Name_,Server_);
      GoatOptAppendTimeline(EA_Name_,Server_,"QUEUE_STATE",QueueItemTitle(QueueItems[pendingIndex]),"Queued","Next pending item queued");
      ReconstructFile(Path_QueueBatch,QueueItems);
      if(ActivatePending(QueueItems[pendingIndex],Key_,EA_Name_,Server_))
         return true;

      StringReplace(QueueItems[pendingIndex], "Queued", "Pending"); StringTrimLeft(QueueItems[pendingIndex]);
      WriteLog("Queued activation failed; restored item to Pending: "+QueueItems[pendingIndex],true,Key_,EA_Name_,Server_);
      GoatOptAppendTimeline(EA_Name_,Server_,"QUEUE_STATE",QueueItemTitle(QueueItems[pendingIndex]),"Pending","Activation failed; restored to Pending");
      ReconstructFile(Path_QueueBatch,QueueItems);
      return false;
     }
    else
    {
     GlobalVariableDel("BatchOnGoing");
     ReconstructFile(Path_QueueBatch,QueueItems);
     return true;
    }
   }
   //if(ongoingIndex>=0) {ActivatePending("",Key_,EA_Name_,Server_); return true;}
   /*
   for(int i=0;i<total-1;i++)
   {
    if(StringFind(QueueItems[i],"Pending")>0)
    {
     if(init)
     {
      if(i==0)
      {
       StringReplace(QueueItems[i],"Pending","OnGoing");
       ReconstructFile(Key_+"\\"+Strategy+"\\Queue."+Key_,QueueItems);
       return UpdateBatchQueueAndWriteConfigFile(false);
      }
      else if(StringFind(QueueItems[i-1],"OnGoing")>0)//i!=0 && QueueContent)
      {
       StringReplace(QueueItems[i-1],"OnGoing","Completed");
       StringReplace(QueueItems[i],"Pending","OnGoing");
       ReconstructFile(Key_+"\\"+Strategy+"\\Queue."+Key_,QueueItems);
       return UpdateBatchQueueAndWriteConfigFile(false);
      }
     }
     else
     {
      return ActivatePending(QueueItems[pendingIndex]);
     }
    }
   }*/
   return false;
  }
//+------------------------------------------------------------------+
bool ActivatePending(string QueueItem,string Key_,string EA_Name_,string Server_)
  {
   QueueItem = RepairTesterExpertPath(QueueItem);
   int ret = StringFind(QueueItem, ":"); if(ret <= 0) {WriteLog("Cannot Activate Queue Item: "+QueueItem,true,Key_,EA_Name_,Server_); return false;}
   Strategy = StringSubstr(QueueItem,ret+1);
   
   string temp = StringSubstr(QueueItem, ret + 1);
   
   ret = StringFind(temp, ";"); if(ret <= 0) {WriteLog("Cannot Activate Queue Item: "+QueueItem,true,Key_,EA_Name_,Server_); return false;}
   Strategy = NormalizeStrategyName(StringSubstr(temp,0,ret));
   string strategyDir = GoatOptStrategyDir(EA_Name_,Server_,Strategy);
   string inputsPath  = strategyDir+"\\Inputs."+Key_;
   EnsureCommonFolderTree(strategyDir);
   string testerInputs = GetFileContent(inputsPath);
   if(testerInputs=="") {WriteLog("Cannot Activate Queue Item. Inputs file missing or empty: "+inputsPath,true,Key_,EA_Name_,Server_); return false;}
   //StringTrimLeft(QueueItem); StringTrimRight(QueueItem);
   int handle = FileOpen(strategyDir+"\\config.ini",FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
    if(QueueItem=="") FileWrite(handle,QueueItem);
    else              FileWrite(handle,QueueItem+"\n[TesterInputs]\n"+testerInputs);
    FileClose(handle);
    AddCommand(strategyDir);
    return true;
   }
   WriteLog("Cannot create config.ini for Queue Item: "+strategyDir,true,Key_,EA_Name_,Server_);
   return false;
  }
//+------------------------------------------------------------------+
bool EnsureCommonFolderTree(string path)
  {
   StringReplace(path,"/","\\");
   while(StringFind(path,"\\\\")>=0) StringReplace(path,"\\\\","\\");
   string parts[];
   int total=StringSplit(path,'\\',parts);
   if(total<1) return false;

   string current="";
   for(int i=0;i<total;i++)
   {
    if(parts[i]=="") continue;
    if(current!="") current+="\\";
    current+=parts[i];
    FolderCreate(current,FILE_COMMON);
   }
   return true;
  }
//+------------------------------------------------------------------+
string NormalizeStrategyName(string s)
  {
   StringTrimLeft(s);
   StringTrimRight(s);

   string out="";
   for(int i=0;i<StringLen(s);i++)
   {
    ushort ch=(ushort)StringGetCharacter(s,i);
    if(ch<32) continue;
    if(ch=='<' || ch=='>' || ch==':' || ch=='\"' || ch=='/' || ch=='\\' || ch=='|' || ch=='?' || ch=='*')
      out+="_";
    else
      out+=ShortToString((short)ch);
   }
   StringTrimLeft(out);
   StringTrimRight(out);
   return out;
  }
//+------------------------------------------------------------------+
string GetFileContent(string FileName)
  {
   int handle=FileOpen(FileName,FILE_READ|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
   if(handle==INVALID_HANDLE) return "";
   
   string content = "";
   while(!FileIsEnding(handle))
   {
    string line = FileReadString(handle);
    content += line;
    if(!FileIsEnding(handle)) content += "\n";
   }
   FileClose(handle);
   StringTrimLeft(content); //StringTrimRight(content);
   return content;
  }
//+------------------------------------------------------------------+
void ReconstructFile(string FileName,string &SubStrings[])
  {
   string str="";
   for(int i=0;i<ArraySize(SubStrings);i++)
   if(SubStrings[i]!=""&& StringLen(SubStrings[i])>9)
   {
    StringTrimLeft(SubStrings[i]); StringTrimRight(SubStrings[i]);
    str+=SubStrings[i]+CharToString((ushort)31)+"\n";
  //str+=SubStrings[i]+((i<ArraySize(SubStrings)-1)?CharToString((ushort)31):"");
   }
   int handle=FileOpen(FileName,FILE_WRITE|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
    StringTrimLeft(str); StringTrimRight(str);
    FileWrite(handle, str);
    FileClose(handle);
   }
  }
//+------------------------------------------------------------------+
bool EndsWith(const string s,const string suf)
{
   const int ls=(int)StringLen(s), lf=(int)StringLen(suf);
   if(ls<lf) return(false);
   return(StringSubstr(s,ls-lf)==suf);
}
//+------------------------------------------------------------------+
// Case-insensitive "contains"                                  // NEW
bool ContainsNoCase(string s,string needle)
{
   string a = s; StringToLower(a); string b = needle; StringToLower(b);
   return (StringFind(a,b) >= 0);
}
//+------------------------------------------------------------------+
// Strip trailing ".txt" (case-insensitive)                      // NEW
string StripTxtExt(string fname)
{
   string low = fname; StringToLower(low);
   int p = StringFind(low, ".txt");
   return (p > 0 ? StringSubstr(fname, 0, p) : fname);
}
//+------------------------------------------------------------------+
// Ensure “Preset” is visible in display name                     // NEW
string ToPresetDisplay(const string baseNoExt)
{
   return ContainsNoCase(baseNoExt, "preset") ? baseNoExt : (baseNoExt + " Preset");
}
//+------------------------------------------------------------------+
// Resolve combo display -> actual preset filename (w/ .txt)      // NEW
string ResolvePresetFileByDisplay(const string display)
{
   for(int i=0;i<ArraySize(g_PresetDisplayNames);i++)
      if(g_PresetDisplayNames[i] == display)
         return g_PresetFileNames[i];
   return "";
}
//+------------------------------------------------------------------+
// Ensure folder + AllSymbolsPreset.txt exists, always            // NEW
void EnsureAllSymbolsPresetExists(const string Key_)
{
   const string dir = Key_ + "\\Symbol Presets\\";
   const string f   = dir + "AllSymbolsPreset.txt";
   if(FileIsExist(f, FILE_COMMON)) return;

   int h = FileOpen(f, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(h != INVALID_HANDLE)
   {
      for(int i=0; i<SymbolsTotal(true); i++)
         FileWriteString(h, SymbolName(i,true) + "\r\n");
      FileClose(h);
   }
}
//+------------------------------------------------------------------+
// Ensure at least one preset exists; if none, create "All Symbols Preset.txt" with all pool symbols.
// Returns number of *.txt preset files in Key_\Symbol Presets\
int EnsureAndCountPresetFiles(const string Key_)
{
   string fname;
   long handle = FileFindFirst(Key_+"\\Symbol Presets\\*.txt", fname, FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      FileFindClose(handle);
      return 1; // at least one exists; we don't need the exact count, just non-zero
   }
   // none found -> create default
   string dir = Key_ + "\\Symbol Presets\\";
   // Make sure directory exists (MT5 auto-creates path on FileOpen for FILE_COMMON)
   int h = FileOpen(dir + "All Symbols Preset.txt", FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(h != INVALID_HANDLE)
   {
      for(int i=0; i<SymbolsTotal(true); i++)
         FileWriteString(h, SymbolName(i,true) + "\n");
      FileClose(h);
   }
   // Now there is at least one
   return 1;
}
//+------------------------------------------------------------------+
// Read symbols robustly: commas OR whitespace, tabs, extra spaces, blank lines,
// comments with '#' or '//' ; de-duplicate while preserving order.              // REPLACE
// Read symbols robustly, de-duplicate
bool LoadSymbolsFromPreset(const string Key_, const string presetFileNameOnly, string &outSymbols[])
{
   ArrayResize(outSymbols,0);
   const string fullPath = Key_ + "\\Symbol Presets\\" + presetFileNameOnly;

   int h = FileOpen(fullPath, FILE_READ|FILE_TXT|FILE_COMMON);
   if(h == INVALID_HANDLE) return(false);

   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line); StringTrimRight(line);
      if(line=="" || StringSubstr(line,0,1)=="#" || StringSubstr(line,0,2)=="//") continue;
      StringReplace(line, "\t", " ");
      string tokens[];
      int n = StringSplit(line, ',', tokens);
      if(n <= 0)
      {
         string tmp = line;
         while(StringFind(tmp,"  ")>=0) StringReplace(tmp,"  "," ");
         n = StringSplit(tmp, ' ', tokens);
      }
      for(int i=0;i<n;i++)
      {
         string s = tokens[i];
         StringTrimLeft(s); StringTrimRight(s);
         if(s=="" || InList(outSymbols,s)) continue;

         int m = ArraySize(outSymbols);
         ArrayResize(outSymbols, m+1);
         outSymbols[m] = s;
      }
   }
   FileClose(h);
   return (ArraySize(outSymbols) > 0);
}
bool InList(const string &arr[], const string s)
{
   for(int i=0;i<ArraySize(arr);i++)
      if(arr[i]==s) return true;
   return false;
}
//+------------------------------------------------------------------+
// Add preset entries FIRST. We show filenames without ".txt". We only list
// files whose names contain "preset" (any case). We also guarantee the
// AllSymbolsPreset.txt presence.                                           // REPLACE
void AddPresetsFirstToCombo(CComboBox &cmb, const string Key_)
{
   // Always ensure the default exists, regardless of other files
   EnsureAllSymbolsPresetExists(Key_);

   // reset mapping
   ArrayResize(g_PresetDisplayNames,0);
   ArrayResize(g_PresetFileNames,0);

   string fname;
   long handle = FileFindFirst(Key_ + "\\Symbol Presets\\*.txt", fname, FILE_COMMON);
   if(handle == INVALID_HANDLE) return;

   do
   {
      // Only treat files that contain "preset" somewhere in their name
      if(!ContainsNoCase(fname, "preset")) continue;

      string display = ToPresetDisplay(StripTxtExt(fname));
      cmb.AddItem(display);

      int n = ArraySize(g_PresetDisplayNames);
      ArrayResize(g_PresetDisplayNames, n+1);
      ArrayResize(g_PresetFileNames,    n+1);
      g_PresetDisplayNames[n] = display;    // what user sees
      g_PresetFileNames[n]    = fname;      // actual filename w/ .txt
   }
   while(FileFindNext(handle, fname));
   FileFindClose(handle);
}
//+------------------------------------------------------------------+
string CStrategyTesterDialog::GetTESTERsettingsString(bool header=false)
  {
   string str="[Tester]"+"\n";
   //Expert — the file name of the Expert Advisor that will automatically run in the testing (optimization) mode. If this parameter is not present, testing will not run.
   string Expert     = m_cmbExpert.Select(); //Print(Expert); Print(n_Expert);
   n_Expert = NormalizeExpertRelativePath(n_Expert);
   str+="Expert="+n_Expert+"\n";
//--------------
   //ExpertParameters — the name of the file that contains Expert Advisor parameters. This file must be located in the MQL5\Profiles\Tester folder of the platform installation directory.
//--------------
   //Symbol — the name of the symbol that will be used as the main testing symbol. If this parameter is not added, the last selected symbol in the tester is used.
   string symbol     = m_cmbSymbol.Select(); //Print(symbol);
   str+="Symbol="+symbol+"\n";
//--------------
   //Period — testing chart period (any of the 21 periods available in the platform). If the parameter is not set, default H1 is used.
   string period     = m_cmbPeriod.Select(); //Print(period);
   str+="Period="+period+"\n";
//--------------
   //Login — this parameter communicates to the Expert Advisor the value of an account, on which testing is allegedly performed. 
   //The need for this parameter is set in the source MQL5 code of the Expert Advisor (in the AccountInfoInteger function).
//--------------
   string Model      = m_cmbModel .Select(); //Print(Model);
   //Model — tick generation mode (0 — "Every tick", 1 — "1 minute OHLC", 2 — "Open price only", 3 — "Math calculations", 4 — "Every tick based on real ticks"). 
   //If this parameter is not specified, Every Tick mode is used.
   string Model_name;
        if(Model=="Open prices only")                {Model="2"; Model_name="OP";}
   else if(Model=="1 minute OHLC")                   {Model="1"; Model_name="OHLC";}
   else if(Model=="Every tick")                      {Model="0"; Model_name="ET";}
   else if(Model=="Every tick based on real ticks")  {Model="4"; Model_name="ETWRT";} //Print(Model);
   str+="Model="+Model+"\n";
//--------------
   string delay      = m_cmbDelay .Select(); //Print(delay);
   //ExecutionMode — trading mode emulated by the strategy tester 
   //(0 — normal, -1 — with a random delay in the execution of trading orders, >0 — trade execution delay in milliseconds, it cannot exceed 600 000).
        if(delay=="Zero latency, ideal execution")    delay="0";
   else if(delay=="10 ms delay")                      delay="10";
   else if(delay=="20 ms delay")                      delay="20";
   else if(delay=="50 ms delay")                      delay="50";
   else if(delay=="100 ms delay")                     delay="100";
   else if(delay=="200 ms delay")                     delay="200";
   else if(delay=="500 ms delay")                     delay="500"; //Print(delay);
   str+="ExecutionMode="+delay+"\n";
//--------------
   string opt        = m_cmbOptimization.Select(); //Print(opt);
   //Optimization — enable/disable optimization, its type (0 — optimization disabled, 1 — "Slow complete algorithm", 2 — "Fast genetic based algorithm", 3 — "All symbols selected in Market Watch").
        if(opt=="Fast genetic based algorithm")       opt="2";
   else if(opt=="optimization disabled")              opt="0"; //Print(opt);
   str+="Optimization="+opt+"\n";
//--------------
   //OptimizationCriterion — optimization criterion: (0 — the maximum balance value, 1 — the maximum value of product of the balance and profitability, 2 — the product of the balance and expected payoff,
   //3 — the maximum value of the expression (100% - Drawdown)*Balance, 4 — the product of the balance and the recovery factor, 5 — the product of the balance and the Sharpe Ratio,
   //6 — a custom optimization criterion received from the OnTester() function in the Expert Advisor), 7 — the maximum of complex criterion.
   string criterion  = "6";
   str+="OptimizationCriterion="+criterion+"\n";
//--------------
   //FromDate — starting date of the testing range in format YYYY.MM.DD. If this parameter is not set, the date from the corresponding field of the strategy tester will be used.
   string FromDate   = TimeToString(m_dtFrom.Value(),TIME_DATE); //Print(FromDate);
   str+="FromDate="+FromDate+"\n";
//--------------
   //ToDate — end date of the testing range in format YYYY.MM.DD. If this parameter is not set, the date from the corresponding field of the strategy tester will be used.
   string ToDate     = TimeToString(m_dtTo.Value(),TIME_DATE); //Print(ToDate);
   str+="ToDate="+ToDate+"\n";
//--------------
   string ForwardMode= m_cmbForward.Select(); //Print(ForwardMode);
   string ForwardDateStr;
   //ForwardMode — forward testing mode (0 — off, 1 — 1/2 of the testing period, 2 — 1/3 of the testing period, 3 — 1/4 of the testing period, 
   //4 — custom interval specified using the ForwardDate parameter).
      //if(ForwardMode=="No")                        {ForwardDateStr="No Forward";     ForwardMode="0";}
        if(ForwardMode=="1/2")                       {ForwardDateStr="1/2";            ForwardMode="1";}
   else if(ForwardMode=="1/3")                       {ForwardDateStr="1/3";            ForwardMode="2";}
   else if(ForwardMode=="1/4")                       {ForwardDateStr="1/4";            ForwardMode="3";}
   else if(ForwardMode=="Custom")                                                      ForwardMode="4"; //Print(ForwardMode);
   str+="ForwardMode="+ForwardMode+"\n";
//--------------
   //ForwardDate — starting date of forward testing in the format YYYY.MM.DD. The parameter is valid only if ForwardMode=4.
   string ForwardDate= TimeToString(m_dtForward.Value(),TIME_DATE); //Print(ForwardDate);
   if(ForwardMode=="4") {str+="ForwardDate="+ForwardDate+"\n"; ForwardDateStr=ForwardDate;}
   else   ForwardDateStr = TimeToString(GetForwardD(m_dtFrom.Value(),m_dtTo.Value(),ForwardDateStr),TIME_DATE);
//--------------
   //Report — the name of the file to save the report on testing or optimization results. The file is created in the trading platform directory. You can specify a path to save the file, 
   //relative to this directory, for example, \reports\tester.htm. The subdirectory where the report is saved should exist. If no extension is specified in the file name, the ".htm" extension 
   //is automatically used for testing reports, and ".xml" is used for optimization reports. If this parameter is not set, the testing report will not be saved as a file. 
   //If forward testing is enabled, its results will be saved in a separate file with the ".forward" suffix. For example, tester.forward.htm.
   str+="Report="+BuildReportValue(Strategy,symbol,period,FromDate,ToDate,ForwardDateStr)+"\n";
//--------------
   //ReplaceReport — enable/disable overwriting of the report file (0 — disable, 1 — enable). If overwriting is forbidden and a file with the same name already exists, 
   //a number in square brackets will be added to the file name. For example, tester[1].htm. If this parameter is not set, default 0 is used (overwriting is not allowed).
   str+="ReplaceReport="+"1"+"\n";
//--------------
   //ShutdownTerminal — enable/disable platform shutdown after completion of testing (0 — disable, 1 — enable). If this parameter is not set, the "0" value is used (shutdown disabled). 
   //If the testing/optimization process is manually stopped by a user, the value of this parameter is automatically reset to 0.
   string Shutdown   = "0";
   str+="ShutdownTerminal="+Shutdown+"\n";
//--------------
   //Deposit — initial deposit for testing optimization. The amount is specified in the account deposit currency. If the parameter is not specified, 
   //a value from the appropriate field of the strategy tester is used.
   string Deposit    = m_edtDeposit.Text(); //Print(Deposit);
   str+="Deposit="+Deposit+"\n";
//--------------
   //Currency — deposit currency for testing/optimization purposes. Specified as a three-letter name, e.g. EUR, USD, CHF etc. Please note that cross rates for converting profit and margin 
   //to the specified deposit currency must be available on the account, to ensure proper testing. If the parameter is not specified, a value from the appropriate field of the strategy tester is used.
   string Currency   = m_edtCurrency.Text(); //Print(Currency);
   str+="Currency="+Currency+"\n";
//--------------
   string Leverage   = m_cmbLeverage.Select(); //Print(Leverage);
   //Leverage — leverage for testing/optimization. For example, 1:100. If the parameter is not specified, a leverage from the appropriate field of the strategy tester is used.
        if(Leverage=="1:100")                         Leverage="100";
   else if(Leverage=="1:200")                         Leverage="200";
   else if(Leverage=="1:500")                         Leverage="500";
   else if(Leverage=="1:1000")                        Leverage="1000"; //Print(Leverage);
   str+="Leverage="+Leverage+"\n";
//--------------
   //UseLocal — enable/disable the use of local agents for testing and optimization (0 — disable, 1 — enable). If the parameter is not specified, current platform settings are used.
//--------------
   //UseRemote — enable/disable use of remote agents for testing and optimization (0 — disable, 1 — enable). If the parameter is not specified, current platform settings are used.
//--------------
   //UseCloud — enable/disable use of agents from the MQL5 Cloud Network (0 — disable, 1 — enable). If the parameter is not specified, current platform settings are used.
//--------------
   //Visual — enable (1) or disable (0) the visual test mode. If the parameter is not specified, the current setting is used.
   string Visual   = "0";
   str+="Visual="+Visual+"";
//--------------
   //Port — the port, on which the local testing agent is running. The port should be specified for the parallel start of testing on different agents. 
   //For example, you can run parallel tests of the same Expert Advisor with different parameters. During a single test port can be omitted.
//--------------
   str = BuildQueueTitle("Pending",symbol,period,FromDate,ToDate,Model,Strategy)+"\n"+str;
 //str = ";"+"Pending_"+symbol+","+period+" "+FromDate+"-"+ToDate+"_"+ForwardDate+"_"+Model_name+"_"+Strategy+";\n"+str;
   StringTrimLeft(str); //StringTrimRight(str);
   return str;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string CStrategyTesterDialog::GetExportSettingsString()
  {
   string str = "[Export]" + "\n";

   // --- left column ------------------------------------------------
   str += "SetsToExport="  + m_edtSetsToExport.Text()         + "\n";
   str += "MinScore="      + m_edtMinScore.Text()             + "\n";
   str += "TargetDD="      + m_edtTargetDD.Text()             + "\n";
   str += "AdjustLots="    + (m_chkAdjustLots.Checked() ? "1" : "0") + "\n";

   // --- right column -----------------------------------------------
   str += "BackOOSDate="   + TimeToString(m_dpBackOOS.Value(), TIME_DATE) + "\n";
   str += "MinARF="        + m_edtMinARF.Text()               + "\n";
   str += "MinSR="         + m_edtMinSR.Text()                + "\n";
   str += "IncludeBackOOS="+ (m_chkVerifyOOS.Checked() ? "1" : "0") + "\n";
   
   // keep the trailing newline for easy concatenation with other blocks
   return str;
  }
//+------------------------------------------------------------------+
string FetchExportSetting(const string settingName,string Key_,string EA_Name_,string Server_)
  {
   string Path_ExportSettings = GoatOptExportSettingsPath(EA_Name_,Server_);
   if(!FileIsExist(Path_ExportSettings,FILE_COMMON)) return "";
   int handle = FileOpen(Path_ExportSettings, FILE_READ|FILE_TXT|FILE_UNICODE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
   if(handle == INVALID_HANDLE) handle = FileOpen(Path_ExportSettings, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
   if(handle == INVALID_HANDLE) { PrintFormat("FetchExportSetting: cannot open %s  (err=%d)", Path_ExportSettings, GetLastError()); return ""; }
   // read whole content into a single string ---------------------------
   string fullText = "";
   while(!FileIsEnding(handle)) fullText += FileReadString(handle) + "\n"; FileClose(handle);
   // quick sanity-check for the [Export] header ------------------------
   int posStart = StringFind(fullText, "[Export]");
   if(posStart < 0) return "";
   // split the export section into lines ------------------------------
   string liness[];
   int cnt = StringSplit(fullText, '\n', liness);
   string key = settingName + "=";
   // walk every line and return the first match -----------------------
   for(int i = 0; i < cnt; i++)
   {
      string line = liness[i];
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringFind(line, key) == 0)                 // “key=value…”
      return StringSubstr(line, StringLen(key));  // strip the “key=”
   }
   return "";                                        // not found
  }
//+------------------------------------------------------------------+
/*void ShowExportSettings()
{
   // --- pull each value as text --------------------------------------
   string sSetsToExport = FetchExportSetting("SetsToExport");
   string sMinScore     = FetchExportSetting("MinScore");
   string sTargetDD     = FetchExportSetting("TargetDD");
   string sAdjustLots   = FetchExportSetting("AdjustLots");
   string sBackOOSDate  = FetchExportSetting("BackOOSDate");
   string sMinARF       = FetchExportSetting("MinARF");
   string sMinSR        = FetchExportSetting("MinSR");
   string sInclBackOOS  = FetchExportSetting("IncludeBackOOS");
   // --- convert to handy types --------------------------------------
   int      setsToExport = (int)StringToInteger(sSetsToExport);
   double   minScore     = StringToDouble  (sMinScore);
   double   targetDD     = StringToDouble  (sTargetDD);
   bool     adjustLots   = (sAdjustLots   == "1");
   datetime backOOSDate  = StringToTime    (sBackOOSDate);
   double   minARF       = StringToDouble  (sMinARF);
   double   minSR        = StringToDouble  (sMinSR);
   bool     inclBackOOS  = (sInclBackOOS  == "1");
   // --- pretty print -------------------------------------------------
   PrintFormat("---------------------- EXPORT SETTINGS ----------------------");
   PrintFormat("Sets to export  : %d",        setsToExport);
   PrintFormat("Min OPT score   : %.2f",      minScore);
   PrintFormat("Target DD       : %.2f",      targetDD);
   PrintFormat("Adjust lots     : %s",        adjustLots  ? "true" : "false");
   PrintFormat("Back-OOS date   : %s",        TimeToString(backOOSDate, TIME_DATE));
   PrintFormat("Min ARF         : %.2f",      minARF);
   PrintFormat("Min SR          : %.2f",      minSR);
   PrintFormat("Include Back OOS: %s",        inclBackOOS ? "true" : "false");
   PrintFormat("--------------------------------------------------------------");
}*/
//----------------------------------------------------------------------------------------------------------------------------------------------------
//+------------------------------------------------------------------+
// 2) single helper that handles all user prompts + optional download
bool EnsureFreshNewsFile(const string csv_file)
{
   datetime latest = 0;
   bool stale = IsNewsHistoryStale(csv_file, latest);
   Print("Latest news: "+(string)latest);

   if(!stale) return true;

   string stamp = (latest==0) ? "No Date" : TimeToString(latest,TIME_DATE|TIME_MINUTES);
   string q = "News history is out of date.\n\nLatest news saved in the file is from:\n" + stamp +
              "\n\nClick Yes to sync now, or No to continue anyway.";
   if(MessageBox(q, "News data out-of-date", MB_YESNO|MB_ICONQUESTION) != IDYES) return true;

   SNewsSyncResult result;
   if(!News.SyncFullHistory(result))
     {
      string msg = "News history sync failed";
      if(result.error_text != "") msg += "\n\n" + result.error_text;
      MessageBox(msg, "News History", MB_OK|MB_ICONERROR);
      return false;
     }

   return true;
}
//+------------------------------------------------------------------+
//  Fast grab of newest-event timestamp – works with CR, LF, CRLF
datetime LatestNewsTimestampFast2(const string file_name)
{
   if(!FileIsExist(file_name,FILE_COMMON))
      return(0);
   // Open text file for reading
   int fh = FileOpen(file_name,FILE_READ|FILE_TXT|FILE_COMMON);
   if(fh==INVALID_HANDLE)
      return(0);
   // How many bytes we'll chunk back from EOF
   const long CHUNK = 2048;
   long fsize = (long) FileSize(fh);
   // Seek CHUNK bytes back from the very end
   // SEEK_END = file end; offset negative moves backward :contentReference[oaicite:0]{index=0}&#8203;:contentReference[oaicite:1]{index=1}
   long offset = (fsize > CHUNK ? -CHUNK : 0);
   FileSeek(fh, offset, SEEK_END);
   // If we didn’t start at file-beginning, skip the first (possibly partial) line
   if(offset != 0)
      FileReadString(fh);
   // Read forward, remembering the last non-blank line
   string line, lastLine="";
   while(!FileIsEnding(fh))
   {
      line = FileReadString(fh);
      if(StringTrim(line) != "")
         lastLine = line;
   }
   FileClose(fh);
   // Parse that last full line
   string parts[];
   if(StringSplit(lastLine, ',', parts) < 2)
      return(0);
   // Convert the timestamp field (parts[1]) to datetime
   return(StringToTime(parts[1]));
}
//string StringTrim(string str) {StringTrimLeft(str); StringTrimRight(str); return str;}
//+------------------------------------------------------------------+
datetime LatestNewsTimestampFast(const string file_name)
{
   if(!FileIsExist(file_name, FILE_COMMON)) return 0;

   int fh = FileOpen(file_name, FILE_READ|FILE_TXT|FILE_COMMON);
   if(fh == INVALID_HANDLE) return 0;

   const long CHUNK = 2048;
   long fsize  = (long)FileSize(fh);
   long offset = (fsize > CHUNK ? -CHUNK : 0);

   FileSeek(fh, offset, SEEK_END);
   // If we didn’t start at file-beginning, discard the first (possibly partial) line
   if(offset != 0) FileReadString(fh);
   
   string line = "", lastLine = "";
   while(!FileIsEnding(fh))
   {
      line = FileReadString(fh);
      StringTrimLeft(line);
      StringTrimRight(line);

      if(line != "")
         lastLine = line;
   }
   FileClose(fh);
   if(lastLine == "")
      return 0;
   // CSV written as: Time,Currency,ImpactScore,...
   // Timestamp is column 0 (NOT column 1)
   string parts[];
   if(StringSplit(lastLine, ',', parts) < 1)
      return 0;
   string ts = parts[0];
   StringTrimLeft(ts);
   StringTrimRight(ts);
   // Strip quotes if present
   if(StringLen(ts) >= 2 && StringGetCharacter(ts, 0) == '\"' && StringGetCharacter(ts, StringLen(ts)-1) == '\"')
      ts = StringSubstr(ts, 1, StringLen(ts)-2);
   // Header guard
   if(ts == "Time") return 0;

   return StringToTime(ts);
}
//+------------------------------------------------------------------+
bool IsNewsHistoryStale(const string file_name, datetime &latest_event_time)
{
   latest_event_time = LatestNewsTimestampFast(file_name);
   if(latest_event_time == 0) return true;
   return ((TimeCurrent() - latest_event_time) > 7*24*3600);
}
//+------------------------------------------------------------------+
datetime GetForwardD(datetime startD, datetime endD, string forwardMode)
  {
   int den = 0;
   if(StringFind(forwardMode, "1/2") != -1)
      den = 2;
   else if(StringFind(forwardMode, "1/3") != -1)
      den = 3;
   else if(StringFind(forwardMode, "1/4") != -1)
      den = 4;
   else
      return StringToTime(forwardMode); // Custom date: convert string to datetime

   // Calculate the total period in days (datetime values are in seconds)
   long totalSec = endD - startD;
   int totalDays = (int)(totalSec / 86400);
   // Compute forward period (number of days reserved for forward testing)
   int fwdDays = (int)MathCeil(totalDays / (double)den);
   // The in-sample period is the remainder of the test period.
   int inSampleDays = totalDays - fwdDays;
   return startD + inSampleDays * 86400;
  }
datetime GetForwardD2(datetime startD,datetime endD,string forwardMode)
  {
   if(StringFind(forwardMode,"1/")==0) // e.g. "1/2","1/3","1/4"
     {
      int pos=StringFind(forwardMode,"/");
      if(pos>=0)
        {
         string denom=StringSubstr(forwardMode,pos+1);
         int x=(int)StringToInteger(denom);
         if(x>1)
           {
            // fraction where the forward period is 1/x
            // => the forward date starts at 1 - (1/x) = (x-1)/x
            double ratio=1.0-1.0/(double)x;
            long diff=(long)endD - (long)startD;
            long offset=(long)(diff*ratio);
            return (datetime)(startD+offset);
           }
        }
     }
   // 2) Otherwise treat forwardMode as a custom date string: "YYYY.MM.DD HH:MI"
   datetime custom=StringToTime(forwardMode);
   if(custom>0) return custom;
   return 0;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//+------------------------------------------------------------------+
//| Batch-optimisation summary builder (three-line report)           |
//|  – MT5-safe: plain MQL5, no STL, lambdas or C++11                |
//+------------------------------------------------------------------+
double ParseNumber(const string src,int pos)
{
   int len=(int)StringLen(src);
   while(pos<len)                                 // advance to first digit/./-
   {
      string ch=StringSubstr(src,pos,1);
      if((ch>="0"&&ch<="9")||ch=="-"||ch==".") break;
      pos++;
   }
   string num="";
   while(pos<len)
   {
      string ch=StringSubstr(src,pos,1);
      if((ch>="0"&&ch<="9")||ch=="-"||ch==".") { num+=ch; pos++; }
      else break;
   }
   return (num=="") ? 0.0 : StringToDouble(num);
}
//--
string Trim(const string s0){ string s=s0; StringTrimLeft(s); StringTrimRight(s); return s; }
/*------------------------------------------------------------------*/
string GenerateOptimizationSummary(const string queueFile,const string logFile)
{
/* 1. -------- read queue – remember last state -------------------*/
string titles[];
bool   queueIsError[];

{
   int h = FileOpen(queueFile,FILE_SHARE_READ|FILE_TXT|FILE_COMMON);
   if(h == INVALID_HANDLE)  return "error: cannot open queue file";

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      bool isCompleted = (StringFind(ln,";Completed_",0) == 0);
      bool isError     = (StringFind(ln,";Error_"    ,0) == 0);
      if(!isCompleted && !isError) continue;          // ignore everything else
      ln =  StringSubstr(ln,1);                       // drop leading ‘;’
      int semi = StringFind(ln,";");
      if(semi > 0) ln = StringSubstr(ln,0,semi);      // cut trailing part
      ln =  StringSubstr(ln,StringFind(ln,"_")+1);    // remove Completed_/Error_
      /* -------- store the *latest* status ----------------------*/
      int idx = -1;
      for(int i = 0; i < ArraySize(titles); i++) if(titles[i] == ln){ idx = i; break; }

      if(idx < 0)                                     // first time – append
      {
         int n = ArraySize(titles);
         ArrayResize(titles,n+1);       titles[n]       = ln;
         ArrayResize(queueIsError,n+1); queueIsError[n] = isError;
      }
      else                                            // seen before – overwrite
         queueIsError[idx] = isError;                 // keep the newest flag
   }
   FileClose(h);
}
/* 2. -------- experts log into array -----------------------------*/
   string liness[];
   {
      int h=FileOpen(logFile,FILE_SHARE_READ|FILE_TXT|FILE_COMMON);
      if(h==INVALID_HANDLE) return "error: cannot open log file";
      int idx=0;
      while(!FileIsEnding(h))
      {
         string ln=FileReadString(h);
         ArrayResize(liness,idx+1); liness[idx]=ln; idx++;
      }
      FileClose(h);
   }
/* 3. -------- locate last batch-start ----------------------------*/
   int start=-1;
   for(int i=ArraySize(liness)-1;i>=0;i--)
      if(StringFind(liness[i],"Batch Start clicked and accepted",0)>=0)
         { start=i; break; }
   if(start<0) return "error: batch-start marker not found";
/* 4. -------- result struct --------------------------------------*/
   struct SRes{
      string title;  bool finished;
      bool   xmlOk;  bool haveScore;
      double topScore; int distinctRows,uniqueRows;
      int expRun,expGood,expPass;
      int adjRun,adjGood,adjPass;
      bool   queuedAsError;          // NEW
   };
   SRes res[];
   ArrayResize(res,ArraySize(titles));
   for(int i=0;i<ArraySize(res);i++)
   {
      res[i].title        = titles[i];
      res[i].finished     = false;
      res[i].xmlOk        = true;
      res[i].haveScore    = false;
      res[i].topScore     = 0.0;
      res[i].distinctRows = 0;  res[i].uniqueRows  = 0;
      res[i].expRun=0;  res[i].expGood=0; res[i].expPass=0;
      res[i].adjRun=0;  res[i].adjGood=0; res[i].adjPass=0;
      res[i].queuedAsError = queueIsError[i];
   }
/* 5. -------- parse log ------------------------------------------*/
   int cur=-1;
   for(int i=start;i<ArraySize(liness);i++)
   {
      string ln=liness[i];
/* 5-a new optimisation block */
      int p=StringFind(ln,"Batch Optimization Initialized",0);
      if(p>=0)
      {
         int c=StringFind(ln,",",p);
         int lt=StringFind(ln,"<",c);
         string sym = (lt > c) ? StringSubstr(ln,c+1,lt-c-1):StringSubstr(ln,c+1);
         sym = Trim(sym);
         cur=-1;
         for(int k=0;k<ArraySize(res);k++)
            if(StringFind(res[k].title,sym,0)>=0){ cur=k; break; }
         continue;
      }
      if(cur<0) continue;
/* 5-b finished */
      if(StringFind(ln,"Optimization Ended",0)>=0){ res[cur].finished=true; continue; }
/* 5-c XML stats --------------------------------------------------*/
      p = StringFind(ln,"DEINIT: ✅ XML files Combined and Analyzed.",0);
      if(p >= 0)
      {
       /* success banner – we didn't necessarily write a “Top” file */
       res[cur].xmlOk     = true;
       res[cur].haveScore = true;            //  ←  add this line
       continue;
      }
      p=StringFind(ln,"SXmlData::WriteTopToXml:",0);
      if(p>=0 && StringFind(ln,"wrote ",p)>=0)
      {
         int w = StringFind(ln,"wrote ",p)+6;
         res[cur].distinctRows = (int)ParseNumber(ln,w);
         int s = StringFind(ln,"Score=",p);
         res[cur].topScore     = ParseNumber(ln,s+6);
         res[cur].haveScore    = true;
         continue;
      }
      p=StringFind(ln,"SXmlData::WriteUniqueRowsToXml:",0);
      if(p>=0 && StringFind(ln,"rows written",p)>=0)
      {
         int w=StringFind(ln,":",p)+1;
         res[cur].uniqueRows=(int)ParseNumber(ln,w);
         continue;
      }
      if(StringFind(ln,"❌ Failed to analyze and combine",0)  >=0 ||   // new (lower-case “analyze”)
         StringFind(ln,"❌ Failed to Analyze and Combine",0)  >=0 ||   // keeps the old one
         StringFind(ln,"❌ SXmlData::WriteTopToXml: No Rows",0)>=0 ||
         StringFind(ln,"❌ SXmlData::WriteUniqueRowsToXml",0) >=0 )    // new selector failure
            res[cur].xmlOk = false;
/* 5-d export sequence -------------------------------------------*/
      p=StringFind(ln,"Export sequence complete:",0);
      if(p>=0)
      {
         int afterColon   = StringFind(ln,":",p)+1;
         res[cur].expRun  = (int)ParseNumber(ln,afterColon);

         int afterAttmpts = StringFind(ln,"attempts",afterColon);
         res[cur].expGood = (int)ParseNumber(ln,afterAttmpts);

         int passPos      = StringFind(ln,"passed thresholds",afterColon-1);
         res[cur].expPass = (int)ParseNumber(ln,passPos-10);   // look 10 chars back
         continue;
      }
/* 5-e adjustment sequence ---------------------------------------*/
      p=StringFind(ln,"Export Adjustment sequence complete:",0);
      if(p>=0)
      {
         int afterColon   = StringFind(ln,":",p)+1;
         res[cur].adjRun  = (int)ParseNumber(ln,afterColon);

         int afterAttmpts = StringFind(ln,"attempts",afterColon);
         res[cur].adjGood = (int)ParseNumber(ln,afterAttmpts);

         int passPos      = StringFind(ln,"passed thresholds",afterColon-1);
         res[cur].adjPass = (int)ParseNumber(ln,passPos-10);
         continue;
      }
/* 5-f exports aborted */
      if(StringFind(ln,"❌ Exports aborted",0)>=0)
      { res[cur].expRun=0; res[cur].expGood=0; res[cur].expPass=0; }
   }
/* 6. -------- build final report ---------------------------------*/
   string out="";
   for(int k=0;k<ArraySize(res);k++)
   {
      /* line 1 */
      bool ok = res[k].finished && res[k].xmlOk && !res[k].queuedAsError;
      out += res[k].title + " -> " + (ok ? "Completed" : "Error") + "\n";
      /* line 2 */
      if(res[k].haveScore)
         out += StringFormat("TopScore=%.1f -> %d distinct row(s) (Score≥60.00)  %d unique rows",res[k].topScore,res[k].distinctRows,res[k].uniqueRows) + "\n";
      else out += "❌ Failed to analyze and combine XML reports – no rows written\n";
      /* line 3 */
      if(res[k].expRun>0)
         out += StringFormat("Exports:(%d/%d good %d above threshold) Adjusted Exports:(%d/%d)",
                             res[k].expGood,res[k].expRun,res[k].expPass,
                             res[k].adjGood,res[k].adjRun);
      else out += "❌ Exports aborted";

      if(k<ArraySize(res)-1) out += "\n\n";
   }
   if(ArraySize(res)==0) out = "No Completed / Error items found in queue";
   return out;
}
//+------------------------------------------------------------------+
