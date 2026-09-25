# GOAT V1.48 input reference

This reference lists every input exposed by this installed build. Run `discover`
for the machine-readable schema and use `validate-set` before preparing a run.
Source defaults below are declaration defaults, not recommended portfolio settings.
A supplied optimization template has its own deliberate values and ranges.

## Reading and changing inputs

- SET values use `current||start||step||stop||Y` for enabled search axes; `N` fixes the current value. Preserve the template format with `build-set`.
- `sinput` and strings cannot be search dimensions. For enums use the exact numeric values listed below; contiguous numeric ranges are not always valid enum ladders.
- Dependency validation currently covers the listed indicator mode gates only. An unchecked axis still needs a behavior-based rationale; a valid file does not prove a useful search space.
- Never optimize identity, controller monitoring or credential fields. `EA_Desc` is generated uniquely for each variant/attempt. Keep credentials in the user’s own activation flow.
- Operation mode, sequence sizing, exits and signal modes work together. Begin with a reviewed template, explain each change, keep unused indicator dimensions fixed, and preserve untouched validation history.
- Optimization Studio tester and export settings are separate from these EA inputs. See [all Studio controls](goat-beta-agent-guide.md) for the 18 tester and nine export fields, including sequence capture and its time/storage cost.
- See [template creation](TEMPLATE-WORKFLOW.md), [capabilities](goat-agent-capabilities.md), and [seed research](SEED-WORKFLOW.md) for the supported workflows.

Input declaration SHA-256: `a460cf6642b794d5e564701b192c135cd7564e300726fa88fe01e9649209e5c0`. Dependency logic SHA-256: `2370b4fe295073f342fabceaf1c309450eaf99a692cd8517bc80a8fd767535e9`.
This release contains **114 inputs**. The installed contract files retain the build defines and complete enum mapping.


## General Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_Operation` | Operation Mode | `ENUM_MODE_OPERATION` | `Operation_Standard` | Fixed only |
| `EA_Desc` | Strategy Comment | `string` | `"GOAT_Trading"` | Fixed only |

## Sequence Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Signal_Sample_Period` | Check Signal (Sequence Start Only) | `ENUM_MODE_SAMPLING` | `M1` | Fixed only |
| `Sequence_Sample_Period` | Check Sequence | `ENUM_MODE_SAMPLING` | `M1` | Fixed only |
| `Trailing_Sample_Period` | Check Trailing/Lock/TP | `ENUM_MODE_SAMPLING` | `Second` | Allowed; validate dependency |
| `Allow_New_Sequence` | Allow New Sequence | `bool` | `true` | Fixed only |
| `Allow_Opposite_Seq` | Allow Opposite Sequences | `bool` | `true` | Allowed; validate dependency |
| `Reverse_Seq` | Reverse Sequence Direction | `bool` | `false` | Allowed; validate dependency |
| `Mode_Trade` | Sequence Type | `ENUM_MODE_TRADE_DIR` | `Long_and_Short` | Allowed; validate dependency |
| `Grid_Size` | Pip Gap Size (-ve for ATR) | `double` | `10.0` | Allowed; validate dependency |
| `Grid_Min` | Pip Gap Minimum (-ve for ATR) | `double` | `1.0` | Allowed; validate dependency |
| `Grid_Max` | Pip Gap Maximum (-ve for ATR) | `double` | `30.0` | Allowed; validate dependency |
| `Grid_Exponent` | Pip Gap Exponent | `double` | `1.2` | Allowed; validate dependency |
| `Grid_Factor` | Dynamic Gap Factor (1=no effect) | `double` | `1.0` | Allowed; validate dependency |
| `Lock_Profit_Size` | Lock Profit (LP) Pips (-ve for ATR) | `double` | `30.0` | Allowed; validate dependency |
| `Lock_Profit_Flexibility` | Dynamic LP (1=same, 0=BE, -1=-LP) | `double` | `1.0` | Allowed; validate dependency |
| `TP_Pips` | TP Size (multiplies LP, must be >1) | `double` | `2.0` | Allowed; validate dependency |
| `SL_Pips` | SL pips (-ve for ATR) | `double` | `0.0` | Allowed; validate dependency |
| `RRR` | Risk/Reward Ratio | `double` | `0.0` | Allowed; validate dependency |
| `Mode_RRR` | RRR Calculation Method | `ENUM_MODE_RRR` | `RRR_Disabled` | Allowed; validate dependency |
| `TSL_Size` | Trailing SL Pips (-ve for ATR) | `double` | `5.0` | Allowed; validate dependency |
| `Mode_Trail` | Trailing Mode | `ENUM_MODE_TRAIL` | `Trail_Lock` | Allowed; validate dependency |
| `Delay_Trade` | Delay Trade Sequence | `int` | `1` | Allowed; validate dependency |
| `Delay_Trade_Live` | Live Delay Sequence | `int` | `1` | Allowed; validate dependency |
| `Delay_Lots_Add` | Add Delayed Lots | `bool` | `true` | Allowed; validate dependency |
| `Max_Seq_Trades` | Max Trades/Entries in a Sequence | `int` | `10` | Allowed; validate dependency |
| `CloseAtMaxLevels` | Close Sequence after Max Trades | `bool` | `false` | Allowed; validate dependency |

## Atr Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `ATR_TF_` | ATR Timeframe | `ENUM_MODE_TFs` | `TF_M1` | Allowed; validate dependency |
| `ATR_Period` | ATR Averaging Period | `int` | `100` | Allowed; validate dependency |
| `ATR_Method` | ATR Averaging Method | `ENUM_MODE_MA` | `SMA` | Allowed; validate dependency |

## Position Sizing

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_Lots` | Sizing Method (For Starting Lots) | `ENUM_MODE_LOTS` | `FixedLots` | Fixed only |
| `Risk` | Risk/Loss per Sequence in $$$ | `double` | `500` | Fixed only |
| `Sequence_MLPS_Hard_Close` | Hard Close Sequence at Risk/MLPS Breach | `bool` | `false` | Fixed only |
| `Lots_Input` | Starting Lots (Fixed/Scaled) | `double` | `0.1` | Allowed; validate dependency |
| `Lots_Max` | Max Trade Lots (multiplies Starting Lots) | `double` | `10.0` | Allowed; validate dependency |
| `Lots_Max_Cum` | Max Cumulative Lots (multiplies Starting Lots) | `double` | `50.0` | Allowed; validate dependency |
| `Lots_Exponent` | Lots Exponent | `double` | `1.2` | Allowed; validate dependency |
| `Lots_Factor` | Dynamic Lots Factor (1=no effect) | `double` | `1.0` | Allowed; validate dependency |
| `Mode_Lots_Prog` | Lots Progression Model | `ENUM_MODE_LOTS_PROG` | `Lots_Prog_Last` | Allowed; validate dependency |
| `Peak_Lots_Pos_PC` | % Position in sequence where Lots peak | `double` | `50.0` | Allowed; validate dependency |
| `Partial_Profit_Factor` | % Standing lots to close on each retrace level | `double` | `10.0` | Allowed; validate dependency |
| `Peak_Smart_Release_PC` | Smart Peak % excess lots harvested | `double` | `50.0` | Allowed; validate dependency |
| `Peak_Smart_Max_Close_PC` | Smart Peak max % standing lots harvested | `double` | `30.0` | Allowed; validate dependency |

## Risk Management

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `MaxLossLocal` | Max Local Running Loss amount | `double` | `0.0` | Fixed only |
| `MaxLossGlobal` | Max Global Running Loss amount | `double` | `0.0` | Fixed only |
| `MaxDailyLossLocal` | Max Daily Local Loss amount | `double` | `0.0` | Allowed; validate dependency |
| `MaxDailyProfitLocal` | Max Daily Local Profit amount | `double` | `0.0` | Allowed; validate dependency |
| `MinLevelEquity` | Low Equity Stop Level | `double` | `0.0` | Fixed only |
| `MaxLevelEquity` | Equity Target Level | `double` | `0.0` | Fixed only |
| `Mode_Restart` | Restart after loss | `ENUM_MODE_RESTART` | `Restart_Tmr` | Fixed only |

## Rsi Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `RSI_Mode` | Mode | `ENUM_MODE_RSI` | `RSI_OverBS` | Allowed; validate dependency |
| `RSI_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_M1` | Allowed; validate dependency |
| `RSI_Period` | Period | `uint` | `4` | Allowed; validate dependency |
| `RSI_Price` | Applied Price | `ENUM_MODE_PRICE` | `Price_Typical` | Allowed; validate dependency |
| `RSI_Level` | High Level (Low level mirrored) | `double` | `80` | Allowed; validate dependency |

## Moving Average Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `EMA_Mode` | Mode | `ENUM_MODE_TRADE` | `Trade_Trend` | Allowed; validate dependency |
| `EMA_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_M15` | Allowed; validate dependency |
| `EMA_Method` | Method | `ENUM_MA_METHOD` | `MODE_EMA` | Allowed; validate dependency |
| `EMA_Price` | Applied Price | `ENUM_MODE_PRICE` | `Price_Typical` | Allowed; validate dependency |
| `EMA_Count` | Number of MAs | `int` | `5` | Allowed; validate dependency |
| `EMA_Period` | Fastest/Smallest Period | `int` | `7` | Allowed; validate dependency |
| `EMA_Exponent` | MA Exponent | `double` | `1.5` | Allowed; validate dependency |
| `EMA_MustCheck` | Must Check (When Delay is used) | `bool` | `false` | Allowed; validate dependency |

## Adx Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `ADX_Mode` | Mode | `ENUM_MODE_TRADE` | `Trade_Trend` | Allowed; validate dependency |
| `ADX_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_M15` | Allowed; validate dependency |
| `ADX_Period` | Period | `uint` | `14` | Allowed; validate dependency |
| `ADX_Level` | Buy/Sell Level | `double` | `30` | Allowed; validate dependency |
| `ADX_MustCheck` | Must Check (When Delay is used) | `bool` | `false` | Allowed; validate dependency |

## Bollinger Bands Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `BB_Mode` | Mode | `ENUM_MODE_BB` | `BB_Disabled` | Allowed; validate dependency |
| `BB_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_H1` | Allowed; validate dependency |
| `BB_Period` | Period | `uint` | `120` | Allowed; validate dependency |
| `BB_Deviation` | Deviation | `double` | `1.5` | Allowed; validate dependency |
| `BB_MustCheck` | Must Check (When Delay is used) | `bool` | `false` | Allowed; validate dependency |

## Macd Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `MACD_Mode` | Mode | `ENUM_MODE_TRADE` | `Trade_Disabled` | Allowed; validate dependency |
| `MACD_Mode_Trend` | MACD Trend Mode | `ENUM_MODE_MACD_TREND` | `MACD_CO` | Allowed; validate dependency |
| `MACD_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_M15` | Allowed; validate dependency |
| `MACD_Fast` | Fast Period | `uint` | `12` | Allowed; validate dependency |
| `MACD_Slow` | Slow Period | `uint` | `26` | Allowed; validate dependency |
| `MACD_Signal` | Signal Period | `uint` | `9` | Allowed; validate dependency |
| `MACD_Deviations` | Threshold Size | `double` | `2.0` | Allowed; validate dependency |
| `MACD_Price` | Applied price | `ENUM_MODE_PRICE` | `Price_Typical` | Allowed; validate dependency |
| `MACD_MustCheck` | Must Check (When Delay is used) | `bool` | `false` | Allowed; validate dependency |

## Rsi2 Settings

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `RSI2_Mode` | Mode | `ENUM_MODE_RSI` | `RSI_Disabled` | Allowed; validate dependency |
| `RSI2_TF_` | Timeframe | `ENUM_MODE_TFs` | `TF_M15` | Allowed; validate dependency |
| `RSI2_Period` | Period | `uint` | `13` | Allowed; validate dependency |
| `RSI2_Price` | Applied Price | `ENUM_MODE_PRICE` | `Price_Typical` | Allowed; validate dependency |
| `RSI2_Level` | High Level (Low level mirrored) | `double` | `70` | Allowed; validate dependency |
| `RSI2_MustCheck` | Must Check (When Delay is used) | `bool` | `false` | Allowed; validate dependency |

## Trading Schedule

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Active_Time_Weekday` | Trading Times (Mon-Thu) | `ENUM_MODE_SESSION` | `SESS_ALL` | Allowed; validate dependency |
| `Active_Time_Friday` | Trading Times (Friday) | `ENUM_MODE_SESSION2` | `SESSION_AS` | Allowed; validate dependency |
| `Active_Time_ASIA` | Session Times (Asia) | `string` | `"01:30-11:00"` | Fixed only |
| `Active_Time_EU` | Session Times (Europe) | `string` | `"10:00-19:00"` | Fixed only |
| `Active_Time_US` | Session Times (US) | `string` | `"15:00-22:30"` | Fixed only |
| `Action_Dayend` | Action at End of Session | `ENUM_ACTION_CLOSE` | `Action_Null` | Allowed; validate dependency |
| `Action_Friday` | Action at Friday Close | `ENUM_ACTION_CLOSE` | `Action_Null` | Allowed; validate dependency |
| `Trade_Friday` | Start New Sequences on Friday | `bool` | `true` | Allowed; validate dependency |

## Goat Ai Signal Filter

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Bias_Protocol` | Authenticated AI bias protocol | `ENUM_GOAT_AI_BIAS_PROTOCOL` | `BiasProtocol_ControlTowerV2DemoRaw` | Allowed; validate dependency |

## News And Ai Filter

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_Bias` | AI bias mode | `ENUM_ACTION_BIAS` | `GOAT_DEFAULT_BIAS_MODE` | Allowed; validate dependency |
| `Mode_Bias_Trades` | AI Bias restriction | `ENUM_BIAS_TRADES` | `Bias_Seq` | Allowed; validate dependency |
| `Mode_Bias_Exit` | AI Bias Exit Mode | `ENUM_BIAS_EXIT` | `BiasExit_HardClose` | Allowed; validate dependency |
| `Bias_Exit_Max_Exposure_Adds` | Smart Rescue max positive adds (-1=normal) | `int` | `-1` | Allowed; validate dependency |
| `Bias_threshold` | Minimum AI confidence to trade (%) | `int` | `60` | Allowed; validate dependency |

## Goat News Filter

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_News` | News Mode | `ENUM_ACTION_NEWS` | `News_Disabled` | Allowed; validate dependency |
| `News_threshold` | News Impact threshold | `int` | `60` | Allowed; validate dependency |
| `News_beforeMinutes` | Before News Minutes | `int` | `90` | Allowed; validate dependency |
| `News_afterMinutes` | After News Minutes | `int` | `150` | Allowed; validate dependency |

## Ai Bias/News Data Downloader

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_Download` | Data Download Mode for Backtest | `ENUM_MODE_DOWNLOAD` | `Download_Disabled` | Fixed only |
| `Download_StartDate` | Download Start Date | `datetime` | `D'2025.01.01'` | Fixed only |

## Optimization Parameters

| Input | Meaning / units from EA declaration | Type | Source default | Search axis |
|---|---|---|---|---|
| `Mode_Opti` | Fitness Calculation | `ENUM_MODE_OPTI` | `Opti_PF_MRF_SRp` | Fixed only |
| `Seq_min_inp` | Ideal Minimum Traded Sequences | `int` | `100` | Fixed only |
| `Trades_min_inp` | Ideal Minimum Trades | `int` | `300` | Fixed only |
| `Trades_Max` | Max Trades Opened | `int` | `1500` | Fixed only |
| `Minutes_Max` | Max Avg Trade duration (Minutes) | `int` | `1000` | Fixed only |
| `Trade_December` | Trade December ? | `bool` | `true` | Fixed only |

## Enum choices

Names and numbers are exact. Do not infer omitted values or use a numeric ladder that crosses an undefined value.

### ENUM_MODE_OPERATION

`Operation_Standard=9`, `Operation_Batch=11`, `Operation_Report=13`, `Operation_Dash=8`.

### ENUM_MODE_SAMPLING

`Tick=0`, `Second=-1`, `M1=1`, `M_Current=99`.

### ENUM_MODE_TRADE_DIR

`Long_and_Short=0`, `Long=1`, `Short=2`.

### ENUM_MODE_RRR

`RRR_Disabled=0`, `RRR_SL_TP=1`, `RRR_SL_LP=2`.

### ENUM_MODE_TRAIL

`Trail_Lock=0`, `Trail_Lock_Pro=1`.

### ENUM_MODE_TFs

`TF_Cur=0`, `TF_M1=1`, `TF_M5=5`, `TF_M15=15`, `TF_H1=60`, `TF_H4=240`.

### ENUM_MODE_MA

`EMA=0`, `SMA=1`, `LWMA=2`.

### ENUM_MODE_LOTS

`FixedLots=0`, `ScaledLots=1`, `RiskperSeq=2`.

### ENUM_MODE_LOTS_PROG

`Lots_Prog_Start=0`, `Lots_Prog_Last=1`, `Lots_Prog_Cum=2`, `Lots_Prog_Cum2=3`, `Lots_Prog_Peak=4`, `Lots_Prog_CumPartial=5`, `Lots_Prog_PeakSmart=6`.

### ENUM_MODE_RESTART

`Restart_Tmr=25`, `Restart_1=1`, `Restart_2=2`, `Restart_3=3`, `Restart_5=5`.

### ENUM_MODE_RSI

`RSI_Disabled=0`, `RSI_OverBS=1`, `RSI_OverBSCross=2`, `RSI_OBSCEngulf=3`.

### ENUM_MODE_PRICE

`Price_Close=1`, `Price_Typical=6`, `Price_Weighted=7`, `Price_Median=5`.

### ENUM_MODE_TRADE

`Trade_Disabled=0`, `Trade_Trend=1`, `Trade_Trend_Range=2`, `Trade_Range=3`, `Trade_Counter_Range=4`, `Trade_Counter=5`.

### ENUM_MA_METHOD

`MODE_SMA=0`, `MODE_EMA=1`, `MODE_SMMA=2`, `MODE_LWMA=3`.

### ENUM_MODE_BB

`BB_Disabled=0`, `BB_Channel=1`, `BB_OverBS=2`, `BB_Trend=3`.

### ENUM_MODE_MACD_TREND

`MACD_CO=0`, `MACD_CO_G=1`, `MACD_CO_T=2`, `MACD_CO_G_T=3`.

### ENUM_MODE_SESSION

`SESS_NONE=0`, `SESS_AS=1`, `SESS_AS_EU=2`, `SESS_EU=3`, `SESS_EU_US=4`, `SESS_US=5`, `SESS_ALL=6`.

### ENUM_MODE_SESSION2

`SESSION_NONE=0`, `SESSION_AS=1`, `SESSION_AS_EU=2`, `SESSION_EU=3`, `SESSION_EU_US=4`, `SESSION_US=5`, `SESSION_ALL=6`, `SESSION_FRI=7`.

### ENUM_ACTION_CLOSE

`Action_Null=0`, `Action_Pause=1`, `Action_Close=2`.

### ENUM_GOAT_AI_BIAS_PROTOCOL

`BiasProtocol_LegacyRecorded=0`, `BiasProtocol_ControlTowerV2=1`, `BiasProtocol_ControlTowerV2DemoRaw=2`.

### ENUM_ACTION_BIAS

`Bias_Display=0`, `Bias_Disabled=1`, `Bias_Opens=2`, `Bias_Close_low=3`, `Bias_Close_med=4`, `Bias_Close_high=5`.

### ENUM_BIAS_TRADES

`Bias_Seq=0`, `Bias_SeqTrade=1`.

### ENUM_BIAS_EXIT

`BiasExit_HardClose=0`, `BiasExit_SmartRescue=1`.

### ENUM_ACTION_NEWS

`News_Display=0`, `News_Disabled=1`, `News_Avoid=2`, `News_Pause=3`, `News_Close=4`, `News_Only=5`.

### ENUM_MODE_DOWNLOAD

`Download_Disabled=0`, `Download_News=1`, `Download_Bias=2`, `Download_NewsBias=3`.

### ENUM_MODE_OPTI

`Opti_MRF=0`, `Opti_PF_MRF=1`, `Opti_PF_MRFp=2`, `Opti_PF_MRF_SR=3`, `Opti_PF_MRF_SRp=4`.

## Validated indicator dependencies

An axis is rejected when its controlling mode is disabled throughout the search. A mixed enabled/disabled mode range produces a conditional warning. Other behavior dependencies are not automatically certified.

| Axis | Controlling mode | Disabled value |
|---|---|---|
| `RSI_TF_` | `RSI_Mode` | `0` |
| `RSI_Period` | `RSI_Mode` | `0` |
| `RSI_Price` | `RSI_Mode` | `0` |
| `RSI_Level` | `RSI_Mode` | `0` |
| `EMA_TF_` | `EMA_Mode` | `0` |
| `EMA_Method` | `EMA_Mode` | `0` |
| `EMA_Price` | `EMA_Mode` | `0` |
| `EMA_Count` | `EMA_Mode` | `0` |
| `EMA_Period` | `EMA_Mode` | `0` |
| `EMA_Exponent` | `EMA_Mode` | `0` |
| `ADX_TF_` | `ADX_Mode` | `0` |
| `ADX_Period` | `ADX_Mode` | `0` |
| `ADX_Level` | `ADX_Mode` | `0` |
| `BB_TF_` | `BB_Mode` | `0` |
| `BB_Period` | `BB_Mode` | `0` |
| `BB_Deviation` | `BB_Mode` | `0` |
| `MACD_Mode_Trend` | `MACD_Mode` | `0` |
| `MACD_TF_` | `MACD_Mode` | `0` |
| `MACD_Fast` | `MACD_Mode` | `0` |
| `MACD_Slow` | `MACD_Mode` | `0` |
| `MACD_Signal` | `MACD_Mode` | `0` |
| `MACD_Deviations` | `MACD_Mode` | `0` |
| `MACD_Price` | `MACD_Mode` | `0` |
| `RSI2_TF_` | `RSI2_Mode` | `0` |
| `RSI2_Period` | `RSI2_Mode` | `0` |
| `RSI2_Price` | `RSI2_Mode` | `0` |
| `RSI2_Level` | `RSI2_Mode` | `0` |

## Reporting unclear behavior

Retain the exact installed versions, input schema hash, template hash, changed values, expected behavior and observed evidence. Use the private support workflow in the [agent guide](goat-beta-agent-guide.md). Preview the report with the user and submit its approved contents; never include activation secrets or another user’s paths/account.
