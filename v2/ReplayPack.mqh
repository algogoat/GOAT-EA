#ifndef GOAT_V2_REPLAY_PACK_MQH
#define GOAT_V2_REPLAY_PACK_MQH

#include "IntelligenceBus.mqh"

class CV2ReplayPack
  {
public:
   bool InitializeDisabled(string &reason)
     {
      reason="";
      return true;
     }

   bool Load(const string path,string &reason)
     {
      reason="PHASE2_REPLAY_PACK_NOT_CERTIFIED";
      return false;
     }
  };

#endif
