#property strict
#property service
#property description "Isolated recovery inventory fixture. Refuses existing GOATStudio; no grants, native requests, trading or globals."
#include "../../../GOATStudioRecoveryFiles.mqh"
int output=INVALID_HANDLE,failures=0,checks=0;
void Expect(bool value,string label)
  {checks++;if(!value)failures++;FileWrite(output,value?"PASS":"FAIL",label);}
void Touch(string path)
  {int h=FileOpen(path,FILE_WRITE|FILE_BIN);if(h==INVALID_HANDLE){Expect(false,"create "+path);return;}FileWriteString(h,"native fixture only");FileClose(h);}
bool Scan(){int count=0;return GoatStudioRecoveryLocalTree("GOATStudio",count);}
void OnStart()
  {
   output=FileOpen("RecoveryDirectoryFixture.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');if(output==INVALID_HANDLE)return;
   ResetLastError();bool existing=FileIsExist("GOATStudio");int error=GetLastError();
   if(existing || error==ERR_FILE_IS_DIRECTORY || error!=ERR_FILE_NOT_EXIST)
     {Expect(false,"refuse existing or unknown GOATStudio");FileClose(output);return;}
   FolderCreate("GOATStudio");FolderCreate("GOATStudio\\native-gate");FolderCreate("GOATStudio\\empty");FolderCreate("GOATStudio\\nested");
   Touch("GOATStudio\\native-gate\\controller.json");Touch("GOATStudio\\native-gate\\request.json");Touch("GOATStudio\\native-gate\\permit.json");
   int gate=FileOpen("GOATStudio\\native-gate\\launch.lock",FILE_READ|FILE_WRITE|FILE_BIN);
   string name;bool observed=false;long find=FileFindFirst("GOATStudio\\*",name);
   if(find!=INVALID_HANDLE){do {if(name=="native-gate\\"){observed=true;string old_path="GOATStudio\\"+name+"\\controller.json";
      Expect(old_path!="GOATStudio\\native-gate\\controller.json","old join reproduces own-owner rejection");
      Expect(GoatStudioRecoveryFindName(name),"normalize actual native directory name");
      Expect("GOATStudio\\"+name+"\\controller.json"=="GOATStudio\\native-gate\\controller.json","exact owner path after normalization");}}
      while(FileFindNext(find,name));FileFindClose(find);}
   Expect(observed,"actual MT5 enumeration returns trailing separator");
   Expect(gate!=INVALID_HANDLE && Scan(),"single native owner and empty inboxes accepted under held gate");
   string foreign[]={"controller.json","request.json","permit.json","pending.json","seed-active.json"};
   for(int i=0;i<ArraySize(foreign);i++){string path="GOATStudio\\nested\\"+foreign[i];Touch(path);Expect(!Scan(),"refuse nested "+foreign[i]);FileDelete(path);Expect(Scan(),"restored valid tree "+foreign[i]);}
   string invalid[]={"", ".", "..", "..\\", "a\\b", "a/b", "C:", "name\\\\"};
   for(int i=0;i<ArraySize(invalid);i++){string value=invalid[i];Expect(!GoatStudioRecoveryFindName(value),"reject invalid component "+invalid[i]);}
   int count=0;Expect(!GoatStudioRecoveryLocalTree("GOATStudio",count,13),"depth limit unchanged");count=50000;Expect(!GoatStudioRecoveryLocalTree("GOATStudio",count),"entry limit unchanged");
   string common="GOAT V1.49-Demo\\";Expect(GoatStudioRecoveryFindName(common) && "GOAT\\"+common+"\\active_optimization_run.ini"=="GOAT\\GOAT V1.49-Demo\\active_optimization_run.ini","common control path canonical");
   Expect(GoatStudioRecoveryCommonClear(),"current common inventory clear (read only)");
   if(gate!=INVALID_HANDLE)FileClose(gate);
   FileDelete("GOATStudio\\native-gate\\controller.json");FileDelete("GOATStudio\\native-gate\\request.json");FileDelete("GOATStudio\\native-gate\\permit.json");FileDelete("GOATStudio\\native-gate\\launch.lock");
   FolderDelete("GOATStudio\\native-gate");FolderDelete("GOATStudio\\nested");FolderDelete("GOATStudio\\empty");FolderDelete("GOATStudio");
   FileWrite(output,"RESULT",checks,failures,__MQLBUILD__);FileFlush(output);FileClose(output);
   PrintFormat("RECOVERY_DIRECTORY_FIXTURE checks=%d failures=%d build=%d",checks,failures,__MQLBUILD__);
  }