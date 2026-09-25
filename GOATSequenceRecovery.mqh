// Durable per-chart sequence checkpoints. No credentials and no entry authorization are persisted.
// File scope is this terminal, account/server, symbol and chart. Inputs are bound separately.
string g_GOATRecoveryPath="",g_GOATRecoverySettings="",g_GOATRecoveryLast="";
bool g_GOATRecoveryWriteFailed=false;

string GOATEncodeSequence(SEQUENCE &seq)
  {
   string value="S1";
   value+=";"+IntegerToString((long)seq.Active);
   value+=";"+IntegerToString((long)seq.Traded);
   value+=";"+IntegerToString((long)seq.Trailing);
   value+=";"+IntegerToString((long)seq.Virtual);
   value+=";"+IntegerToString((long)seq.Retrace_Triggered);
   value+=";"+IntegerToString((long)seq.GuardRealStarted);
   value+=";"+IntegerToString((long)seq.BiasRescueActive);
   value+=";"+IntegerToString((long)seq.BiasRescueBEProtected);
   value+=";"+IntegerToString((long)seq.dir);
   value+=";"+IntegerToString((long)seq.Level_Count);
   value+=";"+IntegerToString((long)seq.Trades_Count);
   value+=";"+IntegerToString((long)seq.BiasRescuePositiveAdds);
   value+=";"+DoubleToString(seq.Level_Last,16);
   value+=";"+DoubleToString(seq.Level_Retrace,16);
   value+=";"+DoubleToString(seq.Level_Lock,16);
   value+=";"+DoubleToString(seq.Level_TP,16);
   value+=";"+DoubleToString(seq.Level_SL,16);
   value+=";"+DoubleToString(seq.Level_TSL,16);
   value+=";"+DoubleToString(seq.Level_Entry,16);
   value+=";"+DoubleToString(seq.LotsTotal,16);
   value+=";"+DoubleToString(seq.Size_Grid,16);
   value+=";"+DoubleToString(seq.Size_Lock,16);
   value+=";"+DoubleToString(seq.Size_TP,16);
   value+=";"+DoubleToString(seq.Size_SL,16);
   value+=";"+DoubleToString(seq.Size_TSL,16);
   value+=";"+DoubleToString(seq.StartLots,16);
   value+=";"+DoubleToString(seq.PeakLots,16);
   value+=";"+DoubleToString(seq.PeakCumLots,16);
   value+=";"+DoubleToString(seq.ScaleFactor,16);
   value+=";"+DoubleToString(seq.SequenceRealizedPL,16);
   value+=";"+DoubleToString(seq.BiasRescueBEPrice,16);
   value+=";"+DoubleToString(seq.BiasRescueSLPrice,16);
   value+=";"+IntegerToString(ArraySize(seq.LotsRaw));
   for(int i=0;i<ArraySize(seq.LotsRaw);i++) value+=";"+DoubleToString(seq.LotsRaw[i],16);
   value+=";"+IntegerToString(ArraySize(seq.LotsNorm));
   for(int i=0;i<ArraySize(seq.LotsNorm);i++) value+=";"+DoubleToString(seq.LotsNorm[i],16);
   value+=";"+IntegerToString(ArraySize(seq.LotsCum));
   for(int i=0;i<ArraySize(seq.LotsCum);i++) value+=";"+DoubleToString(seq.LotsCum[i],16);
   value+=";"+IntegerToString(ArraySize(seq.Distances));
   for(int i=0;i<ArraySize(seq.Distances);i++) value+=";"+DoubleToString(seq.Distances[i],16);
   value+=";"+IntegerToString(ArraySize(seq.TradeLevels));
   for(int i=0;i<ArraySize(seq.TradeLevels);i++)
   {
      value+=";"+IntegerToString(seq.TradeLevels[i].ticket);
      value+=";"+DoubleToString(seq.TradeLevels[i].price_level,16);
      value+=";"+DoubleToString(seq.TradeLevels[i].price_trade,16);
      value+=";"+DoubleToString(seq.TradeLevels[i].sl,16);
      value+=";"+DoubleToString(seq.TradeLevels[i].tp,16);
      value+=";"+DoubleToString(seq.TradeLevels[i].lots,16);
   }
   return value;
  }

bool GOATDecodeSequence(const string value,SEQUENCE &seq)
  {
   string tokens[];
   int count=StringSplit(value,';',tokens),at=1;
   if(count<38 || count>100000 || tokens[0]!="S1") return false;
   for(int i=1;i<count;i++)
   {
      double number=StringToDouble(tokens[i]);
      if(!MathIsValidNumber(number) || (tokens[i]!=DoubleToString(number,16) && tokens[i]!=IntegerToString(StringToInteger(tokens[i])))) return false;
   }
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.Active=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.Traded=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.Trailing=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.Virtual=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.Retrace_Triggered=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.GuardRealStarted=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.BiasRescueActive=(bool)StringToInteger(tokens[at++]);
   if(tokens[at]!="0" && tokens[at]!="1") return false;
   seq.BiasRescueBEProtected=(bool)StringToInteger(tokens[at++]);
   seq.dir=(int)StringToInteger(tokens[at++]);
   seq.Level_Count=(int)StringToInteger(tokens[at++]);
   seq.Trades_Count=(int)StringToInteger(tokens[at++]);
   seq.BiasRescuePositiveAdds=(int)StringToInteger(tokens[at++]);
   seq.Level_Last=(double)StringToDouble(tokens[at++]);
   seq.Level_Retrace=(double)StringToDouble(tokens[at++]);
   seq.Level_Lock=(double)StringToDouble(tokens[at++]);
   seq.Level_TP=(double)StringToDouble(tokens[at++]);
   seq.Level_SL=(double)StringToDouble(tokens[at++]);
   seq.Level_TSL=(double)StringToDouble(tokens[at++]);
   seq.Level_Entry=(double)StringToDouble(tokens[at++]);
   seq.LotsTotal=(double)StringToDouble(tokens[at++]);
   seq.Size_Grid=(double)StringToDouble(tokens[at++]);
   seq.Size_Lock=(double)StringToDouble(tokens[at++]);
   seq.Size_TP=(double)StringToDouble(tokens[at++]);
   seq.Size_SL=(double)StringToDouble(tokens[at++]);
   seq.Size_TSL=(double)StringToDouble(tokens[at++]);
   seq.StartLots=(double)StringToDouble(tokens[at++]);
   seq.PeakLots=(double)StringToDouble(tokens[at++]);
   seq.PeakCumLots=(double)StringToDouble(tokens[at++]);
   seq.ScaleFactor=(double)StringToDouble(tokens[at++]);
   seq.SequenceRealizedPL=(double)StringToDouble(tokens[at++]);
   seq.BiasRescueBEPrice=(double)StringToDouble(tokens[at++]);
   seq.BiasRescueSLPrice=(double)StringToDouble(tokens[at++]);
   if(seq.Level_Count<0 || seq.Level_Count>Max_Seq_Levels || seq.Trades_Count<0 || seq.Trades_Count>Max_Seq_Trades) return false;
   if(at>=count) return false;
   int size_LotsRaw=(int)StringToInteger(tokens[at++]);
   if(size_LotsRaw<0 || size_LotsRaw>Max_Seq_Trades || at+size_LotsRaw>count) return false;
   ArrayResize(seq.LotsRaw,size_LotsRaw);
   for(int i=0;i<size_LotsRaw;i++) seq.LotsRaw[i]=StringToDouble(tokens[at++]);
   if(at>=count) return false;
   int size_LotsNorm=(int)StringToInteger(tokens[at++]);
   if(size_LotsNorm<0 || size_LotsNorm>Max_Seq_Trades || at+size_LotsNorm>count) return false;
   ArrayResize(seq.LotsNorm,size_LotsNorm);
   for(int i=0;i<size_LotsNorm;i++) seq.LotsNorm[i]=StringToDouble(tokens[at++]);
   if(at>=count) return false;
   int size_LotsCum=(int)StringToInteger(tokens[at++]);
   if(size_LotsCum<0 || size_LotsCum>Max_Seq_Trades || at+size_LotsCum>count) return false;
   ArrayResize(seq.LotsCum,size_LotsCum);
   for(int i=0;i<size_LotsCum;i++) seq.LotsCum[i]=StringToDouble(tokens[at++]);
   if(at>=count) return false;
   int size_Distances=(int)StringToInteger(tokens[at++]);
   if(size_Distances<0 || size_Distances>Max_Seq_Trades || at+size_Distances>count) return false;
   ArrayResize(seq.Distances,size_Distances);
   for(int i=0;i<size_Distances;i++) seq.Distances[i]=StringToDouble(tokens[at++]);
   if(at>=count) return false;
   int levels=(int)StringToInteger(tokens[at++]);
   if(levels!=seq.Level_Count || at+levels*6!=count) return false;
   ArrayResize(seq.TradeLevels,levels);
   for(int i=0;i<levels;i++)
   {
      seq.TradeLevels[i].ticket=StringToInteger(tokens[at++]);
      seq.TradeLevels[i].price_level=StringToDouble(tokens[at++]);
      seq.TradeLevels[i].price_trade=StringToDouble(tokens[at++]);
      seq.TradeLevels[i].sl=StringToDouble(tokens[at++]);
      seq.TradeLevels[i].tp=StringToDouble(tokens[at++]);
      seq.TradeLevels[i].lots=StringToDouble(tokens[at++]);
   }
   if(seq.Active && seq.Traded && (ArraySize(seq.LotsNorm)==0 || seq.Level_Count==0)) return false;
   return GOATEncodeSequence(seq)==value;
  }

string GOATRecoverySettings()
  {
   string value="";
   {string item=(string)Mode_Operation;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EA_Desc;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Signal_Sample_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Sequence_Sample_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Trailing_Sample_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Allow_New_Sequence;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Allow_Opposite_Seq;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Reverse_Seq;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Trade;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Grid_Size,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Grid_Min,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Grid_Max,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Grid_Exponent,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Grid_Factor,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lock_Profit_Size,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lock_Profit_Flexibility,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(TP_Pips,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(SL_Pips,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(RRR,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_RRR;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(TSL_Size,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Trail;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Delay_Trade;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Delay_Trade_Live;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Delay_Lots_Add;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Max_Seq_Trades;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)CloseAtMaxLevels;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ATR_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ATR_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ATR_Method;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Lots;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Risk,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Sequence_MLPS_Hard_Close;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lots_Input,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lots_Max,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lots_Max_Cum,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lots_Exponent,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Lots_Factor,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Lots_Prog;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Peak_Lots_Pos_PC,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Partial_Profit_Factor,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Peak_Smart_Release_PC,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(Peak_Smart_Max_Close_PC,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MaxLossLocal,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MaxLossGlobal,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MaxDailyLossLocal,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MaxDailyProfitLocal,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MinLevelEquity,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MaxLevelEquity,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Restart;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI_Price;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(RSI_Level,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_Method;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_Price;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_Count;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(EMA_Exponent,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)EMA_MustCheck;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ADX_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ADX_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ADX_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(ADX_Level,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)ADX_MustCheck;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)BB_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)BB_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)BB_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(BB_Deviation,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)BB_MustCheck;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Mode_Trend;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Fast;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Slow;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Signal;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(MACD_Deviations,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_Price;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)MACD_MustCheck;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI2_Mode;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI2_TF_;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI2_Period;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI2_Price;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=DoubleToString(RSI2_Level,16);value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)RSI2_MustCheck;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Active_Time_Weekday;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Active_Time_Friday;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Active_Time_ASIA;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Active_Time_EU;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Active_Time_US;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Action_Dayend;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Action_Friday;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Trade_Friday;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Bias_Protocol;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Bias;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Bias_Trades;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Bias_Exit;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Bias_Exit_Max_Exposure_Adds;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Bias_threshold;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_News;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)News_threshold;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)News_beforeMinutes;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)News_afterMinutes;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Download;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Download_StartDate;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Mode_Opti;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Seq_min_inp;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Trades_min_inp;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Trades_Max;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Minutes_Max;value+=IntegerToString(StringLen(item))+":"+item;}
   {string item=(string)Trade_December;value+=IntegerToString(StringLen(item))+":"+item;}
   string digest="";
   if(!GOATSha256Utf8(value,digest)) return "";
   return digest;
  }

bool GOATSequenceMatchesBroker(SEQUENCE &seq,const int direction)
  {
   if(seq.dir!=direction || seq.Virtual) return false;
   int found=0;
   for(int i=0;i<seq.Level_Count;i++)
   {
      long ticket=seq.TradeLevels[i].ticket;
      if(ticket<=0) continue;
      if(!PositionSelectByTicket(ticket))
      {if(seq.TradeLevels[i].lots>0 && FindNumberOfPositions(direction,MAGIC1)>0) return false;continue;}
      if(PositionGetInteger(POSITION_MAGIC)!=MAGIC1 || PositionGetString(POSITION_SYMBOL)!=_Symbol ||
         PositionGetInteger(POSITION_TYPE)!=direction || MathAbs(PositionGetDouble(POSITION_VOLUME)-seq.TradeLevels[i].lots)>0.00000001) return false;
      for(int j=0;j<i;j++) if(seq.TradeLevels[j].ticket==ticket) return false;
      found++;
   }
   return(found==FindNumberOfPositions(direction,MAGIC1) && (found==0 || (seq.Active && seq.Traded)));
  }

void GOATRecoverBrokerSequence(SEQUENCE &seq,const int direction)
  {
   // Old builds have no checkpoint. Recover only facts the broker still holds.
   // Do not manufacture virtual levels, old ATR measurements or partial-close ledgers.
   seq.dir=direction;seq.Virtual=false;
   seq.Active=seq.Traded=seq.Trailing=seq.GuardRealStarted=seq.Retrace_Triggered=false;
   seq.Level_Lock=seq.Level_TP=seq.Level_SL=0;
   seq.StartLots=seq.PeakLots=seq.PeakCumLots=seq.ScaleFactor=0;
   ArrayResize(seq.LotsRaw,0);ArrayResize(seq.LotsNorm,0);ArrayResize(seq.LotsCum,0);ArrayResize(seq.Distances,0);
   seq.Level_Count=seq.Trades_Count=0;
   seq.Level_Retrace=seq.Level_TSL=seq.Level_Last=seq.Level_Entry=seq.LotsTotal=0;
   seq.ResetSequenceRiskState();
   ArrayResize(seq.TradeLevels,0);
   long latest=0;
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || PositionGetInteger(POSITION_MAGIC)!=MAGIC1 || PositionGetString(POSITION_SYMBOL)!=_Symbol || PositionGetInteger(POSITION_TYPE)!=direction) continue;
      int n=ArraySize(seq.TradeLevels);ArrayResize(seq.TradeLevels,n+1);
      seq.TradeLevels[n].ticket=(long)ticket;
      seq.TradeLevels[n].price_level=seq.TradeLevels[n].price_trade=PositionGetDouble(POSITION_PRICE_OPEN);
      seq.TradeLevels[n].lots=PositionGetDouble(POSITION_VOLUME);
      seq.TradeLevels[n].sl=PositionGetDouble(POSITION_SL);
      seq.TradeLevels[n].tp=PositionGetDouble(POSITION_TP);
      seq.Level_Entry+=seq.TradeLevels[n].price_trade*seq.TradeLevels[n].lots;
      seq.LotsTotal+=seq.TradeLevels[n].lots;
      if(PositionGetInteger(POSITION_TIME_MSC)>=latest)
      {latest=PositionGetInteger(POSITION_TIME_MSC);seq.Level_Last=seq.TradeLevels[n].price_trade;}
   }
   seq.Level_Count=seq.Trades_Count=ArraySize(seq.TradeLevels);
   if(seq.Level_Count==0) return;
   seq.Active=seq.Traded=seq.GuardRealStarted=true;
   seq.Level_Entry/=seq.LotsTotal;
   seq.Size_Grid=GetSize(GRID);seq.Size_Lock=GetSize(LOCK);seq.Size_TP=GetSize(OP_TP);seq.Size_SL=GetSize(OP_SL);seq.Size_TSL=GetSize(TSL);
   seq.Level_Lock=seq.Size_Lock==0 ? (direction==OP_BUY ? 999999 : 0) : seq.Level_Entry+(direction==OP_BUY ? seq.Size_Lock : -seq.Size_Lock);
   g_GOATRecoveryDegraded=true;
   Print("GOAT recovery: broker positions recovered; full historical sequence state unavailable. New exposure remains blocked pending review.");
  }

void GOATRestoreManagement()
  {
   if(!g_GOATManager) return;
   string identity=(string)g_GOATManagerAccount+"|"+g_GOATManagerServer+"|"+_Symbol+"|"+(string)ChartID()+"|"+(string)MAGIC1;
   string key="";
   if(!GOATSha256Utf8(identity,key))
   {g_GOATRecoveryDegraded=true;GOATRecoverBrokerSequence(Seq_Buy,OP_BUY);GOATRecoverBrokerSequence(Seq_Sell,OP_SELL);return;}
   g_GOATRecoveryPath="GOAT\\Recovery\\"+key+".state";
   g_GOATRecoverySettings=GOATRecoverySettings();
   string binding="";
   if(g_GOATRecoverySettings=="" || !GOATSha256Utf8(key+"|"+g_GOATRecoverySettings,binding))
   {g_GOATRecoverySettings="";g_GOATRecoveryWriteFailed=true;}
   else g_GOATRecoverySettings=binding;
   bool restored=false;
   int handle=FileOpen(g_GOATRecoveryPath,FILE_READ|FILE_TXT|FILE_UNICODE);
   if(handle!=INVALID_HANDLE)
   {
      if(FileSize(handle)<=2000000)
      {
         string record=FileReadString(handle),parts[];
         if(StringSplit(record,'|',parts)==5)
         {
            string digest="",payload=parts[1]+"|"+parts[2]+"|"+parts[3]+"|"+parts[4];
            if(GOATSha256Utf8(payload,digest) && digest==parts[0] && parts[1]==g_GOATRecoverySettings && g_GOATRecoverySettings!="")
            {
               restored=GOATDecodeSequence(parts[2],Seq_Buy) && GOATDecodeSequence(parts[3],Seq_Sell)
                        && GOATSequenceMatchesBroker(Seq_Buy,OP_BUY) && GOATSequenceMatchesBroker(Seq_Sell,OP_SELL);
               if(restored) g_GOATRecoveryDegraded=(parts[4]!="0");
            }
         }
      }
      FileClose(handle);
   }
   if(!restored)
   {
      GOATRecoverBrokerSequence(Seq_Buy,OP_BUY);
      GOATRecoverBrokerSequence(Seq_Sell,OP_SELL);
   }
   else Print("GOAT recovery: sequence checkpoint restored and matched to broker positions.");
   // Closed baskets must not retain an active sequence from a pre-close checkpoint.
   if(FindNumberOfPositions(OP_BUY,MAGIC1)==0) Seq_Buy.End_Sequence("restart: no open buys");
   if(FindNumberOfPositions(OP_SELL,MAGIC1)==0) Seq_Sell.End_Sequence("restart: no open sells");
  }

void GOATSaveManagement()
  {
   if(!g_GOATManager || !g_GOATManagerReady || g_GOATRecoveryPath=="" || g_GOATRecoverySettings=="" || !TerminalInfoInteger(TERMINAL_CONNECTED)) return;
   if(g_GOATRecoveryDegraded && FindNumberOfPositions(OP_BUYSELL,MAGIC1)==0)
   {g_GOATRecoveryDegraded=false;Print("GOAT recovery: uncertain basket is flat; normal entry authorization may resume.");}
   string payload=g_GOATRecoverySettings+"|"+GOATEncodeSequence(Seq_Buy)+"|"+GOATEncodeSequence(Seq_Sell)+"|"+(g_GOATRecoveryDegraded ? "1" : "0");
   if(payload==g_GOATRecoveryLast) return;
   string digest="";
   if(!GOATSha256Utf8(payload,digest)) {g_GOATRecoveryWriteFailed=true;return;}
   string record=digest+"|"+payload;
   int handle=FileOpen(g_GOATRecoveryPath+".tmp",FILE_WRITE|FILE_TXT|FILE_UNICODE);
   bool ok=false;
   if(handle!=INVALID_HANDLE)
   {
      ResetLastError();
      uint written=FileWriteString(handle,record);
      FileFlush(handle);
      ok=(written==(uint)(StringLen(record)*2) && GetLastError()==0);
      FileClose(handle);
      if(ok) ok=FileMove(g_GOATRecoveryPath+".tmp",0,g_GOATRecoveryPath,FILE_REWRITE);
      if(ok)
      {
         int verify=FileOpen(g_GOATRecoveryPath,FILE_READ|FILE_TXT|FILE_UNICODE);
         ok=(verify!=INVALID_HANDLE);
         if(ok) {ok=(FileReadString(verify)==record);FileClose(verify);}
      }
   }
   if(ok) {g_GOATRecoveryLast=payload;g_GOATRecoveryWriteFailed=false;}
   else {g_GOATRecoveryWriteFailed=true;Print("GOAT recovery checkpoint write failed; position management continues, new exposure blocked.");}
  }

// Do not overwrite a pre-restart checkpoint with an empty, disconnected broker view.
bool GOATTryManagementRecovery()
  {
   if(g_GOATManagerReady) return true;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) || g_GOATManagerAccount<=0
      || AccountInfoInteger(ACCOUNT_LOGIN)!=g_GOATManagerAccount || AccountInfoString(ACCOUNT_SERVER)!=g_GOATManagerServer)
   {g_GOATAuthReason="WAITING_FOR_BROKER_IDENTITY";GOATManagementStatus();return false;}
   GOATRestoreManagement();
   g_GOATManagerReady=true;
   GOATSaveManagement();
   GOATManagementStatus();
   return true;
  }
