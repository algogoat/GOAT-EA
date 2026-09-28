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
   return "";
  }
bool GoatStudioSettingOptimizable(const string key)
  {
   return StringFind("|Trailing_Sample_Period|Allow_Opposite_Seq|Reverse_Seq|Mode_Trade|Grid_Size|Grid_Min|Grid_Max|Grid_Exponent|Grid_Factor|Lock_Profit_Size|Lock_Profit_Flexibility|TP_Pips|SL_Pips|RRR|Mode_RRR|TSL_Size|Mode_Trail|Delay_Trade|Delay_Trade_Live|Delay_Lots_Add|Max_Seq_Trades|CloseAtMaxLevels|ATR_TF_|ATR_Period|ATR_Method|Lots_Input|Lots_Max|Lots_Max_Cum|Lots_Exponent|Lots_Factor|Mode_Lots_Prog|Peak_Lots_Pos_PC|Partial_Profit_Factor|Peak_Smart_Release_PC|Peak_Smart_Max_Close_PC|MaxDailyLossLocal|MaxDailyProfitLocal|RSI_Mode|RSI_TF_|RSI_Period|RSI_Price|RSI_Level|EMA_Mode|EMA_TF_|EMA_Method|EMA_Price|EMA_Count|EMA_Period|EMA_Exponent|EMA_MustCheck|ADX_Mode|ADX_TF_|ADX_Period|ADX_Level|ADX_MustCheck|BB_Mode|BB_TF_|BB_Period|BB_Deviation|BB_MustCheck|MACD_Mode|MACD_Mode_Trend|MACD_TF_|MACD_Fast|MACD_Slow|MACD_Signal|MACD_Deviations|MACD_Price|MACD_MustCheck|RSI2_Mode|RSI2_TF_|RSI2_Period|RSI2_Price|RSI2_Level|RSI2_MustCheck|Active_Time_Weekday|Active_Time_Friday|Action_Dayend|Action_Friday|Trade_Friday|Bias_Protocol|Mode_Bias|Mode_Bias_Trades|Mode_Bias_Exit|Bias_Exit_Max_Exposure_Adds|Bias_threshold|Mode_News|News_threshold|News_beforeMinutes|News_afterMinutes|","|"+key+"|")>=0;
  }
#endif
