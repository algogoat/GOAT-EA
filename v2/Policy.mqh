#ifndef GOAT_V2_POLICY_MQH
#define GOAT_V2_POLICY_MQH

#include "Domain.mqh"
#include "Features.mqh"
#include "IntelligenceBus.mqh"

struct V2PolicyEnvelope
  {
   bool                  allow_new_sequence;
   bool                  allow_add;
   bool                  reduce_only;
   ENUM_V2_DIRECTION     proposed_direction;
   double                exposure_factor;
   double                depth_factor;
   double                invalidation_price;
   double                objective_price;
   string                reason_code;

   void Reset(void)
     {
      allow_new_sequence=false;
      allow_add=false;
      reduce_only=false;
      proposed_direction=V2_DIR_NONE;
      exposure_factor=0.0;
      depth_factor=0.0;
      invalidation_price=0.0;
      objective_price=0.0;
      reason_code="NO_PROPOSAL";
     }
  };

class CV2Policy
  {
private:
   ENUM_V2_STATE_MODE m_mode;

public:
                     CV2Policy(void) { m_mode=V2_STATE_DISABLED; }

   bool Initialize(const ENUM_V2_STATE_MODE mode,string &reason)
     {
      reason="";
      if(mode>V2_STATE_SHADOW)
        {
         reason="POLICY_INFLUENCE_NOT_PHASE1_CERTIFIED";
         return false;
        }
      m_mode=mode;
      return true;
     }

   bool Evaluate(const ENUM_V2_DIRECTION deterministic_signal,
                 const V2FeatureFrame &features,
                 const V2IntelligenceState &state,
                 V2PolicyEnvelope &envelope) const
     {
      envelope.Reset();
      if(deterministic_signal==V2_DIR_NONE)
        {
         envelope.reason_code="NO_DETERMINISTIC_SIGNAL";
         return true;
        }
      envelope.proposed_direction=deterministic_signal;
      envelope.exposure_factor=1.0;
      envelope.depth_factor=1.0;
      envelope.allow_new_sequence=true;
      envelope.allow_add=true;
      if(m_mode==V2_STATE_DISABLED)
         envelope.reason_code="STATE_DISABLED";
      else if(m_mode==V2_STATE_DISPLAY)
         envelope.reason_code="STATE_DISPLAY_ONLY";
      else if(!state.valid)
         envelope.reason_code="STATE_SHADOW_ABSTAIN_NO_VALID_STATE";
      else
         envelope.reason_code="STATE_SHADOW_OBSERVED_NO_POLICY_CERTIFIED";
      return true;
     }
  };

#endif
