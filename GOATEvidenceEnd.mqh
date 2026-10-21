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

// The EvidenceEnd value of an [Export] settings text (trimmed), or "" when absent.
string GoatEvidenceSettingValue(const string settings)
  {
   string text="\n"+settings;
   string key="\nEvidenceEnd=";
   int at=StringFind(text,key);
   if(at<0) return "";
   at+=StringLen(key);
   int stop=StringFind(text,"\n",at);
   string found=(stop<0 ? StringSubstr(text,at) : StringSubstr(text,at,stop-at));
   StringTrimLeft(found);
   StringTrimRight(found);
   return found;
  }

// B38: the Studio has no EvidenceEnd control, so every rewrite of
// export_settings.GOAT from the controls (save, rename, .goatbatch load, human
// Start) carries the staged EvidenceEnd forward from the settings it replaces.
// Dropping it would silently end every export on the legacy Thursday.
string GoatEvidenceEndCarry(const string rewritten,const string previous)
  {
   if(rewritten=="" || GoatEvidenceSettingValue(rewritten)!="") return rewritten;
   string value=GoatEvidenceSettingValue(previous);
   if(value=="") return rewritten;
   string separator=(StringSubstr(rewritten,StringLen(rewritten)-1)=="\n" ? "" : "\n");
   return rewritten+separator+"EvidenceEnd="+value+"\n";
  }

// The day an export really ended, from its .set header: the end of the
// "; FOOS:   from-to" range (the tester clock at OnTester, i.e. the last tick),
// else the "; SAMPLE: from-to" range; "" when neither is readable.
string GoatEvidenceHeaderEnd(const string set_text,const string tag)
  {
   int at=StringFind(set_text,tag);
   if(at<0) return "";
   int dash=StringFind(set_text,"-",at);
   if(dash<0) return "";
   string end=StringSubstr(set_text,dash+1,10);
   datetime day=0;
   if(!GoatEvidenceParseDay(end,day)) return "";
   return end;
  }

string GoatEvidenceExportEnd(const string set_text)
  {
   string end=GoatEvidenceHeaderEnd(set_text,"; FOOS:");
   return (end!="" ? end : GoatEvidenceHeaderEnd(set_text,"; SAMPLE:"));
  }
#endif
