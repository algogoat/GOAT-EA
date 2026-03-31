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
#include <ControlsPlus\Scrolls.mqh>
//#include "GOATdefinitions.mqh"
//#include "GOAT_Tester.mqh"
#include <Trade\PositionInfo.mqh>
#ifndef Kernel
#import "kernel32.dll"
   //int GetCurrentProcessId();
   int CopyFileW(string src, string dst, int fail_if_exists);
#import
#endif 
//----------------------------------------------------------------------------------------------------------------------------------------------------
class CGOATDashboard;

class CGOATDashScrollV : public CScrollV
  {
private:
   CGOATDashboard *m_owner;
public:
                     CGOATDashScrollV(void) {m_owner=NULL;}
   void              Owner(CGOATDashboard *owner) {m_owner=owner;}
protected:
   virtual bool      OnChangePos(void);
   virtual bool      OnThumbDragProcess(void);
   virtual bool      OnThumbDragEnd(void);
  };
//----------------------------------------------------------------------------------------------------------------------------------------------------
enum ENUM_GOAT_DASH_SORT_KEY
  {
   GOAT_DASH_SORT_SYMBOL=0,
   GOAT_DASH_SORT_STRATEGY,
   GOAT_DASH_SORT_POSITIONS,
   GOAT_DASH_SORT_TRADES,
   GOAT_DASH_SORT_LOTS,
   GOAT_DASH_SORT_HIST_DD,
   GOAT_DASH_SORT_PL_OPEN,
   GOAT_DASH_SORT_PL_D1,
   GOAT_DASH_SORT_PL_W1,
   GOAT_DASH_SORT_PL_ALL
  };
//----------------------------------------------------------------------------------------------------------------------------------------------------
class CGOATDashboard : public CAppDialog
  {
public:
   CWndClient  c_Wnd_Table,c_Wnd_Export;
   CLabel      m_lblHeading,m_lblExport,
               lbl_RunningLossLead,lbl_RunningLossTail,lbl_DailyLossLead,lbl_DailyLossTail,lbl_DailyTargetLead,lbl_DailyTargetTail,
               lbl_LowEquityStopLead,lbl_EquityTargetLead;
   
   CEdit       edt_Heading,edt_HeadingPortfolio,edt_HeadingMembers,edt_HeadingScore,edt_HeadingAMSR,edt_HeadingMonthlyProfit,edt_HeadingMaxDD,edt_HeadingMonthlyRF,
               edt_RunningLossLimit,edt_DailyLossLimit,edt_DailyTargetLimit,edt_LowEquityStopLevel,edt_EquityTargetLevel,
               edt_Symbol[],edt_Strategy[],edt_Comment[],edt_News[],edt_AIBias[],edt_RiskLots[],edt_Action,edt_Status[],edt_Positions[],edt_Lots[],edt_Trades[],edt_HistDD[],edt_PL_Open[],edt_PL_D1[],edt_PL_W1[],edt_PL_All[];
   CButton     btn_Action[];
   // Layout parameters
   int         Margin_Left,Margin_Top,m_GapHoriz,m_GapVert,m_rowHeight,m_controlHeight,m_controlWidth;
 //int         Width_Symbol, Width_Strategy, Width_Action, Width_Status, Width_Positions, Width_Trades, Width_PL_D1, Width_PL_W1, Width_PL_M1, Width_PL_All;
   color       clrEdt,clrEdtBorder,clrEdtBG;
   CGOATDashScrollV m_rows_scroll;
   int         m_rows_top,m_rows_visible,m_rows_top_max,m_rows_y0,m_rows_view_bottom,m_rows_view_left,m_rows_view_right,m_row_pitch,m_rows_data_offset;
   bool        m_rows_scroll_enabled;
   
   string Key_,EA_Name_,Server_,Font;
   string SetFolder,EA_Path;
   string Portfolio_Name,Portfolio_Members,Portfolio_Score,Portfolio_AMSR,Portfolio_Target_MP,Portfolio_Target_DD,Portfolio_Target_MRF;
   double Portfolio_Live_MP,Portfolio_Live_DD,Portfolio_Live_MRF,Port_RunningLoss,Port_DailyLoss,Port_DailyTarget,Port_LowEquityStopLevel,Port_EquityTargetLevel;
   double Version;
   long   ChartId;
   int    D_Width,D_Height,Font_Size;
 //color  clr_CaptionBack,clr_CaptionBorder,clr_ClientBack,clr_ClientBorder,clr_Text;
   //–– inside the private/protected section ––//
   datetime  m_day_start,          // broker midnight
             m_week_start;         // broker Monday
   datetime  m_hist_last_scan[];   // one per g_sets[] element
   double    m_hist_total_pl[];    // cumulative P/L  "
   int       m_hist_total_trd[];   // cumulative trades "
   // reusable GUI colours
   color clrPos, clrNeg, clrNeu;
   
   struct SetFileRecord
   {
    string path,name,sym,strat,status,news_label,bias_label,risk_lots_label;       // activated ?
    long   cid,magic;
    double PL_total,PL_weekly,PL_daily;
    int    Trades_total;
    datetime last_deal_scan;             // ← NEW  incremental history cursor
    SetFileRecord() {path=name=sym=strat=status=news_label=bias_label=risk_lots_label=""; cid=magic=-1; PL_total=PL_weekly=PL_daily=0; Trades_total=0; last_deal_scan=0;}
   };
   SetFileRecord g_sets[];
   
   CGOATDashboard();
  ~CGOATDashboard();
   
   virtual bool   Create(const long chart_id, const string name,const int subwin,const int SetsTotal,const int x1,const int y1,const int width,const int height,const int heightMax);
   
   void           SetFlags(const string _Key_,const string _EA_Name_,const string _Server_,const string _Version_,const int _Font_Size_,const long Id)
   {
    Key_=_Key_; EA_Name_=_EA_Name_; Server_=_Server_; Version=StringToDouble(_Version_); Font_Size=_Font_Size_; ChartId=Id;
   }
   virtual bool   OnEvent(const int id, const long &lparam,const double &dparam, const string &sparam);
   bool           HandleChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam);
   void           SetCaptionClientColors();
   void           maximizeWindow();
   void           minimizeWindow();
   void           OnClickSelectFile(void);
   string         BuildTemplate(const string eaName,const string eaPath,const string setFile);
   bool           SaveTemplateAndCopy(const string tplName,const string tplText);
   bool           ApplyTemplate(const int idx,ENUM_TIMEFRAMES tf,const string tplName);
   bool           NewSingleInstance(const int idx);
   void           GetOpenStats(const string sym,long magic,int &open_trades,double &open_lots,double &open_pl,double &open_pl_day,double &open_pl_week,string &comment);
   void           CalcHistoryStatsFast(int idx,int  &new_trd,double &pl_d,double &pl_w,double &pl_all);
   void           UpdateRowMetrics(int idx,int gui_row);
   void           UpdatePortfolioRow();
   void           RowsScrollTo(const int top_row);
   bool           HandleMouseWheel(const long lparam,const double dparam);
   bool           HandleHeaderClick(const string control_name);
   void           DeployAll(void);
 //void           ScanAndUpdateRow(int idx,int gui_row);
//––––– 1. Load .set files + build g_sets[] ––––––––––––––––––––––––––
   int LoadSetFiles()
   {
    Print("▶ Loading Set Files...");
    string picked[];
    if(FileSelectDialog("Select .set files",NULL,"set files (*.set)|*.set",FSD_FILE_MUST_EXIST|FSD_ALLOW_MULTISELECT|FSD_COMMON_FOLDER,picked,NULL)<=0)
    {
     Alert("⚠ No files chosen.");
     return 0;
    }
    EA_Path=MQLInfoString(MQL_PROGRAM_PATH); //Print(EA_Path);
    EA_Path=StringSubstr(EA_Path,StringFind(EA_Path,"Experts\\")); //Print(EA_Path);
    SetFolder=FolderOf(picked[0]); //Print(SetFolder);
    
    bool ignore=false;
    ArrayResize(g_sets,0);
    // filter only .set files for this EA & symbols in Market Watch
    for(int i=0;i<ArraySize(picked);++i)
    {
     string sym="",EAname="",file=FileNameOf(picked[i]); //Print(file);
     if(!EndsWith(file,".set"))                     continue;
     if(!ExtractEAnameAndSymbol(file,sym,EAname))  {MessageBox("Expert or symbol Name not found in file:\n\n"+file,"Invalid File Name",MB_OK|MB_ICONERROR); continue;}
     if(!SymbolSelect(sym,true))                   {MessageBox("The Symbol "+sym+" is not found in the market watch","Symbol not found",MB_OK|MB_ICONERROR); continue;}
     if(EAname!=EA_Name_)
     {
      if(StringFind(EAname,Key_)>=0)
      {
       if(!ignore)
       {
          int trim_pos=StringFind(file,"_Trds");
          string file_label=(trim_pos>0 ? StringSubstr(file,0,trim_pos) : file);
          int ret=MessageBox("EA Version not matching in set file:\n\n"+file_label+
                             "\n\nDo you want to accept this set file?"+
                             "\nThis may affect your portfolio profitibility."+
                             "\n\nPress Abort to discard once\nPress Retry to accept once\nPress Ignore to accept all further mismatches",
                             "EA Version Mismatch",MB_ABORTRETRYIGNORE|MB_ICONQUESTION);
          if(ret==IDABORT) continue;
          if(ret==IDIGNORE) ignore=true;
       }
      }
      else continue;
     }
     int n=ArraySize(g_sets); ArrayResize(g_sets,n+1);
     g_sets[n].path = SetFolder+"\\"+file;
     g_sets[n].name = file;
     g_sets[n].sym  = sym;
     g_sets[n].strat=ParseSetFileForInput("EA_Desc=",g_sets[n].path);
     g_sets[n].news_label=BuildNewsLabel(g_sets[n].path);
     g_sets[n].bias_label=BuildBiasLabel(g_sets[n].path);
     g_sets[n].risk_lots_label=BuildRiskLotsLabel(g_sets[n].path);
     g_sets[n].status="❌";
    }
    Print("✓ kept ",ArraySize(g_sets)," file(s) after EA-filter.");
    return ArraySize(g_sets);
   }
//––––– activate row : open chart ▸ attach EA ▸ mark ✔ –––––––––––––––
   void DoActivate(int idx)
   {
    if(idx<0 || idx>=ArraySize(g_sets)) return;
    if(g_sets[idx].status=="✔") return;
    //GlobalVariableSet("Dashboard_ChartID",(double)ChartID());
    // --- timeframe token from filename (",M1" etc.)
    int c = StringFind(g_sets[idx].name,",");
    string tfTok = (c>0 ? StringSubstr(g_sets[idx].name,c+1,2) : "M1");
    ENUM_TIMEFRAMES tf = TF(tfTok);
    // --- build & save template
    string tplName   = g_sets[idx].name;                 // e.g. "GOAT EURUSD,M1.set"
    StringReplace(tplName,".set",".tpl");                // -> "GOAT EURUSD,M1.tpl"
    string tplText = BuildTemplate(EA_Name_,EA_Path,g_sets[idx].path);
    if(!SaveTemplateAndCopy(tplName,tplText)) return;
    // --- open chart & apply template
    if(!ApplyTemplate(idx, tf, tplName)) return;
    Sleep(1000);
    //GlobalVariableDel("Dashboard_ChartID");
   }
   void CalcDayWeekStart()
   {
    datetime now = TimeCurrent();
    m_day_start  = (datetime)(now/86400*86400);      // today 00:00
    MqlDateTime tm;
    TimeToStruct(now,tm);
    int dow = tm.day_of_week;                              // 0-6
   // Monday-based shift (Monday=0, Sunday=6)
    int mondayShift = (dow ? dow-1 : 6);
    m_week_start    = m_day_start - 86400*mondayShift;
   }
//  ───  ANCHOR CALCULATION (call once per calendar day)  ──────────
   void CalcPeriodAnchors()
   {
      if(ArraySize(g_sets)==0) return;
      // use first symbol as reference; all symbols of the same broker share time
      datetime newDay  = iTime(g_sets[0].sym,PERIOD_D1,0);
      datetime newWeek = iTime(g_sets[0].sym,PERIOD_W1,0);
   
      // week rollover?  (new candle ⇒ newWeek > m_week_start)
      if(m_week_start!=0 && newWeek > m_week_start)   WeekRollover();                    // push finished week → PL_total
   
      m_day_start  = newDay;
      m_week_start = newWeek;
      ResetDayStats();                      // zero closed‑PL_daily after anchors move
  }
private:
   bool HandleObjectClick(const string control_name);
   bool NavigateToSet(const int idx);
   void RefreshRowsViewportMetrics(void);
   void LayoutRowsScroll(void);
   void ApplyRowsViewport(void);
   void MoveDataRow(const int gui_row,const int y);
   void SetDataRowVisible(const int gui_row,const bool visible);
   bool ShouldSwapRows(const int lhs,const int rhs,const ENUM_GOAT_DASH_SORT_KEY sort_key);
   void SwapRowState(const int lhs,const int rhs);
   void SwapEditState(CEdit &lhs,CEdit &rhs);
   void SwapButtonState(CButton &lhs,CButton &rhs);
   void SortRows(const ENUM_GOAT_DASH_SORT_KEY sort_key);
   void ParsePortfolioFolderInfo(void);
   void UpdatePortfolioInfoHeader(void);
   string FolderOf(const string p) { for(int i=(int)StringLen(p)-1;i>=0;--i) if(p[i]=='\\'||p[i]=='/') return StringSubstr(p,0,i+0); return ""; }

   string FileNameOf(const string p) { for(int i=(int)StringLen(p)-1;i>=0;--i) if(p[i]=='\\'||p[i]=='/') return StringSubstr(p,i+1);  return p; }

   bool EndsWith(const string s,const string suf) { int d=(int)StringLen(s)-(int)StringLen(suf); return(d>=0 && StringSubstr(s,d)==suf); }

   string StringTrim(string str) {StringTrimLeft(str); StringTrimRight(str); return str;}
   
   bool ExtractEAnameAndSymbol(const string f,string &sym,string &EAname)
   {
    int c=StringFind(f,","); if(c<0) return false;
    for(int p=c-1;p>=0;--p) if(StringGetCharacter(f,p)==' ') { sym=StringSubstr(f,p+1,c-p-1); EAname=StringSubstr(f,0,p); if(EAname!="") return true; }
    return false;
   }
   ENUM_TIMEFRAMES TF(const string t)
   {
    if(t=="M1") return PERIOD_M1;  if(t=="M5") return PERIOD_M5;
    if(t=="M15")return PERIOD_M15; if(t=="M30")return PERIOD_M30;
    if(t=="H1") return PERIOD_H1;  if(t=="H4") return PERIOD_H4;
    if(t=="D1") return PERIOD_D1;  return PERIOD_CURRENT;
   }
   void ResetDayStats()
   {
      for(int i=0;i<ArraySize(g_sets);++i) g_sets[i].PL_daily = 0.0;
   }
   void WeekRollover()  // call just after CalcPeriodAnchors on Monday // push PL_weekly → PL_total on Mondays
   {
    for(int i=0;i<ArraySize(g_sets);++i)
    {
     g_sets[i].PL_total  += g_sets[i].PL_weekly;
     g_sets[i].PL_weekly  = 0.0;
    }
   }
   color CGOATDashboard::ChooseColor(const double v) const
   {
      if(v>0.0)  return C'0,180,0';          // green
      if(v<0.0)  return C'180,0,0';          // red
      return clrWhite;                       // neutral
   }
   string FormatIntegerText(const double value)
   {
      return(IntegerToString((int)MathRound(value)));
   }
   string FormatPadded4Text(const double value)
   {
      return(IntegerToString((int)MathRound(value),4,'0'));
   }
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
  string BuildNewsLabel(const string file)
  {
   int mode=(int)StringToInteger(ParseSetFileForInput("Mode_News=",file));
   string label="News?";
   if(mode==0) label="Disp";
   if(mode==1) label="Off";
   if(mode==2) label="Avoid";
   if(mode==3) label="Pause";
   if(mode==4) label="Close";
   if(mode==5) label="Only";

   string threshold=ParseSetFileForInput("News_threshold=",file);
   if(label=="Off" || label=="Disp" || threshold=="-1.0") return(label);
   return(label+"@"+threshold);
  }
  string BuildBiasLabel(const string file)
  {
   int mode=(int)StringToInteger(ParseSetFileForInput("Mode_Bias=",file));
   string label="Bias?";
   if(mode==0) label="Disp";
   if(mode==1) label="Off";
   if(mode==2) label="Open";
   if(mode==3) label="CloseL";
   if(mode==4) label="CloseM";
   if(mode==5) label="CloseH";

   string threshold=ParseSetFileForInput("Bias_threshold=",file);
   if(label=="Off" || label=="Disp" || threshold=="-1.0") return(label);
   return(label+"@"+threshold);
  }
  string BuildRiskLotsLabel(const string file)
  {
   int mode=(int)StringToInteger(ParseSetFileForInput("Mode_Lots=",file));
   double risk=StringToDouble(ParseSetFileForInput("Risk=",file));
   double lots=StringToDouble(ParseSetFileForInput("Lots_Input=",file));
   if(mode==0) return(""+DoubleToString(lots,2));
   if(mode==1) return(""+DoubleToString(lots,2));
   if(mode==2) return(""+DoubleToString(risk,0)+" $");
   return("Lots?");
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
  void CGOATDashboard::CreateLabel(CLabel &lbl, const string text, int x, int y, int width)
  {
    if(!lbl.Create(m_chart_id, text, m_subwin, x, y, x+width, y+m_controlHeight)) Print("Label creation error:", GetLastError());
    if(Font_Size) lbl.FontSize(Font_Size);
    lbl.Text(text);
    lbl.Color(clrBlack);
    //lbl.Color(clrRed); lbl.ColorBackground(clrAqua); lbl.ColorBorder(clrBlack);
    Add(lbl);
   }
   void CGOATDashboard::CreateEditLabel(CEdit &edt, const string text, const string name, int x, int y, int width)
   {
    if(!edt.Create(m_chart_id, m_name+name+text, m_subwin, x, y, x+width, y+m_controlHeight)) Print("Edit creation error:", GetLastError());
    if(Font_Size) edt.FontSize(Font_Size);
    if(Font!="")  edt.Font(Font);
    edt.Text(text); edt.TextAlign(ALIGN_CENTER); edt.ReadOnly(true);
    edt.Color(clrEdt); edt.ColorBorder(clrEdtBorder); edt.ColorBackground(clrEdtBG);
    Add(edt);
   }
   void CGOATDashboard::CreateButtonCtrl(CButton &btn, const string name, int x, int y, int width, int height, string caption)
   {
    if(!btn.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+height)) Print("Button creation error:", GetLastError());
    btn.Color(clrWhite); btn.ColorBorder(C'15,23,42'); btn.ColorBackground(C'8,8,36');//C'15,23,42');
    if(Font_Size) btn.FontSize(Font_Size);
    btn.Text(caption);
    Add(btn);
   }
   void CGOATDashboard::CreateButtonCtrl2(CButton &btn, const string name, int x, int y, int width, int height, string caption)
   {
    if(!btn.Create(m_chart_id, m_name+name, m_subwin, x, y, x+width, y+height)) Print("Button creation error:", GetLastError());
    btn.Color(clrWhite); btn.ColorBorder(clrWhite); btn.ColorBackground(C'8,8,36');//C'15,23,42');
   if(Font_Size) btn.FontSize(Font_Size);
   btn.Text(caption);
   Add(btn);
  }
  void CGOATDashboard::CreateInfoEdit(CEdit &edt,const string name,const string text,int x,int y,int width,int height,color back,color border)
  {
   if(!edt.Create(m_chart_id,m_name+name,m_subwin,x,y,x+width,y+height)) Print("Edit creation error:",GetLastError());
   if(Font_Size) edt.FontSize(Font_Size);
   edt.Font("Tahoma Bold");
   edt.Text(text);
   edt.TextAlign(ALIGN_CENTER);
   edt.ReadOnly(true);
   edt.Color(clrWhite);
   edt.ColorBorder(border);
   edt.ColorBackground(back);
   Add(edt);
  }
  void CGOATDashboard::CreateInfoLabel(CLabel &lbl,const string name,const string text,int x,int y,int width)
  {
   if(!lbl.Create(m_chart_id,m_name+name,m_subwin,x,y,x+width,y+m_controlHeight)) Print("Label creation error:",GetLastError());
   if(Font_Size) lbl.FontSize(Font_Size);
   lbl.Font("Tahoma Bold");
   lbl.Text(text);
   lbl.Color(clrBlack);
   Add(lbl);
  }
  void CGOATDashboard::CreatePlainInputEdit(CEdit &edt,const string name,const string text,int x,int y,int width)
  {
   if(!edt.Create(m_chart_id,m_name+name,m_subwin,x,y,x+width,y+m_controlHeight)) Print("Edit creation error:",GetLastError());
   if(Font_Size) edt.FontSize(Font_Size);
   edt.Font("Tahoma Bold");
   edt.Text(text);
   edt.TextAlign(ALIGN_CENTER);
   edt.ReadOnly(false);
   edt.Color(clrBlack);
   edt.ColorBorder(C'90,90,90');
   edt.ColorBackground(clrWhite);
   Add(edt);
  }
   // Creates a label and returns the left‐edge for the next column
   int PlaceEditLabel(CEdit &edt,const string id, const string text, int x,int y,int w)
   {
    CreateEditLabel(edt, text, id, x, y, w);
    return x + w + m_GapHoriz; // move past this cell + gap
   }
   // Child control event handlers
  };
//+------------------------------------------------------------------+
EVENT_MAP_BEGIN(CGOATDashboard)
  //ON_EVENT(ON_CLICK,  m_btnSelectFile,OnClickSelectFile)
  //ON_EVENT(ON_CLICK,  m_btnAddQueue  ,OnClickAddQueue)
  //ON_EVENT(ON_CLICK,  m_btnStart ,OnClickStart)
  //ON_EVENT(ON_CLICK,  m_btnStop ,OnClickStop)
EVENT_MAP_END(CAppDialog)
//+------------------------------------------------------------------+
CGOATDashboard::CGOATDashboard()
{
   clrPos=C'0,180,0'; clrNeg=C'180,0,0'; clrNeu=clrWhite;
   m_day_start  = 0;                 // will be set on first timer tick
   m_week_start = 0;
   m_rows_top=0;
   m_rows_visible=0;
   m_rows_top_max=0;
   m_rows_y0=0;
   m_rows_view_bottom=0;
   m_rows_view_left=0;
   m_rows_view_right=0;
   m_row_pitch=0;
   m_rows_data_offset=0;
   m_rows_scroll_enabled=false;
   Portfolio_Name="-";
   Portfolio_Members="-";
   Portfolio_Score="-";
   Portfolio_AMSR="-";
   Portfolio_Target_MP="-";
   Portfolio_Target_DD="-";
   Portfolio_Target_MRF="-";
   Portfolio_Live_MP=0.0;
   Portfolio_Live_DD=0.0;
   Portfolio_Live_MRF=0.0;
   Port_RunningLoss=0.0;
   Port_DailyLoss=0.0;
   Port_DailyTarget=0.0;
   Port_LowEquityStopLevel=0.0;
   Port_EquityTargetLevel=0.0;
}
CGOATDashboard::~CGOATDashboard()
{
   // Typically Destroy is called in OnDeinit
}
void CGOATDashboard::maximizeWindow(void)
{
   this.Maximize();
   ApplyRowsViewport();
   ChartRedraw(0);
}
void CGOATDashboard::minimizeWindow(void)   {this.Minimize();}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::HandleChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
{
   if(id==CHARTEVENT_OBJECT_CLICK)
      return(HandleObjectClick(sparam));

   if(id==CHARTEVENT_MOUSE_WHEEL && HandleMouseWheel(lparam,dparam))
      return(true);

   ChartEvent(id,lparam,dparam,sparam);

   if(id==CHARTEVENT_CHART_CHANGE)
   {
      maximizeWindow();
      return(true);
   }

   return(false);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::DeployAll(void)
{
   for(int i=0;i<ArraySize(g_sets);i++)
      DoActivate(i);

   if(ArraySize(edt_Status)>1)
      edt_Status[1].Text("Deployed");
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::NavigateToSet(const int idx)
{
   if(idx<0 || idx>=ArraySize(g_sets)) return(false);
   if(g_sets[idx].cid<=0) return(false);

   if(!ChartSetInteger(g_sets[idx].cid,CHART_BRING_TO_TOP,0,true))
   {
      Print(__FUNCTION__+", Error Code = ",GetLastError());
      return(false);
   }

   Sleep(100);
   ChartRedraw(g_sets[idx].cid);
   Sleep(100);
   ChartRedraw(0);
   Sleep(100);
   return(true);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::HandleObjectClick(const string control_name)
{
   if(HandleHeaderClick(control_name))
      return(true);

   if(ArraySize(btn_Action)>1 && control_name==btn_Action[1].Name())
   {
      DeployAll();
      return(true);
   }

   for(int row=2; row<ArraySize(btn_Action); row++)
   {
      if(control_name!=btn_Action[row].Name())
         continue;

      int idx=row-2;
      if(btn_Action[row].Text()=="Navigate")
         NavigateToSet(idx);
      else
         DoActivate(idx);

      return(true);
   }

   return(false);
}

CEdit CaptionObjDashboard;
CGOATDashboard DashboardDialog;
//+------------------------------------------------------------------+
bool CGOATDashboard::Create(const long chart_id,const string name,const int subwin,const int sets_total,int x1,int y1,int width,int heightIdeal,int heightMax)
  {
// sizing -----------------------------------------------------------
	const int    ROW_MIN_PX=15;
	const int    ROW_TALL_MIN_PX=20;
   const int    ROW_TALL_EXTRA_PX=1;
	const double GAP_VERT_PC=0.01;
	const double CAPTION_PC=0.05;
	const int    CAPTION_MIN_PX=25;
	const double rowScaling=1.2;
	
	D_Width=width;
	D_Height=(int)MathMin(heightMax,MathMax(heightIdeal,0));
	int captionH=(int)MathMax(CAPTION_MIN_PX,CAPTION_PC*D_Height);
	
	for(int _pass=0;_pass<3;_pass++)
	{
		double denom=(sets_total+3)+GAP_VERT_PC*(sets_total+rowScaling*2);
		double rowH=(double)(D_Height-2*captionH)/denom;
		rowH=MathMax((double)ROW_MIN_PX,MathMin((double)(captionH/rowScaling),rowH));
		
		double gapSet=GAP_VERT_PC*rowH,gapTall=gapSet*rowScaling;
		int rowTallH=(int)MathMax((double)ROW_TALL_MIN_PX,MathRound(rowScaling*rowH)+ROW_TALL_EXTRA_PX);
		int needH=2*captionH+(int)(rowH*(sets_total+3))+(int)(gapTall*2+gapSet*sets_total);
		if(rowTallH>captionH) {captionH=rowTallH; continue;}
		if(needH>D_Height)
		{
			double avail=(double)(D_Height-2*captionH-gapTall*2-gapSet*sets_total)/(sets_total+3);
			rowH=MathMax((double)ROW_MIN_PX,MathMin((double)(captionH/rowScaling),avail));
			gapSet=GAP_VERT_PC*rowH;
         gapTall=gapSet*rowScaling;
		}
		m_rowHeight=(int)rowH;
		m_controlHeight=m_rowHeight;
		m_GapVert=(int)gapSet;
		m_GapHoriz=(int)(0.001*D_Width);
      if(m_GapHoriz<1) m_GapHoriz=1;
		break;
	}
   const int client_width=MathMax(1,D_Width-2*(2*CONTROLS_BORDER_WIDTH+CONTROLS_DIALOG_CLIENT_OFF));
   const int canvas_gap=MathMax(8,(int)MathRound(client_width*0.01));
   const int table_inner_pad=1;
   const int scroll_gap=1;
	Margin_Left=table_inner_pad;
// helper sizes -----------------------------------------------------
	const int rowTallH =MathMax(ROW_TALL_MIN_PX,(int)MathRound(rowScaling*m_rowHeight)+ROW_TALL_EXTRA_PX);
	const int gapTallPx=(int)(m_GapVert*rowScaling);
   const int table_left=canvas_gap;
   const int table_right=(client_width-1)-canvas_gap;
   const int info_pad=canvas_gap;
   const int infoHeight=rowTallH;
   const int info_top=info_pad;
   const int info_row_gap=MathMax(4,m_GapVert+1);
   const int info_table_gap=info_row_gap+MathMax(2,m_GapVert);
   const int table_top=info_top+2*infoHeight+info_row_gap+info_table_gap;
   const int table_bottom=(int)((D_Height-captionH)*0.98)-6;
   const int rows=ArraySize(g_sets);
   const int margin_top_plan=table_top+MathMax(2,m_GapVert);
   const int rows_view_top_plan=margin_top_plan+2*(rowTallH+gapTallPx);
   const int rows_view_bottom_plan=table_bottom-m_GapVert;
   const int rows_view_height_plan=MathMax(0,rows_view_bottom_plan-rows_view_top_plan);
   const int rows_visible_plan=(int)MathMax(1.0,MathFloor((double)(rows_view_height_plan+m_GapVert)/(double)(m_rowHeight+m_GapVert)));
   const bool need_rows_scroll=(rows>rows_visible_plan);
   const int scroll_width=(need_rows_scroll ? CONTROLS_SCROLL_SIZE : 0);
   const int columns_left=table_left+table_inner_pad;
   const int columns_right=table_right-table_inner_pad-(need_rows_scroll ? (scroll_gap+scroll_width) : 0);
   const int column_count=16;
   double column_pct[];
   ArrayResize(column_pct,column_count);
   column_pct[0]=6.0;   // Symbol
   column_pct[1]=11.0;  // Strategy
   column_pct[2]=6.0;   // Action
   column_pct[3]=5.0;   // Status
   column_pct[4]=6.0;   // Comment
   column_pct[5]=6.0;   // News
   column_pct[6]=6.0;   // AI Bias
   const double equal_tail_pct=40.5/9.0;
   for(int i=7;i<column_count;i++)
      column_pct[i]=equal_tail_pct;   // Risk/Lots .. P/L Total
   double column_pct_total=0.0;
   for(int i=0;i<column_count;i++) column_pct_total+=column_pct[i];
   int column_gap_total=(column_count-1)*m_GapHoriz;
   int column_pixels=MathMax(200,columns_right-columns_left-column_gap_total);
   int column_widths[];
   ArrayResize(column_widths,column_count);
   int column_used=0;
   for(int i=0;i<column_count-1;i++)
   {
      column_widths[i]=MathMax(12,(int)MathFloor(column_pixels*column_pct[i]/column_pct_total));
      column_used+=column_widths[i];
   }
   column_widths[column_count-1]=MathMax(12,column_pixels-column_used);
   int Width_Symbol   =column_widths[0];
   int Width_Strategy =column_widths[1];
   int Width_Action   =column_widths[2];
   int Width_Status   =column_widths[3];
   int Width_Comment  =column_widths[4];
   int Width_News     =column_widths[5];
   int Width_AIBias   =column_widths[6];
   int Width_RiskLots =column_widths[7];
   int Width_HistDD   =column_widths[8];
   int Width_Trades   =column_widths[9];
   int Width_Positions=column_widths[10];
   int Width_Lots     =column_widths[11];
   int Width_PL_Open  =column_widths[12];
   int Width_PL_D1    =column_widths[13];
   int Width_PL_W1    =column_widths[14];
   int Width_PL_All   =column_widths[15];
   Margin_Top =margin_top_plan;
// create dialog -----------------------------------------------------
	GlobalVariableSet("CaptionHeight",captionH);
	if(!CAppDialog::Create(chart_id,name,subwin,x1,y1,x1+D_Width,y1+D_Height))
	{
		Print("Failed to create GOAT Dashboard: ",GetLastError());
		return(false);
	}
	GlobalVariableDel("CaptionHeight");
	Caption(Key_+" - Portfolio Dashboard and Deploy");
	ChartSetInteger(0,CHART_SHOW_TRADE_HISTORY,0);
	SetCaptionClientColors();
	
	if(!c_Wnd_Table.Create(m_chart_id,m_name+"Boundary",m_subwin,table_left,table_top,table_right,table_bottom))
	{
		Print("Failed to create boundary rect: ",GetLastError());
		return false;
	}
	c_Wnd_Table.ColorBackground(C'8,8,36');//(clrGainsboro);
	c_Wnd_Table.ColorBorder(clrBlack);
	Add(c_Wnd_Table);
//-------------------------------------------------------------
   m_row_pitch=m_rowHeight+m_GapVert;
   m_rows_data_offset=rowTallH+gapTallPx;
   int ctrlSave=m_controlHeight;
   ParsePortfolioFolderInfo();
   double current_equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(current_equity>0.0)
   {
      Port_LowEquityStopLevel=MathRound(current_equity*0.90);
      Port_EquityTargetLevel =MathRound(current_equity*1.10);
   }
// HEADER INFO ------------------------------------------------------
   m_controlHeight=infoHeight;
   int info_y=info_top;
   int info_gap=MathMax(2,m_GapHoriz);
   int info_x=table_left;
   int info_width=table_right-table_left;
   string info_text_portfolio=Portfolio_Name;
   string info_text_members="Members: "+Portfolio_Members;
   string info_text_score="Score: "+Portfolio_Score;
   string info_text_amsr="Avg. SR: "+Portfolio_AMSR;
   string info_text_mrf="Monthly RF: 0.000/"+Portfolio_Target_MRF;
   string info_text_mp="Monthly Profit: 0/"+Portfolio_Target_MP;
   string info_text_dd="Max DD: 0/"+Portfolio_Target_DD;
   const int info_count=7;
   double info_pct[];
   ArrayResize(info_pct,info_count);
   const double info_large_pct=16.0;
   const double info_small_pct=9.0;
   info_pct[0]=info_large_pct;
   info_pct[1]=info_small_pct;
   info_pct[2]=info_small_pct;
   info_pct[3]=info_small_pct;
   info_pct[4]=info_large_pct;
   info_pct[5]=info_large_pct;
   info_pct[6]=info_large_pct;
   double info_pct_total=0.0;
   for(int i=0;i<info_count;i++) info_pct_total+=info_pct[i];
   int info_avail=info_width-(info_count-1)*info_gap;
   int info_widths[];
   ArrayResize(info_widths,info_count);
   int info_used=0;
   for(int i=0;i<info_count-1;i++)
   {
      info_widths[i]=MathMax(1,(int)MathFloor(info_avail*info_pct[i]/info_pct_total));
      info_used+=info_widths[i];
   }
   info_widths[info_count-1]=MathMax(1,info_avail-info_used);
   CreateInfoEdit(edt_HeadingPortfolio    ,"HdrPortfolio"    ,info_text_portfolio,info_x,info_y,info_widths[0],m_controlHeight,C'21,44,72'  ,clrWhite); info_x+=info_widths[0]+info_gap;
   CreateInfoEdit(edt_HeadingMembers      ,"HdrMembers"      ,info_text_members  ,info_x,info_y,info_widths[1],m_controlHeight,C'26,63,95'  ,clrWhite); info_x+=info_widths[1]+info_gap;
   CreateInfoEdit(edt_HeadingScore        ,"HdrScore"        ,info_text_score    ,info_x,info_y,info_widths[2],m_controlHeight,C'47,74,111' ,clrWhite); info_x+=info_widths[2]+info_gap;
   CreateInfoEdit(edt_HeadingAMSR         ,"HdrAMSR"         ,info_text_amsr     ,info_x,info_y,info_widths[3],m_controlHeight,C'73,90,121' ,clrWhite); info_x+=info_widths[3]+info_gap;
   CreateInfoEdit(edt_HeadingMonthlyRF    ,"HdrMonthlyRF"    ,info_text_mrf      ,info_x,info_y,info_widths[4],m_controlHeight,C'83,53,120' ,clrWhite); info_x+=info_widths[4]+info_gap;
   CreateInfoEdit(edt_HeadingMonthlyProfit,"HdrMonthlyProfit",info_text_mp       ,info_x,info_y,info_widths[5],m_controlHeight,C'19,79,60'  ,clrWhite); info_x+=info_widths[5]+info_gap;
   CreateInfoEdit(edt_HeadingMaxDD        ,"HdrMaxDD"        ,info_text_dd       ,info_x,info_y,info_widths[6],m_controlHeight,C'122,63,34' ,clrWhite);
   info_y+=infoHeight+info_row_gap;
   const double row2_group_pct[5]={23.0,21.0,23.0,16.5,16.5};
   const double row2_lead_edit_gap_pct=0.02;
   const double row2_edit_tail_gap_pct=0.08;
   const double row2_group_gap_pct=0.35;
   const double row2_part_pct[3][3]=
   {
      {45.0,18.0,37.0}, // Running Loss: lead / input / tail
      {43.0,19.0,38.0}, // Daily Loss: lead / input / tail
      {45.0,18.0,37.0}  // Daily Target: lead / input / tail
   };
   const double row2_level_part_pct[2][2]=
   {
      {69.0,31.0}, // Low Equity Stop level: label / input
      {69.0,31.0}  // Equity Target Level: label / input
   };
   int row2_lead_edit_gap=MathMax(1,(int)MathRound(info_width*row2_lead_edit_gap_pct/100.0));
   int row2_edit_tail_gap=MathMax(1,(int)MathRound(info_width*row2_edit_tail_gap_pct/100.0));
   int row2_group_gap=MathMax(1,(int)MathRound(info_width*row2_group_gap_pct/100.0));
   const int row2_level_lead_edit_gap=0;
   int row2_avail=info_width-3*(row2_lead_edit_gap+row2_edit_tail_gap)-2*row2_lead_edit_gap-4*row2_group_gap;
   int row2_group_widths[5];
   int row2_group_used=0;
   for(int i=0;i<4;i++)
   {
      row2_group_widths[i]=MathMax(1,(int)MathFloor(row2_avail*row2_group_pct[i]/100.0));
      row2_group_used+=row2_group_widths[i];
   }
   row2_group_widths[4]=MathMax(1,row2_avail-row2_group_used);
   int row2_part_widths[3][3];
   for(int group=0;group<3;group++)
   {
      int group_inner_avail=row2_group_widths[group]-row2_lead_edit_gap-row2_edit_tail_gap;
      int group_used=0;
      for(int part=0;part<2;part++)
      {
         row2_part_widths[group][part]=MathMax(1,(int)MathFloor(group_inner_avail*row2_part_pct[group][part]/100.0));
         group_used+=row2_part_widths[group][part];
      }
      row2_part_widths[group][2]=MathMax(1,group_inner_avail-group_used);
   }
   int row2_level_widths[2][2];
   for(int group=0;group<2;group++)
   {
      int group_inner_avail=row2_group_widths[group+3]-row2_level_lead_edit_gap;
      row2_level_widths[group][0]=MathMax(1,(int)MathFloor(group_inner_avail*row2_level_part_pct[group][0]/100.0));
      row2_level_widths[group][1]=MathMax(1,group_inner_avail-row2_level_widths[group][0]);
   }
   string txt_running_limit="2000";
   string txt_daily_loss_limit="3000";
   string txt_daily_target_limit="3000";
   string txt_running_lead="Running Loss: "+FormatPadded4Text(Port_RunningLoss)+"/ ";
   string txt_running_tail="("+FormatPadded4Text(StringToDouble(txt_running_limit)-Port_RunningLoss)+" Left)";
   string txt_daily_loss_lead="Daily Loss: "+FormatPadded4Text(Port_DailyLoss)+"/ ";
   string txt_daily_loss_tail="("+FormatPadded4Text(StringToDouble(txt_daily_loss_limit)-Port_DailyLoss)+" Left)";
   string txt_daily_target_lead="Daily Target: "+FormatPadded4Text(Port_DailyTarget)+"/ ";
   string txt_daily_target_tail="("+FormatPadded4Text(StringToDouble(txt_daily_target_limit)-Port_DailyTarget)+" Left)";
   info_x=table_left;
   CreateInfoLabel(lbl_RunningLossLead,"LblRunLossLead",txt_running_lead,info_x,info_y,row2_part_widths[0][0]); info_x+=row2_part_widths[0][0]+row2_lead_edit_gap;
   CreatePlainInputEdit(edt_RunningLossLimit,"EdtRunLossLimit",txt_running_limit,info_x,info_y,row2_part_widths[0][1]); info_x+=row2_part_widths[0][1]+row2_edit_tail_gap;
   CreateInfoLabel(lbl_RunningLossTail,"LblRunLossTail",txt_running_tail,info_x,info_y,row2_part_widths[0][2]); info_x+=row2_part_widths[0][2]+row2_group_gap;
   CreateInfoLabel(lbl_DailyLossLead,"LblDayLossLead",txt_daily_loss_lead,info_x,info_y,row2_part_widths[1][0]); info_x+=row2_part_widths[1][0]+row2_lead_edit_gap;
   CreatePlainInputEdit(edt_DailyLossLimit,"EdtDayLossLimit",txt_daily_loss_limit,info_x,info_y,row2_part_widths[1][1]); info_x+=row2_part_widths[1][1]+row2_edit_tail_gap;
   CreateInfoLabel(lbl_DailyLossTail,"LblDayLossTail",txt_daily_loss_tail,info_x,info_y,row2_part_widths[1][2]); info_x+=row2_part_widths[1][2]+row2_group_gap;
   CreateInfoLabel(lbl_DailyTargetLead,"LblDayTargetLead",txt_daily_target_lead,info_x,info_y,row2_part_widths[2][0]); info_x+=row2_part_widths[2][0]+row2_lead_edit_gap;
   CreatePlainInputEdit(edt_DailyTargetLimit,"EdtDayTargetLimit",txt_daily_target_limit,info_x,info_y,row2_part_widths[2][1]); info_x+=row2_part_widths[2][1]+row2_edit_tail_gap;
   CreateInfoLabel(lbl_DailyTargetTail,"LblDayTargetTail",txt_daily_target_tail,info_x,info_y,row2_part_widths[2][2]); info_x+=row2_part_widths[2][2]+row2_group_gap;
   CreateInfoLabel(lbl_LowEquityStopLead,"LblLowEqStopLead","Low Equity Stop level:",info_x,info_y,row2_level_widths[0][0]); info_x+=row2_level_widths[0][0]+row2_level_lead_edit_gap;
   CreatePlainInputEdit(edt_LowEquityStopLevel,"EdtLowEqStopLevel",FormatIntegerText(Port_LowEquityStopLevel),info_x,info_y,row2_level_widths[0][1]); info_x+=row2_level_widths[0][1]+row2_group_gap;
   CreateInfoLabel(lbl_EquityTargetLead,"LblEqTargetLead","Equity Target Level:",info_x,info_y,row2_level_widths[1][0]); info_x+=row2_level_widths[1][0]+row2_level_lead_edit_gap;
   CreatePlainInputEdit(edt_EquityTargetLevel,"EdtEqTargetLevel",FormatIntegerText(Port_EquityTargetLevel),info_x,info_y,row2_level_widths[1][1]);
// HEADER -----------------------------------------------------------
   m_controlHeight=rowTallH;
	int r=0,y=Margin_Top,x=columns_left;
   int base_font_size=Font_Size;
   const int lead_header_font_size=base_font_size+1;
   const int tail_header_font_size=MathMax(7,lead_header_font_size-2);
	Font_Size=lead_header_font_size; Font="Tahoma Bold";
	clrEdt=clrWhite; clrEdtBorder=C'67,112,176'; clrEdtBG=C'20,52,96';
	string prefix="R0_";
	ArrayResize(edt_Symbol,1);    x=PlaceEditLabel(edt_Symbol[0]   ,prefix+"SYM","Symbol",x,y,Width_Symbol);
	ArrayResize(edt_Strategy,1);  x=PlaceEditLabel(edt_Strategy[0] ,prefix+"STR","Strategy",x,y,Width_Strategy);
	                              x=PlaceEditLabel(edt_Action      ,prefix+"Act","Action",x,y,Width_Action);
	ArrayResize(edt_Status,1);    x=PlaceEditLabel(edt_Status[0]   ,prefix+"STS","Status",x,y,Width_Status);
	ArrayResize(edt_Comment,1);   x=PlaceEditLabel(edt_Comment[0]  ,prefix+"CMT","Comment",x,y,Width_Comment);
	ArrayResize(edt_News,1);      x=PlaceEditLabel(edt_News[0]     ,prefix+"NWS","News",x,y,Width_News);
	ArrayResize(edt_AIBias,1);    x=PlaceEditLabel(edt_AIBias[0]   ,prefix+"BIA","AI Bias",x,y,Width_AIBias);
   Font_Size=tail_header_font_size;
	ArrayResize(edt_RiskLots,1);  x=PlaceEditLabel(edt_RiskLots[0] ,prefix+"RSK","Risk/Lots",x,y,Width_RiskLots);
	ArrayResize(edt_HistDD,1);    x=PlaceEditLabel(edt_HistDD[0]   ,prefix+"HDD","Hist DD",x,y,Width_HistDD);
	ArrayResize(edt_Trades,1);    x=PlaceEditLabel(edt_Trades[0]   ,prefix+"TRD","All Trades",x,y,Width_Trades);
	ArrayResize(edt_Positions,1); x=PlaceEditLabel(edt_Positions[0],prefix+"POS","Standing",x,y,Width_Positions);
	ArrayResize(edt_Lots,1);      x=PlaceEditLabel(edt_Lots[0]     ,prefix+"LOT","Open Lots",x,y,Width_Lots);
	ArrayResize(edt_PL_Open,1);   x=PlaceEditLabel(edt_PL_Open[0]  ,prefix+"PLO","P/L Open",x,y,Width_PL_Open);
	ArrayResize(edt_PL_D1,1);     x=PlaceEditLabel(edt_PL_D1[0]    ,prefix+"PLD","P/L Daily",x,y,Width_PL_D1);
	ArrayResize(edt_PL_W1,1);     x=PlaceEditLabel(edt_PL_W1[0]    ,prefix+"PLW","P/L Weekly",x,y,Width_PL_W1);
	ArrayResize(edt_PL_All,1);    x=PlaceEditLabel(edt_PL_All[0]   ,prefix+"PLA","P/L Total",x,y,Width_PL_All);
	r++; y+=rowTallH+gapTallPx;   x=columns_left;
	Font_Size=base_font_size; Font="";
// PORTFOLIO --------------------------------------------------------
   clrEdt=clrWhite; clrEdtBorder=C'55,56,77'; clrEdtBG=C'55,56,77';//(C'15,23,42');//clrGainsboro
	prefix="R1_";
	ArrayResize(edt_Symbol,2);    x=PlaceEditLabel(edt_Symbol[1]   ,prefix+"SYM","Portfolio",x,y,Width_Symbol);
	ArrayResize(edt_Strategy,2);  x=PlaceEditLabel(edt_Strategy[1] ,prefix+"STR","Mixed",x,y,Width_Strategy);
	ArrayResize(btn_Action,2);    CreateButtonCtrl2(btn_Action[1]  ,prefix+"BTN",x,y,Width_Action,m_controlHeight,"ActivateAll"); x+=Width_Action+m_GapHoriz;
	ArrayResize(edt_Status,2);    x=PlaceEditLabel(edt_Status[1]   ,prefix+"STS","Pending",x,y,Width_Status); //edt_Status[1].Color(clrYellow);
	ArrayResize(edt_Comment,2);   x=PlaceEditLabel(edt_Comment[1]  ,prefix+"CMT","Mixed",x,y,Width_Comment);
	ArrayResize(edt_News,2);      x=PlaceEditLabel(edt_News[1]     ,prefix+"NWS","Mixed",x,y,Width_News);
	ArrayResize(edt_AIBias,2);    x=PlaceEditLabel(edt_AIBias[1]   ,prefix+"BIA","Mixed",x,y,Width_AIBias);
	ArrayResize(edt_RiskLots,2);  x=PlaceEditLabel(edt_RiskLots[1] ,prefix+"RSK","Mixed",x,y,Width_RiskLots);
	ArrayResize(edt_HistDD,2);    x=PlaceEditLabel(edt_HistDD[1]   ,prefix+"HDD","- - -",x,y,Width_HistDD);
	ArrayResize(edt_Trades,2);    x=PlaceEditLabel(edt_Trades[1]   ,prefix+"TRD","- - -",x,y,Width_Trades);
	ArrayResize(edt_Positions,2); x=PlaceEditLabel(edt_Positions[1],prefix+"POS","- - -",x,y,Width_Positions);
	ArrayResize(edt_Lots,2);      x=PlaceEditLabel(edt_Lots[1]     ,prefix+"LOT","- - -",x,y,Width_Lots);
	ArrayResize(edt_PL_Open,2);   x=PlaceEditLabel(edt_PL_Open[1]  ,prefix+"PLO","- - -",x,y,Width_PL_Open);
	ArrayResize(edt_PL_D1,2);     x=PlaceEditLabel(edt_PL_D1[1]    ,prefix+"PLD","- - -",x,y,Width_PL_D1);
	ArrayResize(edt_PL_W1,2);     x=PlaceEditLabel(edt_PL_W1[1]    ,prefix+"PLW","- - -",x,y,Width_PL_W1);
	ArrayResize(edt_PL_All,2);    x=PlaceEditLabel(edt_PL_All[1]   ,prefix+"PLA","- - -",x,y,Width_PL_All);
	r++; y+=rowTallH+gapTallPx;   x=columns_left;
// DATA -------------------------------------------------------------
   clrEdt=clrWhite; clrEdtBorder=C'8,8,36'; clrEdtBG=C'8,8,36';//(C'15,23,42');//clrGainsboro
	m_controlHeight=ctrlSave;
	for(int i=0;i<rows;i++,r++)
	{
	 prefix="R"+(string)r+"_";
	 ArrayResize(edt_Symbol,r+1);    x=PlaceEditLabel(edt_Symbol[r]   ,prefix+"SYM",g_sets[i].sym,x,y,Width_Symbol);
	 ArrayResize(edt_Strategy,r+1);  x=PlaceEditLabel(edt_Strategy[r] ,prefix+"STR",g_sets[i].strat,x,y,Width_Strategy);
	 ArrayResize(btn_Action,r+1);    CreateButtonCtrl(btn_Action[r]   ,prefix+"BTN_"+IntegerToString(i),x, y,Width_Action,m_controlHeight,"Activate");
	                                                                                x+=Width_Action+m_GapHoriz; btn_Action[r].Color(C'87,153,122');
	 ArrayResize(edt_Status,r+1);    x=PlaceEditLabel(edt_Status[r]   ,prefix+"STS",g_sets[i].status,x,y,Width_Status); edt_Status[r].Color(C'146,7,1,255');
	 ArrayResize(edt_Comment,r+1);   x=PlaceEditLabel(edt_Comment[r]  ,prefix+"CMT","- - -",x,y,Width_Comment);
	 ArrayResize(edt_News,r+1);      x=PlaceEditLabel(edt_News[r]     ,prefix+"NWS",g_sets[i].news_label,x,y,Width_News);
	 ArrayResize(edt_AIBias,r+1);    x=PlaceEditLabel(edt_AIBias[r]   ,prefix+"BIA",g_sets[i].bias_label,x,y,Width_AIBias);
	 ArrayResize(edt_RiskLots,r+1);  x=PlaceEditLabel(edt_RiskLots[r] ,prefix+"RSK",g_sets[i].risk_lots_label,x,y,Width_RiskLots);
	 ArrayResize(edt_HistDD,r+1);    x=PlaceEditLabel(edt_HistDD[r]   ,prefix+"HDD","- - -",x,y,Width_HistDD); edt_HistDD[r].Text(FormatIntegerText(FetchMetric(g_sets[i].name,"DD")));
	 ArrayResize(edt_Trades,r+1);    x=PlaceEditLabel(edt_Trades[r]   ,prefix+"TRD","- - -",x,y,Width_Trades);
	 ArrayResize(edt_Positions,r+1); x=PlaceEditLabel(edt_Positions[r],prefix+"POS","- - -",x,y,Width_Positions);
	 ArrayResize(edt_Lots,r+1);      x=PlaceEditLabel(edt_Lots[r]     ,prefix+"LOT","- - -",x,y,Width_Lots);
	 ArrayResize(edt_PL_Open,r+1);   x=PlaceEditLabel(edt_PL_Open[r]  ,prefix+"PLO","- - -",x,y,Width_PL_Open);
	 ArrayResize(edt_PL_D1,r+1);     x=PlaceEditLabel(edt_PL_D1[r]    ,prefix+"PLD","- - -",x,y,Width_PL_D1);
	 ArrayResize(edt_PL_W1,r+1);     x=PlaceEditLabel(edt_PL_W1[r]    ,prefix+"PLW","- - -",x,y,Width_PL_W1);
	 ArrayResize(edt_PL_All,r+1);    x=PlaceEditLabel(edt_PL_All[r]   ,prefix+"PLA","- - -",x,y,Width_PL_All);
	 y+=m_rowHeight+m_GapVert;       x=columns_left;
	}
	ArrayResize(m_hist_last_scan,  ArraySize(g_sets),  0);
   ArrayResize(m_hist_total_pl,   ArraySize(g_sets),  0.0);
   ArrayResize(m_hist_total_trd,  ArraySize(g_sets),  0);
   m_rows_top=0;
   RefreshRowsViewportMetrics();
   if(need_rows_scroll)
   {
      int sbX=table_right-CONTROLS_SCROLL_SIZE;
      int sbY=c_Wnd_Table.Top();
      int sbH=MathMax(1,c_Wnd_Table.Bottom()-c_Wnd_Table.Top());
      if(!m_rows_scroll.Create(m_chart_id,m_name+"RowsVScroll",m_subwin,sbX,sbY,table_right,sbY+sbH))
         Print("Rows scroll creation error:",GetLastError());
      else
      {
         if(!Add(m_rows_scroll))
            Print("Rows scroll add error:",GetLastError());
         else
         {
            m_rows_scroll.Owner(GetPointer(this));
            m_rows_scroll_enabled=true;
         }
      }
   }
   ApplyRowsViewport();
// show -------------------------------------------------------------
	Sleep(50); ChartRedraw(0); Sleep(50); Show(); ChartRedraw(0); Sleep(50);
	return(true);
  }
//+------------------------------------------------------------------+
void CGOATDashboard::SetCaptionClientColors(void)
  {
   Sleep(50);
   string prefix=Name();
   int total=DashboardDialog.ControlsTotal();
   for(int i=0;i<total;i++)
   {
    CWnd*obj=DashboardDialog.Control(i);
    string name=obj.Name();
    //---
    if(name==prefix+"Caption")
    {
     CEdit *edit=(CEdit*) obj;
     CaptionObjDashboard = edit;
     //color clr=(color)GETRGB(XRGB(rand()%255,rand()%255,rand()%255));
     edit.Color(clrWhite);
     //edit.ColorBorder(clrWheat);
     edit.ColorBackground(C'8,8,36');//(C'15,23,42');
     //edit.Font(GetFontName(Font_Header));
     if(Font_Size) edit.FontSize(Font_Size+2);
     edit.Font("Tahoma Bold");
     edit.TextAlign(ALIGN_CENTER); edit.ReadOnly(true);
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
   Sleep(50); ChartRedraw();
   return;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string CGOATDashboard::BuildTemplate(const string eaName,const string eaPath,const string setFile)
{
   string tpl  = "<chart>\r\n";
   tpl        += "<expert>\r\n";
   tpl        +=  "name="+eaName+"\r\n";
   tpl        +=  "path="+eaPath+"\r\n";
   tpl        +=  "expertmode=5\r\n";
   tpl        +=  "<inputs>\r\n";
   // read .set and turn every line "Var=Value" into XML
   int h = FileOpen(setFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h!=INVALID_HANDLE)
   {
      while(!FileIsEnding(h))
      {
         string ln = StringTrim(FileReadString(h));
         if(StringLen(ln)==0 || StringFind(ln,"=")<=0) continue;
         int    p  = StringFind(ln,"=");
         string var=StringSubstr(ln,0,p);
         string val=StringSubstr(ln,p+1);
         tpl += var+"="+val+"\r\n";
      }
      FileClose(h);
   }
   else {Print("FileOpen failed ",GetLastError()," ",setFile);}
   tpl += "</inputs>\r\n</expert>\r\n</chart>\r\n";
   return tpl;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::SaveTemplateAndCopy(const string tplName,const string tplText)
{
   string commonRoot = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\";
   string relFolder  = (StringSubstr(SetFolder, StringLen(commonRoot)));          // e.g. "Freestyle Seq sets\"
   string relPath    = relFolder + tplName;                                      // relative inside Common\Files
   
   // 1) write the template right next to the .set file
   int h = FileOpen(relPath, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) { Print("FileOpen failed ",GetLastError()); return false; }
   FileWriteString(h,tplText);  FileClose(h);
   
   // 2) build extended-length paths for CopyFileW
   string srcPath = commonRoot + relPath;                                        // physical source
   string dstPath = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Profiles\\Templates\\" + tplName;

   string srcXL  = "\\\\?\\" + srcPath;   // <- add long-path prefix
   string dstXL  = "\\\\?\\" + dstPath;

   PrintFormat("Copying '%s' → \n  → '%s'", srcPath, dstPath);
   
   if(!CopyFileW(srcXL, dstXL, 0)) { Print("CopyFileW error ", GetLastError()); return false; }
   FileDelete(relPath,FILE_COMMON);
   return true;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::ApplyTemplate(const int idx,ENUM_TIMEFRAMES tf,const string tplName)
{
   string symbol = g_sets[idx].sym;
   PrintFormat("→ ApplyTemplate  sym=%s  tf=%d  tpl=%s", symbol, tf, tplName);

   long cid = ChartOpen(symbol, tf);
   if(cid==0)
   {
      Alert("  ChartOpen FAILED  err=%d", GetLastError());
      return false;
   }
   g_sets[idx].cid=cid;
   PrintFormat("  Chart opened  cid=%I64d", cid);

   if(!ChartApplyTemplate(cid, tplName))
   {
      Alert(StringFormat("  ChartApplyTemplate FAILED  err=%d", GetLastError()));
      return false;
   }
   
   for(int i=GlobalVariablesTotal()-1;i>=0;i--)
   {
      string gv_name=GlobalVariableName(i);
      if(StringFind(gv_name,symbol)>=0)
         GlobalVariableDel(gv_name);
   }
   while(!NewSingleInstance(idx)) Sleep(50);
   
   Sleep(500); ChartRedraw(cid); Sleep(500);
   
   if(!ChartSetInteger(ChartId,CHART_BRING_TO_TOP,0,true))
   {
    //--- display the error message in Experts journal
    Print(__FUNCTION__+", Error Code = ",GetLastError());
    return(false);
   }
   Sleep(500); ChartRedraw(0); Sleep(500);
   
   if(g_sets[idx].cid!=-1 && g_sets[idx].magic!=-1)
   {
    g_sets[idx].status = "✔";
    edt_Status[idx+2].Text(g_sets[idx].status); edt_Status[idx+2].Color(C'87,153,122');
    btn_Action[idx+2].Text("Navigate");
   }
   Sleep(500); ChartRedraw(); Sleep(500);
   Print("  Template applied ✓");
   return true;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::ParsePortfolioFolderInfo(void)
{
   Portfolio_Name=FileNameOf(SetFolder);
   Portfolio_Members="-";
   Portfolio_Score="-";
   Portfolio_AMSR="-";
   Portfolio_Target_MP="-";
   Portfolio_Target_DD="-";
   Portfolio_Target_MRF="-";

   string parts[];
   int total=StringSplit(Portfolio_Name,'_',parts);
   if(total<=0) return;

   Portfolio_Name=parts[0];
   for(int i=1;i<total;i++)
   {
      int eq=StringFind(parts[i],"=");
      if(eq<=0) continue;

      string key=StringSubstr(parts[i],0,eq);
      string val=StringSubstr(parts[i],eq+1);

      if(key=="Members") Portfolio_Members=val;
      if(key=="Score")   Portfolio_Score=val;
      if(key=="AMSR")    Portfolio_AMSR=val;
      if(key=="MP")      Portfolio_Target_MP=val;
      if(key=="DD")      Portfolio_Target_DD=val;
      if(key=="MRF")     Portfolio_Target_MRF=val;
   }
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::UpdatePortfolioInfoHeader(void)
{
   double running_loss_limit=StringToDouble(edt_RunningLossLimit.Text());
   double daily_loss_limit=StringToDouble(edt_DailyLossLimit.Text());
   double daily_target_limit=StringToDouble(edt_DailyTargetLimit.Text());
   double running_loss_left=running_loss_limit-Port_RunningLoss;
   double daily_loss_left=daily_loss_limit-Port_DailyLoss;
   double daily_target_left=daily_target_limit-Port_DailyTarget;

   edt_HeadingPortfolio.Text(Portfolio_Name);
   edt_HeadingMembers.Text("Members: "+Portfolio_Members);
   edt_HeadingScore.Text("Score: "+Portfolio_Score);
   edt_HeadingAMSR.Text("Avg. SR: "+Portfolio_AMSR);
   edt_HeadingMonthlyRF.Text("Monthly RF: "+DoubleToString(Portfolio_Live_MRF,3)+"/"+Portfolio_Target_MRF);
   edt_HeadingMonthlyProfit.Text("Monthly Profit: "+IntegerToString((int)MathRound(Portfolio_Live_MP))+"/"+Portfolio_Target_MP);
   edt_HeadingMaxDD.Text("Max DD: "+IntegerToString((int)MathRound(Portfolio_Live_DD))+"/"+Portfolio_Target_DD);
   lbl_RunningLossLead.Text("Running Loss: "+FormatPadded4Text(Port_RunningLoss)+"/ ");
   lbl_RunningLossTail.Text("("+FormatPadded4Text(running_loss_left)+" Left)");
   lbl_DailyLossLead.Text("Daily Loss: "+FormatPadded4Text(Port_DailyLoss)+"/ ");
   lbl_DailyLossTail.Text("("+FormatPadded4Text(daily_loss_left)+" Left)");
   lbl_DailyTargetLead.Text("Daily Target: "+FormatPadded4Text(Port_DailyTarget)+"/ ");
   lbl_DailyTargetTail.Text("("+FormatPadded4Text(daily_target_left)+" Left)");
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::NewSingleInstance(const int idx)
{
   for(int i=0;i<GlobalVariablesTotal();i++)
   {
    string NewVar = GlobalVariableName(i);
    if(StringFind(NewVar,"New",0)>0 && StringFind(NewVar,g_sets[idx].sym,0)>=0)
    {
     g_sets[idx].magic = (long)GlobalVariableGet(NewVar);
     GlobalVariableDel(NewVar);
     return true;
    }
   }
   Sleep(100);
   return false;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::GetOpenStats(const string symbol,long magic,int &open_trades,double &open_lots,double &open_pl,double &open_pl_day,double &open_pl_week,string &comment)
{
   open_trades=0;
   open_lots=0.0;
   open_pl=0.0;
   open_pl_day=0.0;
   open_pl_week=0.0;
   comment="- - -";
   string first_comment="";
   CPositionInfo p;
   for(int i=PositionsTotal()-1;i>=0;--i)
   {
      if(!p.SelectByIndex(i))                  continue;
      if(p.Symbol()!=symbol)                   continue;
      if(magic!=0 && p.Magic()!=magic)         continue;

      open_trades++;
      open_lots += p.Volume();

      double pr = p.Profit();
      open_pl += pr;
      if(p.Time() >= m_week_start) open_pl_week += pr;
      if(p.Time() >= m_day_start ) open_pl_day  += pr;

      string pos_comment=PositionGetString(POSITION_COMMENT);
      if(StringLen(pos_comment)==0) pos_comment="- - -";
      if(first_comment=="") first_comment=pos_comment;
      else if(first_comment!=pos_comment) first_comment="Mixed";
   }
   if(first_comment!="") comment=first_comment;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::CalcHistoryStatsFast(int idx,int &new_trd,double &pl_d,double &pl_w,double &pl_all)
{
   new_trd=0; pl_d=pl_w=0.0; pl_all=m_hist_total_pl[idx];

   datetime from = m_hist_last_scan[idx]+1,
            now  = TimeCurrent();

   HistorySelect(from,now);                                        // incremental load :contentReference[oaicite:4]{index=4}
   int deals = HistoryDealsTotal();

   for(int i=0;i<deals;++i)
   {
      ulong   tk = HistoryDealGetTicket(i);
      if(HistoryDealGetString(tk,DEAL_SYMBOL)!=g_sets[idx].sym)            continue;
      if(g_sets[idx].magic!=0 &&
         HistoryDealGetInteger(tk,DEAL_MAGIC)!=g_sets[idx].magic)          continue;

      uint entry=(uint)HistoryDealGetInteger(tk,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY)                continue; // closures :contentReference[oaicite:5]{index=5}

      double profit = HistoryDealGetDouble(tk,DEAL_PROFIT);                // DEAL_PROFIT :contentReference[oaicite:6]{index=6}
      datetime t    =(datetime)HistoryDealGetInteger(tk,DEAL_TIME);

      m_hist_total_pl[idx]+=profit;  m_hist_total_trd[idx]++;  new_trd++;
      if(t>=m_day_start)  pl_d+=profit;
      if(t>=m_week_start) pl_w+=profit;
      if(t>m_hist_last_scan[idx]) m_hist_last_scan[idx]=t;
   }
   pl_all=m_hist_total_pl[idx];
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
//  ───  PER‑ROW METRIC UPDATE  ────────────────────────────────────
void CGOATDashboard::UpdateRowMetrics(const int idx,const int gui_row)
{
   if(idx<0 || idx>=ArraySize(g_sets)) return;

   // ---------- 1. SCAN OPEN POSITIONS --------------------------------
   int    open_trades = 0;
   double open_lots   = 0.0;
   double open_pl_d   = 0.0;
   double open_pl_w   = 0.0;
   double open_pl_any = 0.0;
   string open_comment="- - -";
   GetOpenStats(g_sets[idx].sym,g_sets[idx].magic,open_trades,open_lots,open_pl_any,open_pl_d,open_pl_w,open_comment);

   // ---------- 2. SCAN CLOSED DEALS SINCE LAST PASS ------------------
   datetime from = g_sets[idx].last_deal_scan + 1;
   HistorySelect(from,TimeCurrent());
   int deals = HistoryDealsTotal();

   for(int d=0; d<deals; ++d)
   {
      ulong tk = HistoryDealGetTicket(d);
      if(HistoryDealGetString(tk,DEAL_SYMBOL)  != g_sets[idx].sym)             continue;
      if(g_sets[idx].magic && HistoryDealGetInteger(tk,DEAL_MAGIC)!=g_sets[idx].magic) continue;

      uint entry = (uint)HistoryDealGetInteger(tk,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY)                    continue;

      double pr =  HistoryDealGetDouble(tk,DEAL_PROFIT)
                 + HistoryDealGetDouble(tk,DEAL_SWAP)
                 + HistoryDealGetDouble(tk,DEAL_COMMISSION);

      datetime t_close = (datetime)HistoryDealGetInteger(tk,DEAL_TIME);

      g_sets[idx].Trades_total++;                // permanent counter
      g_sets[idx].PL_weekly += (t_close >= m_week_start ? pr : 0);
      g_sets[idx].PL_daily  += (t_close >= m_day_start  ? pr : 0);

      if(t_close > g_sets[idx].last_deal_scan)
         g_sets[idx].last_deal_scan = t_close;
   }

   // ---------- 3. COMBINE CLOSED + OPEN FOR DISPLAY -----------------
   double run_day   = g_sets[idx].PL_daily  + open_pl_d;
   double run_week  = g_sets[idx].PL_weekly + open_pl_w;
   double run_total = g_sets[idx].PL_total  + run_week;   // spec: total = last‑weeks + running‑week
   double hist_dd_value=FetchMetric(g_sets[idx].name,"DD");

   // ---------- 4. WRITE GUI -----------------------------------------
   edt_Comment  [gui_row].Text(open_comment);
   edt_News     [gui_row].Text(g_sets[idx].news_label);
   edt_AIBias   [gui_row].Text(g_sets[idx].bias_label);
   edt_RiskLots [gui_row].Text(g_sets[idx].risk_lots_label);
   edt_Trades   [gui_row].Text(IntegerToString(g_sets[idx].Trades_total));
   edt_Positions[gui_row].Text(IntegerToString(open_trades));
   edt_Positions[gui_row].Color(ChooseColor(open_pl_any));
   edt_Lots     [gui_row].Text(DoubleToString(open_lots,2));
   edt_Lots     [gui_row].Color(ChooseColor(open_pl_any));
   edt_HistDD   [gui_row].Text(FormatIntegerText(hist_dd_value));
   edt_PL_Open  [gui_row].Text(FormatIntegerText(open_pl_any)); edt_PL_Open[gui_row].Color(ChooseColor(open_pl_any));
   edt_PL_D1 [gui_row].Text(FormatIntegerText(run_day )); edt_PL_D1 [gui_row].Color(ChooseColor(run_day ));
   edt_PL_W1 [gui_row].Text(FormatIntegerText(run_week)); edt_PL_W1 [gui_row].Color(ChooseColor(run_week));
   edt_PL_All[gui_row].Text(FormatIntegerText(run_total));edt_PL_All[gui_row].Color(ChooseColor(run_total));
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
//  ───  PORTFOLIO LINE (row 1)  ────────────────────────────────────
void CGOATDashboard::UpdatePortfolioRow()
{
   int    pos_sum = 0, trade_sum = 0;
   double lot_sum = 0.0, open_sum = 0.0, d_sum = 0.0, w_sum = 0.0, t_sum = 0.0, histdd_max = 0.0;

   const int rows = ArraySize(g_sets);
   for(int i=0;i<rows;++i)
   {
      pos_sum   += (int)StringToInteger(edt_Positions[i+2].Text());
      lot_sum   += StringToDouble (edt_Lots     [i+2].Text());
      trade_sum += g_sets[i].Trades_total;
      open_sum  += StringToDouble (edt_PL_Open  [i+2].Text());
      histdd_max = MathMax(histdd_max,StringToDouble(edt_HistDD[i+2].Text()));

      d_sum += g_sets[i].PL_daily  + StringToDouble(edt_PL_D1 [i+2].Text()) - g_sets[i].PL_daily;
      w_sum += g_sets[i].PL_weekly + StringToDouble(edt_PL_W1[i+2].Text()) - g_sets[i].PL_weekly;
      t_sum += StringToDouble(edt_PL_All[i+2].Text());
   }

   edt_Comment  [1].Text("Mixed");
   edt_News     [1].Text("Mixed");
   edt_AIBias   [1].Text("Mixed");
   edt_RiskLots [1].Text("Mixed");
   edt_HistDD   [1].Text(FormatIntegerText(histdd_max));
   edt_Trades   [1].Text(IntegerToString(trade_sum));
   edt_Positions[1].Text(IntegerToString(pos_sum));           edt_Positions[1].Color(ChooseColor(open_sum));
   edt_Lots     [1].Text(DoubleToString(lot_sum,2));          edt_Lots     [1].Color(ChooseColor(open_sum));
   edt_PL_Open  [1].Text(FormatIntegerText(open_sum));         edt_PL_Open  [1].Color(ChooseColor(open_sum));
   edt_PL_D1 [1].Text(FormatIntegerText(d_sum));  edt_PL_D1 [1].Color(ChooseColor(d_sum));
   edt_PL_W1 [1].Text(FormatIntegerText(w_sum));  edt_PL_W1 [1].Color(ChooseColor(w_sum));
   edt_PL_All[1].Text(FormatIntegerText(t_sum));  edt_PL_All[1].Color(ChooseColor(t_sum));
   UpdatePortfolioInfoHeader();
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::RowsScrollTo(const int top_row)
{
   RefreshRowsViewportMetrics();

   int t=top_row;
   if(t<0) t=0;
   if(t>m_rows_top_max) t=m_rows_top_max;
   if(t==m_rows_top) return;

   m_rows_top=t;

   if(m_rows_scroll_enabled && m_rows_scroll.CurrPos()!=t)
      m_rows_scroll.CurrPos(t);

   ApplyRowsViewport();
   ChartRedraw(0);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::HandleMouseWheel(const long lparam,const double dparam)
{
   RefreshRowsViewportMetrics();
   if(m_rows_top_max<=0) return(false);

   int x_cursor=(int)(short)lparam;
   int y_cursor=(int)(short)(lparam>>16);
   if(x_cursor<m_rows_view_left || x_cursor>m_rows_view_right) return(false);
   if(y_cursor<m_rows_y0 || y_cursor>m_rows_view_bottom) return(false);

   int steps=((int)dparam)/120;
   if(steps==0) return(false);

   RowsScrollTo(m_rows_top-steps);
   return(true);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::HandleHeaderClick(const string control_name)
{
   if(ArraySize(edt_Symbol)<1) return(false);

   if(control_name==edt_Symbol[0].Name())    {SortRows(GOAT_DASH_SORT_SYMBOL);   return(true);}
   if(control_name==edt_Strategy[0].Name())  {SortRows(GOAT_DASH_SORT_STRATEGY); return(true);}
   if(control_name==edt_Positions[0].Name()) {SortRows(GOAT_DASH_SORT_POSITIONS);return(true);}
   if(control_name==edt_Trades[0].Name())    {SortRows(GOAT_DASH_SORT_TRADES);   return(true);}
   if(control_name==edt_Lots[0].Name())      {SortRows(GOAT_DASH_SORT_LOTS);     return(true);}
   if(control_name==edt_HistDD[0].Name())    {SortRows(GOAT_DASH_SORT_HIST_DD);  return(true);}
   if(control_name==edt_PL_Open[0].Name())   {SortRows(GOAT_DASH_SORT_PL_OPEN);  return(true);}
   if(control_name==edt_PL_D1[0].Name())     {SortRows(GOAT_DASH_SORT_PL_D1);    return(true);}
   if(control_name==edt_PL_W1[0].Name())     {SortRows(GOAT_DASH_SORT_PL_W1);    return(true);}
   if(control_name==edt_PL_All[0].Name())    {SortRows(GOAT_DASH_SORT_PL_ALL);   return(true);}

   return(false);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::RefreshRowsViewportMetrics(void)
{
   if(ArraySize(edt_Symbol)<2 || m_row_pitch<=0) return;

   m_rows_y0=edt_Symbol[1].Top()+m_rows_data_offset;
   m_rows_view_bottom=c_Wnd_Table.Bottom()-m_GapVert;
   m_rows_view_left=c_Wnd_Table.Left();
   m_rows_view_right=c_Wnd_Table.Right();

   int view_height=MathMax(0,m_rows_view_bottom-m_rows_y0);
   m_rows_visible=(int)MathMax(1.0,MathFloor((double)(view_height+m_GapVert)/(double)m_row_pitch));
   m_rows_top_max=MathMax(0,ArraySize(g_sets)-m_rows_visible);
   if(m_rows_top>m_rows_top_max)
      m_rows_top=m_rows_top_max;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::LayoutRowsScroll(void)
{
   if(!m_rows_scroll_enabled) return;

   int sbX=c_Wnd_Table.Right()-CONTROLS_SCROLL_SIZE;
   int sbY=c_Wnd_Table.Top();
   int sbH=MathMax(1,c_Wnd_Table.Bottom()-c_Wnd_Table.Top());

   m_rows_scroll.Move(sbX,sbY);
   m_rows_scroll.Size(CONTROLS_SCROLL_SIZE,sbH);
   m_rows_scroll.MinPos(0);
   m_rows_scroll.MaxPos(m_rows_top_max);

   if(m_rows_top_max>0)
   {
      m_rows_scroll.Show();
      if(m_rows_scroll.CurrPos()!=m_rows_top)
         m_rows_scroll.CurrPos(m_rows_top);
   }
   else
      m_rows_scroll.Hide();
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::MoveDataRow(const int gui_row,const int y)
{
   CRect rc=edt_Symbol[gui_row].Rect();    edt_Symbol[gui_row].Move(rc.left,y);
         rc=edt_Strategy[gui_row].Rect();  edt_Strategy[gui_row].Move(rc.left,y);
         rc=edt_Comment[gui_row].Rect();   edt_Comment[gui_row].Move(rc.left,y);
         rc=edt_News[gui_row].Rect();      edt_News[gui_row].Move(rc.left,y);
         rc=edt_AIBias[gui_row].Rect();    edt_AIBias[gui_row].Move(rc.left,y);
         rc=edt_RiskLots[gui_row].Rect();  edt_RiskLots[gui_row].Move(rc.left,y);
         rc=btn_Action[gui_row].Rect();    btn_Action[gui_row].Move(rc.left,y);
         rc=edt_Status[gui_row].Rect();    edt_Status[gui_row].Move(rc.left,y);
         rc=edt_HistDD[gui_row].Rect();    edt_HistDD[gui_row].Move(rc.left,y);
         rc=edt_Trades[gui_row].Rect();    edt_Trades[gui_row].Move(rc.left,y);
         rc=edt_Positions[gui_row].Rect(); edt_Positions[gui_row].Move(rc.left,y);
         rc=edt_Lots[gui_row].Rect();      edt_Lots[gui_row].Move(rc.left,y);
         rc=edt_PL_Open[gui_row].Rect();   edt_PL_Open[gui_row].Move(rc.left,y);
         rc=edt_PL_D1[gui_row].Rect();     edt_PL_D1[gui_row].Move(rc.left,y);
         rc=edt_PL_W1[gui_row].Rect();     edt_PL_W1[gui_row].Move(rc.left,y);
         rc=edt_PL_All[gui_row].Rect();    edt_PL_All[gui_row].Move(rc.left,y);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::SetDataRowVisible(const int gui_row,const bool visible)
{
   if(visible)
   {
      edt_Symbol[gui_row].Show();
      edt_Strategy[gui_row].Show();
      edt_Comment[gui_row].Show();
      edt_News[gui_row].Show();
      edt_AIBias[gui_row].Show();
      edt_RiskLots[gui_row].Show();
      btn_Action[gui_row].Show();
      edt_Status[gui_row].Show();
      edt_HistDD[gui_row].Show();
      edt_Trades[gui_row].Show();
      edt_Positions[gui_row].Show();
      edt_Lots[gui_row].Show();
      edt_PL_Open[gui_row].Show();
      edt_PL_D1[gui_row].Show();
      edt_PL_W1[gui_row].Show();
      edt_PL_All[gui_row].Show();
   }
   else
   {
      edt_Symbol[gui_row].Hide();
      edt_Strategy[gui_row].Hide();
      edt_Comment[gui_row].Hide();
      edt_News[gui_row].Hide();
      edt_AIBias[gui_row].Hide();
      edt_RiskLots[gui_row].Hide();
      btn_Action[gui_row].Hide();
      edt_Status[gui_row].Hide();
      edt_HistDD[gui_row].Hide();
      edt_Trades[gui_row].Hide();
      edt_Positions[gui_row].Hide();
      edt_Lots[gui_row].Hide();
      edt_PL_Open[gui_row].Hide();
      edt_PL_D1[gui_row].Hide();
      edt_PL_W1[gui_row].Hide();
      edt_PL_All[gui_row].Hide();
   }
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashboard::ShouldSwapRows(const int lhs,const int rhs,const ENUM_GOAT_DASH_SORT_KEY sort_key)
{
   if(lhs<0 || rhs<0 || lhs>=ArraySize(g_sets) || rhs>=ArraySize(g_sets)) return(false);

   if(sort_key==GOAT_DASH_SORT_SYMBOL || sort_key==GOAT_DASH_SORT_STRATEGY)
   {
      string left =(sort_key==GOAT_DASH_SORT_SYMBOL ? edt_Symbol[lhs+2].Text()   : edt_Strategy[lhs+2].Text());
      string right=(sort_key==GOAT_DASH_SORT_SYMBOL ? edt_Symbol[rhs+2].Text()   : edt_Strategy[rhs+2].Text());
      StringToUpper(left);
      StringToUpper(right);
      return(StringCompare(left,right)>0);
   }

   if(sort_key==GOAT_DASH_SORT_POSITIONS || sort_key==GOAT_DASH_SORT_TRADES)
   {
      long left =(sort_key==GOAT_DASH_SORT_POSITIONS ? StringToInteger(edt_Positions[lhs+2].Text()) : StringToInteger(edt_Trades[lhs+2].Text()));
      long right=(sort_key==GOAT_DASH_SORT_POSITIONS ? StringToInteger(edt_Positions[rhs+2].Text()) : StringToInteger(edt_Trades[rhs+2].Text()));
      return(left<right);
   }

   double left=0.0,right=0.0;
   if(sort_key==GOAT_DASH_SORT_LOTS)         {left=StringToDouble(edt_Lots  [lhs+2].Text()); right=StringToDouble(edt_Lots  [rhs+2].Text());}
   if(sort_key==GOAT_DASH_SORT_HIST_DD)      {left=StringToDouble(edt_HistDD[lhs+2].Text()); right=StringToDouble(edt_HistDD[rhs+2].Text());}
   if(sort_key==GOAT_DASH_SORT_PL_OPEN)      {left=StringToDouble(edt_PL_Open[lhs+2].Text()); right=StringToDouble(edt_PL_Open[rhs+2].Text());}
   if(sort_key==GOAT_DASH_SORT_PL_D1)        {left=StringToDouble(edt_PL_D1 [lhs+2].Text()); right=StringToDouble(edt_PL_D1 [rhs+2].Text());}
   if(sort_key==GOAT_DASH_SORT_PL_W1)        {left=StringToDouble(edt_PL_W1 [lhs+2].Text()); right=StringToDouble(edt_PL_W1 [rhs+2].Text());}
   if(sort_key==GOAT_DASH_SORT_PL_ALL)       {left=StringToDouble(edt_PL_All[lhs+2].Text()); right=StringToDouble(edt_PL_All[rhs+2].Text());}
   return(left<right);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::SwapEditState(CEdit &lhs,CEdit &rhs)
{
   string text=lhs.Text();
   color  clr =lhs.Color();

   lhs.Text(rhs.Text());
   lhs.Color(rhs.Color());

   rhs.Text(text);
   rhs.Color(clr);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::SwapButtonState(CButton &lhs,CButton &rhs)
{
   string text=lhs.Text();
   lhs.Text(rhs.Text());
   rhs.Text(text);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::SwapRowState(const int lhs,const int rhs)
{
   if(lhs==rhs) return;

   SetFileRecord set_tmp=g_sets[lhs];
   g_sets[lhs]=g_sets[rhs];
   g_sets[rhs]=set_tmp;

   datetime hist_scan_tmp=m_hist_last_scan[lhs];
   m_hist_last_scan[lhs]=m_hist_last_scan[rhs];
   m_hist_last_scan[rhs]=hist_scan_tmp;

   double hist_pl_tmp=m_hist_total_pl[lhs];
   m_hist_total_pl[lhs]=m_hist_total_pl[rhs];
   m_hist_total_pl[rhs]=hist_pl_tmp;

   int hist_trd_tmp=m_hist_total_trd[lhs];
   m_hist_total_trd[lhs]=m_hist_total_trd[rhs];
   m_hist_total_trd[rhs]=hist_trd_tmp;

   int gui_lhs=lhs+2, gui_rhs=rhs+2;
   SwapEditState(edt_Symbol   [gui_lhs],edt_Symbol   [gui_rhs]);
   SwapEditState(edt_Strategy [gui_lhs],edt_Strategy [gui_rhs]);
   SwapEditState(edt_Comment  [gui_lhs],edt_Comment  [gui_rhs]);
   SwapEditState(edt_News     [gui_lhs],edt_News     [gui_rhs]);
   SwapEditState(edt_AIBias   [gui_lhs],edt_AIBias   [gui_rhs]);
   SwapEditState(edt_RiskLots [gui_lhs],edt_RiskLots [gui_rhs]);
   SwapButtonState(btn_Action [gui_lhs],btn_Action   [gui_rhs]);
   SwapEditState(edt_Status   [gui_lhs],edt_Status   [gui_rhs]);
   SwapEditState(edt_HistDD   [gui_lhs],edt_HistDD   [gui_rhs]);
   SwapEditState(edt_Trades   [gui_lhs],edt_Trades   [gui_rhs]);
   SwapEditState(edt_Positions[gui_lhs],edt_Positions[gui_rhs]);
   SwapEditState(edt_Lots     [gui_lhs],edt_Lots     [gui_rhs]);
   SwapEditState(edt_PL_Open  [gui_lhs],edt_PL_Open  [gui_rhs]);
   SwapEditState(edt_PL_D1    [gui_lhs],edt_PL_D1    [gui_rhs]);
   SwapEditState(edt_PL_W1    [gui_lhs],edt_PL_W1    [gui_rhs]);
   SwapEditState(edt_PL_All   [gui_lhs],edt_PL_All   [gui_rhs]);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::SortRows(const ENUM_GOAT_DASH_SORT_KEY sort_key)
{
   int total=ArraySize(g_sets);
   if(total<2) return;

   for(int i=0;i<total-1;i++)
      for(int j=i+1;j<total;j++)
         if(ShouldSwapRows(i,j,sort_key))
            SwapRowState(i,j);

   m_rows_top=0;
   ApplyRowsViewport();
   UpdatePortfolioRow();
   ChartRedraw(0);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CGOATDashboard::ApplyRowsViewport(void)
{
   if(ArraySize(g_sets)<=0 || ArraySize(edt_Symbol)<2 || m_row_pitch<=0) return;

   RefreshRowsViewportMetrics();
   LayoutRowsScroll();

   const int total=ArraySize(g_sets);
   for(int i=0;i<total;i++)
   {
      int gui_row=i+2;
      int slot=i-m_rows_top;
      bool visible=(slot>=0 && slot<m_rows_visible);
      if(visible)
         MoveDataRow(gui_row,m_rows_y0+slot*m_row_pitch);
      SetDataRowVisible(gui_row,visible);
   }
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashScrollV::OnChangePos(void)
{
   bool ok=CScrollV::OnChangePos();
   if(ok && m_owner!=NULL)
      m_owner.RowsScrollTo(CurrPos());
   return(ok);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashScrollV::OnThumbDragProcess(void)
{
   bool ok=CScrollV::OnThumbDragProcess();
   if(ok && m_owner!=NULL)
      m_owner.RowsScrollTo(CurrPos());
   return(ok);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CGOATDashScrollV::OnThumbDragEnd(void)
{
   bool ok=CScrollV::OnThumbDragEnd();
   if(ok && m_owner!=NULL)
      m_owner.RowsScrollTo(CurrPos());
   return(ok);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------





