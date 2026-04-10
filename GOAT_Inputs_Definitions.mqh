#define   Key              "GOAT"
#define   EA_Name          MQLInfoString(MQL_PROGRAM_NAME)
#define   Server           AccountInfoString(ACCOUNT_SERVER)
#ifndef   GOAT_VERSION_LABEL
#define   GOAT_VERSION_LABEL "1.37"
#endif
#define   version_         GOAT_VERSION_LABEL
#define   NEWS_FILE        Key+"\\GOAT_News.csv"
#define   GMT_OFFSET_FILE  Key+"\\GOAT_GMToffset.txt"
#define   DST_FILE         Key+"\\GOAT_DST.txt"
#define   BIAS_FILE        Key+"\\BiasFiles\\GOAT_AI_Bias_"
//----------------------------------------------------------------------------------------------------------------------------------------------------
#define OP_BUY          0
#define OP_SELL         1
#define OP_SL           1
#define OP_TP           2
#define OP_NULL        -1
#define OP_NIL         -2
#define OP_BUYSELL      6
#define OP_None         7     // OnChart (Minimal)
#define OP_Dark         8     // OnChart (Dark Mode)
#define OP_Standard     9     // OnChart (Standard)
#define OP_Dash         8     // Portfolio DashBoard
//#define OP_Export       10    // Export Backtest (csv and set file)
#define OP_Batch        11    // Batch Optimizer
//#define OP_BatchRepExp  12
#define OP_ReportExport 13
#define GRID            121
#define GRID_MIN        122
#define GRID_MAX        123
#define GRID_VALID      124
#define LOCK            125
#define TSL             126
#define LICENSE_VALID   1505
#define MINUTE          60
#define HOUR            3600
#define DAY             86400
//+------------------------------------------------------------------+
//--- indents and gaps
#define INDENT_HORI                         (5)       // indent of panel horizontal
#define INDENT_VERT                         (20)      // indent of panel vertical
#define PANEL_WIDTH                         (320)     // width  of panel
#define PANEL_HEIGHT                        (980)     // height of panel
#define CHART_HEIGHT                        ((int)ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS,0))
#define INDENT_LEFT                         (0)       // indent from left (with allowance for border width)
#define INDENT_TOP                          (2)       // indent from top (with allowance for border width)
#define INDENT_RIGHT                        (0)       // indent from right (with allowance for border width)
#define INDENT_BOTTOM                       (1)       // indent from bottom (with allowance for border width)
#define GAP_X                               (-1)      // gap between Left and Right Section of a Row
#define GAP_Y                               (3)       // vertical gap between sections
#define BUTTON_WIDTH                        (40)      // size by X coordinate
//#define BUTTON_HEIGHT                       (18)      // size by Y coordinate
//--- for the indication area
//#define EDIT_HEIGHT                         (20)      // size by Y coordinate
//#define LABEL_HEIGHT                        (14)
//--- for group controls
//#define GROUP_WIDTH                         (150)     // size by X coordinate
//#define LIST_HEIGHT                         (179)     // size by Y coordinate
//#define RADIO_HEIGHT                        (56)      // size by Y coordinate
//#define CHECK_HEIGHT                        (93)      // size by Y coordinate
//----------------------------------------------------------------------------------------------------------------------------------------------------
enum ENUM_MODE_OPERATION // also adjust Writeset()
  {
 //Operation_None=OP_None,          // OnChart (Minimal)
 //Operation_Dark=OP_Dark,          // OnChart (Dark Mode)
   Operation_Standard=OP_Standard,  // OnChart (Standard)
   Operation_Batch=OP_Batch,        // Optimization Studio
                                    // Batch Optimizer with Set Exporter
   Operation_Report=OP_ReportExport,// Optimization Processor
                                    // XML Report Analyzer+Combiner+Exporter
 //Operation_Port,                  // Portfolio Builder
   Operation_Dash=OP_Dash,          // Portfolio DashBoard
 //Operation_Export=OP_Export,      // Export Backtest
                                    // Export Backtest (CSV+SET files)
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_SAMPLING
  {
   Tick=0,              // every Tick
   Second=-1,           // every Second
   M1=1,                // every Minute
   M_Current=99,        // every Bar/Candle
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_LOTS
  {
   FixedLots,           // Fixed Starting Lots
   ScaledLots,          // Scaled Starting Lots with equity
 //PercentageRisk,      // Percentage Risk (SL based, single trade only)
 //FixedRisk,           // Fixed Risk $$$ per Trade
   RiskperSeq,          // Starting Lots by Risk/Loss per Sequence
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_RRR
  {
   RRR_Disabled,        // Disabled (RRR not used)
   RRR_SL_TP,           // RRR=TP/SL - SL or TP must be 0
   RRR_SL_LP,           // RRR=LP/SL - SL or LP must be 0
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_TFs
  {
   TF_Cur = 0,          // Current
   TF_M1  = 1,          // M1
   TF_M5  = 5,          // M5
   TF_M15 = 15,         // M15
   TF_H1  = 60,         // H1
   TF_H4  = 240,        // H4
  };
//----------
ENUM_TIMEFRAMES TF2TF(ENUM_MODE_TFs TF)
  {
   switch(TF)
   {
    case TF_Cur:  return PERIOD_CURRENT;
    case TF_M1:   return PERIOD_M1;
    case TF_M5:   return PERIOD_M5;
    case TF_M15:  return PERIOD_M15;
    case TF_H1:   return PERIOD_H1;
    case TF_H4:   return PERIOD_H4;
    default:      return PERIOD_CURRENT;
   }
  }
//-------------------------------------------------------------------------
enum ENUM_MODE_PRICE
  {
   Price_Close=1,       // Price Close
   Price_Typical=6,     // Price Typical
   Price_Weighted=7,    // Price Weighted
   Price_Median=5,      // Price Median
  };
//----------
ENUM_APPLIED_PRICE PR2PR(ENUM_MODE_PRICE PR)
  {
   switch(PR)
   {
    case Price_Close:   return PRICE_CLOSE;
    case Price_Typical: return PRICE_TYPICAL;
    case Price_Weighted:return PRICE_WEIGHTED;
    case Price_Median:  return PRICE_MEDIAN;
    default:            return PRICE_CLOSE;
   }
  }
//-------------------------------------------------------------------------
enum ENUM_MODE_MA
  {
   EMA=0,               // EMA
   SMA=1,               // SMA
   LWMA=2,              // LWMA
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_SESSION
  {
   SESS_NONE,           // Dont Trade
   SESS_AS,             // Asian Session only
   SESS_AS_EU,          // Asian + EU Session
   SESS_EU,             // European Session only
   SESS_EU_US,          // EU + US Session
   SESS_US,             // US Session only
   SESS_ALL,            // Asian + EU + US
 //SESS_FRI,            // Same as Weekdays
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_SESSION2
  {
   SESSION_NONE,        // Dont Trade
   SESSION_AS,          // Asian Session only
   SESSION_AS_EU,       // Asian + EU Session
   SESSION_EU,          // European Session only
   SESSION_EU_US,       // EU + US Session
   SESSION_US,          // US Session only
   SESSION_ALL,         // Asian + EU + US
   SESSION_FRI,         // Same as Mon-Thu
  };
//-------------------------------------------------------------------------
enum ENUM_ACTION_NEWS
  {
   News_Display,        // Only display news
   News_Disabled,       // Disabled
   News_Avoid,          // Manage Open Sequence
   News_Pause,          // Pause Open Sequence (no new trades added)
   News_Close,          // Close All Trades and Pause
   News_Only,           // Trade During News Only
  };
//-------------------------------------------------------------------------
enum ENUM_ACTION_BIAS
  {
   Bias_Display,        // Only display AI bias
   Bias_Disabled,       // Disabled
 //Bias_Avoid,          // Only add sequences in AI bias direction
   Bias_Opens,          // Only add with AI Bias above threshold
 //Bias_Pause,          // Only add seq+trades in AI bias direction
 //Bias_Trd_cutoff,     // Only add seq+trades in AI bias direction above threshold
   Bias_Close_low,      // add in bias direction and close on opposite threshold
   Bias_Close_med,      // add above threshold and close on opposite threshold
   Bias_Close_high,     // add above threshold and close on sentiment flip
  };
//-------------------------------------------------------------------------
enum ENUM_BIAS_TRADES
  {
   Bias_Seq,            // Only restrict Sequence starts
   Bias_SeqTrade,       // Restrict Seq starts and trades
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_DOWNLOAD
  {
   Download_Disabled,   // Download Disabled
   Download_News,       // Only Download News
   Download_Bias,       // Only Download AI Bias
   Download_NewsBias,   // Download News and AI Bias
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_OPTI
  {
 //Opti_PF,             // Profit Factor (PF)
 //Opti_RF,             // Recovery Factor (RF)
   Opti_MRF,            // Adaptive Recovery Factor (ARF)
 //Opti_PF_MRF,         // PF x ARF
 //Opti_SPF_MRF,        // √PF x ARF
   Opti_PF_MRF,         // Dynamic Performance Index (DPI)
   Opti_PF_MRFp,        // DPI+ (Local agents only)
   Opti_PF_MRF_SR,      // Adaptive Recovery Coefficient (ARC)
   Opti_PF_MRF_SRp,     // ARC+ (Local agents only)
 //Opti_MRF_SD,         // MRF / Standard Dev
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_TRAIL
  {
   Trail_Lock,          // Start Trailing at Lock Level
   Trail_Lock_Pro,      // Start Trailing at Lock+Trail Level
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_TRADE_DIR
  {
   Long_and_Short,      // Long and Short
   Long,                // Long only
   Short,               // Short only
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_LOTSCLOSE
  {
   Close_Partial,       // Reduce by partial closing
   Close_OpenOpp,       // Reduce by opening opposite
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_LOTS_PROG
  {
   Lots_Prog_Start,     // Calculate by Starting Lots
   Lots_Prog_Last,      // Calculate by Exponential Lots
   Lots_Prog_Cum,       // Calculate by Cumulative Lots
   Lots_Prog_Cum2,      // Calculate by Front-Loaded Cumulative Lots
   Lots_Prog_Peak,      // Calculate by Peak Lots
   Lots_Prog_CumPartial,// Calculate by Cumulative Lots with retrace partial close
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_RESTART
  {
   Restart_Tmr =25,     // Restart next day
   Restart_1   =1,      // Restart in 1 hours
   Restart_2   =2,      // Restart in 2 hours
   Restart_3   =3,      // Restart in 3 hours
   Restart_5   =5,      // Restart in 5 hours
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_RSI
  {
   RSI_Disabled,        // Disabled
   RSI_OverBS,          // RSI Over Bought/Sold (Reversal)
   RSI_OverBSCross,     // RSI Cross back from OB/OS threshold
   RSI_OBSCEngulf,      // RSI Cross back and engulfing
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_TRADE
  {
   Trade_Disabled,      // Disabled
   Trade_Trend,         // Trend
   Trade_Trend_Range,   // Trend and Ranging Market
   Trade_Range,         // Ranging Market
   Trade_Counter_Range, // Counter Trend and Ranging
   Trade_Counter,       // Counter Trend
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_MACD_TREND
  {
   MACD_CO,             // MACD Crossover of zero level
   MACD_CO_G,           // Trending C/O of zero level
   MACD_CO_T,           // MACD C/O of threshold level
   MACD_CO_G_T,         // Trending C/O of threshold level
  };
//-------------------------------------------------------------------------
enum ENUM_MODE_BB
  {
   BB_Disabled,         // Disabled
   BB_Channel,          // Price within BB channel
   BB_OverBS,           // Sell Above and Buy Below (Reversal)
   BB_Trend,            // Buy Above and Sell Below (Trend)
 //BB_OverBS,           // Price out of BB Channel (Reversal)
 //BB_Trend,            // Price out of BB Channel (Trend)
  };
//-------------------------------------------------------------------------
/*enum ENUM_MA_PERIODS
  {
   MA_4_8_60,           // Fast(4)  Mid(8)  Slow(60)
   MA_8_13_21,          // Fast(8)  Mid(13) Slow(21)
   MA_9_21_55,          // Fast(9)  Mid(21) Slow(55)
   MA_10_50_100,        // Fast(10) Mid(50) Slow(100)
   MA_10_50_200,        // Fast(10) Mid(50) Slow(200)
  };*/
//-------------------------------------------------------------------------
enum ENUM_ACTION_CLOSE
  {
   Action_Null,         // Manage Open Sequence
   Action_Pause,        // Pause Open Sequence (no new trades added)
   Action_Close,        // Close All Trades
  };
//-------------------------------------------------------------------------
enum ENUM_FONT // font type
  {
   Font0, //Arial
   Font1, //Arial Black
   Font2, //Arial Bold
   Font3, //Arial Bold Italic
   Font4, //Arial Italic
   Font5, //Comic Sans MS Bold
   Font6, //Courier
   Font7, //Courier New
   Font8, //Courier New Bold
   Font9, //Courier New Bold Italic
   Font10, //Courier New Italic
   Font11, //Estrangelo Edessa
   Font12, //Franklin Gothic Medium
   Font13, //Gautami
   Font14, //Georgia
   Font15, //Georgia Bold
   Font16, //Georgia Bold Italic
   Font17, //Georgia Italic
   Font18, //Georgia Italic Impact
   Font19, //Latha
   Font20, //Lucida Console
   Font21, //Lucida Sans Unicode
   Font22, //Modern MS Sans Serif
   Font23, //MS Sans Serif
   Font24, //Mv Boli
   Font25, //Palatino Linotype
   Font26, //Palatino Linotype Bold
   Font27, //Palatino Linotype Italic
   Font28, //Roman
   Font29, //Script
   Font30, //Small Fonts
   Font31, //Symbol
   Font32, //Tahoma
   Font33, //Tahoma Bold
   Font34, //Times New Roman
   Font35, //Times New Roman Bold
   Font36, //Times New Roman Bold Italic
   Font37, //Times New Roman Italic
   Font38, //Trebuchet MS
   Font39, //Trebuchet MS Bold
   Font40, //Trebuchet MS Bold Italic
   Font41, //Trebuchet MS Italic
   Font42, //Tunga
   Font43, //Verdana
   Font44, //Verdana Bold
   Font45, //Verdana Bold Italic
   Font46, //Verdana Italic
   Font47, //Webdings
   Font48, //Westminster
   Font49, //Wingdings
   Font50, //WST_Czech
   Font51, //WST_Engl
   Font52, //WST_Fren
   Font53, //WST_Germ
   Font54, //WST_Ital
   Font55, //WST_Span
   Font56  //WST_Swed
  };
//----------------------------------------------------------------------------------------------------------------------------------------------------
class INTERVAL
  {
   public:
   datetime lastbar,lastbar2;
   int lastSecond,lastMinute;
   bool Check(ENUM_MODE_SAMPLING mode)
   {
    if(mode == Tick) return true;
    if(mode == Second)
    {
     int curSecond = stm_cur.sec;
     if(lastSecond != curSecond) {lastSecond = curSecond; return true;}
     return false;
    }
    if(mode == M1)
    {
     int curMinute = stm_cur.min;
     if(lastMinute != curMinute) {lastMinute = curMinute; return true;}
     return false;
    }
    if(mode == M_Current)
    {
     datetime curbar = (datetime)SeriesInfoInteger(_Symbol,PERIOD_CURRENT,SERIES_LASTBAR_DATE);
     if(lastbar != curbar) {lastbar = curbar; return true;}
     return false;
    }
    return false;
   }
   bool CheckTF(ENUM_TIMEFRAMES TF)
   {
    datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF,SERIES_LASTBAR_DATE);
    if(lastbar2 != curbar) {lastbar2 = curbar; return true;}
    return false;
   }
   INTERVAL() {}
  };
//----------------------------------------------------------------------------------------------------------------------------------------------------
void WriteSet(string desc)
{
//FileWrite(FileSET_handle,"; saved on "+TimeToString(TimeCurrent(),TIME_DATE)+" "+TimeToString(TimeCurrent(),TIME_MINUTES));
//FileWrite(FileSET_handle,"; this file contains input parameters for testing/optimizing the expert advisor: "+EA_Name);
FileWrite(FileSET_handle,desc);
FileWrite(FileSET_handle,"; ===========GENERAL SETTINGS============");
FileWrite(FileSET_handle,"Mode_Operation="+(string)OP_Standard);//Mode_Operation);
FileWrite(FileSET_handle,"EA_Desc="+Strat);
//FileWrite(FileSET_handle,"Font_Size="+(string)Font_Size);
//FileWrite(FileSET_handle,"Mode_Operation=99");//Mode_Operation);
FileWrite(FileSET_handle,"; ===========SEQUENCE SETTINGS===========");
FileWrite(FileSET_handle,"Signal_Sample_Period="+(string)Signal_Sample_Period);
FileWrite(FileSET_handle,"Sequence_Sample_Period="+(string)Sequence_Sample_Period);
FileWrite(FileSET_handle,"Trailing_Sample_Period="+(string)Trailing_Sample_Period);//=-1||0||0||99||N
FileWrite(FileSET_handle,"Allow_New_Sequence="+(string)Allow_New_Sequence);//=true
FileWrite(FileSET_handle,"Allow_Opposite_Seq="+(string)Allow_Opposite_Seq);
FileWrite(FileSET_handle,"Reverse_Seq="+(string)Reverse_Seq);//=false
FileWrite(FileSET_handle,"Mode_Trade="+(string)Mode_Trade);//=0||0||0||2||N
FileWrite(FileSET_handle,"Grid_Size="+(string)Grid_Size);//=-2||-1.0||-1.0||-15.0||Y
FileWrite(FileSET_handle,"Grid_Min="+(string)Grid_Min);//=-4||-1.0||-1.0||-4.0||Y
FileWrite(FileSET_handle,"Grid_Max="+(string)Grid_Max);//=-15||-10.0||-5.0||-25.0||Y
FileWrite(FileSET_handle,"Grid_Exponent="+(string)Grid_Exponent);//=0.9||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Grid_Factor="+(string)Grid_Factor);//=0.9||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Lock_Profit_Size="+(string)Lock_Profit_Size);//=-13||-10.0||-3.0||-28.0||Y
FileWrite(FileSET_handle,"Lock_Profit_Flexibility="+(string)Lock_Profit_Flexibility);//=0.2||-1.0||0.4||1.0||Y
FileWrite(FileSET_handle,"TP_Pips="+(string)TP_Pips);//=2.00||1.25||0.25||2.0||Y
FileWrite(FileSET_handle,"SL_Pips="+(string)SL_Pips);//=0||150.0||15.000000||1500.000000||N
FileWrite(FileSET_handle,"RRR="+(string)RRR);
FileWrite(FileSET_handle,"Mode_RRR="+(string)Mode_RRR);
FileWrite(FileSET_handle,"TSL_Size="+(string)TSL_Size);//=-12||-2.0||-2.0||-12.0||Y
FileWrite(FileSET_handle,"Mode_Trail="+(string)Mode_Trail);//=0||0||0||1||Y
FileWrite(FileSET_handle,"Delay_Trade="+(string)Delay_Trade);//=0||0||1||3||Y
FileWrite(FileSET_handle,"Delay_Trade_Live="+(string)Delay_Trade_Live);//=2||0||1||3||Y
FileWrite(FileSET_handle,"Delay_Lots_Add="+(string)Delay_Lots_Add);
//FileWrite(FileSET_handle,"Max_Seq_Levels="+(string)Max_Seq_Levels);//=10||7||3||13||Y
FileWrite(FileSET_handle,"Max_Seq_Trades="+(string)Max_Seq_Trades);//=8||2||1||9||Y
FileWrite(FileSET_handle,"CloseAtMaxLevels="+(string)CloseAtMaxLevels);//=true||false||0||true||N
FileWrite(FileSET_handle,"; =============ATR SETTINGS==============");
FileWrite(FileSET_handle,"ATR_TF_="+(string)ATR_TF_);//=1||1||0||5||Y
FileWrite(FileSET_handle,"ATR_Period="+(string)ATR_Period);//=800||100||100||900||Y
FileWrite(FileSET_handle,"ATR_Method="+(string)ATR_Method);//=1||1||0||2||Y
FileWrite(FileSET_handle,"; ============POSITION SIZING============");
FileWrite(FileSET_handle,"Mode_Lots="+(string)Mode_Lots);//=0
FileWrite(FileSET_handle,"Risk="+(string)Risk);//=1
FileWrite(FileSET_handle,"Lots_Input="+(string)Lots_Input);//=0.1||0.1||0.010000||1.000000||N
FileWrite(FileSET_handle,"Lots_Max="+(string)Lots_Max);//=0.2||0.2||0.1||0.9||Y
FileWrite(FileSET_handle,"Lots_Max_Cum="+(string)Lots_Max_Cum);//=0.2||0.2||0.1||0.9||Y
FileWrite(FileSET_handle,"Lots_Exponent="+(string)Lots_Exponent);//=1.4||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Lots_Factor="+(string)Lots_Factor);//=1.4||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Mode_Lots_Prog="+(string)Mode_Lots_Prog);
FileWrite(FileSET_handle,"Peak_Lots_Pos_PC="+(string)Peak_Lots_Pos_PC);
FileWrite(FileSET_handle,"Partial_Profit_Factor="+(string)Partial_Profit_Factor);
FileWrite(FileSET_handle,"; ============MONEY MANAGEMENT===========");
FileWrite(FileSET_handle,"MaxLossLocal="+(string)MaxLossLocal);//=0
FileWrite(FileSET_handle,"MaxLossGlobal="+(string)MaxLossGlobal);//=0
FileWrite(FileSET_handle,"MaxDailyLossLocal="+(string)MaxDailyLossLocal);//=0
FileWrite(FileSET_handle,"MaxDailyProfitLocal="+(string)MaxDailyProfitLocal);//=0
FileWrite(FileSET_handle,"MinLevelEquity="+(string)MinLevelEquity);//=0
FileWrite(FileSET_handle,"MaxLevelEquity="+(string)MaxLevelEquity);//=0
FileWrite(FileSET_handle,"Mode_Restart="+(string)Mode_Restart);//=25
FileWrite(FileSET_handle,"; =============RSI SETTINGS==============");
FileWrite(FileSET_handle,"RSI_Mode="+(string)RSI_Mode);//=1||0||0||2||N
FileWrite(FileSET_handle,"RSI_TF_="+(string)RSI_TF_);//=15||1||0||15||Y
FileWrite(FileSET_handle,"RSI_Period="+(string)RSI_Period);//=7||3||2||9||Y
FileWrite(FileSET_handle,"RSI_Price="+(string)RSI_Price);//=6||5||0||6||N
FileWrite(FileSET_handle,"RSI_Level="+(string)RSI_Level);//=80||80.0||3.0||92.0||Y
FileWrite(FileSET_handle,"; ========MOVING AVERAGE SETTINGS========");
FileWrite(FileSET_handle,"EMA_Mode="+(string)EMA_Mode);//=5||1||0||5||Y
FileWrite(FileSET_handle,"EMA_TF_="+(string)EMA_TF_);//=5||5||0||60||Y
FileWrite(FileSET_handle,"EMA_Method="+(string)EMA_Method);//=1||1||0||3||Y
FileWrite(FileSET_handle,"EMA_Price="+(string)EMA_Price);//=6||5||0||7||N
FileWrite(FileSET_handle,"EMA_Count="+(string)EMA_Count);//=4||5||1||50||N
FileWrite(FileSET_handle,"EMA_Period="+(string)EMA_Period);//=4||7||1||70||N
FileWrite(FileSET_handle,"EMA_Exponent="+(string)EMA_Exponent);//=2||1.5||0.150000||15.000000||N
FileWrite(FileSET_handle,"EMA_MustCheck="+(string)EMA_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============ADX SETTINGS==============");
FileWrite(FileSET_handle,"ADX_Mode="+(string)ADX_Mode);//=4||1||0||5||Y
FileWrite(FileSET_handle,"ADX_TF_="+(string)ADX_TF_);//=15||5||0||60||Y
FileWrite(FileSET_handle,"ADX_Period="+(string)ADX_Period);//=16||8||4||24||Y
FileWrite(FileSET_handle,"ADX_Level="+(string)ADX_Level);//=27||18.0||3.0||33.0||Y
FileWrite(FileSET_handle,"ADX_MustCheck="+(string)ADX_MustCheck);//=true||false||0||true||Y
FileWrite(FileSET_handle,"; =======BOLLINGER BANDS SETTINGS========");
FileWrite(FileSET_handle,"BB_Mode="+(string)BB_Mode);//=1||1||0||3||Y
FileWrite(FileSET_handle,"BB_TF_="+(string)BB_TF_);//=15||15||0||240||Y
FileWrite(FileSET_handle,"BB_Period="+(string)BB_Period);//=10||10||10||50||Y
FileWrite(FileSET_handle,"BB_Deviation="+(string)BB_Deviation);//=1.5||0.5||0.5||2.5||Y
//FileWrite(FileSET_handle,"BB_Price="+(string)BB_Price);//=1||1||0||7||N
FileWrite(FileSET_handle,"BB_MustCheck="+(string)BB_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============MACD SETTINGS=============");
FileWrite(FileSET_handle,"MACD_Mode="+(string)MACD_Mode);//=3||1||0||5||Y
FileWrite(FileSET_handle,"MACD_Mode_Trend="+(string)MACD_Mode_Trend);//=3||0||0||3||Y
FileWrite(FileSET_handle,"MACD_TF_="+(string)MACD_TF_);//=15||5||0||60||Y
FileWrite(FileSET_handle,"MACD_Fast="+(string)MACD_Fast);//=13||5||2||13||Y
FileWrite(FileSET_handle,"MACD_Slow="+(string)MACD_Slow);//=24||15||3||27||Y
FileWrite(FileSET_handle,"MACD_Signal="+(string)MACD_Signal);//=11||5||2||11||Y
FileWrite(FileSET_handle,"MACD_Deviations="+(string)MACD_Deviations);//=2.0||2.0||0.5||3.0||Y
FileWrite(FileSET_handle,"MACD_Price="+(string)MACD_Price);//=6||6||0||7||Y
FileWrite(FileSET_handle,"MACD_MustCheck="+(string)MACD_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============RSI2 SETTINGS==============");
FileWrite(FileSET_handle,"RSI2_Mode="+(string)RSI2_Mode);//=0||0||0||3||N
FileWrite(FileSET_handle,"RSI2_TF_="+(string)RSI2_TF_);//=15||0||0||240||N
FileWrite(FileSET_handle,"RSI2_Period="+(string)RSI2_Period);//=13||13||1||130||N
FileWrite(FileSET_handle,"RSI2_Price="+(string)RSI2_Price);//=1||1||0||7||N
FileWrite(FileSET_handle,"RSI2_Level="+(string)RSI2_Level);//=70.0||90.0||9.000000||900.000000||N
FileWrite(FileSET_handle,"RSI2_MustCheck="+(string)RSI2_MustCheck);//=false||false||0||true||N
FileWrite(FileSET_handle,"; ===========TRADING SCHEDULE============");
//FileWrite(FileSET_handle,"Active_Time_Monday="+(string)Active_Time_Monday);//=02:00-22:30
//FileWrite(FileSET_handle,"Active_Time_Tuesday="+(string)Active_Time_Tuesday);//=01:30-22:30
//FileWrite(FileSET_handle,"Active_Time_Wednesday="+(string)Active_Time_Wednesday);//=01:30-22:30
//FileWrite(FileSET_handle,"Active_Time_Thursday="+(string)Active_Time_Thursday);//=01:30-22:30
FileWrite(FileSET_handle,"Active_Time_Weekday="+(string)Active_Time_Weekday);
FileWrite(FileSET_handle,"Active_Time_Friday="+(string)Active_Time_Friday);
FileWrite(FileSET_handle,"Active_Time_ASIA="+(string)Active_Time_ASIA);//"01:30-11:00";// Session Times (Asia)
FileWrite(FileSET_handle,"Active_Time_EU="+(string)Active_Time_EU);//"10:00-19:00";// Session Times (Europe)
FileWrite(FileSET_handle,"Active_Time_US="+(string)Active_Time_US);//"15:00-22:30";// Session Times (US)
FileWrite(FileSET_handle,"Action_Dayend="+(string)Action_Dayend);//=1||0||0||1||Y
FileWrite(FileSET_handle,"Action_Friday="+(string)Action_Friday);//=2||0||0||2||Y
FileWrite(FileSET_handle,"Trade_Friday="+(string)Trade_Friday);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; ==========NEWS AND AI BIAS FILTER==========");
FileWrite(FileSET_handle,"Mode_Bias="+(string)Mode_Bias);
FileWrite(FileSET_handle,"Mode_Bias_Trades="+(string)Mode_Bias_Trades);
FileWrite(FileSET_handle,"Bias_threshold="+(string)Bias_threshold);
FileWrite(FileSET_handle,"Mode_News="+(string)Mode_News);//=1||1||0||4||Y
FileWrite(FileSET_handle,"News_threshold="+(string)News_threshold);
FileWrite(FileSET_handle,"News_beforeMinutes="+(string)News_beforeMinutes);//=100||120||1||1200||N
FileWrite(FileSET_handle,"News_afterMinutes="+(string)News_afterMinutes);//=100||100||100||200||Y
//FileWrite(FileSET_handle,"News_ExcludeKeywords="+(string)News_ExcludeKeywords);//=crude,zew,ifo,lagarde
FileWrite(FileSET_handle,"; ==========AI BIAS/NEWS DATA DOWNLOADER=========");
FileWrite(FileSET_handle,"Mode_Download="+(string)Mode_Download);
//FileWrite(FileSET_handle,"Download_News_FileName="+(string)Download_News_FileName);//=GOAT_News
//FileWrite(FileSET_handle,"Download_StartDate="+(string)Download_StartDate);//=1672531200
FileWrite(FileSET_handle,"Download_StartDate="+TimeToString(Download_StartDate,TIME_DATE));
//FileWrite(FileSET_handle,"Download_NewsCurrencies="+(string)Download_NewsCurrencies);//=EUR,USD,GBP,JPY,CHF,AUD,CAD,NZD
FileWrite(FileSET_handle,"; ========OPTIMIZATION PARAMETERS========");
FileWrite(FileSET_handle,"Mode_Opti="+(string)Mode_Opti);//=5
FileWrite(FileSET_handle,"Seq_min_inp="+(string)Seq_min_inp);//=100
FileWrite(FileSET_handle,"Trades_min_inp="+(string)Trades_min_inp);//=250
FileWrite(FileSET_handle,"Trades_Max="+(string)Trades_Max);//=1500
FileWrite(FileSET_handle,"Minutes_Max="+(string)Minutes_Max);//=1000
FileWrite(FileSET_handle,"Trade_December="+(string)Trade_December);//=false
FileClose(FileSET_handle); FileSET_handle=INVALID_HANDLE;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
//extern   double                  BatchOnGoing;
//----------------------------------------------------------------------------------------------------------------------------------------------------
input    group                   "===========GENERAL SETTINGS============                    ";
sinput   ENUM_MODE_OPERATION     Mode_Operation                =            Operation_Standard;       // Operation Mode
input    string                  EA_Desc                       =                "GOAT_Trading";       // Strategy Comment
         int                     Font_Size_Base                =                            10;       // Base Font Size
         int                     DWidth                        =                           900;
         int                     DHeight                       =                           530;
//sinput   
         ENUM_FONT               Font_Header                   =                         Font1;
//sinput   
         ENUM_FONT               Font_SubHeader                =                         Font2;
//sinput   
         ENUM_FONT               Font_Text                     =                         Font0;
//input  bool                    TestingPause                  =                          true;       // Pause During Visual Back Testing ?
//input    
         bool                    ArrowDraw                     =                         false;       // Draw Arrow on Signal ?
//sinput   
         bool                    DrawVLines                    =                          true;       // Draw News/inactive Lines ?
//input    
         bool                    Alerts_Popup                  =                         false;       // Pop Up Alerts
//input    
         bool                    Alerts_Notifications          =                         false;       // Push Notifications
input    group                   "===========SEQUENCE SETTINGS===========                    ";
sinput   ENUM_MODE_SAMPLING      Signal_Sample_Period          =                            M1;       // Check Signal (Sequence Start Only)
sinput   ENUM_MODE_SAMPLING      Sequence_Sample_Period        =                            M1;       // Check Sequence
input    ENUM_MODE_SAMPLING      Trailing_Sample_Period        =                        Second;       // Check Trailing/Lock/TP
sinput   bool                    Allow_New_Sequence            =                          true;       // Allow New Sequence
input    bool                    Allow_Opposite_Seq            =                          true;       // Allow Opposite Sequences
input    bool                    Reverse_Seq                   =                         false;       // Reverse Sequence Direction
input    ENUM_MODE_TRADE_DIR     Mode_Trade                    =                Long_and_Short;       // Sequence Type
input    double                  Grid_Size                     =                          10.0;       // Pip Gap Size (-ve for ATR)
input    double                  Grid_Min                      =                           1.0;       // Pip Gap Minimum (-ve for ATR)
input    double                  Grid_Max                      =                          30.0;       // Pip Gap Maximum (-ve for ATR)
input    double                  Grid_Exponent                 =                           1.2;       // Pip Gap Exponent
input    double                  Grid_Factor                   =                           1.0;       // Dynamic Gap Factor (1=no effect)
input    double                  Lock_Profit_Size              =                          30.0;       // Lock Profit (LP) Pips (-ve for ATR)
input    double                  Lock_Profit_Flexibility       =                           1.0;       // Dynamic LP (1=same, 0=BE, -1=-LP)
input    double                  TP_Pips                       =                           2.0;       // TP Size (multiplies LP, must be >1)
input    double                  SL_Pips                       =                           0.0;       // SL pips (-ve for ATR)
input    double                  RRR                           =                           0.0;       // Risk/Reward Ratio
input    ENUM_MODE_RRR           Mode_RRR                      =                  RRR_Disabled;       // RRR Calculation Method
input    double                  TSL_Size                      =                           5.0;       // Trailing SL Pips (-ve for ATR)
input    ENUM_MODE_TRAIL         Mode_Trail                    =                    Trail_Lock;       // Trailing Mode
input    int                     Delay_Trade                   =                             1;       // Delay Trade Sequence
input    int                     Delay_Trade_Live              =                             1;       // Live Delay Sequence
input    bool                    Delay_Lots_Add                =                          true;       // Add Delayed Lots
         int                     Max_Seq_Levels                =                            99;       // Max Levels in a Sequence
input    int                     Max_Seq_Trades                =                            10;       // Max Trades/Entries in a Sequence
input    bool                    CloseAtMaxLevels              =                         false;       // Close Sequence after Max Trades
input    group                   "=============ATR SETTINGS==============                    ";
input    ENUM_MODE_TFs           ATR_TF_                       =                         TF_M1;       // ATR Timeframe
input    int                     ATR_Period                    =                           100;       // ATR Averaging Period
input    ENUM_MODE_MA            ATR_Method                    =                           SMA;       // ATR Averaging Method
input    group                   "============POSITION SIZING============                    ";
sinput   ENUM_MODE_LOTS          Mode_Lots                     =                     FixedLots;       // Sizing Method (For Starting Lots)
sinput   double                  Risk                          =                           500;       // Risk/Loss per Sequence in $$$
input    double                  Lots_Input                    =                           0.1;       // Starting Lots (Fixed/Scaled)
input    double                  Lots_Max                      =                          10.0;       // Max Trade Lots (multiplies Starting Lots)
input    double                  Lots_Max_Cum                  =                          50.0;       // Max Cumulative Lots (multiplies Starting Lots)
input    double                  Lots_Exponent                 =                           1.2;       // Lots Exponent
input    double                  Lots_Factor                   =                           1.0;       // Dynamic Lots Factor (1=no effect)
//sinput ENUM_MODE_LOTSCLOSE     Mode_LotsClose                =                 Close_Partial;       // Net Lots reduction method
input    ENUM_MODE_LOTS_PROG     Mode_Lots_Prog                =                Lots_Prog_Last;       // Lots Progression Model
input    double                  Peak_Lots_Pos_PC              =                          50.0;       // % Position in sequence where Lots peak
input    double                  Partial_Profit_Factor         =                          10.0;       // % Standing lots to close on each retrace level
input    group                   "============RISK MANAGEMENT===========                    ";
sinput   double                  MaxLossLocal                  =                           0.0;       // Max Local Running Loss amount
sinput   double                  MaxLossGlobal                 =                           0.0;       // Max Global Running Loss amount
input    double                  MaxDailyLossLocal             =                           0.0;       // Max Daily Local Loss amount
input    double                  MaxDailyProfitLocal           =                           0.0;       // Max Daily Local Profit amount
//sinput double                  MaxDD                         =                          99.9;       // Global Max Daily Drawdown %
//sinput double                  MaxDP                         =                          99.9;       // Global Daily Profit Target %
sinput   double                  MinLevelEquity                =                           0.0;       // Low Equity Stop Level
sinput   double                  MaxLevelEquity                =                           0.0;       // Equity Target Level
sinput   ENUM_MODE_RESTART       Mode_Restart                  =                   Restart_Tmr;       // Restart after loss
//sinput   
         int                     MaxSP                         =                          9999;       // Maximum Spread (in Points)
input    group                   "=============RSI SETTINGS==============                    ";
//input  bool                    RSI_Enable                    =                          true;       // Enable RSI
input    ENUM_MODE_RSI           RSI_Mode                      =                    RSI_OverBS;       // Mode
input    ENUM_MODE_TFs           RSI_TF_                       =                         TF_M1;       // Timeframe
input    uint                    RSI_Period                    =                             4;       // Period
input    ENUM_MODE_PRICE         RSI_Price                     =                 Price_Typical;       // Applied Price
input    double                  RSI_Level                     =                            80;       // High Level (Low level mirrored)
input    group                   "========MOVING AVERAGE SETTINGS========                    ";
input    ENUM_MODE_TRADE         EMA_Mode                      =                   Trade_Trend;       // Mode
input    ENUM_MODE_TFs           EMA_TF_                       =                        TF_M15;       // Timeframe
input    ENUM_MA_METHOD          EMA_Method                    =                      MODE_EMA;       // Method
input    ENUM_MODE_PRICE         EMA_Price                     =                 Price_Typical;       // Applied Price
input    int                     EMA_Count                     =                             5;       // Number of MAs
input    int                     EMA_Period                    =                             7;       // Fastest/Smallest Period
input    double                  EMA_Exponent                  =                           1.5;       // MA Exponent
//input  ENUM_MA_PERIODS         EMA_Periods                   =                     MA_4_8_60;       // Period Combinations
input    bool                    EMA_MustCheck                 =                         false;       // Must Check (When Delay is used)
input    group                   "=============ADX SETTINGS==============                    ";
input    ENUM_MODE_TRADE         ADX_Mode                      =                   Trade_Trend;       // Mode
input    ENUM_MODE_TFs           ADX_TF_                       =                        TF_M15;       // Timeframe
input    uint                    ADX_Period                    =                            14;       // Period
input    double                  ADX_Level                     =                            30;       // Buy/Sell Level
input    bool                    ADX_MustCheck                 =                         false;       // Must Check (When Delay is used)
input    group                   "=======BOLLINGER BANDS SETTINGS========                    ";
input    ENUM_MODE_BB            BB_Mode                       =                   BB_Disabled;       // Mode
input    ENUM_MODE_TFs           BB_TF_                        =                         TF_H1;       // Timeframe
input    uint                    BB_Period                     =                           120;       // Period
input    double                  BB_Deviation                  =                           1.5;       // Deviation
         ENUM_APPLIED_PRICE      BB_Price                      =                   PRICE_CLOSE;       // Applied price
input    bool                    BB_MustCheck                  =                         false;       // Must Check (When Delay is used)
sinput   group                   "=============MACD SETTINGS=============                    ";
input    ENUM_MODE_TRADE         MACD_Mode                     =                Trade_Disabled;       // Mode
input    ENUM_MODE_MACD_TREND    MACD_Mode_Trend               =                       MACD_CO;       // MACD Trend Mode
input    ENUM_MODE_TFs           MACD_TF_                      =                        TF_M15;       // Timeframe
input    uint                    MACD_Fast                     =                            12;       // Fast Period
input    uint                    MACD_Slow                     =                            26;       // Slow Period
input    uint                    MACD_Signal                   =                             9;       // Signal Period
input    double                  MACD_Deviations               =                           2.0;       // Threshold Size
input    ENUM_MODE_PRICE         MACD_Price                    =                 Price_Typical;       // Applied price
input    bool                    MACD_MustCheck                =                         false;       // Must Check (When Delay is used)
input    group                   "=============RSI2 SETTINGS==============                   ";
input    ENUM_MODE_RSI           RSI2_Mode                     =                  RSI_Disabled;       // Mode
input    ENUM_MODE_TFs           RSI2_TF_                      =                        TF_M15;       // Timeframe
input    uint                    RSI2_Period                   =                            13;       // Period
input    ENUM_MODE_PRICE         RSI2_Price                    =                 Price_Typical;       // Applied Price
input    double                  RSI2_Level                    =                            70;       // High Level (Low level mirrored)
input    bool                    RSI2_MustCheck                =                         false;       // Must Check (When Delay is used)
input    group                   "===========TRADING SCHEDULE============                    ";
input    ENUM_MODE_SESSION       Active_Time_Weekday           =                      SESS_ALL;       // Trading Times (Mon-Thu)
input    ENUM_MODE_SESSION2      Active_Time_Friday            =                    SESSION_AS;       // Trading Times (Friday)
input    string                  Active_Time_ASIA              =                 "01:30-11:00";       // Session Times (Asia)
input    string                  Active_Time_EU                =                 "10:00-19:00";       // Session Times (Europe)
input    string                  Active_Time_US                =                 "15:00-22:30";       // Session Times (US)
//input  string                  Active_Time_Monday            =                 "02:00-22:30";       // Trading Times (Monday)
//input  string                  Active_Time_Tuesday           =                 "01:30-22:30";       // Trading Times (Tuesday)
//input  string                  Active_Time_Wednesday         =                 "01:30-22:30";       // Trading Times (Wednesday)
//input  string                  Active_Time_Thursday          =                 "01:30-22:30";       // Trading Times (Thursday)
//input  string                  Active_Time_Friday            =                 "01:30-22:00";       // Trading Times (Friday)
//input  string                  Active_Time_Saturday          =                 "01:30-22:00";       // Trading Times (Saturday)
//input  string                  Active_Time_Sunday            =                 "01:30-22:00";       // Trading Times (Sunday)
input    ENUM_ACTION_CLOSE       Action_Dayend                 =                   Action_Null;       // Action at End of Session
input    ENUM_ACTION_CLOSE       Action_Friday                 =                   Action_Null;       // Action at Friday Close
input    bool                    Trade_Friday                  =                          true;       // Start New Sequences on Friday
input    group                   "==========NEWS AND AI FILTER==========                   ";
input    ENUM_ACTION_BIAS        Mode_Bias                     =                 Bias_Disabled;       // AI Bias Mode
input    ENUM_BIAS_TRADES        Mode_Bias_Trades              =                      Bias_Seq;       // AI Bias restriction
input    int                     Bias_threshold                =                            60;       // AI Confidence Threshold
input    ENUM_ACTION_NEWS        Mode_News                     =                 News_Disabled;       // News Mode
input    int                     News_threshold                =                            60;       // News Impact threshold
input    int                     News_beforeMinutes            =                            90;       // Before News Minutes
input    int                     News_afterMinutes             =                           150;       // After News Minutes
//input    
         int                     News_RegenerateMinutes        =                            60;       // News Regenerate Minutes
         int                     Bias_RegenerateMinutes        =                            10;       // AI Bias Regenerate Minutes
//input  string                  News_IncludeKeywords          =                            "";       // News Keywords that Must Include ( , separated)
                                 //  "Employment,Payrolls,Interest,Lagarde,Powell,GDP,CPI,ISM";       // News Keywords that Must Include ( , separated)
//input  string                  News_ExcludeKeywords          =       "crude,zew,ifo,lagarde";       // News Keywords that Get Excluded ( , separated)
input    group                   "==========AI BIAS/NEWS DATA DOWNLOADER=========               ";
sinput   ENUM_MODE_DOWNLOAD      Mode_Download                 =             Download_Disabled;       // Data Download Mode for Backtest
       //string                  Download_News_FileName        =                   "GOAT_News";       // News Data File Name
       //string                  Download_Bias_FileName        =                   "GOAT_Bias";       // AI Bias Data File Name
sinput   datetime                Download_StartDate            =                 D'2025.01.01';       // Download Start Date
         string                  Download_NewsCurrencies    ="EUR,USD,GBP,JPY,CHF,AUD,CAD,NZD";       // Currencies to Download
input    group                   "========OPTIMIZATION PARAMETERS========                    ";
sinput   ENUM_MODE_OPTI          Mode_Opti                     =               Opti_PF_MRF_SRp;       // Fitness Calculation
sinput   int                     Seq_min_inp                   =                           100;       // Ideal Minimum Traded Sequences
//sinput int                     Seq_mid                       =                           100;       // Start degrading Fitness if Sequences below this
sinput   int                     Trades_min_inp                =                           300;       // Ideal Minimum Trades
//sinput int                     Trades_mid                    =                           350;       // Start degrading Fitness if Trades below this
sinput   int                     Trades_Max                    =                          1500;       // Max Trades Opened
sinput   int                     Minutes_Max                   =                          1000;       // Max Avg Trade duration (Minutes)
sinput   bool                    Trade_December                =                          true;       // Trade December ?
/*input  group                   "=============NEWS DISPLAY==============                    ";
input    bool                    input_ShowComments            =                          true;       // Show Comments
input    string                  input_Prefix                  =                        "News";       // News Text Label
input    int                     input_NoOfNewsDisplayedOnChart=                             5;       // No Of News Displayed On Chart
input    color                   input_TextColor               =                      clrWhite;       // Text Color
input    string                  input_FontName                =                      "Tahoma";       // Text Font Name
input    int                     input_FontSize                =                             8;       // Text Font Size
input    int                     input_dy                      =                            17;       // Space Between Rows, pixels
 input   int                     input_StartX                  =                            10;       // Start Space From Sides, pixels
input    int                     input_StartY                  =                            30;       // Start Space From Top, pixels
input    color                   input_CommentsLabelColor      =                      clrBlack;       // Comments Label Color
input    bool                    input_CommentsTrasparentBackground=                     false;       // Use Transparent Label Color*/
//----------------------------------------------------------------------------------------------------------------------------------------------------
int      orders=0,orderErrors=0,TPSLmodifieds=0,TPmodifyErrors=0,TSLmodifieds=0,TSLmodifyErrors=0,closed=0,closeErrors=0,Pclosed=0,PcloseErrors=0;

double   Lots,Lots_Order,Lots_Current,Lots_Desired;

bool     FirstRun=true,Active=false,InActive=true,Pause_Flag=false,StopOut_Flag=false,StopOut_Flag_B=false,StopOut_Flag_S=false,FastSpeed_Flag=false;
bool     Sequence_New_News=true,Sequence_New_Bias_B=true,Sequence_New_Bias_S=true,Sequence_New_Friday=true,Sequence_New_Dec=true;
bool     Sequence_Pause_Close=false,Sequence_Pause_News=false,Sequence_Pause_Bias_B=false,Sequence_Pause_Bias_S=false;
int      Sequence_Skipped_News=0,Sequence_Skipped_Bias_B=0,Sequence_Skipped_Bias_S=0;
int      Trades_Skipped_News=0,Trades_Skipped_Bias_B=0,Trades_Skipped_Bias_S=0;
bool     Buy_EN,Sell_EN,MustCheck_Buy=false,MustCheck_Sell=false;
int      arrows=0,lines=0,lines_news=0,lines_bias=0,timer=0,days=0,Positions=0,Sequences=0,Sequences_PL=0;    // iterators
int      Weekend_day;

int      TotalText_Trade  =  20;
int      TotalText_Signal =  13;
int      Font_Size        =   7;
//int    Font_Size_Header =   0;
double   Spacing_Text     = 1.0;
//color  clr_Text=clrDarkGray;
color    clr_Header=clrOlive;

int Vertical_Pointer;

color clr_CaptionBack   = C'15,23,42';
color clr_CaptionBorder = clrWhite;//C'15,23,42';     // caption is wider than client by 2px and now 1px
color clr_ClientBack    = clrWhite;
color clr_ClientBorder  = clrWhite;
color clr_RowBack       = C'15,23,42';
color clr_RowBorders    = C'15,23,42';
color clr_Text          = clrWhite;
color clr_Buy           = C'37,189,0';
color clr_Sell          = C'190,0,5';
color clr_Null          = C'224,135,6';
//ENUM_BASE_CORNER TextCorner;
bool     BuySig, SellSig;
bool     PrevBuySig, PrevSellSig;
bool     BuyExit, SellExit, BuyPartialExit, SellPartialExit;
bool     PrevBuyExit, PrevSellExit;

#define GOAT_EVENT_CHILD_STATUS   (CHARTEVENT_CUSTOM + 101)
#define GOAT_GV_FIELD_CID         "CID"
#define GOAT_GV_FIELD_MAGIC       "Magic"
#define GOAT_GV_FIELD_HEARTBEAT   "HB"
#define GOAT_GV_FIELD_OPEN_TRADES "OTR"
#define GOAT_GV_FIELD_OPEN_LOTS   "OLT"
#define GOAT_GV_FIELD_OPEN_PL     "OPL"
#define GOAT_GV_FIELD_PL_DAILY    "PLD"
#define GOAT_GV_FIELD_PL_WEEKLY   "PLW"
#define GOAT_GV_FIELD_PL_TOTAL    "PLT"
#define GOAT_GV_FIELD_TRADES_TOTAL "TRD"
#define GOAT_GV_FIELD_NEWS        "NEWS"
#define GOAT_GV_FIELD_BIAS        "BIAS"

int      SL_Points,TP_Points;
int      MAGIC1=0,MAGIC2=0,LicenseKey=0;

MqlDateTime    stm_cur;

double   bid,ask;
long     Hour_Start[7],Hour_End[7],Minute_Start[7],Minute_End[7];
datetime tm_cur,LastTradeTime,LastStopoutTime,DStartTime;
uint     LastRetCode,Shift_Sig;
int      LastOrderTicket,LastDealTicket,LastBuyTicket,LastSellTicket,LastTradeCountBuy=0,LastTradeCountSell=0;
double   LastOpen,LastSL,LastTP;
double   Grid_Min_,Grid_Max_,LP_Size_,TP_Pips_,SL_Pips_,TSL_Size_;//,Lots_Max_;

double   DStartEquity=0,StartingEquity=0,randA=0,randB=0,MaxEquity=0,CurrentDDD=0,CurrentDD=0,DStartLocalLoss=99999;
double   DDs[],DDs_PC[],DDs_Actual[],Sequence_Profits[],Position_Durations[];

ENUM_TIMEFRAMES ATR_TF,RSI_TF,EMA_TF,ADX_TF,BB_TF,MACD_TF,RSI2_TF;

int      ATR_handle,ATR_MA_handle;
int      RSI_handle,EMA_handles[],ADX_handle,BB_handle,MACD_handle,RSI2_handle;
int      RSI_Sig   ,EMA_Sig      ,ADX_Sig   ,BB_Sig   ,MACD_Sig   ,RSI2_Sig;
//int    EMA_Periods[];//,EMA2_Period,EMA3_Period;
int      Exit_Sig1,Exit_Sig2;

double   ATR_Buf[],ATR_Pips,
         RSI_Buf[],
         EMA1_Buf[],EMA2_Buf[],EMA3_Buf[],
         ADX_Main_Buf[],ADX_PLS_Buf[],ADX_MNS_Buf[],
         BB_Hi_Buf[],BB_Lo_Buf[],BB_Mi_Buf[],
         MACD_Main_Buf[],MACD_Sig_Buf[],MACD_Clr_Buf[],
         RSI2_Buf[];
class BUF
  {
   public:
   double Buf[];
   BUF()  {ArraySetAsSeries(Buf,true); ArrayResize(Buf,1);}
  };
BUF EMAs[];
/*
string   LANG="en-US";
sNews    NEWS_TABLE[],HEADS;
datetime date1;
int      TIME_CORRECTION;
bool     NEWS_ON=false;
*/
string   URL_Web        = "www.GOATedge.ai";//"https://www.GOATalgo.com/";
string   URL_API        = "https://goatedge.ai";//"https://api.goatalgo.com";
//string URL_API2       = "https://eloquent-nature-75ba63ed82.strapiapp.com/api/metatrader/check-id";
string   requestHeaders = "Content-Type: application/json; charset=UTF-8\r\n"
                          "Authorization: Bearer 664ff7e62275f1ee4438b264e4928176940a7e25c3401b596334a73d689a2dd4"+
                                                "6d647c15a5ee7af289757589ad7f872ad3f74853a120b39d79822dddd2126196";
int      timeout  =                                  5000;
long     Licensed_Account_Number =                      0;  // Account Number     ( 0  for not checking )
string   Licensed_Account_Title  =                     "";  // Account Title/Name ( "" for not checking )
datetime Expiry                  = D'2026.06.26 22:00:00';  // Year Month Day Hours Minutes Seconds
//+------------------------------------------------------------------+
//input string EA_Desc = "EA_Strategy@{mode=EXPORT,dt_BOOS_end=2025.09.01,dt_FOOS_start=2025.09.30"; // Strategy Comment datetime dt_Back_OOS=0,dt_Fwrd_OOS=0;
//input int    Input1 = 1;
//input int    Input2 = 2;
//input int    Input3 = 3;
datetime dt_Back_OOS=0,dt_Fwrd_OOS=0;
string   Strat="",Mode="",_Symbol_=_Symbol;
string   FileCSV_Name="",Date_Start="";
int      FileCSV_handle=INVALID_HANDLE,FileSET_handle=INVALID_HANDLE,FileTester_handle=INVALID_HANDLE;

int      days_BOOS=0,days_IS=0,days_FOOS=0;
datetime dt_BOOS_end=0,dt_IS_end=0;
double   eq_BOOS_start=0,eq_BOOS_end=0,eq_IS_start=0,eq_IS_end=0,eq_FOOS_start=0; // FOOS end is fetchable
int      trd_BOOS=0, trd_IS=0, trd_FOOS=0;
datetime DashboardBusDayStart=0,DashboardBusWeekStart=0;
double   DashboardBusClosedPLDaily=0.0,DashboardBusClosedPLWeekly=0.0,DashboardBusClosedPLTotal=0.0;
int      DashboardBusClosedTradesTotal=0;
double   DashboardBusNewsScore=0.0,DashboardBusBiasSentiment=0.0;
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GetFontName(ENUM_FONT FontNumber)
  {
      string FontTypes[]=
        {
         "Arial",
         "Arial Black",
         "Arial Bold",
         "Arial Bold Italic",
         "Arial Italic",
         "Comic Sans MS Bold",
         "Courier",
         "Courier New",
         "Courier New Bold",
         "Courier New Bold Italic",
         "Courier New Italic",
         "Estrangelo Edessa",
         "Franklin Gothic Medium",
         "Gautami",
         "Georgia",
         "Georgia Bold",
         "Georgia Bold Italic",
         "Georgia Italic",
         "Georgia Italic Impact",
         "Latha",
         "Lucida Console",
         "Lucida Sans Unicode",
         "Modern MS Sans Serif",
         "MS Sans Serif",
         "Mv Boli",
         "Palatino Linotype",
         "Palatino Linotype Bold",
         "Palatino Linotype Italic",
         "Roman",
         "Script",
         "Small Fonts",
         "Symbol",
         "Tahoma",
         "Tahoma Bold",
         "Times New Roman",
         "Times New Roman Bold",
         "Times New Roman Bold Italic",
         "Times New Roman Italic",
         "Trebuchet MS",
         "Trebuchet MS Bold",
         "Trebuchet MS Bold Italic",
         "Trebuchet MS Italic",
         "Tunga",
         "Verdana",
         "Verdana Bold",
         "Verdana Bold Italic",
         "Verdana Italic",
         "Webdings",
         "Westminster",
         "Wingdings",
         "WST_Czech",
         "WST_Engl",
         "WST_Fren",
         "WST_Germ",
         "WST_Ital",
         "WST_Span",
         "WST_Swed"
        };
      return(FontTypes[int(FontNumber)]);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GetRetcodeID(int retcode)
  {
   switch(retcode)
     {
      case   740: return("STOPOUT FLAG: Max DD/Profit OR Stop at DayEnd/WeekEnd");break;
      case   741: return("Max Allowed Margin Reached");        break;
      case 10004: return("TRADE_RETCODE_REQUOTE");             break;
      case 10006: return("TRADE_RETCODE_REJECT");              break;
      case 10007: return("TRADE_RETCODE_CANCEL");              break;
      case 10008: return("TRADE_RETCODE_PLACED");              break;
      case 10009: return("TRADE_RETCODE_DONE");                break;
      case 10010: return("TRADE_RETCODE_DONE_PARTIAL");        break;
      case 10011: return("TRADE_RETCODE_ERROR");               break;
      case 10012: return("TRADE_RETCODE_TIMEOUT");             break;
      case 10013: return("TRADE_RETCODE_INVALID");             break;
      case 10014: return("TRADE_RETCODE_INVALID_VOLUME");      break;
      case 10015: return("TRADE_RETCODE_INVALID_PRICE");       break;
      case 10016: return("TRADE_RETCODE_INVALID_STOPS");       break;
      case 10017: return("TRADE_RETCODE_TRADE_DISABLED");      break;
      case 10018: return("TRADE_RETCODE_MARKET_CLOSED");       break;
      case 10019: return("TRADE_RETCODE_NO_MONEY");            break;
      case 10020: return("TRADE_RETCODE_PRICE_CHANGED");       break;
      case 10021: return("TRADE_RETCODE_PRICE_OFF");           break;
      case 10022: return("TRADE_RETCODE_INVALID_EXPIRATION");  break;
      case 10023: return("TRADE_RETCODE_ORDER_CHANGED");       break;
      case 10024: return("TRADE_RETCODE_TOO_MANY_REQUESTS");   break;
      case 10025: return("TRADE_RETCODE_NO_CHANGES");          break;
      case 10026: return("TRADE_RETCODE_SERVER_DISABLES_AT");  break;
      case 10027: return("TRADE_RETCODE_CLIENT_DISABLES_AT");  break;
      case 10028: return("TRADE_RETCODE_LOCKED");              break;
      case 10029: return("TRADE_RETCODE_FROZEN");              break;
      case 10030: return("TRADE_RETCODE_INVALID_FILL");        break;
      case 10031: return("TRADE_RETCODE_CONNECTION");          break;
      case 10032: return("TRADE_RETCODE_ONLY_REAL");           break;
      case 10033: return("TRADE_RETCODE_LIMIT_ORDERS");        break;
      case 10034: return("TRADE_RETCODE_LIMIT_VOLUME");        break;
      case 10035: return("TRADE_RETCODE_INVALID_ORDER");       break;
      case 10036: return("TRADE_RETCODE_POSITION_CLOSED");     break;
      default:
         return("TRADE_RETCODE_UNKNOWN="+IntegerToString(retcode));
         break;
     }
//---
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string ConvertToGOATsymbol(string symbol)
  {
   // Normalize: uppercase + strip everything except A-Z / 0-9
   string s = symbol;
   StringToUpper(s);
   
   string key = "";
   int    len = StringLen(s);

   for(int i=0;i<len;i++)
     {
      int ch = StringGetCharacter(s,i);
      if((ch>='A' && ch<='Z') || (ch>='0' && ch<='9'))
       key += CharToString((uchar)ch);
     }
   // -------------------- METALS --------------------
   if(StringFind(key,"XAUUSD")>=0 || StringFind(key,"GOLD")>=0)
      return "XAUUSD";
   if(StringFind(key,"XAGUSD")>=0 || StringFind(key,"SILVER")>=0)
      return "XAGUSD";

   // -------------------- CRYPTO --------------------
   if(StringFind(key,"BTCUSDT")>=0 || StringFind(key,"BTCUSD")>=0 || StringFind(key,"XBTUSD")>=0)
      return "BTCUSD";
   if(StringFind(key,"ETHUSDT")>=0 || StringFind(key,"ETHUSD")>=0)
      return "ETHUSD";

   // -------------------- INDICES (with digit-boundary hardening) --------------------
   int p,nch;

   p = StringFind(key,"SPX500");  if(p>=0) { if(p+6>=StringLen(key)) return "US500"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "US500"; }
   p = StringFind(key,"USA500");  if(p>=0) { if(p+6>=StringLen(key)) return "US500"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "US500"; }
   p = StringFind(key,"SP500");   if(p>=0) { if(p+5>=StringLen(key)) return "US500"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "US500"; }
   p = StringFind(key,"US500");   if(p>=0) { if(p+5>=StringLen(key)) return "US500"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "US500"; }

   p = StringFind(key,"NASDAQ100"); if(p>=0) return "NAS100";
   p = StringFind(key,"NAS100");    if(p>=0) { if(p+6>=StringLen(key)) return "NAS100"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "NAS100"; }
   p = StringFind(key,"US100");     if(p>=0) { if(p+5>=StringLen(key)) return "NAS100"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "NAS100"; }
   if(StringFind(key,"USTEC")>=0)   return "NAS100";

   p = StringFind(key,"USA30");   if(p>=0) { if(p+5>=StringLen(key)) return "US30"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "US30"; }
   p = StringFind(key,"WS30");    if(p>=0) { if(p+4>=StringLen(key)) return "US30"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "US30"; }
   p = StringFind(key,"DJ30");    if(p>=0) { if(p+4>=StringLen(key)) return "US30"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "US30"; }
   p = StringFind(key,"DOW30");   if(p>=0) { if(p+5>=StringLen(key)) return "US30"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "US30"; }
   p = StringFind(key,"US30");    if(p>=0) { if(p+4>=StringLen(key)) return "US30"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "US30"; }
   if(StringFind(key,"DOWJONES")>=0 || StringFind(key,"WALLSTREET30")>=0) return "US30";

   p = StringFind(key,"GER40");   if(p>=0) { if(p+5>=StringLen(key)) return "GER40"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "GER40"; }
   p = StringFind(key,"DE40");    if(p>=0) { if(p+4>=StringLen(key)) return "GER40"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "GER40"; }
   p = StringFind(key,"DE30");    if(p>=0) { if(p+4>=StringLen(key)) return "GER40"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "GER40"; }
   p = StringFind(key,"DAX40");   if(p>=0) { if(p+5>=StringLen(key)) return "GER40"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "GER40"; }
   if(StringFind(key,"GDAXI")>=0 || StringFind(key,"DAX")>=0) return "GER40";

   p = StringFind(key,"EUSTX50"); if(p>=0) { if(p+6>=StringLen(key)) return "EU50"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "EU50"; }
   p = StringFind(key,"ESTX50");  if(p>=0) { if(p+5>=StringLen(key)) return "EU50"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "EU50"; }
   p = StringFind(key,"EURO50");  if(p>=0) { if(p+6>=StringLen(key)) return "EU50"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "EU50"; }
   p = StringFind(key,"EU50");    if(p>=0) { if(p+4>=StringLen(key)) return "EU50"; nch=StringGetCharacter(key,p+4); if(!(nch>='0' && nch<='9')) return "EU50"; }
   if(StringFind(key,"EUROSTOXX50")>=0 || StringFind(key,"STOXX50")>=0 || StringFind(key,"SX5E")>=0) return "EU50";

   p = StringFind(key,"JPN225");  if(p>=0) { if(p+6>=StringLen(key)) return "JP225"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "JP225"; }
   p = StringFind(key,"JP225");   if(p>=0) { if(p+5>=StringLen(key)) return "JP225"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "JP225"; }
   p = StringFind(key,"NIKKEI225"); if(p>=0) return "JP225";
   p = StringFind(key,"NK225");   if(p>=0) { if(p+5>=StringLen(key)) return "JP225"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "JP225"; }
   if(key=="N225" || StringFind(key,"NIKKEI")>=0) return "JP225";

   p = StringFind(key,"SPI200");  if(p>=0) { if(p+6>=StringLen(key)) return "AUS200"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "AUS200"; }
   p = StringFind(key,"AUS200");  if(p>=0) { if(p+6>=StringLen(key)) return "AUS200"; nch=StringGetCharacter(key,p+6); if(!(nch>='0' && nch<='9')) return "AUS200"; }
   p = StringFind(key,"ASX200");  if(p>=0) { if(p+5>=StringLen(key)) return "AUS200"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "AUS200"; }
   p = StringFind(key,"AU200");   if(p>=0) { if(p+5>=StringLen(key)) return "AUS200"; nch=StringGetCharacter(key,p+5); if(!(nch>='0' && nch<='9')) return "AUS200"; }

   // -------------------- FOREX (pairs) --------------------
   if(StringFind(key,"EURUSD")>=0) return "EURUSD";
   if(StringFind(key,"GBPUSD")>=0) return "GBPUSD";
   if(StringFind(key,"USDJPY")>=0) return "USDJPY";
   if(StringFind(key,"USDCAD")>=0) return "USDCAD";
   if(StringFind(key,"AUDUSD")>=0) return "AUDUSD";
   if(StringFind(key,"NZDUSD")>=0) return "NZDUSD";
   if(StringFind(key,"USDCHF")>=0) return "USDCHF";

   if(StringFind(key,"EURGBP")>=0) return "EURGBP";
   if(StringFind(key,"EURJPY")>=0) return "EURJPY";
   if(StringFind(key,"EURAUD")>=0) return "EURAUD";
   if(StringFind(key,"EURNZD")>=0) return "EURNZD";
   if(StringFind(key,"EURCAD")>=0) return "EURCAD";
   if(StringFind(key,"EURCHF")>=0) return "EURCHF";

   if(StringFind(key,"GBPJPY")>=0) return "GBPJPY";
   if(StringFind(key,"GBPAUD")>=0) return "GBPAUD";
   if(StringFind(key,"GBPNZD")>=0) return "GBPNZD";
   if(StringFind(key,"GBPCAD")>=0) return "GBPCAD";
   if(StringFind(key,"GBPCHF")>=0) return "GBPCHF";

   if(StringFind(key,"AUDJPY")>=0) return "AUDJPY";
   if(StringFind(key,"AUDCAD")>=0) return "AUDCAD";
   if(StringFind(key,"AUDNZD")>=0) return "AUDNZD";
   if(StringFind(key,"AUDCHF")>=0) return "AUDCHF";
   if(StringFind(key,"NZDJPY")>=0) return "NZDJPY";
   if(StringFind(key,"NZDCAD")>=0) return "NZDCAD";
   if(StringFind(key,"NZDCHF")>=0) return "NZDCHF";
   if(StringFind(key,"CADJPY")>=0) return "CADJPY";
   if(StringFind(key,"CADCHF")>=0) return "CADCHF";
   if(StringFind(key,"CHFJPY")>=0) return "CHFJPY";

   return symbol;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckSignalNow()
  {
   if(Signal_Sample_Period == Tick)       return true;
   if(Signal_Sample_Period == Second)     return CheckNewSecond();
 //if(Signal_Sample_Period == TenSecs)    return CheckNewTenSecs();
   if(Signal_Sample_Period == M1)         return CheckNewMinute();
 //if(Signal_Sample_Period == M5)         return CheckNewMinuteTime(M5);
 //if(Signal_Sample_Period == M10)        return CheckNewMinuteTime(M10);
 //if(Signal_Sample_Period == M15)        return CheckNewMinuteTime(M15);
   if(Signal_Sample_Period == M_Current)  return CheckNewBar(PERIOD_CURRENT);
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckSequenceNow()
  {
   if(Sequence_Sample_Period == Tick)       return true;
   if(Sequence_Sample_Period == Second)     return CheckNewSecond2();
   if(Sequence_Sample_Period == M1)         return CheckNewMinute2();
   if(Sequence_Sample_Period == M_Current)  return CheckNewBar2(PERIOD_CURRENT);
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckTrailingLockTPNow()
  {
   if(Trailing_Sample_Period == Tick)       return true;
   if(Trailing_Sample_Period == Second)     return CheckNewSecond3();
   if(Trailing_Sample_Period == M1)         return CheckNewMinute3();
   if(Trailing_Sample_Period == M_Current)  return CheckNewBar3(PERIOD_CURRENT);
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewSecond()
  {
   static int lastSecond;
   int curSecond = stm_cur.sec;
   if(lastSecond != curSecond)
   {
      lastSecond = curSecond;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewSecond2()
  {
   static int lastSecond;
   int curSecond = stm_cur.sec;
   if(lastSecond != curSecond)
   {
      lastSecond = curSecond;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewSecond3()
  {
   static int lastSecond;
   int curSecond = stm_cur.sec;
   if(lastSecond != curSecond)
   {
      lastSecond = curSecond;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewMinute()
  {
   static int lastMinute;
   int curMinute = stm_cur.min;
   if(lastMinute != curMinute)
   {
      lastMinute = curMinute;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewMinute2()
  {
   static int lastMinute;
   int curMinute = stm_cur.min;
   if(lastMinute != curMinute)
   {
      lastMinute = curMinute;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewMinute3()
  {
   static int lastMinute;
   int curMinute = stm_cur.min;
   if(lastMinute != curMinute)
   {
      lastMinute = curMinute;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewBar(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewBar2(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CheckNewBar3(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewBar(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewBar2(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewBar3(ENUM_TIMEFRAMES TF_Period)
  {
   static datetime lastbar;
   datetime curbar = (datetime)SeriesInfoInteger(_Symbol,TF_Period,SERIES_LASTBAR_DATE);
   if(lastbar != curbar)
   {
      lastbar = curbar;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewSecond()
  {
   static int lastSecond;
   int curSecond = stm_cur.sec;
   if(lastSecond != curSecond)
   {
      lastSecond = curSecond;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewMinute()
  {
   static int lastMinute;
   int curMinute = stm_cur.min;
   if(lastMinute != curMinute)
   {
      lastMinute = curMinute;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewMinute2()
  {
   static int lastMinute;
   int curMinute = stm_cur.min;
   if(lastMinute != curMinute)
   {
      lastMinute = curMinute;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewDay()
  {
   static int lastDay;
   int curDay = stm_cur.day;
   if(lastDay != curDay)
   {
      lastDay = curDay;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool IsNewDay2()
  {
   static int lastDay;
   int curDay = stm_cur.day;
   if(lastDay != curDay)
   {
      lastDay = curDay;
      return true;
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatChildGVName(const long magic,const string symbol,const string field)
  {
   return Key+"_ID_"+IntegerToString((int)magic)+"_"+symbol+"_"+field;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatSymbolGVName(const string symbol,const string field)
  {
   return Key+"_SYM_"+symbol+"_"+field;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatPortfolioGVName(const string field)
  {
   return Key+"_PORT_"+field;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatTerminalToken(void)
  {
   string path=TerminalInfoString(TERMINAL_DATA_PATH);
   for(int i=StringLen(path)-1;i>=0;--i)
   {
      if(path[i]=='\\' || path[i]=='/')
         return StringSubstr(path,i+1);
   }
   return path;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatDashboardStatePath(void)
  {
   return Key+"\\dashboard_state_"+GoatTerminalToken()+".tsv";
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
long GoatTruncateCidValue(const long cid)
  {
   string cid_text=StringFormat("%I64d",cid);
   while(StringLen(cid_text)>0)
   {
      long truncated=(long)StringToInteger(cid_text);
      if(truncated>0 && (double)truncated<=9007199254740991.0)
         return truncated;
      cid_text=StringSubstr(cid_text,1);
   }
   return 0;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool GoatParseChildGVName(const string gv_name,long &magic,string &symbol,string &field)
  {
   string prefix=Key+"_ID_";
   if(StringFind(gv_name,prefix,0)!=0) return false;

   string rest=StringSubstr(gv_name,StringLen(prefix));
   int first_sep=StringFind(rest,"_");
   if(first_sep<=0) return false;

   int last_sep=-1;
   for(int i=StringLen(rest)-1;i>=0;--i)
   {
      if(StringGetCharacter(rest,i)=='_')
      {
         last_sep=i;
         break;
      }
   }
   if(last_sep<=first_sep) return false;

   magic=(long)StringToInteger(StringSubstr(rest,0,first_sep));
   symbol=StringSubstr(rest,first_sep+1,last_sep-first_sep-1);
   field=StringSubstr(rest,last_sep+1);
   return(symbol!="" && field!="");
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool GoatFindMagicByCid(const string symbol,const long chart_id,long &magic_out)
  {
   magic_out=0;
   long target_cid=GoatTruncateCidValue(chart_id);
   if(target_cid<=0) return false;

   for(int i=GlobalVariablesTotal()-1;i>=0;--i)
   {
      string gv_name=GlobalVariableName(i);
      long gv_magic=0;
      string gv_symbol="",gv_field="";
      if(!GoatParseChildGVName(gv_name,gv_magic,gv_symbol,gv_field)) continue;
      if(gv_field!=GOAT_GV_FIELD_CID)                                continue;
      if(gv_symbol!=symbol)                                          continue;

      long gv_cid=GoatTruncateCidValue((long)GlobalVariableGet(gv_name));
      if(gv_cid!=target_cid) continue;

      magic_out=gv_magic;
      return(magic_out>0);
   }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
datetime GoatBrokerDayStart(const datetime when)
  {
   MqlDateTime tm;
   TimeToStruct(when,tm);
   tm.hour=0; tm.min=0; tm.sec=0;
   return StructToTime(tm);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
datetime GoatBrokerWeekStart(const datetime when)
  {
   datetime day_start=GoatBrokerDayStart(when);
   datetime cursor=day_start;
   for(int i=0;i<7;++i)
   {
      MqlDateTime tm;
      TimeToStruct(cursor,tm);
      if(tm.day_of_week==1) return cursor;
      cursor-=86400;
   }
   return day_start;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int GoatCountDashboardDataPoints(int &chart_count)
  {
   chart_count=0;
   long chart_ids[];
   ArrayResize(chart_ids,0);
   int total_points=0;
   string cid_suffix="_CID";

   for(int i=GlobalVariablesTotal()-1;i>=0;--i)
   {
      string gv_name=GlobalVariableName(i);
      bool is_child=(StringFind(gv_name,Key+"_ID_",0)==0);
      bool is_symbol=(StringFind(gv_name,Key+"_SYM_",0)==0);
      if(!is_child && !is_symbol) continue;

      total_points++;
      if(!is_child) continue;
      if(StringLen(gv_name)<StringLen(cid_suffix) || StringSubstr(gv_name,StringLen(gv_name)-StringLen(cid_suffix))!=cid_suffix) continue;

      long cid=GoatTruncateCidValue((long)GlobalVariableGet(gv_name));
      bool seen=false;
      for(int j=0;j<ArraySize(chart_ids);++j)
      {
         if(chart_ids[j]==cid) {seen=true; break;}
      }
      if(seen) continue;

      int n=ArraySize(chart_ids);
      ArrayResize(chart_ids,n+1);
      chart_ids[n]=cid;
   }

   chart_count=ArraySize(chart_ids);
   return total_points;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void GoatDeleteDashboardBusData(void)
  {
   for(int i=GlobalVariablesTotal()-1;i>=0;--i)
   {
      string gv_name=GlobalVariableName(i);
      if(StringFind(gv_name,Key+"_ID_",0)==0 || StringFind(gv_name,Key+"_SYM_",0)==0 || StringFind(gv_name,Key+"_PORT_",0)==0)
         GlobalVariableDel(gv_name);
   }
   GlobalVariableDel("Dashboard_ChartID");
   FileDelete(GoatDashboardStatePath(),FILE_COMMON);
   FileDelete(Key+"\\dashboard_child_map.tsv",FILE_COMMON);
   GlobalVariablesFlush();
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool ObjectSetText2(string name, string text, int font_size, string font_name=NULL, color text_color=CLR_NONE)
{
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   int tmpObjType=(int)ObjectGetInteger(0,name,OBJPROP_TYPE);
   if(tmpObjType!=OBJ_LABEL && tmpObjType!=OBJ_TEXT) return(false);
   if(StringLen(text)>0 && font_size>0)
     {
      if(ObjectSetString(0,name,OBJPROP_TEXT,text)==true
         && ObjectSetInteger(0,name,OBJPROP_FONTSIZE,font_size)==true)
        {
         if((StringLen(font_name)>0)
            && ObjectSetString(0,name,OBJPROP_FONT,font_name)==false)
            return(false);
         if(text_color!=CLR_NONE
            && ObjectSetInteger(0,name,OBJPROP_COLOR,text_color)==false)
            return(false);
         return(true);
        }
      return(false);
     }
   return(false);
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool ObjectExist(string n)
  {
   for(int i=ObjectsTotal(ChartID(),-1); i>=0; i--)
     {
      string name = ObjectName(0,i);
      if(name == n)
         return true;
     }
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void Sleep_(ulong delay_ms)
  {
   ulong start_time = GetTickCount();
   // Loop until the elapsed time reaches the desired delay.
   while(GetTickCount() - start_time < delay_ms) Sleep(1);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string TFToString(ENUM_TIMEFRAMES eTimeframe)
{
    string sTimeframe = EnumToString(eTimeframe);
    StringReplace(sTimeframe, "PERIOD_", ""); // Remove the prefix
    return sTimeframe;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------
int ChartWindowsHandle(const long chart_ID=0)
  {
//--- prepare the variable to get the property value
   long result=-1;
//--- reset the error value
   ResetLastError();
//--- receive the property value
   if(!ChartGetInteger(chart_ID,CHART_WINDOW_HANDLE,0,result))
     {
      //--- display the error message in Experts journal
      Print(__FUNCTION__+", Error Code = ",GetLastError());
     }
//--- return the value of the chart property
   return((int)result);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
/*void WriteSet2()
{
//FileWrite(FileSET_handle,"=",; saved on 2025.01.06 11:43:53
//FileWrite(FileSET_handle,"=",; this file contains input parameters for testing/optimizing V1.19 expert advisor
//FileWrite(FileSET_handle,"=",; to use it in the strategy tester, click Load in the context menu of the Inputs tab
//FileWrite(FileSET_handle,"=",;
FileWrite(FileSET_handle,"; ===========GENERAL SETTINGS============");
FileWrite(FileSET_handle,"EA_Desc=",EA_Desc);
FileWrite(FileSET_handle,"Font_Size=",Font_Size);
FileWrite(FileSET_handle,"Mode_Operation=",0);//Mode_Operation);
FileWrite(FileSET_handle,"; ===========SEQUENCE SETTINGS===========");
FileWrite(FileSET_handle,"Signal_Sample_Period=",Signal_Sample_Period);
FileWrite(FileSET_handle,"Sequence_Sample_Period=",Sequence_Sample_Period);
FileWrite(FileSET_handle,"Trailing_Sample_Period=",Trailing_Sample_Period);//=-1||0||0||99||N
FileWrite(FileSET_handle,"Allow_New_Sequence=",Allow_New_Sequence);//=true
FileWrite(FileSET_handle,"Reverse_Seq=",Reverse_Seq);//=false
FileWrite(FileSET_handle,"Mode_Trade=",Mode_Trade);//=0||0||0||2||N
FileWrite(FileSET_handle,"Grid_Size=",Grid_Size);//=-2||-1.0||-1.0||-15.0||Y
FileWrite(FileSET_handle,"Grid_Min=",Grid_Min);//=-4||-1.0||-1.0||-4.0||Y
FileWrite(FileSET_handle,"Grid_Max=",Grid_Max);//=-15||-10.0||-5.0||-25.0||Y
FileWrite(FileSET_handle,"Grid_Exponent=",Grid_Exponent);//=0.9||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Lock_Profit_Size=",Lock_Profit_Size);//=-13||-10.0||-3.0||-28.0||Y
FileWrite(FileSET_handle,"Lock_Profit_Flexibility=",Lock_Profit_Flexibility);//=0.2||-1.0||0.4||1.0||Y
FileWrite(FileSET_handle,"TP_Pips=",TP_Pips);//=2.00||1.25||0.25||2.0||Y
FileWrite(FileSET_handle,"SL_Pips=",SL_Pips);//=0||150.0||15.000000||1500.000000||N
FileWrite(FileSET_handle,"TSL_Size=",TSL_Size);//=-12||-2.0||-2.0||-12.0||Y
FileWrite(FileSET_handle,"Mode_Trail=",Mode_Trail);//=0||0||0||1||Y
FileWrite(FileSET_handle,"Delay_Trade=",Delay_Trade);//=0||0||1||3||Y
FileWrite(FileSET_handle,"Delay_Trade_Live=",Delay_Trade_Live);//=2||0||1||3||Y
FileWrite(FileSET_handle,"Max_Seq_Levels=",Max_Seq_Levels);//=10||7||3||13||Y
FileWrite(FileSET_handle,"Max_Seq_Trades=",Max_Seq_Trades);//=8||2||1||9||Y
FileWrite(FileSET_handle,"CloseAtMaxLevels=",CloseAtMaxLevels);//=true||false||0||true||N
FileWrite(FileSET_handle,"; =============ATR SETTINGS==============");
FileWrite(FileSET_handle,"ATR_TF_=",ATR_TF_);//=1||1||0||5||Y
FileWrite(FileSET_handle,"ATR_Period=",ATR_Period);//=800||100||100||900||Y
FileWrite(FileSET_handle,"ATR_Method=",ATR_Method);//=1||1||0||2||Y
FileWrite(FileSET_handle,"; ============POSITION SIZING============");
FileWrite(FileSET_handle,"Mode_Lots=",Mode_Lots);//=0
//FileWrite(FileSET_handle,"Risk=",Risk);//=1
FileWrite(FileSET_handle,"Lots_Input=",Lots_Input);//=0.1||0.1||0.010000||1.000000||N
FileWrite(FileSET_handle,"Lots_Exponent=",Lots_Exponent);//=1.4||0.8||0.1||1.5||Y
FileWrite(FileSET_handle,"Lots_Max=",Lots_Max);//=0.2||0.2||0.1||0.9||Y
FileWrite(FileSET_handle,"; ============MONEY MANAGEMENT===========");
FileWrite(FileSET_handle,"MaxLossLocal=",MaxLossLocal);//=0
FileWrite(FileSET_handle,"MaxLossGlobal=",MaxLossGlobal);//=0
FileWrite(FileSET_handle,"MaxDailyLossLocal=",MaxDailyLossLocal);//=0
FileWrite(FileSET_handle,"MaxDailyProfitLocal=",MaxDailyProfitLocal);//=0
FileWrite(FileSET_handle,"MinLevelEquity=",MinLevelEquity);//=0
FileWrite(FileSET_handle,"MaxLevelEquity=",MaxLevelEquity);//=0
FileWrite(FileSET_handle,"Mode_Restart=",Mode_Restart);//=25
FileWrite(FileSET_handle,"; =============RSI SETTINGS==============");
FileWrite(FileSET_handle,"RSI_Mode=",RSI_Mode);//=1||0||0||2||N
FileWrite(FileSET_handle,"RSI_TF_=",RSI_TF_);//=15||1||0||15||Y
FileWrite(FileSET_handle,"RSI_Period=",RSI_Period);//=7||3||2||9||Y
FileWrite(FileSET_handle,"RSI_Price=",RSI_Price);//=6||5||0||6||N
FileWrite(FileSET_handle,"RSI_Level=",RSI_Level);//=80||80.0||3.0||92.0||Y
FileWrite(FileSET_handle,"; ========MOVING AVERAGE SETTINGS========");
FileWrite(FileSET_handle,"EMA_Mode=",EMA_Mode);//=5||1||0||5||Y
FileWrite(FileSET_handle,"EMA_TF_=",EMA_TF_);//=5||5||0||60||Y
FileWrite(FileSET_handle,"EMA_Method=",EMA_Method);//=1||1||0||3||Y
FileWrite(FileSET_handle,"EMA_Price=",EMA_Price);//=6||5||0||7||N
FileWrite(FileSET_handle,"EMA_Count=",EMA_Count);//=4||5||1||50||N
FileWrite(FileSET_handle,"EMA_Period=",EMA_Period);//=4||7||1||70||N
FileWrite(FileSET_handle,"EMA_Exponent=",EMA_Exponent);//=2||1.5||0.150000||15.000000||N
FileWrite(FileSET_handle,"EMA_MustCheck=",EMA_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============ADX SETTINGS==============");
FileWrite(FileSET_handle,"ADX_Mode=",ADX_Mode);//=4||1||0||5||Y
FileWrite(FileSET_handle,"ADX_TF_=",ADX_TF_);//=15||5||0||60||Y
FileWrite(FileSET_handle,"ADX_Period=",ADX_Period);//=16||8||4||24||Y
FileWrite(FileSET_handle,"ADX_Level=",ADX_Level);//=27||18.0||3.0||33.0||Y
FileWrite(FileSET_handle,"ADX_MustCheck=",ADX_MustCheck);//=true||false||0||true||Y
FileWrite(FileSET_handle,"; =======BOLLINGER BANDS SETTINGS========");
FileWrite(FileSET_handle,"BB_Mode=",BB_Mode);//=1||1||0||3||Y
FileWrite(FileSET_handle,"BB_TF_=",BB_TF_);//=15||15||0||240||Y
FileWrite(FileSET_handle,"BB_Period=",BB_Period);//=10||10||10||50||Y
FileWrite(FileSET_handle,"BB_Deviation=",BB_Deviation);//=1.5||0.5||0.5||2.5||Y
FileWrite(FileSET_handle,"BB_Price=",BB_Price);//=1||1||0||7||N
FileWrite(FileSET_handle,"BB_MustCheck=",BB_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============MACD SETTINGS=============");
FileWrite(FileSET_handle,"MACD_Mode=",MACD_Mode);//=3||1||0||5||Y
FileWrite(FileSET_handle,"MACD_Mode_Trend=",MACD_Mode_Trend);//=3||0||0||3||Y
FileWrite(FileSET_handle,"MACD_TF_=",MACD_TF_);//=15||5||0||60||Y
FileWrite(FileSET_handle,"MACD_Fast=",MACD_Fast);//=13||5||2||13||Y
FileWrite(FileSET_handle,"MACD_Slow=",MACD_Slow);//=24||15||3||27||Y
FileWrite(FileSET_handle,"MACD_Signal=",MACD_Signal);//=11||5||2||11||Y
FileWrite(FileSET_handle,"MACD_Deviations=",MACD_Deviations);//=2.0||2.0||0.5||3.0||Y
FileWrite(FileSET_handle,"MACD_Price=",MACD_Price);//=6||6||0||7||Y
FileWrite(FileSET_handle,"MACD_MustCheck=",MACD_MustCheck);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; =============RSI2 SETTINGS==============");
FileWrite(FileSET_handle,"RSI2_Mode=",RSI2_Mode);//=0||0||0||3||N
FileWrite(FileSET_handle,"RSI2_TF_=",RSI2_TF_);//=15||0||0||240||N
FileWrite(FileSET_handle,"RSI2_Period=",RSI2_Period);//=13||13||1||130||N
FileWrite(FileSET_handle,"RSI2_Price=",RSI2_Price);//=1||1||0||7||N
FileWrite(FileSET_handle,"RSI2_Level=",RSI2_Level);//=70.0||90.0||9.000000||900.000000||N
FileWrite(FileSET_handle,"RSI2_MustCheck=",RSI2_MustCheck);//=false||false||0||true||N
FileWrite(FileSET_handle,"; ===========TRADING SCHEDULE============");
FileWrite(FileSET_handle,"Active_Time_Monday=",Active_Time_Monday);//=02:00-22:30
FileWrite(FileSET_handle,"Active_Time_Tuesday=",Active_Time_Tuesday);//=01:30-22:30
FileWrite(FileSET_handle,"Active_Time_Wednesday=",Active_Time_Wednesday);//=01:30-22:30
FileWrite(FileSET_handle,"Active_Time_Thursday=",Active_Time_Thursday);//=01:30-22:30
FileWrite(FileSET_handle,"Active_Time_Friday=",Active_Time_Friday);//=01:30-22:00
FileWrite(FileSET_handle,"Action_Dayend=",Action_Dayend);//=1||0||0||1||Y
FileWrite(FileSET_handle,"Action_Friday=",Action_Friday);//=2||0||0||2||Y
FileWrite(FileSET_handle,"Trade_Friday=",Trade_Friday);//=false||false||0||true||Y
FileWrite(FileSET_handle,"; ==============NEWS FILTER==============");
FileWrite(FileSET_handle,"input_ActionOnNews=",input_ActionOnNews);//=1||1||0||4||Y
FileWrite(FileSET_handle,"input_NewsImportanceLevel=",input_NewsImportanceLevel);//=3||3||1||30||N
FileWrite(FileSET_handle,"input_PauseTradesBeforeNewsMinutes=",input_PauseTradesBeforeNewsMinutes);//=100||120||1||1200||N
FileWrite(FileSET_handle,"input_PauseTradesAfterNewsMinutes=",input_PauseTradesAfterNewsMinutes);//=100||100||100||200||Y
FileWrite(FileSET_handle,"input_NewsExcludeKeywords1=",input_NewsExcludeKeywords1);//=crude,zew,ifo,lagarde
FileWrite(FileSET_handle,"; ==========NEWS DATA DOWNLOADER=========");
FileWrite(FileSET_handle,"input_DownloadNews=",input_DownloadNews);//=false
FileWrite(FileSET_handle,"input_NewsFileName=",input_NewsFileName);
FileWrite(FileSET_handle,"input_StartDate=",input_StartDate);//=1672531200
FileWrite(FileSET_handle,"input_NewsCurrencies=",input_NewsCurrencies);//=EUR,USD,GBP,JPY,CHF,AUD,CAD,NZD
FileWrite(FileSET_handle,"; ========OPTIMIZATION PARAMETERS========");
FileWrite(FileSET_handle,"Mode_Opti=",Mode_Opti);//=5
FileWrite(FileSET_handle,"Seq_min_inp=",Seq_min_inp);//=100
FileWrite(FileSET_handle,"Trades_min_inp=",Trades_min_inp);//=250
FileWrite(FileSET_handle,"Trades_Max=",Trades_Max);//=1500
FileWrite(FileSET_handle,"Minutes_Max=",Minutes_Max);//=1000
FileWrite(FileSET_handle,"Trade_December=",Trade_December);//=false
}*/
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool HLineCreate(const long            chart_ID=0,        // chart's ID
                 const string          name="HLine",      // line name
                 const int             sub_window=0,      // subwindow index
                 double                price=0,           // line price
                 const color           clr=clrRed,        // line color
                 const ENUM_LINE_STYLE style=STYLE_SOLID, // line style
                 const int             width=1,           // line width
                 const bool            back=false,        // in the background
                 const bool            selection=true,    // highlight to move
                 const bool            hidden=true,       // hidden in the object list
                 const long            z_order=0)         // priority for mouse click
  {
//--- Extra Addition
   if(FastSpeed_Flag) return false;
   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) HLineDelete(0,name);
//--- if the price is not set, set it at the current Bid price level
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- reset the error value
   ResetLastError();
//--- create a horizontal line
   if(!ObjectCreate(chart_ID,name,OBJ_HLINE,sub_window,0,price))
     {
      Print(__FUNCTION__,
            ": failed to create a horizontal line! Error code = ",GetLastError());
      return(false);
     }
//--- set line color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set line display style
   ObjectSetInteger(chart_ID,name,OBJPROP_STYLE,style);
//--- set line width
   ObjectSetInteger(chart_ID,name,OBJPROP_WIDTH,width);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the line by mouse
//--- when creating a graphical object using ObjectCreate function, the object cannot be
//--- highlighted and moved by default. Inside this method, selection parameter
//--- is true by default making it possible to highlight and move the object
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool HLineMove(const long   chart_ID=0,   // chart's ID
               const string name="HLine", // line name
               double       price=0)      // line price
  {
//--- if the line price is not set, move it to the current Bid price level
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- reset the error value
   ResetLastError();
//--- move a horizontal line
   if(!ObjectMove(chart_ID,name,0,0,price))
     {
      Print(__FUNCTION__,
            ": failed to move the horizontal line! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool HLineDelete(const long   chart_ID=0,   // chart's ID
                 const string name="HLine") // line name
  {
//--- reset the error value
   ResetLastError();
//--- delete a horizontal line
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete a horizontal line! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool VLineCreate(const long            chart_ID=0,        // chart's ID
                 const string          name="VLine",      // line name
                 const int             sub_window=0,      // subwindow index
                 datetime              time=0,            // line time
                 const color           clr=clrRed,        // line color
                 const ENUM_LINE_STYLE style=STYLE_SOLID, // line style
                 const int             width=1,           // line width
                 const bool            back=false,        // in the background
                 const bool            selection=true,    // highlight to move
                 const bool            hidden=true,       // hidden in the object list
                 const long            z_order=0)         // priority for mouse click
  {
//--- Extra Addition
   if(FastSpeed_Flag) return false;
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) VLineDelete(0,name);
//--- if the line time is not set, draw it via the last bar
   if(!time)
      time=TimeCurrent();
//--- reset the error value
   ResetLastError();
//--- create a vertical line
   if(!ObjectCreate(chart_ID,name,OBJ_VLINE,sub_window,time,0))
     {
      Print(__FUNCTION__,
            ": failed to create a vertical line! Error code = ",GetLastError());
      return(false);
     }
//--- set line color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set line display style
   ObjectSetInteger(chart_ID,name,OBJPROP_STYLE,style);
//--- set line width
   ObjectSetInteger(chart_ID,name,OBJPROP_WIDTH,width);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the line by mouse
//--- when creating a graphical object using ObjectCreate function, the object cannot be
//--- highlighted and moved by default. Inside this method, selection parameter
//--- is true by default making it possible to highlight and move the object
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool VLineMove(const long   chart_ID=0,   // chart's ID
               const string name="VLine", // line name
               datetime     time=0)       // line time
  {
//--- if line time is not set, move the line to the last bar
   if(!time)
      time=TimeCurrent();
//--- reset the error value
   ResetLastError();
//--- move the vertical line
   if(!ObjectMove(chart_ID,name,0,time,0))
     {
      Print(__FUNCTION__,
            ": failed to move the vertical line! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool VLineDelete(const long   chart_ID=0,   // chart's ID
                 const string name="VLine") // line name
  {
//--- reset the error value
   ResetLastError();
//--- delete the vertical line
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete the vertical line! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool ArrowCreate(const long              chart_ID=0,           // chart's ID
                 const string            name="Arrow",         // arrow name
                 const int               sub_window=0,         // subwindow index
                 datetime                time=0,               // anchor point time
                 double                  price=0,              // anchor point price
                 const uchar             arrow_code=252,       // arrow code
                 const ENUM_ARROW_ANCHOR anchor=ANCHOR_BOTTOM, // anchor point position
                 const color             clr=clrRed,           // arrow color
                 const ENUM_LINE_STYLE   style=STYLE_SOLID,    // border line style
                 const int               width=3,              // arrow size
                 const bool              back=false,           // in the background
                 const bool              selection=true,       // highlight to move
                 const bool              hidden=true,          // hidden in the object list
                 const long              z_order=0)            // priority for mouse click
  {
//--- Extra Addition
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) ArrowDelete(0,name);
//--- set anchor point coordinates if they are not set
   ChangeArrowEmptyPoint(time,price);
//--- reset the error value
   ResetLastError();
//--- create an arrow
   if(!ObjectCreate(chart_ID,name,OBJ_ARROW,sub_window,time,price))
     {
      Print(__FUNCTION__,
            ": failed to create an arrow! Error code = ",GetLastError());
      return(false);
     }
//--- set the arrow code
   ObjectSetInteger(chart_ID,name,OBJPROP_ARROWCODE,arrow_code);
//--- set anchor type
   ObjectSetInteger(chart_ID,name,OBJPROP_ANCHOR,anchor);
//--- set the arrow color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set the border line style
   ObjectSetInteger(chart_ID,name,OBJPROP_STYLE,style);
//--- set the arrow's size
   ObjectSetInteger(chart_ID,name,OBJPROP_WIDTH,width);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the arrow by mouse
//--- when creating a graphical object using ObjectCreate function, the object cannot be
//--- highlighted and moved by default. Inside this method, selection parameter
//--- is true by default making it possible to highlight and move the object
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ArrowMove(const long   chart_ID=0,   // chart's ID
               const string name="Arrow", // object name
               datetime     time=0,       // anchor point time coordinate
               double       price=0)      // anchor point price coordinate
  {
//--- if point position is not set, move it to the current bar having Bid price
   if(!time)
      time=TimeCurrent();
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- reset the error value
   ResetLastError();
//--- move the anchor point
   if(!ObjectMove(chart_ID,name,0,time,price))
     {
      Print(__FUNCTION__,
            ": failed to move the anchor point! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ArrowCodeChange(const long   chart_ID=0,   // chart's ID
                     const string name="Arrow", // object name
                     const uchar  code=252)     // arrow code
  {
//--- reset the error value
   ResetLastError();
//--- change the arrow code
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_ARROWCODE,code))
     {
      Print(__FUNCTION__,
            ": failed to change the arrow code! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ArrowAnchorChange(const long              chart_ID=0,        // chart's ID
                       const string            name="Arrow",      // object name
                       const ENUM_ARROW_ANCHOR anchor=ANCHOR_TOP) // anchor type
  {
//--- reset the error value
   ResetLastError();
//--- change anchor type
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_ANCHOR,anchor))
     {
      Print(__FUNCTION__,
            ": failed to change anchor type! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ArrowDelete(const long   chart_ID=0,   // chart's ID
                 const string name="Arrow") // arrow name
  {
//--- reset the error value
   ResetLastError();
//--- delete an arrow
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete an arrow! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
void ChangeArrowEmptyPoint(datetime &time,double &price)
  {
//--- if the point's time is not set, it will be on the current bar
   if(!time)
      time=TimeCurrent();
//--- if the point's price is not set, it will have Bid value
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool ButtonCreate(const long              chart_ID=0,               // chart's ID
                  const string            name="Button",            // button name
                  const int               sub_window=0,             // subwindow index
                  const int               x=0,                      // X coordinate
                  const int               y=0,                      // Y coordinate
                  const int               width=50,                 // button width
                  const int               height=18,                // button height
                  const ENUM_BASE_CORNER  corner=CORNER_LEFT_UPPER, // chart corner for anchoring
                  const string            text="Button",            // text
                  const string            font="Arial",             // font
                  const int               font_size=10,             // font size
                  const color             clr=clrBlack,             // text color
                  const color             back_clr=C'236,233,216',  // background color
                  const color             border_clr=clrNONE,       // border color
                  const bool              state=false,              // pressed/released
                  const bool              back=false,               // in the background
                  const bool              selection=false,          // highlight to move
                  const bool              hidden=true,              // hidden in the object list
                  const long              z_order=0)                // priority for mouse click
  {
//--- reset the error value
   ResetLastError();
//--- create the button
   if(!ObjectCreate(chart_ID,name,OBJ_BUTTON,sub_window,0,0))
     {
      Print(__FUNCTION__,
            ": failed to create the button! Error code = ",GetLastError());
      return(false);
     }
//--- set button coordinates
   ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y);
//--- set button size
   ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width);
   ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height);
//--- set the chart's corner, relative to which point coordinates are defined
   ObjectSetInteger(chart_ID,name,OBJPROP_CORNER,corner);
//--- set the text
   ObjectSetString(chart_ID,name,OBJPROP_TEXT,text);
//--- set text font
   ObjectSetString(chart_ID,name,OBJPROP_FONT,font);
//--- set font size
   ObjectSetInteger(chart_ID,name,OBJPROP_FONTSIZE,font_size);
//--- set text color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set background color
   ObjectSetInteger(chart_ID,name,OBJPROP_BGCOLOR,back_clr);
//--- set border color
   ObjectSetInteger(chart_ID,name,OBJPROP_BORDER_COLOR,border_clr);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- set button state
   ObjectSetInteger(chart_ID,name,OBJPROP_STATE,state);
//--- enable (true) or disable (false) the mode of moving the button by mouse
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ButtonMove(const long   chart_ID=0,    // chart's ID
                const string name="Button", // button name
                const int    x=0,           // X coordinate
                const int    y=0)           // Y coordinate
  {
//--- reset the error value
   ResetLastError();
//--- move the button
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x))
     {
      Print(__FUNCTION__,
            ": failed to move X coordinate of the button! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y))
     {
      Print(__FUNCTION__,
            ": failed to move Y coordinate of the button! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ButtonChangeSize(const long   chart_ID=0,    // chart's ID
                      const string name="Button", // button name
                      const int    width=50,      // button width
                      const int    height=18)     // button height
  {
//--- reset the error value
   ResetLastError();
//--- change the button size
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width))
     {
      Print(__FUNCTION__,
            ": failed to change the button width! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height))
     {
      Print(__FUNCTION__,
            ": failed to change the button height! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ButtonChangeCorner(const long             chart_ID=0,               // chart's ID
                        const string           name="Button",            // button name
                        const ENUM_BASE_CORNER corner=CORNER_LEFT_UPPER) // chart corner for anchoring
  {
//--- reset the error value
   ResetLastError();
//--- change anchor corner
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_CORNER,corner))
     {
      Print(__FUNCTION__,
            ": failed to change the anchor corner! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ButtonTextChange(const long   chart_ID=0,    // chart's ID
                      const string name="Button", // button name
                      const string text="Text")   // text
  {
//--- reset the error value
   ResetLastError();
//--- change object text
   if(!ObjectSetString(chart_ID,name,OBJPROP_TEXT,text))
     {
      Print(__FUNCTION__,
            ": failed to change the text! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool ButtonDelete(const long   chart_ID=0,    // chart's ID
                  const string name="Button") // button name
  {
//--- reset the error value
   ResetLastError();
//--- delete the button
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete the button! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool TrendCreate(const long            chart_ID=0,        // chart's ID
                 const string          name="TrendLine",  // line name
                 const int             sub_window=0,      // subwindow index
                 datetime              time1=0,           // first point time
                 double                price1=0,          // first point price
                 datetime              time2=0,           // second point time
                 double                price2=0,          // second point price
                 const color           clr=clrRed,        // line color
                 const ENUM_LINE_STYLE style=STYLE_SOLID, // line style
                 const int             width=1,           // line width
                 const bool            back=false,        // in the background
                 const bool            selection=true,    // highlight to move
                 const bool            ray_right=false,   // line's continuation to the right
                 const bool            hidden=true,       // hidden in the object list
                 const long            z_order=0)         // priority for mouse click
  {
//--- Extra Addition
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) TrendDelete(0,name);
//--- set anchor points' coordinates if they are not set
   ChangeTrendEmptyPoints(time1,price1,time2,price2);
//--- reset the error value
   ResetLastError();
//--- create a trend line by the given coordinates
   if(!ObjectCreate(chart_ID,name,OBJ_TREND,sub_window,time1,price1,time2,price2))
     {
      Print(__FUNCTION__,
            ": failed to create a trend line! Error code = ",GetLastError());
      return(false);
     }
//--- set line color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set line display style
   ObjectSetInteger(chart_ID,name,OBJPROP_STYLE,style);
//--- set line width
   ObjectSetInteger(chart_ID,name,OBJPROP_WIDTH,width);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the line by mouse
//--- when creating a graphical object using ObjectCreate function, the object cannot be
//--- highlighted and moved by default. Inside this method, selection parameter
//--- is true by default making it possible to highlight and move the object
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- enable (true) or disable (false) the mode of continuation of the line's display to the right
   ObjectSetInteger(chart_ID,name,OBJPROP_RAY_RIGHT,ray_right);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Move trend line anchor point                                     |
//+------------------------------------------------------------------+
bool TrendPointChange(const long   chart_ID=0,       // chart's ID
                      const string name="TrendLine", // line name
                      const int    point_index=0,    // anchor point index
                      datetime     time=0,           // anchor point time coordinate
                      double       price=0)          // anchor point price coordinate
  {
//--- if point position is not set, move it to the current bar having Bid price
   if(!time)
      time=TimeCurrent();
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- reset the error value
   ResetLastError();
//--- move trend line's anchor point
   if(!ObjectMove(chart_ID,name,point_index,time,price))
     {
      Print(__FUNCTION__,
            ": failed to move the anchor point! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| The function deletes the trend line from the chart.              |
//+------------------------------------------------------------------+
bool TrendDelete(const long   chart_ID=0,       // chart's ID
                 const string name="TrendLine") // line name
  {
//--- reset the error value
   ResetLastError();
//--- delete a trend line
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete a trend line! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Check the values of trend line's anchor points and set default   |
//| values for empty ones                                            |
//+------------------------------------------------------------------+
void ChangeTrendEmptyPoints(datetime &time1,double &price1,
                            datetime &time2,double &price2)
  {
//--- if the first point's time is not set, it will be on the current bar
   if(!time1)
      time1=TimeCurrent();
//--- if the first point's price is not set, it will have Bid value
   if(!price1)
      price1=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- if the second point's time is not set, it is located 9 bars left from the second one
   if(!time2)
     {
      //--- array for receiving the open time of the last 10 bars
      datetime temp[10];
      CopyTime(Symbol(),Period(),time1,10,temp);
      //--- set the second point 9 bars left from the first one
      time2=temp[0];
     }
//--- if the second point's price is not set, it is equal to the first point's one
   if(!price2)
      price2=price1;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool RectLabelCreate(const long             chart_ID=0,               // chart's ID
                     const string           name="RectLabel",         // label name
                     const int              sub_window=0,             // subwindow index
                     const int              x=0,                      // X coordinate
                     const int              y=0,                      // Y coordinate
                     const int              width=50,                 // width
                     const int              height=18,                // height
                     const color            back_clr=C'236,233,216',  // background color
                     const ENUM_BORDER_TYPE border=BORDER_SUNKEN,     // border type
                     const ENUM_BASE_CORNER corner=CORNER_LEFT_UPPER, // chart corner for anchoring
                     const color            clr=clrRed,               // flat border color (Flat)
                     const ENUM_LINE_STYLE  style=STYLE_SOLID,        // flat border style
                     const int              line_width=1,             // flat border width
                     const bool             back=false,               // in the background
                     const bool             selection=false,          // highlight to move
                     const bool             hidden=true,              // hidden in the object list
                     const long             z_order=0)                // priority for mouse click
  {
//--- Extra Addition
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) RectLabelDelete(0,name);
//--- reset the error value
   ResetLastError();
//--- create a rectangle label
   if(!ObjectCreate(chart_ID,name,OBJ_RECTANGLE_LABEL,sub_window,0,0))
     {
      Print(__FUNCTION__,
            ": failed to create a rectangle label! Error code = ",GetLastError());
      return(false);
     }
//--- set label coordinates
   ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y);
//--- set label size
   ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width);
   ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height);
//--- set background color
   ObjectSetInteger(chart_ID,name,OBJPROP_BGCOLOR,back_clr);
//--- set border type
   ObjectSetInteger(chart_ID,name,OBJPROP_BORDER_TYPE,border);
//--- set the chart's corner, relative to which point coordinates are defined
   ObjectSetInteger(chart_ID,name,OBJPROP_CORNER,corner);
//--- set flat border color (in Flat mode)
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set flat border line style
   ObjectSetInteger(chart_ID,name,OBJPROP_STYLE,style);
//--- set flat border width
   ObjectSetInteger(chart_ID,name,OBJPROP_WIDTH,line_width);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the label by mouse
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool RectLabelMove(const long   chart_ID=0,       // chart's ID
                   const string name="RectLabel", // label name
                   const int    x=0,              // X coordinate
                   const int    y=0)              // Y coordinate
  {
//--- reset the error value
   ResetLastError();
//--- move the rectangle label
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x))
     {
      Print(__FUNCTION__,
            ": failed to move X coordinate of the label! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y))
     {
      Print(__FUNCTION__,
            ": failed to move Y coordinate of the label! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool RectLabelChangeSize(const long   chart_ID=0,       // chart's ID
                         const string name="RectLabel", // label name
                         const int    width=50,         // label width
                         const int    height=18)        // label height
  {
//--- reset the error value
   ResetLastError();
//--- change label size
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width))
     {
      Print(__FUNCTION__,
            ": failed to change the label's width! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height))
     {
      Print(__FUNCTION__,
            ": failed to change the label's height! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool RectLabelChangeBorderType(const long             chart_ID=0,           // chart's ID
                               const string           name="RectLabel",     // label name
                               const ENUM_BORDER_TYPE border=BORDER_SUNKEN) // border type
  {
//--- reset the error value
   ResetLastError();
//--- change border type
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_BORDER_TYPE,border))
     {
      Print(__FUNCTION__,
            ": failed to change the border type! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
bool RectLabelDelete(const long   chart_ID=0,       // chart's ID
                     const string name="RectLabel") // label name
  {
//--- reset the error value
   ResetLastError();
//--- delete the label
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete a rectangle label! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool EditCreate(const long             chart_ID=0,               // chart's ID
                const string           name="Edit",              // object name
                const int              sub_window=0,             // subwindow index
                const int              x=0,                      // X coordinate
                const int              y=0,                      // Y coordinate
                const int              width=50,                 // width
                const int              height=18,                // height
                const string           text="Text",              // text
                const string           font="Arial",             // font
                const int              font_size=10,             // font size
                const ENUM_ALIGN_MODE  align=ALIGN_CENTER,       // alignment type
                const bool             read_only=false,          // ability to edit
                const ENUM_BASE_CORNER corner=CORNER_LEFT_UPPER, // chart corner for anchoring
                const color            clr=clrBlack,             // text color
                const color            back_clr=clrWhite,        // background color
                const color            border_clr=clrNONE,       // border color
                const bool             back=false,               // in the background
                const bool             selection=false,          // highlight to move
                const bool             hidden=true,              // hidden in the object list
                const long             z_order=0)                // priority for mouse click
  {
//--- reset the error value
   ResetLastError();
//--- create edit field
   if(!ObjectCreate(chart_ID,name,OBJ_EDIT,sub_window,0,0))
     {
      Print(__FUNCTION__,
            ": failed to create \"Edit\" object! Error code = ",GetLastError());
      return(false);
     }
//--- set object coordinates
   ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y);
//--- set object size
   ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width);
   ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height);
//--- set the text
   ObjectSetString(chart_ID,name,OBJPROP_TEXT,text);
//--- set text font
   ObjectSetString(chart_ID,name,OBJPROP_FONT,font);
//--- set font size
   ObjectSetInteger(chart_ID,name,OBJPROP_FONTSIZE,font_size);
//--- set the type of text alignment in the object
   ObjectSetInteger(chart_ID,name,OBJPROP_ALIGN,align);
//--- enable (true) or cancel (false) read-only mode
   ObjectSetInteger(chart_ID,name,OBJPROP_READONLY,read_only);
//--- set the chart's corner, relative to which object coordinates are defined
   ObjectSetInteger(chart_ID,name,OBJPROP_CORNER,corner);
//--- set text color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- set background color
   ObjectSetInteger(chart_ID,name,OBJPROP_BGCOLOR,back_clr);
//--- set border color
   ObjectSetInteger(chart_ID,name,OBJPROP_BORDER_COLOR,border_clr);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the label by mouse
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Move Edit object                                                 |
//+------------------------------------------------------------------+
bool EditMove(const long   chart_ID=0,  // chart's ID
              const string name="Edit", // object name
              const int    x=0,         // X coordinate
              const int    y=0)         // Y coordinate
  {
//--- reset the error value
   ResetLastError();
//--- move the object
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XDISTANCE,x))
     {
      Print(__FUNCTION__,
            ": failed to move X coordinate of the object! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YDISTANCE,y))
     {
      Print(__FUNCTION__,
            ": failed to move Y coordinate of the object! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Resize Edit object                                               |
//+------------------------------------------------------------------+
bool EditChangeSize(const long   chart_ID=0,  // chart's ID
                    const string name="Edit", // object name
                    const int    width=0,     // width
                    const int    height=0)    // height
  {
//--- reset the error value
   ResetLastError();
//--- change the object size
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_XSIZE,width))
     {
      Print(__FUNCTION__,
            ": failed to change the object width! Error code = ",GetLastError());
      return(false);
     }
   if(!ObjectSetInteger(chart_ID,name,OBJPROP_YSIZE,height))
     {
      Print(__FUNCTION__,
            ": failed to change the object height! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Change Edit object's text                                        |
//+------------------------------------------------------------------+
bool EditTextChange(const long   chart_ID=0,  // chart's ID
                    const string name="Edit", // object name
                    const string text="Text") // text
  {
//--- reset the error value
   ResetLastError();
//--- change object text
   if(!ObjectSetString(chart_ID,name,OBJPROP_TEXT,text))
     {
      Print(__FUNCTION__,
            ": failed to change the text! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Return Edit object text                                          |
//+------------------------------------------------------------------+
bool EditTextGet(string      &text,        // text
                 const long   chart_ID=0,  // chart's ID
                 const string name="Edit") // object name
  {
//--- reset the error value
   ResetLastError();
//--- get object text
   if(!ObjectGetString(chart_ID,name,OBJPROP_TEXT,0,text))
     {
      Print(__FUNCTION__,
            ": failed to get the text! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Delete Edit object                                               |
//+------------------------------------------------------------------+
bool EditDelete(const long   chart_ID=0,  // chart's ID
                const string name="Edit") // object name
  {
//--- reset the error value
   ResetLastError();
//--- delete the label
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete \"Edit\" object! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool TextCreate(const long              chart_ID=0,               // chart's ID
                const string            name="Text",              // object name
                const int               sub_window=0,             // subwindow index
                datetime                time=0,                   // anchor point time
                double                  price=0,                  // anchor point price
                const string            text="Text",              // the text itself
                const string            font="Arial",             // font
                const int               font_size=10,             // font size
                const color             clr=clrRed,               // color
                const double            angle=0.0,                // text slope
                const ENUM_ANCHOR_POINT anchor=ANCHOR_LEFT_UPPER, // anchor type
                const bool              back=false,               // in the background
                const bool              selection=false,          // highlight to move
                const bool              hidden=true,              // hidden in the object list
                const long              z_order=0)                // priority for mouse click
  {
//--- Extra Addition
   if(FastSpeed_Flag) return false;
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return false;
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return false;
   if(ObjectFind(0,name) >= 0) TextDelete(0,name);
//--- set anchor point coordinates if they are not set
   ChangeTextEmptyPoint(time,price);
//--- reset the error value
   ResetLastError();
//--- create Text object
   if(!ObjectCreate(chart_ID,name,OBJ_TEXT,sub_window,time,price))
     {
      Print(__FUNCTION__,
            ": failed to create \"Text\" object! Error code = ",GetLastError());
      return(false);
     }
//--- set the text
   ObjectSetString(chart_ID,name,OBJPROP_TEXT,text);
//--- set text font
   ObjectSetString(chart_ID,name,OBJPROP_FONT,font);
//--- set font size
   ObjectSetInteger(chart_ID,name,OBJPROP_FONTSIZE,font_size);
//--- set the slope angle of the text
   ObjectSetDouble(chart_ID,name,OBJPROP_ANGLE,angle);
//--- set anchor type
   ObjectSetInteger(chart_ID,name,OBJPROP_ANCHOR,anchor);
//--- set color
   ObjectSetInteger(chart_ID,name,OBJPROP_COLOR,clr);
//--- display in the foreground (false) or background (true)
   ObjectSetInteger(chart_ID,name,OBJPROP_BACK,back);
//--- enable (true) or disable (false) the mode of moving the object by mouse
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTABLE,selection);
   ObjectSetInteger(chart_ID,name,OBJPROP_SELECTED,selection);
//--- hide (true) or display (false) graphical object name in the object list
   ObjectSetInteger(chart_ID,name,OBJPROP_HIDDEN,hidden);
//--- set the priority for receiving the event of a mouse click in the chart
   ObjectSetInteger(chart_ID,name,OBJPROP_ZORDER,z_order);
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Move the anchor point                                            |
//+------------------------------------------------------------------+
bool TextMove(const long   chart_ID=0,  // chart's ID
              const string name="Text", // object name
              datetime     time=0,      // anchor point time coordinate
              double       price=0)     // anchor point price coordinate
  {
//--- if point position is not set, move it to the current bar having Bid price
   if(!time)
      time=TimeCurrent();
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
//--- reset the error value
   ResetLastError();
//--- move the anchor point
   if(!ObjectMove(chart_ID,name,0,time,price))
     {
      Print(__FUNCTION__,
            ": failed to move the anchor point! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Change the object text                                           |
//+------------------------------------------------------------------+
bool TextChange(const long   chart_ID=0,  // chart's ID
                const string name="Text", // object name
                const string text="Text") // text
  {
//--- reset the error value
   ResetLastError();
//--- change object text
   if(!ObjectSetString(chart_ID,name,OBJPROP_TEXT,text))
     {
      Print(__FUNCTION__,
            ": failed to change the text! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Delete Text object                                               |
//+------------------------------------------------------------------+
bool TextDelete(const long   chart_ID=0,  // chart's ID
                const string name="Text") // object name
  {
//--- reset the error value
   ResetLastError();
//--- delete the object
   if(!ObjectDelete(chart_ID,name))
     {
      Print(__FUNCTION__,
            ": failed to delete \"Text\" object! Error code = ",GetLastError());
      return(false);
     }
//--- successful execution
   return(true);
  }
//+------------------------------------------------------------------+
//| Check anchor point values and set default values                 |
//| for empty ones                                                   |
//+------------------------------------------------------------------+
void ChangeTextEmptyPoint(datetime &time,double &price)
  {
//--- if the point's time is not set, it will be on the current bar
   if(!time)
      time=TimeCurrent();
//--- if the point's price is not set, it will have Bid value
   if(!price)
      price=SymbolInfoDouble(Symbol(),SYMBOL_BID);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
