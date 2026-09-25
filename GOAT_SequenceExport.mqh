// Opt-in fixed-tester evidence only. Native times are broker SERVER time, not UTC.
#ifndef GOAT_SEQUENCE_EXPORT_MQH
#define GOAT_SEQUENCE_EXPORT_MQH

struct GOAT_TRACE_SEQUENCE
  {
   ulong id;
   int direction;
   bool virtual_sequence,logical_active,ended,has_real_entry;
   double profit,commission,fee,swap;
  };
GOAT_TRACE_SEQUENCE g_trace_sequences[];
ulong g_trace_orders[],g_trace_order_sequences[],g_trace_positions[],g_trace_position_sequences[],g_trace_deals[];
int g_trace_files[6]={-1,-1,-1,-1,-1,-1};
bool g_trace_enabled=false,g_trace_failed=false,g_trace_tester_finished=false;
ulong g_trace_current_sequence=0,g_trace_ordinal=0,g_trace_rows=0,g_trace_entry_deals=0,g_trace_bytes=0;
long g_trace_first_time=0,g_trace_last_time=0,g_trace_last_frame=-1;
double g_trace_initial_balance=0.0;
string g_trace_path="",g_trace_error="";
bool g_trace_dirty=false;
int g_trace_history_count=0;
ulong g_trace_pending_ends[];
long g_trace_pending_end_times[];
string g_trace_pending_end_reasons[];

long GoatTraceClock()
  {
   long stamp=(long)TimeTradeServer()*1000;
   MqlTick quote;
   if(SymbolInfoTick(_Symbol,quote) && quote.time_msc>stamp) stamp=quote.time_msc;
   return stamp;
  }

void GoatTraceFail(const string reason)
  {
   if(g_trace_error=="") {g_trace_error=reason;Print("GOAT TRACE INCOMPLETE: ",reason);}
   g_trace_failed=true;
  }

void GoatTraceWritten(const uint bytes)
  {
   g_trace_rows++;g_trace_bytes+=bytes;
   if(bytes==0) GoatTraceFail("write failed");
   if(g_trace_rows>2000000) {GoatTraceFail("2000000 row resource limit exceeded");g_trace_enabled=false;}
   if(g_trace_bytes>536870912) {GoatTraceFail("512 MiB capture resource limit exceeded");g_trace_enabled=false;}
  }

int GoatTraceSequenceIndex(const ulong id)
  {
   for(int i=0;i<ArraySize(g_trace_sequences);++i) if(g_trace_sequences[i].id==id) return i;
   return -1;
  }

ulong GoatTracePositionSequence(const ulong position)
  {
   for(int i=0;i<ArraySize(g_trace_positions);++i) if(g_trace_positions[i]==position) return g_trace_position_sequences[i];
   return 0;
  }

ulong GoatTraceOrderSequence(const ulong order)
  {
   for(int i=0;i<ArraySize(g_trace_orders);++i) if(g_trace_orders[i]==order) return g_trace_order_sequences[i];
   return 0;
  }

void GoatTraceBindPosition(const ulong position,const ulong sequence)
  {
   if(position==0 || sequence==0) {GoatTraceFail("empty position/sequence join");return;}
   ulong prior=GoatTracePositionSequence(position);
   if(prior>0) {if(prior!=sequence) GoatTraceFail("position remapped to different sequence");return;}
   int count=ArraySize(g_trace_positions);
   ArrayResize(g_trace_positions,count+1);ArrayResize(g_trace_position_sequences,count+1);
   g_trace_positions[count]=position;g_trace_position_sequences[count]=sequence;
  }

ulong GoatTraceEnsureSequence(ulong &id,const int direction,const bool virtual_sequence)
  {
   if(!g_trace_enabled) return 0;
   if(id>0) return id;
   int count=ArraySize(g_trace_sequences);
   if(count>=10000) {GoatTraceFail("10000 sequence resource limit exceeded");return 0;}
   ArrayResize(g_trace_sequences,count+1);
   ZeroMemory(g_trace_sequences[count]);
   id=(ulong)count+1;
   g_trace_sequences[count].id=id;g_trace_sequences[count].direction=direction;
   g_trace_sequences[count].virtual_sequence=virtual_sequence;
   GoatTraceWritten(FileWrite(g_trace_files[1],++g_trace_ordinal,GoatTraceClock(),id,direction,virtual_sequence,"allocated","",false));
   return id;
  }

void GoatTraceActivate(const ulong id)
  {
   if(!g_trace_enabled || id==0) return;
   int index=GoatTraceSequenceIndex(id);
   if(index<0) {GoatTraceFail("activation without allocated sequence");return;}
   if(g_trace_sequences[index].logical_active) return;
   g_trace_sequences[index].logical_active=true;
   GoatTraceWritten(FileWrite(g_trace_files[1],++g_trace_ordinal,GoatTraceClock(),id,g_trace_sequences[index].direction,g_trace_sequences[index].virtual_sequence,"active","",true));
  }

void GoatTraceOrderResult(const int direction,const MqlTradeRequest &request,const MqlTradeResult &result,const bool sent)
  {
   if(!g_trace_enabled) return;
   ulong id=g_trace_current_sequence;
   if(id==0) GoatTraceFail("order result without sequence intent");
   if(result.order>0 && id>0)
     {
      ulong prior=GoatTraceOrderSequence(result.order);
      if(prior>0 && prior!=id) GoatTraceFail("order remapped to different sequence");
      else if(prior==0)
        {
         int count=ArraySize(g_trace_orders);
         ArrayResize(g_trace_orders,count+1);ArrayResize(g_trace_order_sequences,count+1);
         g_trace_orders[count]=result.order;g_trace_order_sequences[count]=id;
        }
     }
   g_trace_dirty=true; // Order/position joining is deferred to callback boundaries.
   GoatTraceWritten(FileWrite(g_trace_files[2],++g_trace_ordinal,GoatTraceClock(),id,direction,result.order,result.deal,result.retcode,sent,request.volume,result.volume,result.price));
  }

void GoatTraceDeal(const ulong deal)
  {
   if(!g_trace_enabled || deal==0) return;
   for(int i=0;i<ArraySize(g_trace_deals);++i) if(g_trace_deals[i]==deal) return;
   // Caller selected the complete native history once; never narrow it with HistoryDealSelect.
   int type=(int)HistoryDealGetInteger(deal,DEAL_TYPE);
   if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) return; // account cash reconciled separately
   if(HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol)
     {GoatTraceFail("foreign symbol trading deal in single-strategy run");return;}
   ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER);
   ulong position=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
   int entry=(int)HistoryDealGetInteger(deal,DEAL_ENTRY);
   long deal_magic=HistoryDealGetInteger(deal,DEAL_MAGIC);
   ulong sequence=GoatTracePositionSequence(position);
   ulong intent=GoatTraceOrderSequence(order);
   string join_basis="known-position";
   if(entry==DEAL_ENTRY_IN)
     {
      if(deal_magic!=MAGIC1) {GoatTraceFail("foreign entry magic");return;}
      if(sequence==0 && intent>0)
        {GoatTraceBindPosition(position,intent);sequence=intent;join_basis="known-order-to-position";}
     }
   else if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY)
     {
      // Local CTrade partial-close helpers use magic 0. Closing ownership comes
      // from the immutable opening-position join, never from closing magic alone.
      int owner=GoatTraceSequenceIndex(sequence);
      if(owner<0 || type==g_trace_sequences[owner].direction)
        {GoatTraceFail("closing deal lacks exact owned position/opposite-side join");return;}
     }
   else {GoatTraceFail("netting reversal cannot establish isolated sequence lifecycle");return;}
   if(sequence>0 && intent>0 && sequence!=intent) {GoatTraceFail("deal order/position joins disagree");return;}
   int index=GoatTraceSequenceIndex(sequence);
   if(index<0) {GoatTraceFail("unmatched native deal; no direction-based inference");return;}
   int count=ArraySize(g_trace_deals);ArrayResize(g_trace_deals,count+1);g_trace_deals[count]=deal;
   if(entry==DEAL_ENTRY_IN)
     {
      g_trace_entry_deals++;
      if(!g_trace_sequences[index].has_real_entry)
        {
         g_trace_sequences[index].has_real_entry=true;
         GoatTraceWritten(FileWrite(g_trace_files[1],++g_trace_ordinal,(long)HistoryDealGetInteger(deal,DEAL_TIME_MSC),sequence,
            g_trace_sequences[index].direction,false,"first_real","broker deal",g_trace_sequences[index].logical_active));
        }
     }
   double profit=HistoryDealGetDouble(deal,DEAL_PROFIT),commission=HistoryDealGetDouble(deal,DEAL_COMMISSION);
   double fee=HistoryDealGetDouble(deal,DEAL_FEE),swap=HistoryDealGetDouble(deal,DEAL_SWAP);
   g_trace_sequences[index].profit+=profit;g_trace_sequences[index].commission+=commission;
   g_trace_sequences[index].fee+=fee;g_trace_sequences[index].swap+=swap;
   GoatTraceWritten(FileWrite(g_trace_files[3],++g_trace_ordinal,(long)HistoryDealGetInteger(deal,DEAL_TIME_MSC),sequence,deal,order,position,
      g_trace_sequences[index].direction,type,(int)HistoryDealGetInteger(deal,DEAL_ENTRY),HistoryDealGetDouble(deal,DEAL_VOLUME),HistoryDealGetDouble(deal,DEAL_PRICE),profit,commission,fee,swap,deal_magic,join_basis));
  }

void GoatTraceDrainDeals()
  {
   if(!g_trace_enabled) return;
   // Tester boundary closes can occur after the last quote and its TimeCurrent().
   if(!HistorySelect((datetime)(g_trace_first_time/1000),(datetime)(GoatTraceClock()/1000))) {GoatTraceFail("history unavailable");return;}
   int count=HistoryDealsTotal();
   if(count<g_trace_history_count) {GoatTraceFail("native history shrank during capture");return;}
   // The fixed tester retains its history. Process newly appended deals once;
   // do not rescan every historical deal on every timer/deal callback.
   for(int i=g_trace_history_count;i<count;++i) GoatTraceDeal(HistoryDealGetTicket(i));
   g_trace_history_count=count;
  }

void GoatTraceMarks(const string reason)
  {
   if(!g_trace_enabled) return;
   long stamp=GoatTraceClock();g_trace_last_time=stamp;
   MqlTick quote;ZeroMemory(quote);bool quoted=SymbolInfoTick(_Symbol,quote);
   int count=ArraySize(g_trace_sequences);
   double lots[],floating[],swap[];ArrayResize(lots,count);ArrayResize(floating,count);ArrayResize(swap,count);
   ArrayInitialize(lots,0.0);ArrayInitialize(floating,0.0);ArrayInitialize(swap,0.0);
   for(int p=0;p<PositionsTotal();++p)
     {
      ulong ticket=PositionGetTicket(p);
      if(ticket==0) {GoatTraceFail("position enumeration failed");continue;}
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol || PositionGetInteger(POSITION_MAGIC)!=MAGIC1)
        {GoatTraceFail("foreign standing position");continue;}
      ulong id=GoatTracePositionSequence((ulong)PositionGetInteger(POSITION_IDENTIFIER));
      int index=GoatTraceSequenceIndex(id);
      if(index<0) {GoatTraceFail("unmatched standing position");continue;}
      if(g_trace_sequences[index].ended || !g_trace_sequences[index].logical_active) GoatTraceFail("standing position without active logical sequence");
      lots[index]+=PositionGetDouble(POSITION_VOLUME);
      floating[index]+=PositionGetDouble(POSITION_PROFIT);swap[index]+=PositionGetDouble(POSITION_SWAP);
     }
   double realized=0.0,total_floating=0.0;
   for(int i=0;i<count;++i)
     {
      double net=g_trace_sequences[i].profit+g_trace_sequences[i].commission+g_trace_sequences[i].fee+g_trace_sequences[i].swap;
      realized+=net;total_floating+=floating[i]+swap[i];
      if(!g_trace_enabled) break; // Resource exhaustion never changes trading, only capture.
      // Sparse output: inactive historical sequences carry their final settlement.
      if(g_trace_sequences[i].virtual_sequence) continue;
      if(!g_trace_sequences[i].logical_active && lots[i]==0.0 && reason=="minute") continue;
      GoatTraceWritten(FileWrite(g_trace_files[4],++g_trace_ordinal,stamp,quoted?quote.time_msc:0,g_trace_sequences[i].id,
         g_trace_sequences[i].direction,g_trace_sequences[i].logical_active,g_trace_sequences[i].ended,lots[i],
         g_trace_sequences[i].profit,g_trace_sequences[i].commission,g_trace_sequences[i].fee,g_trace_sequences[i].swap,
         floating[i],swap[i],net+floating[i]+swap[i],reason));
     }
   double balance=AccountInfoDouble(ACCOUNT_BALANCE),equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if((reason=="tester_finished" || reason=="deinit") &&
      (MathAbs(balance-g_trace_initial_balance-realized)>0.02 || MathAbs(equity-balance-total_floating)>0.02))
      GoatTraceFail("final native account cash/mark reconciliation residual");
   GoatTraceWritten(FileWrite(g_trace_files[5],++g_trace_ordinal,stamp,quoted?quote.time_msc:0,reason,balance,equity,
      AccountInfoDouble(ACCOUNT_MARGIN),PositionsTotal(),OrdersTotal(),realized,total_floating,
      balance-g_trace_initial_balance-realized,equity-balance-total_floating));
  }

void GoatTraceEnd(const ulong id,const string reason)
  {
   if(!g_trace_enabled || id==0) return;
   int n=ArraySize(g_trace_pending_ends);
   ArrayResize(g_trace_pending_ends,n+1);ArrayResize(g_trace_pending_end_times,n+1);ArrayResize(g_trace_pending_end_reasons,n+1);
   g_trace_pending_ends[n]=id;g_trace_pending_end_times[n]=GoatTraceClock();g_trace_pending_end_reasons[n]=reason;g_trace_dirty=true;
  }

void GoatTraceCommitEnd(const ulong id,const string reason,const long stamp)
  {
   int index=GoatTraceSequenceIndex(id);
   if(index<0) {GoatTraceFail("end without sequence identity");return;}
   g_trace_sequences[index].logical_active=false;g_trace_sequences[index].ended=true;
   GoatTraceWritten(FileWrite(g_trace_files[1],++g_trace_ordinal,stamp,id,g_trace_sequences[index].direction,
      g_trace_sequences[index].virtual_sequence,"end",reason,false));

  }

// Called only after the original event handler returns. Never select history or
// positions from inside strategy/order loops, including partial-close helpers.
void GoatTraceBoundary(const bool force=false)
  {
   if(!g_trace_enabled || (!force && !g_trace_dirty)) return;
   GoatTraceDrainDeals();
   for(int i=0;i<ArraySize(g_trace_pending_ends);++i)
      GoatTraceCommitEnd(g_trace_pending_ends[i],g_trace_pending_end_reasons[i],g_trace_pending_end_times[i]);
   ArrayResize(g_trace_pending_ends,0);ArrayResize(g_trace_pending_end_times,0);ArrayResize(g_trace_pending_end_reasons,0);
   GoatTraceMarks("event");g_trace_dirty=false;
  }

void GoatTraceFlush()
  {
   for(int i=0;i<6;++i) if(g_trace_files[i]!=INVALID_HANDLE)
     {ResetLastError();FileFlush(g_trace_files[i]);if(GetLastError()!=0) GoatTraceFail("flush failed");}
  }

void GoatTraceTimer()
  {
   if(!g_trace_enabled) return;
   long now=(long)TimeTradeServer();
   if(now%60!=0 || now==g_trace_last_frame) return;
   g_trace_last_frame=now;
   if(g_trace_dirty) GoatTraceBoundary();
   GoatTraceMarks("minute");GoatTraceFlush();
  }

bool GoatTraceInit()
  {
   if(!Sequence_Export_Enabled || Sequence_Export_Id=="" || Mode!="EXPORT" ||
      !MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return true;
   if(!GoatSeqSafeId(Sequence_Export_Id)) {Print("Invalid sequence export identity");return false;}
   g_trace_path="GOATSequencePending\\"+Sequence_Export_Id+"\\";
   if(FileIsExist(g_trace_path+"run.csv",FILE_COMMON)) {Print("Sequence export namespace already exists; preserved");g_trace_path="";return false;}
   GoatSeqMakePath(StringSubstr(g_trace_path,0,StringLen(g_trace_path)-1));
   if(DashboardExposurePolicyMode!=GOAT_EXPOSURE_ALLOW) GoatTraceFail("capture requires exposure filter disabled");
   if(Sequence_Export_Model!=4 || Sequence_Export_Start<=0 || Sequence_Export_End<=Sequence_Export_Start) GoatTraceFail("invalid fixed-export model/window");
   if(!FileIsExist(g_trace_path+"source-inputs.set",FILE_COMMON)) GoatTraceFail("selected source input snapshot missing");
   // The canonical SET serializer reads actual resolved input values before the first tick.
   FileSET_handle=FileOpen(g_trace_path+"effective-inputs.set",FILE_WRITE|FILE_CSV|FILE_COMMON,'\t');
   if(FileSET_handle==INVALID_HANDLE) GoatTraceFail("effective input snapshot unavailable");
   else WriteSet("; Actual resolved native inputs before trading");
   string names[6]={"run","lifecycle","orders","deals","marks","account"};
   for(int i=0;i<6;++i)
     {
      g_trace_files[i]=FileOpen(g_trace_path+names[i]+".csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
      if(g_trace_files[i]==INVALID_HANDLE) {GoatTraceFail("open failed");return false;}
     }
   g_trace_enabled=true;g_trace_first_time=GoatTraceClock();g_trace_initial_balance=AccountInfoDouble(ACCOUNT_BALANCE);
   GoatTraceWritten(FileWrite(g_trace_files[0],"key","value"));
   GoatTraceWritten(FileWrite(g_trace_files[0],"schema","goat-native-sequence-capture-v1"));
   GoatTraceWritten(FileWrite(g_trace_files[0],"time_basis","broker-server-time; NOT UTC"));
   GoatTraceWritten(FileWrite(g_trace_files[0],"run_id",Sequence_Export_Id));
   GoatTraceWritten(FileWrite(g_trace_files[0],"strategy_id",Sequence_Export_Id));
   // Exact final SET SHA256 is appended after WriteSet completes, never guessed at init.
   GoatTraceWritten(FileWrite(g_trace_files[0],"build_id",GOAT_BUILD_ID));
   GoatTraceWritten(FileWrite(g_trace_files[0],"program_path",MQLInfoString(MQL_PROGRAM_PATH)));
   GoatTraceWritten(FileWrite(g_trace_files[0],"server",AccountInfoString(ACCOUNT_SERVER)));
   GoatTraceWritten(FileWrite(g_trace_files[0],"account",AccountInfoInteger(ACCOUNT_LOGIN)));
   GoatTraceWritten(FileWrite(g_trace_files[0],"currency",AccountInfoString(ACCOUNT_CURRENCY)));
   GoatTraceWritten(FileWrite(g_trace_files[0],"model",Sequence_Export_Model));
   GoatTraceWritten(FileWrite(g_trace_files[0],"leverage",AccountInfoInteger(ACCOUNT_LEVERAGE)));
   string effective_hash="";long effective_size=0;
   if(!GoatSeqHash(g_trace_path+"effective-inputs.set",effective_hash,effective_size)) GoatTraceFail("cannot hash effective inputs");
   GoatTraceWritten(FileWrite(g_trace_files[0],"effective_inputs_sha256",effective_hash));
   GoatTraceWritten(FileWrite(g_trace_files[0],"symbol",_Symbol));
   GoatTraceWritten(FileWrite(g_trace_files[0],"magic",MAGIC1));
   GoatTraceWritten(FileWrite(g_trace_files[0],"exposure_filter",DashboardExposurePolicyMode));
   GoatTraceWritten(FileWrite(g_trace_files[0],"margin_mode",AccountInfoInteger(ACCOUNT_MARGIN_MODE)));
   GoatTraceWritten(FileWrite(g_trace_files[0],"expected_start_server_msc",(long)Sequence_Export_Start*1000));
   GoatTraceWritten(FileWrite(g_trace_files[0],"expected_end_server_msc",(long)Sequence_Export_End*1000));
   GoatTraceWritten(FileWrite(g_trace_files[0],"observed_start_server_msc",g_trace_first_time));
   GoatTraceWritten(FileWrite(g_trace_files[0],"initial_balance",g_trace_initial_balance));
   GoatTraceWritten(FileWrite(g_trace_files[0],"initial_positions",PositionsTotal()));
   GoatTraceWritten(FileWrite(g_trace_files[0],"initial_orders",OrdersTotal()));
   if(PositionsTotal()!=0 || OrdersTotal()!=0) GoatTraceFail("capture did not initialize flat");
   GoatTraceWritten(FileWrite(g_trace_files[1],"ordinal","server_time_msc","sequence_id","direction","virtual","kind","reason","logical_active"));
   GoatTraceWritten(FileWrite(g_trace_files[2],"ordinal","server_time_msc","sequence_id","direction","order_id","deal_id","retcode","sent","requested_lots","result_lots","result_price"));
   GoatTraceWritten(FileWrite(g_trace_files[3],"ordinal","server_time_msc","sequence_id","deal_id","order_id","position_id","sequence_direction","deal_type","deal_entry","lots","price","profit","commission","fee","swap","deal_magic","join_basis"));
   GoatTraceWritten(FileWrite(g_trace_files[4],"ordinal","server_time_msc","quote_server_time_msc","sequence_id","direction","logical_active","ended","lots","realized_profit","commission","fee","realized_swap","floating_profit","floating_swap","equity_pnl","reason"));
   GoatTraceWritten(FileWrite(g_trace_files[5],"ordinal","server_time_msc","quote_server_time_msc","reason","balance","equity","margin","positions","orders","ledger_realized","ledger_floating","balance_residual","equity_residual"));
   GoatTraceMarks("initial");GoatTraceFlush();
   return !g_trace_failed;
  }

void GoatTraceTesterFinished()
  {
   if(!g_trace_enabled) return;
   GoatTraceBoundary(true);GoatTraceMarks("tester_finished");GoatTraceFlush();g_trace_tester_finished=true;
  }

// A second complete native-history traversal supplies an independent ledger
// for the importer to compare against sequence-owned deals, including fees.
bool GoatTraceNativeLedger()
  {
   if(!HistorySelect(0,(datetime)(GoatTraceClock()/1000))) return false;
   string ledger_path=g_trace_path+"native-ledger.csv";
   int file=FileOpen(ledger_path,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   bool ok=FileWrite(file,"deal_id","order_id","server_time_msc","symbol","deal_type","deal_entry","lots","price","profit","commission","fee","swap","balance")>0;
   string trading="",cash="";double balance=0.0;int deposits=0;
   for(int i=0;i<HistoryDealsTotal();++i)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0) {ok=false;continue;}
      ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER);
      long stamp=HistoryDealGetInteger(deal,DEAL_TIME_MSC);
      int type=(int)HistoryDealGetInteger(deal,DEAL_TYPE),entry=(int)HistoryDealGetInteger(deal,DEAL_ENTRY);
      double lots=HistoryDealGetDouble(deal,DEAL_VOLUME),price=HistoryDealGetDouble(deal,DEAL_PRICE);
      double profit=HistoryDealGetDouble(deal,DEAL_PROFIT),commission=HistoryDealGetDouble(deal,DEAL_COMMISSION);
      double fee=HistoryDealGetDouble(deal,DEAL_FEE),swap=HistoryDealGetDouble(deal,DEAL_SWAP);
      balance+=profit+commission+fee+swap;
      if(FileWrite(file,deal,order,stamp,HistoryDealGetString(deal,DEAL_SYMBOL),type,entry,lots,price,profit,commission,fee,swap,balance)==0) ok=false;
      if(type==DEAL_TYPE_BALANCE)
        {
         deposits++;
         if(deposits!=1 || MathAbs(profit-g_trace_initial_balance)>0.005 || commission!=0 || fee!=0 || swap!=0)
            GoatTraceFail("unsupported extra native cash flow");
         if(cash!="") cash+=",";
         cash+="{\"dealId\":"+GoatSeqJson((string)deal)+",\"serverTimeMsc\":"+(string)stamp+
               ",\"amount\":"+DoubleToString(profit,12)+",\"balance\":"+DoubleToString(balance,12)+"}";
         continue;
        }
      if((type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) || (entry!=DEAL_ENTRY_IN && entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY))
         {GoatTraceFail("unsupported native cash/deal type");continue;}
      if(trading!="") trading+=",";
      trading+="{\"dealId\":"+GoatSeqJson((string)deal)+",\"orderId\":"+GoatSeqJson((string)order)+
         ",\"serverTimeMsc\":"+(string)stamp+",\"type\":"+GoatSeqJson(type==DEAL_TYPE_BUY?"buy":"sell")+
         ",\"entry\":"+GoatSeqJson(entry==DEAL_ENTRY_IN?"in":(entry==DEAL_ENTRY_OUT?"out":"out-by"))+
         ",\"lots\":"+DoubleToString(lots,12)+",\"price\":"+DoubleToString(price,12)+
         ",\"profit\":"+DoubleToString(profit,12)+",\"commission\":"+DoubleToString(commission,12)+
         ",\"swap\":"+DoubleToString(swap,12)+",\"fee\":"+DoubleToString(fee,12)+"}";
     }
   ResetLastError();FileFlush(file);if(GetLastError()!=0) ok=false;FileClose(file);
   if(deposits!=1 || MathAbs(balance-AccountInfoDouble(ACCOUNT_BALANCE))>0.02) GoatTraceFail("native full ledger balance mismatch");
   string ledger_binding=GoatSeqBinding(ledger_path,"native-ledger.csv");
   if(!ok || ledger_binding=="") return false;
   string receipt="{\"schemaVersion\":\"goat-native-report-reconciliation-v1\",\"report\":"+ledger_binding+
      ",\"evidenceKind\":\"native-deal-ledger\",\"runId\":"+GoatSeqJson(Sequence_Export_Id)+
      ",\"strategyId\":"+GoatSeqJson(Sequence_Export_Id)+",\"asset\":"+GoatSeqJson(_Symbol)+
      ",\"currency\":"+GoatSeqJson(AccountInfoString(ACCOUNT_CURRENCY))+
      ",\"initialBalance\":"+DoubleToString(g_trace_initial_balance,12)+
      ",\"finalBalance\":"+DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),12)+
      ",\"finalEquity\":"+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),12)+
      ",\"timePrecision\":\"milliseconds\",\"tradingDeals\":["+trading+"],\"cashDeals\":["+cash+"]}";
   return GoatSeqAtomicText(g_trace_path+"report-reconciliation.json",receipt);
  }

bool GoatTraceCompletion(const int reason)
  {
   string path=g_trace_path+"completion.csv";
   int file=FileOpen(path+".tmp",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   int real_sequences=0,active_sequences=0;
   for(int i=0;i<ArraySize(g_trace_sequences);++i)
     {
      if(g_trace_sequences[i].has_real_entry) real_sequences++;
      if(g_trace_sequences[i].has_real_entry && g_trace_sequences[i].logical_active) active_sequences++;
     }
   bool ok=true;
   #define GOAT_SEQ_FOOTER(k,v) if(FileWrite(file,k,v)==0) ok=false;
   GOAT_SEQ_FOOTER("key","value")
   GOAT_SEQ_FOOTER("tester_finished",g_trace_tester_finished)
   GOAT_SEQ_FOOTER("deinit_reason",reason)
   GOAT_SEQ_FOOTER("observed_end_server_msc",g_trace_last_time)
   GOAT_SEQ_FOOTER("sequence_allocations",ArraySize(g_trace_sequences))
   GOAT_SEQ_FOOTER("joined_deals",ArraySize(g_trace_deals))
   GOAT_SEQ_FOOTER("real_sequences",real_sequences)
   GOAT_SEQ_FOOTER("entry_deals",g_trace_entry_deals)
   GOAT_SEQ_FOOTER("final_active_real_sequences",active_sequences)
   GOAT_SEQ_FOOTER("final_positions",PositionsTotal())
   GOAT_SEQ_FOOTER("final_orders",OrdersTotal())
   GOAT_SEQ_FOOTER("rows",g_trace_rows)
   GOAT_SEQ_FOOTER("native_final_balance",AccountInfoDouble(ACCOUNT_BALANCE))
   GOAT_SEQ_FOOTER("native_final_equity",AccountInfoDouble(ACCOUNT_EQUITY))
   GOAT_SEQ_FOOTER("error",g_trace_error)
   GOAT_SEQ_FOOTER("capture_status",(!g_trace_failed && g_trace_tester_finished && ok)?"complete-awaiting-external-reconciliation":"incomplete")
   GOAT_SEQ_FOOTER("footer","END")
   #undef GOAT_SEQ_FOOTER
   ResetLastError();FileFlush(file);if(GetLastError()!=0) ok=false;FileClose(file);
   return ok && FileMove(path+".tmp",FILE_COMMON,path,FILE_COMMON);
  }

void GoatTracePublish()
  {
   if(g_sequence_export_csv=="" || g_sequence_export_set=="")
      {Print("Sequence evidence retained as incomplete: no final CSV/SET; ",g_trace_path);return;}
   string package=GoatSeqStem(g_sequence_export_csv)+".goatseq\\";
   GoatSeqMakePath(StringSubstr(package,0,StringLen(package)-1));
   if(FileIsExist(package+"manifest.json",FILE_COMMON)) {Print("Sequence package collision preserved");return;}
   string names[11]={"run.csv","lifecycle.csv","orders.csv","deals.csv","marks.csv","account.csv","completion.csv","native-ledger.csv","source-inputs.set","effective-inputs.set","report-reconciliation.json"};
   for(int i=0;i<11;++i)
      if(!GoatSeqCopyBytes(g_trace_path+names[i],package+names[i])) GoatTraceFail("package payload copy failed: "+names[i]);
   if(!GoatSeqCopyBytes(g_sequence_export_set,package+"effective.set")) GoatTraceFail("final SET snapshot copy failed");
   string raw="";
   for(int i=0;i<8;++i)
     {
      string binding=GoatSeqBinding(package+names[i],names[i]);
      if(binding=="") {GoatTraceFail("package raw binding unavailable");continue;}
      if(raw!="") raw+=",";raw+=binding;
     }
   string csv=GoatSeqBinding(g_sequence_export_csv,"../"+GoatSeqFileName(g_sequence_export_csv));
   string set=GoatSeqBinding(g_sequence_export_set,"../"+GoatSeqFileName(g_sequence_export_set));
   string source=GoatSeqBinding(package+"source-inputs.set","source-inputs.set");
   string effective=GoatSeqBinding(package+"effective.set","effective.set");
   string actual=GoatSeqBinding(package+"effective-inputs.set","effective-inputs.set");
   string receipt=GoatSeqBinding(package+"report-reconciliation.json","report-reconciliation.json");
   if(csv=="" || set=="" || source=="" || effective=="" || actual=="" || receipt=="") GoatTraceFail("package binding unavailable");
   if(!g_trace_tester_finished) GoatTraceFail("tester did not finish");
   string body="{\"schemaVersion\":\"goat-sequence-export-v1\",\"status\":"+
      GoatSeqJson(g_trace_failed?"incomplete":"complete-awaiting-import-verification")+",\"reason\":"+GoatSeqJson(g_trace_error)+
      ",\"runId\":"+GoatSeqJson(Sequence_Export_Id)+",\"nativeStrategyId\":"+GoatSeqJson(Sequence_Export_Id)+
      ",\"asset\":"+GoatSeqJson(_Symbol)+",\"eaVersion\":\"V1.48\",\"buildId\":"+GoatSeqJson(GOAT_BUILD_ID)+
      ",\"model\":"+(string)Sequence_Export_Model+",\"currency\":"+GoatSeqJson(AccountInfoString(ACCOUNT_CURRENCY))+
      ",\"initialEquity\":"+DoubleToString(g_trace_initial_balance,12)+",\"leverage\":"+(string)AccountInfoInteger(ACCOUNT_LEVERAGE)+
      ",\"timeBasis\":{\"kind\":\"broker-server\",\"server\":"+GoatSeqJson(AccountInfoString(ACCOUNT_SERVER))+
      ",\"encoding\":\"wall-clock-as-unix-ms\"},\"requestedPeriod\":{\"startServerMsc\":"+(string)((long)Sequence_Export_Start*1000)+
      ",\"endServerMsc\":"+(string)((long)Sequence_Export_End*1000)+"},\"observedPeriod\":{\"startServerMsc\":"+(string)g_trace_first_time+
      ",\"endServerMsc\":"+(string)g_trace_last_time+"},\"sampling\":{\"intervalMilliseconds\":60000,\"drawdown\":\"sampled\",\"policy\":\"minute-and-event\"},"+
      "\"exports\":{\"csv\":"+(csv==""?"null":csv)+",\"set\":"+(set==""?"null":set)+"},\"sourceInputs\":"+(source==""?"null":source)+
      ",\"effectiveSet\":"+(effective==""?"null":effective)+",\"effectiveInputs\":"+(actual==""?"null":actual)+
      ",\"rawFiles\":["+raw+"],\"reportReceipt\":"+(receipt==""?"null":receipt)+"}";
   if(!GoatSeqAtomicText(package+"manifest.json",body)) {Print("Sequence package manifest commit failed; evidence preserved");return;}
   // Only successful packages retire their private pending copy. Incomplete attempts remain diagnosable.
   if(!g_trace_failed)
     {
      for(int i=0;i<11;++i) FileDelete(g_trace_path+names[i],FILE_COMMON);
      FolderDelete(StringSubstr(g_trace_path,0,StringLen(g_trace_path)-1),FILE_COMMON);
     }
   Print("GOAT SEQUENCE PACKAGE ",package," status=",g_trace_failed?"incomplete":"awaiting import verification");
  }

void GoatTraceClose(const int reason)
  {
   if(g_trace_path=="") return;
   if(g_trace_enabled) {GoatTraceBoundary(true);GoatTraceMarks("deinit");}
   if(!GoatTraceNativeLedger()) GoatTraceFail("native history receipt unavailable");
   string set_hash="";long set_size=0;
   if(g_sequence_export_set=="" || !GoatSeqHash(g_sequence_export_set,set_hash,set_size)) GoatTraceFail("final exported SET unavailable");
   if(g_trace_files[0]!=INVALID_HANDLE) GoatTraceWritten(FileWrite(g_trace_files[0],"source_set_sha256_claim",set_hash));
   GoatTraceFlush();
   for(int i=0;i<6;++i) if(g_trace_files[i]!=INVALID_HANDLE) {FileClose(g_trace_files[i]);g_trace_files[i]=INVALID_HANDLE;}
   if(!GoatTraceCompletion(reason)) GoatTraceFail("completion commit failed");
   g_trace_enabled=false;
   GoatTracePublish();
  }
#endif

