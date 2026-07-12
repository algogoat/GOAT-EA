#ifndef GOAT_V2_BROKER_GATEWAY_MQH
#define GOAT_V2_BROKER_GATEWAY_MQH

#include "Domain.mqh"
#include "Identity.mqh"
#include "SafetyKernel.mqh"
#include "StateDB.mqh"
#include "Receipts.mqh"

#define V2_GATEWAY_RING_CAPACITY 512

enum ENUM_V2_GATEWAY_STATUS
  {
   V2_GATEWAY_DENIED=0,
   V2_GATEWAY_SUBMITTED=1,
   V2_GATEWAY_REJECTED=2,
   V2_GATEWAY_RECONCILE_REQUIRED=3
  };

struct V2GatewayOutcome
  {
   ENUM_V2_GATEWAY_STATUS status;
   V2SafetyDecision       safety;
   string                 order_intent_id;
   bool                   order_send_returned_true;
   bool                   durable_before_send;
   bool                   requires_manage_only;
   ulong                  request_id;
   ulong                  order_ticket;
   ulong                  deal_ticket;
   uint                   retcode;
   uint                   retcode_external;
   string                 broker_comment;
   string                 reason_code;
   V2DomainEvent          domain_event;

   void Reset(void)
     {
      status=V2_GATEWAY_DENIED;
      safety.Reset();
      order_intent_id="";
      order_send_returned_true=false;
      durable_before_send=false;
      requires_manage_only=false;
      request_id=0;
      order_ticket=0;
      deal_ticket=0;
      retcode=0;
      retcode_external=0;
      broker_comment="";
      reason_code="";
      domain_event.Reset();
     }
  };

class CV2BrokerGateway
  {
private:
   CV2Identity       *m_identity;
   CV2SafetyKernel   *m_kernel;
   CV2StateDB        *m_database;
   CV2ReceiptBuilder *m_receipts;
   string             m_manifest_id;
   string             m_broker_profile_version;
   bool               m_initialized;
   bool               m_new_risk_enabled;
   bool               m_ring_overflow;
   bool               m_requires_full_reconciliation;
   ENUM_V2_OPERATIONAL_STATE m_operational_state;
   double             m_peak_equity;
   int                m_consecutive_broker_errors;
   V2TradeObservation m_ring[V2_GATEWAY_RING_CAPACITY];
   int                m_ring_head;
   int                m_ring_tail;
   int                m_ring_count;

   double NormalizeVolumeDown(const string symbol,const double requested) const
     {
      double step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
      double minimum=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
      double maximum=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
      if(step<=0.0 || minimum<=0.0 || maximum<minimum || requested<=0.0)
         return 0.0;
      double normalized=MathFloor((requested+1e-12)/step)*step;
      if(normalized<minimum-1e-12)
         return 0.0;
      normalized=MathMin(normalized,maximum);
      return NormalizeDouble(normalized,8);
     }

   double NormalizePrice(const string symbol,const double price) const
     {
      if(price<=0.0)
         return 0.0;
      double tick=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tick<=0.0)
         tick=SymbolInfoDouble(symbol,SYMBOL_POINT);
      if(tick<=0.0)
         return 0.0;
      return MathRound(price/tick)*tick;
     }

   ENUM_ORDER_TYPE_FILLING FillingMode(const string symbol) const
     {
      long flags=0;
      if(!SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE,flags))
         return ORDER_FILLING_FOK;
      if((flags&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
         return ORDER_FILLING_IOC;
      if((flags&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
         return ORDER_FILLING_FOK;
      return ORDER_FILLING_RETURN;
     }

   bool RetcodeAccepted(const uint retcode) const
     {
      return(retcode==TRADE_RETCODE_PLACED ||
             retcode==TRADE_RETCODE_DONE ||
             retcode==TRADE_RETCODE_DONE_PARTIAL ||
             retcode==TRADE_RETCODE_NO_CHANGES ||
             retcode==TRADE_RETCODE_ORDER_CHANGED);
     }

   bool RetcodeRequiresReconciliation(const uint retcode) const
     {
      return(retcode==TRADE_RETCODE_TIMEOUT || retcode==TRADE_RETCODE_CONNECTION || retcode==0);
     }

   bool PrepareAction(const V2BrokerAction &source,V2BrokerAction &action,string &reason) const
     {
      reason="";
      action=source;
      if(action.symbol=="")
         action.symbol=_Symbol;
      if(!SymbolSelect(action.symbol,true))
        {
         reason="SYMBOL_SELECTION_FAILED";
         return false;
        }

      if(action.action==V2_ACTION_CLOSE || action.action==V2_ACTION_PARTIAL_CLOSE || action.action==V2_ACTION_MODIFY)
        {
         if(action.position_ticket==0 || !PositionSelectByTicket(action.position_ticket))
           {
            reason="POSITION_TARGET_NOT_FOUND";
            return false;
           }
         long position_magic=PositionGetInteger(POSITION_MAGIC);
         string position_symbol=PositionGetString(POSITION_SYMBOL);
         if((ulong)position_magic!=action.magic || position_symbol!=action.symbol)
           {
            reason="POSITION_OWNERSHIP_MISMATCH";
            return false;
           }
         ENUM_POSITION_TYPE position_type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         action.direction=(position_type==POSITION_TYPE_BUY ? V2_DIR_LONG : V2_DIR_SHORT);
         const ulong actual_position_id=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
         if(action.position_id==0 || action.position_id!=actual_position_id)
           {
            reason="POSITION_JOURNAL_LINEAGE_MISMATCH";
            return false;
           }
         action.position_id=actual_position_id;
         action.current_stop_loss=PositionGetDouble(POSITION_SL);
         action.current_take_profit=PositionGetDouble(POSITION_TP);
         double position_volume=PositionGetDouble(POSITION_VOLUME);
         if(action.action==V2_ACTION_CLOSE)
            action.volume=position_volume;
         else if(action.action==V2_ACTION_PARTIAL_CLOSE)
            action.volume=MathMin(action.volume,position_volume);
        }

      if(action.action==V2_ACTION_OPEN || action.action==V2_ACTION_ADD || action.action==V2_ACTION_PARTIAL_CLOSE || action.action==V2_ACTION_CLOSE)
        {
         action.volume=NormalizeVolumeDown(action.symbol,action.volume);
         if(action.volume<=0.0)
           {
            reason="ACTION_VOLUME_NORMALIZATION_FAILED";
            return false;
           }
        }
      action.price=NormalizePrice(action.symbol,action.price);
      action.stop_loss=NormalizePrice(action.symbol,action.stop_loss);
      action.take_profit=NormalizePrice(action.symbol,action.take_profit);
      return true;
     }

   bool BuildRequest(const V2BrokerAction &action,MqlTradeRequest &request,string &reason) const
     {
      reason="";
      ZeroMemory(request);
      request.magic=action.magic;
      request.symbol=action.symbol;
      request.comment="GOAT2:"+StringSubstr(action.order_intent_id,0,24);

      MqlTick tick;
      if(!SymbolInfoTick(action.symbol,tick))
        {
         reason="SYMBOL_TICK_UNAVAILABLE";
         return false;
        }

      if(action.action==V2_ACTION_OPEN || action.action==V2_ACTION_ADD)
        {
         request.action=TRADE_ACTION_DEAL;
         request.type=(action.direction==V2_DIR_LONG ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
         request.volume=action.volume;
         request.price=(action.direction==V2_DIR_LONG ? tick.ask : tick.bid);
         request.sl=action.stop_loss;
         request.tp=action.take_profit;
         request.type_filling=FillingMode(action.symbol);
         request.type_time=ORDER_TIME_GTC;
         return true;
        }

      if(action.action==V2_ACTION_PARTIAL_CLOSE || action.action==V2_ACTION_CLOSE)
        {
         request.action=TRADE_ACTION_DEAL;
         request.position=action.position_ticket;
         request.type=(action.direction==V2_DIR_LONG ? ORDER_TYPE_SELL : ORDER_TYPE_BUY);
         request.volume=action.volume;
         request.price=(action.direction==V2_DIR_LONG ? tick.bid : tick.ask);
         request.type_filling=FillingMode(action.symbol);
         request.type_time=ORDER_TIME_GTC;
         return true;
        }

      if(action.action==V2_ACTION_MODIFY)
        {
         request.action=TRADE_ACTION_SLTP;
         request.position=action.position_ticket;
         request.sl=action.stop_loss;
         request.tp=action.take_profit;
         return true;
        }

      if(action.action==V2_ACTION_CANCEL)
        {
         if(action.order_ticket==0 || !OrderSelect(action.order_ticket))
           {
            reason="ORDER_TARGET_NOT_FOUND";
            return false;
           }
         if((ulong)OrderGetInteger(ORDER_MAGIC)!=action.magic || OrderGetString(ORDER_SYMBOL)!=action.symbol)
           {
            reason="ORDER_OWNERSHIP_MISMATCH";
            return false;
           }
         request.action=TRADE_ACTION_REMOVE;
         request.order=action.order_ticket;
         return true;
        }
      reason="UNSUPPORTED_GATEWAY_ACTION";
      return false;
     }

   void ExposureSnapshot(const string symbol,const ulong magic,V2ExposureSnapshot &snapshot) const
     {
      ZeroMemory(snapshot);
      const int total=PositionsTotal();
      for(int i=0;i<total;i++)
        {
         ulong ticket=PositionGetTicket(i);
         if(ticket==0 || !PositionSelectByTicket(ticket))
            continue;
         if((ulong)PositionGetInteger(POSITION_MAGIC)!=magic)
            continue;
         double volume=PositionGetDouble(POSITION_VOLUME);
         snapshot.portfolio_lots+=volume;
         if(PositionGetString(POSITION_SYMBOL)==symbol)
            snapshot.symbol_lots+=volume;
        }
      snapshot.sequence_lots=snapshot.symbol_lots;
     }

   bool BuildSafetyContext(const V2BrokerAction &action,
                           const MqlTradeRequest &request,
                           V2SafetyContext &context,
                           MqlTradeCheckResult &check)
     {
      ZeroMemory(context);
      ZeroMemory(check);
      context.account.margin_mode=(ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
      context.account.balance=AccountInfoDouble(ACCOUNT_BALANCE);
      context.account.equity=AccountInfoDouble(ACCOUNT_EQUITY);
      context.account.margin=AccountInfoDouble(ACCOUNT_MARGIN);
      context.account.free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(context.account.equity>m_peak_equity)
         m_peak_equity=context.account.equity;
      context.account.peak_equity=m_peak_equity;

      context.symbol.symbol=action.symbol;
      context.symbol.trade_mode=(ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(action.symbol,SYMBOL_TRADE_MODE);
      MqlTick tick;
      SymbolInfoTick(action.symbol,tick);
      context.symbol.bid=tick.bid;
      context.symbol.ask=tick.ask;
      context.symbol.point=SymbolInfoDouble(action.symbol,SYMBOL_POINT);
      context.symbol.tick_size=SymbolInfoDouble(action.symbol,SYMBOL_TRADE_TICK_SIZE);
      context.symbol.volume_min=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_MIN);
      context.symbol.volume_max=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_MAX);
      context.symbol.volume_step=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_STEP);
      context.symbol.stops_level_points=(int)SymbolInfoInteger(action.symbol,SYMBOL_TRADE_STOPS_LEVEL);
      context.symbol.freeze_level_points=(int)SymbolInfoInteger(action.symbol,SYMBOL_TRADE_FREEZE_LEVEL);
      ExposureSnapshot(action.symbol,action.magic,context.exposure);
      context.exposure.projected_sequence_loss=MathMax(0.0,action.projected_loss_delta);
      context.exposure.projected_portfolio_loss=context.exposure.projected_sequence_loss;

      context.operational_state=m_operational_state;
      context.database_healthy=(m_database!=NULL && m_database.IsOpen() && m_database.IsWritable());
      context.writer_lease_held=(m_database!=NULL && (m_database.HasLease() || !m_database.IsDurable()));
      context.new_risk_enabled=m_new_risk_enabled;
      context.session_allows_new_risk=true;
      context.feed_allows_new_risk=true;
      context.license_allows_new_risk=true;
      context.consecutive_broker_errors=m_consecutive_broker_errors;

      ResetLastError();
      context.order_check_ok=OrderCheck(request,check);
      context.order_check_margin=check.margin;
      context.order_check_margin_free=check.margin_free;
      if(action.risk_effect==V2_RISK_DECREASE)
         context.order_check_ok=true;
      return true;
     }

   void BuildPreSubmissionReceipt(const V2BrokerAction &action,
                                  const MqlTradeRequest &request,
                                  const V2SafetyDecision &decision,
                                  V2Receipt &receipt) const
     {
      receipt.Reset();
      receipt.kind=V2_RECEIPT_ORDER_SUBMISSION;
      receipt.occurred_at_msc=(long)TimeCurrent()*1000;
      receipt.deployment_id=m_identity.DeploymentId();
      receipt.portfolio_generation_id=m_identity.GenerationId();
      receipt.strategy_member_id=m_identity.MemberId();
      receipt.sequence_id=action.sequence_id;
      receipt.order_intent_id=action.order_intent_id;
      receipt.state_version=action.state_version;
      receipt.level_index=action.level_index;
      receipt.experiment_manifest_id=m_manifest_id;
      receipt.symbol=action.symbol;
      receipt.direction=action.direction;
      receipt.action=action.action;
      receipt.risk_effect=decision.risk_effect;
      receipt.kernel_verdict=decision.verdict;
      receipt.kernel_reason=decision.reason_code;
      receipt.policy_reason=action.reason_code;
      receipt.policy_verdict="BROKER_ACTION_AUTHORIZED";
      receipt.feature_readiness_mask="SEE_CAUSAL_DOMAIN_RECEIPT";
      receipt.kernel_invariant_snapshot=StringFormat("verdict:%d|riskEffect:%d|volume:%.10f|price:%.10f|sl:%.10f|tp:%.10f",
                                                      (int)decision.verdict,(int)decision.risk_effect,
                                                      decision.normalized_volume,decision.normalized_price,
                                                      decision.normalized_stop_loss,decision.normalized_take_profit);
      receipt.broker_profile_version=m_broker_profile_version;
      receipt.requested_volume=request.volume;
      receipt.requested_price=request.price;
      receipt.stop_loss=request.sl;
      receipt.take_profit=request.tp;
     }

   bool PersistKernelVeto(const V2BrokerAction &action,
                          const MqlTradeRequest &request,
                          const V2SafetyDecision &decision,
                          string &reason)
     {
      V2Receipt receipt;
      BuildPreSubmissionReceipt(action,request,decision,receipt);
      receipt.kind=V2_RECEIPT_KERNEL_VETO;
      receipt.state_version=(action.state_version>0 ? action.state_version-1 : 0);
      receipt.policy_verdict="BROKER_ACTION_VETOED";
      receipt.kernel_reason=decision.reason_code;
      if(!m_receipts.Build(receipt,reason)) return false;
      return m_database.StoreReceipt(receipt,reason);
     }

public:
                     CV2BrokerGateway(void)
     {
      m_identity=NULL;
      m_kernel=NULL;
      m_database=NULL;
      m_receipts=NULL;
      m_manifest_id="";
      m_broker_profile_version="";
      m_initialized=false;
      m_new_risk_enabled=false;
      m_ring_overflow=false;
      m_requires_full_reconciliation=false;
      m_operational_state=V2_OP_MANAGE_ONLY;
      m_peak_equity=0.0;
      m_consecutive_broker_errors=0;
      m_ring_head=0;
      m_ring_tail=0;
      m_ring_count=0;
     }

   bool Initialize(CV2Identity &identity,
                   CV2SafetyKernel &kernel,
                   CV2StateDB &database,
                   CV2ReceiptBuilder &receipts,
                   const string manifest_id,
                   const string broker_profile_version,
                   const double durable_peak_equity,
                   const bool enable_new_risk,
                   string &reason)
     {
      reason="";
      if(!database.IsOpen())
        {
         reason="GATEWAY_DATABASE_NOT_OPEN";
         return false;
        }
      m_identity=&identity;
      m_kernel=&kernel;
      m_database=&database;
      m_receipts=&receipts;
      m_manifest_id=manifest_id;
      m_broker_profile_version=broker_profile_version;
      m_new_risk_enabled=enable_new_risk;
      m_operational_state=(enable_new_risk ? V2_OP_NORMAL : V2_OP_MANAGE_ONLY);
      m_peak_equity=MathMax(AccountInfoDouble(ACCOUNT_EQUITY),durable_peak_equity);
      m_initialized=true;
      return true;
     }

   void SetOperationalState(const ENUM_V2_OPERATIONAL_STATE state)
     {
      m_operational_state=state;
      if(state!=V2_OP_NORMAL)
         m_new_risk_enabled=false;
     }

   void SetNewRiskEnabled(const bool enabled)
     {
      m_new_risk_enabled=enabled;
      if(enabled && m_operational_state==V2_OP_MANAGE_ONLY)
         m_operational_state=V2_OP_NORMAL;
     }

   void SetDurablePeakEquity(const double peak_equity)
     {
      if(MathIsValidNumber(peak_equity) && peak_equity>m_peak_equity)
         m_peak_equity=peak_equity;
     }

   ENUM_V2_GATEWAY_STATUS Execute(const V2BrokerAction &source,V2GatewayOutcome &outcome)
     {
      outcome.Reset();
      if(!m_initialized || m_identity==NULL || m_kernel==NULL || m_database==NULL || m_receipts==NULL)
        {
         outcome.reason_code="GATEWAY_NOT_INITIALIZED";
         return outcome.status;
        }

      V2BrokerAction requested=source;
      requested.magic=m_identity.Magic();
      V2BrokerAction action;
      string reason="";
      if(!PrepareAction(requested,action,reason))
        {
         outcome.reason_code=reason;
         return outcome.status;
        }

      ENUM_V2_RISK_EFFECT classified=V2_RISK_UNKNOWN;
      V2SymbolSnapshot symbol_snapshot;
      ZeroMemory(symbol_snapshot);
      symbol_snapshot.symbol=action.symbol;
      symbol_snapshot.tick_size=SymbolInfoDouble(action.symbol,SYMBOL_TRADE_TICK_SIZE);
      symbol_snapshot.volume_min=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_MIN);
      symbol_snapshot.volume_max=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_MAX);
      symbol_snapshot.volume_step=SymbolInfoDouble(action.symbol,SYMBOL_VOLUME_STEP);
      if(!m_kernel.Classify(action,symbol_snapshot,classified,reason))
        {
         outcome.reason_code=reason;
         return outcome.status;
        }
      action.risk_effect=classified;
      if(action.state_version<=0)
        {
         outcome.reason_code="ACTION_STATE_VERSION_REQUIRED";
         return outcome.status;
        }

      long ordinal=0;
      if(action.order_intent_id=="")
        {
         if(!m_database.ReserveCounter("order_intent",ordinal,reason))
           {
            if(action.risk_effect!=V2_RISK_DECREASE)
              {
               outcome.reason_code="ORDER_INTENT_COUNTER_REQUIRED:"+reason;
               return outcome.status;
              }
            ordinal=(long)TimeCurrent()*1000000+(long)(GetMicrosecondCount()%1000000);
           }
         if(!m_identity.OrderIntentId(action.sequence_id,action.action,ordinal,action.order_intent_id))
           {
            outcome.reason_code="ORDER_INTENT_ID_GENERATION_FAILED";
            return outcome.status;
           }
        }
      outcome.order_intent_id=action.order_intent_id;

      MqlTradeRequest request;
      if(!BuildRequest(action,request,reason))
        {
         outcome.reason_code=reason;
         return outcome.status;
        }
      MqlTradeCheckResult check;
      V2SafetyContext context;
      BuildSafetyContext(action,request,context,check);
      if(!m_kernel.Evaluate(action,context,outcome.safety))
        {
         outcome.reason_code=outcome.safety.reason_code;
         string veto_reason="";
         if(!PersistKernelVeto(action,request,outcome.safety,veto_reason))
           {
            outcome.requires_manage_only=true;
            outcome.reason_code+="|VETO_RECEIPT_FAILED:"+veto_reason;
           }
         return outcome.status;
        }
      if(outcome.safety.verdict!=V2_KERNEL_ALLOW && outcome.safety.verdict!=V2_KERNEL_ALLOW_REDUCE_ONLY)
        {
         outcome.reason_code=outcome.safety.reason_code;
         string veto_reason="";
         if(!PersistKernelVeto(action,request,outcome.safety,veto_reason))
           {
            outcome.requires_manage_only=true;
            outcome.reason_code+="|VETO_RECEIPT_FAILED:"+veto_reason;
           }
         return outcome.status;
        }

      action.risk_effect=outcome.safety.risk_effect;
      if(request.action==TRADE_ACTION_DEAL)
         request.volume=outcome.safety.normalized_volume;
      if(request.action==TRADE_ACTION_SLTP || request.action==TRADE_ACTION_DEAL)
        {
         request.sl=outcome.safety.normalized_stop_loss;
         request.tp=outcome.safety.normalized_take_profit;
        }

      V2OrderIntent intent;
      intent.Reset();
      intent.order_intent_id=action.order_intent_id;
      intent.sequence_id=action.sequence_id;
      intent.action=action.action;
      intent.risk_effect=action.risk_effect;
      intent.status=V2_INTENT_PERSISTED;
      intent.direction=action.direction;
      intent.symbol=action.symbol;
      intent.magic=action.magic;
      intent.level_index=action.level_index;
      intent.requested_volume=request.volume;
      intent.requested_price=request.price;
      intent.stop_loss=request.sl;
      intent.take_profit=request.tp;
      intent.position_id=action.position_id;
      intent.created_at=TimeCurrent();
      intent.reason_code=action.reason_code;

      V2Receipt receipt;
      BuildPreSubmissionReceipt(action,request,outcome.safety,receipt);
      V2PersistenceAuthorization authorization;
      if(!m_database.AuthorizeBrokerSubmission(intent,receipt,action.risk_effect==V2_RISK_DECREASE,authorization) || !authorization.broker_submission_allowed)
        {
         outcome.requires_manage_only=authorization.requires_manage_only;
         if(authorization.requires_manage_only)
           {
            m_operational_state=V2_OP_MANAGE_ONLY;
            m_new_risk_enabled=false;
           }
         outcome.reason_code=authorization.reason;
         return outcome.status;
        }
      outcome.durable_before_send=authorization.durable;
      outcome.requires_manage_only=authorization.requires_manage_only;
      if(authorization.requires_manage_only)
        {
         m_operational_state=V2_OP_MANAGE_ONLY;
         m_new_risk_enabled=false;
        }

      MqlTradeResult result;
      ZeroMemory(result);
      ResetLastError();
      const ulong send_started_micros=GetMicrosecondCount();
      bool submitted=OrderSend(request,result);
      const ulong send_latency_micros=GetMicrosecondCount()-send_started_micros;
      const bool accepted=(submitted && RetcodeAccepted(result.retcode));
      const bool terminal_action=(action.action==V2_ACTION_MODIFY || action.action==V2_ACTION_CANCEL);
      const bool terminal_action_confirmed=(terminal_action && accepted &&
                                            (result.retcode==TRADE_RETCODE_DONE ||
                                             result.retcode==TRADE_RETCODE_NO_CHANGES ||
                                             result.retcode==TRADE_RETCODE_ORDER_CHANGED));
      const bool uncertain=(submitted && ((!accepted && RetcodeRequiresReconciliation(result.retcode)) ||
                                          (terminal_action && accepted && !terminal_action_confirmed)));
      outcome.order_send_returned_true=submitted;
      outcome.request_id=(ulong)result.request_id;
      outcome.order_ticket=result.order;
      outcome.deal_ticket=result.deal;
      outcome.retcode=result.retcode;
      outcome.retcode_external=result.retcode_external;
      outcome.broker_comment=result.comment;

      intent.request_id=outcome.request_id;
      intent.order_ticket=outcome.order_ticket;
      intent.deal_ticket=outcome.deal_ticket;
      intent.retcode=result.retcode;
      intent.status=(terminal_action_confirmed ?
                     (action.action==V2_ACTION_CANCEL ? V2_INTENT_CANCELLED : V2_INTENT_FILLED) :
                     ((accepted && !uncertain) ? V2_INTENT_SUBMITTED :
                      (uncertain ? V2_INTENT_RECONCILE_REQUIRED : V2_INTENT_REJECTED)));
      intent.reason_code=(terminal_action_confirmed ?
                          (action.action==V2_ACTION_CANCEL ? "CANCEL_CONFIRMED" : "PROTECTION_MODIFY_CONFIRMED") :
                          ((accepted && !uncertain) ? "ORDER_SEND_SUBMITTED" :
                           (uncertain ? "ORDER_SEND_UNCERTAIN" : "ORDER_SEND_REJECTED")));

      V2DomainEvent event;
      event.Reset();
      event.kind=(terminal_action_confirmed ? V2_EVENT_ORDER_ACCEPTED :
                  ((accepted || uncertain) ? V2_EVENT_ORDER_SUBMITTED : V2_EVENT_ORDER_REJECTED));
      event.action=action.action;
      event.risk_effect=action.risk_effect;
      event.direction=action.direction;
      event.symbol=action.symbol;
      event.occurred_at=TimeCurrent();
      event.state_version=action.state_version;
      event.sequence_id=action.sequence_id;
      event.order_intent_id=action.order_intent_id;
      event.request_id=outcome.request_id;
      event.order_ticket=outcome.order_ticket;
      event.deal_ticket=outcome.deal_ticket;
      event.position_id=action.position_id;
      event.level_index=action.level_index;
      event.volume=request.volume;
      event.price=request.price;
      event.reason_code=intent.reason_code+":"+IntegerToString((long)result.retcode);
      string event_material=action.order_intent_id+"|"+IntegerToString((int)event.kind)+"|"+V2UlongToText(event.request_id)+"|"+V2UlongToText(event.order_ticket)+"|"+V2UlongToText(event.deal_ticket);
      m_identity.EventId(event_material,event.event_id);

      receipt.request_id=event.request_id;
      receipt.order_ticket=event.order_ticket;
      receipt.deal_ticket=event.deal_ticket;
      receipt.position_id=event.position_id;
      receipt.retcode=result.retcode;
      receipt.retcode_external=result.retcode_external;
      receipt.broker_comment=result.comment;
      receipt.accepted_volume=result.volume;
      receipt.accepted_price=result.price;
      receipt.latency_micros=send_latency_micros;
      receipt.kernel_reason=outcome.safety.reason_code;
      receipt.receipt_id="";
      receipt.payload_hash="";
      receipt.canonical_payload="";

      string persistence_reason="";
      if(!m_database.PersistSubmissionResult(intent,event,receipt,persistence_reason))
        {
         m_requires_full_reconciliation=true;
         m_operational_state=V2_OP_MANAGE_ONLY;
         m_new_risk_enabled=false;
         outcome.status=V2_GATEWAY_RECONCILE_REQUIRED;
         outcome.reason_code="POST_SUBMISSION_PERSISTENCE_FAILED:"+persistence_reason;
         return outcome.status;
        }
      outcome.domain_event=event;

      if(uncertain)
        {
         m_consecutive_broker_errors++;
         m_requires_full_reconciliation=true;
         m_operational_state=V2_OP_MANAGE_ONLY;
         m_new_risk_enabled=false;
         outcome.requires_manage_only=true;
         outcome.status=V2_GATEWAY_RECONCILE_REQUIRED;
         outcome.reason_code="SUBMISSION_RESULT_UNCERTAIN";
        }
      else if(accepted && !uncertain)
        {
         m_consecutive_broker_errors=0;
         outcome.status=V2_GATEWAY_SUBMITTED;
         outcome.reason_code=(terminal_action_confirmed ? "TERMINAL_ACTION_CONFIRMED" : "SUBMITTED_AWAITING_RECONCILIATION");
        }
      else
        {
         m_consecutive_broker_errors++;
         outcome.status=V2_GATEWAY_REJECTED;
         outcome.reason_code="BROKER_REJECTED_SUBMISSION";
        }
      return outcome.status;
     }

   void CaptureTradeTransaction(const MqlTradeTransaction &transaction,
                                const MqlTradeRequest &request,
                                const MqlTradeResult &result)
     {
      if(!m_initialized)
         return;
      if(m_ring_count>=V2_GATEWAY_RING_CAPACITY)
        {
         m_ring_overflow=true;
         m_requires_full_reconciliation=true;
         m_operational_state=V2_OP_MANAGE_ONLY;
         m_new_risk_enabled=false;
         return;
        }
      V2TradeObservation observation;
      observation.Reset();
      observation.captured_at_msc=(long)TimeCurrent()*1000;
      observation.transaction_type=(int)transaction.type;
      observation.request_id=(ulong)result.request_id;
      observation.order_ticket=transaction.order;
      observation.deal_ticket=transaction.deal;
      observation.position_id=transaction.position;
      observation.position_by_id=transaction.position_by;
      observation.symbol=transaction.symbol;
      observation.order_type=(int)transaction.order_type;
      observation.order_state=(int)transaction.order_state;
      observation.deal_type=(int)transaction.deal_type;
      observation.volume=transaction.volume;
      observation.price=transaction.price;
      observation.stop_loss=transaction.price_sl;
      observation.take_profit=transaction.price_tp;
      observation.retcode=result.retcode;
      observation.retcode_external=result.retcode_external;
      observation.comment=result.comment;
      m_ring[m_ring_tail]=observation;
      m_ring_tail=(m_ring_tail+1)%V2_GATEWAY_RING_CAPACITY;
      m_ring_count++;
     }

   int DrainTradeObservations(const int budget)
     {
      if(!m_initialized || m_database==NULL || budget<=0)
         return 0;
      int processed=0;
      while(m_ring_count>0 && processed<budget)
        {
         V2TradeObservation observation=m_ring[m_ring_head];
         string reason="";
         if(!m_database.StoreTradeObservation(observation,reason))
           {
            m_operational_state=V2_OP_MANAGE_ONLY;
            m_new_risk_enabled=false;
            break;
           }
         m_ring_head=(m_ring_head+1)%V2_GATEWAY_RING_CAPACITY;
         m_ring_count--;
         processed++;
        }
      return processed;
     }

   bool RequiresFullReconciliation(void) const { return m_requires_full_reconciliation; }
   bool RingOverflowed(void) const { return m_ring_overflow; }
   int PendingObservationCount(void) const { return m_ring_count; }
   ENUM_V2_OPERATIONAL_STATE OperationalState(void) const { return m_operational_state; }
  };

#endif
