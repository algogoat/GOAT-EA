#ifndef GOAT_V2_PORTFOLIO_MANAGER_MQH
#define GOAT_V2_PORTFOLIO_MANAGER_MQH

#ifndef GOAT2_PHASE1_EXECUTION_CERTIFIED
#define GOAT2_PHASE1_EXECUTION_CERTIFIED 0
#endif

#include "Domain.mqh"
#include "Identity.mqh"
#include "Inputs_V2.mqh"
#include "Core_Sequence.mqh"
#include "Core_Risk.mqh"
#include "SafetyKernel.mqh"
#include "Receipts.mqh"
#include "ExperimentManifest.mqh"
#include "StateDB.mqh"
#include "Telemetry.mqh"
#include "BrokerGateway.mqh"
#include "Scheduler.mqh"
#include "Features.mqh"
#include "IntelligenceBus.mqh"
#include "Policy.mqh"
#include "ReplayPack.mqh"
#include "OnnxLayer.mqh"
#include "ChartHUD.mqh"
#include "ChartOverlay.mqh"
#include "Clock.mqh"

#define V2_MANAGER_OBSERVATION_BUDGET 128
#define V2_MANAGER_WORK_BUDGET        8

struct V2OwnedPosition
  {
   ulong             ticket;
   ulong             position_id;
   ENUM_V2_DIRECTION direction;
   double            volume;
   double            open_price;
   double            stop_loss;
   double            take_profit;
   double            profit;
   double            swap;
   datetime          opened_at;

   void Reset(void)
     {
      ticket=0;
      position_id=0;
      direction=V2_DIR_NONE;
      volume=0.0;
      open_price=0.0;
      stop_loss=0.0;
      take_profit=0.0;
      profit=0.0;
      swap=0.0;
      opened_at=0;
     }
  };

struct V2PendingExecution
  {
   bool                active;
   string              order_intent_id;
   ENUM_V2_ACTION_KIND action;
   int                 semantic_level_index;
   ulong               request_id;
   ulong               order_ticket;
   double              requested_volume;
   double              observed_volume;
   long                submitted_at_msc;
   ulong               submitted_tick_count;

   void Reset(void)
     {
      active=false;
      order_intent_id="";
      action=V2_ACTION_OPEN;
      semantic_level_index=-1;
      request_id=0;
      order_ticket=0;
      requested_volume=0.0;
      observed_volume=0.0;
      submitted_at_msc=0;
      submitted_tick_count=0;
     }
  };

#ifdef GOAT2_TEST_HOOKS
struct V2GatewayIntegrationSnapshot
  {
   bool                      initialized;
   bool                      recovery_verified;
   bool                      new_risk_enabled;
   bool                      pending_execution;
   ENUM_V2_OPERATIONAL_STATE operational_state;
   string                    operational_reason;
   string                    sequence_id;
   ENUM_V2_SEQUENCE_STATUS   runtime_sequence_status;
   ENUM_V2_SEQUENCE_STATUS   persisted_sequence_status;
   bool                      persisted_projection_found;
   double                    broker_standing_volume;
   double                    runtime_standing_volume;
   double                    persisted_standing_volume;
   int                       broker_position_count;

   void Reset(void)
     {
      initialized=false;
      recovery_verified=false;
      new_risk_enabled=false;
      pending_execution=false;
      operational_state=V2_OP_HALTED;
      operational_reason="";
      sequence_id="";
      runtime_sequence_status=V2_SEQ_IDLE;
      persisted_sequence_status=V2_SEQ_IDLE;
      persisted_projection_found=false;
      broker_standing_volume=0.0;
      runtime_standing_volume=0.0;
      persisted_standing_volume=0.0;
      broker_position_count=0;
     }
  };
#endif

class CV2PortfolioManager
  {
private:
   string                    m_product_version;
   string                    m_build_id;
   string                    m_last_reason;
   bool                      m_initialized;
   bool                      m_plans_ready;
   bool                      m_recovery_verified;
   bool                      m_risk_high_water_ready;
   bool                      m_broker_profile_verified;
   bool                      m_new_risk_enabled;
   ENUM_V2_OPERATIONAL_STATE m_operational_state;
   string                    m_operational_reason;

   CV2Identity               m_identity;
   CV2DomainMachine          m_domain;
   CV2StateDB                m_database;
   CV2ReceiptBuilder         m_receipts;
   CV2ExperimentManifest     m_manifest_builder;
   V2ExperimentManifest      m_manifest;
   CV2Telemetry              m_telemetry;
   CV2SafetyKernel           m_kernel;
   CV2BrokerGateway          m_gateway;
   CV2Scheduler              m_scheduler;
   CV2Features               m_features;
   CV2IntelligenceBus        m_intelligence;
   CV2Policy                 m_policy;
   CV2ReplayPack             m_replay;
   CV2OnnxLayer              m_onnx;
   CV2ChartHUD               m_hud;
   CV2ChartOverlay           m_overlay;

   CV2GridPlanner            m_grid_planner;
   CV2LotPlanner             m_lot_planner;
   CV2CostRiskEngine         m_risk_engine;
   CV2BasketPlanner          m_basket_planner;
   CV2RetracePlanner         m_retrace_planner;

   V2SequenceState           m_sequence;
   V2LevelState              m_levels[];
   V2GridPlanConfig          m_grid_config;
   V2GridPlan                m_grid_plan;
   V2LotPlanConfig           m_lot_config;
   V2LotPlan                 m_lot_plan;
   V2BrokerCostProfile       m_cost_profile;
   V2RiskMarketContext       m_risk_market;
   V2CostRiskResult          m_risk_result;
   V2FeatureFrame            m_feature_frame;
   V2PolicyEnvelope          m_policy_envelope;
   V2OnnxProposal            m_onnx_proposal;
   V2PendingExecution        m_pending;

   long                      m_last_hud_render_msc;
   datetime                  m_last_entry_decision_bar;
   datetime                  m_last_shadow_decision_bar;
   datetime                  m_last_level_skip_bar;
   int                       m_last_level_skip_index;
   int                       m_broker_mismatch_passes;
   int                       m_healthy_recovery_passes;
   bool                      m_supervised_repromotion_pending;
   double                    m_peak_equity;
   double                    m_maximum_adverse_excursion_atr;
   double                    m_maximum_favorable_excursion_atr;

   bool Fail(const string reason)
     {
      m_last_reason=reason;
      Print("GOAT2|ERROR|",reason);
      return false;
     }

   double PointSize(void) const
     {
      return SymbolInfoDouble(_Symbol,SYMBOL_POINT);
     }

   double TickSize(void) const
     {
      double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      return(tick>0.0 ? tick : PointSize());
     }

   double PipSize(void) const
     {
      return V2V1ConfiguredPipSize(PointSize());
     }

   double CurrentAtrPrice(void) const
     {
      if(!m_feature_frame.atr_points.ready || m_feature_frame.atr_points.value<=0.0)
         return 0.0;
      return m_feature_frame.atr_points.value*PointSize();
     }

   double ResolveSignedDistance(const double configured,const double atr_price) const
     {
      if(configured>0.0) return configured*PipSize();
      if(configured<0.0 && atr_price>0.0) return -configured*atr_price;
      return 0.0;
     }

   ENUM_V2_MANIFEST_CLASS ManifestClass(void) const
     {
      if(V2_CertificationRun) return V2_MANIFEST_CERTIFICATION;
      if(MQLInfoInteger(MQL_OPTIMIZATION)) return V2_MANIFEST_OPTIMIZATION;
      if(!MQLInfoInteger(MQL_TESTER)) return V2_MANIFEST_LIVE;
      return V2_MANIFEST_DEVELOPMENT;
     }

   bool DirectionAllowed(const ENUM_V2_DIRECTION direction) const
     {
      if(direction==V2_DIR_LONG) return V2_TradeDirection!=V2_TRADE_SHORT_ONLY;
      if(direction==V2_DIR_SHORT) return V2_TradeDirection!=V2_TRADE_LONG_ONLY;
      return false;
     }

   void ConfigureCostProfile(void)
     {
      m_cost_profile.Reset();
      m_cost_profile.profile_id=V2_BrokerProfileId;
      m_cost_profile.profile_version=V2_BrokerProfileVersion;
      m_cost_profile.commission_open_per_lot=V2_CommissionOpenPerLot;
      m_cost_profile.commission_close_per_lot=V2_CommissionClosePerLot;
      m_cost_profile.swap_long_per_lot_day=V2_SwapLongPerLotDay;
      m_cost_profile.swap_short_per_lot_day=V2_SwapShortPerLotDay;
      m_cost_profile.projected_holding_days=V2_ProjectedHoldingDays;
      m_cost_profile.projected_triple_swap_events=V2_ProjectedTripleSwapEvents;
      m_cost_profile.triple_swap_multiplier=3.0;
      m_cost_profile.stressed_spread_points=V2_StressedSpreadPoints;
      m_cost_profile.open_slippage_points=V2_OpenSlippagePoints;
      m_cost_profile.close_slippage_points=V2_CloseSlippagePoints;
      m_cost_profile.terminal_adverse_points=V2_TerminalAdversePoints;
      m_cost_profile.allow_positive_swap_credit=false;
     }

   string CurrentSymbolSpecHash(void) const
     {
      string payload="goat2-symbol-spec-v1|"+_Symbol;
      payload+="|digits="+IntegerToString((long)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS));
      payload+="|point="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_POINT));
      payload+="|tickSize="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
      payload+="|tickValue="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE));
      payload+="|contractSize="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE));
      payload+="|volumeMin="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN));
      payload+="|volumeMax="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX));
      payload+="|volumeStep="+V2CanonicalDouble(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP));
      payload+="|stops="+IntegerToString((long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL));
      payload+="|freeze="+IntegerToString((long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL));
      payload+="|calc="+IntegerToString((long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_CALC_MODE));
      payload+="|swap="+IntegerToString((long)SymbolInfoInteger(_Symbol,SYMBOL_SWAP_MODE));
      payload+="|base="+SymbolInfoString(_Symbol,SYMBOL_CURRENCY_BASE);
      payload+="|profit="+SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT);
      payload+="|margin="+SymbolInfoString(_Symbol,SYMBOL_CURRENCY_MARGIN);
      return V2Sha256Hex(payload);
     }

   string CurrentExecutionPlanHash(void) const
     {
      if(!m_grid_plan.valid || !m_lot_plan.valid || !m_risk_result.valid)
         return "";
      string payload="goat2-execution-plan-v1|product="+m_product_version+"|build="+m_build_id;
      payload+="|sourceHash="+m_manifest.external_source_hash;
      payload+="|binaryHash="+m_manifest.external_binary_hash;
      for(int i=0;i<ArraySize(m_grid_plan.step_distance);i++)
         payload+="|gridStep["+IntegerToString(i)+"]="+V2CanonicalDouble(m_grid_plan.step_distance[i]);
      for(int i=0;i<ArraySize(m_grid_plan.cumulative_distance);i++)
         payload+="|gridCumulative["+IntegerToString(i)+"]="+V2CanonicalDouble(m_grid_plan.cumulative_distance[i]);
      for(int i=0;i<ArraySize(m_lot_plan.normalized_delta);i++)
         payload+="|lotDelta["+IntegerToString(i)+"]="+V2CanonicalDouble(m_lot_plan.normalized_delta[i]);
      for(int i=0;i<ArraySize(m_lot_plan.cumulative_lots);i++)
         payload+="|lotCumulative["+IntegerToString(i)+"]="+V2CanonicalDouble(m_lot_plan.cumulative_lots[i]);
      payload+="|terminalAdversePoints="+V2CanonicalDouble(m_cost_profile.terminal_adverse_points);
      return V2Sha256Hex(payload);
     }

   bool StaticSequenceBindingMatches(string &reason) const
     {
      reason="";
      if(m_sequence.experiment_manifest_id=="" ||
         m_sequence.input_values_hash=="" ||
         m_sequence.broker_profile_hash=="" ||
         m_sequence.symbol_spec_hash=="" ||
         m_sequence.execution_plan_hash=="")
        { reason="SEQUENCE_BINDING_INCOMPLETE"; return false; }
      // experiment_manifest_id is the immutable sequence-start audit anchor.
      // A new process has a new run manifest (and timestamp), so recovery
      // compares the stable semantic hashes below instead of requiring two
      // different runs to share one experiment identity.
      if(m_sequence.input_values_hash!=m_manifest.input_values_hash)
        { reason="SEQUENCE_INPUT_HASH_MISMATCH"; return false; }
      if(m_sequence.broker_profile_hash!=m_manifest.broker_profile_hash)
        { reason="SEQUENCE_BROKER_PROFILE_HASH_MISMATCH"; return false; }
      if(m_sequence.symbol_spec_hash!=CurrentSymbolSpecHash())
        { reason="SEQUENCE_SYMBOL_SPEC_HASH_MISMATCH"; return false; }
      return true;
     }

   bool IsSupervisedRecoveryReason(const string reason) const
     {
      return(StringFind(reason,"DATABASE_HEARTBEAT_FAILED:")==0 ||
             StringFind(reason,"RISK_HIGH_WATER_")==0 ||
             StringFind(reason,"TELEMETRY_")==0 ||
             StringFind(reason,"DECISION_TELEMETRY_")==0 ||
             StringFind(reason,"OBSERVATION_")==0 ||
             StringFind(reason,"BROKER_MATCH_RECHECK_REQUIRED:")==0 ||
             StringFind(reason,"GATEWAY_REQUIRES_MANAGE_ONLY:")==0 ||
             StringFind(reason,"ENTRY_OUTCOME_REQUIRES_RECONCILIATION:")==0 ||
             StringFind(reason,"REDUCTION_GATEWAY_DEGRADED:")==0 ||
             StringFind(reason,"REDUCTION_OUTCOME_REQUIRES_RECONCILIATION:")==0 ||
             StringFind(reason,"PROTECTION_GATEWAY_DEGRADED:")==0);
     }

   void SetOperationalState(const ENUM_V2_OPERATIONAL_STATE state,const string reason)
     {
      const bool changed=(state!=m_operational_state || reason!=m_operational_reason);
      const bool supervised_candidate=(state==V2_OP_DEGRADED ||
                                       (state==V2_OP_MANAGE_ONLY &&
                                        IsSupervisedRecoveryReason(reason)));
      if(supervised_candidate)
        {
         // Every observed failure starts a fresh three-pass audit. Healthy
         // observations accumulated before the degradation never count.
         m_supervised_repromotion_pending=true;
         m_healthy_recovery_passes=0;
        }
      else if(state==V2_OP_NORMAL || state==V2_OP_RECOVERY_QUARANTINE ||
              state==V2_OP_HALTED || state==V2_OP_MANAGE_ONLY)
        {
         m_supervised_repromotion_pending=false;
         m_healthy_recovery_passes=0;
        }
      m_operational_state=state;
      m_operational_reason=reason;
      m_new_risk_enabled=(GOAT2_PHASE1_EXECUTION_CERTIFIED==1 &&
                          state==V2_OP_NORMAL && V2_RunMode==V2_RUN_TRADE &&
                          V2_EnableNewRisk && m_recovery_verified);
      m_gateway.SetOperationalState(state);
      if(m_new_risk_enabled)
         m_gateway.SetNewRiskEnabled(true);
      m_last_reason=reason;
      m_hud.MarkDirty();
      if(changed)
        {
         Print("GOAT2|STATE|",IntegerToString((int)state),"|",reason);
         if(m_initialized)
           {
            string receipt_reason="";
            if(!PersistOperationalStateReceipt(receipt_reason))
               Print("GOAT2|STATE|RECEIPT_FAILED|",receipt_reason);
           }
        }
     }

   bool ApplyIntentTransition(V2OrderIntent &intent,
                              const ENUM_V2_ORDER_INTENT_STATUS next,
                              string &reason) const
     {
      CV2OrderIntentMachine machine;
      return machine.Apply(next,intent,reason);
     }

   bool ApplyObservedIntentTransition(V2OrderIntent &intent,
                                      const ENUM_V2_ORDER_INTENT_STATUS next,
                                      string &reason) const
     {
      reason="";
      if(intent.status==V2_INTENT_PLANNED && next!=V2_INTENT_PERSISTED &&
         !ApplyIntentTransition(intent,V2_INTENT_PERSISTED,reason))
         return false;
      if(intent.status==V2_INTENT_PERSISTED && next!=V2_INTENT_SUBMITTED &&
         next!=V2_INTENT_CANCELLED &&
         !ApplyIntentTransition(intent,V2_INTENT_SUBMITTED,reason))
         return false;
      return ApplyIntentTransition(intent,next,reason);
     }

   int FindLevelByPositionId(const ulong position_id) const
     {
      if(position_id==0) return -1;
      for(int i=0;i<ArraySize(m_levels);i++)
         if(m_levels[i].position_id==position_id && !m_levels[i].closed)
            return i;
      return -1;
     }

   int ExecutedTradeCount(void) const
     {
      const double epsilon=V2PhysicalVolumeEpsilon();
      int count=0;
      for(int i=0;i<ArraySize(m_levels);i++)
         if(m_levels[i].position_id!=0 || m_levels[i].filled_volume>epsilon || m_levels[i].closed)
            count++;
      return count;
     }

   bool HasOwnedPendingOrders(void) const
     {
      for(int i=0;i<OrdersTotal();i++)
        {
         ulong ticket=OrderGetTicket(i);
         if(ticket==0 || !OrderSelect(ticket)) continue;
         if((ulong)OrderGetInteger(ORDER_MAGIC)==m_identity.Magic())
            return true;
        }
      return false;
     }

   bool ScanOwnedPositions(V2OwnedPosition &positions[],
                           double &standing,
                           double &vwap,
                           double &floating_pl,
                           string &reason) const
     {
      ArrayResize(positions,0);
      standing=0.0;
      vwap=0.0;
      floating_pl=0.0;
      reason="";
      double weighted=0.0;
      for(int i=0;i<PositionsTotal();i++)
        {
         ulong ticket=PositionGetTicket(i);
         if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
         if((ulong)PositionGetInteger(POSITION_MAGIC)!=m_identity.Magic()) continue;
         const string symbol=PositionGetString(POSITION_SYMBOL);
         if(symbol!=_Symbol)
           {
            reason="OWNED_POSITION_OUTSIDE_PHASE1_SYMBOL:"+symbol;
            return false;
           }
         V2OwnedPosition position;
         position.Reset();
         position.ticket=ticket;
         position.position_id=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
         const ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         position.direction=(type==POSITION_TYPE_BUY ? V2_DIR_LONG : V2_DIR_SHORT);
         position.volume=PositionGetDouble(POSITION_VOLUME);
         position.open_price=PositionGetDouble(POSITION_PRICE_OPEN);
         position.stop_loss=PositionGetDouble(POSITION_SL);
         position.take_profit=PositionGetDouble(POSITION_TP);
         position.profit=PositionGetDouble(POSITION_PROFIT);
         position.swap=PositionGetDouble(POSITION_SWAP);
         position.opened_at=(datetime)PositionGetInteger(POSITION_TIME);
         const int index=ArraySize(positions);
         if(ArrayResize(positions,index+1)!=index+1)
           { reason="OWNED_POSITION_ALLOCATION_FAILED"; return false; }
         positions[index]=position;
         standing+=position.volume;
         weighted+=position.volume*position.open_price;
         floating_pl+=position.profit+position.swap;
        }
      if(standing>0.0) vwap=weighted/standing;
      return true;
     }

public:
                     CV2PortfolioManager(void)
     {
      m_product_version="2.0";
      m_build_id="GOAT2-V2.0";
      m_last_reason="NOT_INITIALIZED";
      m_initialized=false;
      m_plans_ready=false;
      m_recovery_verified=false;
      m_risk_high_water_ready=false;
      m_broker_profile_verified=false;
      m_new_risk_enabled=false;
      m_operational_state=V2_OP_MANAGE_ONLY;
      m_operational_reason="NOT_INITIALIZED";
      m_sequence.Reset();
      ArrayResize(m_levels,0);
      m_grid_config.Reset();
      m_grid_plan.Reset();
      m_lot_config.Reset();
      m_lot_plan.Reset();
      m_cost_profile.Reset();
      m_risk_market.Reset();
      m_risk_result.Reset();
      m_feature_frame.Reset();
      m_policy_envelope.Reset();
      m_onnx.Evaluate(m_feature_frame,m_onnx_proposal);
      m_pending.Reset();
      m_last_hud_render_msc=0;
      m_last_entry_decision_bar=0;
      m_last_shadow_decision_bar=0;
      m_last_level_skip_bar=0;
      m_last_level_skip_index=-1;
      m_broker_mismatch_passes=0;
      m_healthy_recovery_passes=0;
      m_supervised_repromotion_pending=false;
      m_peak_equity=0.0;
      m_maximum_adverse_excursion_atr=0.0;
      m_maximum_favorable_excursion_atr=0.0;
     }

private:
   bool BuildManifest(const ENUM_V2_STATE_DB_MODE database_mode,string &reason)
     {
      if(!m_manifest_builder.CaptureRuntime(m_identity,
                                            m_product_version,
                                            m_build_id,
                                            ManifestClass(),
                                            V2_Bookkeeping,
                                            V2StateDBModeName(database_mode),
                                            m_manifest,
                                            reason))
         return false;
      V2ExternalLineage lineage;
      lineage.Reset();
      lineage.git_commit=V2_LineageGitCommit;
      lineage.source_hash=V2_LineageSourceHash;
      lineage.binary_hash=V2_LineageBinaryHash;
      lineage.reference_commit=V2_LineageReferenceCommit;
      // A literal .set self-hash is circular when lineage itself is supplied
      // as tester inputs. Use the manifest's normalized strategy-input hash,
      // whose canonical payload deliberately excludes lineage fields.
      lineage.set_hash=m_manifest.input_values_hash;
      lineage.tick_data_hash=V2_LineageTickDataHash;
      lineage.tester_model=V2_LineageTesterModel;
      lineage.test_window=V2_LineageTestWindow;
      lineage.state_pack_hash=V2_LineageStatePackHash;
      lineage.calendar_hash=V2_LineageCalendarHash;
      lineage.model_bundle_hash=V2_LineageModelBundleHash;
      lineage.broker_profile_version=V2_BrokerProfileId+"@"+V2_BrokerProfileVersion;
      lineage.broker_profile_hash=V2Sha256Hex(V2CanonicalBrokerProfileInputs());
      lineage.random_seed=V2_LineageRandomSeed;
      m_manifest_builder.AttachExternalLineage(lineage,m_manifest);
      if(V2_CertificationRun && !m_manifest_builder.ValidateForCertification(m_manifest,reason))
         return false;
      if(!m_manifest_builder.Finalize(m_manifest,reason))
         return false;
      return m_database.SaveExperimentManifest(m_manifest,reason);
     }

   bool InitializeRiskHighWater(string &reason)
     {
      reason="";
      double stored=0.0;
      bool found=false;
      if(!m_database.LoadRiskHighWater("account_equity_peak",stored,found,reason)) return false;
      const double current=AccountInfoDouble(ACCOUNT_EQUITY);
      // Preserve an in-memory peak that may be newer than the durable value.
      // This matters when a transient metadata read/write failure degraded the
      // manager after the account made a new equity high: recovery must retry
      // the highest observed value, never a later lower account snapshot.
      m_peak_equity=MathMax(m_peak_equity,MathMax(current,(found ? stored : 0.0)));
      if(!found || m_peak_equity>stored)
        {
         if(!m_database.StoreRiskHighWater("account_equity_peak",m_peak_equity,reason)) return false;
        }
      m_risk_high_water_ready=true;
      return true;
     }

   bool LoadSequenceExcursions(string &reason)
     {
      reason="";
      m_maximum_adverse_excursion_atr=0.0;
      m_maximum_favorable_excursion_atr=0.0;
      if(m_sequence.sequence_id=="") return true;
      bool found=false;
      if(!m_database.LoadRiskHighWater("mae_"+m_sequence.sequence_id,
                                       m_maximum_adverse_excursion_atr,found,reason)) return false;
      found=false;
      if(!m_database.LoadRiskHighWater("mfe_"+m_sequence.sequence_id,
                                       m_maximum_favorable_excursion_atr,found,reason)) return false;
      return true;
     }

   bool UpdateSequenceExcursions(const double entry_vwap,const double market_price,string &reason)
     {
      reason="";
      const double atr=CurrentAtrPrice();
      if(atr<=0.0 || entry_vwap<=0.0 || market_price<=0.0 || m_sequence.direction==V2_DIR_NONE)
         return true;
      const double signed_excursion=(market_price-entry_vwap)*(double)m_sequence.direction/atr;
      const double adverse=MathMax(0.0,-signed_excursion);
      const double favorable=MathMax(0.0,signed_excursion);
      if(adverse>m_maximum_adverse_excursion_atr)
        {
         m_maximum_adverse_excursion_atr=adverse;
         if(!m_database.StoreRiskHighWater("mae_"+m_sequence.sequence_id,adverse,reason)) return false;
        }
      if(favorable>m_maximum_favorable_excursion_atr)
        {
         m_maximum_favorable_excursion_atr=favorable;
         if(!m_database.StoreRiskHighWater("mfe_"+m_sequence.sequence_id,favorable,reason)) return false;
        }
      return true;
     }

   string FeatureSnapshot(void) const
     {
      return StringFormat("schema=1;spread=%.8f:%d:%I64d;atr=%.8f:%d:%I64d;fast=%.8f:%d:%I64d;slow=%.8f:%d:%I64d;rsi=%.8f:%d:%I64d",
                          m_feature_frame.spread_points.value,(int)m_feature_frame.spread_points.ready,
                          m_feature_frame.spread_points.source_age_msc,
                          m_feature_frame.atr_points.value,(int)m_feature_frame.atr_points.ready,
                          m_feature_frame.atr_points.source_age_msc,
                          m_feature_frame.fast_ema.value,(int)m_feature_frame.fast_ema.ready,
                          m_feature_frame.fast_ema.source_age_msc,
                          m_feature_frame.slow_ema.value,(int)m_feature_frame.slow_ema.ready,
                          m_feature_frame.slow_ema.source_age_msc,
                          m_feature_frame.rsi.value,(int)m_feature_frame.rsi.ready,
                          m_feature_frame.rsi.source_age_msc);
     }

   bool BuildReceipt(const V2DomainEvent &event,
                     const ENUM_V2_RECEIPT_KIND kind,
                     const double event_commission,
                     const double event_swap,
                     V2Receipt &receipt,
                     string &reason) const
     {
      if(!m_receipts.BuildFromEvent(event,kind,
                                    m_identity.DeploymentId(),
                                    m_identity.GenerationId(),
                                    m_identity.MemberId(),
                                    m_manifest.manifest_id,
                                    receipt,reason))
         return false;
      receipt.level_index=event.level_index;
      receipt.kernel_verdict=V2_KERNEL_ALLOW;
      receipt.kernel_reason="DOMAIN_TRANSITION_NO_BROKER_MUTATION";
      receipt.broker_profile_version=V2_BrokerProfileId+"@"+V2_BrokerProfileVersion;
      receipt.feature_schema_version="goat2-feature-frame-v1";
      receipt.feature_readiness_mask=StringFormat("spread:%d|atr:%d|fast:%d|slow:%d|rsi:%d|signal:%d",
                                                   (int)m_feature_frame.spread_points.ready,
                                                   (int)m_feature_frame.atr_points.ready,
                                                   (int)m_feature_frame.fast_ema.ready,
                                                   (int)m_feature_frame.slow_ema.ready,
                                                   (int)m_feature_frame.rsi.ready,
                                                   (int)m_feature_frame.SignalReady());
      receipt.feature_snapshot=FeatureSnapshot();
      receipt.policy_verdict=m_policy_envelope.reason_code;
      receipt.kernel_invariant_snapshot=StringFormat("operational:%d|newRisk:%d|mlpsUsed:%.10f|mlpsBudget:%.10f",
                                                      (int)m_operational_state,(int)m_new_risk_enabled,
                                                      m_sequence.mlps_used,m_sequence.mlps_budget);
      V2IntelligenceState state;
      m_intelligence.Current(state);
      receipt.intelligence_state_id=state.state_id;
      receipt.intelligence_content_hash=state.content_hash;
      receipt.intelligence_thesis=state.thesis_id;
      receipt.intelligence_era=state.era;
      receipt.intelligence_published_at_msc=(long)state.published_at*1000;
      receipt.intelligence_valid_until_msc=(long)state.valid_until*1000;
      receipt.model_bundle_hash=m_onnx_proposal.bundle_hash;
      receipt.onnx_input_ready=m_feature_frame.SignalReady();
      receipt.onnx_outputs=StringFormat("objectiveProbability=%.10f|adverseExcursionAtr=%.10f|executionQuality=%.10f|exposureFactor=%.10f",
                                        m_onnx_proposal.objective_probability,
                                        m_onnx_proposal.adverse_excursion_atr,
                                        m_onnx_proposal.execution_quality,
                                        m_onnx_proposal.exposure_factor);
      receipt.onnx_abstained=m_onnx_proposal.abstained;
      receipt.onnx_out_of_distribution=false;
      receipt.onnx_reason=m_onnx_proposal.reason_code;
      receipt.commission=event_commission;
      receipt.swap=event_swap;
      receipt.level_count=m_sequence.level_count;
      if(kind==V2_RECEIPT_SEQUENCE_END)
        {
         receipt.realized_pl=m_sequence.realized_pl;
         receipt.commission=m_sequence.commission;
         receipt.swap=m_sequence.swap;
         receipt.maximum_adverse_excursion_atr=m_maximum_adverse_excursion_atr;
         receipt.maximum_favorable_excursion_atr=m_maximum_favorable_excursion_atr;
         receipt.duration_seconds=(m_sequence.started_at>0 ? (long)(event.occurred_at-m_sequence.started_at) : 0);
         receipt.exit_attribution=event.reason_code;
        }
      receipt.receipt_id="";
      receipt.payload_hash="";
      receipt.canonical_payload="";
      return m_receipts.Build(receipt,reason);
     }

   bool StoreDecisionReceipt(const ENUM_V2_RECEIPT_KIND kind,
                             const string decision_reason,
                             const ENUM_V2_DIRECTION direction,
                             const ENUM_V2_ACTION_KIND action,
                             const ENUM_V2_RISK_EFFECT risk_effect,
                             const int level_index,
                             const double volume,
                             const double price,
                             string &reason)
     {
      reason="";
      V2DomainEvent event;
      event.Reset();
      event.kind=V2_EVENT_NONE;
      event.sequence_id=m_sequence.sequence_id;
      event.direction=direction;
      event.symbol=_Symbol;
      event.action=action;
      event.risk_effect=risk_effect;
      event.occurred_at=V2UtcNow();
      event.state_version=m_sequence.last_state_version;
      event.level_index=level_index;
      event.volume=volume;
      event.price=price;
      event.reason_code=decision_reason;
      const string material="GOAT2|DECISION|"+IntegerToString((int)kind)+"|"+
                            m_sequence.sequence_id+"|"+IntegerToString(level_index)+"|"+
                            IntegerToString((long)iTime(_Symbol,V2_SignalTimeframe,0))+"|"+decision_reason;
      if(!m_identity.EventId(material,event.event_id))
        { reason="DECISION_RECEIPT_EVENT_ID_FAILED"; return false; }
      V2Receipt receipt;
      if(!BuildReceipt(event,kind,0.0,0.0,receipt,reason))
         return false;
      receipt.counterfactual=(kind==V2_RECEIPT_SHADOW_DECISION);
      receipt.receipt_id="";
      receipt.payload_hash="";
      receipt.canonical_payload="";
      if(!m_receipts.Build(receipt,reason) || !m_database.StoreReceipt(receipt,reason))
         return false;
      V2TelemetryStatus telemetry_status;
      string telemetry_reason="";
      if(!m_telemetry.EnqueueReceipt(receipt,5,false,telemetry_status,telemetry_reason) &&
         telemetry_status.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"DECISION_TELEMETRY_CAPACITY:"+telemetry_reason);
      return true;
     }

   bool PersistOperationalStateReceipt(string &reason)
     {
      reason="";
      if(!m_database.IsOpen() || !m_database.IsWritable())
        { reason="OPERATIONAL_STATE_DATABASE_NOT_WRITABLE"; return false; }
      V2DomainEvent event;
      event.Reset();
      event.kind=V2_EVENT_OPERATIONAL_STATE_CHANGED;
      event.sequence_id=m_sequence.sequence_id;
      event.direction=m_sequence.direction;
      event.symbol=_Symbol;
      event.action=V2_ACTION_CANCEL;
      event.risk_effect=(m_operational_state==V2_OP_NORMAL ? V2_RISK_NEUTRAL : V2_RISK_DECREASE);
      event.occurred_at=V2UtcNow();
      event.state_version=m_sequence.last_state_version;
      event.reason_code="STATE="+IntegerToString((int)m_operational_state)+"|"+m_operational_reason;
      if(!m_identity.EventId("GOAT2|OP_STATE|"+event.reason_code+"|"+
                             IntegerToString((long)GetTickCount64()),event.event_id))
        { reason="OPERATIONAL_STATE_EVENT_ID_FAILED"; return false; }
      V2Receipt receipt;
      if(!BuildReceipt(event,V2_RECEIPT_OPERATIONAL_STATE,0.0,0.0,receipt,reason))
         return false;
      return m_database.StoreReceipt(receipt,reason);
     }

   bool StoreBarDecisionReceipt(const ENUM_V2_RECEIPT_KIND kind,
                                const string decision_reason,
                                const ENUM_V2_DIRECTION direction,
                                const ENUM_V2_ACTION_KIND action,
                                const ENUM_V2_RISK_EFFECT risk_effect,
                                const int level_index,
                                const double volume,
                                const double price,
                                datetime &last_bar,
                                string &reason)
     {
      const datetime current_bar=iTime(_Symbol,V2_SignalTimeframe,0);
      if(current_bar>0 && current_bar==last_bar)
         return true;
      if(!StoreDecisionReceipt(kind,decision_reason,direction,action,risk_effect,
                               level_index,volume,price,reason))
         return false;
      last_bar=current_bar;
      return true;
     }

   bool StoreLevelSkipReceipt(const string skip_reason,
                              const int level_index,
                              const double volume,
                              const double price,
                              string &reason)
     {
      const datetime current_bar=iTime(_Symbol,V2_SignalTimeframe,0);
      if(current_bar>0 && current_bar==m_last_level_skip_bar &&
         level_index==m_last_level_skip_index)
         return true;
      if(!StoreDecisionReceipt(V2_RECEIPT_LEVEL_SKIP,skip_reason,m_sequence.direction,
                               V2_ACTION_ADD,V2_RISK_INCREASE,level_index,
                               volume,price,reason))
         return false;
      m_last_level_skip_bar=current_bar;
      m_last_level_skip_index=level_index;
      return true;
     }

   ENUM_V2_RECEIPT_KIND ReceiptKindForEvent(const V2DomainEvent &event) const
     {
      switch(event.kind)
        {
         case V2_EVENT_SEQUENCE_STARTED:         return V2_RECEIPT_SEQUENCE_START;
         case V2_EVENT_LEVEL_PLANNED:            return V2_RECEIPT_LEVEL_ADD;
         case V2_EVENT_RETRACE_POINTER_MOVED:    return V2_RECEIPT_PARTIAL_CLOSE;
         case V2_EVENT_RESCUE_ARMED:             return V2_RECEIPT_RESCUE_ARM;
         case V2_EVENT_REDUCTION_MANDATED:
         case V2_EVENT_REDUCTION_COMPLETED:      return V2_RECEIPT_PARTIAL_CLOSE;
         case V2_EVENT_SEQUENCE_ENDED:           return V2_RECEIPT_SEQUENCE_END;
         case V2_EVENT_RECOVERY_QUARANTINED:     return V2_RECEIPT_RECOVERY_ACTION;
         case V2_EVENT_OPERATIONAL_STATE_CHANGED:return V2_RECEIPT_OPERATIONAL_STATE;
         case V2_EVENT_FILL_PARTIAL:
         case V2_EVENT_FILL_COMPLETE:
            return(event.risk_effect==V2_RISK_DECREASE ? V2_RECEIPT_PARTIAL_CLOSE : V2_RECEIPT_LEVEL_ADD);
         default:                                return V2_RECEIPT_ORDER_OBSERVATION;
        }
     }

   bool PersistAndApply(V2DomainEvent &event,
                        const bool save_primary_level,
                        V2LevelState &primary_level,
                        const bool save_secondary_level,
                        V2LevelState &secondary_level,
                        const bool update_intent,
                        V2OrderIntent &intent,
                        const double commission,
                        const double swap,
                        string &reason)
     {
      reason="";
      if(event.state_version<=0)
         event.state_version=m_sequence.last_state_version+1;
      if(event.event_id=="")
        {
         const string material=event.sequence_id+"|"+IntegerToString((int)event.kind)+"|"+
                               IntegerToString(event.state_version)+"|"+event.order_intent_id+"|"+
                               V2UlongToText(event.deal_ticket)+"|"+IntegerToString(event.level_index)+"|"+event.reason_code;
         if(!m_identity.EventId(material,event.event_id))
           { reason="DOMAIN_EVENT_ID_GENERATION_FAILED"; return false; }
        }

      V2SequenceState projected=m_sequence;
      if(!m_database.Begin(reason)) return false;
      if(!m_database.AppendDomainEvent(event,reason) || !m_domain.Apply(event,projected,reason))
        {
         m_database.Rollback();
         return false;
        }
      projected.strategy_member_id=m_identity.MemberId();
      projected.max_levels=V2_MaxSequenceTrades;
      if(event.kind==V2_EVENT_FILL_PARTIAL || event.kind==V2_EVENT_FILL_COMPLETE)
        {
         projected.commission+=commission;
         projected.swap+=swap;
        }

      V2Receipt receipt;
      if(!BuildReceipt(event,ReceiptKindForEvent(event),commission,swap,receipt,reason) ||
         !m_database.StoreReceipt(receipt,reason) ||
         (save_primary_level && !m_database.SaveLevelProjection(primary_level,reason)) ||
         (save_secondary_level && !m_database.SaveLevelProjection(secondary_level,reason)) ||
         (update_intent && !m_database.UpdateOrderIntent(intent,reason)) ||
         ((event.kind==V2_EVENT_FILL_PARTIAL || event.kind==V2_EVENT_FILL_COMPLETE) &&
          !m_database.AppendSequenceLedger(event.sequence_id,event.deal_ticket,(long)event.occurred_at*1000,
                                           event.realized_pl,commission,swap,reason)) ||
         !m_database.SaveSequenceProjection(projected,reason) ||
         !m_database.Commit(reason))
        {
         m_database.Rollback();
         return false;
        }
      m_sequence=projected;

      V2TelemetryStatus telemetry_status;
      string telemetry_reason="";
      if(!m_telemetry.EnqueueReceipt(receipt,10,true,telemetry_status,telemetry_reason) && telemetry_status.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"TELEMETRY_CAPACITY:"+telemetry_reason);
      m_hud.MarkDirty();
      return true;
     }

   bool PersistSimpleEvent(V2DomainEvent &event,string &reason)
     {
      V2LevelState first,second;
      first.Reset();
      second.Reset();
      V2OrderIntent intent;
      intent.Reset();
      return PersistAndApply(event,false,first,false,second,false,intent,0.0,0.0,reason);
     }

   bool ApplyPersistedGatewayEvent(const V2GatewayOutcome &outcome,string &reason)
     {
      reason="";
      if(outcome.domain_event.event_id=="")
        {
         reason="GATEWAY_EVENT_NOT_DURABLE";
         return false;
        }
      V2SequenceState projected=m_sequence;
      if(!m_domain.Apply(outcome.domain_event,projected,reason))
         return false;
      projected.strategy_member_id=m_identity.MemberId();
      projected.max_levels=V2_MaxSequenceTrades;
      if(!m_database.SaveSequenceProjection(projected,reason))
         return false;
      m_sequence=projected;
      m_hud.MarkDirty();
      return true;
     }

   bool BuildExecutionPlans(const ENUM_V2_DIRECTION direction,
                            const MqlTick &tick,
                            const double forced_start_volume,
                            string &reason)
     {
      reason="";
      const double point=PointSize();
      const double tick_size=TickSize();
      if(point<=0.0 || tick_size<=0.0 || tick.bid<=0.0 || tick.ask<tick.bid)
        { reason="PLAN_MARKET_SPEC_INVALID"; return false; }

      m_grid_config.Reset();
      m_grid_config.level_count=V2_MaxSequenceTrades;
      m_grid_config.grid_size=V2_GridSize;
      m_grid_config.grid_min=V2_GridMinimum;
      m_grid_config.grid_max=V2_GridMaximum;
      m_grid_config.grid_exponent=V2_GridExponent;
      m_grid_config.grid_factor=V2_GridFactor;
      m_grid_config.pip_size=PipSize();
      m_grid_config.atr_price=CurrentAtrPrice();
      m_grid_config.tick_size=tick_size;
      if(!m_grid_planner.Build(m_grid_config,m_grid_plan))
        { reason=m_grid_plan.reason; return false; }

      m_lot_config.Reset();
      m_lot_config.progression=V2_LotProgression;
      m_lot_config.level_count=V2_MaxSequenceTrades;
      m_lot_config.start_lots=(forced_start_volume>0.0 ? forced_start_volume : V2_StartLots);
      if(forced_start_volume<=0.0 && V2_LotMode==V2_LOTS_EQUITY_SCALED)
         m_lot_config.start_lots=V2_StartLots*AccountInfoDouble(ACCOUNT_EQUITY)/1000.0;
      m_lot_config.lot_exponent=V2_LotExponent;
      m_lot_config.lot_factor=V2_LotFactor;
      m_lot_config.max_trade_multiple=V2_MaxTradeMultiple;
      m_lot_config.max_cumulative_multiple=V2_MaxCumulativeMultiple;
      m_lot_config.peak_position_percent=V2_PeakPositionPercent;
      m_lot_config.volume_min=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      m_lot_config.volume_max=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
      m_lot_config.volume_step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);

      m_risk_market.Reset();
      m_risk_market.symbol=_Symbol;
      m_risk_market.direction=direction;
      m_risk_market.initial_bid=tick.bid;
      m_risk_market.initial_ask=tick.ask;
      m_risk_market.point_size=point;
      m_risk_market.tick_size=tick_size;
      m_risk_market.accrued_sequence_swap=m_sequence.swap;
      const double modeled_stop_distance=ResolveSignedDistance(V2_StopLossSize,CurrentAtrPrice());
      if(modeled_stop_distance>0.0)
         m_cost_profile.terminal_adverse_points=MathMax(V2_TerminalAdversePoints,
                                                        modeled_stop_distance/point);
      else
         m_cost_profile.terminal_adverse_points=V2_TerminalAdversePoints;

      if(forced_start_volume<=0.0 && V2_LotMode==V2_LOTS_RISK_PER_SEQUENCE)
        {
         double solved=0.0;
         const double budget=MathMin(V2_RiskPerSequence,V2_MaxSequenceLoss);
         if(!m_risk_engine.SolveStartLots(budget,m_lot_config,m_grid_plan,m_risk_market,m_cost_profile,
                                          solved,m_risk_result,reason))
            return false;
         m_lot_config.start_lots=solved;
        }
      if(!m_lot_planner.Build(m_lot_config,m_lot_plan))
        { reason=m_lot_plan.reason; return false; }
      if(!m_risk_engine.Evaluate(m_lot_plan,m_grid_plan,m_risk_market,m_cost_profile,m_risk_result))
        { reason=m_risk_result.reason; return false; }
      if(m_risk_result.maximum_loss>V2_MaxSequenceLoss+1e-8)
        { reason="PLANNED_SEQUENCE_LOSS_EXCEEDS_HARD_LIMIT"; return false; }
      m_plans_ready=true;
      return true;
     }

   bool ReplayPersistedEvents(string &reason)
     {
      reason="";
      if(m_sequence.sequence_id=="") return true;
      V2DomainEvent events[];
      if(!m_database.LoadEventsAfter(m_sequence.last_event_number,events,reason))
         return false;
      V2SequenceState projected=m_sequence;
      bool changed=false;
      for(int i=0;i<ArraySize(events);i++)
        {
         if(events[i].sequence_id!=m_sequence.sequence_id) continue;
         if(!m_domain.Apply(events[i],projected,reason))
            return false;
         changed=true;
        }
      if(changed)
        {
         projected.strategy_member_id=m_identity.MemberId();
         if(!m_database.SaveSequenceProjection(projected,reason)) return false;
         m_sequence=projected;
        }
      return true;
     }

   bool RecoveryMatchesBroker(string &reason) const
     {
      reason="";
      V2OwnedPosition positions[];
      double standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,standing,vwap,floating,reason)) return false;
      if(m_sequence.sequence_id=="")
        {
         if(ArraySize(positions)>0 || V2HasPhysicalVolume(standing) || HasOwnedPendingOrders())
           { reason="UNJOURNALED_OWNED_EXPOSURE_OR_ORDER"; return false; }
         return true;
        }
      if(m_sequence.symbol!=_Symbol)
        { reason="RECOVERY_SEQUENCE_SYMBOL_MISMATCH"; return false; }
      if(V2HasPhysicalVolume(standing)!=V2HasPhysicalVolume(m_sequence.standing_volume))
        { reason="RECOVERY_STANDING_VOLUME_PRESENCE_MISMATCH"; return false; }
      if(MathAbs(standing-m_sequence.standing_volume)>V2PhysicalVolumeEpsilon())
        { reason="RECOVERY_STANDING_VOLUME_MISMATCH"; return false; }
      for(int i=0;i<ArraySize(positions);i++)
        {
         if(positions[i].direction!=m_sequence.direction)
           { reason="RECOVERY_DIRECTION_MISMATCH"; return false; }
         const int level=FindLevelByPositionId(positions[i].position_id);
         if(level<0)
           { reason="RECOVERY_POSITION_LINEAGE_MISSING"; return false; }
         if(V2HasPhysicalVolume(m_levels[level].filled_volume)!=V2HasPhysicalVolume(positions[i].volume))
           { reason="RECOVERY_LEVEL_VOLUME_PRESENCE_MISMATCH"; return false; }
         if(MathAbs(m_levels[level].filled_volume-positions[i].volume)>
            V2PhysicalVolumeEpsilon())
           { reason="RECOVERY_LEVEL_VOLUME_MISMATCH"; return false; }
        }
      if(HasOwnedPendingOrders())
        { reason="RECOVERY_PENDING_ORDER_REQUIRES_RECONCILIATION"; return false; }
      return true;
     }

   bool EnterRecoveryQuarantine(const string quarantine_reason)
     {
      m_recovery_verified=false;
      SetOperationalState(V2_OP_RECOVERY_QUARANTINE,quarantine_reason);
      if(m_sequence.sequence_id=="" || m_sequence.status==V2_SEQ_QUARANTINED ||
         m_sequence.status==V2_SEQ_IDLE || m_sequence.status==V2_SEQ_ENDED)
         return false;
      V2DomainEvent event;
      event.Reset();
      event.sequence_id=m_sequence.sequence_id;
      event.kind=V2_EVENT_RECOVERY_QUARANTINED;
      event.action=V2_ACTION_CLOSE;
      event.risk_effect=V2_RISK_DECREASE;
      event.direction=m_sequence.direction;
      event.symbol=m_sequence.symbol;
      event.occurred_at=V2UtcNow();
      event.reason_code=quarantine_reason;
      string reason="";
      if(!PersistSimpleEvent(event,reason))
         Print("GOAT2|RECOVERY|QUARANTINE_EVENT_FAILED|",reason);
      return false;
     }

   bool RecoverState(string &reason)
     {
      reason="";
      V2SequenceState manageable[];
      if(!m_database.LoadManageableSequences(m_identity.MemberId(),manageable,reason))
         return false;
      if(ArraySize(manageable)>1)
        { reason="MULTIPLE_MANAGEABLE_SEQUENCES_REQUIRE_PHASE4"; return false; }
      m_sequence.Reset();
      ArrayResize(m_levels,0);
      if(ArraySize(manageable)==1)
        {
         m_sequence=manageable[0];
         if(!StaticSequenceBindingMatches(reason)) return false;
         if(!ReplayPersistedEvents(reason)) return false;
         if(!m_database.LoadSequenceLevels(m_sequence.sequence_id,m_levels,reason)) return false;
         if(!LoadSequenceExcursions(reason)) return false;
        }
      return true;
     }

   bool InitializeSubsystems(string &reason)
     {
      if(!m_scheduler.Initialize(_Symbol,V2_SignalTimeframe,reason)) return false;
      if(!m_features.Initialize(_Symbol,V2_SignalTimeframe,V2_FastEmaPeriod,V2_SlowEmaPeriod,V2_RsiPeriod,V2_AtrPeriod,reason)) return false;
      if(!m_intelligence.Initialize(V2_StateMode,reason)) return false;
      if(!m_policy.Initialize(V2_StateMode,reason)) return false;
      if(!m_onnx.Initialize(V2_OnnxMode,reason)) return false;
      if(!m_replay.InitializeDisabled(reason)) return false;
      if(!m_hud.Initialize(V2_EnableHud,V2_Mode_Operation,reason)) return false;
      if(!m_overlay.Initialize(V2_EnableOverlay))
        { reason="OVERLAY_INITIALIZATION_FAILED"; return false; }
      return true;
     }

public:
   bool Initialize(const string product_version,const string build_id,string &reason)
     {
      reason="";
      m_product_version=product_version;
      m_build_id=build_id;
      if(!V2ValidateInputs(reason)) return Fail("INPUTS:"+reason);
      if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
        {
         reason="HEDGING_ACCOUNT_REQUIRED";
         return Fail(reason);
        }
      if(!m_identity.Initialize(V2_DeploymentId,V2_PortfolioGenerationId,V2_StrategyMemberId,reason))
         return Fail("IDENTITY:"+reason);

      ConfigureCostProfile();
      m_peak_equity=AccountInfoDouble(ACCOUNT_EQUITY);
      const ENUM_V2_STATE_DB_MODE database_mode=V2ResolveStateDBMode(V2_Bookkeeping);
      V2StateDBConfig database_config;
      V2BuildDefaultStateDBConfig(m_identity,database_mode,database_config);
      if(!m_database.OpenOrRecoverReadOnly(database_config,reason)) return Fail("STATE_DB:"+reason);
      if(m_database.IsReadOnlyRecovery())
        {
         if(!InitializeSubsystems(reason)) return Fail("READ_ONLY_SUBSYSTEM:"+reason);
         m_recovery_verified=false;
         SetOperationalState(V2_OP_HALTED,"DATABASE_READ_ONLY_RECOVERY:"+m_database.StatusReason());
         m_initialized=true;
         RenderHud(true);
         Print("GOAT2|INIT|READ_ONLY_RECOVERY|",m_database.StatusReason(),
               "|path=",MQLInfoString(MQL_PROGRAM_PATH));
         return true;
        }
      if(!InitializeRiskHighWater(reason))
         Print("GOAT2|RISK_HIGH_WATER|DEGRADED|",reason);
      if(!BuildManifest(database_mode,reason)) return Fail("MANIFEST:"+reason);

      V2SafetyLimits limits;
      limits.max_spread_points=V2_MaxSpreadPoints;
      limits.additional_margin_buffer_pct=V2_AdditionalMarginBufferPct;
      limits.max_sequence_loss=V2_MaxSequenceLoss;
      limits.max_symbol_lots=V2_MaxSymbolLots;
      limits.max_portfolio_lots=V2_MaxPortfolioLots;
      limits.equity_floor=V2_EquityFloor;
      limits.max_equity_drawdown_pct=V2_MaxEquityDrawdownPct;
      limits.max_consecutive_broker_errors=V2_MaxConsecutiveBrokerErrors;
      if(!m_kernel.Initialize(limits,reason)) return Fail("SAFETY_KERNEL:"+reason);
      if(!m_telemetry.Initialize(m_database,V2_EnableTelemetry,10000,50*1024*1024,reason))
         return Fail("TELEMETRY:"+reason);
      if(!InitializeSubsystems(reason)) return Fail("SUBSYSTEM:"+reason);

      m_recovery_verified=false;
      string broker_profile_key=V2_BrokerProfileId;
      StringToLower(broker_profile_key);
      m_broker_profile_verified=(MQLInfoInteger(MQL_TESTER) ||
                                 (StringFind(broker_profile_key,"unverified")<0 &&
                                  V2_BrokerProfileVersion!="" &&
                                  V2Sha256Hex(V2CanonicalBrokerProfileInputs())!=""));
      const bool requested_new_risk=(GOAT2_PHASE1_EXECUTION_CERTIFIED==1 &&
                                      V2_RunMode==V2_RUN_TRADE && V2_EnableNewRisk &&
                                      m_risk_high_water_ready && m_broker_profile_verified);
      if(!m_gateway.Initialize(m_identity,m_kernel,m_database,m_receipts,
                               m_manifest.manifest_id,
                               V2_BrokerProfileId+"@"+V2_BrokerProfileVersion,
                               m_peak_equity,
                               false,reason))
         return Fail("BROKER_GATEWAY:"+reason);
      if(!RecoverState(reason))
        {
         EnterRecoveryQuarantine("RECOVERY_LOAD:"+reason);
         m_initialized=true;
         return true;
        }

      // Persisted observations are reconciled before the broker snapshot is
      // accepted. No exposure is adopted from a comment or ticket guess.
      m_gateway.DrainTradeObservations(V2_MANAGER_OBSERVATION_BUDGET);
      if(!ProcessTradeObservations(reason))
        {
         EnterRecoveryQuarantine("RECOVERY_OBSERVATIONS:"+reason);
         m_initialized=true;
         return true;
        }
      if(!ReconcileUnsettledIntents(reason))
        {
         EnterRecoveryQuarantine("RECOVERY_UNSETTLED_INTENTS:"+reason);
         m_initialized=true;
         return true;
        }
      if(!RecoveryMatchesBroker(reason))
        {
         EnterRecoveryQuarantine("RECOVERY_BROKER_MATCH:"+reason);
         m_initialized=true;
         return true;
        }

      V2OwnedPosition recovery_positions[];
      double recovery_standing=0.0,recovery_vwap=0.0,recovery_floating=0.0;
      if(!ScanOwnedPositions(recovery_positions,recovery_standing,recovery_vwap,recovery_floating,reason))
        {
         EnterRecoveryQuarantine("RECOVERY_FLATNESS_SCAN:"+reason);
         m_initialized=true;
         return true;
        }
      const bool recovery_broker_flat=(ArraySize(recovery_positions)==0 &&
                                       !V2HasPhysicalVolume(recovery_standing));
      if(m_sequence.reduction_reason!="" &&
         !V2HasPhysicalVolume(m_sequence.reduction_remaining) &&
         !CompleteReductionMandate(reason))
        {
         EnterRecoveryQuarantine("RECOVERY_REDUCTION_COMPLETION:"+reason);
         m_initialized=true;
         return true;
        }
      if(m_sequence.sequence_id!="" && m_sequence.status!=V2_SEQ_ENDED &&
         recovery_broker_flat && !V2HasPhysicalVolume(m_sequence.standing_volume) &&
         !EndSequence("RECOVERY_BROKER_FLAT",reason))
        {
         EnterRecoveryQuarantine("RECOVERY_SEQUENCE_END:"+reason);
         m_initialized=true;
         return true;
        }

      m_recovery_verified=true;
      if(m_sequence.sequence_id!="" && m_sequence.status==V2_SEQ_ACTIVE)
        {
         MqlTick tick;
         if(SymbolInfoTick(_Symbol,tick))
           {
             m_features.Update(tick,m_sequence.standing_volume,0.0,m_sequence.mlps_used,m_sequence.mlps_budget,m_feature_frame);
             if(!BuildExecutionPlans(m_sequence.direction,tick,m_sequence.start_volume,reason))
                Print("GOAT2|RECOVERY|PLAN_DEFERRED|",reason);
            else if(CurrentExecutionPlanHash()!=m_sequence.execution_plan_hash)
              {
               EnterRecoveryQuarantine("RECOVERY_EXECUTION_PLAN_HASH_MISMATCH");
               reason="RECOVERY_EXECUTION_PLAN_HASH_MISMATCH";
              }
            }
        }
      V2TelemetryStatus startup_telemetry;
      string telemetry_reason="";
      const bool telemetry_ready=m_telemetry.RefreshStatus(startup_telemetry,telemetry_reason);
      if(!telemetry_ready || startup_telemetry.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"TELEMETRY_STARTUP_GATE:"+telemetry_reason+startup_telemetry.reason);
      else if(V2_RunMode==V2_RUN_DISABLED)
         SetOperationalState(V2_OP_HALTED,"RUN_DISABLED_NO_BROKER_MUTATIONS");
      else if(GOAT2_PHASE1_EXECUTION_CERTIFIED!=1)
         SetOperationalState(V2_OP_MANAGE_ONLY,"PHASE1_EXECUTION_NOT_CERTIFIED");
      else if(V2_RunMode!=V2_RUN_TRADE || !V2_EnableNewRisk)
         SetOperationalState(V2_OP_MANAGE_ONLY,"NEW_RISK_NOT_EXPLICITLY_ENABLED");
      else if(!m_risk_high_water_ready)
         SetOperationalState(V2_OP_MANAGE_ONLY,"RISK_HIGH_WATER_NOT_DURABLE");
      else if(!m_broker_profile_verified)
         SetOperationalState(V2_OP_MANAGE_ONLY,"BROKER_PROFILE_UNVERIFIED");
      else if(!requested_new_risk)
         SetOperationalState(V2_OP_MANAGE_ONLY,"NEW_RISK_PREREQUISITE_FAILED");
      else
         SetOperationalState(V2_OP_NORMAL,"RECOVERY_VERIFIED");
      m_initialized=true;
      string state_receipt_reason="";
      if(!PersistOperationalStateReceipt(state_receipt_reason))
         Print("GOAT2|STATE|INITIAL_RECEIPT_FAILED|",state_receipt_reason);
      RenderHud(true);
      Print("GOAT2|INIT|OK|version=",m_product_version,
            "|build=",m_build_id,
            "|manifest=",m_manifest.manifest_id,
            "|magic=",m_identity.MagicTransport(),
            "|path=",MQLInfoString(MQL_PROGRAM_PATH));
      return true;
     }

private:
   bool FindPersistedDealEvent(const ulong deal_ticket,V2DomainEvent &matched,bool &found,string &reason)
     {
      return m_database.FindFillEventByDeal(deal_ticket,matched,found,reason);
     }

   double ExecutedVolumeForIntent(const V2OrderIntent &intent,const ENUM_DEAL_ENTRY expected_entry) const
     {
      const datetime from=V2UtcTimeToServer(intent.created_at>60 ? intent.created_at-60 : 0);
      if(!HistorySelect(from,TimeCurrent()+60)) return 0.0;
      double total=0.0;
      for(int i=0;i<HistoryDealsTotal();i++)
        {
         ulong deal=HistoryDealGetTicket(i);
         if(deal==0) continue;
         if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=m_identity.Magic()) continue;
         if(HistoryDealGetString(deal,DEAL_SYMBOL)!=intent.symbol) continue;
         if(intent.order_ticket!=0 && (ulong)HistoryDealGetInteger(deal,DEAL_ORDER)!=intent.order_ticket) continue;
         const ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
         if(entry!=expected_entry) continue;
         total+=HistoryDealGetDouble(deal,DEAL_VOLUME);
        }
      return total;
     }

   bool EndSequence(const string attribution,string &reason)
     {
      reason="";
      if(m_sequence.sequence_id=="" || m_sequence.status==V2_SEQ_ENDED) return true;
      V2OwnedPosition positions[];
      double broker_standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,broker_standing,vwap,floating,reason))
         return false;
      if(ArraySize(positions)>0 || V2HasPhysicalVolume(broker_standing) ||
         V2HasPhysicalVolume(m_sequence.standing_volume))
        { reason="END_SEQUENCE_NOT_FLAT"; return false; }
      V2DomainEvent event;
      event.Reset();
      event.sequence_id=m_sequence.sequence_id;
      event.kind=V2_EVENT_SEQUENCE_ENDED;
      event.action=V2_ACTION_CLOSE;
      event.risk_effect=V2_RISK_DECREASE;
      event.direction=m_sequence.direction;
      event.symbol=m_sequence.symbol;
      event.occurred_at=V2UtcNow();
      event.reason_code=attribution;
      if(!PersistSimpleEvent(event,reason)) return false;
      m_pending.Reset();
      m_plans_ready=false;
      return true;
     }

   double NextRetracePrice(void) const
     {
      if(m_sequence.sequence_id=="" || m_sequence.status==V2_SEQ_IDLE ||
         m_sequence.status==V2_SEQ_ENDED) return 0.0;
      double prices[];
      ArrayResize(prices,ArraySize(m_levels));
      for(int i=0;i<ArraySize(m_levels);i++) prices[i]=m_levels[i].planned_price;
      return m_retrace_planner.FindNext(m_sequence.direction,m_sequence.retrace_price,
                                        prices,PointSize()*2.0);
     }

   bool AdvanceRetracePointer(string &reason)
     {
      reason="";
      if(m_sequence.sequence_id=="" || m_sequence.status!=V2_SEQ_ACTIVE) return true;
      const double next=NextRetracePrice();
      V2DomainEvent event;
      event.Reset();
      event.sequence_id=m_sequence.sequence_id;
      event.kind=V2_EVENT_RETRACE_POINTER_MOVED;
      event.action=V2_ACTION_PARTIAL_CLOSE;
      event.risk_effect=V2_RISK_DECREASE;
      event.direction=m_sequence.direction;
      event.symbol=m_sequence.symbol;
      event.occurred_at=V2UtcNow();
      event.price=next;
      event.reason_code=(next>0.0 ? "RETRACE_POINTER_ADVANCED" : "RETRACE_CHAIN_EXHAUSTED");
      return PersistSimpleEvent(event,reason);
     }

   bool CompleteReductionMandate(string &reason)
     {
      reason="";
      if(m_sequence.reduction_reason=="") return true;
      if(V2HasPhysicalVolume(m_sequence.reduction_remaining))
        { reason="REDUCTION_COMPLETION_VOLUME_REMAINS"; return false; }
      const bool retrace_pending=m_sequence.retrace_advance_pending;
      V2DomainEvent completed;
      completed.Reset();
      completed.sequence_id=m_sequence.sequence_id;
      completed.kind=V2_EVENT_REDUCTION_COMPLETED;
      completed.action=(!V2HasPhysicalVolume(m_sequence.standing_volume) ?
                        V2_ACTION_CLOSE : V2_ACTION_PARTIAL_CLOSE);
      completed.risk_effect=V2_RISK_DECREASE;
      completed.direction=m_sequence.direction;
      completed.symbol=m_sequence.symbol;
      completed.occurred_at=V2UtcNow();
      completed.level_index=m_sequence.reduction_semantic_level;
      completed.retrace_advance=retrace_pending;
      completed.price=(retrace_pending ? NextRetracePrice() : 0.0);
      completed.reason_code=m_sequence.reduction_reason;
      return PersistSimpleEvent(completed,reason);
     }

   bool ReconcileDealObservation(const V2TradeObservation &observation,string &reason)
     {
      reason="";
      if(observation.deal_ticket==0)
        { reason="DEAL_OBSERVATION_TICKET_ZERO"; return false; }
      if(!HistoryDealSelect(observation.deal_ticket))
        { reason="DEAL_HISTORY_NOT_AVAILABLE"; return false; }
      const ulong magic=(ulong)HistoryDealGetInteger(observation.deal_ticket,DEAL_MAGIC);
      const string symbol=HistoryDealGetString(observation.deal_ticket,DEAL_SYMBOL);
      if(symbol!=_Symbol)
        {
         if(magic!=m_identity.Magic()) return true;
         reason="OWNED_DEAL_OUTSIDE_PHASE1_SYMBOL";
         return false;
        }
      const ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(observation.deal_ticket,DEAL_ENTRY);
      const ENUM_DEAL_REASON deal_reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(observation.deal_ticket,DEAL_REASON);
      const double volume=HistoryDealGetDouble(observation.deal_ticket,DEAL_VOLUME);
      const double price=HistoryDealGetDouble(observation.deal_ticket,DEAL_PRICE);
      const double profit=HistoryDealGetDouble(observation.deal_ticket,DEAL_PROFIT);
      const double commission=HistoryDealGetDouble(observation.deal_ticket,DEAL_COMMISSION);
      const double swap=HistoryDealGetDouble(observation.deal_ticket,DEAL_SWAP);
      const ulong position_id=(ulong)HistoryDealGetInteger(observation.deal_ticket,DEAL_POSITION_ID);
      const ulong order_ticket=(ulong)HistoryDealGetInteger(observation.deal_ticket,DEAL_ORDER);
      if(volume<=0.0 || price<=0.0 || position_id==0)
        { reason="DEAL_PAYLOAD_INVALID"; return false; }
      const int position_level=FindLevelByPositionId(position_id);
      const bool server_reduction=(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY) &&
                                  (deal_reason==DEAL_REASON_SL || deal_reason==DEAL_REASON_TP ||
                                   deal_reason==DEAL_REASON_SO);
      if(magic!=m_identity.Magic())
        {
         if(position_level<0) return true;
         if(!server_reduction)
           { reason="JOURNALED_POSITION_EXITED_BY_UNAUTHORIZED_ACTOR"; return false; }
        }

      V2OrderIntent intent;
      bool intent_found=false;
      if(!m_database.FindOrderIntentByCorrelation(observation.request_id,
                                                   observation.order_ticket,
                                                   observation.deal_ticket,
                                                   intent,intent_found,reason))
         return false;
      if(!intent_found)
        {
         if(!server_reduction || position_level<0 || m_sequence.sequence_id=="")
           { reason="DEAL_ORDER_INTENT_NOT_FOUND"; return false; }

         intent.Reset();
         if(!m_identity.SystemExitIntentId(m_sequence.sequence_id,observation.deal_ticket,
                                           intent.order_intent_id))
           { reason="SYSTEM_EXIT_INTENT_ID_FAILED"; return false; }
         const double level_volume=m_levels[position_level].filled_volume;
         intent.sequence_id=m_sequence.sequence_id;
         intent.action=(V2ExecutedVolumeSatisfies(volume,level_volume) ?
                        V2_ACTION_CLOSE : V2_ACTION_PARTIAL_CLOSE);
         intent.risk_effect=V2_RISK_DECREASE;
         if(!ApplyIntentTransition(intent,V2_INTENT_PERSISTED,reason))
           { reason="SYSTEM_EXIT_INTENT_TRANSITION_FAILED:"+reason; return false; }
         intent.direction=m_sequence.direction;
         intent.symbol=_Symbol;
         intent.magic=m_identity.Magic();
         intent.level_index=position_level;
         intent.requested_volume=volume;
         intent.requested_price=price;
         intent.request_id=observation.request_id;
         intent.order_ticket=order_ticket;
         intent.deal_ticket=observation.deal_ticket;
         intent.position_id=position_id;
         intent.created_at=(datetime)(V2ServerTimeToUtcMsc((long)HistoryDealGetInteger(observation.deal_ticket,DEAL_TIME_MSC))/1000);
         intent.reason_code=(deal_reason==DEAL_REASON_SL ? "SYSTEM_EXIT_STOP_LOSS" :
                             (deal_reason==DEAL_REASON_TP ? "SYSTEM_EXIT_TAKE_PROFIT" :
                              "SYSTEM_EXIT_STOP_OUT"));

         V2Receipt recovery_receipt;
         recovery_receipt.Reset();
         recovery_receipt.kind=V2_RECEIPT_RECOVERY_ACTION;
         recovery_receipt.occurred_at_msc=V2ServerTimeToUtcMsc((long)HistoryDealGetInteger(observation.deal_ticket,DEAL_TIME_MSC));
         recovery_receipt.deployment_id=m_identity.DeploymentId();
         recovery_receipt.portfolio_generation_id=m_identity.GenerationId();
         recovery_receipt.strategy_member_id=m_identity.MemberId();
         recovery_receipt.sequence_id=intent.sequence_id;
         recovery_receipt.order_intent_id=intent.order_intent_id;
         recovery_receipt.experiment_manifest_id=m_manifest.manifest_id;
         recovery_receipt.symbol=intent.symbol;
         recovery_receipt.direction=intent.direction;
         recovery_receipt.level_index=intent.level_index;
         recovery_receipt.action=intent.action;
         recovery_receipt.risk_effect=V2_RISK_DECREASE;
         recovery_receipt.kernel_verdict=V2_KERNEL_ALLOW_REDUCE_ONLY;
         recovery_receipt.policy_reason=intent.reason_code;
         recovery_receipt.kernel_reason="PROVEN_SERVER_REDUCTION_FROM_JOURNALED_POSITION_LINEAGE";
         recovery_receipt.broker_profile_version=V2_BrokerProfileId+"@"+V2_BrokerProfileVersion;
         recovery_receipt.request_id=intent.request_id;
         recovery_receipt.order_ticket=intent.order_ticket;
         recovery_receipt.deal_ticket=intent.deal_ticket;
         recovery_receipt.position_id=intent.position_id;
         recovery_receipt.requested_volume=intent.requested_volume;
         recovery_receipt.requested_price=intent.requested_price;
         recovery_receipt.filled_volume=volume;
         recovery_receipt.filled_price=price;
         recovery_receipt.exit_attribution=intent.reason_code;
         bool newly_inserted=false;
         if(!m_database.PersistOrderIntentAndReceipt(intent,recovery_receipt,newly_inserted,reason))
            return false;
         if(!newly_inserted)
           { reason="SYSTEM_EXIT_INTENT_ID_COLLISION"; return false; }
         intent_found=true;
        }
      if(m_sequence.sequence_id=="" || intent.sequence_id!=m_sequence.sequence_id)
        { reason="DEAL_SEQUENCE_NOT_CURRENT"; return false; }

      V2DomainEvent existing;
      bool event_found=false;
      if(!FindPersistedDealEvent(observation.deal_ticket,existing,event_found,reason)) return false;
      if(event_found)
        {
         if(existing.sequence_id!=m_sequence.sequence_id)
           { reason="PERSISTED_DEAL_SEQUENCE_MISMATCH"; return false; }
         if(existing.state_version==m_sequence.last_state_version+1)
           {
            V2SequenceState projected=m_sequence;
            if(!m_domain.Apply(existing,projected,reason) || !m_database.SaveSequenceProjection(projected,reason))
               return false;
            m_sequence=projected;
           }
         else if(existing.state_version>m_sequence.last_state_version)
            { reason="PERSISTED_DEAL_STATE_VERSION_GAP"; return false; }
         intent.deal_ticket=observation.deal_ticket;
         if(!ApplyObservedIntentTransition(intent,
                                           (existing.kind==V2_EVENT_FILL_COMPLETE ? V2_INTENT_FILLED : V2_INTENT_PARTIAL),
                                           reason))
           { reason="PERSISTED_DEAL_INTENT_TRANSITION_FAILED:"+reason; return false; }
         intent.reason_code="DEAL_EVENT_ALREADY_RECONCILED";
         return m_database.UpdateOrderIntent(intent,reason);
        }

      ENUM_V2_RISK_EFFECT risk_effect=V2_RISK_UNKNOWN;
      if(entry==DEAL_ENTRY_IN) risk_effect=V2_RISK_INCREASE;
      else if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY) risk_effect=V2_RISK_DECREASE;
      else
        { reason="HEDGING_DEAL_ENTRY_UNSUPPORTED"; return false; }
      if((risk_effect==V2_RISK_INCREASE && !V2ActionIncreasesRisk(intent.action)) ||
         (risk_effect==V2_RISK_DECREASE && !V2ActionReducesRisk(intent.action)))
        { reason="DEAL_ACTION_RISK_EFFECT_MISMATCH"; return false; }

      if(intent.order_ticket==0) intent.order_ticket=order_ticket;
      if(intent.order_ticket==0)
        { reason="DEAL_ORDER_TICKET_REQUIRED_FOR_FILL_AGGREGATION"; return false; }
      const double executed=(StringFind(intent.reason_code,"SYSTEM_EXIT_")==0 ?
                             volume : ExecutedVolumeForIntent(intent,entry));
      const bool complete=V2ExecutedVolumeSatisfies(executed,intent.requested_volume);
      if(!ApplyObservedIntentTransition(intent,(complete ? V2_INTENT_FILLED : V2_INTENT_PARTIAL),reason))
        { reason="DEAL_FILL_INTENT_TRANSITION_FAILED:"+reason; return false; }
      intent.risk_effect=risk_effect;
      intent.deal_ticket=observation.deal_ticket;
      intent.order_ticket=order_ticket;
      intent.position_id=position_id;
      intent.reason_code=(complete ? "DEAL_FILL_COMPLETE" : "DEAL_FILL_PARTIAL");

      V2LevelState primary,secondary;
      primary.Reset();
      secondary.Reset();
      bool save_primary=false,save_secondary=false;
      int primary_index=-1,secondary_index=-1;
      if(risk_effect==V2_RISK_INCREASE)
        {
         primary_index=intent.level_index;
         if(primary_index<0 || primary_index>=ArraySize(m_levels))
           { reason="FILL_LEVEL_PROJECTION_MISSING"; return false; }
         primary=m_levels[primary_index];
         const double next_volume=primary.filled_volume+volume;
         primary.average_fill_price=(next_volume>0.0 ?
                                    (primary.average_fill_price*primary.filled_volume+price*volume)/next_volume : 0.0);
         primary.filled_volume=next_volume;
         primary.position_id=position_id;
         primary.closed=false;
         save_primary=true;
        }
      else
        {
         primary_index=FindLevelByPositionId(position_id);
         if(primary_index<0)
           { reason="CLOSE_POSITION_LEVEL_LINEAGE_MISSING"; return false; }
         primary=m_levels[primary_index];
         primary.filled_volume=MathMax(0.0,primary.filled_volume-volume);
         if(!V2HasPhysicalVolume(primary.filled_volume))
           {
            primary.filled_volume=0.0;
            primary.closed=true;
           }
         save_primary=true;
         if(intent.level_index!=primary_index && intent.level_index>=0 && intent.level_index<ArraySize(m_levels))
           {
            secondary_index=intent.level_index;
            secondary=m_levels[secondary_index];
            secondary.closed=complete;
            save_secondary=true;
           }
        }

      V2DomainEvent event;
      event.Reset();
      event.sequence_id=intent.sequence_id;
      event.order_intent_id=intent.order_intent_id;
      event.kind=(complete ? V2_EVENT_FILL_COMPLETE : V2_EVENT_FILL_PARTIAL);
      event.action=intent.action;
      event.risk_effect=risk_effect;
      event.direction=intent.direction;
      event.symbol=intent.symbol;
      event.occurred_at=(datetime)(V2ServerTimeToUtcMsc((long)HistoryDealGetInteger(observation.deal_ticket,DEAL_TIME_MSC))/1000);
      event.level_index=intent.level_index;
      event.request_id=observation.request_id;
      event.order_ticket=order_ticket;
      event.deal_ticket=observation.deal_ticket;
      event.position_id=position_id;
      event.volume=(risk_effect==V2_RISK_DECREASE ?
                    MathMin(volume,m_sequence.standing_volume) : volume);
      event.price=price;
      event.realized_pl=profit;
      event.reason_code=intent.reason_code;
      if(!m_identity.EventId("GOAT2|DEAL|"+V2UlongToText(observation.deal_ticket),event.event_id))
        { reason="DEAL_EVENT_ID_GENERATION_FAILED"; return false; }
      if(!PersistAndApply(event,save_primary,primary,save_secondary,secondary,true,intent,commission,swap,reason))
         return false;
      if(save_primary) m_levels[primary_index]=primary;
      if(save_secondary) m_levels[secondary_index]=secondary;

      if(m_pending.active && m_pending.order_intent_id==intent.order_intent_id)
        {
         m_pending.observed_volume+=volume;
         if(complete) m_pending.Reset();
        }
      if(m_sequence.mlps_budget>0.0)
         m_sequence.mlps_used=MathMax(0.0,-CurrentSequenceProfit());

      if(complete && risk_effect==V2_RISK_INCREASE && intent.level_index>0 &&
         (V2_LotProgression==V2_LOT_CUMULATIVE_PARTIAL || V2_LotProgression==V2_LOT_PEAK_SMART))
        {
         const int previous=intent.level_index-1;
         if(previous>=0 && previous<ArraySize(m_levels))
           {
            V2DomainEvent retrace;
            retrace.Reset();
            retrace.sequence_id=m_sequence.sequence_id;
            retrace.kind=V2_EVENT_RETRACE_POINTER_MOVED;
            retrace.action=V2_ACTION_PARTIAL_CLOSE;
            retrace.risk_effect=V2_RISK_DECREASE;
            retrace.direction=m_sequence.direction;
            retrace.symbol=m_sequence.symbol;
            retrace.occurred_at=V2UtcNow();
            retrace.level_index=previous;
            retrace.price=m_levels[previous].planned_price;
            retrace.reason_code="RETRACE_POINTER_ARMED";
            if(!PersistSimpleEvent(retrace,reason)) return false;
           }
        }

      V2OwnedPosition post_deal_positions[];
      double post_deal_standing=0.0,post_deal_vwap=0.0,post_deal_floating=0.0;
      if(!ScanOwnedPositions(post_deal_positions,post_deal_standing,
                             post_deal_vwap,post_deal_floating,reason))
         return false;
      const bool broker_flat_after_deal=(ArraySize(post_deal_positions)==0 &&
                                         !V2HasPhysicalVolume(post_deal_standing));
      if(broker_flat_after_deal && !V2HasPhysicalVolume(m_sequence.standing_volume))
        {
         const string flat_reason=(m_sequence.reduction_reason=="" ? "BROKER_FLAT" : m_sequence.reduction_reason);
         if(m_sequence.reduction_reason!="" && !CompleteReductionMandate(reason))
            return false;
         if(!EndSequence(flat_reason,reason))
            return false;
        }
      else if(m_sequence.reduction_reason!="" &&
              !V2HasPhysicalVolume(m_sequence.reduction_remaining) &&
              !CompleteReductionMandate(reason))
         return false;
      return true;
     }

   bool ProcessTradeObservations(string &reason)
     {
      reason="";
      bool terminal_order_observed=false;
      V2TradeObservation observations[];
      if(!m_database.LoadUnprocessedTradeObservations(V2_MANAGER_OBSERVATION_BUDGET,observations,reason))
         return false;
      for(int i=0;i<ArraySize(observations);i++)
        {
         if(observations[i].transaction_type==TRADE_TRANSACTION_DEAL_ADD && observations[i].deal_ticket!=0)
           {
            if(!ReconcileDealObservation(observations[i],reason)) return false;
           }
         else if(observations[i].transaction_type==TRADE_TRANSACTION_ORDER_DELETE ||
                 observations[i].transaction_type==TRADE_TRANSACTION_HISTORY_ADD)
            terminal_order_observed=true;
         if(!m_database.MarkTradeObservationProcessed(observations[i].observation_id,reason))
            return false;
        }
      if(terminal_order_observed && !ReconcileUnsettledIntents(reason))
         return false;
      return true;
     }

   bool PositionProtectionMatchesIntent(const V2OrderIntent &intent) const
     {
      if(intent.position_id==0) return false;
      const double epsilon=TickSize()*0.5;
      for(int i=0;i<PositionsTotal();i++)
        {
         const ulong ticket=PositionGetTicket(i);
         if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
         if((ulong)PositionGetInteger(POSITION_MAGIC)!=m_identity.Magic()) continue;
         if((ulong)PositionGetInteger(POSITION_IDENTIFIER)!=intent.position_id) continue;
         return(MathAbs(PositionGetDouble(POSITION_SL)-intent.stop_loss)<=epsilon &&
                MathAbs(PositionGetDouble(POSITION_TP)-intent.take_profit)<=epsilon);
        }
      return false;
     }

   bool ReconcileUnsettledIntents(string &reason)
     {
      reason="";
      V2OrderIntent intents[];
      if(!m_database.LoadUnsettledOrderIntents(1000,intents,reason)) return false;
      for(int i=0;i<ArraySize(intents);i++)
        {
         V2OrderIntent intent=intents[i];
         if(intent.magic!=m_identity.Magic())
           { reason="UNSETTLED_INTENT_MAGIC_MISMATCH"; return false; }
         if(m_sequence.sequence_id=="" || intent.sequence_id!=m_sequence.sequence_id)
            { reason="UNSETTLED_INTENT_SEQUENCE_NOT_MANAGEABLE"; return false; }

         const string correlation_token="GOAT2:"+StringSubstr(intent.order_intent_id,0,24);
         const bool broker_ids_missing=(intent.request_id==0 && intent.order_ticket==0 && intent.deal_ticket==0);
         if(broker_ids_missing)
           {
            for(int order_index=0;order_index<OrdersTotal();order_index++)
              {
               const ulong active_order=OrderGetTicket(order_index);
               if(active_order==0 || !OrderSelect(active_order)) continue;
                if((ulong)OrderGetInteger(ORDER_MAGIC)!=m_identity.Magic() ||
                   OrderGetString(ORDER_SYMBOL)!=intent.symbol ||
                   OrderGetString(ORDER_COMMENT)!=correlation_token) continue;
                intent.order_ticket=active_order;
               if(!ApplyObservedIntentTransition(intent,V2_INTENT_RECONCILE_REQUIRED,reason))
                 { reason="ACTIVE_ORDER_INTENT_TRANSITION_FAILED:"+reason; return false; }
               intent.reason_code="RECOVERY_CORRELATED_ACTIVE_ORDER_BY_TOKEN";
               if(!m_database.UpdateOrderIntent(intent,reason)) return false;
               break;
              }
           }

         bool found_deal=false;
         if(HistorySelect(V2UtcTimeToServer(intent.created_at>60 ? intent.created_at-60 : 0),TimeCurrent()+60))
           {
            ulong deal_tickets[];
            const int history_total=HistoryDealsTotal();
            if(ArrayResize(deal_tickets,history_total)!=history_total)
              { reason="HISTORY_DEAL_SNAPSHOT_ALLOCATION_FAILED"; return false; }
            int deal_count=0;
            for(int d=0;d<history_total;d++)
              {
               const ulong ticket=HistoryDealGetTicket(d);
               if(ticket!=0)
                  deal_tickets[deal_count++]=ticket;
              }
            ArrayResize(deal_tickets,deal_count);
            for(int d=0;d<deal_count;d++)
              {
               const ulong deal=deal_tickets[d];
                if(deal==0 || (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=m_identity.Magic()) continue;
                if(HistoryDealGetString(deal,DEAL_SYMBOL)!=intent.symbol) continue;
                const ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER);
                bool token_correlated=false;
                if(intent.deal_ticket!=0 && deal!=intent.deal_ticket &&
                   (intent.order_ticket==0 || order!=intent.order_ticket)) continue;
                if(intent.deal_ticket==0 && intent.order_ticket!=0 && order!=intent.order_ticket) continue;
                if(intent.deal_ticket==0 && intent.order_ticket==0)
                  {
                   const string deal_comment=HistoryDealGetString(deal,DEAL_COMMENT);
                   const string order_comment=(order!=0 ? HistoryOrderGetString(order,ORDER_COMMENT) : "");
                   if(deal_comment!=correlation_token && order_comment!=correlation_token) continue;
                   token_correlated=true;
                  }
                if(token_correlated)
                  {
                   intent.order_ticket=order;
                   intent.deal_ticket=deal;
                   if(!ApplyObservedIntentTransition(intent,V2_INTENT_RECONCILE_REQUIRED,reason))
                     { reason="CORRELATED_DEAL_INTENT_TRANSITION_FAILED:"+reason; return false; }
                   intent.reason_code="RECOVERY_CORRELATED_DEAL_BY_TOKEN";
                   if(!m_database.UpdateOrderIntent(intent,reason)) return false;
                  }
                V2TradeObservation observation;
               observation.Reset();
               observation.captured_at_msc=V2ServerTimeToUtcMsc(
                                             (long)HistoryDealGetInteger(deal,DEAL_TIME_MSC));
               observation.transaction_type=TRADE_TRANSACTION_DEAL_ADD;
               observation.request_id=intent.request_id;
               observation.order_ticket=order;
               observation.deal_ticket=deal;
               observation.position_id=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
               observation.symbol=intent.symbol;
               observation.volume=HistoryDealGetDouble(deal,DEAL_VOLUME);
               observation.price=HistoryDealGetDouble(deal,DEAL_PRICE);
               if(!ReconcileDealObservation(observation,reason)) return false;
               found_deal=true;
              }
           }
         if(found_deal)
           {
            const ENUM_DEAL_ENTRY expected_entry=(V2ActionIncreasesRisk(intent.action) ?
                                                   DEAL_ENTRY_IN : DEAL_ENTRY_OUT);
            const double executed=ExecutedVolumeForIntent(intent,expected_entry);
            if(V2ExecutedVolumeSatisfies(executed,intent.requested_volume))
               continue;
            const bool active_order=(intent.order_ticket!=0 && OrderSelect(intent.order_ticket));
            bool terminal_remainder=false;
            if(!active_order && intent.order_ticket!=0 && HistoryOrderSelect(intent.order_ticket))
              {
               const ENUM_ORDER_STATE order_state=(ENUM_ORDER_STATE)HistoryOrderGetInteger(intent.order_ticket,ORDER_STATE);
               terminal_remainder=(order_state==ORDER_STATE_CANCELED ||
                                   order_state==ORDER_STATE_REJECTED ||
                                   order_state==ORDER_STATE_EXPIRED);
              }
            if(terminal_remainder)
              {
               if(!ApplyObservedIntentTransition(intent,V2_INTENT_CANCELLED,reason))
                 { reason="PARTIAL_REMAINDER_INTENT_TRANSITION_FAILED:"+reason; return false; }
               intent.reason_code="PARTIAL_FILL_REMAINDER_TERMINATED";
               if(!m_database.UpdateOrderIntent(intent,reason)) return false;
               if(m_pending.active && m_pending.order_intent_id==intent.order_intent_id)
                  m_pending.Reset();
               if(V2ActionIncreasesRisk(intent.action))
                 {
                  reason="POSITIVE_RISK_PARTIAL_FILL_REQUIRES_CERTIFIED_REPLAN";
                  EnterRecoveryQuarantine(reason);
                  return false;
                 }
               continue;
              }
            if(active_order) continue;
           }

          // A committed pre-intent with no broker identifiers straddles the
          // OrderSend crash window.  Absence of identifiers is not proof that
          // it was never submitted, so recovery must quarantine it rather than
          // manufacture a cancellation.
         if(intent.action==V2_ACTION_MODIFY && PositionProtectionMatchesIntent(intent))
           {
            if(!ApplyObservedIntentTransition(intent,V2_INTENT_FILLED,reason))
              { reason="PROTECTION_INTENT_TRANSITION_FAILED:"+reason; return false; }
            intent.reason_code="RECOVERY_PROTECTIVE_MODIFICATION_CONFIRMED";
            if(!m_database.UpdateOrderIntent(intent,reason)) return false;
            continue;
           }
         if(intent.action==V2_ACTION_CANCEL)
           {
            bool broker_order_present=false;
            if(intent.order_ticket!=0 && OrderSelect(intent.order_ticket)) broker_order_present=true;
            if(!broker_order_present)
              {
               if(!ApplyObservedIntentTransition(intent,V2_INTENT_CANCELLED,reason))
                 { reason="CANCEL_INTENT_TRANSITION_FAILED:"+reason; return false; }
               intent.reason_code="RECOVERY_CANCELLATION_CONFIRMED";
               if(!m_database.UpdateOrderIntent(intent,reason)) return false;
               continue;
              }
           }
         if(intent.order_ticket!=0 && !OrderSelect(intent.order_ticket) &&
            HistoryOrderSelect(intent.order_ticket))
           {
            const ENUM_ORDER_STATE order_state=(ENUM_ORDER_STATE)HistoryOrderGetInteger(intent.order_ticket,ORDER_STATE);
            if(order_state==ORDER_STATE_CANCELED || order_state==ORDER_STATE_EXPIRED ||
               order_state==ORDER_STATE_REJECTED)
              {
               if(!ApplyObservedIntentTransition(intent,
                                                 (order_state==ORDER_STATE_REJECTED ? V2_INTENT_REJECTED : V2_INTENT_CANCELLED),
                                                 reason))
                 { reason="TERMINAL_ORDER_INTENT_TRANSITION_FAILED:"+reason; return false; }
               intent.reason_code="BROKER_ORDER_TERMINAL_WITHOUT_FILL";
               if(!m_database.UpdateOrderIntent(intent,reason)) return false;
               if(m_pending.active && m_pending.order_intent_id==intent.order_intent_id)
                  m_pending.Reset();
               if(V2ActionIncreasesRisk(intent.action) && intent.level_index==0 &&
                  !V2HasPhysicalVolume(m_sequence.standing_volume))
                 {
                  if(!EndSequence("ENTRY_REJECTED_ASYNC",reason))
                     return false;
                 }
               continue;
              }
           }
         reason="UNSETTLED_INTENT_BROKER_OUTCOME_AMBIGUOUS:"+intent.order_intent_id;
         return false;
        }
      return true;
     }

   bool PersistPlannedLevel(const int level_index,
                            const double planned_price,
                            const double requested_volume,
                            const bool virtual_level,
                            const ENUM_V2_ACTION_KIND action,
                            const ENUM_V2_RISK_EFFECT risk_effect,
                            const string reason_code,
                            string &reason)
     {
      reason="";
      if(level_index<0 || level_index!=ArraySize(m_levels) || planned_price<=0.0 || requested_volume<=0.0)
        { reason="LEVEL_PLAN_SEQUENCE_INVALID"; return false; }
      V2LevelState level;
      level.Reset();
      level.sequence_id=m_sequence.sequence_id;
      level.level_index=level_index;
      level.planned_price=planned_price;
      level.requested_volume=requested_volume;
      level.virtual_level=virtual_level;

      V2DomainEvent event;
      event.Reset();
      event.sequence_id=m_sequence.sequence_id;
      event.kind=V2_EVENT_LEVEL_PLANNED;
      event.action=action;
      event.risk_effect=risk_effect;
      event.direction=m_sequence.direction;
      event.symbol=m_sequence.symbol;
      event.occurred_at=V2UtcNow();
      event.level_index=level_index;
      event.volume=requested_volume;
      event.price=planned_price;
      event.reason_code=reason_code;
      if(!m_identity.EventId("GOAT2|LEVEL_PLAN|"+m_sequence.sequence_id+"|"+IntegerToString(level_index),event.event_id))
        { reason="LEVEL_PLAN_EVENT_ID_FAILED"; return false; }

      V2LevelState dummy;
      dummy.Reset();
      V2OrderIntent intent;
      intent.Reset();
      if(!PersistAndApply(event,true,level,false,dummy,false,intent,0.0,0.0,reason)) return false;
      const int next=ArraySize(m_levels);
      if(ArrayResize(m_levels,next+1)!=next+1)
        { reason="LEVEL_RUNTIME_ALLOCATION_FAILED_AFTER_PERSIST"; return false; }
      m_levels[next]=level;
      return true;
     }

   bool SubmitLevel(const int level_index,const double requested_volume,const string reason_code,string &reason)
     {
      reason="";
      if(level_index<0 || level_index>=ArraySize(m_levels) || requested_volume<=0.0)
        { reason="SUBMIT_LEVEL_ARGUMENT_INVALID"; return false; }
      MqlTick tick;
      if(!SymbolInfoTick(_Symbol,tick))
        { reason="SUBMIT_LEVEL_TICK_UNAVAILABLE"; return false; }
      const double atr=CurrentAtrPrice();
      if((V2_TakeProfitSize<0.0 || V2_StopLossSize<0.0) && atr<=0.0)
        { reason="ENTRY_ATR_NOT_READY"; return false; }
      const double tp_distance=ResolveSignedDistance(V2_TakeProfitSize,atr);
      const double sl_distance=ResolveSignedDistance(V2_StopLossSize,atr);
      const double entry=(m_sequence.direction==V2_DIR_LONG ? tick.ask : tick.bid);

      V2BrokerAction action;
      action.Reset();
      action.sequence_id=m_sequence.sequence_id;
      action.symbol=_Symbol;
      action.action=(level_index==0 ? V2_ACTION_OPEN : V2_ACTION_ADD);
      action.risk_effect=V2_RISK_INCREASE;
      action.direction=m_sequence.direction;
      action.state_version=m_sequence.last_state_version+1;
      action.level_index=level_index;
      action.volume=requested_volume;
      action.price=entry;
      action.stop_loss=(sl_distance>0.0 ? entry-(double)m_sequence.direction*sl_distance : 0.0);
      action.take_profit=(tp_distance>0.0 ? entry+(double)m_sequence.direction*tp_distance : 0.0);
      double planned_used=0.0;
      if(level_index>=0 && level_index<ArraySize(m_risk_result.loss_path))
         planned_used=m_risk_result.loss_path[level_index];
      const double live_overrun=MathMax(0.0,m_sequence.mlps_used-planned_used);
      action.projected_loss_delta=m_risk_result.maximum_loss+live_overrun;
      if(m_sequence.mlps_budget>0.0 && action.projected_loss_delta>m_sequence.mlps_budget+1e-8)
        {
         reason="LIVE_MLPS_BUDGET_BLOCKS_POSITIVE_ADD";
         if(level_index>0)
           {
            string receipt_reason="";
            if(!StoreLevelSkipReceipt(reason,level_index,requested_volume,entry,receipt_reason))
              {
               SetOperationalState(V2_OP_MANAGE_ONLY,"LEVEL_SKIP_RECEIPT_FAILED:"+receipt_reason);
               reason+="|RECEIPT_FAILED:"+receipt_reason;
              }
           }
         return false;
        }
      action.reason_code=reason_code;
      V2GatewayOutcome outcome;
      m_gateway.Execute(action,outcome);
      if(outcome.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"GATEWAY_REQUIRES_MANAGE_ONLY:"+outcome.reason_code);
      if(outcome.domain_event.event_id!="" && !ApplyPersistedGatewayEvent(outcome,reason))
        {
         SetOperationalState(V2_OP_RECOVERY_QUARANTINE,"GATEWAY_EVENT_PROJECTION_FAILED:"+reason);
         return false;
        }
      if(outcome.status==V2_GATEWAY_SUBMITTED || outcome.status==V2_GATEWAY_RECONCILE_REQUIRED)
        {
         m_pending.Reset();
         m_pending.active=true;
         m_pending.order_intent_id=outcome.order_intent_id;
         m_pending.action=action.action;
         m_pending.semantic_level_index=level_index;
         m_pending.request_id=outcome.request_id;
         m_pending.order_ticket=outcome.order_ticket;
         m_pending.requested_volume=outcome.safety.normalized_volume;
         m_pending.submitted_at_msc=V2UtcNowMsc();
         m_pending.submitted_tick_count=GetTickCount64();
         if(outcome.status==V2_GATEWAY_RECONCILE_REQUIRED)
            SetOperationalState(V2_OP_MANAGE_ONLY,"ENTRY_OUTCOME_REQUIRES_RECONCILIATION:"+outcome.reason_code);
         return true;
        }
      reason="LEVEL_SUBMISSION_"+outcome.reason_code;
      if((outcome.status==V2_GATEWAY_REJECTED || outcome.status==V2_GATEWAY_DENIED) &&
         !V2HasPhysicalVolume(m_sequence.standing_volume))
        {
         string end_reason="";
         if(!EndSequence("ENTRY_PROVEN_NOT_EXECUTED:"+outcome.reason_code,end_reason) && end_reason!="")
            reason+="|SEQUENCE_END_FAILED:"+end_reason;
        }
      return false;
     }

   bool StartSequence(const ENUM_V2_DIRECTION direction,const MqlTick &tick,const string policy_reason,string &reason)
     {
      reason="";
      if(direction==V2_DIR_NONE || !DirectionAllowed(direction))
        { reason="START_DIRECTION_NOT_ALLOWED"; return false; }
      if(m_operational_state!=V2_OP_NORMAL || !m_new_risk_enabled || !m_recovery_verified)
        { reason="START_OPERATIONAL_GATE_CLOSED"; return false; }

      V2SequenceState prior=m_sequence;
      m_sequence.Reset();
      if(!BuildExecutionPlans(direction,tick,0.0,reason))
        { m_sequence=prior; return false; }
      long ordinal=0;
      if(!m_database.ReserveCounter("sequence",ordinal,reason))
        { m_sequence=prior; return false; }
      string sequence_id="";
      if(!m_identity.SequenceId(direction,ordinal,sequence_id))
        { m_sequence=prior; reason="SEQUENCE_ID_GENERATION_FAILED"; return false; }

      m_sequence.Reset();
      m_sequence.sequence_id=sequence_id;
      m_sequence.strategy_member_id=m_identity.MemberId();
      m_sequence.symbol=_Symbol;
      m_sequence.direction=direction;
      m_sequence.max_levels=V2_MaxSequenceTrades;
      m_sequence.start_volume=m_lot_config.start_lots;
      m_sequence.experiment_manifest_id=m_manifest.manifest_id;
      m_sequence.input_values_hash=m_manifest.input_values_hash;
      m_sequence.broker_profile_hash=m_manifest.broker_profile_hash;
      m_sequence.symbol_spec_hash=CurrentSymbolSpecHash();
      m_sequence.execution_plan_hash=CurrentExecutionPlanHash();
      m_sequence.mlps_budget=(V2_LotMode==V2_LOTS_RISK_PER_SEQUENCE ?
                              MathMin(V2_RiskPerSequence,V2_MaxSequenceLoss) : V2_MaxSequenceLoss);
      m_sequence.mlps_used=0.0;
      m_maximum_adverse_excursion_atr=0.0;
      m_maximum_favorable_excursion_atr=0.0;
      ArrayResize(m_levels,0);

      V2DomainEvent start;
      start.Reset();
      start.sequence_id=sequence_id;
      start.kind=V2_EVENT_SEQUENCE_STARTED;
      start.action=V2_ACTION_OPEN;
      start.risk_effect=V2_RISK_INCREASE;
      start.direction=direction;
      start.symbol=_Symbol;
      start.occurred_at=V2UtcNow();
      start.volume=m_lot_config.start_lots;
      start.price=(direction==V2_DIR_LONG ? tick.ask : tick.bid);
      start.reason_code=policy_reason;
      if(!m_identity.EventId("GOAT2|SEQUENCE_START|"+sequence_id,start.event_id) || !PersistSimpleEvent(start,reason))
        {
         m_sequence=prior;
         return false;
        }
      const double entry=(direction==V2_DIR_LONG ? tick.ask : tick.bid);
      if(!PersistPlannedLevel(0,entry,m_lot_plan.normalized_delta[0],false,
                              V2_ACTION_OPEN,V2_RISK_INCREASE,"INITIAL_LEVEL",reason))
        {
         string end_reason="";
         EndSequence("INITIAL_LEVEL_PLAN_FAILED",end_reason);
         return false;
        }
      return SubmitLevel(0,m_lot_plan.normalized_delta[0],"INITIAL_LEVEL",reason);
     }

   bool SelectReductionTarget(const string reason_code,
                              V2OwnedPosition &target,
                              int &target_level,
                              string &reason) const
     {
      target.Reset();
      target_level=-1;
      V2OwnedPosition positions[];
      double standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,standing,vwap,floating,reason)) return false;
      if(ArraySize(positions)==0)
        { reason="REDUCTION_NO_OWNED_POSITION"; return false; }
      const bool smart=(StringFind(reason_code,"PEAK_SMART")>=0);
      int selected=-1;
      if(smart)
        {
         for(int i=0;i<ArraySize(positions);i++)
           {
            if(positions[i].profit+positions[i].swap<=0.0) continue;
            if(selected<0 ||
               (m_sequence.direction==V2_DIR_LONG && positions[i].open_price<positions[selected].open_price) ||
               (m_sequence.direction==V2_DIR_SHORT && positions[i].open_price>positions[selected].open_price))
               selected=i;
           }
        }
      if(selected<0)
        {
         double best_excess=DBL_MAX;
         for(int i=0;i<ArraySize(positions);i++)
           {
            const double excess=positions[i].volume-m_sequence.reduction_remaining;
            if(excess>=-1e-12 && excess<best_excess)
              { best_excess=excess; selected=i; }
           }
        }
      if(selected<0)
        {
         double largest=-1.0;
         for(int i=0;i<ArraySize(positions);i++)
            if(positions[i].volume>largest)
              { largest=positions[i].volume; selected=i; }
        }
      if(selected<0)
        { reason="REDUCTION_TARGET_SELECTION_FAILED"; return false; }
      target=positions[selected];
      target_level=FindLevelByPositionId(target.position_id);
      if(target_level<0)
        { reason="REDUCTION_TARGET_LINEAGE_MISSING"; return false; }
      return true;
     }

   bool SubmitNextReduction(string &reason)
     {
      reason="";
      const double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      if(m_pending.active || !V2HasPhysicalVolume(m_sequence.reduction_remaining)) return true;
      V2OwnedPosition target;
      int target_level=-1;
      if(!SelectReductionTarget(m_sequence.reduction_reason,target,target_level,reason)) return false;
      const double requested=MathMin(m_sequence.reduction_remaining,target.volume);
      const bool full=(target.volume-requested<minimum-1e-12);

      V2BrokerAction action;
      action.Reset();
      action.sequence_id=m_sequence.sequence_id;
      action.symbol=_Symbol;
      action.action=(full ? V2_ACTION_CLOSE : V2_ACTION_PARTIAL_CLOSE);
      action.risk_effect=V2_RISK_DECREASE;
      action.direction=m_sequence.direction;
      action.position_ticket=target.ticket;
      action.position_id=target.position_id;
      action.state_version=m_sequence.last_state_version+1;
      action.level_index=(m_sequence.reduction_semantic_level>=0 ? m_sequence.reduction_semantic_level : target_level);
      action.volume=(full ? target.volume : requested);
      action.projected_loss_delta=-MathMax(1.0,m_sequence.mlps_used);
      action.reason_code=m_sequence.reduction_reason;
      V2GatewayOutcome outcome;
      m_gateway.Execute(action,outcome);
      if(outcome.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"REDUCTION_GATEWAY_DEGRADED:"+outcome.reason_code);
      if(outcome.domain_event.event_id!="" && !ApplyPersistedGatewayEvent(outcome,reason))
        {
         SetOperationalState(V2_OP_RECOVERY_QUARANTINE,"REDUCTION_EVENT_PROJECTION_FAILED:"+reason);
         return false;
        }
      if(outcome.status!=V2_GATEWAY_SUBMITTED && outcome.status!=V2_GATEWAY_RECONCILE_REQUIRED)
        { reason="REDUCTION_SUBMISSION_"+outcome.reason_code; return false; }
      m_pending.Reset();
      m_pending.active=true;
      m_pending.order_intent_id=outcome.order_intent_id;
      m_pending.action=action.action;
      m_pending.semantic_level_index=action.level_index;
      m_pending.request_id=outcome.request_id;
      m_pending.order_ticket=outcome.order_ticket;
      m_pending.requested_volume=outcome.safety.normalized_volume;
      m_pending.submitted_at_msc=V2UtcNowMsc();
      m_pending.submitted_tick_count=GetTickCount64();
      if(outcome.status==V2_GATEWAY_RECONCILE_REQUIRED)
         SetOperationalState(V2_OP_MANAGE_ONLY,"REDUCTION_OUTCOME_REQUIRES_RECONCILIATION:"+outcome.reason_code);
      return true;
     }

   bool BeginReduction(const double requested,
                       const string reason_code,
                       const int semantic_level,
                       const bool advance_retrace,
                       string &reason)
     {
      reason="";
      if(m_sequence.sequence_id=="" || requested<=0.0)
        { reason="REDUCTION_REQUEST_INVALID"; return false; }
      const double target=MathMin(requested,m_sequence.standing_volume);
      if(m_sequence.reduction_reason=="" || target>m_sequence.reduction_remaining+1e-12)
        {
         V2DomainEvent mandate;
         mandate.Reset();
         mandate.sequence_id=m_sequence.sequence_id;
         mandate.kind=V2_EVENT_REDUCTION_MANDATED;
         mandate.action=(target>=m_sequence.standing_volume-1e-12 ? V2_ACTION_CLOSE : V2_ACTION_PARTIAL_CLOSE);
         mandate.risk_effect=V2_RISK_DECREASE;
         mandate.direction=m_sequence.direction;
         mandate.symbol=m_sequence.symbol;
         mandate.occurred_at=V2UtcNow();
         mandate.level_index=semantic_level;
         mandate.volume=target;
         mandate.retrace_advance=advance_retrace;
         mandate.reason_code=reason_code;
         if(!PersistSimpleEvent(mandate,reason)) return false;
        }
      return SubmitNextReduction(reason);
     }

   double CurrentSequenceProfit(void) const
     {
      V2OwnedPosition positions[];
      double standing=0.0,vwap=0.0,floating=0.0;
      string reason="";
      if(!ScanOwnedPositions(positions,standing,vwap,floating,reason))
         return m_sequence.realized_pl+m_sequence.commission+m_sequence.swap;
      return m_sequence.realized_pl+m_sequence.commission+m_sequence.swap+floating;
     }

   bool RefreshFeatures(const MqlTick &tick)
     {
      const double planned_peak=(m_lot_plan.valid ? m_lot_plan.peak_cumulative : 0.0);
      return m_features.Update(tick,m_sequence.standing_volume,planned_peak,
                               m_sequence.mlps_used,m_sequence.mlps_budget,m_feature_frame);
     }

   bool BuildBasket(V2OwnedPosition &positions[],V2BasketPlan &plan,string &reason) const
     {
      reason="";
      double prices[],volumes[];
      ArrayResize(prices,ArraySize(positions));
      ArrayResize(volumes,ArraySize(positions));
      for(int i=0;i<ArraySize(positions);i++)
        {
         prices[i]=positions[i].open_price;
         volumes[i]=positions[i].volume;
        }
      const double atr=CurrentAtrPrice();
      if((V2_LockProfitSize<0.0 || V2_TakeProfitSize<0.0 || V2_StopLossSize<0.0 || V2_TrailingStopSize<0.0) && atr<=0.0)
        { reason="BASKET_ATR_NOT_READY"; return false; }
      V2BasketPlanConfig config;
      config.Reset();
      config.direction=m_sequence.direction;
      config.executed_trade_count=ExecutedTradeCount();
      config.maximum_trade_count=V2_MaxSequenceTrades;
      config.executed_level_count=m_sequence.level_count;
      config.maximum_level_count=V2_MaxSequenceTrades;
      config.lock_distance=ResolveSignedDistance(V2_LockProfitSize,atr);
      config.lock_flexibility=V2_LockFlexibility;
      config.take_profit_distance=ResolveSignedDistance(V2_TakeProfitSize,atr);
      config.stop_loss_distance=ResolveSignedDistance(V2_StopLossSize,atr);
      config.trailing_distance=ResolveSignedDistance(V2_TrailingStopSize,atr);
      config.tick_size=TickSize();
      if(!m_basket_planner.Build(config,prices,volumes,plan))
        { reason=plan.reason; return false; }
      return true;
     }

   bool ModifyProtection(const V2OwnedPosition &position,
                         const double stop_loss,
                         const double take_profit,
                         const bool monotonic_reduction,
                         string &reason)
     {
      reason="";
      V2BrokerAction action;
      action.Reset();
      action.sequence_id=m_sequence.sequence_id;
      action.symbol=_Symbol;
      action.action=V2_ACTION_MODIFY;
      action.risk_effect=(monotonic_reduction ? V2_RISK_DECREASE : V2_RISK_UNKNOWN);
      action.direction=m_sequence.direction;
      action.position_ticket=position.ticket;
      action.position_id=position.position_id;
      action.state_version=m_sequence.last_state_version+1;
      action.level_index=FindLevelByPositionId(position.position_id);
      action.stop_loss=stop_loss;
      action.take_profit=take_profit;
      action.current_stop_loss=position.stop_loss;
      action.current_take_profit=position.take_profit;
      action.projected_loss_delta=(monotonic_reduction ? -1.0 : m_risk_result.maximum_loss);
      action.reason_code=(monotonic_reduction ? "PROTECTIVE_TIGHTEN" : "BASKET_PROTECTION_SYNC");
      V2GatewayOutcome outcome;
      m_gateway.Execute(action,outcome);
      if(outcome.requires_manage_only)
         SetOperationalState(V2_OP_MANAGE_ONLY,"PROTECTION_GATEWAY_DEGRADED:"+outcome.reason_code);
      if(outcome.domain_event.event_id!="" && !ApplyPersistedGatewayEvent(outcome,reason))
         return false;
      if(outcome.status!=V2_GATEWAY_SUBMITTED)
        { reason="PROTECTION_SUBMISSION_"+outcome.reason_code; return false; }
      return true;
     }

   bool ManageProtection(const MqlTick &tick,string &reason)
     {
      reason="";
      if(m_sequence.sequence_id=="" ||
         (m_sequence.status!=V2_SEQ_ACTIVE && m_sequence.status!=V2_SEQ_REDUCE_ONLY && m_sequence.status!=V2_SEQ_QUARANTINED))
         return true;
      V2OwnedPosition positions[];
      double standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,standing,vwap,floating,reason)) return false;
      if(standing<=0.0) return true;
      const double sequence_pl=m_sequence.realized_pl+m_sequence.commission+m_sequence.swap+floating;
      m_sequence.mlps_used=MathMax(0.0,-sequence_pl);
      const double equity=AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity>m_peak_equity)
        {
         m_peak_equity=equity;
         string high_water_reason="";
         if(!m_database.StoreRiskHighWater("account_equity_peak",m_peak_equity,high_water_reason))
           {
            m_risk_high_water_ready=false;
            SetOperationalState(V2_OP_MANAGE_ONLY,"RISK_HIGH_WATER_WRITE_FAILED:"+high_water_reason);
           }
        }
      const double drawdown_pct=(m_peak_equity>0.0 ? 100.0*(m_peak_equity-equity)/m_peak_equity : 0.0);
      if((V2_EquityFloor>0.0 && equity<=V2_EquityFloor) || drawdown_pct>=V2_MaxEquityDrawdownPct)
         return BeginReduction(standing,
                               (V2_EquityFloor>0.0 && equity<=V2_EquityFloor ? "EQUITY_FLOOR" : "EQUITY_DRAWDOWN_LIMIT"),
                               -1,false,reason);
      if(V2_EnableSequenceLossHardClose && m_sequence.mlps_budget>0.0 && sequence_pl<=-m_sequence.mlps_budget)
         return BeginReduction(standing,"MLPS_HARD_CLOSE",-1,false,reason);
      if(V2HasPhysicalVolume(m_sequence.reduction_remaining))
         return SubmitNextReduction(reason);

      V2BasketPlan basket;
      if(!BuildBasket(positions,basket,reason)) return false;
      const double market=(m_sequence.direction==V2_DIR_LONG ? tick.bid : tick.ask);
      string excursion_reason="";
      if(!UpdateSequenceExcursions(vwap,market,excursion_reason))
         SetOperationalState(V2_OP_MANAGE_ONLY,"EXCURSION_HIGH_WATER_WRITE_FAILED:"+excursion_reason);
      const bool tp_hit=(basket.take_profit_price>0.0 &&
                         (m_sequence.direction==V2_DIR_LONG ? market>=basket.take_profit_price : market<=basket.take_profit_price));
      const bool sl_hit=(basket.stop_loss_price>0.0 &&
                         (m_sequence.direction==V2_DIR_LONG ? market<=basket.stop_loss_price : market>=basket.stop_loss_price));
      if(tp_hit || sl_hit)
         return BeginReduction(standing,(tp_hit ? "BASKET_TAKE_PROFIT" : "BASKET_STOP_LOSS"),-1,false,reason);

      const double point=PointSize();
      const double minimum_distance=MathMax((double)MathMax(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),
                                                            SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL)),1.0)*point;
      const bool lock_reached=(basket.lock_price>0.0 &&
                               (m_sequence.direction==V2_DIR_LONG ? market>=basket.lock_price : market<=basket.lock_price));
      V2BasketPlanConfig trailing_config;
      trailing_config.Reset();
      trailing_config.direction=m_sequence.direction;
      trailing_config.trailing_distance=ResolveSignedDistance(V2_TrailingStopSize,CurrentAtrPrice());
      trailing_config.tick_size=TickSize();
      for(int i=0;i<ArraySize(positions);i++)
        {
         double desired_stop=basket.stop_loss_price;
         bool monotonic=false;
         if(lock_reached && trailing_config.trailing_distance>0.0)
           {
            double trailing=0.0;
            if(m_basket_planner.NextTrailingStop(trailing_config,tick.bid,tick.ask,minimum_distance,
                                                 positions[i].stop_loss,trailing))
              {
               desired_stop=trailing;
               monotonic=true;
              }
           }
         // A trailing-stop tighten must never be coupled to a farther profit
         // target, which would change its risk classification in degraded
         // states. Profit-target synchronization can retry independently.
         const double desired_tp=(monotonic ? positions[i].take_profit : basket.take_profit_price);
         const double epsilon=TickSize()*0.5;
         if(MathAbs(desired_stop-positions[i].stop_loss)<=epsilon &&
            MathAbs(desired_tp-positions[i].take_profit)<=epsilon)
            continue;
         string modify_reason="";
         if(!ModifyProtection(positions[i],desired_stop,desired_tp,monotonic,modify_reason))
           {
            Print("GOAT2|PROTECTION|DEFERRED|",modify_reason);
            if(StringFind(modify_reason,"PROJECTION")>=0)
              { reason=modify_reason; return false; }
           }
        }
      return true;
     }

   bool MaybeHandleRetrace(const MqlTick &tick,string &reason)
     {
      reason="";
      if(m_sequence.status!=V2_SEQ_ACTIVE || m_sequence.retrace_price<=0.0 ||
         m_pending.active || V2HasPhysicalVolume(m_sequence.reduction_remaining))
         return true;
      const double market=(m_sequence.direction==V2_DIR_LONG ? tick.bid : tick.ask);
      if(!m_retrace_planner.Crossed(m_sequence.direction,market,m_sequence.retrace_price)) return true;
      const double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      const double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
      const double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
      double close_volume=0.0;
      string close_reason="";
      if(V2_LotProgression==V2_LOT_CUMULATIVE_PARTIAL)
        {
         close_volume=m_retrace_planner.CumulativePartialClose(m_sequence.standing_volume,
                                                               V2_CumPartialReleasePercent,
                                                               minimum,maximum,step);
         close_reason="CUM_PARTIAL_RETRACE";
        }
      else if(V2_LotProgression==V2_LOT_PEAK_SMART)
        {
         int retrace_index=-1;
         for(int i=0;i<ArraySize(m_levels);i++)
            if(MathAbs(m_levels[i].planned_price-m_sequence.retrace_price)<=PointSize()*2.0)
              { retrace_index=i; break; }
         if(retrace_index<0 || retrace_index>=ArraySize(m_lot_plan.cumulative_lots))
           { reason="PEAK_SMART_RETRACE_PLAN_INDEX_MISSING"; return false; }
         V2PeakSmartRetraceResult smart;
         if(!m_retrace_planner.EvaluatePeakSmart(m_sequence.standing_volume,
                                                 m_lot_plan.cumulative_lots[retrace_index],
                                                 CurrentSequenceProfit(),
                                                 V2_PeakSmartReleasePercent,
                                                 V2_PeakSmartMaxClosePercent,
                                                 minimum,maximum,step,smart))
           { reason=smart.reason; return false; }
         if(smart.decision==V2_PEAK_SMART_HOLD_WHILE_UNDERWATER)
            return true;
         if(smart.decision==V2_PEAK_SMART_ADVANCE_WITHOUT_CLOSE)
            return AdvanceRetracePointer(reason);
         close_volume=smart.close_volume;
         close_reason="PEAK_SMART_RETRACE";
        }
      else return true;
      if(close_volume<minimum-1e-12)
         return AdvanceRetracePointer(reason);
      return BeginReduction(close_volume,close_reason,-1,true,reason);
     }

   bool MaybeAddLevel(const MqlTick &tick,string &reason)
     {
      reason="";
      if(m_sequence.status!=V2_SEQ_ACTIVE || m_pending.active ||
         V2HasPhysicalVolume(m_sequence.reduction_remaining))
         return true;
      if(!m_plans_ready)
        {
         RefreshFeatures(tick);
         string plan_reason="";
         if(!BuildExecutionPlans(m_sequence.direction,tick,m_sequence.start_volume,plan_reason))
           {
            Print("GOAT2|SEQUENCE|PLAN_NOT_READY|",plan_reason);
            return true;
           }
        }
      const int next_level=m_sequence.level_count;
      if(next_level>=V2_MaxSequenceTrades)
        {
         if(V2_CloseAtMaxLevels && m_sequence.standing_volume>0.0)
            return BeginReduction(m_sequence.standing_volume,"MAXIMUM_LEVELS_REACHED",-1,false,reason);
         return true;
        }
      if(next_level<=0 || next_level>=ArraySize(m_grid_plan.step_distance)) return true;
      if(next_level-1>=ArraySize(m_levels))
        { reason="ADD_REFERENCE_LEVEL_MISSING"; return false; }
      const double prior=m_levels[next_level-1].planned_price;
      const double trigger=(m_sequence.direction==V2_DIR_LONG ?
                            prior-m_grid_plan.step_distance[next_level] :
                            prior+m_grid_plan.step_distance[next_level]);
      const double market=(m_sequence.direction==V2_DIR_LONG ? tick.ask : tick.bid);
      const bool adverse=(m_sequence.direction==V2_DIR_LONG ? market<=trigger : market>=trigger);
      if(!adverse) return true;

      if(V2_SignalMode!=V2_SIGNAL_DISABLED)
        {
         RefreshFeatures(tick);
         const ENUM_V2_DIRECTION recheck=m_features.Signal(V2_SignalMode,m_feature_frame,
                                                           V2_RsiLongThreshold,V2_RsiShortThreshold);
         if(recheck!=m_sequence.direction)
           {
            if(!StoreLevelSkipReceipt("ADVERSE_LEVEL_SIGNAL_RECHECK_BLOCKED",next_level,0.0,market,reason))
              {
               SetOperationalState(V2_OP_MANAGE_ONLY,"LEVEL_SKIP_RECEIPT_FAILED:"+reason);
               return false;
              }
            return true;
           }
        }
      double delta=0.0;
      if(V2_LotProgression==V2_LOT_CUMULATIVE_PARTIAL)
         delta=m_lot_planner.NextCumulativePartial(m_lot_config,next_level,m_sequence.standing_volume);
      else if(V2_LotProgression==V2_LOT_PEAK_SMART)
         delta=m_lot_planner.NextPeakSmart(m_lot_config,m_lot_plan,next_level,m_sequence.standing_volume);
      else if(next_level<ArraySize(m_lot_plan.normalized_delta))
         delta=m_lot_plan.normalized_delta[next_level];
      const double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      if(MathAbs(delta)<minimum-1e-12)
        {
         if(!StoreLevelSkipReceipt("ADVERSE_LEVEL_DELTA_BELOW_MINIMUM",next_level,MathAbs(delta),market,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"LEVEL_SKIP_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }

      if(next_level<ArraySize(m_levels))
        {
         if(delta>0.0) return SubmitLevel(next_level,m_levels[next_level].requested_volume,"RETRY_PLANNED_LEVEL",reason);
         return BeginReduction(MathAbs(delta),"PROGRAMMED_UNWIND",next_level,false,reason);
        }
      if(delta<0.0)
        {
         if(!PersistPlannedLevel(next_level,market,MathAbs(delta),true,
                                 V2_ACTION_PARTIAL_CLOSE,V2_RISK_DECREASE,"PROGRAMMED_UNWIND",reason))
            return false;
         return BeginReduction(MathAbs(delta),"PROGRAMMED_UNWIND",next_level,false,reason);
        }
      if(!PersistPlannedLevel(next_level,market,delta,false,V2_ACTION_ADD,V2_RISK_INCREASE,"ADVERSE_LEVEL",reason))
         return false;
      return SubmitLevel(next_level,delta,"ADVERSE_LEVEL",reason);
     }

   bool MaybeStartNewSequence(const MqlTick &tick,string &reason)
     {
      reason="";
      if(m_pending.active || V2HasPhysicalVolume(m_sequence.reduction_remaining) ||
         (m_sequence.sequence_id!="" && m_sequence.status!=V2_SEQ_ENDED && m_sequence.status!=V2_SEQ_IDLE))
         return true;
      if(!RefreshFeatures(tick))
        {
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SEQUENCE_START_SUPPRESSED,"FEATURES_NOT_READY",
                                     V2_DIR_NONE,V2_ACTION_OPEN,V2_RISK_INCREASE,-1,0.0,0.0,
                                     m_last_entry_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SEQ_SUPPRESSION_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }
      const ENUM_V2_DIRECTION deterministic=m_features.Signal(V2_SignalMode,m_feature_frame,
                                                               V2_RsiLongThreshold,V2_RsiShortThreshold);
      if(deterministic==V2_DIR_NONE)
        {
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SEQUENCE_START_SUPPRESSED,"DETERMINISTIC_SIGNAL_NONE",
                                     deterministic,V2_ACTION_OPEN,V2_RISK_INCREASE,-1,0.0,0.0,
                                     m_last_entry_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SEQ_SUPPRESSION_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }
      if(!DirectionAllowed(deterministic))
        {
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SEQUENCE_START_SUPPRESSED,"TRADE_DIRECTION_BLOCKED",
                                     deterministic,V2_ACTION_OPEN,V2_RISK_INCREASE,-1,0.0,0.0,
                                     m_last_entry_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SEQ_SUPPRESSION_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }
      V2IntelligenceState intelligence;
      m_intelligence.Current(intelligence);
      if(!m_policy.Evaluate(deterministic,m_feature_frame,intelligence,m_policy_envelope))
         { reason="POLICY_EVALUATION_FAILED"; return false; }
      m_onnx.Evaluate(m_feature_frame,m_onnx_proposal);
      if(V2_StateMode==V2_STATE_SHADOW || V2_OnnxMode==V2_ONNX_SHADOW)
        {
         const string shadow_reason="POLICY="+m_policy_envelope.reason_code+
                                    "|ONNX="+m_onnx_proposal.reason_code;
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SHADOW_DECISION,shadow_reason,
                                     m_policy_envelope.proposed_direction,V2_ACTION_OPEN,V2_RISK_NEUTRAL,
                                     -1,0.0,(deterministic==V2_DIR_LONG ? tick.ask : tick.bid),
                                     m_last_shadow_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SHADOW_DECISION_RECEIPT_FAILED:"+reason);
            return false;
           }
        }
      if(!m_policy_envelope.allow_new_sequence)
        {
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SEQUENCE_START_SUPPRESSED,
                                     "POLICY_BLOCKED:"+m_policy_envelope.reason_code,
                                     deterministic,V2_ACTION_OPEN,V2_RISK_INCREASE,-1,0.0,0.0,
                                     m_last_entry_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SEQ_SUPPRESSION_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }
      if(m_operational_state!=V2_OP_NORMAL || !m_new_risk_enabled || !m_recovery_verified)
        {
         if(!StoreBarDecisionReceipt(V2_RECEIPT_SEQUENCE_START_SUPPRESSED,
                                     "OPERATIONAL_GATE_CLOSED:"+m_operational_reason,
                                     m_policy_envelope.proposed_direction,V2_ACTION_OPEN,V2_RISK_INCREASE,
                                     -1,0.0,0.0,m_last_entry_decision_bar,reason))
           {
            SetOperationalState(V2_OP_MANAGE_ONLY,"SEQ_SUPPRESSION_RECEIPT_FAILED:"+reason);
            return false;
           }
         return true;
        }
      return StartSequence(m_policy_envelope.proposed_direction,tick,m_policy_envelope.reason_code,reason);
     }

   void RenderHud(const bool force)
     {
      const long now=(long)GetTickCount64();
      if(!force && now-m_last_hud_render_msc<1000) return;
      V2HudSnapshot snapshot;
      snapshot.operational_state=m_operational_state;
      snapshot.sequence=m_sequence;
      m_intelligence.Current(snapshot.intelligence);
      snapshot.equity=AccountInfoDouble(ACCOUNT_EQUITY);
      snapshot.free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      MqlTick tick;
      snapshot.spread_points=0.0;
      if(SymbolInfoTick(_Symbol,tick) && PointSize()>0.0)
         snapshot.spread_points=(tick.ask-tick.bid)/PointSize();
      snapshot.new_risk_enabled=m_new_risk_enabled;
      snapshot.build_id=m_build_id;
      if(force) m_hud.MarkDirty();
      m_hud.Render(snapshot);
      V2IntelligenceState intelligence;
      m_intelligence.Current(intelligence);
      m_overlay.UpdateIntelligence(intelligence);
      m_overlay.UpdateSequence(m_sequence,
                               (m_risk_result.valid ? m_risk_result.price_at_maximum : 0.0),
                               m_sequence.retrace_price);
      m_last_hud_render_msc=now;
     }

   bool Housekeeping(string &reason)
     {
      reason="";
      if(m_database.IsReadOnlyRecovery())
        {
         SetOperationalState(V2_OP_HALTED,"DATABASE_READ_ONLY_RECOVERY:"+m_database.StatusReason());
         RenderHud(false);
         return true;
        }
      if(!m_database.Heartbeat(reason))
        {
         SetOperationalState(V2_OP_DEGRADED,"DATABASE_HEARTBEAT_FAILED:"+reason);
         return false;
        }
      if(!m_risk_high_water_ready)
        {
         string recovery_reason="";
         if(!InitializeRiskHighWater(recovery_reason))
           {
            reason="RISK_HIGH_WATER_RECOVERY_FAILED:"+recovery_reason;
            SetOperationalState(V2_OP_DEGRADED,reason);
            return false;
           }
         m_gateway.SetDurablePeakEquity(m_peak_equity);
        }
      const double equity=AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity>m_peak_equity)
        {
         m_peak_equity=equity;
         if(!m_database.StoreRiskHighWater("account_equity_peak",m_peak_equity,reason))
            {
             m_risk_high_water_ready=false;
             SetOperationalState(V2_OP_DEGRADED,"RISK_HIGH_WATER_WRITE_FAILED:"+reason);
             return false;
           }
         m_gateway.SetDurablePeakEquity(m_peak_equity);
        }
      const ulong now_tick_count=GetTickCount64();
      if(m_pending.active && m_pending.submitted_tick_count>0 &&
         now_tick_count-m_pending.submitted_tick_count>=30000)
        {
         if(!ReconcileUnsettledIntents(reason))
           {
            EnterRecoveryQuarantine("PENDING_EXECUTION_TIMEOUT:"+reason);
            return false;
           }
        }
      V2TelemetryStatus status;
      string telemetry_reason="";
      if(!m_telemetry.RecordHeartbeat(m_identity.DeploymentId(),m_operational_state,
                                      V2UtcNowMsc(),m_manifest.manifest_id,
                                      status,telemetry_reason) || status.requires_manage_only)
        {
         m_healthy_recovery_passes=0;
         SetOperationalState(V2_OP_DEGRADED,"TELEMETRY_HEARTBEAT_GATE:"+telemetry_reason+status.reason);
         return false;
        }
      if(m_gateway.RingOverflowed())
        {
         reason="GATEWAY_OBSERVATION_RING_OVERFLOW";
         EnterRecoveryQuarantine(reason);
         return false;
        }
      if(m_gateway.RequiresFullReconciliation() && !m_pending.active &&
         m_gateway.PendingObservationCount()==0)
        {
         if(!ReconcileUnsettledIntents(reason) || !RecoveryMatchesBroker(reason))
           {
            EnterRecoveryQuarantine("GATEWAY_FULL_RECONCILIATION:"+reason);
            return false;
           }
         m_gateway.AcknowledgeFullReconciliation();
        }

      int unprocessed_before=0;
      if(!m_database.CountUnprocessedTradeObservations(unprocessed_before,reason))
        {
         m_healthy_recovery_passes=0;
         SetOperationalState(V2_OP_DEGRADED,"OBSERVATION_COUNT_FAILED:"+reason);
         return false;
        }
      if(m_gateway.PendingObservationCount()==0 && unprocessed_before==0 && !m_pending.active)
        {
         string match_reason="";
         const bool matches=RecoveryMatchesBroker(match_reason);
         int unprocessed_after=0;
         if(!m_database.CountUnprocessedTradeObservations(unprocessed_after,reason))
           {
            m_healthy_recovery_passes=0;
            SetOperationalState(V2_OP_DEGRADED,"OBSERVATION_RECOUNT_FAILED:"+reason);
            return false;
           }
         const bool stable_snapshot=(m_gateway.PendingObservationCount()==0 &&
                                     unprocessed_after==0 && !m_pending.active);
         if(stable_snapshot && !matches)
           {
            m_healthy_recovery_passes=0;
            m_broker_mismatch_passes++;
            if(m_broker_mismatch_passes>=2)
              {
               reason="CONTINUOUS_BROKER_MATCH:"+match_reason;
               EnterRecoveryQuarantine(reason);
               return false;
              }
            SetOperationalState(V2_OP_DEGRADED,"BROKER_MATCH_RECHECK_REQUIRED:"+match_reason);
           }
         else if(stable_snapshot && matches)
           {
            m_broker_mismatch_passes=0;
            if(m_supervised_repromotion_pending &&
               (m_operational_state==V2_OP_DEGRADED ||
                m_operational_state==V2_OP_MANAGE_ONLY))
               m_healthy_recovery_passes++;
            else
               m_healthy_recovery_passes=0;
           }
        }
      else
        {
         m_broker_mismatch_passes=0;
         m_healthy_recovery_passes=0;
        }

      const bool promotion_eligible=(m_supervised_repromotion_pending &&
                                     m_healthy_recovery_passes>=3 && m_recovery_verified &&
                                     m_risk_high_water_ready && m_broker_profile_verified &&
                                     m_database.BrokerMutationAllowed() &&
                                     !m_gateway.RequiresFullReconciliation() &&
                                     !m_gateway.RingOverflowed() &&
                                     (m_operational_state==V2_OP_DEGRADED ||
                                      m_operational_state==V2_OP_MANAGE_ONLY));
      if(promotion_eligible && GOAT2_PHASE1_EXECUTION_CERTIFIED==1 &&
         V2_RunMode==V2_RUN_TRADE && V2_EnableNewRisk)
        {
         SetOperationalState(V2_OP_NORMAL,"SUPERVISED_HEALTH_REPROMOTION");
         m_healthy_recovery_passes=0;
        }
      else if(promotion_eligible)
        {
         SetOperationalState(V2_OP_MANAGE_ONLY,"SUPERVISED_HEALTH_RECOVERED_EXECUTION_LOCKED");
        }
      RenderHud(false);
      return true;
     }

   bool ProcessDueWork(string &reason)
     {
      reason="";
      V2ScheduledWork work[];
      const int count=m_scheduler.CollectDueWork(work,V2_MANAGER_WORK_BUDGET);
      for(int i=0;i<count;i++)
        {
         MqlTick tick;
         switch(work[i].kind)
           {
            case V2_WORK_DRAIN_TRANSACTIONS:
               m_gateway.DrainTradeObservations(V2_MANAGER_OBSERVATION_BUDGET);
               if(!ProcessTradeObservations(reason))
                 {
                  EnterRecoveryQuarantine("TRANSACTION_RECONCILIATION:"+reason);
                  return false;
                 }
               break;
            case V2_WORK_PROTECTIVE_MANAGEMENT:
               if(m_scheduler.LatestTick(tick) && !ManageProtection(tick,reason))
                 {
                  if(StringFind(reason,"PROJECTION")>=0 || StringFind(reason,"LINEAGE")>=0)
                     EnterRecoveryQuarantine("PROTECTIVE_MANAGEMENT:"+reason);
                  return false;
                 }
               break;
            case V2_WORK_SEQUENCE_MANAGEMENT:
               if(m_scheduler.LatestTick(tick))
                 {
                  if(!MaybeHandleRetrace(tick,reason) || !MaybeAddLevel(tick,reason)) return false;
                  if(V2HasPhysicalVolume(m_sequence.reduction_remaining) &&
                     !m_pending.active && !SubmitNextReduction(reason)) return false;
                 }
               break;
            case V2_WORK_SCHEDULED_EXITS:
               break;
            case V2_WORK_NEW_ENTRY:
               if(m_scheduler.LatestTick(tick) && !MaybeStartNewSequence(tick,reason)) return false;
               break;
            case V2_WORK_HOUSEKEEPING:
               Housekeeping(reason);
               break;
           }
        }
      return true;
     }

public:
   void OnTick(const MqlTick &tick)
     {
      if(!m_initialized) return;
      if(m_database.IsReadOnlyRecovery())
        {
         SetOperationalState(V2_OP_HALTED,
                             "DATABASE_READ_ONLY_RECOVERY:"+m_database.StatusReason());
         RenderHud(false);
         return;
        }
      if(V2_RunMode==V2_RUN_DISABLED)
        {
         SetOperationalState(V2_OP_HALTED,"RUN_DISABLED_NO_BROKER_MUTATIONS");
         RenderHud(false);
         return;
        }
      m_scheduler.OnChartTick(tick);
      string reason="";
      if(!ProcessDueWork(reason) && reason!="")
         Print("GOAT2|WORK|DEFERRED|",reason);
     }

   void OnTimer(void)
     {
      if(!m_initialized) return;
      if(m_database.IsReadOnlyRecovery())
        {
         SetOperationalState(V2_OP_HALTED,
                             "DATABASE_READ_ONLY_RECOVERY:"+m_database.StatusReason());
         RenderHud(false);
         return;
        }
      if(V2_RunMode==V2_RUN_DISABLED)
        {
         SetOperationalState(V2_OP_HALTED,"RUN_DISABLED_NO_BROKER_MUTATIONS");
         RenderHud(false);
         return;
        }
      m_scheduler.OnTimer();
      string reason="";
      if(!ProcessDueWork(reason) && reason!="")
         Print("GOAT2|TIMER|DEFERRED|",reason);
     }

   void OnTradeTransaction(const MqlTradeTransaction &transaction,
                           const MqlTradeRequest &request,
                           const MqlTradeResult &result)
     {
      if(!m_initialized) return;
      if(m_database.IsReadOnlyRecovery() || V2_RunMode==V2_RUN_DISABLED) return;
      m_gateway.CaptureTradeTransaction(transaction,request,result);
     }

   void OnChartEvent(const int id,const long lparam,const double dparam,const string sparam)
     {
      if(!m_initialized) return;
      if(m_database.IsReadOnlyRecovery() || V2_RunMode==V2_RUN_DISABLED) return;
      const ENUM_V2_HUD_COMMAND command=m_hud.OnChartEvent(id,lparam,dparam);
      if(command==V2_HUD_NONE) return;
      string reason="";
      switch(command)
        {
         case V2_HUD_PAUSE_NEW_RISK:
            SetOperationalState(V2_OP_MANAGE_ONLY,"HUD_PAUSE_CONFIRMED");
            break;
         case V2_HUD_REDUCE_ONLY:
            SetOperationalState(V2_OP_MANAGE_ONLY,"HUD_REDUCE_ONLY_CONFIRMED");
            break;
         case V2_HUD_CLOSE_SEQUENCE:
         case V2_HUD_CLOSE_ALL:
            {
             V2OwnedPosition positions[];
             double standing=0.0,vwap=0.0,floating=0.0;
             if(ScanOwnedPositions(positions,standing,vwap,floating,reason) && standing>0.0)
               BeginReduction(standing,
                              (command==V2_HUD_CLOSE_ALL ? "HUD_CLOSE_MEMBER" : "HUD_CLOSE_SEQUENCE"),
                              -1,false,reason);
             break;
            }
         default:
            break;
        }
      if(reason!="") Print("GOAT2|HUD|",reason);
      RenderHud(true);
     }

#ifdef GOAT2_TEST_HOOKS
   bool TestGatewayStartSequence(const ENUM_V2_DIRECTION direction,string &reason)
     {
      reason="";
      if(!MQLInfoInteger(MQL_TESTER))
        { reason="TEST_HOOK_REQUIRES_STRATEGY_TESTER"; return false; }
      if(!m_initialized)
        { reason="TEST_HOOK_MANAGER_NOT_INITIALIZED"; return false; }
      if(GOAT2_PHASE1_EXECUTION_CERTIFIED!=1)
        { reason="TEST_HOOK_CERTIFIED_BUILD_REQUIRED"; return false; }
      if(m_operational_state!=V2_OP_NORMAL || !m_recovery_verified || !m_new_risk_enabled)
        { reason="TEST_HOOK_NEW_RISK_GATE_CLOSED:"+m_operational_reason; return false; }
      if(m_sequence.sequence_id!="" && m_sequence.status!=V2_SEQ_ENDED)
        { reason="TEST_HOOK_SEQUENCE_ALREADY_MANAGEABLE"; return false; }
      V2OwnedPosition positions[];
      double broker_standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,broker_standing,vwap,floating,reason)) return false;
      const double epsilon=V2PhysicalVolumeEpsilon();
      if(broker_standing>epsilon || ArraySize(positions)>0)
        { reason="TEST_HOOK_BROKER_NOT_FLAT_AT_START"; return false; }
      MqlTick tick;
      if(!SymbolInfoTick(_Symbol,tick))
        { reason="TEST_HOOK_TICK_UNAVAILABLE"; return false; }
      return StartSequence(direction,tick,"GATEWAY_INTEGRATION_REAL_OPEN",reason);
     }

   bool TestGatewayForceFullReduction(string &reason)
     {
      reason="";
      if(!MQLInfoInteger(MQL_TESTER))
        { reason="TEST_HOOK_REQUIRES_STRATEGY_TESTER"; return false; }
      if(!m_initialized)
        { reason="TEST_HOOK_MANAGER_NOT_INITIALIZED"; return false; }
      if(m_pending.active)
        { reason="TEST_HOOK_EXECUTION_STILL_PENDING"; return false; }
      V2OwnedPosition positions[];
      double broker_standing=0.0,vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,broker_standing,vwap,floating,reason)) return false;
      const double epsilon=V2PhysicalVolumeEpsilon();
      if(!V2HasPhysicalVolume(broker_standing) || ArraySize(positions)<1)
        { reason="TEST_HOOK_NO_REAL_POSITION_TO_REDUCE"; return false; }
      if(MathAbs(broker_standing-m_sequence.standing_volume)>epsilon)
        { reason="TEST_HOOK_PRE_REDUCTION_JOURNAL_MISMATCH"; return false; }
      return BeginReduction(broker_standing,"GATEWAY_INTEGRATION_FORCED_FULL_REDUCTION",-1,false,reason);
     }

   bool TestGatewayExerciseRiskHighWaterLatchRearm(string &reason)
     {
      reason="";
      if(!MQLInfoInteger(MQL_TESTER))
        { reason="TEST_HOOK_REQUIRES_STRATEGY_TESTER"; return false; }
      if(!m_initialized)
        { reason="TEST_HOOK_MANAGER_NOT_INITIALIZED"; return false; }
      double durable_before=0.0;
      bool durable_before_found=false;
      if(!m_database.LoadRiskHighWater("account_equity_peak",durable_before,
                                      durable_before_found,reason))
         return false;
      const double peak_before=MathMax(m_peak_equity,
                                       (durable_before_found ? durable_before : 0.0))+1.0;
      // Model the exact transient-failure case: memory observed a newer peak,
      // the durable store missed it, and equity subsequently fell below it.
      m_peak_equity=peak_before;
      m_risk_high_water_ready=false;
      if(!Housekeeping(reason)) return false;
      if(!m_risk_high_water_ready)
        { reason="TEST_HOOK_RISK_HIGH_WATER_NOT_REARMED"; return false; }
      double durable_after=0.0;
      bool durable_after_found=false;
      if(!m_database.LoadRiskHighWater("account_equity_peak",durable_after,
                                      durable_after_found,reason))
         return false;
      if(m_peak_equity+1e-8<peak_before || !durable_after_found ||
         durable_after+1e-8<peak_before)
        { reason="TEST_HOOK_RISK_HIGH_WATER_REGRESSED"; return false; }
      return true;
     }

   bool TestGatewayExerciseSupervisedRepromotion(string &reason)
     {
      reason="";
      if(!MQLInfoInteger(MQL_TESTER) || GOAT2_PHASE1_EXECUTION_CERTIFIED!=1)
        { reason="TEST_HOOK_CERTIFIED_TESTER_BUILD_REQUIRED"; return false; }
      if(m_operational_state!=V2_OP_NORMAL || !m_new_risk_enabled)
        { reason="TEST_HOOK_REPROMOTION_REQUIRES_NORMAL_START"; return false; }
      SetOperationalState(V2_OP_DEGRADED,
                          "BROKER_MATCH_RECHECK_REQUIRED:TEST_INJECTED_TRANSIENT");
      if(!m_supervised_repromotion_pending || m_healthy_recovery_passes!=0)
        { reason="TEST_HOOK_REPROMOTION_AUDIT_NOT_RESET"; return false; }
      for(int pass=1;pass<=3;pass++)
        {
         if(!Housekeeping(reason)) return false;
         if(pass<3 && (m_operational_state==V2_OP_NORMAL ||
                       m_healthy_recovery_passes!=pass))
           { reason="TEST_HOOK_REPROMOTED_BEFORE_THREE_PASSES"; return false; }
        }
      if(m_operational_state!=V2_OP_NORMAL || !m_new_risk_enabled ||
         m_supervised_repromotion_pending || m_healthy_recovery_passes!=0)
        { reason="TEST_HOOK_REPROMOTION_DID_NOT_COMPLETE"; return false; }
      return true;
     }

   bool TestGatewaySnapshot(V2GatewayIntegrationSnapshot &snapshot,string &reason)
     {
      snapshot.Reset();
      reason="";
      if(!MQLInfoInteger(MQL_TESTER))
        { reason="TEST_HOOK_REQUIRES_STRATEGY_TESTER"; return false; }
      snapshot.initialized=m_initialized;
      snapshot.recovery_verified=m_recovery_verified;
      snapshot.new_risk_enabled=m_new_risk_enabled;
      snapshot.pending_execution=m_pending.active;
      snapshot.operational_state=m_operational_state;
      snapshot.operational_reason=m_operational_reason;
      snapshot.sequence_id=m_sequence.sequence_id;
      snapshot.runtime_sequence_status=m_sequence.status;
      snapshot.runtime_standing_volume=m_sequence.standing_volume;

      V2OwnedPosition positions[];
      double vwap=0.0,floating=0.0;
      if(!ScanOwnedPositions(positions,snapshot.broker_standing_volume,vwap,floating,reason)) return false;
      snapshot.broker_position_count=ArraySize(positions);
      if(snapshot.sequence_id=="") return true;

      V2SequenceState persisted;
      persisted.Reset();
      if(!m_database.LoadSequenceProjection(snapshot.sequence_id,persisted,
                                            snapshot.persisted_projection_found,reason))
         return false;
      if(snapshot.persisted_projection_found)
        {
         snapshot.persisted_sequence_status=persisted.status;
         snapshot.persisted_standing_volume=persisted.standing_volume;
        }
      return true;
     }
#endif

   double TesterScore(void) const
     {
      const double profit=TesterStatistics(STAT_PROFIT);
      const double drawdown=MathMax(0.0,TesterStatistics(STAT_EQUITY_DD));
      const double trades=MathMax(0.0,TesterStatistics(STAT_TRADES));
      if(!MathIsValidNumber(profit) || !MathIsValidNumber(drawdown) || trades<=0.0) return 0.0;
      return profit/(1.0+drawdown)*MathLog(1.0+trades);
     }

   void Shutdown(const int reason)
     {
      if(!m_initialized)
        {
         m_overlay.Shutdown();
         m_hud.Shutdown();
         m_features.Shutdown();
         m_database.Close();
         return;
        }
      string reconcile_reason="";
      if(!m_database.IsReadOnlyRecovery() && V2_RunMode!=V2_RUN_DISABLED)
        {
         m_gateway.DrainTradeObservations(V2_MANAGER_OBSERVATION_BUDGET);
         ProcessTradeObservations(reconcile_reason);
        }
      RenderHud(true);
      m_overlay.Shutdown();
      m_hud.Shutdown();
      m_features.Shutdown();
      m_database.Close();
      m_initialized=false;
      Print("GOAT2|DEINIT|reason=",IntegerToString(reason),
            (reconcile_reason=="" ? "" : "|reconcile="+reconcile_reason));
     }

   ENUM_V2_OPERATIONAL_STATE OperationalState(void) const { return m_operational_state; }
   string LastReason(void) const { return m_last_reason; }
  };

#endif
