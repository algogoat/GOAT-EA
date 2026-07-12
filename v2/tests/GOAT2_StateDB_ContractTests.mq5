#property copyright "GOATedge.ai"
#property version   "2.00"
#property strict
#property tester_no_cache

#include "../StateDB.mqh"

int    g_checks=0;
int    g_passed=0;
int    g_failed=0;
string g_last_failure="";

void Check(const bool condition,const string name,const string detail="")
  {
   g_checks++;
   if(condition)
     {
      g_passed++;
      Print("GOAT2_STATE_DB_TEST|PASS|",name);
      return;
     }
   g_failed++;
   g_last_failure=name+(detail=="" ? "" : ":"+detail);
   Print("GOAT2_STATE_DB_TEST|FAIL|",name,(detail=="" ? "" : "|"+detail));
  }

string UniqueSuffix(void)
  {
   return IntegerToString((long)V2UtcNow())+"_"+V2UlongToText(GetMicrosecondCount());
  }

void RemoveCommonTestFiles(const string database_path,const string lease_path)
  {
   ResetLastError();
   FileDelete(database_path,FILE_COMMON);
   FileDelete(database_path+"-journal",FILE_COMMON);
   FileDelete(database_path+"-wal",FILE_COMMON);
   FileDelete(database_path+"-shm",FILE_COMMON);
   FileDelete(lease_path,FILE_COMMON);
  }

void TestExclusiveAnsiLease(void)
  {
   const string lease_path="GOAT2\\tests\\state-db-lease-"+UniqueSuffix()+".lease";
   CV2WriterLease owner_a;
   CV2WriterLease owner_b;
   string reason_a="",reason_b="";

   const bool acquired_a=owner_a.Acquire(lease_path,"OWNER_A",reason_a);
   Check(acquired_a && owner_a.IsHeld(),"lease.owner_a_acquires",reason_a);

   const bool acquired_b_while_a=owner_b.Acquire(lease_path,"OWNER_B",reason_b);
   Check(!acquired_b_while_a && !owner_b.IsHeld(),
         "lease.owner_b_denied_while_a_holds",reason_b);

   owner_a.Release();
   reason_b="";
   const bool acquired_b_after_release=owner_b.Acquire(lease_path,"OWNER_B",reason_b);
   Check(acquired_b_after_release && owner_b.IsHeld(),
         "lease.owner_b_acquires_after_release",reason_b);
   owner_b.Release();
   FileDelete(lease_path,FILE_COMMON);
  }

void TestExplicitReadOnlyDeniesMutation(void)
  {
   const string suffix=UniqueSuffix();
   V2StateDBConfig config;
   config.Reset();
   config.mode=V2_DB_FULL_DURABLE;
   config.database_path="GOAT2\\tests\\state-db-contract-"+suffix+".sqlite";
   config.lease_path="GOAT2\\tests\\state-db-contract-"+suffix+".lease";
   config.deployment_id="state-db-contract-deployment";
   config.portfolio_generation_id="state-db-contract-generation";
   config.strategy_member_id="state-db-contract-member";
   config.owner_instance_id="state-db-contract-writer-"+suffix;
   config.lease_stale_seconds=30;
   config.schema_version=V2_STATE_DB_SCHEMA_VERSION;
   RemoveCommonTestFiles(config.database_path,config.lease_path);

   CV2StateDB writer;
   string reason="";
   const bool writer_open=writer.Open(config,reason);
   Check(writer_open && writer.IsWritable() && writer.BrokerMutationAllowed(),
         "readonly_fixture.writer_opens",reason);
   if(writer_open)
     {
      long reserved=0;
      reason="";
      Check(writer.ReserveCounter("contract_seed",reserved,reason) && reserved==1,
            "readonly_fixture.writer_mutates",reason);
     }
   writer.Close();

   CV2StateDB reader;
   reason="";
   const bool reader_open=reader.OpenReadOnlyRecovery(config,
                                                       "CONTRACT_TEST_EXPLICIT_READ_ONLY",
                                                       reason);
   Check(reader_open && reader.IsOpen() && reader.IsReadOnlyRecovery() &&
         reader.AccessMode()==V2_DB_ACCESS_READ_ONLY_RECOVERY &&
         !reader.IsWritable() && !reader.BrokerMutationAllowed(),
         "readonly.explicit_access_contract",
         (reader_open ? reader.StatusReason() : reason));
   if(reader_open)
     {
      long canonical_number=0;
      reason="";
      Check(reader.GetLastCanonicalNumber(canonical_number,reason) && canonical_number==0,
            "readonly.read_path_remains_available",reason);

      V2StateDBMemberSnapshot snapshot;
      reason="";
      Check(reader.CreateMemberSnapshot(config.strategy_member_id,snapshot,reason) &&
            snapshot.strategy_member_id==config.strategy_member_id &&
            snapshot.projection_lineage_valid,
            "readonly.member_snapshot_available",reason);

      long denied_counter=0;
      reason="";
      const bool mutation_allowed=reader.ReserveCounter("readonly_must_fail",denied_counter,reason);
      Check(!mutation_allowed && StringFind(reason,"DATABASE_NOT_WRITABLE")>=0,
            "readonly.counter_mutation_denied",reason);

      reason="";
      const bool metadata_write_allowed=reader.StoreRiskHighWater("readonly_must_fail",1.0,reason);
      Check(!metadata_write_allowed && StringFind(reason,"DATABASE_NOT_WRITABLE")>=0,
            "readonly.metadata_mutation_denied",reason);

      reason="";
      Check(reader.AuditJournalFromGenesis(reason) && reader.JournalAuditVerified(),
            "readonly.full_journal_audit_available",reason);
     }
   reader.Close();
   RemoveCommonTestFiles(config.database_path,config.lease_path);
  }

bool PersistIntentFixture(CV2StateDB &database,
                          const V2StateDBConfig &config,
                          const string intent_id,
                          V2OrderIntent &intent,
                          string &reason)
  {
   intent.Reset();
   intent.order_intent_id=intent_id;
   intent.sequence_id="sequence-"+intent_id;
   intent.action=V2_ACTION_ADD;
   intent.risk_effect=V2_RISK_INCREASE;
   intent.direction=V2_DIR_LONG;
   intent.symbol=_Symbol;
   intent.magic=1234567;
   intent.level_index=0;
   intent.requested_volume=0.01;
   intent.requested_price=1.10000;
   intent.stop_loss=1.09000;
   intent.take_profit=1.11000;
   intent.created_at=V2UtcNow();
   intent.reason_code="CONTRACT_PRE_SUBMISSION";
   CV2OrderIntentMachine machine;
   if(!machine.Apply(V2_INTENT_PERSISTED,intent,reason))
      return false;

   V2Receipt receipt;
   receipt.Reset();
   receipt.kind=V2_RECEIPT_ORDER_SUBMISSION;
   receipt.occurred_at_msc=V2UtcNowMsc();
   receipt.deployment_id=config.deployment_id;
   receipt.portfolio_generation_id=config.portfolio_generation_id;
   receipt.strategy_member_id=config.strategy_member_id;
   receipt.sequence_id=intent.sequence_id;
   receipt.order_intent_id=intent.order_intent_id;
   receipt.symbol=intent.symbol;
   receipt.direction=intent.direction;
   receipt.level_index=intent.level_index;
   receipt.action=intent.action;
   receipt.risk_effect=intent.risk_effect;
   receipt.requested_volume=intent.requested_volume;
   receipt.requested_price=intent.requested_price;
   receipt.stop_loss=intent.stop_loss;
   receipt.take_profit=intent.take_profit;
   return database.PersistOrderIntentAndReceipt(intent,receipt,reason);
  }

void TestCanonicalIntentSubmissionBridge(void)
  {
   const string suffix=UniqueSuffix();
   V2StateDBConfig config;
   config.Reset();
   config.mode=V2_DB_FULL_DURABLE;
   config.database_path="GOAT2\\tests\\state-db-intent-"+suffix+".sqlite";
   config.lease_path="GOAT2\\tests\\state-db-intent-"+suffix+".lease";
   config.deployment_id="state-db-intent-deployment";
   config.portfolio_generation_id="state-db-intent-generation";
   config.strategy_member_id="state-db-intent-member";
   config.owner_instance_id="state-db-intent-writer-"+suffix;
   config.lease_stale_seconds=30;
   config.schema_version=V2_STATE_DB_SCHEMA_VERSION;
   RemoveCommonTestFiles(config.database_path,config.lease_path);

   CV2StateDB database;
   string reason="";
   const bool opened=database.Open(config,reason);
   Check(opened && database.IsWritable(),"intent_bridge.database_opens",reason);
   if(opened)
     {
      CV2OrderIntentMachine machine;
      V2OrderIntent rejected;
      reason="";
      const bool rejected_fixture=PersistIntentFixture(database,config,
                                                       "intent-rejected-"+suffix,
                                                       rejected,reason);
      Check(rejected_fixture,"intent_bridge.rejected_fixture_persisted",reason);
      if(rejected_fixture)
        {
         reason="";
         const bool staged=machine.Apply(V2_INTENT_SUBMITTED,rejected,reason) &&
                           machine.Apply(V2_INTENT_REJECTED,rejected,reason);
         rejected.request_id=1001;
         rejected.retcode=10006;
         rejected.reason_code="BROKER_REJECTED_CONTRACT_FIXTURE";
         Check(staged && database.UpdateOrderIntent(rejected,reason),
               "intent_bridge.persisted_to_rejected_replays_submitted",reason);
         reason="";
         Check(database.UpdateOrderIntent(rejected,reason),
               "intent_bridge.rejected_idempotent",reason);
        }

      V2OrderIntent uncertain;
      reason="";
      const bool uncertain_fixture=PersistIntentFixture(database,config,
                                                        "intent-uncertain-"+suffix,
                                                        uncertain,reason);
      Check(uncertain_fixture,"intent_bridge.uncertain_fixture_persisted",reason);
      if(uncertain_fixture)
        {
         reason="";
         const bool staged=machine.Apply(V2_INTENT_SUBMITTED,uncertain,reason) &&
                           machine.Apply(V2_INTENT_RECONCILE_REQUIRED,uncertain,reason);
         uncertain.request_id=1002;
         uncertain.reason_code="ORDER_SEND_UNCERTAIN_CONTRACT_FIXTURE";
         Check(staged && database.UpdateOrderIntent(uncertain,reason),
               "intent_bridge.persisted_to_uncertain_replays_submitted",reason);

         V2OrderIntent unsettled[];
         reason="";
         bool recovered=false;
         if(database.LoadUnsettledOrderIntents(100,unsettled,reason))
           {
            for(int i=0;i<ArraySize(unsettled);i++)
               if(unsettled[i].order_intent_id==uncertain.order_intent_id &&
                  unsettled[i].status==V2_INTENT_RECONCILE_REQUIRED)
                 {
                  recovered=true;
                  break;
                 }
           }
         Check(recovered,"intent_bridge.uncertain_remains_recoverable",reason);
        }

      reason="";
      const bool first_peak=database.StoreRiskHighWater("rounding_peak",1.00000000006,reason);
      Check(first_peak,"high_water.canonical_peak_stored",reason);
      reason="";
      const bool higher_raw_same_canonical=database.StoreRiskHighWater("rounding_peak",1.00000000007,reason);
      Check(higher_raw_same_canonical,
            "high_water.higher_raw_same_canonical_is_idempotent",reason);
      double loaded_peak=0.0;
      bool loaded_peak_found=false;
      reason="";
      Check(database.LoadRiskHighWater("rounding_peak",loaded_peak,loaded_peak_found,reason) &&
            loaded_peak_found && V2CanonicalDouble(loaded_peak)=="1.0000000001",
            "high_water.canonical_peak_round_trip",reason);
     }
   database.Close();
   RemoveCommonTestFiles(config.database_path,config.lease_path);
  }

void WriteSummary(void)
  {
   FolderCreate("GOAT2",FILE_COMMON);
   FolderCreate("GOAT2\\tests",FILE_COMMON);
   int handle=FileOpen("GOAT2\\tests\\state-db-contract-result.json",
                       FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
     {
      Print("GOAT2_STATE_DB_TEST|WARN|summary_file_open_failed|",GetLastError());
      return;
     }
   const string status=(g_failed==0 ? "PASS" : "FAIL");
   string json="{";
   json+="\"schemaVersion\":\"goat2-state-db-contract-result-v1\",";
   json+="\"status\":"+V2JsonQuote(status)+",";
   json+="\"checks\":"+IntegerToString(g_checks)+",";
   json+="\"passed\":"+IntegerToString(g_passed)+",";
   json+="\"failed\":"+IntegerToString(g_failed)+",";
   json+="\"lastFailure\":"+V2JsonQuote(g_last_failure)+",";
   json+="\"utcCompletedAtMsc\":"+IntegerToString(V2UtcNowMsc());
   json+="}\n";
   FileWriteString(handle,json);
   FileClose(handle);
   PrintFormat("GOAT2_STATE_DB_TEST_SUMMARY|checks=%d|passed=%d|failed=%d",
               g_checks,g_passed,g_failed);
  }

int OnInit(void)
  {
   FolderCreate("GOAT2",FILE_COMMON);
   FolderCreate("GOAT2\\tests",FILE_COMMON);
   TestExclusiveAnsiLease();
   TestExplicitReadOnlyDeniesMutation();
   TestCanonicalIntentSubmissionBridge();
   WriteSummary();
   return(g_failed==0 ? INIT_SUCCEEDED : INIT_FAILED);
  }

void OnTick(void)
  {
  }
