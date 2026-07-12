#ifndef GOAT_V2_CHART_OVERLAY_MQH
#define GOAT_V2_CHART_OVERLAY_MQH

#include "Domain.mqh"
#include "IntelligenceBus.mqh"

class CV2ChartOverlay
  {
private:
   string m_prefix;
   bool   m_enabled;

   void SetLine(const string suffix,const double price,const color line_color,const ENUM_LINE_STYLE style)
     {
      string name=m_prefix+suffix;
      if(price<=0.0)
        {
         ObjectDelete(0,name);
         return;
        }
      if(ObjectFind(0,name)<0)
         ObjectCreate(0,name,OBJ_HLINE,0,0,price);
      ObjectSetDouble(0,name,OBJPROP_PRICE,price);
      ObjectSetInteger(0,name,OBJPROP_COLOR,line_color);
      ObjectSetInteger(0,name,OBJPROP_STYLE,style);
      ObjectSetInteger(0,name,OBJPROP_WIDTH,1);
      ObjectSetInteger(0,name,OBJPROP_BACK,true);
      ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
     }

public:
                     CV2ChartOverlay(void)
     {
      m_prefix="GOAT2_OV_";
      m_enabled=false;
     }

   bool Initialize(const bool requested)
     {
      m_enabled=(requested && (!MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_VISUAL_MODE)));
      return true;
     }

   void UpdateIntelligence(const V2IntelligenceState &state)
     {
      if(!m_enabled)
         return;
      SetLine("INVALIDATION",(state.valid ? state.entry_invalidation : 0.0),C'255,96,96',STYLE_DASH);
      SetLine("OBJECTIVE",(state.valid ? state.objective : 0.0),C'52,199,129',STYLE_DASH);
      SetLine("ZONE_LO",(state.valid ? state.zone_lo : 0.0),C'87,187,255',STYLE_DOT);
      SetLine("ZONE_HI",(state.valid ? state.zone_hi : 0.0),C'87,187,255',STYLE_DOT);
     }

   void UpdateSequence(const V2SequenceState &sequence,const double mlps_boundary,const double retrace_price)
     {
      if(!m_enabled)
         return;
      SetLine("MLPS",mlps_boundary,C'255,96,96',STYLE_SOLID);
      SetLine("RETRACE",retrace_price,C'255,184,77',STYLE_DOT);
     }

   void Shutdown(void)
     {
      ObjectsDeleteAll(0,m_prefix);
     }
  };

#endif
