#ifndef GOAT_V2_INTELLIGENCE_BUS_MQH
#define GOAT_V2_INTELLIGENCE_BUS_MQH

#include "Inputs_V2.mqh"

enum ENUM_V2_INTELLIGENCE_REGIME
  {
   V2_REGIME_STRONG_BEARISH=-2,
   V2_REGIME_BEARISH=-1,
   V2_REGIME_NEUTRAL=0,
   V2_REGIME_BULLISH=1,
   V2_REGIME_STRONG_BULLISH=2
  };

struct V2IntelligenceState
  {
   string schema_version;
   string state_id;
   string thesis_id;
   int    revision;
   string asset_canonical;
   datetime market_as_of;
   datetime published_at;
   datetime valid_from;
   datetime valid_until;
   string era;
   ENUM_V2_INTELLIGENCE_REGIME regime;
   double p_bull;
   double p_neutral;
   double p_bear;
   double signed_score;
   string actionability;
   string location_state;
   double zone_lo;
   double zone_hi;
   string trigger_type;
   double entry_invalidation;
   double eae_atr;
   int    eae_minutes;
   double eae_quantile;
   double objective;
   double reference_price;
   datetime reference_price_ts;
   double reference_atr;
   string forecast_horizon;
   string thesis_status;
   string quality_flags[];
   string model_version;
   string analyst_version;
   string content_hash;
   bool   valid;
   bool   availability_approx;

   void Reset(void)
     {
      schema_version="goat-state-v1";
      state_id="";
      thesis_id="";
      revision=0;
      asset_canonical="";
      market_as_of=0;
      published_at=0;
      valid_from=0;
      valid_until=0;
      era="";
      regime=V2_REGIME_NEUTRAL;
      p_bull=0.0;
      p_neutral=1.0;
      p_bear=0.0;
      signed_score=0.0;
      actionability="NO_STATE";
      location_state="NO_TRADE";
      zone_lo=0.0;
      zone_hi=0.0;
      trigger_type="IMMEDIATE";
      entry_invalidation=0.0;
      eae_atr=0.0;
      eae_minutes=0;
      eae_quantile=0.0;
      objective=0.0;
      reference_price=0.0;
      reference_price_ts=0;
      reference_atr=0.0;
      forecast_horizon="";
      thesis_status="";
      ArrayResize(quality_flags,0);
      model_version="";
      analyst_version="";
      content_hash="";
      valid=false;
      availability_approx=false;
     }
  };

class CV2IntelligenceBus
  {
private:
   ENUM_V2_STATE_MODE  m_mode;
   V2IntelligenceState m_state;

public:
                     CV2IntelligenceBus(void)
     {
      m_mode=V2_STATE_DISABLED;
      m_state.Reset();
     }

   bool Initialize(const ENUM_V2_STATE_MODE mode,string &reason)
     {
      reason="";
      if(mode>V2_STATE_SHADOW)
        {
         reason="STATE_INFLUENCE_NOT_PHASE1_CERTIFIED";
         return false;
        }
      m_mode=mode;
      m_state.Reset();
      return true;
     }

   ENUM_V2_STATE_MODE Mode(void) const { return m_mode; }
   bool HasValidState(const datetime now) const
     {
      return(m_state.valid && m_state.published_at<=now && m_state.valid_from<=now && now<=m_state.valid_until);
     }
   void Current(V2IntelligenceState &state) const { state=m_state; }
  };

#endif
