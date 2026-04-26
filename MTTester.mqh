#property strict

// #define RUNEX5_SILENT // Возможность запускать EX5 в Silent-режиме.

#ifdef RUNEX5_SILENT
  #resource "RunMe.ex5" as uchar RunMe[] // https://www.mql5.com/ru/forum/478178/page10#comment_55702486
#endif // #ifdef RUNEX5_SILENT

#include <WinAPI\WinAPI.mqh>

#define GA_ROOT           0x00000002

#define BM_CLICK          0x000000F5

#define WM_KEYDOWN        0x0100
#define WM_CHAR           0x0102
#define WM_LBUTTONDOWN    0x0201
#define WM_CLOSE          0x0010
#define WM_COMMAND        0x0111

#define VK_RETURN         0x0D
#define VK_ESCAPE         0x1B
#define VK_HOME           0x24
#define VK_LEFT           0x25
#define VK_RIGHT          0x27
#define VK_DOWN           0x28
#define VK_DELETE         0x2E

#define DTM_SETSYSTEMTIME 0x1002

#define GW_HWNDNEXT     2
#define GW_CHILD        5

#define CB_GETLBTEXT     0x0148
#define CB_GETLBTEXTLEN  0x0149

#define GMEM_MOVEABLE   2
#define CF_UNICODETEXT  13
#define CF_TEXT         1

#define ID_EDIT_PASTE 0xE125
#define ID_EDIT_COPY  0xE122

#define PROCESS_QUERY_INFORMATION 0x0400

#define FILE_ATTRIBUTE_DIRECTORY 0x00000010
#define INVALID_FILE_ATTRIBUTES UINT_MAX

#define LVM_GETITEMCOUNT 0x1004

#import "user32.dll"
  PVOID SendMessageW( HANDLE, uint, PVOID, int &[] );
  PVOID SendMessageW( HANDLE, uint, PVOID, short &[] );
#import

#define LONG_PATH_ATTR "\\\\?\\"

#import "kernel32.dll"
  bool CopyFileW( string lpExistingFileName, string lpNewFileName, bool bFailIfExists );
  int ReadFile( HANDLE file, uchar &buffer[], uint number_of_bytes_to_read, uint &number_of_bytes_read, PVOID overlapped );
  int WriteFile( HANDLE file, const uchar &buffer[], uint number_of_bytes_to_write, uint &number_of_bytes_written, PVOID overlapped );
  string lstrcatW( HANDLE Dst, string Src );
  int    lstrcpyW( HANDLE ptrhMem, string Text );
  int QueryFullProcessImageNameW( HANDLE process, uint flags, short &Buffer[], uint &size );
#import

class MTTESTER
{
private:
  static string arrayToHex(uchar &arr[])
  {
    string res = "";
    for(int i = 0; i < ::ArraySize(arr); i++)
    {
      res += ::StringFormat("%.2X", arr[i]);
    }
    return(res);
  }

  static long GetHandle( const int &ControlID[] )
  {
    static const bool MT5_b5050 = (::TerminalInfoInteger(TERMINAL_BUILD) > 5000);

    long Handle = MTTESTER::GetTerminalHandle();
    const int Size = ::ArraySize(ControlID);

    for (int i = 0; i < Size; i++)
      if (!MT5_b5050 || (ControlID[i] != 0xE81E))
        Handle = user32::GetDlgItem(Handle, ControlID[i]);

    return(Handle);
  }

  static int GetLastPos( const string &Str, const short Char )
  {
    int Pos = ::StringLen(Str) - 1;

    while ((Pos >= 0) && (Str[Pos] != Char))
      Pos--;

    return(Pos);
  }

  static string GetPathExe( const HANDLE Handle )
  {
    string Str = NULL;

    uint processId = 0;

    if (user32::GetWindowThreadProcessId(Handle, processId))
    {
      const HANDLE processHandle = kernel32::OpenProcess(PROCESS_QUERY_INFORMATION, false, processId);

      if (processHandle)
      {
        short Buffer[MAX_PATH] = {0};

        uint Size = ::ArraySize(Buffer);

        if (kernel32::QueryFullProcessImageNameW(processHandle, 0, Buffer, Size))
          Str = ::ShortArrayToString(Buffer, 0, Size);

        kernel32::CloseHandle(processHandle);
      }
      else
        ::Print("Error: terminal \"" + ::TerminalInfoString(TERMINAL_PATH) + "\" without administrator rights!");
    }

    return(Str);
  }

  static string GetClassName( const HANDLE Handle )
  {
    string Str = NULL;

    ushort Buffer[MAX_PATH] = {0};

    if (user32::GetClassNameW(Handle, Buffer, ::ArraySize(Buffer)))
      Str = ::ShortArrayToString(Buffer);

    return(Str);
  }

  static string StringBetween( string &Str, const string StrBegin, const string StrEnd = NULL )
  {
    string Res = NULL;
    int PosBegin = ::StringFind(Str, StrBegin);

    if ((PosBegin >= 0) || (StrBegin == NULL))
    {
      PosBegin = (PosBegin >= 0) ? PosBegin + ::StringLen(StrBegin) : 0;

      const int PosEnd = ::StringFind(Str, StrEnd, PosBegin);

      if (PosEnd != PosBegin)
        Res = ::StringSubstr(Str, PosBegin, (PosEnd >= 0) ? PosEnd - PosBegin : -1);

      Str = (PosEnd >= 0) ? ::StringSubstr(Str, PosEnd + ::StringLen(StrEnd)) : NULL;

      if (Str == "")
        Str = NULL;
    }

    return((Res == "") ? NULL : Res);
  }

  static bool GetClipboard( string &Str, const int Attempts = 3 )
  {
    bool Res = false;
    Str = NULL;

    for (int j = 0; (j < Attempts) && !Res/* && !::IsStopped()*/; j++) // Глобальному деструктору может понадобиться
      if (user32::OpenClipboard(0))
      {
//        const HANDLE hglb = user32::GetClipboardData(CF_TEXT);
        const HANDLE hglb = user32::GetClipboardData(CF_UNICODETEXT);

        if (hglb)
        {
          const HANDLE lptstr = kernel32::GlobalLock(hglb);

          if (lptstr)
          {
            kernel32::GlobalUnlock(hglb);
/*
            short Array[];
            const int Size = ::StringToShortArray(kernel32::lstrcatW(lptstr, ""), Array) - 1;

            //Str = ::CharArrayToString(_R(Array).Bytes); // TypeToBytes.mqh

            if ((Size > 0) && ::StringReserve(Str, Size << 1))
              for (int i = 0; i < Size; i++)
              {
                const uchar Char1 = (uchar)Array[i];

                if (Char1)
                  Str += ::CharToString(Char1);
                else
                  break;

                const uchar Char2 = uchar(Array[i] >> 8);

                if (Char2)
                  Str += ::CharToString(Char2);
                else
                  break;
              }
*/
            Str = kernel32::lstrcatW(lptstr, "");
            Res = true;
          }
        }

        user32::CloseClipboard();
      }
      else
        ::Sleep(10);

    return(Res);
  }

  static bool SetClipboard( const string Str, const int Attempts = 3 )
  {
    bool Res = false;

    for (int j = 0; (j < Attempts) && !Res/* && !::IsStopped()*/; j++) // Глобальному деструктору может понадобиться
      if (user32::OpenClipboard(0))
      {
        if (user32::EmptyClipboard())
        {
          const HANDLE hMem = kernel32::GlobalAlloc(GMEM_MOVEABLE, (::StringLen(Str) + 1) << 1);

          if (hMem)
          {
            const HANDLE ptrMem = kernel32::GlobalLock(hMem);

            if (ptrMem)
            {
              kernel32::lstrcpyW(ptrMem, Str);
              kernel32::GlobalUnlock(hMem);

              Res = user32::SetClipboardData(CF_UNICODETEXT, hMem);
            }

            if (!ptrMem || !Res)
              kernel32::GlobalFree(hMem);
          }
        }

        user32::CloseClipboard();
      }
      else
        ::Sleep(10);

    return (Res);
  }

  static string GetFreshFileName( const string Path, const string Mask )
  {
    string Str = NULL;

    FIND_DATAW FindData;
    const HANDLE handle = kernel32::FindFirstFileW(Path + Mask, FindData);

    if (handle != INVALID_HANDLE)
    {
      ulong MaxTime = 0;
//      ulong Size = 0;

      do
      {
        const ulong TempTime = ((ulong)FindData.ftLastWriteTime.dwHighDateTime << 32) + FindData.ftLastWriteTime.dwLowDateTime;

        if (TempTime > MaxTime)
        {
          MaxTime = TempTime;

          Str = ::ShortArrayToString(FindData.cFileName);
//          Size = ((ulong)FindData.nFileSizeHigh << 32) + FindData.nFileSizeLow;;
        }
      }
      while (kernel32::FindNextFileW(handle, FindData));

      kernel32::FindClose(handle);
    }

    return((Str == NULL) ? NULL : Path + Str);
  }

  static int DeleteFolder( const string FolderName )
  {
    int Res = 0;

    FIND_DATAW FindData;
    const HANDLE handle = kernel32::FindFirstFileW(FolderName + "\\*", FindData);

    if (handle != INVALID_HANDLE)
    {
      do
      {
        if (FindData.cFileName[0] != '.')
        {
          const string Name = FolderName + "\\" + ::ShortArrayToString(FindData.cFileName);

          Res += (bool)(FindData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? MTTESTER::DeleteFolder(Name) : kernel32::DeleteFileW(Name);

        }
      }
      while (kernel32::FindNextFileW(handle, FindData));

      kernel32::FindClose(handle);

      Res += kernel32::RemoveDirectoryW(FolderName);
    }

    return(Res);
  }

  static string GetLastTstCacheFileName2( void )
  {
    return(MTTESTER::GetFreshFileName(::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\", "*.tst"));
  }

  static string GetLastOptCacheFileName2( void )
  {
    return(MTTESTER::GetFreshFileName(::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\", "*.opt"));
  }

  static string GetLastConfigFileName( void )
  {
    return(MTTESTER::GetFreshFileName(::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\MQL5\\Profiles\\Tester\\", "*.ini"));
  }

  static bool IsChart( const long Handle )
  {
/*
    bool Res = false;

    for (long Chart = ::ChartFirst(), handle = user32::GetDlgItem(Handle, 0xE900);
         (Chart != -1) && !(Res = (::ChartGetInteger(Chart, CHART_WINDOW_HANDLE) == handle));
         Chart = ::ChartNext(Chart))
      ;

    return(Res);
*/
    return((bool)user32::GetDlgItem(user32::GetDlgItem(Handle, 0xE900), 0x27CE));
  }

  static bool SetTime( const long Handle, const datetime time )
  {
    const bool Res = time && MTTESTER::IsReady();

    if (Res)
    {
      MqlDateTime TimeStruct;
      ::TimeToStruct(time, TimeStruct);

      int SysTime[2];

      SysTime[0] = (TimeStruct.mon << 16) | TimeStruct.year;
      SysTime[1] = (TimeStruct.day << 16) | TimeStruct.day_of_week;

      user32::SendMessageW(Handle, DTM_SETSYSTEMTIME, 0, SysTime);
    }

    return(Res || !time);
  }

  static string GetComboBoxString( const long Handle )
  {
    short Buf[];

    // https://www.mql5.com/ru/forum/318305/page20#comment_17747389
    ::ArrayResize(Buf, (int)user32::SendMessageW(Handle, CB_GETLBTEXTLEN, 0, 0 ) + 1);
    user32::SendMessageW(Handle, CB_GETLBTEXT, 0, Buf);

    return(::ShortArrayToString(Buf));
  }

  static void Sleep2( const uint Pause )
  {
    const uint StartTime = ::GetTickCount();

    while (!::IsStopped() && (::GetTickCount() - StartTime) < Pause)
      ::Sleep(0);

    return;
  }

  static bool StartTester( void )
  {
    string Str;

    return(MTTESTER::GetSettings2(Str));
  }

  static bool IsReady2( void )
  {
    static bool bInit = MTTESTER::StartTester();

    static const int ControlID[] = {0xE81E, 0x804E, 0x2712, 0x4196};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    ushort Str[6];

    if (!::IsStopped()) // Иначе зависание при снятии советника.
      user32::GetWindowTextW(Handle, Str, sizeof(Str) / sizeof(ushort));

    const string Name = ::ShortArrayToString(Str);
    bool Res = (Name == "Старт") || (Name == "Start");

    static int Count = 0;

    if (!Res && (Name == "") && (Count < 10))
    {
      MTTESTER::StartTester();
      Count++;

      Res = MTTESTER::IsReady2();
    }

    Count = 0;

    return(Res);
  }

  static string GetStatusString( void )
  {
    static const int ControlID[] = {0xE81E, 0x804E, 0x2791};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    ushort Str[64];

    if (!::IsStopped()) // Иначе зависание при снятии советника.
      user32::GetWindowTextW(Handle, Str, sizeof(Str) / sizeof(ushort));

    return(::ShortArrayToString(Str));
  }

  static int GetAgentNames( string &AgentNames[] )
  {
    ::ArrayFree(AgentNames);

    return(MTTESTER::GetFileNames(::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\", "Agent*.*", AgentNames));
  }

  static string GetBeginFileName( void )
  {
    string Res = NULL;
    string Str;

    if (MTTESTER::GetSettings2(Str))
    {
      string ExpertName = MTTESTER::GetValue(Str, "Expert");
      const int Pos = MTTESTER::GetLastPos(ExpertName, '\\') + 1;

      ExpertName = ::StringSubstr(ExpertName, Pos, ::StringLen(ExpertName) - Pos - 4);

      Res = ExpertName + "." + MTTESTER::GetValue(Str, "Symbol") + "." + MTTESTER::GetValue(Str, "Period");

      string FromDate = MTTESTER::GetValue(Str, "FromDate");
      ::StringReplace(FromDate, ".", NULL);

      string ToDate = MTTESTER::GetValue(Str, "ToDate");
      ::StringReplace(ToDate, ".", NULL);

      Res += "." + FromDate + "_" + ToDate + "." + MTTESTER::GetValue(Str, "Model");
    }

    return(Res);
  }

  static int GetJournalItemCount( void )
  {
    static const int ControlID[] = {0xE81E, 0x804E, 0x28ED};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    return((int)user32::SendMessageW(Handle, LVM_GETITEMCOUNT, 0, 0));
  }

#define GENERIC_READ  0x80000000
#define GENERIC_WRITE 0x40000000
#define SHARE_READ    1
#define OPEN_EXISTING 3
#define OPEN_ALWAYS   4
#define CREATE_ALWAYS 2

  static bool IsLibraryOrService( const string FileName )
  {
      bool Res = true;
      const HANDLE handle = kernel32::CreateFileW(FileName, GENERIC_READ, SHARE_READ, 0, OPEN_EXISTING, 0, 0);

      if (handle != INVALID_HANDLE)
      {
        uchar Buffer[4];
        uint Read;

        kernel32::ReadFile(handle, Buffer, sizeof(Buffer), Read, 0);
        Res = (Read < sizeof(Buffer)) || ((Buffer[3] == 3) || (Buffer[3] == 5)); // 1 - Script, 2 - Expert, 3 - Library, 4 - Indicator, 5 - Service.

        kernel32::CloseHandle(handle);
      }

    return(Res);
  }

  static int GetEX5FileNames( const string FolderName, string &FileNames[] )
  {
    int Res = 0;

    FIND_DATAW FindData;
    const HANDLE handle = kernel32::FindFirstFileW(FolderName + "\\*", FindData);

    if (handle != INVALID_HANDLE)
    {
      do
      {
        if (FindData.cFileName[0] != '.')
        {
          string Name = FolderName + "\\" + ::ShortArrayToString(FindData.cFileName);

          if ((bool)(FindData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY))
            Res += MTTESTER::GetEX5FileNames(Name, FileNames);
          else if (::StringToLower(Name) && (((::StringSubstr(Name, ::StringLen(Name) - 4) == ".ex5") &&
                                             !MTTESTER::IsLibraryOrService(Name)) ||
                                             (::StringSubstr(Name, ::StringLen(Name) - 3) == ".py")))
          {
            FileNames[::ArrayResize(FileNames, ::ArraySize(FileNames) + 1) - 1] = Name;
            Res++;
          }
        }
      }
      while (kernel32::FindNextFileW(handle, FindData));

      kernel32::FindClose(handle);
    }

    return(Res);
  }

  static void RefreshNumbersEX5( const HANDLE TerminalHandle )
  {
    const uint MT5InternalMsg = user32::RegisterWindowMessageW("MetaTrader5_Internal_Message");

    static const uchar Codes[] = {0x01, 0x02, 0x03, 0x1A, 0x04};

    user32::SendMessageW(TerminalHandle, WM_COMMAND, 0X8288, 0);

    for (int i = 0; i < sizeof(Codes); i++)
      user32::SendMessageW(TerminalHandle, MT5InternalMsg, Codes[i], 0);

    return;
  }

  static int GetNumberEX5( const HANDLE TerminalHandle, string FileName )
  {
    int Res = -1;

    const string Path = MTTESTER::GetTerminalDataPath(TerminalHandle);

    if (Path != "")
    {
      MTTESTER::RefreshNumbersEX5(TerminalHandle);

      string FileNames[];

      MTTESTER::GetEX5FileNames(Path + "\\MQL5\\Experts", FileNames);
      MTTESTER::GetEX5FileNames(Path + "\\MQL5\\Indicators", FileNames);
      MTTESTER::GetEX5FileNames(Path + "\\MQL5\\Scripts", FileNames);

      ::StringToLower(FileName);
      const int Len = ::StringLen(Path + "\\MQL5\\");

      for (Res = ::ArraySize(FileNames) - 1; (Res >= 0) && (::StringSubstr(FileNames[Res], Len) != FileName); Res--)
        ;
    }

    return(Res);
  }

  static int ChartsTotal( const HANDLE TerminalHandle )
  {
    int Res = 0;

    const HANDLE Handle = user32::GetDlgItem(TerminalHandle, 0xE900);
    uchar Pos = 0;

    for (HANDLE Chart = user32::GetDlgItem(Handle, 0xFF00); Chart; Chart = user32::GetDlgItem(Handle, 0xFF00 + ++Pos))
      if (MTTESTER::IsChart(Chart))
        Res++;

    return(Res);
  }

  static bool ChartOpen( const HANDLE TerminalHandle )
  {
    const int Total = MTTESTER::ChartsTotal(TerminalHandle);
            // Открывает новый чарт - опасно (default.tpl).
    return((user32::SendMessageW(TerminalHandle, WM_COMMAND, 0x807F, 0) && (MTTESTER::ChartsTotal(TerminalHandle) > Total)) ||
            // Открывает удаленный чарт - очень опасно (может быть торговый советник).
           (user32::SendMessageW(TerminalHandle, WM_COMMAND, 0xCBE8, 0) && (MTTESTER::ChartsTotal(TerminalHandle) > Total)));
  }

  static HANDLE GetChartHandle( const HANDLE TerminalHandle, const char ChartNumber = 0 )
  {
    const HANDLE Handle = user32::GetDlgItem(TerminalHandle, 0xE900);

    HANDLE Chart = 0;
    uchar Pos = 0;

    if (ChartNumber >= 0)
    {
      uchar Amount = 0;

      for (Chart = user32::GetDlgItem(Handle, 0xFF00); Chart; Chart = user32::GetDlgItem(Handle, 0xFF00 + ++Pos))
        if (MTTESTER::IsChart(Chart) && (ChartNumber == Amount++))
        {
          Chart = user32::GetDlgItem(Chart, 0xE900);

          break;
        }
    }
    else if (MTTESTER::ChartOpen(TerminalHandle))
    {
      HANDLE PrevChart = 0;

      for (Chart = user32::GetDlgItem(Handle, 0xFF00); Chart; Chart = user32::GetDlgItem(Handle, 0xFF00 + ++Pos))
        if (MTTESTER::IsChart(Chart))
          PrevChart = Chart;

      if (PrevChart)
        Chart = user32::GetDlgItem(PrevChart, 0xE900);
    }

    return(Chart);
  }

  template <typename T>
  static int Sort( const T &Array[], int &Indexes[] )
  {
    const int Size = ::ArrayResize(Indexes, ::ArraySize(Array));

    for (int i = 0; i < Size - 1; i++)
    {
      int Pos = i;

      for (int j = i + 1; j < Size; j++)
        if (Array[Pos] > Array[j])
          Pos = j;

      Indexes[i] = Pos;
    }

    return(Size);
  }

  static void SortByPath( HANDLE &Handles[] )
  {
    string Path[];

    for (int i = ::ArrayResize(Path, ::ArraySize(Handles)) - 1; i >= 0; i--)
      Path[i] = MTTESTER::GetPathExe(Handles[i]);

    HANDLE NewHandles[];
    int Indexes[];

    for (int i = ::ArrayResize(NewHandles, MTTESTER::Sort(Path, Indexes)) - 1; i >= 0; i--)
      NewHandles[i] = Handles[Indexes[i]];

    ::ArraySwap(Handles, NewHandles);

    return;
  }

  static int GetInputNames( string &Names[] )
  {
    int Res = 0;
    string Str;

    if (MTTESTER::GetSettings(Str))
    {
      string StrArray[];

      for (int i = ::ArrayResize(Names, Res = ::StringSplit(MTTESTER::StringBetween(Str, "[TesterInputs]"), '\n', StrArray) - 2); (bool)i--;)
        Names[i] = MTTESTER::StringBetween(StrArray[i + 1], NULL, (StrArray[i + 1][0] != ';') ? "=" : "\r");
    }

    return(Res);
  }

  static string GetInputsString( void )
  {
    string Str = NULL;

    string Names[];
    const int Size = MTTESTER::GetInputNames(Names);

    for (int i = 0; i < Size; i++)
      Str += "\r\n" + ((Names[i][0] == ';') ? ("+ \"" + Names[i] + "\\n\"") : ("+ TOSTRING(" + Names[i] + ")"));

    return(Str);
  }

  static string GetTerminalDataPathWrong( const HANDLE TerminalHandle )
  {
    const string Common = ::TerminalInfoString(TERMINAL_COMMONDATA_PATH);

    return(::StringSubstr(Common, 0, StringLen(Common) - 6) + MTTESTER::instance_id(MTTESTER::GetTerminalPath(TerminalHandle)));
  }

  static int GetFileNames( const string Path, const string Mask, string &FileNames[], const bool SubFolders = false, const bool OnlyFolders = false )
  {
    ulong Times[];

    FIND_DATAW FindData;

    const HANDLE handle = kernel32::FindFirstFileW(LONG_PATH_ATTR + Path + Mask, FindData);

    if (handle != INVALID_HANDLE)
    {
      do
      {
        if (FindData.cFileName[0] != '.')
        {
          const bool IsFolder = FindData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY;

          if (OnlyFolders ? IsFolder : !IsFolder)
          {
            FileNames[::ArrayResize(FileNames, ::ArraySize(FileNames) + 1) - 1] = (SubFolders ? Path : NULL) +
                                                                                  ::ShortArrayToString(FindData.cFileName) +
                                                                                  (IsFolder ?  "\\" : NULL);
            Times[::ArrayResize(Times, ::ArraySize(Times) + 1) - 1] = ((ulong)FindData.ftLastWriteTime.dwHighDateTime << 32) +
                                                                      FindData.ftLastWriteTime.dwLowDateTime;
          }

          if (SubFolders && IsFolder)
            MTTESTER::GetFileNames(Path + ::ShortArrayToString(FindData.cFileName) + "\\", Mask, FileNames, SubFolders, OnlyFolders);
        }
      }
      while (kernel32::FindNextFileW(handle, FindData));

      kernel32::FindClose(handle);
    }

    if (!SubFolders && !OnlyFolders)
    {
      ulong Pos[][2];
      const int Size = ::ArrayResize(Pos, ::ArraySize(Times));

      for (int i = 0; i < Size; i++)
      {
        Pos[i][0] = Times[i];
        Pos[i][1] = i;
      }

      ::ArraySort(Pos);

      string Array[];

      const int Size2 = ::ArraySize(FileNames);

      for (int i = ::ArrayResize(Array, Size2) - 1; i >= 0; i--)
        Array[i] = FileNames[(i < Size2 - Size) ? i : (Size2 - Size + (int)Pos[i - Size2 + Size][1])];

      ::ArraySwap(Array, FileNames);
    }

    return(::ArraySize(FileNames));
  }

  static string GetDirectory( const string FileName )
  {
    int Pos = ::StringFind(FileName, "\\");
    int LastPos = Pos;

    while (Pos >= 0)
    {
      LastPos = Pos;

      Pos = ::StringFind(FileName, "\\", Pos + 1);
    }

    return((LastPos >= 0) ? ::StringSubstr(FileName, 0, LastPos + 1) : "");
  }

  static HANDLE GetMainWindowHandle( const string ClassName = "MetaQuotes::MetaTrader::5.00", string FolderPath = NULL )
  {
    HANDLE Handle = 0;

    if (FolderPath == NULL)
      FolderPath = ::TerminalInfoString(TERMINAL_PATH);

    for (Handle = user32::GetTopWindow(NULL); Handle; Handle = user32::GetWindow(Handle, GW_HWNDNEXT))
      if (MTTESTER::GetClassName(Handle) == ClassName)
      {
      const string ExePath = MTTESTER::GetPathExe(Handle);

      if (::StringSubstr(ExePath, 0, MTTESTER::GetLastPos(ExePath, '\\')) == FolderPath)
        break;
      }

    return(Handle);
  }

public:
  static HANDLE GetTerminalHandle( void )
  {
    static HANDLE Handle = 0;

    if (!Handle)
    {
      if (::MQLInfoInteger(MQL_TESTER) || (::MQLInfoInteger(MQL_PROGRAM_TYPE) == PROGRAM_SERVICE))
        Handle = MTTESTER::GetMainWindowHandle();
      else
        Handle = user32::GetAncestor(::ChartGetInteger(0, CHART_WINDOW_HANDLE), GA_ROOT);
    }

    return(Handle);
  }

  static HANDLE GetVisualizatorHandle( void )
  {
    return(MTTESTER::GetMainWindowHandle("MetaQuotes::MetaTester::5.00"));
  }

  static string GetTerminalCaption( void )
  {
    ushort Str[128];

    if (!::IsStopped()) // Иначе зависание при снятии советника.
      user32::GetWindowTextW(MTTESTER::GetTerminalHandle(), Str, sizeof(Str) / sizeof(ushort));

    return(::ShortArrayToString(Str));

  }

  static int GetPassesDone( void )
  {
    string Status = MTTESTER::GetStatusString();

    return((int)MTTESTER::StringBetween(Status, ": ", " /"));
  }

  static bool GetSettings( string &Str, const int Attempts = 10 )
  {
    bool Res = false;

    Str = NULL;

    if (/*!::IsStopped() &&*/ (::StringFind(Str, "[Tester]") || MTTESTER::SetClipboard("", Attempts))) // Глобальному деструктору может понадобиться
    {
      const uint MT5InternalMsg = user32::RegisterWindowMessageW("MetaTrader5_Internal_Message");
      const HANDLE HandleRoot = MTTESTER::GetTerminalHandle();

      static const int ControlID[] = {0xE81E, 0x804E};
      static const long Handle = MTTESTER::GetHandle(ControlID);

      for (int j = 0; (j < Attempts) && !Res/* && !::IsStopped()*/; j++) // Глобальному деструктору может понадобиться
      {
        user32::SendMessageW(HandleRoot, MT5InternalMsg, 9, INT_MAX);

//        SetFocus(Handle);

        // MT4build2209+ - не актуально.
//        user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, 0x17007C); // Выбор вкладки "Настройки"
        user32::SendMessageW(Handle, WM_COMMAND, ID_EDIT_COPY, 0);

        ::Sleep(10);

        Res = MTTESTER::GetClipboard(Str, Attempts) && !::StringFind(Str, "[Tester]");
      }
    }

    return(Res);
  }

  static bool SetSettings( const string Str )
  {
    const bool Res = MTTESTER::SetClipboard(Str);

    if (Res)
    {
      const uint MT5InternalMsg = user32::RegisterWindowMessageW("MetaTrader5_Internal_Message");
      user32::SendMessageW(MTTESTER::GetTerminalHandle(), MT5InternalMsg, 9, INT_MAX);

      static const int ControlID[] = {0xE81E, 0x804E};
      static const long Handle = MTTESTER::GetHandle(ControlID);

    // MT4build2209+ - не актуально.
      //user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, 0x17007C); // Выбор вкладки "Настройки"
      user32::SendMessageW(Handle, WM_COMMAND, ID_EDIT_PASTE, 0);

    // MT4build2209+ - не актуально.
//      user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, 0x1200EF); // https://www.mql5.com/ru/forum/321656/page25#comment_13873612 - Параметры
//      user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, 0x17007C); // Выбор вкладки "Настройки"

      ::Sleep(100);
    }

    return(Res);
  }

  static bool SetSettings2( string Str, const int Attempts = 5 )
  {
    bool Res = false;

    if (MTTESTER::LockWaiting())
    {
      for (int j = 0; (j < Attempts) && !Res; j++)
      {
        string Str1;
        string Str2;
        string Str3;

        Res = MTTESTER::SetSettings(Str) && MTTESTER::GetSettings(Str1) &&
              MTTESTER::SetSettings(Str) && MTTESTER::GetSettings(Str2) &&
              MTTESTER::SetSettings(Str) && MTTESTER::GetSettings(Str3) &&
              (Str1 == Str2) && (Str1 == Str3);
      }

      MTTESTER::Lock(false);
    }

    return(Res);
  }

  static bool GetSettings2( string &Str, const int Attempts = 10 )
  {
    bool Res = false;

    if (MTTESTER::LockWaiting())
    {
      Res = MTTESTER::GetSettings(Str, Attempts);

      MTTESTER::Lock(false);
    }

    return(Res);
  }
//-------------------------------------------------------------------------
static bool IsIdle()
  {
   // 1) Fresh handle every call
   static const int ControlID[] = {0xE81E, 0x804E, 0x2712, 0x4196};
   const long hBtn = MTTESTER::GetHandle(ControlID);

   ushort cap[16] = {0};
   if(!IsStopped() && hBtn)
     user32::GetWindowTextW(hBtn, cap, sizeof(cap)/sizeof(ushort));

   string name = ShortArrayToString(cap);

   if(name=="Start" || name=="Старт") return true;   // idle
   if(name=="Stop"  || name=="Стоп" ) return false;  // running
   // 2) Transient/blank caption: nudge & retry once
   MTTESTER::StartTester();
   const long hBtn2 = MTTESTER::GetHandle(ControlID);
   if(hBtn2)
     {
      ushort cap2[16] = {0};
      user32::GetWindowTextW(hBtn2, cap2, sizeof(cap2)/sizeof(ushort));
      name = ShortArrayToString(cap2);

      if(name=="Start" || name=="Старт") return true;
      if(name=="Stop"  || name=="Стоп" ) return false;
     }
   // 3) Heuristic fallback via status text
   string status = MTTESTER::GetStatusString();
   if(status != NULL)
     {
      string s = status;
      StringToLower(s); // in-place
      if(StringFind(s,"/")>=0
      || StringFind(s,"test")>=0
      || StringFind(s,"initializ")>=0)
        return false; // running
     }
   // 4) Last resort: consider idle
   return true;
  }
//-------------------------------------------------------------------------
  static bool SetSettingsPart( string Str, string StrPrev, const int Attempts = 5 )
  {
    return(MTTESTER::SetSettings2(MTTESTER::StringBetween(Str, NULL, "[TesterInputs]") + "[TesterInputs]" +
                                  MTTESTER::StringBetween(StrPrev, "[TesterInputs]") + Str, Attempts));
  }


  // Если входные параметры советника заданы не все, то их значения берутся с предыдущего советника.
  static bool SetSettingsPart( string Str, const int Attempts = 5 )
  {
    string StrPrev;
/*
    string StrTmp = Str;

    StrTmp = MTTESTER::GetValue(MTTESTER::StringBetween(StrTmp, NULL, "[TesterInputs]"), "Expert");

    return(((StrTmp == NULL) || MTTESTER::GetSettings2(StrPrev)) && MTTESTER::SetSettings2(Str, Attempts) &&
           ((StrTmp == NULL) || (MTTESTER::GetValue(MTTESTER::StringBetween(StrPrev, NULL, "[TesterInputs]"), "Expert") ==
             MTTESTER::GetValue(MTTESTER::StringBetween(Str, NULL, "[TesterInputs]"), "Expert")) ||
             (MTTESTER::SetSettings2("[TesterInputs]" + StrPrev, Attempts) &&
              MTTESTER::SetSettings2("[TesterInputs]" + Str, Attempts))));
*/
    return(MTTESTER::GetSettings2(StrPrev) && MTTESTER::SetSettingsPart(Str, StrPrev, Attempts));
  }

  static int GetLastOptCache( uchar &Bytes[] )
  {
    const string FileName = MTTESTER::GetLastOptCacheFileName2();

    return((FileName != NULL) ? MTTESTER::FileLoad(FileName, Bytes) : -1);
  }

  static int GetLastTstCache( uchar &Bytes[], const bool FromSettings = false )
  {
    int Count = 0;

    string FileName = NULL;

    const string BeginFileName = FromSettings ? MTTESTER::GetBeginFileName() : NULL;

    while (!::IsStopped() && (Count++ < 10) && (FileName == NULL))
    {
      FileName = MTTESTER::GetLastTstCacheFileName2();

      if (FileName == NULL || (FromSettings && (::StringFind(FileName, BeginFileName) == -1)))
      {
        FileName = NULL;

        ::Sleep(500);
      }
    }

    return((FileName != NULL) ? MTTESTER::FileLoad(FileName, Bytes) : -1);
  }

  static string GetExpertName( void )
  {
    static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x28F5};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    return(MTTESTER::GetComboBoxString(Handle));
  }

  static string GetSymbolName( void )
  {
    string Str;;

    return(MTTESTER::GetSettings(Str) ? MTTESTER::StringBetween(Str, "Symbol=", "\r\n") : NULL);
  }

  static bool SetExpertName( const string ExpertName = NULL )
  {
    bool Res = (ExpertName == NULL);

    if (!Res)
    {
      const string PrevExpertName = MTTESTER::GetExpertName();

      if (!(Res = (PrevExpertName == ExpertName)))
      {
        static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x28F5};
        static const long Handle = MTTESTER::GetHandle(ControlID);

        user32::SendMessageW(Handle, WM_LBUTTONDOWN, 0, 0);

        const long Handle2 = user32::GetLastActivePopup(MTTESTER::GetTerminalHandle());

        user32::SendMessageW(Handle2, WM_KEYDOWN, VK_LEFT, 0);
        user32::SendMessageW(Handle2, WM_KEYDOWN, VK_LEFT, 0);

        // Нужно для инициализации.
        for (int i = 0; i < 3; i++)
          user32::SendMessageW(Handle2, WM_CHAR, ':', 0);

        user32::SendMessageW(Handle2, WM_KEYDOWN, VK_HOME, 0);

        const int Size = ::StringLen(ExpertName);

        for (int i = 0; i < Size; i++)
          if (ExpertName[i] == '\\')
          {
            user32::SendMessageW(Handle2, WM_KEYDOWN, VK_RIGHT, 0);
            user32::SendMessageW(Handle2, WM_KEYDOWN, VK_RIGHT, 0);
            user32::SendMessageW(Handle2, WM_KEYDOWN, VK_LEFT, 0);
          }
          else
            user32::SendMessageW(Handle2, WM_CHAR, ExpertName[i], 0);

        user32::SendMessageW(Handle2, WM_KEYDOWN, VK_RETURN, 0);
        user32::SendMessageW(Handle2, WM_KEYDOWN, VK_ESCAPE, 0);

        const string NewExpertName = MTTESTER::GetExpertName();

        Res = (NewExpertName == ExpertName);

        if (!Res && (NewExpertName != PrevExpertName))
          MTTESTER::SetExpertName(PrevExpertName);
      }
    }

    return(Res);
  }

  static bool CloseNotChart( void )
  {
    static const int ControlID[] = {0xE900};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    bool Res = false;

    for (long handle = user32::GetWindow(Handle, GW_CHILD); handle; handle = user32::GetWindow(handle, GW_HWNDNEXT))
      if (!MTTESTER::IsChart(handle))
      {
        user32::SendMessageW(handle, WM_CLOSE, 0, 0);
        Res = true;

        break;
      }

    return(Res);
  }

  static bool IsReady( const uint Pause = 100 )
  {
    if (MTTESTER::IsReady2())
      MTTESTER::Sleep2(Pause);

    return(MTTESTER::IsReady2());
  }

  static bool ClickStart( const bool Check = true, const int Attempts = 50 )
  {
//      static const int ControlID[] = {0xE81E, 0x804E, 0x2712, 0x4196}; // Start Button
    static const int ControlID[] = {0xE81E, 0x804E};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    bool Res = !Check || MTTESTER::IsReady2();

    if (Res)
    {
      if (Check)
      {
//        MTTESTER::StartTester();

//        user32::ShowWindow(user32::GetDlgItem(Handle, 0x28ED), 1); // Journal

        for (int i = 0; (i < Attempts)/* && !::IsStopped() */; i++) // Глобальному деструктору может понадобиться
        {
          // https://www.mql5.com/ru/forum/1111/page3471#comment_51964006
          for (int X = 300; (X <= 1000) && !MTTESTER::GetJournalItemCount(); X += 50)
            user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, X); // lparam - X

          ::Sleep(20);

          if (MTTESTER::GetJournalItemCount())
            break;
        }

        for (int i = 0; (i < Attempts)/* && !::IsStopped() */; i++) // Глобальному деструктору может понадобиться
        {
          // https://www.mql5.com/ru/forum/1111/page3471#comment_51964006
          for (int X = 300; (X <= 1000)/* && MTTESTER::GetJournalItemCount()*/; X += 50)
          {
            user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, X); // lparam - X
            user32::SendMessageW(MTTESTER::GetTerminalHandle(), WM_COMMAND, 0X8176, 0);
          }

          ::Sleep(30);

          if (!MTTESTER::GetJournalItemCount())
            break;
        }
      }

      const int PrevCount = Check ? MTTESTER::GetJournalItemCount() : 0;

//      user32::SendMessageW(Handle, BM_CLICK, 0, 0); // Start Button
      user32::SendMessageW(Handle, user32::RegisterWindowMessageW("MetaTrader5_Internal_Message"), 0X31, 0);

      if (Check)
        for (int i = 0; (i < Attempts) && !(Res = !MTTESTER::IsReady2()); i++) // Дать успеть после нажатия на Start переключиться на Stop.
          ::Sleep(1);

      if (!Res) // После нажатия на Start переключение на Stop осталось незамеченным.
      {
        ::Alert(__FILE__ + ": Start->Stop - is not detected!");

        for (int i = 0; (i < Attempts)/* && !::IsStopped() */; i++) // Глобальному деструктору может понадобиться
        {
          // https://www.mql5.com/ru/forum/1111/page3471#comment_51964006
          for (int X = 300; (X <= 1000)/* && (MTTESTER::GetJournalItemCount() == PrevCount)*/; X += 50)
            user32::SendMessageW(user32::GetDlgItem(Handle, 0x2712), WM_LBUTTONDOWN, 1, X); // lparam - X

          ::Sleep(100); // Меньшее значение может не дать успеть обновиться журналу.

          if (Res = (MTTESTER::GetJournalItemCount() - PrevCount > 1))
            break;
        }

        if (!Res || !(Res = (MTTESTER::GetJournalItemCount() - PrevCount > 1)))
          ::Alert(__FILE__ + ": problem with Start-button!");
      }

//      if (Check)
//        user32::ShowWindow(user32::GetDlgItem(Handle, 0x28ED), 0); // Journal
    }

    return(Res);
  }

  static bool ClickStop( const int Attempts = 50 )
  {
    if (MTTESTER::IsIdle())
      return(true);

    static const int ControlID[] = {0xE81E, 0x804E};
    const long Handle = MTTESTER::GetHandle(ControlID);

    if (!Handle)
      return(false);

    user32::SendMessageW(Handle, user32::RegisterWindowMessageW("MetaTrader5_Internal_Message"), 0X31, 0);

    bool Res = false;

    for (int i = 0; (i < Attempts) && !(Res = MTTESTER::IsIdle()); i++)
      ::Sleep(100);

    if (!Res)
      ::Print(__FILE__ + ": Stop->Start - is not detected!");

    return(Res);
  }

  static bool SetTimeFrame( ENUM_TIMEFRAMES period )
  {
    const bool Res = MTTESTER::IsReady();

    if (Res)
    {
      static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x28F7};
      static const long Handle = MTTESTER::GetHandle(ControlID);

      user32::SendMessageW(Handle, WM_KEYDOWN, VK_HOME, 0);

      static const ENUM_TIMEFRAMES Periods[] = {PERIOD_M1, PERIOD_M2, PERIOD_M3, PERIOD_M4, PERIOD_M5, PERIOD_M6, PERIOD_M10,
                                                PERIOD_M12, PERIOD_M15, PERIOD_M20, PERIOD_M30, PERIOD_H1, PERIOD_H2, PERIOD_H3,
                                                PERIOD_H4, PERIOD_H6, PERIOD_H8, PERIOD_H12, PERIOD_D1, PERIOD_W1, PERIOD_MN1};

      if (period == PERIOD_CURRENT)
        period = ::_Period;

      for (int i = 0; (i < sizeof(Periods) / sizeof(ENUM_TIMEFRAMES)) && (period != Periods[i]); i++)
        user32::SendMessageW(Handle, WM_KEYDOWN, VK_DOWN, 0);
    }

    return(Res);
  }

  static bool SetSymbol( const string SymbName = NULL )
  {
    const bool Res = (SymbName == NULL) || (::SymbolInfoInteger(SymbName, SYMBOL_VISIBLE) && MTTESTER::IsReady());
    const int Size = ::StringLen(SymbName);

    if (Res && Size && (SymbName != MTTESTER::GetSymbolName()))
    {
      static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x28F6, 0x2855};
      static const long Handle = MTTESTER::GetHandle(ControlID);

      user32::SendMessageW(Handle, WM_LBUTTONDOWN, 0, 0);
      user32::SendMessageW(Handle, WM_KEYDOWN, VK_DELETE, 0);

      for (int i = 0; i < Size; i++)
        user32::SendMessageW(Handle, WM_CHAR, SymbName[i], 0);

      user32::SendMessageW(Handle, WM_KEYDOWN, VK_RETURN, 0);
    }

    return(Res);
  }

  static bool SetBeginTime( const datetime time )
  {
    static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x2936};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    return(MTTESTER::SetTime(Handle, time));
  }

  static bool SetEndTime( const datetime time )
  {
    static const int ControlID[] = {0xE81E, 0x804E, 0x28EC, 0x2937};
    static const long Handle = MTTESTER::GetHandle(ControlID);

    return(MTTESTER::SetTime(Handle, time));
  }

  static bool Run( const string ExpertName = NULL,
                   const string Symb = NULL,
                   const ENUM_TIMEFRAMES period = PERIOD_CURRENT,
                   const datetime iBeginTime = 0,
                   const datetime iEndTime = 0 )
  {
    string Str = "[Tester]\n";

    Str += (ExpertName != NULL) ? "Expert=" + ExpertName + "\n" : NULL;
    Str += (Symb != NULL) ? "Symbol=" + Symb + "\n" : NULL;
    Str += iBeginTime ? "FromDate=" + ::TimeToString(iBeginTime, TIME_DATE) + "\n" : NULL;
    Str += iEndTime ? "ToDate=" + ::TimeToString(iEndTime, TIME_DATE) + "\n" : NULL;

    return(MTTESTER::SetSettings2(Str) &&
           MTTESTER::SetTimeFrame(period) && MTTESTER::ClickStart());

/*
    return(MTTESTER::SetExpertName(ExpertName) &&
           MTTESTER::SetSymbol(Symb) &&
           MTTESTER::SetBeginTime(iBeginTime) && MTTESTER::SetEndTime(iEndTime) &&
           MTTESTER::SetTimeFrame(period) && MTTESTER::ClickStart());
*/
  }
  static string GetValue( string Settings, const string Name )
  {
    const string Str = (Name == "") ? NULL : MTTESTER::StringBetween(Settings, Name + "=", "\n");
    const int Len = ::StringLen(Str);

    return((Len && (Str[Len - 1] == '\r')) ? ::StringSubstr(Str, 0, Len - 1) : Str);
  }

  static string SetValue( string &Settings, const string Name, const string Value = NULL )
  {
    const string PrevValue = MTTESTER::GetValue(Settings, Name);

    if (PrevValue == NULL)
      Settings += "\n" + Name + "=" + Value;
    else
      ::StringReplace(Settings, Name + "=" + PrevValue, (Value == NULL) ? NULL : Name + "=" + Value); // NULL - delete.

    return(Settings);
  }

  static int GetOptCacheFileNames( string &Path, string &FileNames[] )
  {
    Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\";

    ::ArrayFree(FileNames);
    return(MTTESTER::GetFileNames(Path, "*.opt", FileNames));
  }

  template <typename T>
  static int FileLoad( const string FileName, T &Buffer[] )
  {
    int Res = -1;
    const HANDLE handle = kernel32::CreateFileW(LONG_PATH_ATTR + FileName, GENERIC_READ, SHARE_READ, 0, OPEN_EXISTING, 0, 0);

    if (handle != INVALID_HANDLE)
    {
      long Size;
      kernel32::GetFileSizeEx(handle, Size);

      uint Read = 0;

      if ((::ArrayResize(Buffer, (int)Size / sizeof(T)) >= 0) &&
          kernel32::ReadFile(handle, Buffer, (uint)Size, Read, 0))
        Res = ::ArrayResize(Buffer, Read / sizeof(T));

      kernel32::CloseHandle(handle);
    }

    return(Res);
  }

  static bool FileIsExist( const string FileName )
  {
    const HANDLE handle = kernel32::CreateFileW(LONG_PATH_ATTR + FileName, GENERIC_READ, SHARE_READ, 0, OPEN_EXISTING, 0, 0);
    const bool Res = (handle != INVALID_HANDLE);

    if (Res)
      kernel32::CloseHandle(handle);

    return(Res);
  }

  static bool FileCopy( const string FileNameIn, const string FileNameOut, const bool Overwrite = false )
  {
    string Path = FileNameOut;
    string Directory = LONG_PATH_ATTR;

    // Можно гораздо экономнее находить пути подпапок.
    while (::StringFind(Path, "\\") > 0)
      kernel32::CreateDirectoryW(Directory += MTTESTER::StringBetween(Path, NULL, "\\") + "\\", 0);

    if (Overwrite)
      kernel32::DeleteFileW(LONG_PATH_ATTR + FileNameOut);

    return(kernel32::CopyFileW(LONG_PATH_ATTR + FileNameIn, LONG_PATH_ATTR + FileNameOut, !Overwrite));
  }

  static bool FileMove( const string FileNameIn, const string FileNameOut, const bool Overwrite = false )
  {
    string Path = FileNameOut;
    string Directory = LONG_PATH_ATTR;

    // Можно гораздо экономнее находить пути подпапок.
    while (::StringFind(Path, "\\") > 0)
      kernel32::CreateDirectoryW(Directory += MTTESTER::StringBetween(Path, NULL, "\\") + "\\", 0);

    if (Overwrite)
      kernel32::DeleteFileW(LONG_PATH_ATTR + FileNameOut);

    return((bool)kernel32::MoveFileW(LONG_PATH_ATTR + FileNameIn, LONG_PATH_ATTR + FileNameOut));
  }

  template <typename T>
  static int FileSave( const string FileName, const T &Buffer[] )
  {
    string Path = FileName;
    string Directory = LONG_PATH_ATTR;

    Print(_LastError);

    // Можно гораздо экономнее находить пути подпапок.
    while (::StringFind(Path, "\\") > 0)
    {
      kernel32::CreateDirectoryW(Directory += MTTESTER::StringBetween(Path, NULL, "\\") + "\\", 0);

      Print((string)_LastError + " - " + (string)__LINE__);
    }


    uint Read = 0;
    const HANDLE handle = kernel32::CreateFileW(LONG_PATH_ATTR + FileName, GENERIC_WRITE, SHARE_READ, 0, CREATE_ALWAYS, 0, 0);

      Print((string)_LastError + " - " + (string)__LINE__);

    if (handle != INVALID_HANDLE)
    {
      Print((string)_LastError + " - " + (string)__LINE__);
      kernel32::WriteFile(handle, Buffer, (uint)::ArraySize(Buffer) * sizeof(T), Read, 0);

      Print((string)_LastError + " - " + (string)__LINE__);
      kernel32::CloseHandle(handle);
    }

    return((int)Read / sizeof(T));
  }

  static string GetLastOptCacheFileName( void )
  {
    const string Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\";

    return(::StringSubstr(MTTESTER::GetFreshFileName(Path, "*.opt"), ::StringLen(Path)));
  }

  static string GetLastTstCacheFileName( void )
  {
    const string Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\";

    return(::StringSubstr(MTTESTER::GetFreshFileName(Path, "*.tst"), ::StringLen(Path)));
  }

  static bool DeleteLastINI( void )
  {
    const string Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\MQL5\\Profiles\\Tester\\";
    string FileNames[];

    const int Size = MTTESTER::GetFileNames(Path, "*.ini", FileNames);

    return(Size && kernel32::DeleteFileW(Path + FileNames[Size - 1]));
  }

  static bool DeleteLastTST( void )
  {
    const string Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\cache\\";
    string FileNames[];

    const int Size = MTTESTER::GetFileNames(Path, "*.tst", FileNames);

    return(Size && kernel32::DeleteFileW(Path + FileNames[Size - 1]));
  }

  static bool IsFolderON( const string Name, const bool Log = false )
  {
    const uint FileAttribute = kernel32::GetFileAttributesW(Name);

    const bool Res = (FileAttribute == INVALID_FILE_ATTRIBUTES) || (bool)(FileAttribute & FILE_ATTRIBUTE_DIRECTORY);

    if (Log)
      ::Print(Name + " - " + (Res ? "ON." : "OFF"));

    return(Res);
  }

  static bool FolderOFF( const string Name, const bool Log = false  )
  {
    MTTESTER::DeleteFolder(Name);

    const HANDLE handle = kernel32::CreateFileW(Name, GENERIC_WRITE, SHARE_READ, 0, CREATE_ALWAYS, 0, 0);

    if (handle != INVALID_HANDLE)
      kernel32::CloseHandle(handle);

    return(!MTTESTER::IsFolderON(Name, Log));
  }

  static bool FolderON( const string Name, const bool Log = false  )
  {
    kernel32::DeleteFileW(Name);

    return(!MTTESTER::IsFolderON(Name, Log));
  }

  // https://www.mql5.com/en/code/26945
  static string instance_id(const string strPath)
  {
    string strTest = strPath;
    ::StringToUpper(strTest);

    // Convert the string to widechar Unicode array (it will include a terminating 0)
    ushort arrShort[];
    const int n = ::StringToShortArray(strTest, arrShort); // n includes terminating 0, and should be dropped

    // Convert data to uchar array for hashing
    uchar widechars[];
    ::ArrayResize(widechars, (n - 1) * 2);
    for(int i = 0; i < n - 1; i++)
    {
      widechars[i * 2] = (uchar)(arrShort[i] & 0xFF);
      widechars[i * 2 + 1] = (uchar)((arrShort[i] >> 8) & 0xFF);
    }

    // Do an MD5 hash of the uchar array, containing the Unicode string
    uchar dummykey[1] = {0};
    uchar result[];
    if(::CryptEncode(CRYPT_HASH_MD5, widechars, dummykey, result) == 0)
    {
      ::Print("Error ", ::GetLastError());
      return NULL;
    }

    return arrayToHex(result);
  }

#define TERMINAL_UPDATE(A)                                                                                     \
  static const string Name = ::StringSubstr(::TerminalInfoString(TERMINAL_COMMONDATA_PATH), 0,                 \
                                            ::StringLen(::TerminalInfoString(TERMINAL_COMMONDATA_PATH)) - 6) + \
                             MTTESTER::instance_id(::TerminalInfoString(TERMINAL_PATH)) +                      \
                             (MTTESTER::IsPortable() ? NULL : "\\liveupdate");                                 \
                                                                                                               \
  return(MTTESTER::##A(Name, Log));

  static bool IsTerminalLiveUpdate( const bool Log = false )
  {
    TERMINAL_UPDATE(IsFolderON);
  }

  static bool TerminalLiveUpdateOFF( const bool Log = false )
  {
    TERMINAL_UPDATE(FolderOFF);
  }

  static bool TerminalLiveUpdateON( const bool Log = false )
  {
    TERMINAL_UPDATE(FolderON);
  }
#undef TERMINAL_UPDATE

#define TESTER_LOG(A)                                                                \
  static const string Path = ::TerminalInfoString(TERMINAL_DATA_PATH)+ "\\Tester\\"; \
                                                                                     \
  bool Res = MTTESTER::##A(Path + "logs", Log);                                      \
                                                                                     \
  string AgentNames[];                                                               \
                                                                                     \
  for (int i = MTTESTER::GetAgentNames(AgentNames) - 1; i >= 0; i--)                 \
    Res &= MTTESTER::##A(Path + AgentNames[i] + "\\logs", Log);

  static bool IsTesterLogON( const bool Log = false )
  {
    TESTER_LOG(IsFolderON)

    return(Res);
  }

  static bool TesterLogOFF( const bool Log = false )
  {
    TESTER_LOG(FolderOFF)

    return(!MTTESTER::IsTesterLogON());
  }

  static bool TesterLogON( const bool Log = false )
  {
    TESTER_LOG(FolderON)

    return(MTTESTER::IsTesterLogON());
  }
#undef TESTER_LOG

  static bool Lock( const bool Flag = true )
  {
    static int handle = INVALID_HANDLE;

    if (handle != INVALID_HANDLE)
    {
      ::FileClose(handle);

      handle = INVALID_HANDLE;
    }

    return(Flag && ((handle = ::FileOpen(__FILE__, FILE_WRITE | FILE_COMMON)) != INVALID_HANDLE));
  }

  static bool LockWaiting( const int Attempts = 10 )
  {
    bool Res = MTTESTER::Lock();

    for (int i = 0; (i < Attempts) && !Res && !::IsStopped(); i++)
    {
      ::Sleep(500);

      Res = MTTESTER::Lock();
    }

    return(Res);
  }

  static int GetTerminalHandles( HANDLE &Handles[], const bool SortPath = false )
  {
    ::ArrayFree(Handles);

    for (HANDLE Handle = user32::GetTopWindow(NULL); Handle; Handle = user32::GetWindow(Handle, GW_HWNDNEXT))
      if (MTTESTER::GetClassName(Handle) == "MetaQuotes::MetaTrader::5.00")
        Handles[::ArrayResize(Handles, ::ArraySize(Handles) + 1) - 1] = Handle;

    if (SortPath)
      MTTESTER::SortByPath(Handles);

    return(::ArraySize(Handles));
  }

  static bool IsPortable( const HANDLE TerminalHandle )
  {
    const string Path = MTTESTER::GetTerminalDataPathWrong(TerminalHandle);

//    return(!MTTESTER::FileIsExist(Path + "\\origin.txt") || MTTESTER::FileIsExist(Path + "\\portable.txt"));

    ushort Words[];

    return((MTTESTER::FileLoad(Path + "\\origin.txt", Words) == -1) ||
           ((MTTESTER::FileIsExist(Path + "\\portable.txt") &&
            (::ShortArrayToString(Words, 1) == MTTESTER::GetTerminalPath(TerminalHandle)))));
  }

  static bool IsPortable( void )
  {
    return(MTTESTER::IsPortable(MTTESTER::GetTerminalHandle()));
  }

  static string GetTerminalPath( const HANDLE TerminalHandle )
  {
    if (TerminalHandle == MTTESTER::GetTerminalHandle())
      return(::TerminalInfoString(TERMINAL_PATH));

    string Path = MTTESTER::GetPathExe(TerminalHandle);

    return(::StringSubstr(Path, 0, MTTESTER::GetLastPos(Path, '\\')));
  }

  static string GetTerminalDataPath( const HANDLE TerminalHandle )
  {
    if (TerminalHandle == MTTESTER::GetTerminalHandle())
      return(::TerminalInfoString(TERMINAL_DATA_PATH));

    return((TerminalHandle == MTTESTER::GetTerminalHandle()) ? ::TerminalInfoString(TERMINAL_DATA_PATH) :
             (MTTESTER::IsPortable(TerminalHandle) ? MTTESTER::GetTerminalPath(TerminalHandle)
                                                   : MTTESTER::GetTerminalDataPathWrong(TerminalHandle)));
  }

#define FORCE_PATH "Scripts\\" + __FILE__ + "\\"

  static bool RunEX5( string FileName, HANDLE TerminalHandle = 0, const bool Force = false, const char ChartNumber = 0 )
  {
    bool Res = false;

    if (!TerminalHandle)
      TerminalHandle = MTTESTER::GetTerminalHandle();

    const HANDLE MyChartHandle = ::ChartGetInteger(0, CHART_WINDOW_HANDLE);
    HANDLE ChartHandle = MTTESTER::GetChartHandle(TerminalHandle, ChartNumber);

    if ((ChartHandle && (ChartHandle != MyChartHandle)) ||
        (Force && (bool)(ChartHandle = (ChartHandle || ChartNumber) ? MTTESTER::GetChartHandle(TerminalHandle, (uchar)(!ChartNumber)) : 0)))
    {
      if (Force &&
       #ifndef RUNEX5_SILENT
         (TerminalHandle != MTTESTER::GetTerminalHandle()) &&
       #endif // #ifndef RUNEX5_SILENT
         (MTTESTER::FileCopy(MTTESTER::GetTerminalDataPath(MTTESTER::GetTerminalHandle()) + "\\MQL5\\" + FileName,
                             MTTESTER::GetTerminalDataPath(TerminalHandle) + "\\MQL5\\" + FORCE_PATH + FileName, true)))
        FileName = FORCE_PATH + FileName;

      const int NumberEX5 = MTTESTER::GetNumberEX5(TerminalHandle, FileName);

      Res = (NumberEX5 >= 0) && !user32::SendMessageW(ChartHandle, user32::RegisterWindowMessageW("MetaTrader5_Internal_Message"), 0x1D, NumberEX5);
    }

    return(Res);
  }

  static bool IsForceScript( void )
  {
    return(::StringFind(::MQLInfoString(MQL_PROGRAM_PATH), "\\MQL5\\" + FORCE_PATH) > 0);
  }

#ifdef RUNEX5_SILENT
  static bool RunEX5_Silent( string FileName, HANDLE TerminalHandle = 0, const bool Force = false, const char ChartNumber = 0 )
  {
    ushort Words[];

    return((!Force || MTTESTER::FileCopy(MTTESTER::GetTerminalDataPath(MTTESTER::GetTerminalHandle()) + "\\MQL5\\" + FileName,
                                         MTTESTER::GetTerminalDataPath(TerminalHandle) + "\\MQL5\\" + FORCE_PATH + FileName, true)) &&
           (MTTESTER::FileSave(MTTESTER::GetTerminalDataPath(TerminalHandle) + "\\MQL5\\" + FORCE_PATH + "RunMe.ex5", RunMe) > 0) &&
           (::StringToShortArray((Force ? FORCE_PATH : NULL) + FileName, Words) > 0) &&
           (MTTESTER::FileSave(MTTESTER::GetTerminalDataPath(TerminalHandle) + "\\MQL5\\Files\\RunMe.txt", Words) > 0) &&
           MTTESTER::RunEX5(FORCE_PATH + "RunMe.ex5", TerminalHandle, false, ChartNumber));
  }
#endif // #ifdef RUNEX5_SILENT

#undef FORCE_PATH

  static void SetServerPoint( const int Num = 0 )
  {
    user32::SendMessageW(MTTESTER::GetTerminalHandle(), WM_COMMAND, 53171 + Num, 0);

    return;
  }

  static bool CheckInputs( const bool IncludeFileName = false )
  {
    string Settings;
    bool Res = MTTESTER::GetSettings(Settings);

    if (Res)
    {
      const string FileName = "Experts\\" + MTTESTER::StringBetween(Settings, "Expert=", "ex5") + "mq5";

      if (Res = MTTESTER::FileIsExist(::TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\" + FileName))
      {
        const string Str = MTTESTER::GetInputsString();

        if (Res = (Str != NULL))
        {
          const string Source = ::ShortToString(0xFEFF) +
            "// Generated by " + __FUNCSIG__ + ": https://www.mql5.com/ru/code/26132" + "\n"
            "// Time = " + (string)::TimeLocal() + ", Link: https://www.mql5.com/ru/blogs/post/760770" + "\n"
            "// For " + FileName + "\n"
            "" + "\n"
            "#define TOSTRING(A) #A + \"=\" + (string)A + \"\\n\"" + "\n"
            "" + "\n"
            "class CHECK_INPUTS" + "\n"
            "{" + "\n"
            "private:" + "\n"
            "  static string arrayToHex(uchar &arr[])" + "\n"
            "  {" + "\n"
            "    string res = \"\";" + "\n"
            "    for(int i = 0; i < ::ArraySize(arr); i++)" + "\n"
            "    {" + "\n"
            "      res += ::StringFormat(\"%.2X\", arr[i]);" + "\n"
            "    }" + "\n"
            "    return(res);" + "\n"
            "  }" + "\n"
            "" + "\n"
            "  // https://www.mql5.com/en/code/26945" + "\n"
            "  static string instance_id(const string strPath)" + "\n"
            "  {" + "\n"
            "    string strTest = strPath;" + "\n"
            "    ::StringToUpper(strTest);" + "\n"
            "" + "\n"
            "    // Convert the string to widechar Unicode array (it will include a terminating 0)" + "\n"
            "    ushort arrShort[];" + "\n"
            "    const int n = ::StringToShortArray(strTest, arrShort); // n includes terminating 0, and should be dropped" + "\n"
            "" + "\n"
            "    // Convert data to uchar array for hashing" + "\n"
            "    uchar widechars[];" + "\n"
            "    ::ArrayResize(widechars, (n - 1) * 2);" + "\n"
            "    for(int i = 0; i < n - 1; i++)" + "\n"
            "    {" + "\n"
            "      widechars[i * 2] = (uchar)(arrShort[i] & 0xFF);" + "\n"
            "      widechars[i * 2 + 1] = (uchar)((arrShort[i] >> 8) & 0xFF);" + "\n"
            "    }" + "\n"
            "" + "\n"
            "    // Do an MD5 hash of the uchar array, containing the Unicode string" + "\n"
            "    uchar dummykey[1] = {0};" + "\n"
            "    uchar result[];" + "\n"
            "    if(::CryptEncode(CRYPT_HASH_MD5, widechars, dummykey, result) == 0)" + "\n"
            "    {" + "\n"
            "      ::Print(\"Error \", ::GetLastError());" + "\n"
            "      return NULL;" + "\n"
            "    }" + "\n"
            "" + "\n"
            "    return arrayToHex(result);" + "\n"
            "  }" + "\n"
            "" + "\n"
            "  static int GetLastPos( const string Str, const short Char )" + "\n"
            "  {" + "\n"
            "    int Pos = ::StringLen(Str) - 1;" + "\n"
            "" + "\n"
            "    while ((Pos >= 0) && (Str[Pos] != Char))" + "\n"
            "      Pos--;" + "\n"
            "" + "\n"
            "    return(Pos);" + "\n"
            "  }" + "\n"
            "" + "\n"
            "  // https://www.mql5.com/ru/forum/170952/page293#comment_55996971" + "\n"
            "  static string TimeframeToString( const ENUM_TIMEFRAMES tf )" + "\n"
            "  {" + "\n"
            "    const string ids[] = {\"M\", \"H\", \"W\", \"MN\"};" + "\n"
            "" + "\n"
            "    return(ids[tf >> 14] + (string)(tf & 0x3FFF));" + "\n"
            "  }" + "\n"
            "" + "\n"
            "  static string AddInfo( void )" + "\n"
            "  {" + "\n"
            "    return(\"// Generated by bool MTTESTER::CheckInputs(const bool): https://www.mql5.com/ru/code/26132\\n\" +" + "\n"
            "           \"// Link: https://www.mql5.com/ru/blogs/post/760770\\n\\n\" +" + "\n"
            "           \"// [Tester]\\n\" +" + "\n"
            "           \"// Expert=\" + StringSubstr(::MQLInfoString(MQL_PROGRAM_PATH)," + "\n"
            "                                       ::StringLen(::TerminalInfoString(TERMINAL_DATA_PATH) +" + "\n"
            "                                                   \"\\\\MQL5\\\\Experts\\\\\")) + \"\\n\" +" + "\n"
            "           \"// Symbol=\" + _Symbol + \"\\n\" +" + "\n"
            "           \"// Period=\" + CHECK_INPUTS::TimeframeToString(_Period) + \"\\n\" +" + "\n"
            "           \"// FromDate=\" + ::TimeToString(::TimeCurrent(), TIME_DATE) + \"\\n\" +" + "\n"
            "           \"// Deposit=\" + (string)::AccountInfoDouble(ACCOUNT_BALANCE) + \"\\n\" +" + "\n"
            "           \"// Currency=\" + ::AccountInfoString(ACCOUNT_CURRENCY) + \"\\n\" +" + "\n"
            "           \"// Leverage=\" + (string)::AccountInfoInteger(ACCOUNT_LEVERAGE) + \"\\n\" +" + "\n"
            "           \"// ServerName=\" + ::AccountInfoString(ACCOUNT_SERVER) + \"\\n\" +" + "\n"
            "           \"// [TesterInputs]\\n\\n\");" + "\n"
            "  }" + "\n"
            "" + "\n"
            "  static string GetDate( const datetime Time )" + "\n"
            "  {" + "\n"
            "    string Str = ::TimeToString(Time, TIME_DATE);" + "\n"
            "" + "\n"
            "    ::StringReplace(Str, \".\", NULL);" + "\n"
            "" + "\n"
            "    return(Str);" + "\n"
            "  }" + "\n"
            "" + "\n"
            "public:" + "\n"
            "  const string Inputs;" + "\n"
            "  const string FileName;" + "\n"
            "  " + "\n"
            "  CHECK_INPUTS() : Inputs(::ShortToString(0xFEFF) + CHECK_INPUTS::AddInfo()" + Str + ")," + "\n"
            "                   FileName(\"CheckInputs\\\\\" + ::MQLInfoString(MQL_PROGRAM_NAME) +" + "\n"
            "                            ::StringSubstr(::TerminalInfoString(TERMINAL_DATA_PATH)," + "\n"
            "                                           CHECK_INPUTS::GetLastPos(::TerminalInfoString(TERMINAL_DATA_PATH), '\\\\')) +" + "\n"
            "                            \"_\" + _Symbol +" + "\n"
            "                            \".\" + CHECK_INPUTS::TimeframeToString(_Period) +" + "\n"
            "                            \".\" + CHECK_INPUTS::GetDate(::TimeCurrent()) +" + "\n"
            "                            \".\" + ::AccountInfoString(ACCOUNT_SERVER) +" + "\n"
            "                            \"_\" + CHECK_INPUTS::instance_id(Inputs) + \".txt\")" + "\n"
            "  {" + "\n"
            "    ushort Array[];" + "\n"
            "    " + "\n"
            "    ::StringToShortArray(this.Inputs, Array);" + "\n"
            "    ::FileSave(this.FileName, Array, FILE_COMMON);" + "\n"
            "  }" + "\n"
            "  " + "\n"
            "  ~CHECK_INPUTS() { ::FileDelete(this.FileName, FILE_COMMON); }" + "\n"
            "  " + "\n"
            "} _CheckInputs;" + "\n"
            "" + "\n"
            "#undef TOSTRING";

          const int Pos = MTTESTER::GetLastPos(FileName, '\\') + 1;
          const string FileNameOut = ::StringSubstr(FileName, 0, Pos) +
                                     (IncludeFileName ? ::StringSubstr(FileName, Pos, ::StringLen(FileName) - Pos - 4) + "_"
                                                      : NULL) + "CheckInputs.mqh";
          ushort Array[];

          if (Res = ::StringToShortArray(Source, Array) && MTTESTER::FileSave(::TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\" + FileNameOut, Array))
            ::Print(__FUNCSIG__ + ": " + FileNameOut + " is generated."
                    "\nAdd the following line to " + FileName +
                    "\n#include \"" + ::StringSubstr(FileNameOut, Pos) + "\" // https://www.mql5.com/ru/blogs/post/760770");
        }
      }
      else
        ::Print(__FUNCSIG__ + ": " + FileName + " is not found.");
    }

    return(Res);
  }

  // Возвращает список всех файлов по фильтру
  static int GetFileNames( string &FileNames[], string Filter = "*" )
  {
    const string Directory = MTTESTER::GetDirectory(Filter);
    Filter = ::StringSubstr(Filter, ::StringLen(Directory));

    string Directories[];

    const int Size = ::ArrayResize(Directories, MTTESTER::GetFileNames(Directory, "*", Directories, true, true) + 1);
    Directories[Size - 1] = Directory;

    for (int Pos = 0, i = 0; i < Size; i++)
    {
      const int Total = MTTESTER::GetFileNames(Directories[i], Filter, FileNames);

      while (Pos < Total)
      {
        FileNames[Pos] = Directories[i] + FileNames[Pos];

        Pos++;
      }
    }

    return(::ArraySize(FileNames));
  }

  static bool TerminalJournalClear( void )
  {
    return(!::IsStopped() && user32::SendMessageW(MTTESTER::GetTerminalHandle(), WM_COMMAND, 0X8135, 0));
  }
};

#undef LONG_PATH_ATTR
