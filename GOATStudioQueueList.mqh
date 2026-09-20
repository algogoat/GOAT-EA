#ifndef GOAT_STUDIO_QUEUE_LIST_MQH
#define GOAT_STUDIO_QUEUE_LIST_MQH
// Studio-only sizing; the standard ControlsPlus list keeps its creation-time rows.
class CGoatStudioQueueList : public CListView
  {
public:
   virtual bool Create(const long chart,const string name,const int subwin,const int x1,const int y1,const int x2,const int y2)
     {
      // Containers retain pointers to row objects. Never resize that object array
      // after registration: relocation invalidates event/layout references.
      int original_height=y2-y1;
      if(!CListView::Create(chart,name,subwin,x1,y1,x2,y1+256*m_item_height)) return false;
      if(!Height(original_height)) return false;
      return FitRows(m_item_height,9);
     }
   bool FitRows(const int row_height,const int font_size)
     {
      if(row_height<1 || ArraySize(m_rows)==0) return false;
      m_item_height=row_height;
      int wanted=(int)MathMin(ArraySize(m_rows),MathMax(1,(Height()-2*CONTROLS_BORDER_WIDTH)/row_height));
      m_total_view=wanted;
      m_height_variable=false;
      int maximum=(int)MathMax(0,m_strings.Total()-m_total_view);
      m_offset=(int)MathMin(m_offset,maximum);
      m_scroll_v.MaxPos(maximum);
      m_scroll_v.CurrPos(m_offset);
      if(!VScrolled(maximum>0)) return false;
      for(int i=0;i<ArraySize(m_rows);i++)
        {
         m_rows[i].Move(Left()+CONTROLS_BORDER_WIDTH,Top()+CONTROLS_BORDER_WIDTH+i*row_height);
         m_rows[i].Height(row_height);
         m_rows[i].FontSize(font_size);
         if(i<wanted) m_rows[i].Show(); else m_rows[i].Hide();
        }
      if(VScrolled()) OnVScrollShow(); else OnVScrollHide();
      return Redraw();
     }
  };
#endif
