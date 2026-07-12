#ifndef GOAT_V2_STATE_DB_MQH
#define GOAT_V2_STATE_DB_MQH

#include "Domain.mqh"
#include "Identity.mqh"
#include "Inputs_V2.mqh"
#include "Receipts.mqh"
#include "ExperimentManifest.mqh"
#include "Clock.mqh"

enum ENUM_V2_STATE_DB_MODE
  {
   V2_DB_REDUCED=0,
   V2_DB_FULL_MEMORY=1,
   V2_DB_FULL_DURABLE=2
  };

enum ENUM_V2_PERSISTENCE_OUTCOME
  {
   V2_PERSISTENCE_DENIED=0,
   V2_PERSISTENCE_RECORDED=1
  };

enum ENUM_V2_OUTBOX_STATE
  {
   V2_OUTBOX_PENDING=0,
   V2_OUTBOX_DELIVERED=1,
   V2_OUTBOX_DEAD_LETTER=2
  };

// Schema v4 adds append-only journal guards, an inherited verification
// checkpoint, and an explicit migration ledger.  The application accepts one
// current schema only; every older version must pass a named migration step.
#define V2_STATE_DB_SCHEMA_VERSION 4
#define V2_STATE_DB_MIN_LEASE_STALE_SECONDS 5
#define V2_STATE_DB_MAX_LEASE_STALE_SECONDS 86400

enum ENUM_V2_STATE_DB_ACCESS_MODE
  {
   V2_DB_ACCESS_CLOSED=0,
   V2_DB_ACCESS_READ_ONLY_RECOVERY=1,
   V2_DB_ACCESS_READ_WRITE=2
  };

enum ENUM_V2_STATE_DB_STATUS
  {
   V2_DB_STATUS_CLOSED=0,
   V2_DB_STATUS_HEALTHY=1,
   V2_DB_STATUS_READ_ONLY_EXPLICIT=2,
   V2_DB_STATUS_READ_ONLY_SCHEMA=3,
   V2_DB_STATUS_READ_ONLY_INTEGRITY=4,
   V2_DB_STATUS_READ_ONLY_WRITE_FAILURE=5,
   V2_DB_STATUS_FAILED=6
  };

string V2StateDBAccessModeName(const ENUM_V2_STATE_DB_ACCESS_MODE mode)
  {
   switch(mode)
     {
      case V2_DB_ACCESS_CLOSED:             return "CLOSED";
      case V2_DB_ACCESS_READ_ONLY_RECOVERY: return "READ_ONLY_RECOVERY";
      case V2_DB_ACCESS_READ_WRITE:         return "READ_WRITE";
     }
   return "UNKNOWN";
  }

string V2StateDBStatusName(const ENUM_V2_STATE_DB_STATUS status)
  {
   switch(status)
     {
      case V2_DB_STATUS_CLOSED:                  return "CLOSED";
      case V2_DB_STATUS_HEALTHY:                 return "HEALTHY";
      case V2_DB_STATUS_READ_ONLY_EXPLICIT:      return "READ_ONLY_EXPLICIT";
      case V2_DB_STATUS_READ_ONLY_SCHEMA:        return "READ_ONLY_SCHEMA";
      case V2_DB_STATUS_READ_ONLY_INTEGRITY:     return "READ_ONLY_INTEGRITY";
      case V2_DB_STATUS_READ_ONLY_WRITE_FAILURE: return "READ_ONLY_WRITE_FAILURE";
      case V2_DB_STATUS_FAILED:                  return "FAILED";
     }
   return "UNKNOWN";
  }

string V2StateDBModeName(const ENUM_V2_STATE_DB_MODE mode)
  {
   switch(mode)
     {
      case V2_DB_REDUCED:      return "REDUCED_MEMORY";
      case V2_DB_FULL_MEMORY:  return "FULL_MEMORY";
      case V2_DB_FULL_DURABLE: return "FULL_DURABLE";
     }
   return "UNKNOWN";
  }

ENUM_V2_STATE_DB_MODE V2ResolveStateDBModeForContext(const ENUM_V2_BOOKKEEPING_MODE requested,
                                                     const bool certification_run,
                                                     const bool is_optimization,
                                                     const bool is_tester)
  {
   // Certification evidence is never allowed to use aggregate-only storage,
   // even when the run itself is an optimization pass.
   if(certification_run)
      return is_tester ? V2_DB_FULL_MEMORY : V2_DB_FULL_DURABLE;
   if(requested==V2_BOOKKEEPING_REDUCED)
      return V2_DB_REDUCED;
   if(requested==V2_BOOKKEEPING_FULL)
      return is_tester ? V2_DB_FULL_MEMORY : V2_DB_FULL_DURABLE;
   if(is_optimization)
      return V2_DB_REDUCED;
   if(is_tester)
      return V2_DB_FULL_MEMORY;
   return V2_DB_FULL_DURABLE;
  }

ENUM_V2_STATE_DB_MODE V2ResolveStateDBMode(const ENUM_V2_BOOKKEEPING_MODE requested)
  {
   return V2ResolveStateDBModeForContext(requested,
                                         V2_CertificationRun,
                                         (bool)MQLInfoInteger(MQL_OPTIMIZATION),
                                         (bool)MQLInfoInteger(MQL_TESTER));
  }

string V2SafeFileComponent(const string value)
  {
   string safe="";
   const int length=StringLen(value);
   for(int i=0;i<length;i++)
     {
      const ushort character=StringGetCharacter(value,i);
      const bool accepted=(character>='a' && character<='z') ||
                          (character>='A' && character<='Z') ||
                          (character>='0' && character<='9') ||
                           character=='-' || character=='_' || character=='.';
      safe+=accepted ? ShortToString(character) : "_";
     }
   return safe;
  }

struct V2StateDBConfig
  {
   ENUM_V2_STATE_DB_MODE mode;
   string                database_path;
   string                lease_path;
   string                deployment_id;
   string                portfolio_generation_id;
   string                strategy_member_id;
   string                owner_instance_id;
   int                   lease_stale_seconds;
   int                   schema_version;

   void Reset(void)
     {
      mode=V2_DB_REDUCED;
      database_path="";
      lease_path="";
      deployment_id="";
      portfolio_generation_id="";
      strategy_member_id="";
      owner_instance_id="";
      lease_stale_seconds=30;
      schema_version=V2_STATE_DB_SCHEMA_VERSION;
     }
  };

void V2BuildDefaultStateDBConfig(const CV2Identity &identity,
                                 const ENUM_V2_STATE_DB_MODE mode,
                                 V2StateDBConfig &config)
  {
   config.Reset();
   config.mode=mode;
   config.deployment_id=identity.DeploymentId();
   config.portfolio_generation_id=identity.GenerationId();
   config.strategy_member_id=identity.MemberId();
   const string account_key=StringSubstr(V2Sha256Hex(AccountInfoString(ACCOUNT_SERVER)+"|"+
                                                     IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))),0,16);
   const string deployment=V2SafeFileComponent(identity.DeploymentId());
   const string database_name=V2SafeFileComponent(V2_StateDatabaseName);
   config.database_path="GOAT2_State_"+account_key+"_"+deployment+"_"+database_name;
   config.lease_path="GOAT2_State_"+account_key+"_"+deployment+".lease";
   config.owner_instance_id="owner_"+V2Sha256Hex(identity.DeploymentId()+"|"+
                                                   MQLInfoString(MQL_PROGRAM_PATH)+"|"+
                                                   IntegerToString(ChartID())+"|"+
                                                   IntegerToString((long)V2UtcNow())+"|"+
                                                   V2UlongToText(GetMicrosecondCount()));
  }

struct V2PersistenceAuthorization
  {
   ENUM_V2_PERSISTENCE_OUTCOME outcome;
   bool                        broker_submission_allowed;
   bool                        durable;
   bool                        requires_manage_only;
   string                      reason;

   void Reset(void)
     {
      outcome=V2_PERSISTENCE_DENIED;
      broker_submission_allowed=false;
      durable=false;
      requires_manage_only=false;
      reason="";
     }
  };

struct V2TradeObservation
  {
   string observation_id;
   long   captured_at_msc;
   int    transaction_type;
   ulong  request_id;
   ulong  order_ticket;
   ulong  deal_ticket;
   ulong  position_id;
   ulong  position_by_id;
   string symbol;
   int    order_type;
   int    order_state;
   int    deal_type;
   double volume;
   double price;
   double stop_loss;
   double take_profit;
   uint   retcode;
   uint   retcode_external;
   string comment;

   void Reset(void)
     {
      observation_id="";
      captured_at_msc=0;
      transaction_type=0;
      request_id=0;
      order_ticket=0;
      deal_ticket=0;
      position_id=0;
      position_by_id=0;
      symbol="";
      order_type=0;
      order_state=0;
      deal_type=0;
      volume=0.0;
      price=0.0;
      stop_loss=0.0;
      take_profit=0.0;
      retcode=0;
      retcode_external=0;
      comment="";
     }
  };

struct V2OutboxRecord
  {
   string message_id;
   string message_kind;
   string payload;
   string payload_hash;
   long   created_at_msc;
   long   next_attempt_msc;
   int    attempts;
   int    priority;
   bool   critical;
   ENUM_V2_OUTBOX_STATE state;
   string last_error;

   void Reset(void)
     {
      message_id="";
      message_kind="";
      payload="";
      payload_hash="";
      created_at_msc=0;
      next_attempt_msc=0;
      attempts=0;
      priority=0;
      critical=false;
      state=V2_OUTBOX_PENDING;
      last_error="";
     }
  };

// A recovery snapshot is deliberately scoped to exactly one configured
// strategy member.  It is an audit description, not a database copy and not a
// license to rebuild projections from guesses.
struct V2StateDBMemberSnapshot
  {
   string strategy_member_id;
   long   sequence_count;
   long   manageable_sequence_count;
   long   event_count;
   long   intent_count;
   long   unsettled_intent_count;
   long   observation_count;
   long   unprocessed_observation_count;
   long   last_canonical_number;
   string last_event_hash;
   bool   projection_lineage_valid;
   string audit_reason;
   string snapshot_hash;

   void Reset(void)
     {
      strategy_member_id="";
      sequence_count=0;
      manageable_sequence_count=0;
      event_count=0;
      intent_count=0;
      unsettled_intent_count=0;
      observation_count=0;
      unprocessed_observation_count=0;
      last_canonical_number=0;
      last_event_hash="";
      projection_lineage_valid=false;
      audit_reason="";
      snapshot_hash="";
     }
  };

struct V2StateDBMemberRepairPlan
  {
   string strategy_member_id;
   string snapshot_hash;
   string requested_reason;
   bool   online_apply_allowed;
   string plan_hash;

   void Reset(void)
     {
      strategy_member_id="";
      snapshot_hash="";
      requested_reason="";
      online_apply_allowed=false;
      plan_hash="";
     }
  };

class CV2WriterLease
  {
private:
   int    m_handle;
   string m_path;

public:
                     CV2WriterLease(void)
     {
      m_handle=INVALID_HANDLE;
      m_path="";
     }

                    ~CV2WriterLease(void)
     {
      Release();
     }

   bool Acquire(const string path,const string owner_instance_id,string &reason)
     {
      reason="";
      Release();
      ResetLastError();
      // Intentionally omit FILE_SHARE_READ and FILE_SHARE_WRITE. The open
      // handle itself is the process-lifetime exclusion sentinel.
      m_handle=FileOpen(path,FILE_READ|FILE_WRITE|FILE_BIN|FILE_ANSI|FILE_COMMON);
      if(m_handle==INVALID_HANDLE)
        {
         reason="LEASE_EXCLUSIVE_OPEN_FAILED:"+IntegerToString(GetLastError());
         return false;
        }
      m_path=path;
      FileSeek(m_handle,0,SEEK_SET);
      uchar owner_bytes[];
      const int converted=StringToCharArray(owner_instance_id,owner_bytes,0,WHOLE_ARRAY,CP_UTF8);
      const uint character_count=(uint)StringLen(owner_instance_id);
      const uint byte_count=(converted>0 ? (uint)(converted-1) : 0);
      ResetLastError();
      const uint written=FileWriteString(m_handle,owner_instance_id);
      const int write_error=GetLastError();
      FileFlush(m_handle);
      const ulong persisted_size=FileSize(m_handle);
      const bool count_valid=(written==character_count || written==byte_count);
      if(character_count==0 || byte_count==0 || written==0 || !count_valid || persisted_size<byte_count)
        {
         reason="LEASE_OWNER_WRITE_FAILED:"+IntegerToString(write_error);
         Release();
         return false;
        }
      return true;
     }

   void Release(void)
     {
      if(m_handle!=INVALID_HANDLE)
         FileClose(m_handle);
      m_handle=INVALID_HANDLE;
      m_path="";
     }

   bool IsHeld(void) const { return m_handle!=INVALID_HANDLE; }
   string Path(void) const { return m_path; }
  };

class CV2StateDB
  {
private:
   int                 m_database;
   bool                m_open;
   bool                m_writable;
   bool                m_in_transaction;
   ENUM_V2_STATE_DB_ACCESS_MODE m_access_mode;
   ENUM_V2_STATE_DB_STATUS      m_status;
   V2StateDBConfig     m_config;
   CV2WriterLease      m_lease;
   string              m_last_error;
   string              m_status_reason;
   string              m_last_event_hash;
   string              m_transaction_start_event_hash;
   long                m_transaction_start_checkpoint_number;
   string              m_transaction_start_checkpoint_hash;
   bool                m_transaction_start_checkpoint_inherited;
   long                m_verified_checkpoint_number;
   string              m_verified_checkpoint_hash;
   bool                m_checkpoint_inherited;
   long                m_outbox_max_messages;
   long                m_outbox_max_bytes;

   bool SetFailure(const string reason)
     {
      m_last_error=reason;
      m_status_reason=reason;
      if(m_access_mode!=V2_DB_ACCESS_READ_ONLY_RECOVERY)
         m_status=V2_DB_STATUS_FAILED;
      return false;
     }

   bool RequireReadable(string &reason) const
     {
      if(!m_open || m_database==INVALID_HANDLE)
        {
         reason="DATABASE_NOT_OPEN";
         return false;
        }
      return true;
     }

   bool RequireWritable(string &reason) const
     {
      if(!m_open || !m_writable || m_access_mode!=V2_DB_ACCESS_READ_WRITE ||
         m_database==INVALID_HANDLE)
        {
         reason="DATABASE_NOT_WRITABLE:"+V2StateDBAccessModeName(m_access_mode);
         return false;
        }
      if(m_config.mode==V2_DB_FULL_DURABLE && !m_lease.IsHeld())
        {
         reason="WRITER_LEASE_NOT_HELD";
         return false;
        }
      return true;
     }

   void PoisonWrites(const string reason)
     {
      m_writable=false;
      m_access_mode=(m_open ? V2_DB_ACCESS_READ_ONLY_RECOVERY : V2_DB_ACCESS_CLOSED);
      m_status=(m_open ? V2_DB_STATUS_READ_ONLY_WRITE_FAILURE : V2_DB_STATUS_FAILED);
      m_last_error=reason;
      m_status_reason=reason;
      // Keep an already-held sentinel until Close(): releasing it inside a
      // failed transaction would let a second writer race the rollback.  The
      // logical access mode and writable latch revoke broker authority even
      // while the poisoned instance conservatively retains file exclusion.
     }

   bool CheckOutboxCapacity(const long additional_messages,
                            const long additional_bytes,
                            string &reason)
     {
      long pending_count=0,pending_bytes=0;
      int request=DatabasePrepare(m_database,
         "SELECT COUNT(*),COALESCE(SUM(payload_size),0) FROM telemetry_outbox WHERE outbox_state=0;");
      if(request==INVALID_HANDLE)
        { reason="OUTBOX_CAPACITY_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      if(!DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,pending_count) ||
         !DatabaseColumnLong(request,1,pending_bytes))
        {
         reason="OUTBOX_CAPACITY_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      if(pending_count+additional_messages>m_outbox_max_messages ||
         pending_bytes+additional_bytes>m_outbox_max_bytes)
        {
         reason="OUTBOX_CAPACITY_EXHAUSTED";
         return false;
        }
      return true;
     }

   bool ExecutePreparedNoRows(const int request,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      ResetLastError();
      const bool result=DatabaseRead(request);
      const int error=GetLastError();
      if(result || error==ERR_DATABASE_NO_MORE_DATA)
         return true;
      reason="DATABASE_REQUEST_FAILED:"+IntegerToString(error);
      PoisonWrites(reason);
      return false;
     }

   bool ExecuteSchemaStatement(const string sql,string &reason)
     {
      if(!RequireWritable(reason))
         return false;
      ResetLastError();
      if(DatabaseExecute(m_database,sql))
         return true;
      reason="DATABASE_SCHEMA_FAILED:"+IntegerToString(GetLastError());
      PoisonWrites(reason);
      return false;
     }

   bool TableExists(const string table_name,bool &exists,string &reason)
     {
      exists=false;
      if(!RequireReadable(reason))
         return false;
      int request=DatabasePrepare(m_database,
         "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1 LIMIT 1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,table_name))
        {
         reason="DATABASE_TABLE_LOOKUP_FAILED:"+table_name+":"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         exists=true;
         DatabaseFinalize(request);
         return true;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error==ERR_DATABASE_NO_MORE_DATA)
         return true;
      reason="DATABASE_TABLE_LOOKUP_READ_FAILED:"+table_name+":"+IntegerToString(error);
      return false;
     }

   bool ValidateCoreSchemaTables(const bool require_v4_infrastructure,string &reason)
     {
      string names[]={"meta","counters","domain_events","sequences","levels","seq_ledger",
                      "order_intents","trade_observations","receipts","receipt_aggregates",
                      "reduced_event_keys","reduced_receipt_keys","slippage_log",
                      "intelligence_cache","telemetry_outbox","experiment_manifests"};
      for(int i=0;i<ArraySize(names);i++)
        {
         bool exists=false;
         if(!TableExists(names[i],exists,reason)) return false;
         if(!exists)
           {
            reason="DATABASE_REQUIRED_TABLE_MISSING:"+names[i];
            return false;
           }
        }
      if(require_v4_infrastructure)
        {
         string v4_names[]={"schema_migrations","journal_checkpoints"};
         for(int i=0;i<ArraySize(v4_names);i++)
           {
            bool exists=false;
            if(!TableExists(v4_names[i],exists,reason)) return false;
            if(!exists)
              {
               reason="DATABASE_V4_TABLE_MISSING:"+v4_names[i];
               return false;
              }
           }
        }
      return true;
     }

   bool CreateSchema(string &reason)
     {
      if(!RequireWritable(reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS meta (meta_key TEXT PRIMARY KEY NOT NULL,meta_value TEXT NOT NULL,updated_at_msc INTEGER NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS schema_migrations (migration_id TEXT PRIMARY KEY NOT NULL,from_version INTEGER NOT NULL,to_version INTEGER NOT NULL,applied_at_msc INTEGER NOT NULL,migration_hash TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS journal_checkpoints (checkpoint_slot INTEGER PRIMARY KEY NOT NULL CHECK(checkpoint_slot=1),canonical_number INTEGER NOT NULL,event_hash TEXT NOT NULL,verified_at_msc INTEGER NOT NULL,verification_mode TEXT NOT NULL,checkpoint_hash TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS counters (counter_name TEXT PRIMARY KEY NOT NULL,next_value INTEGER NOT NULL);",reason)) return false;
       if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS domain_events (canonical_number INTEGER PRIMARY KEY NOT NULL,state_version INTEGER NOT NULL,event_id TEXT UNIQUE NOT NULL,event_kind INTEGER NOT NULL,action_kind INTEGER NOT NULL,risk_effect INTEGER NOT NULL,direction INTEGER NOT NULL,symbol TEXT NOT NULL,occurred_at_msc INTEGER NOT NULL,sequence_id TEXT,order_intent_id TEXT,level_index INTEGER NOT NULL,request_id TEXT NOT NULL,order_ticket TEXT NOT NULL,deal_ticket TEXT NOT NULL,position_id TEXT NOT NULL,volume REAL NOT NULL,price REAL NOT NULL,realized_pl REAL NOT NULL,retrace_advance INTEGER NOT NULL,reason_code TEXT NOT NULL,canonical_payload TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT UNIQUE NOT NULL);",reason)) return false;
       if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS sequences (sequence_id TEXT PRIMARY KEY NOT NULL,strategy_member_id TEXT NOT NULL,symbol TEXT NOT NULL,direction INTEGER NOT NULL,status INTEGER NOT NULL,started_at_msc INTEGER NOT NULL,ended_at_msc INTEGER NOT NULL,last_event_number INTEGER NOT NULL,last_state_version INTEGER NOT NULL,last_event_id TEXT NOT NULL,last_event_hash TEXT NOT NULL,experiment_manifest_id TEXT NOT NULL,input_values_hash TEXT NOT NULL,broker_profile_hash TEXT NOT NULL,symbol_spec_hash TEXT NOT NULL,execution_plan_hash TEXT NOT NULL,level_count INTEGER NOT NULL,max_levels INTEGER NOT NULL,start_volume REAL NOT NULL,standing_volume REAL NOT NULL,average_entry_price REAL NOT NULL,realized_pl REAL NOT NULL,commission REAL NOT NULL,swap REAL NOT NULL,mlps_budget REAL NOT NULL,mlps_used REAL NOT NULL,retrace_price REAL NOT NULL,rescue_armed INTEGER NOT NULL,reduction_remaining REAL NOT NULL,reduction_semantic_level INTEGER NOT NULL,reduction_reason TEXT NOT NULL,retrace_advance_pending INTEGER NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS levels (sequence_id TEXT NOT NULL,level_index INTEGER NOT NULL,planned_price REAL NOT NULL,requested_volume REAL NOT NULL,filled_volume REAL NOT NULL,average_fill_price REAL NOT NULL,position_id TEXT NOT NULL,virtual_level INTEGER NOT NULL,closed INTEGER NOT NULL,PRIMARY KEY(sequence_id,level_index));",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS seq_ledger (deal_ticket TEXT PRIMARY KEY NOT NULL,sequence_id TEXT NOT NULL,occurred_at_msc INTEGER NOT NULL,profit REAL NOT NULL,commission REAL NOT NULL,swap REAL NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS order_intents (order_intent_id TEXT PRIMARY KEY NOT NULL,sequence_id TEXT NOT NULL,action_kind INTEGER NOT NULL,risk_effect INTEGER NOT NULL,status INTEGER NOT NULL,direction INTEGER NOT NULL,level_index INTEGER NOT NULL,symbol TEXT NOT NULL,magic TEXT NOT NULL,requested_volume REAL NOT NULL,requested_price REAL NOT NULL,stop_loss REAL NOT NULL,take_profit REAL NOT NULL,request_id TEXT NOT NULL,order_ticket TEXT NOT NULL,deal_ticket TEXT NOT NULL,position_id TEXT NOT NULL,retcode INTEGER NOT NULL,created_at_msc INTEGER NOT NULL,reason_code TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS trade_observations (observation_id TEXT PRIMARY KEY NOT NULL,captured_at_msc INTEGER NOT NULL,transaction_type INTEGER NOT NULL,request_id TEXT NOT NULL,order_ticket TEXT NOT NULL,deal_ticket TEXT NOT NULL,position_id TEXT NOT NULL,position_by_id TEXT NOT NULL,symbol TEXT NOT NULL,order_type INTEGER NOT NULL,order_state INTEGER NOT NULL,deal_type INTEGER NOT NULL,volume REAL NOT NULL,price REAL NOT NULL,stop_loss REAL NOT NULL,take_profit REAL NOT NULL,retcode INTEGER NOT NULL,retcode_external INTEGER NOT NULL,comment TEXT NOT NULL,processed INTEGER NOT NULL DEFAULT 0);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS receipts (receipt_id TEXT PRIMARY KEY NOT NULL,receipt_kind INTEGER NOT NULL,occurred_at_msc INTEGER NOT NULL,canonical_number INTEGER NOT NULL,state_version INTEGER NOT NULL,deployment_id TEXT NOT NULL,portfolio_generation_id TEXT NOT NULL,strategy_member_id TEXT NOT NULL,sequence_id TEXT NOT NULL,order_intent_id TEXT NOT NULL,event_id TEXT NOT NULL,manifest_id TEXT NOT NULL,payload_hash TEXT NOT NULL,canonical_payload TEXT NOT NULL,emergency_persistence INTEGER NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS receipt_aggregates (receipt_kind INTEGER PRIMARY KEY NOT NULL,receipt_count INTEGER NOT NULL,last_occurred_at_msc INTEGER NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS reduced_event_keys (event_id TEXT PRIMARY KEY NOT NULL,canonical_number INTEGER UNIQUE NOT NULL,payload_hash TEXT NOT NULL,event_hash TEXT UNIQUE NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS reduced_receipt_keys (receipt_id TEXT PRIMARY KEY NOT NULL,payload_hash TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS slippage_log (entry_id TEXT PRIMARY KEY NOT NULL,order_intent_id TEXT NOT NULL,occurred_at_msc INTEGER NOT NULL,requested_price REAL NOT NULL,accepted_price REAL NOT NULL,filled_price REAL NOT NULL,latency_micros TEXT NOT NULL,retcode INTEGER NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS intelligence_cache (state_id TEXT PRIMARY KEY NOT NULL,content_hash TEXT NOT NULL,published_at_msc INTEGER NOT NULL,valid_until_msc INTEGER NOT NULL,canonical_payload TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS telemetry_outbox (message_id TEXT PRIMARY KEY NOT NULL,message_kind TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,payload_size INTEGER NOT NULL,created_at_msc INTEGER NOT NULL,next_attempt_msc INTEGER NOT NULL,attempts INTEGER NOT NULL,priority INTEGER NOT NULL,critical INTEGER NOT NULL,outbox_state INTEGER NOT NULL,last_error TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TABLE IF NOT EXISTS experiment_manifests (manifest_id TEXT PRIMARY KEY NOT NULL,manifest_hash TEXT UNIQUE NOT NULL,created_at_msc INTEGER NOT NULL,manifest_class INTEGER NOT NULL,external_lineage_complete INTEGER NOT NULL,canonical_payload TEXT NOT NULL);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_events_sequence ON domain_events(sequence_id,canonical_number);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_events_deal_fill ON domain_events(deal_ticket,event_kind) WHERE deal_ticket<>'0';",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_sequence_state ON domain_events(sequence_id,state_version) WHERE sequence_id IS NOT NULL AND sequence_id<>'';",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_intents_sequence ON order_intents(sequence_id,status);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_intents_request ON order_intents(request_id) WHERE request_id<>'0';",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_intents_order ON order_intents(order_ticket) WHERE order_ticket<>'0';",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_intents_deal ON order_intents(deal_ticket) WHERE deal_ticket<>'0';",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_observations_processed ON trade_observations(processed,captured_at_msc);",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE INDEX IF NOT EXISTS idx_outbox_pending ON telemetry_outbox(outbox_state,priority,next_attempt_msc);",reason)) return false;
      // The journal is append-only.  Projection repair is never allowed to
      // edit or delete evidence; it must be performed by replay into a new
      // projection under a separately reviewed migration/tooling workflow.
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_domain_events_append_guard BEFORE INSERT ON domain_events WHEN NEW.canonical_number<>COALESCE((SELECT MAX(canonical_number)+1 FROM domain_events),1) OR NEW.previous_hash<>COALESCE((SELECT NULLIF(meta_value,'') FROM meta WHERE meta_key='last_event_hash'),'GENESIS') BEGIN SELECT RAISE(ABORT,'DOMAIN_EVENT_APPEND_INVARIANT'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_domain_events_no_update BEFORE UPDATE ON domain_events BEGIN SELECT RAISE(ABORT,'DOMAIN_EVENTS_IMMUTABLE'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_domain_events_no_delete BEFORE DELETE ON domain_events BEGIN SELECT RAISE(ABORT,'DOMAIN_EVENTS_IMMUTABLE'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_reduced_events_append_guard BEFORE INSERT ON reduced_event_keys WHEN NEW.canonical_number<>COALESCE((SELECT MAX(canonical_number)+1 FROM reduced_event_keys),1) BEGIN SELECT RAISE(ABORT,'REDUCED_EVENT_APPEND_INVARIANT'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_reduced_events_no_update BEFORE UPDATE ON reduced_event_keys BEGIN SELECT RAISE(ABORT,'REDUCED_EVENTS_IMMUTABLE'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_reduced_events_no_delete BEFORE DELETE ON reduced_event_keys BEGIN SELECT RAISE(ABORT,'REDUCED_EVENTS_IMMUTABLE'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_update BEFORE UPDATE ON schema_migrations BEGIN SELECT RAISE(ABORT,'SCHEMA_MIGRATIONS_IMMUTABLE'); END;",reason)) return false;
      if(!ExecuteSchemaStatement("CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_delete BEFORE DELETE ON schema_migrations BEGIN SELECT RAISE(ABORT,'SCHEMA_MIGRATIONS_IMMUTABLE'); END;",reason)) return false;
      return true;
     }

   bool ReadMeta(const string key,string &value,bool &found,string &reason)
     {
      value="";
      found=false;
      int request=DatabasePrepare(m_database,"SELECT meta_value FROM meta WHERE meta_key=?1;");
      if(request==INVALID_HANDLE)
        { reason="META_SELECT_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      if(!DatabaseBind(request,0,key))
        { reason="META_SELECT_BIND_FAILED:"+IntegerToString(GetLastError()); DatabaseFinalize(request); return false; }
      ResetLastError();
      if(DatabaseRead(request))
        {
         found=DatabaseColumnText(request,0,value);
         if(!found)
            reason="META_SELECT_COLUMN_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return found;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error==ERR_DATABASE_NO_MORE_DATA)
         return true;
      reason="META_SELECT_FAILED:"+IntegerToString(error);
      return false;
     }

   bool WriteMeta(const string key,const string value,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      string prior="";
      bool found=false;
      if(!ReadMeta(key,prior,found,reason))
         return false;
      const string sql=found ?
         "UPDATE meta SET meta_value=?1,updated_at_msc=?2 WHERE meta_key=?3;" :
         "INSERT INTO meta(meta_value,updated_at_msc,meta_key) VALUES(?1,?2,?3);";
      int request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE)
        {
         reason="META_WRITE_PREPARE_FAILED:"+IntegerToString(GetLastError());
         PoisonWrites(reason);
         return false;
        }
      const long now_msc=V2UtcNowMsc();
      if(!DatabaseBind(request,0,value) || !DatabaseBind(request,1,now_msc) || !DatabaseBind(request,2,key))
        {
         reason="META_WRITE_BIND_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         PoisonWrites(reason);
         return false;
        }
      const bool ok=ExecutePreparedNoRows(request,reason);
      DatabaseFinalize(request);
      return ok;
     }

   bool RecordSchemaMigration(const int from_version,const int to_version,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      const string migration_id="schema_"+IntegerToString(from_version)+"_to_"+IntegerToString(to_version);
      const string migration_hash=V2Sha256Hex(migration_id+"|GOAT2_STATE_DB");
      int request=DatabasePrepare(m_database,
         "INSERT INTO schema_migrations(migration_id,from_version,to_version,applied_at_msc,migration_hash) VALUES(?1,?2,?3,?4,?5);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,migration_id) ||
         !DatabaseBind(request,1,from_version) ||
         !DatabaseBind(request,2,to_version) ||
         !DatabaseBind(request,3,V2UtcNowMsc()) ||
         !DatabaseBind(request,4,migration_hash) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="SCHEMA_MIGRATION_LEDGER_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool ApplySchemaMigrationStep(const int from_version,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      switch(from_version)
        {
         case 3:
           {
            // v3 -> v4 is intentionally additive: verify that the complete v3
            // core exists, then add checkpoint/migration infrastructure and
            // append-only guards.  No journal or projection row is rewritten.
            if(!ValidateCoreSchemaTables(false,reason))
              {
               reason="SCHEMA_MIGRATION_3_TO_4_PRECONDITION_FAILED:"+reason;
               return false;
              }
            if(!CreateSchema(reason) ||
               !RecordSchemaMigration(3,4,reason) ||
               !WriteMeta("schema_version","4",reason))
              {
               reason="SCHEMA_MIGRATION_3_TO_4_FAILED:"+reason;
               return false;
              }
            return true;
           }
         case 1:
         case 2:
            reason="SCHEMA_MIGRATION_UNSAFE_LEGACY_VERSION:"+IntegerToString(from_version);
            return false;
        }
      reason="SCHEMA_MIGRATION_STEP_UNKNOWN:"+IntegerToString(from_version)+"_TO_"+
             IntegerToString(from_version+1);
      return false;
     }

   bool MigrateSchema(const int stored_version,const int target_version,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      if(stored_version<=0 || target_version!=V2_STATE_DB_SCHEMA_VERSION ||
         stored_version>target_version)
        {
         reason="DATABASE_SCHEMA_MIGRATION_UNSUPPORTED:"+IntegerToString(stored_version)+"_TO_"+
                IntegerToString(target_version);
         return false;
        }
      if(stored_version==target_version)
         return ValidateCoreSchemaTables(true,reason);
      if(m_in_transaction)
        { reason="SCHEMA_MIGRATION_AMBIENT_TRANSACTION_FORBIDDEN"; return false; }
      if(!Begin(reason)) return false;
      int version=stored_version;
      while(version<target_version)
        {
         if(!ApplySchemaMigrationStep(version,reason))
           {
            Rollback();
            return false;
           }
         version++;
        }
      if(!Commit(reason)) return false;
      return ValidateCoreSchemaTables(true,reason);
     }

   string CanonicalEventPayload(const V2DomainEvent &event) const
     {
      string payload="{";
      payload+="\"schemaVersion\":\"goat2-domain-event-v2\",";
      payload+="\"canonicalNumber\":"+IntegerToString(event.canonical_number)+",";
      payload+="\"stateVersion\":"+IntegerToString(event.state_version)+",";
      payload+="\"kind\":"+IntegerToString((int)event.kind)+",";
      payload+="\"action\":"+IntegerToString((int)event.action)+",";
      payload+="\"riskEffect\":"+IntegerToString((int)event.risk_effect)+",";
      payload+="\"direction\":"+IntegerToString((int)event.direction)+",";
      payload+="\"symbol\":"+V2JsonQuote(event.symbol)+",";
      payload+="\"occurredAtMsc\":"+IntegerToString((long)event.occurred_at*1000)+",";
      payload+="\"sequenceId\":"+V2JsonQuote(event.sequence_id)+",";
      payload+="\"orderIntentId\":"+V2JsonQuote(event.order_intent_id)+",";
      payload+="\"levelIndex\":"+IntegerToString(event.level_index)+",";
      payload+="\"requestId\":"+V2JsonQuote(V2UlongToText(event.request_id))+",";
      payload+="\"orderTicket\":"+V2JsonQuote(V2UlongToText(event.order_ticket))+",";
      payload+="\"dealTicket\":"+V2JsonQuote(V2UlongToText(event.deal_ticket))+",";
      payload+="\"positionId\":"+V2JsonQuote(V2UlongToText(event.position_id))+",";
      payload+="\"volume\":"+V2CanonicalDouble(event.volume)+",";
      payload+="\"price\":"+V2CanonicalDouble(event.price)+",";
      payload+="\"realizedPl\":"+V2CanonicalDouble(event.realized_pl)+",";
      payload+="\"retraceAdvance\":"+(event.retrace_advance ? "true" : "false")+",";
      payload+="\"reasonCode\":"+V2JsonQuote(event.reason_code);
      payload+="}";
      return payload;
     }

   bool ReadExistingEvent(const string event_id,
                          bool &found,
                          long &canonical_number,
                          string &canonical_payload,
                          string &event_hash,
                          string &reason)
     {
      found=false;
      canonical_number=0;
      canonical_payload="";
      event_hash="";
      if(event_id=="")
         return true;
      const string sql=(m_config.mode==V2_DB_REDUCED) ?
         "SELECT canonical_number,payload_hash,event_hash FROM reduced_event_keys WHERE event_id=?1;" :
         "SELECT canonical_number,canonical_payload,event_hash FROM domain_events WHERE event_id=?1;";
      int request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,event_id))
        {
         reason="EVENT_LOOKUP_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         found=DatabaseColumnLong(request,0,canonical_number) &&
               DatabaseColumnText(request,1,canonical_payload) &&
               DatabaseColumnText(request,2,event_hash);
         if(!found)
            reason="EVENT_LOOKUP_COLUMN_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return found;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error==ERR_DATABASE_NO_MORE_DATA)
         return true;
      reason="EVENT_LOOKUP_FAILED:"+IntegerToString(error);
      return false;
     }

   bool ReadExistingReceipt(const string receipt_id,bool &found,string &payload_hash,string &reason)
     {
      found=false;
      payload_hash="";
      int request=DatabasePrepare(m_database,"SELECT payload_hash FROM receipts WHERE receipt_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,receipt_id))
        {
         reason="RECEIPT_LOOKUP_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         found=DatabaseColumnText(request,0,payload_hash);
         if(!found) reason="RECEIPT_LOOKUP_COLUMN_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return found;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error==ERR_DATABASE_NO_MORE_DATA) return true;
      reason="RECEIPT_LOOKUP_FAILED:"+IntegerToString(error);
      return false;
     }

   bool StoreReceiptAggregate(const V2Receipt &receipt,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      string existing_hash="";
      bool existing=false;
      int request=DatabasePrepare(m_database,
         "SELECT payload_hash FROM reduced_receipt_keys WHERE receipt_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,receipt.receipt_id))
        {
         reason="REDUCED_RECEIPT_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
         existing=DatabaseColumnText(request,0,existing_hash);
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="REDUCED_RECEIPT_LOOKUP_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      if(existing)
        {
         if(existing_hash!=receipt.payload_hash)
           { reason="REDUCED_RECEIPT_ID_HASH_COLLISION"; return false; }
         return true;
        }
      request=DatabasePrepare(m_database,
         "INSERT INTO reduced_receipt_keys(receipt_id,payload_hash) VALUES(?1,?2);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,receipt.receipt_id) ||
         !DatabaseBind(request,1,receipt.payload_hash) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="REDUCED_RECEIPT_KEY_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      long count=0;
      bool found=false;
      request=DatabasePrepare(m_database,
         "SELECT receipt_count FROM receipt_aggregates WHERE receipt_kind=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,(int)receipt.kind))
        {
         reason="RECEIPT_AGGREGATE_SELECT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
         found=DatabaseColumnLong(request,0,count);
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="RECEIPT_AGGREGATE_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      const string sql=found ?
         "UPDATE receipt_aggregates SET receipt_count=?1,last_occurred_at_msc=?2 WHERE receipt_kind=?3;" :
         "INSERT INTO receipt_aggregates(receipt_count,last_occurred_at_msc,receipt_kind) VALUES(?1,?2,?3);";
      request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,count+1) ||
         !DatabaseBind(request,1,receipt.occurred_at_msc) ||
         !DatabaseBind(request,2,(int)receipt.kind) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="RECEIPT_AGGREGATE_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool StoreReceiptInternal(const V2Receipt &receipt,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      if(receipt.receipt_id=="" || receipt.payload_hash=="" || receipt.canonical_payload=="")
        { reason="RECEIPT_NOT_FINALIZED"; return false; }
      CV2ReceiptBuilder validator;
      if(!validator.Validate(receipt,reason))
         return false;
      if(m_config.mode==V2_DB_REDUCED)
         return StoreReceiptAggregate(receipt,reason);

      bool found=false;
      string stored_hash="";
      if(!ReadExistingReceipt(receipt.receipt_id,found,stored_hash,reason))
         return false;
      if(found)
        {
         if(stored_hash!=receipt.payload_hash)
           { reason="RECEIPT_ID_HASH_COLLISION"; return false; }
         return true;
        }

      int request=DatabasePrepare(m_database,
         "INSERT INTO receipts(receipt_id,receipt_kind,occurred_at_msc,canonical_number,state_version,deployment_id,portfolio_generation_id,strategy_member_id,sequence_id,order_intent_id,event_id,manifest_id,payload_hash,canonical_payload,emergency_persistence) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,receipt.receipt_id) ||
         !DatabaseBind(request,1,(int)receipt.kind) ||
         !DatabaseBind(request,2,receipt.occurred_at_msc) ||
         !DatabaseBind(request,3,receipt.canonical_number) ||
         !DatabaseBind(request,4,receipt.state_version) ||
         !DatabaseBind(request,5,receipt.deployment_id) ||
         !DatabaseBind(request,6,receipt.portfolio_generation_id) ||
         !DatabaseBind(request,7,receipt.strategy_member_id) ||
         !DatabaseBind(request,8,receipt.sequence_id) ||
         !DatabaseBind(request,9,receipt.order_intent_id) ||
         !DatabaseBind(request,10,receipt.event_id) ||
         !DatabaseBind(request,11,receipt.experiment_manifest_id) ||
         !DatabaseBind(request,12,receipt.payload_hash) ||
         !DatabaseBind(request,13,receipt.canonical_payload) ||
         !DatabaseBind(request,14,receipt.emergency_persistence ? 1 : 0) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="RECEIPT_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool ReadExistingIntent(const V2OrderIntent &intent,
                           bool &found,
                           int &stored_status,
                           string &reason)
     {
      found=false;
      stored_status=0;
      int request=DatabasePrepare(m_database,
         "SELECT sequence_id,action_kind,risk_effect,status,direction,level_index,symbol,magic,requested_volume,requested_price,stop_loss,take_profit,created_at_msc FROM order_intents WHERE order_intent_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,intent.order_intent_id))
        {
         reason="INTENT_LOOKUP_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         string sequence_id="",symbol="",magic_text="";
         int action=0,risk_effect=0,direction=0,level_index=-1;
         double requested_volume=0.0,requested_price=0.0,stop_loss=0.0,take_profit=0.0;
         long created_at_msc=0;
         const bool read=DatabaseColumnText(request,0,sequence_id) &&
                         DatabaseColumnInteger(request,1,action) &&
                         DatabaseColumnInteger(request,2,risk_effect) &&
                         DatabaseColumnInteger(request,3,stored_status) &&
                         DatabaseColumnInteger(request,4,direction) &&
                         DatabaseColumnInteger(request,5,level_index) &&
                         DatabaseColumnText(request,6,symbol) &&
                         DatabaseColumnText(request,7,magic_text) &&
                         DatabaseColumnDouble(request,8,requested_volume) &&
                         DatabaseColumnDouble(request,9,requested_price) &&
                         DatabaseColumnDouble(request,10,stop_loss) &&
                         DatabaseColumnDouble(request,11,take_profit) &&
                         DatabaseColumnLong(request,12,created_at_msc);
         DatabaseFinalize(request);
         ulong magic=0;
         if(!read || !V2TextToUlong(magic_text,magic))
           {
            reason="INTENT_LOOKUP_COLUMN_FAILED:"+IntegerToString(GetLastError());
            return false;
           }
         if(sequence_id!=intent.sequence_id ||
            action!=(int)intent.action ||
            risk_effect!=(int)intent.risk_effect ||
            direction!=(int)intent.direction ||
            level_index!=intent.level_index ||
            symbol!=intent.symbol ||
            magic!=intent.magic ||
            requested_volume!=intent.requested_volume ||
            requested_price!=intent.requested_price ||
            stop_loss!=intent.stop_loss ||
            take_profit!=intent.take_profit ||
            created_at_msc!=(long)intent.created_at*1000)
           {
            reason="INTENT_ID_PAYLOAD_COLLISION";
            return false;
           }
         found=true;
         return true;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error==ERR_DATABASE_NO_MORE_DATA) return true;
      reason="INTENT_LOOKUP_FAILED:"+IntegerToString(error);
      return false;
     }

   bool InsertIntentInternal(const V2OrderIntent &intent,bool &inserted,string &reason)
     {
      inserted=false;
      if(!RequireWritable(reason)) return false;
      if(intent.order_intent_id=="" || intent.sequence_id=="")
        { reason="INTENT_IDENTITY_EMPTY"; return false; }
      if(!MathIsValidNumber(intent.requested_volume) ||
         !MathIsValidNumber(intent.requested_price) ||
         !MathIsValidNumber(intent.stop_loss) ||
         !MathIsValidNumber(intent.take_profit))
        { reason="INTENT_NUMERIC_VALUE_INVALID"; return false; }
      bool found=false;
      int stored_status=0;
      if(!ReadExistingIntent(intent,found,stored_status,reason))
         return false;
      if(found)
         return true;

      int request=DatabasePrepare(m_database,
         "INSERT INTO order_intents(order_intent_id,sequence_id,action_kind,risk_effect,status,direction,level_index,symbol,magic,requested_volume,requested_price,stop_loss,take_profit,request_id,order_ticket,deal_ticket,position_id,retcode,created_at_msc,reason_code) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,intent.order_intent_id) ||
         !DatabaseBind(request,1,intent.sequence_id) ||
         !DatabaseBind(request,2,(int)intent.action) ||
         !DatabaseBind(request,3,(int)intent.risk_effect) ||
         !DatabaseBind(request,4,(int)V2_INTENT_PERSISTED) ||
         !DatabaseBind(request,5,(int)intent.direction) ||
         !DatabaseBind(request,6,intent.level_index) ||
         !DatabaseBind(request,7,intent.symbol) ||
         !DatabaseBind(request,8,V2UlongToText(intent.magic)) ||
         !DatabaseBind(request,9,intent.requested_volume) ||
         !DatabaseBind(request,10,intent.requested_price) ||
         !DatabaseBind(request,11,intent.stop_loss) ||
         !DatabaseBind(request,12,intent.take_profit) ||
         !DatabaseBind(request,13,V2UlongToText(intent.request_id)) ||
         !DatabaseBind(request,14,V2UlongToText(intent.order_ticket)) ||
         !DatabaseBind(request,15,V2UlongToText(intent.deal_ticket)) ||
         !DatabaseBind(request,16,V2UlongToText(intent.position_id)) ||
         !DatabaseBind(request,17,(long)intent.retcode) ||
         !DatabaseBind(request,18,(long)intent.created_at*1000) ||
         !DatabaseBind(request,19,intent.reason_code) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="INTENT_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      inserted=true;
      return true;
     }

   bool UpdateIntentInternal(const V2OrderIntent &intent,string &reason)
     {
      if(!RequireWritable(reason)) return false;
      bool found=false;
      int stored_status=0;
      if(!ReadExistingIntent(intent,found,stored_status,reason))
         return false;
      if(!found)
        { reason="INTENT_UPDATE_TARGET_MISSING"; return false; }
      CV2OrderIntentMachine intent_machine;
      string transition_reason="";
      if(!intent_machine.CanTransition((ENUM_V2_ORDER_INTENT_STATUS)stored_status,
                                       intent.status,
                                       transition_reason))
        {
         reason="INTENT_DATABASE_TRANSITION_REJECTED:"+
                IntegerToString(stored_status)+"_TO_"+
                IntegerToString((int)intent.status)+":"+transition_reason;
         return false;
        }
      int request=DatabasePrepare(m_database,
         "UPDATE order_intents SET status=?1,request_id=?2,order_ticket=?3,deal_ticket=?4,position_id=?5,retcode=?6,reason_code=?7 WHERE order_intent_id=?8;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,(int)intent.status) ||
         !DatabaseBind(request,1,V2UlongToText(intent.request_id)) ||
         !DatabaseBind(request,2,V2UlongToText(intent.order_ticket)) ||
         !DatabaseBind(request,3,V2UlongToText(intent.deal_ticket)) ||
         !DatabaseBind(request,4,V2UlongToText(intent.position_id)) ||
         !DatabaseBind(request,5,(long)intent.retcode) ||
         !DatabaseBind(request,6,intent.reason_code) ||
         !DatabaseBind(request,7,intent.order_intent_id) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="INTENT_UPDATE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool UpdateIntentCanonicalInternal(const V2OrderIntent &intent,
                                      const bool broker_submission_observed,
                                      string &reason)
     {
      bool found=false;
      int stored_status=0;
      if(!ReadExistingIntent(intent,found,stored_status,reason))
         return false;
      if(!found)
        { reason="INTENT_UPDATE_TARGET_MISSING"; return false; }

      // The runtime machine can observe a broker's terminal answer in the
      // same call that first proves submission. Persist/replay SUBMITTED as
      // the canonical intermediate state instead of attempting an illegal
      // PERSISTED -> terminal shortcut. Both updates remain in the caller's
      // transaction, so failure rolls the intent back to its pre-call state.
      const ENUM_V2_ORDER_INTENT_STATUS current=(ENUM_V2_ORDER_INTENT_STATUS)stored_status;
      const bool needs_submission_bridge=(current==V2_INTENT_PERSISTED &&
                                          intent.status!=V2_INTENT_PERSISTED &&
                                          intent.status!=V2_INTENT_SUBMITTED &&
                                          (broker_submission_observed ||
                                           intent.status!=V2_INTENT_CANCELLED));
      if(needs_submission_bridge)
        {
         V2OrderIntent submitted=intent;
         submitted.status=V2_INTENT_SUBMITTED;
         submitted.reason_code="CANONICAL_SUBMISSION_BRIDGE:"+intent.reason_code;
         if(!UpdateIntentInternal(submitted,reason))
            return false;
        }
      return UpdateIntentInternal(intent,reason);
     }

   bool EnsureStableMetaIdentity(const string key,const string expected,string &reason)
     {
      if(expected=="")
        { reason="DATABASE_META_IDENTITY_EMPTY:"+key; return false; }
      string stored="";
      bool found=false;
      if(!ReadMeta(key,stored,found,reason))
         return false;
      if(found)
        {
         if(stored!=expected)
           { reason="DATABASE_META_IDENTITY_MISMATCH:"+key; return false; }
         return true;
        }
      return WriteMeta(key,expected,reason);
     }

   string JournalCheckpointHash(const long canonical_number,const string event_hash) const
     {
      return V2Sha256Hex("GOAT2_JOURNAL_CHECKPOINT_V1|"+
                         m_config.deployment_id+"|"+
                         IntegerToString(V2_STATE_DB_SCHEMA_VERSION)+"|"+
                         IntegerToString(canonical_number)+"|"+event_hash);
     }

   bool LoadJournalCheckpoint(long &canonical_number,
                              string &event_hash,
                              bool &found,
                              string &reason)
     {
      canonical_number=0;
      event_hash="GENESIS";
      found=false;
      bool checkpoint_table_exists=false;
      if(!TableExists("journal_checkpoints",checkpoint_table_exists,reason)) return false;
      if(!checkpoint_table_exists) return true;
      int request=DatabasePrepare(m_database,
         "SELECT canonical_number,event_hash,checkpoint_hash FROM journal_checkpoints WHERE checkpoint_slot=1;");
      if(request==INVALID_HANDLE)
        { reason="JOURNAL_CHECKPOINT_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      if(!DatabaseRead(request))
        {
         const int error=GetLastError();
         DatabaseFinalize(request);
         if(error==ERR_DATABASE_NO_MORE_DATA) return true;
         reason="JOURNAL_CHECKPOINT_READ_FAILED:"+IntegerToString(error);
         return false;
        }
      string checkpoint_hash="";
      const bool read=DatabaseColumnLong(request,0,canonical_number) &&
                      DatabaseColumnText(request,1,event_hash) &&
                      DatabaseColumnText(request,2,checkpoint_hash);
      DatabaseFinalize(request);
      if(!read || canonical_number<0 || event_hash=="" ||
         checkpoint_hash!=JournalCheckpointHash(canonical_number,event_hash))
        { reason="JOURNAL_CHECKPOINT_INVALID"; return false; }
      if(canonical_number==0)
        {
         if(event_hash!="GENESIS")
           { reason="JOURNAL_GENESIS_CHECKPOINT_INVALID"; return false; }
         found=true;
         return true;
        }
      request=DatabasePrepare(m_database,
         "SELECT event_hash FROM domain_events WHERE canonical_number=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,canonical_number))
        {
         reason="JOURNAL_CHECKPOINT_ANCHOR_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      string anchored_hash="";
      const bool anchor_read=DatabaseRead(request) && DatabaseColumnText(request,0,anchored_hash);
      DatabaseFinalize(request);
      if(!anchor_read || anchored_hash!=event_hash)
        { reason="JOURNAL_CHECKPOINT_ANCHOR_MISMATCH"; return false; }
      found=true;
      return true;
     }

   bool PersistJournalCheckpoint(const long canonical_number,
                                 const string event_hash,
                                 const string verification_mode,
                                 string &reason)
     {
      if(!RequireWritable(reason)) return false;
      const string checkpoint_hash=JournalCheckpointHash(canonical_number,event_hash);
      int request=DatabasePrepare(m_database,
         "INSERT OR REPLACE INTO journal_checkpoints(checkpoint_slot,canonical_number,event_hash,verified_at_msc,verification_mode,checkpoint_hash) VALUES(1,?1,?2,?3,?4,?5);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,canonical_number) ||
         !DatabaseBind(request,1,event_hash) ||
         !DatabaseBind(request,2,V2UtcNowMsc()) ||
         !DatabaseBind(request,3,verification_mode) ||
         !DatabaseBind(request,4,checkpoint_hash) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="JOURNAL_CHECKPOINT_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool VerifyJournalStateVersions(const long checkpoint_number,string &reason)
     {
      string sql="";
      if(checkpoint_number<=0)
         sql="SELECT sequence_id FROM domain_events WHERE sequence_id IS NOT NULL AND sequence_id<>'' GROUP BY sequence_id HAVING MIN(state_version)<>1 OR MAX(state_version)<>COUNT(*) LIMIT 1;";
      else
        {
         const string checkpoint=IntegerToString(checkpoint_number);
         // The correlated prefix MAX is index-backed per touched sequence; the
         // unbounded prefix itself is not rescanned as one global aggregate.
         sql="SELECT e.sequence_id FROM domain_events e WHERE e.canonical_number>"+checkpoint+
             " AND e.sequence_id IS NOT NULL AND e.sequence_id<>'' GROUP BY e.sequence_id HAVING "+
             "MIN(e.state_version)<>COALESCE((SELECT MAX(p.state_version) FROM domain_events p WHERE p.sequence_id=e.sequence_id AND p.canonical_number<="+checkpoint+"),0)+1 OR "+
             "MAX(e.state_version)-MIN(e.state_version)+1<>COUNT(*) LIMIT 1;";
        }
      int request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE)
        { reason="JOURNAL_STATE_VERSION_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      if(DatabaseRead(request))
        {
         string sequence_id="";
         DatabaseColumnText(request,0,sequence_id);
         DatabaseFinalize(request);
         reason="JOURNAL_STATE_VERSION_GAP:"+sequence_id;
         return false;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error!=ERR_DATABASE_NO_MORE_DATA)
        { reason="JOURNAL_STATE_VERSION_READ_FAILED:"+IntegerToString(error); return false; }
      return true;
     }

   bool VerifyProjectionLineage(const string strategy_member_id,string &reason)
     {
      string sql="SELECT s.sequence_id FROM sequences s LEFT JOIN domain_events e ON e.event_id=s.last_event_id WHERE ";
      if(strategy_member_id!="")
         sql+="s.strategy_member_id=?1 AND ";
      sql+="((s.status<>0 AND s.last_state_version<=0) OR (s.last_state_version>0 AND (e.event_id IS NULL OR e.sequence_id<>s.sequence_id OR e.canonical_number<>s.last_event_number OR e.state_version<>s.last_state_version OR e.event_hash<>s.last_event_hash))) LIMIT 1;";
      int request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE || (strategy_member_id!="" && !DatabaseBind(request,0,strategy_member_id)))
        {
         reason="PROJECTION_INTEGRITY_PREPARE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         string sequence_id="";
         DatabaseColumnText(request,0,sequence_id);
         DatabaseFinalize(request);
         reason="PROJECTION_JOURNAL_LINEAGE_MISMATCH:"+sequence_id;
         return false;
        }
      const int error=GetLastError();
      DatabaseFinalize(request);
      if(error!=ERR_DATABASE_NO_MORE_DATA)
        { reason="PROJECTION_INTEGRITY_READ_FAILED:"+IntegerToString(error); return false; }
      return true;
     }

   bool VerifyJournalIntegrity(const bool persist_checkpoint,
                               const bool allow_inherited_checkpoint,
                               string &reason)
     {
      reason="";
      if(!RequireReadable(reason)) return false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;

      long checkpoint_number=0;
      string checkpoint_hash="GENESIS";
      bool checkpoint_found=false;
      if(allow_inherited_checkpoint &&
         !LoadJournalCheckpoint(checkpoint_number,checkpoint_hash,checkpoint_found,reason))
         return false;

      // Verification invariant:
      //  1. With no checkpoint, every event from GENESIS is recomputed.
      //  2. A checkpoint is persisted only after a successful full/inherited
      //     proof or an atomic, hash-verified append from that proven head.  On
      //     later opens its self-hash and anchored journal row must match, and
      //     every suffix link/hash is recomputed to the stored head.
      //  3. v4 SQL triggers forbid in-process UPDATE/DELETE of the inherited
      //     prefix.  quick_check protects SQLite structure.
      // This is an inherited hash-chain proof, not external authentication.  A
      // coordinated offline replacement of both DB history and its checkpoint
      // requires an independently retained snapshot/hash to detect; the prior
      // full O(N) verifier had the same unauthenticated-rewrite limitation.
      const long start_number=(checkpoint_found ? checkpoint_number : 0);
      string running_hash=(checkpoint_found ? checkpoint_hash : "GENESIS");
      long prior_number=start_number;
      int request=DatabasePrepare(m_database,
         "SELECT canonical_number,event_id,canonical_payload,previous_hash,event_hash FROM domain_events WHERE canonical_number>?1 ORDER BY canonical_number ASC;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,start_number))
        {
         reason="JOURNAL_INTEGRITY_PREPARE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="JOURNAL_INTEGRITY_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         long canonical_number=0;
         string event_id="",payload="",previous_hash="",event_hash="";
         const bool read=DatabaseColumnLong(request,0,canonical_number) &&
                         DatabaseColumnText(request,1,event_id) &&
                         DatabaseColumnText(request,2,payload) &&
                         DatabaseColumnText(request,3,previous_hash) &&
                         DatabaseColumnText(request,4,event_hash);
         if(!read || canonical_number!=prior_number+1 || event_id=="" || payload=="" ||
            previous_hash!=running_hash ||
            event_hash!=V2Sha256Hex(previous_hash+"|"+event_id+"|"+payload))
           {
            reason="JOURNAL_LOGICAL_INTEGRITY_FAILED_AT:"+IntegerToString(canonical_number);
            DatabaseFinalize(request);
            return false;
           }
         prior_number=canonical_number;
         running_hash=event_hash;
        }
      DatabaseFinalize(request);

      if(!VerifyJournalStateVersions(start_number,reason) ||
         !VerifyProjectionLineage("",reason))
         return false;

      string stored_head="";
      bool head_found=false;
      if(!ReadMeta("last_event_hash",stored_head,head_found,reason)) return false;
      if(prior_number==0)
        {
         if(head_found && stored_head!="")
           { reason="JOURNAL_HEAD_PRESENT_WITHOUT_EVENTS"; return false; }
         running_hash="GENESIS";
         m_last_event_hash="";
        }
      else
        {
         if(!head_found || stored_head!=running_hash)
           { reason="JOURNAL_HEAD_MISMATCH"; return false; }
         m_last_event_hash=running_hash;
        }

      m_verified_checkpoint_number=prior_number;
      m_verified_checkpoint_hash=running_hash;
      m_checkpoint_inherited=checkpoint_found;
      if(persist_checkpoint)
        {
         const bool own_transaction=!m_in_transaction;
         if(own_transaction && !Begin(reason)) return false;
         const string verification_mode=(checkpoint_found ?
            "INHERITED_PREFIX_PLUS_VERIFIED_SUFFIX" : "FULL_FROM_GENESIS");
         if(!PersistJournalCheckpoint(prior_number,running_hash,verification_mode,reason))
           {
            if(own_transaction) Rollback();
            return false;
           }
         if(own_transaction && !Commit(reason)) return false;
        }
      return true;
     }

   void AbortOpen(void)
     {
      if(m_database!=INVALID_HANDLE)
         DatabaseClose(m_database);
      m_database=INVALID_HANDLE;
      m_open=false;
      m_writable=false;
      m_in_transaction=false;
      m_access_mode=V2_DB_ACCESS_CLOSED;
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;
      m_lease.Release();
     }

   bool ValidateOpenConfig(const V2StateDBConfig &config,
                           const bool read_only_recovery,
                           string &reason) const
     {
      if(config.deployment_id=="" || config.strategy_member_id=="")
        { reason="DATABASE_IDENTITY_EMPTY"; return false; }
      if(config.schema_version!=V2_STATE_DB_SCHEMA_VERSION)
        { reason="DATABASE_SCHEMA_VERSION_UNSUPPORTED"; return false; }
      if(read_only_recovery && config.mode!=V2_DB_FULL_DURABLE)
        { reason="READ_ONLY_RECOVERY_REQUIRES_DURABLE_DATABASE"; return false; }
      if(config.mode!=V2_DB_FULL_DURABLE && !MQLInfoInteger(MQL_TESTER))
        { reason="NON_DURABLE_DATABASE_FORBIDDEN_OUTSIDE_TESTER"; return false; }
      if(config.mode==V2_DB_FULL_DURABLE)
        {
         if(config.database_path=="" || config.lease_path=="" ||
            (!read_only_recovery && config.owner_instance_id==""))
           { reason="DURABLE_DATABASE_CONFIGURATION_INCOMPLETE"; return false; }
         if(config.lease_stale_seconds<V2_STATE_DB_MIN_LEASE_STALE_SECONDS ||
            config.lease_stale_seconds>V2_STATE_DB_MAX_LEASE_STALE_SECONDS)
           { reason="LEASE_STALE_SECONDS_OUT_OF_RANGE"; return false; }
        }
      return true;
     }

public:
                     CV2StateDB(void)
     {
      m_database=INVALID_HANDLE;
      m_open=false;
      m_writable=false;
      m_in_transaction=false;
      m_access_mode=V2_DB_ACCESS_CLOSED;
      m_status=V2_DB_STATUS_CLOSED;
      m_config.Reset();
      m_last_error="";
      m_status_reason="";
      m_last_event_hash="";
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;
      m_outbox_max_messages=10000;
      m_outbox_max_bytes=50*1024*1024;
     }

                    ~CV2StateDB(void)
     {
      Close();
     }

   bool IntegrityCheck(string &reason)
     {
      reason="";
      if(!RequireReadable(reason)) return false;
      int request=DatabasePrepare(m_database,"PRAGMA quick_check(1);");
      if(request==INVALID_HANDLE)
        { reason="DATABASE_INTEGRITY_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      if(!DatabaseRead(request))
        {
         reason="DATABASE_INTEGRITY_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      string result="";
      const bool read=DatabaseColumnText(request,0,result);
      DatabaseFinalize(request);
      if(!read || result!="ok")
        { reason="DATABASE_INTEGRITY_NOT_OK:"+result; return false; }
      return true;
     }

   bool AuditJournalFromGenesis(string &reason)
     {
      reason="";
      if(!RequireReadable(reason)) return false;
      if(m_in_transaction)
        { reason="FULL_JOURNAL_AUDIT_AMBIENT_TRANSACTION_FORBIDDEN"; return false; }
      // This explicit diagnostic never writes/repairs history and deliberately
      // ignores an inherited checkpoint.  It is the authoritative slow audit
      // to run before approving any offline member-projection repair plan.
      if(VerifyJournalIntegrity(false,false,reason)) return true;
      if(m_writable) PoisonWrites("FULL_JOURNAL_AUDIT_FAILED:"+reason);
      return false;
     }

   bool Open(const V2StateDBConfig &config,string &reason)
     {
      reason="";
      Close();
      m_last_error="";
      m_status_reason="";
      m_last_event_hash="";
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;
      m_config=config;

      if(!ValidateOpenConfig(config,false,reason)) return SetFailure(reason);
      if(config.mode==V2_DB_FULL_DURABLE)
        {
         if(!m_lease.Acquire(config.lease_path,config.owner_instance_id,reason))
             return SetFailure(reason);
        }

      ResetLastError();
      if(config.mode==V2_DB_FULL_DURABLE)
         m_database=DatabaseOpen(config.database_path,DATABASE_OPEN_READWRITE|DATABASE_OPEN_CREATE|DATABASE_OPEN_COMMON);
      else
         m_database=DatabaseOpen(":memory:",DATABASE_OPEN_READWRITE|DATABASE_OPEN_CREATE);
      if(m_database==INVALID_HANDLE)
        {
         reason="DATABASE_OPEN_FAILED:"+IntegerToString(GetLastError());
         AbortOpen();
         return SetFailure(reason);
        }
      m_open=true;
      m_writable=true;
      m_access_mode=V2_DB_ACCESS_READ_WRITE;
      m_status=V2_DB_STATUS_HEALTHY;

      if(config.mode==V2_DB_FULL_DURABLE)
        {
         if(!ExecuteSchemaStatement("PRAGMA journal_mode=DELETE;",reason) ||
            !ExecuteSchemaStatement("PRAGMA synchronous=FULL;",reason))
           { AbortOpen(); return SetFailure(reason); }
        }
      else
        {
         if(!ExecuteSchemaStatement("PRAGMA synchronous=OFF;",reason) ||
            !ExecuteSchemaStatement("PRAGMA temp_store=MEMORY;",reason))
           { AbortOpen(); return SetFailure(reason); }
        }

      if(!IntegrityCheck(reason))
        { AbortOpen(); return SetFailure(reason); }

      bool meta_exists=false;
      if(!TableExists("meta",meta_exists,reason))
        { AbortOpen(); return SetFailure(reason); }
      const string account_fingerprint=V2Sha256Hex(AccountInfoString(ACCOUNT_SERVER)+"|"+
                                                    IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));
      if(meta_exists)
        {
         string stored_deployment="",stored_account="";
         bool deployment_found=false,account_found=false;
         if(!ReadMeta("deployment_id",stored_deployment,deployment_found,reason) ||
            !ReadMeta("account_fingerprint",stored_account,account_found,reason) ||
            !deployment_found || !account_found || stored_deployment!=config.deployment_id ||
            stored_account!=account_fingerprint)
           {
            if(reason=="") reason="DATABASE_STABLE_IDENTITY_MISSING_OR_MISMATCH";
            AbortOpen();
            return SetFailure(reason);
           }
        }
      if(!meta_exists)
        {
         if(!Begin(reason) || !CreateSchema(reason) ||
            !WriteMeta("schema_version",IntegerToString(config.schema_version),reason) ||
            !Commit(reason))
           {
            if(m_in_transaction) Rollback();
            AbortOpen();
            return SetFailure(reason);
           }
        }
      else
        {
         string stored_schema="";
         bool schema_found=false;
         if(!ReadMeta("schema_version",stored_schema,schema_found,reason) || !schema_found ||
            IntegerToString((int)StringToInteger(stored_schema))!=stored_schema)
           {
            if(reason=="") reason="DATABASE_SCHEMA_VERSION_METADATA_INVALID";
            AbortOpen();
            return SetFailure(reason);
           }
         const int stored_version=(int)StringToInteger(stored_schema);
         if(stored_version!=config.schema_version)
           {
            if(stored_version==3 && !VerifyJournalIntegrity(false,false,reason))
              {
               reason="SCHEMA_MIGRATION_3_TO_4_SOURCE_AUDIT_FAILED:"+reason;
               AbortOpen();
               return SetFailure(reason);
              }
            if(!MigrateSchema(stored_version,config.schema_version,reason))
              { AbortOpen(); return SetFailure(reason); }
           }
         else
           {
            if(!ValidateCoreSchemaTables(true,reason) || !CreateSchema(reason))
              { AbortOpen(); return SetFailure(reason); }
           }
        }

      if(!ValidateCoreSchemaTables(true,reason))
        { AbortOpen(); return SetFailure(reason); }
      if(!meta_exists &&
         (!EnsureStableMetaIdentity("deployment_id",config.deployment_id,reason) ||
          !EnsureStableMetaIdentity("account_fingerprint",account_fingerprint,reason)))
        { AbortOpen(); return SetFailure(reason); }
      if(!WriteMeta("last_portfolio_generation_id",config.portfolio_generation_id,reason) ||
         !WriteMeta("last_strategy_member_id",config.strategy_member_id,reason) ||
         !WriteMeta("persistence_mode",V2StateDBModeName(config.mode),reason))
         { AbortOpen(); return SetFailure(reason); }

      string previous_owner="",previous_heartbeat="",previous_released="";
      bool owner_found=false,heartbeat_found=false,released_found=false;
      if(!ReadMeta("lease_owner",previous_owner,owner_found,reason) ||
         !ReadMeta("lease_heartbeat_msc",previous_heartbeat,heartbeat_found,reason) ||
         !ReadMeta("lease_released",previous_released,released_found,reason))
        { AbortOpen(); return SetFailure(reason); }
      if(config.mode==V2_DB_FULL_DURABLE && owner_found && previous_owner!=config.owner_instance_id &&
         (!released_found || previous_released!="1") && heartbeat_found)
        {
         const long heartbeat=(long)StringToInteger(previous_heartbeat);
         if(heartbeat<=0 || IntegerToString(heartbeat)!=previous_heartbeat)
           {
            reason="LEASE_HEARTBEAT_METADATA_INVALID";
            AbortOpen();
            return SetFailure(reason);
           }
         const long utc_now_msc=V2UtcNowMsc();
         if(utc_now_msc<=0)
           {
            reason="LEASE_UTC_CLOCK_UNAVAILABLE";
            AbortOpen();
            return SetFailure(reason);
           }
         if(heartbeat>utc_now_msc)
           {
            // The exclusive sentinel is the primary ownership proof.  A
            // persisted future heartbeat indicates a UTC clock regression;
            // fail closed for supervised recovery instead of waiting on a
            // timezone/DST jump or silently taking over.
            reason="LEASE_UTC_CLOCK_REGRESSION_REQUIRES_SUPERVISION";
            AbortOpen();
            return SetFailure(reason);
           }
         const long heartbeat_age_msc=utc_now_msc-heartbeat;
         if(heartbeat_age_msc<(long)config.lease_stale_seconds*1000)
           {
            reason="LEASE_HEARTBEAT_FRESH_FOR_DIFFERENT_OWNER";
            AbortOpen();
            return SetFailure(reason);
           }
        }

      if(!VerifyJournalIntegrity(true,true,reason))
        { AbortOpen(); return SetFailure(reason); }
      if(config.mode==V2_DB_FULL_DURABLE && !Heartbeat(reason))
        { AbortOpen(); return SetFailure(reason); }
      m_status=V2_DB_STATUS_HEALTHY;
      m_status_reason="";
      m_last_error="";
      return true;
     }

   bool OpenReadOnlyRecovery(const V2StateDBConfig &config,
                             const string recovery_trigger,
                             string &reason)
     {
      reason="";
      Close();
      m_last_error="";
      m_status_reason="";
      m_last_event_hash="";
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;
      m_config=config;
      if(!ValidateOpenConfig(config,true,reason)) return SetFailure(reason);

      ResetLastError();
      m_database=DatabaseOpen(config.database_path,DATABASE_OPEN_READONLY|DATABASE_OPEN_COMMON);
      if(m_database==INVALID_HANDLE)
        {
         reason="READ_ONLY_DATABASE_OPEN_FAILED:"+IntegerToString(GetLastError());
         AbortOpen();
         return SetFailure(reason);
        }
      m_open=true;
      m_writable=false;
      m_access_mode=V2_DB_ACCESS_READ_ONLY_RECOVERY;
      m_status=V2_DB_STATUS_READ_ONLY_EXPLICIT;
      m_status_reason=(recovery_trigger=="" ? "EXPLICIT_READ_ONLY_RECOVERY" : recovery_trigger);
      m_last_error=m_status_reason;
      m_lease.Release();

      if(StringFind(m_status_reason,"SCHEMA")>=0)
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
      else if(StringFind(m_status_reason,"INTEGRITY")>=0 ||
              StringFind(m_status_reason,"JOURNAL")>=0 ||
              StringFind(m_status_reason,"PROJECTION")>=0)
         m_status=V2_DB_STATUS_READ_ONLY_INTEGRITY;
      else if(StringFind(m_status_reason,"WRITE")>=0 ||
              StringFind(m_status_reason,"COMMIT")>=0 ||
              StringFind(m_status_reason,"ROLLBACK")>=0 ||
              StringFind(m_status_reason,"DATABASE_REQUEST")>=0)
         m_status=V2_DB_STATUS_READ_ONLY_WRITE_FAILURE;

      string audit_reason="";
      if(!IntegrityCheck(audit_reason))
        {
         m_status=V2_DB_STATUS_READ_ONLY_INTEGRITY;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+audit_reason;
         m_last_error=m_status_reason;
         return true;
        }

      bool meta_exists=false;
      if(!TableExists("meta",meta_exists,audit_reason) || !meta_exists)
        {
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+
                         (audit_reason=="" ? "META_TABLE_MISSING" : audit_reason);
         m_last_error=m_status_reason;
         return true;
        }
      string stored_schema="";
      bool schema_found=false;
      if(!ReadMeta("schema_version",stored_schema,schema_found,audit_reason) || !schema_found)
        {
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+
                         (audit_reason=="" ? "SCHEMA_VERSION_MISSING" : audit_reason);
         m_last_error=m_status_reason;
         return true;
        }
      const int stored_version=(int)StringToInteger(stored_schema);
      if((stored_version!=3 && stored_version!=V2_STATE_DB_SCHEMA_VERSION) ||
         IntegerToString(stored_version)!=stored_schema ||
         !ValidateCoreSchemaTables(stored_version==V2_STATE_DB_SCHEMA_VERSION,audit_reason))
        {
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+
                         (audit_reason=="" ? "UNSUPPORTED_STORED_SCHEMA:"+stored_schema : audit_reason);
         m_last_error=m_status_reason;
         return true;
        }
      if(stored_version==3)
        {
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
         m_status_reason=m_status_reason+"|SCHEMA_MIGRATION_3_TO_4_REQUIRED_FOR_WRITE";
         m_last_error=m_status_reason;
        }

      string stored_deployment="",stored_account="";
      bool deployment_found=false,account_found=false;
      const string account_fingerprint=V2Sha256Hex(AccountInfoString(ACCOUNT_SERVER)+"|"+
                                                    IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));
      if(!ReadMeta("deployment_id",stored_deployment,deployment_found,audit_reason) ||
         !ReadMeta("account_fingerprint",stored_account,account_found,audit_reason) ||
         !deployment_found || !account_found || stored_deployment!=config.deployment_id ||
         stored_account!=account_fingerprint)
        {
         m_status=V2_DB_STATUS_READ_ONLY_SCHEMA;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+
                         (audit_reason=="" ? "DATABASE_IDENTITY_MISMATCH" : audit_reason);
         m_last_error=m_status_reason;
         return true;
        }

      if(!VerifyJournalIntegrity(false,true,audit_reason))
        {
         m_status=V2_DB_STATUS_READ_ONLY_INTEGRITY;
         m_status_reason=m_status_reason+"|READ_ONLY_AUDIT:"+audit_reason;
         m_last_error=m_status_reason;
        }
      return true;
     }

   bool OpenOrRecoverReadOnly(const V2StateDBConfig &config,string &reason)
     {
      string write_reason="";
      if(Open(config,write_reason))
        {
         reason="";
         return true;
        }
      string recovery_reason="";
      if(OpenReadOnlyRecovery(config,write_reason,recovery_reason))
        {
         reason="";
         return true;
        }
      reason=write_reason+"|READ_ONLY_RECOVERY_FAILED:"+recovery_reason;
      return false;
     }

   bool ConfigureOutboxLimits(const long maximum_messages,
                              const long maximum_bytes,
                              string &reason)
     {
      reason="";
      if(maximum_messages<=0 || maximum_bytes<=0)
        { reason="OUTBOX_LIMIT_NOT_POSITIVE"; return false; }
      const long prior_messages=m_outbox_max_messages;
      const long prior_bytes=m_outbox_max_bytes;
      m_outbox_max_messages=maximum_messages;
      m_outbox_max_bytes=maximum_bytes;
      if(m_open && !CheckOutboxCapacity(0,0,reason))
        {
         if(reason=="OUTBOX_CAPACITY_EXHAUSTED")
           {
            // The database remains readable and protective management must
            // still initialize. RefreshStatus will force MANAGE_ONLY before
            // any new-risk gate is enabled.
            reason="";
            return true;
           }
         m_outbox_max_messages=prior_messages;
         m_outbox_max_bytes=prior_bytes;
         return false;
        }
      return true;
     }

   bool LoadRiskHighWater(const string key,
                          double &value,
                          bool &found,
                          string &reason)
     {
      value=0.0;
      found=false;
      reason="";
      if(!RequireReadable(reason)) return false;
      if(key=="" || V2SafeFileComponent(key)!=key)
        { reason="RISK_HIGH_WATER_KEY_INVALID"; return false; }
      string stored="";
      if(!ReadMeta("risk_high_water:"+key,stored,found,reason))
         return false;
      if(!found)
         return true;
      value=StringToDouble(stored);
      if(!MathIsValidNumber(value) || value<0.0 || V2CanonicalDouble(value)!=stored)
        {
         value=0.0;
         found=false;
         reason="RISK_HIGH_WATER_VALUE_INVALID";
         return false;
        }
      return true;
     }

   bool StoreRiskHighWater(const string key,const double value,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(key=="" || V2SafeFileComponent(key)!=key)
        { reason="RISK_HIGH_WATER_KEY_INVALID"; return false; }
      if(!MathIsValidNumber(value) || value<0.0)
        { reason="RISK_HIGH_WATER_VALUE_INVALID"; return false; }
      const string candidate_text=V2CanonicalDouble(value);
      const double candidate=StringToDouble(candidate_text);
      if(!MathIsValidNumber(candidate) || candidate<0.0)
        { reason="RISK_HIGH_WATER_VALUE_INVALID"; return false; }
      double prior=0.0;
      bool found=false;
      if(!LoadRiskHighWater(key,prior,found,reason))
         return false;
      if(found && candidate<prior)
        { reason="RISK_HIGH_WATER_REGRESSION"; return false; }
      if(found && candidate==prior)
         return true;
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason))
         return false;
      if(!WriteMeta("risk_high_water:"+key,candidate_text,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      if(own_transaction && !Commit(reason))
         return false;
      return true;
     }

   bool Begin(string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(m_in_transaction)
        { reason="DATABASE_TRANSACTION_ALREADY_ACTIVE"; return false; }
      if(!DatabaseTransactionBegin(m_database))
        {
         reason="DATABASE_BEGIN_FAILED:"+IntegerToString(GetLastError());
         PoisonWrites(reason);
         return false;
        }
      m_in_transaction=true;
      m_transaction_start_event_hash=m_last_event_hash;
      m_transaction_start_checkpoint_number=m_verified_checkpoint_number;
      m_transaction_start_checkpoint_hash=m_verified_checkpoint_hash;
      m_transaction_start_checkpoint_inherited=m_checkpoint_inherited;
      return true;
     }

   bool Commit(string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(!m_in_transaction)
        { reason="DATABASE_TRANSACTION_NOT_ACTIVE"; return false; }
      if(!DatabaseTransactionCommit(m_database))
        {
         reason="DATABASE_COMMIT_FAILED:"+IntegerToString(GetLastError());
         DatabaseTransactionRollback(m_database);
         m_last_event_hash=m_transaction_start_event_hash;
         m_verified_checkpoint_number=m_transaction_start_checkpoint_number;
         m_verified_checkpoint_hash=m_transaction_start_checkpoint_hash;
         m_checkpoint_inherited=m_transaction_start_checkpoint_inherited;
         m_transaction_start_event_hash="";
         m_transaction_start_checkpoint_number=0;
         m_transaction_start_checkpoint_hash="";
         m_transaction_start_checkpoint_inherited=false;
         m_in_transaction=false;
         PoisonWrites(reason);
         return false;
        }
      m_in_transaction=false;
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      return true;
     }

   void Rollback(void)
     {
      if(m_in_transaction)
        {
         if(!DatabaseTransactionRollback(m_database))
           {
            const string rollback_failure="DATABASE_ROLLBACK_FAILED:"+IntegerToString(GetLastError());
            PoisonWrites(rollback_failure);
           }
         m_last_event_hash=m_transaction_start_event_hash;
         m_verified_checkpoint_number=m_transaction_start_checkpoint_number;
         m_verified_checkpoint_hash=m_transaction_start_checkpoint_hash;
         m_checkpoint_inherited=m_transaction_start_checkpoint_inherited;
        }
      m_in_transaction=false;
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
     }

   bool ReserveCounter(const string counter_name,long &reserved_value,string &reason)
     {
      reserved_value=0;
      reason="";
      if(!RequireWritable(reason)) return false;
      if(counter_name=="" || V2SafeFileComponent(counter_name)!=counter_name)
        { reason="COUNTER_NAME_INVALID"; return false; }
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason))
         return false;

      bool found=false;
      long next_value=0;
      int request=DatabasePrepare(m_database,"SELECT next_value FROM counters WHERE counter_name=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,counter_name))
        {
         reason="COUNTER_SELECT_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         if(own_transaction) Rollback();
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
         found=DatabaseColumnLong(request,0,next_value);
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="COUNTER_SELECT_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         if(own_transaction) Rollback();
         return false;
        }
      DatabaseFinalize(request);
      if(found && next_value<=0)
        {
         reason="COUNTER_VALUE_INVALID";
         if(own_transaction) Rollback();
         return false;
        }
      reserved_value=found ? next_value : 1;
      const string sql=found ?
         "UPDATE counters SET next_value=?1 WHERE counter_name=?2;" :
         "INSERT INTO counters(next_value,counter_name) VALUES(?1,?2);";
      request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,reserved_value+1) ||
         !DatabaseBind(request,1,counter_name) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="COUNTER_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         if(own_transaction) Rollback();
         return false;
        }
      DatabaseFinalize(request);
      if(own_transaction && !Commit(reason))
         return false;
      return true;
     }

   bool AppendDomainEvent(V2DomainEvent &event,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(event.kind==V2_EVENT_NONE)
        { reason="DOMAIN_EVENT_KIND_NONE"; return false; }
      if(event.state_version<0 || (event.sequence_id!="" && event.state_version<=0))
        { reason="DOMAIN_EVENT_STATE_VERSION_INVALID"; return false; }
      if(!MathIsValidNumber(event.volume) ||
         !MathIsValidNumber(event.price) ||
         !MathIsValidNumber(event.realized_pl))
        { reason="DOMAIN_EVENT_NUMERIC_VALUE_INVALID"; return false; }

      bool existing=false;
      long existing_number=0;
      string existing_payload="",existing_hash="";
      if(!ReadExistingEvent(event.event_id,existing,existing_number,existing_payload,existing_hash,reason))
         return false;
      if(existing)
        {
         event.canonical_number=existing_number;
         const string candidate_payload=CanonicalEventPayload(event);
         const string candidate_identity=(m_config.mode==V2_DB_REDUCED) ?
                                         V2Sha256Hex(candidate_payload) : candidate_payload;
         if(existing_payload!=candidate_identity)
           { reason="DOMAIN_EVENT_ID_PAYLOAD_COLLISION"; return false; }
         event.event_hash=existing_hash;
         return true;
        }

      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason))
         return false;
      if(m_config.mode!=V2_DB_REDUCED && event.sequence_id!="")
        {
         long prior_state_version=0;
         int state_request=DatabasePrepare(m_database,
            "SELECT COALESCE(MAX(state_version),0) FROM domain_events WHERE sequence_id=?1;");
         if(state_request==INVALID_HANDLE ||
            !DatabaseBind(state_request,0,event.sequence_id) ||
            !DatabaseRead(state_request) ||
            !DatabaseColumnLong(state_request,0,prior_state_version))
           {
            reason="DOMAIN_EVENT_PRIOR_STATE_VERSION_READ_FAILED:"+IntegerToString(GetLastError());
            if(state_request!=INVALID_HANDLE) DatabaseFinalize(state_request);
            if(own_transaction) Rollback();
            return false;
           }
         DatabaseFinalize(state_request);
         if(event.state_version!=prior_state_version+1)
           {
            reason="DOMAIN_EVENT_STATE_VERSION_NOT_CONSECUTIVE";
            if(own_transaction) Rollback();
            return false;
           }
        }
      // Canonical ordering is owned exclusively by this journal. Resetting a
      // non-existing event also makes a caller-held object safe to retry after
      // an outer transaction rollback.
      event.canonical_number=0;
      event.event_hash="";
      if(!ReserveCounter("domain_event",event.canonical_number,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      const string payload=CanonicalEventPayload(event);
      const string previous=(m_last_event_hash=="") ? "GENESIS" : m_last_event_hash;
      if(event.event_id=="")
         event.event_id="evt_"+V2Sha256Hex(previous+"|"+payload);
      const string event_hash=V2Sha256Hex(previous+"|"+event.event_id+"|"+payload);
      if(event_hash=="")
        {
         reason="DOMAIN_EVENT_HASH_FAILED";
         if(own_transaction) Rollback();
         return false;
        }

      if(m_config.mode==V2_DB_REDUCED)
        {
         int request=DatabasePrepare(m_database,
            "INSERT INTO reduced_event_keys(event_id,canonical_number,payload_hash,event_hash) VALUES(?1,?2,?3,?4);");
         if(request==INVALID_HANDLE ||
            !DatabaseBind(request,0,event.event_id) ||
            !DatabaseBind(request,1,event.canonical_number) ||
            !DatabaseBind(request,2,V2Sha256Hex(payload)) ||
            !DatabaseBind(request,3,event_hash) ||
            !ExecutePreparedNoRows(request,reason))
           {
            if(reason=="") reason="REDUCED_EVENT_KEY_INSERT_FAILED:"+IntegerToString(GetLastError());
            if(request!=INVALID_HANDLE) DatabaseFinalize(request);
            if(own_transaction) Rollback();
            return false;
           }
         DatabaseFinalize(request);
        }
      else
        {
         int request=DatabasePrepare(m_database,
            "INSERT INTO domain_events(canonical_number,state_version,event_id,event_kind,action_kind,risk_effect,direction,symbol,occurred_at_msc,sequence_id,order_intent_id,level_index,request_id,order_ticket,deal_ticket,position_id,volume,price,realized_pl,retrace_advance,reason_code,canonical_payload,previous_hash,event_hash) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23,?24);");
         if(request==INVALID_HANDLE ||
            !DatabaseBind(request,0,event.canonical_number) ||
            !DatabaseBind(request,1,event.state_version) ||
            !DatabaseBind(request,2,event.event_id) ||
            !DatabaseBind(request,3,(int)event.kind) ||
            !DatabaseBind(request,4,(int)event.action) ||
            !DatabaseBind(request,5,(int)event.risk_effect) ||
            !DatabaseBind(request,6,(int)event.direction) ||
            !DatabaseBind(request,7,event.symbol) ||
            !DatabaseBind(request,8,(long)event.occurred_at*1000) ||
            !DatabaseBind(request,9,event.sequence_id) ||
            !DatabaseBind(request,10,event.order_intent_id) ||
            !DatabaseBind(request,11,event.level_index) ||
            !DatabaseBind(request,12,V2UlongToText(event.request_id)) ||
            !DatabaseBind(request,13,V2UlongToText(event.order_ticket)) ||
            !DatabaseBind(request,14,V2UlongToText(event.deal_ticket)) ||
            !DatabaseBind(request,15,V2UlongToText(event.position_id)) ||
            !DatabaseBind(request,16,event.volume) ||
             !DatabaseBind(request,17,event.price) ||
             !DatabaseBind(request,18,event.realized_pl) ||
             !DatabaseBind(request,19,event.retrace_advance ? 1 : 0) ||
             !DatabaseBind(request,20,event.reason_code) ||
             !DatabaseBind(request,21,payload) ||
             !DatabaseBind(request,22,previous) ||
             !DatabaseBind(request,23,event_hash) ||
            !ExecutePreparedNoRows(request,reason))
           {
            if(reason=="") reason="DOMAIN_EVENT_INSERT_FAILED:"+IntegerToString(GetLastError());
            if(request!=INVALID_HANDLE) DatabaseFinalize(request);
            if(own_transaction) Rollback();
            return false;
           }
         DatabaseFinalize(request);
         if(!WriteMeta("last_event_hash",event_hash,reason))
           {
            if(own_transaction) Rollback();
            return false;
           }
         const string verified_head=(m_last_event_hash=="" ? "GENESIS" : m_last_event_hash);
         if(m_verified_checkpoint_hash=="" ||
            m_verified_checkpoint_number!=event.canonical_number-1 ||
            m_verified_checkpoint_hash!=verified_head)
           {
            reason="JOURNAL_CHECKPOINT_PREDECESSOR_NOT_VERIFIED";
            if(own_transaction) Rollback();
            return false;
           }
         // The new event, updated journal head, and advanced checkpoint share
         // the same transaction.  This inductive step keeps restart work
         // bounded to events written outside the normal StateDB path while the
         // append-only guards preserve the already-verified prefix.
         if(!PersistJournalCheckpoint(event.canonical_number,event_hash,
                                      "TRANSACTIONALLY_VERIFIED_APPEND",reason))
           {
            if(own_transaction) Rollback();
            return false;
           }
        }
      m_last_event_hash=event_hash;
      event.event_hash=event_hash;
      if(m_config.mode!=V2_DB_REDUCED)
        {
         m_verified_checkpoint_number=event.canonical_number;
         m_verified_checkpoint_hash=event_hash;
         m_checkpoint_inherited=true;
        }
      if(own_transaction && !Commit(reason))
         return false;
      return true;
     }

   bool StoreReceipt(V2Receipt &receipt,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(receipt.receipt_id=="")
        {
         CV2ReceiptBuilder builder;
         if(!builder.Build(receipt,reason)) return false;
        }
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason)) return false;
      if(!StoreReceiptInternal(receipt,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      if(own_transaction && !Commit(reason)) return false;
      return true;
     }

   bool PersistOrderIntentAndReceipt(const V2OrderIntent &intent,
                                     V2Receipt &receipt,
                                     bool &newly_inserted,
                                     string &reason)
     {
      newly_inserted=false;
      reason="";
      if(!RequireWritable(reason)) return false;
      if(receipt.order_intent_id!=intent.order_intent_id ||
         receipt.sequence_id!=intent.sequence_id ||
         receipt.action!=intent.action ||
         receipt.risk_effect!=intent.risk_effect ||
         receipt.direction!=intent.direction ||
         receipt.level_index!=intent.level_index ||
         receipt.symbol!=intent.symbol ||
         receipt.requested_volume!=intent.requested_volume ||
         receipt.requested_price!=intent.requested_price ||
         receipt.stop_loss!=intent.stop_loss ||
         receipt.take_profit!=intent.take_profit)
        { reason="INTENT_RECEIPT_LINEAGE_OR_PAYLOAD_MISMATCH"; return false; }
      if(receipt.receipt_id=="")
        {
         CV2ReceiptBuilder builder;
         if(!builder.Build(receipt,reason)) return false;
        }
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason)) return false;
      if(!InsertIntentInternal(intent,newly_inserted,reason) || !StoreReceiptInternal(receipt,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      if(own_transaction && !Commit(reason)) return false;
      return true;
     }

   bool PersistOrderIntentAndReceipt(const V2OrderIntent &intent,V2Receipt &receipt,string &reason)
     {
      bool newly_inserted=false;
      return PersistOrderIntentAndReceipt(intent,receipt,newly_inserted,reason);
     }

   bool UpdateOrderIntent(const V2OrderIntent &intent,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason))
         return false;
      if(!UpdateIntentCanonicalInternal(intent,false,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      if(own_transaction && !Commit(reason))
         return false;
      return true;
     }

   bool AuthorizeBrokerSubmission(const V2OrderIntent &intent,
                                  const V2Receipt &source_receipt,
                                  const bool action_proven_risk_reducing,
                                  V2PersistenceAuthorization &authorization)
      {
      authorization.Reset();
      string access_reason="";
      if(!RequireWritable(access_reason))
        {
         authorization.reason=access_reason;
         authorization.requires_manage_only=true;
         return false;
        }
      if(m_in_transaction)
        {
         authorization.reason="BROKER_AUTHORIZATION_REQUIRES_OWN_COMMITTED_TRANSACTION";
         return false;
        }
      V2Receipt receipt=source_receipt;
      string persist_reason="";
      bool newly_inserted=false;
      if(PersistOrderIntentAndReceipt(intent,receipt,newly_inserted,persist_reason))
        {
         if(!newly_inserted)
           {
            authorization.requires_manage_only=true;
            authorization.reason="INTENT_ALREADY_RECORDED_RECONCILIATION_REQUIRED";
            return false;
           }
         authorization.outcome=V2_PERSISTENCE_RECORDED;
         authorization.broker_submission_allowed=true;
         authorization.durable=IsDurable();
         authorization.reason="INTENT_RECORDED";
         return true;
        }

      authorization.requires_manage_only=true;
      authorization.reason=(action_proven_risk_reducing ?
                            "DURABLE_PERSISTENCE_REQUIRED_FOR_REDUCTION:" :
                            "PERSISTENCE_CONTRACT_FAILURE:")+persist_reason;
      // V2.0 deliberately has no process-memory-only broker exception.  A
      // reduction without a durable intent cannot be recovered after a crash;
      // protective server orders remain the fail-safe while persistence is
      // unavailable.
      return false;
     }

   bool PersistSubmissionResult(const V2OrderIntent &intent,
                                V2DomainEvent &event,
                                V2Receipt &receipt,
                                string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason)) return false;
      if(!UpdateIntentCanonicalInternal(intent,true,reason) || !AppendDomainEvent(event,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      // AppendDomainEvent owns canonical ordering. Rebuild the causal receipt
      // only after the event has its final number, identity, and hash so both
      // artifacts commit atomically with identical lineage.
      receipt.canonical_number=event.canonical_number;
      receipt.state_version=event.state_version;
      receipt.event_id=event.event_id;
      receipt.occurred_at_msc=(long)event.occurred_at*1000;
      receipt.request_id=event.request_id;
      receipt.order_ticket=event.order_ticket;
      receipt.deal_ticket=event.deal_ticket;
      receipt.position_id=event.position_id;
      receipt.retcode=intent.retcode;
      receipt.receipt_id="";
      receipt.payload_hash="";
      receipt.canonical_payload="";
      if(!StoreReceipt(receipt,reason))
        {
         if(own_transaction) Rollback();
         return false;
        }
      if(own_transaction && !Commit(reason)) return false;
      return true;
     }

   bool SaveSequenceProjection(const V2SequenceState &state,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      int request=DatabasePrepare(m_database,
         "SELECT last_state_version,last_event_number,last_event_id,last_event_hash FROM sequences WHERE sequence_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,state.sequence_id))
        {
         reason="SEQUENCE_PROJECTION_VERSION_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         long stored_state_version=0,stored_event_number=0;
         string stored_event_id="",stored_event_hash="";
         const bool read=DatabaseColumnLong(request,0,stored_state_version) &&
                         DatabaseColumnLong(request,1,stored_event_number) &&
                         DatabaseColumnText(request,2,stored_event_id) &&
                         DatabaseColumnText(request,3,stored_event_hash);
         DatabaseFinalize(request);
         if(!read)
           { reason="SEQUENCE_PROJECTION_VERSION_COLUMN_FAILED"; return false; }
         if(state.last_state_version<stored_state_version ||
            state.last_event_number<stored_event_number)
           { reason="SEQUENCE_PROJECTION_REGRESSION"; return false; }
         if(state.last_state_version==stored_state_version)
           {
            if(state.last_event_number!=stored_event_number ||
               state.last_event_id!=stored_event_id ||
               state.last_event_hash!=stored_event_hash)
              { reason="SEQUENCE_PROJECTION_VERSION_COLLISION"; return false; }
            return true;
           }
         if(state.last_event_number<=stored_event_number)
           { reason="SEQUENCE_PROJECTION_EVENT_ORDER_REGRESSION"; return false; }
        }
      else
        {
         const int error=GetLastError();
         DatabaseFinalize(request);
         if(error!=ERR_DATABASE_NO_MORE_DATA)
           { reason="SEQUENCE_PROJECTION_VERSION_READ_FAILED:"+IntegerToString(error); return false; }
        }
      request=DatabasePrepare(m_database,
         "INSERT OR REPLACE INTO sequences(sequence_id,strategy_member_id,symbol,direction,status,started_at_msc,ended_at_msc,last_event_number,last_state_version,last_event_id,last_event_hash,experiment_manifest_id,input_values_hash,broker_profile_hash,symbol_spec_hash,execution_plan_hash,level_count,max_levels,start_volume,standing_volume,average_entry_price,realized_pl,commission,swap,mlps_budget,mlps_used,retrace_price,rescue_armed,reduction_remaining,reduction_semantic_level,reduction_reason,retrace_advance_pending) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,?31,?32);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,state.sequence_id) ||
         !DatabaseBind(request,1,state.strategy_member_id) ||
         !DatabaseBind(request,2,state.symbol) ||
         !DatabaseBind(request,3,(int)state.direction) ||
         !DatabaseBind(request,4,(int)state.status) ||
         !DatabaseBind(request,5,(long)state.started_at*1000) ||
         !DatabaseBind(request,6,(long)state.ended_at*1000) ||
         !DatabaseBind(request,7,state.last_event_number) ||
         !DatabaseBind(request,8,state.last_state_version) ||
          !DatabaseBind(request,9,state.last_event_id) ||
          !DatabaseBind(request,10,state.last_event_hash) ||
          !DatabaseBind(request,11,state.experiment_manifest_id) ||
          !DatabaseBind(request,12,state.input_values_hash) ||
          !DatabaseBind(request,13,state.broker_profile_hash) ||
          !DatabaseBind(request,14,state.symbol_spec_hash) ||
          !DatabaseBind(request,15,state.execution_plan_hash) ||
          !DatabaseBind(request,16,state.level_count) ||
          !DatabaseBind(request,17,state.max_levels) ||
          !DatabaseBind(request,18,state.start_volume) ||
          !DatabaseBind(request,19,state.standing_volume) ||
          !DatabaseBind(request,20,state.average_entry_price) ||
          !DatabaseBind(request,21,state.realized_pl) ||
          !DatabaseBind(request,22,state.commission) ||
          !DatabaseBind(request,23,state.swap) ||
          !DatabaseBind(request,24,state.mlps_budget) ||
          !DatabaseBind(request,25,state.mlps_used) ||
          !DatabaseBind(request,26,state.retrace_price) ||
          !DatabaseBind(request,27,state.rescue_armed ? 1 : 0) ||
          !DatabaseBind(request,28,state.reduction_remaining) ||
          !DatabaseBind(request,29,state.reduction_semantic_level) ||
          !DatabaseBind(request,30,state.reduction_reason) ||
          !DatabaseBind(request,31,state.retrace_advance_pending ? 1 : 0) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="SEQUENCE_PROJECTION_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool SaveLevelProjection(const V2LevelState &state,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      int request=DatabasePrepare(m_database,
         "INSERT OR REPLACE INTO levels(sequence_id,level_index,planned_price,requested_volume,filled_volume,average_fill_price,position_id,virtual_level,closed) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,state.sequence_id) ||
         !DatabaseBind(request,1,state.level_index) ||
         !DatabaseBind(request,2,state.planned_price) ||
         !DatabaseBind(request,3,state.requested_volume) ||
         !DatabaseBind(request,4,state.filled_volume) ||
         !DatabaseBind(request,5,state.average_fill_price) ||
         !DatabaseBind(request,6,V2UlongToText(state.position_id)) ||
         !DatabaseBind(request,7,state.virtual_level ? 1 : 0) ||
         !DatabaseBind(request,8,state.closed ? 1 : 0) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="LEVEL_PROJECTION_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool LoadSequenceLevels(const string sequence_id,V2LevelState &levels[],string &reason)
     {
      ArrayResize(levels,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(sequence_id=="")
        { reason="LEVEL_PROJECTION_SEQUENCE_ID_EMPTY"; return false; }
      int request=DatabasePrepare(m_database,
         "SELECT sequence_id,level_index,planned_price,requested_volume,filled_volume,average_fill_price,position_id,virtual_level,closed FROM levels WHERE sequence_id=?1 ORDER BY level_index ASC;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,sequence_id))
        {
         reason="LEVEL_PROJECTION_LOAD_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="LEVEL_PROJECTION_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         if(ArrayResize(levels,count+1)!=count+1)
           {
            reason="LEVEL_PROJECTION_ALLOCATION_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         levels[count].Reset();
         string position_text="";
         int virtual_level=0,closed=0;
         const bool read=DatabaseColumnText(request,0,levels[count].sequence_id) &&
                         DatabaseColumnInteger(request,1,levels[count].level_index) &&
                         DatabaseColumnDouble(request,2,levels[count].planned_price) &&
                         DatabaseColumnDouble(request,3,levels[count].requested_volume) &&
                         DatabaseColumnDouble(request,4,levels[count].filled_volume) &&
                         DatabaseColumnDouble(request,5,levels[count].average_fill_price) &&
                         DatabaseColumnText(request,6,position_text) &&
                         DatabaseColumnInteger(request,7,virtual_level) &&
                         DatabaseColumnInteger(request,8,closed);
         if(!read || !V2TextToUlong(position_text,levels[count].position_id))
           {
            reason="LEVEL_PROJECTION_COLUMN_OR_ID_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         levels[count].virtual_level=(virtual_level!=0);
         levels[count].closed=(closed!=0);
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool LoadSequenceProjection(const string sequence_id,V2SequenceState &state,bool &found,string &reason)
     {
      state.Reset();
      found=false;
      reason="";
      if(!RequireReadable(reason)) return false;
      int request=DatabasePrepare(m_database,
         "SELECT sequence_id,strategy_member_id,symbol,direction,status,started_at_msc,ended_at_msc,last_event_number,last_state_version,last_event_id,last_event_hash,experiment_manifest_id,input_values_hash,broker_profile_hash,symbol_spec_hash,execution_plan_hash,level_count,max_levels,start_volume,standing_volume,average_entry_price,realized_pl,commission,swap,mlps_budget,mlps_used,retrace_price,rescue_armed,reduction_remaining,reduction_semantic_level,reduction_reason,retrace_advance_pending FROM sequences WHERE sequence_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,sequence_id))
        {
         reason="SEQUENCE_PROJECTION_SELECT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(!DatabaseRead(request))
        {
         const int error=GetLastError();
         DatabaseFinalize(request);
         if(error==ERR_DATABASE_NO_MORE_DATA) return true;
         reason="SEQUENCE_PROJECTION_READ_FAILED:"+IntegerToString(error);
         return false;
        }
      int direction=0,status=0,rescue=0,retrace_pending=0;
      long started_msc=0,ended_msc=0;
      found=DatabaseColumnText(request,0,state.sequence_id) &&
            DatabaseColumnText(request,1,state.strategy_member_id) &&
            DatabaseColumnText(request,2,state.symbol) &&
            DatabaseColumnInteger(request,3,direction) &&
            DatabaseColumnInteger(request,4,status) &&
            DatabaseColumnLong(request,5,started_msc) &&
             DatabaseColumnLong(request,6,ended_msc) &&
             DatabaseColumnLong(request,7,state.last_event_number) &&
             DatabaseColumnLong(request,8,state.last_state_version) &&
             DatabaseColumnText(request,9,state.last_event_id) &&
             DatabaseColumnText(request,10,state.last_event_hash) &&
             DatabaseColumnText(request,11,state.experiment_manifest_id) &&
             DatabaseColumnText(request,12,state.input_values_hash) &&
             DatabaseColumnText(request,13,state.broker_profile_hash) &&
             DatabaseColumnText(request,14,state.symbol_spec_hash) &&
             DatabaseColumnText(request,15,state.execution_plan_hash) &&
             DatabaseColumnInteger(request,16,state.level_count) &&
             DatabaseColumnInteger(request,17,state.max_levels) &&
             DatabaseColumnDouble(request,18,state.start_volume) &&
             DatabaseColumnDouble(request,19,state.standing_volume) &&
             DatabaseColumnDouble(request,20,state.average_entry_price) &&
             DatabaseColumnDouble(request,21,state.realized_pl) &&
             DatabaseColumnDouble(request,22,state.commission) &&
             DatabaseColumnDouble(request,23,state.swap) &&
             DatabaseColumnDouble(request,24,state.mlps_budget) &&
             DatabaseColumnDouble(request,25,state.mlps_used) &&
             DatabaseColumnDouble(request,26,state.retrace_price) &&
             DatabaseColumnInteger(request,27,rescue) &&
             DatabaseColumnDouble(request,28,state.reduction_remaining) &&
             DatabaseColumnInteger(request,29,state.reduction_semantic_level) &&
             DatabaseColumnText(request,30,state.reduction_reason) &&
             DatabaseColumnInteger(request,31,retrace_pending);
      DatabaseFinalize(request);
      if(!found)
        { reason="SEQUENCE_PROJECTION_COLUMN_FAILED:"+IntegerToString(GetLastError()); return false; }
      state.direction=(ENUM_V2_DIRECTION)direction;
      state.status=(ENUM_V2_SEQUENCE_STATUS)status;
      state.started_at=(datetime)(started_msc/1000);
      state.ended_at=(datetime)(ended_msc/1000);
      state.rescue_armed=(rescue!=0);
      state.retrace_advance_pending=(retrace_pending!=0);
      return true;
     }

   bool LoadManageableSequences(const string strategy_member_id,
                                V2SequenceState &states[],
                                string &reason)
     {
      ArrayResize(states,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(strategy_member_id=="")
        { reason="MANAGEABLE_SEQUENCE_MEMBER_ID_EMPTY"; return false; }
      int request=DatabasePrepare(m_database,
         "SELECT sequence_id,strategy_member_id,symbol,direction,status,started_at_msc,ended_at_msc,last_event_number,last_state_version,last_event_id,last_event_hash,experiment_manifest_id,input_values_hash,broker_profile_hash,symbol_spec_hash,execution_plan_hash,level_count,max_levels,start_volume,standing_volume,average_entry_price,realized_pl,commission,swap,mlps_budget,mlps_used,retrace_price,rescue_armed,reduction_remaining,reduction_semantic_level,reduction_reason,retrace_advance_pending FROM sequences WHERE strategy_member_id=?1 AND status IN (?2,?3,?4) ORDER BY sequence_id ASC;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,strategy_member_id) ||
         !DatabaseBind(request,1,(int)V2_SEQ_ACTIVE) ||
         !DatabaseBind(request,2,(int)V2_SEQ_REDUCE_ONLY) ||
         !DatabaseBind(request,3,(int)V2_SEQ_QUARANTINED))
        {
         reason="MANAGEABLE_SEQUENCE_SELECT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }

      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="MANAGEABLE_SEQUENCE_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         if(ArrayResize(states,count+1)!=count+1)
           {
            reason="MANAGEABLE_SEQUENCE_ALLOCATION_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         states[count].Reset();
         int direction=0,status=0,rescue=0,retrace_pending=0;
         long started_msc=0,ended_msc=0;
         const bool read=DatabaseColumnText(request,0,states[count].sequence_id) &&
                         DatabaseColumnText(request,1,states[count].strategy_member_id) &&
                         DatabaseColumnText(request,2,states[count].symbol) &&
                         DatabaseColumnInteger(request,3,direction) &&
                         DatabaseColumnInteger(request,4,status) &&
                         DatabaseColumnLong(request,5,started_msc) &&
                         DatabaseColumnLong(request,6,ended_msc) &&
                         DatabaseColumnLong(request,7,states[count].last_event_number) &&
                          DatabaseColumnLong(request,8,states[count].last_state_version) &&
                          DatabaseColumnText(request,9,states[count].last_event_id) &&
                          DatabaseColumnText(request,10,states[count].last_event_hash) &&
                          DatabaseColumnText(request,11,states[count].experiment_manifest_id) &&
                          DatabaseColumnText(request,12,states[count].input_values_hash) &&
                          DatabaseColumnText(request,13,states[count].broker_profile_hash) &&
                          DatabaseColumnText(request,14,states[count].symbol_spec_hash) &&
                          DatabaseColumnText(request,15,states[count].execution_plan_hash) &&
                          DatabaseColumnInteger(request,16,states[count].level_count) &&
                          DatabaseColumnInteger(request,17,states[count].max_levels) &&
                          DatabaseColumnDouble(request,18,states[count].start_volume) &&
                          DatabaseColumnDouble(request,19,states[count].standing_volume) &&
                          DatabaseColumnDouble(request,20,states[count].average_entry_price) &&
                          DatabaseColumnDouble(request,21,states[count].realized_pl) &&
                          DatabaseColumnDouble(request,22,states[count].commission) &&
                          DatabaseColumnDouble(request,23,states[count].swap) &&
                          DatabaseColumnDouble(request,24,states[count].mlps_budget) &&
                          DatabaseColumnDouble(request,25,states[count].mlps_used) &&
                          DatabaseColumnDouble(request,26,states[count].retrace_price) &&
                          DatabaseColumnInteger(request,27,rescue) &&
                          DatabaseColumnDouble(request,28,states[count].reduction_remaining) &&
                          DatabaseColumnInteger(request,29,states[count].reduction_semantic_level) &&
                          DatabaseColumnText(request,30,states[count].reduction_reason) &&
                          DatabaseColumnInteger(request,31,retrace_pending);
         if(!read)
           {
            reason="MANAGEABLE_SEQUENCE_COLUMN_FAILED:"+IntegerToString(GetLastError());
            DatabaseFinalize(request);
            return false;
           }
         states[count].direction=(ENUM_V2_DIRECTION)direction;
         states[count].status=(ENUM_V2_SEQUENCE_STATUS)status;
         states[count].started_at=(datetime)(started_msc/1000);
         states[count].ended_at=(datetime)(ended_msc/1000);
         states[count].rescue_armed=(rescue!=0);
         states[count].retrace_advance_pending=(retrace_pending!=0);
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool LoadEventsAfter(const long canonical_number,V2DomainEvent &events[],string &reason)
     {
      ArrayResize(events,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED)
         return true;
      int request=DatabasePrepare(m_database,
         "SELECT canonical_number,state_version,event_id,event_kind,action_kind,risk_effect,direction,symbol,occurred_at_msc,sequence_id,order_intent_id,level_index,request_id,order_ticket,deal_ticket,position_id,volume,price,realized_pl,retrace_advance,reason_code,event_hash FROM domain_events WHERE canonical_number>?1 ORDER BY canonical_number ASC;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,canonical_number))
        {
         reason="EVENT_REPLAY_SELECT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              { reason="EVENT_REPLAY_READ_FAILED:"+IntegerToString(error); DatabaseFinalize(request); return false; }
            break;
           }
         if(ArrayResize(events,count+1)!=count+1)
           { reason="EVENT_REPLAY_ALLOCATION_FAILED"; DatabaseFinalize(request); return false; }
         events[count].Reset();
         int kind=0,action=0,risk_effect=0,direction=0,retrace_advance=0;
         long occurred_msc=0;
         string request_text="",order_text="",deal_text="",position_text="";
         bool ok=DatabaseColumnLong(request,0,events[count].canonical_number) &&
                  DatabaseColumnLong(request,1,events[count].state_version) &&
                  DatabaseColumnText(request,2,events[count].event_id) &&
                  DatabaseColumnInteger(request,3,kind) &&
                  DatabaseColumnInteger(request,4,action) &&
                  DatabaseColumnInteger(request,5,risk_effect) &&
                  DatabaseColumnInteger(request,6,direction) &&
                  DatabaseColumnText(request,7,events[count].symbol) &&
                  DatabaseColumnLong(request,8,occurred_msc) &&
                  DatabaseColumnText(request,9,events[count].sequence_id) &&
                  DatabaseColumnText(request,10,events[count].order_intent_id) &&
                  DatabaseColumnInteger(request,11,events[count].level_index) &&
                  DatabaseColumnText(request,12,request_text) &&
                  DatabaseColumnText(request,13,order_text) &&
                  DatabaseColumnText(request,14,deal_text) &&
                  DatabaseColumnText(request,15,position_text) &&
                  DatabaseColumnDouble(request,16,events[count].volume) &&
                   DatabaseColumnDouble(request,17,events[count].price) &&
                   DatabaseColumnDouble(request,18,events[count].realized_pl) &&
                   DatabaseColumnInteger(request,19,retrace_advance) &&
                   DatabaseColumnText(request,20,events[count].reason_code) &&
                   DatabaseColumnText(request,21,events[count].event_hash);
         if(!ok || !V2TextToUlong(request_text,events[count].request_id) ||
            !V2TextToUlong(order_text,events[count].order_ticket) ||
            !V2TextToUlong(deal_text,events[count].deal_ticket) ||
            !V2TextToUlong(position_text,events[count].position_id))
           { reason="EVENT_REPLAY_COLUMN_OR_ID_FAILED"; DatabaseFinalize(request); return false; }
         events[count].kind=(ENUM_V2_EVENT_KIND)kind;
         events[count].action=(ENUM_V2_ACTION_KIND)action;
         events[count].risk_effect=(ENUM_V2_RISK_EFFECT)risk_effect;
         events[count].direction=(ENUM_V2_DIRECTION)direction;
         events[count].occurred_at=(datetime)(occurred_msc/1000);
         events[count].retrace_advance=(retrace_advance!=0);
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool FindFillEventByDeal(const ulong deal_ticket,
                            V2DomainEvent &event,
                            bool &found,
                            string &reason)
     {
      event.Reset();
      found=false;
      reason="";
      if(!RequireReadable(reason)) return false;
      if(deal_ticket==0)
        { reason="FILL_EVENT_DEAL_TICKET_ZERO"; return false; }
      if(m_config.mode==V2_DB_REDUCED)
         return true;
      int request=DatabasePrepare(m_database,
         "SELECT canonical_number,state_version,event_id,event_kind,action_kind,risk_effect,direction,symbol,occurred_at_msc,sequence_id,order_intent_id,level_index,request_id,order_ticket,deal_ticket,position_id,volume,price,realized_pl,retrace_advance,reason_code,event_hash FROM domain_events WHERE deal_ticket=?1 AND event_kind IN (?2,?3) ORDER BY canonical_number ASC LIMIT 2;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,V2UlongToText(deal_ticket)) ||
         !DatabaseBind(request,1,(int)V2_EVENT_FILL_PARTIAL) ||
         !DatabaseBind(request,2,(int)V2_EVENT_FILL_COMPLETE))
        {
         reason="FILL_EVENT_LOOKUP_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(!DatabaseRead(request))
        {
         const int error=GetLastError();
         DatabaseFinalize(request);
         if(error==ERR_DATABASE_NO_MORE_DATA) return true;
         reason="FILL_EVENT_LOOKUP_READ_FAILED:"+IntegerToString(error);
         return false;
        }

      int kind=0,action=0,risk_effect=0,direction=0,retrace_advance=0;
      long occurred_msc=0;
      string request_text="",order_text="",deal_text="",position_text="";
      const bool columns=DatabaseColumnLong(request,0,event.canonical_number) &&
                         DatabaseColumnLong(request,1,event.state_version) &&
                         DatabaseColumnText(request,2,event.event_id) &&
                         DatabaseColumnInteger(request,3,kind) &&
                         DatabaseColumnInteger(request,4,action) &&
                         DatabaseColumnInteger(request,5,risk_effect) &&
                         DatabaseColumnInteger(request,6,direction) &&
                         DatabaseColumnText(request,7,event.symbol) &&
                         DatabaseColumnLong(request,8,occurred_msc) &&
                         DatabaseColumnText(request,9,event.sequence_id) &&
                         DatabaseColumnText(request,10,event.order_intent_id) &&
                         DatabaseColumnInteger(request,11,event.level_index) &&
                         DatabaseColumnText(request,12,request_text) &&
                         DatabaseColumnText(request,13,order_text) &&
                         DatabaseColumnText(request,14,deal_text) &&
                         DatabaseColumnText(request,15,position_text) &&
                         DatabaseColumnDouble(request,16,event.volume) &&
                         DatabaseColumnDouble(request,17,event.price) &&
                         DatabaseColumnDouble(request,18,event.realized_pl) &&
                         DatabaseColumnInteger(request,19,retrace_advance) &&
                         DatabaseColumnText(request,20,event.reason_code) &&
                         DatabaseColumnText(request,21,event.event_hash);
      if(!columns || !V2TextToUlong(request_text,event.request_id) ||
         !V2TextToUlong(order_text,event.order_ticket) ||
         !V2TextToUlong(deal_text,event.deal_ticket) ||
         !V2TextToUlong(position_text,event.position_id) ||
         event.deal_ticket!=deal_ticket)
        {
         reason="FILL_EVENT_LOOKUP_COLUMN_OR_ID_FAILED";
         DatabaseFinalize(request);
         return false;
        }
      event.kind=(ENUM_V2_EVENT_KIND)kind;
      event.action=(ENUM_V2_ACTION_KIND)action;
      event.risk_effect=(ENUM_V2_RISK_EFFECT)risk_effect;
      event.direction=(ENUM_V2_DIRECTION)direction;
      event.occurred_at=(datetime)(occurred_msc/1000);
      event.retrace_advance=(retrace_advance!=0);

      ResetLastError();
      if(DatabaseRead(request))
        {
         DatabaseFinalize(request);
         event.Reset();
         reason="FILL_EVENT_DEAL_AMBIGUOUS";
         return false;
        }
      const int tail_error=GetLastError();
      DatabaseFinalize(request);
      if(tail_error!=ERR_DATABASE_NO_MORE_DATA)
        {
         event.Reset();
         reason="FILL_EVENT_LOOKUP_TAIL_READ_FAILED:"+IntegerToString(tail_error);
         return false;
        }
      found=true;
      return true;
     }

   bool GetLastCanonicalNumber(long &canonical_number,string &reason)
     {
      canonical_number=0;
      reason="";
      if(!RequireReadable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED)
        {
         int request=DatabasePrepare(m_database,
            "SELECT COALESCE(MAX(canonical_number),0) FROM reduced_event_keys;");
         if(request==INVALID_HANDLE || !DatabaseRead(request) ||
            !DatabaseColumnLong(request,0,canonical_number))
           {
            reason="REDUCED_CANONICAL_OFFSET_READ_FAILED:"+IntegerToString(GetLastError());
            if(request!=INVALID_HANDLE) DatabaseFinalize(request);
            return false;
           }
         DatabaseFinalize(request);
         return true;
        }
      int request=DatabasePrepare(m_database,
         "SELECT COALESCE(MAX(canonical_number),0) FROM domain_events;");
      if(request==INVALID_HANDLE || !DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,canonical_number))
        {
         reason="CANONICAL_OFFSET_READ_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool StoreTradeObservation(V2TradeObservation &observation,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(!MathIsValidNumber(observation.volume) ||
         !MathIsValidNumber(observation.price) ||
         !MathIsValidNumber(observation.stop_loss) ||
         !MathIsValidNumber(observation.take_profit))
        { reason="TRADE_OBSERVATION_NUMERIC_VALUE_INVALID"; return false; }
      string canonical="{";
      canonical+="\"schemaVersion\":\"goat2-trade-observation-v1\",";
      canonical+="\"capturedAtMsc\":"+IntegerToString(observation.captured_at_msc)+",";
      canonical+="\"transactionType\":"+IntegerToString(observation.transaction_type)+",";
      canonical+="\"requestId\":"+V2JsonQuote(V2UlongToText(observation.request_id))+",";
      canonical+="\"orderTicket\":"+V2JsonQuote(V2UlongToText(observation.order_ticket))+",";
      canonical+="\"dealTicket\":"+V2JsonQuote(V2UlongToText(observation.deal_ticket))+",";
      canonical+="\"positionId\":"+V2JsonQuote(V2UlongToText(observation.position_id))+",";
      canonical+="\"positionById\":"+V2JsonQuote(V2UlongToText(observation.position_by_id))+",";
      canonical+="\"symbol\":"+V2JsonQuote(observation.symbol)+",";
      canonical+="\"orderType\":"+IntegerToString(observation.order_type)+",";
      canonical+="\"orderState\":"+IntegerToString(observation.order_state)+",";
      canonical+="\"dealType\":"+IntegerToString(observation.deal_type)+",";
      canonical+="\"volume\":"+V2CanonicalDouble(observation.volume)+",";
      canonical+="\"price\":"+V2CanonicalDouble(observation.price)+",";
      canonical+="\"stopLoss\":"+V2CanonicalDouble(observation.stop_loss)+",";
      canonical+="\"takeProfit\":"+V2CanonicalDouble(observation.take_profit)+",";
      canonical+="\"retcode\":"+IntegerToString((long)observation.retcode)+",";
      canonical+="\"retcodeExternal\":"+IntegerToString((long)observation.retcode_external)+",";
      canonical+="\"comment\":"+V2JsonQuote(observation.comment);
      canonical+="}";
      const string generated_id="obs_"+V2Sha256Hex(canonical);
      if(observation.observation_id=="")
         observation.observation_id=generated_id;
      else if(observation.observation_id!=generated_id)
        { reason="TRADE_OBSERVATION_ID_PAYLOAD_MISMATCH"; return false; }
      int request=DatabasePrepare(m_database,
         "INSERT OR IGNORE INTO trade_observations(observation_id,captured_at_msc,transaction_type,request_id,order_ticket,deal_ticket,position_id,position_by_id,symbol,order_type,order_state,deal_type,volume,price,stop_loss,take_profit,retcode,retcode_external,comment,processed) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,0);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,observation.observation_id) ||
         !DatabaseBind(request,1,observation.captured_at_msc) ||
         !DatabaseBind(request,2,observation.transaction_type) ||
         !DatabaseBind(request,3,V2UlongToText(observation.request_id)) ||
         !DatabaseBind(request,4,V2UlongToText(observation.order_ticket)) ||
         !DatabaseBind(request,5,V2UlongToText(observation.deal_ticket)) ||
         !DatabaseBind(request,6,V2UlongToText(observation.position_id)) ||
         !DatabaseBind(request,7,V2UlongToText(observation.position_by_id)) ||
         !DatabaseBind(request,8,observation.symbol) ||
         !DatabaseBind(request,9,observation.order_type) ||
         !DatabaseBind(request,10,observation.order_state) ||
         !DatabaseBind(request,11,observation.deal_type) ||
         !DatabaseBind(request,12,observation.volume) ||
         !DatabaseBind(request,13,observation.price) ||
         !DatabaseBind(request,14,observation.stop_loss) ||
         !DatabaseBind(request,15,observation.take_profit) ||
         !DatabaseBind(request,16,(long)observation.retcode) ||
         !DatabaseBind(request,17,(long)observation.retcode_external) ||
         !DatabaseBind(request,18,observation.comment) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="TRADE_OBSERVATION_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool CountUnprocessedTradeObservations(int &count,string &reason)
     {
      count=0;
      reason="";
      if(!RequireReadable(reason)) return false;
      // trade_observations intentionally records the raw terminal stream before
      // member correlation exists.  The durable DB identity is deployment-
      // scoped, so this guard counts every unprocessed observation in that
      // deployment.  This is conservatively stronger than a member-only count:
      // an uncorrelated observation can never be ignored during broker match.
      int request=DatabasePrepare(m_database,
         "SELECT COUNT(*) FROM trade_observations WHERE processed=0;");
      if(request==INVALID_HANDLE)
        { reason="TRADE_OBSERVATION_COUNT_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      long stored_count=0;
      if(!DatabaseRead(request) || !DatabaseColumnLong(request,0,stored_count))
        {
         reason="TRADE_OBSERVATION_COUNT_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      if(stored_count<0 || stored_count>2147483647)
        { reason="TRADE_OBSERVATION_COUNT_OUT_OF_RANGE"; return false; }
      count=(int)stored_count;
      return true;
     }

   bool LoadUnprocessedTradeObservations(const int maximum,
                                         V2TradeObservation &observations[],
                                         string &reason)
     {
      ArrayResize(observations,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(maximum<=0)
         return true;
      const int bounded=MathMin(maximum,1000);
      int request=DatabasePrepare(m_database,
         "SELECT observation_id,captured_at_msc,transaction_type,request_id,order_ticket,deal_ticket,position_id,position_by_id,symbol,order_type,order_state,deal_type,volume,price,stop_loss,take_profit,retcode,retcode_external,comment FROM trade_observations WHERE processed=0 ORDER BY captured_at_msc ASC,observation_id ASC LIMIT "+IntegerToString(bounded)+";");
      if(request==INVALID_HANDLE)
        { reason="TRADE_OBSERVATION_LOAD_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }

      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="TRADE_OBSERVATION_LOAD_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         if(ArrayResize(observations,count+1)!=count+1)
           {
            reason="TRADE_OBSERVATION_LOAD_ALLOCATION_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         observations[count].Reset();
         string request_text="",order_text="",deal_text="",position_text="",position_by_text="";
         long retcode=0,retcode_external=0;
         const bool read=DatabaseColumnText(request,0,observations[count].observation_id) &&
                         DatabaseColumnLong(request,1,observations[count].captured_at_msc) &&
                         DatabaseColumnInteger(request,2,observations[count].transaction_type) &&
                         DatabaseColumnText(request,3,request_text) &&
                         DatabaseColumnText(request,4,order_text) &&
                         DatabaseColumnText(request,5,deal_text) &&
                         DatabaseColumnText(request,6,position_text) &&
                         DatabaseColumnText(request,7,position_by_text) &&
                         DatabaseColumnText(request,8,observations[count].symbol) &&
                         DatabaseColumnInteger(request,9,observations[count].order_type) &&
                         DatabaseColumnInteger(request,10,observations[count].order_state) &&
                         DatabaseColumnInteger(request,11,observations[count].deal_type) &&
                         DatabaseColumnDouble(request,12,observations[count].volume) &&
                         DatabaseColumnDouble(request,13,observations[count].price) &&
                         DatabaseColumnDouble(request,14,observations[count].stop_loss) &&
                         DatabaseColumnDouble(request,15,observations[count].take_profit) &&
                         DatabaseColumnLong(request,16,retcode) &&
                         DatabaseColumnLong(request,17,retcode_external) &&
                         DatabaseColumnText(request,18,observations[count].comment);
         if(!read ||
            !V2TextToUlong(request_text,observations[count].request_id) ||
            !V2TextToUlong(order_text,observations[count].order_ticket) ||
            !V2TextToUlong(deal_text,observations[count].deal_ticket) ||
            !V2TextToUlong(position_text,observations[count].position_id) ||
            !V2TextToUlong(position_by_text,observations[count].position_by_id))
           {
            reason="TRADE_OBSERVATION_LOAD_COLUMN_OR_ID_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         observations[count].retcode=(uint)retcode;
         observations[count].retcode_external=(uint)retcode_external;
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool FindOrderIntentByCorrelation(const ulong request_id,
                                     const ulong order_ticket,
                                     const ulong deal_ticket,
                                     V2OrderIntent &intent,
                                     bool &found,
                                     string &reason)
     {
      intent.Reset();
      found=false;
      reason="";
      if(!RequireReadable(reason)) return false;
      if(request_id==0 && order_ticket==0 && deal_ticket==0)
        { reason="INTENT_CORRELATION_IDS_ALL_ZERO"; return false; }

      string predicate="";
      int parameter_count=0;
      if(request_id!=0)
        {
         parameter_count++;
         predicate="request_id=?"+IntegerToString(parameter_count);
        }
      if(order_ticket!=0)
        {
         parameter_count++;
         if(predicate!="") predicate+=" OR ";
         predicate+="order_ticket=?"+IntegerToString(parameter_count);
        }
      if(deal_ticket!=0)
        {
         parameter_count++;
         if(predicate!="") predicate+=" OR ";
         predicate+="deal_ticket=?"+IntegerToString(parameter_count);
        }

      int request=DatabasePrepare(m_database,
         "SELECT order_intent_id,sequence_id,action_kind,risk_effect,status,direction,level_index,symbol,magic,requested_volume,requested_price,stop_loss,take_profit,request_id,order_ticket,deal_ticket,position_id,retcode,created_at_msc,reason_code FROM order_intents WHERE "+predicate+" ORDER BY order_intent_id ASC LIMIT 2;");
      if(request==INVALID_HANDLE)
        { reason="INTENT_CORRELATION_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      int bind_index=0;
      if((request_id!=0 && !DatabaseBind(request,bind_index++,V2UlongToText(request_id))) ||
         (order_ticket!=0 && !DatabaseBind(request,bind_index++,V2UlongToText(order_ticket))) ||
         (deal_ticket!=0 && !DatabaseBind(request,bind_index++,V2UlongToText(deal_ticket))))
        {
         reason="INTENT_CORRELATION_BIND_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }

      int matches=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="INTENT_CORRELATION_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         matches++;
         if(matches>1)
           {
            reason="INTENT_CORRELATION_AMBIGUOUS";
            DatabaseFinalize(request);
            intent.Reset();
            return false;
           }
         int action=0,risk_effect=0,status=0,direction=0;
         long retcode=0,created_at_msc=0;
         string magic_text="",request_text="",order_text="",deal_text="",position_text="";
         const bool read=DatabaseColumnText(request,0,intent.order_intent_id) &&
                         DatabaseColumnText(request,1,intent.sequence_id) &&
                         DatabaseColumnInteger(request,2,action) &&
                         DatabaseColumnInteger(request,3,risk_effect) &&
                         DatabaseColumnInteger(request,4,status) &&
                         DatabaseColumnInteger(request,5,direction) &&
                         DatabaseColumnInteger(request,6,intent.level_index) &&
                         DatabaseColumnText(request,7,intent.symbol) &&
                         DatabaseColumnText(request,8,magic_text) &&
                         DatabaseColumnDouble(request,9,intent.requested_volume) &&
                         DatabaseColumnDouble(request,10,intent.requested_price) &&
                         DatabaseColumnDouble(request,11,intent.stop_loss) &&
                         DatabaseColumnDouble(request,12,intent.take_profit) &&
                         DatabaseColumnText(request,13,request_text) &&
                         DatabaseColumnText(request,14,order_text) &&
                         DatabaseColumnText(request,15,deal_text) &&
                         DatabaseColumnText(request,16,position_text) &&
                         DatabaseColumnLong(request,17,retcode) &&
                         DatabaseColumnLong(request,18,created_at_msc) &&
                         DatabaseColumnText(request,19,intent.reason_code);
         if(!read ||
            !V2TextToUlong(magic_text,intent.magic) ||
            !V2TextToUlong(request_text,intent.request_id) ||
            !V2TextToUlong(order_text,intent.order_ticket) ||
            !V2TextToUlong(deal_text,intent.deal_ticket) ||
            !V2TextToUlong(position_text,intent.position_id))
           {
            reason="INTENT_CORRELATION_COLUMN_OR_ID_FAILED";
            DatabaseFinalize(request);
            intent.Reset();
            return false;
           }
         intent.action=(ENUM_V2_ACTION_KIND)action;
         intent.risk_effect=(ENUM_V2_RISK_EFFECT)risk_effect;
         intent.status=(ENUM_V2_ORDER_INTENT_STATUS)status;
         intent.direction=(ENUM_V2_DIRECTION)direction;
         intent.retcode=(uint)retcode;
         intent.created_at=(datetime)(created_at_msc/1000);
        }
      DatabaseFinalize(request);
      found=(matches==1);
      return true;
     }

   bool LoadUnsettledOrderIntents(const int maximum,
                                  V2OrderIntent &intents[],
                                  string &reason)
     {
      ArrayResize(intents,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(maximum<=0)
         return true;
      const int bounded=MathMin(maximum,1000);
      int request=DatabasePrepare(m_database,
         "SELECT order_intent_id,sequence_id,action_kind,risk_effect,status,direction,level_index,symbol,magic,requested_volume,requested_price,stop_loss,take_profit,request_id,order_ticket,deal_ticket,position_id,retcode,created_at_msc,reason_code FROM order_intents WHERE status IN (?1,?2,?3,?4,?5) ORDER BY created_at_msc ASC,order_intent_id ASC LIMIT "+IntegerToString(bounded)+";");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,(int)V2_INTENT_PERSISTED) ||
         !DatabaseBind(request,1,(int)V2_INTENT_SUBMITTED) ||
         !DatabaseBind(request,2,(int)V2_INTENT_ACCEPTED) ||
         !DatabaseBind(request,3,(int)V2_INTENT_PARTIAL) ||
         !DatabaseBind(request,4,(int)V2_INTENT_RECONCILE_REQUIRED))
        {
         reason="UNSETTLED_INTENT_SELECT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }

      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              {
               reason="UNSETTLED_INTENT_READ_FAILED:"+IntegerToString(error);
               DatabaseFinalize(request);
               return false;
              }
            break;
           }
         if(ArrayResize(intents,count+1)!=count+1)
           {
            reason="UNSETTLED_INTENT_ALLOCATION_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         intents[count].Reset();
         int action=0,risk_effect=0,status=0,direction=0;
         long retcode=0,created_at_msc=0;
         string magic_text="",request_text="",order_text="",deal_text="",position_text="";
         const bool read=DatabaseColumnText(request,0,intents[count].order_intent_id) &&
                         DatabaseColumnText(request,1,intents[count].sequence_id) &&
                         DatabaseColumnInteger(request,2,action) &&
                         DatabaseColumnInteger(request,3,risk_effect) &&
                         DatabaseColumnInteger(request,4,status) &&
                         DatabaseColumnInteger(request,5,direction) &&
                         DatabaseColumnInteger(request,6,intents[count].level_index) &&
                         DatabaseColumnText(request,7,intents[count].symbol) &&
                         DatabaseColumnText(request,8,magic_text) &&
                         DatabaseColumnDouble(request,9,intents[count].requested_volume) &&
                         DatabaseColumnDouble(request,10,intents[count].requested_price) &&
                         DatabaseColumnDouble(request,11,intents[count].stop_loss) &&
                         DatabaseColumnDouble(request,12,intents[count].take_profit) &&
                         DatabaseColumnText(request,13,request_text) &&
                         DatabaseColumnText(request,14,order_text) &&
                         DatabaseColumnText(request,15,deal_text) &&
                         DatabaseColumnText(request,16,position_text) &&
                         DatabaseColumnLong(request,17,retcode) &&
                         DatabaseColumnLong(request,18,created_at_msc) &&
                         DatabaseColumnText(request,19,intents[count].reason_code);
         if(!read ||
            !V2TextToUlong(magic_text,intents[count].magic) ||
            !V2TextToUlong(request_text,intents[count].request_id) ||
            !V2TextToUlong(order_text,intents[count].order_ticket) ||
            !V2TextToUlong(deal_text,intents[count].deal_ticket) ||
            !V2TextToUlong(position_text,intents[count].position_id))
           {
            reason="UNSETTLED_INTENT_COLUMN_OR_ID_FAILED";
            DatabaseFinalize(request);
            return false;
           }
         intents[count].action=(ENUM_V2_ACTION_KIND)action;
         intents[count].risk_effect=(ENUM_V2_RISK_EFFECT)risk_effect;
         intents[count].status=(ENUM_V2_ORDER_INTENT_STATUS)status;
         intents[count].direction=(ENUM_V2_DIRECTION)direction;
         intents[count].retcode=(uint)retcode;
         intents[count].created_at=(datetime)(created_at_msc/1000);
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool MarkTradeObservationProcessed(const string observation_id,string &reason)
       {
      reason="";
      if(!RequireWritable(reason)) return false;
      const string sql=(m_config.mode==V2_DB_REDUCED) ?
         "DELETE FROM trade_observations WHERE observation_id=?1;" :
         "UPDATE trade_observations SET processed=1 WHERE observation_id=?1;";
      int request=DatabasePrepare(m_database,
         sql);
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,observation_id) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="TRADE_OBSERVATION_UPDATE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool EnqueueOutbox(const string message_id,
                      const string message_kind,
                      const string payload,
                      const int priority,
                      const bool critical,
                      string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED)
         return true;
      if(message_id=="" || message_kind=="" || payload=="")
        { reason="OUTBOX_MESSAGE_INCOMPLETE"; return false; }
      const string payload_hash=V2Sha256Hex(payload);
      if(payload_hash=="")
        { reason="OUTBOX_PAYLOAD_HASH_FAILED"; return false; }

      bool found=false;
      string existing_hash="";
      int request=DatabasePrepare(m_database,
         "SELECT payload_hash FROM telemetry_outbox WHERE message_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,message_id))
        {
         reason="OUTBOX_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
         found=DatabaseColumnText(request,0,existing_hash);
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="OUTBOX_LOOKUP_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      if(found)
        {
         if(existing_hash!=payload_hash)
           { reason="OUTBOX_MESSAGE_ID_COLLISION"; return false; }
         return true;
        }

      const long now_msc=V2UtcNowMsc();
      const long payload_size=V2Utf8ByteCount(payload);
      if(!CheckOutboxCapacity(1,payload_size,reason))
         return false;
      request=DatabasePrepare(m_database,
         "INSERT INTO telemetry_outbox(message_id,message_kind,payload,payload_hash,payload_size,created_at_msc,next_attempt_msc,attempts,priority,critical,outbox_state,last_error) VALUES(?1,?2,?3,?4,?5,?6,?7,0,?8,?9,?10,'');");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,message_id) ||
         !DatabaseBind(request,1,message_kind) ||
         !DatabaseBind(request,2,payload) ||
         !DatabaseBind(request,3,payload_hash) ||
         !DatabaseBind(request,4,payload_size) ||
         !DatabaseBind(request,5,now_msc) ||
         !DatabaseBind(request,6,now_msc) ||
         !DatabaseBind(request,7,priority) ||
         !DatabaseBind(request,8,critical ? 1 : 0) ||
         !DatabaseBind(request,9,(int)V2_OUTBOX_PENDING) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="OUTBOX_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool UpsertHeartbeatOutbox(const string deployment_id,const string payload,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED)
         return true;
      if(deployment_id=="" || payload=="")
        { reason="HEARTBEAT_OUTBOX_PAYLOAD_INCOMPLETE"; return false; }
      const string message_id="heartbeat:"+deployment_id;
      const string payload_hash=V2Sha256Hex(payload);
      if(payload_hash=="")
        { reason="HEARTBEAT_OUTBOX_HASH_FAILED"; return false; }
      const long now_msc=V2UtcNowMsc();
      bool found=false;
      long prior_payload_size=0;
      int prior_state=(int)V2_OUTBOX_DELIVERED;
      int request=DatabasePrepare(m_database,
         "SELECT payload_size,outbox_state FROM telemetry_outbox WHERE message_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,message_id))
        {
         reason="HEARTBEAT_OUTBOX_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
         found=DatabaseColumnLong(request,0,prior_payload_size) &&
               DatabaseColumnInteger(request,1,prior_state);
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="HEARTBEAT_OUTBOX_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
       }
      DatabaseFinalize(request);
      const long payload_size=V2Utf8ByteCount(payload);
      const bool was_pending=(found && prior_state==(int)V2_OUTBOX_PENDING);
      const long additional_messages=was_pending ? 0 : 1;
      const long additional_bytes=payload_size-(was_pending ? prior_payload_size : 0);
      if(!CheckOutboxCapacity(additional_messages,additional_bytes,reason))
         return false;
      const string sql=found ?
         "UPDATE telemetry_outbox SET payload=?1,payload_hash=?2,payload_size=?3,created_at_msc=?4,next_attempt_msc=?5,attempts=0,priority=0,critical=0,outbox_state=0,last_error='' WHERE message_id=?6;" :
         "INSERT INTO telemetry_outbox(payload,payload_hash,payload_size,created_at_msc,next_attempt_msc,attempts,priority,critical,outbox_state,last_error,message_id,message_kind) VALUES(?1,?2,?3,?4,?5,0,0,0,0,'',?6,'HEARTBEAT');";
      request=DatabasePrepare(m_database,sql);
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,payload) ||
         !DatabaseBind(request,1,payload_hash) ||
         !DatabaseBind(request,2,payload_size) ||
         !DatabaseBind(request,3,now_msc) ||
         !DatabaseBind(request,4,now_msc) ||
         !DatabaseBind(request,5,message_id) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="HEARTBEAT_OUTBOX_WRITE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool GetOutboxStats(long &pending_count,long &pending_bytes,string &reason)
     {
      pending_count=0;
      pending_bytes=0;
      reason="";
      if(!RequireReadable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED)
         return true;
      int request=DatabasePrepare(m_database,
         "SELECT COUNT(*),COALESCE(SUM(payload_size),0) FROM telemetry_outbox WHERE outbox_state=0;");
      if(request==INVALID_HANDLE)
        { reason="OUTBOX_STATS_PREPARE_FAILED:"+IntegerToString(GetLastError()); return false; }
      ResetLastError();
      if(!DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,pending_count) ||
         !DatabaseColumnLong(request,1,pending_bytes))
        {
         reason="OUTBOX_STATS_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool LoadPendingOutbox(const int maximum,V2OutboxRecord &records[],string &reason)
     {
      ArrayResize(records,0);
      reason="";
      if(!RequireReadable(reason)) return false;
      if(m_config.mode==V2_DB_REDUCED || maximum<=0)
         return true;
      const int bounded=MathMin(maximum,1000);
      const long now_msc=V2UtcNowMsc();
      int request=DatabasePrepare(m_database,
         "SELECT message_id,message_kind,payload,payload_hash,created_at_msc,next_attempt_msc,attempts,priority,critical,outbox_state,last_error FROM telemetry_outbox WHERE outbox_state=0 AND next_attempt_msc<=?1 ORDER BY priority DESC,next_attempt_msc ASC,created_at_msc ASC LIMIT "+IntegerToString(bounded)+";");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,now_msc))
        {
         reason="OUTBOX_LOAD_PREPARE_OR_BIND_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      int count=0;
      while(true)
        {
         ResetLastError();
         if(!DatabaseRead(request))
           {
            const int error=GetLastError();
            if(error!=ERR_DATABASE_NO_MORE_DATA)
              { reason="OUTBOX_LOAD_READ_FAILED:"+IntegerToString(error); DatabaseFinalize(request); return false; }
            break;
           }
         if(ArrayResize(records,count+1)!=count+1)
           { reason="OUTBOX_LOAD_ALLOCATION_FAILED"; DatabaseFinalize(request); return false; }
         records[count].Reset();
         int critical=0,state=0;
         bool ok=DatabaseColumnText(request,0,records[count].message_id) &&
                 DatabaseColumnText(request,1,records[count].message_kind) &&
                 DatabaseColumnText(request,2,records[count].payload) &&
                 DatabaseColumnText(request,3,records[count].payload_hash) &&
                 DatabaseColumnLong(request,4,records[count].created_at_msc) &&
                 DatabaseColumnLong(request,5,records[count].next_attempt_msc) &&
                 DatabaseColumnInteger(request,6,records[count].attempts) &&
                 DatabaseColumnInteger(request,7,records[count].priority) &&
                 DatabaseColumnInteger(request,8,critical) &&
                 DatabaseColumnInteger(request,9,state) &&
                 DatabaseColumnText(request,10,records[count].last_error);
         if(!ok)
           { reason="OUTBOX_LOAD_COLUMN_FAILED:"+IntegerToString(GetLastError()); DatabaseFinalize(request); return false; }
         records[count].critical=(critical!=0);
         records[count].state=(ENUM_V2_OUTBOX_STATE)state;
         count++;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool MarkOutboxDelivered(const string message_id,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      int request=DatabasePrepare(m_database,
         "UPDATE telemetry_outbox SET payload='',payload_size=0,outbox_state=?1,last_error='' WHERE message_id=?2;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,(int)V2_OUTBOX_DELIVERED) ||
         !DatabaseBind(request,1,message_id) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="OUTBOX_DELIVERED_UPDATE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      if(!ExecuteSchemaStatement(
         "DELETE FROM telemetry_outbox WHERE outbox_state=1 AND rowid NOT IN (SELECT rowid FROM telemetry_outbox WHERE outbox_state=1 ORDER BY created_at_msc DESC,message_id DESC LIMIT 10000);",
         reason))
        {
         reason="OUTBOX_TOMBSTONE_PRUNE_FAILED:"+reason;
         return false;
        }
      return true;
     }

   bool RecordOutboxAttemptFailure(const string message_id,
                                   const long next_attempt_msc,
                                   const string last_error,
                                   string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      int request=DatabasePrepare(m_database,
         "UPDATE telemetry_outbox SET attempts=attempts+1,next_attempt_msc=?1,last_error=?2 WHERE message_id=?3;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,next_attempt_msc) ||
         !DatabaseBind(request,1,last_error) ||
         !DatabaseBind(request,2,message_id) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="OUTBOX_ATTEMPT_UPDATE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool SaveExperimentManifest(const V2ExperimentManifest &manifest,string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(manifest.manifest_id=="" || manifest.manifest_hash=="" || manifest.canonical_payload=="")
        { reason="EXPERIMENT_MANIFEST_NOT_FINALIZED"; return false; }
      if(manifest.manifest_class==V2_MANIFEST_CERTIFICATION && !manifest.external_lineage_complete)
        { reason="EXPERIMENT_CERTIFICATION_LINEAGE_INCOMPLETE"; return false; }
      CV2ExperimentManifest serializer;
      const string canonical_payload=serializer.Serialize(manifest);
      if(manifest.canonical_payload!=canonical_payload)
        { reason="EXPERIMENT_MANIFEST_CANONICAL_PAYLOAD_MISMATCH"; return false; }
      const string manifest_hash=V2Sha256Hex(canonical_payload);
      if(manifest_hash=="" || manifest.manifest_hash!=manifest_hash)
        { reason="EXPERIMENT_MANIFEST_HASH_MISMATCH"; return false; }
      if(manifest.manifest_id!="exp_"+manifest_hash)
        { reason="EXPERIMENT_MANIFEST_ID_MISMATCH"; return false; }
      int request=DatabasePrepare(m_database,
         "INSERT OR IGNORE INTO experiment_manifests(manifest_id,manifest_hash,created_at_msc,manifest_class,external_lineage_complete,canonical_payload) VALUES(?1,?2,?3,?4,?5,?6);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,manifest.manifest_id) ||
         !DatabaseBind(request,1,manifest.manifest_hash) ||
         !DatabaseBind(request,2,manifest.created_at_msc) ||
         !DatabaseBind(request,3,(int)manifest.manifest_class) ||
         !DatabaseBind(request,4,manifest.external_lineage_complete ? 1 : 0) ||
         !DatabaseBind(request,5,manifest.canonical_payload) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="EXPERIMENT_MANIFEST_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool AppendSequenceLedger(const string sequence_id,
                             const ulong deal_ticket,
                             const long occurred_at_msc,
                             const double profit,
                             const double commission,
                             const double swap,
                             string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(sequence_id=="" || deal_ticket==0)
        { reason="SEQUENCE_LEDGER_IDENTITY_INVALID"; return false; }
      if(!MathIsValidNumber(profit) || !MathIsValidNumber(commission) || !MathIsValidNumber(swap))
        { reason="SEQUENCE_LEDGER_NUMERIC_VALUE_INVALID"; return false; }
      int request=DatabasePrepare(m_database,
         "SELECT sequence_id,occurred_at_msc,profit,commission,swap FROM seq_ledger WHERE deal_ticket=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,V2UlongToText(deal_ticket)))
        {
         reason="SEQUENCE_LEDGER_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         string stored_sequence="";
         long stored_time=0;
         double stored_profit=0.0,stored_commission=0.0,stored_swap=0.0;
         const bool read=DatabaseColumnText(request,0,stored_sequence) &&
                         DatabaseColumnLong(request,1,stored_time) &&
                         DatabaseColumnDouble(request,2,stored_profit) &&
                         DatabaseColumnDouble(request,3,stored_commission) &&
                         DatabaseColumnDouble(request,4,stored_swap);
         DatabaseFinalize(request);
         if(!read || stored_sequence!=sequence_id || stored_time!=occurred_at_msc ||
            stored_profit!=profit || stored_commission!=commission || stored_swap!=swap)
           { reason="SEQUENCE_LEDGER_DEAL_COLLISION"; return false; }
         return true;
        }
      const int lookup_error=GetLastError();
      DatabaseFinalize(request);
      if(lookup_error!=ERR_DATABASE_NO_MORE_DATA)
        { reason="SEQUENCE_LEDGER_LOOKUP_READ_FAILED:"+IntegerToString(lookup_error); return false; }

      request=DatabasePrepare(m_database,
         "INSERT INTO seq_ledger(deal_ticket,sequence_id,occurred_at_msc,profit,commission,swap) VALUES(?1,?2,?3,?4,?5,?6);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,V2UlongToText(deal_ticket)) ||
         !DatabaseBind(request,1,sequence_id) ||
         !DatabaseBind(request,2,occurred_at_msc) ||
         !DatabaseBind(request,3,profit) ||
         !DatabaseBind(request,4,commission) ||
         !DatabaseBind(request,5,swap) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="SEQUENCE_LEDGER_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool AppendSlippage(const string entry_id,
                       const string order_intent_id,
                       const long occurred_at_msc,
                       const double requested_price,
                       const double accepted_price,
                       const double filled_price,
                       const ulong latency_micros,
                       const uint retcode,
                       string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(entry_id=="" || order_intent_id=="")
        { reason="SLIPPAGE_IDENTITY_EMPTY"; return false; }
      if(!MathIsValidNumber(requested_price) || !MathIsValidNumber(accepted_price) ||
         !MathIsValidNumber(filled_price))
        { reason="SLIPPAGE_NUMERIC_VALUE_INVALID"; return false; }
      int request=DatabasePrepare(m_database,
         "SELECT order_intent_id,occurred_at_msc,requested_price,accepted_price,filled_price,latency_micros,retcode FROM slippage_log WHERE entry_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,entry_id))
        {
         reason="SLIPPAGE_LOOKUP_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         string stored_intent="",latency_text="";
         long stored_time=0,stored_retcode=0;
         double stored_requested=0.0,stored_accepted=0.0,stored_filled=0.0;
         const bool read=DatabaseColumnText(request,0,stored_intent) &&
                         DatabaseColumnLong(request,1,stored_time) &&
                         DatabaseColumnDouble(request,2,stored_requested) &&
                         DatabaseColumnDouble(request,3,stored_accepted) &&
                         DatabaseColumnDouble(request,4,stored_filled) &&
                         DatabaseColumnText(request,5,latency_text) &&
                         DatabaseColumnLong(request,6,stored_retcode);
         DatabaseFinalize(request);
         ulong stored_latency=0;
         if(!read || !V2TextToUlong(latency_text,stored_latency) ||
            stored_intent!=order_intent_id || stored_time!=occurred_at_msc ||
            stored_requested!=requested_price || stored_accepted!=accepted_price ||
            stored_filled!=filled_price || stored_latency!=latency_micros ||
            stored_retcode!=(long)retcode)
           { reason="SLIPPAGE_ENTRY_COLLISION"; return false; }
         return true;
        }
      const int lookup_error=GetLastError();
      DatabaseFinalize(request);
      if(lookup_error!=ERR_DATABASE_NO_MORE_DATA)
        { reason="SLIPPAGE_LOOKUP_READ_FAILED:"+IntegerToString(lookup_error); return false; }

      request=DatabasePrepare(m_database,
         "INSERT INTO slippage_log(entry_id,order_intent_id,occurred_at_msc,requested_price,accepted_price,filled_price,latency_micros,retcode) VALUES(?1,?2,?3,?4,?5,?6,?7,?8);");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,entry_id) ||
         !DatabaseBind(request,1,order_intent_id) ||
         !DatabaseBind(request,2,occurred_at_msc) ||
         !DatabaseBind(request,3,requested_price) ||
         !DatabaseBind(request,4,accepted_price) ||
         !DatabaseBind(request,5,filled_price) ||
         !DatabaseBind(request,6,V2UlongToText(latency_micros)) ||
         !DatabaseBind(request,7,(long)retcode) ||
         !ExecutePreparedNoRows(request,reason))
        {
         if(reason=="") reason="SLIPPAGE_INSERT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);
      return true;
     }

   bool CreateMemberSnapshot(const string strategy_member_id,
                             V2StateDBMemberSnapshot &snapshot,
                             string &reason)
     {
      snapshot.Reset();
      reason="";
      if(!RequireReadable(reason)) return false;
      if(strategy_member_id=="" || strategy_member_id!=m_config.strategy_member_id)
        { reason="MEMBER_SNAPSHOT_SCOPE_MISMATCH"; return false; }
      snapshot.strategy_member_id=strategy_member_id;

      int request=DatabasePrepare(m_database,
         "SELECT COUNT(*),COALESCE(SUM(CASE WHEN status IN (?1,?2,?3) THEN 1 ELSE 0 END),0) FROM sequences WHERE strategy_member_id=?4;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,(int)V2_SEQ_ACTIVE) ||
         !DatabaseBind(request,1,(int)V2_SEQ_REDUCE_ONLY) ||
         !DatabaseBind(request,2,(int)V2_SEQ_QUARANTINED) ||
         !DatabaseBind(request,3,strategy_member_id) ||
         !DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,snapshot.sequence_count) ||
         !DatabaseColumnLong(request,1,snapshot.manageable_sequence_count))
        {
         reason="MEMBER_SNAPSHOT_SEQUENCE_COUNT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      request=DatabasePrepare(m_database,
         "SELECT COUNT(*) FROM domain_events e INNER JOIN sequences s ON s.sequence_id=e.sequence_id WHERE s.strategy_member_id=?1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,strategy_member_id) ||
         !DatabaseRead(request) || !DatabaseColumnLong(request,0,snapshot.event_count))
        {
         reason="MEMBER_SNAPSHOT_EVENT_COUNT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      request=DatabasePrepare(m_database,
         "SELECT COUNT(*),COALESCE(SUM(CASE WHEN i.status IN (?1,?2,?3,?4,?5) THEN 1 ELSE 0 END),0) FROM order_intents i INNER JOIN sequences s ON s.sequence_id=i.sequence_id WHERE s.strategy_member_id=?6;");
      if(request==INVALID_HANDLE ||
         !DatabaseBind(request,0,(int)V2_INTENT_PERSISTED) ||
         !DatabaseBind(request,1,(int)V2_INTENT_SUBMITTED) ||
         !DatabaseBind(request,2,(int)V2_INTENT_ACCEPTED) ||
         !DatabaseBind(request,3,(int)V2_INTENT_PARTIAL) ||
         !DatabaseBind(request,4,(int)V2_INTENT_RECONCILE_REQUIRED) ||
         !DatabaseBind(request,5,strategy_member_id) ||
         !DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,snapshot.intent_count) ||
         !DatabaseColumnLong(request,1,snapshot.unsettled_intent_count))
        {
         reason="MEMBER_SNAPSHOT_INTENT_COUNT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      // Raw terminal observations precede correlation and are therefore only
      // deployment-scoped.  Reporting the full deployment count is deliberate
      // and prevents a member repair from hiding an ambiguous observation.
      request=DatabasePrepare(m_database,
         "SELECT COUNT(*),COALESCE(SUM(CASE WHEN processed=0 THEN 1 ELSE 0 END),0) FROM trade_observations;");
      if(request==INVALID_HANDLE || !DatabaseRead(request) ||
         !DatabaseColumnLong(request,0,snapshot.observation_count) ||
         !DatabaseColumnLong(request,1,snapshot.unprocessed_observation_count))
        {
         reason="MEMBER_SNAPSHOT_OBSERVATION_COUNT_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      request=DatabasePrepare(m_database,
         "SELECT e.canonical_number,e.event_hash FROM domain_events e INNER JOIN sequences s ON s.sequence_id=e.sequence_id WHERE s.strategy_member_id=?1 ORDER BY e.canonical_number DESC LIMIT 1;");
      if(request==INVALID_HANDLE || !DatabaseBind(request,0,strategy_member_id))
        {
         reason="MEMBER_SNAPSHOT_HEAD_PREPARE_FAILED:"+IntegerToString(GetLastError());
         if(request!=INVALID_HANDLE) DatabaseFinalize(request);
         return false;
        }
      ResetLastError();
      if(DatabaseRead(request))
        {
         if(!DatabaseColumnLong(request,0,snapshot.last_canonical_number) ||
            !DatabaseColumnText(request,1,snapshot.last_event_hash))
           {
            reason="MEMBER_SNAPSHOT_HEAD_READ_FAILED:"+IntegerToString(GetLastError());
            DatabaseFinalize(request);
            return false;
           }
        }
      else if(GetLastError()!=ERR_DATABASE_NO_MORE_DATA)
        {
         reason="MEMBER_SNAPSHOT_HEAD_READ_FAILED:"+IntegerToString(GetLastError());
         DatabaseFinalize(request);
         return false;
        }
      DatabaseFinalize(request);

      string lineage_reason="";
      snapshot.projection_lineage_valid=VerifyProjectionLineage(strategy_member_id,lineage_reason);
      snapshot.audit_reason=(snapshot.projection_lineage_valid ?
         "MEMBER_PROJECTION_LINEAGE_VALID;RAW_OBSERVATIONS_DEPLOYMENT_SCOPED" : lineage_reason);
      const string canonical=strategy_member_id+"|"+
                             IntegerToString(snapshot.sequence_count)+"|"+
                             IntegerToString(snapshot.manageable_sequence_count)+"|"+
                             IntegerToString(snapshot.event_count)+"|"+
                             IntegerToString(snapshot.intent_count)+"|"+
                             IntegerToString(snapshot.unsettled_intent_count)+"|"+
                             IntegerToString(snapshot.observation_count)+"|"+
                             IntegerToString(snapshot.unprocessed_observation_count)+"|"+
                             IntegerToString(snapshot.last_canonical_number)+"|"+
                             snapshot.last_event_hash+"|"+
                             (snapshot.projection_lineage_valid ? "1" : "0")+"|"+
                             snapshot.audit_reason;
      snapshot.snapshot_hash=V2Sha256Hex(canonical);
      if(snapshot.snapshot_hash=="")
        { reason="MEMBER_SNAPSHOT_HASH_FAILED"; return false; }
      return true;
     }

   bool BuildMemberRepairPlan(const string strategy_member_id,
                              const string requested_reason,
                              V2StateDBMemberRepairPlan &plan,
                              string &reason)
     {
      plan.Reset();
      reason="";
      if(requested_reason=="")
        { reason="MEMBER_REPAIR_REASON_EMPTY"; return false; }
      V2StateDBMemberSnapshot snapshot;
      if(!CreateMemberSnapshot(strategy_member_id,snapshot,reason)) return false;
      plan.strategy_member_id=strategy_member_id;
      plan.snapshot_hash=snapshot.snapshot_hash;
      plan.requested_reason=requested_reason;
      plan.online_apply_allowed=false;
      plan.plan_hash=V2Sha256Hex("GOAT2_MEMBER_REPAIR_PLAN_V1|"+
                                plan.strategy_member_id+"|"+
                                plan.snapshot_hash+"|"+
                                plan.requested_reason+"|ONLINE_APPLY_FORBIDDEN");
      if(plan.plan_hash=="")
        { reason="MEMBER_REPAIR_PLAN_HASH_FAILED"; return false; }
      return true;
     }

   bool ApplyMemberRepairPlan(const V2StateDBMemberRepairPlan &plan,string &reason)
     {
      reason="";
      if(plan.strategy_member_id=="" || plan.strategy_member_id!=m_config.strategy_member_id)
        { reason="MEMBER_REPAIR_SCOPE_MISMATCH"; return false; }
      const string expected=V2Sha256Hex("GOAT2_MEMBER_REPAIR_PLAN_V1|"+
                                        plan.strategy_member_id+"|"+
                                        plan.snapshot_hash+"|"+
                                        plan.requested_reason+"|ONLINE_APPLY_FORBIDDEN");
      if(plan.online_apply_allowed || plan.plan_hash=="" || plan.plan_hash!=expected)
        { reason="MEMBER_REPAIR_PLAN_INVALID"; return false; }
      // StateDB never edits or deletes damaged history and cannot reconstruct
      // domain state without the domain reducer.  The reviewed repair workflow
      // is: retain this member-scoped plan/snapshot, replay immutable events
      // into a new projection offline, review the diff, then migrate explicitly.
      reason="ONLINE_MEMBER_REPAIR_FORBIDDEN:OFFLINE_REPLAY_AND_REVIEW_REQUIRED";
      return false;
     }

   bool Heartbeat(string &reason)
     {
      reason="";
      if(!RequireWritable(reason)) return false;
      if(m_config.mode!=V2_DB_FULL_DURABLE)
         return true;
      const bool own_transaction=!m_in_transaction;
      if(own_transaction && !Begin(reason))
         return false;
      const long now_msc=V2UtcNowMsc();
      if(now_msc<=0)
        {
         reason="LEASE_UTC_CLOCK_UNAVAILABLE";
         if(own_transaction) Rollback();
         PoisonWrites(reason);
         return false;
        }
      if(!WriteMeta("lease_owner",m_config.owner_instance_id,reason) ||
         !WriteMeta("lease_heartbeat_msc",IntegerToString(now_msc),reason) ||
         !WriteMeta("lease_released","0",reason))
        {
         if(own_transaction) Rollback();
         PoisonWrites(reason);
         return false;
        }
      if(own_transaction && !Commit(reason))
         return false;
      return true;
     }

   bool IsOpen(void) const { return m_open; }
   bool IsWritable(void) const
     {
      return m_open && m_writable && m_access_mode==V2_DB_ACCESS_READ_WRITE &&
             (m_config.mode!=V2_DB_FULL_DURABLE || m_lease.IsHeld());
     }
   bool BrokerMutationAllowed(void) const { return IsWritable(); }
   bool IsReadOnlyRecovery(void) const
     { return m_open && m_access_mode==V2_DB_ACCESS_READ_ONLY_RECOVERY; }
   bool RequiresSupervisedReopen(void) const { return IsReadOnlyRecovery(); }
   bool IsDurable(void) const { return m_config.mode==V2_DB_FULL_DURABLE; }
   bool HasLease(void) const { return m_lease.IsHeld(); }
   ENUM_V2_STATE_DB_MODE Mode(void) const { return m_config.mode; }
   string ModeName(void) const { return V2StateDBModeName(m_config.mode); }
   ENUM_V2_STATE_DB_ACCESS_MODE AccessMode(void) const { return m_access_mode; }
   string AccessModeName(void) const { return V2StateDBAccessModeName(m_access_mode); }
   ENUM_V2_STATE_DB_STATUS Status(void) const { return m_status; }
   string StatusName(void) const { return V2StateDBStatusName(m_status); }
   string StatusReason(void) const { return m_status_reason; }
   long VerifiedCheckpointNumber(void) const { return m_verified_checkpoint_number; }
   string VerifiedCheckpointHash(void) const { return m_verified_checkpoint_hash; }
   bool JournalAuditVerified(void) const { return m_verified_checkpoint_hash!=""; }
   bool VerificationInheritedCheckpoint(void) const { return m_checkpoint_inherited; }
   string LastError(void) const { return m_last_error; }

   void Close(void)
     {
      if(m_in_transaction)
         Rollback();
      if(m_open && m_config.mode==V2_DB_FULL_DURABLE && m_writable)
        {
         string ignored="";
         const bool own_transaction=!m_in_transaction;
         if(!own_transaction || Begin(ignored))
           {
            const bool release_written=WriteMeta("lease_released","1",ignored) &&
                                       WriteMeta("lease_heartbeat_msc",IntegerToString(V2UtcNowMsc()),ignored);
            if(own_transaction)
              {
               if(release_written) Commit(ignored);
               else Rollback();
              }
           }
        }
      if(m_database!=INVALID_HANDLE)
         DatabaseClose(m_database);
      m_database=INVALID_HANDLE;
      m_open=false;
      m_writable=false;
      m_in_transaction=false;
      m_access_mode=V2_DB_ACCESS_CLOSED;
      m_status=V2_DB_STATUS_CLOSED;
      m_transaction_start_event_hash="";
      m_transaction_start_checkpoint_number=0;
      m_transaction_start_checkpoint_hash="";
      m_transaction_start_checkpoint_inherited=false;
      m_verified_checkpoint_number=0;
      m_verified_checkpoint_hash="";
      m_checkpoint_inherited=false;
      m_lease.Release();
     }
  };

#endif
