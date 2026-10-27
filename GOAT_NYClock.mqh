#ifndef GOAT_NYCLOCK_MQH
#define GOAT_NYCLOCK_MQH
// B50 (B50-alpha; docs/b50/B50_ALPHA_DESIGN.md section 3): the New York session clock. Included at the end of
// GOAT V1.49.mq5. A0 ships this stub, whose functions keep the server-clock behaviour of B49a; A2 fills the bodies
// and owns this file. Clock_Mode, Server_Clock_Model, Server_UTC_Offset, NY_Session and Rollover_Block_Minutes are
// inputs (GOAT_Inputs_Definitions.mqh); OnInit validates them and parses NY_Session into g_GoatNYStartMin/EndMin.
//
// GoatNYTime(server_time): the New York wall-clock time of a server time under Server_Clock_Model. The stub answers
// the server time itself (the server clock).
datetime GoatNYTime(const datetime server_time)
  {
   return server_time;
  }
// GoatNYClockApply(k): called once a second right after the server-clock session block of GoatTickBody (k is that
// block's weekday index). Under Clock_NewYork it sets Active, InActive and Sequence_Pause_Close from the NY session,
// recomputes Sequence_New_Friday from the NY weekday and runs the NY day-end and Friday actions; with
// Rollover_Block_Minutes>0, or a live clock mismatch, it sets g_GoatEntryBlocked. The stub changes nothing, so the
// server clock stays in charge and no entry is ever blocked.
void GoatNYClockApply(const int k)
  {
   if(Clock_Mode!=Clock_NewYork && Rollover_Block_Minutes<=0) return;
  }
#endif
