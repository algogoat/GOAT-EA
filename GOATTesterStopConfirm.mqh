#ifndef GOAT_TESTER_STOP_CONFIRM_MQH
#define GOAT_TESTER_STOP_CONFIRM_MQH
// Controller cancellation answers CANCELLED_RECONCILE only after this bounded
// check has seen the Strategy Tester idle (FU35). MT5 shuts the tester down
// after the Stop click returns, so the single 100 ms read of ClickStop(1) raced
// it and answered CANCEL_SIGNAL_SENT_RECONCILE for batches that did stop.
// - Every poll reads the passive tester caption (GoatStudioTesterState); only
//   "idle" counts. "unknown" (blank or transient caption) never confirms a stop.
// - Start and Stop share one MT5 toggle, so Stop is sent only right after a
//   "running" read, once per run observed: a run that starts after an idle read
//   (an export loop that raced the cancel latch) is stopped again, at most
//   GOAT_STOP_CONFIRM_CLICKS times in total.
// - Idle is confirmed after GOAT_STOP_CONFIRM_STABLE consecutive idle reads.
//   The wait is bounded: GOAT_STOP_CONFIRM_POLLS x GOAT_STOP_CONFIRM_POLL_MS
//   (10 s), inside the controller's 20 s monitor freshness window.
#define GOAT_STOP_CONFIRM_POLLS   40
#define GOAT_STOP_CONFIRM_POLL_MS 250
#define GOAT_STOP_CONFIRM_STABLE  3
#define GOAT_STOP_CONFIRM_CLICKS  3

int   g_GoatStopConfirmPolls=0;
int   g_GoatStopConfirmClicks=0;
ulong g_GoatStopConfirmElapsedMs=0;

// B38 click guard. MTTESTER::ClickStop() re-reads the tester through IsIdle(),
// whose blank-caption fallback (clipboard nudge, status-text guess) can still send
// the 0x31 toggle, which is also Start, or skip it. Here the toggle is sent
// directly, and only when a fresh passive read of the caption still says
// "running"; a blank, unknown or idle caption never sends anything.
bool GoatTesterSendStopIfRunning(void)
  {
   if(GoatStudioTesterState()!="running") return false;
   long handle=MTTESTER::GetTerminalHandle();
   if(handle!=0 && TerminalInfoInteger(TERMINAL_BUILD)<=5000) handle=user32::GetDlgItem(handle,0xE81E);
   if(handle!=0) handle=user32::GetDlgItem(handle,0x804E);
   if(handle==0) return false;
   uint message=user32::RegisterWindowMessageW("MetaTrader5_Internal_Message");
   if(message==0) return false;
   user32::SendMessageW(handle,message,0x31,0);
   return true;
  }

bool GoatTesterStopConfirmed(void)
  {
   ulong started=GetTickCount64();
   int stable=0;
   bool armed=true;
   g_GoatStopConfirmPolls=0;
   g_GoatStopConfirmClicks=0;
   for(int poll=0;poll<GOAT_STOP_CONFIRM_POLLS;poll++)
     {
      g_GoatStopConfirmPolls=poll+1;
      string state=GoatStudioTesterState();
      if(state=="idle")
        {
         stable++;
         armed=true;
        }
      else
        {
         // Disarmed only once a Stop was actually sent: a caption that went blank
         // between the two reads leaves the next "running" read free to send it.
         stable=0;
         if(state=="running" && armed && g_GoatStopConfirmClicks<GOAT_STOP_CONFIRM_CLICKS
            && GoatTesterSendStopIfRunning())
           {
            g_GoatStopConfirmClicks++;
            armed=false;
           }
        }
      if(stable>=GOAT_STOP_CONFIRM_STABLE) break;
      Sleep(GOAT_STOP_CONFIRM_POLL_MS);
     }
   g_GoatStopConfirmElapsedMs=GetTickCount64()-started;
   return stable>=GOAT_STOP_CONFIRM_STABLE;
  }
#endif
