#ifndef GOAT_BATCH_CANCEL_ORIGIN_MQH
#define GOAT_BATCH_CANCEL_ORIGIN_MQH
#define GOAT_BATCH_HUMAN_CANCEL_GV "GOAT_BatchHumanCancelled"

// Values 1 and unknown nonzero values are human/legacy stops, never agent-clearable.
// Only this build's explicit controller cancellation writes value 2.
void GoatBatchRecordControllerCancel(void)
  {
   double cancelled=GlobalVariableGet(GOAT_BATCH_CANCELLED_GV);
   if(cancelled!=0.0) return;
   if(GlobalVariableCheck(GOAT_BATCH_CANCELLED_GV))
      GlobalVariableSetOnCondition(GOAT_BATCH_CANCELLED_GV,2.0,0.0);
   else
      GlobalVariableSet(GOAT_BATCH_CANCELLED_GV,2.0);
  }

bool GoatBatchReleaseControllerCancel(void)
  {
   if(GlobalVariableGet(GOAT_BATCH_HUMAN_CANCEL_GV)!=0.0) return false;
   double cancelled=GlobalVariableGet(GOAT_BATCH_CANCELLED_GV);
   if(cancelled==0.0) return true;
   if(cancelled!=2.0) return false;
   // Compare-and-swap cannot erase a human stop written since the read.
   if(!GlobalVariableSetOnCondition(GOAT_BATCH_CANCELLED_GV,0.0,2.0)) return false;
   return GlobalVariableGet(GOAT_BATCH_HUMAN_CANCEL_GV)==0.0
      && GlobalVariableGet(GOAT_BATCH_CANCELLED_GV)==0.0;
  }
#endif
