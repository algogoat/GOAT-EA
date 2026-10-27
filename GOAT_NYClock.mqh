#ifndef GOAT_NYCLOCK_MQH
#define GOAT_NYCLOCK_MQH
// B50 (B50-alpha; docs/b50/B50_ALPHA_DESIGN.md section 3): the New York session clock. Included at the end of
// GOAT V1.49.mq5. A2 owns this file. Clock_Mode, Server_Clock_Model, Server_UTC_Offset, NY_Session and
// Rollover_Block_Minutes are inputs (GOAT_Inputs_Definitions.mqh); OnInit validates them and parses NY_Session into
// g_GoatNYStartMin/EndMin. Tests: scripts/test_b50_clock.cjs (expected behaviour plus mutants).
//
// Flags off (Clock_Server and Rollover_Block_Minutes=0) GoatNYClockApply returns at its first line, so the server
// clock stays in charge and no entry is ever blocked (B49a). Server_Clock_Model is read only when the New York clock
// or the rollover block is on.
//
// Clock models (every time below is a datetime, seconds; MQL5 datetimes carry no zone):
// - US DST: from the 2nd Sunday of March 07:00 UTC (02:00 EST) to the 1st Sunday of November 06:00 UTC (02:00 EDT);
// - EU DST: from the last Sunday of March to the last Sunday of October, both 01:00 UTC;
// - ServerClock_NYClose: NY = server - 7 h all year (the broker follows US DST, 17:00 NY = 00:00 server);
// - ServerClock_Fixed:   UTC = server - Server_UTC_Offset h;
// - ServerClock_EUDST:   UTC = server - Server_UTC_Offset h - 1 h while EU DST is active;
// - then NY = UTC - (US DST ? 4 : 5) h.
// The transition hours are ambiguous by one hour; they fall on a Sunday while the market is shut.

// B50 clock state. g_GoatNYClockMismatch: the last live self-check failed (fails closed: entries blocked);
// g_GoatNYClockChecked: TimeGMT of that check (0 = not yet); g_GoatNYPauseClose: Sequence_Pause_Close as the New York
// clock left it (see GoatNYClockApply); g_GoatNYTesterNoted: the tester's one log line that it trusts the model.
bool     g_GoatNYClockMismatch=false;
datetime g_GoatNYClockChecked=0;
bool     g_GoatNYPauseClose=false;
bool     g_GoatNYTesterNoted=false;

//--- calendar (pure)
// 00:00 of a calendar date.
datetime GoatNYDate(const int year,const int mon,const int day)
  {
   MqlDateTime st;
   st.year=year; st.mon=mon; st.day=day; st.hour=0; st.min=0; st.sec=0; st.day_of_week=0; st.day_of_year=0;
   return StructToTime(st);
  }
// 0 = Sunday .. 6 = Saturday.
int GoatNYWeekday(const datetime t)
  {
   MqlDateTime st;
   TimeToStruct(t,st);
   return st.day_of_week;
  }
int GoatNYYear(const datetime t)
  {
   MqlDateTime st;
   TimeToStruct(t,st);
   return st.year;
  }
// The day of the month of its n-th Sunday (n >= 1).
int GoatNYNthSunday(const int year,const int mon,const int n)
  {
   int first=1+(7-GoatNYWeekday(GoatNYDate(year,mon,1)))%7;
   return first+7*(n-1);
  }
// The day of the month of its last Sunday (last_day: 31 for March and October).
int GoatNYLastSunday(const int year,const int mon,const int last_day)
  {
   return last_day-GoatNYWeekday(GoatNYDate(year,mon,last_day));
  }

//--- daylight saving (pure; UTC in, UTC out)
datetime GoatNYUSDSTStart(const int year)
  {
   return GoatNYDate(year,3,GoatNYNthSunday(year,3,2))+7*3600;
  }
datetime GoatNYUSDSTEnd(const int year)
  {
   return GoatNYDate(year,11,GoatNYNthSunday(year,11,1))+6*3600;
  }
datetime GoatNYEUDSTStart(const int year)
  {
   return GoatNYDate(year,3,GoatNYLastSunday(year,3,31))+3600;
  }
datetime GoatNYEUDSTEnd(const int year)
  {
   return GoatNYDate(year,10,GoatNYLastSunday(year,10,31))+3600;
  }
bool GoatNYUSDST(const datetime utc)
  {
   int year=GoatNYYear(utc);
   return (utc>=GoatNYUSDSTStart(year) && utc<GoatNYUSDSTEnd(year));
  }
bool GoatNYEUDST(const datetime utc)
  {
   int year=GoatNYYear(utc);
   return (utc>=GoatNYEUDSTStart(year) && utc<GoatNYEUDSTEnd(year));
  }

//--- the server clock models (pure but for the three model inputs)
// New York wall-clock time of a UTC time.
datetime GoatNYFromUTC(const datetime utc)
  {
   if(GoatNYUSDST(utc)) return utc-4*3600;
   return utc-5*3600;
  }
// UTC of a server time under Server_Clock_Model.
datetime GoatNYServerToUTC(const datetime server_time)
  {
   if(Server_Clock_Model==ServerClock_NYClose)
     {
      datetime ny=server_time-7*3600;
      datetime utc_summer=ny+4*3600;
      if(GoatNYUSDST(utc_summer)) return utc_summer;
      return ny+5*3600;
     }
   datetime utc=server_time-Server_UTC_Offset*3600;
   if(Server_Clock_Model==ServerClock_EUDST)
     {
      datetime utc_summer=utc-3600;
      if(GoatNYEUDST(utc_summer)) return utc_summer;
     }
   return utc;
  }
// GoatNYTime(server_time): the New York wall-clock time of a server time under Server_Clock_Model.
datetime GoatNYTime(const datetime server_time)
  {
   if(Server_Clock_Model==ServerClock_NYClose) return server_time-7*3600;
   return GoatNYFromUTC(GoatNYServerToUTC(server_time));
  }

//--- the session and the rollover window (pure)
// The phase of a New York time in the NY_Session window [start_min, end_min) (minutes after NY midnight; start > end
// crosses midnight). A session counts only on a Mon-Fri NY date and belongs to the date it starts on (ruling 5), whose
// weekday lands in session_dow. 0: before the session (or no session that date), 1: in the session, 2: after it, up to
// NY midnight (or, crossing midnight, up to the next start): the day end of session_dow's session.
int GoatNYSessionPhase(const int dow,const int minute,const int start_min,const int end_min,int &session_dow)
  {
   session_dow=dow;
   if(start_min<end_min)
     {
      if(dow<1 || dow>5) return 0;
      if(minute<start_min) return 0;
      if(minute<end_min) return 1;
      return 2;
     }
   if(minute>=start_min)
     {
      if(dow<1 || dow>5) return 0;
      return 1;
     }
   session_dow=(dow+6)%7;   // before the start: the tail of the previous date's session, or its day end
   if(session_dow<1 || session_dow>5) return 0;
   if(minute<end_min) return 1;
   return 2;
  }
// No new entry while |NY - 17:00| < minutes (symmetric, to the second; 0 = off).
bool GoatNYRolloverBlocked(const datetime ny_time,const int minutes)
  {
   if(minutes<=0) return false;
   MqlDateTime st;
   TimeToStruct(ny_time,st);
   int gap=st.hour*3600+st.min*60+st.sec-17*3600;   // -61200 .. 25199
   if(gap<=-43200) gap+=86400;                      // the nearer 17:00 (before midnight a gap of -18 h is +6 h)
   if(gap<0) gap=-gap;
   return (gap<minutes*60);
  }
// The live self-check: the model's UTC of the server's time agrees with the terminal's GMT within 90 s. No clock
// (a zero time) fails it.
bool GoatNYClockAgrees(const datetime server_time,const datetime gmt)
  {
   if(server_time<=0 || gmt<=0) return false;
   long gap=(long)(GoatNYServerToUTC(server_time)-gmt);
   if(gap<0) gap=-gap;
   return (gap<=90);
  }

//--- GoatNYClockApply(k): called once a second right after the server-clock session block of GoatTickBody (k is that
// block's weekday index, unused here: the New York clock keys the session to its own weekday).
// - Live charts only, once a minute: the self-check; a failure sets g_GoatEntryBlocked and "CLOCK MISMATCH" on the panel
//   until a later check passes. The tester's TimeGMT is the server time, so the tester never checks: it trusts the
//   model, and says so once in the log.
// - g_GoatEntryBlocked = the mismatch or the rollover window (Rollover_Block_Minutes, under either clock).
// - Clock_NewYork: Active, InActive and Sequence_Pause_Close as the server session block sets them (main, after
//   "if(IsNewSecond())"), from the NY session; Sequence_New_Friday from the session's NY weekday; the NY day-end and
//   Friday actions (Action_Dayend, Action_Friday) in place of the server ones, which A0 switched off for Clock_NewYork.
//   The server session block still runs first each second. Under Clock_NewYork its table (Hour_Start..Minute_End, read
//   only by that block, the switched-off server day end and the panel's "Today's Schedule") is opened to 00:00-24:00,
//   so the block never forces InActive=true (which would re-run InitializeFlags at every signal check and end the
//   virtual sequences on every tick while the server session is shut and the NY one open); the one thing it still
//   does, clearing Sequence_Pause_Close while InActive, is undone from g_GoatNYPauseClose (nothing else writes that
//   flag between two calls under Clock_NewYork).
void GoatNYClockApply(const int k)
  {
   if(Clock_Mode!=Clock_NewYork && Rollover_Block_Minutes<=0) return;   // flags off: the server clock, nothing blocked
   bool live=(MQLInfoInteger(MQL_TESTER)==0 && MQLInfoInteger(MQL_OPTIMIZATION)==0);
   if(live)
     {
      datetime gmt=TimeGMT();
      if(g_GoatNYClockChecked==0 || gmt-g_GoatNYClockChecked>=60 || gmt<g_GoatNYClockChecked)
        {
         datetime server_now=TimeTradeServer();
         bool agrees=GoatNYClockAgrees(server_now,gmt);
         if(agrees==g_GoatNYClockMismatch)
           {
            if(agrees) Print("B50 clock: the self-check passes again (Server_Clock_Model=",(int)Server_Clock_Model,", Server_UTC_Offset=",Server_UTC_Offset,"); new entries resume");
            else       Print("B50 clock: CLOCK MISMATCH, the model's UTC of server time ",TimeToString(server_now)," is ",(long)(GoatNYServerToUTC(server_now)-gmt),
                             " s from TimeGMT ",TimeToString(gmt),
                             " (Server_Clock_Model=",(int)Server_Clock_Model,", Server_UTC_Offset=",Server_UTC_Offset,"); no new entries");
           }
         g_GoatNYClockMismatch=!agrees;
         g_GoatNYClockChecked=gmt;
        }
     }
   else
     {
      g_GoatNYClockMismatch=false;
      if(!g_GoatNYTesterNoted)
        {
         g_GoatNYTesterNoted=true;
         Print("B50 clock: the tester has no GMT, so it trusts Server_Clock_Model=",(int)Server_Clock_Model,", Server_UTC_Offset=",Server_UTC_Offset,
               " (Clock_Mode=",(int)Clock_Mode,", NY_Session=",NY_Session,", Rollover_Block_Minutes=",Rollover_Block_Minutes,")");
        }
     }
   datetime ny=GoatNYTime(TimeCurrent());
   g_GoatEntryBlocked=(g_GoatNYClockMismatch || GoatNYRolloverBlocked(ny,Rollover_Block_Minutes));
   if(Clock_Mode!=Clock_NewYork)
     {
      if(g_GoatNYClockMismatch && !GoatCidGuardRefuses()) SetEdit(PanelDialog.m_edit_Info_2,"CLOCK MISMATCH",clrRed,Font_Size);
      return;
     }
   Sequence_Pause_Close=g_GoatNYPauseClose;   // as this clock left it (the server block may have just cleared it)
   for(int b50_d=0;b50_d<7;b50_d++) {Hour_Start[b50_d]=0; Minute_Start[b50_d]=0; Hour_End[b50_d]=24; Minute_End[b50_d]=0;}
   MqlDateTime nst;
   TimeToStruct(ny,nst);
   int session_dow=nst.day_of_week;
   int phase=GoatNYSessionPhase(nst.day_of_week,nst.hour*60+nst.min,g_GoatNYStartMin,g_GoatNYEndMin,session_dow);
   if(phase==1)
     {
      Active=true; SetEdit(PanelDialog.m_edit_Info_2,Strat,clr_Text,Font_Size);
      if(InActive) {Sequence_Pause_Close=false;}
     }
   else {Active=false; InActive=true; SetEdit(PanelDialog.m_edit_Info_2,"INACTIVE",clrRed,Font_Size);}
   if(GoatCidGuardRefuses())        SetEdit(PanelDialog.m_edit_Info_2,"REFUSED: "+g_GoatCidGuardReason,clrRed,Font_Size); // B46: CID refusal on the panel
   else if(g_GoatNYClockMismatch)   SetEdit(PanelDialog.m_edit_Info_2,"CLOCK MISMATCH",clrRed,Font_Size);

   int new_dow=(phase==1 ? session_dow : nst.day_of_week);
   if(!Trade_Friday && new_dow==5) Sequence_New_Friday=false;
   else                            Sequence_New_Friday=true;

   // End of the NY session (main's day end, keyed to the session's NY date)
   if(InActive && phase==2)
     {
      if(Action_Dayend==Action_Close) StopOut_Flag = true;
      if(Action_Dayend==Action_Pause) Sequence_Pause_Close = true;
     }
   // End of Friday's NY session
   if(InActive && phase==2 && session_dow==5)
     {
      if(Action_Friday==Action_Close) StopOut_Flag = true;
      if(Action_Friday==Action_Pause) Sequence_Pause_Close = true;
     }
   g_GoatNYPauseClose=Sequence_Pause_Close;
  }
#endif
