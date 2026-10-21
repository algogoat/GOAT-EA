<chart>
<expert>
name=GOAT V1.49
path=Experts\GOAT-EA\GOAT V1.49.ex5
expertmode=5
<inputs>
; Days=164 Weeks=32.0 Months=7.6
; Trades=471 Sequences=171
; Positions=88 Avg Duration=1209 Minutes
; PF=2.421 RF=9.483 SR=4.104 ARF=1.332
; Return=4177 MonthlyRet=553 DD=440
; Orders=431/431 TPSL_Modified=995/995 TSL_Modified=502/502 Closed=84/84 PartialClosed=155/155
; DDs_% =  0.43 0.43 0.38 0.38 0.37 0.36
; DDs_Act= 444 444 393 392 374 368
; BOOS:   2026.02.02-2026.03.02 Days=20 Trades=32 PL=341
; SAMPLE: 2026.03.02-2026.08.15 Days=120 Trades=335 PL=3345
; FWD:    2026.06.20-2026.08.14 Days=39 Trades=90 PL=874
; FOOS:   2026.08.15-2026.09.17 Days=24 Trades=64 PL=642
; ===========GENERAL SETTINGS============
Mode_Operation=9
EA_Desc=R99475c1ec8ee7bd0b661
; ===========SEQUENCE SETTINGS===========
Signal_Sample_Period=99
Sequence_Sample_Period=99
Trailing_Sample_Period=-1
Allow_New_Sequence=true
Allow_Opposite_Seq=false
Reverse_Seq=false
Mode_Trade=0
Grid_Size=-3.0
Grid_Min=-1.5
Grid_Max=-15.0
Grid_Exponent=1.3
Grid_Factor=1.1
Lock_Profit_Size=-8.0
Lock_Profit_Flexibility=0.1
TP_Pips=1.8
SL_Pips=0.0
RRR=0.0
Mode_RRR=0
TSL_Size=-0.5
Mode_Trail=0
Delay_Trade=0
Delay_Trade_Live=0
Delay_Lots_Add=false
Max_Seq_Trades=6
CloseAtMaxLevels=true
; =============ATR SETTINGS==============
ATR_TF_=5
ATR_Period=1000
ATR_Method=1
; ============POSITION SIZING============
Mode_Lots=2
Risk=500.0
Sequence_MLPS_Hard_Close=true
Lots_Input=0.05
Lots_Max=20.0
Lots_Max_Cum=50.0
Lots_Exponent=1.4
Lots_Factor=1.3
Mode_Lots_Prog=5
Peak_Lots_Pos_PC=35.0
Partial_Profit_Factor=30.0
Peak_Smart_Release_PC=20.0
Peak_Smart_Max_Close_PC=15.0
; ============MONEY MANAGEMENT===========
MaxLossLocal=0.0
MaxLossGlobal=0.0
MaxDailyLossLocal=0.0
MaxDailyProfitLocal=0.0
MinLevelEquity=0.0
MaxLevelEquity=0.0
Mode_Restart=25
; =============RSI SETTINGS==============
RSI_Mode=0
RSI_TF_=15
RSI_Period=7
RSI_Price=7
RSI_Level=90.0
; ========MOVING AVERAGE SETTINGS========
EMA_Mode=1
EMA_TF_=15
EMA_Method=1
EMA_Price=7
EMA_Count=4
EMA_Period=7
EMA_Exponent=1.5
EMA_MustCheck=true
; =============ADX SETTINGS==============
ADX_Mode=2
ADX_TF_=15
ADX_Period=7
ADX_Level=24.0
ADX_MustCheck=true
; =======BOLLINGER BANDS SETTINGS========
BB_Mode=3
BB_TF_=5
BB_Period=25
BB_Deviation=1.8
BB_MustCheck=true
; =============MACD SETTINGS=============
MACD_Mode=0
MACD_Mode_Trend=0
MACD_TF_=1
MACD_Fast=8
MACD_Slow=20
MACD_Signal=9
MACD_Deviations=2.0
MACD_Price=1
MACD_MustCheck=false
; =============RSI2 SETTINGS==============
RSI2_Mode=0
RSI2_TF_=1
RSI2_Period=14
RSI2_Price=1
RSI2_Level=70.0
RSI2_MustCheck=true
; ===========TRADING SCHEDULE============
Active_Time_Weekday=6
Active_Time_Friday=2
Active_Time_ASIA=01:30-11:00
Active_Time_EU=10:00-19:00
Active_Time_US=15:00-22:30
Action_Dayend=0
Action_Friday=2
Trade_Friday=true
; ==========GOAT AI SIGNAL FILTER==========
Bias_Protocol=2
Mode_Bias=1
Mode_Bias_Trades=0
Mode_Bias_Exit=1
Bias_Exit_Max_Exposure_Adds=-1
Bias_threshold=50
Mode_News=1
News_threshold=85
News_beforeMinutes=70
News_afterMinutes=120
; ==========AI BIAS/NEWS DATA DOWNLOADER=========
Mode_Download=0
Download_StartDate=2025.01.01
; ========OPTIMIZATION PARAMETERS========
Mode_Opti=3
Seq_min_inp=150
Trades_min_inp=200
Trades_Max=2000
Minutes_Max=1000
Trade_December=true
</inputs>
</expert>
</chart>
