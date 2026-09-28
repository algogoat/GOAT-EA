#ifndef GOAT_STUDIO_CONTROL_FEEDBACK_MQH
#define GOAT_STUDIO_CONTROL_FEEDBACK_MQH
// Presentation only. A click never confirms authority; the verified receipt does.
string g_StudioControlRequest="",g_StudioControlCommand="",g_StudioControlError="";
ulong g_StudioControlSince=0;
int g_StudioControlOutcome=0; // 0 none, 1 waiting, 2 applied receipt, 3 refused/local failure.

void GoatStudioControlBegin(const string id,const string command)
  {
   if(command!="control.grant_agent" && command!="control.takeover") return;
   if(id==g_StudioControlRequest) return; // Recovery/refresh must not reset the wait.
   g_StudioControlRequest=id; g_StudioControlCommand=command;
   g_StudioControlSince=GetTickCount64(); g_StudioControlOutcome=1; g_StudioControlError="";
  }

void GoatStudioControlResolve(const bool applied,const string error)
  {
   g_StudioControlOutcome=applied ? 2 : 3;
   g_StudioControlError=error!="" ? error : "Controller refused the request";
  }

void GoatStudioControlFailure(const string error)
  {
   if(g_StudioControlOutcome==1) return; // Keep an outstanding request visible.
   g_StudioControlOutcome=3; g_StudioControlError=error;
  }

string GoatStudioControlText(const string owner)
  {
   if(g_StudioControlOutcome==1)
     {
      if(GetTickCount64()-g_StudioControlSince>=30000)
         return "Still waiting for controller; request retained";
      return g_StudioControlCommand=="control.grant_agent"
         ? "Connecting agent... waiting for confirmation" : "Taking control... waiting for confirmation";
     }
   if(g_StudioControlOutcome==3) return "Request not applied: "+g_StudioControlError;
   if(g_StudioControlOutcome==2)
     {
      // A newer committed snapshot can supersede the acknowledged handover.
      if(owner=="agent") return "Confirmed: agent controls settings";
      if(owner=="human") return "Confirmed: you control settings";
     }
   return "";
  }
#endif
