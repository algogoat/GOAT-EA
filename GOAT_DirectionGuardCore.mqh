// Platform calls are supplied by GOAT_DirectionGuard.mqh (or the concurrency test).
// No timeout can evict an owner. A vanished owner is reclaimable only after its
// pending request is resolved and actual account exposure is absent.
bool GoatGuardClaim(const string key,const double token,const int direction)
  {
   if(token<=0.0 || !GuardStoreEnsure(key)) return false;
   double owner=GuardStoreRead(key);
   if(owner==token) return !GuardOwnerPending(owner,direction);
   if(owner!=0.0)
     {
      if(GuardOwnerAlive(owner) || GuardOwnerPending(owner,direction) || GuardActualExposure(direction)) return false;
      if(!GuardStoreCAS(key,0.0,owner)) return false;
     }
   if(!GuardStoreCAS(key,token,0.0)) return false;
   // Recheck after winning: catches positions created before acquisition and
   // prevents a fresh sequence after a restart with surviving broker exposure.
   if(GuardActualExposure(direction))
     {
      GuardStoreCAS(key,0.0,token);
      return false;
     }
   return true;
  }

bool GoatGuardRelease(const string key,const double token,const int direction)
  {
   if(token<=0.0 || GuardOwnerPending(token,direction) || GuardActualExposure(direction)) return false;
   return GuardStoreCAS(key,0.0,token);
  }
