// Controller-only long-path byte IO through the existing MTTESTER Win32 layer.
// The native tester producer stays within short sandbox paths and needs no DLL IO.
#ifndef GOAT_SEQUENCE_HOST_IO_MQH
#define GOAT_SEQUENCE_HOST_IO_MQH
#define GOAT_SEQ_LONG_PATH "\\\\?\\"
bool GoatSeqHostAllowed()
  {
   bool context=!MQLInfoInteger(MQL_TESTER);
#ifdef GOAT_SEQUENCE_HOST_TEST
   context=context || Test_Host_IO;
#endif
   return context && MQLInfoInteger(MQL_DLLS_ALLOWED);
  }

string GoatSeqHostAbsolute(const string relative)
  {
   // Never allow the host adapter to escape the Common/Files sandbox.
   if(relative=="" || StringFind(relative,":")>=0 || StringFind(relative,"/")>=0 || StringSubstr(relative,0,1)=="\\") return "";
   string parts[];int count=StringSplit(relative,'\\',parts);
   for(int i=0;i<count;++i) if(parts[i]==".." || parts[i]=="." || parts[i]=="") return "";
   return TerminalInfoString(TERMINAL_COMMONDATA_PATH)+"\\Files\\"+relative;
  }

bool GoatSeqHostExists(const string path)
  {
   string full=GoatSeqHostAbsolute(path);
   return GoatSeqHostAllowed() && full!="" && MTTESTER::FileIsExist(full);
  }

bool GoatSeqHostCopy(const string source,const string destination)
  {
   string from=GoatSeqHostAbsolute(source),to=GoatSeqHostAbsolute(destination);
   return GoatSeqHostAllowed() && from!="" && to!="" && MTTESTER::FileCopy(from,to,false);
  }

bool GoatSeqHostMove(const string source,const string destination)
  {
   string from=GoatSeqHostAbsolute(source),to=GoatSeqHostAbsolute(destination);
   return GoatSeqHostAllowed() && from!="" && to!="" && MTTESTER::FileMove(from,to,false);
  }

bool GoatSeqHostDelete(const string path)
  {
   string full=GoatSeqHostAbsolute(path);
   return GoatSeqHostAllowed() && full!="" && kernel32::DeleteFileW(GOAT_SEQ_LONG_PATH+full);
  }

bool GoatSeqHostRemoveEmpty(const string path)
  {
   string full=GoatSeqHostAbsolute(path);
   return GoatSeqHostAllowed() && full!="" && kernel32::RemoveDirectoryW(GOAT_SEQ_LONG_PATH+full);
  }

bool GoatSeqHostList(const string path,string &names[])
  {
   ArrayResize(names,0);
   string full=GoatSeqHostAbsolute(path);
   if(!GoatSeqHostAllowed() || full=="") return false;
   FIND_DATAW data;
   HANDLE find=kernel32::FindFirstFileW(GOAT_SEQ_LONG_PATH+full+"\\*",data);
   if(find==INVALID_HANDLE) return false;
   bool ok=true;
   do
     {
      string name=ShortArrayToString(data.cFileName);
      if(name=="." || name=="..") continue;
      if((data.dwFileAttributes & 0x10)!=0) {ok=false;break;} // v1 is flat, never recurse
      int n=ArraySize(names);ArrayResize(names,n+1);names[n]=name;
     }while(kernel32::FindNextFileW(find,data));
   kernel32::FindClose(find);
   return ok && ArraySize(names)>0;
  }

string GoatSeqHostStage(const string source)
  {
   string path="GOATSeqIO\\"+(string)ChartID()+"-"+(string)GetMicrosecondCount()+".bin";
   return GoatSeqHostCopy(source,path) ? path : "";
  }
#endif
