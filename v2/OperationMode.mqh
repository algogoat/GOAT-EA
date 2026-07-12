#ifndef GOAT_V2_OPERATION_MODE_MQH
#define GOAT_V2_OPERATION_MODE_MQH

// Product-surface names intentionally match blueprint section 13.4.
enum ENUM_V2_OPERATION_MODE
  {
   TRADING=0,
   PORTFOLIO_DASHBOARD=1,
   OPTIMIZATION_STUDIO=2,
   REPORT_PROCESSOR=3
  };

string V2OperationModeName(const ENUM_V2_OPERATION_MODE mode)
  {
   switch(mode)
     {
      case TRADING:             return "TRADING";
      case PORTFOLIO_DASHBOARD: return "PORTFOLIO_DASHBOARD";
      case OPTIMIZATION_STUDIO: return "OPTIMIZATION_STUDIO";
      case REPORT_PROCESSOR:    return "REPORT_PROCESSOR";
     }
   return "UNKNOWN_OPERATION_MODE";
  }

bool V2OperationModeAllowsExecutionPath(const ENUM_V2_OPERATION_MODE mode)
  {
   return (mode==TRADING);
  }

int V2OperationModeDeliveryPhase(const ENUM_V2_OPERATION_MODE mode)
  {
   switch(mode)
     {
      case TRADING:             return 1;
      case PORTFOLIO_DASHBOARD: return 4;
      case OPTIMIZATION_STUDIO: return 5;
      case REPORT_PROCESSOR:    return 5;
     }
   return 0;
  }

string V2OperationModeStatus(const ENUM_V2_OPERATION_MODE mode)
  {
   if(mode==TRADING)
      return "AVAILABLE - EXECUTION CERTIFICATION GATES STILL APPLY";
   if(mode==PORTFOLIO_DASHBOARD)
      return "READ-ONLY PLACEHOLDER - PHASE 4 NOT YET BUILT";
   if(mode==OPTIMIZATION_STUDIO)
      return "STATUS-ONLY PLACEHOLDER - PHASE 5 NOT YET BUILT";
   if(mode==REPORT_PROCESSOR)
      return "STATUS-ONLY PLACEHOLDER - PHASE 5 NOT YET BUILT";
   return "UNRECOGNIZED MODE - NO EXECUTION PATH";
  }

#endif
