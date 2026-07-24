#property script_show_inputs

#include "..\EALegacyWireContract.mqh"

int g_failures=0;

void Check(const bool condition,const string name)
  {
   if(condition)
      Print("ok - "+name);
   else
     {
      Print("not ok - "+name);
      g_failures++;
     }
  }

string Body(const string server_time,const string rows,const string status="success")
  {
   return "{\"server_time\":\""+server_time+"\",\"status\":\""+status+"\",\"data\":["+rows+"]}";
  }

string Row(const string asset,const string timestamp,const string packed)
  {
   return "{\"asset\":\""+asset+"\",\"timestamp\":\""+timestamp+"\",\"sentiment\":\""+packed+"\"}";
  }

void ExpectUnavailable(const string body,
                       const string reason,
                       const long request_elapsed_ms=1000)
  {
   SEALegacyBiasResponse response;
   bool accepted=EAEvaluateLegacyBiasResponse(body,"EURUSD",request_elapsed_ms,response);
   Check(!accepted && !response.available && response.reason==reason,
         "unavailable "+reason);
  }

void OnStart()
  {
   string first_timestamp="2026-07-18T09:15:00.000Z";
   string first_packed="57.0000 2026-07-18T10:20:00.000Z";
   string first_row=Row("EURUSD",first_timestamp,first_packed);
   string accepted_body=Body("2026-07-18T10:00:00.000Z",first_row);

   SEALegacyBiasResponse accepted;
   Check(EAEvaluateLegacyBiasResponse(accepted_body,"EURUSD",1000,accepted),
         "valid response accepted");
   Check(accepted.available && ArraySize(accepted.rows)==1,
         "valid response exposes one row");
   Check(accepted.rows[0].score==57.0,
         "valid response preserves score");
   Check(accepted.authoritative_now_ms==accepted.server_time_ms+1000,
         "request duration advances authoritative time");

   ExpectUnavailable("{not-json","ENVELOPE_INVALID");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",""),"DATA_EMPTY");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",first_row,"error"),
                     "ENVELOPE_STATUS_NOT_SUCCESS");
   ExpectUnavailable(Body("2026-02-30T10:00:00.000Z",first_row),
                     "SERVER_TIME_INVALID");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",
                          Row("GBPUSD",first_timestamp,first_packed)),
                     "ROW_ASSET_MISMATCH");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",
                          Row("EURUSD",first_timestamp,
                              "101.0000 2026-07-18T10:20:00.000Z")),
                     "ROW_SENTIMENT_INVALID");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",
                          Row("EURUSD",first_timestamp,
                              "57.0000 2026-07-18T10:19:59.000Z")),
                     "ROW_VALIDITY_WINDOW_INVALID");
   ExpectUnavailable(Body("2026-07-18T10:30:00.000Z",first_row),
                     "VALID_UNTIL_EXPIRED");

   string later_row=Row("EURUSD","2026-07-18T09:30:00.000Z",
                        "20.0000 2026-07-18T10:35:00.000Z");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",later_row+","+first_row),
                     "ROWS_NOT_STRICTLY_ASCENDING");
   string future_row=Row("EURUSD","2026-07-18T10:00:02.000Z",
                         "57.0000 2026-07-18T11:05:02.000Z");
   ExpectUnavailable(Body("2026-07-18T10:00:00.000Z",future_row),
                     "ROW_FROM_FUTURE");

   if(g_failures==0) Print("EA legacy wire contract runtime fixtures passed.");
   else Print("EA legacy wire contract runtime fixtures failed: "+(string)g_failures);
  }
