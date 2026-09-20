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
bool GoatStudioReadWorkerPolicy(bool &local,bool &remote,bool &cloud)
  {
   local=false;remote=false;cloud=false;
   // Control IDs/menu protocol are verified on this build only.
   if(IsStopped() || !MQLInfoInteger(MQL_DLLS_ALLOWED) || TerminalInfoInteger(TERMINAL_BUILD)!=6182) return false;
   uint pid=kernel32::GetCurrentProcessId();
   for(long existing=user32::GetTopWindow(0);existing;existing=user32::GetWindow(existing,2))
     {
      uint owner=0;user32::GetWindowThreadProcessId(existing,owner);ushort name[64];
      if(owner==pid && user32::GetClassNameW(existing,name,64) && ShortArrayToString(name)=="#32768") return false;
     }
   if(!MTTESTER::LockWaiting(1)) return false;
   long agents=MTTESTER::ShowTesterAgents();
   if(!agents || !user32::PostMessageW(agents,0x007B,agents,ULONG_MAX))
     {MTTESTER::Lock(false);return false;}
   ulong deadline=GetTickCount64()+3000;
   bool verified=false;
   while(!IsStopped() && GetTickCount64()<deadline && !verified)
     {
      for(long window=user32::GetTopWindow(0);window;window=user32::GetWindow(window,2))
        {
         uint owner=0;user32::GetWindowThreadProcessId(window,owner);
         if(owner!=pid) continue;
         ushort name[64];
         if(!user32::GetClassNameW(window,name,64) || ShortArrayToString(name)!="#32768") continue;
         StudioMenuBarInfo info;ZeroMemory(info);info.cbSize=sizeof(info);
         if(!GetMenuBarInfo(window,-4,0,info) || !info.hMenu) continue;
         uint a=user32::GetMenuState(info.hMenu,33521,0);
         uint b=user32::GetMenuState(info.hMenu,33522,0);
         uint c=user32::GetMenuState(info.hMenu,33525,0);
         if(a==UINT_MAX || b==UINT_MAX || c==UINT_MAX) continue;
         local=(a&8)!=0;remote=(b&8)!=0;cloud=(c&8)!=0;
         bool closing=user32::PostMessageW(window,WM_KEYDOWN,VK_ESCAPE,0)!=0;
         ulong close_deadline=GetTickCount64()+500;
         while(closing && user32::IsWindowVisible(window) && GetTickCount64()<close_deadline) Sleep(10);
         verified=closing && !user32::IsWindowVisible(window);
         MTTESTER::Lock(false);
         return verified;
        }
      Sleep(20);
     }
   MTTESTER::Lock(false);
   return false;
  }
#endif
