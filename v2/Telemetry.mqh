#ifndef GOAT_V2_TELEMETRY_MQH
#define GOAT_V2_TELEMETRY_MQH

#include "Receipts.mqh"
#include "StateDB.mqh"

struct V2TelemetryStatus
  {
   bool enabled;
   bool local_only;
   bool degraded;
   bool requires_manage_only;
   long pending_messages;
   long pending_bytes;
   long maximum_messages;
   long maximum_bytes;
   string reason;

   void Reset(void)
     {
      enabled=false;
      local_only=true;
      degraded=false;
      requires_manage_only=false;
      pending_messages=0;
      pending_bytes=0;
      maximum_messages=0;
      maximum_bytes=0;
      reason="";
     }
  };

class CV2Telemetry
  {
private:
   CV2StateDB *m_database;
   bool        m_enabled;
   long        m_maximum_messages;
   long        m_maximum_bytes;

   bool DatabaseReady(string &reason) const
     {
      if(m_database==NULL || CheckPointer(m_database)==POINTER_INVALID)
        {
         reason="TELEMETRY_DATABASE_POINTER_INVALID";
         return false;
        }
      if(!m_database.IsOpen())
        {
         reason="TELEMETRY_DATABASE_NOT_OPEN";
         return false;
        }
      return true;
     }

public:
                     CV2Telemetry(void)
     {
      m_database=NULL;
      m_enabled=false;
      m_maximum_messages=10000;
      m_maximum_bytes=50*1024*1024;
     }

   bool Initialize(CV2StateDB &database,
                   const bool enabled,
                   const long maximum_messages,
                   const long maximum_bytes,
                   string &reason)
     {
      reason="";
      m_database=GetPointer(database);
      m_enabled=enabled;
      m_maximum_messages=maximum_messages;
      m_maximum_bytes=maximum_bytes;
      if(maximum_messages<=0 || maximum_bytes<=0)
        {
         reason="TELEMETRY_CAPACITY_NOT_POSITIVE";
         return false;
        }
      if(!DatabaseReady(reason))
         return false;
      return m_database.ConfigureOutboxLimits(maximum_messages,maximum_bytes,reason);
     }

   bool RefreshStatus(V2TelemetryStatus &status,string &reason) const
     {
      status.Reset();
      status.enabled=m_enabled;
      status.local_only=true;
      status.maximum_messages=m_maximum_messages;
      status.maximum_bytes=m_maximum_bytes;
      reason="";
      if(!DatabaseReady(reason))
        {
         status.requires_manage_only=m_enabled;
         status.reason=reason;
         return false;
        }
      if(!m_database.GetOutboxStats(status.pending_messages,status.pending_bytes,reason))
        {
         status.requires_manage_only=m_enabled;
         status.reason=reason;
         return false;
        }
      const long warning_messages=(m_maximum_messages*8)/10;
      const long warning_bytes=(m_maximum_bytes*8)/10;
      status.degraded=(status.pending_messages>=warning_messages || status.pending_bytes>=warning_bytes);
      status.requires_manage_only=(status.pending_messages>=m_maximum_messages || status.pending_bytes>=m_maximum_bytes);
      if(status.requires_manage_only)
         status.reason="TELEMETRY_LOCAL_CAPACITY_EXHAUSTED";
      else if(status.degraded)
         status.reason="TELEMETRY_LOCAL_CAPACITY_WARNING";
      return true;
     }

   bool EnqueueReceipt(const V2Receipt &receipt,
                       const int priority,
                       const bool critical,
                       V2TelemetryStatus &status,
                       string &reason)
     {
      reason="";
      if(!m_enabled)
        {
         status.Reset();
         status.local_only=true;
         return true;
        }
      if(receipt.receipt_id=="" || receipt.canonical_payload=="")
        {
         reason="TELEMETRY_RECEIPT_NOT_FINALIZED";
         return false;
        }
      if(!RefreshStatus(status,reason))
         return false;
      if(status.requires_manage_only)
        {
         reason=status.reason;
         return false;
        }
      if(!m_database.EnqueueOutbox(receipt.receipt_id,
                                   V2ReceiptKindName(receipt.kind),
                                   receipt.canonical_payload,
                                   priority,
                                   critical,
                                   reason))
        {
         if(reason=="OUTBOX_CAPACITY_EXHAUSTED")
           {
            status.requires_manage_only=true;
            status.reason=reason;
           }
         return false;
        }
      return RefreshStatus(status,reason);
     }

   bool RecordHeartbeat(const string deployment_id,
                        const ENUM_V2_OPERATIONAL_STATE operational_state,
                        const long occurred_at_msc,
                        const string manifest_id,
                        V2TelemetryStatus &status,
                        string &reason)
     {
      reason="";
      if(!m_enabled)
        {
         status.Reset();
         status.local_only=true;
         return true;
        }
      string payload="{";
      payload+="\"schemaVersion\":\"goat2-heartbeat-v1\",";
      payload+="\"deploymentId\":"+V2JsonQuote(deployment_id)+",";
      payload+="\"occurredAtMsc\":"+IntegerToString(occurred_at_msc)+",";
      payload+="\"operationalState\":"+IntegerToString((int)operational_state)+",";
      payload+="\"manifestId\":"+V2JsonQuote(manifest_id);
      payload+="}";
      if(!m_database.UpsertHeartbeatOutbox(deployment_id,payload,reason))
        {
         if(reason=="OUTBOX_CAPACITY_EXHAUSTED")
           {
            status.requires_manage_only=true;
            status.reason=reason;
           }
         return false;
        }
      return RefreshStatus(status,reason);
     }

   bool LoadPending(const int maximum,V2OutboxRecord &records[],string &reason) const
     {
      if(!DatabaseReady(reason))
         return false;
      return m_database.LoadPendingOutbox(maximum,records,reason);
     }

   bool MarkDelivered(const string message_id,string &reason)
     {
      if(!DatabaseReady(reason))
         return false;
      return m_database.MarkOutboxDelivered(message_id,reason);
     }

   bool RecordAttemptFailure(const string message_id,
                             const long next_attempt_msc,
                             const string last_error,
                             string &reason)
     {
      if(!DatabaseReady(reason))
         return false;
      return m_database.RecordOutboxAttemptFailure(message_id,next_attempt_msc,last_error,reason);
     }

   bool Enabled(void) const { return m_enabled; }
   bool LocalOnly(void) const { return true; }
  };

#endif
