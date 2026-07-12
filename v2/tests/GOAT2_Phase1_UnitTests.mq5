#property copyright "GOATedge.ai"
#property version   "2.00"
#property strict
#property tester_no_cache

#include "../Domain.mqh"
#include "../Identity.mqh"
#include "../Inputs_V2.mqh"
#include "../SafetyKernel.mqh"
#include "../Core_Sequence.mqh"
#include "../Core_Risk.mqh"
#include "../StateDB.mqh"

int g_checks=0;
int g_passed=0;
int g_failed=0;

void Check(const bool condition,const string name,const string detail="")
  {
   g_checks++;
   if(condition)
     {
      g_passed++;
      Print("GOAT2_TEST|PASS|",name);
      return;
     }
   g_failed++;
   Print("GOAT2_TEST|FAIL|",name,(detail=="" ? "" : "|"+detail));
  }

bool Near(const double left,const double right,const double epsilon=1e-9)
  {
   return(MathIsValidNumber(left) && MathIsValidNumber(right) && MathAbs(left-right)<=epsilon);
  }

void MakeEvent(V2DomainEvent &event,
               const string event_id,
               const long canonical_number,
               const ENUM_V2_EVENT_KIND kind,
               const string sequence_id="seq_unit")
  {
   event.Reset();
   event.event_id=event_id;
   event.event_hash=event_id+"_hash";
   event.sequence_id=sequence_id;
   event.kind=kind;
   event.canonical_number=canonical_number;
   event.state_version=canonical_number;
   event.occurred_at=(datetime)((long)D'2026.01.01 00:00:00'+canonical_number);
  }

void TestDomainOrderingAndIdempotency(void)
  {
   CV2DomainMachine machine;
   V2SequenceState state;
   state.Reset();
   V2DomainEvent start;
   MakeEvent(start,"evt_start",1,V2_EVENT_SEQUENCE_STARTED);
   start.direction=V2_DIR_LONG;
   start.symbol="EURUSD";
   string reason="";
   bool ok=machine.Apply(start,state,reason);
   Check(ok && state.status==V2_SEQ_ACTIVE && state.last_event_number==1,
         "domain.start_from_idle",reason);

   long before_number=state.last_event_number;
   ok=machine.Apply(start,state,reason);
   Check(ok && state.last_event_number==before_number,
         "domain.duplicate_same_hash_idempotent",reason);

   V2DomainEvent conflict;
   MakeEvent(conflict,"evt_start",1,V2_EVENT_SEQUENCE_STARTED);
   conflict.event_hash="different_hash";
   conflict.direction=V2_DIR_LONG;
   conflict.symbol="EURUSD";
   ok=machine.Apply(conflict,state,reason);
   Check(!ok && reason=="EVENT_ID_HASH_CONFLICT" && state.last_event_number==1,
         "domain.duplicate_hash_conflict_rejected",reason);

   V2DomainEvent gap;
   MakeEvent(gap,"evt_gap",3,V2_EVENT_LEVEL_PLANNED);
   gap.level_index=0;
   gap.volume=0.10;
   gap.price=1.1000;
   ok=machine.Apply(gap,state,reason);
   Check(!ok && reason=="STATE_VERSION_NOT_CONTIGUOUS" && state.last_event_number==1,
         "domain.canonical_gap_rejected",reason);

   V2DomainEvent mismatch;
   MakeEvent(mismatch,"evt_mismatch",2,V2_EVENT_LEVEL_PLANNED,"seq_other");
   mismatch.level_index=0;
   mismatch.volume=0.10;
   mismatch.price=1.1000;
   ok=machine.Apply(mismatch,state,reason);
   Check(!ok && reason=="SEQUENCE_ID_MISMATCH" && state.last_event_number==1,
         "domain.sequence_identity_mismatch_rejected",reason);
  }

void TestDomainQuarantineReduction(void)
  {
   CV2DomainMachine machine;
   V2SequenceState state;
   state.Reset();
   V2DomainEvent event;
   string reason="";

   MakeEvent(event,"evt_q_start",1,V2_EVENT_SEQUENCE_STARTED);
   event.direction=V2_DIR_LONG;
   event.symbol="EURUSD";
   bool ok=machine.Apply(event,state,reason);
   Check(ok,"domain.quarantine_fixture_started",reason);

   MakeEvent(event,"evt_q_fill",2,V2_EVENT_FILL_COMPLETE);
   event.order_intent_id="int_open";
   event.risk_effect=V2_RISK_INCREASE;
   event.level_index=0;
   event.volume=0.20;
   event.price=1.1000;
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.standing_volume,0.20),"domain.open_fill_increases_standing",reason);

   MakeEvent(event,"evt_q_enter",3,V2_EVENT_RECOVERY_QUARANTINED);
   ok=machine.Apply(event,state,reason);
   Check(ok && state.status==V2_SEQ_QUARANTINED,"domain.enter_recovery_quarantine",reason);

   MakeEvent(event,"evt_q_add_blocked",4,V2_EVENT_ORDER_INTENT_CREATED);
   event.order_intent_id="int_add";
   event.action=V2_ACTION_ADD;
   event.risk_effect=V2_RISK_INCREASE;
   ok=machine.Apply(event,state,reason);
   Check(!ok && reason=="ONLY_RISK_DECREASE_ALLOWED" && state.last_event_number==3,
         "domain.quarantine_blocks_add",reason);

   MakeEvent(event,"evt_q_reduce_one",4,V2_EVENT_FILL_PARTIAL);
   event.order_intent_id="int_reduce";
   event.action=V2_ACTION_PARTIAL_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   event.volume=0.10;
   event.price=1.1010;
   event.realized_pl=1.25;
   ok=machine.Apply(event,state,reason);
   Check(ok && state.status==V2_SEQ_QUARANTINED && Near(state.standing_volume,0.10),
         "domain.quarantine_allows_partial_reduction",reason);

   MakeEvent(event,"evt_q_level_closed",5,V2_EVENT_LEVEL_CLOSED);
   event.action=V2_ACTION_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   ok=machine.Apply(event,state,reason);
   Check(ok,"domain.quarantine_allows_level_close",reason);

   MakeEvent(event,"evt_q_reduce_flat",6,V2_EVENT_FILL_COMPLETE);
   event.order_intent_id="int_close";
   event.action=V2_ACTION_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   event.volume=0.10;
   event.price=1.1020;
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.standing_volume,0.0),"domain.quarantine_can_flatten",reason);

   MakeEvent(event,"evt_q_end",7,V2_EVENT_SEQUENCE_ENDED);
   ok=machine.Apply(event,state,reason);
   Check(ok && state.status==V2_SEQ_ENDED,"domain.flat_quarantined_sequence_can_end",reason);

   MakeEvent(event,"evt_q_restart",8,V2_EVENT_SEQUENCE_STARTED);
   event.direction=V2_DIR_LONG;
   event.symbol="EURUSD";
   ok=machine.Apply(event,state,reason);
   Check(!ok && reason=="SEQUENCE_ALREADY_ACTIVE","domain.ended_aggregate_cannot_restart",reason);
  }

void TestOrderIntentTransitions(void)
  {
   CV2OrderIntentMachine machine;
   V2OrderIntent intent;
   intent.Reset();
   string reason="";
   bool ok=machine.Apply(V2_INTENT_SUBMITTED,intent,reason);
   Check(!ok && reason=="ILLEGAL_ORDER_INTENT_TRANSITION" && intent.status==V2_INTENT_PLANNED,
         "intent.submit_requires_persistence",reason);

   ok=machine.Apply(V2_INTENT_PERSISTED,intent,reason);
   Check(ok && intent.status==V2_INTENT_PERSISTED,"intent.planned_to_persisted",reason);
   ok=machine.Apply(V2_INTENT_SUBMITTED,intent,reason);
   Check(ok && intent.status==V2_INTENT_SUBMITTED,"intent.persisted_to_submitted",reason);
   ok=machine.Apply(V2_INTENT_PARTIAL,intent,reason);
   Check(ok && intent.status==V2_INTENT_PARTIAL,"intent.submitted_to_partial",reason);
   ok=machine.Apply(V2_INTENT_PARTIAL,intent,reason);
   Check(ok,"intent.repeated_partial_is_idempotent",reason);
   ok=machine.Apply(V2_INTENT_FILLED,intent,reason);
   Check(ok && intent.status==V2_INTENT_FILLED,"intent.partial_to_filled",reason);
   ok=machine.Apply(V2_INTENT_REJECTED,intent,reason);
   Check(!ok && reason=="ILLEGAL_ORDER_INTENT_TRANSITION" && intent.status==V2_INTENT_FILLED,
         "intent.filled_is_terminal",reason);

   V2OrderIntent unpersisted_reduction;
   unpersisted_reduction.Reset();
   unpersisted_reduction.action=V2_ACTION_CLOSE;
   unpersisted_reduction.risk_effect=V2_RISK_DECREASE;
   ok=machine.Apply(V2_INTENT_SUBMITTED,unpersisted_reduction,reason);
   Check(!ok && unpersisted_reduction.status==V2_INTENT_PLANNED,
         "intent.reduction_also_requires_durable_persistence",reason);
  }

void BaseLotConfig(V2LotPlanConfig &config,const ENUM_V2_LOT_PROGRESSION progression)
  {
   config.Reset();
   config.progression=progression;
   config.level_count=7;
   config.start_lots=0.10;
   config.lot_exponent=1.30;
   config.lot_factor=0.80;
   config.max_trade_multiple=5.0;
   config.max_cumulative_multiple=8.0;
   config.peak_position_percent=50.0;
   config.volume_min=0.01;
   config.volume_max=100.0;
   config.volume_step=0.01;
  }

string LotModeName(const int mode)
  {
   switch((ENUM_V2_LOT_PROGRESSION)mode)
     {
      case V2_LOT_START:                    return "start";
      case V2_LOT_LAST:                     return "last";
      case V2_LOT_CUMULATIVE:               return "cumulative";
      case V2_LOT_CUMULATIVE_FRONT_LOADED:  return "cumulative_front_loaded";
      case V2_LOT_PEAK:                     return "peak";
      case V2_LOT_CUMULATIVE_PARTIAL:       return "cumulative_partial";
      case V2_LOT_PEAK_SMART:               return "peak_smart";
     }
   return "unknown";
  }

void TestAllLotProgressions(void)
  {
   CV2V1CompatLotPlanner compatibility;
   CV2LotPlanner corrected;
   for(int mode=0;mode<=6;mode++)
     {
      V2LotPlanConfig config;
      BaseLotConfig(config,(ENUM_V2_LOT_PROGRESSION)mode);
      V2LotPlan v1_plan;
      bool ok=compatibility.Build(config,v1_plan);
      string label=LotModeName(mode);
      Check(ok && v1_plan.valid && ArraySize(v1_plan.raw_delta)==config.level_count,
            "lots."+label+".v1_compat_build",v1_plan.reason);

      V2LotPlan v2_plan;
      ok=corrected.Build(config,v2_plan);
      Check(ok && v2_plan.valid && ArraySize(v2_plan.normalized_delta)==config.level_count,
            "lots."+label+".corrected_build",v2_plan.reason);
      if(!ok) continue;

      bool invariant=true;
      double cap=config.start_lots*config.max_cumulative_multiple;
      double trade_cap=config.start_lots*config.max_trade_multiple;
      for(int level=0;level<config.level_count;level++)
        {
         double standing=v2_plan.cumulative_lots[level];
         double delta=v2_plan.normalized_delta[level];
         if(!MathIsValidNumber(standing) || !MathIsValidNumber(delta) ||
            standing<-1e-12 || standing>cap+1e-8 || delta>trade_cap+1e-8)
            invariant=false;
        }
      Check(invariant,"lots."+label+".post_rounding_caps");
     }

   V2LotPlanConfig partial_config;
   BaseLotConfig(partial_config,V2_LOT_CUMULATIVE_PARTIAL);
   double partial_next=corrected.NextCumulativePartial(partial_config,3,0.20);
   Check(MathIsValidNumber(partial_next) && partial_next<=0.50+1e-8,
         "lots.cumulative_partial.live_standing_recalculation");

   V2LotPlanConfig peak_config;
   BaseLotConfig(peak_config,V2_LOT_PEAK_SMART);
   V2LotPlan peak_plan;
   bool ok=corrected.Build(peak_config,peak_plan);
   double peak_next=(ok ? corrected.NextPeakSmart(peak_config,peak_plan,3,0.20) : 0.0);
   Check(ok && MathIsValidNumber(peak_next) && peak_next<=0.50+1e-8,
         "lots.peak_smart.live_target_delta",peak_plan.reason);
  }

void BaseGridConfig(V2GridPlanConfig &config)
  {
   config.Reset();
   config.level_count=7;
   config.grid_size=-3.0;
   config.grid_min=-1.0;
   config.grid_max=-15.0;
   config.grid_exponent=1.20;
   config.grid_factor=1.00;
   config.pip_size=0.0001;
   config.atr_price=0.0010;
   config.tick_size=0.00001;
  }

void TestGridGeometry(void)
  {
   CV2V1CompatGridPlanner compatibility;
   CV2GridPlanner corrected;
   V2GridPlanConfig config;
   BaseGridConfig(config);
   V2GridPlan plan;
   bool ok=compatibility.Build(config,plan);
   Check(ok && plan.valid && ArraySize(plan.step_distance)==7 && Near(plan.base_distance,0.0030),
         "grid.atr_negative_input_convention",plan.reason);

   V2GridPlanConfig zero_factor=config;
   zero_factor.grid_factor=0.0;
   ok=compatibility.Build(zero_factor,plan);
   Check(!ok && plan.reason=="GRID_FACTOR_ZERO_UNDEFINED_IN_V1_COMPAT",
         "grid.v1_zero_factor_rejected",plan.reason);
   ok=corrected.Build(zero_factor,plan);
   Check(ok && plan.valid,"grid.v2_zero_factor_has_defined_neutral_fallback",plan.reason);

   V2GridPlanConfig inverted=config;
   inverted.grid_min=-5.0;
   inverted.grid_max=-1.0;
   ok=corrected.Build(inverted,plan);
   Check(!ok && plan.reason=="GRID_BOUNDS_INVERTED","grid.inverted_bounds_rejected",plan.reason);

   V2GridPlanConfig zero_base=config;
   zero_base.grid_size=0.0;
   ok=corrected.Build(zero_base,plan);
   Check(!ok && plan.reason=="GRID_BASE_NOT_POSITIVE","grid.zero_base_rejected",plan.reason);
  }

void TestCompatibilityRiskPath(void)
  {
   V2LotPlanConfig lot_config;
   BaseLotConfig(lot_config,V2_LOT_START);
   CV2LotPlanner lot_planner;
   V2LotPlan lots;
   bool lot_ok=lot_planner.Build(lot_config,lots);

   V2GridPlanConfig grid_config;
   BaseGridConfig(grid_config);
   CV2GridPlanner grid_planner;
   V2GridPlan grid;
   bool grid_ok=grid_planner.Build(grid_config,grid);

   CV2V1CompatRiskEngine risk;
   V2V1CompatRiskResult result;
   bool ok=(lot_ok && grid_ok && risk.Evaluate(lots,grid,100000.0,result));
   bool monotonic=ok;
   for(int i=1;i<ArraySize(result.loss_path);i++)
      if(result.loss_path[i]+1e-9<result.loss_path[i-1]) monotonic=false;
   Check(ok && result.valid && result.maximum_loss>0.0,
         "risk.compatibility_path_evaluates",result.reason);
   Check(monotonic,"risk.adverse_path_is_monotonic",result.reason);
  }

void BuildSafetySymbol(V2SymbolSnapshot &symbol)
  {
   symbol.symbol="EURUSD";
   symbol.trade_mode=SYMBOL_TRADE_MODE_FULL;
   symbol.bid=1.1000;
   symbol.ask=1.1001;
   symbol.point=0.00001;
   symbol.tick_size=0.00001;
   symbol.volume_min=0.01;
   symbol.volume_max=100.0;
   symbol.volume_step=0.01;
   symbol.stops_level_points=0;
   symbol.freeze_level_points=0;
  }

void TestSafetyRiskClassification(void)
  {
   V2SafetyLimits limits;
   limits.max_spread_points=50.0;
   limits.additional_margin_buffer_pct=20.0;
   limits.max_sequence_loss=1000.0;
   limits.max_symbol_lots=10.0;
   limits.max_portfolio_lots=20.0;
   limits.equity_floor=0.0;
   limits.max_equity_drawdown_pct=20.0;
   limits.max_consecutive_broker_errors=5;
   CV2SafetyKernel kernel;
   string reason="";
   bool ok=kernel.Initialize(limits,reason);
   Check(ok,"safety.kernel_initializes",reason);

   V2SymbolSnapshot symbol;
   BuildSafetySymbol(symbol);
   V2BrokerAction action;
   ENUM_V2_RISK_EFFECT effect=V2_RISK_UNKNOWN;

   action.Reset(); action.action=V2_ACTION_OPEN;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_INCREASE,"safety.open_increases_risk",reason);

   action.Reset(); action.action=V2_ACTION_CLOSE; action.position_ticket=1; action.volume=0.10;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_DECREASE,"safety.close_decreases_risk",reason);

   action.Reset(); action.action=V2_ACTION_MODIFY; action.direction=V2_DIR_LONG;
   action.position_ticket=1; action.current_stop_loss=1.0900; action.stop_loss=1.0950;
   action.projected_loss_delta=-10.0;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_DECREASE,"safety.tighten_long_stop_decreases_risk",reason);

   action.stop_loss=1.0800; action.projected_loss_delta=10.0;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_INCREASE,"safety.loosen_long_stop_increases_risk",reason);

   action.Reset(); action.action=V2_ACTION_MODIFY; action.direction=V2_DIR_SHORT;
   action.position_ticket=2; action.current_stop_loss=1.1100; action.stop_loss=1.1050;
   action.projected_loss_delta=-10.0;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_DECREASE,"safety.tighten_short_stop_decreases_risk",reason);

   action.Reset(); action.action=V2_ACTION_MODIFY; action.direction=V2_DIR_LONG;
   action.position_ticket=1; action.take_profit=1.1050;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_DECREASE,"safety.add_long_profit_target_decreases_risk",reason);
   action.current_take_profit=1.1050; action.take_profit=1.1100;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_INCREASE,"safety.move_long_target_farther_increases_risk",reason);
   action.take_profit=0.0;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_INCREASE,"safety.remove_profit_target_increases_risk",reason);

   action.Reset(); action.action=V2_ACTION_CANCEL; action.order_ticket=3;
   action.cancels_protective_order=false;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_DECREASE,"safety.cancel_entry_decreases_risk",reason);
   action.cancels_protective_order=true;
   ok=kernel.Classify(action,symbol,effect,reason);
   Check(ok && effect==V2_RISK_INCREASE,"safety.cancel_protection_increases_risk",reason);

   V2SafetyContext context;
   context.symbol=symbol;
   context.account.margin_mode=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING;
   context.account.balance=100000.0;
   context.account.equity=100000.0;
   context.account.margin=0.0;
   context.account.free_margin=100000.0;
   context.account.peak_equity=100000.0;
   context.exposure.sequence_lots=0.20;
   context.exposure.symbol_lots=0.20;
   context.exposure.portfolio_lots=0.20;
   context.exposure.projected_sequence_loss=100.0;
   context.exposure.projected_portfolio_loss=100.0;
   context.operational_state=V2_OP_HALTED;
   context.database_healthy=false;
   context.writer_lease_held=false;
   context.new_risk_enabled=false;
   context.session_allows_new_risk=false;
   context.feed_allows_new_risk=false;
   context.license_allows_new_risk=false;
   context.order_check_ok=false;
   context.order_check_margin=0.0;
   context.order_check_margin_free=0.0;
   context.consecutive_broker_errors=99;

   action.Reset(); action.action=V2_ACTION_CLOSE; action.position_ticket=1;
   action.volume=0.10; action.direction=V2_DIR_LONG;
   V2SafetyDecision decision;
   ok=kernel.Evaluate(action,context,decision);
   Check(ok && decision.verdict==V2_KERNEL_ALLOW_REDUCE_ONLY,
         "safety.halted_state_preserves_reduction",decision.reason_code);

   action.Reset(); action.action=V2_ACTION_OPEN; action.volume=0.10;
   action.price=1.1001; action.direction=V2_DIR_LONG;
   context.operational_state=V2_OP_MANAGE_ONLY;
   ok=kernel.Evaluate(action,context,decision);
   Check(ok && decision.verdict==V2_KERNEL_HALT_NEW_RISK,
         "safety.manage_only_blocks_open",decision.reason_code);
  }

void TestDurableReductionMandate(void)
  {
   CV2DomainMachine machine;
   V2SequenceState state;
   state.Reset();
   V2DomainEvent event;
   string reason="";

   MakeEvent(event,"evt_mandate_start",1,V2_EVENT_SEQUENCE_STARTED,"seq_mandate");
   event.direction=V2_DIR_LONG;
   event.symbol="EURUSD";
   bool ok=machine.Apply(event,state,reason);
   Check(ok,"domain.mandate_fixture_started",reason);

   MakeEvent(event,"evt_mandate_open",2,V2_EVENT_FILL_COMPLETE,"seq_mandate");
   event.order_intent_id="int_mandate_open";
   event.risk_effect=V2_RISK_INCREASE;
   event.level_index=0;
   event.volume=1.00;
   event.price=1.1000;
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.standing_volume,1.00),"domain.mandate_fixture_filled",reason);

   MakeEvent(event,"evt_mandate_set",3,V2_EVENT_REDUCTION_MANDATED,"seq_mandate");
   event.action=V2_ACTION_PARTIAL_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   event.volume=0.60;
   event.retrace_advance=true;
   event.reason_code="UNIT_RETRACE_RELEASE";
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.reduction_remaining,0.60) && state.retrace_advance_pending,
         "domain.reduction_mandate_persisted",reason);

   MakeEvent(event,"evt_mandate_partial",4,V2_EVENT_FILL_PARTIAL,"seq_mandate");
   event.order_intent_id="int_mandate_close_a";
   event.action=V2_ACTION_PARTIAL_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   event.volume=0.25;
   event.price=1.1010;
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.reduction_remaining,0.35),"domain.reduction_fill_decrements_mandate",reason);

   MakeEvent(event,"evt_mandate_early_complete",5,V2_EVENT_REDUCTION_COMPLETED,"seq_mandate");
   event.risk_effect=V2_RISK_DECREASE;
   event.retrace_advance=true;
   ok=machine.Apply(event,state,reason);
   Check(!ok && reason=="REDUCTION_COMPLETION_VOLUME_REMAINS",
         "domain.premature_reduction_completion_rejected",reason);

   MakeEvent(event,"evt_mandate_final_fill",5,V2_EVENT_FILL_COMPLETE,"seq_mandate");
   event.order_intent_id="int_mandate_close_b";
   event.action=V2_ACTION_PARTIAL_CLOSE;
   event.risk_effect=V2_RISK_DECREASE;
   event.level_index=0;
   event.volume=0.35;
   event.price=1.1015;
   ok=machine.Apply(event,state,reason);
   Check(ok && Near(state.reduction_remaining,0.0),"domain.reduction_mandate_reaches_zero",reason);

   MakeEvent(event,"evt_mandate_wrong_completion",6,V2_EVENT_REDUCTION_COMPLETED,"seq_mandate");
   event.risk_effect=V2_RISK_DECREASE;
   event.retrace_advance=false;
   ok=machine.Apply(event,state,reason);
   Check(!ok && reason=="REDUCTION_COMPLETION_RETRACE_MISMATCH",
         "domain.retrace_obligation_cannot_be_dropped",reason);

   MakeEvent(event,"evt_mandate_complete",6,V2_EVENT_REDUCTION_COMPLETED,"seq_mandate");
   event.risk_effect=V2_RISK_DECREASE;
   event.retrace_advance=true;
   event.price=1.1020;
   ok=machine.Apply(event,state,reason);
   Check(ok && state.reduction_reason=="" && !state.retrace_advance_pending &&
         Near(state.retrace_price,1.1020),
         "domain.reduction_completion_atomically_advances_retrace",reason);
  }

void TestBasketAndRetraceGeometry(void)
  {
   CV2BasketPlanner basket_planner;
   V2BasketPlanConfig config;
   config.Reset();
   config.direction=V2_DIR_LONG;
   config.executed_level_count=2;
   config.maximum_level_count=7;
   config.lock_distance=0.0030;
   config.lock_flexibility=0.0;
   config.take_profit_distance=0.0060;
   config.stop_loss_distance=0.0100;
   config.trailing_distance=0.0005;
   config.tick_size=0.00001;
   double prices[2]={1.1000,1.0900};
   double volumes[2]={0.10,0.20};
   V2BasketPlan plan;
   bool ok=basket_planner.Build(config,prices,volumes,plan);
   const double expected_vwap=(1.1000*0.10+1.0900*0.20)/0.30;
   const double expected_factor=1.0-MathPow(2.0/7.0,2.0);
   Check(ok && plan.valid && Near(plan.standing_volume,0.30,1e-12) && Near(plan.entry_vwap,expected_vwap,1e-9),
         "basket.actual_fill_vwap",plan.reason);
   Check(ok && Near(plan.lock_factor,expected_factor,1e-12),
         "basket.v1_lock_flexibility_curve",plan.reason);
   Check(ok && plan.take_profit_price>plan.entry_vwap && plan.stop_loss_price<plan.entry_vwap,
         "basket.direction_parameterized_targets",plan.reason);

   double trailing=0.0;
   ok=basket_planner.NextTrailingStop(config,1.1000,1.1001,0.0002,1.0950,trailing);
   Check(ok && Near(trailing,1.0995,1e-9),"basket.trailing_is_legal_and_monotonic");
   double unchanged=0.0;
   ok=basket_planner.NextTrailingStop(config,1.0950,1.0951,0.0002,trailing,unchanged);
   Check(!ok && unchanged==0.0,"basket.trailing_never_loosens");

   CV2RetracePlanner retrace;
   double levels[3]={1.1000,1.0900,1.0800};
   Check(retrace.Crossed(V2_DIR_LONG,1.0810,1.0800),"retrace.long_cross_detected");
   const double next=retrace.FindNext(V2_DIR_LONG,1.0800,levels,0.000001);
   Check(Near(next,1.0900,1e-9),"retrace.next_level_moves_toward_profit");
   const double partial=retrace.CumulativePartialClose(1.00,10.0,0.01,100.0,0.01);
   Check(Near(partial,0.10,1e-12),"retrace.cumulative_partial_volume");
   const double smart=retrace.PeakSmartClose(1.00,0.60,25.0,50.0,30.0,0.01,100.0,0.01);
   Check(Near(smart,0.20,1e-12),"retrace.peak_smart_excess_and_cap");
   Check(retrace.PeakSmartClose(1.00,0.60,-1.0,50.0,30.0,0.01,100.0,0.01)==0.0,
         "retrace.peak_smart_requires_profit");
  }

void TestIdentityAndMagic(void)
  {
   CV2Identity first;
   CV2Identity same;
   CV2Identity other;
   string reason="";
   bool ok_first=first.Initialize("unit-deployment","generation-1","member-a",reason);
   bool ok_same=same.Initialize("unit-deployment","generation-1","member-a",reason);
   bool ok_other=other.Initialize("unit-deployment","generation-1","member-b",reason);
   Check(ok_first && ok_same && ok_other,"identity.initialization",reason);
   Check(first.DeploymentId()==same.DeploymentId() && first.MemberId()==same.MemberId() && first.Magic()==same.Magic(),
         "identity.same_material_is_deterministic");
   Check(first.MemberId()!=other.MemberId() && first.Magic()!=other.Magic(),
         "identity.member_separation");
   Check(first.Magic()>0 && first.Magic()<=0x001FFFFFFFFFFFFF,
         "identity.magic_within_53_bits");
   Check(first.MagicTransport()==StringFormat("%I64u",first.Magic()),
         "identity.magic_uses_decimal_string_transport");
   Check(first.MagicCollides(first.Magic(),other.MemberId()) &&
         !first.MagicCollides(first.Magic(),first.MemberId()),
         "identity.magic_collision_detection");

   string sequence_one="",sequence_same="",sequence_two="";
   bool seq_one=first.SequenceId(V2_DIR_LONG,1,sequence_one);
   bool seq_same=first.SequenceId(V2_DIR_LONG,1,sequence_same);
   bool seq_two=first.SequenceId(V2_DIR_LONG,2,sequence_two);
   Check(seq_one && seq_same && sequence_one==sequence_same,
         "identity.sequence_reserved_ordinal_deterministic");
   Check(seq_two && sequence_one!=sequence_two,"identity.sequence_ordinal_unique");
   string invalid="";
   Check(!first.SequenceId(V2_DIR_LONG,0,invalid) && invalid=="",
         "identity.sequence_zero_ordinal_rejected");

   string intent_one="",intent_two="";
   bool int_one=first.OrderIntentId(sequence_one,V2_ACTION_OPEN,1,intent_one);
   bool int_two=first.OrderIntentId(sequence_one,V2_ACTION_OPEN,2,intent_two);
   Check(int_one && int_two && intent_one!=intent_two,
         "identity.intent_reserved_ordinal_unique");

   string event_one="",event_same="";
   bool evt_one=first.EventId("canonical-payload",event_one);
   bool evt_same=first.EventId("canonical-payload",event_same);
   Check(evt_one && evt_same && event_one==event_same,
         "identity.canonical_event_id_deterministic");
  }

void TestDefaultInputContract(void)
  {
   string reason="";
   bool ok=V2ValidateInputs(reason);
   Check(ok,"inputs.default_contract_is_valid",reason);
   Check(V2_RunMode==V2_RUN_MANAGE_ONLY && !V2_EnableNewRisk,
         "inputs.new_risk_disabled_by_default");
   Check(V2_StateMode<=V2_STATE_SHADOW && V2_OnnxMode==V2_ONNX_DISABLED,
          "inputs.future_influence_modes_are_gated");
  }

void TestCertificationBookkeepingContract(void)
  {
   string reason="";
   bool ok=V2ValidateCertificationBookkeeping(true,V2_BOOKKEEPING_REDUCED,reason);
   Check(!ok && reason=="CERTIFICATION_REQUIRES_FULL_BOOKKEEPING",
         "certification.inputs_reject_explicit_reduced",reason);
   reason="";
   Check(V2ValidateCertificationBookkeeping(true,V2_BOOKKEEPING_AUTO,reason),
         "certification.inputs_allow_auto_resolution",reason);

   Check(V2ResolveStateDBModeForContext(V2_BOOKKEEPING_REDUCED,true,true,true)==V2_DB_FULL_MEMORY,
         "certification.reduced_request_resolves_full_in_tester");
   Check(V2ResolveStateDBModeForContext(V2_BOOKKEEPING_REDUCED,true,false,false)==V2_DB_FULL_DURABLE,
         "certification.reduced_request_resolves_full_durable_live");
   Check(V2ResolveStateDBModeForContext(V2_BOOKKEEPING_AUTO,false,true,true)==V2_DB_REDUCED,
         "certification.noncert_optimization_remains_reduced");

   reason="";
   Check(V2ValidateManifestBookkeeping(V2_BOOKKEEPING_FULL,"FULL_MEMORY",true,reason),
         "certification.manifest_accepts_full_memory",reason);
   reason="";
   ok=V2ValidateManifestBookkeeping(V2_BOOKKEEPING_REDUCED,"REDUCED_MEMORY",true,reason);
   Check(!ok && reason=="CERTIFICATION_REQUIRES_FULL_BOOKKEEPING",
         "certification.manifest_rejects_reduced_backend",reason);
   reason="";
   ok=V2ValidateManifestBookkeeping(V2_BOOKKEEPING_FULL,"REDUCED_MEMORY",true,reason);
   Check(!ok && reason=="MANIFEST_BOOKKEEPING_BACKEND_MISMATCH",
         "certification.manifest_rejects_false_full_claim",reason);
   reason="";
   ok=V2ValidateManifestBookkeeping(V2_BOOKKEEPING_AUTO,"FULL_MEMORY",true,reason);
   Check(!ok && reason=="MANIFEST_BOOKKEEPING_UNRESOLVED",
         "certification.manifest_rejects_unresolved_mode",reason);

   CV2Identity identity;
   reason="";
   bool identity_ok=identity.Initialize("unit-certification","generation-1","member-a",reason);
   Check(identity_ok,"certification.manifest_test_identity",reason);
   if(!identity_ok) return;

   CV2ExperimentManifest builder;
   V2ExperimentManifest manifest;
   reason="";
   ok=builder.CaptureRuntime(identity,"2.0","unit-build",V2_MANIFEST_DEVELOPMENT,
                             V2_BOOKKEEPING_AUTO,"REDUCED_MEMORY",manifest,reason);
   Check(ok && manifest.bookkeeping_mode==V2_BOOKKEEPING_REDUCED &&
         manifest.persistence_backend=="REDUCED_MEMORY",
         "certification.capture_records_actual_reduced_backend",reason);

   reason="";
   ok=builder.CaptureRuntime(identity,"2.0","unit-build",V2_MANIFEST_DEVELOPMENT,
                             V2_BOOKKEEPING_FULL,"REDUCED_MEMORY",manifest,reason);
   Check(!ok && reason=="MANIFEST_BOOKKEEPING_BACKEND_MISMATCH",
         "certification.capture_rejects_backend_misstatement",reason);

   reason="";
   ok=builder.CaptureRuntime(identity,"2.0","unit-build",V2_MANIFEST_CERTIFICATION,
                             V2_BOOKKEEPING_AUTO,"REDUCED_MEMORY",manifest,reason);
   Check(!ok && reason=="CERTIFICATION_REQUIRES_FULL_BOOKKEEPING",
         "certification.capture_never_upgrades_reduced_to_full",reason);

   manifest.Reset();
   manifest.manifest_class=V2_MANIFEST_CERTIFICATION;
   manifest.bookkeeping_mode=V2_BOOKKEEPING_FULL;
   manifest.persistence_backend="REDUCED_MEMORY";
   reason="";
   ok=builder.ValidateForCertification(manifest,reason);
   Check(!ok && reason=="MANIFEST_BOOKKEEPING_BACKEND_MISMATCH",
         "certification.validator_cross_checks_backend",reason);
  }

void WriteSummary(void)
  {
   FolderCreate("GOAT2",FILE_COMMON);
   FolderCreate("GOAT2\\tests",FILE_COMMON);
   int handle=FileOpen("GOAT2\\tests\\phase1-unit-result.json",
                       FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle!=INVALID_HANDLE)
     {
      string status=(g_failed==0 ? "PASS" : "FAIL");
      string json=StringFormat("{\"schemaVersion\":\"goat2-phase1-unit-result-v1\",\"status\":\"%s\",\"checks\":%d,\"passed\":%d,\"failed\":%d,\"symbol\":\"%s\"}\n",
                               status,g_checks,g_passed,g_failed,_Symbol);
      FileWriteString(handle,json);
      FileClose(handle);
     }
   else
      Print("GOAT2_TEST|WARN|summary_file_open_failed|",GetLastError());
   PrintFormat("GOAT2_PHASE1_TEST_SUMMARY|checks=%d|passed=%d|failed=%d",g_checks,g_passed,g_failed);
  }

int OnInit(void)
  {
   TestDomainOrderingAndIdempotency();
   TestDomainQuarantineReduction();
   TestDurableReductionMandate();
   TestOrderIntentTransitions();
   TestAllLotProgressions();
   TestGridGeometry();
   TestCompatibilityRiskPath();
   TestSafetyRiskClassification();
   TestBasketAndRetraceGeometry();
   TestIdentityAndMagic();
   TestDefaultInputContract();
   TestCertificationBookkeepingContract();
   WriteSummary();
   return(g_failed==0 ? INIT_SUCCEEDED : INIT_FAILED);
  }

void OnTick(void)
  {
  }
