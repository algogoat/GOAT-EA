// Terminal-local guard; account/server/symbol/direction keys. Not a cross-terminal lock.
#ifndef GOAT_DIRECTION_GUARD_MQH
#define GOAT_DIRECTION_GUARD_MQH
double g_direction_guard_token=0.0;
bool g_direction_guard_send_attempted=false,g_direction_guard_denied=false;
string g_direction_guard_keys[2];
bool g_direction_guard_held[2]={false,false};
string g_direction_guard_reason[2];
ulong g_direction_guard_pending_order[2]={0,0};
string g_direction_guard_identity="";
bool g_direction_guard_tracking[2]={false,false};
bool g_direction_guard_manual_reconcile[2]={false,false};

string GoatGuardPendingPath(const int direction)
  {
   return "GOATGuard\\"+g_direction_guard_keys[direction]+".T"+DoubleToString(g_direction_guard_token,0)+".pending";
  }

bool GoatGuardDurablePending(const int direction)
  {
   string found="";
   long handle=FileFindFirst("GOATGuard\\"+g_direction_guard_keys[direction]+".*.pending",found);
   if(handle==INVALID_HANDLE) return false;
   FileFindClose(handle);
   return true;
  }

bool GoatGuardWritePending(const int direction)
  {
   if(GoatGuardDurablePending(direction)) return false;
   FolderCreate("GOATGuard");
   int file=FileOpen(GoatGuardPendingPath(direction),FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   ResetLastError();
   uint written=FileWrite(file,g_direction_guard_identity);
   FileWrite(file,"account="+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));
   FileWrite(file,"server="+AccountInfoString(ACCOUNT_SERVER));
   FileWrite(file,"symbol="+_Symbol);
   FileWrite(file,"direction="+IntegerToString(direction));
   FileFlush(file);
   int error=GetLastError();
   FileClose(file);
   // An incomplete marker remains on disk and blocks recovery rather than
   // forgetting a potentially issued order. No OrderSend follows a false result.
   return written>0 && error==0;
  }

bool GoatGuardResolvePending(const int direction)
  {
   int file=FileOpen(GoatGuardPendingPath(direction),FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   string identity=FileReadString(file);
   FileClose(file);
   if(identity!=g_direction_guard_identity) return false;
   return FileDelete(GoatGuardPendingPath(direction));
  }

uint GoatGuardHash(const string value)
  {
   uint hash=2166136261;
   for(int i=0;i<StringLen(value);++i) {hash^=(uint)StringGetCharacter(value,i);hash*=16777619;}
   return hash;
  }

string GoatGuardOwnerKey(const double token,const string field)
  {
   return "GOAT.DG2.O."+DoubleToString(token,0)+"."+field;
  }

bool GuardStoreEnsure(const string key)
  {
   // Unlike Check+Set(0), Temp does not overwrite an already-created variable.
   return GlobalVariableTemp(key);
  }

double GuardStoreRead(const string key)
  {
   double value=-1.0;
   if(!GlobalVariableGet(key,value)) return -1.0;
   return value;
  }

bool GuardStoreCAS(const string key,const double value,const double expected)
  {
   return GlobalVariableSetOnCondition(key,value,expected);
  }

bool GuardOwnerPending(const double token,const int direction)
  {
   // Missing owner metadata is ambiguous and therefore blocks reclamation.
   double value=1.0;
   if(!GlobalVariableGet(GoatGuardOwnerKey(token,direction==OP_BUY ? "PB" : "PS"),value)) return true;
   return value!=0.0;
  }

bool GuardOwnerAlive(const double token)
  {
   double high=0.0,low=0.0;
   if(!GlobalVariableGet(GoatGuardOwnerKey(token,"H"),high) || !GlobalVariableGet(GoatGuardOwnerKey(token,"L"),low)) return true;
   long chart_id=((long)high<<32)|(long)(uint)low;
   double current=0.0;
   if(!GlobalVariableGet("GOAT.DG2.C."+IntegerToString(chart_id),current)) return false;
   if(current!=token) return false;
   for(long chart=ChartFirst();chart>=0;chart=ChartNext(chart))
      if(chart==chart_id) return ChartGetString(chart,CHART_EXPERT_NAME)!="";
   return false;
  }

bool GuardActualExposure(const int direction)
  {
   // Deliberately include manual/unregistered exposure after restart or removal.
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      if(PositionGetTicket(i)==0 || PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((int)PositionGetInteger(POSITION_TYPE)==direction) return true;
     }
   for(int i=OrdersTotal()-1;i>=0;--i)
     {
      if(OrderGetTicket(i)==0 || OrderGetString(ORDER_SYMBOL)!=_Symbol) continue;
      int type=(int)OrderGetInteger(ORDER_TYPE);
      if(direction==OP_BUY && (type==ORDER_TYPE_BUY || type==ORDER_TYPE_BUY_LIMIT || type==ORDER_TYPE_BUY_STOP || type==ORDER_TYPE_BUY_STOP_LIMIT)) return true;
      if(direction==OP_SELL && (type==ORDER_TYPE_SELL || type==ORDER_TYPE_SELL_LIMIT || type==ORDER_TYPE_SELL_STOP || type==ORDER_TYPE_SELL_STOP_LIMIT)) return true;
     }
   return false;
  }

#include "GOAT_DirectionGuardCore.mqh"

bool GoatDirectionGuardInit()
  {
   if(g_direction_guard_token>0.0) return true;
   string counter="GOAT.DG2.Tokens";
   if(!GuardStoreEnsure(counter)) return false;
   for(int attempt=0;attempt<32;++attempt)
     {
      double prior=GuardStoreRead(counter);
      if(prior<0.0 || prior>=9007199254740990.0) return false;
      if(!GuardStoreCAS(counter,prior+1.0,prior)) continue;
      double token=prior+1.0;
      long chart_id=ChartID();
      if(!GlobalVariableTemp(GoatGuardOwnerKey(token,"H")) || !GlobalVariableTemp(GoatGuardOwnerKey(token,"L")) ||
         !GlobalVariableTemp(GoatGuardOwnerKey(token,"PB")) || !GlobalVariableTemp(GoatGuardOwnerKey(token,"PS")) ||
         !GlobalVariableTemp("GOAT.DG2.C."+IntegerToString(chart_id))) return false;
      if(!GlobalVariableSet(GoatGuardOwnerKey(token,"H"),(double)(chart_id>>32)) ||
         !GlobalVariableSet(GoatGuardOwnerKey(token,"L"),(double)(uint)chart_id) ||
         !GlobalVariableSet("GOAT.DG2.C."+IntegerToString(chart_id),token)) return false;
      string scope="GOAT.DG2."+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))+"."+
                   StringFormat("%08X",GoatGuardHash(AccountInfoString(ACCOUNT_SERVER)))+"."+
                   StringFormat("%08X",GoatGuardHash(_Symbol));
      g_direction_guard_keys[OP_BUY]=scope+".B";
      g_direction_guard_keys[OP_SELL]=scope+".S";
      g_direction_guard_token=token;
      g_direction_guard_identity=TerminalInfoString(TERMINAL_DATA_PATH)+"|"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))+"|"+
                                AccountInfoString(ACCOUNT_SERVER)+"|"+_Symbol+"|"+IntegerToString(chart_id)+"|"+
                                TimeToString(TimeLocal(),TIME_DATE|TIME_SECONDS)+"|"+IntegerToString((long)GetMicrosecondCount())+"|"+DoubleToString(token,0);
      return true;
     }
   return false;
  }

void GoatDirectionGuardStatus(const int direction,const string reason)
  {
   if(g_direction_guard_reason[direction]==reason) return;
   g_direction_guard_reason[direction]=reason;
   string status="Asset "+(direction==OP_BUY ? "Buy: " : "Sell: ")+reason;
   Print(status);
   if(!MQLInfoInteger(MQL_TESTER)) DashboardBusSendStatus(status);
  }

bool GoatDirectionGuardBegin(const int direction,const bool already_traded)
  {
   int policy=DashboardExposurePolicyMode;
   string policy_key=GoatPortfolioGVName("DashboardExposurePolicyMode");
   if(!MQLInfoInteger(MQL_TESTER) && GlobalVariableCheck(policy_key)) policy=(int)GlobalVariableGet(policy_key);
   if(policy!=GOAT_EXPOSURE_SYMBOL_DIRECTION) return true;
   if(!GoatDirectionGuardInit()) {GoatDirectionGuardStatus(direction,"lock unavailable");return false;}
   if(GoatGuardDurablePending(direction))
     {GoatDirectionGuardStatus(direction,"Check: unresolved request; reconcile before new entry");return false;}
   if(!already_traded && AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {GoatDirectionGuardStatus(direction,"hedging account required");return false;}
   if(!MQLInfoInteger(MQL_TESTER) && !TerminalInfoInteger(TERMINAL_CONNECTED))
     {GoatDirectionGuardStatus(direction,"disconnected");return false;}
   if(!already_traded && g_direction_guard_held[direction] && GuardActualExposure(direction))
     {GoatDirectionGuardStatus(direction,"prior fill awaiting sequence reconciliation");return false;}
   // Existing sequences retain management when enabled mid-sequence, but their
   // new requests still receive durable uncertainty markers.
   if(!already_traded || g_direction_guard_held[direction])
     {
      if(!GoatGuardClaim(g_direction_guard_keys[direction],g_direction_guard_token,direction))
        {GoatDirectionGuardStatus(direction,"blocked by owner/exposure");return false;}
      g_direction_guard_held[direction]=true;
     }
   g_direction_guard_pending_order[direction]=0;
   g_direction_guard_manual_reconcile[direction]=false;
   if(!GlobalVariableSet(GoatGuardOwnerKey(g_direction_guard_token,direction==OP_BUY ? "PB" : "PS"),1.0)) return false;
   g_direction_guard_tracking[direction]=true;
   if(!GoatGuardWritePending(direction))
     {
      if(!FileIsExist(GoatGuardPendingPath(direction)))
        {
         GlobalVariableSet(GoatGuardOwnerKey(g_direction_guard_token,direction==OP_BUY ? "PB" : "PS"),0.0);
         g_direction_guard_tracking[direction]=false;
         GoatDirectionGuardEnd(direction);
        }
      GoatDirectionGuardStatus(direction,"Check: durable reservation unavailable; no order sent");return false;
     }
   GoatDirectionGuardStatus(direction,g_direction_guard_held[direction] ? "sequence owns lock" : "existing sequence managed");
   return true;
  }

void GoatDirectionGuardEnd(const int direction)
  {
   if(!g_direction_guard_held[direction]) return;
   if(GoatGuardRelease(g_direction_guard_keys[direction],g_direction_guard_token,direction))
     {
      g_direction_guard_held[direction]=false;
      GoatDirectionGuardStatus(direction,"ready (no cooldown)");
     }
  }

void GoatDirectionGuardResult(const int direction,const uint retcode,const bool opened,const bool previously_traded)
  {
   if(!g_direction_guard_tracking[direction]) return;
   bool settled=(retcode==TRADE_RETCODE_DONE || retcode==TRADE_RETCODE_DONE_PARTIAL);
   bool rejected=(retcode==10004 || retcode==10006 || (retcode>=10013 && retcode<=10022) ||
                  retcode==10024 || retcode==10026 || retcode==10027 || retcode==10030 ||
                  (retcode>=10032 && retcode<=10035) || retcode==10040 || (retcode>=10042 && retcode<=10044) || retcode==10046);
   if((settled || rejected) && GoatGuardResolvePending(direction))
     {
      GlobalVariableSet(GoatGuardOwnerKey(g_direction_guard_token,direction==OP_BUY ? "PB" : "PS"),0.0);
      g_direction_guard_tracking[direction]=false;
     }
   if(!opened && !rejected) g_direction_guard_manual_reconcile[direction]=true;
   // PLACED, timeout, connection loss and unknown responses retain reservation.
   if(!opened && rejected && !previously_traded) GoatDirectionGuardEnd(direction);
  }

void GoatDirectionGuardDeal(const ulong deal,const bool buy_started,const bool sell_started)
  {
   if(g_direction_guard_token<=0.0 || !HistoryDealSelect(deal)) return;
   if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=MAGIC1 || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) return;
   if(HistoryDealGetInteger(deal,DEAL_ENTRY)!=DEAL_ENTRY_IN) return;
   int direction=(int)HistoryDealGetInteger(deal,DEAL_TYPE);
   if(direction!=OP_BUY && direction!=OP_SELL) return;
   if(g_direction_guard_pending_order[direction]==0 || (ulong)HistoryDealGetInteger(deal,DEAL_ORDER)!=g_direction_guard_pending_order[direction]) return;
   if(g_direction_guard_manual_reconcile[direction] || !(direction==OP_BUY ? buy_started : sell_started))
     {GoatDirectionGuardStatus(direction,"Check: late fill requires manual sequence reconciliation");return;}
   if(g_direction_guard_tracking[direction] && GoatGuardResolvePending(direction))
     {
      GlobalVariableSet(GoatGuardOwnerKey(g_direction_guard_token,direction==OP_BUY ? "PB" : "PS"),0.0);
      g_direction_guard_tracking[direction]=false;
     }
  }

void GoatDirectionGuardCaptureOrder(const int direction,const ulong order)
  {
   if(g_direction_guard_tracking[direction]) g_direction_guard_pending_order[direction]=order;
  }

void GoatDirectionGuardPublish(const bool buy_traded,const bool sell_traded)
  {
   if(MQLInfoInteger(MQL_TESTER)) return;
   GlobalVariableSet(GoatChildGVName(MAGIC1,_Symbol,"DG_AT"),(double)TimeCurrent());
   if(DashboardExposurePolicyMode!=GOAT_EXPOSURE_SYMBOL_DIRECTION) return;
   if(!GoatDirectionGuardInit()) return;
   for(int direction=OP_BUY;direction<=OP_SELL;++direction)
     {
      int state=0; // ready, owner, blocked, uncertain request, existing sequence
      if(GoatGuardDurablePending(direction)) state=3;
      else if(g_direction_guard_held[direction]) state=GuardOwnerPending(g_direction_guard_token,direction) ? 3 : 1;
      else if(direction==OP_BUY ? buy_traded : sell_traded) state=4;
      else if(GuardActualExposure(direction)) state=2;
      else if(g_direction_guard_token>0.0)
        {
         double owner=GuardStoreRead(g_direction_guard_keys[direction]);
         if(owner>0.0 && (GuardOwnerAlive(owner) || GuardOwnerPending(owner,direction))) state=2;
        }
      GlobalVariableSet(GoatChildGVName(MAGIC1,_Symbol,direction==OP_BUY ? "DGB" : "DGS"),(double)state);
     }
   GlobalVariableSet(GoatChildGVName(MAGIC1,_Symbol,"DGT"),g_direction_guard_token);
  }

void GoatDirectionGuardMaintenance(const bool buy_active,const bool sell_active)
  {
   if(!buy_active || DashboardExposurePolicyMode!=GOAT_EXPOSURE_SYMBOL_DIRECTION) GoatDirectionGuardEnd(OP_BUY);
   if(!sell_active || DashboardExposurePolicyMode!=GOAT_EXPOSURE_SYMBOL_DIRECTION) GoatDirectionGuardEnd(OP_SELL);
  }

void GoatDirectionGuardDeinit()
  {
   GoatDirectionGuardEnd(OP_BUY);
   GoatDirectionGuardEnd(OP_SELL);
   // Do not erase owner/pending metadata: an unfinished request must fail closed.
   if(g_direction_guard_token>0.0)
      GlobalVariableSetOnCondition("GOAT.DG2.C."+IntegerToString(ChartID()),0.0,g_direction_guard_token);
  }
#endif
