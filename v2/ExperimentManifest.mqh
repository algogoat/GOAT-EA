#ifndef GOAT_V2_EXPERIMENT_MANIFEST_MQH
#define GOAT_V2_EXPERIMENT_MANIFEST_MQH

#include "Identity.mqh"
#include "Inputs_V2.mqh"
#include "Receipts.mqh"
#include "Clock.mqh"

enum ENUM_V2_MANIFEST_CLASS
  {
   V2_MANIFEST_DEVELOPMENT=0,
   V2_MANIFEST_OPTIMIZATION=1,
   V2_MANIFEST_CERTIFICATION=2,
   V2_MANIFEST_LIVE=3
  };

struct V2ExternalLineage
  {
   string git_commit;
   string source_hash;
   string binary_hash;
   string reference_commit;
   string set_hash;
   string tick_data_hash;
   string tester_model;
   string test_window;
   string state_pack_hash;
   string calendar_hash;
   string model_bundle_hash;
   string broker_profile_version;
   string broker_profile_hash;
   string random_seed;

   void Reset(void)
     {
      git_commit="";
      source_hash="";
      binary_hash="";
      reference_commit="";
      set_hash="";
      tick_data_hash="";
      tester_model="";
      test_window="";
      state_pack_hash="";
      calendar_hash="";
      model_bundle_hash="";
      broker_profile_version="";
      broker_profile_hash="";
      random_seed="";
     }
  };

struct V2ExperimentManifest
  {
   string                    manifest_id;
   string                    manifest_hash;
   string                    canonical_payload;
   string                    schema_version;
   string                    product_version;
   string                    build_id;
   ENUM_V2_MANIFEST_CLASS    manifest_class;
   long                      created_at_msc;
   string                    deployment_id;
   string                    portfolio_generation_id;
   string                    strategy_member_id;
   string                    magic_transport;
   string                    program_name;
   string                    program_path;
   long                      terminal_build;
   bool                      is_tester;
   bool                      is_optimization;
   bool                      is_forward;
   bool                      is_visual;
   ENUM_V2_BOOKKEEPING_MODE  bookkeeping_mode;
   string                    persistence_backend;
   string                    input_schema_hash;
   string                    input_values_hash;
   string                    expected_source_hash;
   string                    expected_binary_hash;
   string                    external_git_commit;
   string                    external_source_hash;
   string                    external_binary_hash;
   string                    account_fingerprint;
   string                    account_server;
   string                    account_company;
   string                    account_currency;
   long                      account_leverage;
   int                       account_margin_mode;
   string                    symbol;
   string                    symbol_spec_hash;
   string                    reference_commit;
   string                    set_hash;
   string                    tick_data_hash;
   string                    tester_model;
   string                    test_window;
   string                    state_pack_hash;
   string                    calendar_hash;
   string                    model_bundle_hash;
   string                    broker_profile_version;
   string                    broker_profile_hash;
   string                    random_seed;
   bool                      external_lineage_complete;

   void Reset(void)
     {
      manifest_id="";
      manifest_hash="";
      canonical_payload="";
      schema_version="goat2-experiment-manifest-v1";
      product_version="";
      build_id="";
      manifest_class=V2_MANIFEST_DEVELOPMENT;
      created_at_msc=0;
      deployment_id="";
      portfolio_generation_id="";
      strategy_member_id="";
      magic_transport="0";
      program_name="";
      program_path="";
      terminal_build=0;
      is_tester=false;
      is_optimization=false;
      is_forward=false;
      is_visual=false;
      bookkeeping_mode=V2_BOOKKEEPING_AUTO;
      persistence_backend="";
      input_schema_hash="";
      input_values_hash="";
      expected_source_hash="";
      expected_binary_hash="";
      external_git_commit="";
      external_source_hash="";
      external_binary_hash="";
      account_fingerprint="";
      account_server="";
      account_company="";
      account_currency="";
      account_leverage=0;
      account_margin_mode=0;
      symbol="";
      symbol_spec_hash="";
      reference_commit="";
      set_hash="";
      tick_data_hash="";
      tester_model="";
      test_window="";
      state_pack_hash="";
      calendar_hash="";
      model_bundle_hash="";
      broker_profile_version="";
      broker_profile_hash="";
      random_seed="";
      external_lineage_complete=false;
     }
  };

string V2CanonicalInputValues(void)
  {
   string payload="{";
   payload+="\"deploymentId\":"+V2JsonQuote(V2_DeploymentId)+",";
   payload+="\"portfolioGenerationId\":"+V2JsonQuote(V2_PortfolioGenerationId)+",";
   payload+="\"strategyMemberId\":"+V2JsonQuote(V2_StrategyMemberId)+",";
   payload+="\"operationMode\":"+IntegerToString((int)V2_Mode_Operation)+",";
   payload+="\"runMode\":"+IntegerToString((int)V2_RunMode)+",";
   payload+="\"enableNewRisk\":"+V2JsonBool(V2_EnableNewRisk)+",";
   payload+="\"bookkeeping\":"+IntegerToString((int)V2_Bookkeeping)+",";
   payload+="\"certificationRun\":"+V2JsonBool(V2_CertificationRun)+",";
   payload+="\"stateDatabaseName\":"+V2JsonQuote(V2_StateDatabaseName)+",";
   payload+="\"tradeDirection\":"+IntegerToString((int)V2_TradeDirection)+",";
   payload+="\"signalMode\":"+IntegerToString((int)V2_SignalMode)+",";
   payload+="\"signalTimeframe\":"+IntegerToString((int)V2_SignalTimeframe)+",";
   payload+="\"fastEmaPeriod\":"+IntegerToString(V2_FastEmaPeriod)+",";
   payload+="\"slowEmaPeriod\":"+IntegerToString(V2_SlowEmaPeriod)+",";
   payload+="\"rsiPeriod\":"+IntegerToString(V2_RsiPeriod)+",";
   payload+="\"atrPeriod\":"+IntegerToString(V2_AtrPeriod)+",";
   payload+="\"rsiLongThreshold\":"+V2CanonicalDouble(V2_RsiLongThreshold)+",";
   payload+="\"rsiShortThreshold\":"+V2CanonicalDouble(V2_RsiShortThreshold)+",";
   payload+="\"maxSequenceTrades\":"+IntegerToString(V2_MaxSequenceTrades)+",";
   payload+="\"gridSize\":"+V2CanonicalDouble(V2_GridSize)+",";
   payload+="\"gridMinimum\":"+V2CanonicalDouble(V2_GridMinimum)+",";
   payload+="\"gridMaximum\":"+V2CanonicalDouble(V2_GridMaximum)+",";
   payload+="\"gridExponent\":"+V2CanonicalDouble(V2_GridExponent)+",";
   payload+="\"gridFactor\":"+V2CanonicalDouble(V2_GridFactor)+",";
   payload+="\"takeProfitSize\":"+V2CanonicalDouble(V2_TakeProfitSize)+",";
   payload+="\"stopLossSize\":"+V2CanonicalDouble(V2_StopLossSize)+",";
   payload+="\"lockProfitSize\":"+V2CanonicalDouble(V2_LockProfitSize)+",";
   payload+="\"lockFlexibility\":"+V2CanonicalDouble(V2_LockFlexibility)+",";
   payload+="\"trailingStopSize\":"+V2CanonicalDouble(V2_TrailingStopSize)+",";
   payload+="\"closeAtMaxLevels\":"+V2JsonBool(V2_CloseAtMaxLevels)+",";
   payload+="\"enableSequenceLossHardClose\":"+V2JsonBool(V2_EnableSequenceLossHardClose)+",";
   payload+="\"cumPartialReleasePercent\":"+V2CanonicalDouble(V2_CumPartialReleasePercent)+",";
   payload+="\"peakSmartReleasePercent\":"+V2CanonicalDouble(V2_PeakSmartReleasePercent)+",";
   payload+="\"peakSmartMaxClosePercent\":"+V2CanonicalDouble(V2_PeakSmartMaxClosePercent)+",";
   payload+="\"lotMode\":"+IntegerToString((int)V2_LotMode)+",";
   payload+="\"lotProgression\":"+IntegerToString((int)V2_LotProgression)+",";
   payload+="\"startLots\":"+V2CanonicalDouble(V2_StartLots)+",";
   payload+="\"riskPerSequence\":"+V2CanonicalDouble(V2_RiskPerSequence)+",";
   payload+="\"lotExponent\":"+V2CanonicalDouble(V2_LotExponent)+",";
   payload+="\"lotFactor\":"+V2CanonicalDouble(V2_LotFactor)+",";
   payload+="\"maxTradeMultiple\":"+V2CanonicalDouble(V2_MaxTradeMultiple)+",";
   payload+="\"maxCumulativeMultiple\":"+V2CanonicalDouble(V2_MaxCumulativeMultiple)+",";
   payload+="\"peakPositionPercent\":"+V2CanonicalDouble(V2_PeakPositionPercent)+",";
   payload+="\"maxSpreadPoints\":"+V2CanonicalDouble(V2_MaxSpreadPoints)+",";
   payload+="\"additionalMarginBufferPct\":"+V2CanonicalDouble(V2_AdditionalMarginBufferPct)+",";
   payload+="\"maxSymbolLots\":"+V2CanonicalDouble(V2_MaxSymbolLots)+",";
   payload+="\"maxPortfolioLots\":"+V2CanonicalDouble(V2_MaxPortfolioLots)+",";
   payload+="\"maxSequenceLoss\":"+V2CanonicalDouble(V2_MaxSequenceLoss)+",";
   payload+="\"equityFloor\":"+V2CanonicalDouble(V2_EquityFloor)+",";
   payload+="\"maxEquityDrawdownPct\":"+V2CanonicalDouble(V2_MaxEquityDrawdownPct)+",";
   payload+="\"maxConsecutiveBrokerErrors\":"+IntegerToString(V2_MaxConsecutiveBrokerErrors)+",";
   payload+="\"brokerProfileId\":"+V2JsonQuote(V2_BrokerProfileId)+",";
   payload+="\"brokerProfileVersion\":"+V2JsonQuote(V2_BrokerProfileVersion)+",";
   payload+="\"commissionOpenPerLot\":"+V2CanonicalDouble(V2_CommissionOpenPerLot)+",";
   payload+="\"commissionClosePerLot\":"+V2CanonicalDouble(V2_CommissionClosePerLot)+",";
   payload+="\"swapLongPerLotDay\":"+V2CanonicalDouble(V2_SwapLongPerLotDay)+",";
   payload+="\"swapShortPerLotDay\":"+V2CanonicalDouble(V2_SwapShortPerLotDay)+",";
   payload+="\"projectedHoldingDays\":"+V2CanonicalDouble(V2_ProjectedHoldingDays)+",";
   payload+="\"projectedTripleSwapEvents\":"+IntegerToString(V2_ProjectedTripleSwapEvents)+",";
   payload+="\"stressedSpreadPoints\":"+V2CanonicalDouble(V2_StressedSpreadPoints)+",";
   payload+="\"openSlippagePoints\":"+V2CanonicalDouble(V2_OpenSlippagePoints)+",";
   payload+="\"closeSlippagePoints\":"+V2CanonicalDouble(V2_CloseSlippagePoints)+",";
   payload+="\"terminalAdversePoints\":"+V2CanonicalDouble(V2_TerminalAdversePoints)+",";
   payload+="\"stateMode\":"+IntegerToString((int)V2_StateMode)+",";
   payload+="\"onnxMode\":"+IntegerToString((int)V2_OnnxMode)+",";
   payload+="\"enableHud\":"+V2JsonBool(V2_EnableHud)+",";
   payload+="\"enableOverlay\":"+V2JsonBool(V2_EnableOverlay)+",";
   payload+="\"enableTelemetry\":"+V2JsonBool(V2_EnableTelemetry);
   payload+="}";
   return payload;
  }

string V2InputSchemaHash(void)
  {
   const string schema=
      "goat2-inputs-v2|deploymentId|portfolioGenerationId|strategyMemberId|operationMode|runMode|enableNewRisk|bookkeeping|certificationRun|stateDatabaseName|"
      "tradeDirection|signalMode|signalTimeframe|fastEmaPeriod|slowEmaPeriod|rsiPeriod|atrPeriod|rsiLongThreshold|"
      "rsiShortThreshold|maxSequenceTrades|gridSize|gridMinimum|gridMaximum|gridExponent|gridFactor|takeProfitSize|stopLossSize|"
      "lockProfitSize|lockFlexibility|trailingStopSize|closeAtMaxLevels|enableSequenceLossHardClose|cumPartialReleasePercent|peakSmartReleasePercent|peakSmartMaxClosePercent|lotMode|lotProgression|startLots|riskPerSequence|lotExponent|lotFactor|"
      "maxTradeMultiple|maxCumulativeMultiple|peakPositionPercent|maxSpreadPoints|additionalMarginBufferPct|"
      "maxSymbolLots|maxPortfolioLots|maxSequenceLoss|equityFloor|maxEquityDrawdownPct|maxConsecutiveBrokerErrors|"
      "brokerProfileId|brokerProfileVersion|commissionOpenPerLot|commissionClosePerLot|swapLongPerLotDay|swapShortPerLotDay|"
      "projectedHoldingDays|projectedTripleSwapEvents|stressedSpreadPoints|openSlippagePoints|closeSlippagePoints|terminalAdversePoints|"
      "stateMode|onnxMode|enableHud|enableOverlay|enableTelemetry";
   return V2Sha256Hex(schema);
  }

string V2CanonicalSymbolSpecification(const string symbol)
  {
   string payload="{";
   payload+="\"symbol\":"+V2JsonQuote(symbol)+",";
   payload+="\"digits\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_DIGITS))+",";
   payload+="\"point\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_POINT))+",";
   payload+="\"tickSize\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE))+",";
   payload+="\"tickValue\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE))+",";
   payload+="\"contractSize\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_TRADE_CONTRACT_SIZE))+",";
   payload+="\"volumeMin\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN))+",";
   payload+="\"volumeMax\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX))+",";
   payload+="\"volumeStep\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP))+",";
   payload+="\"volumeLimit\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_VOLUME_LIMIT))+",";
   payload+="\"stopsLevel\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL))+",";
   payload+="\"freezeLevel\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL))+",";
   payload+="\"tradeMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_TRADE_MODE))+",";
   payload+="\"executionMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE))+",";
   payload+="\"calculationMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_TRADE_CALC_MODE))+",";
   payload+="\"fillingMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE))+",";
   payload+="\"orderMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_ORDER_MODE))+",";
   payload+="\"currencyBase\":"+V2JsonQuote(SymbolInfoString(symbol,SYMBOL_CURRENCY_BASE))+",";
   payload+="\"currencyProfit\":"+V2JsonQuote(SymbolInfoString(symbol,SYMBOL_CURRENCY_PROFIT))+",";
   payload+="\"currencyMargin\":"+V2JsonQuote(SymbolInfoString(symbol,SYMBOL_CURRENCY_MARGIN))+",";
   payload+="\"swapMode\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_SWAP_MODE))+",";
   payload+="\"swapLong\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_SWAP_LONG))+",";
   payload+="\"swapShort\":"+V2CanonicalDouble(SymbolInfoDouble(symbol,SYMBOL_SWAP_SHORT))+",";
   payload+="\"swapRollover3Days\":"+IntegerToString(SymbolInfoInteger(symbol,SYMBOL_SWAP_ROLLOVER3DAYS));
   payload+="}";
   return payload;
  }

string V2CanonicalBrokerProfileInputs(void)
  {
   string payload="{";
   payload+="\"profileId\":"+V2JsonQuote(V2_BrokerProfileId)+",";
   payload+="\"version\":"+V2JsonQuote(V2_BrokerProfileVersion)+",";
   payload+="\"commissionOpenPerLot\":"+V2CanonicalDouble(V2_CommissionOpenPerLot)+",";
   payload+="\"commissionClosePerLot\":"+V2CanonicalDouble(V2_CommissionClosePerLot)+",";
   payload+="\"swapLongPerLotDay\":"+V2CanonicalDouble(V2_SwapLongPerLotDay)+",";
   payload+="\"swapShortPerLotDay\":"+V2CanonicalDouble(V2_SwapShortPerLotDay)+",";
   payload+="\"projectedHoldingDays\":"+V2CanonicalDouble(V2_ProjectedHoldingDays)+",";
   payload+="\"projectedTripleSwapEvents\":"+IntegerToString(V2_ProjectedTripleSwapEvents)+",";
   payload+="\"stressedSpreadPoints\":"+V2CanonicalDouble(V2_StressedSpreadPoints)+",";
   payload+="\"openSlippagePoints\":"+V2CanonicalDouble(V2_OpenSlippagePoints)+",";
   payload+="\"closeSlippagePoints\":"+V2CanonicalDouble(V2_CloseSlippagePoints)+",";
   payload+="\"terminalAdversePoints\":"+V2CanonicalDouble(V2_TerminalAdversePoints);
   payload+="}";
   return payload;
  }

bool V2StringsEqualNoCase(string left,string right)
  {
   StringToUpper(left);
   StringToUpper(right);
   return left==right;
  }

bool V2BookkeepingForPersistenceBackend(const string persistence_backend,
                                        ENUM_V2_BOOKKEEPING_MODE &actual_mode)
  {
   if(V2StringsEqualNoCase(persistence_backend,"REDUCED_MEMORY"))
     {
      actual_mode=V2_BOOKKEEPING_REDUCED;
      return true;
     }
   if(V2StringsEqualNoCase(persistence_backend,"FULL_MEMORY") ||
      V2StringsEqualNoCase(persistence_backend,"FULL_DURABLE"))
     {
      actual_mode=V2_BOOKKEEPING_FULL;
      return true;
     }
   actual_mode=V2_BOOKKEEPING_AUTO;
   return false;
  }

bool V2ValidateManifestBookkeeping(const ENUM_V2_BOOKKEEPING_MODE manifest_mode,
                                   const string persistence_backend,
                                   const bool certification_manifest,
                                   string &reason)
  {
   reason="";
   ENUM_V2_BOOKKEEPING_MODE actual_mode=V2_BOOKKEEPING_AUTO;
   if(!V2BookkeepingForPersistenceBackend(persistence_backend,actual_mode))
     {
      reason="MANIFEST_PERSISTENCE_BACKEND_UNKNOWN";
      return false;
     }
   if(manifest_mode==V2_BOOKKEEPING_AUTO)
     {
      reason="MANIFEST_BOOKKEEPING_UNRESOLVED";
      return false;
     }
   if(manifest_mode!=actual_mode)
     {
      reason="MANIFEST_BOOKKEEPING_BACKEND_MISMATCH";
      return false;
     }
   if(certification_manifest && actual_mode!=V2_BOOKKEEPING_FULL)
     {
      reason="CERTIFICATION_REQUIRES_FULL_BOOKKEEPING";
      return false;
     }
   return true;
  }

class CV2ExperimentManifest
  {
private:
   string CanonicalPayload(const V2ExperimentManifest &manifest) const
     {
      string payload="{";
      payload+="\"schemaVersion\":"+V2JsonQuote(manifest.schema_version)+",";
      payload+="\"productVersion\":"+V2JsonQuote(manifest.product_version)+",";
      payload+="\"buildId\":"+V2JsonQuote(manifest.build_id)+",";
      payload+="\"manifestClass\":"+IntegerToString((int)manifest.manifest_class)+",";
      payload+="\"createdAtMsc\":"+IntegerToString(manifest.created_at_msc)+",";
      payload+="\"deploymentId\":"+V2JsonQuote(manifest.deployment_id)+",";
      payload+="\"portfolioGenerationId\":"+V2JsonQuote(manifest.portfolio_generation_id)+",";
      payload+="\"strategyMemberId\":"+V2JsonQuote(manifest.strategy_member_id)+",";
      payload+="\"magic\":"+V2JsonQuote(manifest.magic_transport)+",";
      payload+="\"programName\":"+V2JsonQuote(manifest.program_name)+",";
      payload+="\"programPath\":"+V2JsonQuote(manifest.program_path)+",";
      payload+="\"terminalBuild\":"+IntegerToString(manifest.terminal_build)+",";
      payload+="\"isTester\":"+V2JsonBool(manifest.is_tester)+",";
      payload+="\"isOptimization\":"+V2JsonBool(manifest.is_optimization)+",";
      payload+="\"isForward\":"+V2JsonBool(manifest.is_forward)+",";
      payload+="\"isVisual\":"+V2JsonBool(manifest.is_visual)+",";
      payload+="\"bookkeepingMode\":"+IntegerToString((int)manifest.bookkeeping_mode)+",";
      payload+="\"persistenceBackend\":"+V2JsonQuote(manifest.persistence_backend)+",";
      payload+="\"inputSchemaHash\":"+V2JsonQuote(manifest.input_schema_hash)+",";
      payload+="\"inputValuesHash\":"+V2JsonQuote(manifest.input_values_hash)+",";
      payload+="\"expectedSourceHash\":"+V2JsonQuote(manifest.expected_source_hash)+",";
      payload+="\"expectedBinaryHash\":"+V2JsonQuote(manifest.expected_binary_hash)+",";
      payload+="\"externalGitCommit\":"+V2JsonQuote(manifest.external_git_commit)+",";
      payload+="\"externalSourceHash\":"+V2JsonQuote(manifest.external_source_hash)+",";
      payload+="\"externalBinaryHash\":"+V2JsonQuote(manifest.external_binary_hash)+",";
      payload+="\"accountFingerprint\":"+V2JsonQuote(manifest.account_fingerprint)+",";
      payload+="\"accountServer\":"+V2JsonQuote(manifest.account_server)+",";
      payload+="\"accountCompany\":"+V2JsonQuote(manifest.account_company)+",";
      payload+="\"accountCurrency\":"+V2JsonQuote(manifest.account_currency)+",";
      payload+="\"accountLeverage\":"+IntegerToString(manifest.account_leverage)+",";
      payload+="\"accountMarginMode\":"+IntegerToString(manifest.account_margin_mode)+",";
      payload+="\"symbol\":"+V2JsonQuote(manifest.symbol)+",";
      payload+="\"symbolSpecHash\":"+V2JsonQuote(manifest.symbol_spec_hash)+",";
      payload+="\"referenceCommit\":"+V2JsonQuote(manifest.reference_commit)+",";
      payload+="\"setHash\":"+V2JsonQuote(manifest.set_hash)+",";
      payload+="\"tickDataHash\":"+V2JsonQuote(manifest.tick_data_hash)+",";
      payload+="\"testerModel\":"+V2JsonQuote(manifest.tester_model)+",";
      payload+="\"testWindow\":"+V2JsonQuote(manifest.test_window)+",";
      payload+="\"statePackHash\":"+V2JsonQuote(manifest.state_pack_hash)+",";
      payload+="\"calendarHash\":"+V2JsonQuote(manifest.calendar_hash)+",";
      payload+="\"modelBundleHash\":"+V2JsonQuote(manifest.model_bundle_hash)+",";
      payload+="\"brokerProfileVersion\":"+V2JsonQuote(manifest.broker_profile_version)+",";
      payload+="\"brokerProfileHash\":"+V2JsonQuote(manifest.broker_profile_hash)+",";
      payload+="\"randomSeed\":"+V2JsonQuote(manifest.random_seed)+",";
      payload+="\"externalLineageComplete\":"+V2JsonBool(manifest.external_lineage_complete);
      payload+="}";
      return payload;
     }

public:
   bool CaptureRuntime(const CV2Identity &identity,
                       const string product_version,
                       const string build_id,
                       const ENUM_V2_MANIFEST_CLASS manifest_class,
                       const ENUM_V2_BOOKKEEPING_MODE bookkeeping_mode,
                       const string persistence_backend,
                       V2ExperimentManifest &manifest,
                       string &reason) const
     {
      reason="";
      if(identity.DeploymentId()=="" || identity.MemberId()=="")
        {
         reason="MANIFEST_IDENTITY_NOT_INITIALIZED";
         return false;
        }
      if(product_version=="" || build_id=="" || persistence_backend=="")
        {
         reason="MANIFEST_BUILD_OR_PERSISTENCE_IDENTITY_EMPTY";
         return false;
        }
      if(V2_CertificationRun && manifest_class!=V2_MANIFEST_CERTIFICATION)
        {
         reason="CERTIFICATION_RUN_REQUIRES_CERTIFICATION_MANIFEST";
         return false;
        }
      ENUM_V2_BOOKKEEPING_MODE actual_bookkeeping=V2_BOOKKEEPING_AUTO;
      if(!V2BookkeepingForPersistenceBackend(persistence_backend,actual_bookkeeping))
        {
         reason="MANIFEST_PERSISTENCE_BACKEND_UNKNOWN";
         return false;
        }
      if(bookkeeping_mode!=V2_BOOKKEEPING_AUTO && bookkeeping_mode!=actual_bookkeeping)
        {
         reason="MANIFEST_BOOKKEEPING_BACKEND_MISMATCH";
         return false;
        }
      if(!V2ValidateManifestBookkeeping(actual_bookkeeping,
                                        persistence_backend,
                                        manifest_class==V2_MANIFEST_CERTIFICATION || V2_CertificationRun,
                                        reason))
         return false;
      manifest.Reset();
      manifest.product_version=product_version;
      manifest.build_id=build_id;
      manifest.manifest_class=manifest_class;
      manifest.created_at_msc=V2UtcNowMsc();
      manifest.deployment_id=identity.DeploymentId();
      manifest.portfolio_generation_id=identity.GenerationId();
      manifest.strategy_member_id=identity.MemberId();
      manifest.magic_transport=identity.MagicTransport();
      manifest.program_name=MQLInfoString(MQL_PROGRAM_NAME);
      manifest.program_path=MQLInfoString(MQL_PROGRAM_PATH);
      manifest.terminal_build=TerminalInfoInteger(TERMINAL_BUILD);
      manifest.is_tester=(bool)MQLInfoInteger(MQL_TESTER);
      manifest.is_optimization=(bool)MQLInfoInteger(MQL_OPTIMIZATION);
      manifest.is_forward=(bool)MQLInfoInteger(MQL_FORWARD);
      manifest.is_visual=(bool)MQLInfoInteger(MQL_VISUAL_MODE);
      // The backend is the observed runtime truth.  AUTO is resolved from it;
      // an explicit request must agree with it and certification never rewrites
      // a reduced backend to look full.
      manifest.bookkeeping_mode=actual_bookkeeping;
      manifest.persistence_backend=persistence_backend;
      manifest.input_schema_hash=V2InputSchemaHash();
      manifest.input_values_hash=V2Sha256Hex(V2CanonicalInputValues());
      manifest.expected_source_hash=V2_ExpectedSourceHash;
      manifest.expected_binary_hash=V2_ExpectedBinaryHash;
      manifest.account_server=AccountInfoString(ACCOUNT_SERVER);
      manifest.account_company=AccountInfoString(ACCOUNT_COMPANY);
      manifest.account_currency=AccountInfoString(ACCOUNT_CURRENCY);
      manifest.account_leverage=AccountInfoInteger(ACCOUNT_LEVERAGE);
      manifest.account_margin_mode=(int)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
      manifest.account_fingerprint=V2Sha256Hex(manifest.account_server+"|"+
                                               IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));
      manifest.symbol=_Symbol;
      manifest.symbol_spec_hash=V2Sha256Hex(V2CanonicalSymbolSpecification(_Symbol));
      manifest.broker_profile_version=V2_BrokerProfileId+"@"+V2_BrokerProfileVersion;
      manifest.broker_profile_hash=V2Sha256Hex(V2CanonicalBrokerProfileInputs());
      return true;
     }

   void AttachExternalLineage(const V2ExternalLineage &lineage,V2ExperimentManifest &manifest) const
     {
      manifest.external_git_commit=lineage.git_commit;
      manifest.external_source_hash=lineage.source_hash;
      manifest.external_binary_hash=lineage.binary_hash;
      manifest.reference_commit=lineage.reference_commit;
      manifest.set_hash=lineage.set_hash;
      manifest.tick_data_hash=lineage.tick_data_hash;
      manifest.tester_model=lineage.tester_model;
      manifest.test_window=lineage.test_window;
      manifest.state_pack_hash=lineage.state_pack_hash;
      manifest.calendar_hash=lineage.calendar_hash;
      manifest.model_bundle_hash=lineage.model_bundle_hash;
      if(lineage.broker_profile_version!="") manifest.broker_profile_version=lineage.broker_profile_version;
      if(lineage.broker_profile_hash!="") manifest.broker_profile_hash=lineage.broker_profile_hash;
      manifest.random_seed=lineage.random_seed;
     }

   bool ValidateForCertification(V2ExperimentManifest &manifest,string &reason) const
     {
      reason="";
      manifest.external_lineage_complete=false;
      if(manifest.manifest_class!=V2_MANIFEST_CERTIFICATION)
        { reason="CERTIFICATION_MANIFEST_CLASS_REQUIRED"; return false; }
      if(!V2ValidateManifestBookkeeping(manifest.bookkeeping_mode,
                                        manifest.persistence_backend,
                                        true,
                                        reason))
         return false;
      if(manifest.external_git_commit=="")
        { reason="CERTIFICATION_GIT_COMMIT_MISSING"; return false; }
      if(manifest.external_source_hash=="")
        { reason="CERTIFICATION_SOURCE_HASH_MISSING"; return false; }
      if(manifest.external_binary_hash=="")
        { reason="CERTIFICATION_BINARY_HASH_MISSING"; return false; }
      if(manifest.reference_commit=="")
        { reason="CERTIFICATION_REFERENCE_COMMIT_MISSING"; return false; }
      if(manifest.set_hash=="")
        { reason="CERTIFICATION_SET_HASH_MISSING"; return false; }
      if(manifest.tick_data_hash=="")
        { reason="CERTIFICATION_TICK_DATA_HASH_MISSING"; return false; }
      if(manifest.tester_model=="" || manifest.test_window=="")
        { reason="CERTIFICATION_TEST_CONFIGURATION_MISSING"; return false; }
      if(manifest.broker_profile_version=="" || manifest.broker_profile_hash=="")
        { reason="CERTIFICATION_BROKER_PROFILE_MISSING"; return false; }
      if(manifest.expected_source_hash!="" &&
         !V2StringsEqualNoCase(manifest.expected_source_hash,manifest.external_source_hash))
        { reason="CERTIFICATION_SOURCE_HASH_MISMATCH"; return false; }
      if(manifest.expected_binary_hash!="" &&
         !V2StringsEqualNoCase(manifest.expected_binary_hash,manifest.external_binary_hash))
        { reason="CERTIFICATION_BINARY_HASH_MISMATCH"; return false; }
      if(V2_StateMode!=V2_STATE_DISABLED && manifest.state_pack_hash=="")
        { reason="CERTIFICATION_STATE_PACK_HASH_MISSING"; return false; }
      if(V2_OnnxMode!=V2_ONNX_DISABLED && manifest.model_bundle_hash=="")
        { reason="CERTIFICATION_MODEL_BUNDLE_HASH_MISSING"; return false; }
      manifest.external_lineage_complete=true;
      return true;
     }

   bool Finalize(V2ExperimentManifest &manifest,string &reason) const
     {
      reason="";
      if(manifest.manifest_class==V2_MANIFEST_CERTIFICATION && !manifest.external_lineage_complete)
        {
         reason="CERTIFICATION_MANIFEST_NOT_VALIDATED";
         return false;
        }
      manifest.canonical_payload=CanonicalPayload(manifest);
      manifest.manifest_hash=V2Sha256Hex(manifest.canonical_payload);
      if(manifest.manifest_hash=="")
        {
         reason="MANIFEST_HASH_FAILED";
         return false;
        }
      manifest.manifest_id="exp_"+manifest.manifest_hash;
      return true;
     }

   string Serialize(const V2ExperimentManifest &manifest) const
     {
      return CanonicalPayload(manifest);
     }
  };

#endif
