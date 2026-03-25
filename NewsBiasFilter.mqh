#include "GOAT_Inputs_Definitions.mqh"
struct SNewsSyncResult
  {
   bool     success;
   int      total_events;
   datetime latest_event_time;
   string   error_text;
  };

struct SBiasAssetSyncResult
  {
   string   asset;
   bool     success;
   int      total_points;
   datetime earliest_time;
   datetime latest_time;
   string   error_text;
  };

struct SBulkBiasSyncResult
  {
   bool                 success;
   int                  assets_total;
   int                  assets_synced;
   int                  assets_failed;
   string               error_text;
   SBiasAssetSyncResult asset_results[];
  };
int GetGOATSupportedBiasAssets(string &assets[]);
//+------------------------------------------------------------------+
class GOATNewsFilter
  {
   private:
   struct NewsStructObject
     {
    //ulong          EventID;
      datetime       time;
      string         name;
    //int            Importance;
      string         currency;
      int            impact_score;
      double         actual,forecast,previous;
      bool           outcome;
      string         newsDescription;
     };
   bool              NewsChecked;
   string            SymbolCurrenciesString;
   datetime          LastNewsTimeCheck;
   int               BrokerGMTOffsetSec;
   int               BrokerDSTEnabled;
   // Array buffers
   //string            m_arrInclude[];
   //string            m_arrExclude[];

   // --- Private Helpers ---
   bool              WriteNewsFile(const string outputFileName,string &error_text);
   //void              ParseKeywords();
   //void              StringSplitterHelper(string stringname, string &MyArray[], string seperator=",");
   public:
   string            Key_;
   NewsStructObject  NewsList[];
   NewsStructObject  TodaysNewsList[];
   
   GOATNewsFilter()
   {
    Key_                    = "";
    NewsChecked             = false;
    SymbolCurrenciesString  = "";
    LastNewsTimeCheck       = 0;
    BrokerGMTOffsetSec     = 0;
    BrokerDSTEnabled       = 0;
    //ArrayResize(m_arrInclude, 0);
    //ArrayResize(m_arrExclude, 0);
    ArrayResize(NewsList, 0);
    ArrayResize(TodaysNewsList, 0);
   }
   ~GOATNewsFilter()
   {
    //ArrayFree(m_arrInclude);
    //ArrayFree(m_arrExclude);
    ArrayFree(NewsList);
    ArrayFree(TodaysNewsList);
   }
   void              Init(string Key__);
   void              BacktestNewsFileDownloader(datetime startdate);
   bool              SyncFullHistory(SNewsSyncResult &result);
   bool              LoadBacktestFileAndFillNews();
   bool              DownloadAndFillNews(datetime startdate,int news_threshold,bool DownloadMode,bool showSummary=true);
   bool              FillTodaysNewsArray();
   bool              IsNewsTime(string sym,int threshold,int &indices[]);
  };
GOATNewsFilter News;
//+------------------------------------------------------------------+
class GOATBiasHistory
  {
   private:
   struct BiasStructObject
     {
      datetime       time;
      string         asset;
      int            sentiment_score;
     };
   datetime          LastBiasTimeCheck;
   int               BrokerGMTOffsetSec;
   int               BrokerDSTEnabled;

   bool              WriteBiasFile(const string outputFileName,string &error_text);
   void              UpdateStatesToTime(datetime now);
   //bool            ParseIso8601ToDatetime(string ts, datetime &out_time);
   //int             ParseSentimentToInt(string sentiment);
   //void            SortBiasListByTime(int left, int right);

   public:
   string            Key_;
   BiasStructObject  BiasList[];
   
   GOATBiasHistory()
   {
    Key_="";
    ArrayResize(BiasList, 0);
    LastBiasTimeCheck = 0;
    BrokerGMTOffsetSec = 0;
    BrokerDSTEnabled   = 0;
   }
   ~GOATBiasHistory()
   {
    ArrayFree(BiasList);
   }

   void                   Init(string Key__)
                          {
                           Key_ = Key__;
                           if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))
                             {
                              if(LoadBacktestFileAndFillBias()) Print("Bias Initialized");
                              else                              Print("Bias Initialization Failed.");
                             }
                             //LoadBacktestFileAndFillBias();
                          }
   void                   BacktestBiasFileDownloader(datetime startdate);
   bool                   SyncBiasHistory(datetime startdate,const string asset,SBiasAssetSyncResult &result);
   bool                   SyncAllBiasHistory(SBulkBiasSyncResult &result);
   bool                   LoadBacktestFileAndFillBias();
   bool                   DownloadAndFillBias(datetime startdate, string asset, bool DownloadMode,bool showSummary=true);
   int                    GetCurentBiasScore(string asset,int &idx);
  };
GOATBiasHistory Bias;
//+------------------------------------------------------------------+
void GOATNewsFilter::Init(string Key__)
  {
   //int GMToffset = GetGMTOffset();
   //bool DST = IsDST();
   Key_ = Key__;
   string base    = SymbolInfoString(Symbol(), SYMBOL_CURRENCY_BASE);
   string profit  = SymbolInfoString(Symbol(), SYMBOL_CURRENCY_PROFIT);
   string margin  = SymbolInfoString(Symbol(), SYMBOL_CURRENCY_MARGIN);

   if(StringFind(SymbolCurrenciesString, base) == -1)   SymbolCurrenciesString = base;
   if(StringFind(SymbolCurrenciesString, profit) == -1) SymbolCurrenciesString += "," + profit;
   if(StringFind(SymbolCurrenciesString, margin) == -1) SymbolCurrenciesString += "," + margin;
   Print("This Symbols Currencies: "+SymbolCurrenciesString);
   
   if(MQLInfoInteger(MQL_TESTER)||MQLInfoInteger(MQL_OPTIMIZATION)||MQLInfoInteger(MQL_FORWARD))
   if(LoadBacktestFileAndFillNews()) Print("News Initialized"); // All relavant news is loaded in NewsList Array at start
   else                              Print("News Initialization Failed");
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::IsNewsTime(string sym,int threshold,int &indices[])
  {
   // here go through the Active news array and check if any event is within the window of news before minutes and after minutes
   // the passed symbols currencies are to be checked with the series of news events as well.
   // threshold filter is to be applied on news events.
   if(Mode_News == News_Disabled) return false; //return false;
   ArrayResize(indices, 0);
   
   if(!(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))) // if live trading
     {
      if(!DownloadAndFillNews(TimeCurrent(), threshold, false, false)) return false; // live refresh should not block trading with modal API popups
     }

   if(!FillTodaysNewsArray()) return false;
   
   string symCurrencies = "";
   if(sym==Symbol()) symCurrencies = SymbolCurrenciesString;
   else
   {
    string base   = SymbolInfoString(sym, SYMBOL_CURRENCY_BASE);
    string profit = SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT);
    string margin = SymbolInfoString(sym, SYMBOL_CURRENCY_MARGIN);

    if(base   != "") symCurrencies = base;
    if(profit != "" && StringFind(symCurrencies, profit) == -1) symCurrencies += (symCurrencies == "" ? profit : "," + profit);
    if(margin != "" && StringFind(symCurrencies, margin) == -1) symCurrencies += (symCurrencies == "" ? margin : "," + margin);
   }
   if(symCurrencies == "") return false;

   datetime now = TimeCurrent();
   int before_s = News_beforeMinutes * 60;
   int after_s  = News_afterMinutes * 60;

   int hits = 0;
   for(int i = 0; i < ArraySize(TodaysNewsList); i++)
     {
      if(TodaysNewsList[i].impact_score < threshold) continue;

      if(StringFind(symCurrencies, TodaysNewsList[i].currency) == -1) continue;

      datetime t = TodaysNewsList[i].time;

      if(now < (t - before_s)) break;
      if(now > (t + after_s)) continue;

      ArrayResize(indices, hits + 1);
      indices[hits] = i;
      hits++;
     }
   return (hits > 0);
  }
//+------------------------------------------------------------------+
int GOATBiasHistory::GetCurentBiasScore(string asset,int &idxx)
  {
   asset = ConvertToGOATsymbol(asset);
   if(Mode_Bias == Bias_Disabled) return -999;

   datetime now = TimeCurrent();
   
   bool is_tester = (MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD));
   
   if(!is_tester) // if live trading: standing bias = latest point, but must not be too old
     {
      datetime start_srv = TimeCurrent() - 24*60*60; // start with last 24h window in SERVER time
      if(!DownloadAndFillBias(start_srv, asset, false, false)) return -999; // live refresh should not block trading with modal API popups
     }
   if(ArraySize(BiasList) <= 0) {Alert("Empty Bias List!"); return -999;}
   //--- calculate average duration (seconds) between consecutive bias points (used for staleness)
   long sum = 0;
   int  cnt = 0;
   for(int i = 1; i < ArraySize(BiasList); i++)
     {
      long d = (long)(BiasList[i].time - BiasList[i - 1].time);
      if(d > 0) {sum += d;cnt++;}
     }
   long avg = 0;
   if(cnt > 0) avg = sum / cnt;
   else        avg = (long)Bias_RegenerateMinutes * 60;
   //--- find latest timestamp point (should be last element in live mode but not particularly in backtest mode)
   static int idx = 0;
   
   if(!is_tester) idx = 0; // we can afford to loop from the start of biaslist because its small in live mode
   
   //--- critical guard: cached idx can become invalid if BiasList is refreshed/reloaded
   if(idx < 0) idx = 0;
   if(idx >= ArraySize(BiasList)) idx = 0;
   
   //--- pick the most recent bias point that is NOT in the future (time <= now)
   int start = MathMax(0, idx - 5);
   if(BiasList[start].time > now) {start = 0; idx = 0;} // guard against stale/shifted cache region
   for(int i = start; i < ArraySize(BiasList); i++)
     {
      if(BiasList[i].time <= now) {idx = i;} // <= is important for exact timestamp matches
      else                        break;
     }
   //--- if no non-future bias exists yet (all points are future), do NOT use future directive
   if(BiasList[idx].time > now) return -999;

   datetime latest_time = BiasList[idx].time;
   int      latest_score = BiasList[idx].sentiment_score;

   idxx=idx;
   //--- staleness check: if selected bias is too old relative to typical cadence, treat as neutral
   if(avg > 0 && (now - latest_time) > (datetime)(2 * avg)) return -999;

   return latest_score;
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::FillTodaysNewsArray()
  {
   //ArrayResize(NewsList,0);
   //return false;
   static int NextDayIndex = 0;

   if(ArraySize(NewsList) <= 0)
     {
      //ArrayResize(TodaysNewsList, 0); // lets keep the current active list
      Alert("Empty News List!");
      return false;
     }
   
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt); dt.hour = 0; dt.min  = 0; dt.sec  = 0;
   datetime today_start = StructToTime(dt);
   datetime nextday_start = today_start + 24*60*60;
   
   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))
     {
      if(NextDayIndex>=ArraySize(NewsList)) return false;
      if(NewsList[NextDayIndex].time>nextday_start && ArraySize(TodaysNewsList) > 0) return true; // NextDayIndex is initialized with 0 and NewsList size does not change during the backtest

      ArrayResize(TodaysNewsList, 0);
      int out = 0;

      for(int i = NextDayIndex; i < ArraySize(NewsList); i++)
        {
         if(NewsList[i].time > nextday_start) {NextDayIndex=i; break;}
         
         if(NewsList[i].time >= today_start)
         {
          ArrayResize(TodaysNewsList, out + 1);
          TodaysNewsList[out] = NewsList[i];
          out++;
         }
        }
      return true;
     }

   if(!NewsChecked && ArraySize(TodaysNewsList) > 0 && TodaysNewsList[0].time > today_start) return true; // no fresh news in NewsList which was previously used to build TodaysNewsList

   ArrayResize(TodaysNewsList, 0);
   int out = 0;

   for(int i = 0; i < ArraySize(NewsList); i++) // NewsList size is limited here in live mode because the fresh news download started with current day only, we can check from 0 index
     {
      if(NewsList[i].time >= nextday_start) break;
      
      if(NewsList[i].time >= today_start)
      {
       ArrayResize(TodaysNewsList, out + 1);
       TodaysNewsList[out] = NewsList[i];
       out++;
      }
     }
   Print((string)(out)+" News events loaded for today "+TimeToString(today_start,TIME_DATE)+" for "+Symbol());
   NewsChecked = false; // only fill TodaysNewsList again after checked again
   return true;
  }
//+------------------------------------------------------------------+
void GOATNewsFilter::BacktestNewsFileDownloader(datetime startdate)
  {
   Print("Downloading News Data. Please Wait");
   if(!DownloadAndFillNews(startdate,News_threshold,true))
     {
      Alert("News download failed");
      return;
     }
   Print("Downloading News Data Finished");
   Print("Writing to File...");

   string error_text = "";
   if(!WriteNewsFile(NEWS_FILE,error_text))
     {
      Alert(error_text);
      return;
     }
   Print("News Writing Complete");
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::WriteNewsFile(const string outputFileName,string &error_text)
  {
   error_text = "";
   int outputFileHandle = FileOpen(outputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ",");

   if(outputFileHandle == INVALID_HANDLE)
     {
      error_text = "Error opening news file for writing";
      Print(error_text);
      return false;
     }

   FileWrite(outputFileHandle, "Time", "Currency", "ImpactScore", "Name", "Actual", "Forecast", "Previous", "Outcome", "Description");

   for(int i = 0; i < ArraySize(NewsList); i++)
     {
      FileWrite(outputFileHandle,
                TimeToString(NewsList[i].time, TIME_DATE|TIME_MINUTES|TIME_SECONDS),
                NewsList[i].currency,
                NewsList[i].impact_score,
                NewsList[i].name,
                DoubleToString(NewsList[i].actual, 2),
                DoubleToString(NewsList[i].forecast, 2),
                DoubleToString(NewsList[i].previous, 2),
                (int)NewsList[i].outcome,
                NewsList[i].newsDescription);
     }
   FileClose(outputFileHandle);

   int g = 0, d = 0;
   if(!LoadOrSaveBrokerTimeFiles(g, d, false,Key_))
     {
      error_text = "Error writing broker time metadata for news history";
      Print(error_text);
      return false;
     }
   return true;
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::SyncFullHistory(SNewsSyncResult &result)
  {
   result.success = false;
   result.total_events = 0;
   result.latest_event_time = 0;
   result.error_text = "";

   if(!DownloadAndFillNews(GOATFullHistorySyncStart(),News_threshold,true,false))
     {
      result.error_text = "News download failed";
      return false;
     }

   result.total_events = ArraySize(NewsList);
   if(result.total_events > 0)
      result.latest_event_time = NewsList[result.total_events - 1].time;

   if(!WriteNewsFile(NEWS_FILE,result.error_text))
      return false;

   result.success = (result.total_events > 0);
   if(!result.success && result.error_text == "")
      result.error_text = "No news events returned";
   return result.success;
  }
//+------------------------------------------------------------------+
void GOATBiasHistory::BacktestBiasFileDownloader(datetime startdate)
  {
   Print("Downloading Bias Data. Please Wait");
   if(!DownloadAndFillBias(startdate, ConvertToGOATsymbol(Symbol()), true))
     {
      Print("Bias download failed");
      return;
     }
   Print("Downloading Bias Data Finished");
   Print("Writing to File...");

   string error_text = "";
   if(!WriteBiasFile(BIAS_FILE+ConvertToGOATsymbol(Symbol())+".csv",error_text))
     {
      Print(error_text);
      return;
     }
   Print("Bias Writing Complete");
  }
//+------------------------------------------------------------------+
bool GOATBiasHistory::WriteBiasFile(const string outputFileName,string &error_text)
  {
   error_text = "";
   int outputFileHandle = FileOpen(outputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ",");

   if(outputFileHandle == INVALID_HANDLE)
     {
      error_text = "Error opening bias file for writing. Error=" + (string)GetLastError();
      Print(error_text);
      return false;
     }
   FileWrite(outputFileHandle, "Time", "Asset", "SentimentScore");

   for(int i = 0; i < ArraySize(BiasList); i++)
     {
      FileWrite(outputFileHandle,
                TimeToString(BiasList[i].time, TIME_DATE|TIME_MINUTES|TIME_SECONDS),
                BiasList[i].asset,
                BiasList[i].sentiment_score);
     }
   FileClose(outputFileHandle);

   int g = 0, d = 0;
   if(!LoadOrSaveBrokerTimeFiles(g, d, false,Key_))
     {
      error_text = "Error writing broker time metadata for bias history";
      Print(error_text);
      return false;
     }
   return true;
  }
//+------------------------------------------------------------------+
bool GOATBiasHistory::SyncBiasHistory(datetime startdate,const string asset,SBiasAssetSyncResult &result)
  {
   result.asset = asset;
   result.success = false;
   result.total_points = 0;
   result.earliest_time = 0;
   result.latest_time = 0;
   result.error_text = "";

   if(!DownloadAndFillBias(startdate,asset,true,false))
     {
      result.error_text = "Bias download failed";
      return false;
     }

   result.total_points = ArraySize(BiasList);
   if(result.total_points > 0)
     {
      result.earliest_time = BiasList[0].time;
      result.latest_time = BiasList[result.total_points-1].time;
     }

   if(!WriteBiasFile(BIAS_FILE+asset+".csv",result.error_text))
      return false;

   result.success = (result.total_points > 0);
   if(!result.success && result.error_text == "")
      result.error_text = "No bias points returned";
   return result.success;
  }
//+------------------------------------------------------------------+
bool GOATBiasHistory::SyncAllBiasHistory(SBulkBiasSyncResult &result)
  {
   result.success = false;
   result.assets_total = 0;
   result.assets_synced = 0;
   result.assets_failed = 0;
   result.error_text = "";
   ArrayResize(result.asset_results, 0);

   string assets[];
   int total = GetGOATSupportedBiasAssets(assets);
   result.assets_total = total;
   ArrayResize(result.asset_results, total);

   datetime startdate = GOATFullHistorySyncStart();
   for(int i = 0; i < total; i++)
     {
      SBiasAssetSyncResult asset_result;
      if(SyncBiasHistory(startdate,assets[i],asset_result)) result.assets_synced++;
      else                                                  result.assets_failed++;
      result.asset_results[i] = asset_result;
     }

   result.success = (result.assets_synced > 0);
   if(result.assets_failed > 0)
      result.error_text = (string)result.assets_failed + " assets failed during sync";
   return result.success;
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::DownloadAndFillNews(datetime startdate,int news_threshold,bool DownloadMode,bool showSummary)
  {
   //--- build ISO8601 start_time from Download_StartDate (UTC)
   MqlDateTime dt;
   if(DownloadMode)  TimeToStruct(startdate, dt); // input startdate is treated as UTC for download mode
   else
     {
      if(TimeCurrent() > LastNewsTimeCheck + News_RegenerateMinutes*60)
        {
         datetime now_srv = TimeCurrent(); // server time
         TimeToStruct(now_srv, dt); dt.hour = 0; dt.min = 0; dt.sec = 0;

         datetime srv_midnight = StructToTime(dt);
         int off = (int)(TimeTradeServer() - TimeGMT()); // current server->GMT offset (includes DST if any)
         datetime utc_midnight = srv_midnight - off;
         TimeToStruct(utc_midnight, dt); // convert request start_time to UTC ("Z")
         }
      else if(ArraySize(NewsList) > 0) return true; // not the time to check and last checked non empty array exists 
     }
   string start_time = StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec); StringReplace(start_time, ":", "%3A");

   string url = URL_API//"https://serve-api-1062771709899.us-central1.run.app/"   //"https://us-central1-gen-lang-client-0192909082.cloudfunctions.net/serveApi/"
                                                                                                                     +"/api/ea/calendar"//+"?data=calendar"
                                                                                                                     +"?start_time="+start_time
                                                                                                                     +"&limit=99999" // indefinite limit because date dependant only
                                                                                                                     +"&order=asc"
                                                                                                                     +"&id="+(string)AccountInfoInteger(ACCOUNT_LOGIN);
   char request_body[];
   ArrayResize(request_body, 0);
   char result[];
   string result_headers = "";
   
   string x = "e9691e12e7eef5ceb1daa0559374c83d90248ba3165051f4d82670a7ad0928be";
   ResetLastError();
   int res = WebRequest("GET", url, requestHeaders+x+"161bd26578b6b1ab496e3b3fda393a39aa82cf4734bce5bc168d406248db9745\r\n", timeout, request_body, result, result_headers);
   Print("Response Code: ", res);
   if(res == -1)
     {
      int err = GetLastError();
      if(DownloadMode && showSummary) Alert("News downloader WebRequest failed. Error=%d. Add the URL in: Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL.",err);
      PrintFormat("News downloader WebRequest failed. Error=%d. Add the URL in: Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL.",err);
      return false;
     }
   else if(res!=200)
     {
      string response_text = CharArrayToString(result, 0, -1, CP_UTF8);
      if(showSummary && response_text != "") MessageBox(response_text,"Response code: "+(string)res,MB_OK);
      else                                   Print("News downloader HTTP response "+(string)res+(response_text != "" ? ": "+response_text : " (empty body)"));
     }
   else LastNewsTimeCheck=TimeCurrent();
   
   Print("News API called");
   string json = CharArrayToString(result, 0, -1, CP_UTF8);
   //--- fill NewsList from JSON
   ArrayResize(NewsList, 0);

   int pos = 0, dropped=0;
   while(true)
     {
      int p_ts = StringFind(json, "\"timestamp_utc\":\"", pos);
      if(p_ts < 0) break;
      p_ts += StringLen("\"timestamp_utc\":\"");
      int e_ts = StringFind(json, "\"", p_ts);
      if(e_ts < 0) break;
      string ts = StringSubstr(json, p_ts, e_ts - p_ts);

      int p_name = StringFind(json, "\"eventName\":\"", e_ts);
      if(p_name < 0) break;
      p_name += StringLen("\"eventName\":\"");
      int e_name = StringFind(json, "\"", p_name);
      if(e_name < 0) break;
      string name = StringSubstr(json, p_name, e_name - p_name);

      int p_cur = StringFind(json, "\"currency\":\"", e_name);
      if(p_cur < 0) break;
      p_cur += StringLen("\"currency\":\"");
      int e_cur = StringFind(json, "\"", p_cur);
      if(e_cur < 0) break;

      string cur = StringSubstr(json, p_cur, e_cur - p_cur);

      int p_imp = StringFind(json, "\"impact_score\":", e_cur);
      if(p_imp < 0) break;
      p_imp += StringLen("\"impact_score\":");
      int e_imp = StringFind(json, ",", p_imp);
      if(e_imp < 0) e_imp = StringFind(json, "}", p_imp);
      if(e_imp < 0) break;

      int impact_score = (int)StringToInteger(StringSubstr(json, p_imp, e_imp - p_imp));

      int p_act = StringFind(json, "\"actual\":\"", e_imp);
      if(p_act < 0) break;
      p_act += StringLen("\"actual\":\"");
      int e_act = StringFind(json, "\"", p_act);
      if(e_act < 0) break;

      string actual_s = StringSubstr(json, p_act, e_act - p_act);

      int p_fc = StringFind(json, "\"forecast\":\"", e_act);
      if(p_fc < 0) break;
      p_fc += StringLen("\"forecast\":\"");
      int e_fc = StringFind(json, "\"", p_fc);
      if(e_fc < 0) break;
      
      string forecast_s = StringSubstr(json, p_fc, e_fc - p_fc);
      
      int p_prev = StringFind(json, "\"previous\":\"", e_fc);
      if(p_prev < 0) break;
      p_prev += StringLen("\"previous\":\"");
      int e_prev = StringFind(json, "\"", p_prev);
      if(e_prev < 0) break;

      string previous_s = StringSubstr(json, p_prev, e_prev - p_prev);

      int p_out = StringFind(json, "\"outcome\":\"", e_prev);
      if(p_out < 0) break;
      p_out += StringLen("\"outcome\":\"");
      int e_out = StringFind(json, "\"", p_out);
      if(e_out < 0) break;

      string outcome_s = StringSubstr(json, p_out, e_out - p_out);

      int p_ai = StringFind(json, "\"aiAnalysis\":\"", e_out);
      if(p_ai < 0) break;
      p_ai += StringLen("\"aiAnalysis\":\"");
      int e_ai = StringFind(json, "\"", p_ai);
      if(e_ai < 0) break;

      string ai_s = StringSubstr(json, p_ai, e_ai - p_ai);
      pos = e_ai;
      
      if(DownloadMode)
      {
       if(StringFind(Download_NewsCurrencies, cur) == -1) {dropped++; /*Print(cur);*/ continue;}  // if download mode then downlaod all currencies specified in the inputs.
     //if(impact_score < news_threshold) continue;                   // only check impact score in live trading call
      }
      else {
       if(StringFind(SymbolCurrenciesString, cur) == -1)  {dropped++; continue;}  // if not download mode then downlaod only current symbols currencies.
       if(impact_score < news_threshold)                  {dropped++; continue;}  // only check impact score in live trading call
      }
      //--- parse ISO8601 "YYYY-MM-DDTHH:MM:SSZ" to datetime
      datetime event_time = 0;
      if(StringLen(ts) >= 19)
        {
         MqlDateTime et;
         et.year = (int)StringToInteger(StringSubstr(ts, 0, 4));
         et.mon  = (int)StringToInteger(StringSubstr(ts, 5, 2));
         et.day  = (int)StringToInteger(StringSubstr(ts, 8, 2));
         et.hour = (int)StringToInteger(StringSubstr(ts, 11, 2));
         et.min  = (int)StringToInteger(StringSubstr(ts, 14, 2));
         et.sec  = (int)StringToInteger(StringSubstr(ts, 17, 2));
         event_time = StructToTime(et);
         //--- API timestamp is UTC; convert to broker/server time in live mode using current GMT offset (includes DST implicitly)
         if(!DownloadMode)
         {
          int off_now = (int)(TimeTradeServer() - TimeGMT());
          event_time += (datetime)off_now;
         }
        }
      if(event_time <= 0) {dropped++; continue;}
      
      double actual_v   = 0.0;
      double forecast_v = 0.0;
      double previous_v = 0.0;

      if(StringLen(actual_s) > 0)   actual_v   = StringToDouble(actual_s);
      if(StringLen(forecast_s) > 0) forecast_v = StringToDouble(forecast_s);
      if(StringLen(previous_s) > 0) previous_v = StringToDouble(previous_s);

      bool outcome_v = false;
      if(outcome_s != "" && outcome_s != "Pending") outcome_v = true;

      StringReplace(name, ",", " ");
      StringReplace(ai_s, ",", " ");

      int n = ArraySize(NewsList);
      ArrayResize(NewsList, n + 1);

      NewsList[n].time            = event_time;
      NewsList[n].name            = name;
      NewsList[n].currency        = cur;
      NewsList[n].impact_score    = impact_score;
      NewsList[n].actual          = actual_v;
      NewsList[n].forecast        = forecast_v;
      NewsList[n].previous        = previous_v;
      NewsList[n].outcome         = outcome_v;
      NewsList[n].newsDescription = ai_s;
     }
   //--- Post-parse sanity checks: remove double-stamped timestamps; alert+break on wrong order
   for(int i = 1; i < ArraySize(NewsList); )
     {
      if(NewsList[i].time == NewsList[i - 1].time && NewsList[i].name == NewsList[i - 1].name)
        {
         Print("GOATNewsFilter: Duplicate news timestamp+name detected at "+ TimeToString(NewsList[i].time, TIME_DATE|TIME_MINUTES)
               + " (" + NewsList[i].name + "). Removing duplicate entry at index " + (string)i + ".");

         for(int j = i; j < ArraySize(NewsList) - 1; j++) NewsList[j] = NewsList[j + 1];

         ArrayResize(NewsList, ArraySize(NewsList) - 1);
         continue; // re-check same i against i-1 after shift
        }
      if(NewsList[i].time < NewsList[i - 1].time)
        {
         string order_msg = "GOATNewsFilter: News download order is incorrect (expected oldest at index 0). "
                            "Out-of-order at indices " + (string)(i - 1) + " -> " + (string)i
                            + " (" + TimeToString(NewsList[i - 1].time, TIME_DATE|TIME_MINUTES)
                            + " then " + TimeToString(NewsList[i].time, TIME_DATE|TIME_MINUTES) + ").";
         if(showSummary) Alert(order_msg);
         else            Print(order_msg);
         break;
        }
      i++;
     }
   NewsChecked = true; // newsList is fresh now and TodaysNewsList should be rebuilt
   ArrayResize(TodaysNewsList, 0);
   if(DownloadMode && showSummary)
   {
    if(ArraySize(NewsList)>0) MessageBox("Captured "+(string)ArraySize(NewsList)+" News events\nDropped "+(string)dropped+" News events","News Download Complete",MB_OK|MB_ICONINFORMATION);
    else                      MessageBox("No New Events found\n\nResponse="+json,"News Download Incomplete",MB_OK|MB_ICONERROR);
   }
   Print("Captured "+(string)ArraySize(NewsList)+" News events");
   Print("Dropped "+(string)dropped+" News events");

   return (ArraySize(NewsList)>0);
  }
//+------------------------------------------------------------------+
bool GOATBiasHistory::DownloadAndFillBias(datetime startdate,string asset,bool DownloadMode,bool showSummary)
  {
   MqlDateTime dt;
   if(DownloadMode)
     {
      TimeToStruct(startdate, dt); // input startdate is treated as UTC for download mode
     }
   else
     {
      if(TimeCurrent() > LastBiasTimeCheck + Bias_RegenerateMinutes * 60)
        {
         // if not returning then must adjust offset in live mode
         int off = (int)(TimeTradeServer() - TimeGMT()); // current server->GMT offset (includes DST if any)
         datetime utc_start = startdate - off;
         TimeToStruct(utc_start, dt); // convert request start_time to UTC ("Z")
        }
      else if(ArraySize(BiasList) > 0) return true;
     }
   string start_time = StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec); StringReplace(start_time, ":", "%3A");

   string url = URL_API//"https://serve-api-1062771709899.us-central1.run.app/"  //"https://us-central1-gen-lang-client-0192909082.cloudfunctions.net/serveApi/"
                                                                                                                     +"/api/ea/bias"//+"?data=bias"
                                                                                                                     +"?asset="+asset
                                                                                                                     +"&start_time="+start_time
                                                                                                                     +"&limit=99999" // indefinite limit because date dependant only
                                                                                                                     +"&order=asc"
                                                                                                                     +"&id="+(string)AccountInfoInteger(ACCOUNT_LOGIN);
   char request_body[];
   ArrayResize(request_body, 0);
   char result[];
   string result_headers = "";
   
   string x = "e9691e12e7eef5ceb1daa0559374c83d90248ba3165051f4d82670a7ad0928be";
   ResetLastError();
   int res = WebRequest("GET", url, requestHeaders+x+"161bd26578b6b1ab496e3b3fda393a39aa82cf4734bce5bc168d406248db9745\r\n", timeout*3, request_body, result, result_headers);

   if(res == -1)
     {
      int err = GetLastError();
      if(DownloadMode && showSummary) Alert("Bias downloader WebRequest failed. Error=%d. Add the URL in: Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL.", err);
      PrintFormat("Bias downloader WebRequest failed. Error=%d. Add the URL in: Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL.", err);
      return false;
     }
   else if(res!=200)
     {
      string response_text = CharArrayToString(result, 0, -1, CP_UTF8);
      if(showSummary && response_text != "") MessageBox(response_text,"Response code: "+(string)res,MB_OK);
      else                                   Print("Bias downloader HTTP response "+(string)res+(response_text != "" ? ": "+response_text : " (empty body)"));
     }
   //else LastBiasTimeCheck = TimeCurrent();
   Print("Bias API called");
   string json = CharArrayToString(result, 0, -1, CP_UTF8); //Print(json);
   
   ArrayResize(BiasList, 0);

   int pos = 0, dropped = 0;
   while(true)
     {
      int p_ts = StringFind(json, "\"timestamp\":\"", pos);
      if(p_ts < 0) break;

      p_ts += StringLen("\"timestamp\":\"");
      int e_ts = StringFind(json, "\"", p_ts);
      if(e_ts < 0) break;

      string ts = StringSubstr(json, p_ts, e_ts - p_ts);

      int p_sent = StringFind(json, "\"sentiment\":\"", e_ts);
      if(p_sent < 0) break;

      p_sent += StringLen("\"sentiment\":\"");
      int e_sent = StringFind(json, "\"", p_sent);
      if(e_sent < 0) break;

      string sentiment_s = StringSubstr(json, p_sent, e_sent - p_sent);

      pos = e_sent;

      datetime event_time = 0;
      if(StringLen(ts) >= 19)
        {
         MqlDateTime et;
         et.year = (int)StringToInteger(StringSubstr(ts, 0, 4));
         et.mon  = (int)StringToInteger(StringSubstr(ts, 5, 2));
         et.day  = (int)StringToInteger(StringSubstr(ts, 8, 2));
         et.hour = (int)StringToInteger(StringSubstr(ts, 11, 2));
         et.min  = (int)StringToInteger(StringSubstr(ts, 14, 2));
         et.sec  = (int)StringToInteger(StringSubstr(ts, 17, 2));
         event_time = StructToTime(et);
         //--- API timestamp is UTC; convert to broker/server time in live mode using current GMT offset (includes DST implicitly)
         if(!DownloadMode)
         {
          int off_now = (int)(TimeTradeServer() - TimeGMT());
          event_time += (datetime)off_now;
         }
        }
      if(event_time <= 0) {dropped++; continue;}

      string num = sentiment_s;
      int sp = StringFind(num, " ");
      if(sp > 0) num = StringSubstr(num, 0, sp);

      if(num == "") {dropped++; continue;}

      int score = (int)StringToInteger(num);
      if(score >  100) score =  100;
      if(score < -100) score = -100;
      //if(event_time < min_time) {dropped++; continue;}
      int n = ArraySize(BiasList);
      ArrayResize(BiasList, n + 1);

      BiasList[n].time            = event_time;
      BiasList[n].asset           = asset;
      BiasList[n].sentiment_score = score;
     }
     
     if(ArraySize(BiasList) == 0 && !DownloadMode) // Biaslist is empty even tho webrequest was sucessful
     {
      if(startdate > TimeCurrent() - 5*24*60*60)   // reaching 5 days back day by day to get valid bias points
      return DownloadAndFillBias(startdate - 24*60*60, asset, false, showSummary);

      ArrayResize(BiasList, 1); // inserting dummy bias sentiment of 0 value
      BiasList[0].time            = TimeCurrent();
      BiasList[0].asset           = asset;
      BiasList[0].sentiment_score = 0;

      LastBiasTimeCheck = TimeCurrent();
      Print("GOATBiasHistory: No bias points found after going back 5 days. Injected dummy 0 bias point for " + asset);
      return true;
     }
   //--- Post-parse sanity checks: remove double-stamped timestamps; alert+break on wrong order
   for(int i = 1; i < ArraySize(BiasList); )
     {
      if(BiasList[i].time == BiasList[i - 1].time)
        {
         Print("GOATBiasHistory: Duplicate bias timestamps detected for " + asset + " at "+TimeToString(BiasList[i].time, TIME_DATE|TIME_MINUTES)
               + ". Removing duplicate entry at index " + (string)i + ".");

         for(int j = i; j < ArraySize(BiasList) - 1; j++) BiasList[j] = BiasList[j + 1];

         ArrayResize(BiasList, ArraySize(BiasList) - 1);
         continue; // re-check same i against i-1 after shift
        }
      if(BiasList[i].time < BiasList[i - 1].time)
        {
         string order_msg = "GOATBiasHistory: Bias download order is incorrect for " + asset + " Out-of-order at indices " + (string)(i - 1) + " -> " + (string)i
                            + " (" + TimeToString(BiasList[i - 1].time, TIME_DATE|TIME_MINUTES|TIME_SECONDS)+ " then " + TimeToString(BiasList[i].time, TIME_DATE|TIME_MINUTES) + ").";
         if(showSummary) Alert(order_msg);
         else            Print(order_msg);
         break;
        }
      i++;
     }
   if(DownloadMode && showSummary)
   {
    if(ArraySize(BiasList)>0) MessageBox("Captured "+(string)ArraySize(BiasList)+" Bias points for "+asset+"\nDropped "+(string)dropped+" Bias points for "+asset,"Bias Download Complete",MB_OK|MB_ICONINFORMATION);
    else                      MessageBox("No Bias points for "+asset+"\n\nResponse="+json,"Bias Download Incomplete",MB_OK|MB_ICONERROR);
   }
   Print("Captured "+(string)ArraySize(BiasList)+" Bias points for "+asset);
   Print("Dropped "+(string)dropped+" Bias points for "+asset);
   
   if(ArraySize(BiasList) > 0) LastBiasTimeCheck = TimeCurrent();
   return (ArraySize(BiasList) > 0);
  }
//+------------------------------------------------------------------+
datetime GOATFullHistorySyncStart(void)
  {
   return D'2023.01.01';
  }
//+------------------------------------------------------------------+
int GetGOATSupportedBiasAssets(string &assets[])
  {
   string supported_assets[] =
     {
      "EURUSD","GBPUSD","USDJPY","USDCAD","USDCHF","AUDUSD","NZDUSD",
      "EURGBP","EURJPY","EURAUD","EURNZD","EURCAD","EURCHF",
      "GBPJPY","GBPAUD","GBPNZD","GBPCAD","GBPCHF",
      "AUDJPY","AUDCAD","AUDNZD","AUDCHF","NZDJPY","NZDCAD","NZDCHF","CADJPY","CADCHF","CHFJPY",
      "US500","NAS100","US30","GER40","EU50","JP225","AUS200",
      "BTCUSD","ETHUSD",
      "XAUUSD","XAGUSD"
     };

   int total = ArraySize(supported_assets);
   ArrayResize(assets, total);
   for(int i = 0; i < total; i++) assets[i] = supported_assets[i];
   return total;
  }
//+------------------------------------------------------------------+
bool GOATNewsFilter::LoadBacktestFileAndFillNews()  {
   string inputFileName = NEWS_FILE;//Key_+"\\"+Download_News_FileName + ".csv";
   int inputFileHandle = FileOpen(inputFileName, FILE_READ | FILE_SHARE_READ | FILE_CSV | FILE_COMMON, ",");

   if(inputFileHandle == INVALID_HANDLE)
     {
      Print("Error opening news file for reading. Error="+(string)GetLastError());
      return(false);
     }
   Print("Reading News history from the News file...");
   
   BrokerGMTOffsetSec = 0;
   BrokerDSTEnabled   = 0;
   if(!LoadOrSaveBrokerTimeFiles(BrokerGMTOffsetSec, BrokerDSTEnabled, true,Key_)) return(false);

   ArrayResize(NewsList, 0);
   //--- skip header row
   if(FileIsEnding(inputFileHandle))
     {
      FileClose(inputFileHandle);
      return(false);
     }

   for(int i = 0; i < 9 && !FileIsEnding(inputFileHandle); i++) FileReadString(inputFileHandle);
   
   int events=0;
   while(!FileIsEnding(inputFileHandle))
     {
      string time_s = FileReadString(inputFileHandle);
      string cur    = FileReadString(inputFileHandle);
      string imp_s  = FileReadString(inputFileHandle);
      string name   = FileReadString(inputFileHandle);
      string act_s  = FileReadString(inputFileHandle);
      string fc_s   = FileReadString(inputFileHandle);
      string prev_s = FileReadString(inputFileHandle);
      string out_s  = FileReadString(inputFileHandle);
      string desc   = FileReadString(inputFileHandle);

      if(time_s == "" && cur == "")
        {
         if(FileIsEnding(inputFileHandle)) break;
         continue;
        }
      events++; // File not ending event found
      
      datetime utc_t = StringToTime(time_s);
      
      if(utc_t<TimeCurrent()) continue;
      if(StringFind(SymbolCurrenciesString, cur) == -1) continue;
      
      int score=(int)StringToInteger(imp_s);
      if(score<News_threshold) continue;
      
      int n = ArraySize(NewsList);
      ArrayResize(NewsList, n + 1);
      
      datetime adj_t = utc_t + (datetime)BrokerGMTOffsetSec;
      if(BrokerDSTEnabled == 1 && IsInUSDST(utc_t)) adj_t += 3600;
      
      NewsList[n].time = adj_t;
      NewsList[n].currency        = cur;
      NewsList[n].impact_score    = score;
      NewsList[n].name            = name;
      NewsList[n].actual          = 0;//StringToDouble(act_s);
      NewsList[n].forecast        = 0;//StringToDouble(fc_s);
      NewsList[n].previous        = 0;//StringToDouble(prev_s);
      NewsList[n].outcome         = (StringToInteger(out_s) > 0);
      //NewsList[n].newsDescription = desc;
      
      if(n==0&&NewsList[n].time>TimeCurrent()) Alert("Loading News File start date ("+(string)NewsList[n].time+") is greater than test start date ("+(string)TimeCurrent()+") Ensure full news history");
      else if(n==0)                            Print("News File start date is "+(string)NewsList[n].time);
      //Print(NewsList[n].time+" "+NewsList[n].currency+" "+NewsList[n].impact_score+" "+NewsList[n].name+" "+NewsList[n].actual+" "+NewsList[n].outcome+" "+NewsList[n].newsDescription);
     }
   FileClose(inputFileHandle);
   Print((string)events+" News events found");
   Print((string)ArraySize(NewsList)+" News events kept");
   return(ArraySize(NewsList) > 0);
  }
//+------------------------------------------------------------------+
bool GOATBiasHistory::LoadBacktestFileAndFillBias()
  {
   string inputFileName = BIAS_FILE+ConvertToGOATsymbol(Symbol())+".csv";
   int inputFileHandle = FileOpen(inputFileName, FILE_READ | FILE_SHARE_READ | FILE_CSV | FILE_COMMON, ",");

   if(inputFileHandle == INVALID_HANDLE)
     {
      PrintFormat("Error opening bias file for reading. Error=%d.",GetLastError());
      return false;
     }
   Print("Reading Bias history from the Bias file...");
   
   BrokerGMTOffsetSec = 0;
   BrokerDSTEnabled   = 0;
   if(!LoadOrSaveBrokerTimeFiles(BrokerGMTOffsetSec, BrokerDSTEnabled, true,Key_)) return false;

   ArrayResize(BiasList, 0);

   if(FileIsEnding(inputFileHandle))
     {
      FileClose(inputFileHandle);
      return false;
     }

   for(int i = 0; i < 3 && !FileIsEnding(inputFileHandle); i++) FileReadString(inputFileHandle);
   
   while(!FileIsEnding(inputFileHandle))
     {
      string time_s = FileReadString(inputFileHandle);
      string asset  = FileReadString(inputFileHandle);
      string sc_s   = FileReadString(inputFileHandle);

      if(time_s == "" && asset == "")
        {
         if(FileIsEnding(inputFileHandle))
            break;
         continue;
        }

      int n = ArraySize(BiasList);
      ArrayResize(BiasList, n + 1);

      datetime utc_t = StringToTime(time_s);
      datetime adj_t = utc_t + (datetime)BrokerGMTOffsetSec;
      if(BrokerDSTEnabled == 1 && IsInUSDST(utc_t)) adj_t += 3600;
      
      BiasList[n].time = adj_t;
      BiasList[n].asset = asset;
      BiasList[n].sentiment_score = (int)StringToInteger(sc_s);

      if(n == 0 && BiasList[n].time > TimeCurrent()) Alert("Loading Bias File start date (" + (string)BiasList[n].time + ") is greater than test start date (" + (string)TimeCurrent() + ") Ensure full bias history");
      else if(n==0)                                  Print("Bias File start date is "+(string)BiasList[n].time);
      //Print(BiasList[n].time+" "+BiasList[n].asset+" "+BiasList[n].sentiment_score+" ");
     }
   FileClose(inputFileHandle);

   Print((string)ArraySize(BiasList) + " Bias points found");
   return (ArraySize(BiasList) > 0);
  }
//-------------------------------------------------------------------------
bool IsInUSDST(datetime t_gmt)
  {
   static int      cache_year  = -1;
   static datetime cache_begin = 0;
   static datetime cache_end   = 0;

   MqlDateTime dt;
   TimeToStruct(t_gmt,dt);
   int y = dt.year;

   if(y != cache_year)
     {
      cache_year = y;
      if(!GetUSDSTWindow(y, cache_begin, cache_end))
        {
         cache_begin = 0;
         cache_end   = 0;
        }
     }

   if(cache_begin<=0 || cache_end<=0) return false;
   return (t_gmt >= cache_begin && t_gmt < cache_end);
  }
//-------------------------------------------------------------------------
bool GetUSDSTWindow(int year,datetime &dst_begin,datetime &dst_end)
  {
   // US DST schedule (dates only) 2014..2033
   static int years[] = {2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026,2027,2028,2029,2030,2031,2032,2033};
   static int bmon[]  = {3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3};
   static int bday[]  = {9,8,13,12,11,10,8,14,13,12,10,9,8,14,12,11,10,9,14,13};
   static int emon[]  = {11,11,11,11,11,11,11,11,11,11,11,11,11,11,11,11,11,11,11,11};
   static int eday[]  = {2,1,6,5,4,3,1,7,6,5,3,2,1,7,5,4,3,2,7,6};

   dst_begin = 0;
   dst_end   = 0;

   for(int i=0; i<ArraySize(years); i++)
     {
      if(years[i] != year) continue;

      MqlDateTime sd;
      sd.year=year; sd.mon=bmon[i]; sd.day=bday[i]; sd.hour=0; sd.min=0; sd.sec=0;

      MqlDateTime ed;
      ed.year=year; ed.mon=emon[i]; ed.day=eday[i]; ed.hour=0; ed.min=0; ed.sec=0;

      dst_begin = StructToTime(sd);
      dst_end   = StructToTime(ed);
      break;
     }

   return (dst_begin>0 && dst_end>0);
  }
//-------------------------------------------------------------------------
bool LoadOrSaveBrokerTimeFiles(int &gmt_offset_sec,int &dst_enabled,bool LoadOrSave,string _Key_)
  {
   //string GOAT_GMT_OFFSET_FILE = _Key_+"\\"+"GOAT_GMToffset.txt";
   //string GOAT_DST_FILE        = _Key_+"\\"+"GOAT_DST.txt";
   
   const int STEP_SEC = 1800; // 30 minutes
   //--- LOAD
   if(LoadOrSave)
     {
      gmt_offset_sec = 0;
      dst_enabled    = 0;

      //--- read GMT offset
      int h = FileOpen(GMT_OFFSET_FILE, FILE_READ | FILE_TXT | FILE_COMMON);
      if(h == INVALID_HANDLE)
        {
         Alert("GMT_Offset file missing/unreadable: " + GMT_OFFSET_FILE);
         return false;
        }

      string s = "";
      if(!FileIsEnding(h)) s = FileReadString(h);
      FileClose(h);

      if(s == "")
        {
         Alert("GMT_Offset file empty: " + GMT_OFFSET_FILE);
         return false;
        }

      int v = (int)StringToInteger(s);

      int vr = 0;
      if(v >= 0) vr = ((v + STEP_SEC/2) / STEP_SEC) * STEP_SEC;
      else       vr = ((v - STEP_SEC/2) / STEP_SEC) * STEP_SEC;

      if(vr != v) Print("GMT_Offset file was not a clean 30-min step. Rounding. File=" + GMT_OFFSET_FILE + " Old=" + (string)v + " New=" + (string)vr);

      gmt_offset_sec = vr;

      //--- read DST flag (optional)
      int d = -1;
      h = FileOpen(DST_FILE, FILE_READ | FILE_TXT | FILE_COMMON);
      if(h != INVALID_HANDLE)
        {
         string ds = "";
         if(!FileIsEnding(h)) ds = FileReadString(h);
         FileClose(h);

         if(ds != "") d = (int)StringToInteger(ds);
        }

      if(d == 0 || d == 1)
        {
         dst_enabled = d;
         return true;
        }

      //--- DST missing/invalid: avoid prompting in tester/optimizer
      if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))
        {
         Alert("DST file missing/invalid. Defaulting DST=0 for backtest. File: " + DST_FILE);
         dst_enabled = 0;
         return true;
        }

      int ret = MessageBox("Does your broker adjusts with day light savings time?","Broker DST",MB_YESNOCANCEL);
      if(ret == IDYES)
        {
         dst_enabled = 1;
         h = FileOpen(DST_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON);
         if(h != INVALID_HANDLE) {FileWriteString(h, "1"); FileClose(h);}
         return true;
        }
      if(ret == IDNO)
        {
         dst_enabled = 0;
         h = FileOpen(DST_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON);
         if(h != INVALID_HANDLE) {FileWriteString(h, "0"); FileClose(h);}
         return true;
        }
      // cancel -> do not save DST file
      return false;
     }
   //--- SAVE
   int raw = (int)(TimeTradeServer() - TimeGMT());

   //--- round to 30-min step
   int rounded = 0;
   if(raw >= 0) rounded = ((raw + STEP_SEC/2) / STEP_SEC) * STEP_SEC;
   else         rounded = ((raw - STEP_SEC/2) / STEP_SEC) * STEP_SEC;

   //--- get/decide DST flag
   int dst = -1;
   int existing_dst = -1;

   int hdst = FileOpen(DST_FILE, FILE_READ | FILE_TXT | FILE_COMMON);
   if(hdst != INVALID_HANDLE)
     {
      string ds = "";
      if(!FileIsEnding(hdst)) ds = FileReadString(hdst);
      FileClose(hdst);

      if(ds != "") existing_dst = (int)StringToInteger(ds);
     }

   if(existing_dst == 0 || existing_dst == 1)
      dst = existing_dst;
   else
     {
      if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))
        {
         dst = 0; // no prompts in tester/optimizer
        }
      else
        {
         int ret = MessageBox("Does your broker adjusts with day light savings time?","Broker DST",MB_YESNOCANCEL);
         if(ret == IDYES) dst = 1;
         else if(ret == IDNO) dst = 0;
         else return false; // cancel -> don't save anything
        }
     }

   //--- save offset WITHOUT DST regardless of when saved      
   datetime gmt_now = TimeGMT();
   bool in_usdst    = IsInUSDST(gmt_now);          // DST window (US schedule) in GMT reference
   int  local_dst_seconds = (int)TimeDaylightSavings();  // extra sanity signal (platform/local)
   bool local_in_dst      = (local_dst_seconds != 0);
   //--- optional sanity warning (do not block saving)
   if(dst == 1 && in_usdst != local_in_dst)
     {
      static bool dst_sanity_logged = false;
      if(!dst_sanity_logged)
        {
         dst_sanity_logged = true;
         Print("DST sanity check: US-DST-window=" + (string)(in_usdst ? 1 : 0) +
               " LocalDSTFlag=" + (string)(local_in_dst ? 1 : 0) +
               " TimeDaylightSavings=" + (string)local_dst_seconds + ". Saving continues.");
        }
     }
   //--- SAVE STANDARD OFFSET (no DST) regardless of saving date
   // If broker uses DST and we are currently inside the DST window, server offset is typically +3600.
   // We remove that hour so the stored value remains the baseline (non-DST) offset.
   int save_offset = rounded;
   if(dst == 1 && in_usdst) save_offset = rounded - 3600;

   //--- check existing GMT file content and alert if it differs
   int existing_gmt = 0;
   bool has_existing_gmt = false;

   int hg = FileOpen(GMT_OFFSET_FILE, FILE_READ | FILE_TXT | FILE_COMMON);
   if(hg != INVALID_HANDLE)
     {
      string gs = "";
      if(!FileIsEnding(hg)) gs = FileReadString(hg);
      FileClose(hg);

      if(gs != "")
        {
         existing_gmt = (int)StringToInteger(gs);
         has_existing_gmt = true;
        }
     }

   if(has_existing_gmt && existing_gmt != save_offset)
      Alert("GMToffset file value differs. Overwriting. Old=" + (string)existing_gmt + " New=" + (string)save_offset);

   //--- write GMT file
   hg = FileOpen(GMT_OFFSET_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(hg == INVALID_HANDLE)
     {
      Alert("Failed to write GMT_Offset file: " + GMT_OFFSET_FILE);
      return false;
     }
   FileWriteString(hg, (string)save_offset);
   FileClose(hg);

   //--- write/update DST file (only if we have valid 0/1)
   if(!(dst == 0 || dst == 1)) dst = 0;

   int cur_dst = -1;
   hdst = FileOpen(DST_FILE, FILE_READ | FILE_TXT | FILE_COMMON);
   if(hdst != INVALID_HANDLE)
     {
      string cds = "";
      if(!FileIsEnding(hdst)) cds = FileReadString(hdst);
      FileClose(hdst);

      if(cds != "") cur_dst = (int)StringToInteger(cds);
     }

   if(cur_dst == 0 || cur_dst == 1)
     {
      if(cur_dst != dst)
         Alert("DST file value differs. Overwriting. Old=" + (string)cur_dst + " New=" + (string)dst);
     }

   hdst = FileOpen(DST_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(hdst != INVALID_HANDLE)
     {
      FileWriteString(hdst, (string)dst);
      FileClose(hdst);
     }

   gmt_offset_sec = save_offset;
   dst_enabled    = dst;
   return true;
  }
//+------------------------------------------------------------------+
