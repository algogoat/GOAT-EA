#ifndef GOAT_V2_CORE_SEQUENCE_MQH
#define GOAT_V2_CORE_SEQUENCE_MQH

#include "Domain.mqh"
#include "Inputs_V2.mqh"

// Pure sequence geometry.  This module deliberately contains no terminal
// trade mutation.  The V1 compatibility planners reproduce the selected
// V1.42 equations; the corrected planner applies post-rounding execution caps.

struct V2GridPlanConfig
  {
   int    level_count;
   double grid_size;
   double grid_min;
   double grid_max;
   double grid_exponent;
   double grid_factor;
   double pip_size;
   double atr_price;
   double tick_size;

   void Reset(void)
     {
      level_count=0;
      grid_size=0.0;
      grid_min=0.0;
      grid_max=0.0;
      grid_exponent=1.0;
      grid_factor=1.0;
      pip_size=0.0;
      atr_price=0.0;
      tick_size=0.0;
     }
  };

struct V2GridPlan
  {
   bool   valid;
   string reason;
   double base_distance;
   double minimum_distance;
   double maximum_distance;
   double step_distance[];
   double cumulative_distance[];

   void Reset(void)
     {
      valid=false;
      reason="";
      base_distance=0.0;
      minimum_distance=0.0;
      maximum_distance=0.0;
      ArrayResize(step_distance,0);
      ArrayResize(cumulative_distance,0);
     }
  };

class CV2V1CompatGridPlanner
  {
private:
   bool ResolveSignedDistance(const double configured,
                              const V2GridPlanConfig &config,
                              double &distance,
                              string &reason) const
     {
      distance=0.0;
      reason="";
      if(!MathIsValidNumber(configured) || !MathIsValidNumber(config.pip_size) ||
         !MathIsValidNumber(config.atr_price))
        {
         reason="GRID_NONFINITE_INPUT";
         return false;
        }
      if(configured>0.0)
        {
         if(config.pip_size<=0.0)
           {
            reason="GRID_PIP_SIZE_NOT_POSITIVE";
            return false;
           }
         distance=configured*config.pip_size;
        }
      else if(configured<0.0)
        {
         if(config.atr_price<=0.0)
           {
            reason="GRID_ATR_NOT_POSITIVE";
            return false;
           }
         distance=-configured*config.atr_price;
        }
      return MathIsValidNumber(distance);
     }

public:
   bool Build(const V2GridPlanConfig &config,V2GridPlan &plan) const
     {
      plan.Reset();
      if(config.level_count<1)
        {
         plan.reason="GRID_LEVEL_COUNT_RANGE";
         return false;
        }
      if(!MathIsValidNumber(config.grid_exponent) || !MathIsValidNumber(config.grid_factor))
        {
         plan.reason="GRID_SHAPE_NONFINITE";
         return false;
        }

      if(!ResolveSignedDistance(config.grid_size,config,plan.base_distance,plan.reason) ||
         plan.base_distance<=0.0)
        {
         if(plan.reason=="") plan.reason="GRID_BASE_NOT_POSITIVE";
         return false;
        }
      if(!ResolveSignedDistance(config.grid_min,config,plan.minimum_distance,plan.reason))
         return false;
      if(!ResolveSignedDistance(config.grid_max,config,plan.maximum_distance,plan.reason))
         return false;

      // A zero min/max is a caller-controlled disabled bound.  V1 normally
      // converts a disabled maximum to a very large value during OnInit.
      if(plan.minimum_distance<=0.0) plan.minimum_distance=0.0;
      if(plan.maximum_distance<=0.0) plan.maximum_distance=DBL_MAX;
      if(plan.maximum_distance<plan.minimum_distance)
        {
         plan.reason="GRID_BOUNDS_INVERTED";
         return false;
        }

      ArrayResize(plan.step_distance,config.level_count);
      ArrayResize(plan.cumulative_distance,config.level_count);
      ArrayInitialize(plan.step_distance,0.0);
      ArrayInitialize(plan.cumulative_distance,0.0);

      const int n=config.level_count;
      for(int level=1;level<n;level++)
        {
         double distance=plan.base_distance;
         // Exact V1.42 fallback: an invalid/non-positive exponent returns the
         // base grid immediately, before min/max clamping.
         if(config.grid_exponent>0.0)
           {
            double shaped=config.grid_exponent*config.grid_factor;
            if(MathAbs(shaped)<=1e-12)
              {
               plan.reason="GRID_FACTOR_ZERO_UNDEFINED_IN_V1_COMPAT";
               return false;
              }
            double w2=(double)level/(double)n;
            double w1=1.0-w2;
            double frequency=w1*(1.0/config.grid_exponent)+w2*(1.0/shaped);
            if(frequency<=1e-12 && frequency>=-1e-12)
               frequency=(frequency<0.0 ? -1e-12 : 1e-12);
            double effective_growth=1.0/frequency;
            distance=plan.base_distance*MathPow(effective_growth,level-1);
            distance=MathMax(distance,plan.minimum_distance);
            distance=MathMin(distance,plan.maximum_distance);
           }
         if(!MathIsValidNumber(distance) || distance<0.0)
           {
            plan.reason="GRID_DISTANCE_INVALID";
            return false;
           }
         plan.step_distance[level]=distance;
         plan.cumulative_distance[level]=plan.cumulative_distance[level-1]+distance;
        }

      plan.valid=true;
      return true;
     }
  };

// Corrected execution grid.  It preserves the V1 frequency-space geometry,
// but defines factor=0 as neutral (1.0) for the V2 input surface and snaps
// every distance upward to a tradable tick so risk is never understated.
class CV2GridPlanner
  {
private:
   double SnapUp(const double value,const double tick_size) const
     {
      if(tick_size<=0.0) return value;
      return MathCeil((value-1e-12)/tick_size)*tick_size;
     }

public:
   bool Build(const V2GridPlanConfig &source,V2GridPlan &plan) const
     {
      V2GridPlanConfig config=source;
      if(MathAbs(config.grid_factor)<=1e-12) config.grid_factor=1.0;

      CV2V1CompatGridPlanner compatibility;
      if(!compatibility.Build(config,plan)) return false;

      if(config.tick_size>0.0)
        {
         plan.base_distance=SnapUp(plan.base_distance,config.tick_size);
         plan.minimum_distance=SnapUp(plan.minimum_distance,config.tick_size);
         if(plan.maximum_distance<DBL_MAX/2.0)
            plan.maximum_distance=SnapUp(plan.maximum_distance,config.tick_size);
         ArrayInitialize(plan.cumulative_distance,0.0);
         for(int level=1;level<ArraySize(plan.step_distance);level++)
           {
            plan.step_distance[level]=SnapUp(plan.step_distance[level],config.tick_size);
            plan.cumulative_distance[level]=plan.cumulative_distance[level-1]+plan.step_distance[level];
           }
        }
      return true;
     }
  };

struct V2LotPlanConfig
  {
   ENUM_V2_LOT_PROGRESSION progression;
   int    level_count;
   double start_lots;
   double lot_exponent;
   double lot_factor;
   double max_trade_multiple;
   double max_cumulative_multiple;
   double peak_position_percent;
   double volume_min;
   double volume_max;
   double volume_step;

   void Reset(void)
     {
      progression=V2_LOT_START;
      level_count=0;
      start_lots=0.0;
      lot_exponent=1.0;
      lot_factor=1.0;
      max_trade_multiple=0.0;
      max_cumulative_multiple=0.0;
      peak_position_percent=50.0;
      volume_min=0.0;
      volume_max=0.0;
      volume_step=0.0;
     }
  };

struct V2LotPlan
  {
   bool   valid;
   string reason;
   double peak_raw_cumulative;
   double peak_cumulative;
   double scale_factor;
   double raw_delta[];
   double normalized_delta[];
   double cumulative_lots[];

   void Reset(void)
     {
      valid=false;
      reason="";
      peak_raw_cumulative=0.0;
      peak_cumulative=0.0;
      scale_factor=1.0;
      ArrayResize(raw_delta,0);
      ArrayResize(normalized_delta,0);
      ArrayResize(cumulative_lots,0);
     }
  };

class CV2V1CompatLotPlanner
  {
private:
   bool Validate(const V2LotPlanConfig &config,string &reason) const
     {
      reason="";
      if(config.level_count<1)                         { reason="LOT_LEVEL_COUNT_RANGE"; return false; }
      if(config.start_lots<=0.0)                       { reason="LOT_START_NOT_POSITIVE"; return false; }
      if(config.volume_min<=0.0)                       { reason="LOT_VOLUME_MIN_NOT_POSITIVE"; return false; }
      if(config.volume_max<config.volume_min)          { reason="LOT_VOLUME_MAX_RANGE"; return false; }
      if(config.volume_step<=0.0)                      { reason="LOT_VOLUME_STEP_NOT_POSITIVE"; return false; }
      if(config.max_cumulative_multiple<=0.0)          { reason="LOT_CUMULATIVE_CAP_NOT_POSITIVE"; return false; }
      if(config.peak_position_percent<0.0 || config.peak_position_percent>100.0)
                                                        { reason="LOT_PEAK_PERCENT_RANGE"; return false; }
      if(!MathIsValidNumber(config.lot_exponent) || !MathIsValidNumber(config.lot_factor))
                                                        { reason="LOT_SHAPE_NONFINITE"; return false; }
      return true;
     }

   double Hermite(const double h,const double left_value,const double left_slope,
                  const double right_value,const double right_slope,const double span) const
     {
      double h2=h*h;
      double h3=h2*h;
      double h00= 2.0*h3-3.0*h2+1.0;
      double h10=     h3-2.0*h2+h;
      double h01=-2.0*h3+3.0*h2;
      double h11=     h3-    h2;
      return h00*left_value+h10*(span*left_slope)+h01*right_value+h11*(span*right_slope);
     }

public:
   double NormalizeSigned(const double raw_volume,const V2LotPlanConfig &config) const
     {
      if(config.volume_step<=0.0 || config.volume_max<=0.0) return 0.0;
      double steps=MathRound(raw_volume/config.volume_step);
      double lots=steps*config.volume_step;
      if(MathAbs(lots)<config.volume_min) lots=0.0;
      if(lots>=0.0) lots=MathMin(lots,config.volume_max);
      else          lots=-MathMin(MathAbs(lots),config.volume_max);
      return lots;
     }

   bool Build(const V2LotPlanConfig &config,V2LotPlan &plan) const
     {
      plan.Reset();
      if(!Validate(config,plan.reason)) return false;

      const int n=config.level_count;
      ArrayResize(plan.raw_delta,n);
      ArrayResize(plan.normalized_delta,n);
      ArrayResize(plan.cumulative_lots,n);
      ArrayInitialize(plan.raw_delta,0.0);
      ArrayInitialize(plan.normalized_delta,0.0);
      ArrayInitialize(plan.cumulative_lots,0.0);

      double cumulative=0.0;
      for(int level=0;level<n;level++)
        {
         double w2=(double)level/(double)n;
         double w1=1.0-w2;
         double delta=0.0;

         if(level==0)
           {
            plan.raw_delta[level]=config.start_lots;
            double effective0=w1*config.lot_exponent+w2*config.lot_exponent*config.lot_factor;
            if(config.progression==V2_LOT_CUMULATIVE_FRONT_LOADED && effective0>1.0+1e-9)
               cumulative=config.start_lots/(1.0-1.0/effective0);
            else
               cumulative=config.start_lots;
            continue;
           }

         switch(config.progression)
           {
            case V2_LOT_START:
               delta=config.start_lots*(w1*config.lot_exponent+w2*config.lot_exponent*config.lot_factor);
               break;

            case V2_LOT_LAST:
              {
               double shaped=config.lot_exponent*config.lot_factor;
               double first=config.start_lots*w1*MathPow(config.lot_exponent,level);
               double second=config.start_lots*w2*MathPow(MathAbs(shaped),level);
               delta=(shaped<0.0 ? first-second : first+second);
               break;
              }

            case V2_LOT_CUMULATIVE:
            case V2_LOT_CUMULATIVE_PARTIAL:
            case V2_LOT_CUMULATIVE_FRONT_LOADED:
              {
               double effective=w1*config.lot_exponent+w2*config.lot_exponent*config.lot_factor;
               delta=cumulative*(effective-1.0);
               cumulative+=delta;
               if(cumulative<0.0) cumulative=0.0;
               break;
              }

            case V2_LOT_PEAK:
            case V2_LOT_PEAK_SMART:
              {
               int pivot=(int)MathRound(n*config.peak_position_percent/100.0);
               if(pivot<1) pivot=1;
               if(pivot>n-1) pivot=n-1;

               double start_cumulative=config.start_lots;
               double peak_cumulative=config.start_lots*config.max_cumulative_multiple;
               double shape_up=MathMax(0.01,MathMin(5.0,config.lot_exponent));
               double shape_down=MathMax(0.01,MathMin(5.0,config.lot_factor));
               double t=(n>1 ? (double)level/(double)(n-1) : 0.0);
               double peak_t=(n>1 ? (double)pivot/(double)(n-1) : 0.5);
               double up_span=(peak_t>1e-9 ? peak_t : 1.0);
               double down_span=((1.0-peak_t)>1e-9 ? 1.0-peak_t : 1.0);
               double slope_start=shape_up*(peak_cumulative-start_cumulative)/up_span;
               double slope_end=-shape_down*peak_cumulative/down_span;
               double target=0.0;

               if(t<=peak_t || n<=2)
                 {
                  if(peak_t<1e-12) target=peak_cumulative;
                  else
                    {
                     double h=MathMax(0.0,MathMin(1.0,t/peak_t));
                     target=Hermite(h,start_cumulative,slope_start,peak_cumulative,0.0,peak_t);
                    }
                 }
               else
                 {
                  double span=1.0-peak_t;
                  if(span<1e-12) target=0.0;
                  else
                    {
                     double h=MathMax(0.0,MathMin(1.0,(t-peak_t)/span));
                     target=Hermite(h,peak_cumulative,0.0,0.0,slope_end,span);
                    }
                 }

               if(level==pivot) target=peak_cumulative;
               if(level==n-1)   target=0.0;
               delta=target-cumulative;
               cumulative+=delta;
               if(level==pivot)
                 {
                  double error=peak_cumulative-cumulative;
                  if(MathAbs(error)>1e-6) { delta+=error; cumulative=peak_cumulative; }
                 }
               if(level==n-1)
                 {
                  double error=-cumulative;
                  if(MathAbs(error)>1e-6) { delta+=error; cumulative=0.0; }
                 }
               break;
              }
           }
         plan.raw_delta[level]=delta;
        }

      // Exact V1.42 cumulative rescale: level zero is never scaled.
      double raw_cumulative=0.0;
      double raw_peak=0.0;
      for(int level=0;level<n;level++)
        {
         raw_cumulative+=plan.raw_delta[level];
         if(raw_cumulative<0.0) raw_cumulative=0.0;
         if(raw_cumulative>raw_peak) raw_peak=raw_cumulative;
        }
      plan.peak_raw_cumulative=raw_peak;
      plan.scale_factor=1.0;
      double raw_cap=config.start_lots*config.max_cumulative_multiple;
      if(raw_peak>raw_cap) plan.scale_factor=raw_cap/raw_peak;
      for(int level=1;level<n;level++) plan.raw_delta[level]*=plan.scale_factor;

      double standing=0.0;
      for(int level=0;level<n;level++)
        {
         plan.normalized_delta[level]=NormalizeSigned(plan.raw_delta[level],config);
         standing+=plan.normalized_delta[level];
         if(standing<0.0) standing=0.0;
         plan.cumulative_lots[level]=standing;
         if(standing>plan.peak_cumulative) plan.peak_cumulative=standing;
        }

      plan.valid=true;
      return true;
     }

   double NextCumulativePartial(const V2LotPlanConfig &config,
                                const int current_level_count,
                                const double standing_lots) const
     {
      if(standing_lots<=0.0 || config.level_count<1) return 0.0;
      int level=MathMin(current_level_count,config.level_count-1);
      double w2=(double)level/(double)config.level_count;
      double w1=1.0-w2;
      double effective=w1*config.lot_exponent+w2*config.lot_exponent*config.lot_factor;
      double delta=standing_lots*(effective-1.0);
      if(delta>0.0)
        {
         double remaining=config.start_lots*config.max_cumulative_multiple-standing_lots;
         if(remaining<=0.0) return 0.0;
         delta=MathMin(delta,remaining);
         if(config.max_trade_multiple>0.01)
            delta=MathMin(delta,config.max_trade_multiple*config.start_lots);
        }
      return NormalizeSigned(delta,config);
     }

   double NextPeakSmart(const V2LotPlanConfig &config,
                        const V2LotPlan &target_plan,
                        const int current_level_count,
                        const double standing_lots) const
     {
      int count=ArraySize(target_plan.cumulative_lots);
      if(count<1) return 0.0;
      int index=MathMin(MathMax(current_level_count,0),count-1);
      double delta=target_plan.cumulative_lots[index]-MathMax(0.0,standing_lots);
      if(delta>0.0)
        {
         double remaining=config.start_lots*config.max_cumulative_multiple-standing_lots;
         if(remaining<=0.0) return 0.0;
         delta=MathMin(delta,remaining);
         if(config.max_trade_multiple>0.01)
            delta=MathMin(delta,config.max_trade_multiple*config.start_lots);
        }
      return NormalizeSigned(delta,config);
     }
  };

// Corrected V2 post-normalization cap pass.  V1 can exceed a configured cap
// by one or more volume steps after independent rounding; V2 may not.
class CV2LotPlanner
  {
private:
   double FloorPositive(const double value,const V2LotPlanConfig &config) const
     {
      if(value<config.volume_min || config.volume_step<=0.0) return 0.0;
      double lots=MathFloor((value+1e-12)/config.volume_step)*config.volume_step;
      if(lots<config.volume_min) return 0.0;
      return MathMin(lots,config.volume_max);
     }

   double CapDynamicDelta(const double proposed,
                          const double standing,
                          const V2LotPlanConfig &config) const
     {
      if(proposed>0.0)
        {
         const double trade_cap=(config.max_trade_multiple>0.0 ?
                                 config.start_lots*config.max_trade_multiple : config.volume_max);
         const double cumulative_cap=config.start_lots*config.max_cumulative_multiple;
         const double permitted=MathMin(MathMin(proposed,trade_cap),
                                        MathMax(0.0,cumulative_cap-standing));
         return FloorPositive(permitted,config);
        }
      if(proposed<0.0)
         return -FloorPositive(MathMin(MathAbs(proposed),standing),config);
      return 0.0;
     }

public:
   bool Build(const V2LotPlanConfig &config,V2LotPlan &plan) const
     {
      CV2V1CompatLotPlanner compatibility;
      if(!compatibility.Build(config,plan)) return false;

      double standing=0.0;
      double cumulative_cap=config.start_lots*config.max_cumulative_multiple;
      double trade_cap=(config.max_trade_multiple>0.0 ? config.start_lots*config.max_trade_multiple : config.volume_max);
      plan.peak_cumulative=0.0;

      for(int level=0;level<ArraySize(plan.normalized_delta);level++)
        {
         double delta=plan.normalized_delta[level];
         if(delta>0.0)
           {
            double permitted=MathMin(delta,trade_cap);
            permitted=MathMin(permitted,MathMax(0.0,cumulative_cap-standing));
            delta=FloorPositive(permitted,config);
           }
         else if(delta<0.0)
           {
            double reduction=FloorPositive(MathMin(MathAbs(delta),standing),config);
            delta=-reduction;
           }
         standing+=delta;
         if(standing<0.0) standing=0.0;
         plan.normalized_delta[level]=delta;
         plan.cumulative_lots[level]=standing;
         if(standing>plan.peak_cumulative) plan.peak_cumulative=standing;
        }
      return true;
     }

   double NextCumulativePartial(const V2LotPlanConfig &config,
                                const int current_level_count,
                                const double standing_lots) const
     {
      CV2V1CompatLotPlanner compatibility;
      return CapDynamicDelta(compatibility.NextCumulativePartial(config,current_level_count,standing_lots),
                             standing_lots,config);
     }

   double NextPeakSmart(const V2LotPlanConfig &config,
                        const V2LotPlan &target_plan,
                        const int current_level_count,
                        const double standing_lots) const
     {
      CV2V1CompatLotPlanner compatibility;
      return CapDynamicDelta(compatibility.NextPeakSmart(config,target_plan,current_level_count,standing_lots),
                             standing_lots,config);
     }
  };

// Pure basket-management geometry shared by the live manager and tester
// fixtures. Prices supplied here are reconciled broker fill prices, not
// requested prices, so exits remain anchored to actual standing exposure.
struct V2BasketPlanConfig
  {
   ENUM_V2_DIRECTION direction;
   int    executed_level_count;
   int    maximum_level_count;
   double lock_distance;
   double lock_flexibility;
   double take_profit_distance;
   double stop_loss_distance;
   double trailing_distance;
   double tick_size;

   void Reset(void)
     {
      direction=V2_DIR_NONE;
      executed_level_count=0;
      maximum_level_count=0;
      lock_distance=0.0;
      lock_flexibility=1.0;
      take_profit_distance=0.0;
      stop_loss_distance=0.0;
      trailing_distance=0.0;
      tick_size=0.0;
     }
  };

struct V2BasketPlan
  {
   bool   valid;
   string reason;
   double standing_volume;
   double entry_vwap;
   double lock_factor;
   double lock_price;
   double take_profit_price;
   double stop_loss_price;

   void Reset(void)
     {
      valid=false;
      reason="";
      standing_volume=0.0;
      entry_vwap=0.0;
      lock_factor=1.0;
      lock_price=0.0;
      take_profit_price=0.0;
      stop_loss_price=0.0;
     }
  };

class CV2BasketPlanner
  {
private:
   double SnapNearest(const double price,const double tick_size) const
     {
      if(price<=0.0 || tick_size<=0.0) return price;
      return MathRound(price/tick_size)*tick_size;
     }

   double SnapDown(const double price,const double tick_size) const
     {
      if(price<=0.0 || tick_size<=0.0) return price;
      return MathFloor((price+1e-12)/tick_size)*tick_size;
     }

   double SnapUp(const double price,const double tick_size) const
     {
      if(price<=0.0 || tick_size<=0.0) return price;
      return MathCeil((price-1e-12)/tick_size)*tick_size;
     }

public:
   bool Build(const V2BasketPlanConfig &config,
              double &fill_prices[],
              double &standing_volumes[],
              V2BasketPlan &plan) const
     {
      plan.Reset();
      if(config.direction==V2_DIR_NONE)
        { plan.reason="BASKET_DIRECTION_NONE"; return false; }
      if(config.maximum_level_count<1 || config.executed_level_count<0 ||
         config.executed_level_count>config.maximum_level_count)
        { plan.reason="BASKET_LEVEL_GEOMETRY_INVALID"; return false; }
      if(config.lock_flexibility<-1.0 || config.lock_flexibility>1.0 ||
         config.lock_distance<0.0 || config.take_profit_distance<0.0 ||
         config.stop_loss_distance<0.0 || config.trailing_distance<0.0)
        { plan.reason="BASKET_DISTANCE_OR_FLEXIBILITY_INVALID"; return false; }
      const int count=MathMin(ArraySize(fill_prices),ArraySize(standing_volumes));
      double weighted=0.0;
      for(int i=0;i<count;i++)
        {
         if(!MathIsValidNumber(fill_prices[i]) || !MathIsValidNumber(standing_volumes[i]) ||
            fill_prices[i]<=0.0 || standing_volumes[i]<0.0)
           { plan.reason="BASKET_FILL_INVALID"; return false; }
         if(standing_volumes[i]<=0.0) continue;
         weighted+=fill_prices[i]*standing_volumes[i];
         plan.standing_volume+=standing_volumes[i];
        }
      if(plan.standing_volume<=0.0)
        { plan.reason="BASKET_NO_STANDING_VOLUME"; return false; }
      plan.entry_vwap=weighted/plan.standing_volume;
      if(config.executed_level_count>0 && config.lock_flexibility<1.0)
        {
         const double ratio=(double)config.executed_level_count/(double)config.maximum_level_count;
         plan.lock_factor=1.0-(1.0-config.lock_flexibility)*ratio*ratio;
        }
      const double sign=(config.direction==V2_DIR_LONG ? 1.0 : -1.0);
      if(config.lock_distance>0.0)
         plan.lock_price=SnapNearest(plan.entry_vwap+sign*config.lock_distance*plan.lock_factor,config.tick_size);
      if(config.take_profit_distance>0.0)
         plan.take_profit_price=SnapNearest(plan.entry_vwap+sign*config.take_profit_distance,config.tick_size);
      if(config.stop_loss_distance>0.0)
         plan.stop_loss_price=SnapNearest(plan.entry_vwap-sign*config.stop_loss_distance,config.tick_size);
      plan.valid=true;
      return true;
     }

   bool NextTrailingStop(const V2BasketPlanConfig &config,
                         const double bid,
                         const double ask,
                         const double minimum_legal_distance,
                         const double current_stop,
                         double &next_stop) const
     {
      next_stop=0.0;
      if(config.direction==V2_DIR_NONE || config.trailing_distance<=0.0 ||
         config.tick_size<=0.0 || bid<=0.0 || ask<=0.0 || ask<bid || minimum_legal_distance<0.0)
         return false;
      if(config.direction==V2_DIR_LONG)
        {
         const double legal=bid-minimum_legal_distance;
         next_stop=SnapDown(MathMin(bid-config.trailing_distance,legal),config.tick_size);
         if(next_stop<=0.0 || (current_stop>0.0 && next_stop<=current_stop+config.tick_size*0.5))
           { next_stop=0.0; return false; }
        }
      else
        {
         const double legal=ask+minimum_legal_distance;
         next_stop=SnapUp(MathMax(ask+config.trailing_distance,legal),config.tick_size);
         if(next_stop<=0.0 || (current_stop>0.0 && next_stop>=current_stop-config.tick_size*0.5))
           { next_stop=0.0; return false; }
        }
      return true;
     }
  };

class CV2RetracePlanner
  {
private:
   double NormalizeDown(const double requested,const double minimum,const double maximum,const double step) const
     {
      if(requested<=0.0 || minimum<=0.0 || maximum<minimum || step<=0.0) return 0.0;
      double normalized=MathFloor((requested+1e-12)/step)*step;
      normalized=MathMin(normalized,maximum);
      if(normalized<minimum-1e-12) return 0.0;
      return NormalizeDouble(normalized,8);
     }

public:
   bool Crossed(const ENUM_V2_DIRECTION direction,const double market_price,const double retrace_price) const
     {
      if(direction==V2_DIR_NONE || market_price<=0.0 || retrace_price<=0.0) return false;
      return(direction==V2_DIR_LONG ? market_price>=retrace_price : market_price<=retrace_price);
     }

   double FindNext(const ENUM_V2_DIRECTION direction,
                   const double from_price,
                   double &level_prices[],
                   const double epsilon) const
     {
      if(direction==V2_DIR_NONE || from_price<=0.0) return 0.0;
      double next=0.0;
      bool found=false;
      for(int i=0;i<ArraySize(level_prices);i++)
        {
         const double candidate=level_prices[i];
         if(candidate<=0.0) continue;
         if(direction==V2_DIR_LONG && candidate>from_price+epsilon && (!found || candidate<next))
           { next=candidate; found=true; }
         else if(direction==V2_DIR_SHORT && candidate<from_price-epsilon && (!found || candidate>next))
           { next=candidate; found=true; }
        }
      return(found ? next : 0.0);
     }

   double CumulativePartialClose(const double standing_volume,
                                 const double release_percent,
                                 const double volume_min,
                                 const double volume_max,
                                 const double volume_step) const
     {
      const double bounded=MathMax(0.0,MathMin(100.0,release_percent))*0.01;
      return NormalizeDown(MathMin(standing_volume,standing_volume*bounded),volume_min,volume_max,volume_step);
     }

   double PeakSmartClose(const double standing_volume,
                         const double planned_volume,
                         const double sequence_profit,
                         const double release_percent,
                         const double maximum_close_percent,
                         const double volume_min,
                         const double volume_max,
                         const double volume_step) const
     {
      if(sequence_profit<=0.0 || standing_volume<=planned_volume) return 0.0;
      const double release=MathMax(0.0,MathMin(100.0,release_percent))*0.01;
      const double maximum=MathMax(0.0,MathMin(100.0,maximum_close_percent))*0.01;
      double requested=(standing_volume-planned_volume)*release;
      if(maximum>0.0) requested=MathMin(requested,standing_volume*maximum);
      return NormalizeDown(requested,volume_min,volume_max,volume_step);
     }
  };

#endif
