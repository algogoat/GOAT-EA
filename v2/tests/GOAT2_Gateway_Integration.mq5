#property copyright "GOATedge.ai"
#property link      "https://goatedge.ai"
#property version   "2.00"
#property strict
#property tester_no_cache
#property description "GOAT2 real gateway integration: certified open, reconcile, forced close, reconcile"

// This executable is intentionally separate from GOAT2 V2.0.mq5. The
// production EA remains compiled with GOAT2_PHASE1_EXECUTION_CERTIFIED=0.
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 1
#define GOAT2_TEST_HOOKS 1
#include "../PortfolioManager.mqh"

enum ENUM_GOAT2_GATEWAY_TEST_STAGE
  {
   GOAT2_TEST_WAIT_FIRST_TICK=0,
   GOAT2_TEST_WAIT_OPEN_RECONCILIATION=1,
   GOAT2_TEST_WAIT_FLAT_RECONCILIATION=2,
   GOAT2_TEST_TERMINAL=3
  };

input group "GOAT2 gateway integration harness"
input ENUM_V2_DIRECTION V2_TestDirection=V2_DIR_LONG;
input int               V2_TestMaximumTicks=10000;
input int               V2_TestMaximumSimulatedSeconds=3600;

const string GOAT2_TEST_ARTIFACT="GOAT2\\tests\\gateway-integration-result.json";

CV2PortfolioManager          *g_manager=NULL;
ENUM_GOAT2_GATEWAY_TEST_STAGE g_stage=GOAT2_TEST_WAIT_FIRST_TICK;
V2GatewayIntegrationSnapshot  g_snapshot;
datetime                      g_first_tick_time=0;
int                           g_tick_count=0;
bool                          g_finished=false;
bool                          g_passed=false;
bool                          g_open_reconciled=false;
bool                          g_reduction_submitted=false;
bool                          g_risk_high_water_latch_rearm_verified=false;
bool                          g_supervised_repromotion_verified=false;
bool                          g_cleanup_requested=false;
double                        g_open_broker_volume=0.0;
double                        g_open_runtime_volume=0.0;
double                        g_open_persisted_volume=0.0;
int                           g_open_position_count=0;
string                        g_terminal_reason="NOT_FINISHED";

string StageName(const ENUM_GOAT2_GATEWAY_TEST_STAGE stage)
  {
   switch(stage)
     {
      case GOAT2_TEST_WAIT_FIRST_TICK:           return "WAIT_FIRST_TICK";
      case GOAT2_TEST_WAIT_OPEN_RECONCILIATION: return "WAIT_OPEN_RECONCILIATION";
      case GOAT2_TEST_WAIT_FLAT_RECONCILIATION: return "WAIT_FLAT_RECONCILIATION";
      case GOAT2_TEST_TERMINAL:                  return "TERMINAL";
     }
   return "UNKNOWN";
  }

string DirectionName(const ENUM_V2_DIRECTION direction)
  {
   if(direction==V2_DIR_LONG) return "LONG";
   if(direction==V2_DIR_SHORT) return "SHORT";
   return "NONE";
  }

double TestVolumeEpsilon(void)
  {
   return V2PhysicalVolumeEpsilon();
  }

bool RefreshSnapshot(string &reason)
  {
   reason="";
   g_snapshot.Reset();
   if(CheckPointer(g_manager)==POINTER_INVALID)
     { reason="MANAGER_POINTER_INVALID"; return false; }
   return g_manager.TestGatewaySnapshot(g_snapshot,reason);
  }

bool WriteResultArtifact(string &reason)
  {
   reason="";
   FolderCreate("GOAT2",FILE_COMMON);
   FolderCreate("GOAT2\\tests",FILE_COMMON);

   string json="{";
   json+="\"schemaVersion\":\"goat2-gateway-integration-result-v1\",";
   json+="\"testId\":\"real-manager-kernel-gateway-open-force-reduce-flat\",";
   json+="\"result\":"+V2JsonQuote(g_passed ? "PASS" : "FAIL")+",";
   json+="\"reason\":"+V2JsonQuote(g_terminal_reason)+",";
   json+="\"terminalStage\":"+V2JsonQuote(StageName(g_stage))+",";
   json+="\"symbol\":"+V2JsonQuote(_Symbol)+",";
   json+="\"direction\":"+V2JsonQuote(DirectionName(V2_TestDirection))+",";
   json+="\"certifiedTestBuild\":true,";
   json+="\"mockExecution\":false,";
   json+="\"openReconciled\":"+V2JsonBool(g_open_reconciled)+",";
   json+="\"forcedReductionSubmitted\":"+V2JsonBool(g_reduction_submitted)+",";
   json+="\"riskHighWaterLatchRearmVerified\":"+V2JsonBool(g_risk_high_water_latch_rearm_verified)+",";
   json+="\"supervisedRepromotionVerified\":"+V2JsonBool(g_supervised_repromotion_verified)+",";
   json+="\"cleanupRequestedAfterFailure\":"+V2JsonBool(g_cleanup_requested)+",";
   json+="\"ticksObserved\":"+IntegerToString(g_tick_count)+",";
   json+="\"openPositionCount\":"+IntegerToString(g_open_position_count)+",";
   json+="\"openBrokerVolume\":"+V2CanonicalDouble(g_open_broker_volume,8)+",";
   json+="\"openRuntimeStandingVolume\":"+V2CanonicalDouble(g_open_runtime_volume,8)+",";
   json+="\"openPersistedStandingVolume\":"+V2CanonicalDouble(g_open_persisted_volume,8)+",";
   json+="\"finalBrokerPositionCount\":"+IntegerToString(g_snapshot.broker_position_count)+",";
   json+="\"finalBrokerStandingVolume\":"+V2CanonicalDouble(g_snapshot.broker_standing_volume,8)+",";
   json+="\"finalRuntimeStandingVolume\":"+V2CanonicalDouble(g_snapshot.runtime_standing_volume,8)+",";
   json+="\"finalPersistedStandingVolume\":"+V2CanonicalDouble(g_snapshot.persisted_standing_volume,8)+",";
   json+="\"persistedProjectionFound\":"+V2JsonBool(g_snapshot.persisted_projection_found)+",";
   json+="\"pendingExecution\":"+V2JsonBool(g_snapshot.pending_execution)+",";
   json+="\"runtimeSequenceStatus\":"+IntegerToString((int)g_snapshot.runtime_sequence_status)+",";
   json+="\"persistedSequenceStatus\":"+IntegerToString((int)g_snapshot.persisted_sequence_status);
   json+="}";

   ResetLastError();
   int handle=FileOpen(GOAT2_TEST_ARTIFACT,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   if(handle==INVALID_HANDLE)
     { reason="RESULT_ARTIFACT_OPEN_FAILED:"+IntegerToString(GetLastError()); return false; }
   ResetLastError();
   const uint written=FileWriteString(handle,json);
   FileFlush(handle);
   const int write_error=GetLastError();
   FileClose(handle);
   if(written==0 || write_error!=0)
     { reason="RESULT_ARTIFACT_WRITE_FAILED:"+IntegerToString(write_error); return false; }
   return true;
  }

void FinishTest(const bool passed,const string terminal_reason)
  {
   if(g_finished) return;
   string snapshot_reason="";
   if(CheckPointer(g_manager)!=POINTER_INVALID && !RefreshSnapshot(snapshot_reason) && snapshot_reason!="")
      Print("GOAT2_TEST|SNAPSHOT_FAILED|",snapshot_reason);

   if(!passed && CheckPointer(g_manager)!=POINTER_INVALID &&
      g_snapshot.broker_standing_volume>TestVolumeEpsilon() && !g_snapshot.pending_execution)
     {
      string cleanup_reason="";
      g_cleanup_requested=g_manager.TestGatewayForceFullReduction(cleanup_reason);
      Print("GOAT2_TEST|FAILURE_CLEANUP|requested=",g_cleanup_requested,
            (cleanup_reason=="" ? "" : "|reason="+cleanup_reason));
     }

   g_passed=passed;
   g_terminal_reason=terminal_reason+(snapshot_reason=="" ? "" : "|SNAPSHOT:"+snapshot_reason);
   g_stage=GOAT2_TEST_TERMINAL;
   g_finished=true;
   string artifact_reason="";
   if(!WriteResultArtifact(artifact_reason))
      Print("GOAT2_TEST|RESULT_ARTIFACT_FAILED|",artifact_reason);
   Print("GOAT2_TEST|",(passed ? "PASS" : "FAIL"),"|",g_terminal_reason,
         "|artifact=FILE_COMMON\\",GOAT2_TEST_ARTIFACT);
  }

bool ValidateHarnessConfiguration(string &reason)
  {
   reason="";
   if(!MQLInfoInteger(MQL_TESTER))
     { reason="STRATEGY_TESTER_REQUIRED"; return false; }
   if(MQLInfoInteger(MQL_OPTIMIZATION))
     { reason="SINGLE_TESTER_PASS_REQUIRED_NOT_OPTIMIZATION"; return false; }
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     { reason="HEDGING_ACCOUNT_REQUIRED"; return false; }
   if(V2_Mode_Operation!=TRADING || V2_RunMode!=V2_RUN_TRADE || !V2_EnableNewRisk)
     { reason="REQUIRE_TRADING_RUN_MODE_AND_ENABLE_NEW_RISK"; return false; }
   if(V2_Bookkeeping!=V2_BOOKKEEPING_FULL)
     { reason="FULL_BOOKKEEPING_REQUIRED"; return false; }
   if(V2_CertificationRun)
     { reason="HARNESS_USES_CERTIFIED_BUILD_NOT_CERTIFICATION_MANIFEST_MODE"; return false; }
   if(V2_SignalMode!=V2_SIGNAL_DISABLED || V2_MaxSequenceTrades!=1)
     { reason="REQUIRE_SIGNAL_DISABLED_AND_ONE_SEQUENCE_LEVEL"; return false; }
   if(V2_LotMode!=V2_LOTS_FIXED || V2_LotProgression!=V2_LOT_START)
     { reason="REQUIRE_FIXED_START_LOT_MODE"; return false; }
   if(V2_StateMode!=V2_STATE_DISABLED || V2_OnnxMode!=V2_ONNX_DISABLED)
     { reason="REQUIRE_INTELLIGENCE_INFLUENCE_DISABLED"; return false; }
   if(V2_EnableHud || V2_EnableOverlay || V2_EnableTelemetry)
     { reason="REQUIRE_HEADLESS_HUD_OVERLAY_TELEMETRY_DISABLED"; return false; }
   if(V2_TestDirection!=V2_DIR_LONG && V2_TestDirection!=V2_DIR_SHORT)
     { reason="TEST_DIRECTION_REQUIRED"; return false; }
   if((V2_TestDirection==V2_DIR_LONG && V2_TradeDirection==V2_TRADE_SHORT_ONLY) ||
      (V2_TestDirection==V2_DIR_SHORT && V2_TradeDirection==V2_TRADE_LONG_ONLY))
     { reason="TEST_DIRECTION_BLOCKED_BY_TRADE_DIRECTION"; return false; }
   if(V2_TestMaximumTicks<2 || V2_TestMaximumSimulatedSeconds<1)
     { reason="TEST_TIMEOUT_CONFIGURATION_INVALID"; return false; }
   return V2ValidateInputs(reason);
  }

void DriveHarness(const bool from_tick)
  {
   if(g_finished || CheckPointer(g_manager)==POINTER_INVALID) return;
   if(from_tick)
     {
      g_tick_count++;
      if(g_first_tick_time==0) g_first_tick_time=TimeCurrent();
     }
   if(g_tick_count>V2_TestMaximumTicks)
     { FinishTest(false,"TIMEOUT_MAXIMUM_TICKS"); return; }
   if(g_first_tick_time>0 && TimeCurrent()-g_first_tick_time>V2_TestMaximumSimulatedSeconds)
     { FinishTest(false,"TIMEOUT_MAXIMUM_SIMULATED_SECONDS"); return; }

   string reason="";
   if(g_stage==GOAT2_TEST_WAIT_FIRST_TICK)
     {
      if(!from_tick) return;
      if(!g_manager.TestGatewayStartSequence(V2_TestDirection,reason))
        { FinishTest(false,"REAL_OPEN_SUBMISSION_FAILED:"+reason); return; }
      g_stage=GOAT2_TEST_WAIT_OPEN_RECONCILIATION;
      return;
     }

   if(!RefreshSnapshot(reason))
     { FinishTest(false,"SNAPSHOT_FAILED:"+reason); return; }
   const double epsilon=TestVolumeEpsilon();

   if(g_stage==GOAT2_TEST_WAIT_OPEN_RECONCILIATION)
     {
      if(g_snapshot.broker_position_count>1)
        { FinishTest(false,"MORE_THAN_ONE_OWNED_BROKER_POSITION_OPENED"); return; }
      if(g_snapshot.runtime_sequence_status==V2_SEQ_ENDED &&
         g_snapshot.broker_standing_volume<=epsilon && !g_snapshot.pending_execution)
        { FinishTest(false,"OPEN_ENDED_WITHOUT_REAL_BROKER_POSITION"); return; }
      const bool volumes_match=(MathAbs(g_snapshot.broker_standing_volume-g_snapshot.runtime_standing_volume)<=epsilon &&
                                MathAbs(g_snapshot.broker_standing_volume-g_snapshot.persisted_standing_volume)<=epsilon);
      if(g_snapshot.broker_position_count==1 && g_snapshot.broker_standing_volume>epsilon &&
         g_snapshot.persisted_projection_found && volumes_match && !g_snapshot.pending_execution)
        {
         g_open_reconciled=true;
         g_open_position_count=g_snapshot.broker_position_count;
         g_open_broker_volume=g_snapshot.broker_standing_volume;
         g_open_runtime_volume=g_snapshot.runtime_standing_volume;
         g_open_persisted_volume=g_snapshot.persisted_standing_volume;
         if(!g_manager.TestGatewayForceFullReduction(reason))
           { FinishTest(false,"FORCED_FULL_REDUCTION_SUBMISSION_FAILED:"+reason); return; }
         g_reduction_submitted=true;
         g_stage=GOAT2_TEST_WAIT_FLAT_RECONCILIATION;
        }
      return;
     }

   if(g_stage==GOAT2_TEST_WAIT_FLAT_RECONCILIATION)
     {
      const bool broker_flat=(g_snapshot.broker_position_count==0 &&
                              g_snapshot.broker_standing_volume<=epsilon);
      const bool journal_flat=(g_snapshot.runtime_standing_volume<=epsilon &&
                               g_snapshot.persisted_projection_found &&
                               g_snapshot.persisted_standing_volume<=epsilon);
      const bool ended=(g_snapshot.runtime_sequence_status==V2_SEQ_ENDED &&
                        g_snapshot.persisted_sequence_status==V2_SEQ_ENDED);
      if(g_open_reconciled && g_reduction_submitted && broker_flat && journal_flat && ended &&
         !g_snapshot.pending_execution)
        {
         if(!g_manager.TestGatewayExerciseRiskHighWaterLatchRearm(reason))
           { FinishTest(false,"RISK_HIGH_WATER_LATCH_REARM_PROBE_FAILED:"+reason); return; }
         g_risk_high_water_latch_rearm_verified=true;
         if(!g_manager.TestGatewayExerciseSupervisedRepromotion(reason))
           { FinishTest(false,"SUPERVISED_REPROMOTION_PROBE_FAILED:"+reason); return; }
         g_supervised_repromotion_verified=true;
         FinishTest(true,"REAL_OPEN_AND_FORCED_FULL_REDUCTION_RECONCILED_FLAT");
        }
     }
  }

int OnInit(void)
  {
   FolderCreate("GOAT2",FILE_COMMON);
   FolderCreate("GOAT2\\tests",FILE_COMMON);
   FileDelete(GOAT2_TEST_ARTIFACT,FILE_COMMON);
   g_snapshot.Reset();

   string reason="";
   if(!ValidateHarnessConfiguration(reason))
     { FinishTest(false,"CONFIGURATION_INVALID:"+reason); return INIT_PARAMETERS_INCORRECT; }

   g_manager=new CV2PortfolioManager();
   if(CheckPointer(g_manager)==POINTER_INVALID ||
      !g_manager.Initialize("2.0-test","GOAT2-V2.0-GATEWAY-INTEGRATION",reason))
     {
      FinishTest(false,"MANAGER_INITIALIZATION_FAILED:"+reason);
      return INIT_FAILED;
     }
   ResetLastError();
   if(!EventSetTimer(1))
     {
      FinishTest(false,"EVENT_TIMER_START_FAILED:"+IntegerToString(GetLastError()));
      return INIT_FAILED;
     }
   Print("GOAT2_TEST|START|real_execution=true|symbol=",_Symbol,
         "|direction=",DirectionName(V2_TestDirection));
   return INIT_SUCCEEDED;
  }

void OnTick(void)
  {
   if(CheckPointer(g_manager)==POINTER_INVALID) return;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick))
     { if(!g_finished) FinishTest(false,"TICK_READ_FAILED"); return; }
   g_manager.OnTick(tick);
   DriveHarness(true);
  }

void OnTimer(void)
  {
   if(CheckPointer(g_manager)==POINTER_INVALID) return;
   g_manager.OnTimer();
   DriveHarness(false);
  }

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(CheckPointer(g_manager)!=POINTER_INVALID)
      g_manager.OnTradeTransaction(transaction,request,result);
  }

double OnTester(void)
  {
   return(g_finished && g_passed ? 1.0 : 0.0);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(!g_finished)
      FinishTest(false,"DEINITIALIZED_BEFORE_TERMINAL_STAGE:"+IntegerToString(reason));
   if(CheckPointer(g_manager)!=POINTER_INVALID)
     {
      g_manager.Shutdown(reason);
      delete g_manager;
      g_manager=NULL;
     }
  }
