#ifndef GOAT_EVIDENCE_END_MQH
#define GOAT_EVIDENCE_END_MQH
// Export evidence end (FU35, capability goat-evidence-end-v1, rule
// goat-closed-week-v1 of controller/studio_evidence_end.py). The export setting
// EvidenceEnd names the last inclusive broker server day that exported evidence
// covers. MT5's tester ToDate is exclusive, so exports run to EvidenceEnd + 1 day
// and every exported deal, equity row and sequence frame ends at that boundary.
//   absent or empty -> unchanged legacy end: ToDate = the last Friday (today if
//                      Friday), so evidence ends on a Thursday.
//   AUTO            -> the last fully closed Friday on this server's clock. Before
//                      the server date leaves Friday, that is the previous Friday.
//   YYYY.MM.DD      -> an explicit closed server day (before server today).
// Never before the optimization window end. The controller resolves AUTO once at
// prepare and passes the explicit date, so all members of a batch (and its
// successors) share one timeline even across a Friday close. A refused value
// stops the export search; it never falls back to another end.
#define GOAT_EVIDENCE_END_CAPABILITY "goat-evidence-end-v1"
#define GOAT_EVIDENCE_DAY_SECONDS 86400

// Days from server today back to the Friday that ends the last closed week.
// MQL day_of_week is Sunday=0..Saturday=6 (Friday=5); a Friday is still open.
int GoatEvidenceFridayDaysBack(const int day_of_week)
  {
   int back=(day_of_week+2)%7;
   return back==0 ? 7 : back;
  }

datetime GoatEvidenceDay(const datetime moment)
  {
   return (datetime)((long)moment-(long)moment%GOAT_EVIDENCE_DAY_SECONDS);
  }

bool GoatEvidenceParseDay(const string text,datetime &day)
  {
   // The exact round trip accepts only YYYY.MM.DD (TimeToString's own form) and
   // rejects impossible dates such as 2026.02.30, times, dashes and padding.
   day=StringToTime(text);
   return day>0 && TimeToString(day,TIME_DATE)==text;
  }

// Exclusive tester ToDate (YYYY.MM.DD) for a non-empty EvidenceEnd setting, or ""
// with a plain reason when the setting is refused.
string GoatEvidenceEndToDate(const string setting,const datetime server_now,const datetime window_end,string &evidence_end,string &error)
  {
   evidence_end="";
   error="";
   string value=setting;
   StringTrimLeft(value);
   StringTrimRight(value);
   if(server_now<=0) {error="EvidenceEnd: broker server time is unavailable";return "";}
   datetime today=GoatEvidenceDay(server_now);
   datetime end=0;
   if(value=="AUTO" || value=="auto" || value=="Auto")
     {
      // 1970.01.01 was a Thursday (day_of_week 4).
      int day_of_week=(int)(((long)today/GOAT_EVIDENCE_DAY_SECONDS+4)%7);
      end=today-GoatEvidenceFridayDaysBack(day_of_week)*GOAT_EVIDENCE_DAY_SECONDS;
     }
   else
     {
      if(!GoatEvidenceParseDay(value,end)) {error="EvidenceEnd must be AUTO or a date such as 2026.09.25, not '"+value+"'";return "";}
      if(end>=today) {error="EvidenceEnd "+value+" is not a closed broker day yet (server date "+TimeToString(today,TIME_DATE)+")";return "";}
     }
   if(window_end>0 && end<GoatEvidenceDay(window_end))
     {
      error="EvidenceEnd "+TimeToString(end,TIME_DATE)+" is before the optimization window end "+TimeToString(window_end,TIME_DATE)+"; nothing new would be tested";
      return "";
     }
   evidence_end=TimeToString(end,TIME_DATE);
   return TimeToString(end+GOAT_EVIDENCE_DAY_SECONDS,TIME_DATE);
  }
#endif
