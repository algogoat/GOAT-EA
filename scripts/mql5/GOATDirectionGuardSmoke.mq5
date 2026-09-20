#property strict
bool owners[3]={false,true,true};
bool exposure[2]={false,false};
bool pending[3]={false,false,false};
bool GuardStoreEnsure(const string key) {return GlobalVariableTemp(key);}
double GuardStoreRead(const string key) {double value=-1.0;if(!GlobalVariableGet(key,value))return -1.0;return value;}
bool GuardStoreCAS(const string key,const double value,const double expected) {return GlobalVariableSetOnCondition(key,value,expected);}
bool GuardOwnerAlive(const double token) {return owners[(int)token];}
bool GuardOwnerPending(const double token,const int direction) {return pending[(int)token];}
bool GuardActualExposure(const int direction) {return exposure[direction];}
#include "..\..\GOAT_DirectionGuardCore.mqh"
int passed=0,failed=0,receipt=INVALID_HANDLE;
void Check(const bool okay,const string name)
  {
   if(okay) passed++; else failed++;
   string line=(okay ? "PASS " : "FAIL ")+name;
   Print(line);if(receipt!=INVALID_HANDLE) FileWrite(receipt,line);
  }
void OnStart()
  {
   if(StringFind(TerminalInfoString(TERMINAL_DATA_PATH),"guard-native-portable")<0)
     {Print("REFUSED: dedicated isolated portable terminal required");return;}
   receipt=FileOpen("guard-native-smoke.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   string key="GOAT.GUARD.SMOKE."+IntegerToString((long)GetTickCount64());
   Check(GuardStoreEnsure(key),"atomic create");
   Check(GuardStoreRead(key)==0.0,"new temporary global starts at zero");
   Check(GoatGuardClaim(key,1.0,0),"first claim");
   Check(GuardStoreEnsure(key) && GuardStoreRead(key)==1.0,"repeated Temp does not overwrite owner");
   Check(!GoatGuardClaim(key,2.0,0),"second claimant blocked");
   exposure[0]=true;
   Check(GoatGuardClaim(key,1.0,0) && !GoatGuardRelease(key,1.0,0),"owner add and partial remain owned");
   owners[1]=false;
   Check(!GoatGuardClaim(key,2.0,0),"restart actual exposure blocks reclaim");
   exposure[0]=false;pending[1]=true;
   Check(!GoatGuardClaim(key,2.0,0),"orphan pending request blocks reclaim");
   pending[1]=false;
   Check(GoatGuardClaim(key,2.0,0),"resolved flat orphan reclaimed atomically");
   Check(GoatGuardRelease(key,2.0,0) && GoatGuardClaim(key,1.0,0),"immediate release and reentry");
   GlobalVariableDel(key);
   FolderCreate("GOATGuard");string found="";ResetLastError();
   long search=FileFindFirst("GOATGuard\\NO_SUCH_MARKER_987654.*.pending",found);
   int find_error=GetLastError();if(search!=INVALID_HANDLE)FileFindClose(search);
   Check(search==INVALID_HANDLE,"empty durable-marker scan");
   FileWrite(receipt,"EMPTY_FIND_ERROR="+IntegerToString(find_error));
   int marker=FileOpen("GOATGuard\\smoke.pending",FILE_WRITE|FILE_TXT|FILE_ANSI);
   Check(marker!=INVALID_HANDLE,"durable marker create");
   if(marker!=INVALID_HANDLE){FileWrite(marker,"isolated-smoke-owner");FileFlush(marker);FileClose(marker);}
   Check(FileIsExist("GOATGuard\\smoke.pending"),"flushed marker survives close");
   Check(FileDelete("GOATGuard\\smoke.pending"),"resolved marker removed");
   string result=StringFormat("GUARD_NATIVE_SMOKE passed=%d failed=%d",passed,failed);
   Print(result);if(receipt!=INVALID_HANDLE){FileWrite(receipt,result);FileFlush(receipt);FileClose(receipt);}
  }
