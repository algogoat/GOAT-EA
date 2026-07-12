#ifndef GOAT_V2_CORE_RISK_MQH
#define GOAT_V2_CORE_RISK_MQH

#include "Core_Sequence.mqh"

// Risk calculation is split deliberately:
//  * CV2V1CompatRiskEngine reproduces V1.42's cost-free planned-loss path.
//  * CV2CostRiskEngine is the V2 account-currency model and uses
//    OrderCalcProfit plus a pinned, versioned broker-cost profile.
// Neither engine sends, modifies, or closes an order.

struct V2V1CompatRiskResult
  {
   bool   valid;
   string reason;
   double maximum_loss;
   int    maximum_loss_step;
   double loss_path[];

   void Reset(void)
     {
      valid=false;
      reason="";
      maximum_loss=0.0;
      maximum_loss_step=0;
      ArrayResize(loss_path,0);
     }
  };

class CV2V1CompatRiskEngine
  {
public:
   bool Evaluate(const V2LotPlan &lots,
                 const V2GridPlan &grid,
                 const double price_value_per_price_unit_per_lot,
                 V2V1CompatRiskResult &result) const
     {
      result.Reset();
      if(!lots.valid) { result.reason="V1_RISK_LOT_PLAN_INVALID"; return false; }
      if(!grid.valid) { result.reason="V1_RISK_GRID_PLAN_INVALID"; return false; }
      if(price_value_per_price_unit_per_lot<=0.0 ||
         !MathIsValidNumber(price_value_per_price_unit_per_lot))
        {
         result.reason="V1_RISK_PRICE_VALUE_INVALID";
         return false;
        }

      int count=MathMin(ArraySize(lots.cumulative_lots),ArraySize(grid.cumulative_distance));
      if(count<1)
        {
         result.reason="V1_RISK_EMPTY_PATH";
         return false;
        }
      ArrayResize(result.loss_path,count);
      ArrayInitialize(result.loss_path,0.0);

      double loss=0.0;
      for(int level=1;level<count;level++)
        {
         double distance=grid.cumulative_distance[level]-grid.cumulative_distance[level-1];
         double standing=MathMax(0.0,lots.cumulative_lots[level-1]);
         loss+=distance*price_value_per_price_unit_per_lot*standing;
         if(!MathIsValidNumber(loss))
           {
            result.reason="V1_RISK_NONFINITE_PATH";
            return false;
           }
         result.loss_path[level]=loss;
         if(loss>result.maximum_loss)
           {
            result.maximum_loss=loss;
            result.maximum_loss_step=level;
           }
        }
      result.valid=true;
      return true;
     }

   bool SolveStartLots(const double target_loss,
                       const V2LotPlanConfig &source_config,
                       const V2GridPlan &grid,
                       const double price_value_per_price_unit_per_lot,
                       double &start_lots,
                       V2V1CompatRiskResult &result,
                       string &reason) const
     {
      reason="";
      start_lots=0.0;
      result.Reset();
      if(target_loss<=0.0) { reason="V1_RISK_TARGET_NOT_POSITIVE"; return false; }
      if(source_config.volume_step<=0.0 || source_config.volume_max<source_config.volume_min)
        {
         reason="V1_RISK_VOLUME_SPEC_INVALID";
         return false;
        }

      CV2V1CompatLotPlanner planner;
      int low=0;
      int high=(int)MathFloor((source_config.volume_max-source_config.volume_min)/source_config.volume_step+1e-9);
      int best_index=0;
      double best_error=DBL_MAX;

      for(int iteration=0;iteration<40 && low<=high;iteration++)
        {
         int middle=(low+high)/2;
         int candidates[3];
         candidates[0]=MathMax(low,middle-1);
         candidates[1]=middle;
         candidates[2]=MathMin(high,middle+1);
         double middle_loss=0.0;
         bool middle_set=false;

         for(int i=0;i<3;i++)
           {
            V2LotPlanConfig config=source_config;
            double candidate=source_config.volume_min+candidates[i]*source_config.volume_step;
            config.start_lots=planner.NormalizeSigned(candidate,config);
            V2LotPlan plan;
            V2V1CompatRiskResult evaluation;
            if(!planner.Build(config,plan) ||
               !Evaluate(plan,grid,price_value_per_price_unit_per_lot,evaluation))
              {
               reason=(plan.reason!="" ? plan.reason : evaluation.reason);
               return false;
              }
            double error=MathAbs(evaluation.maximum_loss-target_loss);
            if(error<best_error)
              {
               best_error=error;
               best_index=candidates[i];
              }
            if(candidates[i]==middle)
              {
               middle_loss=evaluation.maximum_loss;
               middle_set=true;
              }
           }
         if(!middle_set) { reason="V1_RISK_SOLVER_MIDDLE_MISSING"; return false; }
         if(middle_loss>target_loss) high=middle-1;
         else                        low=middle+1;
         if(high-low<=0) break;
        }

      V2LotPlanConfig best_config=source_config;
      start_lots=planner.NormalizeSigned(source_config.volume_min+best_index*source_config.volume_step,best_config);
      best_config.start_lots=start_lots;
      V2LotPlan best_plan;
      if(!planner.Build(best_config,best_plan) ||
         !Evaluate(best_plan,grid,price_value_per_price_unit_per_lot,result))
        {
         reason=(best_plan.reason!="" ? best_plan.reason : result.reason);
         return false;
        }
      return true;
     }
  };

// All monetary fields are in account currency.  Swap rates are account
// currency per lot per ordinary swap day.  A triple-swap event contributes
// (triple_swap_multiplier-1) additional swap-day equivalents.
struct V2BrokerCostProfile
  {
   string profile_id;
   string profile_version;
   double commission_open_per_lot;
   double commission_close_per_lot;
   double swap_long_per_lot_day;
   double swap_short_per_lot_day;
   double projected_holding_days;
   int    projected_triple_swap_events;
   double triple_swap_multiplier;
   double stressed_spread_points;
   double open_slippage_points;
   double close_slippage_points;
   double terminal_adverse_points;
   bool   allow_positive_swap_credit;

   void Reset(void)
     {
      profile_id="";
      profile_version="";
      commission_open_per_lot=0.0;
      commission_close_per_lot=0.0;
      swap_long_per_lot_day=0.0;
      swap_short_per_lot_day=0.0;
      projected_holding_days=0.0;
      projected_triple_swap_events=0;
      triple_swap_multiplier=3.0;
      stressed_spread_points=0.0;
      open_slippage_points=0.0;
      close_slippage_points=0.0;
      terminal_adverse_points=0.0;
      allow_positive_swap_credit=false;
     }
  };

struct V2RiskMarketContext
  {
   string            symbol;
   ENUM_V2_DIRECTION direction;
   double            initial_bid;
   double            initial_ask;
   double            point_size;
   double            tick_size;
   double            accrued_sequence_swap;

   void Reset(void)
     {
      symbol="";
      direction=V2_DIR_NONE;
      initial_bid=0.0;
      initial_ask=0.0;
      point_size=0.0;
      tick_size=0.0;
      accrued_sequence_swap=0.0;
     }
  };

struct V2CostRiskResult
  {
   bool   valid;
   string reason;
   double maximum_loss;
   int    maximum_loss_step;
   bool   maximum_after_action;
   double net_pl_at_maximum;
   double price_at_maximum;
   double standing_lots_at_maximum;
   double realized_price_pl;
   double paid_commission;
   double projected_swap;
   double projected_close_commission_at_maximum;
   double loss_path[];
   double net_pl_path[];

   void Reset(void)
     {
      valid=false;
      reason="";
      maximum_loss=0.0;
      maximum_loss_step=0;
      maximum_after_action=false;
      net_pl_at_maximum=0.0;
      price_at_maximum=0.0;
      standing_lots_at_maximum=0.0;
      realized_price_pl=0.0;
      paid_commission=0.0;
      projected_swap=0.0;
      projected_close_commission_at_maximum=0.0;
      ArrayResize(loss_path,0);
      ArrayResize(net_pl_path,0);
     }
  };

class CV2CostRiskEngine
  {
private:
   bool Validate(const V2LotPlan &lots,
                 const V2GridPlan &grid,
                 const V2RiskMarketContext &market,
                 const V2BrokerCostProfile &profile,
                 string &reason) const
     {
      reason="";
      if(!lots.valid)                                      { reason="V2_RISK_LOT_PLAN_INVALID"; return false; }
      if(!grid.valid)                                      { reason="V2_RISK_GRID_PLAN_INVALID"; return false; }
      if(market.symbol=="")                                { reason="V2_RISK_SYMBOL_EMPTY"; return false; }
      if(market.direction!=V2_DIR_LONG && market.direction!=V2_DIR_SHORT)
                                                           { reason="V2_RISK_DIRECTION_INVALID"; return false; }
      if(market.initial_bid<=0.0 || market.initial_ask<=0.0 || market.initial_ask<market.initial_bid)
                                                           { reason="V2_RISK_QUOTE_INVALID"; return false; }
      if(market.point_size<=0.0 || market.tick_size<=0.0)  { reason="V2_RISK_PRICE_SPEC_INVALID"; return false; }
      if(profile.profile_id=="" || profile.profile_version=="")
                                                           { reason="V2_RISK_PROFILE_UNVERSIONED"; return false; }
      if(profile.commission_open_per_lot<0.0 || profile.commission_close_per_lot<0.0)
                                                           { reason="V2_RISK_COMMISSION_NEGATIVE"; return false; }
      if(profile.projected_holding_days<0.0 || profile.projected_triple_swap_events<0 || profile.triple_swap_multiplier<1.0)
                                                           { reason="V2_RISK_SWAP_HORIZON_INVALID"; return false; }
      if(profile.stressed_spread_points<0.0 || profile.open_slippage_points<0.0 ||
         profile.close_slippage_points<0.0 || profile.terminal_adverse_points<0.0)
                                                           { reason="V2_RISK_STRESS_INPUT_NEGATIVE"; return false; }
      if(ArraySize(lots.normalized_delta)!=ArraySize(grid.cumulative_distance))
                                                           { reason="V2_RISK_PATH_SIZE_MISMATCH"; return false; }
      return true;
     }

   double SnapPrice(const double price,const bool upward,const V2RiskMarketContext &market) const
     {
      if(market.tick_size<=0.0) return price;
      double steps=price/market.tick_size;
      double snapped=(upward ? MathCeil(steps-1e-12) : MathFloor(steps+1e-12))*market.tick_size;
      int digits=(int)SymbolInfoInteger(market.symbol,SYMBOL_DIGITS);
      return NormalizeDouble(snapped,digits);
     }

   bool CalculateProfit(const V2RiskMarketContext &market,
                        const double volume,
                        const double open_price,
                        const double close_price,
                        double &profit,
                        string &reason) const
     {
      profit=0.0;
      if(volume<=0.0) return true;
      ENUM_ORDER_TYPE order_type=(market.direction==V2_DIR_LONG ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
      ResetLastError();
      if(!OrderCalcProfit(order_type,market.symbol,volume,open_price,close_price,profit))
        {
         reason="ORDER_CALC_PROFIT_FAILED_"+IntegerToString(GetLastError());
         return false;
        }
      if(!MathIsValidNumber(profit))
        {
         reason="ORDER_CALC_PROFIT_NONFINITE";
         return false;
        }
      return true;
     }

   double Standing(double &open_lots[]) const
     {
      double total=0.0;
      for(int i=0;i<ArraySize(open_lots);i++) total+=MathMax(0.0,open_lots[i]);
      return total;
     }

   bool LiquidationNet(const V2RiskMarketContext &market,
                       const V2BrokerCostProfile &profile,
                       double &open_lots[],
                       double &open_prices[],
                       const double close_price,
                       const double realized_price_pl,
                       const double paid_commission,
                       const double projected_swap,
                       double &net_pl,
                       double &standing,
                       double &projected_close_commission,
                       string &reason) const
     {
      net_pl=realized_price_pl+market.accrued_sequence_swap+projected_swap-paid_commission;
      standing=0.0;
      for(int i=0;i<ArraySize(open_lots);i++)
        {
         if(open_lots[i]<=0.0) continue;
         double floating=0.0;
         if(!CalculateProfit(market,open_lots[i],open_prices[i],close_price,floating,reason)) return false;
         net_pl+=floating;
         standing+=open_lots[i];
        }
      projected_close_commission=standing*profile.commission_close_per_lot;
      net_pl-=projected_close_commission;
      return MathIsValidNumber(net_pl);
     }

   void Consider(const int step,
                 const bool after_action,
                 const double close_price,
                 const double net_pl,
                 const double standing,
                 const double close_commission,
                 V2CostRiskResult &result) const
     {
      double loss=MathMax(0.0,-net_pl);
      if(step>=0 && step<ArraySize(result.loss_path))
        {
         if(net_pl<result.net_pl_path[step])
           {
            result.loss_path[step]=loss;
            result.net_pl_path[step]=net_pl;
           }
        }
      bool first=(result.price_at_maximum<=0.0);
      bool greater_loss=(loss>result.maximum_loss+1e-12);
      bool equal_loss_worse_net=(MathAbs(loss-result.maximum_loss)<=1e-12 &&
                                 (first || net_pl<result.net_pl_at_maximum));
      if(greater_loss || equal_loss_worse_net)
        {
         result.maximum_loss=loss;
         result.maximum_loss_step=step;
         result.maximum_after_action=after_action;
         result.net_pl_at_maximum=net_pl;
         result.price_at_maximum=close_price;
         result.standing_lots_at_maximum=standing;
         result.projected_close_commission_at_maximum=close_commission;
        }
     }

public:
   bool Evaluate(const V2LotPlan &lots,
                 const V2GridPlan &grid,
                 const V2RiskMarketContext &market,
                 const V2BrokerCostProfile &profile,
                 V2CostRiskResult &result) const
     {
      result.Reset();
      if(!Validate(lots,grid,market,profile,result.reason)) return false;

      int count=ArraySize(lots.normalized_delta);
      ArrayResize(result.loss_path,count+1);
      ArrayResize(result.net_pl_path,count+1);
      ArrayInitialize(result.loss_path,0.0);
      ArrayInitialize(result.net_pl_path,DBL_MAX);

      double open_lots[];
      double open_prices[];
      ArrayResize(open_lots,count);
      ArrayResize(open_prices,count);
      ArrayInitialize(open_lots,0.0);
      ArrayInitialize(open_prices,0.0);

      double actual_spread=market.initial_ask-market.initial_bid;
      double stressed_spread=MathMax(actual_spread,profile.stressed_spread_points*market.point_size);
      double open_slippage=profile.open_slippage_points*market.point_size;
      double close_slippage=profile.close_slippage_points*market.point_size;
      double base_open_quote=(market.direction==V2_DIR_LONG ? market.initial_ask : market.initial_bid);
      double realized_price_pl=0.0;
      double paid_commission=0.0;
      double projected_swap=0.0;
      double swap_days=profile.projected_holding_days+
                       profile.projected_triple_swap_events*(profile.triple_swap_multiplier-1.0);
      double swap_rate=(market.direction==V2_DIR_LONG ? profile.swap_long_per_lot_day : profile.swap_short_per_lot_day);
      if(!profile.allow_positive_swap_credit && swap_rate>0.0) swap_rate=0.0;

      for(int level=0;level<count;level++)
        {
         double distance=grid.cumulative_distance[level];
         double level_open_quote=(market.direction==V2_DIR_LONG ? base_open_quote-distance : base_open_quote+distance);
         double close_price=(market.direction==V2_DIR_LONG ? level_open_quote-stressed_spread-close_slippage
                                                           : level_open_quote+stressed_spread+close_slippage);
         close_price=SnapPrice(close_price,market.direction==V2_DIR_SHORT,market);
         if(close_price<=0.0)
           {
            result.reason="V2_RISK_CLOSE_PRICE_NOT_POSITIVE";
            return false;
           }

         if(level>0)
           {
            double pre_net=0.0,pre_standing=0.0,pre_close_commission=0.0;
            if(!LiquidationNet(market,profile,open_lots,open_prices,close_price,
                               realized_price_pl,paid_commission,projected_swap,
                               pre_net,pre_standing,pre_close_commission,result.reason)) return false;
            Consider(level,false,close_price,pre_net,pre_standing,pre_close_commission,result);
           }

         double delta=lots.normalized_delta[level];
         if(delta>0.0)
           {
            double open_price=(market.direction==V2_DIR_LONG ? level_open_quote+open_slippage
                                                              : level_open_quote-open_slippage);
            open_price=SnapPrice(open_price,market.direction==V2_DIR_LONG,market);
            if(open_price<=0.0)
              {
               result.reason="V2_RISK_OPEN_PRICE_NOT_POSITIVE";
               return false;
              }
            open_lots[level]=delta;
            open_prices[level]=open_price;
            paid_commission+=delta*profile.commission_open_per_lot;
            projected_swap+=delta*swap_rate*swap_days;
           }
         else if(delta<0.0)
           {
            double before=Standing(open_lots);
            double reduction=MathMin(MathAbs(delta),before);
            if(reduction>0.0 && before>0.0)
              {
               // Corrected V2 uses proportional basket reduction.  This is
               // deterministic and keeps planned exposure separate from the
               // broker's ticket-selection mechanics.
               double ratio=reduction/before;
               for(int i=0;i<count;i++)
                 {
                  if(open_lots[i]<=0.0) continue;
                  double cut=open_lots[i]*ratio;
                  double close_profit=0.0;
                  if(!CalculateProfit(market,cut,open_prices[i],close_price,close_profit,result.reason)) return false;
                  realized_price_pl+=close_profit;
                  open_lots[i]=MathMax(0.0,open_lots[i]-cut);
                 }
               paid_commission+=reduction*profile.commission_close_per_lot;
              }
           }

         double post_net=0.0,post_standing=0.0,post_close_commission=0.0;
         if(!LiquidationNet(market,profile,open_lots,open_prices,close_price,
                            realized_price_pl,paid_commission,projected_swap,
                            post_net,post_standing,post_close_commission,result.reason)) return false;
         Consider(level,true,close_price,post_net,post_standing,post_close_commission,result);
        }

      if(profile.terminal_adverse_points>0.0)
        {
         double final_distance=grid.cumulative_distance[count-1]+profile.terminal_adverse_points*market.point_size;
         double terminal_open_quote=(market.direction==V2_DIR_LONG ? base_open_quote-final_distance : base_open_quote+final_distance);
         double terminal_close=(market.direction==V2_DIR_LONG ? terminal_open_quote-stressed_spread-close_slippage
                                                               : terminal_open_quote+stressed_spread+close_slippage);
         terminal_close=SnapPrice(terminal_close,market.direction==V2_DIR_SHORT,market);
         if(terminal_close<=0.0)
           {
            result.reason="V2_RISK_TERMINAL_PRICE_NOT_POSITIVE";
            return false;
           }
         double net=0.0,standing=0.0,close_commission=0.0;
         if(!LiquidationNet(market,profile,open_lots,open_prices,terminal_close,
                            realized_price_pl,paid_commission,projected_swap,
                            net,standing,close_commission,result.reason)) return false;
         Consider(count,false,terminal_close,net,standing,close_commission,result);
        }

      result.realized_price_pl=realized_price_pl;
      result.paid_commission=paid_commission;
      result.projected_swap=projected_swap;
      result.valid=true;
      return true;
     }

   // Corrected V2 solver returns the largest discrete starting volume whose
   // cost-complete worst path does not exceed target_loss.
   bool SolveStartLots(const double target_loss,
                       const V2LotPlanConfig &source_config,
                       const V2GridPlan &grid,
                       const V2RiskMarketContext &market,
                       const V2BrokerCostProfile &profile,
                       double &start_lots,
                       V2CostRiskResult &result,
                       string &reason) const
     {
      reason="";
      start_lots=0.0;
      result.Reset();
      if(target_loss<=0.0) { reason="V2_RISK_TARGET_NOT_POSITIVE"; return false; }
      if(source_config.volume_min<=0.0 || source_config.volume_step<=0.0 ||
         source_config.volume_max<source_config.volume_min)
        {
         reason="V2_RISK_VOLUME_SPEC_INVALID";
         return false;
        }

      int low=0;
      int high=(int)MathFloor((source_config.volume_max-source_config.volume_min)/source_config.volume_step+1e-9);
      int best_safe=-1;
      CV2LotPlanner planner;

      while(low<=high)
        {
         int middle=(low+high)/2;
         V2LotPlanConfig config=source_config;
         config.start_lots=source_config.volume_min+middle*source_config.volume_step;
         V2LotPlan plan;
         V2CostRiskResult evaluation;
         if(!planner.Build(config,plan) || !Evaluate(plan,grid,market,profile,evaluation))
           {
            reason=(plan.reason!="" ? plan.reason : evaluation.reason);
            return false;
           }
         if(evaluation.maximum_loss<=target_loss+1e-8)
           {
            best_safe=middle;
            low=middle+1;
           }
         else high=middle-1;
        }

      if(best_safe<0)
        {
         reason="V2_RISK_MINIMUM_VOLUME_EXCEEDS_BUDGET";
         return false;
        }

      V2LotPlanConfig best_config=source_config;
      best_config.start_lots=source_config.volume_min+best_safe*source_config.volume_step;
      V2LotPlan best_plan;
      if(!planner.Build(best_config,best_plan) || !Evaluate(best_plan,grid,market,profile,result))
        {
         reason=(best_plan.reason!="" ? best_plan.reason : result.reason);
         return false;
        }
      start_lots=best_config.start_lots;
      return true;
     }
  };

#endif
