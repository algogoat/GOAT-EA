#ifndef GOAT_V2_SCHEDULER_MQH
#define GOAT_V2_SCHEDULER_MQH

enum ENUM_V2_WORK_KIND
  {
   V2_WORK_DRAIN_TRANSACTIONS=0,
   V2_WORK_PROTECTIVE_MANAGEMENT=1,
   V2_WORK_SEQUENCE_MANAGEMENT=2,
   V2_WORK_SCHEDULED_EXITS=3,
   V2_WORK_NEW_ENTRY=4,
   V2_WORK_HOUSEKEEPING=5
  };

struct V2ScheduledWork
  {
   ENUM_V2_WORK_KIND kind;
   string            symbol;
   long              due_time_msc;
   long              sequence_number;
  };

class CV2Scheduler
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_signal_timeframe;
   MqlTick         m_latest_tick;
   datetime        m_last_signal_bar;
   long            m_work_sequence;
   bool            m_tick_ready;
   bool            m_new_bar_due;
   bool            m_housekeeping_due;

   void AddWork(V2ScheduledWork &batch[],const ENUM_V2_WORK_KIND kind,const long due_time_msc)
     {
      int index=ArraySize(batch);
      ArrayResize(batch,index+1);
      batch[index].kind=kind;
      batch[index].symbol=m_symbol;
      batch[index].due_time_msc=due_time_msc;
      batch[index].sequence_number=++m_work_sequence;
     }

public:
                     CV2Scheduler(void)
     {
      m_symbol="";
      m_signal_timeframe=PERIOD_CURRENT;
      ZeroMemory(m_latest_tick);
      m_last_signal_bar=0;
      m_work_sequence=0;
      m_tick_ready=false;
      m_new_bar_due=false;
      m_housekeeping_due=false;
     }

   bool Initialize(const string symbol,const ENUM_TIMEFRAMES signal_timeframe,string &reason)
     {
      reason="";
      if(symbol=="")
        {
         reason="SCHEDULER_SYMBOL_EMPTY";
         return false;
        }
      m_symbol=symbol;
      m_signal_timeframe=signal_timeframe;
      m_last_signal_bar=iTime(symbol,signal_timeframe,0);
      return true;
     }

   void OnChartTick(const MqlTick &tick)
     {
      m_latest_tick=tick;
      m_tick_ready=true;
      datetime current_bar=iTime(m_symbol,m_signal_timeframe,0);
      if(current_bar>0 && current_bar!=m_last_signal_bar)
        {
         m_last_signal_bar=current_bar;
         m_new_bar_due=true;
        }
     }

   void OnTimer(void)
     {
      m_housekeeping_due=true;
     }

   int CollectDueWork(V2ScheduledWork &batch[],const int max_items)
     {
      ArrayResize(batch,0);
      if(max_items<=0)
         return 0;
      const long due=(m_tick_ready ? m_latest_tick.time_msc : (long)TimeCurrent()*1000);
      AddWork(batch,V2_WORK_DRAIN_TRANSACTIONS,due);
      if(ArraySize(batch)<max_items && m_tick_ready) AddWork(batch,V2_WORK_PROTECTIVE_MANAGEMENT,due);
      if(ArraySize(batch)<max_items && m_tick_ready) AddWork(batch,V2_WORK_SEQUENCE_MANAGEMENT,due);
      if(ArraySize(batch)<max_items && m_tick_ready) AddWork(batch,V2_WORK_SCHEDULED_EXITS,due);
      if(ArraySize(batch)<max_items && m_new_bar_due)
        {
         AddWork(batch,V2_WORK_NEW_ENTRY,due);
         m_new_bar_due=false;
        }
      if(ArraySize(batch)<max_items && m_housekeeping_due)
        {
         AddWork(batch,V2_WORK_HOUSEKEEPING,due);
         m_housekeeping_due=false;
        }
      return ArraySize(batch);
     }

   bool LatestTick(MqlTick &tick) const
     {
      if(!m_tick_ready)
         return false;
      tick=m_latest_tick;
      return true;
     }
  };

#endif
