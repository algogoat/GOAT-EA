#ifndef GOAT_V2_ONNX_LAYER_MQH
#define GOAT_V2_ONNX_LAYER_MQH

#include "Inputs_V2.mqh"
#include "Features.mqh"

struct V2OnnxProposal
  {
   bool   available;
   bool   abstained;
   double objective_probability;
   double adverse_excursion_atr;
   double execution_quality;
   double exposure_factor;
   string bundle_hash;
   string reason_code;
  };

class CV2OnnxLayer
  {
public:
   bool Initialize(const ENUM_V2_ONNX_MODE mode,string &reason)
     {
      if(mode!=V2_ONNX_DISABLED)
        {
         reason="ONNX_NOT_PHASE3_CERTIFIED";
         return false;
        }
      reason="";
      return true;
     }

   void Evaluate(const V2FeatureFrame &features,V2OnnxProposal &proposal) const
     {
      proposal.available=false;
      proposal.abstained=true;
      proposal.objective_probability=0.0;
      proposal.adverse_excursion_atr=0.0;
      proposal.execution_quality=0.0;
      proposal.exposure_factor=0.0;
      proposal.bundle_hash="";
      proposal.reason_code="ONNX_DISABLED";
     }
  };

#endif
