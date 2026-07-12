#ifndef GOAT_V2_CHART_HUD_MQH
#define GOAT_V2_CHART_HUD_MQH

#include <Canvas\Canvas.mqh>
#include "Domain.mqh"
#include "IntelligenceBus.mqh"
#include "OperationMode.mqh"

enum ENUM_V2_HUD_COMMAND
  {
   V2_HUD_NONE=0,
   V2_HUD_PAUSE_NEW_RISK=1,
   V2_HUD_REDUCE_ONLY=2,
   V2_HUD_CLOSE_SEQUENCE=3,
   V2_HUD_CLOSE_ALL=4
  };

struct V2HudSnapshot
  {
   ENUM_V2_OPERATIONAL_STATE operational_state;
   V2SequenceState           sequence;
   V2IntelligenceState       intelligence;
   double                    equity;
   double                    free_margin;
   double                    spread_points;
   bool                      new_risk_enabled;
   string                    build_id;
  };

class CV2ChartHUD
  {
private:
   CCanvas             m_canvas;
   string              m_name;
   bool                m_created;
   bool                m_dirty;
   bool                m_enabled;
   int                 m_width;
   int                 m_height;
   ENUM_V2_OPERATION_MODE m_operation_mode;
   ENUM_V2_HUD_COMMAND m_pending_command;
   uint                m_pending_at_ms;

   uint Argb(const color value,const uchar alpha=255) const
     {
      return ColorToARGB(value,alpha);
     }

   string OperationalName(const ENUM_V2_OPERATIONAL_STATE state) const
     {
      switch(state)
        {
         case V2_OP_NORMAL:              return "NORMAL";
         case V2_OP_DEGRADED:            return "DEGRADED";
         case V2_OP_MANAGE_ONLY:         return "MANAGE ONLY";
         case V2_OP_RECOVERY_QUARANTINE: return "RECOVERY QUARANTINE";
         case V2_OP_HALTED:              return "HALTED";
        }
      return "UNKNOWN";
     }

   void Button(const int x,const int y,const int width,const string label,const color fill)
     {
      m_canvas.FillRectangle(x,y,x+width,y+25,Argb(fill));
      m_canvas.TextOut(x+8,y+6,label,Argb(clrWhite));
     }

   void RenderModePlaceholder(void)
     {
      m_canvas.Erase(Argb(C'10,18,30',242));
      m_canvas.FillRectangle(0,0,m_width,34,Argb(C'15,39,68'));
      m_canvas.FontSet("Arial",13,FW_BOLD);
      m_canvas.TextOut(14,9,"GOAT2  V2.0",Argb(C'87,187,255'));

      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(14,52,"OPERATION MODE",Argb(C'132,154,180'));
      m_canvas.FontSet("Arial",11,FW_BOLD);
      m_canvas.TextOut(14,72,V2OperationModeName(m_operation_mode),Argb(C'87,187,255'));

      m_canvas.Line(14,102,m_width-14,102,Argb(C'48,65,86'));
      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(14,117,"DELIVERY STATUS",Argb(C'132,154,180'));
      m_canvas.FontSet("Arial",10,FW_BOLD);
      m_canvas.TextOut(14,139,StringFormat("PHASE %d - NOT YET BUILT",V2OperationModeDeliveryPhase(m_operation_mode)),Argb(C'255,184,77'));
      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(14,165,V2OperationModeStatus(m_operation_mode),Argb(C'220,225,232'));
      m_canvas.TextOut(14,191,"This surface is status-only in the V2.0 foundation.",Argb(C'150,165,185'));
      m_canvas.TextOut(14,209,"No execution manager or broker command path is active.",Argb(C'150,165,185'));

      m_canvas.FillRectangle(14,240,m_width-14,268,Argb(C'31,46,65'));
      m_canvas.FontSet("Arial",9,FW_BOLD);
      m_canvas.TextOut(24,248,"READ-ONLY PLACEHOLDER",Argb(C'255,184,77'));
      m_canvas.Update();
      m_dirty=false;
     }

public:
                     CV2ChartHUD(void)
     {
      m_name="GOAT2_V2_HUD";
      m_created=false;
      m_dirty=true;
      m_enabled=false;
      m_width=380;
      m_height=285;
      m_operation_mode=TRADING;
      m_pending_command=V2_HUD_NONE;
      m_pending_at_ms=0;
     }

   bool Initialize(const bool requested,string &reason)
     {
      return Initialize(requested,TRADING,reason);
     }

   bool Initialize(const bool requested,
                   const ENUM_V2_OPERATION_MODE operation_mode,
                   string &reason)
     {
      reason="";
      m_operation_mode=operation_mode;
      m_enabled=(requested && (!MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_VISUAL_MODE)));
      if(!m_enabled)
         return true;
      if(!m_canvas.CreateBitmapLabel(0,0,m_name,10,20,m_width,m_height,COLOR_FORMAT_ARGB_NORMALIZE))
        {
         reason="HUD_CANVAS_CREATE_FAILED";
         return false;
        }
      m_canvas.FontSet("Arial",10,FW_NORMAL);
      m_created=true;
      m_dirty=true;
      return true;
     }

   void MarkDirty(void) { m_dirty=true; }

   void RenderOperationStatus(void)
     {
      if(!m_enabled || !m_created || !m_dirty || m_operation_mode==TRADING)
         return;
      RenderModePlaceholder();
     }

   void Render(const V2HudSnapshot &snapshot)
     {
      if(!m_enabled || !m_created || !m_dirty)
         return;
      if(m_operation_mode!=TRADING)
        {
         RenderModePlaceholder();
         return;
        }
      m_canvas.Erase(Argb(C'10,18,30',242));
      m_canvas.FillRectangle(0,0,m_width,34,Argb(C'15,39,68'));
      m_canvas.FontSet("Arial",13,FW_BOLD);
      m_canvas.TextOut(14,9,"GOAT2  V2.0",Argb(C'87,187,255'));
      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(250,11,snapshot.build_id,Argb(C'150,165,185'));

      m_canvas.TextOut(14,48,"SAFETY",Argb(C'132,154,180'));
      m_canvas.FontSet("Arial",11,FW_BOLD);
      color state_color=(snapshot.operational_state==V2_OP_NORMAL ? C'52,199,129' : (snapshot.operational_state==V2_OP_MANAGE_ONLY ? C'255,184,77' : C'255,96,96'));
      m_canvas.TextOut(14,66,OperationalName(snapshot.operational_state),Argb(state_color));
      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(180,49,StringFormat("Spread %.1f pt",snapshot.spread_points),Argb(C'220,225,232'));
      m_canvas.TextOut(180,66,StringFormat("Free margin %.2f",snapshot.free_margin),Argb(C'220,225,232'));

      m_canvas.Line(14,91,m_width-14,91,Argb(C'48,65,86'));
      m_canvas.TextOut(14,103,"SEQUENCE",Argb(C'132,154,180'));
      string direction=(snapshot.sequence.direction==V2_DIR_LONG ? "LONG" : (snapshot.sequence.direction==V2_DIR_SHORT ? "SHORT" : "IDLE"));
      m_canvas.FontSet("Arial",11,FW_BOLD);
      m_canvas.TextOut(14,121,direction,Argb(C'87,187,255'));
      m_canvas.FontSet("Arial",9,FW_NORMAL);
      m_canvas.TextOut(95,122,StringFormat("Levels %d/%d",snapshot.sequence.level_count,snapshot.sequence.max_levels),Argb(C'220,225,232'));
      m_canvas.TextOut(210,122,StringFormat("Lots %.2f",snapshot.sequence.standing_volume),Argb(C'220,225,232'));
      double utilization=(snapshot.sequence.mlps_budget>0.0 ? snapshot.sequence.mlps_used/snapshot.sequence.mlps_budget : 0.0);
      utilization=MathMax(0.0,MathMin(1.0,utilization));
      m_canvas.FillRectangle(14,145,m_width-14,160,Argb(C'31,46,65'));
      m_canvas.FillRectangle(14,145,14+(int)((m_width-28)*utilization),160,Argb(utilization<0.75 ? C'52,199,129' : C'255,96,96'));
      m_canvas.TextOut(14,166,StringFormat("MLPS utilization %.1f%%",utilization*100.0),Argb(C'220,225,232'));

      m_canvas.Line(14,190,m_width-14,190,Argb(C'48,65,86'));
      m_canvas.TextOut(14,201,"INTELLIGENCE",Argb(C'132,154,180'));
      m_canvas.TextOut(14,219,(snapshot.intelligence.valid ? snapshot.intelligence.actionability : "NO STATE (PHASE 1)"),Argb(C'220,225,232'));

      Button(14,247,78,"PAUSE",C'44,78,112');
      Button(99,247,82,"REDUCE",C'78,72,41');
      Button(188,247,82,"CLOSE",C'112,54,54');
      Button(277,247,89,"CLOSE ALL",C'125,38,38');
      m_canvas.Update();
      m_dirty=false;
     }

   ENUM_V2_HUD_COMMAND OnChartEvent(const int id,const long lparam,const double dparam)
     {
      if(!m_enabled || m_operation_mode!=TRADING || id!=CHARTEVENT_CLICK)
         return V2_HUD_NONE;
      int x=(int)lparam-10;
      int y=(int)dparam-20;
      if(y<247 || y>272)
         return V2_HUD_NONE;
      ENUM_V2_HUD_COMMAND command=V2_HUD_NONE;
      if(x>=14 && x<=92) command=V2_HUD_PAUSE_NEW_RISK;
      else if(x>=99 && x<=181) command=V2_HUD_REDUCE_ONLY;
      else if(x>=188 && x<=270) command=V2_HUD_CLOSE_SEQUENCE;
      else if(x>=277 && x<=366) command=V2_HUD_CLOSE_ALL;
      if(command==V2_HUD_NONE)
         return command;
      uint now=GetTickCount();
      if(command==m_pending_command && now-m_pending_at_ms<=3000)
        {
         m_pending_command=V2_HUD_NONE;
         m_pending_at_ms=0;
         return command;
        }
      m_pending_command=command;
      m_pending_at_ms=now;
      return V2_HUD_NONE;
     }

   void Shutdown(void)
     {
      if(m_created)
         m_canvas.Destroy();
      m_created=false;
     }
  };

#endif
