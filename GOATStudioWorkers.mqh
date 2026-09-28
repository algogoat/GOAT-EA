#ifndef GOAT_STUDIO_WORKERS_MQH
#define GOAT_STUDIO_WORKERS_MQH
// Read the native policy; no worker command is selected. Caller checks runtime
// ownership and remains responsible for rechecking before a launch side effect.
struct StudioMenuBarInfo pack(8)
  {
   uint cbSize;
   RECT rcBar;
   long hMenu;
   long hwndMenu;
   int focused;
  };
#import "user32.dll"
int GetMenuBarInfo(long hwnd,int object,int item,StudioMenuBarInfo &info);
int GetMenuStringW(long menu,uint item,ushort &text[],int maximum,uint flags);
#import

// Only dismiss a menu created by this probe in the current terminal process.
bool GoatStudioCloseWorkerPopup(const long window,const uint pid)
  {
   if(!window) return true;
   uint owner=0;
   user32::GetWindowThreadProcessId(window,owner);
   if(owner!=pid) return false;
   if(!user32::IsWindowVisible(window)) return true;
   if(!user32::PostMessageW(window,WM_KEYDOWN,VK_ESCAPE,0)) return false;
   ulong deadline=GetTickCount64()+500;
   while(user32::IsWindowVisible(window) && GetTickCount64()<deadline) Sleep(10);
   return !user32::IsWindowVisible(window);
  }

bool GoatStudioReadWorkerPolicy(bool &local,bool &remote,bool &cloud)
  {
   local=false;remote=false;cloud=false;
   // MT5 build numbers change independently of this menu contract. Require
   // the actual owned Agents control, expected commands and their captions.
   if(IsStopped() || !MQLInfoInteger(MQL_DLLS_ALLOWED)) return false;
   uint pid=kernel32::GetCurrentProcessId();
   for(long existing=user32::GetTopWindow(0);existing;existing=user32::GetWindow(existing,2))
     {
      uint owner=0;user32::GetWindowThreadProcessId(existing,owner);ushort name[64];
      if(owner==pid && user32::GetClassNameW(existing,name,64) && ShortArrayToString(name)=="#32768") return false;
     }
   if(!MTTESTER::LockWaiting(1)) return false;
   long agents=MTTESTER::ShowTesterAgents();
   uint agent_owner=0;
   if(agents) user32::GetWindowThreadProcessId(agents,agent_owner);
   if(!agents || agent_owner!=pid || !user32::PostMessageW(agents,0x007B,agents,ULONG_MAX))
     {MTTESTER::Lock(false);return false;}
   ulong deadline=GetTickCount64()+3000;
   long popup=0;
   bool found=false,want_local=false,want_remote=false,want_cloud=false;
   while(!IsStopped() && GetTickCount64()<deadline && !found)
     {
      for(long window=user32::GetTopWindow(0);window;window=user32::GetWindow(window,2))
        {
         uint owner=0;user32::GetWindowThreadProcessId(window,owner);
         if(owner!=pid) continue;
         ushort name[64];
         if(!user32::GetClassNameW(window,name,64) || ShortArrayToString(name)!="#32768") continue;
         popup=window;
         StudioMenuBarInfo info;ZeroMemory(info);info.cbSize=sizeof(info);
         if(!GetMenuBarInfo(window,-4,0,info) || !info.hMenu) continue;
         uint a=user32::GetMenuState(info.hMenu,33521,0);
         uint b=user32::GetMenuState(info.hMenu,33522,0);
         uint c=user32::GetMenuState(info.hMenu,33525,0);
         if(a==UINT_MAX || b==UINT_MAX || c==UINT_MAX) continue;
         ushort local_text[128],remote_text[128],cloud_text[128];
         if(GetMenuStringW(info.hMenu,33521,local_text,128,0)<=0
            || GetMenuStringW(info.hMenu,33522,remote_text,128,0)<=0
            || GetMenuStringW(info.hMenu,33525,cloud_text,128,0)<=0) continue;
         string local_name=ShortArrayToString(local_text);
         string remote_name=ShortArrayToString(remote_text);
         string cloud_name=ShortArrayToString(cloud_text);
         StringToLower(local_name);StringToLower(remote_name);StringToLower(cloud_name);
         // Unknown or localized captions require an explicit capability update.
         if(StringFind(local_name,"local")<0 || StringFind(remote_name,"remote")<0
            || StringFind(cloud_name,"cloud")<0) continue;
         want_local=(a&8)!=0;want_remote=(b&8)!=0;want_cloud=(c&8)!=0;
         PrintFormat("GOAT_STUDIO_WORKER_READBACK build=%d local=%s:%d remote=%s:%d cloud=%s:%d",(int)TerminalInfoInteger(TERMINAL_BUILD),local_name,(int)want_local,remote_name,(int)want_remote,cloud_name,(int)want_cloud);
         found=true;
         break;
        }
      if(!found) Sleep(20);
     }
   // A delayed menu can appear just as the bounded wait ends. We started
   // with no owned menu, so dismiss that newly owned popup before returning.
   if(!popup)
     {
      for(long window=user32::GetTopWindow(0);window;window=user32::GetWindow(window,2))
        {
         uint owner=0;user32::GetWindowThreadProcessId(window,owner);
         if(owner!=pid) continue;
         ushort name[64];
         if(user32::GetClassNameW(window,name,64) && ShortArrayToString(name)=="#32768")
           {popup=window;break;}
        }
     }
   bool popup_closed=GoatStudioCloseWorkerPopup(popup,pid);
   MTTESTER::Lock(false);
   if(!found || !popup_closed) return false;
   local=want_local;remote=want_remote;cloud=want_cloud;
   return true;
  }
#endif
