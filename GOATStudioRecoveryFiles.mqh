#ifndef GOAT_STUDIO_RECOVERY_FILES_MQH
#define GOAT_STUDIO_RECOVERY_FILES_MQH
// FileFindFirst/Next return directory names with a trailing backslash in MT5.
// Normalize one component before joining; never accept an embedded path or alias.
bool GoatStudioRecoveryFindName(string &name)
  {
   int length=StringLen(name);
   if(length>0 && StringSubstr(name,length-1)=="\\") name=StringSubstr(name,0,length-1);
   return StringLen(name)>0 && name!="." && name!=".."
      && StringFind(name,"\\")<0 && StringFind(name,"/")<0 && StringFind(name,":")<0;
  }

bool GoatStudioRecoveryLocalTree(const string root,int &count,const int depth=0)
  {
   if(depth>12) return false;
   string name;long search=FileFindFirst(root+"\\*",name);
   if(search==INVALID_HANDLE) return false; // Unknown/empty roots are not proof.
   bool ok=true;
   do
     {
      if(++count>50000 || !GoatStudioRecoveryFindName(name)) {ok=false;break;}
      string path=root+"\\"+name,lower=name;StringToLower(lower);ResetLastError();bool file=FileIsExist(path);
      if(!file && GetLastError()==ERR_FILE_IS_DIRECTORY)
        {
         // Empty inboxes are normal; only descend where entries exist.
         string child;long found=FileFindFirst(path+"\\*",child);
         if(found!=INVALID_HANDLE)
           {FileFindClose(found);if(!GoatStudioRecoveryLocalTree(path,count,depth+1)) {ok=false;break;}}
        }
      else if(!file) {ok=false;break;}
      else if(lower=="controller.json" && path!="GOATStudio\\native-gate\\controller.json") {ok=false;break;}
      else if((lower=="request.json" || lower=="permit.json") && root!="GOATStudio\\native-gate") {ok=false;break;}
      else if(lower=="pending.json" || lower=="seed-active.json") {ok=false;break;}
     }
   while(FileFindNext(search,name));
   FileFindClose(search);return ok;
  }

bool GoatStudioRecoveryCommonClear(void)
  {
   string name;long search=FileFindFirst("GOAT\\*",name,FILE_COMMON);
   if(search==INVALID_HANDLE) return false;
   int count=0;bool ok=true;
   do
     {
      if(++count>10000 || !GoatStudioRecoveryFindName(name)) {ok=false;break;}
      string lower=name;StringToLower(lower);
      if(StringFind(lower,"goat v")!=0) continue;
      string base="GOAT\\"+name;
      string controls[]={"active_optimization_run.ini","active_optimization_config.ini",
                         "active_optimization_launch.ini","agent-native-control-owner.json"};
      for(int i=0;i<ArraySize(controls);i++)
         if(FileIsExist(base+"\\"+controls[i],FILE_COMMON)) {ok=false;break;}
      if(!ok) break;
     }
   while(FileFindNext(search,name));
   FileFindClose(search);return ok;
  }
#endif
