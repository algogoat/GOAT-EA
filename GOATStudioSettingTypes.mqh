#ifndef GOAT_STUDIO_SETTING_TYPES_MQH
#define GOAT_STUDIO_SETTING_TYPES_MQH
// Explicit V1.49 source-schema allowlist. Unknown inputs fail closed.
string GoatStudioSettingType(const string key)
  {
   if(StringFind("|Mode_Operation|Signal_Sample_Period|Sequence_Sample_Period|Trailing_Sample_Period|Mode_Trade|Mode_RRR|Mode_Trail|Delay_Trade|Delay_Trade_Live|Max_Seq_Trades|ATR_TF_|ATR_Period|ATR_Method|Mode_Lots|Mode_Lots_Prog|Mode_Restart|RSI_Mode|RSI_TF_|RSI_Period|RSI_Price|EMA_Mode|EMA_TF_|EMA_Method|EMA_Price|EMA_Count|EMA_Period|ADX_Mode|ADX_TF_|ADX_Period|BB_Mode|BB_TF_|BB_Period|MACD_Mode|MACD_Mode_Trend|MACD_TF_|MACD_Fast|MACD_Slow|MACD_Signal|MACD_Price|RSI2_Mode|RSI2_TF_|RSI2_Period|RSI2_Price|Active_Time_Weekday|Active_Time_Friday|Action_Dayend|Action_Friday|Bias_Protocol|Mode_Bias|Mode_Bias_Trades|Mode_Bias_Exit|Bias_Exit_Max_Exposure_Adds|Bias_threshold|Mode_News|News_threshold|News_beforeMinutes|News_afterMinutes|Mode_Download|Mode_Opti|Seq_min_inp|Trades_min_inp|Trades_Max|Minutes_Max|","|"+key+"|")>=0) return "int";
   if(StringFind("|EA_Desc|Active_Time_ASIA|Active_Time_EU|Active_Time_US|","|"+key+"|")>=0) return "string";
   if(StringFind("|Allow_New_Sequence|Allow_Opposite_Seq|Reverse_Seq|Delay_Lots_Add|CloseAtMaxLevels|Sequence_MLPS_Hard_Close|EMA_MustCheck|ADX_MustCheck|BB_MustCheck|MACD_MustCheck|RSI2_MustCheck|Trade_Friday|Trade_December|","|"+key+"|")>=0) return "bool";
   if(StringFind("|Grid_Size|Grid_Min|Grid_Max|Grid_Exponent|Grid_Factor|Lock_Profit_Size|Lock_Profit_Flexibility|TP_Pips|SL_Pips|RRR|TSL_Size|Risk|Lots_Input|Lots_Max|Lots_Max_Cum|Lots_Exponent|Lots_Factor|Peak_Lots_Pos_PC|Partial_Profit_Factor|Peak_Smart_Release_PC|Peak_Smart_Max_Close_PC|MaxLossLocal|MaxLossGlobal|MaxDailyLossLocal|MaxDailyProfitLocal|MinLevelEquity|MaxLevelEquity|RSI_Level|EMA_Exponent|ADX_Level|BB_Deviation|MACD_Deviations|RSI2_Level|","|"+key+"|")>=0) return "double";
   if(StringFind("|Download_StartDate|","|"+key+"|")>=0) return "datetime";
   if(key=="Dashboard_Resume_Saved" || key=="Studio_ReadOnlyMonitor") return "bool";
   if(key=="Studio_MonitorRunPath") return "string";
   if(key=="Ledger_Mode") return "int"; // B49a (F2): the appended ENUM_LEDGER_MODE sinput (never an optimization axis)
   // B50:begin b50-types
   // B50 (A0): the inputs appended after Ledger_Mode. The enum inputs are int; Engine_Mode, Clock_Mode, Server_Clock_Model
   // and Server_UTC_Offset are sinputs and NY_Session is a string, so none of those is ever an optimization axis.
   if(StringFind("|Engine_Mode|Single_Time_Stop_Bars|Single_Time_Stop_TF|Clock_Mode|Server_Clock_Model|Server_UTC_Offset|Rollover_Block_Minutes|","|"+key+"|")>=0) return "int";
   if(StringFind("|Single_SL_ATR|Single_TP_ATR|Single_TP_R|","|"+key+"|")>=0) return "double";
   if(key=="Single_Exit_Opposite") return "bool";
   if(key=="NY_Session") return "string";
   // B50:end b50-types
   if(key=="Fix_MoneyVolume") return "int"; // B49b (F7): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Gate_Recheck") return "int"; // B49b (F5): an appended ENUM_GATE_RECHECK sinput (never an optimization axis)
   if(key=="Fix_ClosePath") return "int"; // B49b (F3): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Max_Spread_Points") return "int"; // B49b (F6): an appended int sinput (never an optimization axis)
   if(key=="Min_Margin_Level_PC") return "double"; // B49b (F6): an appended double sinput (never an optimization axis)
   if(key=="Fix_Clock") return "int"; // B49b (F4/R2): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Fix_FeedGuard") return "int"; // B49b (LAG-A): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Diag_TickTiming") return "int"; // B49b (LAG-T): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Fix_TickLoad") return "int"; // B49b (LAG-B): an appended ENUM_GOAT_FIX sinput (never an optimization axis)
   if(key=="Random_Direction") return "bool"; // B51 (beta-1a): the benchmark switch, an sinput (never an optimization axis)
   if(key=="Single_Flat_Only") return "bool"; // B51 (beta-1a): the flat-only eligibility, an sinput (never an optimization axis)
   if(key=="Random_Seed") return "int";       // B51 (beta-1a): the benchmark seed, an optimization axis (a seed sweep)
   if(StringFind("|Single_BE_ATR|Single_Trail_Start_ATR|Single_Trail_ATR|","|"+key+"|")>=0) return "double"; // B51 (beta-1b): break-even and trailing of a single
   if(StringFind("|Single_Partial_ATR|Single_Partial_Fraction|","|"+key+"|")>=0) return "double"; // B51 (section 8.3): the partial close of a single
   if(key=="Single_Partial_BE") return "bool"; // B51 (section 8.3)
   // B54:begin b54-types
   // B54 (A0, docs/b54/BREAKOUT_ENTRIES_SPEC.md section 7): the breakout inputs. The enum inputs are int; BRK_Mode, ORB_Mode
   // and ORB_Clock are sinputs, so none of those three is ever an optimization axis.
   if(StringFind("|BRK_Mode|BRK_TF_|BRK_Bars|ORB_Mode|ORB_Clock|ORB_TF_|ORB_Start_Minute|ORB_Range_Minutes|ORB_Entry_Minutes|","|"+key+"|")>=0) return "int";
   if(StringFind("|BRK_Buffer_ATR|ORB_Buffer_ATR|ORB_Min_Range_ATR|ORB_Max_Range_ATR|","|"+key+"|")>=0) return "double";
   if(key=="BRK_Once_Per_Level") return "bool";
   // B54:end b54-types
   if(key=="BRK_Start_Seq") return "bool"; // B55 (A0, docs/b55/BREAKOUT_SEQUENCE_SPEC.md section 7): the sequence switch, an sinput (never an optimization axis)
   return "";
  }
string GoatStudioOptimizationNames()
  {
   // B50:begin b50-axes
   return "|Trailing_Sample_Period|Allow_Opposite_Seq|Reverse_Seq|Mode_Trade|Grid_Size|Grid_Min|Grid_Max|Grid_Exponent|Grid_Factor|Lock_Profit_Size|Lock_Profit_Flexibility|TP_Pips|SL_Pips|RRR|Mode_RRR|TSL_Size|Mode_Trail|Delay_Trade|Delay_Trade_Live|Delay_Lots_Add|Max_Seq_Trades|CloseAtMaxLevels|ATR_TF_|ATR_Period|ATR_Method|Lots_Input|Lots_Max|Lots_Max_Cum|Lots_Exponent|Lots_Factor|Mode_Lots_Prog|Peak_Lots_Pos_PC|Partial_Profit_Factor|Peak_Smart_Release_PC|Peak_Smart_Max_Close_PC|MaxDailyLossLocal|MaxDailyProfitLocal|RSI_Mode|RSI_TF_|RSI_Period|RSI_Price|RSI_Level|EMA_Mode|EMA_TF_|EMA_Method|EMA_Price|EMA_Count|EMA_Period|EMA_Exponent|EMA_MustCheck|ADX_Mode|ADX_TF_|ADX_Period|ADX_Level|ADX_MustCheck|BB_Mode|BB_TF_|BB_Period|BB_Deviation|BB_MustCheck|MACD_Mode|MACD_Mode_Trend|MACD_TF_|MACD_Fast|MACD_Slow|MACD_Signal|MACD_Deviations|MACD_Price|MACD_MustCheck|RSI2_Mode|RSI2_TF_|RSI2_Period|RSI2_Price|RSI2_Level|RSI2_MustCheck|Active_Time_Weekday|Active_Time_Friday|Action_Dayend|Action_Friday|Trade_Friday|Bias_Protocol|Mode_Bias|Mode_Bias_Trades|Mode_Bias_Exit|Bias_Exit_Max_Exposure_Adds|Bias_threshold|Mode_News|News_threshold|News_beforeMinutes|News_afterMinutes|"
          +"Single_SL_ATR|Single_TP_ATR|Single_TP_R|Single_Exit_Opposite|Single_Time_Stop_Bars|Single_Time_Stop_TF|Rollover_Block_Minutes|" // B50 (A0): the B50 optimization axes (NY_Session is a string, never one); B51 continues the list
          +"Random_Seed|Single_BE_ATR|Single_Trail_Start_ATR|Single_Trail_ATR|Single_Partial_ATR|Single_Partial_Fraction|Single_Partial_BE|" // B51 (beta-1a, beta-1b, section 8.3): the B50-beta optimization axes (Random_Direction is an sinput, never one); B54 continues the list
          +"BRK_TF_|BRK_Bars|BRK_Buffer_ATR|BRK_Once_Per_Level|ORB_TF_|ORB_Start_Minute|ORB_Range_Minutes|ORB_Entry_Minutes|ORB_Buffer_ATR|ORB_Min_Range_ATR|ORB_Max_Range_ATR|"; // B54 (A0, spec section 7): the breakout axes (BRK_Mode, ORB_Mode and ORB_Clock are sinputs, never one)
   // B50:end b50-axes
  }
bool GoatStudioSettingOptimizable(const string key)
  {
   return StringFind(GoatStudioOptimizationNames(),"|"+key+"|")>=0;
  }
// B50:begin b50-defaults
// B50 (A0, GOAT-EA#269 P1): the default of an input appended after Ledger_Mode, as a SET spells it, or "" for any other
// input. A SET written before B50 omits these inputs and runs them at these defaults (the grid engine, the server
// clock), which reproduce B49a: the native config writes the axes among them explicitly (GoatStudioExplicitOptimizationInputs),
// OnTesterInit verifies them (GoatStudioVerifyOptimizationInputs) and the Studio readback accepts them (GoatStudioFixedInternal).
string GoatStudioAppendedDefault(const string key)
  {
   if(StringFind("|Engine_Mode|Single_Time_Stop_Bars|Single_Time_Stop_TF|Clock_Mode|Server_Clock_Model|Rollover_Block_Minutes|","|"+key+"|")>=0) return "0";
   if(StringFind("|Single_SL_ATR|Single_TP_ATR|Single_TP_R|","|"+key+"|")>=0) return "0.0";
   if(key=="Single_Exit_Opposite") return "false";
   if(key=="Server_UTC_Offset") return "2";
   if(key=="NY_Session") return "09:30-16:00";
   if(key=="Random_Direction") return "false"; // B51 (beta-1a): the B50-beta inputs; their defaults reproduce B50-alpha
   if(key=="Random_Seed") return "1";          // B51 (beta-1a)
   if(key=="Single_Flat_Only") return "false"; // B51 (beta-1a)
   if(StringFind("|Single_BE_ATR|Single_Trail_Start_ATR|Single_Trail_ATR|","|"+key+"|")>=0) return "0.0"; // B51 (beta-1b)
   if(StringFind("|Single_Partial_ATR|Single_Partial_Fraction|","|"+key+"|")>=0) return "0.0"; // B51 (section 8.3)
   if(key=="Single_Partial_BE") return "false"; // B51 (section 8.3)
   // B54:begin b54-defaults
   // B54 (A0, spec sections 3.1 and 4.1): the breakout inputs; their defaults (both families Disabled) reproduce B53.
   if(StringFind("|BRK_Mode|ORB_Mode|ORB_Clock|ORB_Entry_Minutes|","|"+key+"|")>=0) return "0";
   if(StringFind("|BRK_Buffer_ATR|ORB_Buffer_ATR|ORB_Min_Range_ATR|ORB_Max_Range_ATR|","|"+key+"|")>=0) return "0.0";
   if(key=="BRK_TF_") return "60";            // TF_H1
   if(key=="BRK_Bars") return "20";
   if(key=="BRK_Once_Per_Level") return "true";
   if(key=="ORB_TF_") return "5";             // TF_M5
   if(key=="ORB_Start_Minute") return "570";  // 09:30, in minutes from midnight of the clock anchor
   if(key=="ORB_Range_Minutes") return "30";
   // B54:end b54-defaults
   if(key=="BRK_Start_Seq") return "false"; // B55 (A0, spec section 3.1): the sequence switch; its default reproduces B54
   return "";
  }
// B50:end b50-defaults
#endif
