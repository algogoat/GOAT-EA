#ifndef GOAT_V2_FEATURES_MQH
#define GOAT_V2_FEATURES_MQH

#include "Domain.mqh"
#include "Inputs_V2.mqh"

struct V2FeatureValue
  {
   double value;
   bool   ready;
   int    observation_count;
   long   source_age_msc;
   int    schema_version;

   void Reset(void)
     {
      value=0.0;
      ready=false;
      observation_count=0;
      source_age_msc=0;
      schema_version=1;
     }
  };

struct V2FeatureFrame
  {
   string         symbol;
   long           observed_at_msc;
   int            schema_version;
   V2FeatureValue spread_points;
   V2FeatureValue atr_points;
   V2FeatureValue fast_ema;
   V2FeatureValue slow_ema;
   V2FeatureValue ema_spread_atr;
   V2FeatureValue rsi;
   V2FeatureValue sequence_mlps_utilization;
   V2FeatureValue sequence_exposure_ratio;

   void Reset(void)
     {
      symbol="";
      observed_at_msc=0;
      schema_version=1;
      spread_points.Reset();
      atr_points.Reset();
      fast_ema.Reset();
      slow_ema.Reset();
      ema_spread_atr.Reset();
      rsi.Reset();
      sequence_mlps_utilization.Reset();
      sequence_exposure_ratio.Reset();
     }

   bool SignalReady(void) const
     {
      return(fast_ema.ready && slow_ema.ready && rsi.ready && atr_points.ready && atr_points.value>0.0);
     }
  };

bool V2ClosedBarAvailabilityAgeMsc(const long observed_at_msc,
                                   const datetime closed_bar_available_at,
                                   long &age_msc)
  {
   age_msc=0;
   const long available_at_msc=(long)closed_bar_available_at*1000;
   if(observed_at_msc<=0 || available_at_msc<=0 || observed_at_msc<available_at_msc)
      return false;
   age_msc=observed_at_msc-available_at_msc;
   return true;
  }

class CV2Features
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_timeframe;
   int             m_fast_handle;
   int             m_slow_handle;
   int             m_rsi_handle;
   int             m_atr_handle;
   int             m_observation_count;

   bool CopyOne(const int handle,const int buffer,const int shift,double &value) const
     {
      double values[1];
      ResetLastError();
      int copied=CopyBuffer(handle,buffer,shift,1,values);
      if(copied!=1 || !MathIsValidNumber(values[0]))
         return false;
      value=values[0];
      return true;
     }

   void SetFeature(V2FeatureValue &feature,const double value,const bool ready,const long age_msc)
     {
      feature.value=(ready ? value : 0.0);
      feature.ready=ready;
      feature.observation_count=(ready ? m_observation_count : 0);
      feature.source_age_msc=age_msc;
      feature.schema_version=1;
     }

public:
                     CV2Features(void)
     {
      m_symbol="";
      m_timeframe=PERIOD_CURRENT;
      m_fast_handle=INVALID_HANDLE;
      m_slow_handle=INVALID_HANDLE;
      m_rsi_handle=INVALID_HANDLE;
      m_atr_handle=INVALID_HANDLE;
      m_observation_count=0;
     }

   bool Initialize(const string symbol,
                   const ENUM_TIMEFRAMES timeframe,
                   const int fast_period,
                   const int slow_period,
                   const int rsi_period,
                   const int atr_period,
                   string &reason)
     {
      reason="";
      m_symbol=symbol;
      m_timeframe=timeframe;
      m_fast_handle=iMA(symbol,timeframe,fast_period,0,MODE_EMA,PRICE_CLOSE);
      m_slow_handle=iMA(symbol,timeframe,slow_period,0,MODE_EMA,PRICE_CLOSE);
      m_rsi_handle=iRSI(symbol,timeframe,rsi_period,PRICE_CLOSE);
      m_atr_handle=iATR(symbol,timeframe,atr_period);
      if(m_fast_handle==INVALID_HANDLE || m_slow_handle==INVALID_HANDLE || m_rsi_handle==INVALID_HANDLE || m_atr_handle==INVALID_HANDLE)
        {
         reason="FEATURE_HANDLE_CREATION_FAILED";
         Shutdown();
         return false;
        }
      return true;
     }

   bool Update(const MqlTick &tick,const double standing_lots,const double planned_peak_lots,const double mlps_used,const double mlps_budget,V2FeatureFrame &frame)
     {
      frame.Reset();
      frame.symbol=m_symbol;
      frame.observed_at_msc=tick.time_msc;
      m_observation_count++;

      double point=SymbolInfoDouble(m_symbol,SYMBOL_POINT);
      bool spread_ready=(point>0.0 && tick.ask>=tick.bid && tick.bid>0.0);
      SetFeature(frame.spread_points,(spread_ready ? (tick.ask-tick.bid)/point : 0.0),spread_ready,0);

      double fast=0.0,slow=0.0,rsi=0.0,atr=0.0;
      // Shift 1 supplies the last closed-bar value; it becomes available at
      // the shift-0 bar boundary, not at the prior bar's opening timestamp.
      const datetime source_available_at=iTime(m_symbol,m_timeframe,0);
      long source_age_msc=0;
      const bool source_timestamp_ready=V2ClosedBarAvailabilityAgeMsc(tick.time_msc,
                                                                     source_available_at,
                                                                     source_age_msc);
      bool fast_ready=source_timestamp_ready && CopyOne(m_fast_handle,0,1,fast);
      bool slow_ready=source_timestamp_ready && CopyOne(m_slow_handle,0,1,slow);
      bool rsi_ready=source_timestamp_ready && CopyOne(m_rsi_handle,0,1,rsi);
      bool atr_ready=source_timestamp_ready && CopyOne(m_atr_handle,0,1,atr) && point>0.0 && atr>0.0;
      SetFeature(frame.fast_ema,fast,fast_ready,source_age_msc);
      SetFeature(frame.slow_ema,slow,slow_ready,source_age_msc);
      SetFeature(frame.rsi,rsi,rsi_ready,source_age_msc);
      SetFeature(frame.atr_points,(atr_ready ? atr/point : 0.0),atr_ready,source_age_msc);
      SetFeature(frame.ema_spread_atr,(fast_ready && slow_ready && atr_ready ? (fast-slow)/atr : 0.0),fast_ready && slow_ready && atr_ready,source_age_msc);
      SetFeature(frame.sequence_mlps_utilization,(mlps_budget>0.0 ? mlps_used/mlps_budget : 0.0),mlps_budget>0.0,0);
      SetFeature(frame.sequence_exposure_ratio,(planned_peak_lots>0.0 ? standing_lots/planned_peak_lots : 0.0),planned_peak_lots>0.0,0);
      return true;
     }

   ENUM_V2_DIRECTION Signal(const ENUM_V2_SIGNAL_MODE mode,const V2FeatureFrame &frame,const double rsi_long,const double rsi_short) const
     {
      if(mode==V2_SIGNAL_DISABLED || !frame.SignalReady())
         return V2_DIR_NONE;
      bool trend_long=(frame.fast_ema.value>frame.slow_ema.value && frame.rsi.value>=rsi_long);
      bool trend_short=(frame.fast_ema.value<frame.slow_ema.value && frame.rsi.value<=rsi_short);
      bool mean_long=(frame.rsi.value<=rsi_short && frame.ema_spread_atr.value<0.0);
      bool mean_short=(frame.rsi.value>=rsi_long && frame.ema_spread_atr.value>0.0);
      if(mode==V2_SIGNAL_TREND)
        {
         if(trend_long) return V2_DIR_LONG;
         if(trend_short) return V2_DIR_SHORT;
        }
      else if(mode==V2_SIGNAL_MEAN_REVERSION)
        {
         if(mean_long) return V2_DIR_LONG;
         if(mean_short) return V2_DIR_SHORT;
        }
      else if(mode==V2_SIGNAL_HYBRID)
        {
         if(trend_long || mean_long) return V2_DIR_LONG;
         if(trend_short || mean_short) return V2_DIR_SHORT;
        }
      return V2_DIR_NONE;
     }

   void Shutdown(void)
     {
      if(m_fast_handle!=INVALID_HANDLE) IndicatorRelease(m_fast_handle);
      if(m_slow_handle!=INVALID_HANDLE) IndicatorRelease(m_slow_handle);
      if(m_rsi_handle!=INVALID_HANDLE) IndicatorRelease(m_rsi_handle);
      if(m_atr_handle!=INVALID_HANDLE) IndicatorRelease(m_atr_handle);
      m_fast_handle=INVALID_HANDLE;
      m_slow_handle=INVALID_HANDLE;
      m_rsi_handle=INVALID_HANDLE;
      m_atr_handle=INVALID_HANDLE;
     }
  };

#endif
