#property copyright "GOATedge.ai"
#property link      "https://goatedge.ai"
#property version   "2.00"
#property strict
#property tester_no_cache
#property description "GOAT2 V2.0 - deterministic, event-sourced execution foundation"
#property description "Fresh V2 product; independent from every GOAT V1 entrypoint and include graph"
#property description "New exposure compile-locked pending external Phase-1 certification"

#define GOAT2_PRODUCT_VERSION "2.0"
#define GOAT2_BUILD_ID        "GOAT2-V2.0-FOUNDATION"
// New exposure remains physically unavailable in this candidate until the
// external Phase-1 certification evidence pack has been completed and the
// release is rebuilt through the controlled certification workflow.
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 0

#include "v2/PortfolioManager.mqh"

CV2PortfolioManager g_goat2;

int OnInit(void)
  {
   string reason="";
   if(!g_goat2.Initialize(GOAT2_PRODUCT_VERSION,GOAT2_BUILD_ID,reason))
     {
      Print("GOAT2|INIT|FAILED|",reason);
      g_goat2.Shutdown(REASON_INITFAILED);
      return INIT_FAILED;
     }
   ResetLastError();
   if(!EventSetTimer(1))
     {
      reason="EVENT_TIMER_START_FAILED:"+IntegerToString(GetLastError());
      Print("GOAT2|INIT|FAILED|",reason);
      g_goat2.Shutdown(REASON_INITFAILED);
      return INIT_FAILED;
     }
   return INIT_SUCCEEDED;
  }

void OnTick(void)
  {
   MqlTick tick;
   if(SymbolInfoTick(_Symbol,tick))
      g_goat2.OnTick(tick);
  }

void OnTimer(void)
  {
   g_goat2.OnTimer();
  }

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   g_goat2.OnTradeTransaction(transaction,request,result);
  }

void OnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
  {
   g_goat2.OnChartEvent(id,lparam,dparam,sparam);
  }

double OnTester(void)
  {
   return g_goat2.TesterScore();
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_goat2.Shutdown(reason);
  }
