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

CV2PortfolioManager *g_goat2=NULL;
CV2ChartHUD           g_operation_hud;
bool                  g_trading_mode=false;

int OnInit(void)
  {
   string reason="";
   if(!V2ValidateInputs(reason))
     {
      Print("GOAT2|INIT|FAILED|INPUTS|",reason);
      return INIT_FAILED;
     }
   g_trading_mode=V2OperationModeAllowsExecutionPath(V2_Mode_Operation);
   if(!g_trading_mode)
     {
      if(!g_operation_hud.Initialize(true,V2_Mode_Operation,reason))
        {
         Print("GOAT2|INIT|FAILED|OPERATION_MODE_HUD|",reason);
         return INIT_FAILED;
        }
      g_operation_hud.RenderOperationStatus();
      Print("GOAT2|OPERATION_MODE|",V2OperationModeName(V2_Mode_Operation),"|",
            V2OperationModeStatus(V2_Mode_Operation));
      return INIT_SUCCEEDED;
     }

   g_goat2=new CV2PortfolioManager();
   if(CheckPointer(g_goat2)==POINTER_INVALID ||
      !g_goat2.Initialize(GOAT2_PRODUCT_VERSION,GOAT2_BUILD_ID,reason))
     {
      Print("GOAT2|INIT|FAILED|",reason);
      if(CheckPointer(g_goat2)!=POINTER_INVALID)
        {
         g_goat2.Shutdown(REASON_INITFAILED);
         delete g_goat2;
         g_goat2=NULL;
        }
      return INIT_FAILED;
     }
   ResetLastError();
   if(!EventSetTimer(1))
     {
      reason="EVENT_TIMER_START_FAILED:"+IntegerToString(GetLastError());
      Print("GOAT2|INIT|FAILED|",reason);
      g_goat2.Shutdown(REASON_INITFAILED);
      delete g_goat2;
      g_goat2=NULL;
      return INIT_FAILED;
     }
   return INIT_SUCCEEDED;
  }

void OnTick(void)
  {
   if(!g_trading_mode || CheckPointer(g_goat2)==POINTER_INVALID) return;
   MqlTick tick;
   if(SymbolInfoTick(_Symbol,tick))
      g_goat2.OnTick(tick);
  }

void OnTimer(void)
  {
   if(g_trading_mode && CheckPointer(g_goat2)!=POINTER_INVALID)
      g_goat2.OnTimer();
  }

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(g_trading_mode && CheckPointer(g_goat2)!=POINTER_INVALID)
      g_goat2.OnTradeTransaction(transaction,request,result);
  }

void OnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
  {
   if(g_trading_mode && CheckPointer(g_goat2)!=POINTER_INVALID)
      g_goat2.OnChartEvent(id,lparam,dparam,sparam);
  }

double OnTester(void)
  {
   if(!g_trading_mode || CheckPointer(g_goat2)==POINTER_INVALID)
      return 0.0;
   return g_goat2.TesterScore();
  }

void OnDeinit(const int reason)
  {
   if(g_trading_mode)
     {
      EventKillTimer();
      if(CheckPointer(g_goat2)!=POINTER_INVALID)
        {
         g_goat2.Shutdown(reason);
         delete g_goat2;
         g_goat2=NULL;
        }
     }
   else
      g_operation_hud.Shutdown();
  }
