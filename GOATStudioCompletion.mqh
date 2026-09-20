#ifndef GOAT_STUDIO_COMPLETION_MQH
#define GOAT_STUDIO_COMPLETION_MQH
// Display only: bind the current native attempt to the shared queue. Never
// infer campaign completion or issue restart from a one-job native summary.
bool GoatStudioCompletionText(const string ea_name,const string server_name,
                              string &progress,string &next_step)
  {
   string config,directory,terminal,run,data,receipt,attempt,snapshot;
   SGOATJsonToken cfg[],owner[],tokens[];
   if(!GoatStudioReadUtf8("GOATStudio\\active.json",config) || !GOATJsonParse(config,cfg)
      || !GOATJsonGetString(config,cfg,0,"directory_id",directory)
      || !GOATJsonGetString(config,cfg,0,"terminal_id",terminal)
      || !GOATJsonGetString(config,cfg,0,"run_id",run)
      || !GOATJsonGetString(config,cfg,0,"terminal_data_path",data)
      || data!=TerminalInfoString(TERMINAL_DATA_PATH)) return false;
   if(!GoatStudioReadUtf8(GoatOptBasePath(ea_name,server_name)+"\\agent-native-control-owner.json",receipt,true)
      || !GOATJsonParse(receipt,owner) || !GOATJsonGetString(receipt,owner,0,"owner",attempt)) return false;
   CGoatStudioBridge bridge;
   if(!bridge.Bind(directory,terminal,run) || !bridge.ReadSnapshot(snapshot)
      || !GOATJsonParse(snapshot,tokens,16384,2000000)) return false;
   int state=GOATJsonFindField(snapshot,tokens,0,"state");
   int queue=GOATJsonFindField(snapshot,tokens,state,"queue");
   if(queue<0 || tokens[queue].type!=GOAT_JSON_ARRAY) return false;
   int total=0,position=0,finished=0,pending=0,matches=0;
   string controller_owner;
   if(!GOATJsonGetString(snapshot,tokens,state,"owner",controller_owner)) return false;
   for(int i=queue+1;i<ArraySize(tokens);i++)
     {
      if(tokens[i].parent!=queue) continue;
      string status,current_attempt;
      if(!GOATJsonGetString(snapshot,tokens,i,"status",status)) return false;
      if(status=="removed" || status=="superseded") continue;
      total++;
      if(status=="completed" || status=="failed" || status=="cancelled") finished++;
      if(status=="pending") pending++;
      if(GOATJsonGetString(snapshot,tokens,i,"restart_attempt_id",current_attempt) && current_attempt==attempt)
        {position=total;matches++;}
     }
   if(matches!=1) return false;
   progress=StringFormat("Queue item %d / %d | %d finished | %d waiting",position,total,finished,pending);
   // Completion is displayed before the host verifies/records this result.
   // Do not promise restart while the host may be paused or at its cutoff.
   next_step=controller_owner=="human" ? "Waiting for human control." :
      (pending>0 ? "Checking result before next restart." : "Final result: checking before batch completion.");
   return true;
  }
#endif
