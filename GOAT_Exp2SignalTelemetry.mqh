#ifndef GOAT_EXP2_SIGNAL_TELEMETRY_MQH
#define GOAT_EXP2_SIGNAL_TELEMETRY_MQH
// Passive demo-only observation. No wire request, permission or trade result is changed.
SGOATAIWireV2State g_exp2_consumed_wire;
bool g_exp2_wire_applied=false,g_exp2_wire_verified=false,g_exp2_signal_context=false,g_exp2_order_attempted=false;
bool g_exp2_signal_edge=false,g_exp2_active[2],g_exp2_seen[2];
string g_exp2_episode[2],g_exp2_context_key="";
long g_exp2_cached_magic=-1;
ulong g_exp2_signal_ordinal=0;
string g_exp2_strategy_key="",g_exp2_boot="",g_exp2_signal_id="",g_exp2_decision="",g_exp2_reason="",g_exp2_gate_utc="",g_exp2_non_ai_suppression="";
int g_exp2_side=0,g_exp2_indicator_side=0;
ulong g_exp2_ordinal=0;
ulong g_exp2_orders[],g_exp2_positions[];
string g_exp2_order_signals[],g_exp2_position_signals[];

bool GoatExp2ObserverEnabled()
  {
   return AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO
      && !MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_OPTIMIZATION) && !MQLInfoInteger(MQL_FORWARD);
  }

string GoatExp2Utc()
  {
   string value=TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS);
   StringReplace(value,".","-");StringReplace(value," ","T");return value+"Z";
  }

void GoatExp2RememberOrder(const ulong order,const string signal)
  {
   if(order==0 || signal=="") return;
   int n=ArraySize(g_exp2_orders);ArrayResize(g_exp2_orders,n+1);ArrayResize(g_exp2_order_signals,n+1);
   g_exp2_orders[n]=order;g_exp2_order_signals[n]=signal;
  }

void GoatExp2Write(const string kind,const string signal,const int side,const int indicator_side,
                  const string decision,const string reason,const string execution,
                  const ulong ticket=0,const ulong order=0,const ulong position=0,
                  const uint retcode=0,const double net_cash=0.0,const long deal_time_msc=0)
  {
   if(!GoatExp2ObserverEnabled()) return;
   if(g_exp2_strategy_key=="" && !GOATSha256Utf8((string)MAGIC1,g_exp2_strategy_key)) return;
   if(g_exp2_boot=="") g_exp2_boot=(string)GetTickCount64()+"-"+(string)GetMicrosecondCount();
   string ticket_hash="",order_hash="",position_hash="";
   if(ticket!=0) GOATSha256Utf8("deal:"+(string)ticket,ticket_hash);
   if(order!=0) GOATSha256Utf8("order:"+(string)order,order_hash);
   if(position!=0) GOATSha256Utf8("position:"+(string)position,position_hash);
   FolderCreate("GOATExp2Signals");
   int file=FileOpen("GOATExp2Signals\\"+g_exp2_strategy_key+".csv",
                     FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',',CP_UTF8);
   if(file==INVALID_HANDLE) {Print("EXP2_SIGNAL_TELEMETRY_WRITE_UNAVAILABLE");return;}
   if(FileSize(file)==0)
      FileWrite(file,"schema","event_type","event_id","utc_time","utc_precision","broker_time",
                "symbol","strategy_key","side","indicator_side","signal_id","ai_lean","ai_probability",
                "probability_authority","wire_verified","wire_available","wire_read_at","wire_valid_until","wire_freshness","gate_updated_utc",
                "decision","reason_code","non_ai_suppression","execution_status","ticket_hash","order_hash","position_hash",
                "retcode","net_cash","deal_server_time_msc");
   FileSeek(file,0,SEEK_END);
   string lean="",probability="",authority="NONE",read_at="",valid_until="";
   bool available=false;
   if(g_exp2_wire_applied && kind=="signal_ai_gate")
     {
      lean=g_exp2_consumed_wire.direction;authority=g_exp2_consumed_wire.probability_authority;
      available=g_exp2_consumed_wire.directive_available;
      if(g_exp2_wire_verified && available) probability=DoubleToString(g_exp2_consumed_wire.decision_probability,12);
      read_at=g_exp2_consumed_wire.read_at;valid_until=g_exp2_consumed_wire.valid_until;
     }
   string event_id=g_exp2_strategy_key+"-"+g_exp2_boot+"-"+(string)(++g_exp2_ordinal);
   // TAKE/VETO is AI-gate permission, never proof of an executable entry or fill.
   FileWrite(file,"goat-exp2-signal-observation-v1",kind,event_id,GoatExp2Utc(),"seconds",
             TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),_Symbol,g_exp2_strategy_key,
             side==OP_BUY?"BUY":"SELL",indicator_side<0?"":(indicator_side==OP_BUY?"BUY":"SELL"),signal,lean,probability,
             authority,(kind=="signal_ai_gate"?g_exp2_wire_verified:false),available,read_at,valid_until,
             kind!="signal_ai_gate"?"NOT_APPLICABLE":(!g_exp2_wire_applied?"NOT_APPLIED":(g_exp2_wire_verified?"VERIFIED_AT_GATE_UPDATE":"UNVERIFIED_AT_GATE_UPDATE")),
             kind=="signal_ai_gate"?g_exp2_gate_utc:"",decision,reason,
             (kind=="signal_ai_gate" || kind=="signal_execution" || kind=="order_result")?g_exp2_non_ai_suppression:"",execution,
             ticket_hash,order_hash,position_hash,retcode,DoubleToString(net_cash,12),deal_time_msc);
   FileFlush(file);FileClose(file);
  }

void GoatExp2ConsumedWire(const bool applied,const bool verified,SGOATAIWireV2State &state)
  {
   if(!GoatExp2ObserverEnabled()) return;
   g_exp2_wire_applied=applied;g_exp2_wire_verified=verified;g_exp2_gate_utc=GoatExp2Utc();
   if(applied) g_exp2_consumed_wire=state;
  }

void GoatExp2EvaluationBegin()
  {
   g_exp2_signal_context=false;
   g_exp2_seen[0]=false;g_exp2_seen[1]=false;
  }

void GoatExp2EvaluationEnd()
  {
   for(int side=0;side<2;side++)
      if(!g_exp2_seen[side]) {g_exp2_active[side]=false;g_exp2_episode[side]="";}
  }

void GoatExp2Signal(const int indicator_side,const int side,const bool bias_allowed,const bool news_allowed,const bool rescue_suppressed)
  {
   if(!GoatExp2ObserverEnabled()) return;
   if(g_exp2_cached_magic!=(long)MAGIC1 || g_exp2_context_key!=_Symbol)
     {
      if(!GOATSha256Utf8((string)MAGIC1,g_exp2_strategy_key)) return;
      g_exp2_cached_magic=(long)MAGIC1;g_exp2_context_key=_Symbol;
      g_exp2_active[0]=false;g_exp2_active[1]=false;
      g_exp2_episode[0]="";g_exp2_episode[1]="";
     }
   if(g_exp2_boot=="") g_exp2_boot=(string)GetTickCount64()+"-"+(string)GetMicrosecondCount();
   g_exp2_seen[side]=true;
   g_exp2_signal_edge=!g_exp2_active[side];
   g_exp2_active[side]=true;
   if(g_exp2_signal_edge)
      g_exp2_episode[side]=g_exp2_strategy_key+"-"+g_exp2_boot+"-signal-"+(string)(++g_exp2_signal_ordinal);
   g_exp2_signal_id=g_exp2_episode[side];
   g_exp2_side=side;g_exp2_indicator_side=indicator_side;g_exp2_signal_context=true;g_exp2_order_attempted=false;
   bool ai_allows=!g_exp2_wire_applied || (g_exp2_wire_verified && g_exp2_consumed_wire.directive_available
      && g_exp2_consumed_wire.actionable
      && (indicator_side==OP_BUY ? g_exp2_consumed_wire.signed_probability_percent>0 : g_exp2_consumed_wire.signed_probability_percent<0));
   g_exp2_decision=!g_exp2_wire_applied?"TAKE":(ai_allows?"TAKE":(g_exp2_wire_verified && g_exp2_consumed_wire.directive_available?"VETO":"NO_WIRE"));
   g_exp2_non_ai_suppression=rescue_suppressed?"BIAS_RESCUE_ACTIVE":(!bias_allowed && ai_allows?"OTHER_BIAS_GATE_STATE":"");
   g_exp2_reason=!g_exp2_wire_applied?"CONTROL_AI_DISABLED":
      (ai_allows?"AI_GATE_ALLOWED":(g_exp2_consumed_wire.reason_code!=""?g_exp2_consumed_wire.reason_code:"AI_GATE_BLOCKED"));
   if(g_exp2_signal_edge) GoatExp2Write("signal_ai_gate",g_exp2_signal_id,side,indicator_side,g_exp2_decision,g_exp2_reason,
                news_allowed?"LATER_ENTRY_GATES_NOT_EVALUATED":"NEWS_BLOCKED");
  }

void GoatExp2SignalEnd()
  {
   if(g_exp2_signal_context && g_exp2_signal_edge && !g_exp2_order_attempted)
      GoatExp2Write("signal_execution",g_exp2_signal_id,g_exp2_side,g_exp2_indicator_side,g_exp2_decision,g_exp2_reason,"NO_ORDER_SEND_OBSERVED");
   g_exp2_signal_context=false;g_exp2_signal_id="";
  }

void GoatExp2OrderResult(const int side,const bool sent,MqlTradeResult &result)
  {
   if(!GoatExp2ObserverEnabled()) return;
   string signal=(g_exp2_signal_context && side==g_exp2_side)?g_exp2_signal_id:"";
   if(signal!="") g_exp2_order_attempted=true;
   bool accepted=sent && (result.retcode==10008 || result.retcode==10009 || result.retcode==10010);
   if(accepted) GoatExp2RememberOrder(result.order,signal);
   GoatExp2Write("order_result",signal,side,signal!=""?g_exp2_indicator_side:-1,
                signal!=""?g_exp2_decision:"",signal!=""?g_exp2_reason:"NO_SIGNAL_CONTEXT",
                accepted?"SEND_ACCEPTED_NOT_FILL":"SEND_REJECTED",result.deal,result.order,0,result.retcode);
  }

void GoatExp2Deal(const ulong deal)
  {
   if(!GoatExp2ObserverEnabled() || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) return;
   int type=(int)HistoryDealGetInteger(deal,DEAL_TYPE);
   if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) return;
   ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER),position=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
   string signal="";
   for(int i=0;i<ArraySize(g_exp2_orders);i++) if(g_exp2_orders[i]==order) {signal=g_exp2_order_signals[i];break;}
   for(int i=0;signal=="" && i<ArraySize(g_exp2_positions);i++) if(g_exp2_positions[i]==position) signal=g_exp2_position_signals[i];
   if(signal=="" && HistoryDealGetInteger(deal,DEAL_MAGIC)!=MAGIC1) return;
   int entry=(int)HistoryDealGetInteger(deal,DEAL_ENTRY);
   if(entry==DEAL_ENTRY_IN && signal!="")
     {
      int n=ArraySize(g_exp2_positions);ArrayResize(g_exp2_positions,n+1);ArrayResize(g_exp2_position_signals,n+1);
      g_exp2_positions[n]=position;g_exp2_position_signals[n]=signal;
     }
   double net=HistoryDealGetDouble(deal,DEAL_PROFIT)+HistoryDealGetDouble(deal,DEAL_COMMISSION)
             +HistoryDealGetDouble(deal,DEAL_SWAP)+HistoryDealGetDouble(deal,DEAL_FEE);
   GoatExp2Write("deal",signal,type==DEAL_TYPE_BUY?OP_BUY:OP_SELL,-1,
                "",signal==""?"NO_LOGGED_SIGNAL_JOIN":"LOGGED_ORDER_POSITION_JOIN",
                entry==DEAL_ENTRY_IN?"ENTRY_FILL":"EXIT_OR_PARTIAL_FILL",deal,order,position,0,net,
                HistoryDealGetInteger(deal,DEAL_TIME_MSC));
  }
#endif
