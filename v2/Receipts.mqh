#ifndef GOAT_V2_RECEIPTS_MQH
#define GOAT_V2_RECEIPTS_MQH

#include "Domain.mqh"

enum ENUM_V2_RECEIPT_KIND
  {
   V2_RECEIPT_NONE=0,
   V2_RECEIPT_SEQUENCE_START=1,
   V2_RECEIPT_SEQUENCE_START_SUPPRESSED=2,
   V2_RECEIPT_LEVEL_ADD=3,
   V2_RECEIPT_LEVEL_SKIP=4,
   V2_RECEIPT_PARTIAL_CLOSE=5,
   V2_RECEIPT_RESCUE_ARM=6,
   V2_RECEIPT_SEQUENCE_END=7,
   V2_RECEIPT_KERNEL_VETO=8,
   V2_RECEIPT_RECOVERY_ACTION=9,
   V2_RECEIPT_SHADOW_DECISION=10,
   V2_RECEIPT_ORDER_SUBMISSION=11,
   V2_RECEIPT_ORDER_OBSERVATION=12,
   V2_RECEIPT_OPERATIONAL_STATE=13
  };

string V2UlongToText(const ulong value)
  {
   return StringFormat("%I64u",value);
  }

bool V2TextToUlong(const string text,ulong &value)
  {
   value=0;
   const int length=StringLen(text);
   if(length<=0)
      return false;
   if(length>1 && StringGetCharacter(text,0)=='0')
      return false;

   const ulong max_value=ULONG_MAX;
   for(int i=0;i<length;i++)
     {
      const ushort character=StringGetCharacter(text,i);
      if(character<'0' || character>'9')
         return false;
      const ulong digit=(ulong)(character-'0');
      if(value>(max_value-digit)/10)
        {
         value=0;
         return false;
        }
      value=value*10+digit;
     }
   return true;
  }

string V2JsonEscape(const string value)
  {
   string escaped="";
   const int length=StringLen(value);
   for(int i=0;i<length;i++)
     {
      const ushort character=StringGetCharacter(value,i);
      switch(character)
        {
         case '"': escaped+="\\\""; break;
         case '\\': escaped+="\\\\"; break;
         case 8:    escaped+="\\b";  break;
         case 9:    escaped+="\\t";  break;
         case 10:   escaped+="\\n";  break;
         case 12:   escaped+="\\f";  break;
         case 13:   escaped+="\\r";  break;
         default:
            if(character<32)
               escaped+=StringFormat("\\u%04X",(uint)character);
            else
               escaped+=ShortToString(character);
            break;
        }
     }
   return escaped;
  }

string V2JsonQuote(const string value)
  {
   return "\""+V2JsonEscape(value)+"\"";
  }

string V2CanonicalDouble(const double value,const int digits=10)
  {
   double normalized=value;
   const double zero_threshold=0.5*MathPow(10.0,-digits);
   if(MathAbs(normalized)<zero_threshold)
      normalized=0.0;
   return DoubleToString(normalized,digits);
  }

string V2JsonBool(const bool value)
  {
   return value ? "true" : "false";
  }

string V2Sha256Hex(const string value)
  {
   uchar source[];
   uchar key[];
   uchar digest[];
   ArrayResize(key,0);
   const int copied=StringToCharArray(value,source,0,StringLen(value),CP_UTF8);
   if(copied<0)
      return "";
   const int bytes=CryptEncode(CRYPT_HASH_SHA256,source,key,digest);
   if(bytes<=0)
      return "";

   string hex="";
   for(int i=0;i<bytes;i++)
      hex+=StringFormat("%02X",(uint)digest[i]);
   return hex;
  }

int V2Utf8ByteCount(const string value)
  {
   uchar bytes[];
   const int copied=StringToCharArray(value,bytes,0,StringLen(value),CP_UTF8);
   return copied<0 ? 0 : copied;
  }

string V2ReceiptKindName(const ENUM_V2_RECEIPT_KIND kind)
  {
   switch(kind)
     {
      case V2_RECEIPT_SEQUENCE_START:            return "SEQ_START";
      case V2_RECEIPT_SEQUENCE_START_SUPPRESSED: return "SEQ_START_SUPPRESSED";
      case V2_RECEIPT_LEVEL_ADD:                 return "LEVEL_ADD";
      case V2_RECEIPT_LEVEL_SKIP:                return "LEVEL_SKIP";
      case V2_RECEIPT_PARTIAL_CLOSE:             return "PARTIAL_CLOSE";
      case V2_RECEIPT_RESCUE_ARM:                return "RESCUE_ARM";
      case V2_RECEIPT_SEQUENCE_END:              return "SEQ_END";
      case V2_RECEIPT_KERNEL_VETO:               return "KERNEL_VETO";
      case V2_RECEIPT_RECOVERY_ACTION:           return "RECOVERY_ACTION";
      case V2_RECEIPT_SHADOW_DECISION:           return "SHADOW_DECISION";
      case V2_RECEIPT_ORDER_SUBMISSION:          return "ORDER_SUBMISSION";
      case V2_RECEIPT_ORDER_OBSERVATION:         return "ORDER_OBSERVATION";
      case V2_RECEIPT_OPERATIONAL_STATE:         return "OPERATIONAL_STATE";
      default:                                   return "NONE";
     }
  }

struct V2Receipt
  {
   string                    receipt_id;
   ENUM_V2_RECEIPT_KIND      kind;
   long                      occurred_at_msc;
   long                      canonical_number;
   long                      state_version;
   string                    deployment_id;
   string                    portfolio_generation_id;
   string                    strategy_member_id;
   string                    sequence_id;
   string                    order_intent_id;
   string                    event_id;
   string                    experiment_manifest_id;
   string                    symbol;
   ENUM_V2_DIRECTION         direction;
   int                       level_index;
   ENUM_V2_ACTION_KIND       action;
   ENUM_V2_RISK_EFFECT       risk_effect;
   ENUM_V2_KERNEL_VERDICT    kernel_verdict;
   string                    policy_reason;
   string                    kernel_reason;
   string                    broker_profile_version;
   string                    feature_schema_version;
   string                    feature_readiness_mask;
   string                    feature_snapshot;
   string                    policy_verdict;
   string                    kernel_invariant_snapshot;
   string                    intelligence_state_id;
   string                    intelligence_content_hash;
   string                    intelligence_thesis;
   string                    intelligence_era;
   long                      intelligence_published_at_msc;
   long                      intelligence_valid_until_msc;
   string                    model_bundle_hash;
   bool                      onnx_input_ready;
   string                    onnx_outputs;
   bool                      onnx_abstained;
   bool                      onnx_out_of_distribution;
   string                    onnx_reason;
   ulong                     request_id;
   ulong                     order_ticket;
   ulong                     deal_ticket;
   ulong                     position_id;
   uint                      retcode;
   uint                      retcode_external;
   string                    broker_comment;
   double                    requested_volume;
   double                    requested_price;
   double                    accepted_volume;
   double                    accepted_price;
   double                    filled_volume;
   double                    filled_price;
   ulong                     latency_micros;
   double                    stop_loss;
   double                    take_profit;
   double                    realized_pl;
   double                    commission;
   double                    swap;
   double                    maximum_adverse_excursion_atr;
   double                    maximum_favorable_excursion_atr;
   long                      duration_seconds;
   int                       level_count;
   string                    exit_attribution;
   bool                      counterfactual;
   bool                      emergency_persistence;
   string                    payload_hash;
   string                    canonical_payload;

   void Reset(void)
     {
      receipt_id="";
      kind=V2_RECEIPT_NONE;
      occurred_at_msc=0;
      canonical_number=0;
      state_version=0;
      deployment_id="";
      portfolio_generation_id="";
      strategy_member_id="";
      sequence_id="";
      order_intent_id="";
      event_id="";
      experiment_manifest_id="";
      symbol="";
      direction=V2_DIR_NONE;
      level_index=-1;
      action=V2_ACTION_OPEN;
      risk_effect=V2_RISK_UNKNOWN;
      kernel_verdict=V2_KERNEL_DENY;
      policy_reason="";
      kernel_reason="";
      broker_profile_version="";
      feature_schema_version="";
      feature_readiness_mask="";
      feature_snapshot="";
      policy_verdict="";
      kernel_invariant_snapshot="";
      intelligence_state_id="";
      intelligence_content_hash="";
      intelligence_thesis="";
      intelligence_era="";
      intelligence_published_at_msc=0;
      intelligence_valid_until_msc=0;
      model_bundle_hash="";
      onnx_input_ready=false;
      onnx_outputs="";
      onnx_abstained=false;
      onnx_out_of_distribution=false;
      onnx_reason="";
      request_id=0;
      order_ticket=0;
      deal_ticket=0;
      position_id=0;
      retcode=0;
      retcode_external=0;
      broker_comment="";
      requested_volume=0.0;
      requested_price=0.0;
      accepted_volume=0.0;
      accepted_price=0.0;
      filled_volume=0.0;
      filled_price=0.0;
      latency_micros=0;
      stop_loss=0.0;
      take_profit=0.0;
      realized_pl=0.0;
      commission=0.0;
      swap=0.0;
      maximum_adverse_excursion_atr=0.0;
      maximum_favorable_excursion_atr=0.0;
      duration_seconds=0;
      level_count=0;
      exit_attribution="";
      counterfactual=false;
      emergency_persistence=false;
      payload_hash="";
      canonical_payload="";
     }
  };

class CV2ReceiptBuilder
  {
private:
   bool ValidateFields(const V2Receipt &receipt,string &reason) const
     {
      reason="";
      if(receipt.kind==V2_RECEIPT_NONE)
        {
         reason="RECEIPT_KIND_NONE";
         return false;
        }
      if(receipt.deployment_id=="")
        {
         reason="RECEIPT_DEPLOYMENT_ID_EMPTY";
         return false;
        }
      if(receipt.strategy_member_id=="")
        {
         reason="RECEIPT_MEMBER_ID_EMPTY";
         return false;
        }
      if(receipt.occurred_at_msc<0 || receipt.canonical_number<0 || receipt.state_version<0)
        {
         reason="RECEIPT_TIME_OR_SEQUENCE_NEGATIVE";
         return false;
        }
      if(receipt.intelligence_published_at_msc<0 || receipt.intelligence_valid_until_msc<0)
        {
         reason="RECEIPT_INTELLIGENCE_TIME_NEGATIVE";
         return false;
        }
      if(!MathIsValidNumber(receipt.requested_volume) ||
         !MathIsValidNumber(receipt.requested_price) ||
         !MathIsValidNumber(receipt.accepted_volume) ||
         !MathIsValidNumber(receipt.accepted_price) ||
         !MathIsValidNumber(receipt.filled_volume) ||
         !MathIsValidNumber(receipt.filled_price) ||
         !MathIsValidNumber(receipt.stop_loss) ||
         !MathIsValidNumber(receipt.take_profit) ||
         !MathIsValidNumber(receipt.realized_pl) ||
         !MathIsValidNumber(receipt.commission) ||
         !MathIsValidNumber(receipt.swap) ||
         !MathIsValidNumber(receipt.maximum_adverse_excursion_atr) ||
         !MathIsValidNumber(receipt.maximum_favorable_excursion_atr))
        {
         reason="RECEIPT_NUMERIC_VALUE_INVALID";
         return false;
        }
      return true;
     }

   string CanonicalPayload(const V2Receipt &receipt) const
     {
      string payload="{";
      payload+="\"schemaVersion\":\"goat2-receipt-v1\",";
      payload+="\"kind\":"+V2JsonQuote(V2ReceiptKindName(receipt.kind))+",";
      payload+="\"occurredAtMsc\":"+IntegerToString(receipt.occurred_at_msc)+",";
      payload+="\"canonicalNumber\":"+IntegerToString(receipt.canonical_number)+",";
      payload+="\"stateVersion\":"+IntegerToString(receipt.state_version)+",";
      payload+="\"deploymentId\":"+V2JsonQuote(receipt.deployment_id)+",";
      payload+="\"portfolioGenerationId\":"+V2JsonQuote(receipt.portfolio_generation_id)+",";
      payload+="\"strategyMemberId\":"+V2JsonQuote(receipt.strategy_member_id)+",";
      payload+="\"sequenceId\":"+V2JsonQuote(receipt.sequence_id)+",";
      payload+="\"orderIntentId\":"+V2JsonQuote(receipt.order_intent_id)+",";
      payload+="\"eventId\":"+V2JsonQuote(receipt.event_id)+",";
      payload+="\"experimentManifestId\":"+V2JsonQuote(receipt.experiment_manifest_id)+",";
      payload+="\"symbol\":"+V2JsonQuote(receipt.symbol)+",";
      payload+="\"direction\":"+IntegerToString((int)receipt.direction)+",";
      payload+="\"levelIndex\":"+IntegerToString(receipt.level_index)+",";
      payload+="\"action\":"+IntegerToString((int)receipt.action)+",";
      payload+="\"riskEffect\":"+IntegerToString((int)receipt.risk_effect)+",";
      payload+="\"kernelVerdict\":"+IntegerToString((int)receipt.kernel_verdict)+",";
      payload+="\"policyReason\":"+V2JsonQuote(receipt.policy_reason)+",";
      payload+="\"kernelReason\":"+V2JsonQuote(receipt.kernel_reason)+",";
      payload+="\"brokerProfileVersion\":"+V2JsonQuote(receipt.broker_profile_version)+",";
      payload+="\"featureSchemaVersion\":"+V2JsonQuote(receipt.feature_schema_version)+",";
      payload+="\"featureReadinessMask\":"+V2JsonQuote(receipt.feature_readiness_mask)+",";
      payload+="\"featureSnapshot\":"+V2JsonQuote(receipt.feature_snapshot)+",";
      payload+="\"policyVerdict\":"+V2JsonQuote(receipt.policy_verdict)+",";
      payload+="\"kernelInvariantSnapshot\":"+V2JsonQuote(receipt.kernel_invariant_snapshot)+",";
      payload+="\"intelligenceStateId\":"+V2JsonQuote(receipt.intelligence_state_id)+",";
      payload+="\"intelligenceContentHash\":"+V2JsonQuote(receipt.intelligence_content_hash)+",";
      payload+="\"intelligenceThesis\":"+V2JsonQuote(receipt.intelligence_thesis)+",";
      payload+="\"intelligenceEra\":"+V2JsonQuote(receipt.intelligence_era)+",";
      payload+="\"intelligencePublishedAtMsc\":"+IntegerToString(receipt.intelligence_published_at_msc)+",";
      payload+="\"intelligenceValidUntilMsc\":"+IntegerToString(receipt.intelligence_valid_until_msc)+",";
      payload+="\"modelBundleHash\":"+V2JsonQuote(receipt.model_bundle_hash)+",";
      payload+="\"onnxInputReady\":"+V2JsonBool(receipt.onnx_input_ready)+",";
      payload+="\"onnxOutputs\":"+V2JsonQuote(receipt.onnx_outputs)+",";
      payload+="\"onnxAbstained\":"+V2JsonBool(receipt.onnx_abstained)+",";
      payload+="\"onnxOutOfDistribution\":"+V2JsonBool(receipt.onnx_out_of_distribution)+",";
      payload+="\"onnxReason\":"+V2JsonQuote(receipt.onnx_reason)+",";
      payload+="\"requestId\":"+V2JsonQuote(V2UlongToText(receipt.request_id))+",";
      payload+="\"orderTicket\":"+V2JsonQuote(V2UlongToText(receipt.order_ticket))+",";
      payload+="\"dealTicket\":"+V2JsonQuote(V2UlongToText(receipt.deal_ticket))+",";
      payload+="\"positionId\":"+V2JsonQuote(V2UlongToText(receipt.position_id))+",";
      payload+="\"retcode\":"+IntegerToString((long)receipt.retcode)+",";
      payload+="\"retcodeExternal\":"+IntegerToString((long)receipt.retcode_external)+",";
      payload+="\"brokerComment\":"+V2JsonQuote(receipt.broker_comment)+",";
      payload+="\"requestedVolume\":"+V2CanonicalDouble(receipt.requested_volume)+",";
      payload+="\"requestedPrice\":"+V2CanonicalDouble(receipt.requested_price)+",";
      payload+="\"acceptedVolume\":"+V2CanonicalDouble(receipt.accepted_volume)+",";
      payload+="\"acceptedPrice\":"+V2CanonicalDouble(receipt.accepted_price)+",";
      payload+="\"filledVolume\":"+V2CanonicalDouble(receipt.filled_volume)+",";
      payload+="\"filledPrice\":"+V2CanonicalDouble(receipt.filled_price)+",";
      payload+="\"latencyMicros\":"+V2JsonQuote(V2UlongToText(receipt.latency_micros))+",";
      payload+="\"stopLoss\":"+V2CanonicalDouble(receipt.stop_loss)+",";
      payload+="\"takeProfit\":"+V2CanonicalDouble(receipt.take_profit)+",";
      payload+="\"realizedPl\":"+V2CanonicalDouble(receipt.realized_pl)+",";
      payload+="\"commission\":"+V2CanonicalDouble(receipt.commission)+",";
      payload+="\"swap\":"+V2CanonicalDouble(receipt.swap)+",";
      payload+="\"maximumAdverseExcursionAtr\":"+V2CanonicalDouble(receipt.maximum_adverse_excursion_atr)+",";
      payload+="\"maximumFavorableExcursionAtr\":"+V2CanonicalDouble(receipt.maximum_favorable_excursion_atr)+",";
      payload+="\"durationSeconds\":"+IntegerToString(receipt.duration_seconds)+",";
      payload+="\"levelCount\":"+IntegerToString(receipt.level_count)+",";
      payload+="\"exitAttribution\":"+V2JsonQuote(receipt.exit_attribution)+",";
      payload+="\"counterfactual\":"+V2JsonBool(receipt.counterfactual)+",";
      payload+="\"emergencyPersistence\":"+V2JsonBool(receipt.emergency_persistence);
      payload+="}";
      return payload;
     }

public:
   bool Build(V2Receipt &receipt,string &reason) const
     {
      if(!ValidateFields(receipt,reason))
         return false;

      receipt.canonical_payload=CanonicalPayload(receipt);
      receipt.payload_hash=V2Sha256Hex(receipt.canonical_payload);
      if(receipt.payload_hash=="")
        {
         reason="RECEIPT_HASH_FAILED";
         return false;
        }
      receipt.receipt_id="rcp_"+receipt.payload_hash;
      return true;
     }

   bool Validate(const V2Receipt &receipt,string &reason) const
     {
      if(!ValidateFields(receipt,reason))
         return false;
      const string canonical_payload=CanonicalPayload(receipt);
      if(receipt.canonical_payload!=canonical_payload)
        {
         reason="RECEIPT_CANONICAL_PAYLOAD_MISMATCH";
         return false;
        }
      const string payload_hash=V2Sha256Hex(canonical_payload);
      if(payload_hash=="")
        {
         reason="RECEIPT_HASH_FAILED";
         return false;
        }
      if(receipt.payload_hash!=payload_hash)
        {
         reason="RECEIPT_PAYLOAD_HASH_MISMATCH";
         return false;
        }
      if(receipt.receipt_id!="rcp_"+payload_hash)
        {
         reason="RECEIPT_ID_MISMATCH";
         return false;
        }
      return true;
     }

   bool BuildFromEvent(const V2DomainEvent &event,
                       const ENUM_V2_RECEIPT_KIND kind,
                       const string deployment_id,
                       const string generation_id,
                       const string member_id,
                       const string manifest_id,
                       V2Receipt &receipt,
                       string &reason) const
     {
      receipt.Reset();
      receipt.kind=kind;
      receipt.occurred_at_msc=(long)event.occurred_at*1000;
      receipt.canonical_number=event.canonical_number;
      receipt.state_version=event.state_version;
      receipt.deployment_id=deployment_id;
      receipt.portfolio_generation_id=generation_id;
      receipt.strategy_member_id=member_id;
      receipt.sequence_id=event.sequence_id;
      receipt.order_intent_id=event.order_intent_id;
      receipt.event_id=event.event_id;
      receipt.experiment_manifest_id=manifest_id;
      receipt.symbol=event.symbol;
      receipt.direction=event.direction;
      receipt.level_index=event.level_index;
      receipt.action=event.action;
      receipt.risk_effect=event.risk_effect;
      receipt.request_id=event.request_id;
      receipt.order_ticket=event.order_ticket;
      receipt.deal_ticket=event.deal_ticket;
      receipt.position_id=event.position_id;
      receipt.requested_volume=event.volume;
      receipt.requested_price=event.price;
      if(event.kind==V2_EVENT_ORDER_ACCEPTED)
        {
         receipt.accepted_volume=event.volume;
         receipt.accepted_price=event.price;
        }
      if(event.kind==V2_EVENT_FILL_PARTIAL || event.kind==V2_EVENT_FILL_COMPLETE)
        {
         receipt.filled_volume=event.volume;
         receipt.filled_price=event.price;
        }
      receipt.realized_pl=event.realized_pl;
      receipt.policy_reason=event.reason_code;
      return Build(receipt,reason);
     }

   string Serialize(const V2Receipt &receipt) const
     {
      return CanonicalPayload(receipt);
     }
  };

#endif
