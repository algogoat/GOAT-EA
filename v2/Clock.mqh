#ifndef GOAT_V2_CLOCK_MQH
#define GOAT_V2_CLOCK_MQH

// GOAT2 persists causal/audit timestamps in UTC.  Broker-history APIs still
// receive server time at their call sites because their selection contract is
// broker-time based.  In the Strategy Tester MetaQuotes defines TimeGMT() as
// the simulated server clock, which preserves causal replay without lookahead.
datetime V2UtcNow(void)
  {
   const datetime utc=TimeGMT();
   if(utc>0)
      return utc;
   const datetime local=TimeLocal();
   return(local>0 ? local+(datetime)TimeGMTOffset() : 0);
  }

long V2UtcNowMsc(void)
  {
   return (long)V2UtcNow()*1000;
  }

long V2ServerUtcOffsetSeconds(void)
  {
   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION))
      return 0;
   const datetime server=TimeTradeServer();
   const datetime utc=V2UtcNow();
   if(server<=0 || utc<=0)
      return 0;
   long offset=(long)server-(long)utc;
   if(MathAbs((double)offset)>86400.0)
      return 0;
   // Remove the one-second estimation jitter documented for TimeTradeServer.
   offset=(offset>=0 ? ((offset+30)/60)*60 : ((offset-30)/60)*60);
   return offset;
  }

long V2ServerTimeToUtcMsc(const long server_time_msc)
  {
   if(server_time_msc<=0)
      return 0;
   return server_time_msc-V2ServerUtcOffsetSeconds()*1000;
  }

datetime V2UtcTimeToServer(const datetime utc_time)
  {
   if(utc_time<=0)
      return 0;
   return utc_time+(datetime)V2ServerUtcOffsetSeconds();
  }

#endif
