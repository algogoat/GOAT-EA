#ifndef GOAT_V2_SAFETY_KERNEL_MQH
#define GOAT_V2_SAFETY_KERNEL_MQH

#include "Domain.mqh"

struct V2SafetyLimits
  {
   double max_spread_points;
   double additional_margin_buffer_pct;
   double max_sequence_loss;
   double max_symbol_lots;
   double max_portfolio_lots;
   double equity_floor;
   double max_equity_drawdown_pct;
   int    max_consecutive_broker_errors;
  };

struct V2AccountSnapshot
  {
   ENUM_ACCOUNT_MARGIN_MODE margin_mode;
   double balance;
   double equity;
   double margin;
   double free_margin;
   double peak_equity;
  };

struct V2SymbolSnapshot
  {
   string symbol;
   ENUM_SYMBOL_TRADE_MODE trade_mode;
   double bid;
   double ask;
   double point;
   double tick_size;
   double volume_min;
   double volume_max;
   double volume_step;
   int    stops_level_points;
   int    freeze_level_points;
  };

struct V2ExposureSnapshot
  {
   double sequence_lots;
   double symbol_lots;
   double portfolio_lots;
   double projected_sequence_loss;
   double projected_portfolio_loss;
  };

struct V2BrokerAction
  {
   string              order_intent_id;
   string              sequence_id;
   string              symbol;
   ENUM_V2_ACTION_KIND action;
   ENUM_V2_RISK_EFFECT risk_effect;
   ENUM_V2_DIRECTION   direction;
   ulong               magic;
   ulong               position_ticket;
   ulong               position_id;
   ulong               order_ticket;
   long                state_version;
   int                 level_index;
   double              volume;
   double              price;
   double              stop_loss;
   double              take_profit;
   double              current_stop_loss;
   double              current_take_profit;
   double              projected_loss_delta;
   bool                cancels_protective_order;
   string              reason_code;

   void Reset(void)
     {
      order_intent_id="";
      sequence_id="";
      symbol="";
      action=V2_ACTION_OPEN;
      risk_effect=V2_RISK_UNKNOWN;
      direction=V2_DIR_NONE;
      magic=0;
      position_ticket=0;
      position_id=0;
      order_ticket=0;
      state_version=0;
      level_index=-1;
      volume=0.0;
      price=0.0;
      stop_loss=0.0;
      take_profit=0.0;
      current_stop_loss=0.0;
      current_take_profit=0.0;
      projected_loss_delta=0.0;
      cancels_protective_order=false;
      reason_code="";
     }
  };

struct V2SafetyContext
  {
   V2AccountSnapshot          account;
   V2SymbolSnapshot           symbol;
   V2ExposureSnapshot         exposure;
   ENUM_V2_OPERATIONAL_STATE operational_state;
   bool                       database_healthy;
   bool                       writer_lease_held;
   bool                       new_risk_enabled;
   bool                       session_allows_new_risk;
   bool                       feed_allows_new_risk;
   bool                       license_allows_new_risk;
   bool                       order_check_ok;
   double                     order_check_margin;
   double                     order_check_margin_free;
   int                        consecutive_broker_errors;
  };

struct V2SafetyDecision
  {
   ENUM_V2_KERNEL_VERDICT verdict;
   ENUM_V2_RISK_EFFECT    risk_effect;
   string                 reason_code;
   double                 normalized_volume;
   double                 normalized_price;
   double                 normalized_stop_loss;
   double                 normalized_take_profit;

   void Reset(void)
     {
      verdict=V2_KERNEL_DENY;
      risk_effect=V2_RISK_UNKNOWN;
      reason_code="UNINITIALIZED";
      normalized_volume=0.0;
      normalized_price=0.0;
      normalized_stop_loss=0.0;
      normalized_take_profit=0.0;
     }
  };

class CV2SafetyKernel
  {
private:
   V2SafetyLimits m_limits;
   bool           m_initialized;

   double NormalizePrice(const double price,const double tick_size) const
     {
      if(price<=0.0 || tick_size<=0.0)
         return 0.0;
      return MathRound(price/tick_size)*tick_size;
     }

   double NormalizeVolumeDown(const double volume,const V2SymbolSnapshot &symbol) const
     {
      if(volume<=0.0 || symbol.volume_step<=0.0)
         return 0.0;
      double steps=MathFloor((volume+1e-12)/symbol.volume_step);
      double normalized=steps*symbol.volume_step;
      if(normalized<symbol.volume_min-1e-12)
         return 0.0;
      if(normalized>symbol.volume_max)
         normalized=MathFloor(symbol.volume_max/symbol.volume_step)*symbol.volume_step;
      return NormalizeDouble(normalized,8);
     }

   bool StopTightens(const V2BrokerAction &action,const V2SymbolSnapshot &symbol) const
     {
      if(action.position_ticket==0 || action.stop_loss<=0.0)
         return false;
      if(action.current_stop_loss<=0.0)
         return true;
      const double epsilon=MathMax(symbol.tick_size,1e-12)*0.5;
      if(action.direction==V2_DIR_LONG)
         return action.stop_loss>=action.current_stop_loss-epsilon;
      if(action.direction==V2_DIR_SHORT)
         return action.stop_loss<=action.current_stop_loss+epsilon;
      return false;
     }

   bool TargetTightens(const V2BrokerAction &action,const V2SymbolSnapshot &symbol) const
     {
      if(action.position_ticket==0 || action.take_profit<=0.0) return false;
      const double epsilon=MathMax(symbol.tick_size,1e-12)*0.5;
      if(action.direction==V2_DIR_LONG)
        {
         if(action.take_profit<=symbol.bid+epsilon) return false;
         return(action.current_take_profit<=0.0 || action.take_profit<=action.current_take_profit+epsilon);
        }
      if(action.direction==V2_DIR_SHORT)
        {
         if(action.take_profit>=symbol.ask-epsilon) return false;
         return(action.current_take_profit<=0.0 || action.take_profit>=action.current_take_profit-epsilon);
        }
      return false;
     }

public:
                     CV2SafetyKernel(void)
     {
      m_initialized=false;
     }

   bool Initialize(const V2SafetyLimits &limits,string &reason)
     {
      reason="";
      if(limits.max_spread_points<=0.0 ||
         limits.additional_margin_buffer_pct<0.0 ||
         limits.max_sequence_loss<=0.0 ||
         limits.max_symbol_lots<=0.0 ||
         limits.max_portfolio_lots<=0.0 ||
         limits.max_symbol_lots>limits.max_portfolio_lots ||
         limits.max_equity_drawdown_pct<=0.0 ||
         limits.max_equity_drawdown_pct>=100.0 ||
         limits.max_consecutive_broker_errors<1)
        {
         reason="SAFETY_LIMITS_INVALID";
         return false;
        }
      m_limits=limits;
      m_initialized=true;
      return true;
     }

   bool Classify(const V2BrokerAction &action,const V2SymbolSnapshot &symbol,ENUM_V2_RISK_EFFECT &effect,string &reason) const
     {
      reason="";
      effect=V2_RISK_UNKNOWN;
      switch(action.action)
        {
         case V2_ACTION_OPEN:
         case V2_ACTION_ADD:
            effect=V2_RISK_INCREASE;
            return true;

         case V2_ACTION_PARTIAL_CLOSE:
         case V2_ACTION_CLOSE:
            if(action.position_ticket==0 || action.volume<=0.0)
              {
               reason="CLOSE_TARGET_INVALID";
               return false;
              }
            effect=V2_RISK_DECREASE;
            return true;

         case V2_ACTION_MODIFY:
            {
             const double epsilon=MathMax(symbol.tick_size,1e-12)*0.5;
             const bool stop_removed=(action.current_stop_loss>0.0 && action.stop_loss<=0.0);
             const bool stop_changed=(MathAbs(action.stop_loss-action.current_stop_loss)>epsilon);
             const bool stop_tightens=StopTightens(action,symbol);
             const bool stop_loosens=(stop_changed && action.current_stop_loss>0.0 && action.stop_loss>0.0 && !stop_tightens);
             const bool target_removed=(action.current_take_profit>0.0 && action.take_profit<=0.0);
             const bool target_changed=(MathAbs(action.take_profit-action.current_take_profit)>epsilon);
             const bool target_tightens=TargetTightens(action,symbol);
             const bool target_moves_farther=(target_changed && action.current_take_profit>0.0 && action.take_profit>0.0 && !target_tightens);
             if(stop_removed || stop_loosens || target_removed || target_moves_farther || action.projected_loss_delta>0.0)
                effect=V2_RISK_INCREASE;
             else if(stop_tightens || target_tightens || action.projected_loss_delta<0.0)
                effect=V2_RISK_DECREASE;
             else
                effect=V2_RISK_NEUTRAL;
             return true;
            }

         case V2_ACTION_CANCEL:
            if(action.order_ticket==0)
              {
               reason="CANCEL_TARGET_INVALID";
               return false;
              }
            effect=(action.cancels_protective_order ? V2_RISK_INCREASE : V2_RISK_DECREASE);
            return true;
        }
      reason="ACTION_CLASSIFICATION_UNKNOWN";
      return false;
     }

   bool Evaluate(const V2BrokerAction &action,const V2SafetyContext &context,V2SafetyDecision &decision) const
     {
      decision.Reset();
      if(!m_initialized)
        {
         decision.reason_code="KERNEL_NOT_INITIALIZED";
         return false;
        }

      string classify_reason="";
      if(!Classify(action,context.symbol,decision.risk_effect,classify_reason))
        {
         decision.reason_code=classify_reason;
         return false;
        }

      decision.normalized_volume=NormalizeVolumeDown(action.volume,context.symbol);
      decision.normalized_price=NormalizePrice(action.price,context.symbol.tick_size);
      decision.normalized_stop_loss=NormalizePrice(action.stop_loss,context.symbol.tick_size);
      decision.normalized_take_profit=NormalizePrice(action.take_profit,context.symbol.tick_size);

      if(action.action!=V2_ACTION_MODIFY && action.action!=V2_ACTION_CANCEL && decision.normalized_volume<=0.0)
        {
         decision.reason_code="NORMALIZED_VOLUME_INVALID";
         return false;
        }

      if(decision.risk_effect==V2_RISK_DECREASE)
        {
         decision.verdict=(context.operational_state==V2_OP_HALTED ? V2_KERNEL_ALLOW_REDUCE_ONLY : V2_KERNEL_ALLOW);
         decision.reason_code="RISK_REDUCTION_ALLOWED";
         return true;
        }

      if(decision.risk_effect==V2_RISK_UNKNOWN)
        {
         decision.reason_code="UNKNOWN_RISK_EFFECT";
         return false;
        }

      if(context.operational_state!=V2_OP_NORMAL)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="OPERATIONAL_STATE_BLOCKS_NEW_RISK";
         return true;
        }
      if(!context.new_risk_enabled)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="NEW_RISK_DISABLED";
         return true;
        }
      if(!context.database_healthy || !context.writer_lease_held)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="DURABILITY_OR_LEASE_UNAVAILABLE";
         return true;
        }
      if(context.account.margin_mode!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="ACCOUNT_MODE_NOT_HEDGING";
         return true;
        }
      if(!context.session_allows_new_risk || !context.feed_allows_new_risk || !context.license_allows_new_risk)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="NEW_RISK_PREREQUISITE_BLOCKED";
         return true;
        }
      if(context.symbol.trade_mode!=SYMBOL_TRADE_MODE_FULL && context.symbol.trade_mode!=SYMBOL_TRADE_MODE_LONGONLY && context.symbol.trade_mode!=SYMBOL_TRADE_MODE_SHORTONLY)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="SYMBOL_TRADE_MODE_BLOCKED";
         return true;
        }
      if(action.direction==V2_DIR_LONG && context.symbol.trade_mode==SYMBOL_TRADE_MODE_SHORTONLY)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="SYMBOL_LONG_NOT_ALLOWED";
         return true;
        }
      if(action.direction==V2_DIR_SHORT && context.symbol.trade_mode==SYMBOL_TRADE_MODE_LONGONLY)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="SYMBOL_SHORT_NOT_ALLOWED";
         return true;
        }
      double spread_points=(context.symbol.point>0.0 ? (context.symbol.ask-context.symbol.bid)/context.symbol.point : DBL_MAX);
      if(!MathIsValidNumber(spread_points) || spread_points>m_limits.max_spread_points)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="SPREAD_LIMIT";
         return true;
        }
      if(m_limits.equity_floor>0.0 && context.account.equity<m_limits.equity_floor)
        {
         decision.verdict=V2_KERNEL_FORCE_REDUCE;
         decision.reason_code="EQUITY_FLOOR";
         return true;
        }
      if(context.account.peak_equity>0.0)
        {
         double drawdown_pct=100.0*(context.account.peak_equity-context.account.equity)/context.account.peak_equity;
         if(drawdown_pct>=m_limits.max_equity_drawdown_pct)
           {
            decision.verdict=V2_KERNEL_FORCE_REDUCE;
            decision.reason_code="EQUITY_DRAWDOWN_LIMIT";
            return true;
           }
        }
      if(context.exposure.projected_sequence_loss>m_limits.max_sequence_loss+1e-8)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="SEQUENCE_LOSS_LIMIT";
         return true;
        }
      if(context.exposure.symbol_lots+decision.normalized_volume>m_limits.max_symbol_lots+1e-12 ||
         context.exposure.portfolio_lots+decision.normalized_volume>m_limits.max_portfolio_lots+1e-12)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="EXPOSURE_LIMIT";
         return true;
        }
      if(context.consecutive_broker_errors>=m_limits.max_consecutive_broker_errors)
        {
         decision.verdict=V2_KERNEL_HALT_NEW_RISK;
         decision.reason_code="BROKER_ERROR_BUDGET";
         return true;
        }
      if(!context.order_check_ok)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="ORDER_CHECK_FAILED";
         return true;
        }
      double required_free=context.order_check_margin*(1.0+m_limits.additional_margin_buffer_pct/100.0);
      if(context.order_check_margin_free<required_free)
        {
         decision.verdict=V2_KERNEL_DENY;
         decision.reason_code="MARGIN_BUFFER";
         return true;
        }

      decision.verdict=V2_KERNEL_ALLOW;
      decision.reason_code="ALL_INVARIANTS_SATISFIED";
      return true;
     }
  };

#endif
