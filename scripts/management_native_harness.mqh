// Appended only by prepare_management_native_test.py. Never ship this binary.
int g_nativeCase=0,g_nativeFailures=0;
bool g_nativeStarted=false,g_nativeDone=false;
void NativeAssert(bool ok,string message)
{Print("NATIVE_ASSERT ",ok ? "PASS " : "FAIL ",message);if(!ok) g_nativeFailures++;}

int OnInit()
{
 if(!MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION))
 {Print("TESTER-ONLY: refuses charts/live/demo attachment");return INIT_FAILED;}
 return INIT_SUCCEEDED;
}
void OnTimer() {}
double OnTester() {return g_nativeDone && g_nativeCase==6 && g_nativeFailures==0 ? 1.0 : -1.0;}
void OnDeinit(const int reason) {if(g_nativeStarted) GOATNative_OnDeinit(reason);}
void OnTick()
{
 if(g_nativeDone) return;
 MqlDateTime fixture_clock;TimeToStruct(TimeCurrent(),fixture_clock);
 if(fixture_clock.hour<2) return; // Exercise management inside the configured session.
 if(!g_nativeStarted)
 {
  g_nativeStarted=true;
  NativeAssert(Mode_Bias==Bias_Disabled && Risk==10 && Sequence_MLPS_Hard_Close,"fixture inputs");
  NativeAssert(GOATNative_OnInit()==INIT_SUCCEEDED,"production initialization succeeds without authorization");
  if(g_nativeFailures>0) {g_nativeDone=true;TesterStop();return;}
 }
 string labels[]={"server_down","rejected","pending","entitlement_expired","revoked","healthy"};
 int responses[]={-1,401,202,200,403,200};
 if(g_nativeCase>=6)
 {
  Print("NATIVE_MANAGEMENT_RESULT cases=6 failures=",g_nativeFailures," simulated_reinit=true cold_terminal_restart=false");
  g_nativeDone=true;TesterStop();return;
 }
 int direction=g_nativeCase%2;
 CTrade fixture;fixture.SetExpertMagicNumber(MAGIC1);fixture.SetTypeFillingBySymbol(_Symbol);
 // Tester-only spread loss crosses the EA's real minimum MLPS of $10.
 double spread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
 double loss_per_lot=spread/SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE)*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
 if(loss_per_lot<=0) return;
 double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 double volume=MathCeil(20.0/loss_per_lot/step)*step;
 NativeAssert(volume<=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),"fixture volume within symbol bounds");
 bool opened=direction==OP_BUY ? fixture.Buy(volume,_Symbol,0,0,0,"management tester fixture") : fixture.Sell(volume,_Symbol,0,0,0,"management tester fixture");
 NativeAssert(opened && FindNumberOfPositions(direction,MAGIC1)==1,labels[g_nativeCase]+": native fixture open");
 if(!opened) {g_nativeDone=true;TesterStop();return;}
 GOATRecoverBrokerSequence(Seq_Buy,OP_BUY);GOATRecoverBrokerSequence(Seq_Sell,OP_SELL);
 // Existing basket recovered by production code; persist a complete one-level test state.
 ArrayResize(Seq_Buy.LotsNorm,1);Seq_Buy.LotsNorm[0]=volume;
 ArrayResize(Seq_Sell.LotsNorm,1);Seq_Sell.LotsNorm[0]=volume;
 g_GOATRecoveryDegraded=false;GOATSaveManagement();
 NativeAssert(!g_GOATRecoveryWriteFailed,"native checkpoint write");
 g_GOATManagerReady=false;g_GOATAuthUntil=0;
 NativeAssert(GOATNative_OnInit()==INIT_SUCCEEDED,labels[g_nativeCase]+": production reinit with existing position");
 g_fixtureStatus=responses[g_nativeCase];g_fixtureReply=g_nativeCase==5 ? (string)g_GOATManagerAccount+" - yes" : "no";
 g_GOATAuthNext=0;GOATManagementAuthPoll();GOATManagementStatus();
 if(g_nativeCase<5)
 {
  NativeAssert(!GOATCanAddRisk(),labels[g_nativeCase]+": entry permission denied");
  int before=PositionsTotal();
  NativeAssert(OpenPosition(direction,MAGIC1,volume,0,0,0,"must be blocked",false)==0,"final send gate blocks added risk");
  NativeAssert(PositionsTotal()==before,"no risk added");
 }
 // The configured spread-loss trigger normally exits inside production reinit.
 GOATNative_OnTick();
 NativeAssert(FindNumberOfPositions(direction,MAGIC1)==0,labels[g_nativeCase]+": native management exit filled");
 g_fixtureStatus=200;g_fixtureReply=(string)g_GOATManagerAccount+" - yes";g_GOATAuthNext=0;GOATManagementAuthPoll();
 NativeAssert(GOATCanAddRisk(),labels[g_nativeCase]+": auth recovers without another init");
 g_GOATAuthUntil=0;g_nativeCase++;
}
