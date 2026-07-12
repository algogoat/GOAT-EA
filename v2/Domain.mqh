#ifndef GOAT_V2_DOMAIN_MQH
#define GOAT_V2_DOMAIN_MQH

enum ENUM_V2_DIRECTION
  {
   V2_DIR_SHORT=-1,
   V2_DIR_NONE=0,
   V2_DIR_LONG=1
  };

enum ENUM_V2_OPERATIONAL_STATE
  {
   V2_OP_NORMAL=0,
   V2_OP_DEGRADED=1,
   V2_OP_MANAGE_ONLY=2,
   V2_OP_RECOVERY_QUARANTINE=3,
   V2_OP_HALTED=4
  };

enum ENUM_V2_SEQUENCE_STATUS
  {
   V2_SEQ_IDLE=0,
   V2_SEQ_ACTIVE=1,
   V2_SEQ_REDUCE_ONLY=2,
   V2_SEQ_QUARANTINED=3,
   V2_SEQ_ENDED=4
  };

enum ENUM_V2_ORDER_INTENT_STATUS
  {
   V2_INTENT_PLANNED=0,
   V2_INTENT_PERSISTED=1,
   V2_INTENT_SUBMITTED=2,
   V2_INTENT_ACCEPTED=3,
   V2_INTENT_PARTIAL=4,
   V2_INTENT_FILLED=5,
   V2_INTENT_REJECTED=6,
   V2_INTENT_CANCELLED=7,
   V2_INTENT_RECONCILE_REQUIRED=8
  };

enum ENUM_V2_ACTION_KIND
  {
   V2_ACTION_OPEN=0,
   V2_ACTION_ADD=1,
   V2_ACTION_MODIFY=2,
   V2_ACTION_PARTIAL_CLOSE=3,
   V2_ACTION_CLOSE=4,
   V2_ACTION_CANCEL=5
  };

enum ENUM_V2_KERNEL_VERDICT
  {
   V2_KERNEL_ALLOW=0,
   V2_KERNEL_ALLOW_REDUCE_ONLY=1,
   V2_KERNEL_DENY=2,
   V2_KERNEL_HALT_NEW_RISK=3,
   V2_KERNEL_FORCE_REDUCE=4
  };

enum ENUM_V2_RISK_EFFECT
  {
   V2_RISK_UNKNOWN=0,
   V2_RISK_INCREASE=1,
   V2_RISK_NEUTRAL=2,
   V2_RISK_DECREASE=3
  };

enum ENUM_V2_EVENT_KIND
  {
   V2_EVENT_NONE=0,
   V2_EVENT_SEQUENCE_STARTED=1,
   V2_EVENT_LEVEL_PLANNED=2,
   V2_EVENT_ORDER_INTENT_CREATED=3,
   V2_EVENT_ORDER_SUBMITTED=4,
   V2_EVENT_ORDER_ACCEPTED=5,
   V2_EVENT_FILL_PARTIAL=6,
   V2_EVENT_FILL_COMPLETE=7,
   V2_EVENT_ORDER_REJECTED=8,
   V2_EVENT_LEVEL_CLOSED=9,
   V2_EVENT_RETRACE_POINTER_MOVED=10,
   V2_EVENT_RESCUE_ARMED=11,
   V2_EVENT_SEQUENCE_ENDED=12,
   V2_EVENT_RECOVERY_QUARANTINED=13,
   V2_EVENT_OPERATIONAL_STATE_CHANGED=14,
   V2_EVENT_REDUCTION_MANDATED=15,
   V2_EVENT_REDUCTION_COMPLETED=16
  };

struct V2DomainEvent
  {
   string             event_id;
   string             sequence_id;
   string             order_intent_id;
   ENUM_V2_EVENT_KIND kind;
   ENUM_V2_ACTION_KIND action;
   ENUM_V2_RISK_EFFECT risk_effect;
   ENUM_V2_DIRECTION   direction;
   string             symbol;
   datetime           occurred_at;
   long               canonical_number;
   long               state_version;
   int                level_index;
   ulong              request_id;
   ulong              order_ticket;
   ulong              deal_ticket;
   ulong              position_id;
   double             volume;
   double             price;
   double             realized_pl;
   bool               retrace_advance;
   string             reason_code;
   string             event_hash;

   void Reset(void)
     {
      event_id="";
      sequence_id="";
      order_intent_id="";
      kind=V2_EVENT_NONE;
      action=V2_ACTION_OPEN;
      risk_effect=V2_RISK_UNKNOWN;
      direction=V2_DIR_NONE;
      symbol="";
      occurred_at=0;
      canonical_number=0;
      state_version=0;
      level_index=-1;
      request_id=0;
      order_ticket=0;
      deal_ticket=0;
      position_id=0;
      volume=0.0;
      price=0.0;
      realized_pl=0.0;
      retrace_advance=false;
      reason_code="";
      event_hash="";
     }
  };

struct V2LevelState
  {
   string sequence_id;
   int    level_index;
   double planned_price;
   double requested_volume;
   double filled_volume;
   double average_fill_price;
   ulong  position_id;
   bool   virtual_level;
   bool   closed;

   void Reset(void)
     {
      sequence_id="";
      level_index=-1;
      planned_price=0.0;
      requested_volume=0.0;
      filled_volume=0.0;
      average_fill_price=0.0;
      position_id=0;
      virtual_level=false;
      closed=false;
     }
  };

struct V2OrderIntent
  {
   string                      order_intent_id;
   string                      sequence_id;
   ENUM_V2_ACTION_KIND         action;
   ENUM_V2_RISK_EFFECT         risk_effect;
   ENUM_V2_ORDER_INTENT_STATUS status;
   ENUM_V2_DIRECTION           direction;
   string                      symbol;
   ulong                       magic;
   int                         level_index;
   double                      requested_volume;
   double                      requested_price;
   double                      stop_loss;
   double                      take_profit;
   ulong                       request_id;
   ulong                       order_ticket;
   ulong                       deal_ticket;
   ulong                       position_id;
   uint                        retcode;
   datetime                    created_at;
   string                      reason_code;

   void Reset(void)
     {
      order_intent_id="";
      sequence_id="";
      action=V2_ACTION_OPEN;
      risk_effect=V2_RISK_UNKNOWN;
      status=V2_INTENT_PLANNED;
      direction=V2_DIR_NONE;
      symbol="";
      magic=0;
      level_index=-1;
      requested_volume=0.0;
      requested_price=0.0;
      stop_loss=0.0;
      take_profit=0.0;
      request_id=0;
      order_ticket=0;
      deal_ticket=0;
      position_id=0;
      retcode=0;
      created_at=0;
      reason_code="";
     }
  };

struct V2SequenceState
  {
   string                  sequence_id;
   string                  strategy_member_id;
   string                  symbol;
   ENUM_V2_DIRECTION       direction;
   ENUM_V2_SEQUENCE_STATUS status;
   datetime                started_at;
   datetime                ended_at;
   long                    last_event_number;
   long                    last_state_version;
   string                  last_event_id;
   string                  last_event_hash;
   string                  experiment_manifest_id;
   string                  input_values_hash;
   string                  broker_profile_hash;
   string                  symbol_spec_hash;
   string                  execution_plan_hash;
   int                     level_count;
   int                     max_levels;
   double                  start_volume;
   double                  standing_volume;
   double                  average_entry_price;
   double                  realized_pl;
   double                  commission;
   double                  swap;
   double                  mlps_budget;
   double                  mlps_used;
   double                  retrace_price;
   bool                    rescue_armed;
   double                  reduction_remaining;
   int                     reduction_semantic_level;
   string                  reduction_reason;
   bool                    retrace_advance_pending;

   void Reset(void)
     {
      sequence_id="";
      strategy_member_id="";
      symbol="";
      direction=V2_DIR_NONE;
      status=V2_SEQ_IDLE;
      started_at=0;
      ended_at=0;
      last_event_number=0;
      last_state_version=0;
      last_event_id="";
      last_event_hash="";
      experiment_manifest_id="";
      input_values_hash="";
      broker_profile_hash="";
      symbol_spec_hash="";
      execution_plan_hash="";
      level_count=0;
      max_levels=0;
      start_volume=0.0;
      standing_volume=0.0;
      average_entry_price=0.0;
      realized_pl=0.0;
      commission=0.0;
      swap=0.0;
      mlps_budget=0.0;
      mlps_used=0.0;
      retrace_price=0.0;
      rescue_armed=false;
      reduction_remaining=0.0;
      reduction_semantic_level=-1;
      reduction_reason="";
      retrace_advance_pending=false;
     }
  };

bool V2ActionIncreasesRisk(const ENUM_V2_ACTION_KIND action)
  {
   return(action==V2_ACTION_OPEN || action==V2_ACTION_ADD);
  }

bool V2ActionReducesRisk(const ENUM_V2_ACTION_KIND action)
  {
   return(action==V2_ACTION_PARTIAL_CLOSE || action==V2_ACTION_CLOSE);
  }

string V2EventKindName(const ENUM_V2_EVENT_KIND kind)
  {
   switch(kind)
     {
      case V2_EVENT_SEQUENCE_STARTED:          return "SEQUENCE_STARTED";
      case V2_EVENT_LEVEL_PLANNED:             return "LEVEL_PLANNED";
      case V2_EVENT_ORDER_INTENT_CREATED:      return "ORDER_INTENT_CREATED";
      case V2_EVENT_ORDER_SUBMITTED:           return "ORDER_SUBMITTED";
      case V2_EVENT_ORDER_ACCEPTED:            return "ORDER_ACCEPTED";
      case V2_EVENT_FILL_PARTIAL:              return "FILL_PARTIAL";
      case V2_EVENT_FILL_COMPLETE:             return "FILL_COMPLETE";
      case V2_EVENT_ORDER_REJECTED:            return "ORDER_REJECTED";
      case V2_EVENT_LEVEL_CLOSED:              return "LEVEL_CLOSED";
      case V2_EVENT_RETRACE_POINTER_MOVED:     return "RETRACE_POINTER_MOVED";
      case V2_EVENT_RESCUE_ARMED:              return "RESCUE_ARMED";
      case V2_EVENT_SEQUENCE_ENDED:            return "SEQUENCE_ENDED";
      case V2_EVENT_RECOVERY_QUARANTINED:      return "RECOVERY_QUARANTINED";
      case V2_EVENT_OPERATIONAL_STATE_CHANGED:return "OPERATIONAL_STATE_CHANGED";
      case V2_EVENT_REDUCTION_MANDATED:        return "REDUCTION_MANDATED";
      case V2_EVENT_REDUCTION_COMPLETED:       return "REDUCTION_COMPLETED";
      default:                                 return "NONE";
     }
  }

class CV2DomainMachine
  {
public:
   bool CanApply(const V2DomainEvent &event,const V2SequenceState &state,string &reason) const
     {
      reason="";
      if(event.event_id=="")
        {
         reason="EVENT_ID_EMPTY";
         return false;
        }
      if(event.kind==V2_EVENT_NONE)
        {
         reason="EVENT_KIND_NONE";
         return false;
        }
      if(event.event_id==state.last_event_id && event.canonical_number==state.last_event_number && event.state_version==state.last_state_version)
        {
         reason=(event.event_hash!="" && event.event_hash==state.last_event_hash ? "EVENT_ALREADY_APPLIED" : "EVENT_ID_HASH_CONFLICT");
         return false;
        }
      if(event.canonical_number<=state.last_event_number)
        {
         reason="GLOBAL_EVENT_ORDER_NOT_MONOTONIC";
         return false;
        }
      if(event.state_version!=state.last_state_version+1)
        {
         reason="STATE_VERSION_NOT_CONTIGUOUS";
         return false;
        }
      if(state.sequence_id!="" && event.sequence_id!="" && event.sequence_id!=state.sequence_id)
        {
         reason="SEQUENCE_ID_MISMATCH";
         return false;
        }
      switch(event.kind)
        {
         case V2_EVENT_SEQUENCE_STARTED:
            if(state.status!=V2_SEQ_IDLE)
              {
               reason="SEQUENCE_ALREADY_ACTIVE";
               return false;
              }
            if(event.sequence_id=="" || event.direction==V2_DIR_NONE || event.symbol=="")
              {
               reason="SEQUENCE_START_IDENTITY_INCOMPLETE";
               return false;
              }
            return true;

         case V2_EVENT_LEVEL_PLANNED:
            if(state.status!=V2_SEQ_ACTIVE)
              {
               reason="LEVEL_PLAN_REQUIRES_ACTIVE_SEQUENCE";
               return false;
              }
            if(event.level_index<0 || event.volume<=0.0 || event.price<=0.0)
              {
               reason="LEVEL_PLAN_GEOMETRY_INVALID";
               return false;
              }
            return true;

         case V2_EVENT_ORDER_INTENT_CREATED:
         case V2_EVENT_ORDER_SUBMITTED:
         case V2_EVENT_ORDER_ACCEPTED:
         case V2_EVENT_ORDER_REJECTED:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY && state.status!=V2_SEQ_QUARANTINED)
              {
               reason="SEQUENCE_NOT_MANAGEABLE";
               return false;
              }
            if(event.order_intent_id=="")
              {
               reason="ORDER_INTENT_ID_EMPTY";
               return false;
              }
            if((state.status==V2_SEQ_REDUCE_ONLY || state.status==V2_SEQ_QUARANTINED) && event.risk_effect!=V2_RISK_DECREASE)
              {
               reason="ONLY_RISK_DECREASE_ALLOWED";
               return false;
              }
            return true;

         case V2_EVENT_FILL_PARTIAL:
         case V2_EVENT_FILL_COMPLETE:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY && state.status!=V2_SEQ_QUARANTINED)
              {
               reason="SEQUENCE_NOT_MANAGEABLE";
               return false;
              }
             if(event.order_intent_id=="" || event.volume<=0.0 || event.price<=0.0 || !MathIsValidNumber(event.volume) || !MathIsValidNumber(event.price))
              {
               reason="FILL_PAYLOAD_INVALID";
                return false;
               }
             if(event.risk_effect!=V2_RISK_INCREASE && event.risk_effect!=V2_RISK_DECREASE)
               {
                reason="FILL_RISK_EFFECT_REQUIRED";
                return false;
               }
            if((state.status==V2_SEQ_REDUCE_ONLY || state.status==V2_SEQ_QUARANTINED) && event.risk_effect!=V2_RISK_DECREASE)
              {
               reason="ONLY_RISK_DECREASE_ALLOWED";
               return false;
              }
            if(event.risk_effect==V2_RISK_DECREASE && event.volume>state.standing_volume+1e-12)
              {
               reason="CLOSE_VOLUME_EXCEEDS_STANDING";
               return false;
              }
            return true;

         case V2_EVENT_LEVEL_CLOSED:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY && state.status!=V2_SEQ_QUARANTINED)
              {
               reason="SEQUENCE_NOT_MANAGEABLE";
               return false;
              }
            if(event.level_index<0)
              {
               reason="LEVEL_INDEX_INVALID";
               return false;
              }
            return true;

         case V2_EVENT_RETRACE_POINTER_MOVED:
            // A zero price explicitly clears an exhausted retrace chain.
            if(state.status!=V2_SEQ_ACTIVE || event.price<0.0 || !MathIsValidNumber(event.price))
              {
               reason="RETRACE_TRANSITION_INVALID";
               return false;
              }
            return true;

         case V2_EVENT_RESCUE_ARMED:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY)
              {
               reason="RESCUE_TRANSITION_INVALID";
               return false;
              }
            return true;

         case V2_EVENT_REDUCTION_MANDATED:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY && state.status!=V2_SEQ_QUARANTINED)
              {
               reason="SEQUENCE_NOT_MANAGEABLE";
               return false;
              }
            if(event.risk_effect!=V2_RISK_DECREASE || event.volume<=0.0 ||
               !MathIsValidNumber(event.volume))
              {
               reason="REDUCTION_MANDATE_VOLUME_INVALID";
               return false;
              }
            if(event.reason_code=="")
              {
               reason="REDUCTION_MANDATE_REASON_EMPTY";
               return false;
              }
            if(state.reduction_remaining>1e-12 &&
               event.volume<state.reduction_remaining-1e-12)
              {
               reason="REDUCTION_MANDATE_CANNOT_SHRINK";
               return false;
              }
            return true;

         case V2_EVENT_REDUCTION_COMPLETED:
            if(state.status!=V2_SEQ_ACTIVE && state.status!=V2_SEQ_REDUCE_ONLY && state.status!=V2_SEQ_QUARANTINED)
              {
               reason="SEQUENCE_NOT_MANAGEABLE";
               return false;
              }
            if(state.reduction_reason=="")
              {
               reason="REDUCTION_MANDATE_NOT_ACTIVE";
               return false;
              }
            if(state.reduction_remaining>1e-12)
              {
               reason="REDUCTION_COMPLETION_VOLUME_REMAINS";
               return false;
              }
            if(event.retrace_advance!=state.retrace_advance_pending)
              {
               reason="REDUCTION_COMPLETION_RETRACE_MISMATCH";
               return false;
              }
            if(event.retrace_advance && (event.price<0.0 || !MathIsValidNumber(event.price)))
              {
               reason="REDUCTION_COMPLETION_RETRACE_PRICE_INVALID";
               return false;
              }
            return true;

         case V2_EVENT_SEQUENCE_ENDED:
            if(state.status==V2_SEQ_IDLE || state.status==V2_SEQ_ENDED)
              {
               reason="SEQUENCE_NOT_ACTIVE";
               return false;
              }
            if(state.standing_volume>1e-12)
              {
               reason="SEQUENCE_END_REQUIRES_FLAT";
               return false;
              }
            return true;

         case V2_EVENT_RECOVERY_QUARANTINED:
            if(state.status==V2_SEQ_IDLE || state.status==V2_SEQ_ENDED)
              {
               reason="RECOVERY_QUARANTINE_REQUIRES_MANAGEABLE_SEQUENCE";
               return false;
              }
            return true;
         case V2_EVENT_OPERATIONAL_STATE_CHANGED:
            return true;
        }
      reason="UNSUPPORTED_TRANSITION";
      return false;
     }

   bool Apply(const V2DomainEvent &event,V2SequenceState &state,string &reason) const
     {
      if(!CanApply(event,state,reason))
        {
         if(reason=="EVENT_ALREADY_APPLIED")
           {
            reason="";
            return true;
           }
         return false;
        }

      if(state.sequence_id=="" && event.sequence_id!="")
         state.sequence_id=event.sequence_id;
      state.last_event_number=event.canonical_number;
      state.last_state_version=event.state_version;
      state.last_event_id=event.event_id;
      state.last_event_hash=event.event_hash;

      switch(event.kind)
        {
         case V2_EVENT_SEQUENCE_STARTED:
            state.status=V2_SEQ_ACTIVE;
            state.direction=event.direction;
            state.symbol=event.symbol;
            state.started_at=event.occurred_at;
            state.ended_at=0;
            break;
         case V2_EVENT_FILL_PARTIAL:
         case V2_EVENT_FILL_COMPLETE:
            if(event.risk_effect==V2_RISK_INCREASE)
              {
               double next_volume=state.standing_volume+event.volume;
               if(next_volume>0.0)
                  state.average_entry_price=((state.average_entry_price*state.standing_volume)+(event.price*event.volume))/next_volume;
               state.standing_volume=next_volume;
              }
            else if(event.risk_effect==V2_RISK_DECREASE)
              {
               state.standing_volume=MathMax(0.0,state.standing_volume-event.volume);
               state.realized_pl+=event.realized_pl;
               if(state.reduction_remaining>1e-12)
                  state.reduction_remaining=MathMax(0.0,state.reduction_remaining-event.volume);
              }
            if(event.level_index+1>state.level_count)
               state.level_count=event.level_index+1;
            break;
         case V2_EVENT_LEVEL_CLOSED:
            state.realized_pl+=event.realized_pl;
            break;
         case V2_EVENT_RETRACE_POINTER_MOVED:
            state.retrace_price=event.price;
            break;
         case V2_EVENT_RESCUE_ARMED:
            state.rescue_armed=true;
            break;
         case V2_EVENT_REDUCTION_MANDATED:
            if(state.status==V2_SEQ_ACTIVE)
               state.status=V2_SEQ_REDUCE_ONLY;
            state.reduction_remaining=event.volume;
            state.reduction_semantic_level=event.level_index;
            state.reduction_reason=event.reason_code;
            state.retrace_advance_pending=event.retrace_advance;
            break;
         case V2_EVENT_REDUCTION_COMPLETED:
            if(event.retrace_advance)
               state.retrace_price=event.price;
            state.reduction_remaining=0.0;
            state.reduction_semantic_level=-1;
            state.reduction_reason="";
            state.retrace_advance_pending=false;
            if(state.status==V2_SEQ_REDUCE_ONLY)
               state.status=V2_SEQ_ACTIVE;
            break;
         case V2_EVENT_RECOVERY_QUARANTINED:
            state.status=V2_SEQ_QUARANTINED;
            break;
         case V2_EVENT_SEQUENCE_ENDED:
            state.status=V2_SEQ_ENDED;
            state.ended_at=event.occurred_at;
            state.standing_volume=0.0;
            state.reduction_remaining=0.0;
            state.reduction_semantic_level=-1;
            state.reduction_reason="";
            state.retrace_advance_pending=false;
            break;
         default:
            break;
        }
      reason="";
      return true;
     }
  };

class CV2OrderIntentMachine
  {
public:
   bool CanTransition(const ENUM_V2_ORDER_INTENT_STATUS current,
                       const ENUM_V2_ORDER_INTENT_STATUS next,
                       string &reason) const
     {
      reason="";
      if(current==next)
         return true;
      switch(current)
        {
         case V2_INTENT_PLANNED:
            if(next==V2_INTENT_PERSISTED)
               return true;
            break;
         case V2_INTENT_PERSISTED:
            if(next==V2_INTENT_SUBMITTED || next==V2_INTENT_CANCELLED)
               return true;
            break;
          case V2_INTENT_SUBMITTED:
             if(next==V2_INTENT_ACCEPTED || next==V2_INTENT_PARTIAL || next==V2_INTENT_FILLED || next==V2_INTENT_REJECTED || next==V2_INTENT_CANCELLED || next==V2_INTENT_RECONCILE_REQUIRED)
                return true;
            break;
         case V2_INTENT_ACCEPTED:
            if(next==V2_INTENT_PARTIAL || next==V2_INTENT_FILLED || next==V2_INTENT_REJECTED || next==V2_INTENT_CANCELLED || next==V2_INTENT_RECONCILE_REQUIRED)
               return true;
            break;
         case V2_INTENT_PARTIAL:
            if(next==V2_INTENT_FILLED || next==V2_INTENT_CANCELLED || next==V2_INTENT_RECONCILE_REQUIRED)
               return true;
            break;
         case V2_INTENT_RECONCILE_REQUIRED:
            if(next==V2_INTENT_ACCEPTED || next==V2_INTENT_PARTIAL || next==V2_INTENT_FILLED || next==V2_INTENT_REJECTED || next==V2_INTENT_CANCELLED)
               return true;
            break;
         default:
            break;
        }
      reason="ILLEGAL_ORDER_INTENT_TRANSITION";
      return false;
     }

   bool Apply(const ENUM_V2_ORDER_INTENT_STATUS next,
               V2OrderIntent &intent,
               string &reason) const
     {
      if(!CanTransition(intent.status,next,reason))
         return false;
      intent.status=next;
      return true;
     }
  };

#endif
