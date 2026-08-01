#define   GOAT_VERSION_LABEL "1.37"
#include "GOAT_Inputs_Definitions.mqh"
//----------------------------------------------------------------------------------------------------------------------------------------------------
#property copyright        "GOATedge.ai"
#property link             "https://www.goatedge.ai"//"https://www.Biiionic.com"
#property version          version_
#property strict
#property icon             "GOAT.ico"
#property tester_no_cache
#property tester_file      NEWS_FILE
#property tester_file      GMT_OFFSET_FILE
#property tester_file      DST_FILE

#property tester_file      BIAS_FILE+"EURUSD"+".csv"
#property tester_file      BIAS_FILE+"GBPUSD"+".csv"
#property tester_file      BIAS_FILE+"USDJPY"+".csv"
#property tester_file      BIAS_FILE+"USDCAD"+".csv"
#property tester_file      BIAS_FILE+"USDCHF"+".csv"
#property tester_file      BIAS_FILE+"AUDUSD"+".csv"
#property tester_file      BIAS_FILE+"NZDUSD"+".csv"

#property tester_file      BIAS_FILE+"EURGBP"+".csv"
#property tester_file      BIAS_FILE+"EURJPY"+".csv"
#property tester_file      BIAS_FILE+"EURAUD"+".csv"
#property tester_file      BIAS_FILE+"EURNZD"+".csv"
#property tester_file      BIAS_FILE+"EURCAD"+".csv"
#property tester_file      BIAS_FILE+"EURCHF"+".csv"

#property tester_file      BIAS_FILE+"GBPJPY"+".csv"
#property tester_file      BIAS_FILE+"GBPAUD"+".csv"
#property tester_file      BIAS_FILE+"GBPNZD"+".csv"
#property tester_file      BIAS_FILE+"GBPCAD"+".csv"
#property tester_file      BIAS_FILE+"GBPCHF"+".csv"

#property tester_file      BIAS_FILE+"AUDJPY"+".csv"
#property tester_file      BIAS_FILE+"AUDCAD"+".csv"
#property tester_file      BIAS_FILE+"AUDNZD"+".csv"
#property tester_file      BIAS_FILE+"AUDCHF"+".csv"
#property tester_file      BIAS_FILE+"NZDJPY"+".csv"
#property tester_file      BIAS_FILE+"NZDCAD"+".csv"
#property tester_file      BIAS_FILE+"NZDCHF"+".csv"
#property tester_file      BIAS_FILE+"CADJPY"+".csv"
#property tester_file      BIAS_FILE+"CADCHF"+".csv"
#property tester_file      BIAS_FILE+"CHFJPY"+".csv"

#property tester_file      BIAS_FILE+"US500"+".csv"
#property tester_file      BIAS_FILE+"NAS100"+".csv"
#property tester_file      BIAS_FILE+"US30"+".csv"
#property tester_file      BIAS_FILE+"GER40"+".csv"
#property tester_file      BIAS_FILE+"EU50"+".csv"
#property tester_file      BIAS_FILE+"JP225"+".csv"
#property tester_file      BIAS_FILE+"AUS200"+".csv"

#property tester_file      BIAS_FILE+"BTCUSD"+".csv"
#property tester_file      BIAS_FILE+"ETHUSD"+".csv"

#property tester_file      BIAS_FILE+"XAUUSD"+".csv"
#property tester_file      BIAS_FILE+"XAGUSD"+".csv"

#property description      "-> Global Optimization Algorithmic Trader"
#property description      " "
#property description      " "
//----------------------------------------------------------------------------------------------------------------------------------------------------
//#include <mql4compat.mqh>
#include <Canvas\png.mqh>
#include <Math\Stat\Math.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\Trade.mqh>
#include "Optimizer.mqh"
#include "Dashboard.mqh"
//#include "XmlProcessor.mqh"
//#include "MTTester.mqh"
//#include <Canvas\iCanvas_CB.mqh> // https://www.mql5.com/ru/code/22164
//#include <fxsaber\MultiTester\MTTester.mqh //#include "MTTester.mqh"
//----------------------------------------------------------------------------------------------------------------------------------------------------
//string MetatraderKey="nsdqfddtlcvdusknzzlrvcpnbq468200|sbiiionic.com|47";
string MetatraderKey="xnwrqlvsugfkeglpyhndyoafci786096|sgoatalgo.com|15";
//In Case Website is Down for how many days the verified client can use the software
int ServerBreakDownDays=1;
// File to be Included
//#resource "\\Experts\\MPTS - GOAT\\Validation Libary biiionic.ex5"    // not working since its script file
//#import "Validation Libary biiionic.ex5"
//#import "Validation Libary goatalgo.ex5"
 //bool OnlineValidationFunction(string productKey,int gracePeriodDays,bool init);
//#import
//+------------------------------------------------------------------+
//#resource "\\Experts\\MPTS - Vince Eger\\G Definitions.ex5"
//#resource "\\Libraries\\G Definitions.ex5"
//#resource "\\G Definitions.ex5"
//#import   "::G Definitions.ex5"
// double func();
//#import
//#resource "\\Experts\\MPTS - GOAT\\GOAT Logo short.png" as uchar LOGO_png_data[]
//#resource "\\Experts\\MPTS - GOAT\\GOAT Name BG.png" as uchar LOGO_png_data[]
//#resource "\\Experts\\MPTS - GOAT\\KID Name BG.png" as uchar LOGO_png_data[]
//#resource "\\Experts\\MPTS - GOAT\\GOAT Gradient Logo.png" as uchar LOGO_png_data[]
#resource "GOAT Gradient Logo.png" as uchar LOGO_png_data[]
CPng EA_LOGO(LOGO_png_data);
//#resource "\\Files\\GOAT_News.csv" as string abc
#resource "\\Indicators\\MACD - GOAT 2.ex5"
string MACD_Path        = "::Indicators\\MACD - GOAT 2.ex5";                    // MACD Indicator Path
//---------------------------------------------------------------------------------------------------------------------------------------------------
class SEQUENCE
  {
   public:
   class TRADELEVEL
   {
    public:
    long     ticket;
    double   price_level,price_trade,sl,tp,lots;
    
    TRADELEVEL()
    {
     ticket = 0;
     price_level=price_trade=sl=tp=lots=0.0;
    }
   };
   
   TRADELEVEL  TradeLevels[];
   string      Desc;
   bool        Active,Traded,Trailing,Virtual,Retrace_Triggered;
   int         dir,Level_Count,Trades_Count;
   double      Level_Last,Level_Retrace,Level_Lock,Level_TP,Level_SL,Level_TSL,Level_Entry,LotsTotal;
   double      Size_Grid,Size_Lock,Size_TP,Size_SL,Size_TSL;
   double      StartLots,PeakLots,PeakCumLots,ScaleFactor,LotsRaw[],LotsNorm[],LotsCum[],Distances[];
   //double      FirstTradeEquity;
   
   SEQUENCE()
   {
    dir=OP_NIL; Virtual=false;
    Active=Traded=Trailing=Retrace_Triggered=false;
    Level_Count=Trades_Count=ArrayResize(TradeLevels,0,Max_Seq_Levels);
    Level_Last=Level_Retrace=Level_Lock=Level_TP=Level_SL=Level_TSL=Level_Entry=LotsTotal=0.0;
    Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;
    StartLots=PeakLots=PeakCumLots=ScaleFactor=0.0;
    ArrayResize(LotsRaw,0,Max_Seq_Trades); ArrayResize(LotsNorm,0,Max_Seq_Trades); ArrayResize(LotsCum,0,Max_Seq_Trades); ArrayResize(Distances,0,Max_Seq_Trades);
    //FirstTradeEquity=0.0;
   }
//----------------------
   void Init(int OP,bool v)
   {
    dir=OP; Virtual=v;
    Desc = Strat+((Virtual)?" Virtual ":" ")+((dir==OP_BUY)?"Buy":"Sell");
    Retrace_Triggered=false;
    Level_Retrace=0.0;
   }
//----------------------
   void End_Sequence(string desc)
   {
    if(Active)
    {
     if(Traded)// && ((dir==OP_BUY&&Last_PL_Buy>0.0)||(dir==OP_SELL&&Last_PL_Sell>0.0)) )
     {
      double PL=0.0;//,vol=0.0;
      for(int i=0;i<ArraySize(TradeLevels);i++)
      {
       if(TradeLevels[i].ticket!=0 && HistorySelectByPosition(TradeLevels[i].ticket))
       {
        ulong time=0;
        for(int j=0;j<HistoryDealsTotal();j++)
        {
         ulong deal_ticket;
         if((deal_ticket=HistoryDealGetTicket(j))>0)
         {
          //PositionSelectByTicket(TradeLevels[i].ticket))
          if(time==0) time = HistoryDealGetInteger(deal_ticket,DEAL_TIME);
          else
          {
           ArrayResize(Position_Durations,ArraySize(Position_Durations)+1);
           Position_Durations[ArraySize(Position_Durations)-1] = (double) MathAbs(HistoryDealGetInteger(deal_ticket,DEAL_TIME)-time)/60;
           Positions++;
          }
          PL+=HistoryDealGetDouble(deal_ticket,DEAL_PROFIT)+HistoryDealGetDouble(deal_ticket,DEAL_SWAP)+HistoryDealGetDouble(deal_ticket,DEAL_COMMISSION);
          //vol+=HistoryDealGetDouble(deal_ticket,DEAL_VOLUME);
          //Print(i+" "+TradeLevels[i].ticket+" "+HistoryDealGetDouble(deal_ticket,DEAL_PROFIT)+" "+HistoryDealGetDouble(deal_ticket,DEAL_SWAP)+" "+HistoryDealGetDouble(deal_ticket,DEAL_COMMISSION));
         }
        }
       }
      }
      if(PL>0.0)
      {
       if(Level_Count-Delay_Trade_Live > 2)
       {
        ArrayResize(Sequence_Profits,ArraySize(Sequence_Profits)+1);
        Sequence_Profits[ArraySize(Sequence_Profits)-1] = PL;///vol;
       }
      }
      Sequences_PL++;
     }
     Active=Traded=Trailing=Retrace_Triggered=false;
     Level_Count=Trades_Count=ArrayResize(TradeLevels,0,Max_Seq_Levels);
     Level_Last=Level_Retrace=Level_Lock=Level_TP=Level_SL=Level_TSL=Level_Entry=LotsTotal=0.0;
     Size_Grid=Size_Lock=Size_TP=Size_SL=Size_TSL=1234.5;
     StartLots=PeakLots=PeakCumLots=ScaleFactor=0.0;
     ArrayResize(LotsRaw,0,Max_Seq_Trades); ArrayResize(LotsNorm,0,Max_Seq_Trades); ArrayResize(LotsCum,0,Max_Seq_Trades); ArrayResize(Distances,0,Max_Seq_Trades);
     //if(DLF==100) Lots_Exponent2=Lots_Exponent; else Lots_Exponent2=DLF;
     //FirstTradeEquity=0.0;
     ObjectsDeleteAll(0,Desc);
     if(ObjectFind(0,Desc+" LockLine")>=0)   HLineDelete(0,Desc+" LockLine");
     if(ObjectFind(0,Desc+" TSL_Level")>=0)  HLineDelete(0,Desc+" TSL_Level");
     if(ObjectFind(0,Desc+" TPLine")>=0)     HLineDelete(0,Desc+" TPLine");
     if(ObjectFind(0,Desc+" SLLine")>=0)     HLineDelete(0,Desc+" SLLine");
     Print(Desc+" Sequence Ended"+" ("+desc+")");
    }
   }
//---------------------- Round any raw volume to the nearest tradable lot
   double NormalizedLots(double raw_volume)
   {
    const double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP); if(step <= 0.0)  return 0.0; // e.g. 0.01
    const double v_min  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);  // e.g. 0.01
    const double v_max  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);  if(v_max <= 0.0) return 0.0; // e.g. 100.00
    
    double steps = raw_volume / step;           // may be ±, fractional
           steps = MathRound(steps);            // MathRound is symmetric: -1.5 → -2, 1.5 → 2
    double lots  = steps * step;
    
    if(MathAbs(lots)<v_min) lots =  0.0;
    if(lots>=0)             lots =  MathMin(lots, v_max);
    else                    lots = -MathMin(MathAbs(lots), v_max);
    return lots;
   }
//---------------------- currency conversion fallback for cross-currency symbols
   double GetSymbolMidPrice(string sym)
   {
    if(sym=="") return 0.0;
    SymbolSelect(sym,true);

   MqlTick tk;
   if(SymbolInfoTick(sym,tk))
   {
     double tickBid = tk.bid, tickAsk = tk.ask;
     if(tickBid>0.0 && tickAsk>0.0) return 0.5*(tickBid+tickAsk);
     if(tickBid>0.0) return tickBid;
     if(tickAsk>0.0) return tickAsk;
   }

   double symBid = SymbolInfoDouble(sym,SYMBOL_BID);
   double symAsk = SymbolInfoDouble(sym,SYMBOL_ASK);
   if(symBid>0.0 && symAsk>0.0) return 0.5*(symBid+symAsk);
   if(symBid>0.0) return symBid;
   if(symAsk>0.0) return symAsk;
   return 0.0;
   }
   double ConvertCurrencyAmount(double amount,string from,string to,string &convSym,double &convPx,bool &isInverse)
   {
    convSym=""; convPx=0.0; isInverse=false;
    if(!MathIsValidNumber(amount) || amount==0.0) return 0.0;
    if(from=="" || to=="") return 0.0;
    if(from==to) return amount;

    int total = (int)SymbolsTotal(false);
    for(int i=0;i<total;i++)
    {
     string sym = SymbolName(i,false);
     if(sym=="") continue;

     string base="", profit="";
     if(!SymbolInfoString(sym,SYMBOL_CURRENCY_BASE,base)) continue;
     if(!SymbolInfoString(sym,SYMBOL_CURRENCY_PROFIT,profit)) continue;

     double px = GetSymbolMidPrice(sym);
     if(!(px>0.0) || !MathIsValidNumber(px)) continue;

     if(base==from && profit==to)
     {
      convSym = sym;
      convPx  = px;
      isInverse = false;
      return amount * px;
     }
     if(base==to   && profit==from)
     {
      convSym = sym;
      convPx  = px;
      isInverse = true;
      return amount / px;
     }
    }
    return 0.0;
   }
//---------------------- price→money conversion for 1.0 lot per 1.0 price unit
   double PriceValuePerPointPerLot0()
   {
    double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(ts<=0.0) ts=_Point; // safety
    return tv/ts;
   }
   double PriceValuePerPointPerLot1()
   {
    double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    if(ts<=0 || !MathIsValidNumber(ts)) ts = pt; // guard
    return (MathIsValidNumber(tv) && tv!=0.0 && MathIsValidNumber(ts) && ts>0.0 && MathIsValidNumber(pt) && pt>0.0) ? tv * (pt/ts) : 0.0;
   }
   double PriceValuePerPointPerLot()
   {
      // --- Basics
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      if(!(point > 0.0) || !MathIsValidNumber(point)) point = _Point;
      // --- Fast path: only use TickSize if it's non-zero; don't scale by point
      double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   
      if(MathIsValidNumber(ts) && ts > 0.0 && MathIsValidNumber(tv) && tv > 0.0)
      {
         double v = tv / ts;                 // per "price unit" as provided; brokers that set these right give correct per-point money for 1 lot in practice
         if(v > 0.0 && MathIsValidNumber(v)) return v;
      }
      // If TickSize is invalid/missing but TickValue exists, use it as-is
      if((!MathIsValidNumber(ts) || ts <= 0.0) && MathIsValidNumber(tv) && tv > 0.0) return tv;
      // --- FOREX-only manual calc (no cross lookups)
      long calc = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_CALC_MODE);
      if(calc == SYMBOL_CALC_MODE_FOREX || calc == SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE)
      {
         string acc   = AccountInfoString(ACCOUNT_CURRENCY);
         string base, quote;
         SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE,   base);
         SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT, quote);
         double contract = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
         if(!(contract > 0.0)) contract = 100000.0; // assume std FX lot if missing
   
         double BID = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double px  = (BID > 0.0 ? BID : SymbolInfoDouble(_Symbol, SYMBOL_ASK));
         if(contract > 0.0)
         {
            // Account == quote (e.g., USD acct & EURUSD) → $1 per 0.00001 move with 100k lot (typical)
            if(acc == quote && quote != "") return contract * point;
            // Account == base (e.g., USD acct & USDJPY) → divide by price
            if(acc == base && base != "" && px > 0.0) return (contract * point) / px;

            // Cross-currency account fallback (e.g., USD acct & AUDJPY) -> convert quote currency to account currency
            string convSym="";
            double convPx=0.0;
            bool   convInverse=false;
            double cross = ConvertCurrencyAmount(contract * point, quote, acc, convSym, convPx, convInverse);
            if(cross > 0.0 && MathIsValidNumber(cross))
            {
               static string lastCrossLog = "";
               string logKey = _Symbol+"|"+quote+"|"+acc+"|"+convSym+"|"+DoubleToString(convPx,_Digits);
               if(lastCrossLog != logKey)
               {
                  lastCrossLog = logKey;
                  Print("PriceValuePerPointPerLot cross fallback: sym=",_Symbol,
                        " profit=",quote,
                        " account=",acc,
                        " via=",convSym,
                        (convInverse?" inverse":" direct"),
                        " px=",DoubleToString(convPx,_Digits),
                        " perPointPerLot=",DoubleToString(cross,6));
               }
               return cross;
            }
         }
      }
      // --- Last resort: EURUSD-like default (per 1 point, 1 lot)
      static string lastFallbackWarn = "";
      string fallbackKey = _Symbol+"|"+AccountInfoString(ACCOUNT_CURRENCY);
      if(lastFallbackWarn != fallbackKey)
      {
         lastFallbackWarn = fallbackKey;
         Print("PriceValuePerPointPerLot WARNING: using final fallback 1.0 for sym=",_Symbol,
               " account=",AccountInfoString(ACCOUNT_CURRENCY),
               " tickValue=",DoubleToString(tv,6),
               " tickSize=",DoubleToString(ts,6));
      }
      return 1.0;
   }
//---------------------- build a formatted lots/cum-lots/cum-loss string
   string BuildLotsInfoString(void)
   {
    // if StartLots not set by caller, infer it like level-1 sizing
    double startL = StartLots;
    if(startL<=0.0)
    {
          if(Mode_Lots==FixedLots)    startL = Lots;
     else if(Mode_Lots==ScaledLots)   startL = Lots * AccountInfoDouble(ACCOUNT_EQUITY) / 1000.0;
     else if(Mode_Lots==RiskperSeq)   startL = SolveStartLotsByRisk(Risk);
     else                             startL = Lots;
     StartLots = startL;
    }
    // build future series from StartLots (normalized lots are the "real" tradable volumes)
    BuildRawLots(startL);
    ScaleRawLots();
    BuildNormalizedLots();
    BuildCumulativeLots(LotsNorm); // fills LotsCum from normalized lots

    const double perUnit  = PriceValuePerPointPerLot();
    const double baseGrid = (Size_Grid==1234.5) ? GetSize(GRID) : Size_Grid;

    double standing = 0.0;   // net lots before current step’s adverse move
    double cumLoss  = 0.0;   // running cumulative loss

    string s = "GAPs=["+DoubleToString(Grid_Exponent,2)+","+DoubleToString(Grid_Factor,2)+"]"+"   LOTs=["+DoubleToString(Lots_Exponent,2)+","+DoubleToString(Lots_Factor,2)+"]\n\n";
           s+= "Peak Cumulative Lots="+DoubleToString(PeakCumLots,2)+"   Scale Factor="+DoubleToString(ScaleFactor,5)+"\n\n";
    if(Mode_Lots_Prog==Lots_Prog_CumPartial)
           s+= "NOTE: CumPartial uses this ladder as a baseline only. After retrace closes, next deeper lots are recalculated from live standing volume.\n\n";

    for(int lvl=0; lvl<Max_Seq_Trades; ++lvl)
    {
     if(lvl>0)
     {
      standing += LotsNorm[lvl-1];
      if(standing < 0.0) standing = 0.0;

      double d = GetSize(GRID_VALID, lvl, baseGrid); // step distance (price units)
      if(d < 0.0) d = -d;

      cumLoss += d * perUnit * standing;
     }
     s += "Lvl=" + IntegerToString(lvl+1,2,'0')
        + ((LotsNorm[lvl]>=0)    ?("  Lots= "    + DoubleToString(LotsNorm[lvl],2))
                                 :("  Lots="     + DoubleToString(LotsNorm[lvl],2)))
        + ((LotsCum[lvl]<=10.0)  ?("  Cum_Lots= "+ DoubleToString(LotsCum[lvl],2))
                                 :("  Cum_Lots=" + DoubleToString(LotsCum[lvl],2)))
        + "  Cum_Loss="+ DoubleToString(cumLoss,2) + "\n";
    }
    return s;
   }
//---------------------- build a formatted string from the already-open sequence levels
   string FormatCompactValue(double value,int digits=2)
   {
    string s = DoubleToString(value,digits);
    int dot = StringFind(s,".");
    if(dot>=0)
    {
     while(StringLen(s)>dot+1 && StringGetCharacter(s,StringLen(s)-1)=='0')
           s = StringSubstr(s,0,StringLen(s)-1);
     if(StringLen(s)>0 && StringGetCharacter(s,StringLen(s)-1)=='.')
           s = StringSubstr(s,0,StringLen(s)-1);
    }
    if(s=="-0") s="0";
    return s;
   }
//----------------------
   string PadRightValue(string value,int width)
   {
    while(StringLen(value)<width) value += " ";
    return value;
   }
//---------------------- build a formatted string from the already-open sequence levels
   string BuildOpenedLotsInfoString(void)
   {
    if(!Active || Level_Count<=0) return "";

    if(Traded) RefreshTicketLots();

    double point = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
    if(!(point>0.0) || !MathIsValidNumber(point)) point = _Point;
    if(!(point>0.0) || !MathIsValidNumber(point)) point = 1e-8;

    double pipUnit = point*10.0;
    if(!(pipUnit>0.0) || !MathIsValidNumber(pipUnit)) pipUnit = point;

    double perUnit = PriceValuePerPointPerLot();
    double standingNow = 0.0;
    int    openLevels  = 0;
    bool   hasClosedLevels = false;

    for(int i=0; i<Level_Count; i++)
    {
     double lots = TradeLevels[i].lots;
     if(!MathIsValidNumber(lots) || lots<0.0) lots = 0.0;
     if(lots>0.0) {standingNow += lots; openLevels++;}
     else if(i<Level_Count-1) hasClosedLevels = true;
     if(Traded && TradeLevels[i].ticket==0) hasClosedLevels = true;
    }

    string state = Virtual ? "Virtual" : (Traded ? "Live" : "Delayed");
    string lockTxt = "-";
    string tpTxt   = "-";
    string slTxt   = "-";

    if(MathIsValidNumber(Level_Lock) && Level_Lock>0.0 && Level_Lock<999999.0) lockTxt = DoubleToString(Level_Lock,_Digits);
    if(MathIsValidNumber(Level_SL)   && Level_SL  >0.0 && Level_SL  <999999.0) slTxt   = DoubleToString(Level_SL,_Digits);
    if(dir==OP_BUY)
    {
     if(MathIsValidNumber(Level_TP) && Level_TP>0.0 && Level_TP<999999.0) tpTxt = DoubleToString(Level_TP,_Digits);
    }
    else if(dir==OP_SELL)
    {
     if(MathIsValidNumber(Level_TP) && Level_TP>0.0) tpTxt = DoubleToString(Level_TP,_Digits);
    }

    string s = Desc+" Open Layout\n";
           s+= "State="+state
             + "  Levels="+(string)Level_Count
             + "  OpenLevels="+(string)openLevels
             + "  StandingLots="+DoubleToString(standingNow,2)+"\n";
           s+= "Entry="+DoubleToString(Level_Entry,_Digits)
             + "  Lock="+lockTxt
             + "  TP="+tpTxt
             + "  SL="+slTxt;
    if(Level_Retrace>0.0 && MathIsValidNumber(Level_Retrace))
           s+= "  Retrace="+DoubleToString(Level_Retrace,_Digits);
           s+= "\n";

    if(Mode_Lots_Prog==Lots_Prog_CumPartial || hasClosedLevels)
           s+= "NOTE: Open layout uses actual standing lots on the stored live levels, so partially closed/buried levels can show 0.00 lots.\n";
           s+= "\n";

    double standing = 0.0;
    double cumLoss  = 0.0;

    for(int lvl=0; lvl<Level_Count; ++lvl)
    {
     double lots = TradeLevels[lvl].lots;
     if(!MathIsValidNumber(lots) || lots<0.0) lots = 0.0;

     string gapTxt = "0";
     if(lvl>0)
     {
      double gap = MathAbs(TradeLevels[lvl].price_level - TradeLevels[lvl-1].price_level);
      double gapPips = gap/pipUnit;
      cumLoss += gap * perUnit * standing;
      gapTxt = FormatCompactValue(gapPips,1) + "p";
     }
     gapTxt = PadRightValue(gapTxt,5);

     double cumLots = standing + lots;
     if(cumLots<0.0) cumLots = 0.0;

     s += "Lvl=" + IntegerToString(lvl+1,2,'0')
        + "  Gap=" + gapTxt
        + ((lots<10.0)    ? ("  Lots= "    + DoubleToString(lots,2))
                          : ("  Lots="     + DoubleToString(lots,2)))
        + ((cumLots<10.0) ? ("  Cum_Lots= "+ DoubleToString(cumLots,2))
                          : ("  Cum_Lots=" + DoubleToString(cumLots,2)))
        + "  Cum_Loss="+ FormatCompactValue(cumLoss,2);

     if(Traded && TradeLevels[lvl].ticket==0) s += "  [closed]";
     s += "\n";

     standing = cumLots;
    }

    return s;
   }
//---------------------- solver for StartLots by target sequence loss (MLPS)
   double SolveStartLotsByRisk(double targetLoss)
   {
    double vmin  = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
    double vmax  = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
    double vstep = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
    
    if(vstep <= 0.0 || vmax <= 0.0) return vmin;
    if(targetLoss<=0.0) return vmin;
    // work in discrete lot-step indices to avoid a second pass
    int kmin = 0;
    int kmax = (int)MathFloor((vmax - vmin)/vstep + 1e-9);

    int    bestK   = kmin;
    double bestErr = DBL_MAX;

    for(int it=0; it<40 && kmin<=kmax; ++it)
    {
     int kmid = (kmin + kmax) / 2;
     // evaluate mid and its neighbors once per iteration
     int ks[3]; ks[0] = MathMax(kmin, kmid-1); ks[1] = kmid; ks[2] = MathMin(kmax, kmid+1);
     
     double loss_mid = 0.0; bool mid_set=false;

     for(int i=0; i<3; ++i)
     {
      int    ki = ks[i];
      double L0 = vmin + ki * vstep;
             L0 = NormalizedLots(L0);
      double loss = EvalLossForStart(L0);
      double err  = MathAbs(loss - targetLoss);

      if(err < bestErr) { bestErr = err; bestK = ki; }
      if(ki == kmid) { loss_mid = loss; mid_set = true; }
     }
     if(!mid_set) break; // safety (should not happen)
     // discrete monotone step: move bounds based on mid
     if(loss_mid > targetLoss) kmax = kmid - 1;
     else                      kmin = kmid + 1;

     if(kmax - kmin <= 0) break;          // converged on the step grid
    }
    double best = vmin + bestK * vstep;
    return NormalizedLots(best);
   }
//---------------------- evaluate sequence max loss for a given StartLots (uses normalized lots)
   double EvalLossForStart(double L0)
   {
    StartLots = L0;                        // ensure ScaleRawLots() uses the candidate L0
    BuildRawLots(L0);
    ScaleRawLots();
    BuildNormalizedLots();
    BuildCumulativeLots(LotsNorm);         // standing exposure must be based on normalized lots
    BuildDistances();
    return FindCumLoss();                  // fills LossPath[], MaxLossPlanned/AtStep
   }
//----------------------
   void BuildRawLots(double InitLots)
   {
      ArrayResize(LotsRaw,Max_Seq_Trades,Max_Seq_Trades); ArrayInitialize(LotsRaw,0.0); // Re Initialize
      double cum=0.0,align = 1.0; // scales all L>=1 deltas to keep them in line with L1 target
      
      for(int lvl=0;lvl<Max_Seq_Trades;lvl++)
      {
       const int N = (Max_Seq_Trades>0) ? Max_Seq_Trades : 1;
       double w2 = (double)lvl / (double)N;
       double w1 = 1.0 - w2;
       double l  = 0.0;
       
       if(lvl==0)
       {
        LotsRaw[lvl]=InitLots;
        
        double Leff0 = (w1*Lots_Exponent + w2*Lots_Exponent*Lots_Factor);
        // Cum2 seed only makes sense when the first-step cumulative factor expands exposure.
        if(Mode_Lots_Prog==Lots_Prog_Cum2 && Leff0>1.0+1e-9) cum=InitLots/(1.0 - 1.0/Leff0);
        else                                                  cum=InitLots;
        
        continue;
       }
       switch(Mode_Lots_Prog)
       {
        case Lots_Prog_Start:
               l = InitLots*(w1*Lots_Exponent+w2*Lots_Exponent*Lots_Factor); break;
        case Lots_Prog_Last:
               if(Lots_Exponent*Lots_Factor<0.0) l = InitLots*w1*MathPow(Lots_Exponent,lvl) - InitLots*w2*MathPow(MathAbs(Lots_Exponent*Lots_Factor),lvl);
               else                              l = InitLots*w1*MathPow(Lots_Exponent,lvl) + InitLots*w2*MathPow(MathAbs(Lots_Exponent*Lots_Factor),lvl); break;
        case Lots_Prog_Cum:{
               // Effective multiplicative factor for this level (your existing shaping)
               double Leff = (w1*Lots_Exponent + w2*Lots_Exponent*Lots_Factor);
               // Standard cumulative delta rule for later steps: li = c_{i-1} * (Leff - 1)
               l   = cum * (Leff - 1.0);
               // If we are effectively flat, never generate a negative delta
               // if (cum <= 0.0 && l < 0.0) l = 0.0;
               cum += l;                 // cum *= Leff
               if(cum < 0.0) cum = 0.0;  // flooring
               break;}
        case Lots_Prog_CumPartial:{
               // CumPartial keeps Cum's signed ladder shape; retrace closes are an extra feature.
               double Leff = (w1*Lots_Exponent + w2*Lots_Exponent*Lots_Factor);
               l   = cum * (Leff - 1.0);
               cum += l;
               if(cum < 0.0) cum = 0.0;
               break;}
        case Lots_Prog_Cum2:{
               // Effective multiplicative factor for this level (your existing shaping)
               double Leff = (w1*Lots_Exponent + w2*Lots_Exponent*Lots_Factor);
               // Standard cumulative delta rule for later steps: li = c_{i-1} * (Leff - 1)
               l   = cum * (Leff - 1.0);
               // If we are effectively flat, never generate a negative delta
               // if (cum <= 0.0 && l < 0.0) l = 0.0;
               cum += l;                 // cum *= Leff
               if(cum < 0.0) cum = 0.0;  // flooring
               break;}
        case Lots_Prog_Peak:{
               // --- Safe bounds and anchors
               const int    Nraw   = (Max_Seq_Trades>0) ? Max_Seq_Trades : 1;
               int          pivot  = (int)MathRound(Max_Seq_Trades * Peak_Lots_Pos_PC / 100.0);
               if(pivot < 1)      pivot = 1;                 // need at least one step to rise
               if(pivot > Nraw-1) pivot = Nraw-1;            // keep inside [1..N-1]
            
               const double C0    = InitLots;                // cumulative at level 0 (seeded outside when lvl==0)
               const double Cpeak = InitLots * Lots_Max_Cum; // required peak cumulative
               const int    N     = Nraw;
               const int    downCnt = (N-1) - pivot;         // number of steps to descend (>=0)
               /*
               // --- Shaping controls (simple bounds; no 0.20 floor)
               double s_up_raw   = Lots_Exponent; if(s_up_raw   < -5.0) s_up_raw   = -5.0; if(s_up_raw   > 5.0) s_up_raw   = 5.0;
               double s_down_raw = Lots_Factor;   if(s_down_raw < -5.0) s_down_raw = -5.0; if(s_down_raw > 5.0) s_down_raw = 5.0;
               // Use magnitude for slope *strength*, keep direction semantics (rise then fall).
               double s_up_mag   = MathMax(1e-6, MathAbs(s_up_raw));    // [1e-6 .. 5]
               double s_down_mag = MathMax(1e-6, MathAbs(s_down_raw));  // [1e-6 .. 5]
               // --- Endpoint slopes (unchanged structure; keep a smooth, flat peak)
               double span_up   = (tp > 1e-9)       ? tp       : 1.0;
               double span_down = ((1.0-tp) > 1e-9) ? 1.0-tp   : 1.0;
               
               double m0  =  s_up_mag   * (Cpeak - C0) / span_up;     // ALWAYS rising on the left
               double mpL =  0.0;                                     // keep the apex flat
               double mpR =  0.0;                                     // keep the apex flat
               double m1  = -s_down_mag * (Cpeak - 0.0) / span_down;  // ALWAYS falling on the right
               */
               // --- Shaping controls (clamped to keep numerics sane)
               double s_up   = Lots_Exponent; if(s_up   < 0.01) s_up   = 0.01; if(s_up   > 5.0) s_up   = 5.0;
               double s_down = Lots_Factor;   if(s_down < 0.01) s_down = 0.01; if(s_down > 5.0) s_down = 5.0;
               // --- Normalized positions in [0..1] across the whole span (for smooth cubic parameterization)
               const double t  = (N>1) ? ((double)lvl)/((double)(N-1)) : 0.0;
               const double tp = (N>1) ? ((double)pivot)/((double)(N-1)) : 0.5;
               // --- Endpoint slopes for the Hermite segments (w.r.t. normalized t)
               // Left segment [0,tp]: C0 -> Cpeak with slope m0 at t=0 and slope 0 at t=tp
               // Right segment [tp,1]: Cpeak -> 0 with slope 0 at t=tp and slope m1 at t=1
               double span_up   = (tp > 1e-9)       ? tp        : 1.0;
               double span_down = ((1.0-tp) > 1e-9) ? (1.0-tp)  : 1.0;
               double m0  =  s_up   * (Cpeak - C0) / span_up;      // initial slope at t=0
               double mpL =  0.0;                                   // slope at peak from left
               double mpR =  0.0;                                   // slope at peak from right
               double m1  = -s_down * (Cpeak - 0.0) / span_down;    // terminal slope at t=1 (negative)
               // --- Hermite basis helper (inline)
               // H00 =  2h^3 - 3h^2 + 1
               // H10 =    h^3 - 2h^2 + h
               // H01 = -2h^3 + 3h^2
               // H11 =    h^3 -   h^2
               double target_cum;
               if(t <= tp || (N<=2))
               {
                  double a=0.0, b=tp, denom=(b-a);
                  if(denom < 1e-12)
                  {
                     target_cum = Cpeak;                       // degenerate left span
                  }
                  else
                  {
                     double h = (t - a) / denom; if(h<0.0) h=0.0; if(h>1.0) h=1.0;
                     double h2 = h*h, h3 = h2*h;
                     double H00 =  2.0*h3 - 3.0*h2 + 1.0;
                     double H10 =      h3 - 2.0*h2 + h;
                     double H01 = -2.0*h3 + 3.0*h2;
                     double H11 =      h3 -     h2;
                     target_cum = H00*C0 + H10*(denom*m0) + H01*Cpeak + H11*(denom*mpL);
                  }
               }
               else
               {
                  double a=tp, b=1.0, denom=(b-a);
                  if(denom < 1e-12)
                  {
                     target_cum = 0.0;                          // degenerate right span
                  }
                  else
                  {
                     double h = (t - a) / denom; if(h<0.0) h=0.0; if(h>1.0) h=1.0;
                     double h2 = h*h, h3 = h2*h;
                     double H00 =  2.0*h3 - 3.0*h2 + 1.0;
                     double H10 =      h3 - 2.0*h2 + h;
                     double H01 = -2.0*h3 + 3.0*h2;
                     double H11 =      h3 -     h2;
                     // Left endpoint (t=tp): value Cpeak, slope 0; Right endpoint (t=1): value 0, slope m1
                     target_cum = H00*Cpeak + H10*(denom*mpR) + H01*0.0 + H11*(denom*m1);
                  }
               }
               // --- Enforce exact anchors (numerical safety)
               if(lvl == pivot) target_cum = Cpeak;
               if(lvl == N-1)   target_cum = 0.0;
               // --- Delta needed at this level to reach the cumulative target
               l   = target_cum - cum;
               cum+= l;
               // --- Micro-correction at the pivot and final bar for perfect anchoring
               if(lvl == pivot)
               {
                  double err = Cpeak - cum;
                  if(MathAbs(err) > 1e-6) { l += err; cum = Cpeak; }
               }
               if(lvl == N-1)
               {
                  double err = 0.0 - cum;
                  if(MathAbs(err) > 1e-6) { l += err; cum = 0.0; }
               }
               break;}}
       LotsRaw[lvl] = l;
       //Print("Level="+lvl+" Lots="+DoubleToString(LotsRaw[lvl],2));
      }
   }
//----------------------
   void ScaleRawLots()
   {
    double cum=0.0, peak=0.0;
    for(int lvl=0;lvl<Max_Seq_Trades;lvl++)
    {
     cum += LotsRaw[lvl];
     if(cum<0.0) cum=0.0;
     if(cum>peak) peak=cum;
    }
    PeakCumLots = peak;

    ScaleFactor=1.0;
    if(PeakCumLots > StartLots*Lots_Max_Cum) ScaleFactor = (StartLots*Lots_Max_Cum)/PeakCumLots;

    for(int lvl=1;lvl<Max_Seq_Trades;lvl++) LotsRaw[lvl] *= ScaleFactor;
   }
//----------------------
   void BuildNormalizedLots() {ArrayResize(LotsNorm,Max_Seq_Trades,Max_Seq_Trades); for(int lvl=0;lvl<Max_Seq_Trades;lvl++) LotsNorm[lvl]=NormalizedLots(LotsRaw[lvl]);}
//----------------------
   void BuildCumulativeLots(double &LotsArr[])
   {
    ArrayResize(LotsCum,Max_Seq_Trades,Max_Seq_Trades);
    double Cum=0.0; PeakCumLots=0.0;
    for(int lvl=0;lvl<Max_Seq_Trades;lvl++)
    {
     Cum+=LotsArr[lvl];
     if(Cum<0.0) Cum=0.0;          // clamp: cannot have negative standing exposure
     LotsCum[lvl]=Cum;             // store net cumulative (standing) lots
     if(Cum>PeakCumLots) PeakCumLots=Cum;
    }
   }
//---------------------- keep ticket-backed lots aligned to live broker volume
   void RefreshTicketLots()
   {
    const double VolMin = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
    for(int i=0; i<Level_Count; i++)
    {
     ulong tk = (ulong)TradeLevels[i].ticket;
     if(tk==0) continue;
     if(!PositionSelectByTicket(tk))
     {
      TradeLevels[i].lots   = 0.0;
      TradeLevels[i].ticket = 0;
      continue;
     }
     double vol = PositionGetDouble(POSITION_VOLUME);
     if(vol < VolMin - 1e-9)
     {
      TradeLevels[i].lots   = 0.0;
      TradeLevels[i].ticket = 0;
     }
     else TradeLevels[i].lots = vol;
    }
   }
//---------------------- sum live standing volume only from ticket-backed positions
   double GetStandingLots(bool refresh=true)
   {
    if(!Traded) return 0.0;
    if(refresh) RefreshTicketLots();
    double standing = 0.0;
    for(int i=0; i<Level_Count; i++)
    {
     if(TradeLevels[i].ticket!=0 && TradeLevels[i].lots>0.0)
        standing += TradeLevels[i].lots;
    }
    return standing;
   }
//---------------------- find the next retrace trigger that is closer to profit
   double FindNextRetraceLevel(double fromLevel)
   {
    if(Level_Count<2 || !(fromLevel>0.0) || !MathIsValidNumber(fromLevel)) return 0.0;

    double eps = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
    if(!(eps>0.0) || !MathIsValidNumber(eps)) eps = _Point;
    if(!(eps>0.0) || !MathIsValidNumber(eps)) eps = 1e-8;

    double nextLevel = 0.0;
    bool found = false;
    for(int i=0; i<Level_Count; i++)
    {
     double lvl = TradeLevels[i].price_level;
     if(!(lvl>0.0) || !MathIsValidNumber(lvl)) continue;

     if(dir==OP_BUY)
     {
      if(lvl > fromLevel + eps && (!found || lvl < nextLevel))
      {
       nextLevel = lvl;
       found = true;
      }
     }
     else if(dir==OP_SELL)
     {
      if(lvl < fromLevel - eps && (!found || lvl > nextLevel))
      {
       nextLevel = lvl;
       found = true;
      }
     }
    }
    return found ? nextLevel : 0.0;
   }
//---------------------- consume the current retrace trigger and arm the next one
   void AdvanceRetraceLevel()
   {
    if(!(Level_Retrace>0.0) || !MathIsValidNumber(Level_Retrace)) return;
    Retrace_Triggered = true;
    Level_Retrace = FindNextRetraceLevel(Level_Retrace);
   }
//---------------------- dynamic next deeper lot for CumPartial mode
   double CalcNextLotsCumPartial()
   {
    double standing = GetStandingLots(true);
    if(standing<=0.0) return 0.0;

    int N = (Max_Seq_Trades>0) ? Max_Seq_Trades : 1;
    int lvl = MathMin(Level_Count,N-1);
    double w2 = (double)lvl / (double)N;
    double w1 = 1.0 - w2;
    double Leff = (w1*Lots_Exponent + w2*Lots_Exponent*Lots_Factor);

    double nextLots = standing * (Leff - 1.0);
    if(nextLots > 0.0 && Lots_Max_Cum>0.0)
    {
     double remaining = StartLots*Lots_Max_Cum - standing;
     if(remaining <= 0.0) return 0.0;
     if(nextLots > remaining) nextLots = remaining;
    }
    if(nextLots > 0.0 && Lots_Max>0.01)
    {
     double tradeCap = Lots_Max*StartLots;
     if(nextLots > tradeCap) nextLots = tradeCap;
    }
    return NormalizedLots(nextLots);
   }
//---------------------- close standing volume as prior levels are recrossed
   bool HandlePartialRetrace(double price)
   {
    if(Virtual || !Active || !Traded || Mode_Lots_Prog!=Lots_Prog_CumPartial || Partial_Profit_Factor<=0.0 || Level_Count<2)
       return true;
    if(!(Level_Retrace>0.0) || !MathIsValidNumber(Level_Retrace)) return true;

    bool crossed = ((dir==OP_BUY) ? (price >= Level_Retrace) : (price <= Level_Retrace));
    if(!crossed) return true;

    double factor = MathMax(0.0,MathMin(100.0,Partial_Profit_Factor))*0.01;
    double standing = GetStandingLots(true);
    if(standing <= 0.0)
    {
     End_Sequence("Sequence Closed: No standing lots on retrace");
     return false;
    }

    double lotsToClose = NormalizedLots(standing * factor);
    if(lotsToClose > standing) lotsToClose = NormalizedLots(standing);
    if(lotsToClose <= 0.0)
    {
     AdvanceRetraceLevel();
     return true;
    }

    if(!closeLots(lotsToClose)) return false;

    UpdateLockTPSL(Trades_Count);
    if(GetStandingLots(true) <= 0.0)
    {
     End_Sequence("Sequence Closed: Partial retrace flattened sequence");
     return false;
    }

    AdvanceRetraceLevel();
    return true;
   }
//---------------------- build cumulative adverse distances (price units)
   void BuildDistances()
   {
    ArrayResize(Distances,Max_Seq_Trades,Max_Seq_Trades); ArrayInitialize(Distances,0.0);
    double base_grid = (Size_Grid==1234.5) ? GetSize(GRID) : Size_Grid;

    for(int i=1;i<Max_Seq_Trades;i++)
    {
     double d = GetSize(GRID_VALID,i,base_grid);          // step distance (price units)
     if(d<0.0) d=-d;                                      // store magnitudes
     Distances[i] = Distances[i-1] + d;                   // cumulative adverse travel
    }
   }
//---------------------- compute loss path and max loss (uses LotsCum & Distances)
   double FindCumLoss()
   {
    double LossPath[];
    ArrayResize(LossPath,Max_Seq_Trades,Max_Seq_Trades); ArrayInitialize(LossPath,0.0);
    double perUnit = PriceValuePerPointPerLot();

    double loss=0.0, maxLoss=0.0; int maxStep=0;
    for(int i=1;i<Max_Seq_Trades;i++)
    {
     double delta     = Distances[i] - Distances[i-1];    // adverse move between (i-1)→i
     double standing  = LotsCum[i-1];                     // net lots before opening level i
     if(standing<0.0) standing=0.0;                       // safety clamp
     loss += delta * perUnit * standing;                  // realized+floating unchanged at cut; equity drops only on adverse move
     LossPath[i] = loss;
     if(loss>maxLoss) {maxLoss=loss; maxStep=i;}
    }
    //MaxLossPlanned = maxLoss;//MaxLossAtStep  = maxStep;
    return maxLoss;
   }
//----------------------
   bool Add_Level(double Level_New)
   {
    if(TimeCurrent()>Expiry) {Alert("This version expired on "+TimeToString(Expiry,TIME_DATE)+". Go to "+URL_Web+" to download the latest version."); ExpertRemove();}
  //if(!IsLicensed())        {Alert("Trial Expired"); return false;}
    if(Level_Count<Max_Seq_Levels && Trades_Count<Max_Seq_Trades)
    {
     //if(StopOut_Flag || Sequence_pause_Flag) return false;
     if(Virtual && Level_Count==Delay_Trade && ((dir==OP_BUY&&!Seq_Buy.Active) || (dir==OP_SELL&&!Seq_Sell.Active)))
     {
      bool ret=false;
      if     (dir==OP_BUY &&MustCheck_Buy)   ret=Seq_Buy.Add_Level(ask);
      else if(dir==OP_SELL&&MustCheck_Sell)  ret=Seq_Sell.Add_Level(bid);
      if(ret) End_Sequence("Real Sequence Start");
      return false;
     }
     // Locking levels; is this active and traded ? 
     if(Size_Grid==1234.5) Size_Grid = GetSize(GRID);
     if(Size_Lock==1234.5) Size_Lock = GetSize(LOCK);
     if(Size_TP  ==1234.5) Size_TP   = GetSize(OP_TP);
     if(Size_SL  ==1234.5) Size_SL   = GetSize(OP_SL);
     if(Size_TSL ==1234.5) Size_TSL  = GetSize(TSL);

     bool   hadPriorLevel = (Level_Count>0);
     double prevLevel     = Level_Last;
     
     double Lots_Calc=0.0; double Lots_Delayed=0.0;
     
     if(Level_Count==0)
     {
           if(Mode_Lots==FixedLots)      Lots_Calc = StartLots = Lots;
      else if(Mode_Lots==ScaledLots)     Lots_Calc = StartLots = Lots*AccountInfoDouble(ACCOUNT_EQUITY)/1000;
    //else if(Mode_Lots==PercentageRisk) {return (Risk*0.01*AccountInfoDouble(ACCOUNT_EQUITY))/((Size_SL/_Point)*SymbolInfoDouble(Symbol(),SYMBOL_TRADE_TICK_VALUE));}
      else if(Mode_Lots==RiskperSeq)     Lots_Calc = StartLots = SolveStartLotsByRisk(Risk);
      
      BuildRawLots(StartLots); ScaleRawLots(); BuildNormalizedLots();
     }
   //else {Lots_Calc = TradeLevels[Level_Count-1].lots*Lots_Exponent;}//TradeLevels[0].lots*(MathPow(Lot_Exponent,Level_Count));
     else
     {
      if(Mode_Lots_Prog==Lots_Prog_CumPartial) Lots_Calc = CalcNextLotsCumPartial();
      else
      {
       //if(Level_Count>=ArraySize(LotsNorm)) Level_Count=ArraySize(LotsNorm)-1;
       int idx = MathMin(Level_Count, ArraySize(LotsNorm)-1);
     //Lots_Calc = LotsNorm[Level_Count];//Level_Lots(Level_Count);
       Lots_Calc = LotsNorm[idx];
      }
     }
     Lots_Calc = NormalizedLots(Lots_Calc);
     //Print("Level="+(Level_Count+1)+" LotsCalc="+DoubleToString(Lots_Calc,3)+" ");
     string Desc_lvl = Desc+" Lvl "+IntegerToString(Level_Count+1,2,'0');
     //-----------------------------------------------------------------
     //  UNWIND branch  – negative lot triggers partial close
     if(Lots_Calc<0.0 && MathAbs(Lots_Calc)>=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN))
     {
      double lotsToCut = MathAbs(Lots_Calc);
      if(closeLots(lotsToCut))                                  //  partial close
      {
       //  write a *virtual* level so VWAP in UpdateLockTPSL stays correct
       Trades_Count++;
       //BuildTradeLevels();
       Level_Count = ArrayResize(TradeLevels,Level_Count+1,Max_Seq_Levels);
       TradeLevels[Level_Count-1].price_level = Level_Last = Level_New;
       TradeLevels[Level_Count-1].price_trade = 0.0;           // no last open
     //TradeLevels[Level_Count-1].lots        = Lots_Calc;     // negative
       TradeLevels[Level_Count-1].sl          = 0.0;
       TradeLevels[Level_Count-1].tp          = 0.0;
       TradeLevels[Level_Count-1].ticket      = 0;             // virtual tag
       UpdateLockTPSL(Trades_Count);                           // refresh Lock/TP/SL
       HLineCreate(0,Desc_lvl,0,Level_New,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DOT,1,true,false,false,0);
       Print(Desc_lvl,": Price=",DoubleToString(Level_New,Digits())," Partial‑Closed Lot=",DoubleToString(lotsToCut,2));
       return true;
      }
      else return false;
     }
     //-----------------------------------------------------------------
     // virtual delayed lots
     if(!Virtual && !Traded && Delay_Lots_Add && Level_Count==MathAbs(Delay_Trade_Live) && Level_Count>0 && Lots_Calc>0)
     {
      for(int i=0;i<Level_Count;i++) Lots_Delayed += TradeLevels[i].lots;
                                     Lots_Delayed += Lots_Calc;
    //if(!Delay_Lots_Add)            Lots_Delayed  = Lots_Calc;
     }
     //-----------------------------------------------------------------
     if(!Virtual && Level_Count>=MathAbs(Delay_Trade_Live))
     { //int oppDir = (dir == OP_BUY) ? POSITION_TYPE_SELL : POSITION_TYPE_BUY;
     double LotsToBeSent=(Lots_Calc>0)?MathMax(Lots_Calc,Lots_Delayed):Lots_Calc;
      if(Mode_Lots_Prog==Lots_Prog_CumPartial && MathAbs(LotsToBeSent)<SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN))
      {
       Print(Desc_lvl,": CumPartial next lots below broker minimum");
       return false;
      }
      
      if(LotsToBeSent>(Lots_Max*StartLots) && Lots_Max>0.01) LotsToBeSent=Lots_Max*StartLots;
      
      if(OpenPosition(dir,MAGIC1,LotsToBeSent,Level_SL,Size_SL,Size_TP,Desc_lvl))
       {
        if(!Active) Print(Desc+" Sequence Started @ "+DoubleToString(Level_New,_Digits));
        if(!Traded) {Sequences++; }//FirstTradeEquity=AccountInfoDouble(ACCOUNT_EQUITY);}
        Active=Traded=true; Trades_Count++;
        Level_Count = ArrayResize(TradeLevels,Level_Count+1,Max_Seq_Levels);
        TradeLevels[Level_Count-1].price_level = Level_Last = Level_New;
        TradeLevels[Level_Count-1].price_trade = LastOpen;
        TradeLevels[Level_Count-1].lots        = Lots_Order;//Lots_Calc;//GetNormalizedLots(Lots_Calc);     // Max Lots issue solved
        TradeLevels[Level_Count-1].sl          = Level_SL = LastSL;
        TradeLevels[Level_Count-1].tp          = LastTP;
        TradeLevels[Level_Count-1].ticket      = LastOrderTicket;
        if(Mode_Lots_Prog==Lots_Prog_CumPartial && hadPriorLevel && !Retrace_Triggered) Level_Retrace = prevLevel;
        //Sleep(1000);
        UpdateLockTPSL(Trades_Count);
        HLineCreate(0,Desc_lvl,0,Level_New,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DOT,1,true,false,false,0);
        Print(Desc_lvl,": Price=",DoubleToString(Level_New,Digits())," Lots=",DoubleToString(Lots_Order,2),"/",DoubleToString(MathMax(Lots_Calc,Lots_Delayed),2)," Filled");
        return true;
       }
       else {Print(Desc_lvl,": Price=",DoubleToString(Level_New,_Digits)," Lots=",DoubleToString(Lots_Order,2),"/",DoubleToString(MathMax(Lots_Calc,Lots_Delayed),2)
                           ," Failed. Return Code:",LastRetCode," ID:",GetRetcodeID(LastRetCode)); return false;}
     }
     else
     {
      if(Mode_Lots_Prog==Lots_Prog_CumPartial && MathAbs(Lots_Calc)<SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN))
      {
       Print(Desc_lvl,": CumPartial next lots below broker minimum");
       return false;
      }
      if(!Active) Print(Desc+" Sequence Started @ "+DoubleToString(Level_New,_Digits));
      Active=true;
      Level_Count = ArrayResize(TradeLevels,Level_Count+1,Max_Seq_Levels);
      TradeLevels[Level_Count-1].price_level = Level_Last = Level_New;
      TradeLevels[Level_Count-1].price_trade = 0.0;
      TradeLevels[Level_Count-1].lots        = Lots_Calc;//GetNormalizedLots(Lots_Calc);
    //TradeLevels[Level_Count-1].sl          = 0.0;
      TradeLevels[Level_Count-1].tp          = (dir==OP_BUY)?NormalizeDouble(ask+Size_TP,_Digits):NormalizeDouble(bid-Size_TP,_Digits);
      if(Mode_Lots_Prog==Lots_Prog_CumPartial && hadPriorLevel && !Retrace_Triggered) Level_Retrace = prevLevel;
      UpdateLockTPSL();
      HLineCreate(0,Desc_lvl,0,Level_New,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DOT,1,true,false,false,0);
      Print(Desc_lvl,": Price=",DoubleToString(Level_New,_Digits)," Lots=",DoubleToString(Lots_Calc,2),(Virtual?" Virtual":" Delayed"));
      return true;
     }
    }
    else
    {
     if(CloseAtMaxLevels && !Virtual)
     {
      CloseAllPositions(dir,MAGIC1);
      int Trades=FindNumberOfPositions(dir,MAGIC1);
      if(Trades==0) End_Sequence("Sequence Closed: Max Levels/Trades reached");
     }
    }
    return false;
   }
//----------------------
   void UpdateLockTPSL(int count=0)
   {
    Level_Lock=Level_TP=Level_Entry=LotsTotal=0.0;
    double Lock_Factor=1;
    if(count>0 && Lock_Profit_Flexibility<1.0)
    {
     Lock_Factor = 1-(1-Lock_Profit_Flexibility)*((double)count/(double)Max_Seq_Trades);
     Lock_Factor = 1-(1-Lock_Profit_Flexibility)*MathPow(((double)count/(double)Max_Seq_Trades),2);
    }
    //Comment(Lock_Factor);
    for(int i=0; i<Level_Count; i++)
    {
     if(1)//PositionSelectByTicket(TradeLevels[i].ticket))
     {
      //if(dir==OP_BUY){
      //Level_Lock += TradeLevels[i].lots * (TradeLevels[i].price_level + Size_Lock*Lock_Factor);
                                          //(TradeLevels[i].price_level + Size_TP);}
      //Level_TP   += TradeLevels[i].lots * (TradeLevels[i].tp);}
      //if(dir==OP_SELL){
      //Level_Lock += TradeLevels[i].lots * (TradeLevels[i].price_level - Size_Lock*Lock_Factor);
                                          //(TradeLevels[i].price_level - Size_TP);}
      //Level_TP   += TradeLevels[i].lots * (TradeLevels[i].tp);}
      if(TradeLevels[i].lots <= 0.0)     continue;   // skip buried/closed levels
      Level_Entry+= TradeLevels[i].lots * (TradeLevels[i].price_level);
      LotsTotal  += TradeLevels[i].lots;
      //Print("Level="+i+" Lots="+DoubleToString(TradeLevels[i].lots,3)+" "+DoubleToString(TradeLevels[i].lots * (TradeLevels[i].price_level),2));
     }
    }
    if(LotsTotal <= 0.0)   return;      // nothing active → early exit
    Level_Entry /= LotsTotal;
    
    HLineCreate(0,Desc+" CumulativePrice",0,Level_Entry,clrAqua,STYLE_DASHDOT,1,false,false,false,0);
    //------------
    if(Size_Lock!=0)
    {
     //Level_Lock /= LotsTotal;
     if     (dir==OP_BUY)  Level_Lock = Level_Entry + Size_Lock*Lock_Factor;
     else if(dir==OP_SELL) Level_Lock = Level_Entry - Size_Lock*Lock_Factor;
     Level_Lock = NormalizeDouble(Level_Lock,_Digits);
     //Print("Level_Entry="+DoubleToString(Level_Entry,_Digits)+" Lock="+Level_Lock+" SizeLock="+DoubleToString(Size_Lock*Lock_Factor,2));
     HLineCreate(0,Desc+" LockLine",0,Level_Lock,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_SOLID,1,false,false,false,0);
    }
    else
    {
     if     (dir==OP_BUY)  Level_Lock=999999;
     else if(dir==OP_SELL) Level_Lock=0;
    }
    //------------
    if(Size_TP!=0)
    {
     //Level_TP   /= LotsTotal;
     if     (dir==OP_BUY)  Level_TP = Level_Entry + Size_TP;
     else if(dir==OP_SELL) Level_TP = Level_Entry - Size_TP;
     Level_TP   = NormalizeDouble(Level_TP,_Digits);
     if(!Virtual && (!Traded||Mode_Operation==Operation_Standard))
                                               HLineCreate(0,Desc+" TPLine",0,Level_TP,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DASH,1,false,false,false,0);
     else {if(ObjectFind(0,Desc+" TPLine")>=0) HLineDelete(0,Desc+" TPLine");}
    }
    else
    {
     if     (dir==OP_BUY)  Level_TP=999999;
     else if(dir==OP_SELL) Level_TP=0;
    }
    //------------
    if(Size_SL!=0)
    {
     //Level_SL   /= LotsTotal;
     if     (dir==OP_BUY)  Level_SL = Level_Entry - Size_SL;
     else if(dir==OP_SELL) Level_SL = Level_Entry + Size_SL;
     Level_SL   = NormalizeDouble(Level_SL,_Digits);
     if(!Virtual && (!Traded||Mode_Operation==Operation_Standard))
                                               HLineCreate(0,Desc+" SLLine",0,Level_SL,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DASHDOT,1,false,false,false,0);
     else {if(ObjectFind(0,Desc+" SLLine")>=0) HLineDelete(0,Desc+" SLLine");}
    }
    //------------
    if(Traded)
    {
     CTrade Trade;
     for(int i=0; i<Level_Count; i++)
     {
      double Level_TP_ = (Level_TP==999999)?0:Level_TP;
      if(PositionSelectByTicket(TradeLevels[i].ticket) && (PositionGetDouble(POSITION_TP)!=Level_TP_||PositionGetDouble(POSITION_SL)!=Level_SL) )
      {
       if(!Trade.PositionModify(TradeLevels[i].ticket,Level_SL,Level_TP_)) TPmodifyErrors++; TPSLmodifieds++;
      }
     }
    }
   }
//----------------------
   void UpdateLock()
   {
    Level_Lock=LotsTotal=0.0;
    
    for(int i=0; i<Level_Count; i++)
    {
     if(dir==OP_BUY)    Level_Lock += TradeLevels[i].lots * (TradeLevels[i].price_level + GetSize(LOCK));
     if(dir==OP_SELL)   Level_Lock += TradeLevels[i].lots * (TradeLevels[i].price_level - GetSize(LOCK));
     
     LotsTotal += TradeLevels[i].lots;
    }
    if(LotsTotal <= 0.0) {Alert("ERROR: LotsTotal==0 in UpdateLock()"); return;}
    Level_Lock /= LotsTotal; Level_Lock = NormalizeDouble(Level_Lock,_Digits);
    
    HLineCreate(0,Desc+" LockLine",0,Level_Lock,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_SOLID,1,false,false,false,0);
   }
//----------------------
   void TrailingStoploss()
   {
    CTrade Trade;
    double SL;
    int MIN_SL_DELTA=5, MIN_SPLVL=(int)MathMax((long)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),(long)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL));
    MIN_SPLVL=MathMax(MIN_SPLVL,1); // atleast 1 point to avoid boundary errors
    //double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    for(int i=0; i<Level_Count; i++)
    {
     if(dir==OP_BUY)
     {
      if(Virtual && TSL_Size_<0) SL = NormalizeDouble(bid-GetSize(TSL),_Digits);
      else                       SL = NormalizeDouble(bid-Size_TSL,_Digits);

      if(Level_TSL==0.0 || (Level_TSL!=0.0&&SL>=Level_TSL)) {Level_TSL=SL; Trailing=true;}

      if(Traded && PositionSelectByTicket(TradeLevels[i].ticket))
      {
       double currSL=PositionGetDouble(POSITION_SL);
       // clamp to nearest legal on every adjustment
       double legal = NormalizeDouble(bid-MIN_SPLVL*_Point,_Digits);
       if(SL > legal) SL = legal;
       // min movement threshold
       double minStep = MathMax(0.0001*bid,MIN_SL_DELTA*_Point);
       // after clamping, "is SL on the legal side" is guaranteed; no need to re-check it
       if(currSL==0.0 || (SL>currSL && (SL-currSL)>=minStep))
       {
        if(!Trade.PositionModify(TradeLevels[i].ticket,SL,PositionGetDouble(POSITION_TP)))
        {TSLmodifyErrors++; PrintFormat("TSL BUY modify failed: ticket=%I64u newSL=%.6f ret=%d (%s)",TradeLevels[i].ticket,DoubleToString(SL,Digits()),Trade.ResultRetcode(),Trade.ResultRetcodeDescription());} TSLmodifieds++;
       }
       else PrintFormat("TSL BUY skipped: ticket=%I64u currSL=%.6f newSL=%.6f",TradeLevels[i].ticket,DoubleToString(currSL,Digits()),DoubleToString(SL,Digits()));
      }
     }
     if(dir==OP_SELL)
     {
      if(Virtual && TSL_Size_<0) SL = NormalizeDouble(ask+GetSize(TSL),_Digits);
      else                       SL = NormalizeDouble(ask+Size_TSL,_Digits);

      if(Level_TSL==0.0 || (Level_TSL!=0.0&&SL<=Level_TSL)) {Level_TSL=SL; Trailing=true;}

      if(Traded && PositionSelectByTicket(TradeLevels[i].ticket))
      {
       double currSL=PositionGetDouble(POSITION_SL);
       // clamp to nearest legal on every adjustment
       double legal = NormalizeDouble(ask+MIN_SPLVL*_Point,_Digits);
       if(SL < legal) SL = legal;
       // min movement threshold
       double minStep = MathMax(0.0001*ask,MIN_SL_DELTA*_Point);
       // after clamping, "is SL on the legal side" is guaranteed; no need to re-check it
       if(currSL==0.0 || (SL<currSL && (currSL-SL)>=minStep))
       {
        if(!Trade.PositionModify(TradeLevels[i].ticket,SL,PositionGetDouble(POSITION_TP)))
        {TSLmodifyErrors++; PrintFormat("TSL SELL modify failed: ticket=%I64u newSL=%.6f ret=%d (%s)",TradeLevels[i].ticket,SL,Trade.ResultRetcode(),Trade.ResultRetcodeDescription());} TSLmodifieds++;
       }
       else PrintFormat("TSL SELL skipped: ticket=%I64u currSL=%.6f newSL=%.6f",TradeLevels[i].ticket,currSL,SL);
      }
     }
    }
    if((!Traded||Mode_Operation==Operation_Standard) && Level_TSL!=0) HLineCreate(0,Desc+" TSL_Level",0,Level_TSL,(dir==OP_BUY)?clrBlue:C'225,68,29',STYLE_DASHDOT,1,false,false,false,0);
   }
//------------------------------------------------------------------
//  SmartVolumeShrink v3 – ticket-only, cache-free,  minimises server requests (netting or hedging)
//------------------------------------------------------------------
   bool closeLots(double lotsReq)
   {
      const double VolMin  = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      const double VolStep = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   
      lotsReq = MathFloor((lotsReq + VolStep*0.5) / VolStep) * VolStep;
      if(lotsReq < VolMin - 1e-9) return true;
   
      CTrade tr;
      int     safety = 64;
   
      while(lotsReq >= VolMin - 1e-9 && safety-- > 0)
      {
         ulong pickTk  = 0;  double pickVol = 0.0;  int pickIdx = -1;
   
         for(int i = 0; i < Level_Count; i++)
         {
            ulong tk = (ulong)TradeLevels[i].ticket;   if(tk == 0) continue;
            if(!PositionSelectByTicket(tk)) { TradeLevels[i].lots = 0.0; TradeLevels[i].ticket = 0; continue; }
            double v = PositionGetDouble(POSITION_VOLUME);
            if(MathAbs(v - lotsReq) < VolStep*0.5) { pickTk=tk; pickVol=v; pickIdx=i; break; }
         }
         if(pickTk == 0)
         {
            double bestDiff = DBL_MAX;
            for(int i = 0; i < Level_Count; i++)
            {
               ulong tk = (ulong)TradeLevels[i].ticket;   if(tk == 0) continue;
               if(!PositionSelectByTicket(tk)) { TradeLevels[i].lots = 0.0; TradeLevels[i].ticket = 0; continue; }
               double v = PositionGetDouble(POSITION_VOLUME);
               double d = v - lotsReq;
               if(d >= 0.0 && d < bestDiff) { bestDiff=d; pickTk=tk; pickVol=v; pickIdx=i; }
            }
         }
         if(pickTk == 0)
         {
            for(int i = 0; i < Level_Count; i++)
            {
               ulong tk = (ulong)TradeLevels[i].ticket;   if(tk == 0) continue;
               if(!PositionSelectByTicket(tk)) { TradeLevels[i].lots = 0.0; TradeLevels[i].ticket = 0; continue; }
               double v = PositionGetDouble(POSITION_VOLUME);
               if(v > pickVol) { pickTk=tk; pickVol=v; pickIdx=i; }
            }
         }
         if(pickTk == 0) break;
   
         double volCut   = MathMin(lotsReq, pickVol);
                volCut   = MathFloor((volCut + VolStep*0.5) / VolStep) * VolStep;
         bool   fullClose = (pickVol - volCut) < VolMin + 1e-9;
         if(volCut < VolMin - 1e-9) { fullClose=true; volCut=pickVol; }
         Pclosed++;
         bool ok = fullClose ? tr.PositionClose(pickTk)
                             : tr.PositionClosePartial(pickTk, volCut);
         if(!ok) {PcloseErrors++; Print("Close error ",_LastError); return false; }
   
         lotsReq -= fullClose ? pickVol : volCut;

         if(pickIdx >= 0)
         {
          double liveVol = 0.0;
          if(!fullClose && PositionSelectByTicket(pickTk)) liveVol = PositionGetDouble(POSITION_VOLUME);
          else if(!fullClose)                              liveVol = MathMax(0.0,pickVol-volCut);

          TradeLevels[pickIdx].lots = liveVol;
          if(fullClose || liveVol < VolMin - 1e-9)
          {
           TradeLevels[pickIdx].lots   = 0.0;
           TradeLevels[pickIdx].ticket = 0;
          }
         }
      }
      RefreshTicketLots();
      return (lotsReq < VolMin - 1e-9);
   }
//------------------------------------------------------------------
   bool closeLots2(double lotsReq)
   {
      const double VolMin  = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      const double VolStep = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   
      if(lotsReq < VolMin - 1e-9) return true;          // nothing to do
      lotsReq  = MathFloor(lotsReq / VolStep) * VolStep;
      CTrade tr;
      while(lotsReq >= VolMin - 1e-9)
      {
         // --- locate largest remaining ticket -----------------------------
         int    idx     = -1;
         double maxLot  = 0.0;
         for(int i=0;i<Level_Count;i++)
            if(TradeLevels[i].ticket > 0 && TradeLevels[i].lots > maxLot)
                  { maxLot = TradeLevels[i].lots; idx = i; }
   
         if(idx == -1) break;                           // no more tickets
   
         ulong   tk       = TradeLevels[idx].ticket;
         double  volPos   = PositionSelectByTicket(tk) ? PositionGetDouble(POSITION_VOLUME) : 0.0;
         double  volCut   = MathMin(maxLot , lotsReq);
         volCut           = MathFloor(volCut / VolStep) * VolStep;
         // safeguard: if the remaining volume after cut would fall *below* the broker’s minimum,
         // simply close the position instead of leaving an unusable stub.
         bool fullClose = (volPos - volCut) < VolMin + 1e-9;
         Pclosed++;
         bool ok = fullClose ? tr.PositionClose(tk) : tr.PositionClosePartial(tk, volCut); // one server hit, ticket gone
   
         if(!ok) { PcloseErrors++; Print("Close error ",_LastError); return false; }
         
         lotsReq -= fullClose ? volPos : volCut;         // how much net volume still to cut?
         // house‑keeping ----------------------------------------------------
         TradeLevels[idx].lots -= fullClose ? volPos : volCut;
         if(fullClose || TradeLevels[idx].lots < VolMin - 1e-9)
         {
            TradeLevels[idx].lots   = 0.0;
            TradeLevels[idx].ticket = 0;                 // mark as closed so Trailing SL ignores it
         }
      }
      //CleanClosedLevels();
      return (lotsReq < VolMin - 1e-9);                  // true = achieved requested reduction
   }
//------------------------------------------------------------------
//  CleanClosedLevels – purges buried (≤0‑lot) or ticket‑less records
   void CleanClosedLevels()
   {
      int newCount = 0;
      for(int i = 0; i < Level_Count; i++)
      {
         if(TradeLevels[i].lots > 0.0 && TradeLevels[i].ticket != 0)  // keep only standing volume
         {
            if(newCount != i) TradeLevels[newCount] = TradeLevels[i];
            newCount++;
         }
      }
      Level_Count = ArrayResize(TradeLevels,newCount,Max_Seq_Levels);
      // recalc quick helpers
      //Trades_Count = 0;
      //for(int k = 0; k < newCount; k++) if(TradeLevels[k].ticket > 0) Trades_Count++;
      //if(newCount > 0)   Level_Last = TradeLevels[newCount-1].price_level;
      //else              {Level_Last = 0.0; Active = false;}
   }
//------------------------------------------------------------------
//--- Re-scan live positions and sync stored volumes ------------------------
   void BuildTradeLevels()
   {
      const double VolMin = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   
      for(int i = 0; i < Level_Count; i++)
      {
         ulong tk = TradeLevels[i].ticket;
         // 1) ticket missing OR position closed  → mark as buried
         if(tk == 0 || !PositionSelectByTicket(tk))
         {
            TradeLevels[i].lots = -MathAbs(TradeLevels[i].lots);
            continue;
         }
         // 2) position still open – copy its current size
         double vol = PositionGetDouble(POSITION_VOLUME);
         // if, for any reason, standing volume is effectively zero, also bury
         TradeLevels[i].lots = (vol >= VolMin - 1e-9) ? vol: -MathAbs(TradeLevels[i].lots);
      }
   }
//----------------------
  };
//----------------------------------------------------------------------------------------------------------------------------------------------------
SEQUENCE       Seq_Buy,Seq_Sell,Seq_Buy_Virtual,Seq_Sell_Virtual;
CPositionInfo  m_position;       // object of CPositionInfo class
COrderInfo     m_order;          // object of COrderInfo class
//----------------------------------------------------------------------------------------------------------------------------------------------------
int VerifyLicense(long AccNum,string AccName,string AccServer,bool init=false)
  {
   static datetime LastLicenseCheckTime;
   if(init) ShowPrompt("Validating License..."," ",URL_Web);
   
   string URL = URL_API+"/api/ea/check";
   //if(Key=="GOAT") URL += "/api/metatrader/check-id/goat";
   //else            URL += "/api/metatrader/check-id";
   string json_data = "{\"id\":\""+(string)AccNum+"\"}";             // Prepare JSON payload
 //if(AccNum<999999) json_data = "{\"id\":\"000"+(string)AccNum+"\"}";
 //int json_len = StringLen(json_data);                              // Prepare the post_data array
   char post_data[],result[];
 //ArrayResize(post_data, json_len + 1);                             // Resize the array to length+1 for null terminator
 //post_data[json_len] = '\0';                                       // Manually add null terminator
 //StringToCharArray(json_data, post_data, 0, json_len);             // Convert string to char array and ensure null termination
   StringToCharArray(json_data, post_data, 0, WHOLE_ARRAY,CP_UTF8);  // Convert string to char array and ensure null termination
   ArrayResize(post_data,ArraySize(post_data)-1);                    // Removing the last character, maybe null added automatically
 //Print("Post data:"+json_data);
   string result_headers;
   string x = "e9691e12e7eef5ceb1daa0559374c83d90248ba3165051f4d82670a7ad0928be";
   int res = WebRequest("POST", URL, requestHeaders+x+"161bd26578b6b1ab496e3b3fda393a39aa82cf4734bce5bc168d406248db9745\r\n", timeout, post_data, result, result_headers);
   Print("Response Code: ", res);
   if(res==-1)
   {
    Print("WebRequest failed: ", GetLastError());
    HidePrompt();
    if(MQLInfoInteger(MQL_VISUAL_MODE)) Print("For security purposes, visual testing mode is limited in features.");
    ShowPrompt("Connection not allowed!","Copy the URL below and add to"," Tools > Options > Experts > Allowed URLs.",URL_API);
    return res;
   }
   else if(res!=200&&res!=1003) Print("License check HTTP response "+(string)res+": "+CharArrayToString(result, 0, -1, CP_UTF8));
   HidePrompt();
   string response_text = CharArrayToString(result);
   //Print("Result Headers: ", result_headers);
   //return LICENSE_VALID;
   // --- New contract: HTTP 200 + "<id> - yes"  OR HTTP 200 + "no"
   if(res == 200)
   {
    if(StringFind(response_text, "yes") >= 0)
    {
     // keep compatibility with checks that look for ID in response
     if(StringFind(response_text, (string)AccNum) >= 0 || Key=="KID")
     {
      Print("License verified.");
      LastLicenseCheckTime=TimeCurrent();
      return LICENSE_VALID;
     }
    }
    if(StringFind(response_text, "no") >= 0)
    {
     Print("License not valid for this MT5 account.");
     ShowPrompt("Validation Failed!","Check your MT5 Acc# in your GOATedge client area.","Visit the URL below to buy or activate the GOAT EA.",URL_Web);
     return res;
    }
    // unexpected 200 body
    ShowPrompt("Validation Failed!","Unexpected response from server."," ",""); 
    return res;
   }
   if(res==400) {ShowPrompt("Bad Request","Missing/invalid MT5 account id (id)."," ",""); return res;}
   if(res==401) {ShowPrompt("Authorization Failed","Missing/invalid bearer token."," ",""); return res;}
   if(res==403) {ShowPrompt("Not Entitled","Account exists but is not entitled for EA."," ",""); return res;}
   if(res==503) {ShowPrompt("Server Auth Issue","Server auth token misconfiguration."," ",""); return res;}
   if(res==1001){ShowPrompt("No Connection!","Ensure your MT5 terminal is online and has stable internet.","GOAT EA requires an active connection to function properly.",""); return res;}
                 ShowPrompt("Validation Failed!","Unexpected HTTP status: "+(string)res,"","");
   return res;
  }
//+------------------------------------------------------------------+
bool IsVersionExpired()
  {
   if(TimeCurrent() > Expiry) return true;
   else                       return false;
   //if(MQLInfoInteger(MQL_TESTER))                                        {ObjectSetText("006","Acc. TradeMode : Tester",Font_Size,"NULL",clr_Text); return true;}
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO)
   {
    //ObjectSetText("006","Acc. TradeMode : Demo",Font_Size,"NULL",clr_Text);
    //ObjectSetText("011","Demo Acc. License",Font_Size,"NULL",clrGreen);
    //ObjectSetText("012","No Expiry",Font_Size,"NULL",clrGreen);
    return true;
   }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL)
   {
    //ObjectSetText("006","Acc. TradeMode : Real",Font_Size,"NULL",clr_Text);
    if(Licensed_Account_Number!=0 && AccountInfoInteger(ACCOUNT_LOGIN)!=Licensed_Account_Number)
    {
     Alert("Account Number is not Licensed"); ExpertRemove();
    }
    if(Licensed_Account_Title!="" && AccountInfoString(ACCOUNT_NAME)!=Licensed_Account_Title)
    {
     Alert("Account Name/Title is not Licensed"); ExpertRemove();
    }
    if(TimeCurrent() > Expiry)
    {
     Alert("License expired"); ExpertRemove();
    }
    //ObjectSetText("011","ACC. LICENSED",Font_Size,"NULL",clrGreen);
    //ObjectSetText("012","ACC. Expiry  : "+TimeToString(License_Expiry,TIME_DATE),Font_Size,"NULL",clrGreen);
    return true;
   }
   return false;
  }
//+------------------------------------------------------------------+
void ShowPrompt(string heading,string sub_heading,string sub_heading2,string text="")
  {
   if(FastSpeed_Flag) return;
   Sleep(20);
   int chartWidth  = (int)ChartGetInteger(ChartID(), CHART_WIDTH_IN_PIXELS);
   int chartHeight = (int)ChartGetInteger(ChartID(), CHART_HEIGHT_IN_PIXELS);
   int promptWidth=600,promptHeight=136;
   // Calculate top-left corner to center on screen
   int left = (chartWidth  - promptWidth ) / 2;
   int top  = (chartHeight - promptHeight) / 2;
   ObjectCreate    (ChartID(), "Prompt_Rect", OBJ_RECTANGLE_LABEL, 0, 0, 0);        Sleep(10);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_XDISTANCE, left);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_YDISTANCE, top);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_XSIZE,     promptWidth);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_YSIZE,     promptHeight);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_COLOR,        clrGray);       // border color
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_BORDER_COLOR, clrGray);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_BGCOLOR,      clrWhite);      // background
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_STYLE,        STYLE_SOLID);
   ObjectSetInteger(ChartID(), "Prompt_Rect", OBJPROP_WIDTH,        2);             // border thickness
   if(MAGIC1==0) EA_LOGO.Resize(128); //EA_LOGO.Resize(W.Width/6); //EA_LOGO._CreateCanvas(W.MouseX, W.MouseY);
   Sleep(10);
   EA_LOGO._CreateCanvas(left+4,top+4,"Prompt_Logo");  // _CreateCanvas is for resized logo
   Sleep(10);
 //EA_LOGO.BmpArrayFree();
   // Position the heading near the top, to the right of the logo
   int headingLeft = left + 128 + 20;                    // 10px margin + 64px logo + maybe 10 more pixels
   int headingTop  = top + 20;                           // 20px from top edge
   ObjectCreate    (ChartID(), "Prompt_Title", OBJ_LABEL, 0, 0, 0);                 Sleep(10);
   ObjectSetString (ChartID(), "Prompt_Title", OBJPROP_TEXT,      heading);
   ObjectSetInteger(ChartID(), "Prompt_Title", OBJPROP_XDISTANCE, headingLeft);
   ObjectSetInteger(ChartID(), "Prompt_Title", OBJPROP_YDISTANCE, headingTop);
   ObjectSetInteger(ChartID(), "Prompt_Title", OBJPROP_COLOR,     clrBlack);
   ObjectSetInteger(ChartID(), "Prompt_Title", OBJPROP_FONTSIZE,  MathMax(Font_Size+3,10));
   // Sub heading
   ObjectCreate    (ChartID(), "Prompt_Descp", OBJ_LABEL, 0, 0, 0);                 Sleep(10);
   ObjectSetString (ChartID(), "Prompt_Descp", OBJPROP_TEXT,      sub_heading);
   ObjectSetInteger(ChartID(), "Prompt_Descp", OBJPROP_XDISTANCE, headingLeft);
   ObjectSetInteger(ChartID(), "Prompt_Descp", OBJPROP_YDISTANCE, headingTop+35);
   ObjectSetInteger(ChartID(), "Prompt_Descp", OBJPROP_COLOR,     clrBlack);
   ObjectSetInteger(ChartID(), "Prompt_Descp", OBJPROP_FONTSIZE,  MathMax(Font_Size+1,8));
   // Sub heading2
   ObjectCreate    (ChartID(), "Prompt_Descp2", OBJ_LABEL, 0, 0, 0);                Sleep(10);
   ObjectSetString (ChartID(), "Prompt_Descp2", OBJPROP_TEXT,      sub_heading2);
   ObjectSetInteger(ChartID(), "Prompt_Descp2", OBJPROP_XDISTANCE, headingLeft);
   ObjectSetInteger(ChartID(), "Prompt_Descp2", OBJPROP_YDISTANCE, headingTop+55);
   ObjectSetInteger(ChartID(), "Prompt_Descp2", OBJPROP_COLOR,     clrBlack);
   ObjectSetInteger(ChartID(), "Prompt_Descp2", OBJPROP_FONTSIZE, MathMax(Font_Size+1,8));
   if(text != ""){
   int editBoxTop  = top + promptHeight - 30;       // 40 px from bottom edge
   ObjectCreate    (ChartID(), "Prompt_Edit", OBJ_EDIT, 0, 0, 0);                   Sleep(10);
   ObjectSetString (ChartID(), "Prompt_Edit", OBJPROP_TEXT, text);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_XDISTANCE, headingLeft);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_YDISTANCE, editBoxTop);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_XSIZE,     400);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_YSIZE,     20);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_COLOR,     clrBlack);  // text color
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_BGCOLOR,   clrWhite);  // background
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_BORDER_COLOR, clrBlack);
   ObjectSetInteger(ChartID(), "Prompt_Edit", OBJPROP_FONTSIZE,  MathMax(Font_Size+0,7));
 //ObjectSetInteger(ChartID(), "Prompt_Descp", OBJPROP_READONLY,  true);
   }
   Sleep(20); ChartRedraw(); Sleep(50);
  }
//+------------------------------------------------------------------+
void HidePrompt()
  {
   ObjectDelete(ChartID(), "Prompt_Rect");   Sleep(10);
   ObjectDelete(ChartID(), "Prompt_Logo");   Sleep(10);
   ObjectDelete(ChartID(), "Prompt_Title");  Sleep(10);
   ObjectDelete(ChartID(), "Prompt_Descp");  Sleep(10);
   ObjectDelete(ChartID(), "Prompt_Descp2"); Sleep(10);
   ObjectDelete(ChartID(), "Prompt_Edit");   Sleep(10);
   ChartRedraw();                            Sleep(10);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void DashboardBusSendStatus(const string status)
  {
   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return;
   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))   return;
   if(!GlobalVariableCheck("Dashboard_ChartID"))                         return;

   long dashboard_cid=(long)GlobalVariableGet("Dashboard_ChartID");
   if(dashboard_cid<=0) return;

   EventChartCustom(dashboard_cid,GOAT_EVENT_CHILD_STATUS,(long)MAGIC1,(double)ChartID(),Symbol()+"|"+status);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void DashboardBusRollClosedBuckets(const datetime now_time)
  {
   datetime day_start=GoatBrokerDayStart(now_time);
   datetime week_start=GoatBrokerWeekStart(now_time);

   if(DashboardBusWeekStart==0 || week_start>DashboardBusWeekStart)
      DashboardBusClosedPLWeekly=0.0;
   if(DashboardBusDayStart==0 || day_start>DashboardBusDayStart)
      DashboardBusClosedPLDaily=0.0;

   DashboardBusWeekStart=week_start;
   DashboardBusDayStart=day_start;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void DashboardBusRebuildClosedStats(void)
  {
   datetime now=TimeCurrent();
   DashboardBusDayStart=GoatBrokerDayStart(now);
   DashboardBusWeekStart=GoatBrokerWeekStart(now);
   DashboardBusClosedPLDaily=0.0;
   DashboardBusClosedPLWeekly=0.0;
   DashboardBusClosedPLTotal=0.0;
   DashboardBusClosedTradesTotal=0;

   if(!HistorySelect(0,now)) return;
   int total=HistoryDealsTotal();

   for(int i=0;i<total;++i)
   {
      ulong ticket=HistoryDealGetTicket(i);
      if(ticket==0)                                              continue;
      if(HistoryDealGetString(ticket,DEAL_SYMBOL)!=_Symbol)      continue;
      if(HistoryDealGetInteger(ticket,DEAL_MAGIC)!=MAGIC1)       continue;

      long entry=HistoryDealGetInteger(ticket,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY)      continue;

      long type=HistoryDealGetInteger(ticket,DEAL_TYPE);
      if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL)            continue;

      double closed_pl=HistoryDealGetDouble(ticket,DEAL_PROFIT)
                      +HistoryDealGetDouble(ticket,DEAL_COMMISSION)
                      +HistoryDealGetDouble(ticket,DEAL_SWAP);
      datetime close_time=(datetime)HistoryDealGetInteger(ticket,DEAL_TIME);

      DashboardBusClosedPLTotal+=closed_pl;
      DashboardBusClosedTradesTotal++;
      if(close_time>=DashboardBusDayStart)  DashboardBusClosedPLDaily +=closed_pl;
      if(close_time>=DashboardBusWeekStart) DashboardBusClosedPLWeekly+=closed_pl;
   }
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int OnInit()
  {
   Print("================"+Server+"-"+EA_Name+" ("+Symbol()+") Initialization Start"+"================");
 //string summary = GenerateOptimizationSummary(Key+"\\"+EA_Name+"-"+Server+"\\GOAT Batch Queue."+Key, Key+"\\"+EA_Name+"-"+Server+"\\log."+Key);
 //int ret=MessageBox("Batch Summary:\n\n"+summary+"\n\nDo you want to open logs?","Batch Complete...",MB_OKCANCEL);
   ulong lastMScount=GetMicrosecondCount();
   uint  lastTickcount=GetTickCount();
   //ulongTime = GetTickCount64();
   string EA_Name_generated=Key+" V"+version_;
   if(EA_Name!=EA_Name_generated) {Alert("Name Mismatch: The Bot/EA cannot be renamed due to security reasons. Internal Name="+EA_Name_generated+" File Name="+EA_Name); ExpertRemove();}
   //ResourceCreate(abc,"abc.csv");
   //ChartSetSymbolPeriod(ChartID(),Symbol(),PERIOD_M1);
   EventSetTimer(1);
   string names[], values[];
   Strat = ExtractFunctionKeysFromInputString(EA_Desc,names,values);
   _Symbol_ = ConvertToGOATsymbol(_Symbol); Print("Symbol="+_Symbol+" GOAT_Symbol="+_Symbol_);
   
   for(int i=0;i<ArraySize(names);i++)
   {
    string v=values[i];
    if(StringFind(names[i],"mode")!=-1||StringFind(names[i],"Mode")!=-1||StringFind(names[i],"MODE")!=-1) Mode=v;
   }
   if(Mode=="EXPORT")
   {
    Print("GOAT Mode found: "+Mode);
    // --- Examples: MQL5 built-in conversion compatibility ---
    for(int i=0;i<ArraySize(names);i++)
    {
     //Print("KV => '",names[i],"' = '",values[i],"'");
     if(names[i]=="dt_BOOS_end")
     {
      dt_Back_OOS = StringToTime(values[i]); Print("dt_BOOS_end:",TimeToString(dt_Back_OOS,TIME_DATE));
     }
     if(names[i]=="dt_FOOS_start")
     {
      dt_Fwrd_OOS = StringToTime(values[i]); Print("dt_FOOS_start:",TimeToString(dt_Fwrd_OOS,TIME_DATE));
     }
    }
    if(MQLInfoInteger(MQL_TESTER))
    {
     if(dt_Back_OOS!=0 && dt_Back_OOS<TimeCurrent()) {Print("EXPORT: dt_BOOS_end:"  +TimeToString(dt_Back_OOS,TIME_DATE)+" must be after test start date"); return(INIT_PARAMETERS_INCORRECT);}
     if(dt_Fwrd_OOS!=0 && dt_Fwrd_OOS<TimeCurrent()) {Print("EXPORT: dt_FOOS_start:"+TimeToString(dt_Fwrd_OOS,TIME_DATE)+" must be after test start date"); return(INIT_PARAMETERS_INCORRECT);}
     if(dt_Back_OOS!=0 && dt_Fwrd_OOS!=0 && dt_Fwrd_OOS<=dt_Back_OOS) {Print("EXPORT: dt_FOOS_start:"+TimeToString(dt_Fwrd_OOS,TIME_DATE)+" must be after dt_BOOS_end"); return(INIT_PARAMETERS_INCORRECT);}
    }
   }
   else if(Mode=="") Strat=EA_Desc; Print("Strategy: "+Strat);
   
   if(Mode_Trade==Long_and_Short || Mode_Trade==Long)  Buy_EN=true;     else Buy_EN=false;
   if(Mode_Trade==Long_and_Short || Mode_Trade==Short) Sell_EN=true;    else Sell_EN=false;
//-------------------------------------------------------------------------
   do Sleep(20); while(TimeToString(TimeCurrent())=="");
   if(TimeCurrent()>Expiry) {Alert("This version expired on "+TimeToString(Expiry,TIME_DATE)+". Go to "+URL_Web+" to download the latest version."); return INIT_FAILED; ExpertRemove();}
//-------------------------------------------------------------------------
   if(Mode_Download==Download_News||Mode_Download==Download_NewsBias)
   {
    if(!MQLInfoInteger(MQL_TESTER)&&!MQLInfoInteger(MQL_OPTIMIZATION)&&!MQLInfoInteger(MQL_FORWARD))
    {
     string nf = NEWS_FILE;//Key+"\\"+Download_News_FileName + ".csv";
     News.Key_=Key;
     if(FileIsExist(nf, FILE_COMMON))
       {
        int ret = MessageBox("High impact news history will download and overwrite the file "+nf+" in Terminal/Common/File folder. Continue ?","Download News File",MB_OKCANCEL);
        if(ret==IDOK) News.BacktestNewsFileDownloader(Download_StartDate);
        else          Alert("News History downloading cancelled");
       }
     else            {News.BacktestNewsFileDownloader(Download_StartDate);}
    }
    else Alert("News History download is not allowed in this mode");
    if(Mode_Download!=Download_NewsBias) ExpertRemove();
   }
   if(Mode_Download==Download_Bias||Mode_Download==Download_NewsBias)
   {
    if(!MQLInfoInteger(MQL_TESTER)&&!MQLInfoInteger(MQL_OPTIMIZATION)&&!MQLInfoInteger(MQL_FORWARD))
    {
     string bf = BIAS_FILE+Symbol()+".csv";
     Bias.Key_=Key;
     if(FileIsExist(bf, FILE_COMMON))
       {
        int ret = MessageBox("Bias sentiment history for this symbol will download and overwrite the file "+bf+" in Terminal/Common/File folder. Continue ?","Download Bias File",MB_OKCANCEL);
        if(ret==IDOK) Bias.BacktestBiasFileDownloader(Download_StartDate);
        else          Alert("Bias History downloading cancelled");
       }
     else            {Bias.BacktestBiasFileDownloader(Download_StartDate);}
    }
    else Alert("Bias History download is not allowed in this mode");
    ExpertRemove();
   }
//-------------------------------------------------------------------------
   string sessionTxt[3]={Active_Time_ASIA,Active_Time_EU,Active_Time_US};
   int    sH[3], sM[3], eH[3], eM[3];
   string parts[2], hm[2];

   for(int i=0;i<3;i++)
     {
      if(StringSplit(sessionTxt[i],'-',parts)!=2) { Alert("Session format must be HH:MM-HH:MM"); return(INIT_FAILED); }

      if(StringSplit(parts[0],':',hm)!=2)         { Alert("Session format must be HH:MM-HH:MM"); return(INIT_FAILED); }
      sH[i]=(int)StringToInteger(hm[0]); sM[i]=(int)StringToInteger(hm[1]);

      if(StringSplit(parts[1],':',hm)!=2)         { Alert("Session format must be HH:MM-HH:MM"); return(INIT_FAILED); }
      eH[i]=(int)StringToInteger(hm[0]); eM[i]=(int)StringToInteger(hm[1]);
     }
   /* 2 ── DECODE ENUMS → plain booleans ---------------------------------- */
   bool wd_as=false, wd_eu=false, wd_us=false,
        fr_as=false, fr_eu=false, fr_us=false;
   switch(Active_Time_Weekday)
     {
      case SESS_AS     : wd_as=true;                      break;
      case SESS_AS_EU  : wd_as=wd_eu=true;                break;
      case SESS_EU     : wd_eu=true;                      break;
      case SESS_EU_US  : wd_eu=wd_us=true;                break;
      case SESS_US     : wd_us=true;                      break;
      case SESS_ALL    : wd_as=wd_eu=wd_us=true;          break;
     }
   if(Active_Time_Friday==SESSION_FRI) { fr_as=wd_as; fr_eu=wd_eu; fr_us=wd_us; }
   else
     switch(Active_Time_Friday)
       {
        case SESSION_AS     : fr_as=true;                      break;
        case SESSION_AS_EU  : fr_as=fr_eu=true;                break;
        case SESSION_EU     : fr_eu=true;                      break;
        case SESSION_EU_US  : fr_eu=fr_us=true;                break;
        case SESSION_US     : fr_us=true;                      break;
        case SESSION_ALL    : fr_as=fr_eu=fr_us=true;          break;
       }
   /* 3 ── PUT THE FLAGS INTO A REGULAR 2-D ARRAY ------------------------- */
   bool flag[2][3]={{wd_as, wd_eu, wd_us},   // 0 → Monday-Thursday
                    {fr_as, fr_eu, fr_us}};    // 1 → Friday
   /* 4 ── BUILD TRADING WINDOWS & ALERT IF GAP --------------------------- */
   int dayStartH[2]={24,24}, dayStartM[2]={0,0},
       dayEndH[2]  ={-1,-1}, dayEndM[2]  ={-1,-1};
       
   for(int d=0; d<2; d++)                         // d=0 weekdays, d=1 Friday
     {
      int prevEH=-1, prevEM=-1; bool first=true, gap=false;

      for(int j=0;j<3;j++) if(flag[d][j])         // j: 0=AS 1=EU 2=US
        {
         /* earliest start */
         if( sH[j] < dayStartH[d] ||
            (sH[j]==dayStartH[d] && sM[j] < dayStartM[d]) )
              { dayStartH[d]=sH[j]; dayStartM[d]=sM[j]; }
         /* latest end */
         if( eH[j] > dayEndH[d] ||
            (eH[j]==dayEndH[d] && eM[j] > dayEndM[d]) )
              { dayEndH[d]=eH[j]; dayEndM[d]=eM[j]; }
         /* gap check (non-overlap) */
         if(!first) if(sH[j] > prevEH || (sH[j]==prevEH && sM[j] > prevEM)) gap=true;
         prevEH=eH[j]; prevEM=eM[j]; first=false;
        }
      if(first) dayStartH[d]=dayStartM[d]=dayEndH[d]=dayEndM[d]=0;
      if(gap)   Alert((d==0?"Weekday":"Friday")+" sessions are NOT contiguous – trading gap detected.");
     }
   /* 5 ── WRITE TO ARRAYS USED BY OnTick() ------------------------------- */
   for(int idx=0; idx<5; idx++)
     {
      bool fri = (idx==4);
      Hour_Start[idx]   = fri ? dayStartH[1] : dayStartH[0];
      Minute_Start[idx] = fri ? dayStartM[1] : dayStartM[0];
      Hour_End[idx]     = fri ? dayEndH[1]   : dayEndH[0];
      Minute_End[idx]   = fri ? dayEndM[1]   : dayEndM[0];
     }
   Print("Mon:"+IntegerToString(Hour_Start[0],2,'0')+":"+IntegerToString(Minute_Start[0],2,'0')+"-"+IntegerToString(Hour_End[0],2,'0')+":"+IntegerToString(Minute_End[0],2,'0'));
   Print("Tue:"+IntegerToString(Hour_Start[1],2,'0')+":"+IntegerToString(Minute_Start[1],2,'0')+"-"+IntegerToString(Hour_End[1],2,'0')+":"+IntegerToString(Minute_End[1],2,'0'));
   Print("Wed:"+IntegerToString(Hour_Start[2],2,'0')+":"+IntegerToString(Minute_Start[2],2,'0')+"-"+IntegerToString(Hour_End[2],2,'0')+":"+IntegerToString(Minute_End[2],2,'0'));
   Print("Thu:"+IntegerToString(Hour_Start[3],2,'0')+":"+IntegerToString(Minute_Start[3],2,'0')+"-"+IntegerToString(Hour_End[3],2,'0')+":"+IntegerToString(Minute_End[3],2,'0'));
   Print("Fri:"+IntegerToString(Hour_Start[4],2,'0')+":"+IntegerToString(Minute_Start[4],2,'0')+"-"+IntegerToString(Hour_End[4],2,'0')+":"+IntegerToString(Minute_End[4],2,'0'));
   /*for(int i=0;i<5;i++)
   {
    string time[],hourMin[];
    if(StringSplit(times[i],'-',time) != 2)     {Alert("Active time input format not correct, it should be like startTime-endTime (01:00-23:00)"); return INIT_FAILED;}
    
    if(StringSplit(time[0],':',hourMin) != 2)   {Alert("Active time input format not correct, it should be like startTime-endTime (01:00-23:00)"); return INIT_FAILED;}
    Hour_Start[i] = StringToInteger(hourMin[0]); Minute_Start[i] = StringToInteger(hourMin[1]);
    if(StringSplit(time[1],':',hourMin) != 2)   {Alert("Active time input format not correct, it should be like startTime-endTime (01:00-23:00)"); return INIT_FAILED;}
    Hour_End[i]   = StringToInteger(hourMin[0]); Minute_End[i]   = StringToInteger(hourMin[1]);
   }*/
//-------------------------------------------------------------------------
   if(1)
   {
    Grid_Min_     = Grid_Min;
    Grid_Max_     = Grid_Max;
    LP_Size_      = Lock_Profit_Size;
    TP_Pips_      = TP_Pips*LP_Size_;
    TSL_Size_     = TSL_Size;
   }
   else
   {
    Grid_Min_     = Grid_Min*Grid_Size;
    Grid_Max_     = Grid_Max*Grid_Size;
    LP_Size_      = Lock_Profit_Size*Grid_Size;    //if(LP_Size_>0 && LP_Size_<5) LP_Size_=5.0;
    TP_Pips_      = TP_Pips*LP_Size_;
    TSL_Size_     = TSL_Size*Grid_Size;
   }
   SL_Pips_       = SL_Pips;
   //Lots_Max_      = Lots_Max*Lots_Input;
   //Print("Lots Max set to "+DoubleToString(Lots_Max_,2));
//-------------------------------------------------------------------------
   if( (MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD) || MQLInfoInteger(MQL_TESTER)) ) FastSpeed_Flag=true; //&&!MQLInfoInteger(MQL_VISUAL_MODE)
   else
   {
    Print("Expiry: ", Expiry);
    Font_Size=Font_Size_Base;
    double dpi = TerminalInfoInteger(TERMINAL_SCREEN_DPI);
    if(dpi<72) dpi=96;
    double dpiFactor = dpi/96.0;
    Font_Size=(int)MathCeil(Font_Size*1.0/dpiFactor); Print("Font Size=",Font_Size);//Font_Size_Header=Font_Size+3;
  //Print("BaseFontSize="+(string)Font_Size_Base+" ScaleRatio="+(string)scaleRatio+" DPIfactor="+(string)dpiFactor+" FontSize="+(string)Font_Size);
  //Font_Size=MathMax(MathMin(Font_Size,40),8);//(int)MathRound(floatSize); //Print(Font_Size);
  //if(Mode_Operation==Operation_Export)
    if(Mode=="EXPORT")
    {
     Alert("Export is only allowed in back testing mode");
     return INIT_PARAMETERS_INCORRECT; ExpertRemove();
    }
    //MessageBox("Press Ok and Please Wait...","Verifying Online License",MB_OK);
    //if(OnlineValidationFunction(MetatraderKey,ServerBreakDownDays,true))  MessageBox("Online License Validation Successful","Licensed",MB_OK);
    //else                                                                  MessageBox("Online License Validation Failed"    ,"Validation Failed",MB_OK);
    if(Mode_Download!=Download_News&&Mode_Download!=Download_NewsBias)
    LicenseKey = VerifyLicense(AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_NAME),AccountInfoString(ACCOUNT_SERVER),true);
    
    if(LicenseKey==LICENSE_VALID)//||LicenseKey!=0)
    {
     if(Mode_Operation==Operation_Report)
     {
      string filenames[];
      int ret = FileSelectDialog("Select both back and forward xml files",NULL,"xml files (*.xml)|*.xml|All files (*.*)|*.*",FSD_FILE_MUST_EXIST|FSD_ALLOW_MULTISELECT|FSD_COMMON_FOLDER,filenames,NULL);
      if(ret<=0) {Alert("Failure: No Files."); return INIT_FAILED;}
      if(ReportAnalyzerCombiner(filenames,false,Key,EA_Name,Server))
      {
       ret = MessageBox("Combined Report saved in the same folder.\nDo you want to run the exporter on the Combined report?","Success",MB_YESNO|MB_ICONQUESTION);
       if(ret==IDYES) {StartExporter(false); Sleep(5000); return INIT_FAILED;}
       if(ret==IDNO||ret==IDCANCEL) return INIT_FAILED;
      }
      return INIT_FAILED;
     }
     //while(GetMicrosecondCount()-lastMScount<2000000) Sleep(500);
     //while(GetTickCount()-lastTickcount<2000) Sleep(500);
     if(MAGIC1==0 && (Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash))
     {
      if(!MQLInfoInteger(MQL_DLLS_ALLOWED))
      {int ret=MessageBox("DLL should be enabled for proper working of this mode.\n\nMT5 > Tools > Options > Experts > Allowed DLL","Enable DLL",MB_OK|MB_ICONERROR); Sleep(5000); return(INIT_FAILED);}
    //string filename; int handle=FileFindFirst("*",filename,FILE_COMMON); Print(filename); FileFindNext(handle,filename);
      if(!ChartGetInteger(0,CHART_IS_MAXIMIZED,0)) Sleep(999);
      int chartWidth  = (int)ChartGetInteger(ChartID(), CHART_WIDTH_IN_PIXELS);
      int chartHeight = (int)ChartGetInteger(ChartID(), CHART_HEIGHT_IN_PIXELS);
      int baseWidth=(Mode_Operation==Operation_Dash ? MathMax(DWidth,1500) : DWidth);
      int baseHeight=DHeight;
      double marginW = 0.05*chartWidth, usableWidth =chartWidth -(2.0*marginW), scaleW=usableWidth/(double)baseWidth;
      double marginH = 0.05*chartHeight,usableHeight=chartHeight-(2.0*marginH), scaleH=usableHeight/(double)baseHeight;
      double scaleFactor=MathMin(MathMin(scaleW,scaleH),1.5);
      if(scaleFactor<=0.0) scaleFactor=1.0;
      int newWidth =MathMin((int)MathRound(baseWidth *scaleFactor),(int)MathRound(usableWidth));
      int newHeight=(int)MathRound(baseHeight*scaleFactor);
      int left=(newWidth >= (int)MathRound(usableWidth) ? (int)MathRound(marginW) : (chartWidth  - newWidth ) / 2);
      int dialogFramePadding=MathMax(28,(int)MathRound(newHeight*0.06));
      int dialogOuterHeight=newHeight+dialogFramePadding;
      int top =(dialogOuterHeight >= chartHeight ? 0 : (chartHeight - dialogOuterHeight) / 2);
      Font_Size=(int)MathCeil(Font_Size_Base*scaleFactor/dpiFactor); //Font_Size_Header=Font_Size+3;
      Print("ChartWidth="+(string)chartWidth+" ChartHeight="+(string)chartHeight);
      Print("BaseWidth="+(string)baseWidth+" BaseHeight="+(string)baseHeight+" NewWidth="+(string)newWidth+" NewHeight="+(string)newHeight+" DialogOuterHeight="+(string)dialogOuterHeight);
      Print("BaseFontSize="+(string)Font_Size_Base+" ScaleFactor="+DoubleToString(scaleFactor,2)+" DPIfactor="+(string)dpiFactor+" FontSize="+(string)Font_Size);
      Sleep(100); ObjectsDeleteAll(ChartID(),0); Sleep(100);
      if(Mode_Operation==Operation_Batch)
      {
       TesterDialog.SetFlags(Key,EA_Name,Server,Font_Size,newWidth,newHeight);
       if(!TesterDialog.Create(ChartID(),"StrategyTesterGUI",0, left,top,left+newWidth,top+dialogOuterHeight)) {Alert("Tester GUI creation Failed, please try again."); return(INIT_FAILED);}
       GUI_BG_Display();
       Sleep(100); TesterDialog.Run(); Sleep(100);
       return (INIT_SUCCEEDED);
      }
      bool fresh_dashboard_launch=false;
      bool resume_dashboard_launch=false;
      if(Mode_Operation==Operation_Dash)
      {
       //ChartNavigate(0,CHART_BEGIN);
       if(ChartID() != ChartFirst())
       {
        int ret=MessageBox("Dashboard mode must run on the first/oldest chart of the terminal for proper navigation and deployment.\nThis is not the first/oldest chart."+
                           "\n\n""Close all other charts now?","Confirmation",MB_YESNO|MB_ICONQUESTION);
        if(ret==IDYES)
        {
         long id = ChartFirst();                      // first chart in terminal
         while(id != -1)                              // <- stop when ChartNext() says -1
         {
            long next = ChartNext(id);                // get next before we kill current
            if(id != ChartID()) ChartClose(id);       // close unwanted window
            id = next;
         }
         ChartRedraw();                               // force GUI refresh
        }
        else {ShowPrompt("Wrong Chart Position"," ","Open Dashboard on the first/oldest chart.",""); Sleep(10000); return(INIT_FAILED); ExpertRemove();}
       }
       DashboardDialog.SetFlags(Key,EA_Name,Server,version_,Font_Size,ChartID());
       if(DashboardDialog.DashboardStateExists())
       {
        string prompt="A previously deployed dashboard configuration was found for this terminal.\n\n"
                     +"Yes = resume the saved dashboard.\n"
                     +"No = deploy a new dashboard and delete the old configuration.\n"
                     +"Cancel = abort dashboard launch.";
        int resume_ret=MessageBox(prompt,"Dashboard Resume",MB_YESNOCANCEL|MB_ICONQUESTION|MB_DEFBUTTON1);
        if(resume_ret==IDYES)
           resume_dashboard_launch=true;
        else if(resume_ret==IDNO)
        {
           GoatDeleteDashboardBusData();
           DashboardDialog.DeleteDashboardConfig();
           fresh_dashboard_launch=true;
        }
        else
        {
           ShowPrompt("Dashboard Launch Cancelled","","The saved dashboard configuration was left untouched.","");
           Sleep(10000);
           return(INIT_FAILED);
           ExpertRemove();
        }
       }

       int SetsTotal=(resume_dashboard_launch ? DashboardDialog.LoadDashboardConfig() : DashboardDialog.LoadSetFiles());
       if(SetsTotal<=0)
       {
        if(resume_dashboard_launch) Alert("Saved dashboard configuration could not be loaded.");
        else                        Alert("No valid .set files found.");
        return(INIT_FAILED);
       }
       if(!resume_dashboard_launch)
          DashboardDialog.ResetPortfolioTrackingState();
       if(fresh_dashboard_launch) DashboardDialog.DeleteDashboardConfig();
       ChartSetInteger(0, CHART_EVENT_MOUSE_WHEEL, true);
       ChartSetInteger(0, CHART_MOUSE_SCROLL, false);
       if(!DashboardDialog.Create(ChartID(),Key+"_Dashboard",0,SetsTotal,left,top,newWidth,newHeight,(int)usableHeight))
       {Alert("Dashboard GUI creation Failed, please try again."); return INIT_FAILED;}
       GUI_BG_Display();
       GlobalVariableSet("Dashboard_ChartID",(double)ChartID());
       GlobalVariablesFlush();
       Sleep(100); DashboardDialog.Run(); Sleep(100);
       return (INIT_SUCCEEDED);
      }
     }
     else {
     //--- create application dialog
      int x1=INDENT_HORI,     y1=INDENT_VERT;//CHART_HEIGHT-PANEL_HEIGHT-INDENT_VERT;
      int x2=x1+PANEL_WIDTH,  y2=y1+PANEL_HEIGHT;
      Sleep(100);
      if(MAGIC1==0) {
       if(!PanelDialog.Create(ChartID(),EA_Name_generated,0,x1,y1,x2,y2)) {Alert("Panel GUI creation Failed, please try again."); return(INIT_FAILED);}
       Sleep(100); PanelDialog.Run(); Sleep(100);
      }
      SetEdit(PanelDialog.m_edit_Info_1,Symbol()); SetEdit(PanelDialog.m_edit_Info_2,Strat,clr_Text,Font_Size);
      SetEdit(PanelDialog.m_edit_Buy1_1, "Buy Sequence");
      SetEdit(PanelDialog.m_edit_Sell1_1,"Sell Sequence");
      
      if(!Buy_EN && !FastSpeed_Flag)  {SetEdit(PanelDialog.m_edit_Buy1_2,"Disabled") ;SetEdit(PanelDialog.m_edit_Buy2_1," ");
                                       SetEdit(PanelDialog.m_edit_Buy2_2," ");SetEdit(PanelDialog.m_edit_Buy3_1," ");SetEdit(PanelDialog.m_edit_Buy3_2," ");}
      if(!Sell_EN && !FastSpeed_Flag) {SetEdit(PanelDialog.m_edit_Sell1_2,"Disabled");SetEdit(PanelDialog.m_edit_Sell2_1," ");
                                       SetEdit(PanelDialog.m_edit_Sell2_2," ");SetEdit(PanelDialog.m_edit_Sell3_1," ");SetEdit(PanelDialog.m_edit_Sell3_2," ");}
      
      SetEdit(PanelDialog.m_edit_Indicators,"Indicators");
      SetEdit(PanelDialog.m_edit_Details,"Trading Details");
      if(Mode_Bias!=Bias_Disabled) {SetEdit(PanelDialog.m_edit_Bias,"AI Bias Confidence");}
      if(Mode_News!=News_Disabled) {SetEdit(PanelDialog.m_edit_News,"High Impact News");}
    //SetEdit(PanelDialog.m_edit_Foot_1,"BIIIONIC"); SetEdit(PanelDialog.m_edit_Foot_2,"EA v");
     }
    }
    else
    {
     Sleep(20000);
     return INIT_FAILED; ExpertRemove();
    }
    //buy sell edit disabled printing to be here later
   }

   StartingEquity = AccountInfoDouble(ACCOUNT_EQUITY);
//-------------------------------------------------------------------------
   if(Mode_Lots == FixedLots)  Lots = Lots_Input;
   if(Mode_Lots == ScaledLots) Lots = Lots_Input/(AccountInfoDouble(ACCOUNT_EQUITY)/1000);
   if(Mode_Lots == RiskperSeq && Risk<10) {Alert("Initialization Stopped Manually: You have selected Risk per Sequence but your Risk Amount is too low."); return INIT_PARAMETERS_INCORRECT;}
//-------------------------------------------------------------------------
   if(Mode_RRR!=RRR_Disabled) // RRR is enabled
   {
    if(RRR<0)                                 {Alert("Initialization Failed: Risk/Reward ratio cannot be negative");                         return INIT_PARAMETERS_INCORRECT;}
    if(RRR==0)                                {Alert("Initialization Failed: Risk/Reward ratio is enabled but RRR=0");                       return INIT_PARAMETERS_INCORRECT;}
    if(Mode_RRR==RRR_SL_TP) // RRR by SL/TP
    {
     if(SL_Pips_!=0) // SL is enabled
     {
      if(TP_Pips_!=0)                         {Alert("Initialization Failed: Risk/Reward mode is SL/TP, but neither TP nor SL is zero");     return INIT_PARAMETERS_INCORRECT;}
      else            {TP_Pips_=SL_Pips_*RRR;  Print("TP Pips are set by TP = Risk/Reward Ratio x SL");}
     }
     else
     {
      if(TP_Pips_!=0) {SL_Pips_=TP_Pips_/RRR;  Print("SL Pips are set by SL = TP / Risk/Reward Ratio");}
      else                                    {Alert("Initialization Failed: Risk/Reward mode is SL/TP, but both TP and SL are zero");       return INIT_PARAMETERS_INCORRECT;}
     }
    }
    else if(Mode_RRR==RRR_SL_LP) // RRR by SL/LP
    {
     if(SL_Pips_!=0) // SL is enabled
     {
      if(LP_Size_!=0)                         {Alert("Initialization Failed: Risk/Reward mode is SL/LP, but neither LP nor SL is zero");     return INIT_PARAMETERS_INCORRECT;}
      else            {LP_Size_=SL_Pips_*RRR;  Print("LP Pips are set by LP = Risk/Reward Ratio x SL");}
     }
     else
     {
      if(LP_Size_!=0) {SL_Pips_=LP_Size_/RRR;  Print("SL Pips are set by SL = LP / Risk/Reward Ratio");}
      else                                    {Alert("Initialization Failed: Risk/Reward mode is SL/LP, but both LP and SL are zero");       return INIT_PARAMETERS_INCORRECT;}
     }
    }
    //if((TP_Pips_>0 && LP_Size_>0 && LP_Size_>=TP_Pips_)||
    //   (TP_Pips_<0 && LP_Size_<0 && LP_Size_<=TP_Pips_)) {Alert("Initialization Failed: LP size is greater than TP size, both enabled");     return INIT_PARAMETERS_INCORRECT;}
   }
   else
   {
    //if(((TP_Pips_>0 && LP_Size_>0 && LP_Size_>=TP_Pips_)||(TP_Pips_<0 && LP_Size_<0 && LP_Size_<=TP_Pips_)) && Lock_Profit_Flexibility==1)
    //                                         {Alert("Initialization Failed: LP size is greater than TP size, both enabled");                 return INIT_PARAMETERS_INCORRECT;}
   }
 //if(Mode_Lots==PercentageRisk&&SL_Pips_==0){Alert("Initialization Failed: Lot Sizing method is SL dependent but SL is set to zero");       return INIT_PARAMETERS_INCORRECT;}
   if(Grid_Size >-0.5 && Grid_Size <0.5)     {Alert("Initialization Failed: Pip Gap Size too small or zero");                                return INIT_PARAMETERS_INCORRECT;}
   if(Grid_Min_ >-0.5 && Grid_Min_ <0.5)     {Print("Grid Min Size too small or zero");                                                      Grid_Min_=-0.5;} // -ve because pips forex!=indices
   if(Grid_Max_ >-1.0 && Grid_Max_ <1.0)     {Print("Grid Max Disabled: Size too small or zero");                                            Grid_Max_=999999;}
   if(LP_Size_  >-1.0 && LP_Size_  <1.0)     {Print("Lock Profit Disabled: Size too small or zero");                                         LP_Size_=0;}
   if(TP_Pips_  >-1.0 && TP_Pips_  <1.0)     {Print("Take Profit Disabled: Size too small or zero");                                         TP_Pips_=0;}
   if(LP_Size_  ==0   && TP_Pips_  ==0)      {Alert("Initialization Failed: Both LP and TP cannot be zero/disabled.");                       return INIT_PARAMETERS_INCORRECT;}
   if(TSL_Size_ >-0.5 && TSL_Size_ <0.5)     {Print("Trailing SL Size too small or zero");                                                   TSL_Size_=-0.5;} // -ve because pips forex!=indices
//-------------------------------------------------------------------------
   ATR_TF = TF2TF(ATR_TF_);
   RSI_TF = TF2TF(RSI_TF_);
   EMA_TF = TF2TF(EMA_TF_);
   ADX_TF = TF2TF(ADX_TF_);
   BB_TF  = TF2TF(BB_TF_);
   MACD_TF= TF2TF(MACD_TF_);
   RSI2_TF= TF2TF(RSI2_TF_);
 /*switch(EMA_Periods)
   {
    case     MA_4_8_60:     EMA1_Period = 4;  EMA2_Period = 8;  EMA3_Period = 60;    break;
    case     MA_8_13_21:    EMA1_Period = 8;  EMA2_Period = 13; EMA3_Period = 21;    break;
    case     MA_9_21_55:    EMA1_Period = 9;  EMA2_Period = 21; EMA3_Period = 55;    break;
    case     MA_10_50_100:  EMA1_Period = 10; EMA2_Period = 50; EMA3_Period = 100;   break;
    case     MA_10_50_200:  EMA1_Period = 10; EMA2_Period = 50; EMA3_Period = 200;   break;
    default:                                                                         break;
   }*/
 //ArrayResize(EMA_Periods,EMA_Count);
   ArrayResize(EMA_handles,EMA_Count);
   ArrayResize(EMAs,EMA_Count);
   ArraySetAsSeries(ATR_Buf      ,true);
   ArraySetAsSeries(RSI_Buf      ,true);
   ArraySetAsSeries(EMA1_Buf     ,true);
   ArraySetAsSeries(EMA2_Buf     ,true);
   ArraySetAsSeries(EMA3_Buf     ,true);
   ArraySetAsSeries(ADX_Main_Buf ,true);
   ArraySetAsSeries(ADX_PLS_Buf  ,true);
   ArraySetAsSeries(ADX_MNS_Buf  ,true);
   ArraySetAsSeries(BB_Hi_Buf    ,true);
   ArraySetAsSeries(BB_Mi_Buf    ,true);
   ArraySetAsSeries(BB_Lo_Buf    ,true);
   ArraySetAsSeries(MACD_Main_Buf,true);
   ArraySetAsSeries(MACD_Sig_Buf ,true);
   ArraySetAsSeries(MACD_Clr_Buf ,true);
   ArraySetAsSeries(RSI2_Buf     ,true);
//-------------------------------------------------------------------------
   if(Grid_Size<0||LP_Size_<0||SL_Pips_<0||TP_Pips_<0||TSL_Size_<0||Grid_Min_<0||Grid_Max_<0){
                                    ATR_handle     = iATR(Symbol(),ATR_TF,1);
                                    if(ATR_handle == INVALID_HANDLE) {Print("iATR failed. err=",GetLastError()); return(INIT_FAILED);}
                                    ENUM_MA_METHOD mt;
                                    switch(ATR_Method){
                                       case  SMA: mt=MODE_SMA; break;
                                       case  EMA: mt=MODE_EMA; break;
                                       case  LWMA:mt=MODE_LWMA;break;
                                       default:   mt=MODE_SMA; break;}
                                    ATR_MA_handle  = iMA    (Symbol(),ATR_TF,ATR_Period,0,mt,ATR_handle);}
                                    if(ATR_MA_handle == INVALID_HANDLE) {Print("iMA-on-ATR failed. err=",GetLastError()," ATR_handle=",ATR_handle); return(INIT_FAILED);}
   if(RSI_Mode != RSI_Disabled)     RSI_handle     = iRSI   (Symbol(),RSI_TF,RSI_Period,RSI_Price);
   if(EMA_Mode != Trade_Disabled)  {for(int i=0;i<EMA_Count;i++)
                                  //EMA2_handle    = iMA    (Symbol(),EMA_TF,EMA2_Period,0,EMA_Method,EMA_Price);
                                    EMA_handles[i] = iMA    (Symbol(),EMA_TF,(int)(((double)EMA_Period)*MathPow(EMA_Exponent,i)),0,EMA_Method,EMA_Price);}
   if(ADX_Mode != Trade_Disabled)   ADX_handle     = iADX   (Symbol(),ADX_TF,ADX_Period);
   if(BB_Mode  != BB_Disabled)      BB_handle      = iBands (Symbol(),BB_TF,BB_Period,0,BB_Deviation,BB_Price);
   if(MACD_Mode!= Trade_Disabled) //MACD_handle    = iMACD  (Symbol(),MACD_TF,          MACD_Fast,MACD_Slow,MACD_Signal,MACD_Price);
                                    MACD_handle    = iCustom(Symbol(),MACD_TF,MACD_Path,MACD_Fast,MACD_Slow,MACD_Signal,0,MACD_Price,100,MACD_Deviations,MACD_Mode_Trend);
   if(RSI2_Mode!= RSI_Disabled)     RSI2_handle    = iRSI   (Symbol(),RSI2_TF,RSI2_Period,RSI2_Price);
//-------------------------------------------------------------------------
   RSI_Sig=EMA_Sig=ADX_Sig=BB_Sig=MACD_Sig=RSI2_Sig=OP_NULL;
//-------------------------------------------------------------------------
   ArraySetAsSeries(DDs,false);        ArrayResize(DDs,99);        ArrayInitialize(DDs,0.0);
   ArraySetAsSeries(DDs_PC,false);     ArrayResize(DDs_PC,99);     ArrayInitialize(DDs_PC,0.0);
   ArraySetAsSeries(DDs_Actual,false); ArrayResize(DDs_Actual,99); ArrayInitialize(DDs_Actual,0.0);
   
   ArrayResize(Sequence_Profits,0);    ArrayResize(Position_Durations,0);
//-------------------------------------------------------------------------
   if(MAGIC1==0)
   {
    if(Mode_News!=News_Disabled) News.Init(Key);
    if(Mode_Bias!=Bias_Disabled) Bias.Init(Key);
    MathSrand(GetTickCount());//*TimeLocal());
  //randPF=(double)(MathRand()%1000)/1000.0;             // 0‥0.999
    randA =(double)(GetTickCount()%1000)/1000;
    long restored_magic=0;
    bool restored_magic_found=GoatFindMagicByCid(Symbol(),ChartID(),restored_magic);
    if(restored_magic_found)
       MAGIC1=(int)restored_magic;
    if(MAGIC1==0) MAGIC1 = MathRand()+9+ChartWindowsHandle(0);
    if(MAGIC2==0) MAGIC2 = MathRand()+9+ChartWindowsHandle(0);
    
                                Seq_Buy.Init(OP_BUY,false);        Seq_Sell.Init(OP_SELL,false);
    if(MathAbs(Delay_Trade)>0) {Seq_Buy_Virtual.Init(OP_BUY,true); Seq_Sell_Virtual.Init(OP_SELL,true);}
    DashboardBusRebuildClosedStats();
    GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_CID),(double)GoatTruncateCidValue(ChartID()));
    if(GlobalVariableCheck("Dashboard_ChartID") && !restored_magic_found)
    {
       GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_MAGIC),(double)MAGIC1);
       DashboardBusSendStatus("Deploying");
    }
    GlobalVariablesFlush();
   }
//-------------------------------------------------------------------------
 //if(Mode_Operation==Operation_Export)
   if(Mode=="EXPORT")
   {
    if(MQLInfoInteger(MQL_OPTIMIZATION)||MQLInfoInteger(MQL_FORWARD)) {Print("Exporting CSV/SET is not allowed in Optimization mode: Initialization Failed."); return INIT_PARAMETERS_INCORRECT;}
    //if(MQLInfoInteger(MQL_TESTER)) Date_Start = TimeToString(TimeCurrent(),TIME_DATE);
    Date_Start = TimeToString(TimeCurrent(),TIME_DATE);
    if(dt_Back_OOS!=0) dt_BOOS_end = dt_Back_OOS;
    
    FileCSV_Name="TEMP"+"\\"+EA_Name+"-"+Server+"\\"+Strat+"\\"+Symbol()+"\\CSV+SET\\"+EA_Name+" "+Symbol()+","+TFToString(Period())+" "+Date_Start;
    FileCSV_handle = FileOpen(FileCSV_Name+"_"+(string)MAGIC1+".csv",FILE_COMMON|FILE_CSV|FILE_WRITE,"\t");
    if(FileCSV_handle == INVALID_HANDLE)
    {
     Print("Failed to open/create the CSV file. Check folder permissions or path. ",GetLastError());
     return INIT_FAILED;
    }
    FileWrite(FileCSV_handle,"<DATE>","<BALANCE>","<EQUITY>","<DEPOSIT LOAD>");
   }
//-------------------------------------------------------------------------
   if(!FastSpeed_Flag)
   {
    /*&& Mode_Operation!=Operation_None)*/ AllDisplaySettings();
    //if(NEWS_FILTER && DRAW_NEWS_CHART && READ_NEWS(NEWS_TABLE) && ArraySize(NEWS_TABLE)>0) DRAW_NEWS(NEWS_TABLE);
    //TIME_CORRECTION = ((int(TimeCurrent() - TimeGMT()) + 1800) / 3600);
   }
   if(MQLInfoInteger(MQL_VISUAL_MODE)) {AllDisplaySettings(); FastSpeed_Flag=false;}
//-------------------------------------------------------------------------
   //if(Mode_Operation!=Operation_Batch) return INIT_PARAMETERS_INCORRECT;
   OnTick(); Sleep(50);
   ChartRedraw(); Sleep(50);
   return (INIT_SUCCEEDED);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void OnDeinit(const int reason)
  {
   Print("================"+Server+"-"+EA_Name+" ("+Symbol()+") Deinit Start"+"================");
   if(reason!=REASON_PARAMETERS && reason!=REASON_TEMPLATE && reason!=REASON_CHARTCHANGE)
   {
      if(Mode_Operation!=Operation_Batch && Mode_Operation!=Operation_Dash)
      {
         DashboardBusSendStatus("Offline");
         GlobalVariablesFlush();
      }
      if(Mode_Operation==Operation_Dash)
      {
         if(reason==REASON_REMOVE)
         {
            DashboardDialog.DeleteDashboardConfig();
            GoatDeleteDashboardBusData();
         }
         GlobalVariableDel("Dashboard_ChartID");
         ChartSetInteger(0,CHART_MOUSE_SCROLL,true);
      }
      if(!MQLInfoInteger(MQL_VISUAL_MODE))
      {
       if(ObjectFind(0,"RectLabel") >= 0) RectLabelDelete(0,"RectLabel");
       
       for(int i=1; i<=30; i++)
       {
        string OBJ_NAME = IntegerToString(i,2,'0'); if(ObjectFind(0,OBJ_NAME) >= 0) ObjectDelete(0,OBJ_NAME);
               OBJ_NAME = IntegerToString(i,3,'0'); if(ObjectFind(0,OBJ_NAME) >= 0) ObjectDelete(0,OBJ_NAME);
       }
      }
      int obj=ObjectsTotal(0)-1;
      for(int i=obj; i>=0; i--)
      {
       string name=ObjectName(0,i);
       if(StringFind(name,Key,0)>=0) ObjectDelete(0,name);
      }
      Comment("");
      if(FileCSV_handle!=INVALID_HANDLE) FileClose(FileCSV_handle);
      if(FileSET_handle!=INVALID_HANDLE) FileClose(FileSET_handle);
      HidePrompt();
      EA_LOGO.BmpArrayFree();
   //--- destroy dialogs
           if(Mode_Operation==Operation_Batch) TesterDialog.Destroy(reason);
      else if(Mode_Operation==Operation_Dash)  DashboardDialog.Destroy(reason);
      else                                     PanelDialog.Destroy(reason);
      EventKillTimer();
   }
   else Print("================"+Server+"-"+EA_Name+" ("+Symbol()+") Deinit Skipped"+"================");
   string desc="",temp="";
 //temp="--------------------------------------------------------------------------------------------------------"; Print(temp); desc+="; "+temp+"\n";
   temp=MQLInfoString(MQL_PROGRAM_NAME)+" "+Symbol()+",M"+(string)Period(); Print(temp); desc+="; "+temp+"\n";
   
   temp="Days="  +(string)days                 +" Weeks="      +DoubleToString(days/5,1)+" Months="+DoubleToString(days/21.7,1); Print(temp); desc+="; "+temp+"\n";
   temp="Trades="+(string)orders               +" Sequences="  +(string)Sequences; Print(temp); desc+="; "+temp+"\n";
   temp= "Orders="        +(string)(orders-orderErrors)          +"/"+(string)orders
        +" TPSL_Modified="+(string)(TPSLmodifieds-TPmodifyErrors)+"/"+(string)TPSLmodifieds
        +" TSL_Modified=" +(string)(TSLmodifieds-TSLmodifyErrors)+"/"+(string)TSLmodifieds
        +" Closed="       +(string)(closed-closeErrors)          +"/"+(string)closed
        +" PartialClosed="+(string)(Pclosed-PcloseErrors)        +"/"+(string)Pclosed;         Print(temp); desc+="; "+temp+"\n";
   if(ArraySize(DDs_PC)>0)     {temp="DDs_% =  " +DoubleToString(DDs_PC[0]*100,2); Print(temp); desc+="; "+temp+"\n";}
   if(ArraySize(DDs_Actual)>0) {temp="DDs_Act= " +DoubleToString(DDs_Actual[0],0); Print(temp); desc+="; "+temp+"\n";}
   temp="--------------------------------------------------------------------------------------------------------"; Print(temp); desc+="; "+temp;
   return;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int OnTesterInit()
  {
   Print(EA_Name+": "+Symbol()+" Optimization Initialization.");//,TerminalInfoString(TERMINAL_DATA_PATH));
   Sleep(100);
   if(GlobalVariableGet("BatchOnGoing")!=0)
   {
    if(GlobalVariableGet("TerminalRunning")==0) GlobalVariableSet("TerminalRunning",1.0);
    else {
      WriteLog("INIT: ❌❌❌❌❌ Batch is running but terminal did not restart (Or you stopped last Batch abruptly), Chance of duplicate Optimization <=====>",false,Key,EA_Name,Server);
      ShowPrompt("Optimization Error...","Batch is running but terminal did not restart!","Chance of duplicate Optimization...","");
      //return INIT_FAILED;
      }
    WriteLog("INIT: ➡️➡️➡️➡️➡️ Batch Optimization Initialized, "+Symbol()+" ➡️➡️➡️➡️➡️",false,Key,EA_Name,Server);
    ShowPrompt("Optimization running...","Do not close this chart!","Batch Running.","");
    
    string movedFiles[];
    if(MigrateLeftOverFilesToCommon(Key,movedFiles) && ArraySize(movedFiles)>1) WriteLog("INIT: ❌ LeftOver XML(s) Found.",false,Key,EA_Name,Server);
    
    GlobalVariableSet("TerminalRunning",1.0);
    if(UpdateBatchQueueAndWriteConfigFile(true,false,Key,EA_Name,Server))
    {
     GlobalVariableSet("RefreshQueue",1.0);
     WriteLog("INIT: Batch Queue updated",false,Key,EA_Name,Server);
    }
    else WriteLog("INIT: ❌ Batch Queue update Error",false,Key,EA_Name,Server);
    Sleep(500);
   }
   else ShowPrompt("Optimization running...","Do not close this chart!"," ","");
   
   if(Mode_Opti==Opti_PF_MRFp || Mode_Opti==Opti_PF_MRF_SRp)
   {
    //if(FileIsExist(Key+"\\"+"Tester.txt",FILE_COMMON))
    FileTester_handle = FileOpen(Key+"\\"+"Tester.txt",FILE_TXT|FILE_WRITE|FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
    FileWrite(FileTester_handle,0.02);
    FileClose(FileTester_handle);
   }
   return INIT_SUCCEEDED;
  }
//-----------------------------------------------------------------------------------
double OnTester()
  {
   if(AccountInfoDouble(ACCOUNT_EQUITY) > MaxEquity)
   {
    MaxEquity = AccountInfoDouble(ACCOUNT_EQUITY);
    ArraySort(DDs_PC); ArraySort(DDs_Actual);
  //ArraySortMQL4(DDs,WHOLE_ARRAY,0,MODE_ASCEND);
   }
   CurrentDD = (MaxEquity-AccountInfoDouble(ACCOUNT_EQUITY))/MaxEquity; if(CurrentDD > DDs_PC[0])     DDs_PC[0]     = CurrentDD;
   CurrentDD = (MaxEquity-AccountInfoDouble(ACCOUNT_EQUITY));           if(CurrentDD > DDs_Actual[0]) DDs_Actual[0] = CurrentDD;
//-----------------------------------------------------------------------------------
 //ArraySortMQL4(DDs,WHOLE_ARRAY,0,MODE_DESCEND);
   ArraySort(DDs);        ArraySetAsSeries(DDs,true);
   ArraySort(DDs_PC);     ArraySetAsSeries(DDs_PC,true);
   ArraySort(DDs_Actual); ArraySetAsSeries(DDs_Actual,true);
   
 //ArrayCopy(DDs,DDs_PC,0,0,WHOLE_ARRAY);
   ArrayCopy(DDs,DDs_Actual,0,0,WHOLE_ARRAY);
   
   double Mean_DD;
   // improve this mean DD calculation
   if     (DDs[0]==0)                                           Mean_DD =  999999;
   else if(DDs[1]==0 || DDs[1]<0.1*DDs[0] || DDs[1]<0.5*DDs[0]) Mean_DD =  DDs[0];
   else if(DDs[2]==0 || DDs[2]<0.1*DDs[0] || DDs[2]<0.5*DDs[1]) Mean_DD = (DDs[0]*6+DDs[1]*5)/11;
   else if(DDs[3]==0 || DDs[3]<0.1*DDs[0] || DDs[3]<0.5*DDs[2]) Mean_DD = (DDs[0]*7+DDs[1]*6+DDs[2]*5)/18;
   else if(DDs[4]==0 || DDs[4]<0.1*DDs[0] || DDs[4]<0.5*DDs[3]) Mean_DD = (DDs[0]*8+DDs[1]*7+DDs[2]*6+DDs[3]*5)/26;
   else                                                         Mean_DD = (DDs[0]*9+DDs[1]*8+DDs[2]*7+DDs[3]*6+DDs[4]*5)/35;
   
   double Return = (AccountInfoDouble(ACCOUNT_EQUITY)-StartingEquity)/StartingEquity; // Profit % return
   
   if(Return<0)   Mean_DD = DDs[0];
   if(Mean_DD==0) Mean_DD = StartingEquity/2; // significant DD to discard result and avoid Divide by zero error
   
   Mean_DD /= StartingEquity; // Now % DD
   double ARF = (Return/Mean_DD); // Modified RF
 //double DD  = TesterStatistics(STAT_EQUITYDD_PERCENT)/100;
 //double DD  = TesterStatistics(STAT_EQUITY_DDREL_PERCENT)/100;
   int trades = (int)TesterStatistics(STAT_TRADES);
   double PF  = TesterStatistics(STAT_PROFIT_FACTOR);
   double RF  = TesterStatistics(STAT_RECOVERY_FACTOR);
   double SR  = TesterStatistics(STAT_SHARPE_RATIO);        // SR
   double profit = TesterStatistics(STAT_PROFIT);
   double dd     = TesterStatistics(STAT_EQUITY_DD);//TesterStatistics(STAT_EQUITY_DDREL_PERCENT);// %DD
   double MARF = ARF/(days/21.7);
   double mean_duration = MathMean(Position_Durations);
   //File_name   = "DDs_"+Symbol()+"_"+(string)Period()+".csv";
   //File_handle = FileOpen(File_name,FILE_CSV|FILE_WRITE,",");
   //for(int i=0; i<=DDs_Index; i++) FileWrite(File_handle,DDs[i]*100);
   //FileClose(File_handle);
//-----------------------------------------------------------------------------------
   string desc="",temp="";
   temp="--------------------------------------------------------------------------------------------------------"; Print(temp); desc+="; "+temp+"\n";
   temp=MQLInfoString(MQL_PROGRAM_NAME)+" "+Symbol()+",M"+(string)Period(); Print(temp); desc+="; "+temp+"\n";
   
   temp="Days="  +(string)days                 +" Weeks="      +DoubleToString(days/5,1)+" Months="+DoubleToString(days/21.7,1); Print(temp); desc+="; "+temp+"\n";
   temp="Trades="+(string)trades               +" Sequences="  +(string)Sequences; Print(temp); desc+="; "+temp+"\n";
   temp="Positions="+(string)Positions         +" Avg Duration="+DoubleToString(mean_duration,0)+" Minutes"; Print(temp); desc+="; "+temp+"\n";
   temp="PF="    +DoubleToString(PF,3)         +" RF="         +DoubleToString(RF,3)+" SR="+DoubleToString(SR,3)+" ARF=" +DoubleToString(MARF,3); Print(temp); desc+="; "+temp+"\n";
 //temp="ARF="   +DoubleToString(ARF,3)        +" MonthlyARF=" +DoubleToString(MARF,3)/*+" MeanDD="+DoubleToString(Mean_DD*StartingEquity,0)*/; Print(temp); desc+="; "+temp+"\n";
   temp="Return="+DoubleToString(profit*1,0)   +" MonthlyRet=" +DoubleToString((profit*1/(days/21.7)),0)+" DD="+DoubleToString(dd*1,0); Print(temp); desc+="; "+temp+"\n";
   
   temp= "Orders="        +(string)(orders-orderErrors)          +"/"+(string)orders
        +" TPSL_Modified="+(string)(TPSLmodifieds-TPmodifyErrors)+"/"+(string)TPSLmodifieds
        +" TSL_Modified=" +(string)(TSLmodifieds-TSLmodifyErrors)+"/"+(string)TSLmodifieds
        +" Closed="       +(string)(closed-closeErrors)          +"/"+(string)closed
        +" PartialClosed="+(string)(Pclosed-PcloseErrors)        +"/"+(string)Pclosed;         Print(temp); desc+="; "+temp+"\n";
   temp="DDs_% =  " +DoubleToString(DDs_PC[0]*100,2) +" "+DoubleToString(DDs_PC[1]*100,2)+" "
                    +DoubleToString(DDs_PC[2]*100,2) +" "+DoubleToString(DDs_PC[3]*100,2)+" "
                    +DoubleToString(DDs_PC[4]*100,2) +" "+DoubleToString(DDs_PC[5]*100,2)+" "; Print(temp); desc+="; "+temp+"\n";
   temp="DDs_Act= " +DoubleToString(DDs_Actual[0],0) +" "+DoubleToString(DDs_Actual[1],0)+" "
                    +DoubleToString(DDs_Actual[2],0) +" "+DoubleToString(DDs_Actual[3],0)+" "
                    +DoubleToString(DDs_Actual[4],0) +" "+DoubleToString(DDs_Actual[5],0)+" "; Print(temp); desc+="; "+temp+"\n";
  /*Print("Symbols=" +(string)Symbols_Total           +" Currencies="+(string)Currencies_Total+" "
                    +Currencies[0].Name+" "+Currencies[MathMin(Currencies_Total-1,1)].Name+" "+Currencies[MathMin(Currencies_Total-1,2)].Name+" "
                    +Currencies[MathMin(Currencies_Total-1,3)].Name);
   for(int x=0;x<Symbols_Total;x++)
   Print(Symbols[x].Name+":"+" Orders="  +(string)(Symbols[x].orders-Symbols[x].orderErrors)    +"/"+(string)Symbols[x].orders
                            +" Modified="+(string)(Symbols[x].modifieds-Symbols[x].modifyErrors)+"/"+(string)Symbols[x].modifieds
                            +" Closed="  +(string)(Symbols[x].closed-Symbols[x].closeErrors)    +"/"+(string)Symbols[x].closed
                            +" PClosed=" +(string)(Symbols[x].P_closed-Symbols[x].P_closeErrors)+"/"+(string)Symbols[x].P_closed
                            +" Renewed=" +(string)(Symbols[x].renews-Symbols[x].renewErrors)    +"/"+(string)Symbols[x].renews);*/
   temp="--------------------------------------------------------------------------------------------------------";           Print(temp); desc+="; "+temp+"\n";
   if(dt_Back_OOS!=0) {
   temp="BOOS:   "+Date_Start+"-"+TimeToString(dt_Back_OOS,TIME_DATE)
                  +" Days="+(string)days_BOOS+" Trades="+(string)trd_BOOS+" PL="+DoubleToString(eq_BOOS_end-eq_BOOS_start,0); Print(temp); desc+="; "+temp+"\n";}
   string is_from = (dt_Back_OOS!=0 ? TimeToString(dt_Back_OOS,TIME_DATE) : Date_Start);
   string is_to   = (dt_Fwrd_OOS!=0 ? TimeToString(dt_Fwrd_OOS,TIME_DATE) : TimeToString(TimeCurrent(),TIME_DATE));
   temp="SAMPLE: "+is_from+"-"+is_to
                  +" Days="+(string)days_IS+" Trades="+(string)trd_IS+" PL="+DoubleToString(eq_IS_end-eq_IS_start,0);         Print(temp); desc+="; "+temp+"\n";
   if(dt_Fwrd_OOS!=0) {
   temp="FOOS:   "+TimeToString(dt_Fwrd_OOS,TIME_DATE)+"-"+TimeToString(TimeCurrent(),TIME_DATE)
                  +" Days="+(string)days_FOOS+" Trades="+(string)trd_FOOS+" PL="+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY)-eq_FOOS_start,0);
                                                                                                                              Print(temp); desc+="; "+temp+"\n";}
   //temp="BOOS:   "+Date_Start                         +"-"+TimeToString(dt_BOOS_end,TIME_DATE)
   //               +" Days="+(string)days_BOOS+" Trades="+(string)trd_BOOS+" PL="+DoubleToString(eq_BOOS_end-eq_BOOS_start,0); Print(temp); desc+="; "+temp+"\n";
   //temp="Sample: "+TimeToString(dt_Back_OOS,TIME_DATE)+"-"+TimeToString(dt_IS_end,TIME_DATE)
   //               +" Days="+(string)days_IS  +" Trades="+(string)trd_IS  +" PL="+DoubleToString(eq_IS_end  -eq_IS_start,0);   Print(temp); desc+="; "+temp+"\n";
   //temp="FOOS:   "+TimeToString(dt_Fwrd_OOS,TIME_DATE)+"-"+TimeToString(TimeCurrent(),TIME_DATE)
   //               +" Days="+(string)days_FOOS+" Trades="+(string)trd_FOOS+" PL="+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY)-eq_FOOS_start,0); Print(temp); desc+="; "+temp+"\n";
   temp="--------------------------------------------------------------------------------------------------------";           Print(temp); desc+="; "+temp;
   if(Mode_News!=News_Disabled) {
   temp="NEWS: News Events="+(string)ArraySize(News.NewsList)+" SkippedSequenceStarts="+(string)Sequence_Skipped_News
                                                               +"     SkippedTrades="+(string)Trades_Skipped_News;            Print(temp); desc+="\n; "+temp;}
   if(Mode_Bias!=Bias_Disabled) {
   temp="BIAS: Bias Points="+(string)ArraySize(Bias.BiasList)+" SkippedBuySequenceStarts="+(string)Sequence_Skipped_Bias_B
                                                              +"  SkippedBuyTrades="+(string)Trades_Skipped_Bias_B;                              Print(temp); desc+="\n; "+temp+"\n";
   temp="                       SkippedSellSequenceStarts="+(string)Sequence_Skipped_Bias_S+" SkippedSellTrades="+(string)Trades_Skipped_Bias_S; Print(temp); desc+="; "+temp+"\n";
   temp="--------------------------------------------------------------------------------------------------------";           Print(temp); desc+="; "+temp;}
//-----------------------------------------------------------------------------------
   // Fitness calculation start now
   double   NOISE_PCT      = 0.10;  // 10 % *added* noise
   double   EXP_PF_BASE    = 0.50;  // √ PF
   double   EXP_MRF_BASE   = 1.50;  // MRF²
   double   EXP_SR_BASE    = 0.50;  // √ SR
   
   PF=MathMin(PF,25.0); ARF=MathMin(ARF,25.0); SR=MathMin(SR,25.0); // should be less than these very high absurd values
   
   ARF = ARF+1;                     // Minimum Value is now zero
   ARF/= (days/21.7);               // Now Monthly
 //SR  = 1.0+MathTanh(SR/2.0);      // compressed and shifted to [0,2] range (neutral=1)
   SR  = 1.0/(1.0+MathExp(-SR/2.7));// Same thing but shifted to [0,1] range; SR(0)=0.5 SR(5)=0.86 SR(-5)=0.14
   
   PF=MathMax(PF,0.0); ARF=MathMax(ARF,0.0); SR=MathMax(SR,0.0);
   
   double fitness=0,fitness_real=0,readVal=0,randC=(double)(GetTickCount()%1000)/1000;
   //bool   checkVal=false;
   
   double noise_PF  = NOISE_PCT * (randA-0.5) * EXP_PF_BASE;
   double noise_MRF = NOISE_PCT * (randB-0.5) * EXP_MRF_BASE;
   double noise_SR  = NOISE_PCT * (randC-0.5) * EXP_SR_BASE;
   
   if(!MQLInfoInteger(MQL_OPTIMIZATION)||MQLInfoInteger(MQL_FORWARD)) {noise_PF=noise_MRF=noise_SR=0.0;}
   
   switch(Mode_Opti)
   {
  //case Opti_PF:       fitness=PF;                                  break;
  //case Opti_RF:       fitness=RF+1;                                break;      // RF>0 but not monthly
    case Opti_MRF:      fitness=ARF;                                 break;
  //case Opti_PF_RF:    fitness=PF*RF;                               break;
  //case Opti_PF_MRF:   fitness=PF*MRF;                              break;      // MRF>0 , fitness>0
  //case Opti_SPF_MRF:  fitness=MathSqrt(PF+1)*MRF;                  break;      // PF>1
    case Opti_PF_MRF:   {
                       //fitness=MathPow(PF+1,c1)*MathPow(MRF+1,c2); break;      // PF>1 MRF>1
                         fitness     =MathPow(PF,EXP_PF_BASE+noise_PF)*MathPow(ARF,EXP_MRF_BASE+noise_MRF); break;
                        }
    case Opti_PF_MRFp:  {
                         fitness_real=MathPow(PF,EXP_PF_BASE+0)       *MathPow(ARF,EXP_MRF_BASE+0);
                         fitness     =MathPow(PF,EXP_PF_BASE+noise_PF)*MathPow(ARF,EXP_MRF_BASE+noise_MRF); break;
                        }
    case Opti_PF_MRF_SR:{
                         fitness     =MathPow(PF,EXP_PF_BASE+noise_PF)*MathPow(ARF,EXP_MRF_BASE+noise_MRF)*MathPow(SR,EXP_SR_BASE+noise_SR); break;
                        }
    case Opti_PF_MRF_SRp:{
                         fitness_real=MathPow(PF,EXP_PF_BASE+0)       *MathPow(ARF,EXP_MRF_BASE+0)        *MathPow(SR,EXP_SR_BASE+0);
                         fitness     =MathPow(PF,EXP_PF_BASE+noise_PF)*MathPow(ARF,EXP_MRF_BASE+noise_MRF)*MathPow(SR,EXP_SR_BASE+noise_SR); break;
                        }
  //case Opti_MRF_SD:
    /*{
     double Profit=0;
     for(int i=0; i<ArraySize(Sequence_Profits); i++) {Profit+=Sequence_Profits[i];}//Print(Sequence_Profits[i]);}
     Print("Total Sequences="+(string)Sequences_PL+"  Considered Sequences="+(string)ArraySize(Sequence_Profits)+"  Profit Sum="+DoubleToString(Profit,1));
     double mean= MathMean(Sequence_Profits);
     double std = MathStandardDeviation(Sequence_Profits);
     fitness=MRF;
     if(ArraySize(Sequence_Profits)>5)
     {
      double CV = std/mean;
      Print("Mean="+DoubleToString(mean,5)+" Standard Dev="+DoubleToString(std,5)+" CV="+DoubleToString(CV,9));
      double fitness_New=MRF/CV;//MathPow(CV,2);
      fitness=MRF/CV;
     }
     //if(!MQLInfoInteger(MQL_FORWARD) && ArraySize(Sequence_Profits)<9)
    }*/
    default:                              break;
   }
   //if(fitness1<0 && fitness2<0)  fitness =  fitness1+fitness2;
   //else                          fitness =  fitness1+fitness2*(fitness1*fitness2/MathAbs(fitness1*fitness2));
   //if(fitness1<0 && fitness2<0)  fitness = -fitness1*fitness2;
   //else                          fitness =  fitness1*fitness2;
   //trades = orders;
//--- If writing of optimization results is enabled
   //int hl=FileOpen("filetest",FILE_CSV|FILE_WRITE);
   //if(hl==INVALID_HANDLE) printf("Error %i creating tester file",GetLastError());
   //else
   {
    //FileWriteString(hl,StringFormat("this is a random test %i",0));
    //FileClose(hl);
    //--- Create a frame
    //if(!FrameAdd("Statistics",rndval,0,"filetest"))   printf("FrameAdd failed with error %i",GetLastError());
    //else                                              Print("Frame added");
   }
   if(fitness_real!=0)
   Print("Real Fitness="+(string)fitness_real);
   Print("Fitness before degradation="+(string)fitness);
   fitness = AdjustFitness(fitness,trades,mean_duration);
   
   if((Mode_Opti==Opti_PF_MRFp||Mode_Opti==Opti_PF_MRF_SRp) && MQLInfoInteger(MQL_OPTIMIZATION) && !MQLInfoInteger(MQL_FORWARD))
   {
    FileTester_handle=INVALID_HANDLE;
    while(FileTester_handle==INVALID_HANDLE) FileTester_handle = FileOpen(Key+"\\"+"Tester.txt",FILE_TXT|FILE_READ|FILE_SHARE_READ|FILE_COMMON);
    readVal=StringToDouble(FileReadString(FileTester_handle));   FileClose(FileTester_handle);
    
    if(fitness>readVal && readVal!=0)
    {
     fitness = AdjustFitness(fitness_real,trades,mean_duration);
    }
    if(fitness>readVal)
    {
     FileTester_handle=INVALID_HANDLE;
     while(FileTester_handle==INVALID_HANDLE) {FileTester_handle = FileOpen(Key+"\\"+"Tester.txt",FILE_TXT|FILE_WRITE|FILE_SHARE_WRITE|FILE_COMMON); Sleep(10);}
     FileWrite(FileTester_handle,fitness);                         FileClose(FileTester_handle);
    }
   }
//-----------------------------------------------------------------------------------
   if(Mode=="EXPORT" && !MQLInfoInteger(MQL_OPTIMIZATION) && !MQLInfoInteger(MQL_FORWARD))
   {
    if(FileCSV_handle != INVALID_HANDLE) {FileClose(FileCSV_handle); FileCSV_handle=INVALID_HANDLE;}
    
    string oldFile = FileCSV_Name+"_"+(string)MAGIC1+".csv";
    string newFile = FileCSV_Name+"-"+TimeToString(TimeCurrent(),TIME_DATE); // Start from the same prefix
    string metrix =  //"_Result="  + DoubleToString(fitness,2)
                       "_Trds="  + IntegerToString(trades)
                     + "_Prf="   + DoubleToString(profit,0)
                     + "_DD="    + DoubleToString(dd,0)
                     + "_PF="    + DoubleToString(TesterStatistics(STAT_PROFIT_FACTOR),2)
                   //+ "_RF="    + DoubleToString(RF,2)
                     + "_SR="    + DoubleToString(TesterStatistics(STAT_SHARPE_RATIO),2)
                     + "_ARF="   + DoubleToString(MARF,3);//Print(metrix);
    newFile += metrix+".csv";//Print(newFile);
    if(!FileMove(oldFile,FILE_COMMON, newFile,FILE_REWRITE|FILE_COMMON)) Print("Error renaming CSV file: ", GetLastError());
    
    string FileSET_Name="TEMP"+"\\"+EA_Name+"-"+Server+"\\"+Strat+"\\"+Symbol()+"\\CSV+SET\\"+EA_Name+" "+Symbol()+","+TFToString(Period())+" "+Date_Start
                                                                                            +"-"+TimeToString(TimeCurrent(),TIME_DATE)+metrix+".set";//Print(FileSET_Name);
    FileSET_handle = FileOpen(FileSET_Name,FILE_CSV|FILE_WRITE|FILE_COMMON,"\t");
    if(FileSET_handle == INVALID_HANDLE)
    {
     Print("Failed to open/create the SET file. Check folder permissions or path. ", GetLastError());
     //return INIT_FAILED;
    }
    else WriteSet(desc);
    ChartClose(ChartID());
   }
   //if(!MQLInfoInteger(MQL_FORWARD))
   {
    if(trades==0)                      return -0.010;
    if(trades<=1)                      return -0.007;
    if(trades<=2)                      return -0.006;
    if(trades<=3)                      return -0.005;
    if(trades<=4)                      return -0.004;
    if(trades<=5)                      return -0.003;
    if(trades<=6)                      return -0.001;
  //if(mean_duration>Minutes_Hi)       return -0.3;
   }
//-----------------------------------------------------------------------------------
   //if(FileIsExist(Key+"\\"+EA_Name+"-"+Server+"\\"+"WriteFlag",FILE_COMMON) && !MQLInfoInteger(MQL_OPTIMIZATION) && !MQLInfoInteger(MQL_FORWARD))
   //WriteTesterStatistics(Key+"\\"+EA_Name+"-"+Server+"\\"+"Stats");
   return fitness;
  }
//-----------------------------------------------------------------------------------
double AdjustFitness(double fitness,int trades,double mean_duration)
  {
   double Trades_min=Trades_min_inp;//,Trades_Low;
   double Seq_min=Seq_min_inp;
   if(MQLInfoInteger(MQL_FORWARD))    {Trades_min/=3; Seq_min/=3;}
                                     //Trades_Low=Trades_min/5;
   if(fitness>0)
   {
  //if(trades<Trades_min || Sequences<Seq_min || trades>Trades_Max || mean_duration>Minutes_Max) return 0;
  //double Avg_Trades = trades/Sequences; fitness /= Avg_Trades;
    if(Sequences<=Seq_min)// && !MQLInfoInteger(MQL_FORWARD)) //&& trades>Trades_Low)
                                                            fitness = fitness*(Sequences-0)      /(Seq_min-0);             // degradation between min and 0   by Interpolation
    if(trades<=Trades_min)                                  fitness = fitness*(trades-0)         /(Trades_min-0);          // degradation between min and 0   by Interpolation
  //if(trades<=Trades_min && trades>Trades_Low)             fitness = fitness*(trades-Trades_Low)/(Trades_min-Trades_Low); // degradation between min and low by Interpolation
  //if(trades<=Trades_Low)                                 {fitness = fitness*(trades-0)         /(Trades_Low-0); fitness-= 0.5;}
  //if(trades<=Trades_Low)                                  fitness = fitness-0.5*(Trades_Low-trades)/Trades_Low;          // degradation between low and 0   by Interpolation
    double Minutes_Lo=Minutes_Max*0.70;//,Minutes_Hi=Minutes_Max*1.50;
    double Trades_Lo = Trades_Max*0.70;//,Trades_Hi = Trades_Max*1.50;
  //if     (mean_duration>Minutes_Hi)  fitness = fitness/10; else 
  //if(mean_duration>Minutes_Lo)       fitness = MathMax(fitness*(Minutes_Hi-mean_duration)/(Minutes_Hi-Minutes_Lo),fitness/10);
    if(mean_duration>Minutes_Lo)       fitness *= exp((MathLog(0.1)*(mean_duration-Minutes_Lo))/(double)Minutes_Lo);
  //if     (trades>Trades_Hi)          fitness = fitness/10; else 
  //if(trades>Trades_Lo)               fitness = MathMax(fitness*(Trades_Hi-trades)        /(Trades_Hi-Trades_Lo),fitness/10);
    if(trades>Trades_Lo)               fitness *= exp((MathLog(0.1)*(trades-Trades_Lo))        /(double)Trades_Lo);
   }
   else
   {
    //if(trades<10)               return -0.45;
   }
   return MathLog1p(MathMax(fitness,0.0));  // keeps GA scale friendly
 //return MathLog(fitness+1);
  }
//-----------------------------------------------------------------------------------
//void OnTesterPass()
  //{
   //ulong pass;
   //string name;
   //long id;
   //double value;
   //ushort data[];
   
   //if(!FrameNext(pass,name,id,value,data))   printf("Error #%i with FrameNext",GetLastError());
   //else                                      printf("%s : new frame pass:%llu name:%s id:%lli value:%f",__FUNCTION__,pass,name,id,value);
   
   //string receivedData=ShortArrayToString(data);
   //printf("Size: %i %s",ArraySize(data),receivedData);
   //Comment(receivedData);
  //}
//-----------------------------------------------------------------------------------
void OnTesterDeinit()
  {
   Print(EA_Name+": "+Symbol()+" Optimization Ended");                     Sleep(100);
   if(FileCSV_handle    != INVALID_HANDLE) {FileClose(FileCSV_handle);     Sleep(100);}
   if(FileTester_handle != INVALID_HANDLE) {FileClose(FileTester_handle);  Sleep(100);}
   FileDelete(Key+"\\"+"Tester.txt",FILE_COMMON);                          Sleep(500);
   ChartSetInteger(0, CHART_BRING_TO_TOP, true);                           Sleep(100);
   
   if(GlobalVariableGet("BatchOnGoing")!=0)
   {
    WriteLog("DEINIT: Optimization Ended, "+Symbol()+"",false,Key,EA_Name,Server);
    ShowPrompt("Optimization Ended!","Waiting a few seconds..."," ","");   Sleep(4000);
    ShowPrompt("Processing Optimization...","Migrating XML files..."," ","");
    bool error=false;
    string movedFiles[];
    if(MigrateFilesToCommon(Key,movedFiles))
    {
     if(ArraySize(movedFiles)>1)
     {
      WriteLog("DEINIT: ✅ XML Migration completed successfully!" ,false,Key,EA_Name,Server); //for(int i=0; i<ArraySize(movedFiles); i++) Print("Moved file: ", movedFiles[i]);
      WriteLog("DEINIT: Filename: "+FileNameOnly(movedFiles[ArraySize(movedFiles)-1]),true,Key,EA_Name,Server);
      ShowPrompt("Processing Optimization...","XML files moved!","Combining and analyzing XML...",""); Sleep(999);
      // Now movedFiles[] contains all the complete paths of migrated files
      if(ReportAnalyzerCombiner(movedFiles,false,Key,EA_Name,Server))
      {
       WriteLog("DEINIT: ✅ XML files Combined and Analyzed.",false,Key,EA_Name,Server);
       ShowPrompt("Processing Optimization...","XML files Combined and Analyzed.","Running the top set for verification...",""); Sleep(999);
       error=!StartExporter(false);
       Print("Deleting Empty Folders...");
       DeleteEmptyFolders("TEMP"); DeleteEmptyFolders("Exports");
       Print("Empty Folders in TEMP and Exports, deleted.");
      }
      else {error=true; WriteLog("DEINIT: ❌ Failed to Analyze and Combine xml reports. Aborting exports",true,Key,EA_Name,Server);
            ShowPrompt("Processing Optimization...","Failed to Analyze and Combine xml reports.","Aborting export cycle...",""); Sleep(999);}
     }
     else {error=true; WriteLog("DEINIT: ❌ XML Migration not complete. Not enough xml reports. Aborting report processing and exports cycle...",true,Key,EA_Name,Server);}
    }
    else {error=true; WriteLog("DEINIT: ❌ Some XML files failed to move. Aborting report processing and exports cycle...",true,Key,EA_Name,Server);}
    Sleep(999);
    if(UpdateBatchQueueAndWriteConfigFile(false,error,Key,EA_Name,Server))
    {
     GlobalVariableDel("TerminalRunning");
     GlobalVariableSet("RefreshQueue",1.0);
     Sleep(500);
     if(GlobalVariableGet("BatchOnGoing")!=0)
     {
      ShowPrompt("Restarting Terminal for next optimization...","Do not close this chart!","Batch Running...",""); Sleep(500);
      WriteLog("DEINIT: ✅ Terminal restart sequence initiated...",false,Key,EA_Name,Server); Sleep(500);
      
      //datetime t_start = TimeCurrent();
      for(int i=0;i<10;i++)
      {
       datetime LastTime = TimeCurrent();
       Sleep(2000); TesterStop(); Sleep(2000); TesterStop(); Sleep(2000); TerminalClose(99); Sleep(9000);
       while(TimeCurrent()-LastTime<10) Sleep(10);
       WriteLog("DEINIT: ❌ Terminal Failed to close in 10 seconds. Retrying...",true,Key,EA_Name,Server);
       //if((TimeCurrent()-t_start) >= 600) {WriteLog("DEINIT: ❌ Unable to close Terminal. Batch Paused...",true,Key,EA_Name,Server); TerminalClose(99); break;}
      }
      WriteLog("DEINIT: ❌ Unable to close Terminal. Batch Paused...",true,Key,EA_Name,Server); TerminalClose(99);
     }
     else
     {
      ShowPrompt("Optimization Batch Completed."," "," ","");
    //string summary = GenerateOptimizationSummary(Key+"\\"+EA_Name+"-"+Server+"\\GOAT Batch Queue."+Key, Key+"\\"+EA_Name+"-"+Server+"\\log."+Key);
    //WriteLog("DEINIT: ➡️➡️➡️➡️➡️ Batch Summary:\n"+summary,false,Key,EA_Name,Server);
      WriteLog("DEINIT: 🔵🔵🔵🔵🔵 Batch Completed 🔵🔵🔵🔵🔵",true,Key,EA_Name,Server);
      GlobalVariableDel("BatchOnGoing");
    //int ret=MessageBox("Batch Summary:\n\n"+summary+"\n\nDo you want to open logs?","Batch Complete...",MB_OKCANCEL);
    //if(ret=IDOK) 
     }
    }
    else
    {
     ShowPrompt("Optimization Processing Complete!","Failed to update and continue Batch Queue."," ","");
     WriteLog("DEINIT: ❌ Failed to update and continue Batch Queue.",true,Key,EA_Name,Server);
    }
   }
   else ShowPrompt("Optimization Ended"," "," ","");
   //ChartSetInteger(0, CHART_BRING_TO_TOP, true);                       Sleep(100);
   //GlobalVariableDel("BatchOnGoing");
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool StartExporter(bool reportMode)
  {
   if(InitializeTester(Key,EA_Name,Server,reportMode))
   {
    string BackOOSDate = FetchExportSetting("BackOOSDate",Key,EA_Name,Server);//Print(BackOOSDate);
    int    SetsToExport= (int)FetchExportSetting("SetsToExport",Key,EA_Name,Server); if(SetsToExport<2) SetsToExport=2;
    double MinScore    = StringToDouble(FetchExportSetting("MinScore",Key,EA_Name,Server)); if(MinScore<60) MinScore=60.0;
    double MinARF      = StringToDouble(FetchExportSetting("MinARF",Key,EA_Name,Server));//Print(MinARF);
    double MinSR       = StringToDouble(FetchExportSetting("MinSR",Key,EA_Name,Server));//Print(MinSR);
    double TargetDD    = StringToDouble(FetchExportSetting("TargetDD",Key,EA_Name,Server)); if(TargetDD<100) TargetDD=100;
    bool   AdjustLots  = StringToInteger(FetchExportSetting("AdjustLots",Key,EA_Name,Server))!=0;//Print(AdjustLots);
    bool   InclBackOOS = StringToInteger(FetchExportSetting("IncludeBackOOS",Key,EA_Name,Server))!=0;//Print(InclBackOOS);

    if(!reportMode)
    {
     LogOrPrint(reportMode,"DEINIT: Running top Score Set on back history only",Key,EA_Name,Server);
     strT.fromDate=TimeToString(xmlData.startD,TIME_DATE); strT.toDate=TimeToString(xmlData.forwardD+24*60*60,TIME_DATE);
     RunAndStoreSet(0,"Mode_Operation="+(string)OP_Standard+"\n"+"EA_Desc="+strT.Strat+"@{mode=EXPORT}"+"\n",reportMode,g_allExports,true); // Just Export enabling is required here
     while(!MTTESTER::IsReady()) Sleep(1000);
    }
    if(InclBackOOS && BackOOSDate!="") {strT.fromDate=BackOOSDate; LogOrPrint(reportMode,"⚠️ Back Out-Of-Sample (OOS) history is enabled.",Key,EA_Name,Server);}
    else                                strT.fromDate=TimeToString(xmlData.startD,TIME_DATE);
                                        strT.toDate=GetLastFridayDate();//TimeToString(TimeCurrent()-7*24*3600,TIME_DATE);//TimeToString(xmlData.endD,TIME_DATE);
    LogOrPrint(reportMode,"Adjusting Test Dates, StartDate="+strT.fromDate+" EndDate="+strT.toDate,Key,EA_Name,Server);
    if(strT.Model!="4") {strT.Model="4"; LogOrPrint(reportMode,"Modelling set to ETWRT",Key,EA_Name,Server);}
    //int hndl = FileOpen(Key+"\\"+EA_Name+"-"+Server+"\\"+"WriteFlag",FILE_WRITE|FILE_COMMON); //if(hndl!=INVALID_HANDLE) return false;
    Sleep(99); ChartSetInteger(0, CHART_BRING_TO_TOP, true); Sleep(99);
    double lastScore=-1;
    const int MAX_CONSEC_NEG = 10; // early abort streak
    int i=0,passes=0,profits=0,losses=0,errors=0,duplicates=0,fitterCount=0,consecNeg=0;
    
    for(;i<MathMin(25,ArraySize(xmlData.RowsUnique));i++)
    {
     if(xmlData.RowsUnique[i].Score!=lastScore)
     {
      lastScore=xmlData.RowsUnique[i].Score;
      ShowPrompt("Processing Optimization...","> Running unique set # ("+IntegerToString(i+1)+") to export..."
                                             ,"Set Exports stored="+(string)ArraySize(g_allExports)+"/"+IntegerToString(passes)+" Above Threshold="+IntegerToString(fitterCount),"");
      LogOrPrint(reportMode                  ,"▶ Running unique set # ("+IntegerToString(i+1)+"). With Score="+DoubleToString(lastScore,1)
                                            +" Set Exports stored="+(string)ArraySize(g_allExports)+"/"+IntegerToString(passes)+" Above Threshold="+IntegerToString(fitterCount),Key,EA_Name,Server);
      
      int PositivePass=RunAndStoreSet(i,"Mode_Operation="+(string)OP_Standard+"\n"+"EA_Desc="+strT.Strat+"@{mode=EXPORT,"+"dt_BOOS_end="  +TimeToString(xmlData.startD,TIME_DATE)+","
                                                                                                        +"dt_FOOS_start="+TimeToString(xmlData.endD  +24*60*60,TIME_DATE)+"}\n",reportMode,g_allExports);
      //@{mode=EXPORT,dt_BOOS_end=2025.09.01,dt_FOOS_start=2025.09.30"; // Strategy Comment datetime dt_Back_OOS=0,dt_Fwrd_OOS=0;
      if(PositivePass==1)
      {
       profits++; consecNeg=0;
       int idx = ArraySize(g_allExports)-1;   // newest record is last element only added if PositivePass is 1
       if(g_allExports[idx].arf>=MinARF && g_allExports[idx].sr>=MinSR) {fitterCount++;  LogOrPrint(reportMode,"✅ Stored Set passed thresholds.",Key,EA_Name,Server);}
       else                                                                              LogOrPrint(reportMode,"⚠️ Not passing thresholds.",Key,EA_Name,Server);
      }
      else if(PositivePass==0) {losses++; consecNeg++;}
      else errors++;
      passes++;
     }
     else {duplicates++; continue;}
     // 0. consecutive errors
     if(errors>=MAX_CONSEC_NEG*1.5) {LogOrPrint(reportMode,"❌ Too many errors while running tests – aborting search...",Key,EA_Name,Server); break;}
     // 1. Ten consecutive non-profit runs *anywhere*
     if(consecNeg>=MAX_CONSEC_NEG) {LogOrPrint(reportMode,"❌ 10 consecutive non-profitable runs – aborting search...",Key,EA_Name,Server); break;}
     // 2. Enough high-quality (“fitter”) sets collected
     if(fitterCount>=SetsToExport) {LogOrPrint(reportMode,"✅ Reached "+(string)SetsToExport+" desired sets target – stopping search...",Key,EA_Name,Server); break;}
     // 3. Enough positive sets but still hunting for fitter ones
     if(profits>=SetsToExport && fitterCount<SetsToExport)
     {
      if(lastScore<MinScore) {LogOrPrint(reportMode,"📉 Score dipped below ("+DoubleToString(MinScore,1)+") – Aborting further search for desired Exports...",Key,EA_Name,Server); break;}
      if((profits+losses)>=SetsToExport*2) {LogOrPrint(reportMode,"ℹ️ ️Extra Look-ahead complete – Aborting further search for desired Exports....",Key,EA_Name,Server); break;}
     }
     // At least SetsToExport passes should happen for complicated scenarios
     if((profits+losses)>=SetsToExport*1.5)
     {
      // 4. Quality slump after at least a winners
      if(profits>0 && lastScore<MinScore) {LogOrPrint(reportMode,"📉 Score dipped below ("+DoubleToString(MinScore,1)+") – Aborting further search for desired Exports...",Key,EA_Name,Server); break;}
      // 5. High rejection rate after at least three winners
      if(profits>0 && (double)profits/(profits+losses)<0.2)
      {LogOrPrint(reportMode,"🚫 Profit hit-rate less than 20% ("+DoubleToString(100.0*(double)profits/(profits+losses),1)
                                                                 +"%) – Aborting further search for desired Exports...",Key,EA_Name,Server); break;}
     }
     if(i==MathMin(25,ArraySize(xmlData.RowsUnique))-1) LogOrPrint(reportMode,"⚠️ No more sets available to run.",Key,EA_Name,Server);
     Sleep(99); ChartSetInteger(0, CHART_BRING_TO_TOP, true); Sleep(99);
    }
    LogOrPrint(reportMode,StringFormat("✅✅✅✅✅ Export sequence complete: %d attempts – %d profitable, %d losses, %d errors, %d duplicates, %d passed thresholds."
                                                                               ,passes,profits,losses,errors,duplicates,fitterCount),Key,EA_Name,Server);
    if(ArraySize(g_allExports)>0)
    {
     SortAndTrimExports(SetsToExport,MinARF,MinSR,g_allExports);
     if(AdjustLots)
     {
      LogOrPrint(reportMode,"⚠️ Lot Adjustment to Target DD is enabled. Rerunning Shorlisted Exports...",Key,EA_Name,Server);
      int j=0;profits=losses=errors=fitterCount=0;
      ExportRecord AdjustedExports[];
      for(;j<ArraySize(g_allExports);j++)
      {
       const ExportRecord r = g_allExports[j];
       double Lots_Old = StringToDouble(ParseSetFileForInput("Lots_Input=",r.setFile));
       if(Lots_Old<0) {LogOrPrint(reportMode,"❌ Problem getting valid lot size from the stored export. Skipping export...",Key,EA_Name,Server); continue;}
       double Lots_Adjusted = NormalizeLots(Lots_Old * (TargetDD / MathMax(r.dd,1.0)),strT.symbol);
     /*if(MathAbs(Lots_Old-Lots_Adjusted)<SymbolInfoDouble(strT.symbol,SYMBOL_VOLUME_MIN))
       {
        int n = ArraySize(AdjustedExports); ArrayResize(AdjustedExports,n+1);
        AdjustedExports[n] = r; // Saving already existing export as it is
        LogOrPrint(reportMode,"⚠️ Export Drawdown DD="+DoubleToString(r.dd,0)+" in set ("+IntegerToString(j+1)+") is almost equal to Target DD. Skipping export...",Key,EA_Name,Server); 
        profits++; continue;
       }*/
       ShowPrompt("Processing Exports...","> Re-running the already stored set # ("+IntegerToString(j+1)+") to adjust export..."
                                             ,"Adjusted Set Exports stored="+(string)ArraySize(AdjustedExports)+"/"+IntegerToString(j),"");
       LogOrPrint(reportMode,"▶ Re-run start for stored set ("+IntegerToString(j+1)+") ARF="+DoubleToString(r.arf,3)+" DD="+DoubleToString(r.dd,3)
                                                                               +" OldLots="+DoubleToString(Lots_Old,2)+" → NewLots="+DoubleToString(Lots_Adjusted,2),Key,EA_Name,Server);
       int PositivePass=RunAndStoreSet(g_allExports[j].rowIndex,"Mode_Operation="+(string)OP_Standard+"\nLots_Input="+DoubleToString(Lots_Adjusted,2)+"\n",reportMode,AdjustedExports);
       if(PositivePass==1)
       {
        profits++;
        int idx = ArraySize(AdjustedExports)-1;   // newest record is last element only added if PositivePass is 1
        if(AdjustedExports[idx].arf>=MinARF && AdjustedExports[idx].sr>=MinSR) fitterCount++;
       }
       else if(PositivePass==0) {losses++;}
       else errors++;
       if(PositivePass<=0) LogOrPrint(reportMode,"❌ Re-run FAILED/Negative for row "+(string)(r.rowIndex+1),Key,EA_Name,Server);
      }
      LogOrPrint(reportMode,StringFormat("✅✅✅✅✅ Export Adjustment sequence complete: %d attempts – %d profitable, %d losses, %d errors, %d passed thresholds"
                                                                                            ,j,profits,losses,errors,fitterCount),Key,EA_Name,Server);
      if(ArraySize(AdjustedExports)>0)
      {
       SortAndTrimExports(SetsToExport,MinARF,MinSR,AdjustedExports);
       if(MoveKeptExports(AdjustedExports,Key)) LogOrPrint(reportMode,"✅ All Shortlisted and Adjusted Exports migrated & saved.",Key,EA_Name,Server);
       else                                     LogOrPrint(reportMode,"❌ Problem migrating the adjusted export package.",Key,EA_Name,Server);
      }
      else {LogOrPrint(reportMode,"❌ zero adjusted exports available after the export cycle.",Key,EA_Name,Server);}
     }
     else
     {
      if(MoveKeptExports(g_allExports,Key)) LogOrPrint(reportMode,"✅ All Shortlisted Exports migrated & saved.",Key,EA_Name,Server);
      else                                  LogOrPrint(reportMode,"❌ Problem migrating the finalized export package.",Key,EA_Name,Server);
     }
    }
    else {LogOrPrint(reportMode,"❌ zero exports available after the export cycle.",Key,EA_Name,Server);}
   }
   else {LogOrPrint(reportMode,"DEINIT: ❌ Failed to Initialize Tester for exporting SETs. Aborting...",Key,EA_Name,Server); return false;}
   return (ArraySize(g_allExports)>0); // true = exported ≥1 profitable set
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int RunAndStoreSet(int rowInd,string mode,bool reportMode,ExportRecord &expArr[],bool Init=false)
  {
   string exports[]; FindExports("TEMP",exports); DeleteExports(exports); DeleteEmptyFolders("TEMP"); Sleep(50);
   
   if(!StartTester(rowInd,mode,reportMode)) {LogOrPrint(reportMode,"❌ Failed to Configure and/or Start the Strategy Tester. Skipping...",Key,EA_Name,Server); return -1;}
   
   const datetime t0 = TimeLocal();
   while(!FindExports("TEMP",exports))
   {
    Sleep(500);
    if(TimeLocal()-t0 > 250) // 200 sec watchdog
    {
     if(!MTTESTER::IsIdle())
     {
      if(TimeLocal()-t0 > 500)
      {
       LogOrPrint(reportMode,"❌ Strategy Tester running for 500 seconds timed out waiting to become idle – aborting this set",Key,EA_Name,Server); return -1;
      }
      continue; // still running but <500s: keep waiting
     }
     LogOrPrint(reportMode,"❌ Export timeout 250 seconds – aborting this set",Key,EA_Name,Server); return -1;
    }
   }
   LogOrPrint(reportMode," Export found in "+(string)((long)TimeLocal()-(long)t0)+"s: "+FileNameOnly(exports[0]),Key,EA_Name,Server);
   
   double profit=FetchMetric(exports[0],"Prf");
   double trades=FetchMetric(exports[0],"Trds");
   
   if(Init && DoubleToString(profit,0)==DoubleToString(xmlData.Rows[0].back_profit,0))
   {
    ShowPrompt("Processing Optimization...","Top Set Verified","Running more sets for export...",""); Sleep(999);
    LogOrPrint(reportMode,"DEINIT: ✅ Top Set Export Verified, Export Profit="+DoubleToString(profit,0)+" Back Profit="+DoubleToString(xmlData.Rows[0].back_profit,0)
                                                           +", Export Trades="+DoubleToString(trades,0)+" Back Trades="+DoubleToString(xmlData.Rows[0].back_trades,0),Key,EA_Name,Server); return 1;
   }
   else if(Init) {
    ShowPrompt("Processing Optimization...","Top Set verification failed !","Running more sets for export...",""); Sleep(999);
    LogOrPrint(reportMode,"DEINIT: ❌ Export verification failed, Export Profit="+DoubleToString(profit,0)+" Back Profit="+DoubleToString(xmlData.Rows[0].back_profit,0)
                                                              +", Export Trades="+DoubleToString(trades,0)+" Back Trades="+DoubleToString(xmlData.Rows[0].back_trades,0),Key,EA_Name,Server); return 0;}
   
   if(profit>0)
   {
    // move first, because MoveExports rewrites paths
    if(!MoveExports("Exports",exports)) {LogOrPrint(reportMode,"❌ Failed to move Exports: "+FileNameOnly(exports[0]),Key,EA_Name,Server); return -1;}
    // identify csv vs set in their new locations
    string csv="",set="";
    for(int k=0;k<ArraySize(exports);k++)
    {
     if(StringFind(exports[k],".csv",0)!=-1) csv=exports[k];
     if(StringFind(exports[k],".set",0)!=-1) set=exports[k];
    }
    if(csv=="" || set=="") {LogOrPrint(reportMode," ❌ csv/set pair incomplete for Set # "+(string)rowInd,Key,EA_Name,Server); return -1;}
    // allocate new slot & fill
    int n = ArraySize(expArr); ArrayResize(expArr,n+1);
    
    expArr[n].csvFile  = csv;
    expArr[n].setFile  = set;
    expArr[n].rowIndex = rowInd;
    expArr[n].trds     = FetchMetric(exports[0],"Trds");
    expArr[n].prf      = FetchMetric(exports[0],"Prf");
    expArr[n].dd       = FetchMetric(exports[0],"DD");
    expArr[n].pf       = FetchMetric(exports[0],"PF");
    expArr[n].sr       = FetchMetric(exports[0],"SR");
    expArr[n].arf      = FetchMetric(exports[0],"ARF");
    
    LogOrPrint(reportMode,"✅ Stored Set "+(string)(rowInd+1)+" Profit="+DoubleToString(expArr[n].prf,0)+" DD=" +DoubleToString(expArr[n].dd,0)
                                                             +" SR="    +DoubleToString(expArr[n].sr,2) +" ARF="+DoubleToString(expArr[n].arf,3),Key,EA_Name,Server);
    return 1;
   }
   else
   {
    LogOrPrint(reportMode,"⚠️ Export Profit="+DoubleToString(profit,0)+"<0, Discarding Set",Key,EA_Name,Server); return 0;
   }
   return -1;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void OnTimer(void)
  {
   if(GlobalVariableGet("RefreshQueue")!=0) {TesterDialog.OnClickRefresh(true); GlobalVariableDel("RefreshQueue");}
   
   if(Mode_Operation==Operation_Dash)
   {
    DashboardDialog.ProcessTimerCycle();
    ChartRedraw(0);
   }
   timer++;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;

   int TradeCount = FindNumberOfPositions(OP_BUY,MAGIC1);
   if(Seq_Buy.Active && LastTradeCountBuy!=TradeCount && TradeCount==0 && Seq_Buy.Traded)//Seq_Buy.Level_Count>=Delay_Trade)
   {
    Seq_Buy.End_Sequence("Trade(s) closed");
   }
   LastTradeCountBuy = TradeCount;

   TradeCount = FindNumberOfPositions(OP_SELL,MAGIC1);
   if(Seq_Sell.Active && LastTradeCountSell!=TradeCount && TradeCount==0 && Seq_Sell.Traded)//Seq_Sell.Level_Count>=Delay_Trade)
   {
    Seq_Sell.End_Sequence("Trade(s) closed");
   }
   LastTradeCountSell = TradeCount;

   if(MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=MAGIC1) return;
   if(HistoryDealGetString(trans.deal,DEAL_SYMBOL)!=_Symbol) return;

   int deal_type=(int)HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   if(deal_type!=DEAL_TYPE_BUY && deal_type!=DEAL_TYPE_SELL) return;
   if(HistoryDealGetDouble(trans.deal,DEAL_VOLUME)<=0.0)     return;

   int deal_entry=(int)HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   datetime deal_time=(datetime)HistoryDealGetInteger(trans.deal,DEAL_TIME);

   if(deal_entry==DEAL_ENTRY_OUT || deal_entry==DEAL_ENTRY_OUT_BY)
   {
    DashboardBusRollClosedBuckets(deal_time);
    double closed_pl=HistoryDealGetDouble(trans.deal,DEAL_PROFIT)
                    +HistoryDealGetDouble(trans.deal,DEAL_COMMISSION)
                    +HistoryDealGetDouble(trans.deal,DEAL_SWAP);
    DashboardBusClosedPLTotal+=closed_pl;
    DashboardBusClosedTradesTotal++;
    if(deal_time>=DashboardBusDayStart)  DashboardBusClosedPLDaily +=closed_pl;
    if(deal_time>=DashboardBusWeekStart) DashboardBusClosedPLWeekly+=closed_pl;
    return;
   }

   if(deal_entry!=DEAL_ENTRY_IN) return;
   if(HistoryDealGetInteger(trans.deal,DEAL_REASON)!=DEAL_REASON_EXPERT) return;

        if(TimeCurrent()<dt_Back_OOS && dt_Back_OOS!=0) trd_BOOS++;
   else if(TimeCurrent()>dt_Fwrd_OOS && dt_Fwrd_OOS!=0) trd_FOOS++;
   else                                                 trd_IS++;
   return;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void OnChartEvent(const int id,         // event ID  
                  const long& lparam,   // event parameter of the long type
                  const double& dparam, // event parameter of the double type
                  const string& sparam) // event parameter of the string type
  {
   if(!FastSpeed_Flag)
   {
         if(Mode_Operation==Operation_Batch) TesterDialog.ChartEvent(id,lparam,dparam,sparam);
    else if(Mode_Operation==Operation_Dash)  DashboardDialog.HandleChartEvent(id,lparam,dparam,sparam);
    else                                     PanelDialog.ChartEvent(id,lparam,dparam,sparam);
  //Panel_Seq2.ChartEvent(id,lparam,dparam,sparam);
    if(id==CHARTEVENT_CHART_CHANGE)
    {
          if(Mode_Operation==Operation_Batch)   TesterDialog.maximizeWindow();
     else if(Mode_Operation!=Operation_Dash)    PanelDialog.maximizeWindow();
    }
  //if(id==CHARTEVENT_OBJECT_DRAG  && sparam==ExtDialog.Name()+"Caption") { ss=0;Comment(ss);}
    if(id==CHARTEVENT_OBJECT_CLICK)
    {
     if(Mode_Operation!=Operation_Batch && Mode_Operation!=Operation_Dash) {for(int i=0; i<ArraySize(Obj_names); i++) if(sparam==Obj_names[i]) PanelDialog.OnClickCaption();}
   //Print(sparam); Print(Key+"_BackToDB_"+(string)MAGIC1);
     //if(sparam==Key+"_BackToDB_"+(string)MAGIC1 && GlobalVariableCheck("Dashboard_ChartID"))
     //{
     //  Print("Return to DB button pressed");
     ////double DB_CID=GlobalVariableGet("Dashboard_ChartID");Print(DB_CID);Print((long)DB_CID);Print((ulong)DB_CID);Print(ChartID());
     //  if(!ChartSetInteger(ChartFirst(),CHART_BRING_TO_TOP,0,true))
     //  {
     //   Print(__FUNCTION__+", Error Code = ",GetLastError()); return;
     //  }
     //  Sleep(100); ChartRedraw(); Sleep(100); ChartRedraw(ChartFirst()); Sleep(100);
     //  ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
     //}
     //if(id==CHARTEVENT_OBJECT_CLICK && StringFind(s,PFX+"BTN_")==0) DashboardDialog.DoActivate((int)StringToInteger(StringSubstr(s,StringLen(PFX+"BTN_"))));
    }
   }
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void InitializeFlags()
  {
   timer=0;
 //TrendSig    = OP_NULL;
   BuySig      = SellSig       = false;
   PrevBuySig  = PrevSellSig   = false;
   BuyExit     = SellExit      = false;
   PrevBuyExit = PrevSellExit  = false;
   //ObjectSetText("06","- - -",Font_Size,"NULL",clrDarkGray);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void OnTick()
  {
   if(Mode_Operation==Operation_Batch || Mode_Operation==Operation_Dash) return; //return; // returning for testing
   //if(!IsLicensed())    {Alert("Trial Expired"); return;}
   //if(!FastSpeed_Flag) OnlineValidationFunction(MetatraderKey,ServerBreakDownDays,false);
   bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   tm_cur = TimeCurrent(); TimeCurrent(stm_cur);
//-------------------------------------------------------------------------
   if(IsNewDay())
   {
    days++;
    if(days==9) randB=(double)(GetTickCount()%1000)/1000;
    //if(CurrentDDD>=MaxDD) MCount=0;
    LastStopoutTime=0;
    StopOut_Flag = false;
    DStartLocalLoss = 99999;
    //ObjectSetText("06","- - -",Font_Size,"NULL",clrDarkGray);
    static datetime DLastTime;
    DStartEquity=AccountInfoDouble(ACCOUNT_EQUITY);

    if(TimeCurrent()<dt_Back_OOS && dt_Back_OOS!=0)
    {
     days_BOOS++;
     if(eq_BOOS_start==0) eq_BOOS_start = DStartEquity;
     eq_BOOS_end = DStartEquity;
     //dt_BOOS_end = DLastTime;
    }
    else if(TimeCurrent()>=dt_Fwrd_OOS && dt_Fwrd_OOS!=0)
    {
     days_FOOS++;
     if(eq_FOOS_start==0) eq_FOOS_start = DStartEquity;
     //eq_FOOS_end = DStartEquity; // fetch realtime
    }
    else
    {
     days_IS++;
     if(eq_IS_start==0) eq_IS_start = DStartEquity;
     eq_IS_end = DStartEquity;
     dt_IS_end = DLastTime;
    }
    DLastTime=TimeCurrent();
   }
//-------------------------------------------------------------------------
   /* tick-by-tick: remember the lowest equity seen since the last bar-open */
   static double MinuteLowEquity = DBL_MAX;
   MinuteLowEquity = MathMin(MinuteLowEquity,AccountInfoDouble(ACCOUNT_EQUITY));
//-------------------------------------------------------------------------
   if(IsNewMinute())
   {
    if(Mode=="EXPORT" && !MQLInfoInteger(MQL_OPTIMIZATION))
    {
     static double LastEquity=0,LastBalance=0,LastBid=bid*1.1,LastAsk=ask*1.1; // avoid divide by zero
     if(AccountInfoDouble(ACCOUNT_EQUITY)!=LastEquity || AccountInfoDouble(ACCOUNT_BALANCE)!=LastBalance)
     {
      double changeBid = MathAbs((bid-LastBid)/LastBid);
      double changeAsk = MathAbs((ask-LastAsk)/LastAsk);
      double change    = MathMax(changeBid,changeAsk);
      if(change>0.001 || (change>0.0001 && AccountInfoDouble(ACCOUNT_EQUITY)<LastEquity) || AccountInfoDouble(ACCOUNT_EQUITY)<MinuteLowEquity)
      {
       FileWrite(FileCSV_handle,TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES)
                               ,DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2)
                               ,DoubleToString(MinuteLowEquity,2)
                               ,0.0);//(AccountInfoDouble(ACCOUNT_MARGIN)/AccountInfoDouble(ACCOUNT_EQUITY))*100.0;
       LastBid=bid; LastAsk=ask;
       LastEquity=AccountInfoDouble(ACCOUNT_EQUITY); LastBalance=AccountInfoDouble(ACCOUNT_BALANCE);
      }
     }
    }
    MinuteLowEquity = AccountInfoDouble(ACCOUNT_EQUITY);   // reset for the next minute
//-------
    // sees if symbol has news
    int indices[];
    bool IsNewsTime=News.IsNewsTime(Symbol(),News_threshold,indices);   // Change Symbol to the symbol traded
    int max_news_score=0;
    for(int i=0;i<ArraySize(indices);++i)
    {
     if(indices[i]<0 || indices[i]>=ArraySize(News.TodaysNewsList)) continue;
     max_news_score=MathMax(max_news_score,News.TodaysNewsList[indices[i]].impact_score);
    }
    DashboardBusNewsScore=max_news_score;
    // We have news
    if(IsNewsTime)
    {
     if(Mode_News!=News_Display) {
     if(Mode_News==News_Avoid)
     {
      Sequence_New_News = false;
     }
     if(Mode_News==News_Pause)
     {
      Sequence_New_News = false; Sequence_Pause_News = true;
     }
     if(Mode_News==News_Close)
     {
      Sequence_New_News = false; Sequence_Pause_News = true; StopOut_Flag = true; // News own stopout
     }
     if(Mode_News==News_Only)
     {
      Sequence_New_News = true; Sequence_Pause_News = false;
     } }
     //if(!ObjectFind(0,(string)BackTestNewsStructArray[backtestnewsindex].Time))
     //VLineCreate(0,(string)BackTestNewsStructArray[backtestnewsindex].Time,0,BackTestNewsStructArray[backtestnewsindex].Time,C'80,0,0',STYLE_SOLID,3,false,false,false,0);
     if(!FastSpeed_Flag && DrawVLines)// && MQLInfoInteger(MQL_VISUAL_MODE))
     {
      if(IsNewBar2(Period()) && ObjectGetInteger(0,IntegerToString(lines_news,4,'N'),OBJPROP_TIME) != iTime(NULL,Period(),0))
      {// this printing of news window region continuous lines
       VLineCreate(0,IntegerToString(lines_news++,4,'N'),0,iTime(NULL,Period(),0),C'0,0,60',STYLE_SOLID,3,true,false,true,0);  if(lines_news>999) lines_news=0;
      }
      if(ArraySize(News.TodaysNewsList)>0)
      {
       for(int i=0;i<ArraySize(News.TodaysNewsList);i++)
       {
        datetime et = News.TodaysNewsList[i].time;

        string s = TimeToString(et,TIME_MINUTES)+" "+News.TodaysNewsList[i].currency+" "+(string)News.TodaysNewsList[i].impact_score+" "+News.TodaysNewsList[i].name;

        string Lname = "L_"+s;
        if(ObjectFind(0,Lname) < 0 || (datetime)ObjectGetInteger(0,Lname,OBJPROP_TIME) != et) VLineCreate(0,Lname,0,et,clrCrimson,STYLE_DOT,1,false,false,false,0);

        string Tname = "T_"+s;
        if(ObjectFind(0,Tname) < 0 || (datetime)ObjectGetInteger(0,Tname,OBJPROP_TIME) != et)
        {
         int    n = ArraySize(News.TodaysNewsList);
         double pmax = ChartGetDouble(0, CHART_PRICE_MAX, 0);
         double pmin = ChartGetDouble(0, CHART_PRICE_MIN, 0);
         // limit vertical placement to 20%..80% of visible price range
         double frac = (n <= 1) ? 0.5 : ((double)i / (double)(n - 1));
         double f2   = 0.2 + 0.6 * frac;                 // 0.20..0.80
         double py   = pmax - f2 * (pmax - pmin);
         TextCreate(0,Tname,0,et,py,s,"Arial",Font_Size,clrCrimson,0.0,ANCHOR_LEFT_UPPER,false,false,true,0);
        }
       }
      }
     }
    }
    else
    {
     if(Mode_News==News_Only) Sequence_New_News = false;
     else                    {Sequence_New_News = true; Sequence_Pause_News = false;}
     
     if(!FastSpeed_Flag && DrawVLines && InActive && !(stm_cur.hour==0&&stm_cur.min<=15) && !(stm_cur.hour==23&&stm_cur.min>=45)) // MQLInfoInteger(MQL_VISUAL_MODE)
     {
      // if news lines are not printed then we can draw inactive lines if inactive time
      if(IsNewBar2(Period()) && ObjectGetInteger(0,IntegerToString(lines,4,'L'),OBJPROP_TIME) != iTime(NULL,Period(),0))
      {//C'60,0,0'
       VLineCreate(0,IntegerToString(lines++,4,'L'),0,iTime(NULL,Period(),0),clrDarkSlateGray,STYLE_SOLID,3,true,false,true,0); if(lines>999) lines=0;
      }
     }
    }
    if(!FastSpeed_Flag) NewsDisplayFunction(true,clrGold);
//-------
    int idx=0;
    static int LastBias=0;
    int CurBias = Bias.GetCurentBiasScore(Symbol(),idx);
    DashboardBusBiasSentiment=0.0;
    
    if(CurBias>=-100 && CurBias<=100) // We have valid bias
    {
     DashboardBusBiasSentiment=CurBias;
     if(Mode_Bias!=Bias_Display) {
     // we disregard Bias_Disabled and Bias_Display as they are covered indirectly in other functions
     int bias_dir = 0;
     if(Bias_threshold > 0)
     {
      if(CurBias >=  Bias_threshold) bias_dir =  1;
      if(CurBias <= -Bias_threshold) bias_dir = -1;
     }
     else
     {
      if(CurBias > 0) bias_dir =  1;
      if(CurBias < 0) bias_dir = -1;
     }
     // defaults
     Sequence_New_Bias_B   = true;  Sequence_New_Bias_S   = true;    // by default, new sequence is allowed
     Sequence_Pause_Bias_B = false; Sequence_Pause_Bias_S = false;   // trade pausing is disabled
     StopOut_Flag_B        = false; StopOut_Flag_S        = false;   // stopout is disabled
     
     static int Bias_LastSign = 0; // used by Bias_Close_high sentiment-flip stopout
     
     if(Mode_Bias==Bias_Opens) // Only add sequences in bias direction
     {
      // here only opening sequence and its trades in bias direction is ensured but with threshold check if non zero threshold
      // Sequence_Pause flags are only set if Mode_Bias_Trades includes trades
      if(bias_dir ==  1) {
       Sequence_New_Bias_S = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_S = true;
      }
      else if(bias_dir == -1) {
       Sequence_New_Bias_B = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_B = true;
      }
      else
      {
       Sequence_New_Bias_B = false; Sequence_New_Bias_S = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) {Sequence_Pause_Bias_B = true; Sequence_Pause_Bias_S = true;}
      }
     }
     if(Mode_Bias==Bias_Close_low) // open restrictions with low level closing trigger
     {
      // close dormant with open abundant, opening with bias and closing on opposite extream
      if(CurBias > 0) {
       Sequence_New_Bias_S = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_S = true;
      }
      if(CurBias < 0) {
       Sequence_New_Bias_B = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_B = true;
      }
      if(Bias_threshold > 0)
      {
       if(CurBias >=  Bias_threshold) StopOut_Flag_S = true;
       if(CurBias <= -Bias_threshold) StopOut_Flag_B = true;
      }
     }
     if(Mode_Bias==Bias_Close_med) // med trade numbers since opening and closing with bias extremes
     {
      if(Bias_threshold > 0)
      {
       if(CurBias >=  Bias_threshold) {
        Sequence_New_Bias_S = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_S = true;
        StopOut_Flag_S = true;
       }
       else if(CurBias <= -Bias_threshold) {
        Sequence_New_Bias_B = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_B = true;
        StopOut_Flag_B = true;
       }
       else {
        Sequence_New_Bias_B = false; Sequence_New_Bias_S = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) {Sequence_Pause_Bias_B = true; Sequence_Pause_Bias_S = true;}
       }
      }
      else
      {
       if(CurBias > 0) {
        Sequence_New_Bias_S = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_S = true;
       }
       if(CurBias < 0) {
        Sequence_New_Bias_B = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_B = true;
       }
      }
     }
     if(Mode_Bias==Bias_Close_high) // Most restrictive: open only at extremes (if threshold>0) - stopout on sentiment flip (sign change)
     {
      bool extreme_ok = true;
      if(Bias_threshold > 0) extreme_ok = (MathAbs(CurBias) >= Bias_threshold);

      if(!extreme_ok)
      {
       Sequence_New_Bias_B = false; Sequence_New_Bias_S = false;
       if(Mode_Bias_Trades==Bias_SeqTrade) {Sequence_Pause_Bias_B = true; Sequence_Pause_Bias_S = true;}
      }
      else
      {
       if(CurBias > 0) {
        Sequence_New_Bias_S = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_S = true;
       }
       else if(CurBias < 0) {
        Sequence_New_Bias_B = false;
        if(Mode_Bias_Trades==Bias_SeqTrade) Sequence_Pause_Bias_B = true;
       }
      }
      int sign = 0;
      if(CurBias > 0) sign = 1;
      else if(CurBias < 0) sign = -1;
      if(sign != 0 && Bias_LastSign != 0 && sign != Bias_LastSign)
      {
       if(sign > 0) StopOut_Flag_S = true;   // flipped to bullish -> stop sells
       else         StopOut_Flag_B = true;   // flipped to bearish -> stop buys
      }
      if(sign != 0) Bias_LastSign = sign;
     }
     if(StopOut_Flag_B)
     {
      Sequence_New_Bias_B   = false;
      Sequence_Pause_Bias_B = true;
     }
     if(StopOut_Flag_S)
     {
      Sequence_New_Bias_S   = false;
      Sequence_Pause_Bias_S = true;
     }}
     if(!FastSpeed_Flag && DrawVLines)// && MQLInfoInteger(MQL_VISUAL_MODE))
     {
      if(IsNewBar2(Period()) && ObjectGetInteger(0,IntegerToString(lines_bias,4,'B'),OBJPROP_TIME) != iTime(NULL,Period(),0))
      {// no specific bias bar in bias case but the general bias color coded lines -100 all red to 100 all green
       // only draw bias lines if inactive lines have not been drawn first on the same bar in the news section
       int x = CurBias + 100; if(x<0) x=0; if(x>200) x=200;
       color c = (color)(((100*(200-x))/200) | (((100*x)/200)<<8));
       if(CurBias==0) c = clrGray;
       VLineCreate(0,IntegerToString(lines_bias++,4,'B'),0,iTime(NULL,Period(),0),c,STYLE_SOLID,3,true,false,true,0);  if(lines_bias>4999) lines_bias=0;
      }
      if(CurBias!=LastBias)
      {
        static int inc=0;
        string tname = "B_"+(string)inc++;
        
        if(ObjectFind(0,tname) < 0)
        {
         double ph = iHigh(NULL,Period(),iHighest(NULL,Period(),MODE_HIGH,30));
         double pl = iLow(NULL,Period(),iLowest(NULL,Period(),MODE_LOW,30));
         
         ObjectCreate(0,tname,OBJ_TEXT,0,TimeCurrent(),(bid>ph)?pl:ph);
         ObjectSetString(0,tname,OBJPROP_TEXT,"Bias="+(string)CurBias);
         ObjectSetInteger(0,tname,OBJPROP_COLOR,(CurBias>0)?clrCornflowerBlue:clrOrangeRed);//clrCrimson);
         ObjectSetInteger(0,tname,OBJPROP_ANCHOR,ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0,tname,OBJPROP_FONTSIZE,Font_Size);
         ObjectSetInteger(0,tname,OBJPROP_BACK,false);
        }
      }
     }
     LastBias=CurBias;
    }
    else
    {
     DashboardBusBiasSentiment=0.0;
     // defaults
     Sequence_New_Bias_B   = true;  Sequence_New_Bias_S   = true;
     Sequence_Pause_Bias_B = false; Sequence_Pause_Bias_S = false;
     StopOut_Flag_B        = false; StopOut_Flag_S        = false;
     // no need to redraw inactive lines as that is already covered in the news section
    }
    if(!FastSpeed_Flag) BiasDisplayFunction(true,clrGold,idx);
   }
//-------------------------------------------------------------------------
   if(IsNewSecond())
   {
    int k;
         if(stm_cur.day_of_week==1)                         k=0;
    else if(stm_cur.day_of_week==2)                         k=1;
    else if(stm_cur.day_of_week==3)                         k=2;
    else if(stm_cur.day_of_week==4)                         k=3;
    else if(stm_cur.day_of_week==5)                         k=4;
    else                                                    k=4;  // Sat-Sun same as Friday
    
    if((stm_cur.hour>Hour_Start[k]||(stm_cur.hour==Hour_Start[k]&&stm_cur.min>=Minute_Start[k])) && 
       (stm_cur.hour<Hour_End[k]  ||(stm_cur.hour==Hour_End[k]  &&stm_cur.min<Minute_End[k])))
    {
     Active=true; SetEdit(PanelDialog.m_edit_Info_2,Strat,clr_Text,Font_Size); //clr_Text=clrWhite;
     if(InActive) {Sequence_Pause_Close=false;}
    }
    else {Active=false; InActive=true; SetEdit(PanelDialog.m_edit_Info_2,"INACTIVE",clrRed,Font_Size);}//clr_Text=clrRed;}
    
    if(!Trade_Friday && (stm_cur.day_of_week==5 || stm_cur.day_of_week==5))      Sequence_New_Friday=false;
    else                                                                         Sequence_New_Friday=true;
    
    if(!Trade_December && FastSpeed_Flag && stm_cur.mon==12)                     Sequence_New_Dec=false;
    else                                                                         Sequence_New_Dec=true;
//-------
    int Trades=0,Buys=0,Sells=0;
    double OpenLots=0.0,PL_Total=0.0,PL_Buy=0.0,PL_Sell=0.0,PL_Closed=0.0,PL_Today=0.0;
    
    //if(MaxLossLocal!=0.0 || MaxDailyLossLocal!=0.0 || MaxDailyProfitLocal!=0.0 || !FastSpeed_Flag)
    {
     for(int i=PositionsTotal()-1; i>=0; i--)
     {
      //if(PositionGetTicket(i)>0)
      if(m_position.SelectByIndex(i))
      {
     //if(PositionGetString(POSITION_SYMBOL) != _Symbol)                        continue;
       if(m_position.Symbol() != _Symbol)                                       continue;
     //if(PositionGetInteger(POSITION_MAGIC) != magic && magic != 0)            continue;
       if(m_position.Magic() != MAGIC1 && MAGIC1 != 0)                          continue;
       
       Trades++;
       OpenLots+=m_position.Volume();
       if(m_position.PositionType() == POSITION_TYPE_BUY)    {Buys++;  PL_Buy += (m_position.Profit()+m_position.Commission()+m_position.Swap());}
       if(m_position.PositionType() == POSITION_TYPE_SELL)   {Sells++; PL_Sell+= (m_position.Profit()+m_position.Commission()+m_position.Swap());}
      }
     }
     PL_Total = PL_Buy+PL_Sell;//Comment(m_position.Commission());
     if(DStartLocalLoss==99999) {DStartLocalLoss=PL_Total; DStartTime=TimeCurrent();}
    }
//-------
    if(MaxDailyLossLocal!=0.0 || MaxDailyProfitLocal!=0.0)
    {
     HistorySelect(DStartTime,TimeCurrent());
     uint     total=HistoryDealsTotal();
     ulong    ticket=0;
     
     for(uint i=0;i<total;i++)
     {
      if((ticket=HistoryDealGetTicket(i))>0)
      {
       if(HistoryDealGetString(ticket,DEAL_SYMBOL) != _Symbol)       continue;
       if(HistoryDealGetInteger(ticket,DEAL_MAGIC) != MAGIC1)        continue;
       //entry =HistoryDealGetInteger(ticket,DEAL_ENTRY);
       PL_Closed+=HistoryDealGetDouble(ticket,DEAL_PROFIT)+HistoryDealGetDouble(ticket,DEAL_COMMISSION)+HistoryDealGetDouble(ticket,DEAL_SWAP);
      }
     }
     PL_Today = PL_Total-DStartLocalLoss+PL_Closed;
    }//Comment("PLTot=",PL_Total," DStart=",DStartLocalLoss," PLCld=",PL_Closed);
//-------
    double DChangeEquity = AccountInfoDouble(ACCOUNT_EQUITY)-DStartEquity;
    CurrentDDD = 100*-1*DChangeEquity/DStartEquity;
    
    if(!FastSpeed_Flag)
    {
     PrintTradeStatus(k,Buys,Sells,PL_Buy,PL_Sell);
     
     if     (CurrentDDD>0) {SetEdit(PanelDialog.m_edit_Det3_1,"Daily Change");
                            SetEdit(PanelDialog.m_edit_Det3_2,DoubleToString(DChangeEquity,1)+"  "+DoubleToString(-CurrentDDD,2)+"%",clr_Sell,Font_Size);}
     else if(CurrentDDD<0) {SetEdit(PanelDialog.m_edit_Det3_1,"Daily Change");
                            SetEdit(PanelDialog.m_edit_Det3_2,DoubleToString(DChangeEquity,1)+"  "+DoubleToString(-CurrentDDD,2)+"%",clr_Buy,Font_Size);}
     else                  {SetEdit(PanelDialog.m_edit_Det3_1,"Daily Change");
                            SetEdit(PanelDialog.m_edit_Det3_2,DoubleToString(DChangeEquity,1)+"  "+DoubleToString(-CurrentDDD,2)+"%",clr_Text,Font_Size);}
     
                        SetEdit(PanelDialog.m_edit_Det4_1,"Running P&L / Max");     SetEdit(PanelDialog.m_edit_Det4_2,DoubleToString(PL_Total,1)+" / "+DoubleToString(MaxLossLocal,0));
     //if(PL_Today==0)   {SetEdit(PanelDialog.m_edit_Det5_1,"Magic Number");          SetEdit(PanelDialog.m_edit_Det5_2,(string)MAGIC1);}
     //else              {SetEdit(PanelDialog.m_edit_Det5_1,"Daily Local P&L / Max"); SetEdit(PanelDialog.m_edit_Det5_2,DoubleToString(PL_Today,1)+" / "+DoubleToString(MaxDailyLossLocal,0));}
     SetEdit(PanelDialog.m_edit_Det5_1,"Volume Method");          //SetEdit(PanelDialog.m_edit_Det5_2,Volume_mode_String);
     switch(Mode_Lots_Prog)
     {
      case Lots_Prog_Start:SetEdit(PanelDialog.m_edit_Det5_2,"Start Lots"); break;
      case Lots_Prog_Last: SetEdit(PanelDialog.m_edit_Det5_2,"Exponential Lots"); break;
      case Lots_Prog_Cum:  SetEdit(PanelDialog.m_edit_Det5_2,"Cumulative Lots"); break;
      case Lots_Prog_Cum2: SetEdit(PanelDialog.m_edit_Det5_2,"Front-Loaded Cumulative"); break;
      case Lots_Prog_CumPartial: SetEdit(PanelDialog.m_edit_Det5_2,"Cum + Partial"); break;
      case Lots_Prog_Peak: SetEdit(PanelDialog.m_edit_Det5_2,"Peak Lots"); break;
      default:             SetEdit(PanelDialog.m_edit_Det5_2,"Unknown Mode"); break;
     }
    }
//-------
    if(!StopOut_Flag && MaxLossLocal!=0.0 && PL_Total<=-MaxLossLocal)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Max Local Running loss",Font_Size,"NULL",clrMagenta);
     Alert("Max Local Running Loss : Trading Stopped");
    }
    if(!StopOut_Flag && MaxLossGlobal!=0.0 && (AccountInfoDouble(ACCOUNT_BALANCE)-AccountInfoDouble(ACCOUNT_EQUITY))>=MaxLossGlobal)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Max Global Running loss",Font_Size,"NULL",clrMagenta);
     Alert("Max Global Running Loss : Trading Stopped");
    }
    if(!StopOut_Flag && MaxDailyLossLocal!=0.0 && PL_Today<=-MaxDailyLossLocal)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Max Local Running loss",Font_Size,"NULL",clrMagenta);
     Alert("Max Daily Local Loss Reached : Trading Stopped");
    }
    if(!StopOut_Flag && MaxDailyProfitLocal!=0.0 && PL_Today>=MaxDailyProfitLocal)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Max Local Running loss",Font_Size,"NULL",clrMagenta);
     Alert("Max Daily Local Profit Reached : Trading Stopped");
    }
    if(!StopOut_Flag && MinLevelEquity!=0.0 && AccountInfoDouble(ACCOUNT_EQUITY)<=MinLevelEquity)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Low Equity Level Reached",Font_Size,"NULL",clrMagenta);
     Alert("Low Equity Level Reached : Trading Stopped");
    }
    if(!StopOut_Flag && MaxLevelEquity!=0.0 && AccountInfoDouble(ACCOUNT_EQUITY)>=MaxLevelEquity)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Equity Target Level Reached",Font_Size,"NULL",clrMagenta);
     Alert("Equity Target Level Reached : Trading Stopped");
    }
  /*if(!StopOut_Flag && CurrentDDD>=MaxDD)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Max Daily DD",Font_Size,"NULL",clrMagenta);
     Alert("Max Daily DD Hit : Trading Stopped");
    }
    if(!StopOut_Flag && -CurrentDDD>=MaxDP)
    {
     StopOut_Flag = true;
     //ObjectSetText("06","Exit Reason: Daily Target Reached",Font_Size,"NULL",clrMagenta);
     Alert("Daily Target Reached : Trading Stopped");
    }*/
    // End of Day/session
    if(InActive && stm_cur.hour>=Hour_End[k])//&& FindNumberOfPositions(OP_BUYSELL,MAGIC1)>0)
    {
     if(Action_Dayend==Action_Close) StopOut_Flag = true;
     if(Action_Dayend==Action_Pause) Sequence_Pause_Close = true;
     //ObjectSetText("06","Exit Reason: Inactive time",Font_Size,"NULL",clrMagenta);
    }
    // End of day/session on friday
    if(InActive && stm_cur.day_of_week==5 && stm_cur.hour>=Hour_End[k])//&& FindNumberOfPositions(OP_BUYSELL,MAGIC1)>0)
    {
     if(Action_Friday==Action_Close) StopOut_Flag = true;
     if(Action_Friday==Action_Pause) Sequence_Pause_Close = true;
     //ObjectSetText("06","Exit Reason: Weekend Close",Font_Size,"NULL",clrMagenta);
    }
    //Comment(Sequence_Pause_Close);
//-------
    if(StopOut_Flag)
    {
     if(Trades>0)
     {
      CloseAllPositions(OP_BUYSELL,MAGIC1);
      Trades=FindNumberOfPositions(OP_BUYSELL,MAGIC1);
     }
     if(Trades==0 && LastStopoutTime==0)
     {
      LastStopoutTime = TimeCurrent();
      Seq_Buy.End_Sequence ("Day/Weekend Close"); Seq_Buy_Virtual.End_Sequence ("Day/Weekend Close");
      Seq_Sell.End_Sequence("Day/Weekend Close"); Seq_Sell_Virtual.End_Sequence("Day/Weekend Close");
      if(!FastSpeed_Flag) VLineCreate(0,Key+"_STOPOUT_"+TimeToString(TimeCurrent(),TIME_DATE)+" "+TimeToString(TimeCurrent(),TIME_MINUTES),0,iTime(NULL,Period(),0),clrDarkOrange,STYLE_SOLID,3,false,false,false,0);
     }
     if(Trades==0 && LastStopoutTime!=0 && (TimeCurrent()>(LastStopoutTime+Mode_Restart*60*60)) ) StopOut_Flag = false;
    }
//-------
    // Direction-specific Bias StopOut handling - Buy
    static bool Last_StopOut_Flag_B = false;
    if(StopOut_Flag_B && !Last_StopOut_Flag_B)
    {
     if(Buys>0)
     {
      if(FindNumberOfPositions(OP_BUY,MAGIC1)>0) CloseAllPositions(OP_BUY,MAGIC1);
     }
     if     (Seq_Buy.Active)         Seq_Buy.End_Sequence("Bias StopOut");
     else if(Seq_Buy_Virtual.Active) Seq_Buy_Virtual.End_Sequence("Bias StopOut");

     if(!FastSpeed_Flag)
     {
      VLineCreate(0,Key+"_STOPOUT_BIAS_B_"+TimeToString(TimeCurrent(),TIME_DATE)+" "+TimeToString(TimeCurrent(),TIME_MINUTES),0,iTime(NULL,Period(),0),clrOrangeRed,STYLE_DASH,2,false,false,false,0);
     }
    }
    Last_StopOut_Flag_B = StopOut_Flag_B;
//-------
    // Direction-specific Bias StopOut handling - Sell
    static bool Last_StopOut_Flag_S = false;
    if(StopOut_Flag_S && !Last_StopOut_Flag_S)
    {
     if(Sells>0)
     {
      if(FindNumberOfPositions(OP_SELL,MAGIC1)>0) CloseAllPositions(OP_SELL,MAGIC1);
     }
     if     (Seq_Sell.Active)         Seq_Sell.End_Sequence("Bias StopOut");
     else if(Seq_Sell_Virtual.Active) Seq_Sell_Virtual.End_Sequence("Bias StopOut");

     if(!FastSpeed_Flag)
     {
      VLineCreate(0,Key+"_STOPOUT_BIAS_S_"+TimeToString(TimeCurrent(),TIME_DATE)+" "+TimeToString(TimeCurrent(),TIME_MINUTES),0,iTime(NULL,Period(),0),clrOrangeRed,STYLE_DASH,2,false,false,false,0);
     }
    }
    Last_StopOut_Flag_S = StopOut_Flag_S;
//-------
    if(AccountInfoDouble(ACCOUNT_EQUITY) > MaxEquity)
    {
     MaxEquity = AccountInfoDouble(ACCOUNT_EQUITY);
     ArraySort(DDs_PC); ArraySort(DDs_Actual);
     //ArraySortMQL4(DDs,WHOLE_ARRAY,0,MODE_ASCEND);
    }
    CurrentDD = (MaxEquity-AccountInfoDouble(ACCOUNT_EQUITY))/MaxEquity; if(CurrentDD > DDs_PC[0])     DDs_PC[0]     = CurrentDD;
    CurrentDD = (MaxEquity-AccountInfoDouble(ACCOUNT_EQUITY));           if(CurrentDD > DDs_Actual[0]) DDs_Actual[0] = CurrentDD;

    DashboardBusRollClosedBuckets(TimeCurrent());
    if(GlobalVariableCheck("Dashboard_ChartID"))
    {
     GlobalVariableSet(GoatSymbolGVName(Symbol(),GOAT_GV_FIELD_NEWS),DashboardBusNewsScore);
     GlobalVariableSet(GoatSymbolGVName(Symbol(),GOAT_GV_FIELD_BIAS),DashboardBusBiasSentiment);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_OPEN_TRADES),(double)Trades);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_OPEN_LOTS),OpenLots);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_OPEN_PL),PL_Total);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_PL_DAILY),DashboardBusClosedPLDaily);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_PL_WEEKLY),DashboardBusClosedPLWeekly);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_PL_TOTAL),DashboardBusClosedPLTotal);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_TRADES_TOTAL),(double)DashboardBusClosedTradesTotal);
     GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_HEARTBEAT),(double)TimeCurrent());

     string dashboard_status="Active";
     if(!Active || InActive) dashboard_status="Inactive";
     if(StopOut_Flag || Pause_Flag || Sequence_Pause_Close || Sequence_Pause_News || Sequence_Pause_Bias_B || Sequence_Pause_Bias_S)
        dashboard_status="Paused";
     DashboardBusSendStatus(dashboard_status);
    }
  //PartialClose();
   }
//-------------------------------------------------------------------------
   if(CheckTrailingLockTPNow())// && Active)
   {
    if(Seq_Buy.Active && bid > Seq_Buy.Level_Lock)
    {
     if(Mode_Trail==Trail_Lock_Pro) {if(bid>Seq_Buy.Level_Lock+Seq_Buy.Size_TSL)    Seq_Buy.TrailingStoploss();}
     else                                                                           Seq_Buy.TrailingStoploss();
    }
    if(Seq_Sell.Active && ask < Seq_Sell.Level_Lock)
    {
     if(Mode_Trail==Trail_Lock_Pro) {if(ask<Seq_Sell.Level_Lock-Seq_Sell.Size_TSL)  Seq_Sell.TrailingStoploss();}
     else                                                                           Seq_Sell.TrailingStoploss();
    }
    
    if(LP_Size_<0)
    {
     if(Seq_Buy_Virtual.Active)  Seq_Buy_Virtual.UpdateLock();
     if(Seq_Sell_Virtual.Active) Seq_Sell_Virtual.UpdateLock();
    }
    
    if(Seq_Buy_Virtual.Active &&       (bid>=Seq_Buy_Virtual.Level_Lock || Seq_Buy_Virtual.Trailing))
    {
     if(Mode_Trail==Trail_Lock_Pro) {if(bid>=Seq_Buy_Virtual.Level_Lock+Seq_Buy_Virtual.Size_TSL)    Seq_Buy_Virtual.TrailingStoploss();}
     else                                                                                            Seq_Buy_Virtual.TrailingStoploss();
    }
    if(Seq_Sell_Virtual.Active &&      (ask<=Seq_Sell_Virtual.Level_Lock || Seq_Sell_Virtual.Trailing)) //ask<Seq_Sell_Virtual.Level_Lock || Seq_Sell_Virtual.Trailing)
    {
     if(Mode_Trail==Trail_Lock_Pro) {if(ask<=Seq_Sell_Virtual.Level_Lock-Seq_Sell_Virtual.Size_TSL)  Seq_Sell_Virtual.TrailingStoploss();}
     else                                                                                            Seq_Sell_Virtual.TrailingStoploss();
    }
   }
//-------------------------------------------------------------------------
   if(Seq_Buy.Active  && !Seq_Buy.Traded)
   {
    if(Seq_Buy.Level_TSL!=0.0 && bid<=Seq_Buy.Level_TSL)          Seq_Buy.End_Sequence("Trailing Virtual");
    if(Seq_Buy.Level_TP!=0.0  && bid>=Seq_Buy.Level_TP)           Seq_Buy.End_Sequence("Virtual TP");       // confirmed Bid>=
   }
   if(Seq_Sell.Active && !Seq_Sell.Traded)
   {
    if(Seq_Sell.Level_TSL!=0.0 && ask>=Seq_Sell.Level_TSL)        Seq_Sell.End_Sequence("Trailing Virtual");
    if(Seq_Sell.Level_TP!=0.0  && ask<=Seq_Sell.Level_TP)         Seq_Sell.End_Sequence("Virtual TP");
   }
   
   if(Seq_Buy_Virtual.Active)
   {
    if(InActive) Seq_Buy_Virtual.End_Sequence("InActive Time");
    if(Seq_Buy_Virtual.Level_TSL!=0.0 && bid<=Seq_Buy_Virtual.Level_TSL)   Seq_Buy_Virtual.End_Sequence("Trailing Virtual");  //confirmed Bid<=
    //if(Seq_Buy_Virtual.Level_TP!=0.0  && bid>=Seq_Buy_Virtual.Level_TP)    Seq_Buy_Virtual.End_Sequence("Virtual TP");
   }
   if(Seq_Sell_Virtual.Active)
   {
    if(InActive) Seq_Sell_Virtual.End_Sequence("InActive Time");
    if(Seq_Sell_Virtual.Level_TSL!=0.0 && ask>=Seq_Sell_Virtual.Level_TSL)  Seq_Sell_Virtual.End_Sequence("Trailing Virtual");
    //if(Seq_Sell_Virtual.Level_TP!=0.0  && ask<=Seq_Sell_Virtual.Level_TP)   Seq_Sell_Virtual.End_Sequence("Virtual TP");
   }
//-------------------------------------------------------------------------
   if( CheckSignalNow() )//|| Check_Forced)
   {
    bool checked=false;
    Shift_Sig = 1;
    
    if(!Sequence_Pause_Close&&!Sequence_Pause_News) // no need to waste computing while paused
    {
     UpdateRSI(Shift_Sig);
     
     if(EMA_MustCheck||ADX_MustCheck||BB_MustCheck||MACD_MustCheck||RSI2_MustCheck) {UpdateCurrentSignals(Shift_Sig); checked=true;}
    }
    
    if(Active)
    {
     // an adjustment for good comparison Weekend Close
     //if(Active && CloseTradesWeekend && stm_cur.day_of_week==1 && stm_cur.hour==Hour_Start[0] && stm_cur.min==Minute_Start[0]) {if(FirstRun) FirstRun=false; else return;}
     if(TimeCurrent()>Expiry) {Alert("This version expired on "+TimeToString(Expiry,TIME_DATE)+". Go to "+URL_Web+" to download the latest version."); ExpertRemove();}
     //if(!IsLicensed())    {Alert("Trial Expired"); return;}
     //if(!FastSpeed_Flag) OnlineValidationFunction(MetatraderKey,ServerBreakDownDays,false);
     SetEdit(PanelDialog.m_edit_Info_2,"Active: Checking...",clrLime,Font_Size);
     
     if(InActive) InitializeFlags();
     
     if(!checked) UpdateCurrentSignals(Shift_Sig);
     
     if(Allow_New_Sequence&&Sequence_New_Friday&&Sequence_New_Dec) SignalEntryTrigger();//Buys,Sells);
     //SignalExitTrigger();
     //OrderUpdate();
     //File_update=true;
     //if(ChartAdjust) AllDisplaySettings();
     InActive=false;
    }
    if(MQLInfoInteger(MQL_VISUAL_MODE)) ChartRedraw(0);
   }
 //else ObjectSetText(IntegerToString(TotalText_Trade-2,2,'0')," ",Font_Size-1,"NULL",clrLime);
//-------------------------------------------------------------------------
   static bool LastBuyTradeSignal=false,LastSellTradeSignal=false;
   
   if(CheckSequenceNow() && !Sequence_Pause_Close)// && Active) // close or inactivity pause takes precedence over other pause types
   {
    if(Seq_Buy.Active)
    {
     if(Seq_Buy.Traded && Mode_Lots_Prog==Lots_Prog_CumPartial && Partial_Profit_Factor>0.0 && ask >= Seq_Buy.Level_Retrace && Seq_Buy.Level_Retrace>0.0)
        Seq_Buy.HandlePartialRetrace(ask);

     if(ask < (Seq_Buy.Level_Last-GetSize(GRID_VALID,Seq_Buy.Level_Count,Seq_Buy.Size_Grid)) && ((RSI_Mode==RSI_Disabled) || RSI_Sig==OP_BUY) )// && BuySig)
     {
      if(Sequence_Pause_News)
      {
       if(!LastBuyTradeSignal) Trades_Skipped_News++; 
      }
      else if(Sequence_Pause_Bias_B)
      {
       if(!LastBuyTradeSignal) Trades_Skipped_Bias_B++;
      }
      else
      {
       Seq_Buy.Add_Level(ask); //return;
      }
      LastBuyTradeSignal = true; // we are currently in add trade condition so Last TradeSignal is true
     }
     else LastBuyTradeSignal = false; // last time sequence conditions didnt try adding a new trade
    }
    else LastBuyTradeSignal = false; // last time sequence conditions didnt try adding a new trade
//--------
    if(Seq_Sell.Active)
    {
     if(Seq_Sell.Traded && Mode_Lots_Prog==Lots_Prog_CumPartial && Partial_Profit_Factor>0.0 && bid <= Seq_Sell.Level_Retrace && Seq_Sell.Level_Retrace>0.0)
        Seq_Sell.HandlePartialRetrace(bid);

     if(bid > (Seq_Sell.Level_Last+GetSize(GRID_VALID,Seq_Sell.Level_Count,Seq_Sell.Size_Grid)) && ((RSI_Mode==RSI_Disabled) || RSI_Sig==OP_SELL) )// && SellSig)
     {
      if(Sequence_Pause_News)
      {
       if(!LastSellTradeSignal) Trades_Skipped_News++;
      }
      else if(Sequence_Pause_Bias_S)
      {
       if(!LastSellTradeSignal) Trades_Skipped_Bias_S++;
      }
      else
      {
       Seq_Sell.Add_Level(bid); //return;
      }
      LastSellTradeSignal = true; // we are currently in add trade condition so Last TradeSignal is true
     }
     else LastSellTradeSignal = false; // last time sequence conditions didnt try adding a new trade
    }
    else LastSellTradeSignal = false; // last time sequence conditions didnt try adding a new trade
//----------------------
    if(Seq_Buy_Virtual.Active && !Sequence_Pause_News && !Sequence_Pause_Bias_B)
    {
     if(ask < (Seq_Buy_Virtual.Level_Last-GetSize(GRID_VALID,Seq_Buy_Virtual.Level_Count,GetSize(GRID))) && ((RSI_Mode==RSI_Disabled) || RSI_Sig==OP_BUY) )// && BuySig)
     {
      Seq_Buy_Virtual.Add_Level(ask); //return;
     }
    }
    if(Seq_Sell_Virtual.Active && !Sequence_Pause_News && !Sequence_Pause_Bias_S)
    {
     if(bid > (Seq_Sell_Virtual.Level_Last+GetSize(GRID_VALID,Seq_Sell_Virtual.Level_Count,GetSize(GRID))) && ((RSI_Mode==RSI_Disabled) || RSI_Sig==OP_SELL) )// && SellSig)
     {
      Seq_Sell_Virtual.Add_Level(bid); //return;
     }
    }
   }
//-------------------------------------------------------------------------
   return;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void UpdateRSI(int shift)
  {
   if((RSI_Mode!=RSI_Disabled))
   {
    CopyBuffer(RSI_handle,0,shift+0,2,RSI_Buf);
    
    if(RSI_Mode==RSI_OverBS)
    {
          if(RSI_Buf[0]<=(100-RSI_Level))                                                       RSI_Sig=OP_BUY;
     else if(RSI_Buf[0]>=RSI_Level)                                                             RSI_Sig=OP_SELL;
     else                                                                                       RSI_Sig=OP_NULL;
    }
  //if(RSI_Mode==RSI_Trend)
  //{
  //      if(RSI_Buf[0]>RSI_Level)                                                              RSI_Sig=OP_BUY;
  // else if(RSI_Buf[0]<(100-RSI_Level))                                                        RSI_Sig=OP_SELL;
  // else                                                                                       RSI_Sig=OP_NULL;
  //}
    else if(RSI_Mode==RSI_OverBSCross)
    {
          if(RSI_Buf[1]<=(100-RSI_Level) && RSI_Buf[0]>(100-RSI_Level) && RSI_Buf[0]<50.0)      RSI_Sig=OP_BUY;
     else if(RSI_Buf[1]>=RSI_Level       && RSI_Buf[0]<RSI_Level       && RSI_Buf[0]>50.0)      RSI_Sig=OP_SELL;
     else                                                                                       RSI_Sig=OP_NULL;
    }
    else if(RSI_Mode==RSI_OBSCEngulf)
    {
     double CurrClose=iClose(Symbol(),RSI_TF,shift);
     double PrevOpen =iOpen(Symbol(),RSI_TF,shift+1);
     
          if(RSI_Buf[1]<=(100-RSI_Level) && RSI_Buf[0]>(100-RSI_Level) && CurrClose>PrevOpen)   RSI_Sig=OP_BUY;
     else if(RSI_Buf[1]>=RSI_Level       && RSI_Buf[0]<RSI_Level       && CurrClose<PrevOpen)   RSI_Sig=OP_SELL;
     else                                                                                       RSI_Sig=OP_NULL;
    }
    SetEdit(PanelDialog.m_edit_Ind1_1,"RSI Trend",clr_Text,Font_Size,(RSI_Sig==OP_BUY)?clr_Buy:(RSI_Sig==OP_SELL)?clr_Sell:clr_Null,(RSI_Sig==OP_BUY)?clr_Buy:(RSI_Sig==OP_SELL)?clr_Sell:clr_Null);
    SetEdit(PanelDialog.m_edit_Ind1_2,(RSI_Sig==OP_BUY)?"BUY":(RSI_Sig==OP_SELL)?"SELL":"NEUTRAL"+" ("+DoubleToString(RSI_Buf[0],1)+")"
                         ,clr_Text,Font_Size,(RSI_Sig==OP_BUY)?clr_Buy:(RSI_Sig==OP_SELL)?clr_Sell:clr_Null,(RSI_Sig==OP_BUY)?clr_Buy:(RSI_Sig==OP_SELL)?clr_Sell:clr_Null);
   }
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void UpdateCurrentSignals(int shift)
  {
   if(FastSpeed_Flag && (!Buy_EN||Seq_Buy.Traded) && (!Sell_EN||Seq_Sell.Traded) ) return;
 //if(FastSpeed_Flag && (!Buy_EN||Seq_Buy.Active) && (!Sell_EN||Seq_Sell.Active) ) return;
//-------------------------------------------------------------------------
   double CurrBar=iClose(Symbol(),PERIOD_CURRENT,shift);
   double PrevBar=iClose(Symbol(),PERIOD_CURRENT,shift+1);
//-------------------------------------------------------------------------
   if(EMA_Mode != Trade_Disabled)
   {
    static INTERVAL EMA_Sample;
    if(EMA_Sample.CheckTF(EMA_TF)) {
    
    int EMA_trend=OP_NULL;
    bool voidBuy=false,voidSell=false;
    for(int i=0;i<EMA_Count;i++)   CopyBuffer(EMA_handles[i],0,shift-0,1,EMAs[i].Buf);
    for(int i=0;i<EMA_Count;i++)
    {
     for(int j=0;j<EMA_Count;j++)
     {
      if(i>j && EMAs[i].Buf[0]>EMAs[j].Buf[0]) voidBuy=true;
      if(i<j && EMAs[i].Buf[0]>EMAs[j].Buf[0]) voidSell=true;
     }
    }
  //CopyBuffer(EMA1_handle,0,shift-0,1,EMA1_Buf); EMA1_Buf[0] = NormalizeDouble(EMA1_Buf[0],_Digits);
  //if     (EMA1_Buf[0]>EMA2_Buf[0]&&EMA2_Buf[0]>EMA3_Buf[0])  
    if     (!voidBuy)                                          {EMA_trend=OP_BUY;  SetEdit(PanelDialog.m_edit_Ind2_1,"MA Trend",clr_Text,Font_Size,clr_Buy,clr_Buy);
                                                                                   SetEdit(PanelDialog.m_edit_Ind2_2,"BUY"     ,clr_Text,Font_Size,clr_Buy,clr_Buy);}
    else if(!voidSell)                                         {EMA_trend=OP_SELL; SetEdit(PanelDialog.m_edit_Ind2_1,"MA Trend",clr_Text,Font_Size,clr_Sell,clr_Sell);
                                                                                   SetEdit(PanelDialog.m_edit_Ind2_2,"SELL"    ,clr_Text,Font_Size,clr_Sell,clr_Sell);}
    else                                                       {EMA_trend=OP_NULL; SetEdit(PanelDialog.m_edit_Ind2_1,"MA Trend",clr_Text,Font_Size,clr_Null,clr_Null);
                                                                                   SetEdit(PanelDialog.m_edit_Ind2_2,"NEUTRAL" ,clr_Text,Font_Size,clr_Null,clr_Null);}
    //if     (EMA_trend==OP_BUY  && EMA_prev_trend!=OP_BUY  && EMA_prev_trend!=OP_NIL) EMA_Sig = OP_BUY;
    //else if(EMA_trend==OP_SELL && EMA_prev_trend!=OP_SELL && EMA_prev_trend!=OP_NIL) EMA_Sig = OP_SELL;
    //else                                                                             EMA_Sig = OP_NULL;
    EMA_Sig = OP_NULL;
    
    if(EMA_trend==OP_BUY)
    {
     if(EMA_Mode==Trade_Trend   || EMA_Mode==Trade_Trend_Range)   EMA_Sig=EMA_trend;
     if(EMA_Mode==Trade_Counter || EMA_Mode==Trade_Counter_Range) EMA_Sig=OP_SELL;
    }
    else if(EMA_trend==OP_SELL)
    {
     if(EMA_Mode==Trade_Trend   || EMA_Mode==Trade_Trend_Range)   EMA_Sig=EMA_trend;
     if(EMA_Mode==Trade_Counter || EMA_Mode==Trade_Counter_Range) EMA_Sig=OP_BUY;
    }
    else if(EMA_Mode==Trade_Range || EMA_Mode==Trade_Trend_Range || EMA_Mode==Trade_Counter_Range) EMA_Sig = OP_BUYSELL;}
   }
//-------------------------------------------------------------------------
   if(ADX_Mode != Trade_Disabled)
   {
    static INTERVAL ADX_Sample;
    if(ADX_Sample.CheckTF(ADX_TF)) {
    
    CopyBuffer(ADX_handle,MAIN_LINE   ,shift+0,1,ADX_Main_Buf); ADX_Main_Buf[0] = NormalizeDouble(ADX_Main_Buf[0],_Digits);
    CopyBuffer(ADX_handle,PLUSDI_LINE ,shift+0,1,ADX_PLS_Buf);  ADX_PLS_Buf[0]  = NormalizeDouble(ADX_PLS_Buf[0],_Digits);
    CopyBuffer(ADX_handle,MINUSDI_LINE,shift+0,1,ADX_MNS_Buf);  ADX_MNS_Buf[0]  = NormalizeDouble(ADX_MNS_Buf[0],_Digits);
    int ADX_trend=OP_NULL;
    if     (ADX_Main_Buf[0]>=ADX_Level&&ADX_PLS_Buf[0]>ADX_MNS_Buf[0])     {ADX_trend=OP_BUY;   SetEdit(PanelDialog.m_edit_Ind3_1,"ADX Trend",clr_Text,Font_Size,clr_Buy,clr_Buy);
                                                                                                SetEdit(PanelDialog.m_edit_Ind3_2,"BUY"      ,clr_Text,Font_Size,clr_Buy,clr_Buy);}
    else if(ADX_Main_Buf[0]>=ADX_Level&&ADX_PLS_Buf[0]<ADX_MNS_Buf[0])     {ADX_trend=OP_SELL;  SetEdit(PanelDialog.m_edit_Ind3_1,"ADX Trend",clr_Text,Font_Size,clr_Sell,clr_Sell);
                                                                                                SetEdit(PanelDialog.m_edit_Ind3_2,"SELL"     ,clr_Text,Font_Size,clr_Sell,clr_Sell);}
    else                                                                   {ADX_trend=OP_NULL;  SetEdit(PanelDialog.m_edit_Ind3_1,"ADX Trend",clr_Text,Font_Size,clr_Null,clr_Null);
                                                                                                SetEdit(PanelDialog.m_edit_Ind3_2,"NEUTRAL"  ,clr_Text,Font_Size,clr_Null,clr_Null);}
    ADX_Sig = OP_NULL;
    
    if(ADX_trend==OP_BUY)
    {
     if(ADX_Mode==Trade_Trend   || ADX_Mode==Trade_Trend_Range)   ADX_Sig=ADX_trend;
     if(ADX_Mode==Trade_Counter || ADX_Mode==Trade_Counter_Range) ADX_Sig=OP_SELL;
    }
    else if(ADX_trend==OP_SELL)
    {
     if(ADX_Mode==Trade_Trend   || ADX_Mode==Trade_Trend_Range)   ADX_Sig=ADX_trend;
     if(ADX_Mode==Trade_Counter || ADX_Mode==Trade_Counter_Range) ADX_Sig=OP_BUY;
    }
    else if(ADX_Mode==Trade_Range || ADX_Mode==Trade_Trend_Range || ADX_Mode==Trade_Counter_Range) ADX_Sig = OP_BUYSELL;}
   }
//-------------------------------------------------------------------------
   if(BB_Mode != BB_Disabled)
   {
    static INTERVAL BB_Sample;
    if(BB_Sample.CheckTF(BB_TF)) {
    
    CopyBuffer(BB_handle,BASE_LINE ,shift,2,BB_Mi_Buf);  BB_Mi_Buf[0] = NormalizeDouble(BB_Mi_Buf[0],_Digits);
    CopyBuffer(BB_handle,UPPER_BAND,shift,2,BB_Hi_Buf);  BB_Hi_Buf[0] = NormalizeDouble(BB_Hi_Buf[0],_Digits);
    CopyBuffer(BB_handle,LOWER_BAND,shift,2,BB_Lo_Buf);  BB_Lo_Buf[0] = NormalizeDouble(BB_Lo_Buf[0],_Digits);
    //     if(CurrBar>BB_Hi_Buf[0])      {ObjectSetText("10","Price above Bollinger Channel" ,Font_Size,"NULL",clr_Text);}
    //else if(CurrBar<BB_Lo_Buf[0])      {ObjectSetText("10","Price below Bollinger Channel" ,Font_Size,"NULL",clr_Text);}
    //else                               {ObjectSetText("10","Price within Bollinger Channel",Font_Size,"NULL",clr_Text);}
    BB_Sig = OP_NULL;
    
    if(BB_Mode==BB_Channel && CurrBar>BB_Lo_Buf[0] && CurrBar<BB_Hi_Buf[0])
    {
     BB_Sig=OP_BUYSELL;
     SetEdit(PanelDialog.m_edit_Ind4_1,"BB Trend",clr_Text,Font_Size,clr_Null,clr_Null);
     SetEdit(PanelDialog.m_edit_Ind4_2,"Within Channel",clr_Text,Font_Size,clr_Null,clr_Null);
    }
    else if(BB_Mode==BB_OverBS)
    {
     if(CurrBar<BB_Lo_Buf[0]) BB_Sig=OP_BUY;
     if(CurrBar>BB_Hi_Buf[0]) BB_Sig=OP_SELL;
    }
    else if(BB_Mode==BB_Trend)
    {
     if(CurrBar<BB_Lo_Buf[0]) BB_Sig=OP_SELL;
     if(CurrBar>BB_Hi_Buf[0]) BB_Sig=OP_BUY;
    }
    if     (BB_Sig==OP_BUY)  {SetEdit(PanelDialog.m_edit_Ind4_1,"BB Trend",clr_Text,Font_Size,clr_Buy,clr_Buy);   SetEdit(PanelDialog.m_edit_Ind4_2,"BUY",clr_Text,Font_Size,clr_Buy,clr_Buy);}
    else if(BB_Sig==OP_SELL) {SetEdit(PanelDialog.m_edit_Ind4_1,"BB Trend",clr_Text,Font_Size,clr_Sell,clr_Sell); SetEdit(PanelDialog.m_edit_Ind4_2,"SELL",clr_Text,Font_Size,clr_Sell,clr_Sell);}
    else if(BB_Sig==OP_NULL) {SetEdit(PanelDialog.m_edit_Ind4_1,"BB Trend",clr_Text,Font_Size,clr_Null,clr_Null); SetEdit(PanelDialog.m_edit_Ind4_2,"NEUTRAL",clr_Text,Font_Size,clr_Null,clr_Null);}}
   }
//-------------------------------------------------------------------------
   if(MACD_Mode != Trade_Disabled)
   {
    static INTERVAL MACD_Sample;
    if(MACD_Sample.CheckTF(MACD_TF)) {
  //CopyBuffer(MACD_handle,MAIN_LINE   ,shift+0,1,MACD_Main_Buf); MACD_Main_Buf[0] = NormalizeDouble(MACD_Main_Buf[0],_Digits);
  //CopyBuffer(MACD_handle,SIGNAL_LINE ,shift+0,1,MACD_Sig_Buf);  MACD_Sig_Buf[0]  = NormalizeDouble(MACD_Sig_Buf[0],_Digits);
  //CopyBuffer(MACD_handle,3           ,shift+0,1,MACD_Main_Buf);//MACD_Main_Buf[0] = NormalizeDouble(MACD_Main_Buf[0],_Digits);
  //CopyBuffer(MACD_handle,3           ,shift+0,1,MACD_Sig_Buf); //MACD_Sig_Buf[0]  = NormalizeDouble(MACD_Sig_Buf[0],_Digits);
    CopyBuffer(MACD_handle,1           ,shift+0,1,MACD_Clr_Buf);
    
    int MACD_trend=OP_NULL;
    
    if(MACD_Clr_Buf[0]==3)  MACD_trend=OP_BUY;
    if(MACD_Clr_Buf[0]==4)  MACD_trend=OP_SELL;
    
    if     (MACD_trend==OP_BUY)    {SetEdit(PanelDialog.m_edit_Ind5_1,"MACD Trend",clr_Text,Font_Size,clr_Buy,clr_Buy);
                                    SetEdit(PanelDialog.m_edit_Ind5_2,"BUY"       ,clr_Text,Font_Size,clr_Buy,clr_Buy);}
    else if(MACD_trend==OP_SELL)   {SetEdit(PanelDialog.m_edit_Ind5_1,"MACD Trend",clr_Text,Font_Size,clr_Sell,clr_Sell);
                                    SetEdit(PanelDialog.m_edit_Ind5_2,"SELL"      ,clr_Text,Font_Size,clr_Sell,clr_Sell);}
    else if(MACD_trend==OP_NULL)   {SetEdit(PanelDialog.m_edit_Ind5_1,"MACD Trend",clr_Text,Font_Size,clr_Null,clr_Null);
                                    SetEdit(PanelDialog.m_edit_Ind5_2,"NEUTRAL"   ,clr_Text,Font_Size,clr_Null,clr_Null);}
    MACD_Sig = OP_NULL;
    
    if(MACD_trend==OP_BUY)
    {
     if(MACD_Mode==Trade_Trend   || MACD_Mode==Trade_Trend_Range)   MACD_Sig=MACD_trend;
     if(MACD_Mode==Trade_Counter || MACD_Mode==Trade_Counter_Range) MACD_Sig=OP_SELL;
    }
    else if(MACD_trend==OP_SELL)
    {
     if(MACD_Mode==Trade_Trend   || MACD_Mode==Trade_Trend_Range)   MACD_Sig=MACD_trend;
     if(MACD_Mode==Trade_Counter || MACD_Mode==Trade_Counter_Range) MACD_Sig=OP_BUY;
    }
    else if(MACD_Mode==Trade_Range || MACD_Mode==Trade_Trend_Range || MACD_Mode==Trade_Counter_Range) MACD_Sig = OP_BUYSELL;}
   }
//-------------------------------------------------------------------------
   if(RSI2_Mode != RSI_Disabled)
   {
    static INTERVAL RSI2_Sample;
    if(RSI2_Sample.CheckTF(RSI2_TF)) {
    
    CopyBuffer(RSI2_handle,0,shift+0,2,RSI2_Buf);
    
    if(RSI2_Mode==RSI_OverBS)
    {
          if(RSI2_Buf[0]<=(100-RSI2_Level))                                                     RSI2_Sig=OP_BUY;
     else if(RSI2_Buf[0]>=RSI2_Level)                                                           RSI2_Sig=OP_SELL;
     else                                                                                       RSI2_Sig=OP_NULL;
    }
  //if(RSI2_Mode==RSI_Trend)
  //{
  //      if(RSI2_Buf[0]>RSI2_Level)                                                            RSI2_Sig=OP_BUY;
  // else if(RSI2_Buf[0]<(100-RSI2_Level))                                                      RSI2_Sig=OP_SELL;
  // else                                                                                       RSI2_Sig=OP_NULL;
  //}
    else if(RSI2_Mode==RSI_OverBSCross)
    {
          if(RSI2_Buf[1]<=(100-RSI2_Level) && RSI2_Buf[0]>(100-RSI2_Level) && RSI2_Buf[0]<50.0) RSI2_Sig=OP_BUY;
     else if(RSI2_Buf[1]>=RSI2_Level       && RSI2_Buf[0]<RSI2_Level       && RSI2_Buf[0]>50.0) RSI2_Sig=OP_SELL;
     else                                                                                       RSI2_Sig=OP_NULL;
    }
    else if(RSI2_Mode==RSI_OBSCEngulf)
    {
     double CurrClose=iClose(Symbol(),RSI2_TF,shift);
     double PrevOpen =iOpen(Symbol(),RSI2_TF,shift+1);
     
          if(RSI2_Buf[1]<=(100-RSI2_Level) && RSI2_Buf[0]>(100-RSI2_Level) && CurrClose>PrevOpen)  RSI2_Sig=OP_BUY;
     else if(RSI2_Buf[1]>=RSI2_Level       && RSI2_Buf[0]<RSI2_Level       && CurrClose<PrevOpen)  RSI2_Sig=OP_SELL;
     else                                                                                          RSI2_Sig=OP_NULL;
    }
    SetEdit(PanelDialog.m_edit_Ind6_1,"RSI2 Trend",clr_Text,Font_Size,(RSI2_Sig==OP_BUY)?clr_Buy:(RSI2_Sig==OP_SELL)?clr_Sell:clr_Null,(RSI2_Sig==OP_BUY)?clr_Buy:(RSI2_Sig==OP_SELL)?clr_Sell:clr_Null);
    SetEdit(PanelDialog.m_edit_Ind6_2,(RSI2_Sig==OP_BUY)?"BUY":(RSI2_Sig==OP_SELL)?"SELL":"NEUTRAL"+" ("+DoubleToString(RSI2_Buf[0],1)+")"
                         ,clr_Text,Font_Size,(RSI2_Sig==OP_BUY)?clr_Buy:(RSI2_Sig==OP_SELL)?clr_Sell:clr_Null,(RSI2_Sig==OP_BUY)?clr_Buy:(RSI2_Sig==OP_SELL)?clr_Sell:clr_Null);}
   }
//-------------------------------------------------------------------------
   if(   ( EMA_Mode==Trade_Disabled|| !EMA_MustCheck || EMA_Sig==OP_BUY || EMA_Sig==OP_BUYSELL)
      && ( ADX_Mode==Trade_Disabled|| !ADX_MustCheck || ADX_Sig==OP_BUY || ADX_Sig==OP_BUYSELL)
      && (  BB_Mode==BB_Disabled   || !BB_MustCheck  ||  BB_Sig==OP_BUY ||  BB_Sig==OP_BUYSELL)
      && (MACD_Mode==Trade_Disabled|| !MACD_MustCheck||MACD_Sig==OP_BUY ||MACD_Sig==OP_BUYSELL)
      && (RSI2_Mode==RSI_Disabled  || !RSI2_MustCheck||RSI2_Sig==OP_BUY ||RSI2_Sig==OP_BUYSELL) ) MustCheck_Buy=true; else MustCheck_Buy=false;
      
   if(   ( EMA_Mode==Trade_Disabled|| !EMA_MustCheck || EMA_Sig==OP_SELL|| EMA_Sig==OP_BUYSELL)
      && ( ADX_Mode==Trade_Disabled|| !ADX_MustCheck || ADX_Sig==OP_SELL|| ADX_Sig==OP_BUYSELL)
      && (  BB_Mode==BB_Disabled   || !BB_MustCheck  ||  BB_Sig==OP_SELL||  BB_Sig==OP_BUYSELL)
      && (MACD_Mode==Trade_Disabled|| !MACD_MustCheck||MACD_Sig==OP_SELL||MACD_Sig==OP_BUYSELL)
      && (RSI2_Mode==RSI_Disabled  || !RSI2_MustCheck||RSI2_Sig==OP_SELL||RSI2_Sig==OP_BUYSELL) ) MustCheck_Sell=true; else MustCheck_Sell=false;
//-------------------------------------------------------------------------
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void SignalEntryTrigger()//int Buys,int Sells)
  {
   static bool LastBuySignal=false,LastSellSignal=false;
   if(//!Seq_Buy_Virtual.Active && !Seq_Buy.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Long)
         ( RSI_Mode==RSI_Disabled  || RSI_Sig==OP_BUY)
      && ( EMA_Mode==Trade_Disabled|| EMA_Sig==OP_BUY|| EMA_Sig==OP_BUYSELL)
      && ( ADX_Mode==Trade_Disabled|| ADX_Sig==OP_BUY|| ADX_Sig==OP_BUYSELL)
      && (  BB_Mode==BB_Disabled   ||  BB_Sig==OP_BUY||  BB_Sig==OP_BUYSELL)
      && (MACD_Mode==Trade_Disabled||MACD_Sig==OP_BUY||MACD_Sig==OP_BUYSELL)
      && (RSI2_Mode==RSI_Disabled  ||RSI2_Sig==OP_BUY||RSI2_Sig==OP_BUYSELL))
   {
    if(Sequence_New_News&&Sequence_New_Bias_B)
    {
     if(Reverse_Seq)
     {
      //virtual or real sequences not open, correct direction, no open trades in the same direction from other charts
      if(!Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short) && FindNumberOfPositions(OP_SELL)<=0)
      {
       if(MathAbs(Delay_Trade)>0)                      Seq_Sell_Virtual.Add_Level(bid);
       else if(Allow_Opposite_Seq || !Seq_Buy.Traded)  Seq_Sell.Add_Level(bid);
      }
     }
     else if(!Seq_Buy_Virtual.Active && !Seq_Buy.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Long) && FindNumberOfPositions(OP_BUY)<=0)
     {
      if(MathAbs(Delay_Trade)>0)                       Seq_Buy_Virtual.Add_Level(ask);
      else if(Allow_Opposite_Seq || !Seq_Sell.Traded)  Seq_Buy.Add_Level(ask);
     }
    }
    else
    {
     if(!Sequence_New_News&&!LastBuySignal)   Sequence_Skipped_News++;
     if(!Sequence_New_Bias_B&&!LastBuySignal) Sequence_Skipped_Bias_B++;
    }
    LastBuySignal=true; // whether skipped of not the signal was present
   }
   else LastBuySignal=false;
//-------------------------------------------------------------------------
   if(//!Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short)
         ( RSI_Mode==RSI_Disabled  || RSI_Sig==OP_SELL)
      && ( EMA_Mode==Trade_Disabled|| EMA_Sig==OP_SELL|| EMA_Sig==OP_BUYSELL)
      && ( ADX_Mode==Trade_Disabled|| ADX_Sig==OP_SELL|| ADX_Sig==OP_BUYSELL)
      && (  BB_Mode==BB_Disabled   ||  BB_Sig==OP_SELL||  BB_Sig==OP_BUYSELL)
      && (MACD_Mode==Trade_Disabled||MACD_Sig==OP_SELL||MACD_Sig==OP_BUYSELL)
      && (RSI2_Mode==RSI_Disabled  ||RSI2_Sig==OP_SELL||RSI2_Sig==OP_BUYSELL))
   {
    if(Sequence_New_News&&Sequence_New_Bias_S)
    {
     if(Reverse_Seq)
     {
      if(!Seq_Buy_Virtual.Active && !Seq_Buy.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Long) && FindNumberOfPositions(OP_BUY)<=0)
      {
       if(MathAbs(Delay_Trade)>0)                      Seq_Buy_Virtual.Add_Level(ask);
       else if(Allow_Opposite_Seq || !Seq_Sell.Traded) Seq_Buy.Add_Level(ask);
      }
     }
     else if(!Seq_Sell_Virtual.Active && !Seq_Sell.Active && (Mode_Trade==Long_and_Short || Mode_Trade==Short) && FindNumberOfPositions(OP_SELL)<=0)
     {
      if(MathAbs(Delay_Trade)>0)                       Seq_Sell_Virtual.Add_Level(bid);
      else if(Allow_Opposite_Seq || !Seq_Buy.Traded)   Seq_Sell.Add_Level(bid);
     }
    }
    else
    {
     if(!Sequence_New_News&&!LastSellSignal)   Sequence_Skipped_News++;
     if(!Sequence_New_Bias_S&&!LastSellSignal) Sequence_Skipped_Bias_S++;
    }
    LastSellSignal=true; // whether skipped of not the signal was present
   }
   else LastSellSignal=false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CloseAllPositions(int OP,int magic=0)
  {
   CTrade m_trade;
   //CPositionInfo   m_position;                   // object of CPositionInfo class
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
    //if(PositionGetTicket(i)>0)
    if(m_position.SelectByIndex(i))
    {
   //if(PositionGetString(POSITION_SYMBOL) != _Symbol)                        continue;
     if(m_position.Symbol() != _Symbol)                                       continue;
   //if(PositionGetInteger(POSITION_MAGIC) != magic && magic != 0)            continue;
     if(m_position.Magic() != magic && magic != 0)                            continue;
     if(m_position.PositionType() != OP && OP != OP_BUYSELL)                  continue;
     
     if(!m_trade.PositionClose(m_position.Ticket())) // close a position by the specified symbol
      closeErrors++;
     closed++;
    }
   }
   Pause_Flag=true;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int FindNumberOfPositions(int OP,int magic=0)
  {
   //CPositionInfo   m_position;                   // object of CPositionInfo class
   int Buys=0,Sells=0;
   
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
    //if(PositionGetTicket(i)>0)
    if(m_position.SelectByIndex(i))
    {
   //if(PositionGetString(POSITION_SYMBOL) != _Symbol)                        continue;
     if(m_position.Symbol() != _Symbol)                                       continue;
   //if(PositionGetInteger(POSITION_MAGIC) != magic && magic != 0)            continue;
     if(m_position.Magic() != magic && magic != 0)                            continue;
     
     if(m_position.PositionType() == POSITION_TYPE_BUY)     Buys++;
     if(m_position.PositionType() == POSITION_TYPE_SELL)    Sells++;
    }
   }
   
   if(OP == OP_BUY)         return Buys;
   if(OP == OP_SELL)        return Sells;
   if(OP == OP_BUYSELL)  return Buys+Sells;
   return Buys+Sells;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
ulong ResolveLivePositionTicket(int OP,int magic,double expectedVolume,string desc,ulong orderTicket,ulong dealTicket)
  {
   if(orderTicket>0 && PositionSelectByTicket(orderTicket))
      return (ulong)PositionGetInteger(POSITION_TICKET);

   if(dealTicket>0 && HistoryDealSelect(dealTicket))
   {
    ulong position_id = (ulong)HistoryDealGetInteger(dealTicket,DEAL_POSITION_ID);
    if(position_id>0 && PositionSelectByTicket(position_id))
       return (ulong)PositionGetInteger(POSITION_TICKET);
   }

   double volTol = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(volTol<=0.0) volTol = 0.01;

   for(int attempt=0; attempt<10; attempt++)
   {
    ulong bestTicket = 0;
    long  bestTime = -1;
    for(int i=PositionsTotal()-1; i>=0; i--)
    {
     if(!m_position.SelectByIndex(i)) continue;
     if(m_position.Symbol()!=_Symbol) continue;
     if(m_position.Magic()!=magic && magic!=0) continue;
     if(m_position.PositionType()!=OP) continue;

     double posVol = PositionGetDouble(POSITION_VOLUME);
     string posComment = PositionGetString(POSITION_COMMENT);
     bool volMatch = (expectedVolume<=0.0 || MathAbs(posVol-expectedVolume)<=volTol*0.5);
     bool descMatch = (desc!="" && posComment==desc);
     if(!volMatch && !descMatch) continue;

     long posTime = (long)PositionGetInteger(POSITION_TIME);
     if(descMatch) posTime += 1000000000;
     if(posTime>=bestTime)
     {
      bestTime = posTime;
      bestTicket = (ulong)PositionGetInteger(POSITION_TICKET);
     }
    }
    if(bestTicket>0) return bestTicket;
    Sleep(50);
   }

   return orderTicket;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void CalculateAllPendingOrders(int &count_buy_limits,int &count_sell_limits,int &count_buy_stops,int &count_sell_stops)
  {
   count_buy_limits  = 0;
   count_sell_limits = 0;
   count_buy_stops   = 0;
   count_sell_stops  = 0;
   for(int i=OrdersTotal()-1; i>=0; i--) // returns the number of current orders
      if(m_order.SelectByIndex(i))     // selects the pending order by index for further access to its properties
         //if(m_order.Symbol()==m_symbol.Name() && m_order.Magic()==InpMagic)
        {
         if(m_order.OrderType()==ORDER_TYPE_BUY_LIMIT)
            count_buy_limits++;
         else
            if(m_order.OrderType()==ORDER_TYPE_SELL_LIMIT)
               count_sell_limits++;
            else
               if(m_order.OrderType()==ORDER_TYPE_BUY_STOP)
                  count_buy_stops++;
               else
                  if(m_order.OrderType()==ORDER_TYPE_SELL_STOP)
                     count_sell_stops++;
        }
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
int OpenPosition(int OP,int magic,double lots,double Level_SL,double Size_SL,double Size_TP,string desc)
  {
   //if((100*AccountInfoDouble(ACCOUNT_MARGIN))/AccountInfoDouble(ACCOUNT_EQUITY)>=Max_Margin) {LastRetCode=741; return 0;}
   if(SymbolInfoInteger(Symbol(),SYMBOL_SPREAD)>MaxSP) return 0;
   if(StopOut_Flag) {LastRetCode=740; return 0;}
   
   int ret=0;
   double SL=0,TP=0;
   Lots_Order=lots;
   double requestedVolume = GetNormalizedLots(Lots_Order);
   static ENUM_ORDER_TYPE_FILLING TypeFillingOpen = -1;//ORDER_FILLING_IOC;
   
   if(MathAbs(lots)<SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN)) {Lots_Order=LastOpen=LastSL=LastTP=0; LastOrderTicket=0; return 1;} // 0 lots added successfully
   
   MqlTradeRequest request;   ZeroMemory(request);
   MqlTradeResult  result;    ZeroMemory(result);
   
   if(OP == POSITION_TYPE_BUY)
   {
    if(ArrowDraw){
     ArrowCreate(0,IntegerToString(arrows++,3,'U'),0,0,bid,233,ANCHOR_TOP,clrBlue,STYLE_DOT,1,false,false,true,0);
     if(ObjectFind(0,IntegerToString(arrows-99,3,'U')) >= 0) ArrowDelete(0,IntegerToString(arrows-99,3,'U'));}
    
    if(Level_SL==0) {SL=NormalizeDouble(ask-Size_SL,_Digits); if(SL>ask) return 0; if(SL==ask) SL=0;}
    else             SL=Level_SL;
    
    double TP=NormalizeDouble(ask+Size_TP,_Digits); if(TP==ask) TP=0;
    
    request.action = TRADE_ACTION_DEAL;                  // Immediate Deal in
    request.magic = magic;                               // Magic Number
  //request.order = ;                                    // Order ticket
    request.symbol = _Symbol;                            // Symbol
    request.volume = requestedVolume;                    // Requested volume for a deal in lots
    request.price = NormalizeDouble(ask,_Digits);        // Lastest Bid price
  //request.stoplimit = ;                                // StopLimit level of the order
    request.sl = SL;                                     // Stop Loss
    request.tp = TP;                                     // Take Profit
    request.deviation = 5;                               // Maximal possible deviation from the requested price
    request.type = ORDER_TYPE_BUY;                       // Sell order
  //if(TypeFillingOpen==0)  TypeFillingOpen=
    SetTypeFillingBySymbol(Symbol(),TypeFillingOpen);
    FillingCheckAndSet(Symbol(),TypeFillingOpen,request,result);
    request.type_filling = TypeFillingOpen;              // Order execution type
  //request.type_filling = ORDER_FILLING_FOK|ORDER_FILLING_IOC;   // Order execution type
  //request.type_time = ;                                // Order expiration type
  //request.expiration = ;                               // Order expiration time (for the orders of ORDER_TIME_SPECIFIED type)
    request.comment = FastSpeed_Flag?"":desc;
  //request.position = ;                                 // Position ticket
  //request.position_by = ;                              // The ticket of an opposite position
    
    bool sent = OrderSend(request,result);
    if(result.retcode!=10008&&result.retcode!=10009) orderErrors++;
    else{
     ret++;
     LastSL=SL; LastTP=TP;
     LastOrderTicket=(int)ResolveLivePositionTicket(OP,magic,requestedVolume,desc,(ulong)result.order,(ulong)result.deal);
     LastDealTicket=LastBuyTicket=(int)result.deal;
   //Print(PositionSelectByTicket(LastOrderTicket)+" "+LastOrderTicket+" "+LastDealTicket+" "+PositionGetInteger(POSITION_TICKET)+" "+PositionGetInteger(POSITION_IDENTIFIER));
   //LastTradeTime = tm_cur;
   //TradesInSession++;
   //TradesInDay++;
    }
    LastRetCode=result.retcode;
    orders++;
   }
//-------------------------------------------------------------------------
   if(OP == POSITION_TYPE_SELL)
   {
    if(ArrowDraw){
     ArrowCreate(0,IntegerToString(arrows++,3,'D'),0,0,ask,234,ANCHOR_BOTTOM,clrRed,STYLE_DOT,1,false,false,true,0);
     if(ObjectFind(0,IntegerToString(arrows-99,3,'D')) >= 0) ArrowDelete(0,IntegerToString(arrows-99,3,'D'));}
    
    if(Level_SL==0) {SL=NormalizeDouble(bid+Size_SL,_Digits); if(SL<bid) return 0; if(SL==bid) SL=0;}
    else             SL=Level_SL;
    
    double TP=NormalizeDouble(bid-Size_TP,_Digits); if(TP==bid) TP=0;
    
    request.action = TRADE_ACTION_DEAL;                  // Immediate Deal in
    request.magic = magic;                               // Magic Number
  //request.order = ;                                    // Order ticket
    request.symbol = _Symbol;                            // Symbol
    request.volume = requestedVolume;                    // Requested volume for a deal in lots
    request.price = NormalizeDouble(bid,_Digits);        // Lastest Bid price
  //request.stoplimit = ;                                // StopLimit level of the order
    request.sl = SL;                                     // Stop Loss
    request.tp = TP;                                     // Take Profit
    request.deviation = 5;                               // Maximal possible deviation from the requested price
    request.type = ORDER_TYPE_SELL;                      // Sell order
  //if(TypeFillingOpen==0)  TypeFillingOpen=
    SetTypeFillingBySymbol(Symbol(),TypeFillingOpen);
    FillingCheckAndSet(Symbol(),TypeFillingOpen,request,result);
    request.type_filling = TypeFillingOpen;              // Order execution type
  //request.type_filling = ORDER_FILLING_FOK|ORDER_FILLING_IOC;   // Order execution type
  //request.type_time = ;                                // Order expiration type
  //request.expiration = ;                               // Order expiration time (for the orders of ORDER_TIME_SPECIFIED type)
    request.comment = FastSpeed_Flag?"":desc;
  //request.position = ;                                 // Position ticket
  //request.position_by = ;                              // The ticket of an opposite position
    
    bool sent = OrderSend(request,result);
    if(result.retcode!=10008&&result.retcode!=10009) orderErrors++;
    else{
     ret++;
     LastSL=SL; LastTP=TP;
     LastOrderTicket=(int)ResolveLivePositionTicket(OP,magic,requestedVolume,desc,(ulong)result.order,(ulong)result.deal);
     LastDealTicket=LastSellTicket=(int)result.deal;
   //LastTradeTime = tm_cur;
   //TradesInSession++;
   //TradesInDay++;
    }
    LastRetCode=result.retcode;
    orders++;
   }
   if(LastOrderTicket>0 && PositionSelectByTicket((ulong)LastOrderTicket))
      LastOpen=PositionGetDouble(POSITION_PRICE_OPEN);
   else
      LastOpen=0.0;
   Pause_Flag=true;
   //ObjectSetText("06","- - -",Font_Size,"NULL",clr_Text);
   return ret;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool SetTypeFillingBySymbol(const string symbol,ENUM_ORDER_TYPE_FILLING &m_type_filling)
  {
//--- get possible filling policy types by symbol
   uint filling=(uint)SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE);
   if((filling&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
     {
      m_type_filling=ORDER_FILLING_FOK;
      return(true);
     }
   if((filling&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
     {
      m_type_filling=ORDER_FILLING_IOC;
      return(true);
     }
//---
   return(false);
  }
//-------------------------------------------------------------------------
bool FillingCheckAndSet(string symbol,ENUM_ORDER_TYPE_FILLING &m_type_filling,MqlTradeRequest &m_request,MqlTradeResult &m_result)
  {
   /*int F_M = (int)SymbolInfoInteger(sym,SYMBOL_FILLING_MODE);
   switch(F_M)
   {
    case SYMBOL_FILLING_FOK: return Filling_M = SYMBOL_FILLING_FOK;   // 1. Fill or Kill
    case SYMBOL_FILLING_IOC: return Filling_M = SYMBOL_FILLING_IOC;   // 2. Immediate or Cancel
    case SYMBOL_FILLING_BOC: return Filling_M = SYMBOL_FILLING_BOC;   // 4. Passive (Book-or-Cancel)
    default:                 return Filling_M = SYMBOL_FILLING_IOC;   // 2. Most Cases
   }*/
//--- get execution mode of orders by symbol
   ENUM_SYMBOL_TRADE_EXECUTION exec=(ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE);
//--- check execution mode
   if(exec==SYMBOL_TRADE_EXECUTION_REQUEST || exec==SYMBOL_TRADE_EXECUTION_INSTANT)
     {
      //--- neccessary filling type will be placed automatically
      return(true);
     }
//--- get possible filling policy types by symbol
   uint filling=(uint)SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE);
//--- check execution mode again
   if(exec==SYMBOL_TRADE_EXECUTION_MARKET)
     {
      //--- for the MARKET execution mode
      //--- analyze order
      if(m_request.action!=TRADE_ACTION_PENDING)
        {
         //--- in case of instant execution order
         //--- if the required filling policy is supported, add it to the request
         if((filling&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
           {
            m_type_filling=ORDER_FILLING_FOK;
            m_request.type_filling=m_type_filling;
            return(true);
           }
         if((filling&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
           {
            m_type_filling=ORDER_FILLING_IOC;
            m_request.type_filling=m_type_filling;
            return(true);
           }
         //--- wrong filling policy, set error code
         m_result.retcode=TRADE_RETCODE_INVALID_FILL;
         return(false);
        }
      return(true);
     }
//--- EXCHANGE execution mode
   switch(m_type_filling)
     {
      case ORDER_FILLING_FOK:
         //--- analyze order
         if(m_request.action==TRADE_ACTION_PENDING)
           {
            //--- in case of pending order
            //--- add the expiration mode to the request
            if(!ExpirationCheck(symbol,m_request,m_result))
               m_request.type_time=ORDER_TIME_DAY;
            //--- stop order?
            if(m_request.type==ORDER_TYPE_BUY_STOP || m_request.type==ORDER_TYPE_SELL_STOP ||
               m_request.type==ORDER_TYPE_BUY_LIMIT || m_request.type==ORDER_TYPE_SELL_LIMIT)
              {
               //--- in case of stop order
               //--- add the corresponding filling policy to the request
               m_request.type_filling=ORDER_FILLING_RETURN;
               return(true);
              }
           }
         //--- in case of limit order or instant execution order
         //--- if the required filling policy is supported, add it to the request
         if((filling&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
           {
            m_request.type_filling=m_type_filling;
            return(true);
           }
         //--- wrong filling policy, set error code
         m_result.retcode=TRADE_RETCODE_INVALID_FILL;
         return(false);
      case ORDER_FILLING_IOC:
         //--- analyze order
         if(m_request.action==TRADE_ACTION_PENDING)
           {
            //--- in case of pending order
            //--- add the expiration mode to the request
            if(!ExpirationCheck(symbol,m_request,m_result))
               m_request.type_time=ORDER_TIME_DAY;
            //--- stop order?
            if(m_request.type==ORDER_TYPE_BUY_STOP || m_request.type==ORDER_TYPE_SELL_STOP ||
               m_request.type==ORDER_TYPE_BUY_LIMIT || m_request.type==ORDER_TYPE_SELL_LIMIT)
              {
               //--- in case of stop order
               //--- add the corresponding filling policy to the request
               m_request.type_filling=ORDER_FILLING_RETURN;
               return(true);
              }
           }
         //--- in case of limit order or instant execution order
         //--- if the required filling policy is supported, add it to the request
         if((filling&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
           {
            m_request.type_filling=m_type_filling;
            return(true);
           }
         //--- wrong filling policy, set error code
         m_result.retcode=TRADE_RETCODE_INVALID_FILL;
         return(false);
      case ORDER_FILLING_RETURN:
         //--- add filling policy to the request
         m_request.type_filling=m_type_filling;
         return(true);
     }
//--- unknown execution mode, set error code
   m_result.retcode=TRADE_RETCODE_ERROR;
   return(false);
  }
//+------------------------------------------------------------------+
//| Check expiration type of pending order                           |
//-------------------------------------------------------------------------
bool ExpirationCheck(const string symbol,MqlTradeRequest &m_request,MqlTradeResult &m_result)
  {
//--- check symbol
   string symbol_name=(symbol==NULL) ? _Symbol : symbol;
//--- get flags
   long tmp_long;
   int  flags=0;
   if(SymbolInfoInteger(symbol_name,SYMBOL_EXPIRATION_MODE,tmp_long))
      flags=(int)tmp_long;
//--- check type
   switch(m_request.type_time)
     {
      case ORDER_TIME_GTC:
         if((flags&SYMBOL_EXPIRATION_GTC)!=0)
            return(true);
         break;
      case ORDER_TIME_DAY:
         if((flags&SYMBOL_EXPIRATION_DAY)!=0)
            return(true);
         break;
      case ORDER_TIME_SPECIFIED:
         if((flags&SYMBOL_EXPIRATION_SPECIFIED)!=0)
            return(true);
         break;
      case ORDER_TIME_SPECIFIED_DAY:
         if((flags&SYMBOL_EXPIRATION_SPECIFIED_DAY)!=0)
            return(true);
         break;
      default:
         Print(__FUNCTION__+": Unknown expiration type");
     }
//--- failed
   return(false);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
double GetNormalizedLots(double size)
  {
   size /= SymbolInfoDouble(Symbol(),SYMBOL_VOLUME_MIN);
   size = MathRound(size);
   return size*SymbolInfoDouble(Symbol(),SYMBOL_VOLUME_MIN);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//double GetOrderLots(int OP,double Size_SL,int magic=0)
//  {
//        if(Mode_Lots == FixedLots)     return Lots_Order = Lots;
//   else if(Mode_Lots == ScaledLots)    return Lots_Order = Lots*AccountInfoDouble(ACCOUNT_EQUITY)/1000;
//   //if(Size_SL==0) {Print("Failure: Lot Sizing method is SL dependent but SL is set to zero"); ExpertRemove();}
//   else if(Mode_Lots == PercentageRisk)return (Risk*0.01*AccountInfoDouble(ACCOUNT_EQUITY))/((Size_SL/_Point)*SymbolInfoDouble(Symbol(),SYMBOL_TRADE_TICK_VALUE));
//   else if(Mode_Lots == FixedRisk)     return (Risk)/((Size_SL/_Point)*SymbolInfoDouble(Symbol(),SYMBOL_TRADE_TICK_VALUE));
//   return Lots_Order;
//  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
double GetSize(int type,int level_count=0,double grid_size=0)
  {
   if(Grid_Size<0||LP_Size_<0||SL_Pips_<0||TP_Pips_<0||TSL_Size_<0||Grid_Min_<0||Grid_Max_<0)
   {
    static double LastATRBid,LastATRAsk;
    if((bid!=LastATRBid || ask!=LastATRAsk) && !Seq_Buy.Active && !Seq_Sell.Active)// && !Seq_Buy_Virtual.Active && !Seq_Sell_Virtual.Active)
    {/*
      int bc = BarsCalculated(ATR_MA_handle);
      bool need_fix = (bc<=0 || !MathIsValidNumber(ATR_Buf[0]) || ATR_Buf[0]==0.0);
      if(need_fix)
      {
         ChartRedraw(0);                         // force redraw (nudge calc)
         MqlTick tk; SymbolInfoTick(_Symbol, tk); // refresh tick snapshot
         double tmp[1] = {0.0};
         if(CopyBuffer(ATR_MA_handle, 0, 0, 1, tmp)!=1 || !MathIsValidNumber(tmp[0]) || tmp[0]==0.0)
         {
            IndicatorRelease(ATR_MA_handle);
            ATR_MA_handle = iATR(_Symbol, _Period, ATR_Period);
            uint t0 = GetTickCount();
            while(BarsCalculated(ATR_MA_handle)<=0 && (GetTickCount()-t0)<250) ChartRedraw(0);
            if(CopyBuffer(ATR_MA_handle, 0, 0, 1, tmp)==1 && MathIsValidNumber(tmp[0]) && tmp[0]!=0.0) ATR_Buf[0] = tmp[0];
         }
         else {ATR_Buf[0] = tmp[0];}
      }*/
     CopyBuffer(ATR_MA_handle,0,1,1,ATR_Buf); ATR_Pips = NormalizeDouble(ATR_Buf[0]/(_Point*10.0),1);
     if(!FastSpeed_Flag) SetEdit(PanelDialog.m_edit_Det6_2,DoubleToString(ATR_Pips,1));
     CopyBuffer(ATR_MA_handle,0,0,1,ATR_Buf); ATR_Pips = NormalizeDouble(ATR_Buf[0]/(_Point*10),1);
     LastATRBid=bid; LastATRAsk=ask;
    }
   }
   if(type==GRID)
   {
    if(Grid_Size>0)        return  Grid_Size*10*Point();//*(MathPow(Grid_Exponent,StepCount-1));
    else                   return -Grid_Size*ATR_Buf[0];//ATR_Pips*10*Point();//*(MathPow(Grid_Exponent,StepCount-1));
   }
   if(type==GRID_MIN)
   {
    if(Grid_Min_>0)        return  Grid_Min_*10*Point();
    else                   return -Grid_Min_*ATR_Buf[0];
   }
   if(type==GRID_MAX)
   {
    if(Grid_Max_>0)        return  Grid_Max_*10*Point();
    else                   return -Grid_Max_*ATR_Buf[0];
   }
   if(type==GRID_VALID)
   {
      const int N = (Max_Seq_Trades>0) ? Max_Seq_Trades : 1;
      double w2=(double)level_count/(double)N, w1=1.0-w2;
      // convert exponents → frequencies, blend, then invert
      if(Grid_Exponent <= 0.0) return GetSize(GRID);        // fallback
      double f_eff = w1*(1.0/Grid_Exponent) + w2*(1.0/(Grid_Exponent*Grid_Factor));
      if(f_eff <= 1e-12 && f_eff >= -1e-12) f_eff = (f_eff<0 ? -1e-12 : 1e-12); // chatGPT recommended check
      double g_eff = 1.0 / f_eff;
    //double size  = grid_size*MathPow(Grid_Exponent,level_count-1);
      double size  = grid_size * MathPow(g_eff,level_count-1);
      size = MathMax(size,GetSize(GRID_MIN));
      size = MathMin(size,GetSize(GRID_MAX));
      return size;
   }
   if(type==LOCK)
   {
         if(LP_Size_>0)    return  LP_Size_*10*Point();
    else if(LP_Size_==0)   return  0;
    else                   return -LP_Size_*ATR_Buf[0];
   }
   if(type==OP_TP)
   {
         if(TP_Pips_>0)    return  TP_Pips_*10*Point();
    else if(TP_Pips_==0)   return  0;
    else                   return -TP_Pips_*ATR_Buf[0];
   }
   if(type==OP_SL)
   {
         if(SL_Pips_>0)    return  SL_Pips_*10*Point();
    else if(SL_Pips_==0)   return  0;
    else                   return -SL_Pips_*ATR_Buf[0];
   }
   if(type==TSL)
   {
         if(TSL_Size_>0)   return  TSL_Size_*10*Point();
    else if(TSL_Size_==0)  return  0;
    else                   return -TSL_Size_*ATR_Buf[0];
   }
   return 0;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void PrintTradeStatus(int k,int buys,int sells,double PL_Buy,double PL_Sell)
  {
     if(Seq_Buy_Virtual.Active)
     {
      SetEdit(PanelDialog.m_edit_Buy1_2,"Active (Virtual)");
      SetEdit(PanelDialog.m_edit_Buy2_1,"Virtual Positions"); SetEdit(PanelDialog.m_edit_Buy2_2,(string)Seq_Buy_Virtual.Level_Count+"/"+(string)Delay_Trade);
      SetEdit(PanelDialog.m_edit_Buy3_1," ");                 SetEdit(PanelDialog.m_edit_Buy3_2," ");
     }
     else if(Seq_Buy.Active)
     {
      SetEdit(PanelDialog.m_edit_Buy1_2,(Seq_Buy.Traded)?"Active":"Active (Delayed)");
      SetEdit(PanelDialog.m_edit_Buy2_1,(Seq_Buy.Traded)?"Open Positions":"Delayed Positions");
      SetEdit(PanelDialog.m_edit_Buy2_2,(Seq_Buy.Traded)?(string)buys+"/"+(string)(Seq_Buy.Level_Count-Delay_Trade_Live):(string)Seq_Buy.Level_Count+"/"+(string)Delay_Trade_Live);
      SetEdit(PanelDialog.m_edit_Buy3_1,"Open P/L");          SetEdit(PanelDialog.m_edit_Buy3_2,DoubleToString(PL_Buy,1));
     }
     else if(Buy_EN)
     {
      SetEdit(PanelDialog.m_edit_Buy1_2,"Enabled");
      SetEdit(PanelDialog.m_edit_Buy2_1,Active?"Searching for signal...":"Waiting...");   SetEdit(PanelDialog.m_edit_Buy2_2," ");
      SetEdit(PanelDialog.m_edit_Buy3_1," ");                                             SetEdit(PanelDialog.m_edit_Buy3_2," ");
     }
//-------------------------------------------------------------------------
     if(Seq_Sell_Virtual.Active)
     {
      SetEdit(PanelDialog.m_edit_Sell1_2,"Active (Virtual)");
      SetEdit(PanelDialog.m_edit_Sell2_1,"Virtual Positions"); SetEdit(PanelDialog.m_edit_Sell2_2,(string)Seq_Sell_Virtual.Level_Count+"/"+(string)Delay_Trade);
      SetEdit(PanelDialog.m_edit_Sell3_1," ");                 SetEdit(PanelDialog.m_edit_Sell3_2," ");
     }
     else if(Seq_Sell.Active)
     {
      SetEdit(PanelDialog.m_edit_Sell1_2,(Seq_Sell.Traded)?"Active":"Active (Delayed)");
      SetEdit(PanelDialog.m_edit_Sell2_1,(Seq_Sell.Traded)?"Open Positions":"Delayed Positions");
      SetEdit(PanelDialog.m_edit_Sell2_2,(Seq_Sell.Traded)?(string)sells+"/"+(string)(Seq_Sell.Level_Count-Delay_Trade_Live):(string)Seq_Sell.Level_Count+"/"+(string)Delay_Trade_Live);
      SetEdit(PanelDialog.m_edit_Sell3_1,"Open P/L");          SetEdit(PanelDialog.m_edit_Sell3_2,DoubleToString(PL_Sell,1));
     }
     else if(Sell_EN)
     {
      SetEdit(PanelDialog.m_edit_Sell1_2,"Enabled");
      SetEdit(PanelDialog.m_edit_Sell2_1,Active?"Searching for signal...":"Waiting...");  SetEdit(PanelDialog.m_edit_Sell2_2," ");
      SetEdit(PanelDialog.m_edit_Sell3_1," ");                                            SetEdit(PanelDialog.m_edit_Sell3_2," ");
     }
//-------------------------------------------------------------------------
   SetEdit(PanelDialog.m_edit_Det1_1,"Current Time");       SetEdit(PanelDialog.m_edit_Det1_2,((stm_cur.hour<10)?("0"+(string)stm_cur.hour):(string)stm_cur.hour)+":"
                                                                     +((stm_cur.min<10) ?("0"+(string)stm_cur.min) :(string)stm_cur.min)+":"
                                                                     +((stm_cur.sec<10) ?("0"+(string)stm_cur.sec) :(string)stm_cur.sec)     );
   int x = MathMax(0,stm_cur.day_of_week-1);
   string times=IntegerToString(Hour_Start[x],2,'0')+":"+IntegerToString(Minute_Start[x],2,'0')+"-"+IntegerToString(Hour_End[x],2,'0')+":"+IntegerToString(Minute_End[x],2,'0');
   SetEdit(PanelDialog.m_edit_Det2_1,"Today's Schedule");   SetEdit(PanelDialog.m_edit_Det2_2,times);
   
   if(Grid_Size<0||LP_Size_<0||SL_Pips_<0||TP_Pips_<0||TSL_Size_<0||Grid_Min_<0||Grid_Max_<0)
   SetEdit(PanelDialog.m_edit_Det6_1,"ATR pips");
   //if(MQLInfoInteger(MQL_OPTIMIZATION)) return;
   //if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return;
   /*
   ObjectSetText("01","Sp="+(string)SymbolInfoInteger(Symbol(),SYMBOL_SPREAD)+" | "
                           +((stm_cur.hour<10)?("0"+(string)stm_cur.hour):(string)stm_cur.hour)+":"
                           +((stm_cur.min<10) ?("0"+(string)stm_cur.min) :(string)stm_cur.min)+":"
                           +((stm_cur.sec<10) ?("0"+(string)stm_cur.sec) :(string)stm_cur.sec)                                ,Font_Size_Header,"NULL",clrOlive);
   ObjectSetText("02","Orders="       +(string)(orders-orderErrors)          +"/"+(string)orders
                     +" TPs="         +(string)(TPmodifieds-TPmodifyErrors)  +"/"+(string)TPmodifieds
                     +" TSLs="        +(string)(TSLmodifieds-TSLmodifyErrors)+"/"+(string)TSLmodifieds
                     +" Closed="      +(string)(closed-closeErrors)          +"/"+(string)closed                              ,Font_Size,"NULL",clr_Text);
 //ObjectSetText("03","Triggers="+(string)(Triggers-TriggerDiscarded)+"/"+(string)Triggers
 //                 +" Signals=" +(string)(Signals-SignalDiscarded)  +"/"+(string)Signals                                     ,Font_Size,"NULL",clr_Text);
   ObjectSetText("03","Equity="+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),1)
                    +" Margin="+DoubleToString(100*AccountInfoDouble(ACCOUNT_MARGIN)/AccountInfoDouble(ACCOUNT_EQUITY),1)+"%",Font_Size,"NULL",clr_Text);
   if(SymbolInfoInteger(Symbol(),SYMBOL_SPREAD)>=MaxSP)  ObjectSetText("05","Spread Filter Active, Sp="  +(string)SymbolInfoInteger(Symbol(),SYMBOL_SPREAD),Font_Size,"NULL",clrMagenta);
   else                                                  ObjectSetText("05","Spread Filter Inactive, Sp="+(string)SymbolInfoInteger(Symbol(),SYMBOL_SPREAD),Font_Size,"NULL",clr_Text);
   if(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))       ObjectSetText(IntegerToString(TotalText_Trade-3,2,'0'),"Algo Trading ON" ,Font_Size,"NULL",clrGreen);
   else                                                  ObjectSetText(IntegerToString(TotalText_Trade-3,2,'0'),"Algo Trading OFF",Font_Size,"NULL",clrRed);
   if(MQLInfoInteger(MQL_TRADE_ALLOWED))                 ObjectSetText(IntegerToString(TotalText_Trade-4,2,'0'),"EA Allowed"      ,Font_Size,"NULL",clrGreen);
   else                                                  ObjectSetText(IntegerToString(TotalText_Trade-4,2,'0'),"EA not Allowed"  ,Font_Size,"NULL",clrRed);*/
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool chartShowGrid = false;
bool chartShowPeriodSep = true;
bool chartAutoScroll = true;
bool chartShift = true;
bool chartShowAsk = true;
bool chartShowBid = true;
color clr_chart_back=clrBlack,clr_chart_fore=clrWhite,clr_bull=clrLime,clr_bear=clrWhite;

void AllDisplaySettings()
  {
   if(Mode_Operation==Operation_Standard)
   {
    clr_chart_back=C'22,26,37'; clr_bull=C'42,162,154'; clr_bear=C'231,86,83';
    ChartSetInteger(0,CHART_COLOR_CHART_LINE,clrWhite);
    if(!MQLInfoInteger(MQL_VISUAL_MODE))
    ChartSetInteger(0,CHART_COLOR_STOP_LEVEL,clrNONE);
    ChartSetInteger(0,CHART_SHOW_TRADE_LEVELS,0);
    ChartSetInteger(0,CHART_SCALE,0);
   }
   ChartSetInteger(0,CHART_SHOW_GRID      ,chartShowGrid);
   ChartSetInteger(0,CHART_SHOW_PERIOD_SEP,chartShowPeriodSep);
   ChartSetInteger(0,CHART_AUTOSCROLL     ,chartAutoScroll);
 //if(TextCorner==CORNER_RIGHT_LOWER||CORNER_RIGHT_UPPER) chartShift=true;
   ChartSetInteger(0,CHART_SHIFT          ,chartShift);
   ChartSetDouble (0,CHART_SHIFT_SIZE     ,5);
   ChartSetInteger(0,CHART_SHOW_ASK_LINE  ,chartShowAsk);
   ChartSetInteger(0,CHART_SHOW_BID_LINE  ,chartShowBid);
   
   ChartSetInteger(0,CHART_MODE,CHART_CANDLES);
   
   ChartSetInteger(0,CHART_COLOR_CHART_UP   ,clr_bull);
   ChartSetInteger(0,CHART_COLOR_CANDLE_BULL,clr_bull);
   ChartSetInteger(0,CHART_COLOR_CHART_DOWN ,clr_bear);
   ChartSetInteger(0,CHART_COLOR_CANDLE_BEAR,clr_bear);
   
   ChartSetInteger(0,CHART_COLOR_BACKGROUND,clr_chart_back);
   ChartSetInteger(0,CHART_COLOR_FOREGROUND,clr_chart_fore);
   
   ChartRedraw();
  }
void GUI_BG_Display()
  {
   ChartSetInteger(0,CHART_COLOR_CHART_LINE,clrNONE);
   ChartSetInteger(0,CHART_COLOR_STOP_LEVEL,clrNONE);
   ChartSetInteger(0,CHART_SHOW_TRADE_LEVELS,0);
   
   ChartSetInteger(0,CHART_SHOW_GRID      ,false);
   ChartSetInteger(0,CHART_SHOW_PERIOD_SEP,false);
   ChartSetInteger(0,CHART_SHOW_ASK_LINE  ,false);
   ChartSetInteger(0,CHART_SHOW_BID_LINE  ,false);
 //ChartSetInteger(0,CHART_MODE,CHART_CANDLES);
   ChartSetInteger(0,CHART_COLOR_CHART_UP   ,clrNONE);
   ChartSetInteger(0,CHART_COLOR_CANDLE_BULL,clrNONE);
   ChartSetInteger(0,CHART_COLOR_CHART_DOWN ,clrNONE);
   ChartSetInteger(0,CHART_COLOR_CANDLE_BEAR,clrNONE);
   
   ChartSetInteger(0,CHART_COLOR_BACKGROUND,clrBlack);
   ChartSetInteger(0,CHART_COLOR_FOREGROUND,clrWhite);
   
   ChartRedraw();
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
class CPanelDialog : public CAppDialog
{
//private:
public:
   CRect             m_rect_Minimized;
   
   CButton           m_button_DB;
   CButton           m_button_Buy_close, m_button_Buy_allow;
   CButton           m_button_Sell_close,m_button_Sell_allow;
   CButton           m_button_Lots_Viewer;
   
   CEdit             m_edit_Dash_1 ,m_edit_Dash_2;
   CEdit             m_edit_Info_1 ,m_edit_Info_2;
   CEdit             m_edit_Buy1_1 ,m_edit_Buy1_2;
   CEdit             m_edit_Buy2_1 ,m_edit_Buy2_2;
   CEdit             m_edit_Buy3_1 ,m_edit_Buy3_2;
   CEdit             m_edit_Sell1_1,m_edit_Sell1_2;
   CEdit             m_edit_Sell2_1,m_edit_Sell2_2;
   CEdit             m_edit_Sell3_1,m_edit_Sell3_2;
   CEdit             m_edit_Indicators;
   CEdit             m_edit_Ind1_1 ,m_edit_Ind1_2;
   CEdit             m_edit_Ind2_1 ,m_edit_Ind2_2;
   CEdit             m_edit_Ind3_1 ,m_edit_Ind3_2;
   CEdit             m_edit_Ind4_1 ,m_edit_Ind4_2;
   CEdit             m_edit_Ind5_1 ,m_edit_Ind5_2;
   CEdit             m_edit_Ind6_1 ,m_edit_Ind6_2;
   CEdit             m_edit_Ind7_1 ,m_edit_Ind7_2;
   CEdit             m_edit_Ind8_1 ,m_edit_Ind8_2;
   CEdit             m_edit_Ind9_1 ,m_edit_Ind9_2;
   CEdit             m_edit_Details;
   CEdit             m_edit_Det1_1 ,m_edit_Det1_2;
   CEdit             m_edit_Det2_1 ,m_edit_Det2_2;
   CEdit             m_edit_Det3_1 ,m_edit_Det3_2;
   CEdit             m_edit_Det4_1 ,m_edit_Det4_2;
   CEdit             m_edit_Det5_1 ,m_edit_Det5_2;
   CEdit             m_edit_Det6_1 ,m_edit_Det6_2;
   CEdit             m_edit_Det7_1 ,m_edit_Det7_2;
   CEdit             m_edit_Det8_1 ,m_edit_Det8_2;
   CEdit             m_edit_Det9_1 ,m_edit_Det9_2;
   CEdit             m_edit_Bias;      // (used as BIAS header)
   CEdit             m_edit_Bias1;     // (used as BIAS: Current)
   CEdit             m_edit_Bias2;     // (used as BIAS: Last)
   CEdit             m_edit_Bias3;     // spacer
   //--- NEWS section
   CEdit             m_edit_News;      // NEWS header
   CListView         m_list_News;      // 5-row listview
   CEdit             m_edit_New1;      // spacer
   //CButton           m_button1;                       // the button object
   //CButton           m_button2;                       // the button object
   //CBmpButton        m_bmpbutton1;                    // CBmpButton object
   // Layout parameters
   string Key_,EA_Name_,Server_;
   int D_Width,D_Height;//,Font_Size;
   //color clr_CaptionBack,clr_CaptionBorder,clr_ClientBack,clr_ClientBorder,clr_Text;
   CPanelDialog(void) {}
  ~CPanelDialog(void) {/*Typically Destroy is called in OnDeinit*/}
   //--- create
   virtual bool      Create(const long chart,const string name,const int subwin,const int x1,const int y1,const int x2,const int y2);
   void              SetFlags(const string _Key_,const string _EA_Name_,const string _Server_,const int _Font_Size_,const int D_Width_,const int D_Height_)
                     {/*Key_=_Key_; EA_Name_=_EA_Name_; Server_=_Server_; Font_Size=_Font_Size_; D_Width=D_Width_; D_Height=D_Height_;*/}
   //--- chart event handler
   virtual bool      OnEvent(const int id,const long &lparam,const double &dparam,const string &sparam);
   void              OnClickCaption(void)
   {
    //if(m_minimized) ExtDialog.maximizeWindow();
    //else            ExtDialog.minimizeWindow();
   }
   void maximizeWindow(void)   {this.Maximize();}
   void minimizeWindow(void)   {this.Minimize();}
   protected:
   void              SetCaptionClientColors();
   bool              CreateBiEditRow(CEdit &edit1,CEdit &edit2   ,int height,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font);
   bool              CreateEditRow  (CEdit &edit1                ,int height,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font);
   bool              CreateButton   (CButton &Button1,string text,int height,int width,int y,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font);
   //bool            CreateButton2(void);
   //bool            CreateBmpButton1(void);
   //--- handlers of the dependent controls events
   void              OnClickCloseBuy(void);
   void              OnClickCloseSell(void);
   void              OnClickLotsViewer(void);
   void              OnClickBackToDB(void);
   //void            OnClickButton2(void);
   //void            OnClickBmpButton1(void);
   //void            WriteLog(string text,bool print,string Key_,string EA_Name_,string Server_);
   //bool            UpdateBatchQueueAndWriteConfigFile(bool init)
private:
   // Helper creation methods
   //void CreateLabel(CLabel &lbl, const string text, int x, int y, int width=130);
   //void CreateCombo(CComboBox &cmb, const string name, int x, int y, int width=160);
   //void CreateDatePick(CDatePicker &dtp, const string name, int x, int y, int width=160);
   //void CreateEditBox(CEdit &edt, const string name, int x, int y, int width=60, string def="");
   //void CreateButtonCtrl(CButton &btn, const string name, int x, int y, int width, int height, string caption);
   //void CreateListView(CListView &listV, const string name, int x, int y, int width, int height, string caption);
   bool CreateListView(CListView &listV, const string name, int x, int y, int width, int height);
};
//+------------------------------------------------------------------+
EVENT_MAP_BEGIN(CPanelDialog)
   ON_EVENT(ON_CLICK,m_button_Buy_close ,OnClickCloseBuy)
   ON_EVENT(ON_CLICK,m_button_Sell_close,OnClickCloseSell)
   ON_EVENT(ON_CLICK,m_button_Lots_Viewer,OnClickLotsViewer)
   ON_EVENT(ON_CLICK,m_button_DB,OnClickBackToDB)
   //ON_EVENT(ON_CLICK,CaptionObjPanel,OnClickCaption)
   //ON_EVENT(ON_CLICK,m_bmpbutton1,OnClickBmpButton1)
EVENT_MAP_END(CAppDialog)
//+------------------------------------------------------------------+
CPanelDialog PanelDialog;
CEdit CaptionObjPanel;
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool CPanelDialog::Create(const long chart,const string name,const int subwin,const int x1,const int y1,const int x2,const int y2)
  {
   if(TimeCurrent()>Expiry) {Alert("This version expired on "+TimeToString(Expiry,TIME_DATE)+". Go to "+URL_Web+" to download the latest version."); ExpertRemove();}
   Vertical_Pointer=INDENT_TOP;
   //GlobalVariableSet("CaptionHeight",0.05*D_Height);
   if(!CAppDialog::Create(chart,name,subwin,x1,y1,x2,y2))
   {
      Print("Failed to create Panel: ", GetLastError());
      return(false);
   }
   //GlobalVariableDel("CaptionHeight");
   //Caption(Key_+" - Optimization Studio");
   SetCaptionClientColors();
//--- create dependent controls
   if(GlobalVariableCheck("Dashboard_ChartID")) {
   if(!CreateBiEditRow(PanelDialog.m_edit_Dash_1 ,m_edit_Dash_2 ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);    Vertical_Pointer+=GAP_Y;
   if(!CreateButton   (m_button_DB,"Return to Dashboard"      ,20,BUTTON_WIDTH*4,24,true,clrSteelBlue,clrWhite,clr_Text,Font_Size,Font_Text))return(false);
   /*GlobalVariableSet(Symbol()+"_"+IntegerToString(MAGIC1)+"_New",(double)MAGIC1);*/}
   if(!CreateBiEditRow(PanelDialog.m_edit_Info_1 ,m_edit_Info_2 ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);    Vertical_Pointer+=GAP_Y;
   if(Buy_EN) {
   if(!CreateBiEditRow(PanelDialog.m_edit_Buy1_1 ,m_edit_Buy1_2 ,20,true,clr_Buy    ,clr_Buy       ,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateButton   (m_button_Buy_close,"Close",18,BUTTON_WIDTH,19,true,clr_Buy   ,clrWhite      ,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Buy2_1 ,m_edit_Buy2_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Buy3_1 ,m_edit_Buy3_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);} //Vertical_Pointer++;
   if(Sell_EN) {
   if(!CreateBiEditRow(PanelDialog.m_edit_Sell1_1,m_edit_Sell1_2,20,true,clr_Sell   ,clr_Sell      ,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateButton   (m_button_Sell_close,"Close",18,BUTTON_WIDTH,19,true,clr_Sell ,clrWhite      ,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Sell2_1,m_edit_Sell2_2,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Sell3_1,m_edit_Sell3_2,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);}   Vertical_Pointer+=GAP_Y;
   
   if(!CreateEditRow  (PanelDialog.m_edit_Indicators            ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size+1,Font_SubHeader))    return(false);
   
   if(RSI_Mode!=RSI_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind1_1 ,m_edit_Ind1_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind1_1.TextAlign(ALIGN_CENTER); m_edit_Ind1_2.TextAlign(ALIGN_CENTER);}
   if(EMA_Mode!=Trade_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind2_1 ,m_edit_Ind2_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind2_1.TextAlign(ALIGN_CENTER); m_edit_Ind2_2.TextAlign(ALIGN_CENTER);}
   if(ADX_Mode!=Trade_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind3_1 ,m_edit_Ind3_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind3_1.TextAlign(ALIGN_CENTER); m_edit_Ind3_2.TextAlign(ALIGN_CENTER);}
   if(BB_Mode!=BB_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind4_1 ,m_edit_Ind4_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind4_1.TextAlign(ALIGN_CENTER); m_edit_Ind4_2.TextAlign(ALIGN_CENTER);}
   if(MACD_Mode!=Trade_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind5_1 ,m_edit_Ind5_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind5_1.TextAlign(ALIGN_CENTER); m_edit_Ind5_2.TextAlign(ALIGN_CENTER);}
   if(RSI2_Mode!=RSI_Disabled)
  {if(!CreateBiEditRow(PanelDialog.m_edit_Ind6_1 ,m_edit_Ind6_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   m_edit_Ind6_1.TextAlign(ALIGN_CENTER); m_edit_Ind6_2.TextAlign(ALIGN_CENTER);}
   
   if(!CreateBiEditRow(PanelDialog.m_edit_Ind7_1 ,m_edit_Ind7_2 ,10,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);    Vertical_Pointer+=GAP_Y;
   
   if(!CreateEditRow  (PanelDialog.m_edit_Details               ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size+1,Font_SubHeader))    return(false);    Vertical_Pointer++;
   
   if(!CreateBiEditRow(PanelDialog.m_edit_Det1_1 ,m_edit_Det1_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   //m_edit_Det1_1.TextAlign(ALIGN_CENTER); m_edit_Det1_2.TextAlign(ALIGN_CENTER);
   if(!CreateBiEditRow(PanelDialog.m_edit_Det2_1 ,m_edit_Det2_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   //m_edit_Det2_1.TextAlign(ALIGN_CENTER); m_edit_Det2_2.TextAlign(ALIGN_CENTER);
   if(!CreateBiEditRow(PanelDialog.m_edit_Det3_1 ,m_edit_Det3_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   //m_edit_Det3_1.TextAlign(ALIGN_CENTER); m_edit_Det3_2.TextAlign(ALIGN_CENTER);
   if(!CreateBiEditRow(PanelDialog.m_edit_Det4_1 ,m_edit_Det4_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Det5_1 ,m_edit_Det5_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateButton   (m_button_Lots_Viewer,"View",18,BUTTON_WIDTH,19,true,clr_RowBack,clrWhite    ,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(Grid_Size<0||LP_Size_<0||SL_Pips_<0||TP_Pips_<0||TSL_Size_<0||Grid_Min_<0||Grid_Max_<0)
   if(!CreateBiEditRow(PanelDialog.m_edit_Det6_1 ,m_edit_Det6_2 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   if(!CreateBiEditRow(PanelDialog.m_edit_Det7_1 ,m_edit_Det7_2 ,10,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);
   
   if(Mode_Bias!=Bias_Disabled) {                                                                                                                              Vertical_Pointer+=GAP_Y;
   if(!CreateEditRow  (PanelDialog.m_edit_Bias                  ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size+1,Font_SubHeader))    return(false);    Vertical_Pointer++;
   if(!CreateEditRow  (PanelDialog.m_edit_Bias1                 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);    //m_edit_Bias1.TextAlign(ALIGN_LEFT);
   if(!CreateEditRow  (PanelDialog.m_edit_Bias2                 ,18,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);    //m_edit_Bias2.TextAlign(ALIGN_LEFT);
   if(!CreateEditRow  (PanelDialog.m_edit_Bias3                 ,10,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);}
   
   if(Mode_News!=News_Disabled) {                                                                                                                              Vertical_Pointer+=GAP_Y;
   if(!CreateEditRow  (PanelDialog.m_edit_News                  ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_SubHeader))    return(false);    Vertical_Pointer++;
   int list_x      = INDENT_LEFT+1;
   int list_y      = Vertical_Pointer+1;
   int list_w      = (PANEL_WIDTH-10) - INDENT_RIGHT - INDENT_LEFT;
   int list_h      = 3*22 + 2; // 3 visible rows

   if(!CreateListView(PanelDialog.m_list_News,"list_news",list_x,list_y,list_w,list_h))                                                      return(false);    Vertical_Pointer += list_h;
   if(!CreateEditRow (PanelDialog.m_edit_New1                   ,10,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size  ,Font_Text))         return(false);}

   //if(!CreateBiEditRow(PanelDialog.m_edit_Foot_1 ,m_edit_Foot_2 ,22,true,clr_RowBack,clr_RowBorders,clr_Text,Font_Size+2,Font_Header))       return(false);    //Vertical_Pointer+=3;
   //if(!CreateButton1())                                     return(false);
   //if(!CreateButton2())                                     return(false);
   int PANEL_HEIGHT_NEW = CONTROLS_DIALOG_CAPTION_HEIGHT+Vertical_Pointer+6;  // 3+3 pixel border top+bottom
   
   m_norm_rect.Height(PANEL_HEIGHT_NEW);
 //ExtDialog.Height(Vertical_Pointer);
 //ExtDialog.Move  (INDENT_HORI,CHART_HEIGHT-PANEL_HEIGHT_NEW-INDENT_VERT);
   PanelDialog.Move  (INDENT_HORI,20);
 //m_norm_rect.Move(INDENT_HORI,CHART_HEIGHT-PANEL_HEIGHT_NEW-INDENT_VERT);
   m_norm_rect.Move(INDENT_HORI,20);
   //ExtDialog.minimizeWindow();
   //ExtDialog.maximizeWindow();
   //Comment(ExtDialog.Left()," ",ExtDialog.Top());
   m_min_rect.SetBound(PanelDialog.Left(),
                       PanelDialog.Top(),
                       PanelDialog.Left()+PANEL_WIDTH,
                       //m_min_rect.bottom
                       PanelDialog.Top()+CONTROLS_DIALOG_CAPTION_HEIGHT+4);
   m_min_rect.Width(PANEL_WIDTH);
   PanelDialog.maximizeWindow();
   //Rebound();
   ChartSetInteger(0,CHART_SHOW_ONE_CLICK,false);
   ChartRedraw();
   // Show the dialog
   Show(); Sleep(50);
   return(true);
  }
//+------------------------------------------------------------------+
void CPanelDialog::SetCaptionClientColors(void)
  {
   string prefix=Name();
   int total=PanelDialog.ControlsTotal();
   for(int i=0;i<total;i++)
   {
    CWnd*obj=PanelDialog.Control(i);
    string name=obj.Name();
    //---
    if(name==prefix+"Caption")
    {
     CEdit *edit=(CEdit*) obj;
     CaptionObjPanel = edit;
     //color clr=(color)GETRGB(XRGB(rand()%255,rand()%255,rand()%255));
     edit.ColorBackground(clr_CaptionBack);
     edit.ColorBorder(clr_CaptionBorder);
     edit.Color(clr_Text);
     edit.Font(GetFontName(Font_Header));
     edit.FontSize(Font_Size+2);
    }
    //---
    if(name==prefix+"Client")
    {
     CWndClient *wndclient=(CWndClient*) obj;
     //color clr=(color)GETRGB(XRGB(rand()%255,rand()%255,rand()%255));
     wndclient.ColorBackground(clr_ClientBack);
     wndclient.ColorBorder(clr_ClientBorder);
    }
   }
   ChartRedraw();
   return;
  }
//+------------------------------------------------------------------+
string Obj_names[];
bool CPanelDialog::CreateBiEditRow(CEdit &edit1,CEdit &edit2,int height,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font)
  {
//--- coordinates
   int x1=INDENT_LEFT,                                            y1=Vertical_Pointer;
   int x2=(PANEL_WIDTH-8)/2,                                      y2=Vertical_Pointer=y1+height;
   
   static int x=0;
   string number=IntegerToString(x,2,'0');      x++;
   
   if(!edit1.Create(0,"edit_L_"+number,0,x1,y1,x2-GAP_X,y2))                  return(false);
   if(!Add(edit1))                                                            return(false);
   
   edit1.ReadOnly(true);edit1.Text(" ");edit1.ColorBackground(cback); edit1.ColorBorder(cborder); edit1.Color(ctext); edit1.Font(GetFontName(font)); edit1.FontSize(Fsize); edit1.TextAlign(ALIGN_LEFT);
   
   if(!edit2.Create(0,"edit_R_"+number,0,x2+GAP_X,y1,x2*2-INDENT_RIGHT,y2))   return(false);
   if(!Add(edit2))                                                            return(false);
   
   edit2.ReadOnly(true);edit2.Text(" ");edit2.ColorBackground(cback); edit2.ColorBorder(cborder); edit2.Color(ctext); edit2.Font(GetFontName(font)); edit2.FontSize(Fsize); edit2.TextAlign(ALIGN_RIGHT);
   
   ArrayResize(Obj_names,ArraySize(Obj_names)+1); Obj_names[ArraySize(Obj_names)-1]="edit_L_"+number;
   ArrayResize(Obj_names,ArraySize(Obj_names)+1); Obj_names[ArraySize(Obj_names)-1]="edit_R_"+number;
//--- succeed
   return(true);
  }
//+------------------------------------------------------------------+
bool CPanelDialog::CreateEditRow(CEdit &edit1,int height,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font)
  {
//--- coordinates
   int x1=INDENT_LEFT,                                            y1=Vertical_Pointer;
   int x2=(PANEL_WIDTH-8),                                        y2=Vertical_Pointer=y1+height;
   
   static int x=0;
   string number=IntegerToString(x,2,'0');      x++;
   
   if(!edit1.Create(0,"edit_"+number,0,x1,y1,x2-INDENT_RIGHT,y2))             return(false);
   if(!Add(edit1))                                                            return(false);
   
   edit1.ReadOnly(true);edit1.Text(" ");edit1.ColorBackground(cback); edit1.ColorBorder(cborder); edit1.Color(ctext); edit1.Font(GetFontName(font)); edit1.FontSize(Fsize); edit1.TextAlign(ALIGN_CENTER);
   
   ArrayResize(Obj_names,ArraySize(Obj_names)+1); Obj_names[ArraySize(Obj_names)-1]="edit_"+number;
//--- succeed
   return(true);
  }
//+------------------------------------------------------------------+
bool CPanelDialog::CreateButton(CButton &Button1,string text,int height,int width,int y,bool readOnly,color cback,color cborder,color ctext,int Fsize,ENUM_FONT font)
  {
//--- coordinates
   int x1=(PANEL_WIDTH-8)/2-width/2,                       y1=Vertical_Pointer-y;
   int x2=(PANEL_WIDTH-8)/2+width/2,                       y2=y1+height;
   
   static int x=0;
   string number=IntegerToString(x,2,'0');      x++;
   
   if(!Button1.Create(0,"Button_"+number,0,x1,y1,x2,y2))                      return(false);
   if(!Button1.Text(text))                                                    return(false);
   if(!Add(Button1))                                                          return(false);
 //button.ReadOnly(true);
 //Button1.BringToTop();
   Button1.ColorBackground(cback); Button1.ColorBorder(cborder); Button1.Color(ctext); Button1.Font(GetFontName(font)); Button1.FontSize(Fsize);
 //Button1.TextAlign(ALIGN_CENTER);
   ArrayResize(Obj_names,ArraySize(Obj_names)+1); Obj_names[ArraySize(Obj_names)-1]="Button_"+number;
//--- succeed
   return(true);
  }
//+------------------------------------------------------------------+
bool CPanelDialog::CreateListView(CListView &listV,const string name,int x,int y,int width,int height)
  {
   int x1=x,            y1=y;
   int x2=x+width,      y2=y+height;

   if(!listV.Create(0,name,0,x1,y1,x2,y2))                        return(false);
   if(!Add(listV))                                                return(false);
   //listV.ColorBackground(clr_RowBack);
   //listV.ColorBorder(clr_RowBorders);
   // IMPORTANT: set text style (otherwise it can look “empty” on dark backgrounds)
   listV.FontSizeFHD(Font_Size);
   listV.ItemHeightFHD(18);
   // show exactly 3 rows (scroll for more)
   //if(!listV.TotalView(3))                                        return(false);
   //listV.Move(x1,y1); // re-apply bounds after TotalView/rows init (fixes “1-row canvas” cases)
   //listV.BringToTop();
   //listV.Show();
   //listV.SetColorMode(true);
   // Do NOT pre-fill blank rows here.
   // We'll append 5-row “blocks” from NewsDisplayFunction (no DeleteAllItems / no Redraw required).
   // pre-fill 5 placeholder rows once (we will re-create the control when content changes)
 //for(int i=0;i<5;i++) if(!listV.AddItem(" ",i))                 return(false);
 //for(int i=0;i<5;i++) if(!listV.AddItem(" "))                   return(false);
 //listV.Select(0);
   return(true);
  }
//+------------------------------------------------------------------+
/*bool CPanelDialog::CreateBmpButton1(void)
  {
//--- coordinates
   int x1=(PANEL_WIDTH-8)/2,                                      y1=Vertical_Pointer-20;
   int x2=(PANEL_WIDTH-8)/2+500,                                   y2=y1+500;
//--- create
   if(!m_bmpbutton1.Create(0,"BmpButton1",0,10,10,100,100))         return(false);
//--- sets the name of bmp files of the control CBmpButton
   //m_bmpbutton1.BmpNames("\\Images\\Biiionic Font Logo White@4x-8_24-bit.bmp","\\Images\\dollar.bmp");
   m_bmpbutton1.BmpNames("\\Images\\euro.bmp","\\Images\\dollar.bmp");
   if(!Add(m_bmpbutton1)) return(false);
   m_bmpbutton1.BringToTop();
//--- succeed
   return(true);
  }*/
//+------------------------------------------------------------------+
bool SetEdit(CEdit &edit1,string text,color ctext=clrNONE,int Fsize=0,color cback=clrNONE,color cborder=clrNONE,ENUM_FONT font=0)
  {
   if(FastSpeed_Flag)   return false;
   
   edit1.Text(text);
   
   if(ctext!=clrNONE)   edit1.Color(ctext);
   if(Fsize!=0)         edit1.FontSize(Fsize);
   if(cback!=clrNONE)   edit1.ColorBackground(cback);
   if(cborder!=clrNONE) edit1.ColorBorder(cborder);
   if(font!=0)          edit1.Font(GetFontName(font));
//--- succeed
   return(true);
  }
//+------------------------------------------------------------------+
void NewsDisplayFunction(bool active,color clrtext)
  {
   if(Mode_News==News_Disabled) return;

   datetime now = TimeCurrent();
   int total    = ArraySize(News.TodaysNewsList);
   int rows     = total; if(rows<3) rows=3;

   static string cache[];
   bool changed = false;

   if(ArraySize(cache)!=rows) changed=true;

   for(int i=0; !changed && i<rows; i++)
     {
      string s=" ";
      if(i<total)
         s = TimeToString(News.TodaysNewsList[i].time,TIME_MINUTES)+" "+News.TodaysNewsList[i].currency+" "+(string)News.TodaysNewsList[i].impact_score+" "+News.TodaysNewsList[i].name;
      if(cache[i]!=s) changed=true;
     }

   if(changed)
     {
      PanelDialog.m_list_News.ItemsClear();
      ArrayResize(cache, rows);

      for(int i=0;i<rows;i++)
        {
         string s=" ";
         if(i<total)
            s = TimeToString(News.TodaysNewsList[i].time,TIME_MINUTES)+" "+News.TodaysNewsList[i].currency+" "+(string)News.TodaysNewsList[i].impact_score+" "+News.TodaysNewsList[i].name;

         PanelDialog.m_list_News.AddItem(s,i);
         cache[i]=s;
        }
     }

   int sel=0;
   if(total>0)
     {
      sel=total-1;
      for(int i=0;i<total;i++)
        {
         if(News.TodaysNewsList[i].time>=now) {sel=i; break;}
        }
     }
   PanelDialog.m_list_News.Select(sel);
   ChartRedraw();
  }
//+------------------------------------------------------------------+
void BiasDisplayFunction(bool active,color clrtext,int idx)
  {
   if(Mode_Bias==Bias_Disabled) return;
   //Print(idx);
   if(idx>=0&&idx<ArraySize(Bias.BiasList))
   SetEdit(PanelDialog.m_edit_Bias1,"  Latest Bias: "+(string)Bias.BiasList[idx].sentiment_score+" ("+(string)((int)(TimeCurrent()-Bias.BiasList[idx].time)/60)+" mins ago)",clrtext);
   //Print(Bias.BiasList[size-1].time);
   if((idx-1)>=0&&(idx-1)<ArraySize(Bias.BiasList)-1)
   SetEdit(PanelDialog.m_edit_Bias2,"Previous Bias: "+(string)Bias.BiasList[idx-1].sentiment_score+" ("+(string)((int)(TimeCurrent()-Bias.BiasList[idx-1].time)/60)+" mins ago)",clr_Text);
  }
//+------------------------------------------------------------------+
void CPanelDialog::OnClickCloseBuy(void)
  {
   if(Seq_Buy.Active)
   {
    if(Seq_Buy.Traded)
    {
     if(FindNumberOfPositions(OP_BUY,MAGIC1)>0) CloseAllPositions(OP_BUY,MAGIC1); 
     Seq_Buy.End_Sequence("Manually Closed");
    }
    else Seq_Buy.End_Sequence("Manually Closed");
   }
   else if(Seq_Buy_Virtual.Active) Seq_Buy_Virtual.End_Sequence("Manually Closed");
  }
void CPanelDialog::OnClickCloseSell(void)
  {
   if(Seq_Sell.Active)
   {
    if(Seq_Sell.Traded)
    {
     if(FindNumberOfPositions(OP_SELL,MAGIC1)>0) CloseAllPositions(OP_SELL,MAGIC1); 
     Seq_Sell.End_Sequence("Manually Closed");
    }
    else Seq_Sell.End_Sequence("Manually Closed");
   }
   else if(Seq_Sell_Virtual.Active) Seq_Sell_Virtual.End_Sequence("Manually Closed");
  }
void CPanelDialog::OnClickLotsViewer(void) 
  {
   SEQUENCE tempSEQ;  // temp seq created 
   string LotsInfo = tempSEQ.BuildLotsInfoString();  // method infers StartLots internally
   string OpenInfo = "";

   if(Seq_Buy.Active)       OpenInfo += Seq_Buy.BuildOpenedLotsInfoString();
   if(Seq_Sell.Active)
   {
    if(OpenInfo!="") OpenInfo += "\n";
    OpenInfo += Seq_Sell.BuildOpenedLotsInfoString();
   }
   if(OpenInfo=="")
   {
    if(Seq_Buy_Virtual.Active)  OpenInfo += Seq_Buy_Virtual.BuildOpenedLotsInfoString();
    if(Seq_Sell_Virtual.Active)
    {
     if(OpenInfo!="") OpenInfo += "\n";
     OpenInfo += Seq_Sell_Virtual.BuildOpenedLotsInfoString();
    }
   }

   if(OpenInfo!="") LotsInfo += "\n\nCURRENT OPENED SEQUENCE LAYOUT\n\n" + OpenInfo;
   MessageBox(LotsInfo,"Sequence Levels Viewer",MB_OK);
  }
void CPanelDialog::OnClickBackToDB(void) 
  {
     //if(sparam==Key+"_BackToDB_"+(string)MAGIC1 && 
     if(GlobalVariableCheck("Dashboard_ChartID"))
     {
       Print("Return to DB button pressed");
     //double DB_CID=GlobalVariableGet("Dashboard_ChartID");Print(DB_CID);Print((long)DB_CID);Print((ulong)DB_CID);Print(ChartID());
       if(!ChartSetInteger(ChartFirst(),CHART_BRING_TO_TOP,0,true))
       {
        Print(__FUNCTION__+", Error Code = ",GetLastError()); return;
       }
       Sleep(100); ChartRedraw(); Sleep(100); ChartRedraw(ChartFirst()); Sleep(100);
     //ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
     }
  }
//+------------------------------------------------------------------+
string ExtractFunctionKeysFromInputString(const string inputString, string &names[], string &values[])
  {
   ArrayResize(names,0); ArrayResize(values,0);
   // Base is everything before '@'
   int at = StringFind(inputString,"@");
   string base = (at<0 ? inputString : StringSubstr(inputString,0,at));
   StringTrimLeft(base); StringTrimRight(base);
   if(at<0) return base; // no "@{...}" section
   // Find @{...}
   int open = StringFind(inputString,"{",at);
   if(open<0) return base; // require braces

   int close = StringFind(inputString,"}",open);
   if(close<0) return base; // malformed, no closing brace
   // Inner = between braces
   string inner = StringSubstr(inputString, open+1, close-open-1);
   StringTrimLeft(inner); StringTrimRight(inner);
   // If caller wrote a trailing ';' after '}', ignore it safely
   // (e.g., EA_Desc=EA_Strategy@{...};
   //  we already cut at '}', but just in case there are residual chars)
   // No-op here because we sliced only between braces.
   // Tokenize by comma ONLY, respecting quotes so we don't split inside quoted values
   string cur=""; bool in_s=false, in_d=false;
   for(int i=0, n=StringLen(inner); i<n; i++)
     {
      string chs = StringSubstr(inner,i,1);
      int    ch  = StringGetCharacter(inner,i);

      if(ch=='\'' && !in_d) { in_s = !in_s; cur += chs; continue; }
      if(ch=='"'  && !in_s) { in_d = !in_d; cur += chs; continue; }

      if(!in_s && !in_d && ch==',')
        {
         string t = cur; StringTrimLeft(t); StringTrimRight(t);
         if(StringLen(t)>0)
           {
            int eq = StringFind(t,"=");
            if(eq>=0)
              {
               string key = StringSubstr(t,0,eq);
               string val = StringSubstr(t,eq+1);
               StringTrimLeft(key); StringTrimRight(key);
               StringTrimLeft(val); StringTrimRight(val);
               // strip optional quotes around value
               int L = StringLen(val);
               if(L>=2)
                 {
                  int c0=StringGetCharacter(val,0), c1=StringGetCharacter(val,L-1);
                  if((c0=='\'' && c1=='\'') || (c0=='"' && c1=='"')) val = StringSubstr(val,1,L-2);
                 }
               int sz = ArraySize(names);
               ArrayResize(names,sz+1); ArrayResize(values,sz+1);
               names[sz]  = key;      // exact case preserved
               values[sz] = val;
              }
           }
         cur = "";
         continue;
        }
      cur += chs;
     }
   // flush last token (after final comma or when there were no commas)
   string t = cur; StringTrimLeft(t); StringTrimRight(t);
   if(StringLen(t)>0)
     {
      int eq = StringFind(t,"=");
      if(eq>=0)
        {
         string key = StringSubstr(t,0,eq);
         string val = StringSubstr(t,eq+1);
         StringTrimLeft(key); StringTrimRight(key);
         StringTrimLeft(val); StringTrimRight(val);

         int L = StringLen(val);
         if(L>=2)
           {
            int c0=StringGetCharacter(val,0), c1=StringGetCharacter(val,L-1);
            if((c0=='\'' && c1=='\'') || (c0=='"' && c1=='"')) val = StringSubstr(val,1,L-2);
           }
         int sz = ArraySize(names);
         ArrayResize(names,sz+1); ArrayResize(values,sz+1);
         names[sz]  = key;
         values[sz] = val;
        }
     }
   return base;
  }
//+------------------------------------------------------------------+
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
//----------------------------------------------------------------------------------------------------------------------------------------------------
